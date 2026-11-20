"""Polygone: mesh reduction of the selected objects with libPolygone (H:/git-repos/libPolygone).

The add-on is the UI only: it passes each mesh as flat arrays to the library's DLL (lib/windows-x64/polygone.dll,
loaded with ctypes) and builds the reduced mesh from what the DLL returns. Independent of the other add-ons here.
"""

bl_info = {
    "name": "Polygone",
    "author": "Flight Sim Studio",
    "description": "Mesh reduction of the selected objects with libPolygone: feature lines, locks, importance, "
                   "UVs, normals and colours kept",
    "blender": (5, 2, 0),
    "version": (0, 2, 0),
    "location": "3D View > Sidebar > Polygone",
    "category": "Mesh",
}

if "ui" in locals():
    import importlib
    native = importlib.reload(native)
    mesh_io = importlib.reload(mesh_io)
    ui = importlib.reload(ui)
else:
    from . import native, mesh_io, ui


def register():
    ui.register()


def unregister():
    ui.unregister()
