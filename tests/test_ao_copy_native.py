"""The C++ DLL (fss_ao_copy.dll) of Apply and of the bake (apply-native-copy and bake-post-native journals).

Plain Python with numpy (Blender's own Python, so the numpy is the one Apply runs with); no Blender needed but for
the PNG reads compared with Blender's. ao_bake_core.py and ao_bake_copy.py are loaded by their paths, as the bake's
second Blender loads the core. Decision 6 (apply-native-copy journal, Session 15) removed the Python code each part of
the DLL replaced; before that, the Python code's outputs of every case below were recorded (tests/data/
ao_native_reference.json, tests/ao_native_reference.py): each case now compares the DLL's outputs with them (REF), and
the DLL at 1, 12 and os.cpu_count() threads with itself. Checked, each on seeded random inputs, every float as its 64
bits:
- the sums: the DLL's pairwise summation equals np.add.reduce (1 to 300 values) and the row sums of 2D arrays;
- the raster: the owners of every sub-sample (overlapping, degenerate and far triangles, grids at any origin, 1 to 16
  samples per pixel axis);
- read(): the DLL's values and clamped points, with and without the surface-aware read, from whole arrays and from
  page files of tiles;
- copy_master: the image, the owners, the steps and every count of info on synthetic meshes (creased height fields,
  stacked UV copies, holes in the master's filled mask), for small and large chunks, whole and paged masters;
- the opening (Session 4): masters written by the add-on's writers (MasterWriter, the JPEG XL Writer; sizes not
  multiples of 256, 1 px wide or high, more than one tile row, an empty map), each kind (AO, curvature, raw): both
  page files; a truncated .jxl, a truncated or corrupt .ao.map, a wrong size, a page file that cannot be created: an
  OSError naming the file, no page file left;
- PNG files (Session 7, decision 4): images of random and smooth values (1 x 1 to 1300 x 1100 px, 1 to 4 channels, 8
  and 16 bits) written by the C++ writer in 5 row blockings: the bytes the same, each file decoded by the C++ reader
  and by Blender (one background Blender, Non-Color) to the rows handed in; the reader on files with each of the five
  filters and mixed (a numpy filter encoder, checked by the byte loop and by Python's zlib) and on real textures with
  Average or Paeth rows (read from G:\\e-jets-e2, never written) against Blender's read; the errors (truncated,
  corrupt, an unknown colour type, a palette, interlace, a bad filter type, a missing folder, a full disk simulated by
  fss_ao_png_test_limit, rows missing, abort): an OSError naming the file, no file left by the writer;
- the per-pixel work around the copy (Session 11, interface version 4): the raster (owners and counts of
  rasterize_ids and raster_window; random, stacked, degenerate, sliver and far triangles, corners on pixel centres and
  edges, NaN and inf corners, k 1 to 16, windows clipped by the grid, more triangles than a band; island_labels of
  several meshes), the dilation (dilate_ids' owners and steps; masks, 0 to 40 iterations, grids 1 px wide or high),
  the UV islands (uv_islands' labels; seams, UVs moved about the tolerance, stacked and degenerate triangles, NaN UVs),
  Soften (called directly and inside copy_master; convex and concave folds, several edges near a pixel, whole and
  paged masters, surface-aware and plain read; the folds by soften_context with a brute-force KD-tree when mathutils
  is missing);
- the bake's post-processing (bake-post-native journal, interface version 5): compose_block (corner pairs, skirt
  faces, rectangles at window edges, empty windows, windows of 1 px, halos clamped at the master's edges, no skirt, no
  corner pairs, stray baked pixels), compose_whole and bake_paged (strips of several windows); the .ao.map writer's
  bytes for any thread count and blocking of the rows, its errors;
- Refresh's scene rule and mesh hash (bake-post-native journal Session 5, interface version 6): the own boxes, their
  separating-axis gaps, the motion test of (object, occluder) pairs, near of whole scenes (queries at a gap exactly and
  just under it), mesh_hash with and without the CPU's SHA instructions, on the seeded cases of
  tests/ao_scene_rule_cases.py, bit for bit equal to the Python code's values (tests/data/ao_scene_rule_reference.json);
- decision 6: with the DLL not loadable (its folder moved) or libjxl not loadable (FSS_AO_BAKE_NO_JXL), unavailable()
  says why on one line and every part refuses with that reason (an OSError); back in place, all runs again.

To run (the DLL's threads under the CPU cap; the argument only=pixels stops after the Session 11 tests, only=compose
runs the bake-post-native composition tests alone, only=scene_rule the scene rule's):
C:\\Users\\uray\\.claude\\tools\\cpucap\\cpucap.exe 50 G:\\e-jets-e2\\tools\\blender\\5.2\\python\\bin\\python.exe
    tests/test_ao_copy_native.py
"""

import hashlib
import importlib.util
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import time
import zlib

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location('_fss_ao_bake_core', os.path.join(REPO, 'fss_blender_tools',
                                                                                 'ao_bake_core.py'))
core = importlib.util.module_from_spec(spec)
sys.modules['_fss_ao_bake_core'] = core
spec.loader.exec_module(core)
nat = core.native_copy()
assert nat.load() is not None, nat.error()
assert nat.unavailable() is None, nat.unavailable()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ao_native_reference import Reference  # noqa: E402  (decision 6: the Python code's values, recorded)

REF = Reference('harness')
INFO_SKIP = ('copy', 'copy_why', 'copy_threads', 'raster', 'dilate', 'soften', 'padding_at_folds')
# the references were recorded before auto-bake decision 78: the padding hinged across every edge, also sharp folds
# (test_fold_padding checks the rule of decision 78)
core.PADDING_FOLD_COS = -2.0


def copy_values(res):
    """What a copy_master result is compared by: the image, the owners, the steps, the counts, info but which code
    ran."""
    return (res[0], res[2], res[3], res[4], {k: v for k, v in res[1].items() if k not in INFO_SKIP})


def rng_of(name):
    """Each test's own seeded generator, so a test's inputs do not depend on the tests before it."""
    return np.random.default_rng([20261114, zlib.crc32(name.encode())])


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
        REF.check(f'raster/{case:02d}', ref)
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


def write_tiles(path, a, T=core.PAGE_TILE):
    """An (H, W) array as open_master's page file (core.PagedArray reads it): tiles of T x T px in the array's order
    (tile (ty, tx) holds rows ty * T.., columns tx * T..; row 0 the bottom), padded with zeros."""
    H, W = a.shape
    ntx, nty = -(-W // T), -(-H // T)
    buf = np.zeros((nty * T, ntx * T), a.dtype)
    buf[:H, :W] = a
    with open(path, 'wb') as f:
        f.write(np.ascontiguousarray(buf.reshape(nty, T, ntx, T).transpose(0, 2, 1, 3)).tobytes())


def paged_copy(master, folder, cache_bytes):
    """The master as open_master pages it: tiled scratch files of the image and the map codes, a cache of tiles."""
    H, W = master['image'].shape
    pimg, pmap = os.path.join(folder, 'm.ao.page'), os.path.join(folder, 'm.ao.mappage')
    write_tiles(pimg, np.asarray(master['image'], np.uint16))
    write_tiles(pmap, core.map_code(master['face_map'], master['filled']))
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
                    n = 20000
                    t = rng.integers(0, len(tris), n)
                    b = rng.uniform(-0.3, 1.3, (n, 3))
                    b[: n // 2] /= b[: n // 2].sum(axis=1, keepdims=True)
                    prep = nat.prepare(mst, (core.PagedArray, core._PagedView))
                    got, cl = nat.read(prep, ctx['tri_normal'], sc, sc is not None, t, b)
                    n_cl = int(cl.sum())
                    REF.check(f'read/{case}/{label}/{"surface" if sc is not None else "plain"}', got, n_cl)
                    n_pts += n
                    n_clamped += n_cl
        finally:
            for a in arrays:
                a.close()
    print(f'PASS: read ({n_pts} points, {n_clamped} clamped: values and clamped points as recorded, surface-aware and '
          f'plain, whole and paged)')


def compare_copy(pos, tris, uvpx, master, crop, chunk, threads=None, pad=4):
    """copy_master at each of `threads` (default 1, 12 and os.cpu_count()): the image (its bits), the owners, the
    steps and info (but the threads) the same. Returns the first."""
    threads = THREADS_ALL if threads is None else threads
    kw = dict(padding=pad, outside_mode='tri', kmax=core.K_MAX, surface_cos=core.SURFACE_COS, chunk=chunk)
    ctx = core.copy_context(pos, tris, uvpx, master, core.K_MIN, core.K_MAX)
    tisl = np.zeros(len(tris), np.int64)
    res = [core.copy_master(pos, tris, uvpx, tisl, master, crop, core.K_MIN, ctx=ctx, threads=t, **kw)
           for t in threads]
    ref = res[0]
    for t, got in zip(threads, res):
        assert got[1]['copy'] == 'native' and got[1]['copy_threads'] == nat.threads_of(t), got[1]
        assert same_bits(ref[0], got[0]), (int((bits(ref[0]) != bits(got[0])).sum()), crop, chunk, t)
        for a, b in zip(ref[2:], got[2:]):
            assert np.array_equal(a, b)
        assert copy_values(ref)[4] == copy_values(got)[4], (ref[1], got[1])
    return ref


def test_copy(rng, folder):
    px = 0
    stats = dict(inside=0, padding=0, clamped_in=0, clamped_pad=0, stacked=0, levels=set())
    t_nat = 0.0
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
        for bi, crop in enumerate(bands):
            for chunk in (core.COPY_CHUNK, 2000):
                t0 = time.time()
                ref = compare_copy(pos, tris, uvpx, master, crop, chunk)
                REF.check(f'copy/{case}/{bi}/{chunk}', *copy_values(ref))
                t_nat += (time.time() - t0) / len(THREADS_ALL)
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
            ref = compare_copy(pos, tris, uvpx, master, (0, 0, W, H), core.COPY_CHUNK, (12,))
            ref_p = compare_copy(pos, tris, uvpx, paged, (0, 0, W, H), core.COPY_CHUNK, (12,))
            REF.check(f'copy/{case}/paged', *copy_values(ref_p))
            assert same_bits(ref[0], ref_p[0])
        finally:
            for a in arrays:
                a.close()
    lv = stats['levels']
    assert {2, 16} <= lv and any(3 <= L <= 11 for L in lv) and any(12 <= L < 16 for L in lv), lv
    print(f"PASS: copy_master (8 meshes, 2 windows, 2 chunk sizes: as recorded, at {THREADS_ALL} threads bit-identical, "
          f"{px} px written, {stats['inside']} inside, {stats['padding']} padding, {stats['clamped_in']} + "
          f"{stats['clamped_pad']} clamped points, {stats['stacked']} stacked px, levels {sorted(stats['levels'])}; "
          f"paged with a 4-tile cache equal to whole; {t_nat:.1f} s per thread count)")


OPEN_SIZES = [(1, 1), (1, 700), (700, 1), (255, 257), (256, 256), (513, 300), (1300, 1100), (2600, 2300)]


def master_image(rng, W, H, k):
    """A master-like uint16 image: smooth shading, flat areas, noise."""
    y, x = np.mgrid[0:H, 0:W]
    img = 30000 + 20000 * np.sin(x / (7.0 + k)) * np.cos(y / 11.0)
    img += rng.normal(0, 300 * (k % 3), (H, W))
    img[(x // 37 + y // 29) % 5 == 0] = 65535
    return np.clip(img, 0, 65535).astype(np.uint16)


def write_master(folder, stem, img, code, extra=()):
    """A master's files as the bake writes them (MasterWriter: the AO as JPEG XL, the .ao.map, the layout), and
    images of other kinds (curvature, raw) of the same size as the JPEG XL Writer writes them."""
    H, W = img.shape
    m = dict(muv=np.zeros((1, 3, 2)), island=np.zeros(1, np.int64), density=1.0, W=W, H=H,
             rects=np.zeros((1, 4), np.int64), gutter=2, degenerate=np.zeros(0, np.int64))
    w = core.MasterWriter(folder, stem, W, H, threads=4)
    assert w.format == 'jxl' and w.map.by == 'C++ (4 threads)', (w.format, w.map.by)
    try:
        for top in range(0, H, 256):
            bot = min(H, top + 256)
            w.write_rows(img[H - bot:H - top][::-1], code[H - bot:H - top][::-1])
        w.finish(m, np.zeros(1, np.int64), {})
    except BaseException:
        w.abort()
        raise
    lib = core.jxl()
    for kind, other in extra:
        jw = lib.Writer(core.image_paths(folder, stem, kind)[0], W, H, threads=4)
        jw.write(other[::-1])
        jw.close()


def page_bytes(folder, stem, kind, threads):
    """open_master's two page files (bytes), its 'open', the image read through its pages, its stats; the files are
    gone after close()."""
    m = core.open_master(folder, stem, kind=kind, threads=threads)
    try:
        paths = [p.path for p in m['pages']]
        data = []
        for p in paths:
            with open(p, 'rb') as f:
                data.append(f.read())
        img = m['image'][np.arange(m['H'])[:, None], np.arange(m['W'])[None, :]]
    finally:
        m['close']()
    assert not any(os.path.exists(p) for p in paths), paths
    return data, m['open'], img, m.get('open_stats')


def scratch_left(folder):
    return [f for f in os.listdir(folder) if f.endswith(('.page', '.mappage', '.tmp', '.raw'))]


def test_fold_padding():
    """Auto-bake decision 78: a padding pixel beyond an edge where the faces fold by more than 30 degrees continues its
    own face (a wall's padding holds the wall's AO, not the top's past its rim); below 30 degrees (a smooth seam) it
    still reads the neighbour hinged flat across the edge, as before."""
    s, c = 0.01 * math.sin(math.radians(10)), 0.01 * math.cos(math.radians(10))
    pos = np.array([(0, 0, 0), (0.01, 0, 0), (0.01, 0, 0.01), (0, 0, 0.01),  # wall A (normal -y)
                    (0.01, 0.01, 0.01), (0, 0.01, 0.01),  # top B, folded 90 degrees at A's upper edge (normal +z)
                    (0.05, 0, 0), (0.06, 0, 0), (0.06, 0, 0.01), (0.05, 0, 0.01),  # wall A2
                    (0.06, -s, 0.01 + c), (0.05, -s, 0.01 + c)], np.float64)  # B2, on at 10 degrees: a smooth seam
    tris = np.array([(0, 1, 2), (0, 2, 3), (3, 2, 4), (3, 4, 5), (6, 7, 8), (6, 8, 9), (9, 8, 10), (9, 10, 11)], np.int64)
    P = pos[tris]
    fn = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
    fn /= np.linalg.norm(fn, axis=1, keepdims=True)
    m = core.build_master(pos, tris, np.repeat(fn[:, None], 3, axis=1), 6000.0, gutter=core.GUTTER, order=core.ORDER,
                          mirror_open=core.MIRROR_OPEN, fold_split=core.FOLD_SPLIT)
    owner, _cnt = core.rasterize_ids(m['muv'], m['W'], m['H'])
    grown, _st = core.dilate_ids(owner, 2)
    dark = np.isin(grown, (0, 1, 4, 5))  # the walls dark, the tops light
    master = dict(m, image=np.where(dark, 20000, 60000).astype(np.uint16), filled=grown >= 0, face_map=grown)
    # the target: each face pair in its own two islands (UV seams at the fold), 30 px apart
    W = H = 160
    uv = np.zeros((len(pos), 2))
    uvpx = np.zeros((len(tris), 3, 2))
    for t, (a, b, cc) in enumerate(tris):
        for k, v in enumerate((a, b, cc)):
            x, y, z = pos[v]
            if t < 2:
                uvpx[t, k] = (10 + x * 1500, 10 + z * 1500)
            elif t < 4:
                uvpx[t, k] = (70 + x * 1500, 10 + y * 1500)
            elif t < 6:
                uvpx[t, k] = (10 + (x - 0.05) * 1500, 80 + z * 1500)
            else:
                uvpx[t, k] = (70 + (x - 0.05) * 1500, 80 + (0.0 if v in (8, 9) else 0.01) * 1500)
    del uv
    tisl = np.zeros(len(tris), np.int64)
    kw = dict(padding=6, outside_mode='tri', kmax=core.K_MAX, surface_cos=core.SURFACE_COS, threads=1)
    new = core.copy_master(pos, tris, uvpx, tisl, master, (0, 0, W, H), core.K_MIN, fold_cos=core.SURFACE_COS, **kw)
    old = core.copy_master(pos, tris, uvpx, tisl, master, (0, 0, W, H), core.K_MIN, fold_cos=-2.0, **kw)
    out_n, info_n, own, steps = new[0], new[1], new[2], new[3]
    out_o = old[0]
    gw, _ = core.dilate_ids(own, 6)
    pad = (own < 0) & (out_n >= 0)
    wall_val = float(np.median(out_n[(own == 0) | (own == 1)]))
    top_val = float(np.median(out_n[(own == 2) | (own == 3)]))
    wall_pad = pad & np.isin(gw, (0, 1))
    top_pad = pad & np.isin(gw, (2, 3))
    assert abs(wall_val - 20000 / 65535) < 2e-3 and abs(top_val - 60000 / 65535) < 2e-3, (wall_val, top_val)
    # decision 78: every padding pixel of the fold pair holds its own face's AO
    err_wall = float(np.abs(out_n[wall_pad] - wall_val).max())
    err_top = float(np.abs(out_n[top_pad] - top_val).max())
    assert err_wall < 2e-3 and err_top < 2e-3, (err_wall, err_top)
    # before it, the wall's padding past the rim took the top's AO
    took = int((np.abs(out_o[wall_pad] - top_val) < 2e-3).sum())
    assert took > 0 and info_n['padding_at_folds'] > 0 and old[1]['padding_at_folds'] == 0, (took, info_n)
    # the smooth seam (10 degrees): as before, bit for bit
    smooth = (gw >= 4) | (own >= 4)
    assert same_bits(np.where(smooth, out_n, 0.0), np.where(smooth, out_o, 0.0))
    print(f"PASS: test_fold_padding (90 degree fold: {int(wall_pad.sum())} wall and {int(top_pad.sum())} top padding "
          f"px within {max(err_wall, err_top):.5f} of their own face, {info_n['padding_at_folds']} px at folds; the "
          f"old rule gave {took} wall padding px the top's AO; the 10 degree seam unchanged)")


def test_open(rng, folder):
    lib = core.jxl()
    assert lib.available(), lib.error()
    n_masters = n_files = n_bytes = 0
    t_nat = 0.0
    most_open = 0
    for k, (W, H) in enumerate(OPEN_SIZES):
        stem = f'open{k}'
        img = master_image(rng, W, H, k)
        if k == 3:  # an empty map: no face, nothing filled
            code = np.zeros((H, W), np.int32)
        elif k % 2:
            code = rng.integers(0, 2 ** 31 - 1, (H, W)).astype(np.int32)
        else:
            face = (np.arange(W)[None, :] // 5 + np.arange(H)[:, None] // 3) % 400 - 1
            code = core.map_code(face, rng.uniform(0, 1, (H, W)) > 0.2)
        write_master(folder, stem, img, code, extra=(('curv', img[::-1, ::-1].copy()), ('ao.raw', img ^ 0x2A55)))
        n_masters += 1
        for kind in ('ao', 'curv', 'ao.raw'):
            want = img if kind == 'ao' else (img[::-1, ::-1] if kind == 'curv' else img ^ 0x2A55)
            T = core.PAGE_TILE
            ref = None
            for threads in THREADS_ALL:
                t0 = time.time()
                got, how, got_img, st = page_bytes(folder, stem, kind, threads)
                t_nat += time.time() - t0
                assert how == f"C++ ({threads} thread{'s' if threads != 1 else ''})", how
                if ref is None:
                    ref = got
                    REF.check(f'open/{k}/{kind}', ref[0], ref[1])
                    assert len(ref[0]) == -(-W // T) * -(-H // T) * T * T * 2 and len(ref[1]) == 2 * len(ref[0])
                assert got[0] == ref[0], (W, H, kind, threads, 'image')
                assert got[1] == ref[1], (W, H, kind, threads, 'map')
                assert np.array_equal(got_img, want), (W, H, kind, threads)
                most_open = max(most_open, st['most_open_tile_rows'])
                n_files += 2
                n_bytes += len(got[0]) + len(got[1])
        assert not scratch_left(folder), scratch_left(folder)
    print(f"PASS: open ({n_masters} masters of {OPEN_SIZES[0]} to {OPEN_SIZES[-1]} px, AO, curvature and raw: "
          f"{n_files} page files of the DLL at {THREADS_ALL} threads byte-identical and as recorded, "
          f"{n_bytes / 2 ** 20:.0f} MiB compared; at most {most_open} rows of tiles mapped at a time; "
          f"{t_nat / len(THREADS_ALL):.1f} s per thread count)")


def expect_open_error(folder, stem, words, kind='ao'):
    """open_master by the DLL fails with an OSError naming the file (words: in the message); no page file left."""
    try:
        m = core.open_master(folder, stem, kind=kind, threads=12)
    except OSError as exc:
        err = exc
    else:
        m['close']()
        raise AssertionError(f'{stem}: opened, an error expected ({words})')
    msg = str(err)
    assert isinstance(err, nat.OpenError), type(err)
    assert all(w in msg for w in words), (msg, words)
    assert not scratch_left(folder), scratch_left(folder)
    return msg


def test_open_errors(rng, folder):
    W, H = 700, 530
    img = master_image(rng, W, H, 1)
    code = rng.integers(0, 2 ** 31 - 1, (H, W)).astype(np.int32)
    msgs = {}

    def fresh(stem):
        write_master(folder, stem, img, code)
        return core.master_paths(folder, stem)

    def cut(path, keep):
        with open(path, 'rb') as f:
            data = f.read()
        with open(path, 'wb') as f:
            f.write(keep(bytearray(data)))
    # a truncated .jxl
    jx, mp, _npz = fresh('err_jxl')
    cut(jx, lambda d: bytes(d[:len(d) // 2]))
    msgs['truncated jxl'] = expect_open_error(folder, 'err_jxl', ['err_jxl.ao.jxl'])
    # a truncated .ao.map
    jx, mp, _npz = fresh('err_map')
    cut(mp, lambda d: bytes(d[:len(d) // 2]))
    msgs['truncated map'] = expect_open_error(folder, 'err_map', ['err_map.ao.map', f'of {H} rows'])

    def corrupt(d):
        for i in range(len(d) // 3, len(d) // 3 + 64):
            d[i] ^= 0xA5
        return bytes(d)
    # a corrupt .ao.map (bytes of its zlib stream changed)
    jx, mp, _npz = fresh('err_zlib')
    cut(mp, corrupt)
    msgs['corrupt map'] = expect_open_error(folder, 'err_zlib', ['err_zlib.ao.map'])

    def magic(d):
        d[:8] = b'NOTAOMAP'
        return bytes(d)
    # not an AO map
    jx, mp, _npz = fresh('err_magic')
    cut(mp, magic)
    msgs['not a map'] = expect_open_error(folder, 'err_magic', ['err_magic.ao.map', 'not an AO map'])
    # a wrong size: the map 1 px wider, the image 1 px higher than the layout
    jx, mp, _npz = fresh('err_wmap')
    w = nat.MapWriter(mp, W + 1, H, level=1, threads=4)
    w.write(np.zeros((H, W + 1), np.int32))
    w.close()
    msgs['map size'] = expect_open_error(folder, 'err_wmap', ['err_wmap.ao.map', f'{W + 1} x {H} px',
                                                              f'the layout says {W} x {H}'])
    jx, mp, _npz = fresh('err_wimg')
    jw = core.jxl().Writer(jx, W, H + 1, threads=4)
    jw.write(np.zeros((H + 1, W), np.uint16))
    jw.close()
    msgs['image size'] = expect_open_error(folder, 'err_wimg', ['err_wimg.ao.jxl', f'{W} x {H + 1} px',
                                                                f'the layout says {W} x {H}'])
    # a page file that cannot be created (its folder missing): the other one not left either
    jx, mp, _npz = fresh('err_io')
    bad = os.path.join(folder, 'missing_folder', 'x.ao.mappage')
    good = os.path.join(folder, 'err_io.ao.page')
    try:
        nat.open_pages(core.jxl().LIB_DIR, jx, mp, good, bad, W, H, core.PAGE_TILE, 12)
    except nat.OpenError as exc:
        msgs['page not created'] = str(exc)
    else:
        raise AssertionError('a page file in a missing folder was created')
    assert 'x.ao.mappage' in msgs['page not created'] and not os.path.exists(good), msgs['page not created']
    # libjxl not in the folder given
    try:
        nat.open_pages(os.path.join(folder, 'no_jxl'), jx, mp, good, good + 'map', W, H, core.PAGE_TILE, 12)
    except nat.OpenError as exc:
        msgs['no libjxl'] = str(exc)
    else:
        raise AssertionError('opened without libjxl')
    assert 'jxl.dll' in msgs['no libjxl'] and not os.path.exists(good), msgs['no libjxl']
    assert not scratch_left(folder), scratch_left(folder)
    print('PASS: open errors (each an OSError naming the file, no page file left): '
          + '; '.join(f'{k}: {v}' for k, v in msgs.items()))


def refuses(fn, words):
    """fn raises an OSError with all of `words` in its message (no Python code runs instead). Returns the message."""
    try:
        fn()
    except OSError as exc:
        msg = str(exc)
        assert all(w in msg for w in words), (msg, words)
        return msg
    raise AssertionError(f'ran without the library ({words})')


def test_unavailable(rng, folder):
    """Decision 6: the DLL and libjxl are required. With the DLL not loadable (ao_bake_copy.LIB_DIR pointed at a
    missing folder) or libjxl not loadable (FSS_AO_BAKE_NO_JXL): unavailable() says why on one line, require() raises
    it, and each part refuses with an OSError (the raster, the dilation, the UV islands, island labels, the copy, the
    opening, the composition, the master's writer, the PNG writer and reader); back in place, all runs again."""
    W, H = 300, 200
    write_master(folder, 'na', master_image(rng, W, H, 2), rng.integers(0, 1000, (H, W)).astype(np.int32))
    pages = page_bytes(folder, 'na', 'ao', 12)[0]
    png = os.path.join(folder, 'na.png')
    core.write_png_int(png, rng.integers(0, 65536, (20, 30, 3)).astype(np.uint16), 16)
    pos, tris, cn = height_mesh(rng, n=6)
    master = make_master(rng, pos, tris, cn)
    uvpx = target_uv(rng, pos, tris, 48, 48)
    wt = core.weld_ids(pos)[tris]
    isl = core.uv_islands(wt, uvpx)
    owner = core.rasterize_ids(uvpx, 48, 48)[0]
    m_c, M16, baked = compose_master(rng, 3)
    parts = dict(
        rasterize_ids=lambda: core.rasterize_ids(uvpx, 48, 48),
        raster_window=lambda: core.raster_window(uvpx, 48, 48),
        dilate_ids=lambda: core.dilate_ids(owner, 3),
        uv_islands=lambda: core.uv_islands(wt, uvpx),
        island_labels=lambda: core.island_labels([(uvpx, isl)], 48, 48, 3),
        copy_master=lambda: core.copy_master(pos, tris, uvpx, np.zeros(len(tris), np.int64), master, (0, 0, 48, 48),
                                             core.K_MIN, 4, surface_cos=core.SURFACE_COS),
        open_master=lambda: core.open_master(folder, 'na', threads=4),
        compose_whole=lambda: core.compose_whole(m_c, M16, baked),
        MasterWriter=lambda: core.MasterWriter(folder, 'na2', W, H, threads=4),
        png_writer=lambda: core.png_writer(os.path.join(folder, 'na2.png'), W, H, 16, 1),
        read_png=lambda: core.read_png(png),
        mesh_hash=lambda: core.mesh_hash(dict(tris=tris, co=pos, cn=cn)),
        scene_near=lambda: nat.SceneRule(np.zeros((1, 8, 3)), np.eye(4)[None], np.eye(4)[None, None], [False], [0],
                                         1e-4, 1e-4).near([0], [0], [0.1], [0]),
        scene_moves=lambda: nat.SceneRule(np.zeros((2, 8, 3)), np.eye(4)[None].repeat(2, 0),
                                          np.eye(4)[None, None].repeat(2, 0), [False, False], [], 1e-4,
                                          1e-4).moves([(0, 1)]))
    old = nat.LIB_DIR
    nat.LIB_DIR = os.path.join(folder, 'no_dll_here')
    nat.reset()
    try:
        why_dll = nat.unavailable()
        assert why_dll.startswith(f'{nat.DLL} could not be loaded (OSError: ') and 'missing' in why_dll, why_dll
        assert '\n' not in why_dll
        msg = refuses(nat.require, ['AO Bake not available: ', why_dll])
        n_dll = 0
        for name, fn in parts.items():
            refuses(fn, ['AO Bake not available', f'{nat.DLL} could not be loaded'])
            n_dll += 1
    finally:
        nat.LIB_DIR = old
        nat.reset()
    lib = core.jxl()
    os.environ[lib.DISABLE_ENV] = '1'
    lib.reset()
    try:
        why_jxl = nat.unavailable()
        assert why_jxl == f'the JPEG XL library (libjxl) could not be loaded (OSError: {lib.DISABLE_ENV} is set)', \
            why_jxl
        refuses(nat.require, ['AO Bake not available: ', why_jxl])
        refuses(parts['open_master'], ['JPEG XL library is not loaded', 'na.ao.jxl'])
        refuses(parts['MasterWriter'], ['JPEG XL library is not loaded', 'na2.ao.jxl'])
    finally:
        del os.environ[lib.DISABLE_ENV]
        lib.reset()
    assert nat.unavailable() is None and lib.available()
    assert page_bytes(folder, 'na', 'ao', 12)[0] == pages
    for name in ('na2.ao.jxl.tmp', 'na2.ao.map.tmp', 'na2.png', 'na2.ao.jxl', 'na2.ao.map'):
        assert not os.path.exists(os.path.join(folder, name)), name
    for name in os.listdir(folder):
        if name.startswith('na'):
            os.remove(os.path.join(folder, name))
    print(f'PASS: unavailable (the DLL not loadable: "{why_dll}", {n_dll} parts refuse ("{msg[:40]}..."); libjxl not '
          f'loadable: "{why_jxl}", the opening and the master\'s writer refuse; back in place: the same page files)')


# ---------------------------------------------------------------------------------------------------------------------
# Session 11: the raster, the dilation, the UV islands and Soften in C++ (interface version 4)
# ---------------------------------------------------------------------------------------------------------------------

THREADS_ALL = (1, 12, os.cpu_count() or 2)


def raster_tris(rng, n, W, H):
    """random_tris plus slivers, corners on pixel centres and on pixel edges, and triangles with NaN or inf corners."""
    tri = random_tris(rng, n, W, H)
    k = max(1, n // 12)
    tri[3 * k:4 * k, 2] = tri[3 * k:4 * k, 0] + rng.uniform(-1e-7, 1e-7, (k, 2))  # slivers
    tri[4 * k:5 * k] = np.floor(tri[4 * k:5 * k]) + 0.5  # corners on pixel centres
    tri[5 * k:6 * k] = np.round(tri[5 * k:6 * k])  # corners on pixel edges
    if n > 20:
        tri[6 * k, 1, 0] = np.nan
        tri[6 * k + 1, 2, 1] = np.inf
        tri[6 * k + 2, 0, 0] = -np.inf
    return tri


def test_raster_ids(rng):
    """fss_ao_copy_raster_ids against rasterize_ids and raster_window (owners and counts)."""
    n_s = n_grids = 0
    for case in range(80):
        W, H = int(rng.integers(1, 50)), int(rng.integers(1, 50))
        if case % 9 == 0:
            W = 1
        elif case % 9 == 1:
            H = 1
        n = int(rng.integers(1, 30)) if case % 3 else int(rng.integers(100, 600))  # more triangles than a band
        uvpx = raster_tris(rng, n, max(W, 4), max(H, 4))
        k = int(rng.integers(1, 17)) if case % 4 else 1
        gx, gy = int(rng.integers(-6, max(W // 2, 1))), int(rng.integers(-6, max(H // 2, 1)))
        gw, gh = int(rng.integers(1, W + 8)), int(rng.integers(1, H + 8))  # windows clipped by the triangles' grid
        eps = (1e-9, 0.0, -1e-7)[case % 3]
        ref = core.rasterize_ids(uvpx, gw, gh, k, gx, gy, eps, threads=1)
        ref_w = core.raster_window(uvpx, gw, gh, k, gx, gy, eps, threads=1)
        REF.check(f'raster_ids/{case:02d}', ref[0], ref[1], ref_w[0], ref_w[1])
        for threads in THREADS_ALL:
            got = core.rasterize_ids(uvpx, gw, gh, k, gx, gy, eps, threads=threads)
            assert np.array_equal(ref[0], got[0]) and np.array_equal(ref[1], got[1]), (case, threads, 'ids')
            assert got[0].dtype == ref[0].dtype and got[1].dtype == ref[1].dtype
            got = core.raster_window(uvpx, gw, gh, k, gx, gy, eps, threads=threads)
            assert np.array_equal(ref_w[0], got[0]) and np.array_equal(ref_w[1], got[1]), (case, threads, 'window')
        n_s += ref[0].size
        n_grids += 1
    # island_labels: several meshes' labels rasterized into one image (keep) and grown
    n_px = 0
    for case in range(6):
        S = int(rng.choice([64, 96, 130]))
        parts = []
        for m in range(3):
            uvpx = raster_tris(rng, int(rng.integers(20, 120)), S, S)
            parts.append((uvpx, rng.integers(0, 5, len(uvpx)).astype(np.int64)))
        ref = core.island_labels(parts, S, S, 3 + case, threads=1)
        REF.check(f'island_labels/{case}', ref)
        for threads in THREADS_ALL:
            got = core.island_labels(parts, S, S, 3 + case, threads=threads)
            assert np.array_equal(ref, got) and ref.dtype == got.dtype, (case, threads)
        n_px += ref.size
    print(f'PASS: raster_ids ({n_grids} grids, {n_s} samples, k 1 to 16, eps 1e-9, 0 and -1e-7, slivers, corners on '
          f'pixel centres and edges, NaN and inf corners, windows clipped, up to 600 triangles: owners and counts of '
          f'rasterize_ids and raster_window as recorded, the same at {THREADS_ALL} threads; island_labels of 3 meshes, '
          f'{n_px} px, the same)')


def test_dilate(rng):
    """fss_ao_copy_dilate against dilate_ids (owners and steps), with and without a mask."""
    n_px = 0
    iters = set()
    for case in range(48):
        H, W = int(rng.integers(1, 90)), int(rng.integers(1, 90))
        if case % 8 == 0:
            W = 1
        elif case % 8 == 1:
            H = 1
        owner = np.full((H, W), -1, np.int64)
        seeds = rng.uniform(0, 1, (H, W)) < rng.choice([0.002, 0.02, 0.2])
        owner[seeds] = rng.integers(0, 1000, int(seeds.sum()))
        mask = None if case % 3 == 0 else rng.uniform(0, 1, (H, W)) > 0.3
        it = int((0, 1, 2, 8, 40)[case % 5])
        iters.add(it)
        ref = core.dilate_ids(owner, it, mask, threads=1)
        for threads in THREADS_ALL:
            got = core.dilate_ids(owner, it, mask, threads=threads)
            assert np.array_equal(ref[0], got[0]) and np.array_equal(ref[1], got[1]), (case, threads)
            assert ref[0].dtype == got[0].dtype and ref[1].dtype == got[1].dtype
        o32 = owner.astype(np.int32)
        ref32, got32 = core.dilate_ids(o32, it, mask, threads=1), core.dilate_ids(o32, it, mask, threads=12)
        assert ref32[0].dtype == got32[0].dtype == np.int32 and np.array_equal(ref32[0], got32[0])
        REF.check(f'dilate/{case:02d}', ref[0], ref[1], ref32[0], ref32[1])
        n_px += owner.size
    print(f'PASS: dilate ({n_px} px of 48 grids, 1 px wide and high among them, masks and none, iterations '
          f'{sorted(iters)}: owners and steps of dilate_ids as recorded, the same at {THREADS_ALL} threads, int64 and '
          f'int32)')


def test_uv_islands(rng):
    """fss_ao_copy_uv_islands against uv_islands: seams, welded copies, stacked (non-manifold) and degenerate
    triangles, NaN UVs."""
    n_tris = n_isl = 0
    for case in range(30):
        n = int(rng.integers(2, 16))
        pos, tris, _cn = height_mesh(rng, n=n, crease=case % 2 == 0)
        T = len(tris)
        uv = pos[tris][:, :, :2] / 0.02
        cut = rng.uniform(0, 1, T) < rng.choice([0.0, 0.05, 0.3])  # seams: triangles moved in UV
        uv[cut] += rng.uniform(-0.5, 0.5, (int(cut.sum()), 1, 2))
        near = rng.uniform(0, 1, T) < 0.05  # UVs moved by about the tolerance
        uv[near] += rng.choice([-1, 1], (int(near.sum()), 1, 1)) * rng.choice([5e-7, 2e-6])
        wt = core.weld_ids(pos)[tris]
        if case % 5 == 1:  # stacked copies: three or more triangles on one edge
            wt = np.concatenate([wt, wt[: T // 3]])
            uv = np.concatenate([uv, uv[: T // 3] + (case % 2) * 1e-7])
        if case % 5 == 2:  # degenerate: two corners welded together
            wt[: 3, 1] = wt[: 3, 0]
        if case % 7 == 3:
            uv[rng.integers(0, len(uv), 3), 1, 0] = np.nan
        tol = (1e-6, 1e-5, 0.0)[case % 3]
        ref = core.uv_islands(wt, uv, tol, threads=1)
        REF.check(f'uv_islands/{case:02d}', ref)
        for threads in THREADS_ALL:
            got = core.uv_islands(wt, uv, tol, threads=threads)
            assert np.array_equal(ref, got) and ref.dtype == got.dtype, (case, threads)
        n_tris += len(wt)
        n_isl += int(ref.max()) + 1
    print(f'PASS: uv_islands (30 meshes, {n_tris} triangles, {n_isl} islands: seams, UVs moved about the tolerance, '
          f'stacked and degenerate triangles, NaN UVs; tol 1e-6, 1e-5, 0: the labels of uv_islands as recorded, the '
          f'same at {THREADS_ALL} threads)')


class _FakeKDTree:
    """mathutils.kdtree.KDTree for soften_context outside Blender: a brute-force search (the candidates are an input
    of the C++ Soften; any valid lists test it)."""

    def __init__(self, n):
        self.co = np.zeros((n, 3))

    def insert(self, co, i):
        self.co[i] = co

    def balance(self):
        pass

    def find_range(self, co, radius):
        d = np.linalg.norm(self.co - np.asarray(co, float), axis=1)
        return [(self.co[i], int(i), float(d[i])) for i in np.nonzero(d <= radius)[0]]


def _mathutils():
    try:
        import mathutils  # noqa: F401
        import mathutils.kdtree  # noqa: F401
        return 'mathutils'
    except ImportError:
        import types
        mu = types.ModuleType('mathutils')
        mu.Vector = lambda v: np.asarray(v, float)
        kd = types.ModuleType('mathutils.kdtree')
        kd.KDTree = _FakeKDTree
        mu.kdtree = kd
        sys.modules['mathutils'], sys.modules['mathutils.kdtree'] = mu, kd
        return 'a brute-force KD-tree'


def fold_mesh(rng, n, fold, bumps):
    """A height field of n x n quads over 2 cm with a fold along x = 1 cm: fold +1 rising (concave seen from above),
    -1 falling (convex), 0 none; bumps: the amplitude of a sine relief (more folds, several edges near a pixel)."""
    xs = np.linspace(0, 0.02, n + 1)
    X, Y = np.meshgrid(xs, xs)
    Z = bumps * np.sin(X * 400) * np.cos(Y * 330) + fold * np.where(X > 0.01, (X - 0.01) * 1.5, 0.0)
    Z += rng.uniform(-1e-5, 1e-5, Z.shape)
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


def test_soften(rng, folder):
    """fss_ao_copy_soften called directly and inside copy_master (inside and padding pixels), convex and concave folds,
    several edges near a pixel, whole and paged masters, with and without the surface-aware read."""
    kdt = _mathutils()
    n_direct = n_changed = n_copy_px = n_soft_px = 0
    n_convex = n_concave = 0
    most_cand = 0
    for case in range(8):
        fold = (1, -1, 1, -1, 0, 1, -1, 0)[case]
        bumps = (0.0, 0.0, 0.0008, 0.0008, 0.0015, 0.0015, 0.0003, 0.002)[case]
        pos, tris, cn = fold_mesh(rng, int(rng.integers(5, 13)), fold, bumps)
        master = make_master(rng, pos, tris, cn, holes=0.02 if case % 2 else 0.0,
                             density=(3000.0, 12000.0, 30000.0)[case % 3])
        W = H = int(rng.choice([64, 96]))
        uvpx = target_uv(rng, pos, tris, W, H, stack=case % 3 == 2)
        ctx = core.copy_context(pos, tris, uvpx, master, core.K_MIN, core.K_MAX)
        width = (0.0005, 0.0015, 0.004)[case % 3]
        sc = core.soften_context(pos, tris, uvpx, ctx, width, cn=None)
        assert sc is not None, case
        n_convex += int(sc['convex'].sum())
        n_concave += int((~sc['convex']).sum())
        most_cand = max(most_cand, int(np.diff(sc['start']).max()))
        paged, arrays = paged_copy(master, folder, 4 * core.PAGE_TILE * core.PAGE_TILE * 6)
        try:
            for mst, label in ((master, 'whole'), (paged, 'paged')):
                for scos in (core.SURFACE_COS, None):
                    # direct: points on random triangles, values random
                    n = 6000
                    t = rng.integers(0, len(tris), n)
                    b = rng.dirichlet((1, 1, 1), n)
                    if case % 2:
                        b = rng.uniform(-0.05, 1.05, (n, 3))  # also just off the triangles
                    p3 = np.einsum('nk,nkd->nd', b, pos[tris[t]])
                    vals = rng.uniform(0, 1, n)
                    prep = nat.prepare(mst, (core.PagedArray, core._PagedView))
                    ref, n_ref = nat.soften(prep, ctx['tri_normal'], scos, scos is not None, sc, core.SURFACE_COS, t,
                                            p3, vals, 1)
                    direct = (ref, n_ref)
                    for threads in THREADS_ALL:
                        got, n_got = nat.soften(prep, ctx['tri_normal'], scos, scos is not None, sc,
                                                core.SURFACE_COS, t, p3, vals, threads)
                        assert same_bits(ref, got) and n_ref == n_got, \
                            (case, label, scos, threads, int((bits(ref) != bits(got)).sum()), n_ref, n_got)
                    n_direct += n
                    n_changed += n_ref
                    # inside copy_master: the inside and the padding pixels softened
                    kw = dict(padding=4, outside_mode='tri', kmax=core.K_MAX, surface_cos=scos, ctx=ctx, soften=sc)
                    tisl = np.zeros(len(tris), np.int64)
                    ref = core.copy_master(pos, tris, uvpx, tisl, mst, (0, 0, W, H), core.K_MIN, threads=1, **kw)
                    REF.check(f'soften/{case}/{label}/{"surface" if scos is not None else "plain"}', direct,
                              *copy_values(ref))
                    for threads in THREADS_ALL:
                        got = core.copy_master(pos, tris, uvpx, tisl, mst, (0, 0, W, H), core.K_MIN,
                                               threads=threads, **kw)
                        assert got[1]['copy'] == 'native'
                        assert same_bits(ref[0], got[0]), (case, label, scos, threads)
                        assert ref[1]['softened_px'] == got[1]['softened_px'], (case, label, scos, threads)
                        for x, y in zip(ref[2:], got[2:]):
                            assert np.array_equal(x, y)
                    n_copy_px += int((ref[0] >= 0).sum())
                    n_soft_px += ref[1]['softened_px']
        finally:
            for a in arrays:
                a.close()
    assert n_convex and n_concave and n_changed and n_soft_px
    print(f'PASS: soften ({n_convex} convex and {n_concave} concave folds, up to {most_cand} candidate edges per '
          f'triangle, candidates by {kdt}; {n_direct} points called directly, {n_changed} changed; copy_master '
          f'{n_copy_px} px, {n_soft_px} softened; whole and paged, surface-aware and plain read: as recorded, '
          f'bit-identical at {THREADS_ALL} threads)')


# ---------------------------------------------------------------------------------------------------------------------
# The bake's post-processing (bake-post-native journal, interface version 5): compose_block and the .ao.map writer
# ---------------------------------------------------------------------------------------------------------------------

def compose_master(rng, case):
    """A master's layout (build_master, corner_pairs) and a bake of it as the runner's rule fills it: the core
    triangles' pixel centres, then the skirt's inside the rectangles; smooth values with noise, some corner pixels
    brighter than their inward pixel (decision 57), some baked pixels dropped (holes for the nearest fill) and, in some
    cases, stray baked pixels outside the rectangles. Returns (m, M16, baked)."""
    kind = case % 4
    if kind == 3:
        pos, tris, cn = fold_mesh(rng, int(rng.integers(4, 10)), 1, 0.0008)  # concave folds: corner pairs
    else:
        pos, tris, cn = height_mesh(rng, n=int(rng.integers(3, 12)), crease=kind != 1)
    density = float(rng.choice([1500.0, 4000.0, 9000.0, 16000.0]))
    m = core.build_master(pos, tris, cn, density, gutter=core.GUTTER, order=core.ORDER, mirror_open=core.MIRROR_OPEN,
                          fold_split=core.FOLD_SPLIT)
    m['corner_pairs'] = core.corner_pairs(m, pos, tris)
    if case % 7 == 5:  # no skirt
        m['skirt_pos'] = np.zeros((0, 3, 3))
        m['skirt_uv'] = np.zeros((0, 3, 2))
        m['skirt_src'] = np.zeros(0, np.int64)
    if case % 9 == 4:
        m['corner_pairs'] = None
    W, H = m['W'], m['H']
    own, _c = core.rasterize_ids(m['muv'][m['core_tris']], W, H)
    cm = own >= 0
    baked = cm.copy()
    if len(m['skirt_pos']):
        sown, _c = core.rasterize_ids(m['skirt_uv'], W, H)
        baked |= (~cm) & (sown >= 0) & (core.rect_window(m['rects'], 0, 0, W, H) >= 0)
    ys, xs = np.mgrid[0:H, 0:W]
    v = 32768 + 20000 * np.sin(xs / 7.0) * np.cos(ys / 5.0) + rng.normal(0, 400, (H, W))
    M16 = np.clip(np.round(v), 0, 65535).astype(np.uint16)
    if m['corner_pairs'] is not None and len(m['corner_pairs'][0]):
        cy, cx, iy, ix = m['corner_pairs']
        pick = rng.uniform(0, 1, len(cy)) < 0.5
        M16[cy[pick], cx[pick]] = np.minimum(65535, M16[iy[pick], ix[pick]].astype(np.int64)
                                             + rng.choice([500, 1310, 1311, 6000], int(pick.sum())))
    baked &= rng.uniform(0, 1, (H, W)) > rng.choice([0.0, 0.05, 0.3])
    if case % 5 == 2:
        baked |= rng.uniform(0, 1, (H, W)) < 0.002
    return m, M16, baked


def same_compose(a, b):
    """(counts, values, filled, face) equal, dtypes too, the counts' keys in the same order."""
    return (list(a[0].items()) == list(b[0].items()) and all(np.array_equal(x, y) and x.dtype == y.dtype
                                                             for x, y in zip(a[1:], b[1:])))


def test_compose(rng):
    """fss_ao_compose_block through compose_block, compose_whole and bake_paged, as recorded and the same at 1, 12 and
    os.cpu_count() threads: rectangles at window edges, corner pairs, skirt faces, empty windows, windows of 1 px,
    halos clamped at the master's edges, no skirt, no corner pairs, stray baked pixels."""
    n_masters = n_blocks = n_px = n_corner = n_fill = n_skirt = n_one = n_empty = 0
    for case in range(36):
        m, M16, baked = compose_master(rng, case)
        H, W = M16.shape
        n_masters += 1
        n_skirt += int(len(m['skirt_pos']) > 0)
        window = int(rng.choice([2048, 64, 37, 9]))
        ref = core.compose_whole(m, M16, baked, window=window, threads=1)
        parts = [ref]  # the reference values of this master: compose_whole, the blocks, bake_paged's rows
        for threads in THREADS_ALL:
            got = core.compose_whole(m, M16, baked, window=window, threads=threads)
            assert same_compose(ref, got), (case, window, threads, ref[0], got[0])
        n_px += W * H
        n_corner += ref[0].get('corner_px', 0)
        n_fill += ref[0].get('nearest_fill_px', 0)
        layout = core.compose_layout(m)
        for b in range(24):  # windows anywhere: at the edges, 1 px, empty, larger than the master's halo
            w = int(rng.integers(1, min(W, 90) + 1)) if b % 4 else 1
            h = int(rng.integers(1, min(H, 90) + 1)) if b % 3 else 1
            x0 = int(rng.choice([0, W - w, int(rng.integers(0, W - w + 1))]))
            y0 = int(rng.choice([0, H - h, int(rng.integers(0, H - h + 1))]))
            halo = int(rng.choice([core.FILL, 0, 3, 20]))
            ex0, ey0 = max(0, x0 - halo), max(0, y0 - halo)
            ex1, ey1 = min(W, x0 + w + halo), min(H, y0 + h + halo)
            Me, Be = M16[ey0:ey1, ex0:ex1], baked[ey0:ey1, ex0:ex1]
            if b == 23:  # an empty block: nothing baked
                Be = np.zeros_like(Be)
            r = core.compose_block(m, Me, Be, ex0, ey0, (x0, y0, w, h), threads=1)
            parts.append(r)
            for threads in THREADS_ALL:
                g = core.compose_block(m, Me, Be, ex0, ey0, (x0, y0, w, h), threads=threads, layout=layout)
                assert same_compose(r, g), (case, b, (x0, y0, w, h), threads, r[0], g[0])
            n_blocks += 1
            n_one += int(w == 1 or h == 1)
            n_empty += int(not Be.any())
        # bake_paged as the runner calls it (the strips' rows into write_rows), several windows per strip
        old = core.COMPOSE_WINDOW, core.COMPOSE_STRIP
        core.COMPOSE_WINDOW, core.COMPOSE_STRIP = int(rng.choice([2048, 41, 23])), int(rng.choice([256, 30, 13]))
        try:
            tile = int(rng.choice([16, 40, 64, 4096]))
            outs = []
            for threads in THREADS_ALL:
                rows_v, rows_c = [], []

                def bake_tile(i, rect, win, bk):
                    x0, y0, w, h = rect
                    win[:] = M16[y0:y0 + h, x0:x0 + w]
                    bk[:] = baked[y0:y0 + h, x0:x0 + w]
                    yield i

                def write_rows(v, c):
                    rows_v.append(np.array(v))
                    rows_c.append(np.array(c))
                counts = {}
                for _ in core.bake_paged(m, tile, bake_tile, write_rows, counts, threads=threads):
                    pass
                outs.append((list(counts.items()), np.concatenate(rows_v), np.concatenate(rows_c)))
            for o in outs[1:]:
                assert o[0] == outs[0][0] and np.array_equal(o[1], outs[0][1]) and np.array_equal(o[2], outs[0][2]), \
                    (case, tile, core.COMPOSE_WINDOW, core.COMPOSE_STRIP)
            assert outs[0][1].shape == (H, W)
            parts.append(outs[0])
            REF.check(f'compose/{case:02d}', *parts)
        finally:
            core.COMPOSE_WINDOW, core.COMPOSE_STRIP = old
    assert n_corner and n_fill and n_one and n_empty
    print(f'PASS: compose ({n_masters} masters, {n_px} px, {n_skirt} with a skirt, compose_whole in windows of 9 to '
          f'2048 px: {n_corner} corner px, {n_fill} px filled; {n_blocks} blocks at the edges, {n_one} of 1 px rows or '
          f'columns, {n_empty} empty, halos 0 to 20 px clamped; bake_paged in tiles of 16 to 4096 px with strips of 13 '
          f'to 256 rows and windows of 23 to 2048 px: values, filled flags, faces, codes and counts as recorded, the '
          f'same at {THREADS_ALL} threads)')


MAP_SIZES = [(1, 1), (1, 700), (700, 1), (255, 257), (1300, 1100), (3000, 900)]


def test_map_writer(rng, folder):
    """ao_bake_copy.MapWriter: the recorded bytes for random, smooth and real-looking codes, the same for any blocking
    of the rows (negative strides among them), at 1, 2, 12 and os.cpu_count() threads; the errors."""
    n_files = n_bytes = 0
    for (W, H) in MAP_SIZES:
        for kind in ('random', 'runs', 'zeros'):
            if kind == 'random':
                codes = rng.integers(-2 ** 31, 2 ** 31, (H, W)).astype(np.int32)
            elif kind == 'runs':
                face = np.repeat(rng.integers(-1, 5000, (H, max(1, W // 37) + 1)), 37, axis=1)[:, :W]
                codes = core.map_code(face, rng.uniform(0, 1, (H, W)) < 0.7)
            else:
                codes = np.zeros((H, W), np.int32)
            ref = os.path.join(folder, f'ref_{W}_{H}_{kind}.ao.map')
            w = nat.MapWriter(ref, W, H, level=1, threads=1)
            for top in range(0, H, 256):
                w.write(codes[top:top + 256])
            w.close()
            want = file_bytes(ref)
            REF.check(f'map/{W}x{H}/{kind}', want)
            for threads in (1, 2, 12, os.cpu_count() or 2):
                for blocking in ('one', 'rows', 'random', 'flipped'):
                    path = os.path.join(folder, f'map_{W}_{H}_{kind}_{threads}_{blocking}.ao.map')
                    w = nat.MapWriter(path, W, H, level=1, threads=threads)
                    if blocking == 'one':
                        w.write(codes)
                    elif blocking == 'rows':
                        for r in range(H):
                            w.write(codes[r:r + 1])
                    elif blocking == 'random':
                        top = 0
                        while top < H:
                            n = int(rng.integers(1, 300))
                            w.write(codes[top:top + n].astype(np.int64) if n % 5 == 0 else codes[top:top + n])
                            top += n
                    else:  # as bake_paged hands them: a strip composed bottom up, written flipped (negative stride)
                        for top in range(0, H, 77):
                            strip = np.ascontiguousarray(codes[top:top + 77][::-1])
                            w.write(strip[::-1])
                    w.close()
                    assert file_bytes(path) == want, (W, H, kind, threads, blocking)
                    assert w.map_stats['file_bytes'] == len(want) and w.map_stats['threads'] == int(threads >= 2)
                    os.remove(path)
                    n_files += 1
            n_bytes += len(want)
            # read back by map_rows
            mW, mH, gen = core.map_rows(ref)
            back = np.concatenate(list(gen))
            assert (mW, mH) == (W, H) and np.array_equal(back, codes)
            os.remove(ref)
    # errors: a missing folder, rows missing at close, too many rows, abort: an OSError naming the file, no file left
    W, H = 300, 200
    codes = rng.integers(0, 1000, (H, W)).astype(np.int32)
    bad = os.path.join(folder, 'missing', 'x.ao.map')
    try:
        nat.MapWriter(bad, W, H)
        raise AssertionError('a map in a missing folder')
    except nat.MapError as exc:
        assert 'x.ao.map' in str(exc) and 'not created' in str(exc), exc
        assert isinstance(exc, OSError)
    msgs = []
    for threads in (1, 12):
        p = os.path.join(folder, f'short_{threads}.ao.map')
        w = nat.MapWriter(p, W, H, threads=threads)
        w.write(codes[:50])
        try:
            w.close()
            raise AssertionError('a map with rows missing')
        except nat.MapError as exc:
            assert '50 of 200 rows' in str(exc) and 'short_' in str(exc), exc
            msgs.append(str(exc))
        assert not os.path.exists(p)
        p = os.path.join(folder, f'long_{threads}.ao.map')
        w = nat.MapWriter(p, W, H, threads=threads)
        w.write(codes)
        try:
            w.write(codes[:1])
            raise AssertionError('a map with a row too many')
        except nat.MapError as exc:
            assert '201 rows handed in' in str(exc), exc
        w.abort()
        assert not os.path.exists(p)
        p = os.path.join(folder, f'abort_{threads}.ao.map')
        w = nat.MapWriter(p, W, H, threads=threads)
        w.write(codes[:120])
        w.abort()
        assert not os.path.exists(p)
    print(f'PASS: map writer ({n_files} files of {len(MAP_SIZES)} sizes, 1 x 1 to 3000 x 900, random, run and zero '
          f'codes, written whole, row by row, in random blocks and flipped, at 1, 2, 12 and {os.cpu_count()} threads: '
          f'the recorded bytes ({n_bytes} bytes); errors: "{msgs[0]}", a missing folder, a row too many, abort, no file '
          f'left)')


# ---------------------------------------------------------------------------------------------------------------------
# PNG files (Session 7, decision 4): the C++ writer and reader
# ---------------------------------------------------------------------------------------------------------------------

PNG_SIZES = [(1, 1), (1, 700), (700, 1), (255, 257), (513, 300), (1300, 1100)]
BLENDER = os.environ.get('FSS_TEST_BLENDER', r'G:\e-jets-e2\tools\blender\blender.exe')
REAL_TEXTURES = [r'G:\e-jets-e2\assets\visual\texture\WINDSHIELD_WIPER_MASK.png',  # 16-bit RGBA, filters 0 to 4
                 r'G:\e-jets-e2\assets\visual\texture\Insects_Helico_Windshield_mask.png',  # 16-bit grey, Paeth
                 r'G:\e-jets-e2\assets\visual\texture\Checklist_E1_albd.png']  # 8-bit RGBA, Average and Paeth
# Blender's read of PNG files (a background Blender, Non-Color, channels packed): the md5 of each file's values as
# (H, W, C) uint16 in the file's depth, row 0 at the bottom
BLENDER_DECODE = r'''
import bpy, hashlib, json, sys
import numpy as np
args = sys.argv[sys.argv.index('--') + 1:]
with open(args[0]) as f:
    items = json.load(f)
out = {}
for path, w, h, bits, ct in items:
    image = bpy.data.images.load(path, check_existing=False)
    try:
        image.colorspace_settings.name = 'Non-Color'
        image.alpha_mode = 'CHANNEL_PACKED'
        buf = np.empty(w * h * 4, np.float32)
        image.pixels.foreach_get(buf)
    finally:
        bpy.data.images.remove(image)
    top = 65535 if bits == 16 else 255
    v = np.floor(buf.reshape(h, w, 4).astype(np.float64) * top + 0.5).astype(np.uint16)
    v = np.ascontiguousarray(v[:, :, {0: [0], 2: [0, 1, 2], 4: [0, 3], 6: [0, 1, 2, 3]}[ct]])
    out[path] = hashlib.md5(v.tobytes()).hexdigest()
with open(args[1], 'w') as f:
    json.dump(out, f)
'''


def md5_of(values):
    v = np.asarray(values, np.uint16)
    v = v if v.ndim == 3 else v[:, :, None]
    return hashlib.md5(np.ascontiguousarray(v).tobytes()).hexdigest()


def blender_md5s(folder, items):
    """{path: md5 of Blender's values} for items [(path, w, h, bits, colour type)]: one background Blender (the
    harness's cap holds for it), started in the scratch folder."""
    lst, res = os.path.join(folder, 'blender_items.json'), os.path.join(folder, 'blender_md5.json')
    with open(lst, 'w') as f:
        json.dump([[str(p), int(w), int(h), int(b), int(c)] for p, w, h, b, c in items], f)
    t0 = time.time()
    run = subprocess.run([BLENDER, '-b', '--factory-startup', '--python-exit-code', '1', '--python-expr',
                          BLENDER_DECODE, '--', lst, res], cwd=folder, capture_output=True, text=True)
    assert run.returncode == 0 and os.path.isfile(res), (run.returncode, run.stdout[-2000:], run.stderr[-2000:])
    with open(res) as f:
        got = json.load(f)
    os.remove(lst)
    os.remove(res)
    return got, time.time() - t0


def png_values(rng, W, H, C, bits, smooth):
    """(H, W, C) uint16 values in the depth's range: random, or smooth gradients with flat areas (as a baked AO)."""
    top = 65535 if bits == 16 else 255
    if not smooth:
        v = rng.integers(0, top + 1, (H, W, C))
    else:
        y, x = np.mgrid[0:H, 0:W]
        v = np.empty((H, W, C))
        for c in range(C):
            v[:, :, c] = 0.5 + 0.4 * np.sin(x / (9.0 + 3 * c)) * np.cos(y / (13.0 + c))
        v[(x // 41 + y // 23) % 4 == 0] = 1.0
        v = np.rint(np.clip(v, 0, 1) * top)
    v = v.astype(np.uint16)
    v[0, 0] = 0
    v[-1, -1] = top
    return v


def write_cpp(path, values, bits, threads, rows):
    """values (H, W, C), row 0 at the bottom, written by the C++ writer `rows` rows at a time from the top (rows 0:
    blocks of random sizes)."""
    H, W, C = values.shape
    w = nat.PngWriter(path, W, H, bits, C, threads)
    try:
        top, k = 0, 0
        while top < H:
            n = rows if rows else int(1 + (k * 7919) % 97)
            n = min(n, H - top)
            block = values[H - top - n:H - top][::-1]
            w.write(block[:, :, 0] if C == 1 and k % 2 else block)  # (n, W) and (n, W, 1) both taken
            top += n
            k += 1
        w.close()
    except BaseException:
        w.abort()
        raise
    return w.png_stats


def with_threads(n):
    """ao_bake_copy.THREADS raised for a test at n threads (threads_of caps at THREADS); returns the old value."""
    old = nat.THREADS
    nat.THREADS = max(old, n)
    return old


def cpp_read(path):
    """The C++ reader's values at 1 thread, (H, W, C), row 0 at the bottom (the header from png_info)."""
    w, h, bits, ct, _il = core.png_info(path)
    return nat.read_png(path, w, h, core.CHANNELS[ct], bits, 1)[0]


def test_png_write(rng, folder):
    cpus = os.cpu_count() or 1
    n_cfg = n_files = 0
    sizes = []
    blender_items, expect = [], {}
    t_cpp = 0.0
    for k, (W, H) in enumerate(PNG_SIZES):
        for C in (1, 2, 3, 4):
            for bits in (8, 16):
                smooth = (k + C + bits) % 2 == 0
                vals = png_values(rng, W, H, C, bits, smooth)
                stem = os.path.join(folder, f'w{k}_{C}_{bits}')
                ref = None
                for threads in (1, 12, cpus):
                    for kb, rows in enumerate((1, 7, 256, H, 0)):
                        p = f'{stem}_{threads}_{kb}.png'
                        old = with_threads(threads)
                        try:
                            t0 = time.time()
                            st = write_cpp(p, vals, bits, threads, rows)
                            t_cpp += time.time() - t0
                        finally:
                            nat.THREADS = old
                        assert st['threads'] == min(threads, max(1, -(-st['raw_bytes'] // (512 << 10)))), st
                        with open(p, 'rb') as f:
                            data = f.read()
                        if ref is None:
                            ref = (p, data)
                        else:
                            assert data == ref[1], (W, H, C, bits, threads, rows)
                            os.remove(p)
                        n_files += 1
                p = ref[0]
                # decoded by the C++ reader (1, 12 and all threads): the values written, as recorded
                REF.check(f'png_write/{k}/{C}/{bits}', cpp_read(p))
                for threads in (1, 12, cpus):
                    old = with_threads(threads)
                    try:
                        got, st = nat.read_png(p, W, H, C, bits, threads)
                    finally:
                        nat.THREADS = old
                    assert np.array_equal(got, vals), (W, H, C, bits, threads, 'C++ reader')
                    assert st['threads'] == (2 if threads > 1 else 1), st
                ct = core.COLOUR_TYPE[C]
                blender_items.append((p, W, H, bits, ct))
                expect[p] = md5_of(vals)
                # write_png_int (the add-on's whole-image writer, through png_writer): the same bytes
                pp = f'{stem}_whole.png'
                core.write_png_int(pp, vals if C > 1 else vals[:, :, 0], bits)
                assert file_bytes(pp) == ref[1], (W, H, C, bits, 'write_png_int')
                sizes.append(os.path.getsize(p))
                os.remove(pp)
                n_cfg += 1
    got, t_bl = blender_md5s(folder, blender_items)
    bad = [p for p in expect if got.get(str(p)) != expect[p]]
    assert not bad, bad[:5]
    for p, *_r in blender_items:
        os.remove(p)
    print(f'PASS: png write ({n_cfg} images of {PNG_SIZES[0]} to {PNG_SIZES[-1]} px, 1 to 4 channels, 8 and 16 bits, '
          f'random and smooth: {n_files} files of the C++ writer at 1, 12 and {cpus} threads and 5 row blockings, '
          f'byte-identical per image, and write_png_int\'s the same; each decoded to the rows handed in (as recorded) '
          f'by the C++ reader at 1, 12 and {cpus} threads and by Blender ({len(blender_items)} files, {t_bl:.1f} s); '
          f'{sum(sizes)} bytes; {t_cpp:.1f} s for {n_files} writes)')


def filter_rows(raw, bpp, kinds):
    """raw (H, n) uint8 unfiltered rows from the top; kinds (H,) filter types: the filtered rows (H, n) (numpy)."""
    raw = raw.astype(np.int32)
    prev = np.zeros_like(raw)
    prev[1:] = raw[:-1]
    a = np.zeros_like(raw)
    a[:, bpp:] = raw[:, :-bpp] if bpp < raw.shape[1] else 0
    c = np.zeros_like(raw)
    c[:, bpp:] = prev[:, :-bpp] if bpp < raw.shape[1] else 0
    b = prev
    p = a + b - c
    pa, pb, pc = np.abs(p - a), np.abs(p - b), np.abs(p - c)
    pred = np.where((pa <= pb) & (pa <= pc), a, np.where(pb <= pc, b, c))
    out = np.stack([raw, raw - a, raw - b, raw - (a + b) // 2, raw - pred])  # (5, H, n)
    return (out[np.asarray(kinds), np.arange(raw.shape[0])] % 256).astype(np.uint8)


def unfilter_slow(stream, h, n, bpp):
    """The PNG unfilter byte by byte (the specification's loop), to check filter_rows on small images."""
    rows, prev = [], bytearray(n)
    for y in range(h):
        kind = stream[y * (n + 1)]
        line = bytearray(stream[y * (n + 1) + 1:(y + 1) * (n + 1)])
        for i in range(n):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if kind == 1:
                line[i] = (line[i] + a) & 0xFF
            elif kind == 2:
                line[i] = (line[i] + b) & 0xFF
            elif kind == 3:
                line[i] = (line[i] + (a + b) // 2) & 0xFF
            elif kind == 4:
                q = a + b - c
                qa, qb, qc = abs(q - a), abs(q - b), abs(q - c)
                line[i] = (line[i] + (a if qa <= qb and qa <= qc else b if qb <= qc else c)) & 0xFF
        rows.append(bytes(line))
        prev = line
    return b''.join(rows)


def chunk(tag, data):
    """A PNG chunk: length, tag, data, CRC."""
    return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)


def write_filtered(path, vals, bits, kinds, rng, extra=True):
    """A PNG of vals (H, W, C), row 0 at the bottom, with filter kinds[y] on file row y; the zlib stream (Python's
    zlib) cut into IDAT chunks of random sizes (an empty one among them), an ancillary chunk before them. Returns the
    filtered stream."""
    H, W, C = vals.shape
    bpp = C * bits // 8
    top_first = vals[::-1]
    raw = np.ascontiguousarray(top_first.astype('>u2' if bits == 16 else np.uint8)).view(np.uint8).reshape(H, -1)
    f = filter_rows(raw, bpp, kinds)
    stream = np.concatenate([np.asarray(kinds, np.uint8)[:, None], f], axis=1).tobytes()
    z = zlib.compress(stream, 1)
    assert zlib.decompress(z) == stream
    parts, at = [], 0
    while at < len(z):
        n = int(rng.integers(1, 70000))
        parts.append(z[at:at + n])
        at += n
    parts.insert(min(1, len(parts)), b'')
    data = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', W, H, bits, core.COLOUR_TYPE[C], 0, 0, 0))
    if extra:
        data += chunk(b'tEXt', b'Comment\x00a chunk the readers skip')
    data += b''.join(chunk(b'IDAT', p) for p in parts) + chunk(b'IEND', b'')
    with open(path, 'wb') as fh:
        fh.write(data)
    return stream, raw


def test_png_read(rng, folder):
    cpus = os.cpu_count() or 1
    n_files = n_slow = n_ref = 0
    blender_items, expect = [], {}
    for k, (W, H) in enumerate([(1, 1), (3, 50), (64, 64), (255, 257), (700, 9), (1300, 1100)]):
        for C in (1, 2, 3, 4):
            for bits in (8, 16):
                vals = png_values(rng, W, H, C, bits, (k + C) % 2 == 0)
                bpp = C * bits // 8
                for kind in ('0', '1', '2', '3', '4', 'mixed'):
                    kinds = rng.integers(0, 5, H) if kind == 'mixed' else np.full(H, int(kind))
                    p = os.path.join(folder, f'r{k}_{C}_{bits}_{kind}.png')
                    stream, raw = write_filtered(p, vals, bits, kinds, rng)
                    if W * H * bpp <= 64 * 64 * 8:  # the numpy filter checked by the specification's loop
                        assert unfilter_slow(stream, H, W * bpp, bpp) == raw.tobytes(), (W, H, C, bits, kind)
                        n_slow += 1
                    for threads in (1, 12, cpus):
                        old = with_threads(threads)
                        try:
                            got, _st = nat.read_png(p, W, H, C, bits, threads)
                        finally:
                            nat.THREADS = old
                        assert np.array_equal(got, vals), (W, H, C, bits, kind, threads)
                    how = {}
                    v, b, ct = core.read_png(p, how=how)
                    assert how['read'] == 'C++ (2 threads)' and b == bits and np.array_equal(
                        v if v.ndim == 3 else v[:, :, None], vals), how
                    if kind in ('0', '1', '2'):  # the files the Python reader decoded: as recorded
                        REF.check(f'png_read/{k}/{C}/{bits}/{kind}', cpp_read(p))
                        n_ref += 1
                    if kind in ('3', '4', 'mixed') and k in (2, 3):
                        blender_items.append((p, W, H, bits, core.COLOUR_TYPE[C]))
                        expect[p] = md5_of(vals)
                    n_files += 1
    # real textures with Average or Paeth rows (read from G:\e-jets-e2, never written)
    real = []
    for p in REAL_TEXTURES:
        if not os.path.isfile(p):
            print(f'  real texture missing: {p}')
            continue
        w, h, bits, ct, il = core.png_info(p)
        t0 = time.time()
        got, st = nat.read_png(p, w, h, core.CHANNELS[ct], bits, 12)
        dt = time.time() - t0
        blender_items.append((p, w, h, bits, ct))
        expect[p] = md5_of(got)
        real.append(f'{os.path.basename(p)} {w} x {h} {bits}-bit colour type {ct}: C++ {dt:.2f} s')
    assert real, 'no real texture found'
    got, t_bl = blender_md5s(folder, blender_items)
    bad = [p for p in expect if got.get(str(p)) != expect[p]]
    assert not bad, bad
    for f in os.listdir(folder):
        if f.startswith('r') and f.endswith('.png'):
            os.remove(os.path.join(folder, f))
    print(f'PASS: png read ({n_files} files with filters None, Sub, Up, Average, Paeth and mixed, 1 to 4 channels, '
          f'8 and 16 bits, several IDAT chunks (an empty one) and a tEXt chunk: the C++ reader at 1, 12 and {cpus} '
          f'threads gives the values written; the numpy filter checked by the byte loop on {n_slow}; {n_ref} files '
          f'(None, Sub, Up) as recorded; {len(blender_items)} files equal to Blender\'s read ({t_bl:.1f} s), among '
          f'them the real textures: ' + '; '.join(real) + ')')


def expect_png_error(fn, words, cls=None):
    try:
        fn()
    except OSError as exc:
        assert isinstance(exc, cls or nat.PngError), type(exc)
        assert all(w in str(exc) for w in words), (str(exc), words)
        return str(exc)
    raise AssertionError(f'no error ({words})')


def test_png_errors(rng, folder):
    msgs = {}
    W, H = 300, 200
    vals = png_values(rng, W, H, 3, 16, False)
    good = os.path.join(folder, 'e_good.png')
    write_cpp(good, vals, 16, 12, 64)
    with open(good, 'rb') as f:
        data = f.read()

    def variant(name, d):
        p = os.path.join(folder, name)
        with open(p, 'wb') as f:
            f.write(d)
        return p
    # the reader: truncated, corrupt, an unknown colour type, a palette, interlace, a bad filter type
    p = variant('e_cut.png', data[:len(data) // 2])
    msgs['truncated'] = expect_png_error(lambda: core.read_png(p), ['e_cut.png', f'of {H} rows'])
    d = bytearray(data)
    for i in range(len(d) // 2, len(d) // 2 + 64):
        d[i] ^= 0x5A
    p = variant('e_corrupt.png', bytes(d))
    msgs['corrupt'] = expect_png_error(lambda: core.read_png(p), ['e_corrupt.png', 'corrupt'])

    def header(ct=2, bits=16, il=0):
        ihdr = struct.pack('>IIBBBBB', W, H, bits, ct, 0, 0, il)
        return data[:8] + chunk(b'IHDR', ihdr) + data[33:]
    for name, kw in (('e_ct5.png', dict(ct=5)), ('e_palette.png', dict(ct=3, bits=8)),
                     ('e_interlace.png', dict(il=1)), ('e_bits4.png', dict(bits=4, ct=0))):
        p = variant(name, header(**kw))
        msgs[name] = expect_png_error(lambda: nat.read_png(p, W, H, 3, 16, 12), [name, 'not read here'],
                                      nat.PngUnsupported)
        try:  # read_png leaves these to Blender (Apply's read_texture)
            core.read_png(p)
        except core.PngNotDecoded:
            pass
        else:
            raise AssertionError(name)
    stream = bytearray(zlib.decompress(b''.join(
        data[i + 8:i + 8 + struct.unpack('>I', data[i:i + 4])[0]] for i in idat_offsets(data))))
    stream[(1 + W * 6) * 5] = 7  # row 5: filter type 7
    p = variant('e_filter.png', data[:33] + chunk(b'IDAT', zlib.compress(bytes(stream))) + chunk(b'IEND', b''))
    msgs['filter type'] = expect_png_error(lambda: core.read_png(p), ['e_filter.png', 'filter type 7'])
    msgs['missing file'] = expect_png_error(lambda: nat.read_png(os.path.join(folder, 'none.png'), W, H, 3, 16, 1),
                                            ['none.png', 'not opened'])
    # the writer: a folder that does not exist, a full disk, rows missing, an abort: nothing left
    bad = os.path.join(folder, 'missing_folder', 'e_w.png')
    msgs['missing folder'] = expect_png_error(lambda: nat.PngWriter(bad, W, H, 16, 3, 12), ['e_w.png', 'not created'])
    big = png_values(rng, 1000, 600, 3, 16, False)  # 3.6 MB of rows: 7 blocks
    for threads in (1, 12):
        p = os.path.join(folder, f'e_full_{threads}.png')
        w = nat.PngWriter(p, 1000, 600, 16, 3, threads)
        w.test_limit(1000000)  # as a disk that is full after 1,000,000 bytes

        def full():
            try:
                for top in range(0, 600, 20):
                    w.write(big[600 - top - 20:600 - top][::-1])
                w.close()
            except BaseException:
                w.abort()
                raise
        msgs[f'full disk {threads}'] = expect_png_error(full, [f'e_full_{threads}.png', 'not written', 'Windows error 112'])
        assert not os.path.exists(p), p
    p = os.path.join(folder, 'e_rows.png')
    w = nat.PngWriter(p, W, H, 16, 3, 12)
    w.write(vals[H - 50:][::-1])
    msgs['rows missing'] = expect_png_error(w.close, ['e_rows.png', f'50 of {H} rows'])
    assert not os.path.exists(p)
    p = os.path.join(folder, 'e_abort.png')
    w = nat.PngWriter(p, W, H, 16, 3, 12)
    w.write(vals[H - 50:][::-1])
    w.abort()
    assert not os.path.exists(p)
    left = [f for f in os.listdir(folder) if f.startswith(('e_w', 'e_full', 'e_rows', 'e_abort'))]
    assert not left and not os.path.exists(os.path.dirname(bad)), left
    for f in os.listdir(folder):
        if f.startswith('e_'):
            os.remove(os.path.join(folder, f))
    print('PASS: png errors (each an OSError naming the file; the writer leaves no file): '
          + '; '.join(f'{k}: {v}' for k, v in msgs.items()))


def idat_offsets(data):
    pos, out = 8, []
    while pos < len(data):
        n, tag = struct.unpack('>I4s', data[pos:pos + 8])
        if tag == b'IDAT':
            out.append(pos)
        pos += 12 + n
    return out


def test_threads(rng, opening, png):
    """Decision 5: Threads 0 is Auto, half the PC's logical processors and at least 2; a number is capped at the
    logical processors; the DLL takes more than 64 threads with the same bytes."""
    lib = core.jxl()
    cpus = os.cpu_count() or 2
    for mod in (nat, lib):
        assert mod.CPUS == cpus and mod.THREADS == max(2, cpus // 2), (mod.__name__, mod.CPUS, mod.THREADS)
    old = (nat.CPUS, nat.THREADS, lib.CPUS, lib.THREADS)
    rows = []
    try:
        for n in (1, 2, 3, 4, 8, 24, 128):
            for mod in (nat, lib):
                mod.CPUS, mod.THREADS = n, max(2, n // 2)
                got = (mod.threads_of(0), mod.threads_of(None), mod.threads_of(1), mod.threads_of(10 ** 6))
                assert got == (max(2, n // 2), max(2, n // 2), 1, max(n, 2)), (mod.__name__, n, got)
            rows.append(f'{n}: Auto {max(2, n // 2)}')
        nat.CPUS = lib.CPUS = 128  # as on a PC of 128 logical processors
        stem, kind = 'open1', 'ao'
        ref = page_bytes(opening, stem, kind, 12)[0]
        got, how, _img, _st = page_bytes(opening, stem, kind, 100)
        assert how == 'C++ (100 threads)' and got == ref, how
        W, H = 700, 520
        img = rng.integers(0, 65536, (H, W, 3)).astype(np.uint16)
        files = []
        for threads in (1, 100):
            path = os.path.join(png, f'threads_{threads}.png')
            w = nat.PngWriter(path, W, H, 16, 3, threads)
            w.write(img)
            w.close()
            files.append(file_bytes(path))
        assert files[0] == files[1]
    finally:
        nat.CPUS, nat.THREADS, lib.CPUS, lib.THREADS = old
    print(f"PASS: threads (this PC: {cpus} logical processors, Auto {max(2, cpus // 2)}; {', '.join(rows)}; "
          f"a number capped at the logical processors; the opening and the PNG writer at 100 threads byte-identical)")


def file_bytes(path):
    with open(path, 'rb') as f:
        return f.read()


def test_scene_rule():
    """Bake-post-native journal Session 5 (interface version 6): Refresh's scene-rule geometry and mesh hash in C++
    against the values the Python code gave on the seeded cases of tests/ao_scene_rule_cases.py (recorded in
    tests/data/ao_scene_rule_reference.json before it was removed), at 1, 12 and all threads: the own boxes
    (oriented_boxes_at) and their gaps (oriented_gaps) bit for bit, moves_against's booleans, near's occluder lists and
    gaps (bit for bit; queries at a gap exactly kept, just under it dropped) and mesh_hash's digests (with the CPU's
    SHA instructions and without)."""
    import ao_scene_rule_cases as cases
    from ao_native_reference import digest
    from ao_scene_rule_reference import load
    want = load('synthetic')
    assert want and all(len(want[k]) for k in ('boxes', 'gaps', 'moves', 'near', 'mesh_hash')), list(want)
    counts = dict(placed=0, not_ok=0, pairs=0, moves=0, against=0, queries=0, kept=0, at_gap=0, meshes=0)
    worst_gap = 0.0
    box_cases = cases.box_cases()
    assert len(box_cases) == len(want['boxes'])
    for (lo, hi, mats), w in zip(box_cases, want['boxes']):
        assert digest(lo, hi, mats) == w['in'], 'the box cases are not the recorded inputs'
        c, a, h, ok = nat.own_boxes(lo, hi, mats, cases.ORTHO_TOL)
        assert digest(c, a, h, ok) == w['out'], (w, ok)
        counts['placed'] += ok.size
        counts['not_ok'] += int((~np.atleast_1d(ok)).sum())
    gap_cases = cases.gap_cases()
    assert len(gap_cases) == len(want['gaps'])
    for (box, centres, axes, halves), w in zip(gap_cases, want['gaps']):
        assert digest(box[0], box[1], box[2], centres, axes, halves) == w['in']
        g = nat.box_gaps(box, centres, axes, halves)
        assert same_bits(g, np.array(w['out'], np.float64).reshape(-1)), (g, w['out'])
        counts['pairs'] += len(g)
    moves_cases = cases.moves_cases()
    near_cases = cases.near_cases()
    closest = dict(world=np.inf, own=np.inf, motion=np.inf, within=0)
    for threads in (1, 12, os.cpu_count() or 2):
        for (M, pairs), w in zip(moves_cases, want['moves']):
            assert digest(M, pairs) == w['in']
            n = len(M)
            rule = nat.SceneRule(np.zeros((n, 8, 3)), M[:, 0], M, cases.moving_of(M), np.zeros(0, np.int64),
                                 cases.ORTHO_TOL, cases.MOTION_TOL)
            moved, singular = rule.moves(pairs, threads)
            assert not singular.any()
            got = ''.join('1' if x else '0' for x in moved.tolist())
            assert got == w['out'], (threads, got, w['out'])
            if len(pairs) and rule.stats['moving_pairs']:
                closest['motion'] = min(closest['motion'], rule.stats['closest_motion'])
            if threads == 1:
                counts['moves'] += len(pairs)
                counts['against'] += got.count('1')
        for case, w in zip(near_cases, want['near']):
            assert digest(case['lo'], case['hi'], case['now'], case['M'], case['occ_rows'],
                          [list(q) for q in case['queries']]) == w['in']
            n = len(case['lo'])
            corners = np.array([cases.corners(case['lo'][r], case['hi'][r]) for r in range(n)])
            rule = nat.SceneRule(corners, case['now'], case['M'], cases.moving_of(case['M']), case['occ_rows'],
                                 cases.ORTHO_TOL, cases.MOTION_TOL)
            queries = [tuple(q) for q in case['queries']] + [tuple(q) for q in w['extra']]
            pos = {int(r): i for i, r in enumerate(case['occ_rows'])}
            res = rule.near([q[0] for q in queries], [q[1] for q in queries], [q[2] for q in queries],
                            [pos.get(int(q[0]), -1) for q in queries], threads)
            assert len(res) == len(w['out'])
            for (idx, gap), wl, wg in zip(res, w['out'], w['gaps']):
                rows = [int(case['occ_rows'][i]) for i in idx.tolist()]
                assert rows == wl, (threads, rows, wl)
                assert same_bits(gap, np.array(wg, np.float64).reshape(-1)), (gap, wg)
                if len(wg):
                    worst_gap = max(worst_gap, float(np.max(np.abs(gap - np.array(wg)))))
            closest['world'] = min(closest['world'], rule.stats['closest_world'])
            closest['own'] = min(closest['own'], rule.stats['closest_own'])
            if threads == 1:
                counts['queries'] += len(queries)
                counts['kept'] += sum(len(x) for x in w['out'])
                counts['at_gap'] += len(w['extra']) // 2
                closest['within'] += rule.stats['within']
    # a moving object of zero scale: its matrix has no inverse (np.linalg.inv raised in the Python code): flagged
    M = np.array([cases.poses(rng_of('singular'), cases.matrix(np.diag([0.0, 1.0, 1.0]), np.zeros(3)), 3, 'slide'),
                  np.array([np.eye(4)] * 3)])
    rule = nat.SceneRule(np.zeros((2, 8, 3)), M[:, 0], M, cases.moving_of(M), [], cases.ORTHO_TOL, cases.MOTION_TOL)
    moved, singular = rule.moves([(0, 1), (1, 0)])
    assert singular.tolist() == [True, False] and not moved[0], (moved, singular)
    mesh_cases = cases.mesh_cases()
    assert len(mesh_cases) == len(want['mesh_hash'])
    has_sha = True
    for ev, w in zip(mesh_cases, want['mesh_hash']):
        assert digest(ev['tris'], ev['co'], ev['cn']) == w['in']
        for threads in (1, 12, os.cpu_count() or 2):
            for impl in (0, 1, 2):
                try:
                    h = nat.mesh_hash(ev['tris'], ev['co'], ev['cn'], threads, impl)[:20]
                except nat.CopyError:
                    assert impl == 2
                    has_sha = False
                    continue
                assert h == w['out'], (threads, impl, h, w['out'])
            assert core.mesh_hash(ev, threads) == w['out']
        counts['meshes'] += 1
    print(f"PASS: scene rule (bake-post-native Session 5; at 1, 12 and {os.cpu_count()} threads, equal to the Python "
          f"code's recorded values: {len(box_cases)} own-box cases ({counts['placed']} placed, {counts['not_ok']} not "
          f"ok), {len(gap_cases)} gap cases ({counts['pairs']} pairs) bit for bit, {len(moves_cases)} motion cases "
          f"({counts['moves']} pairs, {counts['against']} moving against), {len(near_cases)} scenes "
          f"({counts['queries']} queries, {counts['kept']} occluders kept, {counts['at_gap']} queries at a gap exactly "
          f"and just under it; gaps bit for bit, largest difference {worst_gap:.3g} m), {counts['meshes']} mesh hashes "
          f"(the SHA instructions {'and' if has_sha else 'not on this CPU;'} plain C++); the closest gap to its "
          f"distance {closest['world']:.3g} m (world boxes), {closest['own']:.3g} m (own boxes), "
          f"{closest['within']} tests within 1e-9 m (the dyadic scenes), the closest motion to MOTION_TOL "
          f"{closest['motion']:.3g})")


if __name__ == '__main__':
    t0 = time.time()
    folder = os.path.join(REPO, 'tests', '_work', 'ao_copy_native')
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder)
    try:
        only = next((a[5:].split(',') for a in sys.argv if a.startswith('only=')), None)
        if only == ['compose']:  # the bake-post-native tests alone: -- only=compose
            compose_dir = os.path.join(folder, 'compose')
            os.makedirs(compose_dir)
            test_compose(rng_of('compose'))
            test_map_writer(rng_of('map_writer'), compose_dir)
            print(f'COMPOSE TESTS PASSED ({time.time() - t0:.1f} s)')
            sys.exit(0)
        if only == ['scene_rule']:  # the bake-post-native Session 5 tests alone: -- only=scene_rule
            test_scene_rule()
            print(f'SCENE RULE TESTS PASSED ({time.time() - t0:.1f} s)')
            sys.exit(0)
        test_sums(rng_of('sums'))
        test_raster(rng_of('raster'))
        test_read(rng_of('read'), folder)
        test_copy(rng_of('copy'), folder)
        test_raster_ids(rng_of('raster_ids'))  # Session 11: the raster, the dilation, the UV islands, Soften
        test_dilate(rng_of('dilate'))
        test_uv_islands(rng_of('uv_islands'))
        test_soften(rng_of('soften'), folder)
        test_fold_padding()  # auto-bake decision 78
        if only == ['pixels']:  # a quicker run of the tests above: -- only=pixels
            print(f'PIXELS TESTS PASSED ({time.time() - t0:.1f} s)')
            sys.exit(0)
        opening = os.path.join(folder, 'open')  # its own folder: no other page file in it
        os.makedirs(opening)
        test_open(rng_of('open'), opening)
        test_open_errors(rng_of('open_errors'), opening)
        png = os.path.join(folder, 'png')  # Session 7: the PNG writer and reader
        os.makedirs(png)
        test_png_write(rng_of('png_write'), png)
        test_png_read(rng_of('png_read'), png)
        test_png_errors(rng_of('png_errors'), png)
        test_threads(rng_of('threads'), opening, png)  # decision 5
        compose_dir = os.path.join(folder, 'compose')  # bake-post-native journal: the composition, the map writer
        os.makedirs(compose_dir)
        test_compose(rng_of('compose'))
        test_map_writer(rng_of('map_writer'), compose_dir)
        test_scene_rule()  # bake-post-native journal Session 5: Refresh's scene rule and mesh hash
        test_unavailable(rng_of('unavailable'), opening)  # decision 6: the DLL and libjxl required
        n_ref = REF.done(complete=True)
        print(f'PASS: reference values ({n_ref} cases equal to the values the Python code gave before decision 6)')
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    print(f'ALL AO COPY NATIVE TESTS PASSED ({time.time() - t0:.1f} s)')
