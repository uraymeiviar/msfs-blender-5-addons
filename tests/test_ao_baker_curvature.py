"""The AO Baker's curvature in C++ (OptiX baker journal 20261114.optix-baker.md; Glider plan
PLAN-20261114.optix-ao-baker.md, step (d), finish line 1): the curvature master's rows from the baker
(CurvatureLoad, CurvatureRows) against the add-on's own curvature_context and curvature_at, run as write_curvature
runs them (the same loop over the .ao.map's codes in bands of 256 rows), for every master of the AO suite's scene and,
with --cockpit, the 10 masters of the 1024-sample log on the cockpit copy. Reported per master: the pixels computed,
the count and size of any differing pixel, and both times. The map codes come from the master composed with the
add-on's bake_paged (baked through the baker at 1 sample: the codes do not depend on the AO).

    C:\\Users\\uray\\.claude\\tools\\cpucap\\cpucap.exe 50 G:\\e-jets-e2\\tools\\blender\\blender.exe -b --factory-startup
        --python tests\\test_ao_baker_curvature.py -- --exe F:\\glider\\out\\bin\\x64\\Release\\aobaker.exe [--out r.json]
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

BAND = 256  # write_curvature's rows per band


def args_after_dashes():
    ap = argparse.ArgumentParser()
    ap.add_argument('--exe', required=True)
    ap.add_argument('--cockpit', action='store_true')
    ap.add_argument('--out')
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    return ap.parse_args(argv)


def map_codes(ch, sc, label):
    """The master's .ao.map codes (rows from the top), composed from a bake at 1 sample."""
    views = [dict(v, samples=1) for v in sc['views']]
    b = bm.bake_master(core, ch, f'codes-{label}-{os.getpid()}', sc['pos'], sc['tris'], sc['cnm'], sc['m'], sc['dist'], 1,
                       2048, occluders=sc['occluders'], views=views, falloff=sc['falloff'], combine=sc['combine'],
                       keep_tiles=False, keep_rows=True)
    return b.codes


def python_rows(cc, m, pos, tris, codes):
    """write_curvature's loop (ao_bake_core.py) over the codes, without the file: uint16 rows from the top."""
    H, W = codes.shape
    muv = m['muv']
    P = pos[tris]
    out_all = np.empty((H, W), np.uint16)
    for top in range(0, H, BAND):
        block = codes[top:top + BAND]
        n = block.shape[0]
        out = np.full((n, W), core.CURV_FLAT, np.uint16)
        filled, face = core.code_filled(block), core.code_face(block)
        rr, xx = np.nonzero(filled & (face >= 0))
        if len(rr):
            f = face[rr, xx]
            py = (H - 1 - (top + rr)) + 0.5
            a, b, c = muv[f, 0], muv[f, 1], muv[f, 2]
            v1, v2 = b - a, c - a
            vx, vy = xx + 0.5 - a[:, 0], py - a[:, 1]
            den = v1[:, 0] * v2[:, 1] - v1[:, 1] * v2[:, 0]
            den = np.where(np.abs(den) > 1e-12, den, 1e-12)
            l1 = (vx * v2[:, 1] - vy * v2[:, 0]) / den
            l2 = (v1[:, 0] * vy - v1[:, 1] * vx) / den
            bary = np.stack([1 - l1 - l2, l1, l2], 1)
            P3 = np.einsum('nk,nkd->nd', bary, P[f])
            out[rr, xx] = np.rint((0.5 + 0.5 * core.curvature_at(cc, f, bary, P3)) * 65535.0).astype(np.uint16)
        out_all[top:top + n] = out
    return out_all


def native_rows(ch, sc, codes, width, label):
    """The baker's rows of the same codes; (rows, ready, seconds of the rows)."""
    H, W = codes.shape
    name = f'curv-{label}-{os.getpid()}'
    block, nbytes = client.curvature_block(name + '.geo', sc['pos'], sc['tris'], sc['cnm'], sc['m']['muv'], W, H, width)
    try:
        ready = ch.load_curvature(1, name + '.geo', nbytes)
    finally:
        block.close()
    rows_max = min(BAND, H)
    io_block = client.make_block(name + '.rows', rows_max * W * 6)
    out = np.empty((H, W), np.uint16)
    seconds = 0.0
    try:
        codes_view = np.frombuffer(io_block, np.int32, rows_max * W, 0)
        out_view = np.frombuffer(io_block, np.uint16, rows_max * W, rows_max * W * 4)
        for top in range(0, H, BAND):
            n = min(BAND, H - top)
            codes_view[:n * W] = np.ascontiguousarray(codes[top:top + n], dtype=np.int32).ravel()
            got = ch.curvature_rows(1, top, n, name + '.rows', 0, rows_max * W * 4)
            seconds += got['seconds']
            out[top:top + n] = out_view[:n * W].reshape(n, W)
        del codes_view, out_view
    finally:
        io_block.close()
        ch.release_curvature(1)
    return out, ready, seconds


def compare(ch, job, item, label):
    sc = ts.item_scene(job, item)
    width = float(job['settings'].get('curv_width') or core.CURV_WIDTH)
    codes = map_codes(ch, sc, label)
    t = time.perf_counter()
    cc = core.curvature_context(sc['pos'], sc['tris'], sc['cnm'], width)
    t_ctx = time.perf_counter() - t
    t = time.perf_counter()
    ref = python_rows(cc, sc['m'], sc['pos'], sc['tris'], codes)
    t_rows = time.perf_counter() - t
    t = time.perf_counter()
    ours, ready, t_native_rows = native_rows(ch, sc, codes, width, label)
    t_native = time.perf_counter() - t
    computed = core.code_filled(codes) & (core.code_face(codes) >= 0)
    diff = np.abs(ours.astype(np.int64) - ref.astype(np.int64))
    nd = int((diff > 0).sum())
    check(f'curvature-{label}', nd == 0 and ready['edges'] == cc['edges'], master=f'{codes.shape[1]}x{codes.shape[0]}',
          pixels=int(computed.sum()), edges_python=int(cc['edges']), edges_native=ready['edges'],
          candidates_python=int(len(cc['cand'])), candidates_native=ready['candidates'], differing=nd,
          max_difference_16bit=int(diff.max()) if diff.size else 0, python_context_s=round(t_ctx, 2),
          python_rows_s=round(t_rows, 2), native_load_s=round(ready['seconds'], 3),
          native_rows_s=round(t_native_rows, 2), native_wall_s=round(t_native, 2),
          speedup=round((t_ctx + t_rows) / max(t_native, 1e-9), 1))
    return t_ctx + t_rows, t_native


def suite(ch):
    tb.WORK = ts.WORK
    tb.BLEND = ts.WORK / 'suite.blend'
    tb.FOLDER = ts.WORK / 'suite.bake'
    tb.OUT = ts.WORK / 'suite_ao'
    tb.build_scene()
    job = ts.job_items()
    for item in job['items']:
        compare(ch, job, item, 'suite-' + item['name'])


def cockpit(ch):
    folder = store.bake_folder()
    assert Path(folder).resolve().is_relative_to(ts.COCKPIT_WORK.resolve()), folder
    tb.refresh()
    st = store._state
    names = {it['name']: stem for stem, it in st['items'].items()}
    stems = [names[n] for n in ts.LOG_MASTERS if n in names]
    path = store.make_job(bpy.context, stems)
    with open(path, encoding='utf-8') as f:
        job = json.load(f)
    tp = tn = 0.0
    for item in job['items']:
        a, b = compare(ch, job, item, 'cockpit-' + item['name'])
        tp += a
        tn += b
    check('curvature-cockpit-total', True, masters=len(job['items']), python_s=round(tp, 1), native_s=round(tn, 1))


def main():
    args = args_after_dashes()
    baker = Baker(args.exe, 'curv')
    try:
        if args.cockpit:
            cockpit(baker.ch)
        else:
            suite(baker.ch)
    finally:
        baker.close()
    failed = [r['name'] for r in RESULTS if not r['ok']]
    print(f'{len(RESULTS) - len(failed)} passed, {len(failed)} failed' + (f': {failed}' if failed else ''), flush=True)
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as f:
            json.dump(RESULTS, f, indent=1, default=str)


main()
