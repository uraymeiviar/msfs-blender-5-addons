"""Session 14, step 3 (P24, P25): the pixel of panel (b)'s maximum copy error at 4 x, and the P25 pixels of Session 11.

Run (CPU cap, no bake), after s14_fair_ref.py for the same tag and suffix:
    blender -b --factory-startup --python s14_panel_b.py -- tag=panel suffix=_s11x4 master=_s11x4 layout=b top=5
        extra=g:13:44

For the `top` worst inside pixels of the layout (|copy - GT|), and Session 11's P25 pixels (layouts d and e):
- the pixel's face (the copy's owner), its size (area, smallest height) in layout and master pixels;
- the face's three edges: the 3D neighbour across each (welded vertices), the angle between their normals, whether
  the edge is open (no neighbour), a seam of the layout (neighbour in another layout island) or a border of the
  master's islands (neighbour in another master island);
- distances from the pixel centre to the nearest open edge, layout seam and master island border (layout px);
- copy, GT, FAIR (s14_fair_ref.py) with its hi-res count, direct, and the 3 x 3 neighbourhood of copy, GT and FAIR;
- the pixel re-sampled from the master (8 x 8 points on its own triangle, the copy's read) and which master texels
  that read uses (own core, other core, skirt or fill; faces with their weight, mean texel value and angle).
Writes s14_panel_b.json and s14_panel_b.log.txt into tests/_work/ao_bake/layouts/<tag><suffix>/.
"""
import json
import math
import os
import sys

import bpy  # noqa: F401
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bake_common as bc  # noqa: E402
import bake_geom as bg  # noqa: E402
import bake_layouts as bl  # noqa: E402

args = dict(a.split('=', 1) for a in (sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []))
tag = args.get('tag', 'panel')
SUF = args.get('suffix', '_s11x4')
MS = args.get('master', '_s11x4')
LAY = args.get('layout', 'b')
TOP = int(args.get('top', 5))
PAD = 8
SURF_COS = math.cos(math.radians(30.0))
D = os.path.join(bc.WORK, 'layouts', tag + SUF)
LOG = os.path.join(D, 's14_panel_b.log.txt')
if os.path.exists(LOG):
    os.remove(LOG)
P25 = [('d', 284, 778, 122), ('d', 284, 778, 124), ('d', 475, 456, 173), ('d', 475, 455, 173),
       ('e', 475, 591, 224), ('e', 475, 586, 224), ('e', 24, 560, 209), ('e', 24, 560, 210),
       ('d', 71, 747, 12), ('d', 71, 748, 12), ('e', 476, 573, 224)]

target, info = bc.load_scene(tag)
S = int(info['texture_size'])
pos, tris, cn, uvs = bc.mesh_arrays(target.data)
uv0 = uvs[info['uv']]
wt = bg.weld_ids(pos)[tris]
em = bg.edge_map(wt)
P3 = pos[tris]
tri_normal = np.cross(P3[:, 1] - P3[:, 0], P3[:, 2] - P3[:, 0])
tri_normal /= np.maximum(np.linalg.norm(tri_normal, axis=1, keepdims=True), 1e-30)
a3 = bg.tri_areas_3d(pos, tris)
keys = ''.join(sorted(set(LAY) | {p[0] for p in P25}))
layouts, _ = bl.make_layouts(target, pos, tris, wt, uv0, S, PAD, keys)

mz = np.load(os.path.join(bc.WORK, 'master', f'master_{tag}{MS}.npz'))
Mimg = bc.read_png16(os.path.join(bc.WORK, 'master', f'master_{tag}{MS}.png'))
mH, mW = Mimg.shape
rid = np.full((mH, mW), -1, dtype=np.int64)
for i_, (x_, y_, w_, h_) in enumerate(mz['rects']):
    rid[y_:y_ + h_, x_:x_ + w_] = i_
m = dict(muv=mz['muv'], img=Mimg, rect_id=rid, filled=mz['filled'], island=mz['island'], face_map=mz['face_map'],
         density=float(mz['density']), W=mW, H=mH, core_owner=bg.rasterize_ids(mz['muv'], mW, mH)[0])


def angle(a, b):
    return round(math.degrees(math.acos(max(-1.0, min(1.0, float(tri_normal[a] @ tri_normal[b]))))), 1)


def master_read(tri_ids, bary):
    """The copy's read (bake_copy.copy_master.read with surface_cos): clamp into the island, surface-aware bilinear."""
    muv, M, W, H = m['muv'], m['img'], m['W'], m['H']
    mp = np.einsum('nk,nkd->nd', bary, muv[tri_ids])
    xi = np.clip(np.floor(mp[:, 0]).astype(np.int64), 0, W - 1)
    yi = np.clip(np.floor(mp[:, 1]).astype(np.int64), 0, H - 1)
    bad = ~((m['rect_id'][yi, xi] == m['island'][tri_ids]) & m['filled'][yi, xi])
    if bad.any():
        bb = np.clip(bary[bad], 0, None)
        bb /= np.maximum(bb.sum(axis=1, keepdims=True), 1e-30)
        mp[bad] = np.einsum('nk,nkd->nd', bb, muv[tri_ids[bad]])
    fx, fy = mp[:, 0] - 0.5, mp[:, 1] - 0.5
    xa, ya = np.floor(fx).astype(np.int64), np.floor(fy).astype(np.int64)
    ax, ay = fx - xa, fy - ya
    acc = np.zeros(len(mp))
    wsum = np.zeros(len(mp))
    nt = tri_normal[tri_ids]
    kinds = dict(own_core=0.0, other_core=0.0, skirt_or_fill=0.0)
    per_face = {}
    for dx, dy, wgt in ((0, 0, (1 - ax) * (1 - ay)), (1, 0, ax * (1 - ay)), (0, 1, (1 - ax) * ay), (1, 1, ax * ay)):
        xc, yc = np.clip(xa + dx, 0, W - 1), np.clip(ya + dy, 0, H - 1)
        f = m['face_map'][yc, xc]
        ok = (f >= 0) & (np.einsum('nd,nd->n', tri_normal[np.maximum(f, 0)], nt) >= SURF_COS)
        wv = np.where(ok, wgt, 0.0)
        acc += wv * M[yc, xc]
        wsum += wv
        co = m['core_owner'][yc, xc]
        for n in np.nonzero(ok & (wgt > 0))[0]:
            w_ = float(wgt[n])
            kind = 'own_core' if co[n] == tri_ids[n] else ('other_core' if co[n] >= 0 else 'skirt_or_fill')
            kinds[kind] += w_
            pf = per_face.setdefault(int(f[n]), [0.0, 0.0])
            pf[0] += w_
            pf[1] += w_ * float(M[yc[n], xc[n]])
    plain = bg.bilinear(M, mp[:, 0], mp[:, 1])
    vals = np.where(wsum > 1e-9, acc / np.maximum(wsum, 1e-30), plain)
    tot = max(sum(kinds.values()), 1e-30)
    faces_ = sorted(per_face.items(), key=lambda kv: -kv[1][0])[:5]
    br = dict(kinds={k: round(v / tot, 3) for k, v in kinds.items()},
              faces=[(fc, round(v[0] / tot, 3), round(v[1] / max(v[0], 1e-30), 3), angle(fc, int(tri_ids[0])))
                     for fc, v in faces_])
    return vals, br


def seg_dist(p, A, B):
    d = B - A
    L2 = float(d @ d)
    s = 0.0 if L2 <= 0 else float(np.clip((p - A) @ d / L2, 0, 1))
    return float(np.linalg.norm(p - (A + s * d)))


def edge_classes(uvpx, tisl):
    """Per edge (t, i, j) of every face: (neighbour or -1, open, layout seam, master border)."""
    out_ = []
    for key_, lst in em.items():
        for (t, i, j) in lst:
            others = [u for (u, _, _) in lst if u != t]
            u = others[0] if others else -1
            out_.append((t, i, j, u, u < 0, u < 0 or tisl[u] != tisl[t],
                         u < 0 or m['island'][u] != m['island'][t]))
    return out_


cache = {}


def load_layout(key):
    if key not in cache:
        uvpx, size, tisl = layouts[key]
        x0, y0, w, h = bg.crop_box(uvpx, PAD + 4)
        imgs = {n: bc.read_png16(os.path.join(D, f'{key}_{n}.png')) for n in ('copy', 'gt', 'direct')}
        imgs['fair'] = np.load(os.path.join(D, f'{key}_fair.npy')).astype(np.float64)
        imgs['fair_n'] = np.load(os.path.join(D, f'{key}_fair_n.npy'))
        imgs['inside'] = np.load(os.path.join(D, f'{key}_inside.npy'))
        imgs['band'] = np.load(os.path.join(D, f'{key}_band.npy'))
        owner, _ = bg.rasterize_ids(uvpx, w, h, 1, x0, y0)
        cache[key] = dict(uvpx=uvpx, tisl=tisl, crop=(x0, y0, w, h), owner=owner, edges=edge_classes(uvpx, tisl), **imgs)
    return cache[key]


def describe(key, i, j, label):
    Lz = load_layout(key)
    uvpx, (x0, y0, w, h) = Lz['uvpx'], Lz['crop']
    t = int(Lz['owner'][j, i])
    p = np.array([x0 + i + 0.5, y0 + j + 0.5])
    tri_uv = uvpx[t]
    area_l = abs(float(np.cross(tri_uv[1] - tri_uv[0], tri_uv[2] - tri_uv[0]))) / 2
    hgt = min(2 * area_l / max(np.linalg.norm(tri_uv[(k + 2) % 3] - tri_uv[(k + 1) % 3]), 1e-30) for k in range(3))
    lay_per_m = math.sqrt(area_l / max(a3[t], 1e-30))
    r = dict(label=label, layout=key, pixel=[i, j], face=t, area_layout_px=round(area_l, 2),
             min_height_layout_px=round(hgt, 3), min_height_master_px=round(hgt / lay_per_m * m['density'], 3),
             master_island=int(m['island'][t]), layout_island=int(Lz['tisl'][t]))
    own_edges = []
    dmin = dict(open=np.inf, seam=np.inf, master_border=np.inf)
    for (te, ie, je, u, op, seam, mb) in Lz['edges']:
        dd = seg_dist(p, uvpx[te, ie], uvpx[te, je])
        if op:
            dmin['open'] = min(dmin['open'], dd)
        if seam:
            dmin['seam'] = min(dmin['seam'], dd)
        if mb:
            dmin['master_border'] = min(dmin['master_border'], dd)
        if te == t:
            own_edges.append(dict(neighbour=int(u), angle_deg=angle(t, u) if u >= 0 else None, open=bool(op),
                                  layout_seam=bool(seam), master_border=bool(mb), dist_px=round(dd, 3),
                                  length_layout_px=round(float(np.linalg.norm(uvpx[te, je] - uvpx[te, ie])), 2)))
    r['edges'] = own_edges
    r['dist_px'] = {k: round(v, 3) for k, v in dmin.items()}
    # smallest barycentric coordinate of the pixel centre in the face and in each neighbour (>= 0: inside), with the
    # layout UVs in float64 and as float32 (what Cycles gets): a centre on a shared edge has an ambiguous owner
    cand = [t] + [e['neighbour'] for e in own_edges if e['neighbour'] >= 0]
    r['centre_min_bary'] = {}
    for f in cand:
        b64 = bg.barycentric_many(p[None, :], uvpx[[f]])[0]
        sc = np.array([w, h], dtype=np.float64)
        uv32 = ((uvpx[[f]] - np.array([x0, y0])) / sc).astype(np.float32).astype(np.float64)  # BAKE_UV as stored
        b32 = bg.barycentric_many(((p - np.array([x0, y0])) / sc)[None, :], uv32)[0]
        r['centre_min_bary'][int(f)] = [float(b64.min()), float(b32.min())]
    r['values'] = {n: (None if not np.isfinite(Lz[n][j, i]) else round(float(Lz[n][j, i]), 4))
                   for n in ('copy', 'gt', 'fair', 'direct')}
    r['fair_n'] = int(Lz['fair_n'][j, i])
    r['in_band'] = bool(Lz['band'][j, i])
    nb = {}
    for n in ('copy', 'gt', 'fair'):
        blk = Lz[n][max(j - 1, 0):j + 2, max(i - 1, 0):i + 2]
        nb[n] = np.round(blk[::-1], 3).tolist()  # top row first
    nb['owner'] = Lz['owner'][max(j - 1, 0):j + 2, max(i - 1, 0):i + 2][::-1].tolist()
    r['3x3_top_row_first'] = nb
    L8 = 8
    sub = (np.arange(L8) + 0.5) / L8
    sx, sy = np.meshgrid(sub, sub)
    pts = np.stack([x0 + i + sx.ravel(), y0 + j + sy.ravel()], axis=1)
    bp = bg.barycentric_many(pts, np.repeat(uvpx[[t]], len(pts), axis=0))
    own = (bp >= -1e-9).all(axis=1)
    r['own_points_of_64'] = int(own.sum())
    if own.any():
        v, br = master_read(np.full(int(own.sum()), t), bp[own])
        r['master_resampled'] = round(float(v.mean()), 4)
        r['texels'] = br
    # this face's AO in the master (own core texels) and per neighbour
    co = m['core_owner']
    r['master_face_mean'] = {int(f): round(float(Mimg[co == f].mean()), 4) if (co == f).any() else None
                             for f in [t] + [e['neighbour'] for e in own_edges if e['neighbour'] >= 0]}
    v = r['values']
    bc.log(f'{label} {key} px ({i},{j}) face {t}: copy {v["copy"]} GT {v["gt"]} FAIR {v["fair"]} (n {r["fair_n"]}) '
           f'direct {v["direct"]}; master resampled {r.get("master_resampled")}; band {r["in_band"]}; '
           f'area {r["area_layout_px"]} px, min height {r["min_height_layout_px"]} layout px / '
           f'{r["min_height_master_px"]} master px; dist open {r["dist_px"]["open"]} seam {r["dist_px"]["seam"]} '
           f'master border {r["dist_px"]["master_border"]}', LOG)
    for e in own_edges:
        bc.log(f'    edge: neighbour {e["neighbour"]} angle {e["angle_deg"]} open {e["open"]} seam {e["layout_seam"]} '
               f'master border {e["master_border"]} dist {e["dist_px"]} len {e["length_layout_px"]}', LOG)
    bc.log(f'    texels {r.get("texels")}; master face means {r["master_face_mean"]}; centre min bary (f64, f32) '
           f'{r["centre_min_bary"]}', LOG)
    bc.log(f'    3x3 copy {nb["copy"]} GT {nb["gt"]} FAIR {nb["fair"]} owner {nb["owner"]}', LOG)
    return r


report = dict(tag=tag, suffix=SUF, master=MS, layout=LAY, top=[], p25=[])
Lb = load_layout(LAY)
err = np.where(Lb['inside'], np.abs(Lb['copy'] - Lb['gt']), -1.0)
order = np.argsort(err.ravel())[::-1][:TOP]
for n, idx in enumerate(order):
    j, i = np.unravel_index(int(idx), err.shape)
    report['top'].append(describe(LAY, int(i), int(j), f'{LAY} top {n + 1} (|copy-GT| {err[j, i]:.3f})'))
# the worst face's pixels in every loaded layout and in (a), for comparison
t_max = report['top'][0]['face']
for key in sorted(set(keys) | {'a'}):
    if key not in layouts:
        layouts.update(bl.make_layouts(target, pos, tris, wt, uv0, S, PAD, key)[0])
    Lz = load_layout(key)
    sel = Lz['inside'] & (Lz['owner'] == t_max)
    if sel.any():
        fr = np.where(np.isfinite(Lz['fair']), Lz['fair'], np.nan)
        report.setdefault('face_in_layouts', {})[key] = dict(
            px=int(sel.sum()), max_copy_gt=float(np.abs(Lz['copy'] - Lz['gt'])[sel].max()),
            max_copy_fair=float(np.nanmax(np.abs(Lz['copy'] - fr)[sel])),
            max_direct_gt=float(np.abs(Lz['direct'] - Lz['gt'])[sel].max()),
            max_gt_fair=float(np.nanmax(np.abs(Lz['gt'] - fr)[sel])))
        bc.log(f'face {t_max} in layout {key}: {report["face_in_layouts"][key]}', LOG)
for (key, face, i, j) in P25:
    r = describe(key, i, j, f'P25 face {face}')
    report['p25'].append(r)
# extra pixels, extra=g:13:44,c:146:54 (layout:i:j), e.g. the largest copy - FAIR differences
for ex in [e_ for e_ in args.get('extra', '').split(',') if e_]:
    key, i, j = ex.split(':')
    if key not in layouts:
        layouts.update(bl.make_layouts(target, pos, tris, wt, uv0, S, PAD, key)[0])
    report.setdefault('extra', []).append(describe(key, int(i), int(j), f'extra {ex}'))
with open(os.path.join(D, 's14_panel_b.json'), 'w') as f_:
    json.dump(report, f_, indent=1)
bc.log('done', LOG)
