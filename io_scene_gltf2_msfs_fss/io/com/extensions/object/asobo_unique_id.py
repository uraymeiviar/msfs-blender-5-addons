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
from io_scene_gltf2.io.com.gltf2_io_extensions import Extension


class AsoboUniqueId:
    bl_options = {"UNDO"}

    extension_name = "ASOBO_unique_id"

    def __new__(cls, *args, **kwargs):
        raise RuntimeError(f"{cls} should not be instantiated")
    
    @staticmethod
    def get_asobo_unique_id(gltf_node):
        if not gltf_node:
            return None

        if not gltf_node.extensions:
            return None

        extension = gltf_node.extensions.get(AsoboUniqueId.extension_name)
        if not extension:
            return None
        
        return extension.get("id", None)
    
    @staticmethod
    def add_unique_id_to_neutral_bone(gltf2_node, parent_name=""):
        if gltf2_node.extensions is None:
            gltf2_node.extensions = {}
        
        extension = {}
        extension["id"] = parent_name + "_neutral_bone"
        
        gltf2_node.extensions[AsoboUniqueId.extension_name] = Extension(
            name=AsoboUniqueId.extension_name,
            extension=extension,
            required=False
        )

    @staticmethod
    def from_extension(gltf2_node, blender_object):
        if not gltf2_node:
            # Can happen for 3dsMax armature object for example
            return
        unique_id = AsoboUniqueId.get_asobo_unique_id(gltf2_node)
        if not unique_id:
            return
        blender_object.msfs_override_unique_id = True
        blender_object.name = unique_id
        blender_object.msfs_unique_id = unique_id

    @staticmethod
    def export(gltf2_object, blender_object):
        if gltf2_object.extensions is None:
            gltf2_object.extensions = {}

        extension = {}

        if isinstance(blender_object, bpy.types.PoseBone):
            blender_object = blender_object.bone
        
        extension["id"] = gltf2_object.name
        
        if blender_object.msfs_override_unique_id:
            extension["id"] = blender_object.msfs_unique_id
            
        gltf2_object.extensions[AsoboUniqueId.extension_name] = Extension(
            name=AsoboUniqueId.extension_name,
            extension=extension,
            required=False
        )
