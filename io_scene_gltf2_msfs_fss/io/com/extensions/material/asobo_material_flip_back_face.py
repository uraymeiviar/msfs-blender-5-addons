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


class AsoboFlipBackFaceExtension:

    extension_name = "ASOBO_material_flip_back_face"

    @staticmethod
    def from_dict(blender_material, gltf2_material, import_settings):
        extensions = gltf2_material.extensions
        if extensions is None:
            return

        assert isinstance(extensions, dict)
        extension = extensions.get(AsoboFlipBackFaceExtension.extension_name)
        if extension is None:
            return

        setattr(
            blender_material, 
            MSFS2024_MaterialProperties.DOUBLESIDED.attribute_name(), 
            True
        )
        
        setattr(
            blender_material, 
            MSFS2024_MaterialProperties.FLIPBACKFACENORMAL.attribute_name(), 
            True
        )

    @staticmethod
    def to_extension(blender_material, gltf2_material, export_settings):
        double_sided = getattr(
            blender_material, 
            MSFS2024_MaterialProperties.DOUBLESIDED.attribute_name(), 
            False
        )
        
        if (
            double_sided 
            and getattr(
                blender_material, 
                MSFS2024_MaterialProperties.FLIPBACKFACENORMAL.attribute_name()
            )
        ):
            gltf2_material.extensions[AsoboFlipBackFaceExtension.extension_name] = Extension(
                name=AsoboFlipBackFaceExtension.extension_name, 
                extension={"enabled": True}, 
                required=False
            )

def register():
    bpy.types.Material.msfs_flip_back_face_normal = bpy.props.BoolProperty(
        name=MSFS2024_MaterialProperties.FLIPBACKFACENORMAL.property_name(),
        description="When this value is ON, the back face normal will be flipped.\n"
                     "This is useful to make translucent materials",
        default=MSFS2024_MaterialProperties.FLIPBACKFACENORMAL.default_value()
    )

def unregister():
    try:
        del bpy.types.Material.msfs_flip_back_face_normal
    except:
        pass
