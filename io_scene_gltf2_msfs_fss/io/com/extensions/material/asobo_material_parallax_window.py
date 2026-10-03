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

class AsoboParallaxWindowExtension:

    extension_name = "ASOBO_material_parallax_window"

    extension_parameters = [
        MSFS2024_MaterialProperties.PARALLAXROOMSIZEX,
        MSFS2024_MaterialProperties.PARALLAXROOMSIZEY,
        MSFS2024_MaterialProperties.PARALLAXROOMSIZEZ,
        MSFS2024_MaterialProperties.PARALLAXROOMCOUNT,
        MSFS2024_MaterialProperties.PARALLAXCORRIDOR
    ]
    
    @staticmethod
    def from_dict(blender_material, gltf2_material, import_settings):
        extensions = gltf2_material.extensions
        if extensions is None:
            return

        assert isinstance(extensions, dict)
        extension = extensions.get(AsoboParallaxWindowExtension.extension_name)
        if extension is None:
            return

        setattr(
            blender_material, 
            MSFS2024_MaterialProperties.MATERIALTYPE.attribute_name(), 
            MSFS2024_MaterialTypes.PARALLAXWINDOW.value
        )
        
        for extension_parameter in AsoboParallaxWindowExtension.extension_parameters:
            MSFS2024_MaterialUtils.get_extension_parameter(
                extension=extension, 
                material=blender_material,
                attribute=extension_parameter
            )

        MSFS2024_MaterialUtils.get_extension_texture(
            extension=extension,
            material=blender_material,
            attribute=MSFS2024_MaterialProperties.BEHINDGLASSCOLORTEXTURE,
            settings=import_settings
        )

    @staticmethod
    def to_extension(blender_material, gltf2_material, export_settings):
        material_type = getattr(
            blender_material, 
            MSFS2024_MaterialProperties.MATERIALTYPE.attribute_name()
        )
        
        if material_type != MSFS2024_MaterialTypes.PARALLAXWINDOW.value:
            return

        result = {}

        for extension_parameter in AsoboParallaxWindowExtension.extension_parameters:
            MSFS2024_MaterialUtils.set_extension_parameter(
                extension=result,
                material=blender_material,
                attribute=extension_parameter,
                with_default_value=True
            )

        MSFS2024_MaterialUtils.set_extension_texture(
            extension=result, 
            material=blender_material, 
            attribute=MSFS2024_MaterialProperties.BEHINDGLASSCOLORTEXTURE, 
            settings=export_settings
        )

        gltf2_material.extensions[AsoboParallaxWindowExtension.extension_name] = Extension(
            name=AsoboParallaxWindowExtension.extension_name,
            extension=result,
            required=False
        )

def register():
    # region Parameters
    bpy.types.Material.msfs_parallax_room_size_x = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.PARALLAXROOMSIZEX.property_name(),
        min=0.01,
        max=10.0,
        default=MSFS2024_MaterialProperties.PARALLAXROOMSIZEX.default_value()
    )

    bpy.types.Material.msfs_parallax_room_size_y = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.PARALLAXROOMSIZEY.property_name(),
        min=0.01,
        max=10.0,
        default=MSFS2024_MaterialProperties.PARALLAXROOMSIZEY.default_value()
    )

    bpy.types.Material.msfs_parallax_room_size_z = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.PARALLAXROOMSIZEZ.property_name(),
        min=0.01,
        max=1.0,
        default=MSFS2024_MaterialProperties.PARALLAXROOMSIZEZ.default_value()
    )

    bpy.types.Material.msfs_parallax_room_count_xy = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.PARALLAXROOMCOUNT.property_name(),
        min=1,
        max=16,
        default=MSFS2024_MaterialProperties.PARALLAXROOMCOUNT.default_value()
    )

    bpy.types.Material.msfs_parallax_corridor = bpy.props.BoolProperty(
        name=MSFS2024_MaterialProperties.PARALLAXCORRIDOR.property_name(),
        default=MSFS2024_MaterialProperties.PARALLAXCORRIDOR.default_value()
    )
    # endregion
    # region Textures
    bpy.types.Material.msfs_behind_glass_color_texture = bpy.props.PointerProperty(
        name=MSFS2024_MaterialProperties.BEHINDGLASSCOLORTEXTURE.property_name(),
        type=bpy.types.Image,
        update=MSFS2024_MaterialPropUpdate.update_behind_glass_color_texture
    )
    # endregion

def unregister():
    try:
        del bpy.types.Material.msfs_parallax_room_size_x
        del bpy.types.Material.msfs_parallax_room_size_y
        del bpy.types.Material.msfs_parallax_room_size_z
        del bpy.types.Material.msfs_parallax_room_count_xy
        del bpy.types.Material.msfs_parallax_corridor
        del bpy.types.Material.msfs_behind_glass_color_texture
    except:
        pass
    