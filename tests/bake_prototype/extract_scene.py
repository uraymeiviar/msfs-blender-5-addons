"""Bake prototype, step 1: extract each target object with its occluders into a small scene file.

Run (CPU wrapper) on the cockpit copy:
    blender -b --factory-startup tests/_work/ao_bake/COCKPIT.blend --python extract_scene.py -- \
        panel=INHIBIT_PANEL cap=auto knob=ROTARY_IESS_BARO

For each tag=name the script writes tests/_work/ao_bake/scene_<tag>.blend holding one collection BAKE_<tag>
(writing a whole scene crashes Blender 5.2.2 in libraries.write; bake_common.load_scene links the collection into
the empty factory scene) with:
- TARGET: the evaluated target mesh (modifiers applied, current pose), triangulated with Blender's own loop
  triangles, world space, moved so the target's bbox centre is at the origin, split normals kept as custom normals,
  all UV maps kept, no materials;
- OCC_*: every other visible mesh object whose world bbox is within the AO distance (0.1 m) of the target's bbox,
  evaluated and moved the same way, no materials.
Maintainer rules (bake_rules.py): objects with only decal/glass/invisible/occluder materials are neither target nor
occluder, and such faces are dropped from mixed objects; tags Skip-AO-Bake / No Texture exclude targets, Non-AO-Occluder
excludes occluders; animation (tag mark or an action/NLA/driver on the object or a parent) is recorded per object.
It also writes scene_<tag>.json (names, UV map, texture size, occluders, the shift). The cockpit copy is not saved.
"""
import faulthandler
import json
import os
import sys
import time

import bpy
import numpy as np
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bake_common as bc  # noqa: E402
import bake_rules as br  # noqa: E402

faulthandler.enable()
args = dict(a.split('=', 1) for a in (sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []))
LOG = os.path.join(bc.WORK, 'extract.log.txt')
t0 = time.time()
dg = bpy.context.evaluated_depsgraph_get()
shared = bpy.data.collections.get('INTERACTIONS_SHARED_MESH')
ref_names = {o.name for o in shared.all_objects} if shared else set()
vis = [o for o in bpy.context.view_layer.objects
       if o.type == 'MESH' and o.visible_get() and not o.hide_render and o.name not in ref_names]


def world_bbox(obj):
    pts = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    return (np.array([min(p[i] for p in pts) for i in range(3)]), np.array([max(p[i] for p in pts) for i in range(3)]))


boxes = {o.name: world_bbox(o) for o in vis}


def gap(a, b):
    return float(np.max(np.maximum(np.maximum(a[0] - b[1], b[0] - a[1]), 0.0)))


def texture_size(obj):
    best = 0
    for s in obj.material_slots:
        m = s.material
        if m and m.use_nodes:
            for n in m.node_tree.nodes:
                if n.type == 'TEX_IMAGE' and n.image and n.image.size[0] > 0:
                    best = max(best, n.image.size[0], n.image.size[1])
    return best or 4096, ('material image' if best else 'default 4096 (no image found in the material)')


def material_uv(obj):
    for s in obj.material_slots:
        m = s.material
        if m and m.use_nodes:
            for n in m.node_tree.nodes:
                if n.type == 'UVMAP' and n.uv_map:
                    return n.uv_map
    for uv in obj.data.uv_layers:
        if uv.active_render:
            return uv.name
    return obj.data.uv_layers[0].name


def skip_slots(obj):
    return {i for i, s in enumerate(obj.material_slots) if br.is_skip_material(s.material)}


def evaluated_world_mesh(obj, shift):
    import bmesh
    ev = obj.evaluated_get(dg)
    me = bpy.data.meshes.new_from_object(ev, preserve_all_data_layers=True, depsgraph=dg)
    skip = skip_slots(obj)
    dropped = 0
    if skip:
        bm = bmesh.new()
        bm.from_mesh(me)
        faces = [f for f in bm.faces if f.material_index in skip]
        dropped = len(faces)
        bmesh.ops.delete(bm, geom=faces, context='FACES')
        bm.to_mesh(me)
        bm.free()
    me.materials.clear()
    m = Matrix.Translation(Vector(-shift)) @ obj.matrix_world
    me.transform(m)
    return me, dropped


def triangulated_target(obj, shift):
    """Target mesh rebuilt from Blender's loop triangles; corner data (UVs, split normals) copied per corner."""
    ev = obj.evaluated_get(dg)
    src = ev.to_mesh(preserve_all_data_layers=True, depsgraph=dg)
    m = Matrix.Translation(Vector(-shift)) @ obj.matrix_world
    nm = m.to_3x3().inverted().transposed()
    src.calc_loop_triangles()
    nv = len(src.vertices)
    co = np.empty(nv * 3)
    src.vertices.foreach_get('co', co)
    co = co.reshape(-1, 3)
    M = np.array(m)
    co_w = co @ M[:3, :3].T + M[:3, 3]
    nt = len(src.loop_triangles)
    lt_loops = np.empty(nt * 3, dtype=np.int64)
    src.loop_triangles.foreach_get('loops', lt_loops)
    lt_verts = np.empty(nt * 3, dtype=np.int64)
    src.loop_triangles.foreach_get('vertices', lt_verts)
    lt_mat = np.empty(nt, dtype=np.int64)
    src.loop_triangles.foreach_get('material_index', lt_mat)
    keep = ~np.isin(lt_mat, list(skip_slots(obj)))
    dropped = int((~keep).sum())
    lt_loops = lt_loops.reshape(-1, 3)[keep].ravel()
    lt_verts = lt_verts.reshape(-1, 3)[keep].ravel()
    nt = int(keep.sum())
    cn = np.empty(len(src.loops) * 3)
    src.corner_normals.foreach_get('vector', cn)
    cn = cn.reshape(-1, 3) @ np.array(nm).T
    cn /= np.linalg.norm(cn, axis=1, keepdims=True)
    uvs = {}
    for uv in src.uv_layers:
        a = np.empty(len(src.loops) * 2)
        uv.uv.foreach_get('vector', a)
        uvs[uv.name] = a.reshape(-1, 2)
    me = bpy.data.meshes.new('TARGET')
    me.from_pydata(co_w.tolist(), [], lt_verts.reshape(-1, 3).tolist())
    me.update(calc_edges=True)
    if len(me.polygons) != nt:
        raise RuntimeError(f'from_pydata dropped faces: {len(me.polygons)} of {nt}')
    for name, a in uvs.items():
        layer = me.uv_layers.new(name=name)
        layer.uv.foreach_set('vector', a[lt_loops].astype(np.float32).ravel())
    me.shade_smooth()
    me.normals_split_custom_set(cn[lt_loops].tolist())
    me.update()
    # check: the stored corner normals equal the source split normals
    chk = np.empty(nt * 9)
    me.corner_normals.foreach_get('vector', chk)
    dots = np.sum(chk.reshape(-1, 3) * cn[lt_loops], axis=1)
    max_angle = float(np.degrees(np.arccos(np.clip(dots.min(), -1, 1))))
    ev.to_mesh_clear()
    return me, max_angle, dropped


# ---- maintainer rules over the whole visible scene (what each rule excludes) ----
scene0 = bpy.context.scene
marks = br.mark_tags(scene0)
tagged = [o for o in bpy.data.objects if br.get_tags(o)]
all_tags = sorted({t for o in tagged for t in br.get_tags(o)})
rule = {}
for o in vis:
    only_skip, any_skip, _ = br.material_flags(o)
    rule[o.name] = dict(skip_material_only=only_skip, skip_material_some=any_skip and not only_skip,
                        ao_baked=br.is_ao_baked(o, marks), ao_occluder=br.is_ao_occluder(o, marks),
                        animated_tag=br.is_marked_animated(o, marks), animated_by=br.animation_source(o),
                        tags=br.get_tags(o))
glob = dict(visible_mesh_objects=len(vis),
            skip_material_only=sum(r['skip_material_only'] for r in rule.values()),
            skip_material_some_faces=sum(r['skip_material_some'] for r in rule.values()),
            tag_not_baked=sum(not r['ao_baked'] for r in rule.values()),
            tag_not_occluder=sum(not r['ao_occluder'] for r in rule.values()),
            animated_tag=sum(r['animated_tag'] for r in rule.values()),
            animated_by_action=sum(r['animated_by'] is not None for r in rule.values()))
rules_out = dict(mark_tags=marks, objects_with_fss_tags=len(tagged), all_tags=all_tags, scene_counts=glob)
bc.log(f"scene mark tags: {marks}", LOG)
bc.log(f"objects with fss_tags: {len(tagged)}, tags: {all_tags}", LOG)
bc.log(f"visible-scene rule counts: {glob}", LOG)


def is_animated(name):
    r = rule[name]
    return r['animated_tag'] or r['animated_by'] is not None


summary = {}
for tag, name in args.items():
    if tag == 'cap' and name == 'auto':
        panel = bpy.data.objects[args['panel']]
        pb = boxes[panel.name]
        c = (pb[0] + pb[1]) / 2
        caps = [o for o in vis if o.data.name == 'MESH_SHARED_BTN_CAP' and gap(boxes[o.name], pb) < 0.002
                and rule[o.name]['ao_baked'] and not rule[o.name]['skip_material_only']]
        # prefer a static copy, then the one nearest the panel centre
        caps.sort(key=lambda o: (is_animated(o.name), np.linalg.norm(np.array(o.matrix_world.translation) - c), o.name))
        name = caps[0].name
    obj = bpy.data.objects[name]
    r = rule[obj.name]
    if r['skip_material_only'] or not r['ao_baked']:
        raise RuntimeError(f'{obj.name} may not be a bake target: {r}')
    tb = boxes[obj.name]
    shift = (tb[0] + tb[1]) / 2
    near = sorted(o.name for o in vis if o.name != obj.name and gap(boxes[o.name], tb) <= bc.AO_DISTANCE)
    ex_skip = [n for n in near if rule[n]['skip_material_only']]
    ex_tag = [n for n in near if not rule[n]['skip_material_only'] and not rule[n]['ao_occluder']]
    occ = [n for n in near if n not in ex_skip and n not in ex_tag]
    scene = bpy.data.collections.new(f'BAKE_{tag}')
    me, max_angle, t_dropped = triangulated_target(obj, shift)
    tobj = bpy.data.objects.new('TARGET', me)
    scene.objects.link(tobj)
    n_occ_tris = 0
    occ_dropped = {}
    for on in occ:
        o = bpy.data.objects[on]
        ome, dropped = evaluated_world_mesh(o, shift)
        if dropped:
            occ_dropped[on] = dropped
        n_occ_tris += sum(len(p.vertices) - 2 for p in ome.polygons)
        oo = bpy.data.objects.new('OCC_' + on, ome)
        scene.objects.link(oo)
    tex, tex_src = texture_size(obj)
    info = dict(tag=tag, target=obj.name, mesh=obj.data.name, uv=material_uv(obj), uv_maps=[u.name for u in obj.data.uv_layers],
                texture_size=tex, texture_size_source=tex_src, shift=shift.tolist(), occluders=occ,
                n_occluders=len(occ), n_occluder_tris=n_occ_tris, target_tris=len(me.polygons),
                target_faces_dropped_skip_material=t_dropped,
                target_rule=r, target_animated=is_animated(obj.name),
                candidates_within_ao_distance=len(near),
                excluded_skip_material_only=ex_skip, excluded_non_ao_occluder_tag=ex_tag,
                occluder_faces_dropped_skip_material=occ_dropped,
                occluder_tags={n: rule[n]['tags'] for n in occ if rule[n]['tags']},
                animated_occluders={n: rule[n]['animated_by'] or 'tag' for n in occ if is_animated(n)},
                local_axes_world=[list(obj.matrix_world.to_3x3().normalized().col[i]) for i in range(3)],
                normal_copy_max_angle_deg=max_angle, rules=rules_out,
                materials=[(s.material.name, br.material_type(s.material), br.is_skip_material(s.material))
                           if s.material else None for s in obj.material_slots])
    bc.log(f"{tag}: target animated={info['target_animated']} ({r['animated_by']}), tags {r['tags']}; "
           f"{len(near)} near, excluded {len(ex_skip)} skip-material-only, {len(ex_tag)} Non-AO-Occluder; "
           f"{len(info['animated_occluders'])} of {len(occ)} occluders animated; target faces dropped {t_dropped}; "
           f"occluders with dropped faces {len(occ_dropped)}", LOG)
    path = os.path.join(bc.WORK, f'scene_{tag}.blend')
    bpy.data.libraries.write(path, {scene}, fake_user=True, compress=False)  # the collection and its objects
    with open(os.path.join(bc.WORK, f'scene_{tag}.json'), 'w') as f:
        json.dump(info, f, indent=1)
    summary[tag] = info
    bc.log(f"{tag}: {obj.name} ({info['target_tris']} tris, uv {info['uv']}, tex {tex}), {len(occ)} occluders "
           f"({n_occ_tris} tris), normal copy max angle {max_angle:.4f} deg -> {path}", LOG)
bc.log(f"extract done in {time.time() - t0:.1f} s", LOG)
