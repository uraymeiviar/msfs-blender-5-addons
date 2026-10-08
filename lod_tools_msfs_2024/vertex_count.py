"""
Computes the exported vertex count by combining mesh attributes in the
same way as the glTF exporter.

"""
from typing import Iterator

import bpy, bmesh
import numpy as np
import numpy.typing as npt

from lod_tools_msfs_2024 import obj_utils
from lod_tools_msfs_2024.constants import IS_BLENDER_4_2_OR_SUP

from io_scene_gltf2_msfs_fss.blender.utils import msfs_constants

MESH_ACTIVE_UV_NAME = "___merged_active_uv___"
MESH_ACTIVE_COLOR_NAME = "___merged_active_color___"

def _get_loop_vertex_indices(mesh: bpy.types.Mesh) -> npt.NDArray[np.uint32]:
    loop_vertex_indices = np.empty(len(mesh.loops), dtype=np.uint32)
    mesh.loops.foreach_get("vertex_index", loop_vertex_indices)
    return loop_vertex_indices


# region Position

def _get_loop_positions(
    mesh: bpy.types.Mesh, loop_vertex_indices: npt.NDArray[np.uint32] | None = None
) -> npt.NDArray[np.float32] | None:
    """Get vertex positions for each mesh loop (face corner).

    You can provide a precomputed loop-to-vertex mapping. Providing this array avoids
    allocating and populating a new loop vertex index array on each call.
    """
    
    positions = mesh.attributes.get("position", None)
    if not positions:
        return None
    locs = np.empty((len(mesh.vertices), 3), dtype=np.float32)
    positions.data.foreach_get("vector", np.ravel(locs))

    if loop_vertex_indices is None:
        loop_vertex_indices = _get_loop_vertex_indices(mesh)
    return locs[loop_vertex_indices]
# endregion

# region Normals

# Rounding digit used for normal/tangent rounding
ROUNDING_DIGIT = 4  # from builtin gltf exporter


def _normalize_vecs(vectors):
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    np.divide(vectors, norms, out=vectors, where=norms != 0)

def quantize_snorm(array: npt.NDArray[np.float16])-> npt.NDArray[np.int8]:
    _array = np.round(
        np.clip(array, -1.0, 1.0) * 127.0
    ).astype(np.int8)
    return _array

def _get_loop_normals(mesh: bpy.types.Mesh) -> npt.NDArray[np.float32] | None:
    """Get normal for each mesh loop (face corner).
    Quantization to 8bit uint in optimised gltf.
    """
    # Update split normals cache
    if not IS_BLENDER_4_2_OR_SUP:
        mesh.calc_normals_split()
    normals = np.empty((len(mesh.loops), 3), dtype=np.float32)
    mesh.corner_normals.foreach_get("vector", np.ravel(normals))

    # blender gltf rounding
    normals = np.round(normals, ROUNDING_DIGIT)

    # Force normalization of normals in case some normals are not (why ?)
    _normalize_vecs(normals)
    # Replace zero normals with the unit UP vector.
    # Seems to happen sometimes with degenerate tris?
    is_zero = ~normals.any(axis=1)
    normals[is_zero, 2] = 1

    # Quantize to int8 SNORM
    # normals = quantize_snorm(normals)

    return normals

def _get_loop_tangents(trimesh: bpy.types.Mesh) -> npt.NDArray[np.float32] | None:
    """Get normal for each mesh loop (face corner)."""
    if not (trimesh.uv_layers.active and len(trimesh.uv_layers) > 0):
        return None
    try:
        if trimesh.uv_layers.get(MESH_ACTIVE_UV_NAME, None):
            trimesh.calc_tangents(uvmap=MESH_ACTIVE_UV_NAME)
        else:
            active_render_uv_name = ""
            for uv_layer in trimesh.uv_layers:
                if uv_layer.active_render:
                    active_render_uv_name = uv_layer.name
                    break
            trimesh.calc_tangents(uvmap=active_render_uv_name)
    except:

        return None

    _tangents = np.empty((len(trimesh.loops), 3), dtype=np.float32)
    trimesh.loops.foreach_get("tangent", np.ravel(_tangents))
    _tangents = np.round(_tangents, ROUNDING_DIGIT)

    signs = np.empty((len(trimesh.loops),1), dtype=np.float32)
    trimesh.loops.foreach_get('bitangent_sign', np.ravel(signs))
    tangents = np.concatenate([_tangents, signs], axis=1)

    # Quantize to int8 SNORM
    # tangents = quantize_snorm(tangents)

    return tangents

# endregion


# region UVs
def _get_loop_tex_coords(
    mesh: bpy.types.Mesh, uv_index: int
) -> npt.NDArray[np.float32] | None:
    try:
        layer = mesh.uv_layers[uv_index]
    except IndexError:
        return None
    uvs = np.empty((len(mesh.loops), 2), dtype=np.float32)
    layer.uv.foreach_get("vector", np.ravel(uvs))

    return uvs


def _get_tex_coords(mesh: bpy.types.Mesh) -> list[npt.NDArray[np.float32]]:
    """Get first two uv channels. MSFS2024 shaders only use the two uv channels."""
    tex_coords = []
    uv_layers = mesh.uv_layers
    if not uv_layers:
        return tex_coords

    active_render_index = None
    for i, layer in enumerate(uv_layers):
        if layer.active_render:
            active_render_index = i

    if active_render_index is None:
        return tex_coords
    UV0 = _get_loop_tex_coords(mesh, active_render_index)
    tex_coords.append(UV0)
    if not len(mesh.uv_layers) > 1:
        return tex_coords
    # find uv2
    uv2_index = uv_layers.find(msfs_constants.DefaultUV.UV2_NAME)

    if uv2_index == -1:
        # get first uv channel that is not active render layer
        for i, layer in enumerate(uv_layers):
            if layer.active_render:
                continue
            uv2_index = i
            break
    if uv2_index != -1:
        UV2 = _get_loop_tex_coords(mesh, uv2_index)
        tex_coords.append(UV2)

    return tex_coords


# endregion


# region Vertex Color
def _get_loop_colors(
    mesh: bpy.types.Mesh,
    name: str,
    loop_vertex_indices: npt.NDArray[np.uint32] | None = None,
) -> npt.NDArray[np.float32] | None:
    """Get color for each loops (face corner).

    You can provide a precomputed loop-to-vertex mapping. Providing this array avoids
    allocating and populating a new loop vertex index array on each call.
    """
    attr = mesh.color_attributes.get(name, None)
    if not attr:
        return None

    if attr.domain == "POINT":
        loop_colors = np.empty((len(mesh.vertices), 4), dtype=np.float32)
    elif attr.domain == "CORNER":
        loop_colors = np.empty((len(mesh.loops), 4), dtype=np.float32)

    attr.data.foreach_get("color", np.ravel(loop_colors))

    if attr.domain == "POINT":
        if loop_vertex_indices is None:
            loop_vertex_indices = _get_loop_vertex_indices(mesh)
        loop_colors = loop_colors[loop_vertex_indices]

    return loop_colors

def _get_active_loop_colors(
    mesh: bpy.types.Mesh,
    loop_vertex_indices: npt.NDArray[np.uint32] | None = None,
) -> list[npt.NDArray[np.float32]]:

    colors = []
    if not mesh.color_attributes:
        return colors
    render_color_index = mesh.color_attributes.render_color_index
    color_attrib = mesh.color_attributes[render_color_index]
    color = _get_loop_colors(mesh, color_attrib.name, loop_vertex_indices)
    if color is not None:
        colors.append(color)

    return colors

def _get_all_loop_colors(
    mesh: bpy.types.Mesh,
    loop_vertex_indices: npt.NDArray[np.uint32] | None = None,
) -> list[npt.NDArray[np.float32]]:

    colors = []
    for attr in mesh.color_attributes:
        color = _get_loop_colors(mesh, attr.name, loop_vertex_indices)
        if color is None:
            continue
        colors.append(color)

    return colors


# endregion

def _primitive_split(
    mesh: bpy.types.Mesh,
    use_materials: bool = True,
    
) -> dict[int, npt.NDArray[np.uint16]] | None:
    """Split mesh into primitives.
    Code from builtin gltf exporter.
    """
    # Calculate triangles and sort them into primitives.
    try:
        mesh.calc_loop_triangles()
        loop_indices = np.empty(len(mesh.loop_triangles) * 3, dtype=np.uint32)
        # Indices of mesh loops that make up the triangle
        mesh.loop_triangles.foreach_get("loops", loop_indices)

    except:
        # For some not valid meshes, we can't get loops without errors
        # We already displayed a Warning message after validate() check, so here
        # we can return without a new one
        return None
    prim_indices = {}
    if not use_materials:  # Only for None. For placeholder and export, keep primitives
        # Put all vertices into one primitive
        prim_indices[-1] = loop_indices
    else:
        # Bucket by material index.
        tri_material_idxs = np.empty(len(mesh.loop_triangles), dtype=np.uint16)
        mesh.loop_triangles.foreach_get("material_index", tri_material_idxs)
        loop_material_idxs = np.repeat(
            tri_material_idxs, 3
        )  # material index for every loop
        unique_material_idxs = np.unique(tri_material_idxs)
        del tri_material_idxs

        for mat_i in unique_material_idxs:
            prim_indices[mat_i] = loop_indices[
                loop_material_idxs == mat_i
            ]
    return prim_indices


def _count_unique_rows(dots: np.ndarray) -> int:
    dots = np.ascontiguousarray(dots)
    row_view = dots.view(np.dtype((np.void, dots.dtype.itemsize * dots.shape[1])))
    return len(np.unique(row_view))


def get_gltf_vertex_count(
    mesh: bpy.types.Mesh,
) -> int:

    # Mesh must be triangulated for safe tangent compute
    # or mesh.calc_tangents can trigger
    # RuntimeError: Error: Tangent space can only be computed for tris/quads, aborting
    primitives = _primitive_split(mesh)
    if not primitives:
        return 0
    loop_vertex_indices = _get_loop_vertex_indices(mesh)
    loop_positions = _get_loop_positions(mesh, loop_vertex_indices)
    loop_normals = _get_loop_normals(mesh)
    # loop_tangents = _get_loop_tangents(trimesh)
    tex_coords = _get_tex_coords(mesh)
    vertex_colors = _get_active_loop_colors(mesh, loop_vertex_indices)

    all_attribs = [loop_positions, loop_normals, *tex_coords, *vertex_colors]
    full_dots = np.concatenate(
        all_attribs, axis=1, casting="safe"
    )  # cast uint to float

    count = 0
    for _, loop_indices in primitives.items():
        count += _count_unique_rows(full_dots[loop_indices])
    return count


def triangulate_mesh(mesh : bpy.types.Mesh):
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.triangulate(
            bm,
            faces=bm.faces,
            quad_method="FIXED",
            ngon_method="EAR_CLIP"
        )
    bm.to_mesh(mesh)
    bm.free()

def prepare_uv_for_tangent_compute(mesh: bpy.types.Mesh):
    for uv_layer in mesh.uv_layers:
        # Make sure that active render uv have the same name for correct merging
        # It is also important for tangent computation (cf _get_tangent)
        if uv_layer.active_render:
            uv_layer.name = MESH_ACTIVE_UV_NAME
            break

def prepare_mesh_for_tangent_compute(mesh: bpy.types.Mesh):
    prepare_uv_for_tangent_compute(mesh)
    triangulate_mesh(mesh)

def get_obj_vcount(obj: bpy.types.Object, depsgraph: bpy.types.Depsgraph, apply_modifiers: bool = True,) -> int:
    vcount = 0
    if apply_modifiers:
        _obj = obj.evaluated_get(depsgraph)
    else:
        _obj = obj
    mesh = None
    try:
        mesh = _obj.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
    except RuntimeError:
        # No Mesh data
        _obj.to_mesh_clear()
    if mesh:
        # prepare_mesh_for_tangent_compute(mesh)
        vcount += get_gltf_vertex_count(mesh)
    _obj.to_mesh_clear()

    instances = obj_utils.get_object_instances(_obj, depsgraph)
    for inst in instances:
        mesh = None
        try:
            mesh = inst.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
        except RuntimeError:
            # No Mesh data
            inst.to_mesh_clear()
            continue
        if mesh:
            # prepare_mesh_for_tangent_compute(mesh)
            vcount += get_gltf_vertex_count(mesh)
        inst.to_mesh_clear()
    return vcount


def get_gltf_objects_vertex_count(
    objects: Iterator[bpy.types.Object],
    apply_modifiers: bool = True,
    depsgraph: bpy.types.Depsgraph | None = None,
) -> int:
    """
    Calculate vertex count by reproducing gltf export steps defined in primitive_extract.py
    module.
    """
    if depsgraph is None:
        depsgraph = bpy.context.evaluated_depsgraph_get()

    # trimesh = get_merged_trimesh_of_objects(objects, depsgraph)
    # vcount = get_gltf_vertex_count(trimesh)
    # bpy.data.meshes.remove(trimesh)

    vcount = 0
    linked_data_vcount: dict[bpy.types.ID, int] = {}
    for obj in objects:
        obj_data = getattr(obj, "data", None)
        if obj_data and obj_data in linked_data_vcount.keys():
            continue
        vcount += get_obj_vcount(obj, depsgraph, apply_modifiers)

        if not apply_modifiers and obj_data:
            linked_data_vcount[obj_data] = vcount

        elif apply_modifiers and obj_data and not obj.modifiers:
            # Reuse vcount only if obj has no modifiers
            linked_data_vcount[obj_data] = vcount
    return vcount

def get_merged_trimesh_of_objects(
    objects: Iterator[bpy.types.Object],
    depsgraph: bpy.types.Depsgraph,
    include_instances: bool = True
) -> bpy.types.Mesh:
    """
    Create one merged triangulated mesh. 
    Can include objects instances (collection instances, face/vert instances).
    """
    bm = bmesh.new()
    for obj in objects:
        obj_eval = obj.evaluated_get(depsgraph)

        instance_mesh = None
        if include_instances:
            instances = obj_utils.get_object_instances(obj_eval, depsgraph)
            instance_mesh = get_merged_trimesh_of_objects(instances, depsgraph, False)

        mesh = None
        try:
            mesh = obj_eval.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
        except RuntimeError:
            # No Mesh data
            obj_eval.to_mesh_clear()

        if mesh: 
            for uv_layer in mesh.uv_layers:
                # Make sure that active render uv have the same name for correct merging
                # It is also important for tangent computation (cf _get_tangent)
                if uv_layer.active_render:
                    uv_layer.name = MESH_ACTIVE_UV_NAME
                    break
            # Make sure that active render color have the same name before merge
            active_color = None
            try:
                active_color = mesh.color_attributes[mesh.attributes.render_color_index]
            except:
                pass
            if active_color:
                active_color.name = MESH_ACTIVE_COLOR_NAME

            # Transform into world space
            mat = obj_eval.matrix_world

            temp_bm = bmesh.new()
            temp_bm.from_mesh(mesh)

            bmesh.ops.transform(
                temp_bm,
                matrix=mat,
                verts=temp_bm.verts
            )

            temp_bm.to_mesh(mesh)
            temp_bm.free()
            bm.from_mesh(mesh)
            obj_eval.to_mesh_clear()
    
        if instance_mesh:
            bm.from_mesh(instance_mesh)
            bpy.data.meshes.remove(instance_mesh)


    bmesh.ops.triangulate(
        bm,
        faces=bm.faces,
        quad_method="FIXED",
        ngon_method="EAR_CLIP"
    )

    tri_mesh = bpy.data.meshes.new("TempTriMesh")
    bm.to_mesh(tri_mesh)
    bm.free()

    return tri_mesh
