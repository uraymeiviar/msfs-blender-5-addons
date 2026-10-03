import bpy

from io_scene_gltf2_msfs_fss.ui.scene_edition import light_ops
from io_scene_gltf2_msfs_fss.blender.msfs_lights import MSFS2024LightType

class MSFS2024LightsAddMenu(bpy.types.Menu):
    bl_idname = "VIEW3D_MT_msfs_lights2024_add_menu"
    bl_label = "Microsoft Flight Simulator 2024 Lights"

    def draw(self, context):
        add_fast_light_op = self.layout.operator(
            light_ops.MSFS2024AddLight.bl_idname,
            text="Fast Light",
            icon="LIGHT_POINT"
        )
        add_fast_light_op.msfs_light_type = MSFS2024LightType.STREET_LIGHT.identifier

        add_advanced_light_op = self.layout.operator(
            light_ops.MSFS2024AddLight.bl_idname,
            text="Advanced Light",
            icon="LIGHT_POINT"
        )
        add_advanced_light_op.msfs_light_type = MSFS2024LightType.ADVANCED_LIGHT.identifier

        add_skyportal_light_op = self.layout.operator(
            light_ops.MSFS2024AddLight.bl_idname,
            text="Sky Portal Light",
            icon="LIGHT_POINT"
        )
        add_skyportal_light_op.msfs_light_type = MSFS2024LightType.SKYPORTAL_LIGHT.identifier

def draw_menu(self, context):
    self.layout.menu(menu=MSFS2024LightsAddMenu.bl_idname, icon="OUTLINER_DATA_LIGHT")

def register():
    bpy.types.VIEW3D_MT_add.append(draw_menu)


def unregister():
    bpy.types.VIEW3D_MT_add.remove(draw_menu)
