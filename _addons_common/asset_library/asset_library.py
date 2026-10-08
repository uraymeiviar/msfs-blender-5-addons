"""Contain Base classes to declare asset library of node_groups, objects etc
"""
from __future__ import annotations

from typing import Type

import re
from pathlib import Path
from enum import Enum


import bpy

from _addons_common.asset_library import library_utils
from _addons_common.asset_library.library_utils import DataBlockTypes

from _addons_common import geometry_node_utils, data_utils


SUPPORTED_BLENDER_VERSIONS: list[tuple[int, int, int]] = [(3, 3, 0)]

ASSET_ID_NOMENCLATURE = r"^\.(?P<prefix>[A-Z0-9_]+)_(?P<unique_name>[A-Za-z0-9_]+)$"

class BaseAssetLibrary(Enum):
    """Use this class to define a new asset library.
    """
    _ignore_ = (
        "SUPPORTED_BLENDER_VERSIONS",
        "DATAFILES_DIR",
        "ASSET_ID_NOMENCLATURE"
    )

    # Non-member attributes, these assignments are totally ignored
    # This is only for type-hinting
    # Non-member attributes must be assigned outside of class
    SUPPORTED_BLENDER_VERSIONS: list[tuple[int, int, int]] = SUPPORTED_BLENDER_VERSIONS  # type: ignore
    DATAFILES_DIR: Path = Path()  # type: ignore
    ASSET_ID_NOMENCLATURE: str = ASSET_ID_NOMENCLATURE

    @classmethod
    def __get_bpy_data_block(cls) -> bpy.types.bpy_prop_collection[bpy.types.ID]:
        return getattr(bpy.data, cls.get_bpy_data_block_type().value, None)

    @classmethod
    def __check_id_name(cls, id_name:str):
        match = re.fullmatch(
            cls.ASSET_ID_NOMENCLATURE,
            id_name
        )
        if match is None: 
            raise SyntaxError(
                f"Asset id_name {id_name} doesn't follow nomenclature : {cls.ASSET_ID_NOMENCLATURE}"
            )

    @classmethod
    def get_bpy_data_block_type(cls) -> DataBlockTypes:
        raise NotImplementedError

    def __init__(self, id_name: str, asset_path: str):
        """

        Args:
            id_name (str): Unique identifier of asset. 
                Must follow nomenclature (cf ASSET_ID_NOMENCLATURE)

            asset_path (str): Relative path to blend file in datafiles directory.
                Do not include version suffix and .blend extension.

                Example: 
                    'datafiles/assets/nodes/gizmos-3_3_0.blend' -> 'assets/nodes/gizmos'
    
        """
        self.__check_id_name(id_name)

        self.id_name: str = id_name
        self.label_name: str = id_name.replace(".", "")
        self.asset_path: str = asset_path

    @classmethod
    def get_by_id_name(cls, id_name: str) -> BaseAssetLibrary | None:
        """
        Retrieve an Asset entry by its id_name.
        """
        for entry in cls:
            if entry.id_name == id_name:
                return entry

        return None

    def get_latest_blend_path(self) -> Path:
        """Find the most recent blend file in datafiles/assets.

        Uses blend file naming convention : %name%-3_6_0.

        Returns:
            Absolute path to blend file.
        """
        found_library_path = None

        supported_version = False
        found_library_version = (0, 0, 0)

        for version in self.SUPPORTED_BLENDER_VERSIONS:
            if not bpy.app.version >= version or version <= found_library_version:
                continue
            supported_version = True
            _asset_path = library_utils.add_blend_version_suffix(self.asset_path, version)
            absolute_asset_path = self.DATAFILES_DIR / _asset_path
            if absolute_asset_path.exists():
                found_library_path = absolute_asset_path
                found_library_version = version

        if not supported_version:
            raise Exception(f"{bpy.app.version} is not supported!")

        if not found_library_path:
            raise Exception(f"Blend file of asset {self.id_name} was not found in {self.DATAFILES_DIR.as_posix()}!")

        return found_library_path

    def is_asset_instance(
        self, 
        asset: bpy.types.ID, 
        ignore_blend_version: bool = False
    ) -> bool:
        """Check if provided asset matches with Asset library entry.

        When ignore_blend_version is Enabled, we ignore msfs_asset_path version suffix.
        """
        blend_filepath = str(self.get_latest_blend_path())
        relative_blend_filepath = library_utils.absolute_to_relative_asset_path(
            blend_filepath, self.DATAFILES_DIR
        )
        if not relative_blend_filepath:
            return False

        return library_utils.is_asset_instance(
            asset, 
            self.id_name, 
            relative_blend_filepath, 
            ignore_blend_version
        )

    def append_asset(
        self
        ) -> bpy.types.ID | None:
        blend_filepath = str(self.get_latest_blend_path())
        return library_utils.append_asset(
            blend_filepath,
            self.DATAFILES_DIR,
            self.__class__.get_bpy_data_block_type().value,
            self.id_name,
            unique_mode=True,
        )

    def remove_asset(self, clean_dependencies: bool = True, no_users_only: bool = True) -> bool:
        """
        Remove all occurrences of this asset in file.

        When no_users_only is True, only IDs with 0 users are deleted.
        """
        

        blend_filepath = str(self.get_latest_blend_path())
        return library_utils.remove_asset(
            blend_filepath,
            self.DATAFILES_DIR,
            self.__class__.get_bpy_data_block_type().value,
            self.id_name,
            clean_dependencies,
            no_users_only=no_users_only,
        )

    @classmethod
    def remove_library_assets(cls, clean_dependencies: bool = True, no_users_only: bool = True):
        """
        Remove all occurrences of all library assets in current file.
        Also remove assets dependencies. 
        For example a node group can use other node groups.

        When no_users_only is True, only IDs with 0 users are deleted.

        """


        data_users_capture = None
        if clean_dependencies:
            data_users_capture = library_utils.capture_data_users()

        for asset in cls:
            # Clean dependencies after loop
            cls.remove_asset(asset, False, no_users_only)

        if clean_dependencies:
            library_utils.remove_data_without_users(data_users_capture)

    @classmethod
    def pre_remap_asset(cls, old_asset: bpy.types.ID, new_asset: bpy.types.ID):
        """Do something before updating an asset.
        """
        pass

    @classmethod
    def update_appended_assets(cls):
        """
        Update this asset library appended assets.
        """
        current_file = Path(bpy.path.abspath(bpy.data.filepath))
        datafiles_dir = cls.DATAFILES_DIR
        if cls.DATAFILES_DIR.as_posix() in current_file.as_posix():
            print(
                "Skip MSFS libraries link update since this file is an asset library source!"
            )
            return

        treated_assets: dict[str, bpy.types.bpy_struct] = {}
        to_delete: list[bpy.types.bpy_struct] = []
        data_block_type = bpy_data = cls.get_bpy_data_block_type()
        bpy_data = cls.__get_bpy_data_block()
        if not bpy_data:
            return 

        # Update assets
        for asset in bpy_data.values():
            if not asset: # can be None?
                continue

            if not data_utils.is_editable(asset):
                continue
            asset: bpy.types.ID

            relative_asset_path = library_utils.get_msfs_asset_path(asset)
            if not relative_asset_path:
                continue
            absolute_asset_path = library_utils.relative_to_absolute_asset_path(relative_asset_path, datafiles_dir)
            if not absolute_asset_path or not absolute_asset_path.exists():
                continue

            id_name = library_utils.get_asset_id_name(asset)


            asset_entry = cls.get_by_id_name(id_name)
            if not asset_entry:
                continue

            if not asset_entry.is_asset_instance(asset, ignore_blend_version=False):
                # TODO find a way to safely update asset like node groups
                continue

            new_asset = None
            if id_name in treated_assets:
                new_asset = treated_assets[id_name]
            else:
                # Rename old assets to prevent numbered suffix on appended asset
                asset.name = ".To_Purge"

                to_delete.append(asset)
                new_asset = asset_entry.append_asset()
                if not new_asset:
                    continue
                treated_assets[id_name] = new_asset

            if not new_asset:
                print(f"Asset couldn't be appended {id_name}")
                continue

            cls.pre_remap_asset(asset, new_asset)

            asset.user_remap(new_asset)

            print(f"Asset {data_block_type} - {id_name} - was updated")

        bpy.data.batch_remove(to_delete)

BaseAssetLibrary.SUPPORTED_BLENDER_VERSIONS = SUPPORTED_BLENDER_VERSIONS  # type: ignore
BaseAssetLibrary.DATAFILES_DIR = Path()  # type: ignore
BaseAssetLibrary.ASSET_ID_NOMENCLATURE = ASSET_ID_NOMENCLATURE # type: ignore
# region Node Groups Inputs


class NodeGroupInputs(Enum):
    def __init__(self, input_label):
        """
        Node groupe input labels.
        Labels must be unique.
        """
        self.input_label: str = input_label


class EmptyInputs(NodeGroupInputs):
    pass

class NodeGroupEnumInput(Enum):
    """
    Enum storing both the index and identifier of a node group enum input.

    Blender < 5.2 uses the enum index when assigning enum values.
    Blender >= 5.2 uses the enum identifier string instead.
    """

    def __init__(self, index: int, enum_string: str) -> None:
        self.index = index
        self.enum_string = enum_string
    
    @classmethod
    def get_enum_string(cls, index: int) -> str | None:
        for entry in cls:
            if entry.index == index:
                return entry.enum_string

        return None
    
    @classmethod
    def get_enum_string_index(cls, enum_string: str) -> int | None:
        for entry in cls:
            if entry.enum_string == enum_string:
                return entry.index

        return None
# endregion

# region Nodegroup

class NodeGroupLibrary(BaseAssetLibrary):
    """
    Library of node group assets.
    """

    @classmethod
    def get_bpy_data_block_type(cls) -> DataBlockTypes:
        return DataBlockTypes.NODE_GROUPS

    def __init__(
        self, id_name: str, asset_path: str, node_group_inputs: Type[NodeGroupInputs]
    ):
        super().__init__(id_name, asset_path)
        self.node_group_inputs = node_group_inputs

    @classmethod
    def pre_remap_asset(cls, old_node_group: bpy.types.NodeGroup, new_node_group: bpy.types.NodeGroup):
        # Special case for node groups, replace modifiers node groups before
        # remap in order to prevent loosing modifier user inputs.

        for obj in bpy.data.objects:
            for mod in obj.modifiers:
                if mod.type == 'NODES' and mod.node_group == old_node_group:
                    mod.node_group = new_node_group

    def add_modifier(
        self,
        object: bpy.types.Object,
    ) -> bpy.types.Modifier | None:
        """
        Appends a node_group and applies it
        as a modifier to the given object.
        """

        node_group = self.append_asset()

        if not node_group:
            raise Exception("Can't append node group!")

        # Create a new Geometry Nodes modifier
        modifier = object.modifiers.new(name=self.label_name, type="NODES")
        modifier.node_group = node_group
        if bpy.app.version >= (4, 0, 0):
            modifier.show_group_selector = False

        return modifier

    def get_modifier(
        self, 
        obj: bpy.types.Object, 
        ignore_blend_version: bool = True
    ) -> bpy.types.Modifier | None:
        """
        Get the first modifier using node group on object.
        """
        modifier = geometry_node_utils.get_modifier_by_node_group(
            obj, self.id_name)

        # Check if it is part of msfs_library
        if not modifier:
            return None

        if not self.is_asset_instance(modifier.node_group, ignore_blend_version):
            return None
        return modifier


# endregion

class ObjectLibrary(BaseAssetLibrary):
    """
    Library of object assets.
    """

    @classmethod
    def get_bpy_data_block_type(cls) -> DataBlockTypes:
        return DataBlockTypes.OBJECTS
    

    def __init__(
        self, id_name: str, asset_path: str, data_type: str
    ):
        super().__init__(id_name, asset_path)
        self.data_type: str = data_type
