import bpy

class MSFS2024_PT_ObjectProperties(bpy.types.Panel):
    bl_label = "MSFS2024 Object Parameters"
    bl_idname = "OBJECT_PT_msfs2024_object_properties"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        return context.active_object is not None
    
    def draw_object_properties(self, context, active_object, layout):
        box = layout.box()
        box.label(text = "MSFS2024 Object Parameters", icon="OBJECT_DATA")
        box.prop(active_object,"msfs_override_unique_id")
        if active_object.msfs_override_unique_id:
            box.prop(active_object, "msfs_unique_id")

    def draw_mesh_properties(self, context, active_object, layout):
        box = layout.box()
        box.label(text = "MSFS2024 Mesh Parameters", icon="MESH_DATA")
        box.prop(active_object.data, "msfs_softbody")

            
    def draw_transform_properties(self, context, active_object, layout):
        box = layout.box()
        box.label(text="MSFS2024 Transform Properties", icon="GIZMO")
        if active_object.type == "ARMATURE":
            # Reset Transform not supported on armature
            box.label(text="Not supported on Armature", icon="INFO")    
            return
        
        
        export_transform = active_object.msfs_export_transform
        box.prop(export_transform, "reset_translation")
        box.prop(export_transform, "reset_rotation")
        box.prop(export_transform, "reset_scale")

    def draw(self, context):
        layout = self.layout
        active_object = context.object

        self.draw_object_properties(context, active_object, layout)
        self.draw_transform_properties(context, active_object, layout)

        if active_object.type == "MESH":
            self.draw_mesh_properties(context, active_object, layout)
