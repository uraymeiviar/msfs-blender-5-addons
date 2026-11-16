"""Reference values of the Python code the C++ DLL replaced (apply-native-copy journal, decision 6, Session 15).

Decision 6 removed the Python twins of the DLL's parts (the numpy copy, the Python opening, the Python PNG writer and
reader, the raster, the dilation, the UV islands, Soften, the composition, the map writer). Before they were removed,
the tests ran them on their seeded inputs and recorded, per case, a SHA-256 of their outputs (arrays with their dtype
and shape, counts, file bytes) and the number of array elements, in tests/data/ao_native_reference.json. The tests now
run the C++ on the same inputs and compare with those values.

    ref = Reference('harness')
    ref.check('raster/07', owners, counts)  # a SHA-256 of the values, compared with the recorded one
    ref.done(complete=True)                 # a full run: every recorded key was checked

FSS_AO_REF_RECORD=1 recorded the values while the Python code was still there (Session 15, before the deletion); a
recording run needs that code, so it cannot be repeated: with FSS_AO_REF_RECORD=1 Reference now refuses (it would
record the C++ values over the Python code's), and a key that is not in the file fails.
"""

import hashlib
import json
import os

import numpy as np

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'ao_native_reference.json')
RECORD_ENV = 'FSS_AO_REF_RECORD'


def _feed(h, v, n):
    """The bytes of v into the hash h: arrays with dtype and shape, numbers as Python numbers, containers in order.
    Returns the count of array elements so far."""
    if isinstance(v, np.ndarray):
        a = np.ascontiguousarray(v)
        h.update(f'A{a.dtype.str}{a.shape}:'.encode())
        h.update(a.tobytes())
        return n + a.size
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, (bytes, bytearray, memoryview)):
        b = bytes(v)
        h.update(f'B{len(b)}:'.encode())
        h.update(b)
        return n
    if isinstance(v, dict):
        h.update(b'{')
        for k, x in v.items():
            n = _feed(h, str(k), n)
            n = _feed(h, x, n)
        h.update(b'}')
        return n
    if isinstance(v, (list, tuple)):
        h.update(b'[')
        for x in v:
            n = _feed(h, x, n)
        h.update(b']')
        return n
    if v is None or isinstance(v, (bool, int, float, str)):
        h.update(f'{type(v).__name__}:{v!r};'.encode())
        return n
    raise TypeError(f'no reference digest for {type(v).__name__}')


def digest(*values):
    """'<sha256>/<array elements>' of the values."""
    h = hashlib.sha256()
    n = _feed(h, list(values), 0)
    return f'{h.hexdigest()}/{n}'


class Reference:
    """The recorded values of one section of the file (harness, suite, native_job)."""

    def __init__(self, section):
        self.section = section
        self.record = False
        if os.environ.get(RECORD_ENV) == '1':
            raise RuntimeError(f'{RECORD_ENV}=1: the reference values were recorded from the Python code decision 6 '
                               f'removed; they cannot be recorded again')
        self.want = {}
        if os.path.isfile(PATH):
            with open(PATH, encoding='utf-8') as f:
                self.want = json.load(f).get(section, {})
        self.got = {}

    def check(self, key, *values):
        """The digest of the values, compared with the recorded one. A key checked twice in a run must give the same
        digest both times."""
        d = digest(*values)
        if key in self.got:
            assert self.got[key] == d, f'{self.section}/{key}: {d} now, {self.got[key]} earlier in this run'
        self.got[key] = d
        assert key in self.want, f'{self.section}/{key}: no reference value recorded'
        assert self.want[key] == d, f'{self.section}/{key}: {d}, the Python code gave {self.want[key]}'
        return d

    def done(self, complete=False):
        """complete: every recorded key was checked. Returns the number of keys checked."""
        if complete:
            missing = sorted(set(self.want) - set(self.got))
            assert not missing, f'{self.section}: {len(missing)} recorded keys not checked: {missing[:8]}'
        return len(self.got)
