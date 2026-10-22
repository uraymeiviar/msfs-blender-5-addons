"""The FSS Tools sidebar layout: top-level panels in pipeline order, UV Tools and Utilities with their sections, and
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

# idname: (label, parent idname or '', bl_order)
EXPECTED = {
    'FSS_PT_merge': ("Zones & Merge Tree", '', 0),
    'FSS_PT_tags': ("Tags", '', 1),
    'FSS_PT_lod': ("LOD", '', 2),
    'FSS_PT_uv_tools': ("UV Tools", '', 3),
    'FSS_PT_utilities': ("Utilities", '', 4),
    'FSS_PT_uv_autoseam': ("Seams", 'FSS_PT_uv_tools', 0),
    'FSS_PT_uv_marks': ("Packing", 'FSS_PT_uv_tools', 1),
    'FSS_PT_visibility': ("Visibility Scoring", 'FSS_PT_uv_marks', 0),
    'FSS_PT_tools': ("General", 'FSS_PT_utilities', 0),
    'FSS_PT_empty_bounds': ("Empty Bounds", 'FSS_PT_utilities', 1),
    'FSS_PT_uv_heatmap': ("Heatmap", 'FSS_PT_utilities', 2),
    'FSS_PT_checks': ("Checks", 'FSS_PT_utilities', 3),
}


def fss_panels():
    return {cls.bl_idname: cls for cls in bpy.types.Panel.__subclasses__()
            if getattr(cls, 'bl_category', '') == 'FSS Tools' and cls.__module__.startswith('fss_blender_tools')}


def test_layout():
    panels = fss_panels()
    for idname, (label, parent, order) in EXPECTED.items():
        cls = panels.get(idname)
        assert cls is not None, f"{idname} not registered"
        assert cls.bl_label == label, (idname, cls.bl_label, label)
        assert getattr(cls, 'bl_parent_id', '') == parent, (idname, getattr(cls, 'bl_parent_id', ''), parent)
        assert getattr(cls, 'bl_order', 0) == order, (idname, getattr(cls, 'bl_order', 0), order)
        assert getattr(bpy.types, idname, None) is not None, f"{idname} not in bpy.types"
    # Every other FSS panel is a subpanel of one of these (the LOD subpanels)
    for idname, cls in panels.items():
        if idname not in EXPECTED:
            assert getattr(cls, 'bl_parent_id', '') in panels, (idname, getattr(cls, 'bl_parent_id', ''))
    top = sorted((order, label) for label, parent, order in EXPECTED.values() if not parent)
    print(f"PASS: test_layout ({len(panels)} panels; top level: {', '.join(label for _o, label in top)})")


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
    steps = bpy.context.scene.fss_visibility.bl_rna.properties['states']
    assert steps.name == 'Animation Steps', steps.name
    print(f"PASS: test_draw_all ({len(drawn)} panels drawn; Skip Auto Seam in Seams only; Packing without Apply and "
          "Select Marked; 'Animation Steps')")


def main():
    test_layout()
    test_draw_all()
    print("ALL TESTS PASSED")


main()
