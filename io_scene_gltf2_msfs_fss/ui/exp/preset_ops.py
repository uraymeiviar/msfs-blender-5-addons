from __future__ import annotations

import bpy

from io_scene_gltf2_msfs_fss.io.exp import presets as exp_presets

from io_scene_gltf2_msfs_fss.io.exp.presets import (
    MultiExporterPresetGroup,
    MultiExporterPreset
)

from _addons_common.ui.tree_widget.view_ope import  TREEVIEW_OT_ExpandAllItems

# region Preset Group
class MSFS2024_OT_AddPresetGroup(bpy.types.Operator):
    bl_idname = "msfs2024.multi_export_add_preset_group"
    bl_label = "Add group"
    bl_options = {"INTERNAL"}


    def execute(self, context: bpy.types.Context):

        preset_group = exp_presets.add_preset_group(context.scene)

        # Refresh UI
        from io_scene_gltf2_msfs_fss.ui.exp import preset_uilist
        preset_tree_manager = preset_uilist.get_preset_tree_manager()
        if not preset_tree_manager:
            return {"FINISHED"}
        
        preset_tree_manager.generate_tree_collection()
        preset_tree_manager.set_active_item_by_data(preset_group, update_selection=True)
        
        return {"FINISHED"}

class MSFS2024_OT_RemovePresetGroup(bpy.types.Operator):
    bl_idname = "msfs2024.multi_export_remove_preset_group"
    bl_label = "Remove group"
    bl_description = "Remove the group from the group list"
    bl_options = {"INTERNAL"}

    group_id: bpy.props.StringProperty(default="")  # type: ignore

    def execute(self, context: bpy.types.Context):

        from io_scene_gltf2_msfs_fss.ui.exp import preset_uilist
        to_remove = set((self.group_id,))

        # Also remove selected preset groups
        preset_tree_manager = preset_uilist.get_preset_tree_manager()
        if preset_tree_manager:
            selected_items = preset_tree_manager.get_selected_items()
            for item in selected_items:
                data = item.get_data()
                if isinstance(data, MultiExporterPresetGroup):
                    to_remove.add(data.name)

        for _ in to_remove:
            exp_presets.remove_preset_group(_, context.scene)

        # Refresh full data path after a preset deletion
        MultiExporterPresetGroup.update_groups_full_data_path(context.scene)
        MultiExporterPreset.update_presets_full_data_path(context.scene)

        # Refresh UI
        if preset_tree_manager:
            preset_tree_manager.generate_tree_collection()

        return {"FINISHED"}

class MSFS2024_OT_IsolateGroupPresetObjects(bpy.types.Operator):
    bl_idname = "msfs2024.multi_export_isolate_group_preset_object"
    bl_label = "Isolate group's object"
    bl_options = {"INTERNAL"}

    group_id: bpy.props.StringProperty(default="")  # type: ignore

    @classmethod
    def poll(cls, context: bpy.types.Context):
        return context.mode == "OBJECT"

    def execute(self, context: bpy.types.Context):
        scene_preset_groups = exp_presets.get_scene_exporter_preset_groups(context.scene)
        preset_group = scene_preset_groups.get(self.group_id, None)
        if not preset_group:
            return {"CANCELLED"}
        exp_presets.isolate_preset_objects(preset_group, context.view_layer)
        return {"FINISHED"}

class MSFS2024_OT_DuplicatePresetGroup(bpy.types.Operator):
    bl_idname = "msfs2024.multi_export_duplicate_preset_group"
    bl_label = "Duplicate group"
    bl_options = {"INTERNAL"}

    group_id: bpy.props.StringProperty(default="")  # type: ignore

    def execute(self, context: bpy.types.Context):

        from io_scene_gltf2_msfs_fss.ui.exp import preset_uilist

        preset_tree_manager = preset_uilist.get_preset_tree_manager()
        if not preset_tree_manager:
            return {"CANCELLED"}

        scene_groups = exp_presets.get_scene_exporter_preset_groups(context.scene)

        active_group: MultiExporterPresetGroup = scene_groups.get(self.group_id, None)
        if not active_group:
            return {"CANCELLED"}
        duplicated_group = exp_presets.duplicate_preset_group(active_group)

        preset_tree_manager.generate_tree_collection()
        preset_tree_manager.set_active_item_by_data(duplicated_group, update_selection=True)
        return {"FINISHED"}

# endregion

# region Preset
class MSFS2024_OT_EditLayers(bpy.types.Operator):
    bl_idname = "msfs2024.multi_export_edit_layers"
    bl_label = "Edit layers"
    bl_description = "Edit layers to be enabled or disabled for the preset"
    bl_options = {"INTERNAL"}

    preset_id: bpy.props.StringProperty(default="")  # type: ignore

    def execute(self, context: bpy.types.Context):
        return {"FINISHED"}

    def __del__(self):
        try:
            
            self.layers_tree_manager.unregister()
        except:
            pass

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event):

        from io_scene_gltf2_msfs_fss.ui.exp.preset_uilist import (
            LayerTreeManager,
            MSFS2024_UL_Layers,
        )
        scene_presets = exp_presets.get_scene_exporter_presets(context.scene)
        preset: MultiExporterPreset = scene_presets[self.preset_id]
        preset.load_preset_layers()

        # Register Layer Tree Manager
        self.layers_tree_manager = LayerTreeManager(
            ul_tree_view_class=MSFS2024_UL_Layers,
            alphabetical_order=True,
            multiselection_support=True,
            checkable_items=True,
        )

        self.layers_tree_manager.preset = preset

        # Generate Layers UI List
        self.layers_tree_manager.clear_ui_collection()
        self.layers_tree_manager.generate_tree_collection()
        self.layers_tree_manager.expose_checked_items()
        wm = context.window_manager
        return wm.invoke_popup(self, width=500)

    def draw(self, context: bpy.types.Context):
        # Title
        self.layout.label(text=self.bl_label)
        if bpy.app.version >= (4, 2, 0):
            self.layout.separator(type="LINE")
        else:
            self.layout.separator()
        row = self.layout.row()
        row.alignment = "RIGHT"
        TREEVIEW_OT_ExpandAllItems.draw_expand_all_buttons(
            row, self.layers_tree_manager.ul_tree_view_class.tree_manager_name
        )
        self.layers_tree_manager.ul_tree_view_class.draw_UL_TreeView(
            context, self.layout, rows=15
        )

class MSFS2024_OT_AddPreset(bpy.types.Operator):
    bl_idname = "msfs2024.multi_export_add_preset"
    bl_label = "Add preset"
    bl_options = {"INTERNAL"}

    group_id: bpy.props.StringProperty(default="")  # type: ignore

    def execute(self, context: bpy.types.Context) -> set[str]:

        from io_scene_gltf2_msfs_fss.ui.exp import preset_uilist
        preset_tree_manager = preset_uilist.get_preset_tree_manager()
        if not preset_tree_manager:
            return {"CANCELLED"}
        
        preset = exp_presets.add_preset(context.scene, self.group_id)

        preset_tree_manager.generate_tree_collection()
        preset_tree_manager.set_active_item_by_data(preset, update_selection=True)
        return {"FINISHED"}

class MSFS2024_OT_RemovePreset(bpy.types.Operator):
    bl_idname = "msfs2024.multi_export_remove_preset"
    bl_label = "Remove preset"
    bl_description = "Remove the preset from the preset list"
    bl_options = {"INTERNAL"}

    preset_id: bpy.props.StringProperty(default="")  # type: ignore

    def execute(self, context: bpy.types.Context):
        from io_scene_gltf2_msfs_fss.ui.exp import preset_uilist
        preset_tree_manager = preset_uilist.get_preset_tree_manager()
        if not preset_tree_manager:
            return {"CANCELLED"}

        to_remove = set([self.preset_id])
        # Also remove selected presets
        selected_items = preset_tree_manager.get_selected_items()
        for item in selected_items:
            data = item.get_data()
            if isinstance(data, MultiExporterPreset):
                to_remove.add(data.name)


        for id in to_remove:
            exp_presets.remove_preset(id, context.scene)

        # Refresh full data path after a preset deletion
        MultiExporterPreset.update_presets_full_data_path(context.scene)
        preset_tree_manager.generate_tree_collection()
        return {"FINISHED"}

class MSFS2024_OT_IsolatePresetObjects(bpy.types.Operator):
    bl_idname = "msfs2024.multi_isolate_preset_object"
    bl_label = "Isolate preset's object"
    bl_options = {"INTERNAL"}

    preset_id: bpy.props.StringProperty(default="")  # type: ignore

    @classmethod
    def poll(cls, context: bpy.types.Context):
        return context.mode == "OBJECT"

    def execute(self, context: bpy.types.Context):
        scene_presets = exp_presets.get_scene_exporter_presets(context.scene)
        preset = scene_presets.get(self.preset_id, None)
        if not preset:
            return {"CANCELLED"}
        exp_presets.isolate_preset_objects(preset, context.view_layer)
        return {"FINISHED"}

class MSFS2024_OT_RenamePreset(bpy.types.Operator):
    bl_idname = "msfs2024.multi_export_rename_preset"
    bl_label = "Rename"
    bl_description = "Rename Preset"
    bl_options = {"INTERNAL"}

    group_id: bpy.props.StringProperty(default="")  # type: ignore

    preset_id: bpy.props.StringProperty(default="")  # type: ignore

    new_name: bpy.props.StringProperty(name="New Name", default="")  # type: ignore

    group = None
    preset = None

    def execute(self, context: bpy.types.Context):
        return {"FINISHED"}
    
    def cancel(self, context: bpy.types.Context):
        """Launch when popup is closed"""
        from io_scene_gltf2_msfs_fss.ui.exp import preset_uilist
        preset_tree_manager = preset_uilist.get_preset_tree_manager()
        if not preset_tree_manager:
            return 
        # generate tree collection for alphabetical order
        preset_tree_manager.generate_tree_collection()


    def invoke(self, context: bpy.types.Context, event: bpy.types.Event):
        if self.group_id:
            scene_preset_groups = exp_presets.get_scene_exporter_preset_groups(context.scene)
            self.group = scene_preset_groups.get(self.group_id, None)
            if not self.group:
                return {"CANCELLED"}
        elif self.preset_id:
            scene_presets = exp_presets.get_scene_exporter_presets(context.scene)
            self.preset = scene_presets.get(self.preset_id, None)
            if not self.preset:
                return {"CANCELLED"}


        else:
            return {"CANCELLED"}

        return context.window_manager.invoke_popup(self)

    def draw(self, context: bpy.types.Context):
        layout = self.layout
        if self.group:
            layout.prop(self.group, "group_name", text="")
        elif self.preset:
            layout.prop(self.preset, "preset_name", text="")

class MSFS2024_OT_DuplicatePreset(bpy.types.Operator):
    bl_idname = "msfs2024.multi_export_duplicate_preset"
    bl_label = "Duplicate preset"
    bl_options = {"INTERNAL"}

    preset_id: bpy.props.StringProperty(default="")  # type: ignore

    def execute(self, context: bpy.types.Context) -> set[str]:
        from io_scene_gltf2_msfs_fss.ui.exp import preset_uilist
        preset_tree_manager = preset_uilist.get_preset_tree_manager()
        if not preset_tree_manager:
            return {"CANCELLED"}

        scene_presets = exp_presets.get_scene_exporter_presets(context.scene)
        active_preset: MultiExporterPreset = scene_presets[self.preset_id]
        if not active_preset:
            return {"CANCELLED"}

        preset: MultiExporterPreset = exp_presets.duplicate_preset(active_preset, context.scene)

        preset_tree_manager.generate_tree_collection()
        preset_tree_manager.set_active_item_by_data(preset, update_selection=True)
        return {"FINISHED"}

# endregion
