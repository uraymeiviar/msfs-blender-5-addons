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
# faces that cannot be measured (no area in the UVs or the model), shown to artists as 'Error': a colour on neither scale
COLOR_DEGENERATE = np.array([1.00, 0.00, 1.00, ALPHA], dtype=np.float32)

# Text / Legend settings
TEXT_FONT = 0
TEXT_SIZE = 12
COLOR_TEXT_MAIN = (1.0, 1.0, 1.0, 1.0)
COLOR_TEXT_DIM = (0.78, 0.78, 0.78, 1.0)
COLOR_TEXT_WARN = (1.0, 0.75, 0.25, 1.0)

# While the heatmap is shown, its objects are displayed as wire and the heatmap draws their surface itself, opaque and
# lit, so there is no second surface to fight with (no z-fighting and no depth bias). The display type is the only
# thing changed on the object; it is restored when the heatmap is off, the object is deselected, before saving, after
# an undo, and when the add-on is disabled.
BASE_GREY = 0.8
_shader = None
_display_original = {}  # obj_name -> display_type before the heatmap took it over (kept until another file loads)
_display_active = set()  # obj names currently displayed as wire by the heatmap
SYNC_INTERVAL = 0.25

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
    - Degenerate (shown as 'Error'): magenta
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
        # object space: the surface is drawn with the object's current matrix, so it follows moves
        self.pos = P_local.reshape(-1, 3).astype(np.float32)
        e1 = P_local[:, 1] - P_local[:, 0]
        e2 = P_local[:, 2] - P_local[:, 0]
        nor = np.cross(e1, e2)
        nor /= np.maximum(np.linalg.norm(nor, axis=1, keepdims=True), 1e-30)
        self.nor = np.repeat(nor, 3, axis=0).astype(np.float32)  # flat shading: the face normal at every corner
        self.colors_shape = np.repeat(colors_shape, 3, axis=0).astype(np.float32)
        self.colors_density = np.repeat(colors_density, 3, axis=0).astype(np.float32)
        self.area3 = tri_measures['area3']
        self.is_degenerate = tri_measures['is_degenerate']
        self.shape = tri_measures['shape']
        self.rel_density = rel_density
        self.batches = {}  # mode -> GPUBatch

    def get_batch(self, mode, shader):
        if gpu is None or batch_for_shader is None:
            return None
        if mode not in self.batches:
            colors = self.colors_shape if mode == 'SHAPE' else self.colors_density
            self.batches[mode] = batch_for_shader(shader, 'TRIS', {'pos': self.pos, 'nor': self.nor, 'color': colors})
        return self.batches[mode]


def _heatmap_shader():
    """Opaque surface shader: heat colour mixed with grey by the opacity, lit by a headlight; created on first use
    (needs a GPU context)."""
    global _shader
    if _shader is None:
        info = gpu.types.GPUShaderCreateInfo()
        info.push_constant('MAT4', 'mvp')
        info.push_constant('MAT4', 'normal_matrix')
        info.push_constant('FLOAT', 'opacity')
        info.push_constant('FLOAT', 'base_grey')
        info.vertex_in(0, 'VEC3', 'pos')
        info.vertex_in(1, 'VEC3', 'nor')
        info.vertex_in(2, 'VEC4', 'color')
        iface = gpu.types.GPUStageInterfaceInfo('fss_uv_heatmap_iface')
        iface.smooth('VEC4', 'v_color')
        iface.smooth('VEC3', 'v_nor')
        info.vertex_out(iface)
        info.fragment_out(0, 'VEC4', 'FragColor')
        info.vertex_source('void main() { gl_Position = mvp * vec4(pos, 1.0); '
                           'v_nor = (normal_matrix * vec4(nor, 0.0)).xyz; v_color = color; }')
        info.fragment_source('void main() { float shade = 0.7 + 0.3 * abs(normalize(v_nor).z); '
                             'vec3 c = mix(vec3(base_grey), v_color.rgb, opacity) * shade; '
                             'FragColor = vec4(c, 1.0); }')
        _shader = gpu.shader.create_from_info(info)
    return _shader


def _view_layers():
    """(scene, view layer) of every window; timers and handlers have no selection in bpy.context, windows do."""
    wm = getattr(bpy.context, 'window_manager', None)
    pairs = [(w.scene, w.view_layer) for w in wm.windows] if wm is not None else []
    if not pairs and getattr(bpy.context, 'view_layer', None) is not None:
        pairs = [(bpy.context.scene, bpy.context.view_layer)]  # background Blender has no windows
    return pairs


def _heatmap_targets():
    """Names of the objects the heatmap draws now: selected editable meshes with an active UV map, outside Edit Mode."""
    names = set()
    for scene, view_layer in _view_layers():
        if not getattr(scene, 'fss_uv_heatmap_show', False):
            continue
        active = view_layer.objects.active
        if active is not None and active.mode == 'EDIT':
            continue
        names |= {obj.name for obj in view_layer.objects.selected
                  if obj.type == 'MESH' and _editable(obj) and obj.data and obj.data.uv_layers.active is not None}
    return names


def _sync_display():
    """Display the heatmap's objects as wire, and give every other object back its own display type."""
    wanted = _heatmap_targets()
    for name in list(_display_original):
        if name in wanted:
            continue
        obj = bpy.data.objects.get(name)
        if obj is not None and obj.display_type == 'WIRE':
            obj.display_type = _display_original[name]
        _display_active.discard(name)
    for name in wanted - _display_active:
        obj = bpy.data.objects.get(name)
        if obj is None:
            continue
        if name not in _display_original:
            if obj.display_type in ('WIRE', 'BOUNDS'):
                continue  # the artist's own choice: leave it alone
            _display_original[name] = obj.display_type
        obj.display_type = 'WIRE'
        _display_active.add(name)


def _sync_timer():
    try:
        _sync_display()
        keep = bool(_display_active) or any(getattr(s, 'fss_uv_heatmap_show', False) for s, _ in _view_layers())
    except (ReferenceError, RuntimeError):
        keep = True  # no usable data right now (file loading); try again next tick
    return SYNC_INTERVAL if keep else None


def _invalidate_changed(depsgraph):
    """Drop the cached results of objects whose geometry or UVs changed, and the texture set references of their
    materials, so the next redraw recomputes them (an unwrap arrives here when Edit Mode is left)."""
    if depsgraph is None or not _cache:
        return False
    objects, meshes = set(), set()
    for update in depsgraph.updates:
        if not update.is_updated_geometry:
            continue
        idd = getattr(update.id, 'original', update.id)
        if isinstance(idd, bpy.types.Object):
            objects.add(idd.name)
        elif isinstance(idd, bpy.types.Mesh):
            meshes.add(idd.name)
    stale = [name for name in _cache
             if name in objects or ((obj := bpy.data.objects.get(name)) is not None and obj.data is not None
                                    and obj.data.name in meshes)]
    materials = set()
    for name in stale:
        obj = bpy.data.objects.get(name)
        if obj is not None:
            materials |= {slot.material.name for slot in obj.material_slots if slot.material is not None}
    for mat in materials:
        _ref_cache.pop(mat, None)
    # a changed texture set reference changes the density of every cached object using that material
    for name in list(_cache):
        obj = bpy.data.objects.get(name)
        if name in stale or (obj is not None and any(s.material is not None and s.material.name in materials
                                                     for s in obj.material_slots)):
            del _cache[name]
    if stale:
        _global_stats['selection'] = None  # the draw handler recomputes statistics and chart
    return bool(stale)


@persistent
def _on_depsgraph_update_post(_scene, depsgraph=None):
    # a selection change takes effect at once; the timer stays as a safety net. Idempotent, so the update
    # caused by changing a display type does not loop.
    if _display_active or any(getattr(s, 'fss_uv_heatmap_show', False) for s, _ in _view_layers()):
        _sync_display()
        if _invalidate_changed(depsgraph):
            tag_redraw()


def _start_sync_timer():
    if not bpy.app.timers.is_registered(_sync_timer):
        bpy.app.timers.register(_sync_timer, first_interval=SYNC_INTERVAL)


def _restore_all_display():
    for name, display_type in _display_original.items():
        obj = bpy.data.objects.get(name)
        if obj is not None and obj.display_type == 'WIRE':
            obj.display_type = display_type
    _display_active.clear()


@persistent
def _on_save_pre(_dummy):
    # the saved file never keeps the heatmap's wire display
    _restore_all_display()


@persistent
def _on_save_post(_dummy):
    _sync_display()


@persistent
def _on_undo_redo_post(_dummy):
    # undo can bring back a wire display from an earlier step; restore it, or take it over again when shown
    _display_active.clear()
    _sync_display()
    if _display_active:
        _start_sync_timer()


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
    # cache keys are object names, which a newly loaded file may reuse; the file was saved without wire takeovers
    global _chart_key
    clear_cache()
    _display_original.clear()
    _display_active.clear()
    _chart_key = None


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
    selection = tuple(sorted(obj.name for obj in selected))  # the statistics belong to this selection
    if not entries:
        _global_stats = {'skipped_no_uvs': skipped_no_uvs, 'total_tris': 0, 'valid_area': 0.0,
                         'share_above_110': 0.0, 'share_above_125': 0.0, 'share_outside': 0.0,
                         'share_under': 0.0, 'share_over': 0.0, 'share_degenerate': 0.0, 'degenerate_count': 0,
                         'selection': selection}
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
    chart_mask = valid_mask & np.isfinite(all_shape) & np.isfinite(all_rel_d)
    _global_stats = {
        'selection': selection,
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
        # the distribution behind the panel's chart
        'chart_distortion': all_shape[chart_mask],
        'chart_density': all_rel_d[chart_mask],
        'chart_area': all_area3[chart_mask],
    }
    _update_chart(context.scene.fss_uv_heatmap_mode, _global_stats)


# Distribution chart shown in the panel: a square card drawn offscreen into a preview image (a panel can only show
# Blender's own widgets and images, not custom drawing). Redrawn after each update and mode change, not per frame.
CHART_SIZE = 256
CHART_BINS = 48
CHART_SCALE = 12.0  # icon size in UI units in the panel (about 240 px at 100 % interface scale)
_previews = None
_chart_key = None  # what the current chart image shows, to skip redrawing an unchanged chart


def _chart_axis(mode):
    """(value -> 0..1 position, tick values, tick labels) for the chart's horizontal axis."""
    if mode == 'SHAPE':
        def to_x(v):
            return np.clip((np.asarray(v, dtype=np.float64) - 1.0) / 1.0, 0.0, 1.0)
        return to_x, [1.0, 1.10, 1.25, 1.5, 2.0], ['1.0', '1.10', '1.25', '1.5', '2.0+']

    def to_x(v):
        return np.clip((np.log2(np.maximum(np.asarray(v, dtype=np.float64), 1e-12)) + 1.0) / 2.0, 0.0, 1.0)
    return to_x, [0.5, 0.71, 1.0, 1.41, 2.0], ['0.5-', '0.71', '1.0', '1.41', '2.0+']


def _axis_text(mode, value):
    """A value as the chart's axis shows it: beyond the scale's ends as '2.0+' or '0.5-'."""
    if value > 2.0:
        return '2.0+'
    if mode != 'SHAPE' and value < 0.5:
        return '0.5-'
    return f"{value:.2f}"


def _weighted_quantile(values, weights, q):
    order = np.argsort(values, kind='stable')
    cumulative = np.cumsum(weights[order])
    idx = min(int(np.searchsorted(cumulative, q * cumulative[-1])), len(order) - 1)
    return float(values[order[idx]])


def chart_data(mode, stats):
    """Histogram, range bar and text of the chart, without drawing (testable in background)."""
    values = stats.get('chart_distortion' if mode == 'SHAPE' else 'chart_density')
    areas = stats.get('chart_area')
    if values is None or areas is None or not len(values) or areas.sum() <= 0:
        return None
    to_x, ticks, labels = _chart_axis(mode)
    x = to_x(values)
    hist, _ = np.histogram(x, bins=CHART_BINS, range=(0.0, 1.0), weights=areas)
    share = hist / areas.sum()
    centres = (np.arange(CHART_BINS) + 0.5) / CHART_BINS
    if mode == 'SHAPE':
        bin_values = 1.0 + centres
        colors = measures_to_colors(bin_values, np.ones(CHART_BINS), np.zeros(CHART_BINS, bool), 'SHAPE')
        lines = [f"Over 1.10 (target): {stats.get('share_above_110', 0.0):.1%}",
                 f"Over 1.25 (limit): {stats.get('share_above_125', 0.0):.1%}"]
        marks = [1.10, 1.25]
    else:
        bin_values = 2.0 ** (centres * 2.0 - 1.0)
        colors = measures_to_colors(np.ones(CHART_BINS), bin_values, np.zeros(CHART_BINS, bool), 'DENSITY')
        lines = [f"Too low: {stats.get('share_under', 0.0):.1%}", f"Too high: {stats.get('share_over', 0.0):.1%}"]
        marks = [1.0]
    low = _weighted_quantile(values, areas, 0.05)
    high = _weighted_quantile(values, areas, 0.95)
    return {
        'share': share,
        'colors': colors,
        'ticks': [float(to_x(t)) for t in ticks],
        'tick_labels': labels,
        'marks': [float(to_x(m)) for m in marks],
        'range': (float(to_x(low)), float(to_x(high))),
        'range_text': f"90% of surface: {_axis_text(mode, low)} to {_axis_text(mode, high)}",
        'title': 'Distortion' if mode == 'SHAPE' else 'Texel density',
        'lines': lines,
    }


def render_chart(data, size=CHART_SIZE):
    """Draw the chart card offscreen; returns RGBA float pixels (size x size x 4), bottom row first."""
    from mathutils import Matrix
    W = H = size
    left, right = 12, W - 12
    width = right - left
    hist_bottom, hist_top = 122, 214
    band_bottom, band_top = 104, 118

    def rects(boxes, colors):
        pos, col = [], []
        for (x0, y0, x1, y1), c in zip(boxes, colors):
            pos += [(x0, y0), (x1, y0), (x1, y1), (x0, y0), (x1, y1), (x0, y1)]
            col += [tuple(c)] * 6
        return pos, col

    boxes, colors = [], []
    boxes.append((0, 0, W, H))
    colors.append((0.16, 0.16, 0.16, 1.0))
    peak = max(float(data['share'].max()), 1e-12)
    for i, (s, c) in enumerate(zip(data['share'], data['colors'])):
        if s <= 0:
            continue
        x0 = left + width * i / CHART_BINS
        x1 = left + width * (i + 1) / CHART_BINS - 1
        h = (hist_top - hist_bottom) * math.sqrt(s / peak)  # square-root scale: small tails stay visible
        boxes.append((x0, hist_bottom, x1, hist_bottom + max(h, 1.0)))
        colors.append((c[0], c[1], c[2], 1.0))
    for i, c in enumerate(data['colors']):
        boxes.append((left + width * i / CHART_BINS, band_bottom, left + width * (i + 1) / CHART_BINS, band_top))
        colors.append((c[0], c[1], c[2], 1.0))
    for m in data['marks']:
        x = left + width * m
        boxes.append((x - 0.5, band_bottom - 2, x + 0.5, hist_top))
        colors.append((1.0, 0.75, 0.25, 1.0))
    r0, r1 = data['range']
    xr0, xr1 = left + width * r0, left + width * r1
    boxes += [(xr0, 74, max(xr1, xr0 + 1), 76), (xr0 - 1, 70, xr0 + 1, 80), (xr1 - 1, 70, xr1 + 1, 80)]
    colors += [(0.95, 0.95, 0.95, 1.0)] * 3
    pos, col = rects(boxes, colors)

    shader = gpu.shader.from_builtin('SMOOTH_COLOR')
    batch = batch_for_shader(shader, 'TRIS', {'pos': pos, 'color': col})
    ortho = Matrix(((2.0 / W, 0, 0, -1), (0, 2.0 / H, 0, -1), (0, 0, 1, 0), (0, 0, 0, 1)))
    off = gpu.types.GPUOffScreen(W, H)
    try:
        with off.bind():
            fb = gpu.state.active_framebuffer_get()
            fb.clear(color=(0.16, 0.16, 0.16, 1.0))
            with gpu.matrix.push_pop():
                gpu.matrix.load_identity()
                gpu.matrix.load_projection_matrix(ortho)
                batch.draw(shader)
                font = 0
                blf.size(font, 12)
                blf.color(font, 1.0, 1.0, 1.0, 1.0)
                blf.position(font, left, 236, 0)
                blf.draw(font, data['title'])
                blf.size(font, 10)
                blf.color(font, 0.8, 0.8, 0.8, 1.0)
                for t, label in zip(data['ticks'], data['tick_labels']):
                    tw = blf.dimensions(font, label)[0]
                    blf.position(font, min(max(left + width * t - tw / 2, 2), W - tw - 2), 88, 0)
                    blf.draw(font, label)
                blf.size(font, 11)
                blf.color(font, 0.95, 0.95, 0.95, 1.0)
                blf.position(font, left, 54, 0)
                blf.draw(font, data['range_text'])
                for i, line in enumerate(data['lines']):
                    blf.position(font, left, 32 - 16 * i, 0)
                    blf.draw(font, line)
            pixels = np.array(fb.read_color(0, 0, W, H, 4, 0, 'FLOAT').to_list(), dtype=np.float32)
    finally:
        off.free()
    return pixels.reshape(H, W, 4)


def _update_chart(mode, stats):
    """Redraw the panel's chart preview; silently keeps the text fallback when no GPU is available."""
    global _chart_key
    if _previews is None:
        return
    key = (mode, stats.get('total_tris', 0), stats.get('valid_area', 0.0), stats.get('share_above_110', 0.0),
           stats.get('share_outside', 0.0))
    if key == _chart_key and 'chart' in _previews:
        return
    data = chart_data(mode, stats)
    if data is None:
        return
    try:
        pixels = render_chart(data)
    except Exception:  # no GPU context (for example background Blender without gpu.init)
        return
    preview = _previews.get('chart') or _previews.new('chart')
    preview.image_size = (CHART_SIZE, CHART_SIZE)
    preview.image_pixels_float.foreach_set(pixels.ravel())
    _chart_key = key


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

    # A selection change updates statistics and chart; cached objects and texture set references are kept until
    # Refresh, so this only computes newly selected objects
    if _global_stats.get('selection') != tuple(sorted(selected_mesh_names)):
        update_heatmap_cache(context, refresh=False)

    mode = context.scene.fss_uv_heatmap_mode
    shader = _heatmap_shader()
    region = context.region_data
    objects = context.view_layer.objects

    # opaque surface with its own depth: the objects themselves are displayed as wire meanwhile (_sync_display)
    gpu.state.depth_test_set('LESS_EQUAL')
    gpu.state.depth_mask_set(True)
    try:
        shader.bind()
        shader.uniform_float('opacity', context.scene.fss_uv_heatmap_opacity)
        shader.uniform_float('base_grey', BASE_GREY)
        for name in selected_mesh_names:
            entry = _cache.get(name)
            obj = objects.get(name)
            if entry is None or obj is None:
                continue
            batch = entry.get_batch(mode, shader)
            if batch is not None:
                shader.uniform_float('mvp', region.perspective_matrix @ obj.matrix_world)
                shader.uniform_float('normal_matrix',
                                     (region.view_matrix @ obj.matrix_world).inverted_safe().transposed())
                batch.draw(shader)
    finally:
        gpu.state.depth_test_set('NONE')


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
    mode_text = 'Distortion' if mode == 'SHAPE' else 'Texel Density'
    lines.append((f'UV Heatmap: {mode_text}', COLOR_TEXT_MAIN, True))

    # Scale explanation
    if mode == 'SHAPE':
        lines.append(('Scale: 1.0 (neutral) to 2.0+ (blue), magenta = error', COLOR_TEXT_DIM, False))
        s110 = stats.get('share_above_110', 0.0)
        s125 = stats.get('share_above_125', 0.0)
        lines.append((f'Surface over 1.10 (target): {s110:.1%} | over 1.25 (limit): {s125:.1%}', COLOR_TEXT_MAIN, False))
    else:
        lines.append(('Scale: 0.5 (red) - 1.0 (neutral) - 2.0 (blue), magenta = error', COLOR_TEXT_DIM, False))
        s_out = stats.get('share_outside', 0.0)
        s_und = stats.get('share_under', 0.0)
        s_ovr = stats.get('share_over', 0.0)
        lines.append((f'Surface outside its density range: {s_out:.1%} (too low: {s_und:.1%}, too high: {s_ovr:.1%})', COLOR_TEXT_MAIN, False))

    # Degenerate info
    deg_cnt = stats.get('degenerate_count', 0)
    if deg_cnt > 0:
        deg_share = stats.get('share_degenerate', 0.0)
        lines.append((f'Error: {deg_share:.1%} of surface ({deg_cnt} faces without area in the UVs or the model)', COLOR_TEXT_WARN, False))

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
        _start_sync_timer()
    _sync_display()
    tag_redraw()


def _on_mode_change(self, context):
    """Callback when the heatmap mode (Distortion / Density) or the opacity changes."""
    _update_chart(context.scene.fss_uv_heatmap_mode, _global_stats)
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
            chart = _previews.get('chart') if _previews is not None else None
            if stats.get('total_tris', 0) > 0 and chart is not None and _chart_key and _chart_key[0] == scene.fss_uv_heatmap_mode:
                box.template_icon(icon_value=chart.icon_id, scale=CHART_SCALE)
                if stats.get('degenerate_count', 0) > 0:
                    box.label(text=f"Error: {stats.get('share_degenerate', 0.0):.1%} ({stats.get('degenerate_count', 0)} faces without area)", icon='ERROR')
            elif stats.get('total_tris', 0) > 0:
                # text fallback when the chart image is not available
                if scene.fss_uv_heatmap_mode == 'SHAPE':
                    box.label(text=f"Over 1.10 (target): {stats.get('share_above_110', 0.0):.1%} of surface")
                    box.label(text=f"Over 1.25 (limit): {stats.get('share_above_125', 0.0):.1%} of surface")
                else:
                    box.label(text=f"Outside density range: {stats.get('share_outside', 0.0):.1%} of surface")
                    box.label(text=f"  too low: {stats.get('share_under', 0.0):.1%}, too high: {stats.get('share_over', 0.0):.1%}")
                if stats.get('degenerate_count', 0) > 0:
                    box.label(text=f"Error: {stats.get('share_degenerate', 0.0):.1%} ({stats.get('degenerate_count', 0)} faces without area)", icon='ERROR')
            elif stats.get('skipped_no_uvs'):
                box.label(text=f"Skipped (no UVs): {', '.join(stats.get('skipped_no_uvs'))}", icon='CANCEL')
            else:
                box.label(text='Select mesh object(s) with UVs', icon='INFO')


CLASSES = (
    FSS_OT_UvHeatmapRefresh,
    FSS_PT_UvHeatmap,
)


def register():
    global _draw_view_handle, _draw_pixel_handle, _previews
    import bpy.utils.previews
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    _previews = bpy.utils.previews.new()

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
            ('SHAPE', 'Distortion', 'Distortion of each face\'s shape in the UVs (1.0 neutral, > 1.0 stretched or '
                                    'sheared)'),
            ('DENSITY', 'Density', 'Texel density relative to material median and object range (0.5 red, 1.0 neutral, 2.0 blue)'),
        ],
        default='SHAPE',
        options={'SKIP_SAVE'},
        update=_on_mode_change,
    )

    bpy.types.Scene.fss_uv_heatmap_opacity = bpy.props.FloatProperty(
        name='Opacity', default=ALPHA, min=0.3, max=1.0, precision=2, options={'SKIP_SAVE'},
        description='How strongly the heatmap colours cover the plain grey shading of the surface',
        update=_on_mode_change,
    )

    for handlers, handler in ((bpy.app.handlers.load_post, _on_load_post),
                              (bpy.app.handlers.save_pre, _on_save_pre),
                              (bpy.app.handlers.save_post, _on_save_post),
                              (bpy.app.handlers.undo_post, _on_undo_redo_post),
                              (bpy.app.handlers.redo_post, _on_undo_redo_post),
                              (bpy.app.handlers.depsgraph_update_post, _on_depsgraph_update_post)):
        if handler not in handlers:
            handlers.append(handler)

    if not bpy.app.background and gpu is not None:
        _draw_view_handle = bpy.types.SpaceView3D.draw_handler_add(
            _draw_viewport_heatmap, (), 'WINDOW', 'POST_VIEW'
        )
        _draw_pixel_handle = bpy.types.SpaceView3D.draw_handler_add(
            _draw_viewport_legend, (), 'WINDOW', 'POST_PIXEL'
        )


def unregister():
    global _draw_view_handle, _draw_pixel_handle, _shader, _previews, _chart_key
    if _previews is not None:
        bpy.utils.previews.remove(_previews)
        _previews = None
    _chart_key = None
    if _draw_view_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_view_handle, 'WINDOW')
        _draw_view_handle = None
    if _draw_pixel_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_pixel_handle, 'WINDOW')
        _draw_pixel_handle = None

    if bpy.app.timers.is_registered(_sync_timer):
        bpy.app.timers.unregister(_sync_timer)
    _restore_all_display()
    for handlers, handler in ((bpy.app.handlers.load_post, _on_load_post),
                              (bpy.app.handlers.save_pre, _on_save_pre),
                              (bpy.app.handlers.save_post, _on_save_post),
                              (bpy.app.handlers.undo_post, _on_undo_redo_post),
                              (bpy.app.handlers.redo_post, _on_undo_redo_post),
                              (bpy.app.handlers.depsgraph_update_post, _on_depsgraph_update_post)):
        if handler in handlers:
            handlers.remove(handler)
    clear_cache()
    _shader = None

    for prop in ('fss_uv_heatmap_show', 'fss_uv_heatmap_mode', 'fss_uv_heatmap_opacity'):
        if hasattr(bpy.types.Scene, prop):
            delattr(bpy.types.Scene, prop)

    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
