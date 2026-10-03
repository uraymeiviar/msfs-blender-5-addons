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
import math

import bpy

from ..utils.msfs_material_nodes_utils import (
    add_node,
    add_group_input,
    add_group_output,
    get_or_create_group_by_name,
    get_node_by_name,
    get_nodes_by_class_name,
    link,
    unlink_node_input,
    unlink_node_input_by_name,
    unlink_node_output,
    set_input_value,
    MSFS2024_ShaderNodes,
    MSFS2024_ShaderNodeTypes,
    MSFS2024_GroupNodes,
    MSFS2024_GroupTypes,
    MSFS2024_FrameNodes,
    MSFS2024_PrincipledBSDFInputs,
    MSFS2024_NodeMathOpe,
    MSFS2024_NodesSockets,
    MSFS2024_NodeBlendTypes,
    MSFS2024_NodeDataTypes,
    MSFS2024_MapRangeType
)

from ..utils import msfs_material_nodes_library
from ..utils.msfs_material_utils import MSFS2024_MaterialProperties

from ..utils.msfs_constants import DefaultUV

from .msfs_material_ope import MSFS2024_OT_SetPbrTextureSet

class MSFS2024_Material:
    bl_idname = "MSFS2024_ShaderNodeTree"
    bl_label = "MSFS2024 Shader Node Tree"

    # region Private
    def __init__(
        self,
        material,
        build_tree=False,
        revert_to_pbr=False
    ):
        self.material = material
        self.node_tree = self.material.node_tree
        if self.node_tree is not None:
            self.nodes=self.node_tree.nodes
            self.links = self.node_tree.links

            if build_tree:
                self._build_tree()

            if revert_to_pbr:
                self.set_default_properties()
                self._revert_to_pbr_shader_tree()

        self._set_default_material_settings()

    def _set_default_material_settings(self):
        if hasattr(self.material,"use_transparent_shadow"):
            self.material.use_transparent_shadow = True
        if hasattr(self.material,"use_backface_culling_shadow"):
            self.material.use_backface_culling_shadow = True

    def _build_tree(self):
        self._clean_node_tree()
        self._create_tree()

    def _clean_node_tree(self):
        nodes=self.node_tree.nodes
        for _, node in enumerate(nodes):
            # print("Deleting: %s | %s" % (node.name, node.type))
            nodes.remove(node)

    def _create_tree(self):
        output_material_node = add_node(
            nodes=self.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEOUTPUTMATERIAL.value,
            location=(2000.0, 640.0),
            hidden=False
        )

        principled_bsdf = add_node(
            nodes=self.nodes,
            name=MSFS2024_ShaderNodes.PRINCIPLEDBSDF.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADENODEBSDFPRINCIPLED.value,
            location=(1800.0, 610.0),
            hidden=False
        )

        link(self.links, principled_bsdf.outputs[0], output_material_node.inputs[0])

        self.custom_shader_tree()

    def _create_pbr_tree(self):
        output_material_node = add_node(
            nodes=self.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEOUTPUTMATERIAL.value,
            location=(1200.0, 50.0),
            hidden=False
        )
        principled_bsdf = add_node(
            nodes=self.nodes,
            name=MSFS2024_ShaderNodes.PRINCIPLEDBSDF.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADENODEBSDFPRINCIPLED.value,
            location=(1000.0, 25.0),
            hidden=False
        )
        link(self.links, principled_bsdf.outputs[0], output_material_node.inputs[0])

    def _revert_to_pbr_shader_tree(self):
        self._clean_node_tree()
        self._create_pbr_tree()

    ####################################################
    # region Update Nodes Methods
    def _update_blendmask_links(self):
        blendmask_tex_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.BLENDMASKTEX.value)
        blend_mask_group_node = get_node_by_name(self.nodes, MSFS2024_GroupNodes.BLENDMASKGROUP.value)

        ## Set Group Inputs/Outputs Links to default
        unlink_node_input(self.links, blend_mask_group_node, 0)
        unlink_node_input(self.links, blend_mask_group_node, 1)
        set_input_value(blend_mask_group_node.inputs[2], 0) # Disable blend mask input

        if blendmask_tex_node.image:

            link(self.links, blendmask_tex_node.outputs[0], blend_mask_group_node.inputs[1])
            link(self.links, blendmask_tex_node.outputs[1], blend_mask_group_node.inputs[0])
            set_input_value(blend_mask_group_node.inputs[2], 1) # Enable blend mask input

    def _update_blendmask_mode(self):
        blend_mask_tex_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.BLENDMASKTEX.value)

        blend_mask_group_node = get_node_by_name(self.nodes, MSFS2024_GroupNodes.BLENDMASKGROUP.value)
        base_color_group_node = get_node_by_name(self.nodes, MSFS2024_GroupNodes.BASECOLORGROUP.value)
        omr_group_node = get_node_by_name(self.nodes, MSFS2024_GroupNodes.OMRGROUP.value)
        normal_group_node = get_node_by_name(self.nodes, MSFS2024_GroupNodes.NORMALGROUP.value)

        # Blend mode
        if  blend_mask_tex_node.image: 
            set_input_value(blend_mask_group_node.inputs[4], 1)
            set_input_value(base_color_group_node.inputs[6], 1)
            set_input_value(omr_group_node.inputs[6], 1)
            set_input_value(normal_group_node.inputs[6], 1)

        # Detail mode
        else:
            set_input_value(blend_mask_group_node.inputs[4], 0)
            set_input_value(base_color_group_node.inputs[6], 0)
            set_input_value(omr_group_node.inputs[6], 0)
            set_input_value(normal_group_node.inputs[6], 0)

    def _update_color_links(self):
        base_color_tex_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.BASECOLORTEX.value)
        detail_color_tex_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.DETAILCOLORTEX.value)
        base_color_group_node = get_node_by_name(self.nodes, MSFS2024_GroupNodes.BASECOLORGROUP.value)
        alpha_group_node = get_node_by_name(self.nodes, MSFS2024_GroupNodes.ALPHAGROUP.value)

        ## TODO - Maybe get the blend_color_map_node From the group and change the blend_type

        ## Set Group Inputs/Outputs Links to default
        # Unlink Base Color Group textures and alpha detail by default
        unlink_node_input(self.links, base_color_group_node, 1)
        unlink_node_input(self.links, base_color_group_node, 2)
        unlink_node_input(self.links, base_color_group_node, 3)

        set_input_value(base_color_group_node.inputs[4], 0)
        # Unlink Alpha Group textures and alpha detail by default
        unlink_node_input(self.links, alpha_group_node, 1)
        unlink_node_input(self.links, alpha_group_node, 2)

        if base_color_tex_node.image :
            link(self.links, base_color_tex_node.outputs[0], base_color_group_node.inputs[1])
            link(self.links, base_color_tex_node.outputs[1], alpha_group_node.inputs[1])

        if detail_color_tex_node.image :
            link(self.links, detail_color_tex_node.outputs[0], base_color_group_node.inputs[2])
            link(self.links, detail_color_tex_node.outputs[1], base_color_group_node.inputs[3])
            link(self.links, detail_color_tex_node.outputs[1], alpha_group_node.inputs[2])
            set_input_value(base_color_group_node.inputs[4], 1)

        self._update_ao_links() #AO Links depends on base_color_tex_node assignment

    def _set_alpha_link(self, linked: bool):
        """
        Connect or disconnect the alpha texture only when necessary.
        Keeping an unnecessary alpha texture connection can negatively impact performance.

        Args:
            linked: state of alpha link
        """
        alpha_group_node = get_node_by_name(
            self.nodes, MSFS2024_GroupNodes.ALPHAGROUP.value
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

    def _update_omr_links(self):
        omr_tex_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.COMPTEX.value)
        detail_omr_tex_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.DETAILCOMPTEX.value)
        omr_group_node = get_node_by_name(self.nodes, MSFS2024_GroupNodes.OMRGROUP.value)

        ## Set Group Inputs/Outputs Links to default
        unlink_node_input(self.links, omr_group_node, 2)
        unlink_node_input(self.links, omr_group_node, 3)
        set_input_value(omr_group_node.inputs[4], 0) #disable detail

        if omr_tex_node.image :
            link(self.links, omr_tex_node.outputs[0], omr_group_node.inputs[2])

        if detail_omr_tex_node.image:
            link(self.links, detail_omr_tex_node.outputs[0], omr_group_node.inputs[3])
            set_input_value(omr_group_node.inputs[4], 1) #enable detail

    def _update_ao_links(self):
        base_color_tex_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.BASECOLORTEX.value)

        apply_ao_group_node = get_node_by_name(self.nodes, MSFS2024_GroupNodes.APPLYAOGROUP.value)

        omr_group_node = get_node_by_name(self.nodes, MSFS2024_GroupNodes.OMRGROUP.value)
        omr_tex_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.COMPTEX.value)
        detail_omr_tex_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.DETAILCOMPTEX.value)

        occlusion_uv2_tex_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.OCCLUSIONUV2TEX.value)

        unlink_node_input(self.links, apply_ao_group_node, 1)
        unlink_node_input(self.links, apply_ao_group_node, 2)

        # Only use AO maps when there is a base_color_tex in order to prevent gltf export texture issue
        # Error happens when material has an omr_tex or detail_omr_tex without a base_color_tex
        # GLTF Khronos exporter mistakenly assigns omr texture or detail omr texture to base color texture slot...
        if occlusion_uv2_tex_node.image and base_color_tex_node.image:
            link(self.links, occlusion_uv2_tex_node.outputs[0], apply_ao_group_node.inputs[2])

        if (omr_tex_node.image or detail_omr_tex_node.image) and base_color_tex_node.image:
            link(self.links, omr_group_node.outputs[2], apply_ao_group_node.inputs[1])

    def _update_emissive_links(self):
        emissive_tex_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.EMISSIVETEX.value)
        emissive_group_node = get_node_by_name(self.nodes, MSFS2024_GroupNodes.EMISSIVEGROUP.value)

        ## Set Group Inputs/Outputs Links to default
        unlink_node_input(self.links, emissive_group_node, 2)

        if emissive_tex_node.image:
            link(self.links, emissive_tex_node.outputs[0], emissive_group_node.inputs[2])

    def _update_normal_links(self):
        normal_scale_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.NORMALSCALE.value)
        detail_normal_scale_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.DETAILNORMALSCALE.value)
        normal_tex_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.NORMALTEX.value)
        detail_normal_tex_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.DETAILNORMALTEX.value)
        normal_group_node = get_node_by_name(self.nodes, MSFS2024_GroupNodes.NORMALGROUP.value)
        principled_bsdf_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.PRINCIPLEDBSDF.value)

        ## Set Group Inputs/Outputs Links to default
        unlink_node_input(self.links, normal_group_node, 0)
        unlink_node_input(self.links, normal_group_node, 1)
        unlink_node_input(self.links, normal_group_node, 2)
        unlink_node_input(self.links, normal_group_node, 3)

        unlink_node_output(self.links, normal_group_node, 0)
        set_input_value(normal_group_node.inputs[4], 0) # Disable detail normal

        if normal_tex_node.image:
            link(self.links, normal_scale_node.outputs[0], normal_group_node.inputs[0])
            link(self.links, normal_tex_node.outputs[0], normal_group_node.inputs[1])

        if detail_normal_tex_node.image:
            link(self.links, detail_normal_scale_node.outputs[0], normal_group_node.inputs[2])
            link(self.links, detail_normal_tex_node.outputs[0], normal_group_node.inputs[3])
            set_input_value(normal_group_node.inputs[4], 1) # Enable detail normal

        if normal_tex_node.image or detail_normal_tex_node.image:            
            link(self.links, normal_group_node.outputs[0], principled_bsdf_node.inputs[MSFS2024_PrincipledBSDFInputs.NORMAL.value])

    def _update_alpha_mode(self):
        alpha_mode = getattr(
            self.material,
            MSFS2024_MaterialProperties.ALPHAMODE.attribute_name()
        )
        alpha_group_node = get_node_by_name(self.nodes, MSFS2024_GroupNodes.ALPHAGROUP.value)
        if not alpha_group_node:
            return
        if alpha_mode == "MASK":
            set_input_value(alpha_group_node.inputs[4], 1)
        else:
            set_input_value(alpha_group_node.inputs[4], 0)
    # endregion

    # region Blend Methods
    ####################################################
    def switch_to_opaque_render(self):
        self.material.blend_method = "OPAQUE"
        if bpy.app.version >= (4, 2, 0):
            self.material.surface_render_method = "DITHERED"
            self.material.use_transparency_overlap = False

    def switch_to_masked_render(self):
        self.material.blend_method = "CLIP"
        if bpy.app.version >= (4, 2, 0):
            self.material.surface_render_method = "DITHERED"

    def switch_to_blend_render(self):
        self.material.blend_method = "BLEND"
        if bpy.app.version >= (4, 2, 0):
            self.material.surface_render_method = "BLENDED"
            self.material.use_transparency_overlap = True

    def _make_opaque(self):
        self.switch_to_opaque_render()
        self._set_alpha_link(False)

    def _make_masked(self):
        self.switch_to_masked_render()
        self._set_alpha_link(True)

    def _make_alpha_blend(self):
        self.switch_to_blend_render()
        self._set_alpha_link(True)

    def _make_dither(self):
        if bpy.app.version < (4, 2, 0):
            # Since Eevee doesn't provide a dither mode, we'll just use alpha-blend instead.
            self.material.blend_method = "BLEND"
        else:
            self.material.blend_method = "HASHED"
            self.material.surface_render_method = "DITHERED"
            self.material.use_transparency_overlap = True
        self._set_alpha_link(True)

    # endregion

    # endregion

    # region Public
    def custom_shader_tree(self):
        raise NotImplementedError()

    def default_shader_tree(self):
        principled_bsdf_node = get_nodes_by_class_name(
            self.nodes,
            MSFS2024_ShaderNodeTypes.SHADENODEBSDFPRINCIPLED.value
        )[0]

        # region Inputs
        ## Mask Inputs frame
        mask_inputs_frame = add_node(
            nodes=self.nodes,
            name=MSFS2024_FrameNodes.MASKFRAME.frame_name(),
            type_node=MSFS2024_ShaderNodeTypes.NODEFRAME.value,
            color=MSFS2024_FrameNodes.MASKFRAME.color()
        )

        blendmask_tex_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_ShaderNodes.BLENDMASKTEX.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODETEXIMAGE.value,
            location=(-200, 1050),
            width=300.0,
            frame=mask_inputs_frame
        )

        blendmask_threshold_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_ShaderNodes.DETAILBLENDMASKTHRESHOLD.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEVALUE.value,
            location=(-200.0, 1000), 
            frame=mask_inputs_frame
        )

        ## Base Color Inputs frame
        base_color_inputs_frame = add_node(
            nodes=self.nodes,
            name=MSFS2024_FrameNodes.BASECOLORINPUTSFRAME.frame_name(),
            type_node=MSFS2024_ShaderNodeTypes.NODEFRAME.value,
            color=(0.5, 0.1, 0.0)
        )

        ## Base Color RGB
        base_color_rgb_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_ShaderNodes.BASECOLORRGB.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODERGB.value,
            location=(-200.0, 800.0),
            width=300.0,
            frame=base_color_inputs_frame
        )

        ## Base Color Texture
        base_color_tex_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_ShaderNodes.BASECOLORTEX.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODETEXIMAGE.value,
            location=(-200, 750),
            width=300.0,
            frame=base_color_inputs_frame
        )

        # Set this node as active for solid display with shading.color_type set to texture
        self.node_tree.nodes.active = base_color_tex_node 

        ## Detail Color Texture
        detail_color_tex_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_ShaderNodes.DETAILCOLORTEX.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODETEXIMAGE.value,
            location=(-200, 700),
            width=300.0,
            frame=base_color_inputs_frame
        )

        ## Alpha Inputs Frame
        alpha_inputs_frame = add_node(
            nodes=self.nodes,
            name=MSFS2024_FrameNodes.ALPHAINPUTSFRAME.frame_name(),
            type_node=MSFS2024_ShaderNodeTypes.NODEFRAME.value,
            color=(0.6, 0.6, 0.0)
        )

        ## Base color A
        base_color_a_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_ShaderNodes.BASECOLORA.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEVALUE.value,
            location=(-200.0, 510.0),
            width=300.0,
            frame=alpha_inputs_frame
        )
        base_color_a_node.outputs[0].default_value = 1.0

        alpha_cutoff_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_ShaderNodes.ALPHACUTOFF.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEVALUE.value,
            location=(-200.0, 465.0),
            width=300.0,
            frame=alpha_inputs_frame
        )
        alpha_cutoff_node.outputs[0].default_value = 1.0

        ## UV Inputs Frame ##
        uv_frame = add_node(
            nodes=self.nodes,
            name=MSFS2024_FrameNodes.UVFRAME.frame_name(),
            type_node=MSFS2024_ShaderNodeTypes.NODEFRAME.value,
            color=(0.3, 0.3, 0.5)
        )

        ## UV Offset U
        uv_offset_u_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_ShaderNodes.UVOFFSETU.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEVALUE.value,
            location=(-1200.0, 500.0),
            frame=uv_frame
        )

        ## UV Offset V
        uv_offset_v_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_ShaderNodes.UVOFFSETV.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEVALUE.value,
            location=(-1200.0, 450.0),
            frame=uv_frame
        )

        ## UV Tiling U
        uv_tiling_u_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_ShaderNodes.UVTILINGU.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEVALUE.value,
            location=(-1200.0, 400.0),
            frame=uv_frame
        )

        ## UV Tiling V
        uv_tiling_v_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_ShaderNodes.UVTILINGV.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEVALUE.value,
            location=(-1200.0, 350.0),
            frame=uv_frame
        )

        ## UV Rotation
        uv_rotation_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_ShaderNodes.UVROTATION.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEVALUE.value,
            location=(-1200.0, 300.0),
            frame=uv_frame
        )

        ## Detail UV scale
        detail_uv_scale_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_ShaderNodes.DETAILUVSCALE.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEVALUE.value,
            location=(-1200.0, 250.0),
            frame=uv_frame
        )

        ## OMR Inputs Frame ##
        omr_frame = add_node(
            nodes=self.nodes,
            name=MSFS2024_FrameNodes.OMRFRAME.frame_name(),
            type_node=MSFS2024_ShaderNodeTypes.NODEFRAME.value,
            color=(0.1, 0.4, 0.6)
        )

        ## Metallic scale
        metallic_scale_name = add_node(
            nodes=self.nodes,
            name=MSFS2024_ShaderNodes.METALLICSCALE.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEVALUE.value,
            location=(-200.0, 350.0), 
            frame=omr_frame
        )

        ## Roughness scale
        roughness_scale_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_ShaderNodes.ROUGHNESSSCALE.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEVALUE.value,
            location=(-200.0, 300.0),
            frame=omr_frame
        )

        ## Comp Texture
        omr_tex_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_ShaderNodes.COMPTEX.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODETEXIMAGE.value,
            location=(-200, 250),
            width=300.0,
            frame=omr_frame
        )

        ## Detail Comp Texture
        detail_omr_tex_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_ShaderNodes.DETAILCOMPTEX.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODETEXIMAGE.value,
            location=(-200, 200),
            width=300.0,
            frame=omr_frame
        )

        ## Ambient Occlusion UV2
        ao_uv2_tex_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_ShaderNodes.OCCLUSIONUV2TEX.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODETEXIMAGE.value,
            location=(-200, 150),
            width=300.0,
            frame=omr_frame
        )

        ## Emissive Inputs Frame ##
        emissive_frame = add_node(
            nodes=self.nodes,
            name=MSFS2024_FrameNodes.EMISSIVEFRAME.frame_name(),
            type_node=MSFS2024_ShaderNodeTypes.NODEFRAME.value,
            color=(0.1, 0.5, 0.3)
        )

        ## Emissive Scale
        emissive_scale_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_ShaderNodes.EMISSIVESCALE.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEVALUE.value,
            location=(-200.0, 0.0),
            width=300.0,
            frame=emissive_frame
        )

        ## Emissive Color
        emissive_color_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_ShaderNodes.EMISSIVECOLOR.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODERGB.value,
            location=(-200.0, -50),
            width=300.0,
            frame=emissive_frame
        )

        ## Emissive Texture
        emissive_tex_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_ShaderNodes.EMISSIVETEX.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODETEXIMAGE.value,
            location=(-200, -100.0),
            width=300.0,
            frame=emissive_frame
        )

        ## Normal Inputs Frame
        normal_frame = add_node(
            nodes=self.nodes,
            name=MSFS2024_FrameNodes.NORMALFRAME.frame_name(),
            type_node=MSFS2024_ShaderNodeTypes.NODEFRAME.value,
            color=(0.5, 0.25, 0.25)
        )

        ## Normal scale
        normal_scale_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_ShaderNodes.NORMALSCALE.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEVALUE.value,
            location=(-200.0, -350.0),
            width=300.0,
            frame=normal_frame
        )
        normal_scale_node.outputs[0].default_value = 1.0

        ## Normal Texture
        normal_tex_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_ShaderNodes.NORMALTEX.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODETEXIMAGE.value,
            location=(-200, -400),
            width=300.0,
            frame=normal_frame
        )

        ## Detail Normal Scale
        _ = add_node(
            nodes=self.nodes,
            name=MSFS2024_ShaderNodes.DETAILNORMALSCALE.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEVALUE.value,
            location=(-200.0, -450.0),
            width=300.0,
            frame=normal_frame
        )

        ## Detail Normal Texture
        detail_normal_tex_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_ShaderNodes.DETAILNORMALTEX.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODETEXIMAGE.value,
            location=(-200, -500),
            width=300.0,
            frame=normal_frame
        )

        # endregion

        # region Blend Mask Node Group
        blendmask_group, new_group = get_or_create_group_by_name(
            group_name=MSFS2024_GroupNodes.BLENDMASKGROUP.value
        )

        if new_group:
            self.create_blendmask_shadernode_group(group=blendmask_group)

        blend_mask_group_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_GroupNodes.BLENDMASKGROUP.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEGROUP.value,
            location=(200.0, 1080.0),
            width=250.0,
            hidden=False
        )

        blend_mask_group_node.node_tree = blendmask_group
        ## Links
        link(self.links, blendmask_threshold_node.outputs[0], blend_mask_group_node.inputs[3])
        # endregion

        # region Base Color Node Group
        base_color_group, new_group = get_or_create_group_by_name(
            group_name=MSFS2024_GroupNodes.BASECOLORGROUP.value
        )

        if new_group:
            self.create_base_color_shadernode_group(group=base_color_group)

        base_color_group_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_GroupNodes.BASECOLORGROUP.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEGROUP.value,
            location=(500.0, 900.0),
            width=400.0,
            hidden=False
        )
        base_color_group_node.node_tree = base_color_group
        ## Links
        link(self.links, base_color_rgb_node.outputs[0], base_color_group_node.inputs[0])
        link(self.links, blend_mask_group_node.outputs[0], base_color_group_node.inputs[5])

        # endregion

        # region Alpha Node Group
        alpha_group, new_group = get_or_create_group_by_name(
            group_name=MSFS2024_GroupNodes.ALPHAGROUP.value
        )

        if new_group:
            self.create_alpha_shadernode_group(group=alpha_group)

        alpha_group_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_GroupNodes.ALPHAGROUP.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEGROUP.value,
            location=(500.0, 600.0),
            width=400.0,
            hidden=False
        )
        alpha_group_node.node_tree = alpha_group

        ## Links
        link(self.links, base_color_a_node.outputs[0], alpha_group_node.inputs[0])
        link(self.links, alpha_cutoff_node.outputs[0], alpha_group_node.inputs[3])
        # endregion

        # region UV Node Group
        uv_group, new_group = get_or_create_group_by_name(
            group_name=MSFS2024_GroupNodes.UVGROUP.value
        )

        if new_group:
            self.create_uv_shadernode_group(group=uv_group)

        uv_group_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_GroupNodes.UVGROUP.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEGROUP.value,
            location=(-1000.0, 500.0),
            width=300.0,
            hidden=False
        )
        uv_group_node.node_tree = uv_group

        ## Links
        link(self.links, uv_offset_u_node.outputs[0], uv_group_node.inputs[0])
        link(self.links, uv_offset_v_node.outputs[0], uv_group_node.inputs[1])
        link(self.links, uv_tiling_u_node.outputs[0], uv_group_node.inputs[2])
        link(self.links, uv_tiling_v_node.outputs[0], uv_group_node.inputs[3])
        link(self.links, uv_rotation_node.outputs[0], uv_group_node.inputs[4])
        link(self.links, detail_uv_scale_node.outputs[0], uv_group_node.inputs[5])

        link(self.links, uv_group_node.outputs[0], blendmask_tex_node.inputs[0])
        link(self.links, uv_group_node.outputs[0], base_color_tex_node.inputs[0])
        link(self.links, uv_group_node.outputs[0], omr_tex_node.inputs[0])
        link(self.links, uv_group_node.outputs[0], emissive_tex_node.inputs[0])
        link(self.links, uv_group_node.outputs[0], normal_tex_node.inputs[0])

        link(self.links, uv_group_node.outputs[1], detail_color_tex_node.inputs[0])
        link(self.links, uv_group_node.outputs[1], detail_omr_tex_node.inputs[0])
        link(self.links, uv_group_node.outputs[1], detail_normal_tex_node.inputs[0])

        link(self.links, uv_group_node.outputs[2], ao_uv2_tex_node.inputs[0])
        # endregion

        # region OMR Group
        omr_group, new_group = get_or_create_group_by_name(
            group_name=MSFS2024_GroupNodes.OMRGROUP.value
        )

        if new_group:
            self.create_orm_shadernode_group(group=omr_group)

        omr_group_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_GroupNodes.OMRGROUP.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEGROUP.value,
            location=(500.0, 400.0),
            width=400.0,
            hidden=False
        )
        omr_group_node.node_tree = omr_group

        ## Links
        link(self.links, metallic_scale_name.outputs[0], omr_group_node.inputs[0])
        link(self.links, roughness_scale_node.outputs[0], omr_group_node.inputs[1])

        link(self.links, omr_group_node.outputs[0], principled_bsdf_node.inputs[MSFS2024_PrincipledBSDFInputs.METALLIC.value])
        link(self.links, omr_group_node.outputs[1], principled_bsdf_node.inputs[MSFS2024_PrincipledBSDFInputs.ROUGHNESS.value])
        link(self.links, blend_mask_group_node.outputs[0], omr_group_node.inputs[5])

        # endregion

        # region Emissive Group
        emissive_group, new_group = get_or_create_group_by_name(
            group_name=MSFS2024_GroupNodes.EMISSIVEGROUP.value
        )

        if new_group:
            self.create_emissive_shadernode_group(group=emissive_group) 

        emissive_group_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_GroupNodes.EMISSIVEGROUP.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEGROUP.value,
            location=(500.0, 0.0),
            width=400.0,
            hidden=False
        )
        emissive_group_node.node_tree = emissive_group

        ## Links
        link(self.links, emissive_scale_node.outputs[0], emissive_group_node.inputs[0])
        link(self.links, emissive_color_node.outputs[0], emissive_group_node.inputs[1])

        link(self.links, emissive_group_node.outputs[0], principled_bsdf_node.inputs[MSFS2024_PrincipledBSDFInputs.EMISSION.value])
        link(self.links, emissive_scale_node.outputs[0], principled_bsdf_node.inputs[MSFS2024_PrincipledBSDFInputs.EMISSIONSTRENGTH.value])
        # endregion

        # region Normal Group
        normal_group, new_group = get_or_create_group_by_name(
            group_name=MSFS2024_GroupNodes.NORMALGROUP.value
        )

        if new_group:
            self.create_normal_shadernode_group(group=normal_group)

        normal_group_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_GroupNodes.NORMALGROUP.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEGROUP.value,
            location=(500.0, -250.0),
            width=400.0,
            hidden=False
        )
        normal_group_node.node_tree = normal_group

        # region Links
        link(self.links, blend_mask_group_node.outputs[0], normal_group_node.inputs[5])
        # endregion

        # endregion

        # region Apply AO group
        apply_ao_group, new_group = get_or_create_group_by_name(
            group_name=MSFS2024_GroupNodes.APPLYAOGROUP.value
        )

        if new_group:
            self.create_apply_ao_group(group=apply_ao_group)

        apply_ao_group_node = add_node(
            nodes=self.nodes,
            name=MSFS2024_GroupNodes.APPLYAOGROUP.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEGROUP.value,
            location=(1200.0, 630.0),
            width=400.0,
            hidden=False
        )
        apply_ao_group_node.node_tree = apply_ao_group
        # endregion

        # region Links
        link(self.links, base_color_group_node.outputs[0], apply_ao_group_node.inputs[0])
        link(self.links, apply_ao_group_node.outputs[0], principled_bsdf_node.inputs[MSFS2024_PrincipledBSDFInputs.BASECOLOR.value])
        # endregion

    def set_default_properties(self, attributes=None):
        if attributes is None:
            attributes = []

        attribute_names = [x.attribute_name() for x in attributes]
        material_properties = list(MSFS2024_MaterialProperties)

        ## we start at 1 to avoid changing the material type
        for i in range(1, len(material_properties)): 
            material_property = material_properties[i]

            if material_property.attribute_name() in attribute_names:
                continue

            if hasattr(self.material, material_property.attribute_name()):
                setattr(self.material, material_property.attribute_name(), material_property.default_value())

    def force_update_nodes(self):
        self.set_blend_mode(getattr(self.material, MSFS2024_MaterialProperties.ALPHAMODE.attribute_name()))

        self.set_base_color(getattr(self.material, MSFS2024_MaterialProperties.BASECOLOR.attribute_name()))
        self.set_base_color_tex(getattr(self.material, MSFS2024_MaterialProperties.BASECOLORTEXTURE.attribute_name()))
        self.set_omr_tex(getattr(self.material, MSFS2024_MaterialProperties.OMRTEXTURE.attribute_name()))
        self.set_normal_tex(getattr(self.material, MSFS2024_MaterialProperties.NORMALTEXTURE.attribute_name()))

        self.set_blendmask_tex(getattr(self.material, MSFS2024_MaterialProperties.BLENDMASKTEXTURE.attribute_name()))
        self.set_detail_color_tex(getattr(self.material, MSFS2024_MaterialProperties.DETAILCOLORTEXTURE.attribute_name()))
        self.set_detail_omr_tex(getattr(self.material, MSFS2024_MaterialProperties.DETAILOMRTEXTURE.attribute_name()))
        self.set_detail_normal_tex(getattr(self.material, MSFS2024_MaterialProperties.DETAILNORMALTEXTURE.attribute_name()))
        self.set_occlusion_uv2_tex(getattr(self.material, MSFS2024_MaterialProperties.OCCLUSIONUV2.attribute_name()))

        self.set_emissive_tex(getattr(self.material, MSFS2024_MaterialProperties.EMISSIVETEXTURE.attribute_name()))
        self.set_emissive_color(getattr(self.material, MSFS2024_MaterialProperties.EMISSIVECOLOR.attribute_name()))
        self.set_emissive_scale(getattr(self.material, MSFS2024_MaterialProperties.EMISSIVESCALE.attribute_name()))
        self.set_normal_scale(getattr(self.material, MSFS2024_MaterialProperties.NORMALSCALE.attribute_name()))
        self.set_metallic_scale(getattr(self.material, MSFS2024_MaterialProperties.METALLICSCALE.attribute_name()))
        self.set_roughness_scale(getattr(self.material, MSFS2024_MaterialProperties.ROUGHNESSSCALE.attribute_name()))

        self.set_double_sided()
        self.set_alpha_cutoff(getattr(self.material, MSFS2024_MaterialProperties.ALPHACUTOFF.attribute_name()))

        self.set_uv_offset_u(getattr(self.material, MSFS2024_MaterialProperties.UVOFFSETU.attribute_name()))
        self.set_uv_offset_v(getattr(self.material, MSFS2024_MaterialProperties.UVOFFSETV.attribute_name()))
        self.set_uv_tiling_u(getattr(self.material, MSFS2024_MaterialProperties.UVTILINGU.attribute_name()))
        self.set_uv_tiling_v(getattr(self.material, MSFS2024_MaterialProperties.UVTILINGV.attribute_name()))
        self.set_uv_rotation(getattr(self.material, MSFS2024_MaterialProperties.UVROTATION.attribute_name()))

        self.set_detail_uv_scale(getattr(self.material, MSFS2024_MaterialProperties.DETAILUVSCALE.attribute_name()))
        self.set_detail_normal_scale(getattr(self.material, MSFS2024_MaterialProperties.DETAILNORMALSCALE.attribute_name()))

    # region Setter
    def set_base_color(self, color):
        base_color_rgb_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.BASECOLORRGB.value)
        base_color_a_node = get_node_by_name(self.nodes,MSFS2024_ShaderNodes.BASECOLORA.value)

        if base_color_rgb_node and base_color_a_node:
            base_color_rgb_node.outputs[0].default_value[0] = color[0]
            base_color_rgb_node.outputs[0].default_value[1] = color[1]
            base_color_rgb_node.outputs[0].default_value[2] = color[2]
            base_color_a_node.outputs[0].default_value = color[3]

            self._update_color_links()

    def set_alpha_cutoff(self, value):
        alpha_cutoff_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.ALPHACUTOFF.value)
        if alpha_cutoff_node:
            alpha_cutoff_node.outputs[0].default_value = value

    def set_base_color_tex(self, image: bpy.types.Image | None):
        base_color_rgb_tex_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.BASECOLORTEX.value)
        if base_color_rgb_tex_node:
            base_color_rgb_tex_node.image = image

            self._update_color_links()

    def set_detail_color_tex(self, image: bpy.types.Image | None):
        detail_color_tex_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.DETAILCOLORTEX.value)
        if detail_color_tex_node:
            
            detail_color_tex_node.image = image
            self._update_color_links()

    def set_omr_tex(self, image: bpy.types.Image | None):
        omr_tex_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.COMPTEX.value)
        if omr_tex_node:
            omr_tex_node.image = image
            self._update_omr_links()
            self._update_ao_links()

    def set_detail_omr_tex(self, image: bpy.types.Image | None):
        detail_omr_tex_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.DETAILCOMPTEX.value)
        if detail_omr_tex_node:
            detail_omr_tex_node.image = image
            self._update_omr_links()
            self._update_ao_links()

    def set_occlusion_uv2_tex(self, image: bpy.types.Image | None):
        occlusion_uv2_tex_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.OCCLUSIONUV2TEX.value)
        if occlusion_uv2_tex_node:
            

            occlusion_uv2_tex_node.image = image
            self._update_ao_links()

    def set_roughness_scale(self, scale):
        roughness_scale_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.ROUGHNESSSCALE.value)
        if roughness_scale_node:
            roughness_scale_node.outputs[0].default_value = scale
            self._update_omr_links()

    def set_metallic_scale(self, scale):
        metallic_scale_name = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.METALLICSCALE.value)
        if metallic_scale_name:
            metallic_scale_name.outputs[0].default_value = scale
            self._update_omr_links()

    def set_emissive_tex(self, image: bpy.types.Image | None ):
        emissive_tex_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.EMISSIVETEX.value)
        if emissive_tex_node:
            emissive_tex_node.image = image
            self._update_emissive_links()

    def set_emissive_scale(self, scale):
        emissive_scale_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.EMISSIVESCALE.value)
        if emissive_scale_node:
            # Trying to prevent big emissive value while having something close to in game render
            if scale > 0:
                scale = math.log(scale * 0.005 + 1)
            emissive_scale_node.outputs[0].default_value = scale
            self._update_emissive_links()

    def set_emissive_color(self, color):
        emissive_color_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.EMISSIVECOLOR.value)
        if emissive_color_node:
            emissive_value = emissive_color_node.outputs[0].default_value
            emissive_value[0] = color[0]
            emissive_value[1] = color[1]
            emissive_value[2] = color[2]
            emissive_color_node.outputs[0].default_value = emissive_value
            self._update_emissive_links()

    def set_normal_scale(self, scale):
        normal_scale_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.NORMALSCALE.value)
        if normal_scale_node:
            normal_scale_node.outputs[0].default_value = scale
            self._update_normal_links()

    def set_normal_tex(self, image: bpy.types.Image | None):
        normal_tex_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.NORMALTEX.value)
        if normal_tex_node:
            normal_tex_node.image = image
            self._update_normal_links()

    def set_detail_normal_scale(self, scale):
        detail_normal_scale_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.DETAILNORMALSCALE.value)
        if detail_normal_scale_node:
            detail_normal_scale_node.outputs[0].default_value = scale
            self._update_normal_links()

    def set_detail_normal_tex(self, image: bpy.types.Image | None):
        detail_normal_tex_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.DETAILNORMALTEX.value)
        if detail_normal_tex_node:
            detail_normal_tex_node.image = image
            self._update_normal_links()

    def set_blendmask_threshold(self,value):
        blendmask_threshold_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.DETAILBLENDMASKTHRESHOLD.value)
        if blendmask_threshold_node:
            blendmask_threshold_node.outputs[0].default_value = value

    def set_blendmask_tex(self, image: bpy.types.Image | None):
        detail_blend_tex_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.BLENDMASKTEX.value)
        if detail_blend_tex_node:
            detail_blend_tex_node.image = image
            self._update_blendmask_links()
            self._update_blendmask_mode()

    def set_detail_uv_scale(self, uv_scale):
        detail_uv_scale_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.DETAILUVSCALE.value)

        if detail_uv_scale_node:
            detail_uv_scale_node.outputs[0].default_value = uv_scale

    def set_uv_offset_u(self, offset_u):
        uv_offset_u_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.UVOFFSETU.value)

        if uv_offset_u_node:
            uv_offset_u_node.outputs[0].default_value = offset_u

    def set_uv_offset_v(self, offset_v):
        uv_offset_v_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.UVOFFSETV.value)

        if uv_offset_v_node:
            uv_offset_v_node.outputs[0].default_value = offset_v

    def set_uv_tiling_u(self, tiling_u):
        uv_tiling_u_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.UVTILINGU.value)

        if uv_tiling_u_node:
            uv_tiling_u_node.outputs[0].default_value = tiling_u

    def set_uv_tiling_v(self, tiling_v):
        uv_tiling_v_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.UVTILINGV.value)

        if uv_tiling_v_node:
            uv_tiling_v_node.outputs[0].default_value = tiling_v

    def set_uv_rotation(self, rotation):
        uv_rotation_node = get_node_by_name(self.nodes, MSFS2024_ShaderNodes.UVROTATION.value)

        if uv_rotation_node:
            uv_rotation_node.outputs[0].default_value = rotation

    def set_blend_mode(self, blend_mode):
        if blend_mode == "BLEND":
            self._make_alpha_blend()
        elif blend_mode == "MASK":
            self._make_masked()
        elif blend_mode == "DITHER":
            self._make_dither()
        else:
            self._make_opaque()
        self._update_alpha_mode()

    def set_double_sided(self):
        self.material.use_backface_culling = not getattr(self.material, MSFS2024_MaterialProperties.DOUBLESIDED.attribute_name())

    # endregion

    # region Shader Graph Nodes
    def create_blendmask_shadernode_group(self, group):
        input_node = add_node(
            nodes=group.nodes,
            name=MSFS2024_NodesSockets.GROUPINPUT.value,
            type_node=MSFS2024_GroupTypes.NODEGROUPINPUT.value,
            hidden=False
        )

        output_node = add_node(
            nodes=group.nodes,
            name=MSFS2024_NodesSockets.GROUPOUTPUT.value,
            type_node=MSFS2024_GroupTypes.NODEGROUPOUTPUT.value,
            location=(1625.0, 30.0),
            hidden=False
        )

        # region Inputs
        # Base Color A
        base_color_a_input = add_group_input(
            group=group, 
            input_name=MSFS2024_ShaderNodes.DETAILCOLORTEX.value,
            input_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
        )
        base_color_a_input.default_value = 1.0

        # Blend Mask Texture
        blendmask_tex_input = add_group_input(
            group=group, 
            input_name=MSFS2024_ShaderNodes.BLENDMASKTEX.value,
            input_type=MSFS2024_GroupTypes.NODESOCKETCOLOR.value
        )
        blendmask_tex_input.default_value = (1.0, 1.0, 1.0, 1.0)

        # Enable Blend Mask Bool
        enable_blendmask_input = add_group_input(
            group=group, 
            input_name="Enable Blend Mask",
            input_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
        )
        enable_blendmask_input.default_value = 0.0

        # Detail Color Texture
        blendmask_threshold_input = add_group_input(
            group=group, 
            input_name=MSFS2024_ShaderNodes.DETAILBLENDMASKTHRESHOLD.value,
            input_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
        )
        blendmask_threshold_input.default_value = 0

        # Switch blend mode
        switch_to_blend_mode_input = add_group_input(
            group=group, 
            input_name="Switch To Blend Mode",
            input_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
        )
        switch_to_blend_mode_input.default_value = 0
        # endregion

        # region Outputs
        _ = add_group_output(
            group=group,
            output_name="Mask",
            output_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
        )
        # endregion

        # region Common Nodes
        vertex_color_map_node = add_node(
        nodes=group.nodes,
        name=MSFS2024_NodesSockets.VERTEXCOLOR.value,
        type_node=MSFS2024_ShaderNodeTypes.SHADERNODEVERTEXCOLOR.value,
        location=(0.0, 174),
        hidden = False
        )   
        # endregion

        # region #Detail Mode#

        detail_mask_frame = add_node(
            nodes=group.nodes,
            name=MSFS2024_FrameNodes.DETAILMASKFRAME.frame_name(),
            type_node=MSFS2024_ShaderNodeTypes.NODEFRAME.value,
            color=MSFS2024_FrameNodes.DETAILMASKFRAME.color()
        )

        detail_multiply_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
            operation=MSFS2024_NodeMathOpe.MULTIPLY.value,
            location=(230, 30),
            frame=detail_mask_frame
        )

        reroute_detail_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.NODEREROUTE.value,
            location=(1114, 20),
            frame=detail_mask_frame
        )

        # region Links
        link(group.links, vertex_color_map_node.outputs[1], detail_multiply_node.inputs[0])
        link(group.links, input_node.outputs[0], detail_multiply_node.inputs[1])
        link(group.links, detail_multiply_node.outputs[0], reroute_detail_node.inputs[0])
        # endregion
        # endregion #Detail Mode#

        # region #Blend Mode#
        blend_mask_frame = add_node(
            nodes=group.nodes,
            name=MSFS2024_FrameNodes.BLENDMASKFRAME.frame_name(),
            type_node=MSFS2024_ShaderNodeTypes.NODEFRAME.value,
            color=MSFS2024_FrameNodes.BLENDMASKFRAME.color()
        )

        blend_separate_color_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODESEPARATECOLOR.value,
            location=(220, -250),
            frame=blend_mask_frame
        )

        blend_subtract_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
            operation=MSFS2024_NodeMathOpe.SUBTRACT.value,
            location=(450, -330),
            frame=blend_mask_frame
        )
        blend_subtract_node.use_clamp = True

        blend_add_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
            operation=MSFS2024_NodeMathOpe.ADD.value,
            location=(450, -225),
            frame=blend_mask_frame
        )
        blend_add_node.use_clamp = True

        blend_linear_step_node = msfs_material_nodes_library.add_linear_step_node(
            node_tree = group,
            location=(700,-200),
            frame=blend_mask_frame
        )

        blend_switch_node = msfs_material_nodes_library.add_switch_node(
            node_tree = group,
            location=(975, -90),
            frame=blend_mask_frame
        )

        # region Links
        link(group.links, input_node.outputs[1], blend_separate_color_node.inputs[0])

        link(group.links, input_node.outputs[3], blend_add_node.inputs[0])
        link(group.links, input_node.outputs[3], blend_subtract_node.inputs[1])

        link(group.links, blend_separate_color_node.outputs[0], blend_add_node.inputs[1])
        link(group.links, blend_separate_color_node.outputs[0], blend_subtract_node.inputs[0])

        link(group.links, blend_subtract_node.outputs[0], blend_linear_step_node.inputs[0])
        link(group.links, blend_add_node.outputs[0], blend_linear_step_node.inputs[1])
        link(group.links, vertex_color_map_node.outputs[1], blend_linear_step_node.inputs[2])

        link(group.links, input_node.outputs[2], blend_switch_node.inputs[0])
        link(group.links, vertex_color_map_node.outputs[1], blend_switch_node.inputs[1])
        link(group.links, blend_linear_step_node.outputs[0], blend_switch_node.inputs[2])

        # endregion

        # endregion #Blend Mode#

        mode_switch_node = msfs_material_nodes_library.add_switch_node(
            group,
            location=(1325,30)
        )

        link(group.links, input_node.outputs[4], mode_switch_node.inputs[0])
        link(group.links, reroute_detail_node.outputs[0], mode_switch_node.inputs[1])
        link(group.links, blend_switch_node.outputs[0], mode_switch_node.inputs[2])
        link(group.links, mode_switch_node.outputs[0], output_node.inputs[0])

    def create_base_color_shadernode_group(self, group):
        input_node = add_node(
            nodes=group.nodes,
            name=MSFS2024_NodesSockets.GROUPINPUT.value,
            type_node=MSFS2024_GroupTypes.NODEGROUPINPUT.value,
            hidden=False
        )

        output_node = add_node(
            nodes=group.nodes,
            name=MSFS2024_NodesSockets.GROUPOUTPUT.value,
            type_node=MSFS2024_GroupTypes.NODEGROUPOUTPUT.value,
            location=(2600.0, -350.0),
            hidden=False
        )

        # region Inputs
        # Base Color RGB
        base_color_rgb_input = add_group_input(
            group=group, 
            input_name=MSFS2024_ShaderNodes.BASECOLORRGB.value,
            input_type=MSFS2024_GroupTypes.NODESOCKETCOLOR.value
        )
        base_color_rgb_input.default_value = (1.0, 1.0, 1.0, 1.0)

        # Base Color Texture
        base_color_tex_input = add_group_input(
            group=group, 
            input_name=MSFS2024_ShaderNodes.BASECOLORTEX.value,
            input_type=MSFS2024_GroupTypes.NODESOCKETCOLOR.value
        )
        base_color_tex_input.default_value = (1.0, 1.0, 1.0, 1.0)

        # Detail Color Texture
        detail_color_tex_input = add_group_input(
            group=group, 
            input_name=MSFS2024_ShaderNodes.DETAILCOLORTEX.value,
            input_type=MSFS2024_GroupTypes.NODESOCKETCOLOR.value
        )
        detail_color_tex_input.default_value = (1.0, 1.0, 1.0, 1.0)

        # Detail Color Texture Alpha
        detail_color_tex_a_input = add_group_input(
            group=group,
            input_name=MSFS2024_ShaderNodes.DETAILCOLORTEX.value,
            input_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
        )
        detail_color_tex_a_input.default_value = 1.0

        enable_detail_color_input = add_group_input(
            group=group,
            input_name="Enable Detail Color",
            input_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
        )
        enable_detail_color_input.default_value = 0

        mask_input = add_group_input(
            group=group,
            input_name="Mask",
            input_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
        )
        mask_input.default_value = 0

        switch_to_blend_mode_input = add_group_input(
            group=group,
            input_name=MSFS2024_NodesSockets.SWITCHTOBLENDMODE.value,
            input_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
        )
        switch_to_blend_mode_input.default_value = 0
        # endregion

        # region Outputs
        # Base Color RGB
        _ = add_group_output(
            group=group,
            output_name=MSFS2024_ShaderNodes.BASECOLORRGB.value,
            output_type=MSFS2024_GroupTypes.NODESOCKETCOLOR.value
        )
        # endregion

        # region Common Nodes
        multiply_base_color_rgb_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMIXRGB.value,
            blend_type = MSFS2024_NodeBlendTypes.MULTIPLY.value,
            location=(270.0, -25.0),
        )
        multiply_base_color_rgb_node.inputs[0].default_value = 1.0

        vertex_color_map_node = add_node(
            nodes=group.nodes,
            name=MSFS2024_NodesSockets.VERTEXCOLOR.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEVERTEXCOLOR.value,
            location=(1500, -435),
            hidden=False
        )

        # region Links
        link(group.links, input_node.outputs[0], multiply_base_color_rgb_node.inputs[1])
        link(group.links, input_node.outputs[1], multiply_base_color_rgb_node.inputs[2])
        # endregion

        # endregion

        # region Detail Mode
        detail_mask_frame = add_node(
            nodes=group.nodes,
            name=MSFS2024_FrameNodes.DETAILMASKFRAME.frame_name(),
            type_node=MSFS2024_ShaderNodeTypes.NODEFRAME.value,
            color=MSFS2024_FrameNodes.DETAILMASKFRAME.color()
        )

        multiply_detail_rgb_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMIXRGB.value,
            blend_type = MSFS2024_NodeBlendTypes.MULTIPLY.value,
            location=(585.0, -190.0),
            frame=detail_mask_frame
        )
        multiply_detail_rgb_node.inputs[0].default_value = 1.0

        sqrt_color_node = msfs_material_nodes_library.add_sqrt_color_node(
            group,
            frame=detail_mask_frame,
            location=(800,-240)
        )

        smooth_step_node = add_node(
            nodes=group.nodes,
            name="Smoothstep",
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMAPRANGE.value,
            location=(1075.0, -275.0),
            frame=detail_mask_frame
        )
        smooth_step_node.data_type = MSFS2024_NodeDataTypes.FLOAT_VECTOR.value
        smooth_step_node.interpolation_type = MSFS2024_MapRangeType.SMOOTHSTEP.value

        multiply_detail_a_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
            operation =MSFS2024_NodeMathOpe.MULTIPLY.value,
            location=(1200.0, -120.0),
            frame=detail_mask_frame
        )
        multiply_detail_a_node.inputs[0].default_value = 1.0

        detail_mix_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMIXRGB.value,
            location=(1425.0, -165.0),
            frame=detail_mask_frame
        )

        detail_switch_node = msfs_material_nodes_library.add_switch_node(
            group,
            frame=detail_mask_frame,
            location=(1600,0)
        )

        multiply_detail_vertex_color_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMIXRGB.value,
            blend_type = MSFS2024_NodeBlendTypes.MULTIPLY.value,
            location=(1900.0, -25.0),
            frame=detail_mask_frame
        )

        multiply_detail_vertex_color_node.inputs[0].default_value = 1.0

        # region Links
        link(group.links, multiply_base_color_rgb_node.outputs[0], multiply_detail_rgb_node.inputs[1])
        link(group.links, input_node.outputs[2], multiply_detail_rgb_node.inputs[2])

        link(group.links, multiply_detail_rgb_node.outputs[0], sqrt_color_node.inputs[0])
        link(group.links, sqrt_color_node.outputs[0], smooth_step_node.inputs[6]) ## input[6] == "Vector"

        link(group.links, input_node.outputs[3], multiply_detail_a_node.inputs[0])
        link(group.links, input_node.outputs[5], multiply_detail_a_node.inputs[1])

        link(group.links, multiply_detail_a_node.outputs[0], detail_mix_node.inputs[0])

        link(group.links, multiply_base_color_rgb_node.outputs[0], detail_mix_node.inputs[1])
        link(group.links, smooth_step_node.outputs[1], detail_mix_node.inputs[2])

        link(group.links, input_node.outputs[4], detail_switch_node.inputs[0])
        link(group.links, multiply_base_color_rgb_node.outputs[0], detail_switch_node.inputs[1])
        link(group.links, detail_mix_node.outputs[0], detail_switch_node.inputs[2])

        link(group.links, detail_switch_node.outputs[0], multiply_detail_vertex_color_node.inputs[1])
        link(group.links, vertex_color_map_node.outputs[0], multiply_detail_vertex_color_node.inputs[2])
        # endregion

        # endregion

        # region Blend Mode
        blend_mask_frame = add_node(
            nodes=group.nodes,
            name=MSFS2024_FrameNodes.BLENDMASKFRAME.frame_name(),
            type_node=MSFS2024_ShaderNodeTypes.NODEFRAME.value,
            color=MSFS2024_FrameNodes.BLENDMASKFRAME.color()
        )

        blend_mix_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMIXRGB.value,
            location=(585.0, -600.0),
            frame=blend_mask_frame
        )

        multiply_blend_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMIXRGB.value,
            blend_type = MSFS2024_NodeBlendTypes.MULTIPLY.value,
            location=(1900.0, -600.0),
            frame=blend_mask_frame
        )
        multiply_blend_node.inputs[0].default_value = 1.0

        # Switch between detail and blend mode
        mode_switch_node = msfs_material_nodes_library.add_switch_node(
            group,
            location=(2250,-330)
        )

        # region Links
        link(group.links, input_node.outputs[5], blend_mix_node.inputs[0])
        link(group.links, input_node.outputs[2], blend_mix_node.inputs[1])
        link(group.links, multiply_base_color_rgb_node.outputs[0], blend_mix_node.inputs[2])

        link(group.links, blend_mix_node.outputs[0], multiply_blend_node.inputs[1])
        link(group.links, vertex_color_map_node.outputs[0], multiply_blend_node.inputs[2])
        # endregion

        # endregion

        # region Links
        link(group.links, input_node.outputs[6], mode_switch_node.inputs[0])
        link(group.links, multiply_detail_vertex_color_node.outputs[0], mode_switch_node.inputs[1])
        link(group.links, multiply_blend_node.outputs[0], mode_switch_node.inputs[2])
        link(group.links, mode_switch_node.outputs[0], output_node.inputs[0])
        # endregion

    def create_alpha_shadernode_group(self, group):
        ## Group Nodes
        input_node = add_node(
            nodes=group.nodes,
            name=MSFS2024_NodesSockets.GROUPINPUT.value,
            type_node=MSFS2024_GroupTypes.NODEGROUPINPUT.value,
            hidden=False
        )

        output_node = add_node(
            nodes=group.nodes,
            name=MSFS2024_NodesSockets.GROUPOUTPUT.value,
            type_node=MSFS2024_GroupTypes.NODEGROUPOUTPUT.value,
            location=(1800.0, 100.0),
            hidden=False
        )

        # Blend Alpha Map (Detail alpha operator)
        blend_alpha_map_node = add_node(
            nodes=group.nodes,
            name="Blend Alpha Map",
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
            operation=MSFS2024_NodeMathOpe.MULTIPLY.value,
            location=(300.0, -50.0),
            width=200.0
        )

        ## Base Color Multiplier
        multiply_base_color_a_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
            operation=MSFS2024_NodeMathOpe.MULTIPLY.value,
            location=(575.0, -50.0),
            width=200.0
        )

        multiply_vertex_color_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
            operation=MSFS2024_NodeMathOpe.MULTIPLY.value,
            location=(900.0, 50.0),
            width=200.0
        )

        vertex_color_map_node = add_node(
            nodes=group.nodes,
            name=MSFS2024_NodesSockets.VERTEXCOLOR.value,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEVERTEXCOLOR.value,
            location=(700, -125)
        )

        greather_than_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
            operation=MSFS2024_NodeMathOpe.GREATER_THAN.value,
            location=(1180.0, -165.0),
            width=200.0
        )

        ## Inputs
        # Alpha Scalar
        alpha_scalar_input = add_group_input(
            group=group, 
            input_name=MSFS2024_ShaderNodes.BASECOLORA.value,
            input_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
        )
        alpha_scalar_input.default_value = 1.0

        # Base Color Texture Alpha
        base_color_tex_a_input = add_group_input(
            group=group, 
            input_name=MSFS2024_ShaderNodes.BASECOLORTEX.value,
            input_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
        )
        base_color_tex_a_input.default_value = 1.0

        # Detail Color Texture Alpha
        detail_color_tex_a_input = add_group_input(
            group=group, 
            input_name=MSFS2024_ShaderNodes.DETAILCOLORTEX.value,
            input_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
        )
        detail_color_tex_a_input.default_value = 1.0

        alpha_cutoff_input = add_group_input(
            group=group,
            input_name=MSFS2024_ShaderNodes.ALPHACUTOFF.value,
            input_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
        )
        alpha_cutoff_input.default_value = 1.0

        switch_to_mask_mode_input = add_group_input(
            group=group,
            input_name="Switch To Mask Mode",
            input_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
        )
        switch_to_mask_mode_input.default_value = 0

        # Switch between detail and blend mode
        mask_mode_switch_node = msfs_material_nodes_library.add_switch_node(
            group,
            location=(1500,50)
        )

        ## Outputs
        # Alpha
        _ = add_group_output(
            group=group,
            output_name=MSFS2024_ShaderNodes.BASECOLORA.value,
            output_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
        )

        ## Links
        link(group.links, input_node.outputs[1], blend_alpha_map_node.inputs[0])
        link(group.links, input_node.outputs[2], blend_alpha_map_node.inputs[1])
        link(group.links, input_node.outputs[0], multiply_base_color_a_node.inputs[0])
        link(group.links, blend_alpha_map_node.outputs[0], multiply_base_color_a_node.inputs[1])
        link(group.links, multiply_base_color_a_node.outputs[0], multiply_vertex_color_node.inputs[0])
        link(group.links, vertex_color_map_node.outputs[1], multiply_vertex_color_node.inputs[1])
        link(group.links, input_node.outputs[4], mask_mode_switch_node.inputs[0])
        link(group.links, multiply_vertex_color_node.outputs[0], mask_mode_switch_node.inputs[1])
        link(group.links, mask_mode_switch_node.outputs[0],  output_node.inputs[0])
        link(group.links, multiply_vertex_color_node.outputs[0],  greather_than_node.inputs[0])
        link(group.links, input_node.outputs[3],  greather_than_node.inputs[1])
        link(group.links, greather_than_node.outputs[0],  mask_mode_switch_node.inputs[2])

    def create_uv_shadernode_group(self, group):
        ## Group Nodes
        input_node = add_node(
            nodes=group.nodes,
            name=MSFS2024_NodesSockets.GROUPINPUT.value,
            type_node=MSFS2024_GroupTypes.NODEGROUPINPUT.value,
            location=(-450.0, 10.0),
            hidden=False
        )
        output_node = add_node(
            nodes=group.nodes,
            name=MSFS2024_NodesSockets.GROUPOUTPUT.value,
            type_node=MSFS2024_GroupTypes.NODEGROUPOUTPUT.value,
            location=(1235.0, 10.0),
            hidden=False
        )

        # region Inputs
        # UV Offset U
        _ = add_group_input(
            group=group,
            input_name=MSFS2024_ShaderNodes.UVOFFSETU.value,
            input_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
        )

        # UV Offset V
        _ = add_group_input(
            group=group,
            input_name=MSFS2024_ShaderNodes.UVOFFSETV.value,
            input_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
        )

        # UV Tiling U
        _ = add_group_input(
            group=group,
            input_name=MSFS2024_ShaderNodes.UVTILINGU.value,
            input_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
        )

        # UV Tiling V
        _ = add_group_input(
            group=group,
            input_name=MSFS2024_ShaderNodes.UVTILINGV.value,
            input_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
        )

        # UV Rotation
        _ = add_group_input(
            group=group,
            input_name=MSFS2024_ShaderNodes.UVROTATION.value,
            input_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
        )

        # Detail UV Scale
        _ = add_group_input(
            group=group,
            input_name=MSFS2024_ShaderNodes.DETAILUVSCALE.value,
            input_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
        )
        # endregion

        # region Outputs
        # UV Coordinates
        add_group_output(
            group=group,
            output_name="UV Coordinate",
            output_type=MSFS2024_GroupTypes.NODESOCKETVECTOR.value
        )

        # Detail UV Coordinates
        add_group_output(
            group=group,
            output_name="Detail UV Coordinate",
            output_type=MSFS2024_GroupTypes.NODESOCKETVECTOR.value
        )
        add_group_output(
            group=group,
            output_name="UV2",
            output_type=MSFS2024_GroupTypes.NODESOCKETVECTOR.value
        )
        # endregion

        # region Nodes
        # UV Map
        uv_map_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEUVMAP.value,
            location=(-606.0, 115.0)
        )

        subtract_half_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEVECTORMATH.value,
            operation=MSFS2024_NodeMathOpe.SUBTRACT.value,
            location=(-355.0, 90.0)
        )
        subtract_half_node.inputs[1].default_value = (0.5,0.5,0.0)

        to_rad_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
            operation=MSFS2024_NodeMathOpe.RADIANS.value,
            location=(-245.0, 36.0)
        )

        # Rotate UV
        uv_rotate_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEVECTORROTATE.value,
            location=(-175.0, 85.0)
        )

        # Separate UV
        separate_uv_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODESEPARATEXYZ.value,
            location=(5.0, 86.0)
        )

        # Multiply Tiling U
        multiply_tiling_u_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
            operation=MSFS2024_NodeMathOpe.MULTIPLY.value,
            location=(200.0, 92.0)
        )

        # Multiply Tiling V
        multiply_tiling_v_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
            operation=MSFS2024_NodeMathOpe.MULTIPLY.value,
            location=(200.0, 44.0)
        )

        # Add Offset U
        add_offset_u_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
            operation=MSFS2024_NodeMathOpe.ADD.value,
            location=(450.0, -10.0)
        )

        # Sub Offset V
        sub_offset_v_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
            operation=MSFS2024_NodeMathOpe.SUBTRACT.value,
            location=(450.0, -50.0)
        )

        # Combine UV
        combine_uv_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODECOMBINEXYZ.value,
            location=(710.0, -10.0)
        )

        add_half_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEVECTORMATH.value,
            operation=MSFS2024_NodeMathOpe.ADD.value,
            location=(885.0, -10.0)
        )

        add_half_node.inputs[1].default_value=(0.5,-0.5,0.0)

        # Multiply Detail UV Scale
        scale_attribute_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEATTRIBUTE.value,
            location=(680.0, -100.0)
        )
        scale_attribute_node.attribute_type = "OBJECT"
        scale_attribute_node.attribute_name = "scale"

        multiply_object_scale_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEVECTORMATH.value,
            operation=MSFS2024_NodeMathOpe.MULTIPLY.value,
            location=(880.0, -50.0)
        )

        multiply_detail_uv_scale_node = add_node(
            nodes=group.nodes,
            name="Multiply (UV * Detail Scale)",
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEVECTORMATH.value,
            operation=MSFS2024_NodeMathOpe.MULTIPLY.value,
            location=(1080.0, -35.0)
        )

        uv2_map_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEUVMAP.value,
            location=(885.0, -100.0)
        )
        uv2_map_node.uv_map =DefaultUV.UV2_NAME

        # endregion

        # region Links
        link(group.links, uv_map_node.outputs[0], subtract_half_node.inputs[0])
        link(group.links, subtract_half_node.outputs[0], uv_rotate_node.inputs[0])
        link(group.links, input_node.outputs[4], to_rad_node.inputs[0])
        link(group.links, to_rad_node.outputs[0], uv_rotate_node.inputs[3])

        link(group.links, uv_rotate_node.outputs[0], separate_uv_node.inputs[0])

        link(group.links, separate_uv_node.outputs[0], multiply_tiling_u_node.inputs[0])
        link(group.links, separate_uv_node.outputs[1], multiply_tiling_v_node.inputs[0])

        link(group.links, multiply_tiling_u_node.outputs[0], add_offset_u_node.inputs[0])
        link(group.links, multiply_tiling_v_node.outputs[0], sub_offset_v_node.inputs[0])

        link(group.links, add_offset_u_node.outputs[0], combine_uv_node.inputs[0])
        link(group.links, sub_offset_v_node.outputs[0], combine_uv_node.inputs[1])

        link(group.links, input_node.outputs[0], add_offset_u_node.inputs[1])
        link(group.links, input_node.outputs[1], sub_offset_v_node.inputs[1])
        link(group.links, input_node.outputs[2], multiply_tiling_u_node.inputs[1])
        link(group.links, input_node.outputs[3], multiply_tiling_v_node.inputs[1])

        link(group.links, combine_uv_node.outputs[0], add_half_node.inputs[0])
        link(group.links, add_half_node.outputs[0], output_node.inputs[0])

        link(group.links, input_node.outputs[5], multiply_object_scale_node.inputs[0])
        link(group.links, scale_attribute_node.outputs[1], multiply_object_scale_node.inputs[1])
        link(group.links, multiply_object_scale_node.outputs[0], multiply_detail_uv_scale_node.inputs[1])

        link(group.links, add_half_node.outputs[0], multiply_detail_uv_scale_node.inputs[0])
        link(group.links, multiply_detail_uv_scale_node.outputs[0], output_node.inputs[1])
        link(group.links, uv2_map_node.outputs[0], output_node.inputs[2])
        # endregion

    def create_orm_shadernode_group(self, group):
        input_node = add_node(
            nodes=group.nodes,
            name=MSFS2024_NodesSockets.GROUPINPUT.value,
            type_node=MSFS2024_GroupTypes.NODEGROUPINPUT.value,
            location=(-220.0, 0.0),
            width=300.0,
            hidden=False
        )

        output_node = add_node(
            nodes=group.nodes,
            name=MSFS2024_NodesSockets.GROUPOUTPUT.value,
            type_node=MSFS2024_GroupTypes.NODEGROUPOUTPUT.value,
            location=(2725.0, 0.0),
            width=200.0,
            hidden=False
        )

        # region Inputs
        # Metallic Scale
        _ = add_group_input(
            group=group,
            input_name=MSFS2024_ShaderNodes.METALLICSCALE.value,
            input_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
        )

        # Roughness Scale
        _ = add_group_input(
            group=group,
            input_name=MSFS2024_ShaderNodes.ROUGHNESSSCALE.value,
            input_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
        )

        # Comp (OMR) Texture
        omr_tex_input = add_group_input(
            group=group,
            input_name=MSFS2024_ShaderNodes.COMPTEX.value,
            input_type=MSFS2024_GroupTypes.NODESOCKETCOLOR.value
        )
        omr_tex_input.default_value = (1.0, 1.0, 1.0, 1.0)

        # Detail Comp (OMR) Texture
        omr_detail_tex_input = add_group_input(
            group=group,
            input_name=MSFS2024_ShaderNodes.DETAILCOMPTEX.value,
            input_type=MSFS2024_GroupTypes.NODESOCKETCOLOR.value
        )
        omr_detail_tex_input.default_value = (1.0, 1.0, 1.0, 1.0)

        enable_detail_input = add_group_input(
            group=group,
            input_name="Enable Detail",
            input_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
        )
        enable_detail_input.default_value = 0

        mask_input = add_group_input(
            group=group,
            input_name="Mask",
            input_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
        )
        mask_input.default_value = 0

        switch_to_blend_mode_input = add_group_input(
            group=group,
            input_name=MSFS2024_NodesSockets.SWITCHTOBLENDMODE.value,
            input_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
        )
        switch_to_blend_mode_input.default_value = 0
        # endregion

        # region Outputs
        # Metallic Scale
        _ = add_group_output(
            group=group,
            output_name=MSFS2024_ShaderNodes.METALLICSCALE.value,
            output_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
        )

        # Roughness Scale
        _ = add_group_output(
            group=group,
            output_name=MSFS2024_ShaderNodes.ROUGHNESSSCALE.value,
            output_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
        )

        # Occlusion Scale
        _ = add_group_output(
            group=group,
            output_name="Occlusion Scale",
            output_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
        )
        # endregion

        # region Detail Mode
        detail_mask_frame = add_node(
            nodes=group.nodes,
            name=MSFS2024_FrameNodes.DETAILMASKFRAME.frame_name(),
            type_node=MSFS2024_ShaderNodeTypes.NODEFRAME.value,
            color=MSFS2024_FrameNodes.DETAILMASKFRAME.color()
        )

        unpack_detail_orm_node = msfs_material_nodes_library.add_unpack_detail_orm_node(
            node_tree=group,
            location=(195, 195.0),
            frame=detail_mask_frame
        )

        detail_mix_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMIXRGB.value,
            location=(575.0, 90.0),
            frame=detail_mask_frame
        )
        detail_mix_node.inputs[1].default_value = (0.0,0.0,0.0,1.0)

        detail_base_separate_color_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODESEPARATECOLOR.value,
            location=(830, 175),
            width=300,
            frame=detail_mask_frame
        )

        detail_separate_color_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODESEPARATECOLOR.value,
            location=(830, 86),
            width=300,
            frame=detail_mask_frame
        )

        detail_roughness_multiply_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
            operation=MSFS2024_NodeMathOpe.MULTIPLY.value,
            location=(1245, 175),
            frame=detail_mask_frame
        )

        detail_metallic_multiply_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
            operation=MSFS2024_NodeMathOpe.MULTIPLY.value,
            location=(1245, 85),
            frame=detail_mask_frame
        )

        detail_ao_add_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
            operation=MSFS2024_NodeMathOpe.ADD.value,
            location=(1525, 271),
            frame=detail_mask_frame
        )
        detail_ao_add_node.use_clamp=True

        detail_roughness_add_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
            operation=MSFS2024_NodeMathOpe.ADD.value,
            location=(1525, 175),
            frame=detail_mask_frame
        )
        detail_roughness_add_node.use_clamp=True

        detail_metallic_add_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
            operation=MSFS2024_NodeMathOpe.ADD.value,
            location=(1525, 85),
            frame=detail_mask_frame
        )
        detail_metallic_add_node.use_clamp=True

        detail_add_combine_color_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODECOMBINECOLOR.value,
            location=(1755, 175),
            frame=detail_mask_frame
        )

        detail_combine_color_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODECOMBINECOLOR.value,
            location=(1675, 425),
            frame=detail_mask_frame
        )
        detail_combine_color_node.inputs[0].default_value = 1

        detail_switch_node = msfs_material_nodes_library.add_switch_node(
            node_tree = group,
            frame=detail_mask_frame,
            location=(2020,175)
        )

        # region Links
        link(group.links, input_node.outputs[2], detail_base_separate_color_node.inputs[0])
        link(group.links, input_node.outputs[3], unpack_detail_orm_node.inputs[0])
        link(group.links, input_node.outputs[5], detail_mix_node.inputs[0])
        link(group.links, unpack_detail_orm_node.outputs[0], detail_mix_node.inputs[2])
        link(group.links, detail_mix_node.outputs[0], detail_separate_color_node.inputs[0])

        link(group.links, detail_base_separate_color_node.outputs[0], detail_ao_add_node.inputs[0])
        link(group.links, detail_base_separate_color_node.outputs[1], detail_roughness_multiply_node.inputs[0])
        link(group.links, detail_base_separate_color_node.outputs[2], detail_metallic_multiply_node.inputs[0])

        link(group.links, input_node.outputs[1], detail_roughness_multiply_node.inputs[1])
        link(group.links, input_node.outputs[0], detail_metallic_multiply_node.inputs[1])

        link(group.links, detail_roughness_multiply_node.outputs[0], detail_roughness_add_node.inputs[0])
        link(group.links, detail_metallic_multiply_node.outputs[0], detail_metallic_add_node.inputs[0])

        link(group.links, detail_separate_color_node.outputs[0], detail_ao_add_node.inputs[1])
        link(group.links, detail_separate_color_node.outputs[1], detail_roughness_add_node.inputs[1])
        link(group.links, detail_separate_color_node.outputs[2], detail_metallic_add_node.inputs[1])

        link(group.links, detail_roughness_multiply_node.outputs[0], detail_combine_color_node.inputs[1])
        link(group.links, detail_metallic_multiply_node.outputs[0], detail_combine_color_node.inputs[2])

        link(group.links, detail_ao_add_node.outputs[0], detail_add_combine_color_node.inputs[0])
        link(group.links, detail_roughness_add_node.outputs[0], detail_add_combine_color_node.inputs[1])
        link(group.links, detail_metallic_add_node.outputs[0], detail_add_combine_color_node.inputs[2])

        link(group.links, input_node.outputs[4], detail_switch_node.inputs[0])
        link(group.links, detail_combine_color_node.outputs[0], detail_switch_node.inputs[1])
        link(group.links, detail_add_combine_color_node.outputs[0], detail_switch_node.inputs[2])        
        # endregion

        # endregion

        # region Blend Mode
        blend_mask_frame = add_node(
            nodes=group.nodes,
            name=MSFS2024_FrameNodes.BLENDMASKFRAME.frame_name(),
            type_node=MSFS2024_ShaderNodeTypes.NODEFRAME.value,
            color=MSFS2024_FrameNodes.BLENDMASKFRAME.color()
        )

        blend_mix_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMIXRGB.value,
            location=(575.0, -175.0),
            frame=blend_mask_frame
        )

        blend_separate_color_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODESEPARATECOLOR.value,
            location=(830, -175),
            width=300,
            frame=blend_mask_frame
        )

        blend_roughness_mult_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
            operation=MSFS2024_NodeMathOpe.MULTIPLY.value,
            location=(1245, -265),
            frame=blend_mask_frame
        )

        blend_metallic_mult_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
            operation=MSFS2024_NodeMathOpe.MULTIPLY.value,
            location=(1245, -335),
            frame=blend_mask_frame
        )

        blend_combine_color_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODECOMBINECOLOR.value,
            location=(1738, -239),
            frame=blend_mask_frame
        )

        # region Links
        link(group.links, input_node.outputs[2], blend_mix_node.inputs[2])
        link(group.links, input_node.outputs[3], blend_mix_node.inputs[1])
        link(group.links, input_node.outputs[5], blend_mix_node.inputs[0])

        link(group.links, blend_mix_node.outputs[0], blend_separate_color_node.inputs[0])

        link(group.links, blend_separate_color_node.outputs[1], blend_roughness_mult_node.inputs[0])
        link(group.links, blend_separate_color_node.outputs[2], blend_metallic_mult_node.inputs[0])

        link(group.links, input_node.outputs[1], blend_roughness_mult_node.inputs[1])
        link(group.links, input_node.outputs[0], blend_metallic_mult_node.inputs[1])

        link(group.links, blend_separate_color_node.outputs[0], blend_combine_color_node.inputs[0])
        link(group.links, blend_roughness_mult_node.outputs[0], blend_combine_color_node.inputs[1])
        link(group.links, blend_metallic_mult_node.outputs[0], blend_combine_color_node.inputs[2])
        # endregion

        # endregion

        # Switch between detail and blend mode
        mode_switch_node=msfs_material_nodes_library.add_switch_node(
            group,
            location=(2270,0)
        )

        switch_separate_color_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODESEPARATECOLOR.value,
            location=(2495, -65),
        )

        # region Links
        link(group.links, input_node.outputs[6], mode_switch_node.inputs[0])
        link(group.links, detail_switch_node.outputs[0], mode_switch_node.inputs[1])
        link(group.links, blend_combine_color_node.outputs[0], mode_switch_node.inputs[2])

        link(group.links, mode_switch_node.outputs[0], switch_separate_color_node.inputs[0])
        link(group.links, switch_separate_color_node.outputs[0], output_node.inputs[2])
        link(group.links, switch_separate_color_node.outputs[1], output_node.inputs[1])
        link(group.links, switch_separate_color_node.outputs[2], output_node.inputs[0])
        # endregion

    def create_emissive_shadernode_group(self, group):
        input_node = add_node(
            nodes=group.nodes,
            name=MSFS2024_NodesSockets.GROUPINPUT.value,
            type_node=MSFS2024_GroupTypes.NODEGROUPINPUT.value,
            width=200.0,
            hidden=False
        )

        output_node = add_node(
            nodes=group.nodes,
            name=MSFS2024_NodesSockets.GROUPOUTPUT.value,
            type_node=MSFS2024_GroupTypes.NODEGROUPOUTPUT.value,
            location=(735.0, 0.0),
            width=200.0,
            hidden=False
        )

        # region Common Nodes
        ## Emissive Multiplier
        emissive_color_mul_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMIXRGB.value,
            blend_type = MSFS2024_NodeMathOpe.MULTIPLY.value,
            location=(250.0, -75.0)
        )
        emissive_color_mul_node.inputs[0].default_value = 1.0
        emissive_scale_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMIXRGB.value,
            blend_type = MSFS2024_NodeMathOpe.MULTIPLY.value,
            location=(450.0, -15.0)
        )
        emissive_scale_node.inputs[0].default_value = 1.0
        # endregion

        # region Inputs
        # Emissive Scale
        _ = add_group_input(
            group=group,
            input_name=MSFS2024_ShaderNodes.EMISSIVESCALE.value,
            input_type=MSFS2024_GroupTypes.NODESOCKETCOLOR.value
        )

        # Emissive Color
        _ = add_group_input(
            group=group,
            input_name=MSFS2024_ShaderNodes.EMISSIVECOLOR.value,
            input_type=MSFS2024_GroupTypes.NODESOCKETCOLOR.value
        )

        # Emissive Texture
        emissive_tex_input = add_group_input(
            group=group,
            input_name=MSFS2024_ShaderNodes.EMISSIVETEX.value,
            input_type=MSFS2024_GroupTypes.NODESOCKETCOLOR.value
        )
        emissive_tex_input.default_value = (1.0, 1.0, 1.0, 1.0)
        # endregion

        # region Outputs
        # Emissive Color
        _ = add_group_output(
            group=group,
            output_name=MSFS2024_ShaderNodes.EMISSIVECOLOR.value,
            output_type=MSFS2024_GroupTypes.NODESOCKETCOLOR.value
        )
        # endregion

        # region Links
        link(group.links, input_node.outputs[1], emissive_color_mul_node.inputs[1])
        link(group.links, input_node.outputs[2], emissive_color_mul_node.inputs[2])

        link(group.links, input_node.outputs[0], emissive_scale_node.inputs[1])
        link(group.links, emissive_color_mul_node.outputs[0], emissive_scale_node.inputs[2])

        link(group.links, emissive_scale_node.outputs[0], output_node.inputs[0])
        # endregion

    def create_normal_shadernode_group(self, group):
        ## Group Nodes
        input_node = add_node(
            nodes=group.nodes,
            name=MSFS2024_NodesSockets.GROUPINPUT.value,
            type_node=MSFS2024_GroupTypes.NODEGROUPINPUT.value,
            width=200.0,
            hidden=False
        )

        output_node = add_node(
            nodes=group.nodes,
            name=MSFS2024_NodesSockets.GROUPOUTPUT.value,
            type_node=MSFS2024_GroupTypes.NODEGROUPOUTPUT.value,
            location=(2125.0, 0.0),
            width=200.0,
            hidden=False
        )

        # region Inputs
        # Normal Scale Input
        normal_scale_input = add_group_input(
            group=group,
            input_name=MSFS2024_ShaderNodes.NORMALSCALE.value,
            input_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
        )
        normal_scale_input.default_value = 1.0

        # Normal Texture Input
        normal_tex_input = add_group_input(
            group=group,
            input_name=MSFS2024_ShaderNodes.NORMALTEX.value,
            input_type=MSFS2024_GroupTypes.NODESOCKETCOLOR.value
        )
        normal_tex_input.default_value = (0.5, 0.5, 1.0, 1.0)

        # Detail Normal Scale Input
        detail_normal_scale_input = add_group_input(
            group=group,
            input_name=MSFS2024_ShaderNodes.DETAILNORMALSCALE.value,
            input_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
        )
        detail_normal_scale_input.default_value = 1.0

        # Detail Normal Texture Input
        detail_normal_tex_input = add_group_input(
            group=group,
            input_name=MSFS2024_ShaderNodes.DETAILNORMALTEX.value,
            input_type=MSFS2024_GroupTypes.NODESOCKETCOLOR.value
        )
        detail_normal_tex_input.default_value = (0.5, 0.5, 1.0, 1.0)

        # Enable Detail
        enable_detail_input = add_group_input(
            group=group,
            input_name="Enable Detail",
            input_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
        )
        enable_detail_input.default_value = 0

        # Mask Input
        mask_input = add_group_input(
            group=group,
            input_name="Mask",
            input_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
        )
        mask_input.default_value = 0

        # Switch blend mode
        switch_to_blend_mode_input = add_group_input(
            group=group,
            input_name=MSFS2024_NodesSockets.SWITCHTOBLENDMODE.value,
            input_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
        )
        switch_to_blend_mode_input.default_value = 0
        # endregion

        # region Outputs
        # Normal Color
        _ = add_group_output(
            group=group,
            output_name="Normal",
            output_type=MSFS2024_GroupTypes.NODESOCKETCOLOR.value
        )
        # endregion

        # region Common Nodes
        # Invert Y Channel in order to obtain OpenGl normal format
        rgb_curves_node = add_node(
            nodes=group.nodes,
            name="Invert Y",
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODERGBCURVE.value,
            location=(360.0,0)
        )
        curve_mapping = rgb_curves_node.mapping.curves[1]
        curve_mapping.points[0].location=(0.0, 1.0)
        curve_mapping.points[1].location=(1.0, 0.0)

        ## Normal Map Sampler
        normal_map_sampler_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODENORMALMAP.value,
            location=(575.0, 0)
        )

        rgb_curves_detail_node = add_node(
            nodes=group.nodes,
            name="Invert Y",
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODERGBCURVE.value,
            location=(365.0, -95.0)
        )

        curve_mapping = rgb_curves_detail_node.mapping.curves[1]
        curve_mapping.points[0].location=(0.0, 1.0)
        curve_mapping.points[1].location=(1.0, 0.0)

        ## Detail Normal Map Sampler
        normal_map_sampler_detail_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODENORMALMAP.value,
            location=(578.0, -90.0)
        )

        # region Link
        link(group.links, input_node.outputs[0], normal_map_sampler_node.inputs[0])
        link(group.links, input_node.outputs[1], rgb_curves_node.inputs[1])

        link(group.links, rgb_curves_node.outputs[0], normal_map_sampler_node.inputs[1])

        link(group.links, input_node.outputs[2], normal_map_sampler_detail_node.inputs[0])
        link(group.links, input_node.outputs[3], rgb_curves_detail_node.inputs[1])

        link(group.links, rgb_curves_detail_node.outputs[0], normal_map_sampler_detail_node.inputs[1])
        # endregion

        # endregion

        # region Detail Mode
        detail_mask_frame = add_node(
            nodes=group.nodes,
            name=MSFS2024_FrameNodes.DETAILMASKFRAME.frame_name(),
            type_node=MSFS2024_ShaderNodeTypes.NODEFRAME.value,
            color=MSFS2024_FrameNodes.DETAILMASKFRAME.color()
        )

        detail_neutral_normal_node = add_node(
            nodes=group.nodes,
            name="Neutral Normal",
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODENORMALMAP.value,
            location=(885.0, 70.0),
            frame=detail_mask_frame
        )

        detail_mix_normal_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMIXRGB.value,
            location=(1060.0, 115.0),
            frame=detail_mask_frame
        )

        detail_add_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEVECTORMATH.value,
            operation=MSFS2024_NodeMathOpe.ADD.value,
            location=(1240, 110),
            frame=detail_mask_frame
        )

        detail_switch_node = msfs_material_nodes_library.add_switch_node(
            node_tree = group,
            location=(1485,225),
            frame=detail_mask_frame
        )

        # region Links
        link(group.links, input_node.outputs[5], detail_mix_normal_node.inputs[0])
        link(group.links, detail_neutral_normal_node.outputs[0], detail_mix_normal_node.inputs[1])
        link(group.links, normal_map_sampler_detail_node.outputs[0], detail_mix_normal_node.inputs[2])

        link(group.links, normal_map_sampler_node.outputs[0], detail_add_node.inputs[0])
        link(group.links, detail_mix_normal_node.outputs[0], detail_add_node.inputs[1])

        link(group.links, input_node.outputs[4], detail_switch_node.inputs[0])
        link(group.links, normal_map_sampler_node.outputs[0], detail_switch_node.inputs[1])
        link(group.links, detail_add_node.outputs[0], detail_switch_node.inputs[2])
        # endregion

        # endregion

        # region Blend Mode
        blend_mask_frame = add_node(
            nodes=group.nodes,
            name=MSFS2024_FrameNodes.BLENDMASKFRAME.frame_name(),
            type_node=MSFS2024_ShaderNodeTypes.NODEFRAME.value,
            color=MSFS2024_FrameNodes.BLENDMASKFRAME.color()
        )

        blend_mix_normal_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMIXRGB.value,
            location=(1060.0, -200.0),
            frame=blend_mask_frame
        )

        # region Links
        link(group.links, input_node.outputs[5], blend_mix_normal_node.inputs[0])
        link(group.links, normal_map_sampler_detail_node.outputs[0], blend_mix_normal_node.inputs[1])
        link(group.links, normal_map_sampler_node.outputs[0], blend_mix_normal_node.inputs[2])
        # endregion

        # endregion

        # Switch between detail and blend mode
        mode_switch_node = msfs_material_nodes_library.add_switch_node(
            group,
            location=(1850,55)
        )

        # region Links
        link(group.links, input_node.outputs[6], mode_switch_node.inputs[0])
        link(group.links, detail_switch_node.outputs[0], mode_switch_node.inputs[1])
        link(group.links, blend_mix_normal_node.outputs[0], mode_switch_node.inputs[2])
        link(group.links, mode_switch_node.outputs[0], output_node.inputs[0])
        # endregion

    def create_apply_ao_group(self, group):
        input_node = add_node(
            nodes=group.nodes,
            name=MSFS2024_NodesSockets.GROUPINPUT.value,
            type_node=MSFS2024_GroupTypes.NODEGROUPINPUT.value,
            width=200.0,
            hidden=False
        )

        output_node = add_node(
            nodes=group.nodes,
            name=MSFS2024_NodesSockets.GROUPOUTPUT.value,
            type_node=MSFS2024_GroupTypes.NODEGROUPOUTPUT.value,
            location=(1776.0, 0.0),
            width=200.0,
            hidden=False
        )

        # region Inputs
        color_input = add_group_input(
            group=group,
            input_name="Color",
            input_type=MSFS2024_GroupTypes.NODESOCKETCOLOR.value
        )
        color_input.default_value = (1,1,1,1)

        ao_input = add_group_input(
            group=group,
            input_name="AO",
            input_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
        )
        ao_input.default_value = 1.0

        ao_uv2_input = add_group_input(
            group=group,
            input_name="AO UV2",
            input_type=MSFS2024_GroupTypes.NODESOCKETCOLOR.value
        )
        ao_uv2_input.default_value = (1.0, 1.0, 1.0, 1.0)
        # endregion

        # region Outputs
        _ = add_group_output(
            group=group,
            output_name="Color",
            output_type=MSFS2024_GroupTypes.NODESOCKETCOLOR.value
        )
        # endregion

        # region Common Nodes
        shadow_mask_frame = add_node(
            nodes=group.nodes,
            name="Shadow Mask",
            type_node=MSFS2024_ShaderNodeTypes.NODEFRAME.value,
            color=(0.3, 0.3, 0.3)
        )

        diffuse_bsdf_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEBSDFDIFFUSE.value,
            location=(168.0, 130.0),
            frame=shadow_mask_frame
        )

        shader_to_rgb_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODESHADERTORGB.value,
            location=(380.0, 130.0),
            frame=shadow_mask_frame
        )

        color_ramp_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEVALTORGB.value,
            location=(575.0, 124.0),
            frame=shadow_mask_frame
        )

        color_ramp_node.color_ramp.elements[0].position = 1
        color_ramp_node.color_ramp.elements[0].color = (0,0,0,1) 
        color_ramp_node.color_ramp.elements[1].position = 0.475 
        color_ramp_node.color_ramp.elements[1].color = (1,1,1,1) 

        mix_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMIXRGB.value,
            location=(905, 75)
        )

        separate_color_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODESEPARATECOLOR.value,
            location=(220, -100)
        )

        multiply_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEVECTORMATH.value,
            operation=MSFS2024_NodeMathOpe.MULTIPLY.value,
            location=(432, -50)
        )

        multiply_color_node = add_node(
            nodes=group.nodes,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMIXRGB.value,
            blend_type = MSFS2024_NodeBlendTypes.MULTIPLY.value,
            location=(658, -10)
        )
        multiply_color_node.inputs[0].default_value = 1.0 #factor
        # endregion

        # region Links
        link(group.links, diffuse_bsdf_node.outputs[0], shader_to_rgb_node.inputs[0])
        link(group.links, shader_to_rgb_node.outputs[0], color_ramp_node.inputs[0])
        link(group.links, color_ramp_node.outputs[0], mix_node.inputs[0]) # Mix node factor
        link(group.links, mix_node.outputs[0], output_node.inputs[0])

        link(group.links, input_node.outputs[2], separate_color_node.inputs[0])
        link(group.links, input_node.outputs[1], multiply_node.inputs[0])
        link(group.links, separate_color_node.outputs[0], multiply_node.inputs[1])

        link(group.links, input_node.outputs[0], multiply_color_node.inputs[1]) # Mix A input
        link(group.links, multiply_node.outputs[0], multiply_color_node.inputs[2]) # Mix B input

        link(group.links, input_node.outputs[0], mix_node.inputs[1])
        link(group.links, multiply_color_node.outputs[0], mix_node.inputs[2])
        # endregion

    # region Panel
    @staticmethod
    def draw_base_texture_set_operator( layout, material):
        ope = layout.operator(MSFS2024_OT_SetPbrTextureSet.bl_idname,icon="IMAGE_DATA")
        ope.material_name = material.name
        return ope

    # endregion
    # endregion

    # endregion
