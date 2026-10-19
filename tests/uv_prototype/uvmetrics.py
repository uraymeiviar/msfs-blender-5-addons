# numpy-only UV metrics, shared by the Blender prototype (trial checks) and the venv evaluator.
import numpy as np


def tri_area3(P3):  # (n,3,3)
    return 0.5 * np.linalg.norm(np.cross(P3[:, 1] - P3[:, 0], P3[:, 2] - P3[:, 0]), axis=1)


def tri_area2_signed(U):  # (n,3,2)
    a = U[:, 1] - U[:, 0]; b = U[:, 2] - U[:, 0]
    return 0.5 * (a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0])


def area_distortion(P3, U):
    """PartUV calculate_distortion_area: per-face (uvA/3dA)/(sumUV/sum3D), symmetric (x<1 -> 1/x).
    Returns (mean, max, per-face array); zero-3D-area faces skipped; zero-UV-area faces -> inf."""
    a3 = tri_area3(P3); a2 = np.abs(tri_area2_signed(U))
    if a3.sum() == 0 or a2.sum() == 0:
        return 1.0, 1.0, np.ones(len(a3))
    tot = a2.sum() / a3.sum()
    ok = a3 > 0
    r = np.full(len(a3), np.nan)
    with np.errstate(divide='ignore', invalid='ignore'):
        r[ok] = (a2[ok] / a3[ok]) / tot
        r[ok] = np.where(r[ok] < 1, 1.0 / r[ok], r[ok])
    v = r[ok]
    return float(np.mean(v)), float(np.max(v)), r


def angle_distortion(P3, U):
    """mean |corner angle 3D - corner angle UV| in degrees."""
    def ang(X):
        out = []
        for k in range(3):
            a = X[:, (k + 1) % 3] - X[:, k]; b = X[:, (k + 2) % 3] - X[:, k]
            na = np.linalg.norm(a, axis=1); nb = np.linalg.norm(b, axis=1)
            c = np.einsum('ij,ij->i', a, b) / np.maximum(na * nb, 1e-30)
            out.append(np.arccos(np.clip(c, -1, 1)))
        return np.stack(out, 1)
    d = np.abs(ang(P3) - ang(U))
    return float(np.degrees(d).mean())


def flipped_count(U):
    s = tri_area2_signed(U)
    nz = np.abs(s) > 0
    if nz.sum() == 0:
        return 0
    pos = (s > 0).sum(); neg = (s < 0).sum()
    return int(min(pos, neg))  # minority orientation (per call; call per island)


def overlap_pairs(U, eps_rel=1e-6, max_pairs_chunk=200000):
    """Return array (m,2) of triangle index pairs whose UV interiors overlap (2D SAT, eps tolerant,
    so edge/vertex-sharing neighbours do not count)."""
    n = len(U)
    if n < 2:
        return np.zeros((0, 2), np.int64)
    lo = U.min(1); hi = U.max(1)
    allp = U.reshape(-1, 2)
    ext = float((allp.max(0) - allp.min(0)).max())
    if ext <= 0:
        return np.zeros((0, 2), np.int64)
    eps = eps_rel * ext
    cell = max(float(np.median((hi - lo).max(1))) * 1.5, ext / 4096)
    o = allp.min(0)
    i0 = np.floor((lo - o) / cell).astype(np.int64); i1 = np.floor((hi - o) / cell).astype(np.int64)
    span = (i1 - i0 + 1)
    W = int(i1[:, 0].max() + 2)
    keys = []; tris = []
    for t in range(n):
        xs = np.arange(i0[t, 0], i1[t, 0] + 1); ys = np.arange(i0[t, 1], i1[t, 1] + 1)
        k = (ys[:, None] * W + xs[None, :]).ravel()
        keys.append(k); tris.append(np.full(len(k), t))
    keys = np.concatenate(keys); tris = np.concatenate(tris)
    order = np.argsort(keys, kind='stable'); keys = keys[order]; tris = tris[order]
    bounds = np.flatnonzero(np.diff(keys)) + 1
    starts = np.concatenate([[0], bounds]); ends = np.concatenate([bounds, [len(keys)]])
    big = np.flatnonzero(ends - starts > 1)
    pa = []; pb = []
    for g in big:
        ts = tris[starts[g]:ends[g]]
        a, b = np.triu_indices(len(ts), 1)
        pa.append(ts[a]); pb.append(ts[b])
    if not pa:
        return np.zeros((0, 2), np.int64)
    pairs = np.stack([np.concatenate(pa), np.concatenate(pb)], 1)
    pairs = np.sort(pairs, 1)
    pairs = np.unique(pairs, axis=0)
    # bbox prefilter
    A = pairs[:, 0]; B = pairs[:, 1]
    m = np.all(lo[A] < hi[B] - eps, 1) & np.all(lo[B] < hi[A] - eps, 1)
    pairs = pairs[m]
    res = []
    for s in range(0, len(pairs), max_pairs_chunk):
        pr = pairs[s:s + max_pairs_chunk]
        TA = U[pr[:, 0]]; TB = U[pr[:, 1]]
        sep = np.zeros(len(pr), bool)
        for T in (TA, TB):
            e = np.roll(T, -1, axis=1) - T
            ax = np.stack([-e[..., 1], e[..., 0]], -1)
            ln = np.linalg.norm(ax, axis=-1, keepdims=True)
            ax = ax / np.maximum(ln, 1e-30)
            pA = np.einsum('mkd,mjd->mkj', ax, TA); pB = np.einsum('mkd,mjd->mkj', ax, TB)
            s1 = (pA.max(2) <= pB.min(2) + eps) | (pB.max(2) <= pA.min(2) + eps)
            sep |= s1.any(1)
        res.append(pr[~sep])
    return np.concatenate(res) if res else np.zeros((0, 2), np.int64)
