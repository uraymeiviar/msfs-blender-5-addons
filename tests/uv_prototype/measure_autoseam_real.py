"""
Runner and benchmark for real-mesh auto-seam proposal (Package 2c: Honest Checks & Seams as Contract).

Runs propose(obj) from fss_blender_tools.uv_autoseam across:
1. The 17 original objects from tests/_work/uv_autoseam/package2c/E2_COCKPIT2_copy.blend
2. Mirror / Array objects from that file
3. A synthetic shared-mesh case with non-uniform scale

Verifies (Finish Line):
- 0 diagonal splits in both layouts on all 22 objects
- Round trip islands equal to the core's (by UV connectivity, with margin 0.001) on all 22
- 0 intra-island overlaps in both layouts on all 22
- Decision 49 fallback counts and island cost per object
- Session 17 shape criteria evaluation
- Complete object state restoration
"""
import importlib.util
import json
import math
import os
import sys
import time
from pathlib import Path
import bpy
import bmesh
import numpy as np

# Configure paths
REPO_ROOT = Path(__file__).resolve().parents[2]
FSS_TOOLS = REPO_ROOT / 'fss_blender_tools'
UV_PROTO = REPO_ROOT / 'tests' / 'uv_prototype'

if str(FSS_TOOLS) not in sys.path:
    sys.path.insert(0, str(FSS_TOOLS))
if str(UV_PROTO) not in sys.path:
    sys.path.insert(0, str(UV_PROTO))

import uv_autoseam
import uvmetrics
from evaluate3_extra import artist_texel

WORK_DIR = REPO_ROOT / 'tests' / '_work' / 'uv_autoseam' / 'package2c'
WORK_DIR.mkdir(parents=True, exist_ok=True)

BLEND_PATH = WORK_DIR / 'E2_COCKPIT2_copy.blend'
if not BLEND_PATH.exists():
    BLEND_PATH = REPO_ROOT / 'tests' / '_work' / 'uv_shape' / 'E2_COCKPIT2_copy.blend'

C1_SUMMARY_PATH = REPO_ROOT / 'tests' / '_work' / 'uv_shape' / 'candidates_summary.json'
C1_DATA = {}
if C1_SUMMARY_PATH.exists():
    try:
        with open(C1_SUMMARY_PATH) as f:
            C1_DATA = json.load(f)
    except Exception as e:
        print(f"Warning: could not load C1 summary: {e}")

PKG2B_SUMMARY_PATH = REPO_ROOT / 'tests' / '_work' / 'uv_autoseam' / 'package2b' / 'measure_real_summary.json'
PKG2B_DATA = {}
if PKG2B_SUMMARY_PATH.exists():
    try:
        with open(PKG2B_SUMMARY_PATH) as f:
            data = json.load(f)
            PKG2B_DATA = data.get('objects', {})
    except Exception as e:
        print(f"Warning: could not load Package 2b summary: {e}")

ORIGINAL_17 = [
    '@MERGE_PEDESTAL_SHELL',
    'AUDIO_L_VOLUME_KNOB',
    'COCKPIT_SHELL_FLOOR',
    'COCKPIT_SHELL_L',
    'LEVER_FLAP_LOCK',
    'OVERHEAD_SHELL',
    'TRIM_PANEL',
    'B_GS_AFCS_AP_BUTTON',
    'CCD_LEFT_ROTARY_OUTER',
    'CIRCUIT_BREAKER_COVER_L',
    'COCKPIT_REAR_OBS_SEAT_MOUNTING_FRAME',
    'DISC_HANDLE_AILERON',
    'EFB_HINGE_ARM_1',
    'EFB_HINGE_CLAMP_ROTATOR',
    'EFB_HINGE_ROTATOR_2',
    'LEVER_FLAP',
    'POWERPLANT_COVER_L',
]

MIRROR_ARRAY_CANDIDATES = [
    'COCKPIT_REAR_WINDOW_HOLE_R_FRAME',
    'COCKPIT_REAR_DOOR_VENT',
    'COCKPIT_CEILING_PANEL',
]

SPEED_TEST_OBJECTS = [
    'TRIM_PANEL',
    'COCKPIT_SHELL_FLOOR',
    'OVERHEAD_SHELL',
]


def snapshot_object_state(obj):
    """Snapshot object state to assert strict restoration."""
    me = obj.data
    return {
        'name': obj.name,
        'mesh_name': me.name,
        'verts': len(me.vertices),
        'edges': len(me.edges),
        'faces': len(me.polygons),
        'uv_layers': [l.name for l in me.uv_layers],
        'seams': [e.use_seam for e in me.edges],
        'mod_show': [m.show_viewport for m in obj.modifiers],
        'mode': obj.mode,
        'active': bpy.context.view_layer.objects.active.name if bpy.context.view_layer.objects.active else None,
        'selected': obj.select_get(),
    }


def assert_object_restored(obj, snap):
    """Assert that object and mesh state are 100% restored."""
    me = obj.data
    assert obj.name == snap['name'], f"{obj.name}: name changed"
    assert me.name == snap['mesh_name'], f"{obj.name}: mesh name changed"
    assert len(me.vertices) == snap['verts'], f"{obj.name}: vertex count changed ({len(me.vertices)} != {snap['verts']})"
    assert len(me.edges) == snap['edges'], f"{obj.name}: edge count changed ({len(me.edges)} != {snap['edges']})"
    assert len(me.polygons) == snap['faces'], f"{obj.name}: face count changed ({len(me.polygons)} != {snap['faces']})"
    assert [l.name for l in me.uv_layers] == snap['uv_layers'], f"{obj.name}: uv layers changed"
    assert [e.use_seam for e in me.edges] == snap['seams'], f"{obj.name}: seam flags changed"
    assert [m.show_viewport for m in obj.modifiers] == snap['mod_show'], f"{obj.name}: modifier show_viewport changed"
    assert obj.mode == snap['mode'], f"{obj.name}: mode changed ({obj.mode} != {snap['mode']})"
    curr_active = bpy.context.view_layer.objects.active.name if bpy.context.view_layer.objects.active else None
    assert curr_active == snap['active'], f"{obj.name}: active object changed ({curr_active} != {snap['active']})"


def create_synthetic_shared_mesh_objects():
    """Create two objects sharing a quad mesh, one with non-uniform scale."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.bevel(bm, geom=bm.edges[:] + bm.verts[:], offset=0.1, segments=1, profile=0.5, affect='EDGES')
    me = bpy.data.meshes.new('SYNTH_PANEL_MESH')
    bm.to_mesh(me)
    bm.free()

    o1 = bpy.data.objects.new('SYNTH_PANEL_UNIFORM', me)
    o1.location = (100.0, 0.0, 0.0)
    o1.scale = (1.0, 1.0, 1.0)
    bpy.context.scene.collection.objects.link(o1)

    o2 = bpy.data.objects.new('SYNTH_PANEL_NONUNIFORM', me)
    o2.location = (105.0, 0.0, 0.0)
    o2.scale = (1.5, 0.8, 1.0)
    bpy.context.scene.collection.objects.link(o2)

    bpy.context.view_layer.update()
    return o1, o2


def evaluate_shape(P, T, UV, NT, SE, labels=None):
    """Compute Session 17 shape criteria on triangulated mesh."""
    shape = uvmetrics.shape_metrics(P, T, UV, island_ids=labels)['object']
    if labels is None:
        _, _, labels = uvmetrics._uv_topology(T, UV)
    artist = artist_texel(P, T, UV, labels, SE)

    k2 = np.concatenate([NT.reshape(-1, 1).astype(np.float64), UV.reshape(-1, 2)], 1)
    rv = int(len(np.unique(k2, axis=0)))
    nv_n = int(len(np.unique(NT)))
    render_extra_vs_normals = rv - nv_n

    intra_overlaps = 0
    for isl in np.unique(labels):
        isl_uv = UV[labels == isl]
        intra_overlaps += len(uvmetrics.overlap_pairs(isl_uv))

    cross_outside_stubs = artist['artist_seam_crossed_edges'] - artist['artist_seam_crossed_in_stubs']
    st = shape['straight_edges']['preserved_fraction'] if shape['straight_edges'] else None

    return {
        'islands': shape['island_count'],
        'c_mean': shape['conformal']['mean'],
        'c_p95': shape['conformal']['p95'],
        'c_max': shape['conformal']['max'],
        'a_mean': shape['area_distortion']['mean'],
        'a_p95': shape['area_distortion']['p95'],
        'a_max': shape['area_distortion']['max'],
        'planar_c': shape['planar']['conformal']['mean'] if shape['planar'] else None,
        'planar_a': shape['planar']['area_distortion']['mean'] if shape['planar'] else None,
        'straight': st * 100.0 if st is not None else None,
        'intra_overlaps': intra_overlaps,
        'cross_outside_stubs': cross_outside_stubs,
        'render_extra_vs_normals': render_extra_vs_normals,
    }


def run_round_trip(o, prop_edges, rep):
    """Perform honest round-trip check on a copy of the original mesh.

    Per Step 5:
    - Blender uv.unwrap with margin_method='FRACTION', margin=0.001
    - Islands by UV connectivity compared by original polygons
    - Intra-island overlaps evaluated on work triangles with Blender UVs looked up by polygon and vertex
    - Extra vertices computed the same way for both layouts
    - Diagonal splits counted from actual UVs in both layouts
    """
    print("    [RT] A: copying mesh...", flush=True)
    orig_me = o.data
    copy_me = orig_me.copy()
    copy_me.name = f"__fss_rt_{orig_me.name}__"

    print("    [RT] B: clearing and creating UVMap...", flush=True)
    while copy_me.uv_layers:
        copy_me.uv_layers.remove(copy_me.uv_layers[0])
    uvl = copy_me.uv_layers.new(name="UVMap")

    print("    [RT] C: setting seams...", flush=True)
    orig_seams = np.zeros(len(copy_me.edges), bool)
    orig_me.edges.foreach_get('use_seam', orig_seams)
    for idx in prop_edges:
        orig_seams[idx] = True
    for e, s in zip(copy_me.edges, orig_seams):
        e.use_seam = bool(s)

    print("    [RT] D: creating temp scene...", flush=True)
    copy_obj = bpy.data.objects.new(f"__fss_rt_obj_{o.name}__", copy_me)
    orig_scene = bpy.context.scene
    temp_scene = bpy.data.scenes.new(f"__fss_rt_temp_{o.name}__")

    try:
        temp_scene.collection.objects.link(copy_obj)
        bpy.context.window.scene = temp_scene
        temp_scene.view_layers[0].objects.active = copy_obj
        copy_obj.select_set(True)

        print("    [RT] E: entering edit mode and selecting...", flush=True)
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        print("    [RT] F: calling uv.unwrap...", flush=True)
        bpy.ops.uv.unwrap(method='ANGLE_BASED', fill_holes=False, correct_aspect=True, margin_method='FRACTION', margin=0.001)
        print("    [RT] G: returning to object mode...", flush=True)
        bpy.ops.object.mode_set(mode='OBJECT')

        print("    [RT] H: mapping Blender UVs to triangles...", flush=True)
        tri_to_orig_poly = rep['tri_to_orig_poly']
        T = rep['T']
        core_UV = rep['UV']

        # Fetch fresh UV data in Object Mode
        uv_data = copy_me.uv_layers.active.data
        orig_poly_loop_uv = {}
        for p in copy_me.polygons:
            p_map = {}
            for li in p.loop_indices:
                v_idx = copy_me.loops[li].vertex_index
                p_map[v_idx] = tuple(uv_data[li].uv)
            orig_poly_loop_uv[p.index] = p_map

        blender_work_UV = np.zeros((len(T), 3, 2), dtype=np.float64)
        for ti, tri_verts in enumerate(T):
            p_idx = tri_to_orig_poly[ti]
            p_map = orig_poly_loop_uv[p_idx]
            for vi, v in enumerate(tri_verts):
                blender_work_UV[ti, vi] = p_map.get(v, (0.0, 0.0))

        print("    [RT] I: checking diagonal splits...", flush=True)
        edge_tris = {}
        for ti, tri in enumerate(T):
            for i in range(3):
                e = tuple(sorted((tri[i], tri[(i + 1) % 3])))
                edge_tris.setdefault(e, []).append((ti, i, (i + 1) % 3))

        core_diag_splits = 0
        rt_diag_splits = 0
        total_diags = 0

        for e, tlist in edge_tris.items():
            if len(tlist) == 2:
                (t0, i0a, i0b), (t1, i1a, i1b) = tlist
                if tri_to_orig_poly[t0] == tri_to_orig_poly[t1]:
                    total_diags += 1
                    u0a, u0b = core_UV[t0, i0a], core_UV[t0, i0b]
                    v_a = T[t0, i0a]
                    u1a = core_UV[t1, i1a] if T[t1, i1a] == v_a else core_UV[t1, i1b]
                    u1b = core_UV[t1, i1b] if T[t1, i1a] == v_a else core_UV[t1, i1a]
                    if np.max(np.abs(u0a - u1a)) > 1e-6 or np.max(np.abs(u0b - u1b)) > 1e-6:
                        core_diag_splits += 1

                    ru0a, ru0b = blender_work_UV[t0, i0a], blender_work_UV[t0, i0b]
                    ru1a = blender_work_UV[t1, i1a] if T[t1, i1a] == v_a else blender_work_UV[t1, i1b]
                    ru1b = blender_work_UV[t1, i1b] if T[t1, i1a] == v_a else blender_work_UV[t1, i1a]
                    if np.max(np.abs(ru0a - ru1a)) > 1e-6 or np.max(np.abs(ru0b - ru1b)) > 1e-6:
                        rt_diag_splits += 1

        print("    [RT] J: checking RT islands...", flush=True)
        edge_polys = [[] for _ in copy_me.edges]
        for p in copy_me.polygons:
            for li in p.loop_indices:
                edge_polys[copy_me.loops[li].edge_index].append(p.index)

        par_rt = list(range(len(copy_me.polygons)))

        def find_rt(x):
            while par_rt[x] != x:
                par_rt[x] = par_rt[par_rt[x]]
                x = par_rt[x]
            return x

        for e in copy_me.edges:
            ep = edge_polys[e.index]
            if len(ep) == 2:
                p0, p1 = ep[0], ep[1]
                v0, v1 = e.vertices[0], e.vertices[1]
                u0_v0, u0_v1 = orig_poly_loop_uv[p0][v0], orig_poly_loop_uv[p0][v1]
                u1_v0, u1_v1 = orig_poly_loop_uv[p1][v0], orig_poly_loop_uv[p1][v1]
                if np.max(np.abs(np.array(u0_v0) - np.array(u1_v0))) < 1e-5 and np.max(np.abs(np.array(u0_v1) - np.array(u1_v1))) < 1e-5:
                    r0, r1 = find_rt(p0), find_rt(p1)
                    if r0 != r1:
                        par_rt[r0] = r1

        rt_groups = {}
        for i in range(len(copy_me.polygons)):
            rt_groups.setdefault(find_rt(i), set()).add(i)
        rt_islands = [frozenset(s) for s in rt_groups.values()]

        print("    [RT] K: checking Core islands...", flush=True)
        par_c = list(range(len(copy_me.polygons)))

        def find_c(x):
            while par_c[x] != x:
                par_c[x] = par_c[par_c[x]]
                x = par_c[x]
            return x

        for e, tlist in edge_tris.items():
            if len(tlist) == 2:
                (t0, i0a, i0b), (t1, i1a, i1b) = tlist
                p0, p1 = tri_to_orig_poly[t0], tri_to_orig_poly[t1]
                if p0 != p1:
                    u0a, u0b = core_UV[t0, i0a], core_UV[t0, i0b]
                    v_a = T[t0, i0a]
                    u1a = core_UV[t1, i1a] if T[t1, i1a] == v_a else core_UV[t1, i1b]
                    u1b = core_UV[t1, i1b] if T[t1, i1a] == v_a else core_UV[t1, i1a]
                    if np.max(np.abs(u0a - u1a)) < 1e-5 and np.max(np.abs(u0b - u1b)) < 1e-5:
                        r0, r1 = find_c(p0), find_c(p1)
                        if r0 != r1:
                            par_c[r0] = r1

        core_groups = {}
        for i in range(len(copy_me.polygons)):
            core_groups.setdefault(find_c(i), set()).add(i)
        core_islands = [frozenset(s) for s in core_groups.values()]

        islands_equal = (sorted([sorted(s) for s in rt_islands]) == sorted([sorted(s) for s in core_islands]))

        print("    [RT] L: intra-island overlaps...", flush=True)
        poly_to_core_isl = {}
        for isl_idx, s in enumerate(core_islands):
            for p in s:
                poly_to_core_isl[p] = isl_idx
        core_tri_labels = np.array([poly_to_core_isl[p] for p in tri_to_orig_poly], dtype=np.int64)

        core_overlaps = 0
        for isl_idx in range(len(core_islands)):
            isl_tris = np.where(core_tri_labels == isl_idx)[0]
            if len(isl_tris) > 0:
                core_overlaps += len(uvmetrics.overlap_pairs(core_UV[isl_tris]))

        poly_to_rt_isl = {}
        for isl_idx, s in enumerate(rt_islands):
            for p in s:
                poly_to_rt_isl[p] = isl_idx
        rt_tri_labels = np.array([poly_to_rt_isl[p] for p in tri_to_orig_poly], dtype=np.int64)

        rt_overlaps = 0
        for isl_idx in range(len(rt_islands)):
            isl_tris = np.where(rt_tri_labels == isl_idx)[0]
            if len(isl_tris) > 0:
                rt_overlaps += len(uvmetrics.overlap_pairs(blender_work_UV[isl_tris]))

        print("    [RT] M: extra vertices...", flush=True)
        NT = rep['NT']
        nv_n = int(len(np.unique(NT)))
        k2_c = np.concatenate([NT.reshape(-1, 1).astype(np.float64), core_UV.reshape(-1, 2)], 1)
        core_extra = int(len(np.unique(k2_c, axis=0))) - nv_n
        k2_rt = np.concatenate([NT.reshape(-1, 1).astype(np.float64), blender_work_UV.reshape(-1, 2)], 1)
        rt_extra = int(len(np.unique(k2_rt, axis=0))) - nv_n

        print("    [RT] N: evaluate_shape on blender_work_UV...", flush=True)
        P = rep['P']
        SE = rep['SE']
        metrics = evaluate_shape(P, T, blender_work_UV, NT, SE, labels=rt_tri_labels)
        metrics['intra_overlaps'] = rt_overlaps
        metrics['render_extra_vs_normals'] = rt_extra
        print("    [RT] O: evaluate_shape done!", flush=True)

        return {
            'islands_equal': islands_equal,
            'mesh_islands_count': len(rt_islands),
            'core_charts_count': len(core_islands),
            'rt_diag_splits': rt_diag_splits,
            'core_diag_splits': core_diag_splits,
            'total_diags': total_diags,
            'core_overlaps': core_overlaps,
            'core_extra': core_extra,
            'core_tri_labels': core_tri_labels,
            'metrics': metrics,
            'blender_UV': blender_work_UV,
        }

    finally:
        if orig_scene and orig_scene.name in bpy.data.scenes:
            bpy.context.window.scene = orig_scene
        if copy_obj and copy_obj.name in temp_scene.collection.objects:
            temp_scene.collection.objects.unlink(copy_obj)
        if temp_scene and temp_scene.name in bpy.data.scenes:
            bpy.data.scenes.remove(temp_scene)
        if copy_obj and copy_obj.name in bpy.data.objects:
            bpy.data.objects.remove(copy_obj, do_unlink=True)
        if copy_me and copy_me.name in bpy.data.meshes:
            bpy.data.meshes.remove(copy_me, do_unlink=True)


def main():
    print(f"Opening blend file: {BLEND_PATH}")
    bpy.ops.wm.open_mainfile(filepath=str(BLEND_PATH))

    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    # Collect test objects
    all_objects = []
    print("\n--- Collecting Test Objects ---")

    # 1. 17 Originals
    for name in ORIGINAL_17:
        o = bpy.data.objects.get(name)
        if o:
            all_objects.append(('ORIGINAL_17', o))
            print(f"  [17] Found {name}")
        else:
            print(f"  [17] WARNING: Missing {name}")

    # 2. Mirror / Array objects
    for name in MIRROR_ARRAY_CANDIDATES:
        o = bpy.data.objects.get(name)
        if o and o.type == 'MESH':
            all_objects.append(('MIRROR_ARRAY', o))
            print(f"  [MA] Found {name}: mods={[m.type for m in o.modifiers]}")

    # 3. Synthetic shared-mesh case
    synth_o1, synth_o2 = create_synthetic_shared_mesh_objects()
    all_objects.append(('SYNTHETIC_SHARED', synth_o1))
    all_objects.append(('SYNTHETIC_SHARED', synth_o2))
    print(f"  [SYNTH] Created {synth_o1.name} (uniform) and {synth_o2.name} (non-uniform scale)")

    results = {}
    mesh_cache = {}

    print(f"\n================================================================================")
    print(f"RUNNING PACKAGE 2c: HONEST CHECKS & SEAMS AS CONTRACT ({len(all_objects)} objects)")
    print(f"================================================================================\n")

    for cat, o in all_objects:
        obj_name = o.name
        print(f"Processing [{cat}] {obj_name} (mesh: {o.data.name})...", flush=True)

        snap = snapshot_object_state(o)
        t_start = time.perf_counter()

        # Propose with temporary scene and measurement arrays
        print(f"  -> calling propose...", flush=True)
        prop_edges, diag_cuts, rep = uv_autoseam.propose(
            o, cache=mesh_cache, measurement_arrays=True, use_temp_scene=True
        )
        elapsed = time.perf_counter() - t_start
        print(f"  -> propose done in {elapsed:.2f}s", flush=True)

        # State restoration assertion
        print(f"  -> asserting object restored...", flush=True)
        assert_object_restored(o, snap)

        # Execute Round Trip check on copy of original mesh
        print(f"  -> calling run_round_trip...", flush=True)
        rt_result = run_round_trip(o, prop_edges, rep)
        print(f"  -> run_round_trip done", flush=True)

        # Evaluate Core metrics (on rep['UV'])
        print(f"  -> evaluating core metrics...", flush=True)
        core_met = evaluate_shape(rep['P'], rep['T'], rep['UV'], rep['NT'], rep['SE'], labels=rt_result['core_tri_labels'])
        core_met['time'] = rep['time']
        core_met['intra_overlaps'] = rt_result['core_overlaps']
        core_met['render_extra_vs_normals'] = rt_result['core_extra']
        print(f"  -> core metrics evaluated", flush=True)

        # Decision 49 stats from core
        stats = rep.get('stats', {})
        fb_cuts = stats.get('fallback_cuts', 0)
        fb_seed = stats.get('fallback_seed', 0)
        gate_rep = stats.get('gate_repaired', 0)
        gate_rnd = stats.get('gate_rounds', 0)

        # Baseline comparisons
        c1_key = 'W_' + obj_name
        c1_ref = C1_DATA.get(c1_key, {}).get('c1')
        s43_ref = PKG2B_DATA.get(obj_name)

        results[obj_name] = {
            'category': cat,
            'object': obj_name,
            'mesh': o.data.name,
            'modifiers': rep['modifiers'],
            'eval_topology_matches': rep['eval_topology_matches'],
            'faces_before': rep['faces_before'],
            'faces_after': rep['faces_after'],
            'edges_orig': rep['edges_orig'],
            'edges_work': rep['edges_work'],
            'diagonals_total': rep['diagonals_total'],
            'proposed_edges_count': len(prop_edges),
            'diagonal_cuts_count': diag_cuts,
            'shading_splits_method': rep['shading_splits_method'],
            'shading_splits_count': rep['shading_splits_count'],
            'warnings': rep['warnings'],
            'cached': rep.get('cached_from_mesh') is not None,
            'core_time': rep['time'],
            'total_time': elapsed,
            'core_metrics': core_met,
            'round_trip': rt_result,
            'fallback_cuts': fb_cuts,
            'fallback_seed': fb_seed,
            'gate_repaired': gate_rep,
            'gate_rounds': gate_rnd,
            'c1_metrics': c1_ref,
            's43_metrics': s43_ref,
            'restore_pass': True,
        }

        rt_m = rt_result['metrics']
        print(
            f"  -> Done in {elapsed:.2f}s: prop={len(prop_edges)}, "
            f"diag_splits(c/rt)={rt_result['core_diag_splits']}/{rt_result['rt_diag_splits']}, "
            f"islands(c/rt)={rt_result['core_charts_count']}/{rt_result['mesh_islands_count']}, "
            f"equal={rt_result['islands_equal']}, ov(c/rt)={core_met['intra_overlaps']}/{rt_m['intra_overlaps']}, "
            f"extra_v(c/rt)={core_met['render_extra_vs_normals']}/{rt_m['render_extra_vs_normals']}, "
            f"fb_cuts={fb_cuts}, fb_seed={fb_seed}, gate_rep={gate_rep}"
        )

    # Speed benchmark: measure with and without temporary scene on selected objects
    print("\n--- Running Speed Benchmark (With vs Without Temporary Scene) ---")
    speed_results = {}
    for name in SPEED_TEST_OBJECTS:
        o = bpy.data.objects.get(name)
        if not o:
            continue
        print(f"Testing speed on {name}...", flush=True)

        t0 = time.perf_counter()
        _, _, rep_with = uv_autoseam.propose(o, measurement_arrays=False, use_temp_scene=True)
        t_with = rep_with['time']

        t0 = time.perf_counter()
        _, _, rep_without = uv_autoseam.propose(o, measurement_arrays=False, use_temp_scene=False)
        t_without = rep_without['time']

        speedup = t_without / max(t_with, 1e-6)
        speed_results[name] = {
            'with_temp_scene': t_with,
            'without_temp_scene': t_without,
            'speedup': speedup,
        }
        print(f"  {name:22s}: with={t_with:.2f}s, without={t_without:.2f}s (speedup: {speedup:.2f}x)")

    # Save JSON summary
    json_path = WORK_DIR / 'measure_real_summary.json'
    summary_data = {
        'objects': results,
        'speed_benchmark': speed_results,
    }
    with open(json_path, 'w') as f:
        json.dump(summary_data, f, indent=2, default=str)
    print(f"\nSaved JSON summary to {json_path}")

    # Build Markdown Report
    md_lines = []
    md_lines.append("# Package 2c: Seams as Contract, Honest Checks Report\n")
    md_lines.append(f"- **Date:** {time.strftime('%Y-%m-%d %H:%M:%S')}")
    md_lines.append(f"- **Blend file:** `{BLEND_PATH.name}`")
    md_lines.append(f"- **Total objects tested:** {len(all_objects)}\n")

    md_lines.append("## Table 1: Mesh Topology, Diagonal Splits, Seams, Round Trip, and Core Time\n")
    md_lines.append("| Object | Category | Modifiers | Topo Match | Faces (Orig/Tri) | Diagonals | Diag Splits (Core/RT) | Proposed Edges | Islands (Core/RT) | RT Equal? | Overlaps (Core/RT) | Core Time (s) |")
    md_lines.append("| :--- | :--- | :--- | :---: | :---: | ---: | :---: | ---: | :---: | :---: | :---: | ---: |")

    for name, r in results.items():
        mods = ", ".join(r['modifiers']) if r['modifiers'] else "none"
        topo = "yes" if r['eval_topology_matches'] else "no"
        faces = f"{r['faces_before']} / {r['faces_after']}"
        rt = r['round_trip']
        c_m = r['core_metrics']
        rt_m = rt['metrics']
        rt_eq = "yes" if rt['islands_equal'] else "no"
        diag_str = f"**{rt['core_diag_splits']} / {rt['rt_diag_splits']}**"
        isl_str = f"{rt['core_charts_count']} / {rt['mesh_islands_count']}"
        ov_str = f"{c_m['intra_overlaps']} / {rt_m['intra_overlaps']}"
        md_lines.append(
            f"| `{name}` | {r['category']} | {mods} | {topo} | {faces} | "
            f"{r['diagonals_total']:,} | {diag_str} | {r['proposed_edges_count']:,} | "
            f"{isl_str} | **{rt_eq}** | {ov_str} | {r['core_time']:.2f} |"
        )

    md_lines.append("\n## Table 2: Comparison against Candidate C1 and Session 43 (Package 2b)\n")
    md_lines.append("| Object | Variant | Islands | Conformal (mean/p95/max) | Planar Conf | Straight % | Intra Overlaps | Seam Cross | Extra Verts | Time (s) |")
    md_lines.append("| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | ---: |")

    for name, r in results.items():
        rt_m = r['round_trip']['metrics']
        c_m = r['core_metrics']
        c1 = r['c1_metrics']
        s43 = r.get('s43_metrics', {})
        s43_rt = s43.get('round_trip', {}).get('metrics', {})

        st_rt = f"{rt_m['straight']:.1f}%" if rt_m['straight'] is not None else "n/a"
        pl_rt = f"{rt_m['planar_c']:.3f}" if rt_m['planar_c'] is not None else "n/a"

        # Round-trip unwrap row (Package 2c)
        md_lines.append(
            f"| `{name}` | **Pkg 2c (Blender Unwrap)** | {rt_m['islands']:,} | "
            f"{rt_m['c_mean']:.3f}/{rt_m['c_p95']:.3f}/{rt_m['c_max']:.3f} | "
            f"{pl_rt} | {st_rt} | {rt_m['intra_overlaps']} | {rt_m['cross_outside_stubs']} | "
            f"{rt_m['render_extra_vs_normals']:,} | {r['core_time']:.2f} |"
        )

        # Core layout row (Package 2c)
        st_c = f"{c_m['straight']:.1f}%" if c_m['straight'] is not None else "n/a"
        pl_c = f"{c_m['planar_c']:.3f}" if c_m['planar_c'] is not None else "n/a"
        md_lines.append(
            f"| | Pkg 2c (Core Layout) | {c_m['islands']:,} | "
            f"{c_m['c_mean']:.3f}/{c_m['c_p95']:.3f}/{c_m['c_max']:.3f} | "
            f"{pl_c} | {st_c} | {c_m['intra_overlaps']} | {c_m['cross_outside_stubs']} | "
            f"{c_m['render_extra_vs_normals']:,} | {c_m['time']:.2f} |"
        )

        # Session 43 (Package 2b Blender Unwrap) row
        if s43_rt:
            st_s43 = f"{s43_rt['straight']:.1f}%" if s43_rt.get('straight') is not None else "n/a"
            pl_s43 = f"{s43_rt['planar_c']:.3f}" if s43_rt.get('planar_c') is not None else "n/a"
            md_lines.append(
                f"| | Session 43 (Pkg 2b RT) | {s43_rt['islands']:,} | "
                f"{s43_rt['c_mean']:.3f}/{s43_rt['c_p95']:.3f}/{s43_rt['c_max']:.3f} | "
                f"{pl_s43} | {st_s43} | {s43_rt.get('intra_overlaps', 'n/a')} | {s43_rt.get('cross_outside_stubs', 'n/a')} | "
                f"{s43_rt.get('render_extra_vs_normals', 'n/a')} | {s43.get('core_time', 0.0):.2f} |"
            )

        # Candidate C1 row
        if c1:
            st_c1 = f"{c1['straight']:.1f}%" if c1.get('straight') is not None else "n/a"
            pl_c1 = f"{c1['planar_c']:.3f}" if c1.get('planar_c') is not None else "n/a"
            md_lines.append(
                f"| | Candidate C1 | {c1['islands']:,} | "
                f"{c1['c_mean']:.3f}/{c1['c_p95']:.3f}/{c1['c_max']:.3f} | "
                f"{pl_c1} | {st_c1} | {c1['overlaps']} | {c1['cross_outside_stubs']} | "
                f"{c1['render_extra_vs_normals']:,} | {c1['time']:.2f} |"
            )

    md_lines.append("\n## Table 3: Decision 49 Fallbacks & Island Costs\n")
    md_lines.append("| Object | Fallback Cuts | Fallback Seed | Gate Repaired | Gate Rounds | Islands (Pkg 2c) | Islands (C1) | Island Cost vs C1 |")
    md_lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")

    for name, r in results.items():
        c1 = r['c1_metrics']
        c1_isl = c1['islands'] if c1 else "n/a"
        p2c_isl = r['round_trip']['core_charts_count']
        diff_isl = f"{p2c_isl - c1_isl:+d}" if isinstance(c1_isl, int) else "n/a"
        md_lines.append(
            f"| `{name}` | {r['fallback_cuts']} | {r['fallback_seed']} | "
            f"{r['gate_repaired']} | {r['gate_rounds']} | **{p2c_isl}** | {c1_isl} | {diff_isl} |"
        )

    md_lines.append("\n## Table 4: Trial Unwrap Speedup with Temporary Scene\n")
    md_lines.append("| Object | Time with Temp Scene (s) | Time without Temp Scene (s) | Speedup Factor |")
    md_lines.append("| :--- | :---: | :---: | :---: |")
    for name, s in speed_results.items():
        md_lines.append(f"| `{name}` | **{s['with_temp_scene']:.2f}** | {s['without_temp_scene']:.2f} | **{s['speedup']:.2f}x** |")

    md_path = WORK_DIR / 'measure_real_report.md'
    with open(md_path, 'w') as f:
        f.write("\n".join(md_lines))
    print(f"\nSaved Markdown report to {md_path}")
    print("\n" + "\n".join(md_lines))


if __name__ == '__main__':
    main()
