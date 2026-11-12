"""Bake prototype helper: fold angles around the wall faces of a target (why a wall splits into islands)."""
import collections
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bake_common as bc  # noqa: E402
import bake_geom as bg  # noqa: E402
import bake_unfold as bu  # noqa: E402

args = dict(a.split('=', 1) for a in (sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []))
tag = args.get('tag', 'knob')
target, info = bc.load_scene(tag)
pos, tris, cn, uvs = bc.mesh_arrays(target.data)
isl = bu.Islands(pos, tris)
ax = np.array(info['local_axes_world'][2])
ax /= np.linalg.norm(ax)
nd = isl.normal @ ax
side = set(np.nonzero(np.abs(nd) < 0.2)[0].tolist())
lines = [f'{tag}: {len(tris)} tris, side {len(side)}; normal.axis histogram '
         f'{np.histogram(nd, bins=[-1, -0.9, -0.5, -0.2, 0.2, 0.5, 0.9, 1])[0].tolist()}']
kinds = collections.Counter()
for (a, b), lst in isl.edges.items():
    ts = [e[0] for e in lst]
    if not any(t in side for t in ts):
        continue
    if len(lst) != 2:
        kinds[f'boundary/nonmanifold n={len(lst)}'] += 1
        continue
    (t1, i1, j1), (t2, i2, j2) = lst
    f = isl.fold(t1, i1, j1, t2, i2, j2)
    L = np.linalg.norm(pos[tris[t1, i1]] - pos[tris[t1, j1]])
    k = ('side-side' if t1 in side and t2 in side else 'side-other')
    kinds[f'{k} fold {round(f / 5) * 5:.0f} len {L * 1000:.2f}mm'] += 1
for k, v in sorted(kinds.items()):
    lines.append(f'   {k}: {v}')
lines.append(f'areas of side tris (mm2): {sorted(set(np.round(isl.area[list(side)] * 1e6, 3).tolist()))[:20]}')
with open(os.path.join(bc.WORK, f'folds_{tag}.txt'), 'w') as f:
    f.write('\n'.join(lines) + '\n')
print('\n'.join(lines))
