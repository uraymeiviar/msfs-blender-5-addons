"""FSS Blender Tools: visibility analysis core engine.

Scores every face by the light the artist's probe lights cast on it, as EEVEE shows a white diffuse surface in the
viewport with View Transform Standard (UV journal decisions 124 to 130): per light, the share of the face each
soft-shadow sample point reaches (visible over unoccluded solid angle from that point, with patches for faces too small
to measure, decisions 72 to 82), times the light EEVEE gives it without shadows; summed over the lights, displayed with
the sRGB transfer, the highest over the animation states. An island takes a percentile of its faces by area (decision
127), touching islands meet in the middle when they differ by more than the step limit (decision 128), and the most
visible island is 1.0. Independent of UI.
"""

import heapq
import json
import math
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
# 7: scored by probe lights (decision 124), not cameras. 6: Look Around images weighted the right way up, and no
# direction weight (decision 73 removed). 5 added face_facing.
VISIBILITY_SCHEMA = 8
PIECE_SECONDS = 0.2  # a long loop hands back to Blender about this often, so a modal run can draw and read Esc
# The bar's share of each stage, in units of one view besides reading the scene; from a run on the E2 cockpit
UNITS_PREPARE, UNITS_READ, UNITS_VIEW, UNITS_FINAL = 12.0, 6.0, 1.0, 8.0


def _no_report(_fraction):
    pass


def _drain(pieces):
    """Run a generator of pieces to its end and return its value: the same work all at once."""
    try:
        while True:
            next(pieces)
    except StopIteration as done:
        return done.value


class _Pause:
    """When a long loop should hand back."""

    def __init__(self):
        self.last = time.perf_counter()

    def due(self):
        now = time.perf_counter()
        if now - self.last < PIECE_SECONDS:
            return False
        self.last = now
        return True


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


def scene_bounds(view_layer):
    """The world bounding box (min, max) of the visible meshes' bounding boxes, or None without any."""
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
    return (min_v, max_v) if found else None


def compute_scene_extent(view_layer, eye, bounds=None):
    """Near and far clipping planes from the scene's extent seen from eye (Decision 81, Requirement 4); bounds as
    scene_bounds gives them, read from view_layer when not given."""
    bounds = scene_bounds(view_layer) if bounds is None else bounds
    if bounds is False or bounds is None:
        return 0.01, 30.0
    min_v, max_v = bounds
    diag = float(np.linalg.norm(max_v - min_v))
    eye_arr = np.array(eye, dtype=np.float32)
    corners = np.array([[x, y, z] for x in (min_v[0], max_v[0]) for y in (min_v[1], max_v[1])
                        for z in (min_v[2], max_v[2])], dtype=np.float32)
    max_dist = float(np.max(np.linalg.norm(corners - eye_arr, axis=1)))
    return 0.01, max(30.0, max_dist * 1.5, diag * 1.5)


CUBE_FACE_DIRECTIONS = {'FORWARD': (0, -1, 0), 'BACKWARD': (0, 1, 0), 'LEFT': (-1, 0, 0), 'RIGHT': (1, 0, 0),
                        'UP': (0, 0, 1), 'DOWN': (0, 0, -1)}
CUBE_CORNER_ANGLE = math.acos(1.0 / math.sqrt(3.0))  # from a cube face's centre direction to its corner


def cubemap_face_matrices(eye, near=0.01, far=30.0):
    """Return 6 (name, view_matrix, proj_matrix) for a cube map around eye."""
    proj = perspective_proj(math.radians(90.0), 1.0, near, far)
    p = Vector(eye)
    ups = {'UP': Vector((0, -1, 0)), 'DOWN': Vector((0, 1, 0))}
    return [(name, look_at(p, p + Vector(direction), ups.get(name, Vector((0, 0, 1)))), proj)
            for name, direction in CUBE_FACE_DIRECTIONS.items()]


def precompute_cubemap_weights(cube_res=1024):
    """Per-pixel solid angle of a cube map face (decision 72), the same for all 6 faces. Row 0 is the image's bottom,
    as read_color returns it."""
    W = cube_res
    u = (np.arange(W, dtype=np.float32) + 0.5) * (2.0 / W) - 1.0
    U, V = np.meshgrid(u, u)
    return ((4.0 / (W * W)) / np.power(U * U + V * V + 1.0, 1.5)).astype(np.float32)


def batch_triangle_solid_angle(eye, V0, V1, V2):
    """Vectorized calculation of spherical solid angle for a batch of triangles (n, 3) (Oosterom & Strackee 1983). A
    triangle turned away from eye gives 0."""
    return planar_solid_angle(eye, *(np.ascontiguousarray(np.asarray(V, dtype=np.float32).T) for V in (V0, V1, V2)))


def planar_solid_angle(eye, P0, P1, P2):
    """batch_triangle_solid_angle on the corners as rows of x, y and z (3, n), with the same float32 operations in the
    same order, so the result is the same to the bit: the corners A, B, C seen from eye are made unit length, and
    tan(omega / 2) = |a . (b x c)| / (1 + a . b + b . c + c . a). The facing is the normal from the edges, (B - A) x
    (C - A), against -A."""
    ex, ey, ez = (np.float32(v) for v in eye)
    ax, ay, az = P0[0] - ex, P0[1] - ey, P0[2] - ez
    bx, by, bz = P1[0] - ex, P1[1] - ey, P1[2] - ez
    cx, cy, cz = P2[0] - ex, P2[1] - ey, P2[2] - ez

    def cross(ux, uy, uz, vx, vy, vz):
        return uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx

    nx, ny, nz = cross(bx - ax, by - ay, bz - az, cx - ax, cy - ay, cz - az)
    front = (nx * -ax + ny * -ay) + nz * -az > 0.0
    eps = 1e-12
    la = np.sqrt((ax * ax + ay * ay) + az * az)
    lb = np.sqrt((bx * bx + by * by) + bz * bz)
    lc = np.sqrt((cx * cx + cy * cy) + cz * cz)
    valid = (la > eps) & (lb > eps) & (lc > eps) & front
    da, db, dc = np.maximum(la, eps), np.maximum(lb, eps), np.maximum(lc, eps)
    ax, ay, az = ax / da, ay / da, az / da
    bx, by, bz = bx / db, by / db, bz / db
    cx, cy, cz = cx / dc, cy / dc, cz / dc
    kx, ky, kz = cross(bx, by, bz, cx, cy, cz)
    num = np.abs((ax * kx + ay * ky) + az * kz)
    den = ((1.0 + ((ax * bx + ay * by) + az * bz)) + ((bx * cx + by * cy) + bz * cz)) + ((cx * ax + cy * ay) + cz * az)
    omega = 2.0 * np.arctan2(num, den)
    omega = np.where(omega < 0.0, omega + 2.0 * np.pi, omega)
    return np.where(valid, omega, 0.0).astype(np.float32)


# ---------------------------------------------------------------------------
# Probe Lights: the light EEVEE gives a white diffuse surface (decision 126)
# ---------------------------------------------------------------------------

# Measured with EEVEE test renders (UV journal Session 109): a white Diffuse BSDF shows P / (4 pi^2 d^2) x cos from a
# point or spot light of P watts and P / (pi^2 d^2) x cos x the cosine at the emitter from an area light, each faded to
# nothing at the light's reach by (1 - (d / r)^4)^2, r = sqrt(P / (100 x Light Threshold)) or the Custom Distance. A
# spot light has a point light's brightness inside its cone, and Blender's smoothstep over Spot Blend at its edge.
POINT_FACTOR = 1.0 / (4.0 * math.pi ** 2)
AREA_FACTOR = 1.0 / (math.pi ** 2)
PROBE_LIGHT_TYPES = ('POINT', 'SPOT', 'AREA')
MIN_LIGHT_DISTANCE = 0.01  # metres: a face touching a light does not take an endless value


def srgb_encode(linear):
    """The sRGB transfer of the Standard view transform, continued above 1 instead of clipped at white."""
    x = np.maximum(np.asarray(linear, dtype=np.float64), 0.0)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1.0 / 2.4) - 0.055)


def light_reach(light_data, power, scene):
    """Where EEVEE fades the light to nothing: its Custom Distance, else where it falls below the Light Threshold."""
    if getattr(light_data, 'use_custom_distance', False):
        return float(light_data.cutoff_distance)
    threshold = float(getattr(getattr(scene, 'eevee', None), 'light_threshold', 0.01))
    return math.sqrt(power / (100.0 * threshold)) if threshold > 0.0 else float('inf')


def light_record(obj, scene, depsgraph=None):
    """What the score needs of a probe light at the current frame, or None for one that lights nothing here (a sun,
    no power, not a light)."""
    if obj is None or obj.type != 'LIGHT':
        return None
    ev = obj.evaluated_get(depsgraph) if depsgraph is not None else obj
    data = ev.data
    if data.type not in PROBE_LIGHT_TYPES:
        return None
    power = float(data.energy) * max(float(c) for c in data.color)
    if power <= 0.0:
        return None
    axes = np.array(ev.matrix_world.to_3x3(), dtype=np.float64)
    scale = np.linalg.norm(axes, axis=0)
    unit = axes / np.maximum(scale, 1e-12)
    record = {
        'name': obj.name,
        'type': data.type,
        'pos': np.array(ev.matrix_world.translation, dtype=np.float64),
        'unit': unit,  # columns: the light's own x, y and z, unit length
        'power': power,
        'factor': AREA_FACTOR if data.type == 'AREA' else POINT_FACTOR,
        'reach': light_reach(data, power, scene),
        'radius': float(getattr(data, 'shadow_soft_size', 0.0)),
    }
    if data.type == 'AREA':
        record['radius'] = 0.5 * max(float(data.size), float(getattr(data, 'size_y', data.size)))
    if data.type == 'SPOT':
        z = max(float(scale[2]), 1e-12)
        record['cos_half'] = math.cos(float(data.spot_size) * 0.5)
        record['blend'] = float(data.spot_blend)
        record['ellipse'] = (float(scale[0]) / z, float(scale[1]) / z)
    return record


def light_cone(record, dirs):
    """Per unit direction from the light (n, 3): 1 for a point light, the cosine at the emitter for an area light (it
    lights its front side, along -Z), Blender's smoothstep at a spot light's edge, 0 outside the cone."""
    if record['type'] == 'POINT':
        return np.ones(len(dirs))
    local = dirs @ record['unit']
    if record['type'] == 'AREA':
        return np.maximum(-local[:, 2], 0.0)
    ex, ey = record['ellipse']
    x, y, z = local[:, 0] / max(ex, 1e-12), local[:, 1] / max(ey, 1e-12), -local[:, 2]
    cos_off = np.where(z > 0.0, z / np.maximum(np.sqrt(x * x + y * y + z * z), 1e-12), -1.0)
    smooth = (1.0 - record['cos_half']) * record['blend']
    if smooth <= 1e-8:
        return (cos_off > record['cos_half']).astype(np.float64)
    t = np.clip((cos_off - record['cos_half']) / smooth, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def light_direction(record):
    """The direction a spot or area light points (its -Z)."""
    return -record['unit'][:, 2]


def batch_light_term(record, V0, V1, V2, tri_ids, n_ids):
    """Per evaluated face, the light a white diffuse face gets from the light without shadows, summed over its
    triangles by area, and their area: (sum of area x light, area), so faces split by modifiers can be added up."""
    V0, V1, V2 = (np.asarray(V, dtype=np.float64) for V in (V0, V1, V2))
    N = np.cross(V1 - V0, V2 - V0)
    twice_area = np.linalg.norm(N, axis=-1)
    to_face = (V0 + V1 + V2) / 3.0 - record['pos']
    dist = np.linalg.norm(to_face, axis=-1)
    dirs = to_face / np.maximum(dist, 1e-12)[:, None]
    cos_face = np.maximum(-np.sum(N * dirs, axis=-1) / np.maximum(twice_area, 1e-30), 0.0)
    d = np.maximum(dist, MIN_LIGHT_DISTANCE)
    window = np.ones_like(d)
    if math.isfinite(record['reach']):
        f = (d * d) / max(record['reach'] ** 2, 1e-12)
        window = np.square(np.clip(1.0 - f * f, 0.0, 1.0))
    light = record['factor'] * record['power'] / (d * d) * cos_face * window * light_cone(record, dirs)
    area = 0.5 * twice_area
    return (np.bincount(tri_ids, weights=area * light, minlength=n_ids),
            np.bincount(tri_ids, weights=area, minlength=n_ids))


def light_sample_offsets(n):
    """n directions spread evenly over the unit sphere (a Fibonacci sphere): where the soft-shadow samples sit on the
    light's radius. One sample is the light's centre."""
    if n <= 1:
        return np.zeros((1, 3))
    i = np.arange(n) + 0.5
    z = 1.0 - 2.0 * i / n
    r = np.sqrt(np.maximum(1.0 - z * z, 0.0))
    phi = math.pi * (3.0 - math.sqrt(5.0)) * i
    return np.stack([r * np.cos(phi), r * np.sin(phi), z], axis=1)


def cube_faces_in_cone(record):
    """The cube map faces a light can reach: all for a point light or a spot scaled out of round, otherwise those whose
    directions can meet the spot cone or an area light's front side."""
    if record['type'] == 'POINT':
        return set(CUBE_FACE_DIRECTIONS)
    if record['type'] == 'SPOT':
        if max(record['ellipse']) > 1.0 + 1e-6:
            return set(CUBE_FACE_DIRECTIONS)
        half = math.acos(max(min(record['cos_half'], 1.0), -1.0))
    else:
        half = math.pi / 2.0
    axis = light_direction(record)
    found = set()
    for name, direction in CUBE_FACE_DIRECTIONS.items():
        angle = math.acos(max(min(float(np.dot(axis, direction)), 1.0), -1.0))
        if angle <= half + CUBE_CORNER_ANGLE + 1e-6:
            found.add(name)
    return found


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

MAT_OPAQUE, MAT_DECAL_GLASS, MAT_INVISIBLE = 0, 1, 2
_MAT_CODES = {'OPAQUE': MAT_OPAQUE, 'DECAL_GLASS': MAT_DECAL_GLASS, 'INVISIBLE': MAT_INVISIBLE}


def polygon_material_classes(me, mat_slots):
    """Per polygon, its material class as a code (MAT_OPAQUE, MAT_DECAL_GLASS, MAT_INVISIBLE), classified once per
    material slot. A polygon whose index has no slot is opaque."""
    n_polys = len(me.polygons)
    if n_polys == 0 or not mat_slots:
        return np.zeros(n_polys, dtype=np.int8)
    slot_codes = np.array([_MAT_CODES[classify_material(slot.material)] for slot in mat_slots] + [MAT_OPAQUE],
                          dtype=np.int8)
    mat_index = np.empty(n_polys, dtype=np.int32)
    me.polygons.foreach_get('material_index', mat_index)
    mat_index = np.where((mat_index >= 0) & (mat_index < len(mat_slots)), mat_index, len(mat_slots))
    return slot_codes[mat_index]


def _polygon_loops(me):
    """Per polygon, its first loop and loop count; per loop, its vertex; and per corner (each polygon's corners in
    order), its polygon, its loop and the loop of the next corner around the polygon."""
    n_polys, n_loops = len(me.polygons), len(me.loops)
    loop_start = np.empty(n_polys, dtype=np.int64)
    loop_total = np.empty(n_polys, dtype=np.int64)
    me.polygons.foreach_get('loop_start', loop_start)
    me.polygons.foreach_get('loop_total', loop_total)
    loop_vert = np.empty(n_loops, dtype=np.int64)
    me.loops.foreach_get('vertex_index', loop_vert)
    loop_poly = np.repeat(np.arange(n_polys, dtype=np.int64), loop_total)
    position = np.arange(n_loops, dtype=np.int64) - np.repeat(np.cumsum(loop_total) - loop_total, loop_total)
    loop_index = np.repeat(loop_start, loop_total) + position
    next_loop = np.repeat(loop_start, loop_total) + (position + 1) % np.repeat(loop_total, loop_total)
    return loop_start, loop_total, loop_vert, loop_poly, loop_index, next_loop


def polygon_areas(me, matrix_world):
    """Per polygon, its world-space area: the sum of a fan of triangles from its first corner."""
    n_polys = len(me.polygons)
    if n_polys == 0:
        return np.zeros(0, dtype=np.float32)
    V = np.empty((len(me.vertices), 3), dtype=np.float32)
    me.vertices.foreach_get('co', V.ravel())
    M = np.array(matrix_world, dtype=np.float32)
    V = V @ M[:3, :3].T + M[:3, 3]
    loop_start, loop_total, loop_vert, _poly, _index, _next = _polygon_loops(me)
    n_fan = np.maximum(loop_total - 2, 0)
    tri_poly = np.repeat(np.arange(n_polys), n_fan)
    j = np.arange(len(tri_poly)) - np.repeat(np.cumsum(n_fan) - n_fan, n_fan) + 1
    first = loop_start[tri_poly]
    p0, p1, p2 = V[loop_vert[first]], V[loop_vert[first + j]], V[loop_vert[first + j + 1]]
    tri_area = 0.5 * np.linalg.norm(np.cross(p1 - p0, p2 - p0), axis=1)
    return np.bincount(tri_poly, weights=tri_area, minlength=n_polys).astype(np.float32)


def connected_labels(n, a, b):
    """Connected components of n nodes joined by the pairs (a[i], b[i]): per node, the smallest node of its
    component (hooking each root under the smaller one, then jumping pointers until every pair agrees)."""
    label = np.arange(n, dtype=np.int64)
    a = np.asarray(a, dtype=np.int64)
    b = np.asarray(b, dtype=np.int64)
    while len(a):
        la, lb = label[a], label[b]
        differ = la != lb
        if not np.any(differ):
            break
        a, b, la, lb = a[differ], b[differ], la[differ], lb[differ]
        np.minimum.at(label, np.maximum(la, lb), np.minimum(la, lb))
        while True:
            jumped = label[label]
            if np.array_equal(jumped, label):
                break
            label = jumped
    return label


def _shared_key_pairs(keys, owners, n_owners):
    """The pairs of different owners that share a key (each key's owners pairwise), both ways round, unique and
    sorted."""
    order = np.argsort(keys, kind='stable')
    k, o = keys[order], owners[order]
    found = []
    d = 1
    while d < len(k):
        same = k[d:] == k[:-d]
        if not np.any(same):
            break
        a, b = o[:-d][same], o[d:][same]
        keep = a != b
        found += [a[keep] * n_owners + b[keep], b[keep] * n_owners + a[keep]]
        d += 1
    if not found:
        return np.zeros((0, 2), dtype=np.int64)
    codes = np.unique(np.concatenate(found))
    return np.stack([codes // n_owners, codes % n_owners], axis=1)


def extract_mesh_uv_islands(me, uv_name=None):
    """Extract UV island ID for each polygon of base mesh: polygons sharing an edge with the same UVs at both ends
    are one island. Islands are numbered by their first polygon."""
    n_polys = len(me.polygons)
    if n_polys == 0:
        return np.zeros(0, dtype=np.int32)

    if uv_name:
        uv_layer = me.uv_layers.get(uv_name)
    else:
        uv_layer = me.uv_layers.active

    if not uv_layer or len(me.loops) == 0:
        return np.zeros(n_polys, dtype=np.int32)

    _start, _total, loop_vert, loop_poly, loop_index, next_loop = _polygon_loops(me)
    loop_uvs = np.empty((len(me.loops), 2), dtype=np.float32)
    uv_layer.data.foreach_get('uv', loop_uvs.ravel())
    loop_uvs_quant = np.round(loop_uvs, decimals=4)

    _keys, corner_ids = np.unique(
        np.column_stack((loop_vert, loop_uvs_quant)),
        axis=0,
        return_inverse=True
    )
    corner_ids = corner_ids.reshape(-1).astype(np.int64)
    c1, c2 = corner_ids[loop_index], corner_ids[next_loop]
    edge_keys = np.minimum(c1, c2) * (int(corner_ids.max()) + 1) + np.maximum(c1, c2)
    pairs = _shared_key_pairs(edge_keys, loop_poly, n_polys)
    roots = connected_labels(n_polys, pairs[:, 0], pairs[:, 1])
    _, island_ids = np.unique(roots, return_inverse=True)
    return island_ids.reshape(-1).astype(np.int32)


def extract_mesh_face_adjacency(me, mat_slots=None):
    """Compute face adjacency and connected components from original mesh edges.

    Excludes faces of invisible material classes.
    Returns:
    - adj: (indptr, indices), the neighbours of face i are indices[indptr[i]:indptr[i + 1]], ascending
    - face_to_comp: np.ndarray (n_polys,) int32 component IDs (-1 for invisible), numbered by their first face
    - components: list of np.ndarray of face indices for each connected piece, ascending
    """
    n_polys = len(me.polygons)
    if n_polys == 0:
        return (np.zeros(1, dtype=np.int64), np.zeros(0, dtype=np.int64)), np.zeros(0, dtype=np.int32), []

    is_invis = polygon_material_classes(me, mat_slots) == MAT_INVISIBLE
    _start, _total, loop_vert, loop_poly, loop_index, next_loop = _polygon_loops(me)
    visible = ~is_invis[loop_poly]
    v0, v1 = loop_vert[loop_index][visible], loop_vert[next_loop][visible]
    edge_keys = np.minimum(v0, v1) * (len(me.vertices) + 1) + np.maximum(v0, v1)
    pairs = _shared_key_pairs(edge_keys, loop_poly[visible], n_polys)
    indptr = np.zeros(n_polys + 1, dtype=np.int64)
    np.cumsum(np.bincount(pairs[:, 0], minlength=n_polys), out=indptr[1:])
    adj = (indptr, pairs[:, 1].copy())

    labels = connected_labels(n_polys, pairs[:, 0], pairs[:, 1])
    face_to_comp = np.full(n_polys, -1, dtype=np.int32)
    vis_faces = np.flatnonzero(~is_invis)
    roots, comp_of = np.unique(labels[vis_faces], return_inverse=True)
    face_to_comp[vis_faces] = comp_of.reshape(-1)
    order = np.argsort(face_to_comp[vis_faces], kind='stable')
    bounds = np.searchsorted(face_to_comp[vis_faces][order], np.arange(len(roots) + 1))
    components = [vis_faces[order[bounds[c]:bounds[c + 1]]].astype(np.int32) for c in range(len(roots))]
    return adj, face_to_comp, components


def adjacency_csr(adjacency):
    """Face adjacency as (indptr, indices), from either that or a list of neighbour lists."""
    if isinstance(adjacency, tuple):
        return adjacency
    counts = np.array([len(n) for n in adjacency], dtype=np.int64)
    indptr = np.zeros(len(adjacency) + 1, dtype=np.int64)
    np.cumsum(counts, out=indptr[1:])
    indices = np.array([g for n in adjacency for g in n], dtype=np.int64)
    return indptr, indices


# ---------------------------------------------------------------------------
# Instance Discovery & Evaluated Scene Extraction
# ---------------------------------------------------------------------------

def discover_mesh_instances(view_layer):
    return _drain(_discover_pieces(view_layer))


def _discover_pieces(view_layer, report=_no_report):
    """Scan scene for visible mesh objects and assign instances per mesh."""
    mesh_meta = {}

    mesh_objs = [
        o for o in view_layer.objects
        if o is not None and o.type == 'MESH' and o.data and not o.hide_viewport and not o.hide_render
    ]

    pause = _Pause()
    for index, o in enumerate(mesh_objs):
        if pause.due():
            report(index / len(mesh_objs))
            yield
        if is_invisible_object(o):
            continue

        me_orig = o.data
        mesh_name = me_orig.name
        n_orig_faces = len(me_orig.polygons)
        if n_orig_faces == 0:
            continue

        if mesh_name not in mesh_meta:
            orig_areas = polygon_areas(me_orig, o.matrix_world)
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
    return _drain(_extract_pieces(depsgraph, view_layer, mesh_meta))


def _mirror_copies(o, eval_me, me_orig, orig_indices):
    """Per evaluated polygon of an object with Mirror modifiers, which mirror copy it is: 1, 2 and 4 for flipped in
    x, y and z, summed; a polygon on the mirror plane counts as flipped where it lies on the negative side."""
    mirror_mods = [m for m in o.modifiers if m.type == 'MIRROR']
    copy_idx = np.zeros(len(orig_indices), dtype=np.int64)
    if not mirror_mods or len(orig_indices) == 0:
        return copy_idx
    eval_c = np.empty((len(eval_me.polygons), 3), dtype=np.float32)
    eval_me.polygons.foreach_get('center', eval_c.ravel())
    orig_c = np.empty((len(me_orig.polygons), 3), dtype=np.float32)
    me_orig.polygons.foreach_get('center', orig_c.ravel())
    eval_c = eval_c.astype(np.float64)
    orig_c = orig_c.astype(np.float64)[orig_indices]
    for axis, bit in enumerate((1, 2, 4)):
        if any(m.use_axis[axis] for m in mirror_mods):
            e, g = eval_c[:, axis], orig_c[:, axis]
            flip = (e * g < -1e-6) | ((np.abs(g) < 1e-4) & (e < -1e-4))
            copy_idx += bit * flip
    return copy_idx


def _extract_pieces(depsgraph, view_layer, mesh_meta, report=_no_report):
    """Extract evaluated scene geometry split into Opaque and Decal batches. Its value: the batches; per mesh, the
    evaluated face ids with the instance and original face each lands on (ascending ids); the analytical triangles;
    the next free id; and per object its evaluated-to-original face map and evaluated face count."""
    opaque_pos = []
    opaque_ids = []
    decal_pos = []
    decal_ids = []

    all_tri = []
    all_tri_ids = []

    eval_index = {}
    object_eval_face_maps = {}
    object_eval_face_counts = {}
    global_id = 1

    mesh_objs = [
        o for o in view_layer.objects
        if o is not None and o.type == 'MESH' and o.data and not o.hide_viewport and not o.hide_render
    ]

    pause = _Pause()
    for index, o in enumerate(mesh_objs):
        if pause.due():
            report(index / len(mesh_objs))
            yield
        if is_invisible_object(o):
            continue

        me_orig = o.data
        mesh_name = me_orig.name
        if mesh_name not in mesh_meta:
            continue

        meta = mesh_meta[mesh_name]

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
        poly_mat_class = polygon_material_classes(eval_me, o.material_slots)

        # Read original face index attribute transferred through modifiers
        eval_attr = eval_me.attributes.get(ORIG_FACE_ATTR_NAME)
        if eval_attr:
            orig_indices = np.empty(n_eval_polys, dtype=np.int32)
            eval_attr.data.foreach_get('value', orig_indices)
        else:
            raise RuntimeError(f"Attribute {ORIG_FACE_ATTR_NAME} missing on evaluated mesh {mesh_name}")

        copy_idx = _mirror_copies(o, eval_me, me_orig, orig_indices)
        inst_of_copy = np.array([meta['instance_map'].get((o.name, c), 0) for c in range(8)], dtype=np.int64)
        eval_index.setdefault(mesh_name, []).append((
            base_id + np.arange(n_eval_polys, dtype=np.int64), inst_of_copy[copy_idx], orig_indices.astype(np.int64)))

        # Split loop triangles into batches; invisible ones are left out of all batches and analytical triangles
        tri_ids = (base_id + poly_indices).astype(np.int32)
        tri_class = poly_mat_class[poly_indices]
        shown = tri_class != MAT_INVISIBLE
        all_tri.append(P_world[shown])
        all_tri_ids.append(tri_ids[shown])
        for cls, pos, ids in ((MAT_DECAL_GLASS, decal_pos, decal_ids), (MAT_OPAQUE, opaque_pos, opaque_ids)):
            mask = tri_class == cls
            if np.any(mask):
                pos.append(P_world[mask].reshape(-1, 3))
                ids.append(np.repeat(tri_ids[mask], 3))

        global_id += n_eval_polys
        object_eval_face_maps[o.name] = orig_indices.copy().astype(np.int32)
        object_eval_face_counts[o.name] = int(n_eval_polys)
        eval_obj.to_mesh_clear()

    batches = {
        'opaque_pos': np.concatenate(opaque_pos, axis=0) if opaque_pos else np.zeros((0, 3), dtype=np.float32),
        'opaque_ids': np.concatenate(opaque_ids, axis=0) if opaque_ids else np.zeros(0, dtype=np.int32),
        'decal_pos': np.concatenate(decal_pos, axis=0) if decal_pos else np.zeros((0, 3), dtype=np.float32),
        'decal_ids': np.concatenate(decal_ids, axis=0) if decal_ids else np.zeros(0, dtype=np.int32),
    }

    tri = np.concatenate(all_tri, axis=0) if all_tri else np.zeros((0, 3, 3), dtype=np.float32)
    tri_geometry = {
        'V0': np.ascontiguousarray(tri[:, 0]),
        'V1': np.ascontiguousarray(tri[:, 1]),
        'V2': np.ascontiguousarray(tri[:, 2]),
        'tri_ids': np.concatenate(all_tri_ids, axis=0) if all_tri_ids else np.zeros(0, dtype=np.int32),
    }
    eval_index = {m: tuple(np.concatenate(part) for part in zip(*entries)) for m, entries in eval_index.items()}

    return batches, eval_index, tri_geometry, global_id, object_eval_face_maps, object_eval_face_counts


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
        """The scene has one frame for all animations, so the step is a share of the widest range that moves.

        A range without length (one keyframe) holds its pose at every frame, so it neither widens the range nor
        decides it; the result does not depend on the order of the objects."""
        pct_norm = pct if pct <= 1.0 else pct / 100.0
        moving = [s for s in self.original_states if s['frame_end'] > s['frame_start']]
        if moving:
            f_min = min(s['frame_start'] for s in moving)
            f_max = max(s['frame_end'] for s in moving)
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


def _pixel_ids(fb, width, height):
    """The face id of every pixel the ID shader drew: red, green and blue are its low, middle and high byte."""
    px = np.asarray(fb.read_color(0, 0, width, height, 4, 0, 'UBYTE'), dtype=np.uint8)
    return (np.ascontiguousarray(px).reshape(-1).view('<u4') & np.uint32(0xFFFFFF)).astype(np.intp)


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
            ids = _pixel_ids(fb, W, H)
            counts_opaque = np.bincount(ids, weights=weight_flat, minlength=max_id + 1)

        # Pass 2: Decal / Glass
        if batch_decal is not None and batch_decal.has_triangles():
            fb.clear(color=(0, 0, 0, 1))
            gpu.state.depth_mask_set(False)
            batch_decal.draw(shader)
            ids = _pixel_ids(fb, W, H)
            counts_decal = np.bincount(ids, weights=weight_flat, minlength=max_id + 1)

        gpu.state.depth_test_set('NONE')

    return counts_opaque + counts_decal


# ---------------------------------------------------------------------------
# Per-Face Patches, Hierarchy Fallback & Island Scoring (Decisions 79 & 82)
# ---------------------------------------------------------------------------

PATCH_CHUNK = 20000  # small faces whose patches grow together; bounds the memory and the time between yields


def _ring_neighbours(indptr, indices, faces):
    """Per face, its neighbours, flattened: (which face of faces, neighbour)."""
    begin = indptr[faces]
    lengths = indptr[faces + 1] - begin
    total = int(np.sum(lengths))
    if total == 0:
        return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64)
    owner = np.repeat(np.arange(len(faces)), lengths)
    offsets = np.repeat(begin - (np.cumsum(lengths) - lengths), lengths)
    return owner, indices[offsets + np.arange(total)]


def _grow_patches(seeds, indptr, indices, unocc_t, vis_t, omega_threshold):
    """For faces too small to measure (seeds), grow each one's patch ring by ring through its neighbours until its
    largest unoccluded solid angle over the views reaches omega_threshold, or nothing is left to add (decision 79).
    All seeds grow together. Returns per seed the patch's unoccluded and visible solid angle per view (S, rows)."""
    n_faces = unocc_t.shape[0]
    n_seeds = len(seeds)
    seed_ids = np.arange(n_seeds, dtype=np.int64)
    patch_unocc = unocc_t[seeds].copy()
    member_codes = seed_ids * n_faces + seeds
    members = [member_codes]
    ring_seed, ring_face = seed_ids, seeds
    while len(ring_seed):
        owner, neighbour = _ring_neighbours(indptr, indices, ring_face)
        codes = np.unique(ring_seed[owner] * n_faces + neighbour)
        codes = codes[~np.isin(codes, member_codes, assume_unique=True)]
        if len(codes) == 0:
            break
        member_codes = np.concatenate([member_codes, codes])
        members.append(codes)
        grow_seed, grow_face = codes // n_faces, codes % n_faces
        starts = np.flatnonzero(np.r_[True, grow_seed[1:] != grow_seed[:-1]])
        grown = grow_seed[starts]
        patch_unocc[grown] += np.add.reduceat(unocc_t[grow_face], starts, axis=0)
        still = grown[patch_unocc[grown].max(axis=1) < omega_threshold]
        keep = np.isin(grow_seed, still, assume_unique=False)
        ring_seed, ring_face = grow_seed[keep], grow_face[keep]
    codes = np.sort(np.concatenate(members))
    member_seed, member_face = codes // n_faces, codes % n_faces
    starts = np.flatnonzero(np.r_[True, member_seed[1:] != member_seed[:-1]])
    patch_vis = np.add.reduceat(vis_t[member_face], starts, axis=0)
    return patch_unocc, patch_vis


def _lit_shares(meta, m_data, omega_threshold, d_omega_px, pause, report_fraction):
    """Per view, instance and face, the share of the face the view's sample point reaches, 0 to 1 (V, K, F): visible
    over unoccluded solid angle. A face too small to measure from any view takes the share of a patch of its
    neighbours grown until it is measurable (decision 79); a piece too small even as a whole is undetermined and is
    resolved later. A generator: yields between pieces, its value is (lit, undetermined, patch size in pixels)."""
    vis_arr = m_data['vis_omega']
    unocc_arr = m_data['unocc_omega']
    n_faces = meta['n_orig_faces']
    lit = np.zeros(vis_arr.shape, dtype=np.float32)
    undetermined = np.zeros(n_faces, dtype=bool)
    patch_px = np.zeros(n_faces, dtype=np.float32)
    if vis_arr.shape[0] == 0 or n_faces == 0:
        return lit, undetermined, patch_px
    n_views, n_inst = vis_arr.shape[:2]
    rows = n_views * n_inst

    face_max = unocc_arr.max(axis=(0, 1))
    direct = face_max >= omega_threshold
    if np.any(direct):
        u = unocc_arr[:, :, direct]
        lit[:, :, direct] = np.where(u > 1e-12, np.clip(vis_arr[:, :, direct] / np.maximum(u, 1e-12), 0.0, 1.0), 0.0)
    patch_px[direct] = face_max[direct] / d_omega_px

    # A piece (connected component) too small to measure as a whole is undetermined
    components = [comp for comp in meta['components'] if len(comp)]
    if components:
        faces = np.concatenate(components)
        starts = np.cumsum([0] + [len(comp) for comp in components[:-1]])
        comp_max = np.add.reduceat(unocc_arr.reshape(rows, n_faces)[:, faces], starts, axis=1).max(axis=0)
        for comp, size in zip(components, comp_max):
            if 0.0 < size < omega_threshold:
                undetermined[comp] = True
                patch_px[comp] = size / d_omega_px

    small = np.flatnonzero((face_max > 0.0) & ~direct & ~undetermined)
    if len(small) == 0:
        return lit, undetermined, patch_px
    indptr, indices = adjacency_csr(meta['adjacency'])
    unocc_t = np.ascontiguousarray(unocc_arr.reshape(rows, n_faces).T, dtype=np.float64)
    vis_t = np.ascontiguousarray(vis_arr.reshape(rows, n_faces).T, dtype=np.float64)
    for begin in range(0, len(small), PATCH_CHUNK):
        if pause.due():
            report_fraction(begin / len(small))
            yield
        seeds = small[begin:begin + PATCH_CHUNK].astype(np.int64)
        patch_unocc, patch_vis = _grow_patches(seeds, indptr, indices, unocc_t, vis_t, omega_threshold)
        p_max = patch_unocc.max(axis=1)
        patch_px[seeds] = p_max / d_omega_px
        measured = p_max >= omega_threshold
        undetermined[seeds[~measured]] = True
        u, v = patch_unocc[measured], patch_vis[measured]
        share = np.where(u > 1e-12, np.clip(v / np.maximum(u, 1e-12), 0.0, 1.0), 0.0)
        lit[:, :, seeds[measured]] = share.T.reshape(n_views, n_inst, -1)
    return lit, undetermined, patch_px


def limit_steps(values, pairs, ratio):
    """Touching islands may differ by at most ratio (decisions 128 and 134): a darker island rises to its brighter
    neighbour divided by ratio; no island is ever lowered. The brightest islands are settled first, so one pass in
    falling order settles all (a rise travels on through the risen island's own neighbours). 1 makes all touching
    islands equal to the brightest of them. Returns (new values, pairs still above the ratio: always 0)."""
    v = np.array(values, dtype=np.float64)
    if len(pairs) == 0:
        return v, 0
    ratio = max(float(ratio), 1.0)
    neighbours = [[] for _ in range(len(v))]
    for a, b in pairs:
        neighbours[a].append(b)
        neighbours[b].append(a)
    heap = [(-value, i) for i, value in enumerate(v)]
    heapq.heapify(heap)
    while heap:
        negative, i = heapq.heappop(heap)
        if -negative < v[i]:
            continue  # risen since it was queued
        floor = v[i] / ratio
        for n in neighbours[i]:
            if v[n] < floor * (1.0 - 1e-12):
                v[n] = floor
                heapq.heappush(heap, (-floor, n))
    return v, 0


def island_pairs(adjacency, island_index):
    """The pairs of islands (indices) that share an edge in 3D: a UV seam between them, (smaller, larger), sorted."""
    indptr, indices = adjacency_csr(adjacency)
    island_index = np.asarray(island_index, dtype=np.int64)
    if len(indices) == 0:
        return []
    rows = np.repeat(np.arange(len(indptr) - 1), np.diff(indptr))
    a, b = island_index[rows], island_index[indices]
    lo, hi = np.minimum(a, b), np.maximum(a, b)
    keep = lo != hi
    n = int(island_index.max()) + 1
    codes = np.unique(lo[keep] * n + hi[keep])
    return [(int(code // n), int(code % n)) for code in codes]


def _score_pieces(mesh_meta, mesh_arrays, view_pairs, pair_states, pair_samples, n_states, min_px_threshold=10.0,
                  ref_cube_res=1024, island_percentile=0.9, step_limit=1.5, ambient=0.1, scene=None,
                  report=_no_report):
    """Score faces, islands and objects from the probe lights' views (decisions 124 to 128).

    view_pairs: per view, its (state, light) pair; pair_states: per pair, its state; pair_samples: per pair, how many
    sample points it has. A generator: yields between pieces, its value is the summaries."""
    t_start = time.perf_counter()
    d_omega_px = 4.0 / (ref_cube_res * ref_cube_res)
    omega_threshold = min_px_threshold * d_omega_px
    scene = scene or bpy.context.scene
    view_pairs = np.asarray(view_pairs, dtype=np.int64)
    pair_states = np.asarray(pair_states, dtype=np.int64)
    pair_samples = np.maximum(np.asarray(pair_samples, dtype=np.float64), 1.0)
    n_pairs = len(pair_states)

    children_map = {}
    for o in scene.objects:
        children_map.setdefault(o.parent.name if o.parent else None, []).append(o)

    def subtree_meshes(root):
        found, stack = [], [root]
        while stack:
            obj = stack.pop()
            if obj.type == 'MESH' and obj.data:
                found.append(obj)
            stack.extend(children_map.get(obj.name, []))
        return found

    def view_share(objects):
        """Per view, the lit share of a set of objects together, and its largest unoccluded solid angle."""
        vis = np.zeros(len(view_pairs))
        unocc = np.zeros(len(view_pairs))
        for o in objects:
            if is_invisible_object(o) or o.data.name not in mesh_meta or o.data.name not in mesh_arrays:
                continue
            k = mesh_meta[o.data.name]['instance_map'].get((o.name, 0), 0)
            vis += np.sum(mesh_arrays[o.data.name]['vis_omega'][:, k, :], axis=-1)
            unocc += np.sum(mesh_arrays[o.data.name]['unocc_omega'][:, k, :], axis=-1)
        share = np.where(unocc > 1e-12, np.clip(vis / np.maximum(unocc, 1e-12), 0.0, 1.0), 0.0)
        return share, float(np.max(unocc)) if len(unocc) else 0.0

    def resolve_share(obj):
        """A piece too small to measure takes the lit share of its object, else of the nearest parent's subtree that
        is measurable, else counts as fully lit (decision 79)."""
        share, size = view_share([obj])
        if size >= omega_threshold:
            return share, 'OBJECT'
        cur = obj.parent
        while cur is not None:
            share, size = view_share(subtree_meshes(cur))
            if size >= omega_threshold:
                return share, 'PARENT_SUBTREE'
            cur = cur.parent
        return np.ones(len(view_pairs)), 'FALLBACK_1.0'

    resolved_counts = {level: {'faces': 0, 'pieces': 0, 'objects': 0}
                       for level in ('OBJECT', 'PARENT_SUBTREE', 'FALLBACK_1.0')}
    pause = _Pause()
    names = list(mesh_meta)
    raw_isl = {}
    for index, m_name in enumerate(names):
        meta = mesh_meta[m_name]
        m_data = mesh_arrays[m_name]
        frac = 0.75 * index / max(len(names), 1)
        lit, undetermined, patch_px = yield from _lit_shares(
            meta, m_data, omega_threshold, d_omega_px, pause,
            lambda part: report(frac + 0.75 * part / max(len(names), 1)))
        if np.any(undetermined):
            for k, inst in enumerate(meta['instances']):
                obj = bpy.data.objects.get(inst['object_name'])
                share, level = resolve_share(obj) if obj is not None else (np.ones(len(view_pairs)), 'FALLBACK_1.0')
                lit[:, k, undetermined] = share[:, None]
                resolved_counts[level]['faces'] += int(np.count_nonzero(undetermined))
                resolved_counts[level]['objects'] += 1
                resolved_counts[level]['pieces'] += sum(
                    1 for comp in meta['components'] if len(comp) and np.all(undetermined[comp]))

        n_inst = lit.shape[1]
        n_faces = meta['n_orig_faces']
        mean_lit = np.zeros((n_pairs, n_inst, n_faces), dtype=np.float64)
        if len(view_pairs):
            for view, pair in enumerate(view_pairs):
                mean_lit[pair] += lit[view]
        mean_lit /= pair_samples[:, None, None]
        term = m_data['term_w'] / np.maximum(m_data['term_a'], 1e-30)
        light = np.zeros((n_states, n_inst, n_faces), dtype=np.float64)
        for pair, state in enumerate(pair_states):
            light[state] += mean_lit[pair] * term[pair]
        raw = srgb_encode(light).max(axis=(0, 1)) if n_states and n_inst else np.zeros(n_faces)
        del mean_lit, lit

        island_ids = meta['island_ids']
        unique_isls, isl_index = np.unique(island_ids, return_inverse=True)
        areas = meta['orig_areas'].astype(np.float64)
        isl_raw = np.zeros(len(unique_isls))
        order = np.argsort(isl_index, kind='stable')
        starts = np.searchsorted(isl_index[order], np.arange(len(unique_isls) + 1))
        for k in range(len(unique_isls)):
            faces = order[starts[k]:starts[k + 1]]
            isl_raw[k] = weighted_percentile(raw[faces], areas[faces], island_percentile)

        m_data['face_raw'] = raw.astype(np.float32)
        m_data['face_undetermined'] = undetermined
        m_data['face_never_seen'] = (raw <= 0.0) & ~undetermined
        m_data['face_patch_size_px'] = patch_px
        m_data['face_facing'] = np.ones(n_faces, dtype=np.float32)  # the light holds the facing (decision 126)
        raw_isl[m_name] = (unique_isls, isl_index, isl_raw, island_pairs(meta['adjacency'], isl_index), order, starts)
        if pause.due():
            report(0.75 * (index + 1) / max(len(names), 1))
            yield

    # One scale for the scene: the most visible island is 1.0 (decision 126)
    scale = max((float(np.max(entry[2])) for entry in raw_isl.values() if len(entry[2])), default=0.0)
    scale = scale if scale > 0.0 else 1.0
    face_max_raw = max((float(np.max(mesh_arrays[m]['face_raw'])) for m in names if len(mesh_arrays[m]['face_raw'])),
                       default=0.0)

    island_summaries = {}
    object_summaries = {}
    step_stats = {'pairs_left': 0, 'lowered': 0, 'raised': 0, 'largest_lowering': 1.0, 'largest_raising': 1.0,
                  'raised_area_m2': 0.0}
    ambient = min(max(float(ambient), 0.0), 1.0)
    for index, m_name in enumerate(names):
        meta = mesh_meta[m_name]
        m_data = mesh_arrays[m_name]
        unique_isls, isl_index, isl_raw, pairs, order, starts = raw_isl[m_name]
        areas = meta['orig_areas'].astype(np.float64)
        undetermined = m_data['face_undetermined']
        # Ambient lifts every island by the same share of the way to 1 (decision 133), then the step limit raises
        base = ambient + (1.0 - ambient) * isl_raw / scale
        values, left = limit_steps(base, pairs, step_limit)
        step_stats['pairs_left'] += left
        raised = values > base * (1.0 + 1e-9)
        step_stats['raised'] += int(np.count_nonzero(raised))
        if np.any(raised):
            step_stats['largest_raising'] = max(step_stats['largest_raising'],
                                                float(np.max(values[raised] / np.maximum(base[raised], 1e-30))))
            isl_area = np.bincount(isl_index, weights=areas, minlength=len(unique_isls))
            step_stats['raised_area_m2'] += float(np.sum(isl_area[raised]))

        m_data['face_scores'] = (ambient + (1.0 - ambient) * np.clip(m_data['face_raw'] / scale, 0.0, 1.0)).astype(
            np.float32)
        m_data['face_island_values'] = values[isl_index].astype(np.float32)
        m_data['island_scores'] = values.astype(np.float32)
        lit_faces = m_data['face_raw'] > 0.0
        for k, isl_id in enumerate(unique_isls):
            faces = order[starts[k]:starts[k + 1]]
            total = float(np.sum(areas[faces]))
            seen = float(np.sum(areas[faces][lit_faces[faces]]))
            island_summaries[f"{m_name}__isl_{isl_id}"] = {
                'mesh_name': m_name,
                'island_id': int(isl_id),
                'score': float(values[k]),
                'before_step_limit': float(base[k]),
                'size_px': float(np.max(m_data['face_patch_size_px'][faces])) if len(faces) else 0.0,
                'never_seen': bool(isl_raw[k] <= 0.0 and not np.any(undetermined[faces])),
                'seen_area_share': seen / total if total > 0.0 else 0.0,
                'undetermined_only': bool(len(faces) and np.all(undetermined[faces])),
                'area_m2': total,
                'n_faces': int(len(faces)),
            }
        total = float(np.sum(areas))
        o_score = weighted_percentile(m_data['face_island_values'].astype(np.float64), areas, island_percentile)
        for inst in meta['instances']:
            if inst['object_name'] in object_summaries:
                continue
            object_summaries[inst['object_name']] = {
                'mesh_name': m_name,
                'score': o_score,
                'size_px': float(np.max(m_data['face_patch_size_px'])) if len(areas) else 0.0,
                'never_seen': bool(not np.any(lit_faces) and not np.any(undetermined)),
                'undetermined': bool(len(areas) and np.all(undetermined)),
                'seen_area_share': float(np.sum(areas[lit_faces]) / total) if total > 0.0 else 0.0,
                'area_m2': total,
                'n_faces': int(meta['n_orig_faces']),
            }
        if pause.due():
            report(0.75 + 0.25 * (index + 1) / max(len(names), 1))
            yield

    return {
        'patch_expansion_time_s': time.perf_counter() - t_start,
        'resolved_counts': resolved_counts,
        'object_summaries': object_summaries,
        'island_summaries': island_summaries,
        'scale': scale,
        'brightest_face': face_max_raw,
        'step_limit': step_stats,
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
    """Save results as compressed `<blend_name>.visibility` (VISIBILITY_SCHEMA)."""
    vis_path = Path(blend_path).with_suffix('.visibility')

    mesh_face_counts = {
        m_name: meta['n_orig_faces'] for m_name, meta in results['mesh_meta'].items()
    }

    meta = {
        'schema_version': VISIBILITY_SCHEMA,
        'blend_file': str(results.get('blend_file', blend_path)),
        'timestamp': time.strftime("%Y-%m-%d %H:%M:%S"),
        'total_time_s': results.get('total_time_s', 0.0),
        'patch_expansion_time_s': results.get('patch_expansion_time_s', 0.0),
        'state_timings': results.get('state_timings', {}),
        'views': results.get('views', []),
        'lights': results.get('lights', []),
        'light_states': results.get('light_states', []),
        'ref_cube_res': results.get('ref_cube_res', 1024),
        'min_px_threshold': results.get('min_px_threshold', 10.0),
        'island_percentile': results.get('island_percentile', 0.9),
        'step_limit': results.get('step_limit', 1.5),
        'ambient': results.get('ambient', 0.1),
        'step_limit_result': results.get('step_limit_result', {}),
        'scale': results.get('scale', 1.0),
        'brightest_face': results.get('brightest_face', 0.0),
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
        'mesh_face_counts': mesh_face_counts,
        'object_eval_face_counts': results.get('object_eval_face_counts', {}),
        'object_summaries': results.get('object_summaries', {}),
        'island_summaries': results.get('island_summaries', {}),
        'settings': settings or {},
    }

    arrays_to_save = {
        '_meta_json': np.array([json.dumps(meta)]),
    }

    for m_name, m_data in results['mesh_arrays'].items():
        safe_name = m_name.replace('/', '_').replace('\\', '_')
        # The per-view sums are not kept: the scores hold all a reader needs, and the sums grow with every light
        # sample and state
        arrays_to_save[f"{safe_name}__face_scores"] = m_data['face_scores'].astype(np.float32)
        arrays_to_save[f"{safe_name}__face_island_values"] = m_data.get(
            'face_island_values', m_data['face_scores']).astype(np.float32)
        arrays_to_save[f"{safe_name}__face_undetermined"] = m_data['face_undetermined'].astype(bool)
        arrays_to_save[f"{safe_name}__face_never_seen"] = m_data['face_never_seen'].astype(bool)
        arrays_to_save[f"{safe_name}__face_patch_size_px"] = m_data['face_patch_size_px'].astype(np.float32)
        if 'face_facing' in m_data:
            arrays_to_save[f"{safe_name}__face_facing"] = m_data['face_facing'].astype(np.float32)

    for obj_name, eval_map in results.get('object_eval_face_maps', {}).items():
        safe_obj_name = obj_name.replace('/', '_').replace('\\', '_')
        arrays_to_save[f"eval_map__{safe_obj_name}"] = eval_map.astype(np.int32)

    with open(vis_path, 'wb') as f:
        np.savez_compressed(f, **arrays_to_save)

    vis_path_res = vis_path.resolve()
    if vis_path_res in _vis_file_cache:
        del _vis_file_cache[vis_path_res]

    return vis_path


_vis_file_cache = {}
_vis_file_load_count = 0


def get_file_load_count():
    """Return number of times a .visibility file was loaded from disk (for tests)."""
    return _vis_file_load_count


def clear_file_cache():
    """Clear cached .visibility file data."""
    global _vis_file_load_count
    _vis_file_cache.clear()


def is_old_visibility_file(meta):
    """True for a file scored by an older version of the rules: its numbers no longer mean what they say."""
    return meta.get('schema_version', 0) < VISIBILITY_SCHEMA


def _stale_mesh_names(meta, scene_meshes):
    """The meshes whose data cannot be used: changed ones, or all of them in a file with older scoring."""
    if not scene_meshes:
        return []
    saved_counts = meta.get('mesh_face_counts', {})
    if is_old_visibility_file(meta):
        return list(saved_counts)
    stale_meshes = []
    for m_name, saved_n_faces in saved_counts.items():
        me = scene_meshes.get(m_name)
        if me is None or len(me.polygons) != saved_n_faces:
            stale_meshes.append(m_name)
    return stale_meshes


class VisibilityArrays:
    """The arrays of a `.visibility` file, each unzipped once when first read (an npz file unzips again at every
    read). Reads like the npz file: `data[key]`, `data.get(key, default)`, `key in data`, `data.files`."""

    def __init__(self, npz):
        self._npz = npz
        self.files = list(npz.files)
        self._names = set(self.files)
        self._arrays = {}

    def __getitem__(self, key):
        array = self._arrays.get(key)
        if array is None:
            array = self._arrays[key] = self._npz[key]
        return array

    def __contains__(self, key):
        return key in self._names

    def get(self, key, default=None):
        return self[key] if key in self._names else default

    def keys(self):
        return list(self.files)

    def __iter__(self):
        return iter(self.files)

    def __len__(self):
        return len(self.files)

    def close(self):
        """Release the file (the arrays already read stay readable)."""
        self._npz.close()


def load_visibility_file(vis_path, scene_meshes=None, use_cache=True):
    """Load `.visibility` file and verify staleness against scene meshes."""
    global _vis_file_load_count
    vis_path = Path(vis_path).resolve()
    mtime = vis_path.stat().st_mtime if vis_path.exists() else 0.0

    if use_cache and vis_path in _vis_file_cache:
        cached = _vis_file_cache[vis_path]
        if cached['mtime'] == mtime:
            return cached['meta'], cached['data'], _stale_mesh_names(cached['meta'], scene_meshes)

    _vis_file_load_count += 1
    data = VisibilityArrays(np.load(vis_path))
    meta = json.loads(str(data['_meta_json'][0]))
    stale_meshes = _stale_mesh_names(meta, scene_meshes)

    if use_cache:
        _vis_file_cache[vis_path] = {
            'mtime': mtime,
            'meta': meta,
            'data': data,
        }

    return meta, data, stale_meshes


# ---------------------------------------------------------------------------
# Heatmap RGBA Color Mapping (0.0 red, 0.5 neutral, 1.0 blue)
# ---------------------------------------------------------------------------

def compute_heatmap_colors(scores, alpha=0.75):
    """Map visibility scores in [0.0, 1.0] to RGBA colors: black (0.0) to white (1.0)."""
    grey = np.clip(np.asarray(scores, dtype=np.float32), 0.0, 1.0)
    return np.column_stack((grey, grey, grey, np.full(len(grey), alpha, dtype=np.float32)))


# ---------------------------------------------------------------------------
# Step-by-Step Analysis Runner (Supports synchronous & modal execution)
# ---------------------------------------------------------------------------

def _add_by_slot(target, slots, values):
    """Add values into target (instances, faces) at the flat slots (instance x faces + face), repeats summed."""
    target += np.bincount(slots, weights=values, minlength=target.size).reshape(target.shape)


class VisibilityAnalyzer:
    """Visibility analysis from the included probe lights, one view (a light's sample point at an animation state) per
    step, so a modal operator can run it in pieces (Decisions 81 and 124)."""

    def __init__(
        self,
        scene,
        view_layer,
        lights,
        anim_states=(0.0, 0.25, 0.5, 0.75, 1.0),
        cube_res=1024,
        min_px_threshold=10.0,
        blend_path=None,
        shadow_samples=4,
        island_percentile=0.9,
        step_limit=1.5,
        ambient=0.1,
    ):
        if not lights:
            raise ValueError("No probe lights included.")

        self.scene = scene
        self.view_layer = view_layer
        self.lights = [name if isinstance(name, str) else name.name for name in lights]
        self.anim_states = tuple(float(s) for s in anim_states)
        self.cube_res = cube_res
        self.min_px_threshold = min_px_threshold
        self.blend_path = blend_path or ""
        self.shadow_samples = max(1, int(shadow_samples))
        self.island_percentile = float(island_percentile)
        self.step_limit = float(step_limit)
        self.ambient = float(ambient)

        # One sample for a light without radius (its soft shadows are hard), else shadow_samples over its radius
        self.light_samples = []
        for name in self.lights:
            record = light_record(bpy.data.objects.get(name), scene)
            self.light_samples.append(self.shadow_samples if record and record['radius'] > 0.0 else 1)

        self.shader = None
        self.off_cube = None
        self.cube_weights = None
        self.anim_ctrl = None
        self.mesh_meta = None
        self.mesh_arrays = None
        self.object_eval_face_maps = {}
        self.object_eval_face_counts = {}
        self.view_configs = []
        self.current_step = 0
        self.current_state_idx = -1
        self.batches = None
        self.eval_index = None
        self.bounds = None
        self.tri_geom = None
        self.max_id = 0
        self.batch_op = None
        self.batch_dec = None
        self.records = {}
        self.light_log = []
        self.t_start = 0.0
        self.state_timings = {}
        self._state_t0 = 0.0
        self.prepared = False
        self.cleaned_up = False
        self.activity = ''  # what is in work, for the bar's text
        n_views = len(self.anim_states) * sum(self.light_samples)
        self._units_total = UNITS_PREPARE + UNITS_FINAL + len(self.anim_states) * UNITS_READ + n_views * UNITS_VIEW
        self._units_done = 0.0
        self._units_now = 0.0
        self._part_now = 0.0

    def _begin(self, units, activity):
        self._units_done += self._units_now
        self._units_now, self._part_now, self.activity = units, 0.0, activity

    def _part(self, fraction):
        self._part_now = fraction

    def fraction_done(self):
        """How much of the whole run is done, 0 to 1."""
        return min((self._units_done + self._units_now * self._part_now) / self._units_total, 1.0)

    def run_pieces(self):
        """The whole run as a generator: a modal operator takes one piece per timer event, and Blender draws and reads Esc
        between them. Its value is the results, as finalize's."""
        yield from self._prepare_pieces()
        while not self.is_finished():
            yield from self._pieces_of_view()
        return (yield from self._finalize_pieces())

    def prepare(self):
        """Initialize shaders, attributes, instances and sum arrays."""
        _drain(self._prepare_pieces())

    def _prepare_pieces(self):
        if gpu is None:
            raise RuntimeError("GPU module not available.")

        self._begin(UNITS_PREPARE, 'Reading the scene: meshes and UV islands')
        yield
        gpu.init()
        self.shader = get_id_shader()
        add_orig_face_index_attributes()

        self.mesh_meta = yield from _discover_pieces(self.view_layer, self._part)

        # Views: per animation state, per light, per sample point; a (state, light) pair shares one light term
        self.view_configs = []
        n_lights = len(self.lights)
        for state_idx, state_val in enumerate(self.anim_states):
            for light_idx, name in enumerate(self.lights):
                for sample in range(self.light_samples[light_idx]):
                    self.view_configs.append({
                        'state_idx': state_idx,
                        'state_val': state_val,
                        'light': name,
                        'sample': sample,
                        'n_samples': self.light_samples[light_idx],
                        'pair': state_idx * n_lights + light_idx,
                    })

        n_views = len(self.view_configs)
        n_pairs = len(self.anim_states) * n_lights
        self.mesh_arrays = {}
        for m_name, meta in self.mesh_meta.items():
            n_inst = max(len(meta['instances']), 1)
            n_faces = meta['n_orig_faces']
            self.mesh_arrays[m_name] = {
                'vis_omega': np.zeros((n_views, n_inst, n_faces), dtype=np.float32),
                'unocc_omega': np.zeros((n_views, n_inst, n_faces), dtype=np.float32),
                'term_w': np.zeros((n_pairs, n_inst, n_faces), dtype=np.float32),
                'term_a': np.zeros((n_pairs, n_inst, n_faces), dtype=np.float32),
                'area': meta['orig_areas'],
                'island_ids': meta['island_ids'],
            }

        self.off_cube = gpu.types.GPUOffScreen(self.cube_res, self.cube_res)
        self.cube_weights = precompute_cubemap_weights(self.cube_res)
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
        """Execute one view pass (one light sample at one animation state)."""
        if not self.prepared:
            self.prepare()
        if self.is_finished():
            return None
        return _drain(self._pieces_of_view())

    def _read_state(self, state_val):
        """Set the animation state, read the scene's geometry and the lights as they are at that frame."""
        self.anim_ctrl.apply_percentage_state(state_val)
        dg = bpy.context.evaluated_depsgraph_get()
        (self.batches, self.eval_index, self.tri_geom, self.max_id,
         obj_maps, obj_counts) = yield from _extract_pieces(dg, self.view_layer, self.mesh_meta, self._part)
        self.object_eval_face_maps.update(obj_maps)
        self.object_eval_face_counts.update(obj_counts)
        self.bounds = scene_bounds(self.view_layer) or False  # the same for every view of this state

        self.records = {name: light_record(bpy.data.objects.get(name), self.scene, dg) for name in self.lights}
        self.light_log.append({name: None if r is None else {
            'type': r['type'], 'power': r['power'], 'radius': r['radius'], 'reach': r['reach'],
            'pos': [float(c) for c in r['pos']]} for name, r in self.records.items()})

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

    def _pieces_of_view(self):
        """A generator: one view, yielding between pieces; its value is the view's info."""
        view_cfg = self.view_configs[self.current_step]
        state_idx = view_cfg['state_idx']
        state_val = view_cfg['state_val']

        if state_idx != self.current_state_idx:
            if self.current_state_idx >= 0:
                pct_prev = f"{int(self.anim_states[self.current_state_idx] * 100)}%"
                self.state_timings[pct_prev] = time.perf_counter() - self._state_t0
            self.current_state_idx = state_idx
            self._state_t0 = time.perf_counter()
            self._begin(UNITS_READ, f'Reading the scene at animation {int(round(state_val * 100))} %')
            yield
            yield from self._read_state(state_val)
            yield

        name = view_cfg['light']
        sample = view_cfg['sample']
        self._begin(UNITS_VIEW, f"View {self.current_step + 1} of {len(self.view_configs)}: {name}"
                                + (f", shadow sample {sample + 1} of {view_cfg['n_samples']}" if view_cfg['n_samples'] > 1 else '')
                                + f", animation {int(round(state_val * 100))} %")
        record = self.records.get(name)
        info = {'step': self.current_step + 1, 'total_steps': len(self.view_configs), 'light': name,
                'sample': sample, 'state_pct': state_val}
        if record is None or len(self.tri_geom['V0']) == 0:
            self.current_step += 1
            return info

        offsets = light_sample_offsets(view_cfg['n_samples'])
        eye = record['pos'] + offsets[sample] * record['radius']
        n_ids = self.max_id + 1
        if 'planar' not in self.tri_geom:
            self.tri_geom['planar'] = tuple(np.ascontiguousarray(self.tri_geom[k].T) for k in ('V0', 'V1', 'V2'))
        tri_omega = planar_solid_angle(eye, *self.tri_geom['planar'])
        eval_unocc = np.bincount(self.tri_geom['tri_ids'], weights=tri_omega, minlength=n_ids)
        term = None
        if sample == 0:
            term = batch_light_term(record, self.tri_geom['V0'], self.tri_geom['V1'], self.tri_geom['V2'],
                                    self.tri_geom['tri_ids'], n_ids)
        self._part(0.1)
        yield

        near_plane, far_plane = compute_scene_extent(self.view_layer, eye, self.bounds)
        eval_vis = np.zeros(n_ids, dtype=np.float64)
        reached = cube_faces_in_cone(record)
        faces = [face for face in cubemap_face_matrices(eye, near=near_plane, far=far_plane) if face[0] in reached]
        for side, (_face_name, v_mat, p_mat) in enumerate(faces, 1):
            eval_vis += render_camera_view(self.off_cube, self.shader, self.batch_op, self.batch_dec, p_mat @ v_mat,
                                           self.cube_weights, self.max_id)
            self._part(0.1 + 0.85 * side / max(len(faces), 1))
            yield

        step = self.current_step
        pair = view_cfg['pair']
        for m_name, (eids, ks, fs) in self.eval_index.items():
            arrays = self.mesh_arrays[m_name]
            slots = ks * arrays['vis_omega'].shape[2] + fs
            _add_by_slot(arrays['vis_omega'][step], slots, eval_vis[eids])
            _add_by_slot(arrays['unocc_omega'][step], slots, eval_unocc[eids])
            if term is not None:
                _add_by_slot(arrays['term_w'][pair], slots, term[0][eids])
                _add_by_slot(arrays['term_a'][pair], slots, term[1][eids])

        self.current_step += 1
        return info

    def finalize(self):
        """Score faces, islands and objects, and build the results dict."""
        return _drain(self._finalize_pieces())

    def _finalize_pieces(self):
        self._begin(UNITS_FINAL, 'Scoring the faces')
        yield
        if self.current_state_idx >= 0:
            pct_last = f"{int(self.anim_states[self.current_state_idx] * 100)}%"
            self.state_timings[pct_last] = time.perf_counter() - self._state_t0

        n_lights = len(self.lights)
        n_pairs = len(self.anim_states) * n_lights
        pair_states = [pair // n_lights for pair in range(n_pairs)]
        pair_samples = [self.light_samples[pair % n_lights] for pair in range(n_pairs)]
        view_pairs = [cfg['pair'] for cfg in self.view_configs]
        score = yield from _score_pieces(
            self.mesh_meta, self.mesh_arrays, view_pairs, pair_states, pair_samples, len(self.anim_states),
            min_px_threshold=self.min_px_threshold, ref_cube_res=self.cube_res,
            island_percentile=self.island_percentile, step_limit=self.step_limit, ambient=self.ambient, scene=self.scene,
            report=self._part)
        total_time = time.perf_counter() - self.t_start

        all_face_scores, all_face_areas = [], []
        tot_nv_faces = tot_udet_faces = 0
        tot_nv_area = tot_udet_area = 0.0
        for m_name, meta in self.mesh_meta.items():
            m_data = self.mesh_arrays[m_name]
            f_ar = meta['orig_areas']
            all_face_scores.append(m_data['face_scores'])
            all_face_areas.append(f_ar)
            tot_nv_faces += int(np.count_nonzero(m_data['face_never_seen']))
            tot_nv_area += float(np.sum(f_ar[m_data['face_never_seen']]))
            tot_udet_faces += int(np.count_nonzero(m_data['face_undetermined']))
            tot_udet_area += float(np.sum(f_ar[m_data['face_undetermined']]))

        concat_scores = np.concatenate(all_face_scores) if all_face_scores else np.zeros(0, dtype=np.float32)
        concat_areas = np.concatenate(all_face_areas) if all_face_areas else np.zeros(0, dtype=np.float32)
        isl_sums = score['island_summaries']
        isl_scores = np.array([isl['score'] for isl in isl_sums.values()], dtype=np.float32)
        isl_areas = np.array([isl['area_m2'] for isl in isl_sums.values()], dtype=np.float32)
        obj_sums = score['object_summaries']

        return {
            'blend_file': str(self.blend_path),
            'total_time_s': total_time,
            'patch_expansion_time_s': score['patch_expansion_time_s'],
            'state_timings': self.state_timings,
            'views': [{'light': v['light'], 'sample': v['sample'], 'state': v['state_val']} for v in self.view_configs],
            'lights': [{'name': name, 'samples': n} for name, n in zip(self.lights, self.light_samples)],
            'light_states': self.light_log,
            'ref_cube_res': self.cube_res,
            'min_px_threshold': self.min_px_threshold,
            'island_percentile': self.island_percentile,
            'step_limit': self.step_limit,
            'ambient': self.ambient,
            'step_limit_result': score['step_limit'],
            'scale': score['scale'],
            'brightest_face': score['brightest_face'],
            'total_faces': len(concat_scores),
            'total_surface_area_m2': float(np.sum(concat_areas)),
            'total_objects': len(obj_sums),
            'never_seen_objects_count': sum(1 for o in obj_sums.values() if o['never_seen']),
            'undetermined_objects_count': sum(1 for o in obj_sums.values() if o['undetermined']),
            'total_islands': len(isl_sums),
            'never_seen_islands_count': sum(1 for isl in isl_sums.values() if isl['never_seen']),
            'total_never_seen_faces': tot_nv_faces,
            'total_never_seen_face_area_m2': tot_nv_area,
            'total_undetermined_faces': tot_udet_faces,
            'total_undetermined_face_area_m2': tot_udet_area,
            'face_percentiles': {f'p{q}': weighted_percentile(concat_scores, concat_areas, q / 100.0) for q in (50, 90, 95)},
            'island_percentiles': {f'p{q}': weighted_percentile(isl_scores, isl_areas, q / 100.0) for q in (50, 90, 95)},
            'resolved_counts': score['resolved_counts'],
            'mesh_meta': self.mesh_meta,
            'mesh_arrays': self.mesh_arrays,
            'object_summaries': obj_sums,
            'island_summaries': isl_sums,
            'object_eval_face_maps': self.object_eval_face_maps,
            'object_eval_face_counts': self.object_eval_face_counts,
        }

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


def analyze_visibility(
    blend_path,
    lights,
    anim_states=(0.0, 0.25, 0.5, 0.75, 1.0),
    cube_res=1024,
    min_px_threshold=10.0,
    scene=None,
    view_layer=None,
    shadow_samples=4,
    island_percentile=0.9,
    step_limit=1.5,
    ambient=0.1,
):
    """Synchronous execution of visibility analysis returning complete results dict."""
    scene = scene or bpy.context.scene
    view_layer = view_layer or bpy.context.view_layer

    analyzer = VisibilityAnalyzer(
        scene=scene,
        view_layer=view_layer,
        lights=lights,
        anim_states=anim_states,
        cube_res=cube_res,
        min_px_threshold=min_px_threshold,
        blend_path=blend_path,
        shadow_samples=shadow_samples,
        island_percentile=island_percentile,
        step_limit=step_limit,
        ambient=ambient,
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

def get_object_visibility(obj, uv_name=None, vis_path=None, use_cache=True):
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
        meta, data, stale_meshes = load_visibility_file(vis_path, scene_meshes=bpy.data.meshes, use_cache=use_cache)
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
    face_island_values = data.get(f"{safe_name}__face_island_values")
    island_percentile = float(meta.get('island_percentile', 0.9))
    ambient = float(meta.get('ambient', 0.0))

    # Extract UV islands under requested or active UV map
    island_ids = extract_mesh_uv_islands(me, uv_name=uv_name)
    unique_isls = np.unique(island_ids)

    # Face areas in world space
    orig_areas = polygon_areas(me, obj.matrix_world)

    vis_data_ctx = {
        'stale': False,
        'face_scores': face_scores,
        'face_island_values': face_island_values,
        'island_percentile': island_percentile,
        'ambient': ambient,
        'orig_areas': orig_areas,
    }

    island_values = {}
    order = np.argsort(island_ids, kind='stable')
    bounds = np.searchsorted(island_ids[order], np.arange(len(unique_isls) + 1))
    for k, isl_id in enumerate(unique_isls):
        island_values[int(isl_id)] = score_face_set(obj, order[bounds[k]:bounds[k + 1]], vis_data=vis_data_ctx)

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
        'face_island_values': face_island_values,
        'island_percentile': island_percentile,
        'ambient': ambient,
        'orig_areas': orig_areas,
        'face_facing': data.get(f"{safe_name}__face_facing"),
    }


def seen_share_face_set(vis_data, face_indices):
    """The share of a face set's area that some probe light reaches, 0 to 1. Every face scores at least the Ambient
    (decision 133), so the file's never-lit flags decide; without them, a score above 0."""
    faces = np.asarray(face_indices, dtype=np.int32)
    areas = vis_data['orig_areas'][faces]
    total = float(np.sum(areas))
    if total <= 0.0:
        return 1.0
    never = vis_data.get('face_never_seen')
    lit = ~np.asarray(never, dtype=bool)[faces] if never is not None else vis_data['face_scores'][faces] > 0.0
    return float(np.sum(areas[lit]) / total)


def facing_face_set(vis_data, face_indices):
    """How directly a face set faces the cameras, 0 to 1: its faces' facing values averaged by area, hidden and back
    faces counting 0, so an island mostly at the back is low even when one rim of it is seen. 1.0 for a file written
    before facing existed."""
    facing = vis_data.get('face_facing')
    if facing is None:
        return 1.0
    faces = np.asarray(face_indices, dtype=np.int32)
    areas = vis_data['orig_areas'][faces]
    total = float(np.sum(areas))
    values = facing[faces]
    return float(np.sum(values * areas) / total) if total > 0.0 else float(np.mean(values)) if len(faces) else 1.0


def score_face_set(obj, face_indices, vis_data=None, vis_path=None, use_cache=True):
    """The visibility value of a set of faces (an island at pack time): the file's island percentile, by area, of the
    island values its faces had when the file was written (decision 127, after the step limit of decision 128). For an
    island unchanged since then this is its value. Without island values, the percentile of the face scores. 1.0 when
    the visibility data is missing or stale."""
    if obj is None or obj.type != 'MESH' or not obj.data:
        return 1.0
    if vis_data is None:
        vis_data = get_object_visibility(obj, vis_path=vis_path, use_cache=use_cache)
    if vis_data.get('stale', True):
        return 1.0
    face_indices = np.asarray(face_indices, dtype=np.int32)
    if len(face_indices) == 0:
        return 0.0
    values = vis_data.get('face_island_values')
    if values is None:
        values = vis_data.get('face_scores')  # data without island values: the percentile of the faces themselves
    orig_areas = vis_data.get('orig_areas')
    if values is None or orig_areas is None:
        return 1.0
    return weighted_percentile(np.asarray(values, dtype=np.float64)[face_indices],
                               np.asarray(orig_areas, dtype=np.float64)[face_indices],
                               float(vis_data.get('island_percentile', 0.9)))
