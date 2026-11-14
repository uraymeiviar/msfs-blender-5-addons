"""Clearcoat and Occlusion Strength preview of MSFS 2024 materials: the coat branch and its outputs, every clearcoat
parameter reaching its node, Use Uniform Roughness, the coat normal with and without the base normal, alpha and normal
changes, today's Principled kept as Asobo builds it, the artist's images unchanged, the Occlusion Strength node (not on
Windshield), the AO always applied in the shared Apply AO group, a file saved without the preview, the update operator,
the coat and its tint rendered in EEVEE and Cycles, the occlusion darkening a sky-lit plane in both engines, the detail
normal lighting a sun-lit plane as the same texture does as the base normal (Asobo's group showed about 0.6 of it), and
exports identical to the tree the add-on built before these previews, for both simulators and the plain dialog (a
material with base and detail normal, one with a detail normal only).

To run:
G:\\e-jets-e2\\tools\\blender\\blender.exe -b --factory-startup --python tests/test_material_preview.py
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

from io_scene_gltf2_msfs_fss import material_preview as mp  # noqa: E402

SCRATCH_DIR = REPO_ROOT / 'tests' / '_work' / 'material_preview_scratch'
PRINCIPLED = 'Principled BSDF Shader'
P = mp.COAT_PREFIX


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print('PASS:', message)


def image(name, pixel, colorspace):
    path = SCRATCH_DIR / 'tex' / f'{name}.png'
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        im = bpy.data.images.new(name, 8, 8, alpha=True)
        im.pixels = list(pixel) * 64
        im.filepath_raw = str(path)
        im.file_format = 'PNG'
        im.save()
        bpy.data.images.remove(im)
    im = bpy.data.images.load(str(path), check_existing=True)
    im.colorspace_settings.name = colorspace
    return im


def new_material(name, material_type='msfs_clearcoat', coat=True, coat_normal=True, comp=(1, 0.3, 0, 1)):
    material = bpy.data.materials.new(name)
    material.msfs_material_type = material_type
    material.msfs_base_color_texture = image('t_albd', (0.4, 0.4, 0.4, 1), 'sRGB')
    material.msfs_occlusion_metallic_roughness_texture = image(f't_comp_{comp}', comp, 'Non-Color')
    material.msfs_normal_texture = image('t_norm', (0.5, 0.5, 1, 1), 'Non-Color')
    if coat:
        material.msfs_clearcoat_color_roughness_texture = image('t_coat', (1, 1, 1, 0.2), 'sRGB')
    if coat_normal:
        material.msfs_clearcoat_normal_texture = image('t_coat_norm', (0.5, 0.5, 1, 1), 'Non-Color')
    return material


def coat_nodes(material):
    return [n for n in material.node_tree.nodes if n.name.startswith(P)]


def outputs(material):
    return {n.target: n for n in material.node_tree.nodes if n.type == 'OUTPUT_MATERIAL'}


def source(socket):
    return socket.links[0].from_node.name if socket.is_linked else None


def test_clearcoat_tree():
    print('--- clearcoat tree')
    material = new_material('coat')
    nodes = material.node_tree.nodes
    principled = nodes[PRINCIPLED]
    bsdf = nodes[P + 'BSDF']

    check(set(outputs(material)) == {'ALL', 'EEVEE', 'CYCLES'}, 'one output per target')
    check(outputs(material)['ALL'].is_active_output, "today's output stays the active one")
    check(source(outputs(material)['ALL'].inputs[0]) == PRINCIPLED, "today's output keeps its Principled")
    for target in ('EEVEE', 'CYCLES'):
        check(source(outputs(material)[target].inputs[0]) == P + 'BSDF', f'the {target} output shows the coat branch')
    check(source(principled.inputs['Coat Tint']) == 'Clearcoat Separate', "today's Principled keeps Asobo's coat links")
    check(principled.inputs['Coat Weight'].default_value == 0.0, "today's Principled keeps Coat Weight 0")

    check(bsdf.inputs['Coat Weight'].default_value == 1.0, 'the coat covers the material')
    check(source(bsdf.inputs['Coat Tint']) == P + 'Color Roughness', 'coat tint from the clearcoat texture RGB')
    check(bsdf.inputs['Coat Tint'].links[0].from_socket.name == 'Color', 'coat tint is the Color output')
    roughness = nodes[P + 'Roughness']
    check(source(bsdf.inputs['Coat Roughness']) == P + 'Roughness', 'coat roughness through the factor')
    check(roughness.inputs[0].links[0].from_socket.name == 'Alpha', 'coat roughness from the clearcoat texture A')
    for name in ('Base Color', 'Metallic', 'Roughness', 'Normal', 'Emission Color', 'Emission Strength'):
        check(source(bsdf.inputs[name]) == source(principled.inputs[name]), f'the coat branch mirrors {name}')

    material.msfs_clearcoat_roughness_factor = 0.25
    check(abs(nodes[P + 'Roughness'].inputs[1].default_value - 0.25) < 1e-6, 'Clearcoat Roughness Factor reaches its node')
    material.msfs_clearcoat_color_roughness_tiling = 4.0
    check(nodes[P + 'Color Roughness UV'].inputs['Scale'].default_value == 4.0, 'Color/Roughness Tiling reaches its node')
    check(source(nodes[P + 'Color Roughness UV'].inputs[0]) == '.UV Group', "the tiling scales the material's UV")
    material.msfs_clearcoat_normal_tiling = 3.0
    check(nodes[P + 'Normal UV'].inputs['Scale'].default_value == 3.0, 'Normal Tiling reaches its node')
    material.msfs_clearcoat_normal_factor = 0.4
    check(abs(nodes[P + 'Normal Map'].inputs['Strength'].default_value - 0.4) < 1e-6, 'Normal Factor reaches the Normal Map strength')

    bsdf = nodes[P + 'BSDF']
    check(source(bsdf.inputs['Coat Normal']) == P + 'Normal', 'Base Normal Affect Coat: both normals combined')
    material.msfs_base_normal_affect_coat = False
    check(source(nodes[P + 'BSDF'].inputs['Coat Normal']) == P + 'Normal Map', 'without Base Normal Affect Coat: the coat normal alone')
    material.msfs_clearcoat_normal_texture = None
    check(not nodes[P + 'BSDF'].inputs['Coat Normal'].is_linked, 'no coat normal and no base normal: the surface normal')
    material.msfs_base_normal_affect_coat = True
    check(source(nodes[P + 'BSDF'].inputs['Coat Normal']) == '.Normal Group', 'no coat normal: the base normal')
    material.msfs_normal_texture = None
    check(not nodes[P + 'BSDF'].inputs['Coat Normal'].is_linked and not nodes[P + 'BSDF'].inputs['Normal'].is_linked,
          'without a normal map: the coat branch follows')
    material.msfs_normal_texture = image('t_norm', (0.5, 0.5, 1, 1), 'Non-Color')
    check(source(nodes[P + 'BSDF'].inputs['Normal']) == '.Normal Group', 'a normal map comes back on the coat branch')

    material.msfs_clearcoat_inverse_roughness = True
    material.msfs_clearcoat_base_roughness = 0.7
    bsdf = nodes[P + 'BSDF']
    check(not bsdf.inputs['Roughness'].is_linked and abs(bsdf.inputs['Roughness'].default_value - 0.7) < 1e-6,
          'Use Uniform Roughness: the base layer gets Base Roughness')
    check(source(nodes[P + 'Roughness'].inputs[0]) == P + 'OMR Separate', 'Use Uniform Roughness: coat roughness from the OMR texture')
    check(nodes[P + 'Roughness'].inputs[0].links[0].from_socket.name == 'Green', '... its green channel')
    check(nodes.get(P + 'Color Roughness') is None and not bsdf.inputs['Coat Tint'].is_linked, 'Use Uniform Roughness: no clearcoat texture')
    material.msfs_clearcoat_inverse_roughness = False
    check(source(nodes[P + 'BSDF'].inputs['Roughness']) == source(principled.inputs['Roughness']), 'off again: base roughness from the tree')

    for mode, linked in (('OPAQUE', False), ('MASK', True), ('BLEND', True), ('DITHER', True), ('OPAQUE', False)):
        material.msfs_alpha_mode = mode
        check(nodes[P + 'BSDF'].inputs['Alpha'].is_linked == linked, f'{mode}: coat branch alpha linked {linked}')

    material.msfs_clearcoat_color_roughness_texture = None
    check(not nodes[P + 'BSDF'].inputs['Coat Tint'].is_linked, 'no clearcoat texture: a clear coat')
    check(not nodes[P + 'Roughness'].inputs[0].is_linked, 'no clearcoat texture: the roughness factor alone')

    material.msfs_material_type = 'msfs_standard'
    check(not coat_nodes(material) and set(outputs(material)) == {'ALL'}, 'another material type has no coat branch')


def test_images():
    print('--- images')
    material = new_material('images', coat=False, coat_normal=False)
    srgb = image('t_coat_shared', (0.9, 0.2, 0.2, 0.5), 'sRGB')
    material.msfs_clearcoat_color_roughness_texture = srgb
    artist = material.msfs_clearcoat_color_roughness_texture
    node_image = material.node_tree.nodes[P + 'Color Roughness'].image
    check(node_image is not artist, 'the coat node reads a copy')
    check(node_image.colorspace_settings.name == 'sRGB' and node_image.alpha_mode == 'CHANNEL_PACKED',
          'the copy is read as colour with its alpha as data')
    check(artist.colorspace_settings.name == 'Non-Color', "the artist's image keeps Asobo's slot setting")
    count = len(bpy.data.images)
    material.msfs_clearcoat_roughness_factor = 0.5
    check(len(bpy.data.images) == count, 'a rebuild makes no further copy')


def test_occlusion_strength():
    print('--- occlusion strength')
    for material_type in ('msfs_standard', 'msfs_clearcoat'):
        material = new_material(f'ao_{material_type}', material_type, coat=False, coat_normal=False)
        nodes = material.node_tree.nodes
        node = nodes.get(mp.OCCLUSION_NODE)
        check(node is not None, f'{material_type}: the Occlusion Strength node is there')
        check(source(nodes['.Apply AO Group'].inputs[1]) == mp.OCCLUSION_NODE, f'{material_type}: it feeds Apply AO')
        check(source(node.inputs[0]) == '.Occlusion Metallic Roughness Group', f'{material_type}: from the occlusion')
        material.msfs_occlusion_strength = 0.25
        node = nodes[mp.OCCLUSION_NODE]
        check(abs(node.inputs[1].default_value - 0.25) < 1e-6 and abs(node.inputs[2].default_value - 0.75) < 1e-6,
              f'{material_type}: occlusion = 1 + 0.25 * (texture - 1)')
        material.msfs_occlusion_metallic_roughness_texture = None
        check(nodes.get(mp.OCCLUSION_NODE) is None and not nodes['.Apply AO Group'].inputs[1].is_linked,
              f'{material_type}: no OMR texture, no node')
        material.msfs_occlusion_metallic_roughness_texture = image('t_comp_back', (1, 0.3, 0, 1), 'Non-Color')
        check(nodes.get(mp.OCCLUSION_NODE) is not None, f'{material_type}: the node comes back with the texture')
        material.msfs_occlusion_strength = 1.0
        check(len([n for n in nodes if n.name.startswith(mp.OCCLUSION_NODE)]) == 1, f'{material_type}: one node only')
    windshield = new_material('ao_windshield', 'msfs_windshield', coat=False, coat_normal=False)
    check(windshield.node_tree.nodes.get(mp.OCCLUSION_NODE) is None, 'Windshield: no Occlusion Strength node')
    check_ao_always('the shared Apply AO group')


def ao_mix(group):
    output = next(n for n in group.nodes if n.bl_idname == 'NodeGroupOutput')
    return output.inputs[0].links[0].from_node


def check_ao_always(label):
    group = bpy.data.node_groups['.Apply AO Group']
    node = group.nodes.get(mp.AO_ALWAYS_NODE)
    check(node is not None and node.outputs[0].default_value == 1.0, f'{label}: the AO Always node is there, value 1')
    check(source(ao_mix(group).inputs[0]) == mp.AO_ALWAYS_NODE, f'{label}: it feeds the mix factor (not the light mask)')
    check(len([n for n in group.nodes if n.name.startswith(mp.AO_ALWAYS_NODE)]) == 1, f'{label}: one node only')
    group = bpy.data.node_groups['.Occlusion Metallic Roughness Group']
    output = next(n for n in group.nodes if n.bl_idname == 'NodeGroupOutput')
    mix = group.nodes.get(mp.OMR_OCCLUSION_NODE)
    check(mix is not None and source(output.inputs[2]) == mp.OMR_OCCLUSION_NODE, f"{label}: the ORM group's Occlusion output from the FSS mix")
    a = mix.inputs[2].links[0]
    check(a.from_socket.name == 'Red' and a.from_node.inputs[0].links[0].from_socket.name == 'Occlusion (R), Roughness (G), Metallic (B)',
          f"{label}: without a detail texture or blend mode the occlusion is the texture's red")
    check(source(mix.inputs['Factor']) == mp.OMR_EITHER_NODE and mix.inputs[3].is_linked, f"{label}: Asobo's result otherwise")


def strip_ao_always():
    """The groups as Asobo builds them: the ORM group's red at 1 without a detail texture, the light mask feeding the
    Apply AO mix factor."""
    omr = bpy.data.node_groups.get('.Occlusion Metallic Roughness Group')
    if omr is not None and omr.nodes.get(mp.OMR_OCCLUSION_NODE) is not None:
        mix = omr.nodes[mp.OMR_OCCLUSION_NODE]
        output = next(n for n in omr.nodes if n.bl_idname == 'NodeGroupOutput')
        omr.links.new(mix.inputs[3].links[0].from_socket, output.inputs[2])
        omr.nodes.remove(mix)
        omr.nodes.remove(omr.nodes[mp.OMR_EITHER_NODE])
    group = bpy.data.node_groups.get('.Apply AO Group')
    if group is None or group.nodes.get(mp.AO_ALWAYS_NODE) is None:
        return
    ramp = next(n for n in group.nodes if n.bl_idname == 'ShaderNodeValToRGB')
    group.links.new(ramp.outputs[0], ao_mix(group).inputs[0])
    group.nodes.remove(group.nodes[mp.AO_ALWAYS_NODE])


def check_detail_normal(label):
    group = bpy.data.node_groups['.Normal Group']
    output = next(n for n in group.nodes if n.bl_idname == 'NodeGroupOutput')
    mix = group.nodes.get(mp.DETAIL_NORMAL_MIX)
    check(mix is not None and source(output.inputs[0]) == mp.DETAIL_NORMAL_MIX,
          f"{label}: the Normal group's output from the FSS detail normal mix")
    check(mix.inputs[4].is_linked and mix.inputs[4].links[0].from_node.name == '.Switch.001',
          f"{label}: Asobo's result on the mix's first input")
    check(len([n for n in group.nodes if n.name == mp.DETAIL_NORMAL_MIX]) == 1, f'{label}: one detail normal mix only')


def strip_detail_normal():
    """Asobo's Normal group: its own result on the output, no FSS nodes."""
    group = bpy.data.node_groups.get('.Normal Group')
    if group is None or group.nodes.get(mp.DETAIL_NORMAL_MIX) is None:
        return
    output = next(n for n in group.nodes if n.bl_idname == 'NodeGroupOutput')
    group.links.new(group.nodes[mp.DETAIL_NORMAL_MIX].inputs[4].links[0].from_socket, output.inputs[0])
    for node in [n for n in group.nodes if n.name.startswith(mp.DETAIL_NORMAL_PREFIX)]:
        group.nodes.remove(node)


def strip_previews(material):
    """The tree as the add-on built it before these previews."""
    nodes, links = material.node_tree.nodes, material.node_tree.links
    for node in [n for n in nodes if n.name.startswith(P)]:
        nodes.remove(node)
    strip_ao_always()
    strip_detail_normal()
    node = nodes.get(mp.OCCLUSION_NODE)
    if node is not None:
        if node.inputs[0].is_linked:
            links.new(node.inputs[0].links[0].from_socket, nodes['.Apply AO Group'].inputs[1])
        nodes.remove(node)
    if material.msfs_material_type == 'msfs_clearcoat':
        principled = nodes[PRINCIPLED]
        if material.msfs_clearcoat_color_roughness_texture is not None:
            separate = nodes['Clearcoat Separate']
            links.new(separate.outputs[0], principled.inputs['Coat Tint'])
            links.new(separate.outputs[1], principled.inputs['Coat Roughness'])
        if material.msfs_clearcoat_normal_texture is not None:
            links.new(nodes['Clearcoat Normal'].outputs[0], principled.inputs['Coat Normal'])


def test_saved_without_preview():
    print('--- file saved without the preview')
    bpy.ops.wm.read_homefile(use_empty=True)
    bpy.ops.mesh.primitive_plane_add(size=4)
    material = new_material('old')
    bpy.context.active_object.data.materials.append(material)
    strip_previews(material)
    check(not coat_nodes(material), 'stripped: no coat branch')
    blend = SCRATCH_DIR / 'old.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    reopened = bpy.data.materials['old']
    check(coat_nodes(reopened), 'opening the file adds the coat branch')
    check(reopened.node_tree.nodes.get(mp.OCCLUSION_NODE) is not None, 'opening the file adds the Occlusion Strength node')
    check_ao_always('opening the file')
    check_detail_normal('opening the file')
    check(len(outputs(reopened)) == 3, 'three outputs')
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    check(len(outputs(bpy.data.materials['old'])) == 3, 'saving and opening again does not add outputs')

    strip_previews(bpy.data.materials['old'])
    result = bpy.ops.msfs_fss.update_material_nodes()
    check(result == {'FINISHED'}, 'the operator finishes')
    check(coat_nodes(bpy.data.materials['old']), 'the operator adds the coat branch')
    check_ao_always('the operator')
    check_detail_normal('the operator')
    count = len(bpy.data.materials['old'].node_tree.nodes)
    bpy.ops.msfs_fss.update_material_nodes()
    check(len(bpy.data.materials['old'].node_tree.nodes) == count, 'running it again changes nothing')


def render_rgb(scene, engine):
    scene.render.engine = engine
    scene.render.resolution_x = scene.render.resolution_y = 16
    scene.render.image_settings.file_format = 'PNG'
    scene.view_settings.view_transform = 'Standard'
    if engine == 'CYCLES':
        scene.cycles.samples = 64
        scene.cycles.device = 'CPU'
        scene.cycles.use_denoising = False
    else:
        scene.eevee.taa_render_samples = 16
    path = SCRATCH_DIR / f'render_{engine}.png'
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    loaded = bpy.data.images.load(str(path), check_existing=False)
    start = (8 * 16 + 8) * 4
    pixel = list(loaded.pixels[start:start + 3])
    bpy.data.images.remove(loaded)
    return pixel


def test_render():
    """The coat and its tint show in both engines: a plane under a white sky, seen at an angle."""
    print('--- render')
    bpy.ops.wm.read_homefile(use_empty=True)
    scene = bpy.context.scene
    world = bpy.data.worlds.new('world')
    world.use_nodes = True
    world.node_tree.nodes['Background'].inputs[0].default_value = (1, 1, 1, 1)
    scene.world = world
    bpy.ops.mesh.primitive_plane_add(size=40)
    plane = bpy.context.active_object
    camera = bpy.data.objects.new('camera', bpy.data.cameras.new('camera'))
    scene.collection.objects.link(camera)
    camera.location = (0, -6, 2)
    camera.rotation_euler = (1.25, 0, 0)
    scene.camera = camera

    def setup(name, material_type, base, coat_pixel=None, **props):
        material = bpy.data.materials.new(name)
        material.msfs_material_type = material_type
        material.msfs_base_color_factor = base
        material.msfs_occlusion_metallic_roughness_texture = image('t_comp_rough', (1, 1, 0, 1), 'Non-Color')
        if coat_pixel is not None:
            material.msfs_clearcoat_color_roughness_texture = image(f't_coat_{name}', coat_pixel, 'sRGB')
        for key, value in props.items():
            setattr(material, key, value)
        plane.data.materials.clear()
        plane.data.materials.append(material)
        return render_rgb(scene, 'BLENDER_EEVEE'), render_rgb(scene, 'CYCLES')

    plain = setup('plain', 'msfs_standard', (0.05, 0.05, 0.05, 1))
    coat = setup('coat', 'msfs_clearcoat', (0.05, 0.05, 0.05, 1), (1, 1, 1, 0), msfs_clearcoat_roughness_factor=1.0)
    for index, engine in enumerate(('EEVEE', 'Cycles')):
        check(coat[index][0] > plain[index][0] + 0.03, f'{engine}: a smooth coat reflects the sky ({plain[index][0]:.3f} -> {coat[index][0]:.3f})')
    white = setup('white', 'msfs_clearcoat', (0.8, 0.8, 0.8, 1), (1, 1, 1, 1))
    red = setup('red', 'msfs_clearcoat', (0.8, 0.8, 0.8, 1), (1, 0.1, 0.1, 1))
    for index, engine in enumerate(('EEVEE', 'Cycles')):
        check(red[index][1] < white[index][1] - 0.15 and red[index][0] > red[index][1] + 0.15,
              f'{engine}: a red tint colours the coat (white {[round(v, 2) for v in white[index]]}, red {[round(v, 2) for v in red[index]]})')


def linear(v):
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def test_render_ao():
    """The occlusion darkens a rough white plane under a white sky (all ambient light) in both engines; Asobo's groups
    (the red at 1, the light mask) showed none of it."""
    print('--- render AO')
    bpy.ops.wm.read_homefile(use_empty=True)
    scene = bpy.context.scene
    world = bpy.data.worlds.new('world')
    world.use_nodes = True
    world.node_tree.nodes['Background'].inputs[0].default_value = (1, 1, 1, 1)
    scene.world = world
    bpy.ops.mesh.primitive_plane_add(size=40)
    plane = bpy.context.active_object
    camera = bpy.data.objects.new('camera', bpy.data.cameras.new('camera'))
    scene.collection.objects.link(camera)
    camera.location = (0, -6, 2)
    camera.rotation_euler = (1.25, 0, 0)
    scene.camera = camera

    def setup(name, occlusion):
        material = bpy.data.materials.new(name)
        material.msfs_material_type = 'msfs_standard'
        material.msfs_base_color_factor = (0.8, 0.8, 0.8, 1)
        material.msfs_occlusion_metallic_roughness_texture = image(f't_comp_ao_{name}', (occlusion, 1, 0, 1), 'Non-Color')
        plane.data.materials.clear()
        plane.data.materials.append(material)
        return [linear(render_rgb(scene, engine)[0]) for engine in ('BLENDER_EEVEE', 'CYCLES')]

    lit = setup('lit', 1.0)
    dark = setup('dark', 0.25)
    for index, engine in enumerate(('EEVEE', 'Cycles')):
        ratio = dark[index] / lit[index]
        check(ratio < 0.4, f'{engine}: occlusion 0.25 darkens the sky-lit plane to {ratio:.3f} of occlusion 1 '
                           f'({lit[index]:.3f} -> {dark[index]:.3f} linear)')
    strip_ao_always()
    masked = [linear(render_rgb(scene, engine)[0]) for engine in ('BLENDER_EEVEE', 'CYCLES')]
    print("INFO: with Asobo's groups: occlusion 0.25 gives", [round(m / l, 3) for m, l in zip(masked, lit)],
          'of occlusion 1 (EEVEE, Cycles)')
    check(masked[0] / lit[0] > 0.9, f"EEVEE with Asobo's groups: no AO ({masked[0] / lit[0]:.3f})")


def test_render_detail_normal():
    """A sun at 45 degrees on a plane seen from above; a uniform normal texture tilted 30 degrees towards the sun.
    The detail normal (vertex alpha 1) lights the plane as the same texture does as the base normal, a flat detail
    normal leaves the base at full strength, vertex alpha 0 leaves the plane flat; Asobo's group showed about half."""
    print('--- render detail normal')
    bpy.ops.wm.read_homefile(use_empty=True)
    scene = bpy.context.scene
    world = bpy.data.worlds.new('world')
    world.use_nodes = True
    world.node_tree.nodes['Background'].inputs[0].default_value = (0, 0, 0, 1)
    scene.world = world
    bpy.ops.mesh.primitive_plane_add(size=40)
    plane = bpy.context.active_object
    attribute = plane.data.color_attributes.new('Col', 'FLOAT_COLOR', 'POINT')
    plane.data.color_attributes.active_color = attribute
    plane.data.attributes.render_color_index = plane.data.attributes.active_color_index
    sun = bpy.data.objects.new('sun', bpy.data.lights.new('sun', 'SUN'))
    sun.data.energy = 3.0
    sun.rotation_euler = (0, -0.785398, 0)  # light travelling towards +x and down: it comes from -x at 45 degrees
    scene.collection.objects.link(sun)
    camera = bpy.data.objects.new('camera', bpy.data.cameras.new('camera'))
    scene.collection.objects.link(camera)
    camera.location = (0, 0, 10)
    scene.camera = camera
    tilt = image('t_norm_tilt30', (0.25, 0.5, 0.933, 1), 'Non-Color')  # 30 degrees towards -x
    flat = image('t_norm_flat', (0.5, 0.5, 1, 1), 'Non-Color')

    def render(name, base=None, detail=None, alpha=1.0):
        for value in attribute.data:
            value.color = (1, 1, 1, alpha)
        material = bpy.data.materials.new(name)
        material.msfs_material_type = 'msfs_standard'
        material.msfs_base_color_factor = (0.8, 0.8, 0.8, 1)
        material.msfs_occlusion_metallic_roughness_texture = image('t_comp_rough', (1, 1, 0, 1), 'Non-Color')
        if base is not None:
            material.msfs_normal_texture = base
        if detail is not None:
            material.msfs_detail_normal_texture = detail
        plane.data.materials.clear()
        plane.data.materials.append(material)
        return [linear(render_rgb(scene, engine)[0]) for engine in ('BLENDER_EEVEE', 'CYCLES')]

    plain = render('dn_plain')
    base = render('dn_base', base=tilt)
    detail = render('dn_detail', detail=tilt)
    base_flat_detail = render('dn_base_flat_detail', base=tilt, detail=flat)
    masked = render('dn_detail_alpha0', detail=tilt, alpha=0.0)
    for index, engine in enumerate(('EEVEE', 'Cycles')):
        lift = base[index] - plain[index]
        check(lift > 0.05, f'{engine}: the tilted base normal lights the plane ({plain[index]:.3f} -> {base[index]:.3f})')
        share = (detail[index] - plain[index]) / lift
        check(abs(share - 1.0) < 0.05, f'{engine}: the detail normal at vertex alpha 1 gives {share:.3f} of the base normal')
        share = (base_flat_detail[index] - plain[index]) / lift
        check(abs(share - 1.0) < 0.05, f'{engine}: a flat detail normal keeps the base at {share:.3f}')
        check(abs(masked[index] - plain[index]) < 0.01, f'{engine}: vertex alpha 0 leaves the plane flat ({masked[index]:.3f})')
    strip_detail_normal()
    for value in attribute.data:
        value.color = (1, 1, 1, 1)
    plane.data.materials.clear()
    plane.data.materials.append(bpy.data.materials['dn_detail'])
    asobo = [linear(render_rgb(scene, engine)[0]) for engine in ('BLENDER_EEVEE', 'CYCLES')]
    plane.data.materials.clear()
    plane.data.materials.append(bpy.data.materials['dn_base_flat_detail'])
    asobo_base = [linear(render_rgb(scene, engine)[0]) for engine in ('BLENDER_EEVEE', 'CYCLES')]
    print("INFO: with Asobo's group: the detail normal gives",
          [round((a - p) / (b - p), 3) for a, p, b in zip(asobo, plain, base)],
          'and a flat detail keeps the base at', [round((a - p) / (b - p), 3) for a, p, b in zip(asobo_base, plain, base)],
          'of the base normal (EEVEE, Cycles)')


def export_scene(mode, previews, out_dir):
    """A Clearcoat and a Standard material on a grid; returns the glTF's material sections and all file hashes."""
    bpy.ops.wm.read_homefile(use_empty=True)
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=4, y_subdivisions=4, size=1)
    obj = bpy.context.active_object
    obj.name = 'PANEL'
    coat = new_material('Paint')
    coat.msfs_clearcoat_roughness_factor = 0.3
    coat.msfs_clearcoat_normal_tiling = 2.0
    coat.msfs_occlusion_strength = 0.5
    standard = new_material('Metal', 'msfs_standard', coat=False, coat_normal=False)
    standard.msfs_occlusion_strength = 0.5
    standard.msfs_normal_texture = None  # a detail normal without a base normal, as on the E2 seat leather
    standard.msfs_detail_normal_texture = image('t_detail_norm', (0.6, 0.45, 0.9, 1), 'Non-Color')
    standard.msfs_detail_normal_scale = 0.7
    coat.msfs_detail_normal_texture = image('t_detail_norm', (0.6, 0.45, 0.9, 1), 'Non-Color')  # base and detail
    for material in (coat, standard):
        if not previews:
            strip_previews(material)
        obj.data.materials.append(material)
    for polygon in obj.data.polygons:  # half the faces Metal, so both materials are exported
        polygon.material_index = polygon.index % 2
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
        preset.preset_name = 'panel'
        preset.folder_path = str(out_dir)
        preset.enabled = True
        layer = preset.layers.add()
        layer.collection = collection
        layer.enabled = True
        bpy.ops.msfs2024.multi_export_gltf(export_mode='PRESETS')
    else:
        scene.msfs_fss_export_target = 'MSFS2020' if mode == 'fs20' else 'MSFS2024'
        bpy.ops.export_scene.gltf(filepath=str(out_dir / 'panel.gltf'), export_format='GLTF_SEPARATE', use_visible=True,
                                  export_image_format='AUTO')
    files = {p.name: hashlib.md5(p.read_bytes()).hexdigest() for p in out_dir.iterdir() if p.suffix != '.gltf'}
    gltf = json.loads((out_dir / 'panel.gltf').read_text(encoding='utf8'))
    sections = {k: gltf.get(k) for k in ('materials', 'textures', 'images', 'samplers', 'extensionsUsed', 'extensionsRequired', 'meshes')}
    return sections, files


def test_exports():
    print('--- exports')
    for mode, label in (('fs24', 'MSFS 2024 multi-exporter'), ('fs20', 'MSFS 2020'), ('plain', 'File > Export, target 2024')):
        before, before_files = export_scene(mode, False, SCRATCH_DIR / f'{mode}_before')
        after, after_files = export_scene(mode, True, SCRATCH_DIR / f'{mode}_after')
        names = sorted(m['name'] for m in after['materials'])
        check(names == ['Metal', 'Paint'], f'{label}: both materials exported ({names})')
        images = sorted(i.get('uri', '') for i in after.get('images') or [])
        if mode == 'fs24':
            check(any('t_detail_norm' in u for u in images), f'{label}: the detail normal texture is exported ({images})')
        check(after == before, f'{label}: same glTF as the tree before these previews')
        check(after_files == before_files, f'{label}: same files as the tree before these previews')
        if mode != 'plain':  # File > Export writes Asobo's coat links as KHR_materials_clearcoat, as before
            check('KHR_materials_clearcoat' not in (after.get('extensionsUsed') or []), f'{label}: no KHR clearcoat')
        if mode == 'fs24':
            check(any('ASOBO_material_clear_coat_v2' in m.get('extensions', {}) for m in after['materials']),
                  'MSFS 2024: the clearcoat extension is written')


shutil.rmtree(SCRATCH_DIR, ignore_errors=True)
SCRATCH_DIR.mkdir(parents=True)
test_clearcoat_tree()
test_images()
test_occlusion_strength()
test_saved_without_preview()
test_render()
test_render_ao()
test_render_detail_normal()
test_exports()
print('ALL MATERIAL PREVIEW TESTS PASSED')
