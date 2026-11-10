"""Material animation export (ASOBO_property_animation), read back from the written glTF: accessor types, sampler
indices, timing and the value of every frame against the F-Curves in Blender. Bezier and Constant easing, uneven and
partly keyed colors, F-Curves in any order, Emissive Scale per channel and per material, keys past the scene range with
the option on and off, an action used by two materials and by two animations, and moved or scaled NLA strips.

Exports through the MSFS 2024 multi-exporter into tests/_work (git-ignored). The acceptance scene stays there as
material_animation_scratch/acceptance/MaterialAnimationTest_LOD0.gltf, the Glider test file.

To run:
G:\\e-jets-e2\\tools\\blender\\blender.exe -b --factory-startup --python tests/test_material_animation.py
"""

import base64
import json
import shutil
import struct
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

from io_scene_gltf2_msfs_fss.io.exp import export_settings, lod_groups  # noqa: E402

SCRATCH_DIR = REPO_ROOT / 'tests' / '_work' / 'material_animation_scratch'
BASE = 'msfs_base_color_factor'
EMISSIVE = 'msfs_emissive_factor'
TARGET_BASE = 'pbrMetallicRoughness/baseColorFactor'
TARGET_EMISSIVE = 'emissiveFactor'
FPS = 30
TOLERANCE = 1e-4

failures = []


def check(condition, message):
    if condition:
        print('PASS:', message)
    else:
        print('FAIL:', message)
        failures.append(message)


# --- Scene ---

def new_scene(frame_start=1, frame_end=250):
    bpy.ops.wm.read_homefile(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = FPS
    scene.render.fps_base = 1.0
    scene.frame_start = frame_start
    scene.frame_end = frame_end
    root = bpy.data.objects.new('MaterialAnimationTest_LOD0', None)
    scene.collection.objects.link(root)
    return scene, root


def new_object(scene, root, name, material):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)], [], [(0, 1, 2, 3)])
    mesh.uv_layers.new()
    mesh.update()
    mesh.materials.append(material)
    obj = bpy.data.objects.new(name, mesh)
    scene.collection.objects.link(obj)
    obj.parent = root
    return obj


def new_material(name, base=(0.5, 0.5, 0.5, 1.0), emissive=(0.0, 0.0, 0.0), emissive_scale=1.0):
    material = bpy.data.materials.new(name)
    material.msfs_material_type = 'msfs_standard'
    setattr(material, BASE, base)
    setattr(material, EMISSIVE, emissive)
    material.msfs_emissive_scale = emissive_scale
    return material


def key(material, prop, index, frame, value, interpolation=None):
    array = list(getattr(material, prop))
    saved = array[index]
    array[index] = value
    setattr(material, prop, array)
    material.keyframe_insert(prop, index=index, frame=frame)
    array[index] = saved
    setattr(material, prop, array)
    if interpolation:
        for point in fcurves_of(material, prop, index).keyframe_points:
            point.interpolation = interpolation


def channelbag(id_data):
    data = id_data.animation_data
    return data.action.layers[0].strips[0].channelbag(data.action_slot)


def fcurves_of(material, prop, index):
    return next(f for f in channelbag(material).fcurves if f.data_path == prop and f.array_index == index)


def snapshot(material, prop, scale=1.0, bag=None):
    """Evaluates like the Blender preview: keyed components from their F-Curve, others hold the material's value."""
    fcurves = {f.array_index: f for f in (bag or channelbag(material)).fcurves if f.data_path == prop}
    defaults = list(getattr(material, prop))

    def value(frame):
        return [
            (fcurves[i].evaluate(frame) if i in fcurves else defaults[i]) * scale
            for i in range(len(defaults))
        ]
    return value


def preview(scene, material, prop, frames, scale=1.0):
    """What Blender itself shows on each frame, read from the animated material (independent of the exporter's code)."""
    table = {}
    for frame in frames:
        scene.frame_set(frame)
        table[float(frame)] = [value * scale for value in getattr(material, prop)]
    scene.frame_set(scene.frame_start)
    return table.__getitem__


def to_nla(id_data, track_name, start, scale=1.0, repeat=1.0, reverse=False):
    data = id_data.animation_data
    action, slot = data.action, data.action_slot
    data.action = None
    track = data.nla_tracks.new()
    track.name = track_name
    strip = track.strips.new(track_name, int(start), action)
    strip.action_slot = slot
    strip.use_reverse = reverse
    strip.repeat = repeat
    strip.scale = scale
    return strip


# --- Export ---

def export(scene, name, mode='ACTIONS', sampling=False, frame_range=False, merge=None):
    folder = SCRATCH_DIR / name
    folder.mkdir(parents=True, exist_ok=True)
    scene.msfs_export_mode = 'OBJECTS'
    scene.msfs_fss_export_target = 'MSFS2024'
    scene.msfs_background_export = False
    export_settings.init_setting_presets(scene)
    settings = export_settings.get_active_export_settings(scene)
    settings.enable_msfs_extension = True
    settings.export_animations = True
    settings.export_animation_mode = mode
    settings.export_force_sampling = sampling
    settings.export_frame_range = frame_range
    if merge:
        settings.export_merge_animation = merge
    lod_groups.reload_lod_groups(scene, reset=True)
    for group in lod_groups.get_scene_lod_groups(scene):
        group.folder_path = str(folder)
        group.enabled = True
        group.generate_xml = False
        for lod in group.lods:
            lod.enabled = True
    bpy.ops.msfs2024.multi_export_gltf(export_mode='OBJECTS')
    return read_gltf(next(folder.glob('*.gltf')))


class Gltf:
    def __init__(self, path):
        self.path = path
        self.data = json.loads(path.read_text(encoding='utf-8'))
        self.buffers = []
        for buffer in self.data.get('buffers', []):
            uri = buffer['uri']
            if uri.startswith('data:'):
                self.buffers.append(base64.b64decode(uri.split(',', 1)[1]))
            else:
                self.buffers.append((path.parent / uri).read_bytes())

    def accessor(self, index):
        accessor = self.data['accessors'][index]
        view = self.data['bufferViews'][accessor['bufferView']]
        size = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}[accessor['type']]
        offset = view.get('byteOffset', 0) + accessor.get('byteOffset', 0)
        floats = struct.unpack_from(f'<{accessor["count"] * size}f', self.buffers[view['buffer']], offset)
        return accessor, [list(floats[i:i + size]) for i in range(0, len(floats), size)]

    def material_index(self, name):
        return next(i for i, m in enumerate(self.data.get('materials', [])) if m['name'] == name)

    def animation(self, name=None):
        for animation in self.data.get('animations', []):
            if name is None or animation['name'] == name:
                return animation
        return None

    def channel(self, material, target, animation_name=None):
        """Returns (output type, frames, values) of a material channel; None when it was not exported."""
        animation = self.animation(animation_name)
        if animation is None:
            return None
        wanted = f'materials/{self.material_index(material)}/{target}'
        channels = animation.get('extensions', {}).get('ASOBO_property_animation', {}).get('channels', [])
        for channel in channels:
            if channel['target'] == wanted:
                sampler = animation['samplers'][channel['sampler']]
                _, times = self.accessor(sampler['input'])
                accessor, values = self.accessor(sampler['output'])
                return accessor['type'], [round(t[0] * FPS, 3) for t in times], values
        return None


def read_gltf(path):
    return Gltf(path)


def check_channel(gltf, label, material, target, type_name, frames, value_at, animation_name=None):
    channel = gltf.channel(material, target, animation_name)
    check(channel is not None, f'{label}: {target} was exported')
    if channel is None:
        return
    exported_type, exported_frames, values = channel
    check(exported_type == type_name, f'{label}: {target} output is {type_name} (got {exported_type})')
    expected_frames = list(frames)
    check(
        exported_frames == [float(f) for f in expected_frames],
        f'{label}: {target} has one key per frame {expected_frames[0]}..{expected_frames[-1]} '
        f'(got {len(exported_frames)}: {exported_frames[:3]}..{exported_frames[-2:]})',
    )
    worst = None
    for frame, value in zip(exported_frames, values):
        expected = value_at(frame)
        if len(expected) != len(value):
            worst = (frame, value, expected)
            break
        for got, want in zip(value, expected):
            if abs(got - want) > TOLERANCE and (worst is None or abs(got - want) > worst[3]):
                worst = (frame, value, expected, abs(got - want))
    check(worst is None, f'{label}: {target} values match the F-Curves on every frame (worst: {worst})')


def check_valid_samplers(gltf, label):
    for animation in gltf.data.get('animations', []):
        for channel in animation.get('extensions', {}).get('ASOBO_property_animation', {}).get('channels', []):
            sampler = channel['sampler']
            valid = 0 <= sampler < len(animation['samplers'])
            check(valid, f'{label}: {animation["name"]} {channel["target"]} sampler index {sampler} is valid')
            if valid:
                accessor, _ = gltf.accessor(animation['samplers'][sampler]['output'])
                wanted = {'emissiveFactor': 'VEC3', 'baseColorFactor': 'VEC4'}.get(channel['target'].split('/')[-1])
                if wanted:
                    check(accessor['type'] == wanted, f'{label}: {channel["target"]} points at a {wanted} sampler')


# --- Cases ---

def test_acceptance():
    """Base Color and Emissive animated, Bezier easing, uneven keys, Emissive Scale not 1, with the deploy settings."""
    scene, root = new_scene()
    material = new_material('MatAcceptance', emissive_scale=2.5)
    for index, (a, b, c, d) in enumerate([(0.05, 1.0, 0.2, 0.8), (0.9, 0.1, 0.7, 0.2), (0.1, 0.5, 0.9, 0.3)]):
        for frame, value in zip((1, 4, 20, 30), (a, b, c, d)):
            key(material, BASE, index, frame, value)
    for frame, value in zip((1, 4, 20, 30), (1.0, 0.25, 0.75, 0.5)):
        key(material, BASE, 3, frame, value)
    for index, (a, b, c) in enumerate([(0.0, 1.0, 0.2), (0.0, 0.4, 0.8), (0.0, 0.1, 1.0)]):
        for frame, value in zip((1, 9, 30), (a, b, c)):
            key(material, EMISSIVE, index, frame, value)
    new_object(scene, root, 'AnimatedPlate', material)
    frames = range(1, 31)
    base = preview(scene, material, BASE, frames)
    emissive = preview(scene, material, EMISSIVE, frames, 2.5)
    check(base(9.0) != base(10.0) and base(1.0) != base(4.0), 'acceptance: the preview reads animated values')
    gltf = export(scene, 'acceptance')
    check_valid_samplers(gltf, 'acceptance')
    check_channel(gltf, 'acceptance', 'MatAcceptance', TARGET_BASE, 'VEC4', frames, base)
    check_channel(gltf, 'acceptance', 'MatAcceptance', TARGET_EMISSIVE, 'VEC3', frames, emissive)
    check('ASOBO_property_animation' in gltf.data.get('extensionsUsed', []), 'acceptance: extension is declared')


def test_constant_easing():
    scene, root = new_scene()
    material = new_material('MatConstant')
    for index in range(4):
        for frame, value in zip((1, 5, 15), (0.1, 0.9, 0.4)):
            key(material, BASE, index, frame, value, 'CONSTANT')
    new_object(scene, root, 'Plate', material)
    gltf = export(scene, 'constant')
    check_channel(gltf, 'constant', 'MatConstant', TARGET_BASE, 'VEC4', range(1, 16), snapshot(material, BASE))


def test_partial_color():
    """Components keyed on different frames, created out of order; keyframes come first from a later range."""
    scene, root = new_scene()
    material = new_material('MatPartial', base=(0.2, 0.3, 0.4, 0.75), emissive=(0.5, 0.0, 0.25), emissive_scale=2.0)
    key(material, BASE, 2, 10, 0.1)
    key(material, BASE, 2, 20, 0.9)
    key(material, BASE, 0, 1, 1.0)
    key(material, BASE, 0, 30, 0.0)
    key(material, EMISSIVE, 1, 5, 0.0)
    key(material, EMISSIVE, 1, 15, 1.0)
    new_object(scene, root, 'Plate', material)
    base = snapshot(material, BASE)
    emissive = snapshot(material, EMISSIVE, 2.0)
    gltf = export(scene, 'partial')
    check_channel(gltf, 'partial', 'MatPartial', TARGET_BASE, 'VEC4', range(1, 31), base)
    check_channel(gltf, 'partial', 'MatPartial', TARGET_EMISSIVE, 'VEC3', range(5, 16), emissive)


def test_muted_component():
    scene, root = new_scene()
    material = new_material('MatMuted', base=(0.2, 0.3, 0.4, 0.75))
    for index in range(3):
        key(material, BASE, index, 1, 0.0)
        key(material, BASE, index, 10, 1.0)
    fcurves_of(material, BASE, 1).mute = True
    new_object(scene, root, 'Plate', material)
    keyed = snapshot(material, BASE)

    def value(frame):
        result = keyed(frame)
        result[1] = 0.3
        return result
    gltf = export(scene, 'muted')
    check_channel(gltf, 'muted', 'MatMuted', TARGET_BASE, 'VEC4', range(1, 11), value)
    check(fcurves_of(material, BASE, 1).mute, 'muted: the artist\'s muted F-Curve stays muted after the export')


def test_range_off_keeps_later_keys():
    scene, root = new_scene(frame_start=1, frame_end=10)
    material = new_material('MatRangeOff')
    for index in range(4):
        key(material, BASE, index, 1, 0.1)
        key(material, BASE, index, 30, 0.9)
    new_object(scene, root, 'Plate', material)
    gltf = export(scene, 'range_off', frame_range=False)
    check_channel(gltf, 'range off', 'MatRangeOff', TARGET_BASE, 'VEC4', range(1, 31), snapshot(material, BASE))


def test_range_on_clips():
    scene, root = new_scene(frame_start=5, frame_end=10)
    material = new_material('MatRangeOn')
    for index in range(4):
        key(material, BASE, index, 1, 0.1)
        key(material, BASE, index, 30, 0.9)
    new_object(scene, root, 'Plate', material)
    gltf = export(scene, 'range_on', frame_range=True)
    check_channel(gltf, 'range on', 'MatRangeOn', TARGET_BASE, 'VEC4', range(5, 11), snapshot(material, BASE))


def test_shared_action_two_materials():
    scene, root = new_scene()
    first = new_material('MatSharedA', base=(0.1, 0.2, 0.3, 1.0), emissive_scale=2.0)
    for frame, value in zip((1, 10), (0.0, 1.0)):
        for index in range(3):
            key(first, EMISSIVE, index, frame, value)
        key(first, BASE, 0, frame, value)
    second = new_material('MatSharedB', base=(0.6, 0.7, 0.8, 0.5), emissive_scale=5.0)
    second.animation_data_create()
    second.animation_data.action = first.animation_data.action
    second.animation_data.action_slot = first.animation_data.action_slot
    new_object(scene, root, 'PlateA', first)
    new_object(scene, root, 'PlateB', second)
    bag = channelbag(first)
    expected = {
        'MatSharedA': (snapshot(first, EMISSIVE, 2.0, bag), snapshot(first, BASE, 1.0, bag)),
        'MatSharedB': (snapshot(second, EMISSIVE, 5.0, bag), snapshot(second, BASE, 1.0, bag)),
    }
    gltf = export(scene, 'shared_materials')
    check_valid_samplers(gltf, 'shared materials')
    for name, (emissive, base) in expected.items():
        check_channel(gltf, f'shared {name}', name, TARGET_EMISSIVE, 'VEC3', range(1, 11), emissive)
        check_channel(gltf, f'shared {name}', name, TARGET_BASE, 'VEC4', range(1, 11), base)


def test_shared_action_two_animations():
    """Sampler indices of one action in two glTF animations whose node channels differ in number."""
    scene, root = new_scene()
    material = new_material('MatTwoAnims')
    for index in range(4):
        key(material, BASE, index, 1, 0.1)
        key(material, BASE, index, 10, 0.9)
    action = material.animation_data.action
    slot = material.animation_data.action_slot
    value = snapshot(material, BASE)
    material.animation_data.action = None
    for track_name in ('ANIM_A', 'ANIM_B'):
        track = material.animation_data.nla_tracks.new()
        track.name = track_name
        strip = track.strips.new(track_name, 1, action)
        strip.action_slot = slot
    obj = new_object(scene, root, 'Plate', material)
    obj.keyframe_insert('location', frame=1)
    obj.location = (1, 2, 3)
    obj.keyframe_insert('location', frame=10)
    to_nla(obj, 'ANIM_A', 1)
    gltf = export(scene, 'shared_animations', mode='NLA_TRACKS', sampling=True)
    check_valid_samplers(gltf, 'shared animations')
    for name in ('ANIM_A', 'ANIM_B'):
        check_channel(gltf, name, 'MatTwoAnims', TARGET_BASE, 'VEC4', range(1, 11), value, animation_name=name)


def test_nla_strip_placement():
    """A moved and scaled strip: the material follows the object's animation of the same track."""
    scene, root = new_scene()
    material = new_material('MatNla')
    for index in range(4):
        for frame, keyed_value in zip((1, 4, 11), (0.0, 0.9, 0.3)):
            key(material, BASE, index, frame, keyed_value)
    obj = new_object(scene, root, 'Plate', material)
    obj.keyframe_insert('location', frame=1)
    obj.location = (0, 0, 3)
    obj.keyframe_insert('location', frame=11)
    start, scale = 51, 2.0
    to_nla(material, 'MOVED', start, scale)
    to_nla(obj, 'MOVED', start, scale)
    shown = preview(scene, material, BASE, range(start, start + 21))
    gltf = export(scene, 'nla_strip', mode='NLA_TRACKS', sampling=True)

    animation = gltf.animation('MOVED')
    check(animation is not None, 'nla strip: the track was exported')
    node_frames = []
    for channel in animation['channels']:
        if channel['target']['path'] == 'translation':
            _, times = gltf.accessor(animation['samplers'][channel['sampler']]['input'])
            node_frames = [t[0] * FPS for t in times]
    print(f'INFO: nla strip: node channel covers frames {node_frames[0]:.2f}..{node_frames[-1]:.2f}')
    material_channel = gltf.channel('MatNla', TARGET_BASE, 'MOVED')
    check(material_channel is not None, 'nla strip: material channel was exported')
    if material_channel:
        frames = material_channel[1]
        check(
            abs(frames[0] - node_frames[0]) < 0.01 and abs(frames[-1] - node_frames[-1]) < 0.01,
            f'nla strip: material times follow the node ({frames[0]}..{frames[-1]} '
            f'against {node_frames[0]:.2f}..{node_frames[-1]:.2f})',
        )
        check_channel(
            gltf, 'nla strip', 'MatNla', TARGET_BASE, 'VEC4', range(start, start + 21), shown, animation_name='MOVED',
        )


def test_nla_strip_repeat_reverse():
    for label, repeat, reverse in (('repeat', 2.0, False), ('reverse', 1.0, True)):
        scene, root = new_scene()
        material = new_material('MatNlaVariant')
        for index in range(4):
            for frame, keyed_value in zip((1, 4, 11), (0.0, 0.9, 0.3)):
                key(material, BASE, index, frame, keyed_value)
        new_object(scene, root, 'Plate', material)
        strip = to_nla(material, 'VARIANT', 21, 1.0, repeat, reverse)
        frames = range(int(strip.frame_start), int(strip.frame_end) + 1)
        shown = preview(scene, material, BASE, frames)
        gltf = export(scene, f'nla_{label}', mode='NLA_TRACKS', sampling=True)
        check_channel(
            gltf, f'nla {label}', 'MatNlaVariant', TARGET_BASE, 'VEC4', frames, shown, animation_name='VARIANT',
        )


def test_track_of_another_object():
    """The deploy settings (Actions mode, merged by NLA track, no sampling): a material animation named like an NLA
    track of another object (a wiper armature driving the windshield's Wiper 1 State) joins that animation once."""
    scene, root = new_scene()
    driver = bpy.data.objects.new('WiperDriver', None)
    scene.collection.objects.link(driver)
    driver.parent = root
    driver.keyframe_insert('rotation_euler', frame=1)
    driver.rotation_euler = (0.0, 0.0, 1.2)
    driver.keyframe_insert('rotation_euler', frame=11)
    to_nla(driver, 'ANIM_SWEEP', 1)
    material = new_material('MatWiped')
    for index in range(4):
        key(material, BASE, index, 1, 0.0, 'LINEAR')
        key(material, BASE, index, 11, 1.0, 'LINEAR')
    material.animation_data.action.name = 'ANIM_SWEEP'
    to_nla(material, 'ANIM_SWEEP', 1)
    new_object(scene, root, 'Glass', material)
    shown = preview(scene, material, BASE, range(1, 12))
    gltf = export(scene, 'track_of_another_object', merge='NLA_TRACK')
    named = [a for a in gltf.data.get('animations', []) if a['name'] == 'ANIM_SWEEP']
    check(len(named) == 1, f'track of another object: one animation ANIM_SWEEP (got {len(named)})')
    if named:
        nodes = {gltf.data['nodes'][c['target']['node']]['name'] for c in named[0]['channels']}
        check('WiperDriver' in nodes, f'track of another object: ANIM_SWEEP moves the driver (nodes {sorted(nodes)})')
    check_valid_samplers(gltf, 'track of another object')
    check_channel(
        gltf, 'track of another object', 'MatWiped', TARGET_BASE, 'VEC4', range(1, 12), shown,
        animation_name='ANIM_SWEEP',
    )


def test_one_action_object_and_material():
    """The deploy settings: one active action animating an object and its material exports one animation."""
    scene, root = new_scene()
    material = new_material('MatBoth')
    obj = new_object(scene, root, 'Lever', material)
    obj.keyframe_insert('location', frame=1)
    obj.location = (0.0, 0.0, 1.0)
    obj.keyframe_insert('location', frame=11)
    action = obj.animation_data.action
    action.name = 'ANIM_BOTH'
    material.animation_data_create()
    material.animation_data.action = action
    for index in range(4):
        key(material, BASE, index, 1, 0.0, 'LINEAR')
        key(material, BASE, index, 11, 1.0, 'LINEAR')
    shown = preview(scene, material, BASE, range(1, 12))
    gltf = export(scene, 'one_action_object_and_material', merge='NLA_TRACK')
    named = [a for a in gltf.data.get('animations', []) if a['name'] == 'ANIM_BOTH']
    check(len(named) == 1, f'one action: one animation ANIM_BOTH (got {len(named)})')
    if named:
        nodes = {gltf.data['nodes'][c['target']['node']]['name'] for c in named[0]['channels']}
        check('Lever' in nodes, f'one action: ANIM_BOTH moves the object (nodes {sorted(nodes)})')
    check_channel(
        gltf, 'one action', 'MatBoth', TARGET_BASE, 'VEC4', range(1, 12), shown, animation_name='ANIM_BOTH',
    )


def test_keys_outside_range_only():
    """No key inside the exported range: nothing to export, and the rest of the file is intact."""
    scene, root = new_scene(frame_start=100, frame_end=110)
    material = new_material('MatOutside')
    for index in range(4):
        key(material, BASE, index, 1, 0.1)
        key(material, BASE, index, 10, 0.9)
    new_object(scene, root, 'Plate', material)
    gltf = export(scene, 'outside', frame_range=True)
    check(gltf.channel('MatOutside', TARGET_BASE) is None, 'outside: no channel without a frame in the range')
    check(any(n['name'] == 'Plate' for n in gltf.data['nodes']), 'outside: the node is still exported')


def main():
    if SCRATCH_DIR.exists():
        shutil.rmtree(SCRATCH_DIR)
    cases = [
        test_acceptance,
        test_constant_easing,
        test_partial_color,
        test_muted_component,
        test_range_off_keeps_later_keys,
        test_range_on_clips,
        test_shared_action_two_materials,
        test_shared_action_two_animations,
        test_nla_strip_placement,
        test_nla_strip_repeat_reverse,
        test_track_of_another_object,
        test_one_action_object_and_material,
        test_keys_outside_range_only,
    ]
    for case in cases:
        print(f'--- {case.__name__}')
        try:
            case()
        except Exception as error:
            import traceback
            traceback.print_exc()
            check(False, f'{case.__name__} raised {type(error).__name__}: {error}')
    print()
    print(f'RESULT: {len(failures)} failure(s)')
    for failure in failures:
        print('  FAILED:', failure)
    sys.stdout.flush()
    sys.exit(1 if failures else 0)


main()
