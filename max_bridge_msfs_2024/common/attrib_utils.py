"""
Attributes utilities.
Only work on object with data property.
"""
import string
import random

import bpy
import numpy as np

from max_bridge_msfs_2024.common import usd_properties, obj_utils, ope_utils


def get_attrib_by_name(
    obj:bpy.types.Object,
    attrib_name:str
)->None|bpy.types.Attribute:

    attributes = obj.data.attributes

    attrib = attributes.get(attrib_name, None)
    return attrib

def _generate_id(
    size:int=6,
    chars:str=string.ascii_uppercase + string.digits
)->str:
    """Generate a string id.
 
    Args:
        size (optional): Char Length of id. Defaults to 6.
        chars (optional): Characters used in id. Defaults to string.ascii_uppercase+string.digits.

    Returns:
        id
    """
    return ''.join(random.choice(chars) for _ in range(size))

def get_unique_attrib_name(obj:bpy.types.Object)->str:
    """
    Generate a unique attribute name.
    """
    attrib_names=list([attrib.name for attrib in obj.data.attributes])
    unique_name=_generate_id()
    while unique_name in attrib_names:
        unique_name=_generate_id()
    return unique_name


def remove_attribute_by_name(
    obj:bpy.types.Object,
    attrib_name:str
):
    attrib=get_attrib_by_name(obj,attrib_name)
    if attrib:
        obj.data.attributes.remove(attrib)

def set_active_color_attribute(
    obj:bpy.types.Object,
    attrib_name:str
):
    """
    Set color attribute to be active in viewport and render.
    """
    attrib=get_attrib_by_name(obj,attrib_name)
    if attrib:
        obj.data.attributes.active_color = attrib
        obj.data.attributes.render_color_index = obj.data.attributes.active_color_index


def get_render_color_attribute(obj:bpy.types.Object)->None|bpy.types.Attribute:
    try:
        return obj.data.color_attributes[obj.data.attributes.render_color_index]
    except IndexError:
        return None

def convert_color_attribute_domain(
    obj:bpy.types.Object, 
    attrib_name:str, 
    target_domain:str = "CORNER",
    target_type:str = "FLOAT_COLOR"
)->bpy.types.Attribute | None:
    """
    Converts a color attribute to a different domain using a context override.

    Args:
        obj : The object owning the mesh.
        attr_name : The name of the source color attribute.
        target_domain : The target domain ('POINT', 'CORNER', 'FACE').
    Returns:
        Converted color attribute
    """
    mesh=obj.data

    attrib = get_attrib_by_name(obj, attrib_name)
    if not attrib:
        return None

    src_attr = mesh.color_attributes[attrib_name]
    src_domain = src_attr.domain

    if src_domain == target_domain:
        return attrib

    # Prepare a context override
    context_override = ope_utils.get_context_override([obj], obj)

    current_attrib_name = obj.data.attributes.active_color.name
    # switch active attribute for operator
    set_active_color_attribute(obj, attrib_name)
    # Execute the conversion in the overridden context
    with bpy.context.temp_override(**context_override):
        bpy.ops.geometry.color_attribute_convert(domain=target_domain, data_type=target_type)

    set_active_color_attribute(obj, current_attrib_name)

    return get_attrib_by_name(obj, attrib_name)


def add_color_attribute(
    obj: bpy.types.Object,
    attrib_name: str,
    attrib_domain: str = "CORNER",
    attrib_type: str = "FLOAT_COLOR",
) -> bpy.types.Attribute:
    """
    Add a white color attribute.
    WARNING: adding a new  attribute invalid other attributes references...
    That's why get attrib by name after creating it.

    Returns:
        New Color Attribute.
    """

    color_attrib = obj.data.color_attributes.new(
        name=attrib_name,
        type=attrib_type,
        domain=attrib_domain,
    )

    color_attrib = get_attrib_by_name(obj, attrib_name)
    return color_attrib


def merge_in_color_alpha(
    color_attrib:bpy.types.Attribute,
    alpha_attrib:bpy.types.Attribute
):
    """
    Merge alpha_attrib first component into color_attrib alpha.
    """
    color_attrib_data : bpy.types.bpy_prop_collection = color_attrib.data
    alpha_attrib_data : bpy.types.bpy_prop_collection = alpha_attrib.data
    if len(color_attrib_data) != len(alpha_attrib_data):
        raise ValueError("Source and destination attributes must have the same length.")

    np_color = np.ones((len(color_attrib_data), 4), dtype=np.float32)
    np_alpha = np.ones((len(alpha_attrib_data), 4), dtype=np.float32)
    color_attrib_data.foreach_get("color", np.ravel(np_color))
    alpha_attrib_data.foreach_get("color", np.ravel(np_alpha))
    np_color[:, 3] = np_alpha[:, 0]
    color_attrib_data.foreach_set("color", np.ravel(np_color))


def create_attrib_from_alpha(
    obj: bpy.types.Object, color_attrib_name: str, new_attrib_name: str
) -> bpy.types.Attribute | None:

    color_attrib = get_attrib_by_name(obj, color_attrib_name)
    color_attrib_data : bpy.types.bpy_prop_collection = color_attrib.data
    if not len(color_attrib_data):
        return None

    new_attrib = add_color_attribute(
        obj, new_attrib_name, color_attrib.domain, color_attrib.data_type, 
    )

    new_attrib_data : bpy.types.bpy_prop_collection = new_attrib.data

    np_alpha = np.ones((len(color_attrib_data), 4), dtype=np.float32)
    if len(color_attrib_data) == len(new_attrib_data):
        color_attrib_data.foreach_get("color", np.ravel(np_alpha))
        np_alpha = np.repeat(np_alpha[:, 3:4], 4, axis=1)

    else:   
        print(f"Couldn't populate alpha attrib of {obj.name}, set default white Color")

    new_attrib_data.foreach_set("color", np.ravel(np_alpha))

    return new_attrib


def set_obj_color_attrib(obj:bpy.types.Object):
    """
    Prepare obj color attribute.
    Remove useless DisplayColor created by usd importer.
    Create default white vertexColor if not present.

    Args:
        obj : The object whose UV maps will be renamed.

    """
    if not obj_utils.is_mesh(obj):
        return

    displaycolor_attrib_name = usd_properties.USDMeshAttributes.DISPLAY_COLOR.value
    color_attrib_name = usd_properties.USDMeshAttributes.VERTEX_COLOR.value
    alpha_attrib_name = usd_properties.USDMeshAttributes.VERTEX_ALPHA.value

    display_color_attrib = get_attrib_by_name(obj, displaycolor_attrib_name)
    if display_color_attrib:
        obj.data.color_attributes.remove(display_color_attrib)

    color_attrib = get_attrib_by_name(obj, color_attrib_name)

    if not color_attrib:
        color_attrib = add_color_attribute(obj, color_attrib_name)
    else:
        color_attrib = convert_color_attribute_domain(
            obj, attrib_name=color_attrib_name, target_domain="CORNER"
        )
    alpha_attrib = get_attrib_by_name(obj, alpha_attrib_name)
    if alpha_attrib:
        alpha_attrib = convert_color_attribute_domain(
            obj, attrib_name=alpha_attrib_name, target_domain="CORNER"
        )
        # Be carefull after editing attributes, color attrib could not represent attribute correctly
        # So we get color attrib by name again here in order to avoid attribute update issues
        color_attrib = get_attrib_by_name(obj, color_attrib_name)
        alpha_attrib = get_attrib_by_name(obj, alpha_attrib_name)
        merge_in_color_alpha(color_attrib, alpha_attrib)
        obj.data.color_attributes.remove(alpha_attrib)

    set_active_color_attribute(obj, color_attrib_name)

def rename_uv_maps(obj:bpy.types.Object):
    """
    Rename UV maps of the specified object or the active object in Blender.

    Args:
        obj : The object whose UV maps will be renamed.
    """

    if not obj.data or not hasattr(obj.data, 'uv_layers'):
        return

    uv_layers = obj.data.uv_layers
    for index, uv_map in enumerate(uv_layers):
        # Construct the new name
        uv_map.name = f"UV{index+1}"
