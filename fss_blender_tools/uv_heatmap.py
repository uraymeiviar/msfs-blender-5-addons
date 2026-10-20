"""UV Heatmap: per-face conformal shape distortion and texel density overlay in the 3D viewport.

Evaluates loop triangles of selected mesh objects in world space and the active UV map.
Draws directly in the 3D viewport via GPU shaders; writes nothing to meshes, objects, or materials.
RizomUV-style diverging colour bar: neutral 1.0, red below, blue above.
"""

import math
import numpy as np
import bpy
import blf

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


def compute_relative_density(raw_density, area3, is_degenerate, material_keys, density_ranges):
    """Compute relative texel density per triangle.

    For each material across all shown triangles:
    - calculates the area-weighted median of UV area / 3D area as reference.
    - normalizes density against the material's reference.
    - evaluates relative to the object's authored density range:
      inside range counts as 1.0 (neutral), below min relative to min, above max relative to max.
    """
    n = len(raw_density)
    rel_density = np.ones(n, dtype=np.float64)

    # 1. Compute reference median per material
    unique_materials = set(material_keys)
    ref_by_material = {}
    for mat in unique_materials:
        mat_mask = (material_keys == mat) & (~is_degenerate) & np.isfinite(raw_density)
        if np.any(mat_mask):
            ref_by_material[mat] = area_weighted_median(raw_density[mat_mask], area3[mat_mask])
        else:
            ref_by_material[mat] = 1.0

    # 2. Normalize and scale relative to density range
    for i in range(n):
        if is_degenerate[i] or not np.isfinite(raw_density[i]):
            rel_density[i] = np.nan
            continue
        ref = ref_by_material.get(material_keys[i], 1.0)
        norm_d = (raw_density[i] / ref) if ref > 0 else 1.0
        low, high = density_ranges[i]
        if norm_d < low and low > 0:
            rel_density[i] = norm_d / low
        elif norm_d > high and high > 0:
            rel_density[i] = norm_d / high
        else:
            rel_density[i] = 1.0

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

    def __init__(self, obj_name, P3, tri_measures, rel_density, colors_shape, colors_density):
        self.obj_name = obj_name
        self.n_tris = len(P3)
        self.pos = P3.reshape(-1, 3).astype(np.float32)
        self.colors_shape = np.repeat(colors_shape, 3, axis=0).astype(np.float32)
        self.colors_density = np.repeat(colors_density, 3, axis=0).astype(np.float32)
        self.area3 = tri_measures['area3']
        self.is_degenerate = tri_measures['is_degenerate']
        self.shape = tri_measures['shape']
        self.rel_density = rel_density
        self.batch_shape = None
        self.batch_density = None

    def get_batch(self, mode, shader):
        if gpu is None or batch_for_shader is None:
            return None
        if mode == 'SHAPE':
            if self.batch_shape is None:
                self.batch_shape = batch_for_shader(
                    shader, 'TRIS', {'pos': self.pos, 'color': self.colors_shape}
                )
            return self.batch_shape
        else:
            if self.batch_density is None:
                self.batch_density = batch_for_shader(
                    shader, 'TRIS', {'pos': self.pos, 'color': self.colors_density}
                )
            return self.batch_density


def tag_redraw():
    """Trigger redraw of all 3D viewports."""
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def clear_cache():
    """Clear all cached heatmap geometry and GPU batches."""
    global _cache, _global_stats
    _cache.clear()
    _global_stats.clear()


def update_heatmap_cache(context):
    """Compute and cache UV heatmap measures for selected mesh objects."""
    global _cache, _global_stats
    _cache.clear()
    _global_stats.clear()

    selected = [obj for obj in context.selected_objects if _editable(obj)]
    mesh_objs = [obj for obj in selected if obj.type == 'MESH']

    skipped_no_uvs = []
    eval_data = []

    depsgraph = context.evaluated_depsgraph_get()

    for obj in mesh_objs:
        me_orig = obj.data
        if not me_orig or len(me_orig.polygons) == 0:
            continue
        if not me_orig.uv_layers or me_orig.uv_layers.active is None:
            skipped_no_uvs.append(obj.name)
            continue

        ev = obj.evaluated_get(depsgraph)
        me = ev.data
        if not me or len(me.polygons) == 0:
            continue
        if not me.uv_layers or me.uv_layers.active is None:
            skipped_no_uvs.append(obj.name)
            continue

        me.calc_loop_triangles()
        n_tris = len(me.loop_triangles)
        if n_tris == 0:
            continue

        tri_verts = np.empty((n_tris, 3), dtype=np.int32)
        me.loop_triangles.foreach_get('vertices', tri_verts.ravel())
        tri_loops = np.empty((n_tris, 3), dtype=np.int32)
        me.loop_triangles.foreach_get('loops', tri_loops.ravel())
        tri_mat = np.empty(n_tris, dtype=np.int32)
        me.loop_triangles.foreach_get('material_index', tri_mat)

        V = np.empty((len(me.vertices), 3), dtype=np.float64)
        me.vertices.foreach_get('co', V.ravel())
        M = np.array(obj.matrix_world, dtype=np.float64)
        V_world = V @ M[:3, :3].T + M[:3, 3]
        P3 = V_world[tri_verts]

        uv_data = np.empty((len(me.loops), 2), dtype=np.float64)
        me.uv_layers.active.data.foreach_get('uv', uv_data.ravel())
        U = uv_data[tri_loops]

        # Material keys
        slot_names = [slot.material.name if slot.material else '' for slot in obj.material_slots]
        mat_keys = np.array([
            slot_names[idx] if 0 <= idx < len(slot_names) else ''
            for idx in tri_mat
        ], dtype=object)

        # Authoring density range
        (low, high), _ = density(obj)

        eval_data.append({
            'obj': obj,
            'P3': P3,
            'U': U,
            'mat_keys': mat_keys,
            'density_range': (low, high),
        })

    if not eval_data:
        _global_stats = {
            'skipped_no_uvs': skipped_no_uvs,
            'total_tris': 0,
            'valid_area': 0.0,
            'share_above_110': 0.0,
            'share_above_125': 0.0,
            'share_outside': 0.0,
            'share_under': 0.0,
            'share_over': 0.0,
            'share_degenerate': 0.0,
            'degenerate_count': 0,
        }
        return

    # 1. Compute per-triangle measures
    for item in eval_data:
        item['measures'] = compute_triangle_measures(item['P3'], item['U'])

    # 2. Aggregate for density reference across all shown triangles
    all_raw_d = np.concatenate([item['measures']['raw_density'] for item in eval_data])
    all_area3 = np.concatenate([item['measures']['area3'] for item in eval_data])
    all_degen = np.concatenate([item['measures']['is_degenerate'] for item in eval_data])
    all_mat_keys = np.concatenate([item['mat_keys'] for item in eval_data])
    all_ranges = []
    for item in eval_data:
        all_ranges.extend([item['density_range']] * len(item['mat_keys']))
    all_ranges = np.array(all_ranges)

    all_rel_d, _ = compute_relative_density(
        all_raw_d, all_area3, all_degen, all_mat_keys, all_ranges
    )

    # 3. Split relative density back to items, compute colors, and create cache entries
    offset = 0
    for item in eval_data:
        n = len(item['P3'])
        item_rel_d = all_rel_d[offset:offset + n]
        offset += n
        colors_shape = measures_to_colors(
            item['measures']['shape'], item_rel_d, item['measures']['is_degenerate'], 'SHAPE'
        )
        colors_density = measures_to_colors(
            item['measures']['shape'], item_rel_d, item['measures']['is_degenerate'], 'DENSITY'
        )
        cache_entry = ObjectHeatmapCache(
            item['obj'].name, item['P3'], item['measures'], item_rel_d, colors_shape, colors_density
        )
        _cache[item['obj'].name] = cache_entry

    # 4. Compute global summary stats for viewport legend
    all_shape = np.concatenate([item['measures']['shape'] for item in eval_data])
    valid_mask = (~all_degen) & (all_area3 > 0)
    total_valid_area = float(np.sum(all_area3[valid_mask]))
    deg_mask = all_degen
    deg_count = int(np.sum(deg_mask))
    total_area_all = float(np.sum(all_area3))
    deg_area = float(np.sum(all_area3[deg_mask]))

    if total_valid_area > 0:
        area_110 = float(np.sum(all_area3[valid_mask & (all_shape > 1.10)]))
        area_125 = float(np.sum(all_area3[valid_mask & (all_shape > 1.25)]))
        share_110 = area_110 / total_valid_area
        share_125 = area_125 / total_valid_area

        # Density stats: outside range means rel_density < 1.0 (under) or > 1.0 (over)
        # Because relative density maps range [low, high] -> 1.0 exactly
        area_under = float(np.sum(all_area3[valid_mask & (all_rel_d < 0.9999)]))
        area_over = float(np.sum(all_area3[valid_mask & (all_rel_d > 1.0001)]))
        share_under = area_under / total_valid_area
        share_over = area_over / total_valid_area
        share_outside = share_under + share_over
    else:
        share_110 = share_125 = share_outside = share_under = share_over = 0.0

    share_deg = (deg_area / total_area_all) if total_area_all > 0 else 0.0

    _global_stats = {
        'skipped_no_uvs': skipped_no_uvs,
        'total_tris': len(all_shape),
        'valid_area': total_valid_area,
        'share_above_110': share_110,
        'share_above_125': share_125,
        'share_outside': share_outside,
        'share_under': share_under,
        'share_over': share_over,
        'share_degenerate': share_deg,
        'degenerate_count': deg_count,
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

    # Check if cache needs update
    if not all(name in _cache for name in selected_mesh_names if name not in _global_stats.get('skipped_no_uvs', [])):
        update_heatmap_cache(context)

    mode = context.scene.fss_uv_heatmap_mode
    shader = gpu.shader.from_builtin('SMOOTH_COLOR')

    gpu.state.depth_test_set('LESS_EQUAL')
    gpu.state.depth_mask_set(False)
    gpu.state.blend_set('ALPHA')
    try:
        shader.bind()
        for name in selected_mesh_names:
            entry = _cache.get(name)
            if entry is not None:
                batch = entry.get_batch(mode, shader)
                if batch is not None:
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

    clear_cache()

    for prop in ('fss_uv_heatmap_show', 'fss_uv_heatmap_mode'):
        if hasattr(bpy.types.Scene, prop):
            delattr(bpy.types.Scene, prop)

    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
