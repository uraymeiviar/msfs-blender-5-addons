"""
Utilities for UI Tree Widget.

Meant to be reimplemented.

Cf implementation example in msfs_multi_export_objects.py and msfs_multi_export_presets.py
"""
from __future__ import annotations
from contextlib import contextmanager

import bpy

import string

from typing import Any, Iterable, TYPE_CHECKING, Callable, Type

if TYPE_CHECKING:
    # Avoid circular import for type hinting
    from _addons_common.ui.tree_widget.item import IntItem, TreeItem
    from _addons_common.ui.tree_widget.view import UL_TreeView
# region UITreeManager


class TreeManager:
    """
    Tree Manager.

    Manage TreeItem collection.

    Objective is to have a collection of tree items that reflects a collection of data.
    
    This class manages items hierarchy, expand and collapsed items, checked items
    and items multi selection.

    Reimplement it to fit your needs (cf region with overridables functions)
    """
    instances_count = 0
    tree_manager_instances: dict[str, TreeManager] = {}

    @classmethod
    def get_unique_name(cls):
        return str(cls.__name__)
    
    def __init__(
        self,
        ul_tree_view_class: Type[UL_TreeView],
        on_selection_function: Callable | None = None,
        data_collection_getter: Callable | None = None,
        alphabetical_order: bool = True,
        multiselection_support: bool = True,
        checkable_items: bool = True,
        multi_edit_properties : dict[type, list[str]] = {}
        
    ) -> None:
        # Remove white spaces in unique name
        unique_name = self.get_unique_name()
        if not unique_name[0] in string.ascii_letters:
            raise Exception(f"TreeManager Class name must start with a letter! {unique_name} is invalid!")
        if unique_name in TreeManager.tree_manager_instances:
            raise Exception(f"A TreeManager with same class name {unique_name} already exists!")

        TreeManager.instances_count +=1

        self.unique_name = unique_name
        self.data_collection_getter = data_collection_getter
        self.ul_tree_view_class : Type[UL_TreeView] = ul_tree_view_class

        self.on_selection_function: Callable | None = on_selection_function
        # region Manager settings
        self.ALPHABETICAL_ORDER :bool = alphabetical_order
        self.MULTISELECTION_SUPPORT = multiselection_support
        self.CHECKABLE_ITEMS = checkable_items
        self.MULTI_EDIT_PROPERTIES = {}

        if self.MULTISELECTION_SUPPORT and not multiselection_support:
            raise ValueError("multiselection_support must be True in order to use multi_edit_properties.")

        if self.MULTISELECTION_SUPPORT:
            self.MULTI_EDIT_PROPERTIES = multi_edit_properties
            self._reallocation_checker_args = []
        self.disable_multi_edit = False 
        # endregion

        self.ui_tree_prop_name : str 
        self.active_index_prop_name : str 
        self.old_active_index_prop_name :str 

        TreeManager.tree_manager_instances[self.unique_name] = self
        self._expanded_items = []

        # Filter flags must be set in UIList filter_items() if you want
        # Multiselection to work with filters
        self._flt_flags = []

        self._has_multiselection = False # Track if user selected multiple items
        self._updating_props = False #Prevent recursion error when updating prop in multiselection

        self.register()

    @classmethod
    def get_tree_manager_instance(cls, tree_manager_name: str) -> TreeManager | None:
        tree_manager: TreeManager | None = cls.tree_manager_instances.get(
            tree_manager_name, None
        )
        return tree_manager

    # region OVERRIDABLES FUNCTIONS
    def get_name_for_alpha_order(self, data) -> str:
        """
        Get data name for alphabetical ordering.
        It can differ from the item name used for filtering.
        """
        return data.name

    def get_data_children(
        self, 
        data: bpy.types.bpy_struct
    ) -> list[bpy.types.bpy_struct]:
        """
        Return a list of data children.
        Children must have list have a "name" attribute.
        """
        return []

    def set_ui_tree_item_name(
        self,
        item: TreeItem,
        data: bpy.types.bpy_struct
    ):
        """
        Set UITreeItem name according to data.
        Item name is used by filters functions.
        """
        item.name = data.name

    def get_expanded_items(self) -> set[str]:
        """
        Get list of items name that are expanded in ui tree
        """
        expanded_ui_tree_items = set()
        for item in self.get_ui_tree_collection():
            if item.expanded:
                expanded_ui_tree_items.add(item.name)
        return expanded_ui_tree_items

    def is_data_checked(self, data: Any)->bool:
        return False

    def on_data_checked(self, checked: bool, data: Any):
        pass

    # endregion

    def get_data_collection(self) -> Iterable:
        """
        Return main data Collection Iterable.
        """
        if not self.data_collection_getter:
            raise Exception("[TreeManager] Provide a data_collection_getter on init\n," 
                            "or implement get_data_collection() in derived class")
        return self.data_collection_getter()

    def get_ui_tree_collection(self) -> bpy.types.bpy_prop_collection_idprop[TreeItem]:
        """
        Return Collection property of UITreeItem.This is
        the collection that will be displayed in UIList view.
        """
        return getattr(bpy.context.scene, self.ui_tree_prop_name)

    def _get_ui_tree_active_index(self) -> int:
        """
        Return ui list active item property.
        """
        return getattr(bpy.context.window_manager, self.active_index_prop_name)

    def set_ui_tree_active_index(self, value: int | None, update_selection: bool = False):
        """
        Set ui list active item property.
        Selection update is disabled by default in order to prevent infinite recusion.
        """
        if value is None:
            value = -1 # No active item in UI
        if update_selection:
            # Trigger prop update function
            setattr(bpy.context.window_manager, self.active_index_prop_name, value)
        else:
            bpy.context.window_manager[self.active_index_prop_name] = value

    def _get_ui_old_tree_active_index(self) -> int:
        """
        Return ui list old active item property.
        Used for multiselection.
        """
        return getattr(bpy.context.window_manager, self.old_active_index_prop_name)

    def _set_ui_old_tree_active_index(self, value: int):
        """
        Set ui list old active item property.
        Used for multiselection.
        """
        setattr(bpy.context.window_manager, self.old_active_index_prop_name, value)

    def set_ui_tree_active_item_by_data(
        self, data: bpy.types.bpy_struct, 
        update_selection: bool = False
    ):
        """
        Set active item with corresponding data
        """

        ui_tree_collection = self.get_ui_tree_collection()
        for i, item in enumerate(ui_tree_collection):
            item: TreeItem
            item_data = item.get_data()
            if item_data == data:
                self.set_ui_tree_active_index(i, update_selection)
                return

    def _create_tree_item_from_data(
        self,
        data: bpy.types.bpy_struct,
        parent_item_index: int | None = None,
        child_index=0,
    ):
        """
        Create UITreeItem from provided data.
        """
        ui_tree_collection = self.get_ui_tree_collection()
        ui_tree_item: TreeItem = ui_tree_collection.add()
        item_index = len(ui_tree_collection) - 1
        ui_tree_item.index = item_index
        # Store tree manager import class in item so we call tree manager from item (cf _on_item_checked)
        ui_tree_item.tree_manager_name = self.unique_name

        # Set properties depending on parent state
        parent_item = None
        if not parent_item_index is None:
            # Get the parent item each time a new item is added to the UI tree collection.
            # Sometimes the parent_item pointer can become invalid when a new element is added.
            try:
                parent_item = ui_tree_collection[parent_item_index]
            except IndexError:
                parent_item = None
        if not parent_item:
            ui_tree_item.parent_index = -1
        else:
            ui_tree_item.parent_index = parent_item_index

            # Generate list of parents ordered by proximity
            p_index_item :IntItem = ui_tree_item.all_parent_indexes.add()
            p_index_item.value = ui_tree_item.parent_index
            for item in parent_item.all_parent_indexes:
                p_index_item :IntItem = ui_tree_item.all_parent_indexes.add()
                p_index_item.value = item.value
            ui_tree_item.all_parent_count = len(ui_tree_item.all_parent_indexes)

            ui_tree_item.parent_full_data_path = parent_item.full_data_path
            # Item is not visible in list if parent is not expanded
            ui_tree_item.hidden = not parent_item.expanded
            ui_tree_item.child_index = child_index

        ui_tree_item.set_data(data)
        self.set_ui_tree_item_name(ui_tree_item, data)

        # Restore checked state
        ui_tree_item.checked = self.is_data_checked(data)
        # Restore expanded state
        ui_tree_item.expanded = ui_tree_item.name in self._expanded_items

        # Process item children
        children_data = self.get_data_children(data)
        ui_tree_item.children_count = len(children_data)

        children_range_start = len(ui_tree_collection)
        if self.ALPHABETICAL_ORDER:
            children_data = sorted(
                children_data, 
                key=lambda s: self.get_name_for_alpha_order(s).lower(), 
                reverse=False
            )

        for i, child_data in enumerate(children_data):
            self._create_tree_item_from_data(
                data=child_data,
                parent_item_index=item_index,
                child_index=i,
            )
        # Be carefull here, do not use ui_tree_item reference after adding new items in collection
        # This is likely to crash, as internal code may re-allocate
        # the whole container (the collection) memory at some point.

        # In our case, this caused 'item.all_children_count' to be randomly reset because
        # ui_tree_item was pointing to a stale RNA struct after children were added.
        # Always re-fetch the item from the collection after modifying it.
        ui_tree_item = ui_tree_collection[item_index]
        if ui_tree_item.children_count:
            # Get range of item children
            children_range_end = len(ui_tree_collection)

            ui_tree_item.all_children_count = children_range_end - children_range_start

    def _generate_ui_tree_items(self, data_collection: Iterable):
        """
        Generate UI Items from data_collection prop.
        Process entire hierarchy with children items.
        """
        for data in data_collection:
            self._create_tree_item_from_data(data)

    # region Multi Edit Properties
    @contextmanager
    def multi_edit_properties_disabled(self):
        """Temporarily disable multi-edit property synchronization.
        Use this when multi-selection is enabled and you are planning to modify the data collection.
        """

        before_state = self.disable_multi_edit
        self.disable_multi_edit = True
        try:
            yield
        finally:
            self.disable_multi_edit = before_state

    @staticmethod
    def _get_nested_attr(obj: Any, prop_path: str) -> Any:
        """Get nested attribute value.
            example : obj.my_attr_.nested_attrib
            """
        parts = prop_path.split(".")
        value = obj
        for part in parts:
            value = getattr(value, part)

        return value

    @staticmethod
    def _set_nested_attr(
        obj: Any, 
        prop_path: str, 
        value: Any, 
        trigger_update: bool = False
    ):
        """Set nested attribute..
        example : obj.my_attr_.nested_attrib
        """
        parts = prop_path.split(".")
        prop = obj
        for part in parts[:-1]:

            prop = getattr(prop, part)

        if trigger_update:
            setattr(prop, parts[-1], value)
        else:
            prop[parts[-1]] = value

    @staticmethod
    def _update_prop_on_selected_data(
        tree_manager_name: str,
        prop_path: str,
        full_data_path: str,
        trigger_update: bool = True,
    ):
        """
        Do not directly used this function. It is called bpy.msgbus on notify event.

        Update data property on selected items data except active.
        Only update if active item is in selected items list.
        Update only if item data class is identical to active_data class.
        """
        tree_manager = TreeManager.get_tree_manager_instance(tree_manager_name)
        if not tree_manager:
            return
        active_data = None
        try:
            active_data = eval(full_data_path)
        except:
            return
        if active_data is None:
            return

        if tree_manager.disable_multi_edit or tree_manager._updating_props:
            return
        if not tree_manager._has_multiselection:
            return
        tree_manager._updating_props = True

        # Check if item being edited is part of selection
        active_data_in_selection = False
        selected_items = tree_manager.get_selected_items()
        for item in selected_items:
            data = item.get_data()
            if data != active_data:
                continue
            active_data_in_selection = True
            break

        if not active_data_in_selection:
            tree_manager._updating_props = False
            return

        for item in selected_items:
            data = item.get_data()

            if data == active_data:
                continue

            if not isinstance(data,type(active_data)):
                continue

            try:
                before_value = TreeManager._get_nested_attr(data, prop_path)
                value = TreeManager._get_nested_attr(active_data, prop_path)
                if before_value == value:

                    continue

                # Can trigger property update functions
                TreeManager._set_nested_attr(data, prop_path, value, trigger_update)

            except :
                pass
        tree_manager._updating_props = False

    @staticmethod
    def _check_for_data_reallocation(
        tree_manager_name: str,
        instance_full_data_path: str,
        first_instance_pointer: str,
    ) -> bool:
        """
        Check if data pointer has changed.
        """

        tree_manager = TreeManager.get_tree_manager_instance(tree_manager_name)
        if not tree_manager:
            return False
        instance = None
        try:
            instance = eval(instance_full_data_path)
        except:
            return False

        if not instance:
            return False
        instance: bpy.types.ID
        pointer = None
        try:
            pointer = instance.as_pointer()
        except:
            return False

        return pointer != first_instance_pointer

    def ensure_subscription_to_multi_edit_props(self):
        """
        Make sure that callbacks to edit properties on selected items are
        correctly set.

        If not done, callbacks may not be called since they can associated
        with old data pointers.
        """
        if not self._reallocation_checker_args:
            return

        for args in self._reallocation_checker_args:
            if self._check_for_data_reallocation(*args):
                # First instance of this class pointer has changed.
                # It means that past subscribe_rna() are now invalid.
                # We need to subscribe again.
                self.subscribe_to_multi_edit_properties()
                break

    def subscribe_to_multi_edit_properties(self):
        """
        Enable synchronized editing of properties across all selected items.

        Uses bpy.msgbus to notify the tree manager when an item data property
        is modified, allowing updates to propagate to all selected objects.

        Be careful when updating these properties outside of the UIList context.
        Notifications can be triggered when a property is changed via Python.

        Unlike properties update callbacks, message bus update callbacks are postponed until all operators have finished executing.
        You may have to force property notify in this case with bpy.msgbus.publish_rna

        More infos here: https://docs.blender.org/api/current/bpy.msgbus.html#module-bpy.msgbus
        """
        if not (self.MULTISELECTION_SUPPORT and self.MULTI_EDIT_PROPERTIES):
            return
        owner = type(self)

        bpy.msgbus.clear_by_owner(owner)

        instantiated_classes = set()
        self._reallocation_checker_args = []
        for data_class, properties in self.MULTI_EDIT_PROPERTIES.items():
            first_instance = None
            first_instance_data_path = None
            for tree_item in self.get_ui_tree_collection():
                first_instance = tree_item.get_data()
                first_instance_data_path = tree_item.full_data_path
                if isinstance(first_instance, data_class):
                    break
            if not (first_instance and first_instance_data_path):
                continue
            instantiated_classes.add(data_class)

            # Store args to later check if first instance pointer changed later
            self._reallocation_checker_args.append(
                (
                    self.unique_name,
                    first_instance_data_path,
                    first_instance.as_pointer(),
                )
            )

        if not instantiated_classes:
            return

        # Subscribe to instances
        for data_class, properties in self.MULTI_EDIT_PROPERTIES.items():
            if data_class not in instantiated_classes:
                continue
            for tree_item in self.get_ui_tree_collection():
                data = tree_item.get_data()
                if not isinstance(data, data_class):
                    continue
                for prop_path in properties:
                    bpy.msgbus.subscribe_rna(
                        key=data.path_resolve(prop_path, False),
                        owner=owner,
                        args=(self.unique_name, prop_path, tree_item.full_data_path),
                        notify=TreeManager._update_prop_on_selected_data,
                    )
    # endregion
    def generate_ui_tree_collection(self):
        """
        Generate a flat collection of UITreeItem
        from data_collection_prop.
        Preserve expanded state of UITreeItems using names.
        """
        self._expanded_items = self.get_expanded_items()
        # We need to clear the list used to draw items in the ui
        ui_tree_collection = self.get_ui_tree_collection()
        ui_tree_collection.clear()
        data_collection = self.get_data_collection()
        if self.ALPHABETICAL_ORDER:
            data_collection = sorted(
                data_collection, 
                key=self.get_name_for_alpha_order, 
                reverse=False
            )
        self._generate_ui_tree_items(data_collection)
        self.subscribe_to_multi_edit_properties()
        self._expanded_items = []

    def clear_ui_collection(self):
        ui_tree_collection = self.get_ui_tree_collection()
        ui_tree_collection.clear()

    def expand_ui_tree_item(
        self,
        expand: bool,
        item_index: int, 
        set_active: bool = False,
        update_selection: bool = False
    ) :
        """
        Set expand state of UITreeItem

        Args:
            expand: Wanted expand state.
            item_index: Index of item to expand.
            set_active: Set active item to preserve UIList scrolling. Defaults to False.
            update_selection: Triggers active index property update.
        Return:
            Return True if ui_tree_collection_prop len changed.
        """
        item: TreeItem
        item_list = self.get_ui_tree_collection()
        item = item_list[item_index]
        data = item.get_data()
        if not data:
            print(f"Item {str(item)} has no data.")
            return

        if item.expanded and expand:
            return

        if not item.expanded and not expand:
            return

        item.expanded = expand
        if item.children_count == 0:
            return

        expanded_parent_items = set([item_index])
        for i in range(item_index + 1, len(item_list)):
            try:
                child_item = item_list[i]
            except:
                break
            if child_item.parent_index in expanded_parent_items:

                parent_item = item_list[child_item.parent_index]
                if not expand:
                    # When collapsing all children even nested ones should be hidden
                    child_item.hidden = True
                    expanded_parent_items.add(i)  
                else:
                    # When expanding, only children with expanded parent should be visible
                    child_item.hidden = not parent_item.expanded 
                    if parent_item.expanded:
                        expanded_parent_items.add(i)
            else:
                break

        if set_active:
            self.set_ui_tree_active_index(item_index, update_selection)

    def get_active_item(self) -> TreeItem | None:
        ui_tree_collection_prop = self.get_ui_tree_collection()
        active_index = self._get_ui_tree_active_index()
        if active_index < 0: # if -1, means not active index set
            return None
        try:
            active_item = ui_tree_collection_prop[active_index]
            return active_item
        except IndexError:
            return None

    # region MultiSelection
    def save_flt_flags(self, flt_flags):
        self._flt_flags = flt_flags

    def item_visible_after_ui_filter(self, item: TreeItem)->bool:
        """
        Is an item visible after UIList filtering.
        """
        if not self._flt_flags:
            return True
        try:
            if self._flt_flags[item.index] : 
                return True
            return False
        except:
            return True

    def unselect_all(self):
        item_collection = self.get_ui_tree_collection()
        for item in item_collection:
            item:TreeItem
            item.selected = False

        self._has_multiselection = False
        if self.on_selection_function:
            self.on_selection_function(self, bpy.context) # type: ignore
        self.set_ui_tree_active_index(None)

    def select_all_visible(self):
        item_collection = self.get_ui_tree_collection()
        for item in item_collection:
            item:TreeItem
            if self.item_visible_after_ui_filter(item):
                item.selected = True
        active_index = self._get_ui_tree_active_index()
        if len(item_collection) and active_index < 0:
            self.set_ui_tree_active_index(0, update_selection=False)

        self.update_has_multiselection_state()
        if self.on_selection_function:
            self.on_selection_function(self, bpy.context)  # type: ignore

    def update_has_multiselection_state(self):
        selected_items = self.get_selected_items()
        self._has_multiselection = len(selected_items) > 1

        # If one item is selected but active item is not,
        # then multiselection is considered enabled.
        active_item = self.get_active_item()
        if not active_item:
            return
        if not active_item.selected and len(selected_items):
            self._has_multiselection = True

    def get_selected_items(self)->list[TreeItem]:
        """
        Must be launched after update_selected_items() 
        if you want to get up to date list.
        """
        ui_tree_collection_prop = self.get_ui_tree_collection()
        selected_items = []
        for item in ui_tree_collection_prop:
            if item.selected :
                selected_items.append(item)
        return selected_items

    def update_selected_items(self):
        """
        This must be called when user set active item in hierarchy
        in order to update items selection state.
        """
        old_active_index = self._get_ui_old_tree_active_index()
        active_index = self._get_ui_tree_active_index()
        if old_active_index != -1:

            bpy.ops.treeview.set_items_selection(
                "INVOKE_DEFAULT",
                old_active_index=old_active_index,
                new_active_index=active_index,
                tree_manager_name=self.unique_name
            )
        # Get Active index again, it can change during items selection
        active_index = self._get_ui_tree_active_index()
        self._set_ui_old_tree_active_index(active_index)

    def check_all(self, checked: bool = True, visible_only: bool = True):
        item_collection = self.get_ui_tree_collection()
        for item in item_collection:
            item: TreeItem
            if visible_only and not self.item_visible_after_ui_filter(item):
                continue
            item.checked = checked

    def get_checked_items(self)->list[TreeItem]:
        if not self.CHECKABLE_ITEMS:
            return []
        ui_tree_collection_prop = self.get_ui_tree_collection()
        checked_items = []
        for item in ui_tree_collection_prop:
            if item.checked :
                checked_items.append(item)
        return checked_items

    # endregion

    # region Register

    def register(
        self
    ):
        """
        Register all necessary properties (ui tree collection, ui tree active index etc).
        Link TreeManager with provided UL_TreeView.
        """
        self.ul_tree_view_class.tree_manager_name = self.unique_name

        self.ui_tree_prop_name = f"{self.unique_name}_ui_tree"
        self.active_index_prop_name = f"{self.unique_name}_active_index"
        self.old_active_index_prop_name = f"{self.unique_name}_old_active_index"

        # Import here to avoid circular import
        from _addons_common.ui.tree_widget.item import TreeItem
        setattr(
            bpy.types.Scene,
            self.ui_tree_prop_name,
            bpy.props.CollectionProperty(type=TreeItem),
        )

        # Store UI related prop in window manager for better UI Performance.
        # WARNING: these are not saved !
        # In big scenes, properties stored in bpy.types.Scene can cause slow down since it can trigger various updates on access.
        # For example msfs_ui_active_index can freeze template_list on click if it is a bpy.types.Scene property

        if self.MULTISELECTION_SUPPORT:
            # Default multi selection function
            def on_update(_self, context):
                self.update_selected_items()

            if self.on_selection_function:

                def on_update(_self, context):
                    self.update_selected_items()
                    self.on_selection_function(self, context) # type: ignore
            setattr(
                bpy.types.WindowManager,
                self.active_index_prop_name,
                bpy.props.IntProperty(
                    name="Active item", 
                    default=0, 
                    update=on_update
                ),
            )
            setattr(
                bpy.types.WindowManager,
                self.old_active_index_prop_name,
                bpy.props.IntProperty(default=0),
            )

        else:
            on_update = None
            if self.on_selection_function:
                def on_update(_self, context):
                    self.on_selection_function(self, context) # type: ignore

            setattr(
                bpy.types.WindowManager,
                self.active_index_prop_name,
                bpy.props.IntProperty(
                    name="Active item",
                    default=0,
                    update=on_update
                ),
            )

        self.ul_tree_view_class.register()

    def unregister(self):
        self.ul_tree_view_class.unregister()
        try:
            TreeManager.tree_manager_instances.pop(self.unique_name)
            delattr(bpy.types.Scene, self.ui_tree_prop_name)
            delattr(bpy.types.WindowManager, self.active_index_prop_name)
            delattr(bpy.types.WindowManager, self.old_active_index_prop_name)

        except Exception:
            pass
    # endregion


# endregion
