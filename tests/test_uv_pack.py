"""The UV packer per texture set (UV journal decisions 112 to 117): density first with one t per set, underflow,
fit and overflow with k and the needed size (256 to 8192, "does not fit even at 8192"), direction marks, non-square
textures, linked duplicates, islands split by material, islands without UV area kept, Pack and its undo, Check All
writing nothing, Keep UVs, objects included that were not selected, Find Faces Without Area, the report text and the
Packing rows. The synthetic cases are those of tests/uv_prototype/pack_density_proto.py, run through uv_pack.

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


def mat(name, w=4096, h=4096, margin=8):
    m = bpy.data.materials.new(name)
    m.fss_uv_texture_width = str(w)
    m.fss_uv_texture_height = str(h)
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
    assert need[0] >= ext and need[0] / 2 < ext and need == (4096, 4096), (ext, need)
    text = uv_pack.result_text(r)
    assert text.startswith('fits ') and text.endswith(' %') and 'would do' not in text, text
    # a tiny set: the needed size is clamped to 256 at the bottom
    reset(0.9, 1.1)
    m = mat('TINY')
    quad_obj('TI', [(0, 0, 0.02, 0.02), (1, 0, 0.03, 0.01)], mats=[m, m])
    r = uv_pack.measure(m)
    assert r['mode'] == 'underflow' and r['k'] * 4096 < 128 and r['needed_size'] == (256, 256), r
    assert r['fill_pct'] <= 100.0 and uv_pack.result_text(r).endswith('256 x 256 would do'), uv_pack.result_text(r)
    print(f"PASS: test_underflow_and_sizes (t=1, 1 pack, extent {ext:.0f} px needs 4096; tiny set k={r['k']:.4f} "
          f"needs 256 x 256, not {uv_pack.next_pow2(r['k'] * 4096)})")


def test_fit():
    reset(0.8, 1.25)
    m = mat('MID', 1024, 1024)
    rng = np.random.default_rng(5)
    rects = [(i * 0.5, 0, float(s), float(s)) for i, s in enumerate(rng.uniform(0.05, 0.12, 24))]
    quad_obj('MI', rects, mats=[m] * len(rects))
    r = uv_pack.measure(m)
    assert r['mode'] == 'fit' and 0 < r['t'] < 1 and r['k'] <= 1 and ok(r), r
    assert r['needed_size'] == (1024, 1024) and r['fill_pct'] == r['fill_current_pct'], r
    print(f"PASS: test_fit (t={r['t']:.3f}, k={r['k']:.4f}, {r['packs']} packs, fill {r['fill_pct']:.1f} %)")


def test_overflow_and_clamp():
    reset(0.9, 1.1)
    m = mat('OVER', 1024, 1024)
    rng = np.random.default_rng(5)
    rng.uniform(0.05, 0.12, 24)
    rects = [(i * 0.8, 0, float(s), float(s * 0.7)) for i, s in enumerate(rng.uniform(0.15, 0.4, 20))]
    obj = quad_obj('OV', rects, mats=[m] * len(rects))
    r = uv_pack.measure(m)
    k_check = max(r['extent_px']) / 1024
    assert r['mode'] == 'overflow' and r['t'] == 0 and r['k'] > 1 and abs(k_check - r['k']) < 1e-6 and ok(r), r
    assert r['needed_size'] == (uv_pack.next_pow2(r['k'] * 1024),) * 2 and r['fits_8192'], r
    assert uv_pack.result_text(r) == f"needs x{r['k']:.2f}: {r['needed_size'][0]} x {r['needed_size'][1]}"
    k1 = r['k']
    # the same islands at 4096 px for 1024 px of texture: k x 4096 is above 8192
    m.fss_uv_texture_width = m.fss_uv_texture_height = '4096'
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


def test_non_square():
    reset()
    m = mat('WIDE', 4096, 2048)
    rects = [(i * 0.5, 0, 0.2, 0.2) for i in range(8)] + [(0, 1, 1.2, 0.3)]
    obj = quad_obj('NS', rects, mats=[m] * len(rects))
    r = uv_pack.pack(m)
    uv = uvs(obj)
    q = uv.reshape(-1, 4, 2) * np.array([4096, 2048])
    l1 = np.linalg.norm(q[:8, 1] - q[:8, 0], axis=1)
    l2 = np.linalg.norm(q[:8, 3] - q[:8, 0], axis=1)
    sq = float(np.abs(l1 / l2 - 1).max())
    dens = [quad_density(qq, w * 100, h * 100) for qq, (_x, _y, w, h) in zip(q, rects)]
    err = max(abs(d - 20.48) / 20.48 for d in dens)
    assert sq < 1e-4 and err < 1e-4 and ok(r) and (uv >= 0).all() and (uv <= 1).all(), (sq, err, r)
    print(f"PASS: test_non_square (4096 x 2048: side ratio error {sq:.1e}, density error {err:.1e}, {r['mode']})")


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
    ma, mb = mat('SPLIT_A'), mat('SPLIT_B', 2048, 2048)
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
    # islands with a zero-area spike (a degenerate UV triangle sticking out) among small islands
    reset()
    m = mat('SPIKE', 1024, 1024)
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
    assert ok(r), r
    print(f"PASS: test_zero_area_and_spike (line island kept unchanged; spike set gap {r['min_gap_px']:.2f} px, "
          f"0 overlaps, {r['shape_method']})")


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


def test_panel_rows():
    a, b, c, shared, private, fur = build_shared()
    c.select_set(True)
    uv_marks._results.clear()
    r = uv_pack.measure(shared)
    uv_marks._results['SHARED'] = r
    calls = []
    bpy.types.FSS_PT_uv_marks.draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
    labels = [kw.get('text') for name, _a, kw in calls if name == 'label']
    sets = [label for label in labels if label and label.startswith('Texture set: ')]
    assert sets == ['Texture set: SHARED', 'Texture set: PRIVATE', 'Texture set: FUR'], sets
    packs = [args[1].material for name, args, _kw in calls if name == '_op' and args[0] == 'fss.uv_pack_texture_set']
    assert packs == ['SHARED', 'PRIVATE', 'FUR'], packs
    keeps = [args for name, args, kw in calls if name == 'prop' and args[1] == 'fss_uv_keep_uvs']
    assert [m_.name for m_, _p in keeps] == ['SHARED', 'PRIVATE', 'FUR'], keeps
    last = [labels[i + 1] for i, label in enumerate(labels) if label == 'Last run']
    assert last == [uv_pack.result_text(r) + ' (checked)', 'not packed or checked yet', 'kept'], last
    ops = [kw.get('text') for name, _a, kw in calls if name == 'operator']
    assert 'Check All' in ops and ops.count('Pack') == 3, ops
    # while running, only the progress
    uv_marks._progress = {'verb': 'Checking', 'index': 2, 'count': 3, 'set': 'PRIVATE', 'stage': 'concave pack 1',
                          'steps': 1}
    try:
        calls = []
        bpy.types.FSS_PT_uv_marks.draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
    finally:
        uv_marks._progress = None
    names = [name for name, _a, _kw in calls]
    ops = [kw.get('text') for name, _a, kw in calls if name == 'operator']
    assert 'progress' in names and ops == ['Cancel'], (names, ops)
    print(f"PASS: test_panel_rows (3 texture sets of the selection, active first; Keep UVs, Pack, Last run "
          f"'{last[0]}', 'kept'; Check All; progress with Cancel only while running)")


def main():
    test_exact_density()
    test_underflow_and_sizes()
    test_fit()
    test_overflow_and_clamp()
    test_directions()
    test_non_square()
    test_linked_and_split()
    test_zero_area_and_spike()
    test_pack_operator_and_undo()
    test_edit_mode()
    test_check_all_and_keep()
    test_faces_without_area()
    test_panel_rows()
    print("ALL TESTS PASSED")


main()
