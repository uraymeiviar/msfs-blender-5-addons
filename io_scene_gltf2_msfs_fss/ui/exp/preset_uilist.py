from __future__ import annotations

import bpy

from typing import Any, Iterable

from io_scene_gltf2_msfs_fss.io.exp import multi_export_mode
from io_scene_gltf2_msfs_fss.io.exp import presets as exp_presets

from io_scene_gltf2_msfs_fss.io.exp.presets import (
    MultiExporterPreset,
    MultiExporterPresetGroup,
    MultiExporterPresetLayer,
)

from _addons_common.ui.tree_widget.item import TreeItem
from _addons_common.ui.tree_widget.manager import TreeManager
from _addons_common.ui.tree_widget.view import UL_TreeView

from io_scene_gltf2_msfs_fss.ui.exp import preset_ops, exporter_panel_ops


_preset_tree_manager: PresetTreeManager | None = None
def get_preset_tree_manager()-> PresetTreeManager | None:
    global _preset_tree_manager
    return _preset_tree_manager

# region UI Layer TreeView
class LayerTreeManager(TreeManager):
    # Inherited Functions
    preset : MultiExporterPreset | None = None
    def get_data_collection(self) -> Iterable:
        if not self.preset:
            return []
        return [self.preset.get_scene_root_layer()]
    
    @staticmethod
    def _get_collection_parents(
        collection: bpy.types.Collection, 
        parent_names: list | None = None
    ):
        """
        Returns a list of all parents for the given collection, ordered from
        the closest parent to the top-level parent.
        """
        if parent_names is None:
            parent_names = []
        for parent_collection in bpy.data.collections:
            if collection.name in parent_collection.children.keys():
                parent_names.append(parent_collection.name)
                LayerTreeManager._get_collection_parents(parent_collection, parent_names)
                break
        return parent_names
    
    def get_expanded_items(self) -> set[str]:
        """
        Get list of items name that should be expanded in ui tree
        """
        if not self.preset:
            return set()

        expanded_layers = {"Scene Collection"}

        for layer in self.preset.layers:
            if layer.enabled and layer.collection:
                expanded_layers.add(layer.name)
                # We need to add the parent of enabled layers to expand them to get to their children
                parent_names = LayerTreeManager._get_collection_parents(layer.collection)
                expanded_layers.update(set(parent_names))

        return expanded_layers

   
    def get_data_children(
        self, data: bpy.types.bpy_struct
    ) -> list[bpy.types.bpy_struct]:
        
        if not self.preset:
            return []
 
        if isinstance(data, MultiExporterPresetLayer):
            data: MultiExporterPresetLayer
            layer = data
            child_layers = []

            collection = layer.collection
            if layer.is_scene_collection:
                collection = bpy.context.scene.collection

            if not collection:
                return child_layers

            if not collection.children:
                return child_layers

            for col in collection.children:
                for _layer in self.preset.layers:
                    if not _layer.collection:
                        continue
                    if _layer.collection != col:
                        continue

                    child_layers.append(_layer)
                    break

            return child_layers

        return []


    def on_data_checked(self, checked: bool, data: Any):
        if isinstance(data, MultiExporterPresetLayer):
            layer: MultiExporterPresetLayer = data
            layer.enabled = checked


    def is_data_checked(self, data: Any)->bool:
        if isinstance(data, MultiExporterPresetLayer):
            layer: MultiExporterPresetLayer = data
            return layer.enabled
        return False

class MSFS2024_UL_Layers(bpy.types.UIList, UL_TreeView):

    use_filter_invert: bpy.props.BoolProperty(
        name="Filter Invert", 
        default=False,
        options=set()
    )  # type: ignore

    parents_of_filtered_items: bpy.props.BoolProperty(
        name="Show Parents Of Filtered Items",
        description=("Show parents of filtered items.\n"
                     "When disabled, child items can be shown individually") ,
        default=True,
        options=set()
    )  # type: ignore

    check_only: bpy.props.BoolProperty(
        name="Checked",
        description="Show checked items only",
        default=False,
        update=lambda self, ctx: self._sync_state("check")
    ) # type: ignore

    uncheck_only: bpy.props.BoolProperty(
        name="Unchecked",
        description="Show unchecked items only",
        default=False,
        update=lambda self, ctx: self._sync_state("uncheck")
    ) # type: ignore

    def _sync_state(self, source):
        # Prevent recursion
        if source == "check":
            self["uncheck_only"] = False
        elif source == "uncheck" :
            self["check_only"] = False

    # Hack using a boolproperty to reset filters
    # We can't create an operator that could reset filters since
    # we have no acess to UI_List instance.
    reset_filters: bpy.props.BoolProperty(
        name="Reset",
        description="Reset Filters",
        default=False,
        update=lambda self, ctx: self.on_reset_filters(ctx),
        options={"HIDDEN", "SKIP_SAVE"},
    )  # type: ignore

    def on_reset_filters(self, context):
        self.use_filter_invert = False
        self.parents_of_filtered_items = True
        self.check_only = False
        self.uncheck_only = False
        # Make button appears unchecked
        self["reset_filters"] = False

    # Inherited Methods
    @classmethod
    def custom_draw_item(
        cls,
        context: bpy.types.Context,
        index: int,
        item: TreeItem,
        layout: bpy.types.UILayout
    ):

        item: TreeItem
        data = item.get_data()
        if not data:
            return
        if isinstance(data, MultiExporterPresetLayer):
            cls.draw_preset_layer(data, item, index, layout)

    @staticmethod
    def draw_preset_layer(
        preset_layer: MultiExporterPresetLayer,
        item: TreeItem,
        index: int,
        row: bpy.types.UILayout,
    ):
        collection = preset_layer.collection
        if collection:
            row.label(text=preset_layer.collection.name)
        else:
            # Scene collection case
            row.label(text=preset_layer.name)

    def draw_filter(self, context: bpy.types.Context, layout: bpy.types.UILayout):
        row = layout.row(align=True)
        row.prop(self, "filter_name", text="", icon="VIEWZOOM")
        row.prop(
            self, "use_filter_invert", text="", icon="ARROW_LEFTRIGHT", icon_only=True
        )
        box = layout.box()
        row = box.row(align=True)
        row.label(text="Filters:")
        row.prop(
            self, "reset_filters", icon="RECOVER_LAST", toggle=True, icon_only=True
        )
        row = box.row(align=True)
        row.prop(self, "check_only", icon="CHECKBOX_HLT", toggle=True)
        row.prop(self, "uncheck_only", icon="CHECKBOX_DEHLT", toggle=True)
        col = box.column(align=True)
        if bpy.app.version < (4, 2, 0):
            col.separator()
        else:
            col.separator(type="LINE")
        col.prop(self, "parents_of_filtered_items")

    def filter_items(self, context: bpy.types.Context, data: Any|None, propname: str):
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

        msfs_layers_ui_tree :list[TreeItem]= getattr(data, propname)
        for i, item in enumerate(msfs_layers_ui_tree):
            if self.check_only and not item.checked:
                flt_flags[i] &= ~self.bitflag_filter_item
            elif self.uncheck_only and item.checked:
                flt_flags[i] &= ~self.bitflag_filter_item

        if self.parents_of_filtered_items:
            self.show_parents_of_filtered_items(ui_tree, flt_flags)
        return flt_flags, flt_neworder

# endregion

# region UI Presets TreeView
def _on_selection(tree_manager: TreeManager, context: bpy.types.Context):
    """
    This function is used by PRESET_TREE_MANAGERand is called 
    when list active index changed.

    It has two roles:
    - Update items selection in UIList.

    - Select objects in 3d scene when msfs_ui_tree_presets_sync_selection 
    is enabled :
        Select all layers objects of a preset.
        Select all layers objects of for each layer of a preset group.
    """

    if not context.scene.msfs_ui_tree_presets_sync_selection:
        return
    #Deselect 
    for obj in context.view_layer.objects:
        obj.select_set(False)

    selected_items = tree_manager.get_selected_items()

    for item in selected_items:
    
        
        item: TreeItem
        data = item.get_data()
        presets = []
        if isinstance(data, MultiExporterPresetGroup):
            presets = data.get_child_presets()
        elif isinstance(data, MultiExporterPreset):
            # item is a lod group
            presets = [data]
        else:
            continue

        for preset in presets:
            objects = preset.get_preset_objects()
            for obj in objects:
                try:
                    obj.select_set(True)
                    context.view_layer.objects.active = obj
                except RuntimeError:
                    # not in view_layer
                    pass
class PresetTreeManager(TreeManager):
    # region Manager settings
    ALPHABETICAL_ORDER = True
    MULTISELECTION_SUPPORT = True
    CHECKABLE_ITEMS = True
    # endregion

    @classmethod
    def get_data_collection(
        cls,
    ) -> list[MultiExporterPreset | MultiExporterPresetGroup]:
        data_list: list[MultiExporterPreset | MultiExporterPresetGroup] = []
        for data in exp_presets.get_scene_exporter_presets(bpy.context.scene):
            data: MultiExporterPreset
            if not data.group_id:
                data_list.append(data)
        for data in exp_presets.get_scene_exporter_preset_groups(bpy.context.scene):
            data_list.append(data)
        return data_list

    @classmethod
    def get_name_for_alpha_order(cls, data: bpy.types.bpy_struct) -> str:
        """
        Get data name for alphabetical ordering.
        It can differ from the item name used for filtering.
        """
        if isinstance(data, MultiExporterPresetGroup):
            return data.group_name
        elif isinstance(data, MultiExporterPreset):
            return data.preset_name

    @classmethod
    def get_data_children(
        cls,
        data: bpy.types.bpy_struct
    ) -> list[bpy.types.bpy_struct]:
        if isinstance(data, MultiExporterPresetGroup):
            return data.get_child_presets()

        return []

    @classmethod
    def set_ui_tree_item_name(cls, item: TreeItem, data: bpy.types.bpy_struct):
        """
        Set UITreeItem name according to data.
        Item name is used by filters functions.
        """
        if isinstance(data, MultiExporterPresetGroup):
            data: MultiExporterPresetGroup
            item.name = data.group_name
        elif isinstance(data, MultiExporterPreset):
            data: MultiExporterPreset
            # Add preset group name suffix when avaialable
            # Usefull for filtering groups
            parent_data: MultiExporterPresetGroup
            parent_data = item.get_parent_data()
            item.name = ""
            if parent_data:
                item.name = parent_data.group_name

            item.name += data.preset_name

    @classmethod
    def on_data_checked(cls, checked: bool, data: Any):
        if isinstance(data, MultiExporterPresetGroup):
            preset_group: MultiExporterPresetGroup = data
            preset_group.enabled = checked

        elif isinstance(data, MultiExporterPreset):
            preset: MultiExporterPreset = data
            preset.enabled = checked

    @classmethod
    def is_data_checked(cls, data: Any)->bool:
        if isinstance(data, MultiExporterPresetGroup):
            preset_group: MultiExporterPresetGroup = data
            return preset_group.enabled

        elif isinstance(data, MultiExporterPreset):
            preset: MultiExporterPreset = data
            return preset.enabled
        return False

class MSFS2024_UL_Presets(bpy.types.UIList, UL_TreeView):

    use_filter_invert: bpy.props.BoolProperty(
        name="Filter Invert", default=False, options=set()
    )  # type: ignore

    parents_of_filtered_items: bpy.props.BoolProperty(
        name="Show Parents Of Filtered Items",
        description=("Show parents of filtered items.\n"
                     "When disabled, child items can be shown individually") ,
        default=True,
        options=set()
    )  # type: ignore

    check_only: bpy.props.BoolProperty(
        name="Checked",
        description="Show checked items only",
        default=False,
        update=lambda self, ctx: self._sync_state("check")
    ) # type: ignore

    uncheck_only: bpy.props.BoolProperty(
        name="Unchecked",
        description="Show unchecked items only",
        default=False,
        update=lambda self, ctx: self._sync_state("uncheck")
    ) # type: ignore

    def _sync_state(self, source):
        # Prevent recursion
        if source == "check":
            self["uncheck_only"] = False
        elif source == "uncheck" :
            self["check_only"] = False


    # Hack using a boolproperty to reset filters
    # We can't create an operator that could reset filters since
    # we have no acess to UI_List instance.
    reset_filters: bpy.props.BoolProperty(
        name="Reset",
        description="Reset Filters",
        default=False,
        update=lambda self, ctx: self.on_reset_filters(ctx),
        options={"HIDDEN", "SKIP_SAVE"},
    )  # type: ignore

    def on_reset_filters(self, context):
        self.use_filter_invert = False
        self.parents_of_filtered_items = True
        self.check_only = False
        self.uncheck_only = False
        # Make button appears unchecked
        self["reset_filters"] = False

    @classmethod
    def custom_draw_item(cls,
        context: bpy.types.Context,
        index: int,
        item: TreeItem,
        layout: bpy.types.UILayout
    ):
        item: TreeItem
        data = item.get_data()
        if not data:
            return
        row = layout.row(align=True)
        if isinstance(data, MultiExporterPresetGroup):
            preset_group: MultiExporterPresetGroup = data
            cls.draw_preset_group(preset_group, item, index, row)

        elif isinstance(data, MultiExporterPreset):
            preset: MultiExporterPreset = data
            cls.draw_preset(preset, item, index, row)
        else:
            row.label(text="Not Implemented")

    @classmethod
    def draw_context_menu(cls, context: bpy.types.Context, layout: bpy.types.UILayout):
        super().draw_context_menu(context, layout)
        layout.separator()
        export_selected_ope = layout.operator(
            exporter_panel_ops.MSFS2024_OT_ExportSelectedItems.bl_idname,
            text="Export Selected",
            icon="EXPORT",
        )
        export_selected_ope.export_mode = multi_export_mode.ExportMode.PRESETS.identifier
    @staticmethod
    def draw_preset( preset: MultiExporterPreset, item: TreeItem, index:int , row: bpy.types.UILayout):
        item: TreeItem

        row.label(text=preset.preset_name)
        ope = row.operator(
            preset_ops.MSFS2024_OT_RenamePreset.bl_idname,
            text="",
            icon="GREASEPENCIL",
            emboss=False
        )
        ope.preset_id = preset.name
        ope.group_id = ""
        if bpy.app.version > (4, 0, 0):
            row.prop(preset, "folder_path", text="", placeholder="Export Folder")
        else:
            row.prop(preset, "folder_path", text="")
        row.operator(preset_ops.MSFS2024_OT_IsolatePresetObjects.bl_idname, text="", icon="HIDE_OFF").preset_id = preset.name
        row.operator(preset_ops.MSFS2024_OT_EditLayers.bl_idname, text="", icon="COLLECTION_NEW").preset_id = preset.name
        row.operator(preset_ops.MSFS2024_OT_DuplicatePreset.bl_idname, text="", icon="DUPLICATE").preset_id = preset.name
        row.operator(preset_ops.MSFS2024_OT_RemovePreset.bl_idname, text="", icon="REMOVE").preset_id = preset.name

    @staticmethod
    def draw_preset_group(
        preset_group: MultiExporterPresetGroup,
        item: TreeItem,
        index: int,
        row: bpy.types.UILayout,
    ):

        row.label(text=preset_group.group_name)
        ope = row.operator(
            preset_ops.MSFS2024_OT_RenamePreset.bl_idname,
            text="",
            icon="GREASEPENCIL",
            emboss=False,
        )
        ope.group_id = preset_group.name
        ope.preset_id = ""

        if bpy.app.version > (4, 0, 0):
            row.prop(preset_group, "folder_path", text="", placeholder="Export Folder")
        else:
            row.prop(preset_group, "folder_path", text="")

        row.operator(preset_ops.MSFS2024_OT_IsolateGroupPresetObjects.bl_idname, text="", icon="HIDE_OFF").group_id = preset_group.name
        row.operator(preset_ops.MSFS2024_OT_AddPreset.bl_idname, text="", icon="ADD").group_id = preset_group.name
        row.operator(preset_ops.MSFS2024_OT_DuplicatePresetGroup.bl_idname, text="", icon="DUPLICATE").group_id = preset_group.name
        row.operator(preset_ops.MSFS2024_OT_RemovePresetGroup.bl_idname, text="", icon="REMOVE").group_id = preset_group.name

    def draw_filter(self, context: bpy.types.Context, layout: bpy.types.UILayout):

        row = layout.row(align=True)
        row.prop(self, "filter_name", text="", icon="VIEWZOOM")
        row.prop(self, "use_filter_invert", text="", icon="ARROW_LEFTRIGHT", icon_only=True)

        box = layout.box()
        row = box.row()
        row.label(text="Filters:")
        row.prop(
            self, "reset_filters", icon="RECOVER_LAST", toggle=True, icon_only=True
        )
        row = box.row(align=True)
        row.prop(self, "check_only", icon="CHECKBOX_HLT", toggle=True)
        row.prop(self, "uncheck_only", icon="CHECKBOX_DEHLT", toggle=True)

        col = box.column(align=True)
        if bpy.app.version < (4, 2, 0):
            col.separator()
        else:
            col.separator(type="LINE")

        col = box.column(align=False)
        col.prop(self, "parents_of_filtered_items")

    def filter_items(self, context: bpy.types.Context, data: Any|None, propname: str):
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
        if not flt_flags:
            flt_flags = [self.bitflag_filter_item] * len(ui_tree)

        data_tree = [item.get_data() for item in ui_tree]

        # Filtering by group name and preset name
        # Directly use name from data to support live renaming of preset and group,
        # without having to regenerate ui items.
        if self.filter_name:
            for i, _data in enumerate(data_tree):
                preset_name = getattr(_data, "preset_name", None)
                group_name = getattr(_data, "group_name", None)

                name = preset_name if not group_name else group_name

                if name is not None:
                    name = name.lower()
                    if self.use_filter_invert:
                        if self.filter_name.lower() in name:
                            flt_flags[i] &= ~self.bitflag_filter_item
                    else:
                        if not self.filter_name.lower() in name:
                            flt_flags[i] &= ~self.bitflag_filter_item

        msfs_presets_ui_tree: list[TreeItem] = getattr(data, propname)
        for i, item in enumerate(msfs_presets_ui_tree):
            if self.check_only and not item.checked:
                flt_flags[i] &= ~self.bitflag_filter_item
            elif self.uncheck_only and item.checked:
                flt_flags[i] &= ~self.bitflag_filter_item

        if self.parents_of_filtered_items:
            self.show_parents_of_filtered_items(ui_tree, flt_flags)

        self.save_flags_in_tree_manager(flt_flags)

        return flt_flags, flt_neworder

def register():

    global _preset_tree_manager
    multi_edit_properties = {
        MultiExporterPresetGroup: ["group_name", "folder_path", "settings_preset"],
        MultiExporterPreset: ["preset_name", "folder_path", "settings_preset"]
    }
    _preset_tree_manager = PresetTreeManager(
        ul_tree_view_class=MSFS2024_UL_Presets,
        on_selection_function=_on_selection,
        alphabetical_order=True,
        multiselection_support=True,
        checkable_items=True,
        multi_edit_properties=multi_edit_properties
    )

    bpy.types.Scene.msfs_ui_tree_presets_sync_selection = bpy.props.BoolProperty( # type: ignore
        default=False,
        description="Select corresponding scene objects when an item is selected in exporter hierarchy",
    )

def unregister():
    try:
        global _preset_tree_manager
        _preset_tree_manager.unregister()  # type: ignore
        del bpy.types.Scene.msfs_ui_tree_presets_sync_selection  # type: ignore
         
    except:
        pass
