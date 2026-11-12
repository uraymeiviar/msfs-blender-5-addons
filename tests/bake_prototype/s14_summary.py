"""Session 14 summary: the tables of the journal from s14_fair.json of each object (no bake, plain Python).

Run: python s14_summary.py tags=panel,cap,knob suffix=_s11x4
Prints Markdown rows: per object, layout and reference (old GT, FAIR) the copy's and the direct bake's MAE, P99,
maximum (copy / direct ratio), seam / interior and wrong pixels (> 0.1), on the pixels where FAIR is defined; then
the FAIR table (samples, bake time, undefined pixels, GT against FAIR inside faces).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(os.path.dirname(os.path.dirname(HERE)), 'tests', '_work', 'ao_bake')
args = dict(a.split('=', 1) for a in sys.argv[1:] if '=' in a)
TAGS = args.get('tags', 'panel,cap,knob').split(',')
SUF = args.get('suffix', '_s11x4')

print('| Object | Layout | Reference | MAE copy / direct | P99 copy / direct | Max copy / direct (ratio) | '
      'Seam / interior copy, direct | Wrong px copy / direct |')
print('| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |')
fair_rows = []
for tag in TAGS:
    with open(os.path.join(WORK, 'layouts', tag + SUF, 's14_fair.json')) as f:
        r = json.load(f)
    for k, L in r['layouts'].items():
        for name, ref in (('GT', 'vs_gt'), ('FAIR', 'vs_fair')):
            c, d = L[ref]['copy'], L[ref]['direct']
            ci, di = c['inside'], d['inside']
            print(f'| {tag} | {k} | {name} | {ci["mae"]:.4f} / {di["mae"]:.4f} | {ci["p99"]:.4f} / {di["p99"]:.4f} | '
                  f'{ci["max"]:.3f} / {di["max"]:.3f} ({ci["max"] / di["max"]:.2f}) | '
                  f'{c["seam_interior"]:.2f}, {d["seam_interior"]:.2f} | {ci["wrong"]} / {di["wrong"]} |')
        ag = L['agreement']
        g = L['vs_fair']['gt']['inside']
        fair_rows.append(f'| {tag} | {k} | {r["samples"]} | {L["bake_s"]} | {L["undefined_px"]} of {L["inside_px"]} | '
                         f'{ag["px"]} | {ag["gt_vs_fair"]["mae"]:.4f} / {ag["gt_vs_fair"]["bias"]:+.4f} | '
                         f'{ag["copy_vs_fair"]["mae"]:.4f} / {ag["copy_vs_gt"]["mae"]:.4f} | '
                         f'{g["mae"]:.4f} / {g["max"]:.3f} |')
print()
print('| Object | Layout | Samples per hi-res px | Bake, s | Undefined px | Full interior px | GT - FAIR there: MAE / bias '
      '| Copy there: MAE vs FAIR / vs GT | GT - FAIR, all inside: MAE / max |')
print('| :--- | :--- | ---: | ---: | :--- | ---: | :--- | :--- | :--- |')
print('\n'.join(fair_rows))
