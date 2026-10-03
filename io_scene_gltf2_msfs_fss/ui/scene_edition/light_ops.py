import bpy

from io_scene_gltf2_msfs_fss.blender import msfs_lights


class MSFS2024AddLight(bpy.types.Operator):
    bl_idname = "msfs2024.add_light"
    bl_label = "Add MSFS2024 Light"
    bl_options = {"REGISTER", "UNDO"}

    msfs_light_type: bpy.props.StringProperty(default=msfs_lights.MSFS2024LightType.STREET_LIGHT.identifier) # type: ignore

    def execute(self, context):
        msfs_light_type = msfs_lights.MSFS2024LightType.from_identifier(
            self.msfs_light_type
        )
        msfs_lights.add_light(
            msfs_light_type=msfs_light_type,
            view_layer=bpy.context.view_layer,
            collection=bpy.context.collection,
            location=context.scene.cursor.location,
        )

        return {"FINISHED"}
