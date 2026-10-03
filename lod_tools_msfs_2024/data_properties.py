from __future__ import annotations

from typing import Iterable
import bpy

from enum import Enum


from io_scene_gltf2_msfs_fss.io.exp.lod_groups import MultiExporterLODGroup
from lod_tools_msfs_2024 import lod_limits, vertex_count

MSFS_LOD_VIEWER_TAG_PROP = "msfs_lod_viewer_tag"
MSFS_LOD_VIEWER_PROP = "msfs_lod_viewer"

class LODViewerTags(Enum):
    NONE = ("NONE", "None")
    LOD_CAMERA = ("LOD_CAMERA", "Camera")
    LOD_VIEWER = ("LOD_VIEWER", "Viewer")
    LOD_COLLECTION = ("LOD_COLLECTION", "LOD Collection")
    LOD_VIEWER_COLLECTION = ("LOD_VIEWER_COLLECTION", "LOD Viewer Collection") # Collection containing lod viewer objects
    LOD_VIEWER_DATA = ("LOD_VIEWER_DATA", "Viewer Data")

    def __init__(self, identifier: str, label: str):
        self.identifier = identifier
        self.label = label

    @classmethod
    def from_identifier(cls, identifier: str) -> ObjectTags | None:
        for mode in cls:
            if mode.identifier == identifier:
                return mode
        return None

def _has_tag(data: bpy.types.ID, tag: LODViewerTags):
    _tag = get_lod_viewer_tag(data)
    if not _tag:
        return False
    return _tag == tag

LOD_VIEWER_TAG_ENUM_ITEMS = (
    (
        LODViewerTags.NONE.identifier,
        LODViewerTags.NONE.label,
        "Not a LOD Viewer object.",
        "",
        0,
    ),
    (
        LODViewerTags.LOD_CAMERA.identifier,
        LODViewerTags.LOD_CAMERA.label,
        "Camera used to preview LOD transitions",
        "",
        1,
    ),
    (
        LODViewerTags.LOD_VIEWER.identifier,
        LODViewerTags.LOD_VIEWER.label,
        "Object with a Geometry Node modifier controling LOD transitions",
        "",
        2,
    ),
    (
        LODViewerTags.LOD_COLLECTION.identifier,
        LODViewerTags.LOD_COLLECTION.label,
        "LOD Collection used by LOD Viewer geometry node",
        "",
        3,
    ),
    (
        LODViewerTags.LOD_VIEWER_COLLECTION.identifier,
        LODViewerTags.LOD_VIEWER_COLLECTION.label,
        "Collection containing LOD Viewer Objects",
        "",
        4,
    ),
    (
        LODViewerTags.LOD_VIEWER_DATA.identifier,
        LODViewerTags.LOD_VIEWER_DATA.label,
        "Data used by LOD Viewer (Collections, objects etc)",
        "",
        5,
    ),
)


class LODStats(bpy.types.PropertyGroup):

    index: bpy.props.IntProperty(name="Level Index", default=0)  # type: ignore

    vertex_count: bpy.props.IntProperty(name="Vertex Count", default=0)  # type: ignore

    min_size: bpy.props.FloatProperty(
        name="Minimum screen Size provided by user. Equal 0 when not provided",
        default=0,
    )  # type: ignore

    estimated_min_size: bpy.props.FloatProperty(
        name="Minimum Screen Size with current vertex count", default=0.01
    )  # type: ignore

    def get_size_to_use(self, percentage: bool = False):
        # Use the value that pushes this LOD further
        size = max(self.min_size, self.estimated_min_size)
        if percentage:
            size *= 100
        return size


class LODViewerProps(bpy.types.PropertyGroup):

    export_mode: bpy.props.StringProperty(
        name="Mode",
        default="",
        description=(
            "Active export mode when LOD viewer was created.\n"
            "Valid when type is LOD_VIEWER"
        ),
    )  # type: ignore

    exporter_source_data_path: bpy.props.StringProperty(
        name="Source data path",
        default="",
        description=(
            "Context path for a MultiExporterLODGroup\n" "Valid when type is LOD_VIEWER"
        ),
    )  # type: ignore

    exporter_source_name: bpy.props.StringProperty(
        name="Source Name",
        default="",
        description=("Name of MultiExporterLODGroup\n" "Valid when type is LOD_VIEWER"),
    )  # type: ignore

    lod_stats: bpy.props.CollectionProperty(
        name="LOD stats",
        type=LODStats,
        description=("LOD Statistics\n" "Valid when type is LOD_VIEWER"),
    )  # type: ignore


class LODViewerScene(bpy.types.PropertyGroup):

    # region LOD Viewer props
    lod_viewer_collection: bpy.props.PointerProperty(
        type=bpy.types.Collection,
        name="LOD Viewer Collection",
        description="Collection containing lod viewers of this scene",
    )  # type: ignore

    lod_viewer_node_group: bpy.props.PointerProperty(
        type=bpy.types.NodeTree,
        name="LOD Viewer Node Group",
        description="LOD Viewer Node group used in this scene.",
    )  # type: ignore

    lod_viewer_constants_node_group: bpy.props.PointerProperty(
        type=bpy.types.NodeTree,
        name="LOD Viewer Constants Node Group",
        description="LOD Viewer Node group used in this scene.",
    )  # type: ignore

    lod_camera_proxy: bpy.props.PointerProperty(
        type=bpy.types.Object,
        name="LOD Viewer Camera Proxy",
        description="Empty Object that follows viewport transforms.",
    )  # type: ignore

    def reset(self):
        self.lod_camera_proxy = None
        self.lod_viewer_node_group = None
        self.lod_viewer_constants_node_group = None

def set_scene_lod_camera(scene: bpy.types.Scene, camera: bpy.types.Object| None):
    lod_viewer_scene_props : LODViewerScene = get_msfs_lod_viewer_prop(scene)
    if lod_viewer_scene_props is None:
        return 

    scene.camera = camera
    # Store it in our own property group in case user edits scene.camera attribute
    lod_viewer_scene_props.lod_camera_proxy = camera

def set_scene_lod_node_groups(
    scene: bpy.types.Scene,
    lod_viewer_collection: bpy.types.Collection | None,
    lod_viewer_node_groups: bpy.types.NodeTree | None,
    lod_viewer_constants_node_group: bpy.types.NodeTree | None,
):
    lod_viewer_scene_props: LODViewerScene = get_msfs_lod_viewer_prop(scene)
    if lod_viewer_scene_props is None:
        return

    lod_viewer_scene_props.lod_viewer_collection = lod_viewer_collection
    lod_viewer_scene_props.lod_viewer_node_group = lod_viewer_node_groups
    lod_viewer_scene_props.lod_viewer_constants_node_group = (
        lod_viewer_constants_node_group
    )


def reset_scene_lod_viewer_props(scene: bpy.types.Scene):
    lod_viewer_scene_props : LODViewerScene = get_msfs_lod_viewer_prop(scene)
    if lod_viewer_scene_props is None:
        return None
    
    lod_viewer_scene_props.reset()


def evaluate_data_path(path: str) -> Any | None:
    try:
        data = eval(path)
        return data
    except:
        return None


def get_msfs_lod_viewer_prop(
    data_block: bpy.types.Object | bpy.types.Scene | bpy.types.Collection,
) -> LODViewerProps | LODViewerScene | None:
    return getattr(data_block, MSFS_LOD_VIEWER_PROP, None)


def _set_lod_viewer_tag(
    data_block: bpy.types.Object | bpy.types.Collection, tag: LODViewerTags
):
    setattr(data_block, MSFS_LOD_VIEWER_TAG_PROP, tag.identifier)


def get_lod_viewer_tag(data_block: bpy.types.ID) -> LODViewerTags | None:

    tag = getattr(data_block, MSFS_LOD_VIEWER_TAG_PROP, None)
    if not tag:
        return None
    lod_viewer_tag = LODViewerTags.from_identifier(tag)
    return lod_viewer_tag


# region LOD Camera
def tag_as_lod_camera(camera: bpy.types.Object):
    _set_lod_viewer_tag(camera, LODViewerTags.LOD_CAMERA)


def is_lod_camera(obj: bpy.types.Object) -> bool:
    if not obj.type == "CAMERA":
        return False
    return _has_tag(obj, LODViewerTags.LOD_CAMERA)


# endregion


# region LOD Viewer
def tag_as_lod_viewer(obj: bpy.types.Object):
    _set_lod_viewer_tag(obj, LODViewerTags.LOD_VIEWER)

def is_lod_viewer(obj: bpy.types.Object) -> bool:
    return _has_tag(obj, LODViewerTags.LOD_VIEWER)

def set_lod_viewer_source(
    obj: bpy.types.Object, exporter_source_data_path: str, exporter_source_name: str
):
    lod_viewer_prop = get_msfs_lod_viewer_prop(obj)
    if not lod_viewer_prop:
        return
    lod_viewer_prop.exporter_source_data_path = exporter_source_data_path
    lod_viewer_prop.exporter_source_name = exporter_source_name


def get_lod_viewer_source_data(obj: bpy.types.Object) -> tuple[str, str] | None:
    """Get source data info (data path, data name)"""
    lod_viewer_prop = get_msfs_lod_viewer_prop(obj)
    if not lod_viewer_prop:
        return None
    return (
        lod_viewer_prop.exporter_source_data_path,
        lod_viewer_prop.exporter_source_name,
    )


class OutdatedLodGroup:
    # Sentinel value
    pass


def get_lod_viewer_source(
    obj: bpy.types.Object,
) -> MultiExporterLODGroup | type[OutdatedLodGroup] | None:
    source_data_info = get_lod_viewer_source_data(obj)
    if source_data_info is None:
        return None
    data_path, name = source_data_info
    exporter_lod_group = evaluate_data_path(data_path)
    if not isinstance(exporter_lod_group, MultiExporterLODGroup):
        return None
    if exporter_lod_group.name != name:
        # User has generated new lod groups
        return OutdatedLodGroup

    return exporter_lod_group


def add_lod_stats_entry(
    lod_viewer_obj: bpy.types.Object,
    index: int,
) -> LODStats | None:
    lod_viewer_prop = get_msfs_lod_viewer_prop(lod_viewer_obj)
    if not lod_viewer_prop:
        return None
    lod_stats_entry: LODStats = lod_viewer_prop.lod_stats.add()
    lod_stats_entry.index = index
    return lod_stats_entry


def compute_stats(
    lod_stats_entry: LODStats,
    index: int,
    lod_count: int,
    lod_objects: Iterable[bpy.types.Object],
    depsgraph: bpy.types.Depsgraph,
):
    lod_stats_entry.vertex_count = vertex_count.get_gltf_objects_vertex_count(
        objects=list(lod_objects), depsgraph=depsgraph
    )
    is_last_lod = (index + 1) == lod_count
    is_second_to_last_lod = (index + 2) == lod_count

    lod_stats_entry.estimated_min_size = lod_limits.lowest_screen_size_from_vcount(
        lod_stats_entry.vertex_count
    )
    if is_last_lod:
        empty_factor = 1
        if lod_stats_entry.vertex_count == 0:
            empty_factor = 0.01
        lod_stats_entry.estimated_min_size = max(
            lod_stats_entry.estimated_min_size,
            lod_limits.get_last_lod_min_screen_size_ratio() * empty_factor,
        )

    if is_second_to_last_lod:
        lod_stats_entry.estimated_min_size = max(
            lod_stats_entry.estimated_min_size,
            lod_limits.get_second_to_last_lod_min_screen_size_ratio(),
        )


def get_lod_stats_entry(
    lod_viewer_obj: bpy.types.Object, index: int
) -> LODStats | None:
    lod_viewer_prop = get_msfs_lod_viewer_prop(lod_viewer_obj)
    if not lod_viewer_prop:
        return None
    try:
        lod_stats_entry: LODStats = lod_viewer_prop.lod_stats[index]
    except IndexError:
        return None

    return lod_stats_entry


def get_lod_stats_entries(lod_viewer_obj: bpy.types.Object) -> list[LODStats] | None:
    lod_viewer_prop = get_msfs_lod_viewer_prop(lod_viewer_obj)
    if not lod_viewer_prop:
        return None

    return lod_viewer_prop.lod_stats


# endregion

def tag_as_lod_viewer_data(data: bpy.types.Object | bpy.types.Collection):
    _set_lod_viewer_tag(data, LODViewerTags.LOD_VIEWER_DATA)

def is_lod_viewer_data(data: bpy.types.Object | bpy.types.Collection):
    return _has_tag(data, LODViewerTags.LOD_VIEWER_DATA)


# region LOD Viewer Collection
def tag_as_lod_collection(collection: bpy.types.Collection):
    _set_lod_viewer_tag(collection, LODViewerTags.LOD_COLLECTION)


def is_lod_collection(collection: bpy.types.Collection) -> bool:
    return _has_tag(collection, LODViewerTags.LOD_COLLECTION)


def tag_as_lod_viewer_collection(collection: bpy.types.Collection):
    _set_lod_viewer_tag(collection, LODViewerTags.LOD_VIEWER_COLLECTION)


def is_lod_viewer_collection(collection: bpy.types.Collection) -> bool:
    return _has_tag(collection, LODViewerTags.LOD_VIEWER_COLLECTION)


# endregion


def register():

    setattr(
        bpy.types.Object,
        MSFS_LOD_VIEWER_TAG_PROP,
        bpy.props.EnumProperty(
            name="Tag",
            default=LODViewerTags.NONE.identifier,
            items=LOD_VIEWER_TAG_ENUM_ITEMS,
        ),  # type: ignore
    )
    setattr(
        bpy.types.Collection,
        MSFS_LOD_VIEWER_TAG_PROP,
        bpy.props.EnumProperty(
            name="Tag",
            default=LODViewerTags.NONE.identifier,
            items=LOD_VIEWER_TAG_ENUM_ITEMS,
        ),  # type: ignore
    )

    setattr(bpy.types.Object, MSFS_LOD_VIEWER_PROP, bpy.props.PointerProperty(type=LODViewerProps, name="LOD Viewer"))  # type: ignore
    setattr(bpy.types.Scene, MSFS_LOD_VIEWER_PROP, bpy.props.PointerProperty(type=LODViewerScene, name="LOD Viewer"))  # type: ignore


def unregister():

    try:
        delattr( bpy.types.Object, MSFS_LOD_VIEWER_TAG_PROP)  # type: ignore
        delattr( bpy.types.Collection, MSFS_LOD_VIEWER_TAG_PROP)  # type: ignore
        delattr( bpy.types.Collection, MSFS_LOD_VIEWER_PROP)  # type: ignore
        delattr( bpy.types.Scene, MSFS_LOD_VIEWER_PROP)  # type: ignore



    except:
        pass
