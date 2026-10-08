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
    add_node, link, unlink_node_input,
    get_node_by_name,
    MSFS2024_FrameNodes,
    MSFS2024_AnisotropicNodes,
    MSFS2024_ShaderNodes,
    MSFS2024_ShaderNodeTypes,
    MSFS2024_PrincipledBSDFInputs
)

from ..utils.msfs_material_utils import (
    MSFS2024_MaterialProperties,
    MSFS2024_MaterialUtilsUI
)

from .msfs_material import MSFS2024_Material

class MSFS2024_Anisotropic(MSFS2024_Material):

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
        MSFS2024_MaterialProperties.FLIPBACKFACENORMAL,
        MSFS2024_MaterialProperties.DISABLEMOTIONBLUR,

        MSFS2024_MaterialProperties.METALLICSCALE,
        MSFS2024_MaterialProperties.ROUGHNESSSCALE,
        MSFS2024_MaterialProperties.OCCLUSIONSTRENGTH,
        MSFS2024_MaterialProperties.NORMALSCALE,
        MSFS2024_MaterialProperties.ALPHACUTOFF,
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
        MSFS2024_MaterialProperties.OCCANISOROUGHXMETALICTEXTURE,
        MSFS2024_MaterialProperties.NORMALTEXTURE,
        MSFS2024_MaterialProperties.EMISSIVETEXTURE,
        MSFS2024_MaterialProperties.DETAILCOLORTEXTURE,
        MSFS2024_MaterialProperties.DETAILOMRTEXTURE,
        MSFS2024_MaterialProperties.DETAILNORMALTEXTURE,
        MSFS2024_MaterialProperties.BLENDMASKTEXTURE,
        MSFS2024_MaterialProperties.OCCLUSIONUV2,
        MSFS2024_MaterialProperties.ANISODIRECTIONROUGHNESSTEXTURE
    ]

    def __init__(self, material, build_tree=False):
        super().__init__(material=material, build_tree=build_tree)
        if build_tree:
            self.set_default_properties(attributes=self.attributes)
            self.force_update_nodes()

    def custom_shader_tree(self):
        super().default_shader_tree()
        self.anisotropic_shader_tree()

    def anisotropic_shader_tree(self):
        '''
            Method to add shader nodes when anisotropi material is set
        '''
        # TODO - Update shader tree for anisotropic -> Lucas ?
        anisotropic_frame = add_node(
            nodes=self.nodes,
            name=MSFS2024_FrameNodes.ANISOTROPICFRAME.frame_name(),
            type_node=MSFS2024_ShaderNodeTypes.NODEFRAME.value,
            color=(0.35, 0.6, 0.1)
        )
        ## Anisotropic Texture
        # Out[0] : Separate Anisotrpic -> In[0]
        anisotropic_tex_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_AnisotropicNodes.ANISOTROPICTEX.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODETEXIMAGE.value,
            location=(100.0, -700.0),
            width=200.0,
            frame=anisotropic_frame)
        
        ## Separate Anisotropic
        # In[0] : Anisotropic Texture -> Out[0]
        separate_anisotropic_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_AnisotropicNodes.SEPARATEANISOTROPIC.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODESEPARATECOLOR.value,
            location=(400.0, -700.0),
            width=200.0,
            frame=anisotropic_frame)
        # Links
        link(self.links, anisotropic_tex_node.outputs[0], separate_anisotropic_node.inputs[0])

    @staticmethod
    def draw_panel(layout, material):
        '''
            Draw material panel
        '''
        MSFS2024_Anisotropic.draw_parameters_panel(layout=layout, material=material)
        MSFS2024_Anisotropic.draw_textures_panel(layout=layout, material=material)

    @staticmethod
    def draw_parameters_panel(layout, material):
        '''
            Draw material input parameters
        '''
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

        #region Render parameters
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

        ## Occlusion (R), Aniso Roughness X (G), Metallic (B) Texture
        MSFS2024_MaterialUtilsUI.draw_omr_texture_prop(
            layout=box,
            material=material,
            text=MSFS2024_MaterialProperties.OCCANISOROUGHXMETALICTEXTURE.property_name()
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

        ## Anisotropic Direction Roughness Y Texture
        MSFS2024_MaterialUtilsUI.draw_texture_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.ANISODIRECTIONROUGHNESSTEXTURE.attribute_name(),
            text=MSFS2024_MaterialProperties.ANISODIRECTIONROUGHNESSTEXTURE.property_name()
        )
    