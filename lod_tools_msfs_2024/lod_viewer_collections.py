from typing import Iterable

import bpy

from lod_tools_msfs_2024 import data_properties, active_lod_viewer
from lod_tools_msfs_2024.datafiles import asset_library

LOD_VIEWER_COL_NAME = "--LOD Viewers--"

def get_all_lod_viewer_collections(
    scene: bpy.types.Scene,
) -> list[bpy.types.Collection] | None:
    collections = []
    for collection in scene.collection.children_recursive:
        if data_properties.is_lod_viewer_collection(collection):
            collections.append(collection)

    return collections

def get_scene_lod_viewer_collection(
    scene: bpy.types.Scene,
) -> bpy.types.Collection | None:
    """Get first lod viewer collection found at scene root.
    This function is supposed to be fast since it is used in debug draw.
    """

    lod_viewer_col = scene.collection.children.get(LOD_VIEWER_COL_NAME)
    if lod_viewer_col and data_properties.is_lod_viewer_collection(lod_viewer_col):
        return lod_viewer_col
    
    for collection in scene.collection.children:
        if data_properties.is_lod_viewer_collection(collection):
            return collection

    return None

def create_lod_viewer_collection(scene: bpy.types.Scene) -> bpy.types.Collection:
    lod_viewer_collection = bpy.data.collections.new(LOD_VIEWER_COL_NAME)
    data_properties.tag_as_lod_viewer_collection(lod_viewer_collection)
    lod_viewer_collection.color_tag = "COLOR_04"  # Green

    return lod_viewer_collection


def delete_lod_viewer_objects(lod_viewer_collection: bpy.types.Collection):
    """Delete lod viewer objects and their associated data
    """
    to_delete = []
    for obj in lod_viewer_collection.all_objects:
        if data_properties.get_lod_viewer_tag(obj) is not None:
            to_delete.append(obj)
            if hasattr(obj, "data"):
                to_delete.append(obj.data)

    bpy.data.batch_remove(to_delete)
    # Prevent memory exception with UI trying to access deleted modifier
    active_lod_viewer.ActiveLODViewer.reset()
    
def clean_scene_lod_viewer_collection(scene: bpy.types.Scene):
    """
    Remove all trace of scene lod viewers in bpy.data
    """
    scene_lod_viewer_collections = get_all_lod_viewer_collections(scene)

    if scene_lod_viewer_collections:
        for col in scene_lod_viewer_collections:
            # clean existing object
            # Remove object with lod_viewer tag
            delete_lod_viewer_objects(col)
            bpy.data.collections.remove(col)

    delete_lod_collections(no_users_only=True)

    data_properties.reset_scene_lod_viewer_props(scene)
    
    # Delete library assets
    asset_library.ObjectLibrary.remove_library_assets(no_users_only=True)
    asset_library.NodeGroupLibrary.remove_library_assets(no_users_only=True)


def init_scene_lod_viewer_collection(scene: bpy.types.Scene) -> bpy.types.Collection:
    """Get or create the collection that will contain all lod viewer objects.
    Delete additionnal lod viewer collection since we only need one per scene.
    """
    clean_scene_lod_viewer_collection(scene)
    lod_viewer_collection = create_lod_viewer_collection(scene)
    try:
        scene.collection.children.link(lod_viewer_collection)
    except:
        # already in collection--
        pass

    return lod_viewer_collection


def create_lod_collection(
    name:str,
    lod_index:int,
    objects: list[bpy.types.Object]
) -> bpy.types.Collection:
    """Create a hidden collection.
    """
    collection = bpy.data.collections.new(f".{name}_LOD{lod_index}")
    data_properties.tag_as_lod_collection(collection)

    
    for obj in objects:
        collection.objects.link(obj)

    return collection

def create_lod_data_collection(
    name:str,
    lod_index:int,
    objects: Iterable[bpy.types.Object]
) -> bpy.types.Collection:
    """Create a hidden collection.
    """
    collection = bpy.data.collections.new(f".{name}_LOD{lod_index}")
    data_properties.tag_as_lod_viewer_data(collection)

    
    for obj in objects:
        collection.objects.link(obj)

    return collection

def delete_lod_collections(no_users_only: bool = True):
    """Delete lod collections. 
    When no_users_only is True, only lod collection
    with 0 users are deleted.
    """
    to_delete = []
    for col in bpy.data.collections:
        if no_users_only and col.users != 0:
            continue
        if data_properties.is_lod_collection(col):
            to_delete.append(col)
        elif data_properties.is_lod_viewer_data(col):
            to_delete.append(col)

    for obj in bpy.data.objects:
        if no_users_only and obj.users != 0:
            continue
        elif data_properties.is_lod_viewer_data(obj):
            to_delete.append(obj)

    bpy.data.batch_remove(to_delete)
