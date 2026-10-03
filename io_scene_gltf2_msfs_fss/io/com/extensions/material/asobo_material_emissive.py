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

from .....blender.utils.msfs_material_utils import MSFS2024_MaterialProperties
from .....io.com.msfs_material_utils import MSFS2024_MaterialUtils

class AsoboMaterialEmissiveExtension:

    extension_name = "ASOBO_material_emissive"
    
    extension_parameters = [
        MSFS2024_MaterialProperties.EMISSIVE_DAY_MULTIPLIER,
        MSFS2024_MaterialProperties.EMISSIVE_NIGHT_MULTIPLIER
    ]
    
    @staticmethod
    def from_dict(blender_material, gltf2_material, import_settings):
        extensions = gltf2_material.extensions
        if extensions is None:
            return

        assert isinstance(extensions, dict)
        extension = extensions.get(AsoboMaterialEmissiveExtension.extension_name)
        if extension is None:
            return
        
        for extension_parameter in AsoboMaterialEmissiveExtension.extension_parameters:
            MSFS2024_MaterialUtils.get_extension_parameter(
                extension=extension,
                material=blender_material,
                attribute=extension_parameter
            )

    @staticmethod
    def to_extension(blender_material, gltf2_material, export_settings):
        result = {}

        for extension_parameter in AsoboMaterialEmissiveExtension.extension_parameters:
            MSFS2024_MaterialUtils.set_extension_parameter(
                extension=result,
                material=blender_material,
                attribute=extension_parameter
            )
            
        if result:
            gltf2_material.extensions[AsoboMaterialEmissiveExtension.extension_name] = Extension(
                name=AsoboMaterialEmissiveExtension.extension_name,
                extension=result,
                required=False
            )
            
def register():
    bpy.types.Material.msfs_emissive_day_multiplier = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.EMISSIVE_DAY_MULTIPLIER.property_name(),
        min=0.0,
        max=100000.0,
        default=MSFS2024_MaterialProperties.EMISSIVE_DAY_MULTIPLIER.default_value()
    )
    
    bpy.types.Material.msfs_emissive_night_multiplier = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.EMISSIVE_NIGHT_MULTIPLIER.property_name(),
        min=0.0,
        max=100000.0,
        default=MSFS2024_MaterialProperties.EMISSIVE_NIGHT_MULTIPLIER.default_value()
    )

def unregister():
    try:
        del bpy.types.Material.msfs_emissive_day_multiplier 
        del bpy.types.Material.msfs_emissive_day_multiplier
    except:
        pass
