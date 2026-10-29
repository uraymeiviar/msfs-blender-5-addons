"""The UV packer per texture set (UV journal decisions 112 to 121): density first with one t per set, underflow,
fit and overflow with k and the needed size (256 to 8192, "does not fit even at 8192"), direction marks, linked
duplicates, islands split by material, islands without UV area kept, Pack and its undo, Check All writing nothing,
Keep UVs, objects included that were not selected, Find Faces Without Area, Find Faces Without UV Area and the report's
needle warning, the migration to square sizes, the texture set list and the Packing panel in the 3D viewport and the
UV editor. The synthetic cases are those of tests/uv_prototype/pack_density_proto.py, run through uv_pack.

To run:
"<blender>" -b --factory-startup --python tests/test_uv_pack.py
"""

import math
import sys
from pathlib import Path
from types import SimpleNamespace

import bpy
import numpy as np

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
from fss_blender_tools import checks, uv_marks, uv_pack  # noqa: E402

fss_blender_tools.register()
assert Path(uv_pack.__file__).resolve().is_relative_to(REPO_ROOT), uv_pack.__file__

RANGE_TOL = 1e-4  # relative: density inside its range within rounding


def reset(fmin=1.0, fmax=1.0, target=20.48):
    bpy.ops.wm.read_homefile(use_empty=True)
    scene = bpy.context.scene
    scene.fss_uv_target_density = target
    scene.fss_uv_density_freedom_min = fmin
    scene.fss_uv_density_freedom_max = fmax


def quad_obj(name, rects, mats=None, scale=(1, 1, 1), uv_rects=None, mesh=None):
    """An object of separate quads: rects are (x, y, w, h) in metres in the XY plane; UV per quad = its own rect
    times 0.1 (or uv_rects); mats: material per quad."""
    if mesh is None:
        me = bpy.data.meshes.new(name)
        verts, faces = [], []
        for x, y, w, h in rects:
            b = len(verts)
            verts += [(x, y, 0), (x + w, y, 0), (x + w, y + h, 0), (x, y + h, 0)]
            faces.append((b, b + 1, b + 2, b + 3))
        me.from_pydata(verts, [], faces)
        uvl = me.uv_layers.new(name='UVMap')
        lv = np.zeros(len(me.loops), np.int64)
        me.loops.foreach_get('vertex_index', lv)
        if uv_rects is None:
            uvc = np.array(verts)[:, :2] * 0.1
        else:
            uvc = np.array([c for (u, v, w, h) in uv_rects for c in ((u, v), (u + w, v), (u + w, v + h), (u, v + h))])
        uvl.data.foreach_set('uv', uvc[lv].ravel())
        if mats:
            unique = list(dict.fromkeys(mats))
            for m in unique:
                me.materials.append(m)
            me.polygons.foreach_set('material_index', [unique.index(m) for m in mats])
        mesh = me
    obj = bpy.data.objects.new(name, mesh)
    obj.scale = scale
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.update()
    return obj


def mat(name, size=4096, margin=8):
    m = bpy.data.materials.new(name)
    m.fss_uv_texture_size = str(size)
    m.fss_uv_margin_px = margin
    return m


def uvs(obj):
    me = obj.data
    uv = np.zeros(len(me.loops) * 2)
    me.uv_layers.active.data.foreach_get('uv', uv)
    return uv.reshape(-1, 2)


def quad_density(q_px, w_cm, h_cm):
    a_px = uv_pack.tri_area(q_px[[0, 1, 2]][None])[0] + uv_pack.tri_area(q_px[[0, 2, 3]][None])[0]
    return math.sqrt(a_px / (w_cm * h_cm))


def ok(r):
    """0 margin violations, 0 overlaps, every island inside its range, fill at most 100 %."""
    return (r['margin_violations'] == 0 and r['overlap_tri_pairs'] == 0 and r['density_out_of_range_max'] <= RANGE_TOL
            and r['fill_pct'] <= 100.0)


def test_exact_density():
    reset()
    m = mat('EXACT')
    rects = [(0, 0, 0.5, 0.2), (1, 0, 0.1, 0.3), (2, 0, 0.25, 0.25)]
    quad_obj('EX_A', rects, mats=[m] * 3, scale=(2.0, 1.0, 1.0))
    quad_obj('EX_B', [(0, 0, 0.3, 0.3)], mats=[m], scale=(1.0, 1.0, 0.5))
    r = uv_pack.pack(m)
    errs = []
    for name, sizes, sc in (('EX_A', rects, (2.0, 1.0)), ('EX_B', [(0, 0, 0.3, 0.3)], (1.0, 1.0))):
        for q, (_x, _y, w, h) in zip(uvs(bpy.data.objects[name]).reshape(-1, 4, 2) * 4096, sizes):
            errs.append(abs(quad_density(q, w * sc[0] * 100, h * sc[1] * 100) - 20.48) / 20.48)
    assert max(errs) < 1e-4 and ok(r) and r['written'] and r['islands'] == 4, (max(errs), r)
    print(f"PASS: test_exact_density (non-uniform scale, px/cm error {max(errs):.1e}, {r['mode']})")


def test_underflow_and_sizes():
    reset(0.9, 1.1)
    m = mat('UNDER')
    quad_obj('UN', [(i * 0.6, 0, 0.3 + 0.02 * i, 0.2) for i in range(10)], mats=[m] * 10)
    r = uv_pack.measure(m)
    ext = max(r['extent_px'])
    need = r['needed_size']
    assert r['mode'] == 'underflow' and r['t'] == 1.0 and r['packs'] == 1 and ok(r), r
    assert need >= ext and need / 2 < ext and need == 4096, (ext, need)
    text = uv_pack.result_text(r)
    assert text.startswith('fits ') and text.endswith(' %') and 'would do' not in text, text
    # a tiny set: the needed size is clamped to 256 at the bottom
    reset(0.9, 1.1)
    m = mat('TINY')
    quad_obj('TI', [(0, 0, 0.02, 0.02), (1, 0, 0.03, 0.01)], mats=[m, m])
    r = uv_pack.measure(m)
    assert r['mode'] == 'underflow' and r['k'] * 4096 < 128 and r['needed_size'] == 256, r
    assert r['fill_pct'] <= 100.0 and uv_pack.result_text(r).endswith('256 x 256 would do'), uv_pack.result_text(r)
    print(f"PASS: test_underflow_and_sizes (t=1, 1 pack, extent {ext:.0f} px needs 4096; tiny set k={r['k']:.4f} "
          f"needs 256 x 256, not {uv_pack.next_pow2(r['k'] * 4096)})")


def test_fit():
    reset(0.8, 1.25)
    m = mat('MID', 1024)
    rng = np.random.default_rng(5)
    rects = [(i * 0.5, 0, float(s), float(s)) for i, s in enumerate(rng.uniform(0.05, 0.12, 24))]
    quad_obj('MI', rects, mats=[m] * len(rects))
    r = uv_pack.measure(m)
    assert r['mode'] == 'fit' and 0 < r['t'] < 1 and r['k'] <= 1 and ok(r), r
    assert r['needed_size'] == 1024 and r['fill_pct'] == r['fill_current_pct'], r
    print(f"PASS: test_fit (t={r['t']:.3f}, k={r['k']:.4f}, {r['packs']} packs, fill {r['fill_pct']:.1f} %)")


def test_overflow_and_clamp():
    reset(0.9, 1.1)
    m = mat('OVER', 1024)
    rng = np.random.default_rng(5)
    rng.uniform(0.05, 0.12, 24)
    rects = [(i * 0.8, 0, float(s), float(s * 0.7)) for i, s in enumerate(rng.uniform(0.15, 0.4, 20))]
    obj = quad_obj('OV', rects, mats=[m] * len(rects))
    r = uv_pack.measure(m)
    k_check = max(r['extent_px']) / 1024
    assert r['mode'] == 'overflow' and r['t'] == 0 and r['k'] > 1 and abs(k_check - r['k']) < 1e-6 and ok(r), r
    assert r['needed_size'] == uv_pack.next_pow2(r['k'] * 1024) and r['fits_8192'], r
    assert uv_pack.result_text(r) == f"needs x{r['k']:.2f}: {r['needed_size']} x {r['needed_size']}"
    k1 = r['k']
    # the same islands at 4096 px for 1024 px of texture: k x 4096 is above 8192
    m.fss_uv_texture_size = '4096'
    bpy.context.scene.fss_uv_target_density = 20.48 * 4
    obj.data.update()
    r = uv_pack.measure(m)
    assert r['mode'] == 'overflow' and not r['fits_8192'] and r['needed_size'] is None and r['k'] * 4096 > 8192, r
    assert uv_pack.result_text(r) == f"does not fit even at 8192 (x{r['k']:.2f})", uv_pack.result_text(r)
    assert r['fill_pct'] <= 100.0, r['fill_pct']
    print(f"PASS: test_overflow_and_clamp (k={k1:.3f} needs {uv_pack.next_pow2(k1 * 1024)}; at 4096 k={r['k']:.3f}: "
          f"'{uv_pack.result_text(r)}', fill {r['fill_pct']:.1f} % of the layout)")


def test_directions():
    reset()
    m = mat('DIR')
    up = quad_obj('UP', [(0, 0, 0.6, 0.1), (1, 0, 0.1, 0.5)], mats=[m, m])
    up['fss_uv_direction'] = 'UPRIGHT'
    fl = quad_obj('FLIPPED', [(0, 1, 0.5, 0.05)], mats=[m])
    fl['fss_uv_direction'] = 'FLIP'
    quad_obj('FREE', [(i * 0.5, 2, 0.3, 0.07) for i in range(12)], mats=[m] * 12)
    r = uv_pack.pack(m)
    angles = []
    for obj in (up, fl):
        q = uvs(obj).reshape(-1, 4, 2)
        e = q[:, 1] - q[:, 0]
        angles.append(float(np.abs(np.arctan2(e[:, 1], e[:, 0])).max()))
    assert max(angles) < 1e-4 and r['upright_rotation_err_rad'] < 1e-4 and r['upright_islands'] == 3 and ok(r), r
    assert not r['quarter']
    up['fss_uv_direction'] = 'QUARTER'
    r = uv_pack.measure(m)
    assert r['quarter'] and ok(r), r
    print(f"PASS: test_directions (UPRIGHT and FLIP keep their rotation, {max(angles):.1e} rad; QUARTER packs CARDINAL)")


def test_linked_and_split():
    reset()
    m = mat('LINK')
    a = quad_obj('LA', [(0, 0, 0.3, 0.2), (1, 0, 0.2, 0.2)], mats=[m, m])
    quad_obj('LB', None, mesh=a.data).location = (5, 0, 0)
    quad_obj('LC', None, mesh=a.data).location = (9, 0, 0)
    r = uv_pack.measure(m)
    assert r['islands'] == 2 and r['objects'] == ['LA', 'LB', 'LC'] and ok(r), r
    # an island spanning two materials is split, each half at its density in its own texture
    reset()
    ma, mb = mat('SPLIT_A'), mat('SPLIT_B', 2048)
    me = bpy.data.meshes.new('SP')
    me.from_pydata([(0, 0, 0), (0.3, 0, 0), (0.6, 0, 0), (0.6, 0.3, 0), (0.3, 0.3, 0), (0, 0.3, 0)], [],
                   [(0, 1, 4, 5), (1, 2, 3, 4)])
    uvl = me.uv_layers.new(name='UVMap')
    lv = np.zeros(8, np.int64)
    me.loops.foreach_get('vertex_index', lv)
    co = np.array([(0, 0), (0.3, 0), (0.6, 0), (0.6, 0.3), (0.3, 0.3), (0, 0.3)]) * 0.5
    uvl.data.foreach_set('uv', co[lv].ravel())
    me.materials.append(ma)
    me.materials.append(mb)
    me.polygons.foreach_set('material_index', [0, 1])
    obj = quad_obj('SP', None, mesh=me)
    assert [m_.name for m_ in uv_pack.texture_sets()] == ['SPLIT_A', 'SPLIT_B']
    rows = [uv_pack.pack(ma), uv_pack.pack(mb)]
    uv = uvs(obj)
    d = [quad_density(uv[f * 4:(f + 1) * 4] * np.array([w, w]), 30, 30) for f, w in ((0, 4096), (1, 2048))]
    assert all(r_['islands'] == 1 and ok(r_) for r_ in rows) and max(abs(x - 20.48) for x in d) / 20.48 < 1e-4, d
    print(f"PASS: test_linked_and_split (3 users, 2 islands packed once; split halves {[round(x, 4) for x in d]} "
          "px/cm)")


def test_zero_area_and_spike():
    reset()
    m = mat('ZERO')
    zo = quad_obj('ZO', [(0, 0, 0.3, 0.3), (1, 0, 0.2, 0.2)], mats=[m, m],
                  uv_rects=[(0.1, 0.1, 0.2, 0.2), (0.5, 0.5, 0.3, 0.0)])
    before = uvs(zo)
    r = uv_pack.pack(m)
    after = uvs(zo)
    assert r['zero_area_islands'] == 1 and np.abs(after[4:] - before[4:]).max() < 1e-7 and ok(r), r
    assert np.abs(after[:4] - before[:4]).max() > 1e-3  # the other island moved
    assert r['uv_zero_islands'] == 0, r  # the line island is left out, so its triangles are no needles
    # islands with a zero-area spike (a degenerate UV triangle sticking out) among small islands
    reset()
    m = mat('SPIKE', 1024)
    verts, faces, uv_co = [], [], []
    for i in range(6):
        b = len(verts)
        x = i * 1.0
        verts += [(x, 0, 0), (x + 0.2, 0, 0), (x + 0.2, 0.2, 0), (x, 0.2, 0), (x + 0.5, 0.1, 0)]
        faces += [(b, b + 1, b + 2, b + 3), (b + 1, b + 4, b + 2)]
        uv_co += [(0.0, 0.0), (0.2, 0.0), (0.2, 0.2), (0.0, 0.2), (0.2, 1.0)]  # vertex b+4 on the line x = 0.2
    me = bpy.data.meshes.new('SPK')
    me.from_pydata(verts, [], faces)
    uvl = me.uv_layers.new(name='UVMap')
    lv = np.zeros(len(me.loops), np.int64)
    me.loops.foreach_get('vertex_index', lv)
    uvl.data.foreach_set('uv', (np.array(uv_co) * 0.1)[lv].ravel())
    me.materials.append(m)
    quad_obj('SPK', None, mesh=me)
    quad_obj('SPK_SMALL', [(i * 0.3, 3, 0.04 + 0.01 * (i % 4), 0.05) for i in range(40)], mats=[m] * 40)
    r = uv_pack.measure(m)
    # the spikes are needles (3D area, no UV area) inside islands with area (decision 118)
    assert ok(r) and r['uv_zero_islands'] == 6 and r['uv_zero_objects'] == ['SPK'], r
    print(f"PASS: test_zero_area_and_spike (line island kept unchanged; spike set gap {r['min_gap_px']:.2f} px, "
          f"0 overlaps, {r['shape_method']}, 6 needle islands reported)")


def build_shared():
    """SHARED on SEL_A (selected) and OTHER (not selected), PRIVATE on SEL_A, FUR (Keep UVs) on HAIR."""
    reset()
    shared, private, fur = mat('SHARED'), mat('PRIVATE'), mat('FUR')
    fur.fss_uv_keep_uvs = True
    a = quad_obj('SEL_A', [(0, 0, 0.3, 0.2), (1, 0, 0.2, 0.2)], mats=[shared, private])
    b = quad_obj('OTHER', [(0, 1, 0.3, 0.3), (1, 1, 0.1, 0.4)], mats=[shared, shared])
    c = quad_obj('HAIR', [(0, 2, 0.1, 0.4)], mats=[fur])
    for obj in bpy.context.view_layer.objects:
        obj.select_set(obj == a)
    bpy.context.view_layer.objects.active = a
    return a, b, c, shared, private, fur


def all_uvs():
    return {obj.name: uvs(obj).copy() for obj in bpy.data.objects if obj.type == 'MESH'}


def test_pack_operator_and_undo():
    a, b, c, shared, _private, fur = build_shared()
    pins_before = {o.name: o.data.uv_layers.active.name for o in (a, b, c)}
    bpy.ops.ed.undo_push(message='before pack')
    before = all_uvs()
    assert bpy.ops.fss.uv_pack_texture_set(material='SHARED') == {'FINISHED'}
    after = all_uvs()
    # every face of SHARED moved, also on OTHER (not selected); PRIVATE and FUR untouched
    assert np.abs(after['OTHER'] - before['OTHER']).max() > 1e-3
    assert np.abs(after['SEL_A'][:4] - before['SEL_A'][:4]).max() > 1e-3
    assert np.abs(after['SEL_A'][4:] - before['SEL_A'][4:]).max() == 0.0
    assert np.abs(after['HAIR'] - before['HAIR']).max() == 0.0
    # selection, active object, active UV maps restored; no temporary data left
    assert [o.name for o in bpy.context.selected_objects] == ['SEL_A'] and bpy.context.active_object == a
    assert {o.name: o.data.uv_layers.active.name for o in (a, b, c)} == pins_before
    assert not [m for m in bpy.data.meshes if m.name.startswith('FSS_PACK_TMP')]
    assert not [o for o in bpy.data.objects if o.name.startswith('FSS_PACK_TMP')]
    report = bpy.data.texts[uv_pack.REPORT_TEXT_NAME].as_string()
    assert '# Pack: 1 texture set(s)' in report and '## SHARED: ' in report, report
    assert 'Included, not selected: 1 object(s): OTHER' in report, report
    assert uv_marks._results['SHARED']['written']
    # undo restores the UVs
    undone = 'not testable'
    try:
        bpy.ops.ed.undo()
        restored = all_uvs()
        if all(np.array_equal(restored[name], before[name]) for name in before):
            undone = 'restored'
        else:
            undone = 'NOT restored'
    except RuntimeError as ex:
        undone = f'not testable in background ({ex})'
    assert undone != 'NOT restored', undone
    print(f"PASS: test_pack_operator_and_undo (OTHER packed and reported, PRIVATE and FUR unchanged, selection "
          f"restored; undo: {undone})")


def test_edit_mode():
    a, b, _c, shared, _private, _fur = build_shared()
    bpy.ops.object.mode_set(mode='EDIT')
    r = uv_pack.pack(shared)
    assert bpy.context.mode == 'EDIT_MESH' and bpy.context.active_object == a, bpy.context.mode
    bpy.ops.object.mode_set(mode='OBJECT')
    assert r['written'] and ok(r)
    # the written UVs survive leaving Edit Mode: SHARED islands at 20.48 px/cm
    q = uvs(b).reshape(-1, 4, 2) * 4096
    d = quad_density(q[0], 30, 30)
    assert abs(d - 20.48) / 20.48 < 1e-4, d
    print(f"PASS: test_edit_mode (packed from Edit Mode, back in Edit Mode, OTHER at {d:.4f} px/cm)")


def test_check_all_and_keep():
    a, b, c, shared, private, fur = build_shared()
    before = all_uvs()
    assert bpy.ops.fss.uv_pack_check_all() == {'FINISHED'}
    after = all_uvs()
    assert all(np.array_equal(after[name], before[name]) for name in before), 'Check All wrote UVs'
    results = {name: r['mode'] for name, r in uv_marks._results.items()}
    assert results == {'SHARED': 'underflow', 'PRIVATE': 'underflow', 'FUR': 'kept'}, results
    assert not any(r['written'] for r in uv_marks._results.values())
    report = bpy.data.texts[uv_pack.REPORT_TEXT_NAME].as_string()
    assert '# Check All: 3 texture set(s)' in report and 'no UVs written' in report, report
    assert '## FUR: kept' in report and 'Keep UVs: left out, UVs unchanged' in report, report
    assert 'Included, not selected' not in report
    # Pack refuses a kept set
    assert bpy.ops.fss.uv_pack_texture_set(material='FUR') == {'CANCELLED'}
    assert np.array_equal(uvs(c), before['HAIR'])
    print(f"PASS: test_check_all_and_keep (UVs identical after Check All; {results})")


def test_faces_without_area():
    reset()
    m = mat('NOAREA')
    me = bpy.data.meshes.new('BROKEN')
    # a quad and a collapsed triangle (two vertices at the same place) with UVs that make a needle
    me.from_pydata([(0, 0, 0), (0.2, 0, 0), (0.2, 0.2, 0), (0, 0.2, 0), (0.2, 0.2, 0)], [],
                   [(0, 1, 2, 3), (1, 4, 2)])
    uvl = me.uv_layers.new(name='UVMap')
    lv = np.zeros(len(me.loops), np.int64)
    me.loops.foreach_get('vertex_index', lv)
    uvl.data.foreach_set('uv', (np.array([(0, 0), (0.2, 0), (0.2, 0.2), (0, 0.2), (0.25, 0.1)]) * 0.1)[lv].ravel())
    me.materials.append(m)
    broken = quad_obj('BROKEN', None, mesh=me)
    clean = quad_obj('CLEAN', [(1, 0, 0.2, 0.2)], mats=[m])
    found = checks.faces_without_area(bpy.context.view_layer)
    assert list(found) == [broken] and found[broken].tolist() == [1], found
    clean.select_set(True)
    assert bpy.ops.fss.find_faces_without_area() == {'FINISHED'}
    assert [o.name for o in bpy.context.selected_objects] == ['BROKEN'] and bpy.context.active_object == broken
    sel = [p.select for p in broken.data.polygons]
    assert sel == [False, True], sel
    r = uv_pack.measure(m)
    assert r['no_area_objects'] == ['BROKEN'], r['no_area_objects']
    uv_pack.write_report([r], 'Check All', 0.1)
    report = bpy.data.texts[uv_pack.REPORT_TEXT_NAME].as_string()
    assert 'WARNING faces without area in 1 object(s): BROKEN' in report, report
    # a triangle without 3D area is not a needle: the UV check leaves it to this check
    assert checks.faces_without_uv_area(bpy.context.view_layer)[0] == {} and r['uv_zero_islands'] == 0, r
    print(f"PASS: test_faces_without_area (threshold {uv_pack.FACE_AREA_MIN_CM2:g} cm2: BROKEN found and selected, its "
          "face 1 selected; the packer's report warns)")


class _Layout:
    """Records what a panel draws (background Blender has no UI to draw into)."""

    def __init__(self, calls):
        self.calls = calls

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if name == 'operator':
                op = SimpleNamespace()  # panels set operator properties on it
                self.calls.append(('_op', (args[0], op), kwargs))
                return op
            return self if name in ('row', 'column', 'box', 'split', 'grid_flow', 'column_flow') else None
        return call


def draw_panel(cls_name='FSS_PT_uv_marks'):
    calls = []
    getattr(bpy.types, cls_name).draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
    labels = [kw.get('text') for name, _a, kw in calls if name == 'label']
    return calls, labels


def draw_row(material):
    """The texture set list's row of a material, through FSS_UL_TextureSets.draw_item."""
    calls = []
    uv_marks.FSS_UL_TextureSets.draw_item(None, bpy.context, _Layout(calls), bpy.data, material, 0, None, '', 0)
    return [(kw.get('text'), kw.get('icon')) for name, _a, kw in calls if name == 'label']


def test_panel_rows():
    a, b, c, shared, private, fur = build_shared()
    c.select_set(True)
    uv_marks._results.clear()
    bpy.context.window_manager.fss_uv_pack_active = -1
    r = uv_pack.measure(shared)
    uv_marks._results['SHARED'] = r
    calls, labels = draw_panel()
    lists = [(args, kw) for name, args, kw in calls if name == 'template_list']
    assert lists == [(('FSS_UL_texture_sets', '', bpy.data, 'materials', bpy.context.window_manager,
                       'fss_uv_pack_active'), {'rows': 5})], lists
    # the list's rows: the selection's texture sets, the active object's first; name and last result
    assert [m_.name for m_ in uv_marks.texture_set_materials(bpy.context)] == ['SHARED', 'PRIVATE', 'FUR']
    rows = [draw_row(m_) for m_ in (shared, private, fur)]
    assert rows == [[('SHARED', 'MATERIAL'), (uv_pack.result_text(r) + ' (checked)', None)],
                    [('PRIVATE', 'MATERIAL'), ('', None)], [('FUR', 'LOCKED'), ('kept', None)]], rows
    # below the list, the active row's details; no active row yet: the first (the active object's first material)
    sets = [label for label in labels if label and label.startswith('Texture set: ')]
    packs = [args[1].material for name, args, _kw in calls if name == '_op' and args[0] == 'fss.uv_pack_texture_set']
    props = [(args[0].name, args[1]) for name, args, _kw in calls
             if name == 'prop' and isinstance(args[0], bpy.types.Material)]
    assert sets == ['Texture set: SHARED'] and packs == ['SHARED'], (sets, packs)
    assert props == [('SHARED', 'fss_uv_texture_size'), ('SHARED', 'fss_uv_margin_px'), ('SHARED', 'fss_uv_keep_uvs')]
    last = labels[labels.index('Last run') + 1]
    assert last == uv_pack.result_text(r) + ' (checked)', last
    ops = [kw.get('text') for name, _a, kw in calls if name == 'operator']
    assert ops == ['Lower', 'Higher', 'Clear', 'Free', 'Upright', 'Flip', 'Quarter', 'Clear', 'Pack', 'Check All'], ops
    # the active row: FUR
    bpy.context.window_manager.fss_uv_pack_active = list(bpy.data.materials).index(fur)
    calls, labels = draw_panel()
    assert [label for label in labels if label and label.startswith('Texture set: ')] == ['Texture set: FUR']
    assert labels[labels.index('Last run') + 1] == 'kept'
    # nothing selected: no list, a hint
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    bpy.context.view_layer.objects.active = None
    calls, labels = draw_panel()
    assert not [1 for name, _a, _kw in calls if name == 'template_list']
    assert 'Select objects to list their texture sets' in labels, labels
    # while running, only the progress
    uv_marks._progress = {'verb': 'Checking', 'index': 2, 'count': 3, 'set': 'PRIVATE', 'stage': 'concave pack 1',
                          'steps': 1}
    try:
        calls, _labels = draw_panel()
    finally:
        uv_marks._progress = None
    names = [name for name, _a, _kw in calls]
    ops = [kw.get('text') for name, _a, kw in calls if name == 'operator']
    assert 'progress' in names and ops == ['Cancel'], (names, ops)
    print(f"PASS: test_panel_rows (list of 3 texture sets, active object's first; rows with the last result; details "
          f"of the active row: size, margin, Keep UVs, Pack, Last run '{last}'; FUR when active; progress only while "
          "running)")


def test_texture_set_list():
    # more than 5 texture sets: every one is listed, in order, none capped
    reset()
    many = [mat(f'MANY_{index}') for index in range(7)]
    a = quad_obj('MANY_A', [(i * 0.5, 0, 0.2, 0.2) for i in range(7)], mats=many)
    extra = mat('EXTRA_B')
    b = quad_obj('MANY_B', [(0, 2, 0.2, 0.2)], mats=[extra])
    outside = mat('NOT_SELECTED')
    quad_obj('MANY_C', [(0, 4, 0.2, 0.2)], mats=[outside])
    for obj in bpy.context.view_layer.objects:
        obj.select_set(obj in (a, b))
    bpy.context.view_layer.objects.active = b
    expected = ['EXTRA_B'] + [f'MANY_{index}' for index in range(7)]
    flags, order = uv_marks.texture_set_rows(bpy.context, bpy.data.materials)
    materials = list(bpy.data.materials)
    assert sorted(order) == list(range(len(materials))), order  # a permutation: Blender's new index per item
    shown = [materials[i].name for _o, i in sorted((order[i], i) for i in range(len(materials)) if flags[i])]
    assert shown == expected, shown
    # through the list class (as Blender calls it while drawing), with the name filter
    bit = 1 << 30  # UIList.bitflag_filter_item (UILST_FLT_ITEM), an instance attribute only
    ul = SimpleNamespace(bitflag_filter_item=bit, filter_name='')
    flt, neworder = uv_marks.FSS_UL_TextureSets.filter_items(ul, bpy.context, bpy.data, 'materials')
    assert sorted(m_.name for m_, f in zip(materials, flt) if f) == sorted(expected) and neworder == order
    ul.filter_name = 'MANY_1'
    flt, _order = uv_marks.FSS_UL_TextureSets.filter_items(ul, bpy.context, bpy.data, 'materials')
    assert [m_.name for m_, f in zip(materials, flt) if f] == ['MANY_1'], flt
    # drawing wrote nothing: the material count and the active index are unchanged
    before = (len(bpy.data.materials), bpy.context.window_manager.fss_uv_pack_active)
    calls, labels = draw_panel()
    assert (len(bpy.data.materials), bpy.context.window_manager.fss_uv_pack_active) == before
    assert not [label for label in labels if label and 'more' in label], labels
    # the active row is kept by name: a new material moving the indices of bpy.data.materials keeps it
    wm = bpy.context.window_manager
    wm.fss_uv_pack_active = list(bpy.data.materials).index(bpy.data.materials['MANY_3'])
    index_before = wm.fss_uv_pack_active
    mat('AAA_FIRST')  # sorts before every other material
    assert wm.fss_uv_pack_active != index_before and uv_marks.active_texture_set(bpy.context).name == 'MANY_3'
    bpy.data.materials['MANY_3'].name = 'MANY_3_RENAMED'  # a renamed material falls back to the first row
    assert uv_marks.active_texture_set(bpy.context).name == 'EXTRA_B'
    print(f"PASS: test_texture_set_list ({len(expected)} texture sets of 2 selected objects listed, the active "
          "object's first; NOT_SELECTED filtered out; the name filter works; drawing writes nothing; the active row "
          "follows its material when indices move)")


def test_uv_editor_panel():
    # decision 119: the same Packing section in the UV editor's sidebar, drawn by the same code
    build_shared()
    view3d, image = bpy.types.FSS_PT_uv_marks, bpy.types.FSS_PT_uv_marks_image
    assert (image.bl_space_type, image.bl_region_type, image.bl_category, image.bl_label) == (
        'IMAGE_EDITOR', 'UI', 'FSS MSFS Tools', 'UV Auto Packing'), image
    assert view3d.bl_space_type == 'VIEW_3D' and view3d.draw is image.draw  # one draw function, not a copy
    # only in the UV editor, not in the image viewer
    assert image.poll(SimpleNamespace(space_data=SimpleNamespace(mode='UV')))
    assert not image.poll(SimpleNamespace(space_data=SimpleNamespace(mode='VIEW')))
    calls_3d, _labels = draw_panel('FSS_PT_uv_marks')
    calls_uv, labels = draw_panel('FSS_PT_uv_marks_image')
    strip = [[(name, kw.get('text')) for name, _a, kw in calls] for calls in (calls_3d, calls_uv)]
    assert strip[0] == strip[1] and 'Texture set: SHARED' in labels, strip[1]
    texts = [kw.get('text') for name, _a, kw in calls_uv if name == 'operator']
    assert 'Pack' in texts and 'Check All' in texts and 'Lower' in texts, texts
    # Visibility Scoring stays in the 3D viewport
    assert bpy.types.FSS_PT_visibility.bl_parent_id == 'FSS_PT_uv_marks'
    # the redraw helper tags the UV editor too
    assert set(uv_marks.SPACES) == {'VIEW_3D', 'IMAGE_EDITOR'}
    print(f"PASS: test_uv_editor_panel (IMAGE_EDITOR UI 'FSS MSFS Tools' > Packing draws the same {len(strip[1])} calls "
          "as the 3D viewport's)")


def test_square_size_migration():
    reset()
    sizes = {'OLD_2048_1024': (3, 2), 'OLD_HEIGHT_8192': (None, 5), 'OLD_WIDTH_512': (1, None)}
    for name, (width, height) in sizes.items():
        material = bpy.data.materials.new(name)
        system = material.bl_system_properties_get(do_create=True)
        for key, value in zip(uv_marks.OLD_SIZE_KEYS, (width, height)):
            if value is not None:
                system[key] = value  # the enum's item index, as 0.30.0 to 0.32.0 stored it
    scripted = bpy.data.materials.new('OLD_SCRIPTED')
    scripted['fss_uv_texture_width'] = '8192'  # a custom property written by a script
    untouched = mat('NEW_1024', 1024)
    report = uv_marks.run_migration()
    got = {m_.name: uv_marks.texture_size(m_) for m_ in bpy.data.materials}
    assert got == {'OLD_2048_1024': 2048, 'OLD_HEIGHT_8192': 8192, 'OLD_WIDTH_512': 4096, 'OLD_SCRIPTED': 8192,
                   'NEW_1024': 1024}, got
    assert report['size'] == 4 and report['kept'] == 0, report
    for m_ in bpy.data.materials:
        system = m_.bl_system_properties_get()
        for key in uv_marks.OLD_SIZE_KEYS:
            assert key not in m_ and (system is None or key not in system), (m_.name, key)
    assert uv_marks._migration['size'] == 4
    # idempotent: a second run converts nothing and changes nothing
    again = uv_marks.run_migration()
    assert again['size'] == 0 and {m_.name: uv_marks.texture_size(m_) for m_ in bpy.data.materials} == got, again
    # an old key written again next to a square size: the square size is kept, the old key removed
    untouched.bl_system_properties_get()['fss_uv_texture_width'] = 5
    kept = uv_marks.run_migration()
    assert kept['kept'] == 1 and kept['size'] == 0 and uv_marks.texture_size(untouched) == 1024, kept
    assert 'fss_uv_texture_width' not in untouched.bl_system_properties_get()
    print(f"PASS: test_square_size_migration (2048 x 1024 -> 2048, height 8192 -> 8192, width 512 -> 4096, scripted "
          f"8192; {report['size']} converted, second run none, a newer size kept)")


def test_faces_without_uv_area():
    reset()
    m = mat('NEEDLE', 1024)
    me = bpy.data.meshes.new('NEEDLE')
    # a quad and a triangle with 3D area whose UVs lie on the quad's edge line: a needle inside the quad's island
    me.from_pydata([(0, 0, 0), (0.2, 0, 0), (0.2, 0.2, 0), (0, 0.2, 0), (0.5, 0.1, 0)], [],
                   [(0, 1, 2, 3), (1, 4, 2)])
    uvl = me.uv_layers.new(name='UVMap')
    lv = np.zeros(len(me.loops), np.int64)
    me.loops.foreach_get('vertex_index', lv)
    uvl.data.foreach_set('uv', (np.array([(0, 0), (0.2, 0), (0.2, 0.2), (0, 0.2), (0.2, 1.0)]) * 0.1)[lv].ravel())
    me.materials.append(m)
    needle = quad_obj('NEEDLE', None, mesh=me)
    clean = quad_obj('CLEAN', [(1, 0, 0.2, 0.2)], mats=[m])
    # an island with no UV area at all (a line) is left out of packing: its triangles are not needles
    quad_obj('LINE', [(2, 0, 0.2, 0.2)], mats=[m], uv_rects=[(0.5, 0.5, 0.3, 0.0)])
    found, faces, islands = checks.faces_without_uv_area(bpy.context.view_layer)
    assert list(found) == [needle] and found[needle].tolist() == [1] and (faces, islands) == (1, 1), found
    clean.select_set(True)
    assert bpy.ops.fss.find_faces_without_uv_area() == {'FINISHED'}
    assert [o.name for o in bpy.context.selected_objects] == ['NEEDLE'] and bpy.context.active_object == needle
    sel = [p.select for p in needle.data.polygons]
    assert sel == [False, True], sel
    # the reports list it per texture set: Pack's and Check All's
    r = uv_pack.measure(m)
    assert r['uv_zero_islands'] == 1 and r['uv_zero_objects'] == ['NEEDLE'] and r['zero_area_islands'] == 1, r
    for obj in bpy.context.view_layer.objects:
        obj.select_set(obj == clean)
    bpy.context.view_layer.objects.active = clean
    assert bpy.ops.fss.uv_pack_texture_set(material='NEEDLE') == {'FINISHED'}
    warning = ('WARNING triangles without UV area in 1 island(s) of 1 object(s), largest in the layout first: NEEDLE. '
               'They push islands out of the layout')
    for kind in ('Pack', 'Check All'):
        if kind == 'Check All':
            assert bpy.ops.fss.uv_pack_check_all() == {'FINISHED'}
        report = bpy.data.texts[uv_pack.REPORT_TEXT_NAME].as_string()
        block = report[report.index('## NEEDLE: '):]
        assert f'# {kind}: 1 texture set(s)' in report and warning in block and 'Accept + Unwrap' in block, report
    assert draw_row(m)[0] == ('NEEDLE', 'ERROR')
    _calls, labels = draw_panel()
    assert '1 island(s) with triangles without UV area: re-unwrap them' in labels, labels
    print(f"PASS: test_faces_without_uv_area (threshold {uv_pack.UV_TRI_AREA_MIN_PX2:g} px2: NEEDLE found and its face "
          "1 selected, the line island not counted; Pack and Check All reports warn per texture set; the row and "
          "the details flag it)")


def test_report_order():
    # the report names the objects whose needle islands span the most layout pixels first, not by name
    parts = [(None, [SimpleNamespace(name=n)], None) for n in ('A_SCREW', 'B_CEILING', 'C_BAR')]
    ts = SimpleNamespace(p_uv=np.array([5.0, 900.0, 300.0, 40.0]), lo=np.array([20.0, 20.0, 20.0, 20.0]),
                         cur=np.array([10.0, 10.0, 10.0, 10.0]), part_of=np.array([0, 1, 2, 0]), parts=parts)
    mask = np.array([True, True, True, False])
    names = uv_pack.TextureSet.objects_by_layout_size(ts, mask)
    assert names == ['B_CEILING', 'C_BAR', 'A_SCREW'], names
    print("PASS: test_report_order (B_CEILING 1800 px, C_BAR 600 px, A_SCREW 10 px: largest first)")


def main():
    test_exact_density()
    test_underflow_and_sizes()
    test_fit()
    test_overflow_and_clamp()
    test_directions()
    test_linked_and_split()
    test_zero_area_and_spike()
    test_pack_operator_and_undo()
    test_edit_mode()
    test_check_all_and_keep()
    test_faces_without_area()
    test_faces_without_uv_area()
    test_square_size_migration()
    test_panel_rows()
    test_texture_set_list()
    test_uv_editor_panel()
    test_report_order()
    print("ALL TESTS PASSED")


main()
