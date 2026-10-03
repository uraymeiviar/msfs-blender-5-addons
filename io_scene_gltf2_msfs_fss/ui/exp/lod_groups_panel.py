from __future__ import annotations

import bpy

from _addons_common.ui.tree_widget.view_ope import  TREEVIEW_OT_ExpandAllItems

from io_scene_gltf2_msfs_fss.io.exp import lod_groups as exp_lod_groups
from io_scene_gltf2_msfs_fss.io.exp.lod_groups import MultiExporterLOD, MultiExporterLODGroup

from io_scene_gltf2_msfs_fss.ui.exp  import lod_groups_ops, lod_groups_uilist


def _get_number_lods(context: bpy.types.Context):
    scene_lod_groups = exp_lod_groups.get_scene_lod_groups(context.scene)

    total_lods = 0
    for lod_group in scene_lod_groups:
        total_lods += len(lod_group.lods)

    return total_lods

def _draw_active_lod_group_settings(context, lod_group, layout):
    box = layout.box()
    box.label(text="LOD Group Settings:")
    row = box.row()
    if bpy.app.version > (4, 0, 0):
        row.prop(lod_group, "folder_path", text="", placeholder="Export Folder")
    else:
        row.prop(lod_group, "folder_path", text="")
    box.prop(lod_group, "settings_preset", text="Export Preset")
    row = box.row()
    row.prop(lod_group, "generate_xml", text="Generate XML")
    row = row.split()

    row.prop(lod_group, "autogenerate_lods", text="Enable Auto LOD")
    row.prop(lod_group, "overwrite_guid", text="Overwrite GUID")
    row.enabled = lod_group.generate_xml

def draw_lod_groups_panel(layout: bpy.types.UILayout, context: bpy.types.Context):


    layout.operator(
        lod_groups_ops.MSFS2024_OT_ReloadLODGroups.bl_idname,
        text="Reload LODs",
        icon="FILE_REFRESH",
    )
    row = layout.row(align=True)
    row.prop(
        context.scene, "msfs_ui_tree_objects_sync_selection", text="Sync Selection"
    )
    TREEVIEW_OT_ExpandAllItems.draw_expand_all_buttons(
        row, 
        lod_groups_uilist.MSFS2024_UL_LODGroups.tree_manager_name
    )
    total_lods = _get_number_lods(context)

    if total_lods == 0:
        box = layout.box()
        box.label(text="No LODs found in scene")
    else:
        lod_groups_uilist.MSFS2024_UL_LODGroups.draw_UL_TreeView(
            context, 
            layout, 
            rows=4
        )
        lod_group_tree_manager = lod_groups_uilist.get_lod_group_tree_manager()
        active_item = None
        if lod_group_tree_manager:
            active_item = lod_group_tree_manager.get_active_item()

        if active_item:
            active_data = active_item.get_data()
            lod_group = None
            if isinstance(active_data,MultiExporterLODGroup):
                lod_group = active_data
            elif isinstance(active_data, MultiExporterLOD):
                lod_group = active_item.get_parent_data()
            if lod_group:
                _draw_active_lod_group_settings(context,lod_group, layout)



