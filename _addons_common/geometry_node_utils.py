"""
Utilities to manipulate geometry node groups and node modifiers.
"""

from typing import Any


import bpy

class NotFound():
    # Sentinel Value
    pass

# region Node
def set_boolean_node_value(node: bpy.types.FunctionNodeInputBool, value: bool):
    try:
        node.boolean = value
    except AttributeError:
        return


def set_integer_node_value(node: bpy.types.FunctionNodeInputInt, value: int):
    try:
        node.integer = value
    except AttributeError:
        return


def set_node_output_default_value(
    node: bpy.types.GeometryNode, value, output_index: int = 0
):
    input = None
    try:
        input = node.outputs[output_index]
    except IndexError:
        print(f"Output index {output_index} doesn't exist in {node}")
        return

    input.default_value = value


def set_node_input_default_value(
    node: bpy.types.GeometryNode, value, input_identifier: str
):
    input = node.inputs.get(input_identifier, None)
    if not input:
        print(f"Input {input_identifier} doesn't exist in {node}")
        return
    input.default_value = value


def get_node_input_default_value(
    node: bpy.types.GeometryNode, input_identifier: str
) -> Any | NotFound:
    input = node.inputs.get(input_identifier, None)
    if not input:
        print(f"Input {input_identifier} doesn't exist in {node}")
        return NotFound
    return input.default_value


# endregion

# region Group
def get_input_identifier(
    node_group: bpy.types.NodeGroup, input_label: str
) -> None | str:
    """Get the unique identifier of a node group input by using input label name.

    Returns:
        str: The identifier if found, otherwise None.
    """
    if bpy.app.version < (4, 0, 0):

        inputs = node_group.inputs
        input = inputs.get(input_label, None)
        if not input:
            return None
        identifier = input.identifier
        return identifier
    else:
        for item in node_group.interface.items_tree:  # type: ignore
            if not item.in_out == "INPUT" or not item.name == input_label:  # type: ignore
                continue

            return item.identifier
    return None

def construct_input_identifier_map(node_group: bpy.types.NodeGroup) -> dict:
    """Construct a dict mapping input label to their 
    unique identifier names("Socket_0, Socket_1 ...).
    Input labels of node group must be unique.
    """
    input_identifier_map = {}
    if bpy.app.version < (4, 0, 0):

        inputs = node_group.inputs
        for input in inputs:
            input_identifier_map[input.name] = input.identifier
    else:
        for item in node_group.interface.items_tree:  # type: ignore
            if not item.in_out == "INPUT" :  # type: ignore
                continue
            input_identifier_map[item.name] = item.identifier
    return input_identifier_map
# endregion

# region Modifiers
def get_modifier_by_node_group(
    obj:bpy.types.Object,
    node_group_id_name: str,
) -> bpy.types.Modifier | None:
    """Get the first modifier of an object using provided node_group 

    Object data should be of curve type.
    """
    if not obj.type == "CURVE":
        return None
    for mod in obj.modifiers:
        if not mod.type == "NODES" or not mod.node_group:
            continue
        
        if mod.node_group.name.startswith(
            node_group_id_name
        ):
            return mod

    return None

def _is_geometry_node_modifier(modifier):
    if modifier.type != "NODES":
        return False
    node_group: bpy.types.NodeGroup = modifier.node_group  # type: ignore
    if not node_group:
        return False
    return True

def get_modifier_input_value(
    modifier: bpy.types.Modifier, input_identifier: str, default: Any = None
) -> Any:
    """
    Get modifier input value using the input identifier ("Socket_0", ...).

    Blender 5.0 replaced the ID properties behind geometry node modifier inputs
    (modifier["Socket_0"]) with typed RNA (modifier.properties.inputs.Socket_0.value).
    Menu sockets are returned as their integer item value, as the ID property was.
    """
    if hasattr(modifier, "properties"):
        socket = getattr(modifier.properties.inputs, input_identifier, None)
        if socket is None:
            return default
        value_prop = socket.bl_rna.properties["value"]
        if value_prop.type == "ENUM":
            return value_prop.enum_items[socket.value].value
        return socket.value
    return modifier.get(input_identifier, default)


def set_modifier_input_value(modifier: bpy.types.Modifier, input_identifier: str, value: Any):
    """
    Set modifier input value using the input identifier (see get_modifier_input_value).
    Menu sockets accept their integer item value, as the ID property did.
    """
    if hasattr(modifier, "properties"):
        socket = getattr(modifier.properties.inputs, input_identifier)
        value_prop = socket.bl_rna.properties["value"]
        if value_prop.type == "ENUM" and isinstance(value, int):
            value = next(item.identifier for item in value_prop.enum_items if item.value == value)
        socket.value = value
    else:
        modifier[input_identifier] = value


def get_modifier_input(
    modifier: bpy.types.Modifier, input_label: str
) -> Any | NotFound:
    """
    Get modifier input value using input label
    """
    if not _is_geometry_node_modifier(modifier):
        raise TypeError("Not a valid Geometry Node modifier!")

    input_identifier = get_input_identifier(modifier.node_group, input_label)
    if not input_identifier:
        return NotFound
    return get_modifier_input_value(modifier, input_identifier, NotFound)


def set_modifier_input(modifier: bpy.types.Modifier, input_label: str, value: Any):
    """
    Set modifier input value using input label
    """
    if not _is_geometry_node_modifier(modifier):
        raise TypeError("Not a valid Geometry Node modifier!")

    input_identifier = get_input_identifier(modifier.node_group, input_label)
    if not input_identifier:
        return
    set_modifier_input_value(modifier, input_identifier, value)

# endregion
