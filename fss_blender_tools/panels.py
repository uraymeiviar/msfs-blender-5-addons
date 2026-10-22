"""Sidebar groups: UV Tools (Seams, Packing with Visibility Scoring) and Utilities (General, Empty Bounds, Heatmap,
Checks). The groups hold nothing of their own; each section is a subpanel registered by its module, after this one.

bl_order sets the order of the FSS Tools tab: Zones & Merge Tree, Tags, LOD, UV Tools, Utilities.
"""

import bpy


class FSS_PT_UvTools(bpy.types.Panel):
    bl_idname = 'FSS_PT_uv_tools'
    bl_label = 'UV Tools'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'FSS Tools'
    bl_order = 3

    def draw(self, context):
        pass


class FSS_PT_Utilities(bpy.types.Panel):
    bl_idname = 'FSS_PT_utilities'
    bl_label = 'Utilities'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'FSS Tools'
    bl_order = 4

    def draw(self, context):
        pass


CLASSES = (FSS_PT_UvTools, FSS_PT_Utilities)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
