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

class AsoboMaterialFresnelFadeExtension:

    extension_name = "ASOBO_material_fresnel_fade"

    extension_parameters = [
        MSFS2024_MaterialProperties.FRESNELFACTOR,
        MSFS2024_MaterialProperties.FRESNELOPACITYBIAS
    ]

    @staticmethod
    def from_dict(blender_material, gltf2_material, import_settings):
        extensions = gltf2_material.extensions
        if extensions is None:
            return

        assert isinstance(extensions, dict)
        extension = extensions.get(AsoboMaterialFresnelFadeExtension.extension_name)
        if extension is None:
            return
        
        setattr(
            blender_material, 
            MSFS2024_MaterialProperties.MATERIALTYPE.attribute_name(), 
            MSFS2024_MaterialTypes.FRESNELFADE.value
        )

        for extension_parameter in AsoboMaterialFresnelFadeExtension.extension_parameters:
            MSFS2024_MaterialUtils.get_extension_parameter(
                extension=extension,
                material=blender_material,
                attribute=extension_parameter
            )

    @staticmethod
    def to_extension(blender_material, gltf2_material, export_settings):
        material_type = getattr(
            blender_material, 
            MSFS2024_MaterialProperties.MATERIALTYPE.attribute_name()
        )
        
        if material_type != MSFS2024_MaterialTypes.FRESNELFADE.value:
            return

        result = {}
        
        for extension_parameter in AsoboMaterialFresnelFadeExtension.extension_parameters:
            MSFS2024_MaterialUtils.set_extension_parameter(
                extension=result,
                material=blender_material,
                attribute=extension_parameter,
                with_default_value=True
            )

        if result:
            gltf2_material.extensions[AsoboMaterialFresnelFadeExtension.extension_name] = Extension(
                name=AsoboMaterialFresnelFadeExtension.extension_name,
                extension=result,
                required=False
            )

def register():
    bpy.types.Material.msfs_fresnel_factor = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.FRESNELFACTOR.property_name(),
        min=0.001,
        max=100.0,
        default=MSFS2024_MaterialProperties.FRESNELFACTOR.default_value()
    )

    bpy.types.Material.msfs_fresnel_opacity_offset = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.FRESNELOPACITYBIAS.property_name(),
        min=-1.0,
        max=1.0,
        default=MSFS2024_MaterialProperties.FRESNELOPACITYBIAS.default_value()
    )

def unregister():
    try:
        del bpy.types.Material.msfs_fresnel_factor
        del bpy.types.Material.msfs_fresnel_opacity_offset
    except:
        pass
