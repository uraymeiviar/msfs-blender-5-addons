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


class AsoboMaterialWindshieldExtension:

    extension_name = "ASOBO_material_windshield_v3"

    extension_parameters = [
        MSFS2024_MaterialProperties.WINDSHIELDDETAILROUGHNESS1,
        MSFS2024_MaterialProperties.WINDSHIELDDETAILROUGHNESS2,
        MSFS2024_MaterialProperties.WINDSHIELDDETAILOPACITY1,
        MSFS2024_MaterialProperties.WINDSHIELDDETAILOPACITY2,
        MSFS2024_MaterialProperties.WINDSHIELDMICROSCRATCHTILING,
        MSFS2024_MaterialProperties.WINDSHIELDMICROSCRATCHSTRENGTH,
        MSFS2024_MaterialProperties.WINDSHIELDDETAILNORMALREFRACTSCALE,
        MSFS2024_MaterialProperties.WINDSHIELDWIPERLINES,
        MSFS2024_MaterialProperties.WINDSHIELDWIPERLINESSTRENGTH,
        MSFS2024_MaterialProperties.WINDSHIELDWIPERLINESTILING,
        MSFS2024_MaterialProperties.WINDSHIELDWIPER1STATE,
        MSFS2024_MaterialProperties.DETAILUVSCALE,
        MSFS2024_MaterialProperties.WINDSHIELDSSRATTENUATION,
        MSFS2024_MaterialProperties.WINDSHIELDCUBEMAPREFLECTIONMASKING
    ]

    extension_textures = [
        MSFS2024_MaterialProperties.WINDSHIELDWIPERMASKTEXTURE,
        (MSFS2024_MaterialProperties.WINDSHILEDDETAILNORMALTEXTURE, "NORMAL"),
        (MSFS2024_MaterialProperties.WINDSHIELDSCRACHESNORMALTEXTURE, "NORMAL"),
        MSFS2024_MaterialProperties.WINDSHIELDINSECTSALBEDOTEXTURE,
        MSFS2024_MaterialProperties.WINDSHIELDINSECTSMASKTEXTURE
    ]

    @staticmethod
    def from_dict(blender_material, gltf2_material, import_settings):

        extensions = gltf2_material.extensions
        if extensions is None:
            return

        assert isinstance(extensions, dict)
        extension = extensions.get(AsoboMaterialWindshieldExtension.extension_name)
        if extension is None:
            return

        setattr(
            blender_material,
            MSFS2024_MaterialProperties.MATERIALTYPE.attribute_name(),
            MSFS2024_MaterialTypes.WINDSHIELD.value
        )

        for extension_parameter in AsoboMaterialWindshieldExtension.extension_parameters:
            MSFS2024_MaterialUtils.get_extension_parameter(
                extension=extension,
                material=blender_material,
                attribute=extension_parameter
            )

        for extension_texture in AsoboMaterialWindshieldExtension.extension_textures:
            if isinstance(extension_texture, tuple) and len(extension_texture) > 1:
                extension_texture = extension_texture[0]

            MSFS2024_MaterialUtils.get_extension_texture(
                extension=extension,
                material=blender_material,
                attribute=extension_texture,
                settings=import_settings
            )

        ## Get Windshield Detail Normal Scale
        normal_detail_texture_extension = extension.get(
            MSFS2024_MaterialProperties.WINDSHILEDDETAILNORMALTEXTURE.extension_name()
        )
        if normal_detail_texture_extension:
            MSFS2024_MaterialUtils.get_extension_parameter(
                extension=normal_detail_texture_extension,
                material=blender_material,
                attribute=MSFS2024_MaterialProperties.DETAILNORMALSCALE
            )

    @staticmethod
    def to_extension(blender_material, gltf2_material, export_settings):
        material_type = getattr(
            blender_material,
            MSFS2024_MaterialProperties.MATERIALTYPE.attribute_name()
        )

        if material_type != MSFS2024_MaterialTypes.WINDSHIELD.value:
            return

        result = {}
        for extension_parameter in AsoboMaterialWindshieldExtension.extension_parameters:
            MSFS2024_MaterialUtils.set_extension_parameter(
                extension=result,
                material=blender_material,
                attribute=extension_parameter
            )

        for extension_texture in AsoboMaterialWindshieldExtension.extension_textures:
            texture_type = "DEFAULT"

            if isinstance(extension_texture, tuple) and len(extension_texture) > 1:
                texture_type = extension_texture[1]
                extension_texture = extension_texture[0]

            MSFS2024_MaterialUtils.set_extension_texture(
                extension=result,
                material=blender_material,
                attribute=extension_texture,
                settings=export_settings,
                texture_type=texture_type
            )

        # Set detail
        windshield_normal_ext_name = MSFS2024_MaterialProperties.WINDSHILEDDETAILNORMALTEXTURE.extension_name()
        if windshield_normal_ext_name in result:
            exported_windshield_normal_texture = result[windshield_normal_ext_name]
            if exported_windshield_normal_texture is not None:
                exported_windshield_normal_texture.scale = getattr(
                    blender_material,
                    MSFS2024_MaterialProperties.DETAILNORMALSCALE.attribute_name()
                )

        if not result:
            result = {"enabled": True}

        gltf2_material.extensions[AsoboMaterialWindshieldExtension.extension_name] = Extension(
            name=AsoboMaterialWindshieldExtension.extension_name,
            extension=result,
            required=False
        )


def register():
    # region Parameters
    bpy.types.Material.msfs_windshield_detail_rough_1 = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.WINDSHIELDDETAILROUGHNESS1.property_name(),
        min=0.0,
        max=1.0,
        default=MSFS2024_MaterialProperties.WINDSHIELDDETAILROUGHNESS1.default_value()
    )

    bpy.types.Material.msfs_windshield_detail_rough_2 = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.WINDSHIELDDETAILROUGHNESS2.property_name(),
        min=0.0,
        max=1.0,
        default=MSFS2024_MaterialProperties.WINDSHIELDDETAILROUGHNESS2.default_value()
    )

    bpy.types.Material.msfs_windshield_detail_opacity_1 = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.WINDSHIELDDETAILOPACITY1.property_name(),
        min=0.0,
        max=1.0,
        default=MSFS2024_MaterialProperties.WINDSHIELDDETAILOPACITY1.default_value()
    )

    bpy.types.Material.msfs_windshield_detail_opacity_2 = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.WINDSHIELDDETAILOPACITY2.property_name(),
        min=0.0,
        max=1.0,
        default=MSFS2024_MaterialProperties.WINDSHIELDDETAILOPACITY2.default_value()
    )

    bpy.types.Material.msfs_windshield_micro_scratches_tiling = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.WINDSHIELDMICROSCRATCHTILING.property_name(),
        min=0.0,
        max=1000.0,
        default=MSFS2024_MaterialProperties.WINDSHIELDMICROSCRATCHTILING.default_value()
    )

    bpy.types.Material.msfs_windshield_micro_scratches_strength = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.WINDSHIELDMICROSCRATCHSTRENGTH.property_name(),
        min=0.0,
        max=100.0,
        default=MSFS2024_MaterialProperties.WINDSHIELDMICROSCRATCHSTRENGTH.default_value()
    )

    bpy.types.Material.msfs_windshield_detail_normal_refract_scale = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.WINDSHIELDDETAILNORMALREFRACTSCALE.property_name(),
        min=0.0,
        max=1.0,
        default=MSFS2024_MaterialProperties.WINDSHIELDDETAILNORMALREFRACTSCALE.default_value()
    )

    bpy.types.Material.msfs_windshield_wiper_lines = bpy.props.BoolProperty(
        name=MSFS2024_MaterialProperties.WINDSHIELDWIPERLINES.property_name(),
        default=MSFS2024_MaterialProperties.WINDSHIELDWIPERLINES.default_value()
    )

    bpy.types.Material.msfs_windshield_wiper_lines_strength = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.WINDSHIELDWIPERLINESSTRENGTH.property_name(),
        min=0.0,
        max=10.0,
        default=MSFS2024_MaterialProperties.WINDSHIELDWIPERLINESSTRENGTH.default_value()
    )

    bpy.types.Material.msfs_windshield_wiper_lines_tiling = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.WINDSHIELDWIPERLINESTILING.property_name(),
        min=0.0,
        max=100.0,
        default=MSFS2024_MaterialProperties.WINDSHIELDWIPERLINESTILING.default_value()
    )

    bpy.types.Material.msfs_windshield_wiper_1_state = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.WINDSHIELDWIPER1STATE.property_name(),
        min=0.0,
        max=1.0,
        default=MSFS2024_MaterialProperties.WINDSHIELDWIPER1STATE.default_value()
    )

    bpy.types.Material.msfs_ssr_attenuation = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.WINDSHIELDSSRATTENUATION.property_name(),
        min=0.0,
        max=1.0,
        default=MSFS2024_MaterialProperties.WINDSHIELDSSRATTENUATION.default_value()
    )

    bpy.types.Material.msfs_cubemap_reflection_masking = bpy.props.BoolProperty(
        name=MSFS2024_MaterialProperties.WINDSHIELDCUBEMAPREFLECTIONMASKING.property_name(),
        default=MSFS2024_MaterialProperties.WINDSHIELDCUBEMAPREFLECTIONMASKING.default_value()
    )
    # endregion

    # region Textures
    bpy.types.Material.msfs_windshield_wiper_mask_texture = bpy.props.PointerProperty(
        name=MSFS2024_MaterialProperties.WINDSHIELDWIPERMASKTEXTURE.property_name(),
        type=bpy.types.Image
    )

    bpy.types.Material.msfs_windshield_detail_normal_texture = bpy.props.PointerProperty(
        name=MSFS2024_MaterialProperties.WINDSHILEDDETAILNORMALTEXTURE.property_name(),
        type=bpy.types.Image
    )

    bpy.types.Material.msfs_windshield_scratches_normal_texture = bpy.props.PointerProperty(
        name=MSFS2024_MaterialProperties.WINDSHIELDSCRACHESNORMALTEXTURE.property_name(),
        type=bpy.types.Image
    )

    bpy.types.Material.msfs_windshield_insects_albedo_texture = bpy.props.PointerProperty(
        name=MSFS2024_MaterialProperties.WINDSHIELDINSECTSALBEDOTEXTURE.property_name(),
        type=bpy.types.Image
    )

    bpy.types.Material.msfs_windshield_insects_mask_texture = bpy.props.PointerProperty(
        name=MSFS2024_MaterialProperties.WINDSHIELDINSECTSMASKTEXTURE.property_name(),
        type=bpy.types.Image
    )
    # endregion

def unregister():
    try:
        del bpy.types.Material.msfs_windshield_detail_rough_1
        del bpy.types.Material.msfs_windshield_detail_rough_2
        del bpy.types.Material.msfs_windshield_detail_opacity_1
        del bpy.types.Material.msfs_windshield_detail_opacity_2
        del bpy.types.Material.msfs_windshield_micro_scratches_tiling
        del bpy.types.Material.msfs_windshield_micro_scratches_strength
        del bpy.types.Material.msfs_windshield_detail_normal_refract_scale
        del bpy.types.Material.msfs_windshield_wiper_lines
        del bpy.types.Material.msfs_windshield_wiper_lines_strength
        del bpy.types.Material.msfs_windshield_wiper_lines_tiling
        del bpy.types.Material.msfs_windshield_wiper_1_state
        del bpy.types.Material.msfs_windshield_wiper_mask_texture
        del bpy.types.Material.msfs_windshield_detail_normal_texture
        del bpy.types.Material.msfs_windshield_scratches_normal_texture
        del bpy.types.Material.msfs_windshield_insects_albedo_texture
        del bpy.types.Material.msfs_windshield_insects_mask_texture
    except:
        pass
