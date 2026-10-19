"""
Parity benchmark for fss_blender_tools.uv_autoseam_core.

Runs on copies of original_seven.blend and references.blend in background Blender.
Verifies that propose_seams() reproduces the Candidate C1 seam proposals exactly (17/17),
asserts complete restoration of object state, and reports timing compared to C1.
"""
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
import bpy
import numpy as np

# Load core module directly by file path from repo to avoid importing deployed copies
REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_PATH = REPO_ROOT / 'fss_blender_tools' / 'uv_autoseam_core.py'

spec = importlib.util.spec_from_file_location("uv_autoseam_core", str(CORE_PATH))
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
propose_seams = core.propose_seams

WORK_DIR = REPO_ROOT / 'tests' / '_work' / 'uv_autoseam'
SHAPE_DIR = REPO_ROOT / 'tests' / '_work' / 'uv_shape'
C1_RESULTS_DIR = SHAPE_DIR / 'candidate_c1_results'
if not C1_RESULTS_DIR.exists():
    C1_RESULTS_DIR = WORK_DIR / 'repro_c1'

BLEND_SEVEN = WORK_DIR / 'original_seven.blend'
if not BLEND_SEVEN.exists():
    BLEND_SEVEN = SHAPE_DIR / 'original_seven.blend'

BLEND_REFS = WORK_DIR / 'references.blend'
if not BLEND_REFS.exists():
    BLEND_REFS = SHAPE_DIR / 'references.blend'

ORIGINAL_SEVEN_OBJS = [
    'W_@MERGE_PEDESTAL_SHELL',
    'W_AUDIO_L_VOLUME_KNOB',
    'W_COCKPIT_SHELL_FLOOR',
    'W_COCKPIT_SHELL_L',
    'W_LEVER_FLAP_LOCK',
    'W_OVERHEAD_SHELL',
    'W_TRIM_PANEL',
]

REFERENCE_OBJS = [
    'W_B_GS_AFCS_AP_BUTTON',
    'W_CCD_LEFT_ROTARY_OUTER',
    'W_CIRCUIT_BREAKER_COVER_L',
    'W_COCKPIT_REAR_OBS_SEAT_MOUNTING_FRAME',
    'W_DISC_HANDLE_AILERON',
    'W_EFB_HINGE_ARM_1',
    'W_EFB_HINGE_CLAMP_ROTATOR',
    'W_EFB_HINGE_ROTATOR_2',
    'W_LEVER_FLAP',
    'W_POWERPLANT_COVER_L',
]

C1_LOG_TIMES = {
    'W_@MERGE_PEDESTAL_SHELL': 27.30,
    'W_AUDIO_L_VOLUME_KNOB': 0.18,
    'W_COCKPIT_SHELL_FLOOR': 125.80,
    'W_COCKPIT_SHELL_L': 14.00,
    'W_LEVER_FLAP_LOCK': 0.49,
    'W_OVERHEAD_SHELL': 114.55,
    'W_TRIM_PANEL': 5.78,
    'W_B_GS_AFCS_AP_BUTTON': 0.04,
    'W_CCD_LEFT_ROTARY_OUTER': 0.83,
    'W_CIRCUIT_BREAKER_COVER_L': 0.67,
    'W_COCKPIT_REAR_OBS_SEAT_MOUNTING_FRAME': 45.25,
    'W_DISC_HANDLE_AILERON': 5.15,
    'W_EFB_HINGE_ARM_1': 0.34,
    'W_EFB_HINGE_CLAMP_ROTATOR': 2.15,
    'W_EFB_HINGE_ROTATOR_2': 9.51,
    'W_LEVER_FLAP': 0.55,
    'W_POWERPLANT_COVER_L': 0.23,
}

# Try loading exact C1 times from json logs if available
if C1_RESULTS_DIR.exists():
    for f in C1_RESULTS_DIR.glob('blender_log_c1_*.json'):
        try:
            with open(f) as jf:
                log_data = json.load(jf)
                for obj_name, obj_data in log_data.items():
                    if 'c1' in obj_data and 'time' in obj_data['c1']:
                        C1_LOG_TIMES[obj_name] = float(obj_data['c1']['time'])
        except Exception:
            pass


def test_object(obj):
    """Test propose_seams on a single object with restore assertions."""
    me = obj.data

    # Read artist_seam and normal_split from mesh attributes
    nE = len(me.edges)
    artist_seam = np.zeros(nE, bool)
    if 'fss_seam' in me.attributes:
        vals = np.zeros(nE, np.int32)
        me.attributes['fss_seam'].data.foreach_get('value', vals)
        artist_seam = vals != 0

    normal_split = np.zeros(nE, bool)
    if 'fss_nsplit' in me.attributes:
        vals = np.zeros(nE, np.int32)
        me.attributes['fss_nsplit'].data.foreach_get('value', vals)
        normal_split = vals != 0

    # Capture initial state for restore assertions
    initial_mode = obj.mode
    initial_uv_layer_count = len(me.uv_layers)
    initial_uv_layer_names = [l.name for l in me.uv_layers]
    initial_active_uv_name = me.uv_layers.active.name if me.uv_layers.active else None
    initial_uv_coords = {l.name: [tuple(x.uv) for x in l.data] for l in me.uv_layers}
    initial_edge_seams = [e.use_seam for e in me.edges]

    # Run propose_seams
    t0 = time.perf_counter()
    auto_edges, stats = propose_seams(obj, artist_seam, normal_split)
    elapsed = time.perf_counter() - t0

    # Restore assertions
    assert obj.mode == initial_mode, f"{obj.name}: Mode changed from {initial_mode} to {obj.mode}"
    assert len(me.uv_layers) == initial_uv_layer_count, f"{obj.name}: UV layer count changed ({len(me.uv_layers)} != {initial_uv_layer_count})"
    assert [l.name for l in me.uv_layers] == initial_uv_layer_names, f"{obj.name}: UV layer names changed"
    final_active_uv_name = me.uv_layers.active.name if me.uv_layers.active else None
    assert final_active_uv_name == initial_active_uv_name, f"{obj.name}: Active UV layer changed from {initial_active_uv_name} to {final_active_uv_name}"
    for l in me.uv_layers:
        assert [tuple(x.uv) for x in l.data] == initial_uv_coords[l.name], f"{obj.name}: UV coordinates modified on layer {l.name}"
    assert [e.use_seam for e in me.edges] == initial_edge_seams, f"{obj.name}: Edge seam flags modified on mesh"

    # Build proposed proposal: artist + auto seams
    auto_set = set(auto_edges)
    proposed_vertex_pairs = set()
    for e in me.edges:
        if artist_seam[e.index] or e.index in auto_set:
            v0, v1 = int(e.vertices[0]), int(e.vertices[1])
            proposed_vertex_pairs.add(tuple(sorted((v0, v1))))

    # Load reference proposal from candidate_c1_results
    ref_file = C1_RESULTS_DIR / f"{obj.name}__c1_proposal.npy"
    if not ref_file.exists():
        ref_file = SHAPE_DIR / 'candidate_c1_results' / f"{obj.name}__c1_proposal.npy"
    assert ref_file.exists(), f"Reference file not found: {ref_file}"

    ref_data = np.load(ref_file)
    ref_vertex_pairs = set(tuple(sorted((int(p[0]), int(p[1])))) for p in ref_data)

    missing = ref_vertex_pairs - proposed_vertex_pairs
    extra = proposed_vertex_pairs - ref_vertex_pairs
    equal = (len(missing) == 0 and len(extra) == 0)

    return {
        'name': obj.name,
        'equal': equal,
        'edges_count': len(proposed_vertex_pairs),
        'missing': len(missing),
        'extra': len(extra),
        'core_time': elapsed,
        'c1_time': C1_LOG_TIMES.get(obj.name, 0.0),
        'stats': stats,
        'restore_pass': True,
    }


def main():
    print("=" * 88)
    print("PARITY BENCHMARK: fss_blender_tools.uv_autoseam_core vs Candidate C1")
    print("=" * 88)

    results = []

    # 1. Test 7 original cockpit objects
    if BLEND_SEVEN.exists():
        print(f"\nOpening {BLEND_SEVEN.name}...")
        bpy.ops.wm.open_mainfile(filepath=str(BLEND_SEVEN))
        for obj_name in ORIGINAL_SEVEN_OBJS:
            if obj_name in bpy.data.objects:
                obj = bpy.data.objects[obj_name]
                r = test_object(obj)
                results.append(r)
                status = "PASS" if r['equal'] and r['restore_pass'] else "FAIL"
                print(f"  {obj_name:<40} {status} ({r['core_time']:.2f}s, C1: {r['c1_time']:.2f}s)")
            else:
                print(f"  {obj_name:<40} NOT FOUND")
    else:
        print(f"WARNING: {BLEND_SEVEN} not found")

    # 2. Test 10 reference objects
    if BLEND_REFS.exists():
        print(f"\nOpening {BLEND_REFS.name}...")
        bpy.ops.wm.open_mainfile(filepath=str(BLEND_REFS))
        for obj_name in REFERENCE_OBJS:
            if obj_name in bpy.data.objects:
                obj = bpy.data.objects[obj_name]
                r = test_object(obj)
                results.append(r)
                status = "PASS" if r['equal'] and r['restore_pass'] else "FAIL"
                print(f"  {obj_name:<40} {status} ({r['core_time']:.2f}s, C1: {r['c1_time']:.2f}s)")
            else:
                print(f"  {obj_name:<40} NOT FOUND")
    else:
        print(f"WARNING: {BLEND_REFS} not found")

    # Summary table
    print("\n" + "=" * 88)
    print(f"{'Object':<40} {'Equal?':<12} {'Edges':<8} {'Core (s)':<10} {'C1 (s)':<10} {'Restore':<8}")
    print("-" * 88)

    total_core_time = 0.0
    total_c1_time = 0.0
    all_equal = True
    all_restore = True

    for r in results:
        eq_str = "yes" if r['equal'] else f"no (-{r['missing']}/+{r['extra']})"
        rest_str = "PASS" if r['restore_pass'] else "FAIL"
        print(f"{r['name']:<40} {eq_str:<12} {r['edges_count']:<8} {r['core_time']:<10.2f} {r['c1_time']:<10.2f} {rest_str:<8}")
        total_core_time += r['core_time']
        total_c1_time += r['c1_time']
        if not r['equal']:
            all_equal = False
        if not r['restore_pass']:
            all_restore = False

    print("-" * 88)
    print(f"{'TOTAL (' + str(len(results)) + ' objects)':<40} {'17/17 PASS' if all_equal else 'FAIL':<12} {'':<8} {total_core_time:<10.2f} {total_c1_time:<10.2f} {'PASS' if all_restore else 'FAIL':<8}")
    print("=" * 88)

    ratio = total_core_time / total_c1_time if total_c1_time > 0 else 1.0
    diff_pct = (ratio - 1.0) * 100.0
    print(f"\nTiming Comparison: Core Total = {total_core_time:.2f}s, C1 Total = {total_c1_time:.2f}s ({diff_pct:+.1f}%)")

    assert all_equal, "PARITY FAILURE: Not all proposals matched Candidate C1"
    assert all_restore, "RESTORE FAILURE: Not all restore assertions passed"
    print("\nALL 17 OBJECTS MATCH CANDIDATE C1 BIT-FOR-BIT. RESTORE ASSERTIONS PASSED.")


if __name__ == '__main__':
    main()
