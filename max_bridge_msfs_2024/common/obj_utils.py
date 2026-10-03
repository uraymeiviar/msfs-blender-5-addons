"""
Objects utilities
"""

import bpy

from mathutils import Vector, Matrix, Quaternion

from max_bridge_msfs_2024.common.usd_properties import *
from max_bridge_msfs_2024 import logger
from max_bridge_msfs_2024.common import ope_utils, anim_utils

logging = logger.getLogger()


def obj_is_valid(obj: bpy.types.bpy_struct) -> bool:
    try:
        obj.name
        return True
    except:
        return False

def get_evaluated_obj(obj: bpy.types.Object) -> bpy.types.Object:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    return obj.evaluated_get(depsgraph)

def force_frame_evaluation():
    """Force animations to affect objects transforms.
    This can be very slow.
    """
    bpy.context.scene.frame_set(bpy.context.scene.frame_current)

def duplicate_objects(objects: list[bpy.types.Object]) -> tuple[list[bpy.types.Object], list[bpy.types.Object]]:

    """
    Duplicate objects . Make sure list have same order by forcing selection.

    Args:
        objects: A list of objects to duplicate.

    Returns:
        Tuple containing list of original objects (order can changed after selecting),
        and a list of duplicated objects.
    """

    select_objects(objects)
    objects = bpy.context.selected_objects
    bpy.ops.object.duplicate()
    duplicated_objects = bpy.context.selected_objects

    return (objects, duplicated_objects)


def delete_objects(objects: bpy.types.Object | list[bpy.types.Object]):
    if type(objects) is not list:
        objects = [objects]
    for obj in objects:
        try:
            bpy.data.objects.remove(obj)
        except ReferenceError:
            pass

# region obj.data
def clear_all_constraints(
    objects: list[bpy.types.Object],
    keep_transform: bool = True,
):
    for obj in objects:
        
        if keep_transform:
            world_matrix = obj.matrix_world.copy()

        obj.constraints.clear()
        
        if keep_transform:
            obj.matrix_world = world_matrix

    bpy.context.view_layer.update()


def clear_all_modifiers(objects: list[bpy.types.Object]):
    logging.debug(f"Remove All Modifiers")
    for obj in objects:
        obj.modifiers.clear()


def clear_modifiers_except(
    objects: list[bpy.types.Object],
    whitelist: list[bpy.types.ID] = [bpy.types.ArmatureModifier],
):
    logging.debug(f"Remove All Modifiers")
    for obj in objects:
        for mod in obj.modifiers:
            if type(mod) in whitelist:
                continue
            obj.modifiers.remove(mod)

# endregion


# region Rename/Handle
def rename_unique_handle(obj: bpy.types.ID, handle: int) -> str:
    """
    We cant export custom attributes with usd in blender 3.6.
    So we rename nodes to __Handle__%handle%__Handle__ in order to be able to retrieve it in blender.
    Be carefull, Blender has a 64 character limit on nodes name .
    """
    obj.name = f"__Handle__{handle}__Handle__"
    return obj.name


def unique_rename_objects(objects: list[bpy.types.Object]) -> list[str]:
    """
    Rename Objects with unique handle names.

    Args:
        objects: Objects to rename.

    Returns:
        object_names: Original objects names.
    """
    object_names = []
    # Unique renaming of objects
    for handle, obj in enumerate(objects):
        original_name = obj.name
        rename_unique_handle(obj, handle)
        object_names.append(original_name)
    return object_names


def get_handle_from_name(name: str) -> int | None:
    """
    We cant export custom attributes with USD in blender 3.6.
    We retrieve nodes handle in their names __Handle__%handle%__Handle__ .
    This function works with scene objects and materials
    """

    name_parts = name.split("__Handle__")
    if len(name_parts) >= 2:
        return int(name_parts[1])
    else:
        return None


def get_obj_by_handle(objects: list[bpy.types.Object], handle: int) -> bpy.types.Object:
    for obj in objects:
        if not obj_is_valid(obj):
            continue  # deleted object
        if get_handle_from_name(obj.name) == handle:
            return obj


def get_obj_by_name(objects: list[bpy.types.Object], name: str) -> bpy.types.Object:
    for obj in objects:
        if not hasattr(obj, "name"):
            continue  # deleted object
        if obj.name == name:
            return obj
    return None


def get_obj_def(obj, definitions: list[SeriazableDef]) -> None | SeriazableDef:
    handle = get_handle_from_name(obj.name)
    obj_def = get_definition_by_handle(handle, definitions)
    return obj_def


def get_definition_by_handle(
    handle: int, definitions: list[SeriazableDef]
) -> None | SeriazableDef:
    definition = None
    for d in definitions:
        if not isinstance(d, SeriazableDef):
            continue
        if d.handle == handle:
            definition = d
    return definition


# endregion


# region Object types
def is_mesh(obj: bpy.types.Object) -> bool:
    return obj.type == "MESH"


def is_dummy(obj: bpy.types.Object) -> bool:
    return obj.type == "EMPTY"


def is_armature(obj: bpy.types.Object) -> bool:
    data = getattr(obj, "data", None)
    if not data:
        return False
    is_armature = type(data) == bpy.types.Armature
    return is_armature

def has_armature_mod(obj)->bool:
    data = getattr(obj, "data", None)
    if not data:
        return False
    for mod in obj.modifiers:
        if bpy.types.ArmatureModifier == type(mod):
            return True
    return False

def get_armatures(objects: list[bpy.types.Object]) -> list[bpy.types.Armature]:
    armatures_objects = []
    for obj in objects:
        if is_armature(obj):
            armatures_objects.append(obj)
    return armatures_objects


def get_basic_obj_type(obj: bpy.types.Object) -> BasicObjectTypes:
    if is_mesh(obj):
        return BasicObjectTypes.MESH
    elif is_dummy(obj):
        return BasicObjectTypes.DUMMY
    else:
        return BasicObjectTypes.NONE


def hair_curve_to_regular_curve(obj: bpy.types.Object) -> bpy.types.Object | None:
    """
    Converts hair curve objects created by usd importer to regulars curve object.
    Return new curve if successfull else None.
    """
    if bpy.app.version < (4, 2, 0):
        return None

    if not obj.type == "CURVES":
        return None
    
    # Make the hair curve object active
    select_objects(obj)

    # Convert the hair curve to a mesh
    bpy.ops.object.convert(target="MESH")

    # Convert the mesh to a curve
    bpy.ops.object.convert(target="CURVE")
    # Return the new curve object
    return bpy.context.view_layer.objects.active


# endregion


def copy_transform(
    source_obj: bpy.types.Object,
    target_obj: bpy.types.Object
):
    """
    Copy the transform (location, rotation, scale) of one object to another.
    """
    target_obj.matrix_world = source_obj.matrix_world.copy()

def get_delta_transform(
    obj: bpy.types.Object, 
    target_matrix_world: Matrix,
) -> tuple[Vector, Quaternion, Vector]:
    """Get delta transform of provided object in order to match provided
    matrix world

    Returns:
        Tuple containing delta_location, delta_rotation and delta scale
    """
    obj_matrix_world = obj.matrix_world.copy()

    delta_location = target_matrix_world.translation - obj_matrix_world.translation

    delta_matrix = target_matrix_world @ obj_matrix_world.inverted()

    delta_rotation = delta_matrix.to_quaternion()
    delta_scale = delta_matrix.to_scale()

    return (delta_location, delta_rotation, delta_scale)


def match_matrix_world_using_delta_transform(
    obj: bpy.types.Object,
    target_matrix_world: Matrix
):
    """
    Match obj's matrix_world to provided target_matrix_world
    using delta transform.
    """
    obj.delta_location = Vector((0,0,0))

    if obj.rotation_mode == 'QUATERNION':
        obj.delta_rotation_quaternion.identity()
    elif obj.rotation_mode == 'AXIS_ANGLE':
        raise Exception("Axis angle rotation mode not supported")
    else :
        obj.delta_rotation_euler.zero()
    obj.delta_scale = Vector((1,1,1))

    # Super important for matrices update
    bpy.context.view_layer.update()

    delta_location, delta_rotation, delta_scale = get_delta_transform(obj, target_matrix_world)
    # Apply delta transforms
    obj.delta_location =  delta_location

    if obj.rotation_mode == "QUATERNION":
        obj.delta_rotation_quaternion = delta_rotation
    else:
        # Euler (XYZ, ZYX, etc.)
        obj.delta_rotation_euler = delta_rotation.to_euler(obj.rotation_mode)

    obj.delta_scale = delta_scale
    bpy.context.view_layer.update()

def frame_eval_and_correct_objects(object_world_matrices: dict[bpy.types.Object, Matrix]):
    """Force a frame evaluation and correct position of animated 
    objects using delta transform.
    """
    force_frame_evaluation()
    for obj, matrix_world in object_world_matrices.items():
        match_matrix_world_using_delta_transform(obj, matrix_world)

def copy_origin_only(
    source_obj: bpy.types.Object,
    target_obj: bpy.types.Object
):
    """
    Copy origin and preserve mesh position.
    Only copy transforms if target object is not a mesh
    """


    # Store original world matrix (visual position)
    orig_world = target_obj.matrix_world.copy()

    # Copy full transform from source
    target_obj.matrix_world = source_obj.matrix_world.copy()

    if not target_obj.data or not isinstance(target_obj.data, bpy.types.Mesh):
        return

    # Compute the offset to restore original visuals
    offset = target_obj.matrix_world.inverted() @ orig_world

    # Apply to geometry if it has one
    if target_obj.data:
        target_obj.data.transform(offset)

def offset_object_along_local_axis(
    obj: bpy.types.Object,
    offset_vector: Vector,
    affect_children=False,
    depsgraph: None | bpy.types.Depsgraph = None,
):
    """
    Offsets the given object along its local axis without affecting its children.

    Parameters:
        obj (bpy.types.Object): The object to move.
        offset_vector (Vector): The offset vector in the object's local space.
    """
    # Save children relationships
    children = obj.children
    if not affect_children:
        for child in children:
            set_parent_keep_transform(child, None)

    if depsgraph is None:
        depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)
    # Calculate the offset in world space
    # Normalize the local matrix to remove scale effects
    local_matrix = eval_obj.matrix_world.to_3x3().normalized()
    world_offset = local_matrix @ offset_vector

    # Apply the offset
    obj.location += world_offset
    bpy.context.view_layer.update()

    # Reattach children
    if not affect_children:
        for child in children:
            set_parent_keep_transform(child, obj)


# endregion


# region Hierarchy
def clear_matrix_parent_inverse(obj: bpy.types.Object, keep_transform: bool = True):
    matrix_world = obj.matrix_world.copy()
    obj.matrix_parent_inverse.identity()
    if keep_transform:
        obj.matrix_world = matrix_world

def set_parent_keep_transform(
    child: bpy.types.Object,
    parent: bpy.types.Object | None,
    without_inverse: bool = True
):
    """Set Parent and keep transform.
    Args:
        without_inverse: Clear matrix_parent_inverse.
    """
    if child == parent:
        return
    
    if without_inverse:
        clear_matrix_parent_inverse(child)

    matrix_world  = child.matrix_world.copy()

    child.parent = parent

    if not without_inverse:
        child.matrix_parent_inverse = parent.matrix_world.copy().inverted()
    
    child.matrix_world = matrix_world

def set_parent_to_bone_keep_transform(
    obj: bpy.types.Object,
    armature: bpy.types.Object,
    bone_name: str,
    without_inverse: bool = True,
):
    """Set obj to be child of armature's bone."""
    if without_inverse:
        clear_matrix_parent_inverse(obj)
    original_matrix = obj.matrix_world.copy()

    pose_bone = armature.pose.bones.get(bone_name)

    obj.parent = armature
    obj.parent_type = "BONE"
    obj.parent_bone = pose_bone.name

    if not without_inverse:
        obj.matrix_parent_inverse = (
            armature.matrix_world @ pose_bone.matrix
        ).inverted()
    
    obj.matrix_world = original_matrix


def get_all_parents(obj: bpy.types.Object):
    """
    Returns a list of all parents for the given object, ordered from
    the closest parent to the top-level parent.

    Args:
        obj: The object whose parent hierarchy is to be retrieved.

    Returns:
        A list of parent objects, or an empty list if the object has no parent.
    """
    parents = []

    if not obj:
        print("Error: Object is None.")
        return parents

    current_parent = obj.parent
    while current_parent:
        parents.append(current_parent)
        current_parent = current_parent.parent  # Move up the hierarchy

    return parents


def get_parents_count(obj: bpy.types.Object):
    return len(get_all_parents(obj))

def replace_obj_by(
    obj_to_replace: bpy.types.Object,
    new_obj: bpy.types.Object,
    transform: bool = True,
    delete: bool = True
) -> bpy.types.Object:
    """Replace an object by another.
    Delete replaced object.

    Args:
        target_obj: Object to replace.
        new_obj: Replacing object.
        transform : Copy Transform of target object.
        origin_only: Copy origin while preserving visuals.
        animation : Copy animation.
        animation_keep_transform: Preserve new_obj original transforms after setting animation.
        delete : Delete target object after replace.
    Returns:
        New Object.
    """
    # Rename
    new_name = obj_to_replace.name

    # Copy Collections
    for collection in obj_to_replace.users_collection:
        try:
            collection.objects.link(new_obj)
        except RuntimeError:
            # already in collection
            pass
    
    # clear matrix parent inverse of the two objects
    # prevents invalid matrix world in some cases
    clear_matrix_parent_inverse(obj_to_replace)
    clear_matrix_parent_inverse(new_obj)

    # Unparent children of target and new obj before replace
    # We do this since new_obj can be children of obj_to_replace or vice versa.
    # And to prevent children to be affected by transform edits.
    obj_to_replace_children = []
    for child in obj_to_replace.children:
        if child.name != new_obj.name:
            obj_to_replace_children.append(child)
        set_parent_keep_transform(child, None)
    new_obj_children = []
    for child in new_obj.children: 
        if child.name != obj_to_replace.name:
            new_obj_children.append(child)
        set_parent_keep_transform(child, None)
    
    if obj_to_replace.parent_type == "OBJECT":
        # Copy parent
        set_parent_keep_transform(new_obj, obj_to_replace.parent)
    elif obj_to_replace.parent_type == "BONE":
        set_parent_to_bone_keep_transform(
            new_obj,
            obj_to_replace.parent,
            obj_to_replace.parent_bone.name,
        )

    if transform:
        copy_transform(obj_to_replace, new_obj)

    # Reassign children
    for child in obj_to_replace_children:
        set_parent_keep_transform(
            child, new_obj
        )
    for child in new_obj_children:
        set_parent_keep_transform(
            child, new_obj
        )

    obj_to_replace.user_remap(new_obj)
    # Remove the target object
    if delete:
        delete_objects(obj_to_replace)
    # Rename
    new_obj.name = new_name

    return new_obj


def replace_obj_by_dummy(obj: bpy.types.Object) -> bpy.types.Object:
    """Replace object by dummy.

    Delete object

    Args:
        obj: Object to replace.

    Returns:
        Created Dummy.
    """

    dummy = bpy.data.objects.new(name="Dummy", object_data=None)
    replace_obj_by(obj, dummy)

    return dummy


def instance_setup(
    source_obj: bpy.types.Object, target_obj: bpy.types.Object
) -> None | bpy.types.Object:
    """
    Set the target object to make it an instance of the source object.
    """
    if is_dummy(source_obj):
        # Skip since we can't instantiate dummy in blender
        # TODO : this was breaking rig in DA62 but we need to be able to instantiate msfs collision (have a duplicate at least)
        return None

    if source_obj is None or target_obj is None:
        print("Source or target object is None. Aborting.")
        return None

    if source_obj.type == target_obj.type:
        
        # Simple case, we can just transfer data

        if hasattr(source_obj, "material_slots"):
            # Check if materials are differents on each slot
            # In max, instances can have different materials
            # In blender, material slots are linked to object data by default
            # but we can switch materials slots to "OBJECT" mode to replicate max behaviour
            for i, target_mat_slot in enumerate(target_obj.material_slots):
                source_mat_slot = None

                try:
                    source_mat_slot = source_obj.material_slots[i]
                except:
                    pass

                if not source_mat_slot:
                    target_mat_slot.link = "OBJECT"
                    continue

                # If target slot material is different than source material then we switch link mode
                if not target_mat_slot.material == source_mat_slot.material:
                    material = target_mat_slot.material
                    target_mat_slot.link = "OBJECT"
                    # Transfer mat slot material from  "DATA" to "OBJECT" link mode
                    target_mat_slot.material = material

        target_obj.data = source_obj.data
        return target_obj
    
    else:
        
        source_copy = source_obj.copy()
        bpy.context.collection.objects.link(source_copy)

        if anim_utils.is_animated(target_obj):
            anim_utils.copy_animation(target_obj, source_copy)

        replace_obj_by(target_obj, source_copy)
     
        return source_copy


def has_only_empty_children(obj):
    """
    Returns True if the given object has no child
    or all of its descendants (children, grandchildren, etc.) are empties.
    """

    for child in obj.children:
        if child.type != 'EMPTY':
            return False
        if not has_only_empty_children(child):
            return False

    return True

# endregion


def unhide_all_nested_layers(layer_collection: bpy.types.LayerCollection):

    layer_collection.exclude = False 
    layer_collection.collection.hide_select = False
    layer_collection.hide_viewport = False
    layer_collection.collection.hide_viewport = False

    for obj in layer_collection.collection.objects:

        obj.hide_select = False
        obj.hide_set(False)
        obj.hide_viewport= False
    for child_layer in layer_collection.children:
        unhide_all_nested_layers(child_layer)

def select_all_scene(scene: bpy.types.Scene, view_layer: bpy.types.ViewLayer):
    objects = list(scene.collection.all_objects)
    unhide_all_nested_layers(view_layer.layer_collection)
    select_objects(objects)

def select_objects(objects: list[bpy.types.Object] | bpy.types.Object, clear_selection: bool = True):

    try:
        iter(objects)
    except TypeError:
        objects = [objects]

    view_layer = bpy.context.view_layer
    if clear_selection:
        # Deselect all objects first
        for obj in view_layer.objects:
            try:
                obj.select_set(False, view_layer=view_layer)
            except (RuntimeError, AttributeError):
                continue

    # Iterate over the list of objects and select each one
    for obj in objects:
        if obj and obj.name in view_layer.objects:  # Ensure the object exists in the current scene
            try:
                obj.select_set(True, view_layer=view_layer)
            except (RuntimeError, AttributeError):
                continue

    # Set the active object to the last object in the list (if it exists)
    first_object = None
    for obj in objects:
        if obj.name in view_layer.objects:
            first_object = obj
            break

    view_layer.objects.active = first_object


def has_nested_attr(obj: Any, attr: str) -> bool:
    """
    Check if obj has attribute. Works with nested attribute
    example : obj.my_attr_.nested_attrib
    """
    parts = attr.split(".")
    for part in parts:
        if hasattr(obj, part):
            obj = getattr(obj, part)
        else:
            return False

    return True


def get_nested_attr_value(obj: Any, attr: str) -> Any:
    """
    Check if obj has attribute. Works with nested attribute
    example : obj.my_attr_.nested_attrib
    """
    parts = attr.split(".")
    value = obj
    for part in parts:
        value = getattr(value, part)

    return value
