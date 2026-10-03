"""
Registration utilities.

Classes can define a `register_order` attribute (int) to control the order in which they are registered.
This is particularly useful for panels with a parent panel defined by `bl_parent_id`.

To skip registration entirely, set a `skip_register` attribute on the class.
"""

import bpy
import importlib
import inspect
import pkgutil

from pathlib import Path

class Registration:

    def __init__(self, file: str, package: str):
        """
        Args:
            file (str): Path of module file
            package (str): Name of the package of the module
        """
        self.__file = file
        self.__package = package

        self._modules = []
        self._classes = {}

    def _recursive_module_search(self, path: str, root: str = ""):
        """ Recursively search for all modules in a given path """
        for _, module_name, ispkg in pkgutil.iter_modules([str(path)]):
            if ispkg:
                yield from self._recursive_module_search(
                    path / module_name,
                    f"{root}.{module_name}"
                )
            else:
                yield root, module_name

        # Ensure to include __init__.py modules
        yield root, "__init__"

    def _update_module_list(self):
        """ Refresh the list of modules """
        self._modules.clear()

        parent_path = Path(self.__file).parent
        for root, module_name in self._recursive_module_search(parent_path):
            self._modules.append(
                importlib.import_module(
                    f".{module_name}",
                    package=f"{self.__package}{root}"
                )
            )

    def _update_class_list(self):
        """ Refresh the list of classes """
        self._classes.clear()
        _found_classes = set()
        for md in self._modules:
            for obj in md.__dict__.values():
                if not (
                    inspect.isclass(obj) 
                    and md.__name__ in str(obj) 
                    and "bpy" in str(inspect.getmro(obj)[1])
                ):
                    continue
                
                if obj in _found_classes:
                    # Prevent register multiple times
                    continue

                _found_classes.add(obj) 

                if hasattr(obj, "skip_register") and obj.skip_register:
                    continue
                
                order_index = 0
                if (
                    hasattr(obj, "register_order") 
                    and isinstance(obj.register_order, int)
                ):
                    order_index = obj.register_order
                    
                classes_list = self._classes.get(order_index)
                
                if classes_list:
                    classes_list.append(obj)
                else:
                    self._classes[order_index] = [obj]

    def _is_package_init_module(self, md):
        """ Check if a module is the __init__.py of the package of the instance """
        return (
            Path(md.__file__).stem == "__init__"
            and md.__package__ == self.__package
        )

    def set_file(self, file):
        """ Set the file path of the module """
        self.__file = file

    def set_package(self, package):
        """ Set the package name of the module """
        self.__package = package

    def register(self):
        """ Register all classes and modules """
        self._update_module_list()

        # Refresh the list of classes whenever the addon is reloaded
        # So we can stay up to date with the files on disk.
        self._update_class_list()

        # Always register modules after classes
        # Some props have classes as types
        for _, classes in sorted(self._classes.items()):
            for cls in classes:
                try:
                    bpy.utils.register_class(cls)
                except (ValueError, RuntimeError) as e:
                    print(
                        f"Failed to register {cls},"
                        " you may need to define register_order in class."
                    )
                    print(f"Error: {e}")
                    

        for md in self._modules:
            if self._is_package_init_module(md):
                continue

            if hasattr(md, "register"):
                md.register()
    
    def unregister(self):
        """ Unregister all classes and modules """
        for _, classes in sorted(self._classes.items()):
            for cls in classes:
                try:
                    bpy.utils.unregister_class(cls)
                except (ValueError, RuntimeError) as e:
                    print(f"Failed to unregister {cls}")
                    print(f"Error: {e}")
                    

        for md in self._modules:
            if self._is_package_init_module(md):
                continue

            if hasattr(md, "unregister"):
                md.unregister()
