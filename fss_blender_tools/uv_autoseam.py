"""
Automatic seam proposal tool for hard-surface meshes.

Constructs a temporary triangulated world-space work copy of the object mesh
(before modifiers), maps edges by vertex pair, runs propose_seams, and reports
the proposal mapped to original edges along with diagonal cut counts.
Leaves the source object and mesh completely unmodified.

Provides operators to propose seams (modal and synchronous), accept or discard the proposed seams, clear the
current seams, and select proposed or current seams in Edit Mode. Wording for artists: "proposed" seams are the
ones the tool wrote and marked fss_auto_seam; "current" seams are all other seams (internally: artist seams).
"""
import math
import re
import time
import numpy as np
import bpy
import bmesh
from bpy.app.handlers import persistent

try:
    from .uv_autoseam_core import THR, propose_seams, _area_distortion, _overlap_pairs, _tri_area3
except ImportError:
    from uv_autoseam_core import THR, propose_seams, _area_distortion, _overlap_pairs, _tri_area3

try:
    from .tags import _editable
except ImportError:
    def _editable(obj):
        return obj.library is None and obj.override_library is None

try:
    from .uv_marks import skip_autoseam
except ImportError:
    try:
        from uv_marks import skip_autoseam
    except ImportError:
        def skip_autoseam(obj):
            return False, None


AUTO_SEAM_ATTR = 'fss_auto_seam'
REPORT_TEXT_NAME = 'FSS Auto Seam Report'

SKIP_MATERIAL_CLASSES = {
    'DECAL', 'DECAL_EM', 'DECAL_FROST', 'DECAL_BLEND',
    'GLASS', 'WNDSHIELD', 'INVIS', 'OCCLUDER'
}

SKIP_MATERIAL_CLASSES = ('DECAL', 'DECAL_EM', 'DECAL_FROST', 'DECAL_BLEND', 'GLASS', 'WNDSHIELD', 'INVIS', 'OCCLUDER')

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


def _is_skip_material(mat):
    """Check if material belongs to decal, glass, invisible, or occluder classes.

    Identified by:
    1. Name class (decision 23): DECAL, DECAL_EM, DECAL_FROST, DECAL_BLEND,
       GLASS, WNDSHIELD, INVIS, OCCLUDER.
    2. MSFS material type registered by the exporter on the material.
    """
    if mat is None:
        return False

    # decision 23 names are <SCENE>_<ZONE>_<CLASS>: the class is the last part, before Blender's .001 suffix
    base = re.sub(r'\.\d+$', '', mat.name.upper())
    for c in SKIP_MATERIAL_CLASSES:
        if base == c or base.endswith('_' + c):
            return True

    mtype = getattr(mat, 'msfs_material_type', None)
    if (mtype is None or mtype == 'NONE') and 'msfs_material_type' in mat:
        mtype = mat['msfs_material_type']
    if mtype in MSFS_SKIP_MATERIAL_TYPES:
        return True

    return False


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


# While Propose Seams or Accept + Unwrap runs, the panel shows this progress instead of its buttons
_progress = None  # dict: verb, index, count, mesh, faces, done_faces, total_faces, stage, within
_cancel_requested = False
_count_cache = {}  # mesh name -> (proposed, current) seam counts, dropped when the mesh changes


def progress_factor(p):
    """Share of the run done, weighted by faces, including the share of the mesh in work."""
    return min((p['done_faces'] + p['within'] * p['faces']) / max(p['total_faces'], 1), 1.0)


def _redraw_panels():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def _redraw_sidebar_now(spaces=('VIEW_3D',)):
    """Draw the sidebar at once while Blender is busy inside one mesh (no event loop runs then). Only the sidebar is
    drawn: during a mesh the window shows the core's temporary scene, which the viewport must not show. spaces: the
    editors whose first visible sidebar is drawn (the packer's progress also shows in the UV editor)."""
    wm = bpy.context.window_manager
    todo = set(spaces)
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type not in todo:
                continue
            for region in area.regions:
                if region.type == 'UI' and region.width > 1:
                    try:
                        with bpy.context.temp_override(window=window, area=area, region=region):
                            bpy.ops.wm.redraw_timer(type='DRAW_SWAP', iterations=1)
                    except Exception:  # no window to draw into (background) or a refused context
                        pass
                    todo.discard(area.type)
                    if not todo:
                        return
                    break


def _on_core_progress(stage, within):
    if _progress is None:
        return
    _progress['stage'], _progress['within'] = stage, within
    bpy.context.workspace.status_text_set(
        f"FSS Auto Seam: {_progress['index']}/{_progress['count']} meshes ({_progress['mesh']}: {stage})...")
    _redraw_sidebar_now()


def selected_seam_counts(context):
    """(proposed, current) seam counts over the selected meshes, cached per mesh until it changes."""
    proposed = current = 0
    for me in {o.data for o in context.selected_objects if o.type == 'MESH' and _editable(o) and o.data}:
        counts = _count_cache.get(me.name)
        if counts is None:
            counts = _count_cache[me.name] = get_mesh_seam_counts(me)
        proposed += counts[0]
        current += counts[1]
    return proposed, current


def seam_buttons(context):
    """The Auto Seam buttons to show: none while a run is in progress; Accept and Discard only with proposed seams,
    Clear Current only with current seams (in Edit Mode the counts cannot be read, so all are shown)."""
    if _progress is not None:
        return set()
    if context.mode != 'OBJECT':
        return {'PROPOSE', 'ACCEPT', 'ACCEPT_UNWRAP', 'DISCARD', 'CLEAR'}
    proposed, current = selected_seam_counts(context)
    shown = {'PROPOSE'}
    if proposed:
        shown |= {'ACCEPT', 'ACCEPT_UNWRAP', 'DISCARD'}
    if current:
        shown.add('CLEAR')
    return shown


@persistent
def _on_depsgraph_update_post(_scene, depsgraph=None):
    if depsgraph is None or not _count_cache:
        return
    for update in depsgraph.updates:
        data = getattr(update.id, 'data', None) if isinstance(update.id, bpy.types.Object) else update.id
        if isinstance(data, bpy.types.Mesh):
            _count_cache.pop(data.name, None)


@persistent
def _on_load_post(_dummy):
    global _progress, _cancel_requested
    _count_cache.clear()
    _progress = None
    _cancel_requested = False


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
    artist, auto = get_mesh_seam_masks(mesh)
    return int(np.count_nonzero(auto)), int(np.count_nonzero(artist))


def write_proposal(mesh, proposed_orig_edges):
    """Write proposed seam edges onto mesh.

    Per mesh datablock:
    1. Removes previous automatic seams (edges marked fss_auto_seam: clears use_seam and the mark).
    2. Sets use_seam and fss_auto_seam boolean edge attribute on the proposal.
    Artist seams are never changed.
    """
    _count_cache.pop(mesh.name, None)
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
    _count_cache.pop(mesh.name, None)
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


def clear_current_seams(mesh):
    """Remove the current seams (every seam not marked fss_auto_seam); proposed seams stay."""
    _count_cache.pop(mesh.name, None)
    current, proposed = get_mesh_seam_masks(mesh)
    count = int(np.count_nonzero(current))
    if count:
        mesh.edges.foreach_set('use_seam', proposed)
        mesh.update()
    return count


def keep_as_artist_seams(mesh):
    """Convert automatic seams to artist seams by removing the fss_auto_seam attribute.

    Seams remain set on use_seam and are treated as artist seams from then on.
    """
    _count_cache.pop(mesh.name, None)
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


def _evaluate_final_unwrap(orig_me, work_me, tri_to_orig_poly, eval_seams, temp_scene, limit=THR):
    """Evaluate final unwrap on an isolated copy of orig_me to detect islands over limits."""
    eval_me = orig_me.copy()
    eval_me.name = f"__fss_autoseam_eval_{orig_me.name}__"
    eval_obj = bpy.data.objects.new(f"__fss_autoseam_eval_{orig_me.name}__", eval_me)
    eval_scene = bpy.data.scenes.new(f"__fss_autoseam_eval_scene_{orig_me.name}__")
    eval_scene.collection.objects.link(eval_obj)
    orig_win_scene = bpy.context.window.scene
    bpy.context.window.scene = eval_scene
    eval_scene.view_layers[0].objects.active = eval_obj
    eval_obj.select_set(True)

    try:
        eval_me.edges.foreach_set('use_seam', eval_seams)

        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.uv.unwrap(method='ANGLE_BASED', fill_holes=False, correct_aspect=True, margin_method='FRACTION', margin=0.001)
        bpy.ops.object.mode_set(mode='OBJECT')

        uv_data = eval_me.uv_layers.active.data
        orig_poly_uv = {}
        for p in eval_me.polygons:
            pmap = {}
            for li in p.loop_indices:
                pmap[eval_me.loops[li].vertex_index] = uv_data[li].uv[:]
            orig_poly_uv[p.index] = pmap

        n_tri = len(work_me.polygons)
        UV_eval = np.zeros((n_tri, 3, 2), dtype=np.float64)
        for ti in range(n_tri):
            pidx = tri_to_orig_poly[ti]
            pmap = orig_poly_uv.get(pidx, {})
            poly_v = work_me.polygons[ti].vertices
            for vi in range(3):
                UV_eval[ti, vi] = pmap.get(poly_v[vi], (0.0, 0.0))

        P_tri = np.zeros(len(work_me.vertices) * 3, np.float64)
        work_me.vertices.foreach_get('co', P_tri)
        P_tri = P_tri.reshape(-1, 3)
        T_tri = np.zeros(n_tri * 3, np.int64)
        work_me.polygons.foreach_get('vertices', T_tri)
        T_tri = T_tri.reshape(-1, 3)
        area3_tri = _tri_area3(P_tri[T_tri])

        par_orig = list(range(len(orig_me.polygons)))
        def find_orig(x):
            while par_orig[x] != x:
                par_orig[x] = par_orig[par_orig[x]]
                x = par_orig[x]
            return x

        edge_polys = [[] for _ in orig_me.edges]
        for p in orig_me.polygons:
            for li in p.loop_indices:
                edge_polys[orig_me.loops[li].edge_index].append(p.index)

        for e in orig_me.edges:
            if not eval_seams[e.index]:
                ep = edge_polys[e.index]
                if len(ep) == 2:
                    r0, r1 = find_orig(ep[0]), find_orig(ep[1])
                    if r0 != r1:
                        par_orig[r0] = r1

        poly_groups = {}
        for i in range(len(orig_me.polygons)):
            poly_groups.setdefault(find_orig(i), []).append(i)

        poly_to_isl = {}
        for isl_idx, plist in enumerate(poly_groups.values()):
            for p in plist:
                poly_to_isl[p] = isl_idx

        tri_isl = np.array([poly_to_isl[p] for p in tri_to_orig_poly], dtype=np.int64)

        islands_over = []
        for isl_idx, plist in enumerate(poly_groups.values()):
            t_indices = np.where(tri_isl == isl_idx)[0]
            if len(t_indices) == 0:
                continue
            U_isl = UV_eval[t_indices]
            d, dmax, _ = _area_distortion(P_tri[T_tri[t_indices]], U_isl)
            pairs = _overlap_pairs(U_isl)
            non_sliver_ov = 0
            if len(pairs) > 0:
                a0 = area3_tri[t_indices[pairs[:, 0]]]
                a1 = area3_tri[t_indices[pairs[:, 1]]]
                sliver = (a0 < 1e-8) & (a1 < 1e-8)
                non_sliver_ov = int(np.count_nonzero(~sliver))

            if d > limit or non_sliver_ov > 0:
                islands_over.append({
                    'island': isl_idx,
                    'faces': len(plist),
                    'distortion': float(d),
                    'overlap': non_sliver_ov > 0,
                    'overlap_pairs': non_sliver_ov,
                })

        return islands_over, len(poly_groups)

    finally:
        if bpy.context.object and bpy.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        if orig_win_scene and orig_win_scene.name in bpy.data.scenes:
            bpy.context.window.scene = orig_win_scene
        if eval_obj.name in eval_scene.collection.objects:
            eval_scene.collection.objects.unlink(eval_obj)
        if eval_obj.name in bpy.data.objects:
            bpy.data.objects.remove(eval_obj, do_unlink=True)
        if eval_me.name in bpy.data.meshes:
            bpy.data.meshes.remove(eval_me, do_unlink=True)
        if eval_scene.name in bpy.data.scenes:
            bpy.data.scenes.remove(eval_scene)


def write_report_text(mesh_reports, run_time):
    """Write or overwrite the text datablock 'FSS Auto Seam Report'.

    Readable report layout (Session 51):
    - Summary at the top: meshes processed, total time, meshes needing attention.
    - One short block per mesh, meshes needing attention first.
    - Plain wording with what to do:
      e.g. '1 island too stretched (7 faces): add a seam by hand'
      e.g. '1 quad too distorted to flatten (2 faces): check the mesh'
    - over_limits counts final-unwrap islands over the distortion limit or with
      non-sliver overlaps, separately from unverified charts.
    """
    txt = bpy.data.texts.get(REPORT_TEXT_NAME)
    if txt is None:
        txt = bpy.data.texts.new(REPORT_TEXT_NAME)
    else:
        txt.clear()

    attention_reports = []
    clean_reports = []
    for r in mesh_reports:
        unv = r.get('unverified_charts', [])
        over = r.get('islands_over_limits', [])
        warns = r.get('warnings', [])
        if unv or over or warns:
            attention_reports.append(r)
        else:
            clean_reports.append(r)

    total_meshes = len(mesh_reports)
    attention_count = len(attention_reports)
    clean_count = len(clean_reports)

    lines = []
    lines.append(f"# FSS Auto Seam Report - {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"# Meshes processed: {total_meshes} in {run_time:.2f}s")
    if mesh_reports:
        lines.append(f"# Distortion limit: {mesh_reports[0].get('limit', THR):.2f}")
    lines.append(f"# Meshes needing attention: {attention_count} ({clean_count} clean)\n")

    def format_mesh_block(r, needs_attention):
        objs_str = ", ".join(r['objects'])
        mesh_name = r['mesh']
        islands = r['islands']
        extra_verts = r.get('extra_vertices_vs_shading', 0)
        t_core = r.get('time', 0.0)
        unv = r.get('unverified_charts', [])
        over = r.get('islands_over_limits', [])
        over_cnt = r.get('over_limits_count', len(over))
        sliver_ov = r.get('sliver_overlaps', 0)
        warns = r.get('warnings', [])

        block_lines = []
        if needs_attention:
            block_lines.append(f"Mesh '{mesh_name}' (objects: {objs_str}) - NEEDS ATTENTION:")
            # Group repeated problems into one line each, so a broken mesh does not flood the report
            zero_area = [x for x in unv + over if not math.isfinite(x.get('distortion', 0.0))]
            small = [u for u in unv if math.isfinite(u.get('distortion', 0.0)) and u.get('faces', 1) <= 2]
            charts = [u for u in unv if math.isfinite(u.get('distortion', 0.0)) and u.get('faces', 1) > 2]
            overlapping = [i for i in over if i.get('overlap', False) and math.isfinite(i.get('distortion', 0.0))]
            stretched = [i for i in over if not i.get('overlap', False) and math.isfinite(i.get('distortion', 0.0))
                         and i.get('distortion', 0.0) > r.get('limit', THR)]

            def worst(items):
                return max(x.get('distortion', 0.0) for x in items)

            def largest(items):
                return max(x.get('faces', 1) for x in items)

            if zero_area:
                block_lines.append(f"  - {len(zero_area)} group(s) of faces with zero area (collapsed or duplicate "
                                   f"faces, largest {largest(zero_area)} faces): clean up the mesh")
            if small:
                block_lines.append(f"  - {len(small)} quad(s) or face(s) too distorted to flatten (worst "
                                   f"{worst(small):.2f}): split or flatten them in the mesh; a seam cannot help")
            if charts:
                block_lines.append(f"  - {len(charts)} chart(s) too distorted to flatten (largest {largest(charts)} "
                                   f"faces, worst {worst(charts):.2f}): add seams by hand through steep steps or corners")
            if overlapping:
                pairs = sum(i.get('overlap_pairs', 0) for i in overlapping)
                block_lines.append(f"  - {len(overlapping)} island(s) with overlapping triangles ({pairs} pair(s), "
                                   f"largest {largest(overlapping)} faces): add a seam by hand across the fold")
            if stretched:
                block_lines.append(f"  - {len(stretched)} island(s) too stretched (largest {largest(stretched)} faces, "
                                   f"worst {worst(stretched):.2f}): add a seam by hand")

            for w in warns:
                block_lines.append(f"  - Warning: {w}")

            if sliver_ov > 0:
                block_lines.append(f"  - {sliver_ov} sliver overlap(s) ignored (< 1e-8 m²)")

            block_lines.append(
                f"  - islands={islands}, extra_verts={extra_verts}, time={t_core:.2f}s, "
                f"over_limits={over_cnt}, unverified={len(unv)}"
            )
        else:
            block_lines.append(f"Mesh '{mesh_name}' (objects: {objs_str}):")
            if sliver_ov > 0:
                block_lines.append(f"  - {sliver_ov} sliver overlap(s) ignored (< 1e-8 m²)")
            block_lines.append(
                f"  - islands={islands}, extra_verts={extra_verts}, time={t_core:.2f}s, "
                f"over_limits=0, unverified=0 (ok)"
            )

        return "\n".join(block_lines)

    for r in attention_reports:
        lines.append(format_mesh_block(r, needs_attention=True))
        lines.append("")

    for r in clean_reports:
        lines.append(format_mesh_block(r, needs_attention=False))
        lines.append("")

    txt.write("\n".join(lines).rstrip() + "\n")


def propose(obj, cache=None, measurement_arrays=False, use_temp_scene=True, limit=THR, progress=None, **kwargs):
    """Propose automatic UV seams on obj without modifying the object or mesh.

    Parameters:
        obj: bpy.types.Object of type 'MESH'.
        cache: optional dict mapping mesh datablock to (proposal, diagonal_cuts, report).
               If provided and obj.data has already been processed, returns the cached result.
        measurement_arrays: bool (default False). When True, includes P, T, UV, NT, SE
                            and work seam/nsplit arrays in report for benchmark runner.
        use_temp_scene: bool (default True). When True, runs propose_seams inside an isolated
                        temporary scene containing only the work object for speed.
        limit: distortion limit for the core's charts and the final check (the panel's Distortion Limit).
        progress: optional function(stage_name, fraction of this mesh), passed to the core.

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
        auto_edges, stats = propose_seams(work_obj, work_artist_seam, work_nsplit, no_cut=work_no_cut, limit=limit,
                                          progress=progress)

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

        # Evaluate final unwrap on orig_me to detect islands over limits
        eval_seams = orig_artist_seams.copy()
        if proposed_orig_edges:
            eval_seams[proposed_orig_edges] = True
        islands_over, final_island_cnt = _evaluate_final_unwrap(
            orig_me, work_me, tri_to_orig_poly, eval_seams, temp_scene, limit
        )

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
            'islands_over_limits': islands_over,
            'over_limits_count': len(islands_over),
            'final_islands_count': final_island_cnt,
            'limit': limit,
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
            is_skipped, source = skip_autoseam(obj)
            if is_skipped:
                reason = "marked Skip Auto Seam" if source == obj else f"marked Skip Auto Seam (from {source.name})"
                skipped.append((obj.name, reason))
            else:
                mats = [slot.material for slot in obj.material_slots if slot.material is not None]
                if not mats and obj.data and obj.data.materials:
                    mats = [m for m in obj.data.materials if m is not None]

                if mats and all(_is_skip_material(m) for m in mats):
                    skipped.append((obj.name, "only decal, glass, invisible or occluder materials"))
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
    bl_description = ('Propose UV seams for the selected mesh objects; their current seams stay and steer the '
                      'proposal. A new proposal replaces the previous proposed seams')
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
            box.label(text=f"Meshes whose proposed seams are replaced: {len(self._replaced_meshes)}", icon='RECOVER_LAST')
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
        prop_edges, diag_cuts, rep = propose(rep_obj, cache=cache, limit=context.scene.fss_uv_autoseam_limit,
                                             progress=_on_core_progress if _progress is not None else None)
        write_proposal(mesh, prop_edges)
        res = {
            'mesh': mesh.name,
            'objects': [o.name for o in obj_list],
            'islands': rep.get('final_islands_count', rep['stats'].get('charts', len(rep.get('core_chart_polys', [])))),
            'extra_vertices_vs_shading': rep.get('extra_vertices_vs_shading', 0),
            'time': rep.get('time', 0.0),
            'unverified_charts': rep['stats'].get('unverified_charts', []),
            'islands_over_limits': rep.get('islands_over_limits', []),
            'over_limits_count': rep.get('over_limits_count', len(rep.get('islands_over_limits', []))),
            'sliver_overlaps': rep['stats'].get('sliver_overlaps', 0),
            'warnings': rep.get('warnings', []),
            'limit': rep.get('limit', THR),
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
            global _progress, _cancel_requested
            wm = context.window_manager
            self._timer = wm.event_timer_add(0.01, window=context.window)
            wm.modal_handler_add(self)
            self._mesh_idx = 0
            self._mesh_reports = []
            self._cache = {}
            self._t_start = time.perf_counter()
            self._announced = False
            _cancel_requested = False
            _progress = {'verb': 'Proposing', 'index': 0, 'count': len(self._unique_meshes), 'mesh': '', 'faces': 0,
                         'done_faces': 0, 'total_faces': sum(len(m.polygons) for m in self._unique_meshes),
                         'stage': '', 'within': 0.0}
            context.workspace.status_text_set(f"FSS Auto Seam: 0/{len(self._unique_meshes)} meshes...")
            _redraw_panels()
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
        attention_count = sum(
            1 for r in mesh_reports
            if r.get('unverified_charts') or r.get('islands_over_limits') or r.get('warnings')
        )
        attention_str = f" ({attention_count} need attention)" if attention_count > 0 else " (all clean)"
        self.report(
            {'INFO'},
            f"Auto-seam completed: {len(self._unique_meshes)} mesh(es), "
            f"{tot_islands} islands (+{tot_extra} extra verts) in {run_time:.2f}s{attention_str}. "
            f"See '{REPORT_TEXT_NAME}'."
        )
        return {'FINISHED'}

    def _finish(self, context, cancelled=False):
        global _progress, _cancel_requested
        context.window_manager.event_timer_remove(self._timer)
        context.workspace.status_text_set(None)
        _progress = None
        _cancel_requested = False
        _redraw_panels()
        run_time = time.perf_counter() - self._t_start
        write_report_text(self._mesh_reports, run_time)
        if cancelled:
            self.report({'INFO'}, f"Auto-seam cancelled ({self._mesh_idx}/{len(self._unique_meshes)} meshes). "
                                  f"See '{REPORT_TEXT_NAME}'.")
            return {'FINISHED'}
        tot_islands = sum(r['islands'] for r in self._mesh_reports)
        tot_extra = sum(r['extra_vertices_vs_shading'] for r in self._mesh_reports)
        attention_count = sum(
            1 for r in self._mesh_reports
            if r.get('unverified_charts') or r.get('islands_over_limits') or r.get('warnings')
        )
        attention_str = f" ({attention_count} need attention)" if attention_count > 0 else " (all clean)"
        self.report(
            {'INFO'},
            f"Auto-seam completed: {len(self._unique_meshes)} mesh(es), "
            f"{tot_islands} islands (+{tot_extra} extra verts) in {run_time:.2f}s{attention_str}. "
            f"See '{REPORT_TEXT_NAME}'."
        )
        return {'FINISHED'}

    def modal(self, context, event):
        if event.type == 'ESC' or _cancel_requested:
            return self._finish(context, cancelled=True)

        if event.type == 'TIMER':
            if self._mesh_idx >= len(self._unique_meshes):
                return self._finish(context)
            mesh = self._unique_meshes[self._mesh_idx]
            if not self._announced:
                # show which mesh comes next before Blender blocks on it
                _progress.update(index=self._mesh_idx + 1, mesh=mesh.name, faces=len(mesh.polygons), stage='Starting',
                                 within=0.0)
                context.workspace.status_text_set(
                    f"FSS Auto Seam: {self._mesh_idx + 1}/{len(self._unique_meshes)} meshes ({mesh.name})...")
                _redraw_panels()
                self._announced = True
                return {'RUNNING_MODAL'}
            rep_obj = self._mesh_to_objs[mesh][0]
            try:
                rep = self._process_single_mesh(context, mesh, rep_obj, self._mesh_to_objs[mesh], self._cache)
            except Exception as ex:
                self._finish(context, cancelled=True)
                self.report({'ERROR'}, f"Auto-seam stopped at '{mesh.name}': {ex}")
                return {'CANCELLED'}
            self._mesh_reports.append(rep)
            self._mesh_idx += 1
            self._announced = False
            _progress['done_faces'] += len(mesh.polygons)
            _progress['within'] = 0.0
            return {'RUNNING_MODAL'}

        return {'PASS_THROUGH'}


class FSS_OT_UvCancelAutoSeam(bpy.types.Operator):
    bl_idname = 'fss.uv_cancel_auto_seam'
    bl_label = 'Cancel'
    bl_description = ('Stop Propose Seams after the mesh in work (as Esc); finished meshes keep their proposed '
                      'seams')
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return _progress is not None and _progress.get('verb') == 'Proposing'

    def execute(self, context):
        global _cancel_requested
        _cancel_requested = True
        return {'FINISHED'}


def _in_object_mode(context, work):
    """Run work() with the mesh data current: in Edit Mode the mesh's own attributes are not filled (Blender keeps
    an editing copy), so switch to Object Mode for the work and back afterwards."""
    was_edit = context.mode == 'EDIT_MESH'
    if was_edit:
        bpy.ops.object.mode_set(mode='OBJECT')
    try:
        return work()
    finally:
        if was_edit:
            bpy.ops.object.mode_set(mode='EDIT')


class FSS_OT_UvClearAutoSeams(bpy.types.Operator):
    bl_idname = 'fss.uv_clear_auto_seams'
    bl_label = 'Discard Proposed'
    bl_description = 'Remove the proposed seams from the selected mesh objects; current seams stay'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool([o for o in context.selected_objects if o.type == 'MESH' and _editable(o)])

    def execute(self, context):
        meshes = set()
        for o in context.selected_objects:
            if o.type == 'MESH' and _editable(o) and o.data:
                meshes.add(o.data)
        cleared_total = _in_object_mode(context, lambda: sum(clear_auto_seams(m)
                                                             for m in sorted(meshes, key=lambda m: m.name)))
        self.report({'INFO'}, f"Discarded {cleared_total} proposed seam(s) on {len(meshes)} mesh(es)")
        return {'FINISHED'}


class FSS_OT_UvKeepAsArtistSeams(bpy.types.Operator):
    bl_idname = 'fss.uv_keep_as_artist_seams'
    bl_label = 'Accept Proposed'
    bl_description = ('Make the proposed seams of the selected mesh objects current seams; later proposals keep '
                      'them')
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool([o for o in context.selected_objects if o.type == 'MESH' and _editable(o)])

    def execute(self, context):
        meshes = set()
        for o in context.selected_objects:
            if o.type == 'MESH' and _editable(o) and o.data:
                meshes.add(o.data)
        kept_total = _in_object_mode(context, lambda: sum(keep_as_artist_seams(m)
                                                          for m in sorted(meshes, key=lambda m: m.name)))
        self.report({'INFO'}, f"Accepted {kept_total} proposed seam(s) on {len(meshes)} mesh(es)")
        return {'FINISHED'}


def _uniform_scale(obj):
    s = obj.matrix_world.to_scale()
    return math.isclose(s.x, s.y, rel_tol=1e-3) and math.isclose(s.y, s.z, rel_tol=1e-3)


def unwrap_angle_based(context, objects):
    """Unwrap the objects' faces with Angle Based, the method Auto Seam checks its seams with, in one multi-object
    Edit Mode pass. Faces with decal, glass, invisible or occluder materials keep their UVs. Restores the mode,
    selection and active object."""
    view_layer = context.view_layer
    prev_active, prev_selected, prev_mode = view_layer.objects.active, list(context.selected_objects), context.mode
    if prev_mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    try:
        for o in prev_selected:
            o.select_set(False)
        for o in objects:
            o.select_set(True)
        view_layer.objects.active = objects[0]
        bpy.ops.object.mode_set(mode='EDIT')
        for o in objects:
            bm = bmesh.from_edit_mesh(o.data)
            skip = {i for i, slot in enumerate(o.material_slots) if _is_skip_material(slot.material)}
            for f in bm.faces:
                f.select_set(f.material_index not in skip)
            bmesh.update_edit_mesh(o.data)
        bpy.ops.uv.unwrap(method='ANGLE_BASED', fill_holes=False, correct_aspect=True, margin=0.001)
        bpy.ops.object.mode_set(mode='OBJECT')
    finally:
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for o in objects:
            o.select_set(False)
        for o in prev_selected:
            o.select_set(True)
        view_layer.objects.active = prev_active
        if prev_mode == 'EDIT_MESH':
            bpy.ops.object.mode_set(mode='EDIT')


class FSS_OT_UvAcceptAndUnwrap(bpy.types.Operator):
    bl_idname = 'fss.uv_accept_and_unwrap'
    bl_label = 'Accept + Unwrap'
    bl_description = ('Accept the proposed seams, then unwrap the selected objects with Angle Based, the method Auto '
                      'Seam checks its seams with. Replaces their UVs')
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool([o for o in context.selected_objects if o.type == 'MESH' and _editable(o)])

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        global _progress
        meshes, mesh_to_objs, _shared, _replaced, skipped = _gather_candidate_objects(context)
        if not meshes:
            self.report({'WARNING'}, 'Nothing to unwrap: ' + '; '.join(f'{n}: {r}' for n, r in skipped[:5]))
            return {'CANCELLED'}
        self._work = (meshes, mesh_to_objs, skipped)
        if bpy.app.background:
            return self._run(context)
        # draw "Unwrapping" first: the unwrap is one Blender call, Blender waits until it is done
        _progress = {'verb': 'Unwrapping', 'index': 1, 'count': len(meshes), 'mesh': '', 'faces': 0,
                     'done_faces': 0, 'total_faces': 1, 'stage': '', 'within': 0.0}
        _redraw_panels()
        context.workspace.status_text_set(f"FSS Auto Seam: unwrapping {len(meshes)} mesh(es)...")
        self._timer = context.window_manager.event_timer_add(0.05, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        global _progress
        if event.type != 'TIMER':
            return {'RUNNING_MODAL'}
        context.window_manager.event_timer_remove(self._timer)
        try:
            return self._run(context)
        finally:
            _progress = None
            context.workspace.status_text_set(None)
            _redraw_panels()

    def _run(self, context):
        meshes, mesh_to_objs, skipped = self._work
        accepted = _in_object_mode(context, lambda: sum(keep_as_artist_seams(m) for m in meshes))
        objects = [mesh_to_objs[m][0] for m in meshes]  # shared mesh data is unwrapped once
        unwrap_angle_based(context, objects)
        scaled = [o.name for o in objects if not _uniform_scale(o)]
        text = f"Accepted {accepted} seam(s), unwrapped {len(meshes)} mesh(es) with Angle Based"
        if skipped:
            text += f"; skipped {len(skipped)}"
        if scaled:
            text += f"; non-uniform scale (unwrap stretches, apply scale first): {', '.join(scaled[:3])}"
        self.report({'WARNING'} if scaled else {'INFO'}, text)
        return {'FINISHED'}


class FSS_OT_UvClearCurrentSeams(bpy.types.Operator):
    bl_idname = 'fss.uv_clear_current_seams'
    bl_label = 'Clear Current'
    bl_description = ('Remove the current seams (all seams except proposed ones) from the selected mesh objects, '
                      'for example before proposing from scratch')
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool([o for o in context.selected_objects if o.type == 'MESH' and _editable(o)])

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        meshes = {o.data for o in context.selected_objects if o.type == 'MESH' and _editable(o) and o.data}
        removed = _in_object_mode(context, lambda: sum(clear_current_seams(m)
                                                       for m in sorted(meshes, key=lambda m: m.name)))
        self.report({'INFO'}, f"Removed {removed} current seam(s) on {len(meshes)} mesh(es)")
        return {'FINISHED'}


class FSS_OT_UvSelectAutoSeams(bpy.types.Operator):
    bl_idname = 'fss.uv_select_auto_seams'
    bl_label = 'Select Proposed'
    bl_description = 'Select the proposed seam edges of the active mesh in Edit Mode'
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
        self.report({'INFO'}, f"Selected {sel_count} proposed seam edge(s)")
        return {'FINISHED'}


class FSS_OT_UvSelectArtistSeams(bpy.types.Operator):
    bl_idname = 'fss.uv_select_artist_seams'
    bl_label = 'Select Current'
    bl_description = 'Select the current seam edges (not proposed) of the active mesh in Edit Mode'
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
        self.report({'INFO'}, f"Selected {sel_count} current seam edge(s)")
        return {'FINISHED'}


class FSS_PT_UvAutoSeam(bpy.types.Panel):
    bl_idname = 'FSS_PT_uv_autoseam'
    bl_label = 'Seams'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'FSS Tools'
    bl_parent_id = 'FSS_PT_uv_tools'
    bl_order = 0
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        obj = context.active_object

        if _progress is not None:
            # a run is in progress: only the progress, no buttons (the scene may be the core's temporary one)
            p = _progress
            box = layout.box()
            if p['verb'] == 'Proposing':
                box.progress(factor=progress_factor(p), type='BAR',
                             text=f"Proposing {p['index']} of {p['count']}: {p['mesh']}")
                box.label(text=f"{p['stage'] or 'Starting'} ({p['faces']:,} faces)", icon='TIME')
                box.operator(FSS_OT_UvCancelAutoSeam.bl_idname, text='Cancel', icon='CANCEL')
                box.label(text='Cancel and Esc stop after the mesh in work')
            else:
                box.progress(factor=progress_factor(p), type='BAR', text=f"Unwrapping {p['count']} mesh(es)")
                box.label(text='Blender waits until the unwrap is done', icon='TIME')
            return

        box = layout.box()
        if obj is None:
            box.label(text='No active object', icon='INFO')
        elif obj.type != 'MESH':
            box.label(text=obj.name, icon='OBJECT_DATA')
            box.label(text='Active object is not a mesh', icon='INFO')
        else:
            box.label(text=f"{obj.name} ({obj.data.name})", icon='MESH_DATA')
            if context.mode == 'OBJECT':
                auto_cnt, artist_cnt = _count_cache.get(obj.data.name) or get_mesh_seam_counts(obj.data)
                box.label(text=f"Proposed: {auto_cnt} | Current: {artist_cnt}")
            else:
                box.label(text="(Seam counts shown in Object Mode)")

        sel_meshes = {o.data for o in context.selected_objects if o.type == 'MESH' and _editable(o) and o.data}
        box = layout.box()
        box.label(text=f"Selected: {len(sel_meshes)} editable mesh(es)")
        col = box.column(align=True)
        col.prop(context.scene, 'fss_uv_autoseam_limit', slider=True)
        row = col.row()
        row.label(text='Less distortion')
        sub = row.row()
        sub.alignment = 'RIGHT'
        sub.label(text='Fewer islands')
        shown = seam_buttons(context)
        box.operator(FSS_OT_UvProposeSeams.bl_idname, text='Propose Seams', icon='UV_EDGESEL')
        if shown & {'ACCEPT', 'ACCEPT_UNWRAP'}:
            row = box.row(align=True)
            row.operator(FSS_OT_UvKeepAsArtistSeams.bl_idname, text='Accept Proposed', icon='CHECKMARK')
            row.operator(FSS_OT_UvAcceptAndUnwrap.bl_idname, text='Accept + Unwrap', icon='UV')
        if shown & {'DISCARD', 'CLEAR'}:
            row = box.row(align=True)
            if 'DISCARD' in shown:
                row.operator(FSS_OT_UvClearAutoSeams.bl_idname, text='Discard Proposed', icon='X')
            if 'CLEAR' in shown:
                row.operator(FSS_OT_UvClearCurrentSeams.bl_idname, text='Clear Current', icon='TRASH')

        if context.mode == 'EDIT_MESH':
            row = box.row(align=True)
            row.operator(FSS_OT_UvSelectAutoSeams.bl_idname, text='Select Proposed')
            row.operator(FSS_OT_UvSelectArtistSeams.bl_idname, text='Select Current')

        from .uv_marks import draw_skip_autoseam
        draw_skip_autoseam(layout, context)

        txt = bpy.data.texts.get(REPORT_TEXT_NAME)
        box = layout.box()
        if txt is not None and len(txt.lines) > 2:
            box.label(text='Last Run Summary:', icon='TEXT')
            header_lines = [l.body.strip() for l in txt.lines if l.body.strip().startswith('#')]
            for h in header_lines[1:]:
                text = h.lstrip('#').strip()
                if 'needing attention: 0' in text:
                    box.label(text=text, icon='CHECKMARK')
                elif 'needing attention:' in text:
                    box.label(text=text, icon='ERROR')
                else:
                    box.label(text=text)
            box.label(text=f"Full report: Text Editor > '{REPORT_TEXT_NAME}'", icon='INFO')
        else:
            box.label(text='No runs recorded yet', icon='INFO')


CLASSES = (
    FSS_OT_UvProposeSeams,
    FSS_OT_UvClearAutoSeams,
    FSS_OT_UvKeepAsArtistSeams,
    FSS_OT_UvAcceptAndUnwrap,
    FSS_OT_UvCancelAutoSeam,
    FSS_OT_UvClearCurrentSeams,
    FSS_OT_UvSelectAutoSeams,
    FSS_OT_UvSelectArtistSeams,
    FSS_PT_UvAutoSeam,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    for handlers, handler in ((bpy.app.handlers.depsgraph_update_post, _on_depsgraph_update_post),
                              (bpy.app.handlers.load_post, _on_load_post)):
        if handler not in handlers:
            handlers.append(handler)
    bpy.types.Scene.fss_uv_autoseam_limit = bpy.props.FloatProperty(
        name='Distortion Limit', default=THR, min=1.05, max=2.0, soft_min=1.05, soft_max=1.75,
        precision=2, step=5,
        description='How much an island may stretch (1.0 = not at all). Higher: fewer islands and seam vertices, '
                    'more stretch. Lower: less stretch, more islands. Mostly changes large shells')


def unregister():
    for handlers, handler in ((bpy.app.handlers.depsgraph_update_post, _on_depsgraph_update_post),
                              (bpy.app.handlers.load_post, _on_load_post)):
        if handler in handlers:
            handlers.remove(handler)
    del bpy.types.Scene.fss_uv_autoseam_limit
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
