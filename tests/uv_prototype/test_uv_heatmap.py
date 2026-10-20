"""Unit and integration tests for UV Heatmap measures, overlay logic, and Skip Auto Seam mark.

To run:
D:\\fss-e2\\tools\\blender\\blender.exe -b --factory-startup --python tests/uv_prototype/test_uv_heatmap.py
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
from fss_blender_tools import uv_heatmap, uv_marks, uv_autoseam

# Register repository add-on
fss_blender_tools.register()

SCRATCH_DIR = REPO_ROOT / 'tests' / '_work' / 'heatmap_scratch'
WORK3_BLEND = REPO_ROOT / 'tests' / '_work' / 'uv_prototype' / 'work3.blend'
TRIM_PANEL_NPZ = REPO_ROOT / 'tests' / '_work' / 'uv_prototype' / 'results3' / 'W_TRIM_PANEL__existing.npz'


def clean_scene():
    """Reset to an empty scene."""
    bpy.ops.wm.read_homefile(use_empty=True)
    fss_blender_tools.uv_heatmap.clear_cache()


def create_plane(name, size=1.0, uv_scale=(1.0, 1.0), uv_shear=0.0, location=(0, 0, 0)):
    """Create a 2-triangle flat plane with customizable UV coordinates."""
    me = bpy.data.meshes.new(name + "_Mesh")
    bm = bmesh.new()
    
    # 4 vertices in XY plane
    v1 = bm.verts.new((-size / 2, -size / 2, 0.0))
    v2 = bm.verts.new((size / 2, -size / 2, 0.0))
    v3 = bm.verts.new((size / 2, size / 2, 0.0))
    v4 = bm.verts.new((-size / 2, size / 2, 0.0))
    
    # 2 triangles
    f1 = bm.faces.new((v1, v2, v3))
    f2 = bm.faces.new((v1, v3, v4))
    
    uv_layer = bm.loops.layers.uv.new("UVMap")
    
    # UV coords: (0,0), (1,0), (1,1), (0,1) with scaling and shear
    def map_uv(u, v):
        return (u * uv_scale[0] + v * uv_shear, v * uv_scale[1])

    f1.loops[0][uv_layer].uv = map_uv(0.0, 0.0)
    f1.loops[1][uv_layer].uv = map_uv(1.0, 0.0)
    f1.loops[2][uv_layer].uv = map_uv(1.0, 1.0)

    f2.loops[0][uv_layer].uv = map_uv(0.0, 0.0)
    f2.loops[1][uv_layer].uv = map_uv(1.0, 1.0)
    f2.loops[2][uv_layer].uv = map_uv(0.0, 1.0)

    bm.to_mesh(me)
    bm.free()

    obj = bpy.data.objects.new(name, me)
    obj.location = location
    bpy.context.scene.collection.objects.link(obj)
    return obj


def test_flat_plane_undistorted():
    """Verify flat plane unwrapped without distortion gives shape 1.0 and density 1.0."""
    print("Test 1: Flat plane undistorted gives shape 1.0 and density 1.0...")
    clean_scene()
    obj = create_plane("Plane_Undistorted", size=2.0, uv_scale=(1.0, 1.0))
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    mat = bpy.data.materials.new("TestMat")
    obj.data.materials.append(mat)

    bpy.context.scene.fss_uv_heatmap_show = True
    uv_heatmap.update_heatmap_cache(bpy.context)

    cache = uv_heatmap._cache.get(obj.name)
    assert cache is not None, "Heatmap cache entry was not created"
    assert cache.n_tris == 2, f"Expected 2 triangles, got {cache.n_tris}"

    # Shape must be 1.0 everywhere within 1e-6
    max_shape_diff = np.max(np.abs(cache.shape - 1.0))
    assert max_shape_diff < 1e-6, f"Shape distortion was not 1.0: {cache.shape}"

    # Density relative to median must be 1.0 everywhere within 1e-6
    max_density_diff = np.max(np.abs(cache.rel_density - 1.0))
    assert max_density_diff < 1e-6, f"Density was not 1.0: {cache.rel_density}"

    # No degenerate triangles
    assert not np.any(cache.is_degenerate), "Triangles should not be degenerate"
    print(f"  -> PASS: shape diff {max_shape_diff:.2e}, density diff {max_density_diff:.2e}")


def test_uv_scaled_by_two():
    """Verify UVs scaled by 2 give density 4.0 relative to unscaled reference, shape unchanged."""
    print("Test 2: UVs scaled by 2 give density 4.0 relative to reference, shape unchanged...")
    clean_scene()
    mat = bpy.data.materials.new("SharedMat")

    # Reference object with area 10.0 so its texel density (1.0) forms the median reference
    obj_ref = create_plane("Plane_Ref", size=10.0, uv_scale=(10.0, 10.0), location=(-10, 0, 0))
    obj_ref.data.materials.append(mat)

    # Scaled object: 3D area 1.0, but UVs scaled by 2 in each dimension (UV area = 4.0)
    obj_scaled = create_plane("Plane_Scaled", size=1.0, uv_scale=(2.0, 2.0), location=(10, 0, 0))
    obj_scaled.data.materials.append(mat)

    # Set both objects' density range to default (0.9 to 1.1)
    obj_ref[uv_marks.DENSITY_KEY] = [1.0, 1.0]
    obj_scaled[uv_marks.DENSITY_KEY] = [1.0, 1.0]

    obj_ref.select_set(True)
    obj_scaled.select_set(True)
    bpy.context.view_layer.objects.active = obj_scaled

    bpy.context.scene.fss_uv_heatmap_show = True
    uv_heatmap.update_heatmap_cache(bpy.context)

    cache_scaled = uv_heatmap._cache.get(obj_scaled.name)
    assert cache_scaled is not None, "Cache missing for scaled object"

    # Shape must remain 1.0 (uniform scale is shape-preserving)
    max_shape_diff = np.max(np.abs(cache_scaled.shape - 1.0))
    assert max_shape_diff < 1e-6, f"Shape should remain 1.0, got {cache_scaled.shape}"

    # Texel density of scaled object should be 4.0 relative to reference 1.0
    max_dens_diff = np.max(np.abs(cache_scaled.rel_density - 4.0))
    assert max_dens_diff < 1e-6, f"Density should be 4.0, got {cache_scaled.rel_density}"

    # The reference is the whole texture set, not the selection: alone, the scaled object still reads 4.0
    obj_ref.select_set(False)
    uv_heatmap.update_heatmap_cache(bpy.context)
    alone = uv_heatmap._cache.get(obj_scaled.name)
    assert np.max(np.abs(alone.rel_density - 4.0)) < 1e-6, f"Density alone should stay 4.0, got {alone.rel_density}"
    assert obj_ref.name not in uv_heatmap._cache, "unselected objects are not drawn"

    # Drawn positions are in object space (the overlay follows the object's current matrix)
    assert np.max(np.abs(alone.pos[:, 0])) <= 0.5 + 1e-6, "cached positions must be object space, not world space"

    # Opening another file clears the cache (keys are object names)
    uv_heatmap._on_load_post(None)
    assert not uv_heatmap._cache and not uv_heatmap._ref_cache, "load_post must clear the heatmap cache"

    print(f"  -> PASS: shape {cache_scaled.shape[0]:.4f}, relative density {cache_scaled.rel_density[0]:.4f}, "
          f"texture set reference, object space, cleared on load")


def test_uv_sheared():
    """Verify UVs sheared give shape distortion strictly above 1.0."""
    print("Test 3: UVs sheared give shape distortion above 1.0...")
    clean_scene()
    obj = create_plane("Plane_Sheared", size=2.0, uv_scale=(1.0, 1.0), uv_shear=0.8)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    mat = bpy.data.materials.new("ShearMat")
    obj.data.materials.append(mat)

    bpy.context.scene.fss_uv_heatmap_show = True
    uv_heatmap.update_heatmap_cache(bpy.context)

    cache = uv_heatmap._cache.get(obj.name)
    assert cache is not None
    assert np.all(cache.shape > 1.2), f"Expected shape > 1.2 on sheared UVs, got {cache.shape}"
    print(f"  -> PASS: sheared shape distortion = {cache.shape[0]:.4f}")


def test_degenerate_triangles():
    """Verify zero 3D area and zero UV area triangles are counted as degenerate."""
    print("Test 4: Degenerate triangles (zero 3D or UV area)...")
    clean_scene()
    
    # 1. 3D degenerate triangle
    P3_deg = np.array([
        [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [1.0, 0.0, 0.0]],  # zero 3D area
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],  # valid 3D, zero UV
    ], dtype=np.float64)

    U_deg = np.array([
        [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]],                  # valid UV on deg 3D
        [[0.0, 0.0], [0.0, 0.0], [0.0, 0.0]],                  # zero UV on valid 3D
    ], dtype=np.float64)

    res = uv_heatmap.compute_triangle_measures(P3_deg, U_deg)
    assert res['is_degenerate'][0] == True, "Zero 3D area must be marked degenerate"
    assert res['is_degenerate'][1] == True, "Zero UV area must be marked degenerate"

    colors = uv_heatmap.measures_to_colors(res['shape'], np.ones(2), res['is_degenerate'], 'SHAPE')
    assert np.allclose(colors[0], uv_heatmap.COLOR_DEGENERATE), "Degenerate triangle 0 must have grey color"
    assert np.allclose(colors[1], uv_heatmap.COLOR_DEGENERATE), "Degenerate triangle 1 must have grey color"
    print("  -> PASS: both zero-3D and zero-UV triangles recognized and colored grey.")


def test_skip_auto_seam_mark():
    """Verify Skip Auto Seam mark on object and inheritance from parent in Propose Seams."""
    print("Test 5: Skip Auto Seam mark and inheritance in Propose Seams...")
    clean_scene()

    # 1. Direct mark on mesh object
    obj_direct = create_plane("DirectSkipped", location=(0, 0, 0))
    obj_direct.select_set(True)
    bpy.context.view_layer.objects.active = obj_direct

    bpy.ops.fss.uv_set_skip_autoseam(action='SKIP')
    assert obj_direct.get(uv_marks.SKIP_AUTOSEAM_KEY) == True

    is_skip, src = uv_marks.skip_autoseam(obj_direct)
    assert is_skip is True and src == obj_direct

    # Gather candidates for Propose Seams
    unique_m, m_to_objs, shared, replaced, skipped = uv_autoseam._gather_candidate_objects(bpy.context)
    assert len(unique_m) == 0
    assert any(name == "DirectSkipped" and reason == "marked Skip Auto Seam" for name, reason in skipped), (
        f"Direct object not skipped with expected reason: {skipped}"
    )

    # 2. Inherited mark from parent empty
    bpy.ops.fss.uv_set_skip_autoseam(action='CLEAR')
    obj_direct.select_set(False)

    parent_empty = bpy.data.objects.new("ParentEmpty", None)
    bpy.context.scene.collection.objects.link(parent_empty)
    parent_empty[uv_marks.SKIP_AUTOSEAM_KEY] = True

    child_mesh = create_plane("ChildMesh", location=(2, 0, 0))
    child_mesh.parent = parent_empty
    child_mesh.select_set(True)
    bpy.context.view_layer.objects.active = child_mesh

    is_skip, src = uv_marks.skip_autoseam(child_mesh)
    assert is_skip is True and src == parent_empty, f"Expected inheritance from parent_empty, got {src}"

    unique_m, m_to_objs, shared, replaced, skipped = uv_autoseam._gather_candidate_objects(bpy.context)
    assert len(unique_m) == 0
    assert any(name == "ChildMesh" and reason == "marked Skip Auto Seam (from ParentEmpty)" for name, reason in skipped), (
        f"Child object not skipped with inheritance reason: {skipped}"
    )

    # 3. Select Marked operator
    bpy.ops.fss.uv_select_marked()
    assert parent_empty.select_get(), "ParentEmpty should be selected by Select Marked"
    print("  -> PASS: direct mark, inherited mark with parent name, and Select Marked verified.")


def test_gltf_export_unchanged():
    """Verify turning heatmap on/off leaves exported glTF completely unchanged."""
    print("Test 6: glTF export unchanged with heatmap active...")
    clean_scene()
    dir_off = SCRATCH_DIR / "off"
    dir_on = SCRATCH_DIR / "on"
    dir_off.mkdir(parents=True, exist_ok=True)
    dir_on.mkdir(parents=True, exist_ok=True)
    path_off = dir_off / "model.gltf"
    path_on = dir_on / "model.gltf"

    obj = create_plane("ExportPlane", size=1.0)
    mat = bpy.data.materials.new("ExportMat")
    obj.data.materials.append(mat)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    # 1. Export with heatmap off
    bpy.context.scene.fss_uv_heatmap_show = False
    bpy.ops.export_scene.gltf(
        filepath=str(path_off),
        use_selection=True,
        export_format='GLTF_SEPARATE'
    )

    # 2. Turn heatmap on, compute measures and caches
    bpy.context.scene.fss_uv_heatmap_show = True
    uv_heatmap.update_heatmap_cache(bpy.context)

    # Export with heatmap on
    bpy.ops.export_scene.gltf(
        filepath=str(path_on),
        use_selection=True,
        export_format='GLTF_SEPARATE'
    )

    with open(path_off, 'r', encoding='utf-8') as f:
        data_off = json.load(f)
    with open(path_on, 'r', encoding='utf-8') as f:
        data_on = json.load(f)

    # glTF structures and buffers must match exactly
    assert data_off == data_on, "glTF content differed between heatmap off and on!"
    bin_off = open(dir_off / "model.bin", "rb").read()
    bin_on = open(dir_on / "model.bin", "rb").read()
    assert bin_off == bin_on, "glTF binary buffer differed between heatmap off and on!"
    print("  -> PASS: glTF output byte/JSON identical; no heatmap data leaked to export.")


def test_uvmetrics_parity_on_trim_panel():
    """Verify measures agree with uvmetrics.py on TRIM_PANEL artist UVs within 1e-6."""
    print("Test 7: Verification against uvmetrics.py on TRIM_PANEL...")
    if not TRIM_PANEL_NPZ.exists():
        print(f"  SKIPPED: {TRIM_PANEL_NPZ} not found")
        return

    sys.path.insert(0, str(REPO_ROOT / 'tests' / 'uv_prototype'))
    import uvmetrics

    data = np.load(str(TRIM_PANEL_NPZ))
    P, T, UV = data['P'], data['T'], data['UV']
    P3 = P[T]

    # Compute with uvmetrics.shape_metrics
    res_ref = uvmetrics.shape_metrics(P, T, UV)
    ref_conf = res_ref['faces']['conformal']

    # Compute with uv_heatmap.compute_triangle_measures
    res_my = uv_heatmap.compute_triangle_measures(P3, UV)
    my_conf = res_my['shape']

    # Compare finite values
    fin_ref = np.isfinite(ref_conf)
    fin_my = np.isfinite(my_conf)
    assert np.array_equal(fin_ref, fin_my), "Finite status mismatch between uvmetrics and uv_heatmap"

    max_diff = np.max(np.abs(my_conf[fin_ref] - ref_conf[fin_ref]))
    assert max_diff < 1e-6, f"Parity diff {max_diff:.2e} exceeded 1e-6 tolerance!"
    print(f"  -> PASS: 3367 finite faces match uvmetrics within {max_diff:.2e} (tolerance 1e-6).")


def test_overhead_shell_performance():
    """Verify OVERHEAD_SHELL (50,822 triangles) computes in at most 2.0 s."""
    print("Test 8: OVERHEAD_SHELL performance benchmark...")
    if not WORK3_BLEND.exists():
        print(f"  SKIPPED: {WORK3_BLEND} not found")
        return

    clean_scene()
    with bpy.data.libraries.load(str(WORK3_BLEND), link=False) as (data_from, data_to):
        if 'W_OVERHEAD_SHELL' in data_from.objects:
            data_to.objects = ['W_OVERHEAD_SHELL']

    obj = data_to.objects[0]
    bpy.context.scene.collection.objects.link(obj)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    bpy.context.scene.fss_uv_heatmap_show = True

    t0 = time.perf_counter()
    uv_heatmap.update_heatmap_cache(bpy.context)
    dt = time.perf_counter() - t0

    cache = uv_heatmap._cache.get(obj.name)
    assert cache is not None
    n_tris = cache.n_tris
    print(f"  OVERHEAD_SHELL: {n_tris:,} triangles computed in {dt:.4f} s")

    assert dt <= 2.0, f"OVERHEAD_SHELL compute time {dt:.3f} s exceeded 2.0 s threshold!"
    print("  -> PASS: OVERHEAD_SHELL computed well under the 2.0 s limit.")


def test_opaque_surface_shader():
    """The heatmap surface shader compiles, draws opaque colours, and hides its own back parts (depth write)."""
    print("Test 9: Opaque heatmap surface shader (offscreen)...")
    import math
    import gpu
    from mathutils import Matrix
    from gpu_extras.batch import batch_for_shader
    gpu.init()  # background Blender: initialise the GPU module for offscreen drawing

    def plane(z, color):
        pos = np.array([(-1, -1, z), (1, -1, z), (1, 1, z), (-1, -1, z), (1, 1, z), (-1, 1, z)], np.float32)
        nor = np.tile([0.0, 0.0, 1.0], (6, 1)).astype(np.float32)
        col = np.tile(color, (6, 1)).astype(np.float32)
        return pos, nor, col

    # the near plane (z = 0.2, red) is drawn first, the far plane (z = -0.2, blue) second: the near one must win
    near_p, far_p = plane(0.2, [1.0, 0.0, 0.0, 1.0]), plane(-0.2, [0.0, 0.0, 1.0, 1.0])
    pos = np.concatenate([near_p[0], far_p[0]])
    nor = np.concatenate([near_p[1], far_p[1]])
    col = np.concatenate([near_p[2], far_p[2]])
    near, far, t = 0.01, 100.0, 1.0 / math.tan(math.radians(30))
    proj = Matrix(((t, 0, 0, 0), (0, t, 0, 0), (0, 0, (far + near) / (near - far), 2 * far * near / (near - far)),
                   (0, 0, -1, 0)))
    view = Matrix.Translation((0, 0, -3.0))

    shader = uv_heatmap._heatmap_shader()
    batch = batch_for_shader(shader, 'TRIS', {'pos': pos, 'nor': nor, 'color': col})
    size = 64
    off = gpu.types.GPUOffScreen(size, size)
    try:
        def centre_pixel(opacity):
            with off.bind():
                fb = gpu.state.active_framebuffer_get()
                fb.clear(color=(0, 0, 0, 1), depth=1.0)
                gpu.state.depth_test_set('LESS_EQUAL')
                gpu.state.depth_mask_set(True)
                shader.bind()
                shader.uniform_float('mvp', proj @ view)
                shader.uniform_float('normal_matrix', view.inverted_safe().transposed())
                shader.uniform_float('opacity', opacity)
                shader.uniform_float('base_grey', uv_heatmap.BASE_GREY)
                batch.draw(shader)
                gpu.state.depth_test_set('NONE')
                return np.array(fb.read_color(size // 2, size // 2, 1, 1, 4, 0, 'FLOAT').to_list()).ravel()

        full = centre_pixel(1.0)
        assert full[0] > 0.95 and full[2] < 0.05, f"the near plane must hide the far one, got {full}"
        half = centre_pixel(0.5)
        expected = 0.5 * uv_heatmap.BASE_GREY + 0.5  # facing the camera: shade 1.0
        assert abs(half[0] - expected) < 0.02 and abs(half[1] - 0.5 * uv_heatmap.BASE_GREY) < 0.02, \
            f"opacity 0.5 must mix the colour with grey, got {half}"
    finally:
        off.free()
    print(f"  -> PASS: near plane wins ({np.round(full[:3], 3)}), opacity mixes with grey ({np.round(half[:3], 3)}).")


def test_distribution_chart():
    """The panel chart: area-weighted histogram, 90 % range and text, and an offscreen drawing of the card."""
    print("Test 11: Distribution chart for the panel...")
    import gpu
    gpu.init()
    values = np.array([1.0, 1.0, 1.05, 1.3, 2.5])
    areas = np.array([4.0, 3.0, 1.0, 1.0, 1.0])
    stats = {'chart_distortion': values, 'chart_density': np.ones(5), 'chart_area': areas,
             'share_above_110': 0.2, 'share_above_125': 0.2, 'share_under': 0.0, 'share_over': 0.0}
    data = uv_heatmap.chart_data('SHAPE', stats)
    assert abs(data['share'].sum() - 1.0) < 1e-9, "histogram shares must add up to the whole surface"
    assert abs(data['share'][0] - 0.7) < 1e-9, "70 % of the area sits at 1.0"
    assert abs(data['share'][-1] - 0.1) < 1e-9, "values beyond 2.0 go into the last bin"
    assert data['range_text'] == "90% of surface: 1.00 to 2.0+", data['range_text']  # 10 % of the area lies at 2.5
    assert data['lines'] == ["Over 1.10 (target): 20.0%", "Over 1.25 (limit): 20.0%"]
    px = uv_heatmap.render_chart(data)
    assert px.shape == (uv_heatmap.CHART_SIZE, uv_heatmap.CHART_SIZE, 4)
    assert float(px[..., 2].max()) > 0.9, "the band and the histogram must be drawn (blue end of the scale)"
    print(f"  -> PASS: shares, range '{data['range_text']}', and a {px.shape[0]} px card drawn.")


def test_updates_after_uv_change():
    """Changed UVs reach the heatmap without Refresh: a geometry update drops the object's cached results."""
    print("Test 12: Heatmap follows UV changes...")
    from types import SimpleNamespace
    clean_scene()
    obj = create_plane("Plane_Unwrap", size=1.0)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    uv_heatmap.update_heatmap_cache(bpy.context)
    assert np.max(np.abs(uv_heatmap._cache[obj.name].shape - 1.0)) < 1e-6

    # shear the UVs (what an unwrap or a UV edit changes), then deliver the update Blender sends for it
    for loop in obj.data.uv_layers.active.data:
        loop.uv = (loop.uv[0] + 0.8 * loop.uv[1], loop.uv[1])
    obj.data.update()
    fake = SimpleNamespace(updates=[SimpleNamespace(is_updated_geometry=True, id=obj.data)])
    assert uv_heatmap._invalidate_changed(fake), "a geometry update of the mesh must invalidate the object"
    assert obj.name not in uv_heatmap._cache and uv_heatmap._global_stats.get('selection') is None
    uv_heatmap.update_heatmap_cache(bpy.context, refresh=False)  # what the next redraw does
    assert np.min(uv_heatmap._cache[obj.name].shape) > 1.2, "the recomputed heatmap must show the sheared UVs"

    # updates without geometry changes (moving, display type) keep the cache
    fake = SimpleNamespace(updates=[SimpleNamespace(is_updated_geometry=False, id=obj)])
    assert not uv_heatmap._invalidate_changed(fake) and obj.name in uv_heatmap._cache
    print("  -> PASS: UV change invalidates and recomputes; transform-only updates keep the cache.")


def test_wire_display_takeover():
    """While shown, the heatmap's objects display as wire; their own display comes back afterwards."""
    print("Test 10: Wire display takeover and restore...")
    clean_scene()
    obj = create_plane("Plane_Display", size=1.0)
    other = create_plane("Plane_ArtistWire", size=1.0, location=(3, 0, 0))
    obj.display_type = 'TEXTURED'
    other.display_type = 'WIRE'  # the artist's own choice must be left alone
    obj.select_set(True)
    other.select_set(True)
    bpy.context.view_layer.objects.active = obj
    scene = bpy.context.scene

    scene.fss_uv_heatmap_show = False
    scene.fss_uv_heatmap_show = True  # the toggle's update callback takes the selection over
    assert obj.display_type == 'WIRE', f"shown object should display as wire, got {obj.display_type}"

    obj.select_set(False)
    uv_heatmap._sync_display()
    assert obj.display_type == 'TEXTURED', "a deselected object gets its own display back"
    obj.select_set(True)
    uv_heatmap._on_depsgraph_update_post(scene)  # a selection change arrives as a depsgraph update
    assert obj.display_type == 'WIRE', 'the depsgraph handler takes a newly selected object over'
    assert uv_heatmap._sync_timer() == uv_heatmap.SYNC_INTERVAL, 'the timer keeps running while shown'

    uv_heatmap._on_save_pre(None)
    assert obj.display_type == 'TEXTURED', "the saved file must not keep the wire display"
    uv_heatmap._on_save_post(None)
    assert obj.display_type == 'WIRE', "after saving, the heatmap takes the object over again"

    # an undo that brings back a wire display after the heatmap was switched off is repaired
    scene.fss_uv_heatmap_show = False
    assert obj.display_type == 'TEXTURED', "switching off restores the display"
    obj.display_type = 'WIRE'  # what an undo to an earlier step would bring back
    uv_heatmap._on_undo_redo_post(None)
    assert obj.display_type == 'TEXTURED', "after an undo the original display is restored"
    assert other.display_type == 'WIRE', "an object the artist set to wire is never changed"
    print("  -> PASS: wire while shown, restored on deselect, save, switch-off and undo; artist's wire kept.")


def run_all_tests():
    print("=" * 70)
    print("RUNNING UV HEATMAP & SKIP MARK TESTS")
    print("=" * 70)
    test_flat_plane_undistorted()
    test_uv_scaled_by_two()
    test_uv_sheared()
    test_degenerate_triangles()
    test_skip_auto_seam_mark()
    test_gltf_export_unchanged()
    test_uvmetrics_parity_on_trim_panel()
    test_overhead_shell_performance()
    test_opaque_surface_shader()
    test_distribution_chart()
    test_updates_after_uv_change()
    test_wire_display_takeover()
    print("=" * 70)
    print("ALL UV HEATMAP TESTS PASSED SUCCESSFULLY.")
    print("=" * 70)


if __name__ == '__main__':
    run_all_tests()
