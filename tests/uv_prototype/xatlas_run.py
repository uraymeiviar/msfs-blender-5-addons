# Round 2: run xatlas (default options, own packing) on the plain mesh and on the mesh split at proto2 forced cuts.
# Usage (venv): python -I xatlas_run.py results2
import sys, os, glob, json, time
import numpy as np
import xatlas
R = os.path.join(os.path.dirname(os.path.abspath(__file__)), sys.argv[1])

def run(P, T):
    atlas = xatlas.Atlas()
    atlas.add_mesh(P.astype(np.float32), T.astype(np.uint32))
    t0 = time.perf_counter(); atlas.generate(xatlas.ChartOptions(), xatlas.PackOptions()); dt = time.perf_counter() - t0
    vm, idx, uvs = atlas.get_mesh(0)
    s = np.array([atlas.width, atlas.height], np.float64) / max(atlas.width, atlas.height)
    return vm, idx, uvs.astype(np.float64) * s, dict(time=dt, width=atlas.width, height=atlas.height, charts=atlas.chart_count)

for f in sorted(glob.glob(os.path.join(R, '*__existing.npz'))):
    o = os.path.basename(f).split('__')[0]
    d = np.load(f); P, T = d['P'], d['T']
    vm, idx, uv, info = run(P, T)
    assert np.array_equal(vm[idx], T)
    np.savez(os.path.join(R, o + '__xatlas.npz'), P=P, T=T, UV=uv[idx], mat=d['mat'], extra=json.dumps(info))
    s = np.load(os.path.join(R, o + '__splitmesh.npz'))
    assert np.array_equal(s['orig'][s['Ts']], T), 'split mesh face order mismatch'
    vm, idx, uv, info2 = run(s['Ps'], s['Ts'])
    assert np.array_equal(vm[idx], s['Ts'])
    np.savez(os.path.join(R, o + '__xatlascut.npz'), P=P, T=T, UV=uv[idx], mat=d['mat'], extra=json.dumps(info2))
    print(o, 'xatlas', info, 'xatlascut', info2, 'splitverts', len(s['Ps']), 'verts', len(P))
