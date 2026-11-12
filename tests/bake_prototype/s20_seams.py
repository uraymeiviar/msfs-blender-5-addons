"""Session 20, finish line 3: no tile seams. The master baked in tiles (tests/_work/ao_bake/s20/<tag>.bake, from
s17_round_trip.py -- tag=<tag> tile=512 sub=s20) against the untiled master of Session 17 (copied to
tests/_work/ao_bake/s20/untiled/<tag>/ before the re-run).

Run: blender -b --factory-startup --python s20_seams.py -- tags=panel,cap,knob tile=512 [sub=s20] [name=seams]

sub: the folder (in tests/_work/ao_bake/) of the masters compared with the untiled ones; for the control, an untiled
bake with other seeds (FSS_AO_BAKE_SEED_OFFSET=1), the band is the one of the given tile size.

Per object, on the pixels filled in both masters: MAE; the MAE in a band of 2 px on each side of every inner tile
border, and elsewhere, and their ratio; whether the layout, filled pixels and face map are identical. Writes
s20/seams.json.
"""
import importlib.util
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
WORK = os.path.join(REPO, 'tests', '_work', 'ao_bake', 's20')
spec = importlib.util.spec_from_file_location('core', os.path.join(REPO, 'fss_blender_tools', 'ao_bake_core.py'))
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)

args = dict(a.split('=', 1) for a in (sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []))
tags = args.get('tags', 'panel,cap,knob').split(',')
tile = int(args.get('tile', 512))
SUB = os.path.join(REPO, 'tests', '_work', 'ao_bake', args.get('sub', 's20'))
out = {}
for tag in tags:
    folder = os.path.join(SUB, f'{tag}.bake')
    ufolder = os.path.join(WORK, 'untiled', tag)
    stem = [f[:-7] for f in os.listdir(folder) if f.endswith('.ao.png')][0]
    t = core.load_master(folder, stem)
    u = core.load_master(ufolder, stem)
    with open(os.path.join(folder, 'index.json')) as f:
        entry = json.load(f)['masters'][stem]
    H, W = t['image'].shape
    same = dict(shape=t['image'].shape == u['image'].shape, muv=bool(np.allclose(t['muv'], u['muv'], atol=1e-9)),
                filled=bool(np.array_equal(t['filled'], u['filled'])),
                face_map=bool(np.array_equal(t['face_map'], u['face_map'])))
    both = t['filled'] & u['filled']
    d = np.abs(t['image'].astype(np.float64) - u['image']) / 65535.0
    bx = np.zeros(W, bool)
    by = np.zeros(H, bool)
    for b in range(tile, W, tile):
        bx[max(0, b - 2):b + 2] = True
    for b in range(tile, H, tile):
        by[max(0, b - 2):b + 2] = True
    band = (bx[None, :] | by[:, None]) & both
    rest = (~(bx[None, :] | by[:, None])) & both
    mae = float(d[both].mean())
    mb = float(d[band].mean()) if band.any() else None
    mr = float(d[rest].mean())
    out[tag] = dict(W=W, H=H, tile=tile, n_tiles=entry['tiles']['n'], same=same, px=int(both.sum()),
                    filled_differ_px=int((t['filled'] != u['filled']).sum()), mae=mae,
                    max=float(d[both].max()), band_px=int(band.sum()), mae_band=mb, mae_elsewhere=mr,
                    ratio=(mb / mr) if mb is not None and mr > 0 else None,
                    met=bool(mae <= 0.02 and (mb is None or mb / mr <= 1.5)))
    print('SEAMS', tag, json.dumps(out[tag]), flush=True)
with open(os.path.join(WORK, args.get('name', 'seams') + '.json'), 'w') as f:
    json.dump(out, f, indent=1)
