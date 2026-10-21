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
from fss_blender_tools import visibility_core, visibility, uv_heatmap

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
    assert meta_loaded['schema_version'] == 4
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

    # Check file exists and has valid schema 4 + settings
    vis_file = blend_path.with_suffix('.visibility')
    assert vis_file.exists(), f"File {vis_file} was not created"
    meta, data, _ = visibility_core.load_visibility_file(vis_file, scene_meshes=bpy.data.meshes)
    assert meta['schema_version'] == 4
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

    print(f"PASS: test_packer_interface_and_cache (200 calls, {loads} disk load)")


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

    print("\n" + "=" * 70)
    print("      ALL TESTS PASSED")
    print("=" * 70)


if __name__ == '__main__':
    main()
