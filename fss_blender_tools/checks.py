"""Checks: repairs for scene states that break the export silently (the start of the wish-list "stupidity check").

Broken bone parents: an object keeps a parent bone after its parent was changed to something that has no bones
(an empty, a mesh). Blender then reports "Failed to add relation Bone Parent" on every depsgraph build, and the parent
type reads as invalid, so the Relations panel cannot reset it.
Faces without area: faces whose world-space area is (near) zero (UV journal decision 117, uv_pack.FACE_AREA_MIN_CM2);
the check selects the objects that have them, so the artist fixes the mesh.
Faces without UV area: faces with a triangle that has 3D area but no UV area (uv_pack.UV_TRI_AREA_MIN_PX2) inside an
island that has UV area. These needles push islands far out of the packed layout (decision 118); re-unwrapping the
part fixes them. A second button, not part of Find Faces Without Area: the two need different fixes.
Animation range: the project's rule is that every animation runs from frame 0 to 100. MSFS itself plays any range as
start to end (dimensionless), so an offender still works there; the rule keeps the files consistent. The check lists
the objects that break it under its button, a click on a row selects that object, and it changes nothing else: the
artist corrects the keys.
Rules and decisions: codes/wasm/doc/journal/20261014.fss-blender-tools-tags-and-merge.md (FSS repository).
"""

import time

import numpy as np

import bpy
from bpy.app.handlers import persistent

from . import name_check, uv_marks, uv_pack

ANIM_LIST_ROWS = 5  # rows of the animation list before it scrolls (the artist can drag it longer)


def broken_bone_parents():
    """Local objects with a parent bone whose parent is not an armature."""
    return [obj for obj in bpy.data.objects
            if obj.library is None and obj.parent_bone and (obj.parent is None or obj.parent.type != 'ARMATURE')]


class FSS_OT_FixBoneParents(bpy.types.Operator):
    bl_idname = "fss.fix_bone_parents"
    bl_label = "Fix Broken Bone Parents"
    bl_description = ("Reset objects that keep a parent bone on a parent without bones to object parenting, "
                      "keeping their world transforms")
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        broken = broken_bone_parents()
        for obj in broken:
            world = obj.matrix_world.copy()
            obj.parent_type = 'OBJECT'
            obj.parent_bone = ""
            obj.matrix_world = world
            print(f"FSS checks: fixed bone parent of {obj.name} (parent {obj.parent.name if obj.parent else 'none'})")
        if broken:
            self.report({'INFO'}, f"Fixed {len(broken)} object(s): {', '.join(obj.name for obj in broken[:5])}"
                                  + (" ..." if len(broken) > 5 else ""))
        else:
            self.report({'INFO'}, "No broken bone parents")
        return {'FINISHED'}


def faces_without_area(view_layer):
    """{object: indices of its faces with a world-space area of at most uv_pack.FACE_AREA_MIN_CM2} over the view
    layer's local mesh objects (Object Mode data)."""
    found = {}
    for obj in view_layer.objects:
        if obj.type != 'MESH' or obj.data is None or obj.library or len(obj.data.polygons) == 0:
            continue
        faces = (uv_pack.face_areas_cm2(obj) <= uv_pack.FACE_AREA_MIN_CM2).nonzero()[0]
        if len(faces):
            found[obj] = faces
    return found


EVERY_SET = object()  # faces_without_uv_area: every texture set


def faces_without_uv_area(view_layer, only=EVERY_SET):
    """({object: indices of its faces with a triangle without UV area inside an island that has UV area}, number of
    such faces, number of such islands) over the view layer's local mesh objects with a UV map, per texture set at its
    size (decision 118); only: one texture set's material (None for the faces without one). A mesh shared by several
    objects is read once, with its first user's materials (as the packer does); every user is listed."""
    cm2 = uv_pack._cm_per_unit(bpy.context.scene) ** 2
    found = {}
    count = islands = 0
    for me, users in uv_pack._meshes(view_layer).items():
        materials = {slot.material for slot in users[0].material_slots} | {None}
        if only is not EVERY_SET:
            if only not in materials:
                continue
            materials = {only}
        md = uv_pack.MeshData(me)
        hit = []
        for material in materials:
            faces = np.flatnonzero(uv_pack._face_material_mask(users[0], md, material))
            if len(faces):
                f, n = uv_pack.uv_zero_faces(md, users, faces, uv_marks.texture_size(material), cm2)
                hit.append(f)
                islands += n
        faces = np.sort(np.concatenate(hit)) if hit else np.zeros(0, np.int64)
        count += len(faces)
        if len(faces):
            for obj in users:
                found[obj] = faces
    return found, count, islands


def _select_faces(me, faces):
    """Select only `faces` of the mesh, with their vertices and edges, so Edit Mode shows those faces in every
    selection mode."""
    face = np.zeros(len(me.polygons), bool)
    face[faces] = True
    totals = np.zeros(len(me.polygons), np.int64)
    me.polygons.foreach_get('loop_total', totals)
    sel_loops = np.repeat(face, totals)
    lv = np.zeros(len(me.loops), np.int64)
    le = np.zeros(len(me.loops), np.int64)
    me.loops.foreach_get('vertex_index', lv)
    me.loops.foreach_get('edge_index', le)
    vert = np.zeros(len(me.vertices), bool)
    vert[lv[sel_loops]] = True
    edge = np.zeros(len(me.edges), bool)
    edge[le[sel_loops]] = True
    me.polygons.foreach_set('select', face)
    me.vertices.foreach_set('select', vert)
    me.edges.foreach_set('select', edge)
    me.update()


def _select_found(context, found):
    """Select the visible objects of `found` ({object: face indices}), the first active, and in their meshes only
    those faces, so Edit Mode shows them. Returns the objects selected."""
    shown = [obj for obj in found if obj.visible_get()]
    if shown:
        for obj in context.selected_objects:
            obj.select_set(False)
    meshes = set()
    for obj in shown:
        obj.select_set(True)
        if obj.data in meshes or obj.data.library:
            continue
        meshes.add(obj.data)
        _select_faces(obj.data, found[obj])
    if shown:
        context.view_layer.objects.active = shown[0]
    return shown


def _found_text(found, shown):
    hidden = len(found) - len(shown)
    return (f"in {len(found)} object(s), selected" + (f" ({hidden} hidden, not selected)" if hidden else "") + ": "
            + ", ".join(obj.name for obj in list(found)[:5]) + (" ..." if len(found) > 5 else ""))


class FSS_OT_FindFacesWithoutArea(bpy.types.Operator):
    bl_idname = "fss.find_faces_without_area"
    bl_label = "Find Faces Without Area"
    bl_description = ("Select the mesh objects with faces that have no area (collapsed faces, at most "
                      f"{uv_pack.FACE_AREA_MIN_CM2:g} cm2), so the geometry can be fixed. In Edit Mode those faces "
                      "are selected")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        found = faces_without_area(context.view_layer)
        shown = _select_found(context, found)
        faces = sum(len(f) for f in found.values())
        for obj, f in sorted(found.items(), key=lambda item: item[0].name):
            print(f"FSS checks: {obj.name}: {len(f)} face(s) without area")
        if not found:
            self.report({'INFO'}, "No faces without area")
        else:
            self.report({'WARNING'}, f"{faces} face(s) without area {_found_text(found, shown)}")
        return {'FINISHED'}


class FSS_OT_FindFacesWithoutUvArea(bpy.types.Operator):
    bl_idname = "fss.find_faces_without_uv_area"
    bl_label = "Find Faces Without UV Area"
    bl_description = ("Select the mesh objects with faces that have area but a triangle without UV area (at most "
                      f"{uv_pack.UV_TRI_AREA_MIN_PX2:g} px2 of their texture set) inside an island: these needles push "
                      "UV islands far out in packing. Re-unwrap them (for example Accept + Unwrap). In Edit Mode those "
                      "faces are selected")
    bl_options = {'REGISTER', 'UNDO'}

    # one texture set only (its row's name in UV Auto Packing); empty: every texture set
    material: bpy.props.StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        t0 = time.perf_counter()
        only, where = EVERY_SET, ''
        if self.material:
            only = bpy.data.materials.get(self.material)
            if only is None:
                self.report({'ERROR'}, f"No material {self.material}")
                return {'CANCELLED'}
            where = f" of {self.material}"
        found, faces, islands = faces_without_uv_area(context.view_layer, only)
        shown = _select_found(context, found)
        for obj, f in sorted(found.items(), key=lambda item: item[0].name):
            print(f"FSS checks: {obj.name}: {len(f)} face(s) with triangles without UV area{where}")
        seconds = time.perf_counter() - t0
        if not found:
            self.report({'INFO'}, f"No faces without UV area{where} ({seconds:.1f} s)")
        else:
            self.report({'WARNING'}, f"{faces} face(s) with triangles without UV area{where} in {islands} island(s) "
                                     f"{_found_text(found, shown)} ({seconds:.1f} s)")
        return {'FINISHED'}


ANIM_FRAME_START, ANIM_FRAME_END = 0.0, 100.0


def _off_standard(start, end):
    return abs(start - ANIM_FRAME_START) > 1e-3 or abs(end - ANIM_FRAME_END) > 1e-3


def animations_off_range(view_layer):
    """{object: [(description, start, end, plays)]} over the view layer's local objects whose active action, an NLA
    strip's placement or a strip's action does not run from frame 0 to 100. plays is where a strip plays that action in
    the scene, None for the others. Muted strips count: they can be unmuted."""
    found = {}
    for obj in view_layer.objects:
        data = obj.animation_data
        if obj.library or data is None:
            continue
        off = []
        if data.action and _off_standard(*data.action.frame_range):
            off.append((f"action {data.action.name}", *data.action.frame_range, None))
        for track in data.nla_tracks:
            for strip in track.strips:
                if _off_standard(strip.frame_start, strip.frame_end):
                    off.append((f"strip {strip.name}", strip.frame_start, strip.frame_end, None))
                if strip.action and _off_standard(*strip.action.frame_range):
                    off.append((f"action {strip.action.name}", *strip.action.frame_range,
                                (strip.frame_start, strip.frame_end)))
        if off:
            found[obj] = off
    return found


def _breach_lines(what, start, end, plays):
    """A breach in words. In tweak mode the Action Editor draws a strip's keys at their scene time, so a strip's action
    says both numbers: where its keys are stored, which the editors do not show, and where it plays."""
    if plays is None:
        return [f"{what}: {start:g} to {end:g}"]
    return [f"{what}:", f"keys stored at {start:g} to {end:g}, plays at {plays[0]:g} to {plays[1]:g}"]


class FSS_AnimationOffRangeRow(bpy.types.PropertyGroup):
    """One object in the list; `name` is the object's name."""
    ranges: bpy.props.StringProperty()  # the first range, and how many more
    details: bpy.props.StringProperty()  # every breach, one per line


_filling = False  # the list is being filled: setting the active row is not a click


def _can_select(obj, view_layer):
    """Blender cannot select an object that is hidden or outside the view layer."""
    return obj is not None and obj.name in view_layer.objects and obj.visible_get(view_layer=view_layer)


def _select_only(context, objects):
    """Select these objects and nothing else, the first active. In Object Mode."""
    for obj in context.selected_objects:
        obj.select_set(False)
    for obj in objects:
        obj.select_set(True)
    if objects:
        context.view_layer.objects.active = objects[0]


def _select_listed_row(context):
    """Select the list's active row's object. False when there is none, or Blender cannot select it."""
    wm = context.window_manager
    rows = wm.fss_anim_off_rows
    if context.mode != 'OBJECT' or not 0 <= wm.fss_anim_off_active < len(rows):
        return False
    obj = bpy.data.objects.get(rows[wm.fss_anim_off_active].name)
    if not _can_select(obj, context.view_layer):
        return False
    _select_only(context, [obj])
    return True


def _anim_row_clicked(_wm, context):
    if not _filling:
        _select_listed_row(context)


def _fill_animation_rows(wm, found):
    global _filling
    _filling = True
    try:
        rows = wm.fss_anim_off_rows
        rows.clear()
        for obj, off in sorted(found.items(), key=lambda item: item[0].name):
            row = rows.add()
            row.name = obj.name
            row.ranges = f"{off[0][1]:g} - {off[0][2]:g}" + (f" (+{len(off) - 1})" if len(off) > 1 else "")
            row.details = "\n".join(line for breach in off for line in _breach_lines(*breach))
        wm.fss_anim_off_active = -1  # no row is clicked yet: finding selects nothing
    finally:
        _filling = False


class FSS_OT_FindAnimationsOffRange(bpy.types.Operator):
    bl_idname = "fss.find_animations_off_range"
    bl_label = "Find Animations Not 0 to 100"
    bl_description = ("List the objects whose action or NLA strips do not run from frame 0 to 100, the project's "
                      "rule. Nothing is changed. A click on a row selects its object")
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        found = animations_off_range(context.view_layer)
        _fill_animation_rows(context.window_manager, found)
        if not found:
            self.report({'INFO'}, "All animations run from frame 0 to 100")
            return {'FINISHED'}
        for obj, off in sorted(found.items(), key=lambda item: item[0].name):
            for breach in off:
                print(f"FSS checks: {obj.name}: {' '.join(_breach_lines(*breach))}")
        self.report({'WARNING'}, f"{len(found)} object(s) with animation not 0 to 100, listed under the button")
        return {'FINISHED'}


class FSS_OT_AnimationOffRangeSelect(bpy.types.Operator):
    bl_idname = "fss.animation_off_range_select"
    bl_label = "Select"
    bl_description = "Select the object of the list's active row"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and 0 <= context.window_manager.fss_anim_off_active < len(context.window_manager.fss_anim_off_rows)

    def execute(self, context):
        if not _select_listed_row(context):
            self.report({'WARNING'}, "This object is hidden or no longer there, so it cannot be selected")
            return {'CANCELLED'}
        return {'FINISHED'}


class FSS_OT_AnimationOffRangeSelectAll(bpy.types.Operator):
    bl_idname = "fss.animation_off_range_select_all"
    bl_label = "Select All"
    bl_description = "Select every listed object that is not hidden"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and len(context.window_manager.fss_anim_off_rows) > 0

    def execute(self, context):
        rows = context.window_manager.fss_anim_off_rows
        listed = [bpy.data.objects.get(row.name) for row in rows]
        shown = [obj for obj in listed if _can_select(obj, context.view_layer)]
        if shown:
            _select_only(context, shown)
        hidden = len(rows) - len(shown)
        self.report({'INFO'}, f"{len(shown)} object(s) selected" + (f", {hidden} hidden, not selected" if hidden else ""))
        return {'FINISHED'}


class FSS_UL_AnimationsOffRange(bpy.types.UIList):
    bl_idname = 'FSS_UL_animations_off_range'

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        obj = bpy.data.objects.get(item.name)
        split = layout.split(factor=0.68)
        split.label(text=item.name, icon='OBJECT_DATA' if _can_select(obj, context.view_layer) else 'HIDE_ON')
        split.label(text=item.ranges)


def _draw_animations_off_range(layout, context):
    """The button, and under it what it found: a click on a row selects its object."""
    wm = context.window_manager
    layout.operator(FSS_OT_FindAnimationsOffRange.bl_idname, icon='ANIM')
    rows = wm.fss_anim_off_rows
    if not rows:
        return
    layout.template_list(FSS_UL_AnimationsOffRange.bl_idname, '', wm, 'fss_anim_off_rows', wm, 'fss_anim_off_active',
                         rows=ANIM_LIST_ROWS)
    buttons = layout.row(align=True)
    buttons.operator(FSS_OT_AnimationOffRangeSelect.bl_idname, icon='RESTRICT_SELECT_OFF')
    buttons.operator(FSS_OT_AnimationOffRangeSelectAll.bl_idname)
    if 0 <= wm.fss_anim_off_active < len(rows):
        row = rows[wm.fss_anim_off_active]
        details = layout.column(align=True)
        details.scale_y = 0.8
        for line in row.details.split("\n"):
            details.label(text=line)
        if not _can_select(bpy.data.objects.get(row.name), context.view_layer):
            details.label(text="Hidden or no longer there: not selected", icon='INFO')


@persistent
def _on_load_post(*_args):
    """The list belongs to the file it was found in."""
    wm = bpy.context.window_manager
    if wm is not None and hasattr(bpy.types.WindowManager, 'fss_anim_off_rows'):
        _fill_animation_rows(wm, {})


class FSS_PT_Checks(bpy.types.Panel):
    bl_idname = "FSS_PT_checks"
    bl_label = "Checks"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "FSS Tools"
    bl_order = 3
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        name_check.draw(layout, context)
        layout.operator(FSS_OT_FixBoneParents.bl_idname, icon='BONE_DATA')
        layout.operator(FSS_OT_FindFacesWithoutArea.bl_idname, icon='MESH_PLANE')
        layout.operator(FSS_OT_FindFacesWithoutUvArea.bl_idname, icon='UV')
        _draw_animations_off_range(layout, context)


CLASSES = (
    FSS_OT_FixBoneParents,
    FSS_OT_FindFacesWithoutArea,
    FSS_OT_FindFacesWithoutUvArea,
    FSS_AnimationOffRangeRow,
    FSS_OT_FindAnimationsOffRange,
    FSS_OT_AnimationOffRangeSelect,
    FSS_OT_AnimationOffRangeSelectAll,
    FSS_UL_AnimationsOffRange,
    FSS_PT_Checks,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    wm = bpy.types.WindowManager
    wm.fss_anim_off_rows = bpy.props.CollectionProperty(type=FSS_AnimationOffRangeRow)
    wm.fss_anim_off_active = bpy.props.IntProperty(name='Active Object', default=-1, update=_anim_row_clicked,
                                                   description='A click on a row selects its object')
    bpy.app.handlers.load_post.append(_on_load_post)


def unregister():
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    wm = bpy.types.WindowManager
    del wm.fss_anim_off_active
    del wm.fss_anim_off_rows
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
