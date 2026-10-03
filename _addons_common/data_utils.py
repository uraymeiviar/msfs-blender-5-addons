import bpy
import re

def is_editable(id: bpy.types.ID) -> bool:
    # is_editable only exists in blender 4.2 or superior
    if hasattr(id, "is_editable") and not id.is_editable:
        return True
    # if library is not None, then ID is editable since it is not linked.
    return id.library is None

def remove_number_suffix(name: str) -> str:
    """Remove potential suffix like .001"""
    return re.sub(r"\.\d+$", "", name)