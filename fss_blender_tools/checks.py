"""Checks: repairs for scene states that break the export silently (the start of the wish-list "stupidity check").

Broken bone parents: an object keeps a parent bone after its parent was changed to something that has no bones
(an empty, a mesh). Blender then reports "Failed to add relation Bone Parent" on every depsgraph build, and the parent
type reads as invalid, so the Relations panel cannot reset it.
Faces without area: faces whose world-space area is (near) zero (UV journal decision 117, uv_pack.FACE_AREA_MIN_CM2);
the check selects the objects that have them, so the artist fixes the mesh.
Faces without UV area: faces with a triangle that has 3D area but no UV area (uv_pack.UV_TRI_AREA_MIN_PX2) inside an
island that has UV area. These needles push islands far out of the packed layout (decision 118); re-unwrapping the
part fixes them. A second button, not part of Find Faces Without Area: the two need different fixes.
Rules and decisions: codes/wasm/doc/journal/20261014.fss-blender-tools-tags-and-merge.md (FSS repository).
"""

import time

import numpy as np

import bpy

from . import name_check, uv_marks, uv_pack


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


def faces_without_uv_area(view_layer):
    """({object: indices of its faces with a triangle without UV area inside an island that has UV area}, number of
    such faces, number of such islands) over the view layer's local mesh objects with a UV map, per texture set at its
    size (decision 118). A mesh shared by several objects is read once, with its first user's materials (as the
    packer does); every user is listed."""
    cm2 = uv_pack._cm_per_unit(bpy.context.scene) ** 2
    found = {}
    count = islands = 0
    for me, users in uv_pack._meshes(view_layer).items():
        md = uv_pack.MeshData(me)
        hit = []
        for material in {slot.material for slot in users[0].material_slots} | {None}:
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
        select = [False] * len(obj.data.polygons)
        for index in found[obj]:
            select[index] = True
        obj.data.polygons.foreach_set('select', select)
        obj.data.update()
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

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        t0 = time.perf_counter()
        found, faces, islands = faces_without_uv_area(context.view_layer)
        shown = _select_found(context, found)
        for obj, f in sorted(found.items(), key=lambda item: item[0].name):
            print(f"FSS checks: {obj.name}: {len(f)} face(s) with triangles without UV area")
        seconds = time.perf_counter() - t0
        if not found:
            self.report({'INFO'}, f"No faces without UV area ({seconds:.1f} s)")
        else:
            self.report({'WARNING'}, f"{faces} face(s) with triangles without UV area in {islands} island(s) "
                                     f"{_found_text(found, shown)} ({seconds:.1f} s)")
        return {'FINISHED'}


class FSS_PT_Checks(bpy.types.Panel):
    bl_idname = "FSS_PT_checks"
    bl_label = "Checks"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "FSS Tools"
    bl_parent_id = "FSS_PT_utilities"
    bl_order = 3

    def draw(self, context):
        layout = self.layout
        name_check.draw(layout, context)
        layout.operator(FSS_OT_FixBoneParents.bl_idname, icon='BONE_DATA')
        layout.operator(FSS_OT_FindFacesWithoutArea.bl_idname, icon='MESH_PLANE')
        layout.operator(FSS_OT_FindFacesWithoutUvArea.bl_idname, icon='UV')


CLASSES = (
    FSS_OT_FixBoneParents,
    FSS_OT_FindFacesWithoutArea,
    FSS_OT_FindFacesWithoutUvArea,
    FSS_PT_Checks,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
