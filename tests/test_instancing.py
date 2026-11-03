"""Instancing of shared meshes whose users only have Weighted Normal or the converted Auto Smooth (EXP-008).

Each scene is built twice and exported through the real path, once with the rule off and once on, and the written glTFs
are compared with tests/harness/compare.py: the same model at its 1e-4 tolerance, fewer glTF meshes only where the rule
may act. Users evaluating differently split into groups; another modifier, shape keys and skinning leave a mesh alone;
an interactive-style export changes nothing; a multi-exporter run leaves the source objects as they were.

With the environment variable FSS_INSTANCING_RULE_OFF=1 the rule stays off for the whole run: the suite must then fail.

To run:
G:\\e-jets-e2\\tools\\blender\\blender.exe -b --factory-startup --python tests/test_instancing.py
"""

import json
import math
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import addon_utils
import bmesh
import bpy

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPORTER, TOOLS = 'io_scene_gltf2_msfs_fss', 'fss_blender_tools'

# The portable Blender enables its deployed addons_core copies at startup: disable and purge them, then import the
# repository's modules first, so addon_utils enables those. The exporter first, as fss_enable_addons.py does
for name in (TOOLS, EXPORTER):
    if addon_utils.check(name)[1]:
        addon_utils.disable(name)
for mod in list(sys.modules):
    if any(mod == name or mod.startswith(name + '.') for name in (TOOLS, EXPORTER, '_addons_common')):
        del sys.modules[mod]
for path in (str(REPO_ROOT / 'tests'), str(REPO_ROOT)):
    while path in sys.path:
        sys.path.remove(path)
    sys.path.insert(0, path)

import io_scene_gltf2_msfs_fss  # noqa: E402

addon_utils.enable(EXPORTER, default_set=True)
import fss_blender_tools  # noqa: E402

addon_utils.enable(TOOLS, default_set=True)
for module in (io_scene_gltf2_msfs_fss, fss_blender_tools, sys.modules['_addons_common']):
    assert Path(module.__file__).resolve().is_relative_to(REPO_ROOT), module.__file__

from harness.compare import compare_files  # noqa: E402
from io_scene_gltf2_msfs_fss import instancing  # noqa: E402
from io_scene_gltf2_msfs_fss.io.exp import export_settings  # noqa: E402
from io_scene_gltf2_msfs_fss.io.exp.gltf_hooks import Export  # noqa: E402

print('Testing', Path(instancing.__file__).resolve())
SCRATCH_DIR = REPO_ROOT / 'tests' / '_work' / 'instancing_scratch'
RULE_ON = instancing.instance_throwaways
RULE_ALWAYS_OFF = os.environ.get('FSS_INSTANCING_RULE_OFF') == '1'

failures = []


def check(condition, message):
    if condition:
        print('PASS:', message)
    else:
        print('FAIL:', message)
        failures.append(message)


# --- Scene ---

def bevelled_mesh(name='Shared'):
    """A bevelled cube with two UV maps and a color attribute: Weighted Normal changes its shading."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=2.0)
    bmesh.ops.bevel(bm, geom=list(bm.edges), offset=0.2, segments=2, affect='EDGES', profile=0.5)
    for face in bm.faces:
        face.smooth = True
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    for uv_name, scale in (('UVMap', 1.0), ('UV2', 0.5)):
        layer = mesh.uv_layers.new(name=uv_name)
        for index, loop in enumerate(mesh.loops):
            co = mesh.vertices[loop.vertex_index].co
            layer.uv[index].vector = (co.x * scale, (co.y + co.z) * scale)
    colors = mesh.color_attributes.new('Col', 'BYTE_COLOR', 'CORNER')
    for index, data in enumerate(colors.data):
        data.color = (index % 7 / 7, 0.5, 0.25, 1.0)
    mesh.update()
    return mesh


def user(mesh, name, index):
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = (4.0 * index, 1.0 * index, 0.0)
    obj.rotation_euler = (0.0, 0.0, 0.3 * index)
    return obj


def weighted(obj, mode='FACE_AREA', weight=50):
    modifier = obj.modifiers.new('WeightedNormal', 'WEIGHTED_NORMAL')
    modifier.mode = mode
    modifier.weight = weight
    return modifier


def auto_smooth(obj):
    """The modifier Blender 4.1+ adds on conversion is recognized by its node group's name."""
    group = bpy.data.node_groups.get('Auto Smooth')
    if group is None:
        group = bpy.data.node_groups.new('Auto Smooth', 'GeometryNodeTree')
        group.interface.new_socket('Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
        group.interface.new_socket('Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
        group_in = group.nodes.new('NodeGroupInput')
        group_out = group.nodes.new('NodeGroupOutput')
        group.links.new(group_in.outputs[0], group_out.inputs[0])
    modifier = obj.modifiers.new('Auto Smooth', 'NODES')
    modifier.node_group = group
    return modifier


def new_scene():
    # The multi-exporter leaves its settings on the hook class: a pointer into the scene read_homefile frees
    Export.msfs_export_settings = None
    bpy.ops.wm.read_homefile(use_empty=True)
    return bpy.context.scene


def identical():
    mesh = bevelled_mesh()
    for index in range(3):
        weighted(user(mesh, f'User{index}', index))


def no_modifier():
    mesh = bevelled_mesh()
    for index in range(3):
        user(mesh, f'User{index}', index)


def different_settings():
    mesh = bevelled_mesh()
    weighted(user(mesh, 'User0', 0))
    weighted(user(mesh, 'User1', 1))
    weighted(user(mesh, 'User2', 2), mode='CORNER_ANGLE')
    weighted(user(mesh, 'User3', 3), mode='CORNER_ANGLE')
    weighted(user(mesh, 'User4', 4), mode='FACE_AREA_WITH_ANGLE')


def linked_materials():
    mesh = bevelled_mesh()
    mesh.materials.append(bpy.data.materials.new('OnMesh'))
    first, second = bpy.data.materials.new('First'), bpy.data.materials.new('Second')
    for index, material in enumerate((first, first, second)):
        obj = user(mesh, f'User{index}', index)
        weighted(obj)
        obj.material_slots[0].link = 'OBJECT'
        obj.material_slots[0].material = material


def unused_slot_differs():
    """Faces use slot 0 only: a different material in the unused slot 1 does not change the result."""
    mesh = bevelled_mesh()
    mesh.materials.append(bpy.data.materials.new('Used'))
    mesh.materials.append(bpy.data.materials.new('OnMesh'))
    for index, material in enumerate((bpy.data.materials.new('A'), bpy.data.materials.new('B'))):
        obj = user(mesh, f'User{index}', index)
        weighted(obj)
        obj.material_slots[1].link = 'OBJECT'
        obj.material_slots[1].material = material


def another_modifier():
    mesh = bevelled_mesh()
    weighted(user(mesh, 'User0', 0))
    weighted(user(mesh, 'User1', 1))
    mirrored = user(mesh, 'User2', 2)
    mirrored.modifiers.new('Mirror', 'MIRROR')
    weighted(mirrored)


def shape_keys():
    mesh = bevelled_mesh()
    first = user(mesh, 'User0', 0)
    first.shape_key_add(name='Basis')
    moved = first.shape_key_add(name='Moved')
    moved.data[0].co.z += 0.1
    weighted(first)
    weighted(user(mesh, 'User1', 1))


def skinned():
    armature = bpy.data.armatures.new('Rig')
    rig = bpy.data.objects.new('Rig', armature)
    bpy.context.scene.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    bone = armature.edit_bones.new('Bone')
    bone.tail = (0.0, 0.0, 1.0)
    bpy.ops.object.mode_set(mode='OBJECT')
    mesh = bevelled_mesh()
    for index in range(2):
        obj = user(mesh, f'User{index}', index)
        group = obj.vertex_groups.new(name='Bone')
        group.add(range(len(mesh.vertices)), 1.0, 'REPLACE')
        obj.modifiers.new('Armature', 'ARMATURE').object = rig
        weighted(obj)


def auto_smooth_and_weighted():
    mesh = bevelled_mesh()
    for index in range(3):
        obj = user(mesh, f'User{index}', index)
        auto_smooth(obj)
        weighted(obj)


def mixed_without_modifier():
    """Two users without a modifier keep the source mesh; two with Weighted Normal evaluate differently and share."""
    mesh = bevelled_mesh()
    user(mesh, 'User0', 0)
    user(mesh, 'User1', 1)
    weighted(user(mesh, 'User2', 2))
    weighted(user(mesh, 'User3', 3))


def not_exported_user():
    """The Mirror user is hidden, so it is not exported and does not block the two exported users."""
    mesh = bevelled_mesh()
    weighted(user(mesh, 'User0', 0))
    weighted(user(mesh, 'User1', 1))
    hidden = user(mesh, 'Hidden', 2)
    hidden.modifiers.new('Mirror', 'MIRROR')
    hidden.hide_set(True)


def disabled_modifier():
    """A disabled Weighted Normal evaluates to the plain mesh: not identical to the enabled one."""
    mesh = bevelled_mesh()
    weighted(user(mesh, 'User0', 0))
    weighted(user(mesh, 'User1', 1))
    weighted(user(mesh, 'User2', 2)).show_viewport = False
    weighted(user(mesh, 'User3', 3)).show_viewport = False


# --- Export ---

def multi_export(folder, name='Model'):
    folder.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    scene.msfs_fss_export_target = 'MSFS2024'
    scene.msfs_background_export = False
    scene.msfs_export_mode = 'PRESETS'
    export_settings.init_setting_presets(scene)
    settings = export_settings.get_active_export_settings(scene)
    settings.enable_msfs_extension = True
    settings.export_force_sampling = False
    settings.export_animation_mode = 'ACTIONS'
    settings.export_merge_animation = 'NLA_TRACK'
    settings.export_frame_range = False
    settings.generate_texturelib = False
    settings.export_apply = True
    settings.export_keep_originals = False
    settings.export_texture_dir = ''
    collection = bpy.data.collections.new('Export')
    for obj in [obj for obj in scene.objects if obj.visible_get()]:
        collection.objects.link(obj)
    scene.collection.children.link(collection)
    preset = scene.msfs_multi_exporter_presets.add()
    preset.preset_name = name
    preset.folder_path = str(folder)
    preset.enabled = True
    layer = preset.layers.add()
    layer.collection = collection
    layer.enabled = True
    result = bpy.ops.msfs2024.multi_export_gltf(export_mode='PRESETS')
    assert 'FINISHED' in result, result
    return folder / f'{name}.gltf'


def plain_export(folder, target='MSFS2024', name='Model'):
    folder.mkdir(parents=True, exist_ok=True)
    bpy.context.scene.msfs_fss_export_target = target
    path = folder / f'{name}.gltf'
    result = bpy.ops.export_scene.gltf(filepath=str(path), export_format='GLTF_SEPARATE', use_visible=True,
                                       export_apply=True, export_force_sampling=False, export_vertex_color='ACTIVE')
    assert 'FINISHED' in result, result
    return path


def set_rule(on):
    instancing.instance_throwaways = RULE_ON if on and not RULE_ALWAYS_OFF else (lambda objects, settings: {})


def run(build, exporter, name, on):
    set_rule(on)
    new_scene()
    build()
    bpy.context.view_layer.update()
    return exporter(SCRATCH_DIR / name / ('on' if on else 'off'))


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def mesh_count(path):
    return len(read(path).get('meshes', []))


def users_of(path):
    """glTF mesh index -> node names."""
    result = {}
    for node in read(path).get('nodes', []):
        if 'mesh' in node:
            result.setdefault(node['mesh'], []).append(node['name'])
    return sorted(sorted(names) for names in result.values())


def compare_case(build, name, meshes_off, users_on, exporter=multi_export):
    """Export rule off and on: the same model, and the glTF meshes shared as expected."""
    off, on = run(build, exporter, name, False), run(build, exporter, name, True)
    differences = compare_files(str(off), str(on))
    check(not differences, f'{name}: the same model with the rule on and off ({len(differences)} differences)')
    for path, ref, new in differences[:10]:
        print('   ', path, ref, new)
    check(mesh_count(off) == meshes_off, f'{name}: {meshes_off} glTF meshes with the rule off, got {mesh_count(off)}')
    check(users_of(on) == sorted(sorted(u) for u in users_on),
          f'{name}: nodes per glTF mesh with the rule on {users_on}, got {users_of(on)}')
    return off, on


def main():
    if SCRATCH_DIR.exists():
        shutil.rmtree(SCRATCH_DIR)

    # The comparison can see a shading change: Weighted Normal against no modifier
    off = run(identical, multi_export, 'control_weighted', False)
    plain = run(no_modifier, multi_export, 'control_plain', False)
    check(any('elements' in path for path, _ref, _new in compare_files(str(plain), str(off))),
          'control: the comparison sees Weighted Normal against no modifier')

    three = ['User0', 'User1', 'User2']
    _off, on = compare_case(identical, 'identical', 3, [three])
    document = read(on)
    check(len(document['meshes']) == 1 and document['meshes'][0]['name'] == 'Shared',
          'identical: one glTF mesh under the source mesh name')
    check(mesh_count(run(identical, plain_export, 'plain_on', True)) == 1, 'identical: one mesh in a background plain export')

    compare_case(identical, 'plain_fs24', 3, [three], plain_export)
    fs20 = lambda folder: plain_export(folder, 'MSFS2020')  # noqa: E731
    compare_case(identical, 'plain_fs20', 3, [three], fs20)

    compare_case(different_settings, 'different_settings', 5, [['User0', 'User1'], ['User2', 'User3'], ['User4']])
    compare_case(linked_materials, 'linked_materials', 3, [['User0', 'User1'], ['User2']])
    compare_case(unused_slot_differs, 'unused_slot_differs', 2, [['User0', 'User1']])
    compare_case(another_modifier, 'another_modifier', 3, [['User0'], ['User1'], ['User2']])
    compare_case(shape_keys, 'shape_keys', 2, [['User0'], ['User1']])
    compare_case(skinned, 'skinned', 2, [['User0'], ['User1']])
    compare_case(auto_smooth_and_weighted, 'auto_smooth_and_weighted', 3, [three])
    compare_case(mixed_without_modifier, 'mixed_without_modifier', 3, [['User0', 'User1'], ['User2', 'User3']])
    compare_case(not_exported_user, 'not_exported_user', 2, [['User0', 'User1']])
    compare_case(disabled_modifier, 'disabled_modifier', 4, [['User0', 'User1'], ['User2', 'User3']])

    # Interactive-style: original objects, no throwaway copies, Blender not in background
    class Interactive:
        app = SimpleNamespace(background=False)

        def __getattr__(self, name):
            return getattr(bpy, name)

    baseline = run(identical, plain_export, 'interactive_baseline', False)
    set_rule(True)
    new_scene()
    identical()
    before = {o.name: (o.data, [(m.name, m.type) for m in o.modifiers]) for o in bpy.data.objects}
    meshes_before = len(bpy.data.meshes)
    io_scene_gltf2_msfs_fss.bpy = Interactive()
    try:
        interactive = plain_export(SCRATCH_DIR / 'interactive')
    finally:
        io_scene_gltf2_msfs_fss.bpy = bpy
    after = {o.name: (o.data, [(m.name, m.type) for m in o.modifiers]) for o in bpy.data.objects}
    check(before == after and len(bpy.data.meshes) == meshes_before,
          'interactive: the objects keep their modifiers and mesh, no mesh added')
    check(mesh_count(interactive) == 3, 'interactive: one glTF mesh per object, as before')
    differences = compare_files(str(baseline), str(interactive))
    check(not differences, f'interactive: exports as with the rule off ({len(differences)} differences)')

    # The artist's scene after a multi-exporter run
    set_rule(True)
    new_scene()
    different_settings()
    source = bpy.data.objects['User0'].data
    normals = [tuple(n.vector) for n in source.corner_normals]
    before = {o.name: (o.data, [(m.name, m.type, m.mode) for m in o.modifiers]) for o in bpy.data.objects}
    meshes_before = set(bpy.data.meshes)
    exported = multi_export(SCRATCH_DIR / 'artist_scene')
    after = {o.name: (o.data, [(m.name, m.type, m.mode) for m in o.modifiers])
             for o in bpy.data.objects if o.name in before}
    check(mesh_count(exported) == 3, 'multi-exporter: the rule acted on the duplicates')
    check(before == after, 'multi-exporter: source objects keep their modifiers and mesh')
    check(set(bpy.data.objects.keys()) == set(before), 'multi-exporter: no object left over')
    check(set(bpy.data.meshes) == meshes_before, 'multi-exporter: no mesh left over')
    check(all(math.isclose(a, b, abs_tol=1e-6) for x, y in zip(normals, [tuple(n.vector) for n in source.corner_normals])
              for a, b in zip(x, y)), 'multi-exporter: the source mesh keeps its normals')

    # The rule read directly on throwaway-marked objects: nothing changes when modifiers are not applied
    set_rule(True)
    new_scene()
    identical()
    names = RULE_ON(list(bpy.context.scene.objects), {'gltf_apply': False})
    check(not names and all(o.modifiers for o in bpy.data.objects), 'without Apply Modifiers the rule does nothing')

    if failures:
        print(f'FAILED {len(failures)}: {failures}')
        sys.exit(1)
    print('ALL INSTANCING TESTS PASSED')


try:
    main()
except Exception:
    import traceback

    traceback.print_exc()
    sys.exit(1)
