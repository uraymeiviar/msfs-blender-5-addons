"""FSS OptiX in the add-on: the AO Baker (Glider's aobaker.exe, an OptiX baker of the AO masters) as the AO Bake's
second baker (OptiX baker journal docs/journal/20261114.optix-baker.md, decisions 21 to 25; Glider plan
doc/plan/PLAN-20261114.optix-ao-baker.md).

The baker ships in lib/ao_baker/windows-x64 (decision 21: aobaker.exe, its oidn folder, VERSION.txt), copied there by
tools/update-ao-baker.ps1. Baker starts it for a job and holds its channel; the runner gives it a master's scene and
bakes the master's tiles through it (bake_item), and the curvature and the OIDN denoise of the master run in it too
(write_curvature, denoise_master: the files as ao_bake_core's functions of those names write them).

The first part is the client end of the channel (Glider's src/platform/SharedChannel.h and the module's
AoBakeProtocol.h), in plain Python: ctypes for the Windows objects, mmap for the data blocks the client makes. The
channel fss-ao-baker.<name> is a block of shared memory with two rings of messages, one per direction, two auto-reset
events (<name>.s wakes the server, <name>.c the client) and a lock (<name>.lock) the client holds while connected.
Heads and tails are u64 byte counts written as aligned 8-byte stores (atomic on x64, whose stores keep their order:
the payload is visible before the head that publishes it). That part imports neither bpy nor the add-on, so the tests
load this file on its own (tests/ao_baker_client.py).
"""
import ctypes
import mmap
import os
import struct
import subprocess
import time
from ctypes import wintypes

PREFIX = 'fss-ao-baker.'
MAGIC = 0x314E414843535346  # "FSSCHAN1"
LAYOUT = 1
HEADER_BYTES = 4096
MSG_HEADER = 16
OFF_MAGIC, OFF_LAYOUT, OFF_SERVER_PID, OFF_CLIENT_PID, OFF_RING = 0, 8, 16, 20, 24
OFF_TO_SERVER_HEAD, OFF_TO_SERVER_TAIL, OFF_TO_CLIENT_HEAD, OFF_TO_CLIENT_TAIL = 64, 128, 192, 256

PROTOCOL = 1
PROBE_INPUT = 12345
HELLO, READY, JOB_INFO, ECHO, ECHO_DONE, CANCEL, CANCELLED, ERROR, BYE = range(1, 10)
LOAD_SCENE, SCENE_READY, BAKE_TILE, PROGRESS, TILE_DONE, RELEASE_SCENE = range(10, 16)
CURV_LOAD, CURV_READY, CURV_ROWS, CURV_DONE, CURV_RELEASE = range(16, 21)
DN_LOAD, DN_READY, DN_WINDOW, DN_DONE, DN_RELEASE = range(21, 26)
DEVICE_STATES = {0: 'Ok', 1: 'NoDriver', 2: 'NoOptix', 3: 'NoDevice', 4: 'Failed'}
ERROR_CODES = {1: 'UnknownMessage', 2: 'BadPayload', 3: 'BlockMissing', 4: 'BlockTooSmall', 5: 'BadScene', 6: 'OutOfMemory',
               7: 'NoDevice', 8: 'UnknownScene', 9: 'NotSupported', 10: 'DeviceFailed'}
HELLO_FMT = '<II64s'
READY_FMT = '<IIIIIIIIQQ128s128s'
JOB_INFO_FMT = '<II128s'
ECHO_FMT = '<Q64s'
ECHO_DONE_FMT = '<QQQII'
ERROR_FMT = '<II248s'
LOAD_SCENE_FMT = '<IIQ64s'
SCENE_READY_FMT = '<IIIIIIQQ'
BAKE_TILE_FMT = '<IIIIIIIIQQQ64s'
PROGRESS_FMT = '<IIIIIIQQ'
TILE_DONE_FMT = '<IIIIQQQQ'
RELEASE_SCENE_FMT = '<II'
CURV_LOAD_FMT = '<IIQ64s'
CURV_READY_FMT = '<IIIIQQ'
CURV_ROWS_FMT = '<IIIIQQ64s'
CURV_DONE_FMT = '<IIIIQQ'
CURV_RELEASE_FMT = '<II'
DN_LOAD_FMT = '<IIQ64s'
DN_READY_FMT = '<IIIIIIQ128s'
DN_WINDOW_FMT = '<IIIIIfQQQ64s'
DN_DONE_FMT = '<IIIIQdQQQ'
DN_RELEASE_FMT = '<II'
NO_OFFSET = 0xFFFFFFFFFFFFFFFF

# The scene block (AoBakeProtocol.h): the header, then the sections at offsets that are multiples of 8
SCENE_MAGIC = 0x3143534F41535346  # "FSSAOSC1"
SCENE_VERSION = 1
SCENE_HEADER_FMT = '<QIIf' + 'I' * 11 + 'Q' * 9 + 'II' + '112x'
SCENE_HEADER_BYTES = 256
NO_TRIANGLE = 0xFFFFFFFF
COMBINES = {'AVERAGE': 0, 'LIGHTEST': 1, 'DARKEST': 2, 'ONE': 0}  # One Instance: one copy, averaged
IDENTITY = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0)

# The curvature block (AoBakeProtocol.h, CurvatureHeader)
CURV_MAGIC = 0x3156525543535346  # "FSSCURV1"
CURV_VERSION = 1
CURV_HEADER_FMT = '<QIIIIIIdII' + 'Q' * 5 + '48x'
CURV_HEADER_BYTES = 136

# The denoise block (AoBakeProtocol.h, DenoiseHeader)
DN_MAGIC = 0x314F4E4544535346  # "FSSDENO1"
DN_VERSION = 1
DN_HEADER_FMT = '<QIIIIIIII' + 'Q' * 4 + '56x'
DN_HEADER_BYTES = 128
DN_DEVICES = {'GPU': 0, 'CPU': 1}
DN_FLAG_PLAIN = 1
DN_FLAG_NO_BOUND = 2
DN_WINDOW_PIXELS = 16 * 1024 * 1024

_k32 = ctypes.WinDLL('kernel32', use_last_error=True)
_k32.OpenFileMappingW.restype = wintypes.HANDLE
_k32.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
_k32.MapViewOfFile.restype = ctypes.c_void_p
_k32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
_k32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
_k32.OpenEventW.restype = wintypes.HANDLE
_k32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
_k32.OpenMutexW.restype = wintypes.HANDLE
_k32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
_k32.OpenProcess.restype = wintypes.HANDLE
_k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_k32.SetEvent.argtypes = [wintypes.HANDLE]
_k32.ReleaseMutex.argtypes = [wintypes.HANDLE]
_k32.CloseHandle.argtypes = [wintypes.HANDLE]
_k32.WaitForSingleObject.restype = wintypes.DWORD
_k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_k32.WaitForMultipleObjects.restype = wintypes.DWORD
_k32.WaitForMultipleObjects.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE), wintypes.BOOL, wintypes.DWORD]


class _MBI(ctypes.Structure):
    _fields_ = [('BaseAddress', ctypes.c_void_p), ('AllocationBase', ctypes.c_void_p), ('AllocationProtect', wintypes.DWORD),
                ('PartitionId', wintypes.WORD), ('RegionSize', ctypes.c_size_t), ('State', wintypes.DWORD),
                ('Protect', wintypes.DWORD), ('Type', wintypes.DWORD)]


_k32.VirtualQuery.restype = ctypes.c_size_t
_k32.VirtualQuery.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MBI), ctypes.c_size_t]

FILE_MAP_ALL_ACCESS = 0xF001F
EVENT_MODIFY_STATE, MUTEX_MODIFY_STATE, SYNCHRONIZE = 0x2, 0x1, 0x100000
WAIT_OBJECT_0, WAIT_ABANDONED, WAIT_TIMEOUT = 0, 0x80, 0x102


class ChannelError(RuntimeError):
    pass


class PeerGone(ChannelError):
    """The server's process ended."""


def _pad(n):
    return (MSG_HEADER + n + 15) & ~15


def text(raw):
    return raw.split(b'\0', 1)[0].decode('utf-8', 'replace')


def make_block(name, size):
    """A data block the server opens by its name (Local\\<name>); an mmap, writable through numpy."""
    return mmap.mmap(-1, size, tagname='Local\\' + name)


def _dtypes():
    import numpy as np
    piece = np.dtype([('target', '<u4'), ('reserved', '<u4'), ('position', '<f4', (9,)), ('normal', '<f4', (9,)),
                      ('uv', '<f8', (6,))])
    instance = np.dtype([('mesh', '<u4'), ('is_target', '<u4'), ('transform', '<f4', (12,))])
    view = np.dtype([('transform', '<f4', (12,)), ('copy', '<u4'), ('samples', '<u4'), ('first', '<u4'), ('count', '<u4')])
    mesh = np.dtype([('first_vertex', '<u4'), ('vertex_count', '<u4'), ('first_triangle', '<u4'), ('triangle_count', '<u4')])
    assert (piece.itemsize, instance.itemsize, view.itemsize, mesh.itemsize) == (128, 56, 64, 16)
    return piece, instance, view, mesh


def pieces(target, positions, normals, uv):
    """The ScenePiece array of n pieces: target (n,) triangle of mesh 0 or NO_TRIANGLE, positions and normals (n, 3, 3),
    master UVs (n, 3, 2) in pixels (float64, kept exact)."""
    import numpy as np
    piece = _dtypes()[0]
    n = len(target)
    out = np.zeros(n, piece)
    out['target'] = np.asarray(target, dtype=np.int64).astype(np.uint32)
    out['position'] = np.asarray(positions, dtype=np.float32).reshape(n, 9)
    out['normal'] = np.asarray(normals, dtype=np.float32).reshape(n, 9)
    out['uv'] = np.asarray(uv, dtype=np.float64).reshape(n, 6)
    return out


def scene_block(name, meshes, instances, views, core, skirt, distance, falloff=False, combine='AVERAGE', seed=0,
                width=0, height=0):
    """Writes a scene block and returns (mmap, bytes). meshes: [(positions (v, 3), triangles (t, 3))], mesh 0 the target;
    instances: [(mesh, is_target, 3 x 4 transform)]; views: [(3 x 4 target transform, copy, samples, [instance indices])];
    core and skirt: pieces() arrays; width x height: the master's size, for the baker window's preview (0 x 0: none)."""
    import numpy as np
    _piece, instance_dt, view_dt, mesh_dt = _dtypes()
    pos = [np.asarray(p, dtype=np.float32).reshape(-1, 3) for p, _t in meshes]
    tri = [np.asarray(t, dtype=np.uint32).reshape(-1, 3) for _p, t in meshes]
    mesh_arr = np.zeros(len(meshes), mesh_dt)
    v = t = 0
    for k in range(len(meshes)):
        mesh_arr[k] = (v, len(pos[k]), t, len(tri[k]))
        v += len(pos[k])
        t += len(tri[k])
    inst_arr = np.zeros(len(instances), instance_dt)
    for k, (m, is_target, tr) in enumerate(instances):
        inst_arr[k] = (m, 1 if is_target else 0, np.asarray(tr, dtype=np.float32).ravel())
    view_arr = np.zeros(len(views), view_dt)
    lists = []
    for k, (tr, copy, samples, members) in enumerate(views):
        view_arr[k] = (np.asarray(tr, dtype=np.float32).ravel(), copy, samples, sum(len(x) for x in lists), len(members))
        lists.append(list(members))
    view_inst = np.array([i for x in lists for i in x], dtype=np.uint32)
    sections = [mesh_arr, np.concatenate(pos) if pos else np.zeros((0, 3), np.float32),
                np.concatenate(tri) if tri else np.zeros((0, 3), np.uint32), inst_arr, view_arr, view_inst, core, skirt]
    offsets = []
    at = SCENE_HEADER_BYTES
    for s in sections:
        offsets.append(at)
        at = (at + s.nbytes + 7) & ~7
    total = at
    header = struct.pack(SCENE_HEADER_FMT, SCENE_MAGIC, SCENE_VERSION, SCENE_HEADER_BYTES, float(distance),
                         1 if falloff else 0, COMBINES[combine], int(seed) & 0xFFFFFFFF, len(meshes), v, t, len(instances),
                         len(views), len(view_inst), len(core), len(skirt), *offsets, total, int(width), int(height))
    block = make_block(name, total)
    block[:SCENE_HEADER_BYTES] = header
    for off, s in zip(offsets, sections):
        b = np.ascontiguousarray(s).view(np.uint8).ravel()
        block[off:off + len(b)] = b.tobytes()
    return block, total


def curvature_block(name, pos, tris, cn, muv, W, H, width, max_samples=512):
    """Writes a curvature block and returns (mmap, bytes): the master's triangles as write_curvature gets them, pos
    (V, 3), tris (T, 3), corner normals cn (T, 3, 3), master UVs muv (T, 3, 2) in pixels, the master's W x H, the
    curvature width (m)."""
    import numpy as np
    sections = [np.ascontiguousarray(pos, dtype=np.float64).reshape(-1, 3),
                np.ascontiguousarray(tris, dtype=np.uint32).reshape(-1, 3),
                np.ascontiguousarray(cn, dtype=np.float64).reshape(-1, 9),
                np.ascontiguousarray(muv, dtype=np.float64).reshape(-1, 6)]
    offsets = []
    at = CURV_HEADER_BYTES
    for x in sections:
        offsets.append(at)
        at = (at + x.nbytes + 7) & ~7
    header = struct.pack(CURV_HEADER_FMT, CURV_MAGIC, CURV_VERSION, CURV_HEADER_BYTES, len(sections[0]), len(sections[1]),
                         int(W), int(H), float(width), int(max_samples), 0, *offsets, at)
    assert len(header) == CURV_HEADER_BYTES
    block = make_block(name, at)
    block[:CURV_HEADER_BYTES] = header
    for off, x in zip(offsets, sections):
        b = x.view(np.uint8).ravel()
        block[off:off + len(b)] = b.tobytes()
    return block, at


def denoise_block(name, cn, muv, island, W, H, device='GPU', plain=False, no_bound=False):
    """Writes a denoise block and returns (mmap, bytes): the master layout's corner normals cn (T, 3, 3), master UVs muv
    (T, 3, 2) in pixels and island per face (T), in the layout's face order; the master's W x H; the OIDN device;
    plain: OIDN's result as it is (its local mean not restored, not bound to the noise); no_bound: the mean restored,
    not bound."""
    import numpy as np
    sections = [np.ascontiguousarray(cn, dtype=np.float64).reshape(-1, 9),
                np.ascontiguousarray(muv, dtype=np.float64).reshape(-1, 6),
                np.ascontiguousarray(island, dtype=np.uint32).ravel()]
    T = len(sections[0])
    assert len(sections[1]) == T and len(sections[2]) == T, (T, len(sections[1]), len(sections[2]))
    offsets = []
    at = DN_HEADER_BYTES
    for x in sections:
        offsets.append(at)
        at = (at + x.nbytes + 7) & ~7
    islands = int(sections[2].max()) + 1 if T else 0
    header = struct.pack(DN_HEADER_FMT, DN_MAGIC, DN_VERSION, DN_HEADER_BYTES, T, islands, int(W), int(H),
                         DN_DEVICES[device], (DN_FLAG_PLAIN if plain else 0) | (DN_FLAG_NO_BOUND if no_bound else 0), *offsets, at)
    assert len(header) == DN_HEADER_BYTES
    block = make_block(name, at)
    block[:DN_HEADER_BYTES] = header
    for off, x in zip(offsets, sections):
        b = x.view(np.uint8).ravel()
        block[off:off + len(b)] = b.tobytes()
    return block, at


class Channel:
    """One connection to an AO Baker server: Channel(name) claims fss-ao-baker.<name>; close() (or with) gives it back."""

    def __init__(self, name, timeout=2.0):
        full = PREFIX + name
        self.name = full
        self.view = self.mapping = self.server_event = self.own_event = self.lock = self.server_process = None
        self.locked = False
        self.seq = 1
        try:
            self.mapping = _k32.OpenFileMappingW(FILE_MAP_ALL_ACCESS, False, 'Local\\' + full)
            if not self.mapping:
                raise ChannelError(f'no server on {full} (error {ctypes.get_last_error()})')
            self.view = _k32.MapViewOfFile(self.mapping, FILE_MAP_ALL_ACCESS, 0, 0, 0)
            info = _MBI()
            _k32.VirtualQuery(self.view, ctypes.byref(info), ctypes.sizeof(info))
            self.size = info.RegionSize
            self.server_event = _k32.OpenEventW(EVENT_MODIFY_STATE | SYNCHRONIZE, False, 'Local\\' + full + '.s')
            self.own_event = _k32.OpenEventW(EVENT_MODIFY_STATE | SYNCHRONIZE, False, 'Local\\' + full + '.c')
            self.lock = _k32.OpenMutexW(SYNCHRONIZE | MUTEX_MODIFY_STATE, False, 'Local\\' + full + '.lock')
            if not (self.server_event and self.own_event and self.lock):
                raise ChannelError(f'{full}: its events or lock are missing')
            if self._u64(OFF_MAGIC) != MAGIC or self._u32(OFF_LAYOUT) != LAYOUT:
                raise ChannelError(f'{full} is not a channel of layout {LAYOUT}')
            self.ring = self._u32(OFF_RING)
            if _k32.WaitForSingleObject(self.lock, 0) not in (WAIT_OBJECT_0, WAIT_ABANDONED):
                raise ChannelError(f'{full} is busy with another client')
            self.locked = True
            end = time.perf_counter() + timeout
            while self._u32(OFF_CLIENT_PID) != 0:
                if time.perf_counter() > end:
                    raise ChannelError(f'{full}: the server has not let its last client go')
                time.sleep(0.001)
            self.server_pid = self._u32(OFF_SERVER_PID)
            self.server_process = _k32.OpenProcess(SYNCHRONIZE, False, self.server_pid)
            for off in (OFF_TO_SERVER_HEAD, OFF_TO_SERVER_TAIL, OFF_TO_CLIENT_HEAD, OFF_TO_CLIENT_TAIL):
                self._set_u64(off, 0)
            self._set_u32(OFF_CLIENT_PID, os.getpid())
            _k32.SetEvent(self.server_event)
        except BaseException:
            self.close()
            raise

    # the header's fields, as aligned loads and stores of their own size
    def _u64(self, off):
        return ctypes.c_uint64.from_address(self.view + off).value

    def _set_u64(self, off, v):
        ctypes.c_uint64.from_address(self.view + off).value = v

    def _u32(self, off):
        return ctypes.c_uint32.from_address(self.view + off).value

    def _set_u32(self, off, v):
        ctypes.c_uint32.from_address(self.view + off).value = v

    def _wait(self, seconds):
        """'signal', 'timeout' or 'gone' (the server ended)."""
        ms = max(0, int(seconds * 1000))
        if self.server_process:
            handles = (wintypes.HANDLE * 2)(self.own_event, self.server_process)
            r = _k32.WaitForMultipleObjects(2, handles, False, ms)
            return 'signal' if r == WAIT_OBJECT_0 else ('gone' if r == WAIT_OBJECT_0 + 1 else 'timeout')
        return 'gone'

    def send(self, mtype, payload=b'', timeout=5.0):
        total = _pad(len(payload))
        if total > self.ring:
            raise ChannelError(f'a message of {len(payload)} bytes does not fit the ring')
        to_ring = self.view + HEADER_BYTES
        end = time.perf_counter() + timeout
        while True:
            head, tail = self._u64(OFF_TO_SERVER_HEAD), self._u64(OFF_TO_SERVER_TAIL)
            pos = head % self.ring
            skip = self.ring - pos if pos + total > self.ring else 0
            if self.ring - (head - tail) >= skip + total:
                break
            if self._wait(end - time.perf_counter()) == 'gone':
                raise PeerGone(f'{self.name}: the server ended')
            if time.perf_counter() > end:
                raise ChannelError(f'{self.name}: the ring stayed full')
        if skip:
            ctypes.memmove(to_ring + pos, struct.pack('<IIQ', 0, skip - MSG_HEADER, 0), MSG_HEADER)
            head += skip
        at = to_ring + head % self.ring
        ctypes.memmove(at, struct.pack('<IIQ', mtype, len(payload), self.seq), MSG_HEADER)
        if payload:
            ctypes.memmove(at + MSG_HEADER, payload, len(payload))
        self.seq += 1
        self._set_u64(OFF_TO_SERVER_HEAD, head + total)
        _k32.SetEvent(self.server_event)

    def receive(self, timeout=5.0):
        """(type, seq, payload bytes), or None when nothing came in time; PeerGone when the server ended."""
        from_ring = self.view + HEADER_BYTES + self.ring
        end = time.perf_counter() + timeout
        while True:
            head, tail = self._u64(OFF_TO_CLIENT_HEAD), self._u64(OFF_TO_CLIENT_TAIL)
            if head != tail:
                at = from_ring + tail % self.ring
                mtype, n, seq = struct.unpack('<IIQ', ctypes.string_at(at, MSG_HEADER))
                payload = ctypes.string_at(at + MSG_HEADER, n) if mtype else b''
                self._set_u64(OFF_TO_CLIENT_TAIL, tail + _pad(n))
                _k32.SetEvent(self.server_event)
                if mtype:
                    return mtype, seq, payload
                continue
            left = end - time.perf_counter()
            if left <= 0:
                return None
            if self._wait(left) == 'gone':
                raise PeerGone(f'{self.name}: the server ended')

    def expect(self, mtype, timeout=5.0):
        got = self.receive(timeout)
        if got is None:
            raise ChannelError(f'no answer within {timeout} s (waiting for type {mtype})')
        if got[0] != mtype:
            detail = ''
            if got[0] == ERROR:
                code, req, msg = struct.unpack(ERROR_FMT, got[2][:struct.calcsize(ERROR_FMT)])
                detail = f': Error {ERROR_CODES.get(code, code)} to {req}: {text(msg)}'
            raise ChannelError(f'type {got[0]} instead of {mtype}{detail}')
        return got[2]

    # the messages of step (a)
    def hello(self, client='ao_baker_client.py'):
        self.send(HELLO, struct.pack(HELLO_FMT, PROTOCOL, os.getpid(), client.encode()))
        f = struct.unpack(READY_FMT, self.expect(READY)[:struct.calcsize(READY_FMT)])
        return dict(protocol=f[0], server_pid=f[1], device_state=DEVICE_STATES.get(f[2], f[2]), compute=(f[3], f[4]),
                    optix_version=f[5], driver_version=f[6], probe_value=f[7], device_memory=f[8], max_tile_pixels=f[9],
                    device=text(f[10]), detail=text(f[11]))

    def job_info(self, master, masters, name):
        self.send(JOB_INFO, struct.pack(JOB_INFO_FMT, master, masters, name.encode()))

    def echo(self, block='', nbytes=0, timeout=30.0):
        self.send(ECHO, struct.pack(ECHO_FMT, nbytes, block.encode()))
        f = struct.unpack(ECHO_DONE_FMT, self.expect(ECHO_DONE, timeout)[:struct.calcsize(ECHO_DONE_FMT)])
        return dict(bytes=f[0], checksum=f[1], microseconds=f[2], error=f[3])

    def cancel(self):
        self.send(CANCEL)
        self.expect(CANCELLED)

    def bye(self):
        self.send(BYE)

    # the messages of step (b)
    def load_scene(self, scene, block, nbytes, timeout=600.0):
        self.send(LOAD_SCENE, struct.pack(LOAD_SCENE_FMT, scene, 0, nbytes, block.encode()))
        f = struct.unpack(SCENE_READY_FMT, self.expect(SCENE_READY, timeout)[:struct.calcsize(SCENE_READY_FMT)])
        return dict(scene=f[0], triangles=f[1], instances=f[2], views=f[3], core=f[4], skirt=f[5], gpu_bytes=f[6],
                    seconds=f[7] / 1e6)

    def bake_tile(self, scene, rect, block, a_offset, b_offset, owners_offset=NO_OFFSET, tile=1, tiles=1,
                  on_progress=None, timeout=3600.0, only_view=0):
        """Bakes rect (x0, y0, w, h) into the block; returns TileDone as a dict, or None when the server answered
        Cancelled. on_progress(dict) gets each Progress and may call cancel_tile(). only_view v > 0: the mean of view
        v - 1 alone (the test of the combination), else every view combined."""
        x0, y0, w, h = rect
        self.send(BAKE_TILE, struct.pack(BAKE_TILE_FMT, scene, tile, tiles, int(only_view), x0, y0, w, h, a_offset, b_offset,
                                         owners_offset, block.encode()))
        end = time.perf_counter() + timeout
        while True:
            got = self.receive(max(0.0, end - time.perf_counter()))
            if got is None:
                raise ChannelError(f'tile {tile}: no TileDone within {timeout} s')
            mtype, _seq, payload = got
            if mtype == PROGRESS:
                f = struct.unpack(PROGRESS_FMT, payload[:struct.calcsize(PROGRESS_FMT)])
                if on_progress is not None:
                    on_progress(dict(scene=f[0], tile=f[1], view=f[2], views=f[3], samples_done=f[4], samples=f[5],
                                     rays=f[6], seconds=f[7] / 1e6))
            elif mtype == TILE_DONE:
                f = struct.unpack(TILE_DONE_FMT, payload[:struct.calcsize(TILE_DONE_FMT)])
                return dict(scene=f[0], tile=f[1], core_px=f[2], skirt_px=f[3], rays=f[4], raster_s=f[5] / 1e6,
                            trace_s=f[6] / 1e6, seconds=f[7] / 1e6)
            elif mtype == CANCELLED:
                return None
            elif mtype == ERROR:
                code, req, msg = struct.unpack(ERROR_FMT, payload[:struct.calcsize(ERROR_FMT)])
                raise ChannelError(f'Error {ERROR_CODES.get(code, code)} to {req}: {text(msg)}')
            elif mtype != CANCEL:  # the window's Cancel: the caller's to act on; a test ignores it
                raise ChannelError(f'type {mtype} while baking a tile')

    def cancel_tile(self):
        """Inside on_progress: the server stops the tile after its current launch and answers Cancelled."""
        self.send(CANCEL)

    def release_scene(self, scene):
        self.send(RELEASE_SCENE, struct.pack(RELEASE_SCENE_FMT, scene, 0))

    # the curvature of step (d)
    def load_curvature(self, curv, block, nbytes, timeout=600.0):
        self.send(CURV_LOAD, struct.pack(CURV_LOAD_FMT, curv, 0, nbytes, block.encode()))
        f = struct.unpack(CURV_READY_FMT, self.expect(CURV_READY, timeout)[:struct.calcsize(CURV_READY_FMT)])
        return dict(curvature=f[0], triangles=f[1], edges=f[2], candidates=f[4], seconds=f[5] / 1e6)

    def curvature_rows(self, curv, top, rows, block, codes_offset, out_offset, timeout=600.0):
        """Rows top..top + rows - 1 of the .ao.map (from the top): int32 codes at codes_offset in the block, uint16
        curvature written at out_offset."""
        self.send(CURV_ROWS, struct.pack(CURV_ROWS_FMT, curv, top, rows, 0, codes_offset, out_offset, block.encode()))
        f = struct.unpack(CURV_DONE_FMT, self.expect(CURV_DONE, timeout)[:struct.calcsize(CURV_DONE_FMT)])
        return dict(curvature=f[0], top=f[1], rows=f[2], pixels=f[4], seconds=f[5] / 1e6)

    def release_curvature(self, curv):
        self.send(CURV_RELEASE, struct.pack(CURV_RELEASE_FMT, curv, 0))

    # the denoise of step (d)
    def load_denoise(self, dn, block, nbytes, timeout=600.0):
        self.send(DN_LOAD, struct.pack(DN_LOAD_FMT, dn, 0, nbytes, block.encode()))
        f = struct.unpack(DN_READY_FMT, self.expect(DN_READY, timeout)[:struct.calcsize(DN_READY_FMT)])
        return dict(denoise=f[0], triangles=f[1], islands=f[2], device={0: 'GPU', 1: 'CPU'}.get(f[3], f[3]),
                    oidn_version=f[4], seconds=f[6] / 1e6, detail=f[7].split(b'\0', 1)[0].decode(errors='replace'))

    def denoise_window(self, dn, window_top, window_rows, band_top, band_rows, strength, block, codes_offset,
                       raw_offset, out_offset, timeout=600.0):
        """Window rows window_top.. of the .ao.map (from the top): int32 codes and uint16 raw AO at their offsets; the
        band's rows (band_top.. in the window) come back as uint16 at out_offset."""
        self.send(DN_WINDOW, struct.pack(DN_WINDOW_FMT, dn, window_top, window_rows, band_top, band_rows, float(strength),
                                         codes_offset, raw_offset, out_offset, block.encode()))
        f = struct.unpack(DN_DONE_FMT, self.expect(DN_DONE, timeout)[:struct.calcsize(DN_DONE_FMT)])
        return dict(denoise=f[0], window_top=f[1], groups=f[2], pixels=f[4], change=f[5], prepare_s=f[6] / 1e6,
                    oidn_s=f[7] / 1e6, seconds=f[8] / 1e6)

    def release_denoise(self, dn):
        self.send(DN_RELEASE, struct.pack(DN_RELEASE_FMT, dn, 0))

    def close(self):
        if self.locked:
            _k32.ReleaseMutex(self.lock)
            self.locked = False
        for h in (self.server_process, self.lock, self.own_event, self.server_event):
            if h:
                _k32.CloseHandle(h)
        self.server_process = self.lock = self.own_event = self.server_event = None
        if self.view:
            _k32.UnmapViewOfFile(self.view)
            self.view = None
        if self.mapping:
            _k32.CloseHandle(self.mapping)
            self.mapping = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def connect(name, wait=10.0, timeout=2.0):
    """A Channel once a server has made fss-ao-baker.<name> (a just started app needs a moment)."""
    end = time.perf_counter() + wait
    while True:
        try:
            return Channel(name, timeout)
        except PeerGone:
            raise
        except ChannelError as exc:
            if 'no server' not in str(exc) or time.perf_counter() > end:
                raise
            time.sleep(0.01)


# ---------------------------------------------------------------------------------------------------------------------
# FSS OptiX for the AO Bake (decisions 21 to 25): the shipped baker, started for a job
# ---------------------------------------------------------------------------------------------------------------------

NAME = 'FSS OptiX'  # decision 22: the baker's name in the panel, the log and the artist guide
LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib', 'ao_baker', 'windows-x64')
EXE = os.environ.get('FSS_AO_BAKER_EXE') or os.path.join(LIB, 'aobaker.exe')  # the variable: tests (a missing exe)
NO_CUDA_ENV = 'FSS_AO_BAKER_NO_CUDA'  # set: the baker starts without its GPU (a test of the fallback)
CONNECT_S = 20.0  # a just started baker makes its channel within this
CLOSE_S = 30.0
TILE_TIMEOUT_S = 6 * 3600.0
CURV_BAND = 256  # write_curvature's rows per band
CREATE_NO_WINDOW = 0x08000000


def available():
    """(True, '') when the shipped baker can be started on this machine, else (False, why)."""
    if os.name != 'nt':
        return False, f'{NAME} runs on Windows only'
    if not os.path.isfile(EXE):
        return False, f'{NAME} is not installed with the add-on ({EXE} is missing)'
    return True, ''


def version():
    """The shipped baker's VERSION.txt on one line (Glider's commit and the build's time), or 'unknown'."""
    try:
        with open(os.path.join(LIB, 'VERSION.txt'), encoding='utf-8') as f:
            return '; '.join(line.strip() for line in f if line.strip()) or 'unknown'
    except OSError:
        return 'unknown'


def _np():
    import numpy as np
    return np


CORE = None  # ao_bake_core, set by a loader that imports this file by its path (the runner)


def _core():
    """ao_bake_core of the add-on this file belongs to (the part below runs in Blender only): CORE when a loader set it,
    else the package's."""
    if CORE is not None:
        return CORE
    try:
        from . import ao_bake_core as core
    except ImportError:
        import importlib
        core = importlib.import_module(__name__.rsplit('.', 1)[0] + '.ao_bake_core')
    return core


def scene_parts(pos, tris, cn, m):
    """(target triangles, core pieces, skirt pieces) of a master: the target is tris with three distinct corners (the
    runner's FSS_AO_TARGET); each piece names the target triangle it lies on (core: itself; skirt: skirt_src)."""
    np = _np()
    tris = np.asarray(tris)
    distinct = np.array([len(set(r)) == 3 for r in tris.tolist()], dtype=bool)
    tmap = np.full(len(tris), -1, dtype=np.int64)
    tmap[distinct] = np.arange(int(distinct.sum()))
    ct = m['core_tris']

    def target(idx):
        t = tmap[idx]
        return np.where(t >= 0, t, NO_TRIANGLE)
    core_p = pieces(target(ct), np.asarray(pos)[tris[ct]], np.asarray(cn)[ct], m['muv'][ct])
    src = np.asarray(m['skirt_src'], dtype=np.int64)
    skirt_p = pieces(target(src), m['skirt_pos'], m['skirt_n'], m['skirt_uv'])
    return tris[distinct], core_p, skirt_p


def views_scene(pos, target_tris, occluders=(), views=None, samples=1024):
    """(meshes, instances, views) of a scene block: mesh 0 the target, then each occluder (positions (v, 3) in bake
    space, triangles (t, 3)) as one instance in place. views: [dict(transform (3 x 4 or 4 x 4), copy, samples,
    occluders: indices into occluders)], a copy's views consecutive, copies numbered from 0 in order; None: one view
    of every occluder with samples."""
    np = _np()
    meshes = [(pos, target_tris)] + [(p, t) for p, t in occluders]
    instances = [(0, True, IDENTITY)] + [(k + 1, False, IDENTITY) for k in range(len(occluders))]
    if views is None:
        views = [dict(transform=IDENTITY, copy=0, samples=samples, occluders=list(range(len(occluders))))]
    out = []
    for v in views:
        tr = np.asarray(v['transform'], dtype=np.float64)
        tr = tr[:3, :4] if tr.shape == (4, 4) else tr.reshape(3, 4)
        out.append((tr.ravel(), int(v['copy']), int(v['samples']), [0] + [k + 1 for k in v['occluders']]))
    return meshes, instances, out


class Baker:
    """The shipped aobaker.exe started for a job on a channel of its own, connected. foreground: with its window
    (the run mode Foreground, decision 12), else --headless. ok: its GPU works (Ready's device state Ok), else why says
    what it lacks. Close it (or use with); a Baker that is not closed ends with the Blender that started it (the baker
    watches its client's process)."""

    def __init__(self, foreground=False, client='ao_bake_runner', exe=None, tag=''):
        exe = exe or EXE
        self.name = f'addon-{os.getpid()}-{tag or int(time.time() * 1000) % 100000000}'
        args = [exe, '--channel', self.name, '--client-pid', str(os.getpid())] + ([] if foreground else ['--headless'])
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                                     creationflags=0 if foreground else CREATE_NO_WINDOW)
        self.ch = None
        self.blocks = {}
        self.scene = 0
        try:
            self.ch = connect(self.name, wait=CONNECT_S)
            self.ready = self.ch.hello(client)
        except BaseException:
            self.close()
            raise
        self.ok = self.ready['device_state'] == 'Ok'
        self.why = '' if self.ok else f"{self.ready['device_state']}: {self.ready['detail'] or 'no detail'}"
        self.version = version()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        """Says Bye, closes the channel and the blocks, and waits for the baker to end (killed after CLOSE_S)."""
        try:
            if self.ch is not None:
                try:
                    self.ch.bye()
                except ChannelError:
                    pass
                self.ch.close()
                self.ch = None
        finally:
            for b in self.blocks.values():
                b[0].close()
            self.blocks.clear()
            if self.proc is not None:
                try:
                    self.proc.wait(timeout=CLOSE_S)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait(timeout=CLOSE_S)
                self.proc = None

    def _block(self, kind, size):
        """A data block of this Baker of at least size bytes, kept and grown (name, mmap)."""
        have = self.blocks.get(kind)
        if have is None or have[1] < size:
            if have is not None:
                have[0].close()
            name = f'{self.name}.{kind}.{len(self.blocks)}-{size}'
            self.blocks[kind] = (make_block(name, size), size, name)
        b = self.blocks[kind]
        return b[2], b[0]

    def job_info(self, master, masters, name):
        self.ch.job_info(master, masters, name)

    def load_master(self, pos, tris, cn, m, distance, samples, views=None, occluders=(), falloff=False,
                    combine='AVERAGE', seed=0):
        """The master's scene, replacing the last one: pos (V, 3), tris (T, 3) and corner normals cn (T, 3, 3) of the
        master's triangles in bake space (tri_src order), m its layout; occluders [(positions, triangles)]; views as
        views_scene. Returns SceneReady as a dict."""
        target_tris, core_p, skirt_p = scene_parts(pos, tris, cn, m)
        meshes, instances, vlist = views_scene(pos, target_tris, occluders, views, samples)
        if self.scene:
            self.ch.release_scene(self.scene)
        self.scene += 1
        name = f'{self.name}.scene.{self.scene}'
        block, nbytes = scene_block(name, meshes, instances, vlist, core_p, skirt_p, distance, falloff=falloff,
                                    combine=combine, seed=seed, width=m['W'], height=m['H'])
        try:
            return self.ch.load_scene(self.scene, name, nbytes, timeout=TILE_TIMEOUT_S)
        finally:
            block.close()

    def bake_tile(self, rect, tile=1, tiles=1, on_progress=None):
        """The loaded master's tile rect (x0, y0, w, h): (A, B, TileDone), A and B float32 (h, w), rows from y0 up, the
        core's and the skirt's mean AO or -1 where no piece owns the pixel; None when cancelled (cancel_tile from
        on_progress, or the window's Cancel answered)."""
        np = _np()
        x0, y0, w, h = rect
        n = int(w) * int(h)
        name, block = self._block('tile', 2 * n * 4)
        done = self.ch.bake_tile(self.scene, rect, name, 0, n * 4, tile=tile, tiles=tiles, on_progress=on_progress,
                                 timeout=TILE_TIMEOUT_S)
        if done is None:
            return None
        A = np.frombuffer(block, np.float32, n, 0).reshape(h, w).copy()
        B = np.frombuffer(block, np.float32, n, n * 4).reshape(h, w).copy()
        return A, B, done

    def cancel_tile(self):
        self.ch.cancel_tile()

    def release_master(self):
        if self.scene and self.ch is not None:
            self.ch.release_scene(self.scene)

    def write_curvature(self, folder, stem, m, pos, tris, cn, width, threads=None, rows=CURV_BAND, max_samples=512):
        """ao_bake_core.write_curvature in the baker (the same rows, byte for byte: OptiX baker journal Session 6):
        the curvature master <stem>.curv.jxl (an older .curv.png removed) in the AO master's layout, from the master's
        triangles (tris (T, 3) into pos, cn (T, 3, 3), in tri_src order). Returns dict(path, edges, seconds). libjxl is
        required (apply-native-copy decision 6): a JxlError without it."""
        np = _np()
        core = _core()
        t0 = time.time()
        _img, mp, _npz = core.master_paths(folder, stem)
        W, H, gen = core.map_rows(mp, rows)
        geo = f'{self.name}.curv'
        block, nbytes = curvature_block(geo, pos, tris, cn, m['muv'], W, H, width, max_samples)
        try:
            ready = self.ch.load_curvature(1, geo, nbytes, timeout=TILE_TIMEOUT_S)
        finally:
            block.close()
        path, other = core.image_paths(folder, stem, 'curv')
        lib = core.jxl()
        if not lib.available():
            raise lib.JxlError(f'{path}: the JPEG XL library is not loaded ({lib.error()})')
        w = lib.Writer(path + '.tmp', W, H, threads=threads or lib.THREADS)
        name, io_block = self._block('rows', rows * W * 6)
        try:
            codes_view = np.frombuffer(io_block, np.int32, rows * W, 0)
            out_view = np.frombuffer(io_block, np.uint16, rows * W, rows * W * 4)
            top = 0
            for band in gen:  # rows from the top: file row r is master pixel row H - 1 - r
                n = band.shape[0]
                codes_view[:n * W] = np.ascontiguousarray(band, dtype=np.int32).ravel()
                self.ch.curvature_rows(1, top, n, name, 0, rows * W * 4, timeout=TILE_TIMEOUT_S)
                w.write(out_view[:n * W].reshape(n, W).copy())
                top += n
            del codes_view, out_view
            w.close()
        except BaseException:
            w.abort()
            raise
        finally:
            self.ch.release_curvature(1)
        os.replace(path + '.tmp', path)
        try:
            os.remove(other)
        except OSError:
            pass
        return dict(path=path, edges=int(ready['edges']), seconds=round(time.time() - t0, 2))

    def denoise_master(self, folder, stem, cn, opts, device='GPU', on_band=None, cache_bytes=None):
        """ao_bake_core.denoise_master_oidn in the baker (OptiX baker journal Session 8: OIDN 2.5.1 shipped with the
        baker, the islands isolated as the add-on does it, each pixel's island mean restored, the change bound to the
        noise): the raw master <stem>.ao.raw.jxl into the master <stem>.ao.jxl (libjxl required, apply-native-copy
        decision 6), in the add-on's windows. cn (T, 3, 3): the master's corner normals in its face order; opts: strength. on_band(i, n) after each
        window. Returns the stats as denoise_master_oidn's (method OIDN, device, groups, windows, px, mean change,
        seconds) and the baker's name and OIDN's version."""
        np = _np()
        core = _core()
        t0 = time.time()
        cache_bytes = cache_bytes or core.PAGE_CACHE_BYTES
        strength = float(opts.get('strength', 1.0))
        raw = core.master_paths(folder, stem, 'ao.raw')[0]
        if not os.path.isfile(raw):
            raise FileNotFoundError(f'{raw}: no raw master')
        master = core.open_master(folder, stem, cache_bytes=cache_bytes, kind='ao.raw')
        if master is None:
            raise FileNotFoundError(f'{stem}: the raw master or its layout is missing')
        try:
            W, H = master['W'], master['H']
            geo = f'{self.name}.dn'
            block, nbytes = denoise_block(geo, cn, master['muv'], master['island'], W, H, device=device)
            try:
                ready = self.ch.load_denoise(1, geo, nbytes, timeout=TILE_TIMEOUT_S)
            finally:
                block.close()
            dst, other = core.image_paths(folder, stem)
            jl = core.jxl()
            if not jl.available():
                raise jl.JxlError(f'{dst}: the JPEG XL library is not loaded ({jl.error()})')
            w = jl.Writer(dst + '.tmp', W, H, threads=jl.THREADS)
            band = max(64, core.OIDN_WINDOW_PX // max(W, 1) - 2 * core.OIDN_HALO)
            nb = -(-H // band)
            rows_max = min(H, band + 2 * core.OIDN_HALO)
            name, io_block = self._block('dn', rows_max * W * 8)
            n_px, change, groups = 0, 0.0, 0
            try:
                cv = np.frombuffer(io_block, np.int32, rows_max * W, 0)
                rv = np.frombuffer(io_block, np.uint16, rows_max * W, rows_max * W * 4)
                ov = np.frombuffer(io_block, np.uint16, rows_max * W, rows_max * W * 6)
                xi = np.arange(W)
                for i, top in enumerate(range(0, H, band)):
                    bot = min(H, top + band)
                    wt, wb = max(0, top - core.OIDN_HALO), min(H, bot + core.OIDN_HALO)
                    wr = wb - wt
                    ys = H - 1 - np.arange(wt, wb)  # file rows from the top, as master rows (row 0 the bottom)
                    yi, xx = np.broadcast_arrays(ys[:, None], xi[None, :])
                    cv[:wr * W] = core.map_code(master['face_map'][yi, xx], master['filled'][yi, xx]).ravel()
                    rv[:wr * W] = master['image'][yi, xx].ravel()
                    got = self.ch.denoise_window(1, wt, wr, top - wt, bot - top, strength, name, 0, rows_max * W * 4,
                                                 rows_max * W * 6, timeout=TILE_TIMEOUT_S)
                    w.write(ov[:(bot - top) * W].reshape(bot - top, W).copy())  # rows from the top
                    groups = max(groups, got['groups'])
                    n_px += got['pixels']
                    change += got['change']
                    if on_band is not None:
                        on_band(i + 1, nb)
                del cv, rv, ov
                w.close()
            except BaseException:
                w.abort()
                raise
            finally:
                self.ch.release_denoise(1)
            os.replace(dst + '.tmp', dst)
            try:
                os.remove(other)
            except OSError:
                pass
        finally:
            master['close']()
        return dict(method='OIDN', device=ready['device'], groups=int(groups), windows=nb, px=int(n_px),
                    mean_change=round(change / max(n_px, 1), 6), seconds=round(time.time() - t0, 2), baker=NAME,
                    oidn=ready['oidn_version'])
