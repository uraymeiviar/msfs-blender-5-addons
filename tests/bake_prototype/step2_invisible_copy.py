"""Bake prototype, step 2: does a coincident, ray-invisible copy bake the same AO as the object itself?

Run (CPU wrapper, no blend file):
    blender -b --factory-startup --python step2_invisible_copy.py -- tag=panel size=1024 samples=64

Bakes into layout (a) of the target (its material's UV map at texture size `size`, cropped), margin 0:
- D1, D2: the target itself, seeds 1 and 2 (the noise of two direct bakes);
- copy variants, all with seed 3, a coincident copy (same mesh and split normals), target left visible:
  - all_off: every ray visibility off (Cycles drops an object without any visibility);
  - camera_only: every ray visibility off except camera (the copy is invisible to AO and shadow rays);
  - camera_only_offset_<d>: as camera_only, the copy moved d metres along its vertex normals;
  - s2a: the copy with every ray visibility off, baked Selected to Active from the target (the AO is evaluated on
    the target's own triangle at the copy's point);
- an anti-aliasing check: EMIT bake of a sharp step in object X with 1 and `samples` samples.
Writes step2_<tag>_<size>.json and PNGs in tests/_work/ao_bake/step2/.
"""
import json
import os
import sys
import time

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bake_common as bc  # noqa: E402
import bake_geom as bg  # noqa: E402

args = dict(a.split('=', 1) for a in (sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []))
tag = args.get('tag', 'panel')
S = int(args.get('size', 128))
N = int(args.get('samples', 16))
OUT = os.path.join(bc.WORK, 'step2')
os.makedirs(OUT, exist_ok=True)
LOG = os.path.join(OUT, f'step2_{tag}_{S}.log.txt')
t_start = time.time()

target, info = bc.load_scene(tag)
pos, tris, cn, uvs = bc.mesh_arrays(target.data)
uv_px = uvs[info['uv']] * S
x0, y0, w, h = bg.crop_box(uv_px, 4)
bake_uv = (uv_px - np.array([x0, y0])) / np.array([w, h])
bc.set_uv(target.data, 'BAKE_UV', bake_uv)
bc.log(f'{tag}: {info["target"]}, {len(tris)} tris, crop {w}x{h} at ({x0},{y0}) of {S}, samples {N}', LOG)
res = dict(tag=tag, target=info['target'], size=S, samples=N, crop=[x0, y0, w, h], times={}, variants={})
images = {}


def bake_into(obj, name, seed, **kw):
    img = bc.new_float_image(name, w, h)
    t = bc.bake(obj, img, 'BAKE_UV', N, seed, margin=0, **kw)
    a = bc.image_to_array(img)
    res['times'][name] = round(t, 2)
    bpy.data.images.remove(img)
    images[name] = a
    return a


D1 = bake_into(target, 'D1', 1)
D2 = bake_into(target, 'D2', 2)
mask = (D1 >= 0) & (D2 >= 0)
res['pixels'] = int(mask.sum())


def stats(a, b):
    m = mask & (a >= 0) & (b >= 0)
    d = (a - b)[m]
    return dict(mean_abs=float(np.mean(np.abs(d))), rms=float(np.sqrt(np.mean(d * d))), bias=float(np.mean(d)),
                p99=float(np.percentile(np.abs(d), 99)), max=float(np.max(np.abs(d))), pixels=int(m.sum()),
                missing=int((mask & (a < 0)).sum()))


ref = stats(D1, D2)
res['seed_noise_D1_D2'] = ref
bc.log(f'  direct D1 vs D2 (noise)       mean|d| {ref["mean_abs"]:.4f} rms {ref["rms"]:.4f} bias {ref["bias"]:+.4f}', LOG)


def variant(vname, a):
    s1, s2 = stats(a, D1), stats(a, D2)
    met = all(s['mean_abs'] <= 1.1 * ref['mean_abs'] and s['rms'] <= 1.1 * ref['rms']
              and abs(s['bias']) <= 0.1 * ref['mean_abs'] and s['missing'] == 0 for s in (s1, s2))
    res['variants'][vname] = dict(vs_D1=s1, vs_D2=s2, met=met, mean=float(a[mask & (a >= 0)].mean()))
    bc.log(f'  {vname:30s} mean|d| {s1["mean_abs"]:.4f}/{s2["mean_abs"]:.4f} rms {s1["rms"]:.4f}/{s2["rms"]:.4f} '
           f'bias {s1["bias"]:+.4f} missing {s1["missing"]} -> {"MET" if met else "NOT MET"}', LOG)


copy = target.copy()
copy.data = target.data.copy()
copy.name = 'COPY'
bpy.context.scene.collection.objects.link(copy)

bc.set_ray_invisible(copy)
variant('all_off', bake_into(copy, 'all_off', 3))
bc.set_ray_invisible(copy, keep_camera=True)
variant('camera_only', bake_into(copy, 'camera_only', 3))

me = copy.data
vn = np.zeros((len(me.vertices), 3))
np.add.at(vn, tris.ravel(), cn.reshape(-1, 3))
vn /= np.maximum(np.linalg.norm(vn, axis=1, keepdims=True), 1e-12)
for off in (1e-6, 1e-5, 1e-4):
    me.vertices.foreach_set('co', (pos + vn * off).astype(np.float32).ravel())
    me.update()
    me.normals_split_custom_set(cn.reshape(-1, 3).tolist())
    me.update()
    variant(f'camera_only_offset_{off:g}', bake_into(copy, f'offset_{off:g}', 3))
me.vertices.foreach_set('co', pos.astype(np.float32).ravel())
me.update()
me.normals_split_custom_set(cn.reshape(-1, 3).tolist())
me.update()

bc.set_ray_invisible(copy)
variant('s2a', bake_into(copy, 's2a', 3, from_objects=[target]))
res['criterion'] = ('a variant is MET when, against D1 and against D2, its mean|d| and RMS are <= 1.1x those of D1 vs '
                    'D2, its |bias| <= 0.1x the D1-vs-D2 mean|d|, and no pixel is missing')

for name, a in images.items():
    bc.write_png(os.path.join(OUT, f'{tag}_{S}_{name}.png'), np.where(a >= 0, a, 0.0))
for name in ('camera_only', 's2a', 'D2'):
    bc.write_png(os.path.join(OUT, f'{tag}_{S}_diff_{name}_D1_x4.png'),
                 np.where(mask, np.abs(images[name] - D1) * 4, 0), bits=8)

# anti-aliasing check: emission = step(x - x_c) in object space (a sharp edge across the object)
mat = bpy.data.materials.new('AA_STEP')
nt = mat.node_tree
for n in list(nt.nodes):
    nt.nodes.remove(n)
out = nt.nodes.new('ShaderNodeOutputMaterial')
em = nt.nodes.new('ShaderNodeEmission')
geo = nt.nodes.new('ShaderNodeNewGeometry')
sep = nt.nodes.new('ShaderNodeSeparateXYZ')
cmp_ = nt.nodes.new('ShaderNodeMath')
cmp_.operation = 'GREATER_THAN'
cmp_.inputs[1].default_value = float(np.median(pos[:, 0])) + 0.000123
nt.links.new(geo.outputs['Position'], sep.inputs[0])
nt.links.new(sep.outputs['X'], cmp_.inputs[0])
nt.links.new(cmp_.outputs[0], em.inputs['Color'])
nt.links.new(em.outputs[0], out.inputs['Surface'])
bc.set_ray_invisible(copy)
for samples in (1, N):
    img = bc.new_float_image(f'AA_{samples}', w, h)
    tex = nt.nodes.new('ShaderNodeTexImage')
    tex.image = img
    nt.nodes.active = tex
    target.data.materials.clear()
    target.data.materials.append(mat)
    target.data.uv_layers.active = target.data.uv_layers['BAKE_UV']
    bc.setup_cycles(bpy.context.scene, samples, 1)
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    bpy.ops.object.bake(type='EMIT', margin=0, use_clear=False, use_selected_to_active=False)
    a = bc.image_to_array(img)
    m = a >= 0
    frac = m & (a > 0.02) & (a < 0.98)
    res[f'aa_{samples}_samples'] = dict(baked=int(m.sum()), fractional=int(frac.sum()),
                                        values=sorted(set(np.round(a[frac], 3).tolist()))[:12])
    bc.log(f'  AA check {samples} samples: {int(frac.sum())} of {int(m.sum())} pixels between 0 and 1', LOG)
    nt.nodes.remove(tex)
    bpy.data.images.remove(img)
res['anti_aliased'] = res[f'aa_{N}_samples']['fractional'] > 0 and res['aa_1_samples']['fractional'] == 0
res['total_s'] = round(time.time() - t_start, 1)
with open(os.path.join(OUT, f'step2_{tag}_{S}.json'), 'w') as f:
    json.dump(res, f, indent=1)
bc.log(f'anti-aliased: {res["anti_aliased"]}; done in {res["total_s"]} s; bake times {res["times"]}', LOG)
