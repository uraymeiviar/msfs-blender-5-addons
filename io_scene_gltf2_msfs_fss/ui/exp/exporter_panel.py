from __future__ import annotations
import bpy

from enum import Enum

from _addons_common.ui import window

from io_scene_gltf2_msfs_fss.io.exp import export_settings, multi_export_mode, subprocess
from io_scene_gltf2_msfs_fss.io.exp import multi_export

from io_scene_gltf2_msfs_fss.io.com import msfs_logs

from io_scene_gltf2_msfs_fss.ui.exp import exporter_panel_ops, exporter_progress_bar, lod_groups_ops, lod_groups_panel, presets_panel

class PanelTab(Enum):
    HIERARCHY = ("HIERARCHY", "Hierarchy")
    SETTINGS = ("SETTINGS", " Settings")

    def __init__(self, identifier: str, label: str):
        self.identifier = identifier
        self.label = label

    @classmethod
    def from_identifier(cls, identifier: str) -> PanelTab | None:

        for tab in cls:
            if tab.identifier == identifier:
                return tab
        return None

# region panels

def get_active_tab(scene: bpy.types.Scene) -> PanelTab | None:

    return PanelTab.from_identifier(scene.msfs_exporter_current_tab) # type: ignore


class MSFS2024_PT_MultiExporter(bpy.types.Panel):
    """Main Panel
    """
    bl_label = "Multi-Export glTF 2.0"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Microsoft Flight Simulator 2024 Tools"

    register_order = -1 # register before all child panels

    def draw(self, context: bpy.types.Context):
        layout = self.layout
        current_tab = context.scene.msfs_exporter_current_tab

        row = layout.row(align=True)
        hierarchy_tab_active = current_tab == PanelTab.HIERARCHY.identifier
        settings_tab_active = current_tab == PanelTab.SETTINGS.identifier
        row.operator(
            exporter_panel_ops.MSFS2024_OT_ChangeTab.bl_idname,
            text=PanelTab.HIERARCHY.label,
            depress=hierarchy_tab_active,
        ).current_tab = PanelTab.HIERARCHY.identifier
        row.operator(
            exporter_panel_ops.MSFS2024_OT_ChangeTab.bl_idname,
            text=PanelTab.SETTINGS.label,
            depress=settings_tab_active,
        ).current_tab = PanelTab.SETTINGS.identifier

        if hierarchy_tab_active:
            row = layout.row(align=True)
            row.label(text="Mode:")

            row = row.row(align=False)
            row.scale_x = 2
            icon = "OBJECT_DATA"
            text = "Objects"
            export_mode = multi_export_mode.get_active_export_mode(context.scene)
            if export_mode == multi_export_mode.ExportMode.COLLECTIONS:
                icon = "OUTLINER_COLLECTION"
                text = "Collections"
            elif export_mode == multi_export_mode.ExportMode.PRESETS:
                icon = "PRESET_NEW"
                text = "Presets"

            row.operator_menu_enum(
                exporter_panel_ops.MSFS2024_OT_SetHierarchyMode.bl_idname,
                "export_mode",
                text = text,
                icon = icon
            )
      

            if (export_mode == multi_export_mode.ExportMode.OBJECTS) or (export_mode == multi_export_mode.ExportMode.COLLECTIONS):
                lod_groups_panel.draw_lod_groups_panel(self.layout, context)
            elif export_mode == multi_export_mode.ExportMode.PRESETS:
                presets_panel.draw_presets_panel(self.layout, context)

            _draw_export_button(context, self.layout, export_mode)

    def draw_header_preset(self, context: bpy.types.Context) -> None:
        self.layout.operator(exporter_panel_ops.MSFS2024_OT_OpenDocumentation.bl_idname, icon="HELP", text="")
        window.draw_new_window_ope(self.layout)

def _draw_export_button(
    context: bpy.types.Context,
    layout: bpy.types.UILayout,
    export_mode: multi_export_mode.ExportMode,
):  
    """Draw the export operator button in the UI.

    If a subprocess export is currently running, this will draw
    a progress bar and a cancel button instead of the regular export button.
    """
    if subprocess.is_msfs_subprocess_exporting():
        exporter_progress_bar.draw_progress_bar(context, layout)
        subprocess.draw_cancel_button(context, layout)
    else:
        
        if context.scene.msfs_background_export:
            layout.operator(
                subprocess.MSFS2024_OT_SubProcessExport.bl_idname,
                text="Export",
                icon="EXPORT",
            ).export_mode = export_mode.identifier
        else:
            layout.operator(
                multi_export.MSFS2024_OT_MultiExportGLTF2.bl_idname, text="Export", icon="EXPORT"
            ).export_mode = export_mode.identifier

class MSFS2024_PT_Logs(bpy.types.Panel):
    bl_label = "Logs"
    bl_parent_id = "MSFS2024_PT_MultiExporter"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Multi-Export glTF 2.0"

    register_order = 1

    @classmethod
    def poll(cls, context: bpy.types.Context):
        return get_active_tab(context.scene) == PanelTab.HIERARCHY 

    def draw(self, context: bpy.types.Context):
        logger = msfs_logs.get_logger()
        logger.ul_tree_view_class.draw_UL_TreeView(context, self.layout, 5)

    def draw_header_preset(self, context: bpy.types.Context) -> None:
        logger = msfs_logs.get_logger()
        logger.ul_tree_view_class.draw_header_preset(context, self.layout, logger)

def register():

    bpy.types.Scene.msfs_exporter_current_tab = bpy.props.EnumProperty( # type: ignore
        items=(
            (PanelTab.HIERARCHY.identifier, PanelTab.HIERARCHY.label, ""),
            (PanelTab.SETTINGS.identifier, PanelTab.SETTINGS.label, ""),
        )
    )
    bpy.types.Scene.msfs_ui_tree_objects_sync_selection = bpy.props.BoolProperty( # type: ignore
        default=False, 
        description="Select corresponding scene objects when an item is selected in exporter hierarchy"
    )

def unregister():
  
    try:
        del bpy.types.Scene.msfs_exporter_current_tab # type: ignore
        del bpy.types.Scene.msfs_ui_tree_objects_sync_selection # type: ignore  

    except:
        pass
