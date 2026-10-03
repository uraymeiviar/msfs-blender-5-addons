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

class AsoboMaterialIridescentExtension:

    extension_name = "ASOBO_material_iridescent"

    extension_parameters = [
        MSFS2024_MaterialProperties.IRIDESCENTMINTHICKNESS,
        MSFS2024_MaterialProperties.IRIDESCENTMAXTHICKNESS,
        MSFS2024_MaterialProperties.IRIDESCENTBRIGHTNESS
    ]

    @staticmethod
    def from_dict(blender_material, gltf2_material, import_settings):
        extensions = gltf2_material.extensions
        if extensions is None:
            return

        assert isinstance(extensions, dict)
        extension = extensions.get(AsoboMaterialIridescentExtension.extension_name)
        if extension is None:
            return

        setattr(
            blender_material, 
            MSFS2024_MaterialProperties.MATERIALTYPE.attribute_name(), 
            MSFS2024_MaterialTypes.WINDSHIELD.value
        )
        
        setattr(
            blender_material, 
            MSFS2024_MaterialProperties.USEIRIDESCENT.attribute_name(), 
            True
        )

        for extension_parameter in AsoboMaterialIridescentExtension.extension_parameters:
            MSFS2024_MaterialUtils.get_extension_parameter(
                extension=extension, 
                material=blender_material, 
                attribute=extension_parameter
            )

        MSFS2024_MaterialUtils.get_extension_texture(
            extension=extension,
            material=blender_material,
            attribute=MSFS2024_MaterialProperties.IRIDESCENTTHICKNESSTEXTURE,
            settings=import_settings
        )

    @staticmethod
    def to_extension(blender_material, gltf2_material, export_settings):
        result = {}

        if getattr(
            blender_material, 
            MSFS2024_MaterialProperties.USEIRIDESCENT.attribute_name()
        ):
            for extension_parameter in AsoboMaterialIridescentExtension.extension_parameters:
                MSFS2024_MaterialUtils.set_extension_parameter(
                    extension=result, 
                    material=blender_material, 
                    attribute=extension_parameter
                )
            
            MSFS2024_MaterialUtils.set_extension_texture(
                extension=result,
                material=blender_material,
                attribute=MSFS2024_MaterialProperties.IRIDESCENTTHICKNESSTEXTURE,
                settings=export_settings
            )

            gltf2_material.extensions[AsoboMaterialIridescentExtension.extension_name] = Extension(
                name=AsoboMaterialIridescentExtension.extension_name, 
                extension=result, 
                required=False
            )
            
def register():
    bpy.types.Material.msfs_use_iridescent = bpy.props.BoolProperty(
        name=MSFS2024_MaterialProperties.USEIRIDESCENT.property_name(),
        default=MSFS2024_MaterialProperties.USEIRIDESCENT.default_value()
    )

    bpy.types.Material.msfs_iridescent_min_thickness = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.IRIDESCENTMINTHICKNESS.property_name(),
        min=0.0,
        max=2000.0,
        default=MSFS2024_MaterialProperties.IRIDESCENTMINTHICKNESS.default_value()
    )

    bpy.types.Material.msfs_iridescent_max_thickness = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.IRIDESCENTMAXTHICKNESS.property_name(),
        min=0.0,
        max=2000.0,
        default=MSFS2024_MaterialProperties.IRIDESCENTMAXTHICKNESS.default_value()
    )

    bpy.types.Material.msfs_iridescent_brightness = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.IRIDESCENTBRIGHTNESS.property_name(),
        min=0.0,
        max=10.0,
        default=MSFS2024_MaterialProperties.IRIDESCENTBRIGHTNESS.default_value()
    )

    ## Textures
    bpy.types.Material.msfs_iridescent_thickness_texture = bpy.props.PointerProperty(
        name=MSFS2024_MaterialProperties.IRIDESCENTTHICKNESSTEXTURE.property_name(),
        type=bpy.types.Image
    )

def unregister():
    try:
        del bpy.types.Material.msfs_use_iridescent
        del bpy.types.Material.msfs_iridescent_min_thickness
        del bpy.types.Material.msfs_iridescent_max_thickness
        del bpy.types.Material.msfs_iridescent_brightness
        del bpy.types.Material.msfs_iridescent_thickness_texture
    except:
        pass
