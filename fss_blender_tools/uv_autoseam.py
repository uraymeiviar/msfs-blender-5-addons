"""
Automatic seam proposal tool for hard-surface meshes.

Constructs a temporary triangulated world-space work copy of the object mesh
(before modifiers), maps edges by vertex pair, runs propose_seams, and reports
the proposal mapped to original edges along with diagonal cut counts.
Leaves the source object and mesh completely unmodified.

Provides operators to propose seams (modal and synchronous), clear auto seams,
keep them as artist seams, and select auto or artist seams in Edit Mode.
"""
import math
import time
import numpy as np
import bpy
import bmesh

try:
    from .uv_autoseam_core import propose_seams
except ImportError:
    from uv_autoseam_core import propose_seams

try:
    from .tags import _editable
except ImportError:
    def _editable(obj):
        return obj.library is None and obj.override_library is None


AUTO_SEAM_ATTR = 'fss_auto_seam'
REPORT_TEXT_NAME = 'FSS Auto Seam Report'


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


def get_mesh_seam_masks(mesh):
    """Return (artist_seams_mask, auto_seams_mask) boolean arrays for mesh edges.

    Artist seams = use_seam edges not marked fss_auto_seam.
    Auto seams = use_seam edges marked fss_auto_seam.
    """
    ne = len(mesh.edges)
    seams = np.zeros(ne, bool)
    if ne == 0:
        return seams, seams.copy()
    mesh.edges.foreach_get('use_seam', seams)
    auto = np.zeros(ne, bool)
    attr = mesh.attributes.get(AUTO_SEAM_ATTR)
    if attr is not None and attr.domain == 'EDGE' and attr.data_type == 'BOOLEAN':
        attr.data.foreach_get('value', auto)
    artist = seams & (~auto)
    auto = seams & auto
    return artist, auto


def get_mesh_seam_counts(mesh):
    """Return (auto_seam_count, artist_seam_count) for mesh."""
    if bpy.context.mode == 'EDIT_MESH' and bpy.context.edit_object and bpy.context.edit_object.data == mesh:
        bm = bmesh.from_edit_mesh(mesh)
        layer = bm.edges.layers.bool.get(AUTO_SEAM_ATTR)
        auto_cnt = 0
        artist_cnt = 0
        for e in bm.edges:
            if e.seam:
                if layer is not None and e[layer]:
                    auto_cnt += 1
                else:
                    artist_cnt += 1
        return auto_cnt, artist_cnt

    artist, auto = get_mesh_seam_masks(mesh)
    return int(np.count_nonzero(auto)), int(np.count_nonzero(artist))


def write_proposal(mesh, proposed_orig_edges):
    """Write proposed seam edges onto mesh.

    Per mesh datablock:
    1. Removes previous automatic seams (edges marked fss_auto_seam: clears use_seam and the mark).
    2. Sets use_seam and fss_auto_seam boolean edge attribute on the proposal.
    Artist seams are never changed.
    """
    ne = len(mesh.edges)
    if ne == 0:
        return

    cur_seams = np.zeros(ne, bool)
    mesh.edges.foreach_get('use_seam', cur_seams)

    old_auto = np.zeros(ne, bool)
    attr = mesh.attributes.get(AUTO_SEAM_ATTR)
    if attr is not None:
        if attr.domain == 'EDGE' and attr.data_type == 'BOOLEAN':
            attr.data.foreach_get('value', old_auto)
        else:
            mesh.attributes.remove(attr)
            attr = None

    artist_seams = cur_seams & (~old_auto)

    new_auto = np.zeros(ne, bool)
    if proposed_orig_edges:
        valid_edges = [e for e in proposed_orig_edges if 0 <= e < ne]
        new_auto[valid_edges] = True

    final_seams = artist_seams | new_auto
    mesh.edges.foreach_set('use_seam', final_seams)

    if attr is None:
        attr = mesh.attributes.new(name=AUTO_SEAM_ATTR, type='BOOLEAN', domain='EDGE')
    attr.data.foreach_set('value', new_auto)
    mesh.update()


def clear_auto_seams(mesh):
    """Remove automatic seams from mesh.

    Clears use_seam on edges marked fss_auto_seam and removes the fss_auto_seam attribute.
    Artist seams are never changed.
    """
    attr = mesh.attributes.get(AUTO_SEAM_ATTR)
    if attr is None:
        return 0
    ne = len(mesh.edges)
    if ne == 0:
        mesh.attributes.remove(attr)
        return 0

    old_auto = np.zeros(ne, bool)
    if attr.domain == 'EDGE' and attr.data_type == 'BOOLEAN':
        attr.data.foreach_get('value', old_auto)

    cur_seams = np.zeros(ne, bool)
    mesh.edges.foreach_get('use_seam', cur_seams)

    cleared_count = int(np.count_nonzero(old_auto & cur_seams))
    final_seams = cur_seams & (~old_auto)
    mesh.edges.foreach_set('use_seam', final_seams)

    mesh.attributes.remove(attr)
    mesh.update()
    return cleared_count


def keep_as_artist_seams(mesh):
    """Convert automatic seams to artist seams by removing the fss_auto_seam attribute.

    Seams remain set on use_seam and are treated as artist seams from then on.
    """
    attr = mesh.attributes.get(AUTO_SEAM_ATTR)
    if attr is None:
        return 0
    ne = len(mesh.edges)
    old_auto = np.zeros(ne, bool)
    if ne > 0 and attr.domain == 'EDGE' and attr.data_type == 'BOOLEAN':
        attr.data.foreach_get('value', old_auto)
    count = int(np.count_nonzero(old_auto))
    mesh.attributes.remove(attr)
    mesh.update()
    return count


def write_report_text(mesh_reports, run_time):
    """Write or overwrite the text datablock 'FSS Auto Seam Report'.

    One line per mesh:
    objects using it, islands, extra vertices beyond shading splits, time,
    unverified charts with face count and criterion, islands over the limits,
    sliver overlaps, warnings (shared mesh scale, shading-split fallback).
    Nothing is stored in object or mesh custom properties.
    """
    txt = bpy.data.texts.get(REPORT_TEXT_NAME)
    if txt is None:
        txt = bpy.data.texts.new(REPORT_TEXT_NAME)
    else:
        txt.clear()

    lines = []
    lines.append(f"# FSS Auto Seam Report - {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"# Total meshes processed: {len(mesh_reports)} in {run_time:.2f}s\n")

    for r in mesh_reports:
        objs_str = ", ".join(r['objects'])
        mesh_name = r['mesh']
        islands = r['islands']
        extra_verts = r.get('extra_vertices_vs_shading', 0)
        t_core = r.get('time', 0.0)
        unv_charts = r.get('unverified_charts', [])
        if unv_charts:
            unv_str = "; ".join(f"Chart {u['chart']} ({u['faces']} faces, d={u['distortion']:.2f}, {u['criterion']})" for u in unv_charts)
        else:
            unv_str = "none"
        over_limits = len(unv_charts)
        sliver_overlaps = r.get('sliver_overlaps', 0)
        warns = r.get('warnings', [])
        warns_str = "; ".join(warns) if warns else "none"

        line = (
            f"Mesh '{mesh_name}' (objects: {objs_str}): "
            f"islands={islands}, extra_verts={extra_verts}, time={t_core:.2f}s, "
            f"unverified={unv_str}, over_limits={over_limits}, "
            f"sliver_overlaps={sliver_overlaps}, warnings={warns_str}"
        )
        lines.append(line)

    txt.write("\n".join(lines) + "\n")


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

        # Artist seams: use_seam edges not marked fss_auto_seam (decision 42 / Package 3)
        orig_artist_seams, _ = get_mesh_seam_masks(orig_me)

        total_diagonals = 0
        for we in work_me.edges:
            k = (min(we.vertices[0], we.vertices[1]), max(we.vertices[0], we.vertices[1]))
            oe_idx = orig_edge_map.get(k)
            work_to_orig[we.index] = oe_idx
            if oe_idx is not None:
                work_artist_seam[we.index] = orig_artist_seams[oe_idx]
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

        # Compute extra vertices beyond shading splits
        bm_split = bmesh.new()
        bm_split.from_mesh(work_me)
        bm_split.edges.ensure_lookup_table()
        SE = np.array([[e.verts[0].index, e.verts[1].index] for e in bm_split.edges if work_artist_seam[e.index]], dtype=np.int64).reshape(-1, 2)
        bmesh.ops.split_edges(bm_split, edges=[e for e in bm_split.edges if work_nsplit[e.index] and len(e.link_faces) == 2])
        bm_split.verts.index_update()
        bm_split.faces.ensure_lookup_table()
        NT = np.array([[v.index for v in f.verts] for f in bm_split.faces], dtype=np.int64)
        bm_split.free()

        nv_n = int(len(np.unique(NT)))
        k2_c = np.concatenate([NT.reshape(-1, 1).astype(np.float64), stats['uv'].reshape(-1, 2)], 1)
        extra_verts = int(len(np.unique(k2_c, axis=0))) - nv_n

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
            'extra_vertices_vs_shading': extra_verts,
            'warnings': warnings,
            'time': stats.get('time', 0.0),
            'stats': stats,
            'core_chart_polys': core_chart_polys,
            'tri_to_orig_poly': tri_to_orig_poly,
        }

        if measurement_arrays:
            P = np.zeros(len(work_me.vertices) * 3, np.float64)
            work_me.vertices.foreach_get('co', P)
            P = P.reshape(-1, 3)

            T = np.zeros(len(work_me.polygons) * 3, np.int64)
            work_me.polygons.foreach_get('vertices', T)
            T = T.reshape(-1, 3)

            UV = stats['uv'].reshape(-1, 3, 2)

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

        # Restore original selection, mode on processed object before restoring active object
        for o_name, sel in orig_selection.items():
            o = bpy.context.scene.objects.get(o_name)
            if o:
                o.select_set(sel)
        if bpy.context.object and bpy.context.object.mode != orig_mode:
            bpy.ops.object.mode_set(mode=orig_mode)
        if orig_active and orig_active.name in bpy.context.view_layer.objects:
            bpy.context.view_layer.objects.active = orig_active


def _gather_candidate_objects(context):
    """Gather candidate mesh objects and filter reasons for skipping."""
    skipped = []
    valid = []
    for obj in context.selected_objects:
        if obj.type != 'MESH':
            skipped.append((obj.name, "not a mesh"))
        elif not _editable(obj) or (obj.data and obj.data.library is not None):
            skipped.append((obj.name, "linked or not editable"))
        elif len(obj.data.polygons) == 0:
            skipped.append((obj.name, "no faces"))
        elif len(obj.data.uv_layers) >= 8:
            skipped.append((obj.name, "no free UV map slot (limit 8)"))
        else:
            valid.append(obj)

    mesh_to_objs = {}
    for obj in valid:
        mesh_to_objs.setdefault(obj.data, []).append(obj)

    unique_meshes = list(mesh_to_objs.keys())
    shared_meshes = [
        m for m in unique_meshes
        if len(mesh_to_objs[m]) > 1 or len([o for o in context.scene.objects if o.data == m]) > 1
    ]
    replaced_meshes = []
    for m in unique_meshes:
        auto_cnt, _ = get_mesh_seam_counts(m)
        if auto_cnt > 0:
            replaced_meshes.append(m)

    return unique_meshes, mesh_to_objs, shared_meshes, replaced_meshes, skipped


class FSS_OT_UvProposeSeams(bpy.types.Operator):
    bl_idname = 'fss.uv_propose_seams'
    bl_label = 'Propose Seams'
    bl_description = ('Propose automatic UV seams for selected mesh objects without modifying artist seams. '
                      'Replaces previous automatic seams')
    bl_options = {'REGISTER', 'UNDO'}

    _timer = None
    _unique_meshes = None
    _mesh_to_objs = None
    _shared_meshes = None
    _replaced_meshes = None
    _skipped = None
    _mesh_idx = 0
    _mesh_reports = None
    _cache = None
    _t_start = 0.0
    _is_invoked = False

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and bool(context.selected_objects)

    def invoke(self, context, event):
        unique_meshes, mesh_to_objs, shared_meshes, replaced_meshes, skipped = _gather_candidate_objects(context)
        if not unique_meshes:
            reasons = "; ".join(f"{name}: {reason}" for name, reason in skipped) if skipped else "No objects selected"
            self.report({'WARNING'}, f"No eligible mesh objects to process ({reasons})")
            return {'CANCELLED'}

        self._unique_meshes = unique_meshes
        self._mesh_to_objs = mesh_to_objs
        self._shared_meshes = shared_meshes
        self._replaced_meshes = replaced_meshes
        self._skipped = skipped
        self._is_invoked = True

        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box.label(text=f"Meshes to process: {len(self._unique_meshes)}", icon='MESH_DATA')
        if self._shared_meshes:
            box.label(text=f"Shared meshes ({len(self._shared_meshes)}):", icon='LINKED')
            for m in self._shared_meshes[:5]:
                box.label(text=f"  {m.name}")
            if len(self._shared_meshes) > 5:
                box.label(text=f"  ... and {len(self._shared_meshes) - 5} more")
        if self._replaced_meshes:
            box.label(text=f"Meshes with auto seams to replace: {len(self._replaced_meshes)}", icon='RECOVER_LAST')
            for m in self._replaced_meshes[:5]:
                box.label(text=f"  {m.name}")
            if len(self._replaced_meshes) > 5:
                box.label(text=f"  ... and {len(self._replaced_meshes) - 5} more")
        if self._skipped:
            s_box = layout.box()
            s_box.label(text=f"Skipped objects ({len(self._skipped)}):", icon='CANCEL')
            for name, reason in self._skipped[:10]:
                s_box.label(text=f"  {name}: {reason}")
            if len(self._skipped) > 10:
                s_box.label(text=f"  ... and {len(self._skipped) - 10} more")

    def _process_single_mesh(self, context, mesh, rep_obj, obj_list, cache):
        prop_edges, diag_cuts, rep = propose(rep_obj, cache=cache)
        write_proposal(mesh, prop_edges)
        res = {
            'mesh': mesh.name,
            'objects': [o.name for o in obj_list],
            'islands': rep['stats'].get('charts', len(rep.get('core_chart_polys', []))),
            'extra_vertices_vs_shading': rep.get('extra_vertices_vs_shading', 0),
            'time': rep.get('time', 0.0),
            'unverified_charts': rep['stats'].get('unverified_charts', []),
            'sliver_overlaps': rep['stats'].get('sliver_overlaps', 0),
            'warnings': rep.get('warnings', []),
        }
        return res

    def execute(self, context):
        if self._unique_meshes is None:
            unique_meshes, mesh_to_objs, shared_meshes, replaced_meshes, skipped = _gather_candidate_objects(context)
            if not unique_meshes:
                self.report({'INFO'}, "No eligible mesh objects to process")
                return {'CANCELLED'}
            self._unique_meshes = unique_meshes
            self._mesh_to_objs = mesh_to_objs
            self._shared_meshes = shared_meshes
            self._replaced_meshes = replaced_meshes
            self._skipped = skipped

        # Modal execution in interactive Blender when invoked
        if not bpy.app.background and getattr(self, '_is_invoked', False):
            wm = context.window_manager
            self._timer = wm.event_timer_add(0.01, window=context.window)
            wm.modal_handler_add(self)
            self._mesh_idx = 0
            self._mesh_reports = []
            self._cache = {}
            self._t_start = time.perf_counter()
            context.workspace.status_text_set(f"FSS Auto Seam: 0/{len(self._unique_meshes)} meshes...")
            return {'RUNNING_MODAL'}

        # Synchronous execution for background scripts, headless runs, or direct execute calls
        t_start = time.perf_counter()
        mesh_reports = []
        cache = {}
        for mesh in self._unique_meshes:
            rep_obj = self._mesh_to_objs[mesh][0]
            rep = self._process_single_mesh(context, mesh, rep_obj, self._mesh_to_objs[mesh], cache)
            mesh_reports.append(rep)

        run_time = time.perf_counter() - t_start
        write_report_text(mesh_reports, run_time)
        tot_islands = sum(r['islands'] for r in mesh_reports)
        tot_extra = sum(r['extra_vertices_vs_shading'] for r in mesh_reports)
        self.report(
            {'INFO'},
            f"Auto-seam completed: {len(self._unique_meshes)} mesh(es), "
            f"{tot_islands} islands (+{tot_extra} extra verts) in {run_time:.2f}s. "
            f"See '{REPORT_TEXT_NAME}'."
        )
        return {'FINISHED'}

    def modal(self, context, event):
        if event.type == 'ESC':
            context.window_manager.event_timer_remove(self._timer)
            context.workspace.status_text_set(None)
            run_time = time.perf_counter() - self._t_start
            write_report_text(self._mesh_reports, run_time)
            self.report({'INFO'}, f"Auto-seam cancelled by Esc ({self._mesh_idx}/{len(self._unique_meshes)} meshes). See '{REPORT_TEXT_NAME}'.")
            return {'FINISHED'}

        if event.type == 'TIMER':
            if self._mesh_idx < len(self._unique_meshes):
                mesh = self._unique_meshes[self._mesh_idx]
                rep_obj = self._mesh_to_objs[mesh][0]
                rep = self._process_single_mesh(context, mesh, rep_obj, self._mesh_to_objs[mesh], self._cache)
                self._mesh_reports.append(rep)
                self._mesh_idx += 1
                context.workspace.status_text_set(f"FSS Auto Seam: {self._mesh_idx}/{len(self._unique_meshes)} meshes ({mesh.name})...")
                return {'RUNNING_MODAL'}
            else:
                context.window_manager.event_timer_remove(self._timer)
                context.workspace.status_text_set(None)
                run_time = time.perf_counter() - self._t_start
                write_report_text(self._mesh_reports, run_time)
                tot_islands = sum(r['islands'] for r in self._mesh_reports)
                tot_extra = sum(r['extra_vertices_vs_shading'] for r in self._mesh_reports)
                self.report(
                    {'INFO'},
                    f"Auto-seam completed: {len(self._unique_meshes)} mesh(es), "
                    f"{tot_islands} islands (+{tot_extra} extra verts) in {run_time:.2f}s. "
                    f"See '{REPORT_TEXT_NAME}'."
                )
                return {'FINISHED'}

        return {'PASS_THROUGH'}


class FSS_OT_UvClearAutoSeams(bpy.types.Operator):
    bl_idname = 'fss.uv_clear_auto_seams'
    bl_label = 'Clear Auto Seams'
    bl_description = 'Remove automatic seams from selected mesh objects; artist seams are preserved'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool([o for o in context.selected_objects if o.type == 'MESH' and _editable(o)])

    def execute(self, context):
        meshes = set()
        for o in context.selected_objects:
            if o.type == 'MESH' and _editable(o) and o.data:
                meshes.add(o.data)
        cleared_total = 0
        for m in sorted(meshes, key=lambda m: m.name):
            cleared_total += clear_auto_seams(m)
        self.report({'INFO'}, f"Cleared auto seams on {len(meshes)} mesh(es)")
        return {'FINISHED'}


class FSS_OT_UvKeepAsArtistSeams(bpy.types.Operator):
    bl_idname = 'fss.uv_keep_as_artist_seams'
    bl_label = 'Keep as Artist Seams'
    bl_description = 'Convert automatic seams on selected objects into artist seams so future runs keep them'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool([o for o in context.selected_objects if o.type == 'MESH' and _editable(o)])

    def execute(self, context):
        meshes = set()
        for o in context.selected_objects:
            if o.type == 'MESH' and _editable(o) and o.data:
                meshes.add(o.data)
        kept_total = 0
        for m in sorted(meshes, key=lambda m: m.name):
            kept_total += keep_as_artist_seams(m)
        self.report({'INFO'}, f"Converted auto seams to artist seams on {len(meshes)} mesh(es)")
        return {'FINISHED'}


class FSS_OT_UvSelectAutoSeams(bpy.types.Operator):
    bl_idname = 'fss.uv_select_auto_seams'
    bl_label = 'Select Auto Seams'
    bl_description = 'Select automatic seam edges on the active mesh in Edit Mode'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.mode == 'EDIT_MESH' and
                context.active_object and
                context.active_object.type == 'MESH')

    def execute(self, context):
        obj = context.active_object
        me = obj.data
        bm = bmesh.from_edit_mesh(me)
        bm.edges.ensure_lookup_table()
        context.tool_settings.mesh_select_mode = (False, True, False)
        layer = bm.edges.layers.bool.get(AUTO_SEAM_ATTR)
        sel_count = 0
        for e in bm.edges:
            is_auto = bool(e[layer]) if layer is not None else False
            e.select = is_auto
            if is_auto:
                sel_count += 1
        bmesh.update_edit_mesh(me)
        self.report({'INFO'}, f"Selected {sel_count} auto seam edge(s)")
        return {'FINISHED'}


class FSS_OT_UvSelectArtistSeams(bpy.types.Operator):
    bl_idname = 'fss.uv_select_artist_seams'
    bl_label = 'Select Artist Seams'
    bl_description = 'Select artist seam edges on the active mesh in Edit Mode'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.mode == 'EDIT_MESH' and
                context.active_object and
                context.active_object.type == 'MESH')

    def execute(self, context):
        obj = context.active_object
        me = obj.data
        bm = bmesh.from_edit_mesh(me)
        bm.edges.ensure_lookup_table()
        context.tool_settings.mesh_select_mode = (False, True, False)
        layer = bm.edges.layers.bool.get(AUTO_SEAM_ATTR)
        sel_count = 0
        for e in bm.edges:
            is_auto = bool(e[layer]) if layer is not None else False
            is_artist = e.seam and not is_auto
            e.select = is_artist
            if is_artist:
                sel_count += 1
        bmesh.update_edit_mesh(me)
        self.report({'INFO'}, f"Selected {sel_count} artist seam edge(s)")
        return {'FINISHED'}


class FSS_PT_UvAutoSeam(bpy.types.Panel):
    bl_idname = 'FSS_PT_uv_autoseam'
    bl_label = 'Auto Seam'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'FSS Tools'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        obj = context.active_object

        box = layout.box()
        if obj is None:
            box.label(text='No active object', icon='INFO')
        elif obj.type != 'MESH':
            box.label(text=obj.name, icon='OBJECT_DATA')
            box.label(text='Active object is not a mesh', icon='INFO')
        else:
            box.label(text=f"{obj.name} ({obj.data.name})", icon='MESH_DATA')
            auto_cnt, artist_cnt = get_mesh_seam_counts(obj.data)
            box.label(text=f"Auto seams: {auto_cnt} | Artist seams: {artist_cnt}")

        sel_meshes = {o.data for o in context.selected_objects if o.type == 'MESH' and _editable(o) and o.data}
        box = layout.box()
        box.label(text=f"Selected: {len(sel_meshes)} editable mesh(es)")
        box.operator(FSS_OT_UvProposeSeams.bl_idname, text='Propose Seams', icon='UV_EDGESEL')
        row = box.row(align=True)
        row.operator(FSS_OT_UvClearAutoSeams.bl_idname, text='Clear Auto Seams', icon='X')
        row.operator(FSS_OT_UvKeepAsArtistSeams.bl_idname, text='Keep as Artist Seams', icon='CHECKMARK')

        if context.mode == 'EDIT_MESH':
            row = box.row(align=True)
            row.operator(FSS_OT_UvSelectAutoSeams.bl_idname, text='Select Auto')
            row.operator(FSS_OT_UvSelectArtistSeams.bl_idname, text='Select Artist')

        txt = bpy.data.texts.get(REPORT_TEXT_NAME)
        box = layout.box()
        if txt is not None and len(txt.lines) > 1:
            box.label(text='Last Run Summary:', icon='TEXT')
            shown = 0
            for line in txt.lines[1:]:
                body = line.body.strip()
                if body and not body.startswith('#'):
                    box.label(text=body[:50] + ('...' if len(body) > 50 else ''))
                    shown += 1
                    if shown >= 4:
                        break
            box.label(text=f"Full log: Text Editor > '{REPORT_TEXT_NAME}'", icon='INFO')
        else:
            box.label(text='No runs recorded yet', icon='INFO')


CLASSES = (
    FSS_OT_UvProposeSeams,
    FSS_OT_UvClearAutoSeams,
    FSS_OT_UvKeepAsArtistSeams,
    FSS_OT_UvSelectAutoSeams,
    FSS_OT_UvSelectArtistSeams,
    FSS_PT_UvAutoSeam,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
