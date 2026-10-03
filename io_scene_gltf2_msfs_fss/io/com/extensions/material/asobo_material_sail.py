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

from .....blender.utils.msfs_material_utils import (
    MSFS2024_MaterialProperties, 
    MSFS2024_MaterialTypes
)
from .....io.com.msfs_material_utils import MSFS2024_MaterialUtils

class AsoboSailExtension:

    extension_name = "ASOBO_material_sail"

    @staticmethod
    def from_dict(blender_material, gltf2_material, import_settings):
        extensions = gltf2_material.extensions
        if extensions is None:
            return

        assert isinstance(extensions, dict)
        extension = extensions.get(AsoboSailExtension.extension_name)

        if extension is None:
            return

        ## Set Material Type To Sail
        setattr(
            blender_material,
            MSFS2024_MaterialProperties.MATERIALTYPE.attribute_name(),
            MSFS2024_MaterialTypes.SAIL.value
        )

        MSFS2024_MaterialUtils.get_extension_parameter(
            extension=extension,
            material=blender_material,
            attribute=MSFS2024_MaterialProperties.SAILLIGHTABSORPTION
        )

    @staticmethod
    def to_extension(blender_material, gltf2_material, export_settings):
        result = {}

        material_type = getattr(
            blender_material, 
            MSFS2024_MaterialProperties.MATERIALTYPE.attribute_name()
        )
        
        if material_type != MSFS2024_MaterialTypes.SAIL.value:
            return
        
        result = {"enabled": True}
        
        MSFS2024_MaterialUtils.set_extension_parameter(
            extension=result,
            material=blender_material,
            attribute=MSFS2024_MaterialProperties.SAILLIGHTABSORPTION
        )
        
        if result:
            gltf2_material.extensions[AsoboSailExtension.extension_name] = Extension(
                name=AsoboSailExtension.extension_name, 
                extension=result, 
                required=False
            )

def register():
    bpy.types.Material.msfs_sail_light_absorption = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.SAILLIGHTABSORPTION.property_name(),
        min=0.0,
        max=1.0,
        default=MSFS2024_MaterialProperties.SAILLIGHTABSORPTION.default_value()
    )

def unregister():
    try:
        del bpy.types.Material.msfs_sail_light_absorption
    except:
        pass
