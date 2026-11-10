"""MSFS Texture Folder (texture_folder.py, material-management journal Sessions 34 and 35): every MSFS 2024 export
points the glTF image URIs at the PNGs in the scene's texture folder and writes their texture XMLs beside them; a PNG
missing there is reported and its URI kept; an XML already there is read into the image's flags once, then Blender's
flags win; the PNGs are not touched; the MSFS 2020 target and an empty folder keep today's export.

To run:
G:\\e-jets-e2\\tools\\blender\\blender.exe -b --factory-startup --python tests/test_texture_xml.py
"""

import hashlib
import json
import shutil
import sys
from pathlib import Path
from urllib.parse import unquote
from xml.etree import ElementTree

import addon_utils
import bpy

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

from io_scene_gltf2_msfs_fss import texture_folder  # noqa: E402
from io_scene_gltf2_msfs_fss.io.exp import export_settings, gltf_exporter_patches  # noqa: E402
from io_scene_gltf2_msfs_fss.io.exp.texture_lib.texture_xml import XmlSerializer  # noqa: E402
from io_scene_gltf2_msfs_fss.io.exp.texture_lib.gltf_material import GltfMaterial  # noqa: E402

WORK = REPO_ROOT / 'tests' / '_work' / 'texture_xml_scratch'
SOURCE = WORK / 'source'      # where the .blend's images live
TEXTURE = WORK / 'texture'    # the package texture folder
MODEL = WORK / 'model'        # the export folder
BLEND = WORK / 'scene.blend'

# file stem, pixel, colorspace, 16-bit, copied into the texture folder
TEXTURES = {
    'albd': ((0.4, 0.4, 0.4, 1), 'sRGB', False, True),
    'norm': ((0.5, 0.5, 1, 1), 'Non-Color', True, True),
    'dcol': ((0.5, 0.5, 0.5, 1), 'sRGB', False, True),
    'gone': ((1, 0.3, 0, 1), 'Non-Color', False, False),
    'comp': ((1, 0.5, 0, 1), 'Non-Color', False, True),
    'dnml': ((0.5, 0.5, 1, 1), 'Non-Color', False, True),
    'mnml': ((0.5, 0.5, 1, 1), 'Non-Color', False, True),
    'mask': ((1, 1, 1, 1), 'Non-Color', False, True),
    'inml': ((0.5, 0.5, 1, 1), 'Non-Color', False, True),
}


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print('PASS:', message)


def make_files():
    shutil.rmtree(WORK, ignore_errors=True)
    for folder in (SOURCE, TEXTURE, MODEL):
        folder.mkdir(parents=True)
    for stem, (pixel, _colorspace, sixteen, _copied) in TEXTURES.items():
        im = bpy.data.images.new(stem, 8, 8, alpha=False, float_buffer=sixteen)
        im.pixels = list(pixel) * 64
        im.filepath_raw = str(SOURCE / f'{stem}.png')
        im.file_format = 'PNG'
        im.save()
        bpy.data.images.remove(im)
    for stem, (_pixel, _colorspace, _sixteen, copied) in TEXTURES.items():
        if copied:
            shutil.copy2(SOURCE / f'{stem}.png', TEXTURE / f'{stem}.png')
    # A hand-made XML already in the folder: its flag must survive the first export
    (TEXTURE / 'dcol.png.xml').write_text(
        '<BitmapConfiguration><BitmapSlot>MTL_BITMAP_DETAILDIFFUSE</BitmapSlot>'
        '<UserFlags Type="_DEFAULT">+NOMIPMAP</UserFlags></BitmapConfiguration>', encoding='utf8')


def image(stem):
    _pixel, colorspace, _sixteen, _copied = TEXTURES[stem]
    im = bpy.data.images.load(str(SOURCE / f'{stem}.png'), check_existing=True)
    im.colorspace_settings.name = colorspace
    return im


def build(folder_setting):
    bpy.ops.wm.read_homefile(use_empty=True)
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=2, y_subdivisions=2, size=1)
    obj = bpy.context.active_object
    obj.name = 'PANEL'
    material = bpy.data.materials.new('Panel')
    material.msfs_material_type = 'msfs_standard'
    material.msfs_base_color_texture = image('albd')
    material.msfs_normal_texture = image('norm')
    material.msfs_occlusion_metallic_roughness_texture = image('gone')
    material.msfs_detail_color_texture = image('dcol')
    obj.data.materials.append(material)
    image('albd').msfs_flags.msfs_image_quality_high = True
    image('norm').msfs_flags.msfs_image_no_reduction = True
    image('norm').msfs_flags.msfs_image_anisotropic = '4'
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND))  # the folder setting is relative to the .blend
    bpy.context.scene.msfs_fss_texture_folder = folder_setting
    return obj


def export_multi(objects, out_dir):
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
    for existing in scene.msfs_multi_exporter_presets:
        existing.enabled = False
    preset = scene.msfs_multi_exporter_presets.add()
    preset.preset_name = 'panel'
    preset.folder_path = str(out_dir)
    preset.enabled = True
    layer = preset.layers.add()
    layer.collection = collection
    layer.enabled = True
    bpy.ops.msfs2024.multi_export_gltf(export_mode='PRESETS')
    return next(Path(out_dir).glob('*.gltf'))


def export_plain(out_dir, target):
    bpy.context.scene.msfs_fss_export_target = target
    path = Path(out_dir) / 'panel.gltf'
    bpy.ops.export_scene.gltf(filepath=str(path), export_format='GLTF_SEPARATE', use_visible=True,
                              export_image_format='AUTO')
    return path


def uris(gltf_path):
    return {Path(unquote(i['uri'])).name: i['uri'] for i in json.loads(gltf_path.read_text(encoding='utf8'))['images']}


def xml(stem):
    path = TEXTURE / f'{stem}.png.xml'
    if not path.exists():
        return None
    root = ElementTree.parse(path).getroot()
    flags = root.find('UserFlags')
    return root.find('BitmapSlot').text, (flags.text if flags is not None else '')


def force_no_alpha(stem):
    node = ElementTree.parse(TEXTURE / f'{stem}.png.xml').getroot().find('ForceNoAlpha')
    return node is not None and node.text == 'true'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_multi_exporter():
    make_files()
    norm_hash = sha(TEXTURE / 'norm.png')
    obj = build('//texture')
    check(texture_folder.texture_folder(bpy.context.scene) == TEXTURE,
          'the folder setting is a path relative to the .blend')
    gltf = export_multi([obj], MODEL)
    found = uris(gltf)
    for stem in ('albd', 'norm', 'dcol'):
        resolved = (gltf.parent / unquote(found[f'{stem}.png'])).resolve()
        check(found[f'{stem}.png'] == f'../texture/{stem}.png' and resolved == (TEXTURE / f'{stem}.png').resolve(),
              f'multi-exporter: the URI of {stem}.png is ../texture/{stem}.png and resolves to the PNG')
    check(found['gone.png'] == 'gone.png', 'a PNG missing from the folder keeps its URI')
    check(xml('gone') is None, 'no XML for the missing PNG')
    check(xml('albd') == ('MTL_BITMAP_DECAL0', '+QUALITYHIGH'), f'albd.png.xml: base color slot, Quality High {xml("albd")}')
    check(xml('norm') == ('MTL_BITMAP_NORMAL', '+NOREDUCE+ANISOTROPIC=4'),
          f'norm.png.xml: normal slot, the image flags No Reduction and Anisotropic x4 {xml("norm")}')
    check(xml('dcol') == ('MTL_BITMAP_DETAILDIFFUSE', '+NOMIPMAP'),
          f'dcol.png.xml: the hand-made No Mipmap survived the first export {xml("dcol")}')
    check(image('dcol').msfs_flags.msfs_image_no_mipmap and image('dcol').fss_texture_xml_read,
          'the XML was read into the image once and marked read')
    check(image('albd').fss_texture_xml_read and not image('gone').fss_texture_xml_read,
          "an XML the export wrote from Blender's flags counts as read; the missing PNG's image does not")
    check(sha(TEXTURE / 'norm.png') == norm_hash, 'the 16-bit PNG in the folder is untouched')
    check(not (MODEL / 'gone.png.xml').exists() and not list(MODEL.glob('*.xml')), 'no XML written in the model folder')

    # Blender wins once read: a changed flag reaches the XML, a hand edit after the read does not survive
    image('dcol').msfs_flags.msfs_image_no_mipmap = False
    image('dcol').msfs_flags.msfs_image_quality_high = True
    shutil.rmtree(MODEL)
    MODEL.mkdir()
    gltf = export_multi([bpy.data.objects['PANEL']], MODEL)
    check(xml('dcol') == ('MTL_BITMAP_DETAILDIFFUSE', '+QUALITYHIGH'),
          f'after the read, Blender\'s flags are written {xml("dcol")}')


def test_plain_export():
    make_files()
    build('//texture')
    gltf = export_plain(MODEL, 'MSFS2024')
    check(uris(gltf)['albd.png'] == '../texture/albd.png', 'File > Export, target 2024: URIs point at the folder')
    check(xml('albd') == ('MTL_BITMAP_DECAL0', '+QUALITYHIGH'), 'File > Export, target 2024: XMLs written')


def test_file_unchanged_but_uris():
    make_files()
    build('')
    plain = json.loads(export_plain(MODEL / 'a', 'MSFS2024').read_text(encoding='utf8'))
    check(all('/' not in i['uri'] for i in plain['images']) and xml('albd') is None,
          'empty folder: URIs are file names and no XML is written')
    bpy.context.scene.msfs_fss_texture_folder = '//texture'
    pointed = json.loads(export_plain(MODEL / 'b', 'MSFS2024').read_text(encoding='utf8'))
    for i in plain['images']:
        i['uri'] = {'albd.png': '../../texture/albd.png', 'norm.png': '../../texture/norm.png',
                    'dcol.png': '../../texture/dcol.png'}.get(i['uri'], i['uri'])
    plain['buffers'] = pointed['buffers']
    check(plain == pointed, 'with the folder, the glTF differs from the export without it only in the URIs')


def test_msfs2020_untouched():
    make_files()
    build('//texture')
    (TEXTURE / 'dcol.png.xml').unlink()
    gltf = export_plain(MODEL, 'MSFS2020')
    check(all('/' not in uri for uri in uris(gltf).values()), 'MSFS 2020: URIs are file names')
    check(not list(TEXTURE.glob('*.xml')), 'MSFS 2020: no XML written')


def test_missing_folder():
    make_files()
    build('//no_such_folder')
    gltf = export_plain(MODEL, 'MSFS2024')
    check(all('/' not in uri for uri in uris(gltf).values()) and not list(TEXTURE.glob('albd*.xml')),
          'a folder that does not exist: URIs unchanged, no XML written')


def test_force_no_alpha_kept():
    make_files()
    obj = build('//texture')
    bpy.data.materials['Panel'].msfs_occlusion_metallic_roughness_texture = image('comp')

    def export_again():
        shutil.rmtree(MODEL, ignore_errors=True)
        MODEL.mkdir()
        export_multi([obj], MODEL)

    export_again()
    check(xml('comp') == ('MTL_BITMAP_METAL_ROUGH_AO', '') and force_no_alpha('comp'),
          'comp.png.xml: ORM slot with ForceNoAlpha')
    image('comp').msfs_flags.msfs_image_quality_high = True
    export_again()
    check(xml('comp') == ('MTL_BITMAP_METAL_ROUGH_AO', '+QUALITYHIGH') and force_no_alpha('comp'),
          'a flag change rewrites the XML and ForceNoAlpha stays')
    patched = XmlSerializer.update_xml_tree
    XmlSerializer.update_xml_tree = gltf_exporter_patches._original_update_xml_tree
    try:
        image('comp').msfs_flags.msfs_image_no_reduction = True
        export_again()
    finally:
        XmlSerializer.update_xml_tree = patched
    check(xml('comp') == ('MTL_BITMAP_METAL_ROUGH_AO', '+QUALITYHIGH+NOREDUCE') and not force_no_alpha('comp'),
          "without the patch Asobo's rewrite drops ForceNoAlpha (the bug the patch fixes)")


def test_detail_normal_slot():
    make_files()
    bpy.ops.wm.read_homefile(use_empty=True)
    objects = []
    # name, type, detail normal, blend mask: no mask -> DETAILNORMAL (also the Windshield's Icing Normal), mask -> ADD_NORMAL
    for i, (name, kind, normal, mask) in enumerate((('Plain', 'msfs_standard', 'dnml', None),
                                                    ('Masked', 'msfs_standard', 'mnml', 'mask'),
                                                    ('Wind', 'msfs_windshield', 'inml', None))):
        bpy.ops.mesh.primitive_grid_add(x_subdivisions=2, y_subdivisions=2, size=1, location=(i * 2, 0, 0))
        obj = bpy.context.active_object
        obj.name = name.upper()
        material = bpy.data.materials.new(name)
        material.msfs_material_type = kind
        material.msfs_base_color_texture = image('albd')
        material.msfs_detail_color_texture = image('dcol')
        material.msfs_detail_normal_texture = image(normal)
        if mask:
            material.msfs_blend_mask_texture = image(mask)
        obj.data.materials.append(material)
        objects.append(obj)
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND))
    bpy.context.scene.msfs_fss_texture_folder = '//texture'

    def export_slots():
        shutil.rmtree(MODEL, ignore_errors=True)
        MODEL.mkdir()
        for stem in ('dnml', 'mnml', 'inml'):
            (TEXTURE / f'{stem}.png.xml').unlink(missing_ok=True)
        export_multi(objects, MODEL)
        return {stem: (xml(stem) or (None,))[0] for stem in ('dnml', 'mnml', 'inml')}

    want = {'dnml': 'MTL_BITMAP_DETAILNORMAL', 'mnml': 'MTL_BITMAP_ADD_NORMAL', 'inml': 'MTL_BITMAP_DETAILNORMAL'}
    check(export_slots() == want, f'detail normal: DETAILNORMAL without a blend mask (and the windshield icing '
                                  f'normal), ADD_NORMAL with one {want}')
    patched = GltfMaterial.get_detail_normal_tex_config
    GltfMaterial.get_detail_normal_tex_config = gltf_exporter_patches._original_get_detail_normal_tex_config
    try:
        found = export_slots()
    finally:
        GltfMaterial.get_detail_normal_tex_config = patched
    check(found == {'dnml': 'MTL_BITMAP_ADD_NORMAL', 'mnml': 'MTL_BITMAP_DETAILNORMAL', 'inml': 'MTL_BITMAP_ADD_NORMAL'},
          f"without the patch Asobo's slots are swapped (the bug the patch fixes) {found}")


def test_parse_user_flags():
    values = texture_folder.parse_user_flags('FL_BITMAP_SDF+QUALITYHIGH+ANISOTROPIC=16')
    check(values['msfs_image_quality_high'] and values['msfs_image_anisotropic'] == '16'
          and not values['msfs_image_no_mipmap'], 'slot flags in <UserFlags> are ignored, image flags read')


def main():
    test_parse_user_flags()
    test_multi_exporter()
    test_plain_export()
    test_file_unchanged_but_uris()
    test_msfs2020_untouched()
    test_missing_folder()
    test_force_no_alpha_kept()
    test_detail_normal_slot()
    print('ALL TEXTURE XML TESTS PASSED')


try:
    main()
except Exception:
    import traceback
    traceback.print_exc()
    sys.exit(1)
