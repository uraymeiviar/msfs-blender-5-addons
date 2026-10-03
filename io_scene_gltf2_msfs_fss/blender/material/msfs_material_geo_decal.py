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
    get_nodes_by_class_name,
    get_node_by_name,
    add_group_input,
    add_group_output,
    link,
    unlink_node_input_by_name,
    MSFS2024_ShaderNodes,
    MSFS2024_ShaderNodeTypes,
    MSFS2024_GroupNodes,
    MSFS2024_GroupTypes,
    MSFS2024_PrincipledBSDFInputs,
    MSFS2024_NodesSockets,
    MSFS2024_NodeMathOpe
)

from .msfs_material import MSFS2024_Material

class MSFS2024_Geo_Decal(MSFS2024_Material):

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
        MSFS2024_MaterialProperties.DECALMODE,
        MSFS2024_MaterialProperties.UNDERCLEARCOAT,
        MSFS2024_MaterialProperties.SCENERY_CHANNEL,
        MSFS2024_MaterialProperties.TERRAIN_CHANNEL,
        MSFS2024_MaterialProperties.SIMOBJECT_CHANNEL,

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
        setattr(self.material, MSFS2024_MaterialProperties.DECALMODE.attribute_name(), "default")

    def custom_shader_tree(self):
        super().default_shader_tree()
        self.decal_tree()

    def decal_tree(self):
        decal_group, new_group = get_or_create_group_by_name(
            group_name=MSFS2024_GroupNodes.DECALGROUP.value
        )

        if new_group:
            # region Input/Output Nodes
            input_node = add_node(
                nodes=decal_group.nodes,
                name=MSFS2024_NodesSockets.GROUPINPUT.value,
                type_node=MSFS2024_GroupTypes.NODEGROUPINPUT.value,
                location=(65.0, -10.0),
                hidden=False
            )
            output_node = add_node(
                nodes=decal_group.nodes,
                name=MSFS2024_NodesSockets.GROUPOUTPUT.value,
                type_node=MSFS2024_GroupTypes.NODEGROUPOUTPUT.value,
                location=(520.0, -10.0),
                hidden=False
            )
            # endregion

            # region Inputs
            # Alpha Base color output 
            base_color_a_input = add_group_input(
                group=decal_group,
                input_name=MSFS2024_ShaderNodes.BASECOLORA.value,
                input_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
            )
            base_color_a_input.default_value = 1.0
            # endregion

            # region Outputs
            # Alpha output 
            alpha_output = add_group_output(
                group=decal_group,
                output_name="Alpha",
                output_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
            )
            alpha_output.default_value = 1.0
            alpha_output.min_value = 0.0
            alpha_output.max_value = 1.0
            # endregion

            # region Nodes
            ## Vertex color
            vertex_color_node = add_node(
                nodes=decal_group.nodes,
                name=MSFS2024_NodesSockets.VERTEXCOLOR.value,
                type_node=MSFS2024_ShaderNodeTypes.SHADERNODEVERTEXCOLOR.value,
                location=(70.0, 35.0)
            )

            ## Multiply Alpha node
            multiply_vertex_color_alpha_node = add_node(
                nodes=decal_group.nodes,
                type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
                operation=MSFS2024_NodeMathOpe.MULTIPLY.value,
                location=(300.0, 40.0)
            )
            # endregion

            # region Links
            link(decal_group.links, input_node.outputs[0], multiply_vertex_color_alpha_node.inputs[0])
            link(decal_group.links, vertex_color_node.outputs[1], multiply_vertex_color_alpha_node.inputs[1])
            link(decal_group.links, multiply_vertex_color_alpha_node.outputs[0], output_node.inputs[0])
            # endregion

        decal_group_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_GroupNodes.DECALGROUP.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEGROUP.value,
            location=(1230.0, 300.0),
            width=150.0,
            hidden=False
        )
        decal_group_node.node_tree = decal_group

        alpha_group_node = get_node_by_name(self.nodes, MSFS2024_GroupNodes.ALPHAGROUP.value)
        principled_bsdf_node = get_nodes_by_class_name(
            self.nodes,
            MSFS2024_ShaderNodeTypes.SHADENODEBSDFPRINCIPLED.value
        )[0]

        ## Links
        link(
            self.links,
            alpha_group_node.outputs[0],
            decal_group_node.inputs[0]
        )

        link(
            self.links,
            decal_group_node.outputs[0],
            principled_bsdf_node.inputs[MSFS2024_PrincipledBSDFInputs.ALPHA.value]
        )

    def _set_alpha_link(self, linked: bool):
        """Override of function defined in msfs_material.py"""
        alpha_group_node = get_node_by_name(
            self.nodes, MSFS2024_GroupNodes.DECALGROUP.value
        )
        principled_bsdf_node = get_nodes_by_class_name(
            self.nodes, MSFS2024_ShaderNodeTypes.SHADENODEBSDFPRINCIPLED.value
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

    @staticmethod
    def draw_panel(layout, material):
        MSFS2024_Geo_Decal.draw_parameters_panel(layout=layout, material=material)
        MSFS2024_Geo_Decal.draw_textures_panel(layout=layout, material=material)

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
        box.label(text="Decal Parameters")

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

        ## Render Under Clearcoat
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=box,
            material=material,
            prop=MSFS2024_MaterialProperties.UNDERCLEARCOAT.attribute_name()
        )

        # region Decal Channel Mask
        MSFS2024_MaterialUtilsUI.draw_decal_channel_mask_props(
            layout=layout,
            material=material
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
