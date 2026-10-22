"""UV packing per texture set: Blender's Pack Islands wrapped in our own steps (journal 20261019.automated-uv-unwrap.md,
decisions 112 to 117; the method was measured with tests/uv_prototype/pack_density_proto.py, Sessions 97 and 98).

A texture set is every face of one material over all mesh objects of the view layer, selected or not (decisions 100
and 114), with the mesh's active UV map; a mesh shared by several objects is packed once, with the material slots of
its first user. Every island is scaled to the density lo + t (hi - lo) in px/cm, where [lo, hi] = target density x
the object's final factor range (uv_marks.density) x the island's visibility (decisions 82 and 111), and one t holds
for the whole set (decision 113): 1 when the set fits at the top of its ranges, else the largest t that fits, else 0,
and the layout then spills into [0, k] x [0, k] (decision 112).

Packing runs on a temporary mesh per set with Pack Islands at scale=False, so the source objects' selection, modes,
pins and active UV maps are never touched. pack() writes only the UVs of the set's faces back; measure() writes
nothing. Islands without UV area (lines, points) are left out and keep their UVs. No UI here: the operators and the
panel rows are in uv_marks, the Find Faces Without Area check in checks.
"""

import math
import time

import bpy
import numpy as np

from . import uv_marks, visibility_core  # uv_marks imports this module too (its operators call pack and measure)

REPORT_TEXT_NAME = 'FSS Packing Report'
MIN_SIZE, MAX_SIZE = 256, 8192  # texture sizes per side (decisions 9 and 110)
GAP_TOL = 1e-3  # px: a gap below margin - GAP_TOL is a violation
MARGIN_EXTRA = 0.1  # px added to the requested gap (Blender's ADD margin came out 0.016 px short of 2 x margin at 64 px)
ANCHOR_PX = 0.5  # size of the two anchor triangles that set the ORIGINAL_AABB region, in px
ZERO_AREA_PX2 = 1e-6  # UV area in px^2 at or below which an island is a line or a point
FLAT_RATIO = 1e-5  # UV area / UV bbox diagonal^2 at or below which an island is a line (Blender rescales those)
COLLAPSE_Q = 20.0  # UV bbox diagonal / (3D bbox diagonal x density) at the area-based scale: above it, collapsed
PROXY_ROUNDS = 3  # rounds of packing offending islands through their bounding box before the AABB fallback
SEARCH_PACKS = 6  # packs of the search for t after the two at t = 1 and t = 0
FACE_AREA_MIN_CM2 = 1e-6  # world-space face area in cm^2 at or below which a face has no area (decision 117)


def next_pow2(x):
    return 1 << max(0, int(math.ceil(math.log2(max(x, 1e-9)))))


def needed_size(k, width, height):
    """((width, height) or None, fits): the power-of-two size per side that holds a layout of k times the texture,
    clamped to 256 at the bottom; None and False when a side would need more than 8192."""
    w, h = k * width, k * height
    if max(w, h) > MAX_SIZE * (1 + 1e-9):
        return None, False
    return (max(next_pow2(w), MIN_SIZE), max(next_pow2(h), MIN_SIZE)), True


# ------------------------------------------------------------------------------------------------------------------
# Geometry helpers (numpy)
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


def layout_metrics(tri_px, tri_isl, seg_px, seg_isl, n, margin_px):
    """Smallest gap between islands (exact segment distance over island boundaries, measured up to 2 x margin: None
    means every gap is larger), the island pairs closer than the margin, and the overlapping triangle pairs between
    different islands, all in pixels. Returns the metrics and the islands named in a violation or an overlap."""
    reach = 2.0 * margin_px
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
    min_gap = math.inf
    offenders = set()
    violations = 0
    for i, j in zip(a.tolist(), b.tolist()):
        si = s_ord[s_st[i]:s_st[i + 1]]
        sj = s_ord[s_st[j]:s_st[j + 1]]
        si = si[((s_hi[si] >= ilo[j] - reach) & (s_lo[si] <= ihi[j] + reach)).all(1)]
        sj = sj[((s_hi[sj] >= ilo[i] - reach) & (s_lo[sj] <= ihi[i] + reach)).all(1)]
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
            m = (dx * dx + dy * dy) < reach * reach
            if not m.any():
                continue
            A, B = A[m], B[m]
            d = seg_seg_dist(seg_px[A, 0], seg_px[A, 1], seg_px[B, 0], seg_px[B, 1])
            best = min(best, float(d.min()))
        min_gap = min(min_gap, best)
        if best < margin_px - GAP_TOL:
            violations += 1
            offenders |= {i, j}
    # overlaps
    a, b = box_pairs(ilo, ihi, pad=0.0)
    overlaps = 0
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
                offenders |= {i, j}
    return {'min_gap_px': None if min_gap == math.inf else min_gap, 'margin_violations': violations,
            'overlap_tri_pairs': overlaps}, offenders


# ------------------------------------------------------------------------------------------------------------------
# Texture sets
# ------------------------------------------------------------------------------------------------------------------

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
        nxt[self.PS + self.PT - 1] = self.PS
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
        """Face areas in cm^2, from world-space vertices (non-uniform scale exact) and the mesh's triangulation."""
        M = np.array(matrix_world, dtype=np.float64)
        W = self.CO @ M[:3, :3].T + M[:3, 3]
        P = W[self.tri_verts]
        a = 0.5 * np.linalg.norm(np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]), axis=1)
        return np.bincount(self.TP, weights=a, minlength=self.nf) * cm2_per_bu2

    def face_uv_areas(self):
        return np.bincount(self.TP, weights=tri_area(self.UV[self.TL]), minlength=self.nf)


def _cm_per_unit(scene):
    return scene.unit_settings.scale_length * 100.0


def face_areas_cm2(obj, scene=None):
    """World-space areas of the object's faces in cm^2 (Object Mode data)."""
    scene = scene or bpy.context.scene
    me = obj.data
    me.calc_loop_triangles()
    nt = len(me.loop_triangles)
    tl = np.zeros(nt * 3, np.int64)
    me.loop_triangles.foreach_get('vertices', tl)
    tp = np.zeros(nt, np.int64)
    me.loop_triangles.foreach_get('polygon_index', tp)
    co = np.zeros(len(me.vertices) * 3, np.float64)
    me.vertices.foreach_get('co', co)
    M = np.array(obj.matrix_world, dtype=np.float64)
    P = (co.reshape(-1, 3) @ M[:3, :3].T + M[:3, 3])[tl.reshape(-1, 3)]
    a = 0.5 * np.linalg.norm(np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]), axis=1)
    return np.bincount(tp, weights=a, minlength=len(me.polygons)) * _cm_per_unit(scene) ** 2


def _local(obj):
    return not (obj.library or obj.override_library or obj.data.library or obj.data.override_library)


def _meshes(view_layer):
    """{mesh: [users sorted by name]} over the view layer's local mesh objects with faces and an active UV map."""
    by_mesh = {}
    for obj in view_layer.objects:
        if obj.type != 'MESH' or obj.data is None or not _local(obj):
            continue
        me = obj.data
        if me.uv_layers.active is None or len(me.polygons) == 0:
            continue
        by_mesh.setdefault(me, []).append(obj)
    return {me: sorted(users, key=lambda o: o.name) for me, users in by_mesh.items()}


def _slot_match(obj, material):
    """Per material index (plus one past the last slot): True where the face's material is `material`."""
    return np.array([slot.material == material for slot in obj.material_slots] + [material is None], bool)


def _face_material_mask(obj, md, material):
    match = _slot_match(obj, material)
    return match[np.minimum(md.MI, len(match) - 1)]


def texture_sets(view_layer=None):
    """The materials (None for faces without one) that faces with a UV map use in the view layer, by name."""
    view_layer = view_layer or bpy.context.view_layer
    found = {}
    for me, users in _meshes(view_layer).items():
        mi = np.zeros(len(me.polygons), np.int64)
        me.polygons.foreach_get('material_index', mi)
        slots = [slot.material for slot in users[0].material_slots]
        for index in np.unique(mi).tolist():
            material = slots[index] if index < len(slots) else None
            found[material.name_full if material else ''] = material
    return [found[name] for name in sorted(found)]


def gather(view_layer, material):
    """[(MeshData, users, face indices)] of every face using `material` (by the mesh's first user) in the view layer,
    and the faces whose other users show another material there (object-linked slots; not resolved, counted)."""
    parts = []
    conflicts = 0
    for me, users in sorted(_meshes(view_layer).items(), key=lambda item: item[0].name):
        if not _slot_match(users[0], material).any():
            continue
        md = MeshData(me)
        mask = _face_material_mask(users[0], md, material)
        if not mask.any():
            continue
        for other in users[1:]:
            conflicts += int((_face_material_mask(other, md, material) != mask).sum())
        parts.append((md, users, np.flatnonzero(mask)))
    return parts, conflicts


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


class TextureSet:
    """One material's islands with their density ranges, packed on a temporary mesh."""

    def __init__(self, material, parts, scene, vis_cache):
        self.name = material.name if material is not None else '(no material)'
        self.material = material
        self.W, self.H = uv_marks.texture_size(material)
        self.margin_px = int(uv_marks.margin(material))
        self.S = float(max(self.W, self.H))
        self.ax, self.ay = self.W / self.S, self.H / self.S  # region in normalised square-pixel space
        target = uv_marks.target_density(scene)
        bu_cm = _cm_per_unit(scene)
        cm2 = bu_cm * bu_cm
        self.parts = parts
        self.me = self.obj = None
        rows = []  # per island: part index, A_uv (px^2), A3 (cm^2), lo, hi, direction, UV bbox diag, 3D bbox diag
        self.face_isl = []  # per part: global island id per part face
        self.bl = []  # per part: boundary loops
        self.bl_isl = []
        self.stale_meshes = []
        self.linked_range_differs = 0
        self.no_area_objects = []  # objects with faces of the set without 3D area (decision 117)
        n_isl = 0
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
            # visibility per island (decision 82 via score_face_set, floor of decision 111); 1.0 when missing or stale
            vis_data = vis_cache.get(md.me.name)
            if vis_data is None:
                vis_data = visibility_core.get_object_visibility(users[0]) if bpy.data.filepath else {'stale': True}
                vis_cache[md.me.name] = vis_data
            if vis_data.get('stale', True):
                self.stale_meshes.append(md.me.name)
                vis = np.ones(ni)
            else:
                order = np.argsort(isl, kind='stable')
                st = np.searchsorted(isl[order], np.arange(ni + 1))
                vis = np.array([uv_marks.visibility_factor(
                    visibility_core.score_face_set(users[0], faces[order[st[k]:st[k + 1]]], vis_data=vis_data))
                    for k in range(ni)])
            # per user: 3D area and range; the island follows the user that needs the most texture
            best = first = None
            for u in users:
                areas = md.face_areas_world(u.matrix_world, cm2)[faces]
                if first is None and (areas <= FACE_AREA_MIN_CM2).any():
                    self.no_area_objects += [o.name for o in users]
                a3 = np.bincount(isl, weights=areas, minlength=ni)
                (flo, fhi), _source = uv_marks.density(u, scene)
                lo, hi = target * flo * vis, target * fhi * vis
                need = lo / np.maximum(np.sqrt(uv_a / np.maximum(a3, 1e-30)), 1e-30)
                row = (need, a3, lo, hi)
                if best is None:
                    best = first = row
                else:
                    take = need > best[0]
                    best = tuple(np.where(take, r1, r0) for r0, r1 in zip(best, row))
                    self.linked_range_differs += int((np.abs(need - first[0]) > 1e-6 * first[0]).sum())
            _need, a3, lo, hi = best
            direction = uv_marks.direction(users[0])[0]
            for k in range(ni):
                rows.append((pi, uv_a[k], a3[k], lo[k], hi[k], direction, p_uv[k], p_3d[k]))
            self.face_isl.append(isl + n_isl)
            self.bl.append(bl)
            self.bl_isl.append(bl_isl + n_isl)
            n_isl += ni
        self.n = n_isl
        self.part_of = np.array([r[0] for r in rows], np.int64)
        self.a_uv = np.array([r[1] for r in rows])
        self.a3 = np.array([r[2] for r in rows])
        self.lo = np.array([r[3] for r in rows])
        self.hi = np.array([r[4] for r in rows])
        self.dirs = np.array([r[5] for r in rows])
        self.cur = np.sqrt(self.a_uv / np.maximum(self.a3, 1e-30))  # as the UVs sit on the W x H texture
        # the unwrap is conformal in UV space (u and v of equal length): packing works on that shape in square-pixel
        # space (X = u W / S, Y = v H / S after the pack), so the current density there uses S x S
        self.cur_sq = self.cur * self.S / math.sqrt(self.W * self.H)
        self.p_uv = np.array([r[6] for r in rows])
        self.p_3d = np.array([r[7] for r in rows])
        # degenerate: no 3D area (scale 1, kept out of the density check)
        self.degenerate = (self.a3 <= 1e-12) | ((self.a_uv <= 1e-12) & (self.p_uv <= 1e-9))
        # collapsed UVs (a line, a sliver or a point in UV, normal in 3D): scaling by area would blow them up
        # (factors up to 21,294 on the cockpit, one sliver 129,000 px long). Test: the UV bounding-box diagonal at
        # the area-based scale against the 3D bounding-box diagonal x density (an unrolled cylinder gives ~2.2).
        # Above COLLAPSE_Q the island is scaled so that the two diagonals match and is kept out of the density check.
        self.cur_sq_len = self.p_uv / np.maximum(self.p_3d, 1e-30)
        diag_q = self.cur_sq_len / np.maximum(self.cur_sq, 1e-30)
        self.collapsed = ~self.degenerate & (diag_q > COLLAPSE_Q)
        # zero UV area (a line or a point): Blender's packer ignores or rescales such islands and drops them anywhere
        # (measured: gap 0 to packed islands, a 1 px line made 8.6 px long), and no scale gives them a density. They
        # are left out: UVs unchanged, no metrics.
        flat = self.a_uv * self.S * self.S / (self.W * self.H) <= FLAT_RATIO * self.p_uv ** 2
        self.zero_area = (self.a_uv <= ZERO_AREA_PX2) | flat
        self.upright = np.isin(self.dirs, ['UPRIGHT', 'FLIP'])  # FLIP: pinned as UPRIGHT (no 180-degree rule)
        self.quarter = bool((self.dirs == 'QUARTER').any())
        self.proxy = np.zeros(self.n, bool)  # islands packed through their proxy quad
        self.no_area_objects = sorted(set(self.no_area_objects))

    def objects(self):
        return sorted({o.name for _md, users, _faces in self.parts for o in users})

    def objects_of(self, mask):
        return sorted({o.name for p in np.unique(self.part_of[mask]).tolist() for o in self.parts[p][1]})

    # ---- temporary mesh ------------------------------------------------------------------------------------------
    def build_temp(self):
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
        me = bpy.data.meshes.new('FSS_PACK_TMP')
        self.me = me
        me.vertices.add(len(V))
        me.vertices.foreach_set('co', V.astype(np.float32).ravel())
        me.loops.add(nl + 4 * n + 6)
        me.loops.foreach_set('vertex_index', LVt.astype(np.int32))
        me.polygons.add(nf + n + 2)
        me.polygons.foreach_set('loop_start', FS.astype(np.int32))
        me.update(calc_edges=True)
        me.uv_layers.new(name='UVMap')
        ev = np.zeros(len(me.edges) * 2, np.int64)
        me.edges.foreach_get('vertices', ev)
        self.edge_verts = ev.reshape(-1, 2)
        self.loop_vert_t = LVt  # vertex of each temp loop
        self.loop_count_t = np.diff(np.concatenate([FS, [nl + 4 * n + 6]]))  # loops per temp face
        self.obj = bpy.data.objects.new('FSS_PACK_TMP', me)
        bpy.context.scene.collection.objects.link(self.obj)
        # triangles: the source meshes' own triangulation (a concave or folded UV n-gon has a different area under
        # another triangulation), mapped to temp loops
        tl_all, ti_all, bl_t, bl_i = [], [], [], []
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
            # boundary loops (segment from the loop to the next one) in temp order
            pos = np.searchsorted(lsel, self.bl[pi])
            nxt_pos = np.searchsorted(lsel, md.next[self.bl[pi]])
            bl_t.append(np.stack([pos + off, nxt_pos + off], 1))
            bl_i.append(self.bl_isl[pi])
            off += len(lsel)
        self.TLt = np.concatenate(tl_all)
        self.tri_isl = np.concatenate(ti_all)
        self.seg_loops = np.concatenate(bl_t) if bl_t else np.zeros((0, 2), np.int64)
        self.seg_isl = np.concatenate(bl_i) if bl_i else np.zeros(0, np.int64)

    def remove_temp(self):
        if self.obj is not None:
            bpy.data.objects.remove(self.obj)
        if self.me is not None:
            bpy.data.meshes.remove(self.me)
        self.obj = self.me = None
        bpy.context.view_layer.update()  # else the view layer still lists the removed object (as None)

    def px(self, uv):
        """UV -> pixels of the set's texture."""
        return uv * np.array([self.W, self.H])

    def to_uv(self, Q):
        return Q / np.array([self.ax, self.ay])

    def densities(self, t):
        return self.lo + t * (self.hi - self.lo)

    def island_scale(self, t):
        """Linear UV scale per island for density t, 1.0 for degenerate islands."""
        d = self.densities(t)
        f = np.where(self.collapsed, d / np.maximum(self.cur_sq_len, 1e-30), d / np.maximum(self.cur_sq, 1e-30))
        return np.where(self.degenerate, 1.0, f)

    # ---- one pack --------------------------------------------------------------------------------------------------
    def _prepared_uv(self, t):
        """Normalised square-pixel coordinates (u W / S, v H / S) of every loop, each island scaled about its own
        centre to density t and spread on shelves so that no two islands overlap (merge_overlap must not merge
        islands that only touch after scaling). Returns (coords, region corner)."""
        P = self.uv0.copy()  # conformal island shapes; to_uv() divides by (ax, ay) after the pack
        li = self.loop_isl
        lo = np.full((self.n, 2), np.inf)
        hi = np.full((self.n, 2), -np.inf)
        np.minimum.at(lo, li, P)
        np.maximum.at(hi, li, P)
        c = 0.5 * (lo + hi)
        f = self.island_scale(t)
        P = c[li] + (P - c[li]) * f[li][:, None]
        lo = c + (lo - c) * f[:, None]
        hi = c + (hi - c) * f[:, None]
        size = hi - lo
        g = 4.0 * (self.margin_px + 2) / self.S
        order = np.argsort(-size[:, 1], kind='stable')
        aspect = self.ax / self.ay
        row_w = math.sqrt(float(((size[:, 0] + g) * (size[:, 1] + g)).sum()) * aspect)
        row_w = max(row_w, float(size[:, 0].max()) + g)
        off = np.zeros((self.n, 2))
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
        P = P - lo[li] + off[li]
        sw = float(P[:, 0].max()) + g
        sh = float(P[:, 1].max()) + g
        ry = max(sh, sw / aspect)
        return P, (ry * aspect, ry)

    def pack(self, t, shape_method='CONCAVE'):
        """Pack at density t; returns (final coords in normalised space, k, extent px (x, y), prepared coords)."""
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
        me = self.me
        me.uv_layers['UVMap'].data.foreach_set(
            'uv', np.concatenate([P, quads.reshape(-1, 2), anchors]).astype(np.float32).ravel())
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
        use_pin = bool(self.upright.any())
        if use_pin:
            pins[:self.n_loops] = self.upright[self.loop_isl]
            pins[self.n_loops:self.n_loops + 4 * n] = np.repeat(self.upright, 4)
        if len(me.uv_layers['UVMap'].pin) == 0:  # the pin layer exists only once something is pinned
            me.attributes.new(name='.pn.UVMap', type='BOOLEAN', domain='CORNER')
        me.uv_layers['UVMap'].pin.foreach_set('value', pins)
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
        try:
            # margin ADD with scale=False leaves the margin around each island: the gap is twice the margin
            bpy.ops.uv.pack_islands(udim_source='ORIGINAL_AABB', rotate=True,
                                    rotate_method='CARDINAL' if self.quarter else 'ANY', scale=False,
                                    merge_overlap=True, margin_method='ADD',
                                    margin=(self.margin_px + MARGIN_EXTRA) * 0.5 / self.S,
                                    pin=use_pin, pin_method='ROTATION', shape_method=shape_method)
        finally:
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
        Qp = Q[~zl]
        ext = Qp.max(0) * self.S
        if Qp.min() < -1e-7:
            ext = ext + np.maximum(0, -Qp.min(0) * self.S)
        k = max(ext[0] / self.W, ext[1] / self.H)
        return Q, k, ext, P


def search(ts, shape_method, progress=None):
    """Decision 113: t = 1 if it fits, else the largest t that fits (secant steps on k(t) - 1, kept inside the
    bracket), else t = 0 (overflow, k > 1). Returns (the chosen pack, packs, mode)."""
    packs = []

    def run(t):
        if progress is not None:
            progress(f'{shape_method.lower()} pack {len(packs) + 1}, t {t:.2f}')
        Q, k, ext, P = ts.pack(t, shape_method=shape_method)
        packs.append(t)
        return {'t': t, 'Q': Q, 'k': k, 'ext': ext, 'pre': P}

    r1 = run(1.0)
    if r1['k'] <= 1.0:
        return r1, len(packs), 'underflow'
    r0 = run(0.0)
    if r0['k'] > 1.0:
        return r0, len(packs), 'overflow'
    lo, hi = r0, r1
    for _ in range(SEARCH_PACKS):
        if hi['t'] - lo['t'] < 0.01:
            break
        # k is close to linear in the density scale: interpolate where k crosses 1 (aim a little below it)
        tt = lo['t'] + (hi['t'] - lo['t']) * (0.995 - lo['k']) / max(hi['k'] - lo['k'], 1e-9)
        span = hi['t'] - lo['t']
        r = run(min(max(tt, lo['t'] + 0.1 * span), hi['t'] - 0.1 * span))
        if r['k'] <= 1.0:
            lo = r
        else:
            hi = r
    return lo, len(packs), 'fit'


def pack_set(ts, progress=None):
    """Search (decision 113) with Blender's CONCAVE shapes, then measure the layout. Islands named in a margin
    violation or an overlap are packed through their proxy quad (bounding box; the island follows the quad's rigid
    move) in the next round, up to PROXY_ROUNDS more rounds; then the whole set falls back to AABB shapes, whose
    margin is exact. Measured on the cockpit: Blender's concave and convex margins cut corners (6.2 to 7.9 px for
    8.1 px requested), and zero-area triangles inside an island are left out of its hull (the island lands on
    others). Returns (chosen pack, mode, metrics)."""
    packs = 0
    shape = 'CONCAVE'
    rounds = 0
    while True:
        res, n, mode = search(ts, shape, progress)
        packs += n
        if progress is not None:
            progress('measuring the layout')
        row, offenders = evaluate(ts, res)
        if row['margin_violations'] == 0 and row['overlap_tri_pairs'] == 0 or shape == 'AABB':
            break
        if rounds < PROXY_ROUNDS:
            ts.proxy[sorted(offenders)] = True
            rounds += 1
        else:
            ts.proxy[:] = False
            shape = 'AABB'
    row.update(mode=mode, packs=packs, shape_method=shape, proxy_islands=int(ts.proxy.sum()))
    return res, mode, row


def evaluate(ts, res):
    """Metrics of a pack, from the coordinates written back (pixel space of the texture): gaps and overlaps, the
    density of every island against its range, size and fill. Returns (metrics, islands named in a violation or an
    overlap)."""
    px = ts.px(ts.to_uv(res['Q']))
    tri = px[ts.TLt]
    seg = px[ts.seg_loops]
    kt = ~ts.zero_area[ts.tri_isl]
    ks = ~ts.zero_area[ts.seg_isl]
    m, offenders = layout_metrics(tri[kt], ts.tri_isl[kt], seg[ks], ts.seg_isl[ks], ts.n, ts.margin_px)
    # density per island against its range (degenerate, collapsed and zero-area islands have none)
    a_uv = np.bincount(ts.tri_isl, weights=tri_area(tri), minlength=ts.n)
    d = np.sqrt(a_uv / np.maximum(ts.a3, 1e-30))
    ok = ~ts.degenerate & ~ts.collapsed & ~ts.zero_area
    dev = np.maximum(np.where(d < ts.lo, (ts.lo - d) / ts.lo, 0.0), np.where(d > ts.hi, (d - ts.hi) / ts.hi, 0.0))[ok]
    big = a_uv[ok] >= 100.0
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
    k = res['k']
    need, fits = needed_size(k, ts.W, ts.H)
    area_px = float(a_uv[~ts.zero_area].sum())
    m.update({
        't': res['t'], 'k': k, 'extent_px': [float(res['ext'][0]), float(res['ext'][1])],
        'needed_size': need, 'fits_8192': fits,
        # fill of the needed size; beyond 8192 of the layout's k square (never above 100 % unless islands overlap)
        'fill_pct': 100.0 * area_px / (need[0] * need[1] if need else k * k * ts.W * ts.H),
        'fill_current_pct': 100.0 * area_px / (ts.W * ts.H),
        'density_out_of_range_max': float(dev.max()) if len(dev) else 0.0,
        'density_out_of_range_max_ge100px': float(dev[big].max()) if big.any() else 0.0,
        'density_out_of_range_mean': float((dev * ts.a3[ok]).sum() / max(ts.a3[ok].sum(), 1e-30)) if len(dev) else 0.0,
        'upright_rotation_err_rad': up_err,
    })
    return m, offenders


def write_back(ts, res):
    """Write the chosen layout into the source meshes' active UV maps (only the set's loops)."""
    uv = ts.to_uv(res['Q'])
    off = 0
    for pi, (md, _users, _faces) in enumerate(ts.parts):
        lsel = ts.loop_src[pi]
        md.UV[lsel] = uv[off:off + len(lsel)]
        off += len(lsel)
        md.uv_layer.data.foreach_set('uv', md.UV.astype(np.float32).ravel())
        md.me.update()


# ------------------------------------------------------------------------------------------------------------------
# Pack and measure
# ------------------------------------------------------------------------------------------------------------------

def is_kept(material):
    """Keep UVs (decision 116): the texture set is left out of packing and Check All."""
    return bool(material is not None and getattr(material, 'fss_uv_keep_uvs', False))


def set_name(material):
    return material.name if material is not None else '(no material)'


def _save_state(context):
    view_layer = context.view_layer
    return {'active': view_layer.objects.active, 'selected': [o for o in view_layer.objects if o.select_get()],
            'mode': context.mode, 'sync': context.scene.tool_settings.use_uv_select_sync}


def _restore_state(context, state):
    view_layer = context.view_layer
    view_layer.update()
    for o in view_layer.objects:
        if o is not None and o.select_get():
            o.select_set(False)
    for o in state['selected']:
        o.select_set(True)
    view_layer.objects.active = state['active']
    context.scene.tool_settings.use_uv_select_sync = state['sync']
    if state['mode'] == 'EDIT_MESH' and state['active'] is not None:
        bpy.ops.object.mode_set(mode='EDIT')


def _run(material, write, progress=None, vis_cache=None):
    context = bpy.context
    t0 = time.perf_counter()
    W, H = uv_marks.texture_size(material)
    result = {'set': set_name(material), 'material': material.name if material is not None else None,
              'size': (W, H), 'margin_px': int(uv_marks.margin(material)), 'written': False}
    if is_kept(material):
        result.update(mode='kept', time_s=0.0)
        return result
    state = _save_state(context)
    # In Edit Mode the mesh's own data is not current (Blender keeps an editing copy), as uv_autoseam._in_object_mode
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    ts = None
    try:
        context.scene.tool_settings.use_uv_select_sync = True  # the temporary mesh's face selection is its UV selection
        if progress is not None:
            progress('reading the islands')
        parts, conflicts = gather(context.view_layer, material)
        ts = TextureSet(material, parts, context.scene, {} if vis_cache is None else vis_cache) if parts else None
        result.update({'islands': ts.n if ts else 0, 'objects': ts.objects() if ts else [],
                       'linked_material_conflict_faces': conflicts})
        if ts is None or ts.zero_area.all():
            result['mode'] = 'empty'
            result['zero_area_islands'] = int(ts.zero_area.sum()) if ts else 0
            return result
        ts.build_temp()
        res, mode, row = pack_set(ts, progress)
        result.update(row)
        result.update({
            'zero_area_islands': int(ts.zero_area.sum()), 'zero_area_objects': ts.objects_of(ts.zero_area),
            'collapsed_islands': int(ts.collapsed.sum()), 'degenerate_islands': int(ts.degenerate.sum()),
            'no_area_objects': ts.no_area_objects, 'stale_visibility_meshes': len(ts.stale_meshes),
            'linked_users_range_differs': ts.linked_range_differs, 'quarter': ts.quarter,
            'upright_islands': int(ts.upright.sum()),
        })
        if write:
            write_back(ts, res)
            result['written'] = True
    finally:
        if ts is not None:
            ts.remove_temp()
        _restore_state(context, state)
        result['time_s'] = time.perf_counter() - t0
    return result


def measure(material, progress=None, vis_cache=None):
    """Pack the texture set of `material` on a temporary mesh and return the result, without writing UVs (decision
    115). progress: optional function(stage text), called before each Blender pack; vis_cache: {mesh name:
    visibility data} kept over several sets."""
    return _run(material, False, progress, vis_cache)


def pack(material, progress=None, vis_cache=None):
    """Pack the texture set of `material` (every face using it in the view layer, decision 114) and write the UVs.
    Returns the result as measure() does, with 'written' True."""
    return _run(material, True, progress, vis_cache)


# ------------------------------------------------------------------------------------------------------------------
# Results as text
# ------------------------------------------------------------------------------------------------------------------

def result_text(result):
    """The short result of a texture set, as the Packing rows show it."""
    mode = result.get('mode')
    if mode == 'kept':
        return 'kept'
    if mode == 'empty':
        return 'nothing to pack'
    if not result['fits_8192']:
        return f"does not fit even at {MAX_SIZE} (x{result['k']:.2f})"
    w, h = result['needed_size']
    if mode == 'overflow':
        return f"needs x{result['k']:.2f}: {w} x {h}"
    fill = result['fill_current_pct']
    text = f"fits {fill:.0f} %" if fill >= 9.5 else f"fits {fill:.1f} %"
    return text + (f', {w} x {h} would do' if (w, h) != tuple(result['size']) else '')


def _mode_text(result):
    mode = result['mode']
    if mode in ('kept', 'empty'):
        return mode
    if mode == 'overflow':
        return 'overflow' if result['fits_8192'] else f'overflow, does not fit even at {MAX_SIZE}'
    return {'underflow': 'underflow (at the top of the ranges)', 'fit': 'fit'}[mode]


def _names(names, limit=8):
    return ', '.join(names[:limit]) + (f' ... {len(names) - limit} more' if len(names) > limit else '')


def _set_block(r, selected=None):
    lines = [f"## {r['set']}: {result_text(r)}"]
    if r['mode'] == 'kept':
        lines.append('  Keep UVs: left out, UVs unchanged')
        return lines
    W, H = r['size']
    if r['mode'] == 'empty':
        lines.append(f"  Size {W} x {H}; {r.get('islands', 0)} island(s), "
                     f"{r.get('zero_area_islands', 0)} without UV area (kept unchanged)")
        return lines
    need = r['needed_size']
    need_text = f'{need[0]} x {need[1]}' if need else f'more than {MAX_SIZE} on a side'
    gap = r['min_gap_px']
    lines += [
        f"  Mode {_mode_text(r)}; size {W} x {H}, margin {r['margin_px']} px",
        f"  t {r['t']:.3f}, k {r['k']:.3f} (layout {r['extent_px'][0]:.0f} x {r['extent_px'][1]:.0f} px), "
        f"needed {need_text}",
        f"  Fill {r['fill_pct']:.1f} % of {'the needed size' if need else 'the layout'} "
        f"({r['fill_current_pct']:.1f} % of {W} x {H})",
        f"  Smallest gap {'more than 2 x margin' if gap is None else f'{gap:.2f} px'}; "
        f"margin violations {r['margin_violations']}, overlapping triangle pairs {r['overlap_tri_pairs']}",
        f"  Density outside its range: max {100 * r['density_out_of_range_max']:.2f} % "
        f"({100 * r['density_out_of_range_max_ge100px']:.3f} % for islands of 100 px^2 or more)",
        f"  Islands {r['islands']}; shapes {r['shape_method']}"
        + (f", {r['proxy_islands']} packed by their bounding box" if r['proxy_islands'] else '')
        + (f", {r['upright_islands']} upright" if r['upright_islands'] else '')
        + (', quarter turns only' if r['quarter'] else ''),
    ]
    if r['zero_area_islands']:
        lines.append(f"  Kept unchanged: {r['zero_area_islands']} island(s) without UV area (lines or points) in "
                     f"{_names(r['zero_area_objects'])}")
    if r['collapsed_islands'] or r['degenerate_islands']:
        lines.append(f"  Not checked for density: {r['collapsed_islands']} collapsed island(s) (a sliver in UV), "
                     f"{r['degenerate_islands']} without 3D area")
    if r['no_area_objects']:
        lines.append(f"  WARNING faces without area in {len(r['no_area_objects'])} object(s): "
                     f"{_names(r['no_area_objects'])}. They can push islands far out; fix the geometry "
                     "(Utilities > Checks > Find Faces Without Area)")
    if r['stale_visibility_meshes']:
        lines.append(f"  Visibility x1.00 for {r['stale_visibility_meshes']} mesh(es) without current visibility data")
    if selected is not None:
        extra = [name for name in r['objects'] if name not in selected]
        if extra:
            lines.append(f"  Included, not selected: {len(extra)} object(s): {_names(extra)}")
    if r['linked_material_conflict_faces']:
        lines.append(f"  {r['linked_material_conflict_faces']} face(s) of shared meshes show another material on "
                     "another user (the first user's material counts)")
    packs = f"{r['packs']} pack{'' if r['packs'] == 1 else 's'}"
    lines.append(f"  Time {r['time_s']:.1f} s ({packs}){'' if r['written'] else ', nothing written'}")
    return lines


def write_report(results, kind, seconds, selected=None, cancelled=False):
    """Write the text 'FSS Packing Report': a summary, then one block per texture set (kind: 'Pack' or 'Check All';
    selected: the object names selected at Pack, to list the objects included that were not)."""
    txt = bpy.data.texts.get(REPORT_TEXT_NAME) or bpy.data.texts.new(REPORT_TEXT_NAME)
    txt.clear()
    scene = bpy.context.scene
    low, high = uv_marks.scene_freedom(scene)
    counts = {}
    for r in results:
        key = 'overflow beyond 8192' if r['mode'] == 'overflow' and not r['fits_8192'] else r['mode']
        counts[key] = counts.get(key, 0) + 1
    lines = [f"# FSS Packing Report - {time.strftime('%Y-%m-%d %H:%M:%S')}",
             f"# {kind}: {len(results)} texture set(s) in {seconds:.1f} s"
             + (', cancelled' if cancelled else '') + ('' if kind == 'Pack' else ', no UVs written'),
             f"# Target density {uv_marks.target_density(scene):.2f} px/cm, density freedom x{low:.2f} - x{high:.2f}",
             '# ' + ', '.join(f'{n} {mode}' for mode, n in sorted(counts.items())), '']
    for r in results:
        lines += _set_block(r, selected) + ['']
    txt.write('\n'.join(lines))
    return txt
