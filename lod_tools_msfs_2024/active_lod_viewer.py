import bpy

from lod_tools_msfs_2024 import data_utils, lod_viewer
from lod_tools_msfs_2024.constants import IS_BLENDER_5_2_OR_SUP
from _addons_common import geometry_node_utils
class ActiveLODViewer():
    valid_lod_viewer: bool = False
    object: bpy.types.Object | None = None
    modifier : bpy.types.Modifier | None = None
    lod_count: int = 0
    lod_viewer_input_map: dict | None = None # used only on blender < 5.2

    @classmethod
    def reset(cls):
        cls.valid_lod_viewer = False
        cls.modifier = None
        cls.lod_count = 0
        cls.lod_viewer_input_map = None

def on_active_changed(active_object: bpy.types.Object | None):

    ActiveLODViewer.valid_lod_viewer = False
    if not active_object:
        ActiveLODViewer.reset()
        return
    if not data_utils.data_is_valid(active_object):
        return
    ActiveLODViewer.object = active_object
    ActiveLODViewer.modifier = lod_viewer.get_lod_viewer_modifier(active_object)
    if not ActiveLODViewer.modifier:
        return
    
    if not IS_BLENDER_5_2_OR_SUP:
        ActiveLODViewer.lod_viewer_input_map = lod_viewer.lod_viewer_node_groups.get_lod_viewer_input_map()
    
    

    lod_count = geometry_node_utils.get_modifier_input_value(
        ActiveLODViewer.modifier,
        lod_viewer.MSFS2024LODViewerInputs.LOD_COUNT.input_label,
    )
    if lod_count is geometry_node_utils.NotFound:
        return
    ActiveLODViewer.lod_count = lod_count
    ActiveLODViewer.valid_lod_viewer = True
