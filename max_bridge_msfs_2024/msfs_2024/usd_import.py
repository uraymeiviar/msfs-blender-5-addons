from __future__ import annotations

import bpy


from max_bridge_msfs_2024 import logger, addon_prefs
from max_bridge_msfs_2024.common import  obj_utils,anim_utils
from max_bridge_msfs_2024.common.usd_import import *
from max_bridge_msfs_2024.common.usd_properties import *

from max_bridge_msfs_2024.msfs_2024 import import_utils, setting_preset_utils, dependencies
from max_bridge_msfs_2024.msfs_2024 import mat_utils as msfs_2024_mat_utils
from max_bridge_msfs_2024.msfs_2024 import obj_utils as msfs_2024_obj_utils
from max_bridge_msfs_2024.msfs_2024.msfs_properties import *


from io_scene_gltf2_msfs_fss.io.exp import multi_export_mode
from io_scene_gltf2_msfs_fss.io.exp import lod_groups as exp_lod_groups
from io_scene_gltf2_msfs_fss.io.exp import presets as exp_presets

logging = logger.getLogger()


class MSFS2024USDImporter(GenericUSDImporter):
    IMPORTER = "MSFS2024USDImporter"  # used in export_definition
    DCC = "BLENDER"  # used in export_definition

    @classmethod
    def can_import(cls) -> bool:

        return dependencies.are_dependencies_loaded(show_warning=True)

    # region Custom Properties to reimplement
    @classmethod
    def set_obj_with_custom_class(
        cls,
        obj:bpy.types.Object,
        obj_def: ObjectDef
    ) ->bpy.types.Object:
        """
        Initialize MSFS2024 custom object.
        Replace provided obj by a new one.
        """ 
        new_obj = msfs_2024_obj_utils.create_msfs2024_object(obj, obj_def.type, obj_def.custom_class_properties)
        if not new_obj:
            return obj
        return new_obj

    @classmethod
    def set_additional_custom_properties(
        cls,
        properties: dict,
        imported_object_defs: OBJECT_DEFS,
        imported_material_defs: MATERIAL_DEFS
    ):
        prefs = addon_prefs.get_addon_prefs()
        if prefs.msfs_2024_set_exporter_settings:
            cls._create_presets(properties)
        cls._setup_actions_from_anim_groups(properties, imported_object_defs)

    @staticmethod
    def _reload_lod_group():
        if (
            multi_export_mode.get_active_export_mode(bpy.context.scene)
            == multi_export_mode.ExportMode.COLLECTIONS
        ):
            logging.warning(f"LOD group are no going to be setup because Hierarchy Mode is set to '{multi_export_mode.ExportMode.COLLECTIONS.label}'.\n"
                            f"Hierarchy Mode must be set to '{multi_export_mode.ExportMode.OBJECTS.label}' to import LOD Groups from 3ds Max.")
        else:
            exp_lod_groups.reload_lod_groups(bpy.context.scene)
    @classmethod
    def on_before_definitions_set(
        cls,
        imported_objects: list[bpy.types.Object],
        imported_object_defs: OBJECT_DEFS,
        imported_material_defs: MATERIAL_DEFS,
    ):
        """
        Reload LodGroups after objects are imported
        """
        # Lod groups need to be created
        cls._reload_lod_group()

    @classmethod
    def on_after_import(
        cls,
        imported_objects: list[bpy.types.Object],
        imported_object_defs: OBJECT_DEFS,
        imported_material_defs: MATERIAL_DEFS,
    ):
        """
        Reload LodGroups after objects are imported
        """
        # Needed to refresh checkboxes
        bpy.ops.msfs2024.reload_lod_groups()

    @classmethod
    def set_obj_custom_properties(cls, obj:bpy.types.Object, properties: dict) :
        """
        MSFS2024 LODGroup creations.
        """
        prefs = addon_prefs.get_addon_prefs()
        if prefs.msfs_2024_set_exporter_settings:
            cls._set_obj_lod_group(obj, properties)

    @classmethod
    def set_material_custom_properties(cls, material:bpy.types.Material, properties: dict) :
        """
        MSFS 2024 Material Setup
        """
        material.use_nodes = True  # enable shaders nodes

        # first we set up material type:
        material_type = properties[
            MSFS2024_MaterialProperties.MATERIALTYPE.name
        ]
        if material_type == "NONE":
            return
        setattr(
            material,
            MSFS2024_MaterialProperties.MATERIALTYPE.blender_name,
            material_type,
        )

        msfs_mat_attributes = msfs_2024_mat_utils.get_material_attributes_names(material_type)

        if not msfs_mat_attributes:
            return

        for prop in MSFS2024_MaterialProperties:
            if (
                prop == MSFS2024_MaterialProperties.MATERIALTYPE
                or prop.blender_name not in msfs_mat_attributes
            ):
                # only assign attributes needed by each material type.
                # blindly assigning all MSFS2024_MaterialProperties cause issues for material export.
                continue
            if (
                prop.blender_name == NOTIMPLEMENTED
                or properties.get(prop.name) is None
            ):
                continue

            value = properties[prop.name]
            value = import_utils.convert_mat_prop(prop, value)

            try:
                setattr(material, prop.blender_name, value)
                logging.debug(
                    f"Material {material.name} : set {prop.blender_name} to {value}"
                )
            except Exception as e:
                logging.error(
                    f"Material {material.name} : couldn't set mat property '{prop.blender_name}'"
                    f"Error: {e}"
                )

    # endregion

    @classmethod
    def _set_obj_lod_group (cls, obj:bpy.types.Object, properties: dict):

        target_lod_group = None
        target_lod = None
        scene_lod_groups = exp_lod_groups.get_scene_lod_groups(bpy.context.scene)
        for lod_group in scene_lod_groups:
            for lod in lod_group.lods:
                if lod.objectLOD == obj:
                    target_lod_group = lod_group
                    target_lod = lod
                    break

        if target_lod_group:
            for prop in MSFS2024_ObjectExportProperties:
                if (
                    prop.blender_name == NOTIMPLEMENTED
                    or properties.get(prop.name) is None
                ):
                    continue
                value = properties[prop.name]
                prop_blender_name = prop.blender_name
                # value = cls._convert_export_prop(prop, value)

                if (
                    prop == MSFS2024_ObjectExportProperties.LOD_VALUE
                    and target_lod
                ):
                    setattr(target_lod, prop_blender_name, value)
                else:
                    setattr(target_lod_group, prop_blender_name, value)

                logging.debug(f"{obj.name} : Set {prop_blender_name} to {value}")

            # enable generate xml by default
            target_lod_group.generate_xml = True
            # enable all lod by default
            for lod in target_lod_group.lods:
                lod.enabled = True
        else:
            logging.error(
                f"{obj.name} : Can't setup export properties, no lod_group found.")

    @classmethod
    def _create_presets(cls, properties: dict):
        from io_scene_gltf2_msfs_fss.ui.exp import preset_uilist
        # Export Options Creation
        export_options_presets = get_export_options_presets_from_custom_properties(properties)
        new_settings_presets = {}
        for export_option_def in export_options_presets:
            export_option_def:MSFS2024_ExportOptionsPresetDef
            settings_preset = setting_preset_utils.create_settings_preset_from_def(export_option_def)
            new_settings_presets[export_option_def.handle] = settings_preset.name
        # Presets and Preset Groups creation
        presets, preset_groups = get_presets_from_custom_properties(properties)

        new_groups_guid = {} # store new group guids by group handle
        for group_def in preset_groups:
            group_def: MSFS2024_PresetGroupDef
            group = exp_presets.add_preset_group(bpy.context.scene)
            group.group_name = group_def.name
            group.folder_path = group_def.path
            setting_preset = new_settings_presets.get(group_def.export_options, None)
            if setting_preset:
                group.settings_preset = setting_preset
            logging.info(f"New Preset Group : {group.group_name}")

            new_groups_guid[group_def.handle] = group.name

        for preset_def in presets:
            preset_def:MSFS2024_PresetDef
            group_id = preset_def.group

            preset = exp_presets.add_preset(bpy.context.scene)
            preset.preset_name = preset_def.name
            preset.folder_path = preset_def.path

            if group_id:
                settings_preset = None
                preset_group = None
                group_guid = new_groups_guid.get(group_id, None)
                
                if group_guid is not None:
                    scene_preset_groups = exp_presets.get_scene_exporter_preset_groups(
                        bpy.context.scene
                    )
                    preset_group = scene_preset_groups.get(group_guid)
                if preset_group:
                    preset.group_id = preset_group.name
                    settings_preset = preset_group.settings_preset
                else:
                    logging.error(f"Couldn't add preset {preset.preset_name} to group {group_guid}")
                preset.settings_preset = settings_preset 
                logging.info(f"New Preset in {preset_group.group_name}: {preset.preset_name} ")
            else:
                logging.info(f"New Preset : {preset.preset_name}")

            # Set Enabled layers
            for layer_name in preset_def.layer_names:
                layer = preset.layers.get(layer_name, None)
                if layer:
                    # Faster than layer.enabled since it doesnt trigger property update function
                    layer["enabled"] = True

        preset_tree_manager = preset_uilist.get_preset_tree_manager()
        if not preset_tree_manager:
            return
        preset_tree_manager.generate_ui_tree_collection()

    @classmethod
    def _setup_actions_from_anim_groups(cls, 
            properties: dict,
            imported_object_defs: OBJECT_DEFS
        ):

        anim_groups = get_anim_groups_from_custom_properties(properties)
        imported_armatures = []
        f_imported_object_defs = {}

        # Filter armature object
        for obj, obj_def in imported_object_defs.items():
            # Get a list of anim defs for each obj_def
            if obj_utils.is_armature(obj):
                imported_armatures.append(obj)
            else:
                f_imported_object_defs[obj] = obj_def

        # Treat normal objects
        for obj, obj_def in f_imported_object_defs.items(): 

            # Get imported action
            imported_action = anim_utils.get_object_action(obj)
            if not imported_action:

                continue

            if anim_utils.SUPPORTED_ACTION_SLOTS :
                active_slot = anim_utils.get_object_action_slot(obj)
                if not active_slot:
                    # no slot assigned, animation_data is useless
                    anim_utils.clear_animation(obj)
                    continue

            imported_action.name = f"Bridge_Backup_{obj_def.name}"

            obj_anim_defs = []
            for anim_def in anim_groups:
                if obj_def.handle in anim_def.nodes:
                    obj_anim_defs.append(anim_def)

            for anim_def in obj_anim_defs:
                name = f"{anim_def.name}_{obj_def.name}"

                new_action = anim_utils.extract_action_range(
                    source_action=imported_action,
                    frame_range=(anim_def.frame_start, anim_def.frame_end),
                    name=name,
                    remap_to_zero=True,
                )

                anim_utils.add_nla_track_with_action(obj, new_action, anim_def.name)

                logging.info(
                    f"[OBJ] {obj_def.name} [HANDLE] {obj_def.handle} New action pushed down in NLA : {new_action.name}"
                )

            # Remove action if object has anim_groups or if it is static
            if obj_anim_defs:
                anim_utils.remove_object_action(obj)
            elif anim_utils.is_action_static(imported_action):
                anim_utils.remove_object_action(obj)
        # Process armatures
        for armature in imported_armatures: 

            imported_action = anim_utils.get_object_action(armature)
            if not imported_action:
                continue
            if anim_utils.SUPPORTED_ACTION_SLOTS :
                active_slot = anim_utils.get_object_action_slot(armature)
                if not active_slot:
                    # no slot assigned, animation_data is useless
                    anim_utils.clear_animation(armature)
                    continue

            imported_action.name = f"Bridge_Backup_{armature.name}"

            handle_bones_defs ={}

            # Get bone defs using handle
            for bone in armature.data.bones:
                bone_handle = obj_utils.get_handle_from_name(bone.name)
                if bone_handle is None:
                    continue
                bone_def = obj_utils.get_definition_by_handle(bone_handle,imported_object_defs.values())

                if not bone_def:
                    continue
                handle_bones_defs[bone_handle]=bone

            # Get used anim defs and their associated bones
            armature_anim_defs = []
            anim_defs_bones = [] #  list of tuples containing bones used by anim
            for anim_def in anim_groups:

                anim_bones = []
                for handle, bone in handle_bones_defs.items():
                    if handle in anim_def.nodes:
                        anim_bones.append(bone)
                if anim_bones:
                    armature_anim_defs.append(anim_def)
                    anim_defs_bones.append(anim_bones)

            for anim_def, bones in zip(armature_anim_defs,anim_defs_bones):
                # We create an action for each anim_def found

                name = f"{anim_def.name}_{armature.name}"
                new_action = anim_utils.extract_action_range(
                    source_action=imported_action,
                    frame_range=(anim_def.frame_start, anim_def.frame_end),
                    name=name,
                    remap_to_zero=True,
                )

                bones_names = set([bone.name for bone in bones])
                anim_utils.filter_action_to_bones(new_action, bones_names)
                anim_utils.add_nla_track_with_action(armature,new_action,anim_def.name)
                logging.info(f"[ARMATURE] {armature.name} New action pushed down in NLA : {new_action.name}")

            # Remove action if armature has anim_groups or if it is static
            if armature_anim_defs:
                anim_utils.remove_object_action(armature)
            elif anim_utils.is_action_static(imported_action):
                anim_utils.remove_object_action(armature)
