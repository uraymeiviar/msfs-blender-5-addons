"""Session 17, finish line 8: the second Blender started with its window (not hidden), for a screenshot.

Run (CPU cap; the second Blender inherits it) after s17_round_trip.py tag=panel:
    blender -b --factory-startup --python s17_visible.py -- count=4

Opens tests/_work/ao_bake/s17/panel.blend, selects the TARGET and the first `count` - 1 occluders by name, and runs
the tool's Bake Selected with the window shown, waiting until the second Blender quits. Prints the status at the end.
The screenshot is taken from outside (PowerShell) while it runs.
"""
import os
import sys
from pathlib import Path

import addon_utils
import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = Path(HERE).parents[1]
for mod in list(sys.modules.keys()):
    if mod == 'fss_blender_tools' or mod.startswith('fss_blender_tools.'):
        del sys.modules[mod]
while str(REPO) in sys.path:
    sys.path.remove(str(REPO))
sys.path.insert(0, str(REPO))
import fss_blender_tools  # noqa: E402,F401
from fss_blender_tools import ao_bake_store as store  # noqa: E402

args = dict(a.split('=', 1) for a in (sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []))
count = int(args.get('count', 4))
bpy.ops.wm.open_mainfile(filepath=str(REPO / 'tests' / '_work' / 'ao_bake' / 's17' / 'panel.blend'))
addon_utils.enable('fss_blender_tools', default_set=True)
assert Path(sys.modules['fss_blender_tools'].__file__).resolve().is_relative_to(REPO)
names = [o.name for o in bpy.context.view_layer.objects if o.name.startswith('TARGET')]
names += sorted(o.name for o in bpy.context.view_layer.objects if o.name.startswith('OCC_'))[:count - 1]
for o in bpy.context.view_layer.objects:
    o.select_set(o.name in names)
assert bpy.ops.fss.ao_bake_start(scope='SELECTED', hidden=False, wait=True) == {'FINISHED'}
print('STATUS', store.read_status())
