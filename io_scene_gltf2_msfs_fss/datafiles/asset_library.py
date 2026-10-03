from __future__ import annotations

from pathlib import Path

from _addons_common.asset_library import asset_library

SUPPORTED_MSFS_VERSIONS: list[str] = ["2024"]  # type: ignore
SUPPORTED_BLENDER_VERSIONS: list[tuple[int, int, int]] = [(4, 2, 0), (3, 3, 0)]  # type: ignore
DATAFILES_DIR: Path = Path(__file__).parent

class MSFS2024CollisionInputs(asset_library.NodeGroupInputs):
    TYPE = "Collision Type"
    ROAD_COLLIDER = "Road Collider"
    GROUND_COLLIDER = "Ground Collider"


# region Nodegroup
class NodeGroupLibrary(asset_library.NodeGroupLibrary):

    COLLISIONS = (
        ".MSFS_2024_Collision",
        "assets/nodes/gizmos",
        MSFS2024CollisionInputs,
    )

    BOUNDING_VOLUME = (
        ".MSFS_2024_Bounding_Volume",
        "assets/nodes/gizmos",
        asset_library.EmptyInputs,
    )

NodeGroupLibrary.SUPPORTED_MSFS_VERSIONS = SUPPORTED_MSFS_VERSIONS  # type: ignore
NodeGroupLibrary.SUPPORTED_BLENDER_VERSIONS = SUPPORTED_BLENDER_VERSIONS  # type: ignore
NodeGroupLibrary.DATAFILES_DIR = DATAFILES_DIR  # type: ignore
