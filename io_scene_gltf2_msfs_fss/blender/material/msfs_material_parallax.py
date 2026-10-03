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
    MSFS2024_FrameNodes,
    MSFS2024_ShaderNodes,
    MSFS2024_ShaderNodeTypes,
    MSFS2024_NodeBlendTypes
)

from ..utils.msfs_material_utils import (
    MSFS2024_MaterialProperties,
    MSFS2024_MaterialUtilsUI
)

from .msfs_material import MSFS2024_Material

class MSFS2024_Parallax(MSFS2024_Material):

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

        MSFS2024_MaterialProperties.PARALLAXROOMSIZEX,
        MSFS2024_MaterialProperties.PARALLAXROOMSIZEY,
        MSFS2024_MaterialProperties.PARALLAXROOMSIZEZ,
        MSFS2024_MaterialProperties.PARALLAXROOMCOUNT,
        MSFS2024_MaterialProperties.PARALLAXCORRIDOR,

        MSFS2024_MaterialProperties.FRONTGLASSCOLORTEXTURE,
        MSFS2024_MaterialProperties.OMRTEXTURE,
        MSFS2024_MaterialProperties.FRONTGLASSNORMALTEXTURE,
        MSFS2024_MaterialProperties.EMISSIVEINSIDEWINDOWTEXTURE,
        MSFS2024_MaterialProperties.BEHINDGLASSCOLORTEXTURE,
        MSFS2024_MaterialProperties.OCCLUSIONUV2
    ]

    def __init__(self, material, build_tree=False):
        super().__init__(material=material, build_tree=build_tree)
        if build_tree:
            self.set_default_properties(attributes=self.attributes)
            self.force_update_nodes()

    def set_default_properties(self, attributes=None):
        super().set_default_properties(attributes=attributes)
        setattr(self.material, MSFS2024_MaterialProperties.ALPHAMODE.attribute_name(), "MASK")

    def custom_shader_tree(self):
        super().default_shader_tree()
        self.parallax_shader_tree()

    def parallax_shader_tree(self): ## TODO - Update Shader Node Tree ?? 
        ## Parallax Frame
        parallax_frame = add_node(
            nodes=self.nodes,
            name=MSFS2024_FrameNodes.PARALLAXFRAME.frame_name(),
            type_node=MSFS2024_ShaderNodeTypes.NODEFRAME.value,
            color=(0.5, 0.1, 0.3)
        )

        ## Behind Glass Texture
        # Out[0] : Albedo Detail Mix -> In[2]
        behind_glass_tex_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_ShaderNodes.BEHINDGLASSTEX.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODETEXIMAGE.value,
            location=(1135, 760.0),
            frame=parallax_frame
        )

        ## Albedo Detail Mix
        # In[2] :  Behind Glass Texture -> Out[0]
        albedo_detail_mix_node = add_node(
            nodes=self.nodes,
            name="Albedo Detail Mix",
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMIXRGB.value,
            blend_type = MSFS2024_NodeBlendTypes.MIX.value,
            location=(1435.0, 760.0),
            frame=parallax_frame
        )

        ##Links
        link(self.links, behind_glass_tex_node.outputs[0], albedo_detail_mix_node.inputs[2])

    def set_detail_color_tex(self, image: bpy.types.Image | None):
        behind_glass_tex_node = get_node_by_name(
            nodes=self.nodes, 
            node_name=MSFS2024_ShaderNodes.BEHINDGLASSTEX.value
        )

        if behind_glass_tex_node:
            behind_glass_tex_node.image = image
            self._update_color_links()
        
        ## TODO - check if this is good
        # link(self.links, nodeBaseColorMulRGB.outputs[0], nodeAlbedoDetailMix.inputs[1])
        # link(self.links, nodeAlbedoDetailMix.outputs[0], nodePrincipledBSDF.inputs[MSFS2024_PrincipledBSDFInputs.BASECOLOR.property_name()])

    @staticmethod
    def draw_panel(layout, material):
        MSFS2024_Parallax.draw_parameters_panel(layout=layout, material=material)
        MSFS2024_Parallax.draw_textures_panel(layout=layout, material=material)

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

        #region Parallax parameters
        box = layout.box()
        box.label(text="Parallax Parameters")

        ## Parallax Room Size X 
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.PARALLAXROOMSIZEX.attribute_name()
        )

        ## Parallax Room Size Y
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.PARALLAXROOMSIZEY.attribute_name()
        )

        ## Parallax Room Size Z
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.PARALLAXROOMSIZEZ.attribute_name()
        )

        ## Parallax Room Count
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.PARALLAXROOMCOUNT.attribute_name()
        )

        ## Parallax Corridor
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.PARALLAXCORRIDOR.attribute_name()
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
        ## Front Glass Color Texture
        MSFS2024_MaterialUtilsUI.draw_base_color_texture_prop(
            layout=box, 
            material=material,
            text=MSFS2024_MaterialProperties.FRONTGLASSCOLORTEXTURE.property_name()
        )

        ## Occlusion (R), Roughness (G), Metallic (B) Texture
        MSFS2024_MaterialUtilsUI.draw_omr_texture_prop(
            layout=box, 
            material=material
        )

        ## Front Glass Normal Texture
        MSFS2024_MaterialUtilsUI.draw_normal_texture_prop(
            layout=box, 
            material=material, 
            text=MSFS2024_MaterialProperties.FRONTGLASSNORMALTEXTURE.property_name()
        )

        ## Emissive Inside Window Texture
        MSFS2024_MaterialUtilsUI.draw_emissive_texture_prop(
            layout=box, 
            material=material, 
            text=MSFS2024_MaterialProperties.EMISSIVEINSIDEWINDOWTEXTURE.property_name()
        )

        ## Behind Glass Color (RGB) Alpha (A)
        MSFS2024_MaterialUtilsUI.draw_texture_prop(
            layout=box, 
            material=material, 
            prop=MSFS2024_MaterialProperties.BEHINDGLASSCOLORTEXTURE.attribute_name(),
            text=MSFS2024_MaterialProperties.BEHINDGLASSCOLORTEXTURE.property_name()
        )

        ## Occlusion (UV2)
        MSFS2024_MaterialUtilsUI.draw_occlusion_uv2_texture_prop(
            layout=box, 
            material=material
        )
