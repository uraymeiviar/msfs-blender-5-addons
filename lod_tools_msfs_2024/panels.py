import bpy
from lod_tools_msfs_2024 import lod_camera, lod_viewer, active_lod_viewer, prefs, operators, data_utils
from lod_tools_msfs_2024.datafiles.asset_library import MSFS2024LODViewerInputs


class MSFS2024_OT_OpenLODToolsDocumentation(bpy.types.Operator):
    bl_idname = "msfs204.open_lod_tools_documentation"
    bl_label = "Open Documentation"
    bl_description = "Open the MSFS 2024 documentation in your browser"

    def execute(self, context):
        import webbrowser
        from lod_tools_msfs_2024 import DOC

        webbrowser.open(DOC)
        return {'FINISHED'}

class MSFS2024_PT_LODTools(bpy.types.Panel):
    bl_label = "LOD Tools"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Microsoft Flight Simulator 2024 Tools"
    bl_options = {'HEADER_LAYOUT_EXPAND'}

    register_order = -1

    def draw(self, context):
        row = self.layout.row(align=True)
        row.operator(operators.MSFS2024_OT_GenerateLODViewers.bl_idname, icon="PLAY")
        red_row = row.row()
        red_row.alert = True
        red_row.operator(operators.MSFS2024_OT_ClearLODPreview.bl_idname, icon="CANCEL", text="")
        lod_camera_active = lod_camera.is_lod_camera_active_in_ui_space(context)
        row = self.layout.row()
        text = "Enter LOD Camera"
        if lod_camera_active:
            text = "Exit LOD Camera"
            row.alert = True
        row.operator(
                operators.MSFS2024_OT_ToggleLODCamera.bl_idname, icon="OUTLINER_OB_CAMERA", text=text
            )

    def draw_header_preset(self, context: bpy.types.Context) -> None:
        self.layout.operator(MSFS2024_OT_OpenLODToolsDocumentation.bl_idname, icon="HELP", text="")


class MSFS2024_PT_LODSettings(bpy.types.Panel):
    bl_label = "Settings"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Microsoft Flight Simulator 2024 Tools"
    bl_options = {'DEFAULT_CLOSED'}
    bl_parent_id = "MSFS2024_PT_LODTools"

    register_order = 1

    def draw(self, context):
        addon_prefs = prefs.get_addon_prefs()
        if not addon_prefs:
            return
        row = self.layout.row()
        prefs.MSFS2024_LODTools_AddonPreferences.draw_render_preset(addon_prefs.render_settings, row)
        row.operator(operators.MSFS2024_OT_SetRenderSettings.bl_idname, icon="PREFERENCES", text="",emboss=False)
        prefs.MSFS2024_LODTools_AddonPreferences.draw_debug_settings(addon_prefs.debug_settings, self.layout)


class MSFS2024_PT_ActiveLODViewer(bpy.types.Panel):
    bl_label = "Active LOD Viewer"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Microsoft Flight Simulator 2024 Tools"

    bl_parent_id = "MSFS2024_PT_LODTools"

    register_order = 2

    @staticmethod
    def draw_no_viewer_selected(layout: bpy.types.UILayout):
        layout.label(text="No LOD Viewer Selected")

    def draw(self, context):
        active = active_lod_viewer.ActiveLODViewer
        if not active.valid_lod_viewer:
            self.draw_no_viewer_selected(self.layout)
            return
        if not data_utils.data_is_valid(active.object) or not data_utils.data_is_valid(active.modifier):
            active.reset()
            return
  
        row = self.layout.row()
        row.label(text="LOD Minimum Screen Size")
        row.operator(operators.MSFS2024_OT_SendSetupToExporter.bl_idname,text="", icon="EXPORT")
        for i in range(active.lod_count):
            screen_size_label = MSFS2024LODViewerInputs.get_lod_screen_size_input(i)
            if not screen_size_label:
                return
            screen_size_identifier = active.lod_viewer_input_map.get(screen_size_label.value, None)
            if not screen_size_identifier:
                return
            
            self.layout.prop(active.modifier, f'["{screen_size_identifier}"]', text=f"LOD{i}")



