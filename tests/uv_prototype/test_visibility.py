"""Unit and integration tests for FSS Visibility analysis, operators, and heatmap mode.

To run:
"C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe" -b --factory-startup --python tests/uv_prototype/test_visibility.py
"""

import json
import math
import os
import shutil
import sys
import time
from pathlib import Path
import bpy
import bmesh
from mathutils import Matrix, Vector
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
from fss_blender_tools import visibility_core, visibility, uv_heatmap, uv_pack

# Register repository add-on
fss_blender_tools.register()

SCRATCH_DIR = REPO_ROOT / 'tests' / '_work' / 'visibility_scratch'
SCRATCH_DIR.mkdir(parents=True, exist_ok=True)


def build_synthetic_scene(blend_path):
    """Construct synthetic test scene with all 15 test geometries."""
    bpy.ops.wm.read_factory_settings(use_empty=True)

    cam_data = bpy.data.cameras.new("CAM_PILOT_CLOSE")
    cam_data.lens = 28.0
    cam_obj = bpy.data.objects.new("CAM_PILOT_CLOSE", cam_data)
    cam_obj.location = Vector((0, 0, 0))
    cam_obj.rotation_euler = (math.radians(90), 0, math.radians(180))
    bpy.context.scene.collection.objects.link(cam_obj)

    def create_quad_facing(name, size, loc, normal_dir='+Y', mat_name=None):
        me = bpy.data.meshes.new(name + "_Mesh")
        bm = bmesh.new()
        hw, hh = size[0] / 2.0, size[1] / 2.0

        if normal_dir == '+Y':
            v1 = bm.verts.new((-hw, 0, -hh))
            v2 = bm.verts.new((hw, 0, -hh))
            v3 = bm.verts.new((hw, 0, hh))
            v4 = bm.verts.new((-hw, 0, hh))
            bm.faces.new((v4, v3, v2, v1))
        elif normal_dir == '-Y':
            v1 = bm.verts.new((-hw, 0, -hh))
            v2 = bm.verts.new((hw, 0, -hh))
            v3 = bm.verts.new((hw, 0, hh))
            v4 = bm.verts.new((-hw, 0, hh))
            bm.faces.new((v1, v2, v3, v4))
        elif normal_dir == '-X':
            v1 = bm.verts.new((0, -hw, -hh))
            v2 = bm.verts.new((0, hw, -hh))
            v3 = bm.verts.new((0, hw, hh))
            v4 = bm.verts.new((0, -hw, hh))
            bm.faces.new((v4, v3, v2, v1))

        bm.to_mesh(me)
        bm.free()
        obj = bpy.data.objects.new(name, me)
        obj.location = Vector(loc)
        bpy.context.scene.collection.objects.link(obj)

        if mat_name:
            mat = bpy.data.materials.new(mat_name)
            obj.data.materials.append(mat)

        return obj

    # 1. Distance invariance: 0.5 m vs 2.0 m
    create_quad_facing("CASE1_PANEL_NEAR", (0.025, 0.025), (0.0, -0.5, -0.10), '+Y')
    create_quad_facing("CASE1_PANEL_FAR",  (0.10, 0.10),   (0.0, -2.0,  0.40), '+Y')

    # 2. Half-covered panel (score ~ 0.50)
    create_quad_facing("CASE2_HALF_PANEL", (0.2, 0.2), (0.4, -2.0, 0.0), '+Y')
    create_quad_facing("CASE2_COVER_PLATE", (0.1, 0.2), (0.35, -1.999, 0.0), '+Y')

    # 3. Straight ahead (w=1.0) vs 90 deg side (w=0.20 floor)
    create_quad_facing("CASE3_PANEL_AHEAD", (0.2, 0.2), (0.0, -2.0, 0.0), '+Y')
    create_quad_facing("CASE3_PANEL_SIDE",  (0.2, 0.2), (2.0, 0.0, 0.0), '-X')

    # 4. Back face never seen (score = 0.000)
    create_quad_facing("CASE4_BACK_FACE", (0.2, 0.2), (0.0, -2.0, -0.8), '-Y')

    # 5. Invisible box hides nothing
    create_quad_facing("CASE5_TARGET_PANEL", (0.2, 0.2), (-0.8, -2.0, 0.0), '+Y')
    me_invis = bpy.data.meshes.new("CASE5_INVIS_BOX_Mesh")
    bm_invis = bmesh.new()
    bmesh.ops.create_cube(bm_invis, size=0.3)
    bm_invis.to_mesh(me_invis)
    bm_invis.free()
    invis_obj = bpy.data.objects.new("CASE5_COLLISION_BOX", me_invis)
    invis_obj.location = Vector((-0.8, -1.5, 0.0))
    mat_invis = bpy.data.materials.new("COLLIDER_MATERIAL")
    invis_obj.data.materials.append(mat_invis)
    bpy.context.scene.collection.objects.link(invis_obj)

    # 6. Decal does not hide its panel
    create_quad_facing("CASE6_OPAQUE_PANEL", (0.2, 0.2), (-0.4, -2.0, 1.0), '+Y', mat_name="PANEL_OPAQUE_MAT")
    create_quad_facing("CASE6_DECAL_QUAD", (0.15, 0.15), (-0.4, -1.98, 1.0), '+Y', mat_name="LABEL_DECAL")

    # 7. Animated action on frames 100 to 200
    lever = create_quad_facing("CASE7_ANIM_LEVER", (0.2, 0.2), (0.8, -2.0, 0.0), '+Y')
    lever.animation_data_create()
    lever.location.z = 0.0
    lever.keyframe_insert(data_path="location", index=2, frame=100)
    lever.location.z = 0.8
    lever.keyframe_insert(data_path="location", index=2, frame=200)

    act7 = lever.animation_data.action
    lever.animation_data.action = None
    tr7 = lever.animation_data.nla_tracks.new()
    tr7.name = "LEVER_TRACK"
    tr7.strips.new(act7.name, 100, act7)

    create_quad_facing("CASE7_SENSOR_PANEL", (0.15, 0.15), (0.8, -2.05, 0.8), '+Y')

    # 8. Multi-face resolution invariance (single quad vs 10,000 faces at 2 m)
    create_quad_facing("CASE8_PANEL_QUAD", (0.2, 0.2), (0.3, -2.0, -0.4), '+Y')

    # Subdivided grid into 10,000 faces (100 x 100) facing +Y
    me_grid = bpy.data.meshes.new("CASE8_PANEL_GRID_Mesh")
    bm_grid = bmesh.new()
    bmesh.ops.create_grid(bm_grid, x_segments=100, y_segments=100, size=0.1)
    for v in bm_grid.verts:
        x, y, z = v.co.x, v.co.y, v.co.z
        v.co.x = x
        v.co.y = z
        v.co.z = -y
    bm_grid.to_mesh(me_grid)
    bm_grid.free()
    grid_obj = bpy.data.objects.new("CASE8_PANEL_GRID", me_grid)
    grid_obj.location = Vector((-0.3, -2.0, -0.4))
    bpy.context.scene.collection.objects.link(grid_obj)

    # 9. Mirror object with one copy hidden behind a wall
    mirr_obj = create_quad_facing("CASE9_MIRROR_OBJ", (0.2, 0.2), (0.0, 0.0, 0.0), '+Y')
    for v in mirr_obj.data.vertices:
        v.co += Vector((0.5, -2.0, 0.4))
    mirr_obj.data.update()
    mod_m = mirr_obj.modifiers.new("MirrX", "MIRROR")
    mod_m.use_axis[0] = True
    create_quad_facing("CASE9_WALL_BLOCK", (0.4, 0.4), (-0.5, -1.5, 0.4), '+Y')

    # 10. Object with Triangulate modifier (half-covered reads ~ 0.50)
    tri_obj = create_quad_facing("CASE10_TRI_PANEL", (0.2, 0.2), (-0.4, -2.0, 0.0), '+Y')
    tri_obj.modifiers.new("Tri", "TRIANGULATE")
    create_quad_facing("CASE10_COVER_PLATE", (0.1, 0.2), (-0.45, -1.999, 0.0), '+Y')

    # 11. Two linked duplicates, one hidden
    shared_me = bpy.data.meshes.new("CASE11_SHARED_Mesh")
    bm_sh = bmesh.new()
    v1 = bm_sh.verts.new((-0.1, 0, -0.1))
    v2 = bm_sh.verts.new(( 0.1, 0, -0.1))
    v3 = bm_sh.verts.new(( 0.1, 0,  0.1))
    v4 = bm_sh.verts.new((-0.1, 0,  0.1))
    bm_sh.faces.new((v4, v3, v2, v1))
    bm_sh.to_mesh(shared_me)
    bm_sh.free()

    obj_vis = bpy.data.objects.new("CASE11_OBJ_VISIBLE", shared_me)
    obj_vis.location = Vector((-0.6, -2.0, -0.8))
    bpy.context.scene.collection.objects.link(obj_vis)

    obj_hid = bpy.data.objects.new("CASE11_OBJ_HIDDEN", shared_me)
    obj_hid.location = Vector((0.6, -2.0, -0.8))
    bpy.context.scene.collection.objects.link(obj_hid)
    create_quad_facing("CASE11_BLOCKER", (0.4, 0.4), (0.6, -1.5, -0.8), '+Y')

    # 12. Partly hidden island: two quads in ONE UV island, one in plain view and one hidden
    me12 = bpy.data.meshes.new("CASE12_PARTLY_HIDDEN_Mesh")
    bm12 = bmesh.new()
    v12_0 = bm12.verts.new((1.1, -2.0, 0.0))
    v12_1 = bm12.verts.new((1.3, -2.0, 0.0))
    v12_2 = bm12.verts.new((1.3, -2.0, 0.2))
    v12_3 = bm12.verts.new((1.1, -2.0, 0.2))
    f12_0 = bm12.faces.new((v12_3, v12_2, v12_1, v12_0))

    v12_4 = bm12.verts.new((1.3, -2.0, -0.2))
    v12_5 = bm12.verts.new((1.1, -2.0, -0.2))
    f12_1 = bm12.faces.new((v12_0, v12_1, v12_4, v12_5))

    uv_layer = bm12.loops.layers.uv.new("UVMap")
    f12_0.loops[0][uv_layer].uv = (0.0, 1.0)
    f12_0.loops[1][uv_layer].uv = (1.0, 1.0)
    f12_0.loops[2][uv_layer].uv = (1.0, 0.5)
    f12_0.loops[3][uv_layer].uv = (0.0, 0.5)

    f12_1.loops[0][uv_layer].uv = (0.0, 0.5)
    f12_1.loops[1][uv_layer].uv = (1.0, 0.5)
    f12_1.loops[2][uv_layer].uv = (1.0, 0.0)
    f12_1.loops[3][uv_layer].uv = (0.0, 0.0)

    bm12.to_mesh(me12)
    bm12.free()
    obj12 = bpy.data.objects.new("CASE12_PARTLY_HIDDEN_OBJ", me12)
    bpy.context.scene.collection.objects.link(obj12)

    # Blocker in front of Quad 1
    me_b = bpy.data.meshes.new("CASE12_BLOCKER_Mesh")
    bm_b = bmesh.new()
    v_b0 = bm_b.verts.new((0.70, -1.5, -0.20))
    v_b1 = bm_b.verts.new((1.10, -1.5, -0.20))
    v_b2 = bm_b.verts.new((1.10, -1.5,  0.00))
    v_b3 = bm_b.verts.new((0.70, -1.5,  0.00))
    bm_b.faces.new((v_b3, v_b2, v_b1, v_b0))
    bm_b.to_mesh(me_b)
    bm_b.free()
    obj_b = bpy.data.objects.new("CASE12_BLOCKER", me_b)
    bpy.context.scene.collection.objects.link(obj_b)

    # 13. Small 2 mm part at 1 m with parent panel
    p13 = create_quad_facing("CASE13_PARENT_PANEL", (0.2, 0.2), (0.0, -1.0, 0.6), '+Y')
    c13 = create_quad_facing("CASE13_CHILD_PART", (0.002, 0.002), (0.0, -1.0, 0.5), '+Y')
    c13.parent = p13

    # 14. Same 2 mm part with no parent
    create_quad_facing("CASE14_STANDALONE_PART", (0.002, 0.002), (0.3, -1.0, 0.5), '+Y')

    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    return blend_path


# ---------------------------------------------------------------------------
# Test 1: Synthetic 15 Cases through visibility_core
# ---------------------------------------------------------------------------

def test_synthetic_15_cases():
    """Verify all 15 synthetic cases pass through visibility_core (Round 5)."""
    blend_path = SCRATCH_DIR / "synthetic_validation.blend"
    build_synthetic_scene(blend_path)

    cameras = [{
        'name': 'CAM_PILOT_CLOSE',
        'type': 'LOOK_AROUND',
        'pos': Vector((0, 0, 0)),
        'forward': Vector((0, -1, 0)),
        'obj_name': 'CAM_PILOT_CLOSE',
    }]

    results = visibility_core.analyze_visibility(
        blend_path=blend_path,
        cameras=cameras,
        anim_states=(0.0, 0.25, 0.5, 0.75, 1.0),
        cube_res=1024,
        floor=0.2,
        falloff=1.0,
        min_px_threshold=10.0,
    )

    objs = results['object_summaries']
    isls = results['island_summaries']
    m_arrays = results['mesh_arrays']
    mesh_meta = results['mesh_meta']

    # Case 1: Distance Invariance
    s_near = objs["CASE1_PANEL_NEAR"]['score']
    s_far = objs["CASE1_PANEL_FAR"]['score']
    assert s_near >= 0.90, f"Case 1 Near score too low: {s_near}"
    assert s_far >= 0.90, f"Case 1 Far score too low: {s_far}"
    assert abs(s_near - s_far) < 0.02, f"Case 1 Distance diff: {abs(s_near - s_far)}"

    # Case 2: Half-Covered Panel
    s_half = objs["CASE2_HALF_PANEL"]['score']
    assert 0.45 <= s_half <= 0.55, f"Case 2 score out of range: {s_half}"

    # Case 3: Direction Weight Ahead vs Side
    s_ahead = objs["CASE3_PANEL_AHEAD"]['score']
    s_side = objs["CASE3_PANEL_SIDE"]['score']
    assert s_ahead >= 0.98, f"Case 3 Ahead score too low: {s_ahead}"
    assert 0.18 <= s_side <= 0.22, f"Case 3 Side score not near floor: {s_side}"

    # Case 4: Back Face
    s_back = objs["CASE4_BACK_FACE"]['score']
    assert s_back == 0.0, f"Case 4 Back face not 0.0: {s_back}"

    # Case 5: Invisible Box
    s_invis_target = objs["CASE5_TARGET_PANEL"]['score']
    assert s_invis_target >= 0.85, f"Case 5 Target occluded: {s_invis_target}"
    assert "CASE5_COLLISION_BOX" not in objs, "Case 5 collision box was scored"

    # Case 6: Decal on Panel
    s_opaque = objs["CASE6_OPAQUE_PANEL"]['score']
    s_decal = objs["CASE6_DECAL_QUAD"]['score']
    assert s_opaque >= 0.80 and s_decal >= 0.80, f"Case 6 scores low: {s_opaque}, {s_decal}"
    assert abs(s_opaque - s_decal) < 0.10, f"Case 6 mismatch: {s_opaque} vs {s_decal}"

    # Case 7: Animated Action 100-200
    s_lever = objs["CASE7_ANIM_LEVER"]['score']
    s_sensor = objs["CASE7_SENSOR_PANEL"]['score']
    assert s_lever >= 0.80 and s_sensor >= 0.80, f"Case 7 scores low: {s_lever}, {s_sensor}"

    # Case 8: Multi-Face Grid Invariance
    s_quad = isls["CASE8_PANEL_QUAD_Mesh__isl_0"]['score']
    s_grid = isls["CASE8_PANEL_GRID_Mesh__isl_0"]['score']
    assert s_quad >= 0.85, f"Case 8 Quad low: {s_quad}"
    assert abs(s_grid - s_quad) <= 0.02, f"Case 8 Island diff > 0.02: {abs(s_grid - s_quad)}"

    # Case 9: Mirror with one copy blocked
    s_mirr = objs["CASE9_MIRROR_OBJ"]['score']
    assert s_mirr >= 0.85, f"Case 9 Mirror score low: {s_mirr}"

    # Case 10: Triangulate Modifier
    s_tri = objs["CASE10_TRI_PANEL"]['score']
    assert 0.45 <= s_tri <= 0.55, f"Case 10 Tri score out of range: {s_tri}"

    # Case 11: Linked Duplicates
    s_vis = objs["CASE11_OBJ_VISIBLE"]['score']
    s_hid = objs["CASE11_OBJ_HIDDEN"]['score']
    assert s_vis >= 0.85, f"Case 11 score low: {s_vis}"
    assert s_vis == s_hid, f"Case 11 shared mismatch: {s_vis} vs {s_hid}"

    # Case 12: Partly Hidden Island
    isl12 = isls["CASE12_PARTLY_HIDDEN_Mesh__isl_0"]
    assert isl12['score'] >= 0.80, f"Case 12 island value degraded: {isl12['score']}"
    assert 0.45 <= isl12['seen_area_share'] <= 0.55, f"Case 12 share out of range: {isl12['seen_area_share']}"

    # Case 13: 2 mm part with parent
    s_c13 = objs["CASE13_CHILD_PART"]['score']
    assert objs["CASE13_CHILD_PART"]['undetermined'], "Case 13 not undetermined"
    assert s_c13 >= 0.85, f"Case 13 child didn't inherit parent: {s_c13}"
    assert not objs["CASE13_CHILD_PART"]['never_seen'], "Case 13 undetermined marked never-seen"

    # Case 14: 2 mm part without parent
    s_c14 = objs["CASE14_STANDALONE_PART"]['score']
    assert objs["CASE14_STANDALONE_PART"]['undetermined'], "Case 14 not undetermined"
    assert s_c14 == 1.0, f"Case 14 fallback not 1.0: {s_c14}"

    # Case 15: Staleness Check
    vis_file = visibility_core.save_visibility_file(blend_path, results)
    meta_loaded, _, stale_none = visibility_core.load_visibility_file(vis_file, scene_meshes=bpy.data.meshes)
    assert meta_loaded['schema_version'] == 5
    assert len(stale_none) == 0, f"Expected 0 stale, got {stale_none}"

    # Triangulate a mesh to trigger staleness
    target_me = bpy.data.meshes["CASE1_PANEL_NEAR_Mesh"]
    bm_stale = bmesh.new()
    bm_stale.from_mesh(target_me)
    bmesh.ops.triangulate(bm_stale, faces=bm_stale.faces)
    bm_stale.to_mesh(target_me)
    bm_stale.free()

    _, _, stale_detected = visibility_core.load_visibility_file(vis_file, scene_meshes=bpy.data.meshes)
    assert "CASE1_PANEL_NEAR_Mesh" in stale_detected, f"Staleness not detected: {stale_detected}"
    print("PASS: test_synthetic_15_cases")


# ---------------------------------------------------------------------------
# Test 2: Operator Update Visibility on Saved Scene
# ---------------------------------------------------------------------------

def test_operator_on_saved_scene():
    """Verify Update Visibility operator creates file, report text, and panel state."""
    blend_path = SCRATCH_DIR / "operator_test.blend"
    build_synthetic_scene(blend_path)

    # Set up scene cameras in fss_visibility
    visibility.sync_camera_list(bpy.context.scene)
    settings = bpy.context.scene.fss_visibility
    cam_item = next(item for item in settings.cameras if item.camera_name == "CAM_PILOT_CLOSE")
    cam_item.include = True
    cam_item.mode = 'LOOK_AROUND'
    settings.states = 3

    assert bpy.ops.fss.update_visibility.poll(), "Operator poll must be True on saved scene with camera"

    ret = bpy.ops.fss.update_visibility()
    assert ret == {'FINISHED'}, f"Update Visibility failed: {ret}"

    # Check file exists and has valid schema 5 + settings
    vis_file = blend_path.with_suffix('.visibility')
    assert vis_file.exists(), f"File {vis_file} was not created"
    meta, data, _ = visibility_core.load_visibility_file(vis_file, scene_meshes=bpy.data.meshes)
    assert meta['schema_version'] == 5
    assert 'settings' in meta
    assert meta['settings']['states'] == 3
    assert len(meta['settings']['cameras']) == 1

    # Check FSS Visibility Report text datablock
    rep_text = bpy.data.texts.get(visibility.REPORT_TEXT_NAME)
    assert rep_text is not None, "Report text datablock missing"
    assert "FSS VISIBILITY REPORT" in rep_text.as_string()
    assert "NEVER-SEEN OBJECTS" in rep_text.as_string()

    # Check Select Never Seen and Select Stale operators
    ret_sel = bpy.ops.fss.visibility_select_never_seen()
    assert ret_sel == {'FINISHED'}, f"Select Never Seen failed: {ret_sel}"

    ret_stale = bpy.ops.fss.visibility_select_stale()
    assert ret_stale == {'FINISHED'}, f"Select Stale failed: {ret_stale}"

    print("PASS: test_operator_on_saved_scene")


# ---------------------------------------------------------------------------
# Test 3: Scene Unchanged After Run & Esc
# ---------------------------------------------------------------------------

def test_scene_unchanged_after_run_and_esc():
    """Verify scene is left unchanged: face attributes removed, frames and actions restored."""
    blend_path = SCRATCH_DIR / "restore_test.blend"
    build_synthetic_scene(blend_path)

    # Set initial frame
    bpy.context.scene.frame_set(42)

    visibility.sync_camera_list(bpy.context.scene)
    settings = bpy.context.scene.fss_visibility
    settings.cameras[0].include = True

    # 1. Normal run
    bpy.ops.fss.update_visibility()
    assert bpy.context.scene.frame_current == 42, f"Frame not restored (got {bpy.context.scene.frame_current})"
    for me in bpy.data.meshes:
        assert visibility_core.ORIG_FACE_ATTR_NAME not in me.attributes, f"Temporary attribute leaked on {me.name}"

    # 2. Simulated Esc cancellation during analysis
    cameras = [{
        'name': 'CAM_PILOT_CLOSE',
        'type': 'LOOK_AROUND',
        'pos': Vector((0, 0, 0)),
        'forward': Vector((0, -1, 0)),
        'obj_name': 'CAM_PILOT_CLOSE',
    }]
    analyzer = visibility_core.VisibilityAnalyzer(
        scene=bpy.context.scene,
        view_layer=bpy.context.view_layer,
        cameras=cameras,
        blend_path=blend_path,
    )
    analyzer.prepare()
    analyzer.execute_next_step()
    # Cancel!
    analyzer.cleanup()

    assert bpy.context.scene.frame_current == 42, f"Frame not restored after cancel: {bpy.context.scene.frame_current}"
    for me in bpy.data.meshes:
        assert visibility_core.ORIG_FACE_ATTR_NAME not in me.attributes, f"Attribute leaked after cancel on {me.name}"

    print("PASS: test_scene_unchanged_after_run_and_esc")


# ---------------------------------------------------------------------------
# Test 4: Disabled States (Unsaved file, No camera)
# ---------------------------------------------------------------------------

def test_disabled_states():
    """Verify operator is disabled when file is unsaved or no camera is included."""
    # 1. Unsaved file
    bpy.ops.wm.read_factory_settings(use_empty=True)
    assert not bpy.data.filepath
    assert not bpy.ops.fss.update_visibility.poll(), "Poll must be False when file is unsaved"

    # 2. Saved file without camera included
    blend_path = SCRATCH_DIR / "disabled_state_test.blend"
    build_synthetic_scene(blend_path)
    visibility.sync_camera_list(bpy.context.scene)
    settings = bpy.context.scene.fss_visibility
    for item in settings.cameras:
        item.include = False

    assert not bpy.ops.fss.update_visibility.poll(), "Poll must be False when no cameras are included"

    # 3. Include camera
    settings.cameras[0].include = True
    assert bpy.ops.fss.update_visibility.poll(), "Poll must be True when camera is included and file is saved"

    print("PASS: test_disabled_states")


# ---------------------------------------------------------------------------
# Test 5: Visibility Heatmap Mode on Loaded Data
# ---------------------------------------------------------------------------

def test_visibility_heatmap_mode():
    """Verify Visibility heatmap mode properly colors faces and builds chart."""
    blend_path = SCRATCH_DIR / "heatmap_vis_test.blend"
    build_synthetic_scene(blend_path)

    visibility.sync_camera_list(bpy.context.scene)
    bpy.context.scene.fss_visibility.cameras[0].include = True
    bpy.ops.fss.update_visibility()

    # Enable Heatmap and set Visibility mode
    scene = bpy.context.scene
    scene.fss_uv_heatmap_show = True
    scene.fss_uv_heatmap_mode = 'VISIBILITY'

    # Select panel objects
    bpy.ops.object.select_all(action='DESELECT')
    bpy.data.objects["CASE1_PANEL_NEAR"].select_set(True)
    bpy.data.objects["CASE4_BACK_FACE"].select_set(True)
    bpy.data.objects["CASE13_CHILD_PART"].select_set(True)

    uv_heatmap.update_heatmap_cache(bpy.context, refresh=True)
    stats = uv_heatmap._global_stats
    assert stats['total_tris'] > 0, "No triangles in heatmap stats"
    assert 'chart_visibility' in stats, "Visibility distribution missing from stats"

    # Verify colors in cache
    cache_near = uv_heatmap._cache["CASE1_PANEL_NEAR"]
    col_near = cache_near.colors_visibility[0]
    # Visible face: blue side (near 1.0)
    assert col_near[2] > col_near[0], f"Visible face not blue: {col_near}"

    cache_back = uv_heatmap._cache["CASE4_BACK_FACE"]
    col_back = cache_back.colors_visibility[0]
    # Back face: magenta (1.0, 0.0, 1.0)
    assert col_back[0] > 0.9 and col_back[1] < 0.1 and col_back[2] > 0.9, f"Back face not magenta: {col_back}"

    cache_child = uv_heatmap._cache["CASE13_CHILD_PART"]
    col_child = cache_child.colors_visibility[0]
    # Undetermined: cyan (0.0, 0.85, 0.85)
    assert col_child[0] < 0.1 and col_child[1] > 0.8 and col_child[2] > 0.8, f"Undetermined not cyan: {col_child}"

    # Verify chart data
    cdata = uv_heatmap.chart_data('VISIBILITY', stats)
    assert cdata is not None, "Chart data is None"
    assert cdata['title'] == 'Visibility'
    assert len(cdata['ticks']) == 5
    assert len(cdata['marks']) == 1

    print("PASS: test_visibility_heatmap_mode")


# ---------------------------------------------------------------------------
# Test 6: Heatmap Modifier Face Mapping & Evaluated Face Count Mismatch
# ---------------------------------------------------------------------------

def test_heatmap_modifier_face_mapping():
    """Verify heatmap colors across modifiers (Mirror, Triangulate) and No-data on count mismatch."""
    blend_path = SCRATCH_DIR / "heatmap_modifier_test.blend"
    build_synthetic_scene(blend_path)

    visibility.sync_camera_list(bpy.context.scene)
    bpy.context.scene.fss_visibility.cameras[0].include = True
    bpy.ops.fss.update_visibility()

    vis_file = blend_path.with_suffix('.visibility')
    meta, data, _ = visibility_core.load_visibility_file(vis_file)

    # Enable Heatmap and set Visibility mode
    scene = bpy.context.scene
    scene.fss_uv_heatmap_show = True
    scene.fss_uv_heatmap_mode = 'VISIBILITY'

    # 1. Mirror object (CASE9_MIRROR_OBJ)
    bpy.ops.object.select_all(action='DESELECT')
    obj_mirr = bpy.data.objects["CASE9_MIRROR_OBJ"]
    obj_mirr.select_set(True)

    uv_heatmap.update_heatmap_cache(bpy.context, refresh=True)
    cache_mirr = uv_heatmap._cache["CASE9_MIRROR_OBJ"]
    assert cache_mirr.vis_data['has_data'], "Mirror object must have visibility data"

    # Original face 0 score and color
    s_mirr = data['CASE9_MIRROR_OBJ_Mesh__face_scores'][0]
    expected_color_mirr = visibility_core.compute_heatmap_colors(
        np.array([s_mirr]), np.array([False]), np.array([False])
    )[0]

    # Every evaluated triangle (original half and mirrored half) must match original face 0 color
    assert len(cache_mirr.colors_visibility) > 0, "No evaluated triangles for mirror object"
    for tri_col in cache_mirr.colors_visibility:
        np.testing.assert_allclose(tri_col, expected_color_mirr, atol=1e-4)

    # 2. Triangulate object (CASE10_TRI_PANEL)
    bpy.ops.object.select_all(action='DESELECT')
    obj_tri = bpy.data.objects["CASE10_TRI_PANEL"]
    obj_tri.select_set(True)

    uv_heatmap.update_heatmap_cache(bpy.context, refresh=True)
    cache_tri = uv_heatmap._cache["CASE10_TRI_PANEL"]
    assert cache_tri.vis_data['has_data'], "Triangulate object must have visibility data"

    s_tri = data['CASE10_TRI_PANEL_Mesh__face_scores'][0]
    expected_color_tri = visibility_core.compute_heatmap_colors(
        np.array([s_tri]), np.array([False]), np.array([False])
    )[0]

    assert len(cache_tri.colors_visibility) > 0, "No evaluated triangles for triangulate object"
    for tri_col in cache_tri.colors_visibility:
        np.testing.assert_allclose(tri_col, expected_color_tri, atol=1e-4)

    # 3. Object whose evaluated face count changed after the run shows No data
    bpy.ops.object.select_all(action='DESELECT')
    obj_near = bpy.data.objects["CASE1_PANEL_NEAR"]
    obj_near.select_set(True)

    # Before modifying: has valid data
    uv_heatmap.update_heatmap_cache(bpy.context, refresh=True)
    assert uv_heatmap._cache["CASE1_PANEL_NEAR"].vis_data['has_data'], "Base panel must have data"

    # Add Subsurf modifier so evaluated face count changes from 1 to 4
    mod_sub = obj_near.modifiers.new("ChangeEvalCount", "SUBSURF")
    mod_sub.levels = 1

    uv_heatmap.update_heatmap_cache(bpy.context, refresh=True)
    cache_near_changed = uv_heatmap._cache["CASE1_PANEL_NEAR"]
    assert not cache_near_changed.vis_data['has_data'], "Object with changed eval face count must NOT have data"
    assert uv_heatmap._global_stats['no_data_count'] == 1, "no_data_count must be 1"

    for tri_col in cache_near_changed.colors_visibility:
        np.testing.assert_allclose(tri_col, uv_heatmap.COLOR_NO_DATA, atol=1e-4)

    # Restore modifier and verify it regains data
    obj_near.modifiers.remove(mod_sub)
    uv_heatmap.update_heatmap_cache(bpy.context, refresh=True)
    assert uv_heatmap._cache["CASE1_PANEL_NEAR"].vis_data['has_data'], "Panel must regain data when modifier removed"
    assert uv_heatmap._global_stats['no_data_count'] == 0, "no_data_count must return to 0"

    print("PASS: test_heatmap_modifier_face_mapping")


# ---------------------------------------------------------------------------
# Test 7: Camera Renaming and Deletion
# ---------------------------------------------------------------------------

def test_camera_renaming_and_deletion():
    """Verify camera items preserve Include and Mode across renames and delete cleanly."""
    bpy.ops.wm.read_factory_settings(use_empty=True)

    cam1_data = bpy.data.cameras.new("CAM_ALPHA")
    cam1_obj = bpy.data.objects.new("CAM_ALPHA", cam1_data)
    bpy.context.scene.collection.objects.link(cam1_obj)

    cam2_data = bpy.data.cameras.new("CAM_BETA")
    cam2_obj = bpy.data.objects.new("CAM_BETA", cam2_data)
    bpy.context.scene.collection.objects.link(cam2_obj)

    visibility.sync_camera_list(bpy.context.scene)
    settings = bpy.context.scene.fss_visibility
    assert len(settings.cameras) == 2, f"Expected 2 cameras, got {len(settings.cameras)}"

    # Configure camera 1
    item1 = next(it for it in settings.cameras if it.camera == cam1_obj)
    item1.include = True
    item1.mode = 'FIXED_VIEW'

    # Configure camera 2
    item2 = next(it for it in settings.cameras if it.camera == cam2_obj)
    item2.include = False
    item2.mode = 'LOOK_AROUND'

    # 1. Rename camera 1: Include and Mode must be kept, name shown must be new name
    cam1_obj.name = "CAM_ALPHA_RENAMED"
    visibility.sync_camera_list(bpy.context.scene)

    item1_after = next((it for it in settings.cameras if it.camera == cam1_obj), None)
    assert item1_after is not None, "Camera 1 missing after rename"
    assert item1_after.camera.name == "CAM_ALPHA_RENAMED"
    assert item1_after.camera_name == "CAM_ALPHA_RENAMED"
    assert item1_after.include is True, "Include was lost on rename"
    assert item1_after.mode == 'FIXED_VIEW', f"Mode was lost on rename: {item1_after.mode}"

    # 2. Delete camera 2: It must leave the list
    bpy.data.objects.remove(cam2_obj, do_unlink=True)
    visibility.sync_camera_list(bpy.context.scene)

    assert len(settings.cameras) == 1, f"Expected 1 camera after delete, got {len(settings.cameras)}"
    assert settings.cameras[0].camera == cam1_obj

    print("PASS: test_camera_renaming_and_deletion")


def test_camera_sync_after_draw():
    """The panel only reads the camera list while drawing; an out-of-date list is synced once by a timer."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    cam = bpy.data.objects.new("CAM_ONE", bpy.data.cameras.new("CAM_ONE"))
    scene.collection.objects.link(cam)
    visibility.sync_camera_list(scene)
    settings = scene.fss_visibility
    settings.cameras[0].include = True
    assert visibility.camera_list_in_sync(scene), "a synced list must read as in sync"

    cam2 = bpy.data.objects.new("CAM_TWO", bpy.data.cameras.new("CAM_TWO"))
    scene.collection.objects.link(cam2)
    assert not visibility.camera_list_in_sync(scene), "an added camera must make the list out of date"

    registered = []
    original = bpy.app.timers.register
    bpy.app.timers.register = lambda fn, first_interval=0.0, persistent=False: registered.append(fn)
    try:
        visibility.schedule_camera_sync(scene)
        visibility.schedule_camera_sync(scene)  # a second draw before the timer runs schedules nothing
    finally:
        bpy.app.timers.register = original
    assert len(registered) == 1, f"expected one scheduled sync, got {len(registered)}"
    assert len(settings.cameras) == 1, "scheduling must not write the list"
    registered[0]()
    assert visibility.camera_list_in_sync(scene)
    assert [it.camera for it in settings.cameras] == [cam, cam2]
    assert settings.cameras[0].include is True, "Include must survive the sync"
    assert visibility._camera_sync_pending is False
    print("PASS: test_camera_sync_after_draw")


# ---------------------------------------------------------------------------
# Test 8: glTF Leak Check with Animations Off
# ---------------------------------------------------------------------------

def test_gltf_leak_check():
    """Verify that glTF export does not leak temporary attributes or extras."""
    blend_path = SCRATCH_DIR / "gltf_leak_test.blend"
    build_synthetic_scene(blend_path)

    visibility.sync_camera_list(bpy.context.scene)
    bpy.context.scene.fss_visibility.cameras[0].include = True
    bpy.ops.fss.update_visibility()

    out_gltf = SCRATCH_DIR / "test_leak.gltf"
    t0 = time.perf_counter()
    bpy.ops.export_scene.gltf(
        filepath=str(out_gltf),
        export_format='GLTF_SEPARATE',
        export_animations=False,
        export_skins=False,
        export_morph=False,
    )
    dt = time.perf_counter() - t0
    assert dt < 30.0, f"glTF export took too long: {dt:.2f} s"

    with open(out_gltf, 'r', encoding='utf-8') as f:
        gltf_json = json.load(f)

    # Check primitives for leaked attributes
    for mesh in gltf_json.get('meshes', []):
        for prim in mesh.get('primitives', []):
            attrs = prim.get('attributes', {})
            for attr_name in attrs:
                assert visibility_core.ORIG_FACE_ATTR_NAME not in attr_name, f"Attribute leaked: {attr_name}"
                assert "fss_orig" not in attr_name.lower(), f"Attribute leaked: {attr_name}"

    # Check nodes and scene for leaked extras
    gltf_str = json.dumps(gltf_json)
    assert visibility_core.ORIG_FACE_ATTR_NAME not in gltf_str, "Leaked attribute found in JSON"
    print(f"PASS: test_gltf_leak_check (export took {dt:.2f}s)")


# ---------------------------------------------------------------------------
# Test 9: Packer Interface Function & Cache Verification (200 Calls)
# ---------------------------------------------------------------------------

def test_packer_interface_and_cache():
    """Verify get_object_visibility returns Decision 82 values and reuses cache across 200 calls."""
    blend_path = SCRATCH_DIR / "packer_test.blend"
    build_synthetic_scene(blend_path)

    visibility.sync_camera_list(bpy.context.scene)
    bpy.context.scene.fss_visibility.cameras[0].include = True
    bpy.ops.fss.update_visibility()

    obj12 = bpy.data.objects["CASE12_PARTLY_HIDDEN_OBJ"]

    # 1. Basic interface verification
    res12 = visibility_core.get_object_visibility(obj12)
    assert not res12['stale'], "Object must not be stale"
    assert res12['object_name'] == "CASE12_PARTLY_HIDDEN_OBJ"
    assert len(res12['island_values']) > 0, "No island values returned"
    assert 0 in res12['island_values']
    isl_val = res12['island_values'][0]
    assert isl_val >= 0.80, f"Partly hidden island value too low: {isl_val}"
    assert len(res12['face_scores']) == len(obj12.data.polygons)

    # 2. Cache verification: 200 calls read the file from disk exactly once
    visibility_core.clear_file_cache()
    c_start = visibility_core.get_file_load_count()

    cached_results = []
    for _ in range(200):
        res = visibility_core.get_object_visibility(obj12)
        cached_results.append(res)

    loads = visibility_core.get_file_load_count() - c_start
    assert loads == 1, f"Expected file to be read exactly once in 200 calls, got {loads} loads"

    # 3. Uncached call verification: results must equal cached call
    uncached = visibility_core.get_object_visibility(obj12, use_cache=False)
    first_cached = cached_results[0]

    assert first_cached['object_name'] == uncached['object_name']
    assert first_cached['stale'] == uncached['stale']
    assert first_cached['never_seen'] == uncached['never_seen']
    assert first_cached['undetermined'] == uncached['undetermined']
    assert abs(first_cached['object_score'] - uncached['object_score']) < 1e-6
    assert first_cached['island_values'] == uncached['island_values']
    np.testing.assert_array_equal(first_cached['face_scores'], uncached['face_scores'])
    np.testing.assert_array_equal(first_cached['face_undetermined'], uncached['face_undetermined'])
    np.testing.assert_array_equal(first_cached['face_never_seen'], uncached['face_never_seen'])

    # 4. score_face_set verification
    isl0_faces = np.flatnonzero(first_cached['face_scores'] >= 0.0)
    score_set = visibility_core.score_face_set(obj12, isl0_faces, vis_data=first_cached)
    assert abs(score_set - isl_val) < 1e-6, f"score_face_set ({score_set}) != island_values[0] ({isl_val})"

    score_set_direct = visibility_core.score_face_set(obj12, isl0_faces)
    assert abs(score_set_direct - isl_val) < 1e-6, "score_face_set direct mismatch"

    assert visibility_core.score_face_set(obj12, []) == 0.0
    assert visibility_core.score_face_set(None, [0]) == 1.0

    print(f"PASS: test_packer_interface_and_cache (200 calls, {loads} disk load)")


def _quad(me_verts, me_faces, centre, angle_deg, half=0.3):
    """Vertices of a square at centre whose normal is the direction to the origin turned by angle_deg about Z."""
    c = Vector(centre)
    to_eye = -c.normalized()
    normal = Matrix.Rotation(math.radians(angle_deg), 3, 'Z') @ to_eye
    v = Vector((0, 0, 1))
    u = v.cross(normal)
    start = len(me_verts)
    me_verts += [tuple(c + half * (a * u + b * v)) for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    me_faces.append(tuple(range(start, start + 4)))


def _facing_object(name, quads, material):
    verts, faces = [], []
    for centre, angle, half in quads:
        _quad(verts, faces, centre, angle, half)
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    layer = me.uv_layers.new(name='UVMap')
    layer.data.foreach_set('uv', [c for _f in faces for xy in ((0, 0), (.1, 0), (.1, .1), (0, .1)) for c in xy])
    me.materials.append(material)
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def test_facing():
    """Facing per face from a real analysis, the file with and without it, and what the packer does with it."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    material = bpy.data.materials.new('FACING')
    cam = bpy.data.objects.new('CAM', bpy.data.cameras.new('CAM'))
    scene.collection.objects.link(cam)
    _facing_object('DIRECT', [((0, -3, 0), 0, 0.3)], material)
    _facing_object('ANGLED', [((-2.5, -2.5, 0), 60, 0.3)], material)
    _facing_object('BACK', [((2.5, -2.5, 0), 180, 0.3)], material)
    _facing_object('HIDDEN', [((0, 3, 0), 0, 0.3)], material)
    _facing_object('BLOCK', [((0, 1.5, 0), 0, 1.0)], material)
    _facing_object('BOTH', [((3, 2, 0), 0, 0.3), ((3, 3.5, 0), 180, 0.3)], material)
    blend_path = SCRATCH_DIR / 'facing.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    objects = {name: bpy.data.objects[name] for name in ('DIRECT', 'ANGLED', 'BACK', 'HIDDEN', 'BOTH')}
    scene = bpy.context.scene
    cameras = [{'name': 'CAM', 'type': 'LOOK_AROUND', 'pos': Vector((0, 0, 0)), 'forward': Vector((0, -1, 0)), 'obj_name': 'CAM'}]
    results = visibility_core.analyze_visibility(blend_path=blend_path, cameras=cameras, anim_states=(0.0,))
    visibility_core.save_visibility_file(blend_path, results)
    visibility_core.clear_file_cache()

    def face_facing(name):
        return visibility_core.get_object_visibility(objects[name])['face_facing']

    assert abs(face_facing('DIRECT')[0] - 1.0) < 0.02, face_facing('DIRECT')
    assert abs(face_facing('ANGLED')[0] - 0.5) < 0.05, face_facing('ANGLED')
    assert face_facing('BACK')[0] == 0.0 and face_facing('HIDDEN')[0] == 0.0, (face_facing('BACK'), face_facing('HIDDEN'))
    data = visibility_core.get_object_visibility(objects['BOTH'])
    assert data['face_scores'][0] > 0 and data['face_scores'][1] == 0, data['face_scores']
    # one seen face and one back face of the same size: the score only knows the seen one, facing knows both
    alone = visibility_core.score_face_set(objects['BOTH'], [0], vis_data=data)
    assert alone > 0 and visibility_core.score_face_set(objects['BOTH'], [0, 1], vis_data=data) == alone
    half = visibility_core.facing_face_set(data, [0, 1])
    assert 0.4 < half < 0.52, half

    # The packer: facing moves the top of the range towards the minimum, and Pack gives exactly that density
    scene.fss_uv_density_freedom_min, scene.fss_uv_density_freedom_max = 0.5, 1.5
    target = scene.fss_uv_target_density
    material = bpy.data.materials['FACING']

    def rows():
        parts, _conflicts = uv_pack.gather(bpy.context.view_layer, material)
        ts = uv_pack.TextureSet(material, parts, scene, {})
        return ts, {p[1][0].name: ts.face_isl[i][0] for i, p in enumerate(parts)}

    ts, island = rows()
    assert not ts.no_facing_meshes, ts.no_facing_meshes
    k = island['DIRECT']
    assert abs(ts.lo[k] - target * 0.5 * ts.vis[k]) < 1e-3 and abs(ts.hi[k] - target * 1.5 * ts.vis[k]) < 0.05 * target, (ts.lo[k], ts.hi[k])
    k = island['ANGLED']
    assert abs((ts.hi[k] - ts.lo[k]) / (target * ts.vis[k]) - 0.5) < 0.05, (ts.lo[k], ts.hi[k])
    k = island['BACK']
    assert ts.hi[k] == ts.lo[k] and abs(ts.lo[k] - target * 0.5 * 0.1) < 1e-3, (ts.lo[k], ts.hi[k])
    result = uv_pack.pack(material)
    assert result['t'] == 1.0 and result['no_facing_meshes'] == 0, result
    ts, island = rows()
    for name in ('DIRECT', 'BACK'):
        k = island[name]
        assert abs(ts.cur[k] - ts.hi[k]) < 1e-2 * ts.hi[k], (name, ts.cur[k], ts.hi[k])

    # An equal minimum and maximum: facing has no effect
    scene.fss_uv_density_freedom_min, scene.fss_uv_density_freedom_max = 1.0, 1.0
    ts, island = rows()
    assert abs(ts.lo - ts.hi).max() < 1e-6

    # A file written before facing existed: every island keeps the whole range, and the result says so
    scene.fss_uv_density_freedom_min, scene.fss_uv_density_freedom_max = 0.5, 1.5
    for m_data in results['mesh_arrays'].values():
        del m_data['face_facing']
    visibility_core.save_visibility_file(blend_path, results)
    visibility_core.clear_file_cache()
    ts, island = rows()
    k = island['BACK']
    assert ts.no_facing_meshes and abs(ts.hi[k] - 3 * ts.lo[k]) < 1e-3, (ts.lo[k], ts.hi[k])
    assert uv_pack.measure(material)['no_facing_meshes'] >= 5
    assert visibility_core.facing_face_set({'face_facing': None}, [0]) == 1.0
    print("PASS: test_facing (facing 1.0 direct, 0.5 at 60 degrees, 0 at the back and hidden, about 0.5 for half and half; "
          "the top of the range follows it, Pack meets it, equal min and max and an old file unchanged)")


def _strip(name, x_from, x_to, y, count, z=0.0, half_height=0.3):
    """A strip of `count` quads along X at distance y in front of the camera, facing it (+Y)."""
    verts, faces = [], []
    for i in range(count + 1):
        x = x_from + (x_to - x_from) * i / count
        verts += [(x, y, z + half_height), (x, y, z - half_height)]
    for i in range(count):
        a = 2 * i
        faces.append((a, a + 2, a + 3, a + 1))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.uv_layers.new(name='UVMap')
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def test_fixed_view_frame():
    """A fixed view counts its own frame: out of frame lowers nothing, hidden still does. And the camera button."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    cam_data = bpy.data.cameras.new('CAM')
    cam_data.lens = 28.0  # half width 36 / 2 / 28 = 0.643 per metre: 1.93 m at 3 m
    cam = bpy.data.objects.new('CAM', cam_data)
    cam.rotation_euler = (math.radians(90), 0, math.radians(180))
    scene.collection.objects.link(cam)
    _strip('ACROSS', 0.0, 4.0, -3.0, 40)  # across the frame's edge: about half inside
    _strip('INSIDE', -1.5, -0.5, -3.0, 20, z=0.5, half_height=0.2)
    _strip('BEHIND', -1.5, -0.5, -3.0, 1, z=-0.5, half_height=0.2)  # one face, half of it hidden by BLOCK
    _strip('BLOCK', -0.5, -0.25, -1.5, 3, z=-0.25, half_height=0.2)
    _strip('OUT', 20.0, 21.0, -3.0, 4)  # nowhere near the frame
    bpy.context.view_layer.update()  # the camera's world matrix
    blend_path = SCRATCH_DIR / 'fixed_frame.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    scene = bpy.context.scene
    cameras = [{'name': 'CAM', 'type': 'FIXED_VIEW', 'pos': Vector((0, 0, 0)), 'forward': Vector((0, -1, 0)), 'obj_name': 'CAM'}]
    results = visibility_core.analyze_visibility(blend_path=blend_path, cameras=cameras, anim_states=(0.0,))
    visibility_core.save_visibility_file(blend_path, results)
    visibility_core.clear_file_cache()

    def values(name):
        obj = bpy.data.objects[name]
        data = visibility_core.get_object_visibility(obj)
        faces = np.arange(len(obj.data.polygons))
        return data, visibility_core.score_face_set(obj, faces, vis_data=data)

    data, inside = values('INSIDE')
    assert inside > 0.95, inside
    data, across = values('ACROSS')
    assert across > 0.95, across  # 0.48 when the part out of frame still counted
    assert data['face_facing'][:15].min() > 0.5 and data['face_facing'][-15:].max() == 0.0, data['face_facing']
    _data, behind = values('BEHIND')
    assert 0.25 < behind < 0.8, behind  # really hidden still lowers it
    data, out = values('OUT')
    assert out == 0.0 and data['face_facing'].max() == 0.0, (out, data['face_facing'])

    # The camera button
    visibility.sync_camera_list(scene)
    cam = bpy.data.objects['CAM']
    other = bpy.data.objects['INSIDE']
    other.select_set(True)
    assert bpy.ops.fss.visibility_select_camera(camera_name='CAM') == {'FINISHED'}
    assert bpy.context.view_layer.objects.active == cam and cam.select_get() and not other.select_get()
    cam.hide_set(True)
    assert bpy.ops.fss.visibility_select_camera(camera_name='CAM') == {'FINISHED'} and cam.select_get()
    # In a collection that is off in the view layer: nothing changes, the collection stays off
    refs = bpy.data.collections.new('REFS')
    scene.collection.children.link(refs)
    off = bpy.data.objects.new('CAM_OFF', bpy.data.cameras.new('CAM_OFF'))
    refs.objects.link(off)
    layer = bpy.context.view_layer.layer_collection.children['REFS']
    layer.exclude = True
    assert bpy.ops.fss.visibility_select_camera(camera_name='CAM_OFF') == {'CANCELLED'}
    assert layer.exclude and bpy.context.view_layer.objects.active == cam
    assert bpy.ops.fss.visibility_select_camera(camera_name='NO_SUCH') == {'CANCELLED'}
    print(f"PASS: test_fixed_view_frame (across the edge {across:.2f}, inside {inside:.2f}, half hidden {behind:.2f}, out of "
          "frame never seen; the camera button selects, shows a hidden camera, and leaves a collection that is off alone)")


def test_look_limits():
    """Look Around limits: what they leave out, the full default unchanged, the operator and the sphere."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    material = bpy.data.materials.new('LIMITS')
    cam = bpy.data.objects.new('CAM', bpy.data.cameras.new('CAM'))
    cam.rotation_euler = (math.radians(90), 0, math.radians(180))  # looks along -Y
    scene.collection.objects.link(cam)
    _facing_object('FRONT', [((0, -3, 0), 0, 0.3)], material)
    _facing_object('SIDE', [((3, 0, 0), 0, 0.3)], material)
    _facing_object('REAR', [((0, 3, 0), 0, 0.3)], material)
    _facing_object('HIGH', [((0, -1.5, 2.6), 0, 0.2)], material)  # 60 degrees up
    _strip('ACROSS', 0.0, 6.0, -3.0, 60, z=-1.0)  # 0 to 63 degrees to the side
    bpy.context.view_layer.update()
    blend_path = SCRATCH_DIR / 'look_limits.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    scene = bpy.context.scene

    def run(**limits):
        camera = dict({'name': 'CAM', 'type': 'LOOK_AROUND', 'pos': Vector((0, 0, 0)), 'forward': Vector((0, -1, 0)), 'obj_name': 'CAM'}, **limits)
        arrays = visibility_core.analyze_visibility(blend_path=blend_path, cameras=[camera], anim_states=(0.0,))['mesh_arrays']
        return arrays

    def score(arrays, name):
        data = arrays[name]
        faces = np.arange(data['face_scores'].shape[0])
        return data, visibility_core.score_face_set(bpy.data.objects[name], faces, vis_data=dict(
            stale=False, face_scores=data['face_scores'], orig_areas=np.asarray(data['area'], np.float32), vis_omega=data['vis_omega'],
            unocc_omega=data['unocc_omega'], omega_threshold=10.0 * 4.0 / (1024 * 1024)))

    full = run()
    same = run(yaw_limit=180.0, pitch_limit=90.0)
    for name in full:
        np.testing.assert_array_equal(full[name]['vis_omega'], same[name]['vis_omega'])
        np.testing.assert_array_equal(full[name]['unocc_omega'], same[name]['unocc_omega'])
    for name in ('FRONT', 'SIDE', 'REAR', 'HIGH'):
        assert score(full, name)[1] > 0, name
    limited = run(yaw_limit=45.0, pitch_limit=30.0)
    front_full, front_limited = score(full, 'FRONT')[1], score(limited, 'FRONT')[1]
    assert abs(front_full - front_limited) < 1e-3, (front_full, front_limited)
    for name in ('SIDE', 'REAR', 'HIGH'):
        data, value = score(limited, name)
        assert value == 0.0 and data['face_facing'].max() == 0.0, (name, value, data['face_facing'])
    across_full = score(full, 'ACROSS')[1]
    data, across = score(limited, 'ACROSS')
    # beyond the limit: never seen, and it no longer lowers what the head can see
    assert across > across_full and data['face_scores'][-10:].max() == 0.0 and data['face_scores'][:10].min() > 0.5, (across, across_full)

    # Through the panel's settings: the limits reach the analysis and the file, and survive a list rebuild
    visibility.sync_camera_list(scene)
    settings = scene.fss_visibility
    item = settings.cameras[0]
    item.include, item.mode, item.yaw_limit, item.pitch_limit = True, 'LOOK_AROUND', 45, 30
    settings.states = 2
    visibility.sync_camera_list(scene)
    item = settings.cameras[0]
    assert (item.yaw_limit, item.pitch_limit) == (45, 30)
    assert bpy.ops.fss.update_visibility() == {'FINISHED'}
    visibility_core.clear_file_cache()
    meta, _data, _stale = visibility_core.load_visibility_file(blend_path.with_suffix('.visibility'), use_cache=False)
    assert meta['settings']['cameras'][0]['yaw_limit'] == 45 and meta['views'][0]['pitch_limit'] == 30.0, meta['settings']
    assert visibility_core.get_object_visibility(bpy.data.objects['REAR'])['face_scores'].max() == 0.0
    assert '45 left/right, 30 up/down' in bpy.data.texts[visibility.REPORT_TEXT_NAME].as_string()

    # The sphere: on its radius, inside its angles, only for an included Look Around camera on the selected row
    grid, edges = visibility_core.sphere_lines(45, 30, 1.0)
    assert abs(np.linalg.norm(grid, axis=1) - 1.0).max() < 1e-5 and abs(np.linalg.norm(edges[2:], axis=1) - 1.0).max() < 1e-5
    assert len(grid) % 2 == 0 and len(edges) % 2 == 0
    assert np.abs(np.degrees(np.arctan2(grid[:, 0], -grid[:, 2]))).max() < 45.01 and np.abs(np.degrees(np.arcsin(grid[:, 1]))).max() < 30.01
    assert len(visibility_core.sphere_lines(180, 90)[1]) == 2  # no cut: the forward line only
    (camera, yaw, pitch, selected), = visibility.look_sphere_cameras(scene)
    assert (camera.name, yaw, pitch, selected) == ('CAM', 45, 30, True)
    world_grid, world_edges = visibility.look_sphere_world_lines(camera, yaw, pitch)
    assert abs(world_edges[0]).max() < 1e-5 and abs(world_edges[1] - np.array([0, -1, 0])).max() < 1e-4, world_edges[:2]
    # The drawing itself runs (a 3D view is not there to look at: the shader and the batches, into an offscreen)
    import gpu
    gpu.init()
    offscreen = gpu.types.GPUOffScreen(64, 64)
    with offscreen.bind():
        visibility._draw_look_sphere()
    offscreen.free()
    item.mode = 'FIXED_VIEW'
    assert visibility.look_sphere_cameras(scene) == []
    item.mode, item.include = 'LOOK_AROUND', False
    assert visibility.look_sphere_cameras(scene) == []
    item.include, settings.show_look_sphere = True, False
    assert visibility.look_sphere_cameras(scene) == []
    print(f"PASS: test_look_limits (full default unchanged; beyond 45 and 30 degrees never seen; across the limit {across_full:.2f} to "
          f"{across:.2f}; in the file and the report; the sphere on its radius and angles, drawn only when it should)")


def test_unviewable_faces():
    """A face no view can show scores 0, also when small and connected to visible faces; small visible faces still borrow."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    bpy.data.objects.new('CAM', bpy.data.cameras.new('CAM'))
    scene.collection.objects.link(bpy.data.objects['CAM'])
    me = bpy.data.meshes.new('BOX')
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=0.1)
    bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=7, use_grid_fill=True)
    bm.to_mesh(me)
    bm.free()
    me.uv_layers.new(name='UVMap')
    box = bpy.data.objects.new('BOX', me)
    box.location = (0, -3, 0)
    scene.collection.objects.link(box)
    bpy.context.view_layer.update()
    blend_path = SCRATCH_DIR / 'unviewable.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    cameras = [{'name': 'CAM', 'type': 'LOOK_AROUND', 'pos': Vector((0, 0, 0)), 'forward': Vector((0, -1, 0)), 'obj_name': 'CAM'}]
    results = visibility_core.analyze_visibility(blend_path=blend_path, cameras=cameras, anim_states=(0.0,))
    data = results['mesh_arrays']['BOX']
    me = bpy.data.objects['BOX'].data
    normals = np.array([p.normal for p in me.polygons])
    front = normals[:, 1] > 0.9
    assert front.sum() == 64 and len(normals) == 384, (front.sum(), len(normals))
    unocc = data['unocc_omega'].max(axis=(0, 1))
    assert unocc[front].max() < 10.0 * 4.0 / (1024 * 1024), unocc[front].max()  # too small to measure alone
    assert data['face_scores'][front].min() > 0.5, data['face_scores'][front].min()  # they still borrow
    assert data['face_scores'][~front].max() == 0.0 and data['face_never_seen'][~front].all(), data['face_scores'][~front].max()
    assert data['face_facing'][~front].max() == 0.0 and data['face_facing'][front].min() > 0.9
    print(f"PASS: test_unviewable_faces (64 small front faces borrow, score {data['face_scores'][front].min():.2f}; the 320 others score 0)")


def test_camera_weights():
    """A camera's weight lifts what the others miss and never lowers what they see; every ticked camera draws a sphere."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    material = bpy.data.materials.new('WEIGHTS')
    for name, location in (('PILOT', (0, 0, 0)), ('DOME', (1, 0, 0))):
        cam = bpy.data.objects.new(name, bpy.data.cameras.new(name))
        cam.location = location
        cam.rotation_euler = (math.radians(90), 0, math.radians(180))  # along -Y
        scene.collection.objects.link(cam)
    _facing_object('BOTH', [((-2, -3, 0), 0, 0.3)], material)  # seen by both
    _facing_object('DOME_ONLY', [((0, -3, 0), 0, 0.3)], material)  # BLOCK hides it from PILOT
    _facing_object('BLOCK', [((0, -1.5, 0), 0, 0.35)], material)
    bpy.context.view_layer.update()
    blend_path = SCRATCH_DIR / 'camera_weights.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    scene = bpy.context.scene

    def run(dome_weight):
        cameras = [
            {'name': 'PILOT', 'type': 'LOOK_AROUND', 'pos': Vector((0, 0, 0)), 'forward': Vector((0, -1, 0)), 'obj_name': 'PILOT'},
            {'name': 'DOME', 'type': 'LOOK_AROUND', 'pos': Vector((1, 0, 0)), 'forward': Vector((0, -1, 0)), 'obj_name': 'DOME', 'weight': dome_weight},
        ]
        return visibility_core.analyze_visibility(blend_path=blend_path, cameras=cameras, anim_states=(0.0,))['mesh_arrays']

    full, low = run(1.0), run(0.3)
    both_full, both_low = full['BOTH']['face_scores'][0], low['BOTH']['face_scores'][0]
    only_full, only_low = full['DOME_ONLY']['face_scores'][0], low['DOME_ONLY']['face_scores'][0]
    assert only_full > 0.3, only_full
    # BLOCK leaves PILOT nothing of DOME_ONLY: its score is the dome's alone, so it takes the weight
    assert abs(only_low - 0.3 * only_full) < 0.02, (only_low, only_full)
    # What PILOT sees keeps PILOT's score at any dome weight
    assert both_low > 0.5 and abs(both_low - both_full) < 0.02, (both_low, both_full)
    pilot_only = run(0.05)['BOTH']['face_scores'][0]
    assert abs(pilot_only - both_low) < 0.02, (pilot_only, both_low)
    # Facing: hidden from PILOT, so only the dome's angle counts, with its weight, not the head-on angle PILOT would have had
    facing_full, facing_low = full['DOME_ONLY']['face_facing'][0], low['DOME_ONLY']['face_facing'][0]
    assert abs(facing_low - 0.3 * facing_full) < 0.02 and facing_full < 0.99, (facing_low, facing_full)

    # Through the panel: saved, in the file, in the report, and both spheres
    visibility.sync_camera_list(scene)
    settings = scene.fss_visibility
    names = [item.camera.name for item in settings.cameras]
    dome = settings.cameras[names.index('DOME')]
    pilot = settings.cameras[names.index('PILOT')]
    assert pilot.weight == 1.0, pilot.weight  # the default leaves results as they were
    dome.include, pilot.include, dome.weight = True, True, 0.3
    settings.states = 2
    visibility.sync_camera_list(scene)
    assert abs(settings.cameras[names.index('DOME')].weight - 0.3) < 1e-5
    settings.active_camera_index = names.index('PILOT')
    assert bpy.ops.fss.update_visibility() == {'FINISHED'}
    visibility_core.clear_file_cache()
    meta, _data, _stale = visibility_core.load_visibility_file(blend_path.with_suffix('.visibility'), use_cache=False)
    saved = {row['name']: row['weight'] for row in meta['settings']['cameras']}
    assert saved['PILOT'] == 1.0 and abs(saved['DOME'] - 0.3) < 1e-5, saved
    assert 'Weight: 0.30' in bpy.data.texts[visibility.REPORT_TEXT_NAME].as_string()
    spheres = {row[0].name: row[3] for row in visibility.look_sphere_cameras(scene)}
    assert spheres == {'PILOT': True, 'DOME': False}, spheres
    gpu_mod = __import__('gpu')
    gpu_mod.init()
    offscreen = gpu_mod.types.GPUOffScreen(64, 64)
    with offscreen.bind():
        visibility._draw_look_sphere()
    offscreen.free()
    print(f"PASS: test_camera_weights (dome only {only_full:.2f} to {only_low:.2f} at weight 0.3; seen by the pilot too {both_full:.2f} and "
          f"{both_low:.2f}; facing {facing_full:.2f} to {facing_low:.2f}; saved, reported, both spheres drawn)")


# ---------------------------------------------------------------------------
# Main Runner
# ---------------------------------------------------------------------------

def main():
    print("\n" + "=" * 70)
    print("      FSS VISIBILITY TEST SUITE")
    print("=" * 70)

    test_synthetic_15_cases()
    test_operator_on_saved_scene()
    test_scene_unchanged_after_run_and_esc()
    test_disabled_states()
    test_visibility_heatmap_mode()
    test_heatmap_modifier_face_mapping()
    test_camera_renaming_and_deletion()
    test_camera_sync_after_draw()
    test_gltf_leak_check()
    test_packer_interface_and_cache()
    test_facing()
    test_fixed_view_frame()
    test_look_limits()
    test_unviewable_faces()
    test_camera_weights()

    print("\n" + "=" * 70)
    print("      ALL TESTS PASSED")
    print("=" * 70)


if __name__ == '__main__':
    main()
