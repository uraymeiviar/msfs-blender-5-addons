"""
Utilities for UI Tree Widget.

TreeItem
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import bpy

from enum import Enum

from _addons_common.ui.tree_widget.manager import TreeManager


class IntItem(bpy.types.PropertyGroup):

    register_order = -1

    value: bpy.props.IntProperty() # type: ignore

# region UITreeItem


def _set_children_checked_state(item: TreeItem, ui_tree_utils: TreeManager):

    if not item.all_children_count:
        return

    item_list = ui_tree_utils.get_tree_collection()
    children_range_start = item.index + 1
    children_range_end = children_range_start + item.all_children_count
    for i in range(children_range_start, children_range_end):

        try:
            child_item: TreeItem = item_list[i]
        except:
            continue
        # use [] operator to prevent update function to be called
        child_item["checked"] = item.checked
        child_item["partially_checked"] = False
        # Reflect checked state on child item data
        data = child_item.get_data()
        if data:
            ui_tree_utils.on_data_checked(item.checked, data)


def _set_parent_checked_state(item: TreeItem, ui_tree_utils_class: TreeManager):
    """
    Check parent item if all direct children are checked.
    Set parent item as partially checked is some of children are checked.
    """
    item_list = ui_tree_utils_class.get_tree_collection()

    for int_item in item.all_parent_indexes:
        i = int_item.value
        try:
            parent_item: TreeItem = item_list[i]
        except:
            continue
        if not parent_item.children_count:
            continue
        all_children_enabled = True
        has_enabled_children = False
        for j in range(i + 1, i + 1 + parent_item.children_count):
            try:
                child_item: TreeItem = item_list[j]
            except:
                continue
            if child_item.checked:
                has_enabled_children = True
            else :
                all_children_enabled = False
        # use [] operator to prevent update function to be called
        parent_item["checked"] = all_children_enabled
        parent_item.partially_checked = has_enabled_children and not all_children_enabled

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
        item["partially_checked"] = False
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

    self.partially_checked = False

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

class TreeItemColor(Enum):
    NONE = ("NONE", "None", "OUTLINER_COLLECTION")
    RED = ("RED", "Red", "COLLECTION_COLOR_01")
    ORANGE = ("ORANGE", "Orange","COLLECTION_COLOR_02")
    YELLOW = ("YELLOW","Yellow", "COLLECTION_COLOR_03")
    GREEN = ("GREEN", "Green","COLLECTION_COLOR_04")
    BLUE = ("BLUE", "Blue","COLLECTION_COLOR_05")
    PURPLE = ("PURPLE", "Purple","COLLECTION_COLOR_06")
    PINK = ("PINK", "Orange","COLLECTION_COLOR_07")
    BROWN = ("BROWN", "Brown","COLLECTION_COLOR_08")

    def __init__(self, identifier: str, label:str, icon: str):
        self.identifier = identifier
        self.label = label
        self.icon = icon

    @classmethod
    def from_identifier(cls, identifier: str) -> TreeItemColor | None:
        for mode in cls:
            if mode.identifier == identifier:
                return mode
        return None

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

    partially_checked: bpy.props.BoolProperty(
        default=False,
        description="True when children is unchecked, but one of it's children is",          
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

    color_tag: bpy.props.EnumProperty(
        name ="Color Tag",
        items=((TreeItemColor.NONE.identifier, TreeItemColor.NONE.label, "", TreeItemColor.NONE.icon, 0),
               (TreeItemColor.RED.identifier, TreeItemColor.RED.label, "", TreeItemColor.RED.icon, 1),
               (TreeItemColor.ORANGE.identifier, TreeItemColor.ORANGE.label, "", TreeItemColor.ORANGE.icon, 2),
               (TreeItemColor.YELLOW.identifier, TreeItemColor.YELLOW.label, "", TreeItemColor.YELLOW.icon, 3),
               (TreeItemColor.GREEN.identifier, TreeItemColor.GREEN.label, "", TreeItemColor.GREEN.icon, 4),
               (TreeItemColor.BLUE.identifier, TreeItemColor.BLUE.label, "", TreeItemColor.BLUE.icon, 5),
               (TreeItemColor.PURPLE.identifier, TreeItemColor.PURPLE.label, "", TreeItemColor.PURPLE.icon, 6),
               (TreeItemColor.PINK.identifier, TreeItemColor.PINK.label, "", TreeItemColor.PINK.icon, 7),
               (TreeItemColor.BROWN.identifier, TreeItemColor.BROWN.label, "", TreeItemColor.BROWN.icon, 8),
        ), # type: ignore
        default=TreeItemColor.NONE.identifier,
    ) # type: ignore

    @staticmethod
    def _get_full_data_path(data: bpy.types.ID) -> str:

        # repr() can be a bit slow here so use full_data_path prop if present
        full_data_path = getattr(data, "full_data_path", None)
        if not full_data_path:
            full_data_path = repr(data)
            # Store it for later use
            if hasattr(data,"full_data_path"):
                data.full_data_path  = full_data_path
        return full_data_path

    def set_parent_data(self, data: bpy.types.ID):

        self.parent_full_data_path = self._get_full_data_path(data)

    def set_data(self, data: bpy.types.ID):
        # repr can be a bit slow here
        self.full_data_path = self._get_full_data_path(data)

    def _get_data(self, parent: bool = False) -> None | bpy.types.ID:
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

    def get_data(self) -> None | bpy.types.ID:
        return self._get_data(parent=False)

    def get_parent_data(self) -> None | bpy.types.ID:
        return self._get_data(parent=True)

# endregion
