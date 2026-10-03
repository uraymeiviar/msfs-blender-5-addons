# Copyright 2023-2024 The glTF-Blender-IO-MSFS2024 authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
Utilities for bpy.types.Mesh data
"""
import bpy
import numpy as np

from .msfs_constants import DefaultVertexColor

def add_default_vcolor(mesh:bpy.types.Mesh):
    """
    Add a white color attribute.
    """
    if mesh.color_attributes:
        return None

    mesh.color_attributes.new(
        name=DefaultVertexColor.NAME,
        type=DefaultVertexColor.TYPE,
        domain=DefaultVertexColor.DOMAIN,
    )
    return None


def is_color_attribute_uniform_white(mesh:bpy.types.Mesh):
    """
    Checks if the render active color attribute in the specified mesh object 
    is uniformly white.
    
    Parameters:
    - blender_mesh: The Blender mesh to check.

    Returns:
    - True if the render active color attribute is uniformly white, False otherwise.
    """
    if mesh.attributes is None:
        return False

    render_color_index = mesh.attributes.render_color_index

    if render_color_index == -1:
        return False

    if render_color_index >= len(mesh.color_attributes):
        return False

    render_active_attr = mesh.color_attributes[render_color_index]
    color_data = render_active_attr.data

    white_color = (1.0, 1.0, 1.0, 1.0)  
    if all(color.color[:] == white_color for color in color_data):
        return True

    return False

def get_active_color_attribute(mesh: bpy.types.Mesh) -> None | bpy.types.Attribute:
    """Set color attribute to be active in viewport and render.
    """
    return mesh.attributes.active_color

def complies_with_default_vertex_color(color_attribute: bpy.types.Attribute) -> bool:
    """Check if color attribute type and domain match with
    advised default vertex color. 

    Args:
        color_attribute: Color attribute to export.
    """
    if color_attribute.data_type != DefaultVertexColor.TYPE:
        return False
    if color_attribute.domain != DefaultVertexColor.DOMAIN:
        return False

    return True

def convert_active_color_attribute(
    obj:bpy.types.Object, 
    target_domain:str,
    data_type:str
):
    context_override = bpy.context.copy()
    context_override["object"] = obj
    context_override["active_object"] = obj

    with bpy.context.temp_override(**context_override):
        bpy.ops.geometry.color_attribute_convert(domain=target_domain,data_type=data_type)

def swap_uv_layers(
    mesh: bpy.types.Mesh,
    idx: int,
    other_idx: int,
    preserve_active_idx: bool = True,
):
    """Swap uv layers in obj.data.uv_layers list.
    Can preserve active and active_render index.
    """
    size = len(mesh.loops) * 2
    uvs_a = np.empty(size, dtype="float32")
    uvs_b = np.empty(size, dtype="float32")

    layers = mesh.uv_layers
    uv_layer_a = layers[idx]
    uv_layer_b = layers[other_idx]
    uv_layer_a.data.foreach_get("uv", uvs_a)
    uv_layer_b.data.foreach_get("uv", uvs_b)

    uv_layer_a.data.foreach_set("uv", uvs_b)
    uv_layer_b.data.foreach_set("uv", uvs_a)

    if preserve_active_idx:
        if layers.active_index != other_idx:
            layers.active_index = other_idx
        if uv_layer_a.active_render:
            uv_layer_b.active_render = True
            uv_layer_a.active_render = False
        elif uv_layer_b.active_render:
            uv_layer_a.active_render = True
            uv_layer_b.active_render = False
    # Rename
    uv_layer_a_name = uv_layer_a.name
    uv_layer_b_name = uv_layer_b.name
    # Rename layers first to prevent numbered suffix ".001"
    uv_layer_a.name = "temp"
    uv_layer_b.name = "temp"
    uv_layer_a.name = uv_layer_b_name
    uv_layer_b.name = uv_layer_a_name