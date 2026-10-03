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

from io_scene_gltf2_msfs_fss.blender import msfs_lights
from io_scene_gltf2_msfs_fss.blender.msfs_lights import MSFS2024LightPropertiesEnum

from io_scene_gltf2_msfs_fss.blender.utils import msfs_object_utils
from io_scene_gltf2_msfs_fss.io.com.msfs_light_utils import MSFS2024_LightUtils

class AsoboStreetLight:
    bl_options = {"UNDO"}

    extension_name = "ASOBO_street_light"

    extension_parameters = [
        MSFS2024LightPropertiesEnum.LIGHTCOLOR,
        MSFS2024LightPropertiesEnum.LIGHTINTENSITY,
        MSFS2024LightPropertiesEnum.LIGHTDAYNIGHTCYCLE,
        MSFS2024LightPropertiesEnum.LIGHTCONEANGLE,
        MSFS2024LightPropertiesEnum.HASLIGHTSYMMETRY,
        MSFS2024LightPropertiesEnum.LIGHTFLASHFREQUENCY,
        MSFS2024LightPropertiesEnum.LIGHTFLASHDURATION,
        MSFS2024LightPropertiesEnum.LIGHTFLASHPHASE,
        MSFS2024LightPropertiesEnum.LIGHTROTATIONPHASE,
        MSFS2024LightPropertiesEnum.LIGHTROTATIONSPEED,
        MSFS2024LightPropertiesEnum.LIGHTRANDOMPHASE,
        MSFS2024LightPropertiesEnum.FLARE_ENABLED,
        MSFS2024LightPropertiesEnum.FLARE_ONLY
    ]

    def __new__(cls, *args, **kwargs):
        raise RuntimeError(f"{cls} should not be instantiated")

    @classmethod
    def from_extension(cls, vnode, gltf2_node, blender_object):
        """
        Set proper Light properties on the blender object
        """

        if not gltf2_node:
            return

        if not gltf2_node.extensions:
            return

        extension = gltf2_node.extensions.get(cls.extension_name)
        if not extension:
            return
        if blender_object.data and isinstance(blender_object.data, bpy.types.Light):
            msfs_lights.set_light_data(
                msfs_lights.MSFS2024LightType.STREET_LIGHT, blender_object.data
            )
        else:
            # Should not happen, since gltf importer automatically creates a light.
            # in this case we replace blender_object
            light = msfs_lights.create_light_object(
                msfs_lights.MSFS2024LightType.STREET_LIGHT
            )
            blender_object = msfs_object_utils.replace_obj_by(
                obj_to_replace=blender_object,
                new_obj=light,
                transform=True,
                delete=True,
            )
            vnode.blender_object = blender_object

        ## set MSFS2024 parameter with check day/night
        if extension.get(MSFS2024LightPropertiesEnum.LIGHTDAYNIGHTCYCLE.extension_name()) == False:
            attrib_name = MSFS2024LightPropertiesEnum.LIGHTDAYTIMEINTENSITY.attribute_name()
            override_value = extension.get(MSFS2024LightPropertiesEnum.LIGHTDAYTIMEINTENSITY.extension_name())
            if override_value != None:
                setattr(blender_object.data.msfs_light_properties, attrib_name, override_value)

        # Set MSFS2024 Parameters
        for extension_parameter in cls.extension_parameters:
            MSFS2024_LightUtils.get_extension_parameter(
                extension=extension,
                light_data=blender_object.data,
                attribute=extension_parameter
            )

    @classmethod
    def export(cls, gltf2_object, blender_object):
        # First, clear all KHR_lights_punctual extensions from children.
        for child in gltf2_object.children:
            if isinstance(child.extensions, dict) and (
                "KHR_lights_punctual" in child.extensions
            ):
                child.extensions.pop("KHR_lights_punctual")

        if isinstance(gltf2_object.extensions, dict) and (
            "KHR_lights_punctual" in gltf2_object.extensions
        ):
            gltf2_object.extensions.pop("KHR_lights_punctual")

        extension = {}

        light_data = blender_object.data
        light_type = getattr(
            light_data,
            MSFS2024LightPropertiesEnum.LIGHTTYPE.attribute_name()
        )
        if light_type!= msfs_lights.MSFS2024LightType.STREET_LIGHT.identifier:
            return

        ## set extension parameter with check day/night
        day_night = light_data.msfs_light_properties.get(MSFS2024LightPropertiesEnum.LIGHTDAYNIGHTCYCLE.attribute_name())
        if day_night == False:
            attrib_name = MSFS2024LightPropertiesEnum.LIGHTDAYTIMEINTENSITY.attribute_name()
            extension[MSFS2024LightPropertiesEnum.LIGHTDAYTIMEINTENSITY.extension_name()] = light_data.msfs_light_properties.get(attrib_name)

        for extension_parameter in cls.extension_parameters:
            MSFS2024_LightUtils.set_extension_parameter(
                extension=extension,
                light_data=light_data,
                attribute=extension_parameter
            )

        gltf2_object.extensions[cls.extension_name] = Extension(
            name=cls.extension_name,
            extension=extension,
            required=False
        )
