# Round 3 extra metrics: artist-seam crossing / following, texel density spread.
import numpy as np
import uvmetrics as um


def artist_texel(P, T, UV, isl, SE):
    nt = len(T); nV = len(P)
    key = np.concatenate([T.reshape(-1, 1).astype(np.float64), UV.reshape(-1, 2)], 1)
    _, sid = np.unique(key, axis=0, return_inverse=True); sid = sid.reshape(-1, 3); nS = int(sid.max() + 1)
    e3 = np.sort(np.stack([T, np.roll(T, -1, 1)], -1).reshape(-1, 2), 1).astype(np.int64)
    es = np.sort(np.stack([sid, np.roll(sid, -1, 1)], -1).reshape(-1, 2), 1).astype(np.int64)
    k3 = e3[:, 0] * nV + e3[:, 1]; ks = es[:, 0] * nS + es[:, 1]
    tri = np.repeat(np.arange(nt), 3)
    u3, inv3, c3 = np.unique(k3, return_inverse=True, return_counts=True)
    nuniq = np.bincount(np.unique(np.stack([inv3, np.unique(ks, return_inverse=True)[1]], 1), axis=0)[:, 0], minlength=len(u3))
    SEs = np.sort(SE, 1).astype(np.int64); skeys = SEs[:, 0] * nV + SEs[:, 1] if len(SE) else np.zeros(0, np.int64)
    is_seam3 = np.isin(u3, skeys)
    manifold = c3 == 2
    seam_m = is_seam3 & manifold
    cross_e = seam_m & (nuniq == 1)           # artist seam edge with continuous UVs
    offseam = (~is_seam3) & manifold & (nuniq > 1)  # UV split where the artist has no seam
    cross_isl = np.unique(isl[tri[cross_e[inv3]]])
    deg = np.bincount(SEs.ravel(), minlength=nV) if len(SE) else np.zeros(nV, int)
    bord = np.zeros(nV, bool); bu = u3[c3 == 1]; bord[bu // nV] = True; bord[bu % nV] = True
    ea, eb = u3 // nV, u3 % nV
    # dead-end seam stubs: iteratively prune seam edges that end at an interior vertex of seam-degree 1
    # (mesh-border vertices anchor). What remains are cuts that reach a border or close a loop; the pruned stubs
    # are never opened by Blender's unwrap (observed), so crossing them is unavoidable for any Blender unwrap.
    alive = np.ones(len(SEs), bool); dg = deg.copy()
    while True:
        tip = (dg == 1) & ~bord
        kill = alive & (tip[SEs[:, 0]] | tip[SEs[:, 1]]) if len(SEs) else np.zeros(0, bool)
        if not kill.any(): break
        alive &= ~kill
        dg = np.bincount(SEs[alive].ravel(), minlength=nV) if alive.any() else np.zeros(nV, int)
    stub_keys = SEs[~alive, 0] * nV + SEs[~alive, 1] if len(SEs) else np.zeros(0, np.int64)
    is_stub = np.isin(u3, stub_keys)
    unsplit = cross_e & is_stub
    bad_isl = np.unique(np.concatenate([cross_isl, isl[tri[offseam[inv3]]]]))
    n_isl = int(isl.max() + 1)
    a3 = np.bincount(isl, um.tri_area3(P[T]), n_isl); a2 = np.bincount(isl, np.abs(um.tri_area2_signed(UV)), n_isl)
    ok = (a3 > 0) & (a2 > 0)
    d = a2[ok] / a3[ok]; w = a3[ok] / a3[ok].sum(); mu = (w * d).sum()
    return dict(artist_seam_edges=int(seam_m.sum()), artist_seam_split=int((seam_m & (nuniq > 1)).sum()),
                artist_seam_crossed_edges=int(cross_e.sum()), artist_seam_crossed_in_stubs=int(unsplit.sum()), artist_seam_stub_edges=int((is_stub & seam_m).sum()), islands_crossing_artist_seam=int(len(cross_isl)),
                offseam_split_edges=int(offseam.sum()), islands_following_artist_seams=int(n_isl - len(bad_isl)),
                texel_max_min=float(d.max() / d.min()), texel_p95_p5=float(np.percentile(d, 95) / np.percentile(d, 5)),
                texel_cv_areaw=float(np.sqrt((w * (d - mu) ** 2).sum()) / mu), zero_uv_islands=int((~ok).sum()))
