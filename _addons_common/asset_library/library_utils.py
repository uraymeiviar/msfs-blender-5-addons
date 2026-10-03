from __future__ import annotations
from typing import Generator
from pathlib import Path
import re
from enum import Enum
import bpy

from _addons_common import data_utils

class DataBlockTypes(Enum):
    UNDEFINED = "undefined"
    ACTIONS = "actions"
    ARMATURES = "armatures"
    BRUSHES = "brushes"
    CAMERAS = "cameras"
    COLLECTIONS = "collections"
    CURVES = "curves"
    FONTS = "fonts"
    GREASE_PENCILS = "grease_pencils"
    IMAGES = "images"
    LIGHTS = "lights"
    MATERIALS = "materials"
    MESHES = "meshes"
    MOVIECLIPS = "movieclips"
    NODE_GROUPS = "node_groups"
    OBJECTS = "objects"
    SCENES = "scenes"
    SOUNDS = "sounds"
    TEXTS = "texts"
    TEXTURES = "textures"
    WORLDS = "worlds"

    @classmethod
    def get_defined_datablocks(cls)->Generator[DataBlockTypes]:
        for datablock in cls:
            if datablock == cls.UNDEFINED:
                continue
            else:
                yield datablock


# region MSFS Tag
def relative_to_absolute_asset_path(
    relative_asset_path: Path | str, datafiles_dir: Path | str
) -> Path | None:
    """
    Return existing absolute asset path.
    """
    datafiles_dir = Path(datafiles_dir)
    absolute_asset_path = datafiles_dir / Path(relative_asset_path)
    found_library_path = None
    if absolute_asset_path.exists():
        found_library_path = absolute_asset_path

    return found_library_path


def absolute_to_relative_asset_path(absolute_asset_path: Path | str, datafiles_dir: Path | str) -> Path|None:
    absolute_asset_path = Path(absolute_asset_path)
    datafiles_dir = Path(datafiles_dir)
    return absolute_asset_path.relative_to(datafiles_dir)


MSFS_ASSET_PATH_TAG = "msfs_asset_path"

def _set_msfs_asset_path(asset: bpy.types.bpy_struct, blend_filepath: Path | str, datafiles_dir: Path | str):
    """Add a MSFS_ASSET_PATH_TAG to asset.
    """
    asset[MSFS_ASSET_PATH_TAG] = str(absolute_to_relative_asset_path(blend_filepath, datafiles_dir))


def get_msfs_asset_path(asset: bpy.types.bpy_struct) -> Path | None:
    """Return relative blender file path containing asset source.
    """
    msfs_asset_path = None
    try:
        msfs_asset_path = Path(asset[MSFS_ASSET_PATH_TAG])
    except:
        pass
    return msfs_asset_path

# endregion

# region Blend file suffix

BLEND_FILE_VERSION_SEPARATOR = "-"

def add_blend_version_suffix(
    asset_path: str | Path, version: tuple[int, int, int]
) -> Path:
    version_suffix = f"{BLEND_FILE_VERSION_SEPARATOR}{version[0]}_{version[1]}_{version[2]}"
    asset_path = Path(asset_path)
    asset_path = asset_path.with_stem(asset_path.name + version_suffix)
    return asset_path.with_suffix(".blend")


def remove_blend_version_suffix(
    asset_path: str
) -> Path | None:
    parts = asset_path.rsplit(BLEND_FILE_VERSION_SEPARATOR, maxsplit=1)
    if len(parts) == 1:
        return None

    return Path(parts[0])

# endregion

# region Assets

def get_asset_id_name(asset: bpy.types.ID) -> str:
    asset_id_name = None
    if asset.library_weak_reference and asset.library_weak_reference.id_name:
        asset_id_name = asset.library_weak_reference.id_name
        if len(asset_id_name) > 3:
            # Remove leading suffix
            asset_id_name = asset_id_name[2:]
            return asset_id_name
    
    # Use asset name as a backup
    asset_id_name = data_utils.remove_number_suffix(asset.name)
    return asset_id_name


def is_asset_instance(
    asset: bpy.types.ID,
    id_name_target: str,
    msfs_path_target: Path | str,
    ignore_blend_version: bool = False
)->bool:
    """
    Check if provided asset has same id and msfs_asset_path.
    """
    asset_id_name = get_asset_id_name(asset)

    if not asset_id_name == id_name_target:
        return False
    # Only get asset with same msfs_asset_path
    msfs_path_target = Path(msfs_path_target)
    msfs_datafiles_path = None

    if asset.library_weak_reference and asset.library_weak_reference.filepath:
        filepath = Path(asset.library_weak_reference.filepath)
        target_path_count = len(msfs_path_target.parts)
        if len(msfs_path_target.parts) <= len(filepath.parts):
            # Get latest parts of filepath
            msfs_datafiles_path = Path(*filepath.parts[-target_path_count:])

    if msfs_datafiles_path is None:
        # Use msfs asset path as a backup
        msfs_datafiles_path = get_msfs_asset_path(asset)

    if not msfs_datafiles_path:
        return False

    if ignore_blend_version:
        # An asset can have multiple sources.
        # Example with collision gizmo that has 3.3 and 4.2 version
        # Check out io_scene_gltf2_msfs_fss asset library
        msfs_datafiles_path = remove_blend_version_suffix(
                msfs_datafiles_path.as_posix()
            )
        if not msfs_datafiles_path:
            return False

        msfs_path_target = remove_blend_version_suffix(msfs_path_target.as_posix())
        if not msfs_path_target:
            return False

    return msfs_datafiles_path == msfs_path_target

def append_asset(
    blend_filepath: str | Path,
    datafiles_dir:  str | Path,
    datablock_type: str,
    id_name: str,
    unique_mode: bool = False
) -> bpy.types.bpy_struct | None:
    """
    Append asset as a copy in current scene.

    If unique_mode is True, the function will first check if the asset
    is already present in the current blend file and return it is found.
    Ignore assets that have not a msfs_path matching with provided blend_filepath .

    Returns:
        Appended asset or None if failed.
    """
    data_list = getattr(bpy.data, datablock_type)

    if unique_mode:
        # Get asset if it already in blend file
        asset = data_list.get(id_name, None)
        if asset:
            relative_blend_filepath = absolute_to_relative_asset_path(
                blend_filepath, datafiles_dir
            )

            if relative_blend_filepath and is_asset_instance(asset, id_name, relative_blend_filepath):
                return asset

    ids_before = set(data_list.keys())
    with bpy.data.libraries.load(str(blend_filepath), link=False) as (
        data_from,
        data_to,
    ):
        for _id_name in getattr(data_from, datablock_type):
            if id_name == _id_name:

                setattr(data_to, datablock_type, [id_name])
                break

    data_list_after = getattr(bpy.data, datablock_type)
    ids_after = set(data_list_after.keys())

    # Get appended_id_name by comparing the ids after append.
    # So we are sure to get the new appended data.
    # This prevent any id_name conflict (blend adds .001 when id_name already exists)
    id_names_diff = ids_after.difference(ids_before)
    asset = None
    appended_id_name = None
    if not id_names_diff:
        return None

    for name in id_names_diff:
        if data_utils.remove_number_suffix(name)==id_name:
            appended_id_name = name
            break

    if not appended_id_name:
        return None

    asset = data_list_after.get(appended_id_name, None)
    if not asset:
        return None

    _set_msfs_asset_path(asset, blend_filepath, datafiles_dir)

    return asset


DATA_USERS_CAPTURE = dict[str, dict[bpy.types.ID, int]]

def capture_data_users() -> DATA_USERS_CAPTURE:
    """Create a dict containing data users count.
    Used to safely clean removed data dependencies (nested node groups, objects etc)
    """

    data_users: dict[str, dict[bpy.types.ID, int]] = {}
    for datablock in DataBlockTypes.get_defined_datablocks():
        bpy_data = getattr(bpy.data, datablock.value, None)
        if bpy_data is None:
            raise Exception(f"Can't find datablock in bpy.data {datablock.value}")
        if not (bpy_data):
            continue

        _data_users = data_users.get(datablock.value, None)
        if _data_users is None:
            _data_users = {}
            data_users[datablock.value] = _data_users
        for data in bpy_data:
            data: bpy.types.ID
            _data_users[data.name] = data.users

    return data_users


def remove_data_without_users(data_users_capture: DATA_USERS_CAPTURE):
    """
    Recursively remove data that lost users.
    Ignore new data or data that already had 0 users in data_users.
    """

    to_delete = []
    for datablock in DataBlockTypes.get_defined_datablocks():
        bpy_data = getattr(bpy.data, datablock.value, None)
        if bpy_data is None:
            raise Exception(f"Can't find datablock in bpy.data {datablock.value}")
        if not (bpy_data):
            continue

        _data_users = data_users_capture.get(datablock.value, None)
        if _data_users is None:
            continue

        for data in bpy_data:
            data: bpy.types.ID
            users = _data_users.get(data.name, None)
            if users is None or users == 0:
                # Skip if new, or had no users before capture
                continue
            if data.users == 0:
                to_delete.append(data)

    if to_delete:
        try:
            print(f"Deleted: {to_delete}")
            bpy.data.batch_remove(to_delete)
            print(f"SucessFull")
        except:
            pass
        data_users_capture = capture_data_users()
        remove_data_without_users(data_users_capture)


def remove_asset(
    blend_filepath: str | Path,
    datafiles_dir:  str | Path,
    datablock_type: str,
    id_name: str,
    clean_dependencies: bool = True,
    data_users_capture: DATA_USERS_CAPTURE | None = None,
    no_users_only: bool = False
) -> bool:
    """
    Remove all occurences of asset in current scene.

    if msfs_asset_path_only is True, only assets matching provided blend_filepath
    will be disabled.

    Returns:
       True if asset could be found and deleted.
    """
    if clean_dependencies and data_users_capture is None:
        data_users_capture = capture_data_users()

    data_list = getattr(bpy.data, datablock_type)

    to_delete = []
    # Get asset if it already in blend file
    relative_blend_filepath = absolute_to_relative_asset_path(
        blend_filepath, datafiles_dir
    )
    if not relative_blend_filepath:
        return False

    for asset in data_list:
        if no_users_only and asset.users != 0:
            continue
        if is_asset_instance(asset, id_name, relative_blend_filepath):
            to_delete.append(asset)

    try:
        bpy.data.batch_remove(to_delete)
        if clean_dependencies and data_users_capture:
            remove_data_without_users(data_users_capture)
        return True
    except:
        return False
# endregion
