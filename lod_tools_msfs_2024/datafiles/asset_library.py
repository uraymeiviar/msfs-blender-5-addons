from __future__ import annotations
from pathlib import Path

from _addons_common.asset_library import asset_library

SUPPORTED_MSFS_VERSIONS: list[str] = ["2024"]  # type: ignore
SUPPORTED_BLENDER_VERSIONS: list[tuple[int, int, int]] = [(3, 3, 0)]  # type: ignore
DATAFILES_DIR: Path = Path(__file__).parent


class MSFS2024LODViewerInputs(asset_library.NodeGroupInputs):
    CAMERA = "Camera"
    SELF = "Self"
    BOUNDING_SPHERE = "Bounding Sphere"
    LOD_COUNT = "LOD Count"
    LOD0_COLLECTION = "LOD0"
    LOD1_COLLECTION = "LOD1"
    LOD2_COLLECTION = "LOD2"
    LOD3_COLLECTION = "LOD3"
    LOD4_COLLECTION = "LOD4"
    LOD5_COLLECTION = "LOD5"
    LOD6_COLLECTION = "LOD6"
    LOD7_COLLECTION = "LOD7"
    LOD8_COLLECTION = "LOD8"
    LOD0_SCREEN_SIZE = "LOD0 Screen Size"
    LOD1_SCREEN_SIZE = "LOD1 Screen Size"
    LOD2_SCREEN_SIZE = "LOD2 Screen Size"
    LOD3_SCREEN_SIZE = "LOD3 Screen Size"
    LOD4_SCREEN_SIZE = "LOD4 Screen Size"
    LOD5_SCREEN_SIZE = "LOD5 Screen Size"
    LOD6_SCREEN_SIZE = "LOD6 Screen Size"
    LOD7_SCREEN_SIZE = "LOD7 Screen Size"
    LOD8_SCREEN_SIZE = "LOD8 Screen Size"

    @classmethod
    def get_lod_collection_input(cls, level: int):
        return getattr(cls, f"LOD{level}_COLLECTION")

    @classmethod
    def get_lod_screen_size_input(cls, level: int):
        return getattr(cls, f"LOD{level}_SCREEN_SIZE")


# endregion

# region Nodegroup


class NodeGroupLibrary(asset_library.NodeGroupLibrary):

    # Assets:
    LOD_VIEWER = (
        ".MSFS_2024_LOD_Viewer",
        "assets/nodes/lod_viewer",
        MSFS2024LODViewerInputs,
    )
    LOD_VIEWER_CONSTANTS = (
        ".MSFS_2024_LOD_Viewer_Constants",
        "assets/nodes/lod_viewer",
        asset_library.EmptyInputs,
    )

NodeGroupLibrary.SUPPORTED_MSFS_VERSIONS = SUPPORTED_MSFS_VERSIONS  # type: ignore
NodeGroupLibrary.SUPPORTED_BLENDER_VERSIONS = SUPPORTED_BLENDER_VERSIONS  # type: ignore
NodeGroupLibrary.DATAFILES_DIR = DATAFILES_DIR  # type: ignore

# endregion


class ObjectLibrary(asset_library.ObjectLibrary):

    # Assets:
    BOUNDING_SPHERE = (
        ".MSFS_2024_Bounding_Sphere_2m",
        "assets/nodes/lod_viewer",
        "CURVE",
    )

ObjectLibrary.SUPPORTED_MSFS_VERSIONS = SUPPORTED_MSFS_VERSIONS  # type: ignore
ObjectLibrary.SUPPORTED_BLENDER_VERSIONS = SUPPORTED_BLENDER_VERSIONS  # type: ignore
ObjectLibrary.DATAFILES_DIR = DATAFILES_DIR  # type: ignore
