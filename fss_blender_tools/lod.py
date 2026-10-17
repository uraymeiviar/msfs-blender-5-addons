"""Object visibility marks, scene LOD settings and explicit viewport preview."""

import math

import blf
import bpy
import gpu
from bpy_extras.view3d_utils import location_3d_to_region_2d
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

from . import lod_model, lod_rules

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
    for obj in context.view_layer.objects:
        if obj.name not in present and obj.visible_get(view_layer=context.view_layer):
            obj[LOD_HIDDEN_KEY] = True
            obj.hide_set(True, view_layer=context.view_layer)
    wm = getattr(context, 'window_manager', None)
    if wm is not None:
        for window in wm.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()


def _ensure_auto_plan(context):
    scene = context.scene
    if _auto_state['plan'] is None or _auto_state['scene_name'] != scene.name:
        plan = lod_model.build_plan(context, scene.fss_lod_settings.preview_target)
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
                                         plan['write_count'])


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
        return False
    scene.fss_viewport_lod = level
    _auto_state['applied_level'] = level
    _apply_plan_level(ctx, plan, level)
    return True


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
        plan = lod_model.build_plan(context, scene.fss_lod_settings.preview_target)
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
    center, radius = (lo + hi) / 2, (hi - lo).length / 2
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
        blf.draw(0, f'LOD sphere centre, radius {format_length(settings.measured_diameter / 2)}')
    for h in _sphere_faces(settings):
        position = location_3d_to_region_2d(context.region, context.region_data, Vector(h.point) / scale)
        if position is None:
            continue
        blf.position(0, position.x + 8, position.y + 4, 0)
        blf.color(0, *(_ORIGIN_COLOR if h.from_origin else _VERTEX_COLOR))
        blf.draw(0, f'{h.face} {h.object_name} ({"origin" if h.from_origin else "vertex"})')


def _settings_changed(settings, context):
    settings.scanned = False
    invalidate_auto_plan()
    if context and context.scene and (
        context.scene.fss_viewport_lod >= 0 or getattr(context.scene, 'fss_viewport_lod_auto', False)
    ):
        apply_viewport_lod(context)


def _fs24_table_changed(settings, context):
    settings.explicit_fs24 = True
    if not settings.explicit_fs20:
        settings['min_sizes_fs20'] = tuple(settings.min_sizes_fs24)
    _settings_changed(settings, context)


def _fs20_table_changed(settings, context):
    settings.explicit_fs20 = True
    _settings_changed(settings, context)


def last_lod(settings):
    """The lowest-detail LOD the export can write: interiors stop at LOD05 (decision 16)."""
    return 5 if settings.model_type == 'INTERIOR' else 6


def cutoff_context(settings):
    """(diameter, minSize table) behind the size cut-offs, or (None, reason) when they cannot be computed yet.

    Uses the same inputs as lod_model.build_plan: the override diameter, else the diameter measured at the last
    Refresh, and the minSize table of the preview target.
    """
    measured = settings.measured_diameter
    diameter = settings.reference_size or measured
    if diameter <= 0 or (settings.model_type == 'INTERIOR' and measured <= 0):
        return None, 'Press Refresh LOD Counts to measure the model'
    target = settings.preview_target
    explicit = getattr(settings, 'explicit_' + target) or (target == 'fs20' and settings.explicit_fs24)
    try:
        table = lod_rules.min_sizes(settings.model_type, explicit, getattr(settings, 'min_sizes_' + target),
                                    measured or diameter, settings.exterior_diameter, target)
    except ValueError as error:
        return None, str(error)
    return (diameter, table), ''


def cutoff_for_level(settings, inputs, level):
    """Parts smaller than this (metres) are hidden from LOD level; same formula as lod_rules.decide."""
    diameter, table = inputs
    upper = table[level - 1]
    return diameter * settings.pixel_threshold / (upper * settings.screen_height) if upper > 0 else math.inf


def format_length(metres):
    if not math.isfinite(metres):
        return 'everything'
    return f'{metres * 100:.1f} cm' if metres < 1 else f'{metres:.2f} m'


def _get_lowest_cutoff(settings):
    inputs, _reason = cutoff_context(settings)
    return cutoff_for_level(settings, inputs, last_lod(settings)) if inputs else 0.0


def _set_lowest_cutoff(settings, value):
    inputs, _reason = cutoff_context(settings)
    if not inputs or value <= 0:
        return
    diameter, table = inputs
    # Inverse of the cut-off formula; written directly so dragging does not re-plan the scene on every step
    settings['pixel_threshold'] = value * table[last_lod(settings) - 1] * settings.screen_height / diameter
    settings.scanned = False
    invalidate_auto_plan()


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
    model_type: bpy.props.EnumProperty(name='Model Type', default='EXTERIOR', update=_settings_changed,
        items=[('EXTERIOR', 'Exterior part', ''), ('INTERIOR', 'Interior', ''), ('SCENERY', 'Scenery', '')])
    min_sizes_fs24: bpy.props.FloatVectorProperty(name='FS24 minSize', size=7, min=0,
        default=lod_rules.DEFAULT_MIN_SIZES, update=_fs24_table_changed)
    min_sizes_fs20: bpy.props.FloatVectorProperty(name='FS20 minSize (unverified)', size=7, min=0,
        default=lod_rules.DEFAULT_MIN_SIZES, update=_fs20_table_changed)
    explicit_fs24: bpy.props.BoolProperty(default=False)
    explicit_fs20: bpy.props.BoolProperty(default=False)
    exterior_diameter: bpy.props.FloatProperty(name='Exterior Diameter (m)', min=0, update=_settings_changed)
    reference_size: bpy.props.FloatProperty(name='Override Diameter', min=0, subtype='DISTANCE', unit='LENGTH',
        update=_settings_changed,
        description='0 uses the measured model diameter; set the diameter of the whole model when this .blend is '
                    'merged into a bigger one at runtime (wings, winglets)')
    measured_diameter: bpy.props.FloatProperty(name='Measured Diameter', min=0, subtype='DISTANCE', unit='LENGTH',
        description='Diameter of the sphere MSFS uses for LOD selection: LOD00 geometry and every object origin, '
                    'measured by the last Refresh LOD Counts')
    mesh_diameter: bpy.props.FloatProperty(name='Geometry Diameter', min=0, subtype='DISTANCE', unit='LENGTH',
        description='Diameter of the sphere enclosing LOD00 geometry only, measured by the last Refresh LOD Counts')
    # Boxes in metres (min xyz, max xyz) from the last Refresh LOD Counts, drawn by Show LOD Sphere
    sphere_box: bpy.props.FloatVectorProperty(size=6, options={'SKIP_SAVE'})
    mesh_box: bpy.props.FloatVectorProperty(size=6, options={'SKIP_SAVE'})
    lowest_cutoff: bpy.props.FloatProperty(name='Smallest Part Kept', min=0, subtype='DISTANCE', unit='LENGTH',
        get=_get_lowest_cutoff, set=_set_lowest_cutoff, precision=1, step=10,
        description='Parts smaller than this are hidden from the lowest-detail LOD; every other LOD hides '
                    'proportionally smaller parts')
    screen_height: bpy.props.IntProperty(name='Screen Height (px)', default=1440, min=1, update=_settings_changed)
    pixel_threshold: bpy.props.FloatProperty(name='Pixel Threshold', default=4, min=0, update=_settings_changed)
    msfs_vertex_factor: bpy.props.FloatProperty(name='MSFS Vertex Factor', default=1.15, min=0.5, max=2.0,
        description='MSFS counts vertices differently from the export: measured 0.98 to 1.22 times the file count '
                    '(E2 cockpit). Applied to the vertex estimate (about 5 % above the file) to predict from which '
                    'screen size MSFS shows each LOD')
    keep_tags: bpy.props.StringProperty(name='Keep Tags', update=_settings_changed)
    preview_target: bpy.props.EnumProperty(name='Preview Target', default='fs24', update=_settings_changed,
        items=[('fs24', 'MSFS 2024', ''), ('fs20', 'MSFS 2020 (unverified)', '')])
    preview_error: bpy.props.StringProperty(options={'SKIP_SAVE'})
    scanned: bpy.props.BoolProperty(options={'SKIP_SAVE'})
    counts: bpy.props.IntVectorProperty(size=7, options={'SKIP_SAVE'})
    cutoffs: bpy.props.FloatVectorProperty(size=7, options={'SKIP_SAVE'})
    resolved_table: bpy.props.FloatVectorProperty(size=7, options={'SKIP_SAVE'})
    write_count: bpy.props.IntProperty(options={'SKIP_SAVE'})
    vertex_estimates: bpy.props.IntVectorProperty(size=7, options={'SKIP_SAVE'})
    quotas: bpy.props.IntVectorProperty(size=7, options={'SKIP_SAVE'})
    quota_percents: bpy.props.FloatVectorProperty(size=7, options={'SKIP_SAVE'})
    over_quota: bpy.props.BoolVectorProperty(size=7, options={'SKIP_SAVE'})
    dropped_pieces: bpy.props.IntVectorProperty(size=7, options={'SKIP_SAVE'})
    dropped_vertices: bpy.props.IntVectorProperty(size=7, options={'SKIP_SAVE'})
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
            settings.counts = [len(d.present) for d in plan['decisions']]
            settings.cutoffs = [d.cutoff for d in plan['decisions']]
            settings.resolved_table = plan['table']
            settings.write_count = plan['write_count']
            settings.measured_diameter = plan['own_diameter']
            settings.mesh_diameter = plan['mesh_diameter']
            if plan['bounds'] is not None:
                settings.sphere_box = (*plan['bounds'][0], *plan['bounds'][1])
                settings.mesh_box = (*plan['mesh_bounds'][0], *plan['mesh_bounds'][1])
            settings.vertex_estimates = [s['vertices'] for s in stats['lods']]
            settings.quotas = [s['quota'] for s in stats['lods']]
            settings.quota_percents = [s['percent'] for s in stats['lods']]
            settings.over_quota = [s['over'] for s in stats['lods']]
            settings.dropped_pieces = [s['dropped_pieces'] for s in stats['lods']]
            settings.dropped_vertices = [s['dropped_vertices'] for s in stats['lods']]
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
            settings.scanned = True
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
        apply_viewport_lod(context)
        self.report({'INFO'}, f'Set {mode} on {changed} object(s); {clamped} clamped by parent')
        return {'FINISHED'}


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


class FSS_OT_LodPrintSettings(bpy.types.Operator):
    bl_idname = 'fss.lod_print_settings'
    bl_label = 'Print LOD Settings / XML'
    base_name: bpy.props.StringProperty(name='Model Base Name', default='MODEL')

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)

    def execute(self, context):
        import xml.sax.saxutils
        try:
            plan = lod_model.build_plan(context, context.scene.fss_lod_settings.preview_target)
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


class FSS_OT_LodEditTable(bpy.types.Operator):
    bl_idname = 'fss.lod_edit_table'
    bl_label = 'Edit Explicit minSize Table'
    bl_options = {'REGISTER', 'UNDO'}
    target: bpy.props.EnumProperty(items=[('fs24', 'FS24', ''), ('fs20', 'FS20 (unverified)', '')])
    values: bpy.props.FloatVectorProperty(size=7, min=0, default=lod_rules.DEFAULT_MIN_SIZES)

    def invoke(self, context, event):
        settings = context.scene.fss_lod_settings
        self.values = getattr(settings, 'min_sizes_' + self.target)
        try:
            self.values = lod_model.build_plan(context, self.target)['table']
        except ValueError:
            # The user can explicitly author a table without a known exterior diameter.
            pass
        finally:
            apply_viewport_lod(context)
        return context.window_manager.invoke_props_dialog(self, width=350)

    def draw(self, context):
        self.layout.label(text='Explicit screen ratios: 1 = 100%')
        self.layout.label(text='No exterior diameter is needed for this table')
        for level in range(7):
            self.layout.prop(self, 'values', index=level, text=f'LOD{level:02}')

    def execute(self, context):
        try:
            lod_rules.min_sizes('INTERIOR', True, self.values, 0, 0, self.target)
        except ValueError as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        setattr(context.scene.fss_lod_settings, 'min_sizes_' + self.target, self.values)
        return {'FINISHED'}


class FSS_PT_Lod(bpy.types.Panel):
    bl_idname = 'FSS_PT_lod'
    bl_label = 'LOD'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'FSS Tools'

    def draw(self, context):
        layout = self.layout
        active = context.active_object
        row = layout.row(align=True)
        for mode, label in [('AUTO', 'Auto'), ('KEEP', 'Keep')]:
            marked = (active is not None and (bool(active.get(lod_model.KEEP_KEY)) if mode == 'KEEP' else
                      not any(active.get(key) for key in (LOD_KEY, lod_model.SHOW_KEY, lod_model.KEEP_KEY))))
            row.operator('fss.set_object_lod', text=label, depress=marked).mode = mode
        for mode, label, key in [('HIDE', 'Hidden from', LOD_KEY), ('SHOW', 'Visible from', lod_model.SHOW_KEY)]:
            layout.label(text=label)
            row = layout.row(align=True)
            for level in range(1, 7):
                op = row.operator('fss.set_object_lod', text=str(level),
                                  depress=active is not None and lod_model.mark(active, key) == level)
                op.mode, op.level = mode, level
        layout.label(text='Viewport LOD')
        row = layout.row(align=True)
        is_auto = getattr(context.scene, 'fss_viewport_lod_auto', False)
        row.operator('fss.set_viewport_lod', text='Off',
                     depress=not is_auto and context.scene.fss_viewport_lod < 0).level = -1
        row.operator('fss.set_viewport_lod', text='Auto', depress=is_auto).level = -2
        for level in range(7):
            row.operator('fss.set_viewport_lod', text=str(level),
                         depress=context.scene.fss_viewport_lod == level).level = level
        if is_auto and not context.scene.fss_lod_settings.preview_error:
            lvl = max(0, context.scene.fss_viewport_lod)
            layout.label(text=f'Auto: LOD{lvl:02} (screen ratio {_auto_state["last_ratio"]:.1%})', icon='VIEWZOOM')
        if context.scene.fss_lod_settings.preview_error:
            layout.label(text=context.scene.fss_lod_settings.preview_error, icon='ERROR')
        layout.operator('fss.lod_refresh', icon='FILE_REFRESH')
        settings = context.scene.fss_lod_settings
        if settings.scanned:
            layout.label(text='Cached source counts — Refresh after editing')
            for level in range(settings.write_count):
                text = f'LOD{level:02}: {settings.counts[level]} obj'
                if settings.dropped_pieces[level]:
                    text += f', -{settings.dropped_pieces[level]} pcs'
                if level:
                    text += f'; hides < {format_length(settings.cutoffs[level])}'
                layout.label(text=text)
            if settings.write_count < 7:
                layout.label(text=f'LOD{settings.write_count:02}: not written, no objects', icon='INFO')


class FSS_PT_LodQuotaHints(bpy.types.Panel):
    bl_idname = 'FSS_PT_lod_quota_hints'
    bl_label = 'Quota and Hints'
    bl_parent_id = 'FSS_PT_lod'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'FSS Tools'

    def draw(self, context):
        layout = self.layout
        settings = context.scene.fss_lod_settings
        if not settings.scanned:
            layout.label(text='Click Refresh LOD Counts to compute estimates', icon='INFO')
            return
        layout.label(text='Vertex estimates (per material/UV/normal corner, High quota):')
        layout.label(text='MSFS from: where MSFS shows the LOD (minSize or vertex curve, whichever is larger)')
        effective = lod_rules.effective_min_sizes(settings.resolved_table, list(settings.vertex_estimates),
                                                  settings.msfs_vertex_factor, settings.write_count)
        col = layout.column(align=True)
        for level in range(settings.write_count):
            verts = settings.vertex_estimates[level]
            quota = settings.quotas[level]
            pct = settings.quota_percents[level]
            over = settings.over_quota[level]
            row = col.row(align=True)
            if settings.preview_target == 'fs20':
                row.label(text=f'_LOD{level:02}  ~{verts:,} vtx (FS20: no vertex curve)')
                continue
            fallback = '  (fallback: last LOD)' if level == settings.write_count - 1 else ''
            text = f'_LOD{level:02}  ~{verts:,} / {quota:,}  {pct:.0f}%  MSFS from {effective[level]:.1%}{fallback}'
            if over:
                row.alert = True
                row.label(text=text, icon='ERROR')
            else:
                row.label(text=text, icon='CHECKMARK')
            if settings.dropped_pieces[level]:
                sub = col.row(align=True)
                sub.enabled = False
                sub.label(text=f'    -{settings.dropped_pieces[level]:,} loose pieces '
                               f'(~{settings.dropped_vertices[level]:,} vtx) dropped at export')

        layout.separator()
        layout.label(text='Hints for LOD:')
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
        box.label(text=f'Largest contributors in _LOD{active_lod:02}:', icon='MESH_DATA')
        if contributors:
            for h in contributors:
                r = box.row(align=True)
                r.label(text=f'{h.object_name}: ~{h.vertices:,} vtx')
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
    bl_description = 'Show Quota and Hints details for this LOD level'
    level: bpy.props.IntProperty(min=0, max=6, default=0)

    def execute(self, context):
        context.scene.fss_lod_settings.inspect_lod = self.level
        return {'FINISHED'}


class FSS_PT_LodExport(bpy.types.Panel):
    bl_idname = 'FSS_PT_lod_export'
    bl_label = 'Export Settings'
    bl_parent_id = 'FSS_PT_lod'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'FSS Tools'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.fss_lod_settings
        layout.prop(settings, 'model_type')
        if settings.measured_diameter > 0:
            layout.label(text=f'Model diameter: {format_length(settings.measured_diameter)} (measured at Refresh)')
            far = [h for h in settings.hints if h.kind == 'FAR_NODE']
            if far:
                # MSFS's LOD sphere encloses every node: far origins move and enlarge it, so LODs switch elsewhere
                box = layout.box()
                box.label(text=f'{len(far)} origins outside the geometry: LOD sphere '
                               f'{format_length(settings.mesh_diameter)} -> {format_length(settings.measured_diameter)}',
                          icon='ERROR')
                for h in far[:5]:
                    r = box.row(align=True)
                    r.label(text=f'{h.object_name}: {format_length(h.size_m)} outside')
                    r.operator('fss.lod_select_hint', text='', icon='RESTRICT_SELECT_OFF').object_name = h.object_name
                box.label(text='Move these origins into the geometry, or the empties out of this model')
            layout.prop(context.scene, 'fss_lod_show_sphere', toggle=True, icon='SPHERE')
            if context.scene.fss_lod_show_sphere:
                box = layout.box()
                box.label(text='LOD sphere box faces set by (last Refresh):')
                for h in _sphere_faces(settings):
                    r = box.row(align=True)
                    r.label(text=f'{h.face}: {h.object_name} ({"origin" if h.from_origin else "vertex"})',
                            icon='ERROR' if h.from_origin else 'DOT')
                    r.operator('fss.lod_select_hint', text='', icon='RESTRICT_SELECT_OFF').object_name = h.object_name
        else:
            layout.label(text='Model diameter: not measured yet, press Refresh LOD Counts', icon='INFO')
        layout.prop(settings, 'reference_size')
        if settings.model_type == 'INTERIOR':
            layout.prop(settings, 'exterior_diameter')
            target = settings.preview_target
            explicit = getattr(settings, 'explicit_' + target) or (target == 'fs20' and settings.explicit_fs24)
            if not explicit and settings.exterior_diameter <= 0:
                layout.label(text='exterior diameter missing', icon='ERROR')

        inputs, reason = cutoff_context(settings)
        last = last_lod(settings)
        if not inputs:
            layout.label(text=reason, icon='INFO')
        else:
            layout.prop(settings, 'lowest_cutoff', text=f'LOD{last:02} hides parts smaller than')
            box = layout.box()
            box.label(text='Hidden parts, smaller than:')
            for level in range(1, last + 1):
                text = f'LOD{level:02}:  {format_length(cutoff_for_level(settings, inputs, level))}'
                if settings.scanned and level < settings.write_count:
                    text += f'   ({settings.counts[0] - settings.counts[level]} objects'
                    if settings.dropped_pieces[level]:
                        text += f', {settings.dropped_pieces[level]} pieces'
                    text += ')'
                box.label(text=text)
        layout.operator('fss.lod_print_settings', icon='CONSOLE')


class FSS_PT_LodExportAdvanced(bpy.types.Panel):
    bl_idname = 'FSS_PT_lod_export_advanced'
    bl_label = 'Advanced'
    bl_parent_id = 'FSS_PT_lod_export'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'FSS Tools'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.fss_lod_settings
        layout.prop(settings, 'preview_target')
        layout.prop(settings, 'screen_height')
        layout.prop(settings, 'pixel_threshold')
        layout.label(text='The size above is this threshold in pixels at this screen height')
        layout.prop(settings, 'msfs_vertex_factor')
        layout.label(text='Vertex reports: High; counts do not affect culling')
        for target in ('fs24', 'fs20'):
            layout.label(text='FS20 minSize (unverified)' if target == 'fs20' else 'FS24 minSize')
            layout.label(text='Screen ratios: 1 = 100%')
            explicit = getattr(settings, 'explicit_' + target) or (target == 'fs20' and settings.explicit_fs24)
            if settings.model_type == 'INTERIOR' and not explicit:
                layout.label(text='Derived from interior / exterior diameter')
                layout.operator('fss.lod_edit_table').target = target
                if settings.scanned and target == settings.preview_target:
                    for level, value in enumerate(settings.resolved_table):
                        layout.label(text=f'LOD{level:02}: {value:.2%}')
            else:
                for level in range(7):
                    layout.prop(settings, 'min_sizes_' + target, index=level, text=f'LOD{level:02}')


CLASSES = (FSS_LodHintItem, FSS_LodSettings, FSS_OT_LodRefresh, FSS_OT_LodSelectHint, FSS_OT_LodInspectLevel,
           FSS_OT_SetObjectLod, FSS_OT_SetViewportLod, FSS_OT_LodPrintSettings,
           FSS_OT_LodEditTable, FSS_PT_Lod, FSS_PT_LodQuotaHints, FSS_PT_LodExport, FSS_PT_LodExportAdvanced)


def register():
    global _text_handle
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.fss_lod_settings = bpy.props.PointerProperty(type=FSS_LodSettings)
    bpy.types.Scene.fss_viewport_lod = bpy.props.IntProperty(default=-1, min=-1, max=6)
    bpy.types.Scene.fss_viewport_lod_auto = bpy.props.BoolProperty(default=False, options={'SKIP_SAVE'})
    bpy.types.Scene.fss_lod_export_level = bpy.props.IntProperty(default=-1, min=-1, max=6, options={'SKIP_SAVE'})
    bpy.types.Scene.fss_lod_show_sphere = bpy.props.BoolProperty(
        name='Show LOD Sphere', default=False, options={'SKIP_SAVE'},
        description='Draw the sphere MSFS uses for LOD selection, its box, and the vertex or origin setting each face '
                    '(from the last Refresh LOD Counts)')
    if not bpy.app.background:
        _text_handle = bpy.types.SpaceView3D.draw_handler_add(_draw_viewport_lod_text, (), 'WINDOW', 'POST_PIXEL')
        for draw, kind in ((_draw_lod_sphere, 'POST_VIEW'), (_draw_lod_sphere_labels, 'POST_PIXEL')):
            _sphere_handles.append(bpy.types.SpaceView3D.draw_handler_add(draw, (), 'WINDOW', kind))


def unregister():
    global _text_handle
    _stop_auto_timer()
    if _text_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_text_handle, 'WINDOW')
        _text_handle = None
    while _sphere_handles:
        bpy.types.SpaceView3D.draw_handler_remove(_sphere_handles.pop(), 'WINDOW')
    for name in ('fss_lod_settings', 'fss_viewport_lod', 'fss_viewport_lod_auto', 'fss_lod_export_level',
                 'fss_lod_show_sphere'):
        delattr(bpy.types.Scene, name)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
