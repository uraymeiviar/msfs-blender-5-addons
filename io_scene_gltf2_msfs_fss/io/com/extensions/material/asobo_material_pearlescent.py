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

class AsoboPearlescentExtension:

    extension_name = "ASOBO_material_pearlescent"

    extension_parameters = [
        MSFS2024_MaterialProperties.PEARLCOLORSHIFT,
        MSFS2024_MaterialProperties.PEARLCOLORRANGE,
        MSFS2024_MaterialProperties.PEARLCOLORBRIGHTNESS
    ]

    @staticmethod
    def from_dict(blender_material, gltf2_material, import_settings):
        extensions = gltf2_material.extensions
        if extensions is None:
            return

        assert isinstance(extensions, dict)
        extension = extensions.get(AsoboPearlescentExtension.extension_name)
        if extension is None:
            return
        
        setattr(
            blender_material, 
            MSFS2024_MaterialProperties.USEPEARLEFFECT.attribute_name(), 
            True
        )

        for extension_parameter in AsoboPearlescentExtension.extension_parameters:
            MSFS2024_MaterialUtils.get_extension_parameter(
                extension=extension, 
                material=blender_material, 
                attribute=extension_parameter
            )

    @staticmethod
    def to_extension(blender_material, gltf2_material, export_settings):        
        if not getattr(
            blender_material, 
            MSFS2024_MaterialProperties.USEPEARLEFFECT.attribute_name()
        ):
            return

        result = {}
        for extension_parameter in AsoboPearlescentExtension.extension_parameters:
            MSFS2024_MaterialUtils.set_extension_parameter(
                extension=result,
                material=blender_material,
                attribute=extension_parameter,
                with_default_value=True
            )

        if result:
            gltf2_material.extensions[AsoboPearlescentExtension.extension_name] = Extension(
                name=AsoboPearlescentExtension.extension_name, 
                extension=result, 
                required=False
            )

def register():
    bpy.types.Material.msfs_use_pearl = bpy.props.BoolProperty(
        name=MSFS2024_MaterialProperties.USEPEARLEFFECT.property_name(),
        default=MSFS2024_MaterialProperties.USEPEARLEFFECT.default_value()
    )

    bpy.types.Material.msfs_pearl_shift = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.PEARLCOLORSHIFT.property_name(),
        min=-999.0,
        max=999.0,
        default=MSFS2024_MaterialProperties.PEARLCOLORSHIFT.default_value()
    )

    bpy.types.Material.msfs_pearl_range = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.PEARLCOLORRANGE.property_name(),
        min=-999.0,
        max=999.0,
        default=MSFS2024_MaterialProperties.PEARLCOLORRANGE.default_value()
    )

    bpy.types.Material.msfs_pearl_brightness = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.PEARLCOLORBRIGHTNESS.property_name(),
        min=-1.0,
        max=1.0,
        default=MSFS2024_MaterialProperties.PEARLCOLORBRIGHTNESS.default_value()
    )

def unregister():
    try:
        del bpy.types.Material.msfs_use_pearl
        del bpy.types.Material.msfs_pearl_shift
        del bpy.types.Material.msfs_pearl_range
        del bpy.types.Material.msfs_pearl_brightness
    except:
        pass
