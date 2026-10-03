import sys
import importlib

def reload_addon(addon_name):
    """ 
        Reload the addon modules if bpy is available. \n
        WARNING: This function must be called at the top of 
        the __init__.py file of the addon before any import of the bpy module.
    """
    if "bpy" not in locals():
        return
    
    current_package_prefix = f"{addon_name}."
    for name, module in sys.modules.copy().items():
        if name.startswith(current_package_prefix):
            print(f"Reloading {name}")
            importlib.reload(module)
