"""Bake prototype, step 1a: list candidate objects in the cockpit copy (read only).

Run (CPU wrapper, see docs/journal/20261112.auto-bake-ao-curvature.md):
    blender -b --factory-startup tests/_work/ao_bake/COCKPIT.blend --python tests/bake_prototype/inspect_scene.py

Writes tests/_work/ao_bake/inspect.json and prints a summary. Saves nothing.
"""
import json
import os
import sys
import time

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bake_common as bc  # noqa: E402

t0 = time.time()
depsgraph = bpy.context.evaluated_depsgraph_get()


def world_bbox(obj):
    pts = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


meshes = [o for o in bpy.context.view_layer.objects if o.type == 'MESH']
visible = [o for o in meshes if o.visible_get() and not o.hide_render]
print(f"mesh objects in view layer: {len(meshes)}, visible: {len(visible)}")

boxes = {o.name: world_bbox(o) for o in visible}
users = {}
for o in visible:
    users.setdefault(o.data.name, []).append(o.name)

shared = bpy.data.collections.get('INTERACTIONS_SHARED_MESH')
ref_names = {o.name for o in shared.all_objects} if shared else set()
visible = [o for o in visible if o.name not in ref_names]
caps = [o for o in visible if o.data.name == 'MESH_SHARED_BTN_CAP']
bases = [o for o in visible if o.data.name == 'MESH_SHARED_BTN_BASE']
rot = [o for o in visible if any(k in o.data.name.upper() for k in ('ROTARY', 'KNOB'))]
print(f"BTN_CAP copies: {len(caps)}, BTN_BASE copies: {len(bases)}, rotary/knob copies: {len(rot)}")


def dist_boxes(a, b):
    d = 0.0
    for i in range(3):
        g = max(a[0][i] - b[1][i], b[0][i] - a[1][i], 0.0)
        d += g * g
    return d ** 0.5


# Panels: unique-mesh objects near BTN copies, thin in one axis.
btn = caps + bases
panel_cands = []
for o in visible:
    if len(users[o.data.name]) > 1 or o in btn:
        continue
    lo, hi = boxes[o.name]
    ext = sorted(hi - lo)
    if ext[2] > 0.6 or ext[2] < 0.03:
        continue
    near_caps = [c.name for c in caps if dist_boxes(boxes[c.name], (lo, hi)) < 0.002]
    near_bases = [c.name for c in bases if dist_boxes(boxes[c.name], (lo, hi)) < 0.002]
    if not near_caps and not near_bases:
        continue
    n_tris = sum(len(p.vertices) - 2 for p in o.data.polygons)
    panel_cands.append(dict(name=o.name, mesh=o.data.name, tris=n_tris,
                            extent=[round(e, 4) for e in ext], caps=len(near_caps), bases=len(near_bases),
                            mods=[m.type for m in o.modifiers], uv=[u.name for u in o.data.uv_layers],
                            mats=[s.material.name if s.material else None for s in o.material_slots]))
panel_cands.sort(key=lambda d: (d['extent'][2], d['tris']))

rot_info = []
for o in rot:
    rot_info.append(dict(name=o.name, mesh=o.data.name, tris=sum(len(p.vertices) - 2 for p in o.data.polygons),
                         polys=len(o.data.polygons), users=len(users[o.data.name]),
                         parent=o.parent.name if o.parent else None,
                         extent=[round(e, 4) for e in (boxes[o.name][1] - boxes[o.name][0])],
                         mods=[m.type for m in o.modifiers], uv=[u.name for u in o.data.uv_layers]))
cap_info = []
for o in caps[:200]:
    cap_info.append(dict(name=o.name, mesh=o.data.name, parent=o.parent.name if o.parent else None,
                         loc=[round(v, 4) for v in o.matrix_world.translation]))

out = dict(panels=panel_cands[:80], rotary=rot_info, caps=cap_info, time=time.time() - t0)
path = os.path.join(bc.WORK, 'inspect.json')
with open(path, 'w') as f:
    json.dump(out, f, indent=1)
print(f"panels: {len(panel_cands)}; wrote {path} in {time.time() - t0:.1f} s")
