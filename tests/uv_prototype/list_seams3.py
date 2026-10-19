# Round 3: per mesh object, count artist seams and check whether the existing (first) UV map is split at them.
import bpy, json
import numpy as np
rows = []
for o in bpy.data.objects:
    if o.type != 'MESH': continue
    me = o.data
    ne = len(me.edges)
    seam = np.zeros(ne, bool)
    if ne: me.edges.foreach_get('use_seam', seam)
    ns = int(seam.sum())
    r = dict(name=o.name, verts=len(me.vertices), faces=len(me.polygons), seams=ns, uv_layers=[u.name for u in me.uv_layers],
             mats=len(me.materials), mods=[m.type for m in o.modifiers], users=me.users)
    if ns and me.uv_layers and len(me.polygons):
        # for each manifold seam edge: is the UV discontinuous there? and are there UV splits off-seam?
        nl = len(me.loops)
        lv = np.zeros(nl, np.int64); me.loops.foreach_get('vertex_index', lv)
        le = np.zeros(nl, np.int64); me.loops.foreach_get('edge_index', le)
        ls = np.zeros(len(me.polygons), np.int64); me.polygons.foreach_get('loop_start', ls)
        lt = np.zeros(len(me.polygons), np.int64); me.polygons.foreach_get('loop_total', lt)
        uv = np.zeros(nl * 2); me.uv_layers[0].data.foreach_get('uv', uv); uv = uv.reshape(-1, 2)
        nx = np.arange(nl) + 1; nx[ls + lt - 1] = ls
        order = np.argsort(le, kind='stable'); cnt = np.bincount(le, minlength=ne)
        st = np.concatenate([[0], np.cumsum(cnt)[:-1]])
        two = np.flatnonzero(cnt == 2)
        l1 = order[st[two]]; l2 = order[st[two] + 1]
        m1 = np.where(lv[l2] == lv[l1], l2, nx[l2]); m2 = np.where(lv[l2] == lv[l1], nx[l2], l2)
        disc = (np.abs(uv[l1] - uv[m1]).max(1) > 1e-6) | (np.abs(uv[nx[l1]] - uv[m2]).max(1) > 1e-6)
        s2 = seam[two]
        r.update(seam_manifold=int(s2.sum()), seam_uvsplit=int((s2 & disc).sum()), uvsplit_total=int(disc.sum()),
                 uvsplit_offseam=int((~s2 & disc).sum()))
    rows.append(r)
json.dump(rows, open('seams3.json', 'w'), indent=0)
print('N', len(rows), 'with seams', sum(1 for r in rows if r['seams']))
