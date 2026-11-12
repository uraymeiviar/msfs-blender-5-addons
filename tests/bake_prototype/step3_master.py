"""Bake prototype, steps 3 and 4: build the master layout of one object and bake its AO.

Run (CPU wrapper, no blend file):
    blender -b --factory-startup --python step3_master.py -- tag=panel samples=64 size=4096

- density = 2x the area-weighted median texel density of layout (a) (the material's UV map at texture size `size`);
- islands by unfolding, skirt, packing with 2 px gutters (bake_unfold.py); checks: edge lengths, overlaps, islands,
  gutter share;
- bake (step 2's working variant): the master core and the skirt as separate meshes with every ray visibility off,
  each baked Selected to Active from the target, which stays the only occluder of its own;
- compose: core pixels, then skirt pixels, then the remaining pixels of each island's rectangle (wedges beyond
  corners) from the nearest baked pixel;
- face map: the face each master pixel shows (core, skirt source face, nearest), for the copy's surface-aware read;
- save master_<tag>.png (16-bit grey) and master_<tag>.npz (master UV per face corner, island per face, density,
  rectangles, face map, settings) in tests/_work/ao_bake/master/.
Island join order: order=growlen (default; see bake_unfold.py).
mirror_open=1 (P15, Session 6): open mesh edges get the face itself mirrored as skirt; suffix=<s> names the output
master_<tag><s>.
fold_split=30 (P18, Session 8): islands are never joined across folds over 30 degrees, and such split edges get the
face itself mirrored as skirt (bake_unfold.build_master).
"""
import hashlib
import json
import os
import sys
import time

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bake_common as bc  # noqa: E402
import bake_geom as bg  # noqa: E402
import bake_unfold as bu  # noqa: E402

args = dict(a.split('=', 1) for a in (sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []))
tag = args.get('tag', 'panel')
N = int(args.get('samples', 64))
GUTTER = int(args.get('gutter', 2))
ORDER = args.get('order', 'growlen')
MIRROR_OPEN = args.get('mirror_open', '0') == '1'  # P15: mirrored skirt beyond open mesh edges
SUFFIX = args.get('suffix', '')  # output name master_<tag><suffix>, so earlier masters stay
FOLD_SPLIT = float(args['fold_split']) if 'fold_split' in args else None  # P18: split islands at folds over (deg)
OUT = os.path.join(bc.WORK, 'master')
os.makedirs(OUT, exist_ok=True)
LOG = os.path.join(OUT, f'master_{tag}{SUFFIX}.log.txt')
EXTRUSION, RAY_DIST = 2e-5, 4e-5
t_all = time.time()

target, info = bc.load_scene(tag)
S = int(args.get('size', info['texture_size']))
pos, tris, cn, uvs = bc.mesh_arrays(target.data)
uv_px = uvs[info['uv']] * S
dens = bg.densities(pos, tris, uv_px)
a3 = bg.tri_areas_3d(pos, tris)
ok = dens > 0
median_d = bg.weighted_median(dens[ok], a3[ok])
D = 2.0 * median_d
bc.log(f'{tag}: {info["target"]}, {len(tris)} tris, layout (a) median density {median_d:.1f} px/m at {S}, '
       f'master density {D:.1f} px/m', LOG)

t = time.time()
m = bu.build_master(pos, tris, cn, D, gutter=GUTTER, order=ORDER, mirror_open=MIRROR_OPEN, fold_split=FOLD_SPLIT)
t_build = time.time() - t
chk = bu.check_master(pos, tris, m)
bc.log(f'  master {m["W"]}x{m["H"]} px, {m["n_islands"]} islands, {len(m["skirt_pos"])} skirt pieces, '
       f'{m["n_border_edges"]} border edges ({m["n_border_without_neighbour"]} without neighbour, '
       f'{m["n_mirrored"]} mirrored; fold split {FOLD_SPLIT}: {m["n_mirrored_fold"]} mirrored at folds, '
       f'{m["n_fold_inner_cut"]} continuous fold half-edges cut), '
       f'degenerate faces {int(m["degenerate"].sum())}, rejected joins {m["rejected"]}, built in {t_build:.2f} s', LOG)
bc.log(f'  check: {chk}', LOG)

# walls around an axis (the knob's side): the local axis whose perpendicular faces' normals cover the most azimuth;
# each connected set of such faces that goes all the way round (>= 300 degrees) must be one island
axes = np.array(info['local_axes_world'])
nrm = np.cross(pos[tris[:, 1]] - pos[tris[:, 0]], pos[tris[:, 2]] - pos[tris[:, 0]])
nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-30)
best = None
for ai, name in enumerate(('X', 'Y', 'Z')):
    ax = axes[ai] / np.linalg.norm(axes[ai])
    sel = (np.abs(nrm @ ax) < 0.2) & ~m['degenerate']
    u = np.cross(ax, [1.0, 0, 0] if abs(ax[0]) < 0.9 else [0, 1.0, 0])
    u /= np.linalg.norm(u)
    v = np.cross(ax, u)
    az = np.degrees(np.arctan2(nrm @ v, nrm @ u)) % 360
    cover = len(set((az[sel] // 30).astype(int))) * 30 if sel.any() else 0
    if best is None or cover > best[2]:
        best = (name, sel, cover, az)
axis_name, sel, cover, az = best
wid = bg.weld_ids(pos)
wt = wid[tris]
em = bg.edge_map(wt)
parent = {int(t): int(t) for t in np.nonzero(sel)[0]}


def _find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


for lst in em.values():
    ts = [e[0] for e in lst if e[0] in parent]
    for a_, b_ in zip(ts, ts[1:]):
        ra, rb = _find(a_), _find(b_)
        if ra != rb:
            parent[ra] = rb
comps = {}
for t_ in parent:
    comps.setdefault(_find(t_), []).append(t_)
walls = []
for comp in comps.values():
    azs = np.sort(az[comp])
    gaps = np.diff(np.concatenate([azs, azs[:1] + 360]))
    max_gap = float(gaps.max())
    isl_ids = sorted(set(int(m['island'][t_]) for t_ in comp))
    tot_a = float(a3[comp].sum())
    shares = {i_: round(float(a3[[t_ for t_ in comp if m['island'][t_] == i_]].sum()) / tot_a, 4) for i_ in isl_ids}
    cs = set(comp)
    n_e = n_cont = 0
    for lst in em.values():
        if len(lst) == 2 and lst[0][0] in cs and lst[1][0] in cs:
            n_e += 1
            (u1, i1, j1), (u2, i2, j2) = lst
            r2 = list(wt[u2])
            if (np.allclose(m['muv'][u1][i1], m['muv'][u2][r2.index(wt[u1][i1])], atol=1e-6)
                    and np.allclose(m['muv'][u1][j1], m['muv'][u2][r2.index(wt[u1][j1])], atol=1e-6)):
                n_cont += 1
    walls.append(dict(wall_edges=n_e, continuous_edges=n_cont, faces=len(comp), max_azimuth_gap_deg=round(max_gap, 1), islands=shares, n_islands=len(isl_ids),
                      full_round=max_gap < 60))
walls.sort(key=lambda w_: -w_['faces'])
full = [w_ for w_ in walls if w_['full_round']]
side = dict(axis=axis_name, azimuth_cover_deg=cover, walls=walls[:10], full_round_walls=len(full),
            all_full_round_walls_one_island=bool(full) and all(w_['n_islands'] == 1 for w_ in full))
bc.log(f'  walls around local {axis_name}: {side}', LOG)

# bake meshes
W, H = m['W'], m['H']
scale = np.array([W, H], dtype=np.float64)
core = m['core_tris']
core_me = bc.build_mesh('MASTER_CORE', pos[tris[core]].reshape(-1, 3), np.arange(len(core) * 3).reshape(-1, 3),
                        cn[core], m['muv'][core] / scale)
core_obj = bpy.data.objects.new('MASTER_CORE', core_me)
bpy.context.scene.collection.objects.link(core_obj)
bc.set_ray_invisible(core_obj)
times = {}
img = bc.new_float_image('M_CORE', W, H)
times['bake_core_s'] = bc.bake(core_obj, img, 'BAKE_UV', N, 11, margin=0, from_objects=[target],
                               extrusion=EXTRUSION, ray_distance=RAY_DIST)
A = bc.image_to_array(img)
bpy.data.images.remove(img)
ns = len(m['skirt_pos'])
B = np.full((H, W), -1.0)
if ns:
    sk_me = bc.build_mesh('MASTER_SKIRT', m['skirt_pos'].reshape(-1, 3), np.arange(ns * 3).reshape(-1, 3),
                          m['skirt_n'], m['skirt_uv'] / scale)
    sk_obj = bpy.data.objects.new('MASTER_SKIRT', sk_me)
    bpy.context.scene.collection.objects.link(sk_obj)
    bc.set_ray_invisible(sk_obj)
    img = bc.new_float_image('M_SKIRT', W, H)
    times['bake_skirt_s'] = bc.bake(sk_obj, img, 'BAKE_UV', N, 12, margin=0, from_objects=[target],
                                    extrusion=EXTRUSION, ray_distance=RAY_DIST)
    B = bc.image_to_array(img)
    bpy.data.images.remove(img)
bc.log(f'  bakes: {times}', LOG)

# compose
in_rect = np.zeros((H, W), dtype=bool)
rect_id = np.full((H, W), -1, dtype=np.int64)
for i, (x, y, w, h) in enumerate(m['rects']):
    in_rect[y:y + h, x:x + w] = True
    rect_id[y:y + h, x:x + w] = i
M = np.full((H, W), -1.0)
src = np.zeros((H, W), dtype=np.int8)  # 1 core, 2 skirt, 3 nearest fill
cm = A >= 0
M[cm] = A[cm]
src[cm] = 1
sm = (~cm) & (B >= 0) & in_rect
M[sm] = B[sm]
src[sm] = 2
filled = M >= 0
idx = np.where(filled, np.arange(H * W).reshape(H, W), -1)
grown, steps = bg.dilate_ids(idx, 2 * GUTTER + 4, mask_allowed=in_rect)
fm = (~filled) & (grown >= 0)
# a fill must come from the same island's rectangle
same = np.zeros_like(fm)
same[fm] = rect_id.ravel()[grown[fm]] == rect_id[fm]
fm &= same
M[fm] = M.ravel()[grown[fm]]
src[fm] = 3
# face map: which face of the object each master pixel shows (core, then skirt, then the nearest), used by the
# copy to read only texels of the same surface
own_core, _ = bg.rasterize_ids(m['muv'][core], W, H)
face_map = np.where(own_core >= 0, core[np.maximum(own_core, 0)], -1)
if ns:
    own_sk, _ = bg.rasterize_ids(m['skirt_uv'], W, H)
    sk_face = np.where(own_sk >= 0, m['skirt_src'][np.maximum(own_sk, 0)], -1)
    take = (face_map < 0) & (sk_face >= 0) & in_rect
    face_map[take] = sk_face[take]
fidx = np.where(face_map >= 0, np.arange(H * W).reshape(H, W), -1)
fgrown, _ = bg.dilate_ids(fidx, 2 * GUTTER + 4, mask_allowed=in_rect)
fm2 = (face_map < 0) & (fgrown >= 0)
face_map[fm2] = face_map.ravel()[fgrown[fm2]]
comp = dict(core_px=int(cm.sum()), skirt_px=int(sm.sum()), nearest_fill_px=int(fm.sum()),
            rect_px_unfilled=int((in_rect & (M < 0)).sum()), rect_px=int(in_rect.sum()), image_px=int(W * H))
bc.log(f'  compose: {comp}', LOG)
M_out = np.where(M >= 0, M, 0.0)
png = os.path.join(OUT, f'master_{tag}{SUFFIX}.png')
bc.write_png(png, M_out)
src_rgb = np.zeros((H, W, 3))
src_rgb[src == 1] = (0.8, 0.8, 0.8)
src_rgb[src == 2] = (0.2, 0.6, 1.0)
src_rgb[src == 3] = (1.0, 0.4, 0.1)
bc.write_png(os.path.join(OUT, f'master_{tag}{SUFFIX}_sources.png'), src_rgb, bits=8)
fp = hashlib.sha1(np.ascontiguousarray(pos).tobytes() + np.ascontiguousarray(tris).tobytes()
                  + np.round(cn, 5).tobytes()).hexdigest()
npz = os.path.join(OUT, f'master_{tag}{SUFFIX}.npz')
np.savez_compressed(npz, muv=m['muv'], island=m['island'], density=D, W=W, H=H, rects=m['rects'],
                    gutter=GUTTER, degenerate=m['degenerate'], filled=(M >= 0), face_map=face_map.astype(np.int32),
                    meta=json.dumps(dict(schema=1, tag=tag, target=info['target'], mesh_fingerprint=fp,
                                         ao_distance=bc.AO_DISTANCE, samples=N, seeds=[11, 12],
                                         order=ORDER, mirror_open=MIRROR_OPEN, fold_split=FOLD_SPLIT, bake='selected-to-active from the target, extrusion %g m' % EXTRUSION,
                                         layout_a_median_density=median_d, texture_size=S)))
res = dict(tag=tag, order=ORDER, target=info['target'], tris=int(len(tris)), median_density_a=median_d, master_density=D,
           W=W, H=H, n_islands=m['n_islands'], skirt_pieces=int(ns), border_edges=m['n_border_edges'],
           border_without_neighbour=m['n_border_without_neighbour'], mirrored=m['n_mirrored'],
           fold_split=FOLD_SPLIT, mirrored_fold=m['n_mirrored_fold'], fold_inner_cut_half_edges=m['n_fold_inner_cut'],
           mirror_open=MIRROR_OPEN, degenerate=int(m['degenerate'].sum()),
           rejected=m['rejected'], check=chk, side=side, compose=comp, times=dict(times, build_s=t_build),
           png_bytes=os.path.getsize(png), npz_bytes=os.path.getsize(npz), samples=N,
           total_s=round(time.time() - t_all, 1))
with open(os.path.join(OUT, f'master_{tag}{SUFFIX}.json'), 'w') as f:
    json.dump(res, f, indent=1)
bc.log(f'  saved {png} ({res["png_bytes"]} B) and npz ({res["npz_bytes"]} B); total {res["total_s"]} s', LOG)
