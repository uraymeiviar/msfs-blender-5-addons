from enum import Enum

import bpy

from lod_tools_msfs_2024.datafiles.asset_library import NodeGroupLibrary
from lod_tools_msfs_2024 import data_properties
from lod_tools_msfs_2024.constants import IS_BLENDER_5_2_OR_SUP
from _addons_common import geometry_node_utils

LOD_VIEWER_INPUT_MAP = {}

class LODViewerConstantsNodes(Enum):
    CAMERA_OBJECT_INFO = "Camera Object info"
    FOV_Y = "Fov Y"
    LOD_FACTOR = "LOD Factor"
    DISPLAY_BOUNDING_SPHERE = "Display Bounding Sphere"
    FORCE_ACTIVE_LOD = "Force Active LOD"
    ACTIVE_LOD_INDEX = "Active LOD Index"

def get_scene_lod_viewer_constants_group(scene: bpy.types.Scene)->bpy.types.NodeGroup | None:
    # We should only have one lod_viewer_constant node groupe per scene
    lod_viewer_prop = data_properties.get_msfs_lod_viewer_prop(scene)
    if not lod_viewer_prop:
        return None
    
    return lod_viewer_prop.lod_viewer_constants_node_group

def get_scene_lod_viewer_group(scene: bpy.types.Scene)->bpy.types.NodeGroup | None:
    # We should only have one lod_viewer node groupe per scene
    lod_viewer_prop = data_properties.get_msfs_lod_viewer_prop(scene)
    if not lod_viewer_prop:
        return None
    
    return lod_viewer_prop.lod_viewer_node_group

def get_first_lod_viewer_group()->bpy.types.NodeGroup | None:
    """Get the first lod_viewer_group node_group found in bpy.data
    """
    return bpy.data.node_groups.get(NodeGroupLibrary.LOD_VIEWER.id_name)

def set_lod_factor(lod_viewer_constants: bpy.types.NodeGroup, lod_factor: float)->bool:
    lod_factor_node: bpy.types.GeometryNodeObjectInfo | None = (
        lod_viewer_constants.nodes.get(LODViewerConstantsNodes.LOD_FACTOR.value)
    )
    if not lod_factor_node:
        return False
    geometry_node_utils.set_node_output_default_value(lod_factor_node, lod_factor)
    return True 

def set_fov_y(lod_viewer_constants: bpy.types.NodeGroup, fov_y: float)->bool:
    fov_y_node: bpy.types.GeometryNodeObjectInfo | None = (
        lod_viewer_constants.nodes.get(LODViewerConstantsNodes.FOV_Y.value)
    )
    if not fov_y_node:
        return False
    geometry_node_utils.set_node_output_default_value(fov_y_node, fov_y)
    return True 

def set_display_bpshere(lod_viewer_constants: bpy.types.NodeGroup, display_bsphere: bool)->bool:
    display_bounding_sphere_node: bpy.types.FunctionNodeInputBool | None = (
        lod_viewer_constants.nodes.get(
            LODViewerConstantsNodes.DISPLAY_BOUNDING_SPHERE.value
        )
    )
    if not display_bounding_sphere_node:
        return False
    geometry_node_utils.set_boolean_node_value(display_bounding_sphere_node, display_bsphere)
    return True 

def set_force_active_lod(lod_viewer_constants: bpy.types.NodeGroup, force_active_lod: bool, active_lod_index: int = -1)->bool:
    active_lod_index_node: bpy.types.FunctionNodeInputInt | None = (
        lod_viewer_constants.nodes.get(LODViewerConstantsNodes.ACTIVE_LOD_INDEX.value)
    )
    if not active_lod_index_node:
        return False
    geometry_node_utils.set_integer_node_value(active_lod_index_node, active_lod_index)

    force_active_lod_node: bpy.types.FunctionNodeInputBool | None = (
        lod_viewer_constants.nodes.get(
            LODViewerConstantsNodes.FORCE_ACTIVE_LOD.value
        )
    )
    if not force_active_lod_node:
        return False
    geometry_node_utils.set_boolean_node_value(force_active_lod_node, force_active_lod)
    return True 

def setup_lod_viewer_constants(
    scene: bpy.types.Scene,
    fov_y: float,
    lod_factor: float,
    display_bounding_sphere: bool = False,
    force_active_lod: bool = False,
    active_lod_index: bool = -1
):
    lod_viewer_constants: bpy.types.NodeGroup | None = get_scene_lod_viewer_constants_group(scene)
    if not lod_viewer_constants:
        return False

    set_fov_y(lod_viewer_constants, fov_y)
    set_lod_factor(lod_viewer_constants, lod_factor)
    set_display_bpshere(lod_viewer_constants, display_bounding_sphere)
    set_force_active_lod(lod_viewer_constants, force_active_lod, active_lod_index)

def get_lod_viewer_input_map():
    """Construct a dict associating input label to their unique identifiers.
    Can be used later to get properties from modifier.

    Needed only on version inferior to 5.2
    """
    if IS_BLENDER_5_2_OR_SUP:
        return
    
    lod_viewer_grp: bpy.types.NodeGroup | None = get_first_lod_viewer_group()
    if not lod_viewer_grp:
        return
    return geometry_node_utils.construct_input_identifier_map(lod_viewer_grp)
