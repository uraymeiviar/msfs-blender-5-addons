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
from .....blender.utils.msfs_material_utils import MSFS2024_MaterialProperties
from .....io.com.msfs_material_utils import MSFS2024_MaterialUtils


class AsoboMaterialUVOptionsExtension:

    extension_name = "ASOBO_material_UV_options"

    extension_parameters = [
        MSFS2024_MaterialProperties.CLAMPUVX,
        MSFS2024_MaterialProperties.CLAMPUVY,
        MSFS2024_MaterialProperties.UVOFFSETU,
        MSFS2024_MaterialProperties.UVOFFSETV,
        MSFS2024_MaterialProperties.UVTILINGU,
        MSFS2024_MaterialProperties.UVTILINGV,
        MSFS2024_MaterialProperties.UVROTATION
    ]

    @staticmethod
    def from_dict(blender_material, gltf2_material, import_settings):
        extensions = gltf2_material.extensions
        if extensions is None:
            return

        assert isinstance(extensions, dict)
        extension = extensions.get(AsoboMaterialUVOptionsExtension.extension_name)
        
        if extension is None:
            return

        for extension_parameter in AsoboMaterialUVOptionsExtension.extension_parameters:
            MSFS2024_MaterialUtils.get_extension_parameter(
                extension=extension,
                material=blender_material,
                attribute=extension_parameter
            )

    @staticmethod
    def to_extension(blender_material, gltf2_material, export_settings):
        result = {}
        
        for extension_parameter in AsoboMaterialUVOptionsExtension.extension_parameters:
            MSFS2024_MaterialUtils.set_extension_parameter(
                extension=result,
                material=blender_material,
                attribute=extension_parameter
            )

        if result:
            gltf2_material.extensions[AsoboMaterialUVOptionsExtension.extension_name] = Extension(
                name=AsoboMaterialUVOptionsExtension.extension_name,
                extension=result,
                required=False
            )

def register():
    bpy.types.Material.msfs_clamp_uv_x = bpy.props.BoolProperty(
        name=MSFS2024_MaterialProperties.CLAMPUVX.property_name(),
        default=MSFS2024_MaterialProperties.CLAMPUVX.default_value()
    )

    bpy.types.Material.msfs_clamp_uv_y = bpy.props.BoolProperty(
        name=MSFS2024_MaterialProperties.CLAMPUVY.property_name(),
        default=MSFS2024_MaterialProperties.CLAMPUVY.default_value()
    )

    bpy.types.Material.msfs_uv_offset_u = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.UVOFFSETU.property_name(),
        min=-10.0,
        max=10.0,
        default=MSFS2024_MaterialProperties.UVOFFSETU.default_value(),
        options={"ANIMATABLE"},
        set=MSFS2024_MaterialPropUpdate.set_uv_offset_u,
        get=MSFS2024_MaterialPropUpdate.get_uv_offset_u,
        precision=3
    )

    bpy.types.Material.msfs_uv_offset_v = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.UVOFFSETV.property_name(),
        min=-10.0,
        max=10.0,
        default=MSFS2024_MaterialProperties.UVOFFSETV.default_value(),
        options={"ANIMATABLE"},
        set=MSFS2024_MaterialPropUpdate.set_uv_offset_v,
        get=MSFS2024_MaterialPropUpdate.get_uv_offset_v,
        precision=3
    )

    bpy.types.Material.msfs_uv_tiling_u = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.UVTILINGU.property_name(),
        min=-10.0,
        max=100.0,
        default=MSFS2024_MaterialProperties.UVTILINGU.default_value(),
        options={"ANIMATABLE"},
        set=MSFS2024_MaterialPropUpdate.set_uv_tiling_u,
        get=MSFS2024_MaterialPropUpdate.get_uv_tiling_u,
        precision=3
    )

    bpy.types.Material.msfs_uv_tiling_v = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.UVTILINGV.property_name(),
        min=-10.0,
        max=100.0,
        default=MSFS2024_MaterialProperties.UVTILINGV.default_value(),
        options={"ANIMATABLE"},
        set=MSFS2024_MaterialPropUpdate.set_uv_tiling_v,
        get=MSFS2024_MaterialPropUpdate.get_uv_tiling_v,
        precision=3
    )

    bpy.types.Material.msfs_uv_rotation = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.UVROTATION.property_name(),
        min=-360.0,
        max=360.0,
        default=MSFS2024_MaterialProperties.UVROTATION.default_value(),
        options={"ANIMATABLE"},
        set=MSFS2024_MaterialPropUpdate.set_uv_rotation,
        get=MSFS2024_MaterialPropUpdate.get_uv_rotation,
        precision=3
    )

def unregister():
    try:
        del bpy.types.Material.msfs_clamp_uv_x
        del bpy.types.Material.msfs_clamp_uv_y
        del bpy.types.Material.msfs_uv_offset_u
        del bpy.types.Material.msfs_uv_offset_v
        del bpy.types.Material.msfs_uv_tiling_u
        del bpy.types.Material.msfs_uv_tiling_v
        del bpy.types.Material.msfs_uv_rotation
    except:
        pass
