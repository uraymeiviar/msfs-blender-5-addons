"""Bake prototype check: is the master -> layout mapping right? (No AO, no noise.)

    blender -b --factory-startup --python check_mapping.py -- tag=panel layout=a size=4096 period=0.005

Bakes an emission that is a smooth function of the 3D position (no noise) into the master (built exactly as
step3_master.py does) and directly into layout (a); copies the master into the layout with bake_copy and compares.
A mapping bug (wrong face, offset, flip) shows as a large difference; a correct mapping leaves only the softening of
the second read. Writes tests/_work/ao_bake/check/<tag>_*.
"""
import json
import math
import os
import sys

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bake_common as bc  # noqa: E402
import bake_copy as bcp  # noqa: E402
import bake_geom as bg  # noqa: E402
import bake_unfold as bu  # noqa: E402

args = dict(a.split('=', 1) for a in (sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []))
tag = args.get('tag', 'panel')
period = float(args.get('period', 0.005))
order = args.get('order', 'growlen')
OUT = os.path.join(bc.WORK, 'check')
os.makedirs(OUT, exist_ok=True)
LOG = os.path.join(OUT, f'{tag}.log.txt')
target, info = bc.load_scene(tag)
S = int(args.get('size', info['texture_size']))
pos, tris, cn, uvs = bc.mesh_arrays(target.data)
a3 = bg.tri_areas_3d(pos, tris)
uv_px = uvs[info['uv']] * S
D = 2 * bg.weighted_median(bg.densities(pos, tris, uv_px)[a3 > 0], a3[a3 > 0])
m = bu.build_master(pos, tris, cn, D, order=order)


def emission_material(img=None):
    mat = bpy.data.materials.new('EMIT_POS')
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    em = nt.nodes.new('ShaderNodeEmission')
    geo = nt.nodes.new('ShaderNodeNewGeometry')
    dot = nt.nodes.new('ShaderNodeVectorMath')
    dot.operation = 'DOT_PRODUCT'
    d = np.array([0.8, 0.5, 0.33])
    dot.inputs[1].default_value = (d / np.linalg.norm(d) * 2 * math.pi / period).tolist()
    sin = nt.nodes.new('ShaderNodeMath')
    sin.operation = 'SINE'
    mul = nt.nodes.new('ShaderNodeMath')
    mul.operation = 'MULTIPLY_ADD'
    mul.inputs[1].default_value = 0.5
    mul.inputs[2].default_value = 0.5
    nt.links.new(geo.outputs['Position'], dot.inputs[0])
    nt.links.new(dot.outputs['Value'], sin.inputs[0])
    nt.links.new(sin.outputs[0], mul.inputs[0])
    nt.links.new(mul.outputs[0], em.inputs['Color'])
    nt.links.new(em.outputs[0], out.inputs['Surface'])
    if img is not None:
        tex = nt.nodes.new('ShaderNodeTexImage')
        tex.image = img
        nt.nodes.active = tex
    return mat


def run_bake(obj, img, uv_name, selected=None):
    obj.data.uv_layers.active = obj.data.uv_layers[uv_name]
    bc.setup_cycles(bpy.context.scene, 16, 1)
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in (selected or []):
        o.select_set(True)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    kw = dict(cage_extrusion=2e-5, max_ray_distance=4e-5, use_cage=False) if selected else {}
    bpy.ops.object.bake(type='EMIT', margin=0, use_clear=False, use_selected_to_active=bool(selected), **kw)


# target emits; the master core is baked selected-to-active from it
target.data.materials.clear()
target.data.materials.append(emission_material())
W, H = m['W'], m['H']
core = m['core_tris']
core_me = bc.build_mesh('MC', pos[tris[core]].reshape(-1, 3), np.arange(len(core) * 3).reshape(-1, 3), cn[core],
                        m['muv'][core] / np.array([W, H]))
core_obj = bpy.data.objects.new('MC', core_me)
bpy.context.scene.collection.objects.link(core_obj)
bc.set_ray_invisible(core_obj)
imgM = bc.new_float_image('M', W, H)
core_me.materials.append(bc.bake_material(imgM, 'MAT_M'))
run_bake(core_obj, imgM, 'BAKE_UV', selected=[target])
Mimg = bc.image_to_array(imgM)
filled = Mimg >= 0
idx = np.where(filled, np.arange(H * W).reshape(H, W), -1)
in_rect = np.zeros((H, W), dtype=bool)
rect_id = np.full((H, W), -1, dtype=np.int64)
for i, (x, y, w, h) in enumerate(m['rects']):
    in_rect[y:y + h, x:x + w] = True
    rect_id[y:y + h, x:x + w] = i
grown, _ = bg.dilate_ids(idx, 8, mask_allowed=in_rect)
fm = (~filled) & (grown >= 0)
Mf = Mimg.copy()
Mf[fm] = Mimg.ravel()[grown[fm]]
master = dict(muv=m['muv'], image=np.where(Mf >= 0, Mf, 0), rect_id=rect_id, filled=Mf >= 0, island=m['island'])

# direct emission bake into layout (a)
crop = bg.crop_box(uv_px, 12)
x0, y0, w, h = crop
bc.set_uv(target.data, 'BAKE_UV', (uv_px - np.array([x0, y0])) / np.array([w, h]))
imgD = bc.new_float_image('D', w, h)
target.data.materials.clear()
target.data.materials.append(emission_material(imgD))
run_bake(target, imgD, 'BAKE_UV')
Dimg = bc.image_to_array(imgD)
wt = bg.weld_ids(pos)[tris]
tisl = bg.uv_islands(wt, uvs[info['uv']])
copy, cinfo, owner_c, steps, count_c = bcp.copy_master(pos, tris, uv_px, tisl, master, crop, 2, 8)
inside = (owner_c >= 0) & (Dimg >= 0) & (copy >= 0)
d = (copy - Dimg)[inside]
res = dict(tag=tag, period=period, size=S, master=[W, H], mae=float(np.abs(d).mean()),
           p99=float(np.percentile(np.abs(d), 99)), max=float(np.abs(d).max()), px=int(inside.sum()),
           px_over_0_1=int((np.abs(d) > 0.1).sum()), copy_info=cinfo)
# per target triangle: the worst error, to locate mapping bugs
err_t = {}
jj, ii = np.nonzero(inside)
e = np.abs(copy - Dimg)[jj, ii]
for t_, e_ in zip(owner_c[jj, ii], e):
    err_t[int(t_)] = max(err_t.get(int(t_), 0.0), float(e_))
worst = sorted(err_t.items(), key=lambda kv: -kv[1])[:15]
res['worst_triangles'] = [(t_, round(v, 3), int(m['island'][t_]), float(a3[t_] * 1e6)) for t_, v in worst]
with open(os.path.join(OUT, f'{tag}.json'), 'w') as f:
    json.dump(res, f, indent=1)
bc.write_png(os.path.join(OUT, f'{tag}_direct.png'), np.clip(np.where(Dimg >= 0, Dimg, 0), 0, 1))
bc.write_png(os.path.join(OUT, f'{tag}_copy.png'), np.clip(np.where(copy >= 0, copy, 0), 0, 1))
bc.write_png(os.path.join(OUT, f'{tag}_diff_x4.png'), np.where(inside, np.abs(copy - Dimg) * 4, 0), bits=8)
bc.write_png(os.path.join(OUT, f'{tag}_master.png'), np.clip(np.where(Mf >= 0, Mf, 0), 0, 1))
bc.log(f'{tag}: emission mapping check MAE {res["mae"]:.4f} P99 {res["p99"]:.4f} max {res["max"]:.4f} '
       f'px>0.1 {res["px_over_0_1"]} of {res["px"]}; worst (tri, err, master island, area mm2) {res["worst_triangles"]}',
       LOG)
