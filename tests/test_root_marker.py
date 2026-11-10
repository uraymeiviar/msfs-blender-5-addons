"""@ROOT_ marker: a node named @ROOT_<name> is not written; its children go to the glTF root and keep their world
transforms, their own children stay below them. Asobo wants collision meshes at the root, the empty lets the artist move
them together in Blender.

To run:
G:\\e-jets-e2\\tools\\blender\\blender.exe -b --factory-startup --python tests/test_root_marker.py
"""

import json
import math
import shutil
import sys
from pathlib import Path

import addon_utils
import bmesh
import bpy
from mathutils import Matrix

REPO_ROOT = Path(__file__).resolve().parents[1]
ADDONS = ('io_scene_gltf2_msfs_fss', 'fss_blender_tools')

# The portable Blender enables its deployed addons_core copies at startup: disable and purge them, then import the
# repository modules first, so addon_utils enables those (the exporter hooks of enabled add-ons run at export)
for name in reversed(ADDONS):
    if addon_utils.check(name)[1]:
        addon_utils.disable(name)
    for mod in list(sys.modules.keys()):
        if mod == name or mod.startswith(name + '.'):
            del sys.modules[mod]
repo_root_str = str(REPO_ROOT)
while repo_root_str in sys.path:
    sys.path.remove(repo_root_str)
sys.path.insert(0, repo_root_str)

import io_scene_gltf2_msfs_fss  # noqa: E402,F401
import fss_blender_tools  # noqa: E402,F401
from fss_blender_tools import merge, name_check  # noqa: E402
from io_scene_gltf2_msfs_fss.io.exp import export_settings  # noqa: E402

for name in ADDONS:
    addon_utils.enable(name, default_set=True)
    assert Path(sys.modules[name].__file__).resolve().is_relative_to(REPO_ROOT), sys.modules[name].__file__

SCRATCH_DIR = REPO_ROOT / 'tests' / '_work' / 'root_marker_scratch'
LIFTED = ('COL_A', 'COL_B', 'COL_C')


def new_empty(name, parent=None):
    obj = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(obj)
    obj.parent = parent
    return obj


def new_cube(name, parent=None, location=(0.0, 0.0, 0.0)):
    mesh = bpy.data.meshes.new(name + "_Mesh")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=0.1)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.parent = parent
    obj.location = location
    return obj


def build_scene(animate=False):
    """A moved zone holding a moved, rotated and scaled @ROOT_COLLISION (two meshes, one with a child), a plain panel,
    and a merge group holding a @ROOT_INNER."""
    bpy.ops.wm.read_homefile(use_empty=True)
    zone = new_empty("@ZONE_FWD")
    zone.location = (1.0, 2.0, 0.5)
    pivot = new_empty("@ROOT_COLLISION", zone)
    pivot.location = (0.3, -0.4, 0.2)
    pivot.rotation_euler = (0.0, math.radians(20.0), math.radians(90.0))
    pivot.scale = (1.5, 1.5, 1.5)
    new_cube("COL_A", pivot, (0.2, 0.0, 0.0))
    col_b = new_cube("COL_B", pivot, (0.0, 0.3, 0.1))
    col_b.rotation_euler.x = math.radians(30.0)
    new_cube("COL_B_PART", col_b, (0.05, 0.0, 0.1))
    new_cube("PANEL_KEEP", zone, (0.5, 0.0, 0.0))
    group = new_empty("@MERGE_PANEL", zone)
    new_cube("MEMBER", group)
    new_cube("COL_C", new_empty("@ROOT_INNER", group), (0.0, 0.0, 0.4))
    if animate:
        pivot.keyframe_insert("location", frame=1)
        pivot.location.z += 1.0
        pivot.keyframe_insert("location", frame=10)
    bpy.context.scene.frame_set(1)
    bpy.context.view_layer.update()
    # glTF node name -> (world matrix, parent's world matrix) before the export; a background merge changes the scene
    return {obj.name: obj.matrix_world.copy() for obj in bpy.data.objects}


def plain_export(folder, target):
    folder.mkdir(parents=True, exist_ok=True)
    bpy.context.scene.msfs_fss_export_target = target
    path = folder / 'Model.gltf'
    result = bpy.ops.export_scene.gltf(filepath=str(path), export_format='GLTF_SEPARATE', use_visible=True)
    assert 'FINISHED' in result, result
    return json.loads(path.read_text(encoding='utf-8'))


def multi_export(folder):
    folder.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    scene.msfs_fss_export_target = 'MSFS2024'
    scene.msfs_background_export = False
    scene.msfs_export_mode = 'PRESETS'
    export_settings.init_setting_presets(scene)
    settings = export_settings.get_active_export_settings(scene)
    settings.enable_msfs_extension = True
    settings.export_animation_mode = 'ACTIONS'
    settings.generate_texturelib = False
    settings.export_texture_dir = ''
    collection = bpy.data.collections.new('Export')
    for obj in [obj for obj in scene.objects if obj.visible_get()]:
        collection.objects.link(obj)
    scene.collection.children.link(collection)
    preset = scene.msfs_multi_exporter_presets.add()
    preset.preset_name = 'Model'
    preset.folder_path = str(folder)
    preset.enabled = True
    layer = preset.layers.add()
    layer.collection = collection
    layer.enabled = True
    result = bpy.ops.msfs2024.multi_export_gltf(export_mode='PRESETS')
    assert 'FINISHED' in result, result
    return json.loads((folder / 'Model.gltf').read_text(encoding='utf-8'))


def gltf_to_blender(node):
    """A glTF node's local matrix in Blender axes (glTF is Y up: Blender (x, y, z) is glTF (x, z, -y))."""
    t = node.get('translation', [0.0, 0.0, 0.0])
    x, y, z, w = node.get('rotation', [0.0, 0.0, 0.0, 1.0])
    s = node.get('scale', [1.0, 1.0, 1.0])
    from mathutils import Quaternion, Vector
    location = Vector((t[0], -t[2], t[1]))
    rotation = Quaternion((w, x, -z, y))
    scale = Vector((s[0], s[2], s[1]))
    return Matrix.LocRotScale(location, rotation, scale)


def world_matrices(gltf):
    """glTF node name -> world matrix in Blender axes; and node name -> parent name (None at the root)."""
    nodes = gltf['nodes']
    parent = {}
    for index, node in enumerate(nodes):
        for child in node.get('children', []):
            parent[child] = index
    worlds = {}

    def world(index):
        local = gltf_to_blender(nodes[index])
        return world(parent[index]) @ local if index in parent else local

    for index, node in enumerate(nodes):
        worlds[node['name']] = world(index)
    parents = {node['name']: (nodes[parent[i]]['name'] if i in parent else None) for i, node in enumerate(nodes)}
    return worlds, parents


def same(a, b, tolerance=1e-4):
    return all(abs(a[i][j] - b[i][j]) < tolerance for i in range(4) for j in range(4))


def check(gltf, worlds_before, label):
    names = [node['name'] for node in gltf['nodes']]
    assert not any('ROOT_' in name for name in names), (label, names)
    worlds, parents = world_matrices(gltf)
    roots = {gltf['nodes'][i]['name'] for i in gltf['scenes'][gltf.get('scene', 0)]['nodes']}
    for name in LIFTED:
        assert name in roots, (label, name, sorted(roots))
        assert same(worlds[name], worlds_before[name]), (label, name, worlds[name], worlds_before[name])
    assert parents['COL_B_PART'] == 'COL_B', (label, parents['COL_B_PART'])
    assert same(worlds['COL_B_PART'], worlds_before['COL_B_PART']), label
    # The rest keeps its structure: the zone and the merged panel, without the @ROOT_ subtree in the merged mesh
    assert parents['PANEL_KEEP'] == 'ZONE_FWD' and parents['PANEL'] == 'ZONE_FWD', (label, parents)
    assert 'MEMBER' not in names, (label, names)
    panel = next(node for node in gltf['nodes'] if node['name'] == 'PANEL')
    prims = gltf['meshes'][panel['mesh']]['primitives']
    assert sum(gltf['accessors'][p['indices']]['count'] // 3 for p in prims) == 12, label
    print(f"  {label}: {', '.join(LIFTED)} at the root in place, COL_B_PART below COL_B, no @ROOT_ node")


def test_names():
    findings = name_check.check_names(['@ROOT_COLLISION', 'ROOT_COLLISION', '@ZONE_X', 'ZONE_X'],
                                      {'@ROOT_COLLISION', 'ROOT_COLLISION', '@ZONE_X', 'ZONE_X'})
    assert '@ROOT_COLLISION' not in findings and 'ROOT_COLLISION' not in findings, findings
    assert 'CLASH' in findings['@ZONE_X'][0] and 'CLASH' in findings['ZONE_X'][0], findings
    pivot = bpy.data.objects.new('@ROOT_X', None)
    assert merge.skip_reason(pivot, set()) == '@ROOT_ node'
    print("PASS: test_names (a @ROOT_ name is accepted and never clashes; it stays out of a merge group)")


def test_exports():
    if SCRATCH_DIR.exists():
        shutil.rmtree(SCRATCH_DIR)
    SCRATCH_DIR.mkdir(parents=True)
    for target in ('MSFS2024', 'MSFS2020'):
        before = build_scene()
        check(plain_export(SCRATCH_DIR / target.lower(), target), before, f'plain export {target}')
    before = build_scene()
    check(multi_export(SCRATCH_DIR / 'multi'), before, 'MSFS 2024 multi-exporter')
    print("PASS: test_exports (plain exports for both simulators and the multi-exporter)")


def test_animation_warning():
    lines = []
    original = merge._log

    def record(export_settings, message, warning, detail=False):
        lines.append((message, warning))
        original(export_settings, message, warning, detail)

    merge._log = record
    try:
        build_scene()
        plain_export(SCRATCH_DIR / 'static', 'MSFS2024')
        assert not any(warning and 'ROOT_' in message for message, warning in lines), lines
        assert ('@ROOT_COLLISION: 2 child node(s) moved to the glTF root', False) in lines, lines
        lines.clear()
        build_scene(animate=True)
        plain_export(SCRATCH_DIR / 'animated', 'MSFS2024')
        assert ('@ROOT_COLLISION: @ROOT_COLLISION is animated or follows a bone; its children at the glTF root do not '
                'follow that motion', True) in lines, lines
        assert not any(warning and message.startswith('@ROOT_INNER') for message, warning in lines), lines
    finally:
        merge._log = original
    print("PASS: test_animation_warning (an animated @ROOT_ warns, a static one does not)")


def main():
    test_names()
    test_exports()
    test_animation_warning()
    print("ALL ROOT MARKER TESTS PASSED")


if __name__ == '__main__':
    main()
