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

from .....blender.material.msfs_material_properties_update import \
    MSFS2024_MaterialPropUpdate
    
from .....blender.utils.msfs_material_utils import (
    MSFS2024_MaterialProperties, 
    MSFS2024_MaterialTypes
)
from .....io.com.msfs_material_utils import MSFS2024_MaterialUtils

class AsoboSSSExtension:

    extension_name = "ASOBO_material_SSS"

    @staticmethod
    def from_dict(blender_material, gltf2_material, import_settings):
        extensions = gltf2_material.extensions
        if extensions is None:
            return

        assert isinstance(extensions, dict)
        extension = extensions.get(AsoboSSSExtension.extension_name)

        if extension is None:
            return

        ## Set Material Type To SSS
        setattr(
            blender_material, 
            MSFS2024_MaterialProperties.MATERIALTYPE.attribute_name(), 
            MSFS2024_MaterialTypes.SUBSURFACESCATTERING.value
        )

        MSFS2024_MaterialUtils.get_extension_parameter(
            extension=extension,
            material=blender_material,
            attribute=MSFS2024_MaterialProperties.SSSCOLOR
        )
        
        MSFS2024_MaterialUtils.get_extension_texture(
            extension=extension,
            material=blender_material,
            attribute=MSFS2024_MaterialProperties.OPACITYTEXTURE,
            settings=import_settings
        )

    @staticmethod
    def to_extension(blender_material, gltf2_material, export_settings):
        result = {}

        material_type = getattr(
            blender_material, 
            MSFS2024_MaterialProperties.MATERIALTYPE.attribute_name()
        )
        
        if (material_type in [MSFS2024_MaterialTypes.SUBSURFACESCATTERING.value, MSFS2024_MaterialTypes.HAIR.value]):
            
            sss_color = getattr(
                blender_material, 
                MSFS2024_MaterialProperties.SSSCOLOR.attribute_name()
            )
            result[MSFS2024_MaterialProperties.SSSCOLOR.extension_name()] = list(sss_color)

            MSFS2024_MaterialUtils.set_extension_texture(
                extension=result,
                material=blender_material,
                attribute=MSFS2024_MaterialProperties.OPACITYTEXTURE,
                settings=export_settings
            )
            
            gltf2_material.extensions[AsoboSSSExtension.extension_name] = Extension(
                name=AsoboSSSExtension.extension_name, 
                extension=result, 
                required=False
            )


def register():
    # region Parameters
    bpy.types.Material.msfs_sss_color = bpy.props.FloatVectorProperty(
        name=MSFS2024_MaterialProperties.SSSCOLOR.property_name(),
        description="The RGBA components of the SSS color of the material.\n"
                     "These values are linear. If a SSSTexture is specified, "
                     "this value is multiplied with the texel values",
        subtype = "COLOR",
        min=0.0,
        max=1.0,
        size=4,
        default=MSFS2024_MaterialProperties.SSSCOLOR.default_value(),
        update=MSFS2024_MaterialPropUpdate.update_color_sss
    )
    #endregion
    
    # region Textures
    bpy.types.Material.msfs_opacity_texture = bpy.props.PointerProperty(
        name=MSFS2024_MaterialProperties.OPACITYTEXTURE.property_name(), 
        type=bpy.types.Image
    )
    # endregion

def unregister():
    try:
        del bpy.types.Material.msfs_sss_color
        del bpy.types.Material.msfs_opacity_texture
    except:
        pass
