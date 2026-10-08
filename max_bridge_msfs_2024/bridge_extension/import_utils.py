from __future__ import annotations

from max_bridge_asobo import logger
from max_bridge_asobo.bridge_base.usd_properties import *
from max_bridge_asobo.bridge_base import mat_utils

from max_bridge_msfs_2024.bridge_extension.msfs_properties import *


logging=logger.getLogger()


def convert_prop(prop: BridgePropertiesDef, value: Any) -> Any:
    """
    Convert imported bridge properties.
    """
    if prop.prop_type == PropertyTypes.TEXTURE:
        if value:
            value = mat_utils.get_image(value)
            return value
        else:
            return None
    return value


def convert_mat_prop(prop: MSFS2024_MaterialProperties, value: Any) -> Any:

    if prop==MSFS2024_MaterialProperties.EMISSIVECOLOR:
        value = value[:3] #color rgba to rgb
    return convert_prop(prop,value)
