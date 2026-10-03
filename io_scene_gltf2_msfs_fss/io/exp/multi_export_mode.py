from __future__ import annotations
from enum import Enum

import bpy


class ExportMode(Enum):
    OBJECTS = ("OBJECTS", "Objects")
    COLLECTIONS = ("COLLECTIONS", "Collections")
    PRESETS = ("PRESETS", " Presets")

    def __init__(self, identifier: str, label: str):
        self.identifier = identifier
        self.label = label

    @classmethod
    def from_identifier(cls, identifier: str) -> ExportMode | None:
        for mode in cls:
            if mode.identifier == identifier:
                return mode
        return None

EXPORT_MODE_ENUM_ITEMS = (
    (
        ExportMode.OBJECTS.identifier,
        ExportMode.OBJECTS.label,
        "LOD Group are generated from objects hierarchy",
        "OBJECT_DATA",
        0
    ),
    (
        ExportMode.COLLECTIONS.identifier,
        ExportMode.COLLECTIONS.label,
        "LOD Group are generated from collections hierarchy",
        "OUTLINER_COLLECTION",
        1
    ),
    (
        ExportMode.PRESETS.identifier,
        ExportMode.PRESETS.label,
        "LOD Group are manually created using presets",
        "PRESET",
        2
    )
)

def get_active_export_mode(scene: bpy.types.Scene) -> ExportMode | None:
    return ExportMode.from_identifier(scene.msfs_export_mode) # type: ignore


def register():
    bpy.types.Scene.msfs_export_mode = bpy.props.EnumProperty(
        name="Mode",
        default=ExportMode.OBJECTS.identifier,
        description=("LOD groups are generated from scene objects or collections hierarchy."
        "Or manually create LOD group using presets."
        "(WARNING: Switching hierarchy mode between Collections and Objects modes"
        "will reset LOD groups export settings)"),
        items=EXPORT_MODE_ENUM_ITEMS
        ) # type: ignore

def unregister():
    try:
        del bpy.types.Scene.msfs_export_mode
    except:
        pass
