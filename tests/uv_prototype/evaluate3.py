# Round 2 evaluator (xatlas already run by xatlas_run.py): compute uniform metrics for all methods, render PNGs.
# Usage (venv): python -I evaluate.py <results_dir>
import sys, os, glob, json, time
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import uvmetrics as um
from evaluate3_extra import artist_texel
import xatlas
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection

R = os.path.join(HERE, sys.argv[1] if len(sys.argv) > 1 else 'results')


def run_xatlas(P, T, padding=None):
    atlas = xatlas.Atlas()
    atlas.add_mesh(P.astype(np.float32), T.astype(np.uint32))
    co = xatlas.ChartOptions(); po = xatlas.PackOptions()
    if padding is not None:
        po.padding = padding
    t0 = time.perf_counter()
    atlas.generate(co, po)
    dt = time.perf_counter() - t0
    vm, idx, uvs = atlas.get_mesh(0)
    assert np.all(vm[idx] == T), 'xatlas face order/vertex mapping mismatch'
    # python-xatlas normalises u by width and v by height; undo that to keep the chart aspect (square texture)
    s = np.array([atlas.width, atlas.height], np.float64) / max(atlas.width, atlas.height)
    return (uvs[idx].astype(np.float64) * s), dt, dict(width=atlas.width, height=atlas.height, charts=atlas.chart_count)


def metrics(P, T, UV, NT=None):
    nt = len(T)
    P3 = P[T]
    # split vertices: (3D vertex, exact uv)
    key = np.concatenate([T.reshape(-1, 1).astype(np.float64), UV.reshape(-1, 2)], 1)
    _, sid = np.unique(key, axis=0, return_inverse=True); sid = sid.reshape(-1, 3)
    n_split = int(sid.max() + 1); n_v = len(np.unique(T))
    # edges: 3D key and split key
    e3 = np.sort(np.stack([T, np.roll(T, -1, 1)], -1).reshape(-1, 2), 1)
    es = np.sort(np.stack([sid, np.roll(sid, -1, 1)], -1).reshape(-1, 2), 1)
    tri_of = np.repeat(np.arange(nt), 3)
    # islands: triangles sharing a split edge
    _, ues = np.unique(es, axis=0, return_inverse=True)
    order = np.argsort(ues, kind='stable'); u = ues[order]; t = tri_of[order]
    same = u[1:] == u[:-1]
    g = coo_matrix((np.ones(same.sum()), (t[:-1][same], t[1:][same])), shape=(nt, nt))
    n_isl, isl = connected_components(g, directed=False)
    # seams: 3D edges whose incident split-edges are not all identical
    _, ue3, cnt3 = np.unique(e3, axis=0, return_inverse=True, return_counts=True)
    ue3 = ue3.ravel()
    nsplit_per_e3 = {}
    pairs = np.unique(np.stack([ue3, ues.ravel()], 1), axis=0)
    per = np.bincount(pairs[:, 0], minlength=cnt3.size)
    seam_edges = np.flatnonzero(per > 1)
    first = np.zeros(cnt3.size, np.int64); first[ue3[::-1]] = np.arange(len(ue3))[::-1]
    ev = e3[first[seam_edges]]
    seam_len = float(np.linalg.norm(P[ev[:, 0]] - P[ev[:, 1]], axis=1).sum())
    _, _, r = um.area_distortion(P3, UV)
    a3 = um.tri_area3(P3)
    fin = np.isfinite(r)
    zero_uv = int((~fin & (a3 > 0)).sum())
    zero_uv_area_share = float(a3[~fin].sum() / a3.sum())
    dmean = float(r[fin].mean()); dmax = float(r[fin].max())
    dw = float((r[fin] * a3[fin]).sum() / a3[fin].sum())
    deg3d = int((a3 <= 1e-12).sum())
    amean = um.angle_distortion(P3, UV)
    flips = sum(um.flipped_count(UV[isl == i]) for i in range(n_isl))
    ov = um.overlap_pairs(UV)
    ov_tris = len(np.unique(ov)) if len(ov) else 0
    ov_isl = 0
    if len(ov):
        ip = np.sort(isl[ov], 1); ov_isl = len(np.unique(ip, axis=0))
    a2 = np.abs(um.tri_area2_signed(UV)).sum()
    lo = UV.reshape(-1, 2).min(0); hi = UV.reshape(-1, 2).max(0)
    inside = bool(np.all(lo >= -1e-6) and np.all(hi <= 1 + 1e-6))
    rv = None; nv_n = None
    if NT is not None:
        k2 = np.concatenate([NT.reshape(-1, 1).astype(np.float64), UV.reshape(-1, 2)], 1)
        rv = int(len(np.unique(k2, axis=0))); nv_n = int(len(np.unique(NT)))
    return dict(render_verts=rv, normal_split_verts=nv_n, render_extra_vs_normals=(rv - nv_n) if rv is not None else None, tris=nt, verts3d=n_v, islands=int(n_isl), area_dist_mean=dmean, area_dist_max=dmax, area_dist_areaw=dw, zero_uv_tris=zero_uv,
                zero_uv_area_share=zero_uv_area_share, degenerate3d_tris=deg3d,
                angle_dist_deg=amean, overlap_tri_pairs=int(len(ov)), overlap_tris=int(ov_tris),
                overlap_island_pairs=int(ov_isl), flipped_tris=int(flips), seam_len_m=seam_len,
                uv_split_verts=n_split, extra_verts=n_split - n_v, uv_area=float(a2),
                uv_bbox=[float(x) for x in np.concatenate([lo, hi])], inside_unit=inside), isl, ov


def render(UV, isl, ov, path, title):
    fig, ax = plt.subplots(figsize=(6, 6), dpi=150)
    rng = np.random.default_rng(1)
    cols = rng.uniform(0.25, 0.95, (isl.max() + 1, 3))
    pc = PolyCollection(UV, facecolors=cols[isl], edgecolors='none', linewidths=0)
    ax.add_collection(pc)
    if len(ov):
        bad = np.unique(ov)
        ax.add_collection(PolyCollection(UV[bad], facecolors='none', edgecolors='red', linewidths=0.6))
    ax.plot([0, 1, 1, 0, 0], [0, 0, 1, 1, 0], 'k-', lw=0.6)
    lo = np.minimum(UV.reshape(-1, 2).min(0), 0); hi = np.maximum(UV.reshape(-1, 2).max(0), 1)
    ax.set_xlim(lo[0] - 0.01, hi[0] + 0.01); ax.set_ylim(lo[1] - 0.01, hi[1] + 0.01)
    ax.set_aspect('equal'); ax.set_title(title, fontsize=8); ax.tick_params(labelsize=6)
    fig.tight_layout(); fig.savefig(path); plt.close(fig)


rows = []
files = sorted(f for f in glob.glob(os.path.join(R, '*__*.npz')) if 'splitmesh' not in f and 'xatlascut' not in f)
ONLY = sys.argv[2].split(',') if len(sys.argv) > 2 else None
if ONLY: files = [f for f in files if os.path.basename(f).split('__')[1][:-4] in ONLY or f.endswith('__existing.npz')]
objs = sorted(set(os.path.basename(f).split('__')[0] for f in files))
os.makedirs(os.path.join(R, 'png'), exist_ok=True)
for o in objs:
    mf = [f for f in files if os.path.basename(f).startswith(o + '__')]
    d0 = np.load(mf[0]); P, T = d0['P'], d0['T']
    entries = []
    for f in mf:
        d = np.load(f); m = os.path.basename(f).split('__')[1][:-4]
        assert np.array_equal(d['T'], T)
        entries.append((m, d['UV'], json.loads(str(d['extra']))))
    ntp = os.path.join(R, o + '__nsplit_T.npy'); NT = np.load(ntp) if os.path.exists(ntp) else None
    for m, UV, extra in entries:
        t0 = time.perf_counter()
        met, isl, ov = metrics(P, T, UV, NT)
        sp = os.path.join(R, o + '__seams.npy')
        if os.path.exists(sp): met.update(artist_texel(P, T, UV, isl, np.load(sp)))
        met.update(object=o, method=m, time=extra.get('time'), eval_time=time.perf_counter() - t0, extra=extra)
        met['pack_eff'] = met['uv_area'] if met['inside_unit'] else None
        png = os.path.join(R, 'png', '%s__%s.png' % (o, m))
        render(UV, isl, ov, png, '%s  %s  islands=%d dist=%.3f ov=%d' % (o, m, met['islands'], met['area_dist_mean'], met['overlap_tris']))
        met['png'] = png
        rows.append(met)
        print('%-28s %-12s isl=%5d dA=%.3f/%7.2f w=%.3f z=%d/%.4f ang=%5.2f ovT=%5d ovI=%4d flip=%4d seam=%.3fm extra=%5d area=%.3f in=%d t=%s' % (
            o, m, met['islands'], met['area_dist_mean'], met['area_dist_max'], met['area_dist_areaw'], met['zero_uv_tris'], met['zero_uv_area_share'], met['angle_dist_deg'], met['overlap_tris'],
            met['overlap_island_pairs'], met['flipped_tris'], met['seam_len_m'], met['extra_verts'], met['uv_area'],
            met['inside_unit'], ('%.2f' % met['time']) if met['time'] is not None else '-'))
if ONLY and os.path.exists(os.path.join(R, 'metrics.json')):
    old = [r for r in json.load(open(os.path.join(R, 'metrics.json'))) if r['method'] not in ONLY]
    rows = old + [r for r in rows if r['method'] in ONLY]
json.dump(rows, open(os.path.join(R, 'metrics.json'), 'w'), indent=1)
