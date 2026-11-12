"""Bake prototype, steps 5 to 8: target layouts, copy from the master, reference bakes, measurement.

Run (CPU wrapper, no blend file), after step3_master.py for the same tag:
    blender -b --factory-startup --python step5_layouts.py -- tag=panel samples=64 gt_samples=1024 layouts=abcdefg

Layouts are made on copies of the object's UV map (its material's map) in the extracted scene; the object's own map is
never changed:
  a unchanged; b every island rotated 37 degrees about its centre, then packed without scaling; c, d, e islands scaled
  0.5x, 1.9x, 2.5x about their centres, then packed; f Smart UV Project on a copy, scaled to layout (a)'s median
  density, then packed; g layout (a) at a quarter of the texture size.
Packing: shelf, islands 16 px apart (8 px padding each), no rotation, no scaling.
For each layout: GT = direct bake with gt_samples, DIRECT = direct bake with `samples` (the master's count), COPY =
master copied (bake_copy.py: own-triangle sampling, surface-aware bilinear read within 30 degrees), all with 8 px
padding (Cycles: Adjacent Faces margin). Errors against GT over pixels
inside triangles, in a 2 px band along the layout's island borders, in the rest of the islands, and in the padding.
Writes tests/_work/ao_bake/layouts/<tag>/results.json and PNGs.
"""
import json
import math
import os
import sys
import time

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bake_common as bc  # noqa: E402
import bake_copy as bcp  # noqa: E402
import bake_geom as bg  # noqa: E402

args = dict(a.split('=', 1) for a in (sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []))
tag = args.get('tag', 'panel')
N = int(args.get('samples', 64))
NGT = int(args.get('gt_samples', 1024))
LAYOUTS = args.get('layouts', 'abcdefg')
PAD = 8
MODE = args.get('mode', 'tri')
SURF = args.get('surface_deg', '30')
SURF_COS = None if SURF == 'off' else math.cos(math.radians(float(SURF)))
KMAX = int(args.get('kmax', 16))
SUFFIX = args.get('suffix', '')
OUT = os.path.join(bc.WORK, 'layouts', tag + SUFFIX)
os.makedirs(OUT, exist_ok=True)
LOG = os.path.join(OUT, 'log.txt')
t_all = time.time()

target, info = bc.load_scene(tag)
S = int(info['texture_size'])
pos, tris, cn, uvs = bc.mesh_arrays(target.data)
uv0 = uvs[info['uv']]
wt = bg.weld_ids(pos)[tris]
a3 = bg.tri_areas_3d(pos, tris)

# master
mz = np.load(os.path.join(bc.WORK, 'master', f'master_{tag}.npz'))
Mimg = bc.read_png16(os.path.join(bc.WORK, 'master', f'master_{tag}.png'))
mH, mW = Mimg.shape
rect_id = np.full((mH, mW), -1, dtype=np.int64)
for i, (x, y, w, h) in enumerate(mz['rects']):
    rect_id[y:y + h, x:x + w] = i
master = dict(muv=mz['muv'], image=Mimg, rect_id=rect_id, filled=mz['filled'], island=mz['island'],
              face_map=mz['face_map'] if 'face_map' in mz.files else None)
DM = float(mz['density'])
bc.log(f'{tag}: {info["target"]}, {len(tris)} tris, texture {S}, master {mW}x{mH} at {DM:.1f} px/m', LOG)


def pack(uvpx, isl, sep=2 * PAD, width=None):
    """Shelf-pack islands (no rotation, no scaling); returns new uvpx."""
    out = uvpx.copy()
    ids = np.unique(isl)
    boxes = []
    for i in ids:
        P = uvpx[isl == i].reshape(-1, 2)
        lo, hi = P.min(axis=0), P.max(axis=0)
        boxes.append((i, lo, hi - lo))
    width = width or S
    width = max(width, int(math.ceil(max(b[2][0] for b in boxes))) + sep)
    boxes.sort(key=lambda b: (-b[2][1], -b[2][0], b[0]))
    x = y = shelf = 0
    for i, lo, ext in boxes:
        w_, h_ = int(math.ceil(ext[0])) + sep, int(math.ceil(ext[1])) + sep
        if x + w_ > width:
            x, y, shelf = 0, y + shelf, 0
        out[isl == i] = uvpx[isl == i] - lo + np.array([x + PAD, y + PAD])
        x += w_
        shelf = max(shelf, h_)
    return out


def transform_islands(uvpx, isl, scale=1.0, angle=0.0):
    out = uvpx.copy()
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    R = np.array([[c, -s], [s, c]]) * scale
    for i in np.unique(isl):
        P = uvpx[isl == i]
        flat = P.reshape(-1, 2)
        ctr = (flat.min(axis=0) + flat.max(axis=0)) / 2
        out[isl == i] = (P - ctr) @ R.T + ctr
    return out


def smart_uv():
    dup = target.copy()
    dup.data = target.data.copy()
    bpy.context.scene.collection.objects.link(dup)
    layer = dup.data.uv_layers.new(name='SMART')
    dup.data.uv_layers.active = layer
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    dup.select_set(True)
    bpy.context.view_layer.objects.active = dup
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=math.radians(66.0), island_margin=0.0, scale_to_bounds=False)
    bpy.ops.object.mode_set(mode='OBJECT')
    _, _, _, u2 = bc.mesh_arrays(dup.data)
    bpy.data.objects.remove(dup)
    return u2['SMART']


isl_a = bg.uv_islands(wt, uv0)
layouts = {}
base = uv0 * S
med_a = bg.weighted_median(bg.densities(pos, tris, base)[a3 > 0], a3[a3 > 0])
if 'a' in LAYOUTS:
    layouts['a'] = (base, S, isl_a)
if 'b' in LAYOUTS:
    layouts['b'] = (pack(transform_islands(base, isl_a, angle=37.0), isl_a), S, isl_a)
for key, sc in (('c', 0.5), ('d', 1.9), ('e', 2.5)):
    if key in LAYOUTS:
        layouts[key] = (pack(transform_islands(base, isl_a, scale=sc), isl_a, width=int(S * max(sc, 1))), S, isl_a)
if 'f' in LAYOUTS:
    su = smart_uv()
    isl_f = bg.uv_islands(wt, su)
    d_f = bg.weighted_median(bg.densities(pos, tris, su * S)[a3 > 0], a3[a3 > 0])
    layouts['f'] = (pack(su * S * (med_a / d_f), isl_f), S, isl_f)
if 'g' in LAYOUTS:
    layouts['g'] = (uv0 * (S // 4), S // 4, isl_a)


def stats(d):
    if d.size == 0:
        return None
    a = np.abs(d)
    return dict(mae=float(a.mean()), rms=float(np.sqrt((d * d).mean())), p99=float(np.percentile(a, 99)),
                max=float(a.max()), bias=float(d.mean()), px=int(d.size))


def ring_band(lab, inside, width=2):
    """inside pixels within `width` px (8-neighbour steps) of a pixel with another label or none."""
    H_, W_ = lab.shape
    edge = np.zeros_like(inside)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            sh = np.full_like(lab, -2)
            sh[max(dy, 0):H_ + min(dy, 0), max(dx, 0):W_ + min(dx, 0)] = \
                lab[max(-dy, 0):H_ + min(-dy, 0), max(-dx, 0):W_ + min(-dx, 0)]
            edge |= inside & (sh != lab)
    band = edge.copy()
    for _ in range(width - 1):
        grown = band.copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                sh = np.zeros_like(band)
                sh[max(dy, 0):H_ + min(dy, 0), max(dx, 0):W_ + min(dx, 0)] = \
                    band[max(-dy, 0):H_ + min(-dy, 0), max(-dx, 0):W_ + min(-dx, 0)]
                grown |= sh
        band = grown & inside
    return band


results = dict(tag=tag, target=info['target'], texture=S, master_density=DM, median_density_a=med_a,
               samples=N, gt_samples=NGT, padding=PAD, copy_mode=MODE, kmax=KMAX, surface_deg=SURF, layouts={})
for key, (uvpx, size, tisl) in layouts.items():
    t0 = time.time()
    crop = bg.crop_box(uvpx, PAD + 4)
    x0, y0, w, h = crop
    bake_uv = (uvpx - np.array([x0, y0])) / np.array([w, h])
    bc.set_uv(target.data, 'BAKE_UV', bake_uv)
    dens = bg.densities(pos, tris, uvpx)
    ratio = np.where(dens > 0, DM / np.maximum(dens, 1e-30), np.inf)
    r_med = float(np.median(ratio[np.isfinite(ratio)]))
    k = 2  # minimum samples per pixel axis; bake_copy raises it per triangle with the footprint
    tc = time.time()
    copy, cinfo, owner_c, steps, count_c = bcp.copy_master(pos, tris, uvpx, tisl, master, crop, k, PAD,
                                                                 outside_mode=MODE, kmax=KMAX, surface_cos=SURF_COS)
    t_copy = time.time() - tc
    imgs = {}
    times = {}
    for name, ns, seed in (('gt', NGT, 101), ('direct', N, 102)):
        img = bc.new_float_image(f'{key}_{name}', w, h)
        times[name] = bc.bake(target, img, 'BAKE_UV', ns, seed, margin=PAD, margin_type='ADJACENT_FACES')
        imgs[name] = bc.image_to_array(img)
        bpy.data.images.remove(img)
    gt, direct = imgs['gt'], imgs['direct']
    inside = (owner_c >= 0) & (gt >= 0) & (direct >= 0) & (copy >= 0)
    lab = np.where(owner_c >= 0, tisl[np.maximum(owner_c, 0)], -1)
    band = ring_band(lab, inside, 2)
    interior = inside & ~band
    np.save(os.path.join(OUT, f'{key}_inside.npy'), inside)
    np.save(os.path.join(OUT, f'{key}_band.npy'), band)
    padm = (owner_c < 0) & (steps > 0) & (steps <= PAD) & (gt >= 0) & (copy >= 0) & (direct >= 0)
    above = ratio < 1.0  # target denser than the master
    above_px = inside & np.isin(owner_c, np.nonzero(above)[0])
    res = dict(size=size, crop=crop, k=k, ratio_median=r_med, faces_above_master=int(above.sum()),
               area_share_above_master=float(a3[above].sum() / a3.sum()), copy_info=cinfo,
               times=dict(gt_s=round(times['gt'], 2), direct_s=round(times['direct'], 2), copy_s=round(t_copy, 2)),
               missing_inside=dict(gt=int(((owner_c >= 0) & (gt < 0)).sum()),
                                   direct=int(((owner_c >= 0) & (direct < 0)).sum()),
                                   copy=int(((owner_c >= 0) & (copy < 0)).sum())),
               padding_gt_zero_px=int((padm & (gt == 0)).sum()),
               fits_texture=bool(uvpx.reshape(-1, 2).max() <= size and uvpx.reshape(-1, 2).min() >= 0))
    for region, msk in (('inside', inside), ('interior', interior), ('seam_band', band), ('padding', padm),
                        ('padding_gt_nonzero', padm & (gt > 0)),
                        ('above_master', above_px), ('stacked', inside & (count_c > 1))):
        res[region] = dict(copy=stats((copy - gt)[msk]), direct=stats((direct - gt)[msk]))
    ci, di = res['inside']['copy'], res['inside']['direct']
    res['fl3_met'] = bool(ci['mae'] <= di['mae'] and ci['p99'] <= di['p99'])
    cb, cint = res['seam_band']['copy'], res['interior']['copy']
    res['fl4_ratio'] = float(cb['mae'] / cint['mae']) if cb and cint else None
    res['fl4_met_numeric'] = bool(res['fl4_ratio'] is not None and res['fl4_ratio'] <= 1.5)
    results['layouts'][key] = res
    # images
    for name, a in (('gt', gt), ('direct', direct), ('copy', copy)):
        bc.write_png(os.path.join(OUT, f'{key}_{name}.png'), np.where(a >= 0, a, 0.0))
    for name, a in (('copy', copy), ('direct', direct)):
        m_ = (gt >= 0) & (a >= 0)
        rgb = np.zeros((h, w, 3))
        d = np.where(m_, a - gt, 0.0) * 8
        rgb[..., 0] = np.clip(d, 0, 1)
        rgb[..., 1] = np.clip(np.abs(d), 0, 1) * 0.0
        rgb[..., 2] = np.clip(-d, 0, 1)
        rgb[(owner_c < 0) & m_] += 0.08  # padding area slightly grey
        bc.write_png(os.path.join(OUT, f'{key}_diff_{name}_x8.png'), np.clip(rgb, 0, 1), bits=8)
    bc.log(f'  {key}: crop {w}x{h} k levels {cinfo["k_levels"]} cap px {cinfo["px_at_k_cap"]} ratio {r_med:.2f}; inside MAE copy {ci["mae"]:.4f} direct {di["mae"]:.4f}, '
           f'P99 copy {ci["p99"]:.4f} direct {di["p99"]:.4f} -> FL3 {"MET" if res["fl3_met"] else "NOT MET"}; '
           f'seam/interior {res["fl4_ratio"]:.2f}; padding MAE copy '
           f'{res["padding"]["copy"]["mae"] if res["padding"]["copy"] else float("nan"):.4f} direct '
           f'{res["padding"]["direct"]["mae"] if res["padding"]["direct"] else float("nan"):.4f}; above master '
           f'{res["faces_above_master"]} faces; times {res["times"]}; {time.time() - t0:.1f} s', LOG)
    with open(os.path.join(OUT, 'results.json'), 'w') as f:
        json.dump(results, f, indent=1)
results['total_s'] = round(time.time() - t_all, 1)
with open(os.path.join(OUT, 'results.json'), 'w') as f:
    json.dump(results, f, indent=1)
bc.log(f'done in {results["total_s"]} s', LOG)
