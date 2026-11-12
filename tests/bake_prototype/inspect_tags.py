"""Bake prototype, rules check: print every stored fss_ property of each scene (read only), to verify tag reading."""
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bake_common as bc  # noqa: E402
import bake_rules as br  # noqa: E402

lines = []
for sc in bpy.data.scenes:
    sp = sc.bl_system_properties_get()
    keys = sorted(k for k in (sp.keys() if sp else []) if k.startswith('fss'))
    lines.append(f'scene {sc.name}: system fss keys {len(keys)}')
    for k in keys:
        v = sp[k]
        try:
            v = v.to_dict()
        except Exception:
            pass
        lines.append(f'   {k} = {str(v)[:200]!r}')
    lines.append(f'   id-prop fss keys: {[k for k in sc.keys() if k.startswith("fss")]}')
    lines.append(f'   mark tags read: {br.mark_tags(sc)}')
counts = {}
for o in bpy.data.objects:
    for t in br.get_tags(o):
        counts[t] = counts.get(t, 0) + 1
lines.append(f'object tag counts: {counts}')
with open(os.path.join(bc.WORK, 'inspect_tags.txt'), 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines) + '\n')
print('\n'.join(lines))
