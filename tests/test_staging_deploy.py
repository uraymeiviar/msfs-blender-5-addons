"""Staging deploy of the E2 repository (ORM levels journal, decisions 7 and 8, Sessions 4 and 7): the exporter's
`<glTF name>.fss-levels.json` and `G:\\e-jets-e2\\scripts\\msfs24-texture-lib.py --stage`, on scratch copies only. The
staging script filters the source of each listed texture with this repository's
`io_scene_gltf2_msfs_fss/orm_levels_filter.py` (its ADDON_LEVELS_FILTER pointed here: the E2 portable Blender's
deployed add-on has no such file yet).

Two parts, both under cpucap.exe 50, one Blender at a time, from the repository root:

1. Exports (background Blender, this repository's add-ons; nothing is written into G:\\e-jets-e2):
   blender -b --factory-startup --python tests/test_staging_deploy.py -- synthetic
       synthetic scenes: the levels list in the four export modes (written only with levels, its SHA-1 that of the
       file, a stale list removed, nothing new without levels), two glTFs sharing a texture with levels, and a
       texture with levels the exporter cannot filter (listed all the same)
   blender -b --factory-startup --python tests/test_staging_deploy.py -- cockpit name=<folder> [levels=1]
       the E2 LOD export script (G:\\e-jets-e2\\scripts\\export-blend-to-gltf-lods.py, fs24) on a copy of
       COCKPIT.blend in tests/_work/staging_deploy/e2 (made by `prepare`), with levels on Leather_comp.png when
       levels=1 (set in memory after each file load; the copy is never saved)
2. Deploys (plain Python, G:\\e-jets-e2\\tools\\blender\\5.2\\python\\bin\\python.exe -I):
   python tests/test_staging_deploy.py prepare     copies of the cockpit .blend, sources and package folders
   python tests/test_staging_deploy.py deploy      finish lines 1 to 5 of Session 6's hand-off (and Session 3's)

Order: prepare, cockpit name=cockpit_nolevels, cockpit name=cockpit_nolevels_2, cockpit name=cockpit_levels
levels=1, synthetic, deploy. The in-place reference is the script as it was before the staging mode
(G:\\e-jets-e2\\codes\\wasm\\.cache\\backup\\msfs24-texture-lib.py.before-staging), run with its source folder pointed at
the scratch copy of the sources.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORK = REPO_ROOT / 'tests' / '_work' / 'staging_deploy'
E2 = Path(r'G:\e-jets-e2')
E2_PACKAGE = E2 / 'msfs24-projects' / 'fss-aircraft-e2-190' / 'SimObjects' / 'Airplanes' / 'E2-190'
SCRIPT = E2 / 'scripts' / 'msfs24-texture-lib.py'
OLD_SCRIPT = E2 / 'codes' / 'wasm' / '.cache' / 'backup' / 'msfs24-texture-lib.py.before-staging'
LOD_EXPORT = E2 / 'scripts' / 'export-blend-to-gltf-lods.py'
ADDON_TEXTURE_LIB = E2 / 'tools' / 'blender' / '5.2' / 'scripts' / 'addons_core' / 'io_scene_gltf2_msfs_fss' / 'io' / \
    'exp' / 'texture_lib'
ADDON_LEVELS_FILTER = REPO_ROOT / 'io_scene_gltf2_msfs_fss' / 'orm_levels_filter.py'
PYTHON = E2 / 'tools' / 'blender' / '5.2' / 'python' / 'bin' / 'python.exe'
LEVELED_SHA1 = '1147840fea12f01616c105f6c2b6ddd98aadddaa'  # the exporter's filtered Leather_comp.png, Sessions 4 and 5
SCRATCH_E2 = WORK / 'e2'
SOURCES = SCRATCH_E2 / 'assets' / 'visual' / 'texture'
COCKPIT_BLEND = SCRATCH_E2 / 'assets' / 'visual' / 'cockpit' / 'COCKPIT.blend'
PKG_BASE = WORK / 'pkg_base'  # copies of the E2-190 model and texture folders
LEVELED = 'Leather_comp.png'
LEVELS = ((0.0, 1.0, 1.0, 0.0, 0.5), (0.1, 1.2, 0.9, 0.0, 1.0), (0.0, 1.0, 1.0, 0.0, 1.0))
CHANNELS = ('occlusion', 'roughness', 'metallic')
FIELDS = ('in_black', 'gamma', 'in_white', 'out_black', 'out_white')


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print('PASS:', message)


def sha1(path):
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()


# region Blender part

def purge_and_import():
    """The portable Blender enables its deployed addons_core copies: purge them and import this repository's."""
    import addon_utils
    for addon in ('io_scene_gltf2_msfs_fss', 'fss_blender_tools'):
        if addon_utils.check(addon)[1]:
            addon_utils.disable(addon)
        for mod in list(sys.modules):
            if mod == addon or mod.startswith(addon + '.'):
                del sys.modules[mod]
    while str(REPO_ROOT) in sys.path:
        sys.path.remove(str(REPO_ROOT))
    sys.path.insert(0, str(REPO_ROOT))
    import io_scene_gltf2_msfs_fss  # noqa: F401
    addon_utils.enable('io_scene_gltf2_msfs_fss', default_set=True)
    for addon in ('io_scene_gltf2_msfs_fss',):
        assert Path(sys.modules[addon].__file__).resolve().is_relative_to(REPO_ROOT), sys.modules[addon].__file__


def set_levels(image, levels):
    for channel, values in zip(CHANNELS, levels):
        group = getattr(image.fss_orm_levels, channel)
        for field, value in zip(FIELDS, values):
            setattr(group, field, value)


def blender_cockpit(args):
    """The E2 LOD export script on the scratch copy of COCKPIT.blend, into tests/_work/staging_deploy/<name>."""
    import atexit
    import runpy
    import bpy
    import addon_utils
    purge_and_import()
    import fss_blender_tools  # noqa: F401  (the export script enables it; this repository's copy)
    addon_utils.enable('fss_blender_tools', default_set=True)
    from io_scene_gltf2_msfs_fss import orm_levels
    name = args['name']
    out = WORK / name
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    with_levels = args.get('levels') == '1'
    info = {'levels': with_levels, 'loads': []}

    def apply_levels(*_args):
        # Images whose path does not resolve from the copy: pointed at the source of the same name (in memory)
        remapped, missing = [], []
        for i in bpy.data.images:
            if i.source != 'FILE' or not i.filepath or i.library is not None or i.packed_file is not None:
                continue
            path = Path(bpy.path.abspath(i.filepath))
            if path.is_file():
                continue
            if (SOURCES / path.name).is_file():
                remapped.append(f'{i.name}: {i.filepath}')
                i.filepath = str(SOURCES / path.name)
            else:
                missing.append(f'{i.name}: {i.filepath}')
        image = next((i for i in bpy.data.images if Path(bpy.path.abspath(i.filepath)).name == LEVELED), None)
        info['loads'].append({'file': bpy.data.filepath, 'leveled_image': image.name if image else None,
                              'remapped_images': remapped, 'missing_images': missing})
        if with_levels and image is not None:
            set_levels(image, LEVELS)

    def write_info():
        info['stats'] = dict(orm_levels.stats)
        info['addon'] = sys.modules['io_scene_gltf2_msfs_fss'].__file__
        (out / 'blender-info.json').write_text(json.dumps(info, indent=2), encoding='utf-8')

    bpy.app.handlers.load_post.append(bpy.app.handlers.persistent(apply_levels))
    atexit.register(write_info)
    # COCKPIT.blend is saved with a viewport in local view: Asobo's disable_isolate_mode then calls
    # view3d.localview without an area and the multi-export fails in background. Files open without their UI here.
    bpy.context.preferences.filepaths.use_load_ui = False
    bpy.ops.wm.open_mainfile(filepath=str(COCKPIT_BLEND), load_ui=False)
    orm_levels.clear_cache()
    sys.argv = [str(LOD_EXPORT), '--', str(out) + os.sep + '.', 'E2-190-Cockpit.gltf', 'fs24']
    write_info()
    runpy.run_path(str(LOD_EXPORT), run_name='__main__')
    write_info()


def blender_synthetic():
    """Synthetic exports: the levels list in the four modes and two glTFs sharing a texture with levels."""
    import bpy
    import numpy as np
    purge_and_import()
    from io_scene_gltf2_msfs_fss import orm_levels as ol
    from io_scene_gltf2_msfs_fss.io.exp import export_settings
    from io_scene_gltf2_msfs_fss.io.exp.gltf_hooks import Export

    root = WORK / 'synthetic'
    shutil.rmtree(root, ignore_errors=True)
    src = root / 'src'
    src.mkdir(parents=True)
    rng = np.random.default_rng(20261114)

    def write_png(path, size, seed_shift):
        image = bpy.data.images.new(path.stem, size, size, alpha=False)
        pixels = rng.random((size, size, 4), dtype=np.float32)
        pixels[..., 3] = 1.0
        image.pixels.foreach_set(pixels.ravel())
        image.filepath_raw = str(path)
        image.file_format = 'PNG'
        image.save()
        bpy.data.images.remove(image)

    for stem in ('shared_comp', 'plain_detail', 'other_comp'):
        write_png(src / f'{stem}.png', 16, 0)

    def load(stem):
        image = bpy.data.images.load(str(src / f'{stem}.png'), check_existing=True)
        image.colorspace_settings.name = 'Non-Color'
        return image

    def scene(levels, panels=2):
        """PANEL_0 with MAT_A (ORM shared_comp, detail plain_detail) and MAT_C (ORM other_comp); with panels=2 also
        PANEL_1 with MAT_B (ORM shared_comp)."""
        bpy.ops.wm.read_homefile(use_empty=True)
        a = bpy.data.materials.new('MAT_A')
        a.msfs_material_type = 'msfs_standard'
        a.msfs_occlusion_metallic_roughness_texture = load('shared_comp')
        a.msfs_detail_occlusion_metallic_roughness_texture = load('plain_detail')
        b = bpy.data.materials.new('MAT_B')
        b.msfs_material_type = 'msfs_standard'
        b.msfs_occlusion_metallic_roughness_texture = load('shared_comp')
        c = bpy.data.materials.new('MAT_C')
        c.msfs_material_type = 'msfs_standard'
        c.msfs_occlusion_metallic_roughness_texture = load('other_comp')
        set_levels(load('shared_comp'), LEVELS if levels else ((0.0, 1.0, 1.0, 0.0, 1.0),) * 3)
        objects = []
        for index, materials in enumerate(((a, c), (b,))[:panels]):
            bpy.ops.mesh.primitive_grid_add(x_subdivisions=2, y_subdivisions=2, size=1, location=(index * 2, 0, 0))
            obj = bpy.context.active_object
            obj.name = f'PANEL_{index}'
            for material in materials:
                obj.data.materials.append(material)
            for polygon in obj.data.polygons:  # every material slot has faces
                polygon.material_index = polygon.index % len(materials)
            objects.append(obj)
        return objects

    def multi_export(out, groups):
        """One multi-export, one preset per group of objects (glTF `panel_<index>`)."""
        sc = bpy.context.scene
        sc.msfs_fss_export_target = 'MSFS2024'
        sc.msfs_background_export = False
        sc.msfs_export_mode = 'PRESETS'
        export_settings.init_setting_presets(sc)
        settings = export_settings.get_active_export_settings(sc)
        settings.enable_msfs_extension = True
        settings.generate_texturelib = False
        settings.export_apply = True
        settings.export_keep_originals = False
        settings.export_texture_dir = ''
        for preset in sc.msfs_multi_exporter_presets:
            preset.enabled = False
        for index, group in enumerate(groups):
            collection = bpy.data.collections.new(f'FSS_EXPORT_{index}')
            for obj in group:
                collection.objects.link(obj)
            sc.collection.children.link(collection)
            preset = sc.msfs_multi_exporter_presets.add()
            preset.preset_name = f'panel_{index}'
            preset.folder_path = str(out)
            preset.enabled = True
            layer = preset.layers.add()
            layer.collection = collection
            layer.enabled = True
        result = bpy.ops.msfs2024.multi_export_gltf(export_mode='PRESETS')
        check('FINISHED' in result, f'multi-export into {out.name} finished')

    def plain_export(out, mode):
        sc = bpy.context.scene
        sc.msfs_fss_export_target = 'MSFS2020' if mode == 'fs20' else 'MSFS2024'
        try:
            if mode == 'plain':
                Export.msfs_export_settings = None
            elif mode == 'plain_msfs':
                export_settings.init_setting_presets(sc)
                settings = export_settings.get_active_export_settings(sc)
                settings.enable_msfs_extension = True
                Export.msfs_export_settings = settings
            bpy.ops.export_scene.gltf(filepath=str(out / 'panel_0.gltf'), export_format='GLTF_SEPARATE',
                                      use_visible=True, export_image_format='AUTO')
        finally:
            Export.msfs_export_settings = None

    def export(mode, levels, out, panels=1):
        out.mkdir(parents=True, exist_ok=True)
        objects = scene(levels, panels)
        if mode == 'fs24':
            multi_export(out, [objects])
        else:
            plain_export(out, mode)

    print('--- the levels list in every export mode')
    # Each export into its own folder: outside the multi-exporter the exporter's ExportedImageCache is not reset, so
    # a second export into the same folder in one session does not write its images again (a finding, see below)
    for mode in ('fs24', 'fs20', 'plain', 'plain_msfs'):
        out = root / f'list_{mode}_default'
        export(mode, False, out)
        names = sorted(p.name for p in out.iterdir())
        check(not any(n.endswith('.fss-levels.json') for n in names), f'{mode}: no list without levels ({names})')
        out = root / f'list_{mode}'
        export(mode, True, out)
        listing = out / 'panel_0.fss-levels.json'
        check(listing.is_file(), f'{mode}: panel_0.fss-levels.json written with levels')
        content = json.loads(listing.read_text(encoding='utf-8'))
        files = [entry['file'] for entry in content['images']]
        check(files == ['shared_comp.png'], f'{mode}: the list names only the texture with levels ({files})')
        entry = content['images'][0]
        check(entry['sha1'] == sha1(out / 'shared_comp.png'), f'{mode}: its SHA-1 is that of the file written')
        check(entry['sha1'] != sha1(src / 'shared_comp.png'), f'{mode}: the file written is not the source')
        listed = [entry['levels'][c][f] for c in CHANNELS for f in FIELDS]
        check(entry['image'] == 'shared_comp.png' and
              all(abs(a - b) < 1e-6 for a, b in zip(listed, [v for c in LEVELS for v in c])) and len(listed) == 15,
              f'{mode}: the list names the image and its 15 values')
        check(content['gltf'] == 'panel_0.gltf', f'{mode}: the list names its glTF')
        export(mode, False, out)
        check(not listing.exists(), f'{mode}: a later export without levels removes the stale list')

    print('--- a second plain export into the same folder (a finding, not a check)')
    out = root / 'same_folder_fs20'
    export('fs20', False, out)
    first = sha1(out / 'shared_comp.png')
    export('fs20', True, out)
    print(f'INFO: fs20 export with levels after one without, same folder: shared_comp.png rewritten '
          f'{sha1(out / "shared_comp.png") != first}')

    print('--- MSFS 2020: one image in two materials (a finding, not a check)')
    for levels in (False, True):
        out = root / f'fs20_shared_{"levels" if levels else "default"}'
        export('fs20', levels, out, panels=2)
        gltf = json.loads((out / 'panel_0.gltf').read_text(encoding='utf-8'))
        uris = [i.get('uri') for i in gltf.get('images', [])]
        print(f'INFO: fs20, levels {levels}: image URIs {uris}; files {sorted(p.name for p in out.glob("*.png"))}; '
              f'missing {[u for u in uris if not (out / u).is_file()]}')

    print('--- two glTFs sharing a texture with levels')
    out = root / 'shared'
    out.mkdir(parents=True)
    objects = scene(True)
    ol.clear_cache()
    multi_export(out, [[objects[0]], [objects[1]]])
    stats = dict(ol.stats)
    print(f'INFO: filter stats {stats}')
    check(stats['filtered'] == 1, f'the shared texture is filtered once ({stats})')
    lists = sorted(p.name for p in out.glob('*.fss-levels.json'))
    check(lists == ['panel_0.fss-levels.json', 'panel_1.fss-levels.json'], f'one list per glTF ({lists})')
    shas = {json.loads((out / n).read_text(encoding='utf-8'))['images'][0]['sha1'] for n in lists}
    check(shas == {sha1(out / 'shared_comp.png')}, 'both lists name the same written file')
    (out / 'blender-stats.json').write_text(json.dumps(stats), encoding='utf-8')

    print('--- a texture with levels the exporter cannot filter is listed all the same')
    out = root / 'unfilterable'
    (out / 'src').mkdir(parents=True)
    grey = rng.integers(0, 256, size=(16, 16, 1))
    (out / 'src' / 'grey_comp.png').write_bytes(ol.encode_png(grey, 8, 0))  # one channel for three different levels
    bpy.ops.wm.read_homefile(use_empty=True)
    g = bpy.data.materials.new('MAT_G')
    g.msfs_material_type = 'msfs_standard'
    image = bpy.data.images.load(str(out / 'src' / 'grey_comp.png'), check_existing=True)
    image.colorspace_settings.name = 'Non-Color'
    g.msfs_occlusion_metallic_roughness_texture = image
    set_levels(image, LEVELS)
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=2, y_subdivisions=2, size=1)
    panel = bpy.context.active_object
    panel.name = 'PANEL_0'
    panel.data.materials.append(g)
    ol.clear_cache()
    multi_export(out, [[panel]])
    check(ol.stats['filtered'] == 0, f'the exporter filtered nothing ({dict(ol.stats)})')
    listing = out / 'panel_0.fss-levels.json'
    check(listing.is_file(), 'panel_0.fss-levels.json written although nothing was filtered')
    content = json.loads(listing.read_text(encoding='utf-8'))
    files = [entry['file'] for entry in content['images']]
    print(f'INFO: listed {files}; exported {sorted(p.name for p in out.glob("*.png"))}')
    entry = content['images'][0]
    listed = [entry['levels'][c][f] for c in CHANNELS for f in FIELDS]
    check(len(files) == 1 and entry['image'] == 'grey_comp.png' and
          all(abs(a - b) < 1e-6 for a, b in zip(listed, [v for c in LEVELS for v in c])),
          f'the list names the texture of grey_comp.png with its 15 values ({files})')
    check(files == ['grey_comp.png'] and sha1(out / 'grey_comp.png') == sha1(out / 'src' / 'grey_comp.png'),
          'the exported grey_comp.png is the unfiltered source')
    print('ALL STAGING DEPLOY SYNTHETIC EXPORTS PASSED')

# endregion


# region Plain Python part

def run(script_code, args, label):
    """Runs Python code (`script_code` sees `ARGS`) in Blender's Python, returns (exit code, output)."""
    code = f'import sys\nARGS = {list(map(str, args))!r}\n' + script_code
    result = subprocess.run([str(PYTHON), '-I', '-B', '-c', code], capture_output=True, text=True, cwd=str(WORK))
    output = result.stdout + result.stderr
    (WORK / 'logs').mkdir(exist_ok=True)
    (WORK / 'logs' / f'{label}.txt').write_text(output, encoding='utf-8')
    print(f'INFO: {label}: exit {result.returncode}, {len(output.splitlines())} lines (logs/{label}.txt)')
    return result.returncode, output


LOAD = """
from importlib.machinery import SourceFileLoader
mod = SourceFileLoader('texture_lib_under_test', {path!r}).load_module()
mod.ADDON_TEXTURE_LIB = {lib!r}
mod.ADDON_LEVELS_FILTER = {levels_filter!r}
"""


def loader(path, levels_filter=ADDON_LEVELS_FILTER):
    return LOAD.format(path=str(path), lib=str(ADDON_TEXTURE_LIB), levels_filter=str(levels_filter))


OLD_RUNNER = loader(OLD_SCRIPT) + f'mod.SOURCE_TEXTURE_DIR = {str(SOURCES)!r}\nsys.exit(mod.main(ARGS))\n'
NEW_RUNNER = loader(SCRIPT) + 'sys.exit(mod.main(ARGS))\n'
# The filter module is not where the script looks for it
NO_FILTER_RUNNER = loader(SCRIPT, WORK / 'no_such_addon' / 'orm_levels_filter.py') + 'sys.exit(mod.main(ARGS))\n'
# The XML of FAIL_XML cannot be written (XmlSerializer.save returns False for it)
FAIL_XML_RUNNER = loader(SCRIPT) + """
load = mod.load_texture_lib
def load_failing():
    modules = load()
    serializer = modules[2].XmlSerializer
    save = serializer.save
    def failing(self, *a, **k):
        if str(self.xml_path).replace('\\\\', '/').endswith('/' + FAIL_XML):
            print('[test] XmlSerializer.save refused for', self.xml_path)
            return False
        return save(self, *a, **k)
    serializer.save = failing
    return modules
mod.load_texture_lib = load_failing
FAIL_XML = ARGS.pop(0)
sys.exit(mod.main(ARGS))
"""


def snapshot(folder):
    """{relative path: (SHA-1, modification time in ns)} of every file below `folder`."""
    folder = Path(folder)
    return {p.relative_to(folder).as_posix(): (sha1(p), p.stat().st_mtime_ns) for p in sorted(folder.rglob('*'))
            if p.is_file()}


def fresh_package(name, base=PKG_BASE):
    target = WORK / name
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(base, target, copy_function=shutil.copy2)
    return target


def in_place(package, export, label):
    """The deploy before the staging mode: xcopy of each glTF and bin, then the old script in place."""
    gltfs = sorted(Path(export).glob('*.gltf'))
    for gltf in gltfs:
        shutil.copy2(gltf, package / 'model' / gltf.name)
        bin_path = gltf.with_suffix('.bin')
        if bin_path.is_file():
            shutil.copy2(bin_path, package / 'model' / bin_path.name)
    return run(OLD_RUNNER, [str(package / 'model' / g.name) for g in gltfs], label)


def stage_args(package, export, pattern, source=SOURCES):
    return ['--stage', '--export-dir', str(export), '--package-model-dir', str(package / 'model'),
            '--package-texture-dir', str(package / 'texture'), '--source-dir', str(source), pattern]


def stage(package, export, pattern, label, runner=NEW_RUNNER, extra=(), source=SOURCES):
    return run(runner, list(extra) + stage_args(package, export, pattern, source), label)


def copied_count(output):
    line = next((l for l in output.splitlines() if l.startswith('[texture-lib] package:')), '')
    return int(line.split(':')[1].split('file')[0]) if line else None


def compare_packages(a, b):
    sa = {k: v[0] for k, v in snapshot(a).items()}
    sb = {k: v[0] for k, v in snapshot(b).items()}
    names_equal = sorted(sa) == sorted(sb)
    differing = sorted(k for k in sa if k in sb and sa[k] != sb[k])
    return names_equal, differing, len(sa), sorted(set(sa) ^ set(sb))


def export_variant(name, export, textures=()):
    """A copy of the export folder's glTFs, bins and levels lists (and of `textures`) under WORK/<name>."""
    target = WORK / name
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir()
    for p in Path(export).iterdir():
        if p.is_file() and (p.suffix in ('.gltf', '.bin') or p.name.endswith('.fss-levels.json') or p.name in textures):
            shutil.copy2(p, target / p.name)
    return target


def source_variant(name, drop=(), replace=None):
    """The texture sources under WORK/<name> as hard links (no copy of 750 MB), without `drop`, with `replace`
    ({file name: bytes}) written as new files (never through a link into the sources)."""
    target = WORK / name
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir()
    replace = replace or {}
    for p in SOURCES.iterdir():
        if p.is_file() and p.name not in drop and p.name not in replace:
            os.link(p, target / p.name)
    for file, data in replace.items():
        (target / file).write_bytes(data)
    return target


def filtered_lines(output):
    return [l for l in output.splitlines() if l.startswith('[texture-lib] filtered')]


def used_textures(gltf_dir):
    names = set()
    for gltf in Path(gltf_dir).glob('*.gltf'):
        data = json.loads(gltf.read_text(encoding='utf-8'))
        names |= {Path(i['uri']).name for i in data.get('images', []) if i.get('uri')}
    return names


def prepare():
    """Scratch copies: the cockpit .blend and its texture sources (same relative layout), the package folders."""
    cockpit = E2 / 'assets' / 'visual' / 'cockpit'
    COCKPIT_BLEND.parent.mkdir(parents=True, exist_ok=True)
    for name in ('COCKPIT.blend', 'COCKPIT.visibility'):
        shutil.copy2(cockpit / name, COCKPIT_BLEND.parent / name)
    shutil.rmtree(SOURCES, ignore_errors=True)
    shutil.copytree(E2 / 'assets' / 'visual' / 'texture', SOURCES, copy_function=shutil.copy2)
    shutil.rmtree(PKG_BASE, ignore_errors=True)
    for name in ('model', 'texture'):
        shutil.copytree(E2_PACKAGE / name, PKG_BASE / name, copy_function=shutil.copy2)
    print('prepared', WORK)


def deploy_tests():
    nolevels, nolevels_2, levels = WORK / 'cockpit_nolevels', WORK / 'cockpit_nolevels_2', WORK / 'cockpit_levels'
    for folder in (nolevels, nolevels_2, levels):
        check(folder.is_dir(), f'export folder {folder.name} exists')
    for folder in (nolevels, nolevels_2, levels):
        info = json.loads((folder / 'blender-info.json').read_text(encoding='utf-8'))
        check(Path(info['addon']).resolve().is_relative_to(REPO_ROOT), f'{folder.name}: exported by this repository')
        missing = sorted({m for load in info['loads'] for m in load['missing_images']})
        print(f'INFO: {folder.name}: images missing on load: {missing}; filter stats {info.get("stats")}')
    base = snapshot(PKG_BASE)
    gltf_pattern = 'E2-190-Cockpit_LOD0*.gltf'

    print('--- 1: without levels, staging leaves the files the in-place deploy leaves')
    check(not list(nolevels.glob('*.fss-levels.json')), 'the export without levels wrote no levels list')
    old_pkg = fresh_package('pkg_inplace_nolevels')
    code_old, _ = in_place(old_pkg, nolevels, 'inplace_nolevels')
    check(code_old == 0, f'in-place deploy exit {code_old}')
    new_pkg = fresh_package('pkg_stage_nolevels')
    code_new, out_new = stage(new_pkg, nolevels, gltf_pattern, 'stage_nolevels')
    check(code_new == 0, f'staging deploy exit {code_new}')
    names_equal, differing, count, extra = compare_packages(old_pkg, new_pkg)
    print(f'INFO: {count} files compared; copied {copied_count(out_new)}')
    check(names_equal, f'the same {count} file names ({extra})')
    check(not differing, f'every file byte-identical ({differing})')
    check(not list(new_pkg.rglob('*.fss-staging-tmp')), 'no temporary file left in the package')

    print('--- 3: a second deploy without changes copies nothing')
    before = snapshot(new_pkg)
    code, out = stage(new_pkg, nolevels, gltf_pattern, 'stage_nolevels_again')
    check(code == 0 and copied_count(out) == 0, f'same export again: exit {code}, {copied_count(out)} files copied')
    check(snapshot(new_pkg) == before, f'{len(before)} files: bytes and modification times unchanged')
    exported = [p.name for p in sorted(nolevels.glob('E2-190-Cockpit_LOD0*.*')) if p.suffix in ('.gltf', '.bin')]
    same = [n for n in exported if (nolevels_2 / n).is_file() and sha1(nolevels / n) == sha1(nolevels_2 / n)]
    print(f'INFO: second export of the unchanged copy: {len(same)} of {len(exported)} glTF/bin files identical')
    code, out = stage(new_pkg, nolevels_2, gltf_pattern, 'stage_nolevels_reexport')
    copies = [l.split()[-1].replace('\\', '/') for l in out.splitlines() if l.startswith('[texture-lib] copied')]
    differing_exports = sorted(set(exported) - set(same))
    print(f'INFO: a new export of the unchanged .blend: exit {code}, {copied_count(out)} files copied {copies}')
    check(code == 0 and sorted(Path(c).name for c in copies) == differing_exports,
          f'a new export: only the glTF/bin files the exporter wrote differently are copied ({len(copies)})')
    after = snapshot(new_pkg)
    textures_same = ({k: v for k, v in after.items() if k.startswith('texture/')} ==
                     {k: v for k, v in before.items() if k.startswith('texture/')})
    check(textures_same, 'a new export: every texture and XML keeps its bytes and modification time')
    before = after

    print('--- 2: with levels on one texture')
    listing = sorted(levels.glob('*.fss-levels.json'))
    entries = {}
    for path in listing:
        for entry in json.loads(path.read_text(encoding='utf-8'))['images']:
            values = tuple(entry['levels'][c][f] for c in CHANNELS for f in FIELDS)
            entries.setdefault(entry['file'], set()).add((entry.get('sha1'), values))
    print(f'INFO: {len(listing)} levels lists: {sorted(p.name for p in listing)}; files {sorted(entries)}')
    check(sorted(entries) == [LEVELED] and len(entries[LEVELED]) == 1,
          f'the lists name {LEVELED} only, with one set of values')
    listed_sha1, values = next(iter(entries[LEVELED]))
    check(len(values) == 15 and all(abs(a - b) < 1e-6 for a, b in zip(values, [v for c in LEVELS for v in c])),
          f'the lists hold the 15 values set on {LEVELED}')
    filtered = levels / LEVELED
    print(f'INFO: the exporter wrote {LEVELED} SHA-1 {sha1(filtered)} (listed {listed_sha1}); source '
          f'{sha1(SOURCES / LEVELED)}')
    check(sha1(filtered) == LEVELED_SHA1 and listed_sha1 == LEVELED_SHA1,
          f'the exporter filtered PNG of this export is the one of Sessions 4 and 5 ({LEVELED_SHA1[:8]})')
    old_pkg = fresh_package('pkg_inplace_levels')
    code_old, _ = in_place(old_pkg, levels, 'inplace_levels')
    check(code_old == 0, f'in-place deploy exit {code_old}')
    new_pkg = fresh_package('pkg_stage_levels')
    code_new, out_new = stage(new_pkg, levels, gltf_pattern, 'stage_levels')
    check(code_new == 0, f'staging deploy exit {code_new}')
    check((new_pkg / 'texture' / LEVELED).read_bytes() == filtered.read_bytes(),
          f'the package {LEVELED} equals the exporter filtered PNG byte for byte')
    leveled_filtered = filtered_lines(out_new)
    print(f'INFO: {leveled_filtered}')
    check(len(leveled_filtered) == 1 and LEVELED in leveled_filtered[0] and str(SOURCES) in leveled_filtered[0],
          f'5: {LEVELED}, listed by {len(listing)} LOD glTFs, is filtered once, from its source')
    # Made from the source: the same package files without the export's PNG and with another export PNG
    pristine = snapshot(new_pkg)
    for label, textures, changed in (('without the export PNG', (), False), ('with the export PNG changed',
                                                                            (LEVELED,), True)):
        variant = export_variant('cockpit_levels_variant', levels, textures)
        if changed:
            data = bytearray((variant / LEVELED).read_bytes())
            data[-20] ^= 0xFF
            (variant / LEVELED).write_bytes(bytes(data))
        code, out = stage(new_pkg, variant, gltf_pattern, f'stage_levels_{"changed" if changed else "nopng"}')
        staged = variant / 'staging' / 'texture' / LEVELED
        check(code == 0 and copied_count(out) == 0 and staged.read_bytes() == filtered.read_bytes(),
              f'2: {label}: exit {code}, the staged {LEVELED} is the exporter filtered PNG, {copied_count(out)} '
              'files copied')
        check(snapshot(new_pkg) == pristine, f'2: {label}: the package files keep their bytes and times')
        shutil.rmtree(variant, ignore_errors=True)
    used = used_textures(levels) - {LEVELED}
    unequal = sorted(n for n in used if sha1(new_pkg / 'texture' / n) != sha1(SOURCES / n))
    check(not unequal, f'the other {len(used)} textures equal their sources ({unequal})')
    names_equal, differing, count, extra = compare_packages(old_pkg, new_pkg)
    check(names_equal, f'the same {count} file names as in place ({extra})')
    check(differing == [f'texture/{LEVELED}'], f'only {LEVELED} differs from the in-place run ({differing})')
    gltfs = sorted(p.name for p in (new_pkg / 'model').glob('*.gltf'))
    xmls = sorted(p.name for p in (new_pkg / 'texture').glob('*.xml'))
    check(all(sha1(new_pkg / 'model' / n) == sha1(old_pkg / 'model' / n) for n in gltfs),
          f'{len(gltfs)} glTFs (URIs) equal the in-place run')
    check(all(sha1(new_pkg / 'texture' / n) == sha1(old_pkg / 'texture' / n) for n in xmls),
          f'{len(xmls)} XMLs equal the in-place run')
    lines = [l for l in out_new.splitlines() if l.startswith('[texture-lib] copied')]
    print(f'INFO: staging copied {len(lines)} file(s): {[l.split()[-1] for l in lines][:12]}')
    leveled_copies = [l for l in lines if l.endswith('/' + LEVELED) or l.endswith('\\' + LEVELED)]
    check(len(leveled_copies) == 1, f'{LEVELED}, used by several LOD glTFs, is copied once ({len(leveled_copies)})')
    before = snapshot(new_pkg)
    code, out = stage(new_pkg, levels, gltf_pattern, 'stage_levels_again')
    check(code == 0 and copied_count(out) == 0, f'3: with levels, same export again: {copied_count(out)} copied')
    check(snapshot(new_pkg) == before, f'3: {len(before)} files: bytes and modification times unchanged')

    print('--- 4: a failure after staging starts leaves the package untouched')
    fail_pkg = fresh_package('pkg_fail', base=new_pkg)
    (fail_pkg / 'texture' / f'{LEVELED}.xml').unlink()  # so its XML has to be written
    before = snapshot(fail_pkg)
    code, out = stage(fail_pkg, levels, gltf_pattern, 'fail_xml', runner=FAIL_XML_RUNNER, extra=[f'{LEVELED}.xml'])
    check(code != 0 and 'could not write' in out, f'an XML that cannot be written: exit {code}')
    check(snapshot(fail_pkg) == before, f'{len(before)} package files: bytes and modification times unchanged')
    shutil.rmtree(WORK / 'cockpit_levels_corrupt', ignore_errors=True)  # Session 4's variant, no longer used

    print('--- 4: the errors of the levels step leave the package untouched')
    first_list = listing[0].name

    def failing(label, export, expected, runner=NEW_RUNNER, source=SOURCES):
        code, out = stage(fail_pkg, export, gltf_pattern, f'fail_{label}', runner=runner, source=source)
        found = [l for l in out.splitlines() if expected in l]
        print(f'INFO: {label}: {found[:1]}')
        check(code != 0 and found and 'the package was not changed' in out, f'4: {label}: exit {code}')
        check(snapshot(fail_pkg) == before, f'4: {label}: {len(before)} package files keep their bytes and times')

    variant = export_variant('cockpit_levels_variant', levels)
    (variant / first_list).write_text((levels / first_list).read_text(encoding='utf-8')[:-40], encoding='utf-8')
    failing('list_unreadable', variant, f'{first_list} cannot be read')
    variant = export_variant('cockpit_levels_variant', levels)
    content = json.loads((levels / first_list).read_text(encoding='utf-8'))
    content['images'][0]['levels']['roughness']['in_white'] = 0.8
    (variant / first_list).write_text(json.dumps(content, indent=2), encoding='utf-8')
    failing('different_levels', variant, f"'{LEVELED}' has different ORM levels in")
    variant = export_variant('cockpit_levels_variant', levels)
    no_source = source_variant('sources_no_leveled', drop=(LEVELED,))
    check((fail_pkg / 'texture' / LEVELED).is_file(), f'the package has a {LEVELED} the deploy could fall back to')
    failing('no_source', variant, f"'{LEVELED}' has ORM levels but no source", source=no_source)
    failing('filter_missing', variant, 'orm_levels_filter.py is missing', runner=NO_FILTER_RUNNER)
    broken_source = source_variant('sources_broken_leveled', replace={LEVELED: b'not a PNG file'})
    failing('filter_fails', variant, f"'{LEVELED}': the ORM levels filter failed", source=broken_source)
    shutil.rmtree(no_source, ignore_errors=True)
    shutil.rmtree(broken_source, ignore_errors=True)
    for p in variant.glob('*.gltf'):
        text = p.read_text(encoding='utf-8')
        p.write_text(text.replace('"Leather_albd.png"', '"Leather_albd_missing.png"'), encoding='utf-8', newline='')
    failing('texture_missing', variant, "'Leather_albd_missing.png' is neither")
    shutil.rmtree(variant, ignore_errors=True)

    print('--- 4 and 5 on the synthetic export (two glTFs, one texture with levels)')
    syn = WORK / 'synthetic'
    shared = syn / 'shared'
    check(shared.is_dir(), 'export folder synthetic/shared exists')
    syn_base = syn / 'pkg_base'
    shutil.rmtree(syn_base, ignore_errors=True)
    (syn_base / 'model').mkdir(parents=True)
    (syn_base / 'texture').mkdir()
    shutil.copy2(syn / 'src' / 'shared_comp.png', syn_base / 'texture' / 'shared_comp.png')  # unfiltered, older
    (syn_base / 'texture' / 'plain_detail.png').write_bytes(b'older')
    (syn_base / 'texture' / 'plain_detail.png.xml').write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<BitmapConfiguration>\n'
        '<BitmapSlot>MTL_BITMAP_DETAIL_METAL_ROUGH_AO</BitmapSlot>\n<UserFlags Type="_DEFAULT">QUALITYHIGH</UserFlags>\n'
        '</BitmapConfiguration>\n', encoding='utf-8')
    stats = json.loads((shared / 'blender-stats.json').read_text(encoding='utf-8'))
    check(stats['filtered'] == 1, f'5: the exporter filtered shared_comp.png once for the two glTFs ({stats})')
    source_missing = syn / 'src_missing'
    shutil.rmtree(source_missing, ignore_errors=True)
    shutil.copytree(syn / 'src', source_missing)
    (source_missing / 'other_comp.png').unlink()
    pkg = fresh_package('syn_pkg_fail', base=syn_base)
    before = snapshot(pkg)
    code, out = stage(pkg, shared, 'panel_*.gltf', 'syn_fail_missing', source=source_missing)
    check(code != 0 and "'other_comp.png' is neither" in out, f'4: a missing source texture: exit {code}')
    check(snapshot(pkg) == before, f'4: {len(before)} package files unchanged')
    pkg = fresh_package('syn_pkg', base=syn_base)
    code, out = stage(pkg, shared, 'panel_*.gltf', 'syn_stage', source=syn / 'src')
    check(code == 0, f'5: staging deploy exit {code}')
    lines = [l for l in out.splitlines() if l.startswith('[texture-lib] copied')]
    shared_copies = [l for l in lines if l.endswith('shared_comp.png')]
    check(len(shared_copies) == 1, f'5: shared_comp.png copied once ({len(shared_copies)})')
    shared_filtered = filtered_lines(out)
    check(len(shared_filtered) == 1 and 'shared_comp.png' in shared_filtered[0],
          f'5: shared_comp.png, listed by both glTFs, filtered once by the deploy ({len(shared_filtered)})')
    check(sha1(pkg / 'texture' / 'shared_comp.png') == sha1(shared / 'shared_comp.png'),
          '5: the package shared_comp.png is the filtered one (the exporter\'s bytes)')
    check((pkg / 'texture' / 'plain_detail.png.xml').read_text(encoding='utf-8').count('QUALITYHIGH') == 1 and
          'kept    plain_detail.png.xml' in out, '5: the package XML with a fitting slot is kept')
    check((pkg / 'texture' / 'shared_comp.png.xml').is_file() and (pkg / 'texture' / 'other_comp.png.xml').is_file(),
          '5: the missing XMLs are written')
    uris = {Path(i['uri']).as_posix() for g in (pkg / 'model').glob('*.gltf')
            for i in json.loads(g.read_text(encoding='utf-8'))['images']}
    check(all(u.startswith('../texture/') for u in uris), f'5: URIs point at ../texture/ ({sorted(uris)})')
    unfilterable = syn / 'unfilterable'
    check(unfilterable.is_dir(), 'export folder synthetic/unfilterable exists')
    pkg = fresh_package('syn_pkg_unfilterable', base=syn_base)
    before = snapshot(pkg)
    code, out = stage(pkg, unfilterable, 'panel_*.gltf', 'syn_unfilterable', source=unfilterable / 'src')
    reason = [l for l in out.splitlines() if l.startswith('[texture-lib] ERROR')]
    print(f'INFO: a texture with levels the exporter could not filter: {reason}')
    check(code != 0 and snapshot(pkg) == before,
          f'4: a listed texture the filter cannot filter (grey, three different levels): exit {code}, package '
          'unchanged')
    print(f'INFO: the cockpit package base has {len(base)} files')
    print('ALL STAGING DEPLOY TESTS PASSED')

# endregion


if __name__ == '__main__':
    try:
        import bpy  # noqa: F401
        IN_BLENDER = True
    except ImportError:
        IN_BLENDER = False
    if IN_BLENDER:
        ARGV = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
        if ARGV and ARGV[0] == 'cockpit':
            blender_cockpit(dict(a.split('=', 1) for a in ARGV[1:]))
        elif ARGV and ARGV[0] == 'synthetic':
            blender_synthetic()
        else:
            raise SystemExit('use -- synthetic or -- cockpit name=<folder> [levels=1]')
    else:
        ARGV = sys.argv[1:]
        if ARGV == ['prepare']:
            prepare()
        elif ARGV == ['deploy']:
            deploy_tests()
        else:
            raise SystemExit(__doc__)
