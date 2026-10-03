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

class AsoboRainOptionsExtension:

    extension_name = "ASOBO_material_rain_options"

    extension_parameters = [
        MSFS2024_MaterialProperties.RAINDROPTILING,
        MSFS2024_MaterialProperties.RAINONBACKFACE
    ]

    @staticmethod
    def from_dict(blender_material, gltf2_material, import_settings):
        extensions = gltf2_material.extensions
        if extensions is None:
            return

        assert isinstance(extensions, dict)
        extension = extensions.get(AsoboRainOptionsExtension.extension_name)
        if extension is None:
            return

        setattr(
            blender_material,
            MSFS2024_MaterialProperties.RECEIVERAIN.attribute_name(),
            True
        )

        for extension_parameter in AsoboRainOptionsExtension.extension_parameters:
            MSFS2024_MaterialUtils.get_extension_parameter(
                extension=extension,
                material=blender_material,
                attribute=extension_parameter
            )

        # Set Rain on back face if it exists in the extension
        MSFS2024_MaterialUtils.get_extension_parameter(
            extension=extension,
            material=blender_material,
            attribute=MSFS2024_MaterialProperties.RAINONBACKFACE
        )

    @staticmethod
    def to_extension(blender_material, gltf2_material, export_settings):
        result = {}

        if not getattr(
            blender_material,
            MSFS2024_MaterialProperties.RECEIVERAIN.attribute_name()
        ):
            return
        
        for extension_parameter in AsoboRainOptionsExtension.extension_parameters:
            MSFS2024_MaterialUtils.set_extension_parameter(
                extension=result,
                material=blender_material,
                attribute=extension_parameter
            )

        material_type = getattr(
            blender_material,
            MSFS2024_MaterialProperties.MATERIALTYPE.attribute_name()
        )
        
        if material_type == MSFS2024_MaterialTypes.WINDSHIELD:
            MSFS2024_MaterialUtils.set_extension_parameter(
                extension=result,
                material=blender_material,
                attribute=MSFS2024_MaterialProperties.RAINONBACKFACE
            )

        if not result:
            result = {"enabled": True}

        gltf2_material.extensions[AsoboRainOptionsExtension.extension_name] = Extension(
            name=AsoboRainOptionsExtension.extension_name,
            extension=result,
            required=False
        )

def register():
    bpy.types.Material.msfs_receive_rain = bpy.props.BoolProperty(
        name=MSFS2024_MaterialProperties.RECEIVERAIN.property_name(),
        default=MSFS2024_MaterialProperties.RECEIVERAIN.default_value()
    )

    bpy.types.Material.msfs_rain_drop_tiling = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.RAINDROPTILING.property_name(),
        min=0.0,
        max=100.0,
        default=MSFS2024_MaterialProperties.RAINDROPTILING.default_value()
    )

    bpy.types.Material.msfs_rain_on_backface = bpy.props.BoolProperty(
        name=MSFS2024_MaterialProperties.RAINONBACKFACE.property_name(),
        default=MSFS2024_MaterialProperties.RAINONBACKFACE.default_value()
    )

def unregister():
    try:
        del bpy.types.Material.msfs_receive_rain
        del bpy.types.Material.msfs_rain_drop_tiling
        del bpy.types.Material.msfs_rain_on_backface
    except:
        pass
