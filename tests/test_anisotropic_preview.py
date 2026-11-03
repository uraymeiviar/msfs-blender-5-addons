"""Anisotropy preview of MSFS Anisotropic and Hair materials: preview nodes appear with the anisotropic texture and go
with it, the image reaches the node, the branches survive normal and alpha changes, today's output stays untouched,
engines use their own output (also after save and load), a material without the texture renders as before, the update
operator, and exports with the preview are identical to exports without it, for both simulators and the plain dialog.

To run:
G:\\e-jets-e2\\tools\\blender\\blender.exe -b --factory-startup --python tests/test_anisotropic_preview.py
"""

import hashlib
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

from io_scene_gltf2_msfs_fss import anisotropic_preview as ap  # noqa: E402
from io_scene_gltf2_msfs_fss.blender.material.msfs_material_properties_update import (  # noqa: E402
    MSFS2024_MaterialPropUpdate,
)

SCRATCH_DIR = REPO_ROOT / 'tests' / '_work' / 'anisotropic_preview_scratch'
ANISO = 'msfs_anisotropic_direction_roughness_y_texture'
PRINCIPLED = 'Principled BSDF Shader'


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


def new_material(name, material_type, with_aniso=True):
    material = bpy.data.materials.new(name)
    material.msfs_material_type = material_type
    material.msfs_base_color_texture = image('t_albd', (0.4, 0.4, 0.4, 1), 'sRGB')
    material.msfs_occlusion_metallic_roughness_texture = image('t_comp', (1, 0.3, 0, 1), 'Non-Color')
    material.msfs_normal_texture = image('t_norm', (0.5, 0.5, 1, 1), 'Non-Color')
    if with_aniso:
        setattr(material, ANISO, image(f't_aniso_{name}', (0.8, 0.6, 0.7, 1), 'Non-Color'))
    return material


def preview_nodes(material):
    return [n for n in material.node_tree.nodes if n.name.startswith(ap.NODE_PREFIX)]


def outputs(material):
    return {n.target: n for n in material.node_tree.nodes if n.type == 'OUTPUT_MATERIAL'}


def tree_signature(material):
    """Today's part of the tree: everything but the preview nodes and their links, with the Anisotropic Tex image."""
    tree = material.node_tree
    links = sorted(
        (l.from_node.name, l.from_socket.identifier, l.to_node.name, l.to_socket.identifier)
        for l in tree.links
        if not l.from_node.name.startswith(ap.NODE_PREFIX) and not l.to_node.name.startswith(ap.NODE_PREFIX)
    )
    return sorted(n.name for n in tree.nodes if not n.name.startswith(ap.NODE_PREFIX)), links


def is_linked_from(socket, node_name):
    return socket.is_linked and socket.links[0].from_node.name == node_name


def test_material(material_type):
    print('---', material_type)
    with_tex = new_material(f'with_{material_type}', material_type)
    without = new_material(f'without_{material_type}', material_type, with_aniso=False)
    nodes = with_tex.node_tree.nodes

    check(preview_nodes(with_tex), 'preview nodes appear with the texture')
    check(not preview_nodes(without), 'no preview nodes without the texture')
    check(nodes['Anisotropic Tex'].image == getattr(with_tex, ANISO), 'the image reaches the node')
    check(nodes['Anisotropic Tex'].inputs[0].is_linked, 'the texture follows the UV group')
    check(set(outputs(with_tex)) == {'ALL', 'CYCLES', 'EEVEE'}, 'one output per target')
    check(outputs(with_tex)['ALL'].is_active_output, "today's output stays the active one")
    check(not any(n.name == 'Shader Output Material' for n in nodes), 'no output named as an MSFS 2020 tree')

    signature = tree_signature(without)
    setattr(without, ANISO, image('t_aniso_late', (0.8, 0.6, 0.7, 1), 'Non-Color'))
    check(preview_nodes(without), 'a texture added later brings the preview nodes')
    check(tree_signature(without)[0] == signature[0], "adding the texture keeps today's nodes")
    today = {l for l in tree_signature(without)[1] if not l[2].startswith('Anisotropic')}
    check(today == {l for l in signature[1] if not l[2].startswith('Anisotropic')}, "adding the texture keeps today's links")
    principled = without.node_tree.nodes[PRINCIPLED]
    check(is_linked_from(principled.inputs['Roughness'], '.Occlusion Metallic Roughness Group'), 'Principled keeps its roughness')
    check(outputs(without)['ALL'].inputs[0].links[0].from_node == principled, "today's output keeps its Principled")
    setattr(without, ANISO, None)
    check(not preview_nodes(without), 'clearing the texture removes the preview nodes')
    check(without.node_tree.nodes['Anisotropic Tex'].image is None, 'clearing the texture clears the node')
    check(set(outputs(without)) == {'ALL'}, 'only the ALL output after clearing')

    group = nodes[ap.NODE_PREFIX + 'EEVEE']
    bsdf = nodes[ap.NODE_PREFIX + 'Cycles BSDF']
    with_tex.msfs_normal_scale = 0.5
    check(is_linked_from(group.inputs['Normal'], '.Normal Group'), 'EEVEE keeps the normal after a normal scale change')
    check(is_linked_from(bsdf.inputs['Normal'], '.Normal Group'), 'Cycles keeps the normal after a normal scale change')
    with_tex.msfs_normal_texture = None
    check(is_linked_from(group.inputs['Normal'], ap.NODE_PREFIX + 'Geometry'), 'without a normal map: geometry normal')
    with_tex.msfs_normal_texture = image('t_norm', (0.5, 0.5, 1, 1), 'Non-Color')
    check(is_linked_from(group.inputs['Normal'], '.Normal Group'), 'a normal map comes back')

    eevee = outputs(with_tex)['EEVEE']
    for mode, linked in (('OPAQUE', False), ('MASK', True), ('BLEND', True), ('DITHER', True), ('OPAQUE', False)):
        with_tex.msfs_alpha_mode = mode
        check(bsdf.inputs['Alpha'].is_linked == linked, f'{mode}: Cycles alpha linked {linked}')
        check(eevee.inputs[0].links[0].from_node.name == ap.NODE_PREFIX + ('Alpha' if linked else 'Surface'), f'{mode}: EEVEE surface')

    with_tex.msfs_material_type = 'msfs_standard'
    check(not preview_nodes(with_tex), 'another material type has no preview nodes')
    with_tex.msfs_material_type = material_type
    if getattr(with_tex, ANISO) is None:
        setattr(with_tex, ANISO, image('t_aniso_back', (0.8, 0.6, 0.7, 1), 'Non-Color'))
    check(preview_nodes(with_tex), 'back to the type: preview nodes again')


def test_standard_ignores_image():
    material = bpy.data.materials.new('standard_with_aniso')
    material.msfs_material_type = 'msfs_standard'
    setattr(material, ANISO, image('t_aniso_std', (0.8, 0.6, 0.7, 1), 'Non-Color'))
    check(not preview_nodes(material), 'a standard material ignores the anisotropic image')


def test_colorspace():
    material = new_material('colorspace', 'msfs_anisotropic', with_aniso=False)
    srgb = image('t_aniso_srgb', (0.8, 0.6, 0.7, 1), 'sRGB')
    material.msfs_base_color_texture = srgb  # the same image in another slot, which needs sRGB
    setattr(material, ANISO, srgb)
    node_image = material.node_tree.nodes['Anisotropic Tex'].image
    check(getattr(material, ANISO) == srgb, "the artist's image stays in the property")
    check(srgb.colorspace_settings.name == 'sRGB', "the artist's image keeps its colour space")
    check(node_image != srgb and node_image.colorspace_settings.name == 'Non-Color', 'the node reads the image as Non-Color')
    images_before = len(bpy.data.images)
    setattr(material, ANISO, srgb)
    check(len(bpy.data.images) == images_before, 'setting it again makes no further copy')


def test_operator():
    material = new_material('old_file', 'msfs_anisotropic', with_aniso=False)
    setattr(material, ANISO, image('t_aniso_old', (0.8, 0.6, 0.7, 1), 'Non-Color'))
    # A material saved before this feature: the image is set, the node has none and there is no preview
    ap._remove_preview_nodes(MSFS2024_MaterialPropUpdate.get_material(material))
    material.node_tree.nodes['Anisotropic Tex'].image = None
    check(not preview_nodes(material), 'an old material has no preview nodes')
    result = bpy.ops.msfs_fss.update_material_nodes()
    check(result == {'FINISHED'}, 'the operator finishes')
    check(preview_nodes(material), 'the operator adds the preview nodes')
    count = len(preview_nodes(material))
    bpy.ops.msfs_fss.update_material_nodes()
    check(len(preview_nodes(material)) == count, 'running it again changes nothing')


def render_center(scene, engine):
    scene.render.engine = engine
    scene.render.resolution_x = scene.render.resolution_y = 16
    scene.view_settings.view_transform = 'Standard'
    scene.render.image_settings.file_format = 'PNG'
    if engine == 'CYCLES':
        scene.cycles.samples = 1
        scene.cycles.device = 'CPU'
    else:
        scene.eevee.taa_render_samples = 1
    path = SCRATCH_DIR / f'target_{engine}.png'
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    loaded = bpy.data.images.load(str(path), check_existing=False)
    start = (8 * 16 + 8) * 4
    pixel = [round(v, 2) for v in loaded.pixels[start:start + 3]]
    bpy.data.images.remove(loaded)
    return pixel


def test_engines_use_their_output():
    """Emission colours tell the outputs apart, on the real tree and after save and load."""
    bpy.ops.wm.read_homefile(use_empty=True)
    bpy.ops.mesh.primitive_plane_add(size=4)
    plane = bpy.context.active_object
    material = new_material('engines', 'msfs_anisotropic')
    plane.data.materials.append(material)
    scene = bpy.context.scene
    camera = bpy.data.objects.new('camera', bpy.data.cameras.new('camera'))
    scene.collection.objects.link(camera)
    camera.location = (0, 0, 5)
    scene.camera = camera
    blend = SCRATCH_DIR / 'engines.blend'

    def verify(when):
        tree = bpy.data.materials['engines'].node_tree
        for target, color in (('ALL', (1, 0, 0, 1)), ('CYCLES', (0, 1, 0, 1)), ('EEVEE', (0, 0, 1, 1))):
            emission = tree.nodes.new('ShaderNodeEmission')
            emission.inputs[0].default_value = color
            tree.links.new(emission.outputs[0], outputs(bpy.data.materials['engines'])[target].inputs[0])
        check(render_center(bpy.context.scene, 'BLENDER_EEVEE') == [0.0, 0.0, 1.0], f'EEVEE uses its output ({when})')
        check(render_center(bpy.context.scene, 'CYCLES') == [0.0, 1.0, 0.0], f'Cycles uses its output ({when})')

    # A material saved before this feature: the add-on rebuilds every tree when a file opens, which adds the preview
    ap._remove_preview_nodes(MSFS2024_MaterialPropUpdate.get_material(material))
    material.node_tree.nodes['Anisotropic Tex'].image = None
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    reopened = bpy.data.materials['engines']
    check(preview_nodes(reopened), 'opening a file adds the preview to a material saved without it')
    check(reopened.node_tree.nodes['Anisotropic Tex'].image == getattr(reopened, ANISO), 'opening a file sets the image on the node')
    verify('after opening the file')
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    check(len(outputs(bpy.data.materials['engines'])) == 3, 'saving and opening again does not add outputs')
    verify('after saving with the preview and opening again')


def render_rgba(scene, engine):
    scene.render.engine = engine
    scene.render.resolution_x = scene.render.resolution_y = 16
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.film_transparent = True
    scene.view_settings.view_transform = 'Standard'
    if engine == 'CYCLES':
        scene.cycles.samples = 32
        scene.cycles.device = 'CPU'
        scene.cycles.use_denoising = False
    else:
        scene.eevee.taa_render_samples = 16
    path = SCRATCH_DIR / f'features_{engine}.png'
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    loaded = bpy.data.images.load(str(path), check_existing=False)
    start = (8 * 16 + 8) * 4
    pixel = list(loaded.pixels[start:start + 4])
    bpy.data.images.remove(loaded)
    return pixel


def test_render_features(material_type):
    """Metal, emission and alpha on the preview branches, in both engines (the seat belt uses none of them)."""
    print('---', 'render features', material_type)
    bpy.ops.wm.read_homefile(use_empty=True)
    scene = bpy.context.scene
    world = bpy.data.worlds.new('world')
    world.use_nodes = True
    world.node_tree.nodes['Background'].inputs[1].default_value = 1.0
    world.node_tree.nodes['Background'].inputs[0].default_value = (1, 1, 1, 1)
    scene.world = world
    bpy.ops.mesh.primitive_plane_add(size=4)
    plane = bpy.context.active_object
    camera = bpy.data.objects.new('camera', bpy.data.cameras.new('camera'))
    scene.collection.objects.link(camera)
    camera.location = (0, 0, 5)
    scene.camera = camera

    def setup(name, color, comp, **props):
        material = bpy.data.materials.new(name)
        material.msfs_material_type = material_type
        material.msfs_base_color_factor = color
        material.msfs_occlusion_metallic_roughness_texture = image(f't_comp_{name}', comp, 'Non-Color')
        setattr(material, ANISO, image('t_aniso_features', (0.5, 0.5, 0.3, 1), 'Non-Color'))
        for key, value in props.items():
            setattr(material, key, value)
        plane.data.materials.clear()
        plane.data.materials.append(material)
        return render_rgba(scene, 'BLENDER_EEVEE'), render_rgba(scene, 'CYCLES')

    def close(a, b, tolerance=0.08):
        return all(abs(x - y) <= tolerance for x, y in zip(a[:3], b[:3]))

    eevee, cycles = setup('dielectric', (0.8, 0.1, 0.1, 1), (1, 0.5, 0, 1))
    check(eevee[0] > 0.5 and eevee[1] < 0.5, f'dielectric: EEVEE shows the base colour {eevee[:3]}')
    check(close(eevee, cycles), f'dielectric: EEVEE {eevee[:3]} close to Cycles {cycles[:3]}')

    eevee, cycles = setup('metal', (0.8, 0.1, 0.1, 1), (1, 0.5, 1, 1))
    check(eevee[0] > 0.4 and eevee[1] < 0.35, f'metal: EEVEE has a coloured specular {eevee[:3]}')
    check(close(eevee, cycles, 0.15), f'metal: EEVEE {eevee[:3]} close to Cycles {cycles[:3]}')

    eevee, cycles = setup('black', (0, 0, 0, 1), (1, 0.5, 0, 1), msfs_emissive_factor=(0, 1, 0), msfs_emissive_scale=2000.0)
    check(eevee[1] > eevee[0] + 0.3, f'emission: EEVEE {eevee[:3]}')
    check(cycles[1] > cycles[0] + 0.3, f'emission: Cycles {cycles[:3]}')

    eevee, cycles = setup('masked', (0.8, 0.1, 0.1, 0), (1, 0.5, 0, 1), msfs_alpha_mode='MASK', msfs_alpha_cutoff=0.5)
    check(eevee[3] < 0.05, f'alpha mask: EEVEE transparent, alpha {eevee[3]:.2f}')
    check(cycles[3] < 0.05, f'alpha mask: Cycles transparent, alpha {cycles[3]:.2f}')
    eevee, cycles = setup('kept', (0.8, 0.1, 0.1, 1), (1, 0.5, 0, 1), msfs_alpha_mode='MASK', msfs_alpha_cutoff=0.5)
    check(eevee[3] > 0.95, f'alpha mask above the cutoff: EEVEE opaque, alpha {eevee[3]:.2f}')
    check(cycles[3] > 0.95, f'alpha mask above the cutoff: Cycles opaque, alpha {cycles[3]:.2f}')


def export_scene(mode, preview, out_dir):
    """One Anisotropic and one Hair material on a grid; returns the glTF's material sections and all file hashes."""
    bpy.ops.wm.read_homefile(use_empty=True)
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=4, y_subdivisions=4, size=1)
    obj = bpy.context.active_object
    obj.name = 'BELT'
    for name, material_type in (('Belt', 'msfs_anisotropic'), ('Fur', 'msfs_hair'), ('Shared', 'msfs_anisotropic')):
        material = new_material(name, material_type, with_aniso=name != 'Shared')
        if name == 'Shared':
            # An image that is also the base colour of the same material: stays one image in the glTF
            setattr(material, ANISO, material.msfs_base_color_texture)
        if not preview:
            ap._remove_preview_nodes(MSFS2024_MaterialPropUpdate.get_material(material))
        obj.data.materials.append(material)
    scene = bpy.context.scene
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)
    if mode == 'fs24':
        from io_scene_gltf2_msfs_fss.io.exp import export_settings
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
        collection.objects.link(obj)
        scene.collection.children.link(collection)
        presets = scene.msfs_multi_exporter_presets
        for existing in presets:
            existing.enabled = False
        preset = presets.add()
        preset.preset_name = 'belt'
        preset.folder_path = str(out_dir)
        preset.enabled = True
        layer = preset.layers.add()
        layer.collection = collection
        layer.enabled = True
        bpy.ops.msfs2024.multi_export_gltf(export_mode='PRESETS')
    else:
        scene.msfs_fss_export_target = 'MSFS2020' if mode == 'fs20' else 'MSFS2024'
        bpy.ops.export_scene.gltf(filepath=str(out_dir / 'belt.gltf'), export_format='GLTF_SEPARATE', use_visible=True,
                                  export_image_format='AUTO')
    files = {p.name: hashlib.md5(p.read_bytes()).hexdigest() for p in out_dir.iterdir() if p.suffix != '.gltf'}
    gltf = json.loads((out_dir / 'belt.gltf').read_text(encoding='utf8'))
    sections = {k: gltf.get(k) for k in ('materials', 'textures', 'images', 'samplers', 'extensionsUsed', 'extensionsRequired', 'meshes')}
    return sections, files


def test_exports():
    for mode, label in (('fs24', 'MSFS 2024 multi-exporter'), ('fs20', 'MSFS 2020'), ('plain', 'File > Export, target 2024')):
        without, without_files = export_scene(mode, False, SCRATCH_DIR / f'{mode}_without')
        with_preview, with_files = export_scene(mode, True, SCRATCH_DIR / f'{mode}_with')
        check(with_preview == without, f'{label}: same glTF with and without the preview')
        check(with_files == without_files, f'{label}: same files with and without the preview')
        if mode == 'plain':
            check(without['materials'][0].get('normalTexture') is not None, 'plain export: the normal texture is there')
            check('KHR_materials_anisotropy' not in (without.get('extensionsUsed') or []), 'plain export: no KHR anisotropy')
        if mode == 'fs24':
            check(all('ASOBO_material_anisotropic_v2' in m['extensions'] for m in with_preview['materials']), 'MSFS 2024: the anisotropic extension is written')


shutil.rmtree(SCRATCH_DIR, ignore_errors=True)
SCRATCH_DIR.mkdir(parents=True)
test_material('msfs_anisotropic')
test_material('msfs_hair')
test_standard_ignores_image()
test_colorspace()
test_operator()
test_engines_use_their_output()
test_render_features('msfs_anisotropic')
test_render_features('msfs_hair')
test_exports()
print('ALL ANISOTROPIC PREVIEW TESTS PASSED')
