from __future__ import annotations

from typing import TYPE_CHECKING
import bpy
import mathutils


from lod_tools_msfs_2024 import (
    data_properties,
    lod_camera,
    lod_viewer_node_groups,
    prefs,
    lod_viewer_collections,
    bounding_volume, 
    lod_group_infos,
    obj_utils,
    data_utils
)
from lod_tools_msfs_2024.datafiles import asset_library
from lod_tools_msfs_2024.datafiles.asset_library import (
    NodeGroupLibrary,
    MSFS2024LODViewerInputs,
    
)


from io_scene_gltf2_msfs_fss.io.exp import multi_export_mode
from io_scene_gltf2_msfs_fss.io.exp import lod_groups as exp_lod_groups
from io_scene_gltf2_msfs_fss.io.exp import presets as exp_presets
from _addons_common import geometry_node_utils

if TYPE_CHECKING:
    from io_scene_gltf2_msfs_fss.io.exp.lod_groups import  MultiExporterLODGroup


def create_lod_viewer(
    name: str,
    camera: bpy.types.Object,
    bsphere: bpy.types.Object,
    lod_group: lod_group_infos.LODGroupInfos,
    depsgraph: bpy.types.Depsgraph
) -> bpy.types.Object:

    node_group_asset = NodeGroupLibrary.LOD_VIEWER

    mesh_data = bpy.data.meshes.new(name=node_group_asset.label_name)
    lod_viewer_obj = bpy.data.objects.new(f"{name}_LODS", mesh_data)
    data_properties.tag_as_lod_viewer(lod_viewer_obj)
    data_properties.set_lod_viewer_source(
        lod_viewer_obj, 
        lod_group.exporter_source_data_path, 
        lod_group.name
    )
    # Lock Scale
    obj_utils.set_lock_scale(lod_viewer_obj, True)


    modifier = node_group_asset.add_modifier(object=lod_viewer_obj)

    inputs: MSFS2024LODViewerInputs = node_group_asset.node_group_inputs
    geometry_node_utils.set_modifier_input(modifier, inputs.CAMERA.input_label, camera)
    geometry_node_utils.set_modifier_input(
        modifier, inputs.BOUNDING_SPHERE.input_label, bsphere
    )
    # Create lod stats entries in order
    for i in range(lod_group.lod_count):
        stats_entry = data_properties.add_lod_stats_entry(
            lod_viewer_obj, i
        )

    next_lod_min_size = 0
    next_lod_estimated_min_size = 0
    # Loop lods in reverse to make sure minSizes are always increasing
    for i in range(lod_group.lod_count, -1, -1):
        screen_size = lod_group.get_lod_min_size(i)
        collection = lod_group.get_lod_collection(i)
        if not collection:
            continue

        stats_entry = data_properties.get_lod_stats_entry(lod_viewer_obj,i)
        if not stats_entry:
            break

        stats_entry.min_size = screen_size

        data_properties.compute_stats(
            stats_entry, 
            i, 
            lod_group.lod_count, 
            lod_group.get_lod_objects(i), 
            depsgraph
        )

        stats_entry.min_size = max(stats_entry.min_size, next_lod_min_size)
        stats_entry.estimated_min_size = max(stats_entry.estimated_min_size, next_lod_estimated_min_size)

        next_lod_estimated_min_size= stats_entry.estimated_min_size

        screen_size = stats_entry.get_size_to_use(percentage=True)

        geometry_node_utils.set_modifier_input(
            modifier, inputs.get_lod_collection_input(i).input_label, collection
        )
        geometry_node_utils.set_modifier_input(
            modifier, inputs.get_lod_screen_size_input(i).input_label, screen_size
        )

    geometry_node_utils.set_modifier_input(
        modifier, inputs.LOD_COUNT.input_label, lod_group.lod_count
    )

    obj_utils.set_parent_keep_transform(bsphere, lod_viewer_obj)

    return lod_viewer_obj


PROFILING = False


def _generate_lod_viewers(
    lod_infos: list[lod_group_infos.LODGroupInfos],
    scene: bpy.types.Scene,
    temp_scene: bpy.types.Scene,
):

    if PROFILING:
        import cProfile
        import pstats
        import io
        profiler = cProfile.Profile()
        profiler.enable()

    context = bpy.context
    addon_prefs = prefs.get_addon_prefs()
    render_settings: prefs.RenderSettings = addon_prefs.render_settings
    lod_viewer_settings: prefs.LODViewerSettings = addon_prefs.lod_viewer_settings
    debug_settings: prefs.DebugSettings = addon_prefs.debug_settings
    lod_factor = render_settings.lod_factor

    lod_viewer_collection = lod_viewer_collections.init_scene_lod_viewer_collection(scene)

    camera_proxy = lod_camera.init_scene_lod_camera_proxy(scene)

    appended_bsphere_obj: bpy.types.Object = (
                asset_library.ObjectLibrary.BOUNDING_SPHERE.append_asset()
            )

    current_node_groups = set(bpy.data.node_groups)

    context.window.scene = temp_scene
    temp_scene_depsgraph = context.evaluated_depsgraph_get()

    # Safely compute bounding spheres and lod viewer vertex count in temp_scene
    created_lod_viewers: list[bpy.types.Object] = []
    for lod_group in lod_infos:
        last_lod_index = lod_group.lod_count - 1
        last_lod_objects = lod_group.get_lod_collection_objects(last_lod_index)
        if not last_lod_objects:
            continue

        bsphere_center, bsphere_radius = bounding_volume.get_msfs_bounding_sphere(
            last_lod_objects,
            bounding_volume.VolumeGetMode.MESH,
            temp_scene_depsgraph
        )

        if bsphere_center is None or bsphere_radius is None:
            continue

        bsphere = appended_bsphere_obj.copy()
        # Set matrix world directly in order to be able
        # to correctly parent bsphere to lod_viewer

        bsphere.matrix_world = mathutils.Matrix.LocRotScale(
            bsphere_center,
            mathutils.Quaternion(),
            (bsphere_radius, bsphere_radius, bsphere_radius),
        )
        lod_viewer = create_lod_viewer(
            lod_group.name,
            camera_proxy,
            bsphere,
            lod_group,
            temp_scene_depsgraph,
        )
        created_lod_viewers.append(lod_viewer)
        if (
            not lod_group.lod_viewer_offset is None
            and lod_viewer_settings.align_lod_viewer_to_source
        ):
            source_location, source_rotation, _ = (
                lod_group.lod_viewer_offset.decompose()
            )
            lod_viewer.matrix_world = mathutils.Matrix.LocRotScale(
                source_location, source_rotation, lod_viewer.matrix_world.to_scale()
            )

        lod_viewer_collection.objects.link(lod_viewer)

    # Remove Temp Scene
    bpy.data.scenes.remove(temp_scene)

    context.window.scene = scene

    # Offset all lod groups by lod groups bsphere diameter
    if ( lod_viewer_settings.lod_viewer_offset
        != prefs.LODViewerOffsetDirection.NONE.identifier
    ):
        depsgraph = context.evaluated_depsgraph_get()
        _box_center, box_size = bounding_volume.get_bounding_box(
            scene.objects, bounding_volume.VolumeGetMode.BOUNDING_BOX, depsgraph
        )
        translation_matrix = None
        if box_size is not None:
            offset_direction = prefs.LODViewerOffsetDirection.from_identifier(
                lod_viewer_settings.lod_viewer_offset
            )
            if offset_direction and offset_direction.vector is not None:
                vector = offset_direction.vector * box_size[offset_direction.axis_index]
                translation_matrix = mathutils.Matrix.Translation(vector)
        if translation_matrix:
            for lod_viewer in created_lod_viewers:
                lod_viewer.matrix_world = translation_matrix @ lod_viewer.matrix_world

    # Set LOD Viewer constants and scene properties
    if created_lod_viewers:
        lod_viewer = created_lod_viewers[0]
        # Find appendend LOD Viewer node groups
        lod_viewer_node_group = None
        lod_viewer_constants_node_group = None
        new_node_groups = set(bpy.data.node_groups).difference(current_node_groups)
        if not new_node_groups:
            # Can happen if file already contains node groups before the process
            new_node_groups = bpy.data.node_groups

        for node_group in new_node_groups:
            if asset_library.NodeGroupLibrary.LOD_VIEWER.is_asset_instance(node_group):
                lod_viewer_node_group = node_group
            elif asset_library.NodeGroupLibrary.LOD_VIEWER_CONSTANTS.is_asset_instance(node_group):
                lod_viewer_constants_node_group = node_group

            if lod_viewer_constants_node_group and lod_viewer_node_group:
                break

        data_properties.set_scene_lod_node_groups(
            scene,
            lod_viewer_collection,
            lod_viewer_node_group,
            lod_viewer_constants_node_group,
        )

        lod_viewer_node_groups.setup_lod_viewer_constants(
            scene, 
            lod_camera.get_context_fov_y(context), 
            lod_factor, 
            debug_settings.display_bounding_spheres
        )

        lod_viewer_node_groups.construct_lod_viewer_input_map()

    debug_settings.update_debug_draw()

    lod_camera.enable_lod_camera(context, camera_proxy.name, True)

    if PROFILING:
        profiler.disable()
        # Print stats to the console
        s = io.StringIO()
        ps = pstats.Stats(profiler, stream=s).sort_stats("cumtime")
        ps.print_stats(50)
        print(s.getvalue())


def generate_lod_viewers(
    scene: bpy.types.Scene, msfs_lod_groups: list | bpy.types.bpy_prop_collection | None = None
):
    """Create a Lod Viewer collection containing LOD Viewer objects.

    We assume that msfs2024 exporter is loaded.

    if not msfs_lod_groups then we generate lod viewers of all scene lod groups.
    """
    export_mode = multi_export_mode.get_active_export_mode(scene)
    if not export_mode:
        return
    if msfs_lod_groups is None:
        if export_mode == multi_export_mode.ExportMode.OBJECTS or export_mode == multi_export_mode.ExportMode.COLLECTIONS:
            msfs_lod_groups = exp_lod_groups.get_scene_lod_groups(scene)
        else:
            msfs_lod_groups = exp_presets.get_scene_exporter_preset_groups(scene)

    scene_lod_groups, temp_scene = lod_group_infos.construct_scene_lod_group_infos(
        scene, export_mode, msfs_lod_groups
    )

    if not scene_lod_groups or not temp_scene:
        return

    _generate_lod_viewers(scene_lod_groups, scene, temp_scene)


def clean_scene_lod_viewer(scene: bpy.types.Scene):
    lod_camera.delete_scene_lod_camera(scene)
    lod_viewer_collections.clean_scene_lod_viewer_collection(scene)

def get_lod_viewer_modifier(obj: bpy.types.Object):
    if not obj.type == "MESH":
        return None
    modifiers = obj.modifiers
    if not modifiers:
        return
    for mod in modifiers:
        if not (mod.type == "NODES" and mod.node_group):
            continue
        if mod.node_group.name == NodeGroupLibrary.LOD_VIEWER.id_name:
            return mod
    return None


def get_active_lod_viewer_modifier(
    context: bpy.types.Context,
) -> bpy.types.Modifier | None:
    active_object = context.view_layer.objects.active
    if not active_object:
        return None
    return get_lod_viewer_modifier(active_object)


def send_lod_setup_to_exporter(obj: bpy.types.Object) -> bool | type[data_properties.OutdatedLodGroup]:
    source = data_properties.get_lod_viewer_source(obj)

    if source is None :
        return False

    if source is data_properties.OutdatedLodGroup:
        return data_properties.OutdatedLodGroup
    
    source: MultiExporterLODGroup
    # Same pattern in panel
    lod_viewer_input_map = lod_viewer_node_groups.get_lod_viewer_input_map()
    if not lod_viewer_input_map:
        return False

    lod_viewer_modifier = get_lod_viewer_modifier(obj)

    if not lod_viewer_modifier:
        return False
    lod_count_identifier = lod_viewer_input_map.get(
        MSFS2024LODViewerInputs.LOD_COUNT.value, None
    )
    if not lod_count_identifier:
        return False

    lod_count = geometry_node_utils.get_modifier_input_value(lod_viewer_modifier, lod_count_identifier)
    if not lod_count > 1 or lod_count != len(source.lods):
        return False

    for i in range(lod_count):
        screen_size_label = MSFS2024LODViewerInputs.get_lod_screen_size_input(i)
        if not screen_size_label:
            return False
        screen_size_identifier = lod_viewer_input_map.get(screen_size_label.value, None)
        if not screen_size_identifier:
            return False
        val = geometry_node_utils.get_modifier_input_value(lod_viewer_modifier, screen_size_identifier)
        if val is None:
            return False
        source.lods[i].lod_value = val

    return True



