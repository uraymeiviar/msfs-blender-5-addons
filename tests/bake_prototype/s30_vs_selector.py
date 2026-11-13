"""Session 29, finish lines 2 and 6: the VS selector of the E2 cockpit (a copy) baked at 1 and at 5 poses.

Run (CPU cap; the tool's second Blender inherits it) on a copy of the cockpit, never the production file:
    blender -b <copy>/COCKPIT.blend --factory-startup --python s30_vs_selector.py -- out=<folder> [name=<object>]
        [poses=1,5] [radius=0.55,0.85] [sectors=16]

For each pose count: the object's override set to it (in this Blender only; the file is not saved), Refresh, Bake
Selected (hidden), the master's files copied to out/p<N>/, a 16-bit PNG of the master (rows as the master, not a
texture) to out/vs_p<N>.png, the entry's times and peak working set. Then per pose count the master's AO per angle
sector about the wheel's rotation axis (from its animation: the fixed line of its motion between two frames of its
range, in object space), at radii between `radius` x the side faces' largest radius, on the faces whose normal is
within 18 degrees of the axis, each side separately: the sector means and their variation (max - min). out/vs.json.
"""
import json
import math
import os
import shutil
import sys
import time
from pathlib import Path

import addon_utils
import bpy
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = Path(HERE).parents[1]
for name in ('fss_blender_tools',):
    if addon_utils.check(name)[1]:
        addon_utils.disable(name)
    for mod in list(sys.modules.keys()):
        if mod == name or mod.startswith(name + '.'):
            del sys.modules[mod]
while str(REPO) in sys.path:
    sys.path.remove(str(REPO))
sys.path.insert(0, str(REPO))
import fss_blender_tools  # noqa: E402,F401
from fss_blender_tools import ao_bake_core as core, ao_bake_store as store  # noqa: E402

addon_utils.enable('fss_blender_tools', default_set=True)
assert Path(sys.modules['fss_blender_tools'].__file__).resolve().is_relative_to(REPO)

args = dict(a.split('=', 1) for a in (sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []))
OUT = args['out']
NAME = args.get('name', 'B_GS_AFCS_VERTG_VS_SELECTOR')
POSES = [int(x) for x in args.get('poses', '1,5').split(',')]
R0, R1 = (float(x) for x in args.get('radius', '0.55,0.85').split(','))
NSEC = int(args.get('sectors', 16))
os.makedirs(OUT, exist_ok=True)
assert 'e-jets-e2' not in bpy.data.filepath.lower() and 'new-fss-aircraft' not in bpy.data.filepath.lower()
LOG = os.path.join(OUT, 'vs.log.txt')


def log(msg):
    print(msg, flush=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(msg + '\n')


scene = bpy.context.scene
obj = bpy.data.objects[NAME]
log(f"{NAME}: file {bpy.data.filepath}, frame {scene.frame_current}, mover {store.is_mover(obj, scene)}, range "
    f"{store.mover_range(obj)}; distance {scene.fss_ao_bake.distance}, samples {scene.fss_ao_bake.samples}")

# the rotation axis in object space, from the motion between two frames of the range
rng = store.mover_range(obj)
f_ref = scene.frame_current
M_ref = np.array(obj.matrix_world, dtype=np.float64)
mats = []
for f in (rng[0], (rng[0] + rng[1]) / 2):
    scene.frame_set(int(math.floor(f)), subframe=float(f - math.floor(f)))
    mats.append(np.linalg.inv(M_ref) @ np.array(obj.matrix_world, dtype=np.float64))
scene.frame_set(f_ref)
rel = np.linalg.inv(mats[0]) @ mats[1]
w, v = np.linalg.eig(rel[:3, :3])
axis = np.real(v[:, np.argmin(np.abs(w - 1))])
axis /= np.linalg.norm(axis)
angle = math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(rel[:3, :3]) - 1) / 2))))
centre = np.linalg.lstsq(np.eye(3) - rel[:3, :3], rel[:3, 3], rcond=None)[0]
centre -= axis * float(centre @ axis)
log(f"  axis (object space) {np.round(axis, 4).tolist()}, through {np.round(centre, 5).tolist()}; "
    f"{angle:.1f} degrees between frames {rng[0]:g} and {(rng[0] + rng[1]) / 2:g}")
ref = np.array([1.0, 0, 0]) if abs(axis[0]) < 0.9 else np.array([0, 1.0, 0])
u = np.cross(axis, ref)
u /= np.linalg.norm(u)
vv = np.cross(axis, u)


def profile(folder, stem):
    m = core.load_master(folder, stem)
    ev = core.evaluated_triangles(obj, bpy.context.evaluated_depsgraph_get(), [])
    co = ev['co'][ev['tris'][m['tri_src']]]
    k = 8
    g = np.array([(i, j, k - i - j) for i in range(k + 1) for j in range(k + 1 - i)], np.float64) / k
    g = 0.02 / 3 + 0.98 * g
    P = np.einsum('sk,tkd->tsd', g, co) - centre
    UV = np.einsum('sk,tkd->tsd', g, m['muv'])
    n = np.cross(co[:, 1] - co[:, 0], co[:, 2] - co[:, 0])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-30)
    ix = np.clip(np.floor(UV[..., 0]).astype(np.int64), 0, m['W'] - 1)
    iy = np.clip(np.floor(UV[..., 1]).astype(np.int64), 0, m['H'] - 1)
    val = m['image'][iy, ix] / 65535.0
    ok = m['filled'][iy, ix]
    a = P @ u
    b = P @ vv
    r = np.hypot(a, b)
    ang = np.degrees(np.arctan2(b, a)) % 360.0
    sec = np.minimum((ang / (360.0 / NSEC)).astype(np.int64), NSEC - 1)
    nd = n @ axis
    out = {}
    for side, sign in (('+axis', 1), ('-axis', -1)):
        face = (nd * sign > 0.95)
        if not face.any():
            continue
        rmax = float(r[face].max())
        sel = face[:, None] & ok & (r >= R0 * rmax) & (r <= R1 * rmax)
        means = [float(val[sel & (sec == q)].mean()) if (sel & (sec == q)).any() else None for q in range(NSEC)]
        got = [x for x in means if x is not None]
        out[side] = dict(means=[None if x is None else round(x, 4) for x in means],
                         variation=round(max(got) - min(got), 4) if got else None, r_max_m=round(rmax, 5),
                         samples=int(sel.sum()), faces=int(face.sum()))
    return m, out


results = {}
folder = None
for N in POSES:
    obj.fss_ao_bake.poses = N
    t = time.time()
    bpy.ops.fss.ao_bake_refresh()
    t_refresh = time.time() - t
    item = store._state['items'][store._state['by_object'][NAME]]
    for o in bpy.context.view_layer.objects:
        o.select_set(o == obj)
    bpy.context.view_layer.objects.active = obj
    t = time.time()
    assert bpy.ops.fss.ao_bake_start(scope='SELECTED', hidden=True, wait=True) == {'FINISHED'}
    t_run = time.time() - t
    folder = store.bake_folder()
    status = store.read_status(folder)
    entry = store.read_index(folder, use_cache=False)['masters'][item['key']]
    sub = os.path.join(OUT, f'p{N}')
    os.makedirs(sub, exist_ok=True)
    for p in core.all_master_files(folder, item['key']):
        if os.path.isfile(p):
            shutil.copy2(p, sub)
    m, prof = profile(folder, item['key'])
    png = os.path.join(OUT, f'vs_p{N}.png')
    core.write_png_int(png, m['image'])
    results[N] = dict(poses=entry.get('poses'), n_poses=entry.get('n_poses'), note=entry.get('pose_note'),
                      occluders=entry.get('occluders'), W=entry['W'], H=entry['H'], times=entry['times'],
                      tiles=entry['tiles'], second_blender_s=round(t_run, 1), refresh_s=round(t_refresh, 1),
                      state=status['state'], result=status['results'][0], png=png, profile=prof)
    log(f"  {N} pose(s): {status['state']}, master {entry['W']} x {entry['H']}, poses {entry.get('poses')}, "
        f"{len(entry.get('occluders') or [])} occluders, bake {entry['times']['bake_s']} s, whole master "
        f"{entry['times']['total_s']} s, second Blender {t_run:.1f} s, peak working set "
        f"{entry['tiles']['peak_working_set_gb']} GB (refresh {t_refresh:.1f} s)")
    for side, p in prof.items():
        log(f"    {side}: variation {p['variation']}, means {p['means']} ({p['samples']} samples, r_max {p['r_max_m']} m)")
with open(os.path.join(OUT, 'vs.json'), 'w', encoding='utf-8') as f:
    json.dump(dict(name=NAME, axis=axis.tolist(), centre=centre.tolist(), radius=[R0, R1], sectors=NSEC,
                   results=results), f, indent=1)
if 1 in results and len(results) > 1:
    for N in results:
        if N == 1:
            continue
        for side in results[N]['profile']:
            a, b = results[1]['profile'][side]['variation'], results[N]['profile'][side]['variation']
            log(f"  {side}: {N} poses / 1 pose variation {b} / {a} = {b / a:.3f}" if a else f"  {side}: no variation")
        p1, pn = results[1]['tiles']['peak_working_set_gb'], results[N]['tiles']['peak_working_set_gb']
        log(f"  peak working set {N} poses / 1 pose: {pn} / {p1} GB = {pn / p1:.3f}")
