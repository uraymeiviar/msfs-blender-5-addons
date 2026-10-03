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

from enum import Enum
from typing import Any

from ..utils.msfs_material_utils import MSFS2024_MaterialProperties

# region Constants
class MSFS2024_ShaderNodeTypes(Enum):
    NODEREROUTE = "NodeReroute"
    SHADERNODEGROUP = "ShaderNodeGroup"
    SHADERNODETREE = "ShaderNodeTree"
    SHADERNODEOUTPUTMATERIAL = "ShaderNodeOutputMaterial"
    NODEFRAME = "NodeFrame"
    SHADERNODEMIX = "ShaderNodeMix" # This one is not compatible in 3.3
    SHADERNODEMIXRGB = "ShaderNodeMixRGB" 
    NODEGROUPOUTPUT = "NodeGroupOutput"
    NODEGROUPINPUT = "NodeGroupInput"
    SHADENODEBSDFPRINCIPLED = "ShaderNodeBsdfPrincipled"
    SHADERNODETEXIMAGE = "ShaderNodeTexImage"
    SHADERNODEVERTEXCOLOR = "ShaderNodeVertexColor"
    SHADERNODEMATH = "ShaderNodeMath"
    SHADERNODEUVMAP = "ShaderNodeUVMap"
    SHADERNODECOMBINEXYZ = "ShaderNodeCombineXYZ"
    SHADERNODECOMBINECOLOR = "ShaderNodeCombineColor"
    SHADERNODEVECTORMATH = "ShaderNodeVectorMath"
    # SHADERNODESEPARATERGB = "ShaderNodeSeparateRGB" # This is now obsolete
    SHADERNODESEPARATECOLOR = "ShaderNodeSeparateColor"
    SHADERNODESEPARATEXYZ = "ShaderNodeSeparateXYZ"
    SHADERNODENORMALMAP = "ShaderNodeNormalMap"
    SHADERNODERGB = "ShaderNodeRGB"
    SHADERNODEVALUE = "ShaderNodeValue"
    SHADERNODERGBCURVE = "ShaderNodeRGBCurve"
    SHADERNODEMAPRANGE = "ShaderNodeMapRange"
    SHADERNODEVECTORROTATE = "ShaderNodeVectorRotate"
    SHADERNODECLAMP = "ShaderNodeClamp"
    SHADERNODEBSDFDIFFUSE = "ShaderNodeBsdfDiffuse"
    SHADERNODESHADERTORGB = "ShaderNodeShaderToRGB"
    SHADERNODEVALTORGB = "ShaderNodeValToRGB" # Color Ramp
    SHADERNODEATTRIBUTE = "ShaderNodeAttribute"

class MSFS2024_NodeDataTypes(Enum):
    FLOAT = "FLOAT"
    VECTOR = "VECTOR"
    FLOAT_VECTOR = "FLOAT_VECTOR"
    COLOR = "COLOR"
    RGBA = "RGBA"

class MSFS2024_NodeBlendTypes(Enum):
    MIX = "MIX"
    DARKEN = "DARKEN"
    MULTIPLY = "MULTIPLY"
    BURN = "BURN"
    LIGHTEN = "LIGHTEN"
    SCREEN = "SCREEN"
    DODGE = "DODGE"
    ADD = "ADD"
    OVERLAY = "OVERLAY"
    SOFT_LIGHT = "SOFT_LIGHT"
    LINEAR_LIGHT = "LINEAR_LIGHT"
    DIFFERENCE = "DIFFERENCE"
    EXCLUSION = "EXCLUSION"
    SUBTRACT = "SUBTRACT"
    DIVIDE = "DIVIDE"
    HUE = "HUE"
    SATURATION = "SATURATION"
    COLOR = "COLOR"
    VALUE = "VALUE"

class MSFS2024_NodeMathOpe(Enum):
    # Arithmetic
    ADD = "ADD"
    SUBTRACT = "SUBTRACT"
    MULTIPLY = "MULTIPLY"
    DIVIDE = "DIVIDE"
    MULTIPLY_ADD = "MULTIPLY_ADD"
    POWER = "POWER"
    LOGARITHM = "LOGARITHM"
    SQRT = "SQRT"
    INVERSE_SQRT = "INVERSE_SQRT"
    ABSOLUTE = "ABSOLUTE"
    EXPONENT = "EXPONENT"
    
    # Comparison
    MINIMUM = "MINIMUM"
    MAXIMUM = "MAXIMUM"
    LESS_THAN = "LESS_THAN"
    GREATER_THAN = "GREATER_THAN"
    SIGN = "SIGN"
    COMPARE = "COMPARE"
    SMOOTH_MIN = "SMOOTH_MIN"
    SMOOTH_MAX = "SMOOTH_MAX"
    
    # Rounding
    ROUND = "ROUND"
    FLOOR = "FLOOR"
    CEIL = "CEIL"
    TRUNC = "TRUNC"
    FRACT = "FRACT"
    MODULO = "MODULO"
    FLOORED_MODULO = "FLOORED_MODULO"
    WRAP = "WRAP"
    SNAP = "SNAP"
    PINGPONG = "PINGPONG"
    
    # Trigonometric
    SINE = "SINE"
    COSINE = "COSINE"
    TANGENT = "TANGENT"
    ARCSINE = "ARCSINE"
    ARCCOSINE = "ARCCOSINE"
    ARCTANGENT = "ARCTANGENT"
    ARCTAN2 = "ARCTAN2"
    SINH = "SINH"
    COSH = "COSH"
    TANH = "TANH"
    
    # Conversion
    RADIANS = "RADIANS"
    DEGREES = "DEGREES"

class MSFS2024_MapRangeType(Enum):
    LINEAR = "LINEAR"
    STEPPED = "STEPPED"
    SMOOTHSTEP = "SMOOTHSTEP"
    SMOOTHERSTEP = "SMOOTHERSTEP"

class MSFS2024_FrameNodes(Enum):
    MASKFRAME = "Mask Frame", (0.5, 0.5, 0.5)
    DETAILMASKFRAME = "Detail", (0.2, 0.35, 0.2)
    BLENDMASKFRAME = "Blend", (0.35, 0.2, 0.2)
    UVFRAME = "UVs Frame", (0.3, 0.3, 0.5)
    OMRFRAME = "Occlusion Metallic Roughness Frame", (0.1, 0.4, 0.6)
    EMISSIVEFRAME = "Emissive Frame", (0.1, 0.5, 0.3)
    NORMALFRAME = "Normal Frame", (0.5, 0.25, 0.25)
    ANISOTROPICFRAME = "Anisotropic Frame", (0.35, 0.6, 0.1)
    PARALLAXFRAME = "Parallax Frame", (0.5, 0.1, 0.3)
    CLEARCOATFRAME = "Clearcoat Frame", (0.6, 0.2, 0.1)
    BASECOLORINPUTSFRAME = "Base Color Inputs Frame", (0.5, 0.1, 0.0)
    ALPHAINPUTSFRAME = "Alpha Inputs Frame", (0.6, 0.6, 0.0)
    DECALFRAME = "Decal Frame", (0.3, 0.6, 0.0)
    DECALBLENDMASKEDFRAME = "Decal BlendMasked Frame", (0.45, 0.6, 0.1)
    DECALFROSTEDFRAME = "Decal Frosted Frame", (0.1, 0.3, 0.6)
    FROSTFRAME = "Frost", (0.4, 0.3, 0.6)
    FROSTTINTFRAME = "Frost Tint", (0.4, 0.5, 0.6)

    def frame_name(self) -> str:
        return self.value[0]

    def color(self) -> tuple[float, float, float]:
        return self.value[1]

class MSFS2024_NodesSockets(Enum):
    """
        Miscellaneous nodes, Inputs/Outputs names.
    """
    VERTEXCOLOR = "Vertex Color"
    SWITCHTOBLENDMODE = "Switch To Blend Mode"
    GROUPINPUT = "Group Input"
    GROUPOUTPUT = "Group Output"

class MSFS2024_ShaderNodes(Enum):
    """
        Main Graph Nodes Names.
    """

    #region common
    BASECOLORTEX = MSFS2024_MaterialProperties.BASECOLORTEXTURE.property_name()
    BASECOLORRGB = MSFS2024_MaterialProperties.BASECOLOR.property_name()

    BASECOLORA = "Base Color (A)"

    COMPTEX = MSFS2024_MaterialProperties.OMRTEXTURE.property_name()
    ROUGHNESSSCALE = MSFS2024_MaterialProperties.ROUGHNESSSCALE.property_name()
    METALLICSCALE = MSFS2024_MaterialProperties.METALLICSCALE.property_name()

    EMISSIVETEX = MSFS2024_MaterialProperties.EMISSIVETEXTURE.property_name()
    EMISSIVECOLOR = MSFS2024_MaterialProperties.EMISSIVECOLOR.property_name()
    EMISSIVESCALE = MSFS2024_MaterialProperties.EMISSIVESCALE.property_name()

    NORMALTEX = MSFS2024_MaterialProperties.NORMALTEXTURE.property_name()
    NORMALSCALE = MSFS2024_MaterialProperties.NORMALSCALE.property_name()

    DETAILCOLORTEX = MSFS2024_MaterialProperties.DETAILCOLORTEXTURE.property_name()
    DETAILCOMPTEX = MSFS2024_MaterialProperties.DETAILOMRTEXTURE.property_name()
    DETAILNORMALTEX = MSFS2024_MaterialProperties.DETAILNORMALTEXTURE.property_name()
    DETAILNORMALSCALE = MSFS2024_MaterialProperties.DETAILNORMALSCALE.property_name()

    OCCLUSIONUV2TEX = MSFS2024_MaterialProperties.OCCLUSIONUV2.property_name()

    ALPHACUTOFF = MSFS2024_MaterialProperties.ALPHACUTOFF.property_name()

    BLENDMASKTEX = MSFS2024_MaterialProperties.BLENDMASKTEXTURE.property_name()
    DETAILBLENDMASKTHRESHOLD = MSFS2024_MaterialProperties.DETAILBLENDTHRESHOLD.property_name()
    #endregion

    #region UV
    UVOFFSETU = MSFS2024_MaterialProperties.UVOFFSETU.property_name()
    UVOFFSETV = MSFS2024_MaterialProperties.UVOFFSETV.property_name()
    UVTILINGU = MSFS2024_MaterialProperties.UVTILINGU.property_name()
    UVTILINGV = MSFS2024_MaterialProperties.UVTILINGV.property_name()
    UVROTATION = MSFS2024_MaterialProperties.UVROTATION.property_name()
    DETAILUVSCALE = MSFS2024_MaterialProperties.DETAILUVSCALE.property_name()
    #endregion
    
    BEHINDGLASSTEX = MSFS2024_MaterialProperties.BEHINDGLASSCOLORTEXTURE.property_name()

    #region clearcoat
    CLEARCOATTEX = "Clearcoat" #TODO replace by material properties
    CLEARCOATNORMALTEX = MSFS2024_MaterialProperties.CLEARCOATNORMALTEXTURE.property_name()
    CLEARCOATSEPARATE = "Clearcoat Separate" #TODO replace by material properties
    #endregion

    PRINCIPLEDBSDF = "Principled BSDF Shader"

class MSFS2024_GroupNodes(Enum):
    BLENDMASKGROUP = ".Blend Mask Group"
    BASECOLORGROUP = ".Base Color Group"
    ALPHAGROUP = ".Alpha Group"
    UVGROUP = ".UV Group"
    OMRGROUP = ".Occlusion Metallic Roughness Group"
    EMISSIVEGROUP = ".Emissive Group"
    NORMALGROUP = ".Normal Group"
    APPLYAOGROUP = ".Apply AO Group"
    DECALGROUP = ".Decal Group"
    DECALBLENDMASKEDGROUP = ".Decal BlendMasked Group"
    DECALFROSTEDGROUP = ".Decal Frosted Group"
    
    #region Library group
    LINEARSTEPGROUP = ".LinearStep"
    SWITCHGROUP = ".Switch"
    SQUAREROOTCOLORGROUP = ".Square Root Color"
    UNPACKDETAILORMGROUP = ".Unpack Detail ORM"
    #endregion

class MSFS2024_AnisotropicNodes(Enum):
    ANISOTROPICTEX = "Anisotropic Tex" #TODO material properties equivalent?
    SEPARATEANISOTROPIC = "Separate Anisotropic" #TODO material properties equivalent?

class MSFS2024_DecalNodes(Enum):  
    DECALBLENDMASKTEX = MSFS2024_MaterialProperties.DECALBLENDMASKTEXTURE.property_name()
    DECALBLENDMASKTHRESHOLD = MSFS2024_MaterialProperties.DECALBLENDMASKEDTHRESHOLD.property_name()
    DECALBLENDMASKSHARPNESS = MSFS2024_MaterialProperties.DECALBLENDSHARPNESS.property_name()
    DECALFREEZEFACTOR = MSFS2024_MaterialProperties.DECALFREEZEFACTOR.property_name()

class MSFS2024_PrincipledBSDFInputs(Enum):
    BASECOLOR = "Base Color"
    METALLIC = "Metallic"
    ROUGHNESS = "Roughness"
    ANISOTROPIC = "Anisotropic"
    ANISOTROPICROTATION = "Anisotropic Rotation"
    if bpy.app.version < (4, 2, 0):
        EMISSION = "Emission"
        CLEARCOAT = "Clearcoat"
        CLEARCOATNORMAL = "Clearcoat Normal"
        CLEARCOATROUGHNESS = "Clearcoat Roughness"
        SUBSURFACECOLOR = "Subsurface Color"
    else:
        EMISSION = "Emission Color"
        CLEARCOAT = "Coat Tint"
        CLEARCOATNORMAL = "Coat Normal"
        CLEARCOATROUGHNESS = "Coat Roughness"
    EMISSIONSTRENGTH = "Emission Strength"
    ALPHA = "Alpha"
    NORMAL = "Normal"

class MSFS2024_GroupTypes(Enum):
    NODESOCKETFLOAT = "NodeSocketFloat"
    NODESOCKETINT = "NodeSocketInt"
    NODESOCKETCOLOR = "NodeSocketColor"
    NODESOCKETVECTOR = "NodeSocketVector"
    NODEGROUPINPUT = "NodeGroupInput"
    NODEGROUPOUTPUT = "NodeGroupOutput"

# endregion

# TODO - Move these utility functions to addon utils file
# region Utils
def add_node(
        nodes: list, 
        name: str = "", 
        type_node: str = "", 
        location: tuple[float, float] = (0.0, 0.0), 
        hidden: bool = True, 
        width: float = 150.0, 
        frame: Any = None, 
        color: tuple[float, float, float] = (1.0, 1.0, 1.0), 
        blend_type: str = MSFS2024_NodeBlendTypes.MIX.value, 
        operation: str = MSFS2024_NodeMathOpe.ADD.value
    ) -> Any:
    """ This method creates a new node in the shader node tree

    Args:
        nodes (list) : List of nodes of the shader node tree
        name (str) : Name of the node. Defaults to "".
        type_node (str) : Type of the node we want to create, see : MSFS2024_ShaderNodeTypes. Defaults to "".
        location (tuple) : Position in (x, y) of the node in the shader tree. Defaults to (0.0, 0.0).
        hidden (bool) : Close the node or not in the shader node tree. Defaults to True.
        width (float) : Width of the node in the shader node tree. Defaults to 150.0.
        frame (node) : The frame Node of the new node. Defaults to None.
        color (tuple) : Color of the node in the shader node tree used only for frame nodes. Defaults to (1.0, 1.0, 1.0).
        blend_type (str) : Blend type of shader node Mix RGB node type, see : MSFS2024_ShaderNodeTypes.SHADERNODEMIXRGB. Defaults to "MIX".
        operation (str) : Operation of shader node math type or shader node vector math type, 
            see : MSFS2024_ShaderNodeTypes.SHADERNODEMATH / MSFS2024_ShaderNodeTypes.SHADERNODEVECTORMATH. 
            Defaults to "ADD", Operation items can be found in enum MSFS2024_NodeMathOpe.

    Returns:
        bpy.types.Node : A new node in the shader node tree, returns 'None' if the creation fails
    """
    if nodes is None:
        return None
    
    try:
        node = nodes.new(type_node)
        if name != "":
            node.name = name
            node.label = name
        node.location = location
        node.hide = hidden
        node.width = width
        node.parent = frame
        
        if type_node == MSFS2024_ShaderNodeTypes.NODEFRAME.value:
            node.use_custom_color = True
            node.color = color
        elif type_node in (
            MSFS2024_ShaderNodeTypes.SHADERNODEMIXRGB.value,
            MSFS2024_ShaderNodeTypes.SHADERNODEMIX.value
        ):
            node.blend_type = blend_type
        elif type_node in (
            MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
            MSFS2024_ShaderNodeTypes.SHADERNODEVECTORMATH.value
        ):
            node.operation = operation
        return node
    except ValueError:
        print(f"[ValueError] Node '{name}' of type '{type_node}' mismatch affectation.")
        
    return None

def get_node_by_name(
    nodes: list[Any],
    node_name: str
) -> Any:
    """ Return a node with a given name

    Args:
        nodes (list): List of nodes of the shader node tree
        node_name (str): Name of the node

    Returns:
        bpy.types.Node : The node if exists, 'None' if not.
    """

    if nodes.find(node_name) > -1:
        return nodes[node_name]
    return None

def get_nodes_by_class_name(
    nodes: list[Any],
    class_name: str
) -> list:
    """ Return a node with a given class_name

    Args:
        nodes (list): List of nodes of the shader node tree
        class_name (str): Name of the class of the node

    Returns:
        bpy.types.Node : The node if exists, 'None' if not.
    """

    res = []
    for n in nodes:
        if n.__class__.__name__ == class_name:
            res.append(n)
    return res

def get_or_create_group_by_name(
    group_name: str
) -> tuple[Any, bool]:
    """
    This method create and return a new group if this one is not already created
    Args:
        groups (list(NodeTree)): List of existing Groups
        group_name (str): Name of the groupe

    Returns:
        tuple(bpy.types.NodeTree, Bool): 
            The shader node group that has the given name and if it has been created or not 
    """
    groups = bpy.data.node_groups
    if group_name in groups:
        return (groups[group_name], False)
    
    groups.new(
        group_name,
        MSFS2024_ShaderNodeTypes.SHADERNODETREE.value
    )
    return (groups[group_name], True)

def link(
    links: list[Any], 
    out_node: Any, 
    in_node: Any
) -> Any:
    """ Links an output/input to an input/output

    Args:
        links (bpy.types.NodeLinks): 
            List of the links of the shader node tree or the shader node group tree
        out_node (NodeSocket): Output/Input of a node
        in_node (NodeSocket): Input/Output of a node

    Returns:
        bpy.types.NodeLink : The new link created (could be helpful)
    """
    return links.new(out_node, in_node)

def unlink_node_input(
    links: list[Any],
    node: Any,
    node_input_index: int
) -> None:
    """ Unlink a node input with a given index

    Args:
        links (bpy.types.NodeLinks): 
            List of the links of the shader node tree or the shader node group tree
        node (bpy.types.Node): A shader node
        node_input_index (int): Index of the input to unlink
    """
    for _link in node.inputs[node_input_index].links:
        links.remove(_link)


def unlink_node_input_by_name(
    links: list[Any],
    node: Any,
    input_name: str
) -> None:
    """Unlink a node input by name

    Args:
        links (bpy.types.NodeLinks):
            List of the links of the shader node tree or the shader node group tree
        node (bpy.types.Node): A shader node
        node_input_index (int): Index of the input to unlink
    """
    _input = node.inputs.get(input_name, None)
    if not _input:
        return
    for _link in _input.links:
        links.remove(_link)


def unlink_node_output(
    links: list[Any],
    node: Any,
    output_index: int
) -> None:
    """ Unlink a node output with a given index

    Args:
        links (bpy.types.NodeLinks): 
            List of the links of the shader node tree or the shader node group tree
        node (bpy.types.Node): A shader node
        output_index (int): Index of the output to unlink
    """
    for _link in node.outputs[output_index].links:
        links.remove(_link)

def set_input_value(input_node: Any, value: Any) -> None:
    input_node.default_value = value 

def add_group_input(
    group: Any,
    input_name: str,
    input_type: str
) -> None:
    """ Add an Input to a given group

    Args:
        group (bpy.types.NodeTree): The group
        input_name (str): The name of th input
        input_type (str): 
            The type of the input socket see MSFS2024_GroupTypes

    Returns:
        bpy.types.NodeInputs: The Socket containing the input
    """
    if bpy.app.version < (4, 2, 0):
        return group.inputs.new(input_type, input_name)
    
    interface = group.interface
    return interface.new_socket(
        name=input_name,
        in_out="INPUT",
        socket_type=input_type
    )


def add_group_output(
    group: Any,
    output_name: str,
    output_type: str
) -> None:
    """ Add an Output to a given group

    Args:
        group (bpy.types.NodeTree): The group
        output_name (str): The name of th output
        output_type (str): 
            The type of the output socket see MSFS2024_GroupTypes

    Returns:
        bpy.types.NodeOutputs: The Socket containing the Output
    """
    if bpy.app.version < (4, 2, 0):
        return group.outputs.new(output_type, output_name)

    interface = group.interface
    return interface.new_socket(
        name=output_name,
        in_out="OUTPUT",
        socket_type=output_type
    )


# endregion
