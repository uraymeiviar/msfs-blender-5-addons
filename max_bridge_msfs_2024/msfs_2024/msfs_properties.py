"""
THIS MODULE IS IDENTICAL IN 3DSMAX PLUGIN AND BLENDER ADDON.

MSFS2024 Properties.
"""

from __future__ import annotations
from enum import Enum

from ..common.usd_properties import *

class MSFS2024_LightShapes:
    POINT = "point"
    SPHERE = "sphere"
    DISC = "disc"


# region Custom Classes

class MSFS2024_BaseLight(CustomClassPropertiesDef):
    LIGHT_COLOR = [1.0, 1.0, 1.0], "msfs_light_color", "color", PropertyTypes.COLOR
    #POWER
    INTENSITY =  1, "msfs_light_intensity", "intensity", PropertyTypes.FLOAT
    DAY_NIGHT_CYCLE =  False, "msfs_light_day_night_cycle", NOTIMPLEMENTED, PropertyTypes.BOOL

class MSFS2024_FastLight(CustomClassPropertiesDef):
    
    LIGHT_COLOR = [1.0, 1.0, 1.0], "msfs_light_color", "color", PropertyTypes.COLOR
    #POWER
    INTENSITY = 1, "msfs_light_intensity", "intensity", PropertyTypes.FLOAT
    DAY_NIGHT_CYCLE = False, "msfs_light_day_night_cycle", "ActivationMode", PropertyTypes.BOOL
    #DISTRIBUTION
    CONE_ANGLE =  90, "msfs_light_cone_angle", "ConeAngle", PropertyTypes.FLOAT
    HAS_SYMMETRY = False, "msfs_light_has_symmetry", "HasSimmetry", PropertyTypes.BOOL
    #ANIMATION
    FLASH_FREQUENCY = 00.0, "msfs_light_flash_frequency", "FlashFrequency", PropertyTypes.FLOAT
    FLASH_DURATION = 0.2, "msfs_light_flash_duration", "FlashDuration", PropertyTypes.FLOAT
    FLASH_PHASE = 0.0, "msfs_light_flash_phase", "FlashPhase", PropertyTypes.FLOAT
    ROTATION_SPEED = 0.0, "msfs_light_rotation_speed", "RotationSpeed", PropertyTypes.FLOAT
    ROTATION_PHASE = 0.0, "msfs_light_rotation_phase", "RotationPhase", PropertyTypes.FLOAT
    RANDOM_PHASE = True, "msfs_light_random_phase", "RandomPhase", PropertyTypes.BOOL


class MSFS2024_AdvancedLight(CustomClassPropertiesDef):

    LIGHT_COLOR = [1.0, 1.0, 1.0], "msfs_light_color", "color", PropertyTypes.COLOR
    #POWER
    INTENSITY = 1, "msfs_light_intensity", "intensity", PropertyTypes.FLOAT
    DAY_NIGHT_CYCLE = False, "msfs_light_day_night_cycle", NOTIMPLEMENTED, PropertyTypes.BOOL
    #SHAPE
    SHAPE = "point", "msfs_light_shape_type", "ShapeType", PropertyTypes.STRING
    SOURCE_RADIUS = 50.0, "msfs_light_source_radius", "SourceRadius", PropertyTypes.FLOAT
    INNER_ANGLE = 160, "msfs_light_inner_angle", "InnerConeAngle", PropertyTypes.INT
    OUTER_ANGLE = 160, "msfs_light_outer_angle", "OuterConeAngle", PropertyTypes.INT
    CHANNEL_EXTERIOR = True, "msfs_light_channel_exterior", "ChannelExterior", PropertyTypes.BOOL
    CHANNEL_INTERIOR = True, "msfs_light_channel_interior", "ChannelInterior", PropertyTypes.BOOL


class MSFS2024_SkyPortalLight(CustomClassPropertiesDef):
    # SHAPE
    # SHAPE = "point", "msfs_light_shape_type","ShapeType",PropertyTypes.STRING
    SOURCE_RADIUS = 50.0, "msfs_light_source_radius", "SourceRadius", PropertyTypes.FLOAT
    INNER_ANGLE = 160.0, "msfs_light_inner_angle", "InnerConeAngle", PropertyTypes.FLOAT
    OUTER_ANGLE = 160.0, "msfs_light_outer_angle", "OuterConeAngle", PropertyTypes.FLOAT

LIGHTS_CLASS_PROPERTIES_DEFS = [
    MSFS2024_FastLight,
    MSFS2024_AdvancedLight,
    MSFS2024_SkyPortalLight,
]

class MSFS2024_BoxCollision(CustomClassPropertiesDef):

    SCALE_X = 1.0, "scale.x", "BoxGizmo.width", PropertyTypes.REAL_SIZE
    SCALE_Y = 1.0, "scale.y", "BoxGizmo.length", PropertyTypes.REAL_SIZE
    SCALE_Z = 1.0, "scale.z", "BoxGizmo.height", PropertyTypes.REAL_SIZE
    IS_ROAD_COLLIDER  = False , "Modifiers[.MSFS_2024_Collision]:Road Collider", "IsRoad", PropertyTypes.BOOL
    IS_GROUND_COLLIDER  = False , "Modifiers[.MSFS_2024_Collision]:Ground Collider", "IsGround", PropertyTypes.BOOL

class MSFS2024_SphereCollision(CustomClassPropertiesDef):

    SCALE = 1.0, "scale.x", "SphereGizmo.radius", PropertyTypes.REAL_SIZE
    IS_ROAD_COLLIDER  = False , "Modifiers[.MSFS_2024_Collision]:Road Collider", "IsRoad", PropertyTypes.BOOL
    IS_GROUND_COLLIDER  = False , "Modifiers[.MSFS_2024_Collision]:Ground Collider", "IsGround", PropertyTypes.BOOL

class MSFS2024_CylinderCollision(CustomClassPropertiesDef):

    SCALE_XY = 1.0, "scale.x", "CylGizmo.radius", PropertyTypes.REAL_SIZE
    SCALE_Z = 1.0, "scale.z", "CylGizmo.height", PropertyTypes.REAL_SIZE
    IS_ROAD_COLLIDER  = False , "Modifiers[.MSFS_2024_Collision]:Road Collider", "IsRoad", PropertyTypes.BOOL
    IS_GROUND_COLLIDER  = False , "Modifiers[.MSFS_2024_Collision]:Ground Collider", "IsGround", PropertyTypes.BOOL

COLLISIONS_CLASS_PROPERTIES_DEF = [
    MSFS2024_BoxCollision,
    MSFS2024_SphereCollision,
    MSFS2024_CylinderCollision,
]

class MSFS2024_CustomObjectClasses(CustomObjectClasses):
    FAST_LIGHT:tuple[str,CustomClassPropertiesDef] = ("streetLight","MSFS2024FastLight",MSFS2024_FastLight)
    ADVANCED_LIGHT:tuple[str,CustomClassPropertiesDef] = ("advancedLight","MSFS2024AdvancedLight",MSFS2024_AdvancedLight)
    SKY_PORTAL_LIGHT:tuple[str,CustomClassPropertiesDef] = ("skyPortalLight","MSFS2024SkyPortal",MSFS2024_SkyPortalLight)
    
    BOX_COLLISION:tuple[str,CustomClassPropertiesDef] = ("box","MSFS2024BoxGizmo",MSFS2024_BoxCollision)
    SPHERE_COLLISION:tuple[str,CustomClassPropertiesDef] = ("sphere","MSFS2024SphereGizmo",MSFS2024_SphereCollision)
    SPHERE_BOUNDING_COLLISION:tuple[str,CustomClassPropertiesDef] = ("boundingSphere","MSFS2024SphereBoundingVolumeGizmo",MSFS2024_SphereCollision)
    CYLINDER_COLLISION:tuple[str,CustomClassPropertiesDef] = ("cylinder","MSFS2024CylinderGizmo",MSFS2024_CylinderCollision)

# endregion
class MSFS2024_AlphaModes(Enum):

    OPAQUE = "OPAQUE"
    MASK = "MASK"
    BLEND = "BLEND"
    DITHER = "DITHER"


class MSFS2024_MaterialTypes(Enum):
    # order matter here, it needs to reflect material type index in max
    STANDARD = "msfs_standard"
    DECAL = "msfs_decal"
    WINDSHIELD = "msfs_windshield"
    PORTHOLE = "msfs_porthole"
    GLASS = "msfs_glass"
    GEODECALFROSTED = "msfs_geo_decal_frosted"
    CLEARCOAT = "msfs_clearcoat"
    PARALLAXWINDOW = "msfs_parallax_window"
    ANISOTRIPIC = "msfs_anisotropic"
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
    WINDFLEX = "msfs_windflex"
    TREE = "msfs_tree"
    VEGETATION = "msfs_vegetation"
    TIRE = "msfs_tire"

class MSFS2024_MaterialProperties(BridgePropertiesDef):
    """
    Enum describing the parameters of materials contains Tuples of:
    ( 
        Blender default Value, 
        blender attribute name of the property, 
        3dsmax attribute name of the property, 
        blender PropertyType,
        Optionnal 3dsMax default Value
    )
    """

    ## Parameters
    MATERIALTYPE =  "NONE", "msfs_material_type","materialType",PropertyTypes.STRING
    ALPHAMODE =  "OPAQUE", "msfs_alpha_mode","alphaMode",PropertyTypes.STRING

    BASECOLOR =  [1.0, 1.0, 1.0, 1.0], "msfs_base_color_factor","baseColor",PropertyTypes.COLOR
    EMISSIVECOLOR =  [0.0, 0.0, 0.0], "msfs_emissive_factor","emissive",PropertyTypes.COLOR
    SSSCOLOR =  [1.0, 1.0, 1.0, 1.0], "msfs_sss_color", "SSSColor",PropertyTypes.COLOR
    METALLICSCALE =  1.0, "msfs_metallic_factor","Metallic",PropertyTypes.FLOAT
    ROUGHNESSSCALE =  1.0, "msfs_roughness_factor","roughness",PropertyTypes.FLOAT
    NORMALSCALE =  1.0, "msfs_normal_scale","normalScale",PropertyTypes.FLOAT
    EMISSIVESCALE =  1.0, "msfs_emissive_scale","emissiveMul",PropertyTypes.FLOAT
    OCCLUSIONSTRENGTH =  1.0, "msfs_occlusion_strength","occlusionStrength",PropertyTypes.FLOAT
    ALPHACUTOFF =  0.5, "msfs_alpha_cutoff","alphaCutoff",PropertyTypes.FLOAT

    BASECOLORBLENDFACTOR =  1.0, "msfs_base_color_blend_factor","decalColorFactor",PropertyTypes.FLOAT
    METALLICBLENDFACTOR =  1.0, "msfs_metallic_blend_factor","decalMetalFactor",PropertyTypes.FLOAT
    ROUGHNESSBLENDFACTOR =  1.0, "msfs_roughness_blend_factor","decalRoughnessFactor",PropertyTypes.FLOAT
    NORMALBLENDFACTOR =  1.0, "msfs_normal_blend_factor","decalNormalFactor",PropertyTypes.FLOAT
    EMISSIVEBLENDFACTOR =  1.0, "msfs_emissive_blend_factor","decalEmissiveFactor",PropertyTypes.FLOAT
    OCCLUSIONBLENDFACTOR =  1.0, "msfs_occlusion_blend_factor","decalOcclusionFactor",PropertyTypes.FLOAT
    NORMALOVERRIDEFACTOR =  1.0, "msfs_normal_override_blend_factor","decalNormalOverrideFactor",PropertyTypes.FLOAT
    DECALBLENDSHARPNESS =  1.0, "msfs_decal_blend_sharpness","decalBlendSharpnessFactor",PropertyTypes.FLOAT
    DECALBLENDMASKEDTHRESHOLD =  0.0, "msfs_decal_blend_masked_threshold",NOTIMPLEMENTED,PropertyTypes.FLOAT
    DECALFREEZEFACTOR =  0.0, "msfs_decal_freeze_factor",NOTIMPLEMENTED,PropertyTypes.FLOAT
    DECALMODE = "default", "msfs_decal_mode",NOTIMPLEMENTED,PropertyTypes.STRING
    UNDERCLEARCOAT =  True, "msfs_under_clearcoat","decalRenderOnClearcoat",PropertyTypes.BOOL
   
    DRAWORDEROFFSET =  0, "msfs_draw_order_offset","drawOrder",PropertyTypes.INT
    NOCASTSHADOW =  False, "msfs_no_cast_shadow","noCastShadow",PropertyTypes.BOOL
    DAYNIGHTCYCLE = False, "msfs_day_night_cycle","dayNightCycle",PropertyTypes.BOOL
    DISABLEMOTIONBLUR = False, "msfs_disable_motion_blur","disableMotionBlur",PropertyTypes.BOOL
    DOUBLESIDED = False, "msfs_double_sided","DoubleSided",PropertyTypes.BOOL
    FLIPBACKFACENORMAL = False, "msfs_flip_back_face_normal","flipBackFace",PropertyTypes.BOOL
    
    CLAMPUVX =  False, "msfs_clamp_uv_x","clampUVX",PropertyTypes.BOOL
    CLAMPUVY =  False, "msfs_clamp_uv_y","clampUVY",PropertyTypes.BOOL
    UVOFFSETU =  0.0, "msfs_uv_offset_u","UVOffsetU",PropertyTypes.FLOAT
    UVOFFSETV =  0.0, "msfs_uv_offset_v","UVOffsetV",PropertyTypes.FLOAT
    UVTILINGU = 1.0, "msfs_uv_tiling_u","UVTilingU",PropertyTypes.FLOAT
    UVTILINGV =  1.0, "msfs_uv_tiling_v","UVTilingV",PropertyTypes.FLOAT
    UVROTATION = 0.0, "msfs_uv_rotation","UVRotation",PropertyTypes.FLOAT
    
    DETAILUVSCALE =  1.0, "msfs_detail_uv_scale","detailUVScale",PropertyTypes.FLOAT
    DETAILBLENDTHRESHOLD =  0.001, "msfs_detail_blend_threshold","blendThreshold",PropertyTypes.FLOAT
    DETAILNORMALSCALE =  1.0, "msfs_detail_normal_scale","detailNormalScale",PropertyTypes.FLOAT

    WEAROVERLAYUVSCALE = 1.0, "msfs_wear_overlay_uv_scale", "dirtUvScale",PropertyTypes.FLOAT
    WEARBLENDSHARPNESS =  0.0, "msfs_wear_blend_sharpness", "dirtBlendSharpness",PropertyTypes.FLOAT
    WEARAMOUNT = 0.0, "msfs_wear_amount","dirtBlendAmount",PropertyTypes.FLOAT

    COLLISIONMATERIAL = False, "msfs_collision_material","collisionMaterial", PropertyTypes.BOOL
    ROADCOLLISIONMATERIAL = False, "msfs_road_collision_material","roadMaterial", PropertyTypes.BOOL
    GROUNDCOLLISIONMATERIAL = False, "msfs_ground_collision_material","groundMaterial", PropertyTypes.BOOL

    GHOSTBIAS = 1.0, "msfs_ghost_bias","ghostBiasFactor",PropertyTypes.FLOAT
    GHOSTSCALE = 0.0, "msfs_ghost_scale","ghostPowerFactor",PropertyTypes.FLOAT
    GHOSTPOWER =  0.0, "msfs_ghost_power","ghostScaleFactor",PropertyTypes.FLOAT

    SAILLIGHTABSORPTION =  1.0, "msfs_sail_light_absorption","sailLightAbsorption",PropertyTypes.FLOAT

    # windflexMoveDetailNormal = False, "msfs_windflex_move_detail_normal","windFlexNormal",PropertyTypes.Bool

    RECEIVERAIN = False, "msfs_receive_rain","canReceiveRain",PropertyTypes.BOOL
    RAINDROPTILING =  1.0, "msfs_rain_drop_tiling","rainDropScale",PropertyTypes.FLOAT
    RAINONBACKFACE =  False, "msfs_rain_on_backface","rainDropSide",PropertyTypes.BOOL

    USEPEARLEFFECT = False, "msfs_use_pearl","pearlescent",PropertyTypes.BOOL
    PEARLCOLORSHIFT =  0.0, "msfs_pearl_shift","pearlShift",PropertyTypes.FLOAT
    PEARLCOLORRANGE =  0.0, "msfs_pearl_range","pearlRange",PropertyTypes.FLOAT
    PEARLCOLORBRIGHTNESS =  0.0, "msfs_pearl_brightness","pearlBrightness",PropertyTypes.FLOAT

    FRESNELFACTOR = 1.0, "msfs_fresnel_factor","fresnelFactor",PropertyTypes.FLOAT
    FRESNELOPACITYBIAS =  1.0, "msfs_fresnel_opacity_offset","fresnelOpacityOffset",PropertyTypes.FLOAT

    PARALLAXROOMSIZEX = 0.5, "msfs_parallax_room_size_x","roomSizeXScale",PropertyTypes.FLOAT
    PARALLAXROOMSIZEY = 0.5, "msfs_parallax_room_size_y","roomSizeYScale",PropertyTypes.FLOAT
    PARALLAXROOMSIZEZ = 0.0, "msfs_parallax_room_size_z",NOTIMPLEMENTED ,PropertyTypes.FLOAT
    PARALLAXROOMCOUNT =  5, "msfs_parallax_room_count_xy","roomNumberXY",PropertyTypes.INT
    PARALLAXCORRIDOR = False, "msfs_parallax_corridor","corridor",PropertyTypes.BOOL

    GLASSWIDTH =  0.0, "msfs_glass_width","glassWidth",PropertyTypes.FLOAT

    CLEARCOATROUGHNESSFACTOR =  1.0, "msfs_clearcoat_roughness_factor","clearcoatRoughnessFactor",PropertyTypes.FLOAT
    CLEARCOATNORMALFACTOR =  1.0, "msfs_clearcoat_normal_factor","clearcoatNormalFactor",PropertyTypes.FLOAT
    CLEARCOATCOLORROUGHNESSTILING =  1.0, "msfs_clearcoat_color_roughness_tiling","clearcoatColorRoughnessTiling",PropertyTypes.FLOAT
    CLEARCOATNORMALTILING =  1.0, "msfs_clearcoat_normal_tiling","clearcoatNormalTiling",PropertyTypes.FLOAT
    CLEARCOATINVERSEROUGHNESS = False, "msfs_clearcoat_inverse_roughness","clearcoatInverseRoughness",PropertyTypes.BOOL
    CLEARCOATBASEROUGHNESS =  0.5, "msfs_clearcoat_base_roughness","clearcoatBaseRoughness",PropertyTypes.FLOAT


    #region windshield
    WINDSHIELDDETAILROUGHNESS1 =  0.1, "msfs_windshield_detail_rough_1","detail1Rough",PropertyTypes.FLOAT
    WINDSHIELDDETAILROUGHNESS2 =  0.1, "msfs_windshield_detail_rough_2","detail2Rough",PropertyTypes.FLOAT
    WINDSHIELDDETAILOPACITY1 =  0.5, "msfs_windshield_detail_opacity_1","detail1Opacity",PropertyTypes.FLOAT
    WINDSHIELDDETAILOPACITY2 =  0.5, "msfs_windshield_detail_opacity_2","detail2Opacity",PropertyTypes.FLOAT
    WINDSHIELDMICROSCRATCHTILING = 1.0, "msfs_windshield_micro_scratches_tiling","microScratchesTiling",PropertyTypes.FLOAT
    WINDSHIELDMICROSCRATCHSTRENGTH = 1.0, "msfs_windshield_micro_scratches_strength","microScratchesStrength",PropertyTypes.FLOAT
    WINDSHIELDDETAILNORMALREFRACTSCALE = 1.0, "msfs_windshield_detail_normal_refract_scale","detailNormalRefractScale",PropertyTypes.FLOAT
    WINDSHIELDWIPERLINES =  False, "msfs_windshield_wiper_lines","wiperLines",PropertyTypes.BOOL
    WINDSHIELDWIPERLINESTILING =  1.0, "msfs_windshield_wiper_lines_tiling","wiperLinesTiling",PropertyTypes.FLOAT
    WINDSHIELDWIPERLINESSTRENGTH = 1.0, "msfs_windshield_wiper_lines_strength","wiperLinesStrength",PropertyTypes.FLOAT
    WINDSHIELDWIPER1STATE = 0.0, "msfs_windshield_wiper_1_state","wiperAnimState1",PropertyTypes.FLOAT
    WINDSHIELDREFLECTIONMASKSTRENGTH =  1.0, "msfs_occlusion_strength","occlusionStrength",PropertyTypes.FLOAT
    WINDSHIELDSSRATTENUATION = 1.0, "msfs_ssr_attenuation", "ssrAttenuation",PropertyTypes.FLOAT
    WINDSHIELDCUBEMAPREFLECTIONMASKING = False, "msfs_cubemap_reflection_masking", "cubemapReflectionMasking",PropertyTypes.BOOL

    USEIRIDESCENT =  False, "msfs_use_iridescent","iridescent",PropertyTypes.BOOL
    IRIDESCENTMINTHICKNESS = 400.0, "msfs_iridescent_min_thickness","iridescentMinThickness",PropertyTypes.FLOAT
    IRIDESCENTMAXTHICKNESS = 400.0, "msfs_iridescent_max_thickness","iridescentMaxThickness",PropertyTypes.FLOAT
    IRIDESCENTBRIGHTNESS = 1.0, "msfs_iridescent_brightness","iridescentBrightness",PropertyTypes.FLOAT
    #end region
    
    #TEXTURES:
    BASECOLORTEXTURE =  None, "msfs_base_color_texture","BaseColorTex",PropertyTypes.TEXTURE
    OMRTEXTURE =  None, "msfs_occlusion_metallic_roughness_texture","OcclusionRoughnessMetallicTex",PropertyTypes.TEXTURE
    NORMALTEXTURE = None, "msfs_normal_texture","NormalTex",PropertyTypes.TEXTURE
    EMISSIVETEXTURE = None,"msfs_emissive_texture","EmissiveTex",PropertyTypes.TEXTURE

    DETAILCOLORTEXTURE = None, "msfs_detail_color_texture","DetailColorTex",PropertyTypes.TEXTURE
    DETAILOMRTEXTURE = None, "msfs_detail_occlusion_metallic_roughness_texture","DetailOcclusionRoughnessMetallicTex",PropertyTypes.TEXTURE
    DETAILNORMALTEXTURE = None, "msfs_detail_normal_texture","DetailNormalTex",PropertyTypes.TEXTURE

    BLENDMASKTEXTURE = None, "msfs_blend_mask_texture","BlendMaskTex",PropertyTypes.TEXTURE
    OCCLUSIONUV2 = None, "msfs_occlusion_uv2","OcclusionTex",PropertyTypes.TEXTURE
    
    DECALBLENDMASKTEXTURE = None, "msfs_decal_blend_mask_texture","BlendMaskTex",PropertyTypes.TEXTURE
    DECALMELTROUGHNESSMETALLICTEXTURE = None, "msfs_detail_occlusion_metallic_roughness_texture","DetailOcclusionRoughnessMetallicTex",PropertyTypes.TEXTURE

    CLEARCOATCOLORROUGHNESSTEXTURE =  None, "msfs_clearcoat_color_roughness_texture","ClearcoatColorRoughnessTex",PropertyTypes.TEXTURE
    CLEARCOATNORMALTEXTURE = None, "msfs_clearcoat_normal_texture","ClearcoatNormalTex",PropertyTypes.TEXTURE

    FRONTGLASSCOLORTEXTURE =  None, "msfs_base_color_texture","BaseColorTex",PropertyTypes.TEXTURE
    FRONTGLASSNORMALTEXTURE = None, "msfs_normal_texture","NormalTex",PropertyTypes.TEXTURE
    EMISSIVEINSIDEWINDOWTEXTURE =  None, "msfs_emissive_texture","EmissiveTex",PropertyTypes.TEXTURE
    BEHINDGLASSCOLORTEXTURE =  None, "msfs_behind_glass_color_texture",NOTIMPLEMENTED,PropertyTypes.TEXTURE

    OPACITYTEXTURE =  None, "msfs_opacity_texture","OpacityTex",PropertyTypes.TEXTURE

    OCCANISOROUGHXMETALICTEXTURE = None, "msfs_occlusion_metallic_roughness_texture","OcclusionRoughnessMetallicTex",PropertyTypes.TEXTURE
    ANISODIRECTIONROUGHNESSTEXTURE =  None, "msfs_anisotropic_direction_roughnessy_texture","AnisoDirectionRoughnessTex",PropertyTypes.TEXTURE

    WEARALBEDOMASKTEXTURE =  None, "msfs_wear_albedo_mask",NOTIMPLEMENTED,PropertyTypes.TEXTURE
    WEAROMRINTENSITYTEXTURE = None, "msfs_wear_omr_intensity",NOTIMPLEMENTED,PropertyTypes.TEXTURE

    WINDSHIELDWIPERMASKTEXTURE = None, "msfs_windshield_wiper_mask_texture","WiperMaskTex",PropertyTypes.TEXTURE
    WINDSHIELDREFLECTIONROUGHNESSMETALLICTEXTURE =  None, "msfs_occlusion_metallic_roughness_texture","OcclusionRoughnessMetallicTex",PropertyTypes.TEXTURE
    WINDSHILEDDETAILNORMALTEXTURE =  None, "msfs_windshield_detail_normal_texture","WindshieldDetailNormalTex",PropertyTypes.TEXTURE
    WINDSHIELDSCRACHESNORMALTEXTURE = None, "msfs_windshield_scratches_normal_texture","ScratchesNormalTex",PropertyTypes.TEXTURE
    WINDSHIELDINSECTSALBEDOTEXTURE = None, "msfs_windshield_insects_albedo_texture","WindshieldInsectsTex",PropertyTypes.TEXTURE
    WINDSHIELDINSECTSMASKTEXTURE =  None, "msfs_windshield_insects_mask_texture","WindshieldInsectsMaskTex",PropertyTypes.TEXTURE
    WINDSHIELDSECONDARYDETAILSTEXTURE =  None, "msfs_emissive_texture","EmissiveTex",PropertyTypes.TEXTURE
    DETAILS1ICINGMASKDETAILS2TEXTURE =  None, "msfs_detail_color_texture","DetailColorTex",PropertyTypes.TEXTURE
    DETAILSWINDSHIELDREFLECTIONROUGHNESSMETALLICTEXTURE = None, "msfs_detail_occlusion_metallic_roughness_texture","DetailOcclusionRoughnessMetallicTex",PropertyTypes.TEXTURE
    ICINGNORMALTEXTURE = None, "msfs_detail_normal_texture","DetailNormalTex",PropertyTypes.TEXTURE
    REFLECTIONMASKTEXTURE = None, "msfs_occlusion_uv2",NOTIMPLEMENTED,PropertyTypes.TEXTURE
    IRIDESCENTTHICKNESSTEXTURE =  None, "msfs_iridescent_thickness_texture","IridescentThicknessTex",PropertyTypes.TEXTURE

    FOLIAGEMASKTEXTURE =  None, "msfs_foliage_mask_texture","FoliageMaskTex",PropertyTypes.TEXTURE


class MSFS2024_ObjectExportProperties(BridgePropertiesDef):
    """Enum describing export parameters contains Tuples of:
    ( 
        Blender default Value, 
        blender attribute name of the property, 
        3dsmax attribute name of the property, 
        blender PropertyType,
        Optionnal 3dsMax default Value
    )"""
    EXPORT_POSITION =False,NOTIMPLEMENTED,"flightsim_export_position",PropertyTypes.BOOL
    EXPORT_ROTATION =True,NOTIMPLEMENTED,"flightsim_export_rotation",PropertyTypes.BOOL
    EXPORT_SCALE = True,NOTIMPLEMENTED,"flightsim_export_scale",PropertyTypes.BOOL
    EXPORT_TRANSFORM =False,NOTIMPLEMENTED,"flightsim_export_transform",PropertyTypes.BOOL
    EXPORT_PATH="","folder_path","flightsim_multiexporter_path",PropertyTypes.PATH
    LOD_AUTOGEN=False,"autogenerate_lods","flightsim_lod_autogen",PropertyTypes.BOOL
    LOD_VALUE =0,"lod_value","flightsim_lod_value" ,PropertyTypes.FLOAT
    GENERATE_XML=True,"generate_xml",NOTIMPLEMENTED, PropertyTypes.BOOL #not implemented on node properties in max, this is a global multiexporter attribute

class MSFS2024_ExportOptionPresetProperties(BridgePropertiesDef):
    """Enum describing default preset export parameters contains Tuples of:
    ( 
        Blender default Value, 
        blender attribute name of the property, 
        3dsmax attribute name of the property, 
        blender PropertyType,
        Optionnal 3dsMax default Value
    )"""
    # AUTOSAVE = False, NOTIMPLEMENTED,"babylonjs_autosave",PropertyTypes.BOOL
    EXPORT_HIDDEN = False, "use_visible","babylonjs_exporthidden",PropertyTypes.BOOL
    REMOVE_LOD_PREFIX = False, "remove_lod_prefix","flightsim_removelodprefix",PropertyTypes.BOOL
    EXPORT_MATERIALS = False, "export_materials","babylonjs_export_materials",PropertyTypes.BOOL
    # ANIM_GROUP_EXPORT_NON_ANIMATED = False, NOTIMPLEMENTED,"babylonjs_animgroupexportnonanimated",PropertyTypes.BOOL

    PREPROCESS = False, NOTIMPLEMENTED,"babylonjs_preproces",PropertyTypes.BOOL
    # MERGE_CONTAINER_AND_XREF = False, NOTIMPLEMENTED,"babylonjs_mergecontainersandxref",PropertyTypes.BOOL
    # TANGENT_SPACE_CONVENTION = False, NOTIMPLEMENTED,"flightsim_tangent_space_convention",PropertyTypes.INT
    # APPLY_PREPROCESS = False, NOTIMPLEMENTED,"babylonjs_applyPreprocess",PropertyTypes.BOOL
    FLATTEN_NODES = False, "merge_nodes", "flightsim_flattenNodes", PropertyTypes.BOOL

    BAKE_ANIMATION = False, "export_bake_animation","babylonjs_bakeAnimationsType",PropertyTypes.BOOL
    # ASB_ANIMATION_RETARGETING = False, NOTIMPLEMENTED,"babylonjs_asb_animation_retargeting",PropertyTypes.BOOL
    WRITE_TEXTURES = False, "export_keep_originals","babylonjs_writetextures",PropertyTypes.BOOL
    TEXTURE_FOLDER_PATH_PROPERTY = "", "export_texture_dir","textureFolderPathProperty",PropertyTypes.STRING
    # TXT_COMPRESSION = False, NOTIMPLEMENTED,"babylonjs_txtCompression",PropertyTypes.INT

    # TXT_SCALE_FACTOR = False, NOTIMPLEMENTED,"babylonjs_txtScaleFactor",PropertyTypes.INT
    EXPORT_ANIMATION_TYPE = False, NOTIMPLEMENTED,"babylonjs_export_animations_type",PropertyTypes.STRING
    # KEEP_INSTANCES = False, NOTIMPLEMENTED,"flightsim_keepInstances",PropertyTypes.BOOL
    ASB_UNIQUE_ID = False, "use_unique_id","flightsim_asb_unique_id",PropertyTypes.BOOL
    # ONLY_SELECTED = False, NOTIMPLEMENTED,"babylonjs_onlySelected",PropertyTypes.BOOL
    EXPORT_AS_SUBMODEL = False, "export_as_submodel","flightsim_exportAsSubmodel",PropertyTypes.BOOL

    #Blender Only properties
    EXPORT_MESH = True, "export_mesh", NOTIMPLEMENTED, PropertyTypes.BOOL
    EXPORT_MORPH = False, "export_morph", NOTIMPLEMENTED, PropertyTypes.BOOL
    EXPORT_SKINS = True, "export_skins", NOTIMPLEMENTED, PropertyTypes.BOOL
    EXPORT_ANIMATIONS = False, "export_animations", NOTIMPLEMENTED, PropertyTypes.BOOL

class MSFS2024_ExportCustomProperties(Enum):

    presets = "presets"
    preset_groups = "preset_groups"
    export_options_presets = "export_options_presets"
    anim_groups = "anim_groups"

@dataclass
class MSFS2024_PresetDef(SeriazableDef):
    group: str
    path: str
    layer_names: list[str]

@dataclass
class MSFS2024_PresetGroupDef(SeriazableDef):
    path: str
    export_options: str

@dataclass
class MSFS2024_ExportOptionsPresetDef(SeriazableDef):
    options_dict: str

def get_presets_from_custom_properties(custom_properties) -> tuple[list[MSFS2024_PresetDef], list[MSFS2024_PresetGroupDef]]:
    preset_definitions = []
    preset_group_definitions = []

    presets = custom_properties.get(MSFS2024_ExportCustomProperties.presets.value,[])
    for preset_def_dict in presets:
        preset_def = MSFS2024_PresetDef(**preset_def_dict)
        preset_definitions.append(preset_def)
        
    preset_groups = custom_properties.get(MSFS2024_ExportCustomProperties.preset_groups.value,[])
    for preset_def_dict in preset_groups:
        preset_def = MSFS2024_PresetGroupDef(**preset_def_dict)
        preset_group_definitions.append(preset_def)

    return (preset_definitions,preset_group_definitions)

def get_export_options_presets_from_custom_properties(custom_properties) -> list[MSFS2024_ExportOptionsPresetDef]:

    export_options_presets_definitions = []

    export_options_presets = custom_properties.get(MSFS2024_ExportCustomProperties.export_options_presets.value,[])
    for export_option_preset_def_dict in export_options_presets:
        export_option_def = MSFS2024_ExportOptionsPresetDef(**export_option_preset_def_dict)
        export_options_presets_definitions.append(export_option_def)

    return export_options_presets_definitions

@dataclass
class MSFS2024_AnimGroupDef(SeriazableDef):
    frame_start: int
    frame_end : int
    nodes: list[int]
    materials: list[int]

def get_anim_groups_from_custom_properties(custom_properties) -> list[MSFS2024_AnimGroupDef]:

    anim_groups_definitions = []

    anim_groups = custom_properties.get(MSFS2024_ExportCustomProperties.anim_groups.value,[])
    for anim_group_def_dict in anim_groups:
        anim_group_def = MSFS2024_AnimGroupDef(**anim_group_def_dict)
        anim_group_def.frame_start = int(anim_group_def.frame_start)
        anim_group_def.frame_end = int(anim_group_def.frame_end)
        anim_groups_definitions.append(anim_group_def)

    return anim_groups_definitions

# region Max Material Properties
"""
  .radianceMap : filename
  .irradianceMap : filename
  .uniqueInContainer : boolean
  .materialType : integer
  .basecolor : point4
  .emissive : point4
  .dayNightCycle : boolean
  .roughness : float
  .emissiveMul : float
  .Metallic : float
  .occlusionStrength : float
  .normalScale : float
  .windFlexNormal : boolean
  .pearlescent : boolean
  .pearlShift : float
  .pearlRange : float
  .pearlBrightness : float
  .iridescent : boolean
  .iridescentMinThickness : float
  .iridescentMaxThickness : float
  .iridescentBrightness : float
  .sailLightAbsorption : float
  .alphaMode : integer
  .drawOrder : integer
  .alphaCutoff : float
  .detailUVScale : float
  .detailNormalScale : float
  .blendThreshold : float
  .dirtUvScale : float
  .dirtBlendSharpness : float
  .dirtBlendAmount : float
  .DoubleSided : boolean
  .decalColorFactor : float
  .decalRoughnessFactor : float
  .decalMetalFactor : float
  .decalOcclusionFactor : float
  .decalNormalFactor : float
  .decalEmissiveFactor : float
  .decalRenderOnClearcoat : boolean
  .decalNormalOverrideFactor : float
  .decalBlendSharpnessFactor : float
  .clearcoatRoughnessFactor : float
  .clearcoatNormalFactor : float
  .clearcoatColorRoughnessTiling : float
  .clearcoatNormalTiling : float
  .clearcoatInverseRoughness : boolean
  .clearcoatBaseRoughness : float
  .parallaxScale : float
  .roomSizeXScale : float
  .roomSizeYScale : float
  .roomNumberXY : float
  .corridor : boolean
  .glassWidth : float
  .fresnelFactor : float
  .fresnelOpacityOffset : float
  .ghostBiasFactor : float
  .ghostPowerFactor : float
  .ghostScaleFactor : float
  .SSSColor : point4
  .collisionMaterial : boolean
  .roadMaterial : boolean
  .groundMaterial : boolean
  .disableMotionBlur : boolean
  .flipBackFace : boolean
  .noCastShadow : boolean
  .clampUVX : boolean
  .clampUVY : boolean
  .UVOffsetU : float
  .UVOffsetV : float
  .UVTilingU : float
  .UVTilingV : float
  .UVRotation : float
  .detail1Rough : float
  .detail2Rough : float
  .detail1Opacity : float
  .detail2Opacity : float
  .detailNormalRefractScale : float
  .wiperAnimState1 : float
  .microScratchesTiling : float
  .microScratchesStrength : float
  .wiperLines : boolean
  .wiperLinesTiling : float
  .wiperLinesStrength : float
  .ssrAttenuation : float
  .cubemapReflectionMasking : boolean
  .canReceiveRain : boolean
  .rainDropScale : float
  .rainDropSide : boolean
  .tireMudNormalTiling : float
  .tireMudAnimState : float
  .tireDustAnimState : float
  .guid : string
  .debugWindshield_WiperMask : boolean
  .debugWindshield_InsectsAlbedo : boolean
  .debugWindshield_InsectsMask : float
  .debugWindshield_VertexColorR : boolean
  .debugWindshield_VertexColorG : boolean
  .debugWindshield_VertexColorB : boolean
  .debugWindshield_VertexColorA : boolean
  .texSlotSize : integer
  .BaseColorTex : filename
  .OcclusionRoughnessMetallicTex : filename
  .NormalTex : filename
  .WetnessAOTex : filename
  .WindshieldDetailNormalTex : filename
  .AnisoDirectionRoughnessTex : filename
  .OpacityTex : filename
  .DirtTex : filename
  .DirtOcclusionRoughnessMetallicTex : filename
  .EmissiveTex : filename
  .DetailColorTex : filename
  .DetailOcclusionRoughnessMetallicTex : filename
  .DetailNormalTex : filename
  .BlendMaskTex : filename
  .FoliageMaskTex : filename
  .OcclusionTex : filename
  .ClearcoatColorRoughnessTex : filename
  .ClearcoatNormalTex : filename
  .ScratchesNormalTex : filename
  .WiperMaskTex : filename
  .IridescentThicknessTex : filename
  .WindshieldInsectsTex : filename
  .WindshieldInsectsMaskTex : filename
  .TireDetailsTex : filename
  .TireMudNormalTex : filename
"""
# endregion
