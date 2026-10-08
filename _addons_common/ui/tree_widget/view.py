"""
UI Tree View.

Meant to be reimplemented.
Cf implementation example in msfs_multi_export_objects.py and msfs_multi_export_presets.py
"""
from __future__ import annotations

import bpy
from typing import Any, TYPE_CHECKING


from _addons_common.ui.tree_widget.manager import TreeManager
from _addons_common.ui.tree_widget import view_ope
from _addons_common.ui.tree_widget.item import TreeItemColor
if TYPE_CHECKING:
    from _addons_common.ui.tree_widget.item import TreeItem


class UL_TreeView():
    """
    Tree view mixin for UILists.

    Adds tree-like behavior when drawing items 
    (expand/collapse states, parent–child relationships, etc.).

    It is intended to be used as a 
    secondary base class alongside bpy.types.UIList.
    """
    # View Options:
    _indent_scale = 3
    tree_manager_name = None
    ITEM_CONTEXT_POINTER = "tree_item"

    # region OVERRIDABLES FUNCTIONS
    @classmethod
    def custom_draw_item(
        cls,
        context: bpy.types.Context,
        index: int,
        item: TreeItem,
        layout: bpy.types.UILayout
    ):
        raise NotImplementedError()

    @classmethod
    def draw_context_menu(cls, context: bpy.types.Context, layout: bpy.types.UILayout):
        """
        Custom draw function for right click menu.
        """
        tree_manager = cls.get_tree_manager()
        if not tree_manager:
            return
        # Select Operators

        if tree_manager.MULTISELECTION_SUPPORT:
            layout.separator()
            select_all_ope = layout.operator(
                view_ope.TREEVIEW_OT_SelectAllItems.bl_idname,
                text="Select All",
                icon="RESTRICT_SELECT_OFF",
            )
            select_all_ope.tree_manager_name = cls.tree_manager_name
            select_all_ope.select = True

            deselect_all_ope = layout.operator(
                view_ope.TREEVIEW_OT_SelectAllItems.bl_idname,
                text="Deselect All",
                icon="RESTRICT_SELECT_ON",
            )
            deselect_all_ope.tree_manager_name = cls.tree_manager_name
            deselect_all_ope.select = False

        # Check Operators
        if tree_manager.CHECKABLE_ITEMS:
            layout.separator()
            check_all_ope = layout.operator(
                view_ope.TREEVIEW_OT_CheckAllItems.bl_idname,
                text="Check All",
                icon="CHECKBOX_HLT",
            )
            check_all_ope.tree_manager_name = cls.tree_manager_name
            check_all_ope.check = True

            uncheck_all_ope = layout.operator(
                view_ope.TREEVIEW_OT_CheckAllItems.bl_idname,
                text="Uncheck All",
                icon="CHECKBOX_DEHLT",
            )
            uncheck_all_ope.tree_manager_name = cls.tree_manager_name
            uncheck_all_ope.check = False

        if tree_manager.COLORED_ROOT_ITEMS:
            layout.separator()
            active_item = tree_manager.get_active_item()
            if active_item.parent_index == -1:
                view_ope.draw_root_item_colors_ops(cls.tree_manager_name, layout)
    @classmethod
    def draw_UL_TreeView(
        cls, context, layout: bpy.types.UILayout, rows: int = 10, type: str = "DEFAULT"
    ):
        tree_manager = cls.get_tree_manager()
        if not tree_manager:
            return
        if tree_manager.MULTISELECTION_SUPPORT and tree_manager.MULTI_EDIT_PROPERTIES:
            tree_manager.ensure_subscription_to_multi_edit_props()

        layout.template_list(
           cls.__name__,
            "",
            context.scene,
            tree_manager.tree_col_prop_name,
            context.window_manager,
            tree_manager.active_index_prop_name,
            rows=rows,
            type=type,
            sort_lock=True,
        )

    # endregion
    @classmethod
    def get_tree_manager(cls) -> TreeManager | None:
        return TreeManager.get_tree_manager_instance_by_name(cls.tree_manager_name)

    @staticmethod
    def _get_item_from_context_pointer(context: bpy.types.Context | None= None)->bool:
        if context is None:
            context = bpy.context
        tree_item: TreeItem | None = getattr(context, UL_TreeView.ITEM_CONTEXT_POINTER, None)
        return tree_item

    def draw_item(
        self,
        context: bpy.types.Context,
        layout: bpy.types.UILayout,
        data: Any,
        item: TreeItem,
        icon: int,
        active_data: Any,
        active_propname: str,
        index: int
    ):
        if not self.layout_type in {"DEFAULT", "COMPACT"}:
            return
        # Set context pointer for right-click
        layout.context_pointer_set(UL_TreeView.ITEM_CONTEXT_POINTER, item)

        tree_manager = self.get_tree_manager()
        if not tree_manager:
            return

        if (
            tree_manager.MULTISELECTION_SUPPORT 
            and tree_manager._has_multiselection
            and item.selected
        ):
            layout.alert = True

        row = layout.row(align=True)
        for _ in range(item.all_parent_count * self._indent_scale):
            # use layout.row instead of layout.separator_spacer
            row = layout.row(align=True)
        if not tree_manager.IS_FLAT_LIST:
            if not item.children_count:
                # align item without children with item with children
                row.label(text="", icon="BLANK1")
            elif item.expanded :
                op = row.operator(
                    view_ope.TREEVIEW_OT_ToggleItemExpand.bl_idname,
                    text="",
                    icon="DOWNARROW_HLT",
                    emboss=False
                )
                op.tree_manager_name = tree_manager.unique_name
                op.item_index = index

            elif not item.expanded :
                op = row.operator(
                    view_ope.TREEVIEW_OT_ToggleItemExpand.bl_idname,
                    text="",
                    icon="RIGHTARROW",
                    emboss=False
                )
                op.tree_manager_name = tree_manager.unique_name
                op.item_index = index

        if tree_manager.CHECKABLE_ITEMS:
            check_row = row.column()
            # Make checkbox icon smaller and center it  vertically
            check_row.separator(factor=0.25)
            check_row.scale_y = 0.85
            check_row.scale_x = 0.95
            # use icon to simulate tri-state checkbox
            icon = "BLANK1"
            if item.partially_checked:
                icon = "REMOVE"
            elif item.checked:
                icon = "CHECKMARK"

            check_row.prop(item, "checked", icon_only=True, icon=icon)

            row.separator(factor=0.4)

        if tree_manager.COLORED_ROOT_ITEMS and item.parent_index == -1:
            color_tag_row = row.row()
            color_tag_row.scale_x = 0.85
            item_color = TreeItemColor.from_identifier(item.color_tag)
            icon = "BLANK1"
            if item_color:
                icon = item_color.icon
            color_tag_row.label(text="", icon=icon)

        self.custom_draw_item(context, index, item, layout)

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
        
        ui_tree :list[TreeItem]= getattr(data, propname)

        flt_flags = []
        flt_neworder = []

        flt_flags = [self.bitflag_filter_item] * len(ui_tree)

        for i, item in enumerate(ui_tree):

            if item.hidden:
                flt_flags[i] &= ~self.bitflag_filter_item

        self.save_flags_in_tree_manager(flt_flags)
        return flt_flags, flt_neworder

    def save_flags_in_tree_manager(self, flt_flags):
        """Save flags in tree manager class.
        Used for item selection system in order to not select hidden items.
        """
        tree_manager = self.get_tree_manager()
        if not tree_manager:
            return
        tree_manager.save_flt_flags(flt_flags)

    def show_parents_of_filtered_items(self, ui_tree: list[TreeItem], flt_flags):
        """
        Ensure that all parents of currently visible items are also marked visible.
        Call this after filtering.
        """
        for item, flag in zip(ui_tree,flt_flags):
            if not (flag & self.bitflag_filter_item):
                continue
            for parent_item in item.all_parent_indexes:
                flt_flags[parent_item.value] |= self.bitflag_filter_item

    @staticmethod
    def _draw_context_menu(_self, context):
        """
        _self represents the context menu.

        Entry point for right click menu draw function.
        """
        tree_item = UL_TreeView._get_item_from_context_pointer(context)
        if not tree_item:
            return
        tree_manager = TreeManager.get_tree_manager_instance_by_name(tree_item.tree_manager_name)
        if not tree_manager:
            return
        tree_manager.ul_tree_view_class.draw_context_menu(context, _self.layout)

    @classmethod
    def register(cls):
        # Right Click Menu
        # Add custom draw function to UIList context menu
        if not(cls._draw_context_menu in bpy.types.UI_MT_button_context_menu._dyn_ui_initialize()):
            bpy.types.UI_MT_button_context_menu.append(cls._draw_context_menu)

    @classmethod
    def unregister(cls):
        try:
            # Only remove if there are no TreeManager instances
            if (
                not TreeManager.tree_manager_instances
                and cls._draw_context_menu
                in bpy.types.UI_MT_button_context_menu._dyn_ui_initialize()
            ):
                bpy.types.UI_MT_button_context_menu.remove(cls._draw_context_menu)
        except:
            pass
