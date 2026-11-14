"""The AO Baker's steps (b) and (c) on synthetic meshes (OptiX baker journal 20261114.optix-baker.md; Glider plan
PLAN-20261114.optix-ao-baker.md, step (b)): one static mesh, one view, no occluder, no falloff. Checked:

1. the owners of every tile equal the add-on's rasterize_ids (0 differing pixels), core and skirt;
2. the master (composed with the add-on's bake_paged) is byte-identical at tile 512 and 2048, and on a second run;
3. analytic references: a plane is 1 at every baked pixel; a plane meeting a wall at 90 degrees follows the
   distance-limited cosine-weighted visibility 1 - (acos(a) - a sqrt(1 - a^2)) / pi, a = (distance to the other face) /
   (AO distance), averaged over each pixel's footprint, within a bound of the ray noise (each pixel's error over the
   binomial sigma sqrt(V (1 - V) / N)); the inside of a closed box with an AO distance beyond its diagonal is 0 at every
   baked pixel;
4. rays per second, measured.

Step (c) (occluders, poses, copies, falloff):

5. the falloff: the plane meeting a wall against the distance-limited mean of min(t / d, 1),
   F(a) = V(a) + (2a / pi) (ln((1 + s) / a) - s), s = sqrt(1 - a^2), V the visibility above, within the same bound;
6. an occluder: a plane under a parallel occluder plane at height h (larger than the reach of the rays) sees
   (h / d)^2 of its cosine-weighted hemisphere within the distance d; views move the plane (a mover's poses, a shared
   mesh's copies), posed occluders move with it; each combination (a copy's poses averaged; the copies averaged, the
   lightest, the darkest) against the combination of the views' (h / d)^2, within the bound;
7. byte for byte: a master of n views equals the combination (in numpy) of its n single-view bakes, which share the
   combined bake's random numbers, per tile, A and B; and the master of views is equal at tile 512 and 2048.

Plain Python (numpy) or Blender's Python. The baker: aobaker.exe --headless, started per run with a channel of its own.

    C:\\Users\\uray\\.claude\\tools\\cpucap\\cpucap.exe 50 python -I tests/test_ao_baker_static.py
        --exe F:\\glider\\out\\bin\\x64\\Release\\aobaker.exe [--samples 1024] [--out report.json]
"""
import argparse
import json
import math
import os
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ao_baker_client as client  # noqa: E402
import ao_baker_master as bm  # noqa: E402

RESULTS = []


def check(name, ok, **info):
    RESULTS.append(dict(name=name, ok=bool(ok), **info))
    print(('PASS ' if ok else 'FAIL ') + name + ': ' + ', '.join(f'{k}={v}' for k, v in info.items()), flush=True)


# ---------------------------------------------------------------------------------------------------------------------
# Meshes: positions (v, 3), triangles (t, 3), corner normals (t, 3, 3)
# ---------------------------------------------------------------------------------------------------------------------

def grid(origin, du, dv, n, normal):
    """An n x n grid of quads over origin + s du + t dv (s, t in 0..1), two triangles each, wound so their face normal
    is `normal`."""
    origin, du, dv = (np.asarray(x, dtype=np.float64) for x in (origin, du, dv))
    pts = np.array([origin + du * (i / n) + dv * (j / n) for j in range(n + 1) for i in range(n + 1)])
    tris = []
    for j in range(n):
        for i in range(n):
            a, b, c, d = j * (n + 1) + i, j * (n + 1) + i + 1, (j + 1) * (n + 1) + i + 1, (j + 1) * (n + 1) + i
            tris += [(a, b, c), (a, c, d)]
    tris = np.array(tris, dtype=np.int64)
    if np.dot(np.cross(du, dv), normal) < 0:
        tris = tris[:, ::-1].copy()
    return pts, tris


def merge(parts, normals):
    """One mesh of the grids, the vertices welded where they coincide (the shared edges), flat corner normals."""
    pos, tris, cn = [], [], []
    for (p, t), nrm in zip(parts, normals):
        off = sum(len(x) for x in pos)
        pos.append(p)
        tris.append(t + off)
        cn.append(np.tile(np.asarray(nrm, dtype=np.float64), (len(t), 3, 1)))
    pos = np.concatenate(pos)
    tris = np.concatenate(tris)
    key = np.round(pos / 1e-9).astype(np.int64)
    _u, first, inverse = np.unique(key, axis=0, return_index=True, return_inverse=True)
    return pos[first], inverse.reshape(-1)[tris], np.concatenate(cn)


def plane_mesh(size=0.2, n=4):
    return merge([grid((-size / 2, -size / 2, 0), (size, 0, 0), (0, size, 0), n, (0, 0, 1))], [(0, 0, 1)])


def corner_mesh(L=0.4, n=8):
    """A floor (z = 0, x in 0..L, y in -L/2..L/2, normal +z) meeting a wall (x = 0, z in 0..L, normal +x)."""
    floor = grid((0, -L / 2, 0), (L, 0, 0), (0, L, 0), n, (0, 0, 1))
    wall = grid((0, -L / 2, 0), (0, L, 0), (0, 0, L), n, (1, 0, 0))
    return merge([floor, wall], [(0, 0, 1), (1, 0, 0)])


def box_mesh(s=0.2, n=4):
    """A closed cube of side s, its faces facing in."""
    h = s / 2
    faces = [((-h, -h, -h), (s, 0, 0), (0, s, 0), (0, 0, 1)), ((-h, -h, h), (s, 0, 0), (0, s, 0), (0, 0, -1)),
             ((-h, -h, -h), (s, 0, 0), (0, 0, s), (0, 1, 0)), ((-h, h, -h), (s, 0, 0), (0, 0, s), (0, -1, 0)),
             ((-h, -h, -h), (0, s, 0), (0, 0, s), (1, 0, 0)), ((h, -h, -h), (0, s, 0), (0, 0, s), (-1, 0, 0))]
    return merge([grid(o, du, dv, n, nrm) for o, du, dv, nrm in faces], [f[3] for f in faces])


# ---------------------------------------------------------------------------------------------------------------------
# Analytic reference of the corner
# ---------------------------------------------------------------------------------------------------------------------

def visibility(a):
    """Distance-limited cosine-weighted visibility of a point at distance a (in AO distances) from a perpendicular
    infinite face: the cosine-weighted directions project to a uniform disk; those with an in-plane component toward
    the face of at least a reach it within the distance."""
    a = np.clip(a, 0.0, 1.0)
    return 1.0 - (np.arccos(a) - a * np.sqrt(1.0 - a * a)) / math.pi


def falloff_value(a):
    """The distance-limited cosine-weighted mean of min(t / d, 1) at distance a (in AO distances) from a perpendicular
    infinite face, and its variance per ray: the in-plane component q toward the face has density (2 / pi) sqrt(1 -
    q^2) on the unit disk; a ray with q >= a hits at t / d = a / q, the others count 1."""
    a = np.clip(np.asarray(a, dtype=np.float64), 1e-12, 1.0)
    s = np.sqrt(1.0 - a * a)
    v = visibility(a)
    mean = v + (2.0 * a / math.pi) * (np.log((1.0 + s) / a) - s)
    second = v + (2.0 * a * a / math.pi) * (s / a + np.arcsin(a) - math.pi / 2)
    return mean, np.maximum(second - mean * mean, 0.0)


def footprint_points(uv3, p3, cx, cy, k=9):
    """The 3D points of a k x k grid over the pixel (cx, cy) +- 0.5 through the triangle's barycentric map, or None
    when a corner of the pixel lies outside the triangle (then the jitter's mirror changes the footprint)."""
    a, b, c = uv3
    v0, v1 = b - a, c - a
    d = v0[0] * v1[1] - v0[1] * v1[0]
    s = (np.arange(k) + 0.5) / k - 0.5
    X, Y = np.meshgrid(cx + s, cy + s)
    wx, wy = X.ravel() - a[0], Y.ravel() - a[1]
    l1 = (wx * v1[1] - wy * v1[0]) / d
    l2 = (v0[0] * wy - v0[1] * wx) / d
    l0 = 1 - l1 - l2
    corners = np.array([[cx - 0.5, cy - 0.5], [cx + 0.5, cy - 0.5], [cx + 0.5, cy + 0.5], [cx - 0.5, cy + 0.5]])
    cwx, cwy = corners[:, 0] - a[0], corners[:, 1] - a[1]
    cl1 = (cwx * v1[1] - cwy * v1[0]) / d
    cl2 = (v0[0] * cwy - v0[1] * cwx) / d
    if np.any(cl1 < 0) or np.any(cl2 < 0) or np.any(1 - cl1 - cl2 < 0):
        return None
    return np.stack([l0, l1, l2], axis=1) @ p3


# ---------------------------------------------------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------------------------------------------------

class Baker:
    """aobaker.exe --headless with a channel of its own, connected."""

    def __init__(self, exe, tag):
        self.channel_name = f'static-{os.getpid()}-{tag}'
        self.proc = subprocess.Popen([exe, '--channel', self.channel_name, '--client-pid', str(os.getpid()), '--headless'],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.ch = client.connect(self.channel_name, wait=10.0)
        self.ready = self.ch.hello('test_ao_baker_static.py')
        assert self.ready['device_state'] == 'Ok', self.ready

    def close(self):
        try:
            self.ch.bye()
        finally:
            self.ch.close()
            self.proc.wait(timeout=30)


def owners_check(core, label, m, baked):
    """Finish line 1: the baker's owners against rasterize_ids', per tile, core and skirt."""
    cuv = m['muv'][m['core_tris']]
    diff_core = diff_skirt = px = 0
    for t in baked.tiles.values():
        rect = t['rect']
        diff_core += int((bm.python_owners(core, cuv, rect) != t['core_owner']).sum())
        if len(m['skirt_uv']):
            diff_skirt += int((bm.python_owners(core, m['skirt_uv'], rect) != t['skirt_owner']).sum())
        else:
            diff_skirt += int((t['skirt_owner'] != -1).sum())
        px += rect[2] * rect[3]
    check(f'owners-{label}', diff_core == 0 and diff_skirt == 0, tiles=len(baked.tiles), pixels=px,
          core_differing=diff_core, skirt_differing=diff_skirt)


def baked_values(baked):
    """Every baked value of the tiles' A and B (>= 0), and the tile entries."""
    vals = [t[k][t[k] >= 0] for t in baked.tiles.values() for k in ('A', 'B')]
    return np.concatenate(vals) if vals else np.zeros(0, np.float32)


def corner_check(core, m, pos, tris, baked, distance, samples, falloff=False):
    """Finish line 3, the plane meeting a wall: each core pixel whose footprint lies in its triangle and away from the
    faces' far edges, against the footprint's mean visibility (falloff: the mean of min(t / d, 1), step (c))."""
    L = 0.4
    ct = m['core_tris']
    cuv = m['muv'][ct]
    errs, sig = [], []
    for t in baked.tiles.values():
        x0, y0, w, h = t['rect']
        own = t['core_owner']
        ys, xs = np.nonzero(own >= 0)
        for py, px in zip(ys.tolist(), xs.tolist()):
            k = int(own[py, px])
            tri = int(ct[k])
            p3 = pos[tris[tri]]
            pts = footprint_points(cuv[k], p3, x0 + px + 0.5, y0 + py + 0.5)
            if pts is None:
                continue
            on_floor = np.allclose(p3[:, 2], 0.0)
            dist = pts[:, 0] if on_floor else pts[:, 2]
            far = pts[:, 2] if on_floor else pts[:, 0]
            if np.any(np.abs(pts[:, 1]) > L / 2 - distance) or np.any(far > L - distance) or np.any(dist > distance * 1.5):
                continue
            if falloff:
                fm, fv = falloff_value(dist / distance)
                v, var = float(fm.mean()), float(fv.mean())
            else:
                v = float(visibility(dist / distance).mean())
                var = v * (1 - v)
            errs.append(float(t['A'][py, px]) - v)
            sig.append(math.sqrt(max(var, 1e-12) / samples))
    errs, sig = np.array(errs), np.array(sig)
    z = np.abs(errs) / np.maximum(sig, 1.0 / samples)
    bound = 5.0
    check('corner-falloff-analytic' if falloff else 'corner-analytic', len(errs) > 1000 and float(z.max()) <= bound, pixels=len(errs),
          max_abs_error=round(float(np.abs(errs).max()), 5), mean_error=f'{float(errs.mean()):.2e}',
          rms_error=round(float(np.sqrt((errs ** 2).mean())), 5), max_error_over_sigma=round(float(z.max()), 2),
          rms_error_over_sigma=round(float(np.sqrt((z ** 2).mean())), 3), bound_sigma=bound,
          sigma_median=round(float(np.median(sig)), 5))


def translate(z):
    return (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, float(z))


def slab(h, half=0.25):
    """The occluder: a square plane at height h, facing down, wider than the target by more than the AO distance."""
    return merge([grid((-half, -half, h), (2 * half, 0, 0), (0, 2 * half, 0), 2, (0, 0, -1))], [(0, 0, -1)])[:2]


def view_scenarios(samples):
    """Step (c)'s view scenarios on the plane (0.2 m at z = 0) under occluder slabs, AO distance 0.1 m: (label, views,
    combine, per view the plane's height under its occluder) with the samples split as the runner splits them
    (decision 49: averaged views share the count; lightest and darkest keep each copy whole)."""
    def split(n):
        return max(1, -(-samples // n))
    h = 0.05
    up, up2 = 0.025, 0.0125
    return [
        ('mover-static', [dict(transform=translate(0.0), copy=0, samples=split(2), occluders=[0]),
                          dict(transform=translate(up), copy=0, samples=split(2), occluders=[0])],
         'AVERAGE', [h, h - up]),
        ('mover-posed', [dict(transform=translate(0.0), copy=0, samples=split(2), occluders=[0]),
                         dict(transform=translate(up), copy=0, samples=split(2), occluders=[1])],
         'AVERAGE', [h, h]),
        ('copies-average', [dict(transform=translate(0.0), copy=0, samples=split(2), occluders=[0]),
                            dict(transform=translate(up), copy=1, samples=split(2), occluders=[0])],
         'AVERAGE', [h, h - up]),
        ('copies-lightest', [dict(transform=translate(0.0), copy=0, samples=samples, occluders=[0]),
                             dict(transform=translate(up), copy=1, samples=samples, occluders=[0])],
         'LIGHTEST', [h, h - up]),
        ('copies-darkest', [dict(transform=translate(0.0), copy=0, samples=samples, occluders=[0]),
                            dict(transform=translate(up), copy=1, samples=samples, occluders=[0])],
         'DARKEST', [h, h - up]),
        ('copies-poses-average', [dict(transform=translate(0.0), copy=0, samples=split(4), occluders=[0]),
                                  dict(transform=translate(up), copy=0, samples=split(4), occluders=[0]),
                                  dict(transform=translate(up2), copy=1, samples=split(2), occluders=[0])],
         'AVERAGE', [h, h - up, h - up2]),
    ]


def expected_combination(views, combine, heights, distance):
    """(value, sigma per pixel) of a scenario: each view's (h / d)^2 and its binomial variance over its samples,
    combined as the runner combines (a copy's poses averaged, then the copies)."""
    copies = []
    for k, v in enumerate(views):
        p = (heights[k] / distance) ** 2
        if not copies or copies[-1][0] != v['copy']:
            copies.append([v['copy'], []])
        copies[-1][1].append((p, p * (1 - p) / v['samples']))
    vals = [(sum(p for p, _ in c[1]) / len(c[1]), sum(var for _, var in c[1]) / len(c[1]) ** 2) for c in copies]
    if combine == 'LIGHTEST':
        val, var = max(vals)
    elif combine == 'DARKEST':
        val, var = min(vals)
    else:
        val = sum(x for x, _ in vals) / len(vals)
        var = sum(y for _, y in vals) / len(vals) ** 2
    return val, math.sqrt(var)


def views_check(core, ch, samples):
    """Finish lines 6 and 7 of step (c) on the plane under the occluder slabs."""
    pos, tris, cn = plane_mesh()
    distance = 0.1
    m = bm.layout(core, pos, tris, cn, 1000.0)
    occluders = [slab(0.05), slab(0.075)]
    grid512 = core.tile_grid(m['W'], m['H'], 512)
    first = None
    for k, (label, views, combine, heights) in enumerate(view_scenarios(samples)):
        b = bm.bake_master(core, ch, f'views-{os.getpid()}-{k}', pos, tris, cn, m, distance, samples, 512,
                           occluders=occluders, views=views, combine=combine, scene_id=20 + k, keep_scene=True)
        try:
            val, sig = expected_combination(views, combine, heights, distance)
            v = baked_values(b)
            z = np.abs(v.astype(np.float64) - val) / max(sig, 1.0 / samples)
            bound = 5.0
            check(f'views-analytic-{label}', len(v) > 1000 and float(z.max()) <= bound, views=len(views),
                  combine=combine, samples=[x['samples'] for x in views], expected=round(val, 5),
                  mean=round(float(v.mean()), 5), max_abs_error=round(float(np.abs(v - val).max()), 5),
                  max_error_over_sigma=round(float(z.max()), 2), sigma=round(sig, 5), bound_sigma=bound)
            tiles, px, da, db = bm.combination_differences(ch, 20 + k, f'comb-{os.getpid()}-{k}', grid512, views,
                                                           combine)
            check(f'views-combination-bytes-{label}', da == 0 and db == 0, tiles=tiles, pixels=px, a_differing=da,
                  b_differing=db)
        finally:
            ch.release_scene(20 + k)
        if first is None:
            first = (label, views, combine, b)
    label, views, combine, b512 = first
    b2048 = bm.bake_master(core, ch, f'views2048-{os.getpid()}', pos, tris, cn, m, distance, samples, 2048,
                           occluders=occluders, views=views, combine=combine, scene_id=30)
    check(f'views-tile-512-equals-2048-{label}', b512.digest == b2048.digest, sha256_512=b512.digest[:16],
          sha256_2048=b2048.digest[:16], differing=int((b512.M16 != b2048.M16).sum()))


def cancel_check(core, ch, pos, tris, cn, m, distance):
    """A tile of many samples cancelled at its first Progress: the server answers Cancelled after its current launch
    (about 100 ms), and the scene bakes again afterwards."""
    target_tris, core_p, skirt_p = bm.scene_parts(pos, tris, cn, m)
    name = f'cancel-{os.getpid()}'
    block, nbytes = client.scene_block(name + '.scene', [(pos, target_tris)], [(0, True, client.IDENTITY)],
                                       [(client.IDENTITY, 0, 1 << 16, [0])], core_p, skirt_p, distance)
    ch.load_scene(7, name + '.scene', nbytes)
    block.close()
    rect = (0, 0, m['W'], m['H'])
    out = client.make_block(name + '.tile', 2 * m['W'] * m['H'] * 4)
    sent = {}

    def on_progress(p):
        if 'at' not in sent:
            sent['at'] = time.perf_counter()
            sent['done'] = p['samples_done']
            ch.cancel_tile()
    t = time.perf_counter()
    got = ch.bake_tile(7, rect, name + '.tile', 0, m['W'] * m['H'] * 4, on_progress=on_progress)
    answered = time.perf_counter()
    again = ch.bake_tile(7, (0, 0, 64, 64), name + '.tile', 0, 64 * 64 * 4)
    ch.release_scene(7)
    out.close()
    after = answered - sent.get('at', answered)
    check('tile-cancel', got is None and 'at' in sent and after < 0.5 and again is not None,
          samples=1 << 16, cancelled_after_samples=sent.get('done'), first_progress_s=round(sent.get('at', t) - t, 3),
          answer_after_cancel_s=round(after, 3), next_tile_ok=again is not None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--exe', required=True)
    ap.add_argument('--samples', type=int, default=1024)
    ap.add_argument('--out')
    args = ap.parse_args()
    core = bm.load_core()
    print(f'Python {sys.version.split()[0]}, numpy {np.__version__}, samples {args.samples}', flush=True)
    density = 1000.0  # px per m
    baker = Baker(args.exe, 'a')
    try:
        check('ready', baker.ready['device_state'] == 'Ok', device=baker.ready['device'],
              max_tile_pixels=baker.ready['max_tile_pixels'])
        # the plane: 1 everywhere
        pos, tris, cn = plane_mesh()
        m = bm.layout(core, pos, tris, cn, density)
        b = bm.bake_master(core, baker.ch, f'plane-{os.getpid()}', pos, tris, cn, m, 0.05, args.samples, 512, owners=True)
        owners_check(core, 'plane', m, b)
        v = baked_values(b)
        check('plane-analytic', len(v) > 0 and bool(np.all(v == 1.0)), master=f"{m['W']}x{m['H']}", baked=len(v),
              not_one=int((v != 1.0).sum()), min=float(v.min()))
        # the box: 0 everywhere
        pos, tris, cn = box_mesh()
        m = bm.layout(core, pos, tris, cn, density)
        b = bm.bake_master(core, baker.ch, f'box-{os.getpid()}', pos, tris, cn, m, 1.0, args.samples, 512, owners=True)
        owners_check(core, 'box', m, b)
        v = baked_values(b)
        check('box-analytic', len(v) > 0 and bool(np.all(v == 0.0)), master=f"{m['W']}x{m['H']}", baked=len(v),
              not_zero=int((v != 0.0).sum()), max=float(v.max()))
        # a face lying in another surface and facing into it (add-on decision 26): 0 everywhere, as Cycles bakes it;
        # the same surface 1 mm behind the face is not in contact: 1 everywhere
        size = 0.2
        pos, tris, cn = merge([grid((-size / 2, -size / 2, 0), (size, 0, 0), (0, size, 0), 4, (0, 0, -1))],
                              [(0, 0, -1)])
        m = bm.layout(core, pos, tris, cn, density)
        for label, z, want in (('flush', 0.0, 0.0), ('behind-1mm', 0.001, 1.0)):
            opos, otris, _ocn = plane_mesh(size * 2)
            occ = [((opos + (0.0, 0.0, z)).astype(np.float32), otris.astype(np.uint32))]
            b = bm.bake_master(core, baker.ch, f'{label}-{os.getpid()}', pos, tris, cn, m, 0.05, args.samples, 512,
                               occluders=occ)
            v = baked_values(b)
            check(f'{label}-analytic', len(v) > 0 and bool(np.all(v == want)), master=f"{m['W']}x{m['H']}",
                  baked=len(v), expected=want, other=int((v != want).sum()), min=float(v.min()), max=float(v.max()))
        # the corner: owners, analytic, tile sizes, a second run
        pos, tris, cn = corner_mesh()
        distance = 0.1
        m = bm.layout(core, pos, tris, cn, density)
        t = time.perf_counter()
        b512 = bm.bake_master(core, baker.ch, f'corner-{os.getpid()}', pos, tris, cn, m, distance, args.samples, 512,
                              owners=True)
        wall = time.perf_counter() - t
        owners_check(core, 'corner-512', m, b512)
        corner_check(core, m, pos, tris, b512, distance, args.samples)
        rays, trace, rate = bm.rays_per_second(b512)
        check('rays-per-second', rate > 0, master=f"{m['W']}x{m['H']}", tiles=len(b512.tiles), rays=rays,
              trace_s=round(trace, 3), grays_per_s=round(rate / 1e9, 3), master_wall_s=round(wall, 3),
              scene_s=round(b512.seconds['scene'], 3), compose_s=round(b512.seconds['compose'], 3),
              raster_s=round(sum(x['done']['raster_s'] for x in b512.tiles.values()), 3))
        b2048 = bm.bake_master(core, baker.ch, f'corner2-{os.getpid()}', pos, tris, cn, m, distance, args.samples, 2048,
                               owners=True)
        owners_check(core, 'corner-2048', m, b2048)
        same = np.array_equal(b512.M16, b2048.M16) and np.array_equal(b512.codes, b2048.codes)
        check('tile-512-equals-2048', same, master=f"{m['W']}x{m['H']}", tiles_512=len(b512.tiles),
              tiles_2048=len(b2048.tiles), differing=int((b512.M16 != b2048.M16).sum()))
        cancel_check(core, baker.ch, pos, tris, cn, m, distance)
        # step (c): the falloff on the corner, the occluder, poses and copies on the plane
        bf = bm.bake_master(core, baker.ch, f'falloff-{os.getpid()}', pos, tris, cn, m, distance, args.samples, 512,
                            owners=True, falloff=True)
        corner_check(core, m, pos, tris, bf, distance, args.samples, falloff=True)
        views_check(core, baker.ch, args.samples)
    finally:
        baker.close()
    # a second run in a new baker process
    baker = Baker(args.exe, 'b')
    try:
        again = bm.bake_master(core, baker.ch, f'corner3-{os.getpid()}', pos, tris, cn, m, distance, args.samples, 512)
        check('second-run-identical', np.array_equal(b512.M16, again.M16), differing=int((b512.M16 != again.M16).sum()))
    finally:
        baker.close()
    failed = [r['name'] for r in RESULTS if not r['ok']]
    print(f'{len(RESULTS) - len(failed)} passed, {len(failed)} failed' + (f': {failed}' if failed else ''))
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as f:
            json.dump(RESULTS, f, indent=1)
    return len(failed)


if __name__ == '__main__':
    sys.exit(main())
