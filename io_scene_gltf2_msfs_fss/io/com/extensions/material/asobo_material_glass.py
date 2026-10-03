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

class AsoboGlass:

    extension_name = "ASOBO_material_glass_v2"


    @staticmethod
    def from_dict(blender_material, gltf2_material, import_settings):
        extensions = gltf2_material.extensions
        if extensions is None:
            return

        assert isinstance(extensions, dict)
        extension = extensions.get(AsoboGlass.extension_name)
        if extension is None:
            return

        setattr(
            blender_material, 
            MSFS2024_MaterialProperties.MATERIALTYPE.attribute_name(),
            MSFS2024_MaterialTypes.GLASS.value
        )
        
        MSFS2024_MaterialUtils.get_extension_parameter(
            extension=extension, 
            material=blender_material,
            attribute=MSFS2024_MaterialProperties.GLASSWIDTH
        )
        
        # Convert from meters to mm
        glass_width = getattr(
            blender_material, 
            MSFS2024_MaterialProperties.GLASSWIDTH.attribute_name()
        )
        glass_width = glass_width * 100.0
        setattr(
            blender_material, 
            MSFS2024_MaterialProperties.GLASSWIDTH.attribute_name(),
            glass_width
        )

    @staticmethod
    def to_extension(blender_material, gltf2_material, export_settings):        
        material_type = getattr(
            blender_material, 
            MSFS2024_MaterialProperties.MATERIALTYPE.attribute_name()
        )
        
        if material_type != MSFS2024_MaterialTypes.GLASS.value:
            return

        result = {}
        
        MSFS2024_MaterialUtils.set_extension_parameter(
            extension=result,
            material=blender_material,
            attribute=MSFS2024_MaterialProperties.GLASSWIDTH,
            with_default_value=True
        )

        if result:
            value = result[MSFS2024_MaterialProperties.GLASSWIDTH.extension_name()]
            result[MSFS2024_MaterialProperties.GLASSWIDTH.extension_name()] = value / 100.0
            gltf2_material.extensions[AsoboGlass.extension_name] = Extension(
                name=AsoboGlass.extension_name, 
                extension=result, 
                required=False
            )

def register():
    bpy.types.Material.msfs_glass_width = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.GLASSWIDTH.property_name(),
        min=0.0,
        max=1000.0,
        default=MSFS2024_MaterialProperties.GLASSWIDTH.default_value()
    )

def unregister():
    try:
        del bpy.types.Material.msfs_glass_width
    except:
        pass
