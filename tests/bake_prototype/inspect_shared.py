"""Bake prototype, step 1a helper: list the shared interaction meshes and their users (read only)."""
import json
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bake_common as bc  # noqa: E402

coll = bpy.data.collections.get('INTERACTIONS_SHARED_MESH')
out = {}
if coll:
    for o in coll.all_objects:
        if o.type != 'MESH':
            continue
        users = [u for u in bpy.data.objects if u.data == o.data]
        out[o.name] = dict(mesh=o.data.name, users=len(users),
                           visible_users=[u.name for u in users if u.visible_get() and not u.hide_render][:400],
                           tris=sum(len(p.vertices) - 2 for p in o.data.polygons))
with open(os.path.join(bc.WORK, 'inspect_shared.json'), 'w') as f:
    json.dump(out, f, indent=1)
for k, v in sorted(out.items(), key=lambda kv: -kv[1]['users']):
    print(f"{k:32s} mesh={v['mesh']:32s} users={v['users']:4d} visible={len(v['visible_users']):4d} tris={v['tris']}")
