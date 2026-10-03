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

from .msfs_material_utils import MSFS2024_MaterialUtils

from .extensions.material.asobo_extra_occlusion import AsoboExtraOcclusionExtension
from .extensions.material.asobo_material_alphamode_dither import AsoboAlphaModeDither
from .extensions.material.asobo_material_anisotropic import AsoboAnisotropic
from .extensions.material.asobo_material_clear_coat import AsoboClearcoatExtension
from .extensions.material.asobo_material_code import AsoboMaterialCode
from .extensions.material.asobo_material_common import AsoboMaterialCommon
from .extensions.material.asobo_material_day_night_switch import AsoboDayNightCycleExtension
from .extensions.material.asobo_material_detail_map import AsoboMaterialDetailExtension
from .extensions.material.asobo_material_dirt import AsoboMaterialDirtExtension
from .extensions.material.asobo_material_disable_motion_blur import AsoboDisableMotionBlur
from .extensions.material.asobo_material_draw_order import AsoboMaterialDrawOrderExtension
from .extensions.material.asobo_material_environment_occluder import AsoboMaterialEnvironmentOccluderExtension
from .extensions.material.asobo_material_fake_terrain import AsoboMaterialFakeTerrainExtension
from .extensions.material.asobo_material_flip_back_face import AsoboFlipBackFaceExtension
from .extensions.material.asobo_material_foliage_mask import AsoboFoliageMaskExtension
from .extensions.material.asobo_material_fresnel_fade import AsoboMaterialFresnelFadeExtension
from .extensions.material.asobo_material_geometry_decal import AsoboMaterialGeometryDecalExtension
from .extensions.material.asobo_material_ghost_effect import AsoboMaterialGhostEffectExtension
from .extensions.material.asobo_material_glass import AsoboGlass
from .extensions.material.asobo_material_invisible import AsoboMaterialInvisible
from .extensions.material.asobo_material_iridescent import AsoboMaterialIridescentExtension
from .extensions.material.asobo_material_parallax_window import AsoboParallaxWindowExtension
from .extensions.material.asobo_material_pearlescent import AsoboPearlescentExtension
from .extensions.material.asobo_material_rain_options import AsoboRainOptionsExtension
from .extensions.material.asobo_material_sail import AsoboSailExtension
from .extensions.material.asobo_material_shadow_options import AsoboMaterialShadowOptionsExtension
from .extensions.material.asobo_material_sss import AsoboSSSExtension
from .extensions.material.asobo_material_uv_options import AsoboMaterialUVOptionsExtension
from .extensions.material.asobo_material_windshield import AsoboMaterialWindshieldExtension
from .extensions.material.asobo_occlusion_strength import AsoboOcclusionStrengthExtension
from .extensions.material.asobo_material_tire import AsoboMaterialTireExtension
from .extensions.material.asobo_material_emissive import AsoboMaterialEmissiveExtension
from .extensions.material.asobo_tags import AsoboTags

class MSFS2024_MaterialExtension:
    bl_options = {"UNDO"}

    extensions = [
        AsoboMaterialCommon,
        AsoboMaterialEmissiveExtension,
        AsoboMaterialGeometryDecalExtension,
        AsoboMaterialGhostEffectExtension,
        AsoboMaterialDrawOrderExtension,
        AsoboDayNightCycleExtension,
        AsoboDisableMotionBlur,
        AsoboPearlescentExtension,
        AsoboAlphaModeDither,
        AsoboMaterialInvisible,
        AsoboMaterialEnvironmentOccluderExtension,
        AsoboMaterialUVOptionsExtension,
        AsoboMaterialShadowOptionsExtension,
        AsoboMaterialDetailExtension,
        AsoboMaterialFakeTerrainExtension,
        AsoboMaterialFresnelFadeExtension,
        AsoboSSSExtension,
        AsoboAnisotropic,
        AsoboMaterialWindshieldExtension,
        AsoboClearcoatExtension,
        AsoboParallaxWindowExtension,
        AsoboGlass,
        AsoboTags,
        AsoboMaterialCode,
        AsoboFlipBackFaceExtension,
        AsoboMaterialDirtExtension,
        AsoboExtraOcclusionExtension,
        AsoboOcclusionStrengthExtension,
        AsoboRainOptionsExtension,
        AsoboMaterialIridescentExtension,
        AsoboFoliageMaskExtension,
        AsoboSailExtension,
        AsoboMaterialTireExtension
    ]

    def __new__(cls, *args, **kwargs):
        raise RuntimeError(f"{cls} should not be instantiated")

    @staticmethod
    def create(gltf2_material, blender_material, import_settings):
        if gltf2_material.extensions is None:
            gltf2_material.extensions = {}
        assert isinstance(gltf2_material.extensions, dict)
        for extension in MSFS2024_MaterialExtension.extensions:
            extension.from_dict(blender_material, gltf2_material, import_settings)

    @staticmethod
    def export(gltf2_material, blender_material, export_settings):        
        if gltf2_material.extensions is None:
            gltf2_material.extensions = {}
        
        for extension in MSFS2024_MaterialExtension.extensions:
            extension.to_extension(blender_material, gltf2_material, export_settings)
