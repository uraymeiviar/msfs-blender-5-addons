"""
Utilities for bpy_props
"""

from __future__ import annotations
from typing import Iterable

def safe_enum_prop_get(_self, enum_name: str, enum_indexes: Iterable[int], default_index:int=0 )->int:
    """Generic function to safely get enum index.
    Necessary when enum item count was reduced.
    Old scene may references these deleted items.
    In this case we return the default.
    
    cf example with export_animation_mode property.
    """
    index = _self.get(enum_name, None)

    # If invalid or missing → replace with default
    if index not in enum_indexes:
        index = default_index

    return index