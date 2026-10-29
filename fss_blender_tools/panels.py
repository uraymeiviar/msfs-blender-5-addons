"""Sidebar layout of fss_blender_tools; this module registers no panel of its own.

The add-on has two 3D Viewport sidebar tabs (material-management decisions 16 and 26), where bl_order sets the order of
the top-level panels. FSS MSFS Tools: Zones & Merge Tree (merge.py), Materials (materials.py), Tags (tags.py), Object
LOD, Viewport LOD and LOD Settings (lod.py), UV Auto Seam (uv_autoseam.py), UV Auto Packing with Visibility Scoring
inside it (uv_marks.py, visibility.py). FSS Tools: General (tools.py), Empty Bounds (empty_bounds.py), Heatmap
(uv_heatmap.py), Checks (checks.py). The UV Editor's UV Auto Packing panel is in a tab FSS MSFS Tools.
"""

CLASSES = ()


def register():
    pass


def unregister():
    pass
