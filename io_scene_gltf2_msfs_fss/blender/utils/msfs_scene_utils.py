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

from .msfs_material_nodes_utils import (
    MSFS2024_GroupNodes, 
    MSFS2024_MaterialProperties
)

from io_scene_gltf2_msfs_fss.blender.utils import msfs_object_utils

from ..material.msfs_material_properties_update import MSFS2024_MaterialPropUpdate

from io_scene_gltf2_msfs_fss.blender import msfs_lights
from io_scene_gltf2_msfs_fss.blender.msfs_lights import MSFS2024LightType
class MSFS2024_SceneUtils:

    # region Material Conversion
    @staticmethod
    def update_msfs2024_materials_graphs():
        # region Purge node groups
        groups = bpy.data.node_groups
        group_names = [x.value for x in list(MSFS2024_GroupNodes)]
        for group in groups:
            if group.name in group_names:
                bpy.data.node_groups.remove(group)
        # endregion

        # region Update shader materials
        for material in bpy.data.materials:
            if hasattr(material, MSFS2024_MaterialProperties.MATERIALTYPE.attribute_name()):
                MSFS2024_MaterialPropUpdate.update_msfs_material_type(
                    material=material,
                    rebuild_native_mat=False
                )
        # endregion
    # endregion

    # region Light conversion
    @staticmethod
    def convert_lights_to_msfs2024():
        light_objects = list(
            filter(
                lambda object: object.type == "LIGHT", bpy.data.objects
            )
        )

        for light_object in light_objects:
            light_data = light_object.data
            if light_data is None:
                continue

            if light_data.msfs_light_type != MSFS2024LightType.NONE.identifier:
                continue

            new_light_object = msfs_lights.create_light_object(MSFS2024LightType.STREET_LIGHT)

            new_light = new_light_object.data
            new_light.type = light_data.type
            new_light.diffuse_factor = light_data.diffuse_factor
            new_light.specular_factor = light_data.specular_factor
            new_light.volume_factor = light_data.volume_factor

            if hasattr(light_data, "shadow_soft_size"):
                new_light.shadow_soft_size = light_data.shadow_soft_size

            new_light_prop = new_light.msfs_light_properties
            new_light_prop.msfs_light_color = light_data.color
            new_light_prop.msfs_light_intensity = light_data.energy * 100

            if hasattr(light_object, "angle"):
                new_light_prop.msfs_light_cone_angle = light_data.angle

            if hasattr(light_object, "msfs_light_has_symmetry"):
                new_light_prop.msfs_light_has_symmetry = light_object.msfs_light_has_symmetry

            if hasattr(light_object, "msfs_light_flash_frequency"):
                new_light_prop.msfs_light_flash_frequency = light_object.msfs_light_flash_frequency

            if hasattr(light_object, "msfs_light_flash_duration"):
                new_light_prop.msfs_light_flash_duration = light_object.msfs_light_flash_duration

            if hasattr(light_object, "msfs_light_flash_phase"):
                new_light_prop.msfs_light_flash_phase = light_object.msfs_light_flash_phase

            if hasattr(light_object, "msfs_light_rotation_speed"):
                new_light_prop.msfs_light_rotation_speed = light_object.msfs_light_rotation_speed

            if hasattr(light_object, "msfs_light_day_night_cycle"):
                new_light_prop.msfs_light_day_night_cycle = light_object.msfs_light_day_night_cycle

            msfs_object_utils.replace_obj_by(light_object,new_light_object)
    # endregion

    @staticmethod
    def convert_scene_to_msfs2024():
        MSFS2024_SceneUtils.update_msfs2024_materials_graphs()
        MSFS2024_SceneUtils.convert_lights_to_msfs2024()
        return True
