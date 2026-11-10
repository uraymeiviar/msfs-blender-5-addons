"""Marker name clashes at export: a node from a marker (a merged mesh, or a name with a leading '@') whose exported name
or unique id another node already has gets the suffix _GROUP (_GROUP_2, ...), with a log line; the node without a
marker keeps its name. The E2 cockpit case: @MERGE_BTN holding the button cap BTN below a @NOMERGE_ node, which the
MSFS package compile refused with "nodes share the same 'BTN' unique_id".

To run:
G:\\e-jets-e2\\tools\\blender\\blender.exe -b --factory-startup --python tests/test_name_clash.py
"""

import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import addon_utils
import bmesh
import bpy

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
from fss_blender_tools import merge  # noqa: E402
from io_scene_gltf2_msfs_fss.io.exp import export_settings  # noqa: E402

for name in ADDONS:
    addon_utils.enable(name, default_set=True)
    assert Path(sys.modules[name].__file__).resolve().is_relative_to(REPO_ROOT), sys.modules[name].__file__

SCRATCH_DIR = REPO_ROOT / 'tests' / '_work' / 'name_clash_scratch'


def new_empty(name, parent=None):
    obj = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(obj)
    obj.parent = parent
    return obj


def new_cube(name, parent=None, x=0.0):
    mesh = bpy.data.meshes.new(name + "_Mesh")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=0.1)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.parent = parent
    obj.location.x = x
    return obj


def build_scene():
    bpy.ops.wm.read_homefile(use_empty=True)
    zone = new_empty("@ZONE_FWD")
    # The cockpit button: the group is named after the cap, which sits below a @NOMERGE_ node
    button = new_empty("@MERGE_BTN", zone)
    new_cube("BTN_BTN_BASE", button)
    new_cube("BTN", new_empty("@NOMERGE_BTN_BASE", button), x=0.2).keyframe_insert("location", frame=1)
    # A group named like an object elsewhere in the scene
    new_cube("DOOR_PART", new_empty("@MERGE_DOOR", zone), x=0.4)
    new_cube("DOOR", zone, x=0.6)
    # _GROUP is taken too: the next free number
    new_cube("PANEL_PART", new_empty("@MERGE_PANEL", zone), x=0.8)
    new_cube("PANEL", zone, x=1.0)
    new_cube("PANEL_GROUP", zone, x=1.2)
    # A @NOMERGE_ node named like a plain node, and a group whose name is free
    knob_group = new_empty("@MERGE_KNOBS", zone)
    new_cube("KNOB_PART", knob_group, x=1.4)
    new_cube("@NOMERGE_KNOB", knob_group, x=1.6)
    new_cube("KNOB", zone, x=1.8)
    new_cube("FREE_PART", new_empty("@MERGE_FREE", zone), x=2.0)
    bpy.context.view_layer.update()


def multi_export(folder, name='Model'):
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
    preset.preset_name = name
    preset.folder_path = str(folder)
    preset.enabled = True
    layer = preset.layers.add()
    layer.collection = collection
    layer.enabled = True
    result = bpy.ops.msfs2024.multi_export_gltf(export_mode='PRESETS')
    assert 'FINISHED' in result, result
    return json.loads((folder / f'{name}.gltf').read_text(encoding='utf-8'))


def plain_export(folder, target, name='Model'):
    folder.mkdir(parents=True, exist_ok=True)
    bpy.context.scene.msfs_fss_export_target = target
    path = folder / f'{name}.gltf'
    result = bpy.ops.export_scene.gltf(filepath=str(path), export_format='GLTF_SEPARATE', use_visible=True)
    assert 'FINISHED' in result, result
    return json.loads(path.read_text(encoding='utf-8'))


def unique_id(node):
    return node.get('extensions', {}).get('ASOBO_unique_id', {}).get('id')


def node_by_name(gltf):
    nodes = gltf['nodes']
    by_name = {}
    for node in nodes:
        assert node['name'] not in by_name, f"two nodes named {node['name']}: {sorted(n['name'] for n in nodes)}"
        by_name[node['name']] = node
    return by_name


def parent_of(gltf, name):
    nodes = gltf['nodes']
    index = next(i for i, node in enumerate(nodes) if node['name'] == name)
    return next((node['name'] for node in nodes if index in node.get('children', [])), None)


def check(gltf, label, with_ids):
    by_name = node_by_name(gltf)
    # The nodes without a marker keep their names; the marked ones yield
    for name in ('BTN', 'DOOR', 'PANEL', 'PANEL_GROUP', 'KNOB'):
        assert name in by_name, (label, name, sorted(by_name))
    expected = {'BTN_GROUP', 'DOOR_GROUP', 'PANEL_GROUP_2', 'KNOB_GROUP', 'KNOBS', 'FREE', 'BTN_BASE', 'ZONE_FWD'}
    assert expected <= set(by_name), (label, expected - set(by_name), sorted(by_name))
    # The renamed merged mesh is still the group's mesh: the button cap below it, the knob below its group
    assert parent_of(gltf, 'BTN_BASE') == 'BTN_GROUP' and parent_of(gltf, 'BTN') == 'BTN_BASE', label
    assert parent_of(gltf, 'KNOB_GROUP') == 'KNOBS', label
    assert 'mesh' in by_name['BTN_GROUP'] and 'mesh' in by_name['DOOR_GROUP'], label
    assert not any(name.startswith('@') or '.0' in name for name in by_name), (label, sorted(by_name))
    if with_ids:
        ids = [unique_id(node) for node in gltf['nodes'] if unique_id(node)]
        assert len(ids) == len(set(ids)), (label, sorted(ids))
        for name in ('BTN_GROUP', 'DOOR_GROUP', 'PANEL_GROUP_2', 'BTN', 'DOOR', 'PANEL'):
            assert unique_id(by_name[name]) == name, (label, name, unique_id(by_name[name]))


def test_resolve_unit():
    """The pass on its own: renames, unique ids, the log, and a clash between unmarked nodes reported, not renamed."""
    def node(name, uid=None):
        extensions = {'ASOBO_unique_id': SimpleNamespace(extension={'id': uid})} if uid else None
        return SimpleNamespace(name=name, extensions=extensions)

    plain, merged, nomerge = node('X', 'X'), node('X', 'X'), node('Y', '@NOMERGE_Y')
    plain_y, twin_a, twin_b = node('Y', 'Y'), node('Z', 'Z'), node('Z2', 'Z')
    nodes = [merged, plain, nomerge, plain_y, twin_a, twin_b]
    lines = []
    original = merge._log
    merge._log = lambda settings, message, warning, detail=False: lines.append((message, warning))
    try:
        renames = merge._resolve_name_clashes(nodes, {id(merged): '@MERGE_X', id(nomerge): '@NOMERGE_Y'}, {})
    finally:
        merge._log = original
    assert renames == [('@MERGE_X', 'X', 'X_GROUP'), ('@NOMERGE_Y', 'Y', 'Y_GROUP')], renames
    assert (plain.name, merged.name, nomerge.name) == ('X', 'X_GROUP', 'Y_GROUP')
    assert merged.extensions['ASOBO_unique_id'].extension['id'] == 'X_GROUP'
    assert nomerge.extensions['ASOBO_unique_id'].extension['id'] == '@NOMERGE_Y', "an id that was not the name stays"
    assert ("@MERGE_X: exported as X_GROUP, as another node is already named X", False) in lines, lines
    assert any('share the unique id Z' in message and warning for message, warning in lines), lines
    assert twin_a.name == 'Z' and twin_b.name == 'Z2', "nodes without a marker are never renamed"
    print("PASS: test_resolve_unit")


def test_exports():
    if SCRATCH_DIR.exists():
        shutil.rmtree(SCRATCH_DIR)
    SCRATCH_DIR.mkdir(parents=True)
    build_scene()
    check(multi_export(SCRATCH_DIR / 'multi'), 'MSFS 2024 multi-exporter', with_ids=True)
    for target in ('MSFS2024', 'MSFS2020'):
        build_scene()
        gltf = plain_export(SCRATCH_DIR / target.lower(), target)
        check(gltf, f'plain export {target}', with_ids=False)
        ids = [unique_id(node) for node in gltf['nodes'] if unique_id(node)]
        assert len(ids) == len(set(ids)), (target, sorted(ids))
        print(f"  plain export {target}: {len(gltf['nodes'])} nodes, {len(ids)} unique ids")
    print("PASS: test_exports (multi-exporter and plain exports for both simulators)")


def main():
    test_resolve_unit()
    test_exports()
    print("ALL NAME CLASH TESTS PASSED")


if __name__ == '__main__':
    main()
