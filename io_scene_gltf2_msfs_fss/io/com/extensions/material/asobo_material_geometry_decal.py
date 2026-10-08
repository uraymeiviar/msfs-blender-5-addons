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
from .....blender.material.msfs_material_properties_update import MSFS2024_MaterialPropUpdate
from .....io.com.msfs_material_utils import MSFS2024_MaterialUtils

class AsoboMaterialGeometryDecalExtension:

    extension_name = "ASOBO_material_geometry_decal"

    extension_parameters = [
        MSFS2024_MaterialProperties.BASECOLORBLENDFACTOR,
        MSFS2024_MaterialProperties.METALLICBLENDFACTOR,
        MSFS2024_MaterialProperties.ROUGHNESSBLENDFACTOR,
        MSFS2024_MaterialProperties.NORMALBLENDFACTOR,
        MSFS2024_MaterialProperties.EMISSIVEBLENDFACTOR,
        MSFS2024_MaterialProperties.OCCLUSIONBLENDFACTOR,
        MSFS2024_MaterialProperties.NORMALOVERRIDEFACTOR,
        MSFS2024_MaterialProperties.DECALBLENDSHARPNESS,
        MSFS2024_MaterialProperties.UNDERCLEARCOAT
    ]

    required_decal_extension_parameters = [
        MSFS2024_MaterialProperties.SCENERY_CHANNEL,
        MSFS2024_MaterialProperties.TERRAIN_CHANNEL,
        MSFS2024_MaterialProperties.SIMOBJECT_CHANNEL
    ]

    @staticmethod
    def from_dict(blender_material, gltf2_material, import_settings):
        extensions = gltf2_material.extensions
        if extensions is None:
            return

        assert isinstance(extensions, dict)
        extension = extensions.get(AsoboMaterialGeometryDecalExtension.extension_name)
        
        # Retro Compatibility with old decals
        if extension is None:
            extension = extensions.get("ASOBO_material_blend_gbuffer")
            if extension is None:
                return
            extension[MSFS2024_MaterialProperties.DECALMODE.extension_name()] = (
                "default"
            )
        
        if extension is None:
            return

        decal_mode = extension.get(MSFS2024_MaterialProperties.DECALMODE.extension_name())
        if decal_mode == "default":
            setattr(
                blender_material,
                MSFS2024_MaterialProperties.MATERIALTYPE.attribute_name(),
                MSFS2024_MaterialTypes.DECAL.value
            )
        elif decal_mode == "frosted":
            setattr(
                blender_material,
                MSFS2024_MaterialProperties.MATERIALTYPE.attribute_name(),
                MSFS2024_MaterialTypes.GEODECALFROSTED.value
            )
        elif decal_mode == "blendMasked":
            setattr(
                blender_material,
                MSFS2024_MaterialProperties.MATERIALTYPE.attribute_name(),
                MSFS2024_MaterialTypes.GEODECALBLENDMASKED.value
            )

        for extension_parameter in AsoboMaterialGeometryDecalExtension.extension_parameters:
            MSFS2024_MaterialUtils.get_extension_parameter(
                extension=extension,
                material=blender_material,
                attribute=extension_parameter
            )

        MSFS2024_MaterialUtils.get_extension_texture(
            extension=extension,
            material=blender_material,
            attribute=MSFS2024_MaterialProperties.DECALBLENDMASKTEXTURE,
            settings=import_settings
        )

    @staticmethod
    def to_extension(blender_material, gltf2_material, export_settings):
        result = {}

        # Decal Mode
        decal_mode = getattr(
            blender_material,
            MSFS2024_MaterialProperties.DECALMODE.attribute_name()
        )

        if decal_mode == "":
            return

        result[MSFS2024_MaterialProperties.DECALMODE.extension_name()] = decal_mode

        for extension_parameter in AsoboMaterialGeometryDecalExtension.extension_parameters:
            MSFS2024_MaterialUtils.set_extension_parameter(
                extension=result,
                material=blender_material,
                attribute=extension_parameter
            )

        if decal_mode == "default":
            for extension_parameter in AsoboMaterialGeometryDecalExtension.required_decal_extension_parameters:
                MSFS2024_MaterialUtils.set_extension_parameter(
                    extension=result,
                    material=blender_material,
                    attribute=extension_parameter,
                    with_default_value=True
                )

        MSFS2024_MaterialUtils.set_extension_texture(
            extension=result,
            material=blender_material,
            attribute=MSFS2024_MaterialProperties.DECALBLENDMASKTEXTURE,
            settings=export_settings
        )

        if result:
            gltf2_material.extensions[AsoboMaterialGeometryDecalExtension.extension_name] = Extension(
                name=AsoboMaterialGeometryDecalExtension.extension_name,
                extension=result,
                required=False
            )

def register():
    # region Decal Properties
    bpy.types.Material.msfs_base_color_blend_factor = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.BASECOLORBLENDFACTOR.property_name(),
        min=0.0,
        max=1.0,
        default=MSFS2024_MaterialProperties.BASECOLORBLENDFACTOR.default_value()
    )

    bpy.types.Material.msfs_metallic_blend_factor = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.METALLICBLENDFACTOR.property_name(),
        min=0.0,
        max=1.0,
        default=MSFS2024_MaterialProperties.METALLICBLENDFACTOR.default_value()
    )

    bpy.types.Material.msfs_roughness_blend_factor = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.ROUGHNESSBLENDFACTOR.property_name(),
        min=0.0,
        max=1.0,
        default=MSFS2024_MaterialProperties.ROUGHNESSBLENDFACTOR.default_value()
    )

    bpy.types.Material.msfs_normal_blend_factor = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.NORMALBLENDFACTOR.property_name(),
        min=0.0,
        max=1.0,
        default=MSFS2024_MaterialProperties.NORMALBLENDFACTOR.default_value()
    )

    bpy.types.Material.msfs_emissive_blend_factor = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.EMISSIVEBLENDFACTOR.property_name(),
        min=0.0,
        max=1.0,
        default=MSFS2024_MaterialProperties.EMISSIVEBLENDFACTOR.default_value()
    )

    bpy.types.Material.msfs_occlusion_blend_factor = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.OCCLUSIONBLENDFACTOR.property_name(),
        min=0.0,
        max=1.0,
        default=MSFS2024_MaterialProperties.OCCLUSIONBLENDFACTOR.default_value()
    )

    bpy.types.Material.msfs_normal_override_blend_factor = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.NORMALOVERRIDEFACTOR.property_name(),
        min=0.0,
        max=1.0,
        default=MSFS2024_MaterialProperties.NORMALOVERRIDEFACTOR.default_value()
    )

    bpy.types.Material.msfs_decal_blend_sharpness = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.DECALBLENDSHARPNESS.property_name(),
        min=0.0,
        max=1.0,
        default=MSFS2024_MaterialProperties.DECALBLENDSHARPNESS.default_value(),
        update=MSFS2024_MaterialPropUpdate.update_blend_mask_sharpness
    )

    bpy.types.Material.msfs_under_clearcoat = bpy.props.BoolProperty(
        name=MSFS2024_MaterialProperties.UNDERCLEARCOAT.property_name(),
        default=MSFS2024_MaterialProperties.UNDERCLEARCOAT.default_value()
    )

    bpy.types.Material.msfs_decal_mode = bpy.props.StringProperty(
        name=MSFS2024_MaterialProperties.DECALMODE.property_name(),
        default=MSFS2024_MaterialProperties.DECALMODE.default_value()
    )

    bpy.types.Material.msfs_scenery_channel = bpy.props.BoolProperty(
        name=MSFS2024_MaterialProperties.SCENERY_CHANNEL.property_name(),
        default=MSFS2024_MaterialProperties.SCENERY_CHANNEL.default_value()
    )

    bpy.types.Material.msfs_terrain_channel = bpy.props.BoolProperty(
        name=MSFS2024_MaterialProperties.TERRAIN_CHANNEL.property_name(),
        default=MSFS2024_MaterialProperties.TERRAIN_CHANNEL.default_value()
    )

    bpy.types.Material.msfs_simobject_channel = bpy.props.BoolProperty(
        name=MSFS2024_MaterialProperties.SIMOBJECT_CHANNEL.property_name(),
        default=MSFS2024_MaterialProperties.SIMOBJECT_CHANNEL.default_value()
    )
    # endregion

    # region Textures
    bpy.types.Material.msfs_decal_blend_mask_texture = bpy.props.PointerProperty(
        name=MSFS2024_MaterialProperties.DECALBLENDMASKTEXTURE.property_name(),
        type=bpy.types.Image,
        update=MSFS2024_MaterialPropUpdate.update_decal_blend_mask_texture
    )
    # endregion

    #region Debug Shader
    bpy.types.Material.msfs_decal_freeze_factor = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.DECALFREEZEFACTOR.property_name(),
        min=0.0,
        max=1.0,
        default=MSFS2024_MaterialProperties.DECALFREEZEFACTOR.default_value(),
        update=MSFS2024_MaterialPropUpdate.update_freeze_factor
    )

    bpy.types.Material.msfs_decal_blend_masked_threshold = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.DECALBLENDMASKEDTHRESHOLD.property_name(),
        min=0.0,
        max=1.0,
        default=MSFS2024_MaterialProperties.DECALBLENDMASKEDTHRESHOLD.default_value(),
        update=MSFS2024_MaterialPropUpdate.update_blend_mask_threshold
    )
    # endregion

def unregister():
    try:
        del bpy.types.Material.msfs_base_color_blend_factor
        del bpy.types.Material.msfs_metallic_blend_factor
        del bpy.types.Material.msfs_roughness_blend_factor
        del bpy.types.Material.msfs_normal_blend_factor
        del bpy.types.Material.msfs_emissive_blend_factor
        del bpy.types.Material.msfs_occlusion_blend_factor
        del bpy.types.Material.msfs_normal_override_blend_factor
        del bpy.types.Material.msfs_decal_blend_sharpness
        del bpy.types.Material.msfs_under_clearcoat
        del bpy.types.Material.msfs_decal_mode
        del bpy.types.Material.msfs_scenery_channel
        del bpy.types.Material.msfs_terrain_channel
        del bpy.types.Material.msfs_simobject_channel
        del bpy.types.Material.msfs_decal_blend_mask_texture
        del bpy.types.Material.msfs_decal_freeze_factor
        del bpy.types.Material.msfs_decal_blend_masked_threshold
    except:
        pass
