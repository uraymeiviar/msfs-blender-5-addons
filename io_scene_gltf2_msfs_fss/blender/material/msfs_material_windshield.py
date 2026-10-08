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
from ..utils.msfs_material_utils import (
    MSFS2024_MaterialProperties,
    MSFS2024_MaterialUtilsUI
)

from .msfs_material import MSFS2024_Material

class MSFS2024_Windshield(MSFS2024_Material):

    attributes = [
        MSFS2024_MaterialProperties.BASECOLOR,
        
        MSFS2024_MaterialProperties.EMISSIVECOLOR,
        MSFS2024_MaterialProperties.EMISSIVESCALE,
        MSFS2024_MaterialProperties.EMISSIVE_DAY_MULTIPLIER,
        MSFS2024_MaterialProperties.EMISSIVE_NIGHT_MULTIPLIER,

        MSFS2024_MaterialProperties.DRAWORDEROFFSET,
        MSFS2024_MaterialProperties.NOCASTSHADOW,
        MSFS2024_MaterialProperties.DOUBLESIDED,
        MSFS2024_MaterialProperties.FLIPBACKFACENORMAL,
        MSFS2024_MaterialProperties.DISABLEMOTIONBLUR,

        MSFS2024_MaterialProperties.METALLICSCALE,
        MSFS2024_MaterialProperties.ROUGHNESSSCALE,
        MSFS2024_MaterialProperties.OCCLUSIONSTRENGTH,
        MSFS2024_MaterialProperties.NORMALSCALE,
        MSFS2024_MaterialProperties.DETAILUVSCALE,
        MSFS2024_MaterialProperties.DETAILNORMALSCALE,
        MSFS2024_MaterialProperties.DETAILBLENDTHRESHOLD,

        MSFS2024_MaterialProperties.UVOFFSETU,
        MSFS2024_MaterialProperties.UVOFFSETV,
        MSFS2024_MaterialProperties.UVTILINGU,
        MSFS2024_MaterialProperties.UVTILINGV,
        MSFS2024_MaterialProperties.UVROTATION,
        MSFS2024_MaterialProperties.CLAMPUVX,
        MSFS2024_MaterialProperties.CLAMPUVY,

        MSFS2024_MaterialProperties.COLLISIONMATERIAL,
        MSFS2024_MaterialProperties.ROADCOLLISIONMATERIAL,

        MSFS2024_MaterialProperties.RECEIVERAIN,
        MSFS2024_MaterialProperties.RAINDROPTILING,
        MSFS2024_MaterialProperties.RAINONBACKFACE,

        MSFS2024_MaterialProperties.WINDSHIELDWIPERLINES,
        MSFS2024_MaterialProperties.WINDSHIELDWIPERLINESTILING,
        MSFS2024_MaterialProperties.WINDSHIELDWIPERLINESSTRENGTH,

        MSFS2024_MaterialProperties.WINDSHIELDWIPER1STATE,

        MSFS2024_MaterialProperties.WINDSHIELDDETAILROUGHNESS1,
        MSFS2024_MaterialProperties.WINDSHIELDDETAILROUGHNESS2,
        MSFS2024_MaterialProperties.WINDSHIELDDETAILOPACITY1,
        MSFS2024_MaterialProperties.WINDSHIELDDETAILOPACITY2,
        MSFS2024_MaterialProperties.WINDSHIELDMICROSCRATCHTILING,
        MSFS2024_MaterialProperties.WINDSHIELDMICROSCRATCHSTRENGTH,
        MSFS2024_MaterialProperties.WINDSHIELDDETAILNORMALREFRACTSCALE,

        MSFS2024_MaterialProperties.USEIRIDESCENT,
        MSFS2024_MaterialProperties.IRIDESCENTMINTHICKNESS,
        MSFS2024_MaterialProperties.IRIDESCENTMAXTHICKNESS,
        MSFS2024_MaterialProperties.IRIDESCENTBRIGHTNESS,

        MSFS2024_MaterialProperties.BASECOLORTEXTURE,
        MSFS2024_MaterialProperties.WINDSHIELDREFLECTIONROUGHNESSMETALLICTEXTURE,
        MSFS2024_MaterialProperties.NORMALTEXTURE,
        MSFS2024_MaterialProperties.WINDSHIELDSECONDARYDETAILSTEXTURE,
        MSFS2024_MaterialProperties.DETAILS1ICINGMASKDETAILS2TEXTURE,
        MSFS2024_MaterialProperties.DETAILSWINDSHIELDREFLECTIONROUGHNESSMETALLICTEXTURE,
        MSFS2024_MaterialProperties.ICINGNORMALTEXTURE,
        MSFS2024_MaterialProperties.REFLECTIONMASKTEXTURE,
        MSFS2024_MaterialProperties.WINDSHIELDWIPERMASKTEXTURE,
        MSFS2024_MaterialProperties.WINDSHILEDDETAILNORMALTEXTURE,
        MSFS2024_MaterialProperties.WINDSHIELDSCRACHESNORMALTEXTURE,
        MSFS2024_MaterialProperties.IRIDESCENTTHICKNESSTEXTURE,
        MSFS2024_MaterialProperties.WINDSHIELDINSECTSALBEDOTEXTURE,
        MSFS2024_MaterialProperties.WINDSHIELDINSECTSMASKTEXTURE,

        MSFS2024_MaterialProperties.WINDSHIELDCUBEMAPREFLECTIONMASKING,
        MSFS2024_MaterialProperties.WINDSHIELDSSRATTENUATION,
    ]

    def __init__(self, material, build_tree=False):
        super().__init__(material=material, build_tree=build_tree)
        if build_tree:
            self.set_default_properties(attributes=self.attributes)
            self.force_update_nodes()

    def set_default_properties(self, attributes=None):
        super().set_default_properties(attributes=attributes)
        setattr(self.material, MSFS2024_MaterialProperties.ALPHAMODE.attribute_name(), "BLEND")

    def custom_shader_tree(self):
        super().default_shader_tree()

    def set_wiper_mask_tex(self, texture):
        ## TODO - Add new windshield shader 
        return NotImplementedError

    @staticmethod
    def draw_panel(layout, material):
        MSFS2024_Windshield.draw_parameters_panel(layout=layout, material=material)
        MSFS2024_Windshield.draw_textures_panel(layout=layout, material=material)

    @staticmethod
    def draw_parameters_panel(layout, material):
        ## Base Color
        MSFS2024_MaterialUtilsUI.draw_base_color_prop(
            layout=layout,
            material=material
        )

        ## Emissive
        MSFS2024_MaterialUtilsUI.draw_emissive_props(
            layout=layout,
            material=material
        )
        
        # region Render Parameters
        box = layout.box()
        box.label(text="Render Parameters")

        ## Draw Order Offset
        MSFS2024_MaterialUtilsUI.draw_order_offset_prop(
            layout=box,
            material=material
        )

        ## No Cast Shadow
        MSFS2024_MaterialUtilsUI.draw_no_cast_shadow_prop(
            layout=box,
            material=material
        )

        ## Double Sided
        MSFS2024_MaterialUtilsUI.draw_double_sided_prop(
            layout=box,
            material=material
        )

        ## Flip Back Face Normal
        if material.msfs_double_sided:
            MSFS2024_MaterialUtilsUI.draw_flip_back_face_normal_prop(
                layout=box,
                material=material
            )

        ## Motion Blur
        MSFS2024_MaterialUtilsUI.draw_motion_blur_prop(
            layout=box,
            material=material
        )
        # endregion

        # region General parameters
        box = layout.box()
        box.label(text="General Parameters")

        ## Metallic Scale
        MSFS2024_MaterialUtilsUI.draw_metallic_scale_prop(
            layout=box,
            material=material
        )

        ## Roughness Scale
        MSFS2024_MaterialUtilsUI.draw_roughness_scale_prop(
            layout=box,
            material=material
        )

        ## Reflection Mask Strength
        MSFS2024_MaterialUtilsUI.draw_occlusion_strength_prop(
            layout=box,
            material=material,
            text=MSFS2024_MaterialProperties.WINDSHIELDREFLECTIONMASKSTRENGTH.property_name()
        )

        ## Normal Scale
        MSFS2024_MaterialUtilsUI.draw_normal_scale_prop(
            layout=box,
            material=material
        )

        ## Detail UV Scale
        MSFS2024_MaterialUtilsUI.draw_detail_uv_scale_prop(
            layout=box,
            material=material
        )

        ## Detail Normal Scale
        MSFS2024_MaterialUtilsUI.draw_detail_normal_scale_prop(
            layout=box,
            material=material
        )

        ## Detail Blend Threshold
        MSFS2024_MaterialUtilsUI.draw_blend_threshold_prop(
            layout=box,
            material=material
        )
        # endregion

        # region UV options
        MSFS2024_MaterialUtilsUI.draw_uv_panel(
            layout=layout,
            material=material
        )
        # endregion

        # region Gameplay Parameters
        MSFS2024_MaterialUtilsUI.draw_gameplay_panel(
            layout=layout,
            material=material
        )
        # endregion

        # region Rain Options
        box = layout.box()
        box.label(text="Rain Parameters")

        ## Receive Rain
        MSFS2024_MaterialUtilsUI.draw_receive_rain_prop(
            layout=box,
            material=material
        )

        if getattr(material, MSFS2024_MaterialProperties.RECEIVERAIN.attribute_name()):
            ## Rain Drop Tiling
            MSFS2024_MaterialUtilsUI.draw_rain_drop_tiling_prop(
                layout=box,
                material=material
            )

            MSFS2024_MaterialUtilsUI.draw_rain_on_backface_prop(
                layout=box,
                material=material
            )

            # region Windshield Wipers Parameters
            box = layout.box()
            box.label(text="Windshield Wipers Parameters")

            ## Windshield Lines
            MSFS2024_MaterialUtilsUI.draw_prop(
                layout=box,
                material=material,
                prop=MSFS2024_MaterialProperties.WINDSHIELDWIPERLINES.attribute_name(),
                text=MSFS2024_MaterialProperties.WINDSHIELDWIPERLINES.property_name()
            )

            if material.msfs_windshield_wiper_lines:
                ## Windshield Lines Tiling
                MSFS2024_MaterialUtilsUI.draw_prop(
                    layout=box,
                    material=material,
                    prop=MSFS2024_MaterialProperties.WINDSHIELDWIPERLINESTILING.attribute_name(),
                    text=MSFS2024_MaterialProperties.WINDSHIELDWIPERLINESTILING.property_name()
                )

                ## Windshield Lines Strength
                MSFS2024_MaterialUtilsUI.draw_prop(
                    layout=box,
                    material=material,
                    prop=MSFS2024_MaterialProperties.WINDSHIELDWIPERLINESSTRENGTH.attribute_name(),
                    text=MSFS2024_MaterialProperties.WINDSHIELDWIPERLINESSTRENGTH.property_name()
                )

            ## Wiper Animation
            box = layout.box()
            box.label(text="Wiper Animation Parameters")

            MSFS2024_MaterialUtilsUI.draw_prop(
                layout=box,
                material=material,
                prop=MSFS2024_MaterialProperties.WINDSHIELDWIPER1STATE.attribute_name(),
                text=MSFS2024_MaterialProperties.WINDSHIELDWIPER1STATE.property_name()
            )
            # endregion

        # endregion

        # region Windshield Parameters
        box = layout.box()
        box.label(text="Windshield Parameters")

        ## Windshield Detail 1 Rough
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.WINDSHIELDDETAILROUGHNESS1.attribute_name(),
            text=MSFS2024_MaterialProperties.WINDSHIELDDETAILROUGHNESS1.property_name()
        )

        ## Windshield Detail 2 Rough
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.WINDSHIELDDETAILROUGHNESS2.attribute_name(),
            text=MSFS2024_MaterialProperties.WINDSHIELDDETAILROUGHNESS2.property_name()
        )

        ## Windshield Detail 1 Opacity
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.WINDSHIELDDETAILOPACITY1.attribute_name(),
            text=MSFS2024_MaterialProperties.WINDSHIELDDETAILOPACITY1.property_name()
        )

        ## Windshield Detail 2 Opacity
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.WINDSHIELDDETAILOPACITY2.attribute_name(),
            text=MSFS2024_MaterialProperties.WINDSHIELDDETAILOPACITY2.property_name()
        )

        ## Windshield Micro Scratches Tiling
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.WINDSHIELDMICROSCRATCHTILING.attribute_name(),
            text=MSFS2024_MaterialProperties.WINDSHIELDMICROSCRATCHTILING.property_name()
        )

        ## Windshield Micro Scratches Strength
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.WINDSHIELDMICROSCRATCHSTRENGTH.attribute_name(),
            text=MSFS2024_MaterialProperties.WINDSHIELDMICROSCRATCHSTRENGTH.property_name()
        )

        ## Windshield Detail Normal Refract Scale
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.WINDSHIELDDETAILNORMALREFRACTSCALE.attribute_name(),
            text=MSFS2024_MaterialProperties.WINDSHIELDDETAILNORMALREFRACTSCALE.property_name()
        )
        # endregion
        
        # region Windshield Reflection Parameters
        box = layout.box()
        box.label(text="Windshield Reflection Parameters")

        ## Windhsiled Cubemap Reflection Masking
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.WINDSHIELDCUBEMAPREFLECTIONMASKING.attribute_name(),
            text=MSFS2024_MaterialProperties.WINDSHIELDCUBEMAPREFLECTIONMASKING.property_name()
        )

        ## Windshield Screen Space Reflection Attenuation
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.WINDSHIELDSSRATTENUATION.attribute_name(),
            text=MSFS2024_MaterialProperties.WINDSHIELDSSRATTENUATION.property_name()
        )
        # endregion

        # region Iridescent Parameters
        box = layout.box()
        box.label(text="Iridescent Parameters")

        ## Use Iridescent
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.USEIRIDESCENT.attribute_name(),
            text=MSFS2024_MaterialProperties.USEIRIDESCENT.property_name()
        )

        if material.msfs_use_iridescent:
            ## Iridescent Min Thickness
            MSFS2024_MaterialUtilsUI.draw_prop(
                layout=box,
                material=material,
                prop=MSFS2024_MaterialProperties.IRIDESCENTMINTHICKNESS.attribute_name(),
                text=MSFS2024_MaterialProperties.IRIDESCENTMINTHICKNESS.property_name()
            )

            ## Iridescent Max Thickness
            MSFS2024_MaterialUtilsUI.draw_prop(
                layout=box,
                material=material,
                prop=MSFS2024_MaterialProperties.IRIDESCENTMAXTHICKNESS.attribute_name(),
                text=MSFS2024_MaterialProperties.IRIDESCENTMAXTHICKNESS.property_name()
            )

            ## Iridescent Brightness
            MSFS2024_MaterialUtilsUI.draw_prop(
                layout=box,
                material=material,
                prop=MSFS2024_MaterialProperties.IRIDESCENTBRIGHTNESS.attribute_name(),
                text=MSFS2024_MaterialProperties.IRIDESCENTBRIGHTNESS.property_name()
            )
        # endregion

    @staticmethod
    def draw_textures_panel(layout, material):
        box = layout.box()
        box.label(text="Textures")
        ope = MSFS2024_Material.draw_base_texture_set_operator(
            box,
            material
        )
        ope.set_emissive = False

        ## Base Color Texture
        MSFS2024_MaterialUtilsUI.draw_base_color_texture_prop(
            layout=box,
            material=material
        )

        ## Reflection (R), Roughness (G), Metallic (B) Texture
        MSFS2024_MaterialUtilsUI.draw_omr_texture_prop(
            layout=box,
            material=material,
            text=MSFS2024_MaterialProperties.WINDSHIELDREFLECTIONROUGHNESSMETALLICTEXTURE.property_name()
        )

        ## Normal Texture
        MSFS2024_MaterialUtilsUI.draw_normal_texture_prop(
            layout=box,
            material=material,
            text=MSFS2024_MaterialProperties.NORMALTEXTURE.property_name()
        )

        ## Secondary Details
        MSFS2024_MaterialUtilsUI.draw_emissive_texture_prop(
            layout=box,
            material=material,
            text=MSFS2024_MaterialProperties.WINDSHIELDSECONDARYDETAILSTEXTURE.property_name()
        )

        ## Details 1 (R), Icing Mask (G), Details 2 (B)
        MSFS2024_MaterialUtilsUI.draw_detail_color_texture_prop(
            layout=box,
            material=material,
            text=MSFS2024_MaterialProperties.DETAILS1ICINGMASKDETAILS2TEXTURE.property_name()
        )

        ## Details Reflection (R) Roughness (G) Metallic (B)
        MSFS2024_MaterialUtilsUI.draw_detail_omr_texture_prop(
            layout=box,
            material=material,
            text=MSFS2024_MaterialProperties.DETAILSWINDSHIELDREFLECTIONROUGHNESSMETALLICTEXTURE.property_name()
        )

        ## Icing Normal
        MSFS2024_MaterialUtilsUI.draw_detail_normal_texture_prop(
            layout=box,
            material=material,
            text=MSFS2024_MaterialProperties.ICINGNORMALTEXTURE.property_name()
        )

        ## Reflection Mask (UV2)
        MSFS2024_MaterialUtilsUI.draw_occlusion_uv2_texture_prop(
            layout=box,
            material=material,
            text=MSFS2024_MaterialProperties.REFLECTIONMASKTEXTURE.property_name()
        )

        ## Wiper Mask (RGBA)
        MSFS2024_MaterialUtilsUI.draw_texture_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.WINDSHIELDWIPERMASKTEXTURE.attribute_name(),
            text=MSFS2024_MaterialProperties.WINDSHIELDWIPERMASKTEXTURE.property_name()
        )

        ## Detail Normal (use Detail UV Tiling)
        MSFS2024_MaterialUtilsUI.draw_texture_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.WINDSHILEDDETAILNORMALTEXTURE.attribute_name(),
            text=MSFS2024_MaterialProperties.WINDSHILEDDETAILNORMALTEXTURE.property_name()
        )

        ## Scratches Normal
        MSFS2024_MaterialUtilsUI.draw_texture_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.WINDSHIELDSCRACHESNORMALTEXTURE.attribute_name(),
            text=MSFS2024_MaterialProperties.WINDSHIELDSCRACHESNORMALTEXTURE.property_name()
        )

        if material.msfs_use_iridescent:
            ## Iridescent Thickness (R)
            MSFS2024_MaterialUtilsUI.draw_texture_prop(
                layout=box,
                material=material,
                prop=MSFS2024_MaterialProperties.IRIDESCENTTHICKNESSTEXTURE.attribute_name(),
                text=MSFS2024_MaterialProperties.IRIDESCENTTHICKNESSTEXTURE.property_name()
            )

        ## Insects Albedo
        MSFS2024_MaterialUtilsUI.draw_texture_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.WINDSHIELDINSECTSALBEDOTEXTURE.attribute_name(),
            text=MSFS2024_MaterialProperties.WINDSHIELDINSECTSALBEDOTEXTURE.property_name()
        )

        ## Insects Mask
        MSFS2024_MaterialUtilsUI.draw_texture_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.WINDSHIELDINSECTSMASKTEXTURE.attribute_name(),
            text=MSFS2024_MaterialProperties.WINDSHIELDINSECTSMASKTEXTURE.property_name()
        )
