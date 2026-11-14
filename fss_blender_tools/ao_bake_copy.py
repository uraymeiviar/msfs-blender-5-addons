"""AO Bake: Apply's copy in C++ (apply-native-copy journal, decisions 1 and 2).

The per-pixel work of ao_bake_core.copy_master (the inside pixels' L x L sub-samples with the raster of their owners
and their master reads; the padding pixels' reads) runs in lib/ao_copy/windows-x64/fss_ao_copy.dll (source in the
repository's native/ao_copy/), loaded with ctypes as the JPEG XL library is. Its results are bit-identical to the
numpy copy, which stays the reference and the fallback: when the DLL cannot be loaded (another OS, a missing file) or
FSS_AO_COPY=numpy is set, copy_master runs numpy, and Apply's report says so.

The DLL reads the master where copy_master's numpy reads it: a master paged by open_master through its scratch page
files, memory-mapped read-only (PagedArray.address); a master held whole (load_master, tests) from contiguous arrays,
its filled mask and face map packed into the .ao.map codes once per master. The caller owns every buffer.
"""

import ctypes
import os
import sys
from ctypes import POINTER, Structure, c_double, c_int32, c_int64, c_void_p

import numpy as np

LIB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib', 'ao_copy', 'windows-x64')
DLL = 'fss_ao_copy.dll'
ENV = 'FSS_AO_COPY'  # 'numpy': the numpy copy (tests, measurements)
VERSION = 1  # the interface this module expects (fss_ao_copy_version)
THREADS = 12  # at most (the bake's Threads setting)
MAX_LEVEL = 64  # sub-samples per pixel axis the DLL takes at most (copy_master's kmax is 16)
ERRORS = {-1: 'bad arguments', -2: 'out of memory', -3: 'internal error'}


class MasterStruct(Structure):
    """fss_ao_master (native/ao_copy/fss_ao_copy.h): every field 8 bytes."""
    _fields_ = [('W', c_int64), ('H', c_int64), ('tile', c_int64), ('tiles_x', c_int64), ('image', c_void_p),
                ('code', c_void_p), ('muv', c_void_p), ('island', c_void_p), ('rects', c_void_p),
                ('n_rects', c_int64), ('tri_normal', c_void_p), ('n_tris', c_int64), ('surface_cos', c_double),
                ('surface', c_int64)]


_lib = dict(tried=False, dll=None, error=None, version=None)


def load():
    """The DLL as a ctypes library, or None when it cannot be loaded (the reason in error())."""
    if _lib['tried']:
        return _lib['dll']
    _lib['tried'] = True
    try:
        if sys.platform != 'win32' or ctypes.sizeof(c_void_p) != 8:
            raise OSError(f'no C++ copy for {sys.platform} ({8 * ctypes.sizeof(c_void_p)}-bit) in the add-on')
        path = os.path.join(LIB_DIR, DLL)
        if not os.path.isfile(path):
            raise OSError(f'{path} missing')
        dll = ctypes.CDLL(path)
        dll.fss_ao_copy_version.restype, dll.fss_ao_copy_version.argtypes = c_int32, []
        v = int(dll.fss_ao_copy_version())
        if v != VERSION:
            raise OSError(f'{path}: version {v}, the add-on expects {VERSION}')
        p, i64 = c_void_p, c_int64
        sig = {
            'fss_ao_copy_inside': (c_int32, [POINTER(MasterStruct), p, i64, p, p, p, p, i64, p, POINTER(c_int64)]),
            'fss_ao_copy_padding': (c_int32, [POINTER(MasterStruct), i64, p, p, p, p, i64, p, POINTER(c_int64)]),
            'fss_ao_copy_read': (c_int32, [POINTER(MasterStruct), i64, p, p, p, p]),
            'fss_ao_copy_raster': (c_int32, [p, i64, i64, i64, i64, i64, i64, p]),
            'fss_ao_copy_sum': (c_double, [p, i64]),
        }
        for name, (res, args) in sig.items():
            fn = getattr(dll, name)
            fn.restype, fn.argtypes = res, args
        _lib.update(dll=dll, version=v, error=None)
        return dll
    except (OSError, AttributeError) as exc:
        _lib.update(dll=None, version=None, error=f'{type(exc).__name__}: {exc}')
        return None


def reset():
    """Forget the load attempt (tests move the DLL away and back); a loaded DLL stays in the process."""
    _lib.update(tried=False, dll=None, error=None, version=None)


def error():
    load()
    return _lib['error']


def backend():
    """('native', None) when copy_master runs the C++ copy, else ('numpy', why)."""
    if os.environ.get(ENV, '').strip().lower() == 'numpy':
        return 'numpy', f'{ENV}=numpy is set'
    if load() is None:
        return 'numpy', f'the C++ copy is not loaded ({_lib["error"]})'
    return 'native', None


def threads_of(threads):
    return max(1, min(int(threads or THREADS), THREADS))


class CopyError(OSError):
    """The DLL returned an error (an OSError, so Apply reports it per texture set)."""


def _check(rc, what):
    if rc != 0:
        raise CopyError(f'fss_ao_copy_{what}: {ERRORS.get(rc, rc)}')


def _addr(a):
    return a.ctypes.data


class Prepared:
    """A master as the DLL reads it (made once per master dict, kept in master['_native']): its image and map codes
    (memory-mapped page files, or contiguous arrays), the layout's arrays; None from prepare() when the master cannot
    be read by the DLL (the numpy copy runs)."""

    def __init__(self, W, H, tile, tiles_x, image_addr, code_addr, muv, island, rects, keep=()):
        self.W, self.H, self.tile, self.tiles_x = W, H, tile, tiles_x
        self.image_addr, self.code_addr = image_addr, code_addr
        self.muv = np.ascontiguousarray(muv, np.float64)
        self.island = np.ascontiguousarray(island, np.int64)
        r = np.ascontiguousarray(np.asarray(rects, np.int64).reshape(-1, 4))
        self.n_rects = len(r)
        self.rects = r if len(r) else np.zeros((1, 4), np.int64)
        self.keep = keep  # the arrays the addresses point into

    def struct(self, tri_normal, surface_cos, surface):
        tn = np.ascontiguousarray(tri_normal, np.float64)
        s = MasterStruct(W=self.W, H=self.H, tile=self.tile, tiles_x=self.tiles_x, image=self.image_addr,
                         code=self.code_addr, muv=_addr(self.muv), island=_addr(self.island),
                         rects=_addr(self.rects), n_rects=self.n_rects, tri_normal=_addr(tn), n_tris=len(self.muv),
                         surface_cos=float(surface_cos if surface_cos is not None else 2.0), surface=int(surface))
        return s, tn


def prepare(master, paged_types):
    """The master's Prepared (cached in the dict), or None when the DLL cannot read it: an image that is not uint16,
    a per-pixel rect_id, or arrays of another kind. paged_types: (PagedArray, _PagedView) of ao_bake_core."""
    got = master.get('_native')
    if got is not None:
        return got if got != 'no' else None
    PagedArray, PagedView = paged_types
    M, filled, face = master['image'], master['filled'], master.get('face_map')
    prep = None
    if master.get('rect_id') is None and M.dtype == np.uint16 and master['muv'].ndim == 3:
        H, W = M.shape
        if (isinstance(M, PagedArray) and isinstance(filled, PagedView)
                and (face is None or (isinstance(face, PagedView) and face.base is filled.base))):
            code = filled.base
            if code.dtype == np.int32 and code.shape == M.shape and code.T == M.T and M.ntx == code.ntx:
                prep = Prepared(W, H, M.T, M.ntx, M.address(), code.address(), master['muv'], master['island'],
                                master['rects'])
        elif isinstance(M, np.ndarray) and isinstance(filled, np.ndarray) and (face is None
                                                                                or isinstance(face, np.ndarray)):
            if filled.shape == M.shape and (face is None or (face.shape == M.shape
                                                             and np.issubdtype(face.dtype, np.integer))):
                img = np.ascontiguousarray(M)
                f = (np.zeros(M.shape, np.int64) - 1) if face is None else face.astype(np.int64)
                if f.min(initial=-1) >= -1 and f.max(initial=-1) < (1 << 30):
                    code = np.ascontiguousarray(((f + 1) * 2 + (np.asarray(filled) != 0)).astype(np.int32))
                    prep = Prepared(W, H, 0, 0, _addr(img), _addr(code), master['muv'], master['island'],
                                    master['rects'], keep=(img, code))
    master['_native'] = prep if prep is not None else 'no'
    return prep


def inside(prep, tri_normal, surface_cos, surface, uvpx, X, Y, owner, level, gx, gy, threads):
    """fss_ao_copy_inside: (values, clamped sub-samples) of the inside pixels."""
    dll = load()
    n = len(X)
    out = np.empty(n, np.float64)
    if not n:
        return out, 0
    s, tn = prep.struct(tri_normal, surface_cos, surface)
    uv = np.ascontiguousarray(uvpx, np.float64)
    px = np.ascontiguousarray(np.stack([X, Y], axis=1), np.int64)
    org = np.ascontiguousarray(np.stack([gx, gy], axis=1), np.int64)
    own = np.ascontiguousarray(owner, np.int64)
    lvl = np.ascontiguousarray(level, np.int64)
    cl = c_int64(0)
    _check(dll.fss_ao_copy_inside(ctypes.byref(s), _addr(uv), n, _addr(px), _addr(own), _addr(lvl), _addr(org),
                                  threads_of(threads), _addr(out), ctypes.byref(cl)), 'inside')
    del tn
    return out, int(cl.value)


def padding(prep, tri_normal, surface_cos, surface, X, Y, src, tri_uv, level, threads):
    """fss_ao_copy_padding: (values, clamped points) of the padding pixels."""
    dll = load()
    n = len(X)
    out = np.empty(n, np.float64)
    if not n:
        return out, 0
    s, tn = prep.struct(tri_normal, surface_cos, surface)
    px = np.ascontiguousarray(np.stack([X, Y], axis=1), np.int64)
    sr = np.ascontiguousarray(src, np.int64)
    tuv = np.ascontiguousarray(tri_uv, np.float64)
    lvl = np.ascontiguousarray(level, np.int64)
    cl = c_int64(0)
    _check(dll.fss_ao_copy_padding(ctypes.byref(s), n, _addr(px), _addr(sr), _addr(tuv), _addr(lvl),
                                   threads_of(threads), _addr(out), ctypes.byref(cl)), 'padding')
    del tn
    return out, int(cl.value)


# ---------------------------------------------------------------------------------------------------------------------
# Test entry points (tests/test_ao_copy_native.py)
# ---------------------------------------------------------------------------------------------------------------------

def read(prep, tri_normal, surface_cos, surface, tri_ids, bary):
    """copy_master's read() in C++: (values, clamped mask)."""
    dll = load()
    n = len(tri_ids)
    out = np.empty(n, np.float64)
    cl = np.zeros(n, np.uint8)
    s, tn = prep.struct(tri_normal, surface_cos, surface)
    t = np.ascontiguousarray(tri_ids, np.int64)
    b = np.ascontiguousarray(bary, np.float64)
    _check(dll.fss_ao_copy_read(ctypes.byref(s), n, _addr(t), _addr(b), _addr(out), _addr(cl)), 'read')
    del tn
    return out, cl.astype(bool)


def raster(uvpx, gw, gh, level, gx, gy):
    """rasterize_ids' owners in C++ (the counts are not computed)."""
    dll = load()
    uv = np.ascontiguousarray(uvpx, np.float64)
    own = np.empty((gh * level, gw * level), np.int64)
    _check(dll.fss_ao_copy_raster(_addr(uv), len(uv), int(gx), int(gy), int(gw), int(gh), int(level), _addr(own)),
           'raster')
    return own


def total(a):
    """np.add.reduce of a float64 array as the DLL computes it."""
    a = np.ascontiguousarray(a, np.float64)
    return float(load().fss_ao_copy_sum(_addr(a), len(a)))

