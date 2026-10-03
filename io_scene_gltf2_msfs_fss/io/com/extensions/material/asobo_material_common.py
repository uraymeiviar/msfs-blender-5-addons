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

from .....blender.material.msfs_material_properties_update import MSFS2024_MaterialPropUpdate
from .....blender.utils.msfs_material_utils import (
    MSFS2024_MaterialProperties,
    MSFS2024_MaterialTypes
)

from ....com.msfs_material_utils import MSFS2024_MaterialUtils

from io_scene_gltf2.io.com.gltf2_io import (
    TextureInfo,
    MaterialOcclusionTextureInfoClass,
    MaterialNormalTextureInfoClass
)

class AsoboMaterialCommon:

    @staticmethod
    def _extract_emissive_values(emissive_factor: list[float]) -> tuple[[float], float]:
        """Extract the emissive scale and emissive color from the GLTF emissive factor.

        In the exported GLTF, the emissive factor represents the product of 
        the emissive color (RGB, range [0, 1]) and the emissive scale (scalar).
        Since the GLTF does not store emissive color and scale 
        separately, this function calculates them based on the emissive factor.
        It's a bit destructive since we are not able to retrieve orignal values
        but emissive factor will be identical in game.

        Args:
            emissive_factor : A list of three floats representing 
                                            the emissive factor (R, G, B).

        Returns:
            tuple:
                - emissive_color : The emissive color as an RGB list 
                                                with values normalized to [0, 1].
                - emissive_scale : The emissive scale as a scalar value.
        """

        emissive_color = [0, 0, 0]
        # Get emissive_scale as the maximum of emissive_factor
        emissive_scale = max(emissive_factor)
        if not emissive_scale:
            return emissive_color, emissive_scale

        # Calculate the emissive_color by dividing emissive_factor by emissive_scale
        for i, factor in enumerate(emissive_factor):
            emissive_color[i] = factor / emissive_scale

        return emissive_color, emissive_scale

    @staticmethod
    def set_pbr_texture_values():
        return
    
    @staticmethod
    def get_base_color_texture_info(blender_material, export_settings):
        return MSFS2024_MaterialUtils.get_texture_info(
            blender_material=blender_material,
            attribute=MSFS2024_MaterialProperties.BASECOLORTEXTURE.attribute_name(),
            export_settings=export_settings
        )
    
    @staticmethod
    def get_pbr_omr_texture_info(blender_material, export_settings):
        return MSFS2024_MaterialUtils.get_texture_info(
            blender_material=blender_material,
            attribute=MSFS2024_MaterialProperties.OMRTEXTURE.attribute_name(),
            export_settings=export_settings
        )
    
    @staticmethod
    def get_emissive_texture_info(blender_material, export_settings):
        return MSFS2024_MaterialUtils.get_texture_info(
            blender_material=blender_material,
            attribute=MSFS2024_MaterialProperties.EMISSIVETEXTURE.attribute_name(),
            export_settings=export_settings
        )
    
    @staticmethod
    def get_normal_texture_info(blender_material, export_settings):
        return MSFS2024_MaterialUtils.get_texture_info(
            blender_material=blender_material,
            attribute=MSFS2024_MaterialProperties.NORMALTEXTURE.attribute_name(),
            export_settings=export_settings,
            image_type="NORMAL"
        )
    
    @staticmethod
    def from_dict(blender_material, gltf2_material, import_settings):
        # We set blender_material to standard.
        # If the blender_material is another type, it will get changed later
        setattr(
            blender_material,
            MSFS2024_MaterialProperties.MATERIALTYPE.attribute_name(),
            MSFS2024_MaterialTypes.STANDARD.value
        )

        if gltf2_material.pbr_metallic_roughness:
            if gltf2_material.pbr_metallic_roughness.base_color_factor is not None:
                setattr(
                    blender_material,
                    MSFS2024_MaterialProperties.BASECOLOR.attribute_name(),
                    gltf2_material.pbr_metallic_roughness.base_color_factor
                )

            if gltf2_material.pbr_metallic_roughness.metallic_factor is not None:
                setattr(
                    blender_material,
                    MSFS2024_MaterialProperties.METALLICSCALE.attribute_name(),
                    gltf2_material.pbr_metallic_roughness.metallic_factor
                )

            if gltf2_material.pbr_metallic_roughness.roughness_factor is not None:
                setattr(
                    blender_material,
                    MSFS2024_MaterialProperties.ROUGHNESSSCALE.attribute_name(),
                    gltf2_material.pbr_metallic_roughness.roughness_factor
                )

            if gltf2_material.pbr_metallic_roughness.base_color_texture is not None:
                setattr(
                    blender_material,
                    MSFS2024_MaterialProperties.BASECOLORTEXTURE.attribute_name(),
                    MSFS2024_MaterialUtils.create_image(
                        gltf2_material.pbr_metallic_roughness.base_color_texture.index,
                        import_settings
                    )
                )

            if gltf2_material.pbr_metallic_roughness.metallic_roughness_texture is not None:
                setattr(
                    blender_material,
                    MSFS2024_MaterialProperties.OMRTEXTURE.attribute_name(),
                    MSFS2024_MaterialUtils.create_image(
                        gltf2_material.pbr_metallic_roughness.metallic_roughness_texture.index,
                        import_settings
                    )
                )

        if gltf2_material.emissive_factor is not None:
            emissive_color, emissive_scale = (
                AsoboMaterialCommon._extract_emissive_values(
                    gltf2_material.emissive_factor
                )
            )
            setattr(
                blender_material,
                MSFS2024_MaterialProperties.EMISSIVESCALE.attribute_name(),
                emissive_scale
            )
            setattr(
                blender_material,
                MSFS2024_MaterialProperties.EMISSIVECOLOR.attribute_name(),
                emissive_color
            )

        if gltf2_material.alpha_mode is not None:
            setattr(
                blender_material,
                MSFS2024_MaterialProperties.ALPHAMODE.attribute_name(),
                gltf2_material.alpha_mode
            )

        if gltf2_material.alpha_cutoff is not None:
            setattr(
                blender_material,
                MSFS2024_MaterialProperties.ALPHACUTOFF.attribute_name(),
                gltf2_material.alpha_cutoff
            )

        if gltf2_material.double_sided is not None:
            setattr(
                blender_material,
                MSFS2024_MaterialProperties.DOUBLESIDED.attribute_name(),
                gltf2_material.double_sided
            )

        if gltf2_material.normal_texture is not None:
            setattr(
                blender_material,
                MSFS2024_MaterialProperties.NORMALTEXTURE.attribute_name(),
                MSFS2024_MaterialUtils.create_image(
                    gltf2_material.normal_texture.index,
                    import_settings
                )
            )

            if gltf2_material.normal_texture.scale is not None:
                setattr(
                    blender_material,
                    MSFS2024_MaterialProperties.NORMALSCALE.attribute_name(),
                    gltf2_material.normal_texture.scale
                )

        if gltf2_material.emissive_texture is not None:
            setattr(
                blender_material,
                MSFS2024_MaterialProperties.EMISSIVETEXTURE.attribute_name(),
                MSFS2024_MaterialUtils.create_image(
                    gltf2_material.emissive_texture.index,
                    import_settings
                )
            )
    
    @staticmethod
    def to_extension(blender_material, gltf2_material, export_settings):
        # region Base Color Texture
        base_color_texture_info = AsoboMaterialCommon.get_base_color_texture_info(
            blender_material,
            export_settings,
        )
        gltf2_material.pbr_metallic_roughness.base_color_texture = base_color_texture_info
        # endregion

        # region OMR Texture
        omrfields = {
            'extensions': None,
            'extras': None,
            'index': None,
            'strength': None,
            'tex_coord': None
        }
        omr_texture_info = AsoboMaterialCommon.get_pbr_omr_texture_info(
            blender_material,
            export_settings,
        )
        gltf2_material.pbr_metallic_roughness.metallic_roughness_texture = omr_texture_info
        if omr_texture_info is not None:
            if gltf2_material.occlusion_texture is None:
                gltf2_material.occlusion_texture = MaterialOcclusionTextureInfoClass(**omrfields)
            gltf2_material.occlusion_texture.index = omr_texture_info.index
        # endregion

        # region Emissive Texture
        fields = {
            'extensions': None,
            'extras': None,
            'index': None,
            'tex_coord': None
        }
        emissive_texture_info = AsoboMaterialCommon.get_emissive_texture_info(
            blender_material,
            export_settings,
        )
        
        if emissive_texture_info is not None:
            if gltf2_material.emissive_texture is None:
                gltf2_material.emissive_texture = TextureInfo(**fields)
            gltf2_material.emissive_texture.index = emissive_texture_info.index
        # endregion

        # region Normal Texture
        normalfields = {
            'extensions': None,
            'extras': None,
            'index': None,
            'scale': None,
            'tex_coord': None
        }
        normal_texture_info = AsoboMaterialCommon.get_normal_texture_info(
            blender_material,
            export_settings,
        )
        
        if normal_texture_info is not None:
            if gltf2_material.normal_texture is None:
                gltf2_material.normal_texture = MaterialNormalTextureInfoClass(**normalfields)
            gltf2_material.normal_texture.index = normal_texture_info.index

        # endregion

        # region Properties
        gltf2_material.pbr_metallic_roughness.base_color_factor = [
            f for f in getattr(
                blender_material,
                MSFS2024_MaterialProperties.BASECOLOR.attribute_name()
            )
        ]
        gltf2_material.emissive_factor = [
            f * getattr(
                blender_material,
                MSFS2024_MaterialProperties.EMISSIVESCALE.attribute_name()
            )
            for f in getattr(
                blender_material,
                MSFS2024_MaterialProperties.EMISSIVECOLOR.attribute_name()
            )
        ]

        gltf2_material.pbr_metallic_roughness.metallic_factor = getattr(
            blender_material,
            MSFS2024_MaterialProperties.METALLICSCALE.attribute_name()
        )

        gltf2_material.pbr_metallic_roughness.roughness_factor = getattr(
            blender_material,
            MSFS2024_MaterialProperties.ROUGHNESSSCALE.attribute_name()
        )

        if gltf2_material.normal_texture:
            gltf2_material.normal_texture.scale = getattr(
                blender_material,
                MSFS2024_MaterialProperties.NORMALSCALE.attribute_name()
            )

        
        gltf2_material.alpha_mode = getattr(
            blender_material,
            MSFS2024_MaterialProperties.ALPHAMODE.attribute_name()
        )

        if gltf2_material.alpha_mode == "MASK":
            gltf2_material.alpha_cutoff = getattr(
                blender_material,
                MSFS2024_MaterialProperties.ALPHACUTOFF.attribute_name()
            )

        gltf2_material.double_sided = getattr(
            blender_material,
            MSFS2024_MaterialProperties.DOUBLESIDED.attribute_name()
        )

        if "KHR_materials_emissive_strength" in gltf2_material.extensions:
            gltf2_material.extensions.pop("KHR_materials_emissive_strength")
        # endregion


def register():
    
    # region Properties
    ## WARNING - Here the order of the items matters for retro-compatibility of scenes
    bpy.types.Material.msfs_material_type = bpy.props.EnumProperty(
        name="Type",
        items=(
            ("NONE", "Disabled", ""),
            ("msfs_standard", "Standard", ""),
            ("msfs_decal", "Decal", ""),
            ("msfs_geo_decal_frosted", "Geo Decal Frosted", ""),
            ("msfs_windshield", "Windshield", ""),
            ("msfs_porthole", "Porthole", ""),
            ("msfs_glass", "Glass", ""),
            ("msfs_clearcoat", "Clearcoat", ""),
            ("msfs_parallax_window", "Parallax Window", ""),
            ("msfs_anisotropic", "Anisotropic", ""),
            ("msfs_hair", "Hair", ""),
            ("msfs_sss", "Sub-surface Scattering", ""),
            ("msfs_invisible", "Invisible", ""),
            ("msfs_fake_terrain", "Fake Terrain", ""),
            ("msfs_fresnel_fade", "Fresnel Fade", ""),
            ("msfs_environment_occluder", "Environment Occluder", ""),
            ("msfs_ghost", "Ghost", ""),
            ("msfs_geo_decal_blendmasked", "Geo Decal BlendMasked", ""),
            ("msfs_sail", "Sail", ""),
            ("msfs_propeller", "Propeller", ""),
            ("msfs_tree", "Tree", ""),
            ("msfs_vegetation", "Vegetation", ""),
            ("msfs_tire", "Tire", "")
        ),
        default=MSFS2024_MaterialProperties.MATERIALTYPE.default_value(),

        update=lambda material, context: MSFS2024_MaterialPropUpdate.update_msfs_material_type(
            material=material,
            rebuild_native_mat=True
        )
    )

    bpy.types.Material.msfs_base_color_factor = bpy.props.FloatVectorProperty(
        name=MSFS2024_MaterialProperties.BASECOLOR.property_name(),
        description="The RGBA components of the base color of the material.\n"
                    "The fourth component (A) is the alpha coverage of the material.\n"
                    "The alphaMode property specifies how alpha is interpreted.\n"
                    "These values are linear.\n"
                    "If a baseColorTexture is specified, this value is multiplied with the texel values",
        subtype="COLOR",
        min=0.0,
        max=1.0,
        size=4,
        default=MSFS2024_MaterialProperties.BASECOLOR.default_value(),
        options={"ANIMATABLE"},
        set=MSFS2024_MaterialPropUpdate.set_base_color,
        get=MSFS2024_MaterialPropUpdate.get_base_color,
        precision=3
    )

    bpy.types.Material.msfs_emissive_factor = bpy.props.FloatVectorProperty(
        name=MSFS2024_MaterialProperties.EMISSIVECOLOR.property_name(),
        description="The RGB components of the emissive color of the material.\n"
                    "These values are linear.\n"
                    "If an Emissive Texture is specified, this value is multiplied with the texel values",
        subtype="COLOR",
        min=0.0,
        max=1.0,
        size=3,
        default=MSFS2024_MaterialProperties.EMISSIVECOLOR.default_value(),
        options={"ANIMATABLE"},
        set=MSFS2024_MaterialPropUpdate.set_emissive_color,
        get=MSFS2024_MaterialPropUpdate.get_emissive_color,
        precision=3
    )

    bpy.types.Material.msfs_metallic_factor = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.METALLICSCALE.property_name(),
        description="The metalness of the material. A value of 1.0 means the material is a metal.\n"
                    "A value of 0.0 means the material is a dielectric.\n"
                    "Values in between are for blending between metals and dielectrics such as dirty metallic surfaces.\n"
                    "This value is linear.\n"
                    "If a Metallic Roughness Texture is specified, this value is multiplied with the metallic texel values",
        min=0.0,
        max=1.0,
        default=MSFS2024_MaterialProperties.METALLICSCALE.default_value(),
        options={"ANIMATABLE"},
        set=MSFS2024_MaterialPropUpdate.set_metallic_scale,
        get=MSFS2024_MaterialPropUpdate.get_metallic_scale,
        precision=3
    )

    bpy.types.Material.msfs_roughness_factor = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.ROUGHNESSSCALE.property_name(),
        description="The roughness of the material. A value of 1.0 means the material is completely rough.\n"
                    "A value of 0.0 means the material is completely smooth. This value is linear.\n"
                    "If a metallicRoughnessTexture is specified, this value is multiplied with the roughness texel values",
        min=0.0,
        max=1.0,
        default=MSFS2024_MaterialProperties.ROUGHNESSSCALE.default_value(),
        options={"ANIMATABLE"},
        set=MSFS2024_MaterialPropUpdate.set_roughness_scale,
        get=MSFS2024_MaterialPropUpdate.get_roughness_scale,
        precision=3
    )

    bpy.types.Material.msfs_normal_scale = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.NORMALSCALE.property_name(),
        description="The scalar multiplier applied to each normal vector of the texture.\n"
                    "This value is ignored if normalTexture is not specified",
        min=0.0,
        max=1.0,
        default=MSFS2024_MaterialProperties.NORMALSCALE.default_value(),
        update=MSFS2024_MaterialPropUpdate.update_normal_scale,
        precision=3
    )

    bpy.types.Material.msfs_emissive_scale = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.EMISSIVESCALE.property_name(),
        description="Controls the intensity of the emission.\n"
                    "A value of 1.0 means that the material is fully emissive.\n"
                    "This can be used in addition to an emissive texture and in this case, "
                    "it will control the emission Strenght of this one.",
        min=0.0,
        max=200000.0,
        default=MSFS2024_MaterialProperties.EMISSIVESCALE.default_value(),
        update=MSFS2024_MaterialPropUpdate.update_emissive_scale,
        precision=3
    )

    bpy.types.Material.msfs_alpha_mode = bpy.props.EnumProperty(
        name=MSFS2024_MaterialProperties.ALPHAMODE.property_name(),
        items=(
            (
                "OPAQUE",
                "Opaque",
                "The rendered output is fully opaque and any alpha value is ignored",
            ),
            (
                "MASK",
                "Mask",
                "The rendered output is either fully opaque or fully transparent "
                "depending on the alpha value and the specified alpha cutoff value.\n"
                "This mode is used to simulate geometry such as tree leaves or wire fences",
            ),
            (
                "BLEND",
                "Blend",
                "The rendered output is combined with the background using "
                "the normal painting operation (i.e. the Porter and Duff over operator).\n"
                "This mode is used to simulate geometry such as gauze cloth or animal fur",
            ),
            (
                "DITHER",
                "Dither",
                "The rendered output is blend with dithering dot pattern",
            ),
        ),
        default=MSFS2024_MaterialProperties.ALPHAMODE.default_value(),
        update=MSFS2024_MaterialPropUpdate.update_alpha_mode
    )

    bpy.types.Material.msfs_alpha_cutoff = bpy.props.FloatProperty(
        name=MSFS2024_MaterialProperties.ALPHACUTOFF.property_name(),
        description="When alpha mode is set to MASK the alphaCutoff property specifies the cutoff threshold.\n"
                    "If the alpha value is greater than or equal to the alphaCutoff value "
                    "then it is rendered as fully opaque, otherwise, it is rendered as fully transparent.\n"
                    "Alpha cutoff value is ignored for other modes",
        min=0.0,
        max=1.0,
        default=MSFS2024_MaterialProperties.ALPHACUTOFF.default_value(),
        update=MSFS2024_MaterialPropUpdate.update_alpha_cutoff,
        precision=3
    )

    bpy.types.Material.msfs_double_sided = bpy.props.BoolProperty(
        name=MSFS2024_MaterialProperties.DOUBLESIDED.property_name(),
        description="The double sided property specifies whether the material is double sided.\n"
                    "When this value is false, back-face culling is enabled.\n"
                    "When this value is true, back-face culling is disabled and double sided lighting is enabled.\n"
                    "The back-face must have its normals reversed before the lighting equation is evaluated",
        default=MSFS2024_MaterialProperties.DOUBLESIDED.default_value(),
        update=MSFS2024_MaterialPropUpdate.update_double_sided
    )
    # endregion

    # region Textures
    bpy.types.Material.msfs_base_color_texture = bpy.props.PointerProperty(
        name=MSFS2024_MaterialProperties.BASECOLORTEXTURE.property_name(),
        type=bpy.types.Image,
        update=MSFS2024_MaterialPropUpdate.update_base_color_texture,
    )

    bpy.types.Material.msfs_occlusion_metallic_roughness_texture = bpy.props.PointerProperty(
        name=MSFS2024_MaterialProperties.OMRTEXTURE.property_name(),
        type=bpy.types.Image,
        update=MSFS2024_MaterialPropUpdate.update_comp_texture,
    )

    bpy.types.Material.msfs_normal_texture = bpy.props.PointerProperty(
        name=MSFS2024_MaterialProperties.NORMALTEXTURE.property_name(),
        type=bpy.types.Image,
        update=MSFS2024_MaterialPropUpdate.update_normal_texture,
    )

    bpy.types.Material.msfs_emissive_texture = bpy.props.PointerProperty(
        name=MSFS2024_MaterialProperties.EMISSIVETEXTURE.property_name(),
        type=bpy.types.Image,
        update=MSFS2024_MaterialPropUpdate.update_emissive_texture,
    )
    # endregion

def unregister():
    try:
        del bpy.types.Material.msfs_material_type
        del bpy.types.Material.msfs_base_color_factor
        del bpy.types.Material.msfs_emissive_factor
        del bpy.types.Material.msfs_metallic_factor
        del bpy.types.Material.msfs_roughness_factor
        del bpy.types.Material.msfs_normal_scale
        del bpy.types.Material.msfs_emissive_scale
        del bpy.types.Material.msfs_alpha_mode
        del bpy.types.Material.msfs_alpha_cutoff
        del bpy.types.Material.msfs_double_sided
        del bpy.types.Material.msfs_base_color_texture
        del bpy.types.Material.msfs_occlusion_metallic_roughness_texture
        del bpy.types.Material.msfs_normal_texture
        del bpy.types.Material.msfs_emissive_texture
    except:
        pass
