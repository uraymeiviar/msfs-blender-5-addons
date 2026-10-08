from __future__ import annotations


import bpy
from bpy.types import Context

from io_scene_gltf2_msfs_fss.io.exp import lod_groups

class MSFS2024_OT_ReloadLODGroups(bpy.types.Operator):
    bl_idname = "msfs2024.reload_lod_groups"
    bl_label = "Reload LOD groups"
    bl_description = "Reload LOD Groups. Press it when adding, deleting or renaming LOD Groups"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context: Context) -> bool:
        return context.scene
    
    def execute(self, context: bpy.types.Context):

        from io_scene_gltf2_msfs_fss.ui.exp import lod_groups_uilist
        lod_group_tree_manager = lod_groups_uilist.get_lod_group_tree_manager()
        if not lod_group_tree_manager:
            return {"CANCELLED"}
        # Reset Multiselection
        lod_group_tree_manager.unselect_all()
        lod_groups.reload_lod_groups(context.scene)
        lod_group_tree_manager.generate_tree_collection()
        return {"FINISHED"}





