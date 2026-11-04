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
from mathutils import Matrix

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
from fss_blender_tools import lod_model, lod_rules, merge, tags, uv_marks  # noqa: E402

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
            return self if name in ('row', 'column', 'box', 'split') else None
        return call


def test_tags_panel():
    bpy.ops.wm.read_homefile(use_empty=True)
    carrier = new_cube("CARRIER")
    tags.set_tags(carrier, ["LIT"])
    tags.set_tags(new_cube("OTHER"), ["GLASS"])
    tags.set_keep_tags(bpy.context.scene, ["LIT"])
    bpy.context.view_layer.objects.active = carrier

    def draw(selected):
        for obj in bpy.context.view_layer.objects:
            obj.select_set(obj is carrier and selected)
        calls = []
        tags.FSS_PT_Tags.draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
        return calls

    def operators(calls, idname):
        return [kwargs for name, args, kwargs in calls if name == 'operator' and args[0] == idname]

    # The active object's box only with that object selected; nothing is highlighted without a selection
    calls = draw(False)
    assert not [call for call in calls if call[0] == 'box']
    assert not any(kwargs['depress'] for kwargs in operators(calls, tags.FSS_OT_TagSelect.bl_idname))

    calls = draw(True)
    assert [call for call in calls if call[0] == 'box']
    # The tag name is the only select button, highlighted for the tag of the selected object
    names = {kwargs['text']: kwargs for kwargs in operators(calls, tags.FSS_OT_TagSelect.bl_idname)}
    assert set(names) == {"GLASS (1)", "LIT (1)"}, names
    assert names["LIT (1)"]['depress'] and names["LIT (1)"]['emboss']
    assert not names["GLASS (1)"]['depress'] and not names["GLASS (1)"]['emboss']

    # Icons only, with a real icon for each Keep state
    keep = operators(calls, tags.FSS_OT_TagToggleKeep.bl_idname)
    assert [(kwargs['text'], kwargs['icon'], kwargs['depress']) for kwargs in keep] == [
        ("", 'UNPINNED', False), ("", 'PINNED', True)], keep
    known = bpy.types.UILayout.bl_rna.functions['operator'].parameters['icon'].enum_items
    assert 'PINNED' in known and 'UNPINNED' in known

    # Per row: rename before the name; merge, Keep, the two AO toggles, Invisible, Animated, Whole, No Texture, a gap,
    # delete
    order = [args[0] if name == 'operator' else name for name, args, _kwargs in calls
             if name in ('operator', 'separator', 'split')]
    row = order[len(order) - order[::-1].index('split'):]
    assert row == [tags.FSS_OT_TagRemove.bl_idname, tags.FSS_OT_TagAdd.bl_idname, tags.FSS_OT_TagRename.bl_idname,
                   tags.FSS_OT_TagSelect.bl_idname, tags.FSS_OT_TagToggleSkipMerge.bl_idname,
                   tags.FSS_OT_TagToggleKeep.bl_idname, tags.FSS_OT_TagToggleAONoOccluder.bl_idname,
                   tags.FSS_OT_TagToggleAOSkipBake.bl_idname, tags.FSS_OT_TagToggleInvisible.bl_idname,
                   tags.FSS_OT_TagToggleAnimated.bl_idname, tags.FSS_OT_TagToggleWhole.bl_idname,
                   tags.FSS_OT_TagToggleNoTexture.bl_idname, 'separator', tags.FSS_OT_TagDelete.bl_idname], row

    # The AO toggles start off and answer per object: each setting alone, and only for objects carrying the tag
    scene = bpy.context.scene
    other = bpy.data.objects["OTHER"]
    assert all((tags.is_ao_occluder(obj, scene), tags.is_ao_baked(obj, scene)) == (True, True)
               for obj in (carrier, other))
    assert [(kwargs['icon'], kwargs['depress']) for kwargs in
            operators(calls, tags.FSS_OT_TagToggleAONoOccluder.bl_idname)] == [
        ('GHOST_DISABLED', False), ('GHOST_DISABLED', False)]
    assert [(kwargs['icon'], kwargs['depress']) for kwargs in
            operators(calls, tags.FSS_OT_TagToggleAOSkipBake.bl_idname)] == [
        ('RESTRICT_RENDER_OFF', False), ('RESTRICT_RENDER_OFF', False)]
    assert all(icon in known for icon in ('GHOST_ENABLED', 'GHOST_DISABLED', 'RESTRICT_RENDER_ON',
                                          'RESTRICT_RENDER_OFF'))

    bpy.ops.fss.tag_toggle_ao_no_occluder(tag="LIT")
    assert (tags.is_ao_occluder(carrier, scene), tags.is_ao_baked(carrier, scene)) == (False, True)
    assert (tags.is_ao_occluder(other, scene), tags.is_ao_baked(other, scene)) == (True, True)
    bpy.ops.fss.tag_toggle_ao_skip_bake(tag="LIT")
    assert (tags.is_ao_occluder(carrier, scene), tags.is_ao_baked(carrier, scene)) == (False, False)
    bpy.ops.fss.tag_toggle_ao_skip_bake(tag="GLASS")
    assert (tags.is_ao_occluder(other, scene), tags.is_ao_baked(other, scene)) == (True, False)
    calls = draw(True)
    # Rows are sorted by name: GLASS, then LIT
    assert [(kwargs['icon'], kwargs['depress']) for kwargs in
            operators(calls, tags.FSS_OT_TagToggleAONoOccluder.bl_idname)] == [
        ('GHOST_DISABLED', False), ('GHOST_ENABLED', True)]
    assert [(kwargs['icon'], kwargs['depress']) for kwargs in
            operators(calls, tags.FSS_OT_TagToggleAOSkipBake.bl_idname)] == [
        ('RESTRICT_RENDER_ON', True), ('RESTRICT_RENDER_ON', True)]

    # The Invisible mark, alone: off at first, on for objects with the tag, the AO answers unchanged
    assert not tags.is_marked_invisible(carrier, scene) and not tags.is_marked_invisible(other, scene)
    assert [(kwargs['icon'], kwargs['depress']) for kwargs in
            operators(calls, tags.FSS_OT_TagToggleInvisible.bl_idname)] == [('HIDE_OFF', False), ('HIDE_OFF', False)]
    assert 'HIDE_ON' in known and 'HIDE_OFF' in known
    bpy.ops.fss.tag_toggle_invisible(tag="LIT")
    assert tags.is_marked_invisible(carrier, scene) and not tags.is_marked_invisible(other, scene)
    assert tags.is_ao_baked(other, scene) is False
    calls = draw(True)
    assert [(kwargs['icon'], kwargs['depress']) for kwargs in
            operators(calls, tags.FSS_OT_TagToggleInvisible.bl_idname)] == [('HIDE_OFF', False), ('HIDE_ON', True)]

    # The Animated mark, the same way, with one icon and the highlight
    assert not tags.is_marked_animated(carrier, scene)
    assert 'ACTION' in known
    bpy.ops.fss.tag_toggle_animated(tag="LIT")
    assert tags.is_marked_animated(carrier, scene) and not tags.is_marked_animated(other, scene)
    calls = draw(True)
    assert [(kwargs['icon'], kwargs['depress']) for kwargs in
            operators(calls, tags.FSS_OT_TagToggleAnimated.bl_idname)] == [('ACTION', False), ('ACTION', True)]

    # The Whole setting, the same way
    assert not tags.is_whole(carrier, scene)
    assert 'MESH_CUBE' in known
    bpy.ops.fss.tag_toggle_whole(tag="LIT")
    assert tags.is_whole(carrier, scene) and not tags.is_whole(other, scene)
    calls = draw(True)
    assert [(kwargs['icon'], kwargs['depress']) for kwargs in
            operators(calls, tags.FSS_OT_TagToggleWhole.bl_idname)] == [('MESH_CUBE', False), ('MESH_CUBE', True)]

    # No Texture, the same way; it also means no AO bake for the object, without pressing Skip-AO-Bake, and the object
    # still occludes. Measured on OTHER, whose tag GLASS has no AO setting of its own after this press
    assert 'TEXTURE' in known
    bpy.ops.fss.tag_toggle_ao_skip_bake(tag="GLASS")
    assert tags.is_ao_baked(other, scene) and not tags.needs_no_texture(other, scene)
    bpy.ops.fss.tag_toggle_no_texture(tag="GLASS")
    assert tags.needs_no_texture(other, scene) and not tags.needs_no_texture(carrier, scene)
    assert not tags.is_ao_baked(other, scene) and tags.is_ao_occluder(other, scene)
    assert "GLASS" not in tags.get_mark_tags(scene, tags.AO_SKIP_BAKE_PROP)
    calls = draw(True)
    assert [(kwargs['icon'], kwargs['depress']) for kwargs in
            operators(calls, tags.FSS_OT_TagToggleNoTexture.bl_idname)] == [('TEXTURE', True), ('TEXTURE', False)]
    bpy.ops.fss.tag_toggle_no_texture(tag="GLASS")
    assert tags.is_ao_baked(other, scene) and not tags.needs_no_texture(other, scene)
    bpy.ops.fss.tag_toggle_ao_skip_bake(tag="GLASS")
    bpy.ops.fss.tag_toggle_no_texture(tag="LIT")

    # A second press turns it off; Rename and Delete Tag carry the settings along
    bpy.ops.fss.tag_toggle_ao_skip_bake(tag="GLASS")
    assert tags.is_ao_baked(other, scene)
    bpy.ops.fss.tag_rename(tag="LIT", new_name="LAMP")
    assert tags.has_tag(carrier, "LAMP")
    assert scene.fss_ao_no_occluder_tags == "LAMP" and scene.fss_ao_skip_bake_tags == "LAMP"
    assert scene.fss_invisible_tags == "LAMP" and tags.is_marked_invisible(carrier, scene)
    assert scene.fss_animated_tags == "LAMP" and tags.is_marked_animated(carrier, scene)
    assert scene.fss_whole_tags == "LAMP" and tags.is_whole(carrier, scene)
    assert scene.fss_no_texture_tags == "LAMP" and tags.needs_no_texture(carrier, scene)
    assert not tags.is_ao_occluder(carrier, scene) and not tags.is_ao_baked(carrier, scene)
    bpy.ops.fss.tag_delete(tag="LAMP")
    assert scene.fss_ao_no_occluder_tags == "" and scene.fss_ao_skip_bake_tags == ""
    assert scene.fss_invisible_tags == "" and not tags.is_marked_invisible(carrier, scene)
    assert scene.fss_animated_tags == "" and not tags.is_marked_animated(carrier, scene)
    assert scene.fss_whole_tags == "" and not tags.is_whole(carrier, scene)
    assert scene.fss_no_texture_tags == "" and not tags.needs_no_texture(carrier, scene)
    assert tags.is_ao_occluder(carrier, scene) and tags.is_ao_baked(carrier, scene)
    print("PASS: test_tags_panel")


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
    assert "Objects: 11 -> 8 (-27%)" in labels, labels

    # The scene total counts what lies outside every zone too, and matches every mesh node of the export
    bpy.ops.wm.read_homefile(use_empty=True)
    zone = new_empty("@ZONE_FWD")
    inside = new_empty("@MERGE_IN", zone)
    outside = new_empty("@MERGE_OUT")
    for name, parent in (("A", inside), ("B", inside), ("LOOSE_IN", zone), ("C", outside), ("D", outside),
                         ("LOOSE_OUT", None)):
        new_cube(name, parent)
    hidden = new_cube("HIDDEN", zone)
    bpy.context.view_layer.update()
    hidden.hide_set(True)
    bpy.ops.fss.merge_refresh()
    settings = bpy.context.scene.fss_merge
    zone_row = next(item for item in settings.items if item.kind == 'ZONE')
    assert (zone_row.objects, zone_row.merged) == (3, 2), (zone_row.objects, zone_row.merged)
    assert merge._objects_text(settings) == "Objects: 6 -> 4 (-33%)", merge._objects_text(settings)
    path = SCRATCH_DIR / "totals_scene.gltf"
    bpy.ops.export_scene.gltf(filepath=str(path), export_format='GLTF_SEPARATE', use_visible=True)
    mesh_nodes = [node['name'] for node in json.loads(path.read_text(encoding='utf-8'))['nodes'] if 'mesh' in node]
    assert len(mesh_nodes) == settings.objects_after, mesh_nodes

    # Nothing to count, nothing merged, and a merge that adds a transparent mesh
    assert merge._objects_text(SimpleNamespace(objects_before=0, objects_after=0)) == "Objects: 0 -> 0 (0%)"
    assert merge._objects_text(SimpleNamespace(objects_before=4, objects_after=4)) == "Objects: 4 -> 4 (0%)"
    assert merge._objects_text(SimpleNamespace(objects_before=1, objects_after=2)) == "Objects: 1 -> 2 (+100%)"

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
        bpy.context.scene.fss_ao_no_occluder_tags = 'LEAK_PROBE'
        bpy.context.scene.fss_ao_skip_bake_tags = 'LEAK_PROBE'
        bpy.context.scene.fss_invisible_tags = 'LEAK_PROBE'
        bpy.context.scene.fss_animated_tags = 'LEAK_PROBE'
        bpy.context.scene.fss_whole_tags = 'LEAK_PROBE'
        bpy.context.scene.fss_no_texture_tags = 'LEAK_PROBE'
        path = SCRATCH_DIR / f"zones_extras_{int(extras)}.gltf"
        bpy.ops.export_scene.gltf(filepath=str(path), export_format='GLTF_SEPARATE', use_visible=True,
                                  export_extras=extras)
        text = path.read_text(encoding='utf-8')
        gltf = json.loads(text)
        names = {node.get('name') for node in gltf.get('nodes', [])}
        assert 'ZONE_FWD' in names, sorted(names)
        assert 'LEAK_PROBE' not in text
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


def test_stray():
    bpy.ops.wm.read_homefile(use_empty=True)
    scene = bpy.context.scene
    zone = new_empty("@ZONE_FWD")
    knob = new_empty("@NOMERGE_KNOB", zone)
    new_cube("IN_NESTED", new_empty("@MERGE_NESTED", knob))  # merges, though a @NOMERGE_ is above it
    new_cube("BELOW_KNOB", knob)
    group = new_empty("@MERGE_G", zone)
    new_cube("MEMBER", group)
    new_cube("@NOMERGE_OWN", group)
    # A mesh's animation moves that mesh: its children do not count as animated
    moving = new_cube("MOVING", group)
    moving.keyframe_insert("location", frame=1)
    new_cube("GRAND_BELOW", new_cube("CHILD_MOVING", moving))
    new_cube("LOOSE", zone)
    new_cube("OUTSIDE")
    new_cube("LOOSE_ANIM", zone).keyframe_insert("location", frame=1)
    # The armrest: a part directly under an animated empty is animated, its own child is stray again
    pivot = new_empty("PIVOT", zone)
    pivot.keyframe_insert("location", frame=1)
    new_cube("GRAND", new_cube("DIRECT", pivot))
    new_cube("PART_UNDER", new_empty("@MERGE_UNDER", pivot))  # merges
    # Moves through the model XML only: stray until a tag marks it, a mesh or an empty
    new_cube("XML_GRAND", new_cube("XML_CHILD", new_cube("XML_PART", zone)))
    tags.set_tags(bpy.data.objects["XML_PART"], ["XML"])
    xml_empty = new_empty("XML_EMPTY", zone)
    tags.set_tags(xml_empty, ["XML"])
    new_cube("XML_DIRECT", xml_empty)
    tags.set_tags(new_cube("DONT_MERGE", zone), ["SCREEN"])
    scene.fss_merge.skip_tags = "SCREEN"
    tags.set_tags(new_cube("COLLIDER", zone), ["INVIS"])
    new_empty("JUST_EMPTY", zone)
    faceless = bpy.data.objects.new("FACELESS", bpy.data.meshes.new("FACELESS_Mesh"))
    scene.collection.objects.link(faceless)
    hidden = new_cube("HIDDEN", zone)
    bpy.context.view_layer.update()
    hidden.hide_set(True)

    def press(below, extend=False):
        result = bpy.ops.fss.merge_select_stray(below=below, extend=extend)
        return result, selected_names()

    # Nothing marked yet: the collider and the XML parts count as stray
    bpy.ops.fss.merge_refresh()
    settings = scene.fss_merge
    counts = (settings.stray_count, settings.stray_below_count)
    assert counts == (8, 3), counts
    # DIRECT, LOOSE_ANIM and MOVING are animated, so in neither list
    assert press(False) == ({'FINISHED'}, ["COLLIDER", "GRAND", "LOOSE", "OUTSIDE", "XML_CHILD", "XML_DIRECT",
                                           "XML_GRAND", "XML_PART"]), selected_names()
    assert press(True) == ({'FINISHED'}, ["BELOW_KNOB", "CHILD_MOVING", "GRAND_BELOW"]), selected_names()
    assert press(False, extend=True)[1] == ["BELOW_KNOB", "CHILD_MOVING", "COLLIDER", "GRAND", "GRAND_BELOW", "LOOSE",
                                            "OUTSIDE", "XML_CHILD", "XML_DIRECT", "XML_GRAND",
                                            "XML_PART"], selected_names()

    # The marks: the marked mesh, and the child of the marked empty, leave the list; the count waits for a Refresh
    bpy.ops.fss.tag_toggle_invisible(tag="INVIS")
    bpy.ops.fss.tag_toggle_animated(tag="XML")
    assert press(False)[1] == ["GRAND", "LOOSE", "OUTSIDE", "XML_CHILD", "XML_GRAND"], selected_names()
    assert settings.stray_count == 8
    bpy.ops.fss.merge_refresh()
    counts = (settings.stray_count, settings.stray_below_count)
    assert counts == (5, 3), counts

    # The merge does not read the Animated mark: a marked part still merges
    tags.set_tags(bpy.data.objects["MEMBER"], ["XML"])
    assert bpy.data.objects["MEMBER"] in {obj for group in merge.plan(
        scene, lambda obj: obj.visible_get(), {"SCREEN"}) for obj in group.members}

    # The buttons, below the Objects line, each with its own tooltip
    calls = []
    merge.FSS_PT_Merge.draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
    texts = [kwargs.get('text') for name, args, kwargs in calls if name == 'operator'
             and args[0] == merge.FSS_OT_MergeSelectStray.bl_idname]
    assert texts == ["Stray: 5", "Below @NOMERGE_: 3"], texts
    tips = {merge.FSS_OT_MergeSelectStray.description(bpy.context, SimpleNamespace(below=below))
            for below in (False, True)}
    assert len(tips) == 2, tips

    # Nothing left to select leaves the selection alone
    names = ["GRAND", "LOOSE", "OUTSIDE", "XML_CHILD", "XML_GRAND"]
    press(False)
    for name in names:
        tags.set_tags(bpy.data.objects[name], ["INVIS"])
    assert press(False) == ({'CANCELLED'}, names), selected_names()
    print("PASS: test_stray")


def new_pieces(name, sizes):
    """One mesh object of separate cubes in a row, with these sizes in metres."""
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    for index, size in enumerate(sizes):
        bmesh.ops.create_cube(bm, size=size, matrix=Matrix.Translation((index * 2.0, 0, 0)))
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def test_whole():
    """The Whole tag: no loose piece is dropped on its own, in the export and in the counts; the object still leaves."""
    bpy.ops.wm.read_homefile(use_empty=True)
    context, scene = bpy.context, bpy.context.scene
    objects = {name: new_pieces(name, sizes) for name, sizes in (
        ("PLAIN", (1.0, 0.02, 0.02)), ("WHOLE", (1.0, 0.02, 0.02)), ("KEPT", (1.0, 0.02, 0.02)),
        ("WHOLE_MARKED", (1.0, 0.02, 0.02)))}
    # Three small pieces close together: the object as a whole is below the cut-off
    tiny = bpy.data.meshes.new("WHOLE_TINY")
    bm = bmesh.new()
    for index in range(3):
        bmesh.ops.create_cube(bm, size=0.02, matrix=Matrix.Translation((index * 0.04, 0, 0)))
    bm.to_mesh(tiny)
    bm.free()
    objects["WHOLE_TINY"] = bpy.data.objects.new("WHOLE_TINY", tiny)
    scene.collection.objects.link(objects["WHOLE_TINY"])
    context.view_layer.update()
    for name in ("WHOLE", "WHOLE_MARKED", "WHOLE_TINY"):
        tags.set_tags(objects[name], ["INTACT"])
    tags.set_tags(objects["KEPT"], ["HOLD"])
    objects["WHOLE_MARKED"][lod_model.HIDE_KEY] = 5
    bpy.ops.fss.tag_toggle_whole(tag="INTACT")
    bpy.ops.fss.tag_toggle_keep(tag="HOLD")

    def run():
        plan = lod_model.build_plan(context)
        parts = {part.name: part for part in plan['parts']}
        decision = lod_rules.decide(plan['parts'], 3, plan['diameter'], plan['table'], cutoff=0.5)
        kept = [obj for obj in scene.objects if obj.name in decision.present]
        return parts, decision, lod_model.drop_small_pieces(context, kept, parts, 0.5)

    # The tag reaches the plan; it never decides presence: the tiny object leaves by size, all at once
    plan = lod_model.build_plan(context)
    parts = {part.name: part for part in plan['parts']}
    assert [name for name in sorted(parts) if parts[name].whole] == ["WHOLE", "WHOLE_MARKED", "WHOLE_TINY"]
    assert not parts["PLAIN"].whole and not parts["KEPT"].whole
    verts_before = {name: len(obj.data.vertices) for name, obj in objects.items()}

    # The counts, before the export copies are changed: only PLAIN loses pieces
    stats = lod_model.estimate_scene_stats(context, plan)
    level = next(index for index, value in enumerate(stats['lods']) if value['loose_pieces'])
    listed = {item[0] for item in stats['lods'][level]['loose_pieces']}
    assert listed == {"PLAIN"}, listed

    parts, decision, dropped = run()
    assert "WHOLE_TINY" in decision.by_size, decision.by_size
    assert {"PLAIN", "WHOLE", "KEPT", "WHOLE_MARKED"} <= decision.present, decision.present
    assert dropped == 2, dropped
    after = {name: len(obj.data.vertices) for name, obj in objects.items()}
    assert after["PLAIN"] == 8 and verts_before["PLAIN"] == 24, after
    assert all(after[name] == verts_before[name] for name in ("WHOLE", "KEPT", "WHOLE_MARKED", "WHOLE_TINY")), after

    # A mark still applies to a Whole object
    assert "WHOLE_MARKED" in lod_rules.decide(plan['parts'], 5, plan['diameter'], plan['table'], cutoff=0.5).by_mark

    # Turning it off gives the pieces back to the rule
    bpy.ops.fss.tag_toggle_whole(tag="INTACT")
    assert not any(part.whole for part in lod_model.build_plan(context)['parts'])
    assert run()[2] == 4
    print("PASS: test_whole")


def main():
    test_tree_rows()
    test_zone_mark()
    test_nearest_zone()
    test_tags_panel()
    test_draw_smoke()
    test_group_picks()
    test_totals()
    test_stray()
    test_whole()
    test_gltf_leak()
    print("ALL TESTS PASSED")


main()
