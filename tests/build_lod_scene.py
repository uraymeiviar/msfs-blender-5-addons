"""Background Blender synthetic source for stage 1 integration tests."""

import json
from pathlib import Path
import sys

import addon_utils
import bpy

addon_utils.enable('io_scene_gltf2_msfs_fss', default_set=True)
addon_utils.enable('fss_blender_tools', default_set=True)
from fss_blender_tools import lod, lod_model

out = Path(sys.argv[sys.argv.index('--') + 1])
out.mkdir(parents=True, exist_ok=True)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
scene = bpy.context.scene
scene.fss_lod_settings.reference_size = 10


def cube(name, size, x=0, parent=None):
    bpy.ops.mesh.primitive_cube_add(size=size, location=(x, 0, 0))
    obj = bpy.context.object
    obj.name = name
    if parent:
        world = obj.matrix_world.copy()
        obj.parent = parent
        obj.matrix_world = world
    return obj


cube('Large', 1)
cube('Below', .001, 2)
cube('Above', .02, 3)
cube('Hide3', .001, 4)['fss_lod'] = 3
cube('Show3', .001, 5)['fss_lod_show_from'] = 3
cube('Keep', .001, 6)['fss_lod_keep'] = 1
small_parent = cube('SmallParent', .001, 7)
cube('LargeChild', 1, 7, small_parent)
keep_parent = cube('KeepParent', .001, 8)
cube('KeepChild', .001, 8, keep_parent)['fss_lod_keep'] = 1
cube('SmallSibling', .001, 8, keep_parent)
hidden = cube('HiddenParent', 1, 9)
hidden['fss_lod'] = 2
cube('BlockedKeep', .001, 9, hidden)['fss_lod_keep'] = 1
tagged = cube('TaggedKeep', .001, 10)
tagged['fss_tags'] = 'important'
scene.fss_lod_settings.keep_tags = 'important'
manual = cube('ManuallyHidden', 1, 11)
manual.hide_set(True)
root = bpy.data.objects.new('@MERGE_Panel', None)
scene.collection.objects.link(root)
root.location = (12, 0, 0)
cube('PanelBody', 1, 12, root)
cube('PanelScrew', .001, 12, root)
nomerge = cube('@NOMERGE_Button', .2, 12.2, root)
animated = cube('Animated', .2, 12.3, root)
animated['fss_lod'] = 4
animated.keyframe_insert(data_path='location', frame=1)
animated.location.z = .1
animated.keyframe_insert(data_path='location', frame=20)
action = animated.animation_data.action
track = animated.animation_data.nla_tracks.new()
track.name = 'ButtonTravel'
track.strips.new('ButtonTravel', 1, action)
animated.animation_data.action = None
scene.frame_set(1)
bpy.context.view_layer.update()

plan = lod_model.build_plan(bpy.context)
assert 'KeepChild' in plan['decisions'][6].present
assert 'KeepParent' in plan['decisions'][6].present
assert 'SmallSibling' not in plan['decisions'][1].present
assert 'SmallParent' in plan['decisions'][6].present
assert 'BlockedKeep' not in plan['decisions'][2].present
assert 'Show3' not in plan['decisions'][0].present
assert 'Show3' in plan['decisions'][3].present
assert 'TaggedKeep' in plan['decisions'][6].present

scene.fss_viewport_lod = 6
lod.apply_viewport_lod(bpy.context)
assert bpy.data.objects['Below'].get('_fss_lod_hidden')
assert not manual.get('_fss_lod_hidden')
assert manual.hide_get()
bpy.ops.wm.save_as_mainfile(filepath=str(out / 'synthetic.blend'))
expected = {'present': [sorted(d.present) for d in plan['decisions']],
            'count': len(plan['parts']), 'cutoffs': [d.cutoff for d in plan['decisions']]}
(out / 'expected.json').write_text(json.dumps(expected, indent=2))

# Settings and UI operators: verify the saved diameter and explicit-table distinction.
scene.fss_lod_settings.model_type = 'INTERIOR'
assert scene.fss_lod_settings.preview_error == 'exterior diameter missing'
scene.fss_lod_settings.min_sizes_fs24 = (1, .7, .5, .3, .1, .05, .01)
assert scene.fss_lod_settings.explicit_fs24
assert 'not written' in scene.fss_lod_settings.preview_error
assert lod_model.build_plan(bpy.context)['decisions'][6].present == set()
lod_model.restore_filter(bpy.context)
bpy.ops.wm.save_as_mainfile(filepath=str(out / 'interior.blend'))
scene.fss_viewport_lod = -1
lod_model.restore_filter(bpy.context)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
scene.fss_lod_settings.model_type = 'EXTERIOR'
cube('Early', 1)['fss_lod'] = 2
cube('Late', 1, 2)['fss_lod_show_from'] = 4
bpy.ops.wm.save_as_mainfile(filepath=str(out / 'gap.blend'))
print('LOD_SYNTHETIC_SOURCE_PASS', flush=True)
