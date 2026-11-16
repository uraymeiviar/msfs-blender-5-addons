"""FSS OptiX in the AO bake (OptiX baker journal 20261114.optix-baker.md, Session 9's finish lines): bakes through the
panel's operator and the runner, in a hidden second Blender.

The AO suite's scene (default), in tests/_work/ao_bake_native_job/:
  - Cycles unchanged (finish line 2): the job baked by the committed add-on's runner (git HEAD, extracted into the work
    folder), then by this runner with Baker Cycles, with Auto and FSS_AO_BAKER_NO_CUDA, and with Auto and the exe
    missing (FSS_AO_BAKER_EXE): every master's files (AO, raw AO, map, layout, curvature) byte-identical; the log says
    why Cycles baked;
  - FSS OptiX (finish line 1): Baker Auto bakes every master with FSS OptiX (the log, the status, the index entry, the
    curvature and the OIDN denoise name it); the curvature masters and the maps are byte-identical to Cycles'; Apply
    into separate files works on the result; the AO's difference from Cycles is reported;
  - Cancel inside a tile (finish line 3): a master baked at so many samples that one tile takes a minute, cancelled
    two seconds into its first tile: the bake ends within seconds, the master is cancelled and its old files unchanged.
With --cockpit, on the copy of the E2 cockpit opened by the command line (tests/_work/ao_baker_cycles/COCKPIT.blend,
its own bake folder): the 10 masters of the log in one job with Baker Auto, curvature and the OIDN denoise, timed
end to end against the Cycles masters' times of the real index (finish lines 1 and 4); Apply into separate files in
the work folder on their texture sets.

    C:\\Users\\uray\\.claude\\tools\\cpucap\\cpucap.exe 50 G:\\e-jets-e2\\tools\\blender\\blender.exe -b
        --factory-startup --python tests\\test_ao_bake_native_job.py -- [--out r.json]
    C:\\Users\\uray\\.claude\\tools\\cpucap\\cpucap.exe 50 G:\\e-jets-e2\\tools\\blender\\blender.exe -b
        --factory-startup tests\\_work\\ao_baker_cycles\\COCKPIT.blend
        --python tests\\test_ao_bake_native_job.py -- --cockpit
"""
import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_ao_bake as tb  # noqa: E402  (the deployed add-ons purged, this repository's enabled)
from test_ao_bake import bpy, core, store, ao_bake  # noqa: E402
from test_ao_baker_static import check, RESULTS  # noqa: E402

native = sys.modules['fss_blender_tools.ao_bake_native']
JOB_REF = tb.Reference('native_job')  # decision 6: the files of the Python composition, recorded
WORK = tb.REPO_ROOT / 'tests' / '_work' / 'ao_bake_native_job'
COCKPIT_WORK = tb.REPO_ROOT / 'tests' / '_work' / 'ao_baker_cycles'
REAL_INDEX = Path(r'G:\e-jets-e2\assets\visual\cockpit\COCKPIT.bake\index.json')  # read only
LOG_MASTERS = ('MESH_SEAT_HEADREST_PILOT', 'MESH_SEAT_BACK_SHELL_PILOT', 'SEAT_OBS', 'SEAT_OBS_SIT_FOAM',
               'SEAT_CUSHION_GUSSET_PILOT', 'YOKE_BASE_PILOT', 'YOKE_BASE_COPILOT', 'SEAT_CUSHION_GUSSET_COPILOT',
               'MESH_SEAT_ARMREST_RT_PILOT.001', 'MESH_SEAT_ARMREST_LT_PILOT.001')
SUFFIXES = ('.ao.jxl', '.ao.png', '.ao.raw.jxl', '.ao.raw.png', '.ao.map', '.ao.npz', '.curv.jxl', '.curv.png')
CANCEL_SAMPLES = 4_000_000  # one tile of a suite master takes about a minute
CANCEL_AFTER_S = 2.0


def args_after_dashes():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cockpit', action='store_true')
    ap.add_argument('--out')
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    return ap.parse_args(argv)


def head_addon():
    """The committed add-on (git HEAD's fss_blender_tools) in the work folder; returns its runner."""
    dest = WORK / 'head_addon'
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    tar = WORK / 'head.tar'
    subprocess.run(['git', '-C', str(tb.REPO_ROOT), 'archive', '-o', str(tar), 'HEAD', 'fss_blender_tools'], check=True)
    with tarfile.open(tar) as t:
        t.extractall(dest, filter='data')
    tar.unlink()
    rev = subprocess.run(['git', '-C', str(tb.REPO_ROOT), 'rev-parse', '--short', 'HEAD'], check=True,
                         capture_output=True, text=True).stdout.strip()
    return str(dest / 'fss_blender_tools' / 'ao_bake_runner.py'), rev


def files_of(folder):
    """{stem: {suffix: sha256}} of every master in a bake folder."""
    out = {}
    for p in Path(folder).iterdir():
        for suf in SUFFIXES:
            if p.name.endswith(suf):
                out.setdefault(p.name[:-len(suf)], {})[suf] = hashlib.sha256(p.read_bytes()).hexdigest()
                break
    return out


CONSOLE = {'last': ''}  # the console output of the last bake_all's bake


def bake_all(label, env=None, runner=None):
    """Every master of the suite's scene baked anew (the bake folder emptied), with env set for the second Blender
    (and so for aobaker.exe) and the runner given; returns (status, log, seconds, files) and keeps a copy of the
    folder."""
    folder = Path(store.bake_folder())
    if folder.exists():
        shutil.rmtree(folder)
    keep_runner = store.RUNNER
    saved = {k: os.environ.get(k) for k in (env or {})}
    os.environ.update(env or {})
    t = time.time()
    try:
        if runner:
            store.RUNNER = runner
        tb.refresh()
        console = io.StringIO()
        with contextlib.redirect_stdout(console):  # decision 74: the bake's report goes to the console
            res = bpy.ops.fss.ao_bake_start(scope='STALE', hidden=True, wait=True)
        CONSOLE['last'] = console.getvalue()
        assert res == {'FINISHED'}, res
    finally:
        store.RUNNER = keep_runner
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    dt = time.time() - t
    status = store.read_status(str(folder)) or {}
    log = (folder / 'bake.log').read_text(encoding='utf-8')
    dst = WORK / f'bake_{label}'
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(folder, dst, ignore=shutil.ignore_patterns('snapshot.blend', 'preview.bin'))
    return status, log, dt, files_of(folder)


def same_files(a, b, suffixes=SUFFIXES):
    """(masters compared, [(stem, suffix)] that differ or are missing on one side)."""
    diff = []
    for stem in sorted(set(a) | set(b)):
        for suf in suffixes:
            x, y = a.get(stem, {}).get(suf), b.get(stem, {}).get(suf)
            if x != y:
                diff.append((stem, suf))
    return len(set(a) | set(b)), diff


def index_entries(folder):
    with open(Path(folder) / 'index.json', encoding='utf-8') as f:
        return json.load(f)['masters']


def ao_difference(folder_a, folder_b):
    """Per master the mean and 99th percentile of |A - B| over the pixels both fill (a report, not a pass mark)."""
    out = {}
    for stem in index_entries(folder_a):
        a, b = core.load_master(str(folder_a), stem), core.load_master(str(folder_b), stem)
        if a is None or b is None or a['image'].shape != b['image'].shape:
            out[stem] = None
            continue
        both = a['filled'] & b['filled']
        d = np.abs(a['image'][both].astype(np.float64) - b['image'][both].astype(np.float64)) / 65535.0
        out[stem] = dict(mean=round(float(d.mean()), 4), p99=round(float(np.percentile(d, 99)), 4))
    return out


def settings(s, baker, optix_samples=None):
    s.baker = baker
    s.optix_samples = optix_samples or s.samples
    s.curvature = True
    s.denoise = True
    s.dn_method = 'OIDN'
    s.dn_strength = 1.0


def suite():
    tb.WORK = WORK
    tb.BLEND = WORK / 'suite.blend'
    tb.FOLDER = WORK / 'suite.bake'
    tb.OUT = WORK / 'suite_ao'
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    tb.build_scene()
    s = bpy.context.scene.fss_ao_bake
    settings(s, 'CYCLES')
    head_runner, rev = head_addon()

    # finish line 2: Cycles unchanged
    st_h, _log_h, t_h, f_h = bake_all('head', runner=head_runner)
    check('head-bakes', st_h.get('state') == 'done' and len(f_h) > 0, rev=rev, masters=len(f_h), seconds=round(t_h, 1))
    # decision 6: every master's files as the committed runner (the Python composition) writes them, recorded
    bad = []
    for stem in sorted(f_h):
        try:
            JOB_REF.check(f'head/{stem}', dict(sorted(f_h[stem].items())))
        except AssertionError as exc:
            bad.append(str(exc))
    check('head-same-as-recorded', not bad, masters=len(f_h), differing=bad[:4])
    st_c, log_c, t_c, f_c = bake_all('cycles')
    n, diff = same_files(f_h, f_c)
    check('cycles-same-as-head', not diff and 'baker Cycles (the Baker setting)' in log_c, masters=n,
          differing=diff[:8],
          seconds=round(t_c, 1))
    # decision 6: this runner's files (the C++ composition) against the values recorded from the Python composition
    from ao_native_reference import digest
    bad = sorted(s for s in set(f_c) | set(k[5:] for k in JOB_REF.want if k.startswith('head/'))
                 if JOB_REF.want.get(f'head/{s}') != digest(dict(sorted(f_c.get(s, {}).items()))))
    check('cycles-same-as-recorded', not bad, masters=len(f_c), differing=bad[:8])
    settings(s, 'AUTO')
    st_n, log_n, t_n, f_n = bake_all('nocuda', env={native.NO_CUDA_ENV: '1'})
    n, diff = same_files(f_h, f_n)
    line = [x for x in log_n.splitlines() if 'baker Cycles' in x]
    check('auto-no-gpu-cycles', not diff and bool(line) and 'NoDriver' in line[0]
          and 'Cycles because' in CONSOLE['last'],
          masters=n, differing=diff[:8], log=line[:1], seconds=round(t_n, 1))
    missing = str(WORK / 'no_such' / 'aobaker.exe')
    st_m, log_m, t_m, f_m = bake_all('noexe', env={'FSS_AO_BAKER_EXE': missing})
    n, diff = same_files(f_h, f_m)
    line = [x for x in log_m.splitlines() if 'baker Cycles' in x]
    check('auto-no-exe-cycles', not diff and bool(line) and 'is missing' in line[0], masters=n, differing=diff[:8],
          log=line[:1], seconds=round(t_m, 1))
    entries = index_entries(WORK / 'bake_noexe')
    check('cycles-index-baker', all((e.get('baker') or {}).get('name') == 'Cycles' for e in entries.values()),
          bakers=sorted({(e.get('baker') or {}).get('name') for e in entries.values()}))

    # finish line 1 on the suite: FSS OptiX
    st_o, log_o, t_o, f_o = bake_all('optix')
    results = st_o.get('results', [])
    entries = index_entries(WORK / 'bake_optix')
    by = sorted({r.get('baker') for r in results})
    curv_by = sorted({(e.get('curvature') or {}).get('baker') for e in entries.values()})
    dn_by = sorted({(e.get('denoise') or {}).get('baker') for e in entries.values()})
    named = sum(1 for x in log_o.splitlines() if re.search(r'\] \d+/\d+ .*: baked by FSS OptiX', x))  # a master's line
    ok = (st_o.get('state') == 'done' and by == [native.NAME] and named == len(results)
          and all((e.get('baker') or {}).get('name') == native.NAME for e in entries.values())
          and curv_by == [native.NAME] and dn_by == [native.NAME] and f"baker {native.NAME}" in log_o)
    check('optix-bakes-all', ok, masters=len(results), status_bakers=by, log_lines=named, curvature_by=curv_by,
          denoise_by=dn_by, seconds=round(t_o, 1), cycles_seconds=round(t_c, 1))
    n, diff = same_files(f_c, f_o, suffixes=('.ao.map', '.curv.jxl', '.curv.png'))
    check('optix-curvature-map-same', not diff, masters=n, differing=diff[:8])
    check('optix-ao-vs-cycles', True, difference=ao_difference(WORK / 'bake_optix', WORK / 'bake_cycles'))
    rep = tb.apply_set('SET_A', file_name='native_set_a.png')
    out = Path(s.output_folder) / 'native_set_a.png'
    check('optix-apply', out.is_file() and not rep.get('error'), file=str(out),
          bytes=out.stat().st_size if out.is_file() else None)
    cancel_in_tile(s)


def cancel_in_tile(s):
    """Finish line 3: Cancel two seconds into a minute-long tile of FSS OptiX keeps the master as it was."""
    tb.refresh()
    stem = store._state['by_object']['A']
    folder = store.bake_folder()
    before = files_of(folder).get(stem)
    settings(s, 'OPTIX', CANCEL_SAMPLES)
    path = store.make_job(bpy.context, [stem], what={stem: (True, False, False)})
    proc = store.start_bake(path, hidden=True)
    t0 = time.time()
    tile_seen = None
    try:
        while proc.poll() is None and time.time() - t0 < 300:
            st = store.read_status(folder) or {}
            if st.get('tile', 0) >= 1 and st.get('n_tiles') and tile_seen is None:
                tile_seen = time.time()
            if tile_seen is not None and time.time() - tile_seen >= CANCEL_AFTER_S:
                break
            time.sleep(0.1)
        tc = time.time()
        store.cancel()
        proc.wait(timeout=120)
        stop_s = time.time() - tc
    finally:
        if proc.poll() is None:
            proc.kill()
        store.finish_run()
        settings(s, 'CYCLES')
    st = store.read_status(folder) or {}
    after = files_of(folder).get(stem)
    res = (st.get('results') or [{}])[0]
    log = (Path(folder) / 'bake.log').read_text(encoding='utf-8')
    check('optix-cancel-in-tile', tile_seen is not None and res.get('status') == 'cancelled' and before == after
          and bool(before), status=res.get('status'), reason=res.get('reason'), stop_s=round(stop_s, 2),
          files_unchanged=before == after, baker_log=[x for x in log.splitlines() if '] baker ' in x][-1:])


def cockpit():
    """Finish lines 1 and 4 on the cockpit copy: the 10 masters of the log, Baker Auto, timed end to end."""
    folder = Path(store.bake_folder())
    assert folder.resolve().is_relative_to(COCKPIT_WORK.resolve()), folder  # only the copy's bake folder
    s = bpy.context.scene.fss_ao_bake
    settings(s, 'AUTO', 4096)
    out_dir = WORK / 'cockpit_apply'
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    s.output_folder = str(out_dir)
    with open(REAL_INDEX, encoding='utf-8') as f:
        real = {e['name']: e for e in json.load(f)['masters'].values()}
    tb.refresh()
    names = [n for n in LOG_MASTERS if n in real]
    objs = [real[n]['object'] for n in names]
    tb.select(objs)
    t = time.time()
    res = bpy.ops.fss.ao_bake_start(scope='SELECTED', hidden=True, wait=True)
    wall = time.time() - t
    assert res == {'FINISHED'}, res
    status = store.read_status(str(folder)) or {}
    log = (folder / 'bake.log').read_text(encoding='utf-8')
    entries = index_entries(folder)
    results = status.get('results', [])
    baked = [r for r in results if r['status'] == 'baked']
    mine = {store._state['by_object'][o] for o in objs if o in store._state['by_object']}
    ent = {k: entries[k] for k in mine if k in entries}
    ok = (len(baked) == len(names) and all(r.get('baker') == native.NAME for r in baked)
          and all((e.get('baker') or {}).get('name') == native.NAME for e in ent.values())
          and all((e.get('curvature') or {}).get('baker') == native.NAME for e in ent.values())
          and all((e.get('denoise') or {}).get('baker') == native.NAME for e in ent.values()))
    cyc = dict(bake_s=sum((real[n].get('times') or {}).get('bake_s') or 0.0 for n in names),
               total_s=sum((real[n].get('times') or {}).get('total_s') or 0.0 for n in names),
               denoise_s=sum((real[n].get('denoise') or {}).get('seconds') or 0.0 for n in names),
               curvature_s=sum((real[n].get('curvature') or {}).get('seconds') or 0.0 for n in names))
    ours = dict(wall_s=round(wall, 1), job_s=status.get('elapsed_s'),
                bake_s=round(sum(e['times']['bake_s'] for e in ent.values()), 1),
                compose_s=round(sum(e['times']['compose_s'] for e in ent.values()), 1),
                trace_s=round(sum(e['baker'].get('trace_s') or 0.0 for e in ent.values()), 1),
                denoise_s=round(sum((e.get('denoise') or {}).get('seconds') or 0.0 for e in ent.values()), 1),
                curvature_s=round(sum((e.get('curvature') or {}).get('seconds') or 0.0 for e in ent.values()), 1))
    check('cockpit-optix-job', ok, masters=len(baked), of=len(names), bakers=sorted({r.get('baker') for r in baked}),
          ours=ours, cycles={k: round(v, 1) for k, v in cyc.items()},
          baker_line=[x for x in log.splitlines() if x.split('] ', 1)[-1].startswith('baker ')][:1],
          failed=[(r['name'], r.get('reason')) for r in results if r['status'] != 'baked'])
    # Apply on the texture sets of these masters, into separate files in the work folder
    sets = sorted({m for k in mine for m in store._state['items'][k]['sets']})
    reps = []
    for name in sets:
        rep = tb.apply_set(name, file_name=f'native_{core.safe_stem("set", name)}.png')
        reps.append((name, rep.get('error')))
    files = sorted(p.name for p in out_dir.iterdir())
    check('cockpit-apply', len(files) >= len(sets) and not any(e for _n, e in reps), sets=len(sets), files=len(files))


def main():
    args = args_after_dashes()
    have, why = native.available()
    check('native-available', have, why=why, version=native.version())
    if args.cockpit:
        cockpit()
    else:
        suite()
        check('reference-values', True, cases=JOB_REF.done(complete=True))
    failed = [r['name'] for r in RESULTS if not r['ok']]
    print(f'{len(RESULTS) - len(failed)} passed, {len(failed)} failed' + (f': {failed}' if failed else ''), flush=True)
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as f:
            json.dump(RESULTS, f, indent=1, default=str)


if __name__ == '__main__':
    main()
