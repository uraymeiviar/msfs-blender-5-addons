"""Checks: repairs for scene states that break the export silently (the start of the wish-list "stupidity check").

Broken bone parents: an object keeps a parent bone after its parent was changed to something that has no bones
(an empty, a mesh). Blender then reports "Failed to add relation Bone Parent" on every depsgraph build, and the parent
type reads as invalid, so the Relations panel cannot reset it.
Faces without area: faces whose world-space area is (near) zero push islands far out in packing (UV journal
decision 117, uv_pack.FACE_AREA_MIN_CM2); the check selects the objects that have them, so the artist fixes the mesh.
Rules and decisions: codes/wasm/doc/journal/20261014.fss-blender-tools-tags-and-merge.md (FSS repository).
"""

import bpy

from . import name_check, uv_pack


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


class FSS_OT_FindFacesWithoutArea(bpy.types.Operator):
    bl_idname = "fss.find_faces_without_area"
    bl_label = "Find Faces Without Area"
    bl_description = ("Select the mesh objects with faces that have no area (collapsed faces, at most "
                      f"{uv_pack.FACE_AREA_MIN_CM2:g} cm2): they push UV islands far out in packing. In Edit Mode "
                      "those faces are selected")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        found = faces_without_area(context.view_layer)
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
            # only these faces selected, so Edit Mode shows them
            select = [False] * len(obj.data.polygons)
            for index in found[obj]:
                select[index] = True
            obj.data.polygons.foreach_set('select', select)
            obj.data.update()
        if shown:
            context.view_layer.objects.active = shown[0]
        faces = sum(len(f) for f in found.values())
        for obj, f in sorted(found.items(), key=lambda item: item[0].name):
            print(f"FSS checks: {obj.name}: {len(f)} face(s) without area")
        if not found:
            self.report({'INFO'}, "No faces without area")
        else:
            hidden = len(found) - len(shown)
            self.report({'WARNING'}, f"{faces} face(s) without area in {len(found)} object(s), selected"
                                     + (f" ({hidden} hidden, not selected)" if hidden else "") + ": "
                                     + ", ".join(obj.name for obj in list(found)[:5]) + (" ..." if len(found) > 5 else ""))
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


CLASSES = (
    FSS_OT_FixBoneParents,
    FSS_OT_FindFacesWithoutArea,
    FSS_PT_Checks,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
