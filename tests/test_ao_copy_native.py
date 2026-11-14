"""Apply's copy in C++ against the numpy copy, bit for bit (apply-native-copy journal, Session 2).

Plain Python with numpy (Blender's own Python, so the numpy is the one Apply runs with); no Blender needed.
ao_bake_core.py and ao_bake_copy.py are loaded by their paths, as the bake's second Blender loads the core. Checked,
each on random inputs, every float compared as its 64 bits:
- the sums: the DLL's pairwise summation equals np.add.reduce (1 to 300 values) and the row sums of 2D arrays;
- the raster: the DLL's owners of every sub-sample equal rasterize_ids' (overlapping, degenerate and far triangles,
  grids at any origin, 1 to 16 samples per pixel axis);
- read(): the DLL's values and clamped points equal copy_master's own read (taken from copy_master itself), with and
  without the surface-aware read, from whole arrays and from page files of tiles;
- copy_master whole: the image, the owners, the steps and every count of info equal between backend 'numpy' and
  'native' on synthetic meshes (creased height fields, stacked UV copies, holes in the master's filled mask), for
  small and large chunks, whole and paged masters, and the DLL at 1 and 12 threads identical.

To run (the DLL's threads under the CPU cap):
C:\\Users\\uray\\.claude\\tools\\cpucap\\cpucap.exe 50 G:\\e-jets-e2\\tools\\blender\\5.2\\python\\bin\\python.exe
    tests/test_ao_copy_native.py
"""

import importlib.util
import os
import shutil
import sys
import time

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location('_fss_ao_bake_core', os.path.join(REPO, 'fss_blender_tools',
                                                                                 'ao_bake_core.py'))
core = importlib.util.module_from_spec(spec)
sys.modules['_fss_ao_bake_core'] = core
spec.loader.exec_module(core)
nat = core.native_copy()
assert nat.load() is not None, nat.error()
assert nat.backend()[0] == 'native', nat.backend()


def bits(a):
    return np.ascontiguousarray(np.asarray(a, np.float64)).view(np.uint64)


def same_bits(a, b):
    return np.array_equal(bits(a), bits(b))


def test_sums(rng):
    n_cases = 0
    for n in list(range(1, 301)) + [512, 1000]:
        for scale in (1.0, 1e-3, 1e6):
            a = rng.standard_normal(n) * scale
            assert nat.total(a) == np.add.reduce(a), (n, nat.total(a), np.add.reduce(a))
            n_cases += 1
    for L in range(1, 17):
        a = rng.uniform(0, 1, (300, L * L)) * (rng.uniform(0, 1, (300, L * L)) > 0.4)
        s = a.sum(axis=1)
        m = a.reshape(300, L * L).mean(axis=1)
        for i in range(300):
            assert nat.total(a[i]) == s[i], (L, i)
            assert nat.total(a[i]) / float(L * L) == m[i], (L, i)
        n_cases += 300
    print(f'PASS: sums ({n_cases} arrays: pairwise summation as np.add.reduce, row sums and means of 1 to 256 values)')


def random_tris(rng, n, W, H):
    """Triangles in px: most small, some large, some stacked copies, some degenerate, some far away."""
    c = rng.uniform([0, 0], [W, H], (n, 1, 2))
    size = np.where(rng.uniform(0, 1, (n, 1, 1)) < 0.8, rng.uniform(0.5, 6, (n, 1, 1)), rng.uniform(6, 40, (n, 1, 1)))
    tri = c + rng.uniform(-1, 1, (n, 3, 2)) * size
    k = n // 10
    tri[:k] = tri[k:2 * k]  # stacked: the same triangles twice
    tri[2 * k:2 * k + 3, 2] = tri[2 * k:2 * k + 3, 0]  # degenerate
    tri[-3:] = -1e6
    snap = rng.uniform(0, 1, n) < 0.2  # vertices on the sample grid: ties on edges
    tri[snap] = np.round(tri[snap] * 4) / 4
    return tri


def test_raster(rng):
    n_s = 0
    for case in range(60):
        W, H = int(rng.integers(8, 40)), int(rng.integers(8, 40))
        uvpx = random_tris(rng, int(rng.integers(5, 80)), W, H)
        L = int(rng.integers(1, 17))
        gx, gy = int(rng.integers(-3, W // 2)), int(rng.integers(-3, H // 2))
        gw, gh = int(rng.integers(1, W)), int(rng.integers(1, H))
        ref, _cnt = core.rasterize_ids(uvpx, gw, gh, L, gx, gy)
        got = nat.raster(uvpx, gw, gh, L, gx, gy)
        assert np.array_equal(ref, got), (case, int((ref != got).sum()))
        n_s += ref.size
    print(f'PASS: raster (60 grids, {n_s} sub-samples: the owners of rasterize_ids)')


def height_mesh(rng, n=10, crease=True):
    """A height field of n x n quads over 2 cm, with a crease (sharp fold) through it: pos, tris, corner normals."""
    xs = np.linspace(0, 0.02, n + 1)
    X, Y = np.meshgrid(xs, xs)
    Z = 0.002 * np.sin(X * 300) * np.cos(Y * 250)
    if crease:
        Z += np.where(X > 0.01, (X - 0.01) * 1.5, 0.0)
    Z += rng.uniform(-1e-4, 1e-4, Z.shape)
    pos = np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1)
    tris = []
    for j in range(n):
        for i in range(n):
            a = j * (n + 1) + i
            tris += [(a, a + 1, a + n + 2), (a, a + n + 2, a + n + 1)]
    tris = np.array(tris, np.int64)
    P = pos[tris]
    fn = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
    fn /= np.linalg.norm(fn, axis=1, keepdims=True)
    return pos, tris, np.repeat(fn[:, None], 3, axis=1)


def make_master(rng, pos, tris, cn, holes=0.02, density=3000.0):
    m = core.build_master(pos, tris, cn, density, gutter=core.GUTTER, order=core.ORDER, mirror_open=core.MIRROR_OPEN,
                          fold_split=core.FOLD_SPLIT)
    owner, _cnt = core.rasterize_ids(m['muv'], m['W'], m['H'])
    grown, _st = core.dilate_ids(owner, 2)
    img = rng.integers(0, 65536, owner.shape).astype(np.uint16)
    img = np.where(owner >= 0, (np.arange(owner.size).reshape(owner.shape) * 37) % 65536, img).astype(np.uint16)
    filled = (grown >= 0) & (rng.uniform(0, 1, owner.shape) > holes)
    return dict(m, image=img, filled=filled, face_map=grown)


def target_uv(rng, pos, tris, W, H, stack=True):
    """UVs in target px: the flat layout scaled into the target, rotated a little, part of it stacked again."""
    uv = pos[:, :2] / 0.02
    ang = rng.uniform(-0.3, 0.3)
    R = np.array([[np.cos(ang), -np.sin(ang)], [np.sin(ang), np.cos(ang)]])
    uv = (uv - 0.5) @ R.T + 0.5
    uvpx = (uv[tris] * np.array([W * 0.8, H * 0.8]) + np.array([W * 0.1, H * 0.1]))
    if stack:
        k = len(tris) // 4
        uvpx[-k:] = uvpx[:k] + rng.uniform(-0.3, 0.3, (1, 1, 2))  # the last quarter over the first: stacked
    return uvpx


def capture_read(pos, tris, uvpx, master, ctx, surface_cos):
    """copy_master's own numpy read() (the closure it hands to _soften)."""
    got = {}
    real = core._soften

    def grab(sc, tri_ids, P3, vals, read, tn, soft_cos, chunk=core.COPY_CHUNK):
        got['read'] = read
        return vals, 0
    core._soften = grab
    try:
        core.copy_master(pos, tris, uvpx, np.zeros(len(tris), np.int64), master, (0, 0, 64, 64), core.K_MIN, 2,
                         surface_cos=surface_cos, ctx=ctx, soften=object(), backend='numpy')
    finally:
        core._soften = real
    return got['read']


def paged_copy(master, folder, cache_bytes):
    """The master as open_master pages it: tiled scratch files of the image and the map codes, a cache of tiles."""
    H, W = master['image'].shape
    pimg, pmap = os.path.join(folder, 'm.ao.page'), os.path.join(folder, 'm.ao.mappage')
    tw = core._TiledWriter(pimg, H, W, np.uint16)
    tw.write(master['image'][::-1])
    tw.close()
    tw = core._TiledWriter(pmap, H, W, np.int32)
    tw.write(core.map_code(master['face_map'], master['filled'])[::-1])
    tw.close()
    img = core.PagedArray(pimg, H, W, np.uint16, cache_bytes // 3)
    code = core.PagedArray(pmap, H, W, np.int32, cache_bytes - cache_bytes // 3)
    out = {k: v for k, v in master.items() if k not in ('image', 'filled', 'face_map', '_native')}
    out.update(image=img, filled=code.view(core.code_filled, bool), face_map=code.view(core.code_face, np.int32))
    return out, (img, code)


def test_read(rng, folder):
    n_pts = 0
    n_clamped = 0
    for case in range(6):
        pos, tris, cn = height_mesh(rng, n=int(rng.integers(4, 12)), crease=case % 2 == 0)
        master = make_master(rng, pos, tris, cn, holes=0.05)
        uvpx = target_uv(rng, pos, tris, 64, 64, stack=False)
        ctx = core.copy_context(pos, tris, uvpx, master, core.K_MIN, core.K_MAX)
        paged, arrays = paged_copy(master, folder, 4 * core.PAGE_TILE * core.PAGE_TILE * 6)
        try:
            for mst, label in ((master, 'whole'), (paged, 'paged')):
                for sc in (core.SURFACE_COS, None):
                    read = capture_read(pos, tris, uvpx, mst, ctx, sc)
                    n = 20000
                    t = rng.integers(0, len(tris), n)
                    b = rng.uniform(-0.3, 1.3, (n, 3))
                    b[: n // 2] /= b[: n // 2].sum(axis=1, keepdims=True)
                    ref, n_cl = read(t, b)
                    prep = nat.prepare(mst, (core.PagedArray, core._PagedView))
                    got, cl = nat.read(prep, ctx['tri_normal'], sc, sc is not None, t, b)
                    assert same_bits(ref, got), (case, label, sc, int((bits(ref) != bits(got)).sum()))
                    assert int(cl.sum()) == n_cl, (case, label, int(cl.sum()), n_cl)
                    n_pts += n
                    n_clamped += n_cl
        finally:
            for a in arrays:
                a.close()
    print(f'PASS: read ({n_pts} points, {n_clamped} clamped: values bit-identical and the same points clamped, '
          f'surface-aware and plain, whole and paged)')


def compare_copy(pos, tris, uvpx, master, crop, chunk, threads, pad=4, ref=None):
    kw = dict(padding=pad, outside_mode='tri', kmax=core.K_MAX, surface_cos=core.SURFACE_COS, chunk=chunk)
    ctx = core.copy_context(pos, tris, uvpx, master, core.K_MIN, core.K_MAX)
    tisl = np.zeros(len(tris), np.int64)
    if ref is None:
        ref = core.copy_master(pos, tris, uvpx, tisl, master, crop, core.K_MIN, ctx=ctx, backend='numpy', **kw)
    got = core.copy_master(pos, tris, uvpx, tisl, master, crop, core.K_MIN, ctx=ctx, backend='native',
                           threads=threads, **kw)
    assert ref[1]['copy'] == 'numpy' and got[1]['copy'] == 'native', (ref[1]['copy'], got[1]['copy'])
    assert same_bits(ref[0], got[0]), (int((bits(ref[0]) != bits(got[0])).sum()), crop, chunk, threads)
    for a, b in zip(ref[2:], got[2:]):
        assert np.array_equal(a, b)
    skip = ('copy', 'copy_why', 'copy_threads')
    assert {k: v for k, v in ref[1].items() if k not in skip} == {k: v for k, v in got[1].items() if k not in skip}, \
        (ref[1], got[1])
    return ref, got


def test_copy(rng, folder):
    px = 0
    stats = dict(inside=0, padding=0, clamped_in=0, clamped_pad=0, stacked=0, levels=set())
    t_np = t_nat = 0.0
    for case in range(8):
        pos, tris, cn = height_mesh(rng, n=int(rng.integers(4, 14)), crease=case % 2 == 0)
        # master px per target px from about 0.3 to over 8: 2 to 16 sub-samples per pixel axis
        master = make_master(rng, pos, tris, cn, holes=0.03 if case % 3 else 0.0,
                             density=(3000.0, 12000.0, 30000.0, 45000.0)[case % 4])
        W = H = int(rng.choice([48, 96, 160]))
        uvpx = target_uv(rng, pos, tris, W, H, stack=case % 4 != 3)
        if case == 5:  # part of the mesh not in the texture set, as Apply marks it
            uvpx[: len(tris) // 3] = -1e6
        bands = [(0, 0, W, H), (3, H // 3, W - 6, H // 4 + 9)]
        for crop in bands:
            for chunk in (core.COPY_CHUNK, 2000):
                t0 = time.time()
                ref = core.copy_master(pos, tris, uvpx, np.zeros(len(tris), np.int64), master, crop, core.K_MIN,
                                       padding=4, outside_mode='tri', kmax=core.K_MAX, surface_cos=core.SURFACE_COS,
                                       chunk=chunk, ctx=core.copy_context(pos, tris, uvpx, master, core.K_MIN,
                                                                          core.K_MAX), backend='numpy')
                t1 = time.time()
                for threads in (1, 12):
                    compare_copy(pos, tris, uvpx, master, crop, chunk, threads, ref=ref)
                t_np += t1 - t0
                t_nat += (time.time() - t1) / 2
                info = ref[1]
                px += int((ref[0] >= 0).sum())
                stats['inside'] += info['inside_px']
                stats['padding'] += info['padding_px']
                stats['clamped_in'] += info['clamped_inside_points']
                stats['clamped_pad'] += info['clamped_padding_points']
                stats['stacked'] += info['stacked_px']
                stats['levels'] |= set(info['k_levels'])
        # the same through page files with a cache of 4 tiles (tiles dropped and read again)
        paged, arrays = paged_copy(master, folder, 4 * core.PAGE_TILE * core.PAGE_TILE * 6)
        try:
            ref = compare_copy(pos, tris, uvpx, master, (0, 0, W, H), core.COPY_CHUNK, 12)[0]
            got = compare_copy(pos, tris, uvpx, paged, (0, 0, W, H), core.COPY_CHUNK, 12)[1]
            assert same_bits(ref[0], got[0])
        finally:
            for a in arrays:
                a.close()
    lv = stats['levels']
    assert {2, 16} <= lv and any(3 <= L <= 11 for L in lv) and any(12 <= L < 16 for L in lv), lv
    print(f"PASS: copy_master (8 meshes, 2 windows, 2 chunk sizes: numpy and C++ at 1 and 12 threads bit-identical, "
          f"{px} px written, {stats['inside']} inside, {stats['padding']} padding, {stats['clamped_in']} + "
          f"{stats['clamped_pad']} clamped points, {stats['stacked']} stacked px, levels {sorted(stats['levels'])}; "
          f"paged with a 4-tile cache equal to whole; numpy {t_np:.1f} s, C++ {t_nat:.1f} s)")


def test_fallback():
    """FSS_AO_COPY=numpy and a missing DLL: copy_master runs numpy and says why."""
    os.environ[nat.ENV] = 'numpy'
    try:
        assert nat.backend() == ('numpy', f'{nat.ENV}=numpy is set'), nat.backend()
    finally:
        del os.environ[nat.ENV]
    old = nat.LIB_DIR
    nat.LIB_DIR = os.path.join(old, 'missing')
    nat.reset()
    try:
        use, why = nat.backend()
        assert use == 'numpy' and 'missing' in why, (use, why)
    finally:
        nat.LIB_DIR = old
        nat.reset()
    assert nat.backend()[0] == 'native'
    print('PASS: fallback (FSS_AO_COPY=numpy and a missing DLL give the numpy copy, with the reason)')


if __name__ == '__main__':
    t0 = time.time()
    rng = np.random.default_rng(20261114)
    folder = os.path.join(REPO, 'tests', '_work', 'ao_copy_native')
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder)
    try:
        test_sums(rng)
        test_raster(rng)
        test_read(rng, folder)
        test_copy(rng, folder)
        test_fallback()
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    print(f'ALL AO COPY NATIVE TESTS PASSED ({time.time() - t0:.1f} s)')
