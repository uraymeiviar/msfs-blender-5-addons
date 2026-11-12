"""Session 17, finish lines 1 and 9: the tool's Bake and Apply on the prototype's extracted objects, measured with
Session 14's FAIR reference.

Run (CPU cap; the tool's second Blender inherits it), one object per run:
    blender -b --factory-startup --python s17_round_trip.py -- tag=panel layouts=abdf [tile=512] [sub=s20] [seed_offset=1]

tile: force the bake's tile size (Session 20, finish lines 3 and 4; 0 or none: the tool's choice); sub: the folder in
tests/_work/ao_bake/ for the files (default s17).

1. A .blend in tests/_work/ao_bake/s17/<tag>.blend: the prototype's scene_<tag>.blend (TARGET and its occluders), the
   TARGET with a material whose texture set size is the object's texture size and its material's UV map active.
2. The tool (this repository's fss_blender_tools, the deployed copy purged): Refresh, then Bake Selected (TARGET) in
   the second Blender, hidden, 64 samples, AO distance 0.1 m, 12 threads.
3. Per layout (bake_layouts.make_layouts, the crops of Session 11): the layout as a UV map of TARGET (shifted and
   scaled to its crop), made active; Apply into a separate greyscale file at the crop's size (the `size` override of
   ao_bake_apply.Target), padding 8.
4. The applied image against FAIR (`<k>_fair.npy`) on the pixels where Session 14 measured (`<k>_inside.npy` and FAIR
   defined): inside MAE and maximum, next to Session 14's 4 x copy (`s14_fair.json`), and against Session 11's copy
   image of the same layout. The master against Session 11's 4 x master.
Writes s17_<tag>.json and s17_<tag>.log.txt into tests/_work/ao_bake/s17/.
"""
import json
import os
import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import addon_utils
import bpy
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = Path(HERE).parents[1]
sys.path.insert(0, HERE)
import bake_common as bc  # noqa: E402
import bake_geom as bg  # noqa: E402
import bake_layouts as bl  # noqa: E402

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
from fss_blender_tools import ao_bake_apply, ao_bake_core as core, ao_bake_store as store  # noqa: E402

addon_utils.enable('fss_blender_tools', default_set=True)
assert Path(sys.modules['fss_blender_tools'].__file__).resolve().is_relative_to(REPO)

args = dict(a.split('=', 1) for a in (sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []))
tag = args.get('tag', 'panel')
LAYOUTS = args.get('layouts', 'abdf')
SUF = '_s11x4'
PAD = 8
TILE = int(args.get('tile', 0))
if args.get('seed_offset'):
    os.environ['FSS_AO_BAKE_SEED_OFFSET'] = args['seed_offset']  # the second Blender inherits it (a control bake)
OUT = os.path.join(bc.WORK, args.get('sub', 's17'))
os.makedirs(OUT, exist_ok=True)
LOG = os.path.join(OUT, f's17_{tag}.log.txt')
if os.path.exists(LOG):
    os.remove(LOG)
L11 = os.path.join(bc.WORK, 'layouts', tag + SUF)
t_all = time.time()

# 1. the .blend
target, info = bc.load_scene(tag)
S = int(info['texture_size'])
mat = bpy.data.materials.new(f'S17_{tag.upper()}')
mat.fss_uv_texture_size = str(S)
target.data.materials.append(mat)
target.data.uv_layers.active = target.data.uv_layers[info['uv']]
scene = bpy.context.scene
s = scene.fss_ao_bake
s.distance, s.samples, s.threads, s.padding, s.device = 0.1, 64, 12, PAD, 'CPU'
s.output_folder = os.path.join(OUT, f'{tag}_ao')
blend = os.path.join(OUT, f'{tag}.blend')
folder = store.bake_folder(blend)
for p in (folder, s.output_folder):
    if os.path.isdir(p):
        shutil.rmtree(p)
bpy.ops.wm.save_as_mainfile(filepath=blend)
for o in bpy.context.view_layer.objects:
    o.select_set(o == target)
bpy.context.view_layer.objects.active = target

# 2. Refresh and Bake Selected
bpy.ops.fss.ao_bake_refresh()
item = store._state['items'][store._state['by_object'][target.name]]
bc.log(f"{tag}: {len(store._state['items'])} items, TARGET with {len(item['occluders'])} occluders "
       f"(prototype {info['n_occluders']}), uv {item['uv']}, texture {S}", LOG)
t = time.time()
assert bpy.ops.fss.ao_bake_start(scope='SELECTED', hidden=True, wait=True, tile=TILE) == {'FINISHED'}
t_bake_run = time.time() - t
status = store.read_status(folder)
entry = store.read_index(folder, use_cache=False)['masters'][item['key']]
bc.log(f"  bake: {status['state']} {status['n_done']} of {status['n_total']}, second Blender {t_bake_run:.1f} s; "
       f"master {entry['W']} x {entry['H']} at {entry['density']:.1f} px/m, times {entry['times']}", LOG)
master = core.load_master(folder, item['key'])
master['image'] = master['image'] / 65535.0  # the tool's master is uint16 (Session 20)
proto = np.load(os.path.join(bc.WORK, 'master', f'master_{tag}{SUF}.npz'))
proto_img = bc.read_png16(os.path.join(bc.WORK, 'master', f'master_{tag}{SUF}.png'))
same_layout = bool(proto_img.shape == master['image'].shape and np.allclose(proto['muv'], master['muv'], atol=1e-6))
both = proto['filled'] & master['filled'] if same_layout else None
master_cmp = dict(same_shape=proto_img.shape == master['image'].shape, same_layout=same_layout,
                  proto_density=float(proto['density']), density=master['density'])
if same_layout:
    d = np.abs(master['image'] - proto_img)[both]
    master_cmp.update(mae=float(d.mean()), max=float(d.max()), px=int(both.sum()))
bc.log(f'  master against Session 11: {master_cmp}', LOG)

# 3. and 4. Apply per layout, measured
with open(os.path.join(L11, 's14_fair.json')) as f:
    s14 = json.load(f)
with open(os.path.join(L11, 'results.json')) as f:
    res11 = json.load(f)
pos, tris, cn, uvs = bc.mesh_arrays(target.data)
wt = bg.weld_ids(pos)[tris]
layouts, _ = bl.make_layouts(target, pos, tris, wt, uvs[info['uv']], S, PAD, LAYOUTS)
rows = {}
for key, (uvpx, size, _tisl) in layouts.items():
    crop = bg.crop_box(uvpx, PAD + 4)
    assert list(crop) == list(res11['layouts'][key]['crop']), (key, crop)
    x0, y0, w, h = crop
    name = f'S17_{key}'
    bc.set_uv(target.data, name, (uvpx - np.array([x0, y0])) / np.array([w, h]))
    target.data.uv_layers.active = target.data.uv_layers[name]
    bpy.ops.fss.ao_bake_refresh()
    it = store._state['items'][item['key']]
    assert it['grade'] == 'UP_TO_DATE', it['grade']
    settings = SimpleNamespace(target='FILE', file_name=f'{tag}_{key}.png', resolution='ORM', layout='GREY',
                               green_blue='WHITE', sampling='AUTOMATIC', size=(w, h))
    rep = ao_bake_apply.apply_set(bpy.context, mat, None, settings)
    assert not rep.get('error'), rep
    vals, bits, _ct = core.read_png(rep['path'])
    img = vals[:, :, 0].astype(np.float64) / 65535.0
    fair = np.load(os.path.join(L11, f'{key}_fair.npy')).astype(np.float64)
    ins = np.load(os.path.join(L11, f'{key}_inside.npy'))
    insf = ins & np.isfinite(fair)
    d = np.abs(img - np.where(np.isfinite(fair), fair, 0.0))[insf]
    c11 = bc.read_png16(os.path.join(L11, f'{key}_copy.png'))
    dc = np.abs(img - c11)[ins]
    ref = s14['layouts'][key]['vs_fair']['copy']['inside']
    mae, mx = float(d.mean()), float(d.max())
    tol_mae = max(0.1 * ref['mae'], 0.002)
    tol_max = max(0.1 * ref['max'], 0.002)
    row = dict(crop=crop, px=int(insf.sum()), mae=mae, max=mx, s14_mae=ref['mae'], s14_max=ref['max'],
               tol_mae=tol_mae, tol_max=tol_max, met=bool(abs(mae - ref['mae']) <= tol_mae
                                                         and abs(mx - ref['max']) <= tol_max),
               vs_s11_copy=dict(mae=float(dc.mean()), max=float(dc.max()), px=int(ins.sum())),
               apply_s=rep['seconds'], copied=rep['copied'], white=rep['white'], faces_under_4x=rep['faces_under_4x'],
               faces=rep['faces'], stacked_px=rep['stacked_px'])
    rows[key] = row
    bc.log(f"  {key}: crop {w}x{h}; vs FAIR MAE {mae:.4f} (S14 {ref['mae']:.4f}) max {mx:.3f} (S14 {ref['max']:.3f}) "
           f"-> {'MET' if row['met'] else 'NOT MET'}; vs S11 copy MAE {dc.mean():.5f} max {dc.max():.4f}; "
           f"Apply {rep['seconds']} s; faces under 4 x {rep['faces_under_4x']} of {rep['faces']}", LOG)
    target.data.uv_layers.active = target.data.uv_layers[info['uv']]
out = dict(tag=tag, texture=S, tile=TILE, status=dict(state=status['state'], n_done=status['n_done'], n_total=status['n_total']),
           bake_run_s=round(t_bake_run, 2), entry=entry, master_vs_s11=master_cmp, layouts=rows,
           total_s=round(time.time() - t_all, 1))
with open(os.path.join(OUT, f's17_{tag}.json'), 'w') as f:
    json.dump(out, f, indent=1)
bc.log(f'done in {out["total_s"]} s', LOG)
