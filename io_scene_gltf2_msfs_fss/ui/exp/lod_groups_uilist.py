from __future__ import annotations


import bpy

from _addons_common.ui.tree_widget.item import TreeItem
from _addons_common.ui.tree_widget.manager import TreeManager
from _addons_common.ui.tree_widget.view import UL_TreeView

from io_scene_gltf2_msfs_fss.io.exp  import multi_export_mode

from io_scene_gltf2_msfs_fss.io.exp  import lod_groups as exp_lod_groups


from io_scene_gltf2_msfs_fss.io.exp.lod_groups import MultiExporterLOD, MultiExporterLODGroup, LOD_NAME_PATTERN

from io_scene_gltf2_msfs_fss.ui.exp import exporter_panel_ops


_lod_group_tree_manager: LODGroupTreeManager | None = None

def get_lod_group_tree_manager()-> LODGroupTreeManager | None:
    global _lod_group_tree_manager
    return _lod_group_tree_manager

def _on_selection(tree_manager: TreeManager, context: bpy.types.Context):
    """
    This function is used by LodGroupTreeManager and is called 
    when list active index changed.

    It has two roles:
    - Update items selection in UIList.

    - Select objects in 3d scene when msfs_ui_tree_objects_sync_selection 
    is enabled :
        Select all lods of lodgroup when selected item is a lod group.
        Select lod when selected item is a lod.
    """
    if not context.scene.msfs_ui_tree_objects_sync_selection:
        return

    # Deselect
    for obj in context.view_layer.objects:
        obj.select_set(False)
    selected_items = tree_manager.get_selected_items()

    for item in selected_items:

        item: TreeItem
        data = item.get_data()
        objects = []
        root_obj = None
        active_export_mode = multi_export_mode.get_active_export_mode(context.scene)
        if isinstance(data, MultiExporterLODGroup):
            objects = data.get_lod_group_objects(export_mode=active_export_mode)
            if not objects:
                continue
            if len(data.lods)>0 :
                if active_export_mode == multi_export_mode.ExportMode.OBJECTS:
                    root_obj = data.lods[0].objectLOD
                
            
        elif isinstance(data, MultiExporterLOD):
            objects = data.get_lod_objects(export_mode=multi_export_mode.get_active_export_mode(context.scene))
            if not objects:
                continue
            if active_export_mode == multi_export_mode.ExportMode.OBJECTS:
                root_obj = data.objectLOD

        else:
            continue
        

        for obj in objects:
            try:
                obj.select_set(True)
                
            except RuntimeError:
                # Not in view_layer
                pass
        if not root_obj:  
            for obj in objects:
                if not obj.parent:
                    root_obj =  obj
                    break

        try:
            context.view_layer.objects.active = root_obj
        except RuntimeError:
            # Not in view_layer
            pass

class LODGroupTreeManager(TreeManager):

    # endregion
    def get_data_children(
        self, data: bpy.types.bpy_struct
    ) -> list[bpy.types.bpy_struct]:
        if isinstance(data, MultiExporterLODGroup):
            return data.lods
        else:
            return []

    def get_clean_lod_name(self, lod_name:str, index:int)->str:
        new_name = lod_name
        new_suffix = f"_LOD{index}"
        if LOD_NAME_PATTERN.search(new_name):
            new_name = LOD_NAME_PATTERN.sub(new_suffix, new_name)
        return new_name

    def set_tree_item_name(self, item: TreeItem, data: bpy.types.bpy_struct):
        """
        Set UITreeItem name according to data.
        Item name is used by filters functions.
        """

        if isinstance(data, MultiExporterLODGroup):
            lod_group: MultiExporterLODGroup = data
            item.name = lod_group.name

        elif isinstance(data, MultiExporterLOD):
            lod: MultiExporterLOD = data
            item.name = self.get_clean_lod_name(lod.name ,item.child_index)

    def on_data_checked(self, checked: bool, data: Any):
        if isinstance(data, MultiExporterLODGroup):
            lod_group: MultiExporterLODGroup = data
            lod_group.enabled = checked

        elif isinstance(data, MultiExporterLOD):
            lod: MultiExporterLOD = data
            lod.enabled = checked

    def is_data_checked(self, data: Any)->bool:
        if isinstance(data, MultiExporterLODGroup):
            lod_group: MultiExporterLODGroup = data
            return lod_group.enabled

        elif isinstance(data, MultiExporterLOD):
            lod: MultiExporterLOD = data
            return lod.enabled
        return False


class MSFS2024_UL_LODGroups(bpy.types.UIList, UL_TreeView):

    use_filter_invert: bpy.props.BoolProperty(
        name="Filter Invert", default=False, options=set()
    )  # type: ignore

    lods_only: bpy.props.BoolProperty(
        name="LODs",
        description=(
            "Only show objects or collections with suffixes '_LOD0', '_LOD1' etc,\n"
            "Or with prefixes 'x0_', 'x1_' 'x2_' etc"
        ),
        default=False,
        options=set()
    )  # type: ignore

    active_only: bpy.props.BoolProperty(
        name="Active",
        description="Only show LOD group containing active object or active collection",
        default=False,
        options=set()
    )  # type: ignore

    visible_only: bpy.props.BoolProperty(
        name="Visible",
        description="Only show LOD group that are visible in viewport",
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

    @classmethod
    def draw_context_menu(cls, context: bpy.types.Context, layout: bpy.types.UILayout):
        super().draw_context_menu(context, layout)
        layout.separator()
        export_selected_ope = layout.operator(
            exporter_panel_ops.MSFS2024_OT_ExportSelectedItems.bl_idname,
            text="Export Selected",
            icon="EXPORT",
        )
        export_selected_ope.export_mode = multi_export_mode.ExportMode.OBJECTS.identifier

    def on_reset_filters(self, context):
        self.use_filter_invert = False
        self.lods_only = False
        self.active_only = False
        self.visible_only = False
        self.parents_of_filtered_items = True
        self.check_only = False
        self.uncheck_only = False
        # Make button appears unchecked
        self["reset_filters"] = False

    def _sync_state(self, source):
        # Prevent recursion
        if source == "check":
            self["uncheck_only"] = False
        elif source == "uncheck":
            self["check_only"] = False

    # Inherited Methods
    @classmethod
    def custom_draw_item(
        cls,
        context: bpy.types.Context,
        index: int,
        item: TreeItem,
        layout: bpy.types.UILayout,
    ):

        data = item.get_data()
        if not data:
            return
        row = layout.row(align=True)
        if isinstance(data, MultiExporterLODGroup):
            cls.draw_lod_group(data, item, index, row)

        elif isinstance(data, MultiExporterLOD):

            cls.draw_lod(data, item, index, row)
        else:
            row.label(text="Not Implemented")

    @staticmethod
    def draw_lod(lod: MultiExporterLOD, item: TreeItem, index: int, row: bpy.types.UILayout):
        lod_group = item.get_parent_data()
        if not lod_group:
            return

        row.prop(lod, "file_name", text=f"LOD{item.child_index}", expand=False)

        if lod_group.generate_xml and not lod_group.autogenerate_lods:
            row = row.row(align=True)
            row.ui_units_x = 8
            row.label(text="", icon="FULLSCREEN_ENTER")
            row.prop(lod, "lod_value", text="", expand=False)

    @staticmethod
    def draw_lod_group(lod_group: MultiExporterLODGroup, item: int, index: int, row: bpy.types.UILayout):

        small_row = row.row()
        small_row.scale_x = 0.7
        small_row.label(text=lod_group.name)

        if bpy.app.version > (4, 0, 0):
            row.prop(lod_group, "folder_path", text="", placeholder="Export Folder")
        else:
            row.prop(lod_group, "folder_path", text="")

    def draw_filter(self, context, layout):

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
        row.prop(self, "lods_only", icon="OBJECT_DATAMODE", toggle=True)
        row.prop(self, "active_only", icon="LAYER_ACTIVE", toggle=True)
        row.prop(self, "visible_only", icon="HIDE_OFF", toggle=True)
        row = box.row(align=True)
        row.prop(self, "check_only", icon="CHECKBOX_HLT", toggle=True)
        row.prop(self, "uncheck_only", icon="CHECKBOX_DEHLT", toggle=True)
        col = box.column(align=True)
        if bpy.app.version < (4, 2, 0):
            col.separator()
        else:
            col.separator(type="LINE")
        col.prop(self, "parents_of_filtered_items")

    @staticmethod
    def has_lod_name(name: str) -> bool:
        """
        Check if the given name starts with x0, x1 or 
        ends with _LOD e.g.,'LOD', 'LOD0', 'LOD1'.
        """
        matches = LOD_NAME_PATTERN.search(name)

        return bool(matches)

    @staticmethod
    def is_lods_only_item(item: TreeItem) -> bool:
        """Check if item corresponds to lod or lod group following naming conventions.

        For lodgroup , check if the first two lods follows naming conventions.
        """
        data = item.get_data()
        if not data:
            return False

        if isinstance(data, MultiExporterLODGroup):
            # Check if one of two first lods have a valid lod name
            for lod in data.lods[:2]:
                if MSFS2024_UL_LODGroups.has_lod_name(lod.name):
                    return True
            return False

        elif isinstance(data, MultiExporterLOD):
            return MSFS2024_UL_LODGroups.has_lod_name(data.name)

        return False

    def is_active(self, context: bpy.types.Context, item: TreeItem) -> bool:
        """
        Check if the given item coresponds to active object.
        """

        data = item.get_data()
        if not data:
            return
        if isinstance(data, MultiExporterLODGroup):
            lod_group = data
            for lod in lod_group.lods:
                if lod.objectLOD == context.view_layer.objects.active:
                    return True
                if lod.collection == context.view_layer.active_layer_collection.collection:
                    return True

        elif isinstance(data, MultiExporterLOD):

            lod = data
            if lod.objectLOD == context.view_layer.objects.active:
                return True
            if lod.collection == context.view_layer.active_layer_collection.collection:
                return True

        return False

    def _get_layer_collection(self, context: bpy.types.Context, collection: bpy.types.Collection) -> bpy.types.LayerCollection:
        for layer_collection in bpy.context.view_layer.layer_collection.children:
            if layer_collection.collection == collection:
                return layer_collection
        return None

    def is_visible(self, context: bpy.types.Context, item: TreeItem) -> bool:
        """
        Check if the given item coresponds to a visible object.
        """

        data = item.get_data()
        if not data:
            return

        if isinstance(data, MultiExporterLODGroup):
            lod_group = data
            for lod in lod_group.lods:
                if lod.objectLOD and lod.objectLOD.visible_get(view_layer=context.view_layer): 
                    return True
                collection = lod.collection
                if not collection:
                    return
                layer_collection = self._get_layer_collection(context,collection)
                if layer_collection and not ( layer_collection.hide_viewport or layer_collection.exclude):
                    return True

        elif isinstance(data, MultiExporterLOD):

            lod = data
            if lod.objectLOD and lod.objectLOD.visible_get(view_layer=context.view_layer): 
                return True
            collection = lod.collection
            if not collection:
                return
            layer_collection = self._get_layer_collection(context,collection)
            if layer_collection and not ( layer_collection.hide_viewport or layer_collection.exclude):
                return True

        return False

    def filter_items(self, context: bpy.types.Context, data, propname):
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

        # msfs_lod_groups_ui_tree
        ui_tree: list[TreeItem] = getattr(data, propname)
        helper_funcs = bpy.types.UI_UL_list

        # Filtering by name
        if self.filter_name:
            flt_flags = helper_funcs.filter_items_by_name(
                self.filter_name,
                self.bitflag_filter_item,
                ui_tree,
                "name",
                reverse=self.use_filter_invert,
            )  
        for i, item in enumerate(ui_tree):
            if self.lods_only and not MSFS2024_UL_LODGroups.is_lods_only_item(item):
                flt_flags[i] &= ~self.bitflag_filter_item
            if self.active_only and not self.is_active(context, item):
                flt_flags[i] &= ~self.bitflag_filter_item

            if self.visible_only and not self.is_visible(context, item):
                flt_flags[i] &= ~self.bitflag_filter_item

            if self.check_only and not item.checked:
                flt_flags[i] &= ~self.bitflag_filter_item
            elif self.uncheck_only and item.checked:
                flt_flags[i] &= ~self.bitflag_filter_item

        if self.parents_of_filtered_items:
            self.show_parents_of_filtered_items(ui_tree, flt_flags)

        self.save_flags_in_tree_manager(flt_flags)

        return flt_flags, flt_neworder


def register():
    
    global _lod_group_tree_manager
    multi_edit_properties = {
        MultiExporterLOD: ["file_name","lod_value"],
        MultiExporterLODGroup: [
            "enabled",
            "folder_path",
            "settings_preset",
            "generate_xml",
            "overwrite_guid",
            "autogenerate_lods",
        ],
    }
    _lod_group_tree_manager = LODGroupTreeManager(
        ul_tree_view_class=MSFS2024_UL_LODGroups,
        on_selection_function=_on_selection,
        data_collection_getter=lambda: exp_lod_groups.get_scene_lod_groups(bpy.context.scene),
        alphabetical_order=True,
        multiselection_support=True,
        checkable_items=True,
        multi_edit_properties=multi_edit_properties,
        colored_root_items=True
    )


def unregister():
    
    try:
        global _lod_group_tree_manager
        _lod_group_tree_manager.unregister()
    except:
        pass
