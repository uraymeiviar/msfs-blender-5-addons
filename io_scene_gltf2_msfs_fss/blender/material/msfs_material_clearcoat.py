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

from ..utils.msfs_material_nodes_utils import (
    add_node,
    get_node_by_name,
    link,
    unlink_node_input,
    MSFS2024_FrameNodes,
    MSFS2024_ShaderNodes,
    MSFS2024_ShaderNodeTypes,
    MSFS2024_PrincipledBSDFInputs
)

from ..utils.msfs_material_utils import (
    MSFS2024_MaterialProperties,
    MSFS2024_MaterialUtilsUI
)
from .msfs_material import MSFS2024_Material

class MSFS2024_Clearcoat(MSFS2024_Material):

    attributes = [
        MSFS2024_MaterialProperties.BASECOLOR,
        
        MSFS2024_MaterialProperties.EMISSIVECOLOR,
        MSFS2024_MaterialProperties.EMISSIVESCALE,
        MSFS2024_MaterialProperties.EMISSIVE_DAY_MULTIPLIER,
        MSFS2024_MaterialProperties.EMISSIVE_NIGHT_MULTIPLIER,
        
        MSFS2024_MaterialProperties.ALPHAMODE,
        MSFS2024_MaterialProperties.DRAWORDEROFFSET,
        MSFS2024_MaterialProperties.NOCASTSHADOW,
        MSFS2024_MaterialProperties.DOUBLESIDED,
        MSFS2024_MaterialProperties.DAYNIGHTCYCLE,
        MSFS2024_MaterialProperties.DISABLEMOTIONBLUR,
        MSFS2024_MaterialProperties.FLIPBACKFACENORMAL,

        MSFS2024_MaterialProperties.METALLICSCALE,
        MSFS2024_MaterialProperties.ROUGHNESSSCALE,
        MSFS2024_MaterialProperties.OCCLUSIONSTRENGTH,
        MSFS2024_MaterialProperties.NORMALSCALE,
        MSFS2024_MaterialProperties.ALPHACUTOFF,
        MSFS2024_MaterialProperties.DETAILUVSCALE,
        MSFS2024_MaterialProperties.DETAILNORMALSCALE,
        MSFS2024_MaterialProperties.DETAILBLENDTHRESHOLD,
        MSFS2024_MaterialProperties.WEAROVERLAYUVSCALE,
        MSFS2024_MaterialProperties.WEARBLENDSHARPNESS,
        MSFS2024_MaterialProperties.WEARAMOUNT,

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

        MSFS2024_MaterialProperties.RECEIVERAIN,
        MSFS2024_MaterialProperties.RAINDROPTILING,

        MSFS2024_MaterialProperties.CLEARCOATROUGHNESSFACTOR,
        MSFS2024_MaterialProperties.CLEARCOATNORMALFACTOR,
        MSFS2024_MaterialProperties.CLEARCOATCOLORROUGHNESSTILING,
        MSFS2024_MaterialProperties.CLEARCOATNORMALTILING,
        MSFS2024_MaterialProperties.CLEARCOATINVERSEROUGHNESS,
        MSFS2024_MaterialProperties.CLEARCOATBASEROUGHNESS,
        MSFS2024_MaterialProperties.BASE_NORMAL_AFFECT_COAT,

        MSFS2024_MaterialProperties.BASECOLORTEXTURE,
        MSFS2024_MaterialProperties.OMRTEXTURE,
        MSFS2024_MaterialProperties.NORMALTEXTURE,
        MSFS2024_MaterialProperties.EMISSIVETEXTURE,
        MSFS2024_MaterialProperties.DETAILCOLORTEXTURE,
        MSFS2024_MaterialProperties.DETAILOMRTEXTURE,
        MSFS2024_MaterialProperties.DETAILNORMALTEXTURE,
        MSFS2024_MaterialProperties.BLENDMASKTEXTURE,
        MSFS2024_MaterialProperties.OCCLUSIONUV2,
        MSFS2024_MaterialProperties.CLEARCOATCOLORROUGHNESSTEXTURE,
        MSFS2024_MaterialProperties.CLEARCOATNORMALTEXTURE,
        MSFS2024_MaterialProperties.WEARALBEDOMASKTEXTURE,
        MSFS2024_MaterialProperties.WEAROMRINTENSITYTEXTURE
    ]

    #region Private
    def __init__(self, material, build_tree=False):
        super().__init__(material=material, build_tree=build_tree)
        if build_tree:
            self.set_default_properties(attributes=self.attributes)
            self.force_update_nodes()

    def set_default_properties(self, attributes=None):
        super().set_default_properties(attributes=attributes)

    def clearcoat_shader_tree(self) -> None:
        ## Clearcoat Frame
        clearcoat_frame = add_node(
            nodes=self.nodes,
            name=MSFS2024_FrameNodes.CLEARCOATFRAME.frame_name(),
            type_node=MSFS2024_ShaderNodeTypes.NODEFRAME.value,
            color=(0.6, 0.2, 0.1)
        )

        ## Clearcoat Texture
        # Out[0] : ClearcoatSeparate -> In[0]
        clearcoat_tex_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_ShaderNodes.CLEARCOATTEX.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODETEXIMAGE.value,
            location=(100.0, -800.0),
            frame=clearcoat_frame
        )

        ## Clearcoat separate
        # In[0] : ClearcoatTexture -> Out[0]
        # Out[0] : BSDF -> Clearcoat
        # Out[1] : BSDF -> ClearcoatRoughness
        clearcoat_separate_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_ShaderNodes.CLEARCOATSEPARATE.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODESEPARATECOLOR.value,
            location=(300.0, -800.0),
            frame=clearcoat_frame
        )

        ## Clearcoat Normal
        # Out[0] : BSDF -> ClearcoatNormal
        add_node(
            nodes=self.nodes,
            name=MSFS2024_ShaderNodes.CLEARCOATNORMALTEX.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODETEXIMAGE.value,
            location=(300.0, -900.0),
            frame=clearcoat_frame
        )

        link(self.links, clearcoat_tex_node.outputs[0], clearcoat_separate_node.inputs[0])
    #endregion
    
    #region Public
    def custom_shader_tree(self) -> None:
        super().default_shader_tree()
        self.clearcoat_shader_tree()

    def set_clearcoat_tex(self, image: bpy.types.Image | None): 
        ## TODO - Update shader node tree for clearcoat -> Lucas ?
        clearcoat_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.CLEARCOATTEX.value)
        clearcoat_separate_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.CLEARCOATSEPARATE.value)
        principled_bsdf_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.PRINCIPLEDBSDF.value)
        if image:
            clearcoat_node.image = image
            link(
                self.links, 
                clearcoat_separate_node.outputs[0], 
                principled_bsdf_node.inputs[MSFS2024_PrincipledBSDFInputs.CLEARCOAT.value]
            )
            
            link(
                self.links, 
                clearcoat_separate_node.outputs[1], 
                principled_bsdf_node.inputs[MSFS2024_PrincipledBSDFInputs.CLEARCOATROUGHNESS.value]
            )
        else:
            unlink_node_input(
                self.links, 
                principled_bsdf_node, 
                MSFS2024_PrincipledBSDFInputs.CLEARCOAT.value
            )
            
            unlink_node_input(
                self.links, 
                principled_bsdf_node, 
                MSFS2024_PrincipledBSDFInputs.CLEARCOATROUGHNESS.value
            )

    def set_clearcoat_normal_tex(self, image:bpy.types.Image | None): 
        ## TODO - Update shader node tree for clearcoat -> Lucas ?
        clearcoat_normal_node = get_node_by_name(
            nodes=self.nodes, 
            node_name=MSFS2024_ShaderNodes.CLEARCOATNORMALTEX.value
        )
        
        principled_bsdf_node = get_node_by_name(
            nodes=self.nodes, 
            node_name=MSFS2024_ShaderNodes.PRINCIPLEDBSDF.value
        )
        if image:
            clearcoat_normal_node.image = image
            link(
                self.links, 
                clearcoat_normal_node.outputs[0], 
                principled_bsdf_node.inputs[MSFS2024_PrincipledBSDFInputs.CLEARCOATNORMAL.value]
            )
        else:
            unlink_node_input(
                self.links, 
                principled_bsdf_node, 
                MSFS2024_PrincipledBSDFInputs.CLEARCOATNORMAL.value
            )

    #endregion
    
    #region Static
    @staticmethod
    def draw_panel(layout, material):
        MSFS2024_Clearcoat.draw_parameters_panel(layout=layout, material=material)
        MSFS2024_Clearcoat.draw_textures_panel(layout=layout, material=material)

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
        

        ## Alpha mode
        MSFS2024_MaterialUtilsUI.draw_alpha_mode_prop(
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

        ## Day Night Cycle
        MSFS2024_MaterialUtilsUI.draw_day_night_cycle_prop(
            layout=box,
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

        ## Alpha Cutoff
        MSFS2024_MaterialUtilsUI.draw_alpha_cutoff_prop(
            layout = box,
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

        ## Wear Overlay UV Scale
        MSFS2024_MaterialUtilsUI.draw_wear_overlay_uv_scale_prop(
            layout=box,
            material=material
        )

        ## Wear Blend Sharpness
        MSFS2024_MaterialUtilsUI.draw_wear_blend_sharpness_prop(
            layout=box,
            material=material
        )

        ## Wear Amount
        MSFS2024_MaterialUtilsUI.draw_wear_amount_prop(
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
                layout = box,
                material=material
            )
        # endregion

        # region Clearcoat Parameters
        box = layout.box()
        box.label(text="Clearcoat Parameters")

        ## Clearcoat Roughness Factor
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.CLEARCOATROUGHNESSFACTOR.attribute_name()
        )

        ## Clearcoat Normal Factor
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.CLEARCOATNORMALFACTOR.attribute_name()
        )

        ## Clearcoat Color/Roughness Tiling
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.CLEARCOATCOLORROUGHNESSTILING.attribute_name()
        )

        ## Clearcoat Normal Tiling
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.CLEARCOATNORMALTILING.attribute_name()
        )

        ## Clearcoat Inverse Roughness
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.CLEARCOATINVERSEROUGHNESS.attribute_name()
        )
        
        if material.msfs_clearcoat_inverse_roughness:
            ## Clearcoat Base Roughness
            MSFS2024_MaterialUtilsUI.draw_prop(
                layout=box,
                material=material,
                prop=MSFS2024_MaterialProperties.CLEARCOATBASEROUGHNESS.attribute_name()
            )

        # Base Normal Affect Normal Coat
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.BASE_NORMAL_AFFECT_COAT.attribute_name()
        )
        # endregion

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

        if material.msfs_clearcoat_inverse_roughness: 
            ## Occlusion (R), Roughness (G), Metallic (B) Texture
            MSFS2024_MaterialUtilsUI.draw_omr_texture_prop(
                layout=box,
                material=material,
                text="Occlusion (R), Clearcoat Roughness (G), Metallic (B)"
            )
        else:
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

        if not material.msfs_clearcoat_inverse_roughness:
            ## Clearcoat Color (RGB), Clearcoat Roughness (A)
            MSFS2024_MaterialUtilsUI.draw_texture_prop(
                layout=box,
                material=material,
                prop=MSFS2024_MaterialProperties.CLEARCOATCOLORROUGHNESSTEXTURE.attribute_name(),
                text=MSFS2024_MaterialProperties.CLEARCOATCOLORROUGHNESSTEXTURE.property_name()
            )

        ## Clearcoat Normal
        MSFS2024_MaterialUtilsUI.draw_texture_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.CLEARCOATNORMALTEXTURE.attribute_name(),
            text=MSFS2024_MaterialProperties.CLEARCOATNORMALTEXTURE.property_name()
        )
        
        ## Wear Albedo (RGB) Mask (A)
        MSFS2024_MaterialUtilsUI.draw_wear_albedo_mask_texture_prop(
            layout=box, 
            material=material
        )

        ## Wear OMR Intensity (A)
        MSFS2024_MaterialUtilsUI.draw_wear_omr_intensity_texture_prop(
            layout=box, 
            material=material
        )
    #endregion
    