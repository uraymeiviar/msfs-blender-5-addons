"""Session 14, step 1 and 2 (P23): a fair reference at 4 x the layout's resolution, and the copy and the direct bake
measured against it and against the old GT.

Run (CPU cap, no blend file), after step5_layouts.py with the 4 x master (Session 11's `_s11x4` outputs):
    blender -b --factory-startup --python s14_fair_ref.py -- tag=panel suffix=_s11x4 samples=1024 factor=4
        layouts=abcdefg

The rule of the fair reference (FAIR):
1. The layout (the same as step5_layouts.py makes, checked against its crop) is baked by Cycles directly, AO as the
   GT, at `factor` x the layout's resolution (each layout pixel is `factor` x `factor` hi-res pixels), `samples` per
   hi-res pixel, margin 0, seed 301. Large crops are baked in tiles of 512 x 512 layout pixels (the UV map shifted
   and scaled per tile; tiles without a triangle are skipped), so the image stays small.
2. Each layout pixel whose centre lies on a triangle (the copy's owner, `bake_geom.rasterize_ids` at k = 1) takes the
   mean of the hi-res pixels inside it whose centre lies on that same triangle (`rasterize_ids` at k = factor, whose
   sample points are the hi-res pixel centres) and that Cycles baked. This is the copy's own rule (bake_copy.py,
   outside_mode 'tri': only points on the pixel's own triangle count), with Cycles' hi-res pixels as the points.
3. A layout pixel with no such hi-res pixel (its triangle covers no hi-res centre in it) has no fair value; it is
   left out of every comparison against FAIR and counted (`undefined`).
Then copy, direct and GT are measured against FAIR, and copy and direct against GT, on the same pixels (inside and
FAIR defined), split into the seam band and the interior of step5_layouts.py. Agreement of GT and FAIR: interior
pixels whose factor x factor hi-res centres all lie on the pixel's own triangle (inside a face, away from its edges).
Writes <k>_fair.npy (float32, NaN where undefined), <k>_fair_n.npy (hi-res pixels used), <k>_fair.png and
s14_fair.json into tests/_work/ao_bake/layouts/<tag><suffix>/.
"""
import json
import os
import sys
import time

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bake_common as bc  # noqa: E402
import bake_geom as bg  # noqa: E402
import bake_layouts as bl  # noqa: E402

args = dict(a.split('=', 1) for a in (sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []))
tag = args.get('tag', 'panel')
SUF = args.get('suffix', '_s11x4')
NS = int(args.get('samples', 1024))
F = int(args.get('factor', 4))
LAYOUTS = args.get('layouts', 'abcdefg')
TILE = int(args.get('tile', 512))  # layout pixels per tile side
PAD = 8
SEED = 301
D = os.path.join(bc.WORK, 'layouts', tag + SUF)
LOG = os.path.join(D, 's14_fair.log.txt')
if os.path.exists(LOG):
    os.remove(LOG)
t_all = time.time()

with open(os.path.join(D, 'results.json')) as f_:
    res11 = json.load(f_)
target, info = bc.load_scene(tag)
S = int(info['texture_size'])
pos, tris, cn, uvs = bc.mesh_arrays(target.data)
uv0 = uvs[info['uv']]
wt = bg.weld_ids(pos)[tris]
layouts, _ = bl.make_layouts(target, pos, tris, wt, uv0, S, PAD, LAYOUTS)
bc.log(f'{tag}{SUF}: {len(tris)} tris; FAIR at {F} x the layout resolution, {NS} samples per hi-res pixel, '
       f'tiles {TILE} layout px', LOG)


def stats(d):
    if d.size == 0:
        return None
    a = np.abs(d)
    return dict(mae=float(a.mean()), p99=float(np.percentile(a, 99)), max=float(a.max()), bias=float(d.mean()),
                wrong=int((a > 0.1).sum()), px=int(d.size))


def region_stats(img, ref, ins, band):
    r = dict(inside=stats((img - ref)[ins]), interior=stats((img - ref)[ins & ~band]),
             seam_band=stats((img - ref)[ins & band]))
    r['seam_interior'] = (r['seam_band']['mae'] / r['interior']['mae']
                          if r['seam_band'] and r['interior'] and r['interior']['mae'] > 0 else None)
    if r['inside']:
        a = np.where(ins, np.abs(img - ref), -1.0)
        j, i = np.unravel_index(int(np.argmax(a)), a.shape)
        r['max_at'] = [int(i), int(j)]
    return r


out = dict(tag=tag, suffix=SUF, factor=F, samples=NS, seed=SEED, tile=TILE, layouts={})
for key, (uvpx, size, tisl) in layouts.items():
    t0 = time.time()
    crop = bg.crop_box(uvpx, PAD + 4)
    x0, y0, w, h = crop
    assert list(crop) == list(res11['layouts'][key]['crop']), (key, crop, res11['layouts'][key]['crop'])
    copy = bc.read_png16(os.path.join(D, f'{key}_copy.png'))
    gt = bc.read_png16(os.path.join(D, f'{key}_gt.png'))
    direct = bc.read_png16(os.path.join(D, f'{key}_direct.png'))
    ins = np.load(os.path.join(D, f'{key}_inside.npy'))
    band = np.load(os.path.join(D, f'{key}_band.npy'))
    assert copy.shape == (h, w)
    owner_c, _ = bg.rasterize_ids(uvpx, w, h, 1, x0, y0)
    fsum = np.zeros((h, w))
    fcnt = np.zeros((h, w), dtype=np.int32)
    n_hi_baked = n_hi_owned = n_hi_missing = n_hi_extra = 0
    t_bake = 0.0
    n_tiles = 0
    for ty in range(0, h, TILE):
        for tx in range(0, w, TILE):
            tw, th = min(TILE, w - tx), min(TILE, h - ty)
            oc = owner_c[ty:ty + th, tx:tx + tw]
            if not (oc >= 0).any():
                continue
            n_tiles += 1
            bake_uv = (uvpx - np.array([x0 + tx, y0 + ty])) / np.array([tw, th])
            bc.set_uv(target.data, 'BAKE_UV', bake_uv)
            img = bc.new_float_image(f'{key}_fair_{tx}_{ty}', tw * F, th * F)
            t_bake += bc.bake(target, img, 'BAKE_UV', NS, SEED, margin=0)
            hi = bc.image_to_array(img)
            bpy.data.images.remove(img)
            own_s, _ = bg.rasterize_ids(uvpx, tw, th, F, x0 + tx, y0 + ty)
            n_hi_baked += int((hi >= 0).sum())
            n_hi_owned += int((own_s >= 0).sum())
            n_hi_missing += int(((own_s >= 0) & (hi < 0)).sum())
            n_hi_extra += int(((own_s < 0) & (hi >= 0)).sum())
            same = (own_s.reshape(th, F, tw, F) == oc[:, None, :, None]) & (hi.reshape(th, F, tw, F) >= 0)
            same &= (oc >= 0)[:, None, :, None]
            v = np.where(same, hi.reshape(th, F, tw, F), 0.0)
            fsum[ty:ty + th, tx:tx + tw] += v.sum(axis=(1, 3))
            fcnt[ty:ty + th, tx:tx + tw] += same.sum(axis=(1, 3)).astype(np.int32)
    fair = np.where(fcnt > 0, fsum / np.maximum(fcnt, 1), np.nan)
    np.save(os.path.join(D, f'{key}_fair.npy'), fair.astype(np.float32))
    np.save(os.path.join(D, f'{key}_fair_n.npy'), fcnt.astype(np.uint8))
    bc.write_png(os.path.join(D, f'{key}_fair.png'), np.where(np.isfinite(fair), fair, 0.0))
    insf = ins & np.isfinite(fair)
    full = insf & ~band & (fcnt == F * F)
    fr = np.where(np.isfinite(fair), fair, 0.0)
    L = dict(crop=crop, tiles=n_tiles, bake_s=round(t_bake, 1),
             hi_px=dict(baked=n_hi_baked, owned=n_hi_owned, owned_not_baked=n_hi_missing,
                        baked_not_owned=n_hi_extra),
             inside_px=int(ins.sum()), undefined_px=int((ins & ~np.isfinite(fair)).sum()),
             undefined_band_px=int((ins & band & ~np.isfinite(fair)).sum()),
             fair_n_hist={int(n): int((insf & (fcnt == n)).sum()) for n in np.unique(fcnt[insf])},
             agreement=dict(px=int(full.sum()), gt_vs_fair=stats((gt - fr)[full]),
                            direct_vs_fair=stats((direct - fr)[full]), copy_vs_fair=stats((copy - fr)[full]),
                            copy_vs_gt=stats((copy - gt)[full])),
             vs_fair=dict(copy=region_stats(copy, fr, insf, band), direct=region_stats(direct, fr, insf, band),
                          gt=region_stats(gt, fr, insf, band)),
             vs_gt=dict(copy=region_stats(copy, gt, insf, band), direct=region_stats(direct, gt, insf, band)),
             vs_gt_all_inside=dict(copy=region_stats(copy, gt, ins, band), direct=region_stats(direct, gt, ins, band)))
    for ref in ('vs_fair', 'vs_gt'):
        c_, d_ = L[ref]['copy']['inside'], L[ref]['direct']['inside']
        L[ref]['max_ratio'] = c_['max'] / d_['max']
    out['layouts'][key] = L
    ag = L['agreement']['gt_vs_fair']
    cf, df = L['vs_fair']['copy'], L['vs_fair']['direct']
    cg, dg = L['vs_gt']['copy'], L['vs_gt']['direct']
    bc.log(f'  {key}: crop {w}x{h}, {n_tiles} tiles, bake {t_bake:.1f} s; hi px baked {n_hi_baked} owned {n_hi_owned} '
           f'(owned not baked {n_hi_missing}, baked not owned {n_hi_extra}); undefined {L["undefined_px"]} of '
           f'{L["inside_px"]}; GT vs FAIR (full interior, {ag["px"]} px) MAE {ag["mae"]:.4f} bias {ag["bias"]:+.4f} '
           f'max {ag["max"]:.3f}', LOG)
    bc.log(f'      vs FAIR: copy MAE {cf["inside"]["mae"]:.4f} P99 {cf["inside"]["p99"]:.4f} max {cf["inside"]["max"]:.3f} '
           f'at {cf["max_at"]} s/i {cf["seam_interior"]:.2f} wrong {cf["inside"]["wrong"]}; direct MAE '
           f'{df["inside"]["mae"]:.4f} P99 {df["inside"]["p99"]:.4f} max {df["inside"]["max"]:.3f} wrong '
           f'{df["inside"]["wrong"]}; ratio {L["vs_fair"]["max_ratio"]:.2f}', LOG)
    bc.log(f'      vs GT:   copy MAE {cg["inside"]["mae"]:.4f} P99 {cg["inside"]["p99"]:.4f} max {cg["inside"]["max"]:.3f} '
           f'at {cg["max_at"]} s/i {cg["seam_interior"]:.2f} wrong {cg["inside"]["wrong"]}; direct MAE '
           f'{dg["inside"]["mae"]:.4f} P99 {dg["inside"]["p99"]:.4f} max {dg["inside"]["max"]:.3f} wrong '
           f'{dg["inside"]["wrong"]}; ratio {L["vs_gt"]["max_ratio"]:.2f}; {time.time() - t0:.1f} s', LOG)
    with open(os.path.join(D, 's14_fair.json'), 'w') as f_:
        json.dump(out, f_, indent=1)
out['total_s'] = round(time.time() - t_all, 1)
with open(os.path.join(D, 's14_fair.json'), 'w') as f_:
    json.dump(out, f_, indent=1)
bc.log(f'done in {out["total_s"]} s', LOG)
