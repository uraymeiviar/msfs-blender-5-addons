"""FSS Blender Tools: authoring checks and helpers for the Flight Sim Studio E-Jet.

Independent of the Asobo add-ons and of _addons_common, so upstream merges into the exporter stay conflict-free.
"""

bl_info = {
    "name": "FSS Blender Tools",
    "author": "Flight Sim Studio",
    "description": "Authoring checks and helpers for MSFS aircraft (tools, empty bounds, tags, merge tree, checks)",
    "blender": (5, 2, 0),
    "version": (0, 9, 1),
    "location": "3D View > Sidebar > FSS Tools",
    "category": "Object",
}

if "name_check" in locals():
    import importlib
    tools = importlib.reload(tools)
    empty_bounds = importlib.reload(empty_bounds)
    tags = importlib.reload(tags)
    merge = importlib.reload(merge)
    name_check = importlib.reload(name_check)
    checks = importlib.reload(checks)
else:
    from . import checks, empty_bounds, merge, name_check, tags, tools

MODULES = (tools, empty_bounds, tags, merge, name_check, checks)

# The glTF exporter looks this name up on every enabled add-on: merge groups are merged in its pre-export hook
glTF2ExportUserExtension = merge.glTF2ExportUserExtension


def register():
    for module in MODULES:
        module.register()


def unregister():
    for module in reversed(MODULES):
        module.unregister()
