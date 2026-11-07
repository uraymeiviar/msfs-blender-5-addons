"""Texture Sets sub-panel (material-management journal, Session 33): the role table against the exporter's slots and
types, the rows the Materials Refresh fills from PNG headers (roles per type, secondary maps with a blend mask, slots the
type does not use, missing and other files, packed images), the channel tokens and their warnings (unused channels, 16-bit
need per role and type, alpha of an Opaque albedo, grey files), Check Data Depth (real 16-bit, 8-bit data in 16 bits,
flat channels, results kept and reused until the file changes, exact values), and that drawing writes nothing.

To run:
G:\\e-jets-e2\\tools\\blender\\blender.exe -b --factory-startup --python tests/test_texture_sets.py
"""

import os
import shutil
import struct
import sys
import time
import zlib
from pathlib import Path
from types import SimpleNamespace

import addon_utils
import bpy
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
ADDONS = ('io_scene_gltf2_msfs_fss', 'fss_blender_tools')

# The portable Blender enables its deployed addons_core copies at startup: disable and purge them, then import the
# repository modules first, so addon_utils enables those
for name in reversed(ADDONS):
    if addon_utils.check(name)[1]:
        addon_utils.disable(name)
    for mod in list(sys.modules.keys()):
        if mod == name or mod.startswith(name + '.'):
            del sys.modules[mod]
repo_root_str = str(REPO_ROOT)
while repo_root_str in sys.path:
    sys.path.remove(repo_root_str)
sys.path.insert(0, repo_root_str)

import io_scene_gltf2_msfs_fss  # noqa: E402,F401
import fss_blender_tools  # noqa: E402
from fss_blender_tools import texture_sets as ts  # noqa: E402

for name in ADDONS:
    addon_utils.enable(name, default_set=True)
    assert Path(sys.modules[name].__file__).resolve().is_relative_to(REPO_ROOT), sys.modules[name].__file__

SCRATCH = REPO_ROOT / 'tests' / '_work' / 'texture_sets_scratch'
COLOUR_TYPES = {'L': 0, 'RGB': 2, 'LA': 4, 'RGBA': 6}


def write_png(path, bits, kind, values):
    """A PNG of the given bit depth and kind from integer values (height, width, channels) in that bit depth."""
    values = np.asarray(values)
    height, width = values.shape[:2]
    dtype = '>u2' if bits == 16 else 'u1'
    raw = b''.join(b'\x00' + values[y].astype(dtype).tobytes() for y in range(height))

    def chunk(tag, data):
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data))
    Path(path).write_bytes(b'\x89PNG\r\n\x1a\n'
                           + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, bits, COLOUR_TYPES[kind], 0, 0, 0))
                           + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))
    return str(path)


def ramp(channels, bits=16, eight_bit_data=(), flat=(), size=16):
    """size x size values: each channel a different smooth ramp; channels in eight_bit_data hold 8-bit values times
    257, channels in flat a single value."""
    rng = np.random.default_rng(7)
    top = 65535 if bits == 16 else 255
    out = np.zeros((size, size, channels), np.int64)
    for c in range(channels):
        if c in flat:
            out[:, :, c] = top // 2
        elif c in eight_bit_data:
            out[:, :, c] = rng.integers(0, 256, (size, size)) * 257
        else:
            out[:, :, c] = rng.integers(0, top + 1, (size, size))
    return out


def image(path):
    return bpy.data.images.load(str(path), check_existing=False)


def material(name, kind, alpha='OPAQUE', **slots):
    mat = bpy.data.materials.new(name)
    mat.msfs_material_type = kind
    mat.msfs_alpha_mode = alpha
    for prop, img in slots.items():
        setattr(mat, prop, img)
    return mat


def plane(name, materials):
    mesh = bpy.data.meshes.new(name)
    verts, faces = [], []
    for i in range(len(materials)):
        verts += [(i, 0, 0), (i + 1, 0, 0), (i + 1, 1, 0), (i, 1, 0)]
        faces.append((4 * i, 4 * i + 1, 4 * i + 2, 4 * i + 3))
    mesh.from_pydata(verts, [], faces)
    for mat in materials:
        mesh.materials.append(mat)
    mesh.polygons.foreach_set('material_index', list(range(len(materials))))
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for name in ADDONS:
        addon_utils.enable(name, default_set=True)
    if SCRATCH.exists():
        shutil.rmtree(SCRATCH)
    SCRATCH.mkdir(parents=True)


def files():
    """The test textures: name -> path."""
    f = {}
    f['alb8'] = write_png(SCRATCH / 'alb8.png', 8, 'RGB', ramp(3, bits=8))
    f['alb8a'] = write_png(SCRATCH / 'alb8a.png', 8, 'RGBA', ramp(4, bits=8))
    f['alb16'] = write_png(SCRATCH / 'alb16.png', 16, 'RGB', ramp(3))
    f['orm16'] = write_png(SCRATCH / 'orm16.png', 16, 'RGB', ramp(3))
    f['orm16a'] = write_png(SCRATCH / 'orm16a.png', 16, 'RGBA', ramp(4))
    f['orm8'] = write_png(SCRATCH / 'orm8.png', 8, 'RGB', ramp(3, bits=8))
    # occlusion 8-bit data, roughness real 16, metallic flat
    f['orm_fake'] = write_png(SCRATCH / 'orm_fake.png', 16, 'RGB', ramp(3, eight_bit_data=(0,), flat=(2,)))
    f['nml16'] = write_png(SCRATCH / 'nml16.png', 16, 'RGB', ramp(3))
    f['nml8'] = write_png(SCRATCH / 'nml8.png', 8, 'RGB', ramp(3, bits=8))
    f['emis8'] = write_png(SCRATCH / 'emis8.png', 8, 'RGB', ramp(3, bits=8))
    f['ao2grey16'] = write_png(SCRATCH / 'ao2grey16.png', 16, 'L', ramp(1))
    f['ao2rgb16'] = write_png(SCRATCH / 'ao2rgb16.png', 16, 'RGB', ramp(3))
    f['grey8'] = write_png(SCRATCH / 'grey8.png', 8, 'L', ramp(1, bits=8))
    f['dir16'] = write_png(SCRATCH / 'dir16.png', 16, 'RGB', ramp(3))
    f['bmask8'] = write_png(SCRATCH / 'bmask8.png', 8, 'L', ramp(1, bits=8))
    (SCRATCH / 'not_png.png').write_bytes(b'\xff\xd8\xff\xe0' + b'\x00' * 40)  # a JPEG header under a .png name
    f['not_png'] = str(SCRATCH / 'not_png.png')
    return f


def build():
    reset()
    f = files()
    mats = [
        material('MAT_STD', 'msfs_standard', msfs_base_color_texture=image(f['alb8']),
                 msfs_occlusion_metallic_roughness_texture=image(f['orm16a']),
                 msfs_normal_texture=image(f['nml8']), msfs_emissive_texture=image(f['emis8']),
                 msfs_occlusion_uv2=image(f['ao2rgb16'])),
        material('MAT_DECAL', 'msfs_decal', alpha='BLEND', msfs_base_color_texture=image(f['alb8a']),
                 msfs_emissive_texture=image(f['emis8'])),
        material('MAT_GLASS_ALPHA', 'msfs_glass', msfs_base_color_texture=image(f['alb8a'])),
        material('MAT_ANISO', 'msfs_anisotropic', msfs_occlusion_metallic_roughness_texture=image(f['orm_fake']),
                 msfs_anisotropic_direction_roughness_y_texture=image(f['dir16'])),
        material('MAT_MASKED', 'msfs_standard', msfs_detail_color_texture=image(f['alb16']),
                 msfs_detail_occlusion_metallic_roughness_texture=image(f['orm16']),
                 msfs_blend_mask_texture=image(f['bmask8'])),
        material('MAT_WS', 'msfs_windshield', msfs_occlusion_metallic_roughness_texture=image(f['orm8']),
                 msfs_emissive_texture=image(f['alb8a']), msfs_iridescent_thickness_texture=image(f['grey8'])),
        material('MAT_INVISIBLE', 'msfs_invisible', msfs_base_color_texture=image(f['alb8'])),
        material('MAT_PARALLAX', 'msfs_parallax_window', msfs_base_color_texture=image(f['alb8']),
                 msfs_emissive_texture=image(f['alb8a']), msfs_behind_glass_color_texture=image(f['alb8a'])),
        material('MAT_GREY', 'msfs_standard', msfs_occlusion_metallic_roughness_texture=image(f['grey8']),
                 msfs_occlusion_uv2=image(f['ao2grey16'])),
        material('MAT_FILES', 'msfs_standard', msfs_base_color_texture=image(f['not_png']),
                 msfs_normal_texture=image(SCRATCH / 'nml16.png')),
        material('MAT_PLAIN', 'NONE'),
    ]
    missing = image(f['nml16'])
    missing.filepath = str(SCRATCH / 'gone.png')
    mats[-2].msfs_normal_texture = missing
    unused = bpy.data.materials.new('MAT_UNUSED_HELD')
    unused.msfs_material_type = 'msfs_standard'
    unused.msfs_base_color_texture = image(f['alb8'])
    plane('PLANE', mats)
    return f


def slots_of(name):
    row = bpy.context.scene.fss_texture_sets.rows[name]
    return {slot.role: slot for slot in row.slots}


def texts(slot, settings=None):
    settings = settings or bpy.context.scene.fss_texture_sets
    return [(text, warn) for text, warn in ts.tokens(slot, ts.depth_for(settings, slot))]


def test_table():
    """Every slot property is an Image pointer of the exporter, every MSFS 2024 type has a table, and every role a
    channel list (decisions S33.2, S33.6)."""
    pointers = {p.identifier for p in bpy.types.Material.bl_rna.properties
                if p.type == 'POINTER' and getattr(p.fixed_type, 'identifier', '') == 'Image'}
    missing = sorted(set(ts.SLOT_ROLE) - pointers)
    assert not missing, missing
    kinds = {item.identifier for item in bpy.types.Material.bl_rna.properties['msfs_material_type'].enum_items}
    assert kinds - {'NONE'} == set(ts.TYPES), sorted(kinds ^ set(ts.TYPES))
    for kind, (_label, slots) in ts.TYPES.items():
        for prop, role in slots:
            assert prop in ts.SLOT_ROLE and role in ts.ROLES, (kind, prop, role)
        assert len({prop for prop, _role in slots}) == len(slots), kind
    assert ts.TYPES['msfs_invisible'][1] == () and ts.TYPES['msfs_environment_occluder'][1] == ()
    print('PASS: table')


def test_refresh_rows():
    build()
    bpy.ops.fss.materials_refresh()
    settings = bpy.context.scene.fss_texture_sets
    names = [row.name for row in settings.rows]
    assert 'MAT_UNUSED_HELD' not in names, names  # never used: no row
    assert settings.rows['MAT_STD'].kind == 'Standard'
    assert settings.rows['MAT_PLAIN'].kind == 'not an MSFS material' and not settings.rows['MAT_PLAIN'].slots

    std = slots_of('MAT_STD')
    assert list(std) == ['ALB', 'ORM', 'NML', 'EMIS', 'AO2'], list(std)  # the exporter's slot order
    assert (std['ALB'].bits, std['ALB'].colour_type, std['ALB'].status) == (8, 2, 'ok')
    # S33.3: Standard needs a 16-bit albedo and emissive; ORM and every normal on any material
    assert texts(std['ALB']) == [('R8', True), ('G8', True), ('B8', True)]
    assert texts(std['ORM']) == [('O16', False), ('R16', False), ('M16', False), ('A16', True)]  # alpha unused
    assert texts(std['NML']) == [('X8', True), ('Y8', True), ('Z8', True)]
    assert texts(std['EMIS']) == [('R8', True), ('G8', True), ('B8', True)]
    assert texts(std['AO2']) == [('L16', False), ('G16', True), ('B16', True)]  # a one-channel role in an RGB file

    decal = slots_of('MAT_DECAL')
    # Decal: albedo 8-bit is fine and its alpha is used (alpha mode Blend); emissive needs 16-bit
    assert texts(decal['ALB']) == [('R8', False), ('G8', False), ('B8', False), ('A8', False)]
    assert texts(decal['EMIS']) == [('R8', True), ('G8', True), ('B8', True)]
    # alpha in the albedo of an Opaque material is warned (S33.4)
    glass = slots_of('MAT_GLASS_ALPHA')
    assert texts(glass['ALB']) == [('R8', False), ('G8', False), ('B8', False), ('A8', True)]

    aniso = slots_of('MAT_ANISO')
    assert [t for t, _w in texts(aniso['ORM'])] == ['O16', 'Rx16', 'M16']
    assert [t for t, _w in texts(aniso['DIR'])] == ['Dx16', 'Dy16', 'Ry16']

    masked = slots_of('MAT_MASKED')  # a blend mask turns the detail maps into secondary maps
    assert list(masked) == ['ALB-2', 'ORM-2', 'MASK'], list(masked)
    assert texts(masked['MASK']) == [('L8', False)]
    assert texts(masked['ALB-2']) == [('R16', False), ('G16', False), ('B16', False)]

    ws = slots_of('MAT_WS')
    assert list(ws) == ['RRM', 'ALB-2', 'IRID'], list(ws)
    assert [t for t, _w in texts(ws['RRM'])] == ['Rf8', 'R8', 'M8'] and all(w for _t, w in texts(ws['RRM']))
    assert ws['IRID'].unused_slot  # iridescence is off: the exporter does not use the slot
    assert not ws['RRM'].unused_slot and not ws['ALB-2'].unused_slot

    inv = slots_of('MAT_INVISIBLE')
    assert list(inv) == ['ALB'] and inv['ALB'].unused_slot

    par = slots_of('MAT_PARALLAX')
    assert list(par) == ['ALB-G', 'EMIS-R', 'ALB-R'], list(par)
    assert [t for t, _w in texts(par['EMIS-R'])] == ['R8', 'G8', 'B8', 'T8']

    grey = slots_of('MAT_GREY')
    assert texts(grey['ORM']) == [('L8', True)]  # a grey file in a colour role, and 8-bit
    assert texts(grey['AO2']) == [('L16', False)]

    other = slots_of('MAT_FILES')
    assert other['ALB'].status == 'other' and texts(other['ALB']) == [('?', False)]
    assert other['NML'].status == 'missing' and texts(other['NML']) == [('missing', True)]
    print('PASS: refresh rows')


def test_conditions():
    """Clearcoat's inverse roughness and Windshield's iridescence switch slots as the exporter's panels do."""
    reset()
    f = files()
    coat = material('MAT_COAT', 'msfs_clearcoat', msfs_occlusion_metallic_roughness_texture=image(f['orm16']),
                    msfs_clearcoat_color_roughness_texture=image(f['alb16']))
    roles = {role: labels for _prop, role, labels in ts.slot_roles(coat)}
    assert 'COAT' in roles and roles['ORM'] == ('O', 'R', 'M')
    coat.msfs_clearcoat_inverse_roughness = True
    roles = {role: labels for _prop, role, labels in ts.slot_roles(coat)}
    assert 'COAT' not in roles and roles['ORM'] == ('O', 'Cr', 'M')
    ws = material('MAT_WS2', 'msfs_windshield', msfs_iridescent_thickness_texture=image(f['grey8']))
    assert 'IRID' not in {role for _p, role, _l in ts.slot_roles(ws)}
    ws.msfs_use_iridescent = True
    assert 'IRID' in {role for _p, role, _l in ts.slot_roles(ws)}
    hair = material('MAT_HAIR', 'msfs_hair')
    assert {role: labels for _p, role, labels in ts.slot_roles(hair)}['ORM'] == ('O', 'Rx', 'M')
    print('PASS: conditions')


def test_data_check():
    f = build()
    bpy.ops.fss.materials_refresh()
    settings = bpy.context.scene.fss_texture_sets
    pending = dict(ts.to_check(settings))
    expected = {os.path.normpath(f[key]) for key in ('orm16a', 'orm_fake', 'ao2rgb16', 'alb16', 'orm16', 'dir16',
                                                       'ao2grey16')}
    assert set(pending) == expected, sorted(set(pending) ^ expected)
    # exact values: the check of a file with known channels
    assert ts.check_file(f['orm_fake'], 2) == '8,16,flat'
    assert ts.check_file(f['orm16a'], 6) == '16,16,16,16'
    assert ts.check_file(f['ao2grey16'], 0) == '16'
    before = len(bpy.data.images)
    assert bpy.ops.fss.texture_depth_check() == {'FINISHED'}
    assert len(bpy.data.images) == before  # temporary images removed
    assert not ts.to_check(settings)
    aniso = slots_of('MAT_ANISO')
    # occlusion holds 8-bit data and ORM needs 16-bit: warned; metallic flat: no warning
    assert texts(aniso['ORM']) == [('O16→8', True), ('Rx16', False), ('M16', False)], texts(aniso['ORM'])
    # kept until the file changes: rewrite one file, Refresh, and only it is pending again
    time.sleep(0.05)
    write_png(f['orm16'], 16, 'RGB', ramp(3, eight_bit_data=(1,)))
    bpy.ops.fss.materials_refresh()
    assert [os.path.normpath(p) for p, _c in ts.to_check(settings)] == [os.path.normpath(f['orm16'])]
    bpy.ops.fss.texture_depth_check()
    masked = slots_of('MAT_MASKED')
    assert texts(masked['ORM-2']) == [('O16', False), ('R16→8', True), ('M16', False)], texts(masked['ORM-2'])
    # 8-bit data in a role where 8-bit is fine is shown, not warned
    entry = settings.checks[os.path.normpath(f['alb16'])]
    entry.depths = '8,8,8'
    assert texts(masked['ALB-2']) == [('R16→8', False), ('G16→8', False), ('B16→8', False)]
    print('PASS: data check')


def test_packed():
    reset()
    f = files()
    img = image(f['nml16'])
    img.pack()
    mat = material('MAT_PACKED', 'msfs_standard', msfs_normal_texture=img)
    plane('P', [mat])
    bpy.ops.fss.materials_refresh()
    slot = slots_of('MAT_PACKED')['NML']
    assert (slot.status, slot.bits) == ('packed', 16), (slot.status, slot.bits)
    assert not ts.to_check(bpy.context.scene.fss_texture_sets)  # packed files are not read from disk
    print('PASS: packed')


class _Layout:
    """Records what a panel draws (background Blender has no UI to draw into)."""

    def __init__(self, calls):
        self.calls = calls

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if name == 'operator':
                return SimpleNamespace()
            return self if name in ('row', 'column', 'box', 'split') else None
        return call


def snapshot():
    s = bpy.context.scene.fss_texture_sets
    values = [s.show]
    for row in s.rows:
        values.append((row.name, row.kind))
        values += [tuple(getattr(slot, k) for k in ('name', 'role', 'labels', 'file', 'path', 'stamp', 'status', 'bits',
                                                     'colour_type', 'need16', 'alpha_warn', 'unused_slot'))
                   for slot in row.slots]
    values += [(c.name, c.stamp, c.depths) for c in s.checks]
    return values


def test_draw():
    build()
    calls = []
    ts.FSS_PT_TextureSets.draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
    assert [kw.get('text') for n, _a, kw in calls if n == 'label'] == ['Press Refresh to list the texture sets']
    bpy.ops.fss.materials_refresh()
    icons = set(bpy.types.UILayout.bl_rna.functions['label'].parameters['icon'].enum_items.keys())
    for show in ('ALL', 'WARNINGS'):
        bpy.context.scene.fss_texture_sets.show = show
        before = snapshot()
        calls = []
        ts.FSS_PT_TextureSets.draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
        assert snapshot() == before, 'the panel wrote while drawing'
        labels = [kw.get('text') for n, _a, kw in calls if n == 'label']
        assert {kw['icon'] for _n, _a, kw in calls if 'icon' in kw} <= icons
        assert any(n == 'operator' and kw.get('text', '').startswith('Check Data Depth') for n, _a, kw in calls)
        if show == 'ALL':
            assert 'MAT_PLAIN' in labels and 'MAT_DECAL' in labels
            assert 'not an MSFS material' in labels
        else:
            assert 'MAT_PLAIN' not in labels and 'MAT_DECAL' in labels and 'MAT_STD' in labels
        assert any(t and t.endswith('(slot not used by this type)') for t in labels), labels
        assert any(t and t.endswith('(data not checked)') for t in labels), labels
    print('PASS: draw')


def main():
    test_table()
    test_refresh_rows()
    test_conditions()
    test_data_check()
    test_packed()
    test_draw()
    print('ALL TESTS PASSED')


main()
