"""AO Bake: the per-pixel work in C++ (apply-native-copy journal, decisions 1 to 6; bake-post-native journal).

lib/ao_copy/windows-x64/fss_ao_copy.dll (source in the repository's native/ao_copy/), loaded with ctypes as the JPEG
XL library is, does the AO Bake's per-pixel work. Decision 6: it is required, with libjxl (its opening of a master
needs it); there is no Python version of its parts. unavailable() says why the AO Bake cannot run (the DLL or libjxl
not loaded): the AO Bake panel shows it, its operators refuse, and the bake's runner fails the job with it.

- Apply's copy (interface version 1): the inside pixels' L x L sub-samples with the raster of their owners and their
  master reads, the padding pixels' reads (inside, padding). The DLL reads the master where ao_bake_core.copy_master
  reads it: a master paged by open_master through its scratch page files, memory-mapped read-only
  (PagedArray.address); a master held whole (load_master, tests) from contiguous arrays, its filled mask and face map
  packed into the .ao.map codes once per master. The caller owns every buffer.
- The opening of a master (interface version 2, apply-native-copy journal Session 4): open_pages() decodes its JPEG XL
  with libjxl's thread runner (the add-on's lib/jxl DLLs, loaded by the DLL from their folder) and inflates its .ao.map,
  into the two tiled page files of ao_bake_core.open_master.
- PNG files (interface version 3, Session 7, decision 4): PngWriter compresses the filtered rows in blocks at fixed byte
  offsets on several threads (the method of pigz), the same bytes for any thread count and any blocking of the rows;
  read_png() reads grey, grey + alpha, RGB and RGBA at 8 or 16 bits with every filter.
- Apply's per-pixel work around the copy (interface version 4, Sessions 10 and 11): the raster of owners (raster_ids:
  ao_bake_core.rasterize_ids and raster_window), the dilation (dilate: dilate_ids), the UV islands (uv_islands) and
  Soften Sharp Edges (soften, with the C++ read).
- The bake's post-processing (interface version 5, bake-post-native journal): compose() is ao_bake_core.compose_block
  for one window (the corner rule, the nearest fill inside the island rectangles, the face map of the core and the
  skirt, the counts) on a team of threads_of(threads) threads; MapWriter writes the .ao.map (zlib's deflate,
  compressed on a thread beside the composition).
- Refresh's scene rule (interface version 6, bake-post-native journal Sessions 4 and 5): SceneRule holds one pass's
  candidates (their bound_box corners, their matrices now and at each pose, who moves, the occluders' rows);
  SceneRule.near() is ao_bake_store's near (the world-box and own-box gaps, the keep test) for many objects in one
  call, SceneRule.moves() its test of motion against an occluder (decision 59) for many pairs; mesh_hash() is
  ao_bake_core.mesh_hash's SHA-1.

Each part gives the same result at any thread count; the tests compare them with the values recorded from the Python
code they replaced (tests/data/ao_native_reference.json), so the masters already baked stay valid.
"""

import ctypes
import importlib.util
import os
import sys
from ctypes import POINTER, Structure, byref, c_char_p, c_double, c_int32, c_int64, c_void_p, c_wchar_p

import numpy as np

LIB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib', 'ao_copy', 'windows-x64')
DLL = 'fss_ao_copy.dll'
VERSION = 8  # the interface this module expects (fss_ao_copy_version)
CPUS = os.cpu_count() or 2  # the PC's logical processors
THREADS = max(2, CPUS // 2)  # Threads 0, Auto (apply-native-copy decision 5): half the logical processors, at least 2
MAX_LEVEL = 64  # sub-samples per pixel axis the DLL takes at most (copy_master's kmax is 16)
ERRORS = {-1: 'bad arguments', -2: 'out of memory', -3: 'internal error', -4: 'file error', -5: 'bad file',
          -6: 'JPEG XL library not loaded', -7: 'a PNG not read by the C++ reader', -8: 'an output buffer too small'}
E_UNSUPPORTED = -7
E_SPACE = -8
MESSAGE_BYTES = 2048


class MasterStruct(Structure):
    """fss_ao_master (native/ao_copy/fss_ao_copy.h): every field 8 bytes."""
    _fields_ = [('W', c_int64), ('H', c_int64), ('tile', c_int64), ('tiles_x', c_int64), ('image', c_void_p),
                ('code', c_void_p), ('muv', c_void_p), ('island', c_void_p), ('rects', c_void_p),
                ('n_rects', c_int64), ('tri_normal', c_void_p), ('n_tris', c_int64), ('surface_cos', c_double),
                ('surface', c_int64)]


class SoftenStruct(Structure):
    """fss_ao_soften: the folds of ao_bake_core.soften_context, every field 8 bytes."""
    _fields_ = [('n_edges', c_int64), ('E', c_void_p), ('A', c_void_p), ('B', c_void_p), ('mX', c_void_p),
                ('mY', c_void_p), ('hX', c_void_p), ('hY', c_void_p), ('convex', c_void_p), ('n_tris', c_int64),
                ('start', c_void_p), ('cand', c_void_p), ('Wt', c_void_p), ('n_verts', c_int64), ('pos', c_void_p),
                ('tris', c_void_p), ('surface_cos', c_double)]


class ComposeLayout(Structure):
    """fss_ao_compose_layout: a master's layout as compose_block reads it, every field 8 bytes."""
    _fields_ = [('fill', c_int64), ('corner_excess', c_int64), ('rects', c_void_p), ('n_rects', c_int64),
                ('core_uv', c_void_p), ('core_face', c_void_p), ('n_core', c_int64), ('skirt_uv', c_void_p),
                ('skirt_face', c_void_p), ('n_skirt', c_int64), ('corner', c_void_p), ('n_corner', c_int64)]


class MapStats(Structure):
    """fss_ao_map_stats: what a map writer did."""
    _fields_ = [('seconds', c_double), ('wait_seconds', c_double), ('deflate_seconds', c_double),
                ('threads', c_int64), ('raw_bytes', c_int64), ('file_bytes', c_int64)]

    def as_dict(self):
        return dict(seconds=round(self.seconds, 3), wait_seconds=round(self.wait_seconds, 3),
                    deflate_seconds=round(self.deflate_seconds, 3), threads=int(self.threads),
                    raw_bytes=int(self.raw_bytes), file_bytes=int(self.file_bytes))


class SceneStruct(Structure):
    """fss_ao_scene: one Refresh pass's candidates, every field 8 bytes."""
    _fields_ = [('n_rows', c_int64), ('n_poses', c_int64), ('M', c_void_p), ('moving', c_void_p), ('now', c_void_p),
                ('corners', c_void_p), ('n_occ', c_int64), ('occ_rows', c_void_p), ('ortho_tol', c_double),
                ('motion_tol', c_double)]


class NearStats(Structure):
    """fss_ao_near_stats: how close the scene rule's gaps came to the distances."""
    _fields_ = [('closest_world', c_double), ('closest_own', c_double), ('within', c_int64),
                ('world_tests', c_int64), ('own_tests', c_int64)]


class OpenStats(Structure):
    """fss_ao_open_stats: what fss_ao_copy_open_master did."""
    _fields_ = [('seconds', c_double), ('image_seconds', c_double), ('map_seconds', c_double),
                ('decode_threads', c_int64), ('threads', c_int64), ('most_open_tile_rows', c_int64)]


class PngStats(Structure):
    """fss_ao_png_stats: what a PNG writer or reader did."""
    _fields_ = [('seconds', c_double), ('wait_seconds', c_double), ('threads', c_int64), ('blocks', c_int64),
                ('most_in_flight', c_int64), ('raw_bytes', c_int64), ('file_bytes', c_int64)]

    def as_dict(self):
        return dict(seconds=round(self.seconds, 3), wait_seconds=round(self.wait_seconds, 3), threads=int(self.threads),
                    blocks=int(self.blocks), most_in_flight=int(self.most_in_flight), raw_bytes=int(self.raw_bytes),
                    file_bytes=int(self.file_bytes))


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
            'fss_ao_copy_inside_blend': (c_int32, [POINTER(MasterStruct), p, i64, p, p, p, p, i64, p,
                                                   POINTER(c_int64)]),
            'fss_ao_copy_inside_filter': (c_int32, [POINTER(MasterStruct), p, i64, p, p, p, p, i64, i64, p,
                                                    POINTER(c_int64)]),
            'fss_ao_copy_padding': (c_int32, [POINTER(MasterStruct), i64, p, p, p, p, i64, p, POINTER(c_int64)]),
            'fss_ao_copy_read': (c_int32, [POINTER(MasterStruct), i64, p, p, p, p]),
            'fss_ao_copy_raster': (c_int32, [p, i64, i64, i64, i64, i64, i64, p]),
            'fss_ao_copy_sum': (c_double, [p, i64]),
            'fss_ao_copy_open_master': (c_int32, [c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p, i64, i64, i64,
                                                  i64, POINTER(OpenStats), c_char_p, i64]),
            'fss_ao_png_open': (c_int32, [c_wchar_p, i64, i64, i64, i64, i64, POINTER(c_void_p), c_char_p, i64]),
            'fss_ao_png_write': (c_int32, [p, p, i64, c_char_p, i64]),
            'fss_ao_png_close': (c_int32, [p, POINTER(PngStats), c_char_p, i64]),
            'fss_ao_png_abort': (None, [p]),
            'fss_ao_png_test_limit': (c_int32, [p, i64]),
            'fss_ao_png_read': (c_int32, [c_wchar_p, i64, i64, i64, i64, p, i64, POINTER(PngStats), c_char_p, i64]),
            'fss_ao_copy_raster_ids': (c_int32, [p, i64, i64, i64, i64, i64, i64, c_double, i64, p, i64, i64, p, p]),
            'fss_ao_copy_dilate': (c_int32, [p, i64, i64, i64, p, i64, p, p]),
            'fss_ao_copy_uv_islands': (c_int32, [p, p, i64, c_double, i64, p]),
            'fss_ao_copy_soften': (c_int32, [POINTER(MasterStruct), POINTER(SoftenStruct), i64, p, p, p, i64, p,
                                             POINTER(c_int64)]),
            'fss_ao_compose_block': (c_int32, [POINTER(ComposeLayout), p, i64, p, i64, i64, i64, i64, i64, i64, i64,
                                               i64, i64, i64, p, p, p, p, i64, p]),
            'fss_ao_map_open': (c_int32, [c_wchar_p, i64, i64, i64, i64, POINTER(c_void_p), c_char_p, i64]),
            'fss_ao_map_write': (c_int32, [p, p, i64, i64, c_char_p, i64]),
            'fss_ao_map_close': (c_int32, [p, POINTER(MapStats), c_char_p, i64]),
            'fss_ao_map_abort': (None, [p]),
            'fss_ao_scene_near': (c_int32, [POINTER(SceneStruct), i64, p, p, p, p, i64, p, p, p, i64,
                                            POINTER(NearStats)]),
            'fss_ao_scene_moves': (c_int32, [POINTER(SceneStruct), i64, p, p, i64, p, POINTER(c_double)]),
            'fss_ao_scene_boxes': (c_int32, [i64, p, p, p, c_double, p, p, p, p]),
            'fss_ao_scene_gaps': (c_int32, [p, p, p, i64, p, p, p, p]),
            'fss_ao_mesh_hash': (c_int32, [p, i64, p, i64, p, i64, i64, i64, p]),
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


_jxl_module = []


def _jxl():
    """ao_bake_jxl (libjxl), imported from the package or, when this file was loaded by its path (the second Blender,
    the tests), under the name ao_bake_core.jxl() gives it, so both use one module."""
    if not _jxl_module:
        try:
            from . import ao_bake_jxl as mod
        except ImportError:
            name = '_fss_ao_bake_jxl'
            mod = sys.modules.get(name)
            if mod is None:
                spec = importlib.util.spec_from_file_location(
                    name, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ao_bake_jxl.py'))
                mod = importlib.util.module_from_spec(spec)
                sys.modules[name] = mod
                spec.loader.exec_module(mod)
        _jxl_module.append(mod)
    return _jxl_module[0]


def unavailable():
    """Decision 6: None when the AO Bake can run here, else why not, on one line: fss_ao_copy.dll not loaded (missing,
    failed, another interface version) or libjxl not loaded (the DLL's opening of a master needs it)."""
    if load() is None:
        return f'{DLL} could not be loaded ({_lib["error"]})'
    lib = _jxl()
    if not lib.available():
        return f'the JPEG XL library (libjxl) could not be loaded ({lib.error()})'
    return None


def require():
    """Raises CopyError with unavailable()'s reason when the AO Bake cannot run here."""
    why = unavailable()
    if why:
        raise CopyError(f'AO Bake not available: {why}')


def loaded():
    """The DLL, or CopyError with the reason it could not be loaded (each call into it goes through here)."""
    dll = load()
    if dll is None:
        raise CopyError(f'AO Bake not available: {DLL} could not be loaded ({_lib["error"]})')
    return dll


def threads_of(threads):
    """The threads of a job: 0 or None Auto (THREADS), else the number asked, at most the PC's logical processors."""
    n = int(threads or 0)
    return THREADS if n <= 0 else max(1, min(n, max(CPUS, THREADS)))


class CopyError(OSError):
    """The DLL returned an error (an OSError, so Apply reports it per texture set)."""


class OpenError(CopyError):
    """fss_ao_copy_open_master failed: a file truncated, corrupt, of another size, not readable or not writable (its
    path in the message); the DLL removed the page files it had created."""


def open_pages(jxl_dir, image, map_path, page_image, page_map, W, H, tile, threads):
    """fss_ao_copy_open_master: the master's JPEG XL image and .ao.map into the page files page_image (uint16) and
    page_map (int32), tiles of `tile` px (ao_bake_core.PagedArray's layout). Returns the stats (seconds of the
    call, of the image and of the map, the decoder's threads, the threads in all, the image's rows of tiles mapped at
    most); raises OpenError."""
    dll = loaded()
    st = OpenStats()
    msg = ctypes.create_string_buffer(MESSAGE_BYTES)
    rc = dll.fss_ao_copy_open_master(str(jxl_dir), str(image), str(map_path), str(page_image), str(page_map), int(W),
                                     int(H), int(tile), threads_of(threads), ctypes.byref(st), msg, MESSAGE_BYTES)
    if rc != 0:
        text = msg.value.decode('utf-8', 'replace') or ERRORS.get(rc, str(rc))
        raise OpenError(f'opening the master: {text}')
    return dict(seconds=round(st.seconds, 3), image_seconds=round(st.image_seconds, 3),
                map_seconds=round(st.map_seconds, 3), decode_threads=int(st.decode_threads), threads=int(st.threads),
                most_open_tile_rows=int(st.most_open_tile_rows))


class PngError(CopyError):
    """A PNG not written (a folder missing, a full disk, the rows not all handed in) or not read (truncated, a corrupt
    zlib stream): the file's path in the message. The writer removed its file."""


class PngUnsupported(PngError):
    """A PNG the C++ reader does not read (a palette, interlace, another depth): read it another way."""


def _png_text(rc, msg):
    return msg.value.decode('utf-8', 'replace') or ERRORS.get(rc, str(rc))


class PngWriter:
    """A PNG written row by row (fss_ao_png_open, _write, _close, _abort): blocks of rows in file
    order (the top first), (n, w) or (n, w, C) integers in the file's depth; filter 0, zlib level 6, compressed on
    threads_of(threads) threads. close() raises PngError (the file removed) when not every row was written or a write
    failed; abort() removes the file. by: 'C++ (n threads)'; png_stats: what close() reported."""

    def __init__(self, path, w, h, bits=16, channels=1, threads=None):
        self.path, self.w, self.h, self.bits, self.ch = str(path), int(w), int(h), int(bits), int(channels)
        self.threads = threads_of(threads)
        self.dtype = np.uint16 if self.bits == 16 else np.uint8
        self.by = f"C++ ({self.threads} thread{'s' if self.threads != 1 else ''})"
        self.png_stats = {}  # not `stats`: MasterWriter keeps a writer's `stats` in the master's index
        self._dll = loaded()
        self._h = None
        self._msg = ctypes.create_string_buffer(MESSAGE_BYTES)
        h = c_void_p()
        rc = self._dll.fss_ao_png_open(self.path, self.w, self.h, self.bits, self.ch, self.threads, byref(h),
                                       self._msg, MESSAGE_BYTES)
        if rc != 0:
            raise PngError(f'writing the PNG: {_png_text(rc, self._msg)}')
        self._h = h

    def write(self, block):
        block = np.asarray(block)
        if not block.shape[0]:
            return
        if block.shape[1:] not in ((self.w,), (self.w, self.ch)) or (block.ndim == 2 and self.ch != 1):
            raise ValueError(f'{self.path}: rows of shape {block.shape[1:]}, the file has {self.w} x {self.ch}')
        if self._h is None:
            raise PngError(f'writing the PNG: {self.path}: the writer is closed')
        rows = np.ascontiguousarray(block.astype(self.dtype, copy=False))
        rc = self._dll.fss_ao_png_write(self._h, rows.ctypes.data, int(rows.shape[0]), self._msg, MESSAGE_BYTES)
        if rc != 0:
            raise PngError(f'writing the PNG: {_png_text(rc, self._msg)}')

    def close(self):
        if self._h is None:
            raise PngError(f'writing the PNG: {self.path}: the writer is closed')
        st = PngStats()
        h, self._h = self._h, None
        rc = self._dll.fss_ao_png_close(h, byref(st), self._msg, MESSAGE_BYTES)
        self.png_stats = st.as_dict()
        if rc != 0:
            raise PngError(f'writing the PNG: {_png_text(rc, self._msg)}')

    def abort(self):
        h, self._h = self._h, None
        if h:
            self._dll.fss_ao_png_abort(h)

    def test_limit(self, nbytes):
        """Tests: the writer fails as on a full disk once the file would exceed nbytes."""
        self._dll.fss_ao_png_test_limit(self._h, int(nbytes))

    def __del__(self):
        try:
            self.abort()
        except Exception:
            pass


def read_png(path, w, h, channels, bits, threads=None):
    """fss_ao_png_read: ((h, w, channels) uint16 in the file's depth, row 0 at the bottom; the stats). w, h, channels
    and bits: the file's header (ao_bake_core.png_info). Raises PngUnsupported (a palette, interlace, another depth)
    or PngError (not readable, truncated, corrupt), the file's path in the message."""
    dll = loaded()
    out = np.empty((int(h), int(w), int(channels)), np.uint16)
    st = PngStats()
    msg = ctypes.create_string_buffer(MESSAGE_BYTES)
    rc = dll.fss_ao_png_read(str(path), int(w), int(h), int(channels), int(bits), out.ctypes.data, threads_of(threads),
                             byref(st), msg, MESSAGE_BYTES)
    if rc == E_UNSUPPORTED:
        raise PngUnsupported(f'reading the PNG: {_png_text(rc, msg)}')
    if rc != 0:
        raise PngError(f'reading the PNG: {_png_text(rc, msg)}')
    return out, st.as_dict()


def _check(rc, what):
    if rc != 0:
        raise CopyError(f'fss_ao_copy_{what}: {ERRORS.get(rc, rc)}')


def _addr(a):
    return a.ctypes.data


class Prepared:
    """A master as the DLL reads it (made once per master dict, kept in master['_native']): its image and map codes
    (memory-mapped page files, or contiguous arrays), the layout's arrays; None from prepare() when the master cannot
    be read by the DLL (ao_bake_core.copy_master refuses it: re-bake needed)."""

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


def inside(prep, tri_normal, surface_cos, surface, uvpx, X, Y, owner, level, gx, gy, threads, blend=False,
           edge_filter=0):
    """fss_ao_copy_inside (blend: fss_ao_copy_inside_blend, auto-bake decision 108; with edge_filter 1, adaptive:
    fss_ao_copy_inside_filter, decision 109): (values, clamped sub-samples) of the inside pixels."""
    dll = loaded()
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
    if blend and edge_filter:
        _check(dll.fss_ao_copy_inside_filter(ctypes.byref(s), _addr(uv), n, _addr(px), _addr(own), _addr(lvl),
                                             _addr(org), threads_of(threads), int(edge_filter), _addr(out),
                                             ctypes.byref(cl)), 'inside')
    else:
        fn = dll.fss_ao_copy_inside_blend if blend else dll.fss_ao_copy_inside
        _check(fn(ctypes.byref(s), _addr(uv), n, _addr(px), _addr(own), _addr(lvl), _addr(org), threads_of(threads),
                  _addr(out), ctypes.byref(cl)), 'inside')
    del tn
    return out, int(cl.value)


def padding(prep, tri_normal, surface_cos, surface, X, Y, src, tri_uv, level, threads):
    """fss_ao_copy_padding: (values, clamped points) of the padding pixels."""
    dll = loaded()
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
# Apply's per-pixel work around the copy (interface version 4, apply-native-copy journal Sessions 10 and 11): the raster
# of owners, the dilation, the UV islands, Soften Sharp Edges, for ao_bake_core's rasterize_ids, raster_window,
# dilate_ids, uv_islands, island_labels and copy_master
# ---------------------------------------------------------------------------------------------------------------------

def raster_ids(uvpx, W, H, k=1, x0=0, y0=0, eps=1e-9, select=True, threads=None, label=None, owner=None,
               count=True):
    """fss_ao_copy_raster_ids: (owner (H*k, W*k) int64, count (H*k, W*k) int32 or None) as rasterize_ids (select
    False) or raster_window (select True) gives them. label: owners as label[t]; owner: an int64 array written into
    where covered (keep), else a new one of -1. uvpx must be float64 (N, 3, 2)."""
    dll = loaded()
    W, H, k = int(W), int(H), int(k)
    uv = np.ascontiguousarray(uvpx, np.float64).reshape(-1, 3, 2)
    keep = owner is not None
    if owner is None:
        owner = np.empty((H * k, W * k), np.int64)
    elif owner.dtype != np.int64 or not owner.flags.c_contiguous or owner.shape != (H * k, W * k):
        raise ValueError('raster_ids: owner must be a contiguous int64 array of the grid')
    cnt = np.empty((H * k, W * k), np.int32) if count else None
    if cnt is not None and keep:
        cnt[:] = 0
    lab = None if label is None else np.ascontiguousarray(label, np.int64)
    if lab is not None and len(lab) < len(uv):
        raise ValueError('raster_ids: a label per triangle')
    _check(dll.fss_ao_copy_raster_ids(_addr(uv) if len(uv) else None, len(uv), int(x0), int(y0), W, H, k, float(eps),
                                      int(bool(select)), None if lab is None else _addr(lab), int(keep),
                                      threads_of(threads), _addr(owner), None if cnt is None else _addr(cnt)),
           'raster_ids')
    return owner, cnt


def dilate(owner, iterations, mask_allowed=None, threads=None):
    """fss_ao_copy_dilate: (owner, steps) as dilate_ids gives them (int64; the caller casts back)."""
    dll = loaded()
    own = np.ascontiguousarray(owner, np.int64)
    H, W = own.shape
    out = np.empty((H, W), np.int64)
    steps = np.empty((H, W), np.int64)
    m = None if mask_allowed is None else np.ascontiguousarray(np.broadcast_to(mask_allowed, (H, W)), np.uint8)
    _check(dll.fss_ao_copy_dilate(_addr(own), W, H, int(iterations), None if m is None else _addr(m),
                                  threads_of(threads), _addr(out), _addr(steps)), 'dilate')
    return out, steps


def uv_islands(wtris, uv, tol=1e-6, threads=None):
    """fss_ao_copy_uv_islands: the island label (int64) per triangle, as ao_bake_core.uv_islands gives it."""
    dll = loaded()
    wt = np.ascontiguousarray(wtris, np.int64).reshape(-1, 3)
    u = np.ascontiguousarray(uv, np.float64).reshape(-1, 3, 2)
    out = np.empty(len(wt), np.int64)
    if not len(wt):
        return out
    _check(dll.fss_ao_copy_uv_islands(_addr(wt), _addr(u), len(wt), float(tol), threads_of(threads), _addr(out)),
           'uv_islands')
    return out


def soften_struct(sc, surface_cos):
    """The fss_ao_soften of a soften_context (made once per context, kept in sc['_native'] with its arrays)."""
    got = sc.get('_native')
    if got is not None and got[0] == surface_cos:
        return got[1]
    T = len(sc['tris'])
    arrs = dict(E=np.ascontiguousarray(sc['E'], np.int64).reshape(-1, 6),
                A=np.ascontiguousarray(sc['A'], np.float64), B=np.ascontiguousarray(sc['B'], np.float64),
                mX=np.ascontiguousarray(sc['mX'], np.float64), mY=np.ascontiguousarray(sc['mY'], np.float64),
                hX=np.ascontiguousarray(sc['hX'], np.float64), hY=np.ascontiguousarray(sc['hY'], np.float64),
                convex=np.ascontiguousarray(sc['convex'], np.uint8),
                start=np.ascontiguousarray(sc['start'], np.int64), cand=np.ascontiguousarray(sc['cand'], np.int64),
                Wt=np.ascontiguousarray(sc['Wt'], np.float64), pos=np.ascontiguousarray(sc['pos'], np.float64),
                tris=np.ascontiguousarray(sc['tris'], np.int64))
    s = SoftenStruct(n_edges=len(arrs['E']), n_tris=T, n_verts=len(arrs['pos']), surface_cos=float(surface_cos),
                     **{k: (_addr(v) if v.size else None) for k, v in arrs.items()})
    sc['_native'] = (surface_cos, (s, arrs))
    return s, arrs


def soften(prep, tri_normal, surface_cos, surface, sc, soft_cos, tri_ids, P3, vals, threads):
    """fss_ao_copy_soften: (values, points changed) of Soften Sharp Edges (decisions 46 and 58) at points P3 on the
    triangles tri_ids, read with copy_master's read; surface_cos and surface: the copy's read, soft_cos: the angle of
    the folds' faces."""
    dll = loaded()
    n = len(tri_ids)
    vals = np.ascontiguousarray(vals, np.float64)
    if not n:
        return vals.copy(), 0
    out = np.empty(n, np.float64)
    s, tn = prep.struct(tri_normal, surface_cos, surface)
    ss, _arrs = soften_struct(sc, soft_cos)
    t = np.ascontiguousarray(tri_ids, np.int64)
    p3 = np.ascontiguousarray(P3, np.float64)
    ch = c_int64(0)
    rc = dll.fss_ao_copy_soften(ctypes.byref(s), ctypes.byref(ss), n, _addr(t), _addr(p3), _addr(vals),
                                threads_of(threads), _addr(out), ctypes.byref(ch))
    if rc == -6:
        raise CopyError('fss_ao_copy_soften: pow of ucrtbase.dll (the C runtime numpy uses) not found')
    _check(rc, 'soften')
    del tn
    return out, int(ch.value)


# ---------------------------------------------------------------------------------------------------------------------
# The bake's post-processing (interface version 5, bake-post-native journal): the composition of a window, the .ao.map
# writer, for ao_bake_core's compose_block, compose_band and MasterWriter
# ---------------------------------------------------------------------------------------------------------------------

class Layout:
    """A master's layout (ao_bake_core.build_master's dict, with its corner_pairs) as fss_ao_compose_block reads it,
    made once per master (compose_layout)."""

    def __init__(self, m, fill, corner_excess):
        rects = np.ascontiguousarray(np.asarray(m['rects'], np.int64).reshape(-1, 4))
        core = np.ascontiguousarray(np.asarray(m['core_tris'], np.int64).reshape(-1))
        core_uv = np.ascontiguousarray(np.asarray(m['muv'])[core], np.float64).reshape(-1, 3, 2)
        has_skirt = len(m['skirt_pos']) > 0
        skirt_uv = np.ascontiguousarray(m['skirt_uv'], np.float64).reshape(-1, 3, 2) if has_skirt else None
        skirt_face = np.ascontiguousarray(m['skirt_src'], np.int64).reshape(-1) if has_skirt else None
        if has_skirt and len(skirt_face) != len(skirt_uv):
            raise ValueError('compose_layout: a skirt_src per skirt triangle')
        pairs = m.get('corner_pairs')
        corner = None
        if pairs is not None and len(pairs[0]):
            corner = np.ascontiguousarray(np.stack([np.asarray(a, np.int64) for a in pairs], axis=1))
        self.arrays = (rects, core, core_uv, skirt_uv, skirt_face, corner)  # the addresses point into these
        n_skirt = len(skirt_uv) if has_skirt else 0
        self.struct = ComposeLayout(
            fill=int(fill), corner_excess=int(corner_excess), rects=_addr(rects) if len(rects) else None,
            n_rects=len(rects), core_uv=_addr(core_uv) if len(core) else None,
            core_face=_addr(core) if len(core) else None, n_core=len(core),
            skirt_uv=_addr(skirt_uv) if n_skirt else None, skirt_face=_addr(skirt_face) if n_skirt else None,
            n_skirt=n_skirt, corner=None if corner is None else _addr(corner),
            n_corner=0 if corner is None else len(corner))


def compose_layout(m, fill, corner_excess):
    """The Layout of a master's dict m (fill: FILL; corner_excess: int(CORNER_EXCESS * 65535))."""
    return Layout(m, fill, corner_excess)


def _rows(a, dtype):
    """(array, row stride in elements) of a 2D array whose rows are contiguous; a copy when they are not."""
    a = np.asarray(a)
    if a.dtype == np.bool_ and dtype == np.uint8:
        a = a.view(np.uint8)
    if a.dtype != dtype or a.ndim != 2 or a.strides[1] != a.itemsize or a.strides[0] % a.itemsize or a.strides[0] < 0:
        a = np.ascontiguousarray(a, dtype)
    return a, (a.strides[0] // a.itemsize) if a.shape[0] > 1 else a.shape[1]


COUNT_KEYS = ('nearest_fill_px', 'rect_px_unfilled', 'rect_px', 'corner_px')  # compose_block's counts, in its order


def compose(layout, M16e, baked_e, ex0, ey0, win, threads=None, out_values=None, out_code=None, parts=True):
    """fss_ao_compose_block: compose_block's (counts, values, filled, face map) of the window win = (x0, y0, w, h)
    of the block M16e (uint16) and baked_e (bool) whose bottom-left pixel is (ex0, ey0), on threads_of(threads)
    threads. out_values and out_code: (h, w) arrays with contiguous rows and one row stride (a strip's columns), written
    instead of new ones; parts False: no filled and face arrays (None returned)."""
    dll = loaded()
    x0, y0, w, h = (int(v) for v in win)
    M, ms = _rows(M16e, np.uint16)
    B, bs = _rows(baked_e, np.uint8)
    eh, ew = M.shape
    if B.shape != (eh, ew):
        raise ValueError('compose: values and baked flags of another shape')
    vals = np.empty((h, w), np.uint16) if out_values is None else out_values
    if vals.dtype != np.uint16 or vals.shape != (h, w) or vals.strides[1] != 2 or vals.strides[0] < 0:
        raise ValueError('compose: out_values must be (h, w) uint16 with contiguous rows')
    stride = vals.strides[0] // 2 if h > 1 else w
    if out_code is not None and (out_code.dtype != np.int32 or out_code.shape != (h, w) or out_code.strides[1] != 4
                                 or (h > 1 and out_code.strides[0] != 4 * stride)):
        raise ValueError("compose: out_code must be (h, w) int32 with the values' row stride")
    filled = face = None
    if parts:
        if stride != w:
            raise ValueError('compose: filled and face need contiguous out_values')
        filled = np.empty((h, w), np.bool_)
        face = np.empty((h, w), np.int32)
    counts = (c_int64 * 4)()
    rc = dll.fss_ao_compose_block(ctypes.byref(layout.struct), _addr(M) if M.size else None, ms,
                                  _addr(B) if B.size else None, bs, int(ex0), int(ey0), ew, eh, x0, y0, w, h,
                                  threads_of(threads), _addr(vals) if vals.size else None,
                                  None if filled is None or not filled.size else _addr(filled),
                                  None if face is None or not face.size else _addr(face),
                                  None if out_code is None or not out_code.size else _addr(out_code), stride, counts)
    _check(rc, 'compose_block')
    return dict(zip(COUNT_KEYS, (int(c) for c in counts))), vals, filled, face


class MapError(CopyError):
    """An .ao.map not written (a folder missing, a full disk, the rows not all handed in): the file's path in the
    message. The writer removed its file."""


class MapWriter:
    """The .ao.map written row by row (fss_ao_map_open, _write, _close, _abort): blocks of int32 rows in
    file order (the top first); the same file byte for byte (zlib's deflate at `level`, as zlib.compressobj(level)),
    compressed on a thread beside the caller when threads_of(threads) is 2 or more, else in write(). close() raises
    MapError (the file removed) when not every row was written or a write failed; abort() removes the file. by: 'C++
    (n threads)'; map_stats: what close() reported."""

    def __init__(self, path, W, H, level=1, threads=None):
        self.path, self.W, self.H = str(path), int(W), int(H)
        self.threads = threads_of(threads)
        self.by = f"C++ ({self.threads} thread{'s' if self.threads != 1 else ''})"
        self.map_stats = {}
        self._dll = loaded()
        self._h = None
        self._msg = ctypes.create_string_buffer(MESSAGE_BYTES)
        h = c_void_p()
        rc = self._dll.fss_ao_map_open(self.path, self.W, self.H, int(level), self.threads, byref(h), self._msg,
                                       MESSAGE_BYTES)
        if rc != 0:
            raise MapError(f'writing the map: {_png_text(rc, self._msg)}')
        self._h = h

    def write(self, block):
        b = np.asarray(block)
        if not b.shape[0]:
            return
        if b.ndim != 2 or b.shape[1] != self.W:
            raise ValueError(f'{self.path}: rows of shape {b.shape[1:]}, the map is {self.W} wide')
        if b.dtype != np.int32 or b.strides[1] != 4 or b.strides[0] % 4:
            b = np.ascontiguousarray(b, '<i4')
        if self._h is None:
            raise MapError(f'writing the map: {self.path}: the writer is closed')
        stride = b.strides[0] // 4 if b.shape[0] > 1 else self.W
        rc = self._dll.fss_ao_map_write(self._h, _addr(b) if b.size else None, int(b.shape[0]), int(stride),
                                        self._msg, MESSAGE_BYTES)
        if rc != 0:
            raise MapError(f'writing the map: {_png_text(rc, self._msg)}')

    def close(self):
        if self._h is None:
            raise MapError(f'writing the map: {self.path}: the writer is closed')
        st = MapStats()
        h, self._h = self._h, None
        rc = self._dll.fss_ao_map_close(h, byref(st), self._msg, MESSAGE_BYTES)
        self.map_stats = st.as_dict()
        if rc != 0:
            raise MapError(f'writing the map: {_png_text(rc, self._msg)}')

    def abort(self):
        h, self._h = self._h, None
        if h:
            self._dll.fss_ao_map_abort(h)

    def __del__(self):
        try:
            self.abort()
        except Exception:
            pass


# ---------------------------------------------------------------------------------------------------------------------
# Refresh's scene rule and mesh hash (interface version 6, bake-post-native journal Sessions 4 and 5), for
# ao_bake_store._rule_tools (near, against) and ao_bake_core.mesh_hash
# ---------------------------------------------------------------------------------------------------------------------

def _p(a):
    return _addr(a) if a.size else None


class SceneRule:
    """One Refresh pass's candidates as fss_ao_scene_near and fss_ao_scene_moves read them: corners (n, 8, 3) their
    bound_box, now (n, 4, 4) their matrix_world after motion(), M (n, poses, 4, 4) and moving (n,) motion()'s,
    occ_rows (k,) the occluders' rows in the order of their names; ortho_tol and motion_tol: ao_bake_store's ORTHO_TOL
    and MOTION_TOL. stats: what the last near() or moves() reported (how close a gap came to its distance)."""

    def __init__(self, corners, now, M, moving, occ_rows, ortho_tol, motion_tol):
        n = len(corners)
        P = int(np.shape(M)[1]) if n else 1
        self.corners = np.ascontiguousarray(np.asarray(corners, np.float64).reshape(n, 8, 3))
        self.now = np.ascontiguousarray(np.asarray(now, np.float64).reshape(n, 4, 4))
        self.M = np.ascontiguousarray(np.asarray(M, np.float64).reshape(n, P, 4, 4))
        self.moving = np.ascontiguousarray(np.asarray(moving, bool).reshape(n)).view(np.uint8)
        self.occ_rows = np.ascontiguousarray(np.asarray(occ_rows, np.int64).reshape(-1))
        self.struct = SceneStruct(n_rows=n, n_poses=P, M=_p(self.M), moving=_p(self.moving), now=_p(self.now),
                                  corners=_p(self.corners), n_occ=len(self.occ_rows), occ_rows=_p(self.occ_rows),
                                  ortho_tol=float(ortho_tol), motion_tol=float(motion_tol))
        self.stats = {}

    def near(self, rows, which, distance, self_occ, threads=None):
        """fss_ao_scene_near: for each object (its row, which 0 'now' or 1 'swept', its distance, its index among the
        occluders or -1) the occluders kept (indices among them, in their order) and their gaps (m)."""
        dll = loaded()
        r = np.ascontiguousarray(rows, np.int64).reshape(-1)
        n = len(r)
        w = np.ascontiguousarray(which, np.int64).reshape(n)
        d = np.ascontiguousarray(distance, np.float64).reshape(n)
        s = np.ascontiguousarray(self_occ, np.int64).reshape(n)
        offsets = np.zeros(n + 1, np.int64)
        cap = max(64, 8 * n)
        while True:
            occ = np.empty(cap, np.int64)
            gap = np.empty(cap, np.float64)
            st = NearStats()
            rc = dll.fss_ao_scene_near(byref(self.struct), n, _p(r), _p(w), _p(d), _p(s), threads_of(threads),
                                       _addr(offsets), _addr(occ), _addr(gap), cap, byref(st))
            if rc == E_SPACE and int(offsets[n]) > cap:
                cap = int(offsets[n])
                continue
            _check(rc, 'scene_near')
            break
        self.stats = dict(closest_world=st.closest_world, closest_own=st.closest_own, within=int(st.within),
                          world_tests=int(st.world_tests), own_tests=int(st.own_tests))
        return [(occ[offsets[q]:offsets[q + 1]], gap[offsets[q]:offsets[q + 1]]) for q in range(n)]

    def moves(self, pairs, threads=None):
        """fss_ao_scene_moves: for each (row a, row b) pair whether b moves against a (decision 59), as a bool array,
        and which pairs could not be told (a's matrix at the current frame singular: np.linalg.inv raises for them, as
        the Python code did). The inverse of each a's matrix is numpy's (np.linalg.inv), for the pairs where one
        moves."""
        dll = loaded()
        pr = np.ascontiguousarray(np.asarray(pairs, np.int64).reshape(-1, 2))
        out = np.zeros(len(pr), np.uint8)
        singular = np.zeros(len(pr), bool)
        if not len(pr):
            return out.astype(bool), singular
        mv = self.moving.view(bool)
        need = np.unique(pr[mv[pr[:, 0]] | mv[pr[:, 1]], 0])
        inv = np.zeros((max(len(self.M), 1), 4, 4), np.float64)
        if len(need):
            try:
                inv[need] = np.linalg.inv(self.M[need, 0])
            except np.linalg.LinAlgError:  # one at a time: the singular ones marked
                bad = []
                for r in need.tolist():
                    try:
                        inv[r] = np.linalg.inv(self.M[r, 0])
                    except np.linalg.LinAlgError:
                        bad.append(r)
                singular = np.isin(pr[:, 0], bad) & (mv[pr[:, 0]] | mv[pr[:, 1]])
        closest = c_double(0.0)
        _check(dll.fss_ao_scene_moves(byref(self.struct), len(pr), _addr(pr), _addr(inv), threads_of(threads),
                                      _addr(out), byref(closest)), 'scene_moves')
        self.stats = dict(closest_motion=closest.value, pairs=len(pr), moving_pairs=int(
            (mv[pr[:, 0]] | mv[pr[:, 1]]).sum()))
        return out.astype(bool) & ~singular, singular


def mesh_hash(tris, co, cn, threads=None, impl=0):
    """fss_ao_mesh_hash: the SHA-1 (40 hex digits) of the triangles as int32, the positions as float32 and the corner
    normals rounded to 4 decimals as float32 (ao_bake_core.mesh_hash's bytes). impl 0: the CPU's SHA instructions when
    it has them; 1: plain C++; 2: the SHA instructions (CopyError without them)."""
    dll = loaded()
    t = np.ascontiguousarray(tris, np.int64)
    c = np.ascontiguousarray(co, np.float64)
    n = np.ascontiguousarray(cn, np.float64)
    out = (ctypes.c_uint8 * 20)()
    _check(dll.fss_ao_mesh_hash(_p(t), t.size, _p(c), c.size, _p(n), n.size, threads_of(threads), int(impl), out),
           'mesh_hash')
    return bytes(out).hex()


def own_boxes(lo, hi, mats, ortho_tol):
    """Tests: fss_ao_scene_boxes, the own boxes (centres, axes, halves, ok) of bounds lo, hi (..., 3) placed by
    mats (..., 4, 4)."""
    dll = loaded()
    mats = np.asarray(mats, np.float64)
    shape = mats.shape[:-2]
    m = np.ascontiguousarray(mats.reshape(-1, 4, 4))
    k = len(m)
    lo = np.ascontiguousarray(np.broadcast_to(np.asarray(lo, np.float64), shape + (3,)).reshape(k, 3))
    hi = np.ascontiguousarray(np.broadcast_to(np.asarray(hi, np.float64), shape + (3,)).reshape(k, 3))
    c, a, h, ok = np.empty((k, 3)), np.empty((k, 3, 3)), np.empty((k, 3)), np.empty(k, np.uint8)
    _check(dll.fss_ao_scene_boxes(k, _p(lo), _p(hi), _p(m), float(ortho_tol), _p(c), _p(a), _p(h), _p(ok)),
           'scene_boxes')
    return c.reshape(shape + (3,)), a.reshape(shape + (3, 3)), h.reshape(shape + (3,)), ok.astype(bool).reshape(shape)


def box_gaps(box, centres, axes, halves):
    """Tests: fss_ao_scene_gaps, the separating-axis gaps of the own box (centre, unit axes as columns, half sizes) to k
    others."""
    dll = loaded()
    c, U, e = (np.ascontiguousarray(x, np.float64) for x in box)
    cs = np.ascontiguousarray(centres, np.float64).reshape(-1, 3)
    k = len(cs)
    ax = np.ascontiguousarray(axes, np.float64).reshape(k, 3, 3)
    hs = np.ascontiguousarray(halves, np.float64).reshape(k, 3)
    out = np.empty(k, np.float64)
    _check(dll.fss_ao_scene_gaps(_addr(c), _addr(U), _addr(e), k, _p(cs), _p(ax), _p(hs), _p(out)), 'scene_gaps')
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Test entry points (tests/test_ao_copy_native.py)
# ---------------------------------------------------------------------------------------------------------------------

def read(prep, tri_normal, surface_cos, surface, tri_ids, bary):
    """copy_master's read() in C++: (values, clamped mask)."""
    dll = loaded()
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
    dll = loaded()
    uv = np.ascontiguousarray(uvpx, np.float64)
    own = np.empty((gh * level, gw * level), np.int64)
    _check(dll.fss_ao_copy_raster(_addr(uv), len(uv), int(gx), int(gy), int(gw), int(gh), int(level), _addr(own)),
           'raster')
    return own


def total(a):
    """np.add.reduce of a float64 array as the DLL computes it."""
    a = np.ascontiguousarray(a, np.float64)
    return float(load().fss_ao_copy_sum(_addr(a), len(a)))

