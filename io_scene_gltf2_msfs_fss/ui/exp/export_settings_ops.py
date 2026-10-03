import bpy

from io_scene_gltf2_msfs_fss.io.exp import export_settings

class MSFS2024_OT_AddSettingsPreset(bpy.types.Operator):
    bl_idname = "msfs2024.multi_export_add_settings_preset"
    bl_label = "Add settings preset"
    bl_options = {"INTERNAL"}

    def execute(self, context: bpy.types.Context):
        export_settings.add_export_settings_preset(context.scene, set_active=True)
        # Update Enum
        return {"FINISHED"}


class MSFS2024_OT_RemoveSettingsPreset(bpy.types.Operator):
    bl_idname = "msfs2024.multi_export_remove_settings_preset"
    bl_label = "Remove settings preset"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:

        return not export_settings.active_export_settings_is_default(context.scene)
    
    def execute(self, context: bpy.types.Context):
        active_settings_preset = export_settings.get_active_export_settings(context.scene)
        export_settings.remove_export_settings_preset(context.scene, active_settings_preset.name)
        return {"FINISHED"}


class MSFS2024_OT_EditSettingsPresetName(bpy.types.Operator):
    bl_idname = "msfs2024.multi_export_edit_settings_preset_name"
    bl_label = "Edit settings preset name"
    bl_options = {"INTERNAL"}

    preset_name : bpy.props.StringProperty(name="") # type: ignore
    
    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return not export_settings.active_export_settings_is_default(context.scene)
    
    def invoke(self, context: bpy.types.Context, event: bpy.types.Event):
        active_settings_preset = export_settings.get_active_export_settings(context.scene)
        self.preset_name = active_settings_preset.name
        wm = context.window_manager
        return wm.invoke_props_dialog(self)

    def draw(self, context: bpy.types.Context):
        self.layout.prop(self, "preset_name")

    def execute(self, context: bpy.types.Context):
        active_settings_preset = export_settings.get_active_export_settings(context.scene)
        active_settings_preset.name = export_settings.get_unique_preset_name(context.scene, self.preset_name)
        if context.area:
            context.area.tag_redraw() # force area redraw in order force update of preset name
    
        return {"FINISHED"}

