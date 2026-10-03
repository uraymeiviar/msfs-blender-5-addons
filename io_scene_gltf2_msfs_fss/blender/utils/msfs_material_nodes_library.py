"""
Common shader functions library.
"""

from ..utils.msfs_material_nodes_utils import (
    add_node,
    get_or_create_group_by_name,
    add_group_input,
    add_group_output,
    link,
    MSFS2024_GroupNodes,
    MSFS2024_GroupTypes,
    MSFS2024_ShaderNodeTypes,
    MSFS2024_NodesSockets,
    MSFS2024_NodeMathOpe
)

#region Private

def _draw_linear_step(group):
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
        location=(1000.0, 0.0),
        hidden=False
    )
    
    math_substract_node_1 = add_node(
        nodes=group.nodes,
        type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
        operation=MSFS2024_NodeMathOpe.SUBTRACT.value,
        location=(-200, 130)
    )

    math_substract_node_2 = add_node(
        nodes=group.nodes,
        type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
        operation=MSFS2024_NodeMathOpe.SUBTRACT.value,
        location=(-200, -80)
    )
    
    math_divide_node = add_node(
        nodes=group.nodes,
        type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
        operation=MSFS2024_NodeMathOpe.DIVIDE.value,
        location=(20, 60)
    )

    clamp_node = add_node(
        nodes=group.nodes,
        type_node=MSFS2024_ShaderNodeTypes.SHADERNODECLAMP.value,
        location=(220, 75)
    )

    #region Inputs
    low_input = add_group_input(
        group=group, 
        input_name="low",
        input_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
    )
    low_input.default_value = 0.0
    
    high_input = add_group_input(
        group=group, 
        input_name="high",
        input_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
    )
    high_input.default_value = 1.0

    value_input = add_group_input(
        group=group, 
        input_name="value",
        input_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
    )
    value_input.default_value = 1.0
    #endregion

    #region Outputs
    _ = add_group_output(
        group=group,
        output_name="Result",
        output_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
    )
    #endregion

    #region Links
    link(group.links, input_node.outputs[0], math_substract_node_1.inputs[1])
    link(group.links, input_node.outputs[2], math_substract_node_1.inputs[0])

    link(group.links, input_node.outputs[0], math_substract_node_2.inputs[1])
    link(group.links, input_node.outputs[1], math_substract_node_2.inputs[0])

    link(group.links, math_substract_node_1.outputs[0], math_divide_node.inputs[0])
    link(group.links, math_substract_node_2.outputs[0], math_divide_node.inputs[1])

    link(group.links, math_divide_node.outputs[0], clamp_node.inputs[0])

    link(group.links, clamp_node.outputs[0], output_node.inputs[0])
    #endregion


def _draw_switch(group):
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
        location=(1000.0, 0.0),
        hidden=False
    )
    
    compare_math_node = add_node(
        nodes=group.nodes,
        type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
        operation=MSFS2024_NodeMathOpe.COMPARE.value,
        location=(225, 15)
    )
    compare_math_node.inputs[1].default_value = 1.0 #value
    compare_math_node.inputs[2].default_value = 0.0 #epsilon
    
    mix_node = add_node(
        nodes=group.nodes,
        type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMIXRGB.value,
        location=(575, -55)
    )

    #region Inputs
    switch_input = add_group_input(
        group=group, 
        input_name="switch",
        input_type=MSFS2024_GroupTypes.NODESOCKETFLOAT.value
    )
    switch_input.default_value = 0.0
    
    false_input = add_group_input(
        group=group, 
        input_name="false",
        input_type=MSFS2024_GroupTypes.NODESOCKETCOLOR.value
    )
    false_input.default_value = (1.0, 1.0, 1.0, 1.0)
    
    true_input = add_group_input(
        group=group, 
        input_name="true",
        input_type=MSFS2024_GroupTypes.NODESOCKETCOLOR.value
    )
    true_input.default_value = (1.0, 1.0, 1.0, 1.0)
    #endregion

    #region Outputs
    _ = add_group_output(
        group=group,
        output_name="output",
        output_type=MSFS2024_GroupTypes.NODESOCKETCOLOR.value
    )
    #endregion

    #region Links
    link(group.links, input_node.outputs[0], compare_math_node.inputs[0])#switch
    link(group.links, input_node.outputs[1], mix_node.inputs[1])#false
    link(group.links, input_node.outputs[2], mix_node.inputs[2])#true
    
    link(group.links, compare_math_node.outputs[0], mix_node.inputs[0])#factor

    link(group.links, mix_node.outputs[0], output_node.inputs[0])
    #endregion


def _draw_sqrt_color(group):
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
        location=(770.0, 0.0),
        hidden=False
    )
    
    separate_color_node = add_node(
        nodes=group.nodes,
        type_node=MSFS2024_ShaderNodeTypes.SHADERNODESEPARATECOLOR.value,
        location=(215, 66)
    )

    square_root_red_node = add_node(
        nodes=group.nodes,
        type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
        operation=MSFS2024_NodeMathOpe.SQRT.value,
        location=(410, 55)
    )
    
    square_root_blue_node = add_node(
        nodes=group.nodes,
        type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
        operation=MSFS2024_NodeMathOpe.SQRT.value,
        location=(410, 0)
    )
    
    square_root_green_node = add_node(
        nodes=group.nodes,
        type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
        operation=MSFS2024_NodeMathOpe.SQRT.value,
        location=(410, -50)
    )

    combine_color_node = add_node(
        nodes=group.nodes,
        type_node=MSFS2024_ShaderNodeTypes.SHADERNODECOMBINECOLOR.value,
        location=(585, 66)
    )

    #region Inputs
    color_input = add_group_input(
        group=group, 
        input_name="color",
        input_type=MSFS2024_GroupTypes.NODESOCKETCOLOR.value
    )
    color_input.default_value = (1.0, 1.0, 1.0, 1.0)
    
    #endregion

    #region Outputs
    _ = add_group_output(
        group=group,
        output_name="output",
        output_type=MSFS2024_GroupTypes.NODESOCKETCOLOR.value
    )
    #endregion

    #region Links
    link(group.links, input_node.outputs[0], separate_color_node.inputs[0])
    link(group.links, separate_color_node.outputs[0], square_root_red_node.inputs[0])
    link(group.links, separate_color_node.outputs[1], square_root_green_node.inputs[0])
    link(group.links, separate_color_node.outputs[2], square_root_blue_node.inputs[0])
    
    
    link(group.links, square_root_red_node.outputs[0], combine_color_node.inputs[0])
    link(group.links, square_root_green_node.outputs[0], combine_color_node.inputs[1])
    link(group.links, square_root_blue_node.outputs[0], combine_color_node.inputs[2])

    link(group.links, combine_color_node.outputs[0], output_node.inputs[0])
    #endregion


def _draw_unpack_detail_omr(group):
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
        location=(770.0, 0.0),
        hidden=False
    )
    
    multiply_node = add_node(
        nodes=group.nodes,
        type_node=MSFS2024_ShaderNodeTypes.SHADERNODEVECTORMATH.value,
        operation=MSFS2024_NodeMathOpe.MULTIPLY.value,
        location=(295, 0)
    )
    multiply_node.inputs[1].default_value=(2,2,2)

    substract_node = add_node(
        nodes=group.nodes,
        type_node=MSFS2024_ShaderNodeTypes.SHADERNODEVECTORMATH.value,
        operation=MSFS2024_NodeMathOpe.SUBTRACT.value,
        location=(505, 0)
    )
    
    substract_node.inputs[1].default_value=(1, 1, 1)

    #region Inputs
    color_input = add_group_input(
        group=group, 
        input_name="detail ORM",
        input_type=MSFS2024_GroupTypes.NODESOCKETCOLOR.value
    )
    color_input.default_value = (1.0, 1.0, 1.0, 1.0)
    
    #endregion

    #region Outputs
    _ = add_group_output(
        group=group,
        output_name="detail ORM",
        output_type=MSFS2024_GroupTypes.NODESOCKETCOLOR.value
    )
    #endregion

    #region Links
    link(group.links, input_node.outputs[0], multiply_node.inputs[0])
    link(group.links, multiply_node.outputs[0], substract_node.inputs[0])
    link(group.links, substract_node.outputs[0], output_node.inputs[0])
    #endregion

#endregion

#region Public

def add_linear_step_node(node_tree, frame=None, location=(0, 0)):
    """ 
    LinearStep  :
        The function interpolates smoothly between two input values based on a third one.
        that should be between the first two. The returned value is clamped between 0 and 1.

    Args:
        node_tree : ShaderNodeTree or Group
        frame (node) : The frame Node of the new node. Defaults to None.
        location (tuple) : Position in (x, y) of the node in the shader tree. Defaults to (0.0, 0.0).

    Node Inputs:
        input_low 
        input_high 
        value 

    Shader Code:
        float linearstep(const float lo, const float hi, const float input)
        {
            return saturate((input - lo) / (hi - lo));
        }
    """

    linear_step_group, new_group = get_or_create_group_by_name(
        group_name = MSFS2024_GroupNodes.LINEARSTEPGROUP.value
    )
    
    if new_group:
        _draw_linear_step(group=linear_step_group)
    
    linear_step_group_node = add_node(
        nodes=node_tree.nodes,
        name=MSFS2024_GroupNodes.LINEARSTEPGROUP.value,
        type_node=MSFS2024_ShaderNodeTypes.SHADERNODEGROUP.value,
        location=location,
        width=200.0,
        frame=frame,
        hidden=False
    )
    linear_step_group_node.node_tree = linear_step_group

    return linear_step_group_node


def add_switch_node(node_tree, frame=None, location=(0, 0)):
    """
    Args:
        node_tree : ShaderNodeTree or Group
        frame (node) : The frame Node of the new node. Defaults to None.
        location (tuple) : Position in (x, y) of the node in the shader tree. Defaults to (0.0, 0.0).

    Node Inputs:
        switch 
        false 
        true 
    """

    switch_group, new_group = get_or_create_group_by_name(
        group_name=MSFS2024_GroupNodes.SWITCHGROUP.value
    )
    
    if new_group:
        _draw_switch(group=switch_group)
    
    switch_group_node = add_node(
        nodes=node_tree.nodes,
        name=MSFS2024_GroupNodes.SWITCHGROUP.value,
        type_node=MSFS2024_ShaderNodeTypes.SHADERNODEGROUP.value,
        location=location,
        width=200.0,
        frame=frame,
        hidden=False
    )
    switch_group_node.node_tree = switch_group

    return switch_group_node


def add_sqrt_color_node(node_tree, frame=None, location=(0, 0)):
    """
    Args:
        node_tree : ShaderNodeTree or Group
        frame (node) : The frame Node of the new node. Defaults to None.
        location (tuple) : Position in (x, y) of the node in the shader tree. Defaults to (0.0, 0.0).

    Node Inputs:
        color
    """
    square_root_color_group, new_group = get_or_create_group_by_name(
        group_name = MSFS2024_GroupNodes.SQUAREROOTCOLORGROUP.value
    )
    
    if new_group:
        _draw_sqrt_color(group=square_root_color_group)
    
    square_root_color_group_node = add_node(
        nodes=node_tree.nodes,
        name=MSFS2024_GroupNodes.SQUAREROOTCOLORGROUP.value,
        type_node=MSFS2024_ShaderNodeTypes.SHADERNODEGROUP.value,
        location=location,
        width=200.0,
        frame=frame,
        hidden=False
    )
    square_root_color_group_node.node_tree = square_root_color_group

    return square_root_color_group_node


def add_unpack_detail_orm_node(node_tree, frame=None, location=(0, 0)):
    """
    Args:
        node_tree : ShaderNodeTree or Group
        frame (node) : The frame Node of the new node. Defaults to None.
        location (tuple) : Position in (x, y) of the node in the shader tree. Defaults to (0.0, 0.0).

    Node Inputs:
        color
    """
    unpack_orm_group, new_group = get_or_create_group_by_name(
        group_name = MSFS2024_GroupNodes.UNPACKDETAILORMGROUP.value
    )
    
    if new_group:
        _draw_unpack_detail_omr(group = unpack_orm_group)
    
    unpack_orm_group_node = add_node(
        nodes=node_tree.nodes,
        name=MSFS2024_GroupNodes.UNPACKDETAILORMGROUP.value,
        type_node=MSFS2024_ShaderNodeTypes.SHADERNODEGROUP.value,
        location=location,
        width=200.0,
        frame=frame,
        hidden=False
    )
    unpack_orm_group_node.node_tree = unpack_orm_group

    return unpack_orm_group_node
#endregion
    