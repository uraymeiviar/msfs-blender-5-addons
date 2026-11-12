"""The FSS sidebar layout of material-management decision 16: the tab FSS MSFS Tools with the top-level panels in
pipeline order (Zones & Merge Tree, Materials with By Texture Need, Tags, Object LOD, Viewport LOD, LOD Settings with its
subpanels (decision 22), UV Auto Seam, UV Auto Packing (decision 26), AO Bake (auto-bake journal, decision 29)), the tab FSS Tools with General, Empty Bounds, Heatmap, Checks (top-level, closed by default), Packing in the
UV editor's FSS MSFS Tools tab too, no other tab, and every panel drawing without errors. Object LOD draws the
selection, the active object's mark, "mixed" and the number row only for Hidden from / Visible from, without writing.

To run:
"<blender>" -b --factory-startup --python tests/test_panels.py
"""

import math
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
    'FSS_PT_materials_by_need': ("By Texture Need", 'FSS_PT_materials', 0, MSFS),
    'FSS_PT_texture_sets': ("Texture Sets", 'FSS_PT_materials', 1, MSFS),
    'FSS_PT_tags': ("Tags", '', 2, MSFS),
    'FSS_PT_lod': ("Object LOD", '', 3, MSFS),
    'FSS_PT_lod_viewport': ("Viewport LOD", '', 4, MSFS),
    'FSS_PT_lod_settings': ("LOD Settings", '', 5, MSFS),
    'FSS_PT_lod_quota_hints': ("Hints", 'FSS_PT_lod_settings', 0, MSFS),
    'FSS_PT_lod_export': ("Export Settings", 'FSS_PT_lod_settings', 0, MSFS),
    'FSS_PT_lod_export_advanced': ("Advanced", 'FSS_PT_lod_export', 0, MSFS),
    'FSS_PT_uv_autoseam': ("UV Auto Seam", '', 6, MSFS),
    'FSS_PT_uv_marks': ("UV Auto Packing", '', 7, MSFS),
    'FSS_PT_visibility': ("Visibility Scoring", 'FSS_PT_uv_marks', 0, MSFS),
    'FSS_PT_uv_marks_results': ("Check Results", 'FSS_PT_uv_marks', 0, MSFS),
    'FSS_PT_uv_marks_advanced': ("Advanced", 'FSS_PT_uv_marks', 1, MSFS),
    'FSS_PT_ao_bake': ("AO Bake", '', 8, MSFS),
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
    'FSS_PT_uv_marks_image_results': ("Check Results", 'FSS_PT_uv_marks_image', 0, MSFS),
    'FSS_PT_uv_marks_image_advanced': ("Advanced", 'FSS_PT_uv_marks_image', 1, MSFS),
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
    # (FSS MSFS Tools 0..8, FSS Tools 0..3)
    other_tabs = sorted((idname, cls.bl_category) for idname, cls in panels.items()
                        if cls.bl_category not in (MSFS, TOOLS))
    assert not other_tabs, other_tabs
    for category, count in ((MSFS, 9), (TOOLS, 4)):
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
    # Density marks are live fields: no Apply, no Select Marked (decision 109), no presets (decision 134)
    assert 'Apply' not in texts and 'Select Marked' not in texts and not {'Lower', 'Higher'} & set(texts), texts
    assert 'Check' in texts, texts  # the packer (decision 115); Pack needs a material
    uv_editor = []
    bpy.types.FSS_PT_uv_marks_image.draw(SimpleNamespace(layout=_Layout(uv_editor)), bpy.context)
    assert [(name, kwargs.get('text')) for name, _args, kwargs in uv_editor] == [
        (name, kwargs.get('text')) for name, _args, kwargs in packing]
    checks_calls = []
    bpy.types.FSS_PT_checks.draw(SimpleNamespace(layout=_Layout(checks_calls)), bpy.context)
    ops = [args[0] for name, args, _kwargs in checks_calls if name == 'operator']
    assert 'fss.find_faces_without_area' in ops and 'fss.find_faces_without_uv_area' in ops, ops
    assert 'fss.find_animations_off_range' in ops, ops
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



def test_export_settings_one_table():
    """Export Settings: no Model Type, no Exterior Diameter, and the same table fields for every model."""
    settings = bpy.context.scene.fss_lod_settings
    assert 'model_type' not in settings.bl_rna.properties and 'exterior_diameter' not in settings.bl_rna.properties
    assert not hasattr(bpy.types, 'FSS_OT_LodEditTable') and 'lod_edit_table' not in dir(bpy.ops.fss)
    calls = []
    bpy.types.FSS_PT_lod_export.draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
    texts = [kwargs.get('text') or '' for name, _args, kwargs in calls if name == 'label']
    props = [args[1] for name, args, _kwargs in calls if name == 'prop']
    assert not any('exterior' in text.lower() for text in texts), texts
    assert not {'model_type', 'exterior_diameter'}.intersection(props), props
    # Pad LOD Sphere: a multiplier, 1 to 10; the line under it says what MSFS sees (or asks for a Refresh)
    assert any(text.startswith('MSFS sees:') or text.startswith('Press Refresh') for text in texts), texts
    prop = settings.bl_rna.properties['pad_factor']
    assert prop.name == 'Pad LOD Sphere Multiplier' and prop.hard_min == 1.0 and prop.hard_max == 10.0, prop
    calls = []
    bpy.types.FSS_PT_lod_export_advanced.draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
    props = [args[1] for name, args, _kwargs in calls if name == 'prop']
    assert props == ['msfs_vertex_factor'], props
    assert not {'min_sizes_fs24', 'min_sizes_fs20', 'preview_target', 'quotas', 'lowest_cutoff'} & \
        set(settings.bl_rna.properties.keys())
    # No sphere box list, even with the sphere shown; the toggle stays
    bpy.context.scene.fss_lod_show_sphere = True
    calls = []
    bpy.types.FSS_PT_lod_export.draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
    bpy.context.scene.fss_lod_show_sphere = False
    assert not any('box faces' in (kwargs.get('text') or '') for _name, _args, kwargs in calls), calls
    assert 'fss_lod_show_sphere' in [args[1] for name, args, _kwargs in calls if name == 'prop'], calls
    print("PASS: test_export_settings_one_table (no Model Type, Exterior Diameter or Preview Target; one table)")


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


def test_viewport_lod_view_quota():
    """LOD Settings, whatever the viewport preview: per written LOD its vertices, the quota at the view's screen size
    and a Used bar, no table values; the quota moves with the camera; the LOD MSFS shows is marked; drawing writes
    nothing."""
    from mathutils import Matrix, Vector
    from fss_blender_tools import lod, lod_rules
    scene = bpy.context.scene
    settings = scene.fss_lod_settings
    objs = [_cube('VIEWQ_BIG', 2.0, (0, 0, 0)), _cube('VIEWQ_MID', 0.5, (1.5, 0, 0))]
    scene.fss_viewport_lod_auto = False
    scene.fss_viewport_lod = -1
    assert bpy.ops.fss.lod_refresh() == {'FINISHED'}
    count = settings.write_count
    assert count >= 2, count
    saved_ratio = lod._auto_state['last_ratio']
    reduced = []

    def draw(ratio=None):
        if ratio is not None:
            lod._auto_state['last_ratio'] = ratio
        before = _lod_snapshot()
        calls = []
        bpy.types.FSS_PT_lod_settings.draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
        assert _lod_snapshot() == before
        reduced[:] = [(kwargs['factor'], kwargs['text']) for name, _args, kwargs in calls
                      if name == 'progress' and not kwargs['text'].endswith(' %')]
        return ([kwargs.get('text') or '' for name, _args, kwargs in calls if name == 'label'],
                [(kwargs['factor'], kwargs['text'], kwargs['_alert']) for name, _args, kwargs in calls
                 if name == 'progress' and kwargs['text'].endswith(' %')],
                [kwargs['text'].split()[0] for name, args, kwargs in calls
                 if name == 'operator' and args[0] == 'fss.lod_view_shown' and kwargs.get('depress')])

    # The same table for Off, a fixed LOD and Auto; the mark is what MSFS shows at this view, not the preview
    near = lod_rules.vertex_quota_at(1.33, settings.msfs_vertex_factor)
    effective = lod_rules.effective_min_sizes(settings.resolved_table, list(settings.vertex_estimates),
                                              settings.msfs_vertex_factor, count)
    expected = f'{lod_rules.lod_from_screen_ratio(1.33, effective, count):02}'
    results = []
    for level, auto in ((-1, False), (1, False), (1, True)):
        scene.fss_viewport_lod_auto = False
        scene.fss_viewport_lod = level
        scene.fss_viewport_lod_auto = auto
        labels, bars, marked = draw(1.33)
        assert all(text in labels for text in ('LOD', 'Vert/Obj', 'Used', 'ToReduce', 'Reduced')), (level, auto, labels)
        assert 'Quota' not in ' '.join(labels), labels
        assert f'This view: LOD{expected} (screen ratio 133.0%)' in labels, labels
        assert len(bars) == count, (labels, bars)
        assert marked == [expected], (marked, expected)
        results.append(bars)
    assert results[0] == results[1] == results[2], results
    scene.fss_viewport_lod_auto = False
    scene.fss_viewport_lod = -1
    for level, (factor, text, red) in enumerate(results[0]):
        pct = 100.0 * settings.vertex_estimates[level] / near
        assert abs(factor - min(pct / 100, 1)) < 1e-6 and text.endswith(' %') and red == (pct > 100), (level, bars)

    # Moved away: the quota falls; no row names a table value
    far = lod_rules.vertex_quota_at(0.05, settings.msfs_vertex_factor)
    labels, bars, _marked = draw(0.05)
    assert far < near and bars[0][1] == lod.format_percent(100.0 * settings.vertex_estimates[0] / far), (far, bars)
    assert not any(text.startswith('table ') for text in labels) and len(bars) == count, (labels, bars)

    # Reduce: what a more detailed LOD must lose; a dash on the LOD shown and below it
    saved = list(settings.vertex_estimates)
    settings.vertex_estimates[0] = near + 18648
    settings.vertex_estimates[1] = near - 60100
    labels, _bars, marked = draw(1.33)
    assert marked == ['01'], marked
    assert '18.65K' in labels, labels
    # A dash on the LOD shown and below it
    assert labels.count('-') == count - 1, labels
    # Vert./Obj and Reduced, per step and not cumulative; the cut-off beside the LOD number
    assert lod.format_count(1113993) == '1.11M' and lod.format_count(3481) == '3.48K', lod.format_count(3481)
    assert lod.format_count(532) == '532' and lod.format_count(999_999) == '1.00M'
    assert lod.format_step(3481, 2192) == '-1.29K' and lod.format_step(5, 5) == '0' and lod.format_step(5, 7) == '+2'
    verts, objects = settings.vertex_estimates, settings.counts
    assert f'{lod.format_count(verts[2])}/{lod.format_count(objects[2])}' in labels, labels
    # Reduced: the share of the previous LOD's vertices this step removed, the step as its text; LOD00 empty, a dash
    assert len(reduced) == count and reduced[0] == (0.0, '-'), reduced
    assert reduced[2][1] == f'{lod.format_step(verts[1], verts[2])}/{lod.format_step(objects[1], objects[2])}', reduced
    assert abs(reduced[2][0] - max(0, verts[1] - verts[2]) / verts[1]) < 1e-6, reduced
    assert f'02 <{lod.format_length(settings.cutoffs[2]).replace(" ", "")}' in labels, labels
    settings.vertex_estimates = saved

    # Viewport LOD holds only the viewport's settings
    calls = []
    bpy.types.FSS_PT_lod_viewport.draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
    texts = [kwargs.get('text') or '' for name, _args, kwargs in calls if name == 'label']
    assert 'Vert/Obj' not in texts and not any(name == 'progress' for name, _args, _kwargs in calls), texts
    assert 'msfs_quality' not in [args[1] for name, args, _kwargs in calls if name == 'prop'], calls

    # MSFS Quality: High by default; another setting moves the limit and what shows, and the counts stand
    assert settings.msfs_quality == 'HIGH'
    settings.vertex_estimates[0] = 300000
    settings.vertex_estimates[1] = 1000
    _labels, _bars, marked = draw(1.0)
    assert marked == ['01'], marked
    settings.msfs_quality = 'ULTRA'
    assert settings.scanned
    quota = lod_rules.vertex_quota_at(1.0, settings.msfs_vertex_factor, lod_rules.QUALITY_FACTORS['ULTRA'])
    labels, bars, marked = draw(1.0)
    assert marked == ['00'] and bars[0][1] == lod.format_percent(100.0 * 300000 / quota), (marked, bars)
    settings.msfs_quality = 'HIGH'
    settings.vertex_estimates = saved

    # The last LOD over the quota is still shown: the panel says so
    saved = settings.vertex_estimates[count - 1]
    settings.vertex_estimates[count - 1] = 5_000_000
    labels, _bars, marked = draw(0.0001)
    assert 'Over the limit, shown as the last LOD' in labels and marked == [f'{count - 1:02}'], (labels, marked)
    settings.vertex_estimates[count - 1] = saved

    # The camera drives it without Auto: the ratio comes from the view and the sphere of the last Refresh
    def view(distance):
        window = Matrix.Identity(4)
        window[1][1] = 2.0
        return SimpleNamespace(scene=scene, window_manager=None, region_data=SimpleNamespace(
            view_matrix=Matrix.Translation((0, 0, -distance)), window_matrix=window, is_perspective=True))
    center = (Vector(settings.sphere_box[:3]) + Vector(settings.sphere_box[3:])) / 2
    ratios = []
    for distance in (3.0, 30.0):
        assert lod.update_view_ratio(view(distance))
        camera = Vector((0, 0, distance)) * scene.unit_settings.scale_length
        wanted = lod_rules.screen_ratio(settings.lod_diameter, (camera - center).length, 2 * math.atan(1 / 2.0))
        assert abs(lod._auto_state['last_ratio'] - wanted) < 1e-5, (lod._auto_state['last_ratio'], wanted)
        ratios.append(lod._auto_state['last_ratio'])
    assert ratios[0] > ratios[1], ratios
    assert not lod.update_view_ratio(view(30.0))  # the view did not move
    _labels, bars, _marked = draw()
    quota = lod_rules.vertex_quota_at(ratios[1], settings.msfs_vertex_factor)
    assert bars[0][1] == lod.format_percent(100.0 * settings.vertex_estimates[0] / quota), bars
    scene.fss_viewport_lod = 1
    scene.fss_viewport_lod_auto = True
    assert not lod.update_view_ratio(view(9.0)), 'Auto keeps the ratio itself'
    scene.fss_viewport_lod_auto = False
    scene.fss_viewport_lod = -1

    settings.scanned = False
    labels, bars, _marked = draw(0.05)
    assert 'Click Refresh LOD Counts for the quota at this view' in labels and not bars, (labels, bars)
    settings.scanned = True

    lod._auto_state['last_ratio'] = saved_ratio
    lod._auto_state['ratio_view_matrix'] = None
    settings.hide_sizes = (0.0,) * 7
    for obj in objs:
        me = obj.data
        bpy.data.objects.remove(obj)
        bpy.data.meshes.remove(me)
    print(f"PASS: test_viewport_lod_view_quota ({count} LODs; Off, a fixed LOD and Auto alike; quota {near:,} at 133 %, "
          f"{far:,} at 5 %; the camera moves it)")


def _lod_snapshot():
    """What the LOD Settings panels read, to check that drawing writes nothing."""
    settings = bpy.context.scene.fss_lod_settings
    keys = ('scanned', 'write_count', 'counts', 'cutoffs', 'resolved_table', 'vertex_estimates', 'min_sizes',
            'inspect_lod')
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
    """LOD Settings without source counts; Hides Under per LOD in Export Settings; Hints without a quota table or
    Dropped box, with contributor bars as shares of the LOD's vertices; drawing writes nothing."""
    from fss_blender_tools import lod, lod_model, lod_rules
    scene = bpy.context.scene
    settings = scene.fss_lod_settings
    settings.hide_sizes = (0.0,) * 7
    objs = [_cube('BARS_BIG', 2.0, (0, 0, 0)), _cube('BARS_MID', 0.5, (1.5, 0, 0))]
    objs += [_cube(f'BARS_TINY_{i}', 0.001, (-1 + 0.2 * i, 1, 0)) for i in range(10)]
    scene.fss_viewport_lod_auto = False
    scene.fss_viewport_lod = -1
    assert bpy.ops.fss.lod_refresh() == {'FINISHED'}
    assert settings.scanned and settings.write_count >= 2, (settings.scanned, settings.write_count)
    counts = list(settings.counts)[:settings.write_count]

    # A: no source counts in LOD Settings; the table comes from test_viewport_lod_view_quota
    labels, bars = _draw_lod_panel('FSS_PT_lod_settings')
    assert not any(text.endswith(' obj') or ' obj (' in text for _factor, text, _red in bars), bars
    assert 'Vert/Obj' in labels and 'Cached counts: Refresh after editing' in labels, labels
    assert not any(text.startswith('LOD0') and 'hides' in text for text in labels), labels
    assert counts[1] < counts[0], counts  # the tiny cubes are below LOD01's cut-off

    # B: Hides Under per LOD in Export Settings; the first Refresh writes the defaults in, and the XML table is low
    labels, bars = _draw_lod_panel('FSS_PT_lod_export')
    start = labels.index('LOD')
    assert labels[start:start + 4] == ['LOD', 'Hides Under', 'minSize %', 'Shows From'], labels
    assert not bars, bars
    for level in range(1, 7):
        assert abs(settings.hide_sizes[level] - settings.cutoffs[level]) < 1e-5, (level, settings.hide_sizes[:])
    assert settings.hide_sizes[0] == 0.0
    assert all(abs(a - b) < 1e-6 for a, b in zip(settings.resolved_table, lod_rules.MSFS_MIN_SIZES)), \
        list(settings.resolved_table)
    calls = []
    bpy.types.FSS_PT_lod_export.draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
    props = [args[1] for name, args, _kwargs in calls if name == 'prop']
    assert props.count('hide_sizes') == 6 and props.count('min_sizes') == 7, calls

    # Padding: the multiplier scales the geometry's sphere; 1 pads nothing; a saved diameter converts once at Refresh
    mesh = settings.mesh_diameter
    plan = lod_model.build_plan(bpy.context)
    labels, _bars = _draw_lod_panel('FSS_PT_lod_export')
    assert any('origins outside the geometry' in text for text in labels), labels
    far_names = [name for name, _outside in plan['far_nodes']]
    assert far_names, plan['far_nodes']
    assert plan['padding'] is None and settings.pad_factor == 1.0, plan['padding']
    def pad_diameter():
        half = lod_model.build_plan(bpy.context)['padding'][1]
        return 2.0 * sum(value * value for value in half) ** .5

    settings.pad_factor = 2.0
    assert abs(pad_diameter() - 2.0 * mesh) < 1e-3, (pad_diameter(), mesh)
    assert bpy.ops.fss.lod_refresh() == {'FINISHED'}
    # this scene has a far origin: at 2x it stays outside the padding and the panel says so
    assert settings.lod_diameter > 2.0 * mesh + .01, settings.lod_diameter
    labels, _bars = _draw_lod_panel('FSS_PT_lod_export')
    assert any('origins outside the padding' in text for text in labels), labels
    assert not any('origins outside the geometry' in text for text in labels), labels
    assert lod_model.build_plan(bpy.context)['far_nodes'], 'the far origin is still outside at 2x'
    # the padding changed, not yet refreshed: the list was measured with the old padding and is not shown
    settings.pad_factor = 3.0
    labels, _bars = _draw_lod_panel('FSS_PT_lod_export')
    assert not any('origins outside' in text for text in labels), labels
    assert 'Press Refresh LOD Counts to apply' in labels, labels
    # at 10x the padding encloses it: MSFS sees exactly ten times the geometry's sphere
    settings.pad_factor = 10.0
    assert bpy.ops.fss.lod_refresh() == {'FINISHED'}
    assert abs(settings.lod_diameter - 10.0 * mesh) < 1e-3, (settings.lod_diameter, mesh)
    labels, _bars = _draw_lod_panel('FSS_PT_lod_export')
    assert any(text.startswith('MSFS sees:') and 'geometry' in text for text in labels), labels
    # ... and no warning is left: the origin no longer matters
    assert not lod_model.build_plan(bpy.context)['far_nodes'], 'the padding encloses the far origin at 10x'
    assert not any('origins outside' in text for text in labels), labels
    assert 'Above 5x has not been tested in the simulator' in labels, labels
    settings.pad_factor = 1.0
    settings.reference_size = 2.5 * mesh
    assert abs(pad_diameter() - 2.5 * mesh) < 1e-3, pad_diameter()
    assert bpy.ops.fss.lod_refresh() == {'FINISHED'}
    assert settings.reference_size == 0.0 and abs(settings.pad_factor - 2.5) < 1e-3, settings.pad_factor
    assert settings.scanned
    settings.pad_factor = 1.0
    assert bpy.ops.fss.lod_refresh() == {'FINISHED'}

    # A typed minSize holds a LOD back: Shows From, the plan's XML table and the view follow at once, counts stay valid
    settings.vertex_estimates[0] = 1000
    settings.min_sizes[0] = 150.0
    assert settings.scanned
    labels, _bars = _draw_lod_panel('FSS_PT_lod_export')
    assert '150 %' in labels, labels
    assert abs(lod_model.build_plan(bpy.context)['table'][0] - 1.5) < 1e-6
    lod.apply_viewport_lod(bpy.context)
    settings.min_sizes = tuple(value * 100.0 for value in lod_rules.MSFS_MIN_SIZES)
    assert bpy.ops.fss.lod_refresh() == {'FINISHED'}
    # Hints has no quota table and no Dropped box
    labels, bars = _draw_lod_panel('FSS_PT_lod_quota_hints')
    assert not {'Quota', 'Quota Here', 'Used', 'Shows From'} & set(labels), labels
    assert not any(text.startswith('Dropped at export') for text in labels), labels
    assert 'Per LOD Vertex Contributors' in labels and 'Hints for LOD:' not in labels, labels
    assert not any(text.startswith('Largest contributors') for text in labels), labels

    # C: contributor bars, factor = vertices / the LOD's vertices
    total = settings.vertex_estimates[0]
    contributors = [h for h in settings.hints if h.lod_level == 0 and h.kind == 'CONTRIBUTOR'][:5]
    shares = [bar for bar in bars if bar[1].startswith('~')]
    assert contributors and len(shares) == len(contributors), (shares, len(contributors))
    for h, (factor, text, _red) in zip(contributors, shares):
        assert abs(factor - h.vertices / total) < 1e-6 and text.startswith(f'~{h.vertices:,} ('), (factor, text)

    # A heavy LOD: the size it needs, which a near camera can reach; the last LOD is the fallback
    vertex_factor = settings.msfs_vertex_factor
    settings.vertex_estimates[0] = 5_000_000
    effective = lod_rules.effective_min_sizes(settings.resolved_table, list(settings.vertex_estimates),
                                              vertex_factor, settings.write_count)
    assert effective[0] > 1.0, effective
    labels, bars = _draw_lod_panel('FSS_PT_lod_export')
    needs = f'{effective[0] * 100:.0f} %'
    assert needs in labels and 'fallback' in labels and not any(t.startswith('never') for t in labels), labels

    # A typed Hides Under: the counts wait for a Refresh, which then uses it and keeps it
    written = settings.write_count
    settings.hide_sizes[1] = 1.0
    assert not settings.scanned
    labels, bars = _draw_lod_panel('FSS_PT_lod_export')
    assert labels.count('-') == 8 and 'Press Refresh LOD Counts for Shows From' in labels, labels
    assert bpy.ops.fss.lod_refresh() == {'FINISHED'}
    assert abs(settings.cutoffs[1] - 1.0) < 1e-6 and abs(settings.hide_sizes[1] - 1.0) < 1e-6, list(settings.cutoffs)
    assert settings.counts[1] < counts[1], (list(settings.counts), counts)
    assert written >= 2
    settings.hide_sizes = (0.0,) * 7

    for obj in objs:
        bpy.data.objects.remove(obj)
    print(f"PASS: test_lod_settings_bars (objects {counts}, bars count / LOD00; Hides Under per LOD, written at the first "
          f"Refresh and kept, Shows From '{needs}'; {len(shares)} contributor bars as shares; drawing writes "
          f"nothing)")


def test_add_parent():
    bpy.ops.wm.read_homefile(use_empty=True)
    scene = bpy.context.scene
    collection = bpy.data.collections.new("PARTS")
    scene.collection.children.link(collection)

    def new(name, parent=None, location=(0.0, 0.0, 0.0)):
        obj = bpy.data.objects.new(name, None)
        collection.objects.link(obj)
        obj.parent = parent
        obj.location = location
        return obj

    def select(*objects, active=None):
        bpy.context.view_layer.update()  # new objects reach the view layer here
        for obj in bpy.context.view_layer.objects:
            obj.select_set(obj in objects)
        bpy.context.view_layer.objects.active = active
        assert set(bpy.context.selected_objects) == set(objects)

    root = new("ROOT", location=(1.0, 0.0, 0.0))
    root.rotation_euler = (0.0, 0.0, 0.5)
    a, b = new("A", root, (1.0, 2.0, 3.0)), new("B", root, (-1.0, 0.0, 0.0))
    b.rotation_euler = (0.3, 0.0, 0.0)
    a.rotation_euler = (0.0, 0.7, 0.0)
    other = new("OTHER")
    child = new("CHILD", a)

    def note(calls):
        return [kwargs for name, _args, kwargs in calls if name == 'label' and 'different parents' in kwargs.get('text', '')]

    def draw():
        calls = []
        bpy.types.FSS_PT_tools.draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
        return calls

    # Not siblings: refused, with a note in the panel; also a selected object with its own child
    for objects in ((a, other), (a, child)):
        select(*objects, active=a)
        assert not bpy.ops.fss.add_empty_parent.poll()
        assert note(draw())

    # Siblings: one empty, at the active object, under their parent; nothing moves
    select(a, b, active=a)
    assert bpy.ops.fss.add_empty_parent.poll() and not note(draw())
    before = {a: a.matrix_world.copy(), b: b.matrix_world.copy()}
    scene.fss_empty_parent_mode = 'MERGE'
    scene.fss_empty_parent_marker_name = "PANEL"
    assert bpy.ops.fss.add_empty_parent() == {'FINISHED'}
    bpy.context.view_layer.update()
    empty = bpy.data.objects["@MERGE_PANEL"]
    assert a.parent is empty and b.parent is empty and empty.parent is root
    assert [o.name for o in empty.users_collection] == ["PARTS"]
    for obj, world in before.items():
        assert all(abs(x - y) < 1e-5 for ra, rb in zip(obj.matrix_world, world) for x, y in zip(ra, rb)), obj.name
    loc, rot, scale = empty.matrix_world.decompose()
    want_loc, want_rot, _ = before[a].decompose()
    assert (loc - want_loc).length < 1e-5 and abs(rot.dot(want_rot)) > 1 - 1e-5 and abs(scale.x - 1) < 1e-5

    # An inactive selection follows the first selected object; the name rules
    assert build_names(scene, other) == {
        'MANUAL': "OTHER_PARENT", 'SUFFIX': "OTHER_PARENT", 'PREFIX': "PARENT_OTHER", 'MERGE': "@MERGE_OTHER",
        'NOMERGE': "@NOMERGE_OTHER", 'ZONE': "@ZONE_OTHER"}, build_names(scene, other)
    # A marker is not doubled, and a typed name stays with its object
    marked = new("@MERGE_DOOR")
    select(marked, active=marked)
    scene.fss_empty_parent_mode = 'ZONE'
    assert scene.fss_empty_parent_marker_name == "DOOR"
    assert bpy.ops.fss.add_empty_parent() == {'FINISHED'}
    assert marked.parent.name == "@ZONE_DOOR"

    # Bones of one armature are different parents
    armature = bpy.data.objects.new("ARM", bpy.data.armatures.new("ARM"))
    collection.objects.link(armature)
    c, d = new("C", armature), new("D", armature)
    c.parent_type = d.parent_type = 'BONE'
    c.parent_bone, d.parent_bone = "ONE", "TWO"
    select(c, d, active=c)
    assert not bpy.ops.fss.add_empty_parent.poll()
    print("PASS: test_add_parent (siblings get one empty at the active object; others refused with a note)")


def test_rename_meshes():
    bpy.ops.wm.read_homefile(use_empty=True)
    collection = bpy.context.scene.collection

    def new(name, mesh_name=None, parent=None):
        data = None
        if mesh_name is not None:
            data = bpy.data.meshes.get(mesh_name) or bpy.data.meshes.new(mesh_name)
        obj = bpy.data.objects.new(name, data)
        collection.objects.link(obj)
        obj.parent = parent
        return obj

    root = new("ROOT")
    plain = new("PLAIN", "Cube.001", root)
    marked = new("@NOMERGE_PANEL", "Cube.002", root)
    deep = new("DEEP", "Cube.003", new("GROUP", None, root))
    hidden = new("HIDDEN", "Cube.004", root)
    # Shared with a user outside the selection, which sorts first
    in_shared = new("SCREW_B", "Screw", root)
    out_shared = new("SCREW_A", "Screw")
    # Two meshes holding each other's names, a name taken outside, one already right, one not touched
    swap_a = new("SWAP_A", "MESH_SWAP_B", root)
    swap_b = new("SWAP_B", "MESH_SWAP_A", root)
    taken = new("TAKEN", "Cube.005", root)
    outside_taken = new("ELSEWHERE", "MESH_TAKEN")
    done = new("DONE", "MESH_DONE", root)
    untouched = new("UNTOUCHED", "Cube.006")

    bpy.context.view_layer.update()
    hidden.hide_set(True)
    for obj in bpy.context.view_layer.objects:
        obj.select_set(obj is root)
    assert bpy.ops.fss.add_empty_parent.poll() and bpy.ops.fss.rename_meshes.poll()
    assert bpy.ops.fss.rename_meshes() == {'FINISHED'}

    expected = {plain: "MESH_PLAIN", marked: "MESH_PANEL", deep: "MESH_DEEP", hidden: "MESH_HIDDEN",
                in_shared: "MESH_SHARED_SCREW_A", out_shared: "MESH_SHARED_SCREW_A", swap_a: "MESH_SWAP_A",
                swap_b: "MESH_SWAP_B", taken: "MESH_TAKEN.001", outside_taken: "MESH_TAKEN", done: "MESH_DONE",
                untouched: "Cube.006"}
    got = {obj: obj.data.name for obj in expected}
    assert got == expected, {obj.name: name for obj, name in got.items()}
    assert not [mesh.name for mesh in bpy.data.meshes if mesh.name.startswith("FSS_RENAME_")]
    assert root.name == "ROOT" and marked.name == "@NOMERGE_PANEL", "object names stay"

    # Several roots, and nothing to rename
    empty = new("EMPTY")
    other = new("OTHER", "Cube.007")
    bpy.context.view_layer.update()
    for obj in bpy.context.view_layer.objects:
        obj.select_set(obj in (empty, other, untouched))
    assert bpy.ops.fss.rename_meshes() == {'FINISHED'}
    assert (other.data.name, untouched.data.name) == ("MESH_OTHER", "MESH_UNTOUCHED")
    for obj in bpy.context.view_layer.objects:
        obj.select_set(obj is empty)
    try:
        result = bpy.ops.fss.rename_meshes()
    except RuntimeError:  # the warning of a cancelled operator is raised in background Blender
        result = {'CANCELLED'}
    assert result == {'CANCELLED'}
    print("PASS: test_rename_meshes (subtree with hidden objects, shared, markers, swaps, a taken name, linked not run)")


def build_names(scene, obj):
    from fss_blender_tools import tools
    for candidate in bpy.context.view_layer.objects:
        candidate.select_set(candidate is obj)
    bpy.context.view_layer.objects.active = None
    bpy.context.view_layer.update()
    names = {}
    for mode in ('MANUAL', 'SUFFIX', 'PREFIX', 'MERGE', 'NOMERGE', 'ZONE'):
        scene.fss_empty_parent_mode = mode
        names[mode] = tools.build_empty_parent_name(scene, tools._anchor_object(bpy.context))
    return names


def main():
    test_layout()
    test_draw_all()
    test_object_lod()
    test_viewport_lod_excluded()
    test_viewport_lod_view_quota()
    test_export_settings_one_table()
    test_lod_settings_bars()
    test_add_parent()
    test_rename_meshes()
    print("ALL TESTS PASSED")


main()
