# Copyright 2023-2024 The glTF-Blender-IO-MSFS2024 authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import bpy


class MSFS2024_DataUtils:

    @staticmethod
    def _data_is_valid(data: bpy.types.AnyType):
        try:
            data.name
            return True
        except ReferenceError:
            # Object deleted
            return False

    @staticmethod
    def get_all_data_blocks() -> dict[set]:
        """Construct a dictionary containing all sets of data in bpy.data.BlendData

        Returns:
            Dict of bpy.data.BlendData
        """
        data_blocks = {}
        for attr_name in dir(bpy.data):
            try:
                data_collection = getattr(bpy.data, attr_name)
            except AttributeError:
                continue

            if isinstance(data_collection, bpy.types.bpy_prop_collection):
                data_collection_copy = set()
                for data in data_collection:
                    if not MSFS2024_DataUtils._data_is_valid(data):
                        continue
                    data_collection_copy.add(data)
                data_blocks[attr_name] = data_collection_copy  # copy
        return data_blocks

    @staticmethod
    def _delete_data(data_type: str, data: bpy.types.ID):
        bpy_data = getattr(bpy.data, data_type, None)
        if not bpy_data:
            return
        if not MSFS2024_DataUtils._data_is_valid(data):
            return

        bpy_data.remove(data, do_unlink=True)

    @staticmethod
    def purge_new_data(original_data_blocks: dict[set], new_data_blocks: dict[set]):
        """Remove data from bpy.data if it is not present in
        original_data_blocks.

        Args:
            original_data_blocks: Dict of bpy.data.BlendData 
            new_data_blocks: Dict of bpy.data.BlendData
        """

        for data_type, new_data_set in new_data_blocks.items():

            original_data_set: set | None = original_data_blocks.get(data_type, None)

            if not new_data_set:
                continue
            to_delete = None
            if not original_data_set:
                # New data set was created
                to_delete = new_data_set
            else:
                to_delete = new_data_set.difference(original_data_set)

            if to_delete:
                # Make sure data is valid or it will crash!
                to_delete = MSFS2024_DataUtils.filter_deleted(to_delete)
                bpy.data.batch_remove(to_delete)

    @staticmethod
    def filter_deleted(
        data_array: list[bpy.types.AnyType] | set[bpy.types.AnyType],
    ) -> list[bpy.types.Object] | set[bpy.types.AnyType]:
        """Remove deleted object from list or set.

        Args:
            data_array: array of blender data

        Returns:
           List or Set of blender data
        """
        if isinstance(data_array, set):
            filtered_data = set()
            for data in data_array:
                if MSFS2024_DataUtils._data_is_valid(data):
                    filtered_data.add(data)
        elif isinstance(data_array, list):
            filtered_data = []
            for data in data_array:
                if MSFS2024_DataUtils._data_is_valid(data):
                    filtered_data.append(data)
        else:
            raise TypeError("data_array must be a set or list.")
        return filtered_data

    @staticmethod
    def set_msfs_original_name(data: bpy.types.AnyType, name: str):
        """Save data name in a msfs_original_name
        attribute.

        Used in msfs_export.py to reassign objects names after duplication.
        """
        if not data:
            return
        data["msfs_original_name"] = name

    @staticmethod
    def get_msfs_original_name(data: bpy.types.AnyType)->None|str:
        """Get msfs_original_name attribute.

        Used in msfs_export.py to reassign objects names after duplication.
        """
        original_object_name = data.get("msfs_original_name", None)
        return original_object_name

    @staticmethod
    def set_msfs_original_data(
        data: bpy.types.AnyType, original_data: bpy.types.AnyType
    ):
        """Save data in a msfs_original_data
        attribute.
        """
        if not data:
            return
        data["msfs_original_data"] = original_data

    @staticmethod
    def get_msfs_original_data(data: bpy.types.AnyType) -> None | bpy.types.AnyType:
        """Save data in a msfs_original_data
        attribute.
        """
        original_data = data.get("msfs_original_data", None)
        if original_data and not MSFS2024_DataUtils._data_is_valid(original_data):
            return None
        return original_data
