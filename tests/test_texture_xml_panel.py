"""Texture XMLs in the Texture Sets sub-panel (material-management journal, Session 34 part 2): the list follows the
multi-exporter presets or the visible objects, the BitmapSlot of each slot (detail maps with and without a blend mask,
Windshield, Tire, a slot TextureLib writes no XML for), the slot conflict warning, the XML states (missing, matches,
differs, no PNG), Write XMLs writing what the export writes (compared byte for byte with a multi-exporter export),
XMLs read once on Refresh and on opening a file, then Blender's flags win, drawing writes nothing, and the panel without
the exporter.

To run:
G:\\e-jets-e2\\tools\\blender\\blender.exe -b --factory-startup --python tests/test_texture_xml_panel.py
"""

import shutil
import struct
import sys
import zlib
from pathlib import Path
from types import SimpleNamespace

import addon_utils
import bpy

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
import fss_blender_tools  # noqa: E402,F401
from fss_blender_tools import autorefresh, texture_sets as ts  # noqa: E402

for name in ADDONS:
    addon_utils.enable(name, default_set=True)
    assert Path(sys.modules[name].__file__).resolve().is_relative_to(REPO_ROOT), sys.modules[name].__file__

from io_scene_gltf2_msfs_fss.io.exp import export_settings  # noqa: E402
from io_scene_gltf2_msfs_fss.io.exp.texture_lib.bitmap_config import BitmapSlots  # noqa: E402

WORK = REPO_ROOT / 'tests' / '_work' / 'texture_xml_panel_scratch'
SOURCE = WORK / 'source'
TEXTURE = WORK / 'texture'
MODEL = WORK / 'model'
BLEND = WORK / 'scene.blend'


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print('PASS:', message)


def write_png(path, seed):
    """An 8x8 8-bit RGB PNG, its colour from seed."""
    raw =b''.join(b'\x00' + bytes([(seed * 37 + x * 11 + y * 5) % 256 for x in range(8) for _c in range(3)])
                   for y in range(8))

    def chunk(tag, data):
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data))
    Path(path).write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 8, 8, 8, 2, 0, 0, 0))
                           + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def reset(stems, in_folder=None):
    """An empty file saved in WORK (the folder setting is relative to the .blend), the PNGs in SOURCE and those of
    in_folder (default all) copied into TEXTURE, the folder set to //texture."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for name in ADDONS:
        addon_utils.enable(name, default_set=True)
    shutil.rmtree(WORK, ignore_errors=True)
    for folder in (SOURCE, TEXTURE, MODEL):
        folder.mkdir(parents=True)
    for seed, stem in enumerate(stems):
        write_png(SOURCE / f'{stem}.png', seed)
        if in_folder is None or stem in in_folder:
            shutil.copy2(SOURCE / f'{stem}.png', TEXTURE / f'{stem}.png')
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND))
    bpy.context.scene.msfs_fss_texture_folder = '//texture'


def image(stem):
    return bpy.data.images.load(str(SOURCE / f'{stem}.png'), check_existing=True)


def material(name, kind, **slots):
    mat = bpy.data.materials.new(name)
    mat.msfs_material_type = kind
    for prop, value in slots.items():
        setattr(mat, prop, image(value) if isinstance(value, str) else value)
    return mat


def plane(name, mat, collection=None):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
    mesh.uv_layers.new()
    mesh.materials.append(mat)
    obj = bpy.data.objects.new(name, mesh)
    (collection or bpy.context.scene.collection).objects.link(obj)
    return obj


def preset_for(objects, enabled=True):
    """A multi-exporter preset whose one enabled layer holds the objects (as tests/test_texture_xml.py)."""
    scene = bpy.context.scene
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
    preset = scene.msfs_multi_exporter_presets.add()
    preset.preset_name = 'panel'
    preset.folder_path = str(MODEL)
    preset.enabled = enabled
    layer = preset.layers.add()
    layer.collection = collection
    layer.enabled = True
    return preset


def refresh():
    assert bpy.ops.fss.materials_refresh() == {'FINISHED'}
    return {t.name: t for t in bpy.context.scene.fss_texture_sets.textures}


def state(texture):
    return ts.xml_state(bpy.context.scene.fss_texture_sets, texture)


def xml_bytes():
    return {path.name: path.read_bytes() for path in sorted(TEXTURE.glob('*.xml'))}


def xml_text(stem):
    return (TEXTURE / f'{stem}.png.xml').read_text(encoding='utf8')


# --- the tests -----------------------------------------------------------------------------------------------------

def test_table():
    check(set(ts.BITMAP_SLOTS) == set(ts.SLOT_ROLE), 'every MSFS 2024 slot property has a BitmapSlot entry')
    names = {slot.flag for slot in BitmapSlots}
    used = {slot for slot, _b, _n in ts.BITMAP_SLOTS.values() if slot} | set(ts.BITMAP_SLOTS_MASKED.values())
    check(used <= names, 'every BitmapSlot of the table is one of Asobo\'s BitmapSlots')


# every slot of each material its own image, so each XML has one slot
EXPORT_SCENE = {
    'STD': ('msfs_standard', {'msfs_base_color_texture': 'std_alb', 'msfs_occlusion_metallic_roughness_texture':
                              'std_orm', 'msfs_normal_texture': 'std_nml', 'msfs_emissive_texture': 'std_emis',
                              'msfs_detail_color_texture': 'std_dcol', 'msfs_detail_normal_texture': 'std_dnml',
                              'msfs_detail_occlusion_metallic_roughness_texture': 'std_dorm',
                              'msfs_occlusion_uv2': 'std_ao2', 'msfs_wear_albedo_mask': 'std_wear',
                              'msfs_wear_omr_intensity': 'std_wearorm'}),
    'MASKED': ('msfs_standard', {'msfs_blend_mask_texture': 'mk_mask', 'msfs_detail_color_texture': 'mk_dcol',
                                 'msfs_detail_normal_texture': 'mk_dnml',
                                 'msfs_detail_occlusion_metallic_roughness_texture': 'mk_dorm'}),
    'WS': ('msfs_windshield', {'msfs_occlusion_metallic_roughness_texture': 'ws_rrm',
                               'msfs_windshield_wiper_mask_texture': 'ws_wipe',
                               'msfs_windshield_detail_normal_texture': 'ws_dnml',
                               'msfs_windshield_scratches_normal_texture': 'ws_scr',
                               'msfs_windshield_insects_albedo_texture': 'ws_bug',
                               'msfs_windshield_insects_mask_texture': 'ws_bugmask',
                               'msfs_iridescent_thickness_texture': 'ws_irid'}),
    'ANISO': ('msfs_anisotropic', {'msfs_anisotropic_direction_roughness_y_texture': 'an_dir'}),
    'COAT': ('msfs_clearcoat', {'msfs_clearcoat_color_roughness_texture': 'cc_col',
                                'msfs_clearcoat_normal_texture': 'cc_nml'}),
    'TIRE': ('msfs_tire', {'msfs_tire_details_texture': 'ti_det', 'msfs_tire_mud_normal_texture': 'ti_mud',
                           'msfs_tire_mud_cutout_texture': 'ti_cut'}),
    'TREE': ('msfs_tree', {'msfs_foliage_mask_texture': 'tr_fol'}),
    'GEODECAL': ('msfs_geo_decal_blendmasked', {'msfs_decal_blend_mask_texture': 'gd_mask'}),
    'PARALLAX': ('msfs_parallax_window', {'msfs_behind_glass_color_texture': 'px_room'}),
}
EXPECTED_SLOTS = {
    'std_alb': 'MTL_BITMAP_DECAL0', 'std_orm': 'MTL_BITMAP_METAL_ROUGH_AO', 'std_nml': 'MTL_BITMAP_NORMAL',
    'std_emis': 'MTL_BITMAP_EMISSIVE', 'std_dcol': 'MTL_BITMAP_DETAILDIFFUSE', 'std_dnml': 'MTL_BITMAP_ADD_NORMAL',
    'std_dorm': 'MTL_BITMAP_DETAIL_METAL_ROUGH_AO', 'std_ao2': 'MTL_BITMAP_OCCLUSION',
    'std_wear': 'MTL_BITMAP_DIRTOVERLAY', 'std_wearorm': 'MTL_BITMAP_DIRTOVERLAY_METAL_ROUGH_AO',
    'mk_mask': 'MTL_BITMAP_BLENDMASK', 'mk_dcol': 'MTL_BITMAP_ADD_DECAL0', 'mk_dnml': 'MTL_BITMAP_DETAILNORMAL',
    'mk_dorm': 'MTL_BITMAP_ADD_METAL_ROUGH_AO', 'ws_rrm': 'MTL_BITMAP_METAL_ROUGH_AO',
    'ws_wipe': 'MTL_BITMAP_WIPERMASK', 'ws_dnml': 'MTL_BITMAP_WINDSHIELDDETAILNORMAL',
    'ws_scr': 'MTL_BITMAP_SCRATCHESNORMAL', 'ws_bug': 'MTL_BITMAP_WINDSHIELDINSECTS',
    'ws_bugmask': 'MTL_BITMAP_WINDSHIELDINSECTSMASK', 'ws_irid': 'MTL_BITMAP_IRIDESCENTTHICKNESS',
    'an_dir': 'MTL_BITMAP_ANISO_DIR_ROUGH', 'cc_col': 'MTL_BITMAP_CLEARCOATCOLORROUGHNESS',
    'cc_nml': 'MTL_BITMAP_CLEARCOATNORMAL', 'ti_det': 'MTL_BITMAP_TIREDETAILS', 'ti_mud': 'MTL_BITMAP_TIREMUDNORMAL',
    'ti_cut': '', 'tr_fol': 'MTL_BITMAP_ALPHABLENDMASK', 'gd_mask': 'MTL_BITMAP_BLENDMASK',
    'px_room': 'MTL_BITMAP_ADD_DECAL0',
}


def build_export_scene():
    stems = [stem for _kind, slots in EXPORT_SCENE.values() for stem in slots.values()]
    reset(stems)
    objects = []
    for name, (kind, slots) in EXPORT_SCENE.items():
        mat = material(name, kind, **slots)
        if kind == 'msfs_windshield':
            mat.msfs_use_iridescent = True
        if kind == 'msfs_geo_decal_blendmasked' and not mat.msfs_decal_mode:
            mat.msfs_decal_mode = 'blendMasked'
        objects.append(plane(name, mat))
    image('std_alb').msfs_flags.msfs_image_quality_high = True
    image('std_nml').msfs_flags.msfs_image_no_reduction = True
    image('std_nml').msfs_flags.msfs_image_anisotropic = '8'
    image('ws_wipe').msfs_flags.msfs_image_no_mipmap = True
    image('std_orm').msfs_flags.msfs_image_prec_inv_avg = True
    image('ws_bug').msfs_flags.msfs_image_alpha_preserv = True
    preset_for(objects)
    bpy.ops.wm.save_mainfile()
    return objects


def test_slots_and_write_matches_export():
    build_export_scene()
    textures = refresh()
    found = {Path(name).stem: t.slot for name, t in textures.items()}
    check(found == EXPECTED_SLOTS, f'BitmapSlot per slot {sorted(set(found.items()) ^ set(EXPECTED_SLOTS.items()))}')
    check(not any(t.conflict for t in textures.values()), 'no slot conflict in the export scene')
    check(textures['std_orm.png'].no_alpha and textures['an_dir.png'].no_alpha
          and not textures['std_alb.png'].no_alpha, 'ForceNoAlpha on ORM and anisotropic direction only')
    check(all(state(t) == 'missing' for t in textures.values() if t.slot), 'before writing every XML is missing')
    check(state(textures['ti_cut.png']) == '' and ts.texture_warn(bpy.context.scene.fss_texture_sets,
                                                                  textures['ti_cut.png']),
          'the tire mud cutout gets no XML (TextureLib does not read it) and is warned')
    result = bpy.ops.fss.texture_xml_write()
    check(result == {'FINISHED'}, 'Write XMLs runs')
    written = xml_bytes()
    check(len(written) == len(EXPECTED_SLOTS) - 1, f'one XML per texture with a slot ({len(written)})')
    check(all(state(t) == 'matches' for t in textures.values() if t.slot), 'after writing every XML matches')
    check('<UserFlags Type="_DEFAULT">+NOREDUCE+ANISOTROPIC=8</UserFlags>' in xml_text('std_nml')
          and '<ForceNoAlpha>true</ForceNoAlpha>' in xml_text('std_orm')
          and '+PRECOMPUTEDINVAVG' in xml_text('std_orm'), 'the XMLs hold the slot flags and ForceNoAlpha')

    # the export writes the same files: remove them, export, compare byte for byte
    for path in TEXTURE.glob('*.xml'):
        path.unlink()
    bpy.ops.msfs2024.multi_export_gltf(export_mode='PRESETS')
    exported = xml_bytes()
    differ = sorted(name for name in set(written) | set(exported) if written.get(name) != exported.get(name))
    check(not differ, f'Write XMLs writes byte for byte what the multi-exporter writes {differ}')


def test_scope():
    reset(['in_preset', 'outside', 'hidden'])
    a = plane('A', material('MAT_A', 'msfs_standard', msfs_base_color_texture='in_preset'))
    plane('B', material('MAT_B', 'msfs_standard', msfs_base_color_texture='outside'))
    c = plane('C', material('MAT_C', 'msfs_standard', msfs_base_color_texture='hidden'))
    c.hide_set(True)
    check(set(refresh()) == {'in_preset.png', 'outside.png'}, 'without a preset: the visible objects')
    preset = preset_for([a])
    check(set(refresh()) == {'in_preset.png'}, 'with an enabled preset: only its layers\' objects')
    preset.layers[0].enabled = False
    check(set(refresh()) == set(), 'an enabled preset without an enabled layer exports nothing')
    preset.enabled = False
    check(set(refresh()) == {'in_preset.png', 'outside.png'}, 'no enabled preset: the visible objects again')


def test_conflict_and_states():
    reset(['shared', 'compat', 'match', 'diff', 'nopng', 'miss'], in_folder={'shared', 'compat', 'match', 'diff',
                                                                             'miss'})
    plane('A', material('MAT_A', 'msfs_standard', msfs_base_color_texture='shared', msfs_emissive_texture='compat',
                        msfs_normal_texture='match', msfs_occlusion_metallic_roughness_texture='diff'))
    plane('B', material('MAT_B', 'msfs_standard', msfs_normal_texture='shared', msfs_base_color_texture='compat',
                        msfs_emissive_texture='nopng', msfs_occlusion_uv2='miss'))
    (TEXTURE / 'match.png.xml').write_text(
        '<BitmapConfiguration><BitmapSlot>MTL_BITMAP_NORMAL</BitmapSlot>'
        '<UserFlags Type="_DEFAULT">+QUALITYHIGH</UserFlags></BitmapConfiguration>', encoding='utf8')
    (TEXTURE / 'diff.png.xml').write_text(
        '<BitmapConfiguration><BitmapSlot>MTL_BITMAP_DECAL0</BitmapSlot>'
        '<UserFlags Type="_DEFAULT">+NOMIPMAP</UserFlags></BitmapConfiguration>', encoding='utf8')
    t = refresh()
    check(t['shared.png'].conflict and t['shared.png'].slots == 'DECAL0, NORMAL',
          'an image as albedo and as normal: slot conflict warned')
    check(not t['compat.png'].conflict and t['compat.png'].slots == 'EMISSIVE, DECAL0',
          'albedo and emissive are compatible (Asobo\'s is_compatible_id): no conflict')
    check(state(t['match.png']) == 'matches', 'XML state matches')
    check(state(t['diff.png']) == 'differs', 'XML state differs (another slot)')
    check(state(t['miss.png']) == 'missing', 'XML state missing')
    check(state(t['nopng.png']) == 'no PNG', 'XML state no PNG')

    # read once: the XML flags reached the images, which are marked read
    check(image('match').msfs_flags.msfs_image_quality_high and image('match').fss_texture_xml_read
          and image('diff').msfs_flags.msfs_image_no_mipmap, 'Refresh read the XMLs\' flags into the images once')
    check(not image('miss').fss_texture_xml_read, 'an image without an XML is not marked read')
    # Blender wins: a flag changed in Blender shows as differs at once; a hand edit of a read XML is not read again
    image('match').msfs_flags.msfs_image_no_mipmap = True
    check(state(t['match.png']) == 'differs', 'a changed flag shows as differs without Refresh')
    (TEXTURE / 'match.png.xml').write_text(
        '<BitmapConfiguration><BitmapSlot>MTL_BITMAP_NORMAL</BitmapSlot>'
        '<UserFlags Type="_DEFAULT">+NOREDUCE</UserFlags></BitmapConfiguration>', encoding='utf8')
    t = refresh()
    flags = image('match').msfs_flags
    check(flags.msfs_image_quality_high and flags.msfs_image_no_mipmap and not flags.msfs_image_no_reduction
          and state(t['match.png']) == 'differs', 'after the read, Refresh keeps Blender\'s flags (XML differs)')

    # Write XMLs: Blender's flags reach the files; the PNG not in the folder is reported
    check(bpy.ops.fss.texture_xml_write() == {'FINISHED'}, 'Write XMLs runs')
    t = {x.name: x for x in bpy.context.scene.fss_texture_sets.textures}
    check('+QUALITYHIGH+NOMIPMAP' in xml_text('match') and state(t['match.png']) == 'matches',
          'Write XMLs writes Blender\'s flags')
    check('MTL_BITMAP_METAL_ROUGH_AO' in xml_text('diff') and state(t['diff.png']) == 'matches',
          'Write XMLs rewrites an XML with another slot')
    check((TEXTURE / 'miss.png.xml').exists() and not (TEXTURE / 'nopng.png.xml').exists(),
          'a missing XML is written; none for a PNG not in the folder')
    check(state(t['nopng.png']) == 'no PNG', 'the PNG not in the folder stays no PNG')


def test_write_reads_first():
    """Write XMLs reads an XML never read before writing it (S34.2), so its flags are not lost."""
    reset(['first'])
    plane('A', material('MAT_A', 'msfs_standard', msfs_base_color_texture='first'))
    refresh()
    (TEXTURE / 'first.png.xml').write_text(
        '<BitmapConfiguration><BitmapSlot>MTL_BITMAP_EMISSIVE</BitmapSlot>'
        '<UserFlags Type="_DEFAULT">+NOREDUCE</UserFlags></BitmapConfiguration>', encoding='utf8')
    bpy.ops.fss.texture_xml_write()
    check(image('first').msfs_flags.msfs_image_no_reduction and image('first').fss_texture_xml_read
          and '<BitmapSlot>MTL_BITMAP_DECAL0</BitmapSlot>' in xml_text('first') and '+NOREDUCE' in xml_text('first'),
          'Write XMLs read the XML first: its flag kept, the slot written from the material')


def test_read_on_open():
    reset(['opened'])
    plane('A', material('MAT_A', 'msfs_standard', msfs_base_color_texture='opened'))
    bpy.ops.wm.save_mainfile()
    (TEXTURE / 'opened.png.xml').write_text(
        '<BitmapConfiguration><BitmapSlot>MTL_BITMAP_DECAL0</BitmapSlot>'
        '<UserFlags Type="_DEFAULT">+ALPHAPRESERVATION</UserFlags></BitmapConfiguration>', encoding='utf8')
    bpy.ops.wm.open_mainfile(filepath=str(BLEND))
    check(not image('opened').fss_texture_xml_read, 'opening alone reads nothing in background (no timer there)')
    autorefresh.refresh_all()  # what the refresh on opening runs
    check(image('opened').msfs_flags.msfs_image_alpha_preserv and image('opened').fss_texture_xml_read,
          'the refresh on opening reads the XML once')


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
    values = [s.show, s.xml_folder]
    for t in s.textures:
        values.append(tuple(getattr(t, k) for k in ('name', 'image', 'slot', 'slots', 'base_flags', 'no_alpha',
                                                     'conflict', 'png', 'xml', 'xml_valid', 'xml_slot', 'xml_flags',
                                                     'xml_no_alpha')))
    for im in bpy.data.images:
        values.append((im.name, im.fss_texture_xml_read, im.msfs_flags.to_string()))
    return values


def draw():
    calls = []
    ts.FSS_PT_TextureSets.draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
    return calls


def test_draw():
    test_conflict_and_states()
    image('match').msfs_flags.msfs_image_no_mipmap = False  # one XML differs again
    icons = set(bpy.types.UILayout.bl_rna.functions['label'].parameters['icon'].enum_items.keys())
    for show in ('ALL', 'WARNINGS'):
        bpy.context.scene.fss_texture_sets.show = show
        before = snapshot()
        calls = draw()
        check(snapshot() == before, f'drawing ({show}) writes nothing')
        labels = [kw.get('text') for n, _a, kw in calls if n == 'label']
        check({kw['icon'] for _n, _a, kw in calls if 'icon' in kw} <= icons, f'every icon exists ({show})')
        check(any(n == 'operator' and a and a[0] == 'fss.texture_xml_write' for n, a, _kw in calls),
              f'the Write XMLs button is drawn ({show})')
        check(any(n == 'prop' and a[1] == 'msfs_fss_texture_folder' for n, a, _kw in calls),
              f'the folder is drawn ({show})')
        props = [a[1] for n, a, _kw in calls if n == 'prop']
        check(all(p in props for p, _t in ts.FLAG_CELLS) and 'msfs_image_anisotropic' in props,
              f'the six flags are drawn on the rows ({show})')
        check('differs' in labels and 'no PNG' in labels, f'the states are drawn ({show})')
        # a texture row without a warning has the image icon (the material rows below use other icons)
        quiet = [kw.get('text') for n, _a, kw in calls if n == 'label' and kw.get('icon') == 'IMAGE_DATA']
        check(quiet == (['compat.png', 'diff.png', 'miss.png'] if show == 'ALL' else []),
              f'textures without a warning only under All ({show}: {quiet})')
        check('Used in slots that need different BitmapSlots' in labels, f'the conflict is drawn ({show})')
    bpy.context.scene.fss_texture_sets.show = 'ALL'
    bpy.context.scene.msfs_fss_texture_folder = '//elsewhere'
    labels = [kw.get('text') for n, _a, kw in draw() if n == 'label']
    check('The folder does not exist' in labels, 'a folder that does not exist is noted')
    bpy.context.scene.msfs_fss_texture_folder = ''
    labels = [kw.get('text') for n, _a, kw in draw() if n == 'label']
    check('Set the folder to compare and write the XMLs' in labels, 'an empty folder is noted')
    t = refresh()
    check(all(state(x) == '' for x in t.values()) and not bpy.ops.fss.texture_xml_write.poll(),
          'without a folder: no state, Write XMLs disabled')


def test_without_exporter():
    reset(['plain'])
    plane('A', material('MAT_A', 'msfs_standard', msfs_base_color_texture='plain'))
    refresh()
    addon_utils.disable('io_scene_gltf2_msfs_fss')
    try:
        check(bpy.ops.fss.materials_refresh() == {'FINISHED'}
              and not len(bpy.context.scene.fss_texture_sets.textures), 'Refresh without the exporter: no texture')
        labels = [kw.get('text') for n, _a, kw in draw() if n == 'label']
        check('The MSFS exporter add-on is not enabled' in labels, 'the panel draws without the exporter')
    finally:
        addon_utils.enable('io_scene_gltf2_msfs_fss', default_set=True)


def main():
    test_table()
    test_slots_and_write_matches_export()
    test_scope()
    test_conflict_and_states()
    test_write_reads_first()
    test_read_on_open()
    test_draw()
    test_without_exporter()
    print('ALL TEXTURE XML PANEL TESTS PASSED')


try:
    main()
except Exception:
    import traceback
    traceback.print_exc()
    sys.exit(1)
