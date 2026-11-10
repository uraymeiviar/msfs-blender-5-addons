"""The UV packer per texture set (UV journal decisions 112 to 121): density first with one t per set, underflow,
fit and overflow with k and the needed size (256 to 8192, "does not fit even at 8192"), direction marks, linked
duplicates, islands split by material, islands without UV area kept, Pack and its undo, Check All writing nothing,
Keep UVs, objects included that were not selected, Find Faces Without Area, Find Faces Without UV Area and the report's
needle warning, the migration to square sizes, the texture set list and the Packing panel in the 3D viewport and the
UV editor, and the raster step that uses free space (uv_fill): islands inside a ring, direction marks, its fallback to
Pack Islands. The synthetic cases are those of tests/uv_prototype/pack_density_proto.py, run through uv_pack.

To run:
"<blender>" -b --factory-startup --python tests/test_uv_pack.py
"""

import math
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import bmesh
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
from fss_blender_tools import checks, uv_autoseam, uv_fill, uv_islands, uv_marks, uv_pack, visibility_core  # noqa: E402

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


def test_material_factor():
    reset()
    scene = bpy.context.scene
    target = uv_marks.target_density(scene)
    half, full = mat('HALF'), mat('FULL')
    # Two faces joined in UV with different materials: the packer makes them two islands, one per material
    me = bpy.data.meshes.new('JOINED')
    verts = [(0, 0, 0), (0.5, 0, 0), (1, 0, 0), (0, 0.5, 0), (0.5, 0.5, 0), (1, 0.5, 0)]
    me.from_pydata(verts, [], [(0, 1, 4, 3), (1, 2, 5, 4)])
    uvl = me.uv_layers.new(name='UVMap')
    lv = np.zeros(len(me.loops), np.int64)
    me.loops.foreach_get('vertex_index', lv)
    uvl.data.foreach_set('uv', (np.array(verts)[:, :2] * 0.1)[lv].ravel())
    me.materials.append(half)
    me.materials.append(full)
    me.polygons.foreach_set('material_index', [0, 1])
    obj = quad_obj('JOINED', [], mesh=me)
    view_layer = bpy.context.view_layer

    def rows():
        return {row['material'].name: row for row in uv_pack.object_islands(obj, scene, view_layer)[0]}

    assert len(uv_pack.object_islands(obj, scene, view_layer)[0]) == 2 and abs(rows()['HALF']['high'] - target) < 1e-6
    key = uv_islands._key(obj, scene)
    setattr(half, uv_marks.MATERIAL_FACTOR_PROP, 0.5)
    assert uv_islands._key(obj, scene) != key, "the island list must follow the material's factor"
    got = rows()
    assert abs(got['HALF']['low'] - target * 0.5) < 1e-6 and abs(got['HALF']['high'] - target * 0.5) < 1e-6, got['HALF']
    assert abs(got['FULL']['high'] - target) < 1e-6, got['FULL']
    # The real pack: the density on the texture, each set by its own factor
    r = uv_pack.pack(half)
    q = uvs(obj).reshape(-1, 4, 2)[0] * 4096
    assert ok(r) and abs(quad_density(q, 50.0, 50.0) - target * 0.5) / (target * 0.5) < 1e-4, (quad_density(q, 50.0, 50.0), r)
    r = uv_pack.pack(full)
    q = uvs(obj).reshape(-1, 4, 2)[1] * 4096
    assert ok(r) and abs(quad_density(q, 50.0, 50.0) - target) / target < 1e-4, (quad_density(q, 50.0, 50.0), r)
    # Unticked: ignored, the number stays
    setattr(half, uv_marks.MATERIAL_TICK_PROP, False)
    assert abs(rows()['HALF']['high'] - target) < 1e-6 and getattr(half, uv_marks.MATERIAL_FACTOR_PROP) == 0.5
    setattr(half, uv_marks.MATERIAL_TICK_PROP, True)
    # A multiplier set by hand on an island stays final
    uv_marks.set_face_overrides(me, np.array([0]), 2.0)
    assert abs(rows()['HALF']['high'] - target * 2.0) < 1e-5, rows()['HALF']
    print("PASS: test_material_factor (x0.5 on the texture, per material, tick, an island's own multiplier stays final)")


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
    return calls


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
                       'fss_uv_pack_active'), {'rows': 3})], lists  # as many rows as sets, up to 5
    # the list's rows: the selection's texture sets, the active object's first
    assert [m_.name for m_ in uv_marks.texture_set_materials(bpy.context)] == ['SHARED', 'PRIVATE', 'FUR']
    assert not [label for label in labels if label and label.startswith('Texture set: ')] and 'Last run' not in labels
    material_props = {uv_marks.MATERIAL_TICK_PROP, uv_marks.MATERIAL_FACTOR_PROP}  # the Material rows of the table
    assert not [1 for name, args, _kw in calls if name == 'prop' and isinstance(args[0], bpy.types.Material) and args[1] not in material_props]
    ops = [kw.get('text') for name, _a, kw in calls if name == 'operator' and kw.get('text')]
    assert ops == ['Check', 'SHARED', 'PRIVATE', 'SEL_A', 'Pack All (2)'], ops  # SHARED and PRIVATE; FUR is Keep UVs
    for material, kept in ((shared, False), (private, False), (fur, True)):
        row = draw_row(material)
        props = [(args[1], kw) for name, args, kw in row if name == 'prop']
        assert props == [('fss_uv_keep_uvs', {'text': '', 'invert_checkbox': True}), ('fss_uv_texture_size', {'text': ''}),
                         ('fss_uv_margin_px', {'text': ''})], props
        texts = [kw.get('text') for name, _a, kw in row if name == 'operator']
        assert texts == ['', material.name, 'Pack'], texts
        packs = [args[1].material for name, args, _kw in row if name == '_op' and args[0] == 'fss.uv_pack_texture_set']
        assert packs == [material.name], packs
    # the name's tooltip: the last run and what is wrong; the warning icon
    tip = uv_marks.FSS_OT_UvTextureSetInfo.description(bpy.context, SimpleNamespace(material='SHARED'))
    assert uv_pack.result_text(r) + ' (checked)' in tip and tip.startswith('SHARED'), tip
    icons = [kw['icon'] for name, _a, kw in draw_row(shared) if name == 'operator' and kw.get('text') == 'SHARED']
    assert icons == ['NONE'], icons
    shared.fss_uv_margin_px = 2
    icons = [kw['icon'] for name, _a, kw in draw_row(shared) if name == 'operator' and kw.get('text') == 'SHARED']
    assert icons == ['ERROR'] and 'Margin under' in uv_marks.FSS_OT_UvTextureSetInfo.description(
        bpy.context, SimpleNamespace(material='SHARED')), icons
    shared.fss_uv_margin_px = 8
    uv_marks._results['SHARED'] = dict(r, mode='overflow', fits_8192=True)
    assert uv_marks.set_problems(shared) == ['Does not fit this texture size'], uv_marks.set_problems(shared)
    uv_marks._results['SHARED'] = r
    assert 'kept' in uv_marks.FSS_OT_UvTextureSetInfo.description(bpy.context, SimpleNamespace(material='FUR'))
    # nothing selected: no list, a hint
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    bpy.context.view_layer.objects.active = None
    calls, labels = draw_panel()
    assert not [1 for name, _a, _kw in calls if name == 'template_list']
    assert 'Select objects to list their texture sets' in labels, labels
    # while running, only the progress
    uv_marks._progress = {'verb': 'Checking', 'index': 2, 'count': 3, 'set': 'PRIVATE', 'stage': 'Trying layout 1',
                          'fraction': 0.5}
    try:
        calls, _labels = draw_panel()
    finally:
        uv_marks._progress = None
    names = [name for name, _a, _kw in calls]
    ops = [kw.get('text') for name, _a, kw in calls if name == 'operator']
    assert 'progress' in names and ops == ['Cancel'], (names, ops)
    # Pack All with several sets can be cancelled too; one set packing cannot
    uv_marks._progress = {'verb': 'Packing', 'index': 2, 'count': 3, 'set': 'PRIVATE', 'stage': '', 'fraction': 0.5}
    try:
        cancel, _labels = draw_panel()
        assert [kw.get('text') for name, _a, kw in cancel if name == 'operator'] == ['Cancel']
        uv_marks._progress['count'] = 1
        single, _labels = draw_panel()
        assert not [1 for name, _a, _kw in single if name == 'operator']
    finally:
        uv_marks._progress = None
    # half of the second of three sets
    assert [abs(kw['factor'] - 0.5) < 1e-9 for name, _a, kw in calls if name == 'progress'] == [True], calls
    print("PASS: test_panel_rows (a table of 3 texture sets with tick, select, size, margin and Pack; the last run in "
          "the tooltip; Pack All (2); progress only while running)")


def test_check_results():
    reset(fmin=0.8, fmax=1.2)
    uv_marks._results.clear()
    panel = bpy.types.FSS_PT_uv_marks_results
    assert not panel.poll(bpy.context), "no results yet: no sub-panel"
    assert bpy.types.FSS_PT_uv_marks_image_results.draw is panel.draw
    sets = {'ROOM': (4096, 1.0), 'SQUEEZED': (2048, 1.0), 'OVER': (2048, 2.0)}
    objects = {}
    for name, (size, side) in sets.items():
        objects[name] = quad_obj('OBJ_' + name, [(0, 0, side, side)], mats=[mat(name, size=size)])
    kept = mat('KEPT')
    kept.fss_uv_keep_uvs = True
    quad_obj('OBJ_KEPT', [(0, 0, 0.5, 0.5)], mats=[kept])
    before = {name: uvs(obj).copy() for name, obj in objects.items()}
    assert bpy.ops.fss.uv_pack_check_all() == {'FINISHED'}
    for name, obj in objects.items():
        assert np.array_equal(uvs(obj), before[name]), f'{name}: Check wrote UVs'
    results = uv_marks._results
    assert {name: results[name]['mode'] for name in sets} == {'ROOM': 'underflow', 'SQUEEZED': 'fit', 'OVER': 'overflow'}, results
    assert panel.poll(bpy.context) and len(uv_marks.measured_results()) == 3, "the kept set has no row"
    # Room: 1 / k with room left, none for a set lowered inside its range, below 1 for an overflow
    assert abs(uv_marks.result_room(results['ROOM']) - 1.0 / results['ROOM']['k']) < 1e-9 and uv_marks.result_room(results['ROOM']) > 1.5
    assert uv_marks.result_room(results['SQUEEZED']) == 1.0 and uv_marks.result_room(results['OVER']) < 1.0
    width, height = results['ROOM']['extent_px']
    assert abs(uv_marks.result_used(results['ROOM']) - width * height / 4096 ** 2) < 1e-9 and uv_marks.result_used(results['OVER']) == 1.0
    # Tightest first, and only the measured sets
    ui_list = SimpleNamespace(filter_name='', bitflag_filter_item=1 << 30)
    flags, order = uv_marks.FSS_UL_CheckResults.filter_items(ui_list, bpy.context, bpy.data, 'materials')
    shown = sorted((position, m.name) for m, flag, position in zip(bpy.data.materials, flags, order) if flag)
    assert [name for _position, name in shown] == ['OVER', 'SQUEEZED', 'ROOM'], shown
    assert sorted(order) == list(range(len(bpy.data.materials))), order

    def row_of(material):
        layout = _Layout([])
        uv_marks.FSS_UL_CheckResults.draw_item(None, bpy.context, layout, bpy.data, bpy.data.materials[material], 0, None, '', 0)
        return layout, layout.calls

    layout, calls = row_of('ROOM')
    bars = [kw for name, _a, kw in calls if name == 'progress']
    assert bars == [{'factor': uv_marks.result_used(results['ROOM']), 'type': 'BAR', 'text': f'{width:.0f} x {height:.0f} / 4096'}], bars
    params = {p.identifier for p in bpy.types.UILayout.bl_rna.functions['progress'].parameters}
    assert set(bars[0]) <= params, params
    assert layout.active is True
    assert f"x{uv_marks.result_room(results['ROOM']):.2f}" in [kw.get('text') for name, _a, kw in calls if name == 'label']
    assert [kw['icon'] for name, _a, kw in calls if name == 'operator'] == ['RESTRICT_SELECT_OFF']
    _layout, calls = row_of('OVER')
    assert [kw['icon'] for name, _a, kw in calls if name == 'operator'] == ['ERROR']
    _layout, calls = row_of('SQUEEZED')
    assert 'full' in [kw.get('text') for name, _a, kw in calls if name == 'label']
    tip = uv_marks.FSS_OT_UvCheckSelect.description(bpy.context, SimpleNamespace(material='ROOM'))
    assert uv_pack.result_text(results['ROOM']) + ' (checked)' in tip and 'select the objects' in tip, tip
    # A click selects every object with the material
    assert bpy.ops.fss.uv_check_select(material='OVER') == {'FINISHED'}
    assert bpy.context.selected_objects == [objects['OVER']], bpy.context.selected_objects
    # The summary: the overflow first, the target it would take
    target = uv_marks.target_density(bpy.context.scene)
    calls, labels = draw_panel('FSS_PT_uv_marks_results')
    drop = uv_marks.result_room(results['OVER'])
    assert '1 of 3 sets overflow' in labels and f'Target {target * drop:.2f} px/cm (x{drop:.2f}), or larger textures' in labels, labels
    assert not [label for label in labels if label and label.startswith('Numbers changed')], labels
    lists = [args[0] for name, args, _kw in calls if name == 'template_list']
    assert lists == ['FSS_UL_check_results'], lists
    # A setting changes: the result is out of date until it is measured again
    for change in (lambda: setattr(bpy.context.scene, 'fss_uv_target_density', 25.0),
                   lambda: setattr(bpy.data.materials['ROOM'], 'fss_uv_margin_px', 4),
                   lambda: setattr(bpy.data.materials['ROOM'], 'fss_uv_texture_size', '2048'),
                   lambda: setattr(bpy.data.materials['ROOM'], uv_marks.MATERIAL_FACTOR_PROP, 0.5),
                   lambda: setattr(objects['ROOM'], 'fss_uv_direction_mark', 'UPRIGHT')):
        for name in results:
            results[name]['generation'] = uv_marks._settings_generation
        change()
        assert uv_marks.is_stale(results['ROOM']), "a change did not mark the results"
    _calls, labels = draw_panel('FSS_PT_uv_marks_results')
    assert 'Numbers changed: press Check again' in labels, labels
    assert row_of('ROOM')[0].active is False
    # Everything fits, one set full; then all have room: how far the target can rise
    bpy.context.scene.fss_uv_target_density = target
    bpy.data.materials['ROOM'].fss_uv_texture_size = '4096'
    setattr(bpy.data.materials['ROOM'], uv_marks.MATERIAL_FACTOR_PROP, 1.0)
    bpy.data.materials['OVER'].fss_uv_texture_size = '8192'
    assert bpy.ops.fss.uv_pack_check_all() == {'FINISHED'}
    assert not any(uv_marks.is_stale(result) for result in uv_marks.measured_results())
    icon, headline, detail = uv_marks.results_summary(target)
    assert (icon, headline) == ('CHECKMARK', 'All 3 sets fit') and detail.startswith('1 full, typical room x'), (headline, detail)
    bpy.data.materials['SQUEEZED'].fss_uv_texture_size = '4096'
    assert bpy.ops.fss.uv_pack_check_all() == {'FINISHED'}
    rooms = [uv_marks.result_room(result) for result in uv_marks.measured_results()]
    assert uv_marks.results_summary(target)[2] == f'Target can rise x{min(rooms):.2f}, to {target * min(rooms):.2f} px/cm', uv_marks.results_summary(target)
    print(f"PASS: test_check_results (no UVs written, tightest first, room x{min(rooms):.2f}, bar, tooltip, select, out of date)")


def test_pack_all():
    a, b, c, shared, private, fur = build_shared()
    uv_marks._results.clear()
    c.select_set(True)  # FUR is listed too, but is Keep UVs
    before = all_uvs()
    assert bpy.ops.fss.uv_pack_all() == {'FINISHED'}
    assert set(uv_marks._results) == {'SHARED', 'PRIVATE'} and all(
        result['written'] for result in uv_marks._results.values()), uv_marks._results
    after_uvs = all_uvs()
    assert not np.array_equal(before['SEL_A'], after_uvs['SEL_A']) and not np.array_equal(before['OTHER'], after_uvs['OTHER'])
    assert np.array_equal(before['HAIR'], after_uvs['HAIR'])  # the unticked set stays
    assert {obj.name for obj in bpy.context.selected_objects} == {'SEL_A', 'HAIR'}
    report = bpy.data.texts[uv_pack.REPORT_TEXT_NAME].as_string()
    assert '# Pack: 2 texture set(s)' in report and 'no UVs written' not in report, report
    # An untick leaves it out, and the button counts what is ticked
    private.fss_uv_keep_uvs = True
    _calls, _labels = draw_panel()
    assert 'Pack All (1)' in [kw.get('text') for name, _a, kw in _calls if name == 'operator']
    private.fss_uv_keep_uvs = False
    print("PASS: test_pack_all (the ticked sets packed in turn, the unticked one left alone, selection kept, reported)")


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
    assert wm.fss_uv_pack_active != index_before and bpy.data.materials[wm.fss_uv_pack_active].name == 'MANY_3'
    bpy.data.materials['MANY_3'].name = 'MANY_3_RENAMED'  # a renamed material has no highlighted row any more
    assert wm.fss_uv_pack_active == -1
    # A button on each row selects the objects using that row's material; the panel below the list has none
    calls = []
    uv_marks.FSS_UL_TextureSets.draw_item(None, bpy.context, _Layout(calls), bpy.data, bpy.data.materials['EXTRA_B'], 0, None, '', 0)
    buttons = [args[1] for name, args, _kw in calls if name == '_op' and args[0] == 'fss.materials_select']
    assert [button.material for button in buttons] == ['EXTRA_B'], calls
    calls, _labels = draw_panel()
    below_list = calls[[name for name, _args, _kw in calls].index('template_list'):]  # the table's Material rows are above it
    assert not any(name in ('operator', '_op') and args[0] == 'fss.materials_select' for name, args, _kw in below_list), below_list
    assert bpy.ops.fss.materials_select(material='EXTRA_B') == {'FINISHED'}
    assert [obj.name for obj in bpy.context.selected_objects] == ['MANY_B'] and bpy.context.view_layer.objects.active.name == 'MANY_B'
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
    assert strip[0] == strip[1], strip[1]
    texts = [kw.get('text') for name, _a, kw in calls_uv if name == 'operator']
    assert 'Pack All (2)' in texts and 'Check' in texts, texts
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
    assert [kw['icon'] for name, _a, kw in draw_row(m) if name == 'operator' and kw.get('text') == 'NEEDLE'] == ['ERROR']
    tip = uv_marks.FSS_OT_UvTextureSetInfo.description(bpy.context, SimpleNamespace(material='NEEDLE'))
    assert '1 island(s) with triangles without UV area: re-unwrap them' in tip, tip
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


def ring_obj(name, m, outer=1.0, inner=0.6, y=0.0):
    """A square ring in the XY plane, one island, UVs = its coordinates x 0.1."""
    a, b = (outer - inner) / 2, (outer + inner) / 2
    out = [(0, 0), (outer, 0), (outer, outer), (0, outer)]
    ins = [(a, a), (b, a), (b, b), (a, b)]
    verts = [(px, py + y, 0) for px, py in out + ins]
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], [(i, (i + 1) % 4, 4 + (i + 1) % 4, 4 + i) for i in range(4)])
    uvl = me.uv_layers.new(name='UVMap')
    lv = np.zeros(len(me.loops), np.int64)
    me.loops.foreach_get('vertex_index', lv)
    uvl.data.foreach_set('uv', (np.array(verts)[:, :2] * 0.1)[lv].ravel())
    me.materials.append(m)
    return quad_obj(name, None, mesh=me)


def plain_k(m):
    """k of the same set with Pack Islands alone (the layout before the raster step)."""
    parts, _conflicts = uv_pack.gather(bpy.context.view_layer, m)
    ts = uv_pack.TextureSet(m, parts, bpy.context.scene, {})
    ts.use_fill = False
    ts.build_temp()
    try:
        return uv_pack.pack_set(ts)[2]
    finally:
        ts.remove_temp()


def inside_ring(ring, obj, m):
    """How many of the object's quads (4 corners each) lie inside the ring's hole, with the set's gap."""
    q = uvs(ring).reshape(-1, 4, 2) * 4096
    # each of the ring's 4 quads has its outer corners first: corner 3 is on the inner side
    inner = np.array([q[i, 3] for i in range(4)])
    lo, hi = inner.min(0), inner.max(0)
    gap = uv_marks.margin(m)
    corners = uvs(obj).reshape(-1, 4, 2) * 4096
    return int(((corners.min(1) >= lo + gap - 1e-3) & (corners.max(1) <= hi - gap + 1e-3)).all(1).sum())


def test_fill_ring():
    # 25 squares fit the ring's hole. Pack Islands (CONCAVE) uses the hole too, but leaves one square out and the layout
    # grows beyond the ring; the step gets all of them in
    reset()
    m = mat('RING')
    ring = ring_obj('RING', m)
    small = quad_obj('SMALL', [(2 + 0.2 * (i % 5), 0.2 * (i // 5), 0.1, 0.1) for i in range(25)], mats=[m] * 25)
    plain = plain_k(m)
    assert not plain['filled'] and plain['margin_violations'] == 0, plain
    assert max(plain['extent_px']) > 2048 * 1.05, plain  # Pack Islands: the layout is larger than the ring
    measured = uv_pack.measure(m)
    before = uvs(small).copy()
    r = uv_pack.pack(m)
    assert r['filled'] and r['k'] == measured['k'] and np.abs(uvs(small) - before).max() > 1e-3, r
    assert r['k'] < plain['k'] and ok(r), (r['k'], plain['k'], r)
    assert r['margin_violations'] == 0 and r['overlap_tri_pairs'] == 0, r
    inside = inside_ring(ring, small, m)
    assert inside == 25, inside
    assert max(r['extent_px']) < 2048 * 1.01, r  # the layout is the ring
    # only moved and turned: the density of every square as asked
    q = uvs(small).reshape(-1, 4, 2) * 4096
    d = [quad_density(p, 10, 10) for p in q]
    assert max(abs(x - 20.48) for x in d) / 20.48 < 1e-4, d
    report_row = uv_pack._set_block(r)
    assert any('placed into free space' in line for line in report_row), report_row
    # the same input gives the same layout: a set rebuilt the same way
    first = uvs(small).copy()
    reset()
    m = mat('RING')
    ring_obj('RING', m)
    small = quad_obj('SMALL', [(2 + 0.2 * (i % 5), 0.2 * (i // 5), 0.1, 0.1) for i in range(25)], mats=[m] * 25)
    uv_pack.pack(m)
    assert np.array_equal(first, uvs(small)), 'not deterministic'
    print(f"PASS: test_fill_ring (25 of 25 squares inside the ring; k {plain['k']:.3f} with Pack Islands alone, "
          f"{r['k']:.3f} with the step; gap {r['min_gap_px']:.2f} px, 0 violations, 0 overlaps; deterministic)")


def turn_of(q):
    """Per quad, the angle of its first edge in degrees."""
    e = q[:, 1] - q[:, 0]
    return np.degrees(np.arctan2(e[:, 1], e[:, 0]))


def test_fill_directions():
    # Upright and Flip islands moved by the step keep their rotation, in a set without Quarter
    reset()
    m = mat('FILL_DIR')
    ring = ring_obj('DIR_RING', m)
    # 25 squares, as in test_fill_ring: Pack Islands leaves one out of the hole
    up = quad_obj('DIR_UP', [(2 + 0.3 * i, 0, 0.1, 0.1) for i in range(10)], mats=[m] * 10)
    up['fss_uv_direction'] = 'UPRIGHT'
    fl = quad_obj('DIR_FLIP', [(2 + 0.3 * i, 1, 0.1, 0.1) for i in range(10)], mats=[m] * 10)
    fl['fss_uv_direction'] = 'FLIP'
    free = quad_obj('DIR_FREE', [(2 + 0.3 * i, 2, 0.1, 0.1) for i in range(5)], mats=[m] * 5)
    plain = plain_k(m)
    r = uv_pack.pack(m)
    assert r['filled'] and r['k'] < plain['k'] and ok(r), (r, plain['k'])
    assert r['upright_rotation_err_rad'] < 1e-4 and r['upright_islands'] == 20 and not r['quarter'], r
    for obj in (up, fl):
        angles = turn_of(uvs(obj).reshape(-1, 4, 2))
        assert np.abs(angles).max() < 1e-3, (obj.name, angles)
    inside = inside_ring(ring, up, m) + inside_ring(ring, fl, m)
    assert inside == 20, inside  # the marked islands were moved into the ring, without a turn
    # the free islands may have turned, by whatever Pack Islands gave and steps of 90 degrees; their size stays
    q = uvs(free).reshape(-1, 4, 2) * 4096
    assert max(abs(quad_density(p, 10, 10) - 20.48) for p in q) / 20.48 < 1e-4
    # a Quarter island: every island of the set turns in steps of 90 degrees, Upright ones not at all
    reset()
    m = mat('FILL_QUARTER')
    ring = ring_obj('Q_RING', m)
    quarter = quad_obj('Q_TURN', [(2 + 0.3 * i, 0, 0.1, 0.1) for i in range(10)], mats=[m] * 10)
    quarter['fss_uv_direction'] = 'QUARTER'
    up = quad_obj('Q_UP', [(2 + 0.3 * i, 1, 0.1, 0.1) for i in range(5)], mats=[m] * 5)
    up['fss_uv_direction'] = 'UPRIGHT'
    free = quad_obj('Q_FREE', [(2 + 0.3 * i, 2, 0.1, 0.1) for i in range(10)], mats=[m] * 10)
    plain = plain_k(m)
    r = uv_pack.pack(m)
    assert r['filled'] and r['quarter'] and r['k'] < plain['k'] and ok(r), (r, plain['k'])
    for obj in (quarter, free, ring):
        angles = turn_of(uvs(obj).reshape(-1, 4, 2))
        off = np.abs(angles - np.round(angles / 90.0) * 90.0)
        assert off.max() < 1e-3, (obj.name, angles)
    assert np.abs(turn_of(uvs(up).reshape(-1, 4, 2))).max() < 1e-3
    print(f"PASS: test_fill_directions (Upright and Flip moved into the ring without a turn; in a Quarter set every "
          f"island in 90-degree steps, Upright ones unturned; k {plain['k']:.3f} -> {r['k']:.3f})")


def test_fill_footprints():
    # the raster's promise: for random triangles, every point of a triangle lies in a cell of its spans
    rng = np.random.default_rng(3)
    T = rng.uniform(0, 40, (400, 3, 2))
    T[:50, 2] = T[:50, 0] + (T[:50, 1] - T[:50, 0]) * 0.3  # lines
    T[50:60, 1:] = T[50:60, 0:1]  # points
    rows, x0, x1 = uv_fill.spans(T)
    mask = uv_fill.solid_mask(rows, x0, x1)
    w = rng.dirichlet((1, 1, 1), (len(T), 200))
    P = np.einsum('nsv,nvi->nsi', w, T).reshape(-1, 2)
    cy, cx = np.floor(P[:, 1]).astype(int), np.floor(P[:, 0]).astype(int)
    assert mask[cy, cx].all()
    # placing many shapes: the exact distance between any two is at least the gap
    gap = 8.1
    tri = []
    isl = []
    for i in range(120):
        x, y = rng.uniform(0, 9000, 2)
        a, b = rng.uniform(5, 200, 2)
        c = rng.uniform(0.1, 1.0)
        tri += [[(x, y), (x + a, y), (x + a, y + b * c)], [(x, y), (x + a, y + b * c), (x + a * 0.2, y + b)]]
        isl += [i, i]
    tri = np.array(tri)
    isl = np.array(isl)
    active = np.ones(120, bool)
    active[7] = False  # not placed: stays where it is
    t, origin, offset = uv_fill.place(tri[isl != 7], isl[isl != 7], 120, active, np.ones(120, bool), gap)
    moved = uv_fill.apply(tri.reshape(-1, 2), np.repeat(isl, 3), active, t, origin, offset).reshape(-1, 3, 2)
    assert np.array_equal(moved[isl == 7], tri[isl == 7])
    keep = isl != 7
    seg = np.concatenate([moved[keep][:, [0, 1]], moved[keep][:, [1, 2]], moved[keep][:, [2, 0]]])
    seg_isl = np.tile(isl[keep], 3)
    remap = np.searchsorted(np.unique(isl[keep]), isl[keep])
    metrics, _offenders = uv_pack.layout_metrics(moved[keep], remap, seg, np.tile(remap, 3), 119, gap)
    assert metrics['margin_violations'] == 0 and metrics['overlap_tri_pairs'] == 0, metrics
    assert len(seg_isl) == len(seg)
    assert moved[keep].reshape(-1, 2).min() >= gap * 0.5 - 1e-6
    # scale unchanged: the triangles' areas
    assert np.abs(uv_pack.tri_area(moved) - uv_pack.tri_area(tri)).max() < 1e-6
    print(f"PASS: test_fill_footprints (conservative spans for triangles, lines and points; 119 shapes placed, gap "
          f"{metrics['min_gap_px']:.2f} px for {gap} px, areas unchanged)")


def test_fill_fallbacks():
    # Pack Islands alone still works with its proxy islands and the AABB fallback
    reset()
    m = mat('SPIKES', 1024)
    verts, faces, uv_co = [], [], []
    for i in range(6):
        b = len(verts)
        x = i * 1.0
        verts += [(x, 0, 0), (x + 0.2, 0, 0), (x + 0.2, 0.2, 0), (x, 0.2, 0), (x + 0.5, 0.1, 0)]
        faces += [(b, b + 1, b + 2, b + 3), (b + 1, b + 4, b + 2)]
        uv_co += [(0.0, 0.0), (0.2, 0.0), (0.2, 0.2), (0.0, 0.2), (0.2, 1.0)]
    me = bpy.data.meshes.new('SPIKES')
    me.from_pydata(verts, [], faces)
    uvl = me.uv_layers.new(name='UVMap')
    lv = np.zeros(len(me.loops), np.int64)
    me.loops.foreach_get('vertex_index', lv)
    uvl.data.foreach_set('uv', (np.array(uv_co) * 0.1)[lv].ravel())
    me.materials.append(m)
    quad_obj('SPIKES', None, mesh=me)
    quad_obj('SPIKES_SMALL', [(i * 0.3, 3, 0.04 + 0.01 * (i % 4), 0.05) for i in range(40)], mats=[m] * 40)
    plain = plain_k(m)
    assert not plain['filled'] and plain['margin_violations'] == 0 and plain['overlap_tri_pairs'] == 0, plain
    # the step found wanting (never measured; it is what the check after the search is for): Pack Islands takes over
    original = uv_pack.TextureSet.fill
    calls = []

    def broken(self, Q):
        calls.append(1)
        li = self.loop_isl
        lo = np.full((self.n, 2), np.inf)
        np.minimum.at(lo, li, Q)
        F = Q - lo[li]  # every island at the origin: all of them overlap
        return F, 1e-3, np.array([1.0, 1.0])

    uv_pack.TextureSet.fill = broken
    try:
        r = uv_pack.measure(m)
    finally:
        uv_pack.TextureSet.fill = original
    assert calls and not r['filled'] and r['margin_violations'] == 0 and r['overlap_tri_pairs'] == 0, r
    # the step on the same set: the needles count in its footprints
    r = uv_pack.measure(m)
    assert r['filled'] and r['k'] <= plain['k'] and ok(r), (r, plain['k'])
    print(f"PASS: test_fill_fallbacks (Pack Islands alone: k {plain['k']:.3f}, {plain['proxy_islands']} proxy islands, "
          f"{plain['shape_method']}; a broken step falls back to it; with the step k {r['k']:.3f}, 0 violations)")


def test_layout_corner():
    """The block moves to the scene's corner, by whole pixels, and nothing else changes; measuring moves nothing."""
    reset(0.9, 1.1)
    scene = bpy.context.scene
    assert scene.fss_uv_pack_corner == 'BOTTOM_LEFT'
    m = mat('CORNER')
    rects = [(i * 0.6, 0, 0.3 + 0.02 * i, 0.2) for i in range(10)] + [(7, 0, 0.1, 0.1)]
    uv_rects = [(0.01 * i, 0.02, 0.1, 0.1) for i in range(10)] + [(0.7, 0.7, 0.0, 0.1)]  # the last has no UV area
    obj = quad_obj('CO', rects, mats=[m] * len(rects), uv_rects=uv_rects)
    line = np.array([(0.7, 0.7), (0.7, 0.7), (0.7, 0.8), (0.7, 0.8)])

    def block():
        uv = uvs(obj)
        assert np.abs(uv[-4:] - line).max() < 1e-6, uv[-4:]  # the island without UV area keeps its UVs
        return uv[:-4], uv[:-4].min(0), uv[:-4].max(0)

    base = uv_pack.pack(m)
    _uv, lo0, hi0 = block()
    assert ok(base) and base['mode'] == 'underflow' and base['corner'] == 'BOTTOM_LEFT' and hi0.max() < 0.9, base
    pixel = 1 / 4096
    for corner, right, top in (('TOP_LEFT', False, True), ('TOP_RIGHT', True, True), ('BOTTOM_RIGHT', True, False),
                               ('BOTTOM_LEFT', False, False)):
        scene.fss_uv_pack_corner = corner
        before = uvs(obj).copy()
        measured = uv_pack.measure(m)
        assert np.array_equal(uvs(obj), before), corner  # Check All's measure writes nothing, on any corner
        r = uv_pack.pack(m)
        _uv, lo, hi = block()
        assert ok(r) and r['corner'] == corner and abs(r['k'] - base['k']) < 1e-3, (corner, r)
        assert abs(measured['k'] - r['k']) < 1e-9, (measured['k'], r['k'])
        assert np.abs((hi - lo) - (hi0 - lo0)).max() < 2e-3, (corner, hi - lo, hi0 - lo0)  # the same extent
        for axis, far in ((0, right), (1, top)):
            if far:  # as far from the far edge as the layout is from the origin, on the whole pixel below
                assert hi[axis] <= 1.0 - lo0[axis] + 2e-3 and 1.0 - hi[axis] < lo0[axis] + 2 * pixel + 2e-3, (corner, hi)
            else:
                assert lo[axis] < lo0[axis] + 2e-3, (corner, lo)
    # beyond the texture: the layout keeps the corner and spills past the opposite edges; the size asked for stays
    m.fss_uv_texture_size = '256'
    scene.fss_uv_pack_corner = 'BOTTOM_LEFT'
    over = uv_pack.pack(m)
    assert over['mode'] == 'overflow' and over['k'] > 1.0, over
    scene.fss_uv_pack_corner = 'TOP_LEFT'
    r = uv_pack.pack(m)
    _uv, lo, hi = block()
    assert abs(r['k'] - over['k']) < 1e-2 and r['needed_size'] == over['needed_size'], (r['k'], over['k'])
    assert hi[1] <= 1.0 and lo[1] < 0.0 and lo[0] >= 0.0, (lo, hi)
    assert any('corner Top-Left' in text for text in uv_pack._set_block(r)), uv_pack._set_block(r)
    scene.fss_uv_pack_corner = 'BOTTOM_LEFT'
    print(f"PASS: test_layout_corner (4 corners at k {base['k']:.3f}, overflow k {r['k']:.2f} spills to V {lo[1]:.2f})")


class _Recorder:
    """Records what a panel draws (background Blender has no UI to draw into)."""

    def __init__(self, calls):
        self.calls = calls

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self if name in ('row', 'column', 'box', 'split', 'operator') else None
        return call


def draw_islands(obj):
    calls = []
    uv_islands.draw(_Recorder(calls), bpy.context, obj)
    return calls, [kwargs.get('text') for name, _args, kwargs in calls if name == 'label']


def test_island_list():
    reset(0.9, 1.1)
    wm = bpy.context.window_manager
    scene = bpy.context.scene
    view_layer = bpy.context.view_layer
    a, b = mat('ISL_A'), mat('ISL_B')
    # four islands of 1 x 1 m, 1 x 1, 2 x 1 and 1 x 1, seen 1.0, 0.5, not at all, 0.25; the last in another texture set
    rects = [(0, 0, 1, 1), (2, 0, 1, 1), (4, 0, 2, 1), (7, 0, 1, 1)]
    obj = quad_obj('ISL', rects, mats=[a, a, a, b])
    other = quad_obj('ISL_OTHER', [(0, 3, 3, 3)], mats=[a])  # in the same set: the list reads this mesh only
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

    # No visibility data: every multiplier x1.00, and the list says so
    uv_islands.sync(obj, scene, view_layer, wm)
    assert [row.factor for row in wm.fss_uv_island_rows] == [1.0] * 4 and uv_islands._state['stale']
    wm.fss_uv_islands_open = True
    _calls, labels = draw_islands(obj)
    assert 'No visibility data: multipliers are x1.00' in labels, labels

    # With data, through the packer's own path (a saved file is what makes it read visibility)
    folder = Path(tempfile.mkdtemp(prefix='fss_islands_'))
    bpy.ops.wm.save_as_mainfile(filepath=str(folder / 'islands.blend'))
    obj = bpy.data.objects['ISL']
    other = bpy.data.objects['ISL_OTHER']
    a, b = bpy.data.materials['ISL_A'], bpy.data.materials['ISL_B']
    scene = bpy.context.scene
    view_layer = bpy.context.view_layer
    scores = {'ISL': np.array([1.0, 0.5, 0.0, 0.25], np.float32), 'ISL_OTHER': np.array([1.0], np.float32)}
    facing = {'ISL': np.array([1.0, 0.5, 0.0, 0.5], np.float32), 'ISL_OTHER': np.array([1.0], np.float32)}

    def stand_in(user, uv_name=None, vis_path=None, use_cache=True):
        areas = np.array([p.area for p in user.data.polygons], np.float32)
        return {'stale': False, 'face_scores': scores[user.data.name], 'orig_areas': areas, 'vis_omega': None,
                'unocc_omega': None, 'object_score': 0.5, 'island_values': {}, 'face_facing': facing[user.data.name],
                # a file with Ambient 0.1 (decision 133): never-lit faces are flagged, islands floored at 0.1
                'ambient': 0.1, 'face_never_seen': scores[user.data.name] <= 0.0}

    real = visibility_core.get_object_visibility
    visibility_core.get_object_visibility = stand_in
    try:
        uv_islands.sync(obj, scene, view_layer, wm)
        rows = wm.fss_uv_island_rows
        # highest density first; a never-lit island takes the file's Ambient x0.10; the numbers stay with the islands
        got = [(row.number, row.material, round(row.factor, 3)) for row in rows]
        assert got == [(1, 'ISL_A', 1.0), (2, 'ISL_A', 0.5), (4, 'ISL_B', 0.25), (3, 'ISL_A', 0.1)], got
        assert [row.high for row in rows] == sorted((row.high for row in rows), reverse=True)
        # the packer's own values: the texture set with all its objects gives each island the same numbers
        parts, _conflicts = uv_pack.gather(view_layer, a)
        ts = uv_pack.TextureSet(a, parts, scene, {})
        part = next(i for i, p in enumerate(parts) if p[1][0] == obj)
        isl = ts.face_isl[part]
        for row, position in zip(rows, range(len(rows))):
            if row.material != 'ISL_A':
                continue
            k = isl[np.searchsorted(parts[part][2], uv_islands._state['faces'][position][0])]
            assert abs(row.low - ts.lo[k]) < 1e-4 and abs(row.high - ts.hi[k]) < 1e-4, (row.low, ts.lo[k])
            assert abs(row.area - ts.a3[k]) < 1e-1 and abs(row.now - ts.cur[k]) < 1e-3, (row.area, ts.a3[k])
        by_number = {row.number: row for row in rows}
        target = uv_marks.target_density(scene)
        assert abs(by_number[1].high - target * 1.1) < 1e-4 and abs(by_number[3].low - target * 0.9 * 0.1) < 1e-4
        assert (by_number[1].seen, by_number[3].seen) == (1.0, 0.0) and by_number[3].faces == 1
        assert abs(by_number[3].area - 20000.0) < 1e-1, by_number[3].area

        # The Islands tick off: every island of this object counts as fully visible and faces the cameras (decision 139)
        obj.fss_uv_use_visibility = False
        uv_islands.sync(obj, scene, view_layer, wm)
        assert all(abs(row.high - target * 1.1) < 1e-4 and abs(row.low - target * 0.9) < 1e-4 for row in rows)
        obj.fss_uv_use_visibility = True
        uv_islands.sync(obj, scene, view_layer, wm)
        by_number = {row.number: row for row in rows}
        assert abs(by_number[3].low - target * 0.9 * 0.1) < 1e-4

        # Density: the range; after Pack or Check All, the value at that set's t; a kept set says so
        row = by_number[1]
        assert uv_islands.density_text(row) == f'{row.low:.2f} - {row.high:.2f}', uv_islands.density_text(row)
        uv_marks._results['ISL_A'] = {'t': 0.5, 'mode': 'fit'}
        assert uv_islands.density_text(row) == f'{(row.low + row.high) / 2:.2f}', uv_islands.density_text(row)
        uv_marks._results.pop('ISL_A')

        # A refill keeps the active island: island 3 was the first row without data, and is still active
        assert rows[wm.fss_uv_island_active].number == 3, rows[wm.fss_uv_island_active].number
        assert obj.mode == 'OBJECT'  # a refill is not a click
        wm.fss_uv_island_active = 0
        assert obj.mode == 'EDIT'  # a click is
        bpy.ops.object.mode_set(mode='OBJECT')
        uv_islands.sync(obj, scene, view_layer, wm)
        assert wm.fss_uv_island_active == 0 and obj.mode == 'OBJECT'

        # Drawing writes nothing and asks for no refill while the key holds
        calls, labels = draw_islands(obj)
        assert not uv_islands._pending and not any(
            name == 'operator' and args[0] not in ('fss.uv_island_select', 'fss.uv_island_sort', 'fss.uv_island_override_set',
                                                   'fss.uv_island_override_clear', 'fss.uv_island_untick')
            for name, args, _kw in calls)
        assert labels[0] == '#', labels
        titles = [kw['text'] for name, args, kw in calls if name == 'operator' and args[0] == 'fss.uv_island_sort']
        assert titles == ['Area', 'Multiplier', 'Density px/cm'], titles
        assert [name for name, _args, _kw in calls].count('template_list') == 1
        assert ['Material', 'ISL_A'] == labels[1:3] and '100 % of its surface' in labels, labels
        assert labels[labels.index('Facing') + 1] == '1.00', labels
        assert labels[labels.index('Visibility') + 1] == 'x1.00', labels
        # Multiplier is the final number: the scene's 1.1 at full facing, and the floor x0.10 with no range left at facing 0
        assert abs(by_number[1].multiplier - 1.1) < 1e-4 and abs(by_number[3].multiplier - 0.09) < 1e-4, (
            by_number[1].multiplier, by_number[3].multiplier)
        # facing moves the top of the range: the never-seen island, facing 0, has no range left
        assert by_number[3].high == by_number[3].low and abs(by_number[2].high - by_number[2].low - target * 0.2 * 0.5 * 0.5) < 1e-4
        # Sorting: a click on a title sorts by that column, highest first, and a second click reverses. The rows keep their
        # indices, so the list's active row and its faces stay right
        rows = wm.fss_uv_island_rows
        assert wm.fss_uv_island_sort == 'DENSITY' and not wm.fss_uv_island_sort_reverse

        def shown(value):
            order = uv_islands.island_order(rows, wm.fss_uv_island_sort, wm.fss_uv_island_sort_reverse)
            assert sorted(order) == list(range(len(rows))), order
            return [value(rows[i]) for i in sorted(range(len(rows)), key=order.__getitem__)]

        numbers_before = [row.number for row in rows]
        for key, value in (('AREA', lambda r: r.area), ('MULTIPLIER', lambda r: r.multiplier), ('DENSITY', uv_islands.density_value)):
            bpy.ops.fss.uv_island_sort(sort_by=key)
            assert wm.fss_uv_island_sort == key and not wm.fss_uv_island_sort_reverse
            values = shown(value)
            assert values == sorted(values, reverse=True) and values[0] > values[-1], (key, values)
        bpy.ops.fss.uv_island_sort(sort_by='DENSITY')
        assert wm.fss_uv_island_sort_reverse
        values = shown(uv_islands.density_value)
        assert values == sorted(values), values
        bpy.ops.fss.uv_island_sort(sort_by='DENSITY')
        assert not wm.fss_uv_island_sort_reverse and [row.number for row in rows] == numbers_before
        # An island without an area stays last either way
        fake = [SimpleNamespace(area=9.0, multiplier=0.0, high=0.0, low=0.0, kept=False, material='', status='no UV area', number=9),
                SimpleNamespace(area=1.0, multiplier=1.0, high=1.0, low=1.0, kept=False, material='', status='', number=1),
                SimpleNamespace(area=2.0, multiplier=1.0, high=1.0, low=1.0, kept=False, material='', status='', number=2)]
        assert uv_islands.island_order(fake, 'AREA', False) == [2, 1, 0] and uv_islands.island_order(fake, 'AREA', True) == [2, 0, 1]
        # What the list asks: the order, and the filter field still works
        ask = uv_islands.FSS_UL_UvIslands.filter_items
        plain = SimpleNamespace(filter_name='', bitflag_filter_item=1 << 30, use_filter_invert=False)
        flags, order = ask(plain, bpy.context, wm, 'fss_uv_island_rows')
        assert flags == [] and order == uv_islands.island_order(rows, 'DENSITY', False), (flags, order)
        plain.filter_name = f'{rows[0].number} *'
        flags, _order = ask(plain, bpy.context, wm, 'fss_uv_island_rows')
        assert flags[0] and sum(1 for flag in flags if flag) == 1, flags
        # A bar under each number, against the list's largest; the largest row fills it
        fills = {'AREA': [], 'MULTIPLIER': [], 'DENSITY': []}
        for index, row in enumerate(rows):
            calls = []
            uv_islands.FSS_UL_UvIslands.draw_item(None, bpy.context, _Recorder(calls), wm, row, 0, wm, 'fss_uv_island_active', index)
            bars = [kw['factor'] for name, _a, kw in calls if name == 'progress']
            assert len(bars) == 3 and all(0.0 <= bar <= 1.0 for bar in bars), bars
            assert all(kw['text'] == ' ' for name, _a, kw in calls if name == 'progress')
            for key, bar in zip(fills, bars):
                fills[key].append(bar)
        assert all(abs(max(values) - 1.0) < 1e-6 for values in fills.values()), fills
        assert abs(fills['AREA'][[row.number for row in rows].index(3)] - 1.0) < 1e-6, fills  # the 2 x 1 m island

        # visibility data from before facing: the list says so
        facing_before = dict(facing)
        facing.update(ISL=None)
        uv_islands.sync(obj, scene, view_layer, wm)
        _calls, labels = draw_islands(obj)
        assert labels[0] == 'No facing data: run Update Visibility once', labels
        assert labels[labels.index('Facing') + 1] == 'no data: top of the range', labels
        facing.update(facing_before)
        uv_islands.sync(obj, scene, view_layer, wm)
        rows = wm.fss_uv_island_rows

        # What makes the rows out of date: a mark, a kept set, a changed UV
        key = uv_islands._key(obj, scene)
        obj.fss_uv_density_own, obj.fss_uv_density_min, obj.fss_uv_density_max = True, 0.5, 0.5
        assert uv_islands._key(obj, scene) != key
        draw_islands(obj)
        assert uv_islands._pending  # the refill is scheduled, not done in the draw
        assert abs(rows[0].high - target * 1.1) < 1e-4
        uv_islands._pending = False
        uv_islands.sync(obj, scene, view_layer, wm)
        assert abs(wm.fss_uv_island_rows[0].high - target * 1.1 * 0.5) < 1e-4  # the scene freedom x the mark
        obj.fss_uv_density_own = False
        uv_islands.sync(obj, scene, view_layer, wm)
        key = uv_islands._key(obj, scene)
        obj.data.update()
        bpy.context.view_layer.update()
        assert uv_islands._key(obj, scene) != key, 'a geometry update must refresh the list'
        uv_islands.sync(obj, scene, view_layer, wm)

        # A click on a row, from Object Mode, enters Edit Mode with the island's faces; the next click moves the selection
        rows = wm.fss_uv_island_rows
        assert obj.mode == 'OBJECT'
        wm.fss_uv_island_active = 3
        assert obj.mode == 'EDIT'

        def selected():
            bm = bmesh.from_edit_mesh(obj.data)
            return [face.index for face in bm.faces if face.select]

        assert selected() == [2], selected()  # island 3, the never-seen one, is the last row
        wm.fss_uv_island_active = 0
        assert selected() == [0], selected()
        # Select Faces, for the row already active, from Object Mode too
        bpy.ops.object.mode_set(mode='OBJECT')
        assert bpy.ops.fss.uv_island_select() == {'FINISHED'} and obj.mode == 'EDIT'
        assert selected() == [0], selected()
        _calls, labels = draw_islands(obj)  # in Edit Mode the rows stay
        assert '#' in labels and not uv_islands._pending
        bpy.ops.object.mode_set(mode='OBJECT')

        # A shared mesh, an object with no list yet in Edit Mode, and a mesh the packer does not take
        twin = bpy.data.objects.new('ISL_TWIN', obj.data)
        scene.collection.objects.link(twin)
        view_layer.update()
        uv_islands.sync(obj, scene, view_layer, wm)
        assert uv_islands._state['users'] == 2
        _calls, labels = draw_islands(obj)
        assert any(text and text.startswith('Mesh shared by 2') for text in labels), labels
        no_uv = bpy.data.meshes.new('ISL_NO_UV')
        no_uv.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0)], [], [(0, 1, 2)])
        plain = bpy.data.objects.new('ISL_NO_UV', no_uv)
        scene.collection.objects.link(plain)
        view_layer.update()
        uv_islands.sync(plain, scene, view_layer, wm)
        _calls, labels = draw_islands(plain)
        assert len(wm.fss_uv_island_rows) == 0 and any('no UV map' in (text or '') for text in labels), labels
        assert uv_pack.object_islands(plain, scene, view_layer) is None
    finally:
        visibility_core.get_object_visibility = real
        wm.fss_uv_islands_open = False
    print("PASS: test_island_list (the packer's values per island, highest density first, floor x0.10, seen share, "
          "range or value at t, refill after the draw, Select Faces and a click in Edit Mode, shared mesh, no UV map)")


def test_island_override():
    """Set by hand: a multiplier or a density on ticked islands, stored on the faces, final for Pack."""
    reset(0.9, 1.1)
    wm = bpy.context.window_manager
    scene = bpy.context.scene
    view_layer = bpy.context.view_layer
    target = uv_marks.target_density(scene)
    m = mat('OVR')
    obj = quad_obj('OVR', [(0, 0, 0.2, 0.2), (1, 0, 0.2, 0.2), (2, 0, 0.2, 0.2), (3, 0, 0.2, 0.2)], mats=[m, m, m, m])
    view_layer.objects.active = obj
    obj.select_set(True)
    uv_islands.sync(obj, scene, view_layer, wm)
    rows = wm.fss_uv_island_rows
    assert uv_marks.face_overrides(obj.data) is None and all(row.override == 0.0 for row in rows)

    # Nothing ticked: Set and Clear cannot run
    assert not bpy.ops.fss.uv_island_override_set.poll() and not bpy.ops.fss.uv_island_override_clear.poll()

    def by_number():
        return {row.number: row for row in wm.fss_uv_island_rows}

    # A multiplier on two islands: final, whatever the marks say (no range left)
    by_number()[1].ticked = by_number()[2].ticked = True
    wm.fss_uv_override_kind, wm.fss_uv_override_multiplier = 'MULTIPLIER', 0.5
    assert bpy.ops.fss.uv_island_override_set() == {'FINISHED'}
    rows = by_number()
    for number in (1, 2):
        assert abs(rows[number].low - target * 0.5) < 1e-4 and abs(rows[number].high - target * 0.5) < 1e-4
        assert abs(rows[number].multiplier - 0.5) < 1e-4 and abs(rows[number].override - 0.5) < 1e-6
        assert rows[number].ticked and not rows[number].override_mixed
    assert rows[3].override == 0.0 and abs(rows[3].high - target * 1.1) < 1e-4  # the others keep theirs

    # A density is stored as a multiplier of the target density: only the multiplier is on the faces
    for number in (1, 2):
        rows[number].ticked = False
    rows[3].ticked = True
    wm.fss_uv_override_kind, wm.fss_uv_override_density = 'DENSITY', 40.96
    assert bpy.ops.fss.uv_island_override_set() == {'FINISHED'}
    rows = by_number()
    assert abs(rows[3].override - 2.0) < 1e-5 and abs(rows[3].low - 40.96) < 1e-3, rows[3].override
    values = uv_marks.face_overrides(obj.data)
    assert sorted(np.round(values, 4).tolist()) == [0.0, 0.5, 0.5, 2.0], values

    # Pack gives exactly that, the other island at the top of its range (the set fits)
    r = uv_pack.pack(m)
    assert r['written'] and r['t'] == 1.0, r
    q = uvs(obj).reshape(-1, 4, 2) * uv_marks.texture_size(m)
    got = [quad_density(q[i], 20, 20) for i in range(4)]
    wanted = sorted([target * 0.5, target * 0.5, target * 2.0, target * 1.1])
    assert np.allclose(sorted(got), wanted, atol=0.05), (got, wanted)

    # Saved with the file, and a new sync reads it back
    folder = Path(tempfile.mkdtemp(prefix='fss_override_'))
    bpy.ops.wm.save_as_mainfile(filepath=str(folder / 'override.blend'))
    bpy.ops.wm.open_mainfile(filepath=str(folder / 'override.blend'))
    obj = bpy.data.objects['OVR']
    scene, view_layer, wm = bpy.context.scene, bpy.context.view_layer, bpy.context.window_manager
    assert sorted(np.round(uv_marks.face_overrides(obj.data), 4).tolist()) == [0.0, 0.5, 0.5, 2.0]
    view_layer.objects.active = obj
    uv_islands.sync(obj, scene, view_layer, wm)

    # From Edit Mode (a click on a row goes there): it stays there, and the value is on the mesh after leaving
    rows = by_number()
    three = next(row for row in rows.values() if abs(row.override - 2.0) < 1e-5)
    three.ticked = True
    wm.fss_uv_override_kind, wm.fss_uv_override_multiplier = 'MULTIPLIER', 1.5
    bpy.ops.object.mode_set(mode='EDIT')
    assert bpy.ops.fss.uv_island_override_set() == {'FINISHED'} and obj.mode == 'EDIT'
    bpy.ops.object.mode_set(mode='OBJECT')
    assert sorted(np.round(uv_marks.face_overrides(obj.data), 4).tolist()) == [0.0, 0.5, 0.5, 1.5]

    # The highest value of an island counts, and the list warns (faces joined, or seams removed, after setting)
    me = obj.data
    uv_marks.set_face_overrides(me, np.array([0]), 3.0)
    md = uv_pack.MeshData(me)
    faces = np.arange(len(me.polygons))
    isl, _bl, _bl_isl = uv_pack.part_islands(md, faces)
    joined = uv_pack.TextureSet(bpy.data.materials['OVR'], [(md, [obj], faces)], scene, {})
    assert joined.override[isl[0]] == 3.0 and not joined.override_mixed[isl[0]], joined.override
    obj2 = quad_obj('OVR2', [(0, 3, 2, 1)], mats=[bpy.data.materials['OVR']], uv_rects=None)
    bm = bmesh.new()
    bm.from_mesh(obj2.data)
    bmesh.ops.subdivide_edges(bm, edges=[e for e in bm.edges if abs(e.verts[0].co.x - e.verts[1].co.x) > 0.5], cuts=1, use_grid_fill=True)
    bm.to_mesh(obj2.data)
    bm.free()
    uv_marks.set_face_overrides(obj2.data, np.array([0]), 0.7)
    md2 = uv_pack.MeshData(obj2.data)
    faces2 = np.arange(len(obj2.data.polygons))
    mix = uv_pack.TextureSet(bpy.data.materials['OVR'], [(md2, [obj2], faces2)], scene, {})
    assert mix.n == 1 and abs(mix.override[0] - 0.7) < 1e-6 and mix.override_mixed[0] and abs(mix.lo[0] - target * 0.7) < 1e-4, (
        mix.n, mix.override, mix.override_mixed)

    # Clear: back to the marks; the mesh loses the attribute when none is left
    view_layer.objects.active = obj
    uv_islands.sync(obj, scene, view_layer, wm)
    for row in wm.fss_uv_island_rows:
        row.ticked = True
    assert bpy.ops.fss.uv_island_untick() == {'FINISHED'} and not any(row.ticked for row in wm.fss_uv_island_rows)
    for row in wm.fss_uv_island_rows:
        row.ticked = True
    assert bpy.ops.fss.uv_island_override_clear() == {'FINISHED'}
    assert uv_marks.face_overrides(obj.data) is None and uv_marks.OVERRIDE_KEY not in obj.data.attributes
    assert all(row.override == 0.0 and abs(row.high - target * uv_marks.scene_freedom(scene)[1]) < 1e-4 for row in wm.fss_uv_island_rows)

    # A row Pack leaves alone has no tick box; a tick does not reach it
    row = wm.fss_uv_island_rows[0]
    row.status = 'no UV area'
    assert not uv_islands.can_override(row)
    calls = []
    uv_islands.FSS_UL_UvIslands.draw_item(None, bpy.context, _Recorder(calls), wm, row, 0, wm, 'fss_uv_island_active', 0)
    assert not any(name == 'prop' for name, _a, _k in calls), calls
    print('PASS: test_island_override (multiplier and density final for Pack, saved with the file, from Edit Mode, highest wins with a warning, Clear)')


def test_pack_progress():
    """The bar of a Pack: real stages in order, between 0 and 1; it never goes back."""
    reset(0.5, 1.5)
    m = mat('PROGRESS')
    quad_obj('PROGRESS', [(0, 0, 1, 1), (2, 0, 1, 1)], mats=[m, m])
    bpy.context.view_layer.update()
    stages = []
    assert uv_pack.pack(m, progress=lambda text, fraction: stages.append((text, fraction)))['written']
    texts = [text for text, _f in stages]
    assert texts[0] == 'Reading the islands' and texts[-1] == 'Writing the UVs' and texts[-2] == 'Measuring the layout', texts
    assert any(text.startswith('Trying layout 1 of at most') for text in texts), texts
    fractions = [fraction for _t, fraction in stages]
    assert fractions == sorted(fractions) and all(0.0 <= f <= 1.0 for f in fractions), stages
    stages.clear()
    assert not uv_pack.measure(m, progress=lambda text, fraction: stages.append(text))['written'] and 'Writing the UVs' not in stages, stages
    # A later round of packs does not take the bar back
    real = uv_autoseam._redraw_sidebar_now
    uv_autoseam._redraw_sidebar_now = lambda spaces: None
    uv_marks._progress = {'verb': 'Packing', 'index': 1, 'count': 1, 'set': 'X', 'stage': '', 'fraction': 0.0}
    try:
        uv_marks._on_stage('one', 0.9)
        uv_marks._on_stage('two', 0.2)
        assert uv_marks._progress['fraction'] == 0.9 and uv_marks._progress['stage'] == 'two', uv_marks._progress
    finally:
        uv_marks._progress = None
        uv_autoseam._redraw_sidebar_now = real
    print("PASS: test_pack_progress (stages in order, the bar only goes forward)")


def test_partly_seen():
    """The scene's Partly Seen Islands: 1 any seen part counts for the whole island, 0.5 the seen share, 0 only an island
    seen whole; 0.75 and 0.25 biased either way; the minimum holds, the list follows."""
    reset(1.0, 1.0)
    m = mat('PARTLY')
    # One island of two faces sharing an edge and its UVs: 1 m and 3 m wide, the first seen; and a second island, a tiny
    # seen face beside a large unseen one
    verts = [(0, 0, 0), (1, 0, 0), (4, 0, 0), (0, 1, 0), (1, 1, 0), (4, 1, 0),
             (0, 2, 0), (0.1, 2, 0), (9.9, 2, 0), (0, 3, 0), (0.1, 3, 0), (9.9, 3, 0)]
    faces = [(0, 1, 4, 3), (1, 2, 5, 4), (6, 7, 10, 9), (7, 8, 11, 10)]
    me = bpy.data.meshes.new('PARTLY')
    me.from_pydata(verts, [], faces)
    layer = me.uv_layers.new(name='UVMap')
    lv = np.zeros(len(me.loops), np.int64)
    me.loops.foreach_get('vertex_index', lv)
    layer.data.foreach_set('uv', (np.array(verts)[:, :2] * 0.05)[lv].ravel())
    me.materials.append(m)
    obj = bpy.data.objects.new('PARTLY', me)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.update()
    folder = Path(tempfile.mkdtemp(prefix='fss_partly_'))
    bpy.ops.wm.save_as_mainfile(filepath=str(folder / 'partly.blend'))
    obj = bpy.data.objects['PARTLY']
    m = bpy.data.materials['PARTLY']
    scene = bpy.context.scene
    view_layer = bpy.context.view_layer
    scores = np.array([0.8, 0.0, 0.8, 0.0], np.float32)

    def stand_in(user, uv_name=None, vis_path=None, use_cache=True):
        return {'stale': False, 'face_scores': scores, 'orig_areas': np.array([p.area for p in user.data.polygons], np.float32),
                'vis_omega': None, 'unocc_omega': None, 'object_score': 0.5, 'island_values': {}, 'face_facing': None,
                # the brightest face (Island Value 100 %), so only Partly Seen decides how the seen share counts;
                # Partly Seen never takes an island below the file's Ambient
                'island_percentile': 1.0, 'ambient': 0.1}

    def factors():
        parts, _conflicts = uv_pack.gather(view_layer, m)
        ts = uv_pack.TextureSet(m, parts, scene, {})
        return ts.vis[ts.face_isl[0][0]], ts.vis[ts.face_isl[0][2]], ts

    real = visibility_core.get_object_visibility
    visibility_core.get_object_visibility = stand_in
    try:
        # the first island is 25 % seen, the second 0.1 m of 9.9 m, both with score 0.8; the minimum is 0.1
        expected = {1.0: (0.8, 0.8), 0.75: (0.8 * 0.25 ** (1 / 3), 0.8 * (0.1 / 9.9) ** (1 / 3)), 0.5: (0.2, 0.1), 0.25: (0.1, 0.1), 0.0: (0.1, 0.1)}
        assert scene.fss_uv_partly_seen_value == 1.0  # the default (decision 132)
        for value, (want_first, want_second) in expected.items():
            scene.fss_uv_partly_seen_value = value
            first, second, ts = factors()
            assert abs(first - want_first) < 1e-4 and abs(second - want_second) < 1e-4, (value, first, second)
        # 0.25 is the cube of the share, above the minimum for a larger share
        assert abs(uv_marks.partly_seen_factor(0.8, 0.25) - 0.8 ** 3) < 1e-9 and abs(uv_marks.partly_seen_factor(0.5, 0.5) - 0.5) < 1e-9
        # An island seen whole loses nothing at any value, 0 included
        assert all(uv_marks.island_visibility(0.8, 1.0, value) == 0.8 for value in expected)
        scene.fss_uv_partly_seen_value = 0.75
        first, second, ts = factors()
        assert abs(ts.lo[ts.face_isl[0][0]] - scene.fss_uv_target_density * first) < 1e-3
        # The list follows the slider, and Pack still meets the density
        wm = bpy.context.window_manager
        uv_islands.sync(obj, scene, view_layer, wm)
        key = uv_islands._key(obj, scene)
        scene.fss_uv_partly_seen_value = 0.5
        assert uv_islands._key(obj, scene) != key
        uv_islands.sync(obj, scene, view_layer, wm)
        assert abs(max(row.factor for row in wm.fss_uv_island_rows) - 0.2) < 1e-5
        result = uv_pack.pack(m)
        assert result['margin_violations'] == 0 and result['overlap_tri_pairs'] == 0, result
    finally:
        visibility_core.get_object_visibility = real
        scene.fss_uv_partly_seen_value = uv_marks.DEFAULT_PARTLY_SEEN
    # The panel draws it in Advanced
    calls = []
    bpy.types.FSS_PT_uv_marks_advanced.draw(SimpleNamespace(layout=_Recorder(calls)), bpy.context)
    assert any(name == 'prop' and args[1] == 'fss_uv_partly_seen_value' for name, args, _kw in calls), calls
    print("PASS: test_partly_seen (1 whole island, 0.75 and 0.25 biased, 0.5 the seen share, 0 only seen whole; the minimum holds; the list and Pack follow)")


def main():
    test_pack_progress()
    test_partly_seen()
    test_island_list()
    test_island_override()
    test_layout_corner()
    test_fill_footprints()
    test_fill_ring()
    test_fill_directions()
    test_fill_fallbacks()
    test_exact_density()
    test_material_factor()
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
    test_pack_all()
    test_check_results()
    test_texture_set_list()
    test_uv_editor_panel()
    test_report_order()
    print("ALL TESTS PASSED")


main()
