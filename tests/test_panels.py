"""The FSS sidebar layout: every panel in the tab FSS MSFS Tools (material-management decision 15), top-level in
pipeline order (Zones & Merge Tree, Materials with By Zone, Tags, LOD with its subpanels, UV Tools with Seams and
Packing, General, Empty Bounds, Heatmap, Checks), Packing in the UV editor's FSS MSFS Tools tab too, no other tab, and
every panel drawing without errors.

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
EXPECTED = {
    'FSS_PT_merge': ("Zones & Merge Tree", '', 0, MSFS),
    'FSS_PT_materials': ("Materials", '', 1, MSFS),
    'FSS_PT_materials_by_zone': ("By Zone", 'FSS_PT_materials', 0, MSFS),
    'FSS_PT_tags': ("Tags", '', 2, MSFS),
    'FSS_PT_lod': ("LOD", '', 3, MSFS),
    'FSS_PT_lod_quota_hints': ("Quota and Hints", 'FSS_PT_lod', 0, MSFS),
    'FSS_PT_lod_export': ("Export Settings", 'FSS_PT_lod', 0, MSFS),
    'FSS_PT_lod_export_advanced': ("Advanced", 'FSS_PT_lod_export', 0, MSFS),
    'FSS_PT_uv_tools': ("UV Tools", '', 4, MSFS),
    'FSS_PT_uv_autoseam': ("Seams", 'FSS_PT_uv_tools', 0, MSFS),
    'FSS_PT_uv_marks': ("Packing", 'FSS_PT_uv_tools', 1, MSFS),
    'FSS_PT_visibility': ("Visibility Scoring", 'FSS_PT_uv_marks', 0, MSFS),
    'FSS_PT_tools': ("General", '', 5, MSFS),
    'FSS_PT_empty_bounds': ("Empty Bounds", '', 6, MSFS),
    'FSS_PT_uv_heatmap': ("Heatmap", '', 7, MSFS),
    'FSS_PT_checks': ("Checks", '', 8, MSFS),
}
# The former Utilities sections, top-level now: closed by default, as they effectively were inside the closed group
DEFAULT_CLOSED = ('FSS_PT_tools', 'FSS_PT_empty_bounds', 'FSS_PT_uv_heatmap', 'FSS_PT_checks')
# The UV editor's sidebar: Packing again (UV journal decision 119), drawn by the same code
EXPECTED_IMAGE_EDITOR = {
    'FSS_PT_uv_marks_image': ("Packing", '', 0, MSFS),
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
    # The group panel Utilities is gone (decision 15)
    assert not [cls for cls in panels.values() if cls.bl_label == 'Utilities']
    # One tab: no panel of the add-on elsewhere, and top-level orders 0..8 without gaps or doubles
    other_tabs = sorted((idname, cls.bl_category) for idname, cls in panels.items() if cls.bl_category != MSFS)
    assert not other_tabs, other_tabs
    orders = sorted(getattr(cls, 'bl_order', 0) for idname, cls in panels.items()
                    if cls.bl_space_type == 'VIEW_3D' and not getattr(cls, 'bl_parent_id', ''))
    assert orders == list(range(9)), orders
    # Every FSS panel is expected, and a subpanel sits in its parent's tab
    unexpected = sorted(set(panels) - set(EXPECTED) - set(EXPECTED_IMAGE_EDITOR))
    assert not unexpected, unexpected
    for idname, cls in panels.items():
        parent = getattr(cls, 'bl_parent_id', '')
        if parent:
            assert panels[parent].bl_category == cls.bl_category, (idname, cls.bl_category, panels[parent].bl_category)
    top = sorted((getattr(cls, 'bl_order', 0), cls.bl_label) for cls in panels.values()
                 if cls.bl_space_type == 'VIEW_3D' and not getattr(cls, 'bl_parent_id', ''))
    print(f"PASS: test_layout ({len(panels)} panels, all in {MSFS}: {', '.join(label for _o, label in top)}; "
          f"General, Empty Bounds, Heatmap, Checks closed by default; no Utilities; UV editor: {MSFS} > Packing)")


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
    print(f"PASS: test_draw_all ({len(drawn)} panels drawn; Skip Auto Seam in Seams only; Packing without Apply and "
          "Select Marked, with Check All, the same in the UV editor; Find Faces Without Area and Find Faces Without UV "
          "Area in Checks; Refresh in Materials; 'Animation Steps')")


def main():
    test_layout()
    test_draw_all()
    print("ALL TESTS PASSED")


main()
