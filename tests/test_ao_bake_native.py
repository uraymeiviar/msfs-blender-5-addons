"""The add-on's FSS OptiX client, fss_blender_tools/ao_bake_native.py (OptiX baker journal 20261114.optix-baker.md,
decisions 21 to 25), against the paths the baker's own tests checked: for every master of the AO suite's scene, with
the baker shipped in lib/ao_baker (or --exe):
  - tiles: Baker.load_master and Baker.bake_tile, composed by bake_paged with the runner's rule, give the same master
    and map, byte for byte, as the tests' client (ao_baker_master.bake_master, same seed);
  - curvature: Baker.write_curvature writes the same curvature master as ao_bake_core.write_curvature;
  - denoise: Baker.denoise_master turns the raw master file into the same denoised master as the baker's windows fed
    from arrays (test_ao_baker_denoise.native_denoise);
  - the start without a GPU (FSS_AO_BAKER_NO_CUDA): Baker.ok False and why given.
Files in tests/_work/ao_bake_native/.

    C:\\Users\\uray\\.claude\\tools\\cpucap\\cpucap.exe 50 G:\\e-jets-e2\\tools\\blender\\blender.exe -b --factory-startup
        --python tests\\test_ao_bake_native.py -- [--exe path\\aobaker.exe] [--out r.json]
"""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_ao_baker_scenes as ts  # noqa: E402  (imports test_ao_bake: the deployed add-ons purged)
from test_ao_baker_scenes import tb, core  # noqa: E402
import ao_baker_master as bm  # noqa: E402
import test_ao_baker_denoise as td  # noqa: E402
from test_ao_baker_static import check, RESULTS  # noqa: E402

native = sys.modules[core.__name__.rsplit('.', 1)[0] + '.ao_bake_native'] if (
    core.__name__.rsplit('.', 1)[0] + '.ao_bake_native') in sys.modules else None
if native is None:
    import importlib
    native = importlib.import_module(core.__name__.rsplit('.', 1)[0] + '.ao_bake_native')

WORK = tb.REPO_ROOT / 'tests' / '_work' / 'ao_bake_native'
TILE = 512
SEED = 11
SMALL_WINDOW_PX = 30_000  # with the halo of 128 rows: bands of 64 rows on the suite's masters


def args_after_dashes():
    ap = argparse.ArgumentParser()
    ap.add_argument('--exe')
    ap.add_argument('--out')
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    return ap.parse_args(argv)


def bake_native(bk, sc):
    """The master through Baker.load_master and Baker.bake_tile, composed with bake_paged and the runner's rule: (M16,
    codes) rows from the top."""
    m = sc['m']
    bk.load_master(sc['pos'], sc['tris'], sc['cnm'], m, sc['dist'], sc['samples'], views=sc['views'],
                   occluders=sc['occluders'], falloff=sc['falloff'], combine=sc['combine'], seed=SEED)
    W, H = m['W'], m['H']
    grid = core.tile_grid(W, H, TILE)
    rows = []

    def bake_tile(i, rect, win, baked):
        x0, y0, w, h = rect
        A, B, _done = bk.bake_tile(rect, tile=i + 1, tiles=len(grid))
        cm = A >= 0
        win[cm] = core.quantize16(A[cm])
        sm = (~cm) & (B >= 0) & (core.rect_window(m['rects'], x0, y0, w, h) >= 0)
        win[sm] = core.quantize16(B[sm])
        baked |= cm | sm
        yield i

    def write_rows(values, codes):
        rows.append((values.copy(), codes.copy()))
    for _ in core.bake_paged(m, TILE, bake_tile, write_rows, {}):
        pass
    bk.release_master()
    return np.concatenate([r[0] for r in rows]), np.concatenate([r[1] for r in rows])


def write_master(folder, key, m, M16, codes):
    os.makedirs(folder, exist_ok=True)
    w = core.MasterWriter(folder, key, m['W'], m['H'])
    for top in range(0, m['H'], 256):
        w.write_rows(M16[top:top + 256], codes[top:top + 256])
    w.finish(m, np.arange(len(m['muv'])), dict(schema=core.SCHEMA, key=key))


def read_curv(folder, key):
    return core.read_image(core.master_paths(folder, key, 'curv')[0])


def one(bk, ch, job, item):
    label = item['name']
    sc = ts.item_scene(job, item)
    m = sc['m']
    M16, codes = bake_native(bk, sc)
    ref = bm.bake_master(core, ch, f'nat-{label}-{os.getpid()}', sc['pos'], sc['tris'], sc['cnm'], m, sc['dist'],
                         sc['samples'], TILE, seed=SEED, occluders=sc['occluders'], views=sc['views'],
                         falloff=sc['falloff'], combine=sc['combine'], keep_tiles=False, keep_rows=True)
    tiles_same = bool(np.array_equal(M16, ref.M16) and np.array_equal(codes, ref.codes))
    folder = str(WORK / 'masters')
    key = core.safe_stem('ao', label) if hasattr(core, 'safe_stem') else label
    write_master(folder, key, m, M16, codes)
    width = float(job['settings'].get('curv_width') or core.CURV_WIDTH)
    py = core.write_curvature(folder, key, m, sc['pos'], sc['tris'], sc['cnm'], width)
    curv_py = read_curv(folder, key)
    nat = bk.write_curvature(folder, key, m, sc['pos'], sc['tris'], sc['cnm'], width)
    curv_nat = read_curv(folder, key)
    curv_same = bool(np.array_equal(curv_py, curv_nat)) and py['edges'] == nat['edges']
    # the denoise: the master becomes the raw one, as the runner's denoise() does
    img = core.master_paths(folder, key)[0]
    rjx, rpn = core.image_paths(folder, key, 'ao.raw')
    os.replace(img, rjx if img.endswith('.jxl') else rpn)
    st = bk.denoise_master(folder, key, sc['cnm'], dict(strength=1.0))
    den_file = core.read_image(core.master_paths(folder, key)[0])[::-1]  # rows from the top
    den_arr, _ready, _s = td.native_denoise(ch, sc, M16, codes, f'nat-{label}')
    den_same = bool(np.array_equal(den_file, den_arr))
    # the same with small windows (SMALL_WINDOW_PX: 64-row bands), so that the window and halo rows are exercised
    keep = core.OIDN_WINDOW_PX
    core.OIDN_WINDOW_PX = SMALL_WINDOW_PX
    try:
        st_small = bk.denoise_master(folder, key, sc['cnm'], dict(strength=1.0))
        small_file = core.read_image(core.master_paths(folder, key)[0])[::-1]
        small_arr, _ready, _s = td.native_denoise(ch, sc, M16, codes, f'nat-{label}-s')
    finally:
        core.OIDN_WINDOW_PX = keep
    den_same = den_same and bool(np.array_equal(small_file, small_arr)) and st_small['windows'] > 1
    check(f'native-{label}', tiles_same and curv_same and den_same, master=f"{m['W']}x{m['H']}", tiles_same=tiles_same,
          curvature_same=curv_same, edges=nat['edges'], curvature_s=nat['seconds'], denoise_same=den_same,
          denoise_device=st['device'], oidn=st['oidn'], groups=st['groups'], windows=st['windows'],
          small_windows=st_small['windows'],
          mean_change=st['mean_change'], denoise_s=st['seconds'])


def no_gpu(exe):
    os.environ[native.NO_CUDA_ENV] = '1'
    try:
        with native.Baker(exe=exe, tag='nogpu') as bk:
            check('native-no-gpu', not bk.ok and bool(bk.why), gpu_ok=bk.ok, why=bk.why)
    finally:
        del os.environ[native.NO_CUDA_ENV]


def main():
    args = args_after_dashes()
    exe = args.exe or native.EXE
    have, why = native.available()
    check('native-available', have or bool(args.exe), why=why, exe=exe, version=native.version())
    if WORK.exists():
        shutil.rmtree(WORK)
    tb.WORK = ts.WORK
    tb.BLEND = ts.WORK / 'suite.blend'
    tb.FOLDER = ts.WORK / 'suite.bake'
    tb.OUT = ts.WORK / 'suite_ao'
    tb.build_scene()
    job = ts.job_items()
    with native.Baker(exe=exe, tag='main') as bk, native.Baker(exe=exe, tag='ref') as ref:
        check('native-start', bk.ok, device=bk.ready['device'], state=bk.ready['device_state'], version=bk.version)
        for item in job['items']:
            one(bk, ref.ch, job, item)
    no_gpu(exe)
    failed = [r['name'] for r in RESULTS if not r['ok']]
    print(f'{len(RESULTS) - len(failed)} passed, {len(failed)} failed' + (f': {failed}' if failed else ''), flush=True)
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as f:
            json.dump(RESULTS, f, indent=1, default=str)


if __name__ == '__main__':
    main()
