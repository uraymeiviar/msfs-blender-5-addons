"""
Unit and integration tests for FSS Auto Seam operators and panel (Package 3 & 4).

To run:
G:\e-jets-e2\tools\blender\blender.exe -b --factory-startup --python tests/uv_prototype/test_autoseam_operators.py

Verifies:
1. Artist seams unchanged after Propose, Clear, and a second Propose.
2. A second Propose replaces only the automatic seams.
3. After Keep as Artist Seams, a Propose keeps those seams.
4. A shared mesh is processed once; skipped objects are reported with their reason.
5. Object state restored (mode, selection, active object, UV maps, scene).
6. Export check with both exporters into a scratch folder:
   no fss_auto_seam in the glTF, counts equal to the scene without it.
7. UV maps and coordinates unchanged after Propose.
8. Decal and special material skip (decision 55).
9. Readable report formatting, summary at top, and attention counts.
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

# If an addons_core copy was loaded during Blender startup, unregister and purge it
if 'fss_blender_tools' in sys.modules:
    try:
        sys.modules['fss_blender_tools'].unregister()
    except Exception:
        pass
    for mod in list(sys.modules.keys()):
        if mod == 'fss_blender_tools' or mod.startswith('fss_blender_tools.'):
            del sys.modules[mod]

REPO_ROOT = Path(__file__).resolve().parents[2]
repo_root_str = str(REPO_ROOT)
while repo_root_str in sys.path:
    sys.path.remove(repo_root_str)
sys.path.insert(0, repo_root_str)

import fss_blender_tools
from fss_blender_tools import uv_autoseam

# Register repository add-on once at startup
fss_blender_tools.register()

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

    mesh_lines = [l for l in lines if l.startswith("Mesh '")]
    assert len(mesh_lines) == 1, f"Expected exactly 1 mesh block in report, got {len(mesh_lines)}"
    line = mesh_lines[0]
    assert f"Mesh '{o1.data.name}'" in line, f"Mesh name missing in report line: {line}"
    assert "Obj1" in line and "Obj2" in line, f"Objects using mesh missing in report line: {line}"

    stat_lines = [l for l in lines if "islands=" in l]
    assert len(stat_lines) == 1, f"Expected 1 stat line, got {len(stat_lines)}"
    assert "extra_verts=" in stat_lines[0] and "time=" in stat_lines[0], f"Missing metrics in report: {stat_lines[0]}"

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


def test_keep_and_clear_from_edit_mode():
    """Keep as Artist Seams and Clear Auto Seams work when clicked in Edit Mode, and the change survives leaving it."""
    print("Test 5b: Keep and Clear from Edit Mode...")
    bpy.ops.wm.read_homefile(use_empty=True)
    obj = create_cube("EditModeObj")
    me = obj.data
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.fss.uv_propose_seams()
    auto_cnt, artist_cnt = uv_autoseam.get_mesh_seam_counts(me)
    assert auto_cnt > 0

    bpy.ops.object.mode_set(mode='EDIT')
    assert bpy.ops.fss.uv_keep_as_artist_seams() == {'FINISHED'}
    assert bpy.context.mode == 'EDIT_MESH', "the button returns to Edit Mode"
    bpy.ops.object.mode_set(mode='OBJECT')
    assert uv_autoseam.AUTO_SEAM_ATTR not in me.attributes, "leaving Edit Mode must not bring the mark back"
    kept_auto, kept_artist = uv_autoseam.get_mesh_seam_counts(me)
    assert (kept_auto, kept_artist) == (0, artist_cnt + auto_cnt), (kept_auto, kept_artist)

    bpy.ops.fss.uv_propose_seams()  # new auto seams on top of the kept ones
    bpy.ops.object.mode_set(mode='EDIT')
    assert bpy.ops.fss.uv_clear_auto_seams() == {'FINISHED'}
    assert bpy.context.mode == 'EDIT_MESH'
    bpy.ops.object.mode_set(mode='OBJECT')
    cleared_auto, cleared_artist = uv_autoseam.get_mesh_seam_counts(me)
    assert cleared_auto == 0 and cleared_artist == kept_artist, (cleared_auto, cleared_artist)
    print("  -> PASS: Keep and Clear work from Edit Mode and the change survives leaving it.")

    # Clear Current removes the current (accepted) seams and leaves a new proposal alone
    bpy.ops.fss.uv_propose_seams()
    proposed, current = uv_autoseam.get_mesh_seam_counts(me)
    assert current > 0
    assert bpy.ops.fss.uv_clear_current_seams('EXEC_DEFAULT') == {'FINISHED'}
    after_proposed, after_current = uv_autoseam.get_mesh_seam_counts(me)
    assert after_current == 0 and after_proposed == proposed, (after_proposed, after_current)
    print("  -> PASS: Clear Current removes the current seams and keeps the proposed ones.")


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
    scene.msfs_fss_export_target = 'MSFS2020'
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

    scene.msfs_fss_export_target = 'MSFS2020'
    bpy.ops.export_scene.gltf(
        filepath=str(gltf_2020_b),
        export_format='GLTF_SEPARATE',
        use_visible=True,
        export_apply=True,
    )
    assert gltf_2020_b.exists(), "2020 glTF (without auto) was not written"

    dir_2024_b = dir_b / 'msfs2024'
    dir_2024_b.mkdir(parents=True, exist_ok=True)
    scene.msfs_export_mode = 'OBJECTS'
    scene.msfs_fss_export_target = 'MSFS2024'
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

    # 2. Check counts equal between with and without fss_auto_seam (Session 48 & Session 50 Finding 4)
    def get_mesh_counts(gltf_data):
        verts = 0
        tris = 0
        accessors = gltf_data.get('accessors', [])
        for m in gltf_data.get('meshes', []):
            for prim in m.get('primitives', []):
                pos_idx = prim.get('attributes', {}).get('POSITION')
                if pos_idx is not None and pos_idx < len(accessors):
                    verts += accessors[pos_idx].get('count', 0)
                ind_idx = prim.get('indices')
                if ind_idx is not None and ind_idx < len(accessors):
                    tris += accessors[ind_idx].get('count', 0) // 3
        return verts, tris

    data_2020_a = json.loads(text_2020_a)
    data_2020_b = json.loads(text_2020_b)
    verts_20a, tris_20a = get_mesh_counts(data_2020_a)
    verts_20b, tris_20b = get_mesh_counts(data_2020_b)
    assert verts_20a == verts_20b, f"2020 vertex count mismatch: {verts_20a} vs {verts_20b}"
    assert tris_20a == tris_20b, f"2020 triangle count mismatch: {tris_20a} vs {tris_20b}"
    assert len(data_2020_a.get('nodes', [])) == len(data_2020_b.get('nodes', [])), "2020 node count mismatch"
    assert len(data_2020_a.get('meshes', [])) == len(data_2020_b.get('meshes', [])), "2020 mesh count mismatch"

    data_2024_a = json.loads(text_2024_a)
    data_2024_b = json.loads(text_2024_b)
    verts_24a, tris_24a = get_mesh_counts(data_2024_a)
    verts_24b, tris_24b = get_mesh_counts(data_2024_b)
    assert verts_24a == verts_24b, f"2024 vertex count mismatch: {verts_24a} vs {verts_24b}"
    assert tris_24a == tris_24b, f"2024 triangle count mismatch: {tris_24a} vs {tris_24b}"
    assert len(data_2024_a.get('nodes', [])) == len(data_2024_b.get('nodes', [])), "2024 node count mismatch"
    assert len(data_2024_a.get('meshes', [])) == len(data_2024_b.get('meshes', [])), "2024 mesh count mismatch"

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
    mesh_lines = [l for l in lines if l.startswith("Mesh '")]
    assert len(mesh_lines) == len(e2_objs), f"Expected {len(e2_objs)} mesh blocks in report, got {len(mesh_lines)}"

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


def test_uv_maps_unchanged_after_propose():
    """Verify that Propose leaves every UV map, active UV map, and UV coordinates unchanged."""
    print("Test 10: UV maps and coordinates unchanged after propose...")
    bpy.ops.wm.read_homefile(use_empty=True)

    obj = create_cube("UVUnchangedTestObj")
    me = obj.data

    # Add 2 distinct UV maps with known coordinates
    uv_layer1 = me.uv_layers.new(name="CustomUV1")
    uv_layer2 = me.uv_layers.new(name="CustomUV2")
    me.uv_layers.active_index = 1  # CustomUV2 active

    # Assign custom identifiable UV coords
    for i, loop in enumerate(me.loops):
        uv_layer1.data[i].uv = (float(i) * 0.05, float(i) * 0.03)
        uv_layer2.data[i].uv = (1.0 - float(i) * 0.02, 0.5 + float(i) * 0.01)

    # Snapshot coordinates before propose
    coords1_before = [tuple(d.uv) for d in uv_layer1.data]
    coords2_before = [tuple(d.uv) for d in uv_layer2.data]
    uv_names_before = [l.name for l in me.uv_layers]
    active_index_before = me.uv_layers.active_index
    active_name_before = me.uv_layers.active.name

    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    # Run Propose Seams
    res = bpy.ops.fss.uv_propose_seams()
    assert res == {'FINISHED'}, f"Propose failed: {res}"

    # Verify counts and names
    assert [l.name for l in me.uv_layers] == uv_names_before, "UV map names or count changed"
    assert me.uv_layers.active_index == active_index_before, "Active UV layer index changed"
    assert me.uv_layers.active.name == active_name_before, "Active UV layer changed"

    # Verify coordinates bit-for-bit (max diff 0.0)
    coords1_after = [tuple(d.uv) for d in uv_layer1.data]
    coords2_after = [tuple(d.uv) for d in uv_layer2.data]
    diff1 = max(abs(a[0] - b[0]) + abs(a[1] - b[1]) for a, b in zip(coords1_before, coords1_after))
    diff2 = max(abs(a[0] - b[0]) + abs(a[1] - b[1]) for a, b in zip(coords2_before, coords2_after))
    assert diff1 == 0.0, f"CustomUV1 coordinates changed: max diff {diff1}"
    assert diff2 == 0.0, f"CustomUV2 coordinates changed: max diff {diff2}"

    # Also verify after Edit Mode round trip (as maintainer did)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.object.mode_set(mode='OBJECT')
    coords1_edit = [tuple(d.uv) for d in me.uv_layers['CustomUV1'].data]
    coords2_edit = [tuple(d.uv) for d in me.uv_layers['CustomUV2'].data]
    diff_edit1 = max(abs(a[0] - b[0]) + abs(a[1] - b[1]) for a, b in zip(coords1_before, coords1_edit))
    diff_edit2 = max(abs(a[0] - b[0]) + abs(a[1] - b[1]) for a, b in zip(coords2_before, coords2_edit))
    assert diff_edit1 == 0.0, f"CustomUV1 coordinates changed after Edit mode round trip: max diff {diff_edit1}"
    assert diff_edit2 == 0.0, f"CustomUV2 coordinates changed after Edit mode round trip: max diff {diff_edit2}"

    print("  -> PASS: All UV maps, active UV map, and UV coordinates completely unchanged.")


def test_decal_skip():
    """Verify objects with only decal, glass, invis, or occluder materials are skipped."""
    print("Test 11: Decal and special material skip (decision 55)...")
    bpy.ops.wm.read_homefile(use_empty=True)

    # 1. Name class tests (DECAL, DECAL_EM, DECAL_FROST, DECAL_BLEND, GLASS, WNDSHIELD, INVIS, OCCLUDER)
    # decision 23: <SCENE>_<ZONE>_<CLASS>, the class is the last part (Blender's .001 suffix allowed)
    skip_names = [
        "E2_TEST_DECAL",
        "EXT_LIGHT_DECAL_EM",
        "WND_DECAL_FROST.001",
        "PANEL_DECAL_BLEND",
        "CABIN_GLASS",
        "PILOT_WNDSHIELD",
        "COLLIDER_INVIS",
        "SHADOW_OCCLUDER",
    ]
    skip_objs = []
    for name in skip_names:
        obj = create_cube(f"Obj_{name}")
        mat = bpy.data.materials.new(name)
        obj.data.materials.append(mat)
        skip_objs.append(obj)

    # 2. MSFS material type tests (non-matching names, but msfs_material_type set)
    msfs_types = [
        "msfs_decal",
        "msfs_geo_decal",
        "msfs_geo_decal_frosted",
        "msfs_geo_decal_blendmasked",
        "msfs_glass",
        "msfs_windshield",
        "msfs_invisible",
        "msfs_environment_occluder",
    ]
    for mtype in msfs_types:
        obj = create_cube(f"Obj_Type_{mtype}")
        mat = bpy.data.materials.new(f"CustomMat_{mtype}")
        if hasattr(mat, 'msfs_material_type'):
            try:
                mat.msfs_material_type = mtype
            except Exception:
                pass
        mat['msfs_material_type'] = mtype
        obj.data.materials.append(mat)
        skip_objs.append(obj)

    # 3. Mixed materials object: has standard material and a decal material -> MUST NOT BE SKIPPED
    obj_mixed = create_cube("Obj_Mixed")
    mat_std = bpy.data.materials.new("MAT_COCKPIT_SHELL")
    mat_decal = bpy.data.materials.new("DECAL_LABEL")
    obj_mixed.data.materials.append(mat_std)
    obj_mixed.data.materials.append(mat_decal)

    # 4. Standard mesh with no materials -> MUST NOT BE SKIPPED
    obj_nomat = create_cube("Obj_NoMat")

    # 5. A class word inside the name, not at its end -> MUST NOT BE SKIPPED
    obj_inner = create_cube("Obj_InnerClassWord")
    obj_inner.data.materials.append(bpy.data.materials.new("COCKPIT_GLASS_FRAME_STD"))

    # Select all
    all_objs = skip_objs + [obj_mixed, obj_nomat, obj_inner]
    for o in all_objs:
        o.select_set(True)

    unique_meshes, mesh_to_objs, shared_meshes, replaced_meshes, skipped = (
        uv_autoseam._gather_candidate_objects(bpy.context)
    )

    skip_dict = dict(skipped)
    for o in skip_objs:
        assert o.name in skip_dict, f"{o.name} was not skipped"
        assert skip_dict[o.name] == "only decal, glass, invisible or occluder materials", (
            f"Wrong skip reason for {o.name}: {skip_dict[o.name]}"
        )

    assert obj_mixed.name not in skip_dict, f"Mixed material object {obj_mixed.name} was incorrectly skipped"
    assert obj_nomat.name not in skip_dict, f"No-material object {obj_nomat.name} was incorrectly skipped"
    assert obj_mixed.data in unique_meshes, "obj_mixed mesh should be in unique_meshes"
    assert obj_nomat.data in unique_meshes, "obj_nomat mesh should be in unique_meshes"
    assert obj_inner.data in unique_meshes, "a class word inside the material name must not skip the object"
    assert len(unique_meshes) == 3, f"Expected 3 processed meshes, got {len(unique_meshes)}"

    print("  -> PASS: Decal skip correctly handles all 8 name classes, MSFS material types, and mixed materials.")


def test_report_attention_counts():
    """Verify readable report formatting, summary at top, and attention counts."""
    print("Test 12: Report formatting and attention counts...")
    bpy.ops.wm.read_homefile(use_empty=True)

    # Synthetic mock mesh reports
    mock_reports = [
        {
            'mesh': 'CleanMesh',
            'objects': ['CleanObj'],
            'islands': 4,
            'extra_vertices_vs_shading': 0,
            'time': 0.12,
            'unverified_charts': [],
            'islands_over_limits': [],
            'over_limits_count': 0,
            'sliver_overlaps': 0,
            'warnings': [],
        },
        {
            'mesh': 'AttentionMesh',
            'objects': ['AttentionObj1', 'AttentionObj2'],
            'islands': 8,
            'extra_vertices_vs_shading': 14,
            'time': 1.45,
            'unverified_charts': [{'faces': 2, 'distortion': 2.37}, {'faces': 2, 'distortion': 1.50},
                                  {'faces': 2, 'distortion': float('inf')}],
            'islands_over_limits': [{'faces': 43, 'distortion': 1.28, 'overlap': False}],
            'over_limits_count': 1,
            'sliver_overlaps': 2,
            'warnings': ['Shading-split fallback: mesh normals have no split edges'],
        },
    ]

    uv_autoseam.write_report_text(mock_reports, run_time=1.57)

    txt = bpy.data.texts.get(uv_autoseam.REPORT_TEXT_NAME)
    assert txt is not None, "Report text datablock not created"
    text_content = txt.as_string()
    lines = [l.strip() for l in text_content.splitlines() if l.strip()]

    # 1. Summary at the top
    assert lines[0].startswith("# FSS Auto Seam Report")
    assert lines[1] == "# Meshes processed: 2 in 1.57s"
    assert lines[2] == "# Distortion limit: 1.25"
    assert lines[3] == "# Meshes needing attention: 1 (1 clean)"

    # 2. Meshes needing attention listed first
    att_pos = -1
    clean_pos = -1
    for idx, l in enumerate(lines):
        if "Mesh 'AttentionMesh'" in l:
            att_pos = idx
        elif "Mesh 'CleanMesh'" in l:
            clean_pos = idx

    assert att_pos != -1, "AttentionMesh not found in report"
    assert clean_pos != -1, "CleanMesh not found in report"
    assert att_pos < clean_pos, f"Meshes needing attention must come first: att_pos={att_pos}, clean_pos={clean_pos}"

    # 3. Plain wording checks
    # repeated problems are grouped into one line each; zero-area faces are reported apart
    assert sum("too distorted to flatten" in l for l in lines) == 1
    assert any("2 quad(s) or face(s) too distorted to flatten (worst 2.37)" in l for l in lines)
    assert any("1 group(s) of faces with zero area" in l for l in lines)
    assert any("1 island(s) too stretched (largest 43 faces, worst 1.28): add a seam by hand" in l for l in lines)
    assert any("Warning: Shading-split fallback" in l for l in lines)
    assert any("2 sliver overlap(s) ignored (< 1e-8 m²)" in l for l in lines)

    # 4. over_limits counted separately from unverified
    att_block = [l for l in lines[att_pos:clean_pos]]
    stat_line = [l for l in att_block if "over_limits=" in l][0]
    assert "over_limits=1" in stat_line
    assert "unverified=3" in stat_line

    print("  -> PASS: Report summary, attention ordering, plain wording, and separate over_limits verified.")


def test_distortion_limit():
    """The panel's Distortion Limit reaches the core and the report; a higher limit gives fewer seams."""
    print("Test 13: Distortion limit...")
    bpy.ops.wm.read_homefile(use_empty=True)
    scene = bpy.context.scene
    assert abs(scene.fss_uv_autoseam_limit - 1.25) < 1e-6, "default limit must stay 1.25"
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12)
    obj = bpy.context.active_object
    counts = {}
    for limit in (1.10, 1.60):
        scene.fss_uv_autoseam_limit = limit
        uv_autoseam.clear_auto_seams(obj.data)
        bpy.ops.fss.uv_propose_seams()
        text = bpy.data.texts[uv_autoseam.REPORT_TEXT_NAME].as_string()
        assert f"# Distortion limit: {limit:.2f}" in text, f"report must state limit {limit}"
        counts[limit] = uv_autoseam.get_mesh_seam_counts(obj.data)[0]
        _, _, rep = uv_autoseam.propose(obj, limit=limit)
        assert rep['limit'] == limit
        assert all(i['distortion'] > limit or i['overlap'] for i in rep['islands_over_limits'])
    print(f"  proposed seams: {counts}")
    assert counts[1.10] > counts[1.60], "a lower limit must give more seams on a sphere"

    # the report's 'too stretched' line follows the run's limit
    report = {'mesh': 'M', 'objects': ['O'], 'islands': 2, 'extra_vertices_vs_shading': 0, 'time': 0.1,
              'unverified_charts': [], 'islands_over_limits': [{'faces': 9, 'distortion': 1.45, 'overlap': False}],
              'over_limits_count': 1, 'sliver_overlaps': 0, 'warnings': []}
    for limit, expected in ((1.40, True), (1.50, False)):
        uv_autoseam.write_report_text([dict(report, limit=limit)], run_time=0.1)
        text = bpy.data.texts[uv_autoseam.REPORT_TEXT_NAME].as_string()
        assert ("too stretched" in text) == expected, f"limit {limit}: 'too stretched' expected {expected}"
    print("  -> PASS: limit in core, final check and report; 1.10 gives more seams than 1.60.")


def test_accept_and_unwrap():
    """Accept + Unwrap: seams accepted, Angle Based unwrap along them, decal faces keep their UVs, state restored."""
    print("Test 14: Accept + Unwrap...")
    bpy.ops.wm.read_homefile(use_empty=True)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12)
    obj = bpy.context.active_object
    me = obj.data
    me.materials.append(bpy.data.materials.new('COCKPIT_FRONT_STD'))
    me.materials.append(bpy.data.materials.new('COCKPIT_FRONT_DECAL'))
    decal = np.zeros(len(me.polygons), bool)
    decal[:24] = True  # one cap ring gets the decal material
    me.polygons.foreach_set('material_index', decal.astype(np.int32))
    uv = np.zeros(len(me.loops) * 2)
    me.uv_layers.active.data.foreach_get('uv', uv)
    decal_loops = np.zeros(len(me.loops), bool)
    for p in me.polygons:
        if decal[p.index]:
            decal_loops[p.loop_start:p.loop_start + p.loop_total] = True
    uv = uv.reshape(-1, 2)
    uv[decal_loops] = 0.123  # a hand-made decal layout to keep
    me.uv_layers.active.data.foreach_set('uv', uv.ravel())
    me.update()
    before = uv.copy()

    other = create_cube('OtherSelected', location=(5, 0, 0))
    bpy.ops.fss.uv_propose_seams()
    proposed, _ = uv_autoseam.get_mesh_seam_counts(me)
    assert proposed > 0, "the sphere needs proposed seams for this test"
    other.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    res = bpy.ops.fss.uv_accept_and_unwrap()
    assert res == {'FINISHED'}, res
    proposed_after, current_after = uv_autoseam.get_mesh_seam_counts(me)
    assert proposed_after == 0 and current_after >= proposed, (proposed_after, current_after)

    after = np.zeros(len(me.loops) * 2)
    me.uv_layers.active.data.foreach_get('uv', after)
    after = after.reshape(-1, 2)
    assert np.allclose(after[decal_loops], before[decal_loops]), "decal faces must keep their UVs"
    assert not np.allclose(after[~decal_loops], before[~decal_loops]), "the other faces must be unwrapped"
    assert bpy.context.mode == 'OBJECT' and bpy.context.view_layer.objects.active == obj and obj.select_get()
    assert not other.select_get(), "selection must be restored"

    # the unwrapped islands follow the seams: no UV continuity across an accepted seam between two unwrapped faces
    seams = np.zeros(len(me.edges), bool)
    me.edges.foreach_get('use_seam', seams)
    corner_uv = {}
    for p in me.polygons:
        if decal[p.index]:
            continue
        for li in p.loop_indices:
            corner_uv[(p.index, me.loops[li].vertex_index)] = tuple(np.round(after[li], 6))
    edge_faces = {}
    for p in me.polygons:
        if not decal[p.index]:
            for ek in p.edge_keys:
                edge_faces.setdefault(ek, []).append(p.index)
    edge_index = {e.key: e.index for e in me.edges}
    joined_across_seam = 0
    for ek, faces in edge_faces.items():
        if len(faces) == 2 and seams[edge_index[ek]]:
            a, b = faces
            if all(corner_uv[(a, v)] == corner_uv[(b, v)] for v in ek):
                joined_across_seam += 1
    assert joined_across_seam == 0, f"{joined_across_seam} seam edges kept continuous UVs"

    # non-uniform scale is reported
    assert uv_autoseam._uniform_scale(obj)
    obj.scale = (1.0, 1.0, 2.0)
    bpy.context.view_layer.update()
    assert not uv_autoseam._uniform_scale(obj)

    # from Edit Mode: works and returns to Edit Mode
    obj.scale = (1.0, 1.0, 1.0)
    bpy.ops.object.mode_set(mode='EDIT')
    assert bpy.ops.fss.uv_accept_and_unwrap() == {'FINISHED'}
    assert bpy.context.mode == 'EDIT_MESH'
    bpy.ops.object.mode_set(mode='OBJECT')
    print(f"  -> PASS: {proposed} seams accepted, decal UVs kept, islands follow seams, state restored.")


def test_progress_and_buttons():
    """Progress inside a mesh (same seams with and without it), the panel's buttons by seam counts, Cancel."""
    print("Test 15: Progress, buttons and Cancel...")
    from fss_blender_tools import uv_autoseam_core
    bpy.ops.wm.read_homefile(use_empty=True)
    objs = load_e2_test_objects()
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12)
    objs.append(bpy.context.active_object)
    interval = uv_autoseam_core.PROGRESS_INTERVAL
    uv_autoseam_core.PROGRESS_INTERVAL = 0.0
    names = [n for n, _ in uv_autoseam_core.PROGRESS_STAGES]
    try:
        for obj in objs:
            calls = []
            edges_with, _, _ = uv_autoseam.propose(obj, progress=lambda st, f: calls.append((st, f)))
            edges_without, _, _ = uv_autoseam.propose(obj)
            assert sorted(edges_with) == sorted(edges_without), f"{obj.name}: progress changed the proposal"
            assert calls, f"{obj.name}: no progress reported"
            fractions = [f for _, f in calls]
            assert all(0.0 <= f <= 1.0 for f in fractions), fractions
            assert all(b >= a - 1e-12 for a, b in zip(fractions, fractions[1:])), f"{obj.name}: progress went back"
            order = [names.index(st) for st, _ in calls]
            assert order == sorted(order), f"{obj.name}: stages out of order"
            assert calls[-1][0] == 'Final check', calls[-1]
            print(f"  {obj.name}: {len(calls)} reports, stages {sorted(set(st for st, _ in calls), key=names.index)}")
    finally:
        uv_autoseam_core.PROGRESS_INTERVAL = interval

    p = {'done_faces': 50, 'within': 0.5, 'faces': 50, 'total_faces': 100}
    assert abs(uv_autoseam.progress_factor(p) - 0.75) < 1e-12

    # buttons follow the selected meshes' seam counts
    bpy.ops.wm.read_homefile(use_empty=True)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12)
    obj = bpy.context.active_object
    me = obj.data
    me.edges.foreach_set('use_seam', np.zeros(len(me.edges), bool))
    me.update()
    uv_autoseam._count_cache.clear()
    assert uv_autoseam.seam_buttons(bpy.context) == {'PROPOSE'}, uv_autoseam.seam_buttons(bpy.context)
    bpy.ops.fss.uv_propose_seams()
    assert uv_autoseam.seam_buttons(bpy.context) == {'PROPOSE', 'ACCEPT', 'ACCEPT_UNWRAP', 'DISCARD'}
    bpy.ops.fss.uv_keep_as_artist_seams()
    assert uv_autoseam.seam_buttons(bpy.context) == {'PROPOSE', 'CLEAR'}
    bpy.ops.fss.uv_clear_current_seams('EXEC_DEFAULT')
    assert uv_autoseam.seam_buttons(bpy.context) == {'PROPOSE'}
    bpy.ops.object.mode_set(mode='EDIT')
    assert len(uv_autoseam.seam_buttons(bpy.context)) == 5, "Edit Mode shows every button"
    bpy.ops.object.mode_set(mode='OBJECT')

    # while a run is in progress: no buttons; Cancel only then
    assert not bpy.ops.fss.uv_cancel_auto_seam.poll()
    uv_autoseam._progress = {'verb': 'Proposing', 'index': 1, 'count': 2, 'mesh': 'M', 'faces': 10,
                             'done_faces': 0, 'total_faces': 20, 'stage': 'Merging', 'within': 0.5}
    try:
        assert uv_autoseam.seam_buttons(bpy.context) == set()
        assert bpy.ops.fss.uv_cancel_auto_seam() == {'FINISHED'}
        assert uv_autoseam._cancel_requested
    finally:
        uv_autoseam._progress = None
        uv_autoseam._cancel_requested = False
    print("  -> PASS: same seams with progress, progress in order, buttons by counts, Cancel only during a run.")


def test_overlap_check_collapsed_unwrap():
    """A collapsed trial unwrap (most triangles of zero size, a few across the square) is checked quickly, with the
    same pairs as a brute-force check (EFB_HINGE_ARM_2_R took 221 s in one such check, journal Session 91)."""
    print("Test 16: Overlap check on a collapsed unwrap...")
    from fss_blender_tools import uv_autoseam_core
    rng = np.random.default_rng(7)
    tiny = np.repeat(rng.random((150, 1, 2)) * 0.01 + 0.5, 3, axis=1)  # zero-size triangles near the centre
    huge = rng.random((8, 3, 2))
    huge[:, 0] = (0.0, 0.0)
    huge[:, 1] = (1.0, rng.random())
    U = np.concatenate([tiny, huge])
    t = time.perf_counter()
    got = uv_autoseam_core._overlap_pairs(U)
    dt = time.perf_counter() - t
    assert dt < 2.0, f"overlap check took {dt:.1f} s"

    def brute(U, eps_rel=1e-6):
        allp = U.reshape(-1, 2)
        eps = eps_rel * float((allp.max(0) - allp.min(0)).max())
        out = set()
        for a in range(len(U)):
            for b in range(a + 1, len(U)):
                sep = False
                for T in (U[a], U[b]):
                    e = np.roll(T, -1, axis=0) - T
                    for ax in np.stack([-e[:, 1], e[:, 0]], -1):
                        ax = ax / max(np.linalg.norm(ax), 1e-30)
                        pa, pb = U[a] @ ax, U[b] @ ax
                        if pa.max() <= pb.min() + eps or pb.max() <= pa.min() + eps:
                            sep = True
                lo_a, hi_a, lo_b, hi_b = U[a].min(0), U[a].max(0), U[b].min(0), U[b].max(0)
                if not sep and np.all(lo_a < hi_b - eps) and np.all(lo_b < hi_a - eps):
                    out.add((a, b))
        return out

    assert {tuple(p) for p in np.sort(got, 1).tolist()} == brute(U), "pairs differ from the brute-force check"
    print(f"  -> PASS: {len(got)} pairs in {dt * 1000:.0f} ms, equal to brute force.")


def main():
    print("=" * 70)
    print("RUNNING FSS AUTO SEAM OPERATOR & EXPORT TESTS")
    print("=" * 70)
    test_gathering_and_skipped()
    test_shared_mesh_and_report()
    test_artist_seams_preservation()
    test_second_propose_replaces_only_auto_seams()
    test_keep_as_artist_seams()
    test_keep_and_clear_from_edit_mode()
    test_select_operators_in_edit_mode()
    test_state_restoration()
    test_e2_objects_run()
    test_export_check()
    test_uv_maps_unchanged_after_propose()
    test_decal_skip()
    test_report_attention_counts()
    test_distortion_limit()
    test_accept_and_unwrap()
    test_progress_and_buttons()
    test_overlap_check_collapsed_unwrap()
    print("=" * 70)
    print("ALL TESTS PASSED SUCCESSFULLY.")
    print("=" * 70)


if __name__ == '__main__':
    main()
