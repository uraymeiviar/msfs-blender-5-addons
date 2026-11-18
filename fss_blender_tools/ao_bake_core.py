"""AO Bake core (auto-bake journal 20261112, Sessions 15 to 17): the master builder and the copy of the prototype, plain
numpy, so the second Blender that bakes (ao_bake_runner.py) loads this file by its path without the add-on.

The three prototype parts below are tests/bake_prototype/bake_geom.py, bake_unfold.py and bake_copy.py, copied with
their computation unchanged (only the module prefix `bg.` dropped); the prototype scripts stay as they are. After them
come the tool's own parts: the settings the prototype was measured with (Sessions 8, 11 and 14), the composition of a
master from its core and skirt bakes (step3_master.py), the master's files (the AO as lossless JPEG XL through
ao_bake_jxl.py, decision 37), the evaluated triangles and their hash, 16-bit PNG files, and the resampling of an ORM
texture's green and blue inside islands (decisions 24 to 26).

Apply-native-copy decision 6: the per-pixel work runs in the C++ DLL (ao_bake_copy, native_copy()), which is required
with libjxl; the functions below that it does (rasterize_ids, raster_window, dilate_ids, uv_islands, island_labels,
copy_master's copy and Soften, compose_block, the .ao.map and PNG writers, read_png, open_master) call it and keep their
names and signatures; there is no Python version of them.

Pixel convention (Blender's bake): an image of W x H pixels, UV (u, v) at pixel coordinates (u * W, v * H), pixel (i, j)
has its centre at (i + 0.5, j + 0.5); arrays are indexed [j, i] with row 0 at the bottom.
"""
import hashlib
import importlib.util
import json
import math
import os
import struct
import sys
import time
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


_copy_module = []


def native_copy():
    """ao_bake_copy (Apply's copy in C++, apply-native-copy journal), imported as jxl() imports its module."""
    if not _copy_module:
        try:
            from . import ao_bake_copy as mod
        except ImportError:
            name = '_fss_ao_bake_copy'
            mod = sys.modules.get(name)
            if mod is None:
                spec = importlib.util.spec_from_file_location(
                    name, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ao_bake_copy.py'))
                mod = importlib.util.module_from_spec(spec)
                sys.modules[name] = mod
                spec.loader.exec_module(mod)
        _copy_module.append(mod)
    return _copy_module[0]


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


def uv_islands(wtris, uv, tol=1e-6, threads=None):
    """Island label (int64) per triangle: triangles sharing an edge with equal UVs (within tol) at both ends are in one
    island. fss_ao_copy_uv_islands on `threads` threads; wtris (T,3) welded vertex ids, uv (T,3,2) (as float64)."""
    return native_copy().uv_islands(wtris, uv, tol, threads)


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


def rasterize_ids(uv_px, W, H, k=1, x0=0, y0=0, eps=1e-9, threads=None):
    """Owner triangle of each sample point. Samples: k x k per pixel at (i + (a + 0.5) / k, ...).

    Grid covers pixels x0..x0+W-1, y0..y0+H-1 (in the uv_px frame). Returns (owner (H*k, W*k) int64, -1 = none;
    count (H*k, W*k) int32 of triangles covering the sample). Last triangle wins; a sample is inside a triangle when
    each of its barycentric coordinates is at least -eps. fss_ao_copy_raster_ids on `threads` threads (uv_px as
    float64 (N,3,2))."""
    return native_copy().raster_ids(uv_px, W, H, k, x0, y0, eps, select=False, threads=threads)


def dilate_ids(owner, iterations, mask_allowed=None, threads=None):
    """Grow owner ids (>= 0) into -1 pixels by 8-neighbour steps (a pixel takes the owner of its first neighbour
    with one, in the order (0,1), (0,-1), (1,0), (-1,0), then the diagonals, as (dy, dx)), only into pixels of
    mask_allowed when given.
    Returns (owner in owner's dtype, steps int64: the ring index, 0 for the seeds, -1 where nothing reached).
    fss_ao_copy_dilate on `threads` threads."""
    own, steps = native_copy().dilate(owner, iterations, mask_allowed, threads)
    return own.astype(np.asarray(owner).dtype, copy=False), steps


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


def raster_window(uvpx, W, H, k=1, x0=0, y0=0, eps=1e-9, threads=None):
    """rasterize_ids over only the triangles whose bounds reach the grid (tris_in_window): the same owners (indices
    into uvpx, the last triangle still wins) and counts, without looping over every triangle of the mesh for a small
    window. fss_ao_copy_raster_ids on `threads` threads."""
    return native_copy().raster_ids(uvpx, W, H, k, x0, y0, eps, select=True, threads=threads)


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


SOFT_SMOOTH_COS = math.cos(math.radians(1.0))  # corner normals this close across an edge: the edge is shaded smooth


def soften_context(pos, tris, uvpx, ctx, width, use=None, sharp_deg=None, max_samples=512, cn=None):
    """The folds for Apply's edge softening (auto-bake journal, decisions 46 and 58), computed once per master.

    A fold: two faces (welded neighbours) whose normals differ by more than sharp_deg (the copy's surface angle). Only
    folds shaded smooth are softened (cn, the corner normals (T,3,3) in tris' order: the same normal on both sides at
    both ends); a hard-shaded edge (split normals, marked sharp) is left as baked. None: every fold counts as smooth.
    Convex: each face's far corner lies behind the other face (a lip, a rim); else concave (an inside corner). Per
    triangle of `use` (the texture set's), the width it softens over: `width` (m), at least one target texel of that
    triangle; and the edges that can lie within it (the candidates). Returns None without such edges."""
    from mathutils import Vector
    from mathutils.kdtree import KDTree
    sharp_cos = math.cos(math.radians(SURFACE_DEG if sharp_deg is None else sharp_deg))
    wt, tn = ctx['wt'], ctx['tri_normal']
    T = len(tris)
    use = np.ones(T, bool) if use is None else np.asarray(use, bool)
    if cn is not None:
        cn = np.asarray(cn, np.float64)
        cn = cn / np.maximum(np.linalg.norm(cn, axis=2, keepdims=True), 1e-30)
    rows, convex = [], []
    for lst in edge_map(wt).values():
        if len(lst) != 2:
            continue
        (t1, i1, j1), (t2, i2, j2) = lst
        if not (use[t1] or use[t2]) or float(tn[t1] @ tn[t2]) >= sharp_cos:
            continue
        iy, jy = (i2, j2) if wt[t2, i2] == wt[t1, i1] else (j2, i2)
        if cn is not None and not (float(cn[t1, i1] @ cn[t2, iy]) >= SOFT_SMOOTH_COS
                                   and float(cn[t1, j1] @ cn[t2, jy]) >= SOFT_SMOOTH_COS):
            continue  # shaded hard: left as baked
        a = pos[tris[t1, i1]]
        f1, f2 = pos[tris[t1, 3 - i1 - j1]], pos[tris[t2, 3 - i2 - j2]]
        convex.append(bool((f2 - a) @ tn[t1] < 0 and (f1 - a) @ tn[t2] < 0))
        rows.append((t1, i1, j1, t2, iy, jy))
    if not rows:
        return None
    E = np.array(rows, dtype=np.int64)
    A, B = pos[tris[E[:, 0], E[:, 1]]], pos[tris[E[:, 0], E[:, 2]]]
    d = B - A
    L = np.linalg.norm(d, axis=1)
    dn = d / np.maximum(L, 1e-30)[:, None]

    def inward(t, far):
        v = pos[tris[t, far]] - A
        v = v - (v * dn).sum(axis=1, keepdims=True) * dn
        return v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-30)
    mX = inward(E[:, 0], 3 - E[:, 1] - E[:, 2])
    mY = inward(E[:, 3], 3 - E[:, 4] - E[:, 5])
    hX = ((pos[tris[E[:, 0], 3 - E[:, 1] - E[:, 2]]] - A) * mX).sum(axis=1)  # each face's height over the edge
    hY = ((pos[tris[E[:, 3], 3 - E[:, 4] - E[:, 5]]] - A) * mY).sum(axis=1)
    a3 = tri_areas_3d(pos, tris)
    with np.errstate(all='ignore'):
        texel = np.sqrt(a3 / np.abs(tri_areas_2d(uvpx)))
    texel = np.where(use & np.isfinite(texel), texel, 0.0)
    Wt = np.maximum(float(width), texel)
    # the candidates: edge points (spaced at most `step`) near each triangle of `use`
    step = max(float(width), 1e-6)
    n_s = np.clip(np.ceil(L / step), 1, max_samples).astype(np.int64)
    half = float((L / n_s).max()) / 2
    kd = KDTree(int(n_s.sum()))
    owner = np.repeat(np.arange(len(E)), n_s)
    k = 0
    for e in range(len(E)):
        for s in range(n_s[e]):
            kd.insert(Vector(A[e] + d[e] * ((s + 0.5) / n_s[e])), k)
            k += 1
    kd.balance()
    cen = pos[tris].mean(axis=1)
    rad = np.linalg.norm(pos[tris] - cen[:, None], axis=2).max(axis=1)
    start = np.zeros(T + 1, np.int64)
    lists = []
    for t in np.nonzero(use)[0]:
        found = kd.find_range(Vector(cen[t]), float(rad[t] + Wt[t] + half))
        if found:
            ids = np.unique(owner[[i for _co, i, _d in found]])
            lists.append((t, ids))
    for t, ids in lists:
        start[t + 1] = len(ids)
    start = np.cumsum(start)
    cand = np.zeros(int(start[-1]), np.int64)
    for t, ids in lists:
        cand[start[t]:start[t + 1]] = ids
    return dict(E=E, A=A, B=B, mX=mX, mY=mY, hX=hX, hY=hY, convex=np.array(convex, bool), pos=pos, tris=tris,
                Wt=Wt, start=start, cand=cand, width=float(width), edges=len(E))


# ---------------------------------------------------------------------------------------------------------------------
# Curvature (auto-bake journal item D, decision 54): from the object's own geometry, no rays
# ---------------------------------------------------------------------------------------------------------------------
#
# Signed, 50 % grey flat (P3), measured within a width (m) around each point, a sampling radius:
# - a sharp edge (welded faces whose normals are split there and differ by more than CURV_SHARP_DEG) is a band of that
#   width on both its faces, brightest (convex) or darkest (concave) at the edge and fading out (smoothstep); its
#   strength is the angle between the faces over 90 degrees (at most 1). Several convex edges: the strongest; several
#   concave: the strongest; a convex and a concave band add.
# - a smooth-shaded bend (the corner normals) is the angle the surface turns within the width, over 90 degrees: per
#   triangle the mean normal curvature along its edges, averaged per vertex, interpolated.
# The sum is clipped to -1 .. 1 and written as 0.5 + 0.5 x value.

CURV_FLAT = 32768
CURV_SHARP_DEG = 30.0
CURV_WIDTH = 0.0005  # m, the default width


def curvature_context(pos, tris, cn, width, max_samples=512):
    """What curvature_at needs for a mesh: tris (T,3) vertex ids into pos (V,3), cn (T,3,3) corner normals, width (m).
    The sharp edges with sign and strength, their candidates per triangle, the per-vertex smooth curvature."""
    from mathutils import Vector
    from mathutils.kdtree import KDTree
    T = len(tris)
    P = pos[tris]
    tn = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
    tn /= np.maximum(np.linalg.norm(tn, axis=1, keepdims=True), 1e-30)
    wv = weld_ids(pos)
    wt = wv[tris]
    sharp_cos = math.cos(math.radians(CURV_SHARP_DEG))
    rows = []
    for lst in edge_map(wt).values():
        if len(lst) != 2:
            continue
        (t1, i1, j1), (t2, i2, j2) = lst
        cos = float(tn[t1] @ tn[t2])
        if cos >= sharp_cos:
            continue
        iy, jy = (i2, j2) if wt[t2, i2] == wt[t1, i1] else (j2, i2)
        if float(cn[t1, i1] @ cn[t2, iy]) > 0.999 and float(cn[t1, j1] @ cn[t2, jy]) > 0.999:
            continue  # smooth-shaded across: the smooth term carries it
        a = pos[tris[t1, i1]]
        f1, f2 = pos[tris[t1, 3 - i1 - j1]], pos[tris[t2, 3 - i2 - j2]]
        convex = (f2 - a) @ tn[t1] < 0 and (f1 - a) @ tn[t2] < 0
        concave = (f2 - a) @ tn[t1] > 0 and (f1 - a) @ tn[t2] > 0
        if not (convex or concave):
            continue  # folded
        strength = min(1.0, math.degrees(math.acos(max(-1.0, min(1.0, cos)))) / 90.0)
        rows.append((t1, i1, j1, t2, iy, jy, 1.0 if convex else -1.0, strength))
    # smooth term: per triangle the mean of (n_i - n_j).(p_i - p_j) / |p_i - p_j|^2 over its edges (1/m, convex > 0)
    k_t = np.zeros(T)
    for i, j in ((0, 1), (1, 2), (2, 0)):
        dp = P[:, i] - P[:, j]
        k_t += ((cn[:, i] - cn[:, j]) * dp).sum(axis=1) / np.maximum((dp * dp).sum(axis=1), 1e-30)
    k_t /= 3.0
    area = tri_areas_3d(pos, tris)
    nv = int(wv.max()) + 1 if len(wv) else 0
    ks, ws = np.zeros(nv), np.zeros(nv)
    for c in range(3):
        np.add.at(ks, wt[:, c], k_t * area)
        np.add.at(ws, wt[:, c], area)
    k_v = ks / np.maximum(ws, 1e-30)
    out = dict(width=float(width), wt=wt, tn=tn, k_corner=k_v[wt], edges=len(rows), start=np.zeros(T + 1, np.int64),
               cand=np.zeros(0, np.int64))
    if not rows:
        return out
    E = np.array([r[:6] for r in rows], dtype=np.int64)
    sign = np.array([r[6] for r in rows])
    strength = np.array([r[7] for r in rows])
    A, B = pos[tris[E[:, 0], E[:, 1]]], pos[tris[E[:, 0], E[:, 2]]]
    d = B - A
    L = np.linalg.norm(d, axis=1)
    dn = d / np.maximum(L, 1e-30)[:, None]

    def inward(t, far):
        v = pos[tris[t, far]] - A
        v = v - (v * dn).sum(axis=1, keepdims=True) * dn
        return v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-30)
    mX = inward(E[:, 0], 3 - E[:, 1] - E[:, 2])
    mY = inward(E[:, 3], 3 - E[:, 4] - E[:, 5])
    step = max(float(width), 1e-6)
    n_s = np.clip(np.ceil(L / step), 1, max_samples).astype(np.int64)
    half = float((L / n_s).max()) / 2
    kd = KDTree(int(n_s.sum()))
    owner = np.repeat(np.arange(len(E)), n_s)
    k = 0
    for e in range(len(E)):
        for q in range(n_s[e]):
            kd.insert(Vector(A[e] + d[e] * ((q + 0.5) / n_s[e])), k)
            k += 1
    kd.balance()
    cen = P.mean(axis=1)
    rad = np.linalg.norm(P - cen[:, None], axis=2).max(axis=1)
    start = np.zeros(T + 1, np.int64)
    lists = []
    for t in range(T):
        found = kd.find_range(Vector(cen[t]), float(rad[t] + width + half))
        if found:
            ids = np.unique(owner[[i for _co, i, _d in found]])
            lists.append((t, ids))
            start[t + 1] = len(ids)
    start = np.cumsum(start)
    cand = np.zeros(int(start[-1]), np.int64)
    for t, ids in lists:
        cand[start[t]:start[t + 1]] = ids
    out.update(E=E, A=A, B=B, mX=mX, mY=mY, sign=sign, strength=strength, start=start, cand=cand)
    return out


def curvature_at(cc, tri_ids, bary, P3, chunk=COPY_CHUNK):
    """Curvature (-1 .. 1) at points P3 (N,3) on triangles tri_ids with barycentric coordinates bary (N,3)."""
    width = cc['width']
    val = (bary * cc['k_corner'][tri_ids]).sum(axis=1) * width / (math.pi / 2)
    start, cand = cc['start'], cc['cand']
    nc = start[tri_ids + 1] - start[tri_ids]
    idx = np.nonzero(nc > 0)[0]
    if len(idx):
        cnt = nc[idx]
        total = int(cnt.sum())
        pix = np.repeat(idx, cnt)
        first = np.repeat(start[tri_ids[idx]] - np.concatenate([[0], np.cumsum(cnt)[:-1]]), cnt)
        edge = cand[first + np.arange(total)]
        E, A, B, mX, mY, tn = cc['E'], cc['A'], cc['B'], cc['mX'], cc['mY'], cc['tn']
        hi = np.zeros(len(tri_ids))
        lo = np.zeros(len(tri_ids))
        cos = math.cos(math.radians(CURV_SHARP_DEG))
        for c0, c1 in _chunks(total, chunk):
            i, e = pix[c0:c1], edge[c0:c1]
            p, a, b = P3[i], A[e], B[e]
            ab = b - a
            u = np.clip(((p - a) * ab).sum(axis=1) / np.maximum((ab * ab).sum(axis=1), 1e-30), 0.0, 1.0)
            q = a + ab * u[:, None]
            dist = np.linalg.norm(p - q, axis=1)
            s = tri_ids[i]
            cx = (tn[s] * tn[E[e, 0]]).sum(axis=1)
            cy = (tn[s] * tn[E[e, 3]]).sum(axis=1)
            m = np.where((cx >= cy)[:, None], mX[e], mY[e])
            keep = (np.maximum(cx, cy) >= cos) & (((p - q) * m).sum(axis=1) >= -1e-3 * width) & (dist < width)
            if not keep.any():
                continue
            i, e, x = i[keep], e[keep], dist[keep] / width
            g = cc['strength'][e] * (1.0 - x * x * (3.0 - 2.0 * x))
            conv = cc['sign'][e] > 0
            np.maximum.at(hi, i[conv], g[conv])
            np.maximum.at(lo, i[~conv], g[~conv])
        val = val + hi - lo
    return np.clip(val, -1.0, 1.0)


def write_curvature(folder, stem, m, pos, tris, cn, width, threads=None, rows=256):
    """The curvature master <stem>.curv.jxl (an older .curv.png removed) in the AO master's layout (the .ao.map's
    faces, m's muv), from the triangles of the master (tris (T,3) into pos, cn (T,3,3), in tri_src order). Not filled
    pixels: flat. Returns dict(path, edges, seconds)."""
    t0 = time.time()
    cc = curvature_context(pos, tris, cn, width)
    _img, mp, _npz = master_paths(folder, stem)
    W, H, gen = map_rows(mp, rows)
    jx, pn = image_paths(folder, stem, 'curv')
    lib = jxl()  # decision 6: libjxl is required (its Writer raises JxlError without it)
    path, other = jx, pn
    w = lib.Writer(path + '.tmp', W, H, threads=threads or lib.THREADS)
    muv = m['muv']
    P = pos[tris]
    try:
        top = 0
        for block in gen:  # rows from the top: file row r is master pixel row H - 1 - r
            n = block.shape[0]
            out = np.full((n, W), CURV_FLAT, np.uint16)
            filled, face = code_filled(block), code_face(block)
            rr, xx = np.nonzero(filled & (face >= 0))
            if len(rr):
                f = face[rr, xx]
                py = (H - 1 - (top + rr)) + 0.5
                a, b, c = muv[f, 0], muv[f, 1], muv[f, 2]
                v1, v2 = b - a, c - a
                vx, vy = xx + 0.5 - a[:, 0], py - a[:, 1]
                den = v1[:, 0] * v2[:, 1] - v1[:, 1] * v2[:, 0]
                den = np.where(np.abs(den) > 1e-12, den, 1e-12)
                l1 = (vx * v2[:, 1] - vy * v2[:, 0]) / den
                l2 = (v1[:, 0] * vy - v1[:, 1] * vx) / den
                bary = np.stack([1 - l1 - l2, l1, l2], 1)
                P3 = np.einsum('nk,nkd->nd', bary, P[f])
                out[rr, xx] = np.rint((0.5 + 0.5 * curvature_at(cc, f, bary, P3)) * 65535.0).astype(np.uint16)
            w.write(out)
            top += n
        w.close()
    except BaseException:
        w.abort()
        raise
    os.replace(path + '.tmp', path)
    try:
        os.remove(other)
    except OSError:
        pass
    return dict(path=path, edges=int(cc['edges']), seconds=round(time.time() - t0, 2))


# ---------------------------------------------------------------------------------------------------------------------
# Denoise (decision 56): an adaptive, geometry-aware filter of a master, guided by its geometry and its curvature master
# ---------------------------------------------------------------------------------------------------------------------
#
# A-trous joint bilateral filter (the B3 spline, 5 x 5 taps at steps 1, 2, 4 ... px): a neighbour pixel counts with
#   the spatial weight of its 3D distance (Gaussian, sigma = the radius times the pixel's flatness), 0 across a shading
#   normal change over the normal angle (sharp edges; and islands far apart in 3D get no spatial weight), and the
#   range weight of the AO difference against the two pixels' noise (Gaussian, Detail x their noise): a real change
#   of the AO (a contact shadow) is kept, a change within the noise is smoothed. The noise variance per pixel is
#   alpha v (1 - v), alpha measured from the master itself (the residual against the 4 neighbours on the same face) or
#   1 / samples; it is carried through the levels. The curvature master guides it (curv_mode): SIMILAR, a neighbour
#   counts less the more its curvature differs (Gaussian, sigma Threshold), so a sharp edge's band is smoothed along
#   the edge, not across it; SHRINK, the radius times the flatness (1 at flat grey, 0 at Threshold from grey and
#   beyond), so edge bands and tight bends are left as baked; OFF. Measured on the console buttons (Session 39):
#   SHRINK left the bands' noise and did worse than OFF.
# Banded: the rows from the top in bands, each read with a halo of the levels' reach from the raw master paged; one
#   band and its halo are held, whatever the master's size. Pixels without a face (gutter) keep their raw value.

DN_KERNEL = np.array([1 / 16, 1 / 4, 3 / 8, 1 / 4, 1 / 16], np.float32)
DN_VAR_FLOOR = 0.0025  # v (1 - v) at least this: near black and white the noise is not 0 in practice
DN_BAND = 128  # rows per band
DN_MEASURE_RANGE = (0.02, 0.98)  # the AO of the pixels the noise is measured on
DN_CHI2_MEDIAN = 0.4549  # the median of a chi-square with 1 degree of freedom (the noise from squared residuals)
DN_DEFAULTS = dict(radius=0.001, strength=1.0, max_levels=5, detail=3.0, normal_deg=30.0, curv_mode='SIMILAR',
                   curv_threshold=0.1, noise='MEASURED', samples=256)


def denoise_levels(radius_px, max_levels):
    """The a-trous levels whose spread reaches radius_px (the B3 kernel spreads sqrt((4^L - 1) / 3) px after L
    levels), at least 1 and at most max_levels."""
    L = 1
    while L < max_levels and math.sqrt((4 ** L - 1) / 3.0) < radius_px:
        L += 1
    return L


def page_image(path, map_path, W, H, page_path, cache_bytes, threads=None):
    """A master-sized 16-bit JPEG XL image of a master's layout decoded once into a tiled scratch file, read as a
    PagedArray (row 0 the bottom). The caller closes it and removes page_path. Decision 6: the C++ opening does it
    (ao_bake_copy.open_pages), which opens the image with the master's .ao.map (map_path); the map's page file is
    removed at once. A PNG raises MasterUnreadable."""
    if not path.endswith('.jxl'):
        raise MasterUnreadable(f'{path}: a PNG image the C++ code does not open: {REBAKE}')
    lib = jxl()
    if not lib.available():
        raise lib.JxlError(f'{path}: the JPEG XL library is not loaded ({lib.error()})')
    map_page = page_path + '.mappage'
    try:
        native_copy().open_pages(lib.LIB_DIR, path, map_path, page_path, map_page, W, H, PAGE_TILE, threads)
    finally:
        try:
            os.remove(map_page)
        except OSError:
            pass
    return PagedArray(page_path, H, W, np.uint16, cache_bytes)


def _dn_window(master, ys, W):
    yi, xi = np.broadcast_arrays(ys[:, None], np.arange(W)[None, :])
    v = master['image'][yi, xi].astype(np.float32) / 65535.0
    face = master['face_map'][yi, xi]
    filled = master['filled'][yi, xi]
    return v, np.where(filled, face, -1), (yi, xi)


def _dn_geometry(face, ys, muv, P, CN):
    """3D position and interpolated shading normal of each pixel with a face (NaN / 0 elsewhere); P None: the normal
    only (POS None)."""
    h, W = face.shape
    POS = np.zeros((h, W, 3), np.float32) if P is not None else None
    NRM = np.zeros((h, W, 3), np.float32)
    rr, xx = np.nonzero(face >= 0)
    if not len(rr):
        return POS, NRM
    f = face[rr, xx]
    a, b, c = muv[f, 0], muv[f, 1], muv[f, 2]
    v1, v2 = b - a, c - a
    vx, vy = xx + 0.5 - a[:, 0], ys[rr] + 0.5 - a[:, 1]
    den = v1[:, 0] * v2[:, 1] - v1[:, 1] * v2[:, 0]
    den = np.where(np.abs(den) > 1e-12, den, 1e-12)
    l1 = (vx * v2[:, 1] - vy * v2[:, 0]) / den
    l2 = (v1[:, 0] * vy - v1[:, 1] * vx) / den
    bary = np.stack([1 - l1 - l2, l1, l2], 1)
    if P is not None:
        POS[rr, xx] = np.einsum('nk,nkd->nd', bary, P[f])
    n = np.einsum('nk,nkd->nd', bary, CN[f])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-30)
    NRM[rr, xx] = n
    return POS, NRM


def noise_alpha(master, W, H, band=DN_BAND, every=4, cap=4_000_000):
    """The master's noise as alpha in variance = alpha v (1 - v): from the residual of each pixel against its 4
    neighbours on the same face (variance 5/4 of the noise's), the median over every `every`-th band. Only partly
    occluded pixels (DN_MEASURE_RANGE) count: an unoccluded one is exactly white, without noise, and an object mostly
    in the open would otherwise measure no noise at all. None without such pixels."""
    got, n = [], 0
    for y0 in range(0, H, band * every):
        ys = np.arange(y0, min(H, y0 + band))
        if len(ys) < 3:
            continue
        v, face, _ = _dn_window(master, ys, W)
        c, f = v[1:-1, 1:-1], face[1:-1, 1:-1]
        same = (f >= 0) & (f == face[:-2, 1:-1]) & (f == face[2:, 1:-1]) & (f == face[1:-1, :-2]) & (f == face[1:-1, 2:])
        same &= (c > DN_MEASURE_RANGE[0]) & (c < DN_MEASURE_RANGE[1])
        if not same.any():
            continue
        m4 = (v[:-2, 1:-1] + v[2:, 1:-1] + v[1:-1, :-2] + v[1:-1, 2:]) / 4
        q = np.maximum(c * (1 - c), DN_VAR_FLOOR)
        r = ((c - m4) ** 2 / 1.25 / q)[same]
        got.append(r)
        n += len(r)
        if n >= cap:
            break
    if not got:
        return None
    return float(np.median(np.concatenate(got)) / DN_CHI2_MEDIAN)


def _dn_slices(n, d):
    """(destination, source) slices of an axis of n for the neighbour at i + d."""
    return (slice(0, n - d), slice(d, n)) if d >= 0 else (slice(-d, n), slice(0, n + d))


def denoise_window(v0, valid, POS, NRM, sig, var0, levels, detail, cos_min, C=None, c_sigma=0.1):
    """The a-trous joint bilateral filter on a window (see above). sig: the spatial sigma per pixel (m), var0 the
    noise variance per pixel, C the curvature per pixel (0..1) or None. Returns (the filtered values, their noise variance) (valid pixels; the others as given)."""
    h, W = v0.shape
    v, var = v0.copy(), var0.copy()
    s2 = (2.0 * sig * sig).astype(np.float32) + np.float32(1e-20)
    k2 = np.float32(2.0 * detail * detail)
    c2 = np.float32(2.0 * c_sigma * c_sigma)
    for lv in range(levels):
        step = 2 ** lv
        sw = np.zeros((h, W), np.float32)
        swv = np.zeros((h, W), np.float32)
        sw2 = np.zeros((h, W), np.float32)
        for iy in range(5):
            dy = (iy - 2) * step
            if abs(dy) >= h:
                continue
            ydst, ysrc = _dn_slices(h, dy)
            for ix in range(5):
                dx = (ix - 2) * step
                if abs(dx) >= W:
                    continue
                xdst, xsrc = _dn_slices(W, dx)
                c, j = (ydst, xdst), (ysrc, xsrc)
                ok = valid[c] & valid[j]
                if not ok.any():
                    continue
                d = POS[c] - POS[j]
                w = np.exp(-np.einsum('hwc,hwc->hw', d, d) / s2[c])
                w *= DN_KERNEL[iy] * DN_KERNEL[ix]
                w *= np.einsum('hwc,hwc->hw', NRM[c], NRM[j]) >= cos_min
                pred = v[j]
                dv = v[c] - pred
                w *= np.exp(-dv * dv / (k2 * (var[c] + var[j]) + np.float32(1e-12)))
                if C is not None:
                    dc = C[c] - C[j]
                    w *= np.exp(-dc * dc / c2)
                w *= ok
                sw[c] += w
                swv[c] += w * pred
                sw2[c] += w * w * var[j]
        good = valid & (sw > 0)
        v = np.where(good, swv / np.maximum(sw, 1e-30), v)
        var = np.where(good, sw2 / np.maximum(sw * sw, np.float32(1e-30)), var)
    return v, var


def denoise_master(folder, stem, pos, tris, cn, opts, threads=None, band=DN_BAND, on_band=None, cache_bytes=None):
    """Decision 56: the raw master <stem>.ao.raw.jxl filtered into the master <stem>.ao.jxl, in
    bands from the top (see above); tris (T,3) into pos, cn (T,3,3), in tri_src order (as write_curvature). opts:
    DN_DEFAULTS' keys (radius m, strength, max_levels, detail, normal_deg, curv_mode OFF / SIMILAR / SHRINK,
    curv_threshold, noise MEASURED or SAMPLES, samples). The curvature master guides it when it exists. on_band(i, n) after each band.
    Returns the stats (alpha, levels, radius_px, curvature used, pixels, mean change, seconds)."""
    t0 = time.time()
    cache_bytes = cache_bytes or PAGE_CACHE_BYTES
    o = dict(DN_DEFAULTS, **opts)
    raw = master_paths(folder, stem, 'ao.raw')[0]
    if not os.path.isfile(raw):
        raise FileNotFoundError(f'{raw}: no raw master')
    master = open_master(folder, stem, cache_bytes=cache_bytes, kind='ao.raw')
    if master is None:
        raise FileNotFoundError(f'{stem}: the raw master or its layout is missing')
    curv_img, curv_page = None, None
    try:
        W, H = master['W'], master['H']
        cpath = master_paths(folder, stem, 'curv')[0]
        if o['curv_mode'] != 'OFF' and os.path.isfile(cpath):
            curv_page = os.path.join(folder, stem) + '.curv.dnpage'
            curv_img = page_image(cpath, master_paths(folder, stem)[1], W, H, curv_page, cache_bytes // 3,
                                  threads=threads)
        density = float(master['density'])  # px per m
        radius_px = float(o['radius']) * density
        levels = denoise_levels(radius_px, int(o['max_levels']))
        halo = 2 * (2 ** levels - 1)
        if o['noise'] == 'SAMPLES':
            alpha = 1.0 / max(int(o['samples']), 1)
        else:
            alpha = noise_alpha(master, W, H)
            if alpha is None:
                alpha = 1.0 / max(int(o['samples']), 1)
        P = pos[tris].astype(np.float32)
        CN = np.asarray(cn, np.float32)
        muv = master['muv']
        cos_min = np.float32(math.cos(math.radians(float(o['normal_deg']))))
        strength = float(o['strength'])
        dst, other = image_paths(folder, stem)  # decision 6: a raw master opens only as JPEG XL
        lib = jxl()
        w = lib.Writer(dst + '.tmp', W, H, threads=threads or lib.THREADS)
        n_px, change = 0, 0.0
        nb = -(-H // band)
        try:
            for i, top in enumerate(range(0, H, band)):
                y1 = H - top
                y0 = max(0, y1 - band)
                wa, wb = max(0, y0 - halo), min(H, y1 + halo)
                ys = np.arange(wa, wb)
                v0, face, idx = _dn_window(master, ys, W)
                raw16 = master['image'][idx[0][y0 - wa:y1 - wa], idx[1][y0 - wa:y1 - wa]]
                valid = face >= 0
                if valid.any() and strength > 0:
                    POS, NRM = _dn_geometry(face, ys, muv, P, CN)
                    C = None if curv_img is None else curv_img[idx].astype(np.float32) / 65535.0
                    thr = max(float(o['curv_threshold']), 1e-6)
                    if C is not None and o['curv_mode'] == 'SHRINK':
                        flat = np.clip(1.0 - np.abs(C - 0.5) * 2.0 / thr, 0.0, 1.0)
                        C = None
                    else:
                        flat = np.ones_like(v0)
                    sig = (np.float32(o['radius']) * flat).astype(np.float32)
                    var0 = (alpha * np.maximum(v0 * (1 - v0), DN_VAR_FLOOR)).astype(np.float32)
                    out, var1 = denoise_window(v0, valid, POS, NRM, sig, var0, levels, float(o['detail']), cos_min,
                                               C, thr)
                    r = slice(y0 - wa, y1 - wa)
                    vb, okb = v0[r], valid[r]
                    res = np.where(okb, vb + strength * (out[r] - vb), vb)
                    q = np.clip(np.rint(res * 65535.0), 0, 65535).astype(np.uint16)
                    q = np.where(okb, q, raw16)
                    n_px += int(okb.sum())
                    change += float(np.abs(res - vb)[okb].sum())
                else:
                    q = raw16
                w.write(np.ascontiguousarray(q[::-1]))  # file rows from the top
                if on_band is not None:
                    on_band(i + 1, nb)
            w.close()
        except BaseException:
            w.abort()
            raise
        os.replace(dst + '.tmp', dst)
        try:
            os.remove(other)
        except OSError:
            pass
    finally:
        master['close']()
        if curv_img is not None:
            curv_img.close()
            try:
                os.remove(curv_page)
            except OSError:
                pass
    return dict(alpha=round(alpha, 6), noise=round(math.sqrt(alpha * 0.25), 5), levels=int(levels),
                radius_px=round(radius_px, 2), curvature=o['curv_mode'] if curv_img is not None else 'OFF', px=int(n_px),
                mean_change=round(change / max(n_px, 1), 6), seconds=round(time.time() - t0, 2))


# ---------------------------------------------------------------------------------------------------------------------
# Denoise with Open Image Denoise (OIDN, the denoiser Blender ships), islands isolated
# ---------------------------------------------------------------------------------------------------------------------
#
# OIDN's RT filter (the AO as colour, a white albedo, the pixels' shading normals) sees an image, not islands: run on
# the master as it is, the islands next to one another in it bleed into each other. So the islands are isolated: they
# are split into groups whose islands lie at least 2 x OIDN_GROUP_PX apart (a greedy colouring of the islands within
# that distance), and per group an image holds only that group's islands, each grown OIDN_EDGE_PX pixels outward with
# its own edge values and normals (one pixel a step), the rest filled by push-pull (each empty pixel the mean of the
# nearest coarser level with island pixels). OIDN runs once per group; each island keeps its own group's result right
# up to its border. Measured on the console buttons (256 samples against 1024): master RMS 0.0025, 4 x 4 0.0010, as
# the Surface Filter at Detail 6. Banded: windows of rows with a halo of OIDN_HALO rows, so a master of any size fits.
# Pixels without a face (gutter) keep their raw value. The device: the GPU OIDN finds when the bake runs on the GPU
# (else, or when that fails, the CPU).

OIDN_GROUP_PX = 24
OIDN_EDGE_PX = 4
OIDN_HALO = 128
OIDN_WINDOW_PX = 8_000_000  # pixels of a window (its band and halo) at most
OIDN_DEVICES = {'GPU': 0, 'CPU': 1}  # OIDN_DEVICE_TYPE_DEFAULT (the fastest it finds), OIDN_DEVICE_TYPE_CPU
_oidn_cache = {}


def oidn_library():
    """Blender's OpenImageDenoise library through ctypes (loaded once); RuntimeError when it is not there."""
    if 'lib' in _oidn_cache:
        return _oidn_cache['lib']
    import ctypes
    import glob
    import bpy
    folder = os.path.join(os.path.dirname(bpy.app.binary_path), 'blender.shared')
    names = (['OpenImageDenoise.dll'] if os.name == 'nt' else
             sorted(os.path.basename(p) for p in glob.glob(os.path.join(folder, 'libOpenImageDenoise.*'))))
    path = os.path.join(folder, names[0]) if names else ''
    if not path or not os.path.isfile(path):
        raise RuntimeError(f'Open Image Denoise not found beside Blender ({folder})')
    if hasattr(os, 'add_dll_directory'):
        os.add_dll_directory(folder)
    lib = ctypes.CDLL(path)
    vp, cp, sz = ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t
    sig = dict(oidnNewDevice=(vp, [ctypes.c_int]), oidnCommitDevice=(None, [vp]), oidnNewFilter=(vp, [vp, cp]),
               oidnNewBuffer=(vp, [vp, sz]), oidnWriteBuffer=(None, [vp, sz, sz, vp]),
               oidnReadBuffer=(None, [vp, sz, sz, vp]),
               oidnSetFilterImage=(None, [vp, cp, vp, ctypes.c_int, sz, sz, sz, sz, sz]),
               oidnSetFilterBool=(None, [vp, cp, ctypes.c_bool]), oidnSetFilterInt=(None, [vp, cp, ctypes.c_int]),
               oidnCommitFilter=(None, [vp]), oidnExecuteFilter=(None, [vp]),
               oidnGetDeviceError=(ctypes.c_int, [vp, ctypes.POINTER(cp)]), oidnReleaseFilter=(None, [vp]),
               oidnReleaseBuffer=(None, [vp]), oidnReleaseDevice=(None, [vp]))
    for name, (res, args) in sig.items():
        fn = getattr(lib, name)
        fn.restype, fn.argtypes = res, args
    _oidn_cache['lib'] = lib
    return lib


def _oidn_error(lib, dev):
    import ctypes
    msg = ctypes.c_char_p()
    code = lib.oidnGetDeviceError(dev, ctypes.byref(msg))
    return f'{code} {msg.value.decode(errors="replace") if msg.value else ""}'.strip() if code else ''


def oidn_device(kind):
    """(lib, device handle, the device used): the GPU OIDN finds for 'GPU' (the CPU when it finds none or fails)."""
    lib = oidn_library()
    for name in ((kind, 'CPU') if kind != 'CPU' else ('CPU',)):
        dev = lib.oidnNewDevice(OIDN_DEVICES.get(name, 1))
        if dev:
            lib.oidnCommitDevice(dev)
            if not _oidn_error(lib, dev):
                return lib, dev, name
            lib.oidnReleaseDevice(dev)
    raise RuntimeError('Open Image Denoise: no device could be made')


def oidn_run(lib, dev, color, normal):
    """OIDN's RT filter on one image: color (h, w) in 0..1, normal (h, w, 3); a white albedo. Returns (h, w)."""
    h, w = color.shape
    c3 = np.ascontiguousarray(np.repeat(color[..., None], 3, axis=2), np.float32)
    nbytes = c3.nbytes
    bufs = []

    def buf(arr):
        b = lib.oidnNewBuffer(dev, nbytes)
        a = np.ascontiguousarray(arr, np.float32)
        lib.oidnWriteBuffer(b, 0, nbytes, a.ctypes.data)
        bufs.append(b)
        return b
    f = lib.oidnNewFilter(dev, b'RT')
    try:
        lib.oidnSetFilterImage(f, b'color', buf(c3), 3, w, h, 0, 0, 0)  # 3: OIDN_FORMAT_FLOAT3
        lib.oidnSetFilterImage(f, b'albedo', buf(np.ones_like(c3)), 3, w, h, 0, 0, 0)
        lib.oidnSetFilterImage(f, b'normal', buf(normal), 3, w, h, 0, 0, 0)
        out = lib.oidnNewBuffer(dev, nbytes)
        bufs.append(out)
        lib.oidnSetFilterImage(f, b'output', out, 3, w, h, 0, 0, 0)
        lib.oidnSetFilterBool(f, b'hdr', False)
        lib.oidnSetFilterBool(f, b'srgb', False)
        lib.oidnSetFilterBool(f, b'cleanAux', True)
        lib.oidnSetFilterInt(f, b'quality', 6)  # OIDN_QUALITY_HIGH
        lib.oidnCommitFilter(f)
        lib.oidnExecuteFilter(f)
        err = _oidn_error(lib, dev)
        if err:
            raise RuntimeError(f'Open Image Denoise: {err}')
        res = np.empty_like(c3)
        lib.oidnReadBuffer(out, 0, nbytes, res.ctypes.data)
    finally:
        lib.oidnReleaseFilter(f)
        for b in bufs:
            lib.oidnReleaseBuffer(b)
    return res[..., 0]


_SHIFTS = ((1, 0), (-1, 0), (0, 1), (0, -1))


def _dilate_labels(lab, steps, vals=()):
    """Labels grown `steps` pixels (4-neighbour, the first to arrive wins); vals: arrays (h, w[, C]) carried with
    them (the mean of the arriving neighbours of the same label). Returns (labels, vals).

    Works on the growing edge only (the pixels a step can reach are the empty neighbours of the pixels the step before
    labelled), in a copy padded by one pixel so the neighbours need no bounds; the neighbours are read in _SHIFTS order
    and the means summed in that order in float32, as a whole-image step would."""
    h, w = lab.shape
    W2 = w + 2
    Lp = np.full((h + 2, W2), -2, lab.dtype)  # -2: the border, never labelled; -1: empty
    Lp[1:-1, 1:-1] = np.where(lab >= 0, lab, -1)
    Lf = Lp.ravel()
    vals = [v.copy() for v in vals]
    flat = [v.reshape(h * w, -1) for v in vals]  # views of the copies
    offs = tuple(dy * W2 + dx for dy, dx in _SHIFTS)
    inner = Lp[1:-1, 1:-1]
    empty_nb = np.zeros((h, w), bool)
    for dy, dx in _SHIFTS:
        empty_nb |= Lp[1 + dy:h + 1 + dy, 1 + dx:w + 1 + dx] == -1
    yy, xx = np.nonzero((inner >= 0) & empty_nb)
    front = (yy + 1) * W2 + xx + 1
    for _k in range(steps):
        if not len(front):
            break
        nb = (front[:, None] + np.array(offs)[None, :]).ravel()
        nb = np.unique(nb[Lf[nb] == -1])
        if not len(nb):
            break
        cand = np.full(len(nb), -1, Lf.dtype)
        for o in offs:
            src = Lf[nb + o]
            take = (cand < 0) & (src >= 0)
            cand[take] = src[take]
        for v in flat:
            acc = np.zeros((len(nb), v.shape[1]), np.float32)
            cnt = np.zeros(len(nb), np.float32)
            for o in offs:
                q = nb + o
                same = (Lf[q] == cand) & (Lf[q] >= 0)
                qs = q[same]
                acc[same] += v[(qs // W2 - 1) * w + qs % W2 - 1]
                cnt[same] += 1
            f = (nb // W2 - 1) * w + nb % W2 - 1
            v[f] = acc / np.maximum(cnt, 1)[:, None]
        Lf[nb] = cand
        front = nb
    return np.where(inner >= 0, inner, lab), vals


def _push_pull(v, wgt):
    """Empty pixels (wgt 0) filled from a pyramid of masked means: each takes the value of the finest coarser level
    that has island pixels there (nearest upsampling, so the fill next to an island is its own edge)."""
    levels = []
    cv = v * (wgt[..., None] if v.ndim == 3 else wgt)
    cw = wgt.astype(np.float32)
    while max(cw.shape) > 1:
        h2, w2 = -(-cw.shape[0] // 2), -(-cw.shape[1] // 2)
        pv = np.zeros((h2 * 2, w2 * 2) + cv.shape[2:], np.float32)
        pw = np.zeros((h2 * 2, w2 * 2), np.float32)
        pv[:cv.shape[0], :cv.shape[1]] = cv
        pw[:cw.shape[0], :cw.shape[1]] = cw
        cv = pv.reshape(h2, 2, w2, 2, *cv.shape[2:]).sum(axis=(1, 3))
        cw = pw.reshape(h2, 2, w2, 2).sum(axis=(1, 3))
        levels.append((cv, cw))
    fill = None
    for cv, cw in reversed(levels):
        has = (cw > 0)[..., None] if cv.ndim == 3 else cw > 0
        mean = cv / (np.maximum(cw, 1e-12)[..., None] if cv.ndim == 3 else np.maximum(cw, 1e-12))
        if fill is not None:
            up = np.repeat(np.repeat(fill, 2, 0), 2, 1)[:mean.shape[0], :mean.shape[1]]
            mean = np.where(has, mean, up)
        fill = mean
    if fill is None:
        return v
    up = np.repeat(np.repeat(fill, 2, 0), 2, 1)[:v.shape[0], :v.shape[1]]
    return np.where((wgt > 0)[..., None] if v.ndim == 3 else wgt > 0, v, up)


def oidn_isolated(lib, dev, v0, nrm, isl, n_islands):
    """OIDN on a window with its islands isolated (see above): v0 (h, w) the AO, nrm (h, w, 3), isl (h, w) the island
    of each face pixel (-1 none), n_islands the number of the master's islands. Returns (values, groups)."""
    out = v0.copy()
    if not (isl >= 0).any():
        return out, 0
    grown, _ = _dilate_labels(isl, OIDN_GROUP_PX)
    pairs = []
    for a, b in ((grown[:, :-1], grown[:, 1:]), (grown[:-1], grown[1:])):
        m = (a >= 0) & (b >= 0) & (a != b)
        pairs.append(np.stack([np.minimum(a[m], b[m]), np.maximum(a[m], b[m])], 1))
    pairs = np.unique(np.concatenate(pairs), axis=0) if any(len(p) for p in pairs) else np.zeros((0, 2), np.int64)
    present = np.unique(isl[isl >= 0])
    nbr = {int(i): [] for i in present}
    for a, b in pairs.tolist():
        if a in nbr and b in nbr:
            nbr[a].append(b)
            nbr[b].append(a)
    color = np.full(n_islands, -1, np.int64)
    for i in sorted(nbr, key=lambda k: -len(nbr[k])):
        used = {int(color[j]) for j in nbr[i]}
        c = 0
        while c in used:
            c += 1
        color[i] = c
    groups = int(color[present].max()) + 1
    for g in range(groups):
        lab = np.where((isl >= 0) & (color[np.maximum(isl, 0)] == g), isl, -1)
        sel = lab >= 0
        vv = np.where(sel, v0, 0).astype(np.float32)
        nn = np.where(sel[..., None], nrm, 0).astype(np.float32)
        lab2, (vv, nn) = _dilate_labels(lab, OIDN_EDGE_PX, (vv, nn))
        wgt = (lab2 >= 0).astype(np.float32)
        vv = _push_pull(np.where(lab2 >= 0, vv, 0), wgt)
        nn = _push_pull(np.where((lab2 >= 0)[..., None], nn, 0), wgt)
        nn /= np.maximum(np.linalg.norm(nn, axis=2, keepdims=True), 1e-6)
        res = oidn_run(lib, dev, vv, nn)
        out[sel] = res[sel]
    return out, groups


def denoise_master_oidn(folder, stem, pos, tris, cn, opts, device='GPU', on_band=None, cache_bytes=None):
    """The raw master <stem>.ao.raw.jxl denoised by OIDN with its islands isolated (see above) into the master
    <stem>.ao.jxl; tris, pos, cn as denoise_master. opts: method OIDN, strength. on_band(i, n) after each
    window. Returns the stats (method, device, groups at most, windows, pixels, mean change, seconds)."""
    t0 = time.time()
    cache_bytes = cache_bytes or PAGE_CACHE_BYTES
    strength = float(opts.get('strength', 1.0))
    raw = master_paths(folder, stem, 'ao.raw')[0]
    if not os.path.isfile(raw):
        raise FileNotFoundError(f'{raw}: no raw master')
    lib, dev, used = oidn_device(device)
    master = open_master(folder, stem, cache_bytes=cache_bytes, kind='ao.raw')
    if master is None:
        lib.oidnReleaseDevice(dev)
        raise FileNotFoundError(f'{stem}: the raw master or its layout is missing')
    try:
        W, H = master['W'], master['H']
        island = master['island']
        n_islands = int(island.max()) + 1 if len(island) else 0
        CN = np.asarray(cn, np.float32)
        muv = master['muv']
        dst, other = image_paths(folder, stem)  # decision 6: a raw master opens only as JPEG XL
        jl = jxl()
        w = jl.Writer(dst + '.tmp', W, H, threads=jl.THREADS)
        band = max(64, OIDN_WINDOW_PX // max(W, 1) - 2 * OIDN_HALO)
        nb = -(-H // band)
        n_px, change, groups = 0, 0.0, 0
        try:
            for i, top in enumerate(range(0, H, band)):
                y1 = H - top
                y0 = max(0, y1 - band)
                wa, wb = max(0, y0 - OIDN_HALO), min(H, y1 + OIDN_HALO)
                ys = np.arange(wa, wb)
                v0, face, idx = _dn_window(master, ys, W)
                r = slice(y0 - wa, y1 - wa)
                raw16 = master['image'][idx[0][r], idx[1][r]]
                valid = face >= 0
                if valid[r].any() and strength > 0:
                    _none, NRM = _dn_geometry(face, ys, muv, None, CN)  # OIDN reads only the normal
                    isl = np.where(valid, island[np.maximum(face, 0)], -1)
                    out, g = oidn_isolated(lib, dev, v0, NRM, isl, n_islands)
                    groups = max(groups, g)
                    vb, okb = v0[r], valid[r]
                    res = np.where(okb, vb + strength * (np.clip(out[r], 0.0, 1.0) - vb), vb)
                    q = np.clip(np.rint(res * 65535.0), 0, 65535).astype(np.uint16)
                    q = np.where(okb, q, raw16)
                    n_px += int(okb.sum())
                    change += float(np.abs(res - vb)[okb].sum())
                else:
                    q = raw16
                w.write(np.ascontiguousarray(q[::-1]))  # file rows from the top
                if on_band is not None:
                    on_band(i + 1, nb)
            w.close()
        except BaseException:
            w.abort()
            raise
        os.replace(dst + '.tmp', dst)
        try:
            os.remove(other)
        except OSError:
            pass
    finally:
        master['close']()
        lib.oidnReleaseDevice(dev)
    return dict(method='OIDN', device=used, groups=groups, windows=nb, px=int(n_px),
                mean_change=round(change / max(n_px, 1), 6), seconds=round(time.time() - t0, 2))


def copy_master(pos, tris, uvpx, tisl, master, crop, k, padding=8, outside_mode='tri', kmax=16, surface_cos=None,
                same_face=False, ctx=None, chunk=COPY_CHUNK, soften=None, threads=None, fold_cos=None):
    """Returns (image (h,w) with -1 where nothing was written, info, owners (h,w), padding steps (h,w), stacked counts
    (h,w)). fold_cos (auto-bake decision 78): a padding pixel beyond an edge whose two faces' normals have a cosine
    under it (a sharp fold) continues its own face, not the neighbour hinged across (None: PADDING_FOLD_COS; -2: always
    the neighbour, the rule before decision 78). ctx: copy_context (computed here when None); chunk: the sub-samples of a
    block of inside pixels of one
    level (the result does not depend on it). master['image'], ['filled'] and ['face_map'] may be arrays or PagedArray
    views. soften: a soften_context, or None (decision 46: the darker side of convex sharp edges brightened toward the
    edge, inside and padding pixels; decision 58: concave folds blurred across).

    Apply-native-copy decision 6: the copy runs in C++ (ao_bake_copy) on `threads` threads (ao_bake_copy.threads_of):
    the band's raster (raster_window), the inside pixels' L x L sub-samples (each point on the pixel's own triangle, as
    Cycles mirrors jitter back into it) and their master reads (clamped onto the island's baked area; surface_cos: only
    texels of a face within that angle), Soften (the folds' values read the same way), the padding's dilation
    (dilate_ids) and reads (the pixel's own triangle, or its neighbour hinged flat across the nearest edge). It does
    outside_mode 'tri' without same_face, at most ao_bake_copy.MAX_LEVEL samples per pixel axis, on a uint16 master
    without a rect_id map; anything else raises (tisl, the target triangles' islands, mattered only for the other
    modes). info['copy'] is 'native', info['copy_threads'] the threads."""
    x0, y0, w, h = crop
    if ctx is None:
        ctx = copy_context(pos, tris, uvpx, master, k, kmax)
    nat = native_copy()
    if outside_mode != 'tri' or same_face or int(kmax) > nat.MAX_LEVEL:
        raise ValueError(f'a copy the C++ code does not do (outside_mode {outside_mode}, same_face {same_face}, '
                         f'kmax {kmax})')
    prep = nat.prepare(master, (PagedArray, _PagedView))
    if prep is None:
        raise MasterUnreadable('a master the C++ code does not read (not uint16, a rect_id map, or other arrays): '
                               're-bake needed')
    wt = ctx['wt']
    nb = ctx['nb']
    tri_normal = ctx['tri_normal']
    surface_read = surface_cos is not None and master.get('face_map') is not None
    owner_c, count_c = raster_window(uvpx, w, h, 1, x0, y0, threads=threads)
    out = np.full((h, w), -1.0)
    sig, kt_raw, kt = ctx['sig'], ctx['kt_raw'], ctx['kt']
    n_cl_in = 0
    jj, ii = np.nonzero(owner_c >= 0)
    lvl = kt[owner_c[jj, ii]]
    capped_px = int((kt_raw[owner_c[jj, ii]] > kmax).sum())
    gx = np.zeros(len(jj), np.int64)
    gy = np.zeros(len(jj), np.int64)
    for L in np.unique(lvl):
        at_level = np.nonzero(lvl == L)[0]
        # in square blocks whose sub-sample raster (the block's area x L x L) is at most `chunk`: the pixels of one
        # level may lie scattered over the whole window; each pixel gets the corner of its block's raster grid (the
        # box of the block's pixels), the grid its sub-samples' owners are rasterized on
        side = max(1, int(math.sqrt(chunk / (int(L) * int(L)))))
        key = (jj[at_level] // side) * (w // side + 1) + ii[at_level] // side
        order = np.argsort(key, kind='stable')
        cuts = np.flatnonzero(np.diff(key[order])) + 1
        idx = at_level[order]
        starts = np.concatenate([[0], cuts]).astype(np.int64)
        n_in = np.diff(np.append(starts, len(idx)))
        gx[idx] = x0 + np.repeat(np.minimum.reduceat(ii[idx], starts), n_in)
        gy[idx] = y0 + np.repeat(np.minimum.reduceat(jj[idx], starts), n_in)
    if len(jj):
        vals_in, n_cl_in = nat.inside(prep, tri_normal, surface_cos, surface_read, uvpx, x0 + ii, y0 + jj,
                                      owner_c[jj, ii], lvl, gx, gy, threads)
        out[jj, ii] = vals_in
        del vals_in
    soft_cos = SURFACE_COS if surface_cos is None else surface_cos
    n_soft = 0
    if soften is not None and len(jj):
        own = owner_c[jj, ii]
        cb = barycentric_many(np.stack([x0 + ii + 0.5, y0 + jj + 0.5], axis=1), uvpx[own])
        p3 = np.einsum('nk,nkd->nd', cb, pos[tris[own]])
        out[jj, ii], n_soft = nat.soften(prep, tri_normal, surface_cos, surface_read, soften, soft_cos, own, p3,
                                         out[jj, ii], threads)
    # padding pixels
    grown, steps = dilate_ids(owner_c, padding, threads=threads)
    pj, pi = np.nonzero((owner_c < 0) & (grown >= 0))
    n_cl_pad = 0
    n_no_nb = 0
    n_fold = 0
    if len(pi):
        T = grown[pj, pi]
        cen = np.stack([x0 + pi + 0.5, y0 + pj + 0.5], axis=1)
        bc_c = barycentric_many(cen, uvpx[T])
        kmin = np.argmin(bc_c, axis=1)
        U = nb[T, kmin]
        # the pixel's own triangle where it has no neighbour across that edge or its centre is not beyond that edge;
        # else the neighbour hinged flat across the edge, computed once per distinct (triangle, edge)
        flat = (U < 0) | (bc_c[np.arange(len(T)), kmin] >= 0)
        n_no_nb = int((U < 0).sum())
        # decision 78: beyond a sharp fold the neighbour's AO (another surface, e.g. a panel's top past a hole's wall)
        # is not this face's: texture filtering would blend it into the face's edge texels along the pixel staircase
        f_cos = PADDING_FOLD_COS if fold_cos is None else fold_cos
        has = np.nonzero(~flat)[0]
        fold = np.einsum('nd,nd->n', tri_normal[T[has]], tri_normal[U[has]]) < f_cos
        n_fold = int(fold.sum())
        flat[has[fold]] = True
        tri_uv = np.array(uvpx[T], dtype=np.float64)
        src = np.array(T, dtype=np.int64)
        hinge = np.nonzero(~flat)[0]
        if len(hinge):
            keys, inv = np.unique(T[hinge] * 3 + kmin[hinge], return_inverse=True)
            hinged = np.array([_hinged_uv(pos, tris, wt, uvpx, key // 3, key % 3, int(nb[key // 3, key % 3]))
                               for key in keys.tolist()]).reshape(-1, 3, 2)
            tri_uv[hinge] = hinged[inv.ravel()]
            src[hinge] = U[hinge]
        plvl = kt[T]
        vals_pad, n_cl_pad = nat.padding(prep, tri_normal, surface_cos, surface_read, x0 + pi, y0 + pj, src, tri_uv,
                                         plvl, threads)
        out[pj, pi] = vals_pad
        del vals_pad
        if soften is not None:
            # the padding pixel's point: its centre on the face it copies, clamped onto it
            bc = np.clip(barycentric_many(cen, tri_uv), 0, None)
            bc /= np.maximum(bc.sum(axis=1, keepdims=True), 1e-30)
            p3 = np.einsum('nk,nkd->nd', bc, pos[tris[src]])
            out[pj, pi], n_pad_soft = nat.soften(prep, tri_normal, surface_cos, surface_read, soften, soft_cos, src,
                                                 p3, out[pj, pi], threads)
            n_soft += n_pad_soft
    info = dict(k_min=k, k_max=kmax, k_levels={int(L): int((lvl == L).sum()) for L in np.unique(lvl)},
                px_at_k_cap=capped_px, footprint_px_median=float(np.median(sig)), footprint_px_max=float(sig.max()),
                inside_px=int(len(ii)), padding_px=int(len(pi)), clamped_inside_points=n_cl_in,
                clamped_padding_points=n_cl_pad, padding_without_neighbour=n_no_nb, padding_at_folds=n_fold,
                stacked_px=int((count_c > 1).sum()), softened_px=n_soft, copy='native',
                copy_threads=nat.threads_of(threads))
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
PADDING_FOLD_COS = SURFACE_COS  # decision 78: padding beyond a sharper fold continues its own face (copy_master)
K_MIN = 2
K_MAX = 16
SEEDS = (11, 12)  # core and skirt bakes
EXTRUSION = 2e-5  # m, selected-to-active from the target (step3_master.py)
RAY_DISTANCE = 4e-5


SPLIT_MIN = 4  # decision 49: the fewest samples a view gets when the samples are split


def view_samples(samples, n, split):
    """Decision 49: the samples of one view of n averaged views (poses, a shared mesh's copies): the sample count
    split over them (at least SPLIT_MIN) with Split Samples, else the full count."""
    if not split or n <= 1:
        return int(samples)
    return max(SPLIT_MIN, -(-int(samples) // int(n)))


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
# decision 50: a master of several views (poses, a shared mesh's copies) bakes every tile once per view, and much of a
# Cycles bake's time does not grow with the tile (Session 38, GPU: 2.2 s for a 0.8 Mpx tile, 2.8 s for 4 Mpx), so
# fewer, larger tiles are faster there: up to 8192 px when the budget allows
TILE_SIZES_VIEWS = (8192, 4096, 2048, 1024, 512)


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


def choose_tile(W, H, budget, in_use, views=1):
    """The largest tile size whose bake fits the budget: the whole master when it is not larger than the largest of
    TILE_SIZES and fits, else the largest of TILE_SIZES that fits; in_use: the process's working set before the
    master (Blender, the scene). The tile size is also the band's height (decision 33). views: how many bakes each
    tile gets (decision 50: more than one allows tiles up to 8192 px). Returns (size, estimate of the peak in bytes,
    fits)."""
    longest = max(W, H)
    table = TILE_SIZES_VIEWS if views > 1 else TILE_SIZES  # decision 50
    sizes = ([longest] if longest <= table[0] else []) + [s for s in table if s < longest]
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


# A master's thumbnail of 0.60.1 to 0.77.2 (auto-bake decision 43), no longer written or shown (OptiX baker decision
# 31: the master's layout is not the artist's UVs); still one of a master's files, so a rename moves it and a bake
# removes it.
THUMB_EXT = '.ao.thumb'


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


# The corner rule (decision 57): build_master places each island with the bottom of its rectangle on a row of pixel
# centres (+ 0.5), and the minimum-area rectangle has a side along an edge of the island's outline, so in every island
# at least one border edge runs through pixel centres. Such a pixel is baked from a point on the edge itself; at an
# inside corner (a concave fold) the other face's plane passes through that point and part of its rays escape: the
# console buttons (Session 41) had 6.6 % of their on-edge pixels at inside corners brighter than the pixel inward by
# over 0.05 (0.07 against 0.001 at one wall), against 1.3 % just inside; Apply's padding copied them into the texture
# as a light line. AO only darkens toward an inside corner, so along each island border edge across a concave fold the
# baked pixels of that face within CORNER_PX of the edge may not be brighter than the pixel one step inward by more than
# CORNER_EXCESS (well above the bake's noise): such a pixel takes the inward pixel's value. It runs in the composition,
# before the gutter is filled from the baked pixels, so the raw master (and Denoise after it) starts corrected.
CORNER_PX = 0.5
CORNER_EXCESS = 0.02
CORNER_RULE = 1  # in a master's index entry (corner_rule): its bake ran the rule (masters without it predate it)


def corner_pairs(m, pos, tris):
    """Decision 57: (cy, cx, iy, ix) int arrays sorted by cy: the pixels the corner rule checks and the pixel one step
    inward of each, from the layout m (muv, island, W, H) and the triangles' 3D corners pos[tris] (master order)."""
    muv, island = m['muv'], m['island']
    W, H = int(m['W']), int(m['H'])
    P = pos[tris]
    tn = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
    tn /= np.maximum(np.linalg.norm(tn, axis=1, keepdims=True), 1e-30)
    wt = weld_ids(pos)[tris]
    out = []
    for lst in edge_map(wt).values():
        if len(lst) < 2:
            continue
        for (t, i, j) in lst:
            if island[t] < 0:
                continue
            others = [(u, a, b) for (u, a, b) in lst if u != t]
            if all(island[u] == island[t] for u, _a, _b in others):
                continue  # an edge inside the island
            u, ui, uj = others[0]
            if float(tn[t] @ tn[u]) >= SURFACE_COS:
                continue  # not a fold
            a3 = P[t, i]
            if (P[u, 3 - ui - uj] - a3) @ tn[t] < 0 and (P[t, 3 - i - j] - a3) @ tn[u] < 0:
                continue  # convex: a rim brightens toward its edge for real
            A, B = muv[t, i], muv[t, j]
            e = B - A
            L = float(np.linalg.norm(e))
            if L < 1e-6:
                continue
            n = np.array([-e[1], e[0]]) / L
            if (muv[t, 3 - i - j] - A) @ n < 0:
                n = -n
            s = np.linspace(0.0, 1.0, int(L * 2) + 2)
            pts = A[None, :] + s[:, None] * e[None, :]
            base = np.floor(pts).astype(np.int64)
            cand = np.unique(np.concatenate([base + np.array([dx, dy]) for dx in (-1, 0, 1) for dy in (-1, 0, 1)]),
                             axis=0)
            c = cand + 0.5
            d = (c - A) @ n
            k = (d > -0.02) & (d < CORNER_PX)
            if not k.any():
                continue
            cand, c = cand[k], c[k]
            bc = barycentric_many(c, np.repeat(muv[t][None], len(c), axis=0))
            k = (bc[:, i] >= -1e-6) & (bc[:, j] >= -1e-6)  # within the edge's span (its own coordinate is d)
            cand, c = cand[k], c[k]
            inw = np.floor(c + n).astype(np.int64)
            k = ((cand[:, 0] >= 0) & (cand[:, 0] < W) & (cand[:, 1] >= 0) & (cand[:, 1] < H) & (inw[:, 0] >= 0)
                 & (inw[:, 0] < W) & (inw[:, 1] >= 0) & (inw[:, 1] < H))
            if k.any():
                out.append(np.stack([cand[k, 1], cand[k, 0], inw[k, 1], inw[k, 0]], axis=1))
    if not out:
        return tuple(np.zeros(0, np.int64) for _ in range(4))
    a = np.concatenate(out)
    a = a[np.argsort(a[:, 0], kind='stable')]
    return a[:, 0], a[:, 1], a[:, 2], a[:, 3]


def compose_layout(m):
    """The layout of master m as the C++ composition reads it (ao_bake_copy.Layout), made once per master."""
    return native_copy().compose_layout(m, FILL, int(CORNER_EXCESS * 65535))


def compose_by(threads=None):
    """Which code composes a master: 'C++ (n threads)' (the runner's log)."""
    n = native_copy().threads_of(threads)
    return f"C++ ({n} thread{'s' if n != 1 else ''})"


def compose_block(m, M16e, baked_e, ex0, ey0, win, threads=None, layout=None):
    """The composition of a master (step3_master.py) for one window, after the tiles around it are baked.

    M16e (eh, ew) uint16 and baked_e (eh, ew) bool: the core and skirt values and the baked flags (core or skirt) over
    the window and its halo of FILL pixels (clamped to the master), whose bottom-left pixel is (ex0, ey0). Decision 57
    first: the corner pixels (m['corner_pairs']) brighter than their inward pixel by over CORNER_EXCESS take its value.
    Inside each island's rectangle, the pixels within FILL steps of a baked pixel of the same rectangle get that
    pixel's value; the face map holds the face per pixel (core faces, then skirt faces inside rectangles, grown FILL
    steps inside rectangles). With the halo the result equals the composition of the whole image at once (Session 20),
    so a master is composed a strip at a time (Session 23). Returns (counts, values (h, w) uint16, filled (h, w) bool,
    face map (h, w) int32) of the window.

    Apply-native-copy decision 6: fss_ao_compose_block (bake-post-native journal) on `threads` threads. layout:
    compose_layout(m), when the caller made it once."""
    return native_copy().compose(layout if layout is not None else compose_layout(m), M16e, baked_e, ex0, ey0, win,
                                 threads)


def compose_whole(m, M16, baked, window=2048, threads=None):
    """The composition of a whole master held in memory (tests and small masters): (counts, values, filled, face map),
    window by window with compose_block (threads as compose_block takes them)."""
    H, W = M16.shape
    vals = np.zeros_like(M16)
    filled = np.zeros((H, W), bool)
    face = np.full((H, W), -1, np.int32)
    counts = {}
    layout = compose_layout(m)
    for win in tile_grid(W, H, window):
        x0, y0, w, h = win
        ex0, ey0 = max(0, x0 - FILL), max(0, y0 - FILL)
        ex1, ey1 = min(W, x0 + w + FILL), min(H, y0 + h + FILL)
        c, v, f, fm = compose_block(m, M16[ey0:ey1, ex0:ex1], baked[ey0:ey1, ex0:ex1], ex0, ey0, win, threads=threads,
                                    layout=layout)
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


def compose_band(m, bands, kb, write_rows, counts, on_strip=None, ys1=None, stop=None, threads=None, layout=None):
    """Composes band kb a strip of COMPOSE_STRIP rows at a time from the top (or from row ys1, where an earlier call
    stopped); write_rows(values, codes) gets each strip's rows in file order (the top first), on_strip(y0, values) each
    strip as composed (the preview). stop: the first row of the band below when that band is not baked yet: the strips
    whose halo reaches below it wait. Returns the top of the strips not composed (the band's first row when done).
    threads: compose_block's (each window's values and map codes go straight into the strip's rows); layout:
    compose_layout(m), made once by the caller."""
    W, H = m['W'], m['H']
    y0, _v, _b = bands.rows[kb]
    yb1 = y0 + bands.height[kb]
    ys1 = yb1 if ys1 is None else ys1
    if layout is None:
        layout = compose_layout(m)
    nat = native_copy()
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
            c, _wv, _wf, _wm = nat.compose(layout, Me, Be, ex0, ey0, (x0, ys0, w, hs), threads,
                                           out_values=vals[:, x0:x0 + w], out_code=codes[:, x0:x0 + w], parts=False)
            for k, n in c.items():
                counts[k] = counts.get(k, 0) + n
        write_rows(vals[::-1], codes[::-1])
        if on_strip is not None:
            on_strip(ys0, vals)
        ys1 = ys0
    return ys1


def bake_paged(m, tile, bake_tile, write_rows, counts, on_strip=None, threads=None):
    """A master baked and composed band by band (decision 33): the bands from the top (the files are written from the
    top), each band's tiles from the left. bake_tile(i, (x0, y0, w, h), values, baked) bakes tile i of tile_grid (its
    place gives its seed) into the band's views of that tile and is a generator (the runner yields between tiles).
    Once a band is baked, the last strips of the band above it (they needed its top rows) are composed and written,
    then this band's strips that do not reach the band below; only the rows the next strips still read are kept. So
    one band and a strip are held, whatever the master's height. Yields after each tile. threads: the composition's
    (compose_block; compose_by says how many)."""
    W, H = m['W'], m['H']
    tiles = tile_grid(W, H, tile)
    ntx, nb = -(-W // tile), -(-H // tile)
    bands = Bands(W)
    rest = {}  # band index: the top of its strips not composed yet
    kw = dict(threads=threads, layout=compose_layout(m))
    for kb in range(nb - 1, -1, -1):
        yb0 = kb * tile
        _y0, band_v, band_b = bands.add(kb, yb0, min(tile, H - yb0))
        for tx in range(ntx):
            i = kb * ntx + tx
            x0, y0, w, h = tiles[i]
            yield from bake_tile(i, tiles[i], band_v[:, x0:x0 + w], band_b[:, x0:x0 + w])
        del band_v, band_b
        if kb + 1 in rest:
            compose_band(m, bands, kb + 1, write_rows, counts, on_strip, ys1=rest.pop(kb + 1), **kw)
            bands.trim(kb + 1, FILL)  # the halo of this band's top strip
        bands.drop(kb + 2)
        ys1 = compose_band(m, bands, kb, write_rows, counts, on_strip, stop=yb0 if kb else None, **kw)
        if ys1 > yb0:
            rest[kb] = ys1
            bands.trim(kb, ys1 + FILL - yb0)  # the rows the band's last strips read

# ---------------------------------------------------------------------------------------------------------------------
# A master's files (decisions 18, 33 and 37): <stem>.ao.jxl, <stem>.ao.map, <stem>.ao.npz
# ---------------------------------------------------------------------------------------------------------------------
#
# <stem>.ao.jxl: the AO, 16-bit grey, lossless JPEG XL (decision 37, schema 3), encoded by ao_bake_jxl from the rows
#   handed from the top as a band is composed (through a raw scratch file, <stem>.ao.jxl.tmp.raw, deleted afterwards).
#   Masters of 0.55 and earlier, or baked without the library, have <stem>.ao.png instead (decision 18, as schemas 1
#   and 2 wrote it); the C++ code does not read those (apply-native-copy decision 6): Refresh grades them to be baked
#   again, Apply leaves their pixels white, and a new bake removes the .ao.png.
# <stem>.ao.map: the per-pixel data Apply reads besides the AO (Session 23; schema 1 kept them as `filled` and
#   `face_map` in the .npz): MAP_MAGIC, then the version, W and H as little-endian uint32, then one zlib stream of the
#   rows from the top, each W little-endian int32 codes: (face + 1) * 2 + filled, face -1 for none.
# <stem>.ao.npz: the layout, its size set by the triangles and islands, not by the pixels: muv, island, density, W, H,
#   rects, gutter, degenerate, tri_src, meta.

MAP_MAGIC = b'FSSAOMAP'
MAP_VERSION = 1


def image_paths(folder, stem, kind='ao'):
    """(jxl, png): the two names a master's image can have; kind 'ao', or 'curv' for its curvature (decision 54)."""
    base = os.path.join(folder, stem)
    return base + f'.{kind}.jxl', base + f'.{kind}.png'


def master_paths(folder, stem, kind='ao'):
    """(image, map, npz) of a master; image is its .ao.jxl, or its .ao.png when only that exists (a master of 0.55, or
    one baked without the JPEG XL library); kind 'curv': the curvature image of the same layout (decision 54)."""
    jx, pn = image_paths(folder, stem, kind)
    base = os.path.join(folder, stem)
    image = pn if (os.path.isfile(pn) and not os.path.isfile(jx)) else jx
    return image, base + '.ao.map', base + '.ao.npz'


def all_master_files(folder, stem):
    """Every file a master can have (for a rename): the AO's, and its material channels' (decision 79)."""
    base = os.path.join(folder, stem)
    return [base + ext for ext in ('.ao.jxl', '.ao.png', '.ao.map', '.ao.npz', THUMB_EXT, '.curv.jxl', '.curv.png',
                                   '.ao.raw.jxl', '.ao.raw.png')] + [p for g in CHANNEL_GROUPS
                                                                     for p in channel_paths(folder, stem, g)]


# Material channels (auto-bake decisions 79 to 83): a master's albedo, roughness, metal and emissive, baked from the
# object's material as Cycles shades it, one 16-bit grey JPEG XL image per component beside <stem>.ao.jxl in its
# layout (.ao.npz, .ao.map): <stem>.albedo_r.jxl and so on. Albedo and emissive sRGB-encoded (as their textures),
# roughness and metal linear.
CHANNEL_GROUPS = ('albedo', 'rough', 'metal', 'emis')
CHANNEL_KINDS = {'albedo': ('albedo_r', 'albedo_g', 'albedo_b'), 'rough': ('rough',), 'metal': ('metal',),
                 'emis': ('emis_r', 'emis_g', 'emis_b')}
CHANNEL_SRGB = {'albedo': True, 'rough': False, 'metal': False, 'emis': True}
CHANNEL_NAMES = {'albedo': 'Albedo', 'rough': 'Roughness', 'metal': 'Metal', 'emis': 'Emissive'}
CHANNEL_SAMPLES = 64  # Cycles samples per master pixel of a material channel, for a job without the setting


def channel_paths(folder, stem, group):
    """The images of a material channel group (decision 79): <stem>.<kind>.jxl per component."""
    base = os.path.join(folder, stem)
    return [base + f'.{k}.jxl' for k in CHANNEL_KINDS[group]]


def srgb_encode(linear):
    """Scene-linear values 0..1 as sRGB-encoded values 0..1 (the IEC 61966-2-1 curve Blender's sRGB space uses)."""
    x = np.clip(np.asarray(linear, dtype=np.float64), 0.0, 1.0)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1.0 / 2.4) - 0.055)


def srgb_decode(encoded):
    """sRGB-encoded values 0..1 as scene-linear values."""
    x = np.clip(np.asarray(encoded, dtype=np.float64), 0.0, 1.0)
    return np.where(x <= 0.04045, x / 12.92, np.power((x + 0.055) / 1.055, 2.4))


def write_layout(npz, m, tri_src, meta):
    """The layout file (.ao.npz) as MasterWriter.finish writes it."""
    with open(npz, 'wb') as f:
        np.savez_compressed(f, muv=m['muv'], island=m['island'], density=m['density'], W=m['W'], H=m['H'],
                            rects=m['rects'], gutter=m['gutter'], degenerate=m['degenerate'],
                            tri_src=np.asarray(tri_src, dtype=np.int64), meta=json.dumps(meta))


def same_layout(m, lay, atol=1e-6):
    """Decision 81: '' when the layout m built now equals the stored one (core._layout of an .ao.npz: the size, the
    islands and their rectangles equal, the master UVs within atol px), else what differs."""
    if (int(m['W']), int(m['H'])) != (int(lay['W']), int(lay['H'])):
        return f"{m['W']} x {m['H']} px, stored {lay['W']} x {lay['H']}"
    if not np.array_equal(np.asarray(m['island']), np.asarray(lay['island'])):
        return 'other islands'
    if not np.array_equal(np.asarray(m['rects']).reshape(-1, 4), np.asarray(lay['rects']).reshape(-1, 4)):
        return 'other island rectangles'
    d = float(np.abs(np.asarray(m['muv']) - np.asarray(lay['muv'])).max()) if len(m['muv']) else 0.0
    if not d <= atol:
        return f'master UVs differ by {d:.3g} px'
    return ''


class ChannelWriter:
    """One image of a master (a material channel's component, decision 79; or the AO), written row by row from the
    top as JPEG XL to a temporary name. map_mode 'write' (a new layout): the .ao.map from the rows' codes, and the
    .ao.npz at commit; 'check' (a kept layout, decision 81): the codes compared with the stored .ao.map, the pixels
    that differ counted in map_differs; None: the codes ignored. encode() closes the files, commit() puts them in
    place, abort() removes the temporary ones (the old files stay)."""

    def __init__(self, folder, stem, kind, W, H, threads=None, map_mode=None):
        base = os.path.join(folder, stem)
        lib = jxl()
        self.image = base + f'.{kind}.jxl'
        if not lib.available():
            raise lib.JxlError(f'{self.image}: the JPEG XL library is not loaded ({lib.error()})')
        self.map_path, self.npz = base + '.ao.map', base + '.ao.npz'
        self.map_mode, self.map_differs, self.W, self.H = map_mode, 0, int(W), int(H)
        self.stats = {}
        self.img = lib.Writer(self.image + '.tmp', W, H, threads=threads or lib.THREADS)
        self.map = None
        self._rows = self._buf = None
        try:
            if map_mode == 'write':
                self.map = map_writer(self.map_path + '.tmp', W, H, threads=threads)
            elif map_mode == 'check':
                mW, mH, self._rows = map_rows(self.map_path)
                if (mW, mH) != (self.W, self.H):
                    raise ValueError(f'{self.map_path}: {mW} x {mH} px, the master is {W} x {H}')
                self._pos = 0
        except BaseException:
            self.img.abort()
            raise

    def write_rows(self, values, codes):
        self.img.write(values)
        if self.map is not None:
            self.map.write(codes)
        elif self._rows is not None:
            n, k = codes.shape[0], 0
            while k < n:
                if self._buf is None or self._pos >= len(self._buf):
                    self._buf, self._pos = next(self._rows), 0
                take = min(n - k, len(self._buf) - self._pos)
                self.map_differs += int((self._buf[self._pos:self._pos + take] != codes[k:k + take]).sum())
                self._pos += take
                k += take

    def encode(self):
        self.img.close()
        self.stats = dict(format='jxl', **getattr(self.img, 'stats', {}))
        if self.map is not None:
            self.map.close()
        if self._rows is not None:
            self._rows.close()
            self._rows = None

    def commit(self, m=None, tri_src=None, meta=None):
        if self.map_mode == 'write':
            write_layout(self.npz + '.tmp', m, tri_src, meta)
            os.replace(self.map_path + '.tmp', self.map_path)
            os.replace(self.npz + '.tmp', self.npz)
        os.replace(self.image + '.tmp', self.image)
        self.stats['bytes'] = os.path.getsize(self.image)

    def abort(self):
        self.img.abort()
        if self.map is not None:
            self.map.abort()
        if self._rows is not None:
            self._rows.close()
            self._rows = None
        for p in (self.npz + '.tmp',):
            try:
                os.remove(p)
            except OSError:
                pass


def bake_paged_multi(m, tile, n, bake_tile, write_rows, threads=None):
    """bake_paged for n images of one layout (a master's material channel components, decision 79): each tile baked
    once into the n bands' views of it (bake_tile(i, rect, values [n], baked [n]), a generator), each image composed
    and written by its own write_rows[c], without the corner rule (decision 57 is the AO's). Yields after each tile.
    Returns the composition's counts of each image."""
    W, H = m['W'], m['H']
    tiles = tile_grid(W, H, tile)
    ntx, nb = -(-W // tile), -(-H // tile)
    bands = [Bands(W) for _ in range(n)]
    rest = [dict() for _ in range(n)]
    counts = [dict() for _ in range(n)]
    kw = dict(threads=threads, layout=compose_layout(dict(m, corner_pairs=None)))
    for kb in range(nb - 1, -1, -1):
        yb0 = kb * tile
        views = [b.add(kb, yb0, min(tile, H - yb0)) for b in bands]
        for tx in range(ntx):
            i = kb * ntx + tx
            x0, y0, w, h = tiles[i]
            yield from bake_tile(i, tiles[i], [v[1][:, x0:x0 + w] for v in views], [v[2][:, x0:x0 + w] for v in views])
        del views
        for c in range(n):
            if kb + 1 in rest[c]:
                compose_band(m, bands[c], kb + 1, write_rows[c], counts[c], None, ys1=rest[c].pop(kb + 1), **kw)
                bands[c].trim(kb + 1, FILL)
            bands[c].drop(kb + 2)
            ys1 = compose_band(m, bands[c], kb, write_rows[c], counts[c], None, stop=yb0 if kb else None, **kw)
            if ys1 > yb0:
                rest[c][kb] = ys1
                bands[c].trim(kb, ys1 + FILL - yb0)
    return counts


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


def map_writer(path, W, H, threads=None):
    """The .ao.map's writer, ao_bake_copy.MapWriter (C++, compressed beside the composition; blocks of int32 rows in
    file order, close, abort); `by` says 'C++ (n threads)'."""
    return native_copy().MapWriter(path, W, H, level=1, threads=threads)


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
    temporary ones (a cancelled bake keeps the old master). The AO is JPEG XL (decision 37; apply-native-copy decision
    6: libjxl is required, a JxlError without it). The map's writer is map_writer's (C++; `map.by`)."""

    def __init__(self, folder, stem, W, H, threads=None):
        jx, pn = image_paths(folder, stem)
        base = os.path.join(folder, stem)
        lib = jxl()
        if not lib.available():
            raise lib.JxlError(f'{jx}: the JPEG XL library is not loaded ({lib.error()})')
        self.format = 'jxl'
        self.image, self.other = jx, pn
        self.paths = (self.image, base + '.ao.map', base + '.ao.npz')
        self.stats = {}
        self.img = lib.Writer(self.image + '.tmp', W, H, threads=threads or lib.THREADS)
        try:
            self.map = map_writer(self.paths[1] + '.tmp', W, H, threads=threads)
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


REBAKE = 're-bake needed'


class MasterUnreadable(ValueError):
    """A master the C++ code does not read (apply-native-copy decision 6: a PNG image, schema 1 with its maps in the
    .npz, a rect_id map, values not uint16): it has to be baked again."""


def master_unreadable(folder, stem, kind='ao'):
    """Why the master (kind 'ao', 'curv' or 'ao.raw') is one the C++ code does not read, ending in REBAKE, or None:
    its image is a .png (0.55 and earlier, or baked without libjxl) or its .npz holds the maps (schema 1)."""
    image, _mp, npz = master_paths(folder, stem, kind)
    if image.endswith('.png') and os.path.isfile(image):
        return f'{os.path.basename(image)} is a PNG master: {REBAKE}'
    if os.path.isfile(npz) and has_maps_in_npz(npz):
        return f'{os.path.basename(npz)} is a master of schema 1: {REBAKE}'
    return None


def load_master(folder, stem, kind='ao'):
    """The whole master in memory as copy_master reads it (the image as uint16, 0..65535; filled, the face map; the
    island rectangles instead of a per-pixel map), or None when a file is missing. For tests and small masters: Apply
    reads a master paged (open_master). kind 'curv': its curvature image instead of the AO (decision 54). Raises
    MasterUnreadable for a master the C++ code does not read (master_unreadable)."""
    image, mp, npz = master_paths(folder, stem, kind)
    if not (os.path.isfile(image) and os.path.isfile(npz) and os.path.isfile(mp)):
        return None
    why = master_unreadable(folder, stem, kind)
    if why:
        raise MasterUnreadable(why)
    with np.load(npz) as z:
        out = _layout(z)
    img = read_image(image)
    H, W = img.shape
    out.update(image=img, W=W, H=H)
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
        self._map = None

    def address(self):
        """The address of the whole scratch file memory-mapped read-only, for the C++ copy (ao_bake_copy), which reads
        its tiles there; unmapped by close()."""
        if self._map is None:
            import mmap
            size = self.ntx * (-(-self.shape[0] // self.T)) * self.T * self.T * self.dtype.itemsize
            mm = mmap.mmap(self.f.fileno(), 0, access=mmap.ACCESS_READ)
            if len(mm) < size:
                mm.close()
                raise ValueError(f'{self.path}: {len(mm)} bytes, the tiles need {size}')
            self._map = (mm, np.frombuffer(mm, np.uint8))
        return self._map[1].ctypes.data

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
                if self._map is not None:  # mapped for the C++ copy: read there, not through the file (a file read
                    # waited for the C++ opening's mapped pages still being written to a hard disk, Session 6)
                    self.cache[s] = self._map[1][tid * size:(tid + 1) * size].view(self.dtype)
                else:
                    self.f.seek(tid * size)
                    self.f.readinto(memoryview(self.cache[s]).cast('B'))
                self.tile_in[s] = tid
                self.slot_of[tid] = s
                self.loads += 1
        self.used[self.slot_of[need]] = self.clock

    def close(self):
        if self._map is not None:
            mm = self._map[0]
            self._map = None  # the array over the mapping goes first, then the mapping can close
            mm.close()
        self.f.close()


class _PagedView:
    """A decoded view of a PagedArray (the map codes as filled or as faces)."""

    def __init__(self, base, decode, dtype):
        self.base, self.decode, self.dtype, self.shape = base, decode, np.dtype(dtype), base.shape

    def __getitem__(self, key):
        return self.decode(self.base[key])


def open_master(folder, stem, cache_bytes=PAGE_CACHE_BYTES, kind='ao', threads=None, map_page=None):
    """The master paged (decision 33), or None when a file is missing: the AO image (JPEG XL) and the map decoded once
    into two tiled scratch files in the bake folder (<stem>.ao.page and <stem>.ao.mappage) by the C++ DLL
    (ao_bake_copy.open_pages, apply-native-copy journal Session 4; threads: the bake's Threads setting,
    ao_bake_copy.threads_of), read through a cache of tiles; close() closes and deletes them. out['open'] says
    'C++ (n threads)'. Raises MasterUnreadable for a master the C++ code does not read (master_unreadable: a PNG
    image, schema 1; decision 6) and JxlError without libjxl."""
    image, mp, npz = master_paths(folder, stem, kind)
    if not (os.path.isfile(image) and os.path.isfile(npz) and os.path.isfile(mp)):
        return None
    why = master_unreadable(folder, stem, kind)
    if why:
        raise MasterUnreadable(why)
    with np.load(npz) as z:
        out = _layout(z)
    W, H = out['W'], out['H']
    base = os.path.join(folder, stem)
    # map_page: the map's page file's ending, so several images of one master can be open at once (decision 82)
    page_img, page_map = base + f'.{kind}.page', base + (map_page or '.ao.mappage')
    lib = jxl()
    if not lib.available():
        raise lib.JxlError(f'{image}: the JPEG XL library is not loaded ({lib.error()})')
    nat = native_copy()
    # both page files written by the DLL; on an error it removes them itself
    native = nat.open_pages(lib.LIB_DIR, image, mp, page_img, page_map, W, H, PAGE_TILE, threads)
    n = nat.threads_of(threads)
    out.update(open=f"C++ ({n} thread{'s' if n != 1 else ''})", open_stats=native,
               decode_open_tile_rows=native['most_open_tile_rows'])
    try:
        img = PagedArray(page_img, H, W, np.uint16, cache_bytes // 3)
        code = PagedArray(page_map, H, W, np.int32, cache_bytes - cache_bytes // 3)
    except BaseException:
        for p in (page_img, page_map):
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


def mesh_hash(ev, threads=None):
    """Mesh changed (decision 17): the evaluated triangles, their positions and their corner normals, object space:
    the first 20 hex digits of the SHA-1 of the triangles as int32, the positions as float32 and the corner normals
    rounded to 4 decimals (np.round(x, 4) + 0.0) as float32, computed by the C++ DLL (bake-post-native journal Session
    5: the bytes and digests of the Python code it replaced)."""
    return native_copy().mesh_hash(ev['tris'], ev['co'], ev['cn'], threads)[:20]


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


# ---------------------------------------------------------------------------------------------------------------------
# PNG files (rows bottom-up, as Blender images)
# ---------------------------------------------------------------------------------------------------------------------

COLOUR_TYPE = {1: 0, 2: 4, 3: 2, 4: 6}  # channels: PNG colour type
CHANNELS = {0: 1, 4: 2, 2: 3, 6: 4}


def write_png_int(path, q, bits=16, rows=256, threads=None):
    """q: (H, W) or (H, W, C) integers in the file's depth, row 0 = bottom, written by png_writer (C++) `rows` at a
    time, so no copy of the whole image is made."""
    q = np.asarray(q)
    h, w = q.shape[:2]
    ch = 1 if q.ndim == 2 else q.shape[2]
    writer = png_writer(path, w, h, bits, ch, threads=threads)
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


def png_writer(path, w, h, bits=16, channels=1, threads=None):
    """A PNG written row by row (blocks of rows in file order, the top first; close, abort): the C++ writer
    (ao_bake_copy.PngWriter, apply-native-copy journal decisions 4 and 6: filter 0, zlib level 6, the compression on
    `threads` threads). Its `by` says 'C++ (n threads)'."""
    return native_copy().PngWriter(path, w, h, bits, channels, threads)


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
    """A PNG the C++ reader does not decode (not a PNG header, a palette, interlace, another depth): read it through
    Blender."""


def read_png(path, threads=None, how=None):
    """(values (H, W) or (H, W, C) uint16 in the file's depth, row 0 = bottom, bits, colour type), read by the C++
    reader (ao_bake_copy.read_png: grey, grey + alpha, RGB and RGBA at 8 or 16 bits, every filter; a truncated or
    corrupt file raises its PngError, an OSError). A file it does not read (not a PNG header, a palette, interlace,
    another depth) raises PngNotDecoded. how (a dict): gets 'read', 'C++ (n threads)'."""
    nat = native_copy()
    info = png_info(path)
    if info is None:
        if not os.path.isfile(path):
            raise FileNotFoundError(path)
        raise PngNotDecoded(f'{path}: not a PNG header')
    w, h, bits, ct, il = info
    if ct not in CHANNELS or bits not in (8, 16) or il:
        raise PngNotDecoded(f'{path}: colour type {ct}, {bits} bits, interlace {il}: not read by the C++ reader')
    try:
        vals, _st = nat.read_png(path, w, h, CHANNELS[ct], bits, threads)
    except nat.PngUnsupported as exc:
        raise PngNotDecoded(str(exc)) from exc
    if how is not None:
        n = 2 if nat.threads_of(threads) > 1 else 1
        how['read'] = f"C++ ({n} thread{'s' if n != 1 else ''})"
    return (vals[:, :, 0] if vals.shape[2] == 1 else vals), bits, ct


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


def island_labels(uv_px_by_mesh, W, H, padding, threads=None):
    """Island label per pixel of a W x H image for the triangles of several meshes [(uv_px (T,3,2), island (T,))],
    grown into the padding (8-neighbour steps, the nearest island wins). -1 where no island reaches.

    Apply-native-copy decision 6: the raster and the dilation in C++ (fss_ao_copy_raster_ids writing each mesh's
    labels into the image, fss_ao_copy_dilate) on `threads` threads."""
    nat = native_copy()
    owner = np.full((H, W), -1, dtype=np.int64)
    base = 0
    for uvpx, isl in uv_px_by_mesh:
        isl = np.asarray(isl, np.int64)
        nat.raster_ids(uvpx, W, H, 1, 0, 0, select=False, threads=threads, label=base + isl, owner=owner,
                       count=False)
        base += int(isl.max()) + 1 if len(isl) else 0
    return nat.dilate(owner, int(padding), None, threads)[0]

