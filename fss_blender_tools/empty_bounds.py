"""Empty bounds: draws, for each empty, the box around all of its descendants and its origin, in the viewport only.

Nothing is added to the scene: the boxes are drawn by a viewport draw handler, so they never appear in the Outliner,
in a render or in an export. A box is computed bottom-up from direct children only: each object's box (in its own
local space) is the union of its own geometry and of its children's boxes, so an empty's box covers every
descendant, hidden ones included. Boxes are cached and recomputed only for objects whose ancestors or descendants
changed.
"""

import blf
import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

# Object types with a meaningful bound_box; empties, lights, cameras and speakers only pass on their children's boxes
GEOMETRY_TYPES = {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META', 'ARMATURE', 'GREASEPENCIL', 'CURVES', 'POINTCLOUD',
                  'VOLUME', 'LATTICE'}
BOX_EDGES = ((0, 1), (1, 3), (3, 2), (2, 0), (4, 5), (5, 7), (7, 6), (6, 4), (0, 4), (1, 5), (2, 6), (3, 7))
OTHER_COLOR = (0.55, 0.75, 1.0, 0.35)
ANCESTOR_COLOR = (1.0, 0.55, 1.0, 0.85)  # light magenta: empties above a selected object
DASH_PIXELS = 6.0
# Hierarchy text: empties further up, direct parent, non-empty parents, extra-selection note
TEXT_ANCESTOR_COLOR = (0.85, 0.6, 0.85, 1.0)
TEXT_PARENT_COLOR = (1.0, 0.65, 1.0, 1.0)
TEXT_OTHER_COLOR = (0.7, 0.7, 0.7, 1.0)
TEXT_SIZE = 11
TEXT_FONT = 0
TEXT_MAX_ROWS = 48
TEXT_HOVER_COLOR = (1.0, 1.0, 1.0, 0.12)
TEXT_MARGIN = 14
TEXT_INDENT = 12

_boxes = {}       # object pointer -> (min, max) in the object's local space, or None without geometry
_parents = {}     # object pointer -> parent pointer when its box was computed
_children = None  # parent pointer -> child objects, rebuilt after any change of the object set or of a parent
_draw_handle = None
_text_handle = None


def _invalidate_all():
    global _children
    _boxes.clear()
    _parents.clear()
    _children = None


def _invalidate_chain(obj):
    """Drops the cached boxes of obj and of its ancestors, the current ones and those it had when last computed."""
    global _children
    pointer = obj.as_pointer()
    previous_parent = _parents.get(pointer)
    current_parent = obj.parent.as_pointer() if obj.parent else 0
    if previous_parent is not None and previous_parent != current_parent:
        _children = None  # reparented
        while previous_parent:
            _boxes.pop(previous_parent, None)
            previous_parent = _parents.get(previous_parent)
    while obj is not None:
        _boxes.pop(obj.as_pointer(), None)
        obj = obj.parent


def _child_map():
    global _children
    if _children is None:
        _children = {}
        for obj in bpy.data.objects:
            if obj.parent is not None:
                _children.setdefault(obj.parent.as_pointer(), []).append(obj)
    return _children


def local_box(obj, depsgraph):
    """Box around obj and all its descendants in obj's local space, as (min, max), or None when there is no geometry."""
    pointer = obj.as_pointer()
    if pointer in _boxes:
        return _boxes[pointer]
    points = []
    if obj.type in GEOMETRY_TYPES:
        evaluated = obj.evaluated_get(depsgraph) if depsgraph is not None else obj
        points.extend(Vector(corner) for corner in evaluated.bound_box)
    to_local = obj.matrix_world.inverted_safe()
    view_layer = depsgraph.view_layer if depsgraph is not None else None
    for child in _child_map().get(pointer, ()):
        box = local_box(child, depsgraph)
        if box is not None:
            # Objects disabled in viewports are not evaluated, so their matrix_world is stale; for them (and anything
            # not visible) use the parent-relative transform, exact for object parenting without constraints
            if view_layer is not None and child.visible_get(view_layer=view_layer) \
                    and obj.visible_get(view_layer=view_layer):
                child_to_local = to_local @ child.matrix_world
            else:
                child_to_local = child.matrix_parent_inverse @ child.matrix_basis
            points.extend(child_to_local @ corner for corner in _corners(box))
    box = None
    if points:
        box = (Vector(min(p[i] for p in points) for i in range(3)), Vector(max(p[i] for p in points) for i in range(3)))
    _boxes[pointer] = box
    _parents[pointer] = obj.parent.as_pointer() if obj.parent else 0
    return box


def _corners(box):
    low, high = box
    return [Vector((x, y, z)) for x in (low.x, high.x) for y in (low.y, high.y) for z in (low.z, high.z)]


@bpy.app.handlers.persistent
def _on_depsgraph_update(scene, depsgraph):
    for update in depsgraph.updates:
        data = update.id
        if isinstance(data, bpy.types.Collection):
            _invalidate_all()  # objects added, removed or moved between collections
            return
        if isinstance(data, bpy.types.Object):
            _invalidate_chain(data.original)


@bpy.app.handlers.persistent
def _on_reset(*_args):
    _invalidate_all()


def _draw():
    context = bpy.context
    space = context.space_data
    scene = context.scene
    mode = scene.fss_empty_bounds_mode
    if mode == 'OFF' or not space.overlay.show_overlays or not space.show_object_viewport_empty:
        return
    view_layer = context.view_layer
    depsgraph = context.evaluated_depsgraph_get()
    active = view_layer.objects.active
    selected = set(context.selected_objects)

    # Empties above a selected object, unless selected themselves: the direct parent shows its solid box and origin
    # crosshair, empties further up (up to the root) only their dashed box
    parents = set()
    ancestors = set()
    for obj in selected:
        parent = obj.parent
        if parent is not None and parent.type == 'EMPTY' and parent not in selected:
            parents.add(parent)
        parent = parent.parent if parent is not None else None
        while parent is not None:
            if parent.type == 'EMPTY' and parent not in selected:
                ancestors.add(parent)
            parent = parent.parent
    # With a non-empty selected, only the selection and its parents are shown
    show_other = mode == 'ALL' and all(obj.type == 'EMPTY' for obj in selected)

    candidates = view_layer.objects if show_other else selected | parents | ancestors
    groups = {"other": [], "ancestor": [], "parent": [], "selected": [], "active": []}
    for obj in candidates:
        if obj.type != 'EMPTY' or not obj.visible_get(view_layer=view_layer):
            continue
        if obj == active:
            group = "active"
        elif obj in selected:
            group = "selected"
        elif obj in parents:
            group = "parent"
        elif obj in ancestors:
            group = "ancestor"
        else:
            group = "other"
        box = local_box(obj, depsgraph)
        if box is not None:
            _add_box_lines(groups[group], obj, box)
        if group != "ancestor":
            _add_crosshair_lines(groups[group], obj)

    rv3d = context.region_data
    region = context.region
    groups["ancestor"] = _dashed(groups["ancestor"], rv3d.perspective_matrix, region.width, region.height)
    theme = context.preferences.themes[0].view_3d
    styles = {
        "other": (OTHER_COLOR, 1.5),
        "ancestor": (ANCESTOR_COLOR, 1.0),
        "parent": (ANCESTOR_COLOR, 1.0),
        "selected": ((*theme.object_selected, 1.0), 2.0),
        "active": ((*theme.object_active, 1.0), 2.0),
    }
    shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE' if scene.fss_empty_bounds_in_front else 'LESS_EQUAL')
    shader.bind()
    shader.uniform_float("viewportSize", (region.width, region.height))
    for group, lines in groups.items():
        if lines:
            color, width = styles[group]
            shader.uniform_float("color", color)
            shader.uniform_float("lineWidth", width)
            batch_for_shader(shader, 'LINES', {"pos": lines}).draw(shader)
    gpu.state.depth_test_set('NONE')
    gpu.state.blend_set('NONE')


def hierarchy_rows(context):
    """Layout of the hierarchy text: the active object's parent chain, root first, bottom-right of the viewport.

    Returns a list of (x, y, width, height, text, color, target name or None); x, y is the text baseline in region
    pixels. The text drawing and the click gizmos both use it, so what is clicked is what is shown.
    """
    obj = context.active_object
    if obj is None or not context.scene.fss_empty_bounds_hierarchy_text or not context.space_data.overlay.show_overlays:
        return []
    chain = []
    parent = obj.parent
    while parent is not None:
        chain.append(parent)
        parent = parent.parent
    chain.reverse()

    theme = context.preferences.themes[0].view_3d
    items = []
    for depth, item in enumerate(chain):
        if item.type != 'EMPTY':
            color = TEXT_OTHER_COLOR
        elif item == obj.parent:
            color = TEXT_PARENT_COLOR
        else:
            color = TEXT_ANCESTOR_COLOR
        items.append((depth, item.name, color, item.name))
    items.append((len(chain), obj.name, (*theme.object_active, 1.0), obj.name))
    others = len(context.selected_objects) - (1 if obj.select_get() else 0)
    if others > 0:
        items.append((len(chain), f"+{others} more selected", TEXT_OTHER_COLOR, None))

    region = context.region
    scale = context.preferences.system.ui_scale
    blf.size(TEXT_FONT, TEXT_SIZE * scale)
    line_height = blf.dimensions(TEXT_FONT, "Xg")[1] * 1.5
    indent = TEXT_INDENT * scale
    widths = [blf.dimensions(TEXT_FONT, text)[0] for _depth, text, _color, _target in items]
    block_width = max(depth * indent + width for (depth, *_rest), width in zip(items, widths))
    # Keep clear of the sidebar when it overlaps the viewport
    right = region.width - TEXT_MARGIN * scale
    if context.preferences.system.use_region_overlap:
        for other in context.area.regions:
            if other.type == 'UI' and other.width > 1 and other.alignment == 'RIGHT':
                right -= other.width
    left = max(TEXT_MARGIN * scale, right - block_width)
    y = TEXT_MARGIN * scale + line_height * (len(items) - 1)
    rows = []
    for (depth, text, color, target), width in zip(items, widths):
        rows.append((left + depth * indent, y, width, line_height, text, color, target))
        y -= line_height
    return rows


def _draw_hierarchy_text():
    rows = hierarchy_rows(bpy.context)
    if not rows:
        return
    blf.size(TEXT_FONT, TEXT_SIZE * bpy.context.preferences.system.ui_scale)
    blf.enable(TEXT_FONT, blf.SHADOW)
    blf.shadow(TEXT_FONT, 3, 0.0, 0.0, 0.0, 0.9)
    blf.shadow_offset(TEXT_FONT, 1, -1)
    for x, y, _width, _height, text, color, _target in rows:
        blf.position(TEXT_FONT, x, y, 0)
        blf.color(TEXT_FONT, *color)
        blf.draw(TEXT_FONT, text)
    blf.disable(TEXT_FONT, blf.SHADOW)


def _row_rect(row):
    """Clickable rectangle (x, y, width, height) of a text row, from just below the baseline to the next row."""
    x, y, width, height = row[:4]
    return x - 3, y - height * 0.3, width + 6, height


class FSS_GT_HierarchyRow(bpy.types.Gizmo):
    """One clickable row of the hierarchy text; the text itself is drawn by the overlay, this only adds hover and hit."""
    bl_idname = "FSS_GT_hierarchy_row"
    __slots__ = ("rect", "select_props")

    def setup(self):
        self.rect = None

    def test_select(self, context, location):
        if self.rect is None:
            return -1
        x, y, width, height = self.rect
        return 0 if x <= location[0] <= x + width and y <= location[1] <= y + height else -1

    def draw(self, context):
        if not self.is_highlight or self.rect is None:
            return
        x, y, width, height = self.rect
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        quad = ((x, y), (x + width, y), (x + width, y + height), (x, y + height))
        gpu.state.blend_set('ALPHA')
        shader.bind()
        shader.uniform_float("color", TEXT_HOVER_COLOR)
        batch_for_shader(shader, 'TRI_FAN', {"pos": quad}).draw(shader)
        gpu.state.blend_set('NONE')


class FSS_GGT_HierarchyText(bpy.types.GizmoGroup):
    bl_idname = "FSS_GGT_hierarchy_text"
    bl_label = "FSS Hierarchy Text"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_options = {'PERSISTENT'}

    @classmethod
    def poll(cls, context):
        return (context.mode == 'OBJECT' and context.active_object is not None
                and context.scene.fss_empty_bounds_hierarchy_text)

    def setup(self, context):
        for _index in range(TEXT_MAX_ROWS):
            gizmo = self.gizmos.new(FSS_GT_HierarchyRow.bl_idname)
            gizmo.select_props = gizmo.target_set_operator(FSS_OT_HierarchySelect.bl_idname)
            gizmo.hide = True

    def draw_prepare(self, context):
        rows = [row for row in hierarchy_rows(context) if row[6] is not None]
        for index, gizmo in enumerate(self.gizmos):
            if index < len(rows):
                gizmo.rect = _row_rect(rows[index])
                gizmo.select_props.name = rows[index][6]
                gizmo.hide = False
            else:
                gizmo.rect = None
                gizmo.hide = True


class FSS_OT_HierarchySelect(bpy.types.Operator):
    bl_idname = "fss.hierarchy_select"
    bl_label = "Select from Hierarchy"
    bl_description = "Select (Shift: toggle)"
    bl_options = {'REGISTER', 'UNDO'}

    name: bpy.props.StringProperty()
    extend: bpy.props.BoolProperty(options={'SKIP_SAVE'})

    def invoke(self, context, event):
        self.extend = event.shift
        return self.execute(context)

    def execute(self, context):
        view_layer = context.view_layer
        obj = view_layer.objects.get(self.name)
        if obj is None:
            self.report({'WARNING'}, f"{self.name} is not in this view layer")
            return {'CANCELLED'}
        if self.extend and obj.select_get():
            obj.select_set(False)
            return {'FINISHED'}
        if not self.extend:
            for selected in context.selected_objects:
                selected.select_set(False)
        obj.select_set(True)
        view_layer.objects.active = obj
        return {'FINISHED'}


def _add_box_lines(lines, obj, box):
    matrix = obj.matrix_world
    corners = [matrix @ corner for corner in _corners(box)]
    for a, b in BOX_EDGES:
        lines.extend((corners[a], corners[b]))


def _add_crosshair_lines(lines, obj):
    """Origin as a crosshair shaped like Plain Axes: same size, rotation and scale."""
    matrix = obj.matrix_world
    size = obj.empty_display_size
    for axis in ((size, 0, 0), (0, size, 0), (0, 0, size)):
        lines.extend((matrix @ Vector(axis), matrix @ -Vector(axis)))


def _dashed(lines, perspective, width, height):
    """Splits line pairs into dashes of about DASH_PIXELS on screen (a fixed count when an end is behind the view)."""
    dashes = []
    for start, end in zip(lines[0::2], lines[1::2]):
        a = perspective @ start.to_4d()
        b = perspective @ end.to_4d()
        if a.w > 0 and b.w > 0:
            pixels = ((a.x / a.w - b.x / b.w) * width / 2, (a.y / a.w - b.y / b.w) * height / 2)
            count = max(1, int((pixels[0] ** 2 + pixels[1] ** 2) ** 0.5 / (2 * DASH_PIXELS)))
        else:
            count = 20
        step = (end - start) / count
        for i in range(count):
            dashes.extend((start + step * i, start + step * (i + 0.5)))
    return dashes


def _redraw_viewports(_self, context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


class FSS_PT_EmptyBounds(bpy.types.Panel):
    bl_idname = "FSS_PT_empty_bounds"
    bl_label = "Empty Bounds"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "FSS Tools"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        layout.prop(scene, "fss_empty_bounds_mode", expand=True)
        layout.prop(scene, "fss_empty_bounds_in_front")
        layout.prop(scene, "fss_empty_bounds_hierarchy_text")


CLASSES = (FSS_OT_HierarchySelect, FSS_GT_HierarchyRow, FSS_GGT_HierarchyText, FSS_PT_EmptyBounds)


def register():
    global _draw_handle, _text_handle
    bpy.types.Scene.fss_empty_bounds_mode = bpy.props.EnumProperty(
        name="Empty Bounds", default='ALL', update=_redraw_viewports,
        items=(
            ('ALL', "All", "Draw the bounds of every empty. While a non-empty object is selected, only the "
                           "selection and its parents: the direct parent solid, the empties further up dashed"),
            ('SELECTED', "Selected", "Draw the bounds of selected empties and of the empties above a selected "
                                     "object: the direct parent solid, the empties further up dashed"),
            ('OFF', "Off", "Draw no empty bounds"),
        ),
    )
    bpy.types.Scene.fss_empty_bounds_in_front = bpy.props.BoolProperty(
        name="In Front", default=True, update=_redraw_viewports,
        description="Draw the bounds over the geometry instead of hiding them behind it",
    )
    bpy.types.Scene.fss_empty_bounds_hierarchy_text = bpy.props.BoolProperty(
        name="Hierarchy Text", default=True, update=_redraw_viewports,
        description="List the parents of the active object, root first, in the bottom-right corner of the viewport",
    )
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph_update)
    for handlers in (bpy.app.handlers.frame_change_post, bpy.app.handlers.load_post, bpy.app.handlers.undo_post,
                     bpy.app.handlers.redo_post):
        handlers.append(_on_reset)
    _draw_handle = bpy.types.SpaceView3D.draw_handler_add(_draw, (), 'WINDOW', 'POST_VIEW')
    _text_handle = bpy.types.SpaceView3D.draw_handler_add(_draw_hierarchy_text, (), 'WINDOW', 'POST_PIXEL')
    _invalidate_all()


def unregister():
    global _draw_handle, _text_handle
    if _text_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_text_handle, 'WINDOW')
        _text_handle = None
    if _draw_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, 'WINDOW')
        _draw_handle = None
    for handlers in (bpy.app.handlers.frame_change_post, bpy.app.handlers.load_post, bpy.app.handlers.undo_post,
                     bpy.app.handlers.redo_post):
        if _on_reset in handlers:
            handlers.remove(_on_reset)
    if _on_depsgraph_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph_update)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.fss_empty_bounds_hierarchy_text
    del bpy.types.Scene.fss_empty_bounds_in_front
    del bpy.types.Scene.fss_empty_bounds_mode
    _invalidate_all()
