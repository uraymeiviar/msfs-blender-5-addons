"""P12 step 1 (journal Session 4): are the copy's wrong pixels on faces that are narrow in the master?

Run (CPU cap, no blend file), after step3_master.py and step5_layouts.py of Session 2 for the tag:
    blender -b --factory-startup --python p12_measure.py -- tag=panel layouts=ad master_suffix= layout_suffix=

Master width of a face: its smallest altitude (2 x area / longest edge, 3D) x the master density of its island, in
master pixels. For each layout: the pixels whose copy error against GT is above 0.1, the seam band pixels (and their
summed |error|), and all inside pixels as the reference; how many of each lie on faces under 2, 3 and 4 master px.
Writes tests/_work/ao_bake/layouts/<tag><layout_suffix>/p12_measure.json.
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bake_common as bc  # noqa: E402
import bake_geom as bg  # noqa: E402
import bake_layouts as bl  # noqa: E402

args = dict(a.split('=', 1) for a in (sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []))
tag = args.get('tag', 'panel')
KEYS = args.get('layouts', 'ad')
MSUF = args.get('master_suffix', '')
LSUF = args.get('layout_suffix', '')
PAD = 8
OUT = os.path.join(bc.WORK, 'layouts', tag + LSUF)
LOG = os.path.join(OUT, 'p12_measure.log.txt')

target, info = bc.load_scene(tag)
S = int(info['texture_size'])
pos, tris, cn, uvs = bc.mesh_arrays(target.data)
uv0 = uvs[info['uv']]
wt = bg.weld_ids(pos)[tris]
mz = np.load(os.path.join(bc.WORK, 'master', f'master_{tag}{MSUF}.npz'))
dens_isl = mz['island_density'] if 'island_density' in mz.files else None
island = mz['island']
face_d = np.where(island >= 0, dens_isl[np.maximum(island, 0)], 0.0) if dens_isl is not None \
    else np.full(len(tris), float(mz['density']))
p = pos[tris]
area = bg.tri_areas_3d(pos, tris)
longest = np.linalg.norm(p - np.roll(p, -1, axis=1), axis=2).max(axis=1)
width = np.where(longest > 0, 2 * area / np.maximum(longest, 1e-30), 0.0) * face_d
bc.log(f'{tag}: master width per face, px: min {width.min():.3f}, median {np.median(width):.2f}; faces under 2/3/4: '
       f'{int((width < 2).sum())}/{int((width < 3).sum())}/{int((width < 4).sum())} of {len(tris)}', LOG)

layouts, _ = bl.make_layouts(target, pos, tris, wt, uv0, S, PAD, KEYS)
res = dict(tag=tag, faces=int(len(tris)), faces_under={str(k): int((width < k).sum()) for k in (2, 3, 4)},
           area_share_under={str(k): float(area[width < k].sum() / area.sum()) for k in (2, 3, 4)}, layouts={})
for key, (uvpx, size, tisl) in layouts.items():
    x0, y0, w, h = bg.crop_box(uvpx, PAD + 4)
    owner, _ = bg.rasterize_ids(uvpx, w, h, 1, x0, y0)
    copy = bc.read_png16(os.path.join(OUT, f'{key}_copy.png'))
    gt = bc.read_png16(os.path.join(OUT, f'{key}_gt.png'))
    inside = np.load(os.path.join(OUT, f'{key}_inside.npy'))
    band = np.load(os.path.join(OUT, f'{key}_band.npy'))
    err = np.abs(copy - gt)
    fw = np.where(owner >= 0, width[np.maximum(owner, 0)], np.inf)
    sets = dict(wrong=inside & (err > 0.1), seam_band=band, inside=inside)
    row = dict(mae_check=float(err[inside].mean()))
    for name, msk in sets.items():
        n = int(msk.sum())
        r = dict(px=n)
        for k in (2, 3, 4):
            r[f'under_{k}'] = float((msk & (fw < k)).sum() / max(n, 1))
            r[f'err_under_{k}'] = float(err[msk & (fw < k)].sum() / max(err[msk].sum(), 1e-30))
        row[name] = r
    # the wrong pixels' faces
    wf = owner[sets['wrong']]
    row['wrong_faces'] = sorted(((int(f), round(float(width[f]), 2), int((wf == f).sum())) for f in np.unique(wf)),
                                key=lambda x: -x[2])[:20]
    res['layouts'][key] = row
    bc.log(f'  {key}: MAE check {row["mae_check"]:.4f}; ' + '; '.join(
        f'{n} {row[n]["px"]} px, under 2/3/4: ' + '/'.join(f'{100 * row[n][f"under_{k}"]:.1f}' for k in (2, 3, 4))
        + ' %, |err| under 2/3/4: ' + '/'.join(f'{100 * row[n][f"err_under_{k}"]:.1f}' for k in (2, 3, 4)) + ' %'
        for n in sets), LOG)
    bc.log(f'     wrong faces (face, width px, pixels): {row["wrong_faces"]}', LOG)
with open(os.path.join(OUT, 'p12_measure.json'), 'w') as f:
    json.dump(res, f, indent=1)
