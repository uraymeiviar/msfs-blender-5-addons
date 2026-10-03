"""
Pre-export validation functions for exports.
Validates LOD groups, Presets, Settings presets etc
before launching the export process.
"""

from __future__ import annotations
from typing import TYPE_CHECKING, Iterable
from dataclasses import dataclass, field
from pathlib import Path
import os

import bpy

from ..com import msfs_logs
from . import export_settings
from . import multi_export_mode
from . import presets as exp_presets
from . import lod_groups as exp_lod_groups
if TYPE_CHECKING:

    from .lod_groups import MultiExporterLODGroup, MultiExporterLOD
    from .presets import MultiExporterPresetLayer, MultiExporterPreset

MSFS2024_LOGGER : msfs_logs.Logger

# region Common
def _get_list_formatted_string(list: Iterable[str]) -> str:
    """Construct a paragraph from provided list of string.
    Usefull for logging message.
    """
    formatted_str = ""
    for name in list:
        formatted_str += f"-'{name}'\n"
    return formatted_str

@dataclass
class CheckExportFolderResult:
    folder_not_set: bool = False
    invalid_export_folder: bool = False
    absolute_path: str = ""

def _check_export_folder(export_folder: str) -> CheckExportFolderResult:
    """Check if export folder is set and exists.
    """
    export_folder = export_folder.strip()

    # Check if path is set
    if not export_folder:
        return CheckExportFolderResult(folder_not_set=True)

    # Check if it exists
    export_folder = bpy.path.abspath(export_folder)
    export_folder = os.path.realpath(export_folder)
    if not os.path.exists(export_folder):
        return CheckExportFolderResult(
            invalid_export_folder=True, absolute_path=export_folder
        )

    return CheckExportFolderResult(absolute_path=export_folder)


def _process_check_export_folder_result(
    folder_check_result: CheckExportFolderResult, 
    item_name: str
) -> tuple[bool, bool]:
    """Process folder check result and log 
    appropriate messages when necessary.
    
    Returns:
        tuple[bool, bool]: (result, skip_next_checks)
    """
    result = True
    skip_next_checks = False
    if folder_check_result.folder_not_set:
        result = False
        MSFS2024_LOGGER.error(
            message=f"'{item_name}' : No export folder configured.",
            details=(
                f"No export folder assigned to '{item_name}'.\n"
                "Please assign one in the exporter list."
            ),
        )
        skip_next_checks = True
        return result, skip_next_checks

    if folder_check_result.invalid_export_folder:
        result = False
        MSFS2024_LOGGER.error(
            message=f"'{item_name}' : Export folder doesn't exist.",
            details=f"Folder doesn't exists on disk:\n{folder_check_result.absolute_path}",
        )

        skip_next_checks = True
        return result, skip_next_checks

    return result, skip_next_checks


@dataclass
class CheckExportSettingsResult:
    no_export_settings: bool = False
    invalid_texture_dir: bool = False
    export_settings: export_settings.MSFS2024_MultiExporterSettings | None = None

def _has_valid_tex_dir(
    export_settings: export_settings.MSFS2024_MultiExporterSettings,
    absolute_export_path: str,
) -> bool:
    """
    Check if texture directory path is on same disk as gltf export path.
    """
    if export_settings.export_keep_originals or not export_settings.export_texture_dir:
        return True
    # here we reproduce exaclty how gltf addon construct texture dir path
    texture_dir = os.path.join(absolute_export_path, export_settings.export_texture_dir)

    # check if texture dir is relative to gltf
    texture_dir = Path(texture_dir)
    resolved_texture_dir = Path(texture_dir).resolve()
    return (
        resolved_texture_dir.anchor.lower() == Path(absolute_export_path).anchor.lower()
    )

def _check_export_settings(
    msfs_export_settings: None | export_settings.MSFS2024_MultiExporterSettings, 
    absolute_export_path: str
) -> CheckExportSettingsResult:
    """Check if the provided export settings exist,
    and if texture directory is valid.
    """

    no_export_settings = False
    invalid_texture_dir = False

    if not msfs_export_settings:
        no_export_settings = True
        return CheckExportSettingsResult(no_export_settings, invalid_texture_dir)

    valid_texture_dir = _has_valid_tex_dir(
        msfs_export_settings, absolute_export_path
    )
    return CheckExportSettingsResult(
        no_export_settings, 
        not valid_texture_dir, 
        msfs_export_settings
    )

def _process_check_export_settings_result(
    check_export_settings_result: CheckExportSettingsResult,
    item_name: str,
    absolute_export_path: str,
) -> tuple[bool, bool]:
    """Process export settings check results and log 
    appropriate messages when necessary.
    
    Returns:
        tuple[bool, bool]: (result, skip_next_checks)
    """
    result = True
    skip_next_checks = False

    if check_export_settings_result.no_export_settings:
        result = False
        MSFS2024_LOGGER.error(
            message=f"'{item_name}' : Has no export settings.",
            details=f"'{item_name}' has no defined export settings!",
        )

        skip_next_checks = True
        return result, skip_next_checks

    if check_export_settings_result.invalid_texture_dir:
        msfs_export_settings = check_export_settings_result.export_settings
        if not msfs_export_settings:
            raise ValueError("Export settings not assigned in provided check result!")
        result = False
        MSFS2024_LOGGER.error(
            message=f"'{item_name}' : Invalid texture directory.",
            details=(
                f"Export settings '{msfs_export_settings.name}':\n"
                f"Texture directory '{msfs_export_settings.export_texture_dir}' can't be relative to exported gltf path:\n"
                f"'{absolute_export_path}'\n"
                "Texture directory must be on the same disk as the gltf file."
            ),
        )

    return result, skip_next_checks


# region Object Checks
@dataclass
class CheckObjectsResult:
    skinned_objects_without_armature: set[str] = field(default_factory=set)
    skinned_objects_unincluded_armature: set[str] = field(default_factory=set)
    skinned_objects_root_transform_reset: set[str] = field(default_factory=set)
    skinned_objects_obj_transform_reset: set[str] = field(default_factory=set)

def _in_scene(obj: bpy.types.Object) -> bool:
    """Check if object has not been deleted and is present in current scene."""
    try:
        # try accessing name to check if still in bpy.data
        in_scene = obj.name in bpy.context.scene.objects  # type: ignore
        return in_scene
    except:
        # Deleted object
        return False


def _get_last_armature_modifier(
    obj: bpy.types.Object,
) -> None | bpy.types.ArmatureModifier:
    arm_mod = None
    for mod in reversed(obj.modifiers):
        if isinstance(mod, bpy.types.ArmatureModifier):
            arm_mod = mod
            break
    return arm_mod


def _check_objects(
    objects: Iterable[bpy.types.Object], msfs_export_settings: None | export_settings.MSFS2024_MultiExporterSettings
) -> CheckObjectsResult:
    """Perform standard validation checks on the given objects.

    - Validate skinned objects and their Armature modifiers.
    - Validate parent relationships when submodel export is enabled.

    Returns a CheckObjectsResult describing any detected issues.
    """
    skinned_objects_without_armature: set[str] = set()
    skinned_objects_unincluded_armature: set[str] = set()
    skinned_objects_root_transform_reset: set[str] = set()
    skinned_objects_obj_transform_reset: set[str] = set()

    # Check what's needed depending on what's enabled in export settings
    check_skin = False 
    check_root_transform_reset = False
    check_per_object_transform_reset = False

    if msfs_export_settings:
        check_skin = msfs_export_settings.export_skins
        check_root_transform_reset = msfs_export_settings.reset_origins == "ALL_ROOTS"

        check_root_transform_reset = check_root_transform_reset and (
            msfs_export_settings.export_transform_properties.reset_translation
            or msfs_export_settings.export_transform_properties.reset_rotation
            or msfs_export_settings.export_transform_properties.reset_scale
        )
        check_per_object_transform_reset = (
            msfs_export_settings.reset_origins == "PER_OBJECT"
        )

    armatures: set[bpy.types.Object] = set()
    for obj in objects:
        if obj.type == "ARMATURE":
            armatures.add(obj)

    submodel_root_count = 0

    for obj in objects:
        if not _in_scene(obj):
            continue

        if check_skin:
            if obj.type == "ARMATURE":
                continue
            # Find the last armature modifiers, since this the one used by gltf exporter
            arm_mod = _get_last_armature_modifier(obj)
            if not arm_mod:
                continue
            arm_ref = arm_mod.object
            skin_export = False
            if not arm_ref or not _in_scene(arm_ref):
                skinned_objects_without_armature.add(obj.name)
            elif arm_ref not in armatures:
                skinned_objects_unincluded_armature.add(obj.name)
            else:
                # A skin is going to be exported
                skin_export = True

            if check_root_transform_reset and not obj.parent and skin_export:
                skinned_objects_root_transform_reset.add(obj.name)
            elif (
                check_per_object_transform_reset
                and skin_export
                and (
                    obj.msfs_export_transform.reset_translation
                    or obj.msfs_export_transform.reset_rotation
                    or obj.msfs_export_transform.reset_scale
                )
            ):
                skinned_objects_obj_transform_reset.add(obj.name)
            # check if


    return CheckObjectsResult(
        skinned_objects_without_armature,
        skinned_objects_unincluded_armature,
        skinned_objects_root_transform_reset,
        skinned_objects_obj_transform_reset
    )


def _process_check_objects_result(
    check_objects_result: CheckObjectsResult,
    item_name: str,
) -> tuple[bool, bool]:
    """Process objects check result and log
    appropriate messages when necessary.

    Returns:
        tuple[bool, bool]: (result, skip_next_checks)
    """
    result = True
    skip_next_checks = False

    if check_objects_result.skinned_objects_without_armature:

        invalid_skinned_objects = _get_list_formatted_string(
            check_objects_result.skinned_objects_without_armature
        )

        MSFS2024_LOGGER.warning(
            message=f"'{item_name}' : Skinned objects have no assigned armature.",
            details=(
                "Skinning data will not be exported for the following objects.\n"
                "The Armature modifier has no armature object assigned.\n"
                "Affected objects:\n"
                f"{invalid_skinned_objects}"
            ),
        )
    if check_objects_result.skinned_objects_unincluded_armature:

        invalid_skinned_objects = _get_list_formatted_string(
            check_objects_result.skinned_objects_unincluded_armature
        )

        MSFS2024_LOGGER.warning(
            message=f"'{item_name}' : Skinned objects without armature.",
            details=(
                "Skinning data will not be exported for the following objects\n"
                "because their associated armature is not included in the gltf export.\n"
                "To resolve this, include the armature in the exported gltf.\n"
                "Affected objects:\n"
                f"{invalid_skinned_objects}"
            ),
        )

    if check_objects_result.skinned_objects_root_transform_reset:

        invalid_skinned_objects = _get_list_formatted_string(
            check_objects_result.skinned_objects_root_transform_reset
        )
        MSFS2024_LOGGER.warning(
            message=f"'{item_name}' : Can't reset origin of skinned object",
            details=(
                f"The origin of '{item_name}' cannot be reset because it is a skinned object.\n"
                "Parent it to a valid node object whose origin can be reset, or disable\n"
                "'Reset Origins (All Roots)' in the export settings.\n"
                "Invalid objects:\n"
                f"{invalid_skinned_objects}"
            ),
        )


    elif check_objects_result.skinned_objects_obj_transform_reset:

        invalid_skinned_objects = _get_list_formatted_string(
            check_objects_result.skinned_objects_obj_transform_reset
        )
        MSFS2024_LOGGER.warning(
            message=f"'{item_name}' : Can't reset origin of skinned object.",
            details=(
                f"The origin of '{item_name}' cannot be reset because it is a skinned object.\n"
                "Parent it to a valid node object whose origin can be reset, or disable\n"
                "'Reset Origins (Per Object)' in the export settings.\n"
                "Invalid objects:\n"
                f"{invalid_skinned_objects}"
            ),
        )
    return result, skip_next_checks


# endregion

# endregion

# region Preference checks

@dataclass
class CheckPreferencesResult:
    negative_frames_enabled: bool = False


def _use_negative_frames()->bool:
    """
    Warn if negative frames are enabled in Blender versions prior to 3.6.0,
    as they are not supported by the MSFS engine.
    """
    preferences = bpy.context.preferences
    if not preferences:
        return False
    
    if bpy.app.version < (3, 6, 0) and preferences.edit.use_negative_frames:
        return True
        
    return False

def _check_preferences()->CheckPreferencesResult:
    """Check preferences settings:
        -Negative frames enabled on old blender version.

    """
    if _use_negative_frames():
        return(CheckPreferencesResult(True))
    return(CheckPreferencesResult(False))

def _process_check_preferences_result(
    check_preferences_result: CheckPreferencesResult,
   
) -> tuple[bool, bool]:
    """Process preferences check result and log 
    appropriate messages when necessary.
    
    Returns:
        tuple[bool, bool]: (result, skip_next_checks)
    """

    result = True
    skip_next_checks = False

    if check_preferences_result.negative_frames_enabled:

        MSFS2024_LOGGER.warning(
        message="Negative frames are not supported.",
        details=(
            "'Allow Negative Frames' is enabled in Blender preferences.\n"
            "Negative frames are not supported by the MSFS2024 Engine.\n"
            "It is recommended to remove negative frames from animations.\n"
            "Disable 'Allow Negative Frames' to hide this warning."
        ),
        )

    return result, skip_next_checks

def check_preferences()->bool:
    result = True
    check_prefs_result = _check_preferences()
    _result, skip_next_checks = _process_check_preferences_result(
        check_prefs_result
    )
    if not _result:
        result = False

    return result

# endregion

# region LOD Groups
def _get_enabled_lod_groups() -> list[MultiExporterLODGroup]:
    lod_group: MultiExporterLODGroup
    enabled_lod_groups: list[MultiExporterLODGroup] = []
    scene_lod_groups = exp_lod_groups.get_scene_lod_groups(bpy.context.scene)
    for lod_group in scene_lod_groups:  # type: ignore
        if lod_group.enabled:
            enabled_lod_groups.append(lod_group)
            continue
        else:
            for lod in lod_group.lods:
                if lod.enabled:
                    enabled_lod_groups.append(lod_group)
                    break
    return enabled_lod_groups


@dataclass
class CheckLODsResult:
    empty_enabled_lods: set[str] = field(default_factory=set)
    all_enabled_lods_empty: bool = False
    deleted_enabled_lods: set[str] = field(default_factory=set)


def _check_lods_collections(lod_group: MultiExporterLODGroup) -> CheckLODsResult:
    """Check lod groups in collections mode.
    """
    empty_enabled_lods: set[str] = set()
    all_enabled_lods_empty: bool = True
    deleted_enabled_lods: set[str] = set()

    scene_collections: list[bpy.types.Collection] = (
        bpy.context.scene.collection.children_recursive # type: ignore
    )

    for lod in lod_group.lods:
        if not lod.enabled:
            continue
        in_scene = True
        lod: MultiExporterLOD
        # Check if collection has not been deleted and is in scene
        try:
            collection: bpy.types.Collection = lod.collection
            collection.name  # try accessing name to check if still in bpy.data
            in_scene = collection in scene_collections
        except:
            # Deleted collection
            in_scene = False

        if not in_scene:
            deleted_enabled_lods.add(lod.name)
            continue
    
        # Check if collection is empty
        is_empty = False
        if not collection.all_objects:
            is_empty = True
            empty_enabled_lods.add(collection.name)

        if in_scene and not is_empty:
            all_enabled_lods_empty = False

    return CheckLODsResult(
        empty_enabled_lods=empty_enabled_lods,
        all_enabled_lods_empty=all_enabled_lods_empty,
        deleted_enabled_lods=deleted_enabled_lods,
    )


def _check_lods_objects(lod_group: MultiExporterLODGroup) -> CheckLODsResult:
    """Check lod groups in objects mode.
    """

    all_enabled_lods_empty = True
    deleted_enabled_lods: set[str] = set()

    for lod in lod_group.lods:
        if not lod.enabled:
            continue
        lod: MultiExporterLOD

        if _in_scene(lod.objectLOD):
            all_enabled_lods_empty = False
        else:
            deleted_enabled_lods.add(lod.name)

    return CheckLODsResult(
        all_enabled_lods_empty=all_enabled_lods_empty,
        deleted_enabled_lods=deleted_enabled_lods,
    )

def _check_lods(lod_group: MultiExporterLODGroup, export_mode: multi_export_mode.ExportMode) -> CheckLODsResult:
    # region Check enabled LODS
    if export_mode == multi_export_mode.ExportMode.COLLECTIONS:  # type: ignore
        check_lods_result: CheckLODsResult = _check_lods_collections(lod_group)
    elif export_mode == multi_export_mode.ExportMode.OBJECTS:
        check_lods_result: CheckLODsResult = _check_lods_objects(lod_group)
    return check_lods_result

def _process_check_lods_result(check_lods_result: CheckLODsResult, lod_group: MultiExporterLODGroup, export_mode: multi_export_mode.ExportMode)->tuple[bool, bool]:
    """Process lods check result and log 
    appropriate messages when necessary.
    
    Returns:
        tuple[bool, bool]: (result, skip_next_checks)
    """

    result = True
    skip_next_checks = False

    lod_group_name = lod_group.name
    item_log_name = "object"

    if export_mode == multi_export_mode.ExportMode.COLLECTIONS:  # type: ignore
        item_log_name = "collection"

    if check_lods_result.deleted_enabled_lods:
        result = False
        invalid_armature_str = _get_list_formatted_string(
            check_lods_result.deleted_enabled_lods
        )

        MSFS2024_LOGGER.warning(
            message=f"'{lod_group_name}' : Contains deleted {item_log_name}s.",
            details=(
                f"LODs {item_log_name}s have been deleted:\n"
                + invalid_armature_str
                + "You can refresh list by pressing 'Reload LODs'."
            ),
        )

    if check_lods_result.empty_enabled_lods:
        empty_enabled_lods_str = _get_list_formatted_string(
            check_lods_result.empty_enabled_lods
        )
        MSFS2024_LOGGER.warning(
            message=f"'{lod_group_name}' : Some enabled LODs are empty.",
            details=(
                f"Following enabled LODs {item_log_name} are empty:\n" + 
                empty_enabled_lods_str
            ),
        )

    if check_lods_result.all_enabled_lods_empty:
        result = False
        MSFS2024_LOGGER.error(
            message=f"'{lod_group_name}' : Nothing to export!",
            details=f"'{lod_group_name}' enabled lods are empty!",
        )

    return result, skip_next_checks


def check_lod_groups(export_mode: multi_export_mode.ExportMode) -> bool:
    """Check LOD Group:
            - LODs (deleted objects, empty collections ...)
            - LOD Objects
            - Export Folder
            - Export Settings Texture Dir
    Returns:
        False if at least one lod group must not be exported.
    """

    enabled_lod_groups: list[MultiExporterLODGroup] = _get_enabled_lod_groups()

    if not enabled_lod_groups:
        MSFS2024_LOGGER.error(
            message="Nothing to export!",
            details="No item checked in the exporter list. Please check one to export.",
        )
        return False

    result = True
    lod_group: MultiExporterLODGroup
    scene_export_settings = export_settings.get_scene_settings_presets(bpy.context.scene)  # type: ignore
    for lod_group in enabled_lod_groups:

        msfs_export_settings: export_settings.MSFS2024_MultiExporterSettings | None = (
            scene_export_settings.get(lod_group.settings_preset, None)
        )
        # region Check enabled LODS
        check_lods_result: CheckLODsResult = _check_lods(lod_group, export_mode)

        _result, skip_next_checks = _process_check_lods_result(
            check_lods_result, lod_group, export_mode
        )
        if not _result:
            result = False
        if skip_next_checks:
            continue

        # region Check Objects

        check_objects_result: CheckObjectsResult = _check_objects(
            lod_group.get_lod_group_objects(
                export_mode, 
                enabled_only=True
            ),
            msfs_export_settings,
        )
        _result, skip_next_checks = _process_check_objects_result(check_objects_result, lod_group.name)
        if not _result:
            result = False
        if skip_next_checks:
            continue

        # Check Path
        check_export_folder_result: CheckExportFolderResult = _check_export_folder(
            lod_group.folder_path
        )
        _result, skip_next_checks = _process_check_export_folder_result(
            check_export_folder_result, lod_group.name
        )
        if not _result:
            result = False
        if skip_next_checks:
            continue

        # Check Export Settings
        absolute_export_path = check_export_folder_result.absolute_path
        check_export_settings_result: CheckExportSettingsResult = (
            _check_export_settings(msfs_export_settings, absolute_export_path)
        )

        _result, skip_next_checks = _process_check_export_settings_result(
            check_export_settings_result, lod_group.name, absolute_export_path
        )
        if not _result:
            result = False
        if skip_next_checks:
            continue

        # endregion

        # endregion

    return result


# endregion


# region Presets
def _get_enabled_presets() -> list[MultiExporterPreset]:
    preset: MultiExporterPreset
    enabled_presets: list[MultiExporterPreset] = []
    scene_presets = exp_presets.get_scene_exporter_presets(bpy.context.scene)
    for preset in scene_presets:  # type: ignore
        if preset.enabled:
            enabled_presets.append(preset)
            continue
    return enabled_presets


@dataclass
class CheckPresetLayersResult:

    no_enabled_layers: bool = False
    all_enabled_layers_empty: bool = False


def _check_preset_layers(preset: MultiExporterPreset) -> CheckPresetLayersResult:
    """
    Check preset layers:
        - Contains enabled layers.
        - All enabled layers are not empty.
    """
    no_enabled_layers = True
    all_enabled_layers_empty = True

    scene_collections: list[bpy.types.Collection] = (
        bpy.context.scene.collection.children_recursive # type: ignore
    )

    for layer in preset.layers:
        if not layer.enabled:
            continue
        no_enabled_layers = False

        in_scene = True
        layer: MultiExporterPresetLayer
        # Check if collection has not been deleted and is in scene
        try:
            collection: bpy.types.Collection = layer.collection
            collection.name  # try accessing name to check if still in bpy.data
            in_scene = collection in scene_collections
        except:
            # Deleted collection
            in_scene = False

        if in_scene and collection.all_objects:
            all_enabled_layers_empty = False

    return CheckPresetLayersResult(
        no_enabled_layers=no_enabled_layers,
        all_enabled_layers_empty=all_enabled_layers_empty,
    )

def _process_check_preset_layers_result(check_preset_layers_result: CheckPresetLayersResult, preset_name: str)->tuple[bool, bool]:
    """
    Process preset layers check result and log 
    appropriate messages when necessary.
    
    Returns:
        tuple[bool, bool]: (result, skip_next_checks)
    """

    result = True
    skip_next_checks = False
    if check_preset_layers_result.no_enabled_layers:
        result = False
        MSFS2024_LOGGER.error(
            message=f"'{preset_name}' : No enabled layers.",
            details=("Add layers to this preset by pressing 'Edit Layers' button."),
        )

    elif check_preset_layers_result.all_enabled_layers_empty:
        result = False
        MSFS2024_LOGGER.error(
            message=f"'{preset_name}' : Preset is empty!",
            details="All enabled layers are empty.",
        )

    return result, skip_next_checks

def check_presets() -> bool:
    """Check presets:
            - Empty enabled layers.
            - Layer Objects.
            - Export Folder
            - Export Settings Texture Dir
    Returns:
        False if at least one preset must not be exported.
    """
    enabled_presets: list[MultiExporterPreset] = _get_enabled_presets()

    if not enabled_presets:
        MSFS2024_LOGGER.error(
            message="Nothing to export!",
            details="No item checked in the exporter list. Please check one to export.",
        )
        return False
    
    result = True
    preset: MultiExporterPreset
    scene_export_settings = export_settings.get_scene_settings_presets(bpy.context.scene)  # type: ignore

    for preset in enabled_presets:
        msfs_export_settings: export_settings.MSFS2024_MultiExporterSettings | None = (
            scene_export_settings.get(preset.settings_preset, None)
        )

        # Check Layers
        check_preset_layers_result: CheckPresetLayersResult = _check_preset_layers(preset)
        _result, skip_next_checks = _process_check_preset_layers_result(
            check_preset_layers_result, preset.preset_name
        )
        if not _result:
            result = False
        if skip_next_checks:
            continue
            
        # region Check Objects
        check_objects_result: CheckObjectsResult = _check_objects(
            preset.get_preset_objects(),
            msfs_export_settings
        )
        _result, skip_next_checks = _process_check_objects_result(check_objects_result, preset.preset_name)
        if not _result:
            result = False
        if skip_next_checks:
            continue

        # Check Path
        check_export_folder_result: CheckExportFolderResult = _check_export_folder(
            preset.folder_path
        )
        _result, skip_next_checks = _process_check_export_folder_result(
            check_export_folder_result, preset.preset_name
        )
        if not _result:
            result = False
        if skip_next_checks:
            continue

        # Check export setting
        absolute_export_path = check_export_folder_result.absolute_path
        check_export_settings_result: CheckExportSettingsResult = (
            _check_export_settings(msfs_export_settings, absolute_export_path)
        )

        _result, skip_next_checks = _process_check_export_settings_result(
            check_export_settings_result, preset.preset_name, absolute_export_path
        )
        if not _result:
            result = False
        if skip_next_checks:
            continue

        # endregion

        

    return result


# endregion


def pre_export_check(export_mode: multi_export_mode.ExportMode, operator: bpy.types.Operator | None) -> bool:
    """
    Run basic checks before launching export.
    Must be fast, do not add long process during this step.
    """
    global MSFS2024_LOGGER
    MSFS2024_LOGGER = msfs_logs.get_logger()

    export_settings.init_setting_presets(bpy.context.scene)

    result = True # block export if false

    result = check_preferences()
    if not result and operator:
        msfs_logs.process_logger_report(operator, MSFS2024_LOGGER)

    if export_mode == multi_export_mode.ExportMode.OBJECTS or export_mode == multi_export_mode.ExportMode.COLLECTIONS:
        result = check_lod_groups(export_mode)

    elif export_mode == multi_export_mode.ExportMode.PRESETS:
        result = check_presets()

    if not result and operator:
        msfs_logs.process_logger_report(operator, MSFS2024_LOGGER)

    return result
