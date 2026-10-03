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

from enum import Enum

from io_scene_gltf2.io.com.gltf2_io_extensions import Extension

from .....blender.utils.msfs_material_utils import MSFS2024_MaterialProperties

class AsoboTag(Enum):
    COLLISION = "Collision"
    ROAD = "Road"
    GROUND = "Ground"

class AsoboTags:

    extension_name = "ASOBO_tags"

    @staticmethod
    def from_dict(blender_material, gltf2_material, import_settings):
        extensions = gltf2_material.extensions
        if extensions is None:
            return

        assert isinstance(extensions, dict)
        extension = extensions.get(AsoboTags.extension_name)
        if extension is None:
            return

        if AsoboTag.COLLISION.value in extension.get("tags"):
            setattr(
                blender_material,
                MSFS2024_MaterialProperties.COLLISIONMATERIAL.attribute_name(),
                True
            )
            
        if AsoboTag.ROAD.value in extension.get("tags"):
            setattr(
                blender_material,
                MSFS2024_MaterialProperties.ROADCOLLISIONMATERIAL.attribute_name(),
                True
            )

        if AsoboTag.GROUND.value in extension.get("tags"):
            setattr(
                blender_material,
                MSFS2024_MaterialProperties.GROUNDCOLLISIONMATERIAL.attribute_name(),
                True
            )

    @staticmethod
    def to_extension(blender_material, gltf2_material, export_settings):
        result = {}

        tags = []

        if getattr(
            blender_material,
            MSFS2024_MaterialProperties.COLLISIONMATERIAL.attribute_name()
        ):
            tags.append(AsoboTag.COLLISION.value)
            
        if getattr(
            blender_material, 
            MSFS2024_MaterialProperties.ROADCOLLISIONMATERIAL.attribute_name()
        ):
            tags.append(AsoboTag.ROAD.value)

        if getattr(
            blender_material, 
            MSFS2024_MaterialProperties.GROUNDCOLLISIONMATERIAL.attribute_name()
        ):
            tags.append(AsoboTag.GROUND.value)

        if len(tags) > 0:
            result["tags"] = tags

            gltf2_material.extensions[AsoboTags.extension_name] = Extension(
                name=AsoboTags.extension_name, 
                extension=result, 
                required=False
            )


def register():
    bpy.types.Material.msfs_collision_material = bpy.props.BoolProperty(
        name=MSFS2024_MaterialProperties.COLLISIONMATERIAL.property_name(),
        default=MSFS2024_MaterialProperties.COLLISIONMATERIAL.default_value()
    )

    bpy.types.Material.msfs_road_collision_material = bpy.props.BoolProperty(
        name=MSFS2024_MaterialProperties.ROADCOLLISIONMATERIAL.property_name(),
        default=MSFS2024_MaterialProperties.ROADCOLLISIONMATERIAL.default_value()
    )

    bpy.types.Material.msfs_ground_collision_material = bpy.props.BoolProperty(
        name=MSFS2024_MaterialProperties.GROUNDCOLLISIONMATERIAL.property_name(),
        default=MSFS2024_MaterialProperties.GROUNDCOLLISIONMATERIAL.default_value()
    )
    
def unregister():
    try:
        del bpy.types.Material.msfs_collision_material
        del bpy.types.Material.msfs_road_collision_material
        del bpy.types.Material.msfs_ground_collision_material
    except:
        pass
