"""Density-first UV packing prototype: Blender's Pack Islands wrapped in our own steps (journal 20261019, Session 97,
decisions 112 and 113).

Per texture set (material): every island is scaled to its texel density lo_i + t (hi_i - lo_i), with one t for the
whole set (t = 1 when the set fits at the top of its ranges, else the largest t that fits, else t = 0 and the set
spills into [0, k] x [0, k]), then packed with bpy.ops.uv.pack_islands(scale=False). Packing runs on a temporary mesh
per set, so the source objects' selection, modes, pins and active UV maps are never touched; only the UVs of the
packed faces are written back.

Blender modes (background only):
  blender -b --factory-startup --python tests/uv_prototype/pack_density_proto.py -- --synthetic
  blender -b --factory-startup --python tests/uv_prototype/pack_density_proto.py -- --cockpit
Venv mode (numpy, matplotlib/PIL, scipy for pack_grid), after --cockpit:
  tests/_work/uv_packing/venv/Scripts/python.exe tests/uv_prototype/pack_density_proto.py --grid Cockpit_STD,COLLIDER
"""

import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np

try:
    import bpy
except ImportError:  # venv mode
    bpy = None

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
WORK = REPO_ROOT / 'tests' / '_work' / 'uv_packing_density'
COCKPIT_SRC = Path(r'G:\e-jets-e2\assets\visual\cockpit\COCKPIT.blend')
COCKPIT_COPY = WORK / 'COCKPIT_pack.blend'
OUT = WORK / 'out'

GAP_TOL = 1e-3  # px: a gap below margin - GAP_TOL is a violation
MARGIN_EXTRA = 0.1  # px added to the requested gap (Blender's ADD margin came out 0.016 px short of 2 x margin at 64 px)
RANGE_TOL = 1e-4  # relative: density inside its range within rounding
ANCHOR_PX = 0.5  # size of the two anchor triangles that set the ORIGINAL_AABB region, in px


def log(*args):
    print('PDP', *args, flush=True)


def next_pow2(x):
    return 1 << max(0, int(math.ceil(math.log2(max(x, 1e-9)))))


# ------------------------------------------------------------------------------------------------------------------
# Geometry helpers (numpy only; used in Blender and in the venv)
# ------------------------------------------------------------------------------------------------------------------

def _bbox_diag(P, ids, n):
    lo = np.full((n, P.shape[1]), np.inf)
    hi = np.full((n, P.shape[1]), -np.inf)
    np.minimum.at(lo, ids, P)
    np.maximum.at(hi, ids, P)
    return np.linalg.norm(np.where(np.isfinite(hi - lo), hi - lo, 0.0), axis=1)


def components(n, a, b):
    """Connected components of n nodes with edges (a, b): hook roots, then pointer jumping. Returns root labels."""
    parent = np.arange(n, dtype=np.int64)
    a = np.asarray(a, np.int64)
    b = np.asarray(b, np.int64)
    if len(a) == 0:
        return parent
    while True:
        pa, pb = parent[a], parent[b]
        lo, hi = np.minimum(pa, pb), np.maximum(pa, pb)
        m = lo != hi
        if not m.any():
            return parent
        np.minimum.at(parent, hi[m], lo[m])
        while True:
            pp = parent[parent]
            if np.array_equal(pp, parent):
                break
            parent = pp


def tri_area(T):
    """Unsigned areas of 2D triangles (n, 3, 2)."""
    e1 = T[:, 1] - T[:, 0]
    e2 = T[:, 2] - T[:, 0]
    return 0.5 * np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0])


def _pt_seg(P, A, B):
    AB = B - A
    L2 = np.maximum((AB * AB).sum(1), 1e-30)
    t = np.clip(((P - A) * AB).sum(1) / L2, 0.0, 1.0)
    D = A + AB * t[:, None] - P
    return np.sqrt((D * D).sum(1))


def _cross(o, a, b):
    return (a[:, 0] - o[:, 0]) * (b[:, 1] - o[:, 1]) - (a[:, 1] - o[:, 1]) * (b[:, 0] - o[:, 0])


def seg_seg_dist(P1, P2, Q1, Q2):
    """Exact distance between 2D segments (vectorised, row-wise)."""
    d = np.minimum(np.minimum(_pt_seg(P1, Q1, Q2), _pt_seg(P2, Q1, Q2)),
                   np.minimum(_pt_seg(Q1, P1, P2), _pt_seg(Q2, P1, P2)))
    d1, d2 = _cross(Q1, Q2, P1), _cross(Q1, Q2, P2)
    d3, d4 = _cross(P1, P2, Q1), _cross(P1, P2, Q2)
    inter = (d1 * d2 < 0) & (d3 * d4 < 0)
    return np.where(inter, 0.0, d)


def sat_overlap(TA, TB, eps=1e-6):
    """True where 2D triangles TA[i] and TB[i] overlap with positive area (separating axis test)."""
    if len(TA) == 0:
        return np.zeros(0, bool)
    sep = np.zeros(len(TA), bool)
    for T in (TA, TB):
        e = np.roll(T, -1, axis=1) - T
        n = np.stack([-e[:, :, 1], e[:, :, 0]], -1)
        pA = np.einsum('nvi,nji->nvj', TA, n)
        pB = np.einsum('nvi,nji->nvj', TB, n)
        sep |= ((pA.max(1) <= pB.min(1) + eps) | (pB.max(1) <= pA.min(1) + eps)).any(1)
    return ~sep


def box_pairs(lo, hi, pad=0.0):
    """Index pairs (i < j) whose boxes [lo - pad, hi + pad] intersect (sweep over x)."""
    lo = lo - pad
    hi = hi + pad
    order = np.argsort(lo[:, 0], kind='stable')
    slo, shi = lo[order], hi[order]
    ia, ib = [], []
    for k in range(len(order)):
        end = np.searchsorted(slo[:, 0], shi[k, 0], side='right')
        if end > k + 1:
            js = np.arange(k + 1, end)
            m = (slo[js, 1] <= shi[k, 1]) & (shi[js, 1] >= slo[k, 1])
            if m.any():
                ia.append(np.full(int(m.sum()), order[k]))
                ib.append(order[js[m]])
    if not ia:
        return np.zeros(0, np.int64), np.zeros(0, np.int64)
    a = np.concatenate(ia)
    b = np.concatenate(ib)
    return np.minimum(a, b), np.maximum(a, b)


def _grouped(ids, n):
    order = np.argsort(ids, kind='stable')
    starts = np.searchsorted(ids[order], np.arange(n + 1))
    return order, starts


def layout_metrics(tri_px, tri_isl, seg_px, seg_isl, isl_unit, margin_px, reach=None):
    """Smallest gap between units (exact segment distance over island boundaries) and overlapping triangle pairs
    between different units, all in pixels. Islands of one stacking unit are exempt from both. Gaps are measured
    up to `reach` px (default 2 x margin): min_gap_px None means every gap is larger."""
    reach = 2.0 * margin_px if reach is None else reach
    n = len(isl_unit)
    tlo = tri_px.min(1)
    thi = tri_px.max(1)
    ilo = np.full((n, 2), np.inf)
    ihi = np.full((n, 2), -np.inf)
    np.minimum.at(ilo, tri_isl, tlo)
    np.maximum.at(ihi, tri_isl, thi)
    s_lo = np.minimum(seg_px[:, 0], seg_px[:, 1])
    s_hi = np.maximum(seg_px[:, 0], seg_px[:, 1])
    s_ord, s_st = _grouped(seg_isl, n)
    t_ord, t_st = _grouped(tri_isl, n)
    # gaps
    a, b = box_pairs(ilo, ihi, pad=reach * 0.5 + 0.5)
    keep = isl_unit[a] != isl_unit[b]
    a, b = a[keep], b[keep]
    min_gap = math.inf
    viol_pairs = 0
    unit_gap = {}
    for i, j in zip(a.tolist(), b.tolist()):
        si = s_ord[s_st[i]:s_st[i + 1]]
        sj = s_ord[s_st[j]:s_st[j + 1]]
        r = reach
        si = si[((s_hi[si] >= ilo[j] - r) & (s_lo[si] <= ihi[j] + r)).all(1)]
        sj = sj[((s_hi[sj] >= ilo[i] - r) & (s_lo[sj] <= ihi[i] + r)).all(1)]
        if len(si) == 0 or len(sj) == 0:
            continue
        best = math.inf
        for c in range(0, len(si), 512):
            sc = si[c:c + 512]
            A = np.repeat(sc, len(sj))
            B = np.tile(sj, len(sc))
            # prune by box distance before the exact test
            dx = np.maximum(0, np.maximum(s_lo[B, 0] - s_hi[A, 0], s_lo[A, 0] - s_hi[B, 0]))
            dy = np.maximum(0, np.maximum(s_lo[B, 1] - s_hi[A, 1], s_lo[A, 1] - s_hi[B, 1]))
            m = (dx * dx + dy * dy) < r * r
            if not m.any():
                continue
            A, B = A[m], B[m]
            d = seg_seg_dist(seg_px[A, 0], seg_px[A, 1], seg_px[B, 0], seg_px[B, 1])
            best = min(best, float(d.min()))
        key = (min(isl_unit[i], isl_unit[j]), max(isl_unit[i], isl_unit[j]))
        if best < unit_gap.get(key, (math.inf,))[0]:
            unit_gap[key] = (best, i, j)
        min_gap = min(min_gap, best)
    viol = sorted(v for v in unit_gap.values() if v[0] < margin_px - GAP_TOL)
    viol_pairs = len(viol)
    # overlaps
    a, b = box_pairs(ilo, ihi, pad=0.0)
    keep = isl_unit[a] != isl_unit[b]
    a, b = a[keep], b[keep]
    overlaps = 0
    overlap_units = set()
    overlap_isl = set()
    for i, j in zip(a.tolist(), b.tolist()):
        ti = t_ord[t_st[i]:t_st[i + 1]]
        tj = t_ord[t_st[j]:t_st[j + 1]]
        ti = ti[((thi[ti] > ilo[j]) & (tlo[ti] < ihi[j])).all(1)]
        tj = tj[((thi[tj] > ilo[i]) & (tlo[tj] < ihi[i])).all(1)]
        if len(ti) == 0 or len(tj) == 0:
            continue
        for c in range(0, len(ti), 256):
            tc = ti[c:c + 256]
            A = np.repeat(tc, len(tj))
            B = np.tile(tj, len(tc))
            m = ((thi[A] > tlo[B]) & (thi[B] > tlo[A])).all(1)
            if not m.any():
                continue
            ov = int(sat_overlap(tri_px[A[m]], tri_px[B[m]], eps=1e-6).sum())
            if ov:
                overlaps += ov
                overlap_units.add((isl_unit[i], isl_unit[j]))
                overlap_isl.add((i, j))
    return {'min_gap_px': (None if min_gap == math.inf else min_gap), 'margin_violations': viol_pairs,
            'overlap_tri_pairs': overlaps, 'overlap_unit_pairs': len(overlap_units),
            'violations': [(float(g), int(i), int(j)) for g, i, j in viol[:20]],
            '_offenders': {int(x) for _g, i, j in viol for x in (i, j)} | {int(x) for p_ in overlap_isl for x in p_},
            'overlap_pairs': sorted((int(i), int(j)) for i, j in overlap_units)[:20]}


# ------------------------------------------------------------------------------------------------------------------
# Blender part
# ------------------------------------------------------------------------------------------------------------------

def import_addon():
    """Import the repository's fss_blender_tools (purging a deployed copy loaded at startup) and register it."""
    if 'fss_blender_tools' in sys.modules:
        try:
            sys.modules['fss_blender_tools'].unregister()
        except Exception:
            pass
        for mod in list(sys.modules.keys()):
            if mod == 'fss_blender_tools' or mod.startswith('fss_blender_tools.'):
                del sys.modules[mod]
    root = str(REPO_ROOT)
    while root in sys.path:
        sys.path.remove(root)
    sys.path.insert(0, root)
    import fss_blender_tools
    fss_blender_tools.register()
    from fss_blender_tools import uv_marks, visibility_core
    assert Path(uv_marks.__file__).resolve().is_relative_to(REPO_ROOT), uv_marks.__file__
    return uv_marks, visibility_core


class MeshData:
    """Arrays of one mesh's active UV map, loops, faces and triangles."""

    def __init__(self, me):
        self.me = me
        self.uv_layer = me.uv_layers.active
        nl, nf = len(me.loops), len(me.polygons)
        self.nl, self.nf = nl, nf
        self.LV = np.zeros(nl, np.int64)
        me.loops.foreach_get('vertex_index', self.LV)
        uv = np.zeros(nl * 2, np.float64)
        self.uv_layer.data.foreach_get('uv', uv)
        self.UV = uv.reshape(-1, 2)
        self.PS = np.zeros(nf, np.int64)
        me.polygons.foreach_get('loop_start', self.PS)
        self.PT = np.zeros(nf, np.int64)
        me.polygons.foreach_get('loop_total', self.PT)
        self.MI = np.zeros(nf, np.int64)
        me.polygons.foreach_get('material_index', self.MI)
        self.loop_face = np.repeat(np.arange(nf), self.PT)
        nxt = np.arange(nl) + 1
        last = self.PS + self.PT - 1
        nxt[last] = self.PS
        self.next = nxt
        me.calc_loop_triangles()
        nt = len(me.loop_triangles)
        tl = np.zeros(nt * 3, np.int64)
        me.loop_triangles.foreach_get('loops', tl)
        self.TL = tl.reshape(-1, 3)
        self.TP = np.zeros(nt, np.int64)
        me.loop_triangles.foreach_get('polygon_index', self.TP)
        co = np.zeros(len(me.vertices) * 3, np.float64)
        me.vertices.foreach_get('co', co)
        self.CO = co.reshape(-1, 3)
        self.tri_verts = self.LV[self.TL]

    def face_areas_world(self, matrix_world, cm2_per_bu2):
        M = np.array(matrix_world, dtype=np.float64)
        W = self.CO @ M[:3, :3].T + M[:3, 3]
        P = W[self.tri_verts]
        a = 0.5 * np.linalg.norm(np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]), axis=1)
        return np.bincount(self.TP, weights=a, minlength=self.nf) * cm2_per_bu2

    def face_uv_areas(self):
        return np.bincount(self.TP, weights=tri_area(self.UV[self.TL]), minlength=self.nf)


def _material_of_faces(obj, md):
    slots = obj.material_slots
    mats = [s.material for s in slots]
    keys = np.array([id(m) if m is not None else 0 for m in mats] + [0], dtype=np.int64)
    idx = np.where(md.MI < len(mats), md.MI, len(mats))
    return keys[idx], {(id(m) if m is not None else 0): m for m in mats + [None]}


def gather_sets(view_layer, report):
    """{material key: {'material': mat, 'parts': [(MeshData, users, face indices)]}} over the view layer's mesh
    objects, linked duplicates (one mesh, several objects) once. Library and override data are skipped."""
    by_mesh = {}
    skipped_lib = 0
    for obj in view_layer.objects:
        if obj.type != 'MESH' or obj.data is None:
            continue
        if obj.library or obj.override_library or obj.data.library or obj.data.override_library:
            skipped_lib += 1
            continue
        by_mesh.setdefault(obj.data.name, []).append(obj)
    sets = {}
    no_uv_faces = 0
    conflicts = 0
    for name in sorted(by_mesh):
        users = sorted(by_mesh[name], key=lambda o: o.name)
        me = users[0].data
        if me.uv_layers.active is None or len(me.polygons) == 0:
            no_uv_faces += len(me.polygons)
            continue
        md = MeshData(me)
        fkeys, matmap = _material_of_faces(users[0], md)
        for other in users[1:]:
            ok, _ = _material_of_faces(other, md)
            conflicts += int((ok != fkeys).sum())
        for key in np.unique(fkeys):
            entry = sets.setdefault(int(key), {'material': matmap[int(key)], 'parts': []})
            entry['parts'].append((md, users, np.flatnonzero(fkeys == key)))
    report.update({'skipped_library_objects': skipped_lib, 'faces_without_uv_map': no_uv_faces,
                   'linked_material_conflict_faces': conflicts,
                   'linked_meshes': sum(1 for u in by_mesh.values() if len(u) > 1)})
    return sets


def part_islands(md, faces):
    """Islands of a face subset: faces connected through an edge whose two corners have the same UVs on both sides.
    Returns (face -> local island id, boundary loop indices, island of each boundary loop)."""
    fmask = np.zeros(md.nf, bool)
    fmask[faces] = True
    loops = np.flatnonzero(fmask[md.loop_face])
    lf = md.loop_face[loops]
    v0, v1 = md.LV[loops], md.LV[md.next[loops]]
    # exact float32 equality, as Blender's island detection (BM_loop_uv_share_edge_check)
    q0 = md.UV[loops].astype(np.float32).view(np.int32).astype(np.int64)
    q1 = md.UV[md.next[loops]].astype(np.float32).view(np.int32).astype(np.int64)
    sw = v0 > v1
    va, vb = np.where(sw, v1, v0), np.where(sw, v0, v1)
    qa = np.where(sw[:, None], q1, q0)
    qb = np.where(sw[:, None], q0, q1)
    keys = np.column_stack([va, vb, qa, qb])
    _, inv, cnt = np.unique(keys, axis=0, return_inverse=True, return_counts=True)
    inv = inv.ravel()
    order = np.argsort(inv, kind='stable')
    si = inv[order]
    same = si[1:] == si[:-1]
    fa = lf[order[:-1][same]]
    fb = lf[order[1:][same]]
    local = np.full(md.nf, -1, np.int64)
    local[faces] = np.arange(len(faces))
    roots = components(len(faces), local[fa], local[fb])
    _, isl = np.unique(roots, return_inverse=True)
    bmask = cnt[inv] == 1
    bl = loops[bmask]
    return isl.ravel(), bl, isl.ravel()[local[md.loop_face[bl]]]


ZERO_AREA_PX2 = 1e-6  # UV area in px^2 at or below which an island is a line or a point
FLAT_RATIO = 1e-5  # UV area / UV bbox diagonal^2 at or below which an island is a line (Blender rescales those)
COLLAPSE_Q = 20.0  # UV bbox diagonal / (3D bbox diagonal x density) at the area-based scale: above it, collapsed
STACK_SOURCE_OVERLAPS = False  # see TextureSet._find_stacks
_VIS_CACHE = {}  # mesh name -> get_object_visibility result, for one pack_scene run


class TextureSet:
    """One material's islands with their density ranges, packed into a temporary mesh."""

    def __init__(self, name, material, parts, uv_marks, visibility_core, scene, ignore_directions=False):
        self.name = name
        self.material = material
        self.W, self.H = uv_marks.texture_size(material)
        self.margin_px = int(uv_marks.margin(material))
        self.S = float(max(self.W, self.H))
        self.ax, self.ay = self.W / self.S, self.H / self.S  # region in normalised square-pixel space
        target = uv_marks.target_density(scene)
        bu_cm = scene.unit_settings.scale_length * 100.0
        cm2 = bu_cm * bu_cm
        self.parts = parts
        isl_rows = []  # per island: part index, A_uv(px^2), A3 (cm^2), lo, hi, direction, linked users out of range
        self.face_isl = []  # per part: global island id per part face
        self.bl = []  # per part: boundary loops
        self.bl_isl = []
        self.notes = {'stale_or_missing_visibility_meshes': 0, 'degenerate_islands': 0, 'linked_users_range_differs': 0}
        n_isl = 0
        self.vis_time = 0.0
        for pi, (md, users, faces) in enumerate(parts):
            isl, bl, bl_isl = part_islands(md, faces)
            ni = int(isl.max()) + 1 if len(isl) else 0
            uv_a = np.bincount(isl, weights=md.face_uv_areas()[faces], minlength=ni) * self.W * self.H
            # bounding-box diagonals: UV in square pixels (S), 3D in cm (first user)
            fl = np.zeros(md.nf, bool)
            fl[faces] = True
            lsel = np.flatnonzero(fl[md.loop_face])
            loc = np.full(md.nf, -1, np.int64)
            loc[faces] = np.arange(len(faces))
            li = isl[loc[md.loop_face[lsel]]]
            Mw = np.array(users[0].matrix_world, dtype=np.float64)
            Wc = (md.CO @ Mw[:3, :3].T + Mw[:3, 3])[md.LV[lsel]] * bu_cm
            p_uv = _bbox_diag(md.UV[lsel] * self.S, li, ni)
            p_3d = _bbox_diag(Wc, li, ni)
            # visibility per island (decision 82 via score_face_set); 1.0 when missing or stale
            tv = time.perf_counter()
            vis_data = _VIS_CACHE.get(md.me.name)
            if vis_data is None:
                vis_data = visibility_core.get_object_visibility(users[0]) if bpy.data.filepath else {'stale': True}
                _VIS_CACHE[md.me.name] = vis_data
            if vis_data.get('stale', True):
                self.notes['stale_or_missing_visibility_meshes'] += 1
                vis = np.ones(ni)
            else:
                order = np.argsort(isl, kind='stable')
                st = np.searchsorted(isl[order], np.arange(ni + 1))
                vis = np.array([uv_marks.visibility_factor(
                    visibility_core.score_face_set(users[0], faces[order[st[k]:st[k + 1]]], vis_data=vis_data))
                    for k in range(ni)])
            self.vis_time += time.perf_counter() - tv
            # per user: 3D area and range; the island follows the user that needs the most texture
            best = None
            for u in users:
                a3 = np.bincount(isl, weights=md.face_areas_world(u.matrix_world, cm2)[faces], minlength=ni)
                (flo, fhi), _src = uv_marks.density(u, scene)
                lo, hi = target * flo * vis, target * fhi * vis
                cur = np.sqrt(uv_a / np.maximum(a3, 1e-30))
                need = lo / np.maximum(cur, 1e-30)
                row = (need, a3, lo, hi, u)
                if best is None:
                    best = row
                    first = row
                else:
                    take = need > best[0]
                    best = tuple(np.where(take, r1, r0) if isinstance(r0, np.ndarray) else r0
                                 for r0, r1 in zip(best, row))
                    self.notes['linked_users_range_differs'] += int((np.abs(need - first[0]) > 1e-6 * first[0]).sum())
            _need, a3, lo, hi, _u = best
            direction = 'FREE' if ignore_directions else uv_marks.direction(users[0])[0]
            for k in range(ni):
                isl_rows.append((pi, uv_a[k], a3[k], lo[k], hi[k], direction, p_uv[k], p_3d[k]))
            self.face_isl.append(isl + n_isl)
            self.bl.append(bl)
            self.bl_isl.append(bl_isl + n_isl)
            n_isl += ni
        self.n = n_isl
        self.part_of = np.array([r[0] for r in isl_rows], np.int64)
        self.a_uv = np.array([r[1] for r in isl_rows])
        self.a3 = np.array([r[2] for r in isl_rows])
        self.lo = np.array([r[3] for r in isl_rows])
        self.hi = np.array([r[4] for r in isl_rows])
        self.dirs = np.array([r[5] for r in isl_rows])
        self.cur = np.sqrt(self.a_uv / np.maximum(self.a3, 1e-30))  # as the UVs sit on the W x H texture
        # the unwrap is conformal in UV space (u and v of equal length): packing works on that shape in square-pixel
        # space (X = u W / S, Y = v H / S after the pack), so the current density there uses S x S
        self.cur_sq = self.cur * self.S / math.sqrt(self.W * self.H)
        self.p_uv = np.array([r[6] for r in isl_rows])
        self.p_3d = np.array([r[7] for r in isl_rows])
        # collapsed UVs (a line, a sliver or a point in UV, normal in 3D): scaling by area would blow them up
        # (factors up to 21,294 on the cockpit, one sliver 129,000 px long). Test: the UV bounding-box diagonal at
        # the area-based scale against the 3D bounding-box diagonal x density (an unrolled cylinder gives ~2.2).
        # Above COLLAPSE_Q the island is scaled so that the two diagonals match and is kept out of the density check
        # (reported).
        self.degenerate = (self.a3 <= 1e-12) | ((self.a_uv <= 1e-12) & (self.p_uv <= 1e-9))
        cur_len = self.p_uv / np.maximum(self.p_3d, 1e-30)
        self.cur_sq_len = cur_len
        self.diag_q = cur_len / np.maximum(self.cur * self.S / math.sqrt(self.W * self.H), 1e-30)
        self.collapsed = ~self.degenerate & (self.diag_q > COLLAPSE_Q)
        # zero UV area (a line or a point): Blender's packer ignores or rescales such islands and drops them anywhere
        # (measured: gap 0 to packed islands, a 1 px line made 8.6 px long), and no scale gives them a density. They are left out: UVs unchanged, no metrics.
        flat = self.a_uv * self.S * self.S / (self.W * self.H) <= FLAT_RATIO * self.p_uv ** 2
        self.zero_area = (self.a_uv <= ZERO_AREA_PX2) | flat
        self.notes['zero_area_islands_not_packed'] = int(self.zero_area.sum())
        self.notes['zero_area_objects'] = sorted({self.parts[p][1][0].name for p in self.part_of[self.zero_area]})[:20]
        self.notes['degenerate_islands'] = int(self.degenerate.sum())
        self.notes['collapsed_islands'] = int(self.collapsed.sum())
        self.notes['collapsed_objects'] = sorted({self.parts[p][1][0].name for p in self.part_of[self.collapsed]})[:20]
        self.notes['diag_q_pct_1_50_99_999'] = (np.percentile(self.diag_q[~self.degenerate], [1, 50, 99, 99.9]).round(3).tolist()
                                             if (~self.degenerate).any() else None)
        self.upright = np.isin(self.dirs, ['UPRIGHT', 'FLIP'])
        self.quarter = bool((self.dirs == 'QUARTER').any())
        self._build_temp()
        self._find_stacks()

    # ---- temporary mesh ------------------------------------------------------------------------------------------
    def _build_temp(self):
        verts, loops_v, loop_uv, face_start, face_isl = [], [], [], [], []
        self.loop_src = []  # per part: original loop indices in temp loop order
        voff = 0
        loff = 0
        for pi, (md, users, faces) in enumerate(self.parts):
            fmask = np.zeros(md.nf, bool)
            fmask[faces] = True
            lsel = np.flatnonzero(fmask[md.loop_face])
            used, vremap = np.unique(md.LV[lsel], return_inverse=True)
            M = np.array(users[0].matrix_world, dtype=np.float64)
            verts.append(md.CO[used] @ M[:3, :3].T + M[:3, 3])
            loops_v.append(vremap.ravel() + voff)
            loop_uv.append(md.UV[lsel])
            # faces of the part in loop order (loop_start ascending)
            fo = faces[np.argsort(md.PS[faces])]
            face_start.append(np.cumsum(np.concatenate([[0], md.PT[fo][:-1]])) + loff)
            fi = np.full(md.nf, -1, np.int64)
            fi[faces] = self.face_isl[pi]
            face_isl.append(fi[fo])
            self.loop_src.append(lsel)
            voff += len(used)
            loff += len(lsel)
        nl = loff
        self.n_loops = nl
        self.face_island = np.concatenate(face_isl)
        nf = len(self.face_island)
        # one proxy quad per island (its bounding box, packed instead of the island when Blender's hull of the
        # island fails), then two anchor triangles (set the ORIGINAL_AABB region)
        n = self.n
        self.n_extra = 4 * n + 6
        V = np.concatenate(verts + [np.zeros((4 * n + 6, 3))])
        LVt = np.concatenate(loops_v + [np.arange(voff, voff + 4 * n + 6)])
        FS = np.concatenate(face_start + [nl + 4 * np.arange(n), np.array([nl + 4 * n, nl + 4 * n + 3])])
        self.uv0 = np.concatenate(loop_uv)  # original UVs of the set, temp loop order
        self.loop_face_t = np.repeat(np.arange(nf), np.diff(np.concatenate([FS[:nf], [nl]])))
        self.loop_isl = self.face_island[self.loop_face_t]
        me = bpy.data.meshes.new('FSS_PACK_TMP_' + self.name)
        me.vertices.add(len(V))
        me.vertices.foreach_set('co', V.astype(np.float32).ravel())
        me.loops.add(nl + 4 * n + 6)
        me.loops.foreach_set('vertex_index', LVt.astype(np.int32))
        me.polygons.add(nf + n + 2)
        me.polygons.foreach_set('loop_start', FS.astype(np.int32))
        me.update(calc_edges=True)
        me.uv_layers.new(name='UVMap')
        self.me = me
        self.n_faces = nf
        ev = np.zeros(len(me.edges) * 2, np.int64)
        me.edges.foreach_get('vertices', ev)
        self.edge_verts = ev.reshape(-1, 2)
        self.loop_vert_t = LVt  # vertex of each temp loop
        self.loop_count_t = np.diff(np.concatenate([FS, [nl + 4 * n + 6]]))  # loops per temp face
        self.proxy = np.zeros(n, bool)  # islands packed through their proxy quad
        self.obj = bpy.data.objects.new('FSS_PACK_TMP_' + self.name, me)
        bpy.context.scene.collection.objects.link(self.obj)
        # triangles: the source meshes' own triangulation (a concave or folded UV n-gon has a different area under
        # another triangulation), mapped to temp loops
        tl_all, ti_all = [], []
        off = 0
        for pi, lsel in enumerate(self.loop_src):
            md, _users, faces = self.parts[pi]
            fm = np.zeros(md.nf, bool)
            fm[faces] = True
            tm = fm[md.TP]
            tl_all.append(np.searchsorted(lsel, md.TL[tm]) + off)
            fi = np.full(md.nf, -1, np.int64)
            fi[faces] = self.face_isl[pi]
            ti_all.append(fi[md.TP[tm]])
            off += len(lsel)
        self.TLt = np.concatenate(tl_all)
        self.tri_isl = np.concatenate(ti_all)
        # boundary loops in temp order
        bl_t, bl_i = [], []
        off = 0
        for pi, lsel in enumerate(self.loop_src):
            pos = np.searchsorted(lsel, self.bl[pi])
            md = self.parts[pi][0]
            nxt_pos = np.searchsorted(lsel, md.next[self.bl[pi]])
            bl_t.append(np.stack([pos + off, nxt_pos + off], 1))
            bl_i.append(self.bl_isl[pi])
            off += len(lsel)
        self.seg_loops = np.concatenate(bl_t) if bl_t else np.zeros((0, 2), np.int64)
        self.seg_isl = np.concatenate(bl_i) if bl_i else np.zeros(0, np.int64)

    def px(self, uv):
        """UV -> pixels of the set's texture."""
        return uv * np.array([self.W, self.H])

    def _find_stacks(self):
        """Islands of one mesh that overlap in the source UVs. Decision 3 names only shared mesh data and Mirror or
        Array copies as stacking units, and both share UVs by construction (one mesh is packed once; modifier copies
        follow their base). Overlaps inside one mesh are therefore counted, not kept: with STACK_SOURCE_OVERLAPS each
        overlapping group becomes one unit with the scale of its largest island (its other islands then leave their
        density ranges)."""
        if not STACK_SOURCE_OVERLAPS:
            self.source_overlap_islands = None  # not scanned (costly on unpacked source UVs: 156 s on Cockpit_STD)
            self.unit = np.arange(self.n)
            self.n_units = self.n
            self.stack_units = 0
            self.stacked_islands = 0
            self.unit_lead = np.arange(self.n)
            return
        T = self.px(self.uv0[self.TLt])
        lo = np.full((self.n, 2), np.inf)
        hi = np.full((self.n, 2), -np.inf)
        np.minimum.at(lo, self.tri_isl, T.min(1))
        np.maximum.at(hi, self.tri_isl, T.max(1))
        a, b = box_pairs(lo, hi)
        same_part = self.part_of[a] == self.part_of[b]
        a, b = a[same_part], b[same_part]
        t_ord, t_st = _grouped(self.tri_isl, self.n)
        tlo, thi = T.min(1), T.max(1)
        ea, eb = [], []
        for i, j in zip(a.tolist(), b.tolist()):
            ti = t_ord[t_st[i]:t_st[i + 1]]
            tj = t_ord[t_st[j]:t_st[j + 1]]
            ti = ti[((thi[ti] > lo[j]) & (tlo[ti] < hi[j])).all(1)]
            tj = tj[((thi[tj] > lo[i]) & (tlo[tj] < hi[i])).all(1)]
            hit = False
            for c in range(0, len(ti), 256):
                tc = ti[c:c + 256]
                A = np.repeat(tc, len(tj))
                B = np.tile(tj, len(tc))
                m = ((thi[A] > tlo[B]) & (thi[B] > tlo[A])).all(1)
                if m.any() and sat_overlap(T[A[m]], T[B[m]], eps=1e-4).any():
                    hit = True
                    break
            if hit:
                ea.append(i)
                eb.append(j)
        roots = components(self.n, ea, eb)
        sizes0 = np.bincount(np.unique(roots, return_inverse=True)[1].ravel())
        self.source_overlap_islands = int(sizes0[sizes0 > 1].sum())
        if not STACK_SOURCE_OVERLAPS:
            roots = np.arange(self.n)
        _, self.unit = np.unique(roots, return_inverse=True)
        self.unit = self.unit.ravel()
        self.n_units = int(self.unit.max()) + 1 if self.n else 0
        sizes = np.bincount(self.unit, minlength=self.n_units)
        self.stack_units = int((sizes > 1).sum())
        self.stacked_islands = int(sizes[sizes > 1].sum())
        # the unit's scale follows its largest island
        order = np.lexsort((-self.a_uv, self.unit))
        first = np.ones(len(order), bool)
        first[1:] = self.unit[order][1:] != self.unit[order][:-1]
        self.unit_lead = np.zeros(self.n_units, np.int64)
        self.unit_lead[self.unit[order][first]] = order[first]

    def densities(self, t):
        return self.lo + t * (self.hi - self.lo)

    def unit_scale(self, t):
        """Linear UV scale per unit for density t (lead island of each unit), 1.0 for degenerate islands."""
        d = self.densities(t)
        f = np.where(self.collapsed, d / np.maximum(self.cur_sq_len, 1e-30), d / np.maximum(self.cur_sq, 1e-30))
        f = np.where(self.degenerate, 1.0, f)
        return f[self.unit_lead]

    # ---- one pack --------------------------------------------------------------------------------------------------
    def _prepared_uv(self, t):
        """Normalised square-pixel coordinates (u W / S, v H / S) of every loop, each unit scaled about its own
        centre to density t and spread on shelves so that no two units overlap (merge_overlap must merge only
        deliberate stacks). Returns (coords, region corner)."""
        P = self.uv0.copy()  # conformal island shapes; to_uv() divides by (ax, ay) after the pack
        lu = self.unit[self.loop_isl]
        lo = np.full((self.n_units, 2), np.inf)
        hi = np.full((self.n_units, 2), -np.inf)
        np.minimum.at(lo, lu, P)
        np.maximum.at(hi, lu, P)
        c = 0.5 * (lo + hi)
        f = self.unit_scale(t)
        P = c[lu] + (P - c[lu]) * f[lu][:, None]
        lo = c + (lo - c) * f[:, None]
        hi = c + (hi - c) * f[:, None]
        size = hi - lo
        g = 4.0 * (self.margin_px + 2) / self.S
        order = np.argsort(-size[:, 1], kind='stable')
        aspect = self.ax / self.ay
        row_w = math.sqrt(float(((size[:, 0] + g) * (size[:, 1] + g)).sum()) * aspect)
        row_w = max(row_w, float(size[:, 0].max()) + g)
        off = np.zeros((self.n_units, 2))
        x = y = g
        row_h = 0.0
        for u in order.tolist():
            if x + size[u, 0] > row_w + g and x > g:
                x = g
                y += row_h + g
                row_h = 0.0
            off[u] = (x, y)
            x += size[u, 0] + g
            row_h = max(row_h, size[u, 1])
        P = P - lo[lu] + off[lu]
        sw = float(P[:, 0].max()) + g
        sh = float(P[:, 1].max()) + g
        ry = max(sh, sw / aspect)
        return P, (ry * aspect, ry)

    def pack(self, t, rotate_method=None, pin_upright=True, rotate=True, shape_method='CONCAVE', margin_extra=None):
        """Pack at density t; returns (final coords in normalised space, k, extent px (x, y), pack seconds)."""
        P, (rx, ry) = self._prepared_uv(t)
        a = ANCHOR_PX / self.S
        anchors = np.array([[0, 0], [a, 0], [0, a], [rx - a, ry], [rx, ry - a], [rx, ry]], dtype=np.float64)
        n = self.n
        lo = np.full((n, 2), np.inf)
        hi = np.full((n, 2), -np.inf)
        np.minimum.at(lo, self.loop_isl, P)
        np.maximum.at(hi, self.loop_isl, P)
        lo = np.where(np.isfinite(lo), lo, 0.0)
        hi = np.where(np.isfinite(hi), hi, 0.0)
        quads = np.stack([lo, np.stack([hi[:, 0], lo[:, 1]], 1), hi, np.stack([lo[:, 0], hi[:, 1]], 1)], 1)
        allp = np.concatenate([P, quads.reshape(-1, 2), anchors])
        me = self.me
        me.uv_layers['UVMap'].data.foreach_set('uv', allp.astype(np.float32).ravel())
        # faces packed: the real faces of normal islands, the proxy quads of proxy islands, the anchors; zero-area
        # islands are not packed (Blender packs only selected faces and leaves the others untouched: measured)
        packed = ~self.zero_area
        fsel = np.concatenate([(packed & ~self.proxy)[self.face_island], packed & self.proxy, np.ones(2, bool)])
        me.polygons.foreach_set('select', fsel)
        vsel = np.zeros(len(me.vertices), bool)
        vsel[self.loop_vert_t[np.repeat(fsel, self.loop_count_t)]] = True
        me.vertices.foreach_set('select', vsel)
        me.edges.foreach_set('select', vsel[self.edge_verts].all(1))
        pins = np.zeros(self.n_loops + self.n_extra, bool)
        use_pin = pin_upright and bool(self.upright.any())
        if use_pin:
            pins[:self.n_loops] = self.upright[self.loop_isl]
            pins[self.n_loops:self.n_loops + 4 * n] = np.repeat(self.upright, 4)
        if len(me.uv_layers['UVMap'].pin) == 0:  # the pin layer exists only once something is pinned
            me.attributes.new(name='.pn.UVMap', type='BOOLEAN', domain='CORNER')
        me.uv_layers['UVMap'].pin.foreach_set('value', pins)
        if rotate_method is None:
            rotate_method = 'CARDINAL' if self.quarter else 'ANY'
        vl = bpy.context.view_layer
        for o in vl.objects:
            if o.select_get():
                o.select_set(False)
        vl.objects.active = self.obj
        self.obj.select_set(True)
        tool = bpy.context.scene.tool_settings
        sel_mode = tuple(tool.mesh_select_mode)
        tool.mesh_select_mode = (False, False, True)
        bpy.ops.object.mode_set(mode='EDIT')
        t0 = time.perf_counter()
        bpy.ops.uv.pack_islands(udim_source='ORIGINAL_AABB', rotate=rotate, rotate_method=rotate_method, scale=False,
                                merge_overlap=True, margin_method='ADD',
                                margin=(self.margin_px + (MARGIN_EXTRA if margin_extra is None else margin_extra)) * 0.5 / self.S,
                                pin=use_pin, pin_method='ROTATION', shape_method=shape_method)
        dt = time.perf_counter() - t0
        bpy.ops.object.mode_set(mode='OBJECT')
        tool.mesh_select_mode = sel_mode
        out = np.zeros((self.n_loops + self.n_extra) * 2, np.float32)
        me.uv_layers['UVMap'].data.foreach_get('uv', out)
        out = out.reshape(-1, 2).astype(np.float64)
        Q = out[:self.n_loops].copy()
        if self.proxy.any():
            # a proxy island follows its quad's rigid move (rotation of the first edge, move of the centre)
            q1 = out[self.n_loops:self.n_loops + 4 * n].reshape(-1, 4, 2)
            e0 = quads[:, 1] - quads[:, 0]
            e1 = q1[:, 1] - q1[:, 0]
            ang = np.arctan2(e1[:, 1], e1[:, 0]) - np.arctan2(e0[:, 1], e0[:, 0])
            c0 = quads.mean(1)
            c1 = q1.mean(1)
            pl = self.proxy[self.loop_isl] & ~self.zero_area[self.loop_isl]
            li = self.loop_isl[pl]
            ca, sa = np.cos(ang[li]), np.sin(ang[li])
            d = P[pl] - c0[li]
            Q[pl] = np.stack([ca * d[:, 0] - sa * d[:, 1], sa * d[:, 0] + ca * d[:, 1]], 1) + c1[li]
        zl = self.zero_area[self.loop_isl]
        Q[zl] = self.uv0[zl] * np.array([self.ax, self.ay])
        Qp = Q[~zl] if (~zl).any() else Q
        ext = Qp.max(0) * self.S
        if Qp.min() < -1e-7:
            ext = ext + np.maximum(0, -Qp.min(0) * self.S)
        k = max(ext[0] / self.W, ext[1] / self.H)
        return Q, k, ext, dt, P

    def to_uv(self, Q):
        return Q / np.array([self.ax, self.ay])

    def remove_temp(self):
        bpy.data.objects.remove(self.obj)
        bpy.data.meshes.remove(self.me)
        bpy.context.view_layer.update()


def search(ts, max_extra=6, **pack_kw):
    """Decision 113: t = 1 if it fits, else the largest t that fits (secant steps on k(t) - 1, kept inside the
    bracket), else t = 0 (overflow, k > 1). Returns the chosen pack and the trace."""
    trace = []

    def run(t):
        Q, k, ext, dt, P = ts.pack(t, **pack_kw)
        trace.append({'t': t, 'k': k, 'pack_s': dt})
        return {'t': t, 'Q': Q, 'k': k, 'ext': ext, 'pre': P}

    r1 = run(1.0)
    if r1['k'] <= 1.0:
        return r1, trace, 'underflow'
    r0 = run(0.0)
    if r0['k'] > 1.0:
        return r0, trace, 'overflow'
    lo, hi = r0, r1
    for _ in range(max_extra):
        if hi['t'] - lo['t'] < 0.01:
            break
        # k is close to linear in the density scale: interpolate where k crosses 1 (aim a little below it)
        tt = lo['t'] + (hi['t'] - lo['t']) * (0.995 - lo['k']) / max(hi['k'] - lo['k'], 1e-9)
        span = hi['t'] - lo['t']
        tt = min(max(tt, lo['t'] + 0.1 * span), hi['t'] - 0.1 * span)
        r = run(tt)
        if r['k'] <= 1.0:
            lo = r
        else:
            hi = r
    return lo, trace, 'fit'


def pack_set(ts):
    """Search (decision 113) with Blender's CONCAVE shapes, then measure the layout. Islands named in a margin
    violation or an overlap are packed through their proxy quad (bounding box; the island follows the quad's rigid
    move) in the next round, up to three more rounds; then the whole set falls back to AABB shapes, whose margin is
    exact. Measured on the cockpit: Blender's concave and convex margins cut corners (6.2 to 7.9 px for 8.1 px
    requested) and zero-area triangles inside an island are left out of its hull (the island lands on others); every
    island named was of that kind. Returns (result, packs, mode, metrics, attempts)."""
    attempts = []
    trace_all = []
    extra = MARGIN_EXTRA
    plan = [('CONCAVE', extra)]
    while plan:
        shape, extra = plan.pop(0)
        res, trace, mode = search(ts, shape_method=shape, margin_extra=extra)
        trace_all += [dict(x, shape_method=shape) for x in trace]
        row = evaluate(ts, res, mode)
        attempts.append({'shape_method': shape, 'margin_extra': extra, 'packs': len(trace), 't': res['t'],
                         'k': res['k'], 'min_gap_px': row['min_gap_px'], 'margin_violations': row['margin_violations'],
                         'overlap_tri_pairs': row['overlap_tri_pairs']})
        attempts[-1]['proxy_islands'] = int(ts.proxy.sum())
        offenders = row.pop('_offenders')
        if row['margin_violations'] == 0 and row['overlap_tri_pairs'] == 0:
            break
        if shape == 'CONCAVE' and len(attempts) < 4:
            ts.proxy[sorted(offenders)] = True
            plan = [('CONCAVE', extra)]
        elif shape != 'AABB':
            ts.proxy[:] = False
            plan = [('AABB', MARGIN_EXTRA)]
    row['proxy_islands'] = int(ts.proxy.sum())
    row['shape_method'] = attempts[-1]['shape_method']
    row['margin_requested_px'] = ts.margin_px + attempts[-1]['margin_extra']
    return res, trace_all, mode, row, attempts


def evaluate(ts, res, mode):
    """Metrics of a chosen pack, from the coordinates written back (pixel space of the texture)."""
    uv = ts.to_uv(res['Q'])
    px = ts.px(uv)
    tri = px[ts.TLt]
    seg = px[ts.seg_loops]
    kt = ~ts.zero_area[ts.tri_isl]
    ks = ~ts.zero_area[ts.seg_isl]
    m = layout_metrics(tri[kt], ts.tri_isl[kt], seg[ks], ts.seg_isl[ks], ts.unit, ts.margin_px)
    # density per island against its range
    a_uv = np.bincount(ts.tri_isl, weights=tri_area(tri), minlength=ts.n)
    d = np.sqrt(a_uv / np.maximum(ts.a3, 1e-30))
    ok = ~ts.degenerate & ~ts.collapsed & ~ts.zero_area
    below = np.where(d < ts.lo, (ts.lo - d) / ts.lo, 0.0)
    above = np.where(d > ts.hi, (d - ts.hi) / ts.hi, 0.0)
    dev = np.maximum(below, above)[ok]
    w = ts.a3[ok]
    want = ts.densities(res['t'])[ok]
    rel = np.abs(d[ok] - want) / want
    lead = np.zeros(ts.n, bool)
    lead[ts.unit_lead] = True
    lead = lead[ok]
    # rigid moves: each island keeps its prepared size (area ratio) and, if upright, its orientation
    pre_tri = ts.px(ts.to_uv(res['pre']))[ts.TLt]
    area_ratio = a_uv / np.maximum(np.bincount(ts.tri_isl, weights=tri_area(pre_tri), minlength=ts.n), 1e-30)
    up_err = 0.0
    if ts.upright.any():
        e_new = seg[:, 1] - seg[:, 0]
        pre_seg = ts.px(ts.to_uv(res['pre']))[ts.seg_loops]
        e_old = pre_seg[:, 1] - pre_seg[:, 0]
        sel = ts.upright[ts.seg_isl] & (np.linalg.norm(e_old, axis=1) > 1e-3)
        if sel.any():
            ang = np.arctan2(e_old[sel, 0] * e_new[sel, 1] - e_old[sel, 1] * e_new[sel, 0],
                             (e_old[sel] * e_new[sel]).sum(1))
            up_err = float(np.abs(ang).max())
    area_px = float(a_uv.sum())
    k = res['k']
    need = (next_pow2(k * ts.W), next_pow2(k * ts.H))
    return dict(m, **{
        'set': ts.name, 'islands': ts.n, 'units': ts.n_units, 'stack_units': ts.stack_units,
        'stacked_islands': ts.stacked_islands, 'source_overlap_islands': ts.source_overlap_islands, 'size': [ts.W, ts.H], 'margin_px': ts.margin_px,
        'mode': mode, 't': res['t'], 'k': k, 'extent_px': [float(res['ext'][0]), float(res['ext'][1])],
        'needed_size': list(need),
        'fill_texture_pct': 100.0 * area_px / (ts.W * ts.H),
        'fill_k_pct': 100.0 * area_px / (k * k * ts.W * ts.H) if k > 0 else None,
        'fill_needed_pct': 100.0 * area_px / (need[0] * need[1]),
        'area_3d_cm2': float(ts.a3.sum()),
        'density_out_of_range_max': float(dev.max()) if len(dev) else 0.0,
        'density_out_of_range_max_ge1px': float(dev[a_uv[ok] >= 1.0].max())
        if (a_uv[ok] >= 1.0).any() else 0.0,
        'islands_below_1px2': int((a_uv[ok] < 1.0).sum()),
        'density_out_of_range_max_ge100px': float(dev[a_uv[ok] >= 100.0].max()) if (a_uv[ok] >= 100.0).any() else 0.0,
        'density_out_of_range_mean_aw': float((dev * w).sum() / max(w.sum(), 1e-30)) if len(dev) else 0.0,
        'density_vs_t_max_lead': float(rel[lead].max()) if lead.any() else 0.0,
        'density_vs_t_max_all': float(rel.max()) if len(rel) else 0.0,
        'area_ratio_dev_max': float(np.abs(area_ratio[ok] - 1).max()) if ok.any() else 0.0,
        'upright_rotation_err_rad': up_err,
        'lo_range': [float(ts.lo.min()), float(ts.lo.max())] if ts.n else None,
        'hi_range': [float(ts.hi.min()), float(ts.hi.max())] if ts.n else None,
        'notes': ts.notes,
    })


def write_back(ts, res):
    """Write the chosen layout into the source meshes' active UV maps (only the set's loops)."""
    uv = ts.to_uv(res['Q'])
    off = 0
    for pi, (md, users, faces) in enumerate(ts.parts):
        lsel = ts.loop_src[pi]
        md.UV[lsel] = uv[off:off + len(lsel)]
        off += len(lsel)
        md.uv_layer.data.foreach_set('uv', md.UV.astype(np.float32).ravel())


def context_state():
    vl = bpy.context.view_layer
    return {'active': vl.objects.active.name if vl.objects.active else None,
            'selected': sorted(o.name for o in vl.objects if o.select_get()),
            'mode': bpy.context.mode,
            'sync': bpy.context.scene.tool_settings.use_uv_select_sync}


def restore_state(st):
    vl = bpy.context.view_layer
    vl.update()
    for o in vl.objects:
        if o is not None:
            o.select_set(o.name in st['selected'])
    vl.objects.active = bpy.data.objects.get(st['active']) if st['active'] else None
    bpy.context.scene.tool_settings.use_uv_select_sync = st['sync']


def mesh_state(meshes):
    """Per mesh: active UV map name, pin layer presence and pin count, selected face count (for the restore check)."""
    out = {}
    for me in meshes:
        uvl = me.uv_layers.active
        sel = np.zeros(len(me.polygons), bool)
        me.polygons.foreach_get('select', sel)
        pins = None
        if uvl is not None:
            names = {a.name for a in me.attributes}
            pins = [n for n in names if n.startswith('.pn.')]
        out[me.name] = (uvl.name if uvl else None, tuple(sorted(pins or [])), int(sel.sum()))
    return out


def pack_scene(uv_marks, visibility_core, set_filter=None, export_sets=(), ignore_directions=False, dir_study=(),
               write=True):
    """Pack every texture set of the view layer. Returns (rows, report)."""
    scene = bpy.context.scene
    st = context_state()
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    sync = scene.tool_settings.use_uv_select_sync
    scene.tool_settings.use_uv_select_sync = True
    report = {}
    _VIS_CACHE.clear()
    t_all = time.perf_counter()
    sets = gather_sets(bpy.context.view_layer, report)
    meshes = {md.me for e in sets.values() for (md, _u, _f) in e['parts']}
    before = mesh_state(meshes)
    rows = []
    names = {}
    for key, e in sets.items():
        mat = e['material']
        names[key] = mat.name if mat is not None else '<no material>'
    keys = sorted(sets, key=lambda k_: names[k_])
    for key in keys:
        name = names[key]
        if set_filter and name not in set_filter:
            continue
        t0 = time.perf_counter()
        ts = TextureSet(name, sets[key]['material'], sets[key]['parts'], uv_marks, visibility_core, scene,
                        ignore_directions=ignore_directions)
        t_build = time.perf_counter() - t0
        res, trace, mode, row, attempts = pack_set(ts)
        t_search = time.perf_counter() - t0 - t_build
        row.update({'packs': len(trace), 'trace': trace, 'attempts': attempts, 'time_s': time.perf_counter() - t0, 'build_s': t_build,
                    'search_s': t_search, 'vis_s': ts.vis_time,
                    'pack_s': sum(x['pack_s'] for x in trace)})
        if name in dir_study:
            row['direction_study'] = direction_study(ts, res['t'], shape_method=attempts[-1]['shape_method'],
                                                     margin_extra=attempts[-1]['margin_extra'])
        if name in export_sets:
            export_set(ts, res, row)
        if write:
            write_back(ts, res)
        ts.remove_temp()
        rows.append(row)
        log('SET', json.dumps({k_: row[k_] for k_ in ('set', 'islands', 'mode', 't', 'k', 'needed_size',
                                                      'fill_texture_pct', 'min_gap_px', 'margin_violations',
                                                      'overlap_tri_pairs', 'density_out_of_range_max',
                                                      'packs', 'time_s', 'pack_s')}))
    after = mesh_state(meshes)
    scene.tool_settings.use_uv_select_sync = sync
    restore_state(st)
    report['restore_ok'] = (before == after) and (context_state() == st)
    report['total_s'] = time.perf_counter() - t_all
    return rows, report


def direction_study(ts, t, **pack_kw):
    """Layout size k at the same t with each direction rule, on the same islands (cost of the rules)."""
    out = {}
    saved = ts.upright.copy(), ts.quarter
    for label, up, q, rot in (('free_any', False, False, True), ('all_upright_pinned', True, False, True),
                              ('cardinal', False, True, True), ('no_rotation', False, False, False)):
        ts.upright = np.full(ts.n, up)
        ts.quarter = q
        _Q, k, _e, dt, _P = ts.pack(t, rotate=rot, **pack_kw)
        out[label] = {'k': k, 'pack_s': dt}
    ts.upright, ts.quarter = saved
    return out


def export_set(ts, res, row):
    """Save the chosen layout (pixels) and the islands for the venv steps (images, grid packer comparison)."""
    OUT.mkdir(parents=True, exist_ok=True)
    uv = ts.to_uv(res['Q'])
    px = ts.px(uv)
    np.savez_compressed(OUT / f'set_{_safe(ts.name)}.npz', tri_px=px[ts.TLt].astype(np.float32),
                        tri_isl=ts.tri_isl, unit=ts.unit, a3=ts.a3, seg_px=px[ts.seg_loops].astype(np.float32),
                        seg_isl=ts.seg_isl, W=ts.W, H=ts.H, margin=ts.margin_px, k=res['k'], t=res['t'],
                        row=json.dumps({k_: v for k_, v in row.items() if k_ != 'trace'}))


def _safe(name):
    return ''.join(c if c.isalnum() or c in '-_' else '_' for c in name)


# ------------------------------------------------------------------------------------------------------------------
# Synthetic tests
# ------------------------------------------------------------------------------------------------------------------

def _reset_scene():
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for coll in (bpy.data.objects, bpy.data.meshes, bpy.data.materials):
        for item in list(coll):
            coll.remove(item)


def _quad_obj(name, rects, mats=None, scale=(1, 1, 1), uv_rects=None, mesh=None):
    """An object of separate quads: rects are (x, y, w, h) in metres in the XY plane; UV per quad = its own rect
    times 0.1 (or uv_rects); mats: material per quad."""
    if mesh is None:
        me = bpy.data.meshes.new(name)
        verts, faces = [], []
        for i, (x, y, w, h) in enumerate(rects):
            b = len(verts)
            verts += [(x, y, 0), (x + w, y, 0), (x + w, y + h, 0), (x, y + h, 0)]
            faces.append((b, b + 1, b + 2, b + 3))
        me.from_pydata(verts, [], faces)
        uvl = me.uv_layers.new(name='UVMap')
        lv = np.zeros(len(me.loops), np.int64)
        me.loops.foreach_get('vertex_index', lv)
        if uv_rects is None:
            uvc = np.array(verts)[:, :2] * 0.1
        else:
            uvc = []
            for (u, v, w, h) in uv_rects:
                uvc += [(u, v), (u + w, v), (u + w, v + h), (u, v + h)]
            uvc = np.array(uvc)
        uvl.data.foreach_set('uv', uvc[lv].ravel())
        if mats:
            for m in dict.fromkeys(mats):
                me.materials.append(m)
            idx = [list(dict.fromkeys(mats)).index(m) for m in mats]
            me.polygons.foreach_set('material_index', idx)
        mesh = me
    obj = bpy.data.objects.new(name, mesh)
    obj.scale = scale
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.update()
    return obj


def _mat(name, w=4096, h=4096, margin=8):
    m = bpy.data.materials.new(name)
    m.fss_uv_texture_width = str(w)
    m.fss_uv_texture_height = str(h)
    m.fss_uv_margin_px = margin
    return m


def _check(results, name, cond, detail):
    results.append((name, bool(cond), detail))
    log('CASE', 'PASS' if cond else 'FAIL', name, detail)


def _row_ok(r):
    return r['margin_violations'] == 0 and r['overlap_tri_pairs'] == 0 and r['density_out_of_range_max'] <= RANGE_TOL


def margin_probe():
    """Measure the gap Blender leaves between islands for each margin_method at scale=False (and at scale=True)."""
    out = []
    rng = np.random.default_rng(7)
    for method in ('SCALED', 'ADD', 'FRACTION'):
        for scale in (False, True):
            for m_px in (8, 32):
                _reset_scene()
                rects = [(i * 0.5, 0, float(rng.uniform(0.05, 0.3)), float(rng.uniform(0.05, 0.3))) for i in range(40)]
                obj = _quad_obj('M', rects)
                # rotate UVs of each quad by a random angle so the gaps are not only axis aligned
                me = obj.data
                uv = np.zeros(len(me.loops) * 2)
                me.uv_layers.active.data.foreach_get('uv', uv)
                uv = uv.reshape(-1, 4, 2)
                c = uv.mean(1, keepdims=True)
                ang = rng.uniform(0, np.pi, len(uv))
                R = np.stack([np.cos(ang), -np.sin(ang), np.sin(ang), np.cos(ang)], 1).reshape(-1, 2, 2)
                uv = np.einsum('nij,nvj->nvi', R, uv - c) + c
                me.uv_layers.active.data.foreach_set('uv', uv.ravel())
                bpy.context.view_layer.objects.active = obj
                obj.select_set(True)
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_all(action='SELECT')
                bpy.context.scene.tool_settings.use_uv_select_sync = True
                bpy.ops.uv.select_all(action='SELECT')
                bpy.ops.uv.pack_islands(udim_source='CLOSEST_UDIM', rotate=True, rotate_method='ANY', scale=scale,
                                        merge_overlap=True, margin_method=method, margin=m_px / 4096,
                                        shape_method='CONCAVE')
                bpy.ops.object.mode_set(mode='OBJECT')
                me.uv_layers.active.data.foreach_get('uv', uv.ravel())
                P = uv.reshape(-1, 4, 2) * 4096
                tri = np.concatenate([P[:, [0, 1, 2]], P[:, [0, 2, 3]]])
                tri_isl = np.concatenate([np.arange(40), np.arange(40)])
                seg = np.concatenate([P[:, [0, 1]], P[:, [1, 2]], P[:, [2, 3]], P[:, [3, 0]]])
                seg_isl = np.tile(np.arange(40), 4)
                met = layout_metrics(tri, tri_isl, seg, seg_isl, np.arange(40), m_px, reach=40.0 * m_px)
                border = float(P.reshape(-1, 2).min())
                out.append({'method': method, 'scale': scale, 'margin_px': m_px, 'gap_px': met['min_gap_px'],
                            'gap_over_margin': (met['min_gap_px'] or math.nan) / m_px, 'border_px': border})
                log('MARGIN', json.dumps(out[-1]))
    return out


def overflow_probe():
    """How Blender places islands that do not fit with scale=False (CLOSEST_UDIM, ORIGINAL_AABB)."""
    out = []
    for src in ('CLOSEST_UDIM', 'ORIGINAL_AABB'):
        rng = np.random.default_rng(3)
        _reset_scene()
        rects = [(float(rng.uniform(0, 10)), float(rng.uniform(0, 10)), float(rng.uniform(1, 4)),
                  float(rng.uniform(1, 4))) for _ in range(30)]
        # UV = 0.1 x position: the islands overlap and span ~[0, 1.4]^2 before packing
        obj = _quad_obj('O', rects)
        me = obj.data
        area = float(sum(w * h for (_x, _y, w, h) in rects)) * 0.01
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.context.scene.tool_settings.use_uv_select_sync = True
        bpy.ops.uv.select_all(action='SELECT')
        bpy.ops.uv.pack_islands(udim_source=src, rotate=True, rotate_method='ANY', scale=False, merge_overlap=False,
                                margin_method='ADD', margin=4 / 4096, shape_method='CONCAVE')
        bpy.ops.object.mode_set(mode='OBJECT')
        uv = np.zeros(len(me.loops) * 2)
        me.uv_layers.active.data.foreach_get('uv', uv)
        P = uv.reshape(-1, 2)
        lo, hi = P.min(0), P.max(0)
        out.append({'udim_source': src, 'island_area': area, 'bounds_lo': lo.tolist(), 'bounds_hi': hi.tolist(),
                    'fill_of_bounds_pct': 100 * area / float(np.prod(hi - lo))})
        log('OVERFLOW', json.dumps(out[-1]))
    return out


def run_synthetic(uv_marks, visibility_core):
    results = []
    probes = {'margin': margin_probe(), 'overflow': overflow_probe()}

    def scene_setup(fmin=1.0, fmax=1.0, target=20.48):
        sc = bpy.context.scene
        sc.fss_uv_target_density = target
        sc.fss_uv_density_freedom_min = fmin
        sc.fss_uv_density_freedom_max = fmax

    # 1. exact density, non-uniform object scale
    _reset_scene()
    scene_setup()
    m = _mat('EXACT')
    rects = [(0, 0, 0.5, 0.2), (1, 0, 0.1, 0.3), (2, 0, 0.25, 0.25)]
    _quad_obj('EX_A', rects, mats=[m] * 3, scale=(2.0, 1.0, 1.0))
    _quad_obj('EX_B', [(0, 0, 0.3, 0.3)], mats=[m], scale=(1.0, 1.0, 0.5))
    rows, rep = pack_scene(uv_marks, visibility_core)
    r = rows[0]
    # independent check: px/cm of every quad from the written UVs and the known 3D sizes
    errs = []
    for name, sizes, sc in (('EX_A', rects, (2.0, 1.0)), ('EX_B', [(0, 0, 0.3, 0.3)], (1.0, 1.0))):
        me = bpy.data.objects[name].data
        uv = np.zeros(len(me.loops) * 2)
        me.uv_layers.active.data.foreach_get('uv', uv)
        uv = uv.reshape(-1, 4, 2) * 4096
        for q, (_x, _y, w, h) in zip(uv, sizes):
            a_px = tri_area(q[[0, 1, 2]][None])[0] + tri_area(q[[0, 2, 3]][None])[0]
            a_cm = (w * sc[0] * 100) * (h * sc[1] * 100)
            errs.append(abs(math.sqrt(a_px / a_cm) - 20.48) / 20.48)
    _check(results, '1 exact density (non-uniform scale)', max(errs) < 0.01 and _row_ok(r),
           f'max px/cm error {max(errs):.2e}, t={r["t"]}, mode={r["mode"]}, restore_ok={rep["restore_ok"]}')

    # 2. fits at t = 1: underflow, smallest size
    _reset_scene()
    scene_setup(0.9, 1.1)
    m = _mat('UNDER')
    rects = [(i * 0.6, 0, 0.3 + 0.02 * i, 0.2) for i in range(10)]
    _quad_obj('UN', rects, mats=[m] * 10)
    rows, rep = pack_scene(uv_marks, visibility_core)
    r = rows[0]
    ext = max(r['extent_px'])
    need = r['needed_size'][0]
    _check(results, '2 underflow at t=1, smallest size', r['mode'] == 'underflow' and r['t'] == 1.0 and need >= ext
           and need / 2 < ext and _row_ok(r) and r['packs'] == 1,
           f'k={r["k"]:.4f}, extent {ext:.1f} px, needed {r["needed_size"]}, fill {r["fill_texture_pct"]:.2f} %')

    # 3. needs 0 < t < 1
    _reset_scene()
    scene_setup(0.8, 1.25)
    m = _mat('MID', 1024, 1024)
    rng = np.random.default_rng(5)
    # 1024 px at 20.48 px/cm is 50 cm: total island area ~ 0.65 x 2500 cm^2 at x1.0
    rects = [(i * 0.5, 0, float(s), float(s)) for i, s in enumerate(rng.uniform(0.05, 0.12, 24))]
    area = sum(w * h for (_x, _y, w, h) in rects) * 1e4 * 20.48 ** 2 / 1024 ** 2
    _quad_obj('MI', rects, mats=[m] * len(rects))
    rows, rep = pack_scene(uv_marks, visibility_core)
    r = rows[0]
    _check(results, '3 fit with 0 < t < 1', r['mode'] == 'fit' and 0 < r['t'] < 1 and r['k'] <= 1 and _row_ok(r)
           and r['density_vs_t_max_all'] < 1e-4,
           f'area at x1.0 {area:.2f} of the square, t={r["t"]:.3f}, k={r["k"]:.4f}, packs={r["packs"]}, '
           f'fill {r["fill_texture_pct"]:.1f} %')

    # 4. overflow: k and needed size, all islands at lo
    _reset_scene()
    scene_setup(0.9, 1.1)
    m = _mat('OVER', 1024, 1024)
    rects = [(i * 0.8, 0, float(s), float(s * 0.7)) for i, s in enumerate(rng.uniform(0.15, 0.4, 20))]
    _quad_obj('OV', rects, mats=[m] * len(rects))
    rows, rep = pack_scene(uv_marks, visibility_core)
    r = rows[0]
    k_check = max(r['extent_px']) / 1024
    _check(results, '4 overflow k and needed size, all at lo', r['mode'] == 'overflow' and r['t'] == 0 and r['k'] > 1
           and abs(k_check - r['k']) < 1e-6 and r['needed_size'][0] == next_pow2(r['k'] * 1024) and _row_ok(r)
           and r['density_vs_t_max_all'] < 1e-4,
           f'k={r["k"]:.3f}, needed {r["needed_size"]}, gap {r["min_gap_px"]:.3f} px, overlaps {r["overlap_tri_pairs"]}')

    # 5. UPRIGHT island keeps its rotation (others in the set rotate freely)
    _reset_scene()
    scene_setup()
    m = _mat('DIR')
    up = _quad_obj('UP', [(0, 0, 0.6, 0.1), (1, 0, 0.1, 0.5)], mats=[m, m])
    up['fss_uv_direction'] = 'UPRIGHT'
    fl = _quad_obj('FLIPPED', [(0, 1, 0.5, 0.05)], mats=[m])
    fl['fss_uv_direction'] = 'FLIP'
    _quad_obj('FREE', [(i * 0.5, 2, 0.3, 0.07) for i in range(12)], mats=[m] * 12)
    rows, rep = pack_scene(uv_marks, visibility_core)
    r = rows[0]
    me = up.data
    uv = np.zeros(len(me.loops) * 2)
    me.uv_layers.active.data.foreach_get('uv', uv)
    e = uv.reshape(-1, 4, 2)[:, 1] - uv.reshape(-1, 4, 2)[:, 0]
    ang = float(np.abs(np.arctan2(e[:, 1], e[:, 0])).max())
    _check(results, '5 UPRIGHT keeps rotation', ang < 1e-4 and r['upright_rotation_err_rad'] < 1e-4 and _row_ok(r),
           f'max edge angle {ang:.2e} rad (UPRIGHT and FLIP islands), pins restored: {rep["restore_ok"]}')

    # 6. non-square texture keeps square pixels
    _reset_scene()
    scene_setup()
    m = _mat('WIDE', 4096, 2048)
    rects = [(i * 0.5, 0, 0.2, 0.2) for i in range(8)] + [(0, 1, 1.2, 0.3)]
    _quad_obj('NS', rects, mats=[m] * len(rects))
    rows, rep = pack_scene(uv_marks, visibility_core)
    r = rows[0]
    me = bpy.data.objects['NS'].data
    uv = np.zeros(len(me.loops) * 2)
    me.uv_layers.active.data.foreach_get('uv', uv)
    q = uv.reshape(-1, 4, 2) * np.array([4096, 2048])
    l1 = np.linalg.norm(q[:8, 1] - q[:8, 0], axis=1)
    l2 = np.linalg.norm(q[:8, 3] - q[:8, 0], axis=1)
    sq = float(np.abs(l1 / l2 - 1).max())
    inside = bool((uv >= 0).all() and (uv <= 1).all())
    _check(results, '6 non-square 4096x2048 square pixels', sq < 1e-4 and _row_ok(r) and inside,
           f'side ratio error {sq:.2e}, mode {r["mode"]}, k={r["k"]:.3f}, extent {r["extent_px"]}, '
           f'needed {r["needed_size"]}')

    # 7. linked duplicates packed once
    _reset_scene()
    scene_setup()
    m = _mat('LINK')
    a = _quad_obj('LA', [(0, 0, 0.3, 0.2), (1, 0, 0.2, 0.2)], mats=[m, m])
    b = _quad_obj('LB', None, mesh=a.data)
    b.location = (5, 0, 0)
    c = _quad_obj('LC', None, mesh=a.data)
    c.location = (9, 0, 0)
    rows, rep = pack_scene(uv_marks, visibility_core)
    r = rows[0]
    _check(results, '7 linked duplicates packed once', r['islands'] == 2 and rep['linked_meshes'] == 1 and _row_ok(r),
           f'islands {r["islands"]} (mesh has 2, 3 users)')

    # 8. an island spanning two materials is split
    _reset_scene()
    scene_setup()
    ma, mb = _mat('SPLIT_A'), _mat('SPLIT_B', 2048, 2048)
    me = bpy.data.meshes.new('SP')
    me.from_pydata([(0, 0, 0), (0.3, 0, 0), (0.6, 0, 0), (0.6, 0.3, 0), (0.3, 0.3, 0), (0, 0.3, 0)], [],
                   [(0, 1, 4, 5), (1, 2, 3, 4)])
    uvl = me.uv_layers.new(name='UVMap')
    lv = np.zeros(8, np.int64)
    me.loops.foreach_get('vertex_index', lv)
    co = np.array([(0, 0), (0.3, 0), (0.6, 0), (0.6, 0.3), (0.3, 0.3), (0, 0.3)]) * 0.5
    uvl.data.foreach_set('uv', co[lv].ravel())
    me.materials.append(ma)
    me.materials.append(mb)
    me.polygons.foreach_set('material_index', [0, 1])
    _quad_obj('SP', None, mesh=me)
    rows, rep = pack_scene(uv_marks, visibility_core)
    by = {x['set']: x for x in rows}
    uv = np.zeros(16)
    me.uv_layers.active.data.foreach_get('uv', uv)
    uv = uv.reshape(-1, 2)
    # density of each half in its own texture
    d = []
    for f, (w, h) in ((0, (4096, 4096)), (1, (2048, 2048))):
        q = uv[f * 4:(f + 1) * 4] * np.array([w, h])
        a_px = tri_area(q[[0, 1, 2]][None])[0] + tri_area(q[[0, 2, 3]][None])[0]
        d.append(math.sqrt(a_px / 900.0))
    _check(results, '8 island over two materials split',
           len(by) == 2 and by['SPLIT_A']['islands'] == 1 and by['SPLIT_B']['islands'] == 1
           and max(abs(x - 20.48) for x in d) / 20.48 < 1e-4 and all(_row_ok(x) for x in rows),
           f'sets {sorted(by)}, densities {[round(x, 4) for x in d]} px/cm')

    # 9. a zero-area (line) island is left out with its UVs unchanged; the rest packs normally
    _reset_scene()
    scene_setup()
    m = _mat('ZERO')
    zo = _quad_obj('ZO', [(0, 0, 0.3, 0.3), (1, 0, 0.2, 0.2)], mats=[m, m],
                   uv_rects=[(0.1, 0.1, 0.2, 0.2), (0.5, 0.5, 0.3, 0.0)])
    me = zo.data
    before = np.zeros(len(me.loops) * 2)
    me.uv_layers.active.data.foreach_get('uv', before)
    rows, rep = pack_scene(uv_marks, visibility_core)
    r = rows[0]
    after = np.zeros(len(me.loops) * 2)
    me.uv_layers.active.data.foreach_get('uv', after)
    line_same = bool(np.abs(after[8:] - before[8:]).max() < 1e-7)
    _check(results, '9 zero-area island left out', r['notes']['zero_area_islands_not_packed'] == 1 and line_same
           and _row_ok(r), f'not packed {r["notes"]["zero_area_islands_not_packed"]}, line UVs unchanged {line_same}')

    # 10. islands with a zero-area spike (a degenerate triangle sticking out in UV, as SPADE on the cockpit) among
    # small islands: the final layout keeps the margin (directly or through proxy quads)
    _reset_scene()
    scene_setup()
    m = _mat('SPIKE', 1024, 1024)
    verts, faces, uvs = [], [], []
    for i in range(6):
        b = len(verts)
        x = i * 1.0
        verts += [(x, 0, 0), (x + 0.2, 0, 0), (x + 0.2, 0.2, 0), (x, 0.2, 0), (x + 0.5, 0.1, 0)]
        faces += [(b, b + 1, b + 2, b + 3), (b + 1, b + 4, b + 2)]
        uvs += [(0.0, 0.0), (0.2, 0.0), (0.2, 0.2), (0.0, 0.2), (0.2, 1.0)]  # vertex b+4 on the line x = 0.2
    me = bpy.data.meshes.new('SPK')
    me.from_pydata(verts, [], faces)
    uvl = me.uv_layers.new(name='UVMap')
    lv = np.zeros(len(me.loops), np.int64)
    me.loops.foreach_get('vertex_index', lv)
    uvl.data.foreach_set('uv', (np.array(uvs) * 0.1)[lv].ravel())
    me.materials.append(m)
    _quad_obj('SPK', None, mesh=me)
    _quad_obj('SPK_SMALL', [(i * 0.3, 3, 0.04 + 0.01 * (i % 4), 0.05) for i in range(40)], mats=[m] * 40)
    rows, rep = pack_scene(uv_marks, visibility_core)
    r = rows[0]
    _check(results, '10 zero-area spike islands', _row_ok(r),
           f'gap {r["min_gap_px"]}, overlaps {r["overlap_tri_pairs"]}, attempts '
           f'{[(a["shape_method"], a["proxy_islands"], a["margin_violations"], a["overlap_tri_pairs"]) for a in r["attempts"]]}')
    return results, probes


# ------------------------------------------------------------------------------------------------------------------
# Cockpit
# ------------------------------------------------------------------------------------------------------------------

def run_cockpit(uv_marks, visibility_core):
    assert Path(bpy.data.filepath).resolve() == COCKPIT_COPY.resolve(), bpy.data.filepath
    scene = bpy.context.scene
    log('SETTINGS', scene.fss_uv_target_density, uv_marks.scene_freedom(scene), scene.unit_settings.scale_length)
    vis_path = COCKPIT_COPY.with_suffix('.visibility')
    meta, _data, stale = visibility_core.load_visibility_file(vis_path, scene_meshes=bpy.data.meshes)
    log('VISIBILITY', json.dumps({'meshes_in_file': len(meta.get('mesh_face_counts', {})), 'stale': len(stale)}))
    # largest sets by 3D area are chosen after a first pass; the two largest by face count are known from the survey
    t0 = time.perf_counter()
    rows, rep = pack_scene(uv_marks, visibility_core, export_sets=('Cockpit_STD', 'COLLIDER', 'FUR1', 'Rear_doors'),
                           dir_study=('Cockpit_STD', 'FUR1'))
    rep['wall_s'] = time.perf_counter() - t0
    rep['visibility'] = {'meshes_in_file': len(meta.get('mesh_face_counts', {})), 'stale_meshes': len(stale)}
    OUT.mkdir(parents=True, exist_ok=True)
    rows.sort(key=lambda x: -x['area_3d_cm2'])
    (OUT / 'cockpit_results.json').write_text(json.dumps({'rows': rows, 'report': rep}, indent=1, default=str))
    bpy.ops.wm.save_as_mainfile(filepath=str(WORK / 'COCKPIT_packed.blend'), copy=True)
    log('REPORT', json.dumps(rep, default=str))
    return rows, rep


def nonsquare_cockpit(uv_marks, visibility_core, name):
    """The same cockpit set packed into 4096 x 2048."""
    mat = bpy.data.materials[name]
    mat.fss_uv_texture_height = '2048'
    rows, rep = pack_scene(uv_marks, visibility_core, set_filter={name}, write=False)
    mat.fss_uv_texture_height = '4096'
    return rows[0]


def blender_main(argv):
    uv_marks, visibility_core = import_addon()
    if '--synthetic' in argv:
        results, probes = run_synthetic(uv_marks, visibility_core)
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / 'synthetic_results.json').write_text(json.dumps({'cases': results, 'probes': probes}, indent=1))
        n_ok = sum(1 for r in results if r[1])
        log('SYNTHETIC', f'{n_ok}/{len(results)} passed')
    if '--cockpit' in argv:
        rows, rep = run_cockpit(uv_marks, visibility_core)
        biggest = rows[0]['set']
        # non-square test on a real set: reload the unpacked copy so the set starts from the artist's UVs
        bpy.ops.wm.open_mainfile(filepath=str(COCKPIT_COPY))
        uv_marks, visibility_core = import_addon()
        ns = []
        for name in ('Cockpit_STD', 'FUR1'):  # the largest by 3D area and the largest by island count
            ns.append(nonsquare_cockpit(uv_marks, visibility_core, name))
        (OUT / 'cockpit_nonsquare.json').write_text(json.dumps(ns, indent=1, default=str))
        for r in ns:
            log('NONSQUARE', json.dumps({k_: r[k_] for k_ in ('set', 'size', 'mode', 't', 'k', 'needed_size',
                                                             'fill_texture_pct', 'min_gap_px', 'margin_violations',
                                                             'overlap_tri_pairs', 'density_out_of_range_max',
                                                             'time_s')}))
        log('BIGGEST', biggest)


# ------------------------------------------------------------------------------------------------------------------
# Venv: layout images and the grid packer comparison
# ------------------------------------------------------------------------------------------------------------------

def render_png(npz_path, png_path, title):
    from PIL import Image, ImageDraw
    d = np.load(npz_path)
    tri, isl = d['tri_px'], d['tri_isl']
    W, H, k = int(d['W']), int(d['H']), float(d['k'])
    side = max(1.0, k)
    N = 2048
    s = N / (side * max(W, H))
    img = Image.new('RGB', (N, N), (255, 255, 255))
    dr = ImageDraw.Draw(img)
    rng = np.random.default_rng(1)
    cols = (rng.uniform(60, 230, (int(isl.max()) + 1, 3))).astype(int)
    for t_, i in zip(tri, isl):
        dr.polygon([(float(x * s), float(N - 1 - y * s)) for x, y in t_], fill=tuple(cols[i]))
    dr.rectangle([0, N - 1 - H * s, W * s, N - 1], outline=(255, 0, 0), width=2)
    dr.text((8, 8), title, fill=(0, 0, 0))
    img.save(png_path)


def grid_compare(npz_path):
    sys.path.insert(0, str(HERE))
    import pack_grid
    d = np.load(npz_path)
    tri, isl, unit, a3 = d['tri_px'].astype(np.float64), d['tri_isl'], d['unit'], d['a3']
    W, H, M, k = int(d['W']), int(d['H']), int(d['margin']), float(d['k'])
    assert W == H
    islands = []
    order, st = _grouped(isl, len(unit))
    for i in range(len(unit)):
        T = tri[order[st[i]:st[i + 1]]] / W
        c = T.reshape(-1, 2).mean(0)
        a2 = float(tri_area(T).sum())
        islands.append({'id': i, 'obj': 'x', 'uv': T - c, 'orig_uv': T - c, 'a3': float(a3[i]), 'a2': a2,
                        'target_d': a2 / max(float(a3[i]), 1e-30), 'density_factor': 1.0,
                        'stack_id': int(unit[i]) if (unit == unit[i]).sum() > 1 else None})
    out = {}
    for R, label in ((W, 'tiles_at_texture_size'), (int(math.ceil(max(1.0, k) * W / 4.0) * 4), 'one_square_k')):
        if label == 'one_square_k' and k <= 1.0:
            continue
        t0 = time.perf_counter()
        uvs, tiles, stats = pack_grid.pack_grid(islands, resolution=R, margin_px=M, overflow_mode='tiles',
                                                directional_objs=set(), max_tiles=16 if label.startswith('tiles') else 1)
        dt = time.perf_counter() - t0
        if uvs is None:
            out[label] = {'resolution': R, 'fits': False, 'time_s': dt}
            continue
        # metrics in pixels of R with tiles laid side by side
        P = [u * R for u in uvs]
        tri2 = np.concatenate(P)
        tri_isl2 = np.concatenate([np.full(len(u), i) for i, u in enumerate(P)])
        seg_list, seg_isl = [], []
        # boundary = edges used once inside the island
        for i, Ti in enumerate(P):
            E = np.concatenate([Ti[:, [0, 1]], Ti[:, [1, 2]], Ti[:, [2, 0]]])
            q = np.round(np.sort(np.round(E * 1024).astype(np.int64).reshape(-1, 4).reshape(-1, 2, 2), axis=1)
                         .reshape(-1, 4))
            _, inv, cnt = np.unique(q, axis=0, return_inverse=True, return_counts=True)
            b = cnt[inv.ravel()] == 1
            seg_list.append(E[b])
            seg_isl.append(np.full(int(b.sum()), i))
        met = layout_metrics(tri2, tri_isl2, np.concatenate(seg_list), np.concatenate(seg_isl), unit, M)
        area = float(tri_area(tri2).sum())
        out[label] = dict(met, resolution=R, tiles=stats['tiles_count'], scale_loss=stats['scale_loss'],
                          fill_pct=100 * area / (stats['tiles_count'] * R * R),
                          used_px=stats['tile_bounds'], time_s=dt)
        render_png_tris(tri2, tri_isl2, R, stats['tiles_count'], npz_path.with_name(npz_path.stem + f'_grid_{label}.png'))
    return out


def render_png_tris(tri, isl, R, tiles, png_path):
    from PIL import Image, ImageDraw
    N = 2048
    s = N / (R * max(1, tiles))
    img = Image.new('RGB', (N, int(N / max(1, tiles)) + 1), (255, 255, 255))
    dr = ImageDraw.Draw(img)
    rng = np.random.default_rng(1)
    cols = (rng.uniform(60, 230, (int(isl.max()) + 1, 3))).astype(int)
    hgt = img.size[1]
    for t_, i in zip(tri, isl):
        dr.polygon([(float(x * s), float(hgt - 1 - y * s)) for x, y in t_], fill=tuple(cols[i]))
    for t in range(tiles):
        dr.rectangle([t * R * s, 0, (t + 1) * R * s, hgt - 1], outline=(255, 0, 0), width=2)
    img.save(png_path)


def venv_main(argv):
    """Images of every exported set; the grid packer comparison for the sets named after --grid."""
    grid_sets = argv[argv.index('--grid') + 1].split(',') if '--grid' in argv else []
    res = {}
    for npz in sorted(OUT.glob('set_*.npz')):
        row = json.loads(str(np.load(npz)['row']))
        if row['set'] not in grid_sets:
            render_png(npz, npz.with_suffix('.png'), f'{row["set"]}: t={row["t"]:.3f} k={row["k"]:.3f}')
            continue
        render_png(npz, npz.with_suffix('.png'), f'{row["set"]}: t={row["t"]:.3f} k={row["k"]:.3f}')
        res[row['set']] = {'ours': {k_: row[k_] for k_ in ('mode', 't', 'k', 'fill_texture_pct', 'fill_k_pct',
                                                            'min_gap_px', 'margin_violations', 'pack_s', 'time_s')}}
        res[row['set']]['grid'] = grid_compare(npz)
        print('GRID', json.dumps({row['set']: res[row['set']]}, default=str), flush=True)
    (OUT / 'grid_compare.json').write_text(json.dumps(res, indent=1, default=str))


if __name__ == '__main__':
    if bpy is None:
        venv_main(sys.argv[1:])
    else:
        argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
        blender_main(argv)
