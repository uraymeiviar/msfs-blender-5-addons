"""AO Bake core (auto-bake journal 20261112, Sessions 15 to 17): the master builder and the copy of the prototype, plain
numpy, so the second Blender that bakes (ao_bake_runner.py) loads this file by its path without the add-on.

The three prototype parts below are tests/bake_prototype/bake_geom.py, bake_unfold.py and bake_copy.py, copied with
their computation unchanged (only the module prefix `bg.` dropped); the prototype scripts stay as they are. After them
come the tool's own parts: the settings the prototype was measured with (Sessions 8, 11 and 14), the composition of a
master from its core and skirt bakes (step3_master.py), the master's files (the AO as lossless JPEG XL through
ao_bake_jxl.py, decision 37, or PNG), the evaluated triangles and their hash, 16-bit PNG files, and the resampling of
an ORM texture's green and blue inside islands (decisions 24 to 26).

Pixel convention (Blender's bake): an image of W x H pixels, UV (u, v) at pixel coordinates (u * W, v * H), pixel (i, j)
has its centre at (i + 0.5, j + 0.5); arrays are indexed [j, i] with row 0 at the bottom.
"""
import ctypes
import hashlib
import importlib.util
import json
import math
import os
import struct
import sys
import zlib

import numpy as np

_jxl_module = []


def jxl():
    """ao_bake_jxl (the JPEG XL wrapper), imported from the package or, when this file was loaded by its path (the
    second Blender), by its path too."""
    if not _jxl_module:
        try:
            from . import ao_bake_jxl as mod
        except ImportError:
            name = '_fss_ao_bake_jxl'
            mod = sys.modules.get(name)
            if mod is None:
                spec = importlib.util.spec_from_file_location(
                    name, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ao_bake_jxl.py'))
                mod = importlib.util.module_from_spec(spec)
                sys.modules[name] = mod
                spec.loader.exec_module(mod)
        _jxl_module.append(mod)
    return _jxl_module[0]


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


COPY_CHUNK = 1 << 19  # sub-samples per step of the copy (Session 23: bounds its temporaries, not the result)


def raster_window(uvpx, W, H, k=1, x0=0, y0=0, eps=1e-9):
    """rasterize_ids over only the triangles whose bounds reach the grid: the same owners (indices into uvpx, the last
    triangle still wins) and counts, without looping over every triangle of the mesh for a small window."""
    sel = tris_in_window(uvpx, x0, y0, W, H)
    if len(sel) == len(uvpx):
        return rasterize_ids(uvpx, W, H, k, x0, y0, eps)
    if not len(sel):
        return np.full((H * k, W * k), -1, dtype=np.int64), np.zeros((H * k, W * k), dtype=np.int32)
    own, cnt = rasterize_ids(uvpx[sel], W, H, k, x0, y0, eps)
    return np.where(own >= 0, sel[np.maximum(own, 0)], -1), cnt


def copy_context(pos, tris, uvpx, master, k, kmax=16):
    """What copy_master computes from the whole mesh (welded neighbours, normals, samples per triangle), so a copy in
    bands (Session 23) computes it once."""
    muv = master['muv']
    wt = weld_ids(pos)[tris]
    nb = _neighbours(wt)
    pp = pos[tris]
    tri_normal = np.cross(pp[:, 1] - pp[:, 0], pp[:, 2] - pp[:, 0])
    tri_normal /= np.maximum(np.linalg.norm(tri_normal, axis=1, keepdims=True), 1e-30)
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
    return dict(wt=wt, nb=nb, tri_normal=tri_normal, sig=sig, kt_raw=kt_raw, kt=kt)


def _chunks(n, per):
    """Index ranges of at most `per` items (at least one) over n items."""
    per = max(1, int(per))
    return [(a, min(n, a + per)) for a in range(0, n, per)]


def copy_master(pos, tris, uvpx, tisl, master, crop, k, padding=8, outside_mode='tri', kmax=16, surface_cos=None,
                same_face=False, ctx=None, chunk=COPY_CHUNK):
    """Returns (image (h,w) with -1 where nothing was written, info). ctx: copy_context (computed here when None);
    chunk: sub-samples per step (the result does not depend on it). master['image'], ['filled'] and ['face_map'] may be
    arrays or PagedArray views (read a[yi, xi] with index arrays)."""
    x0, y0, w, h = crop
    if ctx is None:
        ctx = copy_context(pos, tris, uvpx, master, k, kmax)
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
    wt = ctx['wt']
    nb = ctx['nb']
    face_map = master.get('face_map')
    tri_normal = ctx['tri_normal']

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

    owner_c, count_c = raster_window(uvpx, w, h, 1, x0, y0)
    out = np.full((h, w), -1.0)
    sig, kt_raw, kt = ctx['sig'], ctx['kt_raw'], ctx['kt']
    n_cl_in = 0
    jj, ii = np.nonzero(owner_c >= 0)
    lvl = kt[owner_c[jj, ii]]
    capped_px = int((kt_raw[owner_c[jj, ii]] > kmax).sum())
    def inside_step(L, sel):
        """The inside pixels jj[sel], ii[sel] of level L (a chunk of them)."""
        pj_, pi_ = jj[sel], ii[sel]
        # owners of the sub-samples on an L x L grid, only over the box of these pixels
        bx0, by0 = int(pi_.min()), int(pj_.min())
        bw, bh = int(pi_.max()) - bx0 + 1, int(pj_.max()) - by0 + 1
        owner_s, _ = raster_window(uvpx, bw, bh, int(L), x0 + bx0, y0 + by0)
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
        wv = wgt.reshape(n, L * L)
        vv = vals.reshape(n, L * L)
        sw = wv.sum(axis=1)
        cb = barycentric_many(np.stack([x0 + pi_ + 0.5, y0 + pj_ + 0.5], axis=1), uvpx[owner_c[pj_, pi_]])
        cv, _ = read(owner_c[pj_, pi_], cb)
        out[pj_, pi_] = np.where(sw > 0, (vv * wv).sum(axis=1) / np.maximum(sw, 1e-30), cv)
        return c_

    for L in np.unique(lvl):
        at_level = np.nonzero(lvl == L)[0]
        # in square blocks whose sub-sample raster (the block's area x L x L) is at most `chunk`: the pixels of one
        # level may lie scattered over the whole window, and the raster covers the box of the pixels it is given
        side = max(1, int(math.sqrt(chunk / (int(L) * int(L)))))
        key = (jj[at_level] // side) * (w // side + 1) + ii[at_level] // side
        order = np.argsort(key, kind='stable')
        cuts = np.flatnonzero(np.diff(key[order])) + 1
        for grp in np.split(at_level[order], cuts):
            n_cl_in += inside_step(int(L), grp)
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
            at_level = np.nonzero(plvl == L)[0]
            sub = (np.arange(L) + 0.5) / L
            sx, sy = np.meshgrid(sub, sub)
            sx, sy = sx.ravel(), sy.ravel()
            for c0, c1 in _chunks(len(at_level), chunk // (int(L) * int(L))):
                sel = at_level[c0:c1]
                ppx = (pi[sel][:, None] + x0 + sx[None, :]).ravel()
                ppy = (pj[sel][:, None] + y0 + sy[None, :]).ravel()
                bary = barycentric_many(np.stack([ppx, ppy], axis=1), np.repeat(tri_uv[sel], L * L, axis=0))
                # stay on the neighbour face: its nearest point (a thin neighbour extended further would reach other
                # faces)
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

SCHEMA = 3  # index.json and the master's files (3: the AO as <stem>.ao.jxl, decision 37; 2 and 1 (PNG) still read)
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


# The memory model of the bake in tiles and pages (Sessions 20 and 23): per tile pixel Cycles' bake data and the tile's
# float image and buffers (measured 240 to 280 bytes); per pixel of a band (one row of tiles, the master's width x the
# tile size) the band being baked, its uint16 values and baked flags: 3 bytes, 4 with the rows of the band above that
# wait for its halo and the strips being written. Nothing is held for the whole master (decision 33).
BYTES_PER_BAND_PX = 4.0
BYTES_PER_TILE_PX = 280.0
TILE_OVERHEAD = 0.25 * 2 ** 30  # bytes beyond the pixels (the scene's copies, Cycles' BVH, a composition strip)
COMPOSE_STRIP = 256  # rows of a band composed and written at a time
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


def estimate(W, H, size, in_use):
    """The peak working set of a bake in tiles of `size` px (Session 23's model): in_use (Blender, the scene, the
    layout) + the overhead + one tile + one band of the master's width."""
    return (in_use + TILE_OVERHEAD + BYTES_PER_TILE_PX * min(size, W) * min(size, H)
            + BYTES_PER_BAND_PX * W * min(size, H))


def choose_tile(W, H, budget, in_use):
    """The largest tile size whose bake fits the budget: the whole master when it is not larger than the largest of
    TILE_SIZES and fits, else the largest of TILE_SIZES that fits; in_use: the process's working set before the
    master (Blender, the scene). The tile size is also the band's height (decision 33). Returns (size, estimate of the
    peak in bytes, fits)."""
    longest = max(W, H)
    sizes = ([longest] if longest <= TILE_SIZES[0] else []) + [s for s in TILE_SIZES if s < longest]
    for s in sizes:
        est = estimate(W, H, s, in_use)
        if est <= budget:
            return int(s), est, True
    s = min(TILE_MIN, longest)
    return int(s), estimate(W, H, s, in_use), False


def tile_grid(W, H, size):
    """Tiles (x0, y0, w, h) of at most size x size px over a W x H master, row by row from the bottom left."""
    size = max(1, int(size))
    return [(x0, y0, min(size, W - x0), min(size, H - y0)) for y0 in range(0, H, size) for x0 in range(0, W, size)]


def tile_seed(base, i, n):
    """Cycles' seed of tile i of n: the base seed for a single tile (the untiled bake), else one per tile, since
    Cycles' noise depends on the pixel's position in the image and would repeat from tile to tile."""
    return int(base) if n == 1 else int(base) + 1009 * (int(i) + 1)


POSE_SEED = 7919  # decision 34: pose p of a mover adds p x this to both seeds (a prime: no tile and pose share one)


def pose_seed(base, p):
    """The base seed of pose p (0 for the first pose, so one pose bakes exactly as before)."""
    return int(base) + POSE_SEED * int(p)


# The preview of the master being baked, for the artist's Blender (decision 36): the runner writes it to the bake
# folder after each tile and composed strip, the panel reads it. PREVIEW_MAGIC, then W, H, a sequence number and 0 as
# little-endian uint32, then W x H uint8 grey, rows from the bottom (as Blender images). Its size does not depend on the
# master's: at most PREVIEW_FILE_MAX px on the long side.
PREVIEW_FILE = 'preview.bin'
PREVIEW_MAGIC = b'FSSAOPV1'
PREVIEW_FILE_MAX = 256
THUMB_EXT = '.ao.thumb'  # a master's own thumbnail (<stem>.ao.thumb, the preview file's format), shown for the object


def write_preview(folder, pv16, seq, name=PREVIEW_FILE):
    """pv16 (h, w) uint16, rows from the bottom; reduced to PREVIEW_FILE_MAX and written atomically. Returns False when
    the file is held by a reader (the next update writes it)."""
    f = max(1, -(-max(pv16.shape) // PREVIEW_FILE_MAX))
    small = pv16[::f, ::f]
    h, w = small.shape
    data = PREVIEW_MAGIC + struct.pack('<4I', w, h, int(seq), 0) + (small >> 8).astype(np.uint8).tobytes()
    path = os.path.join(folder, name)
    tmp = path + '.tmp'
    try:
        with open(tmp, 'wb') as fh:
            fh.write(data)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def read_preview(folder, name=PREVIEW_FILE):
    """(seq, (h, w) uint8 rows from the bottom) of the preview file (or a master's thumbnail), or None."""
    try:
        with open(os.path.join(folder, name), 'rb') as fh:
            data = fh.read()
    except OSError:
        return None
    if len(data) < 24 or data[:8] != PREVIEW_MAGIC:
        return None
    w, h, seq, _z = struct.unpack('<4I', data[8:24])
    if len(data) != 24 + w * h:
        return None
    return seq, np.frombuffer(data, np.uint8, w * h, 24).reshape(h, w)


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


def compose_block(m, M16e, baked_e, ex0, ey0, win):
    """The composition of a master (step3_master.py) for one window, after the tiles around it are baked.

    M16e (eh, ew) uint16 and baked_e (eh, ew) bool: the core and skirt values and the baked flags (core or skirt) over
    the window and its halo of FILL pixels (clamped to the master), whose bottom-left pixel is (ex0, ey0). Inside each
    island's rectangle, the pixels within FILL steps of a baked pixel of the same rectangle get that pixel's value; the
    face map holds the face per pixel (core faces, then skirt faces inside rectangles, grown FILL steps inside
    rectangles). With the halo the result equals the composition of the whole image at once (Session 20), so a master
    is composed a strip at a time (Session 23). Returns (counts, values (h, w) uint16, filled (h, w) bool, face map
    (h, w) int32) of the window."""
    x0, y0, w, h = win
    eh, ew = M16e.shape
    sub = (slice(y0 - ey0, y0 - ey0 + h), slice(x0 - ex0, x0 - ex0 + w))
    rid = rect_window(m['rects'], ex0, ey0, ew, eh)
    in_rect = rid >= 0
    baked = baked_e
    idx = np.where(baked, np.arange(eh * ew, dtype=np.int32).reshape(eh, ew), np.int32(-1))
    grown, _steps = dilate_ids(idx, FILL, mask_allowed=in_rect)
    del idx, _steps
    fm = (~baked) & (grown >= 0)
    same = np.zeros_like(fm)
    same[fm] = rid.ravel()[grown[fm]] == rid[fm]
    fm &= same
    del same
    fmi = fm[sub]
    vals = M16e[sub].copy()
    if fmi.any():
        vals[fmi] = M16e.ravel()[grown[sub][fmi]]  # sources are baked pixels
    del grown
    filled = baked[sub] | fmi
    counts = dict(nearest_fill_px=int(fmi.sum()), rect_px_unfilled=int((in_rect[sub] & ~filled).sum()),
                  rect_px=int(in_rect[sub].sum()))
    del fm
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
    return counts, vals, filled, fmap[sub].copy()


def compose_whole(m, M16, baked, window=2048):
    """The composition of a whole master held in memory (tests and small masters): (counts, values, filled, face map),
    window by window with compose_block."""
    H, W = M16.shape
    vals = np.zeros_like(M16)
    filled = np.zeros((H, W), bool)
    face = np.full((H, W), -1, np.int32)
    counts = {}
    for win in tile_grid(W, H, window):
        x0, y0, w, h = win
        ex0, ey0 = max(0, x0 - FILL), max(0, y0 - FILL)
        ex1, ey1 = min(W, x0 + w + FILL), min(H, y0 + h + FILL)
        c, v, f, fm = compose_block(m, M16[ey0:ey1, ex0:ex1], baked[ey0:ey1, ex0:ex1], ex0, ey0, win)
        vals[y0:y0 + h, x0:x0 + w] = v
        filled[y0:y0 + h, x0:x0 + w] = f
        face[y0:y0 + h, x0:x0 + w] = fm
        for k, n in c.items():
            counts[k] = counts.get(k, 0) + n
    return counts, vals, filled, face


COMPOSE_WINDOW = 2048  # a composition strip is composed in windows of at most this width


class Bands:
    """The bands (rows of tiles) of a master held in memory while it is baked (decision 33): the one being baked, the
    bottom rows of the one above it (its last strips, composed once the band below gives their halo) and the halo rows
    of the one above that. Each holds the uint16 values and the baked flags of its rows."""

    def __init__(self, W):
        self.W = W
        self.rows = {}  # band index: [y0, values (h, W) uint16, baked (h, W) bool], the bottom rows only once trimmed
        self.height = {}  # band index: its full height

    def add(self, kb, y0, h):
        self.rows[kb] = [y0, np.zeros((h, self.W), np.uint16), np.zeros((h, self.W), bool)]
        self.height[kb] = h
        return self.rows[kb]

    def trim(self, kb, n):
        """Keeps only the bottom n rows of band kb (those strips still to come will read)."""
        y0, v, b = self.rows[kb]
        if n < v.shape[0]:
            self.rows[kb] = [y0, v[:n].copy(), b[:n].copy()]

    def drop(self, kb):
        self.rows.pop(kb, None)
        self.height.pop(kb, None)

    def block(self, ey0, ey1, ex0, ex1):
        """(values, baked) of rows ey0..ey1 and columns ex0..ex1, from the bands that hold them."""
        vs, bs = [], []
        for y0, v, b in sorted(self.rows.values(), key=lambda r: r[0]):
            a0, a1 = max(ey0, y0), min(ey1, y0 + v.shape[0])
            if a1 > a0:
                vs.append(v[a0 - y0:a1 - y0, ex0:ex1])
                bs.append(b[a0 - y0:a1 - y0, ex0:ex1])
        v = vs[0] if len(vs) == 1 else np.concatenate(vs, axis=0)
        b = bs[0] if len(bs) == 1 else np.concatenate(bs, axis=0)
        if v.shape[0] != ey1 - ey0:
            raise RuntimeError(f'rows {ey0} to {ey1} not held ({v.shape[0]} rows)')
        return v, b


def compose_band(m, bands, kb, write_rows, counts, on_strip=None, ys1=None, stop=None):
    """Composes band kb a strip of COMPOSE_STRIP rows at a time from the top (or from row ys1, where an earlier call
    stopped); write_rows(values, codes) gets each strip's rows in file order (the top first), on_strip(y0, values) each
    strip as composed (the preview). stop: the first row of the band below when that band is not baked yet: the strips
    whose halo reaches below it wait. Returns the top of the strips not composed (the band's first row when done)."""
    W, H = m['W'], m['H']
    y0, v, _b = bands.rows[kb]
    yb1 = y0 + bands.height[kb]
    ys1 = yb1 if ys1 is None else ys1
    while ys1 > y0:
        ys0 = max(y0, ys1 - COMPOSE_STRIP)
        if stop is not None and ys0 - FILL < stop:
            break
        hs = ys1 - ys0
        vals = np.empty((hs, W), np.uint16)
        codes = np.empty((hs, W), np.int32)
        ey0, ey1 = max(0, ys0 - FILL), min(H, ys1 + FILL)
        for x0 in range(0, W, COMPOSE_WINDOW):
            w = min(COMPOSE_WINDOW, W - x0)
            ex0, ex1 = max(0, x0 - FILL), min(W, x0 + w + FILL)
            Me, Be = bands.block(ey0, ey1, ex0, ex1)
            c, wv, wf, wm = compose_block(m, Me, Be, ex0, ey0, (x0, ys0, w, hs))
            vals[:, x0:x0 + w] = wv
            codes[:, x0:x0 + w] = map_code(wm, wf)
            for k, n in c.items():
                counts[k] = counts.get(k, 0) + n
        write_rows(vals[::-1], codes[::-1])
        if on_strip is not None:
            on_strip(ys0, vals)
        ys1 = ys0
    return ys1


def bake_paged(m, tile, bake_tile, write_rows, counts, on_strip=None):
    """A master baked and composed band by band (decision 33): the bands from the top (the files are written from the
    top), each band's tiles from the left. bake_tile(i, (x0, y0, w, h), values, baked) bakes tile i of tile_grid (its
    place gives its seed) into the band's views of that tile and is a generator (the runner yields between tiles).
    Once a band is baked, the last strips of the band above it (they needed its top rows) are composed and written,
    then this band's strips that do not reach the band below; only the rows the next strips still read are kept. So
    one band and a strip are held, whatever the master's height. Yields after each tile."""
    W, H = m['W'], m['H']
    tiles = tile_grid(W, H, tile)
    ntx, nb = -(-W // tile), -(-H // tile)
    bands = Bands(W)
    rest = {}  # band index: the top of its strips not composed yet
    for kb in range(nb - 1, -1, -1):
        yb0 = kb * tile
        _y0, band_v, band_b = bands.add(kb, yb0, min(tile, H - yb0))
        for tx in range(ntx):
            i = kb * ntx + tx
            x0, y0, w, h = tiles[i]
            yield from bake_tile(i, tiles[i], band_v[:, x0:x0 + w], band_b[:, x0:x0 + w])
        del band_v, band_b
        if kb + 1 in rest:
            compose_band(m, bands, kb + 1, write_rows, counts, on_strip, ys1=rest.pop(kb + 1))
            bands.trim(kb + 1, FILL)  # the halo of this band's top strip
        bands.drop(kb + 2)
        ys1 = compose_band(m, bands, kb, write_rows, counts, on_strip, stop=yb0 if kb else None)
        if ys1 > yb0:
            rest[kb] = ys1
            bands.trim(kb, ys1 + FILL - yb0)  # the rows the band's last strips read

# ---------------------------------------------------------------------------------------------------------------------
# A master's files (decisions 18, 33 and 37): <stem>.ao.jxl (or .ao.png), <stem>.ao.map, <stem>.ao.npz
# ---------------------------------------------------------------------------------------------------------------------
#
# <stem>.ao.jxl: the AO, 16-bit grey, lossless JPEG XL (decision 37, schema 3), encoded by ao_bake_jxl from the rows
#   handed from the top as a band is composed (through a raw scratch file, <stem>.ao.jxl.tmp.raw, deleted afterwards).
#   When the library cannot be loaded, <stem>.ao.png instead (decision 18, as schemas 1 and 2 wrote it), written row
#   by row from the top. A master has one of the two; a new bake removes the other.
# <stem>.ao.map: the per-pixel data Apply reads besides the AO (Session 23; schema 1 kept them as `filled` and
#   `face_map` in the .npz): MAP_MAGIC, then the version, W and H as little-endian uint32, then one zlib stream of the
#   rows from the top, each W little-endian int32 codes: (face + 1) * 2 + filled, face -1 for none.
# <stem>.ao.npz: the layout, its size set by the triangles and islands, not by the pixels: muv, island, density, W, H,
#   rects, gutter, degenerate, tri_src, meta.

MAP_MAGIC = b'FSSAOMAP'
MAP_VERSION = 1


def image_paths(folder, stem):
    """(jxl, png): the two names a master's AO image can have."""
    base = os.path.join(folder, stem)
    return base + '.ao.jxl', base + '.ao.png'


def master_paths(folder, stem):
    """(image, map, npz) of a master; image is its .ao.jxl, or its .ao.png when only that exists (a master of 0.55, or
    one baked without the JPEG XL library)."""
    jx, pn = image_paths(folder, stem)
    base = os.path.join(folder, stem)
    image = pn if (os.path.isfile(pn) and not os.path.isfile(jx)) else jx
    return image, base + '.ao.map', base + '.ao.npz'


def all_master_files(folder, stem):
    """Every file a master can have (for a rename)."""
    base = os.path.join(folder, stem)
    return [base + ext for ext in ('.ao.jxl', '.ao.png', '.ao.map', '.ao.npz', THUMB_EXT)]


def read_image(path):
    """A master's AO image whole as (H, W) uint16, row 0 = bottom (tests and small masters)."""
    if path.endswith('.jxl'):
        return jxl().read_whole(path)[::-1]
    img = read_png(path)[0]
    return img[:, :, 0] if img.ndim == 3 else img


def map_code(face, filled):
    """The .ao.map code of each pixel: (face + 1) * 2 + filled."""
    return ((np.asarray(face, dtype=np.int64) + 1) * 2 + np.asarray(filled, dtype=np.int64)).astype(np.int32)


def code_filled(code):
    return (np.asarray(code) & 1) != 0


def code_face(code):
    return (np.asarray(code, dtype=np.int32) >> 1) - 1


class MapRowWriter:
    """<stem>.ao.map written row by row from the top (blocks of rows in file order)."""

    def __init__(self, path, W, H, level=1):
        self.path, self.W, self.H, self.rows = path, int(W), int(H), 0
        self.f = open(path, 'wb')
        self.f.write(MAP_MAGIC + struct.pack('<IIII', MAP_VERSION, self.W, self.H, 0))
        self.comp = zlib.compressobj(level)

    def write(self, block):
        block = np.ascontiguousarray(block, dtype='<i4')
        self.rows += block.shape[0]
        data = self.comp.compress(block.tobytes())
        if data:
            self.f.write(data)

    def close(self):
        if self.rows != self.H:
            raise ValueError(f'{self.path}: {self.rows} of {self.H} rows written')
        self.f.write(self.comp.flush())
        self.f.close()

    def abort(self):
        self.f.close()
        try:
            os.remove(self.path)
        except OSError:
            pass


def map_rows(path, rows=256):
    """(W, H, generator of int32 blocks (n, W) of the .ao.map's rows, from the top)."""
    f = open(path, 'rb')
    head = f.read(len(MAP_MAGIC) + 16)
    if head[:len(MAP_MAGIC)] != MAP_MAGIC:
        f.close()
        raise ValueError(f'{path}: not an AO map')
    _v, W, H, _r = struct.unpack('<IIII', head[len(MAP_MAGIC):])
    rowlen = 4 * W

    def gen():
        d = zlib.decompressobj()
        pending = bytearray()
        done = 0
        try:
            while True:
                data = f.read(1 << 22)
                if not data:
                    break
                buf = d.decompress(data, 1 << 24)
                while True:
                    pending.extend(buf)
                    n = len(pending) // rowlen
                    while n:
                        k = min(n, rows, H - done)
                        if k <= 0:
                            break
                        yield np.frombuffer(bytes(pending[:k * rowlen]), dtype='<i4').reshape(k, W).astype(np.int32)
                        del pending[:k * rowlen]
                        done += k
                        n -= k
                    if not d.unconsumed_tail:
                        break
                    buf = d.decompress(d.unconsumed_tail, 1 << 24)
            pending.extend(d.flush())
            while done < H and len(pending) >= rowlen:
                k = min(len(pending) // rowlen, rows, H - done)
                yield np.frombuffer(bytes(pending[:k * rowlen]), dtype='<i4').reshape(k, W).astype(np.int32)
                del pending[:k * rowlen]
                done += k
            if done != H:
                raise ValueError(f'{path}: {done} of {H} rows')
        finally:
            f.close()
    return W, H, gen()


def save_master(folder, stem, M16, m, filled, face_map, tri_src, meta):
    """A whole master held in memory (tests and small masters) as its three files; the runner writes them band by band
    instead (MasterWriter)."""
    H, W = M16.shape
    w = MasterWriter(folder, stem, W, H)
    try:
        for top in range(0, H, 256):
            bot = min(H, top + 256)
            w.write_rows(M16[H - bot:H - top][::-1], map_code(face_map, filled)[H - bot:H - top][::-1])
        return w.finish(m, tri_src, meta)
    except BaseException:
        w.abort()
        raise


class MasterWriter:
    """The files of one master, written to temporary names row by row from the top (the AO and the map), then the
    layout; finish() replaces the old files (and removes the AO image of the other format), abort() removes the
    temporary ones (a cancelled bake keeps the old master). The AO is JPEG XL when the library loads (decision 37),
    else PNG (`format`, and `fallback` says why)."""

    def __init__(self, folder, stem, W, H, threads=None):
        jx, pn = image_paths(folder, stem)
        base = os.path.join(folder, stem)
        lib = jxl()
        self.format = 'jxl' if lib.available() else 'png'
        self.fallback = None if self.format == 'jxl' else lib.error()
        self.image, self.other = (jx, pn) if self.format == 'jxl' else (pn, jx)
        self.paths = (self.image, base + '.ao.map', base + '.ao.npz')
        self.stats = {}
        if self.format == 'jxl':
            self.img = lib.Writer(self.image + '.tmp', W, H, threads=threads or lib.THREADS)
        else:
            self.img = PngRowWriter(self.image + '.tmp', W, H, bits=16, channels=1)
        try:
            self.map = MapRowWriter(self.paths[1] + '.tmp', W, H)
        except BaseException:
            self.img.abort()
            raise

    def write_rows(self, values, codes):
        """values (n, W) uint16 and codes (n, W) int32: rows in file order (the top first)."""
        self.img.write(values)
        self.map.write(codes)

    def finish(self, m, tri_src, meta):
        image, mp, npz = self.paths
        self.img.close()
        self.stats = dict(format=self.format, **getattr(self.img, 'stats', {}))
        self.map.close()
        with open(npz + '.tmp', 'wb') as f:
            np.savez_compressed(f, muv=m['muv'], island=m['island'], density=m['density'], W=m['W'], H=m['H'],
                                rects=m['rects'], gutter=m['gutter'], degenerate=m['degenerate'],
                                tri_src=np.asarray(tri_src, dtype=np.int64), meta=json.dumps(meta))
        os.replace(image + '.tmp', image)
        os.replace(mp + '.tmp', mp)
        os.replace(npz + '.tmp', npz)
        try:
            os.remove(self.other)  # a re-bake replaces a master of the other format (a 0.55 PNG by a JPEG XL)
        except OSError:
            pass
        self.stats['bytes'] = os.path.getsize(image)
        return image, npz

    def abort(self):
        self.img.abort()
        self.map.abort()
        try:
            os.remove(self.paths[2] + '.tmp')
        except OSError:
            pass


def _layout(z):
    return dict(muv=z['muv'], rects=z['rects'], island=z['island'], density=float(z['density']), tri_src=z['tri_src'],
                W=int(z['W']), H=int(z['H']), meta=json.loads(str(z['meta'])))


def has_maps_in_npz(npz):
    """True for a master of schema 1 (filled and face map in the .npz, no .ao.map)."""
    try:
        with np.load(npz) as z:
            return 'filled' in z.files
    except (OSError, ValueError):
        return False


def load_master(folder, stem):
    """The whole master in memory as copy_master reads it (the image as uint16, 0..65535; filled, the face map; the
    island rectangles instead of a per-pixel map), or None when a file is missing. For tests and small masters: Apply
    reads a master paged (open_master)."""
    png, mp, npz = master_paths(folder, stem)
    if not (os.path.isfile(png) and os.path.isfile(npz)):
        return None
    with np.load(npz) as z:
        out = _layout(z)
        old = 'filled' in z.files
        if old:
            out.update(filled=z['filled'], face_map=z['face_map'])
    img = read_image(png)
    H, W = img.shape
    out.update(image=img, W=W, H=H)
    if not old:
        if not os.path.isfile(mp):
            return None
        mW, mH, rows = map_rows(mp)
        code = np.empty((mH, mW), np.int32)
        y = 0
        for block in rows:
            n = block.shape[0]
            code[mH - y - n:mH - y] = block[::-1]
            y += n
        out.update(filled=code_filled(code), face_map=code_face(code))
    return out


# ---------------------------------------------------------------------------------------------------------------------
# A master paged for Apply (decision 33): decoded once into tiled scratch files, read through a cache of tiles
# ---------------------------------------------------------------------------------------------------------------------

PAGE_TILE = 256  # px, a power of two
PAGE_CACHE_BYTES = 384 * 2 ** 20  # the cache of one master's tiles: a third for the AO, two thirds for the map codes


class _TiledWriter:
    """A tiled scratch file of an (H, W) array, filled with rows in file order (the top first)."""

    def __init__(self, path, H, W, dtype, T=PAGE_TILE):
        self.path, self.H, self.W, self.T = path, H, W, T
        self.dtype = np.dtype(dtype)
        self.ntx, self.nty = -(-W // T), -(-H // T)
        self.buf = np.zeros((T, self.ntx * T), self.dtype)
        self.ty = None
        self.r = 0  # file rows received
        self.f = open(path, 'wb')

    def _flush(self):
        if self.ty is None:
            return
        T = self.T
        tiles = np.ascontiguousarray(self.buf.reshape(T, self.ntx, T).transpose(1, 0, 2))
        self.f.seek(self.ty * self.ntx * T * T * self.dtype.itemsize)
        self.f.write(tiles.tobytes())
        self.buf.fill(0)

    def write(self, block):
        block = np.asarray(block)
        n = block.shape[0]
        j = self.H - 1 - (self.r + np.arange(n))  # array rows, descending
        ty = j // self.T
        for t in np.unique(ty)[::-1]:
            sel = ty == t
            if self.ty != t:
                self._flush()
                self.ty = int(t)
            self.buf[j[sel] - t * self.T, :self.W] = block[sel]
        self.r += n

    def close(self):
        self._flush()
        self.f.truncate(self.ntx * self.nty * self.T * self.T * self.dtype.itemsize)
        self.f.close()


class _TiledSink:
    """The same tiled scratch file as _TiledWriter (uint16), filled from pieces of rows in any order (the JPEG XL
    decoder hands them group by group, from several threads, one call at a time): put(x, y, n, address) with y from
    the top. A row of tiles is buffered until every pixel of it came, then written and dropped; the decoder works on
    groups of 2048 px at most, so a few rows of tiles are open at a time, never the whole image."""

    def __init__(self, path, H, W, T=PAGE_TILE):
        self.path, self.H, self.W, self.T = path, int(H), int(W), T
        self.ntx, self.nty = -(-self.W // T), -(-self.H // T)
        self.open = {}  # tile row: [buffer (T, ntx * T), address, pixels received]
        self.most_open = 0
        self.f = open(path, 'wb')
        self.f.truncate(self.ntx * self.nty * T * T * 2)

    def put(self, x, y, n, address):
        j = self.H - 1 - y
        ty = j // self.T
        e = self.open.get(ty)
        if e is None:
            buf = np.zeros((self.T, self.ntx * self.T), np.uint16)
            e = self.open[ty] = [buf, buf.ctypes.data, 0]
            self.most_open = max(self.most_open, len(self.open))
        ctypes.memmove(e[1] + 2 * ((j - ty * self.T) * self.ntx * self.T + x), address, 2 * n)
        e[2] += n
        if e[2] >= self.W * min(self.T, self.H - ty * self.T):
            T = self.T
            tiles = np.ascontiguousarray(e[0].reshape(T, self.ntx, T).transpose(1, 0, 2))
            self.f.seek(ty * self.ntx * T * T * 2)
            self.f.write(tiles.tobytes())
            del self.open[ty]

    def close(self):
        self.f.close()
        if self.open:
            raise ValueError(f'{self.path}: {len(self.open)} rows of tiles incomplete')


class PagedArray:
    """An (H, W) array in a tiled scratch file, read as a[yi, xi] with index arrays through a cache of at most
    cache_bytes of tiles (least recently used tiles dropped first), so reading it never holds the whole array."""

    def __init__(self, path, H, W, dtype, cache_bytes, T=PAGE_TILE):
        self.path, self.shape, self.T = path, (int(H), int(W)), T
        self.dtype = np.dtype(dtype)
        self.sh = T.bit_length() - 1
        self.mask = T - 1
        self.ntx, nty = -(-W // T), -(-H // T)
        self.cap = int(max(4, cache_bytes // (T * T * self.dtype.itemsize)))
        self.cache = np.empty((self.cap, T * T), self.dtype)
        self.slot_of = np.full(self.ntx * nty, -1, np.int64)
        self.tile_in = np.full(self.cap, -1, np.int64)
        self.used = np.zeros(self.cap, np.int64)
        self.clock = 0
        self.loads = 0
        self.f = open(path, 'rb')

    def view(self, decode, dtype):
        return _PagedView(self, decode, dtype)

    def __getitem__(self, key):
        yi, xi = key
        yi, xi = np.broadcast_arrays(np.asarray(yi, np.int64), np.asarray(xi, np.int64))
        shape = yi.shape
        yi, xi = yi.ravel(), xi.ravel()
        t = (yi >> self.sh) * self.ntx + (xi >> self.sh)
        local = ((yi & self.mask) << self.sh) | (xi & self.mask)
        return self._gather(t, local).reshape(shape)

    def _gather(self, t, local):
        if not len(t):
            return np.zeros(0, self.dtype)
        need_mask = np.zeros(len(self.slot_of), bool)
        need_mask[t] = True
        need = np.flatnonzero(need_mask)
        if len(need) > self.cap:
            half = len(t) // 2
            return np.concatenate([self._gather(t[:half], local[:half]), self._gather(t[half:], local[half:])])
        self._ensure(need)
        return self.cache.reshape(-1)[self.slot_of[t] * (self.T * self.T) + local]

    def _ensure(self, need):
        self.clock += 1
        slots = self.slot_of[need]
        missing = need[slots < 0]
        if len(missing):
            busy = np.zeros(self.cap, bool)
            busy[slots[slots >= 0]] = True
            free = np.flatnonzero(~busy)
            free = free[np.argsort(self.used[free], kind='stable')][:len(missing)]
            size = self.T * self.T * self.dtype.itemsize
            for tid, s in zip(missing.tolist(), free.tolist()):
                old = self.tile_in[s]
                if old >= 0:
                    self.slot_of[old] = -1
                self.f.seek(tid * size)
                self.f.readinto(memoryview(self.cache[s]).cast('B'))
                self.tile_in[s] = tid
                self.slot_of[tid] = s
                self.loads += 1
        self.used[self.slot_of[need]] = self.clock

    def close(self):
        self.f.close()


class _PagedView:
    """A decoded view of a PagedArray (the map codes as filled or as faces)."""

    def __init__(self, base, decode, dtype):
        self.base, self.decode, self.dtype, self.shape = base, decode, np.dtype(dtype), base.shape

    def __getitem__(self, key):
        return self.decode(self.base[key])


def open_master(folder, stem, cache_bytes=PAGE_CACHE_BYTES):
    """The master paged (decision 33), or None when a file is missing: the AO image (JPEG XL or PNG) and the map
    decoded once into two tiled scratch files in the bake folder (<stem>.ao.page and <stem>.ao.mappage), read through
    a cache of tiles; close() closes and deletes them. A master of schema 1 (filled and the face map in the .npz) is
    loaded whole (load_master)."""
    png, mp, npz = master_paths(folder, stem)
    if not (os.path.isfile(png) and os.path.isfile(npz)):
        return None
    if has_maps_in_npz(npz):
        out = load_master(folder, stem)
        out['close'] = lambda: None
        return out
    if not os.path.isfile(mp):
        return None
    with np.load(npz) as z:
        out = _layout(z)
    W, H = out['W'], out['H']
    base = os.path.join(folder, stem)
    page_img, page_map = base + '.ao.page', base + '.ao.mappage'
    made = []
    try:
        if png.endswith('.jxl'):
            lib = jxl()
            if not lib.available():
                raise lib.JxlError(f'{png}: the JPEG XL library is not loaded ({lib.error()})')
            iw, ih = lib.info(png)
            if (iw, ih) != (W, H):
                raise ValueError(f'{png}: {iw} x {ih} px, the layout says {W} x {H}')
            sink = _TiledSink(page_img, H, W)
            made.append(page_img)
            try:
                lib.decode_rows(png, sink.put, threads=lib.DECODE_THREADS)
            except BaseException:
                sink.f.close()
                raise
            sink.close()
            out['decode_open_tile_rows'] = sink.most_open
        else:
            reader = PngRows(png)
            if (reader.w, reader.h) != (W, H):
                reader.close()
                raise ValueError(f'{png}: {reader.w} x {reader.h} px, the layout says {W} x {H}')
            tw = _TiledWriter(page_img, H, W, np.uint16)
            made.append(page_img)
            for block in reader:
                tw.write(block[:, :, 0])
            tw.close()
        mW, mH, rows = map_rows(mp)
        if (mW, mH) != (W, H):
            raise ValueError(f'{mp}: {mW} x {mH} px, the layout says {W} x {H}')
        tw = _TiledWriter(page_map, H, W, np.int32)
        made.append(page_map)
        for block in rows:
            tw.write(block)
        tw.close()
        img = PagedArray(page_img, H, W, np.uint16, cache_bytes // 3)
        code = PagedArray(page_map, H, W, np.int32, cache_bytes - cache_bytes // 3)
    except BaseException:
        for p in made:
            try:
                os.remove(p)
            except OSError:
                pass
        raise

    def close():
        for arr, p in ((img, page_img), (code, page_map)):
            arr.close()
            try:
                os.remove(p)
            except OSError:
                pass
    out.update(image=img, filled=code.view(code_filled, bool), face_map=code.view(code_face, np.int32),
               close=close, pages=(img, code))
    return out


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


class PngRowWriter:
    """A PNG written row by row: blocks of rows in file order (the top first), (n, w) or (n, w, C) integers in the
    file's depth. Filter 0, zlib level 6, one IDAT chunk per compressed block of `rows` rows, so the file is the same
    whatever the blocks handed in (Session 23: the same bytes as Session 20's write_png_int)."""

    def __init__(self, path, w, h, bits=16, channels=1, rows=256):
        self.path, self.w, self.h, self.bits, self.ch, self.rows = path, int(w), int(h), bits, int(channels), rows
        self.dtype = '>u2' if bits == 16 else np.uint8
        self.pending = []
        self.n_pending = 0
        self.done = 0
        self.comp = zlib.compressobj(6)
        self.f = open(path, 'wb')
        self.f.write(b'\x89PNG\r\n\x1a\n')
        self.f.write(_png_chunk(b'IHDR', struct.pack('>IIBBBBB', self.w, self.h, bits, COLOUR_TYPE[self.ch], 0, 0, 0)))

    def write(self, block):
        block = np.asarray(block)
        if not block.shape[0]:
            return
        self.pending.append(block)
        self.n_pending += block.shape[0]
        while self.n_pending >= self.rows:
            self._emit(self.rows)

    def _emit(self, n):
        rows = self.pending[0] if len(self.pending) == 1 else np.concatenate(self.pending, axis=0)
        take, rest = rows[:n], rows[n:]
        self.pending = [rest] if rest.shape[0] else []
        self.n_pending = rest.shape[0]
        block = np.ascontiguousarray(take.astype(self.dtype)).reshape(n, -1)
        raw = np.zeros((n, block.shape[1] * block.itemsize + 1), dtype=np.uint8)
        raw[:, 1:] = block.view(np.uint8).reshape(n, -1)
        data = self.comp.compress(raw.tobytes())
        if data:
            self.f.write(_png_chunk(b'IDAT', data))
        self.done += n

    def close(self):
        if self.n_pending:
            self._emit(self.n_pending)
        if self.done != self.h:
            self.f.close()
            raise ValueError(f'{self.path}: {self.done} of {self.h} rows written')
        self.f.write(_png_chunk(b'IDAT', self.comp.flush()))
        self.f.write(_png_chunk(b'IEND', b''))
        self.f.close()

    def abort(self):
        self.f.close()
        try:
            os.remove(self.path)
        except OSError:
            pass


def write_png_int(path, q, bits=16, rows=256):
    """q: (H, W) or (H, W, C) integers in the file's depth, row 0 = bottom. Filter 0, zlib level 6. Written row by
    row (`rows` at a time, one IDAT chunk per compressed block), so no copy of the whole image is made."""
    q = np.asarray(q)
    h, w = q.shape[:2]
    ch = 1 if q.ndim == 2 else q.shape[2]
    writer = PngRowWriter(path, w, h, bits, ch, rows)
    try:
        for top in range(0, h, rows):
            bot = min(h, top + rows)
            writer.write(q[h - bot:h - top][::-1])
        writer.close()
    except BaseException:
        writer.abort()
        raise


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


class PngRows:
    """A PNG read row by row: iterating gives blocks (n, w, C) uint16 in the file's depth, in file order (the top
    first). Grey, grey + alpha, RGB and RGBA at 8 or 16 bits, filters None, Sub and Up; PngNotDecoded otherwise. The
    file is read a chunk at a time (Session 23), never whole."""

    def __init__(self, path, rows=256):
        self.path, self.rows = path, rows
        self.f = open(path, 'rb')
        try:
            if self.f.read(8) != b'\x89PNG\r\n\x1a\n':
                raise PngNotDecoded('not a PNG')
            tag, chunk = self._chunk()
            if tag != b'IHDR':
                raise PngNotDecoded('no IHDR')
            self.w, self.h, self.bits, self.ct, _c, _f, il = struct.unpack('>IIBBBBB', chunk[:13])
            if self.ct not in CHANNELS or self.bits not in (8, 16) or il:
                raise PngNotDecoded(f'colour type {self.ct}, {self.bits} bits, interlace {il}')
        except BaseException:
            self.f.close()
            raise
        self.ch = CHANNELS[self.ct]

    def _chunk(self):
        head = self.f.read(8)
        if len(head) < 8:
            return None, b''
        n = struct.unpack('>I', head[:4])[0]
        data = self.f.read(n)
        self.f.read(4)
        return head[4:8], data

    def close(self):
        self.f.close()

    def __iter__(self):
        w, h, bits, ch = self.w, self.h, self.bits, self.ch
        bpp = ch * bits // 8
        rowlen = 1 + w * bpp
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
            state['y'] += n
            if bits == 16:
                return rows.view('>u2').reshape(n, w, ch).astype(np.uint16)
            return rows.reshape(n, w, ch).astype(np.uint16)

        def ready():
            while True:
                n = min(len(pending) // rowlen, h - state['y'], self.rows)
                if n <= 0:
                    return
                yield rows_out(n)

        try:
            while True:
                tag, chunk = self._chunk()
                if tag is None or tag == b'IEND':
                    break
                if tag != b'IDAT':
                    continue
                data = d.decompress(chunk, 1 << 24)
                while True:
                    pending.extend(data)
                    yield from ready()
                    if not d.unconsumed_tail:
                        break
                    data = d.decompress(d.unconsumed_tail, 1 << 24)
            pending.extend(d.flush())
            yield from ready()
            if state['y'] != h:
                raise PngNotDecoded(f'{state["y"]} of {h} rows decoded')
        finally:
            self.f.close()


def read_png(path):
    """(values (H, W) or (H, W, C) uint16 in the file's depth, row 0 = bottom, bits, colour type). Grey, grey + alpha,
    RGB and RGBA at 8 or 16 bits, filters None, Sub and Up; raises PngNotDecoded otherwise."""
    reader = PngRows(path)
    h, ch = reader.h, reader.ch
    vals = np.empty((h, reader.w, ch), dtype=np.uint16)
    y = 0
    for block in reader:
        n = block.shape[0]
        vals[h - y - n:h - y] = block[::-1]
        y += n
    return (vals[:, :, 0] if ch == 1 else vals), reader.bits, reader.ct


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
