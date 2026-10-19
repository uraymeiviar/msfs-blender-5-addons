# Round 5 research prototype; --keep_trials 1 preserves accepted chart UVs. Independent experimental switches: --tree 1,
# --visibility 1, --borders 1, --strips 1, --frames 1. All default off.
# Requires prep3.py's mesh/artist-seam attributes; this is not the production tool.
# --phase benchmark explicitly exports trial unwrap + unchanged baseline packing.
# --phase seams exports proposed edge flags and removes the temporary UV layer.
# See RUN.md and the task journal for measured failures and adoption decisions.
import bpy, bmesh, sys, os, time, math, json
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import uvmetrics as um

argv = sys.argv[sys.argv.index('--') + 1:]
A = dict(objects='', out='results2', soft='30', thr='1.25', method='ANGLE_BASED', budget='600', margin='0.004',
         skip_smart='0', min_split='12', tries='4', tag='proto4', strip_k='0.0075', strip_area='0.001',
         worst='2.0', ms_iter='50', forced_seams='1', forced_nsplit='0', only_smart='0', fill_min='0.5', fill_gain='1.25', tree='0', visibility='0', borders='0', strips='0', frames='0', tree_faces='512', phase='benchmark', keep_trials='0')
for i in range(0, len(argv), 2):
    A[argv[i].lstrip('-')] = argv[i + 1]
if A['phase'] not in ('benchmark', 'seams'):
    raise ValueError('--phase must be benchmark or seams')
if A['phase'] == 'seams':
    A['skip_smart'] = '1'
OUT = os.path.join(HERE, A['out']); os.makedirs(OUT, exist_ok=True)
SOFT = math.radians(float(A['soft'])); THR = float(A['thr']); METHOD = A['method']; BUDGET = float(A['budget'])
MARGIN = float(A['margin']); MIN_SPLIT = int(A['min_split']); TRIES = int(A['tries']); TAG = A['tag']
STRIP_K = float(A['strip_k']); STRIP_AREA = float(A['strip_area']); WORST = float(A['worst']); MS_ITER = int(A['ms_iter'])


def set_active(obj):
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for o in bpy.context.scene.objects:
        o.select_set(False)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)


def export(obj, layer, path, extra):
    me = obj.data
    me.calc_loop_triangles()
    nt = len(me.loop_triangles)
    T = np.zeros(nt * 3, np.int32); me.loop_triangles.foreach_get('vertices', T)
    L = np.zeros(nt * 3, np.int32); me.loop_triangles.foreach_get('loops', L)
    PI = np.zeros(nt, np.int32); me.loop_triangles.foreach_get('polygon_index', PI)
    uv = np.zeros(len(me.loops) * 2, np.float64); me.uv_layers[layer].data.foreach_get('uv', uv)
    P = np.zeros(len(me.vertices) * 3, np.float64); me.vertices.foreach_get('co', P)
    mat = np.zeros(len(me.polygons), np.int32); me.polygons.foreach_get('material_index', mat)
    np.savez(path, P=P.reshape(-1, 3), T=T.reshape(-1, 3), UV=uv.reshape(-1, 2)[L].reshape(-1, 3, 2), mat=mat[PI],
             extra=json.dumps(extra))


def pack():
    bpy.ops.uv.average_islands_scale()
    bpy.ops.uv.pack_islands(udim_source='CLOSEST_UDIM', rotate=True, rotate_method='ANY', scale=True,
                            merge_overlap=False, margin_method='FRACTION', margin=MARGIN, pin=False,
                            shape_method='CONCAVE')


def forced_flags_bm(bm):
    lay = bm.edges.layers.int.get('fss_nsplit'); slay = bm.edges.layers.int.get('fss_seam')
    nE = len(bm.edges)
    forced = np.zeros(nE, bool); why = dict(nonmanifold_or_border=0, normal_split=0, seam=0, material=0)
    for e in bm.edges:
        lf = e.link_faces
        if len(lf) != 2:
            forced[e.index] = True; why['nonmanifold_or_border'] += 1; continue
        f = False
        if lay is not None and e[lay]: why['normal_split'] += 1; f = f or A['forced_nsplit'] == '1'
        if e[slay]: why['seam'] += 1; f = f or A['forced_seams'] == '1'
        if lf[0].material_index != lf[1].material_index: why['material'] += 1; f = True
        forced[e.index] = f
    return forced, why


def export_seams_nsplit(obj, OUT, base):
    bm = bmesh.new(); bm.from_mesh(obj.data); bm.edges.ensure_lookup_table()
    slay = bm.edges.layers.int.get('fss_seam'); lay = bm.edges.layers.int.get('fss_nsplit')
    np.save(os.path.join(OUT, base + '__seams.npy'), np.array([[v.index for v in e.verts] for e in bm.edges if e[slay]], np.int64).reshape(-1, 2))
    bmesh.ops.split_edges(bm, edges=[e for e in bm.edges if e[lay] and len(e.link_faces) == 2])
    bm.verts.index_update(); bm.faces.ensure_lookup_table()
    np.save(os.path.join(OUT, base + '__nsplit_T.npy'), np.array([[v.index for v in f.verts] for f in bm.faces]))
    bm.free()


def export_split_mesh(obj, path):
    """Mesh with vertices split along proto2 forced cuts, for xatlas (binding has no material IDs / split normals)."""
    bm = bmesh.new(); bm.from_mesh(obj.data)
    bm.edges.ensure_lookup_table(); bm.faces.ensure_lookup_table()
    lay = bm.verts.layers.int.new('orig')
    for v in bm.verts: v[lay] = v.index
    forced, _ = forced_flags_bm(bm)
    cut = [e for e in bm.edges if forced[e.index] and len(e.link_faces) == 2]
    bmesh.ops.split_edges(bm, edges=cut)
    bm.verts.index_update(); bm.faces.ensure_lookup_table()
    Ps = np.array([v.co[:] for v in bm.verts]); orig = np.array([v[lay] for v in bm.verts])
    Ts = np.array([[v.index for v in f.verts] for f in bm.faces])
    np.savez(path, Ps=Ps, Ts=Ts, orig=orig)
    bm.free()


def run_smart(obj, angle):
    me = obj.data
    name = 'smart%d' % angle
    me.uv_layers.active = me.uv_layers.new(name=name)
    set_active(obj)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.context.scene.tool_settings.use_uv_select_sync = True
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.mark_seam(clear=True)  # smart_project must not see proto seams
    t0 = time.perf_counter()
    bpy.ops.uv.smart_project(angle_limit=math.radians(angle), island_margin=0.0, area_weight=0.0,
                             correct_aspect=True, scale_to_bounds=False)
    t1 = time.perf_counter()
    pack()
    t2 = time.perf_counter()
    bpy.ops.object.mode_set(mode='OBJECT')
    return name, dict(time_unwrap=t1 - t0, time_pack=t2 - t1, time=t2 - t0)


def run_proto2(obj):
    me = obj.data
    me.uv_layers.active = me.uv_layers.new(name=TAG)
    set_active(obj)
    bpy.ops.object.mode_set(mode='EDIT')
    ts = bpy.context.scene.tool_settings
    ts.use_uv_select_sync = True
    ts.mesh_select_mode = (False, False, True)
    T0 = time.perf_counter(); tm = {}
    bm = bmesh.from_edit_mesh(me)
    bm.faces.ensure_lookup_table(); bm.edges.ensure_lookup_table(); bm.verts.ensure_lookup_table()
    nF = len(bm.faces); nE = len(bm.edges)
    FV = np.array([[v.index for v in f.verts] for f in bm.faces])
    V = np.array([v.co[:] for v in bm.verts])
    FN = np.array([f.normal[:] for f in bm.faces])
    P3all = V[FV]; area3 = um.tri_area3(P3all); A_tot = area3.sum()
    e_faces = [[f.index for f in e.link_faces] for e in bm.edges]
    e_len = np.array([e.calc_length() for e in bm.edges])
    e_verts = np.array([[v.index for v in e.verts] for e in bm.edges])
    face_edges = [[e.index for e in f.edges] for f in bm.faces]
    forced, why = forced_flags_bm(bm)
    # Geometry-only cut cost. AO is sampled in object/world coordinates of the
    # prepared mesh; it is not a cockpit camera visibility measurement.
    cut_cost = e_len.copy()
    loop_cost = np.ones(nE)
    if A['visibility'] == '1' or A['borders'] == '1' or A['frames'] == '1':
        directions = V[e_verts[:, 1]] - V[e_verts[:, 0]]
        directions /= np.maximum(e_len[:, None], 1e-30)
        incident = [[] for _ in V]
        for e, vs in enumerate(e_verts):
            for v in vs: incident[v].append(e)
        for e, vs in enumerate(e_verts):
            continuation = []
            for v in vs:
                continuation.append(max((abs(float(directions[e] @ directions[q]))
                                         for q in incident[v] if q != e), default=0.0))
            loop_cost[e] = 1.0 + 2.0 * (1.0 - min(continuation))
    if A['visibility'] == '1':
        from mathutils.bvhtree import BVHTree
        from mathutils import Vector
        tree_bvh = BVHTree.FromPolygons(V.tolist(), FV.tolist(), all_triangles=True)
        radius = max(float(np.linalg.norm(np.ptp(V, axis=0))), 1e-6)
        exposure = np.zeros(nF)
        for f in range(nF):
            n = FN[f]
            tangent = np.cross(n, [1, 0, 0] if abs(n[0]) < .9 else [0, 1, 0])
            tangent /= max(np.linalg.norm(tangent), 1e-30)
            origin = Vector(P3all[f].mean(0) + n * radius * 1e-6)
            for ray in (n, n + tangent * .7, n - tangent * .7):
                ray = ray / max(np.linalg.norm(ray), 1e-30)
                hit = tree_bvh.ray_cast(origin, Vector(ray), radius)[0]
                exposure[f] += (hit is None) / 3.0
        for e in bm.edges:
            ef = e_faces[e.index]
            if len(ef) == 2:
                concave = e.calc_face_angle_signed(0.0) < -1e-5
                cut_cost[e.index] *= (.35 if concave else 1.0) * (.25 + .75 * exposure[ef].mean()) * loop_cost[e.index]
    soft = np.zeros(nE, bool)
    for e in bm.edges:
        if not forced[e.index] and e.calc_face_angle(0.0) > SOFT:
            soft[e.index] = True
    st = dict(n_forced_manifold=int(sum(1 for e in range(nE) if forced[e] and len(e_faces[e]) == 2)),
              forced_why=why, n_soft=int(soft.sum()))

    def components(face_list, edge_ok):
        fl = list(face_list); inset = set(fl)
        par = {f: f for f in fl}
        def find(x):
            while par[x] != x:
                par[x] = par[par[x]]; x = par[x]
            return x
        for f in fl:
            for e in face_edges[f]:
                ef = e_faces[e]
                if len(ef) != 2 or not edge_ok(e): continue
                g = ef[0] if ef[1] == f else ef[1]
                if g in inset:
                    a, b = find(f), find(g)
                    if a != b: par[a] = b
        groups = {}
        for f in fl:
            groups.setdefault(find(f), []).append(f)
        return list(groups.values())

    comps = components(range(nF), lambda e: not forced[e] and not soft[e])
    st['charts_seed'] = len(comps)
    fc = np.zeros(nF, np.int64); charts = {}
    for i, c in enumerate(comps):
        charts[i] = set(c); fc[c] = i
    nid = [len(comps)]
    seam = np.zeros(nE, bool)
    verified = {}

    def recompute_seams():
        for e in range(nE):
            ef = e_faces[e]
            seam[e] = forced[e] or (len(ef) == 2 and fc[ef[0]] != fc[ef[1]])
        bm.edges.ensure_lookup_table()
        for e in bm.edges:
            e.seam = bool(seam[e.index])

    prev_sel = [set()]
    stats = dict(trials=0, trial_time=0.0)
    rej = dict(dist=0, ov=0, ov_flip=0, ov_pair=0); last_flip = [False]

    def select_unwrap(fl, clear_edges=(), set_edges=()):
        nonlocal bm
        bm = bmesh.from_edit_mesh(me)
        bm.faces.ensure_lookup_table(); bm.edges.ensure_lookup_table(); bm.verts.ensure_lookup_table()
        for f in prev_sel[0]:
            F = bm.faces[f]; F.select = False
            for v in F.verts: v.select = False
            for e in F.edges: e.select = False
        for f in fl:
            F = bm.faces[f]; F.select = True
            for v in F.verts: v.select = True
            for e in F.edges: e.select = True
        prev_sel[0] = set(fl)
        for e in clear_edges: bm.edges[e].seam = False
        for e in set_edges: bm.edges[e].seam = True
        bmesh.update_edit_mesh(me, loop_triangles=False, destructive=False)
        bpy.ops.uv.unwrap(method=METHOD, fill_holes=False, correct_aspect=True, margin_method='FRACTION', margin=0.0)
        bm = bmesh.from_edit_mesh(me); bm.faces.ensure_lookup_table()

    def read_uv(fl):
        uvl = bm.loops.layers.uv.active
        return np.array([[l[uvl].uv[:] for l in bm.faces[f].loops] for f in fl], np.float64)

    def write_uv(fl, U):
        uvl = bm.loops.layers.uv.active
        for f, uu in zip(fl, U):
            for l, x in zip(bm.faces[f].loops, uu): l[uvl].uv = x
        bmesh.update_edit_mesh(me, loop_triangles=False, destructive=False)

    def measure(fl, U):
        d, dmax, _ = um.area_distortion(P3all[fl], U)
        fl_ = um.flipped_count(U) > 0
        last_flip[0] = fl_
        ov = fl_ or len(um.overlap_pairs(U)) > 0
        return d, dmax, ov

    chart_uv = {}
    last_trial = [None]

    def trial(faces, clear_edges=()):
        t0 = time.perf_counter()
        fl = list(faces)
        select_unwrap(fl, clear_edges)
        U = read_uv(fl)
        d, dmax, ov = measure(fl, U)
        if A['keep_trials'] == '1':
            last_trial[0] = (tuple(sorted(fl)), U[np.argsort(fl)].copy(), d, ov)
        stats['trials'] += 1; stats['trial_time'] += time.perf_counter() - t0
        return d, ov

    def restore_seams(edges):
        bm.edges.ensure_lookup_table()
        for e in edges: bm.edges[e].seam = bool(seam[e])

    def neighbours(c):
        nb = {}; ed = {}
        for f in charts[c]:
            for e in face_edges[f]:
                if forced[e]: continue
                ef = e_faces[e]
                g = ef[0] if ef[1] == f else ef[1]
                d = fc[g]
                if d != c:
                    nb[d] = nb.get(d, 0.0) + cut_cost[e]; ed.setdefault(d, set()).add(e)
        return nb, ed

    strip_mode = False
    def try_merge(c, cands, ed):
        for d in cands:
            fs = charts[d] | charts[c]
            dist, ov = trial(fs, ed[d])
            limit = THR
            if strip_mode and A['strips'] == '1':
                fraction = area3[list(charts[c])].sum() / max(A_tot, 1e-30)
                limit += .10 * max(0.0, 1.0 - fraction / STRIP_AREA)
            if dist <= limit and not ov:
                charts[d] = fs; fc[list(charts[c])] = d; del charts[c]; verified.pop(c, None); verified[d] = dist
                if A['keep_trials'] == '1' and last_trial[0]:
                    chart_uv.pop(c, None)
                    chart_uv[d] = (last_trial[0][0], last_trial[0][1])
                for e in ed[d]: seam[e] = False
                return True
            rej['dist' if dist > THR else 'ov'] += 1
            if ov: rej['ov_flip' if last_flip[0] else 'ov_pair'] += 1
            restore_seams(ed[d])
        return False

    recompute_seams()
    n_split = 0
    for cid in list(charts.keys()):
        fs = list(charts[cid])
        if len(fs) < MIN_SPLIT: continue
        d, ov = trial(fs)
        if d <= THR and not ov:
            verified[cid] = d
            if A['keep_trials'] == '1' and last_trial[0]:
                chart_uv[cid] = (last_trial[0][0], last_trial[0][1])
            continue
        cen = P3all[fs].mean(1); w = area3[fs] + 1e-30
        mu = (cen * w[:, None]).sum(0) / w.sum()
        C = ((cen - mu) * w[:, None]).T @ (cen - mu)
        _, axes = np.linalg.eigh(C)
        nd = FN[fs] @ axes
        dirs = np.argmax(np.concatenate([nd, -nd], 1), 1)
        dmap = dict(zip(fs, dirs))
        sub = components(fs, lambda e: (not forced[e]) and (not soft[e]) and dmap.get(e_faces[e][0]) == dmap.get(e_faces[e][1]))
        if len(sub) <= 1: continue
        n_split += 1
        del charts[cid]
        chart_uv.pop(cid, None)
        for s in sub:
            charts[nid[0]] = set(s); fc[s] = nid[0]; nid[0] += 1
    st['seed_charts_split'] = n_split; st['charts_after_split'] = len(charts)
    recompute_seams()
    tm['seed'] = time.perf_counter() - T0

    # Tree dynamic programming over seed charts inside forced-cut components.
    # Normal clustering defines the first split, centroid median breaks ties.
    # Large nodes retain their child solution without an expensive parent trial.
    if A['tree'] == '1':
        tree_start = time.perf_counter()
        leaf_faces = {c: set(fs) for c, fs in charts.items()}
        tree_trials = 0
        def solve(ids):
            nonlocal tree_trials
            if len(ids) == 1:
                c = ids[0]
                return [(leaf_faces[c], chart_uv.get(c))]
            centers = np.array([P3all[list(leaf_faces[c])].mean((0, 1)) for c in ids])
            normals = np.array([FN[list(leaf_faces[c])].mean(0) for c in ids])
            axis = int(np.argmax(np.ptp(normals, axis=0)))
            values = normals[:, axis]
            if np.ptp(values) < .1:
                values = centers[:, int(np.argmax(np.ptp(centers, axis=0)))]
            order_ids = [ids[i] for i in np.argsort(values, kind='stable')]
            middle = len(ids) // 2
            children = solve(order_ids[:middle]) + solve(order_ids[middle:])
            fs = set().union(*[c_fs for c_fs, _ in children])
            if len(fs) > int(A['tree_faces']) or time.perf_counter() - T0 > BUDGET:
                return children
            # A parent may have several components after clustering. Count the
            # actual components, not one nominal tree node, before accepting.
            groups = components(sorted(fs), lambda e: not forced[e])
            if len(groups) >= len(children):
                return children
            cuts = [e for e in range(nE) if not forced[e] and len(e_faces[e]) == 2
                    and all(f in fs for f in e_faces[e])]
            valid = True
            cand_results = []
            for group in groups:
                d, ov = trial(sorted(group), cuts)
                tree_trials += 1
                if ov or d > THR:
                    valid = False
                    break
                if A['keep_trials'] == '1' and last_trial[0]:
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
        if A['keep_trials'] == '1':
            chart_uv = {i: u for i, (_, u) in enumerate(solution) if u is not None}
        else:
            chart_uv = {}
        for c, fs in charts.items(): fc[list(fs)] = c
        nid[0] = len(charts); verified.clear(); recompute_seams()
        st['tree_parent_trials'] = tree_trials
        st['tree_charts'] = len(charts)
        tm['tree'] = time.perf_counter() - tree_start

    # merge pass
    t = time.perf_counter()
    order = sorted(charts.keys(), key=lambda c: (len(charts[c]), area3[list(charts[c])].sum()))
    budget_hit = False
    for c in (order if A['tree'] != '1' else []):
        if c not in charts: continue
        if time.perf_counter() - T0 > BUDGET:
            budget_hit = True; break
        nb, ed = neighbours(c)
        try_merge(c, sorted(nb.keys(), key=lambda d: (-nb[d], len(charts[d])))[:TRIES], ed)
    st['charts_after_merge'] = len(charts); st['budget_hit'] = budget_hit
    tm['merge'] = time.perf_counter() - t

    # strip absorption
    t = time.perf_counter()
    def perimeter(c):
        s = charts[c]; L = 0.0
        for f in s:
            for e in face_edges[f]:
                ef = e_faces[e]
                if len(ef) != 2 or (ef[0] in s) != (ef[1] in s) or (ef[0] not in s or ef[1] not in s):
                    L += e_len[e]
        return L
    def is_strip(c):
        a = area3[list(charts[c])].sum(); L = perimeter(c)
        return a < STRIP_AREA * A_tot or (L > 0 and a / (L * L) < STRIP_K)
    strips = sorted([c for c in charts if is_strip(c)], key=lambda c: area3[list(charts[c])].sum())
    st['strips_before'] = len(strips); absorbed = 0; st['rej_merge'] = dict(rej)
    strip_mode = True
    for c in strips:
        if c not in charts: continue
        if time.perf_counter() - T0 > BUDGET * 1.5: break
        nb, ed = neighbours(c)
        if try_merge(c, sorted(nb.keys(), key=lambda d: (-nb[d], len(charts[d]))), ed):
            absorbed += 1
    st['strips_absorbed'] = absorbed; st['rej_total_after_strips'] = dict(rej)
    strip_mode = False
    rem = [c for c in charts if is_strip(c)]
    st['strips_after'] = len(rem)
    st['strips_after_thin'] = sum(1 for c in rem if area3[list(charts[c])].sum() / max(perimeter(c), 1e-12) ** 2 < STRIP_K)
    st['strips_after_isolated'] = sum(1 for c in rem if not neighbours(c)[0])  # fully bounded by forced cuts
    st['charts_after_strips'] = len(charts)
    tm['strips'] = time.perf_counter() - t

    # smoothing with re-verification
    t = time.perf_counter()
    fc0 = fc.copy(); verified0 = dict(verified); charts0 = {k: set(v) for k, v in charts.items()}
    chart_uv0 = {k: (v[0], v[1].copy()) for k, v in chart_uv.items()}
    moved = 0
    for it in range(5):
        ch = 0
        for f in range(nF):
            cnt = {}
            for e in face_edges[f]:
                if forced[e]: continue
                ef = e_faces[e]
                g = ef[0] if ef[1] == f else ef[1]
                if fc[g] != fc[f]: cnt[fc[g]] = cnt.get(fc[g], 0) + 1
            for d, k in cnt.items():
                improve = True
                if A['borders'] == '1':
                    # A triangle move replaces a two-edge boundary path by the
                    # opposite edge (or reverse). Prefer collinear edge chains.
                    old_cost = new_cost = 0.0
                    for edge in face_edges[f]:
                        ef = e_faces[edge]
                        if forced[edge] or len(ef) != 2: continue
                        other = ef[0] if ef[1] == f else ef[1]
                        weight = e_len[edge] * loop_cost[edge]
                        old_cost += weight * (fc[other] != fc[f])
                        new_cost += weight * (fc[other] != d)
                    improve = new_cost < old_cost - 1e-12
                if k >= 2 and improve and len(charts[fc[f]]) > 1:
                    charts[fc[f]].discard(f); charts[d].add(f); fc[f] = d; ch += 1
                    break
        moved += ch
        if ch == 0: break
    changed = set(int(x) for x in np.unique(np.concatenate([fc0[fc != fc0], fc[fc != fc0]]))) if moved else set()
    reverted_faces = 0; rounds = 0; full_revert = False
    while changed and rounds < 4:
        rounds += 1
        recompute_seams()
        bad = []
        for c in changed:
            if c not in charts or not charts[c]: continue
            d, ov = trial(charts[c])
            if d <= THR and not ov:
                verified[c] = d
                if A['keep_trials'] == '1' and last_trial[0]:
                    chart_uv[c] = (last_trial[0][0], last_trial[0][1])
            else: bad.append(c)
        changed = set()
        for c in bad:
            for f in [f for f in charts[c] if fc0[f] != c] + [f for f in range(nF) if fc0[f] == c and fc[f] != c]:
                old, new = fc0[f], fc[f]
                charts[new].discard(f); charts[old].add(f); fc[f] = old; reverted_faces += 1
                changed.update([old, new])
    if changed:  # still unverified after 4 rounds: drop smoothing entirely
        fc = fc0; charts = charts0; verified = verified0; chart_uv = chart_uv0; full_revert = True
    charts = {k: v for k, v in charts.items() if v}
    st.update(smooth_moved=moved, smooth_reverted_faces=reverted_faces, smooth_rounds=rounds, smooth_full_revert=full_revert)
    tm['smooth'] = time.perf_counter() - t

    # final unwrap of all charts at once (seams exactly at chart borders), compare with accepted trials
    t = time.perf_counter()
    recompute_seams()
    allf = list(range(nF))
    if A['keep_trials'] == '1':
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
        st.update(trial_uv_reused=reused, trial_uv_missing=missing)
    else:
        select_unwrap(allf)
    U_all = read_uv(allf)
    tm['final_unwrap'] = time.perf_counter() - t
    mism = 0; unver_bad = 0; per = {}
    for c, s in charts.items():
        fl = sorted(s)
        d, dmax, ov = measure(fl, U_all[fl])
        per[c] = (d, dmax, ov)
        if c in verified:
            if abs(d - verified[c]) > 0.01 * verified[c] or ov: mism += 1
        elif d > THR or ov:
            unver_bad += 1
    st.update(final_vs_trial_mismatch=mism, verified_charts=sum(1 for c in charts if c in verified),
              unverified_charts_bad=unver_bad, charts_final=len(charts))

    # repair (v2b): charts whose final unwrap overlaps, or unverified charts over threshold (box-split pieces and
    # small seeds are never trial-checked), get a planar projection along their mean normal (PartUV-style box
    # fallback); pieces whose normals do not all face that direction are box-split first.
    t = time.perf_counter()
    rep = rep_fail = rep2 = rep_abf = rep_slit = 0
    if A.get('repair', '1') == '1':
        for c in [c for c, v in per.items() if v[2] or (c not in verified and v[0] > THR)]:
            fl = sorted(charts[c])
            n = (FN[fl] * area3[fl, None]).sum(0); n /= max(np.linalg.norm(n), 1e-30)
            if (FN[fl] @ n).min() > 0.05:
                groups = [fl]
            else:
                cen = P3all[fl].mean(1); w = area3[fl] + 1e-30
                mu = (cen * w[:, None]).sum(0) / w.sum(); C = ((cen - mu) * w[:, None]).T @ (cen - mu)
                _, axes = np.linalg.eigh(C); nd = FN[fl] @ axes
                dmap = dict(zip(fl, np.argmax(np.concatenate([nd, -nd], 1), 1)))
                groups = components(fl, lambda e: (not forced[e]) and dmap.get(e_faces[e][0]) == dmap.get(e_faces[e][1]))
            queue = [(sorted(g), 0) for g in groups]; first = True
            while queue:
                g, lvl = queue.pop()
                # v3c: first try the seam-respecting unwrap of the piece alone; planar projection only as fallback
                # (a projection ignores seams/slits inside the piece, which would cross artist seams)
                select_unwrap(g); U = read_uv(g); d1, m1, o1 = measure(g, U)
                if o1:
                    gn = (FN[g] * area3[g, None]).sum(0); gn /= max(np.linalg.norm(gn), 1e-30)
                    a = np.cross(gn, [1.0, 0, 0] if abs(gn[0]) < 0.9 else [0, 1.0, 0]); a /= np.linalg.norm(a); b = np.cross(gn, a)
                    U = np.stack([P3all[g] @ a, P3all[g] @ b], -1)
                    d1, m1, o1 = measure(g, U)
                    if o1 and lvl < 1 and len(g) > 1:
                        subs = components(g, lambda e: not forced[e] and not soft[e])
                        if len(subs) > 1:
                            queue += [(sorted(x), lvl + 1) for x in subs]; rep2 += 1; continue
                    gs = set(g)
                    rep_slit += int(any(forced[e] and len(e_faces[e]) == 2 and e_faces[e][0] in gs and e_faces[e][1] in gs
                                        for f in g for e in face_edges[f]))
                    write_uv(g, U)
                else:
                    rep_abf += 1
                if first:
                    charts[c] = set(g); per[c] = (d1, m1, o1); first = False
                else:
                    charts[nid[0]] = set(g); fc[g] = nid[0]; per[nid[0]] = (d1, m1, o1); nid[0] += 1
                rep += 1; rep_fail += int(o1)
    st.update(repaired_pieces=rep, repaired_still_overlap=rep_fail, repair_level2_splits=rep2, repair_abf_ok=rep_abf, repair_projection_over_slit=rep_slit)
    tm['repair'] = time.perf_counter() - t

    # worst-triangle pass
    t = time.perf_counter()
    worst_before = max(v[1] for v in per.values()); n_bad_before = sum(1 for v in per.values() if v[1] > WORST)
    split_ok = ms_ok = 0
    for c in [c for c, v in per.items() if v[1] > WORST]:
        if time.perf_counter() - T0 > BUDGET * 2: break
        fl = sorted(charts[c]); d0, m0, _ = per[c]
        saved = read_uv(fl)
        _, _, r = um.area_distortion(P3all[fl], saved)
        wf = fl[int(np.nanargmax(r))]
        sub = components(fl, lambda e: not forced[e] and not soft[e])
        done = False
        if len(sub) > 1:
            W = set(next(s for s in sub if wf in s)); R = set(fl) - W
            cut = [e for f in W for e in face_edges[f] if len(e_faces[e]) == 2 and
                   (e_faces[e][0] in R or e_faces[e][1] in R)]
            select_unwrap(fl, set_edges=cut)
            Wl = sorted(W); Rl = sorted(R)
            dW, mW, oW = measure(Wl, read_uv(Wl)); dR, mR, oR = measure(Rl, read_uv(Rl))
            if max(mW, mR) < m0 and not oW and not oR and dW <= THR and dR <= THR:
                charts[nid[0]] = W; fc[Wl] = nid[0]; charts[c] = R
                for e in cut: seam[e] = True
                per[nid[0]] = (dW, mW, False); per[c] = (dR, mR, False); nid[0] += 1
                split_ok += 1; done = True
            else:
                restore_seams(cut); select_unwrap(fl)  # back to the chart's own unwrap
        if not done:
            select_unwrap(fl)
            bpy.ops.uv.minimize_stretch(fill_holes=True, blend=0.0, iterations=MS_ITER)
            bm = bmesh.from_edit_mesh(me); bm.faces.ensure_lookup_table()
            d1, m1, o1 = measure(fl, read_uv(fl))
            if m1 < m0 and not o1 and d1 <= THR:
                per[c] = (d1, m1, False); ms_ok += 1
            else:
                write_uv(fl, saved)
    worst_after = max(v[1] for v in per.values()); n_bad_after = sum(1 for v in per.values() if v[1] > WORST)
    st.update(worst_chart_max_before=worst_before, worst_chart_max_after=worst_after, charts_over_worst_before=n_bad_before,
              charts_over_worst_after=n_bad_after, worst_split_ok=split_ok, worst_minstretch_ok=ms_ok)
    tm['worst'] = time.perf_counter() - t

    # v3: ring / frame straightening. Charts with >=2 boundary loops and low fill (uv area / min-area rectangle)
    # get k shortest cuts over soft interior edges from the smallest loop to another loop: k=1 (band -> strip),
    # k=4 from the smallest loop's sharpest corners (frame -> straight bars). Kept only if every piece passes the
    # verified check, no worse than max(1.1 x old worst face, WORST), and the fill improves by FILL_GAIN.
    import heapq
    t = time.perf_counter()
    FILL_MIN = float(A['fill_min']); FILL_GAIN = float(A['fill_gain'])
    ring_tried = ring_ok = frame_ok = 0
    def fill_of(U):
        pts = U.reshape(-1, 2); a = np.abs(um.tri_area2_signed(U)).sum()
        p = np.unique(np.round(pts, 9), axis=0)
        if len(p) < 3 or a <= 0: return 1.0
        p = p[np.lexsort((p[:, 1], p[:, 0]))]
        def half(P):
            h = []
            for q in P:
                while len(h) >= 2 and ((h[-1][0] - h[-2][0]) * (q[1] - h[-2][1]) - (h[-1][1] - h[-2][1]) * (q[0] - h[-2][0])) <= 0:
                    h.pop()
                h.append(q)
            return h
        H = np.array(half(p)[:-1] + half(p[::-1])[:-1])
        if len(H) < 3: return 1.0
        e = np.roll(H, -1, 0) - H; ang = np.arctan2(e[:, 1], e[:, 0])
        c_, s_ = np.cos(ang), np.sin(ang)
        x = H[None, :, 0] * c_[:, None] + H[None, :, 1] * s_[:, None]; y = -H[None, :, 0] * s_[:, None] + H[None, :, 1] * c_[:, None]
        return float(a / max(((x.max(1) - x.min(1)) * (y.max(1) - y.min(1))).min(), 1e-30))
    fills_before = []
    for c in list(charts.keys()):
        if time.perf_counter() - T0 > BUDGET * 2.5: break
        fl = sorted(charts[c]); S = charts[c]
        if len(fl) < 8: continue
        bed = list(set(e for f in fl for e in face_edges[f] if sum(1 for x in e_faces[e] if x in S) == 1))
        if len(bed) < 6: continue
        par = {}
        def find(x):
            par.setdefault(x, x)
            while par[x] != x:
                par[x] = par[par[x]]; x = par[x]
            return x
        for e in bed:
            a_, b_ = find(int(e_verts[e][0])), find(int(e_verts[e][1]))
            if a_ != b_: par[a_] = b_
        loops = {}
        for e in bed: loops.setdefault(find(int(e_verts[e][0])), []).append(e)
        if len(loops) < 2: continue
        saved = read_uv(fl); f0 = fill_of(saved)
        if f0 >= FILL_MIN: continue
        ring_tried += 1
        d0, m0, _ = per[c]
        L = sorted(loops.values(), key=lambda es: e_len[es].sum())
        inner = set(int(v) for e in L[0] for v in e_verts[e])
        others = set(int(v) for es in L[1:] for e in es for v in e_verts[e])
        adj = {}
        for f in fl:
            for e in face_edges[f]:
                if forced[e] or sum(1 for x in e_faces[e] if x in S) != 2: continue
                a_, b_ = int(e_verts[e][0]), int(e_verts[e][1])
                adj.setdefault(a_, []).append((b_, e)); adj.setdefault(b_, []).append((a_, e))
        def path_from(srcs):
            dist = {v: 0.0 for v in srcs}; prev = {}; pq = [(0.0, v) for v in srcs]; heapq.heapify(pq)
            while pq:
                dd, v = heapq.heappop(pq)
                if dd > dist.get(v, 1e30): continue
                if v in others:
                    out = []
                    while v in prev:
                        v, e = prev[v]; out.append(e)
                    return out
                for w, e in adj.get(v, ()):
                    weight = cut_cost[e]
                    if A['frames'] == '1':
                        weight *= loop_cost[e]
                        if v in prev:
                            previous_v, _ = prev[v]
                            incoming = V[v] - V[previous_v]; outgoing = V[w] - V[v]
                            cosine = float(incoming @ outgoing) / max(np.linalg.norm(incoming) * np.linalg.norm(outgoing), 1e-30)
                            weight *= 1.0 + 3.0 * (1.0 - cosine)
                    nd_ = dd + weight
                    if nd_ < dist.get(w, 1e30):
                        dist[w] = nd_; prev[w] = (v, e); heapq.heappush(pq, (nd_, w))
            return None
        vin = {}
        for e in L[0]:
            for v in e_verts[e]: vin.setdefault(int(v), []).append(e)
        def turn(v):
            es = vin[v]
            if len(es) != 2: return 0.0
            dv = [V[int(e_verts[e][1] if e_verts[e][0] == v else e_verts[e][0])] - V[v] for e in es]
            cs = np.dot(dv[0], dv[1]) / max(np.linalg.norm(dv[0]) * np.linalg.norm(dv[1]), 1e-30)
            return math.pi - math.acos(max(-1.0, min(1.0, cs)))
        cand = sorted(vin.keys(), key=turn, reverse=True)
        best = None
        candidates = [(1, [list(inner)]), (4, [[v] for v in cand[:4]])]
        if A['frames'] == '1':
            # Connect every hole to the largest boundary; multiple starts permit
            # straight bar decomposition of lattices with more than one hole.
            others = set(int(v) for e in L[-1] for v in e_verts[e])
            holes = [sorted(set(int(v) for e in loop for v in e_verts[e])) for loop in L[:-1]]
            candidates += [(len(holes), holes),
                           (2 * len(holes), [[v] for hole in holes for v in hole[::max(1, len(hole)//2)][:2]]),
                           (4 * len(holes), [[v] for hole in holes for v in hole[::max(1, len(hole)//4)][:4]])]
        for k, srcs_list in candidates:
            cuts = set()
            for srcs in srcs_list:
                p = path_from(srcs)
                if p: cuts.update(p)
            if not cuts: continue
            select_unwrap(fl, set_edges=cuts)
            pieces = components(fl, lambda e: not forced[e] and e not in cuts)
            ok = True; areas = 0.0; rects = 0.0; res = []
            for pc in pieces:
                pc = sorted(pc); U = read_uv(pc); d1, m1, o1 = measure(pc, U)
                if o1 or d1 > THR or m1 > (m0 if A['frames'] == '1' else max(m0 * 1.1, WORST)):
                    ok = False; break
                fi = fill_of(U); a2 = np.abs(um.tri_area2_signed(U)).sum(); areas += a2; rects += a2 / fi
                res.append((pc, d1, m1, U))
            restore_seams(cuts)
            if ok and rects > 0 and areas / rects > f0 * FILL_GAIN and (best is None or areas / rects > best[0]):
                best = (areas / rects, k, set(cuts), res)
        if best is None:
            write_uv(fl, saved); continue
        _, k, cuts, res = best
        bm.edges.ensure_lookup_table()
        for e in cuts:
            seam[e] = True; bm.edges[e].seam = True
        for i, (pc, d1, m1, U) in enumerate(res):
            write_uv(pc, U)
            if i == 0:
                charts[c] = set(pc); per[c] = (d1, m1, False)
            else:
                charts[nid[0]] = set(pc); fc[pc] = nid[0]; per[nid[0]] = (d1, m1, False); nid[0] += 1
        if k == 1: ring_ok += 1
        else: frame_ok += 1
    st.update(ringframe_tried=ring_tried, ring_cut_ok=ring_ok, frame_cut_ok=frame_ok)
    tm['ringframe'] = time.perf_counter() - t

    t = time.perf_counter()
    bm = bmesh.from_edit_mesh(me)
    for f in bm.faces: f.select = True
    for e in bm.edges: e.select = True
    for v in bm.verts: v.select = True
    bmesh.update_edit_mesh(me, loop_triangles=False, destructive=False)
    if A['phase'] == 'benchmark':
        pack()
    tm['pack'] = time.perf_counter() - t
    bpy.ops.object.mode_set(mode='OBJECT')
    st['options'] = {k: A[k] for k in ('tree', 'visibility', 'borders', 'strips', 'frames', 'tree_faces')}
    st.update(stats); st['stage_time'] = tm; st['time'] = time.perf_counter() - T0
    st.update(method=METHOD, soft_deg=float(A['soft']), thr=THR)
    return TAG, st


def emit_seams(obj, layer):
    """Persist proposal ownership; artist flags survive even at dead-end stubs.

    Use the verified UV topology because repair/frame passes can add internal
    slits not represented by face chart labels. No source UV map is modified.
    """
    me = obj.data
    artist = me.attributes['fss_seam']
    uv = me.uv_layers[layer].data
    sides = [[] for _ in me.edges]
    for face in me.polygons:
        loops = list(face.loop_indices)
        for i, li in enumerate(loops):
            lj = loops[(i + 1) % len(loops)]
            side = sorted([(me.loops[li].vertex_index, tuple(uv[li].uv)),
                           (me.loops[lj].vertex_index, tuple(uv[lj].uv))])
            sides[me.loops[li].edge_index].append(side)
    auto = me.attributes.get('fss_auto_seam')
    if auto is None:
        auto = me.attributes.new('fss_auto_seam', 'BOOLEAN', 'EDGE')
    proposal = []
    for e in me.edges:
        es = sides[e.index]
        generated = len(es) == 2 and es[0] != es[1] and not artist.data[e.index].value
        auto.data[e.index].value = generated
        e.use_seam = bool(artist.data[e.index].value or generated)
        if e.use_seam:
            proposal.append(tuple(e.vertices))
    np.save(os.path.join(OUT, obj.name + '__' + TAG + '_proposal.npy'),
            np.asarray(proposal, dtype=np.int64).reshape(-1, 2))


objs = [bpy.data.objects[n] for n in A['objects'].split(',')]
log = {}
for obj in objs:
    base = obj.name; log[base] = {}
    me = obj.data
    if me.uv_layers:
        export(obj, me.uv_layers[0].name, os.path.join(OUT, base + '__existing.npz'), dict(time=0.0))
    export_seams_nsplit(obj, OUT, base)
    if A['only_smart'] == '0':
        original_uv = {layer.name: np.array([tuple(x.uv) for x in layer.data]) for layer in me.uv_layers}
        original_active = me.uv_layers.active_index
        name, st = run_proto2(obj)
        emit_seams(obj, name)
        if A['phase'] == 'benchmark':
            export(obj, name, os.path.join(OUT, base + '__' + name + '.npz'), st)
        else:
            me.uv_layers.remove(me.uv_layers[name])
            me.uv_layers.active_index = original_active
            for layer_name, old in original_uv.items():
                assert np.array_equal(old, np.array([tuple(x.uv) for x in me.uv_layers[layer_name].data]))
            st['original_uv_unchanged'] = True
        log[base][name] = st
        print('DONE', base, name, json.dumps(st), flush=True)
    if A['skip_smart'] == '0':
        name, st = run_smart(obj, 66)
        export(obj, name, os.path.join(OUT, base + '__' + name + '.npz'), st)
        log[base][name] = st
        print('DONE', base, name, json.dumps(st), flush=True)
json.dump(log, open(os.path.join(OUT, 'blender_log_%s_%d.json' % (TAG, int(time.time()))), 'w'), indent=1)
