"""The FSS sidebar layout of material-management decision 16: the tab FSS MSFS Tools with the top-level panels in
pipeline order (Zones & Merge Tree, Materials with By Zone, Tags, Object LOD, Viewport LOD, LOD Settings with its
subpanels (decision 22), UV Auto Seam, UV Auto Packing (decision 26)), the tab FSS Tools with General, Empty Bounds, Heatmap, Checks (top-level, closed by default), Packing in the
UV editor's FSS MSFS Tools tab too, no other tab, and every panel drawing without errors. Object LOD draws the
selection, the active object's mark, "mixed" and the number row only for Hidden from / Visible from, without writing.

To run:
"<blender>" -b --factory-startup --python tests/test_panels.py
"""

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

REPO_ROOT = str(Path(__file__).resolve().parents[1])
while REPO_ROOT in sys.path:
    sys.path.remove(REPO_ROOT)
sys.path.insert(0, REPO_ROOT)

import fss_blender_tools  # noqa: E402

fss_blender_tools.register()

# idname: (label, parent idname or '', bl_order, category)
MSFS = 'FSS MSFS Tools'
TOOLS = 'FSS Tools'
EXPECTED = {
    'FSS_PT_merge': ("Zones & Merge Tree", '', 0, MSFS),
    'FSS_PT_materials': ("Materials", '', 1, MSFS),
    'FSS_PT_materials_by_zone': ("By Zone", 'FSS_PT_materials', 0, MSFS),
    'FSS_PT_tags': ("Tags", '', 2, MSFS),
    'FSS_PT_lod': ("Object LOD", '', 3, MSFS),
    'FSS_PT_lod_viewport': ("Viewport LOD", '', 4, MSFS),
    'FSS_PT_lod_settings': ("LOD Settings", '', 5, MSFS),
    'FSS_PT_lod_quota_hints': ("Quota and Hints", 'FSS_PT_lod_settings', 0, MSFS),
    'FSS_PT_lod_export': ("Export Settings", 'FSS_PT_lod_settings', 0, MSFS),
    'FSS_PT_lod_export_advanced': ("Advanced", 'FSS_PT_lod_export', 0, MSFS),
    'FSS_PT_uv_autoseam': ("UV Auto Seam", '', 6, MSFS),
    'FSS_PT_uv_marks': ("UV Auto Packing", '', 7, MSFS),
    'FSS_PT_visibility': ("Visibility Scoring", 'FSS_PT_uv_marks', 0, MSFS),
    'FSS_PT_tools': ("General", '', 0, TOOLS),
    'FSS_PT_empty_bounds': ("Empty Bounds", '', 1, TOOLS),
    'FSS_PT_uv_heatmap': ("Heatmap", '', 2, TOOLS),
    'FSS_PT_checks': ("Checks", '', 3, TOOLS),
}
# The panels of the tab FSS Tools are closed by default
DEFAULT_CLOSED = ('FSS_PT_tools', 'FSS_PT_empty_bounds', 'FSS_PT_uv_heatmap', 'FSS_PT_checks')
# The UV editor's sidebar: Packing again (UV journal decision 119), drawn by the same code
EXPECTED_IMAGE_EDITOR = {
    'FSS_PT_uv_marks_image': ("UV Auto Packing", '', 0, MSFS),
}


def fss_panels():
    """Every registered panel class of the add-on, whatever its tab, so a panel left in another tab is found. Classes of
    the purged deployed copy stay in __subclasses__ but are not registered."""
    return {cls.bl_idname: cls for cls in bpy.types.Panel.__subclasses__()
            if cls.__module__.startswith('fss_blender_tools') and cls.is_registered}


def test_layout():
    panels = fss_panels()
    for idname, (label, parent, order, category) in {**EXPECTED, **EXPECTED_IMAGE_EDITOR}.items():
        cls = panels.get(idname)
        space = 'IMAGE_EDITOR' if idname in EXPECTED_IMAGE_EDITOR else 'VIEW_3D'
        assert cls is not None, f"{idname} not registered"
        assert cls.bl_label == label, (idname, cls.bl_label, label)
        assert getattr(cls, 'bl_parent_id', '') == parent, (idname, getattr(cls, 'bl_parent_id', ''), parent)
        assert getattr(cls, 'bl_order', 0) == order, (idname, getattr(cls, 'bl_order', 0), order)
        assert cls.bl_category == category, (idname, cls.bl_category, category)
        assert getattr(bpy.types, idname, None) is not None, f"{idname} not in bpy.types"
        assert (cls.bl_space_type, cls.bl_region_type) == (space, 'UI'), (idname, cls.bl_space_type)
    assert bpy.types.FSS_PT_uv_marks.draw is bpy.types.FSS_PT_uv_marks_image.draw
    for idname in DEFAULT_CLOSED:
        assert 'DEFAULT_CLOSED' in getattr(panels[idname], 'bl_options', set()), idname
    # The group panel Utilities stays gone (decisions 15 and 16)
    assert not [cls for cls in panels.values() if cls.bl_label == 'Utilities']
    # Two tabs: no panel of the add-on elsewhere, and top-level orders without gaps or doubles in each tab
    # (FSS MSFS Tools 0..7, FSS Tools 0..3)
    other_tabs = sorted((idname, cls.bl_category) for idname, cls in panels.items()
                        if cls.bl_category not in (MSFS, TOOLS))
    assert not other_tabs, other_tabs
    for category, count in ((MSFS, 8), (TOOLS, 4)):
        orders = sorted(getattr(cls, 'bl_order', 0) for idname, cls in panels.items()
                        if cls.bl_space_type == 'VIEW_3D' and not getattr(cls, 'bl_parent_id', '')
                        and cls.bl_category == category)
        assert orders == list(range(count)), (category, orders)
    tools_tab = sorted(idname for idname, cls in panels.items() if cls.bl_category == TOOLS)
    assert tools_tab == sorted(DEFAULT_CLOSED), tools_tab
    # Every FSS panel is expected, and a subpanel sits in its parent's tab
    unexpected = sorted(set(panels) - set(EXPECTED) - set(EXPECTED_IMAGE_EDITOR))
    assert not unexpected, unexpected
    for idname, cls in panels.items():
        parent = getattr(cls, 'bl_parent_id', '')
        if parent:
            assert panels[parent].bl_category == cls.bl_category, (idname, cls.bl_category, panels[parent].bl_category)
    def top(category):
        return ', '.join(label for _o, label in sorted(
            (getattr(cls, 'bl_order', 0), cls.bl_label) for cls in panels.values()
            if cls.bl_space_type == 'VIEW_3D' and not getattr(cls, 'bl_parent_id', '') and cls.bl_category == category))
    print(f"PASS: test_layout ({len(panels)} panels; {MSFS}: {top(MSFS)}; {TOOLS}: {top(TOOLS)}, closed by default; "
          f"no Utilities; UV editor: {MSFS} > Packing)")


class _Layout:
    """Records what a panel draws (background Blender has no UI to draw into)."""

    def __init__(self, calls, alert=False):
        self.calls = calls
        self.alert = alert  # inherited by sub-layouts, as in Blender; recorded with each progress bar

    def __getattr__(self, name):
        def call(*args, **kwargs):
            if name == 'progress':
                kwargs['_alert'] = self.alert
            self.calls.append((name, args, kwargs))
            if name == 'operator':
                kwargs['_op'] = SimpleNamespace()  # panels set operator properties on it; kept for the checks
                return kwargs['_op']
            if name in ('row', 'column', 'box', 'split', 'grid_flow', 'column_flow'):
                return _Layout(self.calls, self.alert)
            return None
        return call


def test_draw_all():
    me = bpy.data.meshes.new('PANEL_TEST_MESH')
    me.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    obj = bpy.data.objects.new('PANEL_TEST', me)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    drawn = []
    for idname, cls in sorted(fss_panels().items()):
        if hasattr(cls, 'poll') and not cls.poll(bpy.context):
            continue
        calls = []
        cls.draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
        drawn.append(idname)
    seams = []
    bpy.types.FSS_PT_uv_autoseam.draw(SimpleNamespace(layout=_Layout(seams)), bpy.context)
    texts = [kwargs.get('text') for name, _args, kwargs in seams if name == 'operator']
    assert 'Skip Auto Seam' in texts, texts
    packing = []
    bpy.types.FSS_PT_uv_marks.draw(SimpleNamespace(layout=_Layout(packing)), bpy.context)
    texts = [kwargs.get('text') for name, _args, kwargs in packing if name == 'operator']
    assert 'Skip Auto Seam' not in texts, texts
    # Density marks are live fields with factor presets: no Apply, no Select Marked (decision 109)
    assert 'Apply' not in texts and 'Select Marked' not in texts and {'Lower', 'Higher'} <= set(texts), texts
    assert 'Check All' in texts, texts  # the packer (decision 115); Pack needs a material
    uv_editor = []
    bpy.types.FSS_PT_uv_marks_image.draw(SimpleNamespace(layout=_Layout(uv_editor)), bpy.context)
    assert [(name, kwargs.get('text')) for name, _args, kwargs in uv_editor] == [
        (name, kwargs.get('text')) for name, _args, kwargs in packing]
    checks_calls = []
    bpy.types.FSS_PT_checks.draw(SimpleNamespace(layout=_Layout(checks_calls)), bpy.context)
    ops = [args[0] for name, args, _kwargs in checks_calls if name == 'operator']
    assert 'fss.find_faces_without_area' in ops and 'fss.find_faces_without_uv_area' in ops, ops
    materials_calls = []
    bpy.types.FSS_PT_materials.draw(SimpleNamespace(layout=_Layout(materials_calls)), bpy.context)
    ops = [args[0] for name, args, _kwargs in materials_calls if name == 'operator']
    assert ops == ['fss.materials_refresh'], ops  # before the first Refresh: the button and a hint only
    steps = bpy.context.scene.fss_visibility.bl_rna.properties['states']
    assert steps.name == 'Animation Steps', steps.name
    print(f"PASS: test_draw_all ({len(drawn)} panels drawn; Skip Auto Seam in UV Auto Seam only; Packing without Apply and "
          "Select Marked, with Check All, the same in the UV editor; Find Faces Without Area and Find Faces Without UV "
          "Area in Checks; Refresh in Materials; 'Animation Steps')")


def _draw_object_lod():
    """Draw Object LOD; return (label texts, mark buttons as (text, depress), number buttons as (LOD shown, mode,
    level set, depress)), and check that drawing wrote nothing."""
    def snapshot():
        return (bpy.context.window_manager.fss_lod_pending,
                {obj.name: {key: obj[key] for key in obj.keys()} for obj in bpy.data.objects})
    before = snapshot()
    calls = []
    bpy.types.FSS_PT_lod.draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
    assert snapshot() == before, (before, snapshot())
    labels = [kwargs.get('text') for name, _args, kwargs in calls if name == 'label']
    ops = [(args[0], kwargs) for name, args, kwargs in calls if name == 'operator']
    marks = [(kwargs['text'], kwargs.get('depress', False)) for _idname, kwargs in ops
             if not kwargs['text'].isdigit()]
    numbers = [(int(kwargs['text']), kwargs['_op'].mode, kwargs['_op'].level, kwargs.get('depress', False))
               for idname, kwargs in ops if kwargs['text'].isdigit()]
    assert all(idname == 'fss.set_object_lod' for idname, kwargs in ops if kwargs['text'].isdigit()), ops
    assert [text for text, _d in marks] == ['Auto', 'Keep', 'Hidden from', 'Visible from'], marks
    return labels, marks, numbers


def _select(objects, active):
    for obj in bpy.context.view_layer.objects:
        obj.select_set(obj in objects)
    bpy.context.view_layer.objects.active = active


def _mixed(labels):
    return any('mixed' in (text or '') for text in labels)


def test_object_lod():
    """Object LOD (decision 22): the selection line, the active object's mark, "mixed", the number row only for
    Hidden from / Visible from, the pending choice set by fss.lod_pending and cleared by applying a mark. The row
    (decision 23) shows LOD0 to LOD6 lit where the object is visible; a click sets the last (Hidden from n + 1) or
    first (Visible from n) visible LOD."""
    from fss_blender_tools import lod_model
    wm = bpy.context.window_manager
    scene = bpy.context.scene
    objs = []
    for name in ('LOD_A', 'LOD_B'):
        obj = bpy.data.objects.new(name, None)
        scene.collection.objects.link(obj)
        objs.append(obj)
    a, b = objs
    wm.fss_lod_pending = 'NONE'

    # No selection, no active object
    _select([], None)
    labels, marks, numbers = _draw_object_lod()
    assert 'Select objects to mark them' in labels, labels
    assert not numbers and not any(d for _t, d in marks), (marks, numbers)

    # One object without a mark: Auto pressed, no number row
    _select([a], a)
    labels, marks, numbers = _draw_object_lod()
    assert 'Selected: 1 object (active: LOD_A)' in labels and 'Active object: Auto' in labels, labels
    assert [t for t, d in marks if d] == ['Auto'] and not numbers and not _mixed(labels), (labels, marks, numbers)

    # One object Hidden from 3: Hidden from pressed, the number row with 3 pressed
    a[lod_model.HIDE_KEY] = 3
    labels, marks, numbers = _draw_object_lod()
    assert 'Active object: Hidden from LOD3' in labels, labels
    assert [t for t, d in marks if d] == ['Hidden from'], marks
    assert numbers == [(lod, 'HIDE', min(lod + 1, 6), lod < 3) for lod in range(7)], numbers
    assert 'Visible in:' in labels, labels

    # Mixed selection: Hidden from 3 and Keep; the pressed buttons follow the active object
    b[lod_model.KEEP_KEY] = 1
    _select([a, b], b)
    labels, marks, numbers = _draw_object_lod()
    assert 'Selected: 2 objects (active: LOD_B)' in labels and 'Active object: Keep' in labels, labels
    assert _mixed(labels), labels
    assert [t for t, d in marks if d] == ['Keep'] and not numbers, (marks, numbers)
    # Hidden from 3 and Hidden from 4 are different marks too; two Hidden from 3 are not mixed
    del b[lod_model.KEEP_KEY]
    b[lod_model.HIDE_KEY] = 4
    assert _mixed(_draw_object_lod()[0])
    b[lod_model.HIDE_KEY] = 3
    assert not _mixed(_draw_object_lod()[0])

    # Pending Hidden from on an Auto object: Hidden from pressed, the number row with no number pressed
    del a[lod_model.HIDE_KEY]
    _select([a], a)
    assert bpy.ops.fss.lod_pending(mode='HIDE') == {'FINISHED'}
    assert wm.fss_lod_pending == 'HIDE'
    assert not any(key in a for key in (lod_model.HIDE_KEY, lod_model.SHOW_KEY, lod_model.KEEP_KEY)), dict(a)
    labels, marks, numbers = _draw_object_lod()
    assert [t for t, d in marks if d] == ['Hidden from'], marks
    assert numbers == [(lod, 'HIDE', min(lod + 1, 6), False) for lod in range(7)], numbers
    # Pending Visible from on a Hidden from 2 object: the row switches to Visible from
    a[lod_model.HIDE_KEY] = 2
    bpy.ops.fss.lod_pending(mode='SHOW')
    labels, marks, numbers = _draw_object_lod()
    assert [t for t, d in marks if d] == ['Visible from'], marks
    assert numbers == [(lod, 'SHOW', max(lod, 1), False) for lod in range(7)], numbers
    # A number applies the mark and clears the pending choice
    assert bpy.ops.fss.set_object_lod(mode='SHOW', level=2) == {'FINISHED'}
    assert wm.fss_lod_pending == 'NONE'
    assert lod_model.mark(a, lod_model.SHOW_KEY) == 2 and lod_model.HIDE_KEY not in a, dict(a)
    labels, marks, numbers = _draw_object_lod()
    assert [t for t, d in marks if d] == ['Visible from'], marks
    assert numbers == [(lod, 'SHOW', max(lod, 1), lod >= 2) for lod in range(7)], numbers
    # Auto applies at once and clears a pending choice too
    bpy.ops.fss.lod_pending(mode='HIDE')
    assert bpy.ops.fss.set_object_lod(mode='AUTO') == {'FINISHED'}
    assert wm.fss_lod_pending == 'NONE' and lod_model.SHOW_KEY not in a, dict(a)
    # Without a selection the pending choice cannot be made
    _select([], None)
    assert not bpy.ops.fss.lod_pending.poll()
    for obj in objs:
        bpy.data.objects.remove(obj)
    print("PASS: test_object_lod (no selection, one object, Hidden from 3, mixed selection, pending Hidden from / "
          "Visible from, a number applies and clears the pending choice, Auto clears it; drawing writes nothing)")



def test_exterior_diameter_message():
    """Export Settings of an interior without exterior diameter: one message, not two."""
    settings = bpy.context.scene.fss_lod_settings
    model_type, exterior = settings.model_type, settings.exterior_diameter
    settings.model_type = 'INTERIOR'
    settings.exterior_diameter = 0.0
    calls = []
    bpy.types.FSS_PT_lod_export.draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
    texts = [kwargs.get('text') or '' for name, _args, kwargs in calls if name == 'label']
    found = [text for text in texts if 'exterior diameter missing' in text.lower()]
    assert len(found) == 1, texts
    # Pad LOD Sphere To: the line under it names the diameter without padding (or asks for a Refresh)
    assert any(text.startswith('0 = no padding') or text.startswith('Without padding:') for text in texts), texts
    assert settings.bl_rna.properties['reference_size'].name == 'Pad LOD Sphere To'
    settings.model_type, settings.exterior_diameter = model_type, exterior
    print(f"PASS: test_exterior_diameter_message ('{found[0]}')")


def test_viewport_lod_excluded():
    """Viewport LOD: the Excluded row only while a preview is on (Off excludes nothing)."""
    scene = bpy.context.scene

    def excluded_shown():
        calls = []
        bpy.types.FSS_PT_lod_viewport.draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
        return any(name == 'prop' and 'fss_lod_preview_display' in args for name, args, _kwargs in calls)
    scene.fss_viewport_lod_auto = False
    scene.fss_viewport_lod = -1
    assert not excluded_shown()
    for level in (0, 3):
        scene.fss_viewport_lod = level
        assert excluded_shown(), level
    scene.fss_viewport_lod = -1
    scene.fss_viewport_lod_auto = True
    assert excluded_shown()
    scene.fss_viewport_lod_auto = False
    print("PASS: test_viewport_lod_excluded (hidden while Off; shown for LOD0, LOD3 and Auto)")


def _lod_snapshot():
    """What the LOD Settings panels read, to check that drawing writes nothing."""
    settings = bpy.context.scene.fss_lod_settings
    keys = ('scanned', 'write_count', 'counts', 'cutoffs', 'resolved_table', 'vertex_estimates', 'quotas',
            'quota_percents', 'over_quota', 'dropped_pieces', 'dropped_vertices', 'inspect_lod', 'preview_target')
    values = {key: getattr(settings, key) for key in keys}
    values = {key: tuple(value) if hasattr(value, '__len__') and not isinstance(value, str) else value
              for key, value in values.items()}
    values['hints'] = [(h.lod_level, h.kind, h.object_name, h.vertices) for h in settings.hints]
    values['viewport_lod'] = bpy.context.scene.fss_viewport_lod
    return values


def _draw_lod_panel(idname):
    """Draw a LOD Settings panel; return (label texts, progress bars as (factor, text, red)); drawing writes
    nothing."""
    before = _lod_snapshot()
    calls = []
    getattr(bpy.types, idname).draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
    assert _lod_snapshot() == before, (before, _lod_snapshot())
    labels = [kwargs.get('text') or '' for name, _args, kwargs in calls if name == 'label']
    bars = [(kwargs['factor'], kwargs['text'], kwargs['_alert']) for name, _args, kwargs in calls
            if name == 'progress']
    return labels, bars


def _cube(name, size, location):
    h = size / 2
    me = bpy.data.meshes.new(name)
    me.from_pydata([(x, y, z) for x in (-h, h) for y in (-h, h) for z in (-h, h)], [],
                   [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)])
    obj = bpy.data.objects.new(name, me)
    obj.location = location
    bpy.context.scene.collection.objects.link(obj)
    return obj


def test_lod_settings_bars():
    """LOD Settings and Quota and Hints (decision 25): a bar per written LOD full at LOD00's object count; the quota
    table (LOD, Vertices, Quota, Used bar red above 100 %, MSFS shows it from, "never" above 100 % of the screen);
    contributor bars as shares of the LOD's vertices; MSFS 2020 with LOD and Vertices only; drawing writes nothing."""
    from fss_blender_tools import lod_rules
    scene = bpy.context.scene
    settings = scene.fss_lod_settings
    objs = [_cube('BARS_BIG', 2.0, (0, 0, 0)), _cube('BARS_MID', 0.5, (1.5, 0, 0))]
    objs += [_cube(f'BARS_TINY_{i}', 0.001, (-1 + 0.2 * i, 1, 0)) for i in range(10)]
    scene.fss_viewport_lod_auto = False
    scene.fss_viewport_lod = -1
    settings.preview_target = 'fs24'
    assert bpy.ops.fss.lod_refresh() == {'FINISHED'}
    assert settings.scanned and settings.write_count >= 2, (settings.scanned, settings.write_count)
    counts = list(settings.counts)[:settings.write_count]

    # A: one bar per written LOD, factor count / LOD00 count; the share in brackets from LOD01 on
    labels, bars = _draw_lod_panel('FSS_PT_lod_settings')
    assert len(bars) == settings.write_count, bars
    for level, (factor, text, red) in enumerate(bars):
        assert abs(factor - counts[level] / counts[0]) < 1e-6, (level, factor, counts)
        assert text.startswith(f'{counts[level]:,} obj') and ('(' in text) == (level > 0) and not red, text
        assert f'LOD{level:02}' in labels, labels
    assert counts[1] < counts[0], counts  # the tiny cubes are below LOD01's cut-off
    assert any(text.startswith('hides < ') for text in labels), labels

    # B: the header sentence and the table columns; Used bars = min(percent / 100, 1)
    labels, bars = _draw_lod_panel('FSS_PT_lod_quota_hints')
    assert labels[:2] == ['A LOD is shown only when the model is large enough', 'on screen for its vertex count.'], \
        labels
    assert labels[2:7] == ['LOD', 'Vertices', 'Quota', 'Used', 'MSFS shows it from'], labels
    used = [bar for bar in bars if not bar[1].startswith('~')]
    assert len(used) == settings.write_count, used
    for level, (factor, text, red) in enumerate(used):
        pct = settings.quota_percents[level]
        assert abs(factor - min(pct / 100, 1)) < 1e-6 and text.endswith(' %') and red == (pct > 100), (level, used)
    assert 'Per LOD Vertex Contributors' in labels and 'Hints for LOD:' not in labels, labels
    assert not any(text.startswith('Largest contributors') for text in labels), labels

    # C: contributor bars, factor = vertices / the LOD's vertices
    total = settings.vertex_estimates[0]
    contributors = [h for h in settings.hints if h.lod_level == 0 and h.kind == 'CONTRIBUTOR'][:5]
    shares = [bar for bar in bars if bar[1].startswith('~')]
    assert contributors and len(shares) == len(contributors), (shares, len(contributors))
    for h, (factor, text, _red) in zip(contributors, shares):
        assert abs(factor - h.vertices / total) < 1e-6 and text.startswith(f'~{h.vertices:,} ('), (factor, text)

    # Above 100 % of the screen: "never (needs N %; table T %)", the Used bar full and red
    settings.vertex_estimates[0] = 5_000_000
    settings.quota_percents[0] = 2000.0
    effective = lod_rules.effective_min_sizes(settings.resolved_table, list(settings.vertex_estimates),
                                              settings.msfs_vertex_factor, settings.write_count)
    assert effective[0] > 1.0, effective
    labels, bars = _draw_lod_panel('FSS_PT_lod_quota_hints')
    never = [text for text in labels if text.startswith('never (needs ')]
    assert never == [f'never (needs {effective[0] * 100:.0f} %; table {settings.resolved_table[0] * 100:.0f} %)'], \
        (never, effective)
    assert bars[0] == (1.0, '2000 %', True), bars[0]
    assert any(text.endswith(', fallback') for text in labels), labels

    # MSFS 2020: LOD and Vertices only, no quota bars
    settings.preview_target = 'fs20'
    assert bpy.ops.fss.lod_refresh() == {'FINISHED'}
    labels, bars = _draw_lod_panel('FSS_PT_lod_quota_hints')
    assert 'LOD' in labels and 'Vertices' in labels, labels
    assert not {'Quota', 'Used', 'MSFS shows it from'} & set(labels), labels
    assert not [bar for bar in bars if not bar[1].startswith('~')], bars
    assert not any(text.startswith('never') or 'of screen' in text for text in labels), labels
    settings.preview_target = 'fs24'
    for obj in objs:
        bpy.data.objects.remove(obj)
    print(f"PASS: test_lod_settings_bars (objects {counts}, bars count / LOD00; quota table with Used bars, "
          f"'{never[0]}' and a red full bar above 100 %; {len(shares)} contributor bars as shares; MSFS 2020 with "
          "LOD and Vertices only; drawing writes nothing)")


def main():
    test_layout()
    test_draw_all()
    test_object_lod()
    test_viewport_lod_excluded()
    test_exterior_diameter_message()
    test_lod_settings_bars()
    print("ALL TESTS PASSED")


main()
