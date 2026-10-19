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


# Round 5 shape metrics. The round-3 functions above deliberately stay unchanged.
def _uv_topology(T, UV):
    """Exact (mesh vertex, UV) topology, matching the round-3 evaluator.

    Only edges with exactly two incident faces connect islands. Coincident UVs
    from different mesh vertices never weld; non-manifold edges are not joined.
    """
    keys, inverse = np.unique(
        np.column_stack((T.ravel(), UV.reshape(-1, 2))), axis=0,
        return_inverse=True)
    corners = inverse.reshape(-1, 3)
    edges = {}
    for f, vertices in enumerate(corners):
        for a, b in zip(vertices, np.roll(vertices, -1)):
            edge = tuple(sorted((int(a), int(b))))
            edges.setdefault(edge, []).append(f)
    parent = np.arange(len(T))

    def find(f):
        while parent[f] != f:
            parent[f] = parent[parent[f]]
            f = parent[f]
        return f

    for faces in edges.values():
        if len(faces) == 2:
            a, b = map(find, faces)
            parent[a] = b
    roots = [find(f) for f in range(len(T))]
    _, labels = np.unique(roots, return_inverse=True)
    return keys, corners, labels


def _weighted_shape_stats(values, weights):
    """3D-area-weighted mean and inverse-CDF p95 (no interpolation).

    Infinity is retained, never filtered as an outlier. Empty samples are None,
    rather than a misleading perfect score. Callers exclude degenerate 3D faces.
    """
    if not len(values) or weights.sum() <= 0:
        return dict(mean=None, p95=None, max=None)
    order = np.argsort(values, kind='stable')
    cumulative = np.cumsum(weights[order])
    index = min(int(np.searchsorted(cumulative, .95 * cumulative[-1])), len(order) - 1)
    return dict(mean=float(np.sum(values * (weights / weights.sum()))),
                p95=float(values[order[index]]), max=float(np.max(values)))


def _boundary_straightness(P, keys, corners, labels, angle_degrees):
    """Maximal boundary chains joined at degree-two, 3D-straight vertices.

    A chain needs at least two nonzero edges. Its full 3D length is preserved
    only when *every* corresponding UV join passes the same angle limit and no
    UV edge collapses. Single edges and ambiguous branch vertices cannot establish
    straightness. Seam sides are counted separately for their respective islands.
    This is a local consecutive-edge criterion, not a global line fit.
    """
    edges = {}
    for f, vertices in enumerate(corners):
        for a, b in zip(vertices, np.roll(vertices, -1)):
            key = (int(labels[f]), *sorted((int(a), int(b))))
            edges[key] = edges.get(key, 0) + 1
    boundary = [key for key, count in edges.items() if count == 1]
    nonmanifold = sum(count > 2 for count in edges.values())
    adjacency = {}
    for e, (island, a, b) in enumerate(boundary):
        for vertex in (a, b):
            adjacency.setdefault((island, vertex), []).append(e)
    positions = P[keys[:, 0].astype(np.int64)]
    uv = keys[:, 1:]
    parent = list(range(len(boundary)))
    joins = []
    cosine_limit = np.cos(np.radians(angle_degrees))

    def find(e):
        while parent[e] != e:
            parent[e] = parent[parent[e]]
            e = parent[e]
        return e

    def straight(points, a, v, b):
        incoming, outgoing = points[v] - points[a], points[b] - points[v]
        length_product = np.linalg.norm(incoming) * np.linalg.norm(outgoing)
        return (length_product > 0 and
                float(incoming @ outgoing) / length_product >= cosine_limit - 1e-14)

    for (_, vertex), incident in adjacency.items():
        if len(incident) != 2:
            continue
        e, q = incident
        a = next((v for v in boundary[e][1:] if v != vertex), vertex)
        b = next((v for v in boundary[q][1:] if v != vertex), vertex)
        if straight(positions, a, vertex, b):
            parent[find(e)] = find(q)
            joins.append((e, straight(uv, a, vertex, b)))
    chains = {}
    for e, (island, a, b) in enumerate(boundary):
        entry = chains.setdefault(find(e), dict(island=island, edges=0, length=0., ok=True))
        length = float(np.linalg.norm(positions[b] - positions[a]))
        entry['edges'] += int(length > 0)
        entry['length'] += length
        entry['ok'] &= bool(np.linalg.norm(uv[b] - uv[a]) > 0)
    for e, ok in joins:
        chains[find(e)]['ok'] &= ok
    result = {int(i): dict(chain_count=0, eligible_length=0., preserved_length=0.)
              for i in np.unique(labels)}
    for chain in chains.values():
        if chain['edges'] < 2:
            continue
        entry = result[chain['island']]
        entry['chain_count'] += 1
        entry['eligible_length'] += chain['length']
        if chain['ok']:
            entry['preserved_length'] += chain['length']
    total = {k: sum(r[k] for r in result.values())
             for k in ('chain_count', 'eligible_length', 'preserved_length')}
    for entry in [*result.values(), total]:
        entry['preserved_fraction'] = (entry['preserved_length'] / entry['eligible_length']
                                       if entry['eligible_length'] > 0 else None)
    total['nonmanifold_edge_count'] = nonmanifold
    return result, total


def shape_metrics(P, T, UV, island_ids=None, *, planar_degrees=10.,
                  straight_degrees=2., conformal_threshold=1.1,
                  degeneracy_relative=1e-12):
    """Round-5 shape fidelity for one object, with no Blender/SciPy dependency.

    Inputs are positions (V,3), triangle vertex indices (F,3), per-corner UVs
    (F,3,2), and optional integer island labels (F,). Without labels, islands are
    inferred through exact shared UV edges. Supplied labels are authoritative;
    the caller must supply actual islands, not merely soft chart identifiers.

    Construct each 3D triangle's orthonormal 2D frame and its affine Jacobian J
    to UV. Divide J's singular values by sqrt(sum(UV area)/sum(3D area)) within
    each island. Return sigma1/sigma2 and max(sigma1*sigma2, 1/(sigma1*sigma2)).
    Reflection is shape-preserving here; winding/overlap are separate old metrics.

    Returns {'faces': numpy arrays, 'islands': list of summaries, 'object': summary}.
    All means and p95s use 3D area, including object summaries across islands;
    p95 is the inverse weighted CDF, not a face-count percentile. Dominant plane
    normals are the principal eigenvector of sum(area * normal * normal.T), so
    reversed winding cannot cancel them. Tied principal eigenvalues fall back to
    the largest-area face normal (first face breaks ties). Planar faces have an
    unsigned normal angle <= planar_degrees to that plane. This classifies normal
    orientation, not connected planar patches or equal plane offsets.

    3D-degenerate faces (cross length <= degeneracy_relative * longest_edge^2)
    are excluded and counted; their face scores are NaN. Collapsed UVs on valid
    3D faces have infinite conformal/area scores and remain in summaries. An
    entirely collapsed island has zero scale and infinite distortion. Empty or
    inapplicable summaries/straightness fractions are None, never a perfect 1.
    No overlap, seam-crossing or timing metrics are replaced by this function.
    """
    P = np.asarray(P, dtype=np.float64)
    T = np.asarray(T)
    UV = np.asarray(UV, dtype=np.float64)
    if P.ndim != 2 or P.shape[1] != 3:
        raise ValueError('P must have shape (V, 3)')
    if T.ndim != 2 or T.shape[1] != 3 or T.dtype.kind not in 'iu':
        raise ValueError('T must contain integer indices with shape (F, 3)')
    if UV.shape != (len(T), 3, 2):
        raise ValueError('UV must have shape (F, 3, 2)')
    if not np.isfinite(P).all() or not np.isfinite(UV).all():
        raise ValueError('P and UV must be finite')
    if T.size and (T.min() < 0 or T.max() >= len(P)):
        raise ValueError('T contains an out-of-range vertex index')
    if not (0 <= planar_degrees <= 90 and 0 <= straight_degrees < 90
            and np.isfinite(conformal_threshold) and conformal_threshold >= 1
            and np.isfinite(degeneracy_relative) and 0 <= degeneracy_relative < 1):
        raise ValueError('invalid metric thresholds')
    keys, corners, inferred = _uv_topology(T, UV)
    labels = inferred if island_ids is None else np.asarray(island_ids)
    if labels.shape != (len(T),) or labels.dtype.kind not in 'iu':
        raise ValueError('island_ids must be an integer label for each face')
    points = P[T]
    e1, e2 = points[:, 1] - points[:, 0], points[:, 2] - points[:, 0]
    cross = np.cross(e1, e2)
    cross_length = np.linalg.norm(cross, axis=1)
    longest_squared = np.maximum.reduce([np.sum(e1**2, axis=1), np.sum(e2**2, axis=1),
                                        np.sum((e2 - e1)**2, axis=1)])
    valid = cross_length > degeneracy_relative * longest_squared
    area3 = cross_length / 2
    uv_area = np.abs(tri_area2_signed(UV))
    normals = np.zeros_like(cross)
    normals[valid] = cross[valid] / cross_length[valid, None]
    jacobian = np.full((len(T), 2, 2), np.nan)
    length = np.linalg.norm(e1[valid], axis=1)
    x = np.einsum('ij,ij->i', e1[valid], e2[valid]) / length
    height = cross_length[valid] / length
    du, dv = UV[valid, 1] - UV[valid, 0], UV[valid, 2] - UV[valid, 0]
    jacobian[valid, :, 0] = du / length[:, None]
    jacobian[valid, :, 1] = (dv - du * (x / length)[:, None]) / height[:, None]
    sigma = np.full((len(T), 2), np.nan)
    sigma[valid] = np.linalg.svd(jacobian[valid], compute_uv=False)
    conformal = np.full(len(T), np.nan)
    area = np.full(len(T), np.nan)
    planar = np.zeros(len(T), dtype=bool)
    per_island_straight, object_straight = _boundary_straightness(
        P, keys, corners, labels, straight_degrees)

    def summarize(mask):
        use = mask & valid
        weights = area3[use]
        plane = use & planar
        return dict(face_count=int(mask.sum()), valid_face_count=int(use.sum()),
                    degenerate_3d_faces=int((mask & ~valid).sum()),
                    collapsed_uv_faces=int((use & (uv_area == 0)).sum()),
                    area_3d=float(weights.sum()),
                    conformal=_weighted_shape_stats(conformal[use], weights),
                    area_distortion=_weighted_shape_stats(area[use], weights),
                    conformal_area_share_above_threshold=(
                        float(weights[conformal[use] > conformal_threshold].sum() / weights.sum())
                        if weights.sum() > 0 else None),
                    planar=dict(face_count=int(plane.sum()), area_3d=float(area3[plane].sum()),
                                conformal=_weighted_shape_stats(conformal[plane], area3[plane]),
                                area_distortion=_weighted_shape_stats(area[plane], area3[plane])))

    islands = []
    for label in np.unique(labels):
        mask = labels == label
        use = mask & valid
        scale = None
        dominant = None
        if use.any():
            scale = float(np.sqrt(uv_area[use].sum() / area3[use].sum()))
            if scale > 0:
                sigma[use] /= scale
            else:
                sigma[use] = 0.
            hi, lo = sigma[use].T
            with np.errstate(divide='ignore', invalid='ignore'):
                conformal[use] = np.where(lo > 0, hi / lo, np.inf)
                product = hi * lo
                area[use] = np.where(product > 0, np.maximum(product, 1 / product), np.inf)
            # Determinants identify exact collapse even when SVD returns roundoff.
            collapsed = use & (uv_area == 0)
            conformal[collapsed] = area[collapsed] = np.inf
            ns, weights = normals[use], area3[use]
            eigenvalues, axes = np.linalg.eigh((ns * weights[:, None]).T @ ns)
            dominant = axes[:, -1]
            if eigenvalues[-1] - eigenvalues[-2] <= 1e-12 * weights.sum():
                dominant = ns[int(np.argmax(weights))]
            planar[use] = np.abs(ns @ dominant) >= np.cos(np.radians(planar_degrees)) - 1e-14
        entry = summarize(mask)
        entry.update(id=int(label), uv_scale=scale,
                     dominant_plane_normal=dominant.tolist() if dominant is not None else None,
                     straight_edges=per_island_straight[int(label)])
        islands.append(entry)
    summary = summarize(np.ones(len(T), dtype=bool))
    summary.update(island_count=len(islands), straight_edges=object_straight)
    return dict(faces=dict(island_ids=labels.copy(), valid_3d=valid,
                           area_3d=area3, singular_values=sigma,
                           conformal=conformal, area_distortion=area, planar=planar),
                islands=islands, object=summary)
