"""Density marks multiply down the hierarchy (UV journal decisions 105 to 110): the scene freedom applied once, marks
on zones and objects multiplied, presets as factors, Clear, unmarked = x1, parent_density() and density(); the
migration of the marks of versions before 0.31.0 (custom-property density marks, fss_zone_density, margin fractions)
at file load and at register, idempotent; the Result drawn by the Packing panel; texture size (square) and margin
defaults.

To run:
"<blender>" -b --factory-startup --python tests/test_density_marks.py
"""

import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import bpy

# If an addons_core copy was loaded during Blender startup, unregister and purge it
if 'fss_blender_tools' in sys.modules:
    try:
        sys.modules['fss_blender_tools'].unregister()
    except Exception:
        pass
    for mod in list(sys.modules.keys()):
        if mod == 'fss_blender_tools' or mod.startswith('fss_blender_tools.'):
            del sys.modules[mod]

REPO_ROOT = Path(__file__).resolve().parents[1]
repo_root_str = str(REPO_ROOT)
while repo_root_str in sys.path:
    sys.path.remove(repo_root_str)
sys.path.insert(0, repo_root_str)

import fss_blender_tools  # noqa: E402
from fss_blender_tools import uv_marks, visibility_core  # noqa: E402

fss_blender_tools.register()
assert Path(uv_marks.__file__).resolve().is_relative_to(REPO_ROOT), uv_marks.__file__

SCRATCH_DIR = REPO_ROOT / 'tests' / '_work' / 'density_marks_scratch'


def close(a, b):
    return all(abs(x - y) < 1e-6 for x, y in zip(a, b))


def new_object(name, parent=None, mesh=False):
    data = None
    if mesh:
        data = bpy.data.meshes.new(name + '_MESH')
        data.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    obj.parent = parent
    return obj


def mark(obj, low, high=None):
    setattr(obj, uv_marks.OWN_PROP, True)
    setattr(obj, uv_marks.MAX_PROP, high if high is not None else low)
    setattr(obj, uv_marks.MIN_PROP, low)


def build_chain():
    """ROOT > @ZONE_FWD x1.5 > DOOR_L x1.0-1.1 > PANEL (unmarked) > KNOB x0.75 (a mesh)."""
    bpy.ops.wm.read_homefile(use_empty=True)
    o = {'root': new_object('EMPTY_ROOT_TEST')}
    o['zone'] = new_object('@ZONE_FWD', o['root'])
    o['door'] = new_object('DOOR_L', o['zone'])
    o['panel'] = new_object('PANEL', o['door'])
    o['knob'] = new_object('KNOB', o['panel'], mesh=True)
    mark(o['zone'], 1.5)
    mark(o['door'], 1.0, 1.1)
    mark(o['knob'], 0.75)
    return o


def test_defaults():
    bpy.ops.wm.read_homefile(use_empty=True)
    scene = bpy.context.scene
    assert abs(scene.fss_uv_target_density - 20.48) < 1e-6, scene.fss_uv_target_density
    assert close(uv_marks.scene_freedom(scene), (0.9, 1.1)), uv_marks.scene_freedom(scene)
    material = bpy.data.materials.new('DEFAULTS')
    assert material.fss_uv_texture_size == '4096' and uv_marks.texture_size(material) == 4096
    assert uv_marks.margin(material) == 8
    sizes = [item.identifier for item in bpy.types.Material.bl_rna.properties[uv_marks.SIZE_PROP].enum_items]
    assert sizes == ['256', '512', '1024', '2048', '4096', '8192'], sizes
    material.fss_uv_texture_size = '1024'
    assert uv_marks.texture_size(material) == 1024
    assert not any(hasattr(material, key) for key in uv_marks.OLD_SIZE_KEYS)  # square only (decision 120)
    obj = new_object('UNMARKED')
    assert not getattr(obj, uv_marks.OWN_PROP) and uv_marks.own_density(obj) is None
    print("PASS: test_defaults (20.48 px/cm, freedom 0.9-1.1, 4096 x 4096, 8 px)")


def test_multiplication():
    o = build_chain()
    scene = bpy.context.scene
    cases = {  # key: (parent range, parent source, final range, final source)
        'root': ((0.9, 1.1), None, (0.9, 1.1), None),
        'zone': ((0.9, 1.1), None, (1.35, 1.65), 'zone'),
        'door': ((1.35, 1.65), 'zone', (1.35, 1.815), 'door'),
        'panel': ((1.35, 1.815), 'door', (1.35, 1.815), 'door'),
        'knob': ((1.35, 1.815), 'door', (1.0125, 1.36125), 'knob'),
    }
    for key, (parent, parent_source, final, source) in cases.items():
        got_parent, got_parent_source = uv_marks.parent_density(o[key], scene)
        got, got_source = uv_marks.density(o[key], scene)
        assert close(got_parent, parent) and got_parent_source == (o[parent_source] if parent_source else None), (
            key, got_parent, got_parent_source)
        assert close(got, final) and got_source == (o[source] if source else None), (key, got, got_source)
    # The scene freedom enters once, at the root: with 1.0 to 1.0 only the marks remain
    scene.fss_uv_density_freedom_min = 1.0
    scene.fss_uv_density_freedom_max = 1.0
    assert close(uv_marks.density(o['knob'], scene)[0], (1.5 * 0.75, 1.5 * 1.1 * 0.75))
    # Unmarked counts as x1: PANEL's range is its parent's
    assert uv_marks.density(o['panel'], scene)[0] == uv_marks.parent_density(o['panel'], scene)[0]
    assert uv_marks.density(None, scene) == ((1.0, 1.0), None)
    print(f"PASS: test_multiplication ({len(cases)} objects; KNOB x1.0125 - x1.36125 from the chain)")


def test_presets_and_clear():
    o = build_chain()
    for obj in bpy.context.scene.objects:
        obj.select_set(obj in (o['panel'], o['knob']))
    bpy.context.view_layer.objects.active = o['knob']
    expected = {'LOWER': (0.75, 0.75), 'HIGHER': (1.5, 1.5)}
    for preset, factor in expected.items():
        assert bpy.ops.fss.uv_set_density(preset=preset) == {'FINISHED'}
        for key in ('panel', 'knob'):
            assert uv_marks.own_density(o[key]) == factor, (preset, key, uv_marks.own_density(o[key]))
    assert close(uv_marks.density(o['knob'])[0], (1.35 * 1.5 * 1.5, 1.815 * 1.5 * 1.5))
    assert bpy.ops.fss.uv_set_density(preset='CLEAR') == {'FINISHED'}
    for key in ('panel', 'knob'):
        assert uv_marks.own_density(o[key]) is None and not getattr(o[key], uv_marks.OWN_PROP), key
        assert (getattr(o[key], uv_marks.MIN_PROP), getattr(o[key], uv_marks.MAX_PROP)) == (1.0, 1.0), key
    (low, high), source = uv_marks.density(o['knob'])
    assert close((low, high), (1.35, 1.815)) and source == o['door'], (low, high, source)
    # Min never above Max: dragging one past the other moves the other along
    knob = o['knob']
    mark(knob, 1.0, 1.2)
    setattr(knob, uv_marks.MIN_PROP, 1.5)
    assert close((getattr(knob, uv_marks.MIN_PROP), getattr(knob, uv_marks.MAX_PROP)), (1.5, 1.5))
    setattr(knob, uv_marks.MAX_PROP, 0.5)
    assert close((getattr(knob, uv_marks.MIN_PROP), getattr(knob, uv_marks.MAX_PROP)), (0.5, 0.5))
    print("PASS: test_presets_and_clear (Lower x0.75, Higher x1.5, Clear, Min/Max order)")


def build_old_marks():
    """Marks as versions before 0.31.0 stored them, written as raw ID properties:
    @ZONE_A (zone 2.0) > PARENT [1.5, 1.65] > CHILD [0.7, 0.8]; @ZONE_B (zone 1.0) > X;
    @ZONE_C (zone 2.0 and [1.0, 1.2]) > Y [0.5, 0.5]; margins 0.002 and 0.004."""
    o = {}
    o['zone_a'] = new_object('@ZONE_A')
    o['parent'] = new_object('PARENT', o['zone_a'])
    o['child'] = new_object('CHILD', o['parent'])
    o['zone_b'] = new_object('@ZONE_B')
    o['x'] = new_object('X', o['zone_b'])
    o['zone_c'] = new_object('@ZONE_C')
    o['y'] = new_object('Y', o['zone_c'])
    for key, value in (('zone_a', 2.0), ('zone_b', 1.0), ('zone_c', 2.0)):
        o[key].bl_system_properties_get(do_create=True)[uv_marks.ZONE_DENSITY_KEY] = value
    for key, value in (('parent', [1.5, 1.65]), ('child', [0.7, 0.8]), ('zone_c', [1.0, 1.2]), ('y', [0.5, 0.5])):
        o[key][uv_marks.DENSITY_KEY] = value
    for name, value in (('OLD_MARGIN_8', 0.002), ('OLD_MARGIN_16', 0.004)):
        material = bpy.data.materials.new(name)
        material[uv_marks.MARGIN_KEY] = value
        material.use_fake_user = True  # saved without users
    return o


def check_migrated(o, report):
    assert (report['density'], report['zone'], report['margin'], report['kept']) == (4, 3, 2, 0), report
    assert sorted(report['nested']) == [('CHILD', 'PARENT'), ('Y', '@ZONE_C')], report['nested']
    expected = {'zone_a': (2.0, 2.0), 'parent': (1.5, 1.65), 'child': (0.7, 0.8), 'zone_b': None, 'x': None,
                'zone_c': (2.0, 2.4), 'y': (0.5, 0.5)}
    for key, value in expected.items():
        got = uv_marks.own_density(o[key])
        assert (got is None and value is None) or (got is not None and value is not None and close(got, value)), (
            key, got, value)
        assert uv_marks.DENSITY_KEY not in o[key], key
        system = o[key].bl_system_properties_get()
        assert system is None or uv_marks.ZONE_DENSITY_KEY not in system, key
    for name, px in (('OLD_MARGIN_8', 8), ('OLD_MARGIN_16', 16)):
        material = bpy.data.materials[name]
        assert uv_marks.MARGIN_KEY not in material and uv_marks.margin(material) == px, (name, uv_marks.margin(material))


def objects_by_name(keys_to_names):
    return {key: bpy.data.objects[name] for key, name in keys_to_names.items()}


def test_migration():
    bpy.ops.wm.read_homefile(use_empty=True)
    o = build_old_marks()
    report = uv_marks.run_migration()
    check_migrated(o, report)
    assert uv_marks._migration == report
    # Idempotent: a second run finds nothing and changes nothing (the panel keeps the first run's report)
    again = uv_marks.run_migration()
    assert (again['density'], again['zone'], again['margin'], again['nested']) == (0, 0, 0, []), again
    assert uv_marks._migration == report
    check_migrated(o, report)
    # An own mark that already exists wins over an old key written again (by an older version)
    o['child'][uv_marks.DENSITY_KEY] = [3.0, 3.0]
    kept = uv_marks.run_migration()
    assert kept['kept'] == 1 and close(uv_marks.own_density(o['child']), (0.7, 0.8)), kept
    assert uv_marks.DENSITY_KEY not in o['child']
    print(f"PASS: test_migration ({report['density']} density, {report['zone']} zone, {report['margin']} margin, "
          f"nested {report['nested']}; second run converts nothing)")


def test_migration_at_load_and_register():
    names = {'zone_a': '@ZONE_A', 'parent': 'PARENT', 'child': 'CHILD', 'zone_b': '@ZONE_B', 'x': 'X',
             'zone_c': '@ZONE_C', 'y': 'Y'}
    if SCRATCH_DIR.exists():
        shutil.rmtree(SCRATCH_DIR)
    SCRATCH_DIR.mkdir(parents=True)
    path = SCRATCH_DIR / 'old_marks.blend'
    # load_post: a file saved with old marks is converted when it opens
    bpy.ops.wm.read_homefile(use_empty=True)
    build_old_marks()
    bpy.ops.wm.save_as_mainfile(filepath=str(path))
    bpy.ops.wm.read_homefile(use_empty=True)
    bpy.ops.wm.open_mainfile(filepath=str(path))
    check_migrated(objects_by_name(names), uv_marks._migration)
    # register: the open file is converted when the add-on is enabled (no file is read in between: reading one
    # makes Blender reload the add-on modules)
    fss_blender_tools.unregister()
    for collection in (bpy.data.objects, bpy.data.materials):
        for item in list(collection):
            collection.remove(item)
    build_old_marks()
    fss_blender_tools.register()
    check_migrated(objects_by_name(names), uv_marks._migration)
    print("PASS: test_migration_at_load_and_register")


class _Layout:
    """Records what a panel draws (background Blender has no UI to draw into)."""

    def __init__(self, calls):
        self.calls = calls

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if name == 'operator':
                return SimpleNamespace()  # panels set operator properties on it
            return self if name in ('row', 'column', 'box', 'split', 'grid_flow', 'column_flow') else None
        return call


def draw_packing():
    calls = []
    bpy.types.FSS_PT_uv_marks.draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
    labels = [kwargs.get('text') for name, _args, kwargs in calls if name == 'label']
    return calls, labels


def after(labels, label):
    return labels[labels.index(label) + 1]


def test_panel():
    o = build_chain()
    knob = o['knob']
    materials = [bpy.data.materials.new(f'KNOB_MAT_{index}') for index in range(7)]
    for material in materials + [materials[0]]:
        knob.data.materials.append(material)
    bpy.context.view_layer.objects.active = knob
    knob.select_set(True)
    calls, labels = draw_packing()
    rows = {label: after(labels, label) for label in ('Parent', 'Zone', 'Visibility', 'Result')}
    assert rows == {'Parent': 'x1.35 - x1.82 from DOOR_L', 'Zone': 'FWD x1.50', 'Visibility': 'no data: x1.00',
                    'Result': '20.74 - 27.88 px/cm'}, rows
    assert after(labels, 'Result') == '20.74 - 27.88 px/cm'
    assert '= target x parent x own x visibility' in labels
    props = [(args[0], args[1], kwargs.get('text')) for name, args, kwargs in calls if name == 'prop']
    scene = bpy.context.scene
    for prop in ((scene, 'fss_uv_target_density', ''), (scene, 'fss_uv_density_freedom_min', 'Min'),
                 (scene, 'fss_uv_density_freedom_max', 'Max'), (knob, uv_marks.OWN_PROP, 'own mark'),
                 (knob, uv_marks.MIN_PROP, 'Min'), (knob, uv_marks.MAX_PROP, 'Max'),
                 (materials[0], uv_marks.SIZE_PROP, ''), (materials[0], 'fss_uv_margin_px', '')):
        assert prop in props, (prop, props)
    texts = [kwargs.get('text') for name, _args, kwargs in calls if name == 'operator']
    # the presets, the directions, then Pack of the texture set below the list and Check All (decisions 114, 115, 121)
    assert texts == ['Lower', 'Higher', 'Clear', 'Free', 'Upright', 'Flip', 'Quarter', 'Clear', 'Pack', 'Check All'], (
        texts)
    assert 'Select Marked' not in texts and not hasattr(bpy.types, 'FSS_OT_uv_select_marked')
    sets = [label for label in labels if label and label.startswith('Texture set: ')]
    assert sets == ['Texture set: KNOB_MAT_0'], sets
    # all 7 texture sets are in the list (a UIList over bpy.data.materials, filtered to the selection's)
    assert [name for name, _args, _kwargs in calls].count('template_list') == 1 and not [
        label for label in labels if label and label.startswith('... ')], labels
    assert [m.name for m in uv_marks.texture_set_materials(bpy.context)] == [f'KNOB_MAT_{index}' for index in range(7)]
    # Root of the scene: the scene freedom; outside every zone
    bpy.context.view_layer.objects.active = o['root']
    _calls, labels = draw_packing()
    assert (after(labels, 'Parent'), after(labels, 'Zone')) == ('x0.90 - x1.10 (scene freedom)', 'none')
    print("PASS: test_panel (Parent, Zone, Visibility, Result 20.74 - 27.88 px/cm, 7 texture sets in the list)")


def test_panel_visibility():
    """The Visibility row and the Result with island values, through a stand-in for get_object_visibility (the
    analysis itself is tested in tests/uv_prototype/test_visibility.py)."""
    o = build_chain()
    knob = o['knob']
    bpy.context.view_layer.objects.active = knob
    if not SCRATCH_DIR.exists():
        SCRATCH_DIR.mkdir(parents=True)
    path = SCRATCH_DIR / 'visibility_row.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(path))
    path.with_suffix('.visibility').write_bytes(b'stand-in')
    calls = []
    answer = {'stale': False, 'never_seen': False, 'object_score': 0.8, 'island_values': {0: 0.5, 1: 0.0, 2: 0.9}}

    def stand_in(obj, uv_name=None, vis_path=None, use_cache=True):
        calls.append(obj.name)
        return dict(answer)

    real = visibility_core.get_object_visibility
    visibility_core.get_object_visibility = stand_in
    try:
        knob = bpy.data.objects['KNOB']
        bpy.context.view_layer.objects.active = knob
        _draw, labels = draw_packing()
        # Islands: 0.0 is never seen and gets the minimum x0.10 (decision 74)
        assert after(labels, 'Visibility') == 'x0.80  islands 0.10-0.90', after(labels, 'Visibility')
        assert after(labels, 'Result') == '16.59 - 22.30 px/cm  (islands 2.07 - 25.09)', after(labels, 'Result')
        draw_packing()
        assert calls == ['KNOB'], f"a redraw scored the islands again: {calls}"
        answer.update(never_seen=True, object_score=0.0)
        uv_marks._vis_cache.clear()
        _draw, labels = draw_packing()
        assert after(labels, 'Visibility') == 'never seen: x0.10', after(labels, 'Visibility')
        answer.update(stale=True)
        uv_marks._vis_cache.clear()
        _draw, labels = draw_packing()
        assert after(labels, 'Visibility') == 'no data: x1.00', after(labels, 'Visibility')
    finally:
        visibility_core.get_object_visibility = real
    print("PASS: test_panel_visibility (x0.80, islands 0.10-0.90, Result 16.59 - 22.30, cached across redraws)")


def test_visibility_floor():
    # Decision 111: the minimum is a floor, so a face seen a little never gets less than a face never seen
    for score, expected in ((0.0, 0.1), (0.05, 0.1), (0.1, 0.1), (0.5, 0.5), (1.0, 1.0)):
        got = uv_marks.visibility_factor(score)
        assert abs(got - expected) < 1e-9, (score, got, expected)
    print("PASS: test_visibility_floor (0 and 0.05 give x0.10, 0.5 stays x0.50)")


def test_heatmap_after_mark_change():
    # A parent's mark changes its children's density: the heatmap drops its cached objects once the edit pauses
    from fss_blender_tools import uv_heatmap
    o = build_chain()
    edits = [lambda: setattr(o['door'], uv_marks.MIN_PROP, 0.9),
             lambda: setattr(o['door'], uv_marks.MAX_PROP, 1.2),
             lambda: setattr(o['zone'], uv_marks.OWN_PROP, False),
             lambda: setattr(bpy.context.scene, 'fss_uv_density_freedom_min', 0.8)]
    for edit in edits:
        uv_heatmap._cache['KNOB'] = object()
        uv_heatmap._global_stats['selection'] = ('KNOB',)
        edit()
        assert bpy.app.timers.is_registered(uv_heatmap._drop_after_marks), "no refresh scheduled"
        uv_heatmap._drop_after_marks()  # what the timer runs (timers do not fire inside a background script)
        bpy.app.timers.unregister(uv_heatmap._drop_after_marks)
        assert not uv_heatmap._cache and 'selection' not in uv_heatmap._global_stats
    # With nothing cached, a mark change schedules nothing
    o['door'].fss_uv_density_max = 1.3
    assert not bpy.app.timers.is_registered(uv_heatmap._drop_after_marks)
    print(f"PASS: test_heatmap_after_mark_change ({len(edits)} kinds of edit drop the cache)")


def main():
    test_defaults()
    test_multiplication()
    test_presets_and_clear()
    test_migration()
    test_migration_at_load_and_register()
    test_panel()
    test_panel_visibility()
    test_visibility_floor()
    test_heatmap_after_mark_change()
    print("ALL TESTS PASSED")


main()
