from typing import Generator, Iterable

import bpy


import mathutils

def set_lock_scale(obj: bpy.types.Object, state: bool):
    obj.lock_scale = [state, state, state]


def set_viewport_hidden(
    objects: Iterable[bpy.types.Object] | bpy.types.Object, state: bool
):
    if not hasattr(objects, "__iter__"):
        objects = list(objects)

    for obj in objects:

        if obj.hide_viewport != state: # set this value is slow, even it is already equal to state
            obj.hide_viewport = state


def set_parent_keep_transform(
    child: bpy.types.Object,
    parent: bpy.types.Object | None,

):
    """Set Parent and keep transform.
    Args:
        without_inverse: Clear matrix_parent_inverse.
    """
    if child == parent:
        return

    matrix_world  = child.matrix_world.copy()

    child.parent = parent
    if parent:
        child.matrix_parent_inverse = parent.matrix_world.copy().inverted()

    child.matrix_world = matrix_world


def reset_transform(
    obj: bpy.types.Object,
    reset_translation: bool = True,
    reset_rotation: bool = True,
    reset_scale: bool = True,
):
    matrix_world = obj.matrix_world.copy()
    trans, rot, scale = matrix_world.decompose()
    if reset_translation:
        trans = mathutils.Vector((0, 0, 0))
    if reset_rotation:
        rot = mathutils.Quaternion()
    if reset_scale:
        scale = mathutils.Vector((1, 1, 1))
    matrix_world = mathutils.Matrix.LocRotScale(trans, rot, scale)
    obj.matrix_world = matrix_world


def has_instancing(obj: bpy.types.Object):
    return getattr(obj, "instance_collection", None) or (
        getattr(obj, "instance_type", "NONE") != "NONE"
    )


def get_object_instances(
    obj: bpy.types.Object, 
    depsgraph: bpy.types.Depsgraph | None = None,
) -> Generator[bpy.types.Object, None, None]:
    """Yield instance spawned by provided object. Can be a collection instances,
    or object isntance on mesh vertices/faces instancing etc.

    All instances are provided even nested ones (collection instances in collection instances)
    # TODO support geometry node instances?

    WARNING: each yielded object is a temporary depsgraph reference, only
    valid until the generator resumes (i.e. the next loop iteration).
    Do NOT store it or convert this generator to a list — use each object
    immediately inside your `for` loop (read its data, transform, etc.)
    before moving to the next one.
    """
    if not has_instancing(obj):
        return

    if depsgraph is None:
        depsgraph = bpy.context.evaluated_depsgraph_get()
    obj_eval = obj.evaluated_get(depsgraph)
    for inst in depsgraph.object_instances:
        if (
            inst.is_instance
            and inst.object
            and inst.parent == obj_eval
        ):
            yield inst.object
