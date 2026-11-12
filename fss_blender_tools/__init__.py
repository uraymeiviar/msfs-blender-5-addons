"""FSS Blender Tools: authoring checks and helpers for the Flight Sim Studio E-Jet.

Independent of the Asobo add-ons and of _addons_common, so upstream merges into the exporter stay conflict-free.
"""

bl_info = {
    "name": "FSS Blender Tools",
    "author": "Flight Sim Studio",
    "description": "Authoring checks and helpers for MSFS aircraft (zones and merge tree, materials and texture sets, tags, lod, uv tools: seams, packing per texture set with its marks, visibility scoring; ao bake: masters in a second Blender, applied to textures; in a second tab: general tools, empty bounds, heatmap, checks)",
    "blender": (5, 2, 0),
    "version": (0, 55, 1),
    "location": "3D View > Sidebar > FSS MSFS Tools, FSS Tools (General, Empty Bounds, Heatmap, Checks); UV Editor > Sidebar > FSS MSFS Tools (Packing)",
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
    uv_fill = importlib.reload(uv_fill)
    uv_pack = importlib.reload(uv_pack)
    uv_marks = importlib.reload(uv_marks)
    uv_problems = importlib.reload(uv_problems)
    uv_islands = importlib.reload(uv_islands)
    texture_sets = importlib.reload(texture_sets)
    materials = importlib.reload(materials)
    uv_autoseam = importlib.reload(uv_autoseam)
    uv_heatmap = importlib.reload(uv_heatmap)
    visibility_core = importlib.reload(visibility_core)
    visibility = importlib.reload(visibility)
    name_check = importlib.reload(name_check)
    checks = importlib.reload(checks)
    autorefresh = importlib.reload(autorefresh)
    ao_bake_core = importlib.reload(ao_bake_core)
    ao_bake_store = importlib.reload(ao_bake_store)
    ao_bake_apply = importlib.reload(ao_bake_apply)
    ao_bake = importlib.reload(ao_bake)
else:
    from . import (ao_bake, ao_bake_apply, ao_bake_core, ao_bake_store, autorefresh, checks, empty_bounds, lod_rules, lod_model, lod, materials, merge, name_check, panels, tags, texture_sets,
                   tools, uv_autoseam, uv_fill, uv_heatmap, uv_islands, uv_marks, uv_pack, uv_problems, visibility,
                   visibility_core)

# panels first: it documents the sidebar layout (it registers no panel since UV Tools was dissolved)
MODULES = (panels, tools, empty_bounds, lod, tags, merge, uv_marks, uv_problems, uv_islands, materials, texture_sets, uv_autoseam, uv_heatmap, visibility, ao_bake, name_check,
           checks, autorefresh)

# The glTF exporter looks this name up on every enabled add-on: merge groups are merged in its pre-export hook
glTF2ExportUserExtension = merge.glTF2ExportUserExtension


def register():
    for module in MODULES:
        module.register()


def unregister():
    for module in reversed(MODULES):
        module.unregister()
