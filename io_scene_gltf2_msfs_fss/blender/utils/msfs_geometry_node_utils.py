"""
Utilities to manipulate geometry node modifiers and node groups.
"""

from typing import Any

import bpy

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

def get_modifier_input(
    modifier: bpy.types.Modifier, input_label: str
) -> Any | None:
    """
    Get modifier input value using input label
    """
    if not _is_geometry_node_modifier(modifier):
        raise TypeError("Not a valid Geometry Node modifier!")

    input_identifier = get_input_identifier(modifier.node_group, input_label)
    if not input_identifier:
        return None
    return modifier[input_identifier]


def set_modifier_input(modifier: bpy.types.Modifier, input_label: str, value: Any):
    """
    Set modifier input value using input label
    """
    if not _is_geometry_node_modifier(modifier):
        raise TypeError("Not a valid Geometry Node modifier!")

    input_identifier = get_input_identifier(modifier.node_group, input_label)
    if not input_identifier:
        return
    modifier[input_identifier] = value
