"""
Operators used in tree view
"""
from __future__ import annotations
from typing import TYPE_CHECKING, Iterable

import bpy

if TYPE_CHECKING:
    from _addons_common.ui.tree_widget.item import TreeItem
    from _addons_common.ui.tree_widget.manager import TreeManager
# region Selection
class TREEVIEW_OT_SetItemsSelection(bpy.types.Operator):
    bl_idname = "treeview.set_items_selection"
    bl_label = "Set Item Selection using shift and alt hotkeys"
    bl_options = {"INTERNAL"}

    old_active_index: bpy.props.IntProperty(default=0) # type: ignore
    new_active_index: bpy.props.IntProperty(default=0) # type: ignore

    tree_manager_name: bpy.props.StringProperty() # type: ignore

    event_shift = False
    event_alt = False

    def on_shift_event(self, item_list: Iterable[TreeItem], tree_manager: TreeManager):
        """
        Select a range of items between old active index and new active index.
        """
        selection_range = range(self.old_active_index, self.new_active_index + 1)
        if self.new_active_index < self.old_active_index:
            selection_range = range(self.new_active_index, self.old_active_index + 1)
        for i in selection_range:
            try:
                item = item_list[i]
            except IndexError:
                return
            if not tree_manager.item_visible_after_ui_filter(item):
                continue
            item.selected = True

    def on_alt_event(
        self,
        active_item: TreeItem,
        item_list: Iterable[TreeItem],
        tree_manager: TreeManager,
    ):
        """
        Invert selection state when user alt click an item.
        """
        selected_items = tree_manager.get_selected_items()
        if not selected_items and active_item.index == self.old_active_index:
            # User alt + click on active without any selection
            active_item.selected = False
            tree_manager.set_ui_tree_active_index(None, update_selection=False)
        else:
            # User alt + click another item
            active_item.selected = not active_item.selected
            try:
                old_item = item_list[self.old_active_index]
            except IndexError:
                return
            # Always select old item is new active one is selected
            # and set active item to previous old item in case
            if active_item.selected:
                old_item.selected = True
            else:
                # if active item was unselected, then set active the first visible selected item
                selected_items = tree_manager.get_selected_items()
                new_active_index = -1
                for item in reversed(selected_items):

                    if not tree_manager.item_visible_after_ui_filter(item):
                        continue
                    new_active_index = item.index

                    break
                tree_manager.set_ui_tree_active_index(
                    new_active_index, update_selection=False
                )

    def on_simple_click(self, active_item: TreeItem, tree_manager: TreeManager):
        """
        Unselect all and set active item.
        """
        tree_manager.unselect_all()
        # Set active as selected
        active_item.selected = True
        tree_manager.set_ui_tree_active_index(
            self.new_active_index, update_selection=False
        )

    def execute(self, contex: bpy.types.Context):
        from _addons_common.ui.tree_widget.manager import TreeManager

        tree_manager: TreeManager | None = TreeManager.tree_manager_instances.get(
            self.tree_manager_name, None
        )
        if not tree_manager:
            return {"FINISHED"}

        item_list = tree_manager.get_ui_tree_collection()
        active_item = tree_manager.get_active_item()

        if not active_item:
            return {"FINISHED"}
        if not tree_manager.item_visible_after_ui_filter(active_item):
            return {"FINISHED"}

        # Multiselection with shift or alt
        if self.event_shift:
            self.on_shift_event(item_list, tree_manager)

        elif self.event_alt:
            self.on_alt_event(active_item, item_list, tree_manager)
        else:
            self.on_simple_click(active_item, tree_manager)

        tree_manager.update_has_multiselection_state()
        return {"FINISHED"}

    def invoke(self, context, event):
        self.event_alt = event.alt
        self.event_shift = event.shift
        return self.execute(context)

class TREEVIEW_OT_SelectAllItems(bpy.types.Operator):
    bl_idname = "treeview.select_all_items"
    bl_label = "Select/Deselect all items"
    bl_options = {"INTERNAL"}

    select: bpy.props.BoolProperty(default=True) # type: ignore

    tree_manager_name: bpy.props.StringProperty() # type: ignore

    def execute(self, context: bpy.types.Context):
        from _addons_common.ui.tree_widget.manager import TreeManager
        tree_manager: TreeManager | None = TreeManager.tree_manager_instances.get(
            self.tree_manager_name, None
        )
        if not tree_manager:
            return {"FINISHED"}

        # Select or Unselect all
        if self.select :
            tree_manager.select_all_visible()
        else:
            tree_manager.unselect_all()

        return {"FINISHED"}
# endregion

# region Expand/Collapse
def _set_visible_active_after_expand_edit(tree_manager: TreeManager, active_item_index: int):
    """If the active item is no longer visible after expand/edit,
    then set the nearest visible item as active before it (usually the parent).
    """
    active_item = tree_manager.get_active_item()
    # Check if item is hidden since filter flags are not yet refreshed
    # Active item could be hidden after the expand edits
    if not active_item or (not active_item.hidden and tree_manager.item_visible_after_ui_filter(active_item)):
        return
    
    item_list = tree_manager.get_ui_tree_collection()
    # Only search items before the current active index”
    item_list = item_list[:active_item_index]
    new_active_index = -1
    for item in reversed(item_list):
        if item.hidden and not tree_manager.item_visible_after_ui_filter(item):
            continue
        new_active_index = item.index
        
        break
    tree_manager.set_ui_tree_active_index(new_active_index, update_selection=False)

class TREEVIEW_OT_ToggleItemExpand(bpy.types.Operator):

    bl_idname = "treeview.toggle_item_expand"
    bl_label = "Toggle Tree Item expand state"
    bl_options = {"INTERNAL"} 

    item_index: bpy.props.IntProperty(default=0) # type: ignore
    tree_manager_name: bpy.props.StringProperty() # type: ignore

    def execute(self, context: bpy.types.Context):
        from _addons_common.ui.tree_widget.manager import TreeManager
        if not self.tree_manager_name:
            raise NotImplementedError("Must specify tree_manager_name")

        tree_manager :TreeManager = TreeManager.tree_manager_instances.get(self.tree_manager_name, None)
        if not tree_manager:
            return {"FINISHED"}
        item_list = tree_manager.get_ui_tree_collection()
        item: TreeItem
        item = item_list[self.item_index]

        expand = not item.expanded
        if tree_manager._has_multiselection and item.selected:

            active_item = tree_manager.get_active_item()
            active_item_index = -1
            if active_item:
                active_item_index = active_item.index

            index_to_expand = []
            for i, item in enumerate(item_list):
                if not item.selected:
                    continue
                index_to_expand.append(i)

            if index_to_expand:
                index_to_expand.reverse()
                for i in index_to_expand:
                    tree_manager.expand_ui_tree_item(
                        expand=expand,
                        item_index=i,
                        set_active=False,
                        update_selection=False,
                    )

            # Find new active index after expand
            if not active_item_index:
                return {"FINISHED"}
                
            _set_visible_active_after_expand_edit(tree_manager, active_item_index)

        else:
            tree_manager.expand_ui_tree_item(
                expand=expand,
                item_index=self.item_index,
                set_active=True,
                update_selection=False,
            )
        return {"FINISHED"}

class TREEVIEW_OT_ExpandAllItems(bpy.types.Operator):
    bl_idname = "treeview.expand_all_item"
    bl_label = "Expand All Tree Items"
    bl_description = "Expand All or Collapse All Tree Items"
    bl_options = {"INTERNAL"}

    expand: bpy.props.BoolProperty(default=True) # type: ignore
    tree_manager_name: bpy.props.StringProperty() # type: ignore

    def execute(self, context: bpy.types.Context):
        from _addons_common.ui.tree_widget.manager import TreeManager
        if not self.tree_manager_name:
            raise NotImplementedError("Must specify tree_manager_name")

        tree_manager :TreeManager = TreeManager.tree_manager_instances.get(self.tree_manager_name, None)
        if not tree_manager:
            return {"FINISHED"}
        item_list = tree_manager.get_ui_tree_collection()

        active_item = tree_manager.get_active_item()
        active_item_index = -1
        if active_item:
            active_item_index = active_item.index

        index_to_expand = []
        for i, item in enumerate(item_list):
            if item.expanded == self.expand:
                continue
            index_to_expand.append(i)

        if index_to_expand:
            index_to_expand.reverse()
            for i in index_to_expand:
                tree_manager.expand_ui_tree_item(
                    expand=self.expand, 
                    item_index=i, 
                    set_active=False, 
                    update_selection=False
                )

        

        # Find new active index after expand
        if not active_item_index:
            return {"FINISHED"}

        _set_visible_active_after_expand_edit(tree_manager, active_item_index)

        return {"FINISHED"}

    @classmethod
    def draw_expand_all_buttons(cls, layout: bpy.types.UILayout, tree_manager_name: str):
        layout: bpy.types.UILayout
        row = layout.row(align=True)
        op = row.operator(
            cls.bl_idname,
            text="",
            icon="TRIA_DOWN",
            emboss=False
        )
        op.expand = True
        op.tree_manager_name = tree_manager_name
        op = row.operator(
            cls.bl_idname,
            text="",
            icon="TRIA_UP",
            emboss=False
        )
        op.expand = False
        op.tree_manager_name = tree_manager_name
# endregion

# region Check

class TREEVIEW_OT_CheckAllItems(bpy.types.Operator):
    bl_idname = "treeview.check_all_items"
    bl_label = "Check All Tree Items"
    bl_description = "Check all visible or uncheck all items"
    bl_options = {"INTERNAL"}

    check: bpy.props.BoolProperty(default=True) # type: ignore
    tree_manager_name: bpy.props.StringProperty() # type: ignore

    def execute(self, context: bpy.types.Context):
        from _addons_common.ui.tree_widget.manager import TreeManager
        tree_manager: TreeManager | None = TreeManager.tree_manager_instances.get(
            self.tree_manager_name, None
        )
        if not tree_manager:
            return {"FINISHED"}

        tree_manager.check_all(checked=self.check, visible_only=self.check)

        return {"FINISHED"}


# endregion
