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

from mathutils import Color

from io_scene_gltf2_msfs_fss.blender.msfs_lights import MSFS2024LightPropertiesEnum, MSFS2024LightType

class MSFS2024_LightUtils:
    advanced_light_shape_type_match_table = {
        "point": 1,
        "sphere": 2,
        "disc": 3
    }
    
    skyportal_light_shape_type_match_table = {
        "disc": 1
    }

    @staticmethod
    def get_extension_parameter(extension, light_data, attribute):
        
        if attribute.extension_name() is None:
            return
        
        if extension.get(attribute.extension_name()) is None:
            return
        
        attrib_name = attribute.attribute_name()
        value = extension.get(attribute.extension_name())
        msfs_light_properties = light_data.msfs_light_properties

        # Light shape
        if attrib_name == MSFS2024LightPropertiesEnum.LIGHTSHAPE.attribute_name():
            shape_type_match_table = {}
            if light_data.msfs_light_type == MSFS2024LightType.ADVANCED_LIGHT.identifier:
                shape_type_match_table = MSFS2024_LightUtils.advanced_light_shape_type_match_table
            elif light_data.msfs_light_type == MSFS2024LightType.SKYPORTAL_LIGHT.identifier:
                shape_type_match_table = MSFS2024_LightUtils.skyportal_light_shape_type_match_table
                
            for key, val in shape_type_match_table.items():
                if value == val:
                    value = key
        # endregion

        setattr(msfs_light_properties, attrib_name, value)
        
        ## Special case for retro compatibility
        if extension.get("has_simmetry") is not None:
            setattr(
                msfs_light_properties,
                attrib_name,
                extension.get("has_simmetry")
            )
        
    @staticmethod
    def set_extension_parameter(extension, light_data, attribute):
        if not attribute.extension_name():
            return
        
        # region Special Cases
        attrib_name = attribute.attribute_name()
        msfs_light_properties = light_data.msfs_light_properties
        value = getattr(msfs_light_properties, attrib_name)

        # Convert Colors to serializable list
        if isinstance(value, Color):
            value = list(value)

        # Light Shapes (advanced and skyportal only)
        if attrib_name == MSFS2024LightPropertiesEnum.LIGHTSHAPE.attribute_name():
            shape_type_match_table = {}
            if light_data.msfs_light_type == MSFS2024LightType.ADVANCED_LIGHT.identifier:
                shape_type_match_table = MSFS2024_LightUtils.advanced_light_shape_type_match_table
            elif light_data.msfs_light_type == MSFS2024LightType.SKYPORTAL_LIGHT.identifier:
                shape_type_match_table = MSFS2024_LightUtils.skyportal_light_shape_type_match_table

            value = shape_type_match_table[value]

        # endregion

        extension[attribute.extension_name()] = value
