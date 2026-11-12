"""Session 11, step 2 (P17): the GT across the panel's open edges at a few times the master density, against the master.

Run (CPU cap, no blend file), after step3_master.py and step5_layouts.py with the 4 x master:
    blender -b --factory-startup --python s11_profile.py -- tag=panel suffix=_s11x4 masters=_s11x4,_p18 layouts=de
        faces=6 per_face=2 factor=4 gt_samples=4096

1. Wrong pixels (inside, |copy - GT| > 0.1) of the `layouts` in layouts/<tag><suffix>/ within 2 layout px of an open
   mesh edge (an edge without a 3D neighbour), grouped by face; the `faces` faces with the largest summed error.
2. A direct bake (`gt_samples`, margin 0) of only those faces (and the faces of their nearest open edges), each laid
   out on its own in its master UV (isometric) scaled to `factor` x the first master's density; every other face gets
   a UV without area. This is the GT at a quarter of a master pixel.
3. For the `per_face` worst of those pixels per face and layout: the line from the foot of the pixel centre on its
   nearest open edge into the face, perpendicular to the edge, 0 to 4 master px (of the first master) in steps of
   1/8 px. Along it: GT_hi (the hi-res bake, averaged over 7 hi-res px along the edge), and the point read of each
   master (the copy's read: surface-aware bilinear within 30 degrees, clamped into its island).
4. The layout pixel itself: its copy and GT values, and the same pixel re-sampled from GT_hi and from each master
   (8 x 8 points on its own triangle), to check that the profile explains the pixel's error.
Writes s11_profile.json and s11_profile.log.txt into layouts/<tag><suffix>/.
"""
import json
import math
import os
import sys
import time

import bpy  # noqa: F401
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bake_common as bc  # noqa: E402
import bake_geom as bg  # noqa: E402
import bake_layouts as bl  # noqa: E402

args = dict(a.split('=', 1) for a in (sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []))
tag = args.get('tag', 'panel')
SUF = args.get('suffix', '_s11x4')
MASTERS = args.get('masters', '_s11x4,_p18').split(',')
LAYOUTS = args.get('layouts', 'de')
NF = int(args.get('faces', 6))
NPF = int(args.get('per_face', 2))
FACTOR = float(args.get('factor', 4))
NGT = int(args.get('gt_samples', 4096))
DIST = 2.0
PAD = 8
SURF_COS = math.cos(math.radians(30.0))
OUT = os.path.join(bc.WORK, 'layouts', tag + SUF)
LOG = os.path.join(OUT, 's11_profile.log.txt')
if os.path.exists(LOG):
    os.remove(LOG)
t_all = time.time()

target, info = bc.load_scene(tag)
S = int(info['texture_size'])
pos, tris, cn, uvs = bc.mesh_arrays(target.data)
uv0 = uvs[info['uv']]
wt = bg.weld_ids(pos)[tris]
em = bg.edge_map(wt)
P3 = pos[tris]
tri_normal = np.cross(P3[:, 1] - P3[:, 0], P3[:, 2] - P3[:, 0])
tri_normal /= np.maximum(np.linalg.norm(tri_normal, axis=1, keepdims=True), 1e-30)
open_e = [lst[0] for lst in em.values() if len(lst) == 1]


def load_master(ms):
    mz = np.load(os.path.join(bc.WORK, 'master', f'master_{tag}{ms}.npz'))
    img = bc.read_png16(os.path.join(bc.WORK, 'master', f'master_{tag}{ms}.png'))
    H, W = img.shape
    rid = np.full((H, W), -1, dtype=np.int64)
    for i, (x, y, w, h) in enumerate(mz['rects']):
        rid[y:y + h, x:x + w] = i
    return dict(name=ms, muv=mz['muv'], img=img, rect_id=rid, filled=mz['filled'], island=mz['island'],
                face_map=mz['face_map'], density=float(mz['density']), W=W, H=H,
                core_owner=bg.rasterize_ids(mz['muv'], W, H)[0])


def master_read(m, tri_ids, bary):
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
    for dx, dy, wgt in ((0, 0, (1 - ax) * (1 - ay)), (1, 0, ax * (1 - ay)), (0, 1, (1 - ax) * ay), (1, 1, ax * ay)):
        xc, yc = np.clip(xa + dx, 0, W - 1), np.clip(ya + dy, 0, H - 1)
        f = m['face_map'][yc, xc]
        ok = (f >= 0) & (np.einsum('nd,nd->n', tri_normal[np.maximum(f, 0)], nt) >= SURF_COS)
        wv = np.where(ok, wgt, 0.0)
        acc += wv * M[yc, xc]
        wsum += wv
    plain = bg.bilinear(M, mp[:, 0], mp[:, 1])
    return np.where(wsum > 1e-9, acc / np.maximum(wsum, 1e-30), plain)


def texel_breakdown(m, tri_ids, bary):
    """Which master texels the read of these points uses: weight share per texel kind (the read face's own core
    texel, another face's core texel, a skirt or fill texel) and the faces shown, with their texels' mean value."""
    mp = np.einsum('nk,nkd->nd', bary, m['muv'][tri_ids])
    fx, fy = mp[:, 0] - 0.5, mp[:, 1] - 0.5
    xa, ya = np.floor(fx).astype(np.int64), np.floor(fy).astype(np.int64)
    ax, ay = fx - xa, fy - ya
    nt = tri_normal[tri_ids]
    kinds = dict(own_core=0.0, other_core=0.0, skirt_or_fill=0.0)
    per_face = {}
    tot = 0.0
    for dx, dy, wgt in ((0, 0, (1 - ax) * (1 - ay)), (1, 0, ax * (1 - ay)), (0, 1, (1 - ax) * ay), (1, 1, ax * ay)):
        xc, yc = np.clip(xa + dx, 0, m['W'] - 1), np.clip(ya + dy, 0, m['H'] - 1)
        f = m['face_map'][yc, xc]
        ok = (f >= 0) & (np.einsum('nd,nd->n', tri_normal[np.maximum(f, 0)], nt) >= SURF_COS)
        co = m['core_owner'][yc, xc]
        for n in np.nonzero(ok & (wgt > 0))[0]:
            w_ = float(wgt[n])
            tot += w_
            kind = 'own_core' if co[n] == tri_ids[n] else ('other_core' if co[n] >= 0 else 'skirt_or_fill')
            kinds[kind] += w_
            pf = per_face.setdefault(int(f[n]), [0.0, 0.0])
            pf[0] += w_
            pf[1] += w_ * float(m['img'][yc[n], xc[n]])
    tot = max(tot, 1e-30)
    faces_ = sorted(per_face.items(), key=lambda kv: -kv[1][0])[:4]
    return dict(kinds={k: round(v / tot, 3) for k, v in kinds.items()},
                faces=[(fc, round(v[0] / tot, 3), round(v[1] / max(v[0], 1e-30), 3)) for fc, v in faces_])


def bary3d(t, Y):
    """Barycentric coordinates (N,3) of 3D points Y (N,3) in the plane of face t."""
    A = np.array([P3[t, 1] - P3[t, 0], P3[t, 2] - P3[t, 0]]).T
    coef = np.linalg.lstsq(A, (Y - P3[t, 0]).T, rcond=None)[0].T
    return np.stack([1 - coef.sum(axis=1), coef[:, 0], coef[:, 1]], axis=1)


def min_dist(P, uvpx, edges):
    best = np.full(len(P), np.inf)
    arg = np.full(len(P), -1, dtype=np.int64)
    for n, (t, i, j) in enumerate(edges):
        A, B = uvpx[t, i], uvpx[t, j]
        d = B - A
        L2 = float(d @ d)
        if L2 <= 0:
            continue
        s = np.clip(((P - A) @ d) / L2, 0, 1)
        dist = np.linalg.norm(P - (A + s[:, None] * d), axis=1)
        better = dist < best
        best[better] = dist[better]
        arg[better] = n
    return best, arg


masters = [load_master(ms) for ms in MASTERS]
D0 = masters[0]['density']
layouts, _ = bl.make_layouts(target, pos, tris, wt, uv0, S, PAD, LAYOUTS)
bc.log(f'{tag}: {len(tris)} faces, {len(open_e)} open edges; masters {[(m["name"], round(m["density"], 1)) for m in masters]}'
       f'; GT_hi at {FACTOR} x {D0:.1f} px/m, {NGT} samples', LOG)

# 1. wrong pixels near open edges, by face
cands = []
face_err = {}
for key, (uvpx, size, tisl) in layouts.items():
    x0, y0, w, h = bg.crop_box(uvpx, PAD + 4)
    c = bc.read_png16(os.path.join(OUT, f'{key}_copy.png'))
    g = bc.read_png16(os.path.join(OUT, f'{key}_gt.png'))
    ins = np.load(os.path.join(OUT, f'{key}_inside.npy'))
    owner, _ = bg.rasterize_ids(uvpx, w, h, 1, x0, y0)
    wrong = ins & (np.abs(c - g) > 0.1)
    jj, ii = np.nonzero(wrong)
    P = np.stack([x0 + ii + 0.5, y0 + jj + 0.5], axis=1)
    dist, arg = min_dist(P, uvpx, open_e)
    near = dist <= DIST
    bc.log(f'  {key}: wrong {int(wrong.sum())}, within {DIST} px of an open edge {int(near.sum())}', LOG)
    for n in np.nonzero(near)[0]:
        t = int(owner[jj[n], ii[n]])
        e = float(c[jj[n], ii[n]] - g[jj[n], ii[n]])
        face_err[t] = face_err.get(t, 0.0) + abs(e)
        cands.append(dict(layout=key, i=int(ii[n]), j=int(jj[n]), face=t, err=e, copy=float(c[jj[n], ii[n]]),
                          gt=float(g[jj[n], ii[n]]), dist_px=float(dist[n]), edge=int(arg[n]), crop=[x0, y0, w, h]))
top = sorted(face_err, key=lambda t: -face_err[t])[:NF]
bc.log(f'  faces by summed error near open edges: '
       + ', '.join(f'{t} ({face_err[t]:.2f}, {sum(1 for c_ in cands if c_["face"] == t)} px)' for t in top)
       + f'; all faces {len(face_err)}, total {sum(face_err.values()):.2f}', LOG)
lines = []
for t in top:
    for key in LAYOUTS:
        sel = sorted([c_ for c_ in cands if c_['face'] == t and c_['layout'] == key], key=lambda c_: -abs(c_['err']))
        lines += sel[:NPF]

# 2. hi-res GT of the chosen faces
faces = sorted(set(top) | {open_e[c_['edge']][0] for c_ in lines})
m0 = masters[0]
uvhi = np.full((len(tris), 3, 2), -10.0)
x = 2
hmax = 0
for t in faces:
    q = m0['muv'][t] * FACTOR
    lo = q.min(axis=0)
    q = q - lo + np.array([x + 2, 2])
    uvhi[t] = q
    x = int(math.ceil(q[:, 0].max())) + 4
    hmax = max(hmax, int(math.ceil(q[:, 1].max())) + 4)
Wh, Hh = x, hmax
bc.set_uv(target.data, 'BAKE_UV', uvhi / np.array([Wh, Hh]))
HI_NPZ = os.path.join(OUT, 's11_profile_gt_hi.npz')
if args.get('reuse_gt_hi') == '1' and os.path.exists(HI_NPZ):
    _z = np.load(HI_NPZ)
    assert list(_z['faces']) == faces and _z['GH'].shape == (Hh, Wh)
    GH, t_hi = _z['GH'], 0.0
else:
    img = bc.new_float_image('GT_HI', Wh, Hh)
    t_hi = bc.bake(target, img, 'BAKE_UV', NGT, 201, margin=0)
    GH = bc.image_to_array(img)
    bpy.data.images.remove(img)
    np.savez_compressed(HI_NPZ, GH=GH, faces=np.array(faces))
own_hi, _ = bg.rasterize_ids(np.where(np.isin(np.arange(len(tris)), faces)[:, None, None], uvhi, -10.0), Wh, Hh)
bc.write_png(os.path.join(OUT, 's11_profile_gt_hi.png'), np.where(GH >= 0, GH, 0.0))
bc.log(f'  GT_hi: {len(faces)} faces {faces}, image {Wh} x {Hh}, {int((GH >= 0).sum())} px baked, '
       f'{t_hi:.1f} s', LOG)


def gt_hi(t, bary):
    q = np.einsum('nk,kd->nd', bary, uvhi[t])
    xi, yi = np.floor(q[:, 0]).astype(np.int64), np.floor(q[:, 1]).astype(np.int64)
    ok = (xi >= 0) & (xi < Wh) & (yi >= 0) & (yi < Hh)
    v = np.full(len(q), np.nan)
    xi, yi = np.clip(xi, 0, Wh - 1), np.clip(yi, 0, Hh - 1)
    good = ok & (own_hi[yi, xi] == t) & (GH[yi, xi] >= 0)
    v[good] = GH[yi[good], xi[good]]
    return v


# 3. lines across the open edge, 4. the pixel re-sampled
STEPS = np.arange(0, 4.0001, 0.125)
report = []
for c_ in lines:
    te, ie, je = open_e[c_['edge']]
    key = c_['layout']
    uvpx = layouts[key][0]
    x0, y0, w, h = c_['crop']
    to = c_['face']
    pc = np.array([[x0 + c_['i'] + 0.5, y0 + c_['j'] + 0.5]])
    b_c = bg.barycentric_many(pc, uvpx[[to]])
    Xc = (b_c @ P3[to])[0]
    A, B = P3[te, ie], P3[te, je]
    e_hat = (B - A) / np.linalg.norm(B - A)
    s_ = np.clip((Xc - A) @ e_hat, 0, np.linalg.norm(B - A))
    F = A + s_ * e_hat
    k3 = 3 - ie - je
    n_in = np.cross(tri_normal[te], e_hat)
    if (P3[te, k3] - A) @ n_in < 0:
        n_in = -n_in
    prof = dict(s_master_px=STEPS.tolist())
    Y = F[None, :] + n_in[None, :] * (STEPS / D0)[:, None]
    bY = bary3d(te, Y)
    inface = (bY >= -1e-9).all(axis=1)
    gh = np.full(len(STEPS), np.nan)
    acc = np.zeros(len(STEPS))
    cnt = np.zeros(len(STEPS))
    for k in range(-3, 4):
        v = gt_hi(te, bary3d(te, Y + e_hat[None, :] * (k / (FACTOR * D0))))
        okv = np.isfinite(v)
        acc[okv] += v[okv]
        cnt[okv] += 1
    gh[cnt > 0] = acc[cnt > 0] / cnt[cnt > 0]
    gh[~inface] = np.nan
    prof['gt_hi'] = gh.tolist()
    for m in masters:
        mv = master_read(m, np.full(len(STEPS), te), np.clip(bY, 0, None) / np.clip(bY, 0, None).sum(axis=1, keepdims=True))
        mv[~inface] = np.nan
        prof[m['name']] = mv.tolist()
    # the pixel re-sampled, 8 x 8 points on its own triangle
    L = 8
    sub = (np.arange(L) + 0.5) / L
    sx, sy = np.meshgrid(sub, sub)
    pts = np.stack([x0 + c_['i'] + sx.ravel(), y0 + c_['j'] + sy.ravel()], axis=1)
    bp = bg.barycentric_many(pts, np.repeat(uvpx[[to]], len(pts), axis=0))
    own = (bp >= -1e-9).all(axis=1)
    bp = bp[own]
    pix = dict(copy=c_['copy'], gt=c_['gt'], points=int(own.sum()))
    v = gt_hi(to, bp)
    pix['gt_hi'] = float(np.nanmean(v)) if np.isfinite(v).any() else None
    pix['gt_hi_valid'] = int(np.isfinite(v).sum())
    for m in masters:
        pix[m['name']] = float(master_read(m, np.full(len(bp), to), bp).mean())
        pix[m['name'] + '_texels'] = texel_breakdown(m, np.full(len(bp), to), bp)
    pix['angles_deg'] = {int(fc): round(math.degrees(math.acos(max(-1.0, min(1.0, float(tri_normal[fc] @ tri_normal[to]))))), 1)
                         for m in masters for fc, _, _ in pix[m['name'] + '_texels']['faces']}
    ci_, cj_ = c_['i'], c_['j']
    pix['direct'] = float(bc.read_png16(os.path.join(OUT, f'{key}_direct.png'))[cj_, ci_])
    # widths of GT_hi's change from the edge: where it has covered 50 % and 90 % of (value at 4 px - value at 0)
    fin = np.isfinite(gh)
    width = {}
    if fin.sum() > 4:
        g0 = gh[fin][0]
        g4 = gh[fin][-1]
        for frac in (0.5, 0.9):
            reach = np.nonzero(fin & (np.abs(gh - g0) >= frac * abs(g4 - g0)))[0]
            width[f'w{int(frac * 100)}'] = float(STEPS[reach[0]]) if len(reach) and abs(g4 - g0) > 0.02 else None
        width['drop'] = float(g4 - g0)
    err = {}
    for m in masters:
        mv = np.array(prof[m['name']])
        d = np.abs(mv - gh)
        near_ = fin & (STEPS < 1.0)
        far_ = fin & (STEPS >= 1.0)
        err[m['name']] = dict(mae_lt1=float(d[near_].mean()) if near_.any() else None,
                              mae_ge1=float(d[far_].mean()) if far_.any() else None,
                              max=float(np.nanmax(d)) if fin.any() else None)
    r = dict(layout=key, face=to, edge_face=int(te), pixel=[c_['i'], c_['j']], dist_px_layout=c_['dist_px'],
             dist_master_px=float(np.linalg.norm(Xc - F) * D0), profile=prof, pixel_resampled=pix, width=width,
             err=err, inface_steps=int(inface.sum()))
    report.append(r)
    at = {s: int(round(s / 0.125)) for s in (0, 0.25, 0.5, 1, 2, 4)}

    def fmt(arr):
        return ' '.join(f'{arr[i]:.3f}' if np.isfinite(arr[i]) else '  -  ' for i in at.values())

    bc.log(f'  {key} face {to} (edge of {te}) px ({c_["i"]},{c_["j"]}) {r["dist_master_px"]:.2f} master px from the '
           f'edge: copy {pix["copy"]:.3f} GT {pix["gt"]:.3f}; resampled GT_hi {pix["gt_hi"] if pix["gt_hi"] is None else round(pix["gt_hi"], 3)}'
           + ''.join(f', {m["name"]} {pix[m["name"]]:.3f}' for m in masters), LOG)
    bc.log(f'      s = {" ".join(f"{s:5}" for s in at)} px; GT_hi {fmt(gh)}; '
           + '; '.join(f'{m["name"]} {fmt(np.array(prof[m["name"]]))}' for m in masters)
           + f'; width50/90 {width.get("w50")}/{width.get("w90")} drop {width.get("drop", float("nan")):.3f}; '
           + '; '.join(f'|{m["name"]} - GT_hi| <1 px {err[m["name"]]["mae_lt1"]}, >=1 px {err[m["name"]]["mae_ge1"]}'
                       for m in masters), LOG)
    bc.log(f'      pixel: direct {pix["direct"]:.3f}, GT_hi points valid {pix["gt_hi_valid"]} of {pix["points"]}; angle to the faces read '
           f'{pix["angles_deg"]}; texels read: '
           + '; '.join(f'{m["name"]} {pix[m["name"] + "_texels"]}' for m in masters), LOG)
with open(os.path.join(OUT, 's11_profile.json'), 'w') as f:
    json.dump(dict(tag=tag, suffix=SUF, masters=MASTERS, factor=FACTOR, gt_samples=NGT, faces=faces, top=top,
                   face_err={int(k): v for k, v in face_err.items()}, lines=report,
                   gt_hi=dict(W=Wh, H=Hh, bake_s=t_hi), total_s=round(time.time() - t_all, 1)), f, indent=1)
bc.log(f'done in {time.time() - t_all:.1f} s', LOG)
