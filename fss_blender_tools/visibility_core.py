"""FSS Blender Tools: visibility analysis core engine.

Measures per-face visibility sums (weighted visible solid angle and unoccluded solid angle)
from artist-defined reference cameras across animation states, computing per-face patch scores,
undetermined hierarchy resolution, and unbiased seen-face island values from discrete sums
(Decisions 72 to 86). Independent of UI.
"""

import json
import math
import os
import re
import time
from pathlib import Path
from mathutils import Matrix, Vector
import numpy as np
import bpy

try:
    import gpu
    from gpu_extras.batch import batch_for_shader
except ImportError:
    gpu = None
    batch_for_shader = None

ORIG_FACE_ATTR_NAME = "_fss_orig_face_idx"


# ---------------------------------------------------------------------------
# Material & Object Classification (Decision 77)
# ---------------------------------------------------------------------------

def classify_material(mat):
    """Classify a material into 'INVISIBLE', 'DECAL_GLASS', or 'OPAQUE'."""
    if mat is None:
        return 'OPAQUE'

    # Check MSFS material type
    mtype = getattr(mat, 'msfs_material_type', None)
    if (mtype is None or mtype == 'NONE') and 'msfs_material_type' in mat:
        mtype = mat['msfs_material_type']

    if mtype in {'msfs_invisible', 'msfs_environment_occluder', 'msfs_collision'}:
        return 'INVISIBLE'

    if mtype in {
        'msfs_decal', 'msfs_geo_decal', 'msfs_geo_decal_frosted',
        'msfs_geo_decal_blendmasked', 'msfs_glass', 'msfs_windshield'
    }:
        return 'DECAL_GLASS'

    # Check name suffix / class
    base = re.sub(r'\.\d+$', '', mat.name.upper())
    parts = set(base.split('_'))

    invis_tokens = {'INVIS', 'OCCLUDER', 'COLLISION', 'COLLIDER', 'INVISIBLE', 'INVISIBLECOLLIDER'}
    if parts & invis_tokens or any(base.endswith('_' + tok) for tok in invis_tokens) or 'INVISIBLECOLLIDER' in base:
        return 'INVISIBLE'

    decal_tokens = {'DECAL', 'DECAL_EM', 'DECAL_FROST', 'DECAL_BLEND', 'GLASS', 'WNDSHIELD', 'WINDSHIELD'}
    if parts & decal_tokens or any(base.endswith('_' + tok) for tok in decal_tokens):
        return 'DECAL_GLASS'

    return 'OPAQUE'


def is_invisible_object(obj):
    """Check if object name or all of its materials designate invisible/collision geometry."""
    name_upper = obj.name.upper()
    tokens = {'COLLISION', 'COLLIDER', 'INVIS', 'OCCLUDER'}
    if any(tok in name_upper for tok in tokens):
        return True

    # Check materials
    if obj.type == 'MESH' and obj.material_slots:
        mats = [s.material for s in obj.material_slots if s.material]
        if mats and all(classify_material(m) == 'INVISIBLE' for m in mats):
            return True

    return False


# ---------------------------------------------------------------------------
# Attribute Lifecycle (Temporary face index for evaluated meshes)
# ---------------------------------------------------------------------------

def add_orig_face_index_attributes():
    """Add temporary integer face index attribute on all original meshes."""
    for me in bpy.data.meshes:
        n_faces = len(me.polygons)
        if n_faces > 0:
            if ORIG_FACE_ATTR_NAME in me.attributes:
                me.attributes.remove(me.attributes[ORIG_FACE_ATTR_NAME])
            attr = me.attributes.new(name=ORIG_FACE_ATTR_NAME, type='INT', domain='FACE')
            attr.data.foreach_set('value', np.arange(n_faces, dtype=np.int32))


def remove_orig_face_index_attributes():
    """Remove temporary face index attribute from all original meshes."""
    for me in bpy.data.meshes:
        if ORIG_FACE_ATTR_NAME in me.attributes:
            me.attributes.remove(me.attributes[ORIG_FACE_ATTR_NAME])


# ---------------------------------------------------------------------------
# Camera & Projection Math (Decisions 73, 80 & 81)
# ---------------------------------------------------------------------------

def look_at(eye, target, up):
    """Compute view matrix looking from eye towards target with given up vector."""
    z = (eye - target).normalized()
    x = up.cross(z).normalized()
    y = z.cross(x).normalized()
    R = Matrix((
        (x.x, x.y, x.z, 0),
        (y.x, y.y, y.z, 0),
        (z.x, z.y, z.z, 0),
        (0, 0, 0, 1)
    ))
    T = Matrix.Translation(-eye)
    return R @ T


def perspective_proj(fovy, aspect, near, far):
    """Compute standard OpenGL/Vulkan style symmetric perspective projection matrix."""
    tan_half_fovy = math.tan(fovy / 2.0)
    m00 = 1.0 / (aspect * tan_half_fovy)
    m11 = 1.0 / tan_half_fovy
    m22 = -(far + near) / (far - near)
    m23 = -(2.0 * far * near) / (far - near)
    m32 = -1.0
    return Matrix((
        (m00, 0, 0, 0),
        (0, m11, 0, 0),
        (0, 0, m22, m23),
        (0, 0, m32, 0)
    ))


def get_camera_forward(cam_obj):
    """Return forward vector of camera in world space (Blender camera looks down -Z)."""
    return (cam_obj.matrix_world.to_3x3() @ Vector((0, 0, -1))).normalized()


def compute_scene_extent(view_layer, cam_pos):
    """Compute near and far clipping planes from scene extent (Decision 81, Requirement 4)."""
    min_v = np.array([float('inf'), float('inf'), float('inf')], dtype=np.float32)
    max_v = np.array([float('-inf'), float('-inf'), float('-inf')], dtype=np.float32)
    found = False
    for o in view_layer.objects:
        if o.type == 'MESH' and o.data and not o.hide_viewport and not is_invisible_object(o):
            for c in o.bound_box:
                w = o.matrix_world @ Vector(c)
                w_arr = np.array(w, dtype=np.float32)
                min_v = np.minimum(min_v, w_arr)
                max_v = np.maximum(max_v, w_arr)
                found = True
    if not found:
        return 0.05, 30.0

    diag = float(np.linalg.norm(max_v - min_v))
    cam_arr = np.array(cam_pos, dtype=np.float32)
    corners = np.array([
        [min_v[0], min_v[1], min_v[2]],
        [min_v[0], min_v[1], max_v[2]],
        [min_v[0], max_v[1], min_v[2]],
        [min_v[0], max_v[1], max_v[2]],
        [max_v[0], min_v[1], min_v[2]],
        [max_v[0], min_v[1], max_v[2]],
        [max_v[0], max_v[1], min_v[2]],
        [max_v[0], max_v[1], max_v[2]],
    ], dtype=np.float32)
    dists = np.linalg.norm(corners - cam_arr, axis=1)
    max_dist = float(np.max(dists))

    near = 0.05
    far = max(30.0, max_dist * 1.5, diag * 1.5)
    return near, far


def cubemap_face_matrices(cam_pos, cam_forward=None, near=0.05, far=30.0):
    """Return 6 (name, view_matrix, proj_matrix) for a look-around cube map."""
    proj = perspective_proj(math.radians(90.0), 1.0, near, far)
    p = Vector(cam_pos)
    faces = [
        ("FORWARD",  look_at(p, p + Vector((0, -1, 0)), Vector((0, 0, 1))),  proj),
        ("BACKWARD", look_at(p, p + Vector((0, 1, 0)),  Vector((0, 0, 1))),  proj),
        ("LEFT",     look_at(p, p + Vector((-1, 0, 0)), Vector((0, 0, 1))),  proj),
        ("RIGHT",    look_at(p, p + Vector((1, 0, 0)),  Vector((0, 0, 1))),  proj),
        ("UP",       look_at(p, p + Vector((0, 0, 1)),  Vector((0, -1, 0))), proj),
        ("DOWN",     look_at(p, p + Vector((0, 0, -1)), Vector((0, 1, 0))),  proj),
    ]
    return faces


def precompute_cubemap_weights(faces, cam_forward, cube_res=1024, floor=0.2, falloff=1.0):
    """Precompute weighted differential solid angle maps for all 6 cube faces (Decisions 72 & 73)."""
    W = cube_res
    u = (np.arange(W, dtype=np.float32) + 0.5) * (2.0 / W) - 1.0
    v = 1.0 - (np.arange(W, dtype=np.float32) + 0.5) * (2.0 / W)
    U, V = np.meshgrid(u, v)

    d_omega = (4.0 / (W * W)) / np.power(U * U + V * V + 1.0, 1.5).astype(np.float32)
    local_rays = np.stack([U, V, -np.ones_like(U)], axis=-1)

    fwd = np.array(cam_forward, dtype=np.float32)
    fwd /= np.linalg.norm(fwd)

    face_weights = {}
    for face_name, v_mat, _ in faces:
        R_world = np.array(v_mat.to_3x3().transposed(), dtype=np.float32)
        world_rays = local_rays @ R_world.T
        lens = np.linalg.norm(world_rays, axis=-1, keepdims=True)
        world_dirs = world_rays / np.maximum(lens, 1e-12)

        cos_ang = np.sum(world_dirs * fwd, axis=-1)
        if falloff == 1.0:
            ang_weight = np.where(cos_ang > 0.0, np.maximum(floor, cos_ang), floor)
        else:
            pos_term = np.power(np.maximum(cos_ang, 0.0), falloff)
            ang_weight = np.maximum(floor, pos_term)

        face_weights[face_name] = (d_omega * ang_weight).astype(np.float32)

    return face_weights


def precompute_frustum_weights(cam_obj, frustum_res=(2560, 1440)):
    """Precompute differential solid angle map for fixed-view camera frustum."""
    W, H = frustum_res
    dg = bpy.context.evaluated_depsgraph_get()
    proj = cam_obj.calc_matrix_camera(dg, x=W, y=H)

    p00 = float(proj[0][0])
    p11 = float(proj[1][1])

    u = (np.arange(W, dtype=np.float32) + 0.5) * (2.0 / W) - 1.0
    v = 1.0 - (np.arange(H, dtype=np.float32) + 0.5) * (2.0 / H)
    U, V = np.meshgrid(u, v)

    X = U / p00
    Y = V / p11

    dx = 2.0 / (W * p00)
    dy = 2.0 / (H * p11)

    d_omega = (dx * dy) / np.power(X * X + Y * Y + 1.0, 1.5).astype(np.float32)
    return d_omega


def batch_triangle_solid_angle(eye, V0, V1, V2):
    """Vectorized calculation of spherical solid angle for a batch of triangles (Oosterom & Strackee 1983)."""
    eye_arr = np.array(eye, dtype=np.float32).reshape(1, 3)
    A = V0 - eye_arr
    B = V1 - eye_arr
    C = V2 - eye_arr

    N = np.cross(B - A, C - A)
    front = np.sum(N * (-A), axis=-1) > 0.0

    normA = np.linalg.norm(A, axis=-1, keepdims=True)
    normB = np.linalg.norm(B, axis=-1, keepdims=True)
    normC = np.linalg.norm(C, axis=-1, keepdims=True)

    eps = 1e-12
    valid = (normA[..., 0] > eps) & (normB[..., 0] > eps) & (normC[..., 0] > eps) & front

    a = A / np.maximum(normA, eps)
    b = B / np.maximum(normB, eps)
    c = C / np.maximum(normC, eps)

    b_cross_c = np.cross(b, c)
    num = np.abs(np.sum(a * b_cross_c, axis=-1))
    den = 1.0 + np.sum(a * b, axis=-1) + np.sum(b * c, axis=-1) + np.sum(c * a, axis=-1)

    omega = 2.0 * np.arctan2(num, den)
    omega = np.where(omega < 0.0, omega + 2.0 * np.pi, omega)
    return np.where(valid, omega, 0.0).astype(np.float32)


# ---------------------------------------------------------------------------
# GPU Shaders
# ---------------------------------------------------------------------------

_id_shader = None


def get_id_shader():
    """Flat face-ID shader encoding integer ID into RGB bytes."""
    global _id_shader
    if _id_shader is None and gpu is not None:
        info = gpu.types.GPUShaderCreateInfo()
        info.push_constant('MAT4', 'mvp')
        info.vertex_in(0, 'VEC3', 'pos')
        info.vertex_in(1, 'INT', 'face_id')
        iface = gpu.types.GPUStageInterfaceInfo('face_id_iface')
        iface.flat('INT', 'v_id')
        info.vertex_out(iface)
        info.fragment_out(0, 'VEC4', 'FragColor')
        info.vertex_source('void main() { gl_Position = mvp * vec4(pos, 1.0); v_id = face_id; }')
        info.fragment_source('''
            void main() {
                float r = float(v_id & 255) / 255.0;
                float g = float((v_id >> 8) & 255) / 255.0;
                float b = float((v_id >> 16) & 255) / 255.0;
                FragColor = vec4(r, g, b, 1.0);
            }
        ''')
        _id_shader = gpu.shader.create_from_info(info)
    return _id_shader


# ---------------------------------------------------------------------------
# Mesh Topology, Face Adjacency & UV Islands (Decision 79)
# ---------------------------------------------------------------------------

def extract_mesh_uv_islands(me, uv_name=None):
    """Extract UV island ID for each polygon of base mesh."""
    n_polys = len(me.polygons)
    if n_polys == 0:
        return np.zeros(0, dtype=np.int32)

    if uv_name:
        uv_layer = me.uv_layers.get(uv_name)
    else:
        uv_layer = me.uv_layers.active

    if not uv_layer or len(me.loops) == 0:
        return np.zeros(n_polys, dtype=np.int32)

    loop_vert_indices = np.empty(len(me.loops), dtype=np.int32)
    me.loops.foreach_get('vertex_index', loop_vert_indices)

    loop_uvs = np.empty((len(me.loops), 2), dtype=np.float32)
    uv_layer.data.foreach_get('uv', loop_uvs.ravel())
    loop_uvs_quant = np.round(loop_uvs, decimals=4)

    keys, corner_ids = np.unique(
        np.column_stack((loop_vert_indices, loop_uvs_quant)),
        axis=0,
        return_inverse=True
    )

    parent = np.arange(n_polys, dtype=np.int32)

    def find(i):
        path = []
        while parent[i] != i:
            path.append(i)
            i = parent[i]
        for p in path:
            parent[p] = i
        return i

    poly_edges = {}
    for p_idx, p in enumerate(me.polygons):
        p_loops = list(p.loop_indices)
        k = len(p_loops)
        for i in range(k):
            c1 = corner_ids[p_loops[i]]
            c2 = corner_ids[p_loops[(i + 1) % k]]
            edge = (c1, c2) if c1 < c2 else (c2, c1)
            if edge in poly_edges:
                pi, pj = find(p_idx), find(poly_edges[edge])
                if pi != pj:
                    parent[pi] = pj
            else:
                poly_edges[edge] = p_idx

    roots = np.array([find(i) for i in range(n_polys)], dtype=np.int32)
    _, island_ids = np.unique(roots, return_inverse=True)
    return island_ids.astype(np.int32)


def extract_mesh_face_adjacency(me, mat_slots=None):
    """Compute face adjacency and connected components from original mesh edges.

    Excludes faces of invisible material classes.
    Returns:
    - adj: list of lists, where adj[i] contains adjacent visible polygon indices
    - face_to_comp: np.ndarray (n_polys,) int32 component IDs (-1 for invisible)
    - components: list of np.ndarray of face indices for each connected piece
    """
    n_polys = len(me.polygons)
    if n_polys == 0:
        return [], np.zeros(0, dtype=np.int32), []

    # Identify invisible polygons
    is_invis = np.zeros(n_polys, dtype=bool)
    if mat_slots:
        for p in me.polygons:
            mi = p.material_index
            m = mat_slots[mi].material if mi < len(mat_slots) else None
            if classify_material(m) == 'INVISIBLE':
                is_invis[p.index] = True

    # Map edges to visible polygons
    edge_to_faces = {}
    for p in me.polygons:
        if is_invis[p.index]:
            continue
        p_verts = p.vertices
        nv = len(p_verts)
        for i in range(nv):
            v0 = p_verts[i]
            v1 = p_verts[(i + 1) % nv]
            e = (v0, v1) if v0 < v1 else (v1, v0)
            edge_to_faces.setdefault(e, []).append(p.index)

    # Build adjacency list
    adj = [[] for _ in range(n_polys)]
    for e, face_list in edge_to_faces.items():
        if len(face_list) > 1:
            for i in range(len(face_list)):
                fi = face_list[i]
                for j in range(i + 1, len(face_list)):
                    fj = face_list[j]
                    adj[fi].append(fj)
                    adj[fj].append(fi)

    for i in range(n_polys):
        if adj[i]:
            adj[i] = list(set(adj[i]))

    # Connected components among visible faces
    face_to_comp = np.full(n_polys, -1, dtype=np.int32)
    components = []
    comp_id = 0

    for i in range(n_polys):
        if is_invis[i] or face_to_comp[i] != -1:
            continue
        comp = []
        queue = [i]
        face_to_comp[i] = comp_id
        head = 0
        while head < len(queue):
            curr = queue[head]
            head += 1
            comp.append(curr)
            for nbr in adj[curr]:
                if face_to_comp[nbr] == -1 and not is_invis[nbr]:
                    face_to_comp[nbr] = comp_id
                    queue.append(nbr)
        components.append(np.array(comp, dtype=np.int32))
        comp_id += 1

    return adj, face_to_comp, components


# ---------------------------------------------------------------------------
# Instance Discovery & Evaluated Scene Extraction
# ---------------------------------------------------------------------------

def discover_mesh_instances(view_layer):
    """Scan scene for visible mesh objects and assign instances per mesh."""
    mesh_meta = {}

    mesh_objs = [
        o for o in view_layer.objects
        if o is not None and o.type == 'MESH' and o.data and not o.hide_viewport and not o.hide_render
    ]

    for o in mesh_objs:
        if is_invisible_object(o):
            continue

        me_orig = o.data
        mesh_name = me_orig.name
        n_orig_faces = len(me_orig.polygons)
        if n_orig_faces == 0:
            continue

        if mesh_name not in mesh_meta:
            V_base = np.empty((len(me_orig.vertices), 3), dtype=np.float32)
            me_orig.vertices.foreach_get('co', V_base.ravel())
            M_base = np.array(o.matrix_world, dtype=np.float32)
            V_world_base = V_base @ M_base[:3, :3].T + M_base[:3, 3]

            orig_areas = np.zeros(n_orig_faces, dtype=np.float32)
            for i, p in enumerate(me_orig.polygons):
                p_verts = [V_world_base[vi] for vi in p.vertices]
                if len(p_verts) == 3:
                    e1 = p_verts[1] - p_verts[0]
                    e2 = p_verts[2] - p_verts[0]
                    orig_areas[i] = 0.5 * np.linalg.norm(np.cross(e1, e2))
                elif len(p_verts) >= 4:
                    poly_area = 0.0
                    for vi in range(1, len(p_verts) - 1):
                        e1 = p_verts[vi] - p_verts[0]
                        e2 = p_verts[vi + 1] - p_verts[0]
                        poly_area += 0.5 * np.linalg.norm(np.cross(e1, e2))
                    orig_areas[i] = poly_area

            island_ids = extract_mesh_uv_islands(me_orig)
            adj, face_to_comp, components = extract_mesh_face_adjacency(me_orig, o.material_slots)

            mesh_meta[mesh_name] = {
                'mesh': me_orig,
                'n_orig_faces': n_orig_faces,
                'orig_areas': orig_areas,
                'island_ids': island_ids,
                'adjacency': adj,
                'face_to_comp': face_to_comp,
                'components': components,
                'instances': [],
                'instance_map': {},
            }

        # Check Mirror modifiers on this object
        mirror_mods = [m for m in o.modifiers if m.type == 'MIRROR']
        if mirror_mods:
            use_x = any(m.use_axis[0] for m in mirror_mods)
            use_y = any(m.use_axis[1] for m in mirror_mods)
            use_z = any(m.use_axis[2] for m in mirror_mods)
            active_copies = [0]
            if use_x:
                active_copies += [c + 1 for c in active_copies]
            if use_y:
                active_copies += [c + 2 for c in active_copies]
            if use_z:
                active_copies += [c + 4 for c in active_copies]
        else:
            active_copies = [0]

        for c_idx in sorted(set(active_copies)):
            key = (o.name, c_idx)
            if key not in mesh_meta[mesh_name]['instance_map']:
                inst_id = len(mesh_meta[mesh_name]['instances'])
                mesh_meta[mesh_name]['instances'].append({
                    'object_name': o.name,
                    'copy_idx': c_idx,
                    'inst_idx': inst_id,
                })
                mesh_meta[mesh_name]['instance_map'][key] = inst_id

    return mesh_meta


def extract_scene_geometry(depsgraph, view_layer, mesh_meta):
    """Extract evaluated scene geometry split into Opaque and Decal batches."""
    opaque_pos = []
    opaque_ids = []
    decal_pos = []
    decal_ids = []

    all_tri_v0 = []
    all_tri_v1 = []
    all_tri_v2 = []
    all_tri_ids = []

    eval_poly_info = {}
    global_id = 1

    mesh_objs = [
        o for o in view_layer.objects
        if o is not None and o.type == 'MESH' and o.data and not o.hide_viewport and not o.hide_render
    ]

    for o in mesh_objs:
        if is_invisible_object(o):
            continue

        me_orig = o.data
        mesh_name = me_orig.name
        if mesh_name not in mesh_meta:
            continue

        meta = mesh_meta[mesh_name]
        n_orig_faces = meta['n_orig_faces']

        eval_obj = o.evaluated_get(depsgraph)
        eval_me = eval_obj.to_mesh()
        eval_me.calc_loop_triangles()

        n_lt = len(eval_me.loop_triangles)
        if n_lt == 0:
            eval_obj.to_mesh_clear()
            continue

        verts = np.empty((n_lt, 3), dtype=np.int32)
        eval_me.loop_triangles.foreach_get('vertices', verts.ravel())

        V_eval = np.empty((len(eval_me.vertices), 3), dtype=np.float32)
        eval_me.vertices.foreach_get('co', V_eval.ravel())
        M_eval = np.array(o.matrix_world, dtype=np.float32)
        P_world = (V_eval @ M_eval[:3, :3].T + M_eval[:3, 3])[verts]

        poly_indices = np.empty(n_lt, dtype=np.int32)
        eval_me.loop_triangles.foreach_get('polygon_index', poly_indices)

        n_eval_polys = len(eval_me.polygons)
        base_id = global_id

        # Classify each evaluated polygon by material
        poly_mat_class = []
        for p in eval_me.polygons:
            mat_idx = p.material_index
            mat = o.material_slots[mat_idx].material if mat_idx < len(o.material_slots) else None
            poly_mat_class.append(classify_material(mat))

        # Read original face index attribute transferred through modifiers
        eval_attr = eval_me.attributes.get(ORIG_FACE_ATTR_NAME)
        if eval_attr:
            orig_indices = np.empty(n_eval_polys, dtype=np.int32)
            eval_attr.data.foreach_get('value', orig_indices)
        else:
            raise RuntimeError(f"Attribute {ORIG_FACE_ATTR_NAME} missing on evaluated mesh {mesh_name}")

        # Check Mirror modifier axes for copy classification
        mirror_mods = [m for m in o.modifiers if m.type == 'MIRROR']
        use_x = any(m.use_axis[0] for m in mirror_mods)
        use_y = any(m.use_axis[1] for m in mirror_mods)
        use_z = any(m.use_axis[2] for m in mirror_mods)

        for ep_idx in range(n_eval_polys):
            eid = base_id + ep_idx
            orig_idx = int(orig_indices[ep_idx])

            # Classify mirror copy
            if mirror_mods:
                eval_c = eval_me.polygons[ep_idx].center
                orig_c = me_orig.polygons[orig_idx].center
                flip_x = int(use_x and ((eval_c.x * orig_c.x < -1e-6) or (abs(orig_c.x) < 1e-4 and eval_c.x < -1e-4)))
                flip_y = int(use_y and ((eval_c.y * orig_c.y < -1e-6) or (abs(orig_c.y) < 1e-4 and eval_c.y < -1e-4)))
                flip_z = int(use_z and ((eval_c.z * orig_c.z < -1e-6) or (abs(orig_c.z) < 1e-4 and eval_c.z < -1e-4)))
                copy_idx = flip_x * 1 + flip_y * 2 + flip_z * 4
            else:
                copy_idx = 0

            inst_key = (o.name, copy_idx)
            inst_idx = meta['instance_map'].get(inst_key, 0)
            eval_poly_info[eid] = (mesh_name, inst_idx, orig_idx)

        # Split loop triangles into batches
        tri_ids = base_id + poly_indices
        tri_mclasses = [poly_mat_class[pi] for pi in poly_indices]

        for tri_idx in range(n_lt):
            mcls = tri_mclasses[tri_idx]
            if mcls == 'INVISIBLE':
                continue  # Excluded from all batches and analytical triangles

            tid = tri_ids[tri_idx]
            tri_p = P_world[tri_idx]
            tri_id_expanded = np.array([tid, tid, tid], dtype=np.int32)

            all_tri_v0.append(tri_p[0:1])
            all_tri_v1.append(tri_p[1:2])
            all_tri_v2.append(tri_p[2:3])
            all_tri_ids.append(np.array([tid], dtype=np.int32))

            if mcls == 'DECAL_GLASS':
                decal_pos.append(tri_p)
                decal_ids.append(tri_id_expanded)
            else:
                opaque_pos.append(tri_p)
                opaque_ids.append(tri_id_expanded)

        global_id += n_eval_polys
        eval_obj.to_mesh_clear()

    batches = {
        'opaque_pos': np.concatenate(opaque_pos, axis=0) if opaque_pos else np.zeros((0, 3), dtype=np.float32),
        'opaque_ids': np.concatenate(opaque_ids, axis=0) if opaque_ids else np.zeros(0, dtype=np.int32),
        'decal_pos': np.concatenate(decal_pos, axis=0) if decal_pos else np.zeros((0, 3), dtype=np.float32),
        'decal_ids': np.concatenate(decal_ids, axis=0) if decal_ids else np.zeros(0, dtype=np.int32),
    }

    tri_geometry = {
        'V0': np.concatenate(all_tri_v0, axis=0) if all_tri_v0 else np.zeros((0, 3), dtype=np.float32),
        'V1': np.concatenate(all_tri_v1, axis=0) if all_tri_v1 else np.zeros((0, 3), dtype=np.float32),
        'V2': np.concatenate(all_tri_v2, axis=0) if all_tri_v2 else np.zeros((0, 3), dtype=np.float32),
        'tri_ids': np.concatenate(all_tri_ids, axis=0) if all_tri_ids else np.zeros(0, dtype=np.int32),
    }

    return batches, eval_poly_info, tri_geometry, global_id


# ---------------------------------------------------------------------------
# Animation State Controller (Decisions 69 & 86)
# ---------------------------------------------------------------------------

class AnimationStateController:
    """Manages normalized action/NLA percentage states across scene objects."""

    def __init__(self, scene=None):
        self.scene = scene or bpy.context.scene
        self.initial_frame = self.scene.frame_current
        self.original_states = []
        self._setup()

    def _setup(self):
        for o in self.scene.objects:
            if not o.animation_data:
                continue

            act = o.animation_data.action
            if act:
                f_min, f_max = act.frame_range
                self.original_states.append({
                    'object': o,
                    'type': 'ACTION',
                    'action': act,
                    'frame_start': f_min,
                    'frame_end': f_max,
                })
            elif o.animation_data.nla_tracks:
                f_min = float('inf')
                f_max = float('-inf')
                for tr in o.animation_data.nla_tracks:
                    for st in tr.strips:
                        f_min = min(f_min, st.frame_start)
                        f_max = max(f_max, st.frame_end)
                if f_min < f_max:
                    self.original_states.append({
                        'object': o,
                        'type': 'NLA',
                        'frame_start': f_min,
                        'frame_end': f_max,
                    })

    def apply_percentage_state(self, pct):
        pct_norm = pct if pct <= 1.0 else pct / 100.0
        for entry in self.original_states:
            f_min = entry['frame_start']
            f_max = entry['frame_end']
            target_frame = f_min + pct_norm * (f_max - f_min)
            self.scene.frame_set(int(round(target_frame)))

    def restore(self):
        self.scene.frame_set(self.initial_frame)


# ---------------------------------------------------------------------------
# Offscreen Render & Solid Angle Accumulation (Decisions 72 & 77)
# ---------------------------------------------------------------------------

class BatchWrapper:
    def __init__(self, batch, tri_count):
        self.batch = batch
        self.tri_count = tri_count

    def draw(self, shader):
        if self.batch and self.tri_count > 0:
            self.batch.draw(shader)

    def has_triangles(self):
        return self.batch is not None and self.tri_count > 0


def render_camera_view(offscreen, shader, batch_opaque, batch_decal, mvp, weight_map, max_id):
    """Draw opaque pass followed by decal pass with depth_mask=False."""
    W, H = offscreen.width, offscreen.height
    counts_opaque = np.zeros(max_id + 1, dtype=np.float64)
    counts_decal = np.zeros(max_id + 1, dtype=np.float64)

    weight_flat = weight_map.ravel()

    with offscreen.bind():
        fb = gpu.state.active_framebuffer_get()

        # Pass 1: Opaque
        fb.clear(color=(0, 0, 0, 1), depth=1.0)
        gpu.state.depth_test_set('LESS_EQUAL')
        gpu.state.depth_mask_set(True)
        shader.bind()
        shader.uniform_float('mvp', mvp)

        if batch_opaque is not None and batch_opaque.has_triangles():
            batch_opaque.draw(shader)
            px = np.array(fb.read_color(0, 0, W, H, 4, 0, 'UBYTE'), dtype=np.uint8)
            ids = (
                px[..., 0].astype(np.int32)
                | (px[..., 1].astype(np.int32) << 8)
                | (px[..., 2].astype(np.int32) << 16)
            ).ravel()
            counts_opaque = np.bincount(ids, weights=weight_flat, minlength=max_id + 1)

        # Pass 2: Decal / Glass
        if batch_decal is not None and batch_decal.has_triangles():
            fb.clear(color=(0, 0, 0, 1))
            gpu.state.depth_mask_set(False)
            batch_decal.draw(shader)
            px = np.array(fb.read_color(0, 0, W, H, 4, 0, 'UBYTE'), dtype=np.uint8)
            ids = (
                px[..., 0].astype(np.int32)
                | (px[..., 1].astype(np.int32) << 8)
                | (px[..., 2].astype(np.int32) << 16)
            ).ravel()
            counts_decal = np.bincount(ids, weights=weight_flat, minlength=max_id + 1)

        gpu.state.depth_test_set('NONE')

    return counts_opaque + counts_decal


# ---------------------------------------------------------------------------
# Per-Face Patches, Hierarchy Fallback & Island Scoring (Decisions 79 & 82)
# ---------------------------------------------------------------------------

def compute_patch_scores_and_groups(mesh_meta, mesh_arrays, min_px_threshold=10.0, ref_cube_res=1024, scene=None):
    """Compute per-face scores from patches, resolve undetermined pieces, and compute island values (Decision 82)."""
    t_start = time.perf_counter()
    d_omega_px = 4.0 / (ref_cube_res * ref_cube_res)
    omega_threshold = min_px_threshold * d_omega_px
    scene = scene or bpy.context.scene

    # Hierarchy maps for scene objects
    children_map = {}
    for o in scene.objects:
        p_name = o.parent.name if o.parent else None
        children_map.setdefault(p_name, []).append(o)

    def get_subtree_mesh_objects(root_obj):
        res = []
        queue = [root_obj]
        head = 0
        while head < len(queue):
            curr = queue[head]
            head += 1
            if curr.type == 'MESH' and curr.data:
                res.append(curr)
            for child in children_map.get(curr.name, []):
                queue.append(child)
        return res

    # 1. Grow patches per face on each mesh
    for m_name, meta in mesh_meta.items():
        m_data = mesh_arrays[m_name]
        vis_arr = m_data['vis_omega']      # (V, K, F)
        unocc_arr = m_data['unocc_omega']  # (V, K, F)
        n_faces = meta['n_orig_faces']
        adj = meta['adjacency']
        components = meta['components']

        face_scores = np.zeros(n_faces, dtype=np.float32)
        face_undetermined = np.zeros(n_faces, dtype=bool)
        face_never_seen = np.zeros(n_faces, dtype=bool)
        face_patch_size_px = np.zeros(n_faces, dtype=np.float32)

        # Check maximum unoccluded solid angle for each connected piece
        comp_unocc_max = {}
        for c_id, comp_faces in enumerate(components):
            if len(comp_faces) == 0:
                comp_unocc_max[c_id] = 0.0
                continue
            c_unocc = np.sum(unocc_arr[:, :, comp_faces], axis=-1)
            comp_unocc_max[c_id] = float(np.max(c_unocc))

        # Identify components that cannot reach threshold:
        undetermined_comp_ids = {c_id for c_id, max_u in comp_unocc_max.items() if 0.0 < max_u < omega_threshold}
        never_seen_comp_ids = {c_id for c_id, max_u in comp_unocc_max.items() if max_u == 0.0}

        for c_id in undetermined_comp_ids:
            c_faces = components[c_id]
            face_undetermined[c_faces] = True
            face_never_seen[c_faces] = False
            face_patch_size_px[c_faces] = comp_unocc_max[c_id] / d_omega_px

        for c_id in never_seen_comp_ids:
            c_faces = components[c_id]
            face_scores[c_faces] = 0.0
            face_undetermined[c_faces] = False
            face_never_seen[c_faces] = True
            face_patch_size_px[c_faces] = 0.0

        # Expand patches for faces in measurable components
        for c_id, comp_faces in enumerate(components):
            if c_id in undetermined_comp_ids or c_id in never_seen_comp_ids:
                continue

            for f in comp_faces:
                f_unocc = unocc_arr[:, :, f]
                f_max_u = float(np.max(f_unocc))

                if f_max_u >= omega_threshold:
                    valid = f_unocc > 1e-12
                    f_vis = vis_arr[:, :, f]
                    ratio = np.where(valid, np.clip(f_vis / np.maximum(f_unocc, 1e-12), 0.0, 1.0), 0.0)
                    face_scores[f] = float(np.max(ratio))
                    face_never_seen[f] = bool(np.max(f_vis) == 0.0)
                    face_undetermined[f] = False
                    face_patch_size_px[f] = f_max_u / d_omega_px
                else:
                    patch_set = {int(f)}
                    cur_ring = [int(f)]
                    patch_unocc = f_unocc.copy()
                    while float(np.max(patch_unocc)) < omega_threshold:
                        nxt_ring = []
                        for u in cur_ring:
                            for v in adj[u]:
                                if v not in patch_set:
                                    patch_set.add(v)
                                    nxt_ring.append(v)
                        if not nxt_ring:
                            break
                        patch_unocc += np.sum(unocc_arr[:, :, nxt_ring], axis=-1)
                        cur_ring = nxt_ring

                    p_max_u = float(np.max(patch_unocc))
                    if 0.0 < p_max_u < omega_threshold:
                        face_undetermined[f] = True
                        face_never_seen[f] = False
                        face_patch_size_px[f] = p_max_u / d_omega_px
                    elif p_max_u == 0.0:
                        face_scores[f] = 0.0
                        face_undetermined[f] = False
                        face_never_seen[f] = True
                        face_patch_size_px[f] = 0.0
                    else:
                        patch_faces = list(patch_set)
                        patch_vis = np.sum(vis_arr[:, :, patch_faces], axis=-1)
                        valid = patch_unocc > 1e-12
                        ratio = np.where(valid, np.clip(patch_vis / np.maximum(patch_unocc, 1e-12), 0.0, 1.0), 0.0)
                        face_scores[f] = float(np.max(ratio))
                        face_never_seen[f] = bool(np.max(patch_vis) == 0.0)
                        face_undetermined[f] = False
                        face_patch_size_px[f] = p_max_u / d_omega_px

        m_data['face_scores'] = face_scores
        m_data['face_undetermined'] = face_undetermined
        m_data['face_never_seen'] = face_never_seen
        m_data['face_patch_size_px'] = face_patch_size_px

    patch_expansion_time = time.perf_counter() - t_start

    # 2. Hierarchy Fallback Resolution for Undetermined Pieces (Decision 79)
    def resolve_object_score(obj):
        m_name = obj.data.name
        inst_idx = mesh_meta[m_name]['instance_map'].get((obj.name, 0), 0)
        unocc_o = np.sum(mesh_arrays[m_name]['unocc_omega'][:, inst_idx, :], axis=-1)
        if float(np.max(unocc_o)) >= omega_threshold:
            vis_o = np.sum(mesh_arrays[m_name]['vis_omega'][:, inst_idx, :], axis=-1)
            valid = unocc_o > 1e-12
            ratio = np.where(valid, np.clip(vis_o / np.maximum(unocc_o, 1e-12), 0.0, 1.0), 0.0)
            return float(np.max(ratio)), 'OBJECT', float(np.max(unocc_o)) / d_omega_px

        cur = obj.parent
        while cur is not None:
            descendants = get_subtree_mesh_objects(cur)
            V = mesh_arrays[m_name]['vis_omega'].shape[0]
            sub_vis = np.zeros(V, dtype=np.float64)
            sub_unocc = np.zeros(V, dtype=np.float64)
            for d in descendants:
                if is_invisible_object(d):
                    continue
                dm_name = d.data.name
                if dm_name in mesh_meta and dm_name in mesh_arrays:
                    d_inst = mesh_meta[dm_name]['instance_map'].get((d.name, 0), 0)
                    sub_vis += np.sum(mesh_arrays[dm_name]['vis_omega'][:, d_inst, :], axis=-1)
                    sub_unocc += np.sum(mesh_arrays[dm_name]['unocc_omega'][:, d_inst, :], axis=-1)

            sub_max_u = float(np.max(sub_unocc))
            if sub_max_u >= omega_threshold:
                valid = sub_unocc > 1e-12
                ratio = np.where(valid, np.clip(sub_vis / np.maximum(sub_unocc, 1e-12), 0.0, 1.0), 0.0)
                return float(np.max(ratio)), 'PARENT_SUBTREE', sub_max_u / d_omega_px

            cur = cur.parent

        return 1.0, 'FALLBACK_1.0', 0.0

    resolved_counts = {
        'OBJECT': {'faces': 0, 'pieces': 0, 'objects': 0},
        'PARENT_SUBTREE': {'faces': 0, 'pieces': 0, 'objects': 0},
        'FALLBACK_1.0': {'faces': 0, 'pieces': 0, 'objects': 0},
    }

    object_summaries = {}
    island_summaries = {}

    for m_name, meta in mesh_meta.items():
        m_data = mesh_arrays[m_name]
        face_scores = m_data['face_scores']
        face_undetermined = m_data['face_undetermined']
        face_never_seen = m_data['face_never_seen']
        areas = meta['orig_areas']
        island_ids = meta['island_ids']
        components = meta['components']
        n_faces = meta['n_orig_faces']

        if np.any(face_undetermined):
            cand_scores = []
            cand_levels = []
            for inst_info in meta['instances']:
                o_name = inst_info['object_name']
                o_obj = bpy.data.objects.get(o_name)
                if o_obj:
                    s_inh, lvl, _ = resolve_object_score(o_obj)
                    cand_scores.append(s_inh)
                    cand_levels.append(lvl)
                else:
                    cand_scores.append(1.0)
                    cand_levels.append('FALLBACK_1.0')

            best_idx = int(np.argmax(cand_scores)) if cand_scores else 0
            best_inh_score = cand_scores[best_idx] if cand_scores else 1.0
            best_lvl = cand_levels[best_idx] if cand_levels else 'FALLBACK_1.0'

            face_scores[face_undetermined] = best_inh_score
            face_never_seen[face_undetermined] = False

            n_u_faces = int(np.count_nonzero(face_undetermined))
            resolved_counts[best_lvl]['faces'] += n_u_faces

            for c in components:
                if len(c) > 0 and np.all(face_undetermined[c]):
                    resolved_counts[best_lvl]['pieces'] += 1

        # 3. Compute Island Values (Decision 82)
        unique_isls = np.unique(island_ids)
        isl_values_arr = np.zeros(len(unique_isls), dtype=np.float32)
        isl_never_seen_arr = np.zeros(len(unique_isls), dtype=bool)
        isl_seen_share_arr = np.zeros(len(unique_isls), dtype=np.float32)
        isl_undet_only_arr = np.zeros(len(unique_isls), dtype=bool)
        isl_r4_avg_arr = np.zeros(len(unique_isls), dtype=np.float32)

        for idx, isl_id in enumerate(unique_isls):
            isl_mask = (island_ids == isl_id)
            isl_faces = np.flatnonzero(isl_mask)
            f_sc = face_scores[isl_faces]
            f_ar = areas[isl_faces]
            f_udet = face_undetermined[isl_faces]

            f_unocc = np.sum(m_data['unocc_omega'][:, :, isl_faces], axis=-1)
            isl_size_px = float(np.max(f_unocc)) / d_omega_px
            tot_area = float(np.sum(f_ar))

            seen_mask = (f_sc > 0.0)
            seen_area = float(np.sum(f_ar[seen_mask]))
            seen_faces = isl_faces[seen_mask]

            if seen_area > 0.0:
                never_seen = False
                seen_share = seen_area / max(tot_area, 1e-12)
                is_undet_only = bool(np.all(f_udet[seen_mask]))
                r4_avg = float(np.sum(f_sc[seen_mask] * f_ar[seen_mask]) / seen_area)

                seen_unocc = np.sum(m_data['unocc_omega'][:, :, seen_faces], axis=-1)
                max_seen_unocc = float(np.max(seen_unocc))

                if max_seen_unocc >= omega_threshold:
                    seen_vis = np.sum(m_data['vis_omega'][:, :, seen_faces], axis=-1)
                    valid = seen_unocc > 1e-12
                    ratio = np.where(valid, np.clip(seen_vis / np.maximum(seen_unocc, 1e-12), 0.0, 1.0), 0.0)
                    isl_val = float(np.max(ratio))
                else:
                    isl_val = r4_avg
            else:
                isl_val = 0.0
                r4_avg = 0.0
                never_seen = True
                seen_share = 0.0
                is_undet_only = False

            isl_values_arr[idx] = isl_val
            isl_never_seen_arr[idx] = never_seen
            isl_seen_share_arr[idx] = seen_share
            isl_undet_only_arr[idx] = is_undet_only
            isl_r4_avg_arr[idx] = r4_avg

            island_summaries[f"{m_name}__isl_{isl_id}"] = {
                'mesh_name': m_name,
                'island_id': int(isl_id),
                'score': isl_val,
                'r4_avg': r4_avg,
                'size_px': isl_size_px,
                'never_seen': never_seen,
                'seen_area_share': seen_share,
                'undetermined_only': is_undet_only,
                'area_m2': tot_area,
                'n_faces': len(isl_faces),
            }

        m_data['island_scores'] = isl_values_arr
        m_data['island_never_seen'] = isl_never_seen_arr
        m_data['island_seen_shares'] = isl_seen_share_arr
        m_data['island_undet_only'] = isl_undet_only_arr
        m_data['island_r4_avgs'] = isl_r4_avg_arr

        # 4. Compute Object Summaries (Decision 82)
        for inst_info in meta['instances']:
            o_name = inst_info['object_name']
            if o_name in object_summaries:
                continue

            o_obj = bpy.data.objects.get(o_name)
            inst_idx = inst_info['inst_idx']
            o_unocc = np.sum(m_data['unocc_omega'][:, inst_idx, :], axis=-1)
            o_size_px = float(np.max(o_unocc)) / d_omega_px
            o_tot_area = float(np.sum(areas))

            if 0.0 < o_size_px < min_px_threshold:
                o_score, o_lvl, _ = resolve_object_score(o_obj) if o_obj else (1.0, 'FALLBACK_1.0', 0.0)
                o_r4_avg = o_score
                o_never_seen = False
                o_undetermined = True
                o_seen_share = 1.0
                resolved_counts[o_lvl]['objects'] += 1
            elif o_size_px == 0.0:
                o_score = 0.0
                o_r4_avg = 0.0
                o_never_seen = True
                o_undetermined = False
                o_seen_share = 0.0
            else:
                seen_mask = (face_scores > 0.0)
                seen_area = float(np.sum(areas[seen_mask]))
                seen_faces = np.flatnonzero(seen_mask)
                if seen_area > 0.0:
                    o_r4_avg = float(np.sum(face_scores[seen_mask] * areas[seen_mask]) / seen_area)
                    seen_unocc_mesh = np.sum(m_data['unocc_omega'][:, :, seen_faces], axis=-1)
                    max_seen_unocc_mesh = float(np.max(seen_unocc_mesh))
                    if max_seen_unocc_mesh >= omega_threshold:
                        seen_vis_mesh = np.sum(m_data['vis_omega'][:, :, seen_faces], axis=-1)
                        valid_mesh = seen_unocc_mesh > 1e-12
                        ratio_mesh = np.where(valid_mesh, np.clip(seen_vis_mesh / np.maximum(seen_unocc_mesh, 1e-12), 0.0, 1.0), 0.0)
                        o_score = float(np.max(ratio_mesh))
                    else:
                        o_score = o_r4_avg
                    o_never_seen = False
                    o_seen_share = seen_area / max(o_tot_area, 1e-12)
                else:
                    o_score = 0.0
                    o_r4_avg = 0.0
                    o_never_seen = True
                    o_seen_share = 0.0
                o_undetermined = False

            object_summaries[o_name] = {
                'mesh_name': m_name,
                'score': o_score,
                'r4_avg': o_r4_avg,
                'size_px': o_size_px,
                'never_seen': o_never_seen,
                'undetermined': o_undetermined,
                'seen_area_share': o_seen_share,
                'area_m2': o_tot_area,
                'n_faces': n_faces,
            }

    return {
        'patch_expansion_time_s': patch_expansion_time,
        'resolved_counts': resolved_counts,
        'object_summaries': object_summaries,
        'island_summaries': island_summaries,
    }


def weighted_percentile(values, weights, q):
    """Compute weighted quantile q in [0, 1]."""
    if len(values) == 0:
        return 0.0
    order = np.argsort(values, kind='stable')
    sorted_v = values[order]
    sorted_w = weights[order]
    cw = np.cumsum(sorted_w)
    tot = cw[-1]
    if tot <= 0:
        return 0.0
    cutoff = q * tot
    idx = np.searchsorted(cw, cutoff)
    return float(sorted_v[min(idx, len(sorted_v) - 1)])


# ---------------------------------------------------------------------------
# File I/O (Schema Version 4 + Settings)
# ---------------------------------------------------------------------------

def save_visibility_file(blend_path, results, settings=None):
    """Save results as compressed `<blend_name>.visibility` (Schema Version 4)."""
    vis_path = Path(blend_path).with_suffix('.visibility')

    mesh_face_counts = {
        m_name: meta['n_orig_faces'] for m_name, meta in results['mesh_meta'].items()
    }

    meta = {
        'schema_version': 4,
        'blend_file': str(results.get('blend_file', blend_path)),
        'timestamp': time.strftime("%Y-%m-%d %H:%M:%S"),
        'total_time_s': results.get('total_time_s', 0.0),
        'patch_expansion_time_s': results.get('patch_expansion_time_s', 0.0),
        'state_timings': results.get('state_timings', {}),
        'views': results.get('views', []),
        'ref_cube_res': results.get('ref_cube_res', 1024),
        'min_px_threshold': results.get('min_px_threshold', 10.0),
        'total_faces': results.get('total_faces', 0),
        'total_surface_area_m2': results.get('total_surface_area_m2', 0.0),
        'total_objects': results.get('total_objects', 0),
        'never_seen_objects_count': results.get('never_seen_objects_count', 0),
        'undetermined_objects_count': results.get('undetermined_objects_count', 0),
        'total_islands': results.get('total_islands', 0),
        'never_seen_islands_count': results.get('never_seen_islands_count', 0),
        'total_never_seen_faces': results.get('total_never_seen_faces', 0),
        'total_never_seen_face_area_m2': results.get('total_never_seen_face_area_m2', 0.0),
        'total_undetermined_faces': results.get('total_undetermined_faces', 0),
        'total_undetermined_face_area_m2': results.get('total_undetermined_face_area_m2', 0.0),
        'face_percentiles': results.get('face_percentiles', {}),
        'island_percentiles': results.get('island_percentiles', {}),
        'resolved_counts': results.get('resolved_counts', {}),
        'glareshield_island_report': results.get('glareshield_island_report', {}),
        'mesh_face_counts': mesh_face_counts,
        'object_summaries': results.get('object_summaries', {}),
        'island_summaries': results.get('island_summaries', {}),
        'settings': settings or {},
    }

    arrays_to_save = {
        '_meta_json': np.array([json.dumps(meta)]),
    }

    for m_name, m_data in results['mesh_arrays'].items():
        safe_name = m_name.replace('/', '_').replace('\\', '_')
        arrays_to_save[f"{safe_name}__vis_omega"] = m_data['vis_omega'].astype(np.float32)
        arrays_to_save[f"{safe_name}__unocc_omega"] = m_data['unocc_omega'].astype(np.float32)
        arrays_to_save[f"{safe_name}__face_scores"] = m_data['face_scores'].astype(np.float32)
        arrays_to_save[f"{safe_name}__face_undetermined"] = m_data['face_undetermined'].astype(bool)
        arrays_to_save[f"{safe_name}__face_never_seen"] = m_data['face_never_seen'].astype(bool)
        arrays_to_save[f"{safe_name}__face_patch_size_px"] = m_data['face_patch_size_px'].astype(np.float32)

    with open(vis_path, 'wb') as f:
        np.savez_compressed(f, **arrays_to_save)
    return vis_path


def load_visibility_file(vis_path, scene_meshes=None):
    """Load `.visibility` file and verify staleness against scene meshes."""
    data = np.load(vis_path)
    meta = json.loads(str(data['_meta_json'][0]))

    stale_meshes = []
    if scene_meshes:
        saved_counts = meta.get('mesh_face_counts', {})
        for m_name, saved_n_faces in saved_counts.items():
            me = scene_meshes.get(m_name)
            if me is None or len(me.polygons) != saved_n_faces:
                stale_meshes.append(m_name)

    return meta, data, stale_meshes


# ---------------------------------------------------------------------------
# Heatmap RGBA Color Mapping (0.0 red, 0.5 neutral, 1.0 blue)
# ---------------------------------------------------------------------------

def compute_heatmap_colors(scores, undetermined_mask, never_seen_mask, alpha=0.75):
    """Map visibility score in [0.0, 1.0] to RGBA colors.

    - Undetermined: Cyan (0.0, 0.85, 0.85, alpha)
    - Never Seen (0.0): Magenta (1.0, 0.0, 1.0, alpha)
    - Seen (0.0, 0.5]: Red (0.95, 0.15, 0.15) to Neutral Grey (0.92, 0.92, 0.92)
    - Seen [0.5, 1.0]: Neutral Grey (0.92, 0.92, 0.92) to Blue (0.10, 0.35, 0.95)
    """
    n = len(scores)
    colors = np.empty((n, 4), dtype=np.float32)

    c_cyan = np.array([0.0, 0.85, 0.85, alpha], dtype=np.float32)
    c_mag = np.array([1.0, 0.0, 1.0, alpha], dtype=np.float32)
    c_red = np.array([0.95, 0.15, 0.15, alpha], dtype=np.float32)
    c_neu = np.array([0.92, 0.92, 0.92, alpha], dtype=np.float32)
    c_blue = np.array([0.10, 0.35, 0.95, alpha], dtype=np.float32)

    # 1. Never seen
    colors[never_seen_mask] = c_mag

    # 2. Undetermined
    colors[undetermined_mask] = c_cyan

    # 3. Measurable seen
    seen = (~never_seen_mask) & (~undetermined_mask)
    if np.any(seen):
        s_vals = scores[seen]
        seen_idx = np.flatnonzero(seen)

        low_mask = (s_vals <= 0.5)
        if np.any(low_mask):
            l_idx = seen_idx[low_mask]
            t = np.clip(s_vals[low_mask] / 0.5, 0.0, 1.0)[:, None]
            colors[l_idx] = (1.0 - t) * c_red + t * c_neu

        high_mask = (s_vals > 0.5)
        if np.any(high_mask):
            h_idx = seen_idx[high_mask]
            t = np.clip((s_vals[high_mask] - 0.5) / 0.5, 0.0, 1.0)[:, None]
            colors[h_idx] = (1.0 - t) * c_neu + t * c_blue

    return colors


# ---------------------------------------------------------------------------
# Step-by-Step Analysis Runner (Supports synchronous & modal execution)
# ---------------------------------------------------------------------------

class VisibilityAnalyzer:
    """Visibility analysis coordinator supporting one view per step (Decision 81)."""

    def __init__(
        self,
        scene,
        view_layer,
        cameras,
        anim_states=(0.0, 0.25, 0.5, 0.75, 1.0),
        cube_res=1024,
        frustum_res=(2560, 1440),
        floor=0.2,
        falloff=1.0,
        min_px_threshold=10.0,
        blend_path=None,
    ):
        if not cameras:
            raise ValueError("No reference cameras specified (Decision 80).")

        self.scene = scene
        self.view_layer = view_layer
        self.cameras = cameras
        self.anim_states = tuple(float(s) for s in anim_states)
        self.cube_res = cube_res
        self.frustum_res = frustum_res
        self.floor = floor
        self.falloff = falloff
        self.min_px_threshold = min_px_threshold
        self.blend_path = blend_path or (scene.fss_visibility.cameras[0].camera_name if hasattr(scene, 'fss_visibility') else "")

        # State tracking
        self.shader = None
        self.off_cube = None
        self.off_frustum = None
        self.anim_ctrl = None
        self.mesh_meta = None
        self.mesh_arrays = None
        self.view_configs = []
        self.current_step = 0
        self.current_state_idx = -1
        self.batches = None
        self.eval_poly_info = None
        self.tri_geom = None
        self.max_id = 0
        self.batch_op = None
        self.batch_dec = None
        self.t_start = 0.0
        self.state_timings = {}
        self._state_t0 = 0.0
        self.prepared = False
        self.cleaned_up = False

    def prepare(self):
        """Initialize shaders, attributes, instances and sum arrays."""
        if gpu is None:
            raise RuntimeError("GPU module not available.")

        gpu.init()
        self.shader = get_id_shader()
        add_orig_face_index_attributes()

        self.mesh_meta = discover_mesh_instances(self.view_layer)

        # Build view list: camera x animation state
        self.view_configs = []
        for state_idx, state_val in enumerate(self.anim_states):
            for cam in self.cameras:
                self.view_configs.append({
                    'state_idx': state_idx,
                    'state_val': state_val,
                    'camera': cam['name'],
                    'cam_dict': cam,
                    'floor': self.floor,
                    'falloff': self.falloff,
                })

        N_views = len(self.view_configs)
        self.mesh_arrays = {}
        for m_name, meta in self.mesh_meta.items():
            N_inst = max(len(meta['instances']), 1)
            N_faces = meta['n_orig_faces']
            self.mesh_arrays[m_name] = {
                'vis_omega': np.zeros((N_views, N_inst, N_faces), dtype=np.float32),
                'unocc_omega': np.zeros((N_views, N_inst, N_faces), dtype=np.float32),
                'area': meta['orig_areas'],
                'island_ids': meta['island_ids'],
            }

        self.off_cube = gpu.types.GPUOffScreen(self.cube_res, self.cube_res)
        self.off_frustum = gpu.types.GPUOffScreen(self.frustum_res[0], self.frustum_res[1])
        self.anim_ctrl = AnimationStateController(self.scene)

        self.current_step = 0
        self.current_state_idx = -1
        self.t_start = time.perf_counter()
        self.prepared = True

    def total_steps(self):
        return len(self.view_configs)

    def is_finished(self):
        return self.current_step >= len(self.view_configs)

    def execute_next_step(self):
        """Execute one view pass (one camera at one animation state)."""
        if not self.prepared:
            self.prepare()

        if self.is_finished():
            return None

        view_cfg = self.view_configs[self.current_step]
        state_idx = view_cfg['state_idx']
        state_val = view_cfg['state_val']
        cam = view_cfg['cam_dict']

        # Transition to new animation state if needed
        if state_idx != self.current_state_idx:
            if self.current_state_idx >= 0:
                pct_prev = f"{int(self.anim_states[self.current_state_idx] * 100)}%"
                self.state_timings[pct_prev] = time.perf_counter() - self._state_t0

            self.current_state_idx = state_idx
            self._state_t0 = time.perf_counter()
            self.anim_ctrl.apply_percentage_state(state_val)

            dg = bpy.context.evaluated_depsgraph_get()
            self.batches, self.eval_poly_info, self.tri_geom, self.max_id = extract_scene_geometry(
                dg, self.view_layer, self.mesh_meta
            )

            self.batch_op = None
            if len(self.batches['opaque_pos']) > 0:
                b = batch_for_shader(self.shader, 'TRIS', {
                    'pos': self.batches['opaque_pos'],
                    'face_id': self.batches['opaque_ids']
                })
                self.batch_op = BatchWrapper(b, len(self.batches['opaque_pos']) // 3)

            self.batch_dec = None
            if len(self.batches['decal_pos']) > 0:
                b = batch_for_shader(self.shader, 'TRIS', {
                    'pos': self.batches['decal_pos'],
                    'face_id': self.batches['decal_ids']
                })
                self.batch_dec = BatchWrapper(b, len(self.batches['decal_pos']) // 3)

        cam_name = cam['name']
        cam_type = cam['type']
        cam_pos = cam['pos']
        cam_fwd = cam.get('forward', Vector((0, -1, 0)))

        # 1. Unoccluded solid angle from camera position
        if len(self.tri_geom['V0']) > 0:
            tri_omega = batch_triangle_solid_angle(
                cam_pos, self.tri_geom['V0'], self.tri_geom['V1'], self.tri_geom['V2']
            )
            eval_unocc = np.bincount(
                self.tri_geom['tri_ids'], weights=tri_omega, minlength=self.max_id + 1
            )
        else:
            eval_unocc = np.zeros(self.max_id + 1, dtype=np.float32)

        eval_vis = np.zeros(self.max_id + 1, dtype=np.float64)

        # Near and far clipping planes from scene extent (Requirement 4)
        near_plane, far_plane = compute_scene_extent(self.view_layer, cam_pos)

        # 2. Render view
        if cam_type == 'LOOK_AROUND':
            faces = cubemap_face_matrices(cam_pos, cam_fwd, near=near_plane, far=far_plane)
            face_weights = precompute_cubemap_weights(
                faces, cam_fwd, cube_res=self.cube_res, floor=self.floor, falloff=self.falloff
            )
            for face_name, v_mat, p_mat in faces:
                mvp = p_mat @ v_mat
                w_map = face_weights[face_name]
                vis_counts = render_camera_view(
                    self.off_cube, self.shader, self.batch_op, self.batch_dec, mvp, w_map, self.max_id
                )
                eval_vis += vis_counts

        elif cam_type == 'FIXED_VIEW':
            cam_obj = bpy.data.objects.get(cam.get('obj_name', cam_name))
            if cam_obj:
                dg = bpy.context.evaluated_depsgraph_get()
                p_mat = cam_obj.calc_matrix_camera(dg, x=self.frustum_res[0], y=self.frustum_res[1])
                v_mat = cam_obj.matrix_world.inverted()
                mvp = p_mat @ v_mat
                w_map = precompute_frustum_weights(cam_obj, self.frustum_res)
                vis_counts = render_camera_view(
                    self.off_frustum, self.shader, self.batch_op, self.batch_dec, mvp, w_map, self.max_id
                )
                eval_vis += vis_counts

        # 3. Accumulate sums into mesh_arrays
        for eid, (m_name, inst_idx, orig_idx) in self.eval_poly_info.items():
            v_vis = eval_vis[eid]
            v_unocc = eval_unocc[eid]
            self.mesh_arrays[m_name]['vis_omega'][self.current_step, inst_idx, orig_idx] += v_vis
            self.mesh_arrays[m_name]['unocc_omega'][self.current_step, inst_idx, orig_idx] += v_unocc

        step_info = {
            'step': self.current_step + 1,
            'total_steps': len(self.view_configs),
            'camera': cam_name,
            'mode': cam_type,
            'state_pct': state_val,
        }

        self.current_step += 1
        return step_info

    def finalize(self):
        """Compute patch expansion, undetermined resolution, and build results dict."""
        if self.current_state_idx >= 0:
            pct_last = f"{int(self.anim_states[self.current_state_idx] * 100)}%"
            self.state_timings[pct_last] = time.perf_counter() - self._state_t0

        total_time = time.perf_counter() - self.t_start

        patch_res = compute_patch_scores_and_groups(
            self.mesh_meta, self.mesh_arrays,
            min_px_threshold=self.min_px_threshold,
            ref_cube_res=self.cube_res,
            scene=self.scene,
        )

        all_face_scores = []
        all_face_areas = []
        tot_nv_faces = 0
        tot_nv_area = 0.0
        tot_udet_faces = 0
        tot_udet_area = 0.0

        for m_name, meta in self.mesh_meta.items():
            m_data = self.mesh_arrays[m_name]
            f_sc = m_data['face_scores']
            f_ar = meta['orig_areas']
            f_nv = m_data['face_never_seen']
            f_udet = m_data['face_undetermined']

            all_face_scores.append(f_sc)
            all_face_areas.append(f_ar)

            tot_nv_faces += int(np.count_nonzero(f_nv))
            tot_nv_area += float(np.sum(f_ar[f_nv]))
            tot_udet_faces += int(np.count_nonzero(f_udet))
            tot_udet_area += float(np.sum(f_ar[f_udet]))

        concat_scores = np.concatenate(all_face_scores) if all_face_scores else np.zeros(0, dtype=np.float32)
        concat_areas = np.concatenate(all_face_areas) if all_face_areas else np.zeros(0, dtype=np.float32)

        face_p50 = weighted_percentile(concat_scores, concat_areas, 0.50)
        face_p90 = weighted_percentile(concat_scores, concat_areas, 0.90)
        face_p95 = weighted_percentile(concat_scores, concat_areas, 0.95)

        isl_sums = patch_res['island_summaries']
        isl_scores = np.array([isl['score'] for isl in isl_sums.values()], dtype=np.float32)
        isl_areas = np.array([isl['area_m2'] for isl in isl_sums.values()], dtype=np.float32)

        isl_p50 = weighted_percentile(isl_scores, isl_areas, 0.50)
        isl_p90 = weighted_percentile(isl_scores, isl_areas, 0.90)
        isl_p95 = weighted_percentile(isl_scores, isl_areas, 0.95)

        obj_sums = patch_res['object_summaries']
        nv_objs = sum(1 for o in obj_sums.values() if o['never_seen'])
        undet_objs = sum(1 for o in obj_sums.values() if o['undetermined'])
        nv_isls = sum(1 for isl in isl_sums.values() if isl['never_seen'])

        # Check glareshield island if present in scene
        glareshield_rep = {}
        for k, v in isl_sums.items():
            if v['mesh_name'].startswith('C3_001.018') and v['island_id'] == 4:
                glareshield_rep = {
                    'key': k,
                    'score': v['score'],
                    'r4_avg': v['r4_avg'],
                    'seen_share': v['seen_area_share'],
                    'area_m2': v['area_m2'],
                    'n_faces': v['n_faces'],
                }
                break

        results = {
            'blend_file': str(self.blend_path),
            'total_time_s': total_time,
            'patch_expansion_time_s': patch_res['patch_expansion_time_s'],
            'state_timings': self.state_timings,
            'views': [
                {'camera': v['camera'], 'type': v['cam_dict']['type'], 'state': v['state_val']}
                for v in self.view_configs
            ],
            'ref_cube_res': self.cube_res,
            'min_px_threshold': self.min_px_threshold,
            'total_faces': len(concat_scores),
            'total_surface_area_m2': float(np.sum(concat_areas)),
            'total_objects': len(obj_sums),
            'never_seen_objects_count': nv_objs,
            'undetermined_objects_count': undet_objs,
            'total_islands': len(isl_sums),
            'never_seen_islands_count': nv_isls,
            'total_never_seen_faces': tot_nv_faces,
            'total_never_seen_face_area_m2': tot_nv_area,
            'total_undetermined_faces': tot_udet_faces,
            'total_undetermined_face_area_m2': tot_udet_area,
            'face_percentiles': {'p50': face_p50, 'p90': face_p90, 'p95': face_p95},
            'island_percentiles': {'p50': isl_p50, 'p90': isl_p90, 'p95': isl_p95},
            'resolved_counts': patch_res['resolved_counts'],
            'glareshield_island_report': glareshield_rep,
            'mesh_meta': self.mesh_meta,
            'mesh_arrays': self.mesh_arrays,
            'object_summaries': obj_sums,
            'island_summaries': isl_sums,
        }
        return results

    def cleanup(self):
        """Restore scene state, frame, actions and remove temporary attributes."""
        if self.cleaned_up:
            return
        self.cleaned_up = True

        if self.anim_ctrl is not None:
            try:
                self.anim_ctrl.restore()
            except Exception:
                pass
            self.anim_ctrl = None

        try:
            remove_orig_face_index_attributes()
        except Exception:
            pass

        if self.off_cube is not None:
            try:
                self.off_cube.free()
            except Exception:
                pass
            self.off_cube = None

        if self.off_frustum is not None:
            try:
                self.off_frustum.free()
            except Exception:
                pass
            self.off_frustum = None


def analyze_visibility(
    blend_path,
    cameras=None,
    anim_states=(0.0, 0.25, 0.5, 0.75, 1.0),
    cube_res=1024,
    frustum_res=(2560, 1440),
    floor=0.2,
    falloff=1.0,
    min_px_threshold=10.0,
    scene=None,
    view_layer=None,
):
    """Synchronous execution of visibility analysis returning complete results dict."""
    scene = scene or bpy.context.scene
    view_layer = view_layer or bpy.context.view_layer

    analyzer = VisibilityAnalyzer(
        scene=scene,
        view_layer=view_layer,
        cameras=cameras,
        anim_states=anim_states,
        cube_res=cube_res,
        frustum_res=frustum_res,
        floor=floor,
        falloff=falloff,
        min_px_threshold=min_px_threshold,
        blend_path=blend_path,
    )

    analyzer.prepare()
    try:
        while not analyzer.is_finished():
            analyzer.execute_next_step()
        results = analyzer.finalize()
    finally:
        analyzer.cleanup()

    return results


# ---------------------------------------------------------------------------
# Packer Interface Function (Requirement 7)
# ---------------------------------------------------------------------------

def get_object_visibility(obj, uv_name=None, vis_path=None):
    """For the packer: returns each island's value (Decision 82) and each face's score with stale status.

    Returns dict containing:
    - 'stale': bool
    - 'mesh_name': str
    - 'object_name': str
    - 'object_score': float
    - 'never_seen': bool
    - 'undetermined': bool
    - 'island_values': dict {island_id: float score}
    - 'face_scores': np.ndarray of float32 face scores (or None if stale/missing)
    - 'face_undetermined': np.ndarray of bool (or None)
    - 'face_never_seen': np.ndarray of bool (or None)
    """
    if obj is None or obj.type != 'MESH' or not obj.data:
        return {'stale': True, 'reason': 'NOT_A_MESH', 'island_values': {}, 'face_scores': None}

    me = obj.data
    m_name = me.name
    n_faces = len(me.polygons)

    if vis_path is None:
        blend_path = bpy.data.filepath
        if not blend_path:
            return {'stale': True, 'reason': 'UNSAVED_BLEND', 'island_values': {}, 'face_scores': None}
        vis_path = Path(blend_path).with_suffix('.visibility')
    else:
        vis_path = Path(vis_path)

    if not vis_path.exists():
        return {'stale': True, 'reason': 'FILE_NOT_FOUND', 'island_values': {}, 'face_scores': None}

    try:
        meta, data, stale_meshes = load_visibility_file(vis_path, scene_meshes=bpy.data.meshes)
    except Exception as e:
        return {'stale': True, 'reason': f'LOAD_ERROR: {e}', 'island_values': {}, 'face_scores': None}

    if m_name in stale_meshes:
        return {'stale': True, 'reason': 'MESH_STALE', 'island_values': {}, 'face_scores': None}

    safe_name = m_name.replace('/', '_').replace('\\', '_')
    sc_key = f"{safe_name}__face_scores"
    if sc_key not in data:
        return {'stale': True, 'reason': 'MESH_NOT_IN_FILE', 'island_values': {}, 'face_scores': None}

    face_scores = data[sc_key]
    if len(face_scores) != n_faces:
        return {'stale': True, 'reason': 'FACE_COUNT_MISMATCH', 'island_values': {}, 'face_scores': None}

    face_undetermined = data.get(f"{safe_name}__face_undetermined", np.zeros(n_faces, dtype=bool))
    face_never_seen = data.get(f"{safe_name}__face_never_seen", np.zeros(n_faces, dtype=bool))
    vis_omega = data.get(f"{safe_name}__vis_omega")
    unocc_omega = data.get(f"{safe_name}__unocc_omega")

    # Extract UV islands under requested or active UV map
    island_ids = extract_mesh_uv_islands(me, uv_name=uv_name)
    unique_isls = np.unique(island_ids)

    # Face areas in object/world space
    V_base = np.empty((len(me.vertices), 3), dtype=np.float32)
    me.vertices.foreach_get('co', V_base.ravel())
    M_base = np.array(obj.matrix_world, dtype=np.float32)
    V_world_base = V_base @ M_base[:3, :3].T + M_base[:3, 3]

    orig_areas = np.zeros(n_faces, dtype=np.float32)
    for i, p in enumerate(me.polygons):
        p_verts = [V_world_base[vi] for vi in p.vertices]
        if len(p_verts) == 3:
            e1 = p_verts[1] - p_verts[0]
            e2 = p_verts[2] - p_verts[0]
            orig_areas[i] = 0.5 * np.linalg.norm(np.cross(e1, e2))
        elif len(p_verts) >= 4:
            poly_area = 0.0
            for vi in range(1, len(p_verts) - 1):
                e1 = p_verts[vi] - p_verts[0]
                e2 = p_verts[vi + 1] - p_verts[0]
                poly_area += 0.5 * np.linalg.norm(np.cross(e1, e2))
            orig_areas[i] = poly_area

    ref_cube_res = meta.get('ref_cube_res', 1024)
    min_px_thresh = meta.get('min_px_threshold', 10.0)
    d_omega_px = 4.0 / (ref_cube_res * ref_cube_res)
    omega_threshold = min_px_thresh * d_omega_px

    island_values = {}
    for isl_id in unique_isls:
        isl_mask = (island_ids == isl_id)
        isl_faces = np.flatnonzero(isl_mask)
        f_sc = face_scores[isl_faces]
        f_ar = orig_areas[isl_faces]

        seen_mask = (f_sc > 0.0)
        seen_area = float(np.sum(f_ar[seen_mask]))
        seen_faces = isl_faces[seen_mask]

        if seen_area > 0.0:
            r4_avg = float(np.sum(f_sc[seen_mask] * f_ar[seen_mask]) / seen_area)
            if unocc_omega is not None and vis_omega is not None:
                seen_unocc = np.sum(unocc_omega[:, :, seen_faces], axis=-1)
                max_seen_unocc = float(np.max(seen_unocc))
                if max_seen_unocc >= omega_threshold:
                    seen_vis = np.sum(vis_omega[:, :, seen_faces], axis=-1)
                    valid = seen_unocc > 1e-12
                    ratio = np.where(valid, np.clip(seen_vis / np.maximum(seen_unocc, 1e-12), 0.0, 1.0), 0.0)
                    isl_val = float(np.max(ratio))
                else:
                    isl_val = r4_avg
            else:
                isl_val = r4_avg
        else:
            isl_val = 0.0

        island_values[int(isl_id)] = isl_val

    obj_meta = meta.get('object_summaries', {}).get(obj.name, {})
    obj_score = obj_meta.get('score', 1.0)
    never_seen = obj_meta.get('never_seen', False)
    undetermined = obj_meta.get('undetermined', False)

    return {
        'stale': False,
        'mesh_name': m_name,
        'object_name': obj.name,
        'object_score': obj_score,
        'never_seen': never_seen,
        'undetermined': undetermined,
        'island_values': island_values,
        'face_scores': face_scores,
        'face_undetermined': face_undetermined,
        'face_never_seen': face_never_seen,
    }
