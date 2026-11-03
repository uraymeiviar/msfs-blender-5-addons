"""The multi-exporter's settings left on the hook class must not outlive the scene they live in (EXP-015).

Without the fix, a multi-export, then a new or opened file, then a plain MSFS 2024 export crashes Blender. The suite
checks the reference before each plain export, so without the fix it reports FAIL and stops instead of crashing.

With the environment variable FSS_SETTINGS_FIX_OFF=1 the clearing is taken out: the suite must then fail.

To run:
G:\\e-jets-e2\\tools\\blender\\blender.exe -b --factory-startup --python tests/test_export_settings_reference.py
"""

import os
import shutil
import sys
from pathlib import Path

import addon_utils
import bpy

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPORTER = 'io_scene_gltf2_msfs_fss'

# The portable Blender enables its deployed addons_core copies at startup: disable and purge them, then import the
# repository's modules first, so addon_utils enables those
for name in ('fss_blender_tools', EXPORTER):
    if addon_utils.check(name)[1]:
        addon_utils.disable(name)
for mod in list(sys.modules):
    if any(mod == name or mod.startswith(name + '.') for name in ('fss_blender_tools', EXPORTER, '_addons_common')):
        del sys.modules[mod]
while str(REPO_ROOT) in sys.path:
    sys.path.remove(str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT))

import io_scene_gltf2_msfs_fss  # noqa: E402

addon_utils.enable(EXPORTER, default_set=True)
assert Path(io_scene_gltf2_msfs_fss.__file__).resolve().is_relative_to(REPO_ROOT), io_scene_gltf2_msfs_fss.__file__

from io_scene_gltf2_msfs_fss import msfs2020_target  # noqa: E402
from io_scene_gltf2_msfs_fss.io.exp import export_settings  # noqa: E402
from io_scene_gltf2_msfs_fss.io.exp.gltf_hooks import Export  # noqa: E402

print('Testing', Path(msfs2020_target.__file__).resolve())
SCRATCH_DIR = REPO_ROOT / 'tests' / '_work' / 'export_settings_scratch'
failures = []


def check(condition, label):
    print(f"{'PASS' if condition else 'FAIL'}: {label}")
    if not condition:
        failures.append(label)
    return condition


def new_file():
    bpy.ops.wm.read_homefile(use_empty=True)
    scene = bpy.context.scene
    mesh = bpy.data.meshes.new('M')
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0)], [], [(0, 1, 2)])
    mesh.update()
    obj = bpy.data.objects.new('O', mesh)
    scene.collection.objects.link(obj)
    scene.msfs_fss_export_target = 'MSFS2024'
    return scene, obj


def multi_export(scene, obj, name):
    scene.msfs_fss_export_target = 'MSFS2024'
    scene.msfs_background_export = False
    scene.msfs_export_mode = 'PRESETS'
    export_settings.init_setting_presets(scene)
    collection = bpy.data.collections.new('E_' + name)
    collection.objects.link(obj)
    scene.collection.children.link(collection)
    preset = scene.msfs_multi_exporter_presets.add()
    preset.preset_name = name
    preset.folder_path = str(SCRATCH_DIR)
    preset.enabled = True
    layer = preset.layers.add()
    layer.collection = collection
    layer.enabled = True
    bpy.ops.msfs2024.multi_export_gltf(export_mode='PRESETS')
    return SCRATCH_DIR / f'{name}.gltf'


def plain_export(name):
    path = SCRATCH_DIR / f'{name}.gltf'
    bpy.ops.export_scene.gltf(filepath=str(path), export_format='GLTF_SEPARATE', use_visible=True)
    return path


def after_load(label, name):
    """The reference is gone, or the plain export that would crash is not attempted."""
    if not check(Export.msfs_export_settings is None, f'{label}: the settings reference is cleared'):
        return False
    return check(plain_export(name).exists(), f'{label}: the plain MSFS 2024 export is written')


def run():
    shutil.rmtree(SCRATCH_DIR, ignore_errors=True)
    SCRATCH_DIR.mkdir(parents=True)
    saved = SCRATCH_DIR / 'scene.blend'

    scene, obj = new_file()
    bpy.ops.wm.save_as_mainfile(filepath=str(saved))
    scene, obj = bpy.context.scene, bpy.data.objects['O']
    written = multi_export(scene, obj, 'first')
    check(written.exists(), 'multi-export: the glTF is written')
    check(Export.msfs_export_settings is not None, 'multi-export: the hooks hold the settings')
    check(plain_export('same_file').exists(), 'same file: a plain export after a multi-export still works')

    new_file()
    if not after_load('new file', 'after_new'):
        return

    bpy.ops.wm.open_mainfile(filepath=str(saved))
    scene, obj = bpy.context.scene, bpy.data.objects['O']
    check(multi_export(scene, obj, 'second').exists(), 'opened file: a multi-export is written')
    bpy.ops.wm.open_mainfile(filepath=str(saved))
    bpy.context.scene.msfs_fss_export_target = 'MSFS2024'
    if not after_load('open file', 'after_open'):
        return

    scene, obj = new_file()
    written = multi_export(scene, obj, 'third')
    check(written.exists(), 'multi-export after a load: the glTF is written')
    check(Export.msfs_export_settings is not None, 'multi-export after a load: the hooks hold the settings again')


if os.environ.get('FSS_SETTINGS_FIX_OFF') == '1':
    bpy.app.handlers.load_pre.remove(msfs2020_target._on_load_pre)

run()
shutil.rmtree(SCRATCH_DIR, ignore_errors=True)
if failures:
    print(f'{len(failures)} FAILURE(S)')
    sys.stdout.flush()
    os._exit(1)
print('ALL EXPORT SETTINGS REFERENCE TESTS PASSED')
sys.stdout.flush()
os._exit(0)
