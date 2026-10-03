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

class AsoboMaterialDirtExtension:

    extension_name = "ASOBO_material_dirt"

    extension_parameters = [
        MSFS2024_MaterialProperties.WEAROVERLAYUVSCALE,
        MSFS2024_MaterialProperties.WEARBLENDSHARPNESS,
        MSFS2024_MaterialProperties.WEARAMOUNT
    ]

    extension_textures = [
        MSFS2024_MaterialProperties.WEARALBEDOMASKTEXTURE,
        MSFS2024_MaterialProperties.WEAROMRINTENSITYTEXTURE
    ]

    @staticmethod
    def from_dict(blender_material, gltf2_material, import_settings):
        extensions = gltf2_material.extensions
        if extensions is None:
            return

        assert isinstance(extensions, dict)
        extension = extensions.get(AsoboMaterialDirtExtension.extension_name)
        if extension is None:
            return

        for extension_parameter in AsoboMaterialDirtExtension.extension_parameters:
            MSFS2024_MaterialUtils.get_extension_parameter(
                extension=extension,
                material=blender_material,
                attribute=extension_parameter
            )

        for extension_texture in AsoboMaterialDirtExtension.extension_textures:
            MSFS2024_MaterialUtils.get_extension_texture(
                extension=extension,
                material=blender_material,
                attribute=extension_texture,
                settings=import_settings
            )
        
    @staticmethod
    def to_extension(blender_material, gltf2_material, export_settings):
        result = {}

        for extension_parameter in AsoboMaterialDirtExtension.extension_parameters:
            MSFS2024_MaterialUtils.set_extension_parameter(
                extension=result,
                material=blender_material,
                attribute=extension_parameter
            )

        for extension_texture in AsoboMaterialDirtExtension.extension_textures:
            MSFS2024_MaterialUtils.set_extension_texture(
                extension=result,
                material=blender_material,
                attribute=extension_texture,
                settings=export_settings,
            )
        
        if result:
            gltf2_material.extensions[AsoboMaterialDirtExtension.extension_name] = Extension(
                name=AsoboMaterialDirtExtension.extension_name,
                extension=result,
                required=False
            )

def register():
    bpy.types.Material.msfs_wear_overlay_uv_scale = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.WEAROVERLAYUVSCALE.property_name(),
        description="",
        min=0.0,
        max=10.0,
        default=MSFS2024_MaterialProperties.WEAROVERLAYUVSCALE.default_value(),
        precision=3
    )

    bpy.types.Material.msfs_wear_blend_sharpness = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.WEARBLENDSHARPNESS.property_name(),
        description="",
        min=0.0,
        max=1.0,
        default=MSFS2024_MaterialProperties.WEARBLENDSHARPNESS.default_value(),
        precision=3
    )

    bpy.types.Material.msfs_wear_amount = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.WEARAMOUNT.property_name(),
        description="",
        min=0.0,
        max=1.0,
        default=MSFS2024_MaterialProperties.WEARAMOUNT.default_value(),
        precision=3
    )

    ## Textures
    bpy.types.Material.msfs_wear_albedo_mask = bpy.props.PointerProperty(
        name=MSFS2024_MaterialProperties.WEARALBEDOMASKTEXTURE.property_name(), 
        type=bpy.types.Image
    )

    bpy.types.Material.msfs_wear_omr_intensity = bpy.props.PointerProperty(
        name=MSFS2024_MaterialProperties.WEAROMRINTENSITYTEXTURE.property_name(), 
        type=bpy.types.Image
    )

def unregister():
    try:
        del bpy.types.Material.msfs_wear_overlay_uv_scale
        del bpy.types.Material.msfs_wear_blend_sharpness
        del bpy.types.Material.msfs_wear_amount
        del bpy.types.Material.msfs_wear_albedo_mask
        del bpy.types.Material.msfs_wear_omr_intensity
    except:
        pass
    