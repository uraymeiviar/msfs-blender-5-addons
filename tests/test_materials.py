"""Materials panel (material-management journal, Sessions 5, 8 and 11): Refresh rows (never used, shared across zones,
hidden users, shared meshes, area per zone, the estimate with and without a .visibility file), the kind marks with and
without the exporter add-on, the select operators, every panel drawn without writing, Keep UVs in the active material
box (kept instead of the estimate, without Refresh), and that no fss_ key reaches the glTF.

To run:
G:\\e-jets-e2\\tools\\blender\\blender.exe -b --factory-startup --python tests/test_materials.py
"""

import json
import math
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import addon_utils
import bpy
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
ADDONS = ('io_scene_gltf2_msfs_fss', 'fss_blender_tools')

# The portable Blender enables its deployed addons_core copies at startup: disable and purge them, then import the
# repository modules first, so addon_utils enables those (the exporter hooks of enabled add-ons run at export)
for name in reversed(ADDONS):
    if addon_utils.check(name)[1]:
        addon_utils.disable(name)
    for mod in list(sys.modules.keys()):
        if mod == name or mod.startswith(name + '.'):
            del sys.modules[mod]
repo_root_str = str(REPO_ROOT)
while repo_root_str in sys.path:
    sys.path.remove(repo_root_str)
sys.path.insert(0, repo_root_str)

import io_scene_gltf2_msfs_fss  # noqa: E402,F401
import fss_blender_tools  # noqa: E402
from fss_blender_tools import materials, tags, uv_marks, visibility_core  # noqa: E402

for name in ADDONS:
    addon_utils.enable(name, default_set=True)
    assert Path(sys.modules[name].__file__).resolve().is_relative_to(REPO_ROOT), sys.modules[name].__file__

SCRATCH_DIR = REPO_ROOT / 'tests' / '_work' / 'materials_scratch'
TARGET = 10.0  # px/cm for the estimate
EST_MARK = 2.0  # own density mark of the estimate plane


def new_empty(name, parent=None):
    obj = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(obj)
    obj.parent = parent
    return obj


def new_planes(name, quads, slots, face_slots, parent=None, mesh=None, link=True):
    """A mesh object of axis-aligned quads (x, y, width, height) in metres, with the given slots and per-face slot
    indices; mesh: reuse that mesh (a linked duplicate)."""
    if mesh is None:
        mesh = bpy.data.meshes.new(name + '_Mesh')
        verts, faces = [], []
        for x, y, w, h in quads:
            base = len(verts)
            verts += [(x, y, 0), (x + w, y, 0), (x + w, y + h, 0), (x, y + h, 0)]
            faces.append((base, base + 1, base + 2, base + 3))
        mesh.from_pydata(verts, [], faces)
        for material in slots:
            mesh.materials.append(material)
        mesh.polygons.foreach_set('material_index', face_slots)
        mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    if link:
        bpy.context.scene.collection.objects.link(obj)
    obj.parent = parent
    return obj


def build_scene():
    """Zones FWD and AFT and an object outside every zone, with one material per case."""
    bpy.ops.wm.read_homefile(use_empty=True)
    scene = bpy.context.scene
    scene.fss_uv_target_density = TARGET
    m = {name: bpy.data.materials.new(name) for name in (
        'MAT_SHARED', 'MAT_EMPTY_SLOT', 'MAT_NO_SLOT', 'MAT_HIDDEN', 'MAT_INST', 'MAT_BLEND', 'MAT_EMIT', 'MAT_EST',
        'MAT_ORPHAN')}
    o = {'mat': m}
    o['root'] = new_empty('EMPTY_ROOT_TEST')
    o['fwd'] = new_empty('@ZONE_FWD', o['root'])
    o['aft'] = new_empty('@ZONE_AFT', o['root'])
    # MAT_SHARED in both zones: 1 m2 in FWD, 2 m2 in AFT; MAT_EMPTY_SLOT only in a slot without faces
    o['fwd_a'] = new_planes('FWD_A', [(0, 0, 1, 1)], [m['MAT_SHARED'], m['MAT_EMPTY_SLOT']], [0], o['fwd'])
    o['aft_a'] = new_planes('AFT_A', [(0, 0, 2, 1)], [m['MAT_SHARED']], [0], o['aft'])
    # MAT_HIDDEN on a hidden object: used, one hidden user
    o['hidden'] = new_planes('AFT_HIDDEN', [(0, 0, 1, 1)], [m['MAT_HIDDEN']], [0], o['aft'])
    # MAT_INST: two objects share one mesh (0.5 m2); the second is scaled, the area counts once, on INST_1
    o['inst1'] = new_planes('INST_1', [(0, 0, 1, 0.5)], [m['MAT_INST']], [0], o['fwd'])
    o['inst2'] = new_planes('INST_2', None, None, None, o['fwd'], mesh=o['inst1'].data)
    o['inst2'].scale = (3, 3, 3)
    # Outside every zone: MAT_BLEND (0.25 m2) and MAT_EMIT (0.75 m2) on one object
    o['outside'] = new_planes('OUTSIDE', [(0, 0, 0.5, 0.5), (1, 0, 0.75, 1)], [m['MAT_BLEND'], m['MAT_EMIT']],
                              [0, 1], o['root'])
    # The estimate: 0.5 m x 0.5 m in AFT with an own density mark
    o['est'] = new_planes('EST_PLANE', [(0, 0, 0.5, 0.5)], [m['MAT_EST']], [0], o['aft'])
    setattr(o['est'], uv_marks.OWN_PROP, True)
    setattr(o['est'], uv_marks.MAX_PROP, EST_MARK)
    setattr(o['est'], uv_marks.MIN_PROP, EST_MARK)
    # MAT_ORPHAN only on an object outside the view layer
    o['orphan'] = new_planes('ORPHAN', [(0, 0, 1, 1)], [m['MAT_ORPHAN']], [0], link=False)
    # Outside the view layer, in an excluded collection: one material only there, one in a slot without faces there
    # (still never used), one also on an object in the view layer (counted for that object only)
    excluded = bpy.data.collections.new('EXCLUDED')
    bpy.context.scene.collection.children.link(excluded)
    for name in ('MAT_EXCLUDED', 'MAT_EXCLUDED_SLOT', 'MAT_BOTH'):
        m[name] = bpy.data.materials.new(name)
    o['in_excluded'] = new_planes('IN_EXCLUDED', [(0, 0, 1, 1), (2, 0, 1, 1)],
                                  [m['MAT_EXCLUDED'], m['MAT_BOTH'], m['MAT_EXCLUDED_SLOT']], [0, 1], link=False)
    excluded.objects.link(o['in_excluded'])
    o['both'] = new_planes('BOTH', [(0, 0, 1, 1)], [m['MAT_BOTH']], [0], o['fwd'])
    # The mesh holds MAT_SHADOWED, an object-linked slot shows MAT_BOTH instead: no face uses MAT_SHADOWED
    m['MAT_SHADOWED'] = bpy.data.materials.new('MAT_SHADOWED')
    o['shadow'] = new_planes('SHADOW_OBJECT', [(0, 0, 1, 1)], [m['MAT_SHADOWED']], [0], o['fwd'])
    o['shadow'].material_slots[0].link = 'OBJECT'
    o['shadow'].material_slots[0].material = m['MAT_BOTH']
    bpy.context.view_layer.layer_collection.children['EXCLUDED'].exclude = True
    bpy.context.view_layer.update()
    o['hidden'].hide_set(True)
    return o


def rows():
    return {row.name: row for row in bpy.context.scene.fss_materials.rows}


def zones_of(row):
    return {zone.name: (zone.objects, round(zone.area, 6)) for zone in row.zones}


def test_rows():
    o = build_scene()
    selected = {obj.name for obj in bpy.context.view_layer.objects if obj.select_get()}
    active = bpy.context.view_layer.objects.active
    gp = bpy.data.materials.new('GP_MAT')
    bpy.data.materials.create_gpencil_data(gp)
    assert bpy.ops.fss.materials_refresh() == {'FINISHED'}
    r = rows()
    assert 'GP_MAT' not in r, sorted(r)
    # Faces only outside the view layer: no row
    assert sorted(r) == sorted(set(o['mat']) - {'MAT_ORPHAN', 'MAT_EXCLUDED'}), sorted(r)
    assert o['in_excluded'].name not in bpy.context.view_layer.objects
    # Refresh changes nothing but Scene.fss_materials
    assert {obj.name for obj in bpy.context.view_layer.objects if obj.select_get()} == selected
    assert bpy.context.view_layer.objects.active == active

    shared = r['MAT_SHARED']
    assert shared.shared_zones and not shared.never_used and shared.warning
    assert (shared.objects, shared.hidden, shared.shared_meshes) == (2, 0, 0)
    assert zones_of(shared) == {'AFT': (1, 2.0), 'FWD': (1, 1.0)}, zones_of(shared)
    assert abs(shared.area - 3.0) < 1e-6 and shared.zone_names == 'AFT, FWD', (shared.area, shared.zone_names)

    assert r['MAT_BOTH'].objects == 2 and not r['MAT_BOTH'].never_used
    # The objects that only hold a material never used
    assert {name: r[name].holders for name in ('MAT_EMPTY_SLOT', 'MAT_NO_SLOT', 'MAT_EXCLUDED_SLOT', 'MAT_SHADOWED',
                                               'MAT_SHARED')} == {
        'MAT_EMPTY_SLOT': 1, 'MAT_NO_SLOT': 0, 'MAT_EXCLUDED_SLOT': 0, 'MAT_SHADOWED': 1, 'MAT_SHARED': 0}
    for name in ('MAT_EMPTY_SLOT', 'MAT_NO_SLOT', 'MAT_EXCLUDED_SLOT', 'MAT_SHADOWED'):
        row = r[name]
        assert row.never_used and row.warning and row.objects == 0 and not row.zones, name
    hidden = r['MAT_HIDDEN']
    assert (hidden.never_used, hidden.objects, hidden.hidden) == (False, 1, 1)

    inst = r['MAT_INST']
    assert (inst.objects, inst.shared_meshes, inst.shared_zones) == (2, 1, False)
    assert zones_of(inst) == {'FWD': (2, 0.5)}, zones_of(inst)

    blend, emit = r['MAT_BLEND'], r['MAT_EMIT']
    assert zones_of(blend) == {materials.NO_ZONE: (1, 0.25)} and blend.zone_names == materials.NO_ZONE_SHORT
    assert zones_of(emit) == {materials.NO_ZONE: (1, 0.75)}
    assert not blend.warning and not emit.warning

    # The estimate: sqrt(area_cm2) x target x the high end of the object's range (scene freedom x own mark); the
    # .blend is unsaved, so no visibility data: x1.0
    assert not any(row.with_visibility for row in r.values()), [name for name, row in r.items() if row.with_visibility]
    est = r['MAT_EST']
    high = uv_marks.DEFAULT_FREEDOM[1] * EST_MARK
    expected = math.sqrt(2500.0) * TARGET * high
    assert abs(est.estimate - expected) < 1e-3, (est.estimate, expected)
    est_px = est.estimate
    # Without a mark: MAT_SHARED's 3 m2 at the scene freedom's high end
    expected_shared = math.sqrt(30000.0) * TARGET * uv_marks.DEFAULT_FREEDOM[1]
    assert abs(shared.estimate - expected_shared) < 1e-3, (shared.estimate, expected_shared)

    # The active row is kept by name across a new Refresh
    settings = bpy.context.scene.fss_materials
    settings.active = list(r).index('MAT_INST')
    assert settings.active_name == 'MAT_INST'
    bpy.data.materials.new('AAA_FIRST')
    bpy.ops.fss.materials_refresh()
    assert materials.active_row(settings).name == 'MAT_INST', settings.active_name

    # Warnings filter and name filter of the list
    ul = SimpleNamespace(filter_name='', bitflag_filter_item=1 << 30)
    settings.show = 'WARNINGS'
    flags, _order = materials.FSS_UL_Materials.filter_items(ul, bpy.context, settings, 'rows')
    shown = sorted(row.name for row, flag in zip(settings.rows, flags) if flag)
    assert shown == ['AAA_FIRST', 'MAT_EMPTY_SLOT', 'MAT_EXCLUDED_SLOT', 'MAT_NO_SLOT', 'MAT_SHADOWED',
                     'MAT_SHARED'], shown
    settings.show = 'ALL'
    ul.filter_name = '*INST*'
    flags, _order = materials.FSS_UL_Materials.filter_items(ul, bpy.context, settings, 'rows')
    assert [row.name for row, flag in zip(settings.rows, flags) if flag] == ['MAT_INST']
    print(f"PASS: test_rows ({len(settings.rows)} rows; shared across zones, never used (empty slot, no slot), no row "
          f"for faces only outside the view layer, hidden user, shared mesh, area per zone, estimate {est_px:.1f} px)")


def write_visibility(blend_path, objects, stale=()):
    """A .visibility file beside blend_path through visibility_core.save_visibility_file. objects: {object: score or
    'NEVER'}; each object's mesh is in the file (meshes in stale with a wrong face count)."""
    mesh_meta, mesh_arrays, summaries = {}, {}, {}
    for obj, score in objects.items():
        me = obj.data
        n = len(me.polygons)
        mesh_meta[me.name] = {'n_orig_faces': n + 1 if me.name in stale else n}
        mesh_arrays[me.name] = {key: np.zeros(n, np.float32) for key in (
            'vis_omega', 'unocc_omega', 'face_scores', 'face_undetermined', 'face_never_seen', 'face_patch_size_px')}
        never = score == 'NEVER'
        summaries[obj.name] = {'score': 0.0 if never else score, 'never_seen': never, 'undetermined': False}
    return visibility_core.save_visibility_file(blend_path, {'mesh_meta': mesh_meta, 'mesh_arrays': mesh_arrays,
                                                             'object_summaries': summaries})


def test_visibility():
    """Decision 12: the estimate multiplies each object's density by its visibility (the Packing section's object
    score, floor 0.1, never seen 0.1, 1.0 without data); a shared mesh uses its first user."""
    o = build_scene()
    folder = SCRATCH_DIR / 'visibility'
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    blend_path = folder / 'materials_vis.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    high = uv_marks.DEFAULT_FREEDOM[1]

    # Saved, but no .visibility file: the estimate is unchanged
    assert bpy.ops.fss.materials_refresh() == {'FINISHED'}
    r = rows()
    assert not any(row.with_visibility for row in r.values())
    assert abs(r['MAT_EST'].estimate - math.sqrt(2500.0) * TARGET * high * EST_MARK) < 1e-3, r['MAT_EST'].estimate
    plain = {name: row.estimate for name, row in r.items()}

    # FWD_A seen (0.4), AFT_A seen a little (0.05, floor 0.1), EST_PLANE never seen, INST_1 0.5 and INST_2 0.9 (the
    # shared mesh counts on INST_1), OUTSIDE's mesh stale, AFT_HIDDEN not in the file
    write_visibility(blend_path, {o['fwd_a']: 0.4, o['aft_a']: 0.05, o['est']: 'NEVER', o['inst1']: 0.5,
                                  o['inst2']: 0.9, o['outside']: 1.0}, stale={o['outside'].data.name})
    loads = visibility_core.get_file_load_count()
    assert bpy.ops.fss.materials_refresh() == {'FINISHED'}
    assert visibility_core.get_file_load_count() - loads == 1, "the .visibility file was not read once per Refresh"
    r = rows()
    expected = {
        'MAT_SHARED': TARGET * high * math.sqrt(10000.0 * 0.4 ** 2 + 20000.0 * 0.1 ** 2),
        'MAT_EST': math.sqrt(2500.0) * TARGET * high * EST_MARK * uv_marks.NEVER_SEEN_FACTOR,
        'MAT_INST': math.sqrt(5000.0) * TARGET * high * 0.5,
    }
    for name, value in expected.items():
        assert r[name].with_visibility, name
        assert math.isclose(r[name].estimate, value, rel_tol=1e-6, abs_tol=1e-3), (name, r[name].estimate, value)
    for name in ('MAT_BLEND', 'MAT_EMIT', 'MAT_HIDDEN'):
        assert not r[name].with_visibility, name
        assert abs(r[name].estimate - plain[name]) < 1e-6, (name, r[name].estimate, plain[name])
    # The same factor as the Packing section's Visibility row
    for obj, factor in ((o['fwd_a'], 0.4), (o['aft_a'], 0.1), (o['est'], 0.1), (o['inst1'], 0.5)):
        packing = uv_marks._object_visibility(obj)
        assert abs(packing['object'] - factor) < 1e-6, (obj.name, packing)
    assert uv_marks._object_visibility(o['outside'])['status'] == 'NO_DATA'

    settings = bpy.context.scene.fss_materials
    texts = {}
    for name in ('MAT_SHARED', 'MAT_BLEND'):
        settings.active = settings.rows.find(name)
        calls = []
        materials.FSS_PT_Materials.draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
        texts[name] = [kwargs.get('text') for call, _args, kwargs in calls
                       if call == 'label' and (kwargs.get('text') or '').startswith('about ')]
    assert texts['MAT_SHARED'][0].endswith(' px square (estimate, with visibility)'), texts
    assert texts['MAT_BLEND'][0].endswith(' px square (estimate, no visibility data)'), texts
    # The cached file keeps the .visibility file open on Windows: close it, so the scratch folder can be removed
    for entry in visibility_core._vis_file_cache.values():
        entry['data'].close()
    visibility_core.clear_file_cache()
    print(f"PASS: test_visibility (no file: unchanged; with file: MAT_SHARED {r['MAT_SHARED'].estimate:.1f} px, "
          f"never seen x0.1, floor 0.1, shared mesh on its first user, stale and missing x1.0, file read once, "
          f"labels)")


def test_kinds(with_exporter):
    o = build_scene()
    m = o['mat']
    if with_exporter:
        m['MAT_BLEND'].msfs_alpha_mode = 'BLEND'
        m['MAT_EMIT'].msfs_emissive_texture = bpy.data.images.new('EMIT_TEX', 4, 4)
    else:
        # After the scene: reading the home file enables the preferences' add-ons again
        m['MAT_BLEND'].msfs_alpha_mode = 'BLEND'
        m['MAT_EMIT'].msfs_emissive_texture = bpy.data.images.new('EMIT_TEX', 4, 4)
        addon_utils.disable('io_scene_gltf2_msfs_fss', default_set=True)
        assert not addon_utils.check('io_scene_gltf2_msfs_fss')[1], "the exporter add-on is still enabled"
        assert not hasattr(bpy.types.Material, 'msfs_alpha_mode'), "the exporter's material properties remain"
    assert bpy.ops.fss.materials_refresh() == {'FINISHED'}
    r = rows()
    kinds = {name: (row.transparent, row.emissive) for name, row in r.items() if row.transparent or row.emissive}
    expected = {'MAT_BLEND': (True, False), 'MAT_EMIT': (False, True)} if with_exporter else {}
    assert kinds == expected, kinds
    print(f"PASS: test_kinds ({'with' if with_exporter else 'without'} the exporter add-on: {kinds or 'no marks'})")


def selection():
    view_layer = bpy.context.view_layer
    return sorted(obj.name for obj in view_layer.objects if obj.select_get()), view_layer.objects.active


def test_select():
    o = build_scene()
    bpy.ops.fss.materials_refresh()
    assert bpy.ops.fss.materials_select(material='MAT_SHARED') == {'FINISHED'}
    assert selection() == (['AFT_A', 'FWD_A'], o['aft_a']), selection()
    assert bpy.ops.fss.materials_select(material='MAT_SHARED', in_zone=True, zone='@ZONE_FWD') == {'FINISHED'}
    assert selection() == (['FWD_A'], o['fwd_a']), selection()
    assert bpy.ops.fss.materials_select(material='MAT_BLEND', in_zone=True, zone='') == {'FINISHED'}
    assert selection() == (['OUTSIDE'], o['outside']), selection()
    assert bpy.ops.fss.materials_select(material='MAT_INST') == {'FINISHED'}
    assert selection() == (['INST_1', 'INST_2'], o['inst1']), selection()
    # Only visible objects: nothing to select leaves the selection as it was
    assert bpy.ops.fss.materials_select(material='MAT_HIDDEN') == {'CANCELLED'}
    assert selection() == (['INST_1', 'INST_2'], o['inst1']), selection()
    assert bpy.ops.fss.materials_select(material='MAT_SHARED', in_zone=True, zone='') == {'CANCELLED'}
    # A material never used, held without a face using it: in a slot no face uses, and in a mesh slot that an
    # object-linked slot replaces. Select Objects finds the objects; the zone buttons do not
    assert bpy.ops.fss.materials_select(material='MAT_EMPTY_SLOT') == {'FINISHED'}
    assert selection() == (['FWD_A'], o['fwd_a']), selection()
    shadow = o['mat']['MAT_SHADOWED']
    assert 'SHADOW_OBJECT' in bpy.data.objects and bpy.data.objects['SHADOW_OBJECT'].material_slots[0].material != shadow
    assert bpy.ops.fss.materials_select(material='MAT_SHADOWED') == {'FINISHED'}
    assert selection() == (['SHADOW_OBJECT'], bpy.data.objects['SHADOW_OBJECT']), selection()
    assert bpy.ops.fss.materials_select(material='MAT_SHADOWED', in_zone=True, zone='@ZONE_FWD') == {'CANCELLED'}
    # A used material selects only its users: an object that only holds it stays out
    bpy.data.objects['SHADOW_OBJECT'].name = 'AAA_SHADOW'
    o['aaa'] = bpy.data.objects['AAA_SHADOW']
    o['aaa'].data.materials[0] = o['mat']['MAT_INST']
    assert bpy.ops.fss.materials_select(material='MAT_INST') == {'FINISHED'}
    assert selection() == (['INST_1', 'INST_2'], o['inst1']), selection()
    assert o['aaa'] in materials.holding_objects(bpy.context.view_layer, o['mat']['MAT_INST'])
    # Used only by a hidden object, held by a visible one: a used material, so nothing to select
    o['aaa'].data.materials[0] = o['mat']['MAT_HIDDEN']
    assert bpy.ops.fss.materials_select(material='MAT_HIDDEN') == {'CANCELLED'}
    assert selection() == (['INST_1', 'INST_2'], o['inst1']), selection()
    # Hidden holders are counted, not selected
    o['aaa'].hide_set(True)
    o['aaa'].data.materials[0] = shadow
    bpy.ops.fss.materials_refresh()
    assert rows()['MAT_SHADOWED'].holders == 1 and rows()['MAT_SHADOWED'].never_used
    assert bpy.ops.fss.materials_select(material='MAT_SHADOWED') == {'CANCELLED'}
    print("PASS: test_select (all zones, one zone, (no zone), shared mesh, hidden and empty cases, objects that only "
          "hold a material never used, and not a used one)")


class _Layout:
    """Records what a panel or list row draws (background Blender has no UI to draw into)."""

    def __init__(self, calls):
        self.calls = calls

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if name == 'operator':
                kwargs['properties'] = SimpleNamespace()  # panels set operator properties on it
                return kwargs['properties']
            return self if name in ('row', 'column', 'box', 'split') else None
        return call


def snapshot(settings):
    """Everything Refresh wrote, to show that drawing writes nothing."""
    values = [settings.active_name, settings.scanned, settings.show, settings.name_width]
    for row in settings.rows:
        values.append(tuple(getattr(row, key) for key in (
            'name', 'objects', 'hidden', 'shared_meshes', 'zone_names', 'area', 'estimate', 'with_visibility',
            'never_used', 'holders', 'no_texture', 'shared_zones', 'transparent', 'emissive')))
        values += [(zone.name, zone.zone, zone.objects, zone.area) for zone in row.zones]
    return values


class approx(float):
    def __eq__(self, other):
        return abs(self - other) < 1e-6


def _texture(row):
    return materials._texture_text(row, short=True)


def test_draw():
    build_scene()
    settings = bpy.context.scene.fss_materials
    icons = set(bpy.types.UILayout.bl_rna.functions['label'].parameters['icon'].enum_items.keys())
    calls = []
    materials.FSS_PT_Materials.draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
    texts = [kwargs.get('text') for name, _args, kwargs in calls if name == 'label']
    assert texts == ['Press Refresh to list the materials'], texts
    bpy.ops.fss.materials_refresh()
    before = snapshot(settings)
    used_icons = set()
    for index, row in enumerate(settings.rows):
        calls = []
        materials.FSS_UL_Materials.draw_item(None, bpy.context, _Layout(calls), settings, row, 0, settings, 'active',
                                             index)
        used_icons |= {kwargs['icon'] for _name, _args, kwargs in calls if 'icon' in kwargs}
    # The columns: the name at the slider's width, the zones in what is left, the texture narrow and fixed
    settings.name_width = 0.4
    layout = _Layout(calls := [])
    materials.FSS_UL_Materials.draw_item(None, bpy.context, layout, settings, settings.rows['MAT_SHARED'], 0, settings,
                                         'active', 0)
    assert [kwargs['factor'] for name, _args, kwargs in calls if name == 'split'] == [approx(0.4)], calls
    assert layout.ui_units_x == materials.TEXTURE_COLUMN_UNITS  # _Layout hands itself out for each row
    assert [kwargs.get('text') for name, _args, kwargs in calls if name == 'label'][-3:] == [
        'MAT_SHARED', '2 obj  AFT, FWD', _texture(settings.rows['MAT_SHARED'])], calls
    settings.name_width = 0.3
    details = {}
    for index, row in enumerate(settings.rows):
        settings.active = index
        before = snapshot(settings)
        calls = []
        materials.FSS_PT_Materials.draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
        assert snapshot(settings) == before, f"the panel wrote while drawing ({row.name})"
        assert any(name == 'template_list' for name, _args, _kwargs in calls)
        assert any(name == 'prop' and args[1] == 'name_width' and kwargs.get('slider') for name, args, kwargs in calls)
        used_icons |= {kwargs['icon'] for _name, _args, kwargs in calls if 'icon' in kwargs}
        details[row.name] = calls
    calls = []
    materials.FSS_PT_MaterialsByNeed.draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
    assert snapshot(settings) == before, "By Texture Need wrote while drawing"
    used_icons |= {kwargs['icon'] for _name, _args, kwargs in calls if 'icon' in kwargs}
    need_lines = [kwargs.get('text') for name, _args, kwargs in calls if name == 'label']
    # Per material, largest estimate first, without the materials never used
    table = materials.need_table(settings)
    estimates = [row.estimate for row, _material in table]
    assert estimates == sorted(estimates, reverse=True) and estimates[0] > 0, estimates
    assert {row.name for row, _m in table} == {row.name for row in settings.rows if not row.never_used}
    assert not any(row.never_used for row, _m in table)
    assert need_lines[1] == table[0][0].name, need_lines
    assert need_lines[2].startswith(f'about {round(table[0][0].estimate)} px, texture '), need_lines
    assert not any('material(s)' in line for line in need_lines), need_lines

    # What the estimate says against the texture size, in power-of-two sizes
    plain = table[0][1]
    verdict = materials.texture_verdict
    plain_size = uv_marks.texture_size(plain)
    plain.fss_uv_texture_size = '1024'
    assert verdict(SimpleNamespace(estimate=1024.0), plain) == 'about right'
    assert verdict(SimpleNamespace(estimate=600.0), plain) == 'about right'
    assert verdict(SimpleNamespace(estimate=1100.0), plain) == 'too small, 2048 needed'
    assert verdict(SimpleNamespace(estimate=512.0), plain) == 'oversized, 512 would do'
    assert verdict(SimpleNamespace(estimate=3.0), plain) == 'oversized, 256 would do'
    assert verdict(SimpleNamespace(estimate=9000.0), plain) == 'too small, 8192 or more'
    plain.fss_uv_texture_size = str(plain_size)

    # A material that draws nothing leaves this list, by its MSFS type and not by its name; the main list keeps it
    invisible = table[0][1]
    invisible.msfs_material_type = 'msfs_invisible'
    assert invisible not in [material for _row, material in materials.need_table(settings)]
    assert invisible.name in settings.rows
    invisible.msfs_material_type = 'msfs_standard'
    assert invisible in [material for _row, material in materials.need_table(settings)]
    named = bpy.data.materials.new('NAMED_COLLIDER')
    assert not materials.is_not_rendered(named)
    bpy.data.materials.remove(named)

    class Typed(dict):
        msfs_material_type = 'NONE'

    assert all(materials.is_not_rendered(Typed(msfs_material_type=kind))  # the custom property, without the exporter
               for kind in ('msfs_invisible', 'msfs_environment_occluder', 'msfs_collision'))
    assert not materials.is_not_rendered(Typed(msfs_material_type='msfs_glass')) and not materials.is_not_rendered(Typed())

    # A kept material goes last and says so; a Check All result replaces the estimate's verdict
    keep = table[0][1]
    setattr(keep, uv_marks.KEEP_UVS_PROP, True)
    assert materials.need_table(settings)[-1][1] == keep
    calls = []
    materials.FSS_PT_MaterialsByNeed.draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
    lines = [kwargs.get('text') for name, _args, kwargs in calls if name == 'label']
    assert lines[-2:] == [keep.name, f'texture {uv_marks.texture_size(keep)}: kept'], lines
    setattr(keep, uv_marks.KEEP_UVS_PROP, False)
    uv_marks._results[keep.name] = {'set': keep.name, 'mode': 'overflow', 'fits_8192': True, 'k': 1.5, 'needed_size': 8192,
                                    'size': 4096, 'written': False}
    calls = []
    materials.FSS_PT_MaterialsByNeed.draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
    lines = [(kwargs.get('text'), kwargs.get('icon')) for name, _args, kwargs in calls if name == 'label']
    assert lines[1] == (keep.name, materials.ICON_WARNING), lines
    assert lines[2][0].endswith(': needs x1.50: 8192 x 8192 (checked)'), lines
    del uv_marks._results[keep.name]
    assert used_icons <= icons, sorted(used_icons - icons)

    def operators(calls):
        return [kwargs.get('text') or args[0] for name, args, kwargs in calls if name == 'operator']

    # Shared across zones: one icon on each zone line, after that line's label, then Select Objects for all of them
    shared = [call for call in details['MAT_SHARED'] if call[0] in ('label', 'operator')]
    zone_icons = [index for index, (name, args, kwargs) in enumerate(shared) if name == 'operator'
                  and args[0] == materials.FSS_OT_MaterialsSelect.bl_idname and kwargs['properties'].in_zone]
    assert [shared[index][2]['properties'].zone for index in zone_icons] == ['@ZONE_AFT', '@ZONE_FWD'], shared
    assert all(shared[index][2]['text'] == '' and shared[index][2]['icon'] == 'RESTRICT_SELECT_OFF'
               and shared[index][2]['properties'].material == 'MAT_SHARED' for index in zone_icons), shared
    assert [shared[index - 1][2]['text'].split(':')[0] for index in zone_icons] == ['AFT', 'FWD'], shared
    assert operators(details['MAT_SHARED'])[-2:] == ['Select Objects', 'Check All'], operators(details['MAT_SHARED'])
    # One zone: Select Objects does the same, so no icon
    assert operators(details['MAT_INST']) == ['fss.materials_refresh', 'Select Objects', 'Check All'], \
        operators(details['MAT_INST'])
    tips = {materials.FSS_OT_MaterialsSelect.description(bpy.context, SimpleNamespace(in_zone=in_zone))
            for in_zone in (False, True)}
    assert len(tips) == 2, tips
    assert operators(details['MAT_NO_SLOT']) == ['fss.materials_refresh', 'Check All'], operators(details['MAT_NO_SLOT'])
    # A material never used that an object holds: the button to find it, and the count
    assert operators(details['MAT_SHADOWED']) == ['fss.materials_refresh', 'Select Objects', 'Check All'], \
        operators(details['MAT_SHADOWED'])
    assert '1 hold it in a slot no face uses' in [kwargs.get('text') for name, _args, kwargs in details['MAT_SHADOWED']
                                                  if name == 'label']
    labels = [kwargs.get('text') for name, _args, kwargs in details['MAT_EST'] if name == 'label']
    assert any(text and text.startswith('about ') and text.endswith(' px square (estimate, no visibility data)')
               for text in labels), labels
    print(f"PASS: test_draw ({len(settings.rows)} rows and their details, By Texture Need per material, no write while drawing, "
          f"{len(used_icons)} icons valid)")


def test_no_texture():
    """A tag with No Texture: a material only its objects use leaves By Texture Need at the next Refresh; one other
    object keeps it listed; hidden users count; the main list keeps every material."""
    o = build_scene()
    scene = bpy.context.scene
    settings = scene.fss_materials
    for obj in (o['inst1'], o['inst2'], o['fwd_a'], o['hidden']):
        tags.set_tags(obj, ['SCREEN'])
    bpy.ops.fss.materials_refresh()

    def listed():
        return {row.name for row, _material in materials.need_table(settings)}

    assert {'MAT_INST', 'MAT_SHARED', 'MAT_HIDDEN'} <= listed(), listed()
    assert not any(row.no_texture for row in settings.rows)
    bpy.ops.fss.tag_toggle_no_texture(tag='SCREEN')
    assert 'MAT_INST' in listed()  # shows at the next Refresh
    bpy.ops.fss.materials_refresh()
    no_texture = {row.name for row in settings.rows if row.no_texture}
    assert no_texture == {'MAT_INST', 'MAT_HIDDEN'}, no_texture  # MAT_SHARED has an object without the tag
    assert not ({'MAT_INST', 'MAT_HIDDEN'} & listed()) and 'MAT_SHARED' in listed(), listed()
    assert {'MAT_INST', 'MAT_HIDDEN', 'MAT_NO_SLOT'} <= {row.name for row in settings.rows}
    assert not settings.rows['MAT_NO_SLOT'].no_texture  # never used, so nothing says it needs no texture
    bpy.ops.fss.tag_toggle_no_texture(tag='SCREEN')
    bpy.ops.fss.materials_refresh()
    assert 'MAT_INST' in listed()
    print("PASS: test_no_texture (only tagged users leave By Texture Need, a mixed material stays, hidden users count, "
          "main list unchanged, shown at the next Refresh)")


def test_keep_uvs():
    """Decisions 13 and 14: the active material box draws the Keep UVs checkbox (Material.fss_uv_keep_uvs, as in
    Packing); a kept material shows 'kept' instead of the estimate, read when drawing, so without Refresh."""
    o = build_scene()
    bpy.ops.fss.materials_refresh()
    settings = bpy.context.scene.fss_materials
    material = o['mat']['MAT_EST']
    settings.active = settings.rows.find('MAT_EST')
    row = materials.active_row(settings)

    def draw():
        calls = []
        materials.FSS_PT_Materials.draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
        labels = [kwargs.get('text') or '' for name, _args, kwargs in calls if name == 'label']
        props = [(args, kwargs.get('text')) for name, args, kwargs in calls if name == 'prop' and args[0] == material]
        return labels, props

    def list_text():
        calls = []
        materials.FSS_UL_Materials.draw_item(None, bpy.context, _Layout(calls), settings, row, 0, settings, 'active',
                                             settings.active)
        return [kwargs.get('text') for name, _args, kwargs in calls if name == 'label'][-1]

    def packing():
        """What the Packing section draws for the same material (selected and active)."""
        context = SimpleNamespace(selected_objects=[o['est']], active_object=o['est'],
                                  window_manager=bpy.context.window_manager)
        calls = []
        uv_marks._draw_texture_sets(_Layout(calls), context)
        labels = [kwargs.get('text') or '' for name, _args, kwargs in calls if name == 'label']
        props = [args for name, args, kwargs in calls if name == 'prop' and args[1] == uv_marks.KEEP_UVS_PROP]
        return labels, props

    # Not kept: the estimate, the checkbox on the material's Keep UVs property
    assert not getattr(material, uv_marks.KEEP_UVS_PROP)
    labels, props = draw()
    assert any(text.startswith('about ') for text in labels), labels
    assert not any(text.startswith('kept') for text in labels), labels
    assert props == [((material, uv_marks.KEEP_UVS_PROP), 'Keep UVs')], props
    assert not list_text().endswith('kept'), list_text()
    pack_labels, pack_props = packing()
    assert pack_props == [(material, uv_marks.KEEP_UVS_PROP)], pack_props
    assert 'kept' not in pack_labels, pack_labels

    # Ticked (set as the click does), no Refresh: kept, no estimate, in the box, the list row and Packing alike
    before = snapshot(settings)
    setattr(material, uv_marks.KEEP_UVS_PROP, True)
    labels, props = draw()
    assert snapshot(settings) == before, "the panel wrote while drawing (kept)"
    kept_line = [text for text in labels if text.startswith('kept')]
    assert kept_line == ['kept (Keep UVs): no estimate'], labels
    assert not any(text.startswith('about ') or 'estimate,' in text for text in labels), labels
    assert any(text.endswith('  kept') for text in labels), labels  # the Texture line
    assert props == [((material, uv_marks.KEEP_UVS_PROP), 'Keep UVs')], props
    assert list_text().endswith('  kept'), list_text()
    pack_labels, _pack_props = packing()
    assert 'kept' in pack_labels, pack_labels
    assert uv_marks.last_result_text(material) == 'kept'

    # Unticked again: the estimate comes back, still without Refresh
    setattr(material, uv_marks.KEEP_UVS_PROP, False)
    labels, _props = draw()
    assert any(text.startswith('about ') for text in labels) and not any(text.startswith('kept') for text in labels)
    assert snapshot(settings) == before, "the panel wrote while drawing (unkept)"
    print(f"PASS: test_keep_uvs (checkbox on {uv_marks.KEEP_UVS_PROP}; '{kept_line[0]}' without Refresh, list row and "
          f"Packing show kept; estimate back when unticked; no write while drawing)")


def fss_extras_keys(value, path=''):
    """Every key starting with fss_ inside any extras of the glTF, with where it was found."""
    hits = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == 'extras' and isinstance(item, dict):
                hits += [f"{path}/{name}" for name in item if name.startswith('fss_')]
            hits += fss_extras_keys(item, f"{path}/{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            hits += fss_extras_keys(item, f"{path}[{index}]")
    return hits


def test_gltf_leak():
    if SCRATCH_DIR.exists():
        shutil.rmtree(SCRATCH_DIR)
    SCRATCH_DIR.mkdir(parents=True)
    build_scene()
    bpy.ops.fss.materials_refresh()
    assert len(bpy.context.scene.fss_materials.rows) > 0
    bpy.context.scene['artist_scene_note'] = 1  # a plain custom property: shows that extras were written at all
    path = SCRATCH_DIR / 'materials_extras.gltf'
    bpy.ops.export_scene.gltf(filepath=str(path), export_format='GLTF_SEPARATE', use_visible=True, export_extras=True)
    text = path.read_text(encoding='utf-8')
    gltf = json.loads(text)
    hits = fss_extras_keys(gltf)
    assert 'artist_scene_note' in text, "export_extras wrote no custom properties: the leak check would prove nothing"
    assert 'fss_materials' not in text and not hits, hits
    print(f"PASS: test_gltf_leak ({len(gltf.get('nodes', []))} nodes, no fss_ key in the extras)")


def test_refresh_on_open():
    """On opening a file, Zones & Merge Tree, Materials, Scan Names and LOD Counts refresh; never in background."""
    from fss_blender_tools import autorefresh
    build_scene()
    scene = bpy.context.scene
    scene.fss_materials.rows.clear()
    scene.fss_materials.scanned = False
    scene.fss_merge.scanned = False
    scene.fss_name_check.scanned = False
    scene.fss_lod_settings.scanned = False
    scene.fss_lod_settings.hide_sizes = (0.0,) * 7
    ran = autorefresh.refresh_all()
    assert ran == list(autorefresh.REFRESHES), ran
    assert scene.fss_materials.scanned and len(scene.fss_materials.rows) > 0
    assert scene.fss_merge.scanned and scene.fss_name_check.scanned
    assert scene.fss_lod_settings.scanned and scene.fss_lod_settings.hide_sizes[1] > 0, list(scene.fss_lod_settings.hide_sizes)
    assert autorefresh._on_load_post in bpy.app.handlers.load_post
    autorefresh._on_load_post()  # background: schedules nothing
    assert not bpy.app.timers.is_registered(autorefresh._refresh_timer)
    print(f"PASS: test_refresh_on_open ({', '.join(ran)}; no timer in background)")


def main():
    test_rows()
    test_visibility()
    test_kinds(with_exporter=True)
    test_select()
    test_draw()
    test_no_texture()
    test_keep_uvs()
    test_gltf_leak()
    test_refresh_on_open()
    test_kinds(with_exporter=False)
    print("ALL TESTS PASSED")


main()
