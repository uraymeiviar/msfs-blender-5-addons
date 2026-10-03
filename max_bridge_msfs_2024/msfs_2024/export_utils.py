from __future__ import annotations


import bpy
from max_bridge_msfs_2024 import logger

from max_bridge_msfs_2024.common.usd_properties import *

from max_bridge_msfs_2024.msfs_2024.msfs_properties import *

logging = logger.getLogger()


def convert_prop(prop: BridgePropertiesDef, value: Any) -> Any:
    """
    Convert Blender data to python equivalent.
    Values need to be compatible with json.
    """
    if prop == PropertyTypes.TEXTURE and type(value) == bpy.types.Image:
        value = bpy.path.abspath(value.filepath)

    if prop == PropertyTypes.PATH:
        value = bpy.path.abspath(value)

    elif prop == PropertyTypes.COLOR:
        value = list(value)

    elif prop == PropertyTypes.INT:
        value = int(value)

    return value


def convert_mat_prop(prop: MSFS2024_MaterialProperties, value: Any) -> Any:
    """
    Convert blender data to python equivalent.
    Also format other special properties for blender compatibility.
    """
    # material type is convert from int to a readable string
    material_types = list([e.value for e in MSFS2024_MaterialTypes])
    alpha_types = list([e.value for e in MSFS2024_AlphaModes])

    if prop == MSFS2024_MaterialProperties.MATERIALTYPE:
        if value == "NONE":
            value = 0
        else:
            try:
                value = material_types.index(value)
            except ValueError:
                print(f"Material type {value} not supported!")
    # alpha modes convert from int to a readable string
    elif prop == MSFS2024_MaterialProperties.ALPHAMODE:
        try:
            value = alpha_types.index(value)
        except ValueError:
            print(f"Alpha mode {value} not supported!")
    else:
        value = convert_prop(prop.prop_type, value)

    return value


def convert_custom_class_prop(prop: CustomClassPropertiesDef, value) -> Any:
    return convert_prop(prop, value)
