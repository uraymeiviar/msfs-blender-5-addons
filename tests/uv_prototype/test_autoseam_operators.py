"""
Unit and integration tests for FSS Auto Seam operators and panel (Package 3).

Verifies (Session 48):
1. Artist seams unchanged after Propose, Clear, and a second Propose.
2. A second Propose replaces only the automatic seams.
3. After Keep as Artist Seams, a Propose keeps those seams.
4. A shared mesh is processed once; skipped objects are reported with their reason.
5. Object state restored (mode, selection, active object, UV maps, scene).
6. Export check with both exporters into a scratch folder:
   no fss_auto_seam in the glTF, counts equal to the scene without it.
"""
import json
import os
import shutil
import sys
import time
from pathlib import Path
import bpy
import bmesh
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / 'fss_blender_tools') not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / 'fss_blender_tools'))

import fss_blender_tools
from fss_blender_tools import uv_autoseam

SCRATCH_DIR = REPO_ROOT / 'tests' / '_work' / 'export_scratch'
E2_BLEND = REPO_ROOT / 'tests' / '_work' / 'uv_autoseam' / 'package2d' / 'E2_COCKPIT2_copy.blend'


def create_cube(name, location=(0, 0, 0)):
    """Create a simple cube mesh object."""
    me = bpy.data.meshes.new(name + "_Mesh")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    obj.location = location
    bpy.context.scene.collection.objects.link(obj)
    return obj


def load_e2_test_objects():
    """Append 3 objects from E2 cockpit blend into current scene."""
    if not E2_BLEND.exists():
        print(f"Warning: {E2_BLEND} does not exist, using synthetic objects instead")
        return []
    obj_names = ['B_GS_AFCS_AP_BUTTON', 'AUDIO_L_VOLUME_KNOB', 'LEVER_FLAP_LOCK']
    with bpy.data.libraries.load(str(E2_BLEND), link=False) as (data_from, data_to):
        data_to.objects = [name for name in obj_names if name in data_from.objects]
    loaded = []
    for o in data_to.objects:
        if o:
            bpy.context.scene.collection.objects.link(o)
            loaded.append(o)
    return loaded


def test_gathering_and_skipped():
    """Verify skipped objects and reasons in gathering logic."""
    print("Test 1: Gathering and skipped objects...")
    # Clean scene
    bpy.ops.wm.read_homefile(use_empty=True)

    # 1. Normal mesh
    o_normal = create_cube("NormalMesh")

    # 2. Empty object
    o_empty = bpy.data.objects.new("EmptyObj", None)
    bpy.context.scene.collection.objects.link(o_empty)

    # 3. No faces mesh
    me_empty = bpy.data.meshes.new("NoFacesMesh")
    o_nofaces = bpy.data.objects.new("NoFacesObj", me_empty)
    bpy.context.scene.collection.objects.link(o_nofaces)

    # 4. 8 UV layers mesh
    o_8uv = create_cube("EightUVObj")
    for i in range(8):
        o_8uv.data.uv_layers.new(name=f"UVMap_{i}")

    # 5. Shared mesh
    o_shared1 = create_cube("Shared1")
    o_shared2 = bpy.data.objects.new("Shared2", o_shared1.data)
    bpy.context.scene.collection.objects.link(o_shared2)

    # Select all
    for o in (o_normal, o_empty, o_nofaces, o_8uv, o_shared1, o_shared2):
        o.select_set(True)

    unique_meshes, mesh_to_objs, shared_meshes, replaced_meshes, skipped = (
        uv_autoseam._gather_candidate_objects(bpy.context)
    )

    skip_dict = dict(skipped)
    assert "EmptyObj" in skip_dict, "EmptyObj should be skipped"
    assert skip_dict["EmptyObj"] == "not a mesh", f"Wrong reason for EmptyObj: {skip_dict['EmptyObj']}"

    assert "NoFacesObj" in skip_dict, "NoFacesObj should be skipped"
    assert skip_dict["NoFacesObj"] == "no faces", f"Wrong reason for NoFacesObj: {skip_dict['NoFacesObj']}"

    assert "EightUVObj" in skip_dict, "EightUVObj should be skipped"
    assert "no free UV map slot" in skip_dict["EightUVObj"], f"Wrong reason for EightUVObj: {skip_dict['EightUVObj']}"

    assert o_shared1.data in shared_meshes, "Shared mesh not identified in shared_meshes"
    assert len(unique_meshes) == 2, f"Expected 2 unique valid meshes (NormalMesh and Shared1), got {len(unique_meshes)}"
    print("  -> PASS: All skipped objects and shared meshes correctly identified.")


def test_shared_mesh_and_report():
    """Verify shared mesh is processed once and report text is created."""
    print("Test 2: Shared mesh processed once and report datablock...")
    bpy.ops.wm.read_homefile(use_empty=True)
    fss_blender_tools.register()

    o1 = create_cube("Obj1")
    o2 = bpy.data.objects.new("Obj2", o1.data)
    bpy.context.scene.collection.objects.link(o2)

    o1.select_set(True)
    o2.select_set(True)
    bpy.context.view_layer.objects.active = o1

    # Run Propose Seams synchronously
    res = bpy.ops.fss.uv_propose_seams()
    assert res == {'FINISHED'}, f"Propose failed: {res}"

    # Check report datablock
    assert uv_autoseam.REPORT_TEXT_NAME in bpy.data.texts, "Report text datablock not found"
    txt = bpy.data.texts[uv_autoseam.REPORT_TEXT_NAME]
    lines = [l.body.strip() for l in txt.lines if l.body.strip() and not l.body.strip().startswith('#')]

    assert len(lines) == 1, f"Expected exactly 1 line for shared mesh in report, got {len(lines)}"
    line = lines[0]
    assert f"Mesh '{o1.data.name}'" in line, f"Mesh name missing in report line: {line}"
    assert "Obj1" in line and "Obj2" in line, f"Objects using mesh missing in report line: {line}"
    assert "islands=" in line and "extra_verts=" in line and "time=" in line, f"Missing metrics in report: {line}"

    # Check that fss_auto_seam attribute was written on mesh
    assert uv_autoseam.AUTO_SEAM_ATTR in o1.data.attributes, "fss_auto_seam attribute not written"
    auto_cnt, artist_cnt = uv_autoseam.get_mesh_seam_counts(o1.data)
    assert auto_cnt > 0, "No auto seams were marked"
    assert artist_cnt == 0, f"Expected 0 artist seams, got {artist_cnt}"
    print(f"  -> PASS: Shared mesh processed once ({line})")


def test_artist_seams_preservation():
    """Verify artist seams are unchanged after Propose, Clear, and second Propose."""
    print("Test 3: Artist seams preservation across Propose, Clear, Propose...")
    bpy.ops.wm.read_homefile(use_empty=True)

    obj = create_cube("ArtistTestObj")
    me = obj.data

    # Author artist seams on edges 0 and 1
    me.edges[0].use_seam = True
    me.edges[1].use_seam = True
    me.edges[2].use_seam = False
    me.edges[3].use_seam = False

    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    # 1. Propose Seams
    bpy.ops.fss.uv_propose_seams()
    auto_cnt1, artist_cnt1 = uv_autoseam.get_mesh_seam_counts(me)
    assert artist_cnt1 == 2, f"Artist seams changed after propose: {artist_cnt1} != 2"
    assert me.edges[0].use_seam == True, "Edge 0 lost use_seam"
    assert me.edges[1].use_seam == True, "Edge 1 lost use_seam"
    auto_mask = np.zeros(len(me.edges), bool)
    me.attributes[uv_autoseam.AUTO_SEAM_ATTR].data.foreach_get('value', auto_mask)
    assert not auto_mask[0], "Edge 0 was incorrectly marked as auto seam"
    assert not auto_mask[1], "Edge 1 was incorrectly marked as auto seam"

    # 2. Clear Auto Seams
    bpy.ops.fss.uv_clear_auto_seams()
    auto_cnt2, artist_cnt2 = uv_autoseam.get_mesh_seam_counts(me)
    assert auto_cnt2 == 0, f"Auto seams not cleared: {auto_cnt2}"
    assert artist_cnt2 == 2, f"Artist seams altered by Clear Auto Seams: {artist_cnt2} != 2"
    assert me.edges[0].use_seam == True, "Edge 0 lost use_seam after clear"
    assert me.edges[1].use_seam == True, "Edge 1 lost use_seam after clear"
    assert uv_autoseam.AUTO_SEAM_ATTR not in me.attributes, "Attribute not removed after clear"

    # 3. Second Propose
    bpy.ops.fss.uv_propose_seams()
    auto_cnt3, artist_cnt3 = uv_autoseam.get_mesh_seam_counts(me)
    assert artist_cnt3 == 2, f"Artist seams changed after second propose: {artist_cnt3} != 2"
    assert me.edges[0].use_seam == True, "Edge 0 lost use_seam after second propose"
    assert me.edges[1].use_seam == True, "Edge 1 lost use_seam after second propose"
    me.attributes[uv_autoseam.AUTO_SEAM_ATTR].data.foreach_get('value', auto_mask)
    assert not auto_mask[0], "Edge 0 was marked as auto seam in second propose"
    assert not auto_mask[1], "Edge 1 was marked as auto seam in second propose"
    assert auto_cnt3 == auto_cnt1, f"Second propose auto seams mismatch: {auto_cnt3} vs {auto_cnt1}"
    print("  -> PASS: Artist seams completely preserved throughout.")


def test_second_propose_replaces_only_auto_seams():
    """Verify second propose replaces only automatic seams."""
    print("Test 4: Second propose replaces only auto seams...")
    bpy.ops.wm.read_homefile(use_empty=True)

    obj = create_cube("ReplaceTestObj")
    me = obj.data
    me.edges[0].use_seam = True

    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    bpy.ops.fss.uv_propose_seams()
    prop1_seams = [e.index for e in me.edges if e.use_seam]
    _, auto_mask1 = uv_autoseam.get_mesh_seam_masks(me)
    auto1_edges = [e.index for e in me.edges if auto_mask1[e.index]]

    # Run second propose
    bpy.ops.fss.uv_propose_seams()
    prop2_seams = [e.index for e in me.edges if e.use_seam]
    _, auto_mask2 = uv_autoseam.get_mesh_seam_masks(me)
    auto2_edges = [e.index for e in me.edges if auto_mask2[e.index]]

    assert me.edges[0].use_seam == True, "Artist seam edge 0 was modified"
    assert not auto_mask2[0], "Artist seam edge 0 received auto mark"
    assert auto1_edges == auto2_edges, "Second propose altered auto seams"
    assert prop1_seams == prop2_seams, "Total seams altered on identical mesh"
    print("  -> PASS: Second propose replaces only automatic seams.")


def test_keep_as_artist_seams():
    """Verify after Keep as Artist Seams, a Propose keeps those seams."""
    print("Test 5: Keep as Artist Seams...")
    bpy.ops.wm.read_homefile(use_empty=True)

    obj = create_cube("KeepTestObj")
    me = obj.data

    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    bpy.ops.fss.uv_propose_seams()
    auto1_cnt, _ = uv_autoseam.get_mesh_seam_counts(me)
    assert auto1_cnt > 0

    # Keep as Artist Seams
    res = bpy.ops.fss.uv_keep_as_artist_seams()
    assert res == {'FINISHED'}
    assert uv_autoseam.AUTO_SEAM_ATTR not in me.attributes
    auto2_cnt, artist2_cnt = uv_autoseam.get_mesh_seam_counts(me)
    assert auto2_cnt == 0
    assert artist2_cnt == auto1_cnt, f"Seams lost on keep: {artist2_cnt} != {auto1_cnt}"

    # Propose again: all previous seams must be preserved as artist seams!
    bpy.ops.fss.uv_propose_seams()
    auto3_cnt, artist3_cnt = uv_autoseam.get_mesh_seam_counts(me)
    assert artist3_cnt == artist2_cnt, f"Artist seams changed after re-proposing: {artist3_cnt} != {artist2_cnt}"
    print("  -> PASS: Kept seams remain preserved as artist seams in subsequent runs.")


def test_select_operators_in_edit_mode():
    """Verify Select Auto Seams and Select Artist Seams in Edit Mode."""
    print("Test 6: Select operators in Edit Mode...")
    bpy.ops.wm.read_homefile(use_empty=True)

    obj = create_cube("SelectTestObj")
    me = obj.data
    me.edges[0].use_seam = True  # Artist seam

    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    bpy.ops.fss.uv_propose_seams()
    _, auto_mask = uv_autoseam.get_mesh_seam_masks(me)
    auto_indices = {e.index for e in me.edges if auto_mask[e.index]}

    bpy.ops.object.mode_set(mode='EDIT')

    # 1. Select Auto Seams
    bpy.ops.fss.uv_select_auto_seams()
    bm = bmesh.from_edit_mesh(me)
    bm.edges.ensure_lookup_table()
    selected_edges = {e.index for e in bm.edges if e.select}
    assert selected_edges == auto_indices, f"Select Auto Seams mismatch: {selected_edges} vs {auto_indices}"

    # 2. Select Artist Seams
    bpy.ops.fss.uv_select_artist_seams()
    bm = bmesh.from_edit_mesh(me)
    bm.edges.ensure_lookup_table()
    selected_artist = {e.index for e in bm.edges if e.select}
    assert selected_artist == {0}, f"Select Artist Seams mismatch: {selected_artist} vs {{0}}"

    bpy.ops.object.mode_set(mode='OBJECT')
    print("  -> PASS: Select Auto and Select Artist work properly in Edit Mode.")


def test_state_restoration():
    """Verify object state restoration (mode, selection, active object, UV maps, scene)."""
    print("Test 7: Object state restoration...")
    bpy.ops.wm.read_homefile(use_empty=True)

    o1 = create_cube("ObjRest1", (0, 0, 0))
    o2 = create_cube("ObjRest2", (2, 0, 0))
    o3 = create_cube("ObjRest3", (4, 0, 0))

    # Add authored UV maps
    uv1 = o1.data.uv_layers.new(name="AuthoredUV1")
    uv2 = o1.data.uv_layers.new(name="AuthoredUV2")
    o1.data.uv_layers.active_index = 1

    o1.select_set(True)
    o2.select_set(False)
    o3.select_set(True)
    bpy.context.view_layer.objects.active = o3
    orig_scene = bpy.context.scene

    # Propose seams
    bpy.ops.fss.uv_propose_seams()

    assert bpy.context.mode == 'OBJECT', f"Mode not OBJECT: {bpy.context.mode}"
    assert bpy.context.view_layer.objects.active == o3, f"Active object not restored: {bpy.context.view_layer.objects.active}"
    assert o1.select_get() == True, "o1 selection not restored"
    assert o2.select_get() == False, "o2 selection not restored"
    assert o3.select_get() == True, "o3 selection not restored"
    assert bpy.context.scene == orig_scene, "Scene not restored"

    assert len(o1.data.uv_layers) == 2, f"Temporary UV layer leaked: {len(o1.data.uv_layers)}"
    assert o1.data.uv_layers.active_index == 1, f"Active UV index not restored: {o1.data.uv_layers.active_index}"
    print("  -> PASS: All scene and object state faithfully restored.")


def test_export_check():
    """Verify glTF export with both exporters: no fss_auto_seam, identical counts."""
    print("Test 8: glTF export check with both exporters into scratch folder...")
    if SCRATCH_DIR.exists():
        shutil.rmtree(SCRATCH_DIR)
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)

    # Enable MSFS exporter
    import addon_utils
    addon_utils.enable('io_scene_gltf2_msfs_fss')

    # Create test scene
    bpy.ops.wm.read_homefile(use_empty=True)
    scene = bpy.context.scene
    root = bpy.data.objects.new("ExportCube_LOD0", None)
    scene.collection.objects.link(root)

    obj = create_cube("ExportTestCube")
    obj.parent = root
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    # Propose seams (mesh now has fss_auto_seam attribute)
    bpy.ops.fss.uv_propose_seams()
    assert uv_autoseam.AUTO_SEAM_ATTR in obj.data.attributes

    # --- Case A: With fss_auto_seam ---
    dir_a = SCRATCH_DIR / 'with_auto_seam'
    dir_a.mkdir(parents=True, exist_ok=True)
    gltf_2020_a = dir_a / 'cube_2020.gltf'

    # 1. Plain glTF (2020)
    bpy.ops.export_scene.gltf(
        filepath=str(gltf_2020_a),
        export_format='GLTF_SEPARATE',
        use_visible=True,
        export_apply=True,
    )
    assert gltf_2020_a.exists(), "2020 glTF (with auto) was not written"

    # 2. MSFS 2024 multi-export
    dir_2024_a = dir_a / 'msfs2024'
    dir_2024_a.mkdir(parents=True, exist_ok=True)
    scene.msfs_export_mode = 'OBJECTS'
    scene.msfs_fss_export_target = 'MSFS2024'
    from io_scene_gltf2_msfs_fss.io.exp import export_settings, lod_groups
    export_settings.init_setting_presets(scene)
    export_settings.get_active_export_settings(scene).enable_msfs_extension = True
    scene.msfs_background_export = False
    lod_groups.reload_lod_groups(scene, reset=True)
    for group in lod_groups.get_scene_lod_groups(scene):
        group.folder_path = str(dir_2024_a)
        group.enabled = True
        group.generate_xml = False
        for lod in group.lods:
            lod.enabled = True
    bpy.ops.msfs2024.multi_export_gltf(export_mode='OBJECTS')
    written_2024_a = list(dir_2024_a.glob("*.gltf"))
    assert len(written_2024_a) > 0, "2024 glTF (with auto) was not written"
    gltf_2024_a = written_2024_a[0]

    # --- Case B: Without fss_auto_seam ---
    # Clear auto seam attribute
    bpy.ops.fss.uv_clear_auto_seams()
    assert uv_autoseam.AUTO_SEAM_ATTR not in obj.data.attributes

    dir_b = SCRATCH_DIR / 'without_auto_seam'
    dir_b.mkdir(parents=True, exist_ok=True)
    gltf_2020_b = dir_b / 'cube_2020.gltf'

    bpy.ops.export_scene.gltf(
        filepath=str(gltf_2020_b),
        export_format='GLTF_SEPARATE',
        use_visible=True,
        export_apply=True,
    )
    assert gltf_2020_b.exists(), "2020 glTF (without auto) was not written"

    dir_2024_b = dir_b / 'msfs2024'
    dir_2024_b.mkdir(parents=True, exist_ok=True)
    for group in lod_groups.get_scene_lod_groups(scene):
        group.folder_path = str(dir_2024_b)
        group.enabled = True
    bpy.ops.msfs2024.multi_export_gltf(export_mode='OBJECTS')
    written_2024_b = list(dir_2024_b.glob("*.gltf"))
    assert len(written_2024_b) > 0, "2024 glTF (without auto) was not written"
    gltf_2024_b = written_2024_b[0]

    # Inspect JSON contents
    with open(gltf_2020_a, 'r') as f:
        text_2020_a = f.read()
    with open(gltf_2020_b, 'r') as f:
        text_2020_b = f.read()
    with open(gltf_2024_a, 'r') as f:
        text_2024_a = f.read()
    with open(gltf_2024_b, 'r') as f:
        text_2024_b = f.read()

    # 1. Check no fss_auto_seam in glTF JSON
    assert "fss_auto_seam" not in text_2020_a, "fss_auto_seam leaked into 2020 glTF"
    assert "fss_auto_seam" not in text_2024_a, "fss_auto_seam leaked into 2024 glTF"

    # 2. Check counts equal between with and without fss_auto_seam
    data_2020_a = json.loads(text_2020_a)
    data_2020_b = json.loads(text_2020_b)
    assert len(data_2020_a.get('nodes', [])) == len(data_2020_b.get('nodes', [])), "2020 node count mismatch"
    assert len(data_2020_a.get('meshes', [])) == len(data_2020_b.get('meshes', [])), "2020 mesh count mismatch"
    assert len(data_2020_a.get('accessors', [])) == len(data_2020_b.get('accessors', [])), "2020 accessor count mismatch"

    data_2024_a = json.loads(text_2024_a)
    data_2024_b = json.loads(text_2024_b)
    assert len(data_2024_a.get('nodes', [])) == len(data_2024_b.get('nodes', [])), "2024 node count mismatch"
    assert len(data_2024_a.get('meshes', [])) == len(data_2024_b.get('meshes', [])), "2024 mesh count mismatch"
    assert len(data_2024_a.get('accessors', [])) == len(data_2024_b.get('accessors', [])), "2024 accessor count mismatch"

    print("  -> PASS: fss_auto_seam does not appear in glTF; vertex and node counts equal.")


def test_e2_objects_run():
    """Verify operators on 3 real E2 objects."""
    print("Test 9: Real E2 objects run (B_GS_AFCS_AP_BUTTON, AUDIO_L_VOLUME_KNOB, LEVER_FLAP_LOCK)...")
    bpy.ops.wm.read_homefile(use_empty=True)
    e2_objs = load_e2_test_objects()
    if not e2_objs:
        print("  -> SKIPPED (E2 objects not found)")
        return

    for o in e2_objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = e2_objs[0]

    # 1. Propose seams
    res = bpy.ops.fss.uv_propose_seams()
    assert res == {'FINISHED'}, f"Propose failed on E2 objects: {res}"

    # Verify all 3 objects received auto seams or report entries
    txt = bpy.data.texts[uv_autoseam.REPORT_TEXT_NAME]
    lines = [l.body.strip() for l in txt.lines if l.body.strip() and not l.body.strip().startswith('#')]
    assert len(lines) == len(e2_objs), f"Expected {len(e2_objs)} lines in report, got {len(lines)}"

    for o in e2_objs:
        auto_cnt, artist_cnt = uv_autoseam.get_mesh_seam_counts(o.data)
        print(f"    {o.name}: auto={auto_cnt}, artist={artist_cnt}")

    # 2. Clear auto seams
    res = bpy.ops.fss.uv_clear_auto_seams()
    assert res == {'FINISHED'}
    for o in e2_objs:
        auto_cnt, _ = uv_autoseam.get_mesh_seam_counts(o.data)
        assert auto_cnt == 0, f"Auto seams not cleared on {o.name}"

    # 3. Second propose
    res = bpy.ops.fss.uv_propose_seams()
    assert res == {'FINISHED'}

    print("  -> PASS: E2 objects processed and verified successfully.")


def main():
    print("=" * 70)
    print("RUNNING FSS AUTO SEAM OPERATOR & EXPORT TESTS")
    print("=" * 70)
    test_gathering_and_skipped()
    test_shared_mesh_and_report()
    test_artist_seams_preservation()
    test_second_propose_replaces_only_auto_seams()
    test_keep_as_artist_seams()
    test_select_operators_in_edit_mode()
    test_state_restoration()
    test_e2_objects_run()
    test_export_check()
    print("=" * 70)
    print("ALL TESTS PASSED SUCCESSFULLY.")
    print("=" * 70)


if __name__ == '__main__':
    main()
