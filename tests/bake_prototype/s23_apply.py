"""Session 23, finish line 3: Apply paged. The floor's master baked by s20_floor.py (tests/_work/ao_bake/<sub>/floor/
floor_<tex>.blend and its .bake folder) applied into a separate greyscale file of `res` px, with this Blender's
working set before Apply and its peak during Apply.

Run (CPU cap), after s20_floor.py -- obj=floor tex=8192 samples=1 sub=s23:
    blender -b --factory-startup --python s23_apply.py -- [tex=8192] [res=8192] [sub=s23] [band=256] [limit=8]

The peak is read in two ways: this process's PeakWorkingSetSize (GetProcessMemoryInfo) before and after Apply, and a
thread polling the working set every 0.2 s during Apply. limit: a watchdog in GB above the working set before Apply;
when the polled working set exceeds it, the process exits at once (os._exit) and the run is reported as over the
limit. Appends one JSON line to tests/_work/ao_bake/<sub>/apply_runs.jsonl.
"""
import ctypes
import json
import os
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path
from types import SimpleNamespace

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

args = dict(a.split('=', 1) for a in (sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []))
TEX = int(args.get('tex', 8192))
RES = args.get('res', '8192')
BAND = int(args.get('band', 256))
LIMIT = float(args.get('limit', 8)) * 2 ** 30
WORK = REPO / 'tests' / '_work' / 'ao_bake' / args.get('sub', 's23')
blend = WORK / 'floor' / f'floor_{TEX}.blend'
bpy.ops.wm.open_mainfile(filepath=str(blend))
addon_utils.enable('fss_blender_tools', default_set=True)
assert Path(sys.modules['fss_blender_tools'].__file__).resolve().is_relative_to(REPO)
from fss_blender_tools import ao_bake_apply, ao_bake_store as store  # noqa: E402

k32 = ctypes.windll.kernel32


class PMC(ctypes.Structure):
    _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD),
                ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t),
                ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t),
                ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t), ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t)]


k32.GetCurrentProcess.restype = wintypes.HANDLE
k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]


def memory():
    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
    return pmc.WorkingSetSize, pmc.PeakWorkingSetSize


bpy.ops.fss.ao_bake_refresh()
target = bpy.data.objects['OCC_@MERGE_COCKPIT_SHELL_FLOOR']
mat = target.material_slots[0].material
item = store._state['items'][store._state['by_object'][target.name]]
assert item['grade'] == 'UP_TO_DATE', item['grade']
entry = store.read_index(store.bake_folder(), use_cache=False)['masters'][item['key']]
bpy.context.scene.fss_ao_bake.output_folder = str(WORK / 'floor' / 'apply_out')
settings = SimpleNamespace(target='FILE', file_name=f'floor_{TEX}_ao_{RES}.png', resolution=RES, layout='GREY',
                           green_blue='WHITE', sampling='AUTOMATIC')
ws0, peak0 = memory()
poll = dict(max=ws0, run=True)
gb = 2 ** 30


def watch():
    while poll['run']:
        ws, _pk = memory()
        poll['max'] = max(poll['max'], ws)
        if ws - ws0 > LIMIT:
            print(f'S23APPLY over the limit: {ws / gb:.2f} GB, {(ws - ws0) / gb:.2f} GB above the start; exiting',
                  flush=True)
            os._exit(3)
        time.sleep(0.2)


th = threading.Thread(target=watch, daemon=True)
th.start()
t = time.time()
rep = ao_bake_apply.apply_set(bpy.context, mat, None, settings, band_rows=BAND)
dt = time.time() - t
poll['run'] = False
th.join()
ws1, peak1 = memory()
assert not rep.get('error'), rep
folder = store.bake_folder()
left = [f for f in os.listdir(folder) if f.endswith('.page') or f.endswith('.mappage')]
row = dict(tex=TEX, res=RES, band=BAND, master=[entry['W'], entry['H']], master_mpx=round(entry['W'] * entry['H'] / 1e6, 1),
           samples=entry['samples'], seconds=round(dt, 1), written_px=rep['written_px'], copied=rep['copied'],
           white=rep['white'], faces=rep['faces'], faces_under_4x=rep['faces_under_4x'],
           page_loads=rep.get('page_loads'), ws_before_gb=round(ws0 / gb, 3), peak_before_gb=round(peak0 / gb, 3),
           peak_after_gb=round(peak1 / gb, 3), polled_max_gb=round(poll['max'] / gb, 3),
           peak_above_before_gb=round((peak1 - ws0) / gb, 3), ws_after_gb=round(ws1 / gb, 3),
           scratch_left=left, file=rep['path'], file_mb=round(os.path.getsize(rep['path']) / 2 ** 20, 1),
           when=time.strftime('%Y-%m-%d %H:%M:%S'))
print('S23APPLY', json.dumps(row), flush=True)
with open(WORK / 'apply_runs.jsonl', 'a', encoding='utf-8') as f:
    f.write(json.dumps(row) + '\n')
