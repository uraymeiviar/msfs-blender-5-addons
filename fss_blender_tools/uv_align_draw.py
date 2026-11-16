"""The overlay of UV Align marks (native UV packer decision 12, its second delivery): in Edit Mode, every marked edge is
drawn as a dashed yellow line with a symbol at its middle, ─ Horizontal, │ Vertical, ┼ Either; in the 3D view (hidden
behind the mesh as its edges are) and in the UV editor (the UV edges of the faces it shows). Dashed, so that Blender's
own edge colors (seam, sharp, crease, ...) still show between the dashes; one color with a symbol, so that no color of
the theme is taken (maintainer's choice). Show UV Align in the UV Align menu switches it off and on (for the session).

The geometry is computed by lines_3d and lines_uv, without drawing, so that it can be tested in the background; the
draw handlers only bind the shader and draw. Neither touches the BMesh: a Python BMesh element made while Blender draws,
or while a modal operator (a UV grab) holds pointers into the mesh, adds a layer to the edit mesh and moves the data of
all its elements, which crashed Blender. refresh() copies the marked edges into numpy arrays instead, from a timer between
events and never while an editing modal operator runs, through BMesh.to_mesh into a scratch mesh, which makes no
element wrappers. A depsgraph update of a mesh or an object drops the copies and schedules the timer; until it has run,
nothing is drawn (during a grab, the overlay is away).
"""

import bmesh
import bpy
import numpy as np
from bpy.app.handlers import persistent

from . import uv_align

try:
    import gpu
    from gpu_extras.batch import batch_for_shader
except ImportError:  # no GPU module (bpy as a module without a display): nothing is drawn
    gpu = None

SHOW_PROP = 'fss_uv_align_show'  # on the window manager: the overlay on or off for the session
COLOR = (1.0, 0.92, 0.1, 1.0)  # lemon yellow: not a color of Blender's edge flags (seam red, sharp cyan, crease magenta)
DASH_PX, GAP_PX = 6.0, 4.0  # on screen
SYMBOL_PX = 5.0  # half the length of a symbol's stroke, on screen
LINE_WIDTH = 2.0
NUDGE = 0.002  # the 3D lines move this share of their distance towards the eye, so the mesh does not hide them
TMP_NAME = '.fss_uv_align_overlay'  # the scratch mesh of _read: kept, no users (not saved), removed at unregister
# modal operators that may hold pointers into a mesh: no refresh while one runs
MODAL_PREFIXES = ('TRANSFORM_OT', 'MESH_OT', 'UV_OT', 'IMAGE_OT', 'OBJECT_OT', 'SCULPT_OT', 'PAINT_OT')
RETRY_S = 0.2  # the refresh waits this long while such an operator runs
_cache = {}  # mesh name: the marked edges as numpy arrays (see _read), or None; never BMesh data
_handles = []


def show(context=None):
    context = context or bpy.context
    return bool(getattr(context.window_manager, SHOW_PROP, True))


def _read(me):
    """The marked, visible edges of a mesh in Edit Mode as numpy arrays, or None when it has none: 'a', 'b' (N x 3,
    local) and 'kind' (N) for the 3D view; 'uv_a', 'uv_b' (M x 2), 'uv_kind' and 'uv_selected' (M, the face's
    selection) for the UV editor, one per side of a marked edge on a face not hidden. Copies the edit mesh with
    BMesh.to_mesh, which creates no Python BMesh elements and so leaves the edit mesh as it is."""
    if uv_align.ALIGN_KEY not in me.attributes:  # known in Edit Mode too, without reading the BMesh
        return None
    # one scratch mesh, reused: adding and removing a mesh each time rebuilds the depsgraph relations, which reports
    # the objects as updated and would drop the copies again
    tmp = bpy.data.meshes.get(TMP_NAME) or bpy.data.meshes.new(TMP_NAME)
    try:
        bmesh.from_edit_mesh(me).to_mesh(tmp)
        attribute = tmp.attributes.get(uv_align.ALIGN_KEY)
        if attribute is None or attribute.domain != 'EDGE' or attribute.data_type != 'INT':
            return None
        ne, nl, nf = len(tmp.edges), len(tmp.loops), len(tmp.polygons)
        kind = np.zeros(ne, np.int32)
        attribute.data.foreach_get('value', kind)
        hide = np.zeros(ne, bool)
        tmp.edges.foreach_get('hide', hide)
        keep = (kind != 0) & ~hide
        if not keep.any():
            return None
        co = np.zeros(len(tmp.vertices) * 3, np.float64)
        tmp.vertices.foreach_get('co', co)
        co = co.reshape(-1, 3)
        ev = np.zeros(ne * 2, np.int64)
        tmp.edges.foreach_get('vertices', ev)
        ev = ev.reshape(-1, 2)[keep]
        out = {'a': co[ev[:, 0]], 'b': co[ev[:, 1]], 'kind': kind[keep],
               'uv_a': np.zeros((0, 2)), 'uv_b': np.zeros((0, 2)), 'uv_kind': np.zeros(0, np.int32),
               'uv_selected': np.zeros(0, bool)}
        uv_layer = tmp.uv_layers.active
        if uv_layer is None or nl == 0:
            return out
        start, total = np.zeros(nf, np.int64), np.zeros(nf, np.int64)
        tmp.polygons.foreach_get('loop_start', start)
        tmp.polygons.foreach_get('loop_total', total)
        f_hide, f_sel = np.zeros(nf, bool), np.zeros(nf, bool)
        tmp.polygons.foreach_get('hide', f_hide)
        tmp.polygons.foreach_get('select', f_sel)
        loop_edge = np.zeros(nl, np.int64)
        tmp.loops.foreach_get('edge_index', loop_edge)
        uv = np.zeros(nl * 2, np.float64)
        uv_layer.uv.foreach_get('vector', uv)
        uv = uv.reshape(-1, 2)
        face = np.repeat(np.arange(nf), total)
        loops = np.arange(nl)
        nxt = loops + 1
        nxt = np.where(nxt == start[face] + total[face], start[face], nxt)  # the loop after the last is the first
        on = keep[loop_edge] & ~f_hide[face]
        out.update(uv_a=uv[on], uv_b=uv[nxt[on]], uv_kind=kind[loop_edge[on]], uv_selected=f_sel[face[on]])
        return out
    finally:
        tmp.clear_geometry()


def refresh(objects):
    """Copy the marks of these objects' meshes (in Edit Mode) into the cache, those not there yet."""
    for obj in objects:
        if obj.data.name not in _cache:
            _cache[obj.data.name] = _read(obj.data)


def _edit_objects():
    """The meshes in Edit Mode of every window's view layer (a timer has no context), one object per mesh."""
    found = {}
    for window in bpy.context.window_manager.windows:
        for obj in window.view_layer.objects:
            if obj.type == 'MESH' and obj.mode == 'EDIT':
                found.setdefault(obj.data, obj)
    return list(found.values())


def _editing_modal():
    """True while a modal operator that may hold pointers into a mesh runs (a grab, a knife, ...)."""
    for window in bpy.context.window_manager.windows:
        for op in getattr(window, 'modal_operators', ()):
            if op.bl_idname.startswith(MODAL_PREFIXES):
                return True
    return False


def _refresh_timer():
    if not show():
        return None
    if _editing_modal():
        return RETRY_S
    refresh(_edit_objects())
    _tag_redraw()
    return None


def _schedule():
    if not bpy.app.background and not bpy.app.timers.is_registered(_refresh_timer):
        bpy.app.timers.register(_refresh_timer, first_interval=0.0)


def dashes(a, b, length_px):
    """The dashes of a line from a to b (arrays of 2 or 3 numbers) that is length_px long on screen: [(start, end)].
    Whole dashes of DASH_PX with gaps of GAP_PX, stretched to fit; the first starts at a, the last ends at b."""
    a, b = np.asarray(a, np.float64), np.asarray(b, np.float64)
    n = max(int(round((length_px + GAP_PX) / (DASH_PX + GAP_PX))), 1)
    if n == 1:
        return [(a, b)]
    step = 1.0 / (n - (GAP_PX / (DASH_PX + GAP_PX)))  # n dashes and n - 1 gaps fill the line
    on = step * DASH_PX / (DASH_PX + GAP_PX)
    return [(a + (b - a) * (i * step), a + (b - a) * min(i * step + on, 1.0)) for i in range(n)]


def symbol(kind, centre, right, up):
    """The strokes of a kind's symbol at centre, right and up being SYMBOL_PX on screen: ─, │ or ┼."""
    strokes = []
    if kind in (uv_align.HORIZONTAL, uv_align.EITHER):
        strokes.append((centre - right, centre + right))
    if kind in (uv_align.VERTICAL, uv_align.EITHER):
        strokes.append((centre - up, centre + up))
    return strokes


def lines_3d(objects, perspective, eye, view_dir, right_dir, up_dir, size, is_perspective):
    """Points (pairs, for LINES) of the overlay in the 3D view, from the cache: objects in Edit Mode; perspective: the
    region's 4x4 perspective matrix (numpy); eye: the view's position; view_dir, right_dir, up_dir: its forward, right
    and up directions (unit vectors); size: (width, height) of the region in pixels."""
    points = []
    half = np.asarray(size, np.float64) / 2.0

    def screen(p):
        c = perspective @ np.append(p, 1.0)
        return None if c[3] <= 1e-9 else (c[:2] / c[3] + 1.0) * half

    for obj in objects:
        data = _cache.get(obj.data.name)
        if data is None:
            continue
        M = np.array(obj.matrix_world, np.float64)
        world_a = data['a'] @ M[:3, :3].T + M[:3, 3]
        world_b = data['b'] @ M[:3, :3].T + M[:3, 3]
        for a, b, kind in zip(world_a, world_b, data['kind']):
            # towards the eye, so that the edge's own faces do not hide the line
            if is_perspective:
                a, b = a + (eye - a) * NUDGE, b + (eye - b) * NUDGE
            else:
                a, b = a - view_dir * NUDGE, b - view_dir * NUDGE
            sa, sb = screen(a), screen(b)
            if sa is None or sb is None:
                continue
            for p, q in dashes(a, b, float(np.linalg.norm(sb - sa))):
                points += [p, q]
            mid = 0.5 * (a + b)
            sm = screen(mid)
            sr = screen(mid + right_dir)
            if sm is None or sr is None:
                continue
            per_px = 1.0 / max(float(np.linalg.norm(sr - sm)), 1e-9)  # world length of a pixel at mid
            for p, q in symbol(int(kind), mid, right_dir * SYMBOL_PX * per_px, up_dir * SYMBOL_PX * per_px):
                points += [p, q]
    return points


def lines_uv(objects, sync, to_px):
    """Points (pairs, z 0) of the overlay in the UV editor, in region pixels, from the cache: the UV edges of marked
    edges on the faces the editor shows (every face not hidden with UV sync selection, else the selected ones).
    to_px: (u, v) to pixels."""
    points = []
    right, up = np.array([SYMBOL_PX, 0.0, 0.0]), np.array([0.0, SYMBOL_PX, 0.0])
    for obj in objects:
        data = _cache.get(obj.data.name)
        if data is None:
            continue
        for ua, ub, kind, selected in zip(data['uv_a'], data['uv_b'], data['uv_kind'], data['uv_selected']):
            if not (sync or selected):
                continue
            a = np.array([*to_px(float(ua[0]), float(ua[1])), 0.0])
            b = np.array([*to_px(float(ub[0]), float(ub[1])), 0.0])
            for p, q in dashes(a, b, float(np.linalg.norm(b - a))):
                points += [p, q]
            for p, q in symbol(int(kind), 0.5 * (a + b), right, up):
                points += [p, q]
    return points


def _draw(points, region, depth):
    if gpu is None or not points:
        return
    shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('LESS_EQUAL' if depth else 'NONE')
    shader.bind()
    shader.uniform_float('viewportSize', (region.width, region.height))
    shader.uniform_float('lineWidth', LINE_WIDTH)
    shader.uniform_float('color', COLOR)
    batch_for_shader(shader, 'LINES', {'pos': [tuple(map(float, p)) for p in points]}).draw(shader)
    gpu.state.depth_test_set('NONE')
    gpu.state.blend_set('NONE')


def _objects(context):
    """The meshes in Edit Mode; schedules the refresh when one is not in the cache yet."""
    objects = [o for o in getattr(context, 'objects_in_mode_unique_data', []) or [] if o.type == 'MESH']
    if any(o.data.name not in _cache for o in objects):
        _schedule()
    return objects


def _draw_3d():
    context = bpy.context
    if context.mode != 'EDIT_MESH' or not show(context) or context.region_data is None:
        return
    rv3d = context.region_data
    view_inv = np.array(rv3d.view_matrix.inverted(), np.float64)
    axis = [view_inv[:3, i] / max(np.linalg.norm(view_inv[:3, i]), 1e-12) for i in range(3)]
    region = context.region
    points = lines_3d(_objects(context), np.array(rv3d.perspective_matrix, np.float64), view_inv[:3, 3], -axis[2],
                      axis[0], axis[1], (region.width, region.height), rv3d.is_perspective)
    _draw(points, region, True)


def _draw_uv():
    context = bpy.context
    space = context.space_data
    if context.mode != 'EDIT_MESH' or not show(context) or space is None or space.mode != 'UV':
        return
    region = context.region
    view2d = region.view2d
    points = lines_uv(_objects(context), context.scene.tool_settings.use_uv_select_sync,
                      lambda u, v: view2d.view_to_region(u, v, clip=False))
    _draw(points, region, False)


@persistent  # kept when a file loads
def _drop_cache(_scene=None, depsgraph=None):
    """On a depsgraph update of a mesh or an object (an edit, a mark, a selection, an undo): drop the copies and
    schedule the refresh. The scratch mesh of _read is left out, or each refresh would schedule the next."""
    if depsgraph is not None and not any(isinstance(u.id, (bpy.types.Mesh, bpy.types.Object))
                                         and u.id.name != TMP_NAME for u in depsgraph.updates):
        return
    _cache.clear()
    _schedule()


def _tag_redraw():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type in {'VIEW_3D', 'IMAGE_EDITOR'}:
                area.tag_redraw()


def _show_changed(_self, _context):
    _schedule()
    _tag_redraw()


def register():
    setattr(bpy.types.WindowManager, SHOW_PROP, bpy.props.BoolProperty(
        name='Show UV Align', default=True, update=_show_changed,
        description='Show the UV Align marks in Edit Mode: dashed yellow edges with a symbol, ─ Horizontal, '
                    '│ Vertical, ┼ Either'))
    if _drop_cache not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_drop_cache)
    if bpy.app.background:  # nothing to draw on
        return
    _handles.append((bpy.types.SpaceView3D,
                     bpy.types.SpaceView3D.draw_handler_add(_draw_3d, (), 'WINDOW', 'POST_VIEW')))
    _handles.append((bpy.types.SpaceImageEditor,
                     bpy.types.SpaceImageEditor.draw_handler_add(_draw_uv, (), 'WINDOW', 'POST_PIXEL')))


def unregister():
    for space, handle in _handles:
        space.draw_handler_remove(handle, 'WINDOW')
    _handles.clear()
    if _drop_cache in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_drop_cache)
    if bpy.app.timers.is_registered(_refresh_timer):
        bpy.app.timers.unregister(_refresh_timer)
    _cache.clear()
    tmp = bpy.data.meshes.get(TMP_NAME)
    if tmp is not None and not tmp.users:
        bpy.data.meshes.remove(tmp)
    if hasattr(bpy.types.WindowManager, SHOW_PROP):
        delattr(bpy.types.WindowManager, SHOW_PROP)
