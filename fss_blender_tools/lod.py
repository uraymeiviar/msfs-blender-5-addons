"""LOD level marking: explicit per-object LOD level (0 to 6) and viewport LOD filter.

Each object can be marked with an integer LOD level from 0 (highest detail) to 6 (lowest detail) in the custom property
"fss_lod". Objects without "fss_lod" are treated as LOD 0.
A child cannot have a higher detail level (smaller LOD number) than its parent: if a parent is set to LOD 2, its
children can only use LOD 2..6 (not LOD 1 or LOD 0). Multi-object assignments are applied top-down through the parent
tree so each object is clamped by its parent's effective LOD level.
"""

import blf
import bpy

LOD_KEY = "fss_lod"
LOD_HIDDEN_KEY = "_fss_lod_hidden"
LOD_LEVELS = (6, 5, 4, 3, 2, 1, 0)

FILTER_TEXT_FONT = 0
FILTER_TEXT_SIZE = 13
FILTER_TEXT_COLOR = (1.0, 0.78, 0.25, 1.0)
FILTER_TEXT_MARGIN = 16

_text_handle = None


def _editable(obj) -> bool:
    return obj.library is None and obj.override_library is None


def get_own_lod(obj) -> int:
    """The LOD level stored on obj itself (0..6, default 0 when unset)."""
    value = obj.get(LOD_KEY, 0)
    if isinstance(value, (int, float)):
        return max(0, min(6, int(value)))
    return 0


def parent_max_lod(obj, exclude_set=None) -> int:
    """The lowest detail (largest LOD number) among obj's ancestors, which clamps obj's maximum detail level."""
    limit = 0
    parent = obj.parent
    while parent is not None:
        if exclude_set is None or parent not in exclude_set:
            limit = max(limit, get_own_lod(parent))
        parent = parent.parent
    return limit


def get_lod(obj) -> int:
    """Effective LOD level of obj (0..6), clamped by all of its ancestors."""
    return max(get_own_lod(obj), parent_max_lod(obj))


def set_own_lod(obj, level: int):
    """Stores level (0..6) on obj; removes the custom property when level is 0 and no ancestor forces a clamp."""
    level = max(0, min(6, int(level)))
    if level == 0:
        if LOD_KEY in obj:
            del obj[LOD_KEY]
    else:
        obj[LOD_KEY] = level


def _tree_depth(obj) -> int:
    depth = 0
    parent = obj.parent
    while parent is not None:
        depth += 1
        parent = parent.parent
    return depth


def _clamp_descendants_top_down(root):
    """Ensures every descendant of root has an LOD number >= its parent's effective LOD."""
    queue = list(root.children)
    while queue:
        child = queue.pop(0)
        if _editable(child):
            min_lod = parent_max_lod(child)
            if get_own_lod(child) < min_lod:
                set_own_lod(child, min_lod)
        queue.extend(child.children)


def apply_lod_top_down(objects, target_level: int) -> tuple:
    """Applies target_level to objects in top-down tree order, clamping each by its parent's LOD.

    Returns (changed_count, clamped_count).
    """
    ordered = sorted((obj for obj in objects if _editable(obj)), key=_tree_depth)
    changed = 0
    clamped = 0
    for obj in ordered:
        limit = parent_max_lod(obj)
        effective = max(target_level, limit)
        if effective != target_level:
            clamped += 1
        set_own_lod(obj, effective)
        changed += 1
        _clamp_descendants_top_down(obj)
    return changed, clamped


def _redraw_viewports(context):
    if context is None or context.window_manager is None:
        return
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def apply_viewport_lod(context):
    """When scene.fss_viewport_lod > 0, hides objects with effective LOD > active_lod (e.g. for LOD3, hides 6, 5, 4).
    When scene.fss_viewport_lod == 0, unhides all LOD levels.
    """
    scene = context.scene
    view_layer = context.view_layer
    active_lod = scene.fss_viewport_lod

    for obj in view_layer.objects:
        if active_lod > 0 and get_lod(obj) > active_lod:
            if not obj.hide_get(view_layer=view_layer):
                obj[LOD_HIDDEN_KEY] = True
                obj.hide_set(True, view_layer=view_layer)
        else:
            if obj.get(LOD_HIDDEN_KEY):
                del obj[LOD_HIDDEN_KEY]
                obj.hide_set(False, view_layer=view_layer)

    _redraw_viewports(context)


def _draw_viewport_lod_text():
    context = bpy.context
    scene = getattr(context, "scene", None)
    space = getattr(context, "space_data", None)
    if scene is None or space is None or not space.overlay.show_overlays:
        return
    active_lod = getattr(scene, "fss_viewport_lod", 0)
    if active_lod <= 0:
        return

    scale = context.preferences.system.ui_scale
    left = FILTER_TEXT_MARGIN * scale
    if context.preferences.system.use_region_overlap and context.area is not None:
        for region in context.area.regions:
            if region.type == 'TOOLS' and region.width > 1 and region.alignment == 'LEFT':
                left += region.width
    y = FILTER_TEXT_MARGIN * scale

    text = f"Filtered by LOD{active_lod}"
    blf.size(FILTER_TEXT_FONT, FILTER_TEXT_SIZE * scale)
    blf.enable(FILTER_TEXT_FONT, blf.SHADOW)
    blf.shadow(FILTER_TEXT_FONT, 3, 0.0, 0.0, 0.0, 0.9)
    blf.shadow_offset(FILTER_TEXT_FONT, 1, -1)
    blf.position(FILTER_TEXT_FONT, left, y, 0)
    blf.color(FILTER_TEXT_FONT, *FILTER_TEXT_COLOR)
    blf.draw(FILTER_TEXT_FONT, text)
    blf.disable(FILTER_TEXT_FONT, blf.SHADOW)


class FSS_OT_SetObjectLod(bpy.types.Operator):
    bl_idname = "fss.set_object_lod"
    bl_label = "Set Object LOD"
    bl_description = "Set the LOD level of the selected object(s) top-down, clamping children that had a higher level"
    bl_options = {'REGISTER', 'UNDO'}

    level: bpy.props.IntProperty(name="LOD Level", min=0, max=6, default=0)

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects)

    def execute(self, context):
        changed, clamped = apply_lod_top_down(context.selected_objects, self.level)
        if context.scene.fss_viewport_lod > 0:
            apply_viewport_lod(context)
        msg = f"Set LOD {self.level} on {changed} object(s)"
        if clamped:
            msg += f" ({clamped} clamped by parent LOD)"
        self.report({'INFO'}, msg)
        return {'FINISHED'}


class FSS_OT_SetViewportLod(bpy.types.Operator):
    bl_idname = "fss.set_viewport_lod"
    bl_label = "Viewport LOD Filter"
    bl_description = "Filter the viewport by this LOD level (0 unhides all LOD levels)"
    bl_options = {'REGISTER', 'UNDO'}

    level: bpy.props.IntProperty(name="Viewport LOD", min=0, max=6, default=0)

    def execute(self, context):
        context.scene.fss_viewport_lod = self.level
        apply_viewport_lod(context)
        return {'FINISHED'}


class FSS_PT_Lod(bpy.types.Panel):
    bl_idname = "FSS_PT_lod"
    bl_label = "LOD"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "FSS Tools"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        selected = [obj for obj in context.selected_objects if _editable(obj)]
        selected_set = set(selected)

        # Object LOD row: [6][5][4][3][2][1][0], with 6..current_lod highlighted
        layout.label(text="Object LOD")
        obj_row = layout.row(align=True)
        if not selected:
            obj_row.enabled = False
            for level in LOD_LEVELS:
                obj_row.operator(FSS_OT_SetObjectLod.bl_idname, text=str(level)).level = level
        else:
            active = context.active_object if context.active_object in selected_set else selected[0]
            current_lod = get_lod(active)
            # A button is enabled if at least one selected object can reach that level after top-down propagation
            min_allowed = min(parent_max_lod(obj, exclude_set=selected_set) for obj in selected)
            for level in LOD_LEVELS:
                sub = obj_row.row(align=True)
                sub.enabled = level >= min_allowed
                op = sub.operator(
                    FSS_OT_SetObjectLod.bl_idname,
                    text=str(level),
                    depress=(level >= current_lod),
                )
                op.level = level

        # Viewport LOD row: [6][5][4][3][2][1][0], with 6..v_lod highlighted (0 unhides all)
        v_lod = max(0, min(6, scene.fss_viewport_lod))
        header = f"Viewport LOD (LOD{v_lod})" if v_lod > 0 else "Viewport LOD"
        layout.label(text=header)
        view_row = layout.row(align=True)
        for level in LOD_LEVELS:
            op = view_row.operator(
                FSS_OT_SetViewportLod.bl_idname,
                text=str(level),
                depress=(level >= v_lod),
            )
            op.level = level


CLASSES = (
    FSS_OT_SetObjectLod,
    FSS_OT_SetViewportLod,
    FSS_PT_Lod,
)


def register():
    global _text_handle
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.fss_viewport_lod = bpy.props.IntProperty(
        name="Viewport LOD", default=0, min=0, max=6,
        description="Active viewport LOD filter (0 = all LOD levels visible, 1..6 = hide objects below this LOD)",
    )
    _text_handle = bpy.types.SpaceView3D.draw_handler_add(_draw_viewport_lod_text, (), 'WINDOW', 'POST_PIXEL')


def unregister():
    global _text_handle
    if _text_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_text_handle, 'WINDOW')
        _text_handle = None
    del bpy.types.Scene.fss_viewport_lod
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
