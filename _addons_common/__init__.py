"""
Asobo addons utilities.

WARNING :
Package starts with a "_" so it is loaded first.
So do not rename this addon.
"""
import builtins

# from .reload import reload_addon

# reload_addon(__name__)
# import bpy
# bl_info = {
#     "name": "Microsoft Flight Simulator 2024: Addons Utils",
#     "module_name": "_addons_utils",  
#     "author": "Asobo Studio (ykhodja and mrichecoeur)",
#     "description": "This toolkit set up your Microsoft Flight Simulator 2024 addons\n",
#     "location": "",
#     "blender": (3, 3, 0),
#     "version": (0, 0, 1),
#     "category": "",
#     "doc_url": "",
# }

# region ######################### REGISTRATION #################################
from .registration import Registration

# Prevents blender to load this package two times
_SENTINEL = "_addons_utils_loaded"
RG = None
if not getattr(builtins, _SENTINEL, False):
    setattr(builtins, _SENTINEL, True)

    RG = Registration(
        file=__file__,
        package=__package__
    )
    RG.register()

def _pre_reload_cleanup():
    """
    Internal use only. 
    Used by addon reloader to force unregister 
    and mark package as unloaded before reload.
    """
    setattr(builtins, _SENTINEL, False)
    if not RG:
        return
    try:
        RG.unregister()
    except:
        pass

# def register():
#     print("Registering msfs_addons_utils...")
#     RG.register()

# def unregister():
#     print("Unregistering msfs_addons_utils...")
#     RG.unregister()

# endregion
