from __future__ import annotations

from typing import TYPE_CHECKING
import bpy

from lod_tools_msfs_2024 import (
    lod_camera,
    lod_viewer,
    lod_viewer_collections,
    lod_group_infos,
    prefs,
    addon_dependencies,
    data_properties,
)
from _addons_common.ui.tree_widget.manager import TreeManager
from _addons_common.ui.tree_widget.view import UL_TreeView

from io_scene_gltf2_msfs_fss.io.exp import multi_export_mode
from io_scene_gltf2_msfs_fss.io.exp import presets as exp_presets
from io_scene_gltf2_msfs_fss.io.exp import lod_groups as exp_lod_groups

if TYPE_CHECKING:
    from _addons_common.ui.tree_widget.item import TreeItem

class LODViewerTreeManager(TreeManager):
    # Only used by operator below
    @classmethod
    def get_name_for_alpha_order(cls, data: bpy.types.bpy_struct) -> str:
        """
        Get name for alphabetical ordering.
        It can differ from the item name used for filtering.
        """
        if isinstance(data, exp_lod_groups.MultiExporterLODGroup):
            return data.name
        elif isinstance(data, exp_presets.MultiExporterPresetGroup):
            return data.group_name

    @classmethod
    def set_ui_tree_item_name(cls, item: TreeItem, data: bpy.types.bpy_struct):
        """
        Set UITreeItem name according to data.
        Item name is used by filters functions.
        """
        item.name = cls.get_name_for_alpha_order(data)

class MSFS2024_UL_LODViewers(bpy.types.UIList, UL_TreeView):
    use_filter_invert: bpy.props.BoolProperty(
        name="Filter Invert", 
        default=False,
        options=set()
    )  # type: ignore

    # Inherited Methods
    @classmethod
    def custom_draw_item(cls, context, index, item, layout):
        item: TreeItem
        data = item.get_data()
        if not data:
            return
        if isinstance(data, exp_presets.MultiExporterPresetGroup):
            cls.draw_group_preset(data, item, index, layout)
        elif isinstance(data, exp_lod_groups.MultiExporterLODGroup):
            cls.draw_lod_group(data, item, index, layout)

    @staticmethod
    def draw_lod_group(data: exp_lod_groups.MultiExporterLODGroup, item, index, row:bpy.types.UILayout):
        row.label(text=data.name)

    @staticmethod
    def draw_group_preset(data: exp_presets.MultiExporterPresetGroup, item, index, row:bpy.types.UILayout):
        row.label(text=data.group_name)

    def draw_filter(self, context, layout):
        row = layout.row(align=True)
        row.prop(self, "filter_name", text="", icon="VIEWZOOM")
        row.prop(
            self, "use_filter_invert", text="", icon="ARROW_LEFTRIGHT", icon_only=True
        )
        col = layout.column(align=False)

    def filter_items(self, context, data, propname):
        """
        This function gets the collection property (as the usual tuple (data, propname)), and must return two lists:
        * The first one is for filtering, it must contain 32bit integers were self.bitflag_filter_item marks the
          matching item as filtered (i.e. to be shown). The upper 16 bits (including self.bitflag_filter_item) are
          reserved for internal use, the lower 16 bits are free for custom use.
        * The second one is for reordering, it must return a list containing the new indices of the items (which
          gives us a mapping org_idx -> new_idx).

        Please note that the default UI_UL_list defines helper functions for common tasks (see its doc for more info).
        If you do not make filtering and/or ordering, return empty list(s) (this will be more efficient than
        returning full lists doing nothing!).

        """
        flt_flags, flt_neworder = super().filter_items(context, data, propname)

        ui_tree = getattr(data, propname)
        helper_funcs = bpy.types.UI_UL_list

        # Filtering by name
        if self.filter_name:
            flt_flags = helper_funcs.filter_items_by_name(
                self.filter_name,
                self.bitflag_filter_item,
                ui_tree,
                "name",
                reverse=self.use_filter_invert
            )
        if not flt_flags:
            flt_flags = [self.bitflag_filter_item] * len(ui_tree)

        return flt_flags, flt_neworder
target_mode_enum = (
                ("checked", "Checked", "Preview checked items"),
                ("all", "All", "Preview all"),
            )
class MSFS2024_OT_GenerateLODViewers(bpy.types.Operator):
    bl_idname = "msfs2024.generate_lod_viewers"
    bl_label = "Generate LOD Viewers"
    bl_description = (
        "Launch or update the LOD Preview.\n"
        "Hold Shift to skip the options popup and use the last settings."
    )
    use_last_gen_settings: bool = False

    target_mode: bpy.props.EnumProperty(
            name="Target",
            items=target_mode_enum,
            default="all",
            description="Select Objects for LOD Preview"
        )  # type: ignore

    lod_viewer_tree_manager: LODViewerTreeManager | None = None

    def __del__(self):
        try:
            self.lod_viewer_tree_manager.unregister()
        except:
            pass

    @classmethod
    def poll(cls, context):
        return (context.area.type == "VIEW_3D" and 
            context.region.type == "WINDOW")

    def get_msfs_lod_groups(self, context, export_mode: multi_export_mode.ExportMode) -> list:

        if (
            export_mode == multi_export_mode.ExportMode.OBJECTS
            or export_mode == multi_export_mode.ExportMode.COLLECTIONS
        ):
            msfs_lod_groups = exp_lod_groups.get_scene_lod_groups(context.scene)
            # Ignore lod groups that in lod viewer collection
            msfs_lod_groups = lod_group_infos.filter_msfs_lod_groups(msfs_lod_groups, export_mode)
        else:
            msfs_lod_groups = exp_presets.get_scene_exporter_preset_groups(
                context.scene
            )
            grouped_preset_dict = lod_group_infos.construct_grouped_preset_dict(context.scene)
            if not grouped_preset_dict:
                return []

            msfs_lod_groups = lod_group_infos.filter_msfs_preset_groups(msfs_lod_groups, grouped_preset_dict)
        return msfs_lod_groups

    def restore_checked_items(self, context, export_mode: multi_export_mode.ExportMode):
        last_gen = get_last_lod_viewer_gen(context.scene)
        if not last_gen or last_gen.target_mode == "all":
            return
        ui_tree_collection = self.lod_viewer_tree_manager.get_ui_tree_collection()
        last_gen_ids = last_gen.get_lod_group_ids()

        if (
            export_mode == multi_export_mode.ExportMode.OBJECTS
            or export_mode == multi_export_mode.ExportMode.COLLECTIONS
        ):
            for item in ui_tree_collection:
                if item.name in last_gen_ids:
                    item.checked = True
        else:
            for item in ui_tree_collection:
                data = item.get_data()
                if not isinstance(data, exp_presets.MultiExporterPresetGroup):
                    continue

                if data.group_name in last_gen_ids:
                    item.checked = True

    def save_gen_settings(self, context):
        export_mode = multi_export_mode.get_active_export_mode(context.scene)

        last_gen = get_last_lod_viewer_gen(context.scene)
        if not last_gen :
            return
        last_gen.target_mode = self.target_mode
        if self.target_mode == "all" or not self.lod_viewer_tree_manager:
            last_gen.msfs_lod_groups.clear()
            return
        last_gen.msfs_lod_groups.clear()
        ui_tree_collection = self.lod_viewer_tree_manager.get_ui_tree_collection()
        if (
                export_mode == multi_export_mode.ExportMode.OBJECTS
                or export_mode == multi_export_mode.ExportMode.COLLECTIONS
            ):
            for item in ui_tree_collection:
                if item.checked:
                    entry = last_gen.msfs_lod_groups.add()
                    entry.id = item.name
        else:
            for item in ui_tree_collection:
                data = item.get_data()
                if not isinstance(data, exp_presets.MultiExporterPresetGroup):
                    continue
                if item.checked:
                    entry = last_gen.msfs_lod_groups.add()
                    entry.id = data.group_name

    def invoke(self, context, event):
        if not (addon_dependencies.are_dependencies_loaded(show_warning=True)):
            return {"CANCELLED"}

        if event.shift:
            # Execute with current prefs
            self.use_last_gen_settings = True
            return self.execute(context)
        else:
            export_mode = multi_export_mode.get_active_export_mode(context.scene)
            msfs_lod_groups = self.get_msfs_lod_groups(context, export_mode)
            if not msfs_lod_groups:
                self.report({"INFO"}, "No LODs found in exporter!")
                return {"CANCELLED"}

            # Make sure TreeManager instance is deleted
            # TreeManager is deleted on __del__ but it can be skipped if execute() fails
            unique_name = LODViewerTreeManager.get_unique_name()
            instance = TreeManager.get_tree_manager_instance(unique_name)
            if instance:
                try:
                    instance.unregister()
                except:
                    pass

            self.lod_viewer_tree_manager = LODViewerTreeManager(
                ul_tree_view_class=MSFS2024_UL_LODViewers,
                data_collection_getter=lambda: msfs_lod_groups,
                alphabetical_order=True,
                multiselection_support=True,
                checkable_items=True,
            )
            self.lod_viewer_tree_manager.generate_ui_tree_collection()
            self.restore_checked_items(context, export_mode)
            return context.window_manager.invoke_props_dialog(self, width=300)

    def draw(self, context):
        addon_prefs = prefs.get_addon_prefs()
        lod_viewer_settings = addon_prefs.lod_viewer_settings
        self.layout.prop(lod_viewer_settings, "align_lod_viewer_to_source")
        self.layout.prop(lod_viewer_settings, "lod_viewer_offset")
        self.layout.prop(self, "target_mode")
        if self.target_mode == "checked":
            MSFS2024_UL_LODViewers.draw_UL_TreeView(context, self.layout, rows=15)

    def get_checked_data(self, context) -> list:
        """Get lod groups checked by user.
        """
        data = []
        if not self.lod_viewer_tree_manager:
            return data

        checked_items = self.lod_viewer_tree_manager.get_checked_items()
        for item in checked_items:
            item_data = item.get_data()
            if item_data:
                data.append(item_data)
        if not data:
            self.report({"INFO"}, "No Valid objects found in exporter!")

        return data

    def get_last_gen_lod_groups(self, context) -> list | None:
        """Get lod groups generated at previous operator execution.
        """
        last_gen = get_last_lod_viewer_gen(context.scene)
        if not last_gen or last_gen.target_mode == "all":
            return None
        export_mode = multi_export_mode.get_active_export_mode(context.scene)
        _msfs_lod_groups = self.get_msfs_lod_groups(context, export_mode)
        last_gen_ids = last_gen.get_lod_group_ids()
        if not last_gen_ids:
            return None

        filtered = []
        if (
            export_mode == multi_export_mode.ExportMode.OBJECTS
            or export_mode == multi_export_mode.ExportMode.COLLECTIONS
        ):
            for lod_group in _msfs_lod_groups:
                if lod_group.name in last_gen_ids:
                    filtered.append(lod_group)
        else:
            for preset_group in _msfs_lod_groups:
                if preset_group.group_name in last_gen_ids:
                    filtered.append(preset_group)

        if not filtered:
            return None
        
        return filtered

    def execute(self, context):
        if not (addon_dependencies.are_dependencies_loaded(show_warning=True)):
            return {"CANCELLED"}
        set_cursor_wait()

        if self.target_mode == "all":
            lod_viewer.generate_lod_viewers(context.scene)
        elif not self.use_last_gen_settings and self.lod_viewer_tree_manager:
            data = self.get_checked_data(context)
            if not data:
                self.report({"INFO"}, "Nothing to process!")
                try:
                    self.lod_viewer_tree_manager.unregister()
                except:
                    pass
                return {"CANCELLED"}
            lod_viewer.generate_lod_viewers(context.scene, data)
        else:
            # User pressed shift to regenerate with latest settings
            msfs_lod_groups = self.get_last_gen_lod_groups(context)
            lod_viewer.generate_lod_viewers(context.scene, msfs_lod_groups)

        if not self.use_last_gen_settings:
            self.save_gen_settings(context)

        set_cursor_default()
        return {"FINISHED"}

class MSFS2024_OT_ClearLODPreview(bpy.types.Operator):
    bl_idname = "msfs2024.clear_lod_preview"
    bl_label = "Clear LOD Preview"
    bl_description = "Stop LOD Preview and Remove all LOD Viewer objects"

    target_mode: bpy.props.EnumProperty(
        name="Target",
        items=(
            ("active", "Active Scene", "Clear LOD Preview in active scene"),
            ("all", "All Scenes", "Clear LOD Preview in all scenes"),
        ),
        default="active",
        description="Select affected scenes"
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        return (context.area.type == "VIEW_3D" and 
            context.region.type == "WINDOW")

    def invoke(self, context, event):
        wm = context.window_manager
         # Open dialog if multiple scenes
        if len(bpy.data.scenes) > 1:
            return wm.invoke_props_dialog(self)
        
        self.target_mode = "active"
        return self.execute(context)

    
    def execute(self, context):
        set_cursor_wait()


        if self.target_mode == "active":
            lod_viewer.clean_scene_lod_viewer(context.scene)
        elif self.target_mode == "all":
            for scene in bpy.data.scenes:
                lod_viewer.clean_scene_lod_viewer(scene)
        set_cursor_default()
        return {"FINISHED"}

class MSFS2024_OT_ToggleLODCamera(bpy.types.Operator):
    bl_idname = "msfs2024.toggle_lod_camera"
    bl_label = "Toggle LOD Camera"
    bl_description = ("Enter or Exit LOD camera View.\n"
                      "LOD Screen Sizes are not updated when LOD Camera \n"
                      "is not used")

    @classmethod
    def poll(cls, context):
        return (context.area.type == "VIEW_3D" and 
            context.region.type == "WINDOW")

    def execute(self, context):
        lod_camera.toggle_lod_camera(context)
        return {"FINISHED"}


class MSFS2024_OT_SendSetupToExporter(bpy.types.Operator):
    bl_idname = "msfs2024.send_setup_to_exporter"
    bl_label = "Send To Exporter"
    bl_description = "Send selected LOD Viewer setup to exporter"

    target_mode: bpy.props.EnumProperty(
        name="Target",
        items=(
            ("active", "Active", "Only send the active LOD Setup"),
            ("selected", "Selected", "Send selected LOD Setups individually"),
            ("all", "All", "Send all LOD Setups individually"),
        ),
        default="active",
        description="Select which LOD Viewer Setups should be sent"
    )  # type: ignore

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "target_mode")

    def invoke(self, context, event):
        wm = context.window_manager
    
        return wm.invoke_props_dialog(self)
       

    @classmethod
    def poll(cls, context):
        valid_area = (context.area.type == "VIEW_3D" and 
            context.region.type == "WINDOW")
        if not valid_area:
            return False
        obj = context.object
        if not obj:
            return  False
        source = data_properties.get_lod_viewer_source(obj)
        return source is not None

    def execute(self, context):
        lod_viewers = []
        if self.target_mode == "active":
            lod_viewers = [context.object]
        elif self.target_mode == "selected":
            lod_viewers = context.selected_objects
        elif self.target_mode == "all":
            lod_viewer_col = lod_viewer_collections.get_scene_lod_viewer_collection(context.scene)
            if lod_viewer_col:
                lod_viewers = lod_viewer_col.objects

        for obj in lod_viewers:
            result = lod_viewer.send_lod_setup_to_exporter(obj)
            if result is data_properties.OutdatedLodGroup:
                self.report(
                    {"ERROR"},
                    "LOD group was not found in the exporter.\n"
                    "The exporter LOD groups may have changed.\n"
                    "Reload the LOD Preview to fix the issue.",
                )
                return {"CANCELLED"}
            if not result:
                # Not a ExporterLODGroup
                continue

        return {"FINISHED"}

class MSFS2024_OT_ResetRenderSettings(bpy.types.Operator):
    bl_idname = "msfs2024.reset_lod_render_settings"
    bl_label = "Reset Render Settings"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        addon_prefs = prefs.get_addon_prefs()
        addon_prefs.property_unset("render_settings")
        addon_prefs.render_settings.update_all(context)
        
        return {"FINISHED"}

class MSFS2024_OT_ResetDebugSettings(bpy.types.Operator):
    bl_idname = "msfs2024.reset_debug_settings"
    bl_label = "Reset Render Settings"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        addon_prefs = prefs.get_addon_prefs()
        addon_prefs.property_unset("debug_settings")
        addon_prefs.debug_settings.update_all(context)
        
        return {"FINISHED"}

class MSFS2024_OT_SetRenderSettings(bpy.types.Operator):
    bl_idname = "msfs2024.set_lod_render_settings"
    bl_label = "Set LOD RenderSettings"
    bl_description = (
        "Set Render Setting for LOD viewer"
    )
    bl_options = {"INTERNAL"}

    render_settings = None
    def execute(self, context):
        return {"FINISHED"}

    def invoke(self, context, event):
        addon_prefs = prefs.get_addon_prefs()
        if not addon_prefs:
            return {"CANCELLED"}
        self.render_settings = addon_prefs.render_settings
        wm = context.window_manager
        return wm.invoke_popup(self)

    def draw(self, context):
        # Title
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation

        row = self.layout.row()
        row.alignment = "RIGHT"
        row.operator(
            MSFS2024_OT_ResetRenderSettings.bl_idname,
            text="Reset",
            icon="RECOVER_LAST",
        )
        prefs.MSFS2024_LODTools_AddonPreferences.draw_render_preset(self.render_settings, layout)
        prefs.MSFS2024_LODTools_AddonPreferences.draw_render_settings(self.render_settings, layout)


def set_cursor(cursor_type):
    """Set the Blender cursor to a specified type."""
    bpy.context.window.cursor_set(cursor_type)

def set_cursor_wait():
    """Set the Blender cursor to the "WAIT" type (hourglass/spinner)."""
    set_cursor("WAIT")

def set_cursor_default():
    """Reset the Blender cursor to the "DEFAULT" type (normal arrow)."""
    set_cursor("DEFAULT")


class lod_group(bpy.types.PropertyGroup):
    id: bpy.props.StringProperty(name="id", default="")  # type: ignore


class LastLODViewersGeneration(bpy.types.PropertyGroup):

    target_mode: bpy.props.EnumProperty(
        name="Target",
        items=target_mode_enum,
        default="all",
        description="Select Objects for LOD Preview",
    )  # type: ignore
    msfs_lod_groups: bpy.props.CollectionProperty(
        name="LOD Groups",
        type=lod_group,
        description="LOD Groups chosen in latest generation",
    )  # type: ignore

    def get_lod_group_ids(self)->set[str]:
        ids = set()
        for lod_group in self.msfs_lod_groups:
            ids.add(lod_group.id)
        return ids

last_lod_viewer_gen_prop = "msfs_last_lod_viewer_gen_prop"

def get_last_lod_viewer_gen(scene: bpy.types.Scene) -> LastLODViewersGeneration | None:
    return getattr(scene, last_lod_viewer_gen_prop, None)

def register():
    setattr(bpy.types.Scene, last_lod_viewer_gen_prop, bpy.props.PointerProperty(type=LastLODViewersGeneration, name="Last LOD Viewers Generation"))

def unregister():
    try:
        delattr(bpy.types.Scene, last_lod_viewer_gen_prop)
    except:
        pass
