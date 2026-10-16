"""Checks: repairs for scene states that break the export silently (the start of the wish-list "stupidity check").

Broken bone parents: an object keeps a parent bone after its parent was changed to something that has no bones
(an empty, a mesh). Blender then reports "Failed to add relation Bone Parent" on every depsgraph build, and the parent
type reads as invalid, so the Relations panel cannot reset it.
Rules and decisions: codes/wasm/doc/journal/20261014.fss-blender-tools-tags-and-merge.md (FSS repository).
"""

import bpy

from . import name_check


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


class FSS_PT_Checks(bpy.types.Panel):
    bl_idname = "FSS_PT_checks"
    bl_label = "Checks"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "FSS Tools"

    def draw(self, context):
        layout = self.layout
        name_check.draw(layout, context)
        layout.operator(FSS_OT_FixBoneParents.bl_idname, icon='BONE_DATA')


CLASSES = (
    FSS_OT_FixBoneParents,
    FSS_PT_Checks,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
