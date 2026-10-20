"""UV Heatmap: per-face conformal shape distortion and texel density overlay in the 3D viewport.

Evaluates loop triangles of selected mesh objects in world space and the active UV map.
Draws directly in the 3D viewport via GPU shaders; writes nothing to meshes, objects, or materials.
RizomUV-style diverging colour bar: neutral 1.0, red below, blue above.
"""

import math
import numpy as np
import bpy
import blf
from bpy.app.handlers import persistent

try:
    import gpu
    from gpu_extras.batch import batch_for_shader
except ImportError:
    gpu = None
    batch_for_shader = None

from .tags import _editable
from .uv_marks import density

# Color definitions (RGBA, blended over viewport shading)
ALPHA = 0.75
COLOR_NEUTRAL = np.array([0.92, 0.92, 0.92, ALPHA], dtype=np.float32)
COLOR_BLUE = np.array([0.10, 0.35, 0.95, ALPHA], dtype=np.float32)
COLOR_RED = np.array([0.95, 0.15, 0.15, ALPHA], dtype=np.float32)
COLOR_DEGENERATE = np.array([0.50, 0.50, 0.50, ALPHA], dtype=np.float32)

# Text / Legend settings
TEXT_FONT = 0
TEXT_SIZE = 12
COLOR_TEXT_MAIN = (1.0, 1.0, 1.0, 1.0)
COLOR_TEXT_DIM = (0.78, 0.78, 0.78, 1.0)
COLOR_TEXT_WARN = (1.0, 0.75, 0.25, 1.0)

# Global caches and draw handles
_cache = {}  # obj_name -> ObjectHeatmapCache
_ref_cache = {}  # material name -> reference density of its texture set (all scene objects using it)
_global_stats = {}
_draw_view_handle = None
_draw_pixel_handle = None


def tri_area2_signed(U):
    """Signed area of 2D triangles (n, 3, 2). Matches uvmetrics.tri_area2_signed."""
    a = U[:, 1] - U[:, 0]
    b = U[:, 2] - U[:, 0]
    return 0.5 * (a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0])


def tri_area3(P3):
    """Area of 3D triangles (n, 3, 3). Matches uvmetrics.tri_area3."""
    return 0.5 * np.linalg.norm(np.cross(P3[:, 1] - P3[:, 0], P3[:, 2] - P3[:, 0]), axis=1)


def area_weighted_median(values, weights):
    """Area-weighted median (50% quantile). Matches uvmetrics weighted stats."""
    if not len(values) or weights.sum() <= 0:
        return 1.0
    order = np.argsort(values, kind='stable')
    cumulative = np.cumsum(weights[order])
    cutoff = 0.5 * cumulative[-1]
    idx = min(int(np.searchsorted(cumulative, cutoff)), len(order) - 1)
    return float(values[order[idx]])


def compute_triangle_measures(P3, U, degeneracy_relative=1e-12):
    """Compute per-triangle shape and texel density measures from 3D and UV coordinates.

    Matches uvmetrics.py formulas and thresholds:
    - Shape: conformal distortion ratio sigma1 / sigma2 of the affine 3D-to-UV map (>= 1.0).
    - Degenerate: cross_len <= degeneracy_relative * longest_squared or uv_area <= 0.
    """
    n = len(P3)
    if n == 0:
        return {
            'area3': np.zeros(0, dtype=np.float64),
            'uv_area': np.zeros(0, dtype=np.float64),
            'valid': np.zeros(0, dtype=bool),
            'is_degenerate': np.zeros(0, dtype=bool),
            'shape': np.zeros(0, dtype=np.float64),
            'raw_density': np.zeros(0, dtype=np.float64),
        }

    e1 = P3[:, 1] - P3[:, 0]
    e2 = P3[:, 2] - P3[:, 0]
    cross = np.cross(e1, e2)
    cross_len = np.linalg.norm(cross, axis=1)
    longest_sq = np.maximum.reduce([
        np.sum(e1**2, axis=1),
        np.sum(e2**2, axis=1),
        np.sum((e2 - e1)**2, axis=1)
    ])
    valid = cross_len > degeneracy_relative * longest_sq
    area3 = cross_len / 2.0
    uv_area = np.abs(tri_area2_signed(U))
    is_degenerate = (~valid) | (uv_area <= 0)

    shape = np.full(n, np.nan, dtype=np.float64)
    raw_density = np.full(n, np.nan, dtype=np.float64)

    valid_indices = np.flatnonzero(valid)
    if len(valid_indices) > 0:
        l = np.linalg.norm(e1[valid], axis=1)
        x = np.einsum('ij,ij->i', e1[valid], e2[valid]) / l
        h = cross_len[valid] / l
        du = U[valid, 1] - U[valid, 0]
        dv = U[valid, 2] - U[valid, 0]

        J = np.empty((len(valid_indices), 2, 2), dtype=np.float64)
        J[:, :, 0] = du / l[:, None]
        J[:, :, 1] = (dv - du * (x / l)[:, None]) / h[:, None]

        sigma = np.linalg.svd(J, compute_uv=False)
        sig1 = sigma[:, 0]
        sig2 = sigma[:, 1]

        with np.errstate(divide='ignore', invalid='ignore'):
            conf = np.where(sig2 > 0, sig1 / sig2, np.inf)
            conf[uv_area[valid] <= 0] = np.inf
        shape[valid] = conf

        with np.errstate(divide='ignore', invalid='ignore'):
            raw_density[valid] = np.where(area3[valid] > 0, uv_area[valid] / area3[valid], np.nan)

    return {
        'area3': area3,
        'uv_area': uv_area,
        'valid': valid,
        'is_degenerate': is_degenerate,
        'shape': shape,
        'raw_density': raw_density,
    }


def material_references(raw_density, area3, is_degenerate, material_keys):
    """Area-weighted median of UV area / 3D area per material: the reference density of each texture set."""
    refs = {}
    usable = (~is_degenerate) & np.isfinite(raw_density)
    for mat in set(material_keys):
        mask = (material_keys == mat) & usable
        refs[mat] = area_weighted_median(raw_density[mask], area3[mask]) if np.any(mask) else 1.0
    return refs


def compute_relative_density(raw_density, area3, is_degenerate, material_keys, density_ranges, ref_by_material=None):
    """Compute relative texel density per triangle.

    The density of each triangle is divided by its material's reference (the given references, else the
    area-weighted median over these triangles), then read against the object's authored density range:
    inside the range counts as 1.0 (neutral), below the range relative to its minimum, above relative to its maximum.
    """
    if ref_by_material is None:
        ref_by_material = material_references(raw_density, area3, is_degenerate, material_keys)
    density_ranges = np.asarray(density_ranges, dtype=np.float64).reshape(-1, 2)
    ref = np.array([ref_by_material.get(m, 1.0) for m in material_keys], dtype=np.float64)
    low, high = density_ranges[:, 0], density_ranges[:, 1]
    with np.errstate(divide='ignore', invalid='ignore'):
        norm_d = np.where(ref > 0, raw_density / ref, 1.0)
        rel_density = np.where((norm_d < low) & (low > 0), norm_d / low,
                               np.where((norm_d > high) & (high > 0), norm_d / high, 1.0))
    rel_density[is_degenerate | ~np.isfinite(raw_density)] = np.nan
    return rel_density, ref_by_material


def measures_to_colors(shape, rel_density, is_degenerate, mode):
    """Convert shape or density measures to RizomUV-style diverging RGBA colors.

    - Neutral 1.0: light grey / off-white
    - Red below 1.0, blue above 1.0
    - Shape: 1.0 to 2.0 (blue)
    - Density: 0.5 to 2.0 on log scale (0.5 red, 2.0 blue)
    - Degenerate: grey
    """
    n = len(shape)
    colors = np.empty((n, 4), dtype=np.float32)

    if mode == 'SHAPE':
        val = np.where(np.isfinite(shape), shape, 2.0)
        t = np.clip(val - 1.0, 0.0, 1.0)[:, None].astype(np.float32)
        colors = (1.0 - t) * COLOR_NEUTRAL + t * COLOR_BLUE
    else:  # DENSITY
        val = np.where(np.isfinite(rel_density), rel_density, 1.0)
        with np.errstate(divide='ignore', invalid='ignore'):
            log_val = np.log2(np.maximum(val, 1e-12))
        t = np.clip(log_val, -1.0, 1.0)[:, None].astype(np.float32)
        pos = (t >= 0).ravel()
        colors[pos] = (1.0 - t[pos]) * COLOR_NEUTRAL + t[pos] * COLOR_BLUE
        colors[~pos] = (1.0 + t[~pos]) * COLOR_NEUTRAL + (-t[~pos]) * COLOR_RED

    colors[is_degenerate] = COLOR_DEGENERATE
    return colors


class ObjectHeatmapCache:
    """Cached geometry, measures, and GPU batches for a single mesh object."""

    def __init__(self, obj_name, P_local, tri_measures, rel_density, colors_shape, colors_density):
        self.obj_name = obj_name
        self.n_tris = len(P_local)
        # object space: the overlay is drawn with the object's current matrix, so it follows moves
        self.pos = P_local.reshape(-1, 3).astype(np.float32)
        self.colors_shape = np.repeat(colors_shape, 3, axis=0).astype(np.float32)
        self.colors_density = np.repeat(colors_density, 3, axis=0).astype(np.float32)
        self.area3 = tri_measures['area3']
        self.is_degenerate = tri_measures['is_degenerate']
        self.shape = tri_measures['shape']
        self.rel_density = rel_density
        self.batches = {}  # (mode, opacity) -> GPUBatch

    def get_batch(self, mode, shader, opacity=ALPHA):
        if gpu is None or batch_for_shader is None:
            return None
        key = (mode, round(opacity, 3))
        if key not in self.batches:
            colors = (self.colors_shape if mode == 'SHAPE' else self.colors_density).copy()
            colors[:, 3] = opacity
            self.batches.clear()
            self.batches[key] = batch_for_shader(shader, 'TRIS', {'pos': self.pos, 'color': colors})
        return self.batches[key]


def tag_redraw():
    """Trigger redraw of all 3D viewports."""
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def clear_cache():
    """Clear all cached heatmap geometry, material references and GPU batches."""
    _cache.clear()
    _ref_cache.clear()
    _global_stats.clear()


@persistent
def _on_load_post(_dummy):
    # cache keys are object names, which a newly loaded file may reuse
    clear_cache()


def _object_triangles(obj, depsgraph):
    """Loop triangles of the evaluated mesh: world and object space corners, UVs and material per triangle.

    None when the object has no faces or no active UV map.
    """
    if not obj.data or not len(obj.data.polygons) or obj.data.uv_layers.active is None:
        return None
    me = obj.evaluated_get(depsgraph).data
    if not me or not len(me.polygons) or me.uv_layers.active is None:
        return None
    me.calc_loop_triangles()
    n_tris = len(me.loop_triangles)
    if n_tris == 0:
        return None
    tri_verts = np.empty((n_tris, 3), dtype=np.int32)
    me.loop_triangles.foreach_get('vertices', tri_verts.ravel())
    tri_loops = np.empty((n_tris, 3), dtype=np.int32)
    me.loop_triangles.foreach_get('loops', tri_loops.ravel())
    tri_mat = np.empty(n_tris, dtype=np.int32)
    me.loop_triangles.foreach_get('material_index', tri_mat)
    V = np.empty((len(me.vertices), 3), dtype=np.float64)
    me.vertices.foreach_get('co', V.ravel())
    M = np.array(obj.matrix_world, dtype=np.float64)
    uv_data = np.empty((len(me.loops), 2), dtype=np.float64)
    me.uv_layers.active.data.foreach_get('uv', uv_data.ravel())
    slot_names = [slot.material.name if slot.material else '' for slot in obj.material_slots]
    mat_keys = np.array([slot_names[i] if 0 <= i < len(slot_names) else '' for i in tri_mat], dtype=object)
    return {
        'P3': (V @ M[:3, :3].T + M[:3, 3])[tri_verts],  # world space: measures include the object's scale
        'P_local': V[tri_verts],
        'U': uv_data[tri_loops],
        'mat_keys': mat_keys,
    }


def _texture_set_references(context, depsgraph, materials, known):
    """Reference density per material over every mesh object in the view layer that uses it.

    One texture set per material (decision 8): a part is compared with everything sharing its texture,
    not only with the current selection. `known` maps object names to already computed triangle data.
    """
    raw, area, degen, keys = [], [], [], []
    for obj in context.view_layer.objects:
        if obj.type != 'MESH' or not obj.data:
            continue
        if not any(slot.material and slot.material.name in materials for slot in obj.material_slots):
            continue
        item = known.get(obj.name)
        if item is None:
            tris = _object_triangles(obj, depsgraph)
            if tris is None:
                continue
            item = dict(tris, measures=compute_triangle_measures(tris['P3'], tris['U']))
        m = item['measures']
        raw.append(m['raw_density'])
        area.append(m['area3'])
        degen.append(m['is_degenerate'])
        keys.append(item['mat_keys'])
    if not raw:
        return {mat: 1.0 for mat in materials}
    refs = material_references(np.concatenate(raw), np.concatenate(area), np.concatenate(degen),
                               np.concatenate(keys))
    return {mat: refs.get(mat, 1.0) for mat in materials}


def update_heatmap_cache(context, refresh=True):
    """Compute and cache UV heatmap measures for the selected mesh objects.

    refresh=True recomputes everything (toggle, Refresh); refresh=False only adds newly selected objects,
    reusing the cached texture set references, so a selection change stays cheap.
    """
    global _global_stats
    if refresh:
        _cache.clear()
        _ref_cache.clear()
    depsgraph = context.evaluated_depsgraph_get()

    selected = [obj for obj in context.selected_objects if _editable(obj) and obj.type == 'MESH']
    skipped_no_uvs = []
    new_items = {}
    for obj in selected:
        if obj.name in _cache:
            continue
        tris = _object_triangles(obj, depsgraph)
        if tris is None:
            if obj.data and len(obj.data.polygons):
                skipped_no_uvs.append(obj.name)
            continue
        (low, high), _ = density(obj)
        new_items[obj.name] = dict(tris, measures=compute_triangle_measures(tris['P3'], tris['U']),
                                   density_range=(low, high))

    needed = {m for item in new_items.values() for m in item['mat_keys']} - set(_ref_cache)
    if needed:
        _ref_cache.update(_texture_set_references(context, depsgraph, needed, new_items))

    for name, item in new_items.items():
        m = item['measures']
        rel_d, _ = compute_relative_density(m['raw_density'], m['area3'], m['is_degenerate'], item['mat_keys'],
                                            [item['density_range']] * len(item['mat_keys']), _ref_cache)
        _cache[name] = ObjectHeatmapCache(
            name, item['P_local'], m, rel_d,
            measures_to_colors(m['shape'], rel_d, m['is_degenerate'], 'SHAPE'),
            measures_to_colors(m['shape'], rel_d, m['is_degenerate'], 'DENSITY'))

    # Legend statistics over the selected objects shown
    entries = [_cache[obj.name] for obj in selected if obj.name in _cache]
    if not refresh:
        skipped_no_uvs = sorted(set(skipped_no_uvs) | set(_global_stats.get('skipped_no_uvs', [])))
    if not entries:
        _global_stats = {'skipped_no_uvs': skipped_no_uvs, 'total_tris': 0, 'valid_area': 0.0,
                         'share_above_110': 0.0, 'share_above_125': 0.0, 'share_outside': 0.0,
                         'share_under': 0.0, 'share_over': 0.0, 'share_degenerate': 0.0, 'degenerate_count': 0}
        return
    all_shape = np.concatenate([e.shape for e in entries])
    all_rel_d = np.concatenate([e.rel_density for e in entries])
    all_area3 = np.concatenate([e.area3 for e in entries])
    all_degen = np.concatenate([e.is_degenerate for e in entries])
    valid_mask = (~all_degen) & (all_area3 > 0)
    total_valid_area = float(np.sum(all_area3[valid_mask]))
    total_area_all = float(np.sum(all_area3))
    if total_valid_area > 0:
        share_110 = float(np.sum(all_area3[valid_mask & (all_shape > 1.10)])) / total_valid_area
        share_125 = float(np.sum(all_area3[valid_mask & (all_shape > 1.25)])) / total_valid_area
        # the object's density range maps to exactly 1.0
        share_under = float(np.sum(all_area3[valid_mask & (all_rel_d < 0.9999)])) / total_valid_area
        share_over = float(np.sum(all_area3[valid_mask & (all_rel_d > 1.0001)])) / total_valid_area
    else:
        share_110 = share_125 = share_under = share_over = 0.0
    _global_stats = {
        'skipped_no_uvs': skipped_no_uvs,
        'total_tris': len(all_shape),
        'valid_area': total_valid_area,
        'share_above_110': share_110,
        'share_above_125': share_125,
        'share_outside': share_under + share_over,
        'share_under': share_under,
        'share_over': share_over,
        'share_degenerate': (float(np.sum(all_area3[all_degen])) / total_area_all) if total_area_all > 0 else 0.0,
        'degenerate_count': int(np.sum(all_degen)),
    }


def _draw_viewport_heatmap():
    """POST_VIEW draw handler: renders colored loop triangles with depth testing."""
    context = bpy.context
    if not context.space_data or not context.space_data.overlay.show_overlays:
        return
    if not getattr(context.scene, 'fss_uv_heatmap_show', False):
        return
    if context.mode == 'EDIT_MESH':
        return
    if gpu is None:
        return

    selected_mesh_names = [
        obj.name for obj in context.selected_objects
        if obj.type == 'MESH' and _editable(obj)
    ]
    if not selected_mesh_names:
        return

    # Newly selected objects are added; cached ones and the texture set references are kept until Refresh
    if not all(name in _cache for name in selected_mesh_names if name not in _global_stats.get('skipped_no_uvs', [])):
        update_heatmap_cache(context, refresh=False)

    mode = context.scene.fss_uv_heatmap_mode
    opacity = context.scene.fss_uv_heatmap_opacity
    shader = gpu.shader.from_builtin('SMOOTH_COLOR')
    objects = context.view_layer.objects

    gpu.state.depth_test_set('LESS_EQUAL')
    gpu.state.depth_mask_set(False)
    gpu.state.blend_set('ALPHA')
    try:
        shader.bind()
        for name in selected_mesh_names:
            entry = _cache.get(name)
            obj = objects.get(name)
            if entry is None or obj is None:
                continue
            batch = entry.get_batch(mode, shader, opacity)
            if batch is not None:
                with gpu.matrix.push_pop():
                    gpu.matrix.multiply_matrix(obj.matrix_world)
                    batch.draw(shader)
    finally:
        gpu.state.depth_mask_set(True)
        gpu.state.depth_test_set('NONE')
        gpu.state.blend_set('NONE')


def _draw_viewport_legend():
    """POST_PIXEL draw handler: draws legend in viewport corner."""
    context = bpy.context
    if not context.space_data or not context.space_data.overlay.show_overlays:
        return
    if not getattr(context.scene, 'fss_uv_heatmap_show', False):
        return
    if context.mode == 'EDIT_MESH':
        return

    selected_mesh_names = [
        obj.name for obj in context.selected_objects
        if obj.type == 'MESH' and _editable(obj)
    ]
    if not selected_mesh_names:
        return

    mode = context.scene.fss_uv_heatmap_mode
    ui_scale = context.preferences.system.ui_scale
    font_size = int(TEXT_SIZE * ui_scale)
    line_step = int(18 * ui_scale)

    stats = _global_stats
    lines = []

    # Title & mode
    mode_text = 'Shape (Conformal)' if mode == 'SHAPE' else 'Texel Density'
    lines.append((f'UV Heatmap: {mode_text}', COLOR_TEXT_MAIN, True))

    # Scale explanation
    if mode == 'SHAPE':
        lines.append(('Scale: 1.0 (neutral) to 2.0+ (blue), grey = degenerate', COLOR_TEXT_DIM, False))
        s110 = stats.get('share_above_110', 0.0)
        s125 = stats.get('share_above_125', 0.0)
        lines.append((f'Area > 1.10: {s110:.1%} | Area > 1.25: {s125:.1%}', COLOR_TEXT_MAIN, False))
    else:
        lines.append(('Scale: 0.5 (red) - 1.0 (neutral) - 2.0 (blue) [log], grey = degenerate', COLOR_TEXT_DIM, False))
        s_out = stats.get('share_outside', 0.0)
        s_und = stats.get('share_under', 0.0)
        s_ovr = stats.get('share_over', 0.0)
        lines.append((f'Area outside range: {s_out:.1%} (under: {s_und:.1%}, over: {s_ovr:.1%})', COLOR_TEXT_MAIN, False))

    # Degenerate info
    deg_cnt = stats.get('degenerate_count', 0)
    if deg_cnt > 0:
        deg_share = stats.get('share_degenerate', 0.0)
        lines.append((f'Degenerate: {deg_share:.1%} ({deg_cnt} tris)', COLOR_TEXT_WARN, False))

    # Skipped objects without UVs
    skipped = stats.get('skipped_no_uvs', [])
    if skipped:
        lines.append((f'Skipped (no UVs): {", ".join(skipped)}', COLOR_TEXT_WARN, False))

    # Position in bottom-left above LOD preview text
    start_x = 16
    start_y = 36 if getattr(context.scene, 'fss_viewport_lod', -1) >= 0 or getattr(context.scene, 'fss_viewport_lod_auto', False) else 16

    blf.size(TEXT_FONT, font_size)
    blf.enable(TEXT_FONT, blf.SHADOW)
    blf.shadow(TEXT_FONT, 3, 0.0, 0.0, 0.0, 0.9)
    blf.shadow_offset(TEXT_FONT, 1, -1)

    y = start_y + (len(lines) - 1) * line_step
    for text, color, _is_title in lines:
        blf.position(TEXT_FONT, start_x, y, 0)
        blf.color(TEXT_FONT, *color)
        blf.draw(TEXT_FONT, text)
        y -= line_step

    blf.disable(TEXT_FONT, blf.SHADOW)


def _on_toggle_show(self, context):
    """Callback when Show UV Heatmap toggle changes."""
    if self.fss_uv_heatmap_show:
        update_heatmap_cache(context)
    tag_redraw()


def _on_mode_change(self, context):
    """Callback when Heatmap Mode (Shape / Density) changes."""
    tag_redraw()


class FSS_OT_UvHeatmapRefresh(bpy.types.Operator):
    bl_idname = 'fss.uv_heatmap_refresh'
    bl_label = 'Refresh'
    bl_description = 'Recompute UV distortion measures and refresh viewport overlay'
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return any(obj.type == 'MESH' and _editable(obj) for obj in context.selected_objects)

    def execute(self, context):
        update_heatmap_cache(context)
        tag_redraw()
        stats = _global_stats
        self.report({'INFO'}, f"Refreshed UV Heatmap ({stats.get('total_tris', 0)} triangles)")
        return {'FINISHED'}


class FSS_PT_UvHeatmap(bpy.types.Panel):
    bl_idname = 'FSS_PT_uv_heatmap'
    bl_label = 'UV Heatmap'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'FSS Tools'

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        row = layout.row(align=True)
        row.prop(scene, 'fss_uv_heatmap_show', text='Show UV Heatmap', icon='RESTRICT_VIEW_OFF' if scene.fss_uv_heatmap_show else 'RESTRICT_VIEW_ON')
        row.operator(FSS_OT_UvHeatmapRefresh.bl_idname, text='', icon='FILE_REFRESH')

        if scene.fss_uv_heatmap_show:
            row = layout.row(align=True)
            row.prop(scene, 'fss_uv_heatmap_mode', expand=True)
            layout.prop(scene, 'fss_uv_heatmap_opacity', slider=True)

            stats = _global_stats
            box = layout.box()
            if stats.get('total_tris', 0) > 0:
                if scene.fss_uv_heatmap_mode == 'SHAPE':
                    box.label(text=f"Area > 1.10: {stats.get('share_above_110', 0.0):.1%}")
                    box.label(text=f"Area > 1.25: {stats.get('share_above_125', 0.0):.1%}")
                else:
                    box.label(text=f"Outside range: {stats.get('share_outside', 0.0):.1%}")
                    box.label(text=f"  under: {stats.get('share_under', 0.0):.1%}, over: {stats.get('share_over', 0.0):.1%}")
                if stats.get('degenerate_count', 0) > 0:
                    box.label(text=f"Degenerate: {stats.get('share_degenerate', 0.0):.1%} ({stats.get('degenerate_count', 0)} tris)", icon='INFO')
            elif stats.get('skipped_no_uvs'):
                box.label(text=f"Skipped (no UVs): {', '.join(stats.get('skipped_no_uvs'))}", icon='CANCEL')
            else:
                box.label(text='Select mesh object(s) with UVs', icon='INFO')


CLASSES = (
    FSS_OT_UvHeatmapRefresh,
    FSS_PT_UvHeatmap,
)


def register():
    global _draw_view_handle, _draw_pixel_handle
    for cls in CLASSES:
        bpy.utils.register_class(cls)

    bpy.types.Scene.fss_uv_heatmap_show = bpy.props.BoolProperty(
        name='Show UV Heatmap',
        default=False,
        options={'SKIP_SAVE'},
        description='Display UV distortion heatmap overlay on selected mesh objects in the 3D viewport',
        update=_on_toggle_show,
    )

    bpy.types.Scene.fss_uv_heatmap_mode = bpy.props.EnumProperty(
        name='Heatmap Mode',
        items=[
            ('SHAPE', 'Shape', 'Conformal distortion (1.0 neutral, > 1.0 stretched or sheared)'),
            ('DENSITY', 'Density', 'Texel density relative to material median and object range (0.5 red, 1.0 neutral, 2.0 blue)'),
        ],
        default='SHAPE',
        options={'SKIP_SAVE'},
        update=_on_mode_change,
    )

    bpy.types.Scene.fss_uv_heatmap_opacity = bpy.props.FloatProperty(
        name='Opacity', default=ALPHA, min=0.3, max=1.0, precision=2, options={'SKIP_SAVE'},
        description='Opacity of the heatmap over the viewport shading',
        update=_on_mode_change,
    )

    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)

    if not bpy.app.background and gpu is not None:
        _draw_view_handle = bpy.types.SpaceView3D.draw_handler_add(
            _draw_viewport_heatmap, (), 'WINDOW', 'POST_VIEW'
        )
        _draw_pixel_handle = bpy.types.SpaceView3D.draw_handler_add(
            _draw_viewport_legend, (), 'WINDOW', 'POST_PIXEL'
        )


def unregister():
    global _draw_view_handle, _draw_pixel_handle
    if _draw_view_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_view_handle, 'WINDOW')
        _draw_view_handle = None
    if _draw_pixel_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_pixel_handle, 'WINDOW')
        _draw_pixel_handle = None

    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    clear_cache()

    for prop in ('fss_uv_heatmap_show', 'fss_uv_heatmap_mode', 'fss_uv_heatmap_opacity'):
        if hasattr(bpy.types.Scene, prop):
            delattr(bpy.types.Scene, prop)

    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
