"""FSS Blender Tools: authoring checks and helpers for the Flight Sim Studio E-Jet.

Independent of the Asobo add-ons and of _addons_common, so upstream merges into the exporter stay conflict-free.
"""

bl_info = {
    "name": "FSS Blender Tools",
    "author": "Flight Sim Studio",
    "description": "Authoring checks and helpers for MSFS aircraft (name check, empty bounds)",
    "blender": (5, 2, 0),
    "version": (0, 2, 0),
    "location": "3D View > Sidebar > FSS Tools",
    "category": "Object",
}

if "name_check" in locals():
    import importlib
    name_check = importlib.reload(name_check)
    empty_bounds = importlib.reload(empty_bounds)
else:
    from . import empty_bounds, name_check

MODULES = (name_check, empty_bounds)


def register():
    for module in MODULES:
        module.register()


def unregister():
    for module in reversed(MODULES):
        module.unregister()
