"""Bake prototype helper: zoomed side-by-side of GT, copy, direct and |copy-GT| for one layout (reads saved PNGs).

    blender -b --factory-startup --python inspect_zoom.py -- dir=layouts/panel layout=a x=0 y=100 w=120 h=120 zoom=4
Writes <dir>/zoom_<layout>_<x>_<y>.png (columns: GT, copy, direct, |copy-GT| x8).
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bake_common as bc  # noqa: E402

args = dict(a.split('=', 1) for a in (sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []))
D = os.path.join(bc.WORK, args['dir'])
key = args.get('layout', 'a')
x, y, w, h, z = (int(args.get(k_, d)) for k_, d in (('x', 0), ('y', 0), ('w', 100), ('h', 100), ('zoom', 4)))
ims = [bc.read_png16(os.path.join(D, f'{key}_{n}.png'))[y:y + h, x:x + w] for n in ('gt', 'copy', 'direct')]
ims.append(np.clip(np.abs(ims[1] - ims[0]) * 8, 0, 1))
row = np.concatenate([np.pad(a, ((0, 0), (0, 2)), constant_values=1.0) for a in ims], axis=1)
row = np.repeat(np.repeat(row, z, axis=0), z, axis=1)
bc.write_png(os.path.join(D, f'zoom_{key}_{x}_{y}.png'), row, bits=8)
