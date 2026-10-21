"""Visibility-based Texel Density (Texel Demand) Prototype for Blender 5.2.

Features:
- GPU Face-ID rendering via offscreen framebuffer (background Blender compatible).
- Look-around camera mode (6-face cube map) and Fixed-view camera mode (frustum).
- Mirror modifier handling (Option 2B: evaluated geometry, mirrored faces mapped to original).
- 3 animation passes at 0%, 50%, and 100% travel (Option 3A).
- Reference demand from primary forward view (Option 4B).
- Aggregation: MAX per face across views/passes; area-weighted 90th percentile per object (Option 5).
- Storage: external `<blend_name>.visibility` file alongside the .blend (Option 1).
- Never-seen face detection and delete candidate reporting.
- Heatmap image offscreen rendering (pilot view and outside view).
- Synthetic test validation on known cases.
"""

import os
import sys
import math
import time
import json
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

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Math & Matrix Helpers
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


def cubemap_face_matrices(cam_pos, near=0.05, far=20.0):
    """Return 6 (name, view_matrix, proj_matrix) for a cube map around cam_pos.

    Directions:
    - Forward (-Y in cockpit, up +Z)
    - Backward (+Y in cockpit, up +Z)
    - Left (-X, up +Z)
    - Right (+X, up +Z)
    - Up (+Z, up -Y)
    - Down (-Z, up +Y)
    """
    proj = perspective_proj(math.radians(90.0), 1.0, near, far)
    p = Vector(cam_pos)
    faces = [
        ("FORWARD",  look_at(p, p + Vector((0, -1, 0)), Vector((0, 0, 1))), proj),
        ("BACKWARD", look_at(p, p + Vector((0, 1, 0)),  Vector((0, 0, 1))), proj),
        ("LEFT",     look_at(p, p + Vector((-1, 0, 0)), Vector((0, 0, 1))), proj),
        ("RIGHT",    look_at(p, p + Vector((1, 0, 0)),  Vector((0, 0, 1))), proj),
        ("UP",       look_at(p, p + Vector((0, 0, 1)),  Vector((0, -1, 0))), proj),
        ("DOWN",     look_at(p, p + Vector((0, 0, -1)), Vector((0, 1, 0))), proj),
    ]
    return faces


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
# Scene Geometry Extraction & Mirror Mapping (Option 2B)
# ---------------------------------------------------------------------------

def extract_scene_geometry(depsgraph, view_layer):
    """Extract evaluated loop-triangles with global IDs and Mirror mappings.

    Returns:
    - pos_array: np.ndarray (N_verts, 3) float32
    - id_array: np.ndarray (N_verts,) int32
    - eval_poly_map: dict eval_id -> (mesh_name, orig_poly_idx, is_mirrored)
    - mesh_meta: dict mesh_name -> {
          'n_orig_faces': int,
          'orig_areas': np.ndarray (n_orig_faces,) float32,
          'user_objects': list of str,
      }
    - max_id: int
    """
    all_pos = []
    all_ids = []
    eval_poly_map = {}
    mesh_meta = {}

    mesh_objs = [
        o for o in view_layer.objects
        if o.type == 'MESH' and o.data and not o.hide_viewport and not o.hide_render
    ]

    global_id = 1

    for o in mesh_objs:
        me_orig = o.data
        mesh_name = me_orig.name
        n_orig_faces = len(me_orig.polygons)
        if n_orig_faces == 0:
            continue

        if mesh_name not in mesh_meta:
            # Calculate world 3D area for each original polygon
            # Use base mesh vertices scaled by object transform (or average object transform)
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
                    # Newell's formula or fan triangulation for quad/n-gon
                    poly_area = 0.0
                    for vi in range(1, len(p_verts) - 1):
                        e1 = p_verts[vi] - p_verts[0]
                        e2 = p_verts[vi + 1] - p_verts[0]
                        poly_area += 0.5 * np.linalg.norm(np.cross(e1, e2))
                    orig_areas[i] = poly_area

            mesh_meta[mesh_name] = {
                'n_orig_faces': n_orig_faces,
                'orig_areas': orig_areas,
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

        # Polygons of loop triangles
        poly_indices = np.empty(n_lt, dtype=np.int32)
        eval_me.loop_triangles.foreach_get('polygon_index', poly_indices)

        n_eval_polys = len(eval_me.polygons)
        base_id = global_id

        # Loop triangles IDs
        tri_ids = base_id + poly_indices
        tri_ids_expanded = np.repeat(tri_ids, 3)

        all_pos.append(P_world.reshape(-1, 3))
        all_ids.append(tri_ids_expanded)

        # Map each evaluated polygon back to original polygon
        has_mirror = any(m.type == 'MIRROR' for m in o.modifiers)
        for ep_idx in range(n_eval_polys):
            eid = base_id + ep_idx
            if has_mirror and ep_idx >= n_orig_faces:
                orig_idx = ep_idx % n_orig_faces
                is_mirrored = True
            else:
                orig_idx = min(ep_idx, n_orig_faces - 1)
                is_mirrored = False
            eval_poly_map[eid] = (mesh_name, orig_idx, is_mirrored)

        global_id += n_eval_polys
        eval_obj.to_mesh_clear()

    if all_pos:
        pos_cat = np.concatenate(all_pos, axis=0)
        ids_cat = np.concatenate(all_ids, axis=0)
    else:
        pos_cat = np.zeros((0, 3), dtype=np.float32)
        ids_cat = np.zeros(0, dtype=np.int32)

    return pos_cat, ids_cat, eval_poly_map, mesh_meta, global_id


# ---------------------------------------------------------------------------
# Offscreen Render & Pixel Counting
# ---------------------------------------------------------------------------

def render_and_count_ids(offscreen, shader, batch, mvp, max_id):
    """Draw batch into offscreen framebuffer and return pixel counts per ID."""
    W, H = offscreen.width, offscreen.height
    with offscreen.bind():
        fb = gpu.state.active_framebuffer_get()
        fb.clear(color=(0, 0, 0, 1), depth=1.0)
        gpu.state.depth_test_set('LESS_EQUAL')
        gpu.state.depth_mask_set(True)
        shader.bind()
        shader.uniform_float('mvp', mvp)
        batch.draw(shader)
        gpu.state.depth_test_set('NONE')
        px = np.array(fb.read_color(0, 0, W, H, 4, 0, 'UBYTE'), dtype=np.uint8)

    # Decode RGB -> 24-bit ID
    ids = (
        px[..., 0].astype(np.int32)
        | (px[..., 1].astype(np.int32) << 8)
        | (px[..., 2].astype(np.int32) << 16)
    )
    counts = np.bincount(ids.ravel(), minlength=max_id + 1)
    return counts


# ---------------------------------------------------------------------------
# Core Analysis Engine
# ---------------------------------------------------------------------------

def analyze_visibility(
    blend_path,
    cameras=None,
    anim_passes=(0, 50, 100),
    cube_res=1024,
    frustum_res=(2560, 1440),
):
    """Execute complete texel demand analysis on a .blend scene.

    Parameters:
    - blend_path: Path to the .blend file (working copy)
    - cameras: list of camera dicts, e.g.:
        [
          {'name': 'CAM_PILOT_CLOSE', 'type': 'LOOK_AROUND'},
          {'name': 'CAM_PEDESTAL', 'type': 'FIXED_VIEW', 'obj': ...}
        ]
    - anim_passes: tuple of frame percentages (e.g. (0, 50, 100))
    - cube_res: resolution per cube face for LOOK_AROUND
    - frustum_res: (W, H) for FIXED_VIEW

    Returns: results dict.
    """
    gpu.init()
    shader = get_id_shader()
    scene = bpy.context.scene

    # Default camera setup if none provided
    if not cameras:
        # Check for cockpit pilot camera
        pilot_cam = (
            bpy.data.objects.get('CAM_PILOT_CLOSE')
            or bpy.data.objects.get('CAM_PILOT')
            or [o for o in bpy.data.objects if o.type == 'CAMERA'][:1][0]
        )
        cameras = [
            {'name': pilot_cam.name, 'type': 'LOOK_AROUND', 'pos': pilot_cam.matrix_world.translation.copy()},
        ]
        # Add a quickview camera if available or create virtual pedestal look
        quick_cam = bpy.data.objects.get('CAM_COPILOT')
        if quick_cam:
            cameras.append({
                'name': quick_cam.name,
                'type': 'FIXED_VIEW',
                'obj_name': quick_cam.name,
            })

    t_start = time.perf_counter()
    pass_timings = {}

    # Aggregated visible pixels per evaluated ID across passes:
    # We maintain max visible pixels per original face
    # mesh_name -> {
    #   'pixels_orig': np.ndarray,
    #   'pixels_mirr': np.ndarray,
    #   'pass_max_pixels': np.ndarray,
    # }
    mesh_results = {}

    # Offscreen buffers
    off_cube = gpu.types.GPUOffScreen(cube_res, cube_res)
    off_frustum = gpu.types.GPUOffScreen(frustum_res[0], frustum_res[1])

    # Reference demand tracker: collects demands of faces seen in pilot forward view at t=0
    forward_view_demands = []

    try:
        for pass_pct in anim_passes:
            t_pass0 = time.perf_counter()
            frame_num = int(pass_pct)
            scene.frame_set(frame_num)
            dg = bpy.context.evaluated_depsgraph_get()

            # Extract evaluated geometry for this animation frame
            pos_cat, ids_cat, eval_poly_map, mesh_meta, max_id = extract_scene_geometry(
                dg, bpy.context.view_layer
            )
            if len(pos_cat) == 0:
                continue

            batch = batch_for_shader(shader, 'TRIS', {'pos': pos_cat, 'face_id': ids_cat})

            # Initialize mesh_results entry on first pass
            for m_name, meta in mesh_meta.items():
                if m_name not in mesh_results:
                    mesh_results[m_name] = {
                        'n_faces': meta['n_orig_faces'],
                        'orig_areas': meta['orig_areas'],
                        'max_pixels': np.zeros(meta['n_orig_faces'], dtype=np.int32),
                        'max_demand_raw': np.zeros(meta['n_orig_faces'], dtype=np.float32),
                        'user_objects': meta['user_objects'],
                    }

            # Render for each camera
            for cam in cameras:
                cam_name = cam['name']
                cam_type = cam['type']

                if cam_type == 'LOOK_AROUND':
                    cam_pos = cam['pos']
                    faces = cubemap_face_matrices(cam_pos)
                    for face_name, v_mat, p_mat in faces:
                        mvp = p_mat @ v_mat
                        counts = render_and_count_ids(off_cube, shader, batch, mvp, max_id)

                        # Accumulate pixels into evaluated polygons
                        # Track per original face
                        # For Option 2B: separate original half from mirrored half
                        face_orig_counts = {}  # m_name -> np.array
                        face_mirr_counts = {}

                        for eid, px_count in enumerate(counts):
                            if px_count == 0 or eid not in eval_poly_map:
                                continue
                            m_name, orig_idx, is_mirr = eval_poly_map[eid]
                            if m_name not in face_orig_counts:
                                n_f = mesh_results[m_name]['n_faces']
                                face_orig_counts[m_name] = np.zeros(n_f, dtype=np.int32)
                                face_mirr_counts[m_name] = np.zeros(n_f, dtype=np.int32)

                            if is_mirr:
                                face_mirr_counts[m_name][orig_idx] += px_count
                            else:
                                face_orig_counts[m_name][orig_idx] += px_count

                        # Option 2B: max between original and mirrored halves
                        for m_name in face_orig_counts:
                            c_orig = face_orig_counts[m_name]
                            c_mirr = face_mirr_counts[m_name]
                            effective_counts = np.maximum(c_orig, c_mirr)

                            # Update max pixels across camera faces and passes
                            mesh_results[m_name]['max_pixels'] = np.maximum(
                                mesh_results[m_name]['max_pixels'], effective_counts
                            )

                            # Calculate raw demand (pixels / area)
                            areas = mesh_results[m_name]['orig_areas']
                            valid_area = areas > 1e-8
                            raw_d = np.zeros_like(areas)
                            raw_d[valid_area] = effective_counts[valid_area] / areas[valid_area]
                            mesh_results[m_name]['max_demand_raw'] = np.maximum(
                                mesh_results[m_name]['max_demand_raw'], raw_d
                            )

                            # If forward face of pilot camera at pass 0: collect for Option 4B reference
                            if pass_pct == 0 and face_name == "FORWARD" and cam_name.startswith("CAM_PILOT"):
                                vis_mask = valid_area & (effective_counts > 0)
                                if np.any(vis_mask):
                                    for d_val, a_val in zip(raw_d[vis_mask], areas[vis_mask]):
                                        forward_view_demands.append((d_val, a_val))

                elif cam_type == 'FIXED_VIEW':
                    cam_obj = bpy.data.objects.get(cam['obj_name'])
                    if cam_obj:
                        p_mat = cam_obj.calc_matrix_camera(dg, x=frustum_res[0], y=frustum_res[1])
                        v_mat = cam_obj.matrix_world.inverted()
                        mvp = p_mat @ v_mat
                        counts = render_and_count_ids(off_frustum, shader, batch, mvp, max_id)

                        face_orig_counts = {}
                        face_mirr_counts = {}
                        for eid, px_count in enumerate(counts):
                            if px_count == 0 or eid not in eval_poly_map:
                                continue
                            m_name, orig_idx, is_mirr = eval_poly_map[eid]
                            if m_name not in face_orig_counts:
                                n_f = mesh_results[m_name]['n_faces']
                                face_orig_counts[m_name] = np.zeros(n_f, dtype=np.int32)
                                face_mirr_counts[m_name] = np.zeros(n_f, dtype=np.int32)

                            if is_mirr:
                                face_mirr_counts[m_name][orig_idx] += px_count
                            else:
                                face_orig_counts[m_name][orig_idx] += px_count

                        for m_name in face_orig_counts:
                            effective_counts = np.maximum(face_orig_counts[m_name], face_mirr_counts[m_name])
                            mesh_results[m_name]['max_pixels'] = np.maximum(
                                mesh_results[m_name]['max_pixels'], effective_counts
                            )
                            areas = mesh_results[m_name]['orig_areas']
                            valid_area = areas > 1e-8
                            raw_d = np.zeros_like(areas)
                            raw_d[valid_area] = effective_counts[valid_area] / areas[valid_area]
                            mesh_results[m_name]['max_demand_raw'] = np.maximum(
                                mesh_results[m_name]['max_demand_raw'], raw_d
                            )

            pass_timings[f"pass_{pass_pct}%"] = time.perf_counter() - t_pass0

    finally:
        off_cube.free()
        off_frustum.free()

    total_time = time.perf_counter() - t_start

    # Option 4B: Compute Reference Demand (Area-weighted median of forward view)
    if forward_view_demands:
        d_arr = np.array([x[0] for x in forward_view_demands], dtype=np.float64)
        w_arr = np.array([x[1] for x in forward_view_demands], dtype=np.float64)
        order = np.argsort(d_arr)
        cum_w = np.cumsum(w_arr[order])
        cutoff = 0.5 * cum_w[-1]
        idx = min(int(np.searchsorted(cum_w, cutoff)), len(order) - 1)
        ref_demand_raw = float(d_arr[order[idx]])
    else:
        # Fallback to overall visible median
        all_d, all_w = [], []
        for m_data in mesh_results.values():
            vis = m_data['max_demand_raw'] > 0
            all_d.extend(m_data['max_demand_raw'][vis])
            all_w.extend(m_data['orig_areas'][vis])
        if all_d:
            all_d = np.array(all_d)
            all_w = np.array(all_w)
            order = np.argsort(all_d)
            cum_w = np.cumsum(all_w[order])
            idx = min(int(np.searchsorted(cum_w, 0.5 * cum_w[-1])), len(order) - 1)
            ref_demand_raw = float(all_d[order[idx]])
        else:
            ref_demand_raw = 1000.0

    if ref_demand_raw <= 0:
        ref_demand_raw = 1000.0

    # Compute Relative Demand per face: sqrt(raw_demand / ref_demand_raw)
    total_faces = 0
    total_never_seen_faces = 0
    total_surface_area = 0.0
    total_suggested_texture_area = 0.0

    object_suggestions = {}

    for m_name, m_data in mesh_results.items():
        raw_d = m_data['max_demand_raw']
        areas = m_data['orig_areas']
        n_f = len(raw_d)
        total_faces += n_f

        # Relative linear demand: 1.0 is neutral
        rel_demand = np.zeros_like(raw_d)
        vis_mask = raw_d > 0
        never_seen_count = np.sum(~vis_mask)
        total_never_seen_faces += never_seen_count

        rel_demand[vis_mask] = np.sqrt(raw_d[vis_mask] / ref_demand_raw)
        m_data['relative_demand'] = rel_demand

        # Compute per-object statistics (Option 5: area-weighted 90th percentile)
        for obj_name in m_data['user_objects']:
            obj_area = float(np.sum(areas))
            total_surface_area += obj_area

            if np.any(vis_mask):
                vis_d = rel_demand[vis_mask]
                vis_w = areas[vis_mask]
                order = np.argsort(vis_d)
                cum_w = np.cumsum(vis_w[order])
                cutoff = 0.90 * cum_w[-1]
                idx = min(int(np.searchsorted(cum_w, cutoff)), len(order) - 1)
                suggested_density = float(vis_d[order[idx]])
                seen_share = float(np.sum(vis_w) / max(obj_area, 1e-8))
            else:
                suggested_density = 0.5  # minimum density for completely unseen object
                seen_share = 0.0

            clamped_density = float(np.clip(suggested_density, 0.5, 1.1))
            total_suggested_texture_area += (clamped_density ** 2) * obj_area

            object_suggestions[obj_name] = {
                'mesh_name': m_name,
                'suggested_density': suggested_density,
                'clamped_density': clamped_density,
                'seen_share': seen_share,
                'n_faces': n_f,
                'n_never_seen': int(never_seen_count),
                'area': obj_area,
            }

    # Total never seen 3D area
    total_never_seen_area = 0.0
    for m_data in mesh_results.values():
        unseen = m_data['relative_demand'] <= 0
        total_never_seen_area += float(np.sum(m_data['orig_areas'][unseen]))

    never_seen_area_share = (
        total_never_seen_area / max(total_surface_area, 1e-8)
        if total_surface_area > 0 else 0.0
    )

    # Area savings against uniform density (factor = 1.0) with clamped density [0.5, 1.1]
    texture_area_savings = (
        1.0 - (total_suggested_texture_area / max(total_surface_area, 1e-8))
        if total_surface_area > 0 else 0.0
    )

    # Compute demand percentiles across all visible faces
    all_rel_demands = []
    all_rel_weights = []
    for m_data in mesh_results.values():
        vis = m_data['relative_demand'] > 0
        if np.any(vis):
            all_rel_demands.extend(m_data['relative_demand'][vis])
            all_rel_weights.extend(m_data['orig_areas'][vis])

    percentiles = {}
    if all_rel_demands:
        d_arr = np.array(all_rel_demands, dtype=np.float64)
        w_arr = np.array(all_rel_weights, dtype=np.float64)
        order = np.argsort(d_arr)
        cum_w = np.cumsum(w_arr[order])
        total_w = cum_w[-1]
        for p in [10, 25, 50, 75, 90, 95]:
            cutoff = (p / 100.0) * total_w
            idx = min(int(np.searchsorted(cum_w, cutoff)), len(order) - 1)
            percentiles[f"p{p}"] = float(d_arr[order[idx]])

    never_seen_share = total_never_seen_faces / max(total_faces, 1)

    results = {
        'blend_file': str(blend_path),
        'total_time_s': total_time,
        'pass_timings': pass_timings,
        'cameras': [c['name'] for c in cameras],
        'total_faces': total_faces,
        'total_never_seen_faces': total_never_seen_faces,
        'never_seen_share': never_seen_share,
        'total_surface_area_m2': total_surface_area,
        'total_never_seen_area_m2': total_never_seen_area,
        'never_seen_area_share': never_seen_area_share,
        'ref_demand_raw': ref_demand_raw,
        'demand_percentiles': percentiles,
        'texture_area_savings_pct': texture_area_savings * 100.0,
        'mesh_results': mesh_results,
        'object_suggestions': object_suggestions,
    }

    return results


# ---------------------------------------------------------------------------
# Storage: External .visibility File (Option 1)
# ---------------------------------------------------------------------------

def save_visibility_file(blend_path, results):
    """Save results as compressed `<blend_basename>.visibility` alongside the .blend."""
    vis_path = Path(blend_path).with_suffix('.visibility')

    meta = {
        'blend_file': results['blend_file'],
        'timestamp': time.strftime("%Y-%m-%d %H:%M:%S"),
        'total_time_s': results['total_time_s'],
        'cameras': results['cameras'],
        'ref_demand_raw': results['ref_demand_raw'],
        'total_faces': results['total_faces'],
        'never_seen_share': results['never_seen_share'],
        'demand_percentiles': results['demand_percentiles'],
        'texture_area_savings_pct': results['texture_area_savings_pct'],
    }

    arrays_to_save = {
        '_meta_json': np.array([json.dumps(meta)]),
    }

    for m_name, m_data in results['mesh_results'].items():
        safe_name = m_name.replace('/', '_').replace('\\', '_')
        arrays_to_save[f"{safe_name}__demand"] = m_data['relative_demand'].astype(np.float32)
        arrays_to_save[f"{safe_name}__pixels"] = m_data['max_pixels'].astype(np.int32)
        arrays_to_save[f"{safe_name}__area"] = m_data['orig_areas'].astype(np.float32)

    with open(vis_path, 'wb') as f:
        np.savez_compressed(f, **arrays_to_save)
    return vis_path


def load_visibility_file(vis_path):
    """Load a `.visibility` file and return meta and arrays."""
    data = np.load(vis_path)
    meta = json.loads(str(data['_meta_json'][0]))
    return meta, data


# ---------------------------------------------------------------------------
# Offscreen Heatmap Image Rendering
# ---------------------------------------------------------------------------

def compute_heatmap_colors(rel_demands):
    """Map relative demand to RGBA colors matching UV Heatmap scheme."""
    n = len(rel_demands)
    colors = np.empty((n, 4), dtype=np.float32)

    # 0 = never seen: dark slate grey
    unseen = rel_demands <= 0
    colors[unseen] = [0.25, 0.25, 0.28, 1.0]

    seen = ~unseen
    if np.any(seen):
        d = rel_demands[seen]
        log_d = np.log2(np.maximum(d, 1e-4))

        # Under 1.0 (down to 0.5): red to neutral
        under = log_d < 0
        t_under = np.clip(log_d[under], -1.0, 0.0) + 1.0  # 0 at d=0.5, 1 at d=1.0
        c_red = np.array([0.95, 0.15, 0.15, 1.0], dtype=np.float32)
        c_neu = np.array([0.92, 0.92, 0.92, 1.0], dtype=np.float32)
        c_blue = np.array([0.10, 0.35, 0.95, 1.0], dtype=np.float32)

        seen_indices = np.flatnonzero(seen)
        if np.any(under):
            u_idx = seen_indices[under]
            colors[u_idx] = (1.0 - t_under[:, None]) * c_red + t_under[:, None] * c_neu

        # Over 1.0 (up to 2.0+): neutral to blue
        over = log_d >= 0
        if np.any(over):
            o_idx = seen_indices[over]
            t_over = np.clip(log_d[over], 0.0, 1.0)  # 0 at d=1.0, 1 at d=2.0
            colors[o_idx] = (1.0 - t_over[:, None]) * c_neu + t_over[:, None] * c_blue

    return colors


def render_heatmap_image(output_path, mvp, res=(1920, 1080), view_normal_matrix=None, mesh_results=None):
    """Render the scene coloured by texel demand into a PNG file."""
    W, H = res
    shader = get_heatmap_render_shader()
    dg = bpy.context.evaluated_depsgraph_get()

    if view_normal_matrix is None:
        view_normal_matrix = Matrix.Identity(4)

    # Collect all triangles with their demand colours and normals
    all_pos, all_nor, all_col = [], [], []

    mesh_objs = [
        o for o in bpy.context.view_layer.objects
        if o.type == 'MESH' and o.data and not o.hide_viewport and not o.hide_render
    ]

    for o in mesh_objs:
        me_orig = o.data
        m_name = me_orig.name
        if mesh_results and m_name in mesh_results:
            rel_d = mesh_results[m_name]['relative_demand']
        else:
            rel_d = np.zeros(len(me_orig.polygons), dtype=np.float32)

        poly_colors = compute_heatmap_colors(rel_d)

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
        # Transform normals by upper 3x3 of matrix_world
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

    # Save via Blender image API
    abs_path = os.path.abspath(str(output_path))
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    img_name = f"heat_render_{Path(output_path).stem}"
    img = bpy.data.images.new(img_name, W, H, float_buffer=True)
    img.pixels.foreach_set(px.ravel())
    img.filepath_raw = abs_path
    img.file_format = 'PNG'
    img.save()
    bpy.data.images.remove(img)
    return True


# ---------------------------------------------------------------------------
# glTF Export Verification Check
# ---------------------------------------------------------------------------

def test_gltf_export(blend_path, scratch_dir):
    """Export glTF and verify that no visibility data or custom attributes bleed into glTF."""
    print("\n--- Verifying glTF Export Integrity ---")
    sys.stdout.flush()
    gltf_out = Path(scratch_dir) / "vis_export_test.gltf"
    if gltf_out.exists():
        gltf_out.unlink()

    # Fast export without animations/skins (only meshes/nodes needed for attribute check)
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

    # Inspect glTF json
    with open(gltf_out, 'r', encoding='utf-8') as f:
        gltf_data = json.load(f)

    # Check meshes and primitives for custom visibility attributes
    forbidden_terms = ['fss_texel_demand', 'visibility', '_fss_']
    found_leaks = []

    for m in gltf_data.get('meshes', []):
        for prim in m.get('primitives', []):
            for attr in prim.get('attributes', {}).keys():
                for term in forbidden_terms:
                    if term in attr.lower():
                        found_leaks.append(f"Primitive attribute leak: {attr}")

    # Check extras
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
# Synthetic Test Scene Generator & Validator
# ---------------------------------------------------------------------------

def build_synthetic_scene(blend_path):
    """Create a synthetic scene testing the 4 known visibility cases."""
    bpy.ops.wm.read_homefile(use_empty=True)
    import bmesh

    # 1. Pilot Camera at (0, 0, 0) looking along -Y
    cam_data = bpy.data.cameras.new("CAM_PILOT_CLOSE")
    cam_data.lens = 28.0
    cam_obj = bpy.data.objects.new("CAM_PILOT_CLOSE", cam_data)
    cam_obj.location = Vector((0, 0, 0))
    cam_obj.rotation_euler = (math.radians(-90), 0, math.radians(180))  # look along -Y, up +Z
    bpy.context.scene.collection.objects.link(cam_obj)

    # Helper: create quad mesh
    def create_quad(name, size, loc, rot_euler=(0, 0, 0)):
        me = bpy.data.meshes.new(name + "_Mesh")
        bm = bmesh.new()
        hw, hh = size[0] / 2.0, size[1] / 2.0
        v1 = bm.verts.new((-hw, 0, -hh))
        v2 = bm.verts.new((hw, 0, -hh))
        v3 = bm.verts.new((hw, 0, hh))
        v4 = bm.verts.new((-hw, 0, hh))
        bm.faces.new((v1, v2, v3, v4))
        bm.to_mesh(me)
        bm.free()
        obj = bpy.data.objects.new(name, me)
        obj.location = Vector(loc)
        obj.rotation_euler = rot_euler
        bpy.context.scene.collection.objects.link(obj)
        return obj

    # Case 1: Front face vs Back face
    # Front panel facing camera (+Y facing front) at (0, -2, 0)
    # A thin box at (0, -2, 0) with front face at Y=-1.99 and back face at Y=-2.01
    me1 = bpy.data.meshes.new("CASE1_BOX_Mesh")
    bm1 = bmesh.new()
    # Front face at y=-1.95, back face at y=-2.05
    bmesh.ops.create_cube(bm1, size=0.5)
    bm1.to_mesh(me1)
    bm1.free()
    obj1 = bpy.data.objects.new("CASE1_FRONT_BACK_BOX", me1)
    obj1.location = Vector((0, -2.0, 0))
    bpy.context.scene.collection.objects.link(obj1)

    # Case 2: Panel flush behind shell
    # Wall/Shell at (-1.5, -3, 0) size 1.0 x 1.0
    wall = create_quad("CASE2_SHELL", (1.0, 1.0), (-1.5, -3.0, 0.0), (0, 0, 0))
    # Panel directly behind shell at (-1.5, -3.05, 0)
    back_panel = create_quad("CASE2_BACK_PANEL", (0.8, 0.8), (-1.5, -3.05, 0.0), (0, 0, 0))

    # Case 3: Panel half covered by another
    # Full panel at (1.5, -3.0, 0.0)
    full_panel = create_quad("CASE3_FULL_PANEL", (1.0, 1.0), (1.5, -3.0, 0.0), (0, 0, 0))
    # Half-occluded panel at (1.5, -3.0, -1.5)
    half_panel = create_quad("CASE3_HALF_PANEL", (1.0, 1.0), (1.5, -3.0, -1.5), (0, 0, 0))
    # Occluder covering top half of half_panel at (1.5, -2.95, -1.25)
    occluder = create_quad("CASE3_OCCLUDER", (1.0, 0.5), (1.5, -2.95, -1.25), (0, 0, 0))

    # Case 4: Recessed corner
    # Flat wall at (0, -4.0, 1.5) vs a recessed box with corner
    me4 = bpy.data.meshes.new("CASE4_NICHE_Mesh")
    bm4 = bmesh.new()
    # Build a 3-sided niche: back wall, side wall, bottom floor
    v_b1 = bm4.verts.new((-0.25, -4.5, 1.25))
    v_b2 = bm4.verts.new((0.25, -4.5, 1.25))
    v_b3 = bm4.verts.new((0.25, -4.5, 1.75))
    v_b4 = bm4.verts.new((-0.25, -4.5, 1.75))
    f_back = bm4.faces.new((v_b1, v_b2, v_b3, v_b4))

    v_s1 = bm4.verts.new((-0.25, -4.0, 1.25))
    v_s2 = bm4.verts.new((-0.25, -4.0, 1.75))
    f_side = bm4.faces.new((v_s1, v_b1, v_b4, v_s2))
    bm4.to_mesh(me4)
    bm4.free()
    obj4 = bpy.data.objects.new("CASE4_RECESSED_NICHE", me4)
    bpy.context.scene.collection.objects.link(obj4)

    # Reference flat wall of same size directly facing view
    flat_wall = create_quad("CASE4_FLAT_WALL", (0.5, 0.5), (0, -4.0, 2.2), (0, 0, 0))

    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    return blend_path


def validate_synthetic_cases(results):
    """Verify the 4 known cases pass assertions."""
    objs = results['object_suggestions']
    mesh_res = results['mesh_results']

    print("\n--- Validating Known Cases on Synthetic Scene ---")

    # Case 1: Front face vs back face of box
    box_mesh = mesh_res["CASE1_BOX_Mesh"]
    # Box has 6 faces: at least 1 front face visible, and back face never seen
    n_seen = np.count_nonzero(box_mesh['max_pixels'] > 0)
    n_never = np.count_nonzero(box_mesh['max_pixels'] == 0)
    print(f"Case 1 (Front vs Back): {n_seen} faces seen, {n_never} faces never seen.")
    assert n_seen >= 1, "Front face of box must be visible!"
    assert n_never >= 1, "Back face of box must be never seen!"

    # Case 2: Panel flush behind shell
    back_panel = objs["CASE2_BACK_PANEL"]
    print(f"Case 2 (Behind Shell): seen_share = {back_panel['seen_share']:.3f}, never_seen = {back_panel['n_never_seen']}")
    assert back_panel['seen_share'] == 0.0, "Panel behind shell must have 0% visibility!"
    assert back_panel['n_never_seen'] == back_panel['n_faces'], "All faces behind shell must be never-seen!"

    # Case 3: Panel half covered by another
    full_p = mesh_res["CASE3_FULL_PANEL_Mesh"]
    half_p = mesh_res["CASE3_HALF_PANEL_Mesh"]
    full_px = int(np.sum(full_p['max_pixels']))
    half_px = int(np.sum(half_p['max_pixels']))
    ratio = half_px / max(full_px, 1)
    print(f"Case 3 (Half-Covered): Full pixels={full_px}, Half pixels={half_px}, ratio={ratio:.2f}")
    assert 0.40 <= ratio <= 0.60, f"Half-covered panel should get ~50% pixels, got {ratio:.2f}!"

    # Case 4: Recessed corner vs flat wall
    flat_wall_d = objs["CASE4_FLAT_WALL"]['suggested_density']
    niche_m = mesh_res["CASE4_NICHE_Mesh"]
    niche_side_d = float(niche_m['relative_demand'][1])  # side face
    print(f"Case 4 (Recessed Niche): Flat wall demand={flat_wall_d:.3f}, Niche side demand={niche_side_d:.3f}")
    assert niche_side_d < flat_wall_d, f"Recessed corner ({niche_side_d:.3f}) must have lower demand than flat wall ({flat_wall_d:.3f})!"

    print("ALL 4 KNOWN CASES PASSED VALIDATION!\n")
    return True


# ---------------------------------------------------------------------------
# CLI & Execution
# ---------------------------------------------------------------------------

def print_cockpit_report(results):
    """Print comprehensive analysis report for cockpit model."""
    print("\n" + "=" * 70)
    print("      VISIBILITY-BASED TEXEL DEMAND REPORT (E2 COCKPIT)")
    print("=" * 70)
    print(f"File: {results['blend_file']}")
    print(f"Total Analysis Runtime: {results['total_time_s']:.2f} s ({results['total_time_s']/60:.2f} min)")
    print("Pass Timings:")
    for p_name, p_time in results['pass_timings'].items():
        print(f"  - {p_name}: {p_time:.2f} s")
    print(f"Cameras Evaluated: {', '.join(results['cameras'])}")
    print(f"Reference Demand (Forward View Raw): {results['ref_demand_raw']:.1f} px/m²")
    print(f"Total Scene Faces: {results['total_faces']:,}")
    print(f"Never-Seen Faces: {results['total_never_seen_faces']:,} ({results['never_seen_share']*100:.2f}%)")
    print(f"Total 3D Surface Area: {results.get('total_surface_area_m2', 0.0):.2f} m²")
    print(f"Never-Seen 3D Area (Delete Candidates): {results.get('total_never_seen_area_m2', 0.0):.2f} m² ({results.get('never_seen_area_share', 0.0)*100:.2f}%)")
    print(f"Texture Area Savings vs Uniform (Clamped [0.5, 1.1]): {results['texture_area_savings_pct']:.2f}%\n")

    print("--- Demand Percentiles (Visible Faces, 1.0 = Neutral) ---")
    for p, val in results['demand_percentiles'].items():
        print(f"  {p:>4}: {val:.3f}")

    objs = results['object_suggestions']
    # Sort objects by suggested density
    sorted_by_density = sorted(objs.items(), key=lambda item: item[1]['suggested_density'])

    print("\n--- Bottom 20 Objects by Suggested Density (Candidates for Reduction/Deletion) ---")
    print(f"{'Object Name':<38} {'Density':<10} {'Seen %':<10} {'NeverSeen':<10} {'Faces':<8}")
    print("-" * 78)
    for name, data in sorted_by_density[:20]:
        print(f"{name:<38} {data['suggested_density']:<10.3f} {data['seen_share']*100:<10.1f} {data['n_never_seen']:<10} {data['n_faces']:<8}")

    print("\n--- Top 20 Objects by Suggested Density (Highest Detail / Close-up) ---")
    print(f"{'Object Name':<38} {'Density':<10} {'Seen %':<10} {'NeverSeen':<10} {'Faces':<8}")
    print("-" * 78)
    for name, data in sorted_by_density[-20:][::-1]:
        print(f"{name:<38} {data['suggested_density']:<10.3f} {data['seen_share']*100:<10.1f} {data['n_never_seen']:<10} {data['n_faces']:<8}")

    # Objects with 100% never seen
    fully_unseen = [name for name, data in objs.items() if data['seen_share'] == 0.0]
    print(f"\nTotal Objects with 100% Never-Seen Faces: {len(fully_unseen)}")
    if fully_unseen:
        print("Sample Delete Candidate Objects (first 10):")
        for name in fully_unseen[:10]:
            print(f"  - {name} ({objs[name]['n_faces']} faces, area={objs[name]['area']:.4f} m²)")
    print("=" * 70 + "\n")
    sys.stdout.flush()


def main():
    import argparse
    # Parse args after '--'
    argv = sys.argv
    if "--" in argv:
        args_to_parse = argv[argv.index("--") + 1:]
    else:
        args_to_parse = []

    parser = argparse.ArgumentParser(description="Texel Demand Prototype")
    parser.add_argument("--synthetic", action="store_true", help="Run synthetic validation")
    parser.add_argument("--cockpit", action="store_true", help="Run full cockpit analysis")
    parser.add_argument("--cube-res", type=int, default=1024, help="Resolution per cube face")
    parser.add_argument("--out-dir", type=str, default="tests/_work/uv_visibility", help="Output directory")
    args = parser.parse_args(args_to_parse)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.synthetic:
        syn_blend = out_dir / "synthetic_test.blend"
        print(f"Creating synthetic test scene at {syn_blend}...")
        build_synthetic_scene(syn_blend)

        cameras = [
            {'name': 'CAM_PILOT_CLOSE', 'type': 'LOOK_AROUND', 'pos': Vector((0, 0, 0))},
        ]
        results = analyze_visibility(syn_blend, cameras=cameras, anim_passes=(0,), cube_res=512)
        save_visibility_file(syn_blend, results)
        validate_synthetic_cases(results)
        return

    if args.cockpit:
        blend_copy = out_dir / "COCKPIT_copy.blend"
        if not blend_copy.exists():
            raise FileNotFoundError(f"Cockpit copy not found at {blend_copy}")

        print(f"\nStarting Visibility-Based Texel Demand on {blend_copy}...")
        # Configure Pilot Look-Around + Copilot Fixed View
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
            })
        if copilot_cam:
            cameras.append({
                'name': copilot_cam.name,
                'type': 'FIXED_VIEW',
                'obj_name': copilot_cam.name,
            })

        # Run analysis across 3 animation passes
        results = analyze_visibility(
            blend_copy,
            cameras=cameras,
            anim_passes=(0, 50, 100),
            cube_res=args.cube_res,
            frustum_res=(2560, 1440),
        )

        # Save .visibility file
        vis_file = save_visibility_file(blend_copy, results)
        print(f"Saved visibility results to: {vis_file}")
        sys.stdout.flush()

        # Print detailed report
        print_cockpit_report(results)
        sys.stdout.flush()

        # Render offscreen heatmap images
        print("Rendering offscreen heatmap images...")
        sys.stdout.flush()
        dg = bpy.context.evaluated_depsgraph_get()

        # 1. Pilot view
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
            sys.stdout.flush()

        # 2. Outside view (isometric/perspective overview looking into cockpit)
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
        sys.stdout.flush()

        # Test glTF export integrity
        test_gltf_export(blend_copy, out_dir)
        sys.stdout.flush()


if __name__ == "__main__":
    main()
