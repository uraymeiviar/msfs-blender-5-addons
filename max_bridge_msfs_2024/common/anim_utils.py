import bpy

from enum import Enum

from max_bridge_msfs_2024 import logger
from max_bridge_msfs_2024.common import ope_utils, obj_utils

logging = logger.getLogger()

SUPPORTED_ACTION_SLOTS: bool = bpy.app.version >= (4, 4, 0)

class TransformAttribs(Enum):
    LOCATION = "location"
    ROTATION = "rotation"
    SCALE = "scale"


def bake_objects_animation(objects: list[bpy.types.Object]):
    """
    Bake Animation and clear constraints.
    """
    logging.debug(f"Bake Animation.")
    context_override = ope_utils.get_context_override(objects, objects[0])

    with bpy.context.temp_override(**context_override):
        bpy.ops.nla.bake(
            only_selected=True,
            visual_keying=True,
            frame_start=0,
            frame_end=bpy.context.scene.frame_end,
            clear_constraints=True,
            clean_curves=False, # do not enable, too slow
            bake_types={"OBJECT"},
        )

def _has_keyframe(obj: bpy.types.Object, transform_attrib:str) -> bool:
    anim = obj.animation_data
    if anim is not None and anim.action is not None:
        for fcu in anim.action.fcurves:
            if fcu.data_path == transform_attrib:
                return len(fcu.keyframe_points) > 0
    return False


def is_animated(obj: bpy.types.Object) -> bool:
    for t in TransformAttribs:
        if _has_keyframe(obj, t.value):
            return True
    return False

def is_action_static(action: bpy.types.Action, epsilon=1e-4):
    """
    Returns True if the action has constant keyframes.
    """
    if not action.fcurves:
        return True

    start, end = action.frame_range

    for fcurve in action.fcurves:
        if fcurve.mute:
            continue

        keys = fcurve.keyframe_points

        if len(keys) <= 1:
            continue

        reference = fcurve.evaluate(start)


        for key in keys:
            value = fcurve.evaluate(key.co.x)
            if abs(value - reference) > epsilon:
                return False

    return True

def get_object_action(obj: bpy.types.Object) -> bpy.types.Action | None:
    """Get action assigned to the object's animation data, if any.
    """
    if not hasattr(obj, "animation_data"):
        return None
    anim_data = obj.animation_data

    if anim_data and anim_data.action:
        # get clean pointer to action in bpy.data
        return bpy.data.actions.get(anim_data.action.name, None)
    return None

if SUPPORTED_ACTION_SLOTS:
    def get_object_action_slot(obj: bpy.types.Object) -> bpy.types.ActionSlot | None:
        """
        Return active action slot.
        """
        if not hasattr(obj, "animation_data"):
            return None
        anim_data = obj.animation_data
        if anim_data:
            return anim_data.action_slot

        return None

if SUPPORTED_ACTION_SLOTS:

    def set_object_action(
        obj: bpy.types.Object, 
        action: bpy.types.Action, 
        slot: bpy.types.ActionSlot
    ):
        if obj.animation_data is None:
            obj.animation_data_create()

        obj.animation_data.action = action
        obj.animation_data.action_slot = slot


else:

    def set_object_action(obj: bpy.types.Object, action: bpy.types.Action):
        if obj.animation_data is None:
            obj.animation_data_create()

        obj.animation_data.action = action


def copy_animation(
    source_obj: bpy.types.Object,
    target_obj: bpy.types.Object
):

    source_action = get_object_action(source_obj)
    if not source_action:
        return


    if SUPPORTED_ACTION_SLOTS:
        slot = get_object_action_slot(source_obj)
        if slot:
            set_object_action(target_obj, source_action, slot)
    else:
        set_object_action(target_obj, source_action)


def clear_animation(obj: bpy.types.Object):
    obj.animation_data_clear()

def clear_objects_animation(objects: list[bpy.types.Object]):
    for obj in objects:
        clear_animation(obj)

def remove_and_store_children_animation(obj:bpy.types.Object, operations:dict[bpy.types.Object, bpy.types.Action|None] = {}):
    for child in obj.children:
        action = get_object_action(child)
        operations[child] = action
        clear_animation(child)
        remove_and_store_children_animation(child, operations)

    return operations


def restore_children_animation(
    operations: dict[bpy.types.Object, bpy.types.Action | None],
):
    for child, action in operations.items():
        if action:
            set_object_action(child, action)


def remove_object_action(obj: bpy.types.Object, remove_from_data: bool = True) -> bool:
    """
    Deletes the current action assigned to the object (not NLA strips).

    Args:
        obj: The object whose action to delete.
        remove_from_data: If True, removes the action from bpy.data if it's unused.

    Returns:
        True if action was deleted
    """

    anim_data = obj.animation_data
    if anim_data and anim_data.action:
        action = anim_data.action

        # Unlink the action from the object
        anim_data.action = None

        # Optionally remove the action from bpy.data if it's unused
        if remove_from_data and action.users == 0:
            bpy.data.actions.remove(action)

        return True

    return False


def extract_action_range(
    source_action: bpy.types.Action,
    frame_range: tuple[int, int],
    name: str | None = None,
    remap_to_zero: bool = False,
) -> bpy.types.Action:
    """
    Extracts a portion of an existing Blender action into a new action.

    Args:
        source_action : The action to split.
        frame_range : (start_frame, end_frame) inclusive for extraction.
        name : Optional. Name for the new action. If None, auto-generated.
        remap_to_zero : If True, shifts extracted keyframes so the start_frame maps to frame 0.

    Returns:
        Newly created action containing only the specified range.
    """
    start, end = frame_range
    name = name or f"{source_action.name}_extract_{start}_{end}"
    new_action = bpy.data.actions.new(name)
    
    for fcurve in source_action.fcurves:
        # Create identical FCurve in new action
        new_fcurve = new_action.fcurves.new(
            data_path=fcurve.data_path, index=fcurve.array_index
        )
        # Match keyframe property rna_path
        if fcurve.group:
            group = new_action.groups.get(fcurve.group.name, None)
            if not group:
                group = new_action.groups.new(fcurve.group.name)
            new_fcurve.group = group

        last_value = 0
        epsilon = 0.001
        for i, kp in enumerate(fcurve.keyframe_points[start : end + 1]):
            frame = kp.co.x
            value = kp.co.y
            # Dot not create keyframe if value is constant, except for first and last frames.
            if not (i == 0 or i == end) and abs(value - last_value) < epsilon:
                continue
            last_value = value
            new_frame = frame - start if remap_to_zero else frame
            new_kp = new_fcurve.keyframe_points.insert(
                frame=new_frame, value=value, options={"FAST"}
            )
            # Copy interpolation and ha ndle details
            new_kp.interpolation = kp.interpolation
            new_kp.easing = kp.easing
            new_kp.handle_left_type = kp.handle_left_type
            new_kp.handle_right_type = kp.handle_right_type
            new_kp.handle_left = kp.handle_left
            new_kp.handle_right = kp.handle_right

    return new_action


def add_nla_track_with_action(
    obj: bpy.types.Object, 
    action: bpy.types.Action, 
    track_name: str | None = None
) -> bpy.types.NlaTrack:
    """
    Adds a new NLA track to the object and assigns the given action to it.

    Args:
        obj : The object to add the NLA track to.
        action : The action to assign to the NLA track.
        track_name : Optional name for the NLA track.
        start_frame : The starting frame for the strip.

    Returns:
        bpy.types.NlaStrip: The newly created NLA strip.
    """
    if not isinstance(obj, bpy.types.Object):
        raise TypeError("obj must be a Blender Object")
    if not isinstance(action, bpy.types.Action):
        raise TypeError("action must be a Blender Action")

    if obj.animation_data is None:
        obj.animation_data_create()

    # Create a new track
    track = obj.animation_data.nla_tracks.new()
    track.name = track_name or f"{action.name}_track"

    # Create a strip with the action
    strip = track.strips.new(action.name, 0, action)
    strip.action_frame_start = action.frame_range[0]
    strip.action_frame_end = action.frame_range[1]

    return track


def filter_action_to_bones(action: bpy.types.Action, bone_names: str):
    """
    Modifies an action so it only affects the specified bones.

    Args:
        action: The action to filter.
        bone_names : The list of bone names to keep in the action.
    """
    if not isinstance(action, bpy.types.Action):
        raise TypeError("Expected a valid Action")

    if not bone_names:
        raise ValueError("bone_names list cannot be empty")

    fcurves_to_remove = []

    for fcurve in action.fcurves:
        # Bone-related data_path starts like 'pose.bones["BoneName"].location'
        path = fcurve.data_path
        if path.startswith('pose.bones["'):
            start = path.find('"') + 1
            end = path.find('"', start)
            bone_name = path[start:end]
            if bone_name not in bone_names:
                fcurves_to_remove.append(fcurve)

    for fc in fcurves_to_remove:
        action.fcurves.remove(fc)
