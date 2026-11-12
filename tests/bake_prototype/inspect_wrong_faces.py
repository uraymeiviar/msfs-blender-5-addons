"""P12 step 1 follow-up (journal Session 4): what the faces under the copy's wrong pixels are (no bake).

Run (CPU cap): blender -b --factory-startup --python inspect_wrong_faces.py -- tag=panel layout=d faces=288,282,284
Per face: master island and its size, master width, the 3D neighbours across its edges (fold angle, open border),
and for its wrong pixels (|copy - GT| > 0.1): copy, GT, direct, and the distance of the pixel centre to the face's
nearest edge in layout px.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bake_common as bc  # noqa: E402
import bake_geom as bg  # noqa: E402
import bake_layouts as bl  # noqa: E402

args = dict(a.split('=', 1) for a in (sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []))
tag = args.get('tag', 'panel')
key = args.get('layout', 'd')
faces = [int(x) for x in args.get('faces', '288,282,284').split(',')]
PAD = 8
OUT = os.path.join(bc.WORK, 'layouts', tag)
LOG = os.path.join(OUT, 'inspect_wrong_faces.log.txt')
target, info = bc.load_scene(tag)
S = int(info['texture_size'])
pos, tris, cn, uvs = bc.mesh_arrays(target.data)
wt = bg.weld_ids(pos)[tris]
em = bg.edge_map(wt)
mz = np.load(os.path.join(bc.WORK, 'master', f'master_{tag}.npz'))
D = float(mz['density'])
island = mz['island']
p = pos[tris]
nrm = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-30)
layouts, _ = bl.make_layouts(target, pos, tris, wt, uvs[info['uv']], S, PAD, key)
uvpx, size, tisl = layouts[key]
x0, y0, w, h = bg.crop_box(uvpx, PAD + 4)
owner, _ = bg.rasterize_ids(uvpx, w, h, 1, x0, y0)
img = {n: bc.read_png16(os.path.join(OUT, f'{key}_{n}.png')) for n in ('copy', 'gt', 'direct')}
err = np.abs(img['copy'] - img['gt'])
for f in faces:
    e3 = np.linalg.norm(p[f] - np.roll(p[f], -1, axis=0), axis=1)
    alt = 2 * bg.tri_areas_3d(pos, tris)[f] / e3.max() * D
    nb = []
    for i, j in ((0, 1), (1, 2), (2, 0)):
        a, b = int(wt[f, i]), int(wt[f, j])
        lst = em[(a, b) if a < b else (b, a)]
        others = [u for (u, _, _) in lst if u != f]
        nb.append([(u, round(float(np.degrees(np.arccos(np.clip(abs(nrm[f] @ nrm[u]), -1, 1)))), 1),
                    int(island[u] == island[f])) for u in others] or 'open')
    n_isl = int((island == island[f]).sum())
    jj, ii = np.nonzero((owner == f) & (err > 0.1))
    tri = uvpx[f]
    rows = []
    for j, i in zip(jj, ii):
        c = np.array([x0 + i + 0.5, y0 + j + 0.5])
        dist = min(abs(bg.tri_areas_2d(np.array([[tri[a], tri[b], c]]))[0]) * 2 / np.linalg.norm(tri[b] - tri[a])
                   for a, b in ((0, 1), (1, 2), (2, 0)))
        rows.append((round(float(img['copy'][j, i]), 3), round(float(img['gt'][j, i]), 3),
                     round(float(img['direct'][j, i]), 3), round(float(dist), 2)))
    rows.sort(key=lambda r: -abs(r[0] - r[1]))
    bc.log(f'{tag} {key} face {f}: 3D edges mm {np.round(e3 * 1000, 2).tolist()}, master width {alt:.2f} px, '
           f'normal {np.round(nrm[f], 3).tolist()}, master island {int(island[f])} ({n_isl} faces), layout island '
           f'{int(tisl[f])}; neighbours per edge (face, angle deg, same master island): {nb}; wrong px {len(rows)} '
           f'(copy, GT, direct, distance to nearest edge px), worst 8: {rows[:8]}', LOG)
