"""Inside-only difference images (copy - GT, x8, padding black) and wrong-pixel counts (Sessions 8 and 11).

Run (background Blender's Python, no bake; or any Python with numpy):
    blender -b --factory-startup --python inside_diff.py -- tag=panel sets=_p18,_s11x4 layouts=de

For each set (the suffix of tests/_work/ao_bake/layouts/<tag><suffix>/) and layout, reads <k>_copy.png, <k>_gt.png,
<k>_inside.npy and <k>_band.npy (written by step5_layouts.py), writes <k>_inside_diff_copy_x8.png into that folder
(red: copy brighter than GT, blue: darker, grey: inside pixel with no difference, black: padding and outside) and
prints the inside pixels over 0.05 and over 0.1, split into seam band and interior.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bake_common as bc  # noqa: E402

args = dict(a.split('=', 1) for a in (sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []))
tag = args.get('tag', 'panel')
SETS = args.get('sets', '_p15,_p18').split(',')
LAYOUTS = args.get('layouts', 'df')

for suf in SETS:
    d = os.path.join(bc.WORK, 'layouts', tag + suf)
    for k in LAYOUTS:
        c = bc.read_png16(os.path.join(d, f'{k}_copy.png'))
        g = bc.read_png16(os.path.join(d, f'{k}_gt.png'))
        ins = np.load(os.path.join(d, f'{k}_inside.npy'))
        band = np.load(os.path.join(d, f'{k}_band.npy'))
        dd = np.where(ins, c - g, 0.0) * 8
        rgb = np.zeros(c.shape + (3,))
        rgb[..., 0] = np.clip(dd, 0, 1)
        rgb[..., 2] = np.clip(-dd, 0, 1)
        rgb[ins & (rgb.sum(axis=2) == 0)] = 0.05
        bc.write_png(os.path.join(d, f'{k}_inside_diff_copy_x8.png'), np.clip(rgb, 0, 1), bits=8)
        a = np.abs(c - g)
        print(f'{tag}{suf} {k}: inside {int(ins.sum())}, |d|>0.05: band {int((band & (a > 0.05)).sum())}, '
              f'interior {int((ins & ~band & (a > 0.05)).sum())}; |d|>0.1: band {int((band & (a > 0.1)).sum())}, '
              f'interior {int((ins & ~band & (a > 0.1)).sum())}', flush=True)
