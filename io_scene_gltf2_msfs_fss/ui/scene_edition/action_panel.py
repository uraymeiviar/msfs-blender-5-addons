import bpy

class MSFS2024_PT_ActionProperties(bpy.types.Panel):
    bl_label = "MSFS2024 Action Parameters"
    bl_idname = "ACTION_PT_msfs2024_action_properties"
    bl_space_type = "DOPESHEET_EDITOR"
    bl_category = "Action"
    bl_region_type = "UI"
    bl_context = "data"
    
    @classmethod
    def poll(cls, context):
        return context.active_action is not None and context.object.mode in ("POSE", "OBJECT")

    def draw(self, context):
        layout = self.layout
        box = None
        active_action = context.active_action
        if hasattr(active_action, "msfs_facial_animation"):
            box = layout.box()
            box.prop(active_action, "msfs_facial_animation")
