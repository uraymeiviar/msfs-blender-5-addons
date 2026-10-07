# Copyright 2023-2024 The glTF-Blender-IO-MSFS2024 authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from __future__ import annotations
from typing import TYPE_CHECKING
from dataclasses import dataclass

from copy import copy
from ...com import msfs_logs
import bpy

if bpy.app.version >= (4, 5, 0):
    from io_scene_gltf2.io.com import constants as gltf2_io_constants
    from io_scene_gltf2.io.exp import binary_data as gltf2_io_binary_data
    from io_scene_gltf2.blender.exp import accessors as gltf2_blender_gather_accessors
else:
    from io_scene_gltf2.io.com import gltf2_io_constants
    from io_scene_gltf2.io.exp import gltf2_io_binary_data
    from io_scene_gltf2.blender.exp import gltf2_blender_gather_accessors

from io_scene_gltf2.io.com import gltf2_io
from io_scene_gltf2_msfs_fss.blender.utils.msfs_material_utils import MSFS2024_MaterialProperties
from .material.asobo_material_uv_options import AsoboMaterialUVOptionsExtension
from .material.asobo_material_windshield import AsoboMaterialWindshieldExtension
from .material.asobo_material_dirt import AsoboMaterialDirtExtension
from .material.asobo_material_tire import AsoboMaterialTireExtension

if TYPE_CHECKING:
    ANIMATION_INFOS = tuple[str, str|None, tuple[str,...]]
    from io_scene_gltf2.io.com import gltf2_io
    if bpy.app.version > (4,5,0):
        from io_scene_gltf2.blender.exp import gltf2_blender_gather_tree as gltf2_tree
    else:
        from io_scene_gltf2.blender.exp import tree as gltf2_tree
# region Globals
MSFS2024_LOGGER : msfs_logs.Logger
EXTENSION_NAME = "ASOBO_property_animation"
SUPPORTED_ACTION_SLOTS: bool = bpy.app.version >= (4, 4, 0)

# Animatable material properties:
CHANNEL_TARGET_PATHS = {
    MSFS2024_MaterialProperties.BASECOLOR.attribute_name():
        "pbrMetallicRoughness/baseColorFactor",

    MSFS2024_MaterialProperties.EMISSIVECOLOR.attribute_name():
        "emissiveFactor",

    MSFS2024_MaterialProperties.METALLICSCALE.attribute_name():
        "pbrMetallicRoughness/metallicFactor",

    MSFS2024_MaterialProperties.ROUGHNESSSCALE.attribute_name():
        "pbrMetallicRoughness/roughnessFactor",

    MSFS2024_MaterialProperties.UVOFFSETU.attribute_name():
        f"extensions/{AsoboMaterialUVOptionsExtension.extension_name}/UVOffsetU",

    MSFS2024_MaterialProperties.UVOFFSETV.attribute_name():
        f"extensions/{AsoboMaterialUVOptionsExtension.extension_name}/UVOffsetV",

    MSFS2024_MaterialProperties.UVTILINGU.attribute_name():
        f"extensions/{AsoboMaterialUVOptionsExtension.extension_name}/UVTilingU",

    MSFS2024_MaterialProperties.UVTILINGV.attribute_name():
        f"extensions/{AsoboMaterialUVOptionsExtension.extension_name}/UVTilingV",

    MSFS2024_MaterialProperties.UVROTATION.attribute_name():
        f"extensions/{AsoboMaterialUVOptionsExtension.extension_name}/UVRotation",

    MSFS2024_MaterialProperties.WINDSHIELDWIPER1STATE.attribute_name():
        f"extensions/{AsoboMaterialWindshieldExtension.extension_name}/wiper1State",

    MSFS2024_MaterialProperties.WEARAMOUNT.attribute_name():
        f"extensions/{AsoboMaterialDirtExtension.extension_name}/dirtBlendAmount",

    MSFS2024_MaterialProperties.TIREMUDANIMSTATE.attribute_name():
        f"extensions/{AsoboMaterialTireExtension.extension_name}/tireMudAnimState",

    MSFS2024_MaterialProperties.TIREDUSTANIMSTATE.attribute_name():
        f"extensions/{AsoboMaterialTireExtension.extension_name}/tireDustAnimState",
}

export_cache: ExportCache | None = None

# endregion

# region Classes

class Keyframe:
    def __init__(
        self,
        frame: int = 0
    ):
        self.frame: int = frame
        self.value: list[float|int] = []

    @property
    def seconds(self):
        return self.frame / (bpy.context.scene.render.fps * bpy.context.scene.render.fps_base)

class AsoboChannel:
    def __init__(
        self,  
        target_property: str, 
        sampler : None | gltf2_io.AnimationSampler
    ):
        self.target_property = target_property
        self.sampler = sampler
        self.sampler_index = -1

class AsoboMaterialAnimation:
    def __init__(self, channels: list[AsoboChannel], material_name:str):
        self.channels = channels
        self.material_name = material_name

class MaterialAction():
    """
    Wrapper arround bpy.types.Action
    Associates an action with a unique action name that is action_name + used slot name on blender >= 4.4.
    """
    def __init__(self, action: bpy.types.Action, slot: bpy.types.ActionSlot|None = None):

        self.action = action
        self.slot = slot

    @property
    def unique_name(self)-> str:
        
        return _get_unique_action_name(self.action, self.slot)


@dataclass(frozen=True)
class AnimToKeep:
    name: str  # Corresponds to action or track name
    slot_identifier: str | None = None  # None if on version < 4.5
    channels: tuple[str] = tuple([])
    bone_name: str = ""


class ExportCache:
    def __init__(self, khronos_export_settings:dict):
        """
        Tracks material animations discovered during glTF exporter hook execution.

        Attributes
        ----------
        force_keep_anim_original_value : bool
            Original value of the export setting "gltf_optimize_animation_keep_object".

        export_nla : bool
            Current animation export mode (True when using NLA Tracks).

        disable_material_animation : bool
            When True, material animation gathering is disabled.

        treated_materials : set[str]
            Names of materials that have already been processed.

        new_gltf_anim_names : set[str]
            Names of newly discovered glTF animations containing material animations.
            Populated by gather_material_hook for the current object and cleared
            between objects.

        gltf_anim_names : set[str]
            Names of all glTF animations containing one or more material animations.

        sampled_material_anims : dict[str, AsoboMaterialAnimation]
            Mapping between a unique action-slot identifier and the corresponding
            AsoboMaterialAnimation.

        animations_to_force_keep : dict[str, set[AnimToKeep]]
            Keys are node uuid, value is a set of animation that must be
            preserved during export.

        object_gltf_anims : dict[bpy.types.Object, set[str]]
            Mapping between Blender objects and the set of glTF animations that contain
            material animations for each object.

        gltf_anim_material_animations : dict[str, list[AsoboMaterialAnimation]]
            Mapping between glTF animation names and their associated material animations.
        """

        self.force_keep_obj_anim_original_value: bool = khronos_export_settings.get("gltf_optimize_animation_keep_object", False)
        self.force_keep_bone_anim_original_value: bool = khronos_export_settings.get("gltf_optimize_animation_keep_armature", False)
        self.export_nla : bool = _is_export_nla_enabled(khronos_export_settings)
        self.disable_material_animation : bool = False
        self.treated_materials: set[str] = set()
        self.new_gltf_anim_names: set[str] = set()
        self.gltf_anim_names: set[str] = set()
        self.sampled_material_anims: dict[str, AsoboMaterialAnimation] = {}

        self.animations_to_force_keep: dict[str, set[AnimToKeep]] = {}

        self.object_gltf_anims: dict[bpy.types.Object, set[str]] = {}
        self.gltf_anim_material_animations: dict[str, list[AsoboMaterialAnimation]] = {}


# endregion

# region Public Functions
# These functions are called by gltf hooks


def gather_track_animated_channels(
    blender_object: bpy.types.Object,
    track: bpy.types.NlaTrack,
    scene_vexport_nodes: dict[
        bpy.types.Object | bpy.types.Bone, gltf2_tree.VExportNode
    ],
):
    """Gather track animated channel and add them to ExportCache.animations_to_force_keep 
    A channel is included when it has one keyframe.
    """

    vnode = scene_vexport_nodes.get(blender_object, None)
    if not vnode:
        return
    
    if not track.strips:
        return

    first_strip = track.strips[0]
    action = first_strip.action
    if not action:
        return
    
    slot = None
    if SUPPORTED_ACTION_SLOTS:
        slot = first_strip.action_slot

    obj_channels, bone_channels = _get_animated_gltf_channels(action, slot)
    if not (obj_channels or bone_channels):
        return

    uuid = vnode.uuid

    global export_cache
    obj_anims_to_force_keep = export_cache.animations_to_force_keep.get(uuid, None)
    if obj_anims_to_force_keep is None:
        obj_anims_to_force_keep = set()
        export_cache.animations_to_force_keep[uuid] = obj_anims_to_force_keep

    # obj anim
    slot_identifier = None
    if slot:
        slot_identifier = slot.identifier
    obj_anim_to_keep = AnimToKeep(track.name, slot_identifier, tuple(obj_channels))

    obj_anims_to_force_keep.add(obj_anim_to_keep)

    # bone anim
    for bone_name, channels in bone_channels.items():

        bone_anim_to_keep = AnimToKeep(
            track.name, slot_identifier, tuple(channels), bone_name
        )
        obj_anims_to_force_keep.add(bone_anim_to_keep)


def prepare_for_export(khronos_export_settings: dict):
    """First functions that must be launched before parsing for animated channels and material animation
    and using the functions below.
    """
    global export_cache
    export_cache = ExportCache(khronos_export_settings)

    global MSFS2024_LOGGER
    MSFS2024_LOGGER = msfs_logs.get_logger()

def gather_material_animations(
    material: bpy.types.Material,
    khronos_export_settings: dict,
) :
    """
    Must be called during gather_material_hook.
    Collects all AsoboMaterialAnimation instances and stores them in the cache.
    """
    if _disabled_material_animation() :
        return

    if material.name in export_cache.treated_materials:
        return

    anim_material_action = _get_anim_material_actions(material)

    if anim_material_action and not _valid_context():
        return

    for anim_name, material_action in anim_material_action.items():
        # An action can be used by multiple materials.
        # Check whether this action has already been processed to avoid unnecessary sampling.
        unique_name = material_action.unique_name
        mat_animation = export_cache.sampled_material_anims.get(unique_name, None)

        if mat_animation :
            # This action was already sampled for another material.
            # It can be reused; only the target material needs to be updated.
            mat_animation = copy(mat_animation)
            mat_animation.material_name = material.name
        else:
            mat_animation = _sample_material_action(
                material,
                material_action,
                khronos_export_settings=khronos_export_settings
            )
            if mat_animation:
                # Add to cache
                export_cache.sampled_material_anims[unique_name] = mat_animation

        if not mat_animation:
            continue

        if not export_cache.gltf_anim_material_animations.get(anim_name, None):
            export_cache.gltf_anim_material_animations[anim_name] = []

        export_cache.gltf_anim_material_animations[anim_name].append(mat_animation)

        if anim_name not in export_cache.gltf_anim_names:
            export_cache.gltf_anim_names.add(anim_name)
            export_cache.new_gltf_anim_names.add(anim_name) 

    export_cache.treated_materials.add(material.name)


def gather_node(
    blender_object: bpy.types.Object,
    scene_vexport_nodes: dict[
        bpy.types.Object | bpy.types.Bone, gltf2_tree.VExportNode
    ],
):
    if _disabled_material_animation():
        return
    vnode = scene_vexport_nodes.get(blender_object, None)
    if not vnode or not vnode.uuid:
        return
    
    _store_obj_material_animations(blender_object)
    _prepare_obj_for_animation_gather(blender_object, vnode.uuid)


# region Extension
def init_mat_anim_extensions(
    gltf2_animations: list[gltf2_io.Animation]
):
    """
    Insert material animation samplers into glTF animations.
    """
    if _disabled_material_animation() :
        return
    
    if not export_cache.gltf_anim_material_animations:
        return

    for gltf_animation in gltf2_animations:
        for gltf_anim_name, mat_anims in export_cache.gltf_anim_material_animations.items():
            if not gltf_anim_name == gltf_animation.name:
                continue
            for mat_anim in mat_anims:
                _insert_mat_anim_samplers_in_gltf2_anim(
                    gltf2_animation=gltf_animation,
                    material_animation=mat_anim
                )

def finalize_material_animations(
    gltf2_plan: gltf2_io.Gltf
):
    """
    Set up material animation channels in glTF animations.
    """
    if _disabled_material_animation() :
        return
    
    if not export_cache.gltf_anim_material_animations:
        return

    appended = False
    for gltf_animation in gltf2_plan.animations:

        for gltf_anim_name, mat_anims in export_cache.gltf_anim_material_animations.items():
            if not gltf_anim_name == gltf_animation.name:
                continue
            for mat_anim in mat_anims:
                _appended = _append_mat_anim_channels_in_extension(
                    gltf2_animation=gltf_animation,
                    material_animation=mat_anim,
                    gltf2_plan=gltf2_plan
                )

                if _appended:
                    appended = True
    
    if appended and EXTENSION_NAME not in gltf2_plan.extensions_used:
        gltf2_plan.extensions_used.append(EXTENSION_NAME)

    _clean_export_vars()
# endregion
# endregion

# region Private Functions
def _disabled_material_animation():
    return export_cache and export_cache.disable_material_animation
            
def _valid_context()->bool:
    
    if (bpy.app.version) < (3, 6, 0):
        MSFS2024_LOGGER.error(
            message = f"Material animations are not supported in Blender {bpy.app.version}.",
            details = "Material animations are supported in Blender 3.6 and later."
        )
        export_cache.disable_material_animation = True
        return False
    
    elif not export_cache.export_nla and (bpy.app.version) < (4, 5, 0):
        export_cache.disable_material_animation = True
        MSFS2024_LOGGER.error(
        message = "Material animations are not supported in 'Actions' mode",
        details = (
            "Material animations cannot be exported when the \n"
            "animation mode is set to 'Actions' in Blender versions earlier than 4.5.0.\n"
            "Please switch the animation mode to 'NLA Tracks' in export settings."
        )
        )
        return False
    return True

def _clean_export_vars():
    global export_cache
    export_cache = None

def _get_unique_action_name(action: bpy.types.Action, slot: None|bpy.types.ActionSlot):
    unique_name = action.name
    if slot:
        unique_name += slot.identifier
    return unique_name

def _action_is_empty(action: bpy.types.Action) -> bool:
    """For Blender versions earlier than 4.4, checks whether 
    the action has any keyframes.

    For Blender versions 4.4 and later, checks whether 
    each action slot has keyframes.

    Returns:
        True when empty.
    """
    if SUPPORTED_ACTION_SLOTS:
        if not action.layers:
            return True
        # For now action only support one layer
        # https://developer.blender.org/docs/features/animation/animation_system/layered/
        strips = action.layers[0].strips
        if not strips:
            return True

        strip: bpy.types.ActionStrip = strips[0]
        for slot in action.slots:
            channel_bag: bpy.types.ActionChannelbag = strip.channelbag(slot)
            if channel_bag and channel_bag.fcurves:
                return False

        return True
    else:
        return not any(fcurve.keyframe_points for fcurve in action.fcurves)


def _get_used_action(
    data: bpy.types.Material | bpy.types.NlaStrip,
) -> tuple[None | bpy.types.Action, None | bpy.types.ActionSlot]:
    """
    Get the used action and, for Blender 4.4 and later, also get the used action slot.
    """
    used_action = (None, None)
    if isinstance(data, bpy.types.NlaStrip):
        if not data.action:
            return used_action
        slot = None
        if SUPPORTED_ACTION_SLOTS:
            slot = data.action_slot
        used_action= (data.action, slot)

    else:
        if not data.animation_data or not data.animation_data.action:
            return used_action

        slot = None
        if SUPPORTED_ACTION_SLOTS and data.animation_data.action_slot:
            slot = data.animation_data.action_slot
        used_action= (data.animation_data.action, slot)

    return used_action


def _get_material_action(
    data:  bpy.types.Material | bpy.types.NlaStrip
) -> None | MaterialAction:

    action, slot = _get_used_action(data)
    if not action:
        return None
    if SUPPORTED_ACTION_SLOTS and not slot:
        return None
    
    return MaterialAction(action, slot)


def _get_anim_material_actions(material: bpy.types.Material) -> dict[str, MaterialAction]:
    """
    In NLA Tracks mode:
        Build a dictionary by parsing material NLA tracks and retrieving the
        action from the first enabled strip of each track.
        Tracks with duplicate names are ignored.

    In Actions mode:
        Retrieve the active action and the actions from the first enabled strip
        of each track.
        Strips using an action that has already been processed are ignored.

    A material may be referenced by multiple animations
    (e.g., material_A animated in "WIPER_R" and "WIPER_L").

    Empty actions are ignored.
        Returns:
        Key: final animation name.
        Value: associated action.
    """

    if not material.animation_data:
        return {}

    anim_material_actions : dict[str, MaterialAction] = {}
    export_nla = export_cache.export_nla

    # Get active material active action if in action export mode
    if not export_nla:
        action = material.animation_data.action
        if action and not _action_is_empty(action):
            material_action = _get_material_action(material)
            if material_action:
                anim_material_actions[action.name] = material_action
        
    
    # For each track, get action of the first enabled strip
    for track in material.animation_data.nla_tracks:
        if track.mute or track.strips is None:
            continue

        for strip in track.strips:
            if strip.mute:
                continue

            if not strip.action:
                continue
            
            if _action_is_empty(strip.action):
                continue

            material_action = _get_material_action(strip)
            if not material_action:
                continue

            anim_name = material_action.action.name
            if export_nla:
                anim_name = track.name

            if anim_material_actions.get(anim_name):
                if export_nla:
                    MSFS2024_LOGGER.warning(
                        message = f"Material '{material.name}': animation track '{anim_name}' is duplicated.",
                        details = f"Only the first occurrence of track '{anim_name}' will be exported."
                    )
                continue

            anim_material_actions[anim_name] = material_action
            break

    return anim_material_actions

def _store_obj_material_animations(blender_object:bpy.types.Object):
    """
    Collect gltf animations containing material animations from gather_material_hook
    and store them in the object_material_anims cache for the current object.
    """
    if export_cache.new_gltf_anim_names:
        export_cache.object_gltf_anims[blender_object] = export_cache.new_gltf_anim_names.copy()
    export_cache.new_gltf_anim_names = set()

def _get_placeholder_action(
    action_name: str,
) -> tuple[bpy.types.Action, None | bpy.types.ActionSlot]:
    """
    For Blender versions earlier than 4.4.0:
        Create a new action with the provided action_name and return it.
        A numbered suffix may be added to the action name if necessary.

    For Blender versions 4.4.0 and later:
        Use action slots. Assign an empty slot to the action.
        Use an existing empty slot if available; otherwise, create a new one.
    """

    action = None
    empty_slot = None

    if SUPPORTED_ACTION_SLOTS:
        # check if an action already exists

        action = bpy.data.actions.get(action_name)

    if not action:
        action = bpy.data.actions.new(name=action_name)

    if SUPPORTED_ACTION_SLOTS:
        # Find an empty slot, that we can assign or create new one
        # Slot must not have fcurves, so we are sure that it was not created by user
        channel_bag = None
        strip: bpy.types.ActionStrip | None = None

        
        # For now action only support one layer
        # https://developer.blender.org/docs/features/animation/animation_system/layered/
        try:
            strip = action.layers[0].strips[0]
        except (IndexError, AttributeError):
            pass

        if strip:
            for slot in action.slots:
                if not slot.target_id_type == "OBJECT":
                    continue
                channel_bag = strip.channelbag(slot)
                if channel_bag and channel_bag.fcurves:
                    continue
                empty_slot = slot
                break

        if not empty_slot:
            empty_slot = action.slots.new(id_type="OBJECT", name="placeholder")

  

    return (action, empty_slot)


def _add_new_NLA_track_with_action(
    blender_object: bpy.types.Object, 
    track_name:str, 
    action: bpy.types.Action,
    action_slot: None|bpy.types.ActionSlot
)->bpy.types.NlaTrack:

    track = blender_object.animation_data.nla_tracks.new()
    track.name = track_name
    track.mute = False
    strip = track.strips.new(
        name=action.name,
        start=bpy.context.scene.frame_start,
        action=action
    )
    if action_slot:
        strip.action_slot = action_slot
    return track

def _is_export_nla_enabled(khronos_export_settings: dict) -> bool:
    export_nla_animations = False
    if bpy.app.version < (3, 6, 0):
        animation_mode = khronos_export_settings.get("gltf_nla_strips", False)
        export_nla_animations = animation_mode is True
    else:
        animation_mode = khronos_export_settings.get("gltf_animation_mode", None)
        if animation_mode:
            export_nla_animations = animation_mode == "NLA_TRACKS"

    return export_nla_animations

def _prepare_obj_material_animation(
    obj: bpy.types.Object,
    uuid: str,
    anim_name: str
):  
    """
    Ensure that an action or track with the same material animation name exists on the object.
    This is necessary because material animations are appended to the exported object animation
    (see extension functions).

    Behavior:

    - If the object has no animation data:
        - NLA mode: assign a new track.
        - Actions mode: assign a new action on the object.

    - If the object has animation data:
        - NLA mode: check if a track with the same animation name exists. If not, add one.
        - Actions mode: check if the active action has the same animation name. 
        If not, add a track pointing to an action with the same animation name.

    The object’s animation is stored in the cache to ensure it is preserved during sampling
    (see `msfs_gather_sampled_object_channel` in `gltf_exporter_patches`).
    """
    export_nla = export_cache.export_nla
    track = None
    action = None
    slot = None

    if obj.animation_data is None:
        obj.animation_data_create()
        if export_nla:
            action, slot = _get_placeholder_action(anim_name)
            track = _add_new_NLA_track_with_action(obj, anim_name, action, slot)

        else:
            action, slot = _get_placeholder_action(anim_name)
            obj.animation_data.action = action

            if slot:
                obj.animation_data.action_slot = slot

    elif export_nla:
        # Check if a valid track with same name exists
        for _track in obj.animation_data.nla_tracks:

            if (not _track.mute
                and _track.name == anim_name
                and _track.strips
            ):
                first_strip = _track.strips[0]

                strip_action = first_strip.action
                if not strip_action:
                    continue
                action = strip_action
                if SUPPORTED_ACTION_SLOTS:
                    if not first_strip.action_slot:
                        continue
                    slot = first_strip.action_slot

                track = _track
                break

        if not track:
            action, slot = _get_placeholder_action(anim_name)
            track = _add_new_NLA_track_with_action(obj, anim_name, action, slot)

    else:# action mode
        active_action = obj.animation_data.action
        # If there is not active action, then we create one
        if not active_action:
            action, slot = _get_placeholder_action(anim_name)
            obj.animation_data.action = action

            if slot:
                obj.animation_data.action_slot = slot
        elif not active_action.name == anim_name:
            # if active_action is not valid then we add a new track with a valid action
            # be carrefull, exported anim name is action.name instead of track.name
            action, slot = _get_placeholder_action(anim_name)
            _add_new_NLA_track_with_action(obj, anim_name, action, slot)

    # Add to cache
    animation_name = action.name
    if track :
        animation_name = track.name
    action_slot_identifier = None
    if slot:
        action_slot_identifier = slot.identifier

    # Force keeping scale channel for this animation
    obj_anims_to_force_keep = export_cache.animations_to_force_keep.get(
        uuid, None
    )
    if obj_anims_to_force_keep is None:
        obj_anims_to_force_keep = set()
        export_cache.animations_to_force_keep[uuid] = obj_anims_to_force_keep

    obj_anims_to_force_keep.add(
        AnimToKeep(animation_name, action_slot_identifier, ("scale",))
    )


def _prepare_obj_for_animation_gather(
    blender_object: bpy.types.Object,
    uuid: str
):  
    if not blender_object in export_cache.object_gltf_anims:
        return

    # Make sure the blender object itself has animation data that can store material animation
    for gltf_anim_name in export_cache.object_gltf_anims[blender_object]:
        _prepare_obj_material_animation(
            blender_object,
            uuid,
            gltf_anim_name
        )

# region Sampling
def _get_action_fcurves(action: bpy.types.Action,
    slot: None | bpy.types.ActionSlot) -> bpy.types.ActionFCurves | None:
    if SUPPORTED_ACTION_SLOTS:
        if not action.layers:
            return None
        # For now action only support one layer
        # https://developer.blender.org/docs/features/animation/animation_system/layered/
        strips = action.layers[0].strips
        if not strips:
            return None

        strip: bpy.types.ActionStrip = strips[0]
        
        channel_bag: bpy.types.ActionChannelbag = strip.channelbag(slot)
        if channel_bag :
            return channel_bag.fcurves
        return None
    else:
        return action.fcurves

def _get_bone_name_from_data_path(fcurve_data_path: str)->None|str:
    if 'pose.bones["' in fcurve_data_path:
        return fcurve_data_path.split('pose.bones["')[1].split('"]')[0]
    return None

def _get_animated_gltf_channels(
    action: bpy.types.Action, 
    slot: None | bpy.types.ActionSlot
) -> tuple[set[str], dict[str,set[str]]]:
    
    """Get object and bone animated channels
    A channel is considered animatd when it contains at least one keyframe.
    So constant channels are also included.

    Returns:
        Tuple containing one set of obj channel names, and 
        one dict of bone channels (key is bone name, value is a set of channel names)
    """
    # dict to convert blender channel names to exported gltf channel names
    gltf_channels_map = {
        "rotation_quaternion": "rotation_quaternion",
        "rotation_euler": "rotation_quaternion",
        "delta_location": "location",
        "delta_scale": "scale",
        "delta_rotation_euler": "rotation_quaternion",
        "delta_rotation_quaternion": "rotation_quaternion",
    }

    obj_channels = set()
    bone_channels: dict[str,set[str]] = {}

    fcurves = _get_action_fcurves(action, slot)
    if not fcurves:
        return obj_channels, bone_channels
    
    for fcurve in fcurves:
        key_count = len(fcurve.keyframe_points)

        if not key_count >= 1:
            continue

        # Fcurve data path for an object has a simple format: "location","rotation_euler" etc
        channel_name = gltf_channels_map.get(fcurve.data_path, fcurve.data_path)

        # But for bones, Fcurve data path has parts: pose.bones["Bone"].rotation_quaternion
        bone_name = _get_bone_name_from_data_path(fcurve.data_path)
        if bone_name:
            data_path_parts = fcurve.data_path.split(".")
            # Format last part
            _suffix = data_path_parts[-1]
            suffix = gltf_channels_map.get(_suffix, _suffix)
            channels = bone_channels.get(bone_name, None)
            if not channels:
                channels = set()
                bone_channels[bone_name] = channels
            channels.add(suffix)
        else:
            obj_channels.add(channel_name)

    return obj_channels, bone_channels

def _warn_user_of_invalid_target(material_name: str, target_property: str):
    
    details = (f"'{target_property}' is not supported by\n"
                "material animation system and will not be exported.\n"
    )

    # Emissive animation logs to help user
    if (
        target_property== MSFS2024_MaterialProperties.EMISSIVESCALE.attribute_name()
        or target_property== MSFS2024_MaterialProperties.EMISSIVE_DAY_MULTIPLIER.attribute_name()
        or target_property== MSFS2024_MaterialProperties.EMISSIVE_NIGHT_MULTIPLIER.attribute_name()
        or target_property== MSFS2024_MaterialProperties.EMISSIVEBLENDFACTOR.attribute_name()
    ):

        details+=("To animate emissive, use the material"
                    f" '{MSFS2024_MaterialProperties.EMISSIVECOLOR.property_name()}' property instead.")

    _target_property = target_property
    enum_prop = MSFS2024_MaterialProperties.from_attribute_name(target_property)
    if enum_prop:
        _target_property = enum_prop.property_name() # UI Label
    global MSFS2024_LOGGER
    MSFS2024_LOGGER.warning(
        message=f"Material '{material_name}' : '{_target_property}' is not animatable.",
        details=details,
    )

def _sample_material_action(
    material: bpy.types.Material,
    mat_action: MaterialAction,
    khronos_export_settings: dict
) -> None|AsoboMaterialAnimation:

    target_property_fcurves = {}
    
    # Retrieve all fcurves for each animated material property
    fcurves = _get_action_fcurves(mat_action.action, mat_action.slot)
    if not fcurves:
        return None

    for fcurve in fcurves:
        
        if fcurve.mute:
            continue
        if len(fcurve.keyframe_points) == 0:
            continue

        target_property = fcurve.data_path
        valid_target_path = CHANNEL_TARGET_PATHS.get(target_property, None)
        if not valid_target_path:
            _warn_user_of_invalid_target(material.name, target_property)
            continue

        if target_property not in target_property_fcurves:
            target_property_fcurves[target_property] = []

        target_property_fcurves[target_property].append(fcurve)
    
    # Ensure all FCurves of a target property are unmuted if at least one is unmuted.
    # This prevents exporting invalid values (e.g. colors with missing R, G, B, or A components).
    for fcurve in fcurves:
        target_property = fcurve.data_path
        if fcurve.mute and target_property in target_property_fcurves.keys():
            fcurve.mute = False

    is_emissive_factor = (
        target_property == MSFS2024_MaterialProperties.EMISSIVECOLOR.attribute_name()
    )
    emissive_scale = material.msfs_emissive_scale

    # Create AsoboChannel for each target property
    channels = []
    for target_property, fcurves in target_property_fcurves.items():
        keyframes = _get_fcurves_keyframes(fcurves, khronos_export_settings)
        input_accessor, output_accessor = _construct_input_output_accessors(
            keyframes,
            khronos_export_settings,
            is_emissive_factor,
            emissive_scale
        )

        sampler = gltf2_io.AnimationSampler(
            extensions=None,
            extras=None,
            input=input_accessor,
            interpolation="LINEAR", # we'll keep linear for this ones
            output=output_accessor
        )
        channel = AsoboChannel(target_property, sampler)
        channels.append(channel)

    if not channels:
        return None

    animation = AsoboMaterialAnimation(
        channels = channels,
        material_name=material.name
    )

    return animation


def _get_fcurves_keyframes(
    fcurves: list[bpy.types.FCurve], 
    khronos_export_settings: dict
) -> list[Keyframe] :

    keyframes: list[Keyframe] = []
    frame_value: dict[int, list[float | int]] = {}

    crop_negative_frame = False
    use_gltf_frame_range = False
    if bpy.app.version >= (3, 6, 0):
        if khronos_export_settings['gltf_negative_frames'] == "CROP":
            crop_negative_frame = True
        if khronos_export_settings['gltf_frame_range'] is True:
            use_gltf_frame_range = True

    # parse fcurve and get each frame value
    for fcurve in fcurves:
        frames = set()
        for keyframe in fcurve.keyframe_points:
            frame = int(keyframe.co[0])
            if crop_negative_frame and frame < 0:
                continue
            if use_gltf_frame_range and frame < bpy.context.scene.frame_start or frame > bpy.context.scene.frame_end :
                continue

            frames.add(frame)

        if not frames:
            continue

        frames = sorted(frames)

        # Get channel value for each frame
        for frame in frames:
            value = fcurve.evaluate(frame)

            if frame not in frame_value:
                frame_value[frame] = []

            frame_value[frame].append(value)

    for frame, value in frame_value.items():
        key = Keyframe()
        key.frame = frame
        key.value = value
        keyframes.append(key)

    return keyframes

def _lerp(start, end, factor):
    return (1 - factor) * start + factor * end

def _construct_input_output_accessors(
    keyframes: list[Keyframe],
    export_settings: dict,
    is_emissive_factor: bool = False,
    emissive_scale: float = 1.0,
)->tuple[gltf2_io.Accessor, gltf2_io.Accessor]:
    
    # Construct input accessor first
    first_frame = keyframes[0].frame
    last_frame = keyframes[-1].frame
    frame_range = range(first_frame, last_frame + 1)

    frame_times = {}
    for keyframe in keyframes:
        frame_times[keyframe.frame] = keyframe.seconds
    
    # Get time for entire range of frames
    final_frame_times = []
    for frame in frame_range:
        if frame in frame_times:
            final_frame_times.append(frame_times[frame])
        else:
            # Interpolate between the two closest keyframes
            prev_time = max(k for k in frame_times if k <= frame)
            next_time = min(k for k in frame_times if k >= frame)

            if prev_time == next_time:
                final_frame_times.append(frame_times[prev_time])
            else:
                factor = (frame - prev_time) / (next_time - prev_time)
                interpolated_value = _lerp(frame_times[prev_time], frame_times[next_time], factor)
                final_frame_times.append(interpolated_value)

    min_time = keyframes[0].seconds 
    max_time = keyframes[-1].seconds

    # Unified add-on: built directly, as the output accessor below. Khronos' gather_accessor gained a `normalized`
    # parameter in Blender 5; the positional call raised a TypeError inside the hook, which the exporter swallows,
    # so material property animations were dropped silently
    input_accessor = gltf2_io.Accessor(
        buffer_view=gltf2_io_binary_data.BinaryData.from_list(
            final_frame_times,
            gltf2_io_constants.ComponentType.Float
        ),
        byte_offset=None,
        component_type=gltf2_io_constants.ComponentType.Float,
        count=len(final_frame_times),
        extensions=None,
        extras=None,
        max=[max_time],
        min=[min_time],
        name=None,
        normalized=None,
        sparse=None,
        type=gltf2_io_constants.DataType.Scalar
    )

    # Construct output accessor
    keyframe_values = {}
    for keyframe in keyframes:
        keyframe_value = keyframe.value
        # Special case for emissive, in gltf emissive is stored as result of
        # msfs_emissive_factor* msfs_emissive_scale
        if is_emissive_factor:
            keyframe_value = [emissive_scale * val for val in keyframe_value]

        keyframe_values[keyframe.frame] = keyframe_value

    # Get value for entire range of frame
    final_values = []
    for frame in frame_range:
        if frame in keyframe_values:
            final_values += keyframe_values[frame]
        else:
            # Interpolate between the two closest keyframes
            prev_time = max(k for k in keyframe_values if k <= frame)
            next_time = min(k for k in keyframe_values if k >= frame)

            if prev_time == next_time:
                final_values += keyframe_values[prev_time]
            else:
                factor = (frame - prev_time) / (next_time - prev_time)
                interpolated_values = [
                    _lerp(keyframe_values[prev_time][i], keyframe_values[next_time][i], factor)
                    for i in range(len(keyframe_values[prev_time]))
                ]
                final_values += interpolated_values

    # Store the keyframe data in a binary buffer
    component_type = gltf2_io_constants.ComponentType.Float
    data_type = gltf2_io_constants.DataType.vec_type_from_num(len(keyframes[0].value))

    output_accessor = gltf2_io.Accessor(
        buffer_view=gltf2_io_binary_data.BinaryData.from_list(final_values, component_type),
        byte_offset=None,
        component_type=component_type,
        count=len(final_values) // gltf2_io_constants.DataType.num_elements(data_type),
        extensions=None,
        extras=None,
        max=None,
        min=None,
        name=None,
        normalized=None,
        sparse=None,
        type=data_type
    )

    return input_accessor, output_accessor

# endregion

# region Extension
def _insert_mat_anim_samplers_in_gltf2_anim(
    gltf2_animation: gltf2_io.Animation,
    material_animation: AsoboMaterialAnimation
):  
    """
    Insert material animation samplers into glt2_animation samplers list.
    """

    sampler_index = len(gltf2_animation.samplers)

    if not gltf2_animation.extensions:
        gltf2_animation.extensions = {}

    if EXTENSION_NAME not in gltf2_animation.extensions.keys():
        gltf2_animation.extensions[EXTENSION_NAME] = {"channels": []}
  
    for material_channel in material_animation.channels:
        
        if material_channel.sampler not in gltf2_animation.samplers:
            gltf2_animation.samplers.insert(sampler_index, material_channel.sampler)
            material_channel.sampler_index = sampler_index
            sampler_index += 1


def _append_mat_anim_channels_in_extension(
    gltf2_animation: gltf2_io.Animation, 
    material_animation: AsoboMaterialAnimation,
    gltf2_plan: gltf2_io.Gltf
)->bool:
    """
    Append material animation channels into gltf2 animation.
    And set channels targets to the corresponding exported gltf material.

    Returns:
    True if one material animation channel was added into a gltf2 animation.
    """

    if not gltf2_animation.extensions or not gltf2_animation.extensions.get(EXTENSION_NAME):
        return False

    extension = gltf2_animation.extensions[EXTENSION_NAME]

    sucessfull = False
    for material_channel in material_animation.channels:
        channel = {}
        channel["sampler"] = material_channel.sampler_index
        

        # Create Targets
        material_index = None
        for j, material in enumerate(gltf2_plan.materials):
            if material.name == material_animation.material_name:
                material_index = j
                break

        if material_index is None:
            continue

        target_property = material_channel.target_property
        suffix = CHANNEL_TARGET_PATHS.get(target_property, None)
        if not suffix:
            continue

        # set channels targets to the corresponding exported gltf material.
        channel["target"] = f"materials/{material_index}/{suffix}"
        extension["channels"].append(channel)
        sucessfull = True

    return sucessfull
# endregion
# endregion
