"""No Export (UV journal decision 130): a tag mark in the Tags panel whose objects, with everything parented below
them, no export writes and the merge leaves out, as the probe lights of Visibility Scoring need.

To run:
G:\\e-jets-e2\\tools\\blender\\blender.exe -b --factory-startup --python tests/test_no_export.py
"""

import json
import shutil
import sys
from pathlib import Path

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
from fss_blender_tools import tags  # noqa: E402

for name in ADDONS:
    addon_utils.enable(name, default_set=True)
    assert Path(sys.modules[name].__file__).resolve().is_relative_to(REPO_ROOT), sys.modules[name].__file__

SCRATCH_DIR = REPO_ROOT / 'tests' / '_work' / 'no_export_scratch'


def new_empty(name, parent=None):
    obj = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(obj)
    obj.parent = parent
    return obj


def new_cube(name, parent=None, size=0.1):
    mesh = bpy.data.meshes.new(name + "_Mesh")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=size)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.parent = parent
    return obj


def new_light(name, parent=None):
    obj = bpy.data.objects.new(name, bpy.data.lights.new(name, 'SPOT'))
    bpy.context.scene.collection.objects.link(obj)
    obj.parent = parent
    return obj


def build_scene():
    """A panel to keep, the probe lights under a tagged empty (a light and a helper mesh below it), and a merge group
    with a tagged member."""
    bpy.ops.wm.read_homefile(use_empty=True)
    o = {'keep': new_cube("PANEL_KEEP")}
    o['probes'] = new_empty("VISIBILITY_PROBE_LIGHTS")
    o['light'] = new_light("PROBE_PILOT", o['probes'])
    o['helper'] = new_cube("PROBE_HELPER", o['light'])
    o['group'] = new_empty("@MERGE_PANEL")
    o['member'] = new_cube("MEMBER", o['group'])
    o['stray'] = new_cube("STRAY_PROBE_MESH", o['group'], size=0.05)
    tags.set_tags(o['probes'], ['PROBE'])
    tags.set_tags(o['stray'], ['PROBE'])
    bpy.context.view_layer.update()
    return o


def export(name):
    path = SCRATCH_DIR / f"{name}.gltf"
    bpy.ops.export_scene.gltf(filepath=str(path), export_format='GLTF_SEPARATE', use_visible=True, export_lights=True)
    return json.loads(path.read_text(encoding='utf-8'))


def triangles(gltf, node_name):
    node = next(n for n in gltf['nodes'] if n['name'] == node_name)
    prims = gltf['meshes'][node['mesh']]['primitives']
    return sum(gltf['accessors'][p['indices']]['count'] // 3 for p in prims)


def test_mark_and_rule():
    o = build_scene()
    scene = bpy.context.scene
    assert not any(tags.is_no_export(obj, scene) for obj in o.values()), "no mark: everything exports"
    assert bpy.ops.fss.tag_toggle_no_export(tag='PROBE') == {'FINISHED'}
    assert tags.get_mark_tags(scene, tags.NO_EXPORT_PROP) == ['PROBE']
    assert {name for name, obj in o.items() if tags.is_no_export(obj, scene)} == {'probes', 'light', 'helper', 'stray'}
    # A renamed tag keeps its mark; toggling again removes it
    assert bpy.ops.fss.tag_rename(tag='PROBE', new_name='PROBES') == {'FINISHED'}
    assert tags.get_mark_tags(scene, tags.NO_EXPORT_PROP) == ['PROBES'] and tags.is_no_export(o['helper'], scene)
    bpy.ops.fss.tag_toggle_no_export(tag='PROBES')
    assert tags.get_mark_tags(scene, tags.NO_EXPORT_PROP) == [] and not tags.is_no_export(o['helper'], scene)
    print("PASS: test_mark_and_rule (the tag's objects and everything below them; rename keeps the mark)")


def test_export():
    if SCRATCH_DIR.exists():
        shutil.rmtree(SCRATCH_DIR)
    SCRATCH_DIR.mkdir(parents=True)

    build_scene()
    before = export("without_mark")
    names = {node['name'] for node in before['nodes']}
    assert {'VISIBILITY_PROBE_LIGHTS', 'PROBE_PILOT', 'PROBE_HELPER', 'PANEL_KEEP'} <= names, names
    assert 'KHR_lights_punctual' in before.get('extensionsUsed', []), before.get('extensionsUsed')
    merged_before = triangles(before, 'PANEL')

    build_scene()
    bpy.ops.fss.tag_toggle_no_export(tag='PROBE')
    after = export("with_mark")
    names = {node['name'] for node in after['nodes']}
    assert not names & {'VISIBILITY_PROBE_LIGHTS', 'PROBE_PILOT', 'PROBE_HELPER', 'STRAY_PROBE_MESH'}, names
    assert 'PANEL_KEEP' in names and 'PANEL' in names, names
    assert 'KHR_lights_punctual' not in after.get('extensionsUsed', []), after.get('extensionsUsed')
    merged_after = triangles(after, 'PANEL')
    # The merged mesh holds the member only: the tagged mesh in the group is neither merged nor written
    assert merged_before == 2 * merged_after == 24, (merged_before, merged_after)

    # A background export merges the originals in place (renamed .fssmerge, the deploy quits without saving); the
    # tagged objects are left alone, the tagged member included
    missing = {'VISIBILITY_PROBE_LIGHTS', 'PROBE_PILOT', 'PROBE_HELPER', 'STRAY_PROBE_MESH'} - set(bpy.data.objects.keys())
    assert not missing, (missing, sorted(bpy.data.objects.keys()))
    print(f"PASS: test_export (lights and helpers gone with the mark, merged mesh {merged_before} -> {merged_after} triangles)")


def main():
    test_mark_and_rule()
    test_export()
    print("ALL NO EXPORT TESTS PASSED")


if __name__ == '__main__':
    main()
