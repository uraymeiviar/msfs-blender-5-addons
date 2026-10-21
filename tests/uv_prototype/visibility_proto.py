"""Visibility-based Texel Demand Prototype for Blender 5.2 (Round 5).

Implements Session 75 Design and Hand-Off (Decisions 79, 80, 81):
1. Cameras (Decision 80): reference cameras come strictly from CLI (--cameras NAME[:MODE],...).
   No fallback cameras; stops with error if none given.
2. Face Adjacency & Connected Components: original mesh edges determine adjacency and
   connected pieces for visible faces; invisible material classes excluded.
3. Per-Face Patch Scores (Decision 79): unoccluded solid angle threshold is 10 reference pixels
   (ref_cube_res 1024). Faces >= threshold use their own patch; smaller faces grow rings of
   neighbours until the patch reaches the threshold. Scores = max over views/instances of patch
   visible over unoccluded sums.
4. Undetermined Pieces: pieces smaller than threshold as a whole take the score of the next
   measurable group upwards (object, then parent subtree, up hierarchy), else neutral 1.0.
   Never reported as never-seen.
5. Island Value (Decision 79): area-weighted average of seen faces' scores (score > 0).
   Hidden faces left out so partly hidden islands keep the density of their visible part.
   Islands with no seen faces are never seen (0.0).
6. Staleness Check (Session 74 Finding 4): compares mesh face counts on load and reports stale meshes.
7. Resolution Check (1024 vs 4096): area-weighted mean difference and correlation for faces
   and islands bucketed by size; undetermined-only islands reported as a separate row.
8. Cockpit Reporting: detailed face/island/object metrics, undetermined breakdown, top/bottom 20
   measurable objects (>= 10 px), and glareshield island report (CockpitShell.010 island 4).
9. Images: colored by per-face score; undetermined faces in cyan (0.0, 0.85, 0.85),
   never seen in magenta (1.0, 0.0, 1.0), visible in graded blue-grey-red ramp.
10. Synthetic Validation: 15 test cases covering all requirements.
"""

import os
import sys
import math
import time
import json
import re
from pathlib import Path
import numpy as np

import bpy
from mathutils import Vector, Matrix

try:
    import gpu
    from gpu_extras.batch import batch_for_shader
except ImportError:
    gpu = None
    batch_for_shader = None

ORIG_FACE_ATTR_NAME = '_fss_orig_face_idx'


# ---------------------------------------------------------------------------
# Material Classification (Decision 77)
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
# Attribute Lifecycle (Finding 3)
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
# Camera & Projection Math (Decision 80)
# ---------------------------------------------------------------------------

def look_at(eye, target, up):
    """OpenGL view matrix looking from eye towards target with up vector."""
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


def perspective_proj(fov_rad, aspect, near, far):
    """OpenGL perspective projection matrix."""
    f = 1.0 / math.tan(fov_rad / 2.0)
    return Matrix((
        (f / aspect, 0, 0, 0),
        (0, f, 0, 0),
        (0, 0, (far + near) / (near - far), 2 * far * near / (near - far)),
        (0, 0, -1, 0)
    ))


def get_camera_forward(cam_obj):
    """Extract default forward vector in world coordinates from a Blender camera."""
    if cam_obj:
        fwd = cam_obj.matrix_world.to_3x3() @ Vector((0, 0, -1))
        if fwd.length > 1e-6:
            return fwd.normalized()
    return Vector((0, -1, 0))


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
    """Precompute weighted differential solid angle maps for all 6 cube faces."""
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


def parse_cameras_arg(cam_str):
    """Parse --cameras string 'NAME[:MODE],...' into list of camera configs (Decision 80)."""
    if not cam_str or not cam_str.strip():
        raise ValueError(
            "No reference cameras specified. Visibility analysis requires artist-defined "
            "cameras via --cameras NAME[:MODE],... (Decision 80)"
        )

    tokens = [c.strip() for c in cam_str.split(',') if c.strip()]
    if not tokens:
        raise ValueError(
            "No reference cameras specified. Visibility analysis requires artist-defined "
            "cameras via --cameras NAME[:MODE],... (Decision 80)"
        )

    cameras = []
    for tok in tokens:
        if ':' in tok:
            name, mode = tok.split(':', 1)
            mode = mode.strip().upper()
        else:
            name = tok.strip()
            mode = 'LOOK_AROUND'

        if mode not in {'LOOK_AROUND', 'FIXED_VIEW'}:
            raise ValueError(f"Invalid camera mode '{mode}' for camera '{name}'. Must be LOOK_AROUND or FIXED_VIEW.")

        cam_obj = bpy.data.objects.get(name)
        if cam_obj is None:
            raise ValueError(f"Camera object '{name}' not found in scene.")

        cameras.append({
            'name': cam_obj.name,
            'type': mode,
            'pos': cam_obj.matrix_world.translation.copy(),
            'forward': get_camera_forward(cam_obj),
            'obj_name': cam_obj.name,
        })

    return cameras


# ---------------------------------------------------------------------------
# Vectorized Analytical Solid Angle (Oosterom & Strackee 1983)
# ---------------------------------------------------------------------------

def batch_triangle_solid_angle(eye, V0, V1, V2):
    """Vectorized calculation of spherical solid angle for a batch of triangles."""
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
_heatmap_render_shader = None


def get_id_shader():
    """Flat face-ID shader encoding integer ID into RGB bytes."""
    global _id_shader
    if _id_shader is None:
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


def get_heatmap_render_shader():
    """Surface shader with headlight shading and heatmap color."""
    global _heatmap_render_shader
    if _heatmap_render_shader is None:
        info = gpu.types.GPUShaderCreateInfo()
        info.push_constant('MAT4', 'mvp')
        info.push_constant('MAT4', 'normal_matrix')
        info.vertex_in(0, 'VEC3', 'pos')
        info.vertex_in(1, 'VEC3', 'nor')
        info.vertex_in(2, 'VEC4', 'color')
        iface = gpu.types.GPUStageInterfaceInfo('heat_render_iface')
        iface.smooth('VEC4', 'v_color')
        iface.smooth('VEC3', 'v_nor')
        info.vertex_out(iface)
        info.fragment_out(0, 'VEC4', 'FragColor')
        info.vertex_source('''
            void main() {
                gl_Position = mvp * vec4(pos, 1.0);
                v_nor = (normal_matrix * vec4(nor, 0.0)).xyz;
                v_color = color;
            }
        ''')
        info.fragment_source('''
            void main() {
                vec3 n = normalize(v_nor);
                float shade = 0.70 + 0.30 * abs(n.z);
                FragColor = vec4(v_color.rgb * shade, 1.0);
            }
        ''')
        _heatmap_render_shader = gpu.shader.create_from_info(info)
    return _heatmap_render_shader


# ---------------------------------------------------------------------------
# Mesh Topology, Face Adjacency & UV Islands (Step 2 & Decision 79)
# ---------------------------------------------------------------------------

def extract_mesh_uv_islands(me):
    """Extract UV island ID for each polygon of base mesh."""
    n_polys = len(me.polygons)
    if n_polys == 0:
        return np.zeros(0, dtype=np.int32)

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
    """Compute face adjacency and connected components from original mesh edges (Step 2).
    
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
# Instance Discovery & Evaluated Scene Extraction (Steps 1 & 2)
# ---------------------------------------------------------------------------

def discover_mesh_instances(view_layer):
    """Scan scene for visible mesh objects and assign instances per mesh.

    Returns:
    - mesh_meta: dict mesh_name -> meta dict containing:
        'n_orig_faces': int,
        'orig_areas': np.ndarray,
        'island_ids': np.ndarray,
        'adjacency': list of lists,
        'face_to_comp': np.ndarray,
        'components': list of np.ndarray,
        'instances': list of dicts [{'obj_name': str, 'copy_idx': int, 'inst_idx': int}]
        'instance_map': dict (obj_name, copy_idx) -> inst_idx
    """
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
                continue  # Completely excluded from all batches and analytical triangles!

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
# Animation State Controller (Decision 69)
# ---------------------------------------------------------------------------

class AnimationStateController:
    """Manages normalized action/NLA percentage states across scene objects."""

    def __init__(self):
        self.original_states = []
        self.temp_tracks = []
        self._setup()

    def _setup(self):
        for o in bpy.context.scene.objects:
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
            o = entry['object']
            f_min = entry['frame_start']
            f_max = entry['frame_end']
            target_frame = f_min + pct_norm * (f_max - f_min)
            bpy.context.scene.frame_set(int(round(target_frame)))

    def restore(self):
        bpy.context.scene.frame_set(1)


# ---------------------------------------------------------------------------
# Two-Pass Offscreen Render & Solid Angle Accumulation (Decisions 72 & 77)
# ---------------------------------------------------------------------------

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


class BatchWrapper:
    def __init__(self, batch, n_tris):
        self.batch = batch
        self.n_tris = n_tris

    def draw(self, shader):
        if self.n_tris > 0 and self.batch is not None:
            self.batch.draw(shader)

    def has_triangles(self):
        return self.n_tris > 0


# ---------------------------------------------------------------------------
# Per-Face Patch Scoring & Hierarchy Resolution Engine (Decisions 79 & 81)
# ---------------------------------------------------------------------------

def compute_patch_scores_and_groups(mesh_meta, mesh_arrays, min_px_threshold=10.0, ref_cube_res=1024):
    """Compute per-face scores from patches, resolve undetermined pieces, and compute island values (Decision 79)."""
    t_start = time.perf_counter()
    d_omega_px = 4.0 / (ref_cube_res * ref_cube_res)
    omega_threshold = min_px_threshold * d_omega_px

    # Hierarchy maps for scene objects
    children_map = {}
    for o in bpy.context.scene.objects:
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
        # max_u == 0.0 means the piece is completely unseen/facing away in all views (never seen).
        # 0.0 < max_u < omega_threshold means the piece is in view but too small to measure reliably (undetermined).
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
                    # Face alone reaches threshold
                    valid = f_unocc > 1e-12
                    f_vis = vis_arr[:, :, f]
                    ratio = np.where(valid, np.clip(f_vis / np.maximum(f_unocc, 1e-12), 0.0, 1.0), 0.0)
                    face_scores[f] = float(np.max(ratio))
                    face_never_seen[f] = bool(np.max(f_vis) == 0.0)
                    face_undetermined[f] = False
                    face_patch_size_px[f] = f_max_u / d_omega_px
                else:
                    # Grow patch ring by ring
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

    # 2. Hierarchy Fallback Resolution for Undetermined Pieces (Step 4)
    def resolve_object_score(obj):
        m_name = obj.data.name
        inst_idx = mesh_meta[m_name]['instance_map'].get((obj.name, 0), 0)
        unocc_o = np.sum(mesh_arrays[m_name]['unocc_omega'][:, inst_idx, :], axis=-1)
        if float(np.max(unocc_o)) >= omega_threshold:
            vis_o = np.sum(mesh_arrays[m_name]['vis_omega'][:, inst_idx, :], axis=-1)
            valid = unocc_o > 1e-12
            ratio = np.where(valid, np.clip(vis_o / np.maximum(unocc_o, 1e-12), 0.0, 1.0), 0.0)
            return float(np.max(ratio)), 'OBJECT', float(np.max(unocc_o)) / d_omega_px

        # Walk up parent hierarchy
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

    # Resolve undetermined faces on meshes
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

        # Determine inherited score across instances of this mesh
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

            # Assign inherited score to undetermined faces
            face_scores[face_undetermined] = best_inh_score
            face_never_seen[face_undetermined] = False

            # Tally resolution counts
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

            # Unoccluded size of island
            f_unocc = np.sum(m_data['unocc_omega'][:, :, isl_faces], axis=-1)
            isl_size_px = float(np.max(f_unocc)) / d_omega_px
            tot_area = float(np.sum(f_ar))

            # Seen faces: score > 0 (includes undetermined faces with inherited score)
            seen_mask = (f_sc > 0.0)
            seen_area = float(np.sum(f_ar[seen_mask]))
            seen_faces = isl_faces[seen_mask]

            if seen_area > 0.0:
                never_seen = False
                seen_share = seen_area / max(tot_area, 1e-12)
                is_undet_only = bool(np.all(f_udet[seen_mask]))
                r4_avg = float(np.sum(f_sc[seen_mask] * f_ar[seen_mask]) / seen_area)

                # Decision 82: sums over seen faces per view and instance
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
                # Undetermined object!
                o_score, o_lvl, _ = resolve_object_score(o_obj) if o_obj else (1.0, 'FALLBACK_1.0', 0.0)
                o_r4_avg = o_score
                o_never_seen = False
                o_undetermined = True
                o_seen_share = 1.0
                resolved_counts[o_lvl]['objects'] += 1
            elif o_size_px == 0.0:
                # Completely unseen object (e.g. facing away in all views)
                o_score = 0.0
                o_r4_avg = 0.0
                o_never_seen = True
                o_undetermined = False
                o_seen_share = 0.0
            else:
                # Measurable object!
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


# ---------------------------------------------------------------------------
# Core Analysis Engine (Round 5)
# ---------------------------------------------------------------------------

def analyze_visibility(
    blend_path,
    cameras=None,
    anim_states=(0.0, 0.5, 1.0),
    cube_res=1024,
    frustum_res=(2560, 1440),
    floor=0.2,
    falloff=1.0,
    min_px_threshold=10.0,
):
    """Execute complete visibility analysis with per-face sums and patch scoring (Round 5)."""
    if not cameras:
        raise ValueError(
            "No reference cameras specified. Visibility analysis requires artist-defined "
            "cameras via --cameras NAME[:MODE],... (Decision 80)"
        )

    gpu.init()
    shader = get_id_shader()

    # Discover instances & metadata
    add_orig_face_index_attributes()

    try:
        mesh_meta = discover_mesh_instances(bpy.context.view_layer)

        # Build view list: camera x animation state
        view_configs = []
        for state_val in anim_states:
            for cam in cameras:
                view_configs.append({
                    'camera': cam['name'],
                    'cam_dict': cam,
                    'state': float(state_val),
                    'floor': floor,
                    'falloff': falloff,
                })

        N_views = len(view_configs)

        # Allocate per-mesh sum arrays: (N_views, N_instances, N_faces)
        mesh_arrays = {}
        for m_name, meta in mesh_meta.items():
            N_inst = max(len(meta['instances']), 1)
            N_faces = meta['n_orig_faces']
            mesh_arrays[m_name] = {
                'vis_omega': np.zeros((N_views, N_inst, N_faces), dtype=np.float32),
                'unocc_omega': np.zeros((N_views, N_inst, N_faces), dtype=np.float32),
                'area': meta['orig_areas'],
                'island_ids': meta['island_ids'],
            }

        t_start = time.perf_counter()
        state_timings = {}

        off_cube = gpu.types.GPUOffScreen(cube_res, cube_res)
        off_frustum = gpu.types.GPUOffScreen(frustum_res[0], frustum_res[1])
        anim_ctrl = AnimationStateController()

        try:
            view_idx = 0
            for state_val in anim_states:
                t_s0 = time.perf_counter()
                pct_label = f"{int(state_val * 100 if state_val <= 1.0 else state_val)}%"
                anim_ctrl.apply_percentage_state(state_val)

                dg = bpy.context.evaluated_depsgraph_get()
                batches, eval_poly_info, tri_geom, max_id = extract_scene_geometry(
                    dg, bpy.context.view_layer, mesh_meta
                )

                batch_op = None
                if len(batches['opaque_pos']) > 0:
                    b = batch_for_shader(shader, 'TRIS', {
                        'pos': batches['opaque_pos'],
                        'face_id': batches['opaque_ids']
                    })
                    batch_op = BatchWrapper(b, len(batches['opaque_pos']) // 3)

                batch_dec = None
                if len(batches['decal_pos']) > 0:
                    b = batch_for_shader(shader, 'TRIS', {
                        'pos': batches['decal_pos'],
                        'face_id': batches['decal_ids']
                    })
                    batch_dec = BatchWrapper(b, len(batches['decal_pos']) // 3)

                for cam in cameras:
                    cam_name = cam['name']
                    cam_type = cam['type']
                    cam_pos = cam['pos']
                    cam_fwd = cam.get('forward', Vector((0, -1, 0)))

                    # 1. Unoccluded solid angle from this camera position
                    if len(tri_geom['V0']) > 0:
                        tri_omega = batch_triangle_solid_angle(
                            cam_pos, tri_geom['V0'], tri_geom['V1'], tri_geom['V2']
                        )
                        eval_unocc = np.bincount(
                            tri_geom['tri_ids'], weights=tri_omega, minlength=max_id + 1
                        )
                    else:
                        eval_unocc = np.zeros(max_id + 1, dtype=np.float32)

                    eval_vis = np.zeros(max_id + 1, dtype=np.float64)

                    # 2. Render views
                    if cam_type == 'LOOK_AROUND':
                        faces = cubemap_face_matrices(cam_pos, cam_fwd)
                        face_weights = precompute_cubemap_weights(
                            faces, cam_fwd, cube_res=cube_res, floor=floor, falloff=falloff
                        )
                        for face_name, v_mat, p_mat in faces:
                            mvp = p_mat @ v_mat
                            w_map = face_weights[face_name]
                            vis_counts = render_camera_view(
                                off_cube, shader, batch_op, batch_dec, mvp, w_map, max_id
                            )
                            eval_vis += vis_counts

                    elif cam_type == 'FIXED_VIEW':
                        cam_obj = bpy.data.objects.get(cam.get('obj_name', cam_name))
                        if cam_obj:
                            p_mat = cam_obj.calc_matrix_camera(dg, x=frustum_res[0], y=frustum_res[1])
                            v_mat = cam_obj.matrix_world.inverted()
                            mvp = p_mat @ v_mat
                            w_map = precompute_frustum_weights(cam_obj, frustum_res)
                            vis_counts = render_camera_view(
                                off_frustum, shader, batch_op, batch_dec, mvp, w_map, max_id
                            )
                            eval_vis += vis_counts

                    # 3. Accumulate sums into mesh_arrays
                    for eid, (m_name, inst_idx, orig_idx) in eval_poly_info.items():
                        v_vis = eval_vis[eid]
                        v_unocc = eval_unocc[eid]
                        mesh_arrays[m_name]['vis_omega'][view_idx, inst_idx, orig_idx] += v_vis
                        mesh_arrays[m_name]['unocc_omega'][view_idx, inst_idx, orig_idx] += v_unocc

                    view_idx += 1

                state_timings[f"state_{pct_label}"] = time.perf_counter() - t_s0

        finally:
            anim_ctrl.restore()
            off_cube.free()
            off_frustum.free()

        total_time = time.perf_counter() - t_start

        # 4. Compute per-face patch scores, undetermined resolution & island values (Decision 79)
        group_res = compute_patch_scores_and_groups(
            mesh_meta, mesh_arrays, min_px_threshold=min_px_threshold, ref_cube_res=1024
        )

        object_summaries = group_res['object_summaries']
        island_summaries = group_res['island_summaries']
        resolved_counts = group_res['resolved_counts']
        patch_time = group_res['patch_expansion_time_s']

        total_faces = sum(meta['n_orig_faces'] for meta in mesh_meta.values())
        total_surface_area = sum(float(np.sum(meta['orig_areas'])) for meta in mesh_meta.values())

        # Global statistics
        never_seen_islands = [k for k, v in island_summaries.items() if v['never_seen']]
        never_seen_objects = [k for k, v in object_summaries.items() if v['never_seen']]
        undetermined_objects = [k for k, v in object_summaries.items() if v['undetermined']]

        # Face statistics
        total_never_seen_faces = 0
        total_never_seen_face_area = 0.0
        total_undetermined_faces = 0
        total_undetermined_face_area = 0.0
        all_face_scores = []
        all_face_areas = []

        for m_name, meta in mesh_meta.items():
            f_sc = mesh_arrays[m_name]['face_scores']
            f_nv = mesh_arrays[m_name]['face_never_seen']
            f_ud = mesh_arrays[m_name]['face_undetermined']
            f_ar = meta['orig_areas']

            total_never_seen_faces += int(np.count_nonzero(f_nv))
            total_never_seen_face_area += float(np.sum(f_ar[f_nv]))
            total_undetermined_faces += int(np.count_nonzero(f_ud))
            total_undetermined_face_area += float(np.sum(f_ar[f_ud]))

            for i in range(len(f_sc)):
                if not f_nv[i]:
                    all_face_scores.append(f_sc[i])
                    all_face_areas.append(f_ar[i])

        # Face score percentiles
        face_percentiles = {}
        if all_face_scores:
            s_arr = np.array(all_face_scores, dtype=np.float64)
            w_arr = np.array(all_face_areas, dtype=np.float64)
            for p in [10, 25, 50, 75, 90, 95]:
                face_percentiles[f"p{p}"] = weighted_percentile(s_arr, w_arr, p / 100.0)

        # Island score percentiles (area-weighted across all visible islands)
        all_isl_scores = []
        all_isl_areas = []
        for isl in island_summaries.values():
            if not isl['never_seen']:
                all_isl_scores.append(isl['score'])
                all_isl_areas.append(isl['area_m2'])

        island_percentiles = {}
        if all_isl_scores:
            s_arr = np.array(all_isl_scores, dtype=np.float64)
            w_arr = np.array(all_isl_areas, dtype=np.float64)
            for p in [10, 25, 50, 75, 90, 95]:
                island_percentiles[f"p{p}"] = weighted_percentile(s_arr, w_arr, p / 100.0)

        # Glareshield island special report (CockpitShell.010, mesh C3_001.018, island 4)
        glareshield_isl_report = None
        gl_obj = bpy.data.objects.get("CockpitShell.010")
        gl_m_name = gl_obj.data.name if (gl_obj and gl_obj.data) else ("CockpitShell.010" if "CockpitShell.010" in mesh_meta else "C3_001.018")
        gl_key = f"{gl_m_name}__isl_4"
        if gl_key in island_summaries:
            gl_data = island_summaries[gl_key]
            gl_m = mesh_arrays[gl_m_name]
            gl_meta = mesh_meta[gl_m_name]
            gl_faces = np.flatnonzero(gl_meta['island_ids'] == 4)
            gl_vis = np.sum(gl_m['vis_omega'][:, :, gl_faces], axis=-1)
            gl_unocc = np.sum(gl_m['unocc_omega'][:, :, gl_faces], axis=-1)
            valid = gl_unocc > 1e-12
            old_ratio = float(np.max(np.where(valid, np.clip(gl_vis / np.maximum(gl_unocc, 1e-12), 0.0, 1.0), 0.0)))
            glareshield_isl_report = {
                'island_value_d82': gl_data['score'],
                'island_value_r4_avg': gl_data['r4_avg'],
                'seen_area_share': gl_data['seen_area_share'],
                'old_sum_ratio': old_ratio,
                'n_faces': gl_data['n_faces'],
                'area_m2': gl_data['area_m2'],
            }

        results = {
            'blend_file': str(blend_path),
            'schema_version': 4,
            'total_time_s': total_time,
            'patch_expansion_time_s': patch_time,
            'state_timings': state_timings,
            'views': [
                {'camera': v['camera'], 'state': v['state'], 'floor': v['floor'], 'falloff': v['falloff']}
                for v in view_configs
            ],
            'ref_cube_res': 1024,
            'cube_res': cube_res,
            'min_px_threshold': min_px_threshold,
            'total_faces': total_faces,
            'total_surface_area_m2': total_surface_area,
            'total_objects': len(object_summaries),
            'never_seen_objects_count': len(never_seen_objects),
            'undetermined_objects_count': len(undetermined_objects),
            'total_islands': len(island_summaries),
            'never_seen_islands_count': len(never_seen_islands),
            'total_never_seen_faces': total_never_seen_faces,
            'total_never_seen_face_area_m2': total_never_seen_face_area,
            'total_undetermined_faces': total_undetermined_faces,
            'total_undetermined_face_area_m2': total_undetermined_face_area,
            'face_percentiles': face_percentiles,
            'island_percentiles': island_percentiles,
            'resolved_counts': resolved_counts,
            'glareshield_island_report': glareshield_isl_report,
            'object_summaries': object_summaries,
            'island_summaries': island_summaries,
            'mesh_arrays': mesh_arrays,
            'mesh_meta': mesh_meta,
        }

        return results

    finally:
        remove_orig_face_index_attributes()


def weighted_percentile(values, weights, percentile=0.90):
    """Area-weighted percentile (inverse CDF, no interpolation)."""
    if len(values) == 0:
        return 0.0
    val_arr = np.array(values, dtype=np.float64)
    w_arr = np.array(weights, dtype=np.float64)
    order = np.argsort(val_arr)
    cum_w = np.cumsum(w_arr[order])
    total_w = cum_w[-1]
    if total_w <= 1e-12:
        return float(val_arr[order[0]])
    cutoff = percentile * total_w
    idx = min(int(np.searchsorted(cum_w, cutoff)), len(order) - 1)
    return float(val_arr[order[idx]])


# ---------------------------------------------------------------------------
# Storage: External .visibility File Version 4 & Staleness (Decision 67 & Step 6)
# ---------------------------------------------------------------------------

def save_visibility_file(blend_path, results):
    """Save results as compressed `<blend_name>.visibility` (Schema Version 4)."""
    vis_path = Path(blend_path).with_suffix('.visibility')

    mesh_face_counts = {
        m_name: meta['n_orig_faces'] for m_name, meta in results['mesh_meta'].items()
    }

    meta = {
        'schema_version': 4,
        'blend_file': str(results['blend_file']),
        'timestamp': time.strftime("%Y-%m-%d %H:%M:%S"),
        'total_time_s': results['total_time_s'],
        'patch_expansion_time_s': results['patch_expansion_time_s'],
        'state_timings': results['state_timings'],
        'views': results['views'],
        'ref_cube_res': results['ref_cube_res'],
        'min_px_threshold': results['min_px_threshold'],
        'total_faces': results['total_faces'],
        'total_surface_area_m2': results['total_surface_area_m2'],
        'total_objects': results['total_objects'],
        'never_seen_objects_count': results['never_seen_objects_count'],
        'undetermined_objects_count': results['undetermined_objects_count'],
        'total_islands': results['total_islands'],
        'never_seen_islands_count': results['never_seen_islands_count'],
        'total_never_seen_faces': results['total_never_seen_faces'],
        'total_never_seen_face_area_m2': results['total_never_seen_face_area_m2'],
        'total_undetermined_faces': results['total_undetermined_faces'],
        'total_undetermined_face_area_m2': results['total_undetermined_face_area_m2'],
        'face_percentiles': results['face_percentiles'],
        'island_percentiles': results['island_percentiles'],
        'resolved_counts': results['resolved_counts'],
        'glareshield_island_report': results['glareshield_island_report'],
        'mesh_face_counts': mesh_face_counts,
        'object_summaries': results['object_summaries'],
        'island_summaries': results['island_summaries'],
    }

    arrays_to_save = {
        '_meta_json': np.array([json.dumps(meta)]),
    }

    for m_name, m_data in results['mesh_arrays'].items():
        safe_name = m_name.replace('/', '_').replace('\\', '_')
        arrays_to_save[f"{safe_name}__vis_omega"] = m_data['vis_omega'].astype(np.float32)
        arrays_to_save[f"{safe_name}__unocc_omega"] = m_data['unocc_omega'].astype(np.float32)
        arrays_to_save[f"{safe_name}__face_scores"] = m_data['face_scores'].astype(np.float32)
        arrays_to_save[f"{safe_name}__face_undetermined"] = m_data['face_undetermined'].astype(np.int8)
        arrays_to_save[f"{safe_name}__face_never_seen"] = m_data['face_never_seen'].astype(np.int8)
        arrays_to_save[f"{safe_name}__area"] = m_data['area'].astype(np.float32)
        arrays_to_save[f"{safe_name}__island_ids"] = m_data['island_ids'].astype(np.int32)

    with open(vis_path, 'wb') as f:
        np.savez_compressed(f, **arrays_to_save)
    return vis_path


def load_visibility_file(vis_path, scene_meshes=None):
    """Load `.visibility` file and verify staleness against scene meshes (Step 6)."""
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
# Offscreen Heatmap Image Rendering (Step 9)
# ---------------------------------------------------------------------------

def compute_heatmap_colors(scores, undetermined_mask, never_seen_mask):
    """Map visibility score in [0.0, 1.0] to RGBA colors (Step 9).

    - Undetermined: Cyan (0.0, 0.85, 0.85, 1.0)
    - Never Seen (0.0): Magenta (1.0, 0.0, 1.0, 1.0)
    - Seen (0.0, 0.5]: Red (0.95, 0.15, 0.15) to Neutral Grey (0.92, 0.92, 0.92)
    - Seen [0.5, 1.0]: Neutral Grey (0.92, 0.92, 0.92) to Blue (0.10, 0.35, 0.95)
    """
    n = len(scores)
    colors = np.empty((n, 4), dtype=np.float32)

    c_cyan = np.array([0.0, 0.85, 0.85, 1.0], dtype=np.float32)
    c_mag = np.array([1.0, 0.0, 1.0, 1.0], dtype=np.float32)
    c_red = np.array([0.95, 0.15, 0.15, 1.0], dtype=np.float32)
    c_neu = np.array([0.92, 0.92, 0.92, 1.0], dtype=np.float32)
    c_blue = np.array([0.10, 0.35, 0.95, 1.0], dtype=np.float32)

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


def render_heatmap_image(output_path, mvp, res=(1920, 1080), view_normal_matrix=None, results=None):
    """Render scene coloured by per-face visibility score into a PNG image (Step 9)."""
    W, H = res
    shader = get_heatmap_render_shader()

    if view_normal_matrix is None:
        view_normal_matrix = Matrix.Identity(4)

    all_pos, all_nor, all_col = [], [], []

    mesh_objs = [
        o for o in bpy.context.view_layer.objects
        if o is not None and o.type == 'MESH' and o.data and not o.hide_viewport and not o.hide_render
    ]

    add_orig_face_index_attributes()
    dg = bpy.context.evaluated_depsgraph_get()

    try:
        for o in mesh_objs:
            if is_invisible_object(o):
                continue

            me_orig = o.data
            m_name = me_orig.name
            n_orig_faces = len(me_orig.polygons)

            # Read per-face scores
            face_scores = np.zeros(n_orig_faces, dtype=np.float32)
            face_undet = np.zeros(n_orig_faces, dtype=bool)
            face_nv = np.zeros(n_orig_faces, dtype=bool)

            if results and 'mesh_arrays' in results and m_name in results['mesh_arrays']:
                m_data = results['mesh_arrays'][m_name]
                face_scores = m_data['face_scores']
                face_undet = m_data['face_undetermined']
                face_nv = m_data['face_never_seen']

            poly_colors = compute_heatmap_colors(face_scores, face_undet, face_nv)

            eval_obj = o.evaluated_get(dg)
            eval_me = eval_obj.to_mesh()
            eval_me.calc_loop_triangles()
            n_lt = len(eval_me.loop_triangles)
            if n_lt == 0:
                eval_obj.to_mesh_clear()
                continue

            poly_mat_class = []
            for p in eval_me.polygons:
                mat_idx = p.material_index
                mat = o.material_slots[mat_idx].material if mat_idx < len(o.material_slots) else None
                poly_mat_class.append(classify_material(mat))

            eval_attr = eval_me.attributes.get(ORIG_FACE_ATTR_NAME)
            if eval_attr:
                orig_indices = np.empty(len(eval_me.polygons), dtype=np.int32)
                eval_attr.data.foreach_get('value', orig_indices)
            else:
                raise RuntimeError(f"Attribute {ORIG_FACE_ATTR_NAME} missing on evaluated mesh {m_name}")

            verts = np.empty((n_lt, 3), dtype=np.int32)
            eval_me.loop_triangles.foreach_get('vertices', verts.ravel())

            V_eval = np.empty((len(eval_me.vertices), 3), dtype=np.float32)
            eval_me.vertices.foreach_get('co', V_eval.ravel())
            M_eval = np.array(o.matrix_world, dtype=np.float32)
            P_world = (V_eval @ M_eval[:3, :3].T + M_eval[:3, 3])[verts]

            # Normals
            N_tri = np.empty((n_lt, 3), dtype=np.float32)
            eval_me.loop_triangles.foreach_get('normal', N_tri.ravel())
            M_norm = np.linalg.inv(M_eval[:3, :3]).T
            N_world = N_tri @ M_norm.T
            norm_lens = np.linalg.norm(N_world, axis=-1, keepdims=True)
            N_world /= np.maximum(norm_lens, 1e-8)
            N_world_expanded = np.repeat(N_world[:, None, :], 3, axis=1)

            poly_indices = np.empty(n_lt, dtype=np.int32)
            eval_me.loop_triangles.foreach_get('polygon_index', poly_indices)

            # Filter out invisible material triangles
            for lt_idx in range(n_lt):
                pi = poly_indices[lt_idx]
                if poly_mat_class[pi] == 'INVISIBLE':
                    continue

                orig_idx = int(orig_indices[pi])
                col = poly_colors[orig_idx]
                col_expanded = np.repeat(col[None, :], 3, axis=0)

                all_pos.append(P_world[lt_idx])
                all_nor.append(N_world_expanded[lt_idx])
                all_col.append(col_expanded)

            eval_obj.to_mesh_clear()

    finally:
        remove_orig_face_index_attributes()

    if not all_pos:
        return False

    pos_cat = np.concatenate(all_pos, axis=0)
    nor_cat = np.concatenate(all_nor, axis=0)
    col_cat = np.concatenate(all_col, axis=0)

    batch = batch_for_shader(shader, 'TRIS', {'pos': pos_cat, 'nor': nor_cat, 'color': col_cat})

    off = gpu.types.GPUOffScreen(W, H)
    try:
        with off.bind():
            fb = gpu.state.active_framebuffer_get()
            fb.clear(color=(0.05, 0.05, 0.07, 1.0), depth=1.0)
            gpu.state.depth_test_set('LESS_EQUAL')
            gpu.state.depth_mask_set(True)
            shader.bind()
            shader.uniform_float('mvp', mvp)
            shader.uniform_float('normal_matrix', view_normal_matrix)
            batch.draw(shader)
            gpu.state.depth_test_set('NONE')
            px = np.array(fb.read_color(0, 0, W, H, 4, 0, 'FLOAT'), dtype=np.float32)
    finally:
        off.free()

    abs_path = os.path.abspath(str(output_path))
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    img_name = f"vis_render_{Path(output_path).stem}"
    img = bpy.data.images.new(img_name, W, H, float_buffer=True)
    img.pixels.foreach_set(px.ravel())
    img.filepath_raw = abs_path
    img.file_format = 'PNG'
    img.save()
    bpy.data.images.remove(img)
    return True


# ---------------------------------------------------------------------------
# glTF Export Integrity Verification
# ---------------------------------------------------------------------------

def test_gltf_export(blend_path, out_dir):
    """Test that glTF exporter succeeds and no visibility attributes or extras leak."""
    print("\n--- Verifying glTF Export Integrity ---")
    gltf_out = Path(out_dir) / "vis_export_test.gltf"

    t_start = time.perf_counter()
    bpy.ops.export_scene.gltf(
        filepath=str(gltf_out),
        export_format='GLTF_SEPARATE',
        use_selection=False,
        export_animations=False,
        export_skins=False,
        export_morph=False,
    )
    t_export = time.perf_counter() - t_start
    print(f"glTF export completed in {t_export:.2f} s")

    with open(gltf_out, 'r', encoding='utf-8') as f:
        gltf_data = json.load(f)

    # 1. Check for attribute leaks in meshes
    for m in gltf_data.get('meshes', []):
        for prim in m.get('primitives', []):
            attrs = prim.get('attributes', {})
            for attr_name in attrs:
                assert not attr_name.startswith('_FSS_'), f"Leak: found internal attribute {attr_name} in exported mesh"
                assert 'VISIBILITY' not in attr_name.upper(), f"Leak: found visibility attribute {attr_name} in exported mesh"

    # 2. Check for extras leaks in nodes
    for node in gltf_data.get('nodes', []):
        extras = node.get('extras', {})
        for k in extras:
            assert 'visibility' not in k.lower(), f"Leak: found visibility extras property {k} in exported glTF node"

    print("PASS: Verified that no visibility attributes or extras reach exported glTF!\n")
    return t_export


# ---------------------------------------------------------------------------
# Synthetic Validation Suite (15 Test Cases, Step 10)
# ---------------------------------------------------------------------------

def build_synthetic_scene(blend_path):
    """Construct synthetic test scene with all test geometries."""
    import bmesh

    bpy.ops.wm.read_factory_settings(use_empty=True)

    cam_data = bpy.data.cameras.new("CAM_PILOT_CLOSE")
    cam_data.lens = 28.0
    cam_obj = bpy.data.objects.new("CAM_PILOT_CLOSE", cam_data)
    cam_obj.location = Vector((0, 0, 0))
    cam_obj.rotation_euler = (math.radians(-90), 0, math.radians(180))
    bpy.context.scene.collection.objects.link(cam_obj)

    def create_quad_facing(name, size, loc, normal_dir='+Y', mat_name=None):
        me = bpy.data.meshes.new(name + "_Mesh")
        bm = bmesh.new()
        hw, hh = size[0] / 2.0, size[1] / 2.0

        if normal_dir == '+Y':
            v1 = bm.verts.new((-hw, 0, -hh))
            v2 = bm.verts.new((hw, 0, -hh))
            v3 = bm.verts.new((hw, 0, hh))
            v4 = bm.verts.new((-hw, 0, hh))
            bm.faces.new((v4, v3, v2, v1))
        elif normal_dir == '-Y':
            v1 = bm.verts.new((-hw, 0, -hh))
            v2 = bm.verts.new((hw, 0, -hh))
            v3 = bm.verts.new((hw, 0, hh))
            v4 = bm.verts.new((-hw, 0, hh))
            bm.faces.new((v1, v2, v3, v4))
        elif normal_dir == '-X':
            v1 = bm.verts.new((0, -hw, -hh))
            v2 = bm.verts.new((0, hw, -hh))
            v3 = bm.verts.new((0, hw, hh))
            v4 = bm.verts.new((0, -hw, hh))
            bm.faces.new((v4, v3, v2, v1))

        bm.to_mesh(me)
        bm.free()
        obj = bpy.data.objects.new(name, me)
        obj.location = Vector(loc)
        bpy.context.scene.collection.objects.link(obj)

        if mat_name:
            mat = bpy.data.materials.new(mat_name)
            obj.data.materials.append(mat)

        return obj

    # 1. Distance invariance: 0.5 m vs 2.0 m
    create_quad_facing("CASE1_PANEL_NEAR", (0.025, 0.025), (0.0, -0.5, -0.10), '+Y')
    create_quad_facing("CASE1_PANEL_FAR",  (0.10, 0.10),   (0.0, -2.0,  0.40), '+Y')

    # 2. Half-covered panel (score ~ 0.50)
    create_quad_facing("CASE2_HALF_PANEL", (0.2, 0.2), (0.4, -2.0, 0.0), '+Y')
    create_quad_facing("CASE2_COVER_PLATE", (0.1, 0.2), (0.35, -1.999, 0.0), '+Y')

    # 3. Straight ahead (w=1.0) vs 90 deg side (w=0.20 floor)
    create_quad_facing("CASE3_PANEL_AHEAD", (0.2, 0.2), (0.0, -2.0, 0.0), '+Y')
    create_quad_facing("CASE3_PANEL_SIDE",  (0.2, 0.2), (2.0, 0.0, 0.0), '-X')

    # 4. Back face never seen (score = 0.000)
    create_quad_facing("CASE4_BACK_FACE", (0.2, 0.2), (0.0, -2.0, -0.8), '-Y')

    # 5. Invisible box hides nothing
    create_quad_facing("CASE5_TARGET_PANEL", (0.2, 0.2), (-0.8, -2.0, 0.0), '+Y')
    me_invis = bpy.data.meshes.new("CASE5_INVIS_BOX_Mesh")
    bm_invis = bmesh.new()
    bmesh.ops.create_cube(bm_invis, size=0.3)
    bm_invis.to_mesh(me_invis)
    bm_invis.free()
    invis_obj = bpy.data.objects.new("CASE5_COLLISION_BOX", me_invis)
    invis_obj.location = Vector((-0.8, -1.5, 0.0))
    mat_invis = bpy.data.materials.new("COLLIDER_MATERIAL")
    invis_obj.data.materials.append(mat_invis)
    bpy.context.scene.collection.objects.link(invis_obj)

    # 6. Decal does not hide its panel
    create_quad_facing("CASE6_OPAQUE_PANEL", (0.2, 0.2), (-0.4, -2.0, 1.0), '+Y', mat_name="PANEL_OPAQUE_MAT")
    create_quad_facing("CASE6_DECAL_QUAD", (0.15, 0.15), (-0.4, -1.98, 1.0), '+Y', mat_name="LABEL_DECAL")

    # 7. Animated action on frames 100 to 200
    lever = create_quad_facing("CASE7_ANIM_LEVER", (0.2, 0.2), (0.8, -2.0, 0.0), '+Y')
    lever.animation_data_create()
    lever.location.z = 0.0
    lever.keyframe_insert(data_path="location", index=2, frame=100)
    lever.location.z = 0.8
    lever.keyframe_insert(data_path="location", index=2, frame=200)

    act7 = lever.animation_data.action
    lever.animation_data.action = None
    tr7 = lever.animation_data.nla_tracks.new()
    tr7.name = "LEVER_TRACK"
    tr7.strips.new(act7.name, 100, act7)

    create_quad_facing("CASE7_SENSOR_PANEL", (0.15, 0.15), (0.8, -2.05, 0.8), '+Y')

    # 8. Multi-face resolution invariance (single quad vs 10,000 faces at 2 m)
    create_quad_facing("CASE8_PANEL_QUAD", (0.2, 0.2), (0.3, -2.0, -0.4), '+Y')

    # Subdivided grid into 10,000 faces (100 x 100) facing +Y
    me_grid = bpy.data.meshes.new("CASE8_PANEL_GRID_Mesh")
    bm_grid = bmesh.new()
    bmesh.ops.create_grid(bm_grid, x_segments=100, y_segments=100, size=0.1)
    for v in bm_grid.verts:
        x, y, z = v.co.x, v.co.y, v.co.z
        v.co.x = x
        v.co.y = z
        v.co.z = -y
    bm_grid.to_mesh(me_grid)
    bm_grid.free()
    grid_obj = bpy.data.objects.new("CASE8_PANEL_GRID", me_grid)
    grid_obj.location = Vector((-0.3, -2.0, -0.4))
    bpy.context.scene.collection.objects.link(grid_obj)

    # 9. Mirror object with one copy hidden behind a wall
    mirr_obj = create_quad_facing("CASE9_MIRROR_OBJ", (0.2, 0.2), (0.0, 0.0, 0.0), '+Y')
    for v in mirr_obj.data.vertices:
        v.co += Vector((0.5, -2.0, 0.4))
    mirr_obj.data.update()
    mod_m = mirr_obj.modifiers.new("MirrX", "MIRROR")
    mod_m.use_axis[0] = True
    create_quad_facing("CASE9_WALL_BLOCK", (0.4, 0.4), (-0.5, -1.5, 0.4), '+Y')

    # 10. Object with Triangulate modifier (half-covered reads ~ 0.50)
    tri_obj = create_quad_facing("CASE10_TRI_PANEL", (0.2, 0.2), (-0.4, -2.0, 0.0), '+Y')
    tri_obj.modifiers.new("Tri", "TRIANGULATE")
    create_quad_facing("CASE10_COVER_PLATE", (0.1, 0.2), (-0.45, -1.999, 0.0), '+Y')

    # 11. Two linked duplicates, one hidden
    shared_me = bpy.data.meshes.new("CASE11_SHARED_Mesh")
    bm_sh = bmesh.new()
    v1 = bm_sh.verts.new((-0.1, 0, -0.1))
    v2 = bm_sh.verts.new(( 0.1, 0, -0.1))
    v3 = bm_sh.verts.new(( 0.1, 0,  0.1))
    v4 = bm_sh.verts.new((-0.1, 0,  0.1))
    bm_sh.faces.new((v4, v3, v2, v1))
    bm_sh.to_mesh(shared_me)
    bm_sh.free()

    obj_vis = bpy.data.objects.new("CASE11_OBJ_VISIBLE", shared_me)
    obj_vis.location = Vector((-0.6, -2.0, -0.8))
    bpy.context.scene.collection.objects.link(obj_vis)

    obj_hid = bpy.data.objects.new("CASE11_OBJ_HIDDEN", shared_me)
    obj_hid.location = Vector((0.6, -2.0, -0.8))
    bpy.context.scene.collection.objects.link(obj_hid)
    create_quad_facing("CASE11_BLOCKER", (0.4, 0.4), (0.6, -1.5, -0.8), '+Y')

    # 12. Partly hidden island: two quads in ONE UV island, one in plain view and one hidden
    me12 = bpy.data.meshes.new("CASE12_PARTLY_HIDDEN_Mesh")
    bm12 = bmesh.new()
    # Quad 0: z in [0.0, 0.2] facing +Y
    v12_0 = bm12.verts.new((1.1, -2.0, 0.0))
    v12_1 = bm12.verts.new((1.3, -2.0, 0.0))
    v12_2 = bm12.verts.new((1.3, -2.0, 0.2))
    v12_3 = bm12.verts.new((1.1, -2.0, 0.2))
    f12_0 = bm12.faces.new((v12_3, v12_2, v12_1, v12_0))

    # Quad 1: z in [-0.2, 0.0] facing +Y, sharing edge (v12_0, v12_1)
    v12_4 = bm12.verts.new((1.3, -2.0, -0.2))
    v12_5 = bm12.verts.new((1.1, -2.0, -0.2))
    f12_1 = bm12.faces.new((v12_0, v12_1, v12_4, v12_5))

    # Single UV island connecting both quads
    uv_layer = bm12.loops.layers.uv.new("UVMap")
    f12_0.loops[0][uv_layer].uv = (0.0, 1.0)
    f12_0.loops[1][uv_layer].uv = (1.0, 1.0)
    f12_0.loops[2][uv_layer].uv = (1.0, 0.5)
    f12_0.loops[3][uv_layer].uv = (0.0, 0.5)

    f12_1.loops[0][uv_layer].uv = (0.0, 0.5)
    f12_1.loops[1][uv_layer].uv = (1.0, 0.5)
    f12_1.loops[2][uv_layer].uv = (1.0, 0.0)
    f12_1.loops[3][uv_layer].uv = (0.0, 0.0)

    bm12.to_mesh(me12)
    bm12.free()
    obj12 = bpy.data.objects.new("CASE12_PARTLY_HIDDEN_OBJ", me12)
    bpy.context.scene.collection.objects.link(obj12)

    # Blocker in front of Quad 1
    me_b = bpy.data.meshes.new("CASE12_BLOCKER_Mesh")
    bm_b = bmesh.new()
    v_b0 = bm_b.verts.new((0.70, -1.5, -0.20))
    v_b1 = bm_b.verts.new((1.10, -1.5, -0.20))
    v_b2 = bm_b.verts.new((1.10, -1.5,  0.00))
    v_b3 = bm_b.verts.new((0.70, -1.5,  0.00))
    bm_b.faces.new((v_b3, v_b2, v_b1, v_b0))
    bm_b.to_mesh(me_b)
    bm_b.free()
    obj_b = bpy.data.objects.new("CASE12_BLOCKER", me_b)
    bpy.context.scene.collection.objects.link(obj_b)

    # 13. Small 2 mm part at 1 m with parent panel
    p13 = create_quad_facing("CASE13_PARENT_PANEL", (0.2, 0.2), (0.0, -1.0, 0.6), '+Y')
    c13 = create_quad_facing("CASE13_CHILD_PART", (0.002, 0.002), (0.0, -1.0, 0.5), '+Y')
    c13.parent = p13

    # 14. Same 2 mm part with no parent
    create_quad_facing("CASE14_STANDALONE_PART", (0.002, 0.002), (0.3, -1.0, 0.5), '+Y')

    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    return blend_path


def validate_synthetic_cases(results, blend_path=None):
    """Verify all 15 synthetic cases pass assertions (Step 10)."""
    objs = results['object_summaries']
    isls = results['island_summaries']
    m_arrays = results['mesh_arrays']
    mesh_meta = results['mesh_meta']

    print("\n" + "=" * 70)
    print("      SYNTHETIC VALIDATION (ROUND 5 - 15 CASES)")
    print("=" * 70)

    # Case 1: Distance-free equal scores at 0.5 m and 2.0 m
    s_near = objs["CASE1_PANEL_NEAR"]['score']
    s_far  = objs["CASE1_PANEL_FAR"]['score']
    print(f"Case 1 (Distance Invariance): Near (0.5m) = {s_near:.4f}, Far (2.0m) = {s_far:.4f}")
    assert s_near >= 0.90, f"Near panel score too low ({s_near:.4f})"
    assert s_far >= 0.90, f"Far panel score too low ({s_far:.4f})"
    assert abs(s_near - s_far) < 0.02, f"Distance discrepancy: {abs(s_near - s_far):.4f}"
    print("  -> PASS: Distance-free equal scores verified.")

    # Case 2: Half-covered panel (score ~ 0.50)
    s_half = objs["CASE2_HALF_PANEL"]['score']
    print(f"Case 2 (Half-Covered Panel): Score = {s_half:.4f} (expected ~0.50)")
    assert 0.45 <= s_half <= 0.55, f"Half panel score out of range: {s_half:.4f}"
    print("  -> PASS: Half-covered panel receives ~0.50 visible fraction.")

    # Case 3: Straight ahead (w=1.0) vs 90 deg side (w=0.20 floor)
    s_ahead = objs["CASE3_PANEL_AHEAD"]['score']
    s_side  = objs["CASE3_PANEL_SIDE"]['score']
    print(f"Case 3 (Direction Weight): Ahead = {s_ahead:.4f}, Side (90°) = {s_side:.4f}")
    assert s_ahead >= 0.98, f"Straight ahead score too low: {s_ahead:.4f}"
    assert 0.18 <= s_side <= 0.22, f"Side score out of floor range: {s_side:.4f}"
    print("  -> PASS: Side view receives floor weight 0.20.")

    # Case 4: Back face never seen
    s_back = objs["CASE4_BACK_FACE"]['score']
    print(f"Case 4 (Back Face): Score = {s_back:.4f} (expected 0.000)")
    assert s_back == 0.0, f"Back face must have score 0.0, got {s_back}"
    print("  -> PASS: Back face receives score 0.000 (never seen).")

    # Case 5: Invisible box hides nothing
    s_invis_target = objs["CASE5_TARGET_PANEL"]['score']
    print(f"Case 5 (Invisible Box Occlusion): Target Panel Score = {s_invis_target:.4f}")
    assert s_invis_target >= 0.85, f"Invisible box occluded panel: {s_invis_target:.4f}"
    assert "CASE5_COLLISION_BOX" not in objs, "Invisible collision box should not be scored!"
    print("  -> PASS: Invisible box hides nothing and is omitted from scoring.")

    # Case 6: Decal does not hide its panel
    s_opaque = objs["CASE6_OPAQUE_PANEL"]['score']
    s_decal  = objs["CASE6_DECAL_QUAD"]['score']
    print(f"Case 6 (Decal on Panel): Opaque Panel = {s_opaque:.4f}, Decal = {s_decal:.4f}")
    assert s_opaque >= 0.80, f"Opaque panel occluded by decal: {s_opaque:.4f}"
    assert s_decal >= 0.80, f"Decal not scored: {s_decal:.4f}"
    assert abs(s_opaque - s_decal) < 0.10, f"Decal and opaque mismatch: {s_opaque} vs {s_decal}"
    print("  -> PASS: Decal is scored and does not occlude the panel behind it.")

    # Case 7: Animated action on frames 100 to 200
    s_lever  = objs["CASE7_ANIM_LEVER"]['score']
    s_sensor = objs["CASE7_SENSOR_PANEL"]['score']
    print(f"Case 7 (Action 100-200 Evaluation): Lever = {s_lever:.4f}, Sensor = {s_sensor:.4f}")
    assert s_lever >= 0.80, f"Lever score low: {s_lever:.4f}"
    assert s_sensor >= 0.80, f"Sensor uncovered at frame 100 must be seen, got {s_sensor:.4f}"
    print("  -> PASS: Action evaluated across its normalized percentage range.")

    # Case 8: Multi-face resolution invariance - island value within 0.02 of single quad (Decision 82)
    isl_quad = isls["CASE8_PANEL_QUAD_Mesh__isl_0"]
    isl_grid = isls["CASE8_PANEL_GRID_Mesh__isl_0"]
    s_quad = isl_quad['score']
    s_grid = isl_grid['score']
    r4_grid = isl_grid['r4_avg']

    grid_faces_sc = m_arrays["CASE8_PANEL_GRID_Mesh"]['face_scores']
    grid_faces_ar = mesh_meta["CASE8_PANEL_GRID_Mesh"]['orig_areas']
    max_grid_diff = float(np.max(np.abs(grid_faces_sc - s_quad)))
    mean_grid_diff = float(np.average(np.abs(grid_faces_sc - s_quad), weights=grid_faces_ar))
    mean_grid_sc = float(np.average(grid_faces_sc, weights=grid_faces_ar))
    isl_diff = abs(s_grid - s_quad)

    print(f"Case 8 (Multi-Face Patch Invariance): Quad Island = {s_quad:.4f}, Grid Island (D82) = {s_grid:.4f}, Grid R4 Avg = {r4_grid:.4f}")
    print(f"  Info: Per-Face Max Diff = {max_grid_diff:.4f}, Area-Weighted Mean Diff = {mean_grid_diff:.4f}, Area-Weighted Mean Score = {mean_grid_sc:.4f}")
    assert s_quad >= 0.85, f"Quad score low: {s_quad:.4f}"
    assert isl_diff <= 0.02, f"Grid island value exceeds 0.02 tolerance against quad: {isl_diff:.4f}"
    print(f"  -> PASS: Island value of 10,000-face grid is within {isl_diff:.4f} <= 0.02 of single quad.")

    # Case 9: Mirror object with one copy hidden
    s_mirr = objs["CASE9_MIRROR_OBJ"]['score']
    print(f"Case 9 (Mirror with One Copy Blocked): Score = {s_mirr:.4f}")
    assert s_mirr >= 0.85, f"Mirrored object score too low ({s_mirr:.4f})"
    print("  -> PASS: Original mesh keeps score of the unoccluded copy.")

    # Case 10: Object with Triangulate modifier
    s_tri = objs["CASE10_TRI_PANEL"]['score']
    print(f"Case 10 (Triangulate Modifier): Half-Covered Score = {s_tri:.4f} (expected ~0.50)")
    assert 0.45 <= s_tri <= 0.55, f"Triangulate panel score out of range: {s_tri:.4f}"
    print("  -> PASS: Evaluated triangles map to original face, reading ~0.50.")

    # Case 11: Two linked duplicates, one hidden
    s_vis = objs["CASE11_OBJ_VISIBLE"]['score']
    s_hid = objs["CASE11_OBJ_HIDDEN"]['score']
    print(f"Case 11 (Linked Duplicates): Visible Object = {s_vis:.4f}, Hidden Object = {s_hid:.4f}")
    assert s_vis >= 0.85, f"Visible linked duplicate score too low ({s_vis:.4f})"
    assert s_vis == s_hid, f"Linked duplicates share mesh score: {s_vis} vs {s_hid}"
    print("  -> PASS: Linked duplicates correctly share mesh visibility score.")

    # Case 12: Partly hidden island (Decision 79)
    isl12 = isls["CASE12_PARTLY_HIDDEN_Mesh__isl_0"]
    s_isl12 = isl12['score']
    share12 = isl12['seen_area_share']
    print(f"Case 12 (Partly Hidden Island): Island Value = {s_isl12:.4f}, Seen Share = {share12:.2f}")
    assert s_isl12 >= 0.80, f"Partly hidden island value degraded by hidden faces: {s_isl12:.4f}"
    assert 0.45 <= share12 <= 0.55, f"Expected seen share ~0.50, got {share12:.2f}"
    print("  -> PASS: Partly hidden island keeps density of visible part (~0.90, not ~0.45).")

    # Case 13: 2 mm part with parent panel (Decision 79)
    s_c13 = objs["CASE13_CHILD_PART"]['score']
    u_c13 = objs["CASE13_CHILD_PART"]['undetermined']
    print(f"Case 13 (Small Part with Parent): Score = {s_c13:.4f}, Undetermined = {u_c13}")
    assert u_c13, "2 mm child part must be marked undetermined!"
    assert s_c13 >= 0.85, f"Child part must inherit parent panel score, got {s_c13:.4f}"
    assert not objs["CASE13_CHILD_PART"]['never_seen'], "Undetermined part must never be marked never-seen!"
    print("  -> PASS: Small part inherits parent panel score, not never-seen.")

    # Case 14: 2 mm part without parent (Decision 79)
    s_c14 = objs["CASE14_STANDALONE_PART"]['score']
    u_c14 = objs["CASE14_STANDALONE_PART"]['undetermined']
    print(f"Case 14 (Small Part without Parent): Score = {s_c14:.4f}, Undetermined = {u_c14}")
    assert u_c14, "2 mm standalone part must be marked undetermined!"
    assert s_c14 == 1.0, f"Standalone undetermined part must fallback to 1.0, got {s_c14:.4f}"
    print("  -> PASS: Standalone small part falls back to neutral 1.0.")

    # Case 15: Staleness check on load (Finding 4)
    if blend_path:
        vis_file = Path(blend_path).with_suffix('.visibility')
        meta_loaded, _, stale_none = load_visibility_file(vis_file, scene_meshes=bpy.data.meshes)
        assert meta_loaded['schema_version'] == 4
        assert len(stale_none) == 0, f"Expected 0 stale meshes, got {stale_none}"

        # Modify a mesh polygon count to simulate staleness
        import bmesh
        target_me = bpy.data.meshes["CASE1_PANEL_NEAR_Mesh"]
        bm_stale = bmesh.new()
        bm_stale.from_mesh(target_me)
        bmesh.ops.triangulate(bm_stale, faces=bm_stale.faces)
        bm_stale.to_mesh(target_me)
        bm_stale.free()
        _, _, stale_detected = load_visibility_file(vis_file, scene_meshes=bpy.data.meshes)
        print(f"Case 15 (Staleness Detection): Stale list = {stale_detected}")
        assert "CASE1_PANEL_NEAR_Mesh" in stale_detected, "Modified mesh not detected as stale!"
        print("  -> PASS: Modified mesh detected and reported as stale on load.")

    print("\nALL 15 SYNTHETIC CASES PASSED SUCCESSFULLY!")
    print("=" * 70 + "\n")
    return True


# ---------------------------------------------------------------------------
# Resolution Comparison Benchmark (Step 7)
# ---------------------------------------------------------------------------

def run_resolution_check(blend_path, cameras=None, floor=0.2, falloff=1.0, out_dir="tests/_work/uv_visibility"):
    """Run resolution check comparing cube_res=1024 vs cube_res=4096 (Step 7)."""
    print("\n" + "=" * 70)
    print("      RESOLUTION CHECK: 1,024 vs 4,096 PX CUBE FACES (ROUND 5)")
    print("=" * 70)

    # 1. Run at 1024
    print("Running at cube_res = 1,024 px...")
    res_1024 = analyze_visibility(
        blend_path, cameras=cameras, anim_states=(0.0,),
        cube_res=1024, floor=floor, falloff=falloff, min_px_threshold=10.0
    )

    # 2. Run at 4096
    print("Running at cube_res = 4,096 px...")
    res_4096 = analyze_visibility(
        blend_path, cameras=cameras, anim_states=(0.0,),
        cube_res=4096, floor=floor, falloff=falloff, min_px_threshold=10.0
    )

    d_omega_px_1024 = 4.0 / (1024.0 * 1024.0)

    # 1. Per-Face Resolution Comparison Table
    all_f_size_1024 = []
    all_f_s_1024 = []
    all_f_s_4096 = []
    all_f_areas = []

    for m_name, meta in res_1024['mesh_meta'].items():
        if m_name not in res_4096['mesh_meta']:
            continue
        unocc_1024 = res_1024['mesh_arrays'][m_name]['unocc_omega']
        f_size = np.max(unocc_1024, axis=(0, 1)) / d_omega_px_1024
        f_s1 = res_1024['mesh_arrays'][m_name]['face_scores']
        f_s2 = res_4096['mesh_arrays'][m_name]['face_scores']
        f_ar = meta['orig_areas']

        all_f_size_1024.extend(f_size)
        all_f_s_1024.extend(f_s1)
        all_f_s_4096.extend(f_s2)
        all_f_areas.extend(f_ar)

    f_sizes = np.array(all_f_size_1024, dtype=np.float64)
    f_s1_arr = np.array(all_f_s_1024, dtype=np.float64)
    f_s2_arr = np.array(all_f_s_4096, dtype=np.float64)
    f_ar_arr = np.array(all_f_areas, dtype=np.float64)

    face_buckets = [
        ("face", "< 1 px",       f_sizes < 1.0),
        ("face", "1 to 10 px",   (f_sizes >= 1.0) & (f_sizes < 10.0)),
        ("face", "10 to 100 px", (f_sizes >= 10.0) & (f_sizes < 100.0)),
        ("face", "over 100 px",  f_sizes >= 100.0),
    ]

    print("\n--- Per-Face Scores Comparison (Area-Weighted) ---")
    print("| Score | Face size at 1,024 px  | Count | Area (m²) | Mean difference | Correlation | Status |")
    print("| :---  | :---                   | ---:  | ---:      | ---:            | ---:        | :---:  |")

    all_criteria_met = True

    for stype, glabel, mask in face_buckets:
        n_cnt = int(np.count_nonzero(mask))
        if n_cnt > 1:
            diff = np.abs(f_s1_arr[mask] - f_s2_arr[mask])
            w = f_ar_arr[mask]
            w_sum = np.sum(w)
            mean_diff = float(np.sum(diff * w) / max(w_sum, 1e-12))

            v1 = f_s1_arr[mask] - np.mean(f_s1_arr[mask])
            v2 = f_s2_arr[mask] - np.mean(f_s2_arr[mask])
            std1 = np.linalg.norm(v1)
            std2 = np.linalg.norm(v2)
            corr = float(np.dot(v1, v2) / (std1 * std2)) if std1 > 1e-8 and std2 > 1e-8 else 1.0

            is_over_10 = ("10 to 100" in glabel or "over 100" in glabel)
            meets = (mean_diff <= 0.02) if is_over_10 else True
            if not meets:
                all_criteria_met = False
            status_str = "PASS" if meets else "NOT MET"
            print(f"| {stype:<5} | {glabel:<22} | {n_cnt:>5} | {w_sum:>9.3f} | {mean_diff:>15.4f} | {corr:>11.4f} | {status_str:^6} |")
        else:
            print(f"| {stype:<5} | {glabel:<22} | {n_cnt:>5} |       N/A |             N/A |         N/A |   N/A  |")

    # 2. Island Values Comparison Table
    isls_1024 = res_1024['island_summaries']
    isls_4096 = res_4096['island_summaries']
    common_isls = sorted(set(isls_1024.keys()) & set(isls_4096.keys()))

    isl_size_arr = np.array([isls_1024[k]['size_px'] for k in common_isls], dtype=np.float64)
    isl_s1_arr = np.array([isls_1024[k]['score'] for k in common_isls], dtype=np.float64)
    isl_s2_arr = np.array([isls_4096[k]['score'] for k in common_isls], dtype=np.float64)
    isl_ar_arr = np.array([isls_1024[k]['area_m2'] for k in common_isls], dtype=np.float64)
    isl_undet_arr = np.array([isls_1024[k]['undetermined_only'] for k in common_isls], dtype=bool)

    island_buckets = [
        ("island", "undetermined only", isl_undet_arr),
        ("island", "1 to 10 px",        (~isl_undet_arr) & (isl_size_arr >= 1.0) & (isl_size_arr < 10.0)),
        ("island", "10 to 100 px",      (~isl_undet_arr) & (isl_size_arr >= 10.0) & (isl_size_arr < 100.0)),
        ("island", "over 100 px",       (~isl_undet_arr) & (isl_size_arr >= 100.0)),
    ]

    print("\n--- Island Values Comparison (Area-Weighted) ---")
    print("| Score  | Island size at 1,024 px| Count | Area (m²) | Mean difference | Correlation | Status |")
    print("| :---   | :---                   | ---:  | ---:      | ---:            | ---:        | :---:  |")

    for stype, glabel, mask in island_buckets:
        n_cnt = int(np.count_nonzero(mask))
        if n_cnt > 1:
            diff = np.abs(isl_s1_arr[mask] - isl_s2_arr[mask])
            w = isl_ar_arr[mask]
            w_sum = np.sum(w)
            mean_diff = float(np.sum(diff * w) / max(w_sum, 1e-12))

            v1 = isl_s1_arr[mask] - np.mean(isl_s1_arr[mask])
            v2 = isl_s2_arr[mask] - np.mean(isl_s2_arr[mask])
            std1 = np.linalg.norm(v1)
            std2 = np.linalg.norm(v2)
            corr = float(np.dot(v1, v2) / (std1 * std2)) if std1 > 1e-8 and std2 > 1e-8 else 1.0

            is_over_10 = ("10 to 100" in glabel or "over 100" in glabel)
            meets = (mean_diff <= 0.02) if is_over_10 else True
            if not meets:
                all_criteria_met = False
            status_str = "PASS" if meets else "NOT MET"
            print(f"| {stype:<6} | {glabel:<22} | {n_cnt:>5} | {w_sum:>9.3f} | {mean_diff:>15.4f} | {corr:>11.4f} | {status_str:^6} |")
        else:
            print(f"| {stype:<6} | {glabel:<22} | {n_cnt:>5} |       N/A |             N/A |         N/A |   N/A  |")

    print("=" * 70 + "\n")
    return all_criteria_met


# ---------------------------------------------------------------------------
# Cockpit Reporting & CLI (Step 8)
# ---------------------------------------------------------------------------

def print_cockpit_report(results):
    """Print detailed analysis report for the cockpit model (Round 5)."""
    print("\n" + "=" * 76)
    print("      VISIBILITY ANALYSIS REPORT (E2 COCKPIT - ROUND 5)")
    print("=" * 76)
    print(f"File: {results['blend_file']}")
    print(f"Schema Version: {results['schema_version']}")
    print(f"Total Analysis Runtime: {results['total_time_s']:.2f} s ({results['total_time_s']/60:.2f} min)")
    print(f"Patch Expansion Time: {results['patch_expansion_time_s']:.2f} s")
    print("State Timings:")
    for s_name, s_time in results['state_timings'].items():
        print(f"  - {s_name}: {s_time:.2f} s")
    print(f"Views Evaluated: {len(results['views'])}")
    print(f"Cube Face Resolution: {results['cube_res']} px (Ref: {results['ref_cube_res']} px)")
    print(f"Small-Group Threshold: {results['min_px_threshold']} px")
    print(f"Total Scene Faces: {results['total_faces']:,}")
    print(f"Total 3D Surface Area: {results['total_surface_area_m2']:.2f} m²")

    # Faces never seen & undetermined
    n_nv_f = results['total_never_seen_faces']
    a_nv_f = results['total_never_seen_face_area_m2']
    print(f"Never-Seen Faces (Measured Hidden): {n_nv_f:,} ({n_nv_f/max(results['total_faces'], 1)*100:.1f}%), Area = {a_nv_f:.2f} m²")

    n_ud_f = results['total_undetermined_faces']
    a_ud_f = results['total_undetermined_face_area_m2']
    print(f"Undetermined Faces: {n_ud_f:,} ({n_ud_f/max(results['total_faces'], 1)*100:.1f}%), Area = {a_ud_f:.2f} m²")

    # Objects
    tot_o = results['total_objects']
    nv_o = results['never_seen_objects_count']
    ud_o = results['undetermined_objects_count']
    print(f"Total Objects Evaluated: {tot_o:,}")
    print(f"Never-Seen Objects (Measurable Hidden): {nv_o:,} ({nv_o/max(tot_o, 1)*100:.1f}%)")
    print(f"Undetermined Objects (< 10 px): {ud_o:,} ({ud_o/max(tot_o, 1)*100:.1f}%)")

    # UV Islands
    tot_isl = results['total_islands']
    nv_isl = results['never_seen_islands_count']
    print(f"Total UV Islands Evaluated: {tot_isl:,}")
    print(f"Never-Seen UV Islands: {nv_isl:,} ({nv_isl/max(tot_isl, 1)*100:.1f}%)")

    # Undetermined Hierarchy Breakdown
    rc = results['resolved_counts']
    print("\n--- Undetermined Hierarchy Resolution Breakdown ---")
    for lvl in ['OBJECT', 'PARENT_SUBTREE', 'FALLBACK_1.0']:
        data = rc.get(lvl, {'faces': 0, 'pieces': 0, 'objects': 0})
        print(f"  Level {lvl:<15}: {data['faces']:>6} faces, {data['pieces']:>4} pieces, {data['objects']:>4} objects")

    # Percentiles
    print("\n--- Face Visibility Score Percentiles (Visible Faces, Area-Weighted) ---")
    for p, val in results['face_percentiles'].items():
        print(f"  {p:>4}: {val:.4f}")

    print("\n--- Island Visibility Score Percentiles (Visible Islands, Area-Weighted) ---")
    for p, val in results['island_percentiles'].items():
        print(f"  {p:>4}: {val:.4f}")

    # Top & Bottom 20 Objects (Measurable Objects Only >= 10 px)
    objs = results['object_summaries']
    measurable_objs = {k: v for k, v in objs.items() if not v['undetermined']}
    sorted_by_score = sorted(measurable_objs.items(), key=lambda item: item[1]['score'])

    print("\n--- Bottom 20 Measurable Objects by Visibility Score (>= 10 px) ---")
    print(f"{'Object Name':<42} {'Score':<8} {'Size (px)':<10} {'Area (m²)':<10} {'Faces':<8}")
    print("-" * 76)
    for name, data in sorted_by_score[:20]:
        print(f"{name:<42} {data['score']:<8.4f} {data['size_px']:<10.1f} {data['area_m2']:<10.4f} {data['n_faces']:<8}")

    print("\n--- Top 20 Measurable Objects by Visibility Score (>= 10 px) ---")
    print(f"{'Object Name':<42} {'Score':<8} {'Size (px)':<10} {'Area (m²)':<10} {'Faces':<8}")
    print("-" * 76)
    for name, data in sorted_by_score[-20:][::-1]:
        print(f"{name:<42} {data['score']:<8.4f} {data['size_px']:<10.1f} {data['area_m2']:<10.4f} {data['n_faces']:<8}")

    # Island Value Comparison: Decision 82 vs Round 5 Area-Weighted Average
    isls = results['island_summaries']
    isl_size_arr = np.array([v['size_px'] for v in isls.values()], dtype=np.float64)
    isl_d82_arr = np.array([v['score'] for v in isls.values()], dtype=np.float64)
    isl_r4_arr = np.array([v['r4_avg'] for v in isls.values()], dtype=np.float64)
    isl_ar_arr = np.array([v['area_m2'] for v in isls.values()], dtype=np.float64)
    isl_undet_arr = np.array([v['undetermined_only'] for v in isls.values()], dtype=bool)
    isl_nv_arr = np.array([v['never_seen'] for v in isls.values()], dtype=bool)

    seen_isls_mask = ~isl_nv_arr

    island_buckets = [
        ("undetermined only", seen_isls_mask & isl_undet_arr),
        ("1 to 10 px",        seen_isls_mask & (~isl_undet_arr) & (isl_size_arr >= 1.0) & (isl_size_arr < 10.0)),
        ("10 to 100 px",      seen_isls_mask & (~isl_undet_arr) & (isl_size_arr >= 10.0) & (isl_size_arr < 100.0)),
        ("over 100 px",       seen_isls_mask & (~isl_undet_arr) & (isl_size_arr >= 100.0)),
    ]

    print("\n--- Island Values: Decision 82 vs Round 4 Average (Area-Weighted) ---")
    print("| Island Bucket          | Count | Area (m²) | Mean Signed Diff | Mean Absolute Diff |")
    print("| :---                   | ---:  | ---:      | ---:             | ---:               |")
    for glabel, mask in island_buckets:
        n_cnt = int(np.count_nonzero(mask))
        if n_cnt > 0:
            diff_signed = isl_d82_arr[mask] - isl_r4_arr[mask]
            diff_abs = np.abs(diff_signed)
            w = isl_ar_arr[mask]
            w_sum = np.sum(w)
            mean_signed = float(np.sum(diff_signed * w) / max(w_sum, 1e-12))
            mean_abs = float(np.sum(diff_abs * w) / max(w_sum, 1e-12))
            print(f"| {glabel:<22} | {n_cnt:>5} | {w_sum:>9.3f} | {mean_signed:>16.4f} | {mean_abs:>18.4f} |")
        else:
            print(f"| {glabel:<22} | {n_cnt:>5} |       N/A |              N/A |                N/A |")

    # Glareshield island report
    gl = results.get('glareshield_island_report')
    if gl:
        print("\n--- Glareshield Island Report (CockpitShell.010 Island 4) ---")
        print(f"  Faces: {gl['n_faces']}, Total Area: {gl['area_m2']:.4f} m²")
        print(f"  Decision 82 Value (Sums over Seen Faces): {gl['island_value_d82']:.4f}")
        print(f"  Round 4 Average (Area-Weighted Seen Faces): {gl['island_value_r4_avg']:.4f}")
        print(f"  Old Sum Ratio (All Faces, Decision 78): {gl['old_sum_ratio']:.4f}")
        print(f"  Seen Face Area Share: {gl['seen_area_share']*100:.1f}%")

    if results.get('gltf_export_time_s') is not None:
        print(f"\nglTF Export Integrity Check: completed in {results['gltf_export_time_s']:.2f} s")

    print("=" * 76 + "\n")
    sys.stdout.flush()


def main():
    import argparse
    argv = sys.argv
    args_to_parse = argv[argv.index("--") + 1:] if "--" in argv else []

    parser = argparse.ArgumentParser(description="Texel Demand Prototype Round 5")
    parser.add_argument("--synthetic", action="store_true", help="Run 15 synthetic validation cases")
    parser.add_argument("--cockpit", action="store_true", help="Run full cockpit analysis")
    parser.add_argument("--resolution-check", action="store_true", help="Run 1024 vs 4096 resolution check")
    parser.add_argument("--cameras", type=str, default="", help="Comma-separated reference cameras NAME[:MODE],...")
    parser.add_argument("--states", type=int, default=3, choices=[1, 3, 5], help="Number of animation states")
    parser.add_argument("--floor", type=float, default=0.2, help="Direction weight floor")
    parser.add_argument("--falloff", type=float, default=1.0, help="Direction weight falloff power")
    parser.add_argument("--cube-res", type=int, default=1024, help="Resolution per cube face")
    parser.add_argument("--out-dir", type=str, default="tests/_work/uv_visibility", help="Output directory")
    args = parser.parse_args(args_to_parse)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.states == 1:
        anim_states = (0.0,)
    elif args.states == 3:
        anim_states = (0.0, 0.5, 1.0)
    else:
        anim_states = (0.0, 0.25, 0.5, 0.75, 1.0)

    if args.synthetic:
        syn_blend = out_dir / "synthetic_test.blend"
        print(f"Creating synthetic test scene at {syn_blend}...")
        build_synthetic_scene(syn_blend)

        cameras = [
            {
                'name': 'CAM_PILOT_CLOSE',
                'type': 'LOOK_AROUND',
                'pos': Vector((0, 0, 0)),
                'forward': Vector((0, -1, 0)),
                'obj_name': 'CAM_PILOT_CLOSE',
            }
        ]
        results = analyze_visibility(
            syn_blend, cameras=cameras, anim_states=anim_states,
            cube_res=512, floor=args.floor, falloff=args.falloff, min_px_threshold=10.0
        )
        vis_file = save_visibility_file(syn_blend, results)
        validate_synthetic_cases(results, blend_path=syn_blend)
        return

    # For non-synthetic runs, cameras are mandatory (Decision 80)
    cameras = parse_cameras_arg(args.cameras)

    if args.resolution_check:
        blend_copy = out_dir / "COCKPIT_copy.blend"
        if not blend_copy.exists():
            raise FileNotFoundError(f"Cockpit copy not found at {blend_copy}")

        run_resolution_check(blend_copy, cameras=cameras, floor=args.floor, falloff=args.falloff, out_dir=out_dir)
        return

    if args.cockpit:
        blend_copy = out_dir / "COCKPIT_copy.blend"
        if not blend_copy.exists():
            raise FileNotFoundError(f"Cockpit copy not found at {blend_copy}")

        print(f"\nStarting Visibility Analysis on {blend_copy}...")
        results = analyze_visibility(
            blend_copy,
            cameras=cameras,
            anim_states=anim_states,
            cube_res=args.cube_res,
            floor=args.floor,
            falloff=args.falloff,
            min_px_threshold=10.0,
        )

        vis_file = save_visibility_file(blend_copy, results)
        print(f"Saved visibility results to: {vis_file}")
        meta_loaded, _, stale_list = load_visibility_file(vis_file, scene_meshes=bpy.data.meshes)
        assert meta_loaded['schema_version'] == 4
        assert len(stale_list) == 0

        t_export = test_gltf_export(blend_copy, out_dir)
        results['gltf_export_time_s'] = t_export

        print_cockpit_report(results)

        print("Rendering offscreen heatmap images...")
        sys.stdout.flush()
        dg = bpy.context.evaluated_depsgraph_get()

        pilot_cam = bpy.data.objects.get('CAM_PILOT_CLOSE') or bpy.data.objects.get('CAM_PILOT')
        if pilot_cam:
            proj = pilot_cam.calc_matrix_camera(dg, x=1920, y=1080)
            view = pilot_cam.matrix_world.inverted()
            mvp_pilot = proj @ view
            norm_mat = view.to_3x3().inverted().transposed().to_4x4()
            pilot_png = out_dir / "pilot_demand.png"
            render_heatmap_image(
                pilot_png, mvp_pilot, res=(1920, 1080),
                view_normal_matrix=norm_mat,
                results=results
            )
            print(f"Saved Pilot Heatmap Image: {pilot_png}")

        outside_cam_pos = Vector((3.0, -10.0, 3.5))
        cockpit_center = Vector((0.0, -13.0, 1.2))
        outside_view = look_at(outside_cam_pos, cockpit_center, Vector((0, 0, 1)))
        outside_proj = perspective_proj(math.radians(50.0), 1920 / 1080, 0.1, 50.0)
        mvp_outside = outside_proj @ outside_view
        outside_norm_mat = outside_view.to_3x3().inverted().transposed().to_4x4()
        outside_png = out_dir / "outside_demand.png"
        render_heatmap_image(
            outside_png, mvp_outside, res=(1920, 1080),
            view_normal_matrix=outside_norm_mat,
            results=results
        )
        print(f"Saved Outside Heatmap Image: {outside_png}")


if __name__ == "__main__":
    main()
