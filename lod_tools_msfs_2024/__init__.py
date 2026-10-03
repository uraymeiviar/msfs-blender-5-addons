from _addons_common.reload import reload_addon
reload_addon(__name__)

from pathlib import Path

DOC = (Path(__file__).parent/"documentation.html").as_posix()

bl_info = {
    "name": "Microsoft Flight Simulator 2024: LOD Tools",
    "description": "LOD Setup and Visualization",
    "author": "Asobo Studio (Mathieu Richecoeur)",
    "version": (1, 0, 0),
    "blender": (3, 6, 0),
    "location": "View3D > Tool Shelf > Microsoft Flight Simulator Tools > LOD Tools",
    "warning": "",
    "wiki_url": "",
    "tracker_url": "",
    "category": "3D View",
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
