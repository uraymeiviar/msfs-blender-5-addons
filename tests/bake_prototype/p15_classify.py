"""P15 step 1 (journal Session 5's hand-off): classify the copy's wrong pixels and the seam band by cause.

Run (CPU cap, no blend file), after step3_master.py and step5_layouts.py of Session 2 for the tag:
    blender -b --factory-startup --python p15_classify.py -- tag=panel classify=abde measure=abcdefg suffix=

Reads Session 2's images of tests/_work/ao_bake/layouts/<tag><suffix>/ (copy, GT, direct, inside and band masks) and
makes the layouts again (bake_layouts.py, deterministic). Classes of a pixel (several may apply):
  - margin: Cycles did not count the pixel as inside a face: a margin-0 bake (AO, 1 sample) of the same layout leaves
    it unwritten, so the GT there is Cycles' margin, not AO. (By the prototype's own rasterizer every inside pixel has
    its centre in a face, on its border included; the bake shows where Cycles' rule differs.)
  - open: the pixel centre within 2 layout px of an open mesh edge (an edge without a 3D neighbour);
  - fold: within 2 layout px of an edge whose two faces differ by more than 30 degrees and lie in one master island;
  - other: none of these.
Sets: wrong (inside, |copy - GT| > 0.1) in the `classify` layouts, and the seam band.
For the `measure` layouts it also measures copy and direct against GT on the inside pixels that Cycles counts as
inside (MAE, P99, max, seam / interior), next to Session 2's figures on all inside pixels.
Writes p15_classify.json and p15_classify.log.txt into that folder.
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
CLS = args.get('classify', 'abde')
MEAS = args.get('measure', '')
SUF = args.get('suffix', '')
DIST = float(args.get('dist', 2.0))
FOLD = float(args.get('fold_deg', 30.0))
PAD = 8
OUT = os.path.join(bc.WORK, 'layouts', tag + SUF)
LOG = os.path.join(OUT, 'p15_classify.log.txt')
t_all = time.time()

target, info = bc.load_scene(tag)
S = int(info['texture_size'])
pos, tris, cn, uvs = bc.mesh_arrays(target.data)
uv0 = uvs[info['uv']]
wt = bg.weld_ids(pos)[tris]
em = bg.edge_map(wt)
mz = np.load(os.path.join(bc.WORK, 'master', f'master_{tag}.npz'))
misl = mz['island']
p = pos[tris]
nrm = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-30)

# edges by class: (face, corner i, corner j) whose layout segment is measured
open_e, fold_e = [], []
for key, lst in em.items():
    if len(lst) == 1:
        open_e.append(lst[0])
        continue
    for x in range(len(lst)):
        for y in range(x + 1, len(lst)):
            (t1, i1, j1), (t2, i2, j2) = lst[x], lst[y]
            n2 = -nrm[t2] if wt[t1, i1] == wt[t2, i2] else nrm[t2]  # consistent winding: opposite directions
            ang = math.degrees(math.acos(max(-1.0, min(1.0, float(nrm[t1] @ n2)))))
            if ang > FOLD and misl[t1] == misl[t2] and misl[t1] >= 0:
                fold_e += [lst[x], lst[y]]
bc.log(f'{tag}: {len(tris)} faces; open edges {len(open_e)}, fold edges (> {FOLD} deg, one master island) '
       f'{len(fold_e) // 2}', LOG)


def seg_dist(P, A, B):
    d = B - A
    L2 = float(d @ d)
    if L2 <= 0:
        return np.linalg.norm(P - A, axis=1)
    t = np.clip(((P - A) @ d) / L2, 0, 1)
    return np.linalg.norm(P - (A + t[:, None] * d), axis=1)


def min_dist(P, uvpx, edges):
    out = np.full(len(P), np.inf)
    for (t, i, j) in edges:
        A, B = uvpx[t, i], uvpx[t, j]
        lo = np.minimum(A, B) - DIST - 1
        hi = np.maximum(A, B) + DIST + 1
        near = np.all((P >= lo) & (P <= hi), axis=1)
        if near.any():
            out[near] = np.minimum(out[near], seg_dist(P[near], A, B))
    return out


def stats(d):
    if d.size == 0:
        return None
    a = np.abs(d)
    return dict(mae=float(a.mean()), p99=float(np.percentile(a, 99)), max=float(a.max()), px=int(d.size))


keys = ''.join(sorted(set(CLS + MEAS)))
layouts, _ = bl.make_layouts(target, pos, tris, wt, uv0, S, PAD, keys)
res = dict(tag=tag, dist_px=DIST, fold_deg=FOLD, open_edges=len(open_e), fold_edges=len(fold_e) // 2, layouts={})
for key, (uvpx, size, tisl) in layouts.items():
    x0, y0, w, h = bg.crop_box(uvpx, PAD + 4)
    bc.set_uv(target.data, 'BAKE_UV', (uvpx - np.array([x0, y0])) / np.array([w, h]))
    img = bc.new_float_image(f'{key}_cov', w, h)
    t_cov = bc.bake(target, img, 'BAKE_UV', 1, 7, margin=0)
    covered = bc.image_to_array(img) >= 0
    bpy.data.images.remove(img)
    img_ = {n: bc.read_png16(os.path.join(OUT, f'{key}_{n}.png')) for n in ('copy', 'gt', 'direct')}
    inside = np.load(os.path.join(OUT, f'{key}_inside.npy'))
    band = np.load(os.path.join(OUT, f'{key}_band.npy'))
    owner, _ = bg.rasterize_ids(uvpx, w, h, 1, x0, y0)
    dc = img_['copy'] - img_['gt']
    dd = img_['direct'] - img_['gt']
    row = dict(crop=[x0, y0, w, h], coverage_bake_s=round(t_cov, 2), inside_px=int(inside.sum()),
               inside_not_covered_px=int((inside & ~covered).sum()),
               covered_not_inside_px=int((covered & (owner < 0)).sum()))
    if key in CLS:
        for name, msk in (('wrong', inside & (np.abs(dc) > 0.1)), ('seam_band', band)):
            jj, ii = np.nonzero(msk)
            P = np.stack([x0 + ii + 0.5, y0 + jj + 0.5], axis=1)
            e = np.abs(dc[jj, ii])
            c_m = ~covered[jj, ii]
            c_o = min_dist(P, uvpx, open_e) <= DIST
            c_f = min_dist(P, uvpx, fold_e) <= DIST
            combo = {}
            for m_, o_, f_ in ((1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 0), (1, 0, 1), (0, 1, 1), (1, 1, 1), (0, 0, 0)):
                sel = (c_m == bool(m_)) & (c_o == bool(o_)) & (c_f == bool(f_))
                lab = '+'.join(n for n, v in (('margin', m_), ('open', o_), ('fold', f_)) if v) or 'other'
                combo[lab] = dict(px=int(sel.sum()), err=float(e[sel].sum()))
            tot = float(e.sum())
            r = dict(px=int(len(e)), err_sum=tot, positive=int((dc[jj, ii] > 0).sum()),
                     any={n: dict(px=int(c.sum()), err=float(e[c].sum())) for n, c in
                          (('margin', c_m), ('open', c_o), ('fold', c_f), ('other', ~(c_m | c_o | c_f)))},
                     combos=combo)
            row[name] = r
            bc.log(f'  {key} {name}: {r["px"]} px (copy above GT {r["positive"]}), |err| sum {tot:.2f}; any class: '
                   + ', '.join(f'{n} {v["px"]} ({100 * v["px"] / max(r["px"], 1):.1f} % px, '
                               f'{100 * v["err"] / max(tot, 1e-30):.1f} % err)' for n, v in r['any'].items())
                   + '; exclusive: ' + ', '.join(f'{n} {v["px"]}' for n, v in combo.items() if v['px']), LOG)
    if key in MEAS:
        lab = np.where(owner >= 0, tisl[np.maximum(owner, 0)], -1)
        m_new = inside & covered
        meas = {}
        for nm, msk in (('old', inside), ('new', m_new)):
            interior = msk & ~band
            sb = msk & band
            meas[nm] = dict(copy=stats(dc[msk]), direct=stats(dd[msk]),
                            seam_mae=float(np.abs(dc[sb]).mean()), interior_mae=float(np.abs(dc[interior]).mean()))
            meas[nm]['ratio'] = meas[nm]['seam_mae'] / meas[nm]['interior_mae']
        row['measure'] = meas
        bc.log(f'  {key} measure: ' + '; '.join(
            f'{nm}: px {v["copy"]["px"]}, MAE copy/direct {v["copy"]["mae"]:.4f}/{v["direct"]["mae"]:.4f}, '
            f'P99 {v["copy"]["p99"]:.4f}/{v["direct"]["p99"]:.4f}, max {v["copy"]["max"]:.3f}/'
            f'{v["direct"]["max"]:.3f} ({v["copy"]["max"] / v["direct"]["max"]:.2f} x), seam/interior '
            f'{v["seam_mae"]:.4f}/{v["interior_mae"]:.4f} = {v["ratio"]:.2f}' for nm, v in meas.items()), LOG)
    bc.log(f'  {key}: inside {row["inside_px"]}, inside but not covered by Cycles {row["inside_not_covered_px"]}, '
           f'covered but not inside {row["covered_not_inside_px"]}, coverage bake {t_cov:.2f} s', LOG)
    res['layouts'][key] = row
res['total_s'] = round(time.time() - t_all, 1)
with open(os.path.join(OUT, 'p15_classify.json'), 'w') as f:
    json.dump(res, f, indent=1)
bc.log(f'done in {res["total_s"]} s', LOG)
