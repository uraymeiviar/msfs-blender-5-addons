"""Evaluate source bounds once; share immutable LOD membership with every consumer."""

import json
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Vector

from . import lod_rules, tags

HIDE_KEY = 'fss_lod'
SHOW_KEY = 'fss_lod_show_from'
KEEP_KEY = 'fss_lod_keep'
HIDDEN_KEY = '_fss_lod_hidden'
_export_plan = None
_export_level = None
_merged_meshes = 0
_culled_pieces = 0


def mark(obj, key):
    value = obj.get(key, 0)
    return max(0, min(6, int(value))) if isinstance(value, (int, float)) else 0


def restore_filter(context):
    """Only restore objects hidden by us, including a filter saved in the blend."""
    for obj in context.view_layer.objects:
        if obj.get(HIDDEN_KEY):
            obj.hide_set(False, view_layer=context.view_layer)
            del obj[HIDDEN_KEY]
    context.view_layer.update()


def _bounds(points):
    if not points:
        return None
    return (tuple(min(p[i] for p in points) for i in range(3)),
            tuple(max(p[i] for p in points) for i in range(3)))


def _union(bounds):
    return _bounds([point for bound in bounds if bound is not None for point in bound])


def _diameter(bound):
    return (Vector(bound[1]) - Vector(bound[0])).length if bound is not None else 0.0


FAR_NODE_MARGIN = 0.05  # metres outside the mesh box before a node position is reported


def _node_positions(obj, scale):
    """World positions (m) of the glTF nodes an object exports: its origin, plus the bone heads of an armature."""
    points = [tuple(obj.matrix_world.translation * scale)]
    if obj.type == 'ARMATURE':
        points += [tuple((obj.matrix_world @ bone.head) * scale) for bone in obj.pose.bones]
    return points


def _far_nodes(positions, mesh_bounds):
    """(object name, metres outside the mesh box) for node positions beyond FAR_NODE_MARGIN, farthest first."""
    if mesh_bounds is None:
        return []
    lo, hi = Vector(mesh_bounds[0]), Vector(mesh_bounds[1])
    far = []
    for name, points in positions.items():
        outside = max(Vector([max(lo[i] - p[i], p[i] - hi[i], 0.0) for i in range(3)]).length for p in points)
        if outside > FAR_NODE_MARGIN:
            far.append((name, outside))
    return sorted(far, key=lambda item: -item[1])


def mesh_pieces(evaluated_obj, mesh, scale):
    """Connected components of an evaluated mesh and their largest world dimensions in metres.

    Pieces that only touch without sharing vertices count as separate. Returns
    (n_comps, comp_per_vertex, piece_sizes) or (0, None, None) for an empty mesh.
    """
    n_verts = len(mesh.vertices)
    if not n_verts or not len(mesh.polygons):
        return 0, None, None
    n_edges = len(mesh.edges)
    if n_edges:
        edges = np.empty(n_edges * 2, dtype=np.int32)
        mesh.edges.foreach_get('vertices', edges)
        u, v = edges[0::2], edges[1::2]
        parent = np.arange(n_verts, dtype=np.int32)
        while True:
            pu, pv = parent[u], parent[v]
            mask = pu != pv
            if not np.any(mask):
                break
            parent[np.maximum(pu[mask], pv[mask])] = np.minimum(pu[mask], pv[mask])
            parent = parent[parent]
        _, comp = np.unique(parent, return_inverse=True)
        n_comps = int(comp.max()) + 1
    else:
        comp = np.arange(n_verts, dtype=np.int32)
        n_comps = n_verts
    if n_comps <= 1:
        return n_comps, comp, None
    co = np.empty(n_verts * 3, dtype=np.float32)
    mesh.vertices.foreach_get('co', co)
    co = co.reshape(-1, 3)
    matrix = np.array(evaluated_obj.matrix_world, dtype=np.float32)
    world = (np.c_[co, np.ones(n_verts, dtype=np.float32)] @ matrix.T)[:, :3] * scale
    mins = np.full((n_comps, 3), np.inf, dtype=np.float32)
    maxs = np.full((n_comps, 3), -np.inf, dtype=np.float32)
    np.minimum.at(mins, comp, world)
    np.maximum.at(maxs, comp, world)
    return n_comps, comp, (maxs - mins).max(axis=1)


def _is_auto_smooth(modifier):
    group = getattr(modifier, 'node_group', None)
    return (modifier.type == 'NODES' and group is not None
            and (group.name == 'Smooth by Angle' or group.name.startswith('Auto Smooth')))


def _estimate_mesh_pieces(evaluated_obj, mesh, scale):
    """Per-piece world sizes and estimated glTF vertex counts for one evaluated mesh.

    Counts unique combinations of material primitive, position, corner normal, UV maps
    (up to 2) and active colour attribute per corner, matching glTF attribute splitting.
    """
    n_verts = len(mesh.vertices)
    n_polys = len(mesh.polygons)
    n_loops = len(mesh.loops)
    if not n_verts or not n_polys or not n_loops:
        return 0, None, None, None
    n_comps, comp, piece_sizes = mesh_pieces(evaluated_obj, mesh, scale)
    co = np.empty(n_verts * 3, dtype=np.float32)
    mesh.vertices.foreach_get('co', co)
    co = co.reshape(-1, 3)

    loop_starts = np.empty(n_polys, dtype=np.int32)
    mesh.polygons.foreach_get('loop_start', loop_starts)
    loop_ends = np.append(loop_starts[1:], n_loops)
    poly_mats = np.empty(n_polys, dtype=np.int32)
    mesh.polygons.foreach_get('material_index', poly_mats)
    n_slots = max(1, len(evaluated_obj.material_slots))
    poly_mats = np.clip(poly_mats, 0, n_slots - 1)
    loop_mats = np.repeat(poly_mats, loop_ends - loop_starts)

    v_idx = np.empty(n_loops, dtype=np.int32)
    mesh.loops.foreach_get('vertex_index', v_idx)
    no = np.empty(n_loops * 3, dtype=np.float32)
    mesh.corner_normals.foreach_get('vector', no)
    no = np.round(no.reshape(-1, 3), 4)

    cols = [loop_mats[:, None].astype(np.float32), co[v_idx], no]
    for uv_layer in list(mesh.uv_layers)[:2]:
        uv = np.empty(n_loops * 2, dtype=np.float32)
        uv_layer.uv.foreach_get('vector', uv)
        cols.append(np.round(uv.reshape(-1, 2), 5))
    color = mesh.color_attributes.active_color
    if color is not None:
        c_vals = np.empty(len(color.data) * 4, dtype=np.float32)
        color.data.foreach_get('color', c_vals)
        c_vals = c_vals.reshape(-1, 4)
        cols.append(np.round(c_vals[v_idx] if color.domain == 'POINT' else c_vals, 4))

    arr = np.ascontiguousarray(np.hstack(cols))
    void_view = arr.view(np.dtype((np.void, arr.dtype.itemsize * arr.shape[1])))
    _, uniq_loop_idx = np.unique(void_view, return_index=True)
    uniq_v_idx = v_idx[uniq_loop_idx]
    piece_gltf_verts = np.bincount(comp[uniq_v_idx], minlength=n_comps)
    piece_blender_verts = np.bincount(comp, minlength=n_comps)
    return n_comps, piece_sizes, piece_gltf_verts, piece_blender_verts


def estimate_scene_stats(context, plan=None):
    """Evaluate meshes once and compute per-LOD vertex estimates, quotas, and artist hints.

    Uses the same `plan` from `build_plan` as the viewport filter and export (decision 15).
    """
    from . import merge
    if plan is None:
        plan = build_plan(context, context.scene.fss_lod_settings.preview_target)
    scene = context.scene
    depsgraph = context.evaluated_depsgraph_get()
    scale = scene.unit_settings.scale_length
    objects_by_name = {obj.name: obj for obj in context.view_layer.objects}
    parts_by_name = {part.name: part for part in plan['parts']}

    merge_settings = getattr(scene, 'fss_merge', None)
    merge_enabled = bool(merge_settings and merge_settings.enabled)
    skip_tags = set(tags.parse_tag_list(merge_settings.skip_tags)) if merge_settings else set()
    groups = (merge.plan(scene, lambda o: o.name in parts_by_name, skip_tags)
              if merge_enabled else [])
    member_to_group = {}
    for group in groups:
        if not group.root_reason:
            for member in group.members:
                member_to_group[member.name] = group.root.name

    mesh_data = {}
    instance_keys = {}
    for part in plan['parts']:
        obj = objects_by_name.get(part.name)
        if obj is None or obj.type != 'MESH':
            continue
        mods = list(obj.modifiers)
        can_instance = (
            obj.name not in member_to_group
            and obj.data is not None
            and obj.data.users > 1
            and obj.data.library is None
            and obj.data.shape_keys is None
            and not obj.data.has_custom_normals
            and (not mods or (len(mods) == 1 and _is_auto_smooth(mods[0]) and mods[0].show_viewport))
        )
        if can_instance:
            instance_keys[obj.name] = (
                obj.data.name,
                tuple(slot.material.name if slot.material else '' for slot in obj.material_slots),
            )
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            if mesh is None:
                continue
            n_comps, piece_sizes, piece_gltf_verts, piece_blender_verts = _estimate_mesh_pieces(
                evaluated, mesh, scale
            )
        finally:
            if mesh is not None:
                evaluated.to_mesh_clear()
        if n_comps > 0:
            can_drop_pieces = (
                n_comps > 1
                and not part.keep
                and (obj.data.shape_keys is None or len(obj.data.shape_keys.key_blocks) <= 1)
                and not any(m.type == 'ARMATURE' for m in obj.modifiers)
            )
            mesh_data[obj.name] = (
                n_comps,
                piece_sizes,
                piece_gltf_verts,
                piece_blender_verts,
                can_drop_pieces,
            )

    # Identify ancestors of Keep objects so near-cutoff hints skip protected parts
    protected_by_level = []
    for level in range(7):
        prot = set()
        for part in plan['parts']:
            if not part.keep:
                continue
            blocked = (part.hide_from and level >= part.hide_from) or level < part.show_from
            for _, hide, show in part.outside_ancestors:
                blocked = blocked or (hide and level >= hide) or level < show
            parent = parts_by_name.get(part.parent)
            ancestors = {part.name}
            while parent is not None and parent.name not in ancestors:
                ancestors.add(parent.name)
                blocked = blocked or (parent.hide_from and level >= parent.hide_from) or level < parent.show_from
                parent = parts_by_name.get(parent.parent)
            if not blocked:
                prot.update(ancestors)
        protected_by_level.append(prot)

    lod_stats = []
    for level in range(7):
        decision = plan['decisions'][level]
        cutoff = decision.cutoff
        intended = plan['table'][level]
        quota = lod_rules.max_vertex_count(intended)
        forced = plan['model_type'] == 'INTERIOR' and level == 0

        seen_instances = set()
        total_vertices = 0
        total_dropped_pieces = 0
        total_dropped_vertices = 0
        contributor_verts = {}
        obj_kept_verts = {}
        loose_hints = []

        for name in decision.present:
            if name not in mesh_data:
                continue
            n_comps, piece_sizes, piece_gltf_verts, _piece_blender_verts, can_drop = mesh_data[name]
            if level > 0 and can_drop and piece_sizes is not None:
                small = piece_sizes < cutoff
                n_small = int(small.sum())
                dropped_v = int(piece_gltf_verts[small].sum())
                kept_v = int(piece_gltf_verts[~small].sum())
            else:
                n_small = 0
                dropped_v = 0
                kept_v = int(piece_gltf_verts.sum())

            if n_small:
                total_dropped_pieces += n_small
                total_dropped_vertices += dropped_v
                loose_hints.append((name, n_small, dropped_v, cutoff))

            # Shared instanced meshes without piece dropping count once in stored glTF accessors
            counted_v = kept_v
            if not n_small and name in instance_keys:
                ikey = instance_keys[name]
                if ikey in seen_instances:
                    counted_v = 0
                else:
                    seen_instances.add(ikey)

            total_vertices += counted_v
            obj_kept_verts[name] = kept_v
            owner = member_to_group.get(name, name)
            contributor_verts[owner] = contributor_verts.get(owner, 0) + counted_v

        # Subtree kept vertices for near-cutoff Auto candidates
        subtree_verts = {}

        def get_subtree_verts(name):
            if name not in subtree_verts:
                part = parts_by_name[name]
                total = obj_kept_verts.get(name, 0)
                for child in objects_by_name[name].children:
                    if child.name in decision.present and child.name in parts_by_name:
                        total += get_subtree_verts(child.name)
                subtree_verts[name] = total
            return subtree_verts[name]

        near_hints = []
        if level > 0 and cutoff > 0 and cutoff < float('inf'):
            protected = protected_by_level[level]
            next_cutoff = (
                plan['decisions'][level + 1].cutoff
                if level + 1 < 7 and plan['decisions'][level + 1].cutoff < float('inf')
                else cutoff * 3.0
            )
            upper_bound = max(cutoff * 2.5, next_cutoff)
            candidates = {}
            for name in decision.present:
                part = parts_by_name[name]
                if part.hide_from or part.show_from or part.keep or name in protected:
                    continue
                if cutoff <= part.size <= upper_bound:
                    sv = get_subtree_verts(name)
                    if sv > 0:
                        candidates[name] = (part.size, sv)
            for name, (psize, sv) in candidates.items():
                parent_name = parts_by_name[name].parent
                if parent_name in candidates and candidates[parent_name][1] == sv:
                    continue
                near_hints.append((name, psize, sv))

        contributors = [
            (owner, v, owner.startswith(merge.PREFIX))
            for owner, v in sorted(contributor_verts.items(), key=lambda item: -item[1])
            if v > 0
        ][:10]
        loose_hints.sort(key=lambda item: (-item[2], -item[1]))
        near_hints.sort(key=lambda item: (-item[2], item[1]))

        required = (lod_rules.lowest_screen_size_from_vcount(total_vertices)
                    if plan['target'] == 'fs24' else 0.0)
        over = (plan['target'] == 'fs24' and not forced and total_vertices > quota)
        lod_stats.append({
            'level': level,
            'vertices': total_vertices,
            'quota': quota,
            'percent': (100.0 * total_vertices / quota) if quota > 0 else 0.0,
            'over': over,
            'forced': forced,
            'required_min_size': required,
            'dropped_pieces': total_dropped_pieces,
            'dropped_vertices': total_dropped_vertices,
            'contributors': contributors,
            'loose_pieces': loose_hints[:10],
            'near_cutoff': near_hints[:10],
        })

    return {'plan': plan, 'lods': lod_stats}


def build_plan(context, target='fs24', reference=None):
    """Capture the unfiltered visible source set, before exporter duplication/merge.

The AABB diagonal is the diameter of a conservative enclosing sphere. Bounds use
evaluated geometry in metres, and a part includes all of its exported descendants.
"""
    restore_filter(context)
    scene = context.scene
    settings = scene.fss_lod_settings
    objects = [obj for obj in context.view_layer.objects if obj.visible_get(view_layer=context.view_layer)]
    exported = set(objects)
    depsgraph = context.evaluated_depsgraph_get()
    scale = scene.unit_settings.scale_length
    own_bounds = {}
    for obj in objects:
        evaluated = obj.evaluated_get(depsgraph)
        points = []
        if evaluated.type == 'MESH':
            # The exported mesh, not bound_box: Geometry Nodes output that to_mesh() drops (instances, curves) still
            # widens bound_box, up to 1 m on E2 cockpit parts, which made the diameter 6 % too large
            mesh = evaluated.to_mesh()
            try:
                if mesh is not None and len(mesh.vertices):
                    co = np.empty(len(mesh.vertices) * 3)
                    mesh.vertices.foreach_get('co', co)
                    world = np.array(evaluated.matrix_world)
                    co = (co.reshape(-1, 3) @ world[:3, :3].T + world[:3, 3]) * scale
                    points = [tuple(co.min(0)), tuple(co.max(0))]
            finally:
                evaluated.to_mesh_clear()
        elif evaluated.type in {'CURVE', 'SURFACE', 'FONT', 'META', 'VOLUME'}:
            points = [tuple((evaluated.matrix_world @ Vector(corner)) * scale)
                      for corner in evaluated.bound_box]
        own_bounds[obj] = _bounds(points)
    subtree = {}

    def bounds(obj):
        if obj not in subtree:
            subtree[obj] = _union([own_bounds[obj]] + [bounds(child) for child in obj.children if child in exported])
        return subtree[obj]

    keep_tags = set(tags.parse_tag_list(settings.keep_tags))
    parts = []
    for obj in objects:
        bound = bounds(obj)
        size = max(b - a for a, b in zip(*bound)) if bound is not None else 0.0
        # A hidden parent empty can still have visible children. Its explicit
        # marks constrain those children even when it is outside the source set.
        outside = []
        ancestor = obj.parent
        disconnected = False
        while ancestor is not None:
            disconnected = disconnected or ancestor not in exported
            if disconnected:
                outside.append((ancestor.name, mark(ancestor, HIDE_KEY), mark(ancestor, SHOW_KEY)))
            ancestor = ancestor.parent
        parts.append(lod_rules.Part(obj.name, obj.parent.name if obj.parent in exported else None, size,
                                   mark(obj, HIDE_KEY), mark(obj, SHOW_KEY),
                                   bool(obj.get(KEEP_KEY)) or bool(keep_tags.intersection(tags.get_tags(obj))),
                                   tuple(outside)))
    initial = lod_rules.decide(parts, 0, 0, lod_rules.DEFAULT_MIN_SIZES)
    lod0_bounds = _union([own_bounds[obj] for obj in objects if obj.name in initial.present])
    # MSFS's LOD sphere also encloses every node position (measured, journal Session 17): one far origin moves
    # the sphere centre and enlarges it for every LOD
    positions = {obj.name: _node_positions(obj, scale) for obj in objects if obj.name in initial.present}
    sphere_bounds = _union([lod0_bounds] + [_bounds(points) for points in positions.values()])
    own_diameter = _diameter(sphere_bounds)
    diameter = reference if reference is not None else (settings.reference_size or own_diameter)
    table = lod_rules.min_sizes(settings.model_type,
                               (settings.explicit_fs20 or settings.explicit_fs24) if target == 'fs20'
                               else settings.explicit_fs24,
                               settings.min_sizes_fs20 if target == 'fs20' else settings.min_sizes_fs24,
                               own_diameter, settings.exterior_diameter, target)
    decisions = [lod_rules.decide(parts, level, diameter, table,
                                screen_height=settings.screen_height, threshold=settings.pixel_threshold,
                                model_type=settings.model_type) for level in range(7)]
    return {'parts': parts, 'decisions': decisions, 'diameter': diameter, 'own_diameter': own_diameter,
            'table': table, 'target': target, 'model_type': settings.model_type,
            'bounds': sphere_bounds, 'mesh_diameter': _diameter(lod0_bounds),
            'far_nodes': _far_nodes(positions, lod0_bounds), 'write_count': lod_rules.written_lod_count(decisions)}


def begin_export(context, plan, level):
    """Called by the seven-file driver immediately before one exporter invocation."""
    global _export_plan, _export_level, _merged_meshes, _culled_pieces
    _export_plan, _export_level, _merged_meshes, _culled_pieces = plan, level, 0, 0
    context.scene.fss_lod_export_level = level
    restore_filter(context)
    # Hide the parts absent from this LOD in the source scene, so the exporter never duplicates, selects or walks
    # them (LOD06 of the E2 cockpit keeps about 400 of 3,099 objects). cull_export still decides on the export
    # copies; the driver reloads the source .blend before every LOD, so nothing is restored.
    decision = plan['decisions'][level]
    absent = {part.name for part in plan['parts']} - decision.present
    if absent:
        view_layer = context.view_layer
        for obj in view_layer.objects:
            if obj.name in absent:
                obj.hide_set(True, view_layer=view_layer)
        view_layer.update()


def end_export(context):
    global _export_plan, _export_level
    _export_plan = _export_level = None
    context.scene.fss_lod_export_level = -1


def drop_small_pieces(context, objects, parts_by_name, cutoff):
    """Remove faces of disconnected pieces below cutoff on throwaway export meshes (decision 18).

    Keep on an object protects all its pieces. Returns the number of dropped pieces.
    Objects without modifiers that share a mesh are exported as instances of one glTF mesh; when their trimmed
    results are identical (same mesh, same dropped pieces, same materials) they share one trimmed mesh, so the
    instancing survives.
    """
    if cutoff <= 0:
        return 0
    depsgraph = context.evaluated_depsgraph_get()
    scale = context.scene.unit_settings.scale_length
    dropped = 0
    trimmed = {}
    for obj in objects:
        if obj.type != 'MESH':
            continue
        name = obj.get('msfs_original_name', obj.name)
        part = parts_by_name.get(name)
        if part is None or part.keep:
            continue
        if obj.data.shape_keys is not None and len(obj.data.shape_keys.key_blocks) > 1:
            continue
        if any(m.type == 'ARMATURE' for m in obj.modifiers):
            continue
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            if mesh is None:
                continue
            n_comps, comp, sizes = mesh_pieces(evaluated, mesh, scale)
        finally:
            if mesh is not None:
                evaluated.to_mesh_clear()
        if n_comps <= 1 or sizes is None:
            continue
        small = sizes < cutoff
        if not np.any(small):
            continue
        dropped += int(small.sum())
        slots = [slot.material.original if slot.material else None for slot in evaluated.material_slots]
        key = None
        if not obj.modifiers:
            key = (obj.data.as_pointer(), small.tobytes(), tuple(m.as_pointer() if m else 0 for m in slots))
            if key in trimmed:
                obj.data = trimmed[key]
                continue
        new_mesh = bpy.data.meshes.new_from_object(evaluated)
        new_mesh.materials.clear()
        for material in slots:
            new_mesh.materials.append(material)
        if np.all(small):
            new_mesh.clear_geometry()
        else:
            bm = bmesh.new()
            bm.from_mesh(new_mesh)
            bm.verts.ensure_lookup_table()
            small_verts = np.nonzero(small[comp])[0]
            bmesh.ops.delete(bm, geom=[bm.verts[i] for i in small_verts], context='VERTS')
            bm.to_mesh(new_mesh)
            bm.free()
        obj.modifiers.clear()
        obj.data = new_mesh
        if key is not None:
            trimmed[key] = new_mesh
    return dropped


def cull_export(context, exported, log):
    """Hide/deselect absent throwaway objects and drop small loose pieces before the merge sees its input."""
    global _culled_pieces
    if _export_plan is None:
        return
    decision = _export_plan['decisions'][_export_level]
    candidates = [obj for obj in context.scene.objects if exported(obj)]
    if not bpy.app.background and any('msfs_original_name' not in obj for obj in candidates):
        raise RuntimeError('LOD export requires throwaway copies or background Blender')
    kept = []
    for obj in candidates:
        name = obj.get('msfs_original_name', obj.name)
        if name not in decision.present:
            obj.select_set(False)
            obj.hide_set(True)
        else:
            kept.append(obj)
    for warning in decision.warnings:
        log(warning, warning=True)
    context.view_layer.update()
    if _export_level > 0:
        parts_by_name = {part.name: part for part in _export_plan['parts']}
        _culled_pieces = drop_small_pieces(context, kept, parts_by_name, decision.cutoff)
        if _culled_pieces:
            context.view_layer.update()


def record_merge(created):
    global _merged_meshes
    _merged_meshes = sum(obj.type == 'MESH' for obj in created)


def report_file(path, plan, level):
    """Read exact stored POSITION counts, reporting without influencing membership."""
    with open(path, encoding='utf-8') as stream:
        document = json.load(stream)
    count = lod_rules.gltf_vertex_count(document)
    decision = plan['decisions'][level]
    intended = plan['table'][level]
    required = lod_rules.lowest_screen_size_from_vcount(count) if plan['target'] == 'fs24' else 0.0
    effective = max(intended, required)
    quota = lod_rules.max_vertex_count(intended)
    upper = plan['table'][level - 1] if level else float('inf')
    forced = plan['model_type'] == 'INTERIOR' and level == 0
    line = (f'[FSS LOD] _LOD{level:02}: {len(plan["parts"])} objects in, '
            f'{len(decision.by_mark)} culled by mark, {len(decision.by_size)} culled by size, '
            f'{_culled_pieces} culled by size (pieces), '
            f'{_merged_meshes} merged meshes; {count:,} vertices (exact stored POSITION accessors, '
            f'instances counted once); intended {intended:.2%}..{upper:.2%}; '
            f'effective minSize {effective:.2%}')
    if plan['target'] == 'fs24':
        line += f'; High quota {count:,}/{quota:,} ({100 * count / quota:.1f}%)'
    if forced:
        line += '; interior LOD0 forced from the seat'
    elif required > intended:
        line += f'; WARNING High vertex limit: skipped between {intended:.2%} and {required:.2%}'
    if plan['target'] == 'fs20':
        line += '; FS20 table unverified; vertex correction disabled'
    line += '; MSFS seam/instance counting unverified'
    print(line, flush=True)
    print(line, file=sys.stderr, flush=True)
    return count


def report_end(plan):
    """Report the first omitted file and any later visibility island."""
    first_empty = plan['write_count']
    if first_empty == 7:
        return
    lines = [f'[FSS LOD] _LOD{first_empty:02}: not written, no objects']
    later = [f'_LOD{level:02}' for level in range(first_empty + 1, 7)
             if plan['decisions'][level].present]
    if later:
        lines.append('[FSS LOD] WARNING later LODs would have objects through visible-from marks: '
                     + ', '.join(later) + '; not written after the first empty LOD')
    for line in lines:
        print(line, flush=True)
        print(line, file=sys.stderr, flush=True)
