"""Normal Scale per material in an MSFS 2024 export: materials that share one normal image keep their own Normal Scale
and Detail Normal Scale (FSS patch over Asobo 8.4.2, `gltf_exporter_patches.msfs_get_texture_info`), checked through
the multi-exporter and File > Export; with the patch off, the multi-exporter export shows the bug (one scale for all).

To run:
G:\\e-jets-e2\\tools\\blender\\blender.exe -b --factory-startup --python tests/test_normal_scale.py
"""

import json
import shutil
import sys
from pathlib import Path

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

from io_scene_gltf2_msfs_fss.io.com.msfs_material_utils import MSFS2024_MaterialUtils  # noqa: E402
from io_scene_gltf2_msfs_fss.io.exp import export_settings, gltf_exporter_patches  # noqa: E402

SCRATCH_DIR = REPO_ROOT / 'tests' / '_work' / 'normal_scale_scratch'

# name, material type, own Normal Scale (0 to 1); all three use the same normal image
MATERIALS = (('Std', 'msfs_standard', 0.7), ('Coat', 'msfs_clearcoat', 1.0), ('Tire', 'msfs_tire', 0.5))
DETAIL_SCALE = 0.4


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print('PASS:', message)


def image(name, pixel, colorspace):
    path = SCRATCH_DIR / 'tex' / f'{name}.png'
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        im = bpy.data.images.new(name, 8, 8, alpha=False)
        im.pixels = list(pixel) * 64
        im.filepath_raw = str(path)
        im.file_format = 'PNG'
        im.save()
        bpy.data.images.remove(im)
    im = bpy.data.images.load(str(path), check_existing=True)
    im.colorspace_settings.name = colorspace
    return im


def build():
    bpy.ops.wm.read_homefile(use_empty=True)
    objects = []
    for i, (name, material_type, scale) in enumerate(MATERIALS):
        bpy.ops.mesh.primitive_grid_add(x_subdivisions=2, y_subdivisions=2, size=1, location=(i * 2, 0, 0))
        obj = bpy.context.active_object
        obj.name = name.upper()
        material = bpy.data.materials.new(name)
        material.msfs_material_type = material_type
        material.msfs_base_color_texture = image('albd', (0.4, 0.4, 0.4, 1), 'sRGB')
        material.msfs_normal_texture = image('norm', (0.5, 0.5, 1, 1), 'Non-Color')
        material.msfs_normal_scale = scale
        if name == 'Std':
            material.msfs_detail_color_texture = image('dcol', (0.5, 0.5, 0.5, 1), 'sRGB')
            material.msfs_detail_normal_texture = image('norm', (0.5, 0.5, 1, 1), 'Non-Color')
            material.msfs_detail_normal_scale = DETAIL_SCALE
        obj.data.materials.append(material)
        objects.append(obj)
    return objects


def read_materials(path):
    gltf = json.loads(path.read_text(encoding='utf8'))
    return {m['name']: m for m in gltf['materials']}


def export_multi(out_dir):
    objects = build()
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
    preset.preset_name = 'normals'
    preset.folder_path = str(out_dir)
    preset.enabled = True
    layer = preset.layers.add()
    layer.collection = collection
    layer.enabled = True
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)
    bpy.ops.msfs2024.multi_export_gltf(export_mode='PRESETS')
    return read_materials(next(out_dir.glob('*.gltf')))


def export_plain(out_dir):
    build()
    bpy.context.scene.msfs_fss_export_target = 'MSFS2024'
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)
    bpy.ops.export_scene.gltf(filepath=str(out_dir / 'normals.gltf'), export_format='GLTF_SEPARATE', use_visible=True,
                              export_image_format='AUTO')
    return read_materials(out_dir / 'normals.gltf')


def scales(materials):
    return {name: round(materials[name]['normalTexture'].get('scale', 1.0), 4) for name, _type, _scale in MATERIALS}


def test_patch_installed():
    check(gltf_exporter_patches._original_get_texture_info is not None
          and MSFS2024_MaterialUtils.get_texture_info is gltf_exporter_patches.msfs_get_texture_info,
          'the texture info patch is installed at register')


def test_multi_exporter():
    materials = export_multi(SCRATCH_DIR / 'multi')
    want = {name: round(scale, 4) for name, _type, scale in MATERIALS}
    check(scales(materials) == want, f'multi-exporter: each material keeps its own Normal Scale {want}')
    index = {materials[name]['normalTexture']['index'] for name in want}
    check(len(index) == 1, 'multi-exporter: the three materials still share one normal texture')
    detail = materials['Std']['extensions']['ASOBO_material_detail_map']['detailNormalTexture']
    check(round(detail.get('scale', 1.0), 4) == DETAIL_SCALE,
          f'multi-exporter: the Detail Normal Scale {DETAIL_SCALE} is exported, on the same image')


def test_plain_export():
    materials = export_plain(SCRATCH_DIR / 'plain')
    want = {name: round(scale, 4) for name, _type, scale in MATERIALS}
    check(scales(materials) == want, f'File > Export: each material keeps its own Normal Scale {want}')


def test_without_patch_shows_bug():
    patched = MSFS2024_MaterialUtils.get_texture_info
    MSFS2024_MaterialUtils.get_texture_info = staticmethod(gltf_exporter_patches._original_get_texture_info)
    try:
        materials = export_multi(SCRATCH_DIR / 'multi_unpatched')
    finally:
        MSFS2024_MaterialUtils.get_texture_info = patched
    found = scales(materials)
    check(len(set(found.values())) == 1, f'without the patch the multi-exporter gives one scale to all: {found}')


def main():
    test_patch_installed()
    test_multi_exporter()
    test_plain_export()
    test_without_patch_shows_bug()
    print('ALL NORMAL SCALE TESTS PASSED')


try:
    main()
except Exception:
    import traceback
    traceback.print_exc()
    sys.exit(1)
