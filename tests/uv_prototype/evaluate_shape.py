"""Round-5 baseline: python -I evaluate_shape.py RESULTS [OUTPUT].

Requires NumPy/SciPy in a venv. Reads existing/proto3/all NPZs and seam/shading
sidecars, never runs Blender or changes UVs. Includes unchanged round-3 metrics.
JSON non-finite values are explicit strings; per-face arrays retain IEEE values.
"""
import ast
import hashlib
import json
import sys
from pathlib import Path
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import uvmetrics as um
from evaluate3_extra import artist_texel


def legacy_metrics():
    # Load just the existing function; evaluate3's top level runs other methods
    # and imports optional xatlas/plotting packages unrelated to this evaluation.
    source = ast.parse((HERE / 'evaluate3.py').read_text())
    source.body = [n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == 'metrics']
    assert len(source.body) == 1
    namespace = dict(np=np, um=um, coo_matrix=coo_matrix, connected_components=connected_components)
    exec(compile(source, str(HERE / 'evaluate3.py'), 'exec'), namespace)
    return namespace['metrics']


def clean(value):
    if isinstance(value, dict): return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [clean(v) for v in value]
    if isinstance(value, np.generic): return clean(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return 'NaN' if np.isnan(value) else ('Infinity' if value > 0 else '-Infinity')
    return value


def main():
    results = Path(sys.argv[1]).resolve()
    out = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else results / 'shape_baseline'
    out.mkdir(parents=True, exist_ok=True)
    methods = ('existing', 'proto3', 'all')
    objects = sorted(p.name[:-len('__existing.npz')] for p in results.glob('*__existing.npz'))
    if not objects: raise ValueError('No existing UV datasets')
    metrics = legacy_metrics()
    rows = []
    for obj in objects:
        with np.load(results / (obj + '__existing.npz'), allow_pickle=False) as data:
            reference = {k: data[k].copy() for k in ('P', 'T', 'mat')}
        seams = np.load(results / (obj + '__seams.npy'), allow_pickle=False)
        normals = np.load(results / (obj + '__nsplit_T.npy'), allow_pickle=False)
        for method in methods:
            path = results / (obj + '__' + method + '.npz')
            with np.load(path, allow_pickle=False) as data:
                P, T, UV = (data[k] for k in ('P', 'T', 'UV'))
                for k in reference:
                    if not np.array_equal(reference[k], data[k]):
                        raise ValueError(f'{obj}/{method}: mismatched {k}')
                extra = json.loads(str(data['extra']))
            old, labels, overlaps = metrics(P, T, UV, normals)
            artist = artist_texel(P, T, UV, labels, seams)
            shape = um.shape_metrics(P, T, UV)
            # Do not silently substitute the legacy non-manifold island convention.
            np.savez_compressed(out / (obj + '__' + method + '__faces.npz'), **shape.pop('faces'))
            row = dict(object=obj, method=method, input_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                       runtime_seconds=None if method == 'existing' else extra.get('time'),
                       legacy=old, artist=artist, shape=shape)
            rows.append(row)
            print(obj, method, 'C95', shape['object']['conformal']['p95'], flush=True)
    report = dict(methods=methods, object_count=len(objects), metrics_source_sha256={
        name: hashlib.sha256((HERE/name).read_bytes()).hexdigest()
        for name in ('uvmetrics.py','evaluate3.py','evaluate3_extra.py')}, rows=rows)
    (out / 'baseline.json').write_text(json.dumps(clean(report), indent=2, allow_nan=False))
    print('COMPLETE', len(rows), 'method/object rows')


if __name__ == '__main__': main()
