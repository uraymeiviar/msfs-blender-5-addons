"""Bake prototype helper: why copy and Cycles disagree in the padding (reads saved PNGs; bakes nothing).

    blender -b --factory-startup --python inspect_padding.py -- tag=cap layout=c
Prints, for the padding pixels with the largest copy error, the nearest triangle, the neighbour across its nearest
edge (welded and Blender topology), the GT value, the copy value, and the GT value where the neighbour lies in the
layout.
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bake_common as bc  # noqa: E402
import bake_copy as bcp  # noqa: E402
import bake_geom as bg  # noqa: E402

args = dict(a.split('=', 1) for a in (sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []))
tag, key = args.get('tag', 'cap'), args.get('layout', 'c')
D = os.path.join(bc.WORK, 'layouts', tag + args.get('suffix', ''))
res = json.load(open(os.path.join(D, 'results.json')))['layouts'][key]
target, info = bc.load_scene(tag)
pos, tris, cn, uvs = bc.mesh_arrays(target.data)
x0, y0, w, h = res['crop']
size = res['size']
gt = bc.read_png16(os.path.join(D, f'{key}_gt.png'))
cp = bc.read_png16(os.path.join(D, f'{key}_copy.png'))
lines = [f'{tag} {key}: crop {res["crop"]} size {size}']
if key in ('a', 'g'):
    uvpx = uvs[info['uv']] * size
    owner, count = bg.rasterize_ids(uvpx, w, h, 1, x0, y0)
    grown, steps = bg.dilate_ids(owner, 8)
    pad = (owner < 0) & (steps > 0) & (gt > 0)  # PNGs hold unwritten pixels as 0
    err = np.where(pad, np.abs(cp - gt), 0)
    wt_w = bg.weld_ids(pos)[tris]
    nb_w = bcp._neighbours(wt_w)
    nb_b = bcp._neighbours(tris)
    order = np.argsort(err.ravel())[::-1][:15]
    for o in order:
        j, i = divmod(int(o), w)
        T = int(grown[j, i])
        bcen = bg.barycentric_many(np.array([[x0 + i + 0.5, y0 + j + 0.5]]), uvpx[[T]])[0]
        kk = int(np.argmin(bcen))
        uw, ub = int(nb_w[T, kk]), int(nb_b[T, kk])
        where = ''
        if ub >= 0:
            c = uvpx[ub].mean(axis=0) - np.array([x0, y0])
            ci, cj = int(c[0]), int(c[1])
            if 0 <= ci < w and 0 <= cj < h:
                where = f'gt at neighbour centre {gt[cj, ci]:.3f}'
        lines.append(f'  px ({i},{j}) step {int(steps[j, i])} T {T} edge {kk} nb welded {uw} topo {ub} '
                     f'gt {gt[j, i]:.3f} copy {cp[j, i]:.3f} own-centre gt '
                     f'{gt[int(uvpx[T].mean(axis=0)[1] - y0), int(uvpx[T].mean(axis=0)[0] - x0)]:.3f} {where}')
    lines.append(f'  padding px {int(pad.sum())}, with copy error > 0.1: {int((err > 0.1).sum())}; '
                 f'gt == 0 in padding: {int(((gt == 0) & pad).sum())}')
print('\n'.join(lines))
with open(os.path.join(D, f'padding_{key}.txt'), 'w') as f:
    f.write('\n'.join(lines) + '\n')
