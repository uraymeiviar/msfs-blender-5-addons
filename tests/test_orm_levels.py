"""ORM Levels (ORM levels journal, 20261114): the formula, the preview nodes between the ORM and detail ORM textures
and their readers (inserted once, kept through Asobo's relinks, on file load and by the update operator, the clearcoat
branch through them), a texture shared by two materials, exports byte-identical at the defaults for the MSFS 2024
multi-exporter, the MSFS 2020 export and File > Export (with and without the MSFS hooks), exported pixels equal to the
formula for an 8-bit and a 16-bit ORM and a detail ORM, the source files unchanged, a failed export changing nothing,
the export cache, the histogram and the panel drawing without writing data, and EEVEE and Cycles renders with levels
equal to renders of a filtered texture. The filter without Blender (orm_levels_filter.py, Session 7): its decode reads
what Blender reads (every filter type, Adam7), and in a plain Python it gives the exporter's bytes.

The expected pixels come from this file's own formula, PNG writer and PNG reader, not from orm_levels.

To run:
G:\\e-jets-e2\\tools\\blender\\blender.exe -b --factory-startup --python tests/test_orm_levels.py
"""

import hashlib
import json
import shutil
import struct
import sys
import zlib
from pathlib import Path
from types import SimpleNamespace

import addon_utils
import bpy
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
ADDON = 'io_scene_gltf2_msfs_fss'

# The portable Blender enables its deployed addons_core copy at startup: disable and purge it, then import the
# repository's module first, so addon_utils enables that one
if addon_utils.check(ADDON)[1]:
    addon_utils.disable(ADDON)
for mod in list(sys.modules.keys()):
    if mod == ADDON or mod.startswith(ADDON + '.'):
        del sys.modules[mod]
repo_root_str = str(REPO_ROOT)
while repo_root_str in sys.path:
    sys.path.remove(repo_root_str)
sys.path.insert(0, repo_root_str)

import io_scene_gltf2_msfs_fss  # noqa: E402,F401

addon_utils.enable(ADDON, default_set=True)
assert Path(sys.modules[ADDON].__file__).resolve().is_relative_to(REPO_ROOT), sys.modules[ADDON].__file__

from io_scene_gltf2_msfs_fss import orm_levels as ol  # noqa: E402
from io_scene_gltf2_msfs_fss import material_preview as mp  # noqa: E402

SCRATCH = REPO_ROOT / 'tests' / '_work' / 'orm_levels_scratch'
TEX = SCRATCH / 'tex'
ORM_NODE = 'Occlusion (R), Roughness (G), Metallic (B)'
DETAIL_NODE = 'Detail Occlusion (R), Roughness (G), Metallic (B)'
OMR_GROUP = '.Occlusion Metallic Roughness Group'
ORM_ATTR = 'msfs_occlusion_metallic_roughness_texture'
DETAIL_ATTR = 'msfs_detail_occlusion_metallic_roughness_texture'
CHANNELS = ('occlusion', 'roughness', 'metallic')
FIELDS = ('in_black', 'gamma', 'in_white', 'out_black', 'out_white')


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print('PASS:', message)


# region This file's own formula and PNG code

def formula(x, levels):
    """The journal's formula (decision 4) on floats x in 0..1."""
    in_black, gamma, in_white, out_black, out_white = levels
    x = np.asarray(x, dtype=np.float64)
    if in_white <= in_black:
        t = np.where(x >= in_black, 1.0, 0.0)
    else:
        t = np.minimum(np.maximum((x - in_black) / (in_white - in_black), 0.0), 1.0)
    return out_black + (out_white - out_black) * np.power(t, 1.0 / gamma)


def expected_ints(values, levels, maximum):
    """The formula on integers of depth `maximum`, rounded to the nearest integer (halves up)."""
    return np.floor(formula(np.asarray(values) / maximum, levels) * maximum + 0.5).astype(np.int64)


def png_chunk(tag, data):
    return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data))


def filter_row(kind, line, previous, bpp):
    """PNG filter `kind` (0 to 4) on the row bytes `line`, `previous` the row above (unfiltered)."""
    out = bytearray(len(line))
    for i in range(len(line)):
        a = line[i - bpp] if i >= bpp else 0
        b = previous[i]
        c = previous[i - bpp] if i >= bpp else 0
        if kind == 0:
            predictor = 0
        elif kind == 1:
            predictor = a
        elif kind == 2:
            predictor = b
        elif kind == 3:
            predictor = (a + b) // 2
        else:
            p = a + b - c
            pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
            predictor = a if pa <= pb and pa <= pc else b if pb <= pc else c
        out[i] = (line[i] - predictor) & 0xFF
    return bytes(out)


def filtered_stream(pixels, depth, filters):
    """The filtered rows of `pixels`, row y with filter type filters(y)."""
    height, width, channels = pixels.shape
    bpp = channels * depth // 8
    stream, previous = b'', bytes(width * bpp)
    for y in range(height):
        line = pixels[y].astype('>u2' if depth == 16 else np.uint8).tobytes()
        kind = filters(y)
        stream += bytes([kind]) + filter_row(kind, line, previous, bpp)
        previous = line
    return stream


def write_png(path, pixels, depth, color_type, filters=lambda y: 0, interlace=False):
    """`pixels`: rows top to bottom x columns x channels, integers; row y with filter type filters(y) (default 0 on
    every row); with `interlace` written in the seven Adam7 passes."""
    height, width, channels = pixels.shape
    if interlace:
        raw = b''
        for x0, y0, dx, dy in ((0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2),
                               (0, 1, 1, 2)):
            part = pixels[y0::dy, x0::dx]
            if part.size:
                raw += filtered_stream(part, depth, filters)
    else:
        raw = filtered_stream(pixels, depth, filters)
    data = (b'\x89PNG\r\n\x1a\n' + png_chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, depth, color_type, 0, 0,
                                                                  1 if interlace else 0))
            + png_chunk(b'IDAT', zlib.compress(raw)) + png_chunk(b'IEND', b''))
    Path(path).write_bytes(data)
    return data


def blender_decode(data):
    """The PNG's pixels as Blender reads them (rows top to bottom x columns x the file's channels): the exporter's
    decode before the filter moved into orm_levels_filter (ORM levels journal, Session 7)."""
    width, height, depth, color_type, _c, _f, _interlace = struct.unpack('>IIBBBBB', data[16:29])
    maximum = 65535 if depth == 16 else 255
    path = SCRATCH / 'blender_decode.png'
    path.write_bytes(data)
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        image.colorspace_settings.name = 'Non-Color'
        image.alpha_mode = 'CHANNEL_PACKED'
        buffer = np.empty(width * height * 4, np.float32)
        image.pixels.foreach_get(buffer)
    finally:
        bpy.data.images.remove(image)
    rgba = np.floor(buffer.reshape(height, width, 4)[::-1].astype(np.float64) * maximum + 0.5).astype(np.int64)
    return rgba[..., {0: [0], 2: [0, 1, 2], 4: [0, 3], 6: [0, 1, 2, 3]}[color_type]]


def read_png(data):
    """(pixels rows top to bottom x columns x channels, depth, colour type) of a non-interlaced 8/16-bit PNG, every
    filter type, in plain Python."""
    assert data[:8] == b'\x89PNG\r\n\x1a\n', 'not a PNG'
    position, idat, header = 8, b'', None
    while position < len(data):
        length, tag = struct.unpack('>I4s', data[position:position + 8])
        payload = data[position + 8:position + 8 + length]
        if tag == b'IHDR':
            header = struct.unpack('>IIBBBBB', payload)
        elif tag == b'IDAT':
            idat += payload
        position += 12 + length
    width, height, depth, color_type, _c, _f, interlace = header
    assert interlace == 0
    channels = {0: 1, 2: 3, 4: 2, 6: 4}[color_type]
    bpp = channels * depth // 8
    stride = width * bpp
    raw = zlib.decompress(idat)
    rows, previous = [], bytearray(stride)
    for y in range(height):
        kind = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = previous[i]
            c = previous[i - bpp] if i >= bpp else 0
            if kind == 1:
                line[i] = (line[i] + a) & 0xFF
            elif kind == 2:
                line[i] = (line[i] + b) & 0xFF
            elif kind == 3:
                line[i] = (line[i] + (a + b) // 2) & 0xFF
            elif kind == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 0xFF
        rows.append(bytes(line))
        previous = line
    buffer = np.frombuffer(b''.join(rows), dtype='>u2' if depth == 16 else np.uint8).astype(np.int64)
    return buffer.reshape(height, width, channels), depth, color_type

# endregion


# region Scene helpers

RNG = np.random.default_rng(20261114)
SOURCES = {}  # stem -> (pixels, depth, colour type)


def source(stem, depth, color_type, size=16):
    channels = {0: 1, 2: 3, 4: 2, 6: 4}[color_type]
    maximum = 65535 if depth == 16 else 255
    pixels = RNG.integers(0, maximum + 1, size=(size, size, channels))
    pixels[0, 0, :] = 0
    pixels[0, 1, :] = maximum
    path = TEX / f'{stem}.png'
    path.parent.mkdir(parents=True, exist_ok=True)
    write_png(path, pixels, depth, color_type)
    SOURCES[stem] = (pixels, depth, color_type)
    return path


def uniform(stem, rgb, size=8):
    pixels = np.empty((size, size, 3), np.int64)
    pixels[:] = [round(v * 255) for v in rgb]
    path = TEX / f'{stem}.png'
    path.parent.mkdir(parents=True, exist_ok=True)
    write_png(path, pixels, 8, 2)
    return path


def load(stem):
    image = bpy.data.images.load(str(TEX / f'{stem}.png'), check_existing=True)
    image.colorspace_settings.name = 'Non-Color'
    return image


def set_levels(image, levels):
    for channel, values in zip(CHANNELS, levels):
        group = getattr(image.fss_orm_levels, channel)
        for field, value in zip(FIELDS, values):
            setattr(group, field, value)


def new_material(name, orm=None, detail=None, material_type='msfs_standard'):
    material = bpy.data.materials.new(name)
    material.msfs_material_type = material_type
    if orm is not None:
        setattr(material, ORM_ATTR, load(orm))
    if detail is not None:
        setattr(material, DETAIL_ATTR, load(detail))
    return material


def sha(path):
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()


def strip_levels(material):
    """The tree as the add-on built it before the ORM levels: texture straight to its readers."""
    nodes, links = material.node_tree.nodes, material.node_tree.links
    for texture_name, levels_name in ol.LEVELS_NODES.items():
        node, texture = nodes.get(levels_name), nodes.get(texture_name)
        if node is None:
            continue
        targets = [link.to_socket for link in node.outputs[0].links]
        nodes.remove(node)
        for target in targets:
            links.new(texture.outputs[0], target)


def readers(material, texture_name):
    texture = material.node_tree.nodes[texture_name]
    return [(link.to_node.name, link.to_socket.identifier) for link in texture.outputs[0].links]


def source_of(socket):
    return socket.links[0].from_node.name if socket.is_linked else None

# endregion


LEVELS_8 = ((0.1, 1.6, 0.9, 0.05, 0.95), (0.2, 0.7, 0.8, 0.0, 1.0), (0.5, 1.0, 0.5, 0.2, 0.8))
LEVELS_16 = ((0.0, 2.2, 0.75, 0.1, 1.0), (0.3, 1.0, 1.0, 0.0, 0.6), (0.05, 0.45, 0.95, 0.25, 0.75))
LEVELS_DETAIL = ((0.0, 1.0, 1.0, 0.0, 0.5), (0.0, 1.0, 1.0, 0.25, 0.75), (0.4, 1.3, 0.6, 0.0, 1.0))


def test_formula():
    print('--- formula')
    for maximum in (255, 65535):
        values = np.arange(maximum + 1)
        check(np.array_equal(ol.apply_levels(values, ol.DEFAULT, maximum), values),
              f'the defaults change no value of depth {maximum}')
        for levels in LEVELS_8 + LEVELS_16 + LEVELS_DETAIL:
            check(np.array_equal(ol.apply_levels(values, levels, maximum), expected_ints(values, levels, maximum)),
                  f'depth {maximum}, levels {levels}: the formula on every value')
    check(ol.apply_levels(np.array([127, 128]), (0.5, 1.0, 0.5, 0.0, 1.0), 255).tolist() == [0, 255]
          and ol.apply_levels(np.array([127, 128]), (0.6, 1.0, 0.4, 0.0, 1.0), 255).tolist() == [0, 0],
          'input white <= input black: 1 at or above input black, else 0')
    check(abs(ol.gamma_marker((0.2, 2.0, 0.6, 0.0, 1.0)) - (0.2 + 0.4 * 0.25)) < 1e-12,
          'the gamma marker is the input value that becomes the middle of the output')
    # The node values give the same as the formula (what the preview computes)
    x = np.linspace(0.0, 1.0, 1001)
    for levels in LEVELS_8 + LEVELS_16:
        values = ol.node_values((levels, levels, levels))
        nodes = np.clip(x * values['Scale'][0] + values['Bias'][0], 0, 1) ** values['Inverse Gamma'][0]
        nodes = values['Output Black'][0] + values['Output Range'][0] * nodes
        reference = formula(x, levels)
        if levels[2] <= levels[0]:  # the step: the nodes ramp over 1e-5 below input black
            keep = np.abs(x - levels[0]) > 2e-5
            nodes, reference = nodes[keep], reference[keep]
        check(np.max(np.abs(nodes - reference)) < 1e-9, f'the node values reproduce the formula for {levels}')


def test_png():
    print('--- PNG')
    for depth, color_type in ((8, 0), (8, 2), (8, 4), (8, 6), (16, 0), (16, 2), (16, 4), (16, 6)):
        path = source(f'png_{depth}_{color_type}', depth, color_type, size=12)
        data = path.read_bytes()
        pixels, header = ol.decode_png(data)
        check(np.array_equal(pixels, SOURCES[path.stem][0]) and header[2:4] == (depth, color_type),
              f'{depth}-bit colour type {color_type}: decoded exactly')
        levels = ((0.1, 1.5, 0.9, 0.0, 1.0),) * 3
        out, out_depth, out_type = read_png(ol.filter_png(data, levels))
        expected = SOURCES[path.stem][0].copy()
        expected[..., 0] = expected_ints(expected[..., 0], levels[0], 65535 if depth == 16 else 255)
        if color_type in (2, 6):
            for c in (1, 2):
                expected[..., c] = expected_ints(expected[..., c], levels[c], 65535 if depth == 16 else 255)
        check(np.array_equal(out, expected) and (out_depth, out_type) == (depth, color_type),
              f'{depth}-bit colour type {color_type}: filtered pixels, depth and colour type')
        identity, _d, _t = read_png(ol.filter_png(data, ol.DEFAULTS))
        check(np.array_equal(identity, SOURCES[path.stem][0]), f'{depth}-bit colour type {color_type}: defaults keep every pixel')
        # The decode without Blender (orm_levels_filter) reads what Blender reads, for every filter type and Adam7,
        # so the exporter's filtered bytes are those of the decode through Blender before Session 7
        reference = blender_decode(data)
        check(np.array_equal(reference, SOURCES[path.stem][0]), f'{depth}-bit colour type {color_type}: Blender reads '
                                                                 'the source exactly (the reference)')
        filtered = ol.filter_png(data, levels)
        for label, kwargs in (('filter type 1 on every row', {'filters': lambda y: 1}),
                              ('filter types 0 to 4 by row', {'filters': lambda y: y % 5}),
                              ('Adam7, filter types 0 to 4 by row', {'filters': lambda y: y % 5, 'interlace': True})):
            variant = write_png(SCRATCH / f'{path.stem}_variant.png', SOURCES[path.stem][0], depth, color_type, **kwargs)
            decoded, variant_header = ol.decode_png(variant)
            check(np.array_equal(decoded, SOURCES[path.stem][0]) and np.array_equal(decoded, blender_decode(variant))
                  and variant_header[4] == (1 if kwargs.get('interlace') else 0),
                  f'{depth}-bit colour type {color_type}, {label}: decoded exactly, as Blender reads it')
            check(ol.filter_png(variant, levels) == filtered,
                  f'{depth}-bit colour type {color_type}, {label}: the same filtered bytes as the plain source')
        check(np.array_equal(ol.decode_png(filtered)[0], read_png(filtered)[0]),
              f'{depth}-bit colour type {color_type}: the filtered PNG (filter types of the encoder) decodes as this '
              "file's reader reads it")
    grey = source('png_grey_mixed', 8, 0, size=4).read_bytes()
    try:
        ol.filter_png(grey, LEVELS_8)
        refused = False
    except ValueError:
        refused = True
    check(refused, 'a grey texture with different levels per channel is refused (one channel for three)')


def test_tree():
    print('--- preview nodes')
    bpy.ops.wm.read_homefile(use_empty=True)
    source('t_orm', 8, 2)
    source('t_detail', 8, 2)
    material = new_material('tree', 't_orm', 't_detail')
    nodes = material.node_tree.nodes
    omr = nodes[OMR_GROUP]
    check(source_of(omr.inputs[2]) == 'FSS ORM Levels' and source_of(omr.inputs[3]) == 'FSS Detail ORM Levels',
          'the ORM group reads both textures through the levels')
    check(readers(material, ORM_NODE) == [('FSS ORM Levels', 'Socket_0')] or
          [r[0] for r in readers(material, ORM_NODE)] == ['FSS ORM Levels'], 'the ORM texture feeds the levels only')
    check([r[0] for r in readers(material, DETAIL_NODE)] == ['FSS Detail ORM Levels'], 'the detail texture feeds its levels only')
    check(not any(n.bl_idname == 'ShaderNodeSeparateColor' for n in bpy.data.node_groups[ol.GROUP_NAME].nodes),
          'the levels group has no Separate Color (the exporter takes channels from those)')
    count = (len(nodes), len(material.node_tree.links))
    ol.apply_tree(material.node_tree)
    ol.apply_tree(material.node_tree)
    check((len(nodes), len(material.node_tree.links)) == count, 'a second run adds nothing')
    image = getattr(material, ORM_ATTR)
    set_levels(image, LEVELS_8)
    values = ol.node_values(LEVELS_8)
    node = nodes['FSS ORM Levels']
    check(all(np.allclose(tuple(node.inputs[k].default_value), v, atol=1e-6) for k, v in values.items()),
          'a value change reaches the levels node')
    check(all(np.allclose(tuple(nodes['FSS Detail ORM Levels'].inputs[k].default_value), v, atol=1e-6)
              for k, v in ol.node_values(ol.DEFAULTS).items()), 'the detail texture keeps its own (default) values')
    material.msfs_roughness_factor = 0.5
    material.msfs_metallic_factor = 0.7
    check(source_of(omr.inputs[2]) == 'FSS ORM Levels', "Asobo's relink (roughness and metallic scale) keeps the levels")
    setattr(material, ORM_ATTR, None)
    check(not omr.inputs[2].is_linked and nodes.get('FSS ORM Levels') is not None, 'no texture: nothing linked, the node stays')
    setattr(material, ORM_ATTR, image)
    check(source_of(omr.inputs[2]) == 'FSS ORM Levels', 'the texture comes back through the levels')
    check(len([n for n in nodes if n.name.startswith('FSS ORM Levels')]) == 1, 'one levels node per slot')

    coat = new_material('coat', 't_orm', None, 'msfs_clearcoat')
    coat.msfs_clearcoat_inverse_roughness = True
    separate = coat.node_tree.nodes[mp.COAT_PREFIX + 'OMR Separate']
    check(source_of(separate.inputs[0]) == 'FSS ORM Levels', 'the coat\'s Use Uniform Roughness reads the ORM through the levels')
    coat.msfs_clearcoat_roughness_factor = 0.4  # a coat rebuild
    separate = coat.node_tree.nodes[mp.COAT_PREFIX + 'OMR Separate']
    check(source_of(separate.inputs[0]) == 'FSS ORM Levels', '... also after a coat rebuild')

    # A file saved without the nodes (an older file) gets them on opening and from the operator
    bpy.ops.mesh.primitive_plane_add()
    bpy.context.active_object.data.materials.append(material)
    bpy.context.active_object.data.materials.append(coat)
    strip_levels(material)
    strip_levels(coat)
    check(nodes.get('FSS ORM Levels') is None and source_of(omr.inputs[2]) == ORM_NODE, 'stripped: no levels')
    blend = SCRATCH / 'old.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    reopened = bpy.data.materials['tree']
    omr = reopened.node_tree.nodes[OMR_GROUP]
    check(source_of(omr.inputs[2]) == 'FSS ORM Levels' and source_of(omr.inputs[3]) == 'FSS Detail ORM Levels',
          'opening the file adds the levels nodes')
    node = reopened.node_tree.nodes['FSS ORM Levels']
    check(all(np.allclose(tuple(node.inputs[k].default_value), v, atol=1e-6) for k, v in values.items()),
          'with the values stored on the image')
    check(source_of(bpy.data.materials['coat'].node_tree.nodes[mp.COAT_PREFIX + 'OMR Separate'].inputs[0]) == 'FSS ORM Levels',
          'the coat branch reads through the levels after opening')
    for name in ('tree', 'coat'):
        strip_levels(bpy.data.materials[name])
    check(bpy.ops.msfs_fss.update_material_nodes() == {'FINISHED'}, 'the operator finishes')
    reopened = bpy.data.materials['tree']
    check(source_of(reopened.node_tree.nodes[OMR_GROUP].inputs[2]) == 'FSS ORM Levels', 'the operator adds the levels nodes')
    count = {m.name: (len(m.node_tree.nodes), len(m.node_tree.links)) for m in bpy.data.materials if m.node_tree}
    bpy.ops.msfs_fss.update_material_nodes()
    check(count == {m.name: (len(m.node_tree.nodes), len(m.node_tree.links)) for m in bpy.data.materials if m.node_tree},
          'running it again changes nothing')
    check(len([g for g in bpy.data.node_groups if g.name.startswith(ol.GROUP_NAME)]) == 1, 'one levels group')


def test_shared():
    print('--- shared texture')
    bpy.ops.wm.read_homefile(use_empty=True)
    source('t_shared', 8, 2)
    a = new_material('uses_as_orm', 't_shared')
    b = new_material('uses_as_detail', None, 't_shared')
    image = getattr(a, ORM_ATTR)
    check(getattr(b, DETAIL_ATTR) == image, 'one image in both slots')
    set_levels(image, LEVELS_DETAIL)
    values = ol.node_values(LEVELS_DETAIL)
    for material, name in ((a, 'FSS ORM Levels'), (b, 'FSS Detail ORM Levels')):
        node = material.node_tree.nodes[name]
        check(all(np.allclose(tuple(node.inputs[k].default_value), v, atol=1e-6) for k, v in values.items()),
              f'{material.name}: a value change updates its levels node ({name})')
    check(len(ol.materials_using(image)) == 2, 'two material slots use the texture')
    out = SCRATCH / 'shared'
    export(None, 'fs24', out, scene_builder=lambda: shared_scene(a, b))
    gltf = json.loads((out / 'panel.gltf').read_text(encoding='utf8'))
    names = [Path(i['uri']).name for i in gltf.get('images', [])]
    files = [p.name for p in out.iterdir() if p.suffix == '.png']
    check(names.count('t_shared.png') == 1 and files == ['t_shared.png'], f'one exported texture file ({names}, {files})')
    pixels, _d, _t = read_png((out / 't_shared.png').read_bytes())
    expected = SOURCES['t_shared'][0].copy()
    for c in range(3):
        expected[..., c] = expected_ints(expected[..., c], LEVELS_DETAIL[c], 255)
    check(np.array_equal(pixels, expected), 'the file has the levels')


def shared_scene(a, b):
    objects = []
    for index, material in enumerate((a, b)):
        bpy.ops.mesh.primitive_grid_add(x_subdivisions=2, y_subdivisions=2, size=1, location=(index * 2, 0, 0))
        obj = bpy.context.active_object
        obj.name = f'PANEL_{index}'
        obj.data.materials.append(material)
        objects.append(obj)
    return objects


# region Export

def build_scene(levels):
    """Two panels: A with an 8-bit RGB ORM and an 8-bit RGBA detail ORM, B with a 16-bit RGBA ORM."""
    bpy.ops.wm.read_homefile(use_empty=True)
    a = new_material('MAT_A', 'orm8', 'detail8')
    b = new_material('MAT_B', 'orm16')
    a.msfs_occlusion_strength = 0.5
    if levels:
        set_levels(getattr(a, ORM_ATTR), LEVELS_8)
        set_levels(getattr(a, DETAIL_ATTR), LEVELS_DETAIL)
        set_levels(getattr(b, ORM_ATTR), LEVELS_16)
    return shared_scene(a, b)


def export(levels, mode, out_dir, strip=False, scene_builder=None, presets=1):
    """Export the scene (built here unless scene_builder) with `mode`: fs24 (multi-exporter), fs20, plain (File >
    Export, target 2024, no MSFS hooks as in a fresh session) or plain_msfs (File > Export with the MSFS hooks, as
    after a multi-export in the same session). Returns the glTF's material sections and every file's hash."""
    objects = scene_builder() if scene_builder else build_scene(levels)
    if strip:
        for material in bpy.data.materials:
            if material.node_tree is not None:
                strip_levels(material)
    scene = bpy.context.scene
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)
    from io_scene_gltf2_msfs_fss.io.exp import export_settings
    from io_scene_gltf2_msfs_fss.io.exp.gltf_hooks import Export
    original_filter = ol.filter_gltf_image
    if strip:
        ol.filter_gltf_image = lambda *args: False
    try:
        if mode == 'fs24':
            scene.msfs_fss_export_target = 'MSFS2024'
            scene.msfs_background_export = False
            scene.msfs_export_mode = 'PRESETS'
            export_settings.init_setting_presets(scene)
            settings = export_settings.get_active_export_settings(scene)
            settings.enable_msfs_extension = True
            settings.generate_texturelib = False
            settings.export_apply = True
            settings.export_keep_originals = False
            settings.export_texture_dir = ''
            collection = bpy.data.collections.new('FSS_EXPORT_MSFS2024')
            for obj in objects:
                collection.objects.link(obj)
            scene.collection.children.link(collection)
            for existing in scene.msfs_multi_exporter_presets:
                existing.enabled = False
            for index in range(presets):
                preset = scene.msfs_multi_exporter_presets.add()
                preset.preset_name = 'panel' if index == 0 else f'panel_{index}'
                preset.folder_path = str(out_dir)
                preset.enabled = True
                layer = preset.layers.add()
                layer.collection = collection
                layer.enabled = True
            bpy.ops.msfs2024.multi_export_gltf(export_mode='PRESETS')
        else:
            scene.msfs_fss_export_target = 'MSFS2020' if mode == 'fs20' else 'MSFS2024'
            if mode == 'plain':
                Export.msfs_export_settings = None
            elif mode == 'plain_msfs':
                export_settings.init_setting_presets(scene)
                settings = export_settings.get_active_export_settings(scene)
                settings.enable_msfs_extension = True
                Export.msfs_export_settings = settings
            bpy.ops.export_scene.gltf(filepath=str(out_dir / 'panel.gltf'), export_format='GLTF_SEPARATE',
                                      use_visible=True, export_image_format='AUTO')
    finally:
        ol.filter_gltf_image = original_filter
        Export.msfs_export_settings = None
    files = {p.name: hashlib.md5(p.read_bytes()).hexdigest() for p in out_dir.iterdir() if p.suffix != '.gltf'}
    gltf = json.loads((out_dir / 'panel.gltf').read_text(encoding='utf8'))
    sections = {k: gltf.get(k) for k in ('materials', 'textures', 'images', 'samplers', 'extensionsUsed',
                                         'extensionsRequired', 'meshes', 'nodes')}
    return sections, files


MODES = (('fs24', 'MSFS 2024 multi-exporter'), ('fs20', 'MSFS 2020'), ('plain', 'File > Export, target 2024'),
         ('plain_msfs', 'File > Export, target 2024, MSFS hooks'))


def make_sources():
    source('orm8', 8, 2)
    source('orm16', 16, 6)
    source('detail8', 8, 6)


def test_exports_default():
    print('--- exports at the defaults')
    for mode, label in MODES:
        before, before_files = export(False, mode, SCRATCH / f'{mode}_before', strip=True)
        after, after_files = export(False, mode, SCRATCH / f'{mode}_after')
        check(after == before, f'{label}: same glTF as the tree without the levels')
        check(after_files == before_files, f'{label}: same files ({sorted(after_files)})')


def test_exports_adjusted():
    print('--- exports with levels')
    hashes = {stem: sha(TEX / f'{stem}.png') for stem in ('orm8', 'orm16', 'detail8')}
    levels = {'orm8': LEVELS_8, 'orm16': LEVELS_16, 'detail8': LEVELS_DETAIL}
    for mode, label in MODES:
        out = SCRATCH / f'{mode}_levels'
        sections, files = export(True, mode, out)
        names = sorted(Path(i['uri']).name for i in sections.get('images') or [])
        print(f'INFO: {label}: images {names}')
        expected_names = {'orm8.png', 'orm16.png'} | ({'detail8.png'} if mode != 'plain' else set())
        check(expected_names <= set(names), f'{label}: the ORM textures are exported ({names})')
        for name in sorted(expected_names):
            stem = Path(name).stem
            pixels, depth, color_type = read_png((out / name).read_bytes())
            src, src_depth, src_type = SOURCES[stem]
            maximum = 65535 if src_depth == 16 else 255
            expected = src.copy()
            for c in range(3):
                expected[..., c] = expected_ints(src[..., c], levels[stem][c], maximum)
            check((depth, color_type, pixels.shape) == (src_depth, src_type, src.shape),
                  f'{label}: {name} keeps {src_depth} bits, colour type {src_type}, size {src.shape[1]}x{src.shape[0]}')
            check(np.array_equal(pixels, expected), f'{label}: every pixel of {name} is the formula of its source pixel')
            if src.shape[2] == 4:
                check(np.array_equal(pixels[..., 3], src[..., 3]), f'{label}: {name} keeps its alpha')
        check({stem: sha(TEX / f'{stem}.png') for stem in hashes} == hashes, f'{label}: the source files are unchanged')
        for image in bpy.data.images:
            check(not image.is_dirty, f'{label}: image {image.name} not changed in Blender')


def snapshot():
    """Every material (properties, nodes and their inputs, links), image (settings, levels, pixels), node group."""
    def value(v):
        if isinstance(v, bpy.types.ID):
            return 'ID:' + v.name_full
        if hasattr(v, '__len__') and not isinstance(v, str):
            try:
                return tuple(round(x, 6) if isinstance(x, float) else x for x in v)
            except TypeError:
                return str(v)
        return round(v, 6) if isinstance(v, float) else v

    def props(owner):
        out = {}
        for prop in owner.bl_rna.properties:
            if prop.identifier in ('rna_type', 'session_uid') or prop.type == 'COLLECTION':  # identity, not content
                continue
            if prop.type == 'POINTER':
                v = getattr(owner, prop.identifier, None)
                out[prop.identifier] = ('ID:' + v.name_full) if isinstance(v, bpy.types.ID) else type(v).__name__
                continue
            try:
                out[prop.identifier] = value(getattr(owner, prop.identifier))
            except Exception:
                pass
        return out

    def tree(node_tree):
        if node_tree is None:
            return None
        nodes = {}
        for node in node_tree.nodes:
            inputs = []
            for socket in node.inputs:
                inputs.append((socket.identifier, value(getattr(socket, 'default_value', None))))
            nodes[node.name] = (node.bl_idname, tuple(inputs), getattr(getattr(node, 'node_tree', None), 'name', None),
                                getattr(getattr(node, 'image', None), 'name', None))
        links = sorted((l.from_node.name, l.from_socket.identifier, l.to_node.name, l.to_socket.identifier)
                       for l in node_tree.links)
        return nodes, links

    result = {'materials': {}, 'images': {}, 'groups': {}}
    for material in bpy.data.materials:
        result['materials'][material.name] = (props(material), tree(material.node_tree))
    for image in bpy.data.images:
        pixels = None
        if image.size[0]:
            buffer = np.empty(image.size[0] * image.size[1] * image.channels, np.float32)
            image.pixels.foreach_get(buffer)
            pixels = hashlib.sha1(buffer.tobytes()).hexdigest()
        result['images'][image.name] = (image.filepath, image.is_dirty, image.colorspace_settings.name, image.alpha_mode,
                                        ol.levels_of(image), pixels)
    for group in bpy.data.node_groups:
        result['groups'][group.name] = tree(group)
    return result


def test_failed_export():
    print('--- failed export')
    # Khronos catches exceptions raised in user extension hooks and finishes the export, so the export is made to fail
    # where it writes the images, after every material and image was gathered (and filtered)
    from io_scene_gltf2.blender.exp.exporter import GlTF2Exporter
    original = GlTF2Exporter.finalize_images

    def failing(self, *args):
        raise RuntimeError('test: the export fails while writing the images')

    def changes(before, after):
        return {kind: sorted(k for k in set(before[kind]) | set(after[kind]) if before[kind].get(k) != after[kind].get(k))
                for kind in ('materials', 'images', 'groups')}

    def fail(mode, levels, strip):
        objects = build_scene(levels)
        if strip:
            for material in bpy.data.materials:
                strip_levels(material)
        before = snapshot()
        filtered = ol.stats['filtered'] + ol.stats['cached']
        GlTF2Exporter.finalize_images = failing
        original_filter = ol.filter_gltf_image
        if strip:
            ol.filter_gltf_image = lambda *args: False
        failed = False
        try:
            export(levels, mode, SCRATCH / f'{mode}_failed', scene_builder=lambda: objects)
        except Exception as error:
            failed = True
        finally:
            GlTF2Exporter.finalize_images = original
            ol.filter_gltf_image = original_filter
        return before, failed, ol.stats['filtered'] + ol.stats['cached'] - filtered

    for mode, label in MODES:
        before, failed, filtered = fail(mode, True, False)
        print(f'INFO: {label}: the export failed {failed} (the multi-exporter logs it, File > Export raises); textures filtered before '
              f'the failure: {filtered}')
        expected = 2 if mode == 'plain' else 3  # without the MSFS hooks the detail ORM is not exported
        check(filtered >= expected, f'{label}: the failure comes after the {expected} textures were filtered '
                                    f'({filtered} filter calls, cache hits included)')
        changed = changes(before, snapshot())
        if not any(changed.values()):
            for kind, names in changed.items():
                check(not names, f'{label}: a failed export leaves the {kind} as before')
            continue
        # Changes the export path makes without the ORM levels too: compare with the same failure on the tree
        # without the levels nodes and with the filter off
        print(f'INFO: {label}: changed after the failure: {changed}')
        _before, _failed, _filtered = fail(mode, False, True)
        baseline = changes(_before, snapshot())
        print(f'INFO: {label}: without the ORM levels the same failure changes {baseline}')
        check(baseline == changed, f'{label}: the same change without the ORM levels (not caused by them)')
        if mode == 'fs20':
            # The MSFS 2020 export swaps in temporary MSFS 2020 trees and restores them in post_export_hook, which a
            # failed export does not reach; the next export restores them first (legacy_tree.build_legacy_trees)
            from io_scene_gltf2_msfs_fss._msfs2020.blender import legacy_tree
            before, _failed, _filtered = fail(mode, True, False)
            legacy_tree.restore_trees()
            changed = changes(before, snapshot())
            check(not changed['materials'] and not changed['images'],
                  f'{label}: after the restore the next export does first, every material and image is as before')
            check(changed['groups'] == ['glTF Settings'] and 'glTF Settings' not in before['groups'],
                  f'{label}: ... and every node group; the MSFS 2020 tree added its glTF Settings group')
        else:
            new = [name for kind in changed for name in changed[kind] if name not in before[kind]]
            check(all(name.startswith('temp_image_export_mat') for name in new) and len(new) == sum(map(len, changed.values())),
                  f'{label}: only new temporary materials of the MSFS 2024 image export are left ({len(new)}); every '
                  f'existing material, image and node group is as before')


def test_cache():
    print('--- export cache')
    ol.clear_cache()
    first = export(True, 'fs24', SCRATCH / 'cache_1', presets=2)
    counted = dict(ol.stats)
    print(f'INFO: first export (two presets): {counted}')
    check(counted['filtered'] == 3, f'the first export filters each texture once (3 textures, {counted["filtered"]} filtered)')
    second = export(True, 'fs24', SCRATCH / 'cache_2', presets=2)
    print(f'INFO: second export: {ol.stats}')
    check(ol.stats['filtered'] == 3, 'a second export of the same scene filters no texture again')
    check(second[1] == first[1] and second[0] == first[0], 'and writes identical files')


# endregion


# region Histogram and panel

class _Layout:
    """Records what a panel draws (background Blender has no UI to draw into)."""

    def __init__(self, calls):
        self.calls = calls

    def __bool__(self):
        return True

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if name == 'panel':
                return (self, self)
            if name in ('row', 'column', 'box', 'split'):
                return self
            if name in ('operator', 'template_ID', 'template_ID_preview'):
                return SimpleNamespace()
            return None
        return call


def test_histogram_and_panel():
    print('--- histogram and panel')
    bpy.ops.wm.read_homefile(use_empty=True)
    for stem in ('orm8', 'orm16'):
        image = load(stem)
        pixels, depth, _t = SOURCES[stem]
        maximum = 65535 if depth == 16 else 255
        counts, minimum, top = ol.histogram(image)
        for c in range(3):
            bins = np.floor(pixels[..., c] * 255.0 / maximum + 0.5).astype(np.int64)
            reference, _edges = np.histogram(bins, bins=256, range=(-0.5, 255.5))
            check(np.array_equal(counts[c], reference), f'{stem} channel {c}: the counts equal a numpy histogram')
            check(abs(minimum[c] - pixels[..., c].min() / maximum) < 1e-6 and abs(top[c] - pixels[..., c].max() / maximum) < 1e-6,
                  f'{stem} channel {c}: minimum and maximum')
        image_pixels = ol.histogram_pixels(counts[0], (0.2, 1.0, 0.8, 0.0, 1.0), 0)
        check(len(image_pixels) == ol.HIST_SIZE * ol.HIST_SIZE * 4, 'the histogram image has its size')

    with_textures = new_material('with', 'orm8', 'orm16')
    set_levels(getattr(with_textures, ORM_ATTR), LEVELS_8)
    without = new_material('without')
    plain = bpy.data.materials.new('not_msfs')
    from io_scene_gltf2_msfs_fss.blender.material.msfs_material_panel import MSFS2024_PT_Material
    for material in (with_textures, without, plain):
        before = snapshot()
        counts_before = (len(bpy.data.images), len(bpy.data.materials), len(bpy.data.node_groups))
        calls = []
        context = SimpleNamespace(active_object=SimpleNamespace(active_material=material))
        MSFS2024_PT_Material.draw(SimpleNamespace(layout=_Layout(calls)), context)
        check(snapshot() == before and counts_before == (len(bpy.data.images), len(bpy.data.materials), len(bpy.data.node_groups)),
              f'{material.name}: the panel draws without writing data')
        props = [args[1] for name, args, _kw in calls if name == 'prop' and len(args) > 1]
        labels = [kw.get('text') for name, _a, kw in calls if name == 'label']
        levels_drawn = props.count('in_black')
        expected = 6 if material is with_textures else 0
        check(levels_drawn == expected, f'{material.name}: {levels_drawn} channels with levels drawn (expected {expected})')
        if material is with_textures:
            check(all(props.count(f) == 6 for f in FIELDS), 'five sliders per channel')
            check('Levels (adjusted)' in labels and 'Levels' in labels, 'the header tells an adjusted texture')
            check(any(text and text.startswith('Texture ') and ', result ' in text for text in labels),
                  'the result range is shown')
            check(any(text and 'Occlusion (R)' == text for text in labels), 'the channels are labelled')


# endregion


# region Render

def render(scene, engine, path):
    scene.render.engine = engine
    scene.render.resolution_x = scene.render.resolution_y = 16
    scene.render.image_settings.file_format = 'PNG'
    scene.view_settings.view_transform = 'Standard'
    if engine == 'CYCLES':
        scene.cycles.samples = 64
        scene.cycles.device = 'CPU'
        scene.cycles.use_denoising = False
        scene.cycles.seed = 0
    else:
        scene.eevee.taa_render_samples = 16
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    loaded = bpy.data.images.load(str(path), check_existing=False)
    buffer = np.empty(16 * 16 * 4, np.float32)
    loaded.pixels.foreach_get(buffer)
    bpy.data.images.remove(loaded)
    return buffer.reshape(16, 16, 4)[..., :3]


def test_render():
    """A plane under a white sky with a uniform ORM: with levels, against the texture filtered by this file's formula
    with the levels at their defaults."""
    print('--- render')
    levels = ((0.1, 1.5, 0.9, 0.0, 0.4), (0.4, 0.8, 1.0, 0.0, 0.3), (0.0, 0.5, 0.4, 0.1, 1.0))
    rgb = (0.7, 0.5, 0.3)
    uniform('u_adjusted', rgb)
    filtered = [float(np.floor(formula(round(v * 255) / 255, lv) * 255 + 0.5)) / 255 for v, lv in zip(rgb, levels)]
    uniform('u_filtered', filtered)
    print(f'INFO: ORM {rgb} -> filtered {[round(v, 4) for v in filtered]}')
    bpy.ops.wm.read_homefile(use_empty=True)
    scene = bpy.context.scene
    world = bpy.data.worlds.new('world')
    world.use_nodes = True
    world.node_tree.nodes['Background'].inputs[0].default_value = (1, 1, 1, 1)
    scene.world = world
    sun = bpy.data.objects.new('sun', bpy.data.lights.new('sun', 'SUN'))
    sun.data.energy = 3.0
    sun.rotation_euler = (0.6, 0.2, 0.0)
    scene.collection.objects.link(sun)
    bpy.ops.mesh.primitive_plane_add(size=40)
    plane = bpy.context.active_object
    camera = bpy.data.objects.new('camera', bpy.data.cameras.new('camera'))
    scene.collection.objects.link(camera)
    camera.location = (0, -6, 2)
    camera.rotation_euler = (1.25, 0, 0)
    scene.camera = camera

    def setup(name, stem, adjusted):
        material = bpy.data.materials.new(name)
        material.msfs_material_type = 'msfs_standard'
        material.msfs_base_color_factor = (0.8, 0.5, 0.3, 1)
        setattr(material, ORM_ATTR, load(stem))
        if adjusted:
            set_levels(getattr(material, ORM_ATTR), levels)
        plane.data.materials.clear()
        plane.data.materials.append(material)

    results = {}
    for name, stem, adjusted in (('adjusted', 'u_adjusted', True), ('filtered', 'u_filtered', False),
                                 ('unadjusted', 'u_adjusted', None)):
        if adjusted is None:
            set_levels(load('u_adjusted'), ol.DEFAULTS)
            adjusted = False
        setup(name, stem, adjusted)
        results[name] = [render(scene, engine, SCRATCH / f'render_{name}_{engine}.png')
                         for engine in ('BLENDER_EEVEE', 'CYCLES')]
    for index, engine in enumerate(('EEVEE', 'Cycles')):
        difference = np.abs(results['adjusted'][index] - results['filtered'][index]).max()
        effect = np.abs(results['unadjusted'][index] - results['filtered'][index]).max()
        print(f'INFO: {engine}: levels vs filtered texture max {difference * 255:.2f}/255; the levels change the '
              f'render by up to {effect * 255:.1f}/255')
        check(effect * 255 > 10, f'{engine}: the levels visibly change the render ({effect * 255:.1f}/255)')
        check(difference <= 2 / 255, f'{engine}: levels render within 2/255 of the filtered texture '
                                     f'({difference * 255:.2f}/255)')

# endregion


PLAIN_PYTHON = Path(r'G:\e-jets-e2\tools\blender\5.2\python\bin\python.exe')
PLAIN_SCRIPT = r'''
import hashlib, importlib.util, json, sys
spec = importlib.util.spec_from_file_location('orm_levels_filter_plain', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
results = []
for case in json.load(open(sys.argv[2], encoding='utf-8')):
    levels = tuple(tuple(values) for values in case['levels'])
    data = module.filter_png(open(case['source'], 'rb').read(), levels)
    expected = open(case['expected'], 'rb').read()
    results.append({'label': case['label'], 'equal': data == expected, 'sha1': hashlib.sha1(data).hexdigest()})
print(json.dumps({'bpy': 'bpy' in sys.modules, 'addon': [m for m in sys.modules if 'io_scene_gltf2' in m],
                  'numpy': 'numpy' in sys.modules, 'results': results}))
'''


def test_plain_python():
    """orm_levels_filter in a plain Python (no Blender): the exporter's bytes for the 8- and 16-bit cases."""
    import subprocess
    print('--- the filter in plain Python')
    check(PLAIN_PYTHON.is_file(), f'the plain Python {PLAIN_PYTHON}')
    cases = []
    levels = ((0.1, 1.5, 0.9, 0.0, 1.0),) * 3
    for depth, color_type in ((8, 0), (8, 2), (8, 4), (8, 6), (16, 0), (16, 2), (16, 4), (16, 6)):
        stem = f'png_{depth}_{color_type}'
        expected = SCRATCH / f'{stem}_filtered.png'
        expected.write_bytes(ol.filter_png((TEX / f'{stem}.png').read_bytes(), levels))  # the exporter's filter
        cases.append({'label': f'{depth}-bit colour type {color_type}', 'source': str(TEX / f'{stem}.png'),
                      'levels': levels, 'expected': str(expected)})
    stems = {'orm8': LEVELS_8, 'orm16': LEVELS_16, 'detail8': LEVELS_DETAIL}
    for mode, label in MODES:
        for stem, stem_levels in stems.items():
            exported = SCRATCH / f'{mode}_levels' / f'{stem}.png'
            if exported.is_file():  # written by test_exports_adjusted: the exporter's bytes
                # The values as Blender stores them (float32), as the exporter used them and lists them
                cases.append({'label': f'{label}: {stem}.png', 'source': str(TEX / f'{stem}.png'),
                              'levels': [[float(np.float32(v)) for v in values] for values in stem_levels],
                              'expected': str(exported)})
    check(len(cases) == 8 + 11, f'{len(cases)} cases: the 8 colour types and the 11 textures exported with levels')
    (SCRATCH / 'plain_cases.json').write_text(json.dumps(cases), encoding='utf-8')
    filter_path = REPO_ROOT / ADDON / 'orm_levels_filter.py'
    result = subprocess.run([str(PLAIN_PYTHON), '-I', '-B', '-c', PLAIN_SCRIPT, str(filter_path),
                             str(SCRATCH / 'plain_cases.json')], capture_output=True, text=True, cwd=str(SCRATCH))
    check(result.returncode == 0, f'plain Python exit {result.returncode} {result.stderr[-2000:]}')
    report = json.loads(result.stdout.strip().splitlines()[-1])
    check(not report['bpy'] and not report['addon'] and report['numpy'],
          f'plain Python: no bpy, nothing of the add-on imported, numpy ({report["addon"]})')
    for item in report['results']:
        check(item['equal'], f'plain Python, {item["label"]}: the exporter\'s bytes ({item["sha1"][:8]})')


TESTS = (test_formula, test_png, test_tree, test_shared, test_exports_default, test_exports_adjusted,
         test_plain_python, test_failed_export, test_cache, test_histogram_and_panel, test_render)
# "-- only=test_cache,test_render" runs those tests alone
ARGS = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
ONLY = next((a.split('=', 1)[1].split(',') for a in ARGS if a.startswith('only=')), None)
shutil.rmtree(SCRATCH, ignore_errors=True)
SCRATCH.mkdir(parents=True)
make_sources()
for test in TESTS:
    if ONLY is None or test.__name__ in ONLY:
        test()
print('ALL ORM LEVELS TESTS PASSED' if ONLY is None else f'ORM LEVELS TESTS PASSED: {", ".join(ONLY)}')
