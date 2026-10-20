"""
Runner and benchmark for real-mesh auto-seam proposal (Package 2b).

Runs propose(obj) from fss_blender_tools.uv_autoseam across:
1. The 17 original objects from tests/_work/uv_autoseam/package2b/E2_COCKPIT2_copy.blend
2. Mirror / Array objects from that file
3. A synthetic shared-mesh case with non-uniform scale

Verifies:
- 0 diagonal cuts (decision 48 / no_cut)
- Round-trip check in Blender uv.unwrap: island equality with core charts and 0 intra-island overlaps
- Session 17 shape criteria evaluation
- Timing speedup with temporary scene vs full-scene baseline
- Full state restoration
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

WORK_DIR = REPO_ROOT / 'tests' / '_work' / 'uv_autoseam' / 'package2b'
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

PKG2_SUMMARY_PATH = REPO_ROOT / 'tests' / '_work' / 'uv_autoseam' / 'package2' / 'measure_real_summary.json'
PKG2_DATA = {}
if PKG2_SUMMARY_PATH.exists():
    try:
        with open(PKG2_SUMMARY_PATH) as f:
            PKG2_DATA = json.load(f)
    except Exception as e:
        print(f"Warning: could not load Package 2 summary: {e}")

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

    # Compute intra-island overlaps:
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
    """Perform round-trip check on a copy of the original mesh.

    Writes artist seams plus proposed seams onto copy_me, executes
    Blender uv.unwrap(method='ANGLE_BASED', fill_holes=False, correct_aspect=True, margin 0),
    checks island equality against core charts, evaluates intra-island overlaps
    and Session 17 shape criteria.
    """
    orig_me = o.data
    copy_me = orig_me.copy()
    copy_me.name = f"__fss_rt_{orig_me.name}__"

    # Set seams: artist seams + proposed edges
    orig_seams = np.zeros(len(copy_me.edges), bool)
    orig_me.edges.foreach_get('use_seam', orig_seams)
    for idx in prop_edges:
        orig_seams[idx] = True
    for e, s in zip(copy_me.edges, orig_seams):
        e.use_seam = bool(s)

    copy_obj = bpy.data.objects.new(f"__fss_rt_obj_{o.name}__", copy_me)
    orig_scene = bpy.context.scene
    temp_scene = bpy.data.scenes.new(f"__fss_rt_temp_{o.name}__")

    try:
        temp_scene.collection.objects.link(copy_obj)
        bpy.context.window.scene = temp_scene
        temp_scene.view_layers[0].objects.active = copy_obj
        copy_obj.select_set(True)

        uvl = copy_me.uv_layers.new(name="UVMap")
        copy_me.uv_layers.active = uvl
        bpy.ops.object.mode_set(mode='EDIT')
        ts = bpy.context.scene.tool_settings
        ts.use_uv_select_sync = True
        ts.mesh_select_mode = (False, False, True)

        bm = bmesh.from_edit_mesh(copy_me)
        for f in bm.faces:
            f.select = True
            for v in f.verts:
                v.select = True
            for e in f.edges:
                e.select = True
        bmesh.update_edit_mesh(copy_me, loop_triangles=False, destructive=False)

        # Blender unwrap Angle Based
        bpy.ops.uv.unwrap(method='ANGLE_BASED', fill_holes=False, correct_aspect=True, margin_method='FRACTION', margin=0.0)
        bpy.ops.object.mode_set(mode='OBJECT')

        # 1. Connected components of original polygons partitioned by seams
        bm_islands = bmesh.new()
        bm_islands.from_mesh(copy_me)
        bm_islands.edges.ensure_lookup_table()
        bm_islands.faces.ensure_lookup_table()

        par = list(range(len(bm_islands.faces)))
        def find(i):
            while par[i] != i:
                par[i] = par[par[i]]
                i = par[i]
            return i

        for e in bm_islands.edges:
            if not e.seam and len(e.link_faces) == 2:
                f0, f1 = e.link_faces[0].index, e.link_faces[1].index
                if bm_islands.faces[f0].material_index == bm_islands.faces[f1].material_index:
                    r0, r1 = find(f0), find(f1)
                    if r0 != r1:
                        par[r0] = r1

        groups = {}
        for i in range(len(bm_islands.faces)):
            groups.setdefault(find(i), set()).add(i)
        mesh_islands = [frozenset(s) for s in groups.values()]
        bm_islands.free()

        # Check equality against core_chart_polys
        core_charts = rep['core_chart_polys']
        sorted_mesh = sorted(mesh_islands, key=lambda s: (len(s), sorted(s)))
        sorted_core = sorted(core_charts, key=lambda s: (len(s), sorted(s)))
        islands_equal = (sorted_mesh == sorted_core)

        # 2. Triangulate copy_me for Session 17 evaluation and intra-island overlaps
        bm_tri = bmesh.new()
        bm_tri.from_mesh(copy_me)
        poly_layer = bm_tri.faces.layers.int.new('__orig_poly__')
        for f in bm_tri.faces:
            f[poly_layer] = f.index
        bmesh.ops.triangulate(bm_tri, faces=bm_tri.faces[:])

        # Apply matrix_world to vertices for proper 3D scale and orientation
        P_local = np.array([v.co[:] for v in bm_tri.verts], dtype=np.float64)
        mat = np.array(o.matrix_world, dtype=np.float64)
        P = (np.c_[P_local, np.ones(len(P_local))] @ mat.T)[:, :3]

        T = np.array([[v.index for v in f.verts] for f in bm_tri.faces], dtype=np.int64)
        tri_orig_poly = np.array([f[poly_layer] for f in bm_tri.faces], dtype=np.int64)

        uv_data = bm_tri.loops.layers.uv.active
        UV = np.array([[l[uv_data].uv[:] for l in f.loops] for f in bm_tri.faces], dtype=np.float64)

        # Per-triangle island label based on the mesh_islands partition
        poly_to_island = {}
        for isl_idx, polys in enumerate(mesh_islands):
            for p in polys:
                poly_to_island[p] = isl_idx
        tri_labels = np.array([poly_to_island[p] for p in tri_orig_poly], dtype=np.int64)

        # NT from rep['NT'] and SE from rep['SE']
        NT = rep['NT']
        SE = rep['SE']
        bm_tri.free()

        # Evaluate shape criteria on Blender's unwrap
        metrics = evaluate_shape(P, T, UV, NT, SE, labels=tri_labels)

        return {
            'islands_equal': islands_equal,
            'mesh_islands_count': len(mesh_islands),
            'core_charts_count': len(core_charts),
            'metrics': metrics,
            'blender_UV': UV,
        }

    finally:
        bpy.context.window.scene = orig_scene
        if temp_scene.name in bpy.data.scenes:
            bpy.data.scenes.remove(temp_scene)
        if copy_obj.name in bpy.data.objects:
            bpy.data.objects.remove(copy_obj, do_unlink=True)
        if copy_me.name in bpy.data.meshes:
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
    print(f"RUNNING PACKAGE 2b: NO DIAGONAL CUTS, ROUND TRIP & SPEED ({len(all_objects)} objects)")
    print(f"================================================================================\n")

    for cat, o in all_objects:
        obj_name = o.name
        print(f"Processing [{cat}] {obj_name} (mesh: {o.data.name})...", flush=True)

        snap = snapshot_object_state(o)
        t_start = time.perf_counter()

        # Propose with temporary scene and measurement arrays
        prop_edges, diag_cuts, rep = uv_autoseam.propose(
            o, cache=mesh_cache, measurement_arrays=True, use_temp_scene=True
        )
        elapsed = time.perf_counter() - t_start

        # State restoration assertion
        assert_object_restored(o, snap)

        # Evaluate Core metrics (on rep['UV'])
        core_met = evaluate_shape(rep['P'], rep['T'], rep['UV'], rep['NT'], rep['SE'])
        core_met['time'] = rep['time']

        # Execute Round Trip check on copy of original mesh
        rt_result = run_round_trip(o, prop_edges, rep)

        # Baseline comparisons
        c1_key = 'W_' + obj_name
        c1_ref = C1_DATA.get(c1_key, {}).get('c1')
        pkg2_ref = PKG2_DATA.get(obj_name)

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
            'c1_metrics': c1_ref,
            'pkg2_metrics': pkg2_ref,
            'restore_pass': True,
        }

        rt_m = rt_result['metrics']
        print(
            f"  -> Done in {elapsed:.2f}s: prop={len(prop_edges)}, diag_cuts={diag_cuts}, "
            f"core_isl={rt_result['core_charts_count']}, rt_isl={rt_result['mesh_islands_count']}, "
            f"equal={rt_result['islands_equal']}, rt_ov={rt_m['intra_overlaps']}, core_ov={core_met['intra_overlaps']}, "
            f"C95={rt_m['c_p95']:.4f}"
        )

    # Speed benchmark: measure with and without temporary scene on selected objects
    print("\n--- Running Speed Benchmark (With vs Without Temporary Scene) ---")
    speed_results = {}
    for name in SPEED_TEST_OBJECTS:
        o = bpy.data.objects.get(name)
        if not o:
            continue
        print(f"Testing speed on {name}...", flush=True)

        # Time with temp scene (already measured or fresh)
        t0 = time.perf_counter()
        _, _, rep_with = uv_autoseam.propose(o, measurement_arrays=False, use_temp_scene=True)
        t_with = rep_with['time']

        # Time without temp scene
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
    md_lines.append("# Package 2b: No Diagonal Cuts, Round Trip, Speed Report\n")
    md_lines.append(f"- **Date:** {time.strftime('%Y-%m-%d %H:%M:%S')}")
    md_lines.append(f"- **Blend file:** `{BLEND_PATH.name}`")
    md_lines.append(f"- **Total objects tested:** {len(all_objects)}\n")

    md_lines.append("## Table 1: Mesh Topology, Diagonals, Seams, Round Trip, and Core Time\n")
    md_lines.append("| Object | Category | Modifiers | Topo Match | Faces (Orig/Tri) | Diagonals | Diag Cuts | Proposed Edges | Core Islands | RT Equal? | RT Overlaps | Core Time (s) |")
    md_lines.append("| :--- | :--- | :--- | :---: | :---: | ---: | :---: | ---: | :---: | :---: | :---: | ---: |")

    for name, r in results.items():
        mods = ", ".join(r['modifiers']) if r['modifiers'] else "none"
        topo = "yes" if r['eval_topology_matches'] else "no"
        faces = f"{r['faces_before']} / {r['faces_after']}"
        rt = r['round_trip']
        rt_eq = "yes" if rt['islands_equal'] else "no"
        ov = rt['metrics']['intra_overlaps']
        md_lines.append(
            f"| `{name}` | {r['category']} | {mods} | {topo} | {faces} | "
            f"{r['diagonals_total']:,} | **{r['diagonal_cuts_count']}** | {r['proposed_edges_count']:,} | "
            f"{rt['core_charts_count']} | **{rt_eq}** | {ov} | {r['core_time']:.2f} |"
        )

    md_lines.append("\n## Table 2: Comparison against Candidate C1 and Session 41\n")
    md_lines.append("| Object | Variant | Islands | Conformal (mean/p95/max) | Planar Conf | Straight % | Intra Overlaps | Seam Cross | Extra Verts | Time (s) |")
    md_lines.append("| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | ---: |")

    for name, r in results.items():
        rt_m = r['round_trip']['metrics']
        c_m = r['core_metrics']
        c1 = r['c1_metrics']
        p2 = r.get('pkg2_metrics', {}).get('real_metrics')

        st_rt = f"{rt_m['straight']:.1f}%" if rt_m['straight'] is not None else "n/a"
        pl_rt = f"{rt_m['planar_c']:.3f}" if rt_m['planar_c'] is not None else "n/a"

        # Round-trip unwrap row
        md_lines.append(
            f"| `{name}` | **Pkg 2b (Blender Unwrap)** | {rt_m['islands']:,} | "
            f"{rt_m['c_mean']:.3f}/{rt_m['c_p95']:.3f}/{rt_m['c_max']:.3f} | "
            f"{pl_rt} | {st_rt} | {rt_m['intra_overlaps']} | {rt_m['cross_outside_stubs']} | "
            f"{rt_m['render_extra_vs_normals']:,} | {r['core_time']:.2f} |"
        )

        # Core layout row
        st_c = f"{c_m['straight']:.1f}%" if c_m['straight'] is not None else "n/a"
        pl_c = f"{c_m['planar_c']:.3f}" if c_m['planar_c'] is not None else "n/a"
        md_lines.append(
            f"| | Pkg 2b (Core Layout) | {c_m['islands']:,} | "
            f"{c_m['c_mean']:.3f}/{c_m['c_p95']:.3f}/{c_m['c_max']:.3f} | "
            f"{pl_c} | {st_c} | {c_m['intra_overlaps']} | {c_m['cross_outside_stubs']} | "
            f"{c_m['render_extra_vs_normals']:,} | {c_m['time']:.2f} |"
        )

        # Session 41 row
        if p2:
            st_p2 = f"{p2['straight']:.1f}%" if p2.get('straight') is not None else "n/a"
            pl_p2 = f"{p2['planar_c']:.3f}" if p2.get('planar_c') is not None else "n/a"
            md_lines.append(
                f"| | Session 41 (Pkg 2) | {p2['islands']:,} | "
                f"{p2['c_mean']:.3f}/{p2['c_p95']:.3f}/{p2['c_max']:.3f} | "
                f"{pl_p2} | {st_p2} | 0* | {p2['cross_outside_stubs']} | "
                f"{p2['render_extra_vs_normals']:,} | {p2['time']:.2f} |"
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

    md_lines.append("\n## Table 3: Trial Unwrap Speedup with Temporary Scene\n")
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
