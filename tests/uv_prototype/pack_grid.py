#!/usr/bin/env python3
"""
Automated UV Packing Prototype (Phase 3)
MSFS Blender Add-ons / Flight Sim Studio

Pipeline:
1. Load islands per material (texture set) from proto3 unwrap outputs.
2. Density scaling: scale each island so UV area / 3D area = target_density * density_factor.
3. Directional constraint: directional objects rotate only by 0 or 180 degrees.
4. Stacking units: shared mesh data & Mirror islands packed as single units.
5. Coarse-to-fine grid packing:
   - Rasterize islands with half-margin dilation.
   - Large concave charts placed via 2D FFT convolution for optimal cavity nesting.
   - Small & medium islands placed via skyline with cavity filling.
6. Overflow handling:
   - 'tiles': fill tile 0, then tile 1, etc.
   - 'scale': uniform shrink to fit in tile 0, reporting density lost.
7. Metrics:
   - Area share of square
   - Minimum island distance & margin violations
   - Overlaps (excluding stacking units)
   - Texel density deviation
   - Directional rotation adherence
   - Mip-level merge threshold (levels 1-4)
   - Texture memory estimation (BC7 3 maps + mips)
   - Run time
"""

import sys, os, time, json, argparse, subprocess
import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import binary_dilation
from scipy.signal import fftconvolve
from scipy.spatial import cKDTree
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)
import uvmetrics as um

# Default material slot mapping for E2 cockpit test objects
DEFAULT_MAT_MAP = {
    'W_@MERGE_PEDESTAL_SHELL': ['Cockpit_STD'],
    'W_AUDIO_L_VOLUME_KNOB': ['None'],
    'W_COCKPIT_SHELL_FLOOR': ['checker_material_4096x4096'],
    'W_COCKPIT_SHELL_L': ['checker_material_4096x4096', 'Rear_doors'],
    'W_LEVER_FLAP_LOCK': ['None'],
    'W_OVERHEAD_SHELL': ['Cockpit_STD'],
    'W_TRIM_PANEL': ['Cockpit_STD', 'Rear_doors']
}

BLENDER_EXE = r'G:\e-jets-e2\tools\blender\blender.exe'


def load_texture_sets(results_dir, mat_map=None):
    """Load all objects and group triangles/islands by material name."""
    if mat_map is None:
        mat_map = DEFAULT_MAT_MAP

    import glob
    npz_files = sorted(glob.glob(os.path.join(results_dir, 'W_*__proto3.npz')))
    if not npz_files:
        raise RuntimeError(f"No W_*__proto3.npz files found in {results_dir}")

    # Map materials -> list of island dicts
    sets = {}

    for f in npz_files:
        d = np.load(f)
        P = d['P']; T = d['T']; UV = d['UV']; mat = d['mat']
        base = os.path.basename(f).replace('__proto3.npz', '')
        slots = mat_map.get(base, ['Default'])
        clean_obj = base.replace('W_', '')

        for s_idx in np.unique(mat):
            mname = slots[s_idx] if s_idx < len(slots) else f'Slot_{s_idx}'
            if mname is None:
                mname = 'None'

            tri_mask = (mat == s_idx)
            sub_T = T[tri_mask]
            sub_UV = UV[tri_mask]
            nt = len(sub_T)
            if nt == 0:
                continue

            # Extract connected UV islands for this material
            key = np.concatenate([sub_T.reshape(-1, 1).astype(np.float64), sub_UV.reshape(-1, 2)], 1)
            _, sid = np.unique(key, axis=0, return_inverse=True); sid = sid.reshape(-1, 3)
            es = np.sort(np.stack([sid, np.roll(sid, -1, 1)], -1).reshape(-1, 2), 1)
            tri_of = np.repeat(np.arange(nt), 3)
            _, ues = np.unique(es, axis=0, return_inverse=True)
            order = np.argsort(ues, kind='stable'); u = ues[order]; t = tri_of[order]
            same = u[1:] == u[:-1]
            g = coo_matrix((np.ones(same.sum()), (t[:-1][same], t[1:][same])), shape=(nt, nt))
            n_isl, isl = connected_components(g, directed=False)

            P3 = P[sub_T]
            a3 = np.bincount(isl, um.tri_area3(P3), n_isl)
            a2 = np.bincount(isl, np.abs(um.tri_area2_signed(sub_UV)), n_isl)

            if mname not in sets:
                sets[mname] = []

            for i in range(n_isl):
                m = (isl == i)
                sets[mname].append({
                    'obj': clean_obj,
                    'orig_uv': sub_UV[m].copy(),
                    'P3': P3[m],
                    'a3': float(a3[i]),
                    'a2': float(a2[i]),
                    'stack_id': None # None means unique
                })

    return sets


def scale_islands(islands, resolution, ppm, density_factors):
    """Scale each island according to target density and object factor."""
    scaled = []
    for idx, isl in enumerate(islands):
        obj_name = isl['obj']
        factor = density_factors.get(obj_name, 1.0)
        a3 = isl['a3']
        a2 = isl['a2']
        target_d = ((ppm / resolution) ** 2) * factor
        uv = isl['orig_uv'].copy()

        if a3 > 0 and a2 > 0:
            s = np.sqrt((a3 * target_d) / a2)
            c = uv.reshape(-1, 2).mean(0)
            uv = (uv - c) * s
        else:
            uv = uv - uv.reshape(-1, 2).mean(0)

        scaled.append({
            'id': idx,
            'obj': obj_name,
            'orig_uv': isl.get('orig_uv', uv),
            'uv': uv, # centered at (0, 0)
            'a3': a3,
            'a2': float(np.abs(um.tri_area2_signed(uv)).sum()),
            'target_d': target_d,
            'density_factor': factor,
            'stack_id': isl.get('stack_id', None)
        })

    return scaled


def coarse_mask(mask_fine, S):
    """Max-pool a fine mask into S x S cells: a cell is occupied if any of its pixels is. Islands are placed at cell
    origins, so the fine mask's pixel (y, x) lands exactly in coarse cell (y // S, x // S): no pixel can be lost."""
    h, w = mask_fine.shape
    hc, wc = -(-h // S), -(-w // S)
    padded = np.zeros((hc * S, wc * S), dtype=bool)
    padded[:h, :w] = mask_fine
    return padded.reshape(hc, S, wc, S).any(axis=(1, 3)).astype(np.uint8)


def rasterize_island(uv_triangles, angle, R_res, r_margin):
    """Rasterize 2D island triangles into a binary mask with dilation."""
    ca, sa = np.cos(angle), np.sin(angle)
    rot_m = np.array([[ca, -sa], [sa, ca]])
    rot_uv = uv_triangles @ rot_m.T

    pts = rot_uv.reshape(-1, 2) * R_res
    pmin = pts.min(0); pmax = pts.max(0)

    w_px = int(np.ceil(pmax[0] - pmin[0])) + 2 * r_margin + 2
    h_px = int(np.ceil(pmax[1] - pmin[1])) + 2 * r_margin + 2

    im = Image.new('1', (w_px, h_px), 0)
    draw = ImageDraw.Draw(im)
    offset = -pmin + r_margin + 1
    for tri in rot_uv * R_res:
        poly = [(p[0] + offset[0], p[1] + offset[1]) for p in tri]
        draw.polygon(poly, fill=1)
    mask = np.array(im)
    if r_margin > 0:
        mask = binary_dilation(mask, iterations=r_margin)

    return rot_uv, mask, offset, (w_px, h_px)


def pack_grid(islands, resolution=4096, margin_px=8, overflow_mode='tiles',
              directional_objs=None, coarse_step=None, max_tiles=16):
    """
    Coarse-to-fine grid packer.
    Returns:
        packed_uvs: list of (F, 3, 2) arrays in atlas UV space
        tile_indices: list of int tile indices
        stats: dict of execution details
    """
    if directional_objs is None:
        directional_objs = set()
    # Work on copies: the caller's islands are reused by the other packers and must keep their scale
    islands = [dict(isl, uv=isl['uv'].copy()) for isl in islands]

    t_start = time.perf_counter()

    R = resolution
    M = margin_px
    r_dil = -(-M // 2) + 1

    if coarse_step is None:
        # Coarse step: choose so coarse grid is approx 1024 x 1024
        coarse_step = max(2, R // 1024)
    S = coarse_step
    GC_W = R // S
    GC_H = R // S

    # Group by stacking units if any
    # Stack units share the same placement
    stack_groups = {}
    standalone_islands = []

    for isl in islands:
        sid = isl.get('stack_id')
        if sid is not None:
            if sid not in stack_groups:
                stack_groups[sid] = []
            stack_groups[sid].append(isl)
        else:
            standalone_islands.append(isl)

    # Unit list to place: representative island for each stack group + standalone
    pack_units = []
    for sid, group in stack_groups.items():
        pack_units.append({
            'rep': group[0],
            'members': group,
            'is_stack': True,
            'a2': group[0]['a2']
        })
    for isl in standalone_islands:
        pack_units.append({
            'rep': isl,
            'members': [isl],
            'is_stack': False,
            'a2': isl['a2']
        })

    # Sort units largest first
    pack_units.sort(key=lambda u: u['a2'], reverse=True)

    # Tiles state
    tiles = []

    def new_tile():
        return {
            'grid_coarse': np.zeros((GC_H, GC_W), dtype=np.uint8),
            'skyline': np.zeros(GC_W, dtype=np.int32),
            'used_w': 0,
            'used_h': 0,
            'placed_items': []
        }

    current_tile = new_tile()
    tiles.append(current_tile)

    # Placement threshold: top N large units use FFT convolution for optimal cavity nesting
    N_FFT = min(25, max(5, len(pack_units) // 20))

    scale_loss = 0.0

    # Pre-check: an island larger than a tile forces ONE uniform scale for the whole set (decision 13: density goes
    # below the target only uniformly, and is reported), never a shrink of that island alone
    scale_needed = 1.0
    for u in pack_units:
        pts = u['rep']['uv'].reshape(-1, 2) * R
        p_span = pts.max(0) - pts.min(0)
        longest = max(p_span) + 2 * r_dil + 2 + S
        if longest > R:
            scale_needed = min(scale_needed, (R - 2 * r_dil - 2 - S) / max(p_span) * 0.98)
    if scale_needed < 1.0:
        for u in pack_units:
            for m in u['members']:
                m['uv'] = m['uv'] * scale_needed
        scale_loss = 1.0 - scale_needed ** 2

    for u_idx, unit in enumerate(pack_units):
        rep = unit['rep']
        is_dir = rep['obj'] in directional_objs
        angles = [0.0, np.pi] if is_dir else [0.0, np.pi/2, np.pi, 3*np.pi/2]

        placed = False
        tile_idx = len(tiles) - 1

        while not placed:
            tile = tiles[tile_idx]
            grid_coarse = tile['grid_coarse']
            skyline = tile['skyline']
            used_w = tile['used_w']
            used_h = tile['used_h']

            best_score = float('inf')
            best_pos = None
            best_info = None

            use_fft = (u_idx < N_FFT) and (len(tile['placed_items']) > 0)

            if use_fft:
                # Macro stage: 2D FFT convolution
                for ang in angles:
                    rot_uv, mask_fine, offset_fine, (w_f, h_f) = rasterize_island(rep['uv'], ang, R, r_dil)
                    mask_c = coarse_mask(mask_fine, S)
                    hc, wc = mask_c.shape
                    if hc > GC_H or wc > GC_W:
                        continue

                    kernel = mask_c[::-1, ::-1].astype(np.float32)
                    conv = fftconvolve(grid_coarse.astype(np.float32), kernel, mode='valid')
                    vy, vx = np.nonzero(conv < 0.5)
                    if len(vy) == 0:
                        continue
                    nh = np.maximum(used_h, vy + hc)
                    nw = np.maximum(used_w, vx + wc)
                    scores = nh.astype(np.float64) * nw.astype(np.float64) + 0.01 * (vy + vx)
                    b = np.argmin(scores)
                    if scores[b] < best_score:
                        best_score = scores[b]
                        best_pos = (vy[b], vx[b])
                        best_info = {
                            'ang': ang, 'rot_uv': rot_uv, 'mask_c': mask_c,
                            'hc': hc, 'wc': wc, 'offset_fine': offset_fine,
                            'w_f': w_f, 'h_f': h_f
                        }
            else:
                # Micro / standard stage: Skyline search with candidate steps
                for ang in angles:
                    rot_uv, mask_fine, offset_fine, (w_f, h_f) = rasterize_island(rep['uv'], ang, R, r_dil)
                    mask_c = coarse_mask(mask_fine, S)
                    hc, wc = mask_c.shape
                    if hc > GC_H or wc > GC_W:
                        continue

                    step_x = max(1, min(4, wc // 2))
                    for x in range(0, GC_W - wc + 1, step_x):
                        y = int(skyline[x : x + wc].max())
                        if y + hc <= GC_H:
                            if not np.any(grid_coarse[y : y + hc, x : x + wc] & mask_c):
                                nh = max(used_h, y + hc)
                                nw = max(used_w, x + wc)
                                sc = nh * nw + 0.01 * (y + x)
                                if sc < best_score:
                                    best_score = sc
                                    best_pos = (y, x)
                                    best_info = {
                                        'ang': ang, 'rot_uv': rot_uv, 'mask_c': mask_c,
                                        'hc': hc, 'wc': wc, 'offset_fine': offset_fine,
                                        'w_f': w_f, 'h_f': h_f
                                    }

            if best_pos is not None:
                # Successfully placed in current tile
                by, bx = best_pos
                hc, wc = best_info['hc'], best_info['wc']
                grid_coarse[by : by + hc, bx : bx + wc] |= best_info['mask_c']
                for x in range(bx, bx + wc):
                    col = np.nonzero(grid_coarse[:, x])[0]
                    skyline[x] = int(col.max() + 1) if len(col) else 0

                tile['used_h'] = max(used_h, by + hc)
                tile['used_w'] = max(used_w, bx + wc)

                # Fine placement position: (bx * S, by * S)
                fine_x = bx * S
                fine_y = by * S

                # Compute final UV coordinates for all members of the unit
                for m in unit['members']:
                    # Apply rotation and translation to member's original UV
                    ca, sa = np.cos(best_info['ang']), np.sin(best_info['ang'])
                    rot_m = np.array([[ca, -sa], [sa, ca]])
                    m_uv_rot = m['uv'] @ rot_m.T
                    # Pixel coordinates
                    pix = m_uv_rot * R + best_info['offset_fine'] + np.array([fine_x, fine_y])
                    # In atlas UV units [0, 1] + tile offset
                    final_uv = pix / R
                    # Add tile offset horizontally
                    final_uv[:, :, 0] += tile_idx

                    tile['placed_items'].append({
                        'island_id': m['id'],
                        'final_uv': final_uv,
                        'tile': tile_idx,
                        'angle': best_info['ang']
                    })

                placed = True
            else:
                # Does not fit in current tile!
                if overflow_mode == 'tiles' and len(tile['placed_items']) > 0 and len(tiles) < max_tiles:
                    # Start new tile
                    tiles.append(new_tile())
                    tile_idx = len(tiles) - 1
                elif max_tiles == 1:
                    return None, None, {'fits': False}
                else:
                    # In 'scale' mode or island exceeds empty tile: place on tile extending bounds
                    rot_uv, mask_fine, offset_fine, (w_f, h_f) = rasterize_island(rep['uv'], 0.0, R, r_dil)
                    hc = int(np.ceil(h_f / S))
                    wc = int(np.ceil(w_f / S))
                    x = 0
                    y = int(skyline[:min(wc, len(skyline))].max()) if len(skyline) else used_h
                    fine_x = x * S
                    fine_y = y * S
                    for m in unit['members']:
                        pix = m['uv'] * R + offset_fine + np.array([fine_x, fine_y])
                        final_uv = pix / R
                        final_uv[:, :, 0] += tile_idx
                        tile['placed_items'].append({
                            'island_id': m['id'],
                            'final_uv': final_uv,
                            'tile': tile_idx,
                            'angle': 0.0
                        })
                    tile['used_h'] = max(used_h, y + hc)
                    tile['used_w'] = max(used_w, x + wc)
                    placed = True

    # Post-process overflow scaling if any tile exceeds [0, 1]
    for t_idx, tile in enumerate(tiles):
        if not tile['placed_items']:
            continue
        tile_uvs = np.concatenate([it['final_uv'].reshape(-1, 2) for it in tile['placed_items']], 0)
        rel_u = tile_uvs[:, 0] - t_idx
        rel_v = tile_uvs[:, 1]
        max_u = rel_u.max()
        max_v = rel_v.max()
        if max_u > 1.0 or max_v > 1.0:
            shrink = 1.0 / max(max_u, max_v)
            scale_loss = max(scale_loss, 1.0 - (shrink ** 2))
            for it in tile['placed_items']:
                it['final_uv'][:, :, 0] = (it['final_uv'][:, :, 0] - t_idx) * shrink + t_idx
                it['final_uv'][:, :, 1] = it['final_uv'][:, :, 1] * shrink

    t_pack = time.perf_counter() - t_start

    # Collect outputs in original island order
    all_placed = []
    for t_idx, tile in enumerate(tiles):
        all_placed.extend(tile['placed_items'])
    all_placed.sort(key=lambda x: x['island_id'])

    final_uvs = [it['final_uv'] for it in all_placed]
    tile_idxs = [it['tile'] for it in all_placed]
    rot_angles = [it['angle'] for it in all_placed]

    stats = {
        'run_time_s': t_pack,
        'tiles_count': len(tiles),
        'scale_loss': scale_loss,
        'rot_angles': rot_angles,
        'tile_bounds': [(t['used_w'] * S, t['used_h'] * S) for t in tiles]
    }

    return final_uvs, tile_idxs, stats


def pack_grid_one_tile(islands, resolution, margin_px, directional_objs, steps=0.96):
    """Largest uniform scale (<= 1) at which the grid packer fits the whole set into one tile, so its density can be
    compared with Blender's Pack Islands (scale=True), which always packs into one square. Starts from an area bound
    and shrinks by `steps` until the set fits. Returns (final_uvs, stats) with stats['scale'] the uniform factor."""
    import copy
    area = sum(isl['a2'] for isl in islands)
    # Not capped at 1: Blender (scale=True) also scales up to fill the square, so both report the largest scale
    s = (0.85 / max(area, 1e-12)) ** 0.5
    t0 = time.perf_counter()
    tries = 0
    while True:
        tries += 1
        trial = copy.deepcopy(islands)
        for isl in trial:
            isl['uv'] = isl['uv'] * s
            isl['a2'] = isl['a2'] * s * s
        uvs, _, stats = pack_grid(trial, resolution=resolution, margin_px=margin_px, overflow_mode='tiles',
                                  directional_objs=directional_objs, max_tiles=1)
        if uvs is not None and stats['tiles_count'] == 1 and stats['scale_loss'] == 0.0:
            stats['scale'] = s
            stats['tries'] = tries
            stats['run_time_s'] = time.perf_counter() - t0
            return uvs, stats
        s *= steps


def sat_tri_tri(TA, TB, eps=1e-6):
    """Vectorized 2D Separating Axis Theorem for pairs of triangles."""
    if len(TA) == 0:
        return np.zeros(0, bool)
    sep = np.zeros(len(TA), bool)
    for T in (TA, TB):
        e = np.roll(T, -1, axis=1) - T
        n = np.stack([-e[:, :, 1], e[:, :, 0]], -1)
        pA = np.einsum('nvi,nji->nvj', TA, n)
        pB = np.einsum('nvi,nji->nvj', TB, n)
        sep_j = (pA.max(1) < pB.min(1) + eps) | (pB.max(1) < pA.min(1) + eps)
        sep |= sep_j.any(axis=1)
    return ~sep


def compute_pack_metrics(final_uvs, scaled_islands, resolution, margin_px,
                         directional_objs, tiles_count, scale_loss, run_time,
                         stack_groups=None):
    """Compute all required metrics according to Session 5 specifications."""
    R = resolution
    M = margin_px

    # 1. Total UV area & share of square used per tile
    tot_uv_area = sum(float(np.abs(um.tri_area2_signed(uv)).sum()) for uv in final_uvs)
    share_of_square = tot_uv_area / max(1, tiles_count)

    # 2. Overlaps
    # Triangles from the same stacking group are exempted
    tri_list = []
    isl_id_list = []
    stack_id_list = []
    for i, uv in enumerate(final_uvs):
        tri_list.append(uv)
        isl_id_list.append(np.full(len(uv), i, dtype=np.int32))
        sid = scaled_islands[i].get('stack_id')
        stack_id_list.append(np.full(len(uv), -1 if sid is None else hash(sid) % 1000000007, dtype=np.int64))

    all_tris = np.concatenate(tri_list, 0)
    all_isl = np.concatenate(isl_id_list, 0)
    all_stack = np.concatenate(stack_id_list, 0)

    lo = all_tris.min(1); hi = all_tris.max(1)
    order = np.argsort(lo[:, 0])
    sorted_lo = lo[order]; sorted_hi = hi[order]
    sorted_isl = all_isl[order]; sorted_stack = all_stack[order]

    cand_a = []; cand_b = []
    for i in range(len(order)):
        x_max = sorted_hi[i, 0]
        end = np.searchsorted(sorted_lo[:, 0], x_max, side='right')
        if end > i + 1:
            js = np.arange(i + 1, end)
            diff_isl = (sorted_isl[js] != sorted_isl[i])
            same_stack = (sorted_stack[i] != -1) & (sorted_stack[js] == sorted_stack[i])
            valid = diff_isl & (~same_stack)
            if np.any(valid):
                js_v = js[valid]
                y_ov = (sorted_lo[js_v, 1] < sorted_hi[i, 1]) & (sorted_hi[js_v, 1] > sorted_lo[i, 1])
                js_final = js_v[y_ov]
                if len(js_final):
                    cand_a.append(np.full(len(js_final), order[i]))
                    cand_b.append(order[js_final])

    if cand_a:
        ca = np.concatenate(cand_a); cb = np.concatenate(cand_b)
        TA = all_tris[ca]; TB = all_tris[cb]
        ov_mask = sat_tri_tri(TA, TB)
        overlaps_count = int(ov_mask.sum())
    else:
        overlaps_count = 0

    # 3. Smallest distance between islands in pixels and margin violations
    # Sample points on the perimeter of each island
    island_pts = []
    island_ids = []
    for isl_idx, uv in enumerate(final_uvs):
        pts = uv.reshape(-1, 2) * R
        # Sample triangle edges
        edge_pts = np.concatenate([
            pts[0::3], pts[1::3], pts[2::3],
            0.5 * (pts[0::3] + pts[1::3]),
            0.5 * (pts[1::3] + pts[2::3]),
            0.5 * (pts[2::3] + pts[0::3])
        ], 0)
        island_pts.append(edge_pts)
        island_ids.extend([isl_idx] * len(edge_pts))

    all_edge_pts = np.concatenate(island_pts, 0)
    island_ids = np.array(island_ids)

    # 3. Smallest distance between islands in pixels and margin violations
    tree = cKDTree(all_edge_pts)
    dists, idxs = tree.query(all_edge_pts, k=10)

    # Determine stack group or island id
    stack_or_isl = np.array([
        scaled_islands[iid].get('stack_id') if scaled_islands[iid].get('stack_id') is not None else iid
        for iid in island_ids
    ])
    _, eff_ids = np.unique(stack_or_isl, return_inverse=True)

    cur_eff = eff_ids[:, None]
    neigh_eff = eff_ids[idxs]
    cur_isl = island_ids[:, None]
    neigh_isl = island_ids[idxs]

    diff_mask = (cur_eff != neigh_eff)
    valid_dists = dists[diff_mask]
    min_dist_px = float(valid_dists.min()) if len(valid_dists) else float(M)

    viol_mask = diff_mask & (dists < (M - 0.5))
    if np.any(viol_mask):
        p1 = np.repeat(cur_isl, idxs.shape[1], axis=1)[viol_mask]
        p2 = neigh_isl[viol_mask]
        pairs = np.sort(np.stack([p1, p2], 1), axis=1)
        margin_violations = int(len(np.unique(pairs, axis=0)))
    else:
        margin_violations = 0

    # 4. Texel density deviation
    density_devs = []
    for isl_idx, uv in enumerate(final_uvs):
        isl = scaled_islands[isl_idx]
        a3 = isl['a3']
        a2 = float(np.abs(um.tri_area2_signed(uv)).sum())
        if a3 > 0:
            actual_d = a2 / a3
            target_d = isl['target_d']
            if scale_loss > 0:
                target_d = target_d * (1.0 - scale_loss)
            dev = abs(actual_d - target_d) / target_d
            density_devs.append(dev)

    max_density_dev = float(max(density_devs)) if density_devs else 0.0

    # 5. Directional islands rotation check
    dir_rot_violations = 0
    for isl_idx, isl in enumerate(scaled_islands):
        if isl['obj'] in directional_objs:
            orig_c = isl['orig_uv'].reshape(-1, 2)
            new_c = final_uvs[isl_idx].reshape(-1, 2)
            dists = np.linalg.norm(orig_c - orig_c[0], axis=1)
            far_idx = int(np.argmax(dists))
            if dists[far_idx] > 1e-5:
                orig_v = orig_c[far_idx] - orig_c[0]
                new_v = new_c[far_idx] - new_c[0]
                norm_orig = float(np.linalg.norm(orig_v))
                norm_new = float(np.linalg.norm(new_v))
                if norm_orig > 1e-8 and norm_new > 1e-8:
                    cos_th = float(np.dot(orig_v, new_v) / (norm_orig * norm_new))
                    ang = float(np.arccos(np.clip(cos_th, -1.0, 1.0)))
                    diff = min(abs(ang - 0.0), abs(ang - np.pi))
                    if diff > 1e-2:
                        dir_rot_violations += 1

    # 6. Mip level merging check (levels 1 to 4)
    # A margin of m pixels survives about log2(m) mip levels
    first_merge_mip = None
    for mip in range(1, 5):
        scale_mip = 2 ** mip
        coords = np.floor(all_edge_pts / scale_mip).astype(np.int64)
        # Check if multiple islands share the exact same mip pixel
        stack_or_isl = np.array([
            scaled_islands[iid].get('stack_id') if scaled_islands[iid].get('stack_id') is not None else iid
            for iid in island_ids
        ])
        # Convert stack_or_isl to integer IDs
        _, eff_ids = np.unique(stack_or_isl, return_inverse=True)
        hashes = coords[:, 0] * 10000000 + coords[:, 1]
        _, inv = np.unique(hashes, return_inverse=True)
        pairs = np.unique(np.stack([inv, eff_ids], 1), axis=0)
        counts = np.bincount(pairs[:, 0], minlength=len(np.unique(hashes)))
        if np.any(counts > 1):
            first_merge_mip = mip
            break

    # 7. Estimated texture memory (MSFS BC7 3 maps + mip chain)
    # 1 byte per texel for BC7 + 33% for mip chain = 1.3333 bytes/texel * 3 maps * R * R * tiles
    bytes_per_map = (R * R) * 1.3333333333333333
    est_mem_mb = (3 * bytes_per_map * tiles_count) / (1024 * 1024)

    return {
        'share_of_square': share_of_square,
        'min_distance_px': min_dist_px,
        'margin_violations': margin_violations,
        'overlaps': overlaps_count,
        'max_density_dev': max_density_dev,
        'dir_rot_violations': dir_rot_violations,
        'first_merge_mip': first_merge_mip if first_merge_mip is not None else '> 4',
        'tiles_count': tiles_count,
        'scale_loss': scale_loss,
        'texture_mem_mb': est_mem_mb,
        'run_time_s': run_time
    }


def render_layout_png(final_uvs, out_path, title='UV Layout'):
    """Render layout PNG with distinct colors per island and overlaps highlighted."""
    fig, ax = plt.subplots(figsize=(8, 8), dpi=150)
    rng = np.random.default_rng(42)
    n_isl = len(final_uvs)
    colors = rng.uniform(0.2, 0.9, (n_isl, 3))

    polys = []
    poly_colors = []
    for i, uv in enumerate(final_uvs):
        for tri in uv:
            polys.append(tri)
            poly_colors.append(colors[i])

    pc = PolyCollection(polys, facecolors=poly_colors, edgecolors='black', linewidths=0.2)
    ax.add_collection(pc)

    all_uv_tris = np.concatenate(final_uvs, 0)

    max_tile = int(np.ceil(all_uv_tris[:, :, 0].max())) if len(all_uv_tris) else 1
    max_tile = max(1, max_tile)

    for t in range(max_tile):
        ax.plot([t, t+1, t+1, t, t], [0, 0, 1, 1, 0], 'r--', lw=0.8)

    ax.set_xlim(-0.02, max_tile + 0.02)
    ax.set_ylim(-0.02, 1.02)
    ax.set_aspect('equal')
    ax.set_title(title)
    plt.tight_layout()
    plt.savefig(out_path)
    plt.close()
    print(f'Saved layout PNG to {out_path}')


def run_blender_pack_comparison(scaled_islands, resolution, margin_px, out_dir):
    """Run Blender's Pack Islands on the exact same scaled islands."""
    # Ensure no other Blender process is running
    cmd_check = 'Get-Process blender -ErrorAction SilentlyContinue'
    res = subprocess.run(['powershell', '-Command', cmd_check], capture_output=True, text=True)
    if 'blender' in res.stdout.lower():
        raise RuntimeError("Another Blender process is currently running! Cannot start Blender.")

    # Prepare input npz for Blender
    all_uvs = []; all_tris = []; all_pts = []
    v_off = 0
    for isl in scaled_islands:
        # One vertex per distinct UV inside the island: the island stays one connected UV island for Blender
        uniq, inverse = np.unique(np.round(isl['uv'].reshape(-1, 2), 12), axis=0, return_inverse=True)
        flat_p = np.pad(uniq, ((0, 0), (0, 1)))
        flat_t = inverse.reshape(-1, 3) + v_off
        v_off += len(flat_p)
        all_uvs.append(isl['uv'].reshape(-1, 2))
        all_pts.append(flat_p)
        all_tris.append(flat_t)

    U = np.concatenate(all_uvs, 0)
    P = np.concatenate(all_pts, 0)
    T = np.concatenate(all_tris, 0)

    npz_in = os.path.join(out_dir, '_blender_pack_in.npz')
    npz_out = os.path.join(out_dir, '_blender_pack_out.npz')
    np.savez(npz_in, UV=U, P=P, T=T)

    margin_frac = float(margin_px) / float(resolution) / 2.0

    blender_py = f"""
import bpy, numpy as np, time
d = np.load(r'{npz_in}')
U = d['UV']; F = d['T']; P = d['P']
bpy.ops.wm.read_factory_settings(use_empty=True)
me = bpy.data.meshes.new('b_mesh')
me.from_pydata(P.tolist(), [], F.tolist())
me.update()
uv_layer = me.uv_layers.new(name='UVMap')
uv_layer.data.foreach_set('uv', U.ravel())
ob = bpy.data.objects.new('b_obj', me)
bpy.context.collection.objects.link(ob)
bpy.context.view_layer.objects.active = ob
ob.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='SELECT')
t0 = time.perf_counter()
bpy.ops.uv.pack_islands(udim_source='CLOSEST_UDIM', rotate=True, rotate_method='ANY', scale=True,
                        merge_overlap=False, margin_method='FRACTION', margin={margin_frac},
                        pin=False, shape_method='CONCAVE')
dt = time.perf_counter() - t0
bpy.ops.object.mode_set(mode='OBJECT')
out_uv = np.zeros(len(U) * 2)
me.uv_layers['UVMap'].data.foreach_get('uv', out_uv)
np.savez(r'{npz_out}', UV=out_uv.reshape(-1, 3, 2), time=dt)
"""
    script_path = os.path.join(out_dir, '_blender_pack_script.py')
    with open(script_path, 'w') as f:
        f.write(blender_py)

    t0 = time.perf_counter()
    p = subprocess.run([BLENDER_EXE, '-b', '--python', script_path], capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"Blender pack failed:\n{p.stderr}\n{p.stdout}")

    d_out = np.load(npz_out)
    b_uv = d_out['UV']
    b_dt = float(d_out['time'])

    # Partition back into islands
    out_islands_uv = []
    idx = 0
    for isl in scaled_islands:
        nt = len(isl['uv'])
        out_islands_uv.append(b_uv[idx : idx + nt])
        idx += nt

    return out_islands_uv, b_dt


def run_xatlas_pack_comparison(scaled_islands, resolution, margin_px):
    """Run xatlas on the exact same scaled islands."""
    import xatlas
    all_uvs = []; all_tris = []
    v_off = 0
    grid_step = 2.0
    cols = 40
    for idx, isl in enumerate(scaled_islands):
        gx = (idx % cols) * grid_step
        gy = (idx // cols) * grid_step
        flat_uv = isl['uv'].reshape(-1, 2) + np.array([gx, gy])
        flat_t = np.arange(len(flat_uv)).reshape(-1, 3) + v_off
        v_off += len(flat_uv)
        all_uvs.append(flat_uv)
        all_tris.append(flat_t)

    U = np.concatenate(all_uvs, 0).astype(np.float32)
    T = np.concatenate(all_tris, 0).astype(np.uint32)

    atlas = xatlas.Atlas()
    atlas.add_uv_mesh(U, T)
    po = xatlas.PackOptions()
    po.resolution = resolution
    po.padding = margin_px
    po.rotate_charts = False
    po.blockAlign = True

    t0 = time.perf_counter()
    atlas.generate(pack_options=po)
    dt = time.perf_counter() - t0

    vm, tind, out_uvs = atlas.get_mesh(0)
    s = np.array([atlas.width, atlas.height], np.float64) / max(atlas.width, atlas.height)
    x_uv = (out_uvs[tind].astype(np.float64) * s).reshape(-1, 3, 2)

    out_islands_uv = []
    idx = 0
    for isl in scaled_islands:
        nt = len(isl['uv'])
        out_islands_uv.append(x_uv[idx : idx + nt])
        idx += nt

    return out_islands_uv, dt, atlas.atlas_count


def run_synthetic_stacking_test(resolution=4096, margin_px=8):
    """
    Synthetic test for Requirement 3:
    1 object with a Mirror modifier (unwrapped before modifier -> 2 halves share UVs).
    2 objects sharing 1 mesh datablock.
    Verify that their islands are placed together and remain perfectly stacked.
    """
    print("\n--- Running Synthetic Stacking Test ---")
    # Base island 1: quad with 2 triangles
    tri1 = np.array([[[0.0, 0.0], [0.1, 0.0], [0.1, 0.1]], [[0.0, 0.0], [0.1, 0.1], [0.0, 0.1]]])
    # Mirror half: identical UVs, stack_id = 'mirror_pair_0'
    isl_m1 = {'id': 0, 'obj': 'MIRROR_OBJ', 'uv': tri1.copy(), 'a3': 0.01, 'a2': 0.01, 'target_d': 1.0, 'density_factor': 1.0, 'stack_id': 'mirror_0'}
    isl_m2 = {'id': 1, 'obj': 'MIRROR_OBJ', 'uv': tri1.copy(), 'a3': 0.01, 'a2': 0.01, 'target_d': 1.0, 'density_factor': 1.0, 'stack_id': 'mirror_0'}

    # Base island 2: triangle
    tri2 = np.array([[[0.0, 0.0], [0.15, 0.0], [0.05, 0.15]]])
    # Shared mesh between OBJ_A and OBJ_B: stack_id = 'shared_mesh_0'
    isl_s1 = {'id': 2, 'obj': 'OBJ_A', 'uv': tri2.copy(), 'a3': 0.02, 'a2': 0.02, 'target_d': 1.0, 'density_factor': 1.0, 'stack_id': 'shared_0'}
    isl_s2 = {'id': 3, 'obj': 'OBJ_B', 'uv': tri2.copy(), 'a3': 0.02, 'a2': 0.02, 'target_d': 1.0, 'density_factor': 1.0, 'stack_id': 'shared_0'}

    test_islands = [isl_m1, isl_m2, isl_s1, isl_s2]

    packed_uvs, tiles, stats = pack_grid(test_islands, resolution=resolution, margin_px=margin_px)

    # Verify stacking
    mirror_diff = np.max(np.abs(packed_uvs[0] - packed_uvs[1]))
    shared_diff = np.max(np.abs(packed_uvs[2] - packed_uvs[3]))

    print(f"Mirror pair max coordinate difference: {mirror_diff:.8f}")
    print(f"Shared mesh pair max coordinate difference: {shared_diff:.8f}")

    assert mirror_diff < 1e-6, "Mirror stacked islands did not stay stacked!"
    assert shared_diff < 1e-6, "Shared mesh stacked islands did not stay stacked!"

    # Verify overlap check exempts stacking units
    metrics = compute_pack_metrics(packed_uvs, test_islands, resolution, margin_px, set(), 1, 0.0, stats['run_time_s'])
    print(f"Overlaps (exempting stacking units): {metrics['overlaps']}")
    assert metrics['overlaps'] == 0, f"Expected 0 non-exempt overlaps, got {metrics['overlaps']}"

    print("Synthetic Stacking Test PASSED successfully!\n")
    return True


def main():
    parser = argparse.ArgumentParser(description="Automated UV Packing Prototype (Phase 3)")
    parser.add_argument('--results', default=os.path.join(HERE, 'results3'), help='Path to results3 dir containing proto3 npz files')
    parser.add_argument('--config', default=os.path.join(HERE, 'pack_config.json'), help='Path to pack_config.json')
    parser.add_argument('--resolution', type=int, default=4096, choices=[4096, 8192], help='Texture resolution')
    parser.add_argument('--margin', type=int, default=8, help='Margin in pixels')
    parser.add_argument('--overflow', default='tiles', choices=['tiles', 'scale'], help='Overflow handling mode')
    parser.add_argument('--set', default='all', help='Texture set name or all')
    parser.add_argument('--compare', default='all', choices=['all', 'grid', 'blender', 'xatlas', 'none'], help='Methods to run')
    parser.add_argument('--out', default=os.path.join(HERE, 'pack_output'), help='Output directory')
    parser.add_argument('--save_png', action='store_true', default=True, help='Save layout PNGs')
    parser.add_argument('--test_stacking', action='store_true', default=False, help='Run synthetic stacking test')
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)

    if args.test_stacking:
        run_synthetic_stacking_test(args.resolution, args.margin)
        return

    # Load configuration
    ppm = 2048.0
    density_factors = {}
    directional_objs = set()

    if os.path.exists(args.config):
        with open(args.config, 'r') as f:
            cfg = json.load(f)
            ppm = float(cfg.get('pixels_per_metre', ppm))
            density_factors = {k.replace('W_', ''): v for k, v in cfg.get('density_factors', {}).items()}
            directional_objs = set(k.replace('W_', '') for k in cfg.get('directional_objects', []))
            print(f"Loaded config: PPM={ppm}, density_factors={density_factors}, directional={directional_objs}")
    else:
        print(f"Config file not found at {args.config}, using defaults.")

    # Load texture sets
    texture_sets = load_texture_sets(args.results)
    print(f"Found {len(texture_sets)} texture sets: {list(texture_sets.keys())}")

    target_sets = [args.set] if args.set != 'all' else list(texture_sets.keys())

    all_results = {}

    for mat_name in target_sets:
        if mat_name not in texture_sets:
            print(f"Warning: texture set '{mat_name}' not found!")
            continue

        raw_islands = texture_sets[mat_name]
        print(f"\n========================================================")
        print(f"Processing Texture Set: '{mat_name}' ({len(raw_islands)} islands)")
        print(f"Resolution: {args.resolution}x{args.resolution}, Margin: {args.margin} px, PPM: {ppm}")
        print(f"========================================================")

        scaled_islands = scale_islands(raw_islands, args.resolution, ppm, density_factors)
        mat_results = {}

        # 1. Grid Packer
        if args.compare in ['all', 'grid']:
            print("\n>>> Running Grid Packer...")
            final_uvs, tile_idxs, stats = pack_grid(
                scaled_islands, resolution=args.resolution, margin_px=args.margin,
                overflow_mode=args.overflow, directional_objs=directional_objs
            )
            metrics_grid = compute_pack_metrics(
                final_uvs, scaled_islands, args.resolution, args.margin,
                directional_objs, stats['tiles_count'], stats['scale_loss'], stats['run_time_s']
            )
            mat_results['GridPacker'] = metrics_grid
            # Same set in one square with one uniform scale: comparable with Blender's Pack Islands
            one_uvs, one_stats = pack_grid_one_tile(scaled_islands, args.resolution, args.margin, directional_objs)
            metrics_one = compute_pack_metrics(
                one_uvs, scaled_islands, args.resolution, args.margin,
                directional_objs, 1, 1.0 - one_stats['scale'] ** 2, one_stats['run_time_s']
            )
            metrics_one['uniform_scale'] = one_stats['scale']
            mat_results['GridPacker1Tile'] = metrics_one
            print(f"GridPacker one tile: scale {one_stats['scale']:.3f} ({one_stats['tries']} tries, {one_stats['run_time_s']:.1f} s), "
                  f"min distance {metrics_one['min_distance_px']:.2f} px, violations {metrics_one['margin_violations']}, "
                  f"overlaps {metrics_one['overlaps']}")
            if args.save_png and mat_name == 'Cockpit_STD':
                png_path = os.path.join(args.out, f'{mat_name}__GridPacker1Tile_{args.resolution}_{args.margin}px.png')
                render_layout_png(one_uvs, png_path, f'Grid Packer, one tile: {mat_name} ({args.resolution}x{args.resolution}, {args.margin}px)')
            print(f"GridPacker completed in {metrics_grid['run_time_s']:.2f} s")
            print(f"   Share of square: {metrics_grid['share_of_square']*100:.2f}% (tiles: {metrics_grid['tiles_count']})")
            print(f"   Smallest distance: {metrics_grid['min_distance_px']:.2f} px (margin violations: {metrics_grid['margin_violations']})")
            print(f"   Overlaps: {metrics_grid['overlaps']}")
            print(f"   Max density dev: {metrics_grid['max_density_dev']*100:.2f}%")
            print(f"   First mip merge: {metrics_grid['first_merge_mip']}")

            if args.save_png and mat_name == 'Cockpit_STD':
                png_path = os.path.join(args.out, f'{mat_name}__GridPacker_{args.resolution}_{args.margin}px.png')
                render_layout_png(final_uvs, png_path, f'Grid Packer: {mat_name} ({args.resolution}x{args.resolution}, {args.margin}px)')

        # 2. Blender Pack Islands
        if args.compare in ['all', 'blender']:
            print("\n>>> Running Blender Pack Islands...")
            try:
                b_uvs, b_dt = run_blender_pack_comparison(scaled_islands, args.resolution, args.margin, args.out)
                # Blender packs into one square with a uniform scale (scale=True): report that scale as the density
                # it reaches, the same measure as the grid packer's one-tile search below
                a_in = sum(isl['a2'] for isl in scaled_islands)
                a_out = sum(float(np.abs(um.tri_area2_signed(uv)).sum()) for uv in b_uvs)
                b_scale = (a_out / a_in) ** 0.5 if a_in > 0 else 1.0
                b_tiles = 1
                metrics_blender = compute_pack_metrics(
                    b_uvs, scaled_islands, args.resolution, args.margin,
                    directional_objs, b_tiles, 1.0 - b_scale ** 2, b_dt
                )
                metrics_blender['uniform_scale'] = b_scale
                mat_results['BlenderPack'] = metrics_blender
                print(f"Blender completed in {metrics_blender['run_time_s']:.2f} s")
                print(f"   Share of square: {metrics_blender['share_of_square']*100:.2f}% (tiles: {b_tiles})")
                print(f"   Smallest distance: {metrics_blender['min_distance_px']:.2f} px (margin violations: {metrics_blender['margin_violations']})")
                print(f"   Overlaps: {metrics_blender['overlaps']}")
                print(f"   Max density dev: {metrics_blender['max_density_dev']*100:.2f}%")
                print(f"   First mip merge: {metrics_blender['first_merge_mip']}")

                if args.save_png and mat_name == 'Cockpit_STD':
                    png_path = os.path.join(args.out, f'{mat_name}__BlenderPack_{args.resolution}_{args.margin}px.png')
                    render_layout_png(b_uvs, png_path, f'Blender Pack: {mat_name} ({args.resolution}x{args.resolution}, {args.margin}px)')
            except Exception as e:
                print(f"Blender pack comparison failed: {e}")

        # 3. xatlas Packer
        if args.compare in ['all', 'xatlas']:
            print("\n>>> Running xatlas Packer...")
            try:
                x_uvs, x_dt, x_atlases = run_xatlas_pack_comparison(scaled_islands, args.resolution, args.margin)
                metrics_xatlas = compute_pack_metrics(
                    x_uvs, scaled_islands, args.resolution, args.margin,
                    directional_objs, x_atlases, 0.0, x_dt
                )
                mat_results['xatlas'] = metrics_xatlas
                print(f"xatlas completed in {metrics_xatlas['run_time_s']:.2f} s")
                print(f"   Share of square: {metrics_xatlas['share_of_square']*100:.2f}% (tiles: {x_atlases})")
                print(f"   Smallest distance: {metrics_xatlas['min_distance_px']:.2f} px (margin violations: {metrics_xatlas['margin_violations']})")
                print(f"   Overlaps: {metrics_xatlas['overlaps']}")
                print(f"   Max density dev: {metrics_xatlas['max_density_dev']*100:.2f}%")
                print(f"   First mip merge: {metrics_xatlas['first_merge_mip']}")

                if args.save_png and mat_name == 'Cockpit_STD':
                    png_path = os.path.join(args.out, f'{mat_name}__xatlas_{args.resolution}_{args.margin}px.png')
                    render_layout_png(x_uvs, png_path, f'xatlas: {mat_name} ({args.resolution}x{args.resolution}, {args.margin}px)')
            except Exception as e:
                print(f"xatlas pack comparison failed: {e}")

        all_results[mat_name] = mat_results

    # Save summary json
    summary_path = os.path.join(args.out, f'pack_results_{args.resolution}_{args.margin}px.json')
    with open(summary_path, 'w') as f:
        json.dump(all_results, f, indent=2)
    print(f"\nAll results saved to {summary_path}")


if __name__ == '__main__':
    main()
