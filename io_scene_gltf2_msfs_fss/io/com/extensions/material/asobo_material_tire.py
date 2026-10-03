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
    MSFS2024_MaterialTypes,
)
from .....io.com.msfs_material_utils import MSFS2024_MaterialUtils

class AsoboMaterialTireExtension:

    extension_name = "ASOBO_material_tire"
    
    extension_parameters = [
        MSFS2024_MaterialProperties.TIREMUDNORMALTILING,
        MSFS2024_MaterialProperties.TIREDUSTANIMSTATE,
        MSFS2024_MaterialProperties.TIREMUDANIMSTATE
    ]
    
    extension_textures = [
        MSFS2024_MaterialProperties.TIREMUDCUTOUTTEXTURE,
        MSFS2024_MaterialProperties.TIREDETAILSTEXTURE,
        (MSFS2024_MaterialProperties.TIREMUDNORMALTEXTURE, "NORMAL")
    ]
    
    @staticmethod
    def from_dict(blender_material, gltf2_material, import_settings):
        extensions = gltf2_material.extensions
        if extensions is None:
            return

        assert isinstance(extensions, dict)
        extension = extensions.get(AsoboMaterialTireExtension.extension_name)

        if extension is None:
            return

        setattr(
            blender_material,
            MSFS2024_MaterialProperties.MATERIALTYPE.attribute_name(),
            MSFS2024_MaterialTypes.TIRE.value
        )

        for extension_parameter in AsoboMaterialTireExtension.extension_parameters:
            MSFS2024_MaterialUtils.get_extension_parameter(
                extension=extension,
                material=blender_material,
                attribute=extension_parameter
            )
            
        for extension_texture in AsoboMaterialTireExtension.extension_textures:
            if isinstance(extension_texture, tuple) and len(extension_texture) > 1:
                extension_texture = extension_texture[0]

            MSFS2024_MaterialUtils.get_extension_texture(
                extension=extension,
                material=blender_material,
                attribute=extension_texture,
                settings=import_settings
            )
        

    @staticmethod
    def to_extension(blender_material, gltf2_material, export_settings):
        result = {}
        
        for extension_parameter in AsoboMaterialTireExtension.extension_parameters:
            MSFS2024_MaterialUtils.set_extension_parameter(
                extension=result,
                material=blender_material,
                attribute=extension_parameter
            )

        for extension_texture in AsoboMaterialTireExtension.extension_textures:
            texture_type="DEFAULT"
            
            if isinstance(extension_texture, tuple) and len(extension_texture) > 1:
                texture_type=extension_texture[1]
                extension_texture = extension_texture[0]

            MSFS2024_MaterialUtils.set_extension_texture(
                extension=result,
                material=blender_material,
                attribute=extension_texture,
                settings=export_settings,
                texture_type=texture_type
            )
            
        if not result:
            return
        
        gltf2_material.extensions[AsoboMaterialTireExtension.extension_name] = Extension(
            name=AsoboMaterialTireExtension.extension_name,
            extension=result,
            required=False
        )

def register():
    #region Parameters
    bpy.types.Material.msfs_tire_mud_normal_tiling = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.TIREMUDNORMALTILING.property_name(),
        min=0.0,
        max=100.0,
        default=MSFS2024_MaterialProperties.TIREMUDNORMALTILING.default_value(),
        options={"ANIMATABLE"}
    )

    bpy.types.Material.msfs_tire_mud_anim_state = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.TIREMUDANIMSTATE.property_name(),
        min=0.0,
        max=1.0,
        default=MSFS2024_MaterialProperties.TIREMUDANIMSTATE.default_value(),
        options={"ANIMATABLE"}
    )
    
    bpy.types.Material.msfs_tire_dust_anim_state = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.TIREDUSTANIMSTATE.property_name(),
        min=0.0,
        max=1.0,
        default=MSFS2024_MaterialProperties.TIREDUSTANIMSTATE.default_value(),
        options={"ANIMATABLE"}
    )
    #endregion
    
    #region Textures
    bpy.types.Material.msfs_tire_mud_cutout_texture = bpy.props.PointerProperty(
        name=MSFS2024_MaterialProperties.TIREMUDCUTOUTTEXTURE.property_name(),
        type=bpy.types.Image
    )
    
    bpy.types.Material.msfs_tire_details_texture = bpy.props.PointerProperty(
        name=MSFS2024_MaterialProperties.TIREDETAILSTEXTURE.property_name(),
        type=bpy.types.Image
    )
    
    bpy.types.Material.msfs_tire_mud_normal_texture = bpy.props.PointerProperty(
        name=MSFS2024_MaterialProperties.TIREMUDNORMALTEXTURE.property_name(),
        type=bpy.types.Image
    )
    #endregion

def unregister():
    try:
        del bpy.types.Material.msfs_tire_mud_normal_tiling
        del bpy.types.Material.msfs_tire_mud_anim_state
        del bpy.types.Material.msfs_tire_dust_anim_state
        del bpy.types.Material.msfs_tire_mud_cutout_texture
        del bpy.types.Material.msfs_tire_details_texture
        del bpy.types.Material.msfs_tire_mud_normal_texture
    except:
        pass
