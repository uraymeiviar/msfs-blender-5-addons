from __future__ import annotations

import uuid

import bpy

from io_scene_gltf2_msfs_fss.io.exp import export_settings
from  io_scene_gltf2_msfs_fss.io.com import msfs_path_utils

class MultiExporterPresetGroup(bpy.types.PropertyGroup):

    def _update_group_path(self, context: bpy.types.Context):
        scene = self.get_scene()
        scene_presets = get_scene_exporter_presets(scene)
        for preset in scene_presets:
            if preset.group_id == self.name:
                # preset["folder_path"] does not trigger prop update function
                preset["folder_path"] = self.folder_path

    def _set_folder_path(self, value:str):
        self["folder_path"] = msfs_path_utils.get_relative_path_to_scene(value)
        scene = self.get_scene()
        scene_presets = get_scene_exporter_presets(scene)
        for preset in scene_presets:
            if preset.group_id == self.name:
                # preset["folder_path"] does not trigger prop update function
                preset["folder_path"] = self.folder_path

    def _get_group_folder_path(self):
        return self.get("folder_path", "")

    def _update_group_presets_settings(self, context: bpy.types.Context):
        scene = self.get_scene()
        scene_presets = get_scene_exporter_presets(scene)
        settings_presets = export_settings.get_scene_settings_presets(scene)
        for preset in scene_presets:
            if preset.group_id == self.name:
                # preset["settings_preset"] does not trigger prop update function
                preset["settings_preset"] = settings_presets.find(self.settings_preset)

    ## name : guid of the Preset Group
    group_name: bpy.props.StringProperty(
        name="",
        default="",
        description="Name of the presets's group"
    )  # type: ignore

    folder_path: bpy.props.StringProperty(
        name="",
        default="",
        subtype="DIR_PATH",
        description="Path to the directory where you want the presets to be exported",
        update=_update_group_path,
        set=_set_folder_path,
        get=_get_group_folder_path,
        options={"PATH_SUPPORTS_BLEND_RELATIVE"} if bpy.app.version >= (4,5,0) else set()
    )  # type: ignore

    enabled: bpy.props.BoolProperty(
        name="",
        default=False,
        description="Enable/Disable the group for the export",
    )  # type: ignore

    settings_preset: bpy.props.EnumProperty(
        name="Settings Preset", 
        items=export_settings.get_setting_presets_items, 
        update=_update_group_presets_settings
    )  # type: ignore

    full_data_path: bpy.props.StringProperty(
        description="Use by Tree View for fast data access."
    )  # type: ignore

    def get_scene(self) -> bpy.types.Scene:
        scene = self.id_data
        if not isinstance(scene, bpy.types.Scene):
            raise AttributeError("Preset Group must be stored in a Scene Property!")
        return scene

    def get_child_presets(self):
        scene = self.get_scene()
        scene_presets = get_scene_exporter_presets(scene)
        child_presets = []
        for preset in scene_presets:
            if preset.group_id == self.name:
                child_presets.append(preset)
        return child_presets

    def update_full_data_path(self):
        scene = self.get_scene()
        scene_preset_groups = get_scene_exporter_preset_groups(scene)
        index = scene_preset_groups.find(self.name)
        # Faster than repr() in order to get full data_path
        self.full_data_path = f"bpy.context.scene.msfs_multi_exporter_preset_groups[{index}]"

    def get_export_settings_preset(self) -> export_settings.MSFS2024_MultiExporterSettings | None:
        scene = self.get_scene()
        return export_settings.get_settings_preset_by_name(scene, self.settings_preset)

    @staticmethod
    def update_groups_full_data_path(scene: bpy.types.Scene ):
        """More efficient than calling update_full_data_path multiple times 
        when updating all scene group presets.
        """
        scene_preset_groups = get_scene_exporter_preset_groups(
            scene
        )
        for i, group in enumerate(scene_preset_groups):
            group.full_data_path = f"bpy.context.scene.msfs_multi_exporter_preset_groups[{i}]"

class MultiExporterPresetLayer(bpy.types.PropertyGroup):
    collection: bpy.props.PointerProperty(
        name="Collection",
        type=bpy.types.Collection
    )  # type: ignore

    is_scene_collection: bpy.props.BoolProperty(
        name="is scene collection",
        description="True when layer represents a scene root collection",
        default=False,

    )  # type: ignore

    enabled: bpy.props.BoolProperty(
        name="Enabled",
        default=False,
        description="Enable/Disable the collection for the preset",
    )  # type: ignore

    full_data_path: bpy.props.StringProperty(
        description="Use by Tree View for fast data access."
    )  # type: ignore

    preset_id: bpy.props.StringProperty(default="")  # type: ignore

    def get_layer_objects(
        self,
    ) -> set[bpy.types.Object]:

        objects = set()
        if not self.collection:
            # Happen in background process
            # Scene collection reference is broken on scene reopening
            return objects
        
        try:
            objects = set(self.collection.objects)
        except RuntimeError:
            # deleted collection
            return objects
        
        return objects

class MultiExporterPreset(bpy.types.PropertyGroup):

    def _set_relative_path(self, value: str):
        self["folder_path"] = msfs_path_utils.get_relative_path_to_scene(value)

    def _get_relative_path(self):
        return self.get("folder_path", "")

    ## name : guid of Preset
    preset_name: bpy.props.StringProperty(
        name="",
        default="",
        description="Name of the glTF to export",
    )  # type: ignore

    folder_path: bpy.props.StringProperty(
        name="",
        default="",
        subtype="DIR_PATH",
        description="Path to the directory where you want your model to be exported",
        set=_set_relative_path,
        get=_get_relative_path,
        options={"PATH_SUPPORTS_BLEND_RELATIVE"} if bpy.app.version >= (4,5,0) else set()
    )  # type: ignore

    enabled: bpy.props.BoolProperty(
        name="",
        default=False,
        description="Enable/Disable the preset for the export",
    )  # type: ignore

    layers: bpy.props.CollectionProperty(type=MultiExporterPresetLayer)  # type: ignore
    group_id: bpy.props.StringProperty(default="")  # type: ignore

    settings_preset: bpy.props.EnumProperty(
        name="Settings Preset",
        items=export_settings.get_setting_presets_items,
    )  # type: ignore

    full_data_path: bpy.props.StringProperty(
        description="Use by Tree View for fast data access."
    )  # type: ignore

    def get_scene(self) -> bpy.types.Scene:
        scene = self.id_data
        if not isinstance(scene, bpy.types.Scene):
            raise AttributeError("Preset must be stored in a Scene Property!")
        return scene
    
    def load_preset_layers(self):
        scene = self.get_scene()
        _scene_collections: list = scene.collection.children_recursive
        _scene_collections.append(scene.collection)

        # Retrieve scene collections from bpy.data.collections instead of
        # scene.collection.children_recursive
        # This avoids the error:
        #      "RuntimeError: Error: RNA_property_pointer_set: cannot assign an embedded ID to an IDProperty"
        # which occurs when assigning layer.collection (PointerProperty).

        scene_collections = [
            col for col in bpy.data.collections if col in _scene_collections
        ]

        # Store enabled layers
        enabled_layers = set()
        for layer in self.layers:
            if layer.enabled:
                enabled_layers.add(layer.name)

        # Recreate all layers
        self.layers.clear()
        for collection in scene_collections:

            layer = self.layers.add()
            layer.name = collection.name
            layer.collection = collection
            layer.preset_id = self.name
            layer.enabled = layer.name in enabled_layers

        self.update_full_data_path(update_layers=True)

    def get_preset_objects(self)->set[bpy.types.Object]:
        objects = set()
        for layer in self.layers:
            layer: MultiExporterPresetLayer
            if not layer.enabled:
                continue
            layer_objects = layer.get_layer_objects()
            if not layer_objects:
                continue
            objects.update(layer_objects)
        return objects

    def get_preset_collections(self)->list[bpy.types.Collection]:
        collections = []
        for layer in self.layers:
            if not layer.enabled:
                continue

            if layer.collection is None:
                continue
            try:
                layer.collection.objects
            except RuntimeError:
                # deleted collection
                continue
            collections.append(layer.collection)
        return collections

    def get_scene_root_layer(self) -> MultiExporterPresetLayer:
        """Get preset root layer. Create it if it not present."""
        scene_layer = None
        index = 0
        for i, layer in enumerate(self.layers):
            if not layer.is_scene_collection:
                continue
            scene_layer = layer
            index = i
            break

        # Create root scene_layer if it doesnt exist
        if not scene_layer:
            scene_layer: MultiExporterPresetLayer = self.layers.add()
            index = len(self.layers) - 1

        scene_layer.preset_id = self.name
        scene_layer.name = "Scene Collection"
        scene_layer.is_scene_collection = True

        scene_layer.full_data_path = self.full_data_path + f".layers[{index}]"

        if not self.full_data_path:
            self.update_full_data_path()
        return scene_layer

    def update_full_data_path(
        self,
        update_layers: bool = False
    ):
        scene = self.get_scene()
        scene_presets = get_scene_exporter_presets(scene)
        preset_index = scene_presets.find(self.name)
        # Faster than repr() in order to get full data_path
        self.full_data_path = f"bpy.context.scene.msfs_multi_exporter_presets[{preset_index}]"
        if update_layers:

            for i, layer in enumerate(self.layers):

                layer.full_data_path =f"{self.full_data_path}.layers[{i}]"

    @staticmethod
    def update_presets_full_data_path(
        scene: bpy.types.Scene, 
        update_layers: bool = False
    ):
        """More efficient than calling update_full_data_path multiple times 
        when updating all scene presets.
        """

        scene_presets = get_scene_exporter_presets(scene)
        for i, preset in enumerate(scene_presets):
            preset.full_data_path = f"bpy.context.scene.msfs_multi_exporter_presets[{i}]"
            if update_layers:
                return
            for i, layer in enumerate(preset.layers):
                layer.full_data_path =f"{preset.full_data_path}.layers[{i}]"

# endregion

# region Utilities
def add_preset_group(scene: bpy.types.Scene) -> MultiExporterPresetGroup:
    scene_groups = get_scene_exporter_preset_groups(scene)
    group: MultiExporterPresetGroup = scene_groups.add()
    group.name = str(uuid.uuid4())
    group.group_name = f"Group.{len(scene_groups)}"
    group.folder_path = ""
    group.update_full_data_path()
    return group

def remove_preset_group(
    group_id: str,
    scene: bpy.types.Scene,
    refresh_data_path: bool = False,
):
    scene_groups = get_scene_exporter_preset_groups(scene)
    scene_presets = get_scene_exporter_presets(scene)
    for preset_id in scene_presets.keys():
        idx = scene_presets.find(preset_id)
        if scene_presets[idx].group_id == group_id:
            scene_presets.remove(idx)

    idx = scene_groups.find(group_id)
    scene_groups.remove(idx)

    if refresh_data_path:
        # Refresh full data path after a preset deletion
        MultiExporterPresetGroup.update_groups_full_data_path(scene)
        MultiExporterPreset.update_presets_full_data_path(scene)

def _get_duplicate_name(name: str, nbr_elem: int):
    split_name = name.split('.')
    last_split_elem = len(split_name) - 1
    suffix = split_name[last_split_elem]

    if suffix.isdigit():
        new_suffix = '.' + str(nbr_elem)
        split_name[last_split_elem] = new_suffix
    else:
        split_name.append('.0')

    return ''.join(split_name)


def duplicate_preset_group(group: MultiExporterPresetGroup) -> MultiExporterPresetGroup:

    # Store group name to get new ref after creating new group.
    # On rare occasion, adding a group can invalidate existing group ref.
    group_name = group.name
    scene = group.get_scene()
    duplicated_group: MultiExporterPresetGroup = add_preset_group(scene)
    scene_groups = get_scene_exporter_preset_groups(scene)

    # Safely get group ref
    group = scene_groups.get(group_name)
    active_group_name = group.group_name
    group_prefixes = [group.group_name.split(".")[0] for group in scene_groups]
    duplicated_group.group_name = _get_duplicate_name(
        active_group_name, len(group_prefixes)
    )

    duplicated_group.folder_path = group.folder_path
    duplicated_group.settings_preset = group.settings_preset
    scene_presets = get_scene_exporter_presets(scene)
    for preset in scene_presets:
        if preset.group_id == group.name:
            duplicated_preset = duplicate_preset(preset, scene)
            duplicated_preset.group_id = duplicated_group.name
    return duplicated_group


def add_preset(scene: bpy.types.Scene, group_id: str = "") -> MultiExporterPreset:
    scene_presets = get_scene_exporter_presets(scene)

    preset: MultiExporterPreset = scene_presets.add()
    preset.name = str(uuid.uuid4())
    preset.preset_name = f"Preset.{len(scene_presets)}"

    if group_id != "":
        scene_groups = get_scene_exporter_preset_groups(scene)
        group: MultiExporterPresetGroup = scene_groups.get(group_id, None)
        if group:
            preset.folder_path = group.folder_path
            preset.group_id = group_id

    preset.update_full_data_path()
    preset.load_preset_layers()
    return preset

def remove_preset(preset_id: str, scene: bpy.types.Scene,refresh_data_path: bool = False):
    scene_presets = get_scene_exporter_presets(scene)
    idx = scene_presets.find(preset_id)
    scene_presets.remove(idx)
    if refresh_data_path:
        # Refresh full data path after a preset deletion
        MultiExporterPreset.update_presets_full_data_path(scene)


def duplicate_preset(
    preset: MultiExporterPreset, scene: bpy.types.Scene
) -> MultiExporterPreset:
    # Store preset name to get new ref after creating new preset.
    # On rare occasion, adding a preset can invalidate existing preset ref.
    preset_name = preset.name
    duplicated_preset: MultiExporterPreset = add_preset(scene)

    scene_presets = get_scene_exporter_presets(scene)

    # Safely get preset ref
    preset = scene_presets.get(preset_name)

    active_preset_name = preset.preset_name
    preset_prefixes = [preset.preset_name.split(".")[0] for preset in scene_presets]
    duplicated_preset.preset_name = _get_duplicate_name(
        active_preset_name, len(preset_prefixes)
    )

    duplicated_preset.folder_path = preset.folder_path
    duplicated_preset.group_id = preset.group_id
    duplicated_preset.settings_preset = preset.settings_preset

    # We need to load layer and to enable the same from the preset
    # layers are readonly we can't just copy the list
    duplicated_preset.load_preset_layers()
    for layer in duplicated_preset.layers:
        if layer.name not in preset.layers:
            continue
        layer.enabled = preset.layers[layer.name].enabled

    return duplicated_preset


def isolate_preset_objects(
    preset: MultiExporterPreset | MultiExporterPresetGroup,
    view_layer: bpy.types.ViewLayer,
):
    """Only show preset or preset group objects in viewport."""
    preset_objects = set()
    if isinstance(preset, MultiExporterPreset):
        preset_objects = preset.get_preset_objects()
    elif isinstance(preset, MultiExporterPresetGroup):
        for p in preset.get_child_presets():
            preset_objects.update(p.get_preset_objects())
    if not preset_objects:
        return

    scene = preset.get_scene()
    scene_objects: set[bpy.types.Object] = set()
    # Get obj from bpy.data.objects to prevent crash during
    # looping of scene.collection.all_objects
    # Setting obj.hide_viewport invalide scene.collection.all_objects pointers
    for obj in scene.collection.all_objects:
        _ = bpy.data.objects.get(obj.name, None)
        if not _:
            continue
        scene_objects.add(_)

    # TODO move this function in a common collections utilities module
    # also used in export
    def _construct_object_layer_collections_dict(
        layer_collection: None | bpy.types.LayerCollection = None,
        object_layer_collections: (
            None | dict[bpy.types.Object, list[bpy.types.LayerCollection]]
        ) = None,
        parents: None | list[bpy.types.LayerCollection] = None,
    ) -> dict[bpy.types.Object, list[bpy.types.LayerCollection]]:
        """
        Create a dict mapping each object to the list of LayerCollections it belongs to.

        The list represents the LayerCollection parent chain for the object and is
        ordered by proximity: the last element is the direct LayerCollection containing
        the object, while preceding elements are its parent LayerCollections.
        """
        if layer_collection is None:
            # Get layer_collection from bpy.data to prevent invalid memory adress
            _scene = bpy.data.scenes[bpy.context.scene.name]
            _view_layer = _scene.view_layers[bpy.context.view_layer.name]
            layer_collection = _view_layer.layer_collection
        if object_layer_collections is None:
            object_layer_collections = {}
        if parents is None:
            parents = []

        parents.append(layer_collection)
        for obj in layer_collection.collection.objects:
            if not object_layer_collections.get(obj):
                object_layer_collections[obj] = parents
            else:
                object_layer_collections[obj] += parents

        for layer in layer_collection.children:
            _construct_object_layer_collections_dict(
                layer, object_layer_collections, parents.copy()
            )

        return object_layer_collections

    obj_layer_collections = _construct_object_layer_collections_dict(
        view_layer.layer_collection
    )
    _treated_layer_collections = set()
    for obj in scene_objects:
        if obj in preset_objects:
            layer_collections = obj_layer_collections.get(obj, [])
            # Make sur obj parent layer collections are visible
            for layer_col in layer_collections:
                if layer_col in _treated_layer_collections:
                    # Prevent unhidding layer collection multiple times
                    # This can be very very slow on big scenes
                    continue
                layer_col.exclude = False
                layer_col.hide_viewport = False
                layer_col.collection.hide_viewport = False
                layer_col.collection.hide_select = False
                layer_col.collection.hide_render = False
                _treated_layer_collections.add(layer_col)
            try:
                obj.hide_set(False, view_layer=view_layer)
                obj.hide_select = False
                obj.hide_viewport = False
                obj.hide_render = False
                obj.select_set(True, view_layer=view_layer)
            except RuntimeError:
                pass
        else:
            try:
                obj.select_set(False, view_layer=view_layer)
                obj.hide_set(True, view_layer=view_layer)
            except RuntimeError:
                pass

    view_layer.objects.active = list(preset_objects)[0]
# endregion


def get_scene_exporter_presets(
    scene: bpy.types.Scene,
) -> bpy.types.bpy_prop_collection_idprop[MultiExporterPreset]:
    return scene.msfs_multi_exporter_presets


def get_scene_exporter_preset_groups(
    scene: bpy.types.Scene,
) -> bpy.types.bpy_prop_collection_idprop[MultiExporterPresetGroup]:
    return scene.msfs_multi_exporter_preset_groups


def register():
    bpy.types.Scene.msfs_multi_exporter_presets = bpy.props.CollectionProperty(type=MultiExporterPreset) # type: ignore
    bpy.types.Scene.msfs_multi_exporter_preset_groups = bpy.props.CollectionProperty(type=MultiExporterPresetGroup) # type: ignore

def unregister():
    try:
        del bpy.types.Scene.msfs_multi_exporter_presets  # type: ignore
        del bpy.types.Scene.msfs_multi_exporter_preset_groups  # type: ignore
    except:
        pass
