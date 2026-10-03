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

from enum import Enum
from typing import Any

from .msfs_utils import MSFS2024_Enum_Properties

# region Constants
class MSFS2024_MaterialTypes(Enum):
    STANDARD = "msfs_standard"
    DECAL = "msfs_decal"
    WINDSHIELD = "msfs_windshield"
    PORTHOLE = "msfs_porthole"
    GLASS = "msfs_glass"
    GEODECALFROSTED = "msfs_geo_decal_frosted"
    CLEARCOAT = "msfs_clearcoat"
    PARALLAXWINDOW = "msfs_parallax_window"
    ANISOTROPIC = "msfs_anisotropic"
    HAIR = "msfs_hair"
    SUBSURFACESCATTERING = "msfs_sss"
    INVISIBLE = "msfs_invisible"
    FAKETERRAIN = "msfs_fake_terrain"
    FRESNELFADE = "msfs_fresnel_fade"
    ENVIRONMENTOCCLUDER = "msfs_environment_occluder"
    GHOST = "msfs_ghost"
    GEODECALBLENDMASKED = "msfs_geo_decal_blendmasked"
    SAIL = "msfs_sail"
    PROPELLER = "msfs_propeller"
    TREE = "msfs_tree"
    VEGETATION = "msfs_vegetation"
    TIRE = "msfs_tire"

class MSFS2024_MaterialProperties(MSFS2024_Enum_Properties):
    """
        Enum describing the parameters of materials contains Tuples of:
        ( 
            The name that appears in the UI, 
            Default Value, 
            attribute name of the prop, 
            name that appear in the extension when it's exported/imported
        )
    """

    # region Parameters
    MATERIALTYPE = "Material Type", "NONE", "msfs_material_type", None
    ALPHAMODE = "Alpha Mode", "OPAQUE", "msfs_alpha_mode", None

    BASECOLOR = "Base Color", [1.0, 1.0, 1.0, 1.0], "msfs_base_color_factor", None
    SSSCOLOR = "Sub-Surface Scattering Color", [1.0, 1.0, 1.0, 1.0], "msfs_sss_color", "SSSColor"
    METALLICSCALE = "Metallic Factor", 1.0, "msfs_metallic_factor", None
    ROUGHNESSSCALE = "Roughness Factor", 1.0, "msfs_roughness_factor", None
    NORMALSCALE = "Normal Scale", 1.0, "msfs_normal_scale", None
    EMISSIVESCALE = "Emissive Scale", 1000.0, "msfs_emissive_scale", None
    OCCLUSIONSTRENGTH = "Occlusion Strength", 1.0, "msfs_occlusion_strength", "strength"
    ALPHACUTOFF = "Alpha Cutoff", 0.5, "msfs_alpha_cutoff", None
    
    # region Emissive Parameters
    EMISSIVECOLOR = "Emissive Color", [0.0, 0.0, 0.0], "msfs_emissive_factor", None
    EMISSIVE_DAY_MULTIPLIER = "Emissive Day Multiplier", 1.0, "msfs_emissive_day_multiplier", "emissiveDayMultiplier"
    EMISSIVE_NIGHT_MULTIPLIER = "Emissive Night Multiplier", 1.0, "msfs_emissive_night_multiplier", "emissiveNightMultiplier"

    # region Render Parameters
    DRAWORDEROFFSET = "Draw Order Offset", 0, "msfs_draw_order_offset", "drawOrderOffset"
    NOCASTSHADOW = "Don't Cast Shadows", False, "msfs_no_cast_shadow", "noCastShadow"
    DAYNIGHTCYCLE = "Day Night Cycle", False, "msfs_day_night_cycle", None
    DISABLEMOTIONBLUR = "Disable Motion Blur", False, "msfs_disable_motion_blur", "enabled"
    DOUBLESIDED = "Double Sided", False, "msfs_double_sided", None
    FLIPBACKFACENORMAL = "Flip Back Face Normal", False, "msfs_flip_back_face_normal", None
    # endregion

    # region UV
    CLAMPUVX = "Clamp UV U", False, "msfs_clamp_uv_x", "clampUVX"
    CLAMPUVY = "Clamp UV V", False, "msfs_clamp_uv_y", "clampUVY"
    UVOFFSETU = "UV Offset U", 0.0, "msfs_uv_offset_u", "UVOffsetU"
    UVOFFSETV = "UV Offset V", 0.0, "msfs_uv_offset_v", "UVOffsetV"
    UVTILINGU = "UV Tiling U", 1.0, "msfs_uv_tiling_u", "UVTilingU"
    UVTILINGV = "UV Tiling V", 1.0, "msfs_uv_tiling_v", "UVTilingV"
    UVROTATION = "UV Rotation", 0.0, "msfs_uv_rotation", "UVRotation"
    # endregion

    # region Detail
    DETAILUVSCALE = "Detail UV Scale", 1.0, "msfs_detail_uv_scale", "UVScale"
    DETAILBLENDTHRESHOLD = "Blend Mask Threshold", 0.001, "msfs_detail_blend_threshold", "blendThreshold"
    DETAILNORMALSCALE = "Detail Normal Scale", 1.0, "msfs_detail_normal_scale", "scale"
    # endregion

    # region Decal
    BASECOLORBLENDFACTOR = "Base Color Blend Factor", 1.0, "msfs_base_color_blend_factor", "baseColorBlendFactor"
    METALLICBLENDFACTOR = "Metallic Blend Factor", 1.0, "msfs_metallic_blend_factor", "metallicBlendFactor"
    ROUGHNESSBLENDFACTOR = "Roughness Blend Factor", 1.0, "msfs_roughness_blend_factor", "roughnessBlendFactor"
    NORMALBLENDFACTOR = "Normal Blend Factor", 1.0, "msfs_normal_blend_factor", "normalBlendFactor"
    EMISSIVEBLENDFACTOR = "Emissive Blend Factor", 1.0, "msfs_emissive_blend_factor", "emissiveBlendFactor"
    OCCLUSIONBLENDFACTOR = "Occlusion Blend Factor", 1.0, "msfs_occlusion_blend_factor", "occlusionBlendFactor"
    NORMALOVERRIDEFACTOR = "Normal Mode Tangent/Override", 1.0, "msfs_normal_override_blend_factor", "normalOverrideFactor"
    DECALBLENDSHARPNESS = "Decal Blend Mask Sharpness", 0.0, "msfs_decal_blend_sharpness", "blendSharpnessFactor"
    DECALBLENDMASKEDTHRESHOLD = "Decal Blend Mask Threshold", 0.0, "msfs_decal_blend_masked_threshold", ""
    DECALFREEZEFACTOR = "Freeze Factor", 0.0, "msfs_decal_freeze_factor", ""
    DECALMODE = "Decal Mode", "", "msfs_decal_mode", "mode"
    UNDERCLEARCOAT = "Render Under Clearcoat", True, "msfs_under_clearcoat", "underClearcoat"
    SCENERY_CHANNEL = "Scenery Channel", True, "msfs_scenery_channel", "decalChan0"
    TERRAIN_CHANNEL = "Terrain Channel", False, "msfs_terrain_channel", "decalChan1"
    SIMOBJECT_CHANNEL = "Simobject Channel", True, "msfs_simobject_channel", "decalChan2"
    # endregion

    # region Wear
    WEAROVERLAYUVSCALE = "Wear Overlay UV Scale", 1.0, "msfs_wear_overlay_uv_scale", "dirtUvScale"
    WEARBLENDSHARPNESS = "Wear Blend Sharpness", 0.0, "msfs_wear_blend_sharpness", "dirtBlendSharpness"
    WEARAMOUNT = "Wear Amount", 0.0, "msfs_wear_amount", "dirtBlendAmount"
    # endregion

    # region Collision
    COLLISIONMATERIAL = "Collision Material", False, "msfs_collision_material", None
    ROADCOLLISIONMATERIAL = "Road Collision Material", False, "msfs_road_collision_material", None
    GROUNDCOLLISIONMATERIAL = "Ground Collision Material", False, "msfs_ground_collision_material", None
    # endregion

    # region Ghost
    GHOSTBIAS = "Ghost Bias", 0.0, "msfs_ghost_bias", "bias"
    GHOSTSCALE = "Ghost Scale", 1.0, "msfs_ghost_scale", "scale"
    GHOSTPOWER = "Ghost Power", 1.0, "msfs_ghost_power", "power"
    # endregion

    # region Sail
    SAILLIGHTABSORPTION = "Light Absorption", 1.0, "msfs_sail_light_absorption", "sailLightAbsorption"
    # endregion

    # region Rain
    RECEIVERAIN = "Receive Rain", False, "msfs_receive_rain", None
    RAINDROPTILING = "Rain Drop Tiling", 1.0, "msfs_rain_drop_tiling", "rainDropScale"
    RAINONBACKFACE = "Rain On BackFace", False, "msfs_rain_on_backface", "rainDropSide"
    # endregion

    # region Pearl
    USEPEARLEFFECT = "Use Pearl Effect", False, "msfs_use_pearl", None
    PEARLCOLORSHIFT = "Pearl Color Shift", 0.0, "msfs_pearl_shift", "pearlShift"
    PEARLCOLORRANGE = "Pearl Color Range", 0.0, "msfs_pearl_range", "pearlRange"
    PEARLCOLORBRIGHTNESS = "Pearl Color Brightness", 0.0, "msfs_pearl_brightness", "pearlBrightness"
    # endregion

    # region Fresnel
    FRESNELFACTOR = "Fresnel Factor", 1.0, "msfs_fresnel_factor", "fresnelFactor"
    FRESNELOPACITYBIAS = "Fresnel Opacity Bias", 1.0, "msfs_fresnel_opacity_offset", "fresnelOpacityOffset"
    # endregion

    # region Parallax
    PARALLAXROOMSIZEX = "Room Scale X", 0.5, "msfs_parallax_room_size_x", "roomSizeXScale"
    PARALLAXROOMSIZEY = "Room Scale Y", 0.5, "msfs_parallax_room_size_y", "roomSizeYScale"
    PARALLAXROOMSIZEZ = "Room Scale Z", 0.5, "msfs_parallax_room_size_z", "parallaxScale"
    PARALLAXROOMCOUNT = "Room Count", 5, "msfs_parallax_room_count_xy", "roomNumberXY"
    PARALLAXCORRIDOR = "Corridor", False, "msfs_parallax_corridor", "corridor"
    # endregion

    # region Glass
    GLASSWIDTH = "Glass Width (mm)", 0.0, "msfs_glass_width", "glassWidth"
    # endregion

    # region Clearcoat
    CLEARCOATROUGHNESSFACTOR = "Clearcoat Roughness Factor", 1.0, "msfs_clearcoat_roughness_factor", "clearcoatRoughnessFactor"
    CLEARCOATNORMALFACTOR = "Clearcoat Normal Factor", 1.0, "msfs_clearcoat_normal_factor", "clearcoatNormalFactor"
    CLEARCOATCOLORROUGHNESSTILING = "Clearcoat Color/Roughness Tiling", 1.0, "msfs_clearcoat_color_roughness_tiling", "clearcoatColorRoughnessTiling"
    CLEARCOATNORMALTILING = "Clearcoat Normal Tiling", 1.0, "msfs_clearcoat_normal_tiling", "clearcoatNormalTiling"
    CLEARCOATINVERSEROUGHNESS = "Use Uniform Roughness", False, "msfs_clearcoat_inverse_roughness", "clearcoatInverseRoughness"
    CLEARCOATBASEROUGHNESS = "Base Roughness", 0.5, "msfs_clearcoat_base_roughness", "clearcoatBaseRoughness"
    BASE_NORMAL_AFFECT_COAT = "Base Normal Affect Coat", True, "msfs_base_normal_affect_coat", "clearcoatBaseAffectCoat"
    # endregion

    # region Windshield
    WINDSHIELDDETAILROUGHNESS1 = "Detail 1 (R) Roughness", 0.0, "msfs_windshield_detail_rough_1", "detail1Rough"
    WINDSHIELDDETAILROUGHNESS2 = "Detail 2 (B) Roughness", 0.0, "msfs_windshield_detail_rough_2", "detail2Rough"
    WINDSHIELDDETAILOPACITY1 = "Detail 1 (R) Opacity", 0.0, "msfs_windshield_detail_opacity_1", "detail1Opacity"
    WINDSHIELDDETAILOPACITY2 = "Detail 2 (B) Opacity", 0.0, "msfs_windshield_detail_opacity_2", "detail2Opacity"
    WINDSHIELDMICROSCRATCHTILING = "Micro-Scratches Tiling", 1.0, "msfs_windshield_micro_scratches_tiling", "microScratchesTiling"
    WINDSHIELDMICROSCRATCHSTRENGTH = "Micro-Scratches Strength", 1.0, "msfs_windshield_micro_scratches_strength", "microScratchesStrength"
    WINDSHIELDDETAILNORMALREFRACTSCALE = "Detail Normal Refraction Strength", 1.0, "msfs_windshield_detail_normal_refract_scale", "detailNormalRefractScale"
    WINDSHIELDWIPERLINES = "Wiper Lines", False, "msfs_windshield_wiper_lines", "wiperLines"
    WINDSHIELDWIPERLINESTILING = "Wiper Lines Tiling", 1.0, "msfs_windshield_wiper_lines_tiling", "wiperLinesTiling"
    WINDSHIELDWIPERLINESSTRENGTH = "Wiper Lines Strength", 1.0, "msfs_windshield_wiper_lines_strength", "wiperLinesStrength"
    WINDSHIELDWIPER1STATE = "Wiper 1 State", 0.0, "msfs_windshield_wiper_1_state", "wiper1State"
    WINDSHIELDREFLECTIONMASKSTRENGTH = "Reflection Mask Strength", 1.0, "msfs_occlusion_strength", "strength"
    WINDSHIELDSSRATTENUATION = "SSR Attenuation", 1.0, "msfs_ssr_attenuation", "ssrAttenuation"
    WINDSHIELDCUBEMAPREFLECTIONMASKING = "Cubemap Reflection Masking", False, "msfs_cubemap_reflection_masking", "cubemapReflectionMasking"
    # endregion

    # region Iridescent
    USEIRIDESCENT = "Use Iridescent Parameters", False, "msfs_use_iridescent", None
    IRIDESCENTMINTHICKNESS = "Min Thickness", 400.0, "msfs_iridescent_min_thickness", "iridescentMinThickness"
    IRIDESCENTMAXTHICKNESS = "Max Thickness", 400.0, "msfs_iridescent_max_thickness", "iridescentMaxThickness"
    IRIDESCENTBRIGHTNESS = "Brightness", 1.0, "msfs_iridescent_brightness", "iridescentBrightness"
    # endregion

    # region Mud
    TIREMUDNORMALTILING = "Mud Tiling", 1.0, "msfs_tire_mud_normal_tiling", "tireMudTiling"
    TIREMUDANIMSTATE = "Mud Anim State", 0.0, "msfs_tire_mud_anim_state", "tireMudAnimState"
    TIREDUSTANIMSTATE = "Dust Anim State", 0.0, "msfs_tire_dust_anim_state", "tireDustAnimState"
    # endregion

    # endregion

    # region Textures
    BASECOLORTEXTURE = "Base Color Texture (RGBA)", None, "msfs_base_color_texture", "baseColorTexture"
    OMRTEXTURE = "Occlusion (R), Roughness (G), Metallic (B)", None, "msfs_occlusion_metallic_roughness_texture", "metallicRoughnessTexture"
    NORMALTEXTURE = "Normal Texture (RGB)", None, "msfs_normal_texture", "normalTexture"
    EMISSIVETEXTURE = "Emissive Texture (RGB)", None, "msfs_emissive_texture", "emissiveTexture"

    DETAILCOLORTEXTURE = "Detail Color (RGB), Alpha (A)", None, "msfs_detail_color_texture", "detailColorTexture"
    DETAILOMRTEXTURE = "Detail Occlusion (R), Roughness (G), Metallic (B)", None, "msfs_detail_occlusion_metallic_roughness_texture", "detailMetalRoughAOTexture"
    DETAILNORMALTEXTURE = "Detail Normal Texture", None, "msfs_detail_normal_texture", "detailNormalTexture"

    BLENDMASKTEXTURE = "Blend Mask Texture", None, "msfs_blend_mask_texture", "blendMaskTexture"
    OCCLUSIONUV2 = "Occlusion (UV2)", None, "msfs_occlusion_uv2", "extraOcclusionTexture"

    DECALBLENDMASKTEXTURE = "Decal Blend Mask Texture", None, "msfs_decal_blend_mask_texture", "blendMaskTexture"
    DECALMELTROUGHNESSMETALLICTEXTURE = "Melt Pattern (R) Roughness (G) Metallic (B)", None, "msfs_detail_occlusion_metallic_roughness_texture", "detailMetalRoughAOTexture"

    CLEARCOATCOLORROUGHNESSTEXTURE = "Clearcoat amount (R), Clearcoat rough (G)", None, "msfs_clearcoat_color_roughness_texture", "clearcoatColorRoughnessTexture"
    CLEARCOATNORMALTEXTURE = "Clearcoat Normal", None, "msfs_clearcoat_normal_texture", "clearcoatNormalTexture"

    FRONTGLASSCOLORTEXTURE = "Front Glass Color Texture", None, "msfs_base_color_texture", None
    FRONTGLASSNORMALTEXTURE = "Front Glass Normal Texture", None, "msfs_normal_texture", None
    EMISSIVEINSIDEWINDOWTEXTURE = "Emissive Inside Window Texture", None, "msfs_emissive_texture", None
    BEHINDGLASSCOLORTEXTURE = "Behind Glass Color Texture", None, "msfs_behind_glass_color_texture", "behindWindowMapTexture"

    OPACITYTEXTURE = "Opacity", None, "msfs_opacity_texture", "opacityTexture"

    OCCANISOROUGHXMETALICTEXTURE = "Occlusion (R), Anisotropic Roughness X (G), Metallic (B)", None, "msfs_occlusion_metallic_roughness_texture", None
    ANISODIRECTIONROUGHNESSTEXTURE = "Anisotropic Direction (RG), Roughness Y (B)", None, "msfs_anisotropic_direction_roughness_y_texture", "anisoDirectionRoughnessTexture"

    WEARALBEDOMASKTEXTURE = "Wear Albedo (RGB), Mask (A)", None, "msfs_wear_albedo_mask", "dirtTexture"
    WEAROMRINTENSITYTEXTURE = "Wear Occlusion (R), Roughness (G), Metallic (B), Intensity (A)", None, "msfs_wear_omr_intensity", "dirtOcclusionRoughnessMetallicTexture"

    WINDSHIELDWIPERMASKTEXTURE = "Wiper Mask (RGBA)", None, "msfs_windshield_wiper_mask_texture", "wiperMaskTexture"
    WINDSHIELDREFLECTIONROUGHNESSMETALLICTEXTURE = "Reflection (R) Roughness (G) Metallic (B)", None, "msfs_occlusion_metallic_roughness_texture", None
    WINDSHILEDDETAILNORMALTEXTURE = "Detail Normal (use Detail UV Scale)", None, "msfs_windshield_detail_normal_texture", "windshieldDetailNormalTexture"
    WINDSHIELDSCRACHESNORMALTEXTURE = "Scratches Normal", None, "msfs_windshield_scratches_normal_texture", "scratchesNormalTexture"
    WINDSHIELDINSECTSALBEDOTEXTURE = "Insects Albedo (RGBA)", None, "msfs_windshield_insects_albedo_texture", "windshieldInsectsTexture"
    WINDSHIELDINSECTSMASKTEXTURE = "Insects Mask (A)", None, "msfs_windshield_insects_mask_texture", "windshieldInsectsMaskTexture"
    WINDSHIELDSECONDARYDETAILSTEXTURE = "Secondary Details (RGBA)", None, "msfs_emissive_texture", None
    DETAILS1ICINGMASKDETAILS2TEXTURE = "Details 1 (R), Icing Mask (G), Details 2 (B)", None, "msfs_detail_color_texture", "detailColorTexture"
    DETAILSWINDSHIELDREFLECTIONROUGHNESSMETALLICTEXTURE = "Details Reflection (R) Roughness (G) Metallic (B)", None, "msfs_detail_occlusion_metallic_roughness_texture", "detailMetalRoughAOTexture"
    ICINGNORMALTEXTURE = "Icing Normal (use UV Detail Scale)", None, "msfs_detail_normal_texture", "detailNormalTexture"
    REFLECTIONMASKTEXTURE = "Reflection Mask (UV2)", None, "msfs_occlusion_uv2", "extraOcclusionTexture"
    IRIDESCENTTHICKNESSTEXTURE = "Iridescent Thickness (R)", None, "msfs_iridescent_thickness_texture", "iridescentThicknessTexture"

    FOLIAGEMASKTEXTURE = "Foliage Mask (R) Transluency (G) WindMask (B)", None, "msfs_foliage_mask_texture", "foliageMaskTexture"

    TIREMUDCUTOUTTEXTURE = "Tire Mud Cutout", None, "msfs_tire_mud_cutout_texture", "tireMudCutoutTexture"
    TIREDETAILSTEXTURE = "Tire details Mud(R) Dust (G)", None, "msfs_tire_details_texture", "tireDetailsTexture"
    TIREMUDNORMALTEXTURE = "Tire Mud Normal", None, "msfs_tire_mud_normal_texture", "tireMudNormalTexture"

    # endregion

# endregion

class MSFS2024_MaterialUtilsUI:

    @staticmethod
    def draw_prop(
        layout: Any,
        material: Any,
        prop: str,
        text: str = "",
        enabled: bool = True
    ) -> Any:
        row = layout.row()
        if text:
            row.prop(material, prop, text=text)
        else:
            row.prop(material, prop)

        row.enabled = enabled
        return row

    @staticmethod
    def draw_texture_prop(
        layout: Any,
        material: Any,
        prop: str,
        text: str = "",
        enabled: bool = True
    ) -> Any:
        column = layout.column()
        if text:
            column.label(text=text)
        sub_row = column.row(align=False)
        image = getattr(material, prop, None)
        if image:
            sub_row.template_ID_preview(
                material, 
                prop, 
                open="image.open", 
                rows=3, 
                cols=3, 
                hide_buttons=False
            )
        else:
            sub_row.template_ID(material, prop, open="image.open", live_icon=False)
        return column

    ## Parameters
    @staticmethod
    def draw_base_color_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.BASECOLOR.property_name()
    ) -> None:
        box = layout.box()
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.BASECOLOR.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_emissive_props(
        layout: Any,
        material: Any
    ):
        box = layout.box()

        MSFS2024_MaterialUtilsUI.draw_emissive_color_prop(box, material)
        MSFS2024_MaterialUtilsUI.draw_emissive_scale_prop(box, material)
        MSFS2024_MaterialUtilsUI.draw_emissive_day_multiplier_prop(box, material)
        MSFS2024_MaterialUtilsUI.draw_emissive_night_multiplier_prop(box, material)

    @staticmethod
    def draw_emissive_color_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.EMISSIVECOLOR.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.EMISSIVECOLOR.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_emissive_scale_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.EMISSIVESCALE.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.EMISSIVESCALE.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_emissive_day_multiplier_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.EMISSIVE_DAY_MULTIPLIER.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.EMISSIVE_DAY_MULTIPLIER.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_emissive_night_multiplier_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.EMISSIVE_NIGHT_MULTIPLIER.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.EMISSIVE_NIGHT_MULTIPLIER.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_alpha_mode_prop(
        layout: Any,
        material: Any,
        text: str = ""
    ) -> None:
        box = layout.box()
        box.label(text="Alpha Mode")
        box.prop(
            material,
            MSFS2024_MaterialProperties.ALPHAMODE.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_order_offset_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.DRAWORDEROFFSET.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.DRAWORDEROFFSET.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_no_cast_shadow_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.NOCASTSHADOW.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.NOCASTSHADOW.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_double_sided_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.DOUBLESIDED.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.DOUBLESIDED.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_flip_back_face_normal_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.FLIPBACKFACENORMAL.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.FLIPBACKFACENORMAL.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_day_night_cycle_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.DAYNIGHTCYCLE.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.DAYNIGHTCYCLE.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_motion_blur_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.DISABLEMOTIONBLUR.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.DISABLEMOTIONBLUR.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_collision_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.COLLISIONMATERIAL.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.COLLISIONMATERIAL.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_road_collision_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.ROADCOLLISIONMATERIAL.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.ROADCOLLISIONMATERIAL.attribute_name(),
            text=text
        )
    
    @staticmethod
    def draw_ground_collision_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.GROUNDCOLLISIONMATERIAL.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.GROUNDCOLLISIONMATERIAL.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_gameplay_panel(layout: Any, material: Any) -> None:
        box = layout.box()
        box.label(text="Gameplay Parameters")

        MSFS2024_MaterialUtilsUI.draw_collision_prop(layout=box, material=material)
        MSFS2024_MaterialUtilsUI.draw_road_collision_prop(layout=box, material=material)
        MSFS2024_MaterialUtilsUI.draw_ground_collision_prop(layout=box, material=material)

    @staticmethod
    def draw_uv_offset_u_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.UVOFFSETU.property_name()
    ) -> None:
        layout.use_property_decorate = True
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.UVOFFSETU.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_uv_offset_v_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.UVOFFSETV.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.UVOFFSETV.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_tiling_u_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.UVTILINGU.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.UVTILINGU.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_tiling_v_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.UVTILINGV.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.UVTILINGV.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_clamp_uv_x_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.CLAMPUVX.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.CLAMPUVX.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_clamp_uv_y_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.CLAMPUVY.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.CLAMPUVY.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_uv_rotation_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.UVROTATION.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.UVROTATION.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_uv_panel(layout: Any, material: Any) -> None:
        box = layout.box()
        box.label(text="UV Options")

        MSFS2024_MaterialUtilsUI.draw_uv_offset_u_prop(layout=box, material=material)
        MSFS2024_MaterialUtilsUI.draw_uv_offset_v_prop(layout=box, material=material)
        MSFS2024_MaterialUtilsUI.draw_tiling_u_prop(layout=box, material=material)
        MSFS2024_MaterialUtilsUI.draw_tiling_v_prop(layout=box, material=material)
        MSFS2024_MaterialUtilsUI.draw_uv_rotation_prop(layout=box, material=material)
        MSFS2024_MaterialUtilsUI.draw_clamp_uv_x_prop(layout=box, material=material)
        MSFS2024_MaterialUtilsUI.draw_clamp_uv_y_prop(layout=box, material=material)

    @staticmethod
    def draw_metallic_scale_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.METALLICSCALE.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.METALLICSCALE.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_roughness_scale_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.ROUGHNESSSCALE.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.ROUGHNESSSCALE.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_occlusion_strength_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.OCCLUSIONSTRENGTH.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.OCCLUSIONSTRENGTH.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_normal_scale_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.NORMALSCALE.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.NORMALSCALE.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_alpha_cutoff_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.ALPHACUTOFF.property_name()
    ) -> None:
        alpha_mode = getattr(
            material,
            MSFS2024_MaterialProperties.ALPHAMODE.attribute_name()
        )
        if alpha_mode != "MASK":
            return

        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.ALPHACUTOFF.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_detail_uv_scale_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.DETAILUVSCALE.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.DETAILUVSCALE.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_detail_normal_scale_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.DETAILNORMALSCALE.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.DETAILNORMALSCALE.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_blend_threshold_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.DETAILBLENDTHRESHOLD.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.DETAILBLENDTHRESHOLD.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_wear_overlay_uv_scale_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.WEAROVERLAYUVSCALE.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.WEAROVERLAYUVSCALE.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_wear_blend_sharpness_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.WEARBLENDSHARPNESS.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.WEARBLENDSHARPNESS.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_wear_amount_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.WEARAMOUNT.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.WEARAMOUNT.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_sss_color_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.SSSCOLOR.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.SSSCOLOR.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_receive_rain_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.RECEIVERAIN.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.RECEIVERAIN.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_rain_drop_tiling_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.RAINDROPTILING.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.RAINDROPTILING.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_rain_on_backface_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.RAINONBACKFACE.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.RAINONBACKFACE.attribute_name(),
            text=text
        )

    ## Textures
    @staticmethod
    def draw_base_color_texture_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.BASECOLORTEXTURE.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_texture_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.BASECOLORTEXTURE.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_omr_texture_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.OMRTEXTURE.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_texture_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.OMRTEXTURE.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_normal_texture_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.NORMALTEXTURE.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_texture_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.NORMALTEXTURE.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_emissive_texture_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.EMISSIVETEXTURE.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_texture_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.EMISSIVETEXTURE.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_detail_color_texture_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.DETAILCOLORTEXTURE.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_texture_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.DETAILCOLORTEXTURE.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_detail_omr_texture_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.DETAILOMRTEXTURE.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_texture_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.DETAILOMRTEXTURE.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_detail_normal_texture_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.DETAILNORMALTEXTURE.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_texture_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.DETAILNORMALTEXTURE.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_blend_mask_texture_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.BLENDMASKTEXTURE.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_texture_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.BLENDMASKTEXTURE.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_decal_blend_mask_texture_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.DECALBLENDMASKTEXTURE.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_texture_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.DECALBLENDMASKTEXTURE.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_occlusion_uv2_texture_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.OCCLUSIONUV2.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_texture_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.OCCLUSIONUV2.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_wear_albedo_mask_texture_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.WEARALBEDOMASKTEXTURE.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_texture_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.WEARALBEDOMASKTEXTURE.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_wear_omr_intensity_texture_prop(
        layout: Any,
        material: Any,
        text: str = MSFS2024_MaterialProperties.WEAROMRINTENSITYTEXTURE.property_name()
    ) -> None:
        MSFS2024_MaterialUtilsUI.draw_texture_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.WEAROMRINTENSITYTEXTURE.attribute_name(),
            text=text
        )

    @staticmethod
    def draw_decal_channel_mask_props(
        layout: Any,
        material: Any
    ):
        box = layout.box()
        box.label(text="Decal Channel Mask")

        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.SCENERY_CHANNEL.attribute_name()
        )

        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.TERRAIN_CHANNEL.attribute_name()
        )

        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.SIMOBJECT_CHANNEL.attribute_name()
        )
