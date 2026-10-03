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


class MSFS2024_Porthole(MSFS2024_Material):

    attributes = [
        MSFS2024_MaterialProperties.BASECOLOR,
        
        MSFS2024_MaterialProperties.EMISSIVECOLOR,
        MSFS2024_MaterialProperties.EMISSIVESCALE,
        MSFS2024_MaterialProperties.EMISSIVE_DAY_MULTIPLIER,
        MSFS2024_MaterialProperties.EMISSIVE_NIGHT_MULTIPLIER,
        
        MSFS2024_MaterialProperties.DRAWORDEROFFSET,
        MSFS2024_MaterialProperties.NOCASTSHADOW,
        MSFS2024_MaterialProperties.DOUBLESIDED,
        MSFS2024_MaterialProperties.DISABLEMOTIONBLUR,
        MSFS2024_MaterialProperties.FLIPBACKFACENORMAL,
        
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
        MSFS2024_MaterialProperties.GROUNDCOLLISIONMATERIAL,

        MSFS2024_MaterialProperties.BASECOLORTEXTURE,
        MSFS2024_MaterialProperties.OMRTEXTURE,
        MSFS2024_MaterialProperties.NORMALTEXTURE,
        MSFS2024_MaterialProperties.EMISSIVETEXTURE,
        MSFS2024_MaterialProperties.DETAILCOLORTEXTURE,
        MSFS2024_MaterialProperties.DETAILOMRTEXTURE,
        MSFS2024_MaterialProperties.DETAILNORMALTEXTURE,
        MSFS2024_MaterialProperties.BLENDMASKTEXTURE,
        MSFS2024_MaterialProperties.OCCLUSIONUV2
    ]

    def __init__(self, material, build_tree=False):
        super().__init__(material=material, build_tree=build_tree)
        if build_tree:
            self.set_default_properties(attributes=self.attributes)
            self.force_update_nodes()

    def custom_shader_tree(self):
        super().default_shader_tree()

    @staticmethod
    def draw_panel(layout, material):
        MSFS2024_Porthole.draw_parameters_panel(layout=layout, material=material)
        MSFS2024_Porthole.draw_textures_panel(layout=layout, material=material)

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
        
        #region Render Parameters
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
                layout = box,
                material=material
            )

        ## Motion Blur
        MSFS2024_MaterialUtilsUI.draw_motion_blur_prop(
            layout=box,
            material=material
        )
        #endregion

        #region General parameters
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
        
        ## Occlusion Strength
        MSFS2024_MaterialUtilsUI.draw_occlusion_strength_prop(
            layout=box,
            material=material
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

        #endregion

        #region UV options
        MSFS2024_MaterialUtilsUI.draw_uv_panel(
            layout=layout,
            material=material
        )
        #endregion

        #region Gameplay Parameters
        MSFS2024_MaterialUtilsUI.draw_gameplay_panel(
            layout=layout,
            material=material
        )
        #endregion

    @staticmethod
    def draw_textures_panel(layout, material):
        box = layout.box()
        box.label(text="Textures")
        MSFS2024_Material.draw_base_texture_set_operator(
            box, 
            material
        )
        
        ## Base Color Texture
        MSFS2024_MaterialUtilsUI.draw_base_color_texture_prop(
            layout=box,
            material=material
        )

        ## Occlusion (R), Roughness (G), Metallic (B) Texture
        MSFS2024_MaterialUtilsUI.draw_omr_texture_prop(
            layout=box,
            material=material
        )

        ## Normal Texture
        MSFS2024_MaterialUtilsUI.draw_normal_texture_prop(
            layout=box, 
            material=material
        )

        ## Emissive Texture
        MSFS2024_MaterialUtilsUI.draw_emissive_texture_prop(
            layout=box,
            material=material
        )

        ## Detail Color Texture
        MSFS2024_MaterialUtilsUI.draw_detail_color_texture_prop(
            layout=box, 
            material=material
        )

        ## Detail Occlusion (R), Roughness (G), Metallic (B) Texture
        MSFS2024_MaterialUtilsUI.draw_detail_omr_texture_prop(
            layout=box, 
            material=material
        )
        
        ## Detail Normal Texture
        MSFS2024_MaterialUtilsUI.draw_detail_normal_texture_prop(
            layout=box, 
            material=material
        )

        ## Blend Mask Texture
        MSFS2024_MaterialUtilsUI.draw_blend_mask_texture_prop(
            layout=box, 
            material=material
        )

        ## Occlusion (UV2)
        MSFS2024_MaterialUtilsUI.draw_occlusion_uv2_texture_prop(
            layout=box, 
            material=material
        )
