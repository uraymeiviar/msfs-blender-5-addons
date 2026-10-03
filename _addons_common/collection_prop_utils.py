from __future__ import annotations

import bpy

def _split_name(name: str):
    parts = name.rsplit(".", 1)

    if len(parts) == 2 and parts[1].isdigit():
        return parts[0], int(parts[1])

    return name, None


def get_unique_name(collection: bpy.types.bpy_prop_collection_idprop, name: str)->str:
    """
    Return a unique name for a new item in collection.

    Uses Blender's naming convention:
        Name
        Name.001
        Name.002
        ...

    Notes:
        This function builds a set of all collection names on every call,
        making it O(n). Avoid calling it repeatedly when creating many
        items.
    """
    keys = set(collection.keys())

    if name not in keys:
        return name

    base_name, _ = _split_name(name)

    i = 1
    while True:
        candidate = f"{base_name}.{i:03d}"
        if candidate not in keys:
            return candidate
        i += 1
