"""A master baked through the AO Baker (OptiX baker journal 20261114.optix-baker.md, step (b)): the layout from the
add-on's ao_bake_core.build_master, the pieces as the runner's bake_item cuts them, the tiles from the baker, the
composition from the add-on's bake_paged with the runner's single-view rule. Step (c): occluder meshes, views (a
mover's poses, a shared mesh's copies) with their samples, the falloff and the combine; the baker combines the views,
combine_views() does the same in numpy from the single-view bakes (the byte-for-byte check). No add-on file is changed; the add-on's own
client (step (d)) will do this inside the runner.

Works in plain Python and in Blender's Python (numpy, the add-on's ao_bake_core loaded from this repository).
"""
import hashlib
import importlib.util
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ao_baker_client as client  # noqa: E402


def load_core():
    """The add-on's ao_bake_core from this repository (in Blender the test imports the add-on and passes it in)."""
    name = 'fss_ao_bake_core_for_tests'
    if name in sys.modules:
        return sys.modules[name]
    path = os.path.join(os.path.dirname(HERE), 'fss_blender_tools', 'ao_bake_core.py')
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def layout(core, pos, tris, cn, density):
    """The master layout with the runner's settings (bake_item)."""
    m = core.build_master(pos, tris, cn, density, gutter=core.GUTTER, order=core.ORDER, mirror_open=core.MIRROR_OPEN,
                          fold_split=core.FOLD_SPLIT)
    m['corner_pairs'] = core.corner_pairs(m, pos, tris)
    return m


def scene_parts(pos, tris, cn, m):
    """(target triangles, core pieces, skirt pieces): the target is tris with three distinct corners (the runner's
    FSS_AO_TARGET), each piece names the target triangle it lies on (core: itself; skirt: skirt_src)."""
    distinct = np.array([len(set(r)) == 3 for r in np.asarray(tris).tolist()], dtype=bool)
    tmap = np.full(len(tris), -1, dtype=np.int64)
    tmap[distinct] = np.arange(int(distinct.sum()))
    ct = m['core_tris']

    def target(idx):
        t = tmap[idx]
        return np.where(t >= 0, t, client.NO_TRIANGLE)
    core_p = client.pieces(target(ct), pos[tris[ct]], cn[ct], m['muv'][ct])
    src = np.asarray(m['skirt_src'], dtype=np.int64)
    skirt_p = client.pieces(target(src), m['skirt_pos'], m['skirt_n'], m['skirt_uv'])
    return np.asarray(tris)[distinct], core_p, skirt_p


class BakedMaster:
    """A master's tiles from the baker and its composition: M16 (H, W) uint16 and codes (H, W) int32, rows from the
    top as the files have them; per tile its A, B (and owners when asked) and TileDone."""

    def __init__(self):
        self.tiles = {}
        self.M16 = self.codes = None
        self.digest = None  # SHA-256 of the composed rows (values, then codes, strip by strip from the top)
        self.counts = {}
        self.scene = None
        self.seconds = dict(scene=0.0, bake=0.0, compose=0.0)


def views_scene(pos, target_tris, occluders=(), views=None, samples=1024):
    """(meshes, instances, views) of a scene block: mesh 0 the target, then each occluder (positions (v, 3) in bake
    space, triangles (t, 3)) as one instance in place. views: [dict(transform (3 x 4 or 4 x 4), copy, samples,
    occluders: indices into occluders)], the copies' views consecutive; None: one view of every occluder."""
    meshes = [(pos, target_tris)] + [(p, t) for p, t in occluders]
    instances = [(0, True, client.IDENTITY)] + [(k + 1, False, client.IDENTITY) for k in range(len(occluders))]
    if views is None:
        views = [dict(transform=client.IDENTITY, copy=0, samples=samples, occluders=list(range(len(occluders))))]
    out = []
    for v in views:
        tr = np.asarray(v['transform'], dtype=np.float64)
        tr = tr[:3, :4] if tr.shape == (4, 4) else tr.reshape(3, 4)
        out.append((tr.ravel(), int(v['copy']), int(v['samples']), [0] + [k + 1 for k in v['occluders']]))
    return meshes, instances, out


def combine_views(means, views, combine):
    """The baker's combination (AoTileBaker) of the views' means (float32 arrays, -1 where not baked) in numpy: per
    copy its views summed in float64 and divided by their count; the copies averaged, or the lightest, or the
    darkest; clamped to 0..1, float32; -1 where not baked."""
    owned = means[0] >= 0
    result = None
    copies = 0
    pose_sum = np.zeros(means[0].shape, np.float64)
    poses = 0
    for k, v in enumerate(views):
        pose_sum = pose_sum + means[k].astype(np.float64)
        poses += 1
        if k + 1 == len(views) or views[k + 1]['copy'] != v['copy']:
            c = pose_sum / float(poses)
            if result is None:
                result = c if combine in ('LIGHTEST', 'DARKEST') else 0.0 + c
            elif combine == 'LIGHTEST':
                result = np.maximum(result, c)
            elif combine == 'DARKEST':
                result = np.minimum(result, c)
            else:
                result = result + c
            copies += 1
            pose_sum = np.zeros(means[0].shape, np.float64)
            poses = 0
    if combine not in ('LIGHTEST', 'DARKEST'):
        result = result / float(copies)
    return np.where(owned, np.clip(result, 0.0, 1.0).astype(np.float32), np.float32(-1.0))


def bake_master(core, ch, name, pos, tris, cn, m, distance, samples, tile, seed=11, owners=False, scene_id=1,
                keep_tiles=True, keep_rows=True, on_tile=None, occluders=(), views=None, falloff=False,
                combine='AVERAGE', keep_scene=False):
    """Bakes and composes one master through the channel ch; name: a prefix for the shared memory blocks.
    keep_tiles: keep each tile's A and B (and owners); on_tile(entry): called with each tile's entry (owners included)
    before it is dropped; keep_rows: keep M16 and codes (else only their digest). occluders, views: see views_scene;
    keep_scene: leave the scene loaded (the caller releases it)."""
    out = BakedMaster()
    target_tris, core_p, skirt_p = scene_parts(pos, tris, cn, m)
    t0 = time.perf_counter()
    meshes, instances, vlist = views_scene(pos, target_tris, occluders, views, samples)
    block, nbytes = client.scene_block(f'{name}.scene', meshes, instances, vlist, core_p, skirt_p, distance,
                                       falloff=falloff, combine=combine, seed=seed)
    try:
        out.scene = ch.load_scene(scene_id, f'{name}.scene', nbytes)
    finally:
        block.close()
    out.seconds['scene'] = time.perf_counter() - t0
    W, H = m['W'], m['H']
    grid = core.tile_grid(W, H, tile)
    biggest = max(w * h for _x, _y, w, h in grid)
    a_off, b_off, o_off = 0, biggest * 4, 2 * biggest * 4
    tile_block = client.make_block(f'{name}.tile', (4 if owners else 2) * biggest * 4)
    rects = m['rects']

    def bake_tile(i, rect, win, baked):
        x0, y0, w, h = rect
        tb = time.perf_counter()
        done = ch.bake_tile(scene_id, rect, f'{name}.tile', a_off, b_off, o_off if owners else client.NO_OFFSET,
                            tile=i + 1, tiles=len(grid))
        out.seconds['bake'] += time.perf_counter() - tb
        A = np.frombuffer(tile_block, np.float32, w * h, a_off).reshape(h, w).copy()
        B = np.frombuffer(tile_block, np.float32, w * h, b_off).reshape(h, w).copy()
        entry = dict(rect=rect, done=done)
        if owners:
            o = np.frombuffer(tile_block, np.int32, 2 * w * h, o_off).reshape(2, h, w).copy()
            entry['core_owner'], entry['skirt_owner'] = o[0], o[1]
        entry['A'], entry['B'] = A, B
        if on_tile is not None:
            on_tile(entry)
        if not keep_tiles:
            for k in ('A', 'B', 'core_owner', 'skirt_owner'):
                entry.pop(k, None)
        out.tiles[i] = entry
        # the runner's single-view rule (bake_tile without poses or views)
        cm = A >= 0
        win[cm] = core.quantize16(A[cm])
        sm = (~cm) & (B >= 0) & (core.rect_window(rects, x0, y0, w, h) >= 0)
        win[sm] = core.quantize16(B[sm])
        baked |= cm | sm
        yield i

    rows = []
    digest = hashlib.sha256()

    def write_rows(values, codes):
        digest.update(np.ascontiguousarray(values).tobytes())
        digest.update(np.ascontiguousarray(codes).tobytes())
        if keep_rows:
            rows.append((values.copy(), codes.copy()))
    tc = time.perf_counter()
    try:
        for _ in core.bake_paged(m, tile, bake_tile, write_rows, out.counts):
            pass
    finally:
        tile_block.close()
        if not keep_scene:
            ch.release_scene(scene_id)
    out.seconds['compose'] = time.perf_counter() - tc - out.seconds['bake']
    out.digest = digest.hexdigest()
    if keep_rows:
        out.M16 = np.concatenate([r[0] for r in rows], axis=0)
        out.codes = np.concatenate([r[1] for r in rows], axis=0)
        assert out.M16.shape == (H, W), (out.M16.shape, H, W)
    return out


def owner_differences(core, m, entry):
    """(core, skirt) pixels of the tile whose owner differs from rasterize_ids'."""
    rect = entry['rect']
    dc = int((python_owners(core, m['muv'][m['core_tris']], rect) != entry['core_owner']).sum())
    if len(m['skirt_uv']):
        ds = int((python_owners(core, m['skirt_uv'], rect) != entry['skirt_owner']).sum())
    else:
        ds = int((entry['skirt_owner'] != -1).sum())
    return dc, ds


def python_owners(core, uv, rect):
    """rasterize_ids' owners of the window rect among the triangles uv (n, 3, 2), as global indices (-1 none), as
    the runner would cut them (tris_in_window, in order)."""
    x0, y0, w, h = rect
    sel = core.tris_in_window(uv, x0, y0, w, h)
    if not len(sel):
        return np.full((h, w), -1, dtype=np.int64)
    own, _count = core.rasterize_ids(uv[sel], w, h, 1, x0, y0)
    return np.where(own >= 0, sel[np.maximum(own, 0)], -1).astype(np.int64)


def rays_per_second(baked):
    rays = sum(t['done']['rays'] for t in baked.tiles.values())
    trace = sum(t['done']['trace_s'] for t in baked.tiles.values())
    return rays, trace, (rays / trace if trace > 0 else 0.0)


def tile_arrays(ch, scene_id, name, rect, only_view=0):
    """(A, B) of one tile baked alone (only_view as in Channel.bake_tile) and its TileDone."""
    x0, y0, w, h = rect
    blk = client.make_block(f'{name}.one', 2 * w * h * 4)
    try:
        done = ch.bake_tile(scene_id, rect, f'{name}.one', 0, w * h * 4, only_view=only_view)
        A = np.frombuffer(blk, np.float32, w * h, 0).reshape(h, w).copy()
        B = np.frombuffer(blk, np.float32, w * h, w * h * 4).reshape(h, w).copy()
    finally:
        blk.close()
    return A, B, done


def combination_differences(ch, scene_id, name, rects, views, combine):
    """Finish line 1 of step (c): per tile, the combined bake against combine_views of its single-view bakes (the
    same keys); returns (tiles, pixels, differing A pixels, differing B pixels), bytes compared."""
    tiles = px = da = db = 0
    for rect in rects:
        A, B, _d = tile_arrays(ch, scene_id, name, rect)
        ones = [tile_arrays(ch, scene_id, name, rect, only_view=k + 1)[:2] for k in range(len(views))]
        ca = combine_views([o[0] for o in ones], views, combine)
        cb = combine_views([o[1] for o in ones], views, combine)
        da += int((A.view(np.uint32) != ca.view(np.uint32)).sum())
        db += int((B.view(np.uint32) != cb.view(np.uint32)).sum())
        tiles += 1
        px += A.size
    return tiles, px, da, db
