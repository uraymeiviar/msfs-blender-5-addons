"""The AO Baker's step (c) in Blender (OptiX baker journal 20261114.optix-baker.md; Glider plan
PLAN-20261114.optix-ao-baker.md, step (c), finish lines 1 and 3): occluders, poses, shared-mesh copies and the falloff
from the add-on's own job items. The runner's bake_item, setup_copies and pose_setup are replicated here as arrays (the
scene block: occluder meshes in bake space, one view per pose and copy with its samples and its occluders); no add-on
file is changed.

- The AO suite's scene (test_ao_bake.build_scene, in tests/_work/ao_baker_scenes/): every item bakes and composes
  without error (its views, occluders and time reported); the shared mesh's master in Average, Lightest and Darkest
  and the wheel's 8 poses (test_ao_bake.build_wheel_scene, a posed occluder) equal, byte for byte per tile, the
  combination of their single-view bakes (finish line 1); with the falloff on, a master is not darker than without.
- With --cockpit: the 10 masters of the 1024-sample log on the copy of the E2 cockpit in tests/_work/ao_baker_cycles/
  (never the original), each at the AO distance, falloff, sample split, combine and (without copies) occluder list
  its Cycles master was baked with (read from the real bake folder's index, its files copied into
  tests/_work/ao_baker_scenes/real/ first; a copy's occluders are not in the index and come from the file): time,
  peak memory and the difference from the Cycles master (finish line 3).

    C:\\Users\\uray\\.claude\\tools\\cpucap\\cpucap.exe 50 G:\\e-jets-e2\\tools\\blender\\blender.exe -b --factory-startup
        --python tests\\test_ao_baker_scenes.py -- --exe F:\\glider\\out\\bin\\x64\\Release\\aobaker.exe [--out r.json]
    (the same with tests\\_work\\ao_baker_cycles\\COCKPIT.blend before --python, and --cockpit, for the cockpit)
"""
import argparse
import ctypes
import json
import os
import shutil
import sys
import time
from ctypes import wintypes
from pathlib import Path

import bpy
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_ao_bake as tb  # noqa: E402  (purges the deployed add-ons, imports this repository's)
from fss_blender_tools import ao_bake_core as core, ao_bake_store as store  # noqa: E402
import ao_baker_master as bm  # noqa: E402
from test_ao_baker_static import Baker, check, RESULTS  # noqa: E402

WORK = tb.REPO_ROOT / 'tests' / '_work' / 'ao_baker_scenes'
COCKPIT_WORK = tb.REPO_ROOT / 'tests' / '_work' / 'ao_baker_cycles'
REAL_BAKE = Path(r'G:\e-jets-e2\assets\visual\cockpit\COCKPIT.bake')  # read only: its files are copied first
LOG_MASTERS = ('MESH_SEAT_HEADREST_PILOT', 'MESH_SEAT_BACK_SHELL_PILOT', 'SEAT_OBS', 'SEAT_OBS_SIT_FOAM',
               'SEAT_CUSHION_GUSSET_PILOT', 'YOKE_BASE_PILOT', 'YOKE_BASE_COPILOT', 'SEAT_CUSHION_GUSSET_COPILOT',
               'MESH_SEAT_ARMREST_RT_PILOT.001', 'MESH_SEAT_ARMREST_LT_PILOT.001')
GB = 2 ** 30


def args_after_dashes():
    ap = argparse.ArgumentParser()
    ap.add_argument('--exe', required=True)
    ap.add_argument('--cockpit', action='store_true')
    ap.add_argument('--only', help='cockpit masters by name, comma separated')
    ap.add_argument('--copies-self', action='store_true', help="a shared mesh's copies without occluders")
    ap.add_argument('--out')
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    return ap.parse_args(argv)


def process_peak(pid):
    """(working set, peak working set) of another process in bytes, or (None, None)."""

    class PMC(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD),
                    ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t),
                    ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t), ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                    ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t)]
    k32 = ctypes.windll.kernel32
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
    k32.K32GetProcessMemoryInfo.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    query_limited = 0x1000
    h = k32.OpenProcess(query_limited, False, int(pid))
    out = (None, None)
    if h:
        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        if k32.K32GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
            out = (int(pmc.WorkingSetSize), int(pmc.PeakWorkingSetSize))
        k32.CloseHandle(h)
    return out


# ---------------------------------------------------------------------------------------------------------------------
# The runner's bake_item as a scene (ao_bake_runner.py: bake_item, occluder_mesh, pose_setup, setup_copies)
# ---------------------------------------------------------------------------------------------------------------------

def prepare(job, item):
    """bake_item's steps up to the layout, on this Blender's file: (obj, pos, tris, cnm, m, dist, shift, ref_co)."""
    SET = job['settings']
    if item.get('frame') is not None:
        bpy.context.scene.frame_set(int(item['frame']))
    obj = bpy.data.objects[item['object']]
    dist = float(item.get('ao_distance', SET['ao_distance']))
    dg = bpy.context.evaluated_depsgraph_get()
    uv_name = item['uv']
    ev = core.evaluated_triangles(obj, dg, [uv_name])
    sizes = item['tex_size']
    skip = set(item['skip_slots'])
    sel = np.array([(m not in skip) and (str(int(m)) in sizes) for m in ev['mat'].tolist()], dtype=bool)
    tri_src = np.nonzero(sel)[0]
    pos_w, _ = core.to_world(ev)
    used = np.unique(ev['tris'][tri_src])
    lo, hi = pos_w[used].min(axis=0), pos_w[used].max(axis=0)
    shift = (lo + hi) / 2
    pos, cn = core.to_world(ev, shift)
    tris = ev['tris'][tri_src]
    cnm = cn[tri_src]
    size = np.array([float(sizes[str(int(m))]) for m in ev['mat'][tri_src]])
    uvpx = ev['uv'][uv_name][tri_src] * size[:, None, None]
    D = core.master_density(pos, tris, uvpx)
    m = bm.layout(core, pos, tris, cnm, D)
    return obj, pos, tris, cnm, m, dist, shift, ev['co']


def occluder_arrays(o, dg, skip_slots, shift):
    """occluder_mesh as arrays: the evaluated mesh without its skip faces, in bake space (world moved by -shift)."""
    ev = core.evaluated_triangles(o, dg)
    pos, _cn = core.to_world(ev, shift)
    keep = ~np.isin(ev['mat'], list(skip_slots)) if skip_slots else np.ones(len(ev['tris']), dtype=bool)
    return pos.astype(np.float32), ev['tris'][keep].astype(np.uint32)


def bake_matrices(shift):
    to_bake = np.eye(4)
    to_bake[:3, 3] = -shift
    from_bake = np.eye(4)
    from_bake[:3, 3] = shift
    return to_bake, from_bake


def poses_of(obj, frames, ref_co, shift, posed, add):
    """pose_setup: per pose frame the target's placement relative to the current frame (bake space) and the indices of
    its posed occluders' meshes (add(o, skip) adds one at that frame); None when the target's mesh deforms."""
    scene = bpy.context.scene
    f0, s0 = scene.frame_current, scene.frame_subframe
    to_bake, from_bake = bake_matrices(shift)
    inv_ref = np.linalg.inv(np.array(obj.matrix_world, dtype=np.float64))
    out = []
    try:
        for f in frames:
            fi = int(np.floor(f))
            scene.frame_set(fi, subframe=float(f - fi))
            dg = bpy.context.evaluated_depsgraph_get()
            co = core.evaluated_triangles(obj, dg)['co']
            if co.shape != ref_co.shape or not np.allclose(co, ref_co, rtol=0.0, atol=1e-6):
                out = None
                break
            M = to_bake @ np.array(obj.matrix_world, dtype=np.float64) @ inv_ref @ from_bake
            out.append((M, [add(o, skip, dg) for o, skip in posed]))
    finally:
        scene.frame_set(f0, subframe=s0)
    return out


def item_scene(job, item):
    """The scene of a job item: dict(pos, tris, cnm, m, dist, samples, occluders, views, falloff, combine, notes)."""
    SET = job['settings']
    samples = int(SET['samples'])
    split = bool(SET.get('sample_split'))
    obj, pos, tris, cnm, m, dist, shift, ref_co = prepare(job, item)
    occluders = []

    def add(o, skip, dg=None):
        occluders.append(occluder_arrays(o, dg or bpy.context.evaluated_depsgraph_get(), skip, shift))
        return len(occluders) - 1
    views, notes = [], []
    combine = 'AVERAGE'
    if item.get('copies'):  # setup_copies (decision 47)
        combine = item.get('combine') or 'AVERAGE'
        to_bake, from_bake = bake_matrices(shift)
        inv_first = np.linalg.inv(np.array(obj.matrix_world, dtype=np.float64))
        static = {}
        for ci, c in enumerate(item['copies']):
            o = bpy.data.objects.get(c['object'])
            if o is None or o.type != 'MESH':
                notes.append(f"{c['object']}: not in the file, left out")
                continue
            X = to_bake @ np.array(o.matrix_world, dtype=np.float64) @ inv_first @ from_bake
            vis, posed = [], []
            for occ in c['occluders']:
                oc = bpy.data.objects.get(occ['name'])
                if oc is None or oc.type != 'MESH':
                    continue
                if c.get('poses') and occ.get('posed'):
                    posed.append((oc, set(occ['skip_slots'])))
                    continue
                if oc.name not in static:
                    static[oc.name] = add(oc, set(occ['skip_slots']))
                vis.append(static[oc.name])
            got = None
            if c.get('poses'):
                ref = core.evaluated_triangles(o, bpy.context.evaluated_depsgraph_get())['co']
                got = poses_of(o, c['poses'], ref, shift, posed, add)
                if got is None:
                    notes.append(f'{o.name}: its mesh deforms between poses: baked in the current frame')
            if got is None:
                vis = vis + [add(oc, skip) for oc, skip in posed]
                views.append(dict(transform=X, copy=ci, occluders=vis, cposes=1))
            else:
                for M, idx in got:
                    views.append(dict(transform=M @ X, copy=ci, occluders=vis + idx, cposes=len(got)))
        order = {c: k for k, c in enumerate(dict.fromkeys(v['copy'] for v in views))}
        for v in views:
            v['copy'] = order[v['copy']]
            share = v['cposes'] * (len(order) if combine in ('AVERAGE', 'ONE') else 1)
            v['samples'] = core.view_samples(samples, share, split)  # decision 49
    else:
        frames = item.get('poses') or None
        static, posed = [], []
        for occ in item['occluders']:
            o = bpy.data.objects.get(occ['name'])
            if o is None or o.type != 'MESH' or o == obj:
                continue
            if frames and occ.get('posed'):
                posed.append((o, set(occ['skip_slots'])))  # decision 35
                continue
            static.append(add(o, set(occ['skip_slots'])))
        got = poses_of(obj, frames, ref_co, shift, posed, add) if frames else None
        if frames and got is None:
            notes.append('its mesh deforms between poses: baked in the current frame only')
            static += [add(o, skip) for o, skip in posed]
        if got:
            vs = core.view_samples(samples, len(got), split)
            views = [dict(transform=M, copy=0, samples=vs, occluders=static + idx) for M, idx in got]
        else:
            views = [dict(transform=np.eye(4), copy=0, samples=samples, occluders=static)]
    nf = int(item.get('falloff') or 0)
    return dict(name=item['name'], key=item['key'], pos=pos, tris=tris, cnm=cnm, m=m, dist=dist, samples=samples,
                occluders=occluders, views=views, falloff=nf > 1, combine=combine, notes=notes)


def bake_scene(ch, sc, label, tile, scene_id=1, keep_scene=False, keep_rows=False):
    t = time.perf_counter()
    b = bm.bake_master(core, ch, f'{label}-{os.getpid()}', sc['pos'], sc['tris'], sc['cnm'], sc['m'], sc['dist'],
                       sc['samples'], tile, occluders=sc['occluders'], views=sc['views'], falloff=sc['falloff'],
                       combine=sc['combine'], scene_id=scene_id, keep_tiles=False, keep_rows=keep_rows,
                       keep_scene=keep_scene)
    b.seconds['wall'] = time.perf_counter() - t
    return b


def summary(sc, b):
    rays, trace, rate = bm.rays_per_second(b)
    return dict(master=f"{sc['m']['W']}x{sc['m']['H']}", views=len(sc['views']),
                copies=len({v['copy'] for v in sc['views']}), samples=sorted({v['samples'] for v in sc['views']}),
                occluder_meshes=len(sc['occluders']), occluder_tris=int(sum(len(t) for _p, t in sc['occluders'])),
                falloff=sc['falloff'], combine=sc['combine'], tiles=len(b.tiles), gpu_mb=round(b.scene['gpu_bytes'] / 2 ** 20, 1),
                scene_s=round(b.seconds['scene'], 2), trace_s=round(trace, 2), grays_per_s=round(rate / 1e9, 2),
                compose_s=round(b.seconds['compose'], 2), wall_s=round(b.seconds['wall'], 2),
                notes='; '.join(sc['notes']) or None)


# ---------------------------------------------------------------------------------------------------------------------
# The AO suite's objects
# ---------------------------------------------------------------------------------------------------------------------

def job_items(names=None):
    """The add-on's job items (store.make_job) of the named objects, or of every item."""
    tb.refresh()
    st = store._state
    stems = [st['by_object'][n] for n in names] if names else sorted(st['items'])
    path = store.make_job(bpy.context, stems)
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def combination_check(ch, sc, label, tile=512):
    """Finish line 1: the master's tiles against the combination of the single-view bakes, byte for byte."""
    sid = 40
    b = bake_scene(ch, sc, label, tile, scene_id=sid, keep_scene=True, keep_rows=True)
    try:
        grid = core.tile_grid(sc['m']['W'], sc['m']['H'], tile)
        tiles, px, da, db = bm.combination_differences(ch, sid, f'comb-{label}-{os.getpid()}', grid, sc['views'],
                                                       sc['combine'])
    finally:
        ch.release_scene(sid)
    check(f'combination-bytes-{label}', da == 0 and db == 0 and len(sc['views']) > 1, views=len(sc['views']),
          combine=sc['combine'], tiles=tiles, pixels=px, a_differing=da, b_differing=db)
    return b


def suite(ch):
    tb.WORK = WORK
    tb.BLEND = WORK / 'suite.blend'
    tb.FOLDER = WORK / 'suite.bake'
    tb.OUT = WORK / 'suite_ao'
    if WORK.exists():
        shutil.rmtree(WORK / 'suite.bake', ignore_errors=True)
    tb.build_scene()
    b_obj = bpy.data.objects['B']
    b_obj.fss_ao_bake.occluders = 'CUSTOM'
    b_obj.fss_ao_bake.custom.add().object = bpy.data.objects['O2']  # test_custom_occluders' list
    job = job_items()
    failed = []
    for item in job['items']:
        label = 'suite-' + item['name']
        try:
            sc = item_scene(job, item)
            b = bake_scene(ch, sc, label, 512)
            check(label, b.digest is not None, **summary(sc, b))
        except Exception as e:  # reported, the other items still bake
            failed.append(item['name'])
            check(label, False, error=f'{type(e).__name__}: {e}')
    # the shared mesh in each combine mode: byte for byte, and darkest <= average <= lightest
    me = bpy.data.meshes['MESH_SHARED_CUBE']
    means = {}
    for mode in ('AVERAGE', 'LIGHTEST', 'DARKEST'):
        me.fss_ao_shared.combine = mode
        job = job_items(['S1'])
        sc = item_scene(job, job['items'][0])
        b = combination_check(ch, sc, f'shared-{mode.lower()}')
        means[mode] = float(b.M16[core.code_filled(b.codes)].mean() / 65535.0)
    me.fss_ao_shared.combine = 'DEFAULT'
    check('shared-combine-order', means['DARKEST'] <= means['AVERAGE'] <= means['LIGHTEST'],
          **{k.lower(): round(v, 5) for k, v in means.items()})
    # the falloff: A over O1 is not darker with it
    s = bpy.context.scene.fss_ao_bake
    vals = {}
    for on in (False, True):
        s.falloff = on
        job = job_items(['A'])
        sc = item_scene(job, job['items'][0])
        b = bake_scene(ch, sc, f'falloff-{on}', 512, keep_rows=True)
        vals[on] = b.M16[core.code_filled(b.codes)].astype(np.float64)
    s.falloff = False
    lighter = bool(np.all(vals[True] >= vals[False] - 1)) and vals[True].mean() > vals[False].mean()
    check('falloff-not-darker', lighter, mean_off=round(float(vals[False].mean() / 65535), 5),
          mean_on=round(float(vals[True].mean() / 65535), 5),
          darker_pixels=int((vals[True] < vals[False] - 1).sum()))
    # the wheel: 8 poses, PEG posed with it, SLAB against
    tb.build_wheel_scene()
    job = job_items(['W'])
    item = job['items'][0]
    sc = item_scene(job, item)
    check('wheel-item', len(sc['views']) == 8 and len(item.get('poses') or ()) == 8, poses=item.get('poses'),
          occluders=[o['name'] for o in item['occluders']], posed=[o['name'] for o in item['occluders'] if o['posed']],
          occluder_meshes=len(sc['occluders']))
    combination_check(ch, sc, 'wheel-8-poses')
    return failed


# ---------------------------------------------------------------------------------------------------------------------
# The cockpit's 10 masters
# ---------------------------------------------------------------------------------------------------------------------

def copy_real(stem, dest):
    """The real master's files (read only) into dest; returns the image kind ('ao.raw' when a raw image exists)."""
    dest.mkdir(parents=True, exist_ok=True)
    kind = 'ao.raw' if (REAL_BAKE / f'{stem}.ao.raw.jxl').is_file() else 'ao'
    for suffix in ('.ao.map', '.ao.npz', f'.{kind}.jxl'):
        src = REAL_BAKE / f'{stem}{suffix}'
        dst = dest / f'{stem}{suffix}'
        if not dst.is_file() or dst.stat().st_size != src.stat().st_size:
            shutil.copy2(src, dst)
    return kind


def compare_cycles(label, b, cyc):
    """As test_ao_baker_cycles: over the pixels both have a value for; load_master's rows start at the bottom."""
    ours = b.M16[::-1]
    codes = b.codes[::-1]
    fill_o = core.code_filled(codes)
    both = fill_o & cyc['filled']
    d = ours[both].astype(np.float64) / 65535.0 - cyc['image'][both].astype(np.float64) / 65535.0
    a = np.abs(d)
    return dict(pixels=int(both.sum()), only_ours=int((fill_o & ~cyc['filled']).sum()),
                only_cycles=int((cyc['filled'] & ~fill_o).sum()), mean=round(float(d.mean()), 5),
                mean_abs=round(float(a.mean()), 5), p99_abs=round(float(np.percentile(a, 99)), 4),
                max_abs=round(float(a.max()), 4), share_over_0_05=round(float((a > 0.05).mean()), 5),
                ours_mean=round(float(ours[both].mean() / 65535.0), 4),
                cycles_mean=round(float(cyc['image'][both].mean() / 65535.0), 4))


def cockpit(ch, baker, only, copies_self=False):
    folder = store.bake_folder()
    assert Path(folder).resolve().is_relative_to(COCKPIT_WORK.resolve()), folder  # only the copy's bake folder
    with open(REAL_BAKE / 'index.json', encoding='utf-8') as f:
        real = {e['name']: (k, e) for k, e in json.load(f)['masters'].items()}
    s = bpy.context.scene.fss_ao_bake
    total = dict(cycles_bake_s=0.0, cycles_total_s=0.0, ours_s=0.0, trace_s=0.0, compose_s=0.0)
    for name in only or LOG_MASTERS:
        stem, entry = real[name]
        kind = copy_real(stem, WORK / 'real')
        # the settings its Cycles master was baked with
        s.distance = float(entry['ao_distance'])
        s.falloff = bool(entry.get('falloff'))
        if entry.get('falloff'):
            s.falloff_steps = int(entry['falloff'])
        s.samples = int(entry['samples'])
        s.sample_quality = 'SPLIT' if entry.get('sample_split') else 'FULL'
        mesh = bpy.data.objects[entry['object']].data
        if entry.get('combine') and hasattr(mesh, 'fss_ao_shared'):
            mesh.fss_ao_shared.combine = entry['combine']  # the copies as its Cycles master combined them
        tb.refresh()
        st = store._state
        obj_name = entry['object']
        mine = st['by_object'].get(obj_name)
        if mine is None:
            check(f'cockpit-{name}', False, error=f'{obj_name}: no item in the copy')
            continue
        path = store.make_job(bpy.context, [mine])
        with open(path, encoding='utf-8') as f:
            job = json.load(f)
        item = job['items'][0]
        item['ao_distance'] = float(entry['ao_distance'])
        if not item.get('copies'):  # the occluders its Cycles master was baked with (the index's list)
            item['occluders'] = [dict(name=n, skip_slots=list(store.skip_slots(bpy.data.objects[n])), posed=False)
                                 for n in entry.get('occluders') or () if n in bpy.data.objects]
        elif copies_self:  # the index does not list a copy's occluders: each copy alone, as a check of the setup
            for c in item['copies']:
                c['occluders'] = []
        sc = item_scene(job, item)
        b = bake_scene(ch, sc, f'cockpit-{len(total)}', 2048, keep_rows=True)
        _ws, peak = core.process_memory()
        _bws, bpeak = process_peak(baker.proc.pid)
        cyc = core.load_master(str(WORK / 'real'), stem, kind=kind)
        same = cyc is not None and (cyc['W'], cyc['H']) == (sc['m']['W'], sc['m']['H'])
        info = summary(sc, b)
        times = entry.get('times') or {}
        info.update(cycles_bake_s=times.get('bake_s'), cycles_total_s=times.get('total_s'),
                    speedup_bake=round(times['bake_s'] / max(b.seconds['wall'], 1e-9), 1) if times.get('bake_s') else None,
                    cycles_views=entry.get('n_poses'), cycles_view_samples=entry.get('view_samples'),
                    occluders_ours=len(item['occluders']) if not item.get('copies') else None,
                    occluders_cycles=len(entry.get('occluders') or []), mesh_same=item['mesh_hash'] == entry.get('mesh_hash'),
                    layout_same=same, blender_peak_gb=round(peak / GB, 2) if peak else None,
                    baker_peak_gb=round(bpeak / GB, 2) if bpeak else None, cycles_image=kind)
        if same:
            info.update(compare_cycles(name, b, cyc))
        check(f'cockpit-{name}', b.digest is not None, **info)
        total['cycles_bake_s'] += times.get('bake_s') or 0.0
        total['cycles_total_s'] += times.get('total_s') or 0.0
        total['ours_s'] += b.seconds['wall']
        total['trace_s'] += info['trace_s']
        total['compose_s'] += info['compose_s']
        del b, cyc
    check('cockpit-total', True, **{k: round(v, 1) for k, v in total.items()})


def main():
    args = args_after_dashes()
    baker = Baker(args.exe, 'scenes')
    try:
        if args.cockpit:
            cockpit(baker.ch, baker, args.only.split(',') if args.only else None, args.copies_self)
        else:
            suite(baker.ch)
    finally:
        baker.close()
    failed = [r['name'] for r in RESULTS if not r['ok']]
    print(f'{len(RESULTS) - len(failed)} passed, {len(failed)} failed' + (f': {failed}' if failed else ''), flush=True)
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as f:
            json.dump(RESULTS, f, indent=1, default=str)


if __name__ == '__main__':
    main()
