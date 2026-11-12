"""Geometry of the bake prototype in plain numpy (no bpy): densities, rasterizing, islands, crops.

Pixel convention (same as Blender's bake): image of W x H pixels, UV (u, v) maps to pixel coordinates
(x, y) = (u * W, v * H); pixel (i, j) has its centre at (i + 0.5, j + 0.5); array rows are j (row 0 = bottom).
"""
import numpy as np


# ---------------------------------------------------------------------------------------------------------------
# Triangles
# ---------------------------------------------------------------------------------------------------------------

def tri_areas_3d(pos, tris):
    p = pos[tris]
    return 0.5 * np.linalg.norm(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1)


def tri_areas_2d(uv):
    """uv: (T,3,2). Signed area."""
    a = uv[:, 1] - uv[:, 0]
    b = uv[:, 2] - uv[:, 0]
    return 0.5 * (a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0])


def densities(pos, tris, uv_px):
    """Texel density per triangle in px/m (sqrt of the area ratio); 0 for triangles without 3D area."""
    a3 = tri_areas_3d(pos, tris)
    a2 = np.abs(tri_areas_2d(uv_px))
    d = np.zeros(len(tris))
    ok = a3 > 1e-16
    d[ok] = np.sqrt(a2[ok] / a3[ok])
    return d


def weighted_median(values, weights):
    o = np.argsort(values)
    c = np.cumsum(weights[o])
    return float(values[o][np.searchsorted(c, 0.5 * c[-1])])


def weld_ids(pos, tol=1e-7):
    """Vertex ids merged by position (topology only)."""
    q = np.round(pos / tol).astype(np.int64)
    _, inv = np.unique(q, axis=0, return_inverse=True)
    return inv.ravel()


def edge_map(wtris):
    """{(a, b) sorted welded ids: [(tri, corner_of_a, corner_of_b), ...]}."""
    em = {}
    for t, (a, b, c) in enumerate(wtris):
        for i, j in ((0, 1), (1, 2), (2, 0)):
            va, vb = int(wtris[t, i]), int(wtris[t, j])
            key = (va, vb) if va < vb else (vb, va)
            em.setdefault(key, []).append((t, i, j))
    return em


def uv_islands(wtris, uv, tol=1e-6):
    """Island label per triangle: triangles sharing an edge with equal UVs at both ends are in one island."""
    n = len(wtris)
    parent = np.arange(n)

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for key, lst in edge_map(wtris).items():
        if len(lst) < 2:
            continue
        for (t1, i1, j1) in lst:
            for (t2, i2, j2) in lst:
                if t2 <= t1:
                    continue
                # map the edge ends of t2 to those of t1 by welded id
                ends1 = {int(wtris[t1, i1]): uv[t1, i1], int(wtris[t1, j1]): uv[t1, j1]}
                ok = True
                for c in (i2, j2):
                    if np.max(np.abs(ends1[int(wtris[t2, c])] - uv[t2, c])) > tol:
                        ok = False
                if ok:
                    a, b = find(t1), find(t2)
                    if a != b:
                        parent[a] = b
    roots = np.array([find(i) for i in range(n)])
    _, lab = np.unique(roots, return_inverse=True)
    return lab.ravel()


# ---------------------------------------------------------------------------------------------------------------
# Rasterizing
# ---------------------------------------------------------------------------------------------------------------

def barycentric(p, a, b, c):
    """p: (..., 2), a/b/c: (2,). Returns (..., 3)."""
    v0 = b - a
    v1 = c - a
    d = v0[0] * v1[1] - v0[1] * v1[0]
    if abs(d) < 1e-30:
        return None
    w = p - a
    l1 = (w[..., 0] * v1[1] - w[..., 1] * v1[0]) / d
    l2 = (v0[0] * w[..., 1] - v0[1] * w[..., 0]) / d
    return np.stack([1.0 - l1 - l2, l1, l2], axis=-1)


def barycentric_many(p, tri_uv):
    """p: (N,2), tri_uv: (N,3,2) -> (N,3); degenerate triangles give NaN."""
    a, b, c = tri_uv[:, 0], tri_uv[:, 1], tri_uv[:, 2]
    v0 = b - a
    v1 = c - a
    d = v0[:, 0] * v1[:, 1] - v0[:, 1] * v1[:, 0]
    with np.errstate(divide='ignore', invalid='ignore'):
        w = p - a
        l1 = (w[:, 0] * v1[:, 1] - w[:, 1] * v1[:, 0]) / d
        l2 = (v0[:, 0] * w[:, 1] - v0[:, 1] * w[:, 0]) / d
    return np.stack([1.0 - l1 - l2, l1, l2], axis=-1)


def rasterize_ids(uv_px, W, H, k=1, x0=0, y0=0, eps=1e-9):
    """Owner triangle of each sample point. Samples: k x k per pixel at (i + (a + 0.5) / k, ...).

    Grid covers pixels x0..x0+W-1, y0..y0+H-1 (in the uv_px frame). Returns (owner (H*k, W*k) int, -1 = none;
    count (H*k, W*k) of triangles covering the sample). Last triangle wins.
    """
    owner = np.full((H * k, W * k), -1, dtype=np.int64)
    count = np.zeros((H * k, W * k), dtype=np.int32)
    for t in range(len(uv_px)):
        tri = uv_px[t]
        lo = np.floor((tri.min(axis=0) - np.array([x0, y0])) * k - 0.5).astype(int)
        hi = np.ceil((tri.max(axis=0) - np.array([x0, y0])) * k - 0.5).astype(int)
        sx0, sy0 = max(lo[0], 0), max(lo[1], 0)
        sx1, sy1 = min(hi[0], W * k - 1), min(hi[1], H * k - 1)
        if sx1 < sx0 or sy1 < sy0:
            continue
        xs = x0 + (np.arange(sx0, sx1 + 1) + 0.5) / k
        ys = y0 + (np.arange(sy0, sy1 + 1) + 0.5) / k
        P = np.stack(np.meshgrid(xs, ys), axis=-1)
        bc = barycentric(P, tri[0], tri[1], tri[2])
        if bc is None:
            continue
        inside = np.all(bc >= -eps, axis=-1)
        if not inside.any():
            continue
        sub = owner[sy0:sy1 + 1, sx0:sx1 + 1]
        sub[inside] = t
        count[sy0:sy1 + 1, sx0:sx1 + 1] += inside
    return owner, count


def dilate_ids(owner, iterations, mask_allowed=None):
    """Grow owner ids (>= 0) into -1 pixels by 8-neighbour steps. Returns (owner, steps) with steps = ring index."""
    own = owner.copy()
    steps = np.where(own >= 0, 0, -1)
    H, W = own.shape
    for it in range(1, iterations + 1):
        new = own.copy()
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            src = np.full_like(own, -1)
            ys = slice(max(dy, 0), H + min(dy, 0))
            yd = slice(max(-dy, 0), H + min(-dy, 0))
            xs = slice(max(dx, 0), W + min(dx, 0))
            xd = slice(max(-dx, 0), W + min(-dx, 0))
            src[yd, xd] = own[ys, xs]
            take = (new < 0) & (src >= 0)
            if mask_allowed is not None:
                take &= mask_allowed
            new[take] = src[take]
        grown = (new >= 0) & (own < 0)
        steps[grown] = it
        own = new
    return own, steps


def bilinear(img, x, y):
    """img (H, W); x, y pixel coordinates (centres at +0.5). Clamped at the image edge."""
    H, W = img.shape
    fx = x - 0.5
    fy = y - 0.5
    x0 = np.floor(fx).astype(np.int64)
    y0 = np.floor(fy).astype(np.int64)
    ax = fx - x0
    ay = fy - y0
    x0c = np.clip(x0, 0, W - 1)
    x1c = np.clip(x0 + 1, 0, W - 1)
    y0c = np.clip(y0, 0, H - 1)
    y1c = np.clip(y0 + 1, 0, H - 1)
    return ((1 - ax) * (1 - ay) * img[y0c, x0c] + ax * (1 - ay) * img[y0c, x1c]
            + (1 - ax) * ay * img[y1c, x0c] + ax * ay * img[y1c, x1c])


def crop_box(uv_px, border, S=None):
    """Integer pixel box (x0, y0, w, h) around all triangles plus border pixels."""
    lo = np.floor(uv_px.reshape(-1, 2).min(axis=0)).astype(int) - border
    hi = np.ceil(uv_px.reshape(-1, 2).max(axis=0)).astype(int) + border
    return int(lo[0]), int(lo[1]), int(hi[0] - lo[0]), int(hi[1] - lo[1])
