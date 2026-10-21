"""
Automatic seam proposal core for hard-surface meshes.

Port of Candidate C1 (Round 5 Package 10) from tests/uv_prototype/proto_blender_v5.py.
Proposes seams only; does not alter existing UV maps or artist seams.
Leaves the object exactly as it found it (Object Mode, selection, active UV map,
existing UV layer data, and edge seam flags restored in a finally block).
"""
import heapq
import math
import time
import numpy as np
import bpy
import bmesh
from mathutils.bvhtree import BVHTree
from mathutils import Vector

# Fixed Candidate C1 constants (decision 40)
SOFT_DEG = 30.0
SOFT_RAD = math.radians(SOFT_DEG)
THR = 1.25
METHOD = 'ANGLE_BASED'
BUDGET = 600.0
MIN_SPLIT = 12
TRIES = 4
STRIP_K = 0.0075
STRIP_AREA = 0.001
WORST = 2.0
MS_ITER = 50
FILL_MIN = 0.5
FILL_GAIN = 1.25
TREE_FACES = 512
# Progress inside one mesh: stages in order with their share of the run time, from OVERHEAD_SHELL,
# COCKPIT_SHELL_FLOOR and @MERGE_PEDESTAL_SHELL together (journal Session 90); single meshes differ a lot
PROGRESS_STAGES = (('Seeding', 0.15), ('Merging', 0.42), ('Strips', 0.12), ('Smoothing', 0.02), ('Wall cuts', 0.03),
                   ('Final unwrap', 0.01), ('Repair', 0.04), ('Worst triangles', 0.01), ('Rings and frames', 0.02),
                   ('Final check', 0.18))
PROGRESS_INTERVAL = 0.25  # seconds between progress reports: the caller may redraw, which costs a few milliseconds


def _tri_area3(P3):
    return 0.5 * np.linalg.norm(np.cross(P3[:, 1] - P3[:, 0], P3[:, 2] - P3[:, 0]), axis=1)


def _tri_area2_signed(U):
    a = U[:, 1] - U[:, 0]
    b = U[:, 2] - U[:, 0]
    return 0.5 * (a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0])


def _area_distortion(P3, U):
    a3 = _tri_area3(P3)
    a2 = np.abs(_tri_area2_signed(U))
    if a3.sum() == 0 or a2.sum() == 0:
        return 1.0, 1.0, np.ones(len(a3))
    tot = a2.sum() / a3.sum()
    ok = a3 > 0
    r = np.full(len(a3), np.nan)
    with np.errstate(divide='ignore', invalid='ignore'):
        r[ok] = (a2[ok] / a3[ok]) / tot
        r[ok] = np.where(r[ok] < 1.0, 1.0 / r[ok], r[ok])
    v = r[ok]
    return float(np.mean(v)), float(np.max(v)), r


def _flipped_count(U):
    s = _tri_area2_signed(U)
    nz = np.abs(s) > 0
    if nz.sum() == 0:
        return 0
    pos = (s > 0).sum()
    neg = (s < 0).sum()
    return int(min(pos, neg))


def _overlap_pairs(U, eps_rel=1e-6, max_pairs_chunk=200000):
    n = len(U)
    if n < 2:
        return np.zeros((0, 2), np.int64)
    lo = U.min(1)
    hi = U.max(1)
    allp = U.reshape(-1, 2)
    ext = float((allp.max(0) - allp.min(0)).max())
    if ext <= 0:
        return np.zeros((0, 2), np.int64)
    eps = eps_rel * ext
    cell = max(float(np.median((hi - lo).max(1))) * 1.5, ext / 4096)
    o = allp.min(0)
    i0 = np.floor((lo - o) / cell).astype(np.int64)
    i1 = np.floor((hi - o) / cell).astype(np.int64)
    W = int(i1[:, 0].max() + 2)
    keys = []
    tris = []
    for t in range(n):
        xs = np.arange(i0[t, 0], i1[t, 0] + 1)
        ys = np.arange(i0[t, 1], i1[t, 1] + 1)
        k = (ys[:, None] * W + xs[None, :]).ravel()
        keys.append(k)
        tris.append(np.full(len(k), t))
    keys = np.concatenate(keys)
    tris = np.concatenate(tris)
    order = np.argsort(keys, kind='stable')
    keys = keys[order]
    tris = tris[order]
    bounds = np.flatnonzero(np.diff(keys)) + 1
    starts = np.concatenate([[0], bounds])
    ends = np.concatenate([bounds, [len(keys)]])
    big = np.flatnonzero(ends - starts > 1)
    pa = []
    pb = []
    for g in big:
        ts = tris[starts[g]:ends[g]]
        a, b = np.triu_indices(len(ts), 1)
        pa.append(ts[a])
        pb.append(ts[b])
    if not pa:
        return np.zeros((0, 2), np.int64)
    pairs = np.stack([np.concatenate(pa), np.concatenate(pb)], 1)
    pairs = np.sort(pairs, 1)
    pairs = np.unique(pairs, axis=0)
    A = pairs[:, 0]
    B = pairs[:, 1]
    m = np.all(lo[A] < hi[B] - eps, 1) & np.all(lo[B] < hi[A] - eps, 1)
    pairs = pairs[m]
    res = []
    for s in range(0, len(pairs), max_pairs_chunk):
        pr = pairs[s:s + max_pairs_chunk]
        TA = U[pr[:, 0]]
        TB = U[pr[:, 1]]
        sep = np.zeros(len(pr), bool)
        for T in (TA, TB):
            e = np.roll(T, -1, axis=1) - T
            ax = np.stack([-e[..., 1], e[..., 0]], -1)
            ln = np.linalg.norm(ax, axis=-1, keepdims=True)
            ax = ax / np.maximum(ln, 1e-30)
            pA = np.einsum('mkd,mjd->mkj', ax, TA)
            pB = np.einsum('mkd,mjd->mkj', ax, TB)
            s1 = (pA.max(2) <= pB.min(2) + eps) | (pB.max(2) <= pA.min(2) + eps)
            sep |= s1.any(1)
        res.append(pr[~sep])
    return np.concatenate(res) if res else np.zeros((0, 2), np.int64)


def propose_seams(obj, artist_seam, normal_split=None, no_cut=None, limit=THR, progress=None):
    """Propose automatic UV seams on obj.

    Parameters:
        obj: bpy.types.Object in OBJECT mode, active in current view layer.
        artist_seam: boolean sequence of length len(obj.data.edges); True for artist seams.
        normal_split: optional boolean sequence of length len(obj.data.edges); True for shading splits.
        no_cut: optional boolean sequence of length len(obj.data.edges); True for edges that must
                never be cut or act as chart boundaries (e.g. triangulation diagonals).
        limit: largest mean area distortion a chart may have (1.0 = none); higher gives fewer charts.
        progress: optional function(stage_name, fraction 0..1 of this mesh), called at most every
                  PROGRESS_INTERVAL seconds from the trial unwraps and at each stage.

    Returns:
        (auto_seam_edges, stats):
            auto_seam_edges: list of edge indices proposed as automatic seams (excluding artist seams).
            stats: dictionary containing charts count, wall_cuts, frame_cuts, stage_time, time.
    """
    me = obj.data
    orig_mode = obj.mode
    orig_active = bpy.context.view_layer.objects.active
    orig_selection = {o.name: o.select_get() for o in bpy.context.scene.objects if o.name in bpy.context.view_layer.objects}
    orig_active_uv_idx = me.uv_layers.active_index
    orig_uv_data = {layer.name: [tuple(x.uv) for x in layer.data] for layer in me.uv_layers}
    orig_edge_seams = [e.use_seam for e in me.edges]

    temp_layer = me.uv_layers.new(name='__fss_autoseam_temp__')
    temp_layer_name = temp_layer.name
    me.uv_layers.active = temp_layer

    ts = bpy.context.scene.tool_settings
    orig_uv_sync = ts.use_uv_select_sync
    orig_mesh_select_mode = tuple(ts.mesh_select_mode)

    try:
        if bpy.context.object and bpy.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for o in bpy.context.scene.objects:
            o.select_set(False)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')

        ts.use_uv_select_sync = True
        ts.mesh_select_mode = (False, False, True)

        T0 = time.perf_counter()
        tm = {}
        progress_at = [0, 0.0, 0.0]  # stage index, share of the stage done, time of the last report

        def report(force=False):
            now = time.perf_counter()
            if progress is None or (not force and now - progress_at[2] < PROGRESS_INTERVAL):
                return
            progress_at[2] = now
            i = progress_at[0]
            start = sum(w for _, w in PROGRESS_STAGES[:i])
            progress(PROGRESS_STAGES[i][0], start + PROGRESS_STAGES[i][1] * min(max(progress_at[1], 0.0), 1.0))

        def stage(i):
            progress_at[0], progress_at[1] = i, 0.0
            report(force=True)

        def advance(done, total):
            progress_at[1] = done / total if total else 1.0
            report()

        bm = bmesh.from_edit_mesh(me)
        bm.faces.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.verts.ensure_lookup_table()

        nF = len(bm.faces)
        nE = len(bm.edges)
        FV = np.array([[v.index for v in f.verts] for f in bm.faces])
        V = np.array([v.co[:] for v in bm.verts])
        FN = np.array([f.normal[:] for f in bm.faces])
        P3all = V[FV]
        area3 = _tri_area3(P3all)
        A_tot = area3.sum()
        e_faces = [[f.index for f in e.link_faces] for e in bm.edges]
        e_len = np.array([e.calc_length() for e in bm.edges])
        e_verts = np.array([[v.index for v in e.verts] for e in bm.edges])
        face_edges = [[e.index for e in f.edges] for f in bm.faces]

        if no_cut is None:
            no_cut_arr = np.zeros(nE, bool)
        else:
            no_cut_arr = np.asarray(no_cut, bool)
            if len(no_cut_arr) != nE:
                raise ValueError(f"no_cut length ({len(no_cut_arr)}) != edge count ({nE})")

        # Map faces to original polygon components across no_cut diagonals
        poly_id = list(range(nF))
        if no_cut is not None:
            def find_p(x):
                while poly_id[x] != x:
                    poly_id[x] = poly_id[poly_id[x]]
                    x = poly_id[x]
                return x
            for e in range(nE):
                if no_cut_arr[e] and len(e_faces[e]) == 2:
                    p0, p1 = find_p(e_faces[e][0]), find_p(e_faces[e][1])
                    if p0 != p1:
                        poly_id[p0] = p1
            poly_map = [find_p(f) for f in range(nF)]
        else:
            poly_map = list(range(nF))

        forced = np.zeros(nE, bool)
        why = dict(nonmanifold_or_border=0, normal_split=0, seam=0, material=0)
        for e in bm.edges:
            if no_cut_arr[e.index]:
                continue
            lf = e.link_faces
            if len(lf) != 2:
                forced[e.index] = True
                why['nonmanifold_or_border'] += 1
                continue
            f = False
            if normal_split is not None and normal_split[e.index]:
                why['normal_split'] += 1
            if artist_seam[e.index]:
                why['seam'] += 1
                f = True
            if lf[0].material_index != lf[1].material_index:
                why['material'] += 1
                f = True
            forced[e.index] = f

        cut_cost = e_len.copy()
        loop_cost = np.ones(nE)
        directions = V[e_verts[:, 1]] - V[e_verts[:, 0]]
        directions /= np.maximum(e_len[:, None], 1e-30)
        incident = [[] for _ in V]
        for e, vs in enumerate(e_verts):
            for v in vs:
                incident[v].append(e)
        for e, vs in enumerate(e_verts):
            continuation = []
            for v in vs:
                continuation.append(max((abs(float(directions[e] @ directions[q]))
                                         for q in incident[v] if q != e), default=0.0))
            loop_cost[e] = 1.0 + 2.0 * (1.0 - min(continuation))

        tree_bvh = BVHTree.FromPolygons(V.tolist(), FV.tolist(), all_triangles=True)
        radius = max(float(np.linalg.norm(np.ptp(V, axis=0))), 1e-6)
        exposure = np.zeros(nF)
        for f in range(nF):
            n = FN[f]
            tangent = np.cross(n, [1, 0, 0] if abs(n[0]) < 0.9 else [0, 1, 0])
            tangent /= max(np.linalg.norm(tangent), 1e-30)
            origin = Vector(P3all[f].mean(0) + n * radius * 1e-6)
            for ray in (n, n + tangent * 0.7, n - tangent * 0.7):
                ray = ray / max(np.linalg.norm(ray), 1e-30)
                hit = tree_bvh.ray_cast(origin, Vector(ray), radius)[0]
                exposure[f] += (hit is None) / 3.0
        for e in bm.edges:
            ef = e_faces[e.index]
            if len(ef) == 2:
                concave = e.calc_face_angle_signed(0.0) < -1e-5
                cut_cost[e.index] *= (0.35 if concave else 1.0) * (0.25 + 0.75 * exposure[ef].mean()) * loop_cost[e.index]

        soft = np.zeros(nE, bool)
        edge_dihedral = np.zeros(nE, np.float64)
        for e in bm.edges:
            if len(e_faces[e.index]) == 2:
                ang = e.calc_face_angle(0.0)
                edge_dihedral[e.index] = ang
                if not forced[e.index] and not no_cut_arr[e.index] and ang > SOFT_RAD:
                    soft[e.index] = True

        def components(face_list, edge_ok):
            fl = list(face_list)
            inset = set(fl)
            par = {f: f for f in fl}

            def find(x):
                while par[x] != x:
                    par[x] = par[par[x]]
                    x = par[x]
                return x

            for f in fl:
                for e in face_edges[f]:
                    ef = e_faces[e]
                    if len(ef) != 2:
                        continue
                    if not (no_cut_arr[e] or edge_ok(e)):
                        continue
                    g = ef[0] if ef[1] == f else ef[1]
                    if g in inset:
                        a, b = find(f), find(g)
                        if a != b:
                            par[a] = b
            groups = {}
            for f in fl:
                groups.setdefault(find(f), []).append(f)
            return list(groups.values())

        comps = components(range(nF), lambda e: not forced[e] and not soft[e])
        fc = np.zeros(nF, np.int64)
        charts = {}
        for i, c in enumerate(comps):
            charts[i] = set(c)
            fc[c] = i
        nid = [len(comps)]
        seam = np.zeros(nE, bool)
        verified = {}
        internal_seams = set()

        def recompute_seams():
            for e in range(nE):
                ef = e_faces[e]
                seam[e] = not no_cut_arr[e] and (forced[e] or (e in internal_seams) or (len(ef) == 2 and fc[ef[0]] != fc[ef[1]]))
            bm.edges.ensure_lookup_table()
            for e in bm.edges:
                e.seam = bool(seam[e.index])

        prev_sel = [set()]
        stats_trials = dict(trials=0, trial_time=0.0)
        rej = dict(dist=0, ov=0, ov_flip=0, ov_pair=0)
        last_flip = [False]

        def select_unwrap(fl, clear_edges=(), set_edges=()):
            nonlocal bm
            bm = bmesh.from_edit_mesh(me)
            bm.faces.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            bm.verts.ensure_lookup_table()
            for f in prev_sel[0]:
                F = bm.faces[f]
                F.select = False
                for v in F.verts:
                    v.select = False
                for e in F.edges:
                    e.select = False
            for f in fl:
                F = bm.faces[f]
                F.select = True
                for v in F.verts:
                    v.select = True
                for e in F.edges:
                    e.select = True
            prev_sel[0] = set(fl)
            for e in clear_edges:
                bm.edges[e].seam = False
            for e in set_edges:
                bm.edges[e].seam = True
            bmesh.update_edit_mesh(me, loop_triangles=False, destructive=False)
            bpy.ops.uv.unwrap(method=METHOD, fill_holes=False, correct_aspect=True, margin_method='FRACTION', margin=0.0)
            bm = bmesh.from_edit_mesh(me)
            bm.faces.ensure_lookup_table()

        def read_uv(fl):
            uvl = bm.loops.layers.uv.active
            return np.array([[l[uvl].uv[:] for l in bm.faces[f].loops] for f in fl], np.float64)

        def write_uv(fl, U):
            uvl = bm.loops.layers.uv.active
            for f, uu in zip(fl, U):
                for l, x in zip(bm.faces[f].loops, uu):
                    l[uvl].uv = x
            bmesh.update_edit_mesh(me, loop_triangles=False, destructive=False)

        def measure(fl, U):
            d, dmax, _ = _area_distortion(P3all[fl], U)
            fl_ = _flipped_count(U) > 0
            last_flip[0] = fl_
            pairs = _overlap_pairs(U)
            if len(pairs) > 0:
                fl_arr = np.asarray(fl)
                a0 = area3[fl_arr[pairs[:, 0]]]
                a1 = area3[fl_arr[pairs[:, 1]]]
                sliver = (a0 < 1e-8) & (a1 < 1e-8)
                ov = fl_ or (np.count_nonzero(~sliver) > 0)
            else:
                ov = fl_
            return d, dmax, ov

        chart_uv = {}
        last_trial = [None]

        def trial(faces, clear_edges=(), set_edges=()):
            t0 = time.perf_counter()
            report()
            fl = list(faces)
            select_unwrap(fl, clear_edges, set_edges)
            U = read_uv(fl)
            d, dmax, ov = measure(fl, U)
            last_trial[0] = (tuple(sorted(fl)), U[np.argsort(fl)].copy(), d, ov)
            stats_trials['trials'] += 1
            stats_trials['trial_time'] += time.perf_counter() - t0
            return d, ov, U

        def restore_seams(edges):
            bm.edges.ensure_lookup_table()
            for e in edges:
                bm.edges[e].seam = bool(seam[e])

        def neighbours(c):
            nb = {}
            ed = {}
            for f in charts[c]:
                for e in face_edges[f]:
                    if forced[e]:
                        continue
                    ef = e_faces[e]
                    g = ef[0] if ef[1] == f else ef[1]
                    d = fc[g]
                    if d != c:
                        nb[d] = nb.get(d, 0.0) + cut_cost[e]
                        ed.setdefault(d, set()).add(e)
            return nb, ed

        strip_mode = False

        def try_merge(c, cands, ed):
            for d in cands:
                fs = charts[d] | charts[c]
                dist, ov, U = trial(fs, ed[d])
                accepted = (dist <= limit) and not ov
                if accepted:
                    charts[d] = fs
                    fc[list(charts[c])] = d
                    del charts[c]
                    verified.pop(c, None)
                    verified[d] = dist
                    if last_trial[0]:
                        chart_uv.pop(c, None)
                        chart_uv[d] = (last_trial[0][0], last_trial[0][1])
                    for e in ed[d]:
                        seam[e] = False
                    return True

                rej['dist' if dist > limit else 'ov'] += 1
                if ov:
                    rej['ov_flip' if last_flip[0] else 'ov_pair'] += 1
                restore_seams(ed[d])
            return False

        recompute_seams()
        n_split = 0
        stage(0)
        seed_ids = list(charts.keys())
        for i_seed, cid in enumerate(seed_ids):
            advance(i_seed, len(seed_ids))
            fs = list(charts[cid])
            if len(fs) < MIN_SPLIT:
                continue
            d, ov, U = trial(fs)
            accepted = (d <= limit and not ov)
            if accepted:
                verified[cid] = d
                if last_trial[0]:
                    chart_uv[cid] = (last_trial[0][0], last_trial[0][1])
                continue
            cen = P3all[fs].mean(1)
            w = area3[fs] + 1e-30
            mu = (cen * w[:, None]).sum(0) / w.sum()
            C = ((cen - mu) * w[:, None]).T @ (cen - mu)
            _, axes = np.linalg.eigh(C)
            nd = FN[fs] @ axes
            dirs = np.argmax(np.concatenate([nd, -nd], 1), 1)
            dmap = dict(zip(fs, dirs))
            sub = components(fs, lambda e: (not forced[e]) and (not soft[e]) and dmap.get(e_faces[e][0]) == dmap.get(e_faces[e][1]))
            if len(sub) <= 1:
                continue
            n_split += 1
            del charts[cid]
            chart_uv.pop(cid, None)
            for s in sub:
                charts[nid[0]] = set(s)
                fc[s] = nid[0]
                nid[0] += 1
        recompute_seams()
        tm['seed'] = time.perf_counter() - T0

        # Tree dynamic programming over seed charts inside forced-cut components
        tree_start = time.perf_counter()
        leaf_faces = {c: set(fs) for c, fs in charts.items()}
        tree_trials = 0
        stage(1)
        leaves_done = [0]

        def solve(ids):
            nonlocal tree_trials
            if len(ids) == 1:
                c = ids[0]
                leaves_done[0] += 1
                advance(leaves_done[0], len(leaf_faces))
                return [(leaf_faces[c], chart_uv.get(c))]
            centers = np.array([P3all[list(leaf_faces[c])].mean((0, 1)) for c in ids])
            normals = np.array([FN[list(leaf_faces[c])].mean(0) for c in ids])
            axis = int(np.argmax(np.ptp(normals, axis=0)))
            values = normals[:, axis]
            if np.ptp(values) < 0.1:
                values = centers[:, int(np.argmax(np.ptp(centers, axis=0)))]
            order_ids = [ids[i] for i in np.argsort(values, kind='stable')]
            middle = len(ids) // 2
            children = solve(order_ids[:middle]) + solve(order_ids[middle:])
            fs = set().union(*[c_fs for c_fs, _ in children])
            if len(fs) > TREE_FACES or time.perf_counter() - T0 > BUDGET:
                return children
            groups = components(sorted(fs), lambda e: not forced[e])
            if len(groups) >= len(children):
                return children
            cuts = [e for e in range(nE) if not forced[e] and not no_cut_arr[e] and len(e_faces[e]) == 2
                    and all(f in fs for f in e_faces[e])]
            valid = True
            cand_results = []
            for group in groups:
                d, ov, U = trial(sorted(group), cuts)
                tree_trials += 1
                bad = (ov or d > limit)
                if bad:
                    valid = False
                    break
                if last_trial[0]:
                    cand_results.append((set(group), (last_trial[0][0], last_trial[0][1])))
                else:
                    cand_results.append((set(group), None))
            restore_seams(cuts)
            return cand_results if valid else children

        roots = components(range(nF), lambda e: not forced[e])
        solution = []
        for root in roots:
            solution.extend(solve(sorted(set(int(fc[f]) for f in root))))
        charts = {i: fs for i, (fs, _) in enumerate(solution)}
        chart_uv = {i: u for i, (_, u) in enumerate(solution) if u is not None}
        for c, fs in charts.items():
            fc[list(fs)] = c
        nid[0] = len(charts)
        verified.clear()
        recompute_seams()
        tm['tree'] = time.perf_counter() - tree_start
        tm['merge'] = 0.0

        # Strip absorption
        t = time.perf_counter()

        def perimeter(c):
            s = charts[c]
            L = 0.0
            for f in s:
                for e in face_edges[f]:
                    ef = e_faces[e]
                    if len(ef) != 2 or (ef[0] in s) != (ef[1] in s) or (ef[0] not in s or ef[1] not in s):
                        L += e_len[e]
            return L

        def is_strip(c):
            a = area3[list(charts[c])].sum()
            L = perimeter(c)
            return a < STRIP_AREA * A_tot or (L > 0 and a / (L * L) < STRIP_K)

        strips = sorted([c for c in charts if is_strip(c)], key=lambda c: area3[list(charts[c])].sum())
        absorbed = 0
        strip_mode = True
        stage(2)
        for i_strip, c in enumerate(strips):
            advance(i_strip, len(strips))
            if c not in charts:
                continue
            if time.perf_counter() - T0 > BUDGET * 1.5:
                break
            nb, ed = neighbours(c)
            if try_merge(c, sorted(nb.keys(), key=lambda d: (-nb[d], len(charts[d]))), ed):
                absorbed += 1
        strip_mode = False
        tm['strips'] = time.perf_counter() - t

        # Smoothing with re-verification
        t = time.perf_counter()
        fc0 = fc.copy()
        verified0 = dict(verified)
        charts0 = {k: set(v) for k, v in charts.items()}
        chart_uv0 = {k: (v[0], v[1].copy()) for k, v in chart_uv.items()}
        moved = 0
        stage(3)
        for it in range(5):
            advance(it, 5)
            ch = 0
            for f in range(nF):
                cnt = {}
                for e in face_edges[f]:
                    if forced[e]:
                        continue
                    ef = e_faces[e]
                    g = ef[0] if ef[1] == f else ef[1]
                    if fc[g] != fc[f]:
                        cnt[fc[g]] = cnt.get(fc[g], 0) + 1
                for d, k in cnt.items():
                    old_cost = new_cost = 0.0
                    for edge in face_edges[f]:
                        ef = e_faces[edge]
                        if forced[edge] or len(ef) != 2:
                            continue
                        other = ef[0] if ef[1] == f else ef[1]
                        weight = e_len[edge] * loop_cost[edge]
                        old_cost += weight * (fc[other] != fc[f])
                        new_cost += weight * (fc[other] != d)
                    improve = new_cost < old_cost - 1e-12
                    if k >= 2 and improve and len(charts[fc[f]]) > 1:
                        if any(no_cut_arr[edge] and fc[e_faces[edge][0] if e_faces[edge][1] == f else e_faces[edge][1]] != d
                               for edge in face_edges[f] if len(e_faces[edge]) == 2):
                            continue
                        charts[fc[f]].discard(f)
                        charts[d].add(f)
                        fc[f] = d
                        ch += 1
                        break
            moved += ch
            if ch == 0:
                break
        changed = set(int(x) for x in np.unique(np.concatenate([fc0[fc != fc0], fc[fc != fc0]]))) if moved else set()
        reverted_faces = 0
        rounds = 0
        while changed and rounds < 4:
            rounds += 1
            recompute_seams()
            bad = []
            for c in changed:
                if c not in charts or not charts[c]:
                    continue
                d, ov, U = trial(charts[c])
                n_c = len(components(sorted(charts[c]), lambda e: not forced[e]))
                accepted = (d <= limit and not ov and n_c == 1)
                if accepted:
                    verified[c] = d
                    if last_trial[0]:
                        chart_uv[c] = (last_trial[0][0], last_trial[0][1])
                else:
                    bad.append(c)
            changed = set()
            for c in bad:
                for f in [f for f in charts[c] if fc0[f] != c] + [f for f in range(nF) if fc0[f] == c and fc[f] != c]:
                    old, new = fc0[f], fc[f]
                    charts[new].discard(f)
                    charts[old].add(f)
                    fc[f] = old
                    reverted_faces += 1
                    changed.update([old, new])
        if changed:
            fc = fc0
            charts = charts0
            verified = verified0
            chart_uv = chart_uv0
        charts = {k: v for k, v in charts.items() if v}
        tm['smooth'] = time.perf_counter() - t

        # Wall corner cuts (Package 7)
        t_wc = time.perf_counter()
        wall_box_charts = set()
        wall_box_faces = set()
        wall_charts_tried = wall_cuts_applied = wall_fallback_applied = 0
        stage(4)
        wall_ids = list(charts.keys())
        for i_wall, c in enumerate(wall_ids):
            advance(i_wall, len(wall_ids))
            if c not in charts:
                continue
            fl = sorted(charts[c])
            if len(fl) < 12:
                continue
            w = area3[fl]
            W_tot = w.sum()
            if W_tot <= 0:
                continue
            FN_c = FN[fl]
            M = (FN_c * w[:, None]).T @ FN_c
            evals, axes = np.linalg.eigh(M)
            dom = axes[:, -1]
            if evals[-1] - evals[-2] <= 1e-12 * W_tot:
                dom = FN_c[int(np.argmax(w))]
            dots = np.abs(FN_c @ dom)
            angs = np.degrees(np.arccos(np.clip(dots, -1.0, 1.0)))
            planar_faces = [fl[i] for i in range(len(fl)) if angs[i] <= 15.0]
            wall_faces = [fl[i] for i in range(len(fl)) if angs[i] > 60.0]
            if area3[planar_faces].sum() < 0.4 * W_tot or not wall_faces:
                continue
            wall_charts_tried += 1
            fl_set = set(fl)
            corner_edges = []
            for f in wall_faces:
                for e in face_edges[f]:
                    if forced[e] or no_cut_arr[e]:
                        continue
                    ef = e_faces[e]
                    if len(ef) != 2:
                        continue
                    f0, f1 = ef[0], ef[1]
                    if f0 not in fl_set or f1 not in fl_set:
                        continue
                    ang = np.degrees(edge_dihedral[e])
                    if ang > 45.0:
                        corner_edges.append(e)
            corner_edges = list(set(corner_edges))
            if not corner_edges:
                continue
            d_old = verified.get(c, 1e9)
            select_unwrap(fl, set_edges=corner_edges)
            U = read_uv(fl)
            d_new, dmax_new, ov_new = measure(fl, U)
            accepted = (not ov_new) and (d_new <= max(limit, d_old * 1.05))
            if accepted:
                for e in corner_edges:
                    seam[e] = True
                    bm.edges[e].seam = True
                wall_cuts_applied += 1
                wall_box_faces.update(fl)
                sub_comps = components(fl, lambda e: not forced[e] and e not in corner_edges)
                if len(sub_comps) > 1:
                    for i, pc in enumerate(sub_comps):
                        pc = sorted(pc)
                        if i == 0:
                            charts[c] = set(pc)
                            fc[pc] = c
                            verified[c] = d_new
                            wall_box_charts.add(c)
                            chart_uv[c] = (tuple(pc), U[np.searchsorted(fl, pc)])
                        else:
                            new_c = nid[0]
                            nid[0] += 1
                            charts[new_c] = set(pc)
                            fc[pc] = new_c
                            verified[new_c] = d_new
                            wall_box_charts.add(new_c)
                            chart_uv[new_c] = (tuple(pc), U[np.searchsorted(fl, pc)])
                else:
                    internal_seams.update(corner_edges)
                    verified[c] = d_new
                    wall_box_charts.add(c)
                    chart_uv[c] = (tuple(fl), U)
            else:
                wall_set = set(wall_faces)
                hinge_edges = []
                for f in wall_faces:
                    for e in face_edges[f]:
                        if forced[e] or no_cut_arr[e]:
                            continue
                        ef = e_faces[e]
                        if len(ef) != 2:
                            continue
                        f0, f1 = ef[0], ef[1]
                        if f0 in fl_set and f1 in fl_set:
                            if (f0 in wall_set) != (f1 in wall_set):
                                hinge_edges.append(e)
                hinge_edges = list(set(hinge_edges))
                all_cuts = set(corner_edges) | set(hinge_edges)
                for e in all_cuts:
                    seam[e] = True
                    bm.edges[e].seam = True
                sub_comps = components(fl, lambda e: not forced[e] and e not in all_cuts)
                if len(sub_comps) > 1:
                    wall_fallback_applied += 1
                    for i, pc in enumerate(sub_comps):
                        pc = sorted(pc)
                        select_unwrap(pc)
                        U_pc = read_uv(pc)
                        d_pc, _, o_pc = measure(pc, U_pc)
                        if i == 0:
                            charts[c] = set(pc)
                            fc[pc] = c
                            verified[c] = d_pc
                            chart_uv[c] = (tuple(pc), U_pc)
                        else:
                            new_c = nid[0]
                            nid[0] += 1
                            charts[new_c] = set(pc)
                            fc[pc] = new_c
                            verified[new_c] = d_pc
                            chart_uv[new_c] = (tuple(pc), U_pc)
                else:
                    restore_seams(corner_edges)
        tm['wall_cuts'] = time.perf_counter() - t_wc

        # Final unwrap of all charts with keep_trials
        t = time.perf_counter()
        stage(5)
        recompute_seams()
        allf = list(range(nF))
        reused = missing = 0
        for c, faces in charts.items():
            fl = sorted(faces)
            entry = chart_uv.get(c)
            if entry is not None and entry[0] == tuple(fl):
                write_uv(fl, entry[1])
                reused += 1
            else:
                select_unwrap(fl)
                missing += 1
        U_all = read_uv(allf)
        tm['final_unwrap'] = time.perf_counter() - t

        mism = 0
        unver_bad = 0
        per = {}
        for c, s in charts.items():
            fl = sorted(s)
            d, dmax, ov = measure(fl, U_all[fl])
            per[c] = (d, dmax, ov)
            if c in verified:
                if abs(d - verified[c]) > 0.01 * verified[c] or ov:
                    mism += 1
            elif d > limit or ov:
                unver_bad += 1

        # Decision 49 / Decision 50: decompose an unverified chart via cost-aware cut paths
        # along original edges verified by Angle Based trial unwrap
        fallback_counts = {
            'seed_split': 0,
            'boundary_dijkstra_cut': 0,
            'normal_clustering_split': 0,
            'feature_dijkstra_cut': 0,
        }
        unverified_charts = []

        def get_dijkstra_boundary_cuts(fl_sub):
            fl_set = set(fl_sub)
            internal_cuttable_adj = {}
            b_edges = []
            for f in fl_sub:
                for e in face_edges[f]:
                    ef = e_faces[e]
                    if len(ef) == 2 and ef[0] in fl_set and ef[1] in fl_set:
                        if not forced[e] and not no_cut_arr[e]:
                            u, v = int(e_verts[e][0]), int(e_verts[e][1])
                            internal_cuttable_adj.setdefault(u, []).append((v, e))
                            internal_cuttable_adj.setdefault(v, []).append((u, e))
                    else:
                        b_edges.append(e)

            b_edges = list(set(b_edges))
            if not b_edges or not internal_cuttable_adj:
                return []

            # Build directed boundary cycle(s) from face loop winding
            directed_b = {}
            b_verts = set()
            for f in fl_sub:
                for e in face_edges[f]:
                    ef = e_faces[e]
                    if len(ef) == 2 and ef[0] in fl_set and ef[1] in fl_set:
                        continue
                    # Boundary edge: find directed orientation in face f
                    F = bm.faces[f]
                    for l in F.loops:
                        if l.edge.index == e:
                            u, v = int(l.vert.index), int(l.link_loop_next.vert.index)
                            directed_b[u] = v
                            b_verts.add(u)
                            b_verts.add(v)
                            break

            if not b_verts or not internal_cuttable_adj:
                return []

            # Trace directed boundary loops
            visited_b = set()
            loops = []
            for start_v in list(directed_b.keys()):
                if start_v in visited_b:
                    continue
                loop = []
                curr = start_v
                while curr in directed_b and curr not in visited_b:
                    visited_b.add(curr)
                    loop.append(curr)
                    curr = directed_b[curr]
                if loop and len(loop) >= 3:
                    loops.append(loop)

            def dijkstra_path(srcs, target_set):
                dist = {v: 0.0 for v in srcs}
                prev = {}
                pq = [(0.0, v) for v in srcs]
                heapq.heapify(pq)
                while pq:
                    dd, v = heapq.heappop(pq)
                    if dd > dist.get(v, 1e30):
                        continue
                    if v in target_set:
                        path = []
                        curr = v
                        while curr in prev:
                            curr, e = prev[curr]
                            path.append(e)
                        return path
                    for w, e in internal_cuttable_adj.get(v, ()):
                        weight = cut_cost[e] * loop_cost[e]
                        if v in prev:
                            prev_v, _ = prev[v]
                            inc = V[v] - V[prev_v]
                            outg = V[w] - V[v]
                            cos_val = float(inc @ outg) / max(np.linalg.norm(inc) * np.linalg.norm(outg), 1e-30)
                            weight *= 1.0 + 3.0 * (1.0 - cos_val)
                        nd_ = dd + weight
                        if nd_ < dist.get(w, 1e30):
                            dist[w] = nd_
                            prev[w] = (v, e)
                            heapq.heappush(pq, (nd_, w))
                return None

            if len(fl_sub) in (236, 110, 84, 108):
                pass
            candidates = []
            if len(loops) >= 2:
                # Multi-boundary chart (e.g. cylinder / frame with hole)
                loops.sort(key=len)
                inner = loops[0]
                outer = set.union(*[set(l) for l in loops[1:]])
                # 1-cut candidate (unrolls into 1 piece if compliant)
                p1 = dijkstra_path(inner, outer)
                if p1:
                    candidates.append(p1)
                # 2-cut candidate (opposite sides along principal axis)
                if len(inner) >= 2:
                    pts_in = V[inner]
                    cov_in = (pts_in - pts_in.mean(0)).T @ (pts_in - pts_in.mean(0))
                    _, axes_in = np.linalg.eigh(cov_in)
                    p_proj = pts_in @ axes_in[:, 2]
                    v_a = inner[int(np.argmin(p_proj))]
                    v_b = inner[int(np.argmax(p_proj))]
                    pa = dijkstra_path([v_a], outer)
                    pb = dijkstra_path([v_b], outer)
                    if pa and pb:
                        candidates.append(list(set(pa) | set(pb)))
                # 4-cut candidate (quarter points)
                if len(inner) >= 4:
                    q_indices = [0, len(inner) // 4, len(inner) // 2, (3 * len(inner)) // 4]
                    cuts4 = set()
                    for qi in q_indices:
                        pq = dijkstra_path([inner[qi]], outer)
                        if pq:
                            cuts4.update(pq)
                    if cuts4:
                        candidates.append(list(cuts4))
            elif len(loops) == 1:
                loop = loops[0]
                M = len(loop)
                if M >= 4:
                    min_sep = max(2, min(5, M // 4))
                    pts = V[loop]
                    mu = pts.mean(0)
                    cov = (pts - mu).T @ (pts - mu)
                    _, axes = np.linalg.eigh(cov)
                    p0 = pts @ axes[:, 2]
                    p1 = pts @ axes[:, 1]
                    cand_src_indices = [
                        0, M // 4, M // 2, (3 * M) // 4,
                        int(np.argmin(p0)), int(np.argmax(p0)),
                        int(np.argmin(p1)), int(np.argmax(p1))
                    ]
                    seen = set()
                    for idx in cand_src_indices:
                        src_v = loop[idx]
                        if src_v in internal_cuttable_adj and src_v not in seen:
                            seen.add(src_v)
                            targets = set(
                                loop[j] for j in range(M)
                                if min(abs(j - idx), M - abs(j - idx)) >= min_sep
                            )
                            p = dijkstra_path([src_v], targets)
                            if p:
                                candidates.append(p)

            unique_cands = []
            seen_cands = set()
            for c in candidates:
                key = tuple(sorted(c))
                if key and key not in seen_cands:
                    seen_cands.add(key)
                    unique_cands.append(c)
            return unique_cands

        def get_feature_dijkstra_cuts(fl_sub):
            fl_set = set(fl_sub)
            internal_cuttable = []
            b_edges = []
            for f in fl_sub:
                for e in face_edges[f]:
                    ef = e_faces[e]
                    if len(ef) == 2 and ef[0] in fl_set and ef[1] in fl_set:
                        if not forced[e] and not no_cut_arr[e]:
                            internal_cuttable.append(e)
                    else:
                        b_edges.append(e)
            b_edges = list(set(b_edges))
            b_verts = set(int(v) for e in b_edges for v in e_verts[e])
            if not b_verts or not internal_cuttable:
                return []

            internal_cuttable_adj = {}
            for e in internal_cuttable:
                u, v = int(e_verts[e][0]), int(e_verts[e][1])
                internal_cuttable_adj.setdefault(u, []).append((v, e))
                internal_cuttable_adj.setdefault(v, []).append((u, e))

            def dijkstra_to_targets(src, targets, forbidden_edges=set()):
                dist = {src: 0.0}
                prev = {}
                pq = [(0.0, src)]
                while pq:
                    dd, v = heapq.heappop(pq)
                    if dd > dist.get(v, 1e30):
                        continue
                    if v in targets and v != src:
                        path = []
                        curr = v
                        while curr in prev:
                            curr, e = prev[curr]
                            path.append(e)
                        return path
                    for w, e in internal_cuttable_adj.get(v, ()):
                        if e in forbidden_edges:
                            continue
                        weight = cut_cost[e] * loop_cost[e]
                        nd_ = dd + weight
                        if nd_ < dist.get(w, 1e30):
                            dist[w] = nd_
                            prev[w] = (v, e)
                            heapq.heappush(pq, (nd_, w))
                return None

            scored_edges = sorted(internal_cuttable, key=lambda e: (cut_cost[e], -edge_dihedral[e]))
            candidates = []
            for fe in scored_edges[:4]:
                u, v = int(e_verts[fe][0]), int(e_verts[fe][1])
                if u in b_verts and v in b_verts:
                    candidates.append([fe])
                    continue
                path_u = dijkstra_to_targets(u, b_verts, {fe}) if u not in b_verts else []
                path_v = dijkstra_to_targets(v, b_verts, {fe} | set(path_u if path_u else ())) if v not in b_verts else []
                if (u in b_verts or path_u) and (v in b_verts or path_v):
                    combined = (path_u if path_u else []) + [fe] + (path_v if path_v else [])
                    candidates.append(combined)

            unique_cands = []
            seen = set()
            for c in candidates:
                k = tuple(sorted(c))
                if k and k not in seen:
                    seen.add(k)
                    unique_cands.append(c)
            return unique_cands

        def get_normal_clustering_pieces(fl_sub):
            cen = P3all[fl_sub].mean(1)
            w = area3[fl_sub] + 1e-30
            mu = (cen * w[:, None]).sum(0) / w.sum()
            C = ((cen - mu) * w[:, None]).T @ (cen - mu)
            _, axes = np.linalg.eigh(C)
            nd = FN[fl_sub] @ axes
            dmap = dict(zip(fl_sub, np.argmax(np.concatenate([nd, -nd], 1), 1)))
            return components(fl_sub, lambda e: (not forced[e]) and dmap.get(e_faces[e][0]) == dmap.get(e_faces[e][1]))

        def decompose_chart(fl_init, depth=0):
            fl_init = sorted(fl_init)
            if len(fl_init) == 1:
                d, ov, U = trial(fl_init)
                if ov or d > limit:
                    crit = 'overlap' if ov else 'distortion'
                    unverified_charts.append({'chart': -1, 'faces': 1, 'distortion': float(d), 'overlap': bool(ov), 'criterion': crit})
                return [(fl_init, d, U)]

            d, ov, U = trial(fl_init)
            n_c = len(components(fl_init, lambda e: not forced[e]))
            if not ov and d <= limit and n_c == 1:
                return [(fl_init, d, U)]

            # Strategy 1: Seed pieces split (between forced and soft edges)
            subs = components(fl_init, lambda e: not forced[e] and not soft[e])
            if len(subs) > 1:
                fallback_counts['seed_split'] += 1
                res = []
                for sub in subs:
                    res.extend(decompose_chart(sub, depth + 1))
                return res

            # Strategy 2: Boundary-to-boundary Dijkstra cut (lowest-cost path between boundary points using cut_cost)
            b_cands = get_dijkstra_boundary_cuts(fl_init)
            verified_cands = []
            for cand_cut in b_cands:
                cand_pieces = components(fl_init, lambda e: not forced[e] and e not in cand_cut)
                if len(cand_pieces) == 1:
                    # Test if this cut unrolls the chart (e.g. annular ring with a radial cut)
                    select_unwrap(fl_init, set_edges=cand_cut)
                    U = read_uv(fl_init)
                    d_p, _, ov_p = measure(fl_init, U)
                    restore_seams(cand_cut)
                    if not ov_p and d_p <= limit:
                        cost = sum(cut_cost[e] for e in cand_cut)
                        verified_cands.append((1, cost, [(fl_init, d_p, U)], cand_cut))
                elif len(cand_pieces) > 1:
                    all_ok = True
                    p_res = []
                    for cp in cand_pieces:
                        cp_s = sorted(cp)
                        d_p, ov_p, U_p = trial(cp_s)
                        n_cp = len(components(cp_s, lambda e: not forced[e]))
                        if ov_p or d_p > limit or n_cp > 1:
                            all_ok = False
                            break
                        p_res.append((cp_s, d_p, U_p))
                    if all_ok:
                        cost = sum(cut_cost[e] for e in cand_cut)
                        verified_cands.append((len(cand_pieces), cost, p_res, cand_cut))

            if verified_cands:
                verified_cands.sort(key=lambda x: (x[0], x[1]))
                best = verified_cands[0]
                fallback_counts['boundary_dijkstra_cut'] += 1
                if best[0] == 1:
                    internal_seams.update(best[3])
                return best[2]

            # Strategy 3: Normal PCA clustering
            norm_pieces = get_normal_clustering_pieces(fl_init)
            if len(norm_pieces) > 1:
                all_ok = True
                p_res = []
                for np_piece in norm_pieces:
                    np_s = sorted(np_piece)
                    d_p, ov_p, U_p = trial(np_s)
                    n_cp = len(components(np_s, lambda e: not forced[e]))
                    if ov_p or d_p > limit or n_cp > 1:
                        all_ok = False
                        break
                    p_res.append((np_s, d_p, U_p))
                if all_ok:
                    fallback_counts['normal_clustering_split'] += 1
                    return p_res

            # Strategy 4: Feature / Crease Ridge Dijkstra Cut (lowest-cost cut along high-curvature crease to boundary)
            f_cands = get_feature_dijkstra_cuts(fl_init)
            verified_cands_f = []
            for cand_cut in f_cands:
                cand_pieces = components(fl_init, lambda e: not forced[e] and e not in cand_cut)
                if len(cand_pieces) > 1:
                    all_ok = True
                    p_res = []
                    for cp in cand_pieces:
                        cp_s = sorted(cp)
                        d_p, ov_p, U_p = trial(cp_s)
                        n_cp = len(components(cp_s, lambda e: not forced[e]))
                        if ov_p or d_p > limit or n_cp > 1:
                            all_ok = False
                            break
                        p_res.append((cp_s, d_p, U_p))
                    if all_ok:
                        cost = sum(cut_cost[e] for e in cand_cut)
                        verified_cands_f.append((len(cand_pieces), cost, p_res, cand_cut))

            if verified_cands_f:
                verified_cands_f.sort(key=lambda x: (x[0], x[1]))
                fallback_counts['feature_dijkstra_cut'] += 1
                return verified_cands_f[0][2]



            # If no cut gave 100% verified pieces on the first split:
            # Try recursive decomposition using the most balanced candidate cut
            best_cand = None
            best_balance = -1
            for cand_cut in (b_cands + f_cands):
                cand_pieces = components(fl_init, lambda e: not forced[e] and e not in cand_cut)
                if len(cand_pieces) > 1:
                    balance = min(len(cp) for cp in cand_pieces)
                    if balance > best_balance:
                        best_balance = balance
                        best_cand = cand_pieces

            if best_cand is not None and depth < 4:
                fallback_counts['boundary_dijkstra_cut'] += 1
                res = []
                for cp in best_cand:
                    res.extend(decompose_chart(cp, depth + 1))
                return res

            # Truly un-splittable or limit reached:
            d, ov, U = trial(fl_init)
            return [(fl_init, d, U)]

        # Repair pass per decision 49 (cuts only, no planar projection writes)
        t = time.perf_counter()
        bad_charts = [c for c, v in per.items() if v[2] or (c not in verified and v[0] > limit) or len(components(sorted(charts[c]), lambda e: not forced[e])) > 1]
        stage(6)
        for i_bad, c in enumerate(bad_charts):
            advance(i_bad, len(bad_charts))
            fl = sorted(charts[c])
            decomp = decompose_chart(fl)
            for i, (pc, d_pc, U_pc) in enumerate(decomp):
                pc_sorted = sorted(pc)
                is_ver = (d_pc <= limit) and (len(components(pc_sorted, lambda e: not forced[e])) == 1)
                _, _, o_pc = measure(pc_sorted, U_pc)
                is_ver = is_ver and not o_pc
                if i == 0:
                    charts[c] = set(pc)
                    fc[pc] = c
                    per[c] = (d_pc, 0.0, o_pc)
                    chart_uv[c] = (tuple(pc_sorted), U_pc)
                    if is_ver:
                        verified[c] = d_pc
                    else:
                        verified.pop(c, None)
                else:
                    new_cid = nid[0]
                    nid[0] += 1
                    charts[new_cid] = set(pc)
                    fc[pc] = new_cid
                    per[new_cid] = (d_pc, 0.0, o_pc)
                    chart_uv[new_cid] = (tuple(pc_sorted), U_pc)
                    if is_ver:
                        verified[new_cid] = d_pc
        recompute_seams()
        tm['repair'] = time.perf_counter() - t

        # Worst-triangle pass (Decision 49: NO minimize_stretch)
        t = time.perf_counter()
        stage(7)
        worst_before = max(v[1] for v in per.values())
        n_bad_before = sum(1 for v in per.values() if v[1] > WORST)
        split_ok = 0
        for c in [c for c, v in per.items() if v[1] > WORST]:
            if time.perf_counter() - T0 > BUDGET * 2:
                break
            fl = sorted(charts[c])
            d0, m0, _ = per[c]
            saved = read_uv(fl)
            _, _, r = _area_distortion(P3all[fl], saved)
            wf = fl[int(np.nanargmax(r))]
            sub = components(fl, lambda e: not forced[e] and not soft[e])
            done = False
            if len(sub) > 1:
                W = set(next(s for s in sub if wf in s))
                R = set(fl) - W
                cut = [e for f in W for e in face_edges[f] if not no_cut_arr[e] and len(e_faces[e]) == 2 and
                       (e_faces[e][0] in R or e_faces[e][1] in R)]
                select_unwrap(fl, set_edges=cut)
                Wl = sorted(W)
                Rl = sorted(R)
                dW, mW, oW = measure(Wl, read_uv(Wl))
                dR, mR, oR = measure(Rl, read_uv(Rl))
                if max(mW, mR) < m0 and not oW and not oR and dW <= limit and dR <= limit and len(components(Wl, lambda e: not forced[e])) == 1 and len(components(Rl, lambda e: not forced[e])) == 1:
                    charts[nid[0]] = W
                    fc[Wl] = nid[0]
                    charts[c] = R
                    for e in cut:
                        seam[e] = True
                    per[nid[0]] = (dW, mW, False)
                    per[c] = (dR, mR, False)
                    verified[nid[0]] = dW
                    verified[c] = dR
                    nid[0] += 1
                    split_ok += 1
                    done = True
                else:
                    restore_seams(cut)
                    select_unwrap(fl)
            if not done:
                write_uv(fl, saved)
        tm['worst'] = time.perf_counter() - t

        # Ring / frame straightening with frame protection
        t = time.perf_counter()
        ring_tried = ring_ok = frame_ok = 0

        def fill_of(U):
            pts = U.reshape(-1, 2)
            a = np.abs(_tri_area2_signed(U)).sum()
            p = np.unique(np.round(pts, 9), axis=0)
            if len(p) < 3 or a <= 0:
                return 1.0
            p = p[np.lexsort((p[:, 1], p[:, 0]))]

            def half(P):
                h = []
                for q in P:
                    while len(h) >= 2 and ((h[-1][0] - h[-2][0]) * (q[1] - h[-2][1]) - (h[-1][1] - h[-2][1]) * (q[0] - h[-2][0])) <= 0:
                        h.pop()
                    h.append(q)
                return h

            H = np.array(half(p)[:-1] + half(p[::-1])[:-1])
            if len(H) < 3:
                return 1.0
            e = np.roll(H, -1, 0) - H
            ang = np.arctan2(e[:, 1], e[:, 0])
            c_, s_ = np.cos(ang), np.sin(ang)
            x = H[None, :, 0] * c_[:, None] + H[None, :, 1] * s_[:, None]
            y = -H[None, :, 0] * s_[:, None] + H[None, :, 1] * c_[:, None]
            return float(a / max(((x.max(1) - x.min(1)) * (y.max(1) - y.min(1))).min(), 1e-30))

        frame_protected_skipped = 0
        stage(8)
        ring_ids = list(charts.keys())
        for i_ring, c in enumerate(ring_ids):
            advance(i_ring, len(ring_ids))
            if time.perf_counter() - T0 > BUDGET * 2.5:
                break
            if c in wall_box_charts or bool(charts[c] & wall_box_faces):
                frame_protected_skipped += 1
                continue
            fl = sorted(charts[c])
            S = charts[c]
            if len(fl) < 8:
                continue
            bed = list(set(e for f in fl for e in face_edges[f] if sum(1 for x in e_faces[e] if x in S) == 1))
            if len(bed) < 6:
                continue
            par = {}

            def find(x):
                par.setdefault(x, x)
                while par[x] != x:
                    par[x] = par[par[x]]
                    x = par[x]
                return x

            for e in bed:
                a_, b_ = find(int(e_verts[e][0])), find(int(e_verts[e][1]))
                if a_ != b_:
                    par[a_] = b_
            loops = {}
            for e in bed:
                loops.setdefault(find(int(e_verts[e][0])), []).append(e)
            if len(loops) < 2:
                continue
            saved = read_uv(fl)
            f0 = fill_of(saved)
            if f0 >= FILL_MIN:
                continue
            ring_tried += 1
            d0, m0, _ = per[c]
            L = sorted(loops.values(), key=lambda es: e_len[es].sum())
            inner = set(int(v) for e in L[0] for v in e_verts[e])
            others = set(int(v) for es in L[1:] for e in es for v in e_verts[e])
            adj = {}
            for f in fl:
                for e in face_edges[f]:
                    if forced[e] or no_cut_arr[e] or sum(1 for x in e_faces[e] if x in S) != 2:
                        continue
                    a_, b_ = int(e_verts[e][0]), int(e_verts[e][1])
                    adj.setdefault(a_, []).append((b_, e))
                    adj.setdefault(b_, []).append((a_, e))

            def path_from(srcs):
                dist = {v: 0.0 for v in srcs}
                prev = {}
                pq = [(0.0, v) for v in srcs]
                heapq.heapify(pq)
                while pq:
                    dd, v = heapq.heappop(pq)
                    if dd > dist.get(v, 1e30):
                        continue
                    if v in others:
                        out = []
                        while v in prev:
                            v, e = prev[v]
                            out.append(e)
                        return out
                    for w, e in adj.get(v, ()):
                        weight = cut_cost[e] * loop_cost[e]
                        if v in prev:
                            previous_v, _ = prev[v]
                            incoming = V[v] - V[previous_v]
                            outgoing = V[w] - V[v]
                            cosine = float(incoming @ outgoing) / max(np.linalg.norm(incoming) * np.linalg.norm(outgoing), 1e-30)
                            weight *= 1.0 + 3.0 * (1.0 - cosine)
                        nd_ = dd + weight
                        if nd_ < dist.get(w, 1e30):
                            dist[w] = nd_
                            prev[w] = (v, e)
                            heapq.heappush(pq, (nd_, w))
                return None

            vin = {}
            for e in L[0]:
                for v in e_verts[e]:
                    vin.setdefault(int(v), []).append(e)

            def turn(v):
                es = vin[v]
                if len(es) != 2:
                    return 0.0
                dv = [V[int(e_verts[e][1] if e_verts[e][0] == v else e_verts[e][0])] - V[v] for e in es]
                cs = np.dot(dv[0], dv[1]) / max(np.linalg.norm(dv[0]) * np.linalg.norm(dv[1]), 1e-30)
                return math.pi - math.acos(max(-1.0, min(1.0, cs)))

            cand = sorted(vin.keys(), key=turn, reverse=True)
            best = None
            others = set(int(v) for e in L[-1] for v in e_verts[e])
            holes = [sorted(set(int(v) for e in loop for v in e_verts[e])) for loop in L[:-1]]
            candidates = [(1, [list(inner)]),
                          (4, [[v] for v in cand[:4]]),
                          (len(holes), holes),
                          (2 * len(holes), [[v] for hole in holes for v in hole[::max(1, len(hole)//2)][:2]]),
                          (4 * len(holes), [[v] for hole in holes for v in hole[::max(1, len(hole)//4)][:4]])]
            for k, srcs_list in candidates:
                cuts = set()
                for srcs in srcs_list:
                    p = path_from(srcs)
                    if p:
                        cuts.update(p)
                if not cuts:
                    continue
                select_unwrap(fl, set_edges=cuts)
                pieces = components(fl, lambda e: not forced[e] and e not in cuts)
                ok = True
                areas = 0.0
                rects = 0.0
                res = []
                for pc in pieces:
                    pc = sorted(pc)
                    U = read_uv(pc)
                    d1, m1, o1 = measure(pc, U)
                    if o1 or d1 > limit or m1 > m0:
                        ok = False
                        break
                    fi = fill_of(U)
                    a2 = np.abs(_tri_area2_signed(U)).sum()
                    areas += a2
                    rects += a2 / fi
                    res.append((pc, d1, m1, U))
                restore_seams(cuts)
                if ok and rects > 0 and areas / rects > f0 * FILL_GAIN and (best is None or areas / rects > best[0]):
                    best = (areas / rects, k, set(cuts), res)
            if best is None:
                write_uv(fl, saved)
                continue
            _, k, cuts, res = best
            bm.edges.ensure_lookup_table()
            for e in cuts:
                seam[e] = True
                bm.edges[e].seam = True
            for i, (pc, d1, m1, U) in enumerate(res):
                write_uv(pc, U)
                if i == 0:
                    charts[c] = set(pc)
                    per[c] = (d1, m1, False)
                else:
                    charts[nid[0]] = set(pc)
                    fc[pc] = nid[0]
                    per[nid[0]] = (d1, m1, False)
                    nid[0] += 1
            if k == 1:
                ring_ok += 1
                if len(res) == 1:
                    internal_seams.update(cuts)
            else:
                frame_ok += 1
        tm['ringframe'] = time.perf_counter() - t

        # Step 3: Final gate in the core
        # Unwrap the whole work object once with the final seams;
        # every island checked for overlaps and the shape limits, failures go back to step 2;
        # the returned UVs are this unwrap.
        t_fg = time.perf_counter()
        gate_rounds = 0
        gate_repaired = 0
        unsplit_charts = set()
        stage(9)
        while gate_rounds < 10:
            advance(gate_rounds, 10)
            gate_rounds += 1
            recompute_seams()
            bm = bmesh.from_edit_mesh(me)
            bm.faces.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            bm.verts.ensure_lookup_table()
            for f in bm.faces: f.select = True
            for v in bm.verts: v.select = True
            for e in bm.edges:
                e.select = True
                e.seam = bool(seam[e.index])
            bmesh.update_edit_mesh(me, loop_triangles=False, destructive=False)
            bpy.ops.uv.unwrap(method=METHOD, fill_holes=False, correct_aspect=True, margin_method='FRACTION', margin=0.001)
            bm = bmesh.from_edit_mesh(me)
            bm.faces.ensure_lookup_table()

            uv_layer = bm.loops.layers.uv.active
            U_all = np.array([[l[uv_layer].uv[:] for l in bm.faces[f].loops] for f in range(nF)], np.float64)

            # Check every chart in this whole-object unwrap
            failing = []
            for c, fs in list(charts.items()):
                fl = sorted(fs)
                U_c = U_all[fl]
                d, dmax, ov = measure(fl, U_c)
                n_c = len(components(fl, lambda e: not forced[e]))
                if ov or d > limit or n_c > 1:
                    failing.append(c)

            if not failing:
                break

            splittable = [c for c in failing if c not in unsplit_charts]
            if not splittable:
                break

            gate_repaired += len(splittable)
            for c in splittable:
                fl = sorted(charts[c])
                decomp = decompose_chart(fl)
                if len(decomp) == 1 and decomp[0][0] == fl:
                    unsplit_charts.add(c)
                for i, (pc, d_pc, U_pc) in enumerate(decomp):
                    pc_sorted = sorted(pc)
                    is_ver = (d_pc <= limit) and (len(components(pc_sorted, lambda e: not forced[e])) == 1)
                    _, _, o_pc = measure(pc_sorted, U_pc)
                    is_ver = is_ver and not o_pc
                    if i == 0:
                        charts[c] = set(pc)
                        fc[pc] = c
                        per[c] = (d_pc, 0.0, o_pc)
                        chart_uv[c] = (tuple(pc_sorted), U_pc)
                        if is_ver:
                            verified[c] = d_pc
                        else:
                            verified.pop(c, None)
                    else:
                        new_cid = nid[0]
                        nid[0] += 1
                        charts[new_cid] = set(pc)
                        fc[pc] = new_cid
                        per[new_cid] = (d_pc, 0.0, o_pc)
                        chart_uv[new_cid] = (tuple(pc_sorted), U_pc)
                        if is_ver:
                            verified[new_cid] = d_pc

        tm['final_gate'] = time.perf_counter() - t_fg

        # Collect unverified charts and count sliver overlaps
        total_sliver_overlaps = 0
        final_unverified = []
        for c, fs in list(charts.items()):
            fl = sorted(fs)
            U_c = U_all[fl]
            d, dmax, ov = measure(fl, U_c)
            pairs = _overlap_pairs(U_c)
            if len(pairs) > 0:
                fl_arr = np.asarray(fl)
                a0 = area3[fl_arr[pairs[:, 0]]]
                a1 = area3[fl_arr[pairs[:, 1]]]
                sliver = (a0 < 1e-8) & (a1 < 1e-8)
                total_sliver_overlaps += int(np.count_nonzero(sliver))
            n_c = len(components(fl, lambda e: not forced[e]))
            if ov or d > limit or n_c > 1:
                crit = 'overlap' if ov else ('distortion' if d > limit else 'disconnected')
                final_unverified.append({
                    'chart': int(c),
                    'faces': len(fl),
                    'distortion': float(d),
                    'overlap': bool(ov),
                    'components': int(n_c),
                    'criterion': crit,
                })

        # Seam extraction: switch to Object Mode to update polygon loops
        bmesh.update_edit_mesh(me, loop_triangles=True, destructive=False)
        bpy.ops.object.mode_set(mode='OBJECT')

        uv = me.uv_layers[temp_layer_name].data
        loop_uvs = np.zeros(len(me.loops) * 2, dtype=np.float64)
        uv.foreach_get('uv', loop_uvs)
        loop_uvs = loop_uvs.reshape(-1, 2)

        sides = [[] for _ in me.edges]
        for face in me.polygons:
            loops = list(face.loop_indices)
            for i, li in enumerate(loops):
                lj = loops[(i + 1) % len(loops)]
                side = sorted([(me.loops[li].vertex_index, tuple(uv[li].uv)),
                               (me.loops[lj].vertex_index, tuple(uv[lj].uv))])
                sides[me.loops[li].edge_index].append(side)

        auto_seam_edges = []
        for e in me.edges:
            if no_cut_arr[e.index]:
                continue
            es = sides[e.index]
            if len(es) == 2 and es[0] != es[1] and not artist_seam[e.index]:
                auto_seam_edges.append(e.index)

        fb_boundary = fallback_counts['boundary_dijkstra_cut']
        fb_normal = fallback_counts['normal_clustering_split']
        fb_feature = fallback_counts['feature_dijkstra_cut']
        fb_cuts_total = fb_boundary + fb_normal + fb_feature

        stats = dict(
            charts=len(charts),
            chart_faces=[sorted(fs) for fs in charts.values()],
            wall_cuts=wall_cuts_applied,
            frame_cuts=frame_ok,
            ring_cuts=ring_ok,
            wall_fallback=wall_fallback_applied,
            frame_protected_skipped=frame_protected_skipped,
            fallback_seed=fallback_counts['seed_split'],
            fallback_boundary=fb_boundary,
            fallback_normal=fb_normal,
            fallback_feature=fb_feature,
            fallback_cuts=fb_cuts_total,
            unverified_charts=final_unverified,
            sliver_overlaps=total_sliver_overlaps,
            gate_repaired=gate_repaired,
            gate_rounds=gate_rounds,
            stage_time=tm,
            time=time.perf_counter() - T0,
            uv=loop_uvs,
        )

        return auto_seam_edges, stats

    finally:
        # Guarantee object restoration
        if bpy.context.object and bpy.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        if temp_layer_name in me.uv_layers:
            me.uv_layers.remove(me.uv_layers[temp_layer_name])
        if orig_active_uv_idx >= 0 and orig_active_uv_idx < len(me.uv_layers):
            me.uv_layers.active_index = orig_active_uv_idx
        for layer_name, old_uvs in orig_uv_data.items():
            if layer_name in me.uv_layers:
                layer = me.uv_layers[layer_name]
                for d, old_uv in zip(layer.data, old_uvs):
                    d.uv = old_uv
        for e, seam_val in zip(me.edges, orig_edge_seams):
            e.use_seam = seam_val
        for o_name, sel in orig_selection.items():
            o = bpy.context.scene.objects.get(o_name)
            if o:
                o.select_set(sel)
        ts.use_uv_select_sync = orig_uv_sync
        ts.mesh_select_mode = orig_mesh_select_mode
        if orig_mode != 'OBJECT':
            bpy.ops.object.mode_set(mode=orig_mode)
        if orig_active:
            bpy.context.view_layer.objects.active = orig_active
