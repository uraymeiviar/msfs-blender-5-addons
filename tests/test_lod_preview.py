"""Unit and integration tests for viewport LOD preview by display type.

To run:
G:\\e-jets-e2\\tools\\blender\\blender.exe -b --factory-startup --python tests/test_lod_preview.py
"""

import json
import os
import shutil
import sys
from pathlib import Path

import bmesh
import bpy

# If an addons_core copy was loaded during Blender startup, unregister and purge it
if 'fss_blender_tools' in sys.modules:
    try:
        sys.modules['fss_blender_tools'].unregister()
    except Exception:
        pass
    for mod in list(sys.modules.keys()):
        if mod == 'fss_blender_tools' or mod.startswith('fss_blender_tools.'):
            del sys.modules[mod]

REPO_ROOT = Path(__file__).resolve().parents[1]
repo_root_str = str(REPO_ROOT)
while repo_root_str in sys.path:
    sys.path.remove(repo_root_str)
sys.path.insert(0, repo_root_str)

import fss_blender_tools
from fss_blender_tools import lod, lod_model, uv_heatmap

# Register repository add-on
fss_blender_tools.register()

SCRATCH_DIR = REPO_ROOT / 'tests' / '_work' / 'lod_preview_scratch'


def clean_scene():
    """Reset to an empty scene with unit settings matching production."""
    bpy.ops.wm.read_homefile(use_empty=True)
    if not bpy.data.scenes:
        bpy.data.scenes.new("Scene")
    scene = bpy.context.scene
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.scale_length = 1.0
    scene.fss_viewport_lod = -1
    scene.fss_viewport_lod_auto = False
    scene.fss_lod_preview_display = 'BOUNDS'  # most tests check the bounds preview; the hidden one has its own
    return scene


def create_mesh_cube(name, size=1.0, location=(0, 0, 0), display_type='TEXTURED'):
    """Create a cube mesh object with UVs and material."""
    me = bpy.data.meshes.new(name + "_Mesh")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=size)
    uv_layer = bm.loops.layers.uv.new("UVMap")
    for face in bm.faces:
        for loop in face.loops:
            loop[uv_layer].uv = (0.5, 0.5)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    obj.location = location
    obj.display_type = display_type
    bpy.context.scene.collection.objects.link(obj)
    mat = bpy.data.materials.new(name + "_Mat")
    obj.data.materials.append(mat)
    return obj


def test_preview_active_bounds_and_visibility():
    """Verify absent objects get display_type 'BOUNDS', visible_get() stays True, and no hide_set."""
    print("Test 1: Preview active sets absent objects to BOUNDS, visible_get() True, no hide_set...")
    clean_scene()
    keep = create_mesh_cube("Keep_Obj", size=2.0, display_type='TEXTURED')
    keep['fss_lod_keep'] = 1

    solid = create_mesh_cube("Absent_Solid", size=0.2, display_type='SOLID')
    solid['fss_lod'] = 1

    wire = create_mesh_cube("Absent_Wire", size=0.2, display_type='WIRE')
    wire['fss_lod'] = 1

    bounds = create_mesh_cube("Absent_Bounds", size=0.2, display_type='BOUNDS')
    bounds['fss_lod'] = 1

    textured = create_mesh_cube("Absent_Textured", size=0.2, display_type='TEXTURED')
    textured['fss_lod'] = 1

    user_hidden = create_mesh_cube("User_Hidden", size=0.2, display_type='SOLID')
    user_hidden['fss_lod'] = 1
    user_hidden.hide_set(True, view_layer=bpy.context.view_layer)

    bpy.context.scene.fss_viewport_lod = 1
    lod.apply_viewport_lod(bpy.context)

    # Keep object is present in LOD 1
    assert keep.display_type == 'TEXTURED', f"Expected TEXTURED, got {keep.display_type}"
    assert keep.visible_get(view_layer=bpy.context.view_layer) is True
    assert '_fss_lod_hidden' not in keep

    # Absent visible objects must be display_type 'BOUNDS'
    for obj, orig_type in ((solid, 'SOLID'), (wire, 'WIRE'), (bounds, 'BOUNDS'), (textured, 'TEXTURED')):
        assert obj.display_type == 'BOUNDS', f"{obj.name}: expected BOUNDS, got {obj.display_type}"
        assert obj.visible_get(view_layer=bpy.context.view_layer) is True, f"{obj.name}: visible_get should be True"
        assert obj.hide_get(view_layer=bpy.context.view_layer) is False, f"{obj.name}: hide_get should be False"
        assert obj.get('_fss_lod_hidden') == orig_type, f"{obj.name}: expected recorded {orig_type}, got {obj.get('_fss_lod_hidden')}"

    # User-hidden object remains hidden and untouched
    assert user_hidden.visible_get(view_layer=bpy.context.view_layer) is False
    assert user_hidden.hide_get(view_layer=bpy.context.view_layer) is True
    assert '_fss_lod_hidden' not in user_hidden
    print("  -> PASS: All absent objects displayed as BOUNDS, visible_get() True, no hide_set called.")


def test_preview_off_restores_original_display_types():
    """Verify Off restores original display types including WIRE and BOUNDS."""
    print("Test 2: Off restores exactly the original display types...")
    clean_scene()
    keep = create_mesh_cube("Keep_Obj", size=2.0, display_type='TEXTURED')
    keep['fss_lod_keep'] = 1
    solid = create_mesh_cube("Absent_Solid", size=0.2, display_type='SOLID')
    solid['fss_lod'] = 1
    wire = create_mesh_cube("Absent_Wire", size=0.2, display_type='WIRE')
    wire['fss_lod'] = 1
    bounds = create_mesh_cube("Absent_Bounds", size=0.2, display_type='BOUNDS')
    bounds['fss_lod'] = 1
    textured = create_mesh_cube("Absent_Textured", size=0.2, display_type='TEXTURED')
    textured['fss_lod'] = 1

    # Turn preview ON
    bpy.context.scene.fss_viewport_lod = 1
    lod.apply_viewport_lod(bpy.context)
    assert solid.display_type == 'BOUNDS'
    assert wire.display_type == 'BOUNDS'
    assert bounds.display_type == 'BOUNDS'
    assert textured.display_type == 'BOUNDS'

    # Turn preview OFF
    bpy.context.scene.fss_viewport_lod = -1
    lod.apply_viewport_lod(bpy.context)

    assert keep.display_type == 'TEXTURED'
    assert solid.display_type == 'SOLID', f"Expected SOLID, got {solid.display_type}"
    assert wire.display_type == 'WIRE', f"Expected WIRE, got {wire.display_type}"
    assert bounds.display_type == 'BOUNDS', f"Expected BOUNDS, got {bounds.display_type}"
    assert textured.display_type == 'TEXTURED', f"Expected TEXTURED, got {textured.display_type}"

    for obj in (solid, wire, bounds, textured):
        assert '_fss_lod_hidden' not in obj, f"{obj.name} still has _fss_lod_hidden marker"
        assert obj.visible_get(view_layer=bpy.context.view_layer) is True

    # Switching to another level and back Off
    bpy.context.scene.fss_viewport_lod = 2
    lod.apply_viewport_lod(bpy.context)
    assert wire.display_type == 'BOUNDS'

    bpy.context.scene.fss_viewport_lod = -1
    lod.apply_viewport_lod(bpy.context)
    assert wire.display_type == 'WIRE'
    print("  -> PASS: Original display types (including WIRE and BOUNDS) faithfully restored.")


def test_save_with_preview_active_and_reopen():
    """Verify saving with preview active restores before save, re-applies after, and reopen resets to Off."""
    print("Test 3: Save with preview active, reopen: original display, nothing hidden, LOD Off...")
    clean_scene()
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    test_blend = SCRATCH_DIR / "preview_active_saved.blend"

    keep = create_mesh_cube("Keep_Obj", size=2.0, display_type='TEXTURED')
    keep['fss_lod_keep'] = 1
    solid = create_mesh_cube("Absent_Solid", size=0.2, display_type='SOLID')
    solid['fss_lod'] = 1
    wire = create_mesh_cube("Absent_Wire", size=0.2, display_type='WIRE')
    wire['fss_lod'] = 1
    bounds = create_mesh_cube("Absent_Bounds", size=0.2, display_type='BOUNDS')
    bounds['fss_lod'] = 1

    # Activate preview level 1
    bpy.context.scene.fss_viewport_lod = 1
    lod.apply_viewport_lod(bpy.context)
    assert solid.display_type == 'BOUNDS'
    assert wire.display_type == 'BOUNDS'

    # Save to disk
    bpy.ops.wm.save_as_mainfile(filepath=str(test_blend))

    # In memory after save, save_post re-applies preview
    assert bpy.context.scene.fss_viewport_lod == 1
    assert solid.display_type == 'BOUNDS'
    assert wire.display_type == 'BOUNDS'

    # Reopen saved file
    bpy.ops.wm.open_mainfile(filepath=str(test_blend))

    # load_post resets viewport LOD to -1 and cleans markers
    scene = bpy.context.scene
    assert scene.fss_viewport_lod == -1, f"Expected fss_viewport_lod -1 on reopen, got {scene.fss_viewport_lod}"

    s_solid = bpy.data.objects.get("Absent_Solid")
    s_wire = bpy.data.objects.get("Absent_Wire")
    s_bounds = bpy.data.objects.get("Absent_Bounds")
    s_keep = bpy.data.objects.get("Keep_Obj")

    assert s_solid is not None and s_solid.display_type == 'SOLID', f"Absent_Solid: expected SOLID, got {getattr(s_solid, 'display_type', None)}"
    assert s_wire is not None and s_wire.display_type == 'WIRE', f"Absent_Wire: expected WIRE, got {getattr(s_wire, 'display_type', None)}"
    assert s_bounds is not None and s_bounds.display_type == 'BOUNDS', f"Absent_Bounds: expected BOUNDS, got {getattr(s_bounds, 'display_type', None)}"
    assert s_keep is not None and s_keep.display_type == 'TEXTURED'

    for obj in (s_solid, s_wire, s_bounds, s_keep):
        assert '_fss_lod_hidden' not in obj
        assert obj.visible_get(view_layer=bpy.context.view_layer) is True
        assert obj.hide_get(view_layer=bpy.context.view_layer) is False

    print("  -> PASS: File saved clean; reopen shows original display types, nothing hidden, LOD Off.")


def test_legacy_file_cleaned_on_open():
    """Verify a file saved by earlier versions (hidden objects, _fss_lod_hidden=True) is cleaned on open."""
    print("Test 4: File saved by earlier versions (hidden objects and True marker) cleaned on open...")
    clean_scene()
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    legacy_blend = SCRATCH_DIR / "legacy_hidden.blend"

    obj1 = create_mesh_cube("Legacy_Visible", size=1.0)
    obj2 = create_mesh_cube("Legacy_Hidden", size=1.0)

    # Simulate old code: hidden with hide_set(True) and marked True
    obj2.hide_set(True, view_layer=bpy.context.view_layer)
    obj2[lod_model.HIDDEN_KEY] = True
    bpy.context.scene.fss_viewport_lod = 2

    # Temporarily remove save_pre handler to save the raw legacy state to disk
    save_pre_handlers = list(bpy.app.handlers.save_pre)
    bpy.app.handlers.save_pre.clear()
    try:
        bpy.ops.wm.save_as_mainfile(filepath=str(legacy_blend))
    finally:
        bpy.app.handlers.save_pre.extend(save_pre_handlers)

    # Reopen with active add-on (load_post handler fires)
    bpy.ops.wm.open_mainfile(filepath=str(legacy_blend))

    scene = bpy.context.scene
    assert scene.fss_viewport_lod == -1, f"Expected fss_viewport_lod -1, got {scene.fss_viewport_lod}"

    c_obj1 = bpy.data.objects.get("Legacy_Visible")
    c_obj2 = bpy.data.objects.get("Legacy_Hidden")

    assert c_obj1 is not None and c_obj1.visible_get(view_layer=bpy.context.view_layer) is True
    assert c_obj2 is not None, "Legacy_Hidden object missing"
    assert c_obj2.hide_get(view_layer=bpy.context.view_layer) is False, "Legacy_Hidden was not unhidden"
    assert c_obj2.visible_get(view_layer=bpy.context.view_layer) is True, "Legacy_Hidden is not visible"
    assert lod_model.HIDDEN_KEY not in c_obj2, f"{lod_model.HIDDEN_KEY} was not removed from Legacy_Hidden"
    print("  -> PASS: Legacy hidden objects unhidden and markers purged on open.")


def test_single_file_export_contains_all_objects():
    """Verify single-file export linking visible_get() objects contains every object of a cleaned legacy file."""
    print("Test 5: Single-file export (visible_get() collection) contains every object...")
    clean_scene()
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    legacy_blend = SCRATCH_DIR / "legacy_export_test.blend"
    gltf_out = SCRATCH_DIR / "single_file_export.gltf"

    create_mesh_cube("Mesh_A", size=1.0, location=(0, 0, 0))
    hidden_mesh = create_mesh_cube("Mesh_B_FormerlyHidden", size=1.0, location=(2, 0, 0))
    create_mesh_cube("Mesh_C", size=1.0, location=(4, 0, 0))

    # Old code state
    hidden_mesh.hide_set(True, view_layer=bpy.context.view_layer)
    hidden_mesh[lod_model.HIDDEN_KEY] = True
    bpy.context.scene.fss_viewport_lod = 3

    save_pre_handlers = list(bpy.app.handlers.save_pre)
    bpy.app.handlers.save_pre.clear()
    try:
        bpy.ops.wm.save_as_mainfile(filepath=str(legacy_blend))
    finally:
        bpy.app.handlers.save_pre.extend(save_pre_handlers)

    # Reopen to trigger load_post cleanup
    bpy.ops.wm.open_mainfile(filepath=str(legacy_blend))

    # Single-file export logic as in scripts/export-blend-to-gltf.py
    scene = bpy.context.scene
    export_collection = bpy.data.collections.new("FSS_EXPORT_MSFS2024")
    visible_objects = [obj for obj in scene.objects if obj.visible_get()]
    for obj in visible_objects:
        export_collection.objects.link(obj)
    scene.collection.children.link(export_collection)

    expected_names = {"Mesh_A", "Mesh_B_FormerlyHidden", "Mesh_C"}
    visible_names = {obj.name for obj in visible_objects}
    assert expected_names.issubset(visible_names), f"Missing objects in visible_get(): {expected_names - visible_names}"

    # Export to glTF and verify JSON node hierarchy
    bpy.ops.export_scene.gltf(filepath=str(gltf_out), export_format='GLTF_SEPARATE', use_visible=True)

    with open(gltf_out, 'r', encoding='utf-8') as f:
        gltf_data = json.load(f)

    exported_node_names = {node.get('name') for node in gltf_data.get('nodes', [])}
    for name in expected_names:
        assert name in exported_node_names, f"Object '{name}' not found in exported glTF nodes: {exported_node_names}"

    print("  -> PASS: All objects (including formerly hidden) successfully exported in single-file path.")


def test_heatmap_and_preview_coexistence():
    """Verify display takeover harmony: object ends with artist's display type after both tools are off."""
    print("Test 6: Heatmap and LOD preview display takeover and restoration...")
    clean_scene()
    scene = bpy.context.scene

    # Shared object with SOLID display type
    obj_solid = create_mesh_cube("Shared_Solid", size=0.5, display_type='SOLID')
    obj_solid['fss_lod'] = 1
    obj_solid.select_set(True)
    bpy.context.view_layer.objects.active = obj_solid

    # --- Sequence A: Heatmap ON -> Preview ON -> Preview OFF -> Heatmap OFF ---
    # 1. Heatmap ON
    scene.fss_uv_heatmap_show = True
    uv_heatmap._sync_display()
    assert obj_solid.display_type == 'WIRE', f"Heatmap should display WIRE, got {obj_solid.display_type}"
    assert "Shared_Solid" in uv_heatmap._display_original
    assert uv_heatmap._display_original["Shared_Solid"] == 'SOLID'

    # 2. Preview ON
    scene.fss_viewport_lod = 1
    lod.apply_viewport_lod(bpy.context)
    assert obj_solid.display_type == 'BOUNDS', f"Preview should display BOUNDS, got {obj_solid.display_type}"
    assert obj_solid.get('_fss_lod_hidden') == 'SOLID', f"Preview should record original SOLID, got {obj_solid.get('_fss_lod_hidden')}"
    assert "Shared_Solid" not in uv_heatmap._display_original, "Object should be dropped from heatmap _display_original"
    assert "Shared_Solid" not in uv_heatmap._display_active, "Object should be dropped from heatmap _display_active"

    # Heatmap sync while preview is active: leaves BOUNDS alone
    uv_heatmap._sync_display()
    assert obj_solid.display_type == 'BOUNDS'

    # 3. Preview OFF: preview restores to SOLID; heatmap immediately re-takes over as WIRE on depsgraph update
    scene.fss_viewport_lod = -1
    lod.apply_viewport_lod(bpy.context)
    assert '_fss_lod_hidden' not in obj_solid
    assert obj_solid.display_type == 'WIRE', f"Heatmap should re-take over as WIRE, got {obj_solid.display_type}"
    assert "Shared_Solid" in uv_heatmap._display_original
    assert uv_heatmap._display_original["Shared_Solid"] == 'SOLID'

    # 4. Heatmap OFF
    scene.fss_uv_heatmap_show = False
    uv_heatmap._sync_display()
    assert obj_solid.display_type == 'SOLID', f"Expected final SOLID, got {obj_solid.display_type}"

    # --- Sequence B: Heatmap ON -> Preview ON -> Heatmap OFF -> Preview OFF ---
    obj_solid.display_type = 'SOLID'
    scene.fss_uv_heatmap_show = True
    uv_heatmap._sync_display()
    assert obj_solid.display_type == 'WIRE'

    scene.fss_viewport_lod = 1
    lod.apply_viewport_lod(bpy.context)
    assert obj_solid.display_type == 'BOUNDS'

    scene.fss_uv_heatmap_show = False
    uv_heatmap._sync_display()
    # Still owned by preview
    assert obj_solid.display_type == 'BOUNDS'

    scene.fss_viewport_lod = -1
    lod.apply_viewport_lod(bpy.context)
    assert obj_solid.display_type == 'SOLID', f"Expected final SOLID, got {obj_solid.display_type}"

    # --- Sequence C: Artist authored WIRE originally ---
    obj_solid.select_set(False)
    obj_wire = create_mesh_cube("Shared_Wire", size=0.5, display_type='WIRE')
    obj_wire['fss_lod'] = 1
    obj_wire.select_set(True)
    bpy.context.view_layer.objects.active = obj_wire

    scene.fss_uv_heatmap_show = True
    uv_heatmap._sync_display()
    assert obj_wire.display_type == 'WIRE'
    assert "Shared_Wire" not in uv_heatmap._display_original  # artist choice ignored by heatmap

    scene.fss_viewport_lod = 1
    lod.apply_viewport_lod(bpy.context)
    assert obj_wire.display_type == 'BOUNDS'
    assert obj_wire.get('_fss_lod_hidden') == 'WIRE'

    scene.fss_viewport_lod = -1
    lod.apply_viewport_lod(bpy.context)
    assert obj_wire.display_type == 'WIRE'

    scene.fss_uv_heatmap_show = False
    uv_heatmap._sync_display()
    assert obj_wire.display_type == 'WIRE'

    # --- Sequence D: Artist authored BOUNDS originally ---
    obj_wire.select_set(False)
    obj_bounds = create_mesh_cube("Shared_Bounds", size=0.5, display_type='BOUNDS')
    obj_bounds['fss_lod'] = 1
    obj_bounds.select_set(True)
    bpy.context.view_layer.objects.active = obj_bounds

    scene.fss_uv_heatmap_show = True
    uv_heatmap._sync_display()
    assert obj_bounds.display_type == 'BOUNDS'

    scene.fss_viewport_lod = 1
    lod.apply_viewport_lod(bpy.context)
    assert obj_bounds.display_type == 'BOUNDS'
    assert obj_bounds.get('_fss_lod_hidden') == 'BOUNDS'

    scene.fss_viewport_lod = -1
    lod.apply_viewport_lod(bpy.context)
    assert obj_bounds.display_type == 'BOUNDS'

    scene.fss_uv_heatmap_show = False
    uv_heatmap._sync_display()
    assert obj_bounds.display_type == 'BOUNDS'

    print("  -> PASS: All combinations of heatmap and preview takeover restore artist's display type.")


def test_hidden_preview_saved_clean():
    """The default Hidden preview hides absent objects in the session, but a saved file keeps every object visible."""
    print("Test 7: Hidden preview: hidden in the session, saved file clean, single-file export complete...")
    clean_scene()
    scene = bpy.context.scene
    scene.fss_lod_preview_display = 'HIDDEN'
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    path = SCRATCH_DIR / "hidden_preview_saved.blend"
    keep = create_mesh_cube("Keep", size=2.0)
    absent = create_mesh_cube("Absent", size=0.2, location=(3, 0, 0), display_type='SOLID')
    absent['fss_lod'] = 1
    scene.fss_viewport_lod = 1
    lod.apply_viewport_lod(bpy.context)
    assert not absent.visible_get() and absent.display_type == 'SOLID', "Hidden mode hides, display type untouched"
    assert keep.visible_get()

    bpy.ops.wm.save_as_mainfile(filepath=str(path))
    assert not absent.visible_get(), "after saving, the preview is re-applied in the session"
    bpy.ops.wm.open_mainfile(filepath=str(path))
    scene = bpy.context.scene
    names = {obj.name for obj in scene.objects if obj.visible_get()}
    assert {"Keep", "Absent"} <= names, f"saved file must keep every object visible, visible: {names}"
    assert scene.fss_viewport_lod == -1
    assert lod_model.HIDDEN_KEY not in bpy.data.objects["Absent"], "no preview marker in the saved file"
    print("  -> PASS: hidden in the session, every object visible in the saved file.")


def main():
    print("=" * 70)
    print("RUNNING VIEWPORT LOD PREVIEW & DISPLAY TAKEOVER TESTS")
    print("=" * 70)
    try:
        test_preview_active_bounds_and_visibility()
        test_preview_off_restores_original_display_types()
        test_save_with_preview_active_and_reopen()
        test_legacy_file_cleaned_on_open()
        test_single_file_export_contains_all_objects()
        test_heatmap_and_preview_coexistence()
        test_hidden_preview_saved_clean()
        print("=" * 70)
        print("ALL LOD PREVIEW TESTS PASSED SUCCESSFULLY.")
        print("=" * 70)
    finally:
        if SCRATCH_DIR.exists():
            shutil.rmtree(SCRATCH_DIR, ignore_errors=True)


if __name__ == '__main__':
    main()
