"""Session 20, finish lines 1, 2 and 5 and decision 32: memory and time of the bake in tiles on a large master.

Run (CPU cap; the tool's second Blender inherits it), one bake per run:
    blender -b --factory-startup --python s20_floor.py -- obj=floor tex=4096 [tile=2048] [budget=4] [limit=8]

obj=floor: OCC_@MERGE_COCKPIT_SHELL_FLOOR in tests/_work/ao_bake/s20/floor_base.blend (a copy of the prototype's
panel scene), given a test material whose texture set size is `tex` (4096: a master of about 214 Mpx, 2048: about
54 Mpx); obj=cap: the cap's TARGET in tests/_work/ao_bake/s17/cap.blend as Session 17 set it up.
tile: force the tile size (0: the tool's choice); budget: the memory budget in GB (FSS_AO_BAKE_MEMORY_GB, inherited
by the second Blender; none: the machine's default). limit: a watchdog in GB: when the second Blender's working set
exceeds it, the `cancel` file is written (the bake stops at the next tile) and the run is reported as over the limit.

The second Blender reports its own peak working set (GetProcessMemoryInfo) in index.json; this script also polls the
second Blender's working set every 0.25 s (GetProcessMemoryInfo on its process handle) and reads its peak at the end.
Appends one JSON line per run to tests/_work/ao_bake/s20/memory_runs.jsonl.
"""
import ctypes
import json
import os
import shutil
import sys
import time
from ctypes import wintypes
from pathlib import Path

import addon_utils
import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = Path(HERE).parents[1]
for mod in list(sys.modules.keys()):
    if mod == 'fss_blender_tools' or mod.startswith('fss_blender_tools.'):
        del sys.modules[mod]
if addon_utils.check('fss_blender_tools')[1]:
    addon_utils.disable('fss_blender_tools')
while str(REPO) in sys.path:
    sys.path.remove(str(REPO))
sys.path.insert(0, str(REPO))
import fss_blender_tools  # noqa: E402,F401
from fss_blender_tools import ao_bake_store as store  # noqa: E402

args = dict(a.split('=', 1) for a in (sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []))
OBJ = args.get('obj', 'floor')
TEX = int(args.get('tex', 4096))
TILE = int(args.get('tile', 0))
BUDGET = args.get('budget')
LIMIT = float(args.get('limit', 8)) * 2 ** 30
WORK = REPO / 'tests' / '_work' / 'ao_bake' / 's20'
if BUDGET:
    os.environ['FSS_AO_BAKE_MEMORY_GB'] = BUDGET
else:
    os.environ.pop('FSS_AO_BAKE_MEMORY_GB', None)

if OBJ == 'floor':
    bpy.ops.wm.open_mainfile(filepath=str(WORK / 'floor_base.blend'))
    name = 'OCC_@MERGE_COCKPIT_SHELL_FLOOR'
    target = bpy.data.objects[name]
    mat = bpy.data.materials.new('S20_FLOOR')
    target.data.materials.clear()
    target.data.materials.append(mat)
    blend = WORK / 'floor' / f'floor_{TEX}.blend'
else:
    bpy.ops.wm.open_mainfile(filepath=str(REPO / 'tests' / '_work' / 'ao_bake' / 's17' / f'{OBJ}.blend'))
    target = next(o for o in bpy.data.objects if o.name.startswith('TARGET'))
    mat = target.material_slots[0].material
    blend = WORK / OBJ / f'{OBJ}.blend'
addon_utils.enable('fss_blender_tools', default_set=True)
assert Path(sys.modules['fss_blender_tools'].__file__).resolve().is_relative_to(REPO)
mat.fss_uv_texture_size = str(TEX)
s = bpy.context.scene.fss_ao_bake
s.distance, s.samples, s.threads, s.device = 0.1, 64, 12, 'CPU'
blend.parent.mkdir(parents=True, exist_ok=True)
folder = store.bake_folder(str(blend))
if os.path.isdir(folder):
    shutil.rmtree(folder)
bpy.ops.wm.save_as_mainfile(filepath=str(blend))
for o in bpy.context.view_layer.objects:
    o.select_set(o == target)
bpy.context.view_layer.objects.active = target

k32 = ctypes.windll.kernel32


class PMC(ctypes.Structure):
    _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD),
                ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t),
                ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t),
                ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t), ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t)]


k32.OpenProcess.restype = wintypes.HANDLE
k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]


def memory_of(handle):
    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    if handle and k32.K32GetProcessMemoryInfo(handle, ctypes.byref(pmc), pmc.cb):
        return pmc.WorkingSetSize, pmc.PeakWorkingSetSize
    return None, None


bpy.ops.fss.ao_bake_refresh()
t = time.time()
assert bpy.ops.fss.ao_bake_start(scope='SELECTED', hidden=True, wait=False, tile=TILE) == {'FINISHED'}
proc = store._run['proc']
handle = k32.OpenProcess(0x1000 | 0x0400 | 0x0010, False, proc.pid)  # query (limited) information, vm read
ws_max = 0
peak = 0
over = False
while proc.poll() is None:
    ws, pk = memory_of(handle)
    if ws:
        ws_max = max(ws_max, ws)
        peak = max(peak, pk)
        if ws > LIMIT and not over:
            over = True
            store.cancel()
            print(f'S20FLOOR over the limit: {ws / 2 ** 30:.2f} GB, cancel written', flush=True)
    time.sleep(0.25)
wall = time.time() - t
from fss_blender_tools import ao_bake  # noqa: E402
ao_bake.finish_bake()
status = store.read_status(folder) or {}
index = store.read_index(folder, use_cache=False)
item = store._state['items'][store._state['by_object'][target.name]]
entry = index['masters'].get(item['key'], {})
res = (status.get('results') or [{}])[0]
row = dict(obj=OBJ, tex=TEX, tile_forced=TILE, budget_arg=BUDGET, state=status.get('state'), result=res.get('status'),
           reason=res.get('reason'), W=entry.get('W'), H=entry.get('H'),
           mpx=round(entry['W'] * entry['H'] / 1e6, 1) if entry else None, tiles=entry.get('tiles'),
           times=entry.get('times'), second_blender_s=round(wall, 1), budget_gb=status.get('budget_gb'),
           polled_ws_max_gb=round(ws_max / 2 ** 30, 3), polled_peak_gb=round(peak / 2 ** 30, 3), over_limit=over,
           when=time.strftime('%Y-%m-%d %H:%M:%S'))
print('S20FLOOR', json.dumps(row), flush=True)
with open(WORK / 'memory_runs.jsonl', 'a', encoding='utf-8') as f:
    f.write(json.dumps(row) + '\n')
