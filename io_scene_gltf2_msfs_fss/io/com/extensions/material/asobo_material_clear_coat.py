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
from .....blender.utils.msfs_material_utils import (
    MSFS2024_MaterialProperties,
    MSFS2024_MaterialTypes
)
from .....io.com.msfs_material_utils import MSFS2024_MaterialUtils


class AsoboClearcoatExtension:

    extension_name = "ASOBO_material_clear_coat_v2"
    
    extension_parameters = [
        MSFS2024_MaterialProperties.CLEARCOATROUGHNESSFACTOR,
        MSFS2024_MaterialProperties.CLEARCOATNORMALFACTOR,
        MSFS2024_MaterialProperties.CLEARCOATINVERSEROUGHNESS,
        MSFS2024_MaterialProperties.BASE_NORMAL_AFFECT_COAT,
        MSFS2024_MaterialProperties.CLEARCOATCOLORROUGHNESSTILING,
        MSFS2024_MaterialProperties.CLEARCOATNORMALTILING
    ]

    extension_textures = [
        (MSFS2024_MaterialProperties.CLEARCOATNORMALTEXTURE, "NORMAL")
    ]

    @staticmethod
    def from_dict(blender_material, gltf2_material, import_settings):
        extensions = gltf2_material.extensions

        extension = extensions.get(AsoboClearcoatExtension.extension_name)
        if extension is None:
            return

        setattr(
            blender_material, MSFS2024_MaterialProperties.MATERIALTYPE.attribute_name(),
            MSFS2024_MaterialTypes.CLEARCOAT.value
        )

        for extension_parameter in AsoboClearcoatExtension.extension_parameters:
            MSFS2024_MaterialUtils.get_extension_parameter(
                extension=extension,
                material=blender_material,
                attribute=extension_parameter
            )

        for extension_texture in AsoboClearcoatExtension.extension_textures:
            if isinstance(extension_texture, tuple) and len(extension_texture) > 1:
                extension_texture = extension_texture[0]

            MSFS2024_MaterialUtils.get_extension_texture(
                extension=extension,
                material=blender_material,
                attribute=extension_texture,
                settings=import_settings
            )

        inverse_clearcoat_roughness = getattr(
            blender_material,
            MSFS2024_MaterialProperties.CLEARCOATINVERSEROUGHNESS.attribute_name()
        )
        if not inverse_clearcoat_roughness:
            # Clear coat roughness texture
            MSFS2024_MaterialUtils.get_extension_texture(
                extension=extension,
                material=blender_material,
                attribute=MSFS2024_MaterialProperties.CLEARCOATCOLORROUGHNESSTEXTURE,
                settings=import_settings
            )
        else:
            MSFS2024_MaterialUtils.get_extension_parameter(
                extension=extension,
                material=blender_material,
                attribute=MSFS2024_MaterialProperties.CLEARCOATBASEROUGHNESS
            )

    @staticmethod
    def to_extension(blender_material, gltf2_material, export_settings):
        # First clear "KHR_materials_clearcoat"
        if "KHR_materials_clearcoat" in gltf2_material.extensions:
            gltf2_material.extensions.pop("KHR_materials_clearcoat")

        material_type = getattr(
            blender_material,
            MSFS2024_MaterialProperties.MATERIALTYPE.attribute_name()
        )
        if material_type != MSFS2024_MaterialTypes.CLEARCOAT.value:
            return

        result = {}

        for extension_texture in AsoboClearcoatExtension.extension_textures:
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

        inverse_clearcoat_roughness = getattr(
            blender_material,
            MSFS2024_MaterialProperties.CLEARCOATINVERSEROUGHNESS.attribute_name()
        )

        if not inverse_clearcoat_roughness:
            MSFS2024_MaterialUtils.set_extension_texture(
                extension=result,
                material=blender_material,
                attribute=MSFS2024_MaterialProperties.CLEARCOATCOLORROUGHNESSTEXTURE,
                settings=export_settings
            )
        else:
            # We will need to export the clearcoat base roughness only if we
            # use uniform roughness is enabled
            MSFS2024_MaterialUtils.set_extension_parameter(
                extension=result,
                material=blender_material,
                attribute=MSFS2024_MaterialProperties.CLEARCOATBASEROUGHNESS
            )

        # Export other parameters
        for extension_parameter in AsoboClearcoatExtension.extension_parameters:
            MSFS2024_MaterialUtils.set_extension_parameter(
                extension=result,
                material=blender_material,
                attribute=extension_parameter
            )

        if not result:
            result = {"enabled": True}

        gltf2_material.extensions[AsoboClearcoatExtension.extension_name] = Extension(
            name=AsoboClearcoatExtension.extension_name,
            extension=result,
            required=False
        )


def update_inverse_clearcoat_roughness(self, context):
    if not self.msfs_clearcoat_inverse_roughness:
        self.msfs_clearcoat_base_roughness = MSFS2024_MaterialProperties.CLEARCOATBASEROUGHNESS.default_value()
             
def register():
    # region Extension Parameters
    bpy.types.Material.msfs_clearcoat_roughness_factor = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.CLEARCOATROUGHNESSFACTOR.property_name(),
        min=0.0,
        max=1.0,
        default=MSFS2024_MaterialProperties.CLEARCOATROUGHNESSFACTOR.default_value()
    )

    bpy.types.Material.msfs_clearcoat_normal_factor = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.CLEARCOATNORMALFACTOR.property_name(),
        min=0.0,
        max=1.0,
        default=MSFS2024_MaterialProperties.CLEARCOATNORMALFACTOR.default_value()
    )

    bpy.types.Material.msfs_clearcoat_color_roughness_tiling = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.CLEARCOATCOLORROUGHNESSTILING.property_name(),
        min=0.0,
        max=1000.0,
        default=MSFS2024_MaterialProperties.CLEARCOATCOLORROUGHNESSTILING.default_value()
    )

    bpy.types.Material.msfs_clearcoat_normal_tiling = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.CLEARCOATNORMALTILING.property_name(),
        min=0.0,
        max=1000.0,
        default=MSFS2024_MaterialProperties.CLEARCOATNORMALTILING.default_value()
    )

    bpy.types.Material.msfs_clearcoat_inverse_roughness = bpy.props.BoolProperty(
        name=MSFS2024_MaterialProperties.CLEARCOATINVERSEROUGHNESS.property_name(),
        default=MSFS2024_MaterialProperties.CLEARCOATINVERSEROUGHNESS.default_value(),
        description="Use the Roughness in the comp slot as the roughness used for the clearcoat layer",
        update=update_inverse_clearcoat_roughness
    )

    bpy.types.Material.msfs_clearcoat_base_roughness = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.CLEARCOATBASEROUGHNESS.property_name(),
        min=0.0,
        max=1.0,
        default=MSFS2024_MaterialProperties.CLEARCOATBASEROUGHNESS.default_value()
    )

    bpy.types.Material.msfs_base_normal_affect_coat = bpy.props.BoolProperty(
        name=MSFS2024_MaterialProperties.BASE_NORMAL_AFFECT_COAT.property_name(),
        default=MSFS2024_MaterialProperties.BASE_NORMAL_AFFECT_COAT.default_value(),
        description="This used to determine if the base normal affect or not the normal coat"
    )
    # endregion

    # region Textures
    bpy.types.Material.msfs_clearcoat_color_roughness_texture = bpy.props.PointerProperty(
        name=MSFS2024_MaterialProperties.CLEARCOATCOLORROUGHNESSTEXTURE.property_name(),
        type=bpy.types.Image,
        update=MSFS2024_MaterialPropUpdate.update_clearcoat_color_roughness_texture
    )

    bpy.types.Material.msfs_clearcoat_normal_texture = bpy.props.PointerProperty(
        name=MSFS2024_MaterialProperties.CLEARCOATNORMALTEXTURE.property_name(),
        type=bpy.types.Image,
        update=MSFS2024_MaterialPropUpdate.update_clearcoat_normal_texture
    )
    #endregion

def unregister():
    try:
        del bpy.types.Material.msfs_clearcoat_roughness_factor 
        del bpy.types.Material.msfs_clearcoat_normal_factor
        del bpy.types.Material.msfs_clearcoat_color_roughness_tiling
        del bpy.types.Material.msfs_clearcoat_normal_tiling
        del bpy.types.Material.msfs_clearcoat_inverse_roughness
        del bpy.types.Material.msfs_clearcoat_base_roughness
        del bpy.types.Material.msfs_base_normal_affect_coat
        del bpy.types.Material.msfs_clearcoat_color_roughness_texture
        del bpy.types.Material.msfs_clearcoat_normal_texture
    except:
        pass
