"""Bake prototype, step 1a helper: custom and system properties of objects and their materials (read only)."""
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bake_common as bc  # noqa: E402

names = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
lines = []


def props(idb):
    out = {}
    try:
        for k in idb.keys():
            out[k] = str(idb[k])[:80]
    except Exception:
        pass
    try:
        sp = idb.bl_system_properties_get()
        if sp:
            for k in sp.keys():
                v = sp[k]
                try:
                    v = v.to_dict()
                except Exception:
                    pass
                out['sys:' + k] = str(v)[:300]
    except Exception as e:
        out['sys_err'] = str(e)
    return out


for name in names:
    o = bpy.data.objects.get(name)
    if not o:
        lines.append(f'{name}: missing')
        continue
    lines.append(f'== {name}: {props(o)}')
    for s in o.material_slots:
        if s.material:
            lines.append(f'   mat {s.material.name}: {props(s.material)}')
imgs = sorted((i.name, tuple(i.size), i.filepath) for i in bpy.data.images)
lines.append(f'images ({len(imgs)}):')
for i in imgs:
    if any(k in i[0].upper() for k in ('PEDESTAL', 'INTERACTION', 'COCKPIT_FRONT')):
        lines.append(f'   {i}')
with open(os.path.join(bc.WORK, 'inspect_props.txt'), 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines) + '\n')
print('\n'.join(lines))
