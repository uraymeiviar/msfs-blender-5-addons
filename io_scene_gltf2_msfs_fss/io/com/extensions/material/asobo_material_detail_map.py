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

from .....blender.material.msfs_material_properties_update import MSFS2024_MaterialPropUpdate
from .....blender.utils.msfs_material_utils import MSFS2024_MaterialProperties
from .....io.com.msfs_material_utils import MSFS2024_MaterialUtils


class AsoboMaterialDetailExtension:

    extension_name = "ASOBO_material_detail_map"

    extension_parameters = [
        MSFS2024_MaterialProperties.DETAILUVSCALE,
        MSFS2024_MaterialProperties.DETAILBLENDTHRESHOLD
    ]

    extension_textures = [
        MSFS2024_MaterialProperties.DETAILCOLORTEXTURE,
        MSFS2024_MaterialProperties.DETAILOMRTEXTURE,
        (MSFS2024_MaterialProperties.DETAILNORMALTEXTURE, "NORMAL"),
        MSFS2024_MaterialProperties.BLENDMASKTEXTURE
    ]

    @staticmethod
    def from_dict(blender_material, gltf2_material, import_settings):
        extensions = gltf2_material.extensions
        if extensions is None:
            return

        assert isinstance(extensions, dict)
        extension = extensions.get(AsoboMaterialDetailExtension.extension_name)
        if extension is None:
            return

        for extension_parameter in AsoboMaterialDetailExtension.extension_parameters:
            MSFS2024_MaterialUtils.get_extension_parameter(
                extension=extension,
                material=blender_material,
                attribute=extension_parameter
            )
        
        for extension_texture in AsoboMaterialDetailExtension.extension_textures:
            if isinstance(extension_texture, tuple) and len(extension_texture) > 1:
                extension_texture = extension_texture[0]

            MSFS2024_MaterialUtils.get_extension_texture(
                extension=extension,
                material=blender_material,
                attribute=extension_texture,
                settings=import_settings
            )

        ## get the scale from the normal texture information
        # "detailNormalTexture": {
        #     "scale": 0.4,
        #     "index": 3
        #   }
        normal_texture_extension = extension.get(MSFS2024_MaterialProperties.DETAILNORMALTEXTURE.extension_name())
        if normal_texture_extension:
            MSFS2024_MaterialUtils.get_extension_parameter(
                    extension=normal_texture_extension,
                    material=blender_material,
                    attribute=MSFS2024_MaterialProperties.DETAILNORMALSCALE
                )        

    @staticmethod
    def to_extension(blender_material, gltf2_material, export_settings):
        result = {}

        for extension_texture in AsoboMaterialDetailExtension.extension_textures:
            texture_type="DEFAULT"

            if isinstance(extension_texture, tuple) and len(extension_texture) > 1:
                texture_type=extension_texture[1]
                extension_texture = extension_texture[0]

            MSFS2024_MaterialUtils.set_extension_texture(
                extension=result,
                material=blender_material,
                attribute=extension_texture,
                settings=export_settings,
                texture_type=texture_type,
            )

        
        if not result:
            return

        if getattr(
            blender_material, 
            MSFS2024_MaterialProperties.DETAILNORMALTEXTURE.attribute_name()
        ) is not None:
            
            result[MSFS2024_MaterialProperties.DETAILNORMALTEXTURE.extension_name()].scale = getattr(
                blender_material, 
                MSFS2024_MaterialProperties.DETAILNORMALSCALE.attribute_name()
            )  
        for extension_parameter in AsoboMaterialDetailExtension.extension_parameters:
            MSFS2024_MaterialUtils.set_extension_parameter(
                extension=result,
                material=blender_material,
                attribute=extension_parameter
            )

        gltf2_material.extensions[AsoboMaterialDetailExtension.extension_name] = Extension(
            name=AsoboMaterialDetailExtension.extension_name,
            extension=result,
            required=False
        )

def register():
    # region Parameters
    bpy.types.Material.msfs_detail_uv_scale = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.DETAILUVSCALE.property_name(),
        min=0.01,
        max=100.0,
        default=MSFS2024_MaterialProperties.DETAILUVSCALE.default_value(),
        update=MSFS2024_MaterialPropUpdate.update_detail_uv,
        precision=3
    )

    bpy.types.Material.msfs_detail_blend_threshold = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.DETAILBLENDTHRESHOLD.property_name(),
        min=0.001,
        max=1.0,
        default=MSFS2024_MaterialProperties.DETAILBLENDTHRESHOLD.default_value(),
        update=MSFS2024_MaterialPropUpdate.update_blend_mask_threshold,
        precision=3
    )

    bpy.types.Material.msfs_detail_normal_scale = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.DETAILNORMALSCALE.property_name(),
        min=0.0,
        max=1.0,
        default=MSFS2024_MaterialProperties.DETAILNORMALSCALE.default_value(),
        update=MSFS2024_MaterialPropUpdate.update_detail_normal_scale,
        precision=3
    )
    # endregion
    
    # region Textures
    bpy.types.Material.msfs_detail_color_texture = bpy.props.PointerProperty(
        name=MSFS2024_MaterialProperties.DETAILCOLORTEXTURE.property_name(),
        type=bpy.types.Image,
        update=MSFS2024_MaterialPropUpdate.update_detail_color_texture
    )

    bpy.types.Material.msfs_detail_occlusion_metallic_roughness_texture = bpy.props.PointerProperty(
            name=MSFS2024_MaterialProperties.DETAILOMRTEXTURE.property_name(),
            type = bpy.types.Image,
            update=MSFS2024_MaterialPropUpdate.update_detail_comp_texture
    )

    bpy.types.Material.msfs_detail_normal_texture = bpy.props.PointerProperty(
        name=MSFS2024_MaterialProperties.DETAILNORMALTEXTURE.property_name(),
        type=bpy.types.Image,
        update=MSFS2024_MaterialPropUpdate.update_detail_normal_texture
    )

    bpy.types.Material.msfs_blend_mask_texture = bpy.props.PointerProperty(
        name=MSFS2024_MaterialProperties.BLENDMASKTEXTURE.property_name(),
        type=bpy.types.Image,
        update=MSFS2024_MaterialPropUpdate.update_blend_mask_texture
    )
    # endregion

def unregister():
    try:
        del bpy.types.Material.msfs_detail_uv_scale
        del bpy.types.Material.msfs_detail_blend_threshold
        del bpy.types.Material.msfs_detail_normal_scale
        del bpy.types.Material.msfs_detail_color_texture
        del bpy.types.Material.msfs_detail_occlusion_metallic_roughness_texture
        del bpy.types.Material.msfs_detail_normal_texture
        del bpy.types.Material.msfs_blend_mask_texture
    except:
        pass
