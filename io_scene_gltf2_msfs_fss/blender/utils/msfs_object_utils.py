"""
Utilities to manipulate bpy.types.Object
"""
import bpy
from typing import Iterable
from mathutils import Vector, Matrix, Quaternion


def get_parent_bone(
    obj: bpy.types.Object, pose_bone: bool = False
) -> None | bpy.types.Bone | bpy.types.PoseBone:
    """Return parent bone."""
    if not obj.parent:
        return None

    if not obj.parent_type in ("BONE", "BONE_RELATIVE"):
        return None

    parent_bone_name = obj.parent_bone
    if not parent_bone_name:
        return None
    armature_obj = obj.parent
    if not armature_obj:
        return None
    if pose_bone:
        return armature_obj.pose.bones.get(parent_bone_name, None)
    return armature_obj.data.bones.get(parent_bone_name, None)


def replace_obj_by(
    obj_to_replace: bpy.types.Object,
    new_obj: bpy.types.Object,
    transform: bool = True,
    delete: bool = True,
    depsgraph: bpy.types.Depsgraph | None = None,
) -> bpy.types.Object:
    """Replace an object by another.
    Delete replaced object.

    Args:
        obj_to_replace: Object to replace.
        new_obj: Replacing object.
        transform : Copy Transform of target object.
        delete : Delete target object after replace.
        depsgraph: Used to retrieve evaluated objects. If this function is
        called repeatedly, pass an existing dependency graph to avoid the
        overhead of calling bpy.context.evaluated_depsgraph_get() each time.
    Returns:
        New Object.
    """
    if depsgraph is None:
        depsgraph = bpy.context.evaluated_depsgraph_get()
    # rename
    new_name = obj_to_replace.name
    # Copy Collections
    for collection in obj_to_replace.users_collection:
        try:
            collection.objects.link(new_obj)
        except RuntimeError:
            # already in collection
            pass

    # Unparent children before replace
    new_obj_children = []
    for child in new_obj.children:  # safely get children list in case new_obj is children of target_obj
        new_obj_children.append(child)
        set_parent_keep_transform(child, None, depsgraph)

    if transform:
        copy_transform(obj_to_replace, new_obj, depsgraph)

    set_parent_keep_transform(new_obj, obj_to_replace.parent, depsgraph)

    # Reassign children
    if obj_to_replace.children:
        new_obj_children.extend(obj_to_replace.children)

    for child in new_obj_children :
        set_parent_keep_transform(child, new_obj, depsgraph)

    obj_to_replace.user_remap(new_obj)

    # Remove the target object
    if delete:
        delete_objects(obj_to_replace)
    # Rename
    new_obj.name = new_name

    return new_obj


def set_parent_keep_transform(
    child: bpy.types.Object,
    parent: bpy.types.Object | None,
    depsgraph: bpy.types.Depsgraph | None = None,
):
    """
    Set Parent and keep transform.
    Args:
        depsgraph: Used to retrieve evaluated objects. If this function is
            called repeatedly, pass an existing dependency graph to avoid the
            overhead of calling bpy.context.evaluated_depsgraph_get() each time.
    """
    if child == parent:
        return

    if depsgraph is None:
        depsgraph = bpy.context.evaluated_depsgraph_get()

    eval_child = child.evaluated_get(depsgraph)
    world_matrix  = eval_child.matrix_world.copy()

    child.parent = parent

    if parent:
        eval_parent = parent.evaluated_get(depsgraph)
        child.matrix_parent_inverse = eval_parent.matrix_world.copy().inverted()

    else:
        child.matrix_parent_inverse.identity()

    child.matrix_world = world_matrix


def copy_transform(
    source_obj: bpy.types.Object,
    target_obj: bpy.types.Object,
    depsgraph: None | bpy.types.Depsgraph = None,
):
    """
    Copy the transform (location, rotation, scale) of one object to another.

    Args:
        source_name: The name of the source object (the object with the desired transform).
        target_name: The name of the target object (the object to apply the transform to).
        depsgraph: Used to retrieve evaluated objects. If this function is
            called repeatedly, pass an existing dependency graph to avoid the
            overhead of calling bpy.context.evaluated_depsgraph_get() each time.
    """
    if depsgraph is None:
        depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_source_obj = source_obj.evaluated_get(depsgraph)

    target_obj.matrix_world = eval_source_obj.matrix_world.copy()


def delete_objects(objects: bpy.types.Object | Iterable[bpy.types.Object]):
    try:
        # Check if objects is iterable
        iter(objects)
    except TypeError:
        objects = [objects]

    for obj in objects:
        bpy.data.objects.remove(obj)

def _deselect_all_objects_in_scene():
    for obj in bpy.context.scene.objects:
        obj.select_set(False)


def realize_instance_and_reparent(
    empty_obj: bpy.types.Object,
    depsgraph: None | bpy.types.Depsgraph = None,
) -> list[bpy.types.Object]:
    """Convert Empty that instantiates a collection to regular objects.
    Reparent objects to empty's parent.

    Args:
        empty_obj: Empty with collection instance.
        depsgraph: Used to retrieve evaluated objects. If this function is
            called repeatedly, pass an existing dependency graph to avoid the
            overhead of calling bpy.context.evaluated_depsgraph_get() each time.
    Returns:
        New realized objects
    """

    if empty_obj.type != 'EMPTY' or empty_obj.instance_type != 'COLLECTION':
        return []

    empty_parent = empty_obj.parent

    _deselect_all_objects_in_scene()

    empty_obj.select_set(True)
    bpy.context.view_layer.objects.active = empty_obj

    bpy.ops.object.duplicates_make_real(use_base_parent=True, use_hierarchy=True)
    empty_obj.select_set(False)

    # Get all objects that are now parented to the instance
    realized_objects = bpy.context.selected_objects

    if depsgraph is None:
        depsgraph = bpy.context.evaluated_depsgraph_get()
    # Reparent to the original parent of the instance
    for obj in realized_objects:
        if obj.parent == empty_obj:
            set_parent_keep_transform(obj, empty_parent, depsgraph)

    _deselect_all_objects_in_scene()

    return realized_objects
