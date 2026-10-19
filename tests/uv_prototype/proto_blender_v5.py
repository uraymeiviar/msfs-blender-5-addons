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
         worst='2.0', ms_iter='50', forced_seams='1', forced_nsplit='0', only_smart='0', fill_min='0.5', fill_gain='1.25',
         tree='0', visibility='0', borders='0', strips='0', frames='0', tree_faces='512', phase='benchmark', keep_trials='0',
         shape_accept='0', shape_p95='1.10', shape_max='1.5', shape_tiny='0.001', shape_planar='1.02', shape_planar_deg='10.0',
         fold_rule='0', fold_angle='45.0', fold_conformal='1.05', fold_max='1.5',
         wall_cuts='0', straighten='0')
for i in range(0, len(argv), 2):
    A[argv[i].lstrip('-')] = argv[i + 1]
if 'shape' in A and 'shape_accept' not in [argv[i].lstrip('-') for i in range(0, len(argv), 2)]:
    A['shape_accept'] = A['shape']
if 'fold' in A and 'fold_rule' not in [argv[i].lstrip('-') for i in range(0, len(argv), 2)]:
    A['fold_rule'] = A['fold']
if 'walls' in A and 'wall_cuts' not in [argv[i].lstrip('-') for i in range(0, len(argv), 2)]:
    A['wall_cuts'] = A['walls']
if 'wall_corner_cuts' in A and 'wall_cuts' not in [argv[i].lstrip('-') for i in range(0, len(argv), 2)]:
    A['wall_cuts'] = A['wall_corner_cuts']
if 'straighten_strips' in A and 'straighten' not in [argv[i].lstrip('-') for i in range(0, len(argv), 2)]:
    A['straighten'] = A['straighten_strips']
if A['phase'] not in ('benchmark', 'seams'):
    raise ValueError('--phase must be benchmark or seams')
if A['phase'] == 'seams':
    A['skip_smart'] = '1'
OUT = os.path.join(HERE, A['out']); os.makedirs(OUT, exist_ok=True)
SOFT = math.radians(float(A['soft'])); THR = float(A['thr']); METHOD = A['method']; BUDGET = float(A['budget'])
MARGIN = float(A['margin']); MIN_SPLIT = int(A['min_split']); TRIES = int(A['tries']); TAG = A['tag']
STRIP_K = float(A['strip_k']); STRIP_AREA = float(A['strip_area']); WORST = float(A['worst']); MS_ITER = int(A['ms_iter'])
SHAPE_P95 = float(A['shape_p95']); SHAPE_MAX = float(A['shape_max'])
SHAPE_TINY = float(A['shape_tiny']); SHAPE_PLANAR = float(A['shape_planar'])
SHAPE_PLANAR_DEG = float(A['shape_planar_deg'])
FOLD_ANGLE = float(A['fold_angle']); FOLD_RAD = math.radians(FOLD_ANGLE)
FOLD_CONFORMAL = float(A['fold_conformal']); FOLD_MAX = float(A['fold_max'])


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


def straighten_quad_strip_faces(fl, bm, V, FV, edge_dihedral, U_curr, seam):
    """Straighten an island if it is a quad strip or grid (Follow Active Quads equivalent).
    Recovers quads from triangle pairs, computes arc-length rectangular grid, and returns U_new.
    """
    if len(fl) % 2 != 0:
        return None

    edge_fl_faces = {}
    for f in fl:
        for e in bm.faces[f].edges:
            edge_fl_faces.setdefault(e.index, []).append(f)

    diag_cands = []
    for e_idx, tris in edge_fl_faces.items():
        if len(tris) == 2 and not seam[e_idx]:
            t0, t1 = tris
            ang = edge_dihedral[e_idx]
            if ang < math.radians(60.0):
                e_verts = [v.index for v in bm.edges[e_idx].verts]
                v0, v1 = e_verts[0], e_verts[1]
                t0_v = list(FV[t0]); t1_v = list(FV[t1])
                opp0 = [v for v in t0_v if v != v0 and v != v1][0]
                opp1 = [v for v in t1_v if v != v0 and v != v1][0]
                cos_a = math.cos(ang)
                diag_cands.append((cos_a, e_idx, t0, t1, v0, v1, opp0, opp1))

    diag_cands.sort(key=lambda x: x[0], reverse=True)
    used_tris = set()
    quads = []
    for cos_a, e_idx, t0, t1, v0, v1, opp0, opp1 in diag_cands:
        if t0 not in used_tris and t1 not in used_tris:
            used_tris.add(t0); used_tris.add(t1)
            t0_v = list(FV[t0])
            i0 = t0_v.index(v0)
            if t0_v[(i0 + 1) % 3] == opp0:
                cyc = [v0, opp0, v1, opp1]
            else:
                cyc = [v0, opp1, v1, opp0]
            quads.append((cyc, t0, t1))

    if len(used_tris) != len(fl) or not quads:
        return None

    n_quads = len(quads)
    if n_quads == 1:
        cyc, t0, t1 = quads[0]
        d01 = np.linalg.norm(V[cyc[1]] - V[cyc[0]])
        d23 = np.linalg.norm(V[cyc[3]] - V[cyc[2]])
        d12 = np.linalg.norm(V[cyc[2]] - V[cyc[1]])
        d30 = np.linalg.norm(V[cyc[0]] - V[cyc[3]])
        w = 0.5 * (d01 + d23)
        h = 0.5 * (d12 + d30)
        vert_uv = {
            cyc[0]: np.array([0.0, 0.0]),
            cyc[1]: np.array([w, 0.0]),
            cyc[2]: np.array([w, h]),
            cyc[3]: np.array([0.0, h])
        }
        U_new = np.zeros_like(U_curr)
        for i, f in enumerate(fl):
            for j, l in enumerate(bm.faces[f].loops):
                U_new[i, j] = vert_uv[l.vert.index]
        return U_new

    quad_edges = []
    for cyc, _, _ in quads:
        edges = [
            tuple(sorted((cyc[0], cyc[1]))),
            tuple(sorted((cyc[1], cyc[2]))),
            tuple(sorted((cyc[2], cyc[3]))),
            tuple(sorted((cyc[3], cyc[0])))
        ]
        quad_edges.append(edges)

    e_to_q = {}
    for qi, edges in enumerate(quad_edges):
        for ed in edges:
            e_to_q.setdefault(ed, []).append(qi)

    bm.edges.ensure_lookup_table()
    q_adj = {}
    for ed, q_list in e_to_q.items():
        if len(q_list) == 2:
            v0, v1 = bm.verts[ed[0]], bm.verts[ed[1]]
            e_obj = bm.edges.get((v0, v1))
            if e_obj is not None and seam[e_obj.index]:
                continue
            q_adj.setdefault(q_list[0], []).append((q_list[1], ed))
            q_adj.setdefault(q_list[1], []).append((q_list[0], ed))
        elif len(q_list) > 2:
            return None

    deg1 = [q for q, nb in q_adj.items() if len(nb) == 1]
    deg2 = [q for q, nb in q_adj.items() if len(nb) == 2]

    # Open 1xM quad strip
    if len(deg1) == 2 and len(deg1) + len(deg2) == n_quads:
        ordered_q = [deg1[0]]
        curr = deg1[0]; prev = None
        while True:
            nxt = [q for q, ed in q_adj[curr] if q != prev]
            if not nxt: break
            prev = curr; curr = nxt[0]
            ordered_q.append(curr)
            if curr == deg1[1]: break

        shared_rung = list(set(quad_edges[ordered_q[0]]) & set(quad_edges[ordered_q[1]]))[0]
        cyc0 = quads[ordered_q[0]][0]
        for i in range(4):
            ed = tuple(sorted((cyc0[i], cyc0[(i+1)%4])))
            if ed == shared_rung:
                railA = [cyc0[(i-1)%4], cyc0[i]]
                railB = [cyc0[(i+2)%4], cyc0[(i+1)%4]]
                break

        for step in range(1, len(ordered_q)):
            qi = ordered_q[step]
            cyc = quads[qi][0]
            lastA = railA[-1]; lastB = railB[-1]
            rem = [v for v in cyc if v != lastA and v != lastB]
            if len(rem) != 2: return None
            if tuple(sorted((lastA, rem[0]))) in quad_edges[qi]:
                nextA = rem[0]; nextB = rem[1]
            else:
                nextA = rem[1]; nextB = rem[0]
            railA.append(nextA); railB.append(nextB)

        L_A = [np.linalg.norm(V[railA[k+1]] - V[railA[k]]) for k in range(len(railA)-1)]
        L_B = [np.linalg.norm(V[railB[k+1]] - V[railB[k]]) for k in range(len(railA)-1)]
        W = [np.linalg.norm(V[railB[k]] - V[railA[k]]) for k in range(len(railA))]
        W_mean = float(np.mean(W))

        U_coords = [0.0]
        for k in range(len(L_A)):
            U_coords.append(U_coords[-1] + 0.5 * (L_A[k] + L_B[k]))

        U_new = np.zeros_like(U_curr)
        for step, qi in enumerate(ordered_q):
            cyc, t0, t1 = quads[qi]
            q_v_uv = {
                railA[step]: np.array([U_coords[step], 0.0]),
                railA[step+1]: np.array([U_coords[step+1], 0.0]),
                railB[step+1]: np.array([U_coords[step+1], W_mean]),
                railB[step]: np.array([U_coords[step], W_mean])
            }
            for f_idx in [t0, t1]:
                i = fl.index(f_idx)
                for j, l in enumerate(bm.faces[f_idx].loops):
                    U_new[i, j] = q_v_uv[l.vert.index]
        return U_new

    return None


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
    edge_dihedral = np.zeros(nE, np.float64)
    for e in bm.edges:
        if len(e_faces[e.index]) == 2:
            ang = e.calc_face_angle(0.0)
            edge_dihedral[e.index] = ang
            if not forced[e.index] and ang > SOFT:
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
    rej = dict(dist=0, ov=0, ov_flip=0, ov_pair=0, fold=0); last_flip = [False]

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

    def compute_conformal(fl, U):
        P3 = P3all[fl]
        e1 = P3[:, 1] - P3[:, 0]
        e2 = P3[:, 2] - P3[:, 0]
        cross = np.cross(e1, e2)
        cross_len = np.linalg.norm(cross, axis=1)
        L_sq = np.maximum.reduce([np.sum(e1**2, axis=1), np.sum(e2**2, axis=1), np.sum((e2 - e1)**2, axis=1)])
        valid = cross_len > 1e-12 * L_sq
        if not np.any(valid):
            return valid, np.array([]), np.array([])
        length = np.linalg.norm(e1[valid], axis=1)
        h = cross_len[valid] / length
        x = np.einsum('ij,ij->i', e1[valid], e2[valid]) / length
        du = U[valid, 1] - U[valid, 0]
        dv = U[valid, 2] - U[valid, 0]
        J0 = du / length[:, None]
        J1 = (dv - du * (x / length)[:, None]) / h[:, None]
        E = J0[:, 0]**2 + J0[:, 1]**2
        G = J1[:, 0]**2 + J1[:, 1]**2
        detJ = np.abs(J0[:, 0] * J1[:, 1] - J0[:, 1] * J1[:, 0])
        xi = (E + G) / (2.0 * np.maximum(detJ, 1e-15))
        conformal = np.where(detJ > 1e-14, xi + np.sqrt(np.maximum(xi**2 - 1.0, 0.0)), np.inf)
        uv_area = 0.5 * detJ * cross_len[valid]
        collapsed = uv_area == 0
        conformal[collapsed] = np.inf
        w = cross_len[valid] / 2.0
        return valid, conformal, w

    def check_shape_island(fl, U, ov):
        if ov:
            return False, None, None, None
        valid, conformal, w = compute_conformal(fl, U)
        if len(conformal) == 0:
            return False, None, None, None
        W = w.sum()
        if W <= 0:
            return False, None, None, None
        order = np.argsort(conformal, kind='stable')
        cum = np.cumsum(w[order])
        idx = min(int(np.searchsorted(cum, 0.95 * cum[-1])), len(order) - 1)
        c_p95 = conformal[order[idx]]
        if c_p95 > SHAPE_P95:
            return False, c_p95, None, None
        non_tiny = w >= (SHAPE_TINY * W)
        if np.any(non_tiny):
            c_max = np.max(conformal[non_tiny])
            if c_max > SHAPE_MAX:
                return False, c_p95, c_max, None
        else:
            c_max = c_p95
        FN_v = FN[fl][valid]
        M = (FN_v * w[:, None]).T @ FN_v
        evals, axes = np.linalg.eigh(M)
        dom = axes[:, -1]
        if evals[-1] - evals[-2] <= 1e-12 * W:
            dom = FN_v[int(np.argmax(w))]
        planar = np.abs(FN_v @ dom) >= np.cos(np.radians(SHAPE_PLANAR_DEG)) - 1e-14
        planar_c = None
        if np.any(planar):
            wp = w[planar]
            Wp = wp.sum()
            if Wp > 0:
                planar_c = np.sum(conformal[planar] * (wp / Wp))
                if planar_c > SHAPE_PLANAR:
                    return False, c_p95, c_max, planar_c
        return True, c_p95, c_max, planar_c

    def check_fold_sides(fl, U, sides_faces, cleared_edges):
        if not any(edge_dihedral[e] > FOLD_RAD for e in cleared_edges):
            return True
        valid, conformal, w = compute_conformal(fl, U)
        if len(conformal) == 0:
            return False
        fl_valid = np.array(fl)[valid]
        face_map = {f: i for i, f in enumerate(fl_valid)}
        for side in sides_faces:
            idxs = [face_map[f] for f in side if f in face_map]
            if not idxs:
                continue
            c_s = conformal[idxs]
            w_s = w[idxs]
            W_s = w_s.sum()
            if W_s <= 0:
                continue
            order = np.argsort(c_s, kind='stable')
            cum = np.cumsum(w_s[order])
            idx = min(int(np.searchsorted(cum, 0.95 * cum[-1])), len(order) - 1)
            c_p95 = c_s[order[idx]]
            if c_p95 > FOLD_CONFORMAL:
                return False
            non_tiny = w_s >= (SHAPE_TINY * W_s)
            if np.any(non_tiny):
                c_max = np.max(c_s[non_tiny])
                if c_max > FOLD_MAX:
                    return False
        return True

    chart_uv = {}
    last_trial = [None]

    def trial(faces, clear_edges=()):
        t0 = time.perf_counter()
        fl = list(faces)
        select_unwrap(fl, clear_edges)
        U = read_uv(fl)
        d, dmax, ov = measure(fl, U)
        shape_ok = True
        if A['shape_accept'] == '1':
            shape_ok, _, _, _ = check_shape_island(fl, U, ov)
        if A['keep_trials'] == '1':
            last_trial[0] = (tuple(sorted(fl)), U[np.argsort(fl)].copy(), d, ov, shape_ok)
        stats['trials'] += 1; stats['trial_time'] += time.perf_counter() - t0
        return d, ov, shape_ok, U

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
            dist, ov, shape_ok, U = trial(fs, ed[d])
            fold_ok = True
            if A['fold_rule'] == '1':
                fold_ok = check_fold_sides(list(fs), U, [charts[c], charts[d]], ed[d])
            if A['shape_accept'] == '1':
                accepted = shape_ok and fold_ok and not ov
            else:
                limit = THR
                if strip_mode and A['strips'] == '1':
                    fraction = area3[list(charts[c])].sum() / max(A_tot, 1e-30)
                    limit += .10 * max(0.0, 1.0 - fraction / STRIP_AREA)
                accepted = (dist <= limit) and fold_ok and not ov
            if accepted:
                charts[d] = fs; fc[list(charts[c])] = d; del charts[c]; verified.pop(c, None); verified[d] = dist
                if A['keep_trials'] == '1' and last_trial[0]:
                    chart_uv.pop(c, None)
                    chart_uv[d] = (last_trial[0][0], last_trial[0][1])
                for e in ed[d]: seam[e] = False
                return True
            rej['dist' if (not shape_ok if A['shape_accept'] == '1' else dist > THR) else ('fold' if not fold_ok else 'ov')] += 1
            if ov: rej['ov_flip' if last_flip[0] else 'ov_pair'] += 1
            restore_seams(ed[d])
        return False

    recompute_seams()
    n_split = 0
    for cid in list(charts.keys()):
        fs = list(charts[cid])
        if len(fs) < MIN_SPLIT: continue
        d, ov, shape_ok, U = trial(fs)
        accepted = (shape_ok and not ov) if A['shape_accept'] == '1' else (d <= THR and not ov)
        if accepted:
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
                d, ov, shape_ok, U = trial(sorted(group), cuts)
                tree_trials += 1
                bad = (not shape_ok or ov) if A['shape_accept'] == '1' else (ov or d > THR)
                if not bad and A['fold_rule'] == '1':
                    group_set = set(group)
                    group_children = [c_fs for c_fs, _ in children if c_fs & group_set]
                    if len(group_children) > 1:
                        group_cuts = [e for e in cuts if e_faces[e][0] in group_set and e_faces[e][1] in group_set]
                        if not check_fold_sides(sorted(group), U, group_children, group_cuts):
                            bad = True
                if bad:
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
            d, ov, shape_ok, U = trial(charts[c])
            accepted = (shape_ok and not ov) if A['shape_accept'] == '1' else (d <= THR and not ov)
            if accepted:
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

    # Round 5 Package 7: wall corner cuts (Session 7 item 1)
    if A['wall_cuts'] == '1':
        t_wc = time.perf_counter()
        wall_charts_tried = wall_cuts_applied = wall_fallback_applied = 0
        for c in list(charts.keys()):
            if c not in charts: continue
            fl = sorted(charts[c])
            if len(fl) < 12: continue
            w = area3[fl]
            W_tot = w.sum()
            if W_tot <= 0: continue
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
                    if forced[e]: continue
                    ef = e_faces[e]
                    if len(ef) != 2: continue
                    f0, f1 = ef[0], ef[1]
                    if f0 not in fl_set or f1 not in fl_set: continue
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
            shape_ok = True
            if A['shape_accept'] == '1':
                shape_ok, _, _, _ = check_shape_island(fl, U, ov_new)
            accepted = (not ov_new) and (shape_ok if A['shape_accept'] == '1' else d_new <= max(THR, d_old * 1.05))
            if accepted:
                for e in corner_edges:
                    seam[e] = True
                    bm.edges[e].seam = True
                wall_cuts_applied += 1
                sub_comps = components(fl, lambda e: not forced[e] and e not in corner_edges)
                if len(sub_comps) > 1:
                    for i, pc in enumerate(sub_comps):
                        pc = sorted(pc)
                        if i == 0:
                            charts[c] = set(pc); fc[pc] = c; verified[c] = d_new
                            if A['keep_trials'] == '1':
                                chart_uv[c] = (tuple(pc), U[np.searchsorted(fl, pc)])
                        else:
                            new_c = nid[0]; nid[0] += 1
                            charts[new_c] = set(pc); fc[pc] = new_c; verified[new_c] = d_new
                            if A['keep_trials'] == '1':
                                chart_uv[new_c] = (tuple(pc), U[np.searchsorted(fl, pc)])
                else:
                    verified[c] = d_new
                    if A['keep_trials'] == '1':
                        chart_uv[c] = (tuple(fl), U)
            else:
                wall_set = set(wall_faces)
                hinge_edges = []
                for f in wall_faces:
                    for e in face_edges[f]:
                        if forced[e]: continue
                        ef = e_faces[e]
                        if len(ef) != 2: continue
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
                            charts[c] = set(pc); fc[pc] = c; verified[c] = d_pc
                            if A['keep_trials'] == '1':
                                chart_uv[c] = (tuple(pc), U_pc)
                        else:
                            new_c = nid[0]; nid[0] += 1
                            charts[new_c] = set(pc); fc[pc] = new_c; verified[new_c] = d_pc
                            if A['keep_trials'] == '1':
                                chart_uv[new_c] = (tuple(pc), U_pc)
                else:
                    restore_seams(corner_edges)
        st.update(wall_charts_tried=wall_charts_tried, wall_cuts_applied=wall_cuts_applied,
                  wall_fallback_applied=wall_fallback_applied)
        tm['wall_cuts'] = time.perf_counter() - t_wc

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

    # Round 5 Package 8: straightening (quad strips and grids)
    if A['straighten'] == '1':
        t_st = time.perf_counter()
        straight_tried = straight_ok = 0
        for c in list(charts.keys()):
            fl = sorted(charts[c])
            if len(fl) % 2 != 0:
                continue
            U_curr = read_uv(fl)
            U_new = straighten_quad_strip_faces(fl, bm, V, FV, edge_dihedral, U_curr, seam)
            if U_new is None:
                continue
            straight_tried += 1
            fl_ = um.flipped_count(U_new) > 0
            ov_pairs = len(um.overlap_pairs(U_new))
            if fl_ or ov_pairs > 0:
                continue
            m_old = um.shape_metrics(V, FV[fl], U_curr)['object']
            m_new = um.shape_metrics(V, FV[fl], U_new)['object']
            c_p95_old, c_p95_new = m_old['conformal']['p95'], m_new['conformal']['p95']
            c_max_old, c_max_new = m_old['conformal']['max'], m_new['conformal']['max']
            d_old, d_new = m_old['area_distortion']['mean'], m_new['area_distortion']['mean']
            se_old, se_new = m_old['straight_edges']['preserved_fraction'], m_new['straight_edges']['preserved_fraction']
            se_ok = (se_old is None) or (se_new is not None and se_new >= se_old - 1e-4)
            if (c_p95_new <= max(c_p95_old, 1.05) + 1e-4 and
                c_max_new <= max(c_max_old, 1.5) + 1e-4 and
                d_new <= max(THR, d_old * 1.05) and se_ok):
                write_uv(fl, U_new)
                straight_ok += 1
                if A['keep_trials'] == '1':
                    chart_uv[c] = (tuple(fl), U_new)
        st.update(straighten_tried=straight_tried, straighten_ok=straight_ok)
        tm['straighten'] = time.perf_counter() - t_st

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
    st['options'] = {k: A[k] for k in ('tree', 'visibility', 'borders', 'strips', 'frames', 'tree_faces', 'keep_trials', 'shape_accept', 'fold_rule', 'wall_cuts', 'straighten')}
    st.update(stats); st['stage_time'] = tm; st['time'] = time.perf_counter() - T0
    st.update(method=METHOD, soft_deg=float(A['soft']), thr=THR, shape_accept=A['shape_accept'],
              shape_p95=SHAPE_P95, shape_max=SHAPE_MAX, shape_tiny=SHAPE_TINY, shape_planar=SHAPE_PLANAR,
              fold_rule=A['fold_rule'], fold_angle=FOLD_ANGLE, fold_conformal=FOLD_CONFORMAL,
              wall_cuts=A['wall_cuts'], straighten=A['straighten'])
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
