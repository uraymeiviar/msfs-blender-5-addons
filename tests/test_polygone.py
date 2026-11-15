"""Tests of the Polygone add-on (polygone/), in a background Blender.

    "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" -b --factory-startup --python-exit-code 1 \
        --python tests/test_polygone.py [-- <sample.glb> ...]

Imports this repository's polygone package (not a deployed copy), builds synthetic scenes and reduces them; each
.glb named after -- is imported and reduced to 10 % as a real-data check, with its numbers printed.
"""

import math
import os
import sys
import time

import bpy
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
for name in [m for m in sys.modules if m == 'polygone' or m.startswith('polygone.')]:
    del sys.modules[name]
import polygone  # noqa: E402

failures = []


def check(condition, what):
    print(('  ok   ' if condition else '  FAIL ') + what)
    if not condition:
        failures.append(what)


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    polygone.ui.LAST_RUN.clear()


def positions(me):
    co = np.empty(len(me.vertices) * 3, dtype=np.float32)
    me.vertices.foreach_get('co', co)
    return co.reshape(-1, 3)


def make_sphere(name='Sphere'):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=32, radius=1.0)
    obj = bpy.context.active_object
    obj.name = name
    me = obj.data
    bpy.ops.object.shade_smooth()
    for mat_name in ('Upper', 'Lower'):
        me.materials.append(bpy.data.materials.new(mat_name))
    centers = np.empty(len(me.polygons) * 3, dtype=np.float32)
    me.polygons.foreach_get('center', centers)
    me.polygons.foreach_set('material_index', (centers.reshape(-1, 3)[:, 2] < 0).astype(np.int32))
    # Sharp edges along the equator, a colour attribute, a lock group and an importance group.
    sharp = me.attributes.new('sharp_edge', 'BOOLEAN', 'EDGE')
    ev = np.empty(len(me.edges) * 2, dtype=np.int32)
    me.edges.foreach_get('vertices', ev)
    co = positions(me)
    ev = ev.reshape(-1, 2)
    on_equator = (np.abs(co[ev[:, 0], 2]) < 1e-4) & (np.abs(co[ev[:, 1], 2]) < 1e-4)
    sharp.data.foreach_set('value', on_equator)
    color = me.color_attributes.new('Col', 'FLOAT_COLOR', 'CORNER')
    loop_vert = np.empty(len(me.loops), dtype=np.int32)
    me.loops.foreach_get('vertex_index', loop_vert)
    rgba = np.concatenate([(co[loop_vert] + 1) / 2, np.ones((len(loop_vert), 1), dtype=np.float32)], axis=1)
    color.data.foreach_set('color', rgba.ravel())
    lock = obj.vertex_groups.new(name='lock')
    locked = [int(i) for i in np.nonzero(co[:, 0] > 0.9)[0]]
    lock.add(locked, 1.0, 'REPLACE')
    imp = obj.vertex_groups.new(name='imp')
    imp.add([int(i) for i in np.nonzero(co[:, 1] > 0.5)[0]], 0.7, 'REPLACE')
    return obj, co[locked]


def run(**settings):
    s = bpy.context.scene.fss_polygone
    for key, value in settings.items():
        setattr(s, key, value)
    start = time.perf_counter()
    result = bpy.ops.polygone.reduce_selected()
    return result, time.perf_counter() - start


def test_library():
    print('library')
    dll = polygone.native.load()
    check(dll is not None, f'bundled DLL loads ({polygone.native.error()})')


def test_new_object():
    print('new object, ratio 0.25, sharp equator, lock and importance groups')
    reset_scene()
    obj, locked_positions = make_sphere()
    tris_in = sum(len(p.vertices) - 2 for p in obj.data.polygons)
    result, seconds = run(target_mode='RATIO', ratio=0.25, output='NEW', lock_group='lock', importance_group='imp')
    check(result == {'FINISHED'}, f'operator finished ({seconds:.2f} s)')
    copy = bpy.data.objects.get('Sphere_polygone')
    check(copy is not None, 'Sphere_polygone created')
    if copy is None:
        return
    me = copy.data
    r = polygone.ui.LAST_RUN[0]
    print(f'    {r}')
    check(len(me.polygons) <= round(tris_in * 0.25) + 2, f'triangles {len(me.polygons)} near target {tris_in * 0.25:.0f}')
    check(me.validate(verbose=True) is False, 'mesh valid (validate changed nothing)')
    check([m.name for m in me.materials] == ['Upper', 'Lower'], 'materials kept')
    mats = np.empty(len(me.polygons), dtype=np.int32)
    me.polygons.foreach_get('material_index', mats)
    check(set(mats.tolist()) == {0, 1}, 'both material indices used')
    check(me.uv_layers.get('UVMap') is not None, 'UV layer UVMap kept')
    uv = np.empty(len(me.loops) * 2, dtype=np.float32)
    me.uv_layers['UVMap'].uv.foreach_get('vector', uv)
    check(np.all(np.isfinite(uv)), 'UVs finite')
    check(me.color_attributes.get('Col') is not None, 'colour attribute kept')
    n = np.empty(len(me.loops) * 3, dtype=np.float32)
    me.corner_normals.foreach_get('vector', n)
    lengths = np.linalg.norm(n.reshape(-1, 3), axis=1)
    check(np.all(np.abs(lengths - 1) < 1e-3), 'corner normals unit length')
    out = positions(me)
    found = [np.min(np.linalg.norm(out - p, axis=1)) for p in locked_positions]
    check(max(found) < 1e-6, f'all {len(locked_positions)} locked vertices kept in place (max {max(found):.2e})')
    lock = copy.vertex_groups.get('lock')
    check(lock is not None, 'vertex group lock on the copy')
    weights = [g.weight for v in me.vertices for g in v.groups if g.group == lock.index]
    check(len(weights) == len(locked_positions), f'lock weights on {len(weights)} vertices')
    check(obj.hide_get(), 'original hidden')
    check(0 < r['error'] < 0.1, f'error {r["error"]:.5f} reported')


def test_replace_keeps_modifiers():
    print('replace mesh, modifiers stay')
    reset_scene()
    obj, _ = make_sphere()
    obj.modifiers.new('Bevel', 'BEVEL')
    data_before = obj.data
    result, _s = run(target_mode='COUNT', triangles=500, output='REPLACE')
    check(result == {'FINISHED'}, 'operator finished')
    check(obj.data is not data_before, 'mesh replaced')
    check(len(obj.modifiers) == 1, 'modifier kept')
    check(len(obj.data.polygons) <= 502, f'triangles {len(obj.data.polygons)} at 500')


def test_error_only_and_subset():
    print('error only, subset placement')
    reset_scene()
    obj, _ = make_sphere()
    co_in = positions(obj.data)
    result, _s = run(target_mode='ERROR', max_error=0.01, output='NEW', placement='SUBSET')
    check(result == {'FINISHED'}, 'operator finished')
    copy = bpy.data.objects.get('Sphere_polygone')
    out = positions(copy.data)
    nearest = np.array([np.min(np.linalg.norm(co_in - p, axis=1)) for p in out])
    check(np.max(nearest) == 0.0, 'subset: every output vertex is an input vertex')
    r = polygone.ui.LAST_RUN[0]
    check(r['error'] <= 0.01 * 1.0001, f'error {r["error"]:.5f} within max error 0.01, stop: {r["stop"]}')
    check(r['tris_out'] < r['tris_in'], f'reduced {r["tris_in"]} -> {r["tris_out"]}')


def test_scaled_object_error_in_scene_units():
    print('scaled object: max error in scene units')
    reset_scene()
    obj, _ = make_sphere()
    obj.scale = (10, 10, 10)
    result, _s = run(target_mode='ERROR', max_error=0.05, output='NEW', placement='OPTIMAL')
    r = polygone.ui.LAST_RUN[0]
    check(result == {'FINISHED'} and r['error'] <= 0.05 * 1.0001, f'error {r["error"]:.5f} <= 0.05 scene units')


def test_modifiers_applied():
    print('new object from the mesh with modifiers applied')
    reset_scene()
    obj, _ = make_sphere()
    mod = obj.modifiers.new('Sub', 'SUBSURF')
    mod.levels = 1
    result, _s = run(target_mode='RATIO', ratio=0.5, output='NEW', apply_modifiers=True)
    copy = bpy.data.objects.get('Sphere_polygone')
    r = polygone.ui.LAST_RUN[0]
    check(result == {'FINISHED'} and len(copy.modifiers) == 0, 'copy has no modifiers')
    check(r['tris_in'] > 4000, f'input was the subdivided mesh ({r["tris_in"]} triangles)')
    check(len(bpy.data.meshes) <= 3, f'no leftover meshes ({len(bpy.data.meshes)})')


def test_flat_shading():
    print('flat shaded mesh: reduces, stays flat; mixed flat and smooth keeps both')
    reset_scene()
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=4)
    obj = bpy.context.active_object
    obj.name = 'Ico'
    bpy.ops.object.shade_flat()
    result, _s = run(target_mode='RATIO', ratio=0.25, output='NEW', apply_modifiers=True)
    r = polygone.ui.LAST_RUN[0]
    copy = bpy.data.objects['Ico_polygone']
    smooth = np.empty(len(copy.data.polygons), dtype=bool)
    copy.data.polygons.foreach_get('use_smooth', smooth)
    check(result == {'FINISHED'} and r['stop'] == 'target reached', f'flat ico {r["tris_in"]} -> {r["tris_out"]}, '
                                                                    f'{r["stop"]}')
    check(not np.any(smooth), 'every output face flat')
    n = np.empty(len(copy.data.loops) * 3, dtype=np.float32)
    copy.data.corner_normals.foreach_get('vector', n)
    face_n = np.empty(len(copy.data.polygons) * 3, dtype=np.float32)
    copy.data.polygons.foreach_get('normal', face_n)
    check(np.allclose(n.reshape(-1, 3), np.repeat(face_n.reshape(-1, 3), 3, axis=0), atol=1e-5),
          'flat faces shaded by their face normal')
    reset_scene()
    obj, _ = make_sphere()
    me = obj.data
    centers = np.empty(len(me.polygons) * 3, dtype=np.float32)
    me.polygons.foreach_get('center', centers)
    me.polygons.foreach_set('use_smooth', centers.reshape(-1, 3)[:, 0] < 0)  # half flat
    result, _s = run(target_mode='RATIO', ratio=0.25, output='NEW', lock_group='', importance_group='')
    copy = bpy.data.objects['Sphere_polygone']
    smooth = np.empty(len(copy.data.polygons), dtype=bool)
    copy.data.polygons.foreach_get('use_smooth', smooth)
    check(result == {'FINISHED'} and 0 < np.count_nonzero(smooth) < len(smooth),
          f'mixed: {np.count_nonzero(smooth)} smooth and {np.count_nonzero(~smooth)} flat faces')


def test_sample(path):
    print(f'sample {os.path.basename(path)}, ratio 0.1')
    reset_scene()
    bpy.ops.import_scene.gltf(filepath=path)
    for o in bpy.context.scene.objects:
        o.select_set(o.type == 'MESH')
    meshes = [o for o in bpy.context.selected_objects if o.type == 'MESH']  # not the hidden bone shapes
    result, seconds = run(target_mode='RATIO', ratio=0.1, output='NEW', hide_originals=True)
    check(result == {'FINISHED'}, f'{len(meshes)} meshes reduced in {seconds:.2f} s')
    runs = polygone.ui.LAST_RUN
    for r in runs if len(runs) <= 8 else []:
        print(f'    {r["name"]}: tris {r["tris_in"]} -> {r["tris_out"]}, verts {r["verts_in"]} -> {r["verts_out"]}, '
              f'split {r["split_in"]} -> {r["split_out"]}, '
              f'error {r["error"]:.5g} ({100 * r["relative"]:.3f} %), {r["stop"]}, {r["seconds"]:.2f} s')
    if len(runs) > 8:
        reached = sum(r['stop'] == 'target reached' for r in runs)
        print(f'    {len(runs)} meshes: tris {sum(r["tris_in"] for r in runs)} -> {sum(r["tris_out"] for r in runs)}, '
              f'{reached} reached the target, largest error {100 * max(r["relative"] for r in runs):.3f} % of size')
    invalid = [r['name'] for r in runs if bpy.data.objects[r['name']].data.validate() is not False]
    check(not invalid, f'every result mesh valid {invalid}')
    check(len(runs) == len(meshes), f'{len(runs)} results for {len(meshes)} meshes')


def main():
    polygone.register()
    try:
        test_library()
        test_new_object()
        test_replace_keeps_modifiers()
        test_error_only_and_subset()
        test_scaled_object_error_in_scene_units()
        test_modifiers_applied()
        test_flat_shading()
        argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
        for path in argv:
            test_sample(path)
    finally:
        polygone.unregister()
    print(f'\n{len(failures)} failure(s)' + (':\n  ' + '\n  '.join(failures) if failures else ''))
    sys.exit(1 if failures else 0)


main()
