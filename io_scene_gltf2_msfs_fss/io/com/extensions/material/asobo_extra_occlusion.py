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

from pathlib import Path

from io_scene_gltf2.io.com.gltf2_io_extensions import Extension

from .....blender.utils.msfs_material_utils import MSFS2024_MaterialProperties
from .....blender.material.msfs_material_properties_update import MSFS2024_MaterialPropUpdate
from .....io.com.msfs_material_utils import MSFS2024_MaterialUtils

class AsoboExtraOcclusionExtension:

    extension_name = "ASOBO_extra_occlusion"
    
    @staticmethod
    def from_dict(blender_material, gltf2_material, import_settings):
        extensions = gltf2_material.extensions
        if extensions is None:
            return

        assert isinstance(extensions, dict)
        extension=extensions.get(AsoboExtraOcclusionExtension.extension_name)
        if extension is None:
            return

        MSFS2024_MaterialUtils.get_extension_texture(
            extension=extension,
            material=blender_material,
            attribute=MSFS2024_MaterialProperties.OCCLUSIONUV2,
            settings=import_settings
        )

    @staticmethod
    def to_extension(blender_material, gltf2_material, export_settings):
        result = {}

        MSFS2024_MaterialUtils.set_extension_texture(
            extension=result,
            material=blender_material,
            attribute=MSFS2024_MaterialProperties.OCCLUSIONUV2,
            settings=export_settings
        )

        if not result:
            return
        
        if hasattr(result[MSFS2024_MaterialProperties.OCCLUSIONUV2.extension_name()], "tex_coord"):
            result[MSFS2024_MaterialProperties.OCCLUSIONUV2.extension_name()].tex_coord = 1
        
        gltf2_material.extensions[AsoboExtraOcclusionExtension.extension_name] = Extension(
            name=AsoboExtraOcclusionExtension.extension_name, 
            extension=result, 
            required=False
        )

def register():
    bpy.types.Material.msfs_occlusion_uv2 = bpy.props.PointerProperty(
        name=MSFS2024_MaterialProperties.OCCLUSIONUV2.property_name(), 
        type=bpy.types.Image,
        update=MSFS2024_MaterialPropUpdate.update_occlusion_uv2_texture
    )

def unregister():
    try:
        del bpy.types.Material.msfs_occlusion_uv2
    except:
        pass
