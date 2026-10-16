"""Tools: scene authoring helpers for parenting and object origins.

Add Empty Parent inserts a <Name>_PARENT empty at each selected object's location and rotation (unit scale), taking
over its current parent and collections while keeping the object's world transform.
Origin to Bounding Box computes the minimum-volume oriented bounding box (OBB) of each selected object's own geometry
(children excluded), aligns the object's origin orientation to the OBB and moves its origin to one of the 8 corners,
6 face centers or 12 edge centers without moving the geometry or any child objects in world space.
"""

import itertools
import math

import bpy
import mathutils
from mathutils import Matrix, Vector
import numpy as np

CORNER_TARGETS = (
    ("CORNER_NNN", "Bottom Front Left (-X -Y -Z)", (-1.0, -1.0, -1.0)),
    ("CORNER_PNN", "Bottom Front Right (+X -Y -Z)", (1.0, -1.0, -1.0)),
    ("CORNER_NPN", "Bottom Back Left (-X +Y -Z)", (-1.0, 1.0, -1.0)),
    ("CORNER_PPN", "Bottom Back Right (+X +Y -Z)", (1.0, 1.0, -1.0)),
    ("CORNER_NNP", "Top Front Left (-X -Y +Z)", (-1.0, -1.0, 1.0)),
    ("CORNER_PNP", "Top Front Right (+X -Y +Z)", (1.0, -1.0, 1.0)),
    ("CORNER_NPP", "Top Back Left (-X +Y +Z)", (-1.0, 1.0, 1.0)),
    ("CORNER_PPP", "Top Back Right (+X +Y +Z)", (1.0, 1.0, 1.0)),
)

FACE_TARGETS = (
    ("FACE_NZ", "Bottom (-Z)", (0.0, 0.0, -1.0)),
    ("FACE_PZ", "Top (+Z)", (0.0, 0.0, 1.0)),
    ("FACE_NY", "Front (-Y)", (0.0, -1.0, 0.0)),
    ("FACE_PY", "Back (+Y)", (0.0, 1.0, 0.0)),
    ("FACE_NX", "Left (-X)", (-1.0, 0.0, 0.0)),
    ("FACE_PX", "Right (+X)", (1.0, 0.0, 0.0)),
)

EDGE_TARGETS = (
    ("EDGE_0NN", "Bottom Front (0 -Y -Z)", (0.0, -1.0, -1.0)),
    ("EDGE_0PN", "Bottom Back (0 +Y -Z)", (0.0, 1.0, -1.0)),
    ("EDGE_N0N", "Bottom Left (-X 0 -Z)", (-1.0, 0.0, -1.0)),
    ("EDGE_P0N", "Bottom Right (+X 0 -Z)", (1.0, 0.0, -1.0)),
    ("EDGE_0NP", "Top Front (0 -Y +Z)", (0.0, -1.0, 1.0)),
    ("EDGE_0PP", "Top Back (0 +Y +Z)", (0.0, 1.0, 1.0)),
    ("EDGE_N0P", "Top Left (-X 0 +Z)", (-1.0, 0.0, 1.0)),
    ("EDGE_P0P", "Top Right (+X 0 +Z)", (1.0, 0.0, 1.0)),
    ("EDGE_NN0", "Front Left (-X -Y 0)", (-1.0, -1.0, 0.0)),
    ("EDGE_PN0", "Front Right (+X -Y 0)", (1.0, -1.0, 0.0)),
    ("EDGE_NP0", "Back Left (-X +Y 0)", (-1.0, 1.0, 0.0)),
    ("EDGE_PP0", "Back Right (+X +Y 0)", (1.0, 1.0, 0.0)),
)

ALL_TARGETS = CORNER_TARGETS + FACE_TARGETS + EDGE_TARGETS
TARGET_COORDS = {item[0]: item[2] for item in ALL_TARGETS}
TARGET_LABELS = {item[0]: item[1] for item in ALL_TARGETS}
TARGET_ENUM_ITEMS = tuple((item[0], item[1], "") for item in ALL_TARGETS)

# All 24 right-handed signed permutations of 3 basis vectors
_RIGHT_HANDED_PERMS = []
for _perm in itertools.permutations((0, 1, 2)):
    _parity = (
        (_perm[0] > _perm[1]) + (_perm[0] > _perm[2]) + (_perm[1] > _perm[2])
    ) % 2
    for _sx in (-1.0, 1.0):
        for _sy in (-1.0, 1.0):
            for _sz in (-1.0, 1.0):
                if _sx * _sy * _sz == (-1.0 if _parity else 1.0):
                    _RIGHT_HANDED_PERMS.append((_perm, (_sx, _sy, _sz)))


def _dedup_axes(candidates, limit=24, cos_tol=0.9995):
    """Keeps up to limit unit vectors that are not parallel or anti-parallel within cos_tol."""
    kept = []
    for vec in candidates:
        norm = float(np.linalg.norm(vec))
        if norm < 1e-8:
            continue
        unit = vec / norm
        if any(abs(float(np.dot(unit, prev))) >= cos_tol for prev in kept):
            continue
        kept.append(unit)
        if len(kept) >= limit:
            break
    return kept


def _world_points_and_axes(obj, depsgraph):
    """Returns (world_pts, candidate_axes) for obj's own geometry (children not included), or (None, None)."""
    mat = np.array(obj.matrix_world, dtype=np.float64)
    linear = mat[:3, :3]
    translation = mat[:3, 3]
    rot_ref = np.array(obj.matrix_world.to_quaternion().to_matrix(), dtype=np.float64)
    base_axes = [rot_ref[:, 0], rot_ref[:, 1], rot_ref[:, 2],
                 np.array((1.0, 0.0, 0.0)), np.array((0.0, 1.0, 0.0)), np.array((0.0, 0.0, 1.0))]

    mesh = obj.data if obj.type == 'MESH' else None
    temp_eval = None
    if mesh is None:
        if obj.data is None or not hasattr(obj.data, "transform"):
            return None, None
        temp_eval = obj.evaluated_get(depsgraph) if depsgraph is not None else obj
        try:
            mesh = temp_eval.to_mesh()
        except RuntimeError:
            mesh = None

    try:
        if mesh is not None and len(mesh.vertices) > 0:
            local_pts = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
            mesh.vertices.foreach_get("co", local_pts)
            local_pts = local_pts.reshape(-1, 3).astype(np.float64)
            world_pts = local_pts @ linear.T + translation

            extra_axes = []
            if len(mesh.polygons) > 0:
                normals = np.empty(len(mesh.polygons) * 3, dtype=np.float32)
                areas = np.empty(len(mesh.polygons), dtype=np.float32)
                mesh.polygons.foreach_get("normal", normals)
                mesh.polygons.foreach_get("area", areas)
                normals = normals.reshape(-1, 3).astype(np.float64)
                normal_mat = np.linalg.inv(linear).T if abs(np.linalg.det(linear)) > 1e-12 else rot_ref
                order = np.argsort(-areas)[:64]
                extra_axes.extend(_dedup_axes(normals[order] @ normal_mat.T, limit=12))
            if len(mesh.edges) > 0:
                edges = np.empty(len(mesh.edges) * 2, dtype=np.int32)
                mesh.edges.foreach_get("vertices", edges)
                edges = edges.reshape(-1, 2)
                vecs = world_pts[edges[:, 1]] - world_pts[edges[:, 0]]
                lengths = np.linalg.norm(vecs, axis=1)
                order = np.argsort(-lengths)[:64]
                extra_axes.extend(_dedup_axes(vecs[order], limit=12))
        else:
            if not hasattr(obj, "bound_box"):
                return None, None
            local_pts = np.array([ tuple(c) for c in obj.bound_box ], dtype=np.float64)
            world_pts = local_pts @ linear.T + translation
            extra_axes = []
    finally:
        if temp_eval is not None:
            temp_eval.to_mesh_clear()

    if len(world_pts) >= 3:
        centered = world_pts - world_pts.mean(axis=0)
        _vals, vecs = np.linalg.eigh(centered.T @ centered)
        base_axes.extend([vecs[:, 0], vecs[:, 1], vecs[:, 2]])

    return world_pts, _dedup_axes(base_axes + extra_axes, limit=32)


def _frame_from_axis(axis, pts_for_hull):
    """Builds the 3x3 orthonormal frame [x, y, z] whose z is axis and (x, y) is the exact 2D minimum box via box_fit_2d."""
    vz = Vector(axis).normalized()
    vu = vz.orthogonal().normalized()
    vv = vz.cross(vu).normalized()
    u = np.array(vu, dtype=np.float64)
    v = np.array(vv, dtype=np.float64)
    z = np.array(vz, dtype=np.float64)
    pts_2d = np.column_stack((pts_for_hull @ u, pts_for_hull @ v))
    angle = mathutils.geometry.box_fit_2d(pts_2d.tolist())
    c, s = math.cos(-angle), math.sin(-angle)
    x = c * u + s * v
    y = -s * u + c * v
    return np.column_stack((x, y, z))


def _box_score(world_pts, frame, fixed_scale):
    """Scores a 3x3 orthonormal frame by bounding box volume, with surface area and extent sum for flat/thin meshes."""
    proj = world_pts @ frame
    extents = np.maximum(proj.max(axis=0) - proj.min(axis=0), 0.0)
    e = extents / fixed_scale
    volume = float(e[0] * e[1] * e[2])
    area = float(e[0] * e[1] + e[1] * e[2] + e[2] * e[0])
    length = float(e[0] + e[1] + e[2])
    return volume + 1e-4 * area + 1e-8 * length


def _align_axes_to_reference(frame, ref_frame):
    """Picks the right-handed signed permutation of frame's columns closest to ref_frame."""
    best_frame = frame
    best_trace = -4.0
    for perm, signs in _RIGHT_HANDED_PERMS:
        cand = np.column_stack((
            frame[:, perm[0]] * signs[0],
            frame[:, perm[1]] * signs[1],
            frame[:, perm[2]] * signs[2],
        ))
        trace = float(np.trace(cand.T @ ref_frame))
        if trace > best_trace:
            best_trace = trace
            best_frame = cand
    return best_frame


def compute_obb(obj, depsgraph):
    """Returns (rotation_matrix_3x3, b_min_3, b_max_3) of obj's minimum-volume OBB in world space, or None."""
    world_pts, axes = _world_points_and_axes(obj, depsgraph)
    if world_pts is None or len(world_pts) == 0:
        return None

    fixed_scale = float(np.linalg.norm(world_pts.max(axis=0) - world_pts.min(axis=0)))
    if fixed_scale < 1e-12:
        fixed_scale = 1.0

    ref_frame = np.array(obj.matrix_world.to_quaternion().to_matrix(), dtype=np.float64)
    best_frame = ref_frame
    best_score = _box_score(world_pts, ref_frame, fixed_scale)

    # Subsample very dense meshes for the 2D rotating-calipers search; full vertices still score and bound the box
    if len(world_pts) > 4096:
        step = max(1, len(world_pts) // 4096)
        hull_pts = world_pts[::step]
    else:
        hull_pts = world_pts

    for axis in axes:
        f1 = _frame_from_axis(axis, hull_pts)
        candidates = [f1, _frame_from_axis(f1[:, 0], hull_pts), _frame_from_axis(f1[:, 1], hull_pts)]
        for cand in candidates:
            score = _box_score(world_pts, cand, fixed_scale)
            # Prefer the current orientation on ties (within floating-point noise)
            if score < best_score * (1.0 - 1e-5):
                best_score = score
                best_frame = cand

    aligned = _align_axes_to_reference(best_frame, ref_frame)
    proj = world_pts @ aligned
    b_min = proj.min(axis=0)
    b_max = proj.max(axis=0)
    rot_mat = Matrix(aligned.tolist())
    return rot_mat, b_min, b_max


class FSS_OT_AddEmptyParent(bpy.types.Operator):
    bl_idname = "fss.add_empty_parent"
    bl_label = "Add Empty Parent"
    bl_description = ("Insert an empty parent named <Object>_PARENT at each selected object's location and rotation, "
                      "keeping all world transforms")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and bool(context.selected_objects)

    def execute(self, context):
        selected = list(context.selected_objects)
        created = []
        for obj in selected:
            world = obj.matrix_world.copy()
            loc, rot, _scale = world.decompose()
            empty_world = Matrix.LocRotScale(loc, rot, Vector((1.0, 1.0, 1.0)))

            parent = obj.parent
            parent_type = obj.parent_type if parent is not None else 'OBJECT'
            parent_bone = obj.parent_bone if parent is not None else ""

            empty = bpy.data.objects.new(f"{obj.name}_PARENT", None)
            empty.empty_display_type = 'PLAIN_AXES'
            empty.empty_display_size = 0.02
            collections = list(obj.users_collection) or [context.scene.collection]
            for collection in collections:
                collection.objects.link(empty)

            if parent is not None:
                empty.parent = parent
                empty.parent_type = parent_type
                if parent_type == 'BONE':
                    empty.parent_bone = parent_bone
                context.view_layer.update()
            empty.matrix_world = empty_world
            context.view_layer.update()

            obj.parent = empty
            obj.parent_type = 'OBJECT'
            obj.parent_bone = ""
            obj.matrix_parent_inverse.identity()
            obj.matrix_world = world
            created.append(empty)

        context.view_layer.update()
        self.report({'INFO'}, f"Added {len(created)} empty parent(s)")
        return {'FINISHED'}


class FSS_OT_OriginToBounds(bpy.types.Operator):
    bl_idname = "fss.origin_to_bounds"
    bl_label = "Origin to Bounding Box"
    bl_description = ("Move the selected objects' origins to the chosen point of their oriented bounding box "
                      "(own geometry only, children excluded) and align the origin orientation to the bounding box")
    bl_options = {'REGISTER', 'UNDO'}

    target: bpy.props.EnumProperty(name="Position", items=TARGET_ENUM_ITEMS, default="FACE_NZ")

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and bool(context.selected_objects)

    def execute(self, context):
        coords = np.array(TARGET_COORDS[self.target], dtype=np.float64)
        depsgraph = context.evaluated_depsgraph_get()
        changed = 0
        skipped = 0

        for obj in list(context.selected_objects):
            if obj.library is not None or obj.override_library is not None or obj.data is None:
                skipped += 1
                continue
            if not hasattr(obj.data, "transform") or obj.data.library is not None:
                skipped += 1
                continue

            obb = compute_obb(obj, depsgraph)
            if obb is None:
                skipped += 1
                continue
            rot_mat, b_min, b_max = obb
            center = 0.5 * (b_min + b_max)
            half = 0.5 * (b_max - b_min)
            target_obb = center + coords * half
            origin_world = rot_mat @ Vector(target_obb.tolist())

            old_world = obj.matrix_world.copy()
            _old_loc, _old_rot, old_scale = old_world.decompose()
            new_world = Matrix.LocRotScale(origin_world, rot_mat.to_quaternion(), old_scale)
            delta = new_world.inverted_safe() @ old_world

            if obj.data.users > 1:
                obj.data = obj.data.copy()
            if obj.type == 'MESH':
                obj.data.transform(delta, shape_keys=True)
                obj.data.update()
            else:
                obj.data.transform(delta)

            child_inverses = [
                (child, child.matrix_parent_inverse.copy())
                for child in obj.children
                if child.parent_type == 'OBJECT'
            ]
            obj.matrix_world = new_world
            for child, parent_inv in child_inverses:
                child.matrix_parent_inverse = delta @ parent_inv

            changed += 1

        context.view_layer.update()
        if changed:
            if context.scene.transform_orientation_slots:
                context.scene.transform_orientation_slots[0].type = 'LOCAL'
            label = TARGET_LABELS.get(self.target, self.target)
            msg = f"Origin set to {label} on {changed} object(s)"
            if skipped:
                msg += f" ({skipped} skipped)"
            self.report({'INFO'}, msg)
        else:
            self.report({'WARNING'}, "No editable geometry objects selected")
            return {'CANCELLED'}
        return {'FINISHED'}


class FSS_MT_OriginBoundsCorners(bpy.types.Menu):
    bl_idname = "FSS_MT_origin_bounds_corners"
    bl_label = "Corners"

    def draw(self, context):
        layout = self.layout
        for target_id, label, _coords in CORNER_TARGETS:
            layout.operator(FSS_OT_OriginToBounds.bl_idname, text=label).target = target_id


class FSS_MT_OriginBoundsFaces(bpy.types.Menu):
    bl_idname = "FSS_MT_origin_bounds_faces"
    bl_label = "Face-Center"

    def draw(self, context):
        layout = self.layout
        for target_id, label, _coords in FACE_TARGETS:
            layout.operator(FSS_OT_OriginToBounds.bl_idname, text=label).target = target_id


class FSS_MT_OriginBoundsEdges(bpy.types.Menu):
    bl_idname = "FSS_MT_origin_bounds_edges"
    bl_label = "Edge-Center"

    def draw(self, context):
        layout = self.layout
        for target_id, label, _coords in EDGE_TARGETS:
            layout.operator(FSS_OT_OriginToBounds.bl_idname, text=label).target = target_id


class FSS_MT_OriginToBounds(bpy.types.Menu):
    bl_idname = "FSS_MT_origin_to_bounds"
    bl_label = "Origin to Bounding Box"

    def draw(self, context):
        layout = self.layout
        layout.menu(FSS_MT_OriginBoundsCorners.bl_idname, icon='VERTEXSEL')
        layout.menu(FSS_MT_OriginBoundsFaces.bl_idname, icon='FACESEL')
        layout.menu(FSS_MT_OriginBoundsEdges.bl_idname, icon='EDGESEL')


class FSS_PT_Tools(bpy.types.Panel):
    bl_idname = "FSS_PT_tools"
    bl_label = "Tools"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "FSS Tools"

    def draw(self, context):
        layout = self.layout
        layout.operator(FSS_OT_AddEmptyParent.bl_idname, icon='EMPTY_AXIS')
        layout.menu(FSS_MT_OriginToBounds.bl_idname, icon='OBJECT_ORIGIN')


CLASSES = (
    FSS_OT_AddEmptyParent,
    FSS_OT_OriginToBounds,
    FSS_MT_OriginBoundsCorners,
    FSS_MT_OriginBoundsFaces,
    FSS_MT_OriginBoundsEdges,
    FSS_MT_OriginToBounds,
    FSS_PT_Tools,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
