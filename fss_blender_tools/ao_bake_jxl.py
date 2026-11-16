"""AO Bake: masters as lossless JPEG XL through the reference library libjxl (auto-bake journal, decision 37).

The DLLs of a released libjxl (lib/jxl/windows-x64/, with their licences) are loaded with ctypes; no Python package
and no other software is needed. Both directions keep decision 33's paging, so memory does not grow with the master:

- Encode (Writer): the bake hands rows from the top, but libjxl's chunked frame input (JxlEncoderAddChunkedFrame)
  pulls rectangles of at most 2048 x 2048 px in its own order, after the frame is added. The rows therefore go to a
  raw uint16 scratch file beside the master (<path>.raw, 2 bytes per pixel, deleted afterwards), and close() encodes
  from it: each rectangle the encoder asks for is read from the file, and an output processor writes the codestream
  to the file as it comes (seek-based streaming output, OUTPUT_MODE 1).
- Decode (decode_rows): the file is fed to JxlDecoder a chunk at a time; the decoded pixels arrive through the
  image-out callback as pieces of rows, in the decoder's order (not top to bottom); the caller's sink places them.

16-bit grey only (one colour channel, no alpha), as the masters are (decision 18). If the DLLs cannot be loaded
(another OS, a missing file, or FSS_AO_BAKE_NO_JXL set for tests), available() is False and the AO Bake is not
available (apply-native-copy decision 6: the panel says why, the bake and Apply refuse).
"""

import ctypes
import os
import sys
import threading
import time
from ctypes import (CFUNCTYPE, POINTER, Structure, byref, c_double, c_float, c_int, c_size_t, c_uint8, c_uint32,
                    c_uint64, c_void_p)

import numpy as np

LIB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib', 'jxl', 'windows-x64')
DLLS = ('brotlicommon.dll', 'brotlidec.dll', 'brotlienc.dll', 'jxl_cms.dll', 'jxl.dll', 'jxl_threads.dll')
DISABLE_ENV = 'FSS_AO_BAKE_NO_JXL'  # tests: behave as if the library could not be loaded
EFFORT = 7  # libjxl's effort (1 fastest .. 10). Session 27, the 214 Mpx floor: efforts 1 and 3 larger than the PNG,
#             5 40 % smaller, 7 43 % smaller in 3.9 s and 0.16 GB peak
CPUS = os.cpu_count() or 2  # the PC's logical processors
THREADS = max(2, CPUS // 2)  # Threads 0, Auto (apply-native-copy decision 5): half the logical processors, at least 2
READ_CHUNK = 4 << 20  # bytes of the file handed to the decoder at a time

# ---------------------------------------------------------------------------------------------------------------------
# The C API (jxl/types.h, codestream_header.h, color_encoding.h, encode.h, decode.h of libjxl 0.12)
# ---------------------------------------------------------------------------------------------------------------------

JXL_TYPE_UINT16 = 3
JXL_LITTLE_ENDIAN = 1
JXL_ENC_SUCCESS, JXL_ENC_ERROR = 0, 1
JXL_DEC_SUCCESS, JXL_DEC_ERROR, JXL_DEC_NEED_MORE_INPUT = 0, 1, 2
JXL_DEC_NEED_IMAGE_OUT_BUFFER = 5
JXL_DEC_BASIC_INFO, JXL_DEC_FULL_IMAGE = 0x40, 0x1000
JXL_DEC_COLOR_ENCODING, JXL_DEC_FRAME = 0x100, 0x400
SETTING_EFFORT = 0
SETTING_MODULAR_GROUP_SIZE = 26
SETTING_MODULAR_PREDICTOR = 27
SETTING_MODULAR_MA_TREE_LEARNING_PERCENT = 28
SETTING_MODULAR_NB_PREV_CHANNELS = 29
SETTING_BUFFERING = 34
SETTING_OUTPUT_MODE = 40
# the encoder's options besides effort and lossless
OPTIONS = {
    SETTING_BUFFERING: 2,  # chunked input streamed (2: streaming above a lower size threshold than 1)
    SETTING_OUTPUT_MODE: 1,  # seek-based streaming output: group data first, then the header and TOC written back
}


class PixelFormat(Structure):
    _fields_ = [('num_channels', c_uint32), ('data_type', c_int), ('endianness', c_int), ('align', c_size_t)]


class BasicInfo(Structure):
    _fields_ = [('have_container', c_int), ('xsize', c_uint32), ('ysize', c_uint32), ('bits_per_sample', c_uint32),
                ('exponent_bits_per_sample', c_uint32), ('intensity_target', c_float), ('min_nits', c_float),
                ('relative_to_max_display', c_int), ('linear_below', c_float), ('uses_original_profile', c_int),
                ('have_preview', c_int), ('have_animation', c_int), ('orientation', c_int),
                ('num_color_channels', c_uint32), ('num_extra_channels', c_uint32), ('alpha_bits', c_uint32),
                ('alpha_exponent_bits', c_uint32), ('alpha_premultiplied', c_int), ('preview_xsize', c_uint32),
                ('preview_ysize', c_uint32), ('tps_numerator', c_uint32), ('tps_denominator', c_uint32),
                ('num_loops', c_uint32), ('have_timecodes', c_int), ('intrinsic_xsize', c_uint32),
                ('intrinsic_ysize', c_uint32), ('padding', c_uint8 * 100)]


class ColorEncoding(Structure):
    _fields_ = [('color_space', c_int), ('white_point', c_int), ('white_point_xy', c_double * 2),
                ('primaries', c_int), ('primaries_red_xy', c_double * 2), ('primaries_green_xy', c_double * 2),
                ('primaries_blue_xy', c_double * 2), ('transfer_function', c_int), ('gamma', c_double),
                ('rendering_intent', c_int)]


GET_BUFFER = CFUNCTYPE(c_void_p, c_void_p, POINTER(c_size_t))
RELEASE_OUT = CFUNCTYPE(None, c_void_p, c_size_t)
SEEK = CFUNCTYPE(None, c_void_p, c_uint64)
SET_FINALIZED = CFUNCTYPE(None, c_void_p, c_uint64)
GET_FORMAT = CFUNCTYPE(None, c_void_p, POINTER(PixelFormat))
GET_DATA = CFUNCTYPE(c_void_p, c_void_p, c_size_t, c_size_t, c_size_t, c_size_t, POINTER(c_size_t))
GET_EC_FORMAT = CFUNCTYPE(None, c_void_p, c_size_t, POINTER(PixelFormat))
GET_EC_DATA = CFUNCTYPE(c_void_p, c_void_p, c_size_t, c_size_t, c_size_t, c_size_t, c_size_t, POINTER(c_size_t))
RELEASE_IN = CFUNCTYPE(None, c_void_p, c_void_p)
IMAGE_OUT = CFUNCTYPE(None, c_void_p, c_size_t, c_size_t, c_size_t, c_void_p)


class OutputProcessor(Structure):
    _fields_ = [('opaque', c_void_p), ('get_buffer', GET_BUFFER), ('release_buffer', RELEASE_OUT), ('seek', SEEK),
                ('set_finalized_position', SET_FINALIZED)]


class ChunkedInput(Structure):
    _fields_ = [('opaque', c_void_p), ('get_color_channels_pixel_format', GET_FORMAT),
                ('get_color_channel_data_at', GET_DATA), ('get_extra_channel_pixel_format', GET_EC_FORMAT),
                ('get_extra_channel_data_at', GET_EC_DATA), ('release_buffer', RELEASE_IN)]


_lib = dict(tried=False, jxl=None, threads=None, error=None, version=None)


def _signatures(jxl, thr):
    sig = {
        'JxlEncoderVersion': (c_uint32, []),
        'JxlEncoderCreate': (c_void_p, [c_void_p]),
        'JxlEncoderDestroy': (None, [c_void_p]),
        'JxlEncoderSetParallelRunner': (c_int, [c_void_p, c_void_p, c_void_p]),
        'JxlEncoderInitBasicInfo': (None, [POINTER(BasicInfo)]),
        'JxlEncoderSetBasicInfo': (c_int, [c_void_p, POINTER(BasicInfo)]),
        'JxlColorEncodingSetToLinearSRGB': (None, [POINTER(ColorEncoding), c_int]),
        'JxlEncoderSetColorEncoding': (c_int, [c_void_p, POINTER(ColorEncoding)]),
        'JxlEncoderFrameSettingsCreate': (c_void_p, [c_void_p, c_void_p]),
        'JxlEncoderSetFrameLossless': (c_int, [c_void_p, c_int]),
        'JxlEncoderFrameSettingsSetOption': (c_int, [c_void_p, c_int, ctypes.c_int64]),
        'JxlEncoderSetOutputProcessor': (c_int, [c_void_p, OutputProcessor]),
        'JxlEncoderAddChunkedFrame': (c_int, [c_void_p, c_int, ChunkedInput]),
        'JxlEncoderFlushInput': (c_int, [c_void_p]),
        'JxlEncoderGetError': (c_int, [c_void_p]),
        'JxlDecoderCreate': (c_void_p, [c_void_p]),
        'JxlDecoderDestroy': (None, [c_void_p]),
        'JxlDecoderSetParallelRunner': (c_int, [c_void_p, c_void_p, c_void_p]),
        'JxlDecoderSubscribeEvents': (c_int, [c_void_p, c_int]),
        'JxlDecoderSetInput': (c_int, [c_void_p, c_void_p, c_size_t]),
        'JxlDecoderReleaseInput': (c_size_t, [c_void_p]),
        'JxlDecoderCloseInput': (None, [c_void_p]),
        'JxlDecoderProcessInput': (c_int, [c_void_p]),
        'JxlDecoderGetBasicInfo': (c_int, [c_void_p, POINTER(BasicInfo)]),
        'JxlDecoderSetImageOutCallback': (c_int, [c_void_p, POINTER(PixelFormat), IMAGE_OUT, c_void_p]),
    }
    for name, (res, args) in sig.items():
        fn = getattr(jxl, name)
        fn.restype, fn.argtypes = res, args
    thr.JxlThreadParallelRunnerCreate.restype = c_void_p
    thr.JxlThreadParallelRunnerCreate.argtypes = [c_void_p, c_size_t]
    thr.JxlThreadParallelRunnerDestroy.restype = None
    thr.JxlThreadParallelRunnerDestroy.argtypes = [c_void_p]


def load():
    """(jxl, jxl_threads) as ctypes libraries, or None when they cannot be loaded (the reason in error())."""
    if _lib['tried']:
        return (_lib['jxl'], _lib['threads']) if _lib['jxl'] is not None else None
    _lib['tried'] = True
    try:
        if os.environ.get(DISABLE_ENV):
            raise OSError(f'{DISABLE_ENV} is set')
        if sys.platform != 'win32' or ctypes.sizeof(c_void_p) != 8:
            raise OSError(f'no JPEG XL library for {sys.platform} ({8 * ctypes.sizeof(c_void_p)}-bit) in the add-on')
        libs = {}
        for name in DLLS:  # dependencies first, each by its full path
            path = os.path.join(LIB_DIR, name)
            if not os.path.isfile(path):
                raise OSError(f'{path} missing')
            libs[name] = ctypes.CDLL(path)
        jxl, thr = libs['jxl.dll'], libs['jxl_threads.dll']
        _signatures(jxl, thr)
        v = jxl.JxlEncoderVersion()
        _lib.update(jxl=jxl, threads=thr, version=f'{v // 1000000}.{v // 1000 % 1000}.{v % 1000}', error=None)
        return jxl, thr
    except (OSError, AttributeError) as exc:
        _lib.update(jxl=None, threads=None, error=f'{type(exc).__name__}: {exc}')
        return None


def available():
    return load() is not None


def error():
    """Why the library could not be loaded (None when it is loaded or was not tried)."""
    load()
    return _lib['error']


def version():
    load()
    return _lib['version']


def reset():
    """Forget the load attempt (tests switch FSS_AO_BAKE_NO_JXL); the loaded DLLs stay in the process."""
    _lib.update(tried=False, jxl=None, threads=None, error=None, version=None)


class JxlError(OSError):
    """The library is not loaded, or a file is not encoded or decoded (an OSError, so Apply reports it per set)."""


def threads_of(threads):
    """The threads of a job: 0 or None Auto (THREADS), else the number asked, at most the PC's logical processors (the
    same rule as ao_bake_copy.threads_of)."""
    n = int(threads or 0)
    return THREADS if n <= 0 else max(1, min(n, max(CPUS, THREADS)))


def _runner(thr, threads):
    n = threads_of(threads)
    return thr.JxlThreadParallelRunnerCreate(None, n), n


# ---------------------------------------------------------------------------------------------------------------------
# Encode
# ---------------------------------------------------------------------------------------------------------------------

def encode_raw(raw_path, W, H, out_path, effort=EFFORT, threads=THREADS, stats=None):
    """Encodes the raw uint16 file raw_path (H rows of W little-endian values, the top first) as a lossless 16-bit
    grey JPEG XL at out_path. Memory: the encoder's own (it streams in rectangles of at most 2048 px) and one
    rectangle at a time read from the file. Returns stats (seconds, bytes, regions, effort, threads)."""
    libs = load()
    if libs is None:
        raise JxlError(f'JPEG XL library not loaded: {_lib["error"]}')
    jxl, thr = libs
    W, H = int(W), int(H)
    stats = stats if stats is not None else {}
    t0 = time.time()
    rowbytes = 2 * W
    fin = open(raw_path, 'rb')
    fout = open(out_path, 'wb')
    held = {}
    errors = []
    lock = threading.Lock()
    out = dict(pos=0, end=0, buf=None)
    regions = [0]

    def get_format(_opaque, fmt):
        fmt[0].num_channels, fmt[0].data_type, fmt[0].endianness, fmt[0].align = 1, JXL_TYPE_UINT16, \
            JXL_LITTLE_ENDIAN, 0

    def get_data(_opaque, xpos, ypos, xsize, ysize, row_offset):
        try:
            a = np.empty((ysize, xsize), '<u2')
            with lock:
                if xsize == W:
                    fin.seek(ypos * rowbytes)
                    fin.readinto(memoryview(a).cast('B'))
                else:
                    for k in range(ysize):
                        fin.seek((ypos + k) * rowbytes + 2 * xpos)
                        fin.readinto(memoryview(a[k]).cast('B'))
                regions[0] += 1
                addr = a.ctypes.data
                held[addr] = a
            row_offset[0] = 2 * xsize
            return addr
        except Exception as exc:  # noqa: BLE001 (an exception cannot cross into the library)
            errors.append(exc)
            a = np.zeros((max(1, ysize), max(1, xsize)), '<u2')
            with lock:
                held[a.ctypes.data] = a
            row_offset[0] = 2 * xsize
            return a.ctypes.data

    def get_ec_format(_opaque, _i, fmt):
        get_format(None, fmt)

    def get_ec_data(_opaque, _i, xpos, ypos, xsize, ysize, row_offset):
        errors.append(JxlError('extra channel asked for'))
        return get_data(None, xpos, ypos, xsize, ysize, row_offset)

    def release_in(_opaque, buf):
        with lock:
            held.pop(buf, None)

    def get_buffer(_opaque, size):
        n = max(int(size[0]), 1 << 16)
        if out['buf'] is None or len(out['buf']) < n:
            out['buf'] = (ctypes.c_ubyte * n)()
        size[0] = len(out['buf'])
        return ctypes.addressof(out['buf'])

    def release_out(_opaque, written):
        try:
            if written:
                fout.seek(out['pos'])
                fout.write(memoryview(out['buf']).cast('B')[:written])
                out['pos'] += written
                out['end'] = max(out['end'], out['pos'])
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    def seek(_opaque, position):
        out['pos'] = int(position)

    def set_finalized(_opaque, _position):
        pass

    cb = dict(get_format=GET_FORMAT(get_format), get_data=GET_DATA(get_data), get_ec_format=GET_EC_FORMAT(get_ec_format),
              get_ec_data=GET_EC_DATA(get_ec_data), release_in=RELEASE_IN(release_in), get_buffer=GET_BUFFER(get_buffer),
              release_out=RELEASE_OUT(release_out), seek=SEEK(seek), set_finalized=SET_FINALIZED(set_finalized))
    enc = jxl.JxlEncoderCreate(None)
    runner, n_threads = _runner(thr, threads)
    try:
        def check(status, what):
            if status != JXL_ENC_SUCCESS:
                raise JxlError(f'{what} failed (encoder error {jxl.JxlEncoderGetError(enc)})')
        check(jxl.JxlEncoderSetParallelRunner(enc, ctypes.cast(thr.JxlThreadParallelRunner, c_void_p), runner),
              'JxlEncoderSetParallelRunner')
        info = BasicInfo()
        jxl.JxlEncoderInitBasicInfo(byref(info))
        info.xsize, info.ysize = W, H
        info.bits_per_sample, info.exponent_bits_per_sample = 16, 0
        info.num_color_channels, info.num_extra_channels, info.alpha_bits = 1, 0, 0
        info.uses_original_profile = 1
        check(jxl.JxlEncoderSetBasicInfo(enc, byref(info)), 'JxlEncoderSetBasicInfo')
        ce = ColorEncoding()
        jxl.JxlColorEncodingSetToLinearSRGB(byref(ce), 1)  # grey, linear: the AO values as they are
        check(jxl.JxlEncoderSetColorEncoding(enc, byref(ce)), 'JxlEncoderSetColorEncoding')
        fs = jxl.JxlEncoderFrameSettingsCreate(enc, None)
        check(jxl.JxlEncoderSetFrameLossless(fs, 1), 'JxlEncoderSetFrameLossless')
        check(jxl.JxlEncoderFrameSettingsSetOption(fs, SETTING_EFFORT, int(effort)), 'effort')
        for option, value in OPTIONS.items():
            check(jxl.JxlEncoderFrameSettingsSetOption(fs, option, int(value)), f'option {option}')
        proc = OutputProcessor(None, cb['get_buffer'], cb['release_out'], cb['seek'], cb['set_finalized'])
        check(jxl.JxlEncoderSetOutputProcessor(enc, proc), 'JxlEncoderSetOutputProcessor')
        src = ChunkedInput(None, cb['get_format'], cb['get_data'], cb['get_ec_format'], cb['get_ec_data'],
                           cb['release_in'])
        check(jxl.JxlEncoderAddChunkedFrame(fs, 1, src), 'JxlEncoderAddChunkedFrame')
        if errors:
            raise JxlError(f'reading {raw_path}: {errors[0]}')
        fout.truncate(out['end'])
    finally:
        jxl.JxlEncoderDestroy(enc)
        thr.JxlThreadParallelRunnerDestroy(runner)
        fin.close()
        fout.close()
        held.clear()
    stats.update(seconds=round(time.time() - t0, 3), bytes=os.path.getsize(out_path), regions=regions[0],
                 effort=int(effort), threads=n_threads, library=_lib['version'])
    return stats


class Writer:
    """A 16-bit grey JPEG XL master written from rows handed top first (as ao_bake_copy.PngWriter takes them): the rows go to
    <path>.raw, close() encodes it into path and deletes it, abort() deletes both."""

    def __init__(self, path, W, H, effort=EFFORT, threads=THREADS):
        if not available():
            raise JxlError(f'JPEG XL library not loaded: {_lib["error"]}')
        self.path, self.W, self.H, self.effort, self.threads = path, int(W), int(H), effort, threads
        self.raw = path + '.raw'
        self.rows = 0
        self.stats = {}
        self.f = open(self.raw, 'wb')

    def write(self, block):
        block = np.ascontiguousarray(block, dtype='<u2')
        if block.ndim == 3:
            block = np.ascontiguousarray(block[:, :, 0])
        if not block.shape[0]:
            return
        if block.shape[1] != self.W:
            raise ValueError(f'{self.path}: a row of {block.shape[1]} px, the image is {self.W} px wide')
        self.f.write(block.tobytes())
        self.rows += block.shape[0]

    def close(self):
        self.f.close()
        try:
            if self.rows != self.H:
                raise ValueError(f'{self.path}: {self.rows} of {self.H} rows written')
            self.stats['scratch_bytes'] = os.path.getsize(self.raw)
            encode_raw(self.raw, self.W, self.H, self.path, self.effort, self.threads, self.stats)
        finally:
            _remove(self.raw)

    def abort(self):
        if not self.f.closed:
            self.f.close()
        _remove(self.raw)
        _remove(self.path)


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


# ---------------------------------------------------------------------------------------------------------------------
# Decode
# ---------------------------------------------------------------------------------------------------------------------

def is_jxl(path):
    try:
        with open(path, 'rb') as f:
            head = f.read(12)
    except OSError:
        return False
    return head[:2] == b'\xff\x0a' or head == b'\x00\x00\x00\x0cJXL \r\n\x87\n'


def decode_rows(path, sink, threads=THREADS, on_info=None):
    """Decodes path (a 16-bit grey JPEG XL) piece by piece: sink(x, y, n, address) gets n uint16 values of row y
    (from the top) starting at x, valid only during the call, in the decoder's order and possibly from several
    threads (one call at a time: the callback holds a lock). on_info(W, H) is called first. The file is read
    READ_CHUNK bytes at a time; the image is never held whole here."""
    libs = load()
    if libs is None:
        raise JxlError(f'JPEG XL library not loaded: {_lib["error"]}')
    jxl, thr = libs
    lock = threading.Lock()
    errors = []
    size = {}

    def on_pixels(_opaque, x, y, n, pixels):
        try:
            with lock:
                sink(x, y, n, pixels)
        except Exception as exc:  # noqa: BLE001 (an exception cannot cross into the library)
            if not errors:
                errors.append(exc)

    callback = IMAGE_OUT(on_pixels)
    dec = jxl.JxlDecoderCreate(None)
    runner = _runner(thr, threads)[0] if threads and threads > 0 else None  # 0: decoded in this thread
    f = open(path, 'rb')
    try:
        if runner is not None and jxl.JxlDecoderSetParallelRunner(
                dec, ctypes.cast(thr.JxlThreadParallelRunner, c_void_p), runner):
            raise JxlError('JxlDecoderSetParallelRunner failed')
        if jxl.JxlDecoderSubscribeEvents(dec, JXL_DEC_BASIC_INFO | JXL_DEC_FULL_IMAGE):
            raise JxlError('JxlDecoderSubscribeEvents failed')
        buf = None
        held = b''
        eof = False
        fmt = PixelFormat(1, JXL_TYPE_UINT16, JXL_LITTLE_ENDIAN, 0)
        while True:
            status = jxl.JxlDecoderProcessInput(dec)
            if status == JXL_DEC_NEED_MORE_INPUT:
                rest = jxl.JxlDecoderReleaseInput(dec) if buf is not None else 0
                if eof:
                    raise JxlError(f'{path}: the file ends before the image')
                more = f.read(READ_CHUNK)
                if not more:
                    eof = True
                    jxl.JxlDecoderCloseInput(dec)
                    data = held[len(held) - rest:] if rest else b''
                else:
                    data = (held[len(held) - rest:] if rest else b'') + more
                held = data
                buf = ctypes.create_string_buffer(data, len(data)) if data else ctypes.create_string_buffer(1)
                if jxl.JxlDecoderSetInput(dec, buf, len(data)):
                    raise JxlError('JxlDecoderSetInput failed')
            elif status == JXL_DEC_BASIC_INFO:
                info = BasicInfo()
                if jxl.JxlDecoderGetBasicInfo(dec, byref(info)):
                    raise JxlError('JxlDecoderGetBasicInfo failed')
                if info.num_color_channels != 1 or info.num_extra_channels or info.bits_per_sample != 16:
                    raise JxlError(f'{path}: {info.num_color_channels} colour channel(s), {info.num_extra_channels} '
                                   f'extra, {info.bits_per_sample} bits: not a 16-bit grey master')
                size.update(W=int(info.xsize), H=int(info.ysize))
                if on_info is not None:
                    on_info(size['W'], size['H'])
            elif status == JXL_DEC_NEED_IMAGE_OUT_BUFFER:
                if jxl.JxlDecoderSetImageOutCallback(dec, byref(fmt), callback, None):
                    raise JxlError('JxlDecoderSetImageOutCallback failed')
            elif status == JXL_DEC_FULL_IMAGE:
                if errors:
                    raise errors[0]
            elif status == JXL_DEC_SUCCESS:
                break
            elif status == JXL_DEC_ERROR:
                raise JxlError(f'{path}: not decoded (decoder error)')
            else:
                raise JxlError(f'{path}: unexpected decoder status {status}')
        if errors:
            raise errors[0]
    finally:
        f.close()
        jxl.JxlDecoderDestroy(dec)
        if runner is not None:
            thr.JxlThreadParallelRunnerDestroy(runner)
    return size['W'], size['H']


def read_whole(path, threads=THREADS):
    """The whole image as (H, W) uint16, row 0 = the top (tests and small masters)."""
    st = {}

    def on_info(W, H):
        st['a'] = np.zeros((H, W), np.uint16)
        st['base'] = st['a'].ctypes.data
        st['W'] = W

    def sink(x, y, n, addr):
        ctypes.memmove(st['base'] + 2 * (y * st['W'] + x), addr, 2 * n)
    decode_rows(path, sink, threads, on_info)
    return st['a']


def info(path):
    """(W, H) of a JPEG XL file, read from its header (decoding stops after the basic info)."""
    libs = load()
    if libs is None:
        raise JxlError(f'JPEG XL library not loaded: {_lib["error"]}')
    jxl, _thr = libs
    dec = jxl.JxlDecoderCreate(None)
    try:
        jxl.JxlDecoderSubscribeEvents(dec, JXL_DEC_BASIC_INFO)
        with open(path, 'rb') as f:
            data = f.read(1 << 16)
        buf = ctypes.create_string_buffer(data, len(data))
        jxl.JxlDecoderSetInput(dec, buf, len(data))
        jxl.JxlDecoderCloseInput(dec)
        if jxl.JxlDecoderProcessInput(dec) != JXL_DEC_BASIC_INFO:
            raise JxlError(f'{path}: no basic info')
        bi = BasicInfo()
        jxl.JxlDecoderGetBasicInfo(dec, byref(bi))
        return int(bi.xsize), int(bi.ysize)
    finally:
        jxl.JxlDecoderDestroy(dec)
