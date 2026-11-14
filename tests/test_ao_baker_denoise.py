"""The AO Baker's denoise in C++ (OptiX baker journal 20261114.optix-baker.md, decisions 17 to 20; Glider plan
PLAN-20261114.optix-ao-baker.md, step (d), finish line 2): each master baked by the baker at the job's samples (the raw
master) and at REF_FACTOR times them with another seed (the reference), the raw master denoised by the baker
(DenoiseLoad, DenoiseWindow: OIDN 2.5.1 with the islands isolated, in the windows denoise_master_oidn uses), and with
--python also by the add-on's own oidn_isolated (Blender's OIDN) on the same windows. Measured against the reference on
the pixels with a face: the RMS of the raw and the denoised master, the same on 4 x 4 block means, the 99th percentile
of the difference, and the mean. The raw master's own noise is measured from a second raw bake with another seed
(RMS of the two's difference / sqrt 2): when it equals the raw master's RMS against the reference, the reference's own
error is small beside it. Written
to tests/_work/ao_baker_denoise/: per master the raw, denoised and reference masters (16-bit PNG) and crops of the
noisiest and the worst-denoised areas, raw | OIDN as it is | [python |] denoised | reference side by side, 8-bit, 2x.
"native" is the baker's denoise (its local mean restored, bound to the noise); "native_unbound" the mean restored,
not bound; "native_plain" OIDN's result as it is (the block's flags). The measures are reported,
not judged (decision 20: the maintainer judges the result).

    C:\\Users\\uray\\.claude\\tools\\cpucap\\cpucap.exe 50 G:\\e-jets-e2\\tools\\blender\\blender.exe -b --factory-startup
        --python tests\\test_ao_baker_denoise.py -- --exe F:\\glider\\out\\bin\\x64\\Release\\aobaker.exe [--python] [--out r.json]
    (the same with tests\\_work\\ao_baker_cycles\\COCKPIT.blend before --python, and --cockpit, for the cockpit)
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import bpy
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_ao_baker_scenes as ts  # noqa: E402  (imports test_ao_bake: the deployed add-ons purged)
from test_ao_baker_scenes import tb, core, store  # noqa: E402
import ao_baker_client as client  # noqa: E402
import ao_baker_master as bm  # noqa: E402
from test_ao_baker_static import Baker, check, RESULTS  # noqa: E402

OUT = tb.REPO_ROOT / 'tests' / '_work' / 'ao_baker_denoise'
REF_FACTOR = 16
REF_SEED = 12
RAW_SEED, RAW2_SEED = 11, 13
TILE = 2048
CROP = 192
ZOOM = 2
BLOCK = 4
REUSE = False  # --reuse: the raw and reference masters of an earlier run (OUT/<label>.bakes.npz), not baked again


def args_after_dashes():
    ap = argparse.ArgumentParser()
    ap.add_argument('--exe', required=True)
    ap.add_argument('--cockpit', action='store_true')
    ap.add_argument('--python', action='store_true', help="also the add-on's oidn_isolated on the same windows")
    ap.add_argument('--only', help='comma-separated master names')
    ap.add_argument('--reuse', action='store_true', help='the raw and reference masters of an earlier run')
    ap.add_argument('--out')
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    return ap.parse_args(argv)


def bake(ch, sc, label, factor, seed):
    views = [dict(v, samples=int(v['samples']) * factor) for v in sc['views']]
    t = time.perf_counter()
    b = bm.bake_master(core, ch, f'dn-{label}-{factor}-{os.getpid()}', sc['pos'], sc['tris'], sc['cnm'], sc['m'],
                       sc['dist'], sc['samples'] * factor, TILE, seed=seed, occluders=sc['occluders'], views=views,
                       falloff=sc['falloff'], combine=sc['combine'], keep_tiles=False, keep_rows=True)
    return b, time.perf_counter() - t


def windows(W, H):
    """denoise_master_oidn's windows, as (window top, window rows, band top in the window, band rows), file rows from
    the top."""
    band = max(64, core.OIDN_WINDOW_PX // max(W, 1) - 2 * core.OIDN_HALO)
    out = []
    for top in range(0, H, band):
        bot = min(H, top + band)
        wa, wb = max(0, top - core.OIDN_HALO), min(H, bot + core.OIDN_HALO)
        out.append((wa, wb - wa, top - wa, bot - top))
    return out


def native_denoise(ch, sc, raw, codes, label, strength=1.0, plain=False, no_bound=False):
    H, W = raw.shape
    m = sc['m']
    name = f'dn-{label}-{os.getpid()}'
    block, nbytes = client.denoise_block(name + '.geo', sc['cnm'], m['muv'], m['island'], W, H, plain=plain,
                                         no_bound=no_bound)
    try:
        ready = ch.load_denoise(1, name + '.geo', nbytes)
    finally:
        block.close()
    wins = windows(W, H)
    rows_max = max(w[1] for w in wins)
    io_block = client.make_block(name + '.io', rows_max * W * 8)
    out = np.empty((H, W), np.uint16)
    stats = dict(groups=0, prepare_s=0.0, oidn_s=0.0, server_s=0.0, pixels=0)
    t = time.perf_counter()
    try:
        cv = np.frombuffer(io_block, np.int32, rows_max * W, 0)
        rv = np.frombuffer(io_block, np.uint16, rows_max * W, rows_max * W * 4)
        ov = np.frombuffer(io_block, np.uint16, rows_max * W, rows_max * W * 6)
        for wt, wr, bt, br in wins:
            cv[:wr * W] = codes[wt:wt + wr].ravel()
            rv[:wr * W] = raw[wt:wt + wr].ravel()
            got = ch.denoise_window(1, wt, wr, bt, br, strength, name + '.io', 0, rows_max * W * 4, rows_max * W * 6)
            out[wt + bt:wt + bt + br] = ov[:br * W].reshape(br, W)
            stats['groups'] = max(stats['groups'], got['groups'])
            stats['pixels'] += got['pixels']
            for k in ('prepare_s', 'oidn_s'):
                stats[k] += got[k]
            stats['server_s'] += got['seconds']
        del cv, rv, ov
    finally:
        io_block.close()
        ch.release_denoise(1)
    stats['wall_s'] = time.perf_counter() - t
    stats['windows'] = len(wins)
    return out, ready, stats


def python_denoise(sc, raw, codes):
    """denoise_master_oidn's loop (strength 1) over the same rows without the files, Blender's OIDN on the GPU."""
    H, W = raw.shape
    m = sc['m']
    CN = np.asarray(sc['cnm'], np.float32)
    lib, dev, used = core.oidn_device('GPU')
    out = raw.copy()
    n_islands = int(m['island'].max()) + 1
    t = time.perf_counter()
    try:
        for wt, wr, bt, br in windows(W, H):
            c = codes[wt:wt + wr][::-1]  # rows from the bottom, as the add-on reads the master
            v0 = raw[wt:wt + wr][::-1].astype(np.float32) / 65535.0
            face = np.where(core.code_filled(c), core.code_face(c), -1)
            ys = np.arange(H - (wt + wr), H - wt)
            valid = face >= 0
            if not valid.any():
                continue
            _none, NRM = core._dn_geometry(face, ys, m['muv'], None, CN)
            isl = np.where(valid, m['island'][np.maximum(face, 0)], -1)
            res, _g = core.oidn_isolated(lib, dev, v0, NRM, isl, n_islands)
            q = np.where(valid, np.clip(np.rint(np.clip(res, 0.0, 1.0) * 65535.0), 0, 65535).astype(np.uint16),
                         raw[wt:wt + wr][::-1])[::-1]
            out[wt + bt:wt + bt + br] = q[bt:bt + br]
    finally:
        lib.oidnReleaseDevice(dev)
    return out, used, time.perf_counter() - t


def block_means(x, valid):
    """Means of the BLOCK x BLOCK blocks whose pixels all have a face."""
    H, W = x.shape
    h, w = H // BLOCK, W // BLOCK
    xs = x[:h * BLOCK, :w * BLOCK].reshape(h, BLOCK, w, BLOCK)
    vs = valid[:h * BLOCK, :w * BLOCK].reshape(h, BLOCK, w, BLOCK).all(axis=(1, 3))
    return xs.mean(axis=(1, 3))[vs]


def measures(img, ref, valid):
    d = (img.astype(np.float64) - ref) / 65535.0
    dv = d[valid]
    rms = float(np.sqrt(np.mean(dv ** 2)))
    bm_ = block_means(d, valid)
    return dict(rms=round(rms, 5),
                rms_4x4=round(float(np.sqrt(np.mean(bm_ ** 2))), 5) if bm_.size else None,
                p99=round(float(np.percentile(np.abs(dv), 99)), 5),
                mean=round(float(dv.mean()), 5))


def crop_at(err, valid):
    """The top-left corner of the CROP x CROP area with the largest mean err over its face pixels (a coarse search)."""
    H, W = err.shape
    if H <= CROP or W <= CROP:
        return 0, 0
    step = CROP // 2
    best, at = -1.0, (0, 0)
    for y in range(0, H - CROP + 1, step):
        for x in range(0, W - CROP + 1, step):
            v = valid[y:y + CROP, x:x + CROP]
            if v.mean() < 0.25:
                continue
            e = float(err[y:y + CROP, x:x + CROP][v].mean())
            if e > best:
                best, at = e, (y, x)
    return at


def write_crops(label, raw, den, ref, valid, middle=()):
    """Two crops: the noisiest raw area and the worst denoised one, each raw | the middle images | denoised |
    reference."""
    names = []
    for kind, err in (('noisiest', np.abs(raw.astype(np.float64) - ref)),
                      ('worst', np.abs(den.astype(np.float64) - ref))):
        y, x = crop_at(err, valid)
        parts = [raw] + list(middle) + [den, ref]
        tiles = []
        for p in parts:
            c = p[y:y + CROP, x:x + CROP].astype(np.float64) / 65535.0
            c = np.where(valid[y:y + CROP, x:x + CROP], c, 0.5 * c)  # the gutter dimmed
            c = np.repeat(np.repeat(c, ZOOM, 0), ZOOM, 1)
            tiles.append(c)
            tiles.append(np.ones((c.shape[0], 4)))
        strip = np.concatenate(tiles[:-1], axis=1)
        path = OUT / f'{label}.{kind}.png'
        core.write_png(str(path), strip[::-1], bits=8)  # write_png takes row 0 = bottom
        names.append(dict(file=path.name, y=int(y), x=int(x)))
    return names


def run_master(ch, sc, label, with_python):
    m = sc['m']
    cache = OUT / f'{label}.bakes.npz'
    z = dict(np.load(cache)) if REUSE and cache.is_file() else {}
    if 'raw' not in z:
        raw_b, t_raw = bake(ch, sc, label, 1, RAW_SEED)
        ref_b, t_ref = bake(ch, sc, label, REF_FACTOR, REF_SEED)
        z.update(raw=raw_b.M16, codes=raw_b.codes, ref=ref_b.M16, t_raw=t_raw, t_ref=t_ref)
    if 'raw2' not in z:
        z['raw2'] = bake(ch, sc, label, 1, RAW2_SEED)[0].M16
    OUT.mkdir(parents=True, exist_ok=True)
    np.savez(cache, **z)
    raw, codes, ref16, raw2 = z['raw'], z['codes'], z['ref'], z['raw2']
    t_raw, t_ref = float(z['t_raw']), float(z['t_ref'])
    ref = ref16.astype(np.float64)
    valid = core.code_filled(codes) & (core.code_face(codes) >= 0)
    raw_noise = float(np.sqrt(np.mean(((raw.astype(np.float64) - raw2)[valid] / 65535.0) ** 2) / 2.0))
    den, ready, st = native_denoise(ch, sc, raw, codes, label)
    plain, _ready, _st = native_denoise(ch, sc, raw, codes, label + '-plain', plain=True)
    unbound, _ready, _st = native_denoise(ch, sc, raw, codes, label + '-unbound', no_bound=True)
    row = dict(master=f"{m['W']}x{m['H']}", pixels=int(valid.sum()), islands=int(m['island'].max()) + 1,
               samples=int(sc['samples']), ref_samples=int(sc['samples']) * REF_FACTOR, device=ready['device'],
               oidn=ready['oidn_version'], detail=ready['detail'] or None, windows=st['windows'], groups=st['groups'],
               raw_bake_s=round(t_raw, 1), ref_bake_s=round(t_ref, 1), denoise_s=round(st['wall_s'], 2),
               prepare_s=round(st['prepare_s'], 2), oidn_s=round(st['oidn_s'], 2),
               raw_noise=round(raw_noise, 5))
    row['raw'] = measures(raw, ref, valid)
    row['native'] = measures(den, ref, valid)
    row['native_plain'] = measures(plain, ref, valid)
    row['native_unbound'] = measures(unbound, ref, valid)
    gutter_same = bool(np.array_equal(den[~valid], raw[~valid]))
    py = None
    if with_python:
        py, used, t_py = python_denoise(sc, raw, codes)
        row['python'] = measures(py, ref, valid)
        row['python_s'] = round(t_py, 1)
        row['python_device'] = used
        d = np.abs(py.astype(np.int64) - den.astype(np.int64))[valid] / 65535.0
        row['native_vs_python'] = dict(mean=round(float(d.mean()), 5), p99=round(float(np.percentile(d, 99)), 5))
    OUT.mkdir(parents=True, exist_ok=True)
    for kind, img in (('raw', raw), ('denoised', den), ('reference', ref16)):
        core.write_png_int(str(OUT / f'{label}.{kind}.png'), img[::-1], bits=16)
    row['crops'] = write_crops(label, raw, den, ref16, valid, [plain] + ([py] if py is not None else []))
    check(f'denoise-{label}', gutter_same and st['pixels'] == int(valid.sum()), gutter_unchanged=gutter_same, **row)
    return row


def suite(ch, with_python, only):
    tb.WORK = ts.WORK
    tb.BLEND = ts.WORK / 'suite.blend'
    tb.FOLDER = ts.WORK / 'suite.bake'
    tb.OUT = ts.WORK / 'suite_ao'
    tb.build_scene()
    job = ts.job_items()
    for item in job['items']:
        if only and item['name'] not in only:
            continue
        run_master(ch, ts.item_scene(job, item), 'suite-' + item['name'], with_python)


def cockpit(ch, with_python, only):
    folder = store.bake_folder()
    assert Path(folder).resolve().is_relative_to(ts.COCKPIT_WORK.resolve()), folder
    tb.refresh()
    st = store._state
    names = {it['name']: stem for stem, it in st['items'].items()}
    stems = [names[n] for n in ts.LOG_MASTERS if n in names and (not only or n in only)]
    path = store.make_job(bpy.context, stems)
    with open(path, encoding='utf-8') as f:
        job = json.load(f)
    total = dict(denoise_s=0.0, prepare_s=0.0, oidn_s=0.0, python_s=0.0)
    for item in job['items']:
        row = run_master(ch, ts.item_scene(job, item), 'cockpit-' + item['name'], with_python)
        for k in total:
            total[k] += row.get(k, 0.0)
    check('denoise-cockpit-total', True, masters=len(job['items']), **{k: round(v, 1) for k, v in total.items()})


def main():
    global REUSE
    args = args_after_dashes()
    REUSE = args.reuse
    only = set(args.only.split(',')) if args.only else None
    baker = Baker(args.exe, 'dn')
    try:
        if args.cockpit:
            cockpit(baker.ch, args.python, only)
        else:
            suite(baker.ch, args.python, only)
    finally:
        baker.close()
    failed = [r['name'] for r in RESULTS if not r['ok']]
    print(f'{len(RESULTS) - len(failed)} passed, {len(failed)} failed' + (f': {failed}' if failed else ''), flush=True)
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as f:
            json.dump(RESULTS, f, indent=1, default=str)


if __name__ == '__main__':
    main()
