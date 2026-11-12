"""Bake prototype, step 1a helper: details of candidate panels and knobs (read only).

Args after --: object names. Prints collections, location, bbox, LOD-like neighbours and mesh traits.
"""
import os
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bake_common as bc  # noqa: E402

names = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
out_path = os.path.join(bc.WORK, 'inspect_panel.txt')
lines = []


def world_bbox(obj):
    pts = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


vis = [o for o in bpy.context.view_layer.objects if o.type == 'MESH' and o.visible_get() and not o.hide_render]
boxes = {o.name: world_bbox(o) for o in vis}
top = [c.name for c in bpy.context.scene.collection.children]
lines.append(f"top collections: {top}")
for name in names:
    o = bpy.data.objects.get(name)
    if o is None:
        lines.append(f"{name}: missing")
        continue
    lo, hi = world_bbox(o)
    lines.append(f"== {name} mesh={o.data.name} colls={[c.name for c in o.users_collection]} "
                 f"parent={o.parent.name if o.parent else None} loc={tuple(round(v, 4) for v in o.matrix_world.translation)}")
    lines.append(f"   bbox lo={tuple(round(v, 4) for v in lo)} hi={tuple(round(v, 4) for v in hi)} "
                 f"scale={tuple(round(v, 4) for v in o.matrix_world.to_scale())}")
    me = o.data
    sharp = me.attributes.get('sharp_edge')
    sharp_face = me.attributes.get('sharp_face')
    n_sharp = sum(1 for d in sharp.data if d.value) if sharp else 0
    n_flat = sum(1 for d in sharp_face.data if d.value) if sharp_face else 0
    lines.append(f"   polys={len(me.polygons)} verts={len(me.vertices)} sharp_edges={n_sharp} flat_faces={n_flat} "
                 f"custom_normals={me.has_custom_normals} attrs={[a.name for a in me.attributes]}")
    lines.append(f"   modifiers={[(m.type, m.name) for m in o.modifiers]}")
    for s in o.material_slots:
        if s.material and s.material.use_nodes:
            imgs = [(n.image.name, tuple(n.image.size), n.image.filepath) for n in s.material.node_tree.nodes
                    if n.type == 'TEX_IMAGE' and n.image]
            uvn = [n.uv_map for n in s.material.node_tree.nodes if n.type == 'UVMAP']
            lines.append(f"   mat {s.material.name}: uvmap nodes={uvn} images={imgs[:6]}")
    near = []
    for n2, (l2, h2) in boxes.items():
        if n2 == name:
            continue
        gap = max(max(l2[i] - hi[i], lo[i] - h2[i], 0.0) for i in range(3))
        if gap <= bc.AO_DISTANCE:
            near.append(n2)
    lines.append(f"   objects within {bc.AO_DISTANCE} m (bbox): {len(near)}")
    same = [n2 for n2 in near if (boxes[n2][0] - lo).length < 0.003 and (boxes[n2][1] - hi).length < 0.003]
    lines.append(f"   objects with nearly the same bbox: {same}")
    lines.append(f"   near sample: {sorted(near)[:60]}")
with open(out_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines) + '\n')
print('\n'.join(lines))
