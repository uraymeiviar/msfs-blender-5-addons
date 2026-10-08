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

from typing import Any
from ..utils.msfs_material_utils import (
    MSFS2024_MaterialProperties, 
    MSFS2024_MaterialTypes
)

from .msfs_material import MSFS2024_Material
from .msfs_material_anisotropic import MSFS2024_Anisotropic
from .msfs_material_clearcoat import MSFS2024_Clearcoat
from .msfs_material_environment_occluder import MSFS2024_Environment_Occluder
from .msfs_material_fake_terrain import MSFS2024_Fake_Terrain
from .msfs_material_fresnel_fade import MSFS2024_Fresnel_Fade
from .msfs_material_geo_decal import MSFS2024_Geo_Decal
from .msfs_material_geo_decal_blendmasked import MSFS2024_Geo_Decal_BlendMasked
from .msfs_material_geo_decal_frosted import MSFS2024_Geo_Decal_Frosted
from .msfs_material_ghost import MSFS2024_Ghost
from .msfs_material_glass import MSFS2024_Glass
from .msfs_material_hair import MSFS2024_Hair
from .msfs_material_invisible import MSFS2024_Invisible
from .msfs_material_parallax import MSFS2024_Parallax
from .msfs_material_porthole import MSFS2024_Porthole
from .msfs_material_propeller import MSFS2024_Propeller
from .msfs_material_sail import MSFS2024_Sail
from .msfs_material_sss import MSFS2024_SSS
from .msfs_material_standard import MSFS2024_Standard
from .msfs_material_tree import MSFS2024_Tree
from .msfs_material_vegetation import MSFS2024_Vegetation
from .msfs_material_windshield import MSFS2024_Windshield
from .msfs_material_tire import MSFS2024_Tire

from io_scene_gltf2_msfs_fss.blender import msfs_image

class MSFS2024_MaterialPropUpdate:

    @staticmethod
    def get_material(material: bpy.types.Material) -> MSFS2024_Material|None:
        match getattr(material, MSFS2024_MaterialProperties.MATERIALTYPE.attribute_name()):
            case MSFS2024_MaterialTypes.STANDARD.value:
                return MSFS2024_Standard(material)
            case MSFS2024_MaterialTypes.DECAL.value:
                return MSFS2024_Geo_Decal(material)
            case MSFS2024_MaterialTypes.GEODECALFROSTED.value:
                return MSFS2024_Geo_Decal_Frosted(material)
            case MSFS2024_MaterialTypes.GEODECALBLENDMASKED.value:
                return MSFS2024_Geo_Decal_BlendMasked(material)
            case MSFS2024_MaterialTypes.WINDSHIELD.value:
                return MSFS2024_Windshield(material)
            case MSFS2024_MaterialTypes.PORTHOLE.value:
                return MSFS2024_Porthole(material)
            case MSFS2024_MaterialTypes.GLASS.value:
                return MSFS2024_Glass(material)
            case MSFS2024_MaterialTypes.CLEARCOAT.value:
                return MSFS2024_Clearcoat(material)
            case MSFS2024_MaterialTypes.PARALLAXWINDOW.value:
                return MSFS2024_Parallax(material)
            case MSFS2024_MaterialTypes.ANISOTROPIC.value:
                return MSFS2024_Anisotropic(material)
            case MSFS2024_MaterialTypes.HAIR.value:
                return MSFS2024_Hair(material)
            case MSFS2024_MaterialTypes.SUBSURFACESCATTERING.value:
                return MSFS2024_SSS(material)
            case MSFS2024_MaterialTypes.INVISIBLE.value:
                return MSFS2024_Invisible(material)
            case MSFS2024_MaterialTypes.FAKETERRAIN.value:
                return MSFS2024_Fake_Terrain(material)
            case MSFS2024_MaterialTypes.FRESNELFADE.value:
                return MSFS2024_Fresnel_Fade(material)
            case MSFS2024_MaterialTypes.ENVIRONMENTOCCLUDER.value:
                return MSFS2024_Environment_Occluder(material)
            case MSFS2024_MaterialTypes.GHOST.value:
                return MSFS2024_Ghost(material)
            case MSFS2024_MaterialTypes.SAIL.value:
                return MSFS2024_Sail(material)
            case MSFS2024_MaterialTypes.PROPELLER.value:
                return MSFS2024_Propeller(material)
            case MSFS2024_MaterialTypes.TREE.value:
                return MSFS2024_Tree(material)
            case MSFS2024_MaterialTypes.VEGETATION.value:
                return MSFS2024_Vegetation(material)
            case MSFS2024_MaterialTypes.TIRE.value:
                return MSFS2024_Tire(material)
            case _:
                return None

    @staticmethod
    def update_msfs_material_type(
        material: Any,
        rebuild_native_mat: bool = True,
        build_tree: bool = True
    ) -> Any:
        match getattr(material, MSFS2024_MaterialProperties.MATERIALTYPE.attribute_name()):
            case MSFS2024_MaterialTypes.STANDARD.value:
                MSFS2024_Standard(material, build_tree=build_tree)
            case MSFS2024_MaterialTypes.DECAL.value:
                MSFS2024_Geo_Decal(material, build_tree=build_tree)
            case MSFS2024_MaterialTypes.GEODECALFROSTED.value:
                MSFS2024_Geo_Decal_Frosted(material, build_tree=build_tree)
            case MSFS2024_MaterialTypes.WINDSHIELD.value:
                MSFS2024_Windshield(material, build_tree=build_tree)
            case MSFS2024_MaterialTypes.PORTHOLE.value:
                MSFS2024_Porthole(material, build_tree=build_tree)
            case MSFS2024_MaterialTypes.GLASS.value:
                MSFS2024_Glass(material, build_tree=build_tree)
            case MSFS2024_MaterialTypes.CLEARCOAT.value:
                MSFS2024_Clearcoat(material, build_tree=build_tree)
            case MSFS2024_MaterialTypes.PARALLAXWINDOW.value:
                MSFS2024_Parallax(material, build_tree=build_tree)
            case MSFS2024_MaterialTypes.ANISOTROPIC.value:
                MSFS2024_Anisotropic(material, build_tree=build_tree)
            case MSFS2024_MaterialTypes.HAIR.value:
                MSFS2024_Hair(material, build_tree=build_tree)
            case MSFS2024_MaterialTypes.SUBSURFACESCATTERING.value:
                MSFS2024_SSS(material, build_tree=build_tree)
            case MSFS2024_MaterialTypes.INVISIBLE.value:
                MSFS2024_Invisible(material, build_tree=build_tree)
            case MSFS2024_MaterialTypes.FAKETERRAIN.value:
                MSFS2024_Fake_Terrain(material, build_tree=build_tree)
            case MSFS2024_MaterialTypes.FRESNELFADE.value:
                MSFS2024_Fresnel_Fade(material, build_tree=build_tree)
            case MSFS2024_MaterialTypes.ENVIRONMENTOCCLUDER.value:
                MSFS2024_Environment_Occluder(material, build_tree=build_tree)
            case MSFS2024_MaterialTypes.GHOST.value:
                MSFS2024_Ghost(material, build_tree=build_tree)
            case MSFS2024_MaterialTypes.GEODECALBLENDMASKED.value:
                MSFS2024_Geo_Decal_BlendMasked(material, build_tree=build_tree)
            case MSFS2024_MaterialTypes.SAIL.value:
                MSFS2024_Sail(material, build_tree=build_tree)
            case MSFS2024_MaterialTypes.PROPELLER.value:
                MSFS2024_Propeller(material, build_tree=build_tree)
            case MSFS2024_MaterialTypes.TREE.value:
                MSFS2024_Tree(material, build_tree=build_tree)
            case MSFS2024_MaterialTypes.VEGETATION.value:
                MSFS2024_Vegetation(material, build_tree=build_tree)
            case MSFS2024_MaterialTypes.TIRE.value:
                MSFS2024_Tire(material, build_tree=build_tree)
            case _:
                MSFS2024_Material(material, build_tree=False, revert_to_pbr=rebuild_native_mat)

    @staticmethod
    def _validate_material_image(
        material: bpy.types.Material,
        attribute_name: str,
        alpha_mode: msfs_image.ImageAlphaMode,
        colorspace: msfs_image.ImageColorSpace,
    ) -> bpy.types.Image:
        
        image = getattr(material, attribute_name, None)

        # PointerProperty does not support a custom setter/getter, and assigning
        # through the ID-property API (material[attribute_name] = image) cannot
        # be used to update this property in Blender 5.2.
        #
        # Assigning with setattr() triggers the property's update callback again,
        # so use a temporary ID-property as a recursion guard.

        recursion_flag = "__validating_mat_image__"
        if material.get(recursion_flag):
            del material[recursion_flag]
            return image
    
        if isinstance(image, bpy.types.Image):
            image = msfs_image.validate_image(
                image=image,
                alpha_mode=alpha_mode,
                colorspace=colorspace,
            )

            # The assignment triggers the PointerProperty update callback again.
            # Set the guard first so the recursive invocation returns immediately.
            material[recursion_flag] = True
            setattr(material, attribute_name, image)
            
        return image

    @staticmethod
    def update_base_color_texture(material, context):
        msfs_material = MSFS2024_MaterialPropUpdate.get_material(material)
        if msfs_material is None:
            return
        image = MSFS2024_MaterialPropUpdate._validate_material_image(
            material,
            MSFS2024_MaterialProperties.BASECOLORTEXTURE.attribute_name(),
            msfs_image.ImageAlphaMode.CHANNEL_PACKED,
            msfs_image.ImageColorSpace.SRGB,
        )

        if not isinstance(msfs_material, MSFS2024_Invisible):
            msfs_material.set_base_color_tex(image)

    @staticmethod
    def update_comp_texture(material, context):
        msfs_material = MSFS2024_MaterialPropUpdate.get_material(material)
        if msfs_material is None:
            return
        image = MSFS2024_MaterialPropUpdate._validate_material_image(
            material,
            MSFS2024_MaterialProperties.OMRTEXTURE.attribute_name(),
            msfs_image.ImageAlphaMode.NONE,
            msfs_image.ImageColorSpace.NON_COLOR,
        )

        if not isinstance(msfs_material, MSFS2024_Invisible):
            msfs_material.set_omr_tex(
                image
            )

    @staticmethod
    def update_normal_texture(material, context):
        msfs_material = MSFS2024_MaterialPropUpdate.get_material(material)
        if msfs_material is None:
            return

        image = MSFS2024_MaterialPropUpdate._validate_material_image(
            material,
            MSFS2024_MaterialProperties.NORMALTEXTURE.attribute_name(),
            msfs_image.ImageAlphaMode.NONE,
            msfs_image.ImageColorSpace.NON_COLOR,
        )

        if not isinstance(msfs_material, MSFS2024_Invisible):
            msfs_material.set_normal_tex(
                image
            )

    @staticmethod
    def update_emissive_texture(material, context):
        msfs_material = MSFS2024_MaterialPropUpdate.get_material(material)
        if msfs_material is None:
            return

        image = MSFS2024_MaterialPropUpdate._validate_material_image(
            material,
            MSFS2024_MaterialProperties.EMISSIVETEXTURE.attribute_name(),
            msfs_image.ImageAlphaMode.NONE,
            msfs_image.ImageColorSpace.NON_COLOR,
        )
        if not isinstance(msfs_material, MSFS2024_Invisible):
            msfs_material.set_emissive_tex(image)

    @staticmethod
    def update_detail_color_texture(material, context):
        msfs_material = MSFS2024_MaterialPropUpdate.get_material(material)
        if msfs_material is None:
            return
        image = MSFS2024_MaterialPropUpdate._validate_material_image(
            material,
            MSFS2024_MaterialProperties.DETAILCOLORTEXTURE.attribute_name(),
            msfs_image.ImageAlphaMode.CHANNEL_PACKED,
            msfs_image.ImageColorSpace.SRGB,
        )

        if not isinstance(msfs_material, MSFS2024_Invisible):
            msfs_material.set_detail_color_tex(image)

    @staticmethod
    def update_detail_comp_texture(material, context):
        msfs_material = MSFS2024_MaterialPropUpdate.get_material(material)
        if msfs_material is None:
            return
        image = MSFS2024_MaterialPropUpdate._validate_material_image(
            material,
            MSFS2024_MaterialProperties.DETAILOMRTEXTURE.attribute_name(),
            msfs_image.ImageAlphaMode.NONE,
            msfs_image.ImageColorSpace.NON_COLOR,
        )

        if not isinstance(msfs_material, MSFS2024_Invisible):
            msfs_material.set_detail_omr_tex(image)

    @staticmethod
    def update_occlusion_uv2_texture(material, context):
        msfs_material = MSFS2024_MaterialPropUpdate.get_material(material)
        if msfs_material is None:
            return
        image = MSFS2024_MaterialPropUpdate._validate_material_image(
            material,
            MSFS2024_MaterialProperties.OCCLUSIONUV2.attribute_name(),
            msfs_image.ImageAlphaMode.NONE,
            msfs_image.ImageColorSpace.NON_COLOR,
        )

        if not isinstance(msfs_material, MSFS2024_Invisible):
            msfs_material.set_occlusion_uv2_tex(image)

    @staticmethod
    def update_detail_normal_texture(material, context):
        msfs_material = MSFS2024_MaterialPropUpdate.get_material(material)
        if msfs_material is None:
            return
        image = MSFS2024_MaterialPropUpdate._validate_material_image(
            material,
            MSFS2024_MaterialProperties.DETAILNORMALTEXTURE.attribute_name(),
            msfs_image.ImageAlphaMode.NONE,
            msfs_image.ImageColorSpace.NON_COLOR,
        )

        if not isinstance(msfs_material, MSFS2024_Invisible):
            msfs_material.set_detail_normal_tex(image)

    @staticmethod
    def update_blend_mask_texture(material, context):
        msfs_material = MSFS2024_MaterialPropUpdate.get_material(material)
        if msfs_material is None:
            return
        image = MSFS2024_MaterialPropUpdate._validate_material_image(
            material,
            MSFS2024_MaterialProperties.BLENDMASKTEXTURE.attribute_name(),
            msfs_image.ImageAlphaMode.NONE,
            msfs_image.ImageColorSpace.NON_COLOR,
        )

        valid_material_types = (MSFS2024_Standard, MSFS2024_Tree)
        if type(msfs_material) in valid_material_types:
            msfs_material.set_blendmask_tex(image)

    @staticmethod
    def update_decal_blend_mask_texture(material, context):
        msfs_material = MSFS2024_MaterialPropUpdate.get_material(material)
        if msfs_material is None:
            return

        image = MSFS2024_MaterialPropUpdate._validate_material_image(
            material,
            MSFS2024_MaterialProperties.DECALBLENDMASKTEXTURE.attribute_name(),
            msfs_image.ImageAlphaMode.NONE,
            msfs_image.ImageColorSpace.NON_COLOR,
        )

        if isinstance(msfs_material, MSFS2024_Geo_Decal_BlendMasked):
            msfs_material.set_decal_blend_mask_tex(
                image
            )

    @staticmethod
    def update_blend_mask_threshold(material, context):
        msfs_material = MSFS2024_MaterialPropUpdate.get_material(material)
        if msfs_material is None:
            return
        valid_material_types = (MSFS2024_Standard, MSFS2024_Tree)
        if type(msfs_material) in valid_material_types:
            msfs_material.set_blendmask_threshold(
                getattr(
                    material, 
                    MSFS2024_MaterialProperties.DETAILBLENDTHRESHOLD.attribute_name()
                )
            )

        elif isinstance(msfs_material, MSFS2024_Geo_Decal_BlendMasked):
            msfs_material.set_blendmask_threshold(
                getattr(
                    material, 
                    MSFS2024_MaterialProperties.DECALBLENDMASKEDTHRESHOLD.attribute_name()
                )
            )

    @staticmethod
    def update_freeze_factor(material, context):
        msfs_material = MSFS2024_MaterialPropUpdate.get_material(material)
        if msfs_material is None:
            return

        if isinstance(msfs_material, MSFS2024_Geo_Decal_Frosted):
            msfs_material.set_freeze_factor(
                getattr(
                    material, 
                    MSFS2024_MaterialProperties.DECALFREEZEFACTOR.attribute_name()
                )
            )

    @staticmethod
    def update_blend_mask_sharpness(material, context):
        msfs_material = MSFS2024_MaterialPropUpdate.get_material(material)
        if msfs_material is None:
            return

        if isinstance(msfs_material, MSFS2024_Geo_Decal_BlendMasked):
            msfs_material.set_blend_mask_sharpness(
                getattr(
                    material, 
                    MSFS2024_MaterialProperties.DECALBLENDSHARPNESS.attribute_name()
                )
            )

    @staticmethod
    def update_alpha_mode(material, context):
        msfs_material = MSFS2024_MaterialPropUpdate.get_material(material)
        if msfs_material is None:
            return

        msfs_material.set_blend_mode(
            getattr(
                material, 
                MSFS2024_MaterialProperties.ALPHAMODE.attribute_name()
            )
        )

    @staticmethod
    def get_base_color(material):
        return material.get(
           MSFS2024_MaterialProperties.BASECOLOR.attribute_name(), 
           MSFS2024_MaterialProperties.BASECOLOR.default_value()
        )

    @staticmethod
    def set_base_color(material, value):
        msfs_material = MSFS2024_MaterialPropUpdate.get_material(material)
        if msfs_material is None:
            return

        msfs_material.set_base_color(value)
        material[MSFS2024_MaterialProperties.BASECOLOR.attribute_name()] = value

    @staticmethod
    def get_emissive_color(material):
        return material.get(
           MSFS2024_MaterialProperties.EMISSIVECOLOR.attribute_name(), 
           MSFS2024_MaterialProperties.EMISSIVECOLOR.default_value()
        )

    @staticmethod
    def set_emissive_color(material, value):
        msfs_material = MSFS2024_MaterialPropUpdate.get_material(material)
        if msfs_material is None:
            return

        msfs_material.set_emissive_color(value)
        material[MSFS2024_MaterialProperties.EMISSIVECOLOR.attribute_name()] = value

    @staticmethod
    def update_emissive_scale(material, context):
        msfs_material = MSFS2024_MaterialPropUpdate.get_material(material)
        if msfs_material is None:
            return

        emissive_value = getattr(
            material, 
            MSFS2024_MaterialProperties.EMISSIVESCALE.attribute_name()
        )      
        msfs_material.set_emissive_scale(emissive_value)

    @staticmethod
    def get_metallic_scale(material):
        return material.get(
           MSFS2024_MaterialProperties.METALLICSCALE.attribute_name(), 
           MSFS2024_MaterialProperties.METALLICSCALE.default_value()
        )

    @staticmethod
    def set_metallic_scale(material, value):
        msfs_material = MSFS2024_MaterialPropUpdate.get_material(material)
        if msfs_material is None:
            return

        msfs_material.set_metallic_scale(value)
        material[MSFS2024_MaterialProperties.METALLICSCALE.attribute_name()] = value

    @staticmethod
    def get_roughness_scale(material):
        return material.get(
           MSFS2024_MaterialProperties.ROUGHNESSSCALE.attribute_name(), 
           MSFS2024_MaterialProperties.ROUGHNESSSCALE.default_value()
        )

    @staticmethod
    def set_roughness_scale(material, value):
        msfs_material = MSFS2024_MaterialPropUpdate.get_material(material)
        if msfs_material is None:
            return

        msfs_material.set_roughness_scale(value)
        material[MSFS2024_MaterialProperties.ROUGHNESSSCALE.attribute_name()] = value

    @staticmethod
    def update_normal_scale(material, context):
        msfs_material = MSFS2024_MaterialPropUpdate.get_material(material)
        if msfs_material is None:
            return

        msfs_material.set_normal_scale(
            getattr(
                material, 
                MSFS2024_MaterialProperties.NORMALSCALE.attribute_name()
            )
        )

    @staticmethod
    def update_color_sss(material, context):
        msfs_material = MSFS2024_MaterialPropUpdate.get_material(material)
        if msfs_material is None:
            return

        if isinstance(msfs_material, MSFS2024_SSS):
            msfs_material.set_sss_color(
                getattr(
                    material, 
                    MSFS2024_MaterialProperties.SSSCOLOR.attribute_name()
                )
            )

    @staticmethod
    def update_double_sided(material, context):
        double_sided_value = getattr(
            material, 
            MSFS2024_MaterialProperties.DOUBLESIDED.attribute_name()
        )
        material.use_backface_culling = not double_sided_value
        setattr(
            material, 
            MSFS2024_MaterialProperties.FLIPBACKFACENORMAL.attribute_name(), 
            double_sided_value
        )

    @staticmethod
    def update_alpha_cutoff(material, context):
        msfs_material = MSFS2024_MaterialPropUpdate.get_material(material)
        if msfs_material is None:
            return
        msfs_material.set_alpha_cutoff(
            getattr(material, MSFS2024_MaterialProperties.ALPHACUTOFF.attribute_name())
        )

    @staticmethod
    def update_detail_uv(material, context):
        msfs_material = MSFS2024_MaterialPropUpdate.get_material(material)
        if msfs_material is None:
            return

        msfs_material.set_detail_uv_scale(
            getattr(
                material, 
                MSFS2024_MaterialProperties.DETAILUVSCALE.attribute_name()
            )
        )

    @staticmethod
    def update_detail_normal_scale(material, context):
        msfs_material = MSFS2024_MaterialPropUpdate.get_material(material)
        if msfs_material is None:
            return

        msfs_material.set_detail_normal_scale(
            getattr(
                material, 
                MSFS2024_MaterialProperties.DETAILNORMALSCALE.attribute_name()
            )
        )

    @staticmethod
    def update_clearcoat_color_roughness_texture(material, context):
        msfs_material = MSFS2024_MaterialPropUpdate.get_material(material)
        if msfs_material is None:
            return
        image = MSFS2024_MaterialPropUpdate._validate_material_image(
            material,
            MSFS2024_MaterialProperties.CLEARCOATCOLORROUGHNESSTEXTURE.attribute_name(),
            msfs_image.ImageAlphaMode.NONE,
            msfs_image.ImageColorSpace.NON_COLOR,
        )
        if isinstance(msfs_material, MSFS2024_Clearcoat):
            msfs_material.set_clearcoat_tex(image)

    @staticmethod
    def update_clearcoat_normal_texture(material, context):
        msfs_material = MSFS2024_MaterialPropUpdate.get_material(material)
        if msfs_material is None:
            return

        image = MSFS2024_MaterialPropUpdate._validate_material_image(
            material,
            MSFS2024_MaterialProperties.CLEARCOATNORMALTEXTURE.attribute_name(),
            msfs_image.ImageAlphaMode.NONE,
            msfs_image.ImageColorSpace.NON_COLOR,
        )

        if isinstance(msfs_material, MSFS2024_Clearcoat):
            msfs_material.set_clearcoat_normal_tex(image)

    @staticmethod
    def update_behind_glass_color_texture(material, context):
        msfs_material = MSFS2024_MaterialPropUpdate.get_material(material)
        if msfs_material is None:
            return
        image = MSFS2024_MaterialPropUpdate._validate_material_image(
            material,
            MSFS2024_MaterialProperties.BEHINDGLASSCOLORTEXTURE.attribute_name(),
            msfs_image.ImageAlphaMode.NONE,
            msfs_image.ImageColorSpace.SRGB,
        )

        if not isinstance(msfs_material, MSFS2024_Invisible):
            msfs_material.set_detail_color_tex(image)

    @staticmethod
    def get_uv_offset_u(material):
        return material.get(
            MSFS2024_MaterialProperties.UVOFFSETU.attribute_name(), 
            MSFS2024_MaterialProperties.UVOFFSETU.default_value()
        )

    @staticmethod
    def set_uv_offset_u(material, value):
        msfs_material = MSFS2024_MaterialPropUpdate.get_material(material)
        if msfs_material is None:
            return

        msfs_material.set_uv_offset_u(value)
        material[MSFS2024_MaterialProperties.UVOFFSETU.attribute_name()] = value

    @staticmethod
    def get_uv_offset_v(material):
        return material.get(
            MSFS2024_MaterialProperties.UVOFFSETV.attribute_name(), 
            MSFS2024_MaterialProperties.UVOFFSETV.default_value()
        )

    @staticmethod
    def set_uv_offset_v(material, value):
        msfs_material = MSFS2024_MaterialPropUpdate.get_material(material)
        if msfs_material is None:
            return

        msfs_material.set_uv_offset_v(value)
        material[MSFS2024_MaterialProperties.UVOFFSETV.attribute_name()] = value

    @staticmethod
    def get_uv_tiling_u(material):
        return material.get(
            MSFS2024_MaterialProperties.UVTILINGU.attribute_name(), 
            MSFS2024_MaterialProperties.UVTILINGU.default_value()
        )

    @staticmethod
    def set_uv_tiling_u(material, value):
        msfs_material = MSFS2024_MaterialPropUpdate.get_material(material)
        if msfs_material is None:
            return

        msfs_material.set_uv_tiling_u(value)
        material[MSFS2024_MaterialProperties.UVTILINGU.attribute_name()] = value

    @staticmethod
    def get_uv_tiling_v(material):
        return material.get(
            MSFS2024_MaterialProperties.UVTILINGV.attribute_name(), 
            MSFS2024_MaterialProperties.UVTILINGV.default_value()
        )

    @staticmethod
    def set_uv_tiling_v(material, value):
        msfs_material = MSFS2024_MaterialPropUpdate.get_material(material)
        if msfs_material is None:
            return

        msfs_material.set_uv_tiling_v(value)
        material[MSFS2024_MaterialProperties.UVTILINGV.attribute_name()] = value

    @staticmethod
    def get_uv_rotation(material):
        return material.get(
            MSFS2024_MaterialProperties.UVROTATION.attribute_name(), 
            MSFS2024_MaterialProperties.UVROTATION.default_value()
        )

    @staticmethod
    def set_uv_rotation(material, value):
        msfs_material = MSFS2024_MaterialPropUpdate.get_material(material)
        if msfs_material is None:
            return

        msfs_material.set_uv_rotation(value)
        material[MSFS2024_MaterialProperties.UVROTATION.attribute_name()] = value
