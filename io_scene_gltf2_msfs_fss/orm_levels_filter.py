"""
FSS: the ORM levels filter without Blender (ORM levels journal, 20261114, decision 8).

The formula, the PNG decode and encode, and the filter of a PNG file's bytes. Imports only the standard library and
numpy, and nothing of the add-on, so the FSS deploy (`msfs24-texture-lib.py --stage` in the aircraft repository) loads
this file by its path with a plain Python and filters the source textures with the same code as the exporter
(`orm_levels.py`, which imports it). Both give the same bytes for the same source file and levels.

Five values per channel (occlusion R, roughness G, metallic B): input black, gamma, input white, output black, output
white. For a channel value x in 0..1:

    t = clamp((x - in_black) / (in_white - in_black), 0, 1)     (in_white <= in_black: t = 1 where x >= in_black, else 0)
    out = out_black + (out_white - out_black) * t ^ (1 / gamma)

Defaults (0, 1, 1, 0, 1) change nothing. Integer values are rounded to the nearest integer (halves up).

PNG: 8 and 16 bits, grey, RGB, grey + alpha and RGBA, interlaced or not, every filter type. The result has the same
size, bit depth, colour type, alpha and ancillary chunks as the source; an interlaced source is written
non-interlaced. Anything else raises ValueError.
"""

import hashlib
import math
import struct
import zlib
from collections import OrderedDict

import numpy as np

CHANNELS = ("occlusion", "roughness", "metallic")
FIELDS = ("in_black", "gamma", "in_white", "out_black", "out_white")
DEFAULT = (0.0, 1.0, 1.0, 0.0, 1.0)
DEFAULTS = (DEFAULT, DEFAULT, DEFAULT)

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_COLOR_TYPE_CHANNELS = {0: 1, 2: 3, 4: 2, 6: 4}  # grey, RGB, grey + alpha, RGBA
# Adam7 passes: (first column, first row, column step, row step)
_ADAM7 = ((0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2))

# Cache: (sha1 of the source bytes, levels) -> filtered bytes; counters for the tests
_CACHE_SIZE = 16
_filtered = OrderedDict()
stats = {"filtered": 0, "cached": 0}


# region Formula

def levels_float(x, levels):
    """The formula on values `x` in 0..1 (a numpy array or a float) for one channel's (in_black, gamma, in_white,
    out_black, out_white). Returns float64."""
    in_black, gamma, in_white, out_black, out_white = (float(v) for v in levels)
    x = np.asarray(x, dtype=np.float64)
    if in_white <= in_black:
        t = (x >= in_black).astype(np.float64)
    else:
        t = np.clip((x - in_black) / (in_white - in_black), 0.0, 1.0)
    t = t ** (1.0 / gamma)
    return out_black + (out_white - out_black) * t


def apply_levels(values, levels, maximum):
    """The formula on integer channel values `values` of depth `maximum` (255 or 65535), rounded to the nearest
    integer (halves up). Returns an array of the same shape and dtype."""
    out = levels_float(np.asarray(values, dtype=np.float64) / maximum, levels) * maximum
    return np.clip(np.floor(out + 0.5), 0, maximum).astype(np.asarray(values).dtype)


def levels_from_mapping(mapping):
    """The three (in_black, gamma, in_white, out_black, out_white) tuples of a {channel: {field: value}} mapping, as
    the exporter's levels list (`<glTF name>.fss-levels.json`) holds them. Raises ValueError when a value is missing,
    not a finite number, or the gamma is not above 0."""
    try:
        levels = tuple(tuple(float(mapping[channel][field]) for field in FIELDS) for channel in CHANNELS)
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"levels need {len(CHANNELS)} channels of {len(FIELDS)} numbers ({error!r})") from None
    for channel, values in zip(CHANNELS, levels):
        if not all(math.isfinite(v) for v in values) or values[1] <= 0.0:
            raise ValueError(f"levels of {channel} are not usable: {values}")
    return levels

# endregion


# region PNG

def _chunks(data):
    """(type, payload) of each chunk of a PNG; raises ValueError when it is not one."""
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("not a PNG")
    position, chunks = len(PNG_SIGNATURE), []
    while position + 8 <= len(data):
        length, tag = struct.unpack(">I4s", data[position:position + 8])
        chunks.append((tag, data[position + 8:position + 8 + length]))
        position += 12 + length
        if tag == b"IEND":
            break
    return chunks


def png_header(data):
    """(width, height, bit depth, colour type, interlace) of a PNG."""
    for tag, payload in _chunks(data):
        if tag == b"IHDR":
            width, height, depth, color_type, _compression, _filter, interlace = struct.unpack(">IIBBBBB", payload)
            return width, height, depth, color_type, interlace
    raise ValueError("PNG without IHDR")


def _chunk(tag, payload):
    return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)


def _filter_rows(raw, bpp):
    """PNG filtering of `raw` (rows x row bytes, uint8): per row the filter with the smallest sum of absolute signed
    bytes (the usual heuristic). Returns the filtered stream with the filter type bytes."""
    height = raw.shape[0]
    x = raw.astype(np.int16)
    left = np.zeros_like(x)
    left[:, bpp:] = x[:, :-bpp]
    up = np.zeros_like(x)
    up[1:] = x[:-1]
    upleft = np.zeros_like(x)
    upleft[1:, bpp:] = x[:-1, :-bpp]
    p = left + up - upleft
    pa, pb, pc = np.abs(p - left), np.abs(p - up), np.abs(p - upleft)
    paeth = np.where((pa <= pb) & (pa <= pc), left, np.where(pb <= pc, up, upleft))
    candidates = np.stack([x, x - left, x - up, x - (left + up) // 2, x - paeth]) & 0xFF
    signed = np.where(candidates > 127, 256 - candidates, candidates)
    best = signed.sum(axis=2).argmin(axis=0)
    rows = candidates[best, np.arange(height)].astype(np.uint8)
    return np.concatenate([best.astype(np.uint8)[:, None], rows], axis=1).tobytes()


def encode_png(pixels, depth, color_type, ancillary=()):
    """A PNG of `pixels` (rows top to bottom x columns x channels, integers of `depth` bits) with the given colour
    type; `ancillary` (type, payload) chunks are written before the image data."""
    height, width, channels = pixels.shape
    if depth == 16:
        raw = pixels.astype(">u2").reshape(height, width * channels).view(np.uint8)
        bpp = 2 * channels
    else:
        raw = pixels.astype(np.uint8).reshape(height, width * channels)
        bpp = channels
    header = struct.pack(">IIBBBBB", width, height, depth, color_type, 0, 0, 0)
    out = [PNG_SIGNATURE, _chunk(b"IHDR", header)]
    out += [_chunk(tag, payload) for tag, payload in ancillary]
    out.append(_chunk(b"IDAT", zlib.compress(_filter_rows(np.ascontiguousarray(raw), bpp), 6)))
    out.append(_chunk(b"IEND", b""))
    return b"".join(out)


def _diagonal(flat, row, column, count, row_length, bpp):
    """A view of `count` pixels (each `bpp` bytes) of a C-contiguous (rows x row_length x bpp) uint8 array, given
    flat, from (row, column) going one row down and one column left per pixel."""
    start = (row * row_length + column) * bpp
    return np.lib.stride_tricks.as_strided(flat[start:], shape=(count, bpp), strides=((row_length - 1) * bpp, 1))


def _unfilter(stream, width, height, bpp):
    """The bytes of a filtered PNG image (`height` rows of a filter type byte and width * bpp bytes) without the
    filters, as (height x width x bpp) uint8. Rows of the types None, Sub and Up only are undone row by row; with
    Average or Paeth rows, pixel (y, x) depends on (y, x-1), (y-1, x) and (y-1, x-1), so the pixels of one
    anti-diagonal (x + y constant) are undone together, one anti-diagonal after the other."""
    row_bytes = width * bpp
    rows = np.frombuffer(stream, dtype=np.uint8, count=height * (row_bytes + 1)).reshape(height, row_bytes + 1)
    types = rows[:, 0]
    if types.max(initial=0) > 4:
        raise ValueError(f"PNG filter type {int(types.max())} does not exist")
    raw = rows[:, 1:].reshape(height, width, bpp)
    if not np.any(types >= 3):
        out = np.empty((height, width, bpp), np.uint8)
        previous = np.zeros((width, bpp), np.uint8)
        for y in range(height):
            kind = types[y]
            if kind == 0:
                out[y] = raw[y]
            elif kind == 1:
                np.cumsum(raw[y], axis=0, dtype=np.uint8, out=out[y])
            else:
                np.add(raw[y], previous, out=out[y])
            previous = out[y]
        return out
    # One row and one column of zeros before the image: the neighbours outside it
    padded = np.zeros((height + 1, width + 1, bpp), np.uint8)
    flat_out = padded.reshape(-1)
    flat_raw = np.ascontiguousarray(raw).reshape(-1)
    kinds = types.astype(np.int16)
    for d in range(width + height - 1):
        first = max(0, d - width + 1)
        count = min(height - 1, d) - first + 1
        column = d - first
        a = _diagonal(flat_out, first + 1, column, count, width + 1, bpp).astype(np.int16)  # left
        b = _diagonal(flat_out, first, column + 1, count, width + 1, bpp).astype(np.int16)  # up
        c = _diagonal(flat_out, first, column, count, width + 1, bpp).astype(np.int16)  # up left
        kind = kinds[first:first + count, None]
        pa, pb, pc = np.abs(b - c), np.abs(a - c), np.abs(a + b - 2 * c)
        paeth = np.where((pa <= pb) & (pa <= pc), a, np.where(pb <= pc, b, c))
        predictor = np.where(kind == 1, a, np.where(kind == 2, b, np.where(kind == 3, (a + b) >> 1,
                                                                             np.where(kind == 4, paeth, 0))))
        value = (_diagonal(flat_raw, first, column, count, width, bpp).astype(np.int16) + predictor) & 0xFF
        _diagonal(flat_out, first + 1, column + 1, count, width + 1, bpp)[...] = value
    return padded[1:, 1:]


def decode_png(data):
    """The pixels of a PNG (rows top to bottom x columns x the file's channels) as int64 integers of its bit depth,
    with its (width, height, bit depth, colour type, interlace). Exact for 8 and 16 bits; the alpha channel as it
    is."""
    width, height, depth, color_type, interlace = png_header(data)
    if color_type not in _COLOR_TYPE_CHANNELS or depth not in (8, 16):
        raise ValueError(f"PNG colour type {color_type} with {depth} bits is not supported")
    if interlace not in (0, 1):
        raise ValueError(f"PNG interlace method {interlace} does not exist")
    channels = _COLOR_TYPE_CHANNELS[color_type]
    bpp = channels * depth // 8
    try:
        stream = zlib.decompress(b"".join(payload for tag, payload in _chunks(data) if tag == b"IDAT"))
    except zlib.error as error:
        raise ValueError(f"PNG image data cannot be read ({error})") from None
    passes = [(0, 0, 1, 1)] if interlace == 0 else _ADAM7
    image = np.empty((height, width, bpp), np.uint8)
    position = 0
    for x0, y0, dx, dy in passes:
        pass_width, pass_height = -(-(width - x0) // dx), -(-(height - y0) // dy)
        if pass_width <= 0 or pass_height <= 0:
            continue  # an empty pass has no rows
        size = pass_height * (pass_width * bpp + 1)
        if position + size > len(stream):
            raise ValueError("PNG image data is too short")
        image[y0::dy, x0::dx] = _unfilter(stream[position:position + size], pass_width, pass_height, bpp)
        position += size
    if depth == 16:
        pixels = image.reshape(height, width * bpp).view(">u2").reshape(height, width, channels)
    else:
        pixels = image
    return pixels.astype(np.int64), (width, height, depth, color_type, interlace)


def filter_png(data, levels):
    """The PNG `data` with `levels` applied to its R, G and B channels: same size, bit depth, colour type, alpha and
    ancillary chunks (an interlaced source is written non-interlaced). Raises ValueError for what it cannot filter."""
    pixels, (_width, _height, depth, color_type, _interlace) = decode_png(data)
    maximum = 65535 if depth == 16 else 255
    out = pixels.copy()
    if color_type in (0, 4):
        if not (levels[0] == levels[1] == levels[2]):
            raise ValueError("a grey texture holds one channel for occlusion, roughness and metallic: their levels "
                             "must be the same")
        out[..., 0] = apply_levels(pixels[..., 0], levels[0], maximum)
    else:
        for index in range(3):
            out[..., index] = apply_levels(pixels[..., index], levels[index], maximum)
    ancillary = [(tag, payload) for tag, payload in _chunks(data) if tag not in (b"IHDR", b"IDAT", b"IEND")]
    return encode_png(out, depth, color_type, ancillary)


def filtered_bytes(data, levels):
    """filter_png through the cache (source bytes and levels)."""
    key = (hashlib.sha1(data).hexdigest(), levels)
    cached = _filtered.get(key)
    if cached is not None:
        _filtered.move_to_end(key)
        stats["cached"] += 1
        return cached
    result = filter_png(data, levels)
    stats["filtered"] += 1
    _filtered[key] = result
    while len(_filtered) > _CACHE_SIZE:
        _filtered.popitem(last=False)
    return result


def clear_cache():
    _filtered.clear()
    stats["filtered"] = stats["cached"] = 0

# endregion
