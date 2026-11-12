"""The copy of the bake prototype (P4): master -> any UV layout of the same mesh, plain numpy.

For each pixel of the target layout whose centre lies in a triangle, L x L points in the pixel are mapped through
their triangle's barycentric coordinates into the master and read bilinearly. L per triangle = 2 x the pixel's
footprint in master pixels (at least k, at most kmax). outside_mode 'tri' (default): only points on the pixel's own
triangle count, as in a direct Cycles bake whose jitter stays on that triangle; 'drop': points on any triangle of the
pixel's layout island count; 'extend': every point counts, points off the island using the pixel's triangle extended.
With surface_cos, the bilinear read uses only master texels whose face (the master's face map) has a normal within
that cosine of the sampled face, so a read near a sharp fold does not take the other face's AO.
Padding pixels (up to `padding` px from the layout) take the nearest triangle, cross its nearest edge into the 3D
neighbour face hinged flat into the layout, and read the nearest point of that face from the master. A master point
outside its island's baked pixels is clamped into its triangle.
"""
import numpy as np

import bake_geom as bg


def _neighbours(wt):
    """(T,3) neighbour triangle across the edge opposite corner k (-1 if none), choosing the first other triangle."""
    em = bg.edge_map(wt)
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


def copy_master(pos, tris, uvpx, tisl, master, crop, k, padding=8, outside_mode='tri', kmax=16, surface_cos=None):
    """Returns (image (h,w) with -1 where nothing was written, info)."""
    x0, y0, w, h = crop
    muv = master['muv']
    M = master['image']
    mH, mW = M.shape
    rect_id = master['rect_id']
    filled = master['filled']
    misl = master['island']
    wt = bg.weld_ids(pos)[tris]
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
        ok = (rect_id[yi, xi] == misl[tri_ids]) & filled[yi, xi]
        bad = ~ok
        n_clamped = int(bad.sum())
        if bad.any():
            bb = np.clip(bary[bad], 0, None)
            bb /= np.maximum(bb.sum(axis=1, keepdims=True), 1e-30)
            mp[bad] = np.einsum('nk,nkd->nd', bb, muv[tri_ids[bad]])
        if surface_cos is None or face_map is None:
            return bg.bilinear(M, mp[:, 0], mp[:, 1]), n_clamped
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
        nt = tri_normal[tri_ids]
        for dx, dy, wgt in ((0, 0, (1 - ax) * (1 - ay)), (1, 0, ax * (1 - ay)), (0, 1, (1 - ax) * ay), (1, 1, ax * ay)):
            xc = np.clip(xa + dx, 0, mW - 1)
            yc = np.clip(ya + dy, 0, mH - 1)
            f = face_map[yc, xc]
            ok = (f >= 0) & (np.einsum('nd,nd->n', tri_normal[np.maximum(f, 0)], nt) >= surface_cos)
            wv = np.where(ok, wgt, 0.0)
            acc += wv * M[yc, xc]
            wsum += wv
        plain = bg.bilinear(M, mp[:, 0], mp[:, 1])
        return np.where(wsum > 1e-9, acc / np.maximum(wsum, 1e-30), plain)

    owner_c, count_c = bg.rasterize_ids(uvpx, w, h, 1, x0, y0)
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
        owner_s, _ = bg.rasterize_ids(uvpx, bw, bh, int(L), x0 + bx0, y0 + by0)
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
        bary = bg.barycentric_many(np.stack([px, py], axis=1), uvpx[use])
        vals, c_ = read(use, bary)
        n_cl_in += c_
        wv = wgt.reshape(n, L * L)
        vv = vals.reshape(n, L * L)
        sw = wv.sum(axis=1)
        cb = bg.barycentric_many(np.stack([x0 + pi_ + 0.5, y0 + pj_ + 0.5], axis=1), uvpx[owner_c[pj_, pi_]])
        cv, _ = read(owner_c[pj_, pi_], cb)
        out[pj_, pi_] = np.where(sw > 0, (vv * wv).sum(axis=1) / np.maximum(sw, 1e-30), cv)
    # padding pixels
    grown, steps = bg.dilate_ids(owner_c, padding)
    pj, pi = np.nonzero((owner_c < 0) & (grown >= 0))
    n_cl_pad = 0
    n_no_nb = 0
    if len(pi):
        T = grown[pj, pi]
        cen = np.stack([x0 + pi + 0.5, y0 + pj + 0.5], axis=1)
        bc_c = bg.barycentric_many(cen, uvpx[T])
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
            bary = bg.barycentric_many(np.stack([ppx, ppy], axis=1), np.repeat(tri_uv[sel], L * L, axis=0))
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