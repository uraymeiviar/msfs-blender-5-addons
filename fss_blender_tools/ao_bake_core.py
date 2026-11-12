"""AO Bake core (auto-bake journal 20261112, Sessions 15 to 17): the master builder and the copy of the prototype, plain
numpy, so the second Blender that bakes (ao_bake_runner.py) loads this file by its path without the add-on.

The three prototype parts below are tests/bake_prototype/bake_geom.py, bake_unfold.py and bake_copy.py, copied with
their computation unchanged (only the module prefix `bg.` dropped); the prototype scripts stay as they are. After them
come the tool's own parts: the settings the prototype was measured with (Sessions 8, 11 and 14), the composition of a
master from its core and skirt bakes (step3_master.py), the evaluated triangles and their hash, 16-bit PNG files, and
the resampling of an ORM texture's green and blue inside islands (decisions 24 to 26).

Pixel convention (Blender's bake): an image of W x H pixels, UV (u, v) at pixel coordinates (u * W, v * H), pixel (i, j)
has its centre at (i + 0.5, j + 0.5); arrays are indexed [j, i] with row 0 at the bottom.
"""
import hashlib
import json
import math
import os
import struct
import zlib

import numpy as np


# -------------------------------------------------------------------------------------------------------------------
# Geometry (tests/bake_prototype/bake_geom.py)
# -------------------------------------------------------------------------------------------------------------------

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


def bilinear(img, x, y, den=1.0):
    """img (H, W); x, y pixel coordinates (centres at +0.5). Clamped at the image edge. den: the values are divided
    by it (65535 for a uint16 master, read without converting the whole image)."""
    if den != 1.0:
        return bilinear(img, x, y) / den
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


# -------------------------------------------------------------------------------------------------------------------
# The master layout (tests/bake_prototype/bake_unfold.py)
# -------------------------------------------------------------------------------------------------------------------

def _tri_frame(p0, p1, p2):
    """2D placement of a 3D triangle with exact edge lengths, counter-clockwise (positive area)."""
    e1 = p1 - p0
    l01 = np.linalg.norm(e1)
    x = e1 / l01
    e2 = p2 - p0
    n = np.cross(e1, e2)
    nn = np.linalg.norm(n)
    y = np.cross(n / nn, x)
    return np.array([[0.0, 0.0], [l01, 0.0], [float(e2 @ x), float(e2 @ y)]])


def _side(a, b, p):
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


def _hinge_point(a2, b2, la, lb, away_from):
    """2D point at distance la from a2 and lb from b2, on the side of edge a2-b2 opposite to away_from."""
    d = b2 - a2
    L = np.linalg.norm(d)
    ex = d / L
    ey = np.array([-ex[1], ex[0]])
    x = (la * la - lb * lb + L * L) / (2 * L)
    y = math.sqrt(max(la * la - x * x, 0.0))
    p = a2 + ex * x + ey * y
    if _side(a2, b2, away_from) * _side(a2, b2, p) > 0:
        p = a2 + ex * x - ey * y
    return p


def _sat_overlap(A, B):
    """A: (N,3,2), B: (N,3,2) triangles, both shrunk slightly. True where the interiors overlap."""
    over = np.ones(len(A), dtype=bool)
    for T in (A, B):
        for i in range(3):
            e = T[:, (i + 1) % 3] - T[:, i]
            nrm = np.stack([-e[:, 1], e[:, 0]], axis=1)
            pa = np.einsum('nkd,nd->nk', A, nrm)
            pb = np.einsum('nkd,nd->nk', B, nrm)
            sep = (pa.max(axis=1) < pb.min(axis=1)) | (pb.max(axis=1) < pa.min(axis=1))
            over &= ~sep
    return over


def _shrink(T, f=1e-6):
    c = T.mean(axis=1, keepdims=True)
    return c + (T - c) * (1.0 - f)


class Islands:
    def __init__(self, pos, tris):
        self.pos = pos
        self.tris = tris
        self.w = weld_ids(pos)
        self.wt = self.w[tris]
        T = len(tris)
        p = pos[tris]
        n = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
        self.area = 0.5 * np.linalg.norm(n, axis=1)
        lens = np.linalg.norm(p - np.roll(p, -1, axis=1), axis=2)
        self.degenerate = (self.area <= 1e-14) | (lens.min(axis=1) <= 1e-9) | \
            np.array([len(set(r)) < 3 for r in self.wt])
        with np.errstate(invalid='ignore', divide='ignore'):
            self.normal = n / np.linalg.norm(n, axis=1, keepdims=True)
        self.edges = edge_map(self.wt)
        self.island_of = np.full(T, -1, dtype=np.int64)
        self.members = {}
        self.C = np.zeros((T, 3, 2))  # corner positions, each in the frame of its island
        self.cell = float(np.median(lens[~self.degenerate])) * 2.0 if (~self.degenerate).any() else 1.0
        self.grid = {}
        for t in range(T):
            if self.degenerate[t]:
                continue
            self.C[t] = _tri_frame(*pos[tris[t]])
            self.island_of[t] = t
            self.members[t] = [t]
            self.grid[t] = {}
            self._grid_add(t, t, self.C[t])
        self.rejected = dict(overlap=0, nonmanifold=0)

    def _cells(self, q):
        lo = np.floor(q.min(axis=0) / self.cell).astype(int)
        hi = np.floor(q.max(axis=0) / self.cell).astype(int)
        return [(i, j) for i in range(lo[0], hi[0] + 1) for j in range(lo[1], hi[1] + 1)]

    def _grid_add(self, isl, t, q):
        g = self.grid[isl]
        for c in self._cells(q):
            g.setdefault(c, []).append(t)

    def fold(self, t1, i1, j1, t2, i2, j2):
        n1, n2 = self.normal[t1], self.normal[t2]
        # consistent winding traverses the shared edge in opposite directions
        same_dir = self.wt[t1, i1] == self.wt[t2, i2]
        if same_dir:
            n2 = -n2
        return math.degrees(math.acos(max(-1.0, min(1.0, float(n1 @ n2)))))

    def try_merge(self, t1, t2, a, b):
        """Hinge the smaller island flat onto the larger one across edge (a, b) of t1 and t2.

        Every triangle keeps its exact shape. A vertex may get a second position in the island: it then lies on the
        island's border in both places (a cut, as at the seam of an unrolled cylinder); a vertex can only end up inside
        the island when its fan closes, that is when its angles add up to 360 degrees. Refused when triangles overlap.
        """
        I1, I2 = self.island_of[t1], self.island_of[t2]
        if I1 == I2:
            return False
        if len(self.members[I1]) < len(self.members[I2]):
            I1, I2, t1, t2 = I2, I1, t2, t1
        r1 = [int(v) for v in self.wt[t1]]
        r2 = [int(v) for v in self.wt[t2]]
        pa1, pb1 = self.C[t1, r1.index(a)], self.C[t1, r1.index(b)]
        pa2, pb2 = self.C[t2, r2.index(a)], self.C[t2, r2.index(b)]
        c1 = self.C[t1, 3 - r1.index(a) - r1.index(b)]
        c2 = self.C[t2, 3 - r2.index(a) - r2.index(b)]
        d1 = pb1 - pa1
        d2 = pb2 - pa2
        ang = math.atan2(d1[1], d1[0]) - math.atan2(d2[1], d2[0])
        c, s = math.cos(ang), math.sin(ang)
        R = np.array([[c, -s], [s, c]])
        c2t = R @ (c2 - pa2) + pa1
        if _side(pa1, pb1, c1) * _side(pa1, pb1, c2t) > 0:
            u = d1 / np.linalg.norm(d1)
            R = (2 * np.outer(u, u) - np.eye(2)) @ R
        mem2 = self.members[I2]
        new = (self.C[mem2] - pa2) @ R.T + pa1
        # the hinge edge itself gets exactly the positions it has in the larger island
        k = mem2.index(t2)
        new[k, r2.index(a)] = pa1
        new[k, r2.index(b)] = pb1
        A, B = [], []
        g = self.grid[I1]
        for q in new:
            cand = set()
            for cc in self._cells(q):
                cand.update(g.get(cc, ()))
            for u in cand:
                A.append(q)
                B.append(self.C[u])
        if A:
            ov = _sat_overlap(_shrink(np.array(A)), _shrink(np.array(B)))
            if ov.any():
                self.rejected['overlap'] += 1
                return False
        self.C[mem2] = new
        for t, q in zip(mem2, new):
            self.island_of[t] = I1
            self.members[I1].append(t)
            self._grid_add(I1, t, q)
        del self.members[I2], self.grid[I2]
        return True
    def build(self, order='fold'):
        """order: 'fold' joins the smallest fold first; 'length' the longest shared edge first (fold breaks ties);
        'bucket' folds in 15 degree steps, the longest edge first within a step."""
        cand = []
        for (a, b), lst in self.edges.items():
            if len(lst) != 2:
                if len(lst) > 2:
                    self.rejected['nonmanifold'] += 1
                continue
            (t1, i1, j1), (t2, i2, j2) = lst
            if self.degenerate[t1] or self.degenerate[t2]:
                continue
            f = self.fold(t1, i1, j1, t2, i2, j2)
            L = float(np.linalg.norm(self.pos[self.tris[t1, i1]] - self.pos[self.tris[t1, j1]]))
            if order == 'length':
                k = (-round(L, 9), round(f, 6))
            elif order == 'bucket':
                k = (int(f // 15.0), -round(L, 9))
            else:
                k = (round(f, 6), -(self.area[t1] + self.area[t2]))
            cand.append(k + (a, b, t1, t2))
        cand.sort()
        self.join_order = cand
        if order.startswith('growlen'):
            return self._grow(float(order[7:] or 180.0), longest_first=True)
        if order.startswith('grow'):
            return self._grow(float(order[4:] or 180.0))
        for *_k, a, b, t1, t2 in cand:
            self.try_merge(t1, t2, a, b)
        roots = sorted(self.members.keys(), key=lambda r: (-sum(self.area[self.members[r]]), r))
        self.island_ids = {r: i for i, r in enumerate(roots)}
        return self

    def _grow(self, limit, longest_first=False):
        """P1 as written: an island grows from the largest free triangle; free neighbours join one at a time, the
        smallest fold first (the longer edge on ties), across folds up to `limit` degrees."""
        import heapq
        adj = {}
        for (f, _x, a, b, t1, t2) in self.join_order:
            adj.setdefault(t1, []).append((f, t2, a, b))
            adj.setdefault(t2, []).append((f, t1, a, b))
        free = set(t for t in range(len(self.tris)) if not self.degenerate[t])
        by_area = sorted(free, key=lambda t: (-self.area[t], t))
        for seed in by_area:
            if seed not in free:
                continue
            free.discard(seed)
            heap = []

            def push(t):
                for (f, u, a, b) in adj.get(t, ()):
                    if u in free and f <= limit:
                        L = float(np.linalg.norm(self.pos[self.tris[t][list(self.wt[t]).index(a)]]
                                                 - self.pos[self.tris[t][list(self.wt[t]).index(b)]]))
                        key = (-round(L, 9), f) if longest_first else (f, -L)
                        heapq.heappush(heap, key + (u, t, a, b))
            push(seed)
            while heap:
                _k1, _k2, u, t, a, b = heapq.heappop(heap)
                if u not in free:
                    continue
                if self.try_merge(t, u, a, b):
                    free.discard(u)
                    push(u)
        roots = sorted(self.members.keys(), key=lambda r: (-sum(self.area[self.members[r]]), r))
        self.island_ids = {r: i for i, r in enumerate(roots)}
        return self


def _hull(pts):
    pts = sorted(map(tuple, pts))
    if len(pts) <= 2:
        return np.array(pts)

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return np.array(lower[:-1] + upper[:-1])


def _min_rect_rotation(pts):
    h = _hull(pts)
    if len(h) < 3:
        return 0.0
    best = (np.inf, 0.0)
    for i in range(len(h)):
        e = h[(i + 1) % len(h)] - h[i]
        ang = -math.atan2(e[1], e[0])
        c, s = math.cos(ang), math.sin(ang)
        q = h @ np.array([[c, -s], [s, c]]).T
        ext = q.max(axis=0) - q.min(axis=0)
        area = ext[0] * ext[1]
        # prefer landscape for the shelf packer
        if ext[1] > ext[0]:
            ang += math.pi / 2
        if area < best[0] - 1e-18:
            best = (area, ang)
    return best[1]


def _clip(poly, clip):
    """Sutherland-Hodgman: poly (list of 2D) clipped by a convex counter-clockwise polygon."""
    out = list(poly)
    for i in range(len(clip)):
        a, b = clip[i], clip[(i + 1) % len(clip)]
        inp, out = out, []
        if not inp:
            break
        for j in range(len(inp)):
            p, q = inp[j], inp[(j + 1) % len(inp)]
            sp, sq = _side(a, b, p), _side(a, b, q)
            if sp >= 0:
                out.append(p)
            if (sp >= 0) != (sq >= 0):
                t = sp / (sp - sq)
                out.append(p + (q - p) * t)
    return out


def build_master(pos, tris, cn, density, gutter=2, order='fold', mirror_open=False, fold_split=None):
    """Returns a dict with the master layout: per triangle island id and master UV in px; core and skirt meshes.

    mirror_open (P15): a border edge without a 3D neighbour (open mesh border) gets the face itself mirrored across
    the edge as its skirt piece; without it such edges get no skirt (the corner fill takes the nearest pixel).
    fold_split (P18, degrees): islands grow ('growlen' only) across folds of at most this angle, so an edge whose
    faces differ by more is never joined inside an island; and a border edge whose nearest 3D neighbour lies across
    such a fold gets the face itself mirrored as its skirt piece (the copy's surface-aware read would skip the
    neighbour's texels), as mirror_open does at open edges. Such an edge is also never counted as an inner edge."""
    if fold_split is not None:
        if order != 'growlen':
            raise ValueError('fold_split needs order growlen')
        order = f'growlen{float(fold_split)}'
    isl = Islands(pos, tris).build(order)
    T = len(tris)
    island = np.full(T, -1, dtype=np.int64)
    for r, i in isl.island_ids.items():
        island[isl.members[r]] = i
    n_isl = len(isl.island_ids)
    # island frames in px, rotated to the min-area rectangle
    frames = {}
    for r, i in isl.island_ids.items():
        mem = isl.members[r]
        P = isl.C[mem] * density
        ang = _min_rect_rotation(P.reshape(-1, 2))
        c, s = math.cos(ang), math.sin(ang)
        Rm = np.array([[c, -s], [s, c]])
        P = P @ Rm.T
        frames[i] = (r, mem, P)
    # shelf packing of rectangles (island bbox + gutter on each side, integer pixels)
    rects = []
    for i in range(n_isl):
        r, mem, P = frames[i]
        lo, hi = P.reshape(-1, 2).min(axis=0), P.reshape(-1, 2).max(axis=0)
        w = int(math.ceil(hi[0] - lo[0])) + 2 * gutter + 1
        h = int(math.ceil(hi[1] - lo[1])) + 2 * gutter + 1
        rects.append((i, w, h, lo))
    total = sum(w * h for _, w, h, _ in rects)
    width = max(max(w for _, w, _, _ in rects), int(math.ceil(math.sqrt(total) * 1.15)))
    order = sorted(rects, key=lambda r: (-r[2], -r[1], r[0]))
    x = y = shelf_h = 0
    place = {}
    for i, w, h, lo in order:
        if x + w > width:
            x, y, shelf_h = 0, y + shelf_h, 0
        place[i] = (x, y, w, h, lo)
        x += w
        shelf_h = max(shelf_h, h)
    W = width
    H = y + shelf_h
    # master UV in px per triangle corner
    muv = np.zeros((T, 3, 2))
    for i in range(n_isl):
        r, mem, P = frames[i]
        px, py, w, h, lo = place[i]
        off = np.array([px + gutter + 0.5, py + gutter + 0.5]) - lo
        muv[mem] = P + off
    # border edges and the skirt
    skirt_pos, skirt_uv, skirt_n, skirt_isl, skirt_src = [], [], [], [], []
    band = gutter + 1.0
    n_border = n_no_neighbour = n_mirrored = n_mirrored_fold = n_fold_inner = 0
    for t in range(T):
        i = island[t]
        if i < 0:
            continue
        for ci, cj in ((0, 1), (1, 2), (2, 0)):
            a, b = int(isl.wt[t, ci]), int(isl.wt[t, cj])
            key = (a, b) if a < b else (b, a)
            lst = isl.edges[key]
            mine = [e for e in lst if e[0] == t][0]
            inner = [u for (u, iu, ju) in lst if u != t and island[u] == i
                     and np.allclose(muv[u][list(isl.wt[u]).index(a)], muv[t][ci], rtol=0, atol=1e-6)
                     and np.allclose(muv[u][list(isl.wt[u]).index(b)], muv[t][cj], rtol=0, atol=1e-6)]
            if fold_split is not None and inner:
                # P18: a fold over the limit is never an inner edge, even where a closing fan made it continuous
                folded = [u for u in inner if isl.fold(t, mine[1], mine[2], *[e for e in lst if e[0] == u][0])
                          > fold_split]
                n_fold_inner += len(folded)
                inner = [u for u in inner if u not in folded]
            if inner:
                continue
            n_border += 1
            neigh = [(u, iu, ju) for (u, iu, ju) in lst if u != t and not isl.degenerate[u]]
            if not neigh:
                n_no_neighbour += 1
                if not mirror_open:
                    continue
                # P15: an open edge gets the face itself, mirrored across the edge (the hinge point of the face's
                # own third corner, on the far side), so the skirt bakes the face's own surface near the edge
                u = t
                n_mirrored += 1
            else:
                u, iu, ju = min(neigh, key=lambda e: (isl.fold(t, mine[1], mine[2], e[0], e[1], e[2]), e[0]))
                if fold_split is not None and isl.fold(t, mine[1], mine[2], u, iu, ju) > fold_split:
                    # P18: the neighbour lies across a split fold; the face itself, mirrored, is the skirt
                    u = t
                    n_mirrored_fold += 1
            a2, b2 = muv[t][ci], muv[t][cj]
            c_own = muv[t][3 - ci - cj]
            ru = [int(v) for v in isl.wt[u]]
            ka, kb = ru.index(a), ru.index(b)
            kc = 3 - ka - kb
            P3 = pos[tris[u]]
            la = np.linalg.norm(P3[kc] - P3[ka]) * density
            lb = np.linalg.norm(P3[kc] - P3[kb]) * density
            c2 = _hinge_point(a2, b2, la, lb, c_own)
            tri2 = np.zeros((3, 2))
            tri2[ka], tri2[kb], tri2[kc] = a2, b2, c2
            d = b2 - a2
            nrm = np.array([-d[1], d[0]]) / np.linalg.norm(d)
            if _side(a2, b2, a2 + nrm) * _side(a2, b2, c_own) > 0:
                nrm = -nrm
            quad = [a2, b2, b2 + nrm * band, a2 + nrm * band]
            # make the clip polygon counter-clockwise
            qa = np.array(quad)
            if tri_areas_2d(qa[None, [0, 1, 2]])[0] < 0:
                quad = quad[::-1]
            poly = _clip([tri2[0], tri2[1], tri2[2]] if tri_areas_2d(tri2[None])[0] > 0
                         else [tri2[0], tri2[2], tri2[1]], quad)
            if len(poly) < 3:
                continue
            poly = np.array(poly)
            bcs = barycentric(poly, tri2[0], tri2[1], tri2[2])
            if bcs is None:
                continue
            p3 = bcs @ P3
            nn = bcs @ cn[u]
            nn /= np.linalg.norm(nn, axis=1, keepdims=True)
            for k in range(1, len(poly) - 1):
                idx = [0, k, k + 1]
                if abs(tri_areas_2d(poly[None, idx])[0]) < 1e-9:
                    continue
                skirt_pos.append(p3[idx])
                skirt_uv.append(poly[idx])
                skirt_n.append(nn[idx])
                skirt_isl.append(i)
                skirt_src.append(u)
    core = ~isl.degenerate
    rect = np.array([place[i][:4] for i in range(n_isl)], dtype=np.int64)
    return dict(W=int(W), H=int(H), density=float(density), gutter=gutter, island=island, muv=muv,
                n_islands=n_isl, rects=rect, degenerate=isl.degenerate,
                core_tris=np.nonzero(core)[0],
                skirt_pos=np.array(skirt_pos).reshape(-1, 3, 3), skirt_uv=np.array(skirt_uv).reshape(-1, 3, 2),
                skirt_n=np.array(skirt_n).reshape(-1, 3, 3), skirt_island=np.array(skirt_isl, dtype=np.int64),
                skirt_src=np.array(skirt_src, dtype=np.int64),
                n_border_edges=n_border, n_border_without_neighbour=n_no_neighbour, n_mirrored=n_mirrored,
                n_mirrored_fold=n_mirrored_fold, n_fold_inner_cut=n_fold_inner, fold_split=fold_split,
                rejected=isl.rejected,
                n_join_candidates=len(isl.join_order))


def check_master(pos, tris, m):
    """Edge-length check (master px / density vs 3D), pixel overlaps of the core, gutter share."""
    core = m['core_tris']
    P = pos[tris[core]]
    U = m['muv'][core] / m['density']
    l3 = np.linalg.norm(P - np.roll(P, -1, axis=1), axis=2)
    l2 = np.linalg.norm(U - np.roll(U, -1, axis=1), axis=2)
    rel = np.abs(l2 - l3) / l3
    # the same with the float32 UVs Blender stores (normalised to the image size)
    scale = np.array([m['W'], m['H']], dtype=np.float64)
    U32 = ((m['muv'][core] / scale).astype(np.float32).astype(np.float64) * scale) / m['density']
    l2f = np.linalg.norm(U32 - np.roll(U32, -1, axis=1), axis=2)
    rel32 = np.abs(l2f - l3) / l3
    owner, count = rasterize_ids(m['muv'][core], m['W'], m['H'], eps=-1e-7)
    covered = int((count > 0).sum())
    overlap_px = int((count > 1).sum())
    in_rect = np.zeros((m['H'], m['W']), dtype=bool)
    for x, y, w, h in m['rects']:
        in_rect[y:y + h, x:x + w] = True
    return dict(edge_rel_err_max=float(rel.max()), edge_rel_err_p99=float(np.percentile(rel, 99)),
                edge_rel_err_max_float32_uv=float(rel32.max()), faces_checked=int(len(core)),
                faces_over_rel_1e_4=int((rel.max(axis=1) > 1e-4).sum()), overlap_pixels=overlap_px,
                core_pixels=covered, rect_pixels=int(in_rect.sum()), image_pixels=int(m['W'] * m['H']),
                gutter_share_of_rects=float(1 - covered / max(in_rect.sum(), 1)),
                non_island_share_of_image=float(1 - covered / (m['W'] * m['H'])))


# -------------------------------------------------------------------------------------------------------------------
# The copy (tests/bake_prototype/bake_copy.py)
# -------------------------------------------------------------------------------------------------------------------

def _neighbours(wt):
    """(T,3) neighbour triangle across the edge opposite corner k (-1 if none), choosing the first other triangle."""
    em = edge_map(wt)
    nb = np.full((len(wt), 3), -1, dtype=np.int64)
    for lst in em.values():
        for (t, i, j) in lst:
            others = [u for (u, _, _) in lst if u != t]
            if others:
                nb[t, 3 - i - j] = others[0]
    return nb


def _hinged_uv(pos, tris, wt, uvpx, t, k, u):
    """UV triangle (3,2) of neighbour u laid flat across the edge of t opposite corner k, in t's affine UV map."""
    a, b = [c for c in range(3) if c != k]
    va, vb = wt[t, a], wt[t, b]
    ru = list(wt[u])
    ka, kb = ru.index(va), ru.index(vb)
    kc = 3 - ka - kb
    P = pos[tris[t]]
    Q = pos[tris[u]]
    # rotate Q's third vertex about the shared edge into t's plane, on the side away from t's third vertex
    e = P[b] - P[a]
    e_hat = e / np.linalg.norm(e)
    n_t = np.cross(P[1] - P[0], P[2] - P[0])
    n_t /= np.linalg.norm(n_t)
    q = Q[kc] - P[a]
    along = q @ e_hat
    perp = np.linalg.norm(q - along * e_hat)
    in_plane = np.cross(n_t, e_hat)
    if (P[k] - P[a]) @ in_plane > 0:
        in_plane = -in_plane
    c3 = P[a] + along * e_hat + perp * in_plane
    # t's affine map 3D (in its plane) -> UV
    M = np.array([P[1] - P[0], P[2] - P[0]]).T  # 3x2
    coef, *_ = np.linalg.lstsq(M, c3 - P[0], rcond=None)
    bc3 = np.array([1 - coef.sum(), coef[0], coef[1]])
    out = np.zeros((3, 2))
    out[ka] = uvpx[t, a]
    out[kb] = uvpx[t, b]
    out[kc] = bc3 @ uvpx[t]
    return out


def copy_master(pos, tris, uvpx, tisl, master, crop, k, padding=8, outside_mode='tri', kmax=16, surface_cos=None,
                same_face=False):
    """Returns (image (h,w) with -1 where nothing was written, info)."""
    x0, y0, w, h = crop
    muv = master['muv']
    M = master['image']
    # a tool master is uint16 (Session 20): only the texels read are converted
    den = 65535.0 if M.dtype == np.uint16 else 1.0
    mH, mW = M.shape
    rect_id = master.get('rect_id')
    rects = np.asarray(master['rects']) if rect_id is None else None
    filled = master['filled']
    misl = master['island']

    def in_own_rect(xi, yi, isl):
        """rect_id[yi, xi] == isl, from the rectangles (they do not overlap) when there is no per-pixel map."""
        if rect_id is not None:
            return rect_id[yi, xi] == isl
        r = rects[np.maximum(isl, 0)]
        return (isl >= 0) & (xi >= r[:, 0]) & (xi < r[:, 0] + r[:, 2]) & (yi >= r[:, 1]) & (yi < r[:, 1] + r[:, 3])
    wt = weld_ids(pos)[tris]
    nb = _neighbours(wt)
    face_map = master.get('face_map')
    pp = pos[tris]
    tri_normal = np.cross(pp[:, 1] - pp[:, 0], pp[:, 2] - pp[:, 0])
    tri_normal /= np.maximum(np.linalg.norm(tri_normal, axis=1, keepdims=True), 1e-30)

    def read(tri_ids, bary):
        """bary (N,3) w.r.t. triangles tri_ids -> master values; clamps points outside their island's baked area."""
        mp = np.einsum('nk,nkd->nd', bary, muv[tri_ids])
        xi = np.clip(np.floor(mp[:, 0]).astype(np.int64), 0, mW - 1)
        yi = np.clip(np.floor(mp[:, 1]).astype(np.int64), 0, mH - 1)
        ok = in_own_rect(xi, yi, misl[tri_ids]) & filled[yi, xi]
        bad = ~ok
        n_clamped = int(bad.sum())
        if bad.any():
            bb = np.clip(bary[bad], 0, None)
            bb /= np.maximum(bb.sum(axis=1, keepdims=True), 1e-30)
            mp[bad] = np.einsum('nk,nkd->nd', bb, muv[tri_ids[bad]])
        if surface_cos is None or face_map is None:
            return bilinear(M, mp[:, 0], mp[:, 1], den), n_clamped
        return _surface_bilinear(mp, tri_ids), n_clamped

    def _surface_bilinear(mp, tri_ids):
        """Bilinear read that keeps only texels showing a face of the same surface (normal within the angle)."""
        fx = mp[:, 0] - 0.5
        fy = mp[:, 1] - 0.5
        xa = np.floor(fx).astype(np.int64)
        ya = np.floor(fy).astype(np.int64)
        ax = fx - xa
        ay = fy - ya
        acc = np.zeros(len(mp))
        wsum = np.zeros(len(mp))
        acc_f = np.zeros(len(mp))
        wsum_f = np.zeros(len(mp))
        nt = tri_normal[tri_ids]
        for dx, dy, wgt in ((0, 0, (1 - ax) * (1 - ay)), (1, 0, ax * (1 - ay)), (0, 1, (1 - ax) * ay), (1, 1, ax * ay)):
            xc = np.clip(xa + dx, 0, mW - 1)
            yc = np.clip(ya + dy, 0, mH - 1)
            f = face_map[yc, xc]
            ok = (f >= 0) & (np.einsum('nd,nd->n', tri_normal[np.maximum(f, 0)], nt) >= surface_cos)
            wv = np.where(ok, wgt, 0.0)
            mv = M[yc, xc] / den
            acc += wv * mv
            wsum += wv
            if same_face:
                wf = np.where(f == tri_ids, wgt, 0.0)
                acc_f += wf * mv
                wsum_f += wf
        plain = bilinear(M, mp[:, 0], mp[:, 1], den)
        out_ = np.where(wsum > 1e-9, acc / np.maximum(wsum, 1e-30), plain)
        if same_face:
            out_ = np.where(wsum_f > 1e-9, acc_f / np.maximum(wsum_f, 1e-30), out_)
        return out_

    owner_c, count_c = rasterize_ids(uvpx, w, h, 1, x0, y0)
    out = np.full((h, w), -1.0)
    # samples per pixel axis per triangle: the target pixel's footprint in the master (largest singular value of the
    # map layout px -> master px) sampled at least twice per master pixel; `k` is the minimum, kmax the cap
    Mt = np.stack([uvpx[:, 1] - uvpx[:, 0], uvpx[:, 2] - uvpx[:, 0]], axis=2)
    Mm = np.stack([muv[:, 1] - muv[:, 0], muv[:, 2] - muv[:, 0]], axis=2)
    with np.errstate(all='ignore'):
        J = Mm @ np.linalg.pinv(Mt)
        sig = np.linalg.svd(J, compute_uv=False)[:, 0]
    sig = np.where(np.isfinite(sig), sig, 1.0)
    kt_raw = np.ceil(2 * sig).astype(np.int64)
    kt = np.clip(kt_raw, k, kmax)
    n_cl_in = 0
    jj, ii = np.nonzero(owner_c >= 0)
    lvl = kt[owner_c[jj, ii]]
    capped_px = int((kt_raw[owner_c[jj, ii]] > kmax).sum())
    for L in np.unique(lvl):
        sel = lvl == L
        pj_, pi_ = jj[sel], ii[sel]
        # owners of the sub-samples on an L x L grid, only over the box of these pixels
        bx0, by0 = int(pi_.min()), int(pj_.min())
        bw, bh = int(pi_.max()) - bx0 + 1, int(pj_.max()) - by0 + 1
        owner_s, _ = rasterize_ids(uvpx, bw, bh, int(L), x0 + bx0, y0 + by0)
        sub = (np.arange(L) + 0.5) / L
        sx, sy = np.meshgrid(sub, sub)
        sx, sy = sx.ravel(), sy.ravel()
        n = len(pi_)
        px = (x0 + pi_[:, None] + sx[None, :]).ravel()
        py = (y0 + pj_[:, None] + sy[None, :]).ravel()
        own_pix = np.repeat(owner_c[pj_, pi_], L * L)
        a_idx = np.arange(L)
        ax_, ay_ = np.meshgrid(a_idx, a_idx)
        si = ((pi_ - bx0)[:, None] * L + ax_.ravel()[None, :]).ravel()
        sj = ((pj_ - by0)[:, None] * L + ay_.ravel()[None, :]).ravel()
        own_sub = owner_s[sj, si]
        if outside_mode == 'tri':
            # as Cycles: every jitter point stays on the pixel's own triangle (mirrored back), so only points on
            # that triangle count
            same = own_sub == own_pix
        else:
            same = (own_sub >= 0) & (tisl[np.maximum(own_sub, 0)] == tisl[own_pix])
        use = np.where(same, own_sub, own_pix)
        # 'drop': Cycles mirrors jitter that leaves the pixel's triangle back into it, so points beyond the island
        # border are left out and a border pixel averages its part inside the island; 'extend' keeps them
        wgt = same.astype(np.float64) if outside_mode in ('drop', 'tri') else np.ones(len(use))
        bary = barycentric_many(np.stack([px, py], axis=1), uvpx[use])
        vals, c_ = read(use, bary)
        n_cl_in += c_
        wv = wgt.reshape(n, L * L)
        vv = vals.reshape(n, L * L)
        sw = wv.sum(axis=1)
        cb = barycentric_many(np.stack([x0 + pi_ + 0.5, y0 + pj_ + 0.5], axis=1), uvpx[owner_c[pj_, pi_]])
        cv, _ = read(owner_c[pj_, pi_], cb)
        out[pj_, pi_] = np.where(sw > 0, (vv * wv).sum(axis=1) / np.maximum(sw, 1e-30), cv)
    # padding pixels
    grown, steps = dilate_ids(owner_c, padding)
    pj, pi = np.nonzero((owner_c < 0) & (grown >= 0))
    n_cl_pad = 0
    n_no_nb = 0
    if len(pi):
        T = grown[pj, pi]
        cen = np.stack([x0 + pi + 0.5, y0 + pj + 0.5], axis=1)
        bc_c = barycentric_many(cen, uvpx[T])
        kmin = np.argmin(bc_c, axis=1)
        U = nb[T, kmin]
        cache = {}
        tri_uv = np.zeros((len(T), 3, 2))
        src = np.zeros(len(T), dtype=np.int64)
        for n in range(len(T)):
            t, kk, u = int(T[n]), int(kmin[n]), int(U[n])
            if u < 0 or bc_c[n, kk] >= 0:
                tri_uv[n] = uvpx[t]
                src[n] = t
                n_no_nb += int(u < 0)
                continue
            key = (t, kk)
            if key not in cache:
                cache[key] = _hinged_uv(pos, tris, wt, uvpx, t, kk, u)
            tri_uv[n] = cache[key]
            src[n] = u
        plvl = kt[T]
        for L in np.unique(plvl):
            sel = np.nonzero(plvl == L)[0]
            sub = (np.arange(L) + 0.5) / L
            sx, sy = np.meshgrid(sub, sub)
            sx, sy = sx.ravel(), sy.ravel()
            ppx = (pi[sel][:, None] + x0 + sx[None, :]).ravel()
            ppy = (pj[sel][:, None] + y0 + sy[None, :]).ravel()
            bary = barycentric_many(np.stack([ppx, ppy], axis=1), np.repeat(tri_uv[sel], L * L, axis=0))
            # stay on the neighbour face: its nearest point (a thin neighbour extended further would reach other faces)
            bary = np.clip(bary, 0, None)
            bary /= np.maximum(bary.sum(axis=1, keepdims=True), 1e-30)
            vals, c_ = read(np.repeat(src[sel], L * L), bary)
            n_cl_pad += c_
            out[pj[sel], pi[sel]] = vals.reshape(len(sel), L * L).mean(axis=1)
    info = dict(k_min=k, k_max=kmax, k_levels={int(L): int((lvl == L).sum()) for L in np.unique(lvl)},
                px_at_k_cap=capped_px, footprint_px_median=float(np.median(sig)), footprint_px_max=float(sig.max()),
                inside_px=int(len(ii)), padding_px=int(len(pi)), clamped_inside_points=n_cl_in,
                clamped_padding_points=n_cl_pad, padding_without_neighbour=n_no_nb,
                stacked_px=int((count_c > 1).sum()))
    return out, info, owner_c, steps, count_c


# ---------------------------------------------------------------------------------------------------------------------
# The tool's settings: the prototype as measured in Sessions 8, 11 and 14 (decision 9)
# ---------------------------------------------------------------------------------------------------------------------

SCHEMA = 1  # index.json and the npz layout
METHOD = 1  # what a master is (the settings below); a change makes every master's surroundings stale
DENSITY_FACTOR = 4.0  # master density = 4 x the object's median density in its layout at bake time (Session 12)
GUTTER = 2
ORDER = 'growlen'
MIRROR_OPEN = True  # P15
FOLD_SPLIT = 30.0  # P18, degrees
SURFACE_DEG = 30.0  # the copy's surface-aware read
SURFACE_COS = math.cos(math.radians(SURFACE_DEG))
K_MIN = 2
K_MAX = 16
SEEDS = (11, 12)  # core and skirt bakes
EXTRUSION = 2e-5  # m, selected-to-active from the target (step3_master.py)
RAY_DISTANCE = 4e-5
MASTER_KEYS = ('muv', 'island', 'rects', 'filled', 'face_map', 'tri_src')


def method_settings():
    return dict(method=METHOD, density_factor=DENSITY_FACTOR, gutter=GUTTER, order=ORDER, mirror_open=MIRROR_OPEN,
                fold_split=FOLD_SPLIT, surface_deg=SURFACE_DEG, seeds=list(SEEDS), extrusion=EXTRUSION,
                ray_distance=RAY_DISTANCE)


def safe_stem(kind, name):
    """File name stem of a master: the name made safe for the file system plus a short hash of kind and name."""
    safe = ''.join(c if (c.isalnum() or c in '-_.') else '_' for c in name).strip('.') or 'master'
    digest = hashlib.sha1(f'{kind}:{name}'.encode('utf-8')).hexdigest()[:8]
    return f'{safe[:80]}_{digest}'


# ---------------------------------------------------------------------------------------------------------------------
# A master from its two bakes (step3_master.py, compose and face map)
# ---------------------------------------------------------------------------------------------------------------------

def master_density(pos, tris, uv_px, factor=DENSITY_FACTOR):
    """factor x the area-weighted median texel density (px/m) of the triangles in their layout; 0 without one."""
    dens = densities(pos, tris, uv_px)
    a3 = tri_areas_3d(pos, tris)
    ok = (dens > 0) & np.isfinite(dens)
    if not ok.any():
        return 0.0
    return factor * weighted_median(dens[ok], a3[ok])


FILL = 2 * GUTTER + 4  # the nearest fill and the face map grow this many pixels inside each island's rectangle
TILE_MIN = 512
# the tile sizes the runner chooses from (decision 32): tiles over 2048 px were slower, not faster (Session 20: the
# 214 Mpx floor's bake 300 s in tiles of 1024 and 2048 px, 319 s in 4096 and 320 s in 8192 px, at 2.3, 2.3, 4.8 and
# 16.2 GB), so more memory buys no time and the largest tile is 2048 px; a smaller budget gets smaller tiles
TILE_SIZES = (2048, 1024, 512)


# The memory model of the bake in tiles (Session 20, measured on the floor at 54 and 214 Mpx and on the cap): per
# master pixel the uint16 image, the flags and the int32 face map with the composition's and the files' temporaries
# (about 10 bytes: 2.3 GB peak at 214 Mpx with small tiles); per tile pixel Cycles' bake data and the tile's float
# image and buffers (measured 240 to 280 bytes).
BYTES_PER_MASTER_PX = 10.0
BYTES_PER_TILE_PX = 280.0
TILE_OVERHEAD = 0.25 * 2 ** 30  # bytes beyond the pixels (the scene's copies, Cycles' BVH, a composition window)
BUDGET_SHARE = 0.6  # of the physical memory free when the bake starts
BUDGET_MAX = 32 * 2 ** 30  # decision 32: never more than 32 GB


def memory_status():
    """(total, available) physical memory in bytes (Windows: GlobalMemoryStatusEx), or (None, None)."""
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong),
                        ('ullTotalPhys', ctypes.c_ulonglong), ('ullAvailPhys', ctypes.c_ulonglong),
                        ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong),
                        ('ullTotalVirtual', ctypes.c_ulonglong), ('ullAvailVirtual', ctypes.c_ulonglong),
                        ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]
        st = MEMORYSTATUSEX()
        st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return int(st.ullTotalPhys), int(st.ullAvailPhys)
    except (AttributeError, OSError, ImportError):
        pass
    try:
        info = {}
        with open('/proc/meminfo', encoding='ascii') as f:
            for line in f:
                k, v = line.split(':', 1)
                info[k] = int(v.split()[0]) * 1024
        return info['MemTotal'], info.get('MemAvailable', info['MemFree'])
    except (OSError, KeyError, ValueError):
        return None, None


def process_memory():
    """(working set, peak working set) of this process in bytes (Windows: GetProcessMemoryInfo), or (None, None)."""
    try:
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD),
                        ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t),
                        ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t),
                        ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t), ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                        ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t)]
        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.GetCurrentProcess.argtypes = []
        k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
        k32.K32GetProcessMemoryInfo.restype = wintypes.BOOL
        if k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
            return int(pmc.WorkingSetSize), int(pmc.PeakWorkingSetSize)
    except (AttributeError, OSError, ImportError, ctypes.ArgumentError):
        pass
    try:
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        return None, peak
    except (ImportError, AttributeError):
        return None, None


def memory_budget(override_gb=None):
    """The bake's memory budget in bytes (decision 32): an override (tests), else BUDGET_SHARE of the physical
    memory free now, at most BUDGET_MAX; 4 GB when the free memory cannot be read."""
    if override_gb:
        return int(float(override_gb) * 2 ** 30)
    _total, avail = memory_status()
    if not avail:
        return 4 * 2 ** 30
    return int(min(BUDGET_MAX, BUDGET_SHARE * avail))


def choose_tile(W, H, budget, in_use):
    """The largest tile size whose bake fits the budget: the whole master when it is not larger than the largest of
    TILE_SIZES and fits, else the largest of TILE_SIZES that fits; in_use: the process's working set before the
    master (Blender, the scene). Returns (size, estimate of the peak in bytes, fits)."""
    fixed = in_use + BYTES_PER_MASTER_PX * W * H
    longest = max(W, H)
    sizes = ([longest] if longest <= TILE_SIZES[0] else []) + [s for s in TILE_SIZES if s < longest]
    for s in sizes:
        est = fixed + TILE_OVERHEAD + BYTES_PER_TILE_PX * min(s, W) * min(s, H)
        if est <= budget:
            return int(s), est, True
    s = min(TILE_MIN, longest)
    return int(s), fixed + TILE_OVERHEAD + BYTES_PER_TILE_PX * min(s, W) * min(s, H), False


def tile_grid(W, H, size):
    """Tiles (x0, y0, w, h) of at most size x size px over a W x H master, row by row from the bottom left."""
    size = max(1, int(size))
    return [(x0, y0, min(size, W - x0), min(size, H - y0)) for y0 in range(0, H, size) for x0 in range(0, W, size)]


def tile_seed(base, i, n):
    """Cycles' seed of tile i of n: the base seed for a single tile (the untiled bake), else one per tile, since
    Cycles' noise depends on the pixel's position in the image and would repeat from tile to tile."""
    return int(base) if n == 1 else int(base) + 1009 * (int(i) + 1)


def tris_in_window(uvpx, x0, y0, w, h, margin=1.0):
    """Indices of the triangles (N, 3, 2 px) whose bounding box overlaps the window (plus a margin)."""
    if not len(uvpx):
        return np.zeros(0, dtype=np.int64)
    lo = uvpx.min(axis=1)
    hi = uvpx.max(axis=1)
    ok = ((hi[:, 0] >= x0 - margin) & (lo[:, 0] <= x0 + w + margin) & (hi[:, 1] >= y0 - margin)
          & (lo[:, 1] <= y0 + h + margin))
    return np.nonzero(ok)[0]


def rect_window(rects, x0, y0, w, h):
    """The island rectangle id (int32, -1 for none) of each pixel of a window."""
    rid = np.full((h, w), -1, dtype=np.int32)
    r = np.asarray(rects, dtype=np.int64).reshape(-1, 4)
    if not len(r):
        return rid
    ax0 = np.maximum(r[:, 0], x0)
    ay0 = np.maximum(r[:, 1], y0)
    ax1 = np.minimum(r[:, 0] + r[:, 2], x0 + w)
    ay1 = np.minimum(r[:, 1] + r[:, 3], y0 + h)
    for i in np.nonzero((ax1 > ax0) & (ay1 > ay0))[0].tolist():
        rid[ay0[i] - y0:ay1[i] - y0, ax0[i] - x0:ax1[i] - x0] = i
    return rid


def quantize16(values):
    """Floats 0..1 as the 16-bit values of the master PNG (as write_png rounds them)."""
    return np.round(np.clip(np.asarray(values, dtype=np.float64), 0.0, 1.0) * 65535.0).astype(np.uint16)


def compose_window(m, M16, flags, face_map, win):
    """The composition of a master (step3_master.py) for one window of the whole master, after every tile is baked.

    M16 (H, W) uint16: the core and skirt values; flags (H, W) uint8: bit 1 = baked (core or skirt), set by the bake;
    this sets bit 2 = filled (baked or nearest fill) and fills, inside each island's rectangle, the pixels within
    FILL steps of a baked pixel of the same rectangle with that pixel's value; face_map (H, W) int32 gets the window's
    face per pixel (core faces, then skirt faces inside rectangles, grown FILL steps inside rectangles).
    The window is read with a halo of FILL pixels, so the result equals the composition of the whole image at once.
    Returns the window's counts."""
    W, H = m['W'], m['H']
    x0, y0, w, h = win
    ex0, ey0 = max(0, x0 - FILL), max(0, y0 - FILL)
    ex1, ey1 = min(W, x0 + w + FILL), min(H, y0 + h + FILL)
    ew, eh = ex1 - ex0, ey1 - ey0
    sub = (slice(y0 - ey0, y0 - ey0 + h), slice(x0 - ex0, x0 - ex0 + w))
    rid = rect_window(m['rects'], ex0, ey0, ew, eh)
    in_rect = rid >= 0
    baked = (flags[ey0:ey1, ex0:ex1] & 1) != 0
    idx = np.where(baked, np.arange(eh * ew, dtype=np.int32).reshape(eh, ew), np.int32(-1))
    grown, _steps = dilate_ids(idx, FILL, mask_allowed=in_rect)
    del idx, _steps
    fm = (~baked) & (grown >= 0)
    same = np.zeros_like(fm)
    same[fm] = rid.ravel()[grown[fm]] == rid[fm]
    fm &= same
    del same
    fmi = fm[sub]
    if fmi.any():
        src = M16[ey0:ey1, ex0:ex1].ravel()[grown[sub][fmi]]  # sources are baked pixels: never written by a fill
        M16[y0:y0 + h, x0:x0 + w][fmi] = src
    del grown
    filled = baked[sub] | fmi
    flags[y0:y0 + h, x0:x0 + w] |= np.where(filled, np.uint8(2), np.uint8(0))
    counts = dict(nearest_fill_px=int(fmi.sum()), rect_px_unfilled=int((in_rect[sub] & ~filled).sum()),
                  rect_px=int(in_rect[sub].sum()))
    del fm, baked
    # the face map
    core = m['core_tris']
    cuv = m['muv'][core]
    sel = tris_in_window(cuv, ex0, ey0, ew, eh)
    fmap = np.full((eh, ew), -1, dtype=np.int32)
    if len(sel):
        own, _cnt = rasterize_ids(cuv[sel], ew, eh, 1, ex0, ey0)
        fmap = np.where(own >= 0, core[sel][np.maximum(own, 0)], -1).astype(np.int32)
        del own, _cnt
    sel = tris_in_window(m['skirt_uv'], ex0, ey0, ew, eh) if len(m['skirt_pos']) else []
    if len(sel):
        own, _cnt = rasterize_ids(m['skirt_uv'][sel], ew, eh, 1, ex0, ey0)
        sk_face = np.where(own >= 0, m['skirt_src'][sel][np.maximum(own, 0)], -1)
        del own, _cnt
        take = (fmap < 0) & (sk_face >= 0) & in_rect
        fmap[take] = sk_face[take]
        del sk_face, take
    fidx = np.where(fmap >= 0, np.arange(eh * ew, dtype=np.int32).reshape(eh, ew), np.int32(-1))
    fgrown, _steps = dilate_ids(fidx, FILL, mask_allowed=in_rect)
    del fidx, _steps
    fm2 = (fmap < 0) & (fgrown >= 0)
    fmap[fm2] = fmap.ravel()[fgrown[fm2]]
    face_map[y0:y0 + h, x0:x0 + w] = fmap[sub]
    return counts


def save_master(folder, stem, M16, m, filled, face_map, tri_src, meta):
    """<stem>.ao.png (16-bit grey, written row by row from the uint16 master) and <stem>.ao.npz (the layout).
    Written to temporary names, then replaced, so a bake that stops on the way keeps the old master."""
    png = os.path.join(folder, stem + '.ao.png')
    npz = os.path.join(folder, stem + '.ao.npz')
    write_png_int(png + '.tmp', M16, bits=16)
    with open(npz + '.tmp', 'wb') as f:
        np.savez_compressed(f, muv=m['muv'], island=m['island'], density=m['density'], W=m['W'], H=m['H'],
                            rects=m['rects'], gutter=m['gutter'], degenerate=m['degenerate'], filled=filled,
                            face_map=face_map, tri_src=np.asarray(tri_src, dtype=np.int64),
                            meta=json.dumps(meta))
    os.replace(png + '.tmp', png)
    os.replace(npz + '.tmp', npz)
    return png, npz


def load_master(folder, stem):
    """The master as copy_master reads it (the image as uint16, 0..65535; the island rectangles instead of a per-pixel
    map), or None when a file is missing."""
    png = os.path.join(folder, stem + '.ao.png')
    npz = os.path.join(folder, stem + '.ao.npz')
    if not (os.path.isfile(png) and os.path.isfile(npz)):
        return None
    z = np.load(npz)
    img = read_png(png)[0]
    if img.ndim == 3:
        img = img[:, :, 0]
    H, W = img.shape
    return dict(muv=z['muv'], image=img, rects=z['rects'], filled=z['filled'], island=z['island'],
                face_map=z['face_map'], density=float(z['density']), tri_src=z['tri_src'], W=W, H=H,
                meta=json.loads(str(z['meta'])))


# ---------------------------------------------------------------------------------------------------------------------
# Evaluated triangles and their hash (bpy imported only here)
# ---------------------------------------------------------------------------------------------------------------------

def evaluated_triangles(obj, depsgraph, uv_names=()):
    """The object's evaluated mesh (modifiers applied, current pose) as loop triangles, in object space:
    dict(co (V,3), tris (T,3) vertex ids, loops (T,3), poly (T,), mat (T,) material index, cn (T,3,3) corner normals,
    uv {name: (T,3,2)}, matrix (4,4) world). Leaves no datablock behind."""
    ev = obj.evaluated_get(depsgraph)
    me = ev.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
    try:
        me.calc_loop_triangles()
        nv = len(me.vertices)
        co = np.empty(nv * 3, dtype=np.float32)
        me.vertices.foreach_get('co', co)
        nt = len(me.loop_triangles)
        loops = np.empty(nt * 3, dtype=np.int64)
        me.loop_triangles.foreach_get('loops', loops)
        verts = np.empty(nt * 3, dtype=np.int64)
        me.loop_triangles.foreach_get('vertices', verts)
        poly = np.empty(nt, dtype=np.int64)
        me.loop_triangles.foreach_get('polygon_index', poly)
        mat = np.empty(nt, dtype=np.int64)
        me.loop_triangles.foreach_get('material_index', mat)
        cn = np.empty(len(me.loops) * 3, dtype=np.float32)
        me.corner_normals.foreach_get('vector', cn)
        cn = cn.reshape(-1, 3)[loops].reshape(nt, 3, 3)
        uvs = {}
        for name in uv_names:
            layer = me.uv_layers.get(name)
            if layer is None:
                continue
            a = np.empty(len(me.loops) * 2, dtype=np.float32)
            layer.uv.foreach_get('vector', a)
            uvs[name] = a.reshape(-1, 2)[loops].reshape(nt, 3, 2).astype(np.float64)
    finally:
        ev.to_mesh_clear()
    return dict(co=co.reshape(-1, 3).astype(np.float64), tris=verts.reshape(nt, 3), loops=loops.reshape(nt, 3),
                poly=poly, mat=mat, cn=cn.astype(np.float64), uv=uvs,
                matrix=np.array(obj.matrix_world, dtype=np.float64))


def mesh_hash(ev):
    """Mesh changed (decision 17): the evaluated triangles, their positions and their corner normals, object space."""
    h = hashlib.sha1()
    h.update(np.ascontiguousarray(ev['tris'], dtype=np.int32).tobytes())
    h.update(np.ascontiguousarray(ev['co'], dtype=np.float32).tobytes())
    h.update(np.ascontiguousarray(np.round(ev['cn'], 4) + 0.0, dtype=np.float32).tobytes())
    return h.hexdigest()[:20]


def matrix_key(matrix):
    """A world matrix as a list rounded to 1e-6 (the surroundings key)."""
    return [round(float(v), 6) + 0.0 for v in np.asarray(matrix, dtype=np.float64).ravel()]


def to_world(ev, shift=None):
    """(positions (V,3), corner normals (T,3,3)) in world space, optionally moved by -shift."""
    M = ev['matrix']
    pos = ev['co'] @ M[:3, :3].T + M[:3, 3]
    if shift is not None:
        pos = pos - shift
    nm = np.linalg.inv(M[:3, :3]).T
    cn = ev['cn'].reshape(-1, 3) @ nm.T
    cn /= np.maximum(np.linalg.norm(cn, axis=1, keepdims=True), 1e-30)
    return pos, cn.reshape(-1, 3, 3)


def world_bounds(ev):
    pos, _ = to_world(ev)
    if not len(pos):
        return None
    return pos.min(axis=0), pos.max(axis=0)


def box_gap(a, b):
    """Largest axis gap between two boxes (lo, hi); 0 when they touch or overlap."""
    return float(np.max(np.maximum(np.maximum(a[0] - b[1], b[0] - a[1]), 0.0)))


# ---------------------------------------------------------------------------------------------------------------------
# PNG files (rows bottom-up, as Blender images)
# ---------------------------------------------------------------------------------------------------------------------

def _png_chunk(tag, data):
    return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)


COLOUR_TYPE = {1: 0, 2: 4, 3: 2, 4: 6}  # channels: PNG colour type
CHANNELS = {0: 1, 4: 2, 2: 3, 6: 4}


def write_png_int(path, q, bits=16, rows=256):
    """q: (H, W) or (H, W, C) integers in the file's depth, row 0 = bottom. Filter 0, zlib level 6. Written row by
    row (`rows` at a time, one IDAT chunk per compressed block), so no copy of the whole image is made."""
    q = np.asarray(q)
    h, w = q.shape[:2]
    ch = 1 if q.ndim == 2 else q.shape[2]
    dtype = '>u2' if bits == 16 else np.uint8
    ihdr = struct.pack('>IIBBBBB', w, h, bits, COLOUR_TYPE[ch], 0, 0, 0)
    comp = zlib.compressobj(6)
    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n')
        f.write(_png_chunk(b'IHDR', ihdr))
        for top in range(0, h, rows):
            bot = min(h, top + rows)
            block = np.ascontiguousarray(q[h - bot:h - top][::-1].astype(dtype)).reshape(bot - top, -1)
            raw = np.zeros((bot - top, block.shape[1] * block.itemsize + 1), dtype=np.uint8)
            raw[:, 1:] = block.view(np.uint8).reshape(bot - top, -1)
            data = comp.compress(raw.tobytes())
            if data:
                f.write(_png_chunk(b'IDAT', data))
        f.write(_png_chunk(b'IDAT', comp.flush()))
        f.write(_png_chunk(b'IEND', b''))


def write_png(path, arr, bits=16):
    """arr: (H, W) or (H, W, C) floats in 0..1, row 0 = bottom."""
    a = np.clip(np.asarray(arr, dtype=np.float64), 0.0, 1.0)
    top = 65535.0 if bits == 16 else 255.0
    write_png_int(path, np.round(a * top).astype(np.uint16 if bits == 16 else np.uint8), bits)


def png_info(path):
    """(width, height, bits, colour type, interlace) from the header, or None for another format."""
    try:
        with open(path, 'rb') as f:
            data = f.read(33)
    except OSError:
        return None
    if len(data) < 29 or data[:8] != b'\x89PNG\r\n\x1a\n' or data[12:16] != b'IHDR':
        return None
    w, h, bits, ct, _c, _f, il = struct.unpack('>IIBBBBB', data[16:29])
    return w, h, bits, ct, il


class PngNotDecoded(Exception):
    """A PNG this reader does not decode (palette, interlace, filters Average or Paeth): read it through Blender."""


def read_png(path):
    """(values (H, W) or (H, W, C) uint16 in the file's depth, row 0 = bottom, bits, colour type). Grey, grey + alpha,
    RGB and RGBA at 8 or 16 bits, filters None, Sub and Up; raises PngNotDecoded otherwise."""
    with open(path, 'rb') as f:
        data = f.read()
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise PngNotDecoded('not a PNG')
    pos = 8
    idat = []
    w = h = bits = ct = il = 0
    while pos < len(data):
        n = struct.unpack('>I', data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + n]
        if tag == b'IHDR':
            w, h, bits, ct, _c, _f, il = struct.unpack('>IIBBBBB', chunk[:13])
        elif tag == b'IDAT':
            idat.append(chunk)
        elif tag == b'IEND':
            break
        pos += 12 + n
    if ct not in CHANNELS or bits not in (8, 16) or il:
        raise PngNotDecoded(f'colour type {ct}, {bits} bits, interlace {il}')
    ch = CHANNELS[ct]
    bpp = ch * bits // 8
    stride = w * bpp
    rowlen = 1 + stride
    vals = np.empty((h, w, ch), dtype=np.uint16)
    # decoded in blocks of rows (no copy of the whole raw image); file row y is vals row h - 1 - y
    d = zlib.decompressobj()
    pending = bytearray()
    state = dict(y=0, prev=None)

    def rows_out(n):
        block = np.frombuffer(bytes(pending[:n * rowlen]), dtype=np.uint8).reshape(n, rowlen)
        del pending[:n * rowlen]
        filters = block[:, 0]
        if np.any(filters > 2):
            raise PngNotDecoded('filter Average or Paeth')
        rows = block[:, 1:].copy()
        if np.any(filters != 0):
            for k in range(n):
                f = filters[k]
                if f == 1:
                    r = rows[k].reshape(w, bpp).astype(np.uint32)
                    rows[k] = (np.cumsum(r, axis=0) % 256).astype(np.uint8).ravel()
                elif f == 2:
                    prev = rows[k - 1] if k > 0 else state['prev']
                    if prev is not None:
                        rows[k] = (rows[k].astype(np.uint16) + prev) % 256
        state['prev'] = rows[-1].copy()
        y = state['y']
        if bits == 16:
            v = rows.view('>u2').reshape(n, w, ch)
        else:
            v = rows.reshape(n, w, ch)
        vals[h - y - n:h - y] = v[::-1]
        state['y'] = y + n

    for chunk in idat:
        data = d.decompress(chunk, 1 << 24)
        while True:
            pending.extend(data)
            n = len(pending) // rowlen
            if n:
                rows_out(min(n, h - state['y']))
            if not d.unconsumed_tail:
                break
            data = d.decompress(d.unconsumed_tail, 1 << 24)
    pending.extend(d.flush())
    n = min(len(pending) // rowlen, h - state['y'])
    if n:
        rows_out(n)
    if state['y'] != h:
        raise PngNotDecoded(f'{state["y"]} of {h} rows decoded')
    return (vals[:, :, 0] if ch == 1 else vals), bits, ct


# ---------------------------------------------------------------------------------------------------------------------
# Green and blue of an ORM texture at another size (P44, decisions 24 to 26): resampled inside each island
# ---------------------------------------------------------------------------------------------------------------------

SAMPLING = ('AUTOMATIC', 'NEAREST', 'BICUBIC')


def _cubic(t, a=-0.5):
    t = np.abs(t)
    return np.where(t <= 1, (a + 2) * t ** 3 - (a + 3) * t ** 2 + 1,
                    np.where(t < 2, a * t ** 3 - 5 * a * t ** 2 + 8 * a * t - 4 * a, 0.0))


def resample(src, src_label, dst_label, method='AUTOMATIC', rows=256):
    """src (Hs, Ws, C) floats, src_label (Hs, Ws) and dst_label (Ht, Wt) island labels (-1: no island). Returns
    (Ht, Wt, C). A destination pixel of an island reads only source pixels of the same island; one without an island
    reads every source pixel. AUTOMATIC: the mean of the covered source pixels when the destination is smaller by a
    whole factor, bilinear otherwise; NEAREST: the nearest pixel; BICUBIC: cubic convolution (a = -0.5), clamped."""
    Hs, Ws, C = src.shape
    Ht, Wt = dst_label.shape
    out = np.zeros((Ht, Wt, C))
    rx, ry = Ws / Wt, Hs / Ht
    box = method == 'AUTOMATIC' and rx >= 1 and ry >= 1 and Ws % Wt == 0 and Hs % Ht == 0
    for y0 in range(0, Ht, rows):
        y1 = min(Ht, y0 + rows)
        lab = dst_label[y0:y1]
        if box:
            fx, fy = Ws // Wt, Hs // Ht
            s = src[y0 * fy:y1 * fy].reshape(y1 - y0, fy, Wt, fx, C)
            sl = src_label[y0 * fy:y1 * fy].reshape(y1 - y0, fy, Wt, fx)
            same = (sl == lab[:, None, :, None]) | (lab[:, None, :, None] < 0)
            wsum = same.sum(axis=(1, 3))
            acc = (s * same[..., None]).sum(axis=(1, 3))
            plain = s.mean(axis=(1, 3))
            out[y0:y1] = np.where(wsum[..., None] > 0, acc / np.maximum(wsum, 1)[..., None], plain)
            continue
        jj, ii = np.mgrid[y0:y1, 0:Wt]
        x = (ii + 0.5) * rx - 0.5
        y = (jj + 0.5) * ry - 0.5
        if method == 'NEAREST':
            taps = [(np.floor(x + 0.5).astype(np.int64), np.floor(y + 0.5).astype(np.int64), None)]
            xa, ya = np.floor(x).astype(np.int64), np.floor(y).astype(np.int64)
            ax, ay = x - xa, y - ya
            near = [(xa, ya, (1 - ax) * (1 - ay)), (xa + 1, ya, ax * (1 - ay)), (xa, ya + 1, (1 - ax) * ay),
                    (xa + 1, ya + 1, ax * ay)]
            xs = np.clip(taps[0][0], 0, Ws - 1)
            ys = np.clip(taps[0][1], 0, Hs - 1)
            val = src[ys, xs]
            ok = (src_label[ys, xs] == lab) | (lab < 0)
            best_w = np.where(ok, 2.0, -1.0)
            for tx, ty, wgt in near:
                tx, ty = np.clip(tx, 0, Ws - 1), np.clip(ty, 0, Hs - 1)
                good = (src_label[ty, tx] == lab) & ~ok & (wgt > best_w)
                val = np.where(good[..., None], src[ty, tx], val)
                best_w = np.where(good, wgt, best_w)
            out[y0:y1] = val
            continue
        if method == 'BICUBIC':
            xa, ya = np.floor(x).astype(np.int64), np.floor(y).astype(np.int64)
            taps = []
            for dy in (-1, 0, 1, 2):
                for dx in (-1, 0, 1, 2):
                    taps.append((xa + dx, ya + dy, _cubic(x - (xa + dx)) * _cubic(y - (ya + dy))))
        else:
            xa, ya = np.floor(x).astype(np.int64), np.floor(y).astype(np.int64)
            ax, ay = x - xa, y - ya
            taps = [(xa, ya, (1 - ax) * (1 - ay)), (xa + 1, ya, ax * (1 - ay)), (xa, ya + 1, (1 - ax) * ay),
                    (xa + 1, ya + 1, ax * ay)]
        acc = np.zeros((y1 - y0, Wt, C))
        wsum = np.zeros((y1 - y0, Wt))
        acc_all = np.zeros((y1 - y0, Wt, C))
        wsum_all = np.zeros((y1 - y0, Wt))
        for tx, ty, wgt in taps:
            tx, ty = np.clip(tx, 0, Ws - 1), np.clip(ty, 0, Hs - 1)
            v = src[ty, tx]
            ok = (src_label[ty, tx] == lab) | (lab < 0)
            wv = np.where(ok, wgt, 0.0)
            acc += wv[..., None] * v
            wsum += wv
            acc_all += wgt[..., None] * v
            wsum_all += wgt
        nearest = src[np.clip(np.floor(y + 0.5).astype(np.int64), 0, Hs - 1),
                      np.clip(np.floor(x + 0.5).astype(np.int64), 0, Ws - 1)]
        res = np.where(np.abs(wsum)[..., None] > 1e-6, acc / np.where(np.abs(wsum) > 1e-6, wsum, 1.0)[..., None],
                       nearest)
        out[y0:y1] = np.clip(res, 0.0, 1.0)
    return out


def island_labels(uv_px_by_mesh, W, H, padding):
    """Island label per pixel of a W x H image for the triangles of several meshes [(uv_px (T,3,2), island (T,))],
    grown into the padding (8-neighbour steps, the nearest island wins). -1 where no island reaches."""
    owner = np.full((H, W), -1, dtype=np.int64)
    base = 0
    for uvpx, isl in uv_px_by_mesh:
        own, _ = rasterize_ids(uvpx, W, H)
        hit = own >= 0
        owner[hit] = base + isl[own[hit]]
        base += int(isl.max()) + 1 if len(isl) else 0
    grown, _ = dilate_ids(owner, int(padding))
    return grown
