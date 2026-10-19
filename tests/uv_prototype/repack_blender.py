# Round 2: load xatlas UVs into Blender and repack with the same Average Islands Scale + Pack Islands settings as proto/smart.
import bpy, sys, os, json, time
import numpy as np
argv = sys.argv[sys.argv.index('--') + 1:]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), argv[0]); objs = argv[1].split(','); MARGIN = 0.004
import bmesh
for n in objs:
    obj = bpy.data.objects[n]; me = obj.data
    # per-corner "render vertex" id when splitting only at shading (normal) splits -> lets the evaluator count
    # MSFS-relevant vertices = unique(normal-split vertex, uv)
    bm = bmesh.new(); bm.from_mesh(me); bm.faces.ensure_lookup_table()
    lay = bm.edges.layers.int.get('fss_nsplit')
    bmesh.ops.split_edges(bm, edges=[e for e in bm.edges if e[lay] and len(e.link_faces) == 2])
    bm.verts.index_update(); bm.faces.ensure_lookup_table()
    np.save(os.path.join(OUT, n + '__nsplit_T.npy'), np.array([[v.index for v in f.verts] for f in bm.faces]))
    bm.free()
    for src in ('xatlas', 'xatlascut'):
        d = np.load(os.path.join(OUT, n + '__' + src + '.npz'))
        me.calc_loop_triangles(); nt = len(me.loop_triangles)
        L = np.zeros(nt * 3, np.int32); me.loop_triangles.foreach_get('loops', L)
        T = np.zeros(nt * 3, np.int32); me.loop_triangles.foreach_get('vertices', T)
        assert np.array_equal(T.reshape(-1, 3), d['T'])
        uv = np.zeros((len(me.loops), 2)); uv[L] = d['UV'].reshape(-1, 2)
        lay = me.uv_layers.new(name=src + '_bpack'); lay.data.foreach_set('uv', uv.ravel()); me.uv_layers.active = lay
        for o in bpy.context.scene.objects: o.select_set(False)
        bpy.context.view_layer.objects.active = obj; obj.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.context.scene.tool_settings.use_uv_select_sync = True
        bpy.ops.mesh.select_all(action='SELECT')
        t0 = time.perf_counter()
        bpy.ops.uv.average_islands_scale()
        bpy.ops.uv.pack_islands(udim_source='CLOSEST_UDIM', rotate=True, rotate_method='ANY', scale=True, merge_overlap=False,
                                margin_method='FRACTION', margin=MARGIN, pin=False, shape_method='CONCAVE')
        dt = time.perf_counter() - t0
        bpy.ops.object.mode_set(mode='OBJECT')
        out = np.zeros(len(me.loops) * 2); me.uv_layers[src + '_bpack'].data.foreach_get('uv', out)
        ex = json.loads(str(d['extra'])); ex['time_xatlas'] = ex['time']; ex['time_bpack'] = dt; ex['time'] = ex['time'] + dt
        np.savez(os.path.join(OUT, n + '__' + src + '_bpack.npz'), P=d['P'], T=d['T'], UV=out.reshape(-1, 2)[L].reshape(-1, 3, 2),
                 mat=d['mat'], extra=json.dumps(ex))
        print('REPACK', n, src, dt, flush=True)
