"""
Utilities for UI Tree Widget.

TreeItem
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import bpy


from _addons_common.ui.tree_widget.manager import TreeManager


class IntItem(bpy.types.PropertyGroup):

    register_order = -1

    value: bpy.props.IntProperty() # type: ignore

# region UITreeItem


def _set_children_checked_state(item: TreeItem, ui_tree_utils: TreeManager):

    if not item.all_children_count:
        return

    item_list = ui_tree_utils.get_ui_tree_collection()
    children_range_start = item.index + 1
    children_range_end = children_range_start + item.all_children_count
    for i in range(children_range_start, children_range_end):

        try:
            child_item: TreeItem = item_list[i]
        except:
            continue
        # use [] operator to prevent update function to be called
        child_item["checked"] = item.checked
        # Reflect checked state on child item data
        data = child_item.get_data()
        if data:
            ui_tree_utils.on_data_checked(item.checked, data)


def _set_parent_checked_state(item: TreeItem, ui_tree_utils_class: TreeManager):
    """
    Check parent item if all direct children are checked
    """
    item_list = ui_tree_utils_class.get_ui_tree_collection()

    for int_item in item.all_parent_indexes:
        i = int_item.value
        try:
            parent_item: TreeItem = item_list[i]
        except:
            continue
        if not parent_item.children_count:
            continue
        all_children_enabled = True
        for j in range(i + 1, i + 1 + parent_item.children_count):
            try:
                child_item: TreeItem = item_list[j]
            except:
                continue
            if not child_item.checked:
                all_children_enabled = False
                break
        # use [] operator to prevent update function to be called
        parent_item["checked"] = all_children_enabled
        # Reflect checked state on parent item data
        data = parent_item.get_data()
        if data:
            ui_tree_utils_class.on_data_checked(all_children_enabled, data)


def _process_checked_selection(ui_tree_utils_class: TreeManager, checked: bool):
    selected_items = ui_tree_utils_class.get_selected_items()
    if len(selected_items) <= 1:
        return

    for item in selected_items:
        # use [] operator to prevent update function to be called
        item["checked"] = checked
        data = item.get_data()
        if data:
            ui_tree_utils_class.on_data_checked(item.checked, data)

        # Update chilren checked state
        _set_children_checked_state(item, ui_tree_utils_class)

        # Update parent checked state
        # Check parent item if all direct children are checked
        _set_parent_checked_state(item, ui_tree_utils_class)


def _on_item_checked(self: TreeItem, context):
    """Update function for UITreeItem checked property.
    Set check state on item children and parents.
    Also set check state on other selected items.
    """
    tree_manager : TreeManager = TreeManager.tree_manager_instances.get(self.tree_manager_name, None)
    if not tree_manager:
        return
    # Reflect item checked state on  data
    active_data = self.get_data()
    if active_data:
        tree_manager.on_data_checked(self.checked, active_data)
    
    # Update chilren checked state
    _set_children_checked_state(self, tree_manager)

    # Update parent checked state
    # Check parent item if all direct children are checked
    _set_parent_checked_state(self, tree_manager)

    # Checked selected items if item being checked is selected
    active_data_in_selection = False
    selected_items = tree_manager.get_selected_items()
    for item in selected_items:
        data = item.get_data()
        if active_data != data:
            continue
        active_data_in_selection = True
        break

    if active_data_in_selection:
        _process_checked_selection(tree_manager, self.checked)


class TreeItem(bpy.types.PropertyGroup):
    """
    A UIList item with additional properties to mimic
    a hierarchical tree structure.
    """

    # region Properties
    selected: bpy.props.BoolProperty(
        default=False,
        description="Is item selected"
    ) # type: ignore

    checked: bpy.props.BoolProperty(
        default=False,
        description="Is item checked",
        update=_on_item_checked,
        
    ) # type: ignore

    expanded: bpy.props.BoolProperty(
        default=False,
        description="Is item expanded"
    ) # type: ignore
    
    hidden: bpy.props.BoolProperty(
        default=False,
        description="Is item hidden, before any UI Filtering"
    ) # type: ignore

    index: bpy.props.IntProperty(
        default=-1
    ) # type: ignore

    # Index of parent item in the same collection, -1 if no parent
    parent_index: bpy.props.IntProperty(
        default=-1
    ) # type: ignore
    
    all_parent_indexes: bpy.props.CollectionProperty(
        type=IntItem,
        description=(
            "List of all parents indexes,"
            " starting from the closest parent"
        )
    )  # type: ignore
    
    all_parent_count: bpy.props.IntProperty(
        default=0,
        description="Number of all parent items"
    ) # type: ignore
    
    child_index: bpy.props.IntProperty(
        default=0,
        description="Local index under parent"
    ) # type: ignore
    
    children_count: bpy.props.IntProperty(
        default=0, 
        description="Direct children count"
    ) # type: ignore
    
    all_children_count: bpy.props.IntProperty(
        default=0,
        description="All children count including nested ones"
    ) # type: ignore
    
    full_data_path: bpy.props.StringProperty(
        default="",
        description=(
            "Full path to data this item represents.\n"
            "For example:\n"
            "bpy.context.scene.msfs_multi_exporter_lod_groups[0]"
        )
    ) # type: ignore
    
    parent_full_data_path: bpy.props.StringProperty(
        default="",
        description="Full path to data of the parent item."
    ) # type: ignore
    
    tree_manager_name: bpy.props.StringProperty() # type: ignore

    @staticmethod
    def _get_full_data_path(data: bpy.types.bpy_struct) -> str:

        # repr() can be a bit slow here so use full_data_path prop if present
        full_data_path = getattr(data, "full_data_path", None)
        if not full_data_path:
            full_data_path = repr(data)
            # Store it for later use
            if hasattr(data,"full_data_path"):
                data.full_data_path  = full_data_path
        return full_data_path

    def set_parent_data(self, data: bpy.types.bpy_struct):

        self.parent_full_data_path = self._get_full_data_path(data)

    def set_data(self, data: bpy.types.bpy_struct):
        # repr can be a bit slow here
        self.full_data_path = self._get_full_data_path(data)

    def _get_data(self, parent: bool = False) -> None | bpy.types.bpy_struct:
        """
        Safely get data from data_path string

        Args:
            parent: Retrieve parent_data instead of data. Defaults to False.
        """

        prop = self.full_data_path
        if parent:
            prop = self.parent_full_data_path

        if not prop:
            return None
        try:
            data = eval(prop)
            return data
        except:
            return None

    def get_data(self) -> None | bpy.types.bpy_struct:
        return self._get_data(parent=False)

    def get_parent_data(self) -> None | bpy.types.bpy_struct:
        return self._get_data(parent=True)

# endregion
