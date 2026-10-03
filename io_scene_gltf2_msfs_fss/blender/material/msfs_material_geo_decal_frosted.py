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

from ..utils.msfs_material_nodes_utils import (
    add_node,
    get_or_create_group_by_name,
    add_group_input,
    add_group_output,
    link,
    unlink_node_input_by_name,
    get_node_by_name,
    get_nodes_by_class_name,
    MSFS2024_FrameNodes,
    MSFS2024_ShaderNodes,
    MSFS2024_ShaderNodeTypes,
    MSFS2024_GroupNodes,
    MSFS2024_GroupTypes,
    MSFS2024_NodesSockets,
    MSFS2024_DecalNodes,
    MSFS2024_NodeMathOpe,
    MSFS2024_PrincipledBSDFInputs
)
from .msfs_material import MSFS2024_Material


class MSFS2024_Geo_Decal_Frosted(MSFS2024_Material):

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
        MSFS2024_MaterialProperties.UVOFFSETV,
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
        MSFS2024_MaterialProperties.DECALMODE,
        MSFS2024_MaterialProperties.UNDERCLEARCOAT,
        MSFS2024_MaterialProperties.DECALFREEZEFACTOR,

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
    
    def set_default_properties(self, attributes=None):
        super().set_default_properties(attributes=attributes)
        setattr(self.material, MSFS2024_MaterialProperties.ALPHAMODE.attribute_name(), "BLEND")
        setattr(self.material, MSFS2024_MaterialProperties.DECALMODE.attribute_name(), "frosted")

    def force_update_nodes(self):
        super().force_update_nodes()
        self.set_freeze_factor(
            getattr(
                self.material, 
                MSFS2024_MaterialProperties.DECALFREEZEFACTOR.attribute_name()
            )
        )
        
    def custom_shader_tree(self):
        super().default_shader_tree()
        self.decal_frosted_tree()

    def decal_frosted_tree(self):
        decal_frosted_frame = add_node(
            nodes=self.nodes,
            name=MSFS2024_FrameNodes.DECALFROSTEDFRAME.frame_name(),
            type_node=MSFS2024_ShaderNodeTypes.NODEFRAME.value,
            color=MSFS2024_FrameNodes.DECALFROSTEDFRAME.color()
        )

        freeze_factor_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_DecalNodes.DECALFREEZEFACTOR.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEVALUE.value,
            location=(1135.0, -40.0),
            hidden=True,
            frame=decal_frosted_frame
        )

        decal_frosted_group, new_group = get_or_create_group_by_name(
            group_name = MSFS2024_GroupNodes.DECALFROSTEDGROUP.value
        )

        if new_group:
            # region Input/Output Nodes
            input_node = add_node(
                nodes=decal_frosted_group.nodes,
                name=MSFS2024_NodesSockets.GROUPINPUT.value,
                type_node=MSFS2024_GroupTypes.NODEGROUPINPUT.value,
                location=(-1080.0, -160.0),
                hidden=False
            )
            output_node = add_node(
                nodes=decal_frosted_group.nodes,
                name=MSFS2024_NodesSockets.GROUPOUTPUT.value,
                type_node=MSFS2024_GroupTypes.NODEGROUPOUTPUT.value,
                location=(810.0, -165.0),
                hidden=False
            )
            # endregion

            # region Inputs
            # Base color RGB Input
            base_color_rgb_input = add_group_input(
                group=decal_frosted_group, 
                input_name = MSFS2024_ShaderNodes.BASECOLORRGB.value,
                input_type=MSFS2024_GroupTypes.NODESOCKETCOLOR.value
            )
            base_color_rgb_input.default_value = (1.0, 1.0, 1.0, 1.0)

            # Alpha Base color output 
            base_color_a_input = add_group_input(
                group=decal_frosted_group, 
                input_name = MSFS2024_ShaderNodes.BASECOLORA.value,
                input_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
            )
            base_color_a_input.default_value = 1.0

            # Freeze factor
            freeze_factor_input = add_group_input(
                group=decal_frosted_group, 
                input_name = MSFS2024_DecalNodes.DECALFREEZEFACTOR.value,
                input_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
            )
            freeze_factor_input.default_value = 0.0
            # endregion

            # region Outputs
            # Base Color Output
            base_color_output = add_group_output(
                group=decal_frosted_group, 
                output_name=MSFS2024_ShaderNodes.BASECOLORRGB.value,
                output_type=MSFS2024_GroupTypes.NODESOCKETCOLOR.value
            )
            base_color_output.default_value = (1.0, 1.0, 1.0, 1.0)

            # Alpha output 
            alpha_output = add_group_output(
                group=decal_frosted_group, 
                output_name="Alpha",
                output_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
            )
            alpha_output.default_value = 1.0
            alpha_output.min_value = 0.0
            alpha_output.max_value = 1.0
            # endregion

            # region Nodes
            # Vertex color
            vertex_color_node = add_node(
                nodes=decal_frosted_group.nodes,
                name=MSFS2024_NodesSockets.VERTEXCOLOR.value,
                type_node=MSFS2024_ShaderNodeTypes.SHADERNODEVERTEXCOLOR.value,
                location=(-800.0, -215.0)
            )

            # Multiply Alpha node
            multiply_vertex_color_alpha_node = add_node(
                nodes=decal_frosted_group.nodes,
                name="Multiply (Alpha * Vertex Color)",
                type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
                operation=MSFS2024_NodeMathOpe.MULTIPLY.value,
                location=(-620.0, -230.0),
                width=200.0
            )

            # Invert Alpha
            one_minus_alpha_node = add_node(
                nodes=decal_frosted_group.nodes,
                name="1 - alpha",
                type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
                operation=MSFS2024_NodeMathOpe.SUBTRACT.value,
                location=(-370.0, -230.0)
            )
            one_minus_alpha_node.inputs[0].default_value = 1.0

            # Classic Frost (cf)
            cf_frame = add_node(
                nodes=decal_frosted_group.nodes,
                name=MSFS2024_FrameNodes.FROSTFRAME.frame_name(),
                type_node=MSFS2024_ShaderNodeTypes.NODEFRAME.value,
                color = MSFS2024_FrameNodes.FROSTFRAME.color(),
                location=(2800.0, -1340.0)
            )

            # Multiply (x * 0.675)
            multiply_0675_node = add_node(
                nodes=decal_frosted_group.nodes,
                name="Multiply (x * 0.675)",
                type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
                operation=MSFS2024_NodeMathOpe.MULTIPLY.value,
                location=(-510.0, -50.0),
                frame=cf_frame
            )
            multiply_0675_node.inputs[1].default_value = 0.675

            # Subtract (x - 0.02)
            subtract_002_node = add_node(
                nodes=decal_frosted_group.nodes,
                name="Subtract (x - 0.02)",
                type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
                operation=MSFS2024_NodeMathOpe.SUBTRACT.value,
                location=(-310.0, -50.0),
                frame=cf_frame
            )
            subtract_002_node.inputs[1].default_value = 0.02

            # Multiply (x * 0.951)
            multiply_0951_node = add_node(
                nodes=decal_frosted_group.nodes,
                name="Multiply (x * 0.951)",
                type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
                operation=MSFS2024_NodeMathOpe.MULTIPLY.value,
                location=(-510.0, -90.0),
                frame=cf_frame
            )
            multiply_0951_node.inputs[1].default_value = 0.951

            # Subtract (x - 0.01)
            subtract_001_node = add_node(
                nodes=decal_frosted_group.nodes,
                name="Subtract (x - 0.01)",
                type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
                operation=MSFS2024_NodeMathOpe.SUBTRACT.value,
                location=(-310.0, -90.0),
                frame=cf_frame
            )
            subtract_001_node.inputs[1].default_value = 0.01

            # Linearstep(freezeFactor * 0.675 - 0.02, freezeFactor * 0.951 - 0.01, 1.0 - alpha)
            cf_first_pass_node = add_node(
                nodes=decal_frosted_group.nodes,
                name="Frost First Pass",
                type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMAPRANGE.value,
                location=(-100.0, -70.0),
                frame=cf_frame
            )
            cf_first_pass_node.interpolation_type = "LINEAR"

            # Subtract (1 - linearStep(freezeFactor * 0.675 - 0.02, freezeFactor * 0.951 - 0.01, 1.0 - alpha))
            invertcf_first_pass_node = add_node(
                nodes=decal_frosted_group.nodes,
                name="Substract (1 - classicFrostFirstPass)",
                type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
                operation=MSFS2024_NodeMathOpe.SUBTRACT.value,
                location=(70.0, -72.0),
                width=225.0,
                frame=cf_frame
            )
            invertcf_first_pass_node.inputs[0].default_value = 1.0

            # Subtract (classicFrostFirstPass - frostTint)
            cf_first_pass_minusfrost_tint_node = add_node(
                nodes=decal_frosted_group.nodes,
                name="Substract (classicFrostFirstPass - frostTint)",
                type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
                operation=MSFS2024_NodeMathOpe.SUBTRACT.value,
                location=(315.0, -72.0),
                width=250.0,
                frame=cf_frame
            )
            cf_first_pass_minusfrost_tint_node.use_clamp = True

            # Multiply saturate((classicFrostFirsPass - frostedTint) * 0.4)
            cf_second_pass_node = add_node(
                nodes=decal_frosted_group.nodes,
                name="Multiply (x * 0.4)",
                type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
                operation=MSFS2024_NodeMathOpe.MULTIPLY.value,
                location=(590.0, -75.0),
                frame=cf_frame
            )
            cf_second_pass_node.use_clamp = True
            cf_second_pass_node.inputs[1].default_value = 0.4

            # Frost Tint
            frost_tint_frame = add_node(
                nodes=decal_frosted_group.nodes,
                name=MSFS2024_FrameNodes.FROSTTINTFRAME.frame_name(),
                type_node=MSFS2024_ShaderNodeTypes.NODEFRAME.value,
                color = MSFS2024_FrameNodes.FROSTTINTFRAME.color()
            )

            # Multiply (x * 0.455)
            multiply_0455_node = add_node(
                nodes=decal_frosted_group.nodes,
                name="Multiply (x * 0.455)",
                type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
                operation=MSFS2024_NodeMathOpe.MULTIPLY.value,
                location=(-615.0, -300.0),
                frame=frost_tint_frame
            )
            multiply_0455_node.inputs[1].default_value = 0.455

            # Multiply (x * 0.935)
            multiply_0935_node = add_node(
                nodes=decal_frosted_group.nodes,
                name="Multiply (x * 0.935)",
                type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
                operation=MSFS2024_NodeMathOpe.MULTIPLY.value,
                location=(-615.0, -340.0),
                frame=frost_tint_frame
            )
            multiply_0935_node.inputs[1].default_value = 0.935

            # Subtract (x - 0.2)
            subtract_02_node = add_node(
                nodes=decal_frosted_group.nodes,
                name="Subtract (x -0.2)",
                type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
                operation=MSFS2024_NodeMathOpe.SUBTRACT.value,
                location=(-396.0, -300.0),
                frame=frost_tint_frame
            )
            subtract_02_node.inputs[1].default_value = 0.2

            # Subtract (x - 0.15)
            subtract_015_node = add_node(
                nodes=decal_frosted_group.nodes,
                name="Subtract (x -0.15)",
                type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
                operation=MSFS2024_NodeMathOpe.SUBTRACT.value,
                location=(-396.0, -340.0),
                frame=frost_tint_frame
            )
            subtract_015_node.inputs[1].default_value = 0.15

            # Linearstep(freezeFactor * 0.455 - 0.2, freezeFactor * 0.935 - 0.15, 1.0 - alpha)
            frost_tint_first_pass_node = add_node(
                nodes=decal_frosted_group.nodes,
                name="Frost Tint First Pass",
                type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMAPRANGE.value,
                location=(-165.0, -320.0),
                frame=frost_tint_frame
            )
            frost_tint_first_pass_node.interpolation_type = "LINEAR"

            # Frost Tint
            frost_tint_node = add_node(
                nodes=decal_frosted_group.nodes,
                name="Frost Tint Result",
                type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
                operation=MSFS2024_NodeMathOpe.SUBTRACT.value,
                location=(-4.0, -320.0),
                frame=frost_tint_frame
            )
            frost_tint_node.inputs[0].default_value = 1.0

            # Linearstep lerp(float3(1,1,1), float3(0.7, 0.85, 0.9), frostedTint)
            lerp_frost_tint_node = add_node(
                nodes=decal_frosted_group.nodes,
                name="Lerp Frost Tint",
                type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMAPRANGE.value,
                location=(365.0, -140.0)
            )
            lerp_frost_tint_node.interpolation_type = "LINEAR"
            lerp_frost_tint_node.data_type = "FLOAT_VECTOR"
            lerp_frost_tint_node.inputs[7].default_value = (1.0, 1.0, 1.0)
            lerp_frost_tint_node.inputs[8].default_value = (0.7, 0.85, 0.9)

            # Base color RGB * lerpFrostTint
            multiply_rgb_frost_tint_node = add_node(
                nodes=decal_frosted_group.nodes,
                name="Base Color RGB * Frost Tint",
                type_node=MSFS2024_ShaderNodeTypes.SHADERNODEVECTORMATH.value,
                operation=MSFS2024_NodeMathOpe.MULTIPLY.value,
                location=(540.0, -190.0),
                width=200.0
            )
            # endregion

            # region Links
            # Alpha
            link(decal_frosted_group.links, vertex_color_node.outputs[1], multiply_vertex_color_alpha_node.inputs[0])
            link(decal_frosted_group.links, input_node.outputs[1], multiply_vertex_color_alpha_node.inputs[1])
            link(decal_frosted_group.links, multiply_vertex_color_alpha_node.outputs[0], one_minus_alpha_node.inputs[1])

            # Frost Tint
            link(decal_frosted_group.links, input_node.outputs[2], multiply_0455_node.inputs[0])
            link(decal_frosted_group.links, input_node.outputs[2], multiply_0935_node.inputs[0])
            
            link(decal_frosted_group.links, multiply_0455_node.outputs[0], subtract_02_node.inputs[0])
            link(decal_frosted_group.links, multiply_0935_node.outputs[0], subtract_015_node.inputs[0])

            link(decal_frosted_group.links, one_minus_alpha_node.outputs[0], frost_tint_first_pass_node.inputs[0])
            link(decal_frosted_group.links, subtract_02_node.outputs[0], frost_tint_first_pass_node.inputs[1])
            link(decal_frosted_group.links, subtract_015_node.outputs[0], frost_tint_first_pass_node.inputs[2])
            link(decal_frosted_group.links, frost_tint_first_pass_node.outputs[0], frost_tint_node.inputs[1])

            # Classic Frost
            link(decal_frosted_group.links, input_node.outputs[2], multiply_0675_node.inputs[0])
            link(decal_frosted_group.links, input_node.outputs[2], multiply_0951_node.inputs[0])

            link(decal_frosted_group.links, multiply_0675_node.outputs[0], subtract_002_node.inputs[0])
            link(decal_frosted_group.links, multiply_0951_node.outputs[0], subtract_001_node.inputs[0])

            link(decal_frosted_group.links, one_minus_alpha_node.outputs[0], cf_first_pass_node.inputs[0])
            link(decal_frosted_group.links, subtract_002_node.outputs[0], cf_first_pass_node.inputs[1])
            link(decal_frosted_group.links, subtract_001_node.outputs[0], cf_first_pass_node.inputs[2])

            link(decal_frosted_group.links, cf_first_pass_node.outputs[0], invertcf_first_pass_node.inputs[1])
            
            link(decal_frosted_group.links, invertcf_first_pass_node.outputs[0], cf_first_pass_minusfrost_tint_node.inputs[0])
            link(decal_frosted_group.links, frost_tint_node.outputs[0], cf_first_pass_minusfrost_tint_node.inputs[1])

            link(decal_frosted_group.links, cf_first_pass_minusfrost_tint_node.outputs[0], cf_second_pass_node.inputs[0])

            # Base Color RGB
            link(decal_frosted_group.links, frost_tint_node.outputs[0], lerp_frost_tint_node.inputs[6])
            link(decal_frosted_group.links, lerp_frost_tint_node.outputs[1], multiply_rgb_frost_tint_node.inputs[0])
            link(decal_frosted_group.links, input_node.outputs[0], multiply_rgb_frost_tint_node.inputs[1])

            link(decal_frosted_group.links, multiply_rgb_frost_tint_node.outputs[0], output_node.inputs[0])
            link(decal_frosted_group.links, cf_second_pass_node.outputs[0], output_node.inputs[1])
            # endregion

        decal_frosted_group_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_GroupNodes.DECALFROSTEDGROUP.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEGROUP.value,
            location=(1345.0, 120.0),
            width=200.0,
            hidden=False,
            frame=decal_frosted_frame
        )
        decal_frosted_group_node.node_tree = decal_frosted_group

        alpha_group_node = get_node_by_name(self.nodes, MSFS2024_GroupNodes.ALPHAGROUP.value)
        base_color_rgb_group_node = get_node_by_name(self.nodes, MSFS2024_GroupNodes.BASECOLORGROUP.value)
        principled_bsdf_node = get_nodes_by_class_name(self.nodes, MSFS2024_ShaderNodeTypes.SHADENODEBSDFPRINCIPLED.value)[0]

        ## Links
        link(self.links, base_color_rgb_group_node.outputs[0], decal_frosted_group_node.inputs[0])
        link(self.links, decal_frosted_group_node.outputs[0], principled_bsdf_node.inputs[MSFS2024_PrincipledBSDFInputs.BASECOLOR.value])
        link(self.links, alpha_group_node.outputs[0], decal_frosted_group_node.inputs[1])
        link(self.links, decal_frosted_group_node.outputs[1], principled_bsdf_node.inputs[MSFS2024_PrincipledBSDFInputs.ALPHA.value])
        link(self.links, freeze_factor_node.outputs[0], decal_frosted_group_node.inputs[2])

    def _set_alpha_link(self, linked: bool):
        """Override of function defined in msfs_material.py"""
        alpha_group_node = get_node_by_name(
            self.nodes,
            MSFS2024_GroupNodes.DECALFROSTEDGROUP.value
        )
        principled_bsdf_node = get_nodes_by_class_name(
            self.nodes,
            MSFS2024_ShaderNodeTypes.SHADENODEBSDFPRINCIPLED.value
        )[0]

        if linked:
            link(
                self.links,
                alpha_group_node.outputs[1],
                principled_bsdf_node.inputs[MSFS2024_PrincipledBSDFInputs.ALPHA.value],
            )
        else:
            unlink_node_input_by_name(
                self.links,
                principled_bsdf_node,
                MSFS2024_PrincipledBSDFInputs.ALPHA.value,
            )

    def set_freeze_factor(self, value):
        freeze_factor_node = get_node_by_name(self.nodes, MSFS2024_DecalNodes.DECALFREEZEFACTOR.value)
        if freeze_factor_node:
            freeze_factor_node.outputs[0].default_value = value

    @staticmethod
    def draw_panel(layout, material):
        MSFS2024_Geo_Decal_Frosted.draw_parameters_panel(layout=layout, material=material)
        MSFS2024_Geo_Decal_Frosted.draw_textures_panel(layout=layout, material=material)

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

        ## Normal Blend Factor
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.NORMALBLENDFACTOR.attribute_name()
        )

        ## Blast Sys
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.OCCLUSIONBLENDFACTOR.attribute_name(),
            text="Blast Sys"
        )

        ## Melt Sys
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.EMISSIVEBLENDFACTOR.attribute_name(),
            text="Melt Sys"
        )

        ## Normal Override
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.NORMALOVERRIDEFACTOR.attribute_name()
        )

        ## Render Under Clearcoat
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.UNDERCLEARCOAT.attribute_name()
        )
        # endregion

        # region Decal Debug
        box = layout.box()
        box.label(text="Debug")

        ## Freeze Factor
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.DECALFREEZEFACTOR.attribute_name()
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

        ## Melt Pattern (R), Roughness (G), Metallic (B) Texture
        MSFS2024_MaterialUtilsUI.draw_detail_omr_texture_prop(
            layout=box, 
            material=material,
            text="Melt Pattern (R), Roughness (G), Metallic (B)"
        )
        
        ## Detail Normal Texture
        MSFS2024_MaterialUtilsUI.draw_detail_normal_texture_prop(
            layout=box, 
            material=material
        )

        ## Occlusion (UV2)
        MSFS2024_MaterialUtilsUI.draw_occlusion_uv2_texture_prop(
            layout=box, 
            material=material
        )
