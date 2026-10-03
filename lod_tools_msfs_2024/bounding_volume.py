from typing import  Iterable
from enum import Enum

import numpy as np

import bpy
import mathutils

from lod_tools_msfs_2024 import obj_utils


# region bsphere
class VolumeGetMode(Enum):
    BOUNDING_BOX = "BBOX"
    MESH = "MESH"


def _world_points(local_pts: np.ndarray, matrix_world: mathutils.Matrix) -> np.ndarray:
    """Convert vertices point from local space to world space.
    """
    mat = np.array(matrix_world, dtype=np.float64)  # (4,4)
    n = local_pts.shape[0]
    homogeneous = np.hstack([local_pts, np.ones((n, 1))])
    return (homogeneous @ mat.T)[:, :3]


def _mesh_points(obj: bpy.types.Object, depsgraph: bpy.types.Depsgraph) -> np.ndarray | None:
    """Get mesh world space vertices coordinates."""
    
    eval_obj = obj.evaluated_get(depsgraph) 
    try:
        mesh = eval_obj.to_mesh(preserve_all_data_layers=False, depsgraph=depsgraph)
    except:
        # No mesh data
        return None
    n = len(mesh.vertices)
    if n == 0:
        return None
    co = np.empty(n * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", co)
    return _world_points(co.reshape(n, 3), eval_obj.matrix_world)


def _bbox_points(obj: bpy.types.Object) -> np.ndarray:
    return _world_points(np.array(obj.bound_box, dtype=np.float64), obj.matrix_world)


def get_msfs_bounding_sphere(
    objects: Iterable[bpy.types.Object],
    mode: VolumeGetMode = VolumeGetMode.MESH,
    depsgraph: bpy.types.Depsgraph | None = None,
) -> tuple[mathutils.Vector | None, float | None]:
    """Return the bounding sphere center and radius for objects (in world coordinates).
    Support collection instances.

    Bounding Box mode doesnt work correctly if origin is far from mesh.
    """
    if not isinstance(objects, Iterable):
        objects = [objects]

    if depsgraph is None:
        depsgraph = bpy.context.evaluated_depsgraph_get()

    points_arrays = []

    collect_function = (
        _mesh_points if mode == VolumeGetMode.MESH else lambda objects, _ : _bbox_points(objects)
    )

    for obj in objects:
        pts = collect_function(obj, depsgraph)
        if pts is not None:
            points_arrays.append(pts)

        for _obj in obj_utils.get_object_instances(obj, depsgraph):

            pts = collect_function(_obj, depsgraph)
            if pts is not None:
                points_arrays.append(pts)

    if not points_arrays:
        return None, None

    all_points = np.concatenate(points_arrays, axis=0)
    mins = all_points.min(axis=0)
    maxs = all_points.max(axis=0)
    center = (mins + maxs) * 0.5
    radius = float(np.linalg.norm(maxs - mins) * 0.5)

    return mathutils.Vector(center), radius

def get_bounding_box(
    objects: Iterable[bpy.types.Object],
    mode: VolumeGetMode = VolumeGetMode.MESH,
    depsgraph: bpy.types.Depsgraph | None = None,
) -> tuple[mathutils.Vector | None, mathutils.Vector | None]:
    """Return the world-space axis-aligned bounding box for objects, as (center, extents).
    Support collection instances.

    Bounding Box mode doesnt work correctly if origin is far from mesh.

    """
    if not isinstance(objects, Iterable):
        objects = [objects]

    if depsgraph is None:
        depsgraph = bpy.context.evaluated_depsgraph_get()

    points_arrays = []

    collect_function = (
        _mesh_points if mode == VolumeGetMode.MESH else lambda objects, _: _bbox_points(objects)
    )

    for obj in objects:
        pts = collect_function(obj, depsgraph)
        if pts is not None:
            points_arrays.append(pts)

        for _obj in obj_utils.get_object_instances(obj, depsgraph):

            pts = collect_function(_obj, depsgraph)
            if pts is not None:
                points_arrays.append(pts)

    if not points_arrays:
        return None, None

    all_points = np.concatenate(points_arrays, axis=0)
    mins = all_points.min(axis=0)
    maxs = all_points.max(axis=0)
    center = (mins + maxs) * 0.5
    extents = (maxs - mins)

    return mathutils.Vector(center), mathutils.Vector(extents)

