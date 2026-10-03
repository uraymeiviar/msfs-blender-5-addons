"""
"Prepare for MSFS 2024": add the MSFS 2024 representation of MSFS 2020 data next to it.

The MSFS 2024 add-on converts MSFS 2020 data in place (gizmo empties replaced on load, lights replaced by
`convert_lights_to_msfs2024`), after which the file can no longer be exported for MSFS 2020. Here nothing is
replaced: each converted object gets an MSFS 2024 counterpart, the counterpart is marked "MSFS 2024 Only"
and the original "MSFS 2020 Only" (Object.msfs_fss_export_only), so each export keeps using its own.
"""

import bpy

from .. import msfs2020_target
from ..blender import msfs_gizmo, msfs_lights
from ..blender.msfs_lights import MSFS2024LightType
from ..blender.utils import msfs_object_utils

_COUNTERPART = "msfs_fss_msfs2024_counterpart"  # custom property: name of the object's MSFS 2024 counterpart


def _has_counterpart(obj) -> bool:
    name = obj.get(_COUNTERPART)
    return bool(name) and bpy.data.objects.get(name) is not None


def _legacy_gizmos(scene):
    return [obj for obj in scene.objects
            if obj.type == "EMPTY" and getattr(obj, "msfs_gizmo_type", "NONE") != "NONE" and not _has_counterpart(obj)]


def _legacy_lights(scene):
    return [obj for obj in scene.objects
            if obj.type == "LIGHT" and obj.data is not None
            and obj.data.msfs_light_type == MSFS2024LightType.NONE.identifier
            and obj.msfs_fss_export_only != msfs2020_target.TARGET_MSFS2024 and not _has_counterpart(obj)]


def pending_counts(scene):
    return len(_legacy_gizmos(scene)), len(_legacy_lights(scene))


def _place_next_to(original, counterpart, depsgraph):
    for collection in original.users_collection:
        if counterpart.name not in collection.objects:
            collection.objects.link(counterpart)
    msfs_object_utils.copy_transform(original, counterpart, depsgraph)
    msfs_object_utils.set_parent_keep_transform(counterpart, original.parent, depsgraph)
    original[_COUNTERPART] = counterpart.name
    original.msfs_fss_export_only = msfs2020_target.TARGET_MSFS2020
    counterpart.msfs_fss_export_only = msfs2020_target.TARGET_MSFS2024


def _add_gizmo_counterpart(empty, depsgraph):
    gizmo_type = msfs_gizmo.GizmoTypes.from_identifier(empty.msfs_gizmo_type)
    if gizmo_type is None:
        return None
    gizmo = msfs_gizmo.create_gizmo(gizmo_type)
    _place_next_to(empty, gizmo, depsgraph)
    collision_mod = msfs_gizmo.get_collision_mod(gizmo)
    if collision_mod is not None:
        msfs_gizmo.set_is_road_collider(collision_mod, empty.msfs_collision_is_road_collider)
    gizmo.name = empty.name + "_2024"
    return gizmo


def _add_light_counterpart(light_object, depsgraph):
    """Same mapping as Asobo's MSFS2024_SceneUtils.convert_lights_to_msfs2024, without replacing."""
    light_data = light_object.data
    new_light_object = msfs_lights.create_light_object(MSFS2024LightType.STREET_LIGHT)
    new_light = new_light_object.data
    new_light.type = light_data.type
    new_light.diffuse_factor = light_data.diffuse_factor
    new_light.specular_factor = light_data.specular_factor
    new_light.volume_factor = light_data.volume_factor
    if hasattr(light_data, "shadow_soft_size"):
        new_light.shadow_soft_size = light_data.shadow_soft_size

    props = new_light.msfs_light_properties
    props.msfs_light_color = light_data.color
    props.msfs_light_intensity = light_data.energy * 100
    for name in ("has_symmetry", "flash_frequency", "flash_duration", "flash_phase", "rotation_speed",
                 "day_night_cycle"):
        setattr(props, "msfs_light_" + name, getattr(light_object, "msfs_light_" + name))

    _place_next_to(light_object, new_light_object, depsgraph)
    new_light_object.name = light_object.name + "_2024"
    return new_light_object


class MSFS_FSS_OT_prepare_msfs2024(bpy.types.Operator):
    bl_idname = "msfs_fss.prepare_msfs2024"
    bl_label = "Prepare for MSFS 2024"
    bl_description = ("Add MSFS 2024 collision gizmos and lights next to the MSFS 2020 ones. Nothing is removed: "
                      "originals become MSFS 2020 only, the new objects MSFS 2024 only")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        scene = context.scene
        if scene is None:
            return False
        if not (msfs2020_target.is_msfs2020_target(scene) or msfs2020_target._has_msfs2020_data(scene)):
            return False
        return any(pending_counts(scene))

    def execute(self, context):
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        scene = context.scene
        depsgraph = context.evaluated_depsgraph_get()
        gizmos = [g for g in map(lambda e: _add_gizmo_counterpart(e, depsgraph), _legacy_gizmos(scene)) if g]
        lights = [_add_light_counterpart(obj, depsgraph) for obj in _legacy_lights(scene)]
        self.report({"INFO"}, f"Added {len(gizmos)} MSFS 2024 collision gizmo(s) and {len(lights)} light(s)")
        return {"FINISHED"}
