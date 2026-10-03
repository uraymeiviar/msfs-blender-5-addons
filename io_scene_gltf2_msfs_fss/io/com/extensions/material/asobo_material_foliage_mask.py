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

class AsoboFoliageMaskExtension:

    extension_name = "ASOBO_material_foliage_mask"


    @staticmethod
    def from_dict(blender_material, gltf2_material, import_settings):

        extensions = gltf2_material.extensions
        if extensions is None:
            return

        assert isinstance(extensions, dict)
        extension = extensions.get(AsoboFoliageMaskExtension.extension_name)
        if extension is None:
            return

        MSFS2024_MaterialUtils.get_extension_texture(
            extension=extension,
            material=blender_material,
            attribute=MSFS2024_MaterialProperties.FOLIAGEMASKTEXTURE,
            settings=import_settings
        )

    @staticmethod
    def to_extension(blender_material, gltf2_material, export_settings):
        result = {}

        MSFS2024_MaterialUtils.set_extension_texture(
            extension=result,
            material=blender_material,
            attribute=MSFS2024_MaterialProperties.FOLIAGEMASKTEXTURE,
            settings=export_settings,
            texture_type="DEFAULT"
        )

        if result:            
            gltf2_material.extensions[AsoboFoliageMaskExtension.extension_name] = Extension(
                name=AsoboFoliageMaskExtension.extension_name, 
                extension=result, 
                required=False
            )

def register():
    bpy.types.Material.msfs_foliage_mask_texture = bpy.props.PointerProperty(
        name=MSFS2024_MaterialProperties.FOLIAGEMASKTEXTURE.property_name(), 
        type=bpy.types.Image
    )

def unregister():
    try:
        del bpy.types.Material.msfs_foliage_mask_texture
    except:
        pass
