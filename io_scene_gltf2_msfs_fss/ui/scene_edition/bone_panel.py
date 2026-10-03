import bpy

class MSFS2024_PT_BoneProperties(bpy.types.Panel):
    bl_label = "MSFS2024 Bone Properties"
    bl_idname = "BONE_PT_msfs2024_bone_properties"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "bone"
    
    @classmethod
    def poll(cls, context):
        return context.active_bone is not None

    def draw(self, context):
        if context.mode == "EDIT_ARMATURE":
            return
        
        layout = self.layout
        box = None
        active_bone = context.active_bone
        
        if hasattr(active_bone, "msfs_override_unique_id"):
            box = layout.box()
            box.prop(active_bone,"msfs_override_unique_id")
            if active_bone.msfs_override_unique_id:
                box.prop(active_bone, "msfs_unique_id")
                
        if hasattr(active_bone, "msfs_facial_animation"):
            if box is None:
                box = layout.box()
            box.prop(active_bone, "msfs_facial_animation")