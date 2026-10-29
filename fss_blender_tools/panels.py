"""Sidebar group UV Tools (Seams, Packing with Visibility Scoring). The group holds nothing of its own; each section is
a subpanel registered by its module, after this one.

Every panel of the add-on is in the 3D Viewport sidebar tab FSS MSFS Tools (material-management decision 15), where
bl_order sets the order: Zones & Merge Tree (merge.py), Materials (materials.py), Tags (tags.py), LOD (lod.py),
UV Tools (this module), General (tools.py), Empty Bounds (empty_bounds.py), Heatmap (uv_heatmap.py), Checks
(checks.py). The UV Editor's Packing panel is in a tab FSS MSFS Tools too.
"""

import bpy


class FSS_PT_UvTools(bpy.types.Panel):
    bl_idname = 'FSS_PT_uv_tools'
    bl_label = 'UV Tools'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'FSS MSFS Tools'
    bl_order = 4

    def draw(self, context):
        pass


CLASSES = (FSS_PT_UvTools,)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
