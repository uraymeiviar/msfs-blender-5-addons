"""Object visibility marks, scene LOD settings and explicit viewport preview."""

import math

import blf
import bpy
import gpu
from bpy_extras.view3d_utils import location_3d_to_region_2d
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

from bpy.app.handlers import persistent
from . import lod_model, lod_rules, uv_heatmap

LOD_KEY = lod_model.HIDE_KEY
LOD_HIDDEN_KEY = lod_model.HIDDEN_KEY
_ORTHO_FAKE_FOV = math.radians(1.0)
_AUTO_INTERVAL = 0.15
_text_handle = None
_sphere_handles = []
_SPHERE_COLOR = (1.0, .55, .1, 1.0)
_MESH_BOX_COLOR = (.3, .9, .3, .8)
_ORIGIN_COLOR = (1.0, .2, .2, 1.0)
_VERTEX_COLOR = (1.0, .9, .2, 1.0)
_auto_state = {
    'plan': None,
    'scene_name': None,
    'center': None,
    'applied_level': None,
    'last_ratio': 0.0,
    'region_3d': None,
    'last_view_matrix': None,
    'last_window_matrix': None,
    'ratio_view_matrix': None,
    'ratio_window_matrix': None,
}


def invalidate_auto_plan():
    _auto_state['plan'] = None
    _auto_state['scene_name'] = None
    _auto_state['center'] = None
    _auto_state['applied_level'] = None
    _auto_state['last_view_matrix'] = None
    _auto_state['last_window_matrix'] = None


def _editable(obj):
    return obj.library is None and obj.override_library is None


def parent_interval(obj):
    hide, show = 7, 0
    parent = obj.parent
    while parent is not None:
        hide = min(hide, lod_model.mark(parent, LOD_KEY) or 7)
        show = max(show, lod_model.mark(parent, lod_model.SHOW_KEY))
        parent = parent.parent
    return hide, show


def _tree_depth(obj):
    depth = 0
    while obj.parent is not None:
        depth += 1
        obj = obj.parent
    return depth


def apply_marks(objects, mode, level):
    changed, clamped = 0, set()
    for obj in sorted((o for o in objects if _editable(o)), key=_tree_depth):
        hide, show = parent_interval(obj)
        assigned = min(level, hide) if mode == 'HIDE' else max(level, show) if mode == 'SHOW' else level
        for key in (LOD_KEY, lod_model.SHOW_KEY, lod_model.KEEP_KEY):
            if key in obj:
                del obj[key]
        if mode == 'HIDE':
            obj[LOD_KEY] = assigned
        elif mode == 'SHOW':
            obj[lod_model.SHOW_KEY] = assigned
        elif mode == 'KEEP':
            obj[lod_model.KEEP_KEY] = 1
        changed += 1
        if assigned != level:
            clamped.add(obj)
        queue = list(obj.children)
        while queue:
            child = queue.pop(0)
            if _editable(child):
                hide, show = parent_interval(child)
                own_hide = lod_model.mark(child, LOD_KEY)
                own_show = lod_model.mark(child, lod_model.SHOW_KEY)
                if own_hide and own_hide > hide:
                    child[LOD_KEY] = hide
                    clamped.add(child)
                if own_show and own_show < show:
                    child[lod_model.SHOW_KEY] = show
                    clamped.add(child)
            queue.extend(child.children)
    return changed, len(clamped)


def _find_region_3d(context=None):
    ctx = context or bpy.context
    region_3d = getattr(ctx, 'region_data', None)
    if region_3d is not None:
        return region_3d
    space = getattr(ctx, 'space_data', None)
    if space is not None and getattr(space, 'type', None) == 'VIEW_3D' and getattr(space, 'region_3d', None) is not None:
        return space.region_3d
    wm = getattr(ctx, 'window_manager', None)
    if wm is not None:
        for window in wm.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D' and area.spaces.active and area.spaces.active.region_3d:
                    return area.spaces.active.region_3d
    return _auto_state.get('region_3d')


def viewport_fov_and_location(region_3d):
    """Return (vertical_fov_radians, camera_world_location) from a 3D viewport region.

    Follows lod_tools_msfs_2024/lod_camera.py for perspective and orthographic views.
    """
    m = region_3d.window_matrix
    try:
        m11 = float(m[1][1])
    except (IndexError, TypeError, ValueError):
        return None, None
    if abs(m11) <= 1e-12:
        return None, None
    if region_3d.is_perspective:
        fov_y = 2.0 * math.atan(1.0 / m11)
        cam_pos = region_3d.view_matrix.inverted().translation.copy()
        return fov_y, cam_pos
    ortho_height = 2.0 / m11
    virtual_distance = ortho_height / (2.0 * math.tan(_ORTHO_FAKE_FOV / 2.0))
    forward = region_3d.view_rotation @ Vector((0.0, 0.0, -1.0))
    cam_pos = region_3d.view_location - forward * virtual_distance
    return _ORTHO_FAKE_FOV, cam_pos


def _apply_plan_level(context, plan, level):
    scene = context.scene
    lod_model.restore_filter(context)
    scene.fss_lod_settings.preview_error = ''
    present = plan['decisions'][level].present if level < plan['write_count'] else set()
    if level >= plan['write_count']:
        scene.fss_lod_settings.preview_error = f'LOD{level:02}: not written (first empty LOD{plan["write_count"]:02})'
    hide = getattr(scene, 'fss_lod_preview_display', 'HIDDEN') == 'HIDDEN'
    for obj in context.view_layer.objects:
        if obj.name not in present and obj.visible_get(view_layer=context.view_layer):
            if hide:
                # hidden (the clean preview); save_pre and load_post undo it, so a saved file never keeps it
                obj[LOD_HIDDEN_KEY] = True
                obj.hide_set(True, view_layer=context.view_layer)
                continue
            orig = obj.display_type
            if hasattr(uv_heatmap, '_display_original') and obj.name in uv_heatmap._display_original:
                orig = uv_heatmap._display_original.pop(obj.name)
                if hasattr(uv_heatmap, '_display_active'):
                    uv_heatmap._display_active.discard(obj.name)
            obj[LOD_HIDDEN_KEY] = orig
            obj.display_type = 'BOUNDS'
    _tag_view3d_redraw(context)


def _tag_view3d_redraw(context):
    wm = getattr(context, 'window_manager', None)
    if wm is not None:
        for window in wm.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()


def _ensure_auto_plan(context):
    scene = context.scene
    if _auto_state['plan'] is None or _auto_state['scene_name'] != scene.name:
        plan = lod_model.build_plan(context)
        bounds = plan['bounds']
        center = (Vector(tuple(0.5 * (lo + hi) for lo, hi in zip(*bounds)))
                  if bounds is not None else Vector((0.0, 0.0, 0.0)))
        _auto_state['plan'] = plan
        _auto_state['scene_name'] = scene.name
        _auto_state['center'] = center
        _auto_state['applied_level'] = None
    return _auto_state['plan'], _auto_state['center']


def simulated_min_sizes(settings, plan):
    """minSize per LOD as MSFS applies it (vertex curve included) once Refresh has counted the vertices; the XML
    table before that, and for fs20, which has no vertex curve."""
    if not settings.scanned or plan['target'] != 'fs24':
        return plan['table']
    return lod_rules.effective_min_sizes(plan['table'], list(settings.vertex_estimates), settings.msfs_vertex_factor,
                                         plan['write_count'], lod_rules.QUALITY_FACTORS[settings.msfs_quality])


def update_auto_viewport_lod(context=None, region_3d=None, force=False):
    """Compute bounding-sphere screen ratio from the 3D viewport and apply the filter only when the LOD changes."""
    ctx = context or bpy.context
    scene = getattr(ctx, 'scene', None)
    if scene is None or not getattr(scene, 'fss_viewport_lod_auto', False):
        return False
    r3d = region_3d or _find_region_3d(ctx)
    if r3d is None:
        return False
    if not force and _auto_state['plan'] is not None and _auto_state['scene_name'] == scene.name:
        if (_auto_state['last_view_matrix'] is not None
                and _auto_state['last_window_matrix'] is not None
                and r3d.view_matrix == _auto_state['last_view_matrix']
                and r3d.window_matrix == _auto_state['last_window_matrix']):
            return False
    fov_y, cam_pos = viewport_fov_and_location(r3d)
    if fov_y is None or cam_pos is None:
        return False
    try:
        plan, center = _ensure_auto_plan(ctx)
    except ValueError as error:
        lod_model.restore_filter(ctx)
        scene.fss_lod_settings.preview_error = str(error)
        return False
    _auto_state['last_view_matrix'] = r3d.view_matrix.copy()
    _auto_state['last_window_matrix'] = r3d.window_matrix.copy()
    scale = scene.unit_settings.scale_length
    distance = (cam_pos * scale - center).length
    ratio = lod_rules.screen_ratio(plan['diameter'], distance, fov_y)
    level = lod_rules.lod_from_screen_ratio(ratio, simulated_min_sizes(scene.fss_lod_settings, plan),
                                            plan['write_count'])
    _auto_state['last_ratio'] = ratio
    if not force and _auto_state['applied_level'] == level and scene.fss_viewport_lod == level:
        _tag_view3d_redraw(ctx)  # the same LOD, but the panel's screen ratio and quota moved with the view
        return False
    scene.fss_viewport_lod = level
    _auto_state['applied_level'] = level
    _apply_plan_level(ctx, plan, level)
    return True


def update_view_ratio(context=None):
    """Keep the screen ratio current with the Blender view while Auto is off, for the table in Viewport LOD. Reads the
    LOD sphere of the last Refresh, so it plans nothing and hides nothing; Auto keeps the ratio itself."""
    ctx = context or bpy.context
    scene = getattr(ctx, 'scene', None)
    if scene is None or getattr(scene, 'fss_viewport_lod_auto', False):
        return False
    settings = scene.fss_lod_settings
    if not settings.scanned or settings.lod_diameter <= 0:
        return False
    r3d = _find_region_3d(ctx)
    if r3d is None:
        return False
    if (_auto_state['ratio_view_matrix'] is not None and r3d.view_matrix == _auto_state['ratio_view_matrix']
            and r3d.window_matrix == _auto_state['ratio_window_matrix']):
        return False
    fov_y, cam_pos = viewport_fov_and_location(r3d)
    if fov_y is None or cam_pos is None:
        return False
    _auto_state['ratio_view_matrix'] = r3d.view_matrix.copy()
    _auto_state['ratio_window_matrix'] = r3d.window_matrix.copy()
    center = (Vector(settings.sphere_box[:3]) + Vector(settings.sphere_box[3:])) / 2
    distance = (cam_pos * scene.unit_settings.scale_length - center).length
    _auto_state['last_ratio'] = lod_rules.screen_ratio(settings.lod_diameter, distance, fov_y)
    _tag_view3d_redraw(ctx)
    return True


def _view_ratio_timer():
    try:
        update_view_ratio()
    except Exception:
        pass
    return _AUTO_INTERVAL


def _auto_viewport_timer():
    ctx = bpy.context
    scene = getattr(ctx, 'scene', None)
    if scene is None or not getattr(scene, 'fss_viewport_lod_auto', False):
        return None
    try:
        update_auto_viewport_lod(ctx)
    except Exception:
        return None
    return _AUTO_INTERVAL


def _start_auto_timer():
    if not bpy.app.timers.is_registered(_auto_viewport_timer):
        bpy.app.timers.register(_auto_viewport_timer, first_interval=_AUTO_INTERVAL)


def _stop_auto_timer():
    invalidate_auto_plan()
    _auto_state['region_3d'] = None
    if bpy.app.timers.is_registered(_auto_viewport_timer):
        try:
            bpy.app.timers.unregister(_auto_viewport_timer)
        except ValueError:
            pass


def apply_viewport_lod(context):
    scene = context.scene
    invalidate_auto_plan()
    if getattr(scene, 'fss_viewport_lod_auto', False):
        if update_auto_viewport_lod(context, force=True):
            return
        if scene.fss_lod_settings.preview_error:
            return
        if scene.fss_viewport_lod < 0:
            scene.fss_viewport_lod = 0
    level = scene.fss_viewport_lod
    lod_model.restore_filter(context)
    if level < 0:
        scene.fss_lod_settings.preview_error = ''
        return
    try:
        plan = lod_model.build_plan(context)
    except ValueError as error:
        scene.fss_lod_settings.preview_error = str(error)
        return
    _apply_plan_level(context, plan, level)


def _draw_viewport_lod_text():
    context = bpy.context
    if not context.space_data or not context.space_data.overlay.show_overlays:
        return
    is_auto = getattr(context.scene, 'fss_viewport_lod_auto', False)
    level = context.scene.fss_viewport_lod
    if not is_auto and level < 0:
        return
    if context.scene.fss_lod_settings.preview_error:
        text = context.scene.fss_lod_settings.preview_error
    elif is_auto:
        text = f'Auto LOD{max(0, level)} ({_auto_state["last_ratio"]:.1%})'
    else:
        text = f'Filtered by LOD{level}'
    blf.size(0, 13 * context.preferences.system.ui_scale)
    blf.position(0, 16, 16, 0)
    blf.color(0, 1.0, .78, .25, 1.0)
    blf.draw(0, text)


def _box_lines(lo, hi):
    corners = [Vector((x, y, z)) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
    # Corner indices differ in exactly one bit along an edge
    return [corners[i] for a in range(8) for b in range(a + 1, 8) if bin(a ^ b).count('1') == 1 for i in (a, b)]


def _circle_lines(center, radius, u, v, segments=64):
    points = [center + radius * (math.cos(2 * math.pi * k / segments) * u + math.sin(2 * math.pi * k / segments) * v)
              for k in range(segments + 1)]
    return [p for k in range(segments) for p in (points[k], points[k + 1])]


def _sphere_faces(settings):
    return [h for h in settings.hints if h.kind == 'BOX_FACE']


def _show_sphere(context):
    scene = context.scene
    return (scene.fss_lod_show_sphere and context.space_data.overlay.show_overlays
            and scene.fss_lod_settings.measured_diameter > 0)


def _draw_lod_sphere():
    """The LOD sphere MSFS uses (from the last Refresh), its box, the geometry box, and the point setting each face."""
    context = bpy.context
    if not _show_sphere(context):
        return
    settings = context.scene.fss_lod_settings
    scale = context.scene.unit_settings.scale_length
    lo, hi = Vector(settings.sphere_box[:3]) / scale, Vector(settings.sphere_box[3:]) / scale
    center, radius = (lo + hi) / 2, (settings.lod_diameter or settings.measured_diameter) / 2 / scale
    axes = [Vector(axis) for axis in ((1, 0, 0), (0, 1, 0), (0, 0, 1))]
    groups = [(_SPHERE_COLOR, 2.0, _box_lines(lo, hi)),
              (_SPHERE_COLOR, 1.0, [p for u, v in ((0, 1), (0, 2), (1, 2))
                                    for p in _circle_lines(center, radius, axes[u], axes[v])])]
    if settings.mesh_diameter < settings.measured_diameter - lod_model.FAR_NODE_MARGIN:
        groups.append((_MESH_BOX_COLOR, 1.5, _box_lines(Vector(settings.mesh_box[:3]) / scale,
                                                         Vector(settings.mesh_box[3:]) / scale)))
    marker = radius * .03
    groups.append((_SPHERE_COLOR, 3.0, [p for axis in axes for p in (center - 2 * marker * axis,
                                                                    center + 2 * marker * axis)]))
    for h in _sphere_faces(settings):
        point = Vector(h.point) / scale
        groups.append((_ORIGIN_COLOR if h.from_origin else _VERTEX_COLOR, 2.0,
                       [p for axis in axes for p in (point - marker * axis, point + marker * axis)]))
    region = context.region
    shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')
    shader.bind()
    shader.uniform_float("viewportSize", (region.width, region.height))
    for color, width, lines in groups:
        shader.uniform_float("color", color)
        shader.uniform_float("lineWidth", width)
        batch_for_shader(shader, 'LINES', {"pos": lines}).draw(shader)
    gpu.state.blend_set('NONE')


def _draw_lod_sphere_labels():
    context = bpy.context
    if not _show_sphere(context):
        return
    settings = context.scene.fss_lod_settings
    scale = context.scene.unit_settings.scale_length
    blf.size(0, 12 * context.preferences.system.ui_scale)
    center = (Vector(settings.sphere_box[:3]) + Vector(settings.sphere_box[3:])) / 2
    position = location_3d_to_region_2d(context.region, context.region_data, center / scale)
    if position is not None:
        blf.position(0, position.x + 8, position.y + 4, 0)
        blf.color(0, *_SPHERE_COLOR)
        radius = (settings.lod_diameter or settings.measured_diameter) / 2
        padded = ' (padded)' if settings.lod_diameter > settings.measured_diameter + .01 else ''
        blf.draw(0, f'LOD sphere centre, radius {format_length(radius)}{padded}')
    for h in _sphere_faces(settings):
        position = location_3d_to_region_2d(context.region, context.region_data, Vector(h.point) / scale)
        if position is None:
            continue
        blf.position(0, position.x + 8, position.y + 4, 0)
        blf.color(0, *(_ORIGIN_COLOR if h.from_origin else _VERTEX_COLOR))
        blf.draw(0, f'{h.face} {h.object_name} ({"origin" if h.from_origin else "vertex"})')


def _reference_changed(settings, context):
    settings.lod_diameter = 0.0
    _settings_changed(settings, context)


def _settings_changed(settings, context):
    settings.scanned = False
    invalidate_auto_plan()
    if context and context.scene and (
        context.scene.fss_viewport_lod >= 0 or getattr(context.scene, 'fss_viewport_lod_auto', False)
    ):
        apply_viewport_lod(context)


def format_length(metres):
    if not math.isfinite(metres):
        return 'everything'
    return f'{metres * 100:.1f} cm' if metres < 1 else f'{metres:.2f} m'


def format_percent(value):
    """A percentage short enough for a table column: '364 %', '20 %', '8.8 %', '0.5 %'."""
    return f'{value:.0f} %' if value >= 10 else f'{value:.2g} %'


def format_count(value):
    """A count short enough for a narrow table: '532', '3.48K', '1.11M'."""
    if value >= 999_995:
        return f'{value / 1_000_000:.2f}M'
    return f'{value / 1000:.2f}K' if value >= 1000 else str(value)


def format_step(previous, current):
    """What one LOD step took away: '-1.29K', '0', and '+' if the step added (shared meshes no longer counted once)."""
    removed = previous - current
    return f'-{format_count(removed)}' if removed > 0 else f'+{format_count(-removed)}' if removed < 0 else '0'


def table_row(layout, shares):
    """The cells of one table row, widths as shares of the row (summing to 1); split keeps them lined up across
    rows."""
    cells = []
    rest = 1.0
    split = layout
    for share in shares[:-1]:
        split = split.split(factor=share / rest, align=True)
        cells.append(split.column(align=True))
        rest -= share
    cells.append(split.column(align=True))
    return cells


def _draw_view_quota(layout, scene, ratio):
    """What MSFS does at the Blender view, whatever the viewport preview shows: the LOD it shows, highlighted, and for
    each more detailed LOD the vertices to remove so that it shows here instead."""
    settings = scene.fss_lod_settings
    layout.prop(settings, 'msfs_quality')
    if not settings.scanned:
        layout.label(text='Click Refresh LOD Counts for the quota at this view', icon='INFO')
        return
    quality = lod_rules.QUALITY_FACTORS[settings.msfs_quality]
    quota = lod_rules.vertex_quota_at(ratio, settings.msfs_vertex_factor, quality)
    effective = lod_rules.effective_min_sizes([value / 100.0 for value in settings.min_sizes],
                                              list(settings.vertex_estimates), settings.msfs_vertex_factor,
                                              settings.write_count, quality)
    shown = lod_rules.lod_from_screen_ratio(ratio, effective, settings.write_count)
    last = settings.write_count - 1
    layout.label(text=f'This view: LOD{shown:02} (screen ratio {ratio:.1%})', icon='VIEWZOOM')
    factors = (0.18, 0.23, 0.13, 0.18, 0.28)
    col = layout.column(align=True)
    for cell, text in zip(table_row(col.row(), factors), ('LOD', 'Vert/Obj', 'Used', 'ToReduce', 'Reduced')):
        cell.label(text=text)
    for level in range(settings.write_count):
        cells = table_row(col.row(), factors)
        vertices = settings.vertex_estimates[level]
        objects = settings.counts[level]
        name = f'{level:02} <' + format_length(settings.cutoffs[level]).replace(' ', '') if level else '00 -'
        if level == shown:
            cells[0].operator('fss.lod_view_shown', text=name, depress=True)
        else:
            cells[0].label(text=name)
        cells[1].label(text=f'{format_count(vertices)}/{format_count(objects)}')
        pct = 100.0 * vertices / quota
        cells[2].alert = pct > 100.0
        cells[2].progress(factor=min(pct / 100.0, 1.0), text=format_percent(pct))
        cells[3].label(text=format_count(vertices - quota) if level < shown and vertices > quota else '-')
        # The bar: the share of the previous LOD's vertices this step removed, fair across LODs; the text: the step
        previous = settings.vertex_estimates[level - 1] if level else 0
        cells[4].progress(factor=max(0, previous - vertices) / previous if previous else 0.0, text='-' if not level else
                          f'{format_step(settings.vertex_estimates[level - 1], vertices)}/'
                          f'{format_step(settings.counts[level - 1], objects)}')
    if shown == last and settings.vertex_estimates[last] > quota:
        layout.label(text='Over the limit, shown as the last LOD', icon='INFO')


def _draw_hides_table(layout, settings):
    """The settings per LOD, one table: Hides Under decides what is in the LOD, minSize holds it back from smaller
    screen sizes, and Shows From is the size MSFS needs for it after the last Refresh."""
    layout.label(text='Hides Under: parts smaller than this are left out')
    layout.label(text='minSize: the LOD never shows below this screen size')
    scanned = settings.scanned
    effective = (lod_rules.effective_min_sizes([value / 100.0 for value in settings.min_sizes],
                                               list(settings.vertex_estimates), settings.msfs_vertex_factor,
                                               settings.write_count,
                                               lod_rules.QUALITY_FACTORS[settings.msfs_quality]) if scanned else [])
    shares = (0.12, 0.32, 0.28, 0.28)
    col = layout.column(align=True)
    for cell, text in zip(table_row(col.row(), shares), ('LOD', 'Hides Under', 'minSize %', 'Shows From')):
        cell.label(text=text)
    for level in range(7):
        cells = table_row(col.row(), shares)
        cells[0].label(text=f'{level:02}')
        if level:
            cells[1].prop(settings, 'hide_sizes', index=level, text='')
        else:
            cells[1].label(text='-')
        cells[2].prop(settings, 'min_sizes', index=level, text='')
        if not scanned or level >= settings.write_count:
            cells[3].label(text='-')
        else:
            cells[3].label(text='fallback' if level == settings.write_count - 1
                           else format_percent(effective[level] * 100.0))
    if not scanned:
        layout.label(text='Press Refresh LOD Counts for Shows From', icon='INFO')


def _min_sizes_changed(settings, context):
    # What is in each LOD stands: only when it shows changes, so the counts stay valid and Auto looks again
    invalidate_auto_plan()
    _tag_view3d_redraw(context)


def _quality_changed(settings, context):
    # The counts stand: only what MSFS would show changes, so Auto looks again and the panels redraw
    _auto_state['last_view_matrix'] = None
    _tag_view3d_redraw(context)


class FSS_LodHintItem(bpy.types.PropertyGroup):
    lod_level: bpy.props.IntProperty()
    kind: bpy.props.EnumProperty(items=[
        ('CONTRIBUTOR', 'Largest Contributor', ''),
        ('LOOSE_PIECES', 'Loose Pieces Below Cut-off', ''),
        ('NEAR_CUTOFF', 'Near Cut-off', ''),
        ('FAR_NODE', 'Origin Outside the Geometry', ''),
        ('BOX_FACE', 'Point Setting a Face of the LOD Sphere Box', ''),
    ])
    object_name: bpy.props.StringProperty()
    vertices: bpy.props.IntProperty()
    pieces: bpy.props.IntProperty()
    size_m: bpy.props.FloatProperty()
    cutoff_m: bpy.props.FloatProperty()
    is_merge_group: bpy.props.BoolProperty()
    face: bpy.props.StringProperty()
    point: bpy.props.FloatVectorProperty(size=3)
    from_origin: bpy.props.BoolProperty()


class FSS_LodSettings(bpy.types.PropertyGroup):
    # Screen percent per LOD, written to the XML; low on purpose (see lod_rules.MSFS_MIN_SIZES)
    min_sizes: bpy.props.FloatVectorProperty(name='minSize', size=7, min=0, precision=1,
        default=tuple(value * 100.0 for value in lod_rules.MSFS_MIN_SIZES), update=_min_sizes_changed,
        description='The LOD never shows below this screen size. Low values leave it to the vertex count; a high '
                    'value holds the LOD back. Must not increase from one LOD to the next')
    pad_factor: bpy.props.FloatProperty(name='Pad LOD Sphere Multiplier', default=1.0, min=1.0, max=10.0, precision=2,
        update=_reference_changed,
        description='1 uses the measured LOD sphere. A larger value multiplies the geometry\'s sphere at export '
                    '(invisible corner points): MSFS sees the model larger, so every LOD holds to that many times the '
                    'distance, and heavier LODs are drawn further out')
    # The target diameter of older versions: export still honours it until a Refresh converts it to pad_factor
    reference_size: bpy.props.FloatProperty(min=0, update=_reference_changed)
    lod_diameter: bpy.props.FloatProperty(name='LOD Sphere', min=0, subtype='DISTANCE', unit='LENGTH',
        description='Diameter of the sphere MSFS will use after export (padded or measured), from the last Refresh')
    measured_diameter: bpy.props.FloatProperty(name='Measured Diameter', min=0, subtype='DISTANCE', unit='LENGTH',
        description='Diameter of the sphere MSFS uses for LOD selection: LOD00 geometry and every object origin, '
                    'measured by the last Refresh LOD Counts')
    mesh_diameter: bpy.props.FloatProperty(name='Geometry Diameter', min=0, subtype='DISTANCE', unit='LENGTH',
        description='Diameter of the sphere enclosing LOD00 geometry only, measured by the last Refresh LOD Counts')
    # Boxes in metres (min xyz, max xyz) from the last Refresh LOD Counts, drawn by Show LOD Sphere
    sphere_box: bpy.props.FloatVectorProperty(size=6, options={'SKIP_SAVE'})
    mesh_box: bpy.props.FloatVectorProperty(size=6, options={'SKIP_SAVE'})
    # Metres per LOD; 0 takes the default from the diameter and the SDK's table, and the first Refresh writes it in
    hide_sizes: bpy.props.FloatVectorProperty(name='Hides Under', size=7, min=0, unit='LENGTH', precision=3, step=10,
        description='Parts of this LOD smaller than this are left out', update=_settings_changed)
    screen_height: bpy.props.IntProperty(name='Screen Height (px)', default=1440, min=1, update=_settings_changed)
    pixel_threshold: bpy.props.FloatProperty(name='Pixel Threshold', default=4, min=0, update=_settings_changed)
    msfs_quality: bpy.props.EnumProperty(name='MSFS Quality', default='HIGH', update=_quality_changed,
        description='The graphics setting to predict: a higher one lets each LOD show from a smaller screen size. '
                    'Only High has been checked against the simulator',
        items=[('ULTRA', 'Ultra', ''), ('HIGH', 'High', ''), ('MEDIUM', 'Medium', ''), ('LOW', 'Low', '')])
    msfs_vertex_factor: bpy.props.FloatProperty(name='MSFS Vertex Factor', default=1.15, min=0.5, max=2.0,
        description='MSFS counts vertices differently from the export: measured 0.98 to 1.22 times the file count '
                    '(E2 cockpit). Applied to the vertex estimate (about 5 % above the file) to predict from which '
                    'screen size MSFS shows each LOD')
    keep_tags: bpy.props.StringProperty(name='Keep Tags', update=_settings_changed)
    preview_error: bpy.props.StringProperty(options={'SKIP_SAVE'})
    scanned: bpy.props.BoolProperty(options={'SKIP_SAVE'})
    counts: bpy.props.IntVectorProperty(size=7, options={'SKIP_SAVE'})
    cutoffs: bpy.props.FloatVectorProperty(size=7, options={'SKIP_SAVE'})
    resolved_table: bpy.props.FloatVectorProperty(size=7, options={'SKIP_SAVE'})
    write_count: bpy.props.IntProperty(options={'SKIP_SAVE'})
    vertex_estimates: bpy.props.IntVectorProperty(size=7, options={'SKIP_SAVE'})
    hints: bpy.props.CollectionProperty(type=FSS_LodHintItem, options={'SKIP_SAVE'})
    inspect_lod: bpy.props.IntProperty(name='Inspect LOD', default=0, min=0, max=6, options={'SKIP_SAVE'})


class FSS_OT_LodRefresh(bpy.types.Operator):
    bl_idname = 'fss.lod_refresh'
    bl_label = 'Refresh LOD Counts'
    bl_description = 'Evaluate source bounds, loose pieces, vertex estimates, quotas and hints'

    def execute(self, context):
        settings = context.scene.fss_lod_settings
        try:
            stats = lod_model.estimate_scene_stats(context)
            plan = stats['plan']
            if settings.reference_size > 0:  # a diameter saved by an older version becomes the multiplier, once
                factor = settings.reference_size / plan['mesh_diameter'] if plan['mesh_diameter'] > 0 else 1.0
                settings.reference_size = 0.0
                settings.pad_factor = max(1.0, min(10.0, factor))
            settings.counts =[len(d.present) for d in plan['decisions']]
            settings.cutoffs = [d.cutoff for d in plan['decisions']]
            settings.resolved_table = plan['table']
            settings.write_count = plan['write_count']
            settings.measured_diameter = plan['own_diameter']
            settings.mesh_diameter = plan['mesh_diameter']
            settings.lod_diameter = plan['diameter']
            if plan['bounds'] is not None:
                settings.sphere_box = (*plan['bounds'][0], *plan['bounds'][1])
                settings.mesh_box = (*plan['mesh_bounds'][0], *plan['mesh_bounds'][1])
            settings.vertex_estimates = [s['vertices'] for s in stats['lods']]
            settings.hints.clear()
            for obj_name, outside in plan['far_nodes']:
                item = settings.hints.add()
                item.lod_level = 0
                item.kind = 'FAR_NODE'
                item.object_name = obj_name
                item.size_m = outside
            for face, obj_name, kind, point in plan['extremes']:
                item = settings.hints.add()
                item.lod_level = 0
                item.kind = 'BOX_FACE'
                item.face = face
                item.object_name = obj_name
                item.point = point
                item.from_origin = kind == 'origin'
            for s in stats['lods'][:plan['write_count']]:
                level = s['level']
                for obj_name, verts, is_group in s['contributors']:
                    item = settings.hints.add()
                    item.lod_level = level
                    item.kind = 'CONTRIBUTOR'
                    item.object_name = obj_name
                    item.vertices = verts
                    item.is_merge_group = is_group
                for obj_name, n_pieces, verts, cutoff in s['loose_pieces']:
                    item = settings.hints.add()
                    item.lod_level = level
                    item.kind = 'LOOSE_PIECES'
                    item.object_name = obj_name
                    item.pieces = n_pieces
                    item.vertices = verts
                    item.cutoff_m = cutoff
                for obj_name, size_m, verts in s['near_cutoff']:
                    item = settings.hints.add()
                    item.lod_level = level
                    item.kind = 'NEAR_CUTOFF'
                    item.object_name = obj_name
                    item.size_m = size_m
                    item.vertices = verts
            if settings.inspect_lod >= settings.write_count:
                settings.inspect_lod = max(0, settings.write_count - 1)
            if any(settings.hide_sizes[d] <= 0 and math.isfinite(plan['decisions'][d].cutoff) for d in range(1, 7)):
                settings.hide_sizes = [settings.hide_sizes[d] if d == 0 or settings.hide_sizes[d] > 0
                                       or not math.isfinite(plan['decisions'][d].cutoff)
                                       else plan['decisions'][d].cutoff for d in range(7)]
            settings.scanned = True
            _auto_state['ratio_view_matrix'] = None  # the sphere may have changed: measure the view again
            update_view_ratio(context)
            for warning in plan['decisions'][0].warnings:
                self.report({'WARNING'}, warning)
        except ValueError as error:
            settings.scanned = False
            settings.preview_error = str(error)
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        finally:
            apply_viewport_lod(context)
        return {'FINISHED'}


class FSS_OT_LodSelectHint(bpy.types.Operator):
    bl_idname = 'fss.lod_select_hint'
    bl_label = 'Select'
    bl_description = 'Select this object or merge group root in the 3D View (Shift: add to selection)'
    bl_options = {'REGISTER', 'UNDO'}

    object_name: bpy.props.StringProperty(name='Object')
    extend: bpy.props.BoolProperty(options={'SKIP_SAVE'})

    def invoke(self, context, event):
        self.extend = event.shift
        return self.execute(context)

    def execute(self, context):
        view_layer = context.view_layer
        obj = view_layer.objects.get(self.object_name)
        if obj is None:
            self.report({'WARNING'}, f'Object {self.object_name} not found in view layer')
            return {'CANCELLED'}
        if not obj.visible_get(view_layer=view_layer):
            self.report({'WARNING'}, f'{self.object_name} is currently hidden in the viewport')
            return {'CANCELLED'}
        if not self.extend:
            for other in context.selected_objects:
                other.select_set(False)
        obj.select_set(True)
        view_layer.objects.active = obj
        self.report({'INFO'}, f'Selected {self.object_name}')
        return {'FINISHED'}


class FSS_OT_SetObjectLod(bpy.types.Operator):
    bl_idname = 'fss.set_object_lod'
    bl_label = 'Set Object LOD'
    bl_description = 'Set visibility marks; parent visibility limits still apply'
    bl_options = {'REGISTER', 'UNDO'}
    level: bpy.props.IntProperty(min=0, max=6, default=0)
    mode: bpy.props.EnumProperty(default='HIDE', items=[('AUTO', 'Auto', ''), ('HIDE', 'Hidden from', ''),
                                                       ('SHOW', 'Visible from', ''), ('KEEP', 'Keep', '')])

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects)

    def execute(self, context):
        mode = 'AUTO' if self.level == 0 and self.mode == 'HIDE' else self.mode
        changed, clamped = apply_marks(context.selected_objects, mode, max(1, self.level))
        # Applying any mark ends a pending Hidden from / Visible from choice of the Object LOD panel
        context.window_manager.fss_lod_pending = 'NONE'
        apply_viewport_lod(context)
        self.report({'INFO'}, f'Set {mode} on {changed} object(s); {clamped} clamped by parent')
        return {'FINISHED'}


class FSS_OT_LodPending(bpy.types.Operator):
    bl_idname = 'fss.lod_pending'
    bl_label = 'Choose LOD Mark'
    bl_description = 'Choose this mark, then an LOD number to apply it to the selected objects'
    mode: bpy.props.EnumProperty(default='HIDE', items=[('HIDE', 'Hidden from', ''), ('SHOW', 'Visible from', '')])

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects)

    def execute(self, context):
        # UI state only: the marks change when a number is pressed (fss.set_object_lod)
        context.window_manager.fss_lod_pending = self.mode
        return {'FINISHED'}


_MARK_LABELS = {'AUTO': 'Auto', 'KEEP': 'Keep', 'HIDE': 'Hidden from', 'SHOW': 'Visible from'}


def object_mark(obj):
    """The object's mark as (mode, level): ('AUTO', 0), ('KEEP', 0), ('HIDE', n) or ('SHOW', n)."""
    if obj.get(lod_model.KEEP_KEY):
        return 'KEEP', 0
    hide = lod_model.mark(obj, LOD_KEY)
    if hide:
        return 'HIDE', hide
    show = lod_model.mark(obj, lod_model.SHOW_KEY)
    if show:
        return 'SHOW', show
    return 'AUTO', 0


def mark_text(mark):
    mode, level = mark
    return f'{_MARK_LABELS[mode]} LOD{level}' if level else _MARK_LABELS[mode]


class FSS_OT_SetViewportLod(bpy.types.Operator):
    bl_idname = 'fss.set_viewport_lod'
    bl_label = 'Viewport LOD Filter'
    bl_description = 'Preview export membership; Auto picks LOD by viewport screen size; Off restores hidden objects'
    bl_options = {'REGISTER', 'UNDO'}
    level: bpy.props.IntProperty(min=-2, max=6, default=-1)

    def execute(self, context):
        if self.level == -2:
            context.scene.fss_viewport_lod_auto = True
            _auto_state['region_3d'] = _find_region_3d(context)
            apply_viewport_lod(context)
            _start_auto_timer()
        else:
            context.scene.fss_viewport_lod_auto = False
            _stop_auto_timer()
            context.scene.fss_viewport_lod = self.level
            apply_viewport_lod(context)
        error = context.scene.fss_lod_settings.preview_error
        if error:
            self.report({'WARNING'}, error)
        return {'FINISHED'}


class FSS_OT_LodViewShown(bpy.types.Operator):
    bl_idname = 'fss.lod_view_shown'
    bl_label = 'LOD Shown Here'
    bl_description = 'The LOD MSFS shows at this view'
    bl_options = {'INTERNAL'}

    def execute(self, context):
        return {'FINISHED'}


class FSS_OT_LodPrintSettings(bpy.types.Operator):
    bl_idname = 'fss.lod_print_settings'
    bl_label = 'Print LOD Settings / XML'
    base_name: bpy.props.StringProperty(name='Model Base Name', default='MODEL')

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)

    def execute(self, context):
        import xml.sax.saxutils
        try:
            plan = lod_model.build_plan(context)
            print('<LODS>')
            for level, value in enumerate(plan['table'][:plan['write_count']]):
                filename = xml.sax.saxutils.quoteattr(f'{self.base_name}_LOD{level:02}.gltf')
                print(f'    <LOD minSize="{value * 100:g}" ModelFile={filename}/>')
            print('</LODS>')
            for level, decision in enumerate(plan['decisions'][:plan['write_count']]):
                print(f'[FSS LOD] _LOD{level:02}: {len(decision.present)} objects, cut-off {decision.cutoff:g} m')
                for warning in decision.warnings:
                    print(f'[FSS LOD] WARNING {warning}')
            lod_model.report_end(plan)
        except ValueError as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        finally:
            apply_viewport_lod(context)
        return {'FINISHED'}


class FSS_PT_Lod(bpy.types.Panel):
    bl_idname = 'FSS_PT_lod'
    bl_label = 'Object LOD'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'FSS MSFS Tools'
    bl_order = 3

    def draw(self, context):
        layout = self.layout
        active = context.active_object
        selected = context.selected_objects
        if selected:
            count = f'{len(selected)} object' + ('' if len(selected) == 1 else 's')
            layout.label(text=f'Selected: {count} (active: {active.name})' if active else f'Selected: {count}')
        else:
            layout.label(text='Select objects to mark them', icon='INFO')
        active_mark = object_mark(active) if active is not None else None
        if active_mark is not None:
            layout.label(text=f'Active object: {mark_text(active_mark)}')
        if len({object_mark(obj) for obj in selected}) > 1:
            layout.label(text='Selected objects: mixed marks', icon='INFO')
        # The pressed mark follows a pending Hidden from / Visible from choice, else the active object's mark
        pending = context.window_manager.fss_lod_pending
        shown = pending if pending != 'NONE' else active_mark[0] if active_mark is not None else None
        row = layout.row(align=True)
        for mode in ('AUTO', 'KEEP'):
            row.operator('fss.set_object_lod', text=_MARK_LABELS[mode], depress=shown == mode).mode = mode
        for mode in ('HIDE', 'SHOW'):
            row.operator('fss.lod_pending', text=_MARK_LABELS[mode], depress=shown == mode).mode = mode
        if shown in ('HIDE', 'SHOW'):
            # Decision 23: the row lights the LODs where the object is visible; the clicked LOD is the last visible
            # one (Hidden from n + 1) or the first (Visible from n), so it is always lit
            layout.label(text='Visible in:')
            row = layout.row(align=True)
            for lod in range(7):
                level = lod + 1 if shown == 'HIDE' else lod
                visible = active_mark is not None and active_mark[0] == shown and (
                    lod < active_mark[1] if shown == 'HIDE' else lod >= active_mark[1])
                cell = row.row(align=True)
                cell.enabled = 1 <= level <= 6
                op = cell.operator('fss.set_object_lod', text=str(lod), depress=visible)
                op.mode, op.level = shown, max(1, min(6, level))


class FSS_PT_LodViewport(bpy.types.Panel):
    bl_idname = 'FSS_PT_lod_viewport'
    bl_label = 'Viewport LOD'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'FSS MSFS Tools'
    bl_order = 4

    def draw(self, context):
        layout = self.layout
        row = layout.row(align=True)
        is_auto = getattr(context.scene, 'fss_viewport_lod_auto', False)
        row.operator('fss.set_viewport_lod', text='Off',
                     depress=not is_auto and context.scene.fss_viewport_lod < 0).level = -1
        row.operator('fss.set_viewport_lod', text='Auto', depress=is_auto).level = -2
        for level in range(7):
            row.operator('fss.set_viewport_lod', text=str(level),
                         depress=context.scene.fss_viewport_lod == level).level = level
        previewing = is_auto or context.scene.fss_viewport_lod >= 0
        if previewing:  # Off excludes nothing, so the choice of how excluded objects show only appears with a preview
            row = layout.row(align=True)
            row.label(text='Excluded')
            row.prop(context.scene, 'fss_lod_preview_display', expand=True)
        if previewing and context.scene.fss_lod_preview_display == 'HIDDEN':
            layout.label(text='Excluded objects hidden: set Viewport LOD Off before exporting by hand', icon='INFO')
        if context.scene.fss_lod_settings.preview_error:
            layout.label(text=context.scene.fss_lod_settings.preview_error, icon='ERROR')


class FSS_PT_LodSettings(bpy.types.Panel):
    bl_idname = 'FSS_PT_lod_settings'
    bl_label = 'LOD Settings'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'FSS MSFS Tools'
    bl_order = 5

    def draw(self, context):
        layout = self.layout
        layout.operator('fss.lod_refresh', icon='FILE_REFRESH')
        settings = context.scene.fss_lod_settings
        if settings.scanned:
            layout.label(text='Cached counts: Refresh after editing')
        _draw_view_quota(layout, context.scene, _auto_state['last_ratio'])
        if settings.scanned and settings.write_count < 7:
            layout.label(text=f'LOD{settings.write_count:02}: not written, no objects', icon='INFO')


class FSS_PT_LodQuotaHints(bpy.types.Panel):
    bl_idname = 'FSS_PT_lod_quota_hints'
    bl_label = 'Hints'
    bl_parent_id = 'FSS_PT_lod_settings'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'FSS MSFS Tools'

    def draw(self, context):
        layout = self.layout
        settings = context.scene.fss_lod_settings
        if not settings.scanned:
            layout.label(text='Click Refresh LOD Counts to compute estimates', icon='INFO')
            return
        layout.label(text='Per LOD Vertex Contributors')
        sel_row = layout.row(align=True)
        active_lod = (context.scene.fss_viewport_lod
                      if 0 <= context.scene.fss_viewport_lod < settings.write_count
                      else min(settings.inspect_lod, max(0, settings.write_count - 1)))
        for level in range(settings.write_count):
            op = sel_row.operator('fss.lod_inspect_level', text=str(level), depress=(level == active_lod))
            op.level = level

        lod_hints = [h for h in settings.hints if h.lod_level == active_lod]
        contributors = [h for h in lod_hints if h.kind == 'CONTRIBUTOR'][:5]
        loose = [h for h in lod_hints if h.kind == 'LOOSE_PIECES'][:5]
        near = [h for h in lod_hints if h.kind == 'NEAR_CUTOFF'][:5]

        box = layout.box()
        total = settings.vertex_estimates[active_lod]
        box.label(text=f'LOD{active_lod:02}: ~{total:,} vtx', icon='MESH_DATA')
        if contributors:
            # A bar per contributor for its share of the LOD's vertices (decision 25 C)
            for h in contributors:
                r = box.row(align=True)
                name_cell, bar_cell = table_row(r, (0.5, 0.5))
                name_cell.label(text=h.object_name)
                share = 100.0 * h.vertices / total if total else 0.0
                bar_cell.progress(factor=min(share / 100.0, 1.0), text=f'~{h.vertices:,} ({format_percent(share)})')
                r.operator('fss.lod_select_hint', text='', icon='RESTRICT_SELECT_OFF').object_name = h.object_name
        else:
            box.label(text='None')

        if active_lod > 0:
            box = layout.box()
            box.label(text=f'Loose pieces below {settings.cutoffs[active_lod]:.4g} m (dropped at export):',
                      icon='MOD_EXPLODE')
            if loose:
                for h in loose:
                    r = box.row(align=True)
                    r.label(text=f'{h.object_name}: {h.pieces:,} pcs, ~{h.vertices:,} vtx')
                    r.operator('fss.lod_select_hint', text='', icon='RESTRICT_SELECT_OFF').object_name = h.object_name
            else:
                box.label(text='None')

            box = layout.box()
            box.label(text=f'Near cut-off ({settings.cutoffs[active_lod]:.4g} m, candidates to hide):',
                      icon='FILTER')
            if near:
                for h in near:
                    r = box.row(align=True)
                    r.label(text=f'{h.object_name} ({h.size_m:.3g} m): ~{h.vertices:,} vtx')
                    r.operator('fss.lod_select_hint', text='', icon='RESTRICT_SELECT_OFF').object_name = h.object_name
            else:
                box.label(text='None')


class FSS_OT_LodInspectLevel(bpy.types.Operator):
    bl_idname = 'fss.lod_inspect_level'
    bl_label = 'Inspect LOD Hints'
    bl_description = 'Show the hints for this LOD level'
    level: bpy.props.IntProperty(min=0, max=6, default=0)

    def execute(self, context):
        context.scene.fss_lod_settings.inspect_lod = self.level
        return {'FINISHED'}


class FSS_PT_LodExport(bpy.types.Panel):
    bl_idname = 'FSS_PT_lod_export'
    bl_label = 'Export Settings'
    bl_parent_id = 'FSS_PT_lod_settings'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'FSS MSFS Tools'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.fss_lod_settings
        if settings.measured_diameter > 0:
            layout.label(text=f'Model diameter: {format_length(settings.measured_diameter)} (measured at Refresh)')
            far = [h for h in settings.hints if h.kind == 'FAR_NODE']
            if far and settings.lod_diameter:  # 0: the padding changed, these were measured with the old one
                # MSFS's LOD sphere encloses every node: far origins move and enlarge it, so LODs switch elsewhere
                box = layout.box()
                if settings.pad_factor > 1.0:
                    box.label(text=f'{len(far)} origins outside the padding: LOD sphere '
                                   f'{format_length(settings.pad_factor * settings.mesh_diameter)} -> '
                                   f'{format_length(settings.lod_diameter)}', icon='ERROR')
                else:
                    box.label(text=f'{len(far)} origins outside the geometry: LOD sphere '
                                   f'{format_length(settings.mesh_diameter)} -> {format_length(settings.lod_diameter)}',
                              icon='ERROR')
                for h in far[:5]:
                    r = box.row(align=True)
                    r.label(text=f'{h.object_name}: {format_length(h.size_m)} outside')
                    r.operator('fss.lod_select_hint', text='', icon='RESTRICT_SELECT_OFF').object_name = h.object_name
                box.label(text='Move these origins into the geometry, or the empties out of this model')
            layout.prop(context.scene, 'fss_lod_show_sphere', toggle=True, icon='SPHERE')
        else:
            layout.label(text='Model diameter: not measured yet, press Refresh LOD Counts', icon='INFO')
        layout.prop(settings, 'pad_factor')
        if settings.mesh_diameter <= 0:
            layout.label(text='Press Refresh LOD Counts to measure the model')
        elif not settings.lod_diameter:
            layout.label(text='Press Refresh LOD Counts to apply', icon='INFO')
        elif settings.pad_factor <= 1.0:
            layout.label(text=f'MSFS sees: {format_length(settings.lod_diameter)} (no padding)')
        else:
            layout.label(text=f'MSFS sees: {format_length(settings.lod_diameter)} '
                              f'(geometry {format_length(settings.mesh_diameter)})')
        if settings.pad_factor > 5.0:
            layout.label(text='Above 5x has not been tested in the simulator', icon='INFO')

        _draw_hides_table(layout, settings)
        layout.operator('fss.lod_print_settings', icon='CONSOLE')


class FSS_PT_LodExportAdvanced(bpy.types.Panel):
    bl_idname = 'FSS_PT_lod_export_advanced'
    bl_label = 'Advanced'
    bl_parent_id = 'FSS_PT_lod_export'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'FSS MSFS Tools'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.fss_lod_settings
        layout.prop(settings, 'msfs_vertex_factor')


def _on_preview_display_change(self, context):
    if getattr(self, 'fss_viewport_lod_auto', False) or self.fss_viewport_lod >= 0:
        apply_viewport_lod(context)


@persistent
def _on_save_pre(*_dummy):
    lod_model.restore_filter(bpy.context)


@persistent
def _on_save_post(*_dummy):
    context = bpy.context
    scene = getattr(context, 'scene', None)
    if scene is not None:
        if getattr(scene, 'fss_viewport_lod_auto', False) or scene.fss_viewport_lod >= 0:
            apply_viewport_lod(context)


@persistent
def _on_load_post(*_dummy):
    _stop_auto_timer()
    lod_model.restore_filter(bpy.context)
    for scene in bpy.data.scenes:
        scene.fss_viewport_lod = -1


CLASSES = (FSS_LodHintItem, FSS_LodSettings, FSS_OT_LodRefresh, FSS_OT_LodSelectHint, FSS_OT_LodInspectLevel,
           FSS_OT_SetObjectLod, FSS_OT_LodPending, FSS_OT_SetViewportLod, FSS_OT_LodViewShown, FSS_OT_LodPrintSettings,
           FSS_PT_Lod, FSS_PT_LodViewport, FSS_PT_LodSettings, FSS_PT_LodQuotaHints,
           FSS_PT_LodExport, FSS_PT_LodExportAdvanced)


def register():
    global _text_handle
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.fss_lod_settings = bpy.props.PointerProperty(type=FSS_LodSettings)
    # The Object LOD panel's chosen Hidden from / Visible from before a number is pressed (UI only, not saved)
    bpy.types.WindowManager.fss_lod_pending = bpy.props.EnumProperty(
        name='Pending LOD Mark', default='NONE', options={'SKIP_SAVE'},
        items=[('NONE', 'None', ''), ('HIDE', 'Hidden from', ''), ('SHOW', 'Visible from', '')])
    bpy.types.Scene.fss_viewport_lod = bpy.props.IntProperty(default=-1, min=-1, max=6)
    bpy.types.Scene.fss_viewport_lod_auto = bpy.props.BoolProperty(default=False, options={'SKIP_SAVE'})
    bpy.types.Scene.fss_lod_preview_display = bpy.props.EnumProperty(
        name='Excluded', default='HIDDEN', update=_on_preview_display_change,
        description='How the viewport LOD preview shows objects that are not in the previewed LOD',
        items=[('HIDDEN', 'Hidden', 'Hide them: a clean view of what the LOD keeps'),
               ('BOUNDS', 'Bounds', 'Show them as box outlines: where the excluded parts are')])
    bpy.types.Scene.fss_lod_export_level = bpy.props.IntProperty(default=-1, min=-1, max=6, options={'SKIP_SAVE'})
    bpy.types.Scene.fss_lod_show_sphere = bpy.props.BoolProperty(
        name='Show LOD Sphere', default=False, options={'SKIP_SAVE'},
        description='Draw the sphere MSFS uses for LOD selection, its box, and the vertex or origin setting each face '
                    '(from the last Refresh LOD Counts)')
    if not bpy.app.background:
        bpy.app.timers.register(_view_ratio_timer, first_interval=_AUTO_INTERVAL, persistent=True)
        _text_handle = bpy.types.SpaceView3D.draw_handler_add(_draw_viewport_lod_text, (), 'WINDOW', 'POST_PIXEL')
        for draw, kind in ((_draw_lod_sphere, 'POST_VIEW'), (_draw_lod_sphere_labels, 'POST_PIXEL')):
            _sphere_handles.append(bpy.types.SpaceView3D.draw_handler_add(draw, (), 'WINDOW', kind))
    for handlers, handler in ((bpy.app.handlers.save_pre, _on_save_pre),
                              (bpy.app.handlers.save_post, _on_save_post),
                              (bpy.app.handlers.load_post, _on_load_post)):
        if handler not in handlers:
            handlers.append(handler)


def unregister():
    global _text_handle
    _stop_auto_timer()
    if bpy.app.timers.is_registered(_view_ratio_timer):
        bpy.app.timers.unregister(_view_ratio_timer)
    lod_model.restore_filter(bpy.context)
    for handlers, handler in ((bpy.app.handlers.save_pre, _on_save_pre),
                              (bpy.app.handlers.save_post, _on_save_post),
                              (bpy.app.handlers.load_post, _on_load_post)):
        if handler in handlers:
            handlers.remove(handler)
    if _text_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_text_handle, 'WINDOW')
        _text_handle = None
    while _sphere_handles:
        bpy.types.SpaceView3D.draw_handler_remove(_sphere_handles.pop(), 'WINDOW')
    for name in ('fss_lod_settings', 'fss_viewport_lod', 'fss_viewport_lod_auto', 'fss_lod_preview_display',
                 'fss_lod_export_level',
                 'fss_lod_show_sphere'):
        delattr(bpy.types.Scene, name)
    del bpy.types.WindowManager.fss_lod_pending
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
