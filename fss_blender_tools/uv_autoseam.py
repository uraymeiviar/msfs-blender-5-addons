"""
Automatic seam proposal tool for hard-surface meshes.

Constructs a temporary triangulated world-space work copy of the object mesh
(before modifiers), maps edges by vertex pair, runs propose_seams, and reports
the proposal mapped to original edges along with diagonal cut counts.
Leaves the source object and mesh completely unmodified.
"""
import math
import numpy as np
import bpy
import bmesh

try:
    from .uv_autoseam_core import propose_seams
except ImportError:
    from uv_autoseam_core import propose_seams


def get_shading_splits(obj):
    """Return per original edge whether shading splits there.

    Evaluates the object with Mirror and Array modifiers temporarily hidden (show_viewport)
    and compares corner normals across each edge as prep3.py does.
    When the evaluated edge count differs from the original's, uses the mesh's own
    sharp_edge attribute instead and reports fallback.

    Returns:
        (nsplit, used_fallback):
            nsplit: boolean NumPy array of length len(obj.data.edges).
            used_fallback: True if topology differed and sharp_edge attribute was used.
    """
    orig_me = obj.data
    ne = len(orig_me.edges)

    mirror_array_mods = [m for m in obj.modifiers if m.type in ('MIRROR', 'ARRAY')]
    orig_show = [m.show_viewport for m in mirror_array_mods]

    me_eval = None
    try:
        for m in mirror_array_mods:
            m.show_viewport = False

        bpy.context.view_layer.update()
        deps = bpy.context.evaluated_depsgraph_get()
        ev = obj.evaluated_get(deps)
        me_eval = bpy.data.meshes.new_from_object(ev, preserve_all_data_layers=True, depsgraph=deps)
        me_eval.transform(obj.matrix_world)

        if len(me_eval.edges) != ne:
            # Topology differs: use mesh's own sharp_edge attribute
            sh = np.zeros(ne, bool)
            if 'sharp_edge' in orig_me.attributes:
                orig_me.attributes['sharp_edge'].data.foreach_get('value', sh)
            else:
                orig_me.edges.foreach_get('use_edge_sharp', sh)
            return sh, True

        # Topology matches: compare corner normals across each edge
        nl = len(me_eval.loops)
        eval_ne = len(me_eval.edges)
        CN = np.zeros(nl * 3, np.float64)
        me_eval.corner_normals.foreach_get('vector', CN)
        CN = CN.reshape(-1, 3)

        lv = np.zeros(nl, np.int64)
        me_eval.loops.foreach_get('vertex_index', lv)
        le = np.zeros(nl, np.int64)
        me_eval.loops.foreach_get('edge_index', le)
        ls = np.zeros(len(me_eval.polygons), np.int64)
        me_eval.polygons.foreach_get('loop_start', ls)
        lt = np.zeros(len(me_eval.polygons), np.int64)
        me_eval.polygons.foreach_get('loop_total', lt)

        nx = np.arange(nl) + 1
        last = ls + lt - 1
        nx[last] = ls

        order = np.argsort(le, kind='stable')
        cnt = np.bincount(le, minlength=eval_ne)
        starts = np.concatenate([[0], np.cumsum(cnt)[:-1]])

        nsplit = np.zeros(eval_ne, bool)
        two = np.flatnonzero(cnt == 2)
        if len(two) > 0:
            l1 = order[starts[two]]
            l2 = order[starts[two] + 1]
            m1 = np.where(lv[l2] == lv[l1], l2, nx[l2])
            m2 = np.where(lv[l2] == lv[l1], nx[l2], l2)
            d1 = np.einsum('ij,ij->i', CN[l1], CN[m1])
            d2 = np.einsum('ij,ij->i', CN[nx[l1]], CN[m2])
            TOL = math.cos(math.radians(1.0))
            nsplit[two] = (d1 < TOL) | (d2 < TOL)
        nsplit[cnt > 2] = True

        return nsplit, False

    finally:
        if me_eval is not None:
            bpy.data.meshes.remove(me_eval, do_unlink=True)
        for m, s in zip(mirror_array_mods, orig_show):
            m.show_viewport = s
        bpy.context.view_layer.update()


def propose(obj, cache=None, measurement_arrays=False, use_temp_scene=True, **kwargs):
    """Propose automatic UV seams on obj without modifying the object or mesh.

    Parameters:
        obj: bpy.types.Object of type 'MESH'.
        cache: optional dict mapping mesh datablock to (proposal, diagonal_cuts, report).
               If provided and obj.data has already been processed, returns the cached result.
        measurement_arrays: bool (default False). When True, includes P, T, UV, NT, SE
                            and work seam/nsplit arrays in report for benchmark runner.
        use_temp_scene: bool (default True). When True, runs propose_seams inside an isolated
                        temporary scene containing only the work object for speed.

    Returns:
        (proposed_orig_edges, diagonal_cuts, report):
            proposed_orig_edges: list of edge indices on obj.data.edges proposed as seams.
            diagonal_cuts: count of proposed seam cuts on internal triangulation diagonals
                           (which cannot be written to original quad/ngon edges; 0 with no_cut).
            report: dictionary containing modifier info, topology check, face counts,
                    diagonal counts, shading splits method/count, warnings, and core stats.
    """
    if kwargs.get('return_measurement_arrays', False):
        measurement_arrays = True
    if obj is None or obj.type != 'MESH':
        raise ValueError(f"Object '{obj}' is not a valid mesh object")
    orig_me = obj.data
    if len(orig_me.polygons) == 0:
        raise ValueError(f"Object '{obj.name}' has no faces")

    # Check shared mesh cache
    if cache is not None and orig_me in cache:
        cached_prop, cached_diag, cached_rep = cache[orig_me]
        rep = dict(cached_rep)
        rep['object'] = obj.name
        rep['cached_from_mesh'] = orig_me.name
        return cached_prop, cached_diag, rep

    # Shared mesh and scale check across scene users
    warnings = []
    users = [o for o in bpy.data.objects if o.type == 'MESH' and o.data == orig_me]
    if len(users) > 1:
        scales = [o.matrix_world.to_scale() for o in users]
        has_non_uniform = any(
            not (math.isclose(s.x, s.y, rel_tol=1e-3) and math.isclose(s.y, s.z, rel_tol=1e-3))
            for s in scales
        )
        scales_differ = any(
            not (math.isclose(scales[0].x, s.x, rel_tol=1e-3) and
                 math.isclose(scales[0].y, s.y, rel_tol=1e-3) and
                 math.isclose(scales[0].z, s.z, rel_tol=1e-3))
            for s in scales[1:]
        )
        if has_non_uniform or scales_differ:
            warnings.append(
                f"Shared mesh '{orig_me.name}' is used by {len(users)} objects with differing or non-uniform scales."
            )

    # Shading splits for report
    nsplit, used_fallback = get_shading_splits(obj)
    if used_fallback:
        warnings.append("Evaluated topology differs from original mesh; used sharp_edge attribute for shading splits.")

    orig_mode = bpy.context.object.mode if bpy.context.object else 'OBJECT'
    orig_active = bpy.context.view_layer.objects.active
    orig_selection = {o.name: o.select_get() for o in bpy.context.scene.objects if o.name in bpy.context.view_layer.objects}

    work_me = None
    work_obj = None
    temp_scene = None
    orig_scene = None

    try:
        # Build temporary work mesh before all modifiers, transformed to world space
        work_me = orig_me.copy()
        work_me.name = f"__fss_autoseam_work_{orig_me.name}__"
        work_me.transform(obj.matrix_world)

        # Triangulate with bmesh, tracking original polygon per triangle
        bm = bmesh.new()
        bm.from_mesh(work_me)
        faces_before = len(bm.faces)
        poly_layer = bm.faces.layers.int.new("__orig_poly__")
        for f in bm.faces:
            f[poly_layer] = f.index
        bmesh.ops.triangulate(bm, faces=bm.faces[:])
        faces_after = len(bm.faces)
        tri_to_orig_poly = np.array([f[poly_layer] for f in bm.faces], dtype=np.int64)
        bm.to_mesh(work_me)
        bm.free()

        # Build edge mapping by vertex pair (triangulation adds no vertices)
        orig_edge_map = {}
        for e in orig_me.edges:
            k = (min(e.vertices[0], e.vertices[1]), max(e.vertices[0], e.vertices[1]))
            orig_edge_map[k] = e.index

        work_to_orig = [None] * len(work_me.edges)
        work_artist_seam = np.zeros(len(work_me.edges), bool)
        work_nsplit = np.zeros(len(work_me.edges), bool)
        work_no_cut = np.zeros(len(work_me.edges), bool)

        orig_seams = np.zeros(len(orig_me.edges), bool)
        orig_me.edges.foreach_get('use_seam', orig_seams)

        total_diagonals = 0
        for we in work_me.edges:
            k = (min(we.vertices[0], we.vertices[1]), max(we.vertices[0], we.vertices[1]))
            oe_idx = orig_edge_map.get(k)
            work_to_orig[we.index] = oe_idx
            if oe_idx is not None:
                work_artist_seam[we.index] = orig_seams[oe_idx]
                work_nsplit[we.index] = nsplit[oe_idx]
            else:
                total_diagonals += 1
                work_no_cut[we.index] = True

        # Create temporary work object
        work_obj = bpy.data.objects.new(f"__fss_autoseam_work_{obj.name}__", work_me)
        if use_temp_scene:
            orig_scene = bpy.context.scene
            temp_scene = bpy.data.scenes.new(f"__fss_autoseam_temp_scene_{obj.name}__")
            temp_scene.collection.objects.link(work_obj)
            bpy.context.window.scene = temp_scene
            temp_scene.view_layers[0].objects.active = work_obj
            work_obj.select_set(True)
        else:
            bpy.context.scene.collection.objects.link(work_obj)
            bpy.context.view_layer.objects.active = work_obj
            work_obj.select_set(True)

        # Run core propose_seams passing diagonals as no_cut
        auto_edges, stats = propose_seams(work_obj, work_artist_seam, work_nsplit, no_cut=work_no_cut)

        # Map proposed cuts back to original edges; count cuts on diagonals
        proposed_orig_edges = []
        diagonal_cuts = 0
        for we_idx in auto_edges:
            oe_idx = work_to_orig[we_idx]
            if oe_idx is not None:
                proposed_orig_edges.append(oe_idx)
            else:
                diagonal_cuts += 1
        proposed_orig_edges.sort()

        # Map core charts to original polygon sets via seam-partitioned components
        auto_set = set(auto_edges)
        par = list(range(len(work_me.polygons)))

        def find(i):
            while par[i] != i:
                par[i] = par[par[i]]
                i = par[i]
            return i

        e_faces = [[] for _ in work_me.edges]
        for f in work_me.polygons:
            for li in f.loop_indices:
                e_faces[work_me.loops[li].edge_index].append(f.index)

        for e_idx, ef in enumerate(e_faces):
            if len(ef) == 2 and not work_artist_seam[e_idx] and (e_idx not in auto_set):
                f0, f1 = ef
                if work_me.polygons[f0].material_index == work_me.polygons[f1].material_index:
                    r0, r1 = find(f0), find(f1)
                    if r0 != r1:
                        par[r0] = r1

        groups = {}
        for i in range(len(work_me.polygons)):
            groups.setdefault(find(i), set()).add(int(tri_to_orig_poly[i]))

        core_chart_polys = [frozenset(s) for s in groups.values()]

        report = {
            'object': obj.name,
            'mesh': orig_me.name,
            'modifiers': [m.type for m in obj.modifiers],
            'eval_topology_matches': not used_fallback,
            'faces_before': faces_before,
            'faces_after': faces_after,
            'edges_orig': len(orig_me.edges),
            'edges_work': len(work_me.edges),
            'diagonals_total': total_diagonals,
            'proposed_edges_count': len(proposed_orig_edges),
            'diagonal_cuts_count': diagonal_cuts,
            'shading_splits_method': 'sharp_edge_fallback' if used_fallback else 'corner_normals',
            'shading_splits_count': int(np.sum(nsplit)),
            'warnings': warnings,
            'time': stats.get('time', 0.0),
            'stats': stats,
            'core_chart_polys': core_chart_polys,
            'tri_to_orig_poly': tri_to_orig_poly,
        }

        if measurement_arrays:
            # Extract geometry and split topology for benchmark evaluation
            P = np.zeros(len(work_me.vertices) * 3, np.float64)
            work_me.vertices.foreach_get('co', P)
            P = P.reshape(-1, 3)

            T = np.zeros(len(work_me.polygons) * 3, np.int64)
            work_me.polygons.foreach_get('vertices', T)
            T = T.reshape(-1, 3)

            UV = stats['uv'].reshape(-1, 3, 2)

            bm_split = bmesh.new()
            bm_split.from_mesh(work_me)
            bm_split.edges.ensure_lookup_table()
            SE = np.array([[e.verts[0].index, e.verts[1].index] for e in bm_split.edges if work_artist_seam[e.index]], dtype=np.int64).reshape(-1, 2)
            bmesh.ops.split_edges(bm_split, edges=[e for e in bm_split.edges if work_nsplit[e.index] and len(e.link_faces) == 2])
            bm_split.verts.index_update()
            bm_split.faces.ensure_lookup_table()
            NT = np.array([[v.index for v in f.verts] for f in bm_split.faces], dtype=np.int64)
            bm_split.free()

            report.update({
                'P': P,
                'T': T,
                'UV': UV,
                'NT': NT,
                'SE': SE,
                'work_artist_seam': work_artist_seam,
                'work_nsplit': work_nsplit,
            })

        result = (proposed_orig_edges, diagonal_cuts, report)
        if cache is not None:
            cache[orig_me] = result
        return result

    finally:
        # Guarantee removal of temporary work object, work mesh, and temporary scene
        if use_temp_scene and temp_scene is not None:
            if orig_scene is not None and orig_scene.name in bpy.data.scenes:
                bpy.context.window.scene = orig_scene
            if work_obj is not None and work_obj.name in temp_scene.collection.objects:
                temp_scene.collection.objects.unlink(work_obj)
            if temp_scene.name in bpy.data.scenes:
                bpy.data.scenes.remove(temp_scene)
        elif work_obj is not None:
            if work_obj.name in bpy.context.scene.collection.objects:
                bpy.context.scene.collection.objects.unlink(work_obj)
        if work_obj is not None and work_obj.name in bpy.data.objects:
            bpy.data.objects.remove(work_obj, do_unlink=True)
        if work_me is not None and work_me.name in bpy.data.meshes:
            bpy.data.meshes.remove(work_me, do_unlink=True)

        # Restore original selection, active object, and mode
        for o_name, sel in orig_selection.items():
            o = bpy.context.scene.objects.get(o_name)
            if o:
                o.select_set(sel)
        if orig_active and orig_active.name in bpy.context.view_layer.objects:
            bpy.context.view_layer.objects.active = orig_active
        if bpy.context.object and bpy.context.object.mode != orig_mode:
            bpy.ops.object.mode_set(mode=orig_mode)
