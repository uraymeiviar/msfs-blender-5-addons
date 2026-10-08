from _addons_common.reload import reload_addon
reload_addon(__name__)

import bpy

bl_info = {
    "name": "Microsoft Flight Simulator 2024: 3ds Max Bridge",
    "author": "Asobo Studio (Mathieu Richecoeur)",
    "version": (1, 0, 0),
    "blender": (3, 6, 0),
    "description": "Add MSFS 2024 Bridge Preset to add-on 'Asobo: 3ds Max Bridge'",
    "location": "View3D > Tool Shelf > 3ds Max Bridge",
    "warning": "",
    "doc_url": "",
    "category": "Tools",
}

# region ######################### REGISTRATION #################################
from _addons_common.registration import Registration

RG = Registration(
    file=__file__,
    package=__package__
)


def register():
  
    # Check if max_bridge_asobo is accessible
    import importlib.util
    base_bridge_package = "max_bridge_asobo"
    spec = importlib.util.find_spec(base_bridge_package)
    if not spec:
        print("Skip Register of 'Microsoft Flight Simulator 2024: 3ds Max Bridge'" 
              "since Add-On 'Asobo: 3ds Max Bridge' was not found.")
        return
    
    import addon_utils
    # Enabled add-on 'Asobo: 3ds Max Bridge' if it is not enabled by default
    loaded_default, loaded_state = addon_utils.check(base_bridge_package)
    if not loaded_default:
        addon_utils.enable(base_bridge_package, default_set=True)
        print("Enable Add-On 'Asobo: 3ds Max Bridge'")
    RG.register()

def unregister():
    RG.unregister()
    
# endregion
