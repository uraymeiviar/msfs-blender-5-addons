from typing import TYPE_CHECKING
import uuid
import addon_utils
import bpy

from io_scene_gltf2_msfs_fss.blender import msfs_gizmo
from io_scene_gltf2_msfs_fss.blender.utils import msfs_object_utils

from io_scene_gltf2_msfs_fss.io.exp import multi_export_mode, export_settings
from io_scene_gltf2_msfs_fss.io.exp import presets as exp_presets

from io_scene_gltf2_msfs_fss.io.exp.presets import (
    MultiExporterPreset,
    MultiExporterPresetGroup
)

from io_scene_gltf2_msfs_fss.io.exp import lod_groups as exp_lod_groups

from io_scene_gltf2_msfs_fss.datafiles import asset_library



from .msfs_lights import force_update_all_lights
from .utils.msfs_scene_utils import MSFS2024_SceneUtils

from . import msfs_gizmo

from io_scene_gltf2_msfs_fss.ui.exp import lod_groups_uilist, preset_uilist


converting_old_gizmo = False

def replace_old_gizmos(scene:bpy.types.Scene):
    """Replace scene old gizmos (empties with a msfs_gizmo_type prop)
    by new ones using geometry nodes modifiers.

    OLD gizmo properties

    bpy.types.Object.msfs_gizmo_type = bpy.props.EnumProperty(
        name="Type",
        description="Type of collision gizmo to add",
        items=(("NONE", "Disabled", ""),
              ("sphere", "Sphere Collision Gizmo", ""),
              ("box", "Box Collision Gizmo", ""),
              ("cylinder", "Cylinder Collision Gizmo", ""),
              ("boundingSphere", "Skin Bounding Volume Gizmo", "")
        )
    )
    bpy.types.Object.msfs_collision_is_road_collider = bpy.props.BoolProperty(name="Road Collider", default=False)
    bpy.types.Object.msfs_collision_is_ground_collider = bpy.props.BoolProperty(name="Ground Collider", default=False)
    """

    global converting_old_gizmo
    if converting_old_gizmo:
        return
    # Prevent import handlers to be launched recursively
    # Can happen when this function is called from an import handler
    # during collision gizmos creation
    converting_old_gizmo = True

    old_value = ("NONE", "sphere", "box", "cylinder", "boundingSphere")
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for obj in list(scene.objects): #loop over a copy of scene objects
        if not obj.type == "EMPTY" :
            continue
        # Even if property is not registered, we can retrieved it
        # if it is not set to its default value
        old_attrib = "msfs_gizmo_type"
        gizmo_type_index = obj.get(old_attrib, None)
        if gizmo_type_index is None:
            continue
            # Not a gizmo, or property is set to default "NONE"
        try:
            gizmo_type = old_value[gizmo_type_index]
        except :
            print("Invalid gizmo type index")
            continue
        gizmo_type = msfs_gizmo.GizmoTypes.from_identifier(gizmo_type)
        if not gizmo_type:
            continue
        new_gizmo = msfs_gizmo.create_gizmo(gizmo_type)
        print(f"Replaced old gizmo of type {gizmo_type} ")
        msfs_object_utils.replace_obj_by(obj, new_gizmo, depsgraph=depsgraph)

    converting_old_gizmo = False

def _convert_old_scene(scene: bpy.types.Scene):

    # Unified add-on: legacy gizmo empties are NOT replaced on load. They are the MSFS 2020 export
    # representation of collisions; converting them to MSFS 2024 gizmos is an explicit step.

    # Presets compatibility
    scene_presets = exp_presets.get_scene_exporter_presets(scene)
    for preset in scene_presets:        
        if preset.preset_name == "":
            preset.preset_name = preset.name
            preset.name = str(uuid.uuid4())

    # Object LOD Group compatibility
    scene_lod_groups = exp_lod_groups.get_scene_lod_groups(scene)
    for lod_group in scene_lod_groups:
        if lod_group.group_name != "":
            lod_group.name = lod_group.group_name

    # Removed properties special case

    # A deleted property is kept in scene attributes if it is not set to its default value.

    # Definition of multi_exporter_grouped_by_collections:
    # bpy.types.Scene.multi_exporter_grouped_by_collections = bpy.props.BoolProperty( # type: ignore
    #     name="Grouped by collections",
    #     default=False,
    # )
    # This property defined if lod groups in msfs_multi_exporter_lod_groups where using collections to store lod objects.
    
    # It has now been replaced by bpy.types.Scene.msfs_export_mode
    old_attrib = "multi_exporter_grouped_by_collections"
    grouped_by_collections = scene.get(old_attrib, None)
    if grouped_by_collections is not None:
        # in this case we force export mode to collection
        # since it is present it should be set to True, but check it anyway:
        if grouped_by_collections:
            scene.msfs_export_mode = multi_export_mode.ExportMode.COLLECTIONS.identifier
        else:
            scene.msfs_export_mode = multi_export_mode.ExportMode.OBJECTS.identifier
        # Remove the property so we skip this step next time
        scene.pop(old_attrib)

def prepare_scenes():
    # Try accessing bpy.data to check if blender is ready
    try:
        bpy.data.scenes
    except:
        return
    
    asset_library.NodeGroupLibrary.update_appended_assets()

    # Unified add-on: decide every scene's export target, then migrate materials authored with the
    # MSFS 2020 add-on to MSFS 2024 meaning (once per material), before any graph is rebuilt
    from io_scene_gltf2_msfs_fss import legacy_normals, migration, msfs2020_target
    # Blender <= 4.0 files: keep the per-mesh Auto Smooth flag Blender drops on load (Restore 3.6 Normals)
    legacy_normals.record_legacy_auto_smooth()
    for scene in bpy.data.scenes:
        msfs2020_target.detect_export_target(scene)
    migration.migrate_materials(bpy.context.scene)

    addon_name = "io_scene_gltf2_msfs"
    (loaded_default, loaded_state) = addon_utils.check(addon_name)
    # Update material graph nodes if 2020 addon is not enabled
    if not loaded_default and not loaded_state:
        MSFS2024_SceneUtils.update_msfs2024_materials_graphs()

    force_update_all_lights()

    original_scene = bpy.context.scene
    for scene in bpy.data.scenes:
        
        _convert_old_scene(scene)

        MultiExporterPreset.update_presets_full_data_path(scene)
        MultiExporterPresetGroup.update_groups_full_data_path(scene)

        # Settings Presets
        export_settings.init_setting_presets(scene)

        export_mode = multi_export_mode.get_active_export_mode(scene)
        # Force exporter ui tree items generation
        # we need to change scene using context because the tree managers
        # are context sensitive

        bpy.context.window.scene = scene
        if (
            export_mode == multi_export_mode.ExportMode.OBJECTS
            or export_mode == multi_export_mode.ExportMode.COLLECTIONS
        ):

            exp_lod_groups.reload_lod_groups(scene)
            # UI List refresh for each scene
            lod_group_tree_manager = lod_groups_uilist.get_lod_group_tree_manager()
            if lod_group_tree_manager:
                lod_group_tree_manager.generate_tree_collection()

        preset_tree_manager = preset_uilist.get_preset_tree_manager()
        if preset_tree_manager:
            preset_tree_manager.generate_tree_collection()

    if bpy.context.window.scene != original_scene:
        bpy.context.window.scene = original_scene
