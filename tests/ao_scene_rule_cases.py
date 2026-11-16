"""Seeded synthetic cases of Refresh's scene-rule geometry (bake-post-native journal, Session 5): the inputs only, plain
numpy. tests/test_ao_copy_native.py runs them through fss_ao_copy.dll and compares with the values the Python code
(ao_bake_store's oriented_boxes_at, oriented_gaps, moves_against and near, before decision 6 removed them) gave on the
same inputs, recorded in tests/data/ao_scene_rule_reference.json (section 'synthetic', with a digest of each case's
inputs, so a changed generator or random generator is caught).

- boxes: own boxes (bounds lo, hi) placed by matrices: turned, scaled unevenly, mirrored, a zero or tiny scale, a
  shear from a parent's uneven scale (also about ORTHO_TOL), one matrix or a stack;
- gaps: an oriented box against k others: turned at random, the same axes (parallel edges), turned about a shared axis
  (some parallel edges), touching, overlapping, flat, apart along an edge-edge axis, none (k = 0), exact (axes of a
  permutation, dyadic centres and sizes);
- moves: (object, occluder) pairs over sampled frames: still, one moving, moving together (a child), moving
  differently, apart by about MOTION_TOL;
- near: scenes of candidates (world matrices now and at each pose, bounds), some moving, sheared, flat or zero-scaled,
  occluders a subset (also none), queried 'now' and 'swept' at random distances, at 0, and at a gap exactly (dyadic
  scenes whose gaps are exact: kept at the distance, dropped just under it).
"""

import zlib

import numpy as np

MOTION_TOL = 1e-4  # ao_bake_store.MOTION_TOL
ORTHO_TOL = 1e-4  # ao_bake_store.ORTHO_TOL


def rng_of(name):
    return np.random.default_rng([20261116, zlib.crc32(name.encode())])


def rotation(rng):
    q = rng.standard_normal(4)
    q /= np.linalg.norm(q)
    w, x, y, z = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def about_axis(axis, angle):
    c, s = np.cos(angle), np.sin(angle)
    a = np.asarray(axis, np.float64)
    a = a / np.linalg.norm(a)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + s * K + (1 - c) * (K @ K)


def permutation(rng):
    P = np.eye(3)[rng.permutation(3)]
    return P * rng.choice([-1.0, 1.0], 3)[None, :]


def matrix(R, t):
    M = np.eye(4)
    M[:3, :3] = R
    M[:3, 3] = t
    return M


def placed(rng, kind=None):
    """A world matrix of one of the kinds an object can have."""
    kind = kind or rng.choice(['turn', 'turn', 'turn', 'scale', 'mirror', 'zero', 'tiny', 'shear', 'shear_tol'])
    R = rotation(rng)
    t = rng.uniform(-1, 1, 3)
    if kind == 'turn':
        return matrix(R * rng.uniform(0.5, 2.0), t)
    if kind == 'scale':
        return matrix(R @ np.diag(rng.uniform(0.2, 3.0, 3)), t)
    if kind == 'mirror':
        return matrix(R @ np.diag([-1.0, 1.0, 1.0]) * rng.uniform(0.5, 2.0), t)
    if kind == 'zero':
        s = rng.uniform(0.5, 2.0, 3)
        s[rng.integers(3)] = 0.0
        return matrix(R @ np.diag(s), t)
    if kind == 'tiny':
        s = rng.uniform(0.5, 2.0, 3)
        s[rng.integers(3)] = rng.choice([1e-13, 1e-12, 2e-12, 1e-11])
        return matrix(R @ np.diag(s), t)
    if kind == 'shear':  # a child turned under a parent scaled unevenly
        return matrix(np.diag(rng.uniform(0.5, 2.0, 3)) @ R, t)
    # an axis leaning by about ORTHO_TOL
    eps = rng.choice([0.5, 0.9, 0.99, 1.01, 1.1, 2.0]) * ORTHO_TOL
    S = np.eye(3)
    S[0, 1] = eps
    return matrix(R @ S, t)


def bounds(rng):
    lo = rng.uniform(-0.3, 0.1, 3)
    hi = lo + rng.uniform(0.0, 0.5, 3) * (rng.uniform(0, 1, 3) > 0.05)
    return lo, hi


def corners(lo, hi):
    """Blender's bound_box order (only their min and max matter)."""
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    return np.array([[x0, y0, z0], [x0, y0, z1], [x0, y1, z1], [x0, y1, z0],
                     [x1, y0, z0], [x1, y0, z1], [x1, y1, z1], [x1, y1, z0]], np.float64)


def box_cases():
    rng = rng_of('boxes')
    out = []
    for i in range(160):
        n = 0 if i % 40 == 7 else int(rng.integers(1, 9))
        b = [bounds(rng) for _ in range(n)]
        lo = np.array([x[0] for x in b]).reshape(-1, 3)
        hi = np.array([x[1] for x in b]).reshape(-1, 3)
        mats = np.array([placed(rng) for _ in range(n)]).reshape(-1, 4, 4)
        if i % 10 == 0 and n:  # one matrix: (4, 4), bounds (3,)
            out.append((lo[0], hi[0], mats[0]))
        else:
            out.append((lo, hi, mats))
    return out


def own_box(R, c, e):
    return np.asarray(c, np.float64), np.asarray(R, np.float64), np.asarray(e, np.float64)


def gap_cases():
    rng = rng_of('gaps')
    out = []
    for i in range(200):
        kind = ['random', 'random', 'same_axes', 'shared_axis', 'touch', 'overlap', 'flat', 'edge', 'none',
                'exact'][i % 10]
        if kind == 'exact':
            UA = permutation(rng)
            c = rng.integers(-8, 8, 3) / 8.0
            e = rng.integers(0, 8, 3) / 16.0
        else:
            UA = rotation(rng)
            c = rng.uniform(-0.5, 0.5, 3)
            e = rng.uniform(0.01, 0.4, 3)
        if kind == 'flat':
            e[rng.integers(3)] = 0.0
        k = 0 if kind == 'none' else int(rng.integers(1, 9))
        cs, axs, hs = [], [], []
        for _ in range(k):
            if kind == 'exact':
                UB = permutation(rng)
                cb = rng.integers(-16, 16, 3) / 8.0
                hb = rng.integers(0, 8, 3) / 16.0
            else:
                UB = {'same_axes': UA, 'shared_axis': UA @ about_axis(np.eye(3)[rng.integers(3)],
                                                                      rng.uniform(0, np.pi))}.get(kind)
                if UB is None:
                    UB = rotation(rng)
                hb = rng.uniform(0.01, 0.4, 3)
                if kind == 'flat':
                    hb[rng.integers(3)] = 0.0
                d = rng.standard_normal(3)
                d /= np.linalg.norm(d)
                dist = {'touch': 0.0, 'overlap': -0.05}.get(kind, rng.uniform(0.0, 0.6))
                if kind == 'touch':  # B's face on A's face along A's first axis
                    cb = c + UA[:, 0] * (e[0] + hb[0])
                    UB = UA
                elif kind == 'edge':  # turned 45 degrees about A's z: a corner towards A's face
                    UB = UA @ about_axis([0, 0, 1], np.pi / 4) @ about_axis([1, 0, 0], rng.uniform(0, np.pi))
                    cb = c + UA[:, 0] * (e[0] + np.linalg.norm(hb) + rng.uniform(0, 0.2))
                else:
                    cb = c + d * (np.linalg.norm(e) + np.linalg.norm(hb) + dist)
            cs.append(cb)
            axs.append(UB)
            hs.append(hb)
        out.append((own_box(UA, c, e), np.array(cs).reshape(-1, 3), np.array(axs).reshape(-1, 3, 3),
                    np.array(hs).reshape(-1, 3)))
    return out


def poses(rng, M0, P, kind):
    """(P, 4, 4): pose 0 the current frame."""
    out = [M0]
    for p in range(1, P):
        if kind == 'still':
            out.append(M0.copy())
        elif kind == 'slide':
            M = M0.copy()
            M[:3, 3] += rng.uniform(-0.3, 0.3, 3) * p / P
            out.append(M)
        else:  # turn about the object's own origin
            out.append(M0 @ matrix(about_axis(rng.standard_normal(3), rng.uniform(0, 1.5) * p / P), np.zeros(3)))
    return np.array(out)


def moving_of(M):
    """motion()'s moving flags."""
    return (np.abs(M - M[:, :1]).max(axis=(1, 2, 3)) > MOTION_TOL) if len(M) else np.zeros(0, bool)


def moves_cases():
    rng = rng_of('moves')
    out = []
    for i in range(80):
        P = int(rng.integers(1, 7))
        n = int(rng.integers(2, 10))
        M = []
        for r in range(n):
            M0 = placed(rng, rng.choice(['turn', 'scale', 'mirror']))
            M.append(poses(rng, M0, P, rng.choice(['still', 'still', 'slide', 'turn'])))
        M = np.array(M)
        # children: rigidly with an object, or apart from it by about MOTION_TOL at the poses after the first
        for r in range(n):
            if rng.uniform() < 0.3:
                a = int(rng.integers(n))
                if a == r:
                    continue
                rel = matrix(rotation(rng), rng.uniform(-0.2, 0.2, 3))
                M[r] = M[a] @ rel
                if rng.uniform() < 0.5 and P > 1:
                    delta = rng.choice([0.5, 0.99, 1.01, 2.0]) * MOTION_TOL
                    M[r, 1:, rng.integers(3), 3] += delta
        pairs = np.array([(a, b) for a in range(n) for b in range(n) if a != b and rng.uniform() < 0.7],
                         np.int64).reshape(-1, 2)
        out.append((M, pairs))
    return out


def near_cases():
    rng = rng_of('near')
    out = []
    for i in range(48):
        exact = i % 4 == 3
        P = 1 if i % 6 == 0 else int(rng.integers(2, 6))
        n = int(rng.integers(1, 20))
        lo, hi, M = [], [], []
        for r in range(n):
            if exact:
                b_lo = rng.integers(-8, 8, 3) / 8.0
                b_hi = b_lo + rng.integers(0, 4, 3) / 8.0
                M0 = matrix(permutation(rng) if rng.uniform() < 0.5 else np.eye(3), rng.integers(-4, 4, 3) / 4.0)
                kind = rng.choice(['still', 'still', 'step'])
                if kind == 'step':
                    Ms = [M0]
                    for p in range(1, P):
                        Mp = M0.copy()
                        Mp[:3, 3] += rng.integers(-2, 3, 3) / 8.0
                        Ms.append(Mp)
                    Ms = np.array(Ms)
                else:
                    Ms = np.array([M0] * P)
            else:
                b_lo, b_hi = bounds(rng)
                M0 = placed(rng, rng.choice(['turn', 'turn', 'turn', 'scale', 'mirror', 'zero', 'shear', 'shear_tol']))
                Ms = poses(rng, M0, P, rng.choice(['still', 'still', 'slide', 'turn']))
            lo.append(b_lo)
            hi.append(b_hi)
            M.append(Ms)
        lo, hi, M = np.array(lo), np.array(hi), np.array(M)
        now = M[:, 0].copy()
        if i % 8 == 5:  # the matrices after motion() a hair off its first grab
            now[:, :3, 3] += rng.choice([0.0, 1e-12], (n, 3))
        k = 0 if i % 12 == 11 else int(rng.integers(0, n + 1))
        occ_rows = np.sort(rng.choice(n, size=min(k, n), replace=False)).astype(np.int64)
        queries = []
        for r in range(n):
            for which in (0, 1):
                if exact:
                    dists = [rng.integers(0, 12) / 16.0]
                else:
                    dists = [float(rng.uniform(0.0, 0.5)), 0.0]
                for d in dists:
                    queries.append((r, which, float(d)))
        out.append(dict(lo=lo, hi=hi, now=now, M=M, occ_rows=occ_rows, queries=queries, exact=exact))
    return out


def mesh_cases():
    """evaluated_triangles-like dicts (tris int64 (T, 3), co float64 (V, 3) of float32 values, cn float64 (T, 3, 3)
    of float32 values) for mesh_hash: empty, small, large (several blocks and threads), corner normals at the
    rounding's halves, about -0 (rounded to -0.0, then +0.0), large, NaN and inf."""
    rng = rng_of('mesh_hash')
    out = []
    for i, T in enumerate([0, 1, 2, 7, 100, 1000, 4096, 30000, 100001, 250000]):
        V = max(1, T // 2 + 3) if T else 0
        tris = rng.integers(0, max(V, 1), (T, 3)).astype(np.int64)
        co = rng.uniform(-3, 3, (V, 3)).astype(np.float32).astype(np.float64)
        n = rng.standard_normal((T, 3, 3))
        n /= np.maximum(np.linalg.norm(n, axis=2, keepdims=True), 1e-30)
        cn = n.astype(np.float32).astype(np.float64)
        if T:
            flat = cn.reshape(-1)
            m = len(flat)
            k = rng.integers(0, m, max(1, m // 5))
            flat[k] = ((rng.integers(-10000, 10000, len(k)) + 0.5) / 10000.0).astype(np.float32)  # about the halves
            k = rng.integers(0, m, max(1, m // 20))
            flat[k] = rng.uniform(-0.00006, 0.00006, len(k)).astype(np.float32)  # about zero, both signs
            if i % 3 == 2:
                flat[rng.integers(0, m, 3)] = [np.nan, np.inf, -np.inf]
                flat[rng.integers(0, m, 2)] = [3.0e38, -1.5e38]
        out.append(dict(tris=tris, co=co, cn=cn))
    return out
