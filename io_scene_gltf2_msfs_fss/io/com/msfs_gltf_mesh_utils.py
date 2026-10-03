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
import bpy

from io_scene_gltf2_msfs_fss.blender.utils.msfs_constants import DefaultVertexColor
from io_scene_gltf2_msfs_fss.blender.utils import msfs_mesh_utils


def remove_color_attribute(gltf2_mesh, blender_mesh:bpy.types.Mesh):
    if not msfs_mesh_utils.is_color_attribute_uniform_white(blender_mesh):
        return

    for primitive in gltf2_mesh.primitives:
        new_attributes = {}
        for attribute_name, attribute in primitive.attributes.items():
            if not attribute_name.startswith(DefaultVertexColor.NAME):
                new_attributes[attribute_name] = attribute
        primitive.attributes = new_attributes

 