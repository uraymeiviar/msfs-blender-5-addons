"""UV Heatmap: per-face conformal shape distortion and texel density overlay in the 3D viewport.

Evaluates loop triangles of selected mesh objects in world space and the active UV map.
Draws directly in the 3D viewport via GPU shaders; writes nothing to meshes, objects, or materials.
RizomUV-style diverging colour bar: neutral 1.0, red below, blue above.
"""

import math
from pathlib import Path
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
from . import visibility_core

# Color definitions (RGBA, blended over viewport shading)
ALPHA = 0.75
COLOR_NEUTRAL = np.array([0.92, 0.92, 0.92, ALPHA], dtype=np.float32)
COLOR_BLUE = np.array([0.10, 0.35, 0.95, ALPHA], dtype=np.float32)
COLOR_RED = np.array([0.95, 0.15, 0.15, ALPHA], dtype=np.float32)
# Distortion mode: shear towards blue, area towards green, both towards cyan (red stays Density's "too low")
COLOR_GREEN = np.array([0.15, 0.80, 0.30, ALPHA], dtype=np.float32)
COLOR_CYAN = np.array([0.10, 0.80, 0.95, ALPHA], dtype=np.float32)
AREA_TOP = 2.0  # area distortion shows fully green at twice or half the island's own density
# faces that cannot be measured (no area in the UVs or the model), shown to artists as 'Error': a colour on neither scale
COLOR_DEGENERATE = np.array([1.00, 0.00, 1.00, ALPHA], dtype=np.float32)
# Visibility mode: meshes without data or stale in a neutral dark grey labelled 'No data'
COLOR_NO_DATA = np.array([0.30, 0.30, 0.30, ALPHA], dtype=np.float32)

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


def uv_islands(tri_verts, U):
    """Island index per triangle: triangles that share an edge with equal UVs at both ends belong together."""
    n = len(tri_verts)
    if n == 0:
        return np.zeros(0, dtype=np.int64)
    i0, i1 = np.array([0, 1, 2]), np.array([1, 2, 0])
    va, vb = tri_verts[:, i0].ravel(), tri_verts[:, i1].ravel()
    ua, ub = U[:, i0].reshape(-1, 2), U[:, i1].reshape(-1, 2)
    swap = va > vb
    va, vb = np.where(swap, vb, va), np.where(swap, va, vb)
    ua, ub = np.where(swap[:, None], ub, ua), np.where(swap[:, None], ua, ub)
    keys = np.column_stack([va, vb, np.round(np.hstack([ua, ub]) * 1e6).astype(np.int64)])
    _, inverse = np.unique(keys, axis=0, return_inverse=True)
    inverse = inverse.ravel()
    order = np.argsort(inverse, kind='stable')
    # only edges with exactly two faces join (as uvmetrics): a non-manifold edge does not weld islands
    same = (inverse[order][1:] == inverse[order][:-1]) & (np.bincount(inverse)[inverse[order][1:]] == 2)
    owner = np.repeat(np.arange(n), 3)[order]
    pa, pb = owner[:-1][same], owner[1:][same]
    labels = np.arange(n)
    while True:  # label propagation with pointer jumping; a few passes even on large shells
        low = np.minimum(labels[pa], labels[pb])
        new = labels.copy()
        np.minimum.at(new, pa, low)
        np.minimum.at(new, pb, low)
        new = new[new]
        if np.array_equal(new, labels):
            return np.unique(labels, return_inverse=True)[1].ravel()
        labels = new


def area_distortion(uv_area, area3, islands, valid):
    """Per face: its UV area / 3D area against its island's, folded so half and double both read 2.0. Auto Seam's
    Distortion Limit is the island's average of this value."""
    ok = valid & (uv_area > 0)
    isl_uv = np.bincount(islands, np.where(ok, uv_area, 0.0))
    isl_3d = np.bincount(islands, np.where(ok, area3, 0.0))
    with np.errstate(divide='ignore', invalid='ignore'):
        r = (uv_area / area3) / (isl_uv / isl_3d)[islands]
        r = np.where(r < 1.0, 1.0 / r, r)
    r[~ok] = np.nan
    return r


def island_area_means(area, islands):
    """Per island: the average of its faces' area distortion, the value Auto Seam compares with its limit."""
    ok = np.isfinite(area)
    count = np.bincount(islands, ok.astype(np.float64))
    with np.errstate(divide='ignore', invalid='ignore'):
        return np.bincount(islands, np.where(ok, area, 0.0)) / count


def distortion_colors(shear, area, is_degenerate, view):
    """White = none; shear towards blue, area towards green, both towards cyan (a bilinear colour square)."""
    s = np.clip(np.where(np.isfinite(shear), shear, 2.0) - 1.0, 0.0, 1.0)
    a = np.clip((np.where(np.isfinite(area), area, AREA_TOP) - 1.0) / (AREA_TOP - 1.0), 0.0, 1.0)
    if view == 'SHEAR':
        a = np.zeros_like(a)
    elif view == 'AREA':
        s = np.zeros_like(s)
    s, a = s[:, None], a[:, None]
    colors = ((1 - s) * (1 - a) * COLOR_NEUTRAL + s * (1 - a) * COLOR_BLUE
              + (1 - s) * a * COLOR_GREEN + s * a * COLOR_CYAN).astype(np.float32)
    colors[is_degenerate] = COLOR_DEGENERATE
    return colors


DISTORTION_VIEWS = ('BOTH', 'SHEAR', 'AREA')


class ObjectHeatmapCache:
    """Cached geometry, measures, and GPU batches for a single mesh object."""

    def __init__(self, obj_name, P_local, tri_measures, rel_density, colors_shape, colors_density, colors_visibility=None, uv=None, vis_data=None,
                 area=None, islands=None):
        self.obj_name = obj_name
        self.n_tris = len(P_local)
        # object space: the surface is drawn with the object's current matrix, so it follows moves
        self.pos = P_local.reshape(-1, 3).astype(np.float32)
        e1 = P_local[:, 1] - P_local[:, 0]
        e2 = P_local[:, 2] - P_local[:, 0]
        nor = np.cross(e1, e2)
        nor /= np.maximum(np.linalg.norm(nor, axis=1, keepdims=True), 1e-30)
        self.nor = np.repeat(nor, 3, axis=0).astype(np.float32)  # flat shading: the face normal at every corner
        # UVs per corner, for the optional UV grid and cell labels
        self.uv = (uv.reshape(-1, 2) if uv is not None else np.zeros((len(self.pos), 2))).astype(np.float32)
        # Distortion mode: colours per view; colors_shape is the shear view, or a dict of all three views
        if isinstance(colors_shape, dict):
            self.colors_distortion = {view: np.repeat(c, 3, axis=0).astype(np.float32) for view, c in colors_shape.items()}
        else:
            self.colors_distortion = {view: np.repeat(colors_shape, 3, axis=0).astype(np.float32) for view in DISTORTION_VIEWS}
        self.colors_shape = self.colors_distortion['SHEAR']
        self.colors_density = np.repeat(colors_density, 3, axis=0).astype(np.float32)
        if colors_visibility is not None:
            self.colors_visibility = np.repeat(colors_visibility, 3, axis=0).astype(np.float32)
        else:
            self.colors_visibility = np.repeat(np.tile(COLOR_NO_DATA, (len(P_local), 1)), 3, axis=0).astype(np.float32)
        self.area3 = tri_measures['area3']
        self.is_degenerate = tri_measures['is_degenerate']
        self.shape = tri_measures['shape']
        self.rel_density = rel_density
        self.area = area if area is not None else np.full(len(P_local), np.nan)
        self.islands = islands if islands is not None else np.zeros(len(P_local), dtype=np.int64)
        self.vis_data = vis_data or {}
        self.batches = {}  # mode -> GPUBatch

    def get_batch(self, mode, shader, view='BOTH'):
        if gpu is None or batch_for_shader is None:
            return None
        key = (mode, view) if mode == 'SHAPE' else mode
        if key not in self.batches:
            if mode == 'SHAPE':
                colors = self.colors_distortion.get(view, self.colors_shape)
            elif mode == 'DENSITY':
                colors = self.colors_density
            else:
                colors = self.colors_visibility
            self.batches[key] = batch_for_shader(shader, 'TRIS', {'pos': self.pos, 'nor': self.nor, 'color': colors,
                                                                  'uv': self.uv})
        return self.batches[key]


GLYPHS = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'
GLYPH_PX = 32  # height of one glyph cell in the label texture
_glyph_texture = None

_FRAGMENT = '''
int glyph_of(int slot, int col, int row) {
    /* label of a cell: column letters (A..Z, AA..) then row number from 1; -1 past its end */
    int n_letters = col < 26 ? 1 : 2;
    int r = row + 1;
    int n_digits = r < 10 ? 1 : 2;
    if (slot < n_letters) {
        if (n_letters == 1) return 10 + col;
        return slot == 0 ? 10 + (col / 26 - 1) : 10 + (col - (col / 26) * 26);
    }
    int d = slot - n_letters;
    if (d >= n_digits) return -1;
    if (n_digits == 1) return r;
    return d == 0 ? r / 10 : r - (r / 10) * 10;
}

void main() {
    float shade = 0.7 + 0.3 * abs(normalize(v_nor).z);
    vec3 c = mix(vec3(base_grey), v_color.rgb, opacity);
    if (grid_cells > 0.0) {
        vec2 g = v_uv * grid_cells;
        vec2 cell = floor(g);
        vec2 f = g - cell;
        vec2 w = max(fwidth(g), vec2(1e-6));
        vec2 d = min(f, 1.0 - f) / w;            /* distance to the nearest cell border, in pixels */
        float line = 1.0 - clamp(min(d.x, d.y) - 0.5, 0.0, 1.0);
        c = mix(c, vec3(0.08), 0.85 * line);
        float cell_px = 1.0 / max(w.x, w.y);      /* a cell's size on screen */
        if (show_labels > 0.5 && cell_px > 22.0) {   /* labels fade in from 22 to 34 px cells */
            float gh = 0.26;                       /* glyph height as a share of the cell */
            float gw = gh * 0.62;
            vec2 q = (f - vec2(0.07, 1.0 - 0.07 - gh)) / vec2(gw, gh);
            if (q.y >= 0.0 && q.y < 1.0 && q.x >= 0.0 && q.x < 4.0) {
                int slot = int(floor(q.x));
                int col = int(mod(cell.x, grid_cells));
                int row = int(mod(cell.y, grid_cells));
                int glyph = glyph_of(slot, col, row);
                if (glyph >= 0) {
                    vec2 t = vec2((float(glyph) + fract(q.x)) / float(n_glyphs), q.y);
                    /* the texture is shrunk on screen without mipmaps: take the strongest of a few taps so thin
                       strokes do not fade */
                    vec2 dx = dFdx(t) * 0.35;
                    vec2 dy = dFdy(t) * 0.35;
                    /* keep every tap inside this glyph's slot, so no sliver of the neighbour shows */
                    float lo = (float(glyph) + 0.04) / float(n_glyphs);
                    float hi = (float(glyph) + 0.96) / float(n_glyphs);
                    vec2 b0 = vec2(lo, 0.0);
                    vec2 b1 = vec2(hi, 1.0);
                    float a = max(max(texture(glyphs, clamp(t + dx, b0, b1)).r, texture(glyphs, clamp(t - dx, b0, b1)).r),
                                  max(texture(glyphs, clamp(t + dy, b0, b1)).r, texture(glyphs, clamp(t - dy, b0, b1)).r));
                    a = smoothstep(0.15, 0.55, max(a, texture(glyphs, clamp(t, b0, b1)).r));
                    float fade = clamp((cell_px - 22.0) / 12.0, 0.0, 1.0);
                    c = mix(c, vec3(0.05), 0.9 * a * fade);
                }
            }
        }
    }
    FragColor = vec4(c * shade, 1.0);
}
'''


def _glyphs():
    """Texture with the label characters side by side, drawn once with blf (needs a GPU context)."""
    global _glyph_texture
    if _glyph_texture is None:
        from mathutils import Matrix
        h = GLYPH_PX
        w = int(h * 0.62)
        size = (w * len(GLYPHS), h)
        off = gpu.types.GPUOffScreen(*size)
        try:
            with off.bind():
                fb = gpu.state.active_framebuffer_get()
                fb.clear(color=(0.0, 0.0, 0.0, 1.0))
                with gpu.matrix.push_pop():
                    gpu.matrix.load_identity()
                    gpu.matrix.load_projection_matrix(Matrix(((2.0 / size[0], 0, 0, -1), (0, 2.0 / size[1], 0, -1),
                                                              (0, 0, 1, 0), (0, 0, 0, 1))))
                    blf.size(0, int(h * 0.8))
                    blf.color(0, 1.0, 1.0, 1.0, 1.0)
                    for i, ch in enumerate(GLYPHS):
                        cw = blf.dimensions(0, ch)[0]
                        for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1)):  # drawn four times, shifted: bold
                            blf.position(0, i * w + (w - cw) / 2 + dx, h * 0.16 + dy, 0)
                            blf.draw(0, ch)
                pixels = fb.read_color(0, 0, size[0], size[1], 4, 0, 'FLOAT')
        finally:
            off.free()
        _glyph_texture = gpu.types.GPUTexture(size, format='RGBA16F', data=pixels)
    return _glyph_texture


def _heatmap_shader():
    """Opaque surface shader: heat colour mixed with grey by the opacity, lit by a headlight, with an optional UV
    grid and cell labels; created on first use (needs a GPU context)."""
    global _shader
    if _shader is None:
        info = gpu.types.GPUShaderCreateInfo()
        info.push_constant('MAT4', 'mvp')
        info.push_constant('MAT4', 'normal_matrix')
        info.push_constant('FLOAT', 'opacity')
        info.push_constant('FLOAT', 'base_grey')
        info.push_constant('FLOAT', 'grid_cells')   # 0 = no grid
        info.push_constant('FLOAT', 'show_labels')
        info.push_constant('INT', 'n_glyphs')
        info.sampler(0, 'FLOAT_2D', 'glyphs')
        info.vertex_in(0, 'VEC3', 'pos')
        info.vertex_in(1, 'VEC3', 'nor')
        info.vertex_in(2, 'VEC4', 'color')
        info.vertex_in(3, 'VEC2', 'uv')
        iface = gpu.types.GPUStageInterfaceInfo('fss_uv_heatmap_iface')
        iface.smooth('VEC4', 'v_color')
        iface.smooth('VEC3', 'v_nor')
        iface.smooth('VEC2', 'v_uv')
        info.vertex_out(iface)
        info.fragment_out(0, 'VEC4', 'FragColor')
        info.vertex_source('void main() { gl_Position = mvp * vec4(pos, 1.0); '
                           'v_nor = (normal_matrix * vec4(nor, 0.0)).xyz; v_color = color; v_uv = uv; }')
        info.fragment_source(_FRAGMENT)
        _shader = gpu.shader.create_from_info(info)
    return _shader


def _bind_surface_shader(shader, scene, glyph_texture):
    """Uniforms shared by every object of one draw. The glyph texture is made before any framebuffer is bound
    (_glyphs draws offscreen itself)."""
    shader.uniform_float('opacity', scene.fss_uv_heatmap_opacity)
    shader.uniform_float('base_grey', BASE_GREY)
    cells = float(scene.fss_uv_heatmap_grid_cells) if scene.fss_uv_heatmap_grid else 0.0
    shader.uniform_float('grid_cells', cells)
    shader.uniform_float('show_labels', 1.0 if scene.fss_uv_heatmap_grid_labels else 0.0)
    shader.uniform_int('n_glyphs', len(GLYPHS))
    shader.uniform_sampler('glyphs', glyph_texture)


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


MARKS_REFRESH_DELAY = 0.3  # s after the last mark change: a slider drag sends one change per step


def marks_changed():
    """A density mark or the scene freedom changed: a parent's mark changes the density of everything below it.
    Once the edit pauses, the cached objects are dropped; the next redraw recomputes the selected ones."""
    if not _cache:
        return
    if bpy.app.timers.is_registered(_drop_after_marks):
        bpy.app.timers.unregister(_drop_after_marks)
    bpy.app.timers.register(_drop_after_marks, first_interval=MARKS_REFRESH_DELAY)


def _drop_after_marks():
    _cache.clear()
    _global_stats.pop('selection', None)  # the draw callback then recomputes the selection
    tag_redraw()
    return None


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


def _object_triangles(obj, depsgraph, allow_no_uvs=False):
    """Loop triangles of the evaluated mesh: world and object space corners, UVs and material per triangle.

    None when the object has no faces or (if not allow_no_uvs) no active UV map.
    """
    if not obj.data or not len(obj.data.polygons):
        return None
    if not allow_no_uvs and obj.data.uv_layers.active is None:
        return None
    me = obj.evaluated_get(depsgraph).data
    if not me or not len(me.polygons):
        return None
    if not allow_no_uvs and me.uv_layers.active is None:
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
    tri_poly = np.empty(n_tris, dtype=np.int32)
    me.loop_triangles.foreach_get('polygon_index', tri_poly)
    V = np.empty((len(me.vertices), 3), dtype=np.float64)
    me.vertices.foreach_get('co', V.ravel())
    M = np.array(obj.matrix_world, dtype=np.float64)
    if me.uv_layers.active is not None:
        uv_data = np.empty((len(me.loops), 2), dtype=np.float64)
        me.uv_layers.active.data.foreach_get('uv', uv_data.ravel())
        U = uv_data[tri_loops]
    else:
        U = np.zeros((n_tris, 3, 2), dtype=np.float64)
    slot_names = [slot.material.name if slot.material else '' for slot in obj.material_slots]
    mat_keys = np.array([slot_names[i] if 0 <= i < len(slot_names) else '' for i in tri_mat], dtype=object)
    return {
        'P3': (V @ M[:3, :3].T + M[:3, 3])[tri_verts],  # world space: measures include the object's scale
        'P_local': V[tri_verts],
        'tri_verts': tri_verts,
        'U': U,
        'has_uvs': me.uv_layers.active is not None,
        'tri_poly': tri_poly,
        'eval_face_count': len(me.polygons),
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

    mode = context.scene.fss_uv_heatmap_mode
    is_vis = (mode == 'VISIBILITY')

    vis_file = Path(bpy.data.filepath).with_suffix('.visibility') if bpy.data.filepath else None
    vis_meta, vis_data_arrays, stale_meshes = None, None, []
    if vis_file and vis_file.exists():
        try:
            vis_meta, vis_data_arrays, stale_meshes = visibility_core.load_visibility_file(vis_file, scene_meshes=bpy.data.meshes)
        except Exception:
            pass

    selected = [obj for obj in context.selected_objects if _editable(obj) and obj.type == 'MESH']
    if is_vis:
        selected = [obj for obj in selected if not (obj.hide_render or visibility_core.is_invisible_object(obj))]
    skipped_no_uvs = []
    new_items = {}
    for obj in selected:
        if obj.name in _cache:
            continue
        tris = _object_triangles(obj, depsgraph, allow_no_uvs=is_vis)
        if tris is None:
            if obj.data and len(obj.data.polygons) and not is_vis:
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

        colors_vis = None
        vis_item_data = {'has_data': False}
        if vis_meta and vis_data_arrays:
            obj_inst = context.view_layer.objects.get(name)
            m_name = obj_inst.data.name if (obj_inst and obj_inst.data) else ""
            safe_name = m_name.replace('/', '_').replace('\\', '_')
            safe_obj_name = name.replace('/', '_').replace('\\', '_')
            sc_key = f"{safe_name}__face_scores"
            eval_map_key = f"eval_map__{safe_obj_name}"
            stored_counts = vis_meta.get('object_eval_face_counts', {})
            stored_eval_count = stored_counts.get(name)
            current_eval_count = item.get('eval_face_count', -1)

            if (m_name and m_name not in stale_meshes and sc_key in vis_data_arrays and
                    eval_map_key in vis_data_arrays and stored_eval_count is not None and
                    stored_eval_count == current_eval_count):
                eval_map = vis_data_arrays[eval_map_key]
                if len(eval_map) == current_eval_count:
                    face_sc = vis_data_arrays[sc_key]
                    face_ud = vis_data_arrays.get(f"{safe_name}__face_undetermined", np.zeros(len(face_sc), dtype=bool))
                    face_nv = vis_data_arrays.get(f"{safe_name}__face_never_seen", np.zeros(len(face_sc), dtype=bool))
                    poly_colors = visibility_core.compute_heatmap_colors(face_sc, face_ud, face_nv, alpha=ALPHA)
                    tri_orig = eval_map[item['tri_poly']]
                    colors_vis = poly_colors[tri_orig]
                    vis_item_data = {
                        'has_data': True,
                        'scores': face_sc[tri_orig],
                        'undetermined': face_ud[tri_orig],
                        'never_seen': face_nv[tri_orig],
                    }

        if colors_vis is None:
            colors_vis = np.tile(COLOR_NO_DATA, (len(item['P_local']), 1))
            vis_item_data = {
                'has_data': False,
                'scores': np.zeros(len(item['P_local']), dtype=np.float32),
                'undetermined': np.zeros(len(item['P_local']), dtype=bool),
                'never_seen': np.zeros(len(item['P_local']), dtype=bool),
            }

        islands = uv_islands(item['tri_verts'], item['U'])
        area = area_distortion(m['uv_area'], m['area3'], islands, m['valid'] & ~m['is_degenerate'])
        _cache[name] = ObjectHeatmapCache(
            name, item['P_local'], m, rel_d,
            {view: distortion_colors(m['shape'], area, m['is_degenerate'], view) for view in DISTORTION_VIEWS},
            measures_to_colors(m['shape'], rel_d, m['is_degenerate'], 'DENSITY'),
            colors_visibility=colors_vis, uv=item['U'], vis_data=vis_item_data, area=area, islands=islands)

    # Legend statistics over the selected objects shown
    entries = [_cache[obj.name] for obj in selected if obj.name in _cache]
    if not refresh:
        skipped_no_uvs = sorted(set(skipped_no_uvs) | set(_global_stats.get('skipped_no_uvs', [])))
    selection = tuple(sorted(obj.name for obj in selected))  # the statistics belong to this selection
    if not entries:
        _global_stats = {'skipped_no_uvs': skipped_no_uvs, 'total_tris': 0, 'valid_area': 0.0,
                         'share_above_110': 0.0, 'share_above_125': 0.0, 'share_outside': 0.0,
                         'share_under': 0.0, 'share_over': 0.0, 'share_degenerate': 0.0, 'degenerate_count': 0,
                         'selection': selection, 'share_never_seen': 0.0, 'share_undetermined': 0.0, 'no_data_count': 0}
        return
    all_shape = np.concatenate([e.shape for e in entries])
    all_rel_d = np.concatenate([e.rel_density for e in entries])
    all_area3 = np.concatenate([e.area3 for e in entries])
    all_degen = np.concatenate([e.is_degenerate for e in entries])
    all_area_d = np.concatenate([e.area for e in entries])
    valid_mask = (~all_degen) & (all_area3 > 0)
    total_valid_area = float(np.sum(all_area3[valid_mask]))
    total_area_all = float(np.sum(all_area3))
    if total_valid_area > 0:
        share_110 = float(np.sum(all_area3[valid_mask & (all_shape > 1.10)])) / total_valid_area
        share_125 = float(np.sum(all_area3[valid_mask & (all_shape > 1.25)])) / total_valid_area
        # the object's density range maps to exactly 1.0
        share_under = float(np.sum(all_area3[valid_mask & (all_rel_d < 0.9999)])) / total_valid_area
        share_over = float(np.sum(all_area3[valid_mask & (all_rel_d > 1.0001)])) / total_valid_area
        area_110 = float(np.sum(all_area3[valid_mask & (all_area_d > 1.10)])) / total_valid_area
        area_125 = float(np.sum(all_area3[valid_mask & (all_area_d > 1.25)])) / total_valid_area
    else:
        share_110 = share_125 = share_under = share_over = area_110 = area_125 = 0.0
    # per island: the average area distortion (Auto Seam's measure) and the island's 3D area, for "islands over limit"
    island_means = np.concatenate([island_area_means(e.area, e.islands) for e in entries])
    island_area3 = np.concatenate([np.bincount(e.islands, np.where(e.is_degenerate, 0.0, e.area3)) for e in entries])

    all_vis_has = np.concatenate([np.full(len(e.shape), e.vis_data.get('has_data', False), dtype=bool) for e in entries])
    all_vis_sc = np.concatenate([e.vis_data.get('scores', np.zeros(len(e.shape), dtype=np.float32)) for e in entries])
    all_vis_ud = np.concatenate([e.vis_data.get('undetermined', np.zeros(len(e.shape), dtype=bool)) for e in entries])
    all_vis_nv = np.concatenate([e.vis_data.get('never_seen', np.zeros(len(e.shape), dtype=bool)) for e in entries])

    vis_valid_mask = all_vis_has & (~all_vis_ud) & (~all_vis_nv) & (all_area3 > 0)
    total_vis_area = float(np.sum(all_area3[all_vis_has])) if np.any(all_vis_has) else 0.0

    share_nv = float(np.sum(all_area3[all_vis_has & all_vis_nv])) / total_vis_area if total_vis_area > 0 else 0.0
    share_ud = float(np.sum(all_area3[all_vis_has & all_vis_ud])) / total_vis_area if total_vis_area > 0 else 0.0

    chart_mask = valid_mask & np.isfinite(all_shape) & np.isfinite(all_rel_d)
    _global_stats = {
        'selection': selection,
        'skipped_no_uvs': skipped_no_uvs,
        'total_tris': len(all_shape),
        'valid_area': total_valid_area,
        'share_above_110': share_110,
        'share_above_125': share_125,
        'area_above_110': area_110,
        'area_above_125': area_125,
        'island_means': island_means,
        'island_area3': island_area3,
        'share_outside': share_under + share_over,
        'share_under': share_under,
        'share_over': share_over,
        'share_degenerate': (float(np.sum(all_area3[all_degen])) / total_area_all) if total_area_all > 0 else 0.0,
        'degenerate_count': int(np.sum(all_degen)),
        # the distribution behind the panel's chart
        'chart_distortion': all_shape[chart_mask],
        'chart_area_distortion': np.where(np.isfinite(all_area_d), all_area_d, 1.0)[chart_mask],
        'chart_density': all_rel_d[chart_mask],
        'chart_visibility': all_vis_sc[vis_valid_mask],
        'chart_area': all_area3[vis_valid_mask] if is_vis else all_area3[chart_mask],
        'share_never_seen': share_nv,
        'share_undetermined': share_ud,
        'no_data_count': sum(1 for e in entries if not e.vis_data.get('has_data', False)),
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
    elif mode == 'DENSITY':
        def to_x(v):
            return np.clip((np.log2(np.maximum(np.asarray(v, dtype=np.float64), 1e-12)) + 1.0) / 2.0, 0.0, 1.0)
        return to_x, [0.5, 0.71, 1.0, 1.41, 2.0], ['0.5-', '0.71', '1.0', '1.41', '2.0+']
    else:  # VISIBILITY
        def to_x(v):
            return np.clip(np.asarray(v, dtype=np.float64), 0.0, 1.0)
        return to_x, [0.0, 0.25, 0.5, 0.75, 1.0], ['0.0', '0.25', '0.5', '0.75', '1.0']


def _axis_text(mode, value):
    """A value as the chart's axis shows it: beyond the scale's ends as '2.0+' or '0.5-'."""
    if mode == 'VISIBILITY':
        return f"{value:.2f}"
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


def islands_over_limit(stats, limit):
    """(islands over the limit, all islands, share of the surface in them) from the per-island averages."""
    means = stats.get('island_means')
    areas = stats.get('island_area3')
    if means is None or not len(means):
        return 0, 0, 0.0
    over = np.isfinite(means) & (means > limit + 1e-9)
    total = float(areas.sum())
    return int(over.sum()), len(means), (float(areas[over].sum()) / total if total > 0 else 0.0)


def _histogram(values, areas, to_x):
    hist, _ = np.histogram(to_x(values), bins=CHART_BINS, range=(0.0, 1.0), weights=areas)
    return hist / areas.sum()


def chart_data(mode, stats, view='SHEAR', limit=1.25):
    """Histogram, range bar and text of the chart, without drawing (testable in background).

    Distortion mode shows the shear, the area, or both (two histograms) by view; limit is Auto Seam's Distortion
    Limit, against which islands are counted."""
    if mode == 'SHAPE' and view in ('AREA', 'BOTH'):
        return _distortion_chart(stats, view, limit)
    if mode == 'SHAPE':
        values = stats.get('chart_distortion')
    elif mode == 'DENSITY':
        values = stats.get('chart_density')
    else:
        values = stats.get('chart_visibility')

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
                 f"Over 1.25: {stats.get('share_above_125', 0.0):.1%}"]
        marks = [1.10, 1.25]
    elif mode == 'DENSITY':
        bin_values = 2.0 ** (centres * 2.0 - 1.0)
        colors = measures_to_colors(np.ones(CHART_BINS), bin_values, np.zeros(CHART_BINS, bool), 'DENSITY')
        lines = [f"Too low: {stats.get('share_under', 0.0):.1%}", f"Too high: {stats.get('share_over', 0.0):.1%}"]
        marks = [1.0]
    else:  # VISIBILITY
        t = centres / 0.5 - 1.0
        pos = (t >= 0).ravel()
        colors = np.empty((CHART_BINS, 4), dtype=np.float32)
        colors[pos] = (1.0 - t[pos, None]) * COLOR_NEUTRAL + t[pos, None] * COLOR_BLUE
        colors[~pos] = (1.0 + t[~pos, None]) * COLOR_NEUTRAL + (-t[~pos, None]) * COLOR_RED
        colors[:, 3] = ALPHA
        lines = [f"Never seen: {stats.get('share_never_seen', 0.0):.1%}",
                 f"Undetermined: {stats.get('share_undetermined', 0.0):.1%}"]
        marks = [0.5]

    low = _weighted_quantile(values, areas, 0.05)
    high = _weighted_quantile(values, areas, 0.95)
    title = 'Distortion' if mode == 'SHAPE' else ('Texel density' if mode == 'DENSITY' else 'Visibility')
    return {
        'share': share,
        'colors': colors,
        'ticks': [float(to_x(t)) for t in ticks],
        'tick_labels': labels,
        'marks': [float(to_x(m)) for m in marks],
        'range': (float(to_x(low)), float(to_x(high))),
        'range_text': f"90% of surface: {_axis_text(mode, low)} to {_axis_text(mode, high)}",
        'title': title,
        'lines': lines,
    }


def _distortion_chart(stats, view, limit):
    shear = stats.get('chart_distortion')
    area = stats.get('chart_area_distortion')
    areas = stats.get('chart_area')
    if shear is None or area is None or areas is None or not len(area) or areas.sum() <= 0:
        return None
    to_x, ticks, labels = _chart_axis('SHAPE')
    centres = (np.arange(CHART_BINS) + 0.5) / CHART_BINS
    bin_values = 1.0 + centres
    ones, none = np.ones(CHART_BINS), np.zeros(CHART_BINS, bool)
    n_over, n_all, over_share = islands_over_limit(stats, limit)
    island_line = f"Islands over limit {limit:.2f}: {n_over} of {n_all} ({over_share:.1%})"
    a_low, a_high = _weighted_quantile(area, areas, 0.05), _weighted_quantile(area, areas, 0.95)
    data = {
        'share': _histogram(area, areas, to_x),
        'colors': distortion_colors(ones, bin_values, none, 'AREA'),
        'ticks': [float(to_x(t)) for t in ticks],
        'tick_labels': labels,
        'marks': [float(to_x(limit))],
        'range': (float(to_x(a_low)), float(to_x(a_high))),
        'range_text': f"90% of surface: {_axis_text('SHAPE', a_low)} to {_axis_text('SHAPE', a_high)}",
        'title': 'Distortion: area',
        'lines': [f"Over 1.10: {stats.get('area_above_110', 0.0):.1%}, over 1.25: {stats.get('area_above_125', 0.0):.1%}",
                  island_line],
    }
    if view == 'BOTH':
        s_low, s_high = _weighted_quantile(shear, areas, 0.05), _weighted_quantile(shear, areas, 0.95)
        data.update({
            'share2': data['share'], 'colors2': data['colors'], 'marks2': data['marks'],
            'share': _histogram(shear, areas, to_x),
            'colors': distortion_colors(bin_values, ones, none, 'SHEAR'),
            'marks': [float(to_x(1.10)), float(to_x(1.25))],
            'range': None,
            'range_text': (f"90%: shear {_axis_text('SHAPE', s_low)}-{_axis_text('SHAPE', s_high)}, "
                           f"area {_axis_text('SHAPE', a_low)}-{_axis_text('SHAPE', a_high)}"),
            'title': 'Distortion: shear and area',
            'lines': [f"Shear over 1.25: {stats.get('share_above_125', 0.0):.1%}",
                      f"Area over 1.25: {stats.get('area_above_125', 0.0):.1%}",
                      island_line],
        })
    return data


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

    def histogram(shares, cols, bottom, top):
        peak = max(float(shares.max()), 1e-12)
        for i, (s, c) in enumerate(zip(shares, cols)):
            if s <= 0:
                continue
            x0 = left + width * i / CHART_BINS
            x1 = left + width * (i + 1) / CHART_BINS - 1
            h = (top - bottom) * math.sqrt(s / peak)  # square-root scale: small tails stay visible
            boxes.append((x0, bottom, x1, bottom + max(h, 1.0)))
            colors.append((c[0], c[1], c[2], 1.0))

    def band(cols, bottom, top):
        for i, c in enumerate(cols):
            boxes.append((left + width * i / CHART_BINS, bottom, left + width * (i + 1) / CHART_BINS, top))
            colors.append((c[0], c[1], c[2], 1.0))

    def marks(values, bottom, top):
        for m in values:
            x = left + width * m
            boxes.append((x - 0.5, bottom, x + 0.5, top))
            colors.append((1.0, 0.75, 0.25, 1.0))

    if 'share2' in data:  # two rows: shear above, area below, each with its half of the colour band
        split = (hist_bottom + hist_top) // 2
        histogram(data['share'], data['colors'], split + 4, hist_top)
        histogram(data['share2'], data['colors2'], hist_bottom, split)
        band_split = (band_bottom + band_top) // 2
        band(data['colors'], band_split, band_top)
        band(data['colors2'], band_bottom, band_split)
        marks(data['marks'], band_split, hist_top)
        marks(data['marks2'], band_bottom - 2, split)
        # the colour square: shear to the right, area upwards, cyan in the far corner
        cells, sq, x_sq, y_sq = 6, 30, W - 12 - 30, H - 34
        steps = np.linspace(0.0, 1.0, cells)
        for i, sh in enumerate(steps):
            for j, ar in enumerate(steps):
                c = distortion_colors(np.array([1.0 + sh]), np.array([1.0 + ar * (AREA_TOP - 1.0)]),
                                      np.zeros(1, bool), 'BOTH')[0]
                boxes.append((x_sq + sq * i / cells, y_sq + sq * j / cells,
                              x_sq + sq * (i + 1) / cells, y_sq + sq * (j + 1) / cells))
                colors.append((c[0], c[1], c[2], 1.0))
    else:
        histogram(data['share'], data['colors'], hist_bottom, hist_top)
        band(data['colors'], band_bottom, band_top)
        marks(data['marks'], band_bottom - 2, hist_top)
    if data.get('range') is not None:
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
                step = 16 if len(data['lines']) <= 2 else 14
                for i, line in enumerate(data['lines']):
                    blf.position(font, left, 32 - step * i, 0)
                    blf.draw(font, line)
            pixels = np.array(fb.read_color(0, 0, W, H, 4, 0, 'FLOAT').to_list(), dtype=np.float32)
    finally:
        off.free()
    return pixels.reshape(H, W, 4)


def _distortion_view(scene):
    """(Both / Shear / Area view of the Distortion mode, Auto Seam's Distortion Limit)."""
    return getattr(scene, 'fss_uv_heatmap_distortion', 'BOTH'), getattr(scene, 'fss_uv_autoseam_limit', 1.25)


def _update_chart(mode, stats):
    """Redraw the panel's chart preview; silently keeps the text fallback when no GPU is available."""
    global _chart_key
    if _previews is None:
        return
    view, limit = _distortion_view(bpy.context.scene)
    key = (mode, stats.get('total_tris', 0), stats.get('valid_area', 0.0), stats.get('share_above_110', 0.0),
           stats.get('share_outside', 0.0), view, round(limit, 4))
    if key == _chart_key and 'chart' in _previews:
        return
    data = chart_data(mode, stats, view, limit)
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
    view, _limit = _distortion_view(context.scene)
    _update_chart(mode, _global_stats)  # follows the view and Auto Seam's limit; redraws only when they change
    shader = _heatmap_shader()
    glyph_texture = _glyphs()
    region = context.region_data
    objects = context.view_layer.objects

    # opaque surface with its own depth: the objects themselves are displayed as wire meanwhile (_sync_display)
    gpu.state.depth_test_set('LESS_EQUAL')
    gpu.state.depth_mask_set(True)
    try:
        shader.bind()
        _bind_surface_shader(shader, context.scene, glyph_texture)
        for name in selected_mesh_names:
            entry = _cache.get(name)
            obj = objects.get(name)
            if entry is None or obj is None:
                continue
            batch = entry.get_batch(mode, shader, view)
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
    if mode == 'SHAPE':
        mode_text = 'Distortion'
    elif mode == 'DENSITY':
        mode_text = 'Texel Density'
    else:
        mode_text = 'Visibility'
    lines.append((f'Heatmap: {mode_text}', COLOR_TEXT_MAIN, True))

    # Scale explanation
    if mode == 'SHAPE':
        view, limit = _distortion_view(context.scene)
        s110 = stats.get('share_above_110', 0.0)
        s125 = stats.get('share_above_125', 0.0)
        a110 = stats.get('area_above_110', 0.0)
        a125 = stats.get('area_above_125', 0.0)
        n_over, n_all, _share = islands_over_limit(stats, limit)
        if view == 'BOTH':
            lines.append(('Scale: white = none, blue = shear, green = area, cyan = both (full at 2.0), magenta = error',
                          COLOR_TEXT_DIM, False))
            lines.append((f'Shear over 1.25: {s125:.1%} | Area over 1.25: {a125:.1%} | '
                          f'Islands over limit {limit:.2f}: {n_over} of {n_all}', COLOR_TEXT_MAIN, False))
        elif view == 'AREA':
            lines.append(('Area: 1.0 (neutral) to 2.0+ (green), magenta = error', COLOR_TEXT_DIM, False))
            lines.append((f'Surface over 1.10: {a110:.1%} | over 1.25: {a125:.1%} | '
                          f'Islands over limit {limit:.2f}: {n_over} of {n_all}', COLOR_TEXT_MAIN, False))
        else:
            lines.append(('Shear: 1.0 (neutral) to 2.0+ (blue), magenta = error', COLOR_TEXT_DIM, False))
            lines.append((f'Surface over 1.10 (target): {s110:.1%} | over 1.25: {s125:.1%}', COLOR_TEXT_MAIN, False))
    elif mode == 'DENSITY':
        lines.append(('Scale: 0.5 (red) - 1.0 (neutral) - 2.0 (blue), magenta = error', COLOR_TEXT_DIM, False))
        s_out = stats.get('share_outside', 0.0)
        s_und = stats.get('share_under', 0.0)
        s_ovr = stats.get('share_over', 0.0)
        lines.append((f'Surface outside its density range: {s_out:.1%} (too low: {s_und:.1%}, too high: {s_ovr:.1%})', COLOR_TEXT_MAIN, False))
    else:
        lines.append(('Scale: 0.0 (red) - 0.5 (neutral) - 1.0 (blue), magenta = never seen, cyan = undetermined', COLOR_TEXT_DIM, False))
        s_nv = stats.get('share_never_seen', 0.0)
        s_ud = stats.get('share_undetermined', 0.0)
        lines.append((f'Never seen: {s_nv:.1%} | Undetermined: {s_ud:.1%}', COLOR_TEXT_MAIN, False))
        if stats.get('no_data_count', 0) > 0:
            lines.append((f'No data (or stale): {stats.get("no_data_count", 0)} object(s) in dark grey', COLOR_TEXT_WARN, False))

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
    bl_label = 'Heatmap'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'FSS MSFS Tools'
    bl_order = 7
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        row = layout.row(align=True)
        row.prop(scene, 'fss_uv_heatmap_show', text='Show Heatmap', icon='RESTRICT_VIEW_OFF' if scene.fss_uv_heatmap_show else 'RESTRICT_VIEW_ON')
        row.operator(FSS_OT_UvHeatmapRefresh.bl_idname, text='', icon='FILE_REFRESH')

        if scene.fss_uv_heatmap_show:
            row = layout.row(align=True)
            row.prop(scene, 'fss_uv_heatmap_mode', expand=True)
            if scene.fss_uv_heatmap_mode == 'SHAPE':
                row = layout.row(align=True)
                row.prop(scene, 'fss_uv_heatmap_distortion', expand=True)
            layout.prop(scene, 'fss_uv_heatmap_opacity', slider=True)
            row = layout.row(align=True)
            row.prop(scene, 'fss_uv_heatmap_grid', text='UV Grid', toggle=True)
            sub = row.row(align=True)
            sub.enabled = scene.fss_uv_heatmap_grid
            sub.prop(scene, 'fss_uv_heatmap_grid_cells', text='')
            sub.prop(scene, 'fss_uv_heatmap_grid_labels', text='', icon='FONT_DATA')

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
                    view, limit = _distortion_view(scene)
                    data = chart_data('SHAPE', stats, view, limit)
                    for line in (data['lines'] if data else []):
                        box.label(text=line)
                elif scene.fss_uv_heatmap_mode == 'DENSITY':
                    box.label(text=f"Outside density range: {stats.get('share_outside', 0.0):.1%} of surface")
                    box.label(text=f"  too low: {stats.get('share_under', 0.0):.1%}, too high: {stats.get('share_over', 0.0):.1%}")
                else:
                    box.label(text=f"Never seen: {stats.get('share_never_seen', 0.0):.1%} of surface")
                    box.label(text=f"Undetermined: {stats.get('share_undetermined', 0.0):.1%} of surface")
                    if stats.get('no_data_count', 0) > 0:
                        box.label(text=f"No data / stale: {stats.get('no_data_count', 0)} object(s)", icon='INFO')
                if stats.get('degenerate_count', 0) > 0:
                    box.label(text=f"Error: {stats.get('share_degenerate', 0.0):.1%} ({stats.get('degenerate_count', 0)} faces without area)", icon='ERROR')
            elif stats.get('skipped_no_uvs'):
                box.label(text=f"Skipped (no UVs): {', '.join(stats.get('skipped_no_uvs'))}", icon='CANCEL')
            else:
                box.label(text='Select mesh object(s)', icon='INFO')


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
        name='Show Heatmap',
        default=False,
        options={'SKIP_SAVE'},
        description='Display heatmap overlay on selected mesh objects in the 3D viewport',
        update=_on_toggle_show,
    )

    bpy.types.Scene.fss_uv_heatmap_mode = bpy.props.EnumProperty(
        name='Heatmap Mode',
        items=[
            ('SHAPE', 'Distortion', 'Distortion of each face\'s shape in the UVs (1.0 neutral, > 1.0 stretched or '
                                    'sheared)'),
            ('DENSITY', 'Density', 'Texel density relative to material median and object range (0.5 red, 1.0 neutral, 2.0 blue)'),
            ('VISIBILITY', 'Visibility', 'Visibility from artist cameras (0.0 red, 0.5 neutral, 1.0 blue)'),
        ],
        default='SHAPE',
        options={'SKIP_SAVE'},
        update=_on_mode_change,
    )

    bpy.types.Scene.fss_uv_heatmap_distortion = bpy.props.EnumProperty(
        name='Distortion', default='BOTH', options={'SKIP_SAVE'}, update=_on_mode_change,
        items=[('BOTH', 'Both', 'Shear in blue, area in green, both together in cyan'),
               ('SHEAR', 'Shear', 'How much each face is skewed in the UVs (1.0 = keeps its shape)'),
               ('AREA', 'Area', "How much each face's size differs from the rest of its island (1.0 = same)")])
    bpy.types.Scene.fss_uv_heatmap_grid = bpy.props.BoolProperty(
        name='UV Grid', default=True, update=_on_mode_change,  # saved with the file, on by default
        description='Draw a grid in UV space over the heatmap: stretched UVs show as stretched cells')
    bpy.types.Scene.fss_uv_heatmap_grid_cells = bpy.props.EnumProperty(
        name='Cells', default='16', update=_on_mode_change,
        description='Number of grid cells across the UV square',
        items=[('8', '8 x 8', ''), ('16', '16 x 16', ''), ('32', '32 x 32', ''), ('64', '64 x 64', '')])
    bpy.types.Scene.fss_uv_heatmap_grid_labels = bpy.props.BoolProperty(
        name='Cell Labels', default=True, update=_on_mode_change,
        description='Label each grid cell (column letter, row number) so you can see where a cell ends up')
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
    global _draw_view_handle, _draw_pixel_handle, _shader, _previews, _chart_key, _glyph_texture
    if bpy.app.timers.is_registered(_drop_after_marks):
        bpy.app.timers.unregister(_drop_after_marks)
    _glyph_texture = None
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

    for prop in ('fss_uv_heatmap_show', 'fss_uv_heatmap_mode', 'fss_uv_heatmap_distortion', 'fss_uv_heatmap_opacity',
                 'fss_uv_heatmap_grid', 'fss_uv_heatmap_grid_cells', 'fss_uv_heatmap_grid_labels'):
        if hasattr(bpy.types.Scene, prop):
            delattr(bpy.types.Scene, prop)

    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
