import bpy
import webbrowser

from io_scene_gltf2_msfs_fss.io.exp import multi_export, multi_export_mode, lod_groups

from io_scene_gltf2_msfs_fss.ui.exp import lod_groups_uilist, preset_uilist

class MSFS2024_OT_ChangeTab(bpy.types.Operator):
    bl_idname = "msfs2024.multi_export_change_tab"
    bl_label = "Change tab"
    bl_options = {"INTERNAL"}

    current_tab: bpy.props.StringProperty() # type: ignore

    def execute(self, context: bpy.types.Context):
        context.scene.msfs_exporter_current_tab = self.current_tab
        return {"FINISHED"}

class MSFS2024_OT_OpenDocumentation(bpy.types.Operator):
    bl_idname = "msfs204.open_documentation"
    bl_label = "Open Documentation"
    bl_description = "Open the MSFS 2024 documentation in your browser"

    def execute(self, context):
        from io_scene_gltf2_msfs_fss import bl_info
        doc_url = bl_info.get("doc_url", None)
        if doc_url is None:
            self.report({"ERROR"}, "Doc URL not found")
            return {"CANCELLED"}
        webbrowser.open(doc_url)
        return {'FINISHED'}

class MSFS2024_OT_ExportSelectedItems(bpy.types.Operator):
    bl_idname = "msfs2024.export_selected_items"
    bl_label = "Export selected items"
    bl_description = (
        "Export only selected items.\n"
        "Completely ignore items checked state.\n"
        "You can selected multiple items using shift and alt hotkeys"
    )
    bl_options = {"INTERNAL"}

    export_mode: bpy.props.EnumProperty(
        items=multi_export_mode.EXPORT_MODE_ENUM_ITEMS
    )  # type: ignore

    def execute(self, context: bpy.types.Context):

        tree_manager = None
        if self.export_mode == multi_export_mode.ExportMode.OBJECTS.identifier or self.export_mode == multi_export_mode.ExportMode.PRESETS.identifier:
            tree_manager = lod_groups_uilist.get_lod_group_tree_manager()
        if self.export_mode == multi_export_mode.ExportMode.PRESETS.identifier:
            tree_manager = preset_uilist.get_preset_tree_manager()
        if not tree_manager:
            return
        # Save checked items state
        checked_items = tree_manager.get_checked_items()
        tree_manager.check_all(checked=False, visible_only=False)
        # Checked selected items
        selected_items = tree_manager.get_selected_items()
        for item in selected_items:
            item.checked = True
        try:
            multi_export.launch_export(context, self.export_mode)
        except:
            pass
        # Restore checked items
        tree_manager.check_all(checked=False, visible_only=False)
        for item in checked_items:
            item.checked = True
        return {"FINISHED"}

class MSFS2024_OT_SetHierarchyMode(bpy.types.Operator):
    """Set Hierarchy Mode for user. Shows a popup that
    warns user about the reset of export settings."""

    bl_idname = "msfs2024.set_hierarchy_mode"
    bl_label = "Objects export settings will be reset. Switch?"
    bl_description = "Switch between hierarchy modes (Objects or Collections)"
    bl_options = {"INTERNAL"}

    export_mode: bpy.props.EnumProperty(
        name="Mode",
        default=multi_export_mode.ExportMode.OBJECTS.identifier,
        description="Group LODs by objects or collections "
        "(WARNING: Switching hierarchy mode will"
        "reset objects export settings)",
        items=multi_export_mode.EXPORT_MODE_ENUM_ITEMS
    )  # type: ignore

    trigger_reload_lod_group: bpy.props.BoolProperty(default=False) # type: ignore

    def execute(self, context: bpy.types.Context):

        if context.scene.msfs_export_mode == self.export_mode:
            return {"FINISHED"}
        
        context.scene.msfs_export_mode = self.export_mode
    
        if self.trigger_reload_lod_group:  
            lod_groups.reload_lod_groups(context.scene, reset=True)
            from io_scene_gltf2_msfs_fss.ui.exp import lod_groups_uilist

            tree_manager = lod_groups_uilist.get_lod_group_tree_manager()
            if not tree_manager:
                return {"FINISHED"}
            # Refresh UiList
            tree_manager.generate_tree_collection()

        return {"FINISHED"}

    def invoke(self, context, event):
        current_export_mode = context.scene.msfs_export_mode

        if current_export_mode == self.export_mode:
            return {"CANCELLED"}
        
        # Show a warning when switching between objects and collections mode
        self.trigger_reload_lod_group = False

        if (self.export_mode == multi_export_mode.ExportMode.OBJECTS.identifier
            and current_export_mode == multi_export_mode.ExportMode.COLLECTIONS.identifier
        ) or (self.export_mode == multi_export_mode.ExportMode.COLLECTIONS.identifier
            and current_export_mode == multi_export_mode.ExportMode.OBJECTS.identifier
        ):  
            self.trigger_reload_lod_group = True

        if self.trigger_reload_lod_group:
            if bpy.app.version > (4,0,0):
                return context.window_manager.invoke_confirm(
                    self,
                    event,
                    title="",
                    message=("WARNING: Switching between Objects and Collection modes\n" 
                             "will reset LOD Groups export settings."
                    ),
                    icon="WARNING"
                )
            else:
                return context.window_manager.invoke_confirm(
                    self,
                    event
                )

        self.execute(context)

        return {"FINISHED"}
