"""Find Animations Not 0 to 100 (Checks panel): what it reports and selects, and that it changes nothing.

To run:
"<blender>" -b --factory-startup --python tests/test_animation_ranges.py
"""

import sys
import traceback
from pathlib import Path

# If an addons_core copy was loaded during Blender startup, unregister and purge it
if 'fss_blender_tools' in sys.modules:
    try:
        sys.modules['fss_blender_tools'].unregister()
    except Exception:
        pass
    for mod in list(sys.modules.keys()):
        if mod == 'fss_blender_tools' or mod.startswith('fss_blender_tools.'):
            del sys.modules[mod]

REPO_ROOT = str(Path(__file__).resolve().parents[1])
while REPO_ROOT in sys.path:
    sys.path.remove(REPO_ROOT)
sys.path.insert(0, REPO_ROOT)

import bpy  # noqa: E402

import fss_blender_tools  # noqa: E402
from fss_blender_tools import checks  # noqa: E402


def _empty(name):
    obj = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _keyed(name, *frames):
    """An empty keyed on `frames`, with the action still active."""
    obj = _empty(name)
    for frame in frames:
        obj.location.x = frame
        obj.keyframe_insert('location', index=0, frame=frame)
    return obj


def _strip(name, frames, start=None, end=None, mute=False):
    """An empty whose action, keyed on `frames`, is only in an NLA strip placed at start to end."""
    obj = _keyed(name, *frames)
    action = obj.animation_data.action
    obj.animation_data.action = None
    strip = obj.animation_data.nla_tracks.new().strips.new(name, int(frames[0] if start is None else start), action)
    if end is not None:
        strip.frame_end = end
    strip.mute = mute
    return obj


def _clear():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    for action in list(bpy.data.actions):
        bpy.data.actions.remove(action)


def _build():
    _clear()
    for obj in (_keyed('OK_ACTION', 0, 100), _strip('OK_STRIP', (0, 100)), _empty('NOT_ANIMATED')):
        pass
    _keyed('ACTION_50_100', 50, 100)
    _keyed('ACTION_1_100', 1, 100)
    _keyed('ACTION_0_101', 0, 101)
    _keyed('ACTION_100_200', 100, 200)
    _keyed('ACTION_SINGLE_KEY', 100)
    _strip('STRIP_MOVED', (0, 100), start=10)
    _strip('STRIP_ACTION_OFF', (100, 200), start=0, end=100)
    _strip('STRIP_MUTED', (50, 100), mute=True)
    bpy.context.view_layer.update()


BAD = {'ACTION_50_100', 'ACTION_1_100', 'ACTION_0_101', 'ACTION_100_200', 'ACTION_SINGLE_KEY',
       'STRIP_MOVED', 'STRIP_ACTION_OFF', 'STRIP_MUTED'}


def test_finds_every_breach_and_only_those():
    _build()
    found = checks.animations_off_range(bpy.context.view_layer)
    assert {obj.name for obj in found} == BAD, sorted(obj.name for obj in found)
    by_name = {obj.name: off for obj, off in found.items()}
    assert [off[1:] for off in by_name['ACTION_50_100']] == [(50.0, 100.0)], by_name['ACTION_50_100']
    assert [off[1:] for off in by_name['ACTION_SINGLE_KEY']] == [(100.0, 100.0)], by_name['ACTION_SINGLE_KEY']
    # A strip moved in time is off even though its action is 0 to 100.
    assert [off[1:] for off in by_name['STRIP_MOVED']] == [(10.0, 110.0)], by_name['STRIP_MOVED']
    # A strip at 0 to 100 does not hide an action keyed elsewhere.
    assert [off[1:] for off in by_name['STRIP_ACTION_OFF']] == [(100.0, 200.0)], by_name['STRIP_ACTION_OFF']
    print("PASS: every breach found, exact ranges, nothing else listed")


def _state():
    scene = bpy.context.scene
    objects = {}
    for obj in bpy.data.objects:
        data = obj.animation_data
        objects[obj.name] = None if data is None else (
            data.action.name if data.action else None,
            tuple(data.action.frame_range) if data.action else None,
            [(s.name, s.frame_start, s.frame_end, s.mute) for t in data.nla_tracks for s in t.strips],
        )
    actions = {a.name: tuple(a.frame_range) for a in bpy.data.actions}
    return scene.frame_current, scene.frame_start, scene.frame_end, objects, actions


def test_operator_selects_and_changes_nothing():
    _build()
    bpy.data.objects['OK_ACTION'].select_set(True)
    hidden = bpy.data.objects['ACTION_1_100']
    hidden.hide_set(True)
    bpy.context.view_layer.update()
    before = _state()
    assert bpy.ops.fss.find_animations_off_range() == {'FINISHED'}
    assert _state() == before, "the check changed animation data"
    selected = {obj.name for obj in bpy.context.selected_objects}
    assert selected == BAD - {'ACTION_1_100'}, sorted(selected)
    assert bpy.context.view_layer.objects.active.name in selected
    assert hidden.name in {obj.name for obj in checks.animations_off_range(bpy.context.view_layer)}
    print("PASS: operator selects the visible offenders, keeps hidden ones reported, changes no animation data")


def test_clean_scene_keeps_selection():
    _clear()
    good = _keyed('OK_ACTION', 0, 100)
    other = _empty('OTHER')
    other.select_set(True)
    bpy.context.view_layer.update()
    assert checks.animations_off_range(bpy.context.view_layer) == {}
    assert bpy.ops.fss.find_animations_off_range() == {'FINISHED'}
    assert other.select_get() and not good.select_get()
    print("PASS: a clean scene reports nothing and keeps the selection")


if __name__ == '__main__':
    failed = False
    fss_blender_tools.register()
    try:
        test_finds_every_breach_and_only_those()
        test_operator_selects_and_changes_nothing()
        test_clean_scene_keeps_selection()
        print("ALL ANIMATION RANGE TESTS PASSED")
    except Exception:
        traceback.print_exc()
        failed = True
    sys.stdout.flush()
    if failed:
        sys.exit(1)
