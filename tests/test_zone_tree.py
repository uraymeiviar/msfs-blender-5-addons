"""Zones & Merge Tree: zone rows, merge groups below them, @NOMERGE_ rows, Unzoned, nesting flags, the zone row
editing the zone empty's own density mark (uv_marks, decision 108), nearest_zone(), and that no fss_ key reaches the
glTF.

To run:
G:\\e-jets-e2\\tools\\blender\\blender.exe -b --factory-startup --python tests/test_zone_tree.py
"""

import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import addon_utils
import bmesh
import bpy

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
from fss_blender_tools import merge, tags, uv_marks  # noqa: E402

for name in ADDONS:
    addon_utils.enable(name, default_set=True)
    assert Path(sys.modules[name].__file__).resolve().is_relative_to(REPO_ROOT), sys.modules[name].__file__

SCRATCH_DIR = REPO_ROOT / 'tests' / '_work' / 'zone_tree_scratch'


def new_empty(name, parent=None):
    obj = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(obj)
    obj.parent = parent
    return obj


def new_cube(name, parent=None):
    mesh = bpy.data.meshes.new(name + "_Mesh")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=0.1)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.parent = parent
    return obj


def build_scene():
    """Two zones, nested groups, a @NOMERGE_ child, an unzoned group, a zone inside a group and one inside a zone."""
    bpy.ops.wm.read_homefile(use_empty=True)
    o = {}
    o['root'] = new_empty("EMPTY_ROOT_TEST")
    o['fwd'] = new_empty("@ZONE_FWD", o['root'])
    o['panel'] = new_empty("@MERGE_PANEL", o['fwd'])
    o['p1'] = new_cube("PANEL_SHELL", o['panel'])
    o['screen'] = new_cube("@NOMERGE_SCREEN", o['panel'])
    o['knob'] = new_empty("@MERGE_KNOB", o['panel'])
    o['k1'] = new_cube("KNOB_CAP", o['knob'])
    o['loose'] = new_cube("LOOSE_PART", o['fwd'])
    o['hidden_group'] = new_empty("@MERGE_HIDDEN", o['fwd'])
    o['hidden_part'] = new_cube("HIDDEN_PART", o['fwd'])
    o['aft'] = new_empty("@ZONE_AFT", o['root'])
    o['shelf'] = new_empty("@MERGE_SHELF", o['aft'])
    o['s1'] = new_cube("SHELF_BOARD", o['shelf'])
    o['inner'] = new_empty("@ZONE_INNER", o['aft'])
    o['box'] = new_empty("@MERGE_BOX", o['inner'])
    o['b1'] = new_cube("BOX_LID", o['box'])
    o['stray'] = new_empty("@MERGE_STRAY", o['root'])
    o['t1'] = new_cube("STRAY_PART", o['stray'])
    o['bad'] = new_empty("@ZONE_BAD", o['stray'])
    o['z1'] = new_cube("BAD_PART", o['bad'])
    bpy.context.view_layer.update()
    o['hidden_group'].hide_set(True)
    o['hidden_part'].hide_set(True)
    return o


def test_tree_rows():
    o = build_scene()
    assert bpy.ops.fss.merge_refresh() == {'FINISHED'}
    items = bpy.context.scene.fss_merge.items
    rows = [(item.kind, item.name, item.depth) for item in items]
    expected = [
        ('ZONE', 'AFT', 0), ('GROUP', 'SHELF', 1),
        ('ZONE', 'BAD', 0),
        ('ZONE', 'FWD', 0), ('GROUP', 'PANEL', 1), ('NOMERGE', 'SCREEN', 2), ('GROUP', 'KNOB', 2),
        ('ZONE', 'INNER', 0), ('GROUP', 'BOX', 1),
        ('UNZONED', 'Unzoned', 0), ('GROUP', 'STRAY', 1),
    ]
    assert rows == expected, rows
    by_name = {(item.kind, item.name): item for item in items}
    flags = {name: by_name[('ZONE', name)].flag for name in ('AFT', 'BAD', 'FWD', 'INNER')}
    assert flags == {'AFT': '', 'BAD': 'inside @MERGE_STRAY', 'FWD': '', 'INNER': 'inside @ZONE_AFT'}, flags
    counts = {name: (by_name[('ZONE', name)].groups, by_name[('ZONE', name)].objects, by_name[('ZONE', name)].merged)
              for name in ('AFT', 'BAD', 'FWD', 'INNER')}
    # Meshes, before and after. FWD: PANEL_SHELL, SCREEN, KNOB_CAP, LOOSE_PART (the hidden part is not counted), each
    # a mesh of its own after the merge too; BAD: its part merges away into STRAY, outside the zone
    assert counts == {'AFT': (1, 1, 1), 'BAD': (0, 1, 0), 'FWD': (2, 4, 4), 'INNER': (1, 1, 1)}, counts
    assert by_name[('UNZONED', 'Unzoned')].groups == 1
    for name in ('AFT', 'BAD', 'FWD', 'INNER'):
        assert by_name[('ZONE', name)].zone == o[name.lower()], name
    assert by_name[('NOMERGE', 'SCREEN')].root == "@NOMERGE_SCREEN"
    # Merge-group rows keep their content
    panel = by_name[('GROUP', 'PANEL')]
    assert (panel.root, panel.objects, panel.kept) == ("@MERGE_PANEL", 1, 2), (panel.root, panel.objects, panel.kept)

    # Clicking a row selects that object; the Unzoned row selects nothing
    settings = bpy.context.scene.fss_merge
    settings.active = rows.index(('ZONE', 'FWD', 0))
    assert bpy.context.view_layer.objects.active == o['fwd'] and o['fwd'].select_get()
    settings.active = rows.index(('NOMERGE', 'SCREEN', 2))
    assert bpy.context.view_layer.objects.active == o['screen'] and not o['fwd'].select_get()
    settings.active = rows.index(('UNZONED', 'Unzoned', 0))
    assert bpy.context.view_layer.objects.active == o['screen'] and o['screen'].select_get()
    print(f"PASS: test_tree_rows ({len(rows)} rows)")


def test_zone_mark():
    o = build_scene()
    zone = o['fwd']
    assert not hasattr(bpy.types.Object, 'fss_zone_density'), "the separate zone property is gone (decision 108)"
    assert uv_marks.own_density(zone) is None
    # A write through the row's zone pointer lands on the empty's own mark, without Refresh
    bpy.ops.fss.merge_refresh()
    row = next(item for item in bpy.context.scene.fss_merge.items if item.kind == 'ZONE' and item.name == 'FWD')
    setattr(row.zone, uv_marks.OWN_PROP, True)
    setattr(row.zone, uv_marks.MAX_PROP, 2.5)
    setattr(row.zone, uv_marks.MIN_PROP, 2.5)
    assert uv_marks.own_density(zone) == (2.5, 2.5), uv_marks.own_density(zone)
    # Everything below takes the zone's factor, times the scene freedom
    (low, high), source = uv_marks.density(o['k1'])
    assert abs(low - 0.9 * 2.5) < 1e-6 and abs(high - 1.1 * 2.5) < 1e-6 and source == zone, (low, high, source)
    print("PASS: test_zone_mark")


def test_nearest_zone():
    o = build_scene()
    cases = {
        'fwd': 'fwd', 'panel': 'fwd', 'k1': 'fwd', 'screen': 'fwd', 'aft': 'aft', 's1': 'aft',
        'inner': 'inner', 'b1': 'inner', 'bad': 'bad', 'z1': 'bad', 'root': None, 'stray': None, 't1': None,
    }
    for key, zone_key in cases.items():
        got = merge.nearest_zone(o[key])
        assert got == (o[zone_key] if zone_key else None), (key, got)
    assert merge.nearest_zone(None) is None
    print(f"PASS: test_nearest_zone ({len(cases)} objects)")


class _Layout:
    """Records what a panel or list row draws (background Blender has no UI to draw into)."""

    def __init__(self, calls):
        self.calls = calls

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if name == 'operator':
                return SimpleNamespace()
            return self if name in ('row', 'column', 'box') else None
        return call


def test_draw_smoke():
    o = build_scene()
    setattr(o['fwd'], uv_marks.OWN_PROP, True)
    bpy.ops.fss.merge_refresh()
    settings = bpy.context.scene.fss_merge
    texts = []
    for index, item in enumerate(settings.items):
        calls = []
        merge.FSS_UL_MergeTree.draw_item(None, bpy.context, _Layout(calls), settings, item, 0, settings, "active",
                                         index)
        texts.append([kwargs.get('text') for name, _args, kwargs in calls if name == 'label' and kwargs.get('text')])
        props = [(args[0], args[1]) for name, args, _kwargs in calls if name == 'prop']
        mark = [(item.zone, name) for name in (uv_marks.OWN_PROP, uv_marks.MIN_PROP, uv_marks.MAX_PROP)]
        assert props == (mark if item.kind == 'ZONE' else []), (item.name, props)
        assert item.kind != 'ZONE' or item.zone == o[item.name.lower()], item.name
    assert texts[2] == ["BAD (inside @MERGE_STRAY)", "1 -> 0 obj"], texts[2]
    assert texts[5] == ["SCREEN (stays separate)"], texts[5]
    assert texts[9] == ["Unzoned: 1 group(s) outside every @ZONE_ empty"], texts[9]
    assert merge.FSS_PT_Merge.bl_label == "Zones & Merge Tree"
    for index in range(len(settings.items)):
        settings.active = index
        calls = []
        merge.FSS_PT_Merge.draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
        assert any(name == 'template_list' for name, _args, _kwargs in calls)
    print(f"PASS: test_draw_smoke ({len(settings.items)} rows and their details)")


def build_pick_scene():
    """One group with several materials, a transparent part, UV warnings, and every kind of part kept out."""
    bpy.ops.wm.read_homefile(use_empty=True)
    bpy.context.scene.fss_merge.skip_tags = "SCREEN"
    zone = new_empty("@ZONE_FWD")
    root = new_empty("@MERGE_MIX", zone)
    o = {'root': root}
    red, blue = bpy.data.materials.new("RED"), bpy.data.materials.new("BLUE")
    glass = bpy.data.materials.new("GLASS")
    glass.msfs_alpha_mode = 'BLEND'
    for name, materials, uv_maps in (("A", [red], ["UVMap"]), ("B", [blue], ["OTHER"]),
                                     ("C", [red, glass], ["UVMap", "UV2", "UV3"])):
        o[name] = new_cube(name, root)
        for material in materials:
            o[name].data.materials.append(material)
        for uv_map in uv_maps:
            o[name].data.uv_layers.new(name=uv_map)
    o['C'].data.polygons[0].material_index = 1
    o['anim1'] = new_cube("ANIM1", root)
    o['anim2'] = new_cube("ANIM2", root)
    for key in ('anim1', 'anim2'):
        o[key].keyframe_insert("location", frame=1)
    # Below an animated part: moves with it, so it is not a part of the group's walk at all
    o['below'] = new_cube("BELOW_ANIM", o['anim1'])
    o['below'].data.materials.append(red)
    o['tagged'] = new_cube("TAGGED", root)
    tags.set_tags(o['tagged'], ["SCREEN"])
    o['nomerge'] = new_cube("@NOMERGE_PART", root)
    o['inner'] = new_empty("@MERGE_INNER", root)
    o['hidden'] = new_cube("HIDDEN_RED", root)
    o['hidden'].data.materials.append(red)
    bpy.context.view_layer.update()
    o['hidden'].hide_set(True)
    return o


def selected_names():
    return sorted(obj.name for obj in bpy.context.view_layer.objects if obj.select_get())


def test_group_picks():
    o = build_pick_scene()
    bpy.ops.fss.merge_refresh()
    item = next(item for item in bpy.context.scene.fss_merge.items if item.kind == 'GROUP' and item.name == 'MIX')
    picks = {(pick.what, pick.value, pick.index): pick.count for pick in item.picks}
    assert picks == {
        ('MATERIAL', 'RED', 0): 2, ('MATERIAL', 'BLUE', 0): 1, ('MATERIAL', 'GLASS', 0): 1,
        ('TRANSPARENT', '', 0): 1,
        ('UV', 'UVMap', 0): 2, ('UV', 'OTHER', 0): 1, ('UV', 'UV3', 2): 1,
        ('KEPT', 'animated', 0): 2, ('KEPT', 'tag SCREEN', 0): 1, ('KEPT', '@NOMERGE_ node', 0): 1,
        ('KEPT', 'own @MERGE_ group', 0): 1,
    }, picks

    def select(what, value="", index=0, **options):
        return bpy.ops.fss.merge_select(root=o['root'].name, what=what, value=value, index=index, **options)

    # Each row selects exactly its objects, replacing the selection, and the first becomes active. Neither the hidden
    # part with the same material nor the part below an animated one is picked
    cases = (
        (('MATERIAL', 'RED'), ["A", "C"]), (('MATERIAL', 'BLUE'), ["B"]), (('TRANSPARENT',), ["C"]),
        (('UV', 'OTHER'), ["B"]), (('UV', 'UV3', 2), ["C"]), (('KEPT', 'animated'), ["ANIM1", "ANIM2"]),
        (('KEPT', 'tag SCREEN'), ["TAGGED"]), (('KEPT', '@NOMERGE_ node'), ["@NOMERGE_PART"]),
        (('KEPT', 'own @MERGE_ group'), ["@MERGE_INNER"]),
    )
    for args, expected in cases:
        assert select(*args) == {'FINISHED'}, args
        assert selected_names() == expected, (args, selected_names())
        assert bpy.context.view_layer.objects.active.name in expected, args

    # Extending keeps what is selected; a click takes Shift from the event
    select('MATERIAL', 'BLUE')
    select('KEPT', 'animated', extend=True)
    assert selected_names() == ["ANIM1", "ANIM2", "B"], selected_names()
    probe = SimpleNamespace(extend=False, execute=lambda context: {'FINISHED'})
    merge.FSS_OT_MergeSelect.invoke(probe, bpy.context, SimpleNamespace(shift=True))
    assert probe.extend is True

    # The selection comes from the scene as it is now, not from the list of the last Refresh
    o['A'].data.materials[0] = bpy.data.materials['BLUE']
    assert select('MATERIAL', 'RED') == {'FINISHED'}
    assert selected_names() == ["C"], selected_names()
    o['C'].data.materials[0] = bpy.data.materials['BLUE']
    before = selected_names()
    assert select('MATERIAL', 'RED') == {'CANCELLED'}
    assert selected_names() == before, "a row that finds nothing leaves the selection alone"
    try:
        bpy.ops.fss.merge_select(root="GONE", what='MATERIAL', value='RED')
        raise AssertionError("a deleted group must be reported")
    except RuntimeError as error:
        assert "press Refresh" in str(error), error

    # Refreshed, the details draw a button per row with the row's own settings; a clean group keeps its plain UV label
    bpy.ops.fss.merge_refresh()
    settings = bpy.context.scene.fss_merge
    settings.active = next(index for index, item in enumerate(settings.items) if item.name == 'MIX')
    calls = []
    merge.FSS_PT_Merge.draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
    texts = [kwargs['text'] for name, args, kwargs in calls
             if name == 'operator' and args[0] == merge.FSS_OT_MergeSelect.bl_idname]
    assert "animated  2 obj" in texts and "BLUE  3 obj" in texts, texts
    assert "Transparent parts become MIX_TRANSPARENT  1 obj" in texts and "UV map 3: UV3  1 obj" in texts, texts
    icons = [kwargs.get('icon') for name, _args, kwargs in calls
             if name == 'label' and kwargs.get('text', '').startswith("UV maps")]
    assert icons == ['ERROR'], icons

    bpy.ops.wm.read_homefile(use_empty=True)
    zone = new_empty("@ZONE_FWD")
    clean = new_empty("@MERGE_CLEAN", zone)
    part = new_cube("PART", clean)
    part.data.uv_layers.new(name="UVMap")
    bpy.ops.fss.merge_refresh()
    settings = bpy.context.scene.fss_merge
    settings.active = next(index for index, item in enumerate(settings.items) if item.name == 'CLEAN')
    assert not [pick for pick in settings.items[settings.active].picks if pick.what == 'UV']
    calls = []
    merge.FSS_PT_Merge.draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
    icons = [kwargs.get('icon') for name, _args, kwargs in calls
             if name == 'label' and kwargs.get('text', '').startswith("UV maps")]
    assert icons == ['GROUP_UVS'], icons
    print(f"PASS: test_group_picks ({len(cases)} rows)")


def build_totals_scene():
    """One zone: a split group, a group with a transparent slot no face uses, a group whose only problem is its UV
    names, a group with faces without a material, kept parts, a loose part, and a hidden part with a material of its
    own."""
    bpy.ops.wm.read_homefile(use_empty=True)
    red, glass = bpy.data.materials.new("RED"), bpy.data.materials.new("GLASS")
    glass.msfs_alpha_mode = 'BLEND'
    zone = new_empty("@ZONE_FWD")
    o = {'split': new_empty("@MERGE_SPLIT", zone), 'unused': new_empty("@MERGE_UNUSED", zone),
         'uvs': new_empty("@MERGE_UVS", zone), 'none': new_empty("@MERGE_NONE", zone)}
    for name, parent, materials, uv_map in (("A", 'split', [red], ""), ("G", 'split', [red, glass], ""),
                                            ("U", 'unused', [red, glass], ""), ("V", 'unused', [red], ""),
                                            ("P", 'uvs', [red], "UVMap"), ("Q", 'uvs', [red], "OTHER"),
                                            ("X", 'none', [red], ""), ("Y", 'none', [], "")):
        o[name] = new_cube(name, o[parent])
        for material in materials:
            o[name].data.materials.append(material)
        if uv_map:
            o[name].data.uv_layers.new(name=uv_map)
    o['G'].data.polygons[0].material_index = 1
    o['nomerge'] = new_cube("@NOMERGE_N", o['uvs'])
    o['anim'] = new_cube("ANIM", o['split'])
    o['anim'].keyframe_insert("location", frame=1)
    o['loose'] = new_cube("LOOSE", zone)
    o['loose'].data.materials.append(bpy.data.materials.new("BLUE"))
    o['hidden'] = new_cube("HIDDEN", zone)
    o['hidden'].data.materials.append(bpy.data.materials.new("HIDDEN_MAT"))
    # Meshes without faces are not counted, loose, in a group, or as the only part of a group
    for name, parent in (("FACELESS_LOOSE", zone), ("FACELESS_MEMBER", o['uvs']),
                         ("FACELESS_ONLY", new_empty("@MERGE_FACELESS", zone))):
        obj = bpy.data.objects.new(name, bpy.data.meshes.new(name + "_Mesh"))
        bpy.context.scene.collection.objects.link(obj)
        obj.parent = parent
    bpy.context.view_layer.update()
    o['hidden'].hide_set(True)
    return o


def test_totals():
    build_totals_scene()
    bpy.ops.fss.merge_refresh()
    settings = bpy.context.scene.fss_merge
    by_name = {item.name: item for item in settings.items}
    # A, G, U, V, P, Q, X, Y, @NOMERGE_N, ANIM, LOOSE -> SPLIT, SPLIT_TRANSPARENT, UNUSED, UVS, NONE, N, ANIM, LOOSE
    assert (by_name['FWD'].objects, by_name['FWD'].merged) == (11, 8), (by_name['FWD'].objects, by_name['FWD'].merged)
    # As in the export: UV names alone and faces without a material warn, a slot no face uses does not
    assert [item.name for item in settings.items if merge._row_warns(item)] == ['NONE', 'SPLIT', 'UVS']
    unused = by_name['UNUSED']
    assert (unused.material_count, unused.transparent) == (1, False), (unused.material_count, unused.transparent)
    picks = {(pick.what, pick.value): pick.count for pick in by_name['NONE'].picks}
    assert picks == {('MATERIAL', 'RED'): 1, ('MATERIAL', ''): 1}, picks
    assert bpy.ops.fss.merge_select(root="@MERGE_NONE", what='MATERIAL', value="") == {'FINISHED'}
    assert selected_names() == ["Y"], selected_names()

    def row_icons(item):
        calls = []
        merge.FSS_UL_MergeTree.draw_item(None, bpy.context, _Layout(calls), settings, item, 0, settings, "active", 0)
        return [kwargs.get('icon') for name, _args, kwargs in calls if name == 'label']

    assert 'ERROR' in row_icons(by_name['UVS'])
    assert 'SHADING_BBOX' in row_icons(by_name['FWD'])
    icons = bpy.types.UILayout.bl_rna.functions['label'].parameters['icon'].enum_items
    assert 'SHADING_BBOX' in icons.keys()
    settings.active = list(settings.items).index(by_name['FWD'])
    calls = []
    merge.FSS_PT_Merge.draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
    labels = [kwargs.get('text') for name, _args, kwargs in calls if name == 'label']
    # Neither the hidden part's material nor faces without a material are counted as a material of the scene
    assert "1 zone  5 merge  1 no-merge  3 warnings  3 materials" in labels, labels
    assert not hasattr(merge, 'FSS_OT_MergePreview')

    # The count after the merge is what an export writes: mesh nodes below the zone
    if SCRATCH_DIR.exists():
        shutil.rmtree(SCRATCH_DIR)
    SCRATCH_DIR.mkdir(parents=True)
    path = SCRATCH_DIR / "totals.gltf"
    bpy.ops.export_scene.gltf(filepath=str(path), export_format='GLTF_SEPARATE', use_visible=True)
    nodes = json.loads(path.read_text(encoding='utf-8'))['nodes']

    def meshes_below(index):
        node = nodes[index]
        return ([node['name']] if 'mesh' in node else []) + [name for child in node.get('children', [])
                                                             for name in meshes_below(child)]

    zone_index = next(index for index, node in enumerate(nodes) if node['name'] == 'ZONE_FWD')
    exported = sorted(meshes_below(zone_index))
    assert len(exported) == by_name['FWD'].merged, exported
    assert 'SPLIT_TRANSPARENT' in exported and 'UNUSED_TRANSPARENT' not in exported, exported

    # A merged mesh named like a node that stays warns, and the details say so
    bpy.ops.wm.read_homefile(use_empty=True)
    root = new_empty("@MERGE_CLASH", new_empty("@ZONE_FWD"))
    new_cube("PART", root)
    new_cube("CLASH", root).keyframe_insert("location", frame=1)
    bpy.ops.fss.merge_refresh()
    settings = bpy.context.scene.fss_merge
    settings.active = next(index for index, item in enumerate(settings.items) if item.kind == 'GROUP')
    item = settings.items[settings.active]
    assert item.name_clash == "CLASH" and merge._row_warns(item), item.name_clash
    calls = []
    merge.FSS_PT_Merge.draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
    assert any(kwargs.get('text', '').startswith("CLASH: named like") for name, _args, kwargs in calls if name == 'label')
    print(f"PASS: test_totals (zone 11 -> 8 meshes, export {len(exported)})")


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
    results = {}
    for extras in (True, False):
        o = build_scene()
        # The registered density mark on the zone empty, texture size and margin on a material
        setattr(o['fwd'], uv_marks.OWN_PROP, True)
        setattr(o['fwd'], uv_marks.MAX_PROP, 2.5)
        setattr(o['fwd'], uv_marks.MIN_PROP, 2.5)
        o['fwd']['artist_note'] = 1  # a plain custom property: shows that extras were written at all
        # FSS keys on a material and on mesh data, beside the scene's registered fss_merge and fss_viewport_lod
        mesh_obj = next(obj for obj in bpy.context.scene.objects if obj.type == 'MESH' and obj.visible_get())
        mat = bpy.data.materials.new('ZONE_LEAK_MAT')
        mat['fss_probe'] = 1
        mat['artist_mat_note'] = 1
        mat.fss_uv_texture_size = '2048'
        mat.fss_uv_margin_px = 12
        mesh_obj.data.materials.append(mat)
        mesh_obj.data['fss_probe'] = 1
        path = SCRATCH_DIR / f"zones_extras_{int(extras)}.gltf"
        bpy.ops.export_scene.gltf(filepath=str(path), export_format='GLTF_SEPARATE', use_visible=True,
                                  export_extras=extras)
        text = path.read_text(encoding='utf-8')
        gltf = json.loads(text)
        names = {node.get('name') for node in gltf.get('nodes', [])}
        assert 'ZONE_FWD' in names, sorted(names)
        results[extras] = ('fss_uv_' in text, fss_extras_keys(gltf),
                           'artist_note' in text and 'artist_mat_note' in text)
        print(f"  export_extras={extras}: {len(gltf.get('nodes', []))} nodes, fss_uv_ in file: "
              f"{results[extras][0]}, fss_ keys in extras: {results[extras][1]}, custom properties written: "
              f"{results[extras][2]}")
    # With Include Extras, Blender 5.2 also writes registered properties; the FSS export hooks drop every fss_ key
    # from the extras of nodes, meshes, materials and the scene, and keep the artist's own custom properties
    assert results[True][2], "export_extras=True wrote no custom properties: the leak check would prove nothing"
    for extras in (True, False):
        in_text, hits, _custom = results[extras]
        assert not in_text and not hits, f"fss_ keys reached the glTF (export_extras={extras}): {hits}"
    print("PASS: test_gltf_leak")


def main():
    test_tree_rows()
    test_zone_mark()
    test_nearest_zone()
    test_draw_smoke()
    test_group_picks()
    test_totals()
    test_gltf_leak()
    print("ALL TESTS PASSED")


main()
