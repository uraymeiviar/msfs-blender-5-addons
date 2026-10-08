from __future__ import annotations

import bpy


from io_scene_gltf2_msfs_fss.io.exp.presets  import MultiExporterPreset, MultiExporterPresetGroup

from io_scene_gltf2_msfs_fss.ui.exp import preset_ops, preset_uilist

from _addons_common.ui.tree_widget.view_ope import  TREEVIEW_OT_ExpandAllItems


def _draw_active_preset_settings(context: bpy.types.Context, preset: MultiExporterPreset, layout: bpy.types.UILayout):
    box = layout.box()
    box.label(text="Preset Settings:")
    row = box.row()
    row.prop(preset, "preset_name",text="Name")

    if bpy.app.version > (4, 0, 0):
        box.prop(preset, "folder_path", text="Export Path", placeholder="Export Folder")
    else:
        box.prop(preset, "folder_path", text="Export Path")
    box.prop(preset, "settings_preset", text="Export Preset")

def _draw_active_preset_group_settings(
    context: bpy.types.Context,
    preset_group: MultiExporterPresetGroup,
    layout: bpy.types.UILayout,
):
    box = layout.box()
    box.label(text="Preset Group Settings:")
    box.prop(preset_group, "group_name",text="Name")
    if bpy.app.version > (4, 0, 0):
        box.prop(preset_group, "folder_path", text="Export Path", placeholder="Export Folder")
    else:
        box.prop(preset_group, "folder_path", text="Export Path")
    box.prop(preset_group, "settings_preset", text="Export Preset")

def draw_presets_panel(layout: bpy.types.UILayout, context: bpy.types.Context):
    row = layout.row()
    row.operator(preset_ops.MSFS2024_OT_AddPreset.bl_idname, text="Add Preset", icon="FILE_NEW").group_id = ""
    row.operator(preset_ops.MSFS2024_OT_AddPresetGroup.bl_idname, text="Add Group", icon="NEWFOLDER")
    row = layout.row()
    row.prop(context.scene,"msfs_ui_tree_presets_sync_selection",text="Sync Selection")
    TREEVIEW_OT_ExpandAllItems.draw_expand_all_buttons(
        row, 
        preset_uilist.MSFS2024_UL_Presets.tree_manager_name
    )
    preset_uilist.MSFS2024_UL_Presets.draw_UL_TreeView(context, layout, rows=4)
    preset_tree_manager = preset_uilist.get_preset_tree_manager()
    active_item = None
    if preset_tree_manager: 
        active_item = preset_tree_manager.get_active_item()
    
    if active_item:
        active_data = active_item.get_data()
        if isinstance(active_data,MultiExporterPreset):
            _draw_active_preset_settings(context,active_data,layout)
        elif isinstance(active_data,MultiExporterPresetGroup):
            _draw_active_preset_group_settings(context,active_data,layout)

