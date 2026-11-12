"""Bake prototype helper: difference images of the copy and the direct bake against GT, inside the layout only.

    blender -b --factory-startup --python inspect_seams.py -- tag=knob layouts=abcdefg zoom=3 max=900
Reads the saved PNGs and results.json of step5_layouts.py; writes <layout>_inside_diff_x8.png in the same folder:
copy - GT on the left, direct - GT on the right, red = brighter than GT, blue = darker, x8, padding black, island
borders not marked; scaled up by `zoom` unless wider than `max` px.
"""
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bake_common as bc  # noqa: E402

args = dict(a.split('=', 1) for a in (sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []))
tag = args.get('tag', 'knob')
D = os.path.join(bc.WORK, 'layouts', tag)
res = json.load(open(os.path.join(D, 'results.json')))
for key in args.get('layouts', 'abcdefg'):
    if key not in res['layouts']:
        continue
    r = res['layouts'][key]
    x0, y0, w, h = r['crop']
    gt = bc.read_png16(os.path.join(D, f'{key}_gt.png'))
    cp = bc.read_png16(os.path.join(D, f'{key}_copy.png'))
    di = bc.read_png16(os.path.join(D, f'{key}_direct.png'))
    # pixels inside the layout's triangles, saved by step5_layouts.py
    inside =np.load(os.path.join(D, f'{key}_inside.npy')) if os.path.exists(os.path.join(D, f'{key}_inside.npy')) \
        else None
    if inside is None:
        continue
    panels = []
    for a in (cp, di):
        d = np.where(inside, a - gt, 0.0) * 8
        rgb = np.zeros((h, w, 3))
        rgb[..., 0] = np.clip(d, 0, 1)
        rgb[..., 2] = np.clip(-d, 0, 1)
        rgb[~inside] = 0.0
        panels.append(np.pad(rgb, ((0, 0), (0, 3), (0, 0)), constant_values=1.0))
    img = np.concatenate(panels, axis=1)
    z = int(args.get('zoom', 3))
    z = max(1, min(z, int(math.floor(int(args.get('max', 900)) / img.shape[1]))))
    img = np.repeat(np.repeat(img, z, axis=0), z, axis=1)
    bc.write_png(os.path.join(D, f'{key}_inside_diff_x8.png'), img, bits=8)
    print(key, 'written', img.shape)
