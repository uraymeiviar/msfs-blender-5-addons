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
    assert [off[1:] for off in by_name['ACTION_50_100']] == [(50.0, 100.0, None)], by_name['ACTION_50_100']
    assert [off[1:] for off in by_name['ACTION_SINGLE_KEY']] == [(100.0, 100.0, None)], by_name['ACTION_SINGLE_KEY']
    # A strip moved in time is off even though its action is 0 to 100.
    assert [off[1:] for off in by_name['STRIP_MOVED']] == [(10.0, 110.0, None)], by_name['STRIP_MOVED']
    # A strip at 0 to 100 does not hide an action keyed elsewhere, and it says where the strip plays it.
    assert [off[1:] for off in by_name['STRIP_ACTION_OFF']] == [(100.0, 200.0, (0.0, 100.0))], by_name['STRIP_ACTION_OFF']
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


def _selected():
    return {obj.name for obj in bpy.context.selected_objects}


class _Recorder:
    """Records what a panel draws (background Blender has no UI to draw into)."""

    def __init__(self, calls):
        self.calls = calls

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self if name in ('row', 'column', 'box', 'split', 'operator') else None
        return call


def test_list_and_click_select():
    _build()
    wm = bpy.context.window_manager
    keep = bpy.data.objects['OK_ACTION']
    keep.select_set(True)
    hidden = bpy.data.objects['ACTION_1_100']
    hidden.hide_set(True)
    bpy.context.view_layer.update()
    before = _state()

    # Finding lists every offender, hidden ones too, sorted, and selects nothing
    assert bpy.ops.fss.find_animations_off_range() == {'FINISHED'}
    assert _state() == before, "the check changed animation data"
    rows = wm.fss_anim_off_rows
    names = [row.name for row in rows]
    assert names == sorted(BAD), names
    assert wm.fss_anim_off_active == -1 and _selected() == {'OK_ACTION'}, _selected()
    by_name = {row.name: row for row in rows}
    assert by_name['ACTION_50_100'].ranges == '50 - 100' and by_name['ACTION_50_100'].details.endswith(': 50 to 100')
    assert by_name['STRIP_ACTION_OFF'].details.split('\n')[-1] == 'keys stored at 100 to 200, plays at 0 to 100', by_name['STRIP_ACTION_OFF'].details

    # A click on a row selects its object alone and makes it active
    wm.fss_anim_off_active = names.index('ACTION_50_100')
    assert _selected() == {'ACTION_50_100'} and bpy.context.view_layer.objects.active.name == 'ACTION_50_100'
    wm.fss_anim_off_active = names.index('STRIP_MOVED')
    assert _selected() == {'STRIP_MOVED'} and bpy.context.view_layer.objects.active.name == 'STRIP_MOVED'

    # The same row again, after clicking elsewhere: Select does it, as a list does not call a row clicked twice
    bpy.data.objects['STRIP_MOVED'].select_set(False)
    assert bpy.ops.fss.animation_off_range_select() == {'FINISHED'} and _selected() == {'STRIP_MOVED'}

    # A hidden object's row: the selection stays, Select says why, and the row says so
    wm.fss_anim_off_active = names.index('ACTION_1_100')
    assert _selected() == {'STRIP_MOVED'}, _selected()
    assert bpy.ops.fss.animation_off_range_select() == {'CANCELLED'} and _selected() == {'STRIP_MOVED'}

    # Drawn: the list under the button, with the details of the active row
    calls = []
    checks._draw_animations_off_range(_Recorder(calls), bpy.context)
    assert [name for name, _a, _k in calls][:2] == ['operator', 'template_list'], calls
    labels = [kw.get('text') for name, _a, kw in calls if name == 'label']
    assert 'Hidden or no longer there: not selected' in labels, labels

    # Select All: every listed object Blender can select, as the check did before
    assert bpy.ops.fss.animation_off_range_select_all() == {'FINISHED'}
    assert _selected() == BAD - {'ACTION_1_100'}, _selected()

    # An object deleted after finding: its row does nothing, and nothing fails
    bpy.data.objects.remove(bpy.data.objects['ACTION_0_101'])
    wm.fss_anim_off_active = names.index('ACTION_0_101')
    assert bpy.ops.fss.animation_off_range_select() == {'CANCELLED'}
    assert _state()[0] == before[0]

    # Opening a file empties the list
    checks._on_load_post()
    assert len(wm.fss_anim_off_rows) == 0 and wm.fss_anim_off_active == -1
    calls = []
    checks._draw_animations_off_range(_Recorder(calls), bpy.context)
    assert [name for name, _a, _k in calls] == ['operator'], calls
    print("PASS: the list shows every offender, a click selects its object, hidden and deleted rows do no harm, nothing else changes")


def test_clean_scene_keeps_selection():
    _clear()
    good = _keyed('OK_ACTION', 0, 100)
    other = _empty('OTHER')
    other.select_set(True)
    bpy.context.view_layer.update()
    assert checks.animations_off_range(bpy.context.view_layer) == {}
    assert bpy.ops.fss.find_animations_off_range() == {'FINISHED'}
    assert other.select_get() and not good.select_get()
    assert len(bpy.context.window_manager.fss_anim_off_rows) == 0
    print("PASS: a clean scene lists nothing and keeps the selection")


if __name__ == '__main__':
    failed = False
    fss_blender_tools.register()
    try:
        test_finds_every_breach_and_only_those()
        test_list_and_click_select()
        test_clean_scene_keeps_selection()
        print("ALL ANIMATION RANGE TESTS PASSED")
    except Exception:
        traceback.print_exc()
        failed = True
    sys.stdout.flush()
    if failed:
        sys.exit(1)
