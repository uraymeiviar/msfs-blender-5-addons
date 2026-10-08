from __future__ import annotations

import re

import bpy

from io_scene_gltf2_msfs_fss.io.exp import multi_export_mode
from io_scene_gltf2_msfs_fss.io.exp import export_settings
from io_scene_gltf2_msfs_fss.io.com import msfs_path_utils
from io_scene_gltf2_msfs_fss.io.exp.multi_export_mode import ExportMode

# region Properties
class MultiExporterLOD(bpy.types.PropertyGroup):

    objectLOD: bpy.props.PointerProperty(
        name="Object",
        type=bpy.types.Object
    )  # type: ignore

    collection: bpy.props.PointerProperty(
        name="Collection",
        type=bpy.types.Collection
    )  # type: ignore

    enabled: bpy.props.BoolProperty(
        name="Enabled",
        default=False,
        description="Enable/Disable to export"
    )  # type: ignore

    lod_value: bpy.props.FloatProperty(
        name="LOD Value",
        default=0,
        min=0,
        max=999,
        precision=4,
    )  # type: ignore

    file_name: bpy.props.StringProperty(
        name="File name",
        default="",
        description="File name of the exported model",
    )  # type: ignore

    group_name: bpy.props.StringProperty(
        name="Group Name",
        default=""
    )  # type: ignore

    full_data_path: bpy.props.StringProperty(
        description="Use by Tree View for fast data access."
    )  # type: ignore

    def get_scene(self) -> bpy.types.Scene:
        scene = self.id_data
        if not isinstance(scene, bpy.types.Scene):
            raise AttributeError("LOD must be stored in a Scene Property!")
        return scene

    def to_dict(self):
        """
        Serialize LOD properties to dictionnary.
        """
        lod_props = {}
        lod_object = self.objectLOD
        try:
            if lod_object:
                lod_object.name
        except RuntimeError:
            # deleted object
            lod_object = None
        lod_props["objectLOD"] = lod_object
        collection = self.collection
        try:
            if collection:
                collection.name
        except RuntimeError:
            collection = None

        lod_props["collection"] = self.collection
        lod_props["file_name"] = self.file_name
        lod_props["name"] = self.name
        lod_props["group_name"] = self.group_name
        lod_props["enabled"] = self.enabled
        lod_props["lod_value"] = self.lod_value

        return lod_props

    def get_lod_objects(
        self,
        export_mode: ExportMode
    ) -> set[bpy.types.Object]:

        scene = self.get_scene()

        scene_objects = scene.objects
        objects = set()

        if export_mode == ExportMode.COLLECTIONS :
            # Collection can be None if deleted
            if not self.collection:
                return objects
            try:
                in_scene = self.collection in scene.collection.children_recursive
                if not in_scene:
                    return objects
            except:
                return objects
            
            objects = set(self.collection.all_objects)
        elif export_mode == ExportMode.OBJECTS:
            in_scene = False
            try:
                # Try accessing name to check if still in bpy.data
                # Check if it is in current scene
                in_scene = self.objectLOD.name in scene_objects  # type: ignore
                if not in_scene:
                    return objects
            except:
                # Deleted objects
                return objects

            objects = set((self.objectLOD,))
            children = self.objectLOD.children_recursive
            in_scene_children = set()
            for child in children:
                if child.name in scene_objects:
                    in_scene_children.add(child)
            if in_scene_children:
                objects.update(in_scene_children)

        return objects

class MultiExporterLODGroup(bpy.types.PropertyGroup):

    register_order = 1 #register after MultiExportLOD class

    def _set_folder_path(self, value: str):

        self["folder_path"] = msfs_path_utils.get_relative_path_to_scene(value)

    def _get_folder_path(self):
        return self.get("folder_path", "")

    def enabled_lod_count(self):
        count = 0
        for lod in self.lods:
            if lod.enabled:
                count += 1
        return count

    # We will need to keep this for retro-compatibility
    group_name: bpy.props.StringProperty(
        name="Group Name",
        default=""
    )  # type: ignore

    lods: bpy.props.CollectionProperty(type=MultiExporterLOD)  # type: ignore

    folder_path: bpy.props.StringProperty(
        name="Export Folder Path",
        default="",
        subtype="DIR_PATH",
        description="Path to the directory where you want your model to be exported",
        set=_set_folder_path,
        get=_get_folder_path,
        options=(
            {"PATH_SUPPORTS_BLEND_RELATIVE"} if bpy.app.version >= (4, 5, 0) else set()
        ),
    )  # type: ignore

    generate_xml: bpy.props.BoolProperty(
        name="Generate XML",
        description=(
            "Generate XML or update it if already exists.\n"
            "XML update is conservative:\n"
            "Only LOD entries are modified, other attributes like animation are untouched."
        ),
        default=True,
    )  # type: ignore

    overwrite_guid: bpy.props.BoolProperty(
        name="Overwrite GUID",
        default=False,
        description="If an XML file already exists in the location to export to, the GUID will be overwritten",
    )  # type: ignore

    autogenerate_lods: bpy.props.BoolProperty(
        name="Autogenerate LODs",
        default=False,
        description=(
            "If enabled, only the first enabled LOD will be exported.\n" 
            "When the Microsoft Flight Simulator 2024's BuildPackage process will be used,\n"
            "LODs will be generated automatically, using Simplygon."
        ),
    )  # type: ignore

    enabled: bpy.props.BoolProperty(
        name="Enabled",
        default=False,
        description="Enable/Disable all LODs to export"
    )  # type: ignore

    settings_preset: bpy.props.EnumProperty(
        name="Settings Preset",
        items=export_settings.get_setting_presets_items,
    ) # type: ignore

    full_data_path: bpy.props.StringProperty(
        description="Use by Tree View for fast data access."
    ) # type: ignore

    def get_scene(self) -> bpy.types.Scene:
        scene = self.id_data
        if not isinstance(scene, bpy.types.Scene):
            raise AttributeError("LOD Group must be stored in a Scene Property!")
        return scene
    
    def to_dict(self):
        """
        Serialize LODGroup properties to dictionnary.
        """
        lod_group_dict = {}
        lod_group_dict["name"] = self.name
        lod_group_dict["group_name"] = self.group_name
        lod_group_dict["folder_path"] = self.folder_path
        lod_group_dict["generate_xml"] = self.generate_xml
        lod_group_dict["autogenerate_lods"] = self.autogenerate_lods
        lod_group_dict["enabled"] = self.enabled
        lod_group_dict["settings_preset"] = self.settings_preset
        lod_group_dict["lods"] = []
        for lod in self.lods:
            lop_dict = lod.to_dict()
            lod_group_dict["lods"].append(lop_dict)

        return lod_group_dict

    def get_lod_group_objects(
        self,
        export_mode: ExportMode,
        enabled_only: bool = False
    ) -> set[bpy.types.Object]:
        objects = set()
        for lod in self.lods:
            if enabled_only and not lod.enabled:
                continue
            lod: MultiExporterLOD
            objects.update(lod.get_lod_objects(export_mode),)

        return objects
    
    def get_export_settings_preset(self) -> export_settings.MSFS2024_MultiExporterSettings | None:
        scene = self.get_scene()
        return export_settings.get_settings_preset_by_name(scene, self.settings_preset)

# endregion

# LOD groups generation
LOD_NAME_PATTERN = re.compile(r"^x[0-9]_|_lod[0-9]+$",re.IGNORECASE)

def _get_group_name_from_lod_name(name: str):
    matches = re.findall(LOD_NAME_PATTERN, name)
    # If a blender_object starts with xN_ or ends with _LODN, treat as an LOD
    if matches:
        # Get base blender_object group name from blender_object
        for match in matches:
            filtered_string = name.replace(match, "")
            return filtered_string

    # If prefix or suffix isn't found, use the blender_object name as the group
    return name

# region Groups getter
def _get_new_groups_from_objects(objects: list[bpy.types.Object])-> dict[str,bpy.types.Object]:
    found_lod_groups = {}

    for blender_object in objects:
        if blender_object.parent is not None:
            continue

        lod_group_name = _get_group_name_from_lod_name(blender_object.name)

        if lod_group_name not in found_lod_groups:
            found_lod_groups[lod_group_name] = []

        found_lod_groups[lod_group_name].append(blender_object)
    return found_lod_groups

def _get_new_groups_from_collections(collections: list[bpy.types.Collection])->dict[str, bpy.types.Collection]:
    found_lod_groups = {}

    for collection in collections:
        lod_group_name = _get_group_name_from_lod_name(collection.name)

        if lod_group_name not in found_lod_groups:
            found_lod_groups[lod_group_name] = []

        found_lod_groups[lod_group_name].append(collection)

    return found_lod_groups
# end region

def _store_lod_groups_to_dicts(scene: bpy.types.Scene):
    """
    Serialize lod groups into a dictionnary.
    """
    lod_groups = get_scene_lod_groups(scene)
    lod_groups_dicts = {}
    for lod_group in lod_groups:
        lod_group_dict = lod_group.to_dict()
        lod_groups_dicts[lod_group.name.lower()] = lod_group_dict
    return lod_groups_dicts

def _create_lod_from_old_lod_dict(old_lod: dict, lod_group: MultiExporterLODGroup, object_key):
    lod = lod_group.lods.add()
    for key, value in old_lod.items():
        setattr(lod, key, value)
    # Only set file name if user changed it
    if (
        old_lod["file_name"].strip()
        and old_lod["file_name"] != old_lod[object_key].name
    ):
        lod.file_name = old_lod["file_name"]
    else:
        lod.file_name = old_lod[object_key].name

    return lod

def reload_lod_groups(scene: bpy.types.Scene, reset: bool = False):
    """
    Recreate lod groups while preserving custom settings .
    """

    export_mode = multi_export_mode.ExportMode.from_identifier(scene.msfs_export_mode)
    if not export_mode:
        raise Exception("Invalid Export mode!")

    lod_groups = get_scene_lod_groups(scene)
    grouped_by_collections = False
    if export_mode == multi_export_mode.ExportMode.COLLECTIONS:
        if reset:
            lod_groups.clear()

        new_lod_groups = _get_new_groups_from_collections(scene.collection.children_recursive)
        grouped_by_collections = True

    elif export_mode == multi_export_mode.ExportMode.OBJECTS:
        if reset:
            lod_groups.clear()

        new_lod_groups = _get_new_groups_from_objects(scene.objects)
    else:
        print(f"Can't reload lod groups when Export Mode is set to {export_mode}")
        return

    # Store original lod_groups in dict before clear()
    old_lod_groups_dicts = _store_lod_groups_to_dicts(scene)
    lod_groups.clear()

    # Force alphabetical order
    ordered_new_lod_groups_keys = list(new_lod_groups.keys())
    ordered_new_lod_groups_keys.sort(reverse=False)

    for i, new_lod_group_name in enumerate(ordered_new_lod_groups_keys):
        new_lods = new_lod_groups[new_lod_group_name]
        # ignore casing when trying to find existing lod group
        old_lod_group = old_lod_groups_dicts.get(new_lod_group_name.lower(), None)

        lod_group: MultiExporterLODGroup = lod_groups.add()
        # Manually format Full data path, much faster than repr()
        lod_group.full_data_path = f"bpy.context.scene.msfs_multi_exporter_lod_groups[{i}]"
        if old_lod_group:
            # Recreate lod_group with original settings
            for key, value in old_lod_group.items():
                if key == "lods":
                    continue
                # lod_group[key] will not trigger property update function
                lod_group[key] = value

        lod_group.name = new_lod_group_name

        sorted_new_lods = sorted(new_lods, key=lambda x: x.name, reverse=False)
        # Lodgroup lods creation:
        for i, new_lod in enumerate(sorted_new_lods):
            # Here new_lod can be an object or a collection
            old_lod = None
            object_key = "objectLOD"
            if grouped_by_collections:
                object_key = "collection"

            if old_lod_group:
                for lod in old_lod_group["lods"]:
                    if new_lod == lod[object_key]:
                        old_lod = lod

            if old_lod:
                # Recreate lod with old_lod settings
                lod = _create_lod_from_old_lod_dict(
                    old_lod, 
                    lod_group, 
                    object_key
                )
            else:
                # New lod with default settings
                lod = lod_group.lods.add()
                lod["file_name"] = new_lod.name

            # Renaming
            if grouped_by_collections:
                lod["collection"] = new_lod
                if new_lod:
                    lod["name"] = new_lod.name
            else:
                lod["objectLOD"] = new_lod
                if new_lod:
                    lod["name"] = new_lod.name
            lod["group_name"] = lod_group.name

            # Faster than repr()
            lod.full_data_path = lod_group.full_data_path + f".lods[{i}]"


def get_scene_lod_groups(
    scene: bpy.types.Scene,
) -> bpy.types.bpy_prop_collection_idprop[MultiExporterLODGroup]:
    return scene.msfs_multi_exporter_lod_groups

bpy.types.CollectionProperty
def register():
    bpy.types.Scene.msfs_multi_exporter_lod_groups = bpy.props.CollectionProperty(type=MultiExporterLODGroup) # type: ignore


def unregister():
    
    try:
        del bpy.types.Scene.msfs_multi_exporter_lod_groups # type: ignore
    except:
        pass
