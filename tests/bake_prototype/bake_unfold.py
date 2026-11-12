"""The master layout of the bake prototype (P1 islands by unfolding, P2 skirt, P3 density), plain numpy.

Islands (P1): every triangle is laid flat with its exact edge lengths. A join across an edge hinges one island flat
onto the other (a rotation, with a reflection if the winding needs it, and a translation), so every triangle keeps its
exact shape. A join is refused only when triangles would overlap. A vertex may get a second position in an island: it
then lies on the border in both places (a cut, as along the seam of an unrolled cylinder); a vertex can end up inside
an island only when its fan closes, that is when its angles add up to 360 degrees. No angle limit. The same mesh
always gives the same islands. Join orders (Islands.build):
- 'growlen' (used): an island grows from the largest free triangle, the free neighbour across the longest shared
  edge first (the smaller fold on ties), until nothing more joins; then the next island;
- 'grow': as 'growlen', the smallest fold first;
- 'fold' / 'length' / 'bucket': all edges at once (Kruskal), by fold, by length, or by 15 degree fold steps.
On the knob, 'fold' hinges the side faces one by one onto a 15 degree bevel ring (petals, 21 of 40 side
edges continuous); 'growlen' unrolls the side as one strip (39 of 40 continuous, one cut).

Skirt (P2): for each border edge of an island, the neighbour triangle across that edge in 3D (the one with the
smallest fold if there are several) is hinged flat onto the edge and clipped to a band of (gutter + 1) px outside the
edge. The clipped pieces keep their exact 3D positions (affine in the hinged triangle), so a bake of them reads the
real neighbour surface. Pixels beyond corners are filled later from the nearest baked pixel.

P18 (build_master fold_split): islands are not joined across folds over the limit, and such split edges get the face
itself mirrored as the skirt (as mirror_open does at open edges).
"""
import math

import numpy as np

import bake_geom as bg


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
        self.w = bg.weld_ids(pos)
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
        self.edges = bg.edge_map(self.wt)
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
            if bg.tri_areas_2d(qa[None, [0, 1, 2]])[0] < 0:
                quad = quad[::-1]
            poly = _clip([tri2[0], tri2[1], tri2[2]] if bg.tri_areas_2d(tri2[None])[0] > 0
                         else [tri2[0], tri2[2], tri2[1]], quad)
            if len(poly) < 3:
                continue
            poly = np.array(poly)
            bcs = bg.barycentric(poly, tri2[0], tri2[1], tri2[2])
            if bcs is None:
                continue
            p3 = bcs @ P3
            nn = bcs @ cn[u]
            nn /= np.linalg.norm(nn, axis=1, keepdims=True)
            for k in range(1, len(poly) - 1):
                idx = [0, k, k + 1]
                if abs(bg.tri_areas_2d(poly[None, idx])[0]) < 1e-9:
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
    owner, count = bg.rasterize_ids(m['muv'][core], m['W'], m['H'], eps=-1e-7)
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
