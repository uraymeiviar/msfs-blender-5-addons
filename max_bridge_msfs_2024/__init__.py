from _addons_common.reload import reload_addon
reload_addon(__name__)

bl_info = {
    "name": "Microsoft Flight Simulator 2024: 3ds Max Bridge",
    "author": "Asobo Studio (Mathieu Richecoeur)",
    "version": (1, 0, 0),
    "blender": (3, 6, 0),
    "description": "Transfer 3D Models between 3ds Max and Blender.",
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
    RG.register()

def unregister():
    RG.unregister()
    
# endregion
