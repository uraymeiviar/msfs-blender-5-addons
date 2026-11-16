"""Placing UV islands on a raster, into the free space between and inside each other (no bpy): the FSS packer that
uv_pack uses (it replaced Blender's Pack Islands in native UV packer step c). The work is done by the C++ library
fss_uv_pack (native/uv_pack, native UV packer journal steps b and c); this module keeps the cheap setup (the order of
the islands, the raster's cell size, the reach table) and the columns of the islands left outside. The Python code of
step b is kept for comparison in tests/uv_fill_reference.py; there is no Python fallback (native UV packer decision 13).

Blender's Pack Islands, which uv_pack used before, left free space inside closed shapes and beside large islands: on the
E2 cockpit (material MAT_STD_COCKPIT_FRONT, 1243 islands) 11.3 % of its layout was empty and enclosed and 30.5 %
open and empty. The raster sees every island as it is: the cells its triangles touch. An island may go wherever its
footprint, grown by the gap to its neighbours, covers no occupied cell; inside a ring as well as beside it. Footprints
are conservative (every cell a triangle touches) and the growth counts the distance between cells, so a position found
here keeps the gap for any two points of two islands, whatever the triangles look like (needles included). Islands move
and turn as their turn set allows (UPRIGHT not at all, FLIP by 180 degrees, QUARTER in 90-degree steps, EIGHTH in
45-degree steps, native UV packer decision 20), after a base angle (a Free island straightened by its tightest box,
straighten); their scale never changes. The result is deterministic: no random numbers, stable sorts.

The islands are taken largest first; each goes where the layout grows least, within that into an island's enclosed
space first, then where it touches its neighbours most, then nearest the origin, then by the order of preference of the
turns: none, 180, 90 and 270 degrees, then the 45-degree ones.
"""

import ctypes
import math
import os
import sys
from ctypes import POINTER, c_double, c_int32, c_int64, c_void_p

import numpy as np

BLOCK = 16  # cells per side of the blocks that prune the search (also in the library)
MIN_CELLS = 128  # raster cells per side at least (twice the largest free square the search keeps maps of)
MAX_CELLS = 4096  # raster cells per side at most (about 170 MB of tables)
CELLS_PER_SIDE = 2700  # raster cells over the expected layout's side; at 2.7 px per cell, 8.1 px of gap are 3 cells
MIN_CELLS_PER_SIDE = 100  # however large the gap, an island is not rasterised coarser than this
MAX_CELLS_PER_GAP = 8  # a finer raster than this is not needed: small sets of tiny islands, 1 px per cell at 8 px
# Which island first: bounding box area to this power x real area to 1 - this power. A smaller power uses enclosed space
# better, a larger one gives the smaller layout. Measured on MAT_STD_COCKPIT_FRONT at 2.7 px per cell (k, enclosed empty
# space): 1: 1.540, 5.4 %; 0.8: 1.539, 4.8 %; 0.75: 1.551, 4.7 %; 0.5: 1.567, 4.1 %; 0: 1.586, 3.6 %
BOX_POWER = 0.8
# place tries the islands in these orders (BOX_POWER values) and keeps the tightest layout. Measured on the E2 cockpit
# (native UV packer Session 5): 0.6 gives the tightest MAT_LEATHER (k 0.9211 against 0.9232 at 0.8) and
# MAT_STD_COCKPIT_REAR (0.8923 against 0.8983), 0.4 MAT_STD_COCKPIT_FRONT (0.9410 against 0.9633)
ORDERS = (BOX_POWER, 0.6, 0.4)
# turn sets (fss_uv_pack.h): the turns an island may take after its base angle
UPRIGHT, FLIP, QUARTER, EIGHTH = 0, 1, 2, 3

LIB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib', 'uv_pack', 'windows-x64')
DLL = 'fss_uv_pack.dll'
VERSION = 2  # FSS_UV_PACK_VERSION of native/uv_pack/fss_uv_pack.h

_lib = {'tried': False, 'dll': None, 'error': None}


def load():
    """The library, or None when it cannot be loaded (the reason in error())."""
    if _lib['tried']:
        return _lib['dll']
    _lib['tried'] = True
    try:
        if sys.platform != 'win32' or ctypes.sizeof(c_void_p) != 8:
            raise OSError(f'no build for {sys.platform} ({8 * ctypes.sizeof(c_void_p)}-bit)')
        path = os.path.join(LIB_DIR, DLL)
        if not os.path.isfile(path):
            raise OSError(f'{path} is missing')
        dll = ctypes.CDLL(path)
        dll.fss_uv_pack_version.restype = c_int32
        dll.fss_uv_pack_version.argtypes = []
        version = int(dll.fss_uv_pack_version())
        if version != VERSION:
            raise OSError(f'{path} is version {version}, the add-on needs {VERSION}')
        p, i64 = c_void_p, c_int64
        signatures = {
            'fss_uv_solid': [p, i64, p, i64, POINTER(c_int64), POINTER(c_int64)],
            'fss_uv_place_once': [p, p, i64, p, p, i64, p, p, c_double, c_double, p, i64, i64, p, i64, p, p],
            'fss_uv_repair': [p, p, i64, p, p, p, p, p, p, p, c_double, c_double, p, i64, i64, c_double, c_double,
                              p, p, p, p, POINTER(c_int64)],
            'fss_uv_straighten': [p, p, i64, p, p],
        }
        for name, args in signatures.items():
            fn = getattr(dll, name)
            fn.restype = c_int32
            fn.argtypes = args
        _lib['dll'] = dll
    except (OSError, AttributeError) as exc:
        _lib['error'] = f'the C++ packer ({DLL}) could not be loaded: {exc}'
    return _lib['dll']


def error():
    """Why the library could not be loaded, or None when it is loaded."""
    load()
    return _lib['error']


def _dll():
    dll = load()
    if dll is None:
        raise RuntimeError(error())
    return dll


def _ptr(a):
    return a.ctypes.data_as(c_void_p)


def solid_mask_of(T):
    """The cells triangles T (k, 3, 2; x, y in cells, not negative) touch, as a boolean array (rows y, columns x)."""
    T = np.ascontiguousarray(T, np.float64)
    h, w = c_int64(0), c_int64(0)
    dll = _dll()
    out = np.zeros(1, np.uint8)
    rc = dll.fss_uv_solid(_ptr(T), len(T), _ptr(out), out.size, ctypes.byref(h), ctypes.byref(w))
    if rc == 0:  # too small: the size is known now
        out = np.zeros(max(h.value * w.value, 1), np.uint8)
        rc = dll.fss_uv_solid(_ptr(T), len(T), _ptr(out), out.size, ctypes.byref(h), ctypes.byref(w))
    if rc != 1:
        raise RuntimeError('fss_uv_solid failed')
    return out[:h.value * w.value].reshape(h.value, w.value).astype(bool)


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


def turned(P, turns):
    """Points P (.., 2) turned by turns x 90 degrees counter-clockwise (exactly)."""
    turns %= 4
    if turns == 0:
        return P
    if turns == 1:
        return np.stack([-P[..., 1], P[..., 0]], -1)
    if turns == 2:
        return -P
    return np.stack([P[..., 1], -P[..., 0]], -1)


def rotated(P, base, eighths):
    """Points P (.., 2) turned by base (radians) + eighths x 45 degrees counter-clockwise: exact when base is 0 and the
    turn a multiple of 90 degrees, as the library does."""
    if base == 0.0 and eighths % 2 == 0:
        return turned(P, eighths // 2)
    a = base + eighths * (math.pi / 4.0)
    c, s = math.cos(a), math.sin(a)
    return np.stack([c * P[..., 0] - s * P[..., 1], s * P[..., 0] + c * P[..., 1]], -1)


def _per_island(values, n, dtype, default):
    return np.full(n, default, dtype) if values is None else np.ascontiguousarray(values, dtype)


def straighten(tri, tri_isl, n, active):
    """Per island the angle (radians, -45 to 45 degrees) that gives the active island its smallest bounding box
    (decision 10: 36 steps of 10 degrees, refined), 0 when it is already smallest; for Free islands."""
    grouped, start_t, _lo, _hi, _area = _islands(tri, tri_isl, n)
    base = np.zeros(n, np.float64)
    act = np.ascontiguousarray(active, np.uint8)
    if _dll().fss_uv_straighten(_ptr(grouped), _ptr(start_t), n, _ptr(act), _ptr(base)) != 1:
        raise RuntimeError('fss_uv_straighten failed')
    return base


def cell_size(side, gap):
    """Pixels per raster cell for a layout of about this side. When the gap is a whole number of cells, the islands
    come to the gap exactly, without a part of a cell to spare."""
    cell = max(side / CELLS_PER_SIDE, min(gap / MAX_CELLS_PER_GAP, side / MIN_CELLS_PER_SIDE))
    return gap / math.ceil(gap / cell) if cell < gap else cell


def _islands(tri, tri_isl, n):
    """The triangles grouped per island (contiguous, for the library), where each island's start, and per island
    the low and high corner of its box and its area."""
    order_t = np.argsort(tri_isl, kind='stable')
    start_t = np.searchsorted(tri_isl[order_t], np.arange(n + 1)).astype(np.int64)
    lo = np.full((n, 2), np.inf)
    hi = np.full((n, 2), -np.inf)
    ids = np.repeat(tri_isl, 3)
    flat = tri.reshape(-1, 2)
    np.minimum.at(lo, ids, flat)
    np.maximum.at(hi, ids, flat)
    e1, e2 = tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]
    area = np.bincount(tri_isl, weights=0.5 * np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]), minlength=n)
    grouped = np.ascontiguousarray(tri[order_t], np.float64)
    return grouped, start_t, lo, hi, area


def _place_once(grouped, start_t, lo, order, turn_set, base, gap, cell, side, fixed_ids=()):
    reach = reach_table(round(gap / cell, 6))
    shift = max(len(reach) - 1, reach[0]) + 1  # a grown footprint must not start below the raster
    grid_cells = max(int(side / cell) + 2 * shift + BLOCK, MIN_CELLS)
    n = len(lo)
    turns = np.zeros(n, np.int32)
    offset = np.zeros((n, 2), np.float64)
    order_a = np.asarray(order, np.int64)
    fixed_a = np.asarray(fixed_ids, np.int64)
    reach_a = np.asarray(reach, np.int32)
    lo_a = np.ascontiguousarray(lo, np.float64)
    rc = _dll().fss_uv_place_once(_ptr(grouped), _ptr(start_t), n, _ptr(lo_a), _ptr(order_a), len(order_a),
                                  _ptr(turn_set), _ptr(base), gap, cell, _ptr(reach_a), len(reach_a), grid_cells,
                                  _ptr(fixed_a), len(fixed_a), _ptr(turns), _ptr(offset))
    if rc < 0:
        raise RuntimeError('fss_uv_place_once failed')
    return (turns, offset) if rc == 1 else None


def place(tri, tri_isl, n, active, turn_set, gap, fixed=None, base=None, powers=ORDERS):
    """Place the active islands of triangles `tri` (m, 3, 2, in pixels), each turned by its base angle (radians, None:
    0) and then as its turn set allows (UPRIGHT, FLIP, QUARTER, EIGHTH per island). fixed: islands that stay where they
    are (pinned); the others go around them. The islands are placed once per order of powers (BOX_POWER) and the
    tightest layout is kept (the first of equals). Returns (turns per island in eighths, origin per island: the point
    subtracted before turning, offset per island: the point added after turning), or None when no raster could hold
    them. apply takes these with the same base."""
    grouped, start_t, lo, hi, area = _islands(tri, tri_isl, n)
    turn_set = _per_island(turn_set, n, np.uint8, UPRIGHT)
    base = _per_island(base, n, np.float64, 0.0)
    size = np.where(np.isfinite(hi - lo), hi - lo, 0.0)
    box = size[:, 0] * size[:, 1]
    active_ids = np.flatnonzero(active)
    # the raster: room for the islands' bounding boxes with their gaps; larger when that was not enough
    needed = math.sqrt(max(float(((size[active] + gap).prod(axis=1)).sum()), 1.0))
    largest = float(size[active].max()) + 2.0 * gap
    fixed_ids = [] if fixed is None else np.flatnonzero(fixed & ~active).tolist()
    best = None
    points = tri.reshape(-1, 2)
    point_isl = np.repeat(tri_isl, 3)
    on = active[point_isl]
    for power in powers:
        key = box ** power * area ** (1.0 - power)
        order = active_ids[np.lexsort((active_ids, -key[active_ids]))]
        cell = cell_size(needed, gap)
        side = max(1.1 * needed, 1.3 * largest)
        if fixed_ids:
            side = max(side, float(hi[fixed_ids].max()) + 2.0 * gap + needed)
        for _attempt in range(3):
            cell = max(cell, side / MAX_CELLS)
            result = _place_once(grouped, start_t, lo, order, turn_set, base, gap, cell, side, fixed_ids)
            if result is not None:
                turns = np.zeros(n, np.int64)
                offset = lo.copy()
                turns[order] = result[0][order]
                offset[order] = result[1][order]
                break
            side *= 1.5
        if result is None:
            continue
        if len(powers) == 1:
            return turns, lo, offset
        # the layout's side: from the origin with pinned islands (they stay), else from its own low corner (uv_pack
        # slides the layout there)
        F = apply(points[on], point_isl[on], active, turns, lo, offset, base)
        side_px = float((F.max(0) - (0.0 if fixed_ids else F.min(0))).max())
        if best is None or side_px < best[0]:
            best = (side_px, turns, offset)
    return None if best is None else (best[1], lo, best[2])


def repair(tri, tri_isl, n, active, turn_set, gap, limit, fixed=None, aside=None, base=None):
    """Islands of a layout that lie outside the texture (0 to limit pixels), wholly or in part, moved into its free
    space (decision 156). The islands inside stay where they are; the others go, largest first, into the best free
    place inside, turned as their turn set allows after their base angle, keeping the gap to every island and half of
    it to the texture's edges; an island that fits nowhere is skipped. The ones left go into columns beyond the right
    edge, wholly outside, so that none covers part of the texture. Their scale never changes. fixed: pinned islands, which never
    move; an island inside the texture that comes closer to one than the gap is moved as if it were outside.
    limit: the texture's side in pixels, or (width, height) of the target area (decision 158), which then stands for
    the texture; aside: (x, y) in pixels where the columns of the islands left outside start, by default just beyond
    the right edge.

    tri (m, 3, 2) in pixels with tri_isl per triangle. Returns (moved, turns, origin, offset, outside, outside area in
    px^2): moved and outside per island; turns, origin and offset as apply takes them."""
    grouped, start_t, lo, hi, area = _islands(tri, tri_isl, n)
    turn_set = _per_island(turn_set, n, np.uint8, UPRIGHT)
    base = _per_island(base, n, np.float64, 0.0)
    lo = np.where(np.isfinite(lo), lo, 0.0)
    hi = np.where(np.isfinite(hi), hi, 0.0)
    size = hi - lo
    fixed = np.zeros(n, bool) if fixed is None else fixed & active
    lim = np.broadcast_to(np.asarray(limit, np.float64), (2,))  # (x, y)
    inside = active & ~fixed & (lo >= 0.0).all(1) & (hi <= lim).all(1)
    out = active & ~fixed & ~inside
    moved = np.zeros(n, bool)
    turns = np.zeros(n, np.int64)
    offset = lo.copy()
    if not out.any() and not fixed.any():
        return moved, turns, lo, offset, out, 0.0
    cell = cell_size(float(lim.max()), gap)
    reach = np.asarray(reach_table(round(gap / cell, 6)), np.int32)
    half = int(math.ceil(0.5 * gap / cell))  # half the gap to the texture's edges, in cells
    key = np.ascontiguousarray((size[:, 0] * size[:, 1]) ** BOX_POWER * area ** (1.0 - BOX_POWER), np.float64)
    inside_a = inside.astype(np.uint8)
    moved_a = np.zeros(n, np.uint8)
    turns_a = np.zeros(n, np.int32)
    offset_a = np.zeros((n, 2), np.float64)
    left_a = np.zeros(max(n, 1), np.int64)
    n_left = c_int64(0)
    lo_a = np.ascontiguousarray(lo, np.float64)
    fixed_a = fixed.astype(np.uint8)
    active_a = np.ascontiguousarray(active, np.uint8)
    rc = _dll().fss_uv_repair(_ptr(grouped), _ptr(start_t), n, _ptr(lo_a), _ptr(key), _ptr(inside_a), _ptr(fixed_a),
                              _ptr(active_a), _ptr(turn_set), _ptr(base), gap, cell, _ptr(reach), len(reach), half,
                              float(lim[0]), float(lim[1]), _ptr(moved_a), _ptr(turns_a), _ptr(offset_a), _ptr(left_a),
                              ctypes.byref(n_left))
    if rc < 0:
        raise RuntimeError('fss_uv_repair failed')
    if rc == 2:  # no island comes too close to a pinned one and none is outside
        return moved, turns, lo, offset, np.zeros(n, bool), 0.0
    moved = moved_a.astype(bool)
    turns = turns_a.astype(np.int64)
    offset = np.where(moved[:, None], offset_a, offset)
    left = left_a[:n_left.value].tolist()
    # what fits nowhere: in columns beyond the right edge (or from `aside` on), as they are, each column as high as
    # the texture
    x0, y0 = (lim[0] + gap, 0.5 * gap) if aside is None else (float(aside[0]) + 0.5 * gap, float(aside[1]) + 0.5 * gap)
    x, y = x0, y0
    column = 0.0
    for i in left:
        if y + size[i, 1] > y0 - 0.5 * gap + lim[1] and y > y0:
            x += column + gap
            y = y0
            column = 0.0
        offset[i] = (x, y)
        moved[i] = True
        y += size[i, 1] + gap
        column = max(column, size[i, 0])
    outside = np.zeros(n, bool)
    outside[left] = True
    return moved, turns, lo, offset, outside, float(area[outside].sum())


def apply(points, point_isl, moved, turns, origin, offset, base=None):
    """New positions of points (.., 2, the loops of a layout, in pixels) under the result of place or repair (turns in
    eighths after the base angles given to it): the islands of `moved` turn and move, the others stay."""
    out = points.copy()
    if base is None:
        base = np.zeros(len(turns))
    for i in np.flatnonzero(moved & (base != 0.0)).tolist():  # straightened islands, one at a time (few)
        sel = point_isl == i
        out[sel] = rotated(points[sel] - origin[i], float(base[i]), int(turns[i])) + offset[i]
    plain = moved & (base == 0.0)
    for t in np.unique(turns[plain]).tolist():
        sel = plain[point_isl] & (turns[point_isl] == t)
        ids = point_isl[sel]
        out[sel] = rotated(points[sel] - origin[ids], 0.0, t) + offset[ids]
    return out
