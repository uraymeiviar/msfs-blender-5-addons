from __future__ import annotations

from typing import TYPE_CHECKING, Iterable
import bpy
import mathutils

from dataclasses import dataclass, field
from uuid import UUID, uuid4

from lod_tools_msfs_2024 import (
    data_properties,
    lod_viewer_collections,
    data_utils,
    collections_utils,
    obj_utils
)


from io_scene_gltf2_msfs_fss.io.exp import multi_export_mode

from io_scene_gltf2_msfs_fss.io.exp import export_settings
from io_scene_gltf2_msfs_fss.io.exp import lod_groups as exp_lod_groups
from io_scene_gltf2_msfs_fss.io.exp import presets as exp_presets


if TYPE_CHECKING:
    from io_scene_gltf2_msfs_fss.io.exp.lod_groups import MultiExporterLOD, MultiExporterLODGroup
    from io_scene_gltf2_msfs_fss.io.exp.presets import MultiExporterPresetGroup


@dataclass
class RootOriginSettings:
    reset_translation: bool = False
    reset_rotation: bool = False
    reset_scale: bool = False

@dataclass
class LODGroupInfos:
    """Contain info for a group of lods.
    Used to generate LOD Viewers in scene.
    """
    # Make class hashable
    uid: UUID = field(default_factory=uuid4, init=False)

    def __hash__(self):
        return hash(self.uid)

    name: str = ""

    exporter_source_data_path: str = ""  # Path to exporter LODGroup

    lod_count: int = 1

    root_origin_settings: RootOriginSettings | None = None # Settings applied to all LOD Roots

    has_per_object_origin_settings: bool = False

    lod_viewer_offset: mathutils.Matrix | None = None # LOD Viewer Offset from LOD0 first root

    lod0_collection: bpy.types.Collection | None = None
    lod1_collection: bpy.types.Collection | None = None
    lod2_collection: bpy.types.Collection | None = None
    lod3_collection: bpy.types.Collection | None = None
    lod4_collection: bpy.types.Collection | None = None
    lod5_collection: bpy.types.Collection | None = None
    lod6_collection: bpy.types.Collection | None = None
    lod7_collection: bpy.types.Collection | None = None
    lod8_collection: bpy.types.Collection | None = None

    lod0_objects: list[bpy.types.Object] | None = None
    lod1_objects: list[bpy.types.Object] | None = None
    lod2_objects: list[bpy.types.Object] | None = None
    lod3_objects: list[bpy.types.Object] | None = None
    lod4_objects: list[bpy.types.Object] | None = None
    lod5_objects: list[bpy.types.Object] | None = None
    lod6_objects: list[bpy.types.Object] | None = None
    lod7_objects: list[bpy.types.Object] | None = None
    lod8_objects: list[bpy.types.Object] | None = None

    lod0_min_size: float = 0
    lod1_min_size: float = 0
    lod2_min_size: float = 0
    lod3_min_size: float = 0
    lod4_min_size: float = 0
    lod5_min_size: float = 0
    lod6_min_size: float = 0
    lod7_min_size: float = 0
    lod8_min_size: float = 0
    
    def get_lod_collection(self, level: int) -> bpy.types.Collection | None:
        return getattr(self, f"lod{level}_collection", None)

    def get_lod_collection_objects(self, level: int) -> list[bpy.types.Object] | None:
        """Get all objects in lod collection.
        May not contain original lod objects but collection instances instead.
        """
        collection = self.get_lod_collection(level)
        if not collection:
            return []
        else:
            return list(collection.all_objects)

    def set_lod_collection(self, level: int, collection: bpy.types.Collection):
        return setattr(self, f"lod{level}_collection", collection)

    def get_lod_objects(self, level: int) -> list[bpy.types.Object] | None:
        """Return lod original objects.
        Objects that will be used to compute LOD Vertex count.
        """
        return getattr(self, f"lod{level}_objects", None)

    def set_lod_objects(self, level: int, objects: list[bpy.types.Object]):
        """Set lod original objects.
        Objects that will be used to compute LOD Vertex count.
        """
        return setattr(self, f"lod{level}_objects", objects)

    def get_lod_min_size(self, level: int) -> float:
        return getattr(self, f"lod{level}_min_size", 0)

    def set_lod_min_size(self, level: int, min_size: float):
        return setattr(self, f"lod{level}_min_size", min_size)

def _get_roots(objects: Iterable[bpy.types.Object])->list[bpy.types.Object]:
    valid_roots = []
    objects = set(objects)
    for obj in objects:
        if data_utils.data_is_valid(obj) and (not obj.parent or obj.parent not in objects):
            valid_roots.append(obj)
    return valid_roots


def get_first_without_parent(
    objects: Iterable[bpy.types.Object],
) -> bpy.types.Object | None:
    for obj in objects:
        if not obj.parent:
            return obj
    return None


def _get_lod_valid_roots(
    lod: MultiExporterLOD, export_mode: multi_export_mode.ExportMode
) -> list[bpy.types.Object] | None:
    if export_mode == multi_export_mode.ExportMode.OBJECTS:
        root_obj = lod.objectLOD
        if not root_obj or not data_utils.data_is_valid(root_obj):
            return None
        return [root_obj]
    elif export_mode == multi_export_mode.ExportMode.COLLECTIONS:
        collection: bpy.types.Collection = lod.collection
        if not collection or not collection.objects:
            return None
        return _get_roots(collection.objects)
    return None


def _capture_export_settings(
    lod_group_source: MultiExporterLODGroup | MultiExporterPresetGroup,
    lod_group_infos: LODGroupInfos,
):
    """Get export settings from source and store them in lod_group_infos.
    """
    group_export_settings = lod_group_source.get_export_settings_preset()
    if group_export_settings:
        if group_export_settings.reset_origins == export_settings.ResetOriginMode.ALL_ROOTS.identifier:
            export_transform_properties = group_export_settings.export_transform_properties
            if not (export_transform_properties.reset_translation or export_transform_properties.reset_rotation or export_transform_properties.reset_scale):
                # User enabled reset origin but disable all reset options
                origin_settings = None
            else:

                origin_settings = RootOriginSettings(reset_translation=export_transform_properties.reset_translation,
                                                    reset_rotation=export_transform_properties.reset_rotation,
                                                    reset_scale=export_transform_properties.reset_scale)

            lod_group_infos.root_origin_settings = origin_settings
        elif group_export_settings.reset_origins == export_settings.ResetOriginMode.PER_OBJECT.identifier:
            # settings are retrieved on objects
            lod_group_infos.has_per_object_origin_settings = True


def _capture_lod_viewer_offset(
    lod0_root: bpy.types.Object, lod_group_infos: LODGroupInfos
):
    """Get lod0 root offset from world origin.
    Used later to move lod viewer back to source position.

    Scale is ignored.
    """
    if not (lod_group_infos.root_origin_settings or lod_group_infos.has_per_object_origin_settings):
        return
    lod_viewer_offset = None

    has_translation_offset = False
    has_rotation_offset = False
    if lod_group_infos.root_origin_settings:
        has_translation_offset = (
            lod_group_infos.root_origin_settings.reset_translation,
        )
        has_rotation_offset = lod_group_infos.root_origin_settings.reset_rotation
    elif lod_group_infos.has_per_object_origin_settings:
        has_translation_offset = lod0_root.msfs_export_transform.reset_translation
        has_rotation_offset = lod0_root.msfs_export_transform.reset_rotation
    offset_translation = mathutils.Vector()
    offset_rotation = mathutils.Quaternion()
    if has_translation_offset:
        offset_translation = lod0_root.matrix_world.translation
    if has_rotation_offset:
        offset_rotation = lod0_root.matrix_world.to_quaternion()
    lod_viewer_offset = mathutils.Matrix.LocRotScale(
        offset_translation, offset_rotation, None
    )

    lod_group_infos.lod_viewer_offset = lod_viewer_offset


def _create_lod_root_with_resetted_transforms(
    name: str,
    lod_index: int,
    root_obj: bpy.types.Object,
    lod_objects: list[bpy.types.Object],
    reset_translation: bool = False,
    reset_rotation: bool = False,
    reset_scale: bool = False
)->list[bpy.types.Object] :
    """Create a LOD root with selected transforms reset.

    Simulates the transform reset done during gltf export.

    Returns:
        Lod objects (One empty and a collection instance children)
    """

    if root_obj.type == "EMPTY" and not root_obj.children:
        return []
    # Create a collection containing all lod objects under root and instantiate it
    root_objects = set((root_obj, *root_obj.children_recursive))
    root_lod_objects = set(lod_objects).intersection(root_objects)

    collection = lod_viewer_collections.create_lod_data_collection(
        name, lod_index, root_lod_objects
    )
    collection_inst = collections_utils.instantiate_collection(
        collection
    )

    # Hide collection instance empty with a size of 0 and disable selection
    # Can't use collection_inst.hide_viewport here, or meshes will not be visible in viewport
    collection_inst.empty_display_size = 0
    collection_inst.hide_select = True

    # Tag it so it can be retrieved and deleted later
    data_properties.tag_as_lod_viewer_data(collection_inst)

    # Create empty that we are going to use to apply the transform reset
    empty_obj = bpy.data.objects.new(
        name=collection.name, object_data=None
    )
    data_properties.tag_as_lod_viewer_data(empty_obj)
    # Hide in viewport
    empty_obj.hide_viewport = True
    empty_obj.hide_select = True

    # Copy LOD root Transform and parent collection instance to empty

    empty_obj.matrix_world = root_obj.matrix_world.copy()
    obj_utils.set_parent_keep_transform(collection_inst, empty_obj)

    # Now we can apply the transform reset
    obj_utils.reset_transform(
        empty_obj,
        reset_translation,
        reset_rotation,
        reset_scale,
    )

    return [empty_obj, collection_inst]


def filter_msfs_lod_groups(
    mfs_lod_groups: list | bpy.types.bpy_prop_collection,
    export_mode: (
        multi_export_mode.ExportMode.OBJECTS | multi_export_mode.ExportMode.COLLECTIONS
    ),
    logging: bool = False
)->list:

    filtered = []
    for lod_group in mfs_lod_groups:
        if lod_group.autogenerate_lods:
            if logging:
                print(f"Skip Lod group {lod_group.name} : Auto LOD is enabled")
            continue
        if not len(lod_group.lods) > 1:
            if logging:
                print(f"Skip Lod group {lod_group.name} : only one LOD")
            continue

        lod0_roots = _get_lod_valid_roots(lod_group.lods[0], export_mode)
        if not lod0_roots:
            if logging:
                print(f"Skip Lod group {lod_group.name} : LOD0 has been deleted")
            continue

        last_lod_roots = _get_lod_valid_roots(lod_group.lods[-1], export_mode)
        if not last_lod_roots:
            if logging:
                print(f"Skip Lod group {lod_group.name} : Last LOD has been deleted")
            continue

        if data_properties.is_lod_viewer(lod0_roots[0]):
            continue
        filtered.append(lod_group)

    return filtered


def get_objects_lod_group_infos(
    msfs_lod_groups: list | bpy.types.bpy_prop_collection,
    temp_scene: bpy.types.Scene,
    export_mode: (
        multi_export_mode.ExportMode.OBJECTS | multi_export_mode.ExportMode.COLLECTIONS
    ),
)->list[LODGroupInfos]:       
    lod_group_infos =  []
    msfs_lod_groups = filter_msfs_lod_groups(msfs_lod_groups, export_mode, True)
    for i, lod_group in enumerate(msfs_lod_groups):

        # Check if first and last lods seem valid
        lod0_roots = _get_lod_valid_roots(lod_group.lods[0], export_mode)
        if not lod0_roots:
            continue

        last_lod_roots = _get_lod_valid_roots(lod_group.lods[-1], export_mode)
        if not last_lod_roots:
            continue

        _lod_group_infos = LODGroupInfos(
            name=lod_group.name,
            exporter_source_data_path=lod_group.full_data_path,
            lod_count=len(lod_group.lods)
        )

        valid_lods = True

        _capture_export_settings(lod_group, _lod_group_infos)
        _capture_lod_viewer_offset(lod0_roots[0], _lod_group_infos)

        for i, lod in enumerate(lod_group.lods):

            lod_roots = _get_lod_valid_roots(lod, export_mode)
            if not lod_roots:
                # Ignore entire lod group is one of the lod object is deleted
                valid_lods = False
                break

            lod_objects = lod.get_lod_objects(export_mode)
            if not lod_objects:
                valid_lods = False
                break

            # Make sure lod objects are visible for depsgraph eval later
            # If not done evaluated object is empty
            obj_utils.set_viewport_hidden(lod_objects, False)

            lod_collection = None
            if _lod_group_infos.root_origin_settings:   
                resetted_lod_objects = []
                for root in lod_roots:
                    resetted_lod_objects.extend(_create_lod_root_with_resetted_transforms(
                        name=lod_group.name,
                        lod_index=i,
                        root_obj=root,
                        lod_objects=lod_objects,
                        reset_translation=_lod_group_infos.root_origin_settings.reset_translation,
                        reset_rotation=_lod_group_infos.root_origin_settings.reset_rotation,
                        reset_scale=_lod_group_infos.root_origin_settings.reset_scale,
                    ))
                lod_collection = lod_viewer_collections.create_lod_collection(
                    lod_group.name, i, resetted_lod_objects
                )
            elif _lod_group_infos.has_per_object_origin_settings:
                resetted_lod_objects = []
                for root in lod_roots:
                    resetted_lod_objects.extend(_create_lod_root_with_resetted_transforms(
                        name=lod_group.name,
                        lod_index=i,
                        root_obj=root,
                        lod_objects=lod_objects,
                        reset_translation=root.msfs_export_transform.reset_translation,
                        reset_rotation=root.msfs_export_transform.reset_rotation,
                        reset_scale=root.msfs_export_transform.reset_scale,
                    ))
                lod_collection = lod_viewer_collections.create_lod_collection(
                    lod_group.name, i, resetted_lod_objects
                )

            else:
                lod_collection = lod_viewer_collections.create_lod_collection(
                    lod_group.name,
                    i,
                    lod_objects
                )

            if not lod_collection:
                valid_lods = False
                break
            # Add to temp_scene in order to be evaluated later
            temp_scene.collection.children.link(lod_collection)

            min_size = 0
            if lod.lod_value > 0:
                min_size = lod.lod_value / 100
            _lod_group_infos.set_lod_objects(i, lod_objects)
            _lod_group_infos.set_lod_collection(i, lod_collection)
            _lod_group_infos.set_lod_min_size(i, min_size)

        if valid_lods:
            lod_group_infos.append(_lod_group_infos)

    return lod_group_infos

def filter_msfs_preset_groups(
    msfs_preset_groups: dict | bpy.types.bpy_prop_collection,
    grouped_preset_dict: dict | None = None,
    logging: bool = False
)->list:

    filtered = []
    for group_id, presets in grouped_preset_dict.items():
        group = msfs_preset_groups.get(group_id, None)
        if not group or not presets:
            continue
        if not len(presets) > 1:
            if logging:
                print(f"Skip Lod group {group.group_name} : only one LOD")
            continue
        
        lod0_preset = presets[0]
        lod_objects = lod0_preset.get_preset_objects()
        if not lod_objects:
            if logging:
                print(f"Skip Lod group {group.group_name} : Empty LOD0")
            continue

        lod0_roots = _get_roots(lod_objects)
        if not lod0_roots:
            continue
        if data_properties.is_lod_viewer(lod0_roots[0]):
            continue
        filtered.append(group)
        
    return filtered

def construct_grouped_preset_dict(scene: bpy.types.Scene) -> dict[str, list]:
    """Create a dict associating group_id and their presets.
    Returns:
        dict 
        key : group_id.
        value : list of presets in the group.
    """
    msfs_presets = exp_presets.get_scene_exporter_presets(scene)
    grouped_preset_dict: dict[str, list] = {}

    for preset in msfs_presets:
        preset_list = grouped_preset_dict.get(preset.group_id, None)
        if preset_list is None:
            preset_list = []
            grouped_preset_dict[preset.group_id] = preset_list
        preset_list.append(preset)

    return grouped_preset_dict


def get_presets_lod_group_infos(
    msfs_preset_groups: dict | bpy.types.bpy_prop_collection,
    scene: bpy.types.Scene,
    temp_scene: bpy.types.Scene):

    grouped_preset_dict = construct_grouped_preset_dict(scene)
    if not grouped_preset_dict:
        return []
    
    msfs_preset_groups = filter_msfs_preset_groups(msfs_preset_groups, grouped_preset_dict, True)
    lod_group_infos = []

    for group in msfs_preset_groups:
        presets = grouped_preset_dict.get(group.name)
        if not presets:
            continue
        lod0_preset = presets[0]
        lod_objects = lod0_preset.get_preset_objects()
        if not lod_objects:
            continue

        lod0_roots = _get_roots(lod_objects)
        if not lod0_roots:
            continue

        _lod_group_infos = LODGroupInfos(
            name=group.group_name,
            exporter_source_data_path="",
            lod_count=len(presets)
        )
        _capture_export_settings(group, _lod_group_infos)
        root = get_first_without_parent(lod0_roots)
        if not root:
            root = lod0_roots[0]
        _capture_lod_viewer_offset(root, _lod_group_infos)

        presets.sort(reverse=False, key=lambda p: p.preset_name)
        valid_lods = True
        for i, p in enumerate(presets):
            lod_objects = p.get_preset_objects()
            if not lod_objects:
                valid_lods = False
                break

            # Make sure lod objects are visible for depsgraph eval later
            # If not done evaluated object is empty
            obj_utils.set_viewport_hidden(lod_objects, False)

            valid_roots = _get_roots(lod_objects)

            if valid_roots:
                resetted_lod_objects = []
                for root in valid_roots:
                    # Make that root parent is not part of lod object
                    resetted_lod_objects.extend(_create_lod_root_with_resetted_transforms(
                        name=group.group_name,
                        lod_index=i,
                        root_obj=root,
                        lod_objects=lod_objects,
                        reset_translation=root.msfs_export_transform.reset_translation,
                        reset_rotation=root.msfs_export_transform.reset_rotation,
                        reset_scale=root.msfs_export_transform.reset_scale,
                    ))
                lod_collection = lod_viewer_collections.create_lod_collection(
                    group.group_name, i, resetted_lod_objects
                )
            else:
                lod_collection = lod_viewer_collections.create_lod_collection(
                    group.group_name,
                    i,
                    lod_objects
                )

            # Add to temp_scene to be evaluated later
            temp_scene.collection.children.link(lod_collection)

            _lod_group_infos.set_lod_collection(i, lod_collection)
            _lod_group_infos.set_lod_objects(i, lod_objects)

        if valid_lods:
            lod_group_infos.append(_lod_group_infos)
    return lod_group_infos

def create_temp_scene()->bpy.types.Scene:
    return bpy.data.scenes.new(".temp_lod_eval")


def construct_scene_lod_group_infos(
    scene: bpy.types.Scene,
    export_mode: multi_export_mode.ExportMode,
    msfs_lod_groups: list | bpy.types.bpy_prop_collection
) -> tuple[list[LODGroupInfos], bpy.types.Scene | None]:
    """Create LODGroupInfos of scene.

    Creates a temporary scene used to safely evaluate LOD objects (bounding
    sphere, vertex count, etc.).
    This avoids dependency graph evaluation
    issues when objects cannot be evaluated in the original scene, such as
    when they belong to excluded collections, are hidden etc.
    """
    lod_groups_infos = []
    temp_scene = None

    if (
        export_mode == multi_export_mode.ExportMode.OBJECTS
        or export_mode == multi_export_mode.ExportMode.COLLECTIONS
    ):
        temp_scene = create_temp_scene()
        lod_groups_infos = get_objects_lod_group_infos(
            msfs_lod_groups, temp_scene, export_mode
        )
    elif export_mode == multi_export_mode.ExportMode.PRESETS:

        if not msfs_lod_groups:
            return (lod_groups_infos, temp_scene)
        
        msfs_preset_groups = {}
        for group in msfs_lod_groups:
            msfs_preset_groups[group.name] = group
    
        temp_scene = create_temp_scene()
        lod_groups_infos = get_presets_lod_group_infos(
            msfs_preset_groups, scene, temp_scene
        )

    return (lod_groups_infos, temp_scene)
