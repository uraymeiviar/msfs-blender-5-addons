"""Placing UV islands on a raster, into the free space between and inside each other (numpy only, no bpy): the layout
uv_pack tries next to Blender's Pack Islands.

Blender's Pack Islands leaves free space inside closed shapes and beside large islands: on the E2 cockpit (material
MAT_STD_COCKPIT_FRONT, 1243 islands) 11.3 % of its layout is empty and enclosed and 30.5 % open and empty. The raster
sees every island as it is: the cells its triangles touch. An island may go wherever its footprint, grown by the gap to
its neighbours, covers no occupied cell; inside a ring as well as beside it. Footprints are conservative (every cell a
triangle touches) and the growth counts the distance between cells, so a position found here keeps the gap for any two
points of two islands, whatever the triangles look like (needles included). Islands only move and turn in steps of 90
degrees (or not at all); their scale never changes. The result is deterministic: no random numbers, stable sorts.

The islands are taken largest first; each goes where the layout grows least, within that into an island's enclosed
space first, then where it touches its neighbours most, then nearest the origin.
"""

import math

import numpy as np

BLOCK = 16  # cells per side of the blocks that prune the search
CHUNK = 128  # blocks searched at a time
LEVELS = (2, 4, 8, 16, 32, 64)  # sides of the free squares the search keeps maps of
MIN_CELLS = 128  # raster cells per side at least (twice the largest level)
MAX_CELLS = 4096  # raster cells per side at most (about 170 MB of tables)
CELLS_PER_SIDE = 2700  # raster cells over the expected layout's side; at 2.7 px per cell, 8.1 px of gap are 3 cells
MIN_CELLS_PER_SIDE = 100  # however large the gap, an island is not rasterised coarser than this
MAX_CELLS_PER_GAP = 8  # a finer raster than this is not needed: small sets of tiny islands, 1 px per cell at 8 px
RING_SAMPLES = 200  # cells around a mask counted for the contact with its neighbours
TOUCH_STEPS = 4  # contact counts in quarters of the ring; within a quarter the position nearest the origin wins
MAX_CANDIDATES = 2048  # positions compared by contact
# Which island first: bounding box area to this power x real area to 1 - this power. A smaller power uses enclosed space
# better, a larger one gives the smaller layout. Measured on MAT_STD_COCKPIT_FRONT at 2.7 px per cell (k, enclosed empty
# space): 1: 1.540, 5.4 %; 0.8: 1.539, 4.8 %; 0.75: 1.551, 4.7 %; 0.5: 1.567, 4.1 %; 0: 1.586, 3.6 %
BOX_POWER = 0.8


def spans(T):
    """Per row of cells, the cells each triangle of T (n, 3, 2; x, y in cells, not negative) touches: returns (row,
    first x, last x), one entry per triangle and row. Lines and points count too: a triangle's span in a row is the
    span of its three edges clipped to that row, which holds for any triangle, degenerate or not."""
    A = T.reshape(-1, 2)
    B = np.roll(T, -1, axis=1).reshape(-1, 2)
    tri = np.repeat(np.arange(len(T)), 3)
    swap = A[:, 1] > B[:, 1]
    P = np.where(swap[:, None], B, A)
    R = np.where(swap[:, None], A, B)
    r0 = np.floor(P[:, 1]).astype(np.int64)
    r1 = np.floor(R[:, 1]).astype(np.int64)
    count = r1 - r0 + 1
    e = np.repeat(np.arange(len(P)), count)
    rows = r0[e] + np.arange(len(e)) - (np.cumsum(count) - count)[e]
    dy = (R - P)[:, 1][e]
    dx = (R - P)[:, 0][e]
    py, px = P[e, 1], P[e, 0]
    flat = dy <= 1e-12
    slope = np.where(flat, 0.0, dx / np.where(flat, 1.0, dy))
    xa = px + (np.maximum(py, rows) - py) * slope
    xb = np.where(flat, px + dx, px + (np.minimum(py + dy, rows + 1.0) - py) * slope)
    # rounding must not take a span outside its edge
    lo = np.floor(np.maximum(np.minimum(xa, xb), np.minimum(px, px + dx))).astype(np.int64)
    hi = np.floor(np.minimum(np.maximum(xa, xb), np.maximum(px, px + dx))).astype(np.int64)
    # one span per triangle and row
    width = int(rows.max()) + 2
    key = tri[e] * width + rows
    order = np.argsort(key, kind='stable')
    key = key[order]
    first = np.flatnonzero(np.concatenate([[True], key[1:] != key[:-1]]))
    return key[first] % width, np.minimum.reduceat(lo[order], first), np.maximum.reduceat(hi[order], first)


def reach_table(gap_cells):
    """Per row distance dy, how many cells to each side a footprint must grow so that two footprints not touching
    are at least gap_cells apart. Two cells dx and dy apart are at least hypot(dx - 1, dy - 1) cells apart."""
    table = []
    dy = 0
    while max(dy - 1, 0) < gap_cells:
        h = max(dy - 1, 0)
        table.append(int(math.ceil(math.sqrt(max(gap_cells * gap_cells - h * h, 0.0)))))
        dy += 1
    return table


def solid_mask(rows, x0, x1):
    """The cells of spans as a boolean array."""
    w = int(x1.max()) + 1
    diff = np.zeros((int(rows.max()) + 1, w + 1), np.int32)
    np.add.at(diff, (rows, x0), 1)
    np.add.at(diff, (rows, x1 + 1), -1)
    return np.cumsum(diff, axis=1)[:, :w] > 0


def grown_mask(solid, reach):
    """A mask grown by the reach table; its (0, 0) is the solid mask's (-pad, -pad). Returns (mask, pad)."""
    r, s, n = runs_of(solid)
    pad = max(len(reach) - 1, reach[0])
    h, w = solid.shape[0] + 2 * pad, solid.shape[1] + 2 * pad
    diff = np.zeros((h, w + 1), np.int32)
    for dy in range(-(len(reach) - 1), len(reach)):
        grow = reach[abs(dy)]
        np.add.at(diff, (r + dy + pad, s - grow + pad), 1)
        np.add.at(diff, (r + dy + pad, s + n + grow + pad), -1)
    return np.cumsum(diff, axis=1)[:, :w] > 0, pad


def runs_of(mask):
    """The runs of True per row of a mask: (row, first cell, length). The rows are spread: 0, then the middle, then
    the quarters..., so that the search rejects a position after few of them."""
    edge = np.diff(np.pad(mask, ((0, 0), (1, 1))).astype(np.int8), axis=1)
    r, s = np.nonzero(edge == 1)
    _r, e = np.nonzero(edge == -1)
    n = e - s
    r1 = r + 1
    order = np.lexsort((-n, -(r1 & -r1)))
    return r[order], s[order], n[order]


def probe_of(mask):
    """The largest level (a side of LEVELS) of a square that the mask contains, and where: (side, y, x)."""
    best = (LEVELS[0], 0, 0)
    cur = mask
    for level in LEVELS:
        half = level // 2
        if min(cur.shape) <= half:
            break
        nxt = cur[:-half, :-half] & cur[half:, :-half] & cur[:-half, half:] & cur[half:, half:]
        where = int(np.argmax(nxt))
        if not nxt.flat[where]:
            break
        cur = nxt
        best = (level, *np.unravel_index(where, cur.shape))
    return best


def ring_of(mask):
    """Cells just outside a mask (a sample of them), relative to its (0, 0): (rows, columns)."""
    wide = np.pad(mask, 1)
    grown = wide.copy()
    grown[1:] |= wide[:-1]
    grown[:-1] |= wide[1:]
    grown[:, 1:] |= wide[:, :-1]
    grown[:, :-1] |= wide[:, 1:]
    ry, rx = np.nonzero(grown & ~wide)
    step = max(len(ry) // RING_SAMPLES, 1)
    return ry[::step] - 1, rx[::step] - 1


def turned(P, turns):
    """Points P (.., 2) turned by turns x 90 degrees counter-clockwise."""
    turns %= 4
    if turns == 0:
        return P
    if turns == 1:
        return np.stack([-P[..., 1], P[..., 0]], -1)
    if turns == 2:
        return -P
    return np.stack([P[..., 1], -P[..., 0]], -1)


class Shape:
    """An island at one turn, in cells: its footprint, the footprint grown by the gap with the tables of the search,
    and the point of the turned island at the footprint's (0, 0) (low, in pixels)."""

    def __init__(self, local, turn, cell, reach):
        T = turned(local, turn)
        self.turn = turn
        self.low = T.reshape(-1, 2).min(0)
        self.solid = solid_mask(*spans((T - self.low) / cell))
        self.inner_h, self.inner_w = self.solid.shape
        self.mask, self.pad = grown_mask(self.solid, reach)
        self.runs = runs_of(self.mask)
        self.probe = probe_of(self.mask)
        self.ring = ring_of(self.mask)


class Grid:
    """The occupied cells of a square raster with the tables of the search: per cell, the free cells from it to the
    right, and for each level whether a free square of that side starts there; per block a summary of these. The cells
    enclosed by an island are kept too, so that smaller islands go there first."""

    def __init__(self, cells):
        self.cells = c = (int(cells) // BLOCK + 1) * BLOCK
        self.blocks = b = c // BLOCK
        self.occ = np.zeros((c, c), bool)
        self.run = np.tile(c - np.arange(c, dtype=np.int16), (c, 1))
        self.free_sq = {}
        self.sq_blocks = {}
        self.sq_any = {}
        for level in LEVELS:
            square = np.zeros((c, c), bool)
            square[:c - level + 1, :c - level + 1] = True
            self.free_sq[level] = square
            self.sq_blocks[level] = square.reshape(b, BLOCK, b, BLOCK).transpose(0, 2, 1, 3)
            self.sq_any[level] = self.sq_blocks[level].any(axis=(2, 3))
        self.occ_blocks = self.occ.reshape(b, BLOCK, b, BLOCK).transpose(0, 2, 1, 3)
        self.hole =np.zeros((c, c), bool)
        self.hole_blocks = self.hole.reshape(b, BLOCK, b, BLOCK).transpose(0, 2, 1, 3)
        self.hole_count = np.zeros((b, b), np.int32)

    def paint(self, mask, y, x):
        """Occupy a mask's cells with its (0, 0) at cell (y, x), inside the grid, and update the tables."""
        h, w = mask.shape
        self.occ[y:y + h, x:x + w] |= mask
        c = self.cells
        xs = np.arange(x + w)
        at = np.where(self.occ[y:y + h, :x + w], xs, c)
        # beyond the window the next occupied cell stays as it was
        tail = np.full(h, c) if x + w >= c else (x + w) + self.run[y:y + h, x + w]
        at = np.concatenate([at, tail[:, None]], axis=1)
        self.run[y:y + h, :x + w] = (np.minimum.accumulate(at[:, ::-1], axis=1)[:, :0:-1] - xs).astype(np.int16)
        below = ~self.occ
        half = 1
        for level in LEVELS:
            y0, x0 = max(y - level + 1, 0), max(x - level + 1, 0)
            y1, x1 = min(y + h, c - level + 1), min(x + w, c - level + 1)
            if y1 > y0 and x1 > x0:
                self.free_sq[level][y0:y1, x0:x1] = (below[y0:y1, x0:x1] & below[y0 + half:y1 + half, x0:x1]
                                                     & below[y0:y1, x0 + half:x1 + half]
                                                     & below[y0 + half:y1 + half, x0 + half:x1 + half])
                by0, by1 = y0 // BLOCK, (y1 - 1) // BLOCK + 1
                bx0, bx1 = x0 // BLOCK, (x1 - 1) // BLOCK + 1
                self.sq_any[level][by0:by1, bx0:bx1] = self.sq_blocks[level][by0:by1, bx0:bx1].any(axis=(2, 3))
            below = self.free_sq[level]
            half = level
        # the island's own enclosed cells: free cells with the island in all four directions
        hole = (np.logical_or.accumulate(mask, 1) & np.logical_or.accumulate(mask[:, ::-1], 1)[:, ::-1]
                & np.logical_or.accumulate(mask, 0) & np.logical_or.accumulate(mask[::-1], 0)[::-1] & ~mask)
        if hole.any():
            self.hole[y:y + h, x:x + w] |= hole
        by0, by1 = y // BLOCK, (y + h - 1) // BLOCK + 1
        bx0, bx1 = x // BLOCK, (x + w - 1) // BLOCK + 1
        self.hole_count[by0:by1, bx0:bx1] = (self.hole_blocks[by0:by1, bx0:bx1]
                                             & ~self.occ_blocks[by0:by1, bx0:bx1]).sum(axis=(2, 3))

    def find(self, shape, extent, start):
        """The best position of a Shape: (the layout's side with it, y, x of its mask, inside an enclosed space,
        contact with its neighbours), or None when nothing fits. extent: the layout's side in cells so far; start: the
        first cell a footprint may start in."""
        r, s, n = shape.runs
        side, py, px = shape.probe
        p = shape.pad
        h, w = shape.mask.shape
        hits = np.argwhere(self.sq_any[side])
        if len(hits) == 0:
            return None
        by, bx = hits[:, 0], hits[:, 1]
        cost = np.maximum(np.maximum(by * BLOCK - py + shape.inner_h + p, bx * BLOCK - px + shape.inner_w + p), extent)
        order = np.lexsort((by + bx, self.hole_count[by, bx] == 0, cost))
        best = None
        for c in range(0, len(order), CHUNK):
            pick = order[c:c + CHUNK]
            if best is not None and cost[pick[0]] >= best[0]:
                break
            q, iy, ix = np.nonzero(self.sq_blocks[side][by[pick], bx[pick]])
            y = by[pick][q] * BLOCK + iy - py
            x = bx[pick][q] * BLOCK + ix - px
            keep = (y + p >= start) & (x + p >= start) & (y + h <= self.cells) & (x + w <= self.cells)
            y, x = y[keep], x[keep]
            for i in range(len(r)):
                if len(y) == 0:
                    break
                keep = self.run[y + r[i], x + s[i]] >= n[i]
                y, x = y[keep], x[keep]
            if len(y) == 0:
                continue
            grown = np.maximum(np.maximum(y + p + shape.inner_h, x + p + shape.inner_w), extent)
            lowest = int(grown.min())
            m = np.flatnonzero(grown == lowest)
            if len(m) > MAX_CANDIDATES:
                m = m[::len(m) // (MAX_CANDIDATES // 2)]
            yy, xx = y[m], x[m]
            ry, rx = shape.ring
            touch = self.occ[np.clip(yy[:, None] + ry, 0, self.cells - 1),
                             np.clip(xx[:, None] + rx, 0, self.cells - 1)].sum(1)
            inside = self.hole[yy + p + shape.inner_h // 2, xx + p + shape.inner_w // 2]
            j = np.lexsort((xx, yy + xx, -(touch * TOUCH_STEPS // max(len(ry), 1)), ~inside))[0]
            if best is None or lowest < best[0]:
                best = (lowest, int(yy[j]), int(xx[j]), bool(inside[j]), int(touch[j]))
            if lowest <= extent:
                break
        return best


def cell_size(side, gap):
    """Pixels per raster cell for a layout of about this side. When the gap is a whole number of cells, the islands
    come to the gap exactly, without a part of a cell to spare."""
    cell = max(side / CELLS_PER_SIDE, min(gap / MAX_CELLS_PER_GAP, side / MIN_CELLS_PER_SIDE))
    return gap / math.ceil(gap / cell) if cell < gap else cell


def _place_once(tri, order_t, start_t, lo, order, can_turn, gap, cell, side):
    reach = reach_table(round(gap / cell, 6))
    shift = max(len(reach) - 1, reach[0]) + 1  # a grown footprint must not start below the raster
    first = shift + int(math.ceil(0.5 * gap / cell))  # half the gap to the layout's edge
    grid = Grid(max(int(side / cell) + 2 * shift + BLOCK, MIN_CELLS))
    extent = shift
    turns = {}
    offset = {}
    for i in order:
        local = tri[order_t[start_t[i]:start_t[i + 1]]] - lo[i]
        best = None
        for t in ((0, 1) if can_turn[i] else (0,)):
            shape = Shape(local, t, cell, reach)
            pos = grid.find(shape, extent, first)
            if pos is None:
                continue
            key = (pos[0], not pos[3], -pos[4] / max(len(shape.ring[0]), 1), pos[1] + pos[2], t)
            if best is None or key < best[0]:
                best = (key, shape, pos)
        if best is None:
            return None
        _key, shape, (extent, y, x, _inside, _touch) = best
        grid.paint(shape.solid, y + shape.pad, x + shape.pad)
        turns[i] = shape.turn
        offset[i] = np.array([(x + shape.pad - shift) * cell, (y + shape.pad - shift) * cell]) - shape.low
    return turns, offset


def place(tri, tri_isl, n, active, can_turn, gap):
    """Place the active islands of triangles `tri` (m, 3, 2, in pixels) from their present orientation, or a quarter
    turn from it where can_turn. Returns (turns per island, origin per island: the point subtracted before turning,
    offset per island: the point added after turning), or None when no raster could hold them."""
    order_t = np.argsort(tri_isl, kind='stable')
    start_t = np.searchsorted(tri_isl[order_t], np.arange(n + 1))
    lo = np.full((n, 2), np.inf)
    hi = np.full((n, 2), -np.inf)
    ids = np.repeat(tri_isl, 3)
    flat = tri.reshape(-1, 2)
    np.minimum.at(lo, ids, flat)
    np.maximum.at(hi, ids, flat)
    size = np.where(np.isfinite(hi - lo), hi - lo, 0.0)
    box = size[:, 0] * size[:, 1]
    e1, e2 = tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]
    area = np.bincount(tri_isl, weights=0.5 * np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]), minlength=n)
    key = box ** BOX_POWER * area ** (1.0 - BOX_POWER)
    active_ids = np.flatnonzero(active)
    order = active_ids[np.lexsort((active_ids, -key[active_ids]))].tolist()
    # the raster: room for the islands' bounding boxes with their gaps; larger when that was not enough
    needed = math.sqrt(max(float(((size[active] + gap).prod(axis=1)).sum()), 1.0))
    largest = float(size[active].max()) + 2.0 * gap
    cell = cell_size(needed, gap)
    side = max(1.1 * needed, 1.3 * largest)
    for _attempt in range(3):
        cell = max(cell, side / MAX_CELLS)
        result = _place_once(tri, order_t, start_t, lo, order, can_turn, gap, cell, side)
        if result is not None:
            turns = np.zeros(n, np.int64)
            offset = lo.copy()
            for i in order:
                turns[i] = result[0][i]
                offset[i] = result[1][i]
            return turns, lo, offset
        side *= 1.5
    return None


def apply(points, point_isl, moved, turns, origin, offset):
    """New positions of points (.., 2, the loops of a layout, in pixels) under the result of place: the islands of
    `moved` turn and move, the others stay."""
    out = points.copy()
    for t in np.unique(turns[moved]).tolist():
        sel = moved[point_isl] & (turns[point_isl] == t)
        ids = point_isl[sel]
        out[sel] = turned(points[sel] - origin[ids], t) + offset[ids]
    return out
