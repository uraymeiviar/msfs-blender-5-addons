"""FSS Blender Tools: authoring checks and helpers for the Flight Sim Studio E-Jet.

Independent of the Asobo add-ons and of _addons_common, so upstream merges into the exporter stay conflict-free.
"""

bl_info = {
    "name": "FSS Blender Tools",
    "author": "Flight Sim Studio",
    "description": "Authoring checks and helpers for MSFS aircraft (zones and merge tree, tags, lod, uv tools: seams, packing per texture set with its marks, visibility scoring; utilities: general tools, empty bounds, heatmap, checks)",
    "blender": (5, 2, 0),
    "version": (0, 32, 0),
    "location": "3D View > Sidebar > FSS Tools",
    "category": "Object",
}

if "name_check" in locals():
    import importlib
    panels = importlib.reload(panels)
    tools = importlib.reload(tools)
    empty_bounds = importlib.reload(empty_bounds)
    lod_rules = importlib.reload(lod_rules)
    lod_model = importlib.reload(lod_model)
    lod = importlib.reload(lod)
    tags = importlib.reload(tags)
    merge = importlib.reload(merge)
    uv_pack = importlib.reload(uv_pack)
    uv_marks = importlib.reload(uv_marks)
    uv_autoseam = importlib.reload(uv_autoseam)
    uv_heatmap = importlib.reload(uv_heatmap)
    visibility_core = importlib.reload(visibility_core)
    visibility = importlib.reload(visibility)
    name_check = importlib.reload(name_check)
    checks = importlib.reload(checks)
else:
    from . import (checks, empty_bounds, lod_rules, lod_model, lod, merge, name_check, panels, tags, tools, uv_autoseam,
                   uv_heatmap, uv_marks, uv_pack, visibility, visibility_core)

# panels first: it registers the UV Tools and Utilities groups that the other modules' panels sit in
MODULES = (panels, tools, empty_bounds, lod, tags, merge, uv_marks, uv_autoseam, uv_heatmap, visibility, name_check, checks)

# The glTF exporter looks this name up on every enabled add-on: merge groups are merged in its pre-export hook
glTF2ExportUserExtension = merge.glTF2ExportUserExtension


def register():
    for module in MODULES:
        module.register()


def unregister():
    for module in reversed(MODULES):
        module.unregister()
