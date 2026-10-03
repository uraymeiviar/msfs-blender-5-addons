import bpy

from io_scene_gltf2_msfs_fss.blender.utils.msfs_scene_utils import MSFS2024_SceneUtils
from io_scene_gltf2_msfs_fss.ui.scene_edition import image_ops

class MSFS2024_OT_ConvertSceneTo2024(bpy.types.Operator):
    bl_idname = "msfs2024.convert_scene_to_2024"
    bl_label = "Convert all scene to be compatible with MSFS2024."
    bl_description = "This will convert all scene to be compatible with MSFS2024"

    def execute(self, context):
        
        if MSFS2024_SceneUtils.convert_scene_to_msfs2024():
            return {'FINISHED'}
        return {'CANCELLED'}

    def invoke(self, context, event):
        if bpy.app.version > (4,0,0):
            return context.window_manager.invoke_confirm(
                self,
                event,
                title="",
                message="WARNING: This will convert all scene to be compatible with MSFS2024.",
                icon="WARNING"
            )
        else:
            return context.window_manager.invoke_confirm(
                self,
                event
            )
        
class MSFS2024_OT_ConvertBlenderLights(bpy.types.Operator):
    bl_idname = "msfs2024.convert_blender_lights"
    bl_label = "Convert all blender lights to MSFS2024."
    bl_description = "Convert current scene lights to MSFS2024"

    def execute(self, context):
        MSFS2024_SceneUtils.convert_lights_to_msfs2024()
        return {'FINISHED'}

    def invoke(self, context, event):
        if bpy.app.version > (4,0,0):
            return context.window_manager.invoke_confirm(
                self,
                event,
                title="",
                message="WARNING: This will convert all blender lights to MSFS2024.",
                icon="WARNING"
            )
        else:
            return context.window_manager.invoke_confirm(
                self,
                event
            )

class MSFS2024_HeaderMenu(bpy.types.Menu):
    bl_label = "MSFS2024"
    bl_idname = "VIEW3D_MT_MSFS2024"
    bl_context = "objectmode"

    def draw(self, context):
        layout = self.layout
        layout.operator(
            operator=MSFS2024_OT_ConvertSceneTo2024.bl_idname, 
            text="Convert Scene to MSFS2024"
        )
        layout.operator(
            operator=MSFS2024_OT_ConvertBlenderLights.bl_idname, 
            text="Convert Lights"
        )
        layout.operator(
            operator=image_ops.MSFS2024_OT_SetImageFlags.bl_idname, 
            text="Set Image Flags"
        )

def draw_menu(self, context):
    self.layout.menu(MSFS2024_HeaderMenu.bl_idname)

def register():
    bpy.types.VIEW3D_MT_editor_menus.append(draw_menu)

def unregister():
    bpy.types.VIEW3D_MT_editor_menus.remove(draw_menu)
