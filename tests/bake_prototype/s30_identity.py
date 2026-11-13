"""Session 29, finish line 3: a bake at 1 pose with the Scene rule gives the masters of 0.57.0, pixel for pixel.

Run (CPU cap; the tool's second Blender inherits it), once with the code before the change and once after:
    blender -b --factory-startup --python s30_identity.py -- src=<suite.blend> out=<folder> [poses=1]

Copies src into out (the copy is the file baked; src is not touched), sets the scene's pose count when the add-on has
one (0.58.0), bakes every master (Bake Missing and Stale, hidden) and writes out/identity.json: per master the
SHA-256 of its decoded pixels (uint16, row order of the file), of its .ao.map, its size and its image format.
Compare two runs with `s30_identity.py -- compare=<a>/identity.json,<b>/identity.json`.
"""
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

args = dict(a.split('=', 1) for a in (sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []))

if 'compare' in args:
    a, b = (json.load(open(p, encoding='utf-8')) for p in args['compare'].split(','))
    same_px = [k for k in a if k in b and a[k]['pixels'] == b[k]['pixels']]
    same_map = [k for k in a if k in b and a[k]['map'] == b[k]['map']]
    diff = sorted(set(a) ^ set(b)) + sorted(k for k in a if k in b and a[k]['pixels'] != b[k]['pixels'])
    print(json.dumps(dict(masters_a=len(a), masters_b=len(b), pixels_identical=len(same_px), maps_identical=len(same_map),
                          different=diff), indent=1))
    sys.exit(0)

import addon_utils  # noqa: E402
import bpy  # noqa: E402

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

out = args['out']
os.makedirs(out, exist_ok=True)
blend = os.path.join(out, 'suite.blend')
shutil.copyfile(args['src'], blend)
folder = store.bake_folder(blend)
if os.path.isdir(folder):
    shutil.rmtree(folder)
bpy.ops.wm.open_mainfile(filepath=blend)
s = bpy.context.scene.fss_ao_bake
if hasattr(s, 'poses'):
    s.poses = int(args.get('poses', 1))
    bpy.ops.wm.save_mainfile()
print('version', fss_blender_tools.bl_info['version'], 'poses', getattr(s, 'poses', None))
bpy.ops.fss.ao_bake_refresh()
assert bpy.ops.fss.ao_bake_start(scope='STALE', hidden=True, wait=True) == {'FINISHED'}
status = store.read_status(folder)
assert status['state'] == 'done', status
res = {}
for stem, entry in store.read_index(folder, use_cache=False)['masters'].items():
    image, mp, _npz = core.master_paths(folder, stem)
    px = core.read_image(image)
    res[entry['name']] = dict(stem=stem, pixels=hashlib.sha256(px.tobytes()).hexdigest(),
                              map=hashlib.sha256(Path(mp).read_bytes()).hexdigest(), W=entry['W'], H=entry['H'],
                              format=os.path.splitext(image)[1], poses=entry.get('poses'))
with open(os.path.join(out, 'identity.json'), 'w', encoding='utf-8') as f:
    json.dump(res, f, indent=1)
print(f'identity: {len(res)} masters written to {out}')
