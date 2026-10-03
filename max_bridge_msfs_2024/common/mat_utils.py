from __future__ import annotations

from pathlib import Path

import bpy


def get_image(path: str) -> None | bpy.types.Image:
    """
    Load image if not already in scene.
    """
    for image in bpy.data.images:
        if Path(image.filepath) == Path(path):
            return image
    if Path(path).exists():
        return bpy.data.images.load(path)
    else:
        return None


def get_materials(obj: bpy.types.Object) -> set[bpy.types.Material]:
    """
    Get object materials.
    """
    _materials = set()
    if not obj or not obj.material_slots:
        return _materials

    for slot in obj.material_slots:
        # Check if the slot contains a material
        if slot.material:
            _materials.add(slot.material)

    return _materials


def get_unique_materials(objects: list[bpy.types.Object]) -> set[bpy.types.Material]:
    """
    Construct a unique set of materials assigned on objects.
    """
    materials = set()
    for obj in objects:
        obj_mat = get_materials(obj)
        materials.update(obj_mat)
    return list(materials)
