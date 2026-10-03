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

from ..utils.msfs_material_utils import (
    MSFS2024_MaterialProperties,
    MSFS2024_MaterialUtilsUI
)

from ..utils.msfs_material_nodes_utils import (
    add_node,
    get_or_create_group_by_name,
    add_group_input,
    add_group_output,
    link,
    unlink_node_input_by_name,
    unlink_node_output,
    get_node_by_name,
    get_nodes_by_class_name,
    MSFS2024_FrameNodes,
    MSFS2024_ShaderNodes,
    MSFS2024_ShaderNodeTypes,
    MSFS2024_DecalNodes,
    MSFS2024_GroupNodes,
    MSFS2024_GroupTypes,
    MSFS2024_NodesSockets,
    MSFS2024_NodeMathOpe,
    MSFS2024_MapRangeType,
    MSFS2024_PrincipledBSDFInputs
)

from .msfs_material import MSFS2024_Material

class MSFS2024_Geo_Decal_BlendMasked(MSFS2024_Material):
    
    attributes = [
        MSFS2024_MaterialProperties.BASECOLOR,
        
        MSFS2024_MaterialProperties.EMISSIVECOLOR,
        MSFS2024_MaterialProperties.EMISSIVESCALE,
        MSFS2024_MaterialProperties.EMISSIVE_DAY_MULTIPLIER,
        MSFS2024_MaterialProperties.EMISSIVE_NIGHT_MULTIPLIER,
        
        MSFS2024_MaterialProperties.DRAWORDEROFFSET,
        MSFS2024_MaterialProperties.DOUBLESIDED,
        MSFS2024_MaterialProperties.DAYNIGHTCYCLE,
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

        MSFS2024_MaterialProperties.BASECOLORBLENDFACTOR,
        MSFS2024_MaterialProperties.ROUGHNESSBLENDFACTOR,
        MSFS2024_MaterialProperties.METALLICBLENDFACTOR,
        MSFS2024_MaterialProperties.OCCLUSIONBLENDFACTOR,
        MSFS2024_MaterialProperties.NORMALBLENDFACTOR,
        MSFS2024_MaterialProperties.EMISSIVEBLENDFACTOR,
        MSFS2024_MaterialProperties.NORMALOVERRIDEFACTOR,
        MSFS2024_MaterialProperties.DECALBLENDSHARPNESS,
        MSFS2024_MaterialProperties.DECALMODE,
        MSFS2024_MaterialProperties.UNDERCLEARCOAT,
        
        MSFS2024_MaterialProperties.DECALBLENDMASKEDTHRESHOLD,

        MSFS2024_MaterialProperties.BASECOLORTEXTURE,
        MSFS2024_MaterialProperties.OMRTEXTURE,
        MSFS2024_MaterialProperties.NORMALTEXTURE,
        MSFS2024_MaterialProperties.EMISSIVETEXTURE,
        MSFS2024_MaterialProperties.DETAILCOLORTEXTURE,
        MSFS2024_MaterialProperties.DETAILOMRTEXTURE,
        MSFS2024_MaterialProperties.DETAILNORMALTEXTURE,
        MSFS2024_MaterialProperties.DECALBLENDMASKTEXTURE,
        MSFS2024_MaterialProperties.OCCLUSIONUV2
    ]
    
    def __init__(self, material, build_tree=False):
        super().__init__(material=material, build_tree=build_tree)
        if build_tree:
            self.set_default_properties(attributes=self.attributes)
            self.force_update_nodes()
    
    def set_default_properties(self, attributes=None):
        super().set_default_properties(attributes=attributes)
        setattr(self.material, MSFS2024_MaterialProperties.ALPHAMODE.attribute_name(), "BLEND")
        setattr(self.material, MSFS2024_MaterialProperties.DECALMODE.attribute_name(), "blendMasked")
        
    def force_update_nodes(self):
        super().force_update_nodes()
        self.set_decal_blend_mask_tex(getattr(self.material, MSFS2024_MaterialProperties.DECALBLENDMASKTEXTURE.attribute_name()))
        self.set_blendmask_threshold(getattr(self.material, MSFS2024_MaterialProperties.DECALBLENDMASKEDTHRESHOLD.attribute_name()))
        self.set_blend_mask_sharpness(getattr(self.material, MSFS2024_MaterialProperties.DECALBLENDSHARPNESS.attribute_name()))

    def custom_shader_tree(self):
        super().default_shader_tree()
        self.decal_blendmasked_tree()

    def _set_alpha_link(self, linked: bool):
        """Override of function defined in msfs_material.py"""
        alpha_group_node = get_node_by_name(
            self.nodes,
            MSFS2024_GroupNodes.DECALBLENDMASKEDGROUP.value
        )
        principled_bsdf_node = get_nodes_by_class_name(
            self.nodes,
            MSFS2024_ShaderNodeTypes.SHADENODEBSDFPRINCIPLED.value
        )[0]

        if linked:
            link(
                self.links,
                alpha_group_node.outputs[0],
                principled_bsdf_node.inputs[MSFS2024_PrincipledBSDFInputs.ALPHA.value],
            )
        else:
            unlink_node_input_by_name(
                self.links,
                principled_bsdf_node,
                MSFS2024_PrincipledBSDFInputs.ALPHA.value,
            )

    def decal_blendmasked_tree(self):
        ## Decal Frame
        decal_frame = add_node(
            nodes=self.nodes,
            name=MSFS2024_FrameNodes.DECALBLENDMASKEDFRAME.frame_name(),
            type_node=MSFS2024_ShaderNodeTypes.NODEFRAME.value,
            color=(0.5, 0.1, 0.0)
        )

        # Blend Mask
        decal_blendmask_tex_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_DecalNodes.DECALBLENDMASKTEX.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODETEXIMAGE.value,
            location=(1133.0, 214.0),
            width=300.0,
            frame=decal_frame
        )
        decal_blendmask_tex_node.interpolation = "Linear"

        # Blend Mask Threshold
        blend_mask_threshold_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_DecalNodes.DECALBLENDMASKTHRESHOLD.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEVALUE.value,
            location=(1133.0, 160.0),
            width=300.0,
            frame=decal_frame
        )
        blend_mask_threshold_node.outputs[0].default_value = 1.0

        # Blend Mask Threshold
        blend_sharpness_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_DecalNodes.DECALBLENDMASKSHARPNESS.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEVALUE.value,
            location=(1133.0, 114.0),
            width=300.0,
            frame=decal_frame
        )
        blend_sharpness_node.outputs[0].default_value = 1.0
        
        decal_blendmasked_group, new_group = get_or_create_group_by_name(
            group_name = MSFS2024_GroupNodes.DECALBLENDMASKEDGROUP.value
        )

        if new_group:
            input_node = add_node(
                nodes=decal_blendmasked_group.nodes,
                name=MSFS2024_NodesSockets.GROUPINPUT.value,
                type_node=MSFS2024_GroupTypes.NODEGROUPINPUT.value,
                location=(-480.0, 40.0),
                hidden = False
            )
            
            output_node = add_node(
                nodes=decal_blendmasked_group.nodes,
                name=MSFS2024_NodesSockets.GROUPOUTPUT.value,
                type_node=MSFS2024_GroupTypes.NODEGROUPOUTPUT.value,
                location=(1000.0, 30.0),
                hidden = False
            )

            # region Inputs
            base_color_a_input = add_group_input(
                group = decal_blendmasked_group, 
                input_name = MSFS2024_ShaderNodes.BASECOLORA.value,
                input_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
            )
            base_color_a_input.default_value = 1.0

            blend_masked_input = add_group_input(
                group = decal_blendmasked_group, 
                input_name = MSFS2024_ShaderNodes.BLENDMASKTEX.value,
                input_type=MSFS2024_GroupTypes.NODESOCKETCOLOR.value
            )
            blend_masked_input.default_value = (1.0, 1.0, 1.0, 1.0)

            blend_mask_threshold_input = add_group_input(
                group = decal_blendmasked_group, 
                input_name = MSFS2024_DecalNodes.DECALBLENDMASKTHRESHOLD.value,
                input_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
            )
            blend_mask_threshold_input.default_value = 1.0

            blend_mask_sharpness_input = add_group_input(
                group = decal_blendmasked_group, 
                input_name = MSFS2024_DecalNodes.DECALBLENDMASKSHARPNESS.value,
                input_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
            )
            blend_mask_sharpness_input.default_value = 1.0
            # endregion

            # region Outputs
            # Alpha output 
            alpha_output = add_group_output(
                group = decal_blendmasked_group, 
                output_name="Alpha",
                output_type = MSFS2024_GroupTypes.NODESOCKETFLOAT.value
            )
            alpha_output.default_value = 1.0
            alpha_output.min_value = 0.0
            alpha_output.max_value = 1.0
            # endregion

            # region Nodes
            # Vertex color
            vertex_color_node = add_node(
                nodes=decal_blendmasked_group.nodes,
                name=MSFS2024_NodesSockets.VERTEXCOLOR.value,
                type_node=MSFS2024_ShaderNodeTypes.SHADERNODEVERTEXCOLOR.value,
                location=(20.0, -7.0)
            )

            one_minus_threshold_node = add_node(
                name="Substract (1 - x)",
                nodes=decal_blendmasked_group.nodes,
                type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
                operation=MSFS2024_NodeMathOpe.SUBTRACT.value,
                location=(28.0, -40.0)
            )

            multiply_vertex_color_alpha_node = add_node(
                nodes=decal_blendmasked_group.nodes,
                type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
                operation=MSFS2024_NodeMathOpe.MULTIPLY.value,
                location=(230.0, -25.0)
            )

            one_minus_sharpness_node = add_node(
                nodes=decal_blendmasked_group.nodes,
                type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
                operation=MSFS2024_NodeMathOpe.SUBTRACT.value,
                location=(24.0, -161.0)
            )
            one_minus_sharpness_node.inputs[0].default_value = 1.0

            separate_blend_mask_tex_node = add_node(
                nodes=decal_blendmasked_group.nodes,
                type_node=MSFS2024_ShaderNodeTypes.SHADERNODESEPARATECOLOR.value,
                location=(20.0, -120.0)
            )

            blend_mask_minus_sharpness_node = add_node(
                nodes=decal_blendmasked_group.nodes,
                type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
                operation=MSFS2024_NodeMathOpe.SUBTRACT.value,
                location=(340.0, -100.0)
            )
            blend_mask_minus_sharpness_node.use_clamp = True

            blend_mask_plus_sharpness_node = add_node(
                nodes=decal_blendmasked_group.nodes,
                type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
                operation=MSFS2024_NodeMathOpe.ADD.value,
                location=(340.0, -163.0)
            )
            blend_mask_plus_sharpness_node.use_clamp = True

            linear_step_map_range_node = add_node(
                nodes=decal_blendmasked_group.nodes,
                type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMAPRANGE.value,
                operation=MSFS2024_MapRangeType.LINEAR.value,
                location=(560.0, -80.0)
            )

            multiply_alpha_linear_step_node = add_node(
                nodes=decal_blendmasked_group.nodes,
                type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
                operation=MSFS2024_NodeMathOpe.MULTIPLY.value,
                location=(782.0, 5.0)
            )
            # endregion

            # region Links
            link(decal_blendmasked_group.links, input_node.outputs[0], multiply_alpha_linear_step_node.inputs[0])

            link(decal_blendmasked_group.links, input_node.outputs[1], separate_blend_mask_tex_node.inputs[0])
            link(decal_blendmasked_group.links, separate_blend_mask_tex_node.outputs[0], blend_mask_minus_sharpness_node.inputs[0])
            link(decal_blendmasked_group.links, separate_blend_mask_tex_node.outputs[0], blend_mask_plus_sharpness_node.inputs[0])

            link(decal_blendmasked_group.links, vertex_color_node.outputs[1], multiply_vertex_color_alpha_node.inputs[0])
            link(decal_blendmasked_group.links, input_node.outputs[2], one_minus_threshold_node.inputs[1])
            link(decal_blendmasked_group.links, one_minus_threshold_node.outputs[0], multiply_vertex_color_alpha_node.inputs[1])
            
            link(decal_blendmasked_group.links, input_node.outputs[3], one_minus_sharpness_node.inputs[1])

            link(decal_blendmasked_group.links, one_minus_sharpness_node.outputs[0], blend_mask_plus_sharpness_node.inputs[1])
            link(decal_blendmasked_group.links, one_minus_sharpness_node.outputs[0], blend_mask_minus_sharpness_node.inputs[1])

            link(decal_blendmasked_group.links, multiply_vertex_color_alpha_node.outputs[0], linear_step_map_range_node.inputs[0])
            link(decal_blendmasked_group.links, blend_mask_minus_sharpness_node.outputs[0], linear_step_map_range_node.inputs[1])
            link(decal_blendmasked_group.links, blend_mask_plus_sharpness_node.outputs[0], linear_step_map_range_node.inputs[2])

            link(decal_blendmasked_group.links, linear_step_map_range_node.outputs[0], multiply_alpha_linear_step_node.inputs[1])
            link(decal_blendmasked_group.links, multiply_alpha_linear_step_node.outputs[0], output_node.inputs[0])
            # endregion

        decal_blend_masked_group_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_GroupNodes.DECALBLENDMASKEDGROUP.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEGROUP.value,
            location=(1513.0, 329.0),
            width=150.0,
            hidden=False,
            frame=decal_frame
        )
        decal_blend_masked_group_node.node_tree = decal_blendmasked_group

        alpha_group_node = get_node_by_name(self.nodes, MSFS2024_GroupNodes.ALPHAGROUP.value)
        principled_bsdf_node = get_nodes_by_class_name(self.nodes, MSFS2024_ShaderNodeTypes.SHADENODEBSDFPRINCIPLED.value)[0]

        ## Links
        link(self.links, alpha_group_node.outputs[0], decal_blend_masked_group_node.inputs[0])
        link(self.links, decal_blendmask_tex_node.outputs[0], decal_blend_masked_group_node.inputs[1])
        link(self.links, blend_mask_threshold_node.outputs[0], decal_blend_masked_group_node.inputs[2])
        link(self.links, blend_sharpness_node.outputs[0], decal_blend_masked_group_node.inputs[3])
        link(self.links, decal_blend_masked_group_node.outputs[0], principled_bsdf_node.inputs[MSFS2024_PrincipledBSDFInputs.ALPHA.value])

    def set_decal_blend_mask_tex(self, image: bpy.types.Image | None):
        decal_blend_mask_tex = get_node_by_name(
            nodes=self.nodes,
            node_name=MSFS2024_DecalNodes.DECALBLENDMASKTEX.value
        )
        
        if not decal_blend_mask_tex:
            return
        decal_blend_mask_tex.image = image
        # Update shader tree
        if image is None:
            unlink_node_output(self.links, decal_blend_mask_tex, 0)
            return
        
        decal_blend_mask_group_node = get_node_by_name(
            nodes=self.nodes, 
            node_name=MSFS2024_GroupNodes.DECALBLENDMASKEDGROUP.value
        )
        
        if decal_blend_mask_group_node:
            link(self.links, decal_blend_mask_tex.outputs[0], decal_blend_mask_group_node.inputs[1])

        uv_group_node = get_node_by_name(
            nodes=self.nodes,
            node_name=MSFS2024_GroupNodes.UVGROUP.value
        )
        
        if uv_group_node:
            link(self.links, uv_group_node.outputs[0], decal_blend_mask_tex.inputs[0])

    def set_blendmask_threshold(self, value):
        blend_threshold_value_node = get_node_by_name(
            nodes=self.nodes, 
            node_name=MSFS2024_DecalNodes.DECALBLENDMASKTHRESHOLD.value
        )
        
        if blend_threshold_value_node:
            blend_threshold_value_node.outputs[0].default_value = value

    def set_blend_mask_sharpness(self, value):
        blend_mask_sharpness_value_node = get_node_by_name(
            nodes=self.nodes, 
            node_name=MSFS2024_DecalNodes.DECALBLENDMASKSHARPNESS.value
        )
        
        if blend_mask_sharpness_value_node:
            # We need to add a small value to avoid division by zero
            blend_mask_sharpness_value_node.outputs[0].default_value = value + 0.000001 

    @staticmethod
    def draw_panel(layout, material):
        MSFS2024_Geo_Decal_BlendMasked.draw_parameters_panel(layout=layout, material=material)
        MSFS2024_Geo_Decal_BlendMasked.draw_textures_panel(layout=layout, material=material)

    @staticmethod
    def draw_parameters_panel(layout, material):
        # region Colors
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
        
        # endregion

        # region Render parameters
        box = layout.box()
        box.label(text="Render Parameters")

        ## Draw Order Offset
        MSFS2024_MaterialUtilsUI.draw_order_offset_prop(
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

        # region Decal Blend Parameters
        box = layout.box()
        box.label(text="Decal Blend Factors")

        ## Base Color Blend Factor
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.BASECOLORBLENDFACTOR.attribute_name()
        )

        ## Roughness Blend Factor
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.ROUGHNESSBLENDFACTOR.attribute_name()
        )

        ## Metallic Blend Factor
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.METALLICBLENDFACTOR.attribute_name()
        )

        ## Occlusion Blend Factor
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.OCCLUSIONBLENDFACTOR.attribute_name()
        )

        ## Normal Blend Factor
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.NORMALBLENDFACTOR.attribute_name()
        )

        ## Emissive
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.EMISSIVEBLENDFACTOR.attribute_name()
        )

        ## Normal Override
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.NORMALOVERRIDEFACTOR.attribute_name()
        )

        ## Blend Sharpness
        blend_mask_texture = getattr(
            material,
            MSFS2024_MaterialProperties.DECALBLENDMASKTEXTURE.attribute_name()
        )
        
        if blend_mask_texture is not None:
            MSFS2024_MaterialUtilsUI.draw_prop(
                layout=box,
                material=material,
                prop=MSFS2024_MaterialProperties.DECALBLENDSHARPNESS.attribute_name()
            )

        ## Render Under Clearcoat
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.UNDERCLEARCOAT.attribute_name()
        )
        # endregion
        
        # region Debug Parameters
        if blend_mask_texture is not None:
            box = layout.box()
            box.label(text="Decal Blend Mask Debug")

            ## Blend Mask Threshold
            MSFS2024_MaterialUtilsUI.draw_prop(
                layout=box,
                material=material,
                prop=MSFS2024_MaterialProperties.DECALBLENDMASKEDTHRESHOLD.attribute_name()
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

        ## Decal Blend Mask Texture
        MSFS2024_MaterialUtilsUI.draw_decal_blend_mask_texture_prop(
            layout=box, 
            material=material
        )

        ## Occlusion (UV2)
        MSFS2024_MaterialUtilsUI.draw_occlusion_uv2_texture_prop(
            layout=box, 
            material=material
        )
