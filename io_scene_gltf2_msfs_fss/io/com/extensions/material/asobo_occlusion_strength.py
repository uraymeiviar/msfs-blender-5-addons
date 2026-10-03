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

from .....blender.utils.msfs_material_utils import MSFS2024_MaterialProperties
from .....io.com.msfs_material_utils import MSFS2024_MaterialUtils


class AsoboOcclusionStrengthExtension:

    extension_name = "ASOBO_occlusion_strength"

    @staticmethod
    def from_dict(blender_material, gltf2_material, import_settings):
        extensions = gltf2_material.extensions
        if extensions is None:
            return

        assert isinstance(extensions, dict)
        extension = extensions.get(AsoboOcclusionStrengthExtension.extension_name)
        if extension is None:
            return

        MSFS2024_MaterialUtils.get_extension_parameter(
            extension=extension, 
            material=blender_material, 
            attribute=MSFS2024_MaterialProperties.OCCLUSIONSTRENGTH
        )

    @staticmethod
    def to_extension(blender_material, gltf2_material, export_settings):
        result = {}

        MSFS2024_MaterialUtils.set_extension_parameter(
            extension=result,
            material=blender_material,
            attribute=MSFS2024_MaterialProperties.OCCLUSIONSTRENGTH
        )
        
        if result:
            gltf2_material.extensions[AsoboOcclusionStrengthExtension.extension_name] = Extension(
                name=AsoboOcclusionStrengthExtension.extension_name, 
                extension=result, 
                required=False
            )


def register():
    bpy.types.Material.msfs_occlusion_strength = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.OCCLUSIONSTRENGTH.property_name(),
        min=0.0,
        max=2.0,
        default=MSFS2024_MaterialProperties.OCCLUSIONSTRENGTH.default_value(),
        precision=3
    )

def unregister():
    try: 
        del bpy.types.Material.msfs_occlusion_strength
    except:
        pass
