"""The libPolygone DLL through ctypes (include/polygone/polygone.h of H:/git-repos/libPolygone, interface version 2).

The bundled DLL is lib/windows-x64/polygone.dll. The add-on's preferences can name another one (a fresh build of the
library); either is loaded from a copy in the temporary folder, so a running Blender never holds the file a build
writes, and Reload loads a newer copy without restarting Blender.

Everything here runs without bpy, so reduce() can run in worker threads: ctypes releases the GIL during a call, and
the library reduces one mesh per call on one thread.
"""

import ctypes
import hashlib
import os
import shutil
import sys
import tempfile
from ctypes import POINTER, Structure, c_float, c_uint8, c_uint32, c_uint64, c_void_p

import numpy as np

LIB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib', 'windows-x64')
BUNDLED = os.path.join(LIB_DIR, 'polygone.dll')
INTERFACE_VERSION = 2

STATUS = {0: 'ok', 1: 'invalid argument', 2: 'out of memory', 3: 'unsupported', 4: 'internal error'}
STOP = {0: 'target reached', 1: 'max error reached', 2: 'no collapse left'}

ATTRIBUTE_UNIT_VECTOR = 1
ATTRIBUTE_CLAMP01 = 2
LOCK_OPEN_BORDERS = 1
LOCK_GROUP_BORDERS = 2
PLACEMENT_OPTIMAL = 0
PLACEMENT_SUBSET = 1

# PolygoneExperimental: (bit, name, default on). A set bit turns its switch the other way from its default.
SWITCHES = (
    (1, 'Retry placement', False),
    (2, 'Curve solve 3D', True),
    (4, 'Slide curve ends', False),
    (8, 'Remove border components', False),
    (16, 'Line quadrics', False),
    (32, 'Memoryless borders', True),
    (64, 'Collapse junctions', True),
    (128, 'Collapse islands', True),
    (256, 'Borders along edge', False),
    (512, 'Swing seams', False),
    (1024, 'Swing by largest error', True),
    (2048, 'Remember borders', False),
    (4096, 'Keep input values', False),
    (8192, 'Root area weights', False),
    (16384, 'Restrain placement', False),
    (32768, 'Subset values on wide wedges', False),
    (65536, 'Split normalisation', False),
    (131072, 'Constrain volume', False),
    (262144, 'Region normals', False),
    (524288, 'Stall stage', False),
    (1048576, 'Relative quality floor', True),
    (2097152, 'Min-max placement', False),
    (4194304, 'Reject UV folds', False),
    (8388608, 'Max-plane term', False),
    (16777216, 'Sample gate', False),
    (33554432, 'Edge flips at a stall', False),
)


class Attribute(Structure):
    _fields_ = [('data', c_void_p), ('componentCount', c_uint32), ('stride', c_uint32), ('weight', c_float),
                ('flags', c_uint32)]


class FeatureEdge(Structure):
    _fields_ = [('vertices', c_uint32 * 2), ('weight', c_float)]


class MeshView(Structure):
    _fields_ = [('structSize', c_uint32), ('positions', c_void_p), ('positionStride', c_uint32),
                ('vertexCount', c_uint32), ('indices', c_void_p), ('indexCount', c_uint32),
                ('attributes', POINTER(Attribute)), ('attributeCount', c_uint32), ('triangleGroups', c_void_p),
                ('vertexLocks', c_void_p), ('featureEdges', POINTER(FeatureEdge)), ('featureEdgeCount', c_uint32),
                ('vertexImportance', c_void_p)]


class ReduceOptions(Structure):
    _fields_ = [('structSize', c_uint32), ('targetTriangleCount', c_uint32), ('maxError', c_float),
                ('flags', c_uint32), ('placement', c_uint32), ('maxNormalDeviation', c_float),
                ('experimental', c_uint32)]


class ResultInfo(Structure):
    _fields_ = [('structSize', c_uint32), ('vertexCount', c_uint32), ('indexCount', c_uint32), ('error', c_float),
                ('errorInputToOutput', c_float), ('errorOutputToInput', c_float), ('peakMemoryBytes', c_uint64),
                ('stopReason', c_uint32)]


_lib = dict(dll=None, path=None, source=None, error=None, version=None)


def _shadow_copy(path):
    """A copy of the DLL in the temporary folder, named by its content, so the original stays free for a build."""
    with open(path, 'rb') as f:
        digest = hashlib.sha1(f.read()).hexdigest()[:16]
    folder = os.path.join(tempfile.gettempdir(), 'polygone-blender')
    os.makedirs(folder, exist_ok=True)
    copy = os.path.join(folder, f'polygone-{digest}.dll')
    if not os.path.isfile(copy):
        shutil.copyfile(path, copy)
    return copy


def load(override=''):
    """The library, loaded once per source path; None when it cannot be loaded (the reason in error())."""
    source = override.strip() if override and override.strip() else BUNDLED
    if _lib['dll'] is not None and _lib['source'] == source:
        return _lib['dll']
    try:
        if sys.platform != 'win32' or ctypes.sizeof(c_void_p) != 8:
            raise OSError(f'no libPolygone build for {sys.platform} ({8 * ctypes.sizeof(c_void_p)}-bit) in the add-on')
        if not os.path.isfile(source):
            raise OSError(f'{source} missing')
        path = _shadow_copy(source)
        dll = ctypes.CDLL(path)
        dll.polygoneInterfaceVersion.restype, dll.polygoneInterfaceVersion.argtypes = c_uint32, []
        version = int(dll.polygoneInterfaceVersion())
        if version != INTERFACE_VERSION:
            raise OSError(f'{source}: interface version {version}, the add-on expects {INTERFACE_VERSION}')
        p, u32 = c_void_p, c_uint32
        sig = {
            'polygoneReduce': (u32, [POINTER(MeshView), POINTER(ReduceOptions), POINTER(c_void_p)]),
            'polygoneResultGetInfo': (u32, [p, POINTER(ResultInfo)]),
            'polygoneResultCopyIndices': (u32, [p, p, u32]),
            'polygoneResultCopySourceVertices': (u32, [p, p, u32]),
            'polygoneResultCopyPositions': (u32, [p, p, u32]),
            'polygoneResultCopyAttribute': (u32, [p, u32, p, u32]),
            'polygoneResultCopyTriangleGroups': (u32, [p, p, u32]),
            'polygoneResultDestroy': (None, [p]),
        }
        for name, (res, args) in sig.items():
            fn = getattr(dll, name)
            fn.restype, fn.argtypes = res, args
        _lib.update(dll=dll, path=path, source=source, error=None, version=version)
        return dll
    except (OSError, AttributeError) as exc:
        _lib.update(dll=None, path=None, source=source, error=f'{type(exc).__name__}: {exc}', version=None)
        return None


def reset():
    """Forget the loaded library; the next load() takes a fresh copy (a loaded DLL stays in the process)."""
    _lib.update(dll=None, path=None, source=None, error=None, version=None)


def error():
    return _lib['error']


def source():
    return _lib['source']


def _ptr(array):
    return array.ctypes.data_as(c_void_p) if array is not None else None


def _check(status, what):
    if status != 0:
        raise RuntimeError(f'{what}: {STATUS.get(status, status)}')


def reduce(dll, mesh, settings):
    """Reduce one mesh. mesh: dict of numpy arrays (positions float32 (n,3), indices uint32 (t*3), attributes list of
    (float32 (n,c), weight, flags), groups uint32 (t), locks uint8 (n) or None, importance float32 (n) or None,
    features uint32 (e,2) and float32 (e) or None). settings: dict of the ReduceOptions fields.
    Returns a dict with the output arrays and the result info."""
    positions = np.ascontiguousarray(mesh['positions'], dtype=np.float32)
    indices = np.ascontiguousarray(mesh['indices'], dtype=np.uint32)
    streams = [(np.ascontiguousarray(a, dtype=np.float32), w, f) for a, w, f in mesh['attributes']]
    groups = np.ascontiguousarray(mesh['groups'], dtype=np.uint32)
    locks = mesh.get('locks')
    locks = np.ascontiguousarray(locks, dtype=np.uint8) if locks is not None else None
    importance = mesh.get('importance')
    importance = np.ascontiguousarray(importance, dtype=np.float32) if importance is not None else None

    attributes = (Attribute * max(1, len(streams)))()
    for i, (a, w, f) in enumerate(streams):
        attributes[i] = Attribute(_ptr(a), a.shape[1], 0, float(w), int(f))
    feature_vertices, feature_weights = mesh.get('features') or (None, None)
    count = 0 if feature_vertices is None else len(feature_vertices)
    features = (FeatureEdge * max(1, count))()
    for i in range(count):
        features[i] = FeatureEdge((c_uint32 * 2)(int(feature_vertices[i, 0]), int(feature_vertices[i, 1])),
                                  float(feature_weights[i]))

    view = MeshView(ctypes.sizeof(MeshView), _ptr(positions), 0, len(positions), _ptr(indices), len(indices),
                    attributes, len(streams), _ptr(groups), _ptr(locks), features if count else None, count,
                    _ptr(importance))
    options = ReduceOptions(ctypes.sizeof(ReduceOptions), int(settings['target']), float(settings['max_error']),
                            int(settings['flags']), int(settings['placement']), float(settings['max_normal']),
                            int(settings['experimental']))
    handle = c_void_p()
    _check(dll.polygoneReduce(ctypes.byref(view), ctypes.byref(options), ctypes.byref(handle)), 'polygoneReduce')
    try:
        info = ResultInfo()
        info.structSize = ctypes.sizeof(ResultInfo)
        _check(dll.polygoneResultGetInfo(handle, ctypes.byref(info)), 'polygoneResultGetInfo')
        n, k = info.vertexCount, info.indexCount
        out_indices = np.empty(k, dtype=np.uint32)
        out_sources = np.empty(n, dtype=np.uint32)
        out_positions = np.empty((n, 3), dtype=np.float32)
        out_groups = np.empty(k // 3, dtype=np.uint32)
        _check(dll.polygoneResultCopyIndices(handle, _ptr(out_indices), k), 'polygoneResultCopyIndices')
        _check(dll.polygoneResultCopySourceVertices(handle, _ptr(out_sources), n), 'polygoneResultCopySourceVertices')
        _check(dll.polygoneResultCopyPositions(handle, _ptr(out_positions), n * 3), 'polygoneResultCopyPositions')
        _check(dll.polygoneResultCopyTriangleGroups(handle, _ptr(out_groups), k // 3),
               'polygoneResultCopyTriangleGroups')
        out_attributes = []
        for i, (a, _w, _f) in enumerate(streams):
            data = np.empty((n, a.shape[1]), dtype=np.float32)
            _check(dll.polygoneResultCopyAttribute(handle, i, _ptr(data), data.size), 'polygoneResultCopyAttribute')
            out_attributes.append(data)
        return dict(indices=out_indices, sources=out_sources, positions=out_positions, groups=out_groups,
                    attributes=out_attributes, error=info.error, error_in_out=info.errorInputToOutput,
                    error_out_in=info.errorOutputToInput, peak_memory=info.peakMemoryBytes,
                    stop=STOP.get(info.stopReason, str(info.stopReason)))
    finally:
        dll.polygoneResultDestroy(handle)
