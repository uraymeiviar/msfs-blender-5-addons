"""The AO Baker's step (b) on a production object against the Cycles bake (OptiX baker journal 20261114.optix-baker.md;
Glider plan PLAN-20261114.optix-ao-baker.md, step (b), finish lines 1, 2 and 4). On a copy of the E2 cockpit in
tests/_work/ao_baker_cycles/ (never the original):

- the add-on bakes the object with Cycles through its own operator (a second Blender, the file's device and samples,
  Self Only, falloff off, no curvature, no denoise), as an artist's bake would;
- the same layout is rebuilt here from the job (the runner's bake_item steps) and baked through aobaker.exe at the
  tile size the runner chose, at 2048 and at 512: the owners of every tile against rasterize_ids (finish line 1), the
  masters byte-identical across the tile sizes (finish line 2);
- measured (finish line 4): rays per second, the time per master against the Cycles bake's, and the difference from
  the Cycles master (mean, mean absolute, 99th percentile and largest, over the pixels both baked; D4: no byte
  comparison is asked).

    C:\\Users\\uray\\.claude\\tools\\cpucap\\cpucap.exe 50 G:\\e-jets-e2\\tools\\blender\\blender.exe -b --factory-startup
        tests\\_work\\ao_baker_cycles\\COCKPIT.blend --python tests\\test_ao_baker_cycles.py --
        --exe F:\\glider\\out\\bin\\x64\\Release\\aobaker.exe [--object SEAT_OBS] [--out report.json] [--keep-cycles]
"""
import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

import addon_utils
import bpy
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
ADDONS = ('io_scene_gltf2_msfs_fss', 'fss_blender_tools')
for name in reversed(ADDONS):
    if addon_utils.check(name)[1]:
        addon_utils.disable(name)
    for mod in list(sys.modules.keys()):
        if mod == name or mod.startswith(name + '.'):
            del sys.modules[mod]
while str(REPO_ROOT) in sys.path:
    sys.path.remove(str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / 'tests'))
import io_scene_gltf2_msfs_fss  # noqa: E402,F401
import fss_blender_tools  # noqa: E402,F401
from fss_blender_tools import ao_bake_core as core, ao_bake_store as store  # noqa: E402
for name in ADDONS:
    addon_utils.enable(name, default_set=True)
    assert Path(sys.modules[name].__file__).resolve().is_relative_to(REPO_ROOT), sys.modules[name].__file__
import ao_baker_master as bm  # noqa: E402
from test_ao_baker_static import Baker, check, RESULTS  # noqa: E402

WORK = REPO_ROOT / 'tests' / '_work' / 'ao_baker_cycles'


def args_after_dashes():
    ap = argparse.ArgumentParser()
    ap.add_argument('--exe', required=True)
    ap.add_argument('--object', default='SEAT_OBS')
    ap.add_argument('--out')
    ap.add_argument('--keep-cycles', action='store_true', help='use the Cycles master already in the bake folder')
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    return ap.parse_args(argv)


def cycles_bake(obj_name, keep):
    """The add-on's own bake of the object (a second Blender); returns (job item, index entry, wall seconds)."""
    folder = store.bake_folder()
    assert Path(folder).resolve().is_relative_to(WORK.resolve()), folder  # only the copy's bake folder
    if not keep and os.path.isdir(folder):
        shutil.rmtree(folder)
    scene = bpy.context.scene
    s = scene.fss_ao_bake
    s.occluders, s.falloff, s.curvature, s.denoise, s.bake_ao = 'SELF', False, False, False, True
    obj = bpy.data.objects[obj_name]
    vl = bpy.context.view_layer
    for o in vl.objects:
        o.select_set(False)
    obj.select_set(True)
    vl.objects.active = obj
    t = time.perf_counter()
    if not keep:
        res = bpy.ops.fss.ao_bake_start(scope='SELECTED', hidden=True, wait=True)
        assert res == {'FINISHED'}, res
    wall = time.perf_counter() - t
    with open(os.path.join(folder, 'job.json'), encoding='utf-8') as f:
        job = json.load(f)
    item = [it for it in job['items'] if it['object'] == obj_name][0]
    with open(os.path.join(folder, 'index.json'), encoding='utf-8') as f:
        index = json.load(f)
    entry = index['masters'][item['key']]
    return job, item, entry, wall, folder


def prepare(job, item):
    """bake_item's steps up to the layout (ao_bake_runner.py), on this Blender's copy of the file."""
    SET = job['settings']
    if item.get('frame') is not None:
        bpy.context.scene.frame_set(int(item['frame']))
    obj = bpy.data.objects[item['object']]
    dist = float(item.get('ao_distance', SET['ao_distance']))
    dg = bpy.context.evaluated_depsgraph_get()
    uv_name = item['uv']
    ev = core.evaluated_triangles(obj, dg, [uv_name])
    sizes = item['tex_size']
    skip = set(item['skip_slots'])
    sel = np.array([(m not in skip) and (str(int(m)) in sizes) for m in ev['mat'].tolist()], dtype=bool)
    tri_src = np.nonzero(sel)[0]
    pos_w, _ = core.to_world(ev)
    used = np.unique(ev['tris'][tri_src])
    lo, hi = pos_w[used].min(axis=0), pos_w[used].max(axis=0)
    shift = (lo + hi) / 2
    pos, cn = core.to_world(ev, shift)
    tris = ev['tris'][tri_src]
    cnm = cn[tri_src]
    size = np.array([float(sizes[str(int(m))]) for m in ev['mat'][tri_src]])
    uvpx = ev['uv'][uv_name][tri_src] * size[:, None, None]
    D = core.master_density(pos, tris, uvpx)
    m = bm.layout(core, pos, tris, cnm, D)
    return pos, tris, cnm, m, dist, int(SET['samples'])


def compare_cycles(label, baked, cyc):
    """Our master against the Cycles master, over the pixels both have a value for (the map's filled flag: baked, or
    filled from a baked pixel of its island). load_master's rows start at the bottom, the composed rows at the top."""
    ours = baked.M16[::-1]
    codes = baked.codes[::-1]
    fill_o = core.code_filled(codes)
    face_c, fill_c = cyc['face_map'], cyc['filled']
    both = fill_o & fill_c
    check(f'cycles-valued-{label}', True, ours=int(fill_o.sum()), cycles=int(fill_c.sum()), both=int(both.sum()),
          only_ours=int((fill_o & ~fill_c).sum()), only_cycles=int((fill_c & ~fill_o).sum()))
    d = ours[both].astype(np.float64) / 65535.0 - cyc['image'][both].astype(np.float64) / 65535.0
    a = np.abs(d)
    check(f'cycles-difference-{label}', True, pixels=int(both.sum()), mean=round(float(d.mean()), 5),
          mean_abs=round(float(a.mean()), 5), p99_abs=round(float(np.percentile(a, 99)), 4),
          max_abs=round(float(a.max()), 4), share_over_0_05=round(float((a > 0.05).mean()), 5),
          ours_mean=round(float(ours[both].mean() / 65535.0), 4),
          cycles_mean=round(float(cyc['image'][both].mean() / 65535.0), 4),
          map_codes_differing=int((codes != core.map_code(face_c, fill_c)).sum()))


def main():
    args = args_after_dashes()
    assert Path(bpy.data.filepath).resolve().is_relative_to(WORK.resolve()), bpy.data.filepath
    job, item, entry, cycles_wall, folder = cycles_bake(args.object, args.keep_cycles)
    print(f"Cycles: {item['name']} {entry['W']} x {entry['H']} px, tile {entry['tiles']['size']}, {entry['samples']} "
          f"samples, device {job['settings']['device']}, times {entry['times']}, wall {cycles_wall:.1f} s", flush=True)
    pos, tris, cnm, m, dist, samples = prepare(job, item)
    check('layout-as-cycles', (m['W'], m['H']) == (entry['W'], entry['H']) and len(tris) == entry['tris'],
          ours=f"{m['W']}x{m['H']}", cycles=f"{entry['W']}x{entry['H']}", tris=len(tris), distance_m=dist)
    cyc = core.load_master(folder, item['key'])
    baker = Baker(args.exe, 'cycles')
    try:
        tiles = []
        for t in (int(entry['tiles']['size']), 2048, 512):
            if t not in tiles:
                tiles.append(t)
        masters = {}
        for t in tiles:
            diffs = dict(core=0, skirt=0, px=0, check_s=0.0)

            def on_tile(entry):
                tc = time.perf_counter()
                dc, ds = bm.owner_differences(core, m, entry)
                diffs['core'] += dc
                diffs['skirt'] += ds
                diffs['px'] += entry['rect'][2] * entry['rect'][3]
                diffs['check_s'] += time.perf_counter() - tc
            t0 = time.perf_counter()
            b = bm.bake_master(core, baker.ch, f'cyc-{os.getpid()}-{t}', pos, tris, cnm, m, dist, samples, t,
                               owners=True, keep_tiles=False, keep_rows=t == tiles[0], on_tile=on_tile)
            wall = time.perf_counter() - t0 - diffs['check_s']
            masters[t] = b
            check(f'owners-{item["name"]}-{t}', diffs['core'] == 0 and diffs['skirt'] == 0, tiles=len(b.tiles),
                  pixels=diffs['px'], core_differing=diffs['core'], skirt_differing=diffs['skirt'])
            rays, trace, rate = bm.rays_per_second(b)
            check(f'time-tile-{t}', True, tiles=len(b.tiles), master_wall_s=round(wall, 2), trace_s=round(trace, 2),
                  scene_s=round(b.seconds['scene'], 3), compose_s=round(b.seconds['compose'], 2),
                  raster_s=round(sum(x['done']['raster_s'] for x in b.tiles.values()), 3), grays=round(rays / 1e9, 2),
                  grays_per_s=round(rate / 1e9, 2), cycles_bake_s=entry['times']['bake_s'],
                  cycles_total_s=entry['times']['total_s'], speedup_bake=round(entry['times']['bake_s'] / max(trace, 1e-9), 1),
                  speedup_master=round(entry['times']['total_s'] / max(wall, 1e-9), 1))
        first = masters[tiles[0]]
        for t in tiles[1:]:
            check(f'tile-{tiles[0]}-equals-{t}', first.digest == masters[t].digest, sha256_first=first.digest[:16],
                  sha256_other=masters[t].digest[:16])
        compare_cycles(item['name'], first, cyc)
    finally:
        baker.close()
    failed = [r['name'] for r in RESULTS if not r['ok']]
    print(f'{len(RESULTS) - len(failed)} passed, {len(failed)} failed' + (f': {failed}' if failed else ''), flush=True)
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as f:
            json.dump(RESULTS, f, indent=1)
    return len(failed)


if __name__ == '__main__':
    code = main()
    sys.stdout.flush()
    os._exit(code)
