"""x4 crops of the inside-only difference images, before (left) and after (right), side by side (Sessions 8, 11).

Run (background Blender's Python, no bake; or any Python with numpy):
    blender -b --factory-startup --python zoom_diff.py -- tag=panel before=_p18 after=_s11x4 layouts=de crops=3

The layouts of both sets must be the same (bake_layouts.py is deterministic). Crops of 200 x 120 px are centred on
the worst inside pixels of the before set (|copy - GT|, at least 150 px apart), or given as crops_<k>=x,y,w,h;...
Writes layouts/<tag><after>/<k>_inside_zoom<n>_before_after.png and prints each crop's box.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bake_common as bc  # noqa: E402

args = dict(a.split('=', 1) for a in (sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []))
tag = args.get('tag', 'panel')
BEFORE, AFTER = args.get('before', '_p15'), args.get('after', '_p18')
LAYOUTS = args.get('layouts', 'df')
NCROP = int(args.get('crops', 3))
CW, CH = 200, 120


def load(suf, k):
    d = os.path.join(bc.WORK, 'layouts', tag + suf)
    c = bc.read_png16(os.path.join(d, f'{k}_copy.png'))
    g = bc.read_png16(os.path.join(d, f'{k}_gt.png'))
    ins = np.load(os.path.join(d, f'{k}_inside.npy'))
    return np.where(ins, c - g, 0.0), ins


for k in LAYOUTS:
    d0, ins0 = load(BEFORE, k)
    H, W = d0.shape
    if f'crops_{k}' in args:
        crops = [tuple(int(v) for v in s.split(',')) for s in args[f'crops_{k}'].split(';')]
    else:
        crops = []
        a = np.abs(d0)
        order = np.argsort(a.ravel())[::-1]
        for idx in order:
            y, x = divmod(int(idx), W)
            if a[y, x] <= 0 or len(crops) >= NCROP:
                break
            if all(abs(x - (cx + CW // 2)) > 150 or abs(y - (cy + CH // 2)) > 150 for cx, cy, _, _ in crops):
                crops.append((min(max(x - CW // 2, 0), max(W - CW, 0)), min(max(y - CH // 2, 0), max(H - CH, 0)),
                              min(CW, W), min(CH, H)))
    for n, (x, y, w, h) in enumerate(crops):
        tiles = []
        for suf in (BEFORE, AFTER):
            dd, ins = load(suf, k)
            dd = dd * 8
            rgb = np.zeros(dd.shape + (3,))
            rgb[..., 0] = np.clip(dd, 0, 1)
            rgb[..., 2] = np.clip(-dd, 0, 1)
            rgb[..., 1] = np.where(ins, 0.06, 0.0)
            t = rgb[y:y + h, x:x + w]
            tiles.append(np.repeat(np.repeat(t, 4, axis=0), 4, axis=1))
            tiles.append(np.ones((tiles[-1].shape[0], 8, 3)))
        out = np.concatenate(tiles[:-1], axis=1)
        path = os.path.join(bc.WORK, 'layouts', tag + AFTER, f'{k}_inside_zoom{n}_before_after.png')
        bc.write_png(path, np.clip(out, 0, 1), bits=8)
        print(f'{k} crop {n}: x {x} y {y} w {w} h {h} (rows from the bottom) -> {path}', flush=True)
