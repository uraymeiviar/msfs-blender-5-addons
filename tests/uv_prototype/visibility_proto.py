"""Visibility-based Texel Demand Prototype for Blender 5.2 (Round 2).

Implements Session 69 Design and Hand-Off:
1. Visible fraction in spherical solid angle Omega_vis / Omega_unocc in [0, 1] (Decision 72),
   independent of distance.
2. Direction weight max(floor, cos(angle)) to camera default forward (Decision 73),
   floor 0.2 and falloff as options; fixed-view mode kept as a per-camera option.
3. Animation states as percentages of each action's own frame range (Decision 69),
   default 3 states (0%, 50%, 100%), option for 5 states (0%, 25%, 50%, 75%, 100%).
4. Material classes (Decision 77):
   - Invisible / collision / occluder not rendered and not scored.
   - Decal / glass / windshield rendered after opaque pass without depth writes (scored, hide nothing).
5. Mirror mapping with maximum kept over copies (Decision 68).
6. Aggregation (Decisions 71, 74): max per face; area-weighted 90th percentile per UV island
   and per object. Never-seen reported as 'never seen in the analysed views and states'.
7. External `<blend_name>.visibility` file (Decision 67) with schema version 2.
8. Offscreen heatmap images showing graded 0..1 score (never seen in magenta).
9. Synthetic validation covering all 7 test cases.
10. Cockpit run with CAM_PILOT_CLOSE and CAM_COPILOT as look-around cameras.
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
from mathutils import Vector, Matrix, Euler

try:
    import gpu
    from gpu_extras.batch import batch_for_shader
except ImportError:
    gpu = None
    batch_for_shader = None


# ---------------------------------------------------------------------------
# Material Classification (Decision 77)
# ---------------------------------------------------------------------------

SKIP_MATERIAL_CLASSES = {
    'DECAL', 'DECAL_EM', 'DECAL_FROST', 'DECAL_BLEND',
    'GLASS', 'WNDSHIELD', 'WINDSHIELD', 'INVIS', 'OCCLUDER'
}

MSFS_SKIP_MATERIAL_TYPES = {
    'msfs_decal',
    'msfs_geo_decal',
    'msfs_geo_decal_frosted',
    'msfs_geo_decal_blendmasked',
    'msfs_glass',
    'msfs_windshield',
    'msfs_invisible',
    'msfs_environment_occluder',
}


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

    invis_tokens = {'INVIS', 'OCCLUDER', 'COLLISION', 'COLLIDER', 'INVISIBLE'}
    if parts & invis_tokens or any(base.endswith('_' + tok) for tok in invis_tokens):
        return 'INVISIBLE'

    decal_tokens = {'DECAL', 'DECAL_EM', 'DECAL_FROST', 'DECAL_BLEND', 'GLASS', 'WNDSHIELD', 'WINDSHIELD'}
    if parts & decal_tokens or any(base.endswith('_' + tok) for tok in decal_tokens):
        return 'DECAL_GLASS'

    return 'OPAQUE'


def is_invisible_object(obj):
    """Check if object name designates invisible/collision geometry."""
    name_upper = obj.name.upper()
    tokens = {'COLLISION', 'COLLIDER', 'INVIS', 'OCCLUDER'}
    return any(tok in name_upper for tok in tokens)


# ---------------------------------------------------------------------------
# Camera & Projection Math
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
        # In Blender camera local space, forward is -Z
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


# ---------------------------------------------------------------------------
# Solid Angle Maps & Direction Weights (Decisions 72 & 73)
# ---------------------------------------------------------------------------

def precompute_cubemap_weights(faces, cam_forward, cube_res=1024, floor=0.2, falloff=1.0):
    """Precompute weighted differential solid angle maps for all 6 cube faces.

    Returns dict of face_name -> np.ndarray (cube_res, cube_res) float32.
    """
    W = cube_res
    # Pixel center normalized coordinates in [-1, 1]
    u = (np.arange(W, dtype=np.float32) + 0.5) * (2.0 / W) - 1.0
    v = 1.0 - (np.arange(W, dtype=np.float32) + 0.5) * (2.0 / W)
    U, V = np.meshgrid(u, v)

    # Differential solid angle on plane at distance 1
    # d_omega = (4 / W^2) / (u^2 + v^2 + 1)^(3/2)
    d_omega = (4.0 / (W * W)) / np.power(U * U + V * V + 1.0, 1.5).astype(np.float32)

    # Local ray vectors on plane at z = -1: (U, V, -1)
    local_rays = np.stack([U, V, -np.ones_like(U)], axis=-1)  # (W, W, 3)

    fwd = np.array(cam_forward, dtype=np.float32)
    fwd /= np.linalg.norm(fwd)

    face_weights = {}
    for face_name, v_mat, _ in faces:
        # Rotation matrix from camera local to world
        # V = R @ T => R_world = V[:3, :3].T (inverse of orthogonal rotation)
        R_world = np.array(v_mat.to_3x3().transposed(), dtype=np.float32)

        # World ray directions for all pixels
        world_rays = local_rays @ R_world.T  # (W, W, 3)
        lens = np.linalg.norm(world_rays, axis=-1, keepdims=True)
        world_dirs = world_rays / np.maximum(lens, 1e-12)

        # cos(angle) to default forward
        cos_ang = np.sum(world_dirs * fwd, axis=-1)

        # Direction weight: max(floor, cos(angle)^falloff)
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

    # Weight is 1.0 inside frustum; only solid angle applies
    d_omega = (dx * dy) / np.power(X * X + Y * Y + 1.0, 1.5).astype(np.float32)
    return d_omega


# ---------------------------------------------------------------------------
# Vectorized Analytical Solid Angle (Oosterom & Strackee 1983)
# ---------------------------------------------------------------------------

def batch_triangle_solid_angle(eye, V0, V1, V2):
    """Vectorized calculation of spherical solid angle for a batch of triangles.

    Returns solid angle in steradians [0, 2*pi] for front-facing triangles,
    or 0.0 for triangles turned away or edge-on (Decision 72).
    """
    eye_arr = np.array(eye, dtype=np.float32).reshape(1, 3)
    A = V0 - eye_arr
    B = V1 - eye_arr
    C = V2 - eye_arr

    # Surface normal
    N = np.cross(B - A, C - A)

    # Front-facing test: normal pointing towards camera
    # Vector from surface point V0 to camera eye is -A = eye - V0
    # N . (-A) > 0  <=>  N . A < 0
    front = np.sum(N * (-A), axis=-1) > 0.0

    normA = np.linalg.norm(A, axis=-1, keepdims=True)
    normB = np.linalg.norm(B, axis=-1, keepdims=True)
    normC = np.linalg.norm(C, axis=-1, keepdims=True)

    eps = 1e-12
    valid = (normA[..., 0] > eps) & (normB[..., 0] > eps) & (normC[..., 0] > eps) & front

    a = A / np.maximum(normA, eps)
    b = B / np.maximum(normB, eps)
    c = C / np.maximum(normC, eps)

    # det = a . (b x c)
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
# UV Island Extraction (Union-Find)
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


# ---------------------------------------------------------------------------
# Evaluated Scene Extraction with Material Splitting (Decision 77)
# ---------------------------------------------------------------------------

def extract_scene_geometry(depsgraph, view_layer):
    """Extract evaluated scene geometry split into Opaque and Decal batches.

    Returns:
    - batches: dict with 'opaque_pos', 'opaque_ids', 'decal_pos', 'decal_ids'
    - eval_poly_map: dict eval_id -> (mesh_name, orig_poly_idx, is_mirrored)
    - mesh_meta: dict mesh_name -> meta dict
    - tri_geometry: dict with 'V0', 'V1', 'V2', 'tri_ids' for analytical solid angle
    - max_id: int
    """
    opaque_pos = []
    opaque_ids = []
    decal_pos = []
    decal_ids = []

    all_tri_v0 = []
    all_tri_v1 = []
    all_tri_v2 = []
    all_tri_ids = []

    eval_poly_map = {}
    mesh_meta = {}

    mesh_objs = [
        o for o in view_layer.objects
        if o.type == 'MESH' and o.data and not o.hide_viewport and not o.hide_render
    ]

    global_id = 1

    for o in mesh_objs:
        if is_invisible_object(o):
            continue

        me_orig = o.data
        mesh_name = me_orig.name
        n_orig_faces = len(me_orig.polygons)
        if n_orig_faces == 0:
            continue

        if mesh_name not in mesh_meta:
            # Calculate 3D area of each original polygon
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

            mesh_meta[mesh_name] = {
                'n_orig_faces': n_orig_faces,
                'orig_areas': orig_areas,
                'island_ids': island_ids,
                'user_objects': [],
            }
        mesh_meta[mesh_name]['user_objects'].append(o.name)

        # Evaluated geometry
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

        # World coordinates of triangle corners
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

        # Check Mirror modifier
        has_mirror = any(m.type == 'MIRROR' for m in o.modifiers)
        for ep_idx in range(n_eval_polys):
            eid = base_id + ep_idx
            is_mirr = has_mirror and (ep_idx >= n_orig_faces)
            orig_idx = (ep_idx % n_orig_faces) if is_mirr else min(ep_idx, n_orig_faces - 1)
            eval_poly_map[eid] = (mesh_name, orig_idx, is_mirr)

        # Split loop triangles into Opaque, Decal, or Invisible
        tri_ids = base_id + poly_indices
        tri_mclasses = [poly_mat_class[pi] for pi in poly_indices]

        # Record triangle geometry for analytical solid angle
        all_tri_v0.append(P_world[:, 0, :])
        all_tri_v1.append(P_world[:, 1, :])
        all_tri_v2.append(P_world[:, 2, :])
        all_tri_ids.append(tri_ids)

        for tri_idx in range(n_lt):
            mcls = tri_mclasses[tri_idx]
            if mcls == 'INVISIBLE':
                continue
            tid = tri_ids[tri_idx]
            tri_p = P_world[tri_idx]  # (3, 3)
            tri_id_expanded = np.array([tid, tid, tid], dtype=np.int32)

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

    return batches, eval_poly_map, mesh_meta, tri_geometry, global_id


# ---------------------------------------------------------------------------
# Animation State Evaluation (Decision 69)
# ---------------------------------------------------------------------------

class AnimationStateController:
    """Manages normalized action/NLA percentage states across scene objects."""

    def __init__(self):
        self.original_states = []
        self.temp_tracks = []
        self._setup()

    def _setup(self):
        """Prepare all animated objects for normalized percentage evaluation."""
        for obj in bpy.data.objects:
            adata = obj.animation_data
            if not adata:
                continue

            # If object has an active action but no NLA strips, temporarily wrap it into an NLA track
            if adata.action and not adata.nla_tracks:
                act = adata.action
                tr = adata.nla_tracks.new()
                tr.name = "__FSS_TEMP_TRACK__"
                strip = tr.strips.new(act.name, int(act.frame_range[0]), act)
                adata.action = None
                self.temp_tracks.append((obj, tr, act))

            # Record all strips
            for tr in adata.nla_tracks:
                for strip in tr.strips:
                    self.original_states.append({
                        'strip': strip,
                        'frame_start': strip.frame_start,
                        'frame_end': strip.frame_end,
                        'scale': strip.scale,
                        'action_start': strip.action_frame_start,
                        'action_end': strip.action_frame_end,
                    })

    def apply_percentage_state(self, pct):
        """Shift strips so that at scene frame 0 each strip evaluates at pct [0.0, 1.0]."""
        p = float(pct) / 100.0 if pct > 1.0 else float(pct)
        for sinfo in self.original_states:
            strip = sinfo['strip']
            a_start = sinfo['action_start']
            a_end = sinfo['action_end']
            length = max(a_end - a_start, 1.0)
            target_f = a_start + p * length
            new_start = 0.0 - (target_f - a_start)
            strip.frame_start = new_start
            strip.frame_end = new_start + length
            strip.scale = 1.0

        bpy.context.scene.frame_set(0)

    def restore(self):
        """Clean teardown: restore original strip timing and remove temporary tracks."""
        for sinfo in self.original_states:
            strip = sinfo['strip']
            try:
                strip.frame_start = sinfo['frame_start']
                strip.frame_end = sinfo['frame_end']
                strip.scale = sinfo['scale']
            except ReferenceError:
                pass

        for obj, tr, act in self.temp_tracks:
            try:
                obj.animation_data.nla_tracks.remove(tr)
                obj.animation_data.action = act
            except ReferenceError:
                pass


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

        if batch_opaque is not None:
            batch_opaque.draw(shader)
            px = np.array(fb.read_color(0, 0, W, H, 4, 0, 'UBYTE'), dtype=np.uint8)
            ids = (
                px[..., 0].astype(np.int32)
                | (px[..., 1].astype(np.int32) << 8)
                | (px[..., 2].astype(np.int32) << 16)
            ).ravel()
            counts_opaque = np.bincount(ids, weights=weight_flat, minlength=max_id + 1)

        # Pass 2: Decal / Glass (depth_mask=False, depth_test=LESS_EQUAL)
        if batch_decal is not None:
            # Clear color only; keep depth buffer from Pass 1 intact!
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
# Core Analysis Engine
# ---------------------------------------------------------------------------

def analyze_visibility(
    blend_path,
    cameras=None,
    anim_states=(0.0, 0.5, 1.0),
    cube_res=1024,
    frustum_res=(2560, 1440),
    floor=0.2,
    falloff=1.0,
):
    """Execute complete visibility-based texel demand analysis (Round 2)."""
    gpu.init()
    shader = get_id_shader()

    # Default camera configuration if none provided
    if not cameras:
        pilot_cam = (
            bpy.data.objects.get('CAM_PILOT_CLOSE')
            or bpy.data.objects.get('CAM_PILOT')
            or [o for o in bpy.data.objects if o.type == 'CAMERA'][:1][0]
        )
        cameras = [
            {
                'name': pilot_cam.name,
                'type': 'LOOK_AROUND',
                'pos': pilot_cam.matrix_world.translation.copy(),
                'forward': get_camera_forward(pilot_cam),
            }
        ]
        copilot_cam = bpy.data.objects.get('CAM_COPILOT')
        if copilot_cam:
            cameras.append({
                'name': copilot_cam.name,
                'type': 'LOOK_AROUND',
                'pos': copilot_cam.matrix_world.translation.copy(),
                'forward': get_camera_forward(copilot_cam),
            })

    t_start = time.perf_counter()
    state_timings = {}

    mesh_results = {}
    off_cube = gpu.types.GPUOffScreen(cube_res, cube_res)
    off_frustum = gpu.types.GPUOffScreen(frustum_res[0], frustum_res[1])

    anim_ctrl = AnimationStateController()

    try:
        for state_val in anim_states:
            t_s0 = time.perf_counter()
            pct_label = f"{int(state_val * 100 if state_val <= 1.0 else state_val)}%"
            anim_ctrl.apply_percentage_state(state_val)

            dg = bpy.context.evaluated_depsgraph_get()
            batches, eval_poly_map, mesh_meta, tri_geom, max_id = extract_scene_geometry(
                dg, bpy.context.view_layer
            )

            # Build GPU batches
            batch_op = None
            if len(batches['opaque_pos']) > 0:
                batch_op = batch_for_shader(shader, 'TRIS', {
                    'pos': batches['opaque_pos'],
                    'face_id': batches['opaque_ids']
                })

            batch_dec = None
            if len(batches['decal_pos']) > 0:
                batch_dec = batch_for_shader(shader, 'TRIS', {
                    'pos': batches['decal_pos'],
                    'face_id': batches['decal_ids']
                })

            # Initialize mesh_results entry on first pass
            for m_name, meta in mesh_meta.items():
                if m_name not in mesh_results:
                    mesh_results[m_name] = {
                        'n_faces': meta['n_orig_faces'],
                        'orig_areas': meta['orig_areas'],
                        'island_ids': meta['island_ids'],
                        'face_scores': np.zeros(meta['n_orig_faces'], dtype=np.float32),
                        'user_objects': meta['user_objects'],
                    }

            # Render for each camera
            for cam in cameras:
                cam_name = cam['name']
                cam_type = cam['type']
                cam_pos = cam['pos']
                cam_fwd = cam.get('forward', Vector((0, -1, 0)))

                # 1. Compute analytical unoccluded solid angle from this camera position
                tri_omega = batch_triangle_solid_angle(
                    cam_pos, tri_geom['V0'], tri_geom['V1'], tri_geom['V2']
                )
                eval_unocc = np.bincount(
                    tri_geom['tri_ids'], weights=tri_omega, minlength=max_id + 1
                )

                eval_vis = np.zeros(max_id + 1, dtype=np.float64)

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

                # 2. Compute visible fraction score per evaluated polygon:
                # fraction = min(1.0, vis / unocc) if unocc > 1e-12 else 0.0
                valid_mask = eval_unocc > 1e-12
                eval_scores = np.zeros(max_id + 1, dtype=np.float32)
                eval_scores[valid_mask] = np.clip(
                    eval_vis[valid_mask] / eval_unocc[valid_mask], 0.0, 1.0
                ).astype(np.float32)

                # 3. Map back to original faces with max aggregation (Decisions 68 & 71)
                for eid, score in enumerate(eval_scores):
                    if score <= 0.0 or eid not in eval_poly_map:
                        continue
                    m_name, orig_idx, is_mirr = eval_poly_map[eid]
                    cur = mesh_results[m_name]['face_scores'][orig_idx]
                    if score > cur:
                        mesh_results[m_name]['face_scores'][orig_idx] = score

            state_timings[f"state_{pct_label}"] = time.perf_counter() - t_s0

    finally:
        anim_ctrl.restore()
        off_cube.free()
        off_frustum.free()

    total_time = time.perf_counter() - t_start

    # Aggregation & Island Statistics (Decisions 71, 74)
    total_faces = 0
    total_never_seen_faces = 0
    total_surface_area = 0.0
    total_never_seen_area = 0.0

    object_summaries = {}

    for m_name, m_data in mesh_results.items():
        scores = m_data['face_scores']
        areas = m_data['orig_areas']
        islands = m_data['island_ids']
        n_f = len(scores)
        total_faces += n_f

        unseen_mask = (scores <= 0.0)
        n_unseen = int(np.sum(unseen_mask))
        total_never_seen_faces += n_unseen

        m_area = float(np.sum(areas))
        m_unseen_area = float(np.sum(areas[unseen_mask]))
        total_surface_area += m_area
        total_never_seen_area += m_unseen_area

        # Area-weighted 90th percentile per UV island
        unique_islands = np.unique(islands)
        island_p90 = {}
        for isl_id in unique_islands:
            isl_mask = (islands == isl_id)
            isl_scores = scores[isl_mask]
            isl_areas = areas[isl_mask]
            isl_p90 = weighted_percentile(isl_scores, isl_areas, 0.90)
            island_p90[int(isl_id)] = isl_p90

        m_data['island_p90'] = island_p90

        # Object level summaries
        obj_p90 = weighted_percentile(scores, areas, 0.90)
        for obj_name in m_data['user_objects']:
            object_summaries[obj_name] = {
                'mesh_name': m_name,
                'p90_score': obj_p90,
                'seen_share': float(1.0 - (m_unseen_area / max(m_area, 1e-8))),
                'n_faces': n_f,
                'n_never_seen': n_unseen,
                'area_m2': m_area,
                'never_seen_area_m2': m_unseen_area,
            }

    # Demand percentiles across visible faces
    all_seen_scores = []
    all_seen_areas = []
    for m_data in mesh_results.values():
        vis = m_data['face_scores'] > 0.0
        if np.any(vis):
            all_seen_scores.extend(m_data['face_scores'][vis])
            all_seen_areas.extend(m_data['orig_areas'][vis])

    percentiles = {}
    if all_seen_scores:
        s_arr = np.array(all_seen_scores, dtype=np.float64)
        w_arr = np.array(all_seen_areas, dtype=np.float64)
        for p in [10, 25, 50, 75, 90, 95]:
            percentiles[f"p{p}"] = weighted_percentile(s_arr, w_arr, p / 100.0)

    never_seen_share = total_never_seen_faces / max(total_faces, 1)
    never_seen_area_share = total_never_seen_area / max(total_surface_area, 1e-8)

    results = {
        'blend_file': str(blend_path),
        'total_time_s': total_time,
        'state_timings': state_timings,
        'cameras': [c['name'] for c in cameras],
        'camera_configs': cameras,
        'anim_states': [float(s) for s in anim_states],
        'options': {'floor': floor, 'falloff': falloff, 'cube_res': cube_res},
        'total_faces': total_faces,
        'total_never_seen_faces': total_never_seen_faces,
        'never_seen_share': never_seen_share,
        'total_surface_area_m2': total_surface_area,
        'total_never_seen_area_m2': total_never_seen_area,
        'never_seen_area_share': never_seen_area_share,
        'score_percentiles': percentiles,
        'mesh_results': mesh_results,
        'object_summaries': object_summaries,
    }

    return results


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
# Storage: External .visibility File Version 2 (Decision 67)
# ---------------------------------------------------------------------------

def save_visibility_file(blend_path, results):
    """Save analysis results into compressed `<blend_name>.visibility` (Schema Version 2)."""
    vis_path = Path(blend_path).with_suffix('.visibility')

    meta = {
        'schema_version': 2,
        'blend_file': str(results['blend_file']),
        'timestamp': time.strftime("%Y-%m-%d %H:%M:%S"),
        'total_time_s': results['total_time_s'],
        'state_timings': results['state_timings'],
        'cameras': results['cameras'],
        'anim_states': results['anim_states'],
        'options': results['options'],
        'total_faces': results['total_faces'],
        'total_never_seen_faces': results['total_never_seen_faces'],
        'never_seen_share': results['never_seen_share'],
        'total_surface_area_m2': results['total_surface_area_m2'],
        'total_never_seen_area_m2': results['total_never_seen_area_m2'],
        'never_seen_area_share': results['never_seen_area_share'],
        'score_percentiles': results['score_percentiles'],
        'object_summaries': results['object_summaries'],
    }

    arrays_to_save = {
        '_meta_json': np.array([json.dumps(meta)]),
    }

    for m_name, m_data in results['mesh_results'].items():
        safe_name = m_name.replace('/', '_').replace('\\', '_')
        arrays_to_save[f"{safe_name}__score"] = m_data['face_scores'].astype(np.float32)
        arrays_to_save[f"{safe_name}__area"] = m_data['orig_areas'].astype(np.float32)
        arrays_to_save[f"{safe_name}__island"] = m_data['island_ids'].astype(np.int32)

    with open(vis_path, 'wb') as f:
        np.savez_compressed(f, **arrays_to_save)
    return vis_path


def load_visibility_file(vis_path):
    """Load `.visibility` file and return metadata and arrays."""
    data = np.load(vis_path)
    meta = json.loads(str(data['_meta_json'][0]))
    return meta, data


# ---------------------------------------------------------------------------
# Offscreen Heatmap Image Rendering (Graded 0..1, Magenta for Never-Seen)
# ---------------------------------------------------------------------------

def compute_heatmap_colors(scores):
    """Map visibility score in [0.0, 1.0] to RGBA colors.

    - 0.0 (never seen): Magenta (1.0, 0.0, 1.0, 1.0)
    - (0.0, 0.5]: Red (0.95, 0.15, 0.15) to Neutral Grey (0.92, 0.92, 0.92)
    - [0.5, 1.0]: Neutral Grey (0.92, 0.92, 0.92) to Blue (0.10, 0.35, 0.95)
    """
    n = len(scores)
    colors = np.empty((n, 4), dtype=np.float32)

    c_mag = np.array([1.0, 0.0, 1.0, 1.0], dtype=np.float32)
    c_red = np.array([0.95, 0.15, 0.15, 1.0], dtype=np.float32)
    c_neu = np.array([0.92, 0.92, 0.92, 1.0], dtype=np.float32)
    c_blue = np.array([0.10, 0.35, 0.95, 1.0], dtype=np.float32)

    unseen = (scores <= 0.0)
    colors[unseen] = c_mag

    seen = ~unseen
    if np.any(seen):
        s_vals = scores[seen]
        seen_idx = np.flatnonzero(seen)

        # Lower half: (0.0, 0.5] -> Red to Neutral
        low_mask = (s_vals <= 0.5)
        if np.any(low_mask):
            l_idx = seen_idx[low_mask]
            t = np.clip(s_vals[low_mask] / 0.5, 0.0, 1.0)[:, None]
            colors[l_idx] = (1.0 - t) * c_red + t * c_neu

        # Upper half: (0.5, 1.0] -> Neutral to Blue
        high_mask = (s_vals > 0.5)
        if np.any(high_mask):
            h_idx = seen_idx[high_mask]
            t = np.clip((s_vals[high_mask] - 0.5) / 0.5, 0.0, 1.0)[:, None]
            colors[h_idx] = (1.0 - t) * c_neu + t * c_blue

    return colors


def render_heatmap_image(output_path, mvp, res=(1920, 1080), view_normal_matrix=None, mesh_results=None):
    """Render the scene coloured by visibility score into a PNG image."""
    W, H = res
    shader = get_heatmap_render_shader()
    dg = bpy.context.evaluated_depsgraph_get()

    if view_normal_matrix is None:
        view_normal_matrix = Matrix.Identity(4)

    all_pos, all_nor, all_col = [], [], []

    mesh_objs = [
        o for o in bpy.context.view_layer.objects
        if o.type == 'MESH' and o.data and not o.hide_viewport and not o.hide_render
    ]

    for o in mesh_objs:
        if is_invisible_object(o):
            continue

        me_orig = o.data
        m_name = me_orig.name
        if mesh_results and m_name in mesh_results:
            scores = mesh_results[m_name]['face_scores']
        else:
            scores = np.zeros(len(me_orig.polygons), dtype=np.float32)

        poly_colors = compute_heatmap_colors(scores)

        eval_obj = o.evaluated_get(dg)
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

        # Normals
        N_tri = np.empty((n_lt, 3), dtype=np.float32)
        eval_me.loop_triangles.foreach_get('normal', N_tri.ravel())
        M_norm = np.linalg.inv(M_eval[:3, :3]).T
        N_world = N_tri @ M_norm.T
        norm_lens = np.linalg.norm(N_world, axis=-1, keepdims=True)
        N_world /= np.maximum(norm_lens, 1e-8)
        N_world_expanded = np.repeat(N_world[:, None, :], 3, axis=1)

        # Polygons mapping
        poly_indices = np.empty(n_lt, dtype=np.int32)
        eval_me.loop_triangles.foreach_get('polygon_index', poly_indices)
        orig_indices = poly_indices % len(poly_colors)
        tri_colors = poly_colors[orig_indices]
        tri_colors_expanded = np.repeat(tri_colors[:, None, :], 3, axis=1)

        all_pos.append(P_world.reshape(-1, 3))
        all_nor.append(N_world_expanded.reshape(-1, 3))
        all_col.append(tri_colors_expanded.reshape(-1, 4))
        eval_obj.to_mesh_clear()

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

def test_gltf_export(blend_path, scratch_dir):
    """Export glTF and verify that no visibility data or custom attributes bleed into glTF."""
    print("\n--- Verifying glTF Export Integrity ---")
    sys.stdout.flush()
    gltf_out = Path(scratch_dir) / "vis_export_test.gltf"
    if gltf_out.exists():
        gltf_out.unlink()

    try:
        bpy.ops.export_scene.gltf(
            filepath=str(gltf_out),
            export_format='GLTF_SEPARATE',
            use_selection=False,
            export_animations=False,
            export_skins=False,
            export_morph=False,
        )
    except Exception as e:
        print(f"glTF export call: {e}")
        return False

    if not gltf_out.exists():
        print("glTF file was not written!")
        return False

    with open(gltf_out, 'r', encoding='utf-8') as f:
        gltf_data = json.load(f)

    forbidden_terms = ['fss_texel_demand', 'visibility', '_fss_']
    found_leaks = []

    for m in gltf_data.get('meshes', []):
        for prim in m.get('primitives', []):
            for attr in prim.get('attributes', {}).keys():
                for term in forbidden_terms:
                    if term in attr.lower():
                        found_leaks.append(f"Primitive attribute leak: {attr}")

    for node in gltf_data.get('nodes', []):
        extras = node.get('extras', {})
        for k in extras:
            for term in forbidden_terms:
                if term in k.lower():
                    found_leaks.append(f"Node extras leak: {k}")

    if found_leaks:
        print(f"FAILED: Found visibility leaks in glTF: {found_leaks}")
        return False
    else:
        print("PASS: Verified that no visibility attributes or extras reach exported glTF!")
        return True


# ---------------------------------------------------------------------------
# Synthetic Test Scene Generator & Validator (7 Cases)
# ---------------------------------------------------------------------------

def build_synthetic_scene(blend_path):
    """Create synthetic test scene covering all 7 cases specified in Session 69."""
    bpy.ops.wm.read_homefile(use_empty=True)
    import bmesh

    # Pilot camera at origin looking along -Y (Euler: pitch down 90 deg, roll 180)
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
            # Facing +Y towards camera at origin
            v1 = bm.verts.new((-hw, 0, -hh))
            v2 = bm.verts.new((hw, 0, -hh))
            v3 = bm.verts.new((hw, 0, hh))
            v4 = bm.verts.new((-hw, 0, hh))
            bm.faces.new((v4, v3, v2, v1))
        elif normal_dir == '-Y':
            # Facing -Y away from camera
            v1 = bm.verts.new((-hw, 0, -hh))
            v2 = bm.verts.new((hw, 0, -hh))
            v3 = bm.verts.new((hw, 0, hh))
            v4 = bm.verts.new((-hw, 0, hh))
            bm.faces.new((v1, v2, v3, v4))
        elif normal_dir == '-X':
            # Facing -X towards origin from +X
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

    # -------------------------------------------------------------
    # Case 1: Distance-free equal scores at 0.5 m and 2.0 m
    # -------------------------------------------------------------
    create_quad_facing("CASE1_PANEL_NEAR", (0.025, 0.025), (0.0, -0.5, -0.10), '+Y')
    create_quad_facing("CASE1_PANEL_FAR",  (0.10, 0.10),   (0.0, -2.0,  0.40), '+Y')

    # -------------------------------------------------------------
    # Case 2: Half-covered panel (score ~ 0.50)
    # -------------------------------------------------------------
    create_quad_facing("CASE2_HALF_PANEL", (0.2, 0.2), (0.4, -2.0, 0.0), '+Y')
    create_quad_facing("CASE2_COVER_PLATE", (0.1, 0.2), (0.35, -1.999, 0.0), '+Y')

    # -------------------------------------------------------------
    # Case 3: Panel straight ahead (w=1.0) vs 90 deg side (w=0.20 floor)
    # -------------------------------------------------------------
    create_quad_facing("CASE3_PANEL_AHEAD", (0.2, 0.2), (0.0, -2.0, 0.0), '+Y')
    create_quad_facing("CASE3_PANEL_SIDE",  (0.2, 0.2), (2.0, 0.0, 0.0), '-X')

    # -------------------------------------------------------------
    # Case 4: Back face never seen (score = 0.000)
    # -------------------------------------------------------------
    create_quad_facing("CASE4_BACK_FACE", (0.2, 0.2), (0.0, -2.0, -0.8), '-Y')

    # -------------------------------------------------------------
    # Case 5: Invisible box hides nothing
    # -------------------------------------------------------------
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

    # -------------------------------------------------------------
    # Case 6: Decal does not hide its panel
    # -------------------------------------------------------------
    create_quad_facing("CASE6_OPAQUE_PANEL", (0.2, 0.2), (-0.8, -2.0, 0.8), '+Y', mat_name="PANEL_OPAQUE_MAT")
    create_quad_facing("CASE6_DECAL_QUAD", (0.15, 0.15), (-0.8, -1.98, 0.8), '+Y', mat_name="LABEL_DECAL")

    # -------------------------------------------------------------
    # Case 7: Animated action on frames 100 to 200
    # -------------------------------------------------------------
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

    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    return blend_path


def validate_synthetic_cases(results):
    """Verify all 7 synthetic cases pass assertions."""
    objs = results['object_summaries']
    mesh_res = results['mesh_results']

    print("\n" + "=" * 70)
    print("      SYNTHETIC VALIDATION (ROUND 2 - 7 CASES)")
    print("=" * 70)

    # Case 1: Distance-free equal scores at 0.5 m and 2.0 m
    s_near = objs["CASE1_PANEL_NEAR"]['p90_score']
    s_far  = objs["CASE1_PANEL_FAR"]['p90_score']
    print(f"Case 1 (Distance Invariance): Near (0.5m) = {s_near:.4f}, Far (2.0m) = {s_far:.4f}")
    assert s_near >= 0.90, f"Near panel score too low ({s_near:.4f})"
    assert s_far >= 0.90, f"Far panel score too low ({s_far:.4f})"
    assert abs(s_near - s_far) < 0.01, f"Distance discrepancy: {abs(s_near - s_far):.4f}"
    print("  -> PASS: Distance-free equal scores verified.")

    # Case 2: Half-covered panel (score ~ 0.50)
    s_half = objs["CASE2_HALF_PANEL"]['p90_score']
    print(f"Case 2 (Half-Covered Panel): Score = {s_half:.4f} (expected ~0.50)")
    assert 0.45 <= s_half <= 0.55, f"Half panel score out of range: {s_half:.4f}"
    print("  -> PASS: Half-covered panel receives ~0.50 visible fraction.")

    # Case 3: Straight ahead (w=1.0) vs 90 deg side (w=0.20 floor)
    s_ahead = objs["CASE3_PANEL_AHEAD"]['p90_score']
    s_side  = objs["CASE3_PANEL_SIDE"]['p90_score']
    print(f"Case 3 (Direction Weight): Ahead = {s_ahead:.4f}, Side (90°) = {s_side:.4f}")
    assert s_ahead >= 0.98, f"Straight ahead score too low: {s_ahead:.4f}"
    assert 0.18 <= s_side <= 0.22, f"Side score out of floor range: {s_side:.4f}"
    print("  -> PASS: Side view receives floor weight 0.20.")

    # Case 4: Back face never seen
    s_back = objs["CASE4_BACK_FACE"]['p90_score']
    print(f"Case 4 (Back Face): Score = {s_back:.4f} (expected 0.000)")
    assert s_back == 0.0, f"Back face must have score 0.0, got {s_back}"
    print("  -> PASS: Back face receives score 0.000 (never seen).")

    # Case 5: Invisible box hides nothing
    s_invis_target = objs["CASE5_TARGET_PANEL"]['p90_score']
    print(f"Case 5 (Invisible Box Occlusion): Target Panel Score = {s_invis_target:.4f}")
    assert s_invis_target >= 0.85, f"Invisible box occluded panel: {s_invis_target:.4f}"
    assert "CASE5_COLLISION_BOX" not in objs, "Invisible collision box should not be scored!"
    print("  -> PASS: Invisible box hides nothing and is omitted from scoring.")

    # Case 6: Decal does not hide its panel
    s_opaque = objs["CASE6_OPAQUE_PANEL"]['p90_score']
    s_decal  = objs["CASE6_DECAL_QUAD"]['p90_score']
    print(f"Case 6 (Decal on Panel): Opaque Panel = {s_opaque:.4f}, Decal = {s_decal:.4f}")
    assert s_opaque >= 0.80, f"Opaque panel occluded by decal: {s_opaque:.4f}"
    assert s_decal >= 0.80, f"Decal not scored: {s_decal:.4f}"
    assert abs(s_opaque - s_decal) < 0.05, f"Decal and opaque mismatch: {s_opaque} vs {s_decal}"
    print("  -> PASS: Decal is scored and does not occlude the panel behind it.")

    # Case 7: Animated action on frames 100 to 200
    s_lever  = objs["CASE7_ANIM_LEVER"]['p90_score']
    s_sensor = objs["CASE7_SENSOR_PANEL"]['p90_score']
    print(f"Case 7 (Action 100-200 Evaluation): Lever = {s_lever:.4f}, Sensor = {s_sensor:.4f}")
    assert s_lever >= 0.80, f"Lever score low: {s_lever:.4f}"
    assert s_sensor >= 0.80, f"Sensor uncovered at frame 100 must be seen, got {s_sensor:.4f}"
    print("  -> PASS: Action evaluated across its normalized percentage range.")

    print("\nALL 7 SYNTHETIC CASES PASSED SUCCESSFULLY!")
    print("=" * 70 + "\n")
    return True


# ---------------------------------------------------------------------------
# Cockpit Reporting & CLI
# ---------------------------------------------------------------------------

def print_cockpit_report(results):
    """Print detailed analysis report for the cockpit model."""
    print("\n" + "=" * 76)
    print("      VISIBILITY-BASED TEXEL DEMAND REPORT (E2 COCKPIT - ROUND 2)")
    print("=" * 76)
    print(f"File: {results['blend_file']}")
    print(f"Total Analysis Runtime: {results['total_time_s']:.2f} s ({results['total_time_s']/60:.2f} min)")
    print("State Timings:")
    for s_name, s_time in results['state_timings'].items():
        print(f"  - {s_name}: {s_time:.2f} s")
    print(f"Cameras Evaluated: {', '.join(results['cameras'])}")
    print(f"States Evaluated: {results['anim_states']}")
    print(f"Total Scene Faces: {results['total_faces']:,}")
    print(f"Never-Seen Faces: {results['total_never_seen_faces']:,} ({results['never_seen_share']*100:.2f}%)")
    print(f"Total 3D Surface Area: {results.get('total_surface_area_m2', 0.0):.2f} m²")
    print(f"Never-Seen 3D Area: {results.get('total_never_seen_area_m2', 0.0):.2f} m² ({results.get('never_seen_area_share', 0.0)*100:.2f}%)")

    print("\n--- Visibility Score Percentiles (Visible Faces, 0.0 to 1.0) ---")
    for p, val in results['score_percentiles'].items():
        print(f"  {p:>4}: {val:.4f}")

    objs = results['object_summaries']
    sorted_by_score = sorted(objs.items(), key=lambda item: item[1]['p90_score'])

    print("\n--- Bottom 20 Objects by Visibility Score ---")
    print(f"{'Object Name':<42} {'Score':<8} {'Seen %':<8} {'NeverSeen':<10} {'Faces':<8}")
    print("-" * 76)
    for name, data in sorted_by_score[:20]:
        print(f"{name:<42} {data['p90_score']:<8.4f} {data['seen_share']*100:<8.1f} {data['n_never_seen']:<10} {data['n_faces']:<8}")

    print("\n--- Top 20 Objects by Visibility Score (Direct Pilot View) ---")
    print(f"{'Object Name':<42} {'Score':<8} {'Seen %':<8} {'NeverSeen':<10} {'Faces':<8}")
    print("-" * 76)
    for name, data in sorted_by_score[-20:][::-1]:
        print(f"{name:<42} {data['p90_score']:<8.4f} {data['seen_share']*100:<8.1f} {data['n_never_seen']:<10} {data['n_faces']:<8}")

    fully_unseen = [name for name, data in objs.items() if data['seen_share'] == 0.0]
    print(f"\nTotal Objects Never Seen in Analysed Views and States: {len(fully_unseen)}")
    if fully_unseen:
        print("Sample objects never seen in analysed states (first 10):")
        for name in fully_unseen[:10]:
            print(f"  - {name} ({objs[name]['n_faces']} faces, area={objs[name]['area_m2']:.4f} m²)")
    print("=" * 76 + "\n")
    sys.stdout.flush()


def main():
    import argparse
    argv = sys.argv
    args_to_parse = argv[argv.index("--") + 1:] if "--" in argv else []

    parser = argparse.ArgumentParser(description="Texel Demand Prototype Round 2")
    parser.add_argument("--synthetic", action="store_true", help="Run synthetic validation")
    parser.add_argument("--cockpit", action="store_true", help="Run full cockpit analysis")
    parser.add_argument("--states", type=int, default=3, choices=[3, 5], help="Number of animation states (3 or 5)")
    parser.add_argument("--floor", type=float, default=0.2, help="Direction weight floor")
    parser.add_argument("--falloff", type=float, default=1.0, help="Direction weight falloff power")
    parser.add_argument("--cube-res", type=int, default=1024, help="Resolution per cube face")
    parser.add_argument("--out-dir", type=str, default="tests/_work/uv_visibility", help="Output directory")
    args = parser.parse_args(args_to_parse)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    anim_states = (0.0, 0.5, 1.0) if args.states == 3 else (0.0, 0.25, 0.5, 0.75, 1.0)

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
            }
        ]
        results = analyze_visibility(
            syn_blend, cameras=cameras, anim_states=anim_states,
            cube_res=512, floor=args.floor, falloff=args.falloff
        )
        vis_file = save_visibility_file(syn_blend, results)
        meta_loaded, _ = load_visibility_file(vis_file)
        assert meta_loaded['schema_version'] == 2
        validate_synthetic_cases(results)
        return

    if args.cockpit:
        blend_copy = out_dir / "COCKPIT_copy.blend"
        if not blend_copy.exists():
            raise FileNotFoundError(f"Cockpit copy not found at {blend_copy}")

        print(f"\nStarting Visibility Analysis on {blend_copy}...")
        pilot_cam = (
            bpy.data.objects.get('CAM_PILOT_CLOSE')
            or bpy.data.objects.get('CAM_PILOT')
        )
        copilot_cam = bpy.data.objects.get('CAM_COPILOT')

        cameras = []
        if pilot_cam:
            cameras.append({
                'name': pilot_cam.name,
                'type': 'LOOK_AROUND',
                'pos': pilot_cam.matrix_world.translation.copy(),
                'forward': get_camera_forward(pilot_cam),
            })
        if copilot_cam:
            cameras.append({
                'name': copilot_cam.name,
                'type': 'LOOK_AROUND',
                'pos': copilot_cam.matrix_world.translation.copy(),
                'forward': get_camera_forward(copilot_cam),
            })

        results = analyze_visibility(
            blend_copy,
            cameras=cameras,
            anim_states=anim_states,
            cube_res=args.cube_res,
            floor=args.floor,
            falloff=args.falloff,
        )

        # Save and verify .visibility file
        vis_file = save_visibility_file(blend_copy, results)
        print(f"Saved visibility results to: {vis_file}")
        meta_loaded, _ = load_visibility_file(vis_file)
        assert meta_loaded['total_faces'] == results['total_faces']

        # Print detailed report
        print_cockpit_report(results)

        # Render offscreen heatmap images
        print("Rendering offscreen heatmap images...")
        sys.stdout.flush()
        dg = bpy.context.evaluated_depsgraph_get()

        # 1. Pilot View
        if pilot_cam:
            proj = pilot_cam.calc_matrix_camera(dg, x=1920, y=1080)
            view = pilot_cam.matrix_world.inverted()
            mvp_pilot = proj @ view
            norm_mat = view.to_3x3().inverted().transposed().to_4x4()
            pilot_png = out_dir / "pilot_demand.png"
            render_heatmap_image(
                pilot_png, mvp_pilot, res=(1920, 1080),
                view_normal_matrix=norm_mat,
                mesh_results=results['mesh_results']
            )
            print(f"Saved Pilot Heatmap Image: {pilot_png}")

        # 2. Outside View (isometric overview looking into cockpit)
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
            mesh_results=results['mesh_results']
        )
        print(f"Saved Outside Heatmap Image: {outside_png}")

        # Test glTF export integrity
        test_gltf_export(blend_copy, out_dir)


if __name__ == "__main__":
    main()
