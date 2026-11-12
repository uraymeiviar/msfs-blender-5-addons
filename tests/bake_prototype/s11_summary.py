"""Session 11 summary: per object and layout, one row per set of results (2 x, 4 x, after the tuning pass).

Run (background Blender's Python, no bake; or any Python with numpy):
    blender -b --factory-startup --python s11_summary.py -- sets=_p18,_s11x4 tags=panel,cap,knob masters=_p18,_s11x4

Reads tests/_work/ao_bake/layouts/<tag><set>/results.json and the copy / GT images with the inside and band masks;
prints seam / interior, maximum copy / direct (ratio), wrong pixels (inside, |copy - GT| > 0.1, seam band + interior),
MAE and P99 copy / direct, faces above master and their MAE / P99; and the master's size, PNG kB and bake times.
Writes tests/_work/ao_bake/s11_summary<name>.json (name=<s>).
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bake_common as bc  # noqa: E402

args = dict(a.split('=', 1) for a in (sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []))
SETS = args.get('sets', '_p18,_s11x4').split(',')
MASTERS = args.get('masters', ','.join(SETS)).split(',')
TAGS = args.get('tags', 'panel,cap,knob').split(',')
out = dict(sets=SETS, masters=MASTERS, rows={}, master={})
for tag in TAGS:
    for ms in MASTERS:
        p = os.path.join(bc.WORK, 'master', f'master_{tag}{ms}.json')
        if not os.path.exists(p):
            continue
        with open(p) as f:
            m = json.load(f)
        r = dict(W=m['W'], H=m['H'], px=m['W'] * m['H'], png_kB=round(m['png_bytes'] / 1024, 1),
                 npz_kB=round(m['npz_bytes'] / 1024, 1), density=round(m['master_density'], 1),
                 islands=m['n_islands'], core_s=round(m['times']['bake_core_s'], 2),
                 skirt_s=round(m['times'].get('bake_skirt_s', 0), 2), check=m['check'], side=m['side'])
        out['master'][f'{tag}{ms}'] = r
        print(f'master {tag}{ms}: {r["W"]} x {r["H"]} ({r["px"]}), {r["density"]} px/m, {r["islands"]} islands, '
              f'PNG {r["png_kB"]} kB, npz {r["npz_kB"]} kB, bake core / skirt {r["core_s"]} / {r["skirt_s"]} s; '
              f'edge err {m["check"]["edge_rel_err_max"]:.2g} (f32 {m["check"]["edge_rel_err_max_float32_uv"]:.2g}), '
              f'faces > 1e-4 {m["check"]["faces_over_rel_1e_4"]}, overlap px {m["check"]["overlap_pixels"]}; '
              f'full-round walls one island {m["side"]["all_full_round_walls_one_island"]}', flush=True)
    for suf in SETS:
        d = os.path.join(bc.WORK, 'layouts', tag + suf)
        p = os.path.join(d, 'results.json')
        if not os.path.exists(p):
            continue
        with open(p) as f:
            res = json.load(f)
        for k, L in res['layouts'].items():
            c = bc.read_png16(os.path.join(d, f'{k}_copy.png'))
            g = bc.read_png16(os.path.join(d, f'{k}_gt.png'))
            ins = np.load(os.path.join(d, f'{k}_inside.npy'))
            band = np.load(os.path.join(d, f'{k}_band.npy'))
            wrong = ins & (np.abs(c - g) > 0.1)
            ci, di = L['inside']['copy'], L['inside']['direct']
            am = L['above_master']
            row = dict(ratio=L['fl4_ratio'], seam_mae=L['seam_band']['copy']['mae'],
                       interior_mae=L['interior']['copy']['mae'], max_copy=ci['max'], max_direct=di['max'],
                       max_ratio=ci['max'] / di['max'], wrong=int(wrong.sum()), wrong_band=int((wrong & band).sum()),
                       mae_copy=ci['mae'], mae_direct=di['mae'], p99_copy=ci['p99'], p99_direct=di['p99'],
                       fl3=L['fl3_met'], px=ci['px'], above=L['faces_above_master'],
                       above_share=L['area_share_above_master'],
                       above_mae=(am['copy']['mae'], am['direct']['mae']) if am['copy'] else None,
                       above_p99=(am['copy']['p99'], am['direct']['p99']) if am['copy'] else None,
                       ratio_median=L['ratio_median'], times=L['times'], stacked=L['copy_info']['stacked_px'])
            out['rows'][f'{tag}{suf}:{k}'] = row
            ab = (f'above {row["above"]} ({100 * row["above_share"]:.1f} %) MAE {row["above_mae"][0]:.4f} / '
                  f'{row["above_mae"][1]:.4f} P99 {row["above_p99"][0]:.4f} / {row["above_p99"][1]:.4f}'
                  if row['above_mae'] else 'above 0')
            print(f'{tag}{suf} {k}: px {row["px"]} seam/int {row["ratio"]:.2f} ({row["seam_mae"]:.4f} / '
                  f'{row["interior_mae"]:.4f}) max {row["max_copy"]:.3f} / {row["max_direct"]:.3f} '
                  f'({row["max_ratio"]:.2f}) wrong {row["wrong"]} (band {row["wrong_band"]}) MAE '
                  f'{row["mae_copy"]:.4f} / {row["mae_direct"]:.4f} P99 {row["p99_copy"]:.4f} / '
                  f'{row["p99_direct"]:.4f} FL3 {row["fl3"]} stacked {row["stacked"]} {ab} '
                  f'm/l {row["ratio_median"]:.2f} t {row["times"]}', flush=True)
        print(f'{tag}{suf} total {res.get("total_s")} s', flush=True)
with open(os.path.join(bc.WORK, f's11_summary{args.get("name", "")}.json'), 'w') as f:
    json.dump(out, f, indent=1)
