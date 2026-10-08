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
import uuid
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


def is_color_attribute_uniform_white(attribute: bpy.types.FloatColorAttribute):
    """
    Checks if the color attribute in the specified mesh object 
    is uniformly white.
    
    Returns:
    - True if the render active color attribute is uniformly white, False otherwise.
    """
    
    data = attribute.data
    if not data:
        return True

    color_array = np.empty((len(data), 4), dtype=np.float32)
    data.foreach_get("color", np.ravel(color_array))

    return np.all(color_array == 1)


def get_active_color_attribute(mesh: bpy.types.Mesh) -> None | bpy.types.FloatColorAttribute:
    """Get color attribute to be active in viewport.
    Corresponds to attribute selected (outlined in blue) in Color Attributes panel.
    Differs from the active_render attributes.
    """
    if not mesh.attributes:
        return None
    return mesh.attributes.active_color # type: ignore

def get_active_render_color_index(mesh: bpy.types.Mesh) -> None | int:
    """Get color attribute to be active in viewport.
    Corresponds to attribute selected (outlined in blue) in Color Attributes panel.
    Differs from the active_render attributes.
    """
    if not mesh.color_attributes:
        return None

    return mesh.color_attributes.render_color_index

def get_active_render_color_attribute(mesh: bpy.types.Mesh) -> None | bpy.types.FloatColorAttribute:
    """Get color attribute to be active in viewport.
    Corresponds to attribute selected (outlined in blue) in Color Attributes panel.
    Differs from the active_render attributes.
    """
    index = get_active_render_color_index(mesh)
    if index is None:
        return None

    if index >= len(mesh.color_attributes):
        return None

    return mesh.color_attributes[index] # type: ignore

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
    preserve_active_idx: bool = True
):
    """Swap uv layers in obj.data.uv_layers list.
    Can preserve active and active_render index.
    """
    size = len(mesh.loops) * 2
    uvs_a = np.empty(size, dtype=np.float32)
    uvs_b = np.empty(size, dtype=np.float32)

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
    # Be carefull, uv_layer ref can be invalid after a rename, and point to another layer in the list.
    layer_a_temp_name = str(uuid.uuid4())
    layer_b_temp_name = str(uuid.uuid4())
    uv_layer_a.name = layer_a_temp_name
    uv_layer_b.name = layer_b_temp_name
    uv_layer_a = mesh.uv_layers[layer_a_temp_name]
    uv_layer_b = mesh.uv_layers[layer_b_temp_name]
    uv_layer_a.name = uv_layer_b_name
    uv_layer_b.name = uv_layer_a_name