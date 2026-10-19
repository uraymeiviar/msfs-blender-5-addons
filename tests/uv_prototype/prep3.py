# Round 3 prep (also stores artist seams as INT edge attribute fss_seam): evaluated, world-space copies; records shading (normal) splits per edge as INT edge attribute
# 'fss_nsplit' BEFORE triangulation (custom/split normals compared across each edge), then triangulates.
import bpy, bmesh, sys, json, math
import numpy as np
names = sys.argv[sys.argv.index('--')+1:]
TOL = math.cos(math.radians(1.0))
deps = bpy.context.evaluated_depsgraph_get()
info = {}; keep = []
for n in names:
    src = bpy.data.objects.get(n)
    if src is None: print('MISSING', n); continue
    ev = src.evaluated_get(deps)
    me = bpy.data.meshes.new_from_object(ev, preserve_all_data_layers=True, depsgraph=deps)
    me.transform(src.matrix_world)
    nl = len(me.loops); ne = len(me.edges)
    CN = np.zeros(nl * 3); me.corner_normals.foreach_get('vector', CN); CN = CN.reshape(-1, 3)
    lv = np.zeros(nl, np.int64); me.loops.foreach_get('vertex_index', lv)
    le = np.zeros(nl, np.int64); me.loops.foreach_get('edge_index', le)
    ls = np.zeros(len(me.polygons), np.int64); me.polygons.foreach_get('loop_start', ls)
    lt = np.zeros(len(me.polygons), np.int64); me.polygons.foreach_get('loop_total', lt)
    nx = np.arange(nl) + 1
    last = ls + lt - 1; nx[last] = ls
    order = np.argsort(le, kind='stable'); cnt = np.bincount(le, minlength=ne)
    starts = np.concatenate([[0], np.cumsum(cnt)[:-1]])
    nsplit = np.zeros(ne, np.int32)
    two = np.flatnonzero(cnt == 2)
    l1 = order[starts[two]]; l2 = order[starts[two] + 1]
    # corner of l2-face at vertex lv[l1]: either l2 or nx[l2]
    m1 = np.where(lv[l2] == lv[l1], l2, nx[l2]); m2 = np.where(lv[l2] == lv[l1], nx[l2], l2)
    d1 = np.einsum('ij,ij->i', CN[l1], CN[m1]); d2 = np.einsum('ij,ij->i', CN[nx[l1]], CN[m2])
    nsplit[two] = ((d1 < TOL) | (d2 < TOL)).astype(np.int32)
    nsplit[cnt > 2] = 1
    sh = np.zeros(ne, bool); me.attributes.get('sharp_edge') and me.attributes['sharp_edge'].data.foreach_get('value', sh)
    a = me.attributes.new('fss_nsplit', 'INT', 'EDGE'); a.data.foreach_set('value', nsplit)
    sm = np.zeros(ne, bool); me.edges.foreach_get('use_seam', sm)
    b = me.attributes.new('fss_seam', 'INT', 'EDGE'); b.data.foreach_set('value', sm.astype(np.int32))
    bm = bmesh.new(); bm.from_mesh(me)
    nf_before = len(bm.faces); nv = len(bm.verts)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bm.to_mesh(me); bm.free()
    nsp2 = np.zeros(len(me.edges), np.int32); me.attributes['fss_nsplit'].data.foreach_get('value', nsp2)
    me.name = 'W_' + n
    o = bpy.data.objects.new('W_' + n, me); keep.append(o)
    info[n] = dict(modifiers=[m.type for m in src.modifiers], eval_v=nv, eval_f=nf_before, tris=len(me.polygons),
                   materials=len(me.materials), nsplit_edges_quad=int(nsplit.sum()), nsplit_edges_tri=int(nsp2.sum()),
                   sharp_marked=int(sh.sum()), seams=sum(1 for e in me.edges if e.use_seam), has_custom_normals=me.has_custom_normals)
    print('INFO', n, json.dumps(info[n]))
others = [o for o in bpy.data.objects if o not in keep]
bpy.data.batch_remove(others)
sc = bpy.context.scene
for c in list(sc.collection.children): sc.collection.children.unlink(c)
for o in keep: sc.collection.objects.link(o)
bpy.ops.outliner.orphans_purge(do_recursive=True)
json.dump(info, open('objects_info3.json', 'w'), indent=1)
bpy.ops.wm.save_as_mainfile(filepath=bpy.path.abspath('//work3.blend'), compress=False)
