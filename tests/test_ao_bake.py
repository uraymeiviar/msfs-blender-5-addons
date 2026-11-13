"""AO Bake (auto-bake journal, Sessions 15 to 17): masters in a second Blender, their staleness, and Apply.

A synthetic scene of small groups (plane with a cube near it, 1 m apart, AO distance 0.1 m) is saved to
tests/_work/ao_bake_suite/suite.blend and baked through the tool's operators in hidden mode (a second, background
Blender). Checked:
- the second Blender: status.json reaches m of m; Cancel stops after the current object and keeps the finished masters
  (finish line 8);
- the bake in tiles (Session 19): a master in tiles of 64 px has the untiled master's layout, filled pixels and face
  map, and differs by noise only; Cancel between tiles stops within one tile and keeps the object's old master; an
  object's faces without a material are not baked, an object without one is excluded and listed (decision 30);
- the master paged (Session 23): baked and written band by band, no per-pixel array in the .npz, Apply in bands of 5
  rows, of 256 rows and from the whole master in memory byte-identical, no scratch file left;
- the masters as JPEG XL (Session 26, decision 37): every master .jxl; a PNG master as 0.55.2 wrote it is up to date
  and applied byte-identically, and a re-bake replaces it with a .jxl and removes the PNG; with the library made
  unloadable (FSS_AO_BAKE_NO_JXL) the bake writes PNG, the report says so once, and Apply works;
- staleness: a moved vertex, changed custom normals and an added modifier give "mesh changed"; a moved occluder inside
  the AO distance, an occluder tagged Non-AO-Occluder, the AO distance and a moved object give "surroundings changed";
  an occluder moved outside the distance, UVs moved, scaled and re-unwrapped, a material changed leave it up to date;
  a renamed object is linked to its master again (finish line 2);
- the artist's file untouched by a bake (the .blend's hash, datablock counts, matrices, materials, images) and Apply
  adding no datablock (finish line 3);
- into the ORM slot texture: red written, green and blue byte for byte, 16-bit, the backup; an 8-bit file reported and
  written as 16-bit with green and blue kept (finish line 4);
- per-object Apply: pixels outside the selected objects' faces and padding unchanged, no padding inside another
  object's face (finish line 5);
- separate files: greyscale, ORM layout white and copied, another size with each sampling method, neighbour islands
  of different green never mixed (finish line 6);
- rules: no master for a Skip-AO-Bake object; decal and glass faces not in the master and not written; a
  Non-AO-Occluder darkens nothing; a mover darkens no other object; a shared mesh gets its self-shading only; faces
  under 4 x counted (finish line 7);
- the panel draws without writing;
- the options of Session 25 (decisions 34 to 36): a Non-AO-Occluder in a custom list shades the target, an object not
  in the list does not (finish line 4); the pose count, occluder mode and custom list each give "surroundings changed"
  and back "up to date" (finish line 5); the run mode Hidden (and Visible with FSS_AO_BAKE_TEST_VISIBLE=1): the bake
  finishes, the panel's preview updates during it, the .blend, its datablocks and is_dirty unchanged (finish line 7);
  last, a wheel half sunk in a slab (wheel.blend): at 1 pose its AO per angle sector varies, at 8 poses over a full
  turn at most a quarter of that, Self only no slab shadow, a custom list's mover posed with it (finish line 1).
  `-- only=test_poses` runs that test alone.

To run (the second Blender inherits the CPU cap):
C:\\Users\\uray\\.claude\\tools\\cpucap\\cpucap.exe 50 G:\\e-jets-e2\\tools\\blender\\blender.exe -b --factory-startup
    --python tests/test_ao_bake.py
"""

import hashlib
import math
import os
import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import addon_utils
import bpy
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
ADDONS = ('io_scene_gltf2_msfs_fss', 'fss_blender_tools')

# The portable Blender enables its deployed addons_core copies at startup: disable and purge them, then import the
# repository modules first, so addon_utils enables those
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
from fss_blender_tools import ao_bake, ao_bake_apply, ao_bake_core as core, ao_bake_store as store, tags  # noqa: E402

for name in ADDONS:
    addon_utils.enable(name, default_set=True)
    assert Path(sys.modules[name].__file__).resolve().is_relative_to(REPO_ROOT), sys.modules[name].__file__

WORK = REPO_ROOT / 'tests' / '_work' / 'ao_bake_suite'
BLEND = WORK / 'suite.blend'
FOLDER = WORK / 'suite.bake'
OUT = WORK / 'suite_ao'
SIZE = 256
CELL = 1.0 / 4  # UV cells of 64 px
PAD = 8


# ---------------------------------------------------------------------------------------------------------------------
# Scene
# ---------------------------------------------------------------------------------------------------------------------

def link(obj):
    bpy.context.scene.collection.objects.link(obj)
    return obj


def material(name, size=SIZE):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.fss_uv_texture_size = str(size)
    try:
        mat.msfs_material_type = 'msfs_standard'
    except (AttributeError, TypeError):
        pass
    return mat


def cell_uv(cell, u, v, margin=0.1):
    """u, v in 0..1 placed into UV cell `cell` (row-major, 4 x 4) with a margin."""
    cx, cy = cell % 4, cell // 4
    return ((cx + margin + u * (1 - 2 * margin)) * CELL, (cy + margin + v * (1 - 2 * margin)) * CELL)


def plane(name, location, mat, cell, size=0.2, n=4, extra_mats=None):
    """A grid of n x n quads, size m, at location; UVs fill a cell. extra_mats {face index: material}."""
    verts, faces = [], []
    for j in range(n + 1):
        for i in range(n + 1):
            verts.append(((i / n - 0.5) * size, (j / n - 0.5) * size, 0.0))
    for j in range(n):
        for i in range(n):
            a = j * (n + 1) + i
            faces.append((a, a + 1, a + n + 2, a + n + 1))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.materials.append(mat)
    uv = me.uv_layers.new(name='UVMap')
    for poly in me.polygons:
        for li in poly.loop_indices:
            x, y, _z = verts[me.loops[li].vertex_index]
            uv.data[li].uv = cell_uv(cell, x / size + 0.5, y / size + 0.5)
    if extra_mats:
        for fi, (m, cell2) in extra_mats.items():
            if m.name not in [x.name for x in me.materials]:
                me.materials.append(m)
            poly = me.polygons[fi]
            poly.material_index = [x.name for x in me.materials].index(m.name)
            for k, li in enumerate(poly.loop_indices):
                uv.data[li].uv = cell_uv(cell2, (k in (1, 2)) * 1.0, (k in (2, 3)) * 1.0, margin=0.3)
    obj = link(bpy.data.objects.new(name, me))
    obj.location = location
    return obj


def cube_mesh(name, mat, cell, size=0.06):
    s = size / 2
    verts = [(-s, -s, 0), (s, -s, 0), (s, s, 0), (-s, s, 0), (-s, -s, 2 * s), (s, -s, 2 * s), (s, s, 2 * s),
             (-s, s, 2 * s)]
    faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.materials.append(mat)
    uv = me.uv_layers.new(name='UVMap')
    for f, poly in enumerate(me.polygons):
        fx, fy = f % 3, f // 3
        for k, li in enumerate(poly.loop_indices):
            u = (fx + 0.1 + 0.8 * (k in (1, 2))) / 3
            v = (fy + 0.1 + 0.8 * (k in (2, 3))) / 2
            uv.data[li].uv = cell_uv(cell, u, v, margin=0.05)
    return me


def cube(name, location, mat, cell, mesh=None, size=0.06):
    obj = link(bpy.data.objects.new(name, mesh or cube_mesh(name, mat, cell, size)))
    obj.location = location
    return obj


def write_png(path, values, bits=16):
    core.write_png_int(str(path), values, bits)
    return str(path)


def build_scene():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    scene = bpy.context.scene
    scene.frame_set(1)
    s = scene.fss_ao_bake
    s.distance, s.samples, s.threads, s.padding = 0.1, 16, 12, PAD
    s.output_folder = str(OUT)
    scene.fss_ao_no_occluder_tags = 'noocc'
    scene.fss_ao_skip_bake_tags = 'skip'
    set_a, set_b = material('SET_A'), material('SET_B')
    decal, glass = material('F_DECAL'), material('F_GLASS')
    plane('A', (0, 0, 0), set_a, 0)
    cube('O1', (0, 0, 0), set_b, 0)
    plane('B', (1, 0, 0), set_a, 1)
    tags.set_tags(cube('O2', (1, 0, 0), set_b, 1), ['noocc'])
    plane('C', (2, 0, 0), set_a, 2)
    m = cube('M', (2, 0, 0), set_b, 2)
    m.keyframe_insert('location', frame=1)
    m.location.z = 0.01
    m.keyframe_insert('location', frame=50)
    scene.frame_set(1)
    plane('D', (3, 0, 0), set_a, 3)
    shared = cube_mesh('MESH_SHARED_CUBE', set_b, 3)
    cube('S1', (3.04, 0, 0), set_b, 0, mesh=shared)
    cube('S2', (2.96, 0, 0), set_b, 0, mesh=shared)
    plane('E', (4, 0, 0), set_a, 4)
    tags.set_tags(cube('K', (4, 0, 0), set_b, 4), ['skip'])
    plane('F', (5, 0, 0), set_a, 5, extra_mats={0: (decal, 12), 15: (glass, 13)})
    cube('O6', (5, 0, 0), set_b, 5)
    cube('Z', (0.6, 0, 0), set_b, 6)  # outside A's AO distance
    # ORM slot textures (16-bit and 8-bit) on their own sets
    rng = np.random.default_rng(5)
    orm16 = np.zeros((SIZE, SIZE, 3), np.int64)
    orm16[:, :, 0] = 32768
    orm16[:, :, 1:] = rng.integers(0, 65536, (SIZE, SIZE, 2))
    orm8 = np.zeros((SIZE, SIZE, 3), np.int64)
    orm8[:, :, 0] = 128
    orm8[:, :, 1:] = rng.integers(0, 256, (SIZE, SIZE, 2))
    WORK.mkdir(parents=True, exist_ok=True)
    p16 = write_png(WORK / 'orm16.png', orm16)
    p8 = write_png(WORK / 'orm8.png', orm8, bits=8)
    set_orm, set_orm8 = material('SET_ORM'), material('SET_ORM8')
    set_orm.msfs_occlusion_metallic_roughness_texture = bpy.data.images.load(p16)
    set_orm8.msfs_occlusion_metallic_roughness_texture = bpy.data.images.load(p8)
    plane('P', (6, 0, 0), set_orm, 0)
    cube('O7', (6, 0, 0), set_b, 7)
    plane('P8', (7, 0, 0), set_orm8, 0)
    cube('O8', (7, 0, 0), set_b, 8)
    # per-object Apply: two planes whose islands lie 4 px apart in one texture set
    set_po = material('SET_PO')
    q1 = plane('Q1', (8, 0, 0), set_po, 0)
    q2 = plane('Q2', (8.5, 0, 0), set_po, 0)
    for obj, (u0, u1) in ((q1, (0.10, 0.45)), (q2, (0.45 + 4 / SIZE, 0.85))):
        uv = obj.data.uv_layers['UVMap']
        for poly in obj.data.polygons:
            for li in poly.loop_indices:
                x, y, _z = obj.data.vertices[obj.data.loops[li].vertex_index].co
                uv.data[li].uv = (u0 + (x / 0.2 + 0.5) * (u1 - u0), 0.2 + (y / 0.2 + 0.5) * 0.5)
    cube('O9', (8, 0, 0), set_b, 9)
    # neighbour islands of different green (G1, G2 in SET_GB, 4 px apart)
    set_gb = material('SET_GB')
    g1 = plane('G1', (9, 0, 0), set_gb, 0)
    g2 = plane('G2', (9.5, 0, 0), set_gb, 0)
    for obj, (u0, u1) in ((g1, (0.10, 0.45)), (g2, (0.45 + 4 / SIZE, 0.85))):
        uv = obj.data.uv_layers['UVMap']
        for poly in obj.data.polygons:
            for li in poly.loop_indices:
                x, y, _z = obj.data.vertices[obj.data.loops[li].vertex_index].co
                uv.data[li].uv = (u0 + (x / 0.2 + 0.5) * (u1 - u0), 0.2 + (y / 0.2 + 0.5) * 0.5)
    # decision 30: N has faces of SET_A and faces in an empty slot; NM has no material at all
    n_obj = plane('N', (10, 0, 0), set_a, 6)
    n_obj.data.materials.append(None)
    for poly in n_obj.data.polygons:
        if poly.index < 4:
            poly.material_index = 1
    cube('ON', (10, 0, 0), set_b, 10)
    nm = plane('NM', (11, 0, 0), set_a, 7)
    nm.data.materials.clear()
    WORK.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND))


def gb_texture():
    """SET_GB's ORM texture: green 0.2 on G1's island and padding, 0.8 on G2's, blue the other way round; written
    after the bake (it needs the island labels Apply computes)."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    parts = []
    for name in ('G1', 'G2'):
        ev = core.evaluated_triangles(bpy.data.objects[name], depsgraph, ['UVMap'])
        wt = core.weld_ids(ev['co'])[ev['tris']]
        uv = ev['uv']['UVMap']
        parts.append((uv * SIZE, core.uv_islands(wt, uv)))
    lab = core.island_labels(parts, SIZE, SIZE, PAD)
    vals = np.full((SIZE, SIZE, 3), 30000, np.int64)
    n1 = int(parts[0][1].max()) + 1
    g1 = (lab >= 0) & (lab < n1)
    g2 = lab >= n1
    vals[g1, 1], vals[g1, 2] = round(0.2 * 65535), round(0.6 * 65535)
    vals[g2, 1], vals[g2, 2] = round(0.8 * 65535), round(0.1 * 65535)
    path = write_png(WORK / 'orm_gb.png', vals)
    mat = bpy.data.materials['SET_GB']
    mat.msfs_occlusion_metallic_roughness_texture = bpy.data.images.load(path)
    return parts, n1


# ---------------------------------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------------------------------

def refresh():
    bpy.ops.fss.ao_bake_refresh()
    return store._state


def grade_of(name):
    return store._state['items'][store._state['by_object'][name]]['grade']


def entry_of(name):
    stem = store._state['by_object'][name]
    return store.read_index(str(FOLDER), use_cache=False)['masters'].get(stem), stem


def master_image(name):
    _e, stem = entry_of(name)
    m = core.load_master(str(FOLDER), stem)
    return m, m['image'][m['filled']] / 65535.0


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def datablocks():
    out = {}
    for attr in dir(bpy.data):
        coll = getattr(bpy.data, attr, None)
        if isinstance(coll, bpy.types.bpy_prop_collection):
            out[attr] = len(coll)
    return out


def snapshot():
    return dict(counts=datablocks(), matrices={o.name: tuple(map(tuple, o.matrix_world)) for o in bpy.data.objects},
                materials=sorted((m.name, m.users, len(m.node_tree.nodes) if m.node_tree else 0)
                                 for m in bpy.data.materials),
                images=sorted((i.name, i.filepath, tuple(i.size)) for i in bpy.data.images),
                slots={o.name: [s.material.name if s.material else None for s in o.material_slots]
                       for o in bpy.data.objects})


def select(names):
    for obj in bpy.context.view_layer.objects:
        obj.select_set(obj.name in names)
    if names:
        bpy.context.view_layer.objects.active = bpy.data.objects[names[0]]


class ApplySettings(SimpleNamespace):
    def __init__(self, **kw):
        base = dict(target='FILE', file_name='', resolution='ORM', layout='GREY', green_blue='WHITE',
                    sampling='AUTOMATIC')
        base.update(kw)
        super().__init__(**base)


def apply_set(name, objects=None, band_rows=ao_bake_apply.APPLY_BAND, **kw):
    mat = bpy.data.materials[name]
    rep = ao_bake_apply.apply_set(bpy.context, mat, objects, ApplySettings(**kw), band_rows=band_rows)
    assert not rep.get('error'), rep
    return rep


def read(path):
    vals, bits, ct = core.read_png(path)
    return (vals if vals.ndim == 3 else vals[:, :, None]), bits, ct


def faces_mask(name, W=SIZE, H=SIZE, material=None):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    obj = bpy.data.objects[name]
    ev = core.evaluated_triangles(obj, depsgraph, ['UVMap'])
    sel = np.ones(len(ev['tris']), bool)
    if material is not None:
        slots = [s.material.name for s in obj.material_slots]
        sel = np.array([slots[m] == material for m in ev['mat']])
    own, _ = core.rasterize_ids(ev['uv']['UVMap'][sel] * np.array([W, H]), W, H)
    return own >= 0


# ---------------------------------------------------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------------------------------------------------

def test_bake_all():
    """FL8 m of m, FL3 the file untouched by a bake, FL7 rules."""
    if FOLDER.exists():
        shutil.rmtree(FOLDER)
    if OUT.exists():
        shutil.rmtree(OUT)
    state = refresh()
    names = {it['name'] for it in state['items'].values()}
    assert 'K' not in names and state['excluded'].get('K') == 'Skip-AO-Bake or No Texture tag', state['excluded']
    assert 'MESH_SHARED_CUBE' in names and 'S1' not in names, names
    assert all(it['grade'] == 'MISSING' for it in state['items'].values())
    before_hash = file_hash(BLEND)
    before = snapshot()
    t = time.time()
    res = bpy.ops.fss.ao_bake_start(scope='STALE', hidden=True, wait=True)
    assert res == {'FINISHED'}, res
    status = store.read_status(str(FOLDER))
    m = len(state['items'])
    assert status['state'] == 'done' and status['n_done'] == status['n_total'] == m, status
    assert all(r['status'] == 'baked' for r in status['results']), status['results']
    after = snapshot()
    assert file_hash(BLEND) == before_hash
    assert after == before, [k for k in before if before[k] != after[k]]
    assert all(it['grade'] == 'UP_TO_DATE' for it in store._state['items'].values()), \
        {it['name']: it['grade'] for it in store._state['items'].values()}
    # FL7: no master for K; decal and glass faces not in F's master
    files = sorted(p.name for p in FOLDER.iterdir())
    assert not any(p.startswith('K_') for p in files), files
    f_master, _vals = master_image('F')
    ev = core.evaluated_triangles(bpy.data.objects['F'], bpy.context.evaluated_depsgraph_get(), [])
    slots = [s.material.name for s in bpy.data.objects['F'].material_slots]
    skip_tris = {i for i, mi in enumerate(ev['mat'].tolist()) if slots[mi] in ('F_DECAL', 'F_GLASS')}
    assert len(skip_tris) == 4 and not skip_tris & set(f_master['tri_src'].tolist()), skip_tris
    assert len(f_master['tri_src']) == len(ev['tris']) - 4
    # decision 30 (Session 19, finish line 6): N's faces without a material not in its master; NM excluded
    assert state['excluded'].get('NM') == 'no face with a texture set (material)', state['excluded']
    assert 'NM' not in names and not any(p.startswith('NM_') for p in files), files
    n_master, _vals = master_image('N')
    ev_n = core.evaluated_triangles(bpy.data.objects['N'], bpy.context.evaluated_depsgraph_get(), [])
    no_set = set(np.nonzero(ev_n['mat'] == 1)[0].tolist())
    assert len(no_set) == 8 and not no_set & set(n_master['tri_src'].tolist()), no_set
    assert len(n_master['tri_src']) == len(ev_n['tris']) - 8
    report = bpy.context.window_manager.fss_ao_bake_state.report
    assert 'excluded (no face with a texture set (material)): 1: NM' in report, report
    # FL7: darkening
    mins = {n: float(master_image(n)[1].min()) for n in ('A', 'B', 'C', 'D', 'E', 'O1', 'S1', 'M')}
    assert mins['A'] < 0.9 and mins['D'] < 0.9 and mins['E'] < 0.9, mins  # O1, S1/S2, K (skip-bake) darken
    assert mins['B'] > 0.999, mins  # O2 Non-AO-Occluder darkens nothing
    assert mins['C'] > 0.999, mins  # M is a mover: it darkens no other object
    assert mins['S1'] > 0.999, mins  # the shared mesh: self-shading only (a convex cube)
    assert mins['O1'] < 0.9 and mins['M'] < 0.9, mins  # an own-mesh cube is darkened by its plane
    times = {r['name']: r['bake_s'] for r in status['results']}
    print(f"PASS: test_bake_all ({m} masters in {time.time() - t:.1f} s, m of m; .blend hash, datablocks, matrices, "
          f"materials, images unchanged; no master for K; F's 4 decal/glass triangles not in its master; N's 8 "
          f"triangles without a material not in its master ({len(n_master['tri_src'])} kept); NM excluded and "
          f"listed in the report; minima {mins}; bake s {times})")
    return status


def test_cancel():
    """FL8: Cancel stops after the current object; the finished masters are kept."""
    names = ['A', 'B', 'C', 'E']
    select(names)
    stems = store.items_for_objects([bpy.data.objects[n] for n in names])
    old = {s: os.path.getmtime(store.master_files(str(FOLDER), s)[0]) for s in stems}
    res = bpy.ops.fss.ao_bake_start(scope='SELECTED', hidden=True, wait=False, test_delay=4.0)
    assert res == {'FINISHED'}
    proc = store._run['proc']
    t = time.time()
    while time.time() - t < 120:
        st = store.read_status()
        if st and st.get('n_done', 0) >= 1:
            break
        time.sleep(0.2)
    store.cancel()
    proc.wait(timeout=300)
    ao_bake.finish_bake()
    status = store.read_status()
    assert status['state'] == 'cancelled' and status['n_done'] == 1 and status['n_total'] == 4, status
    first = status['results'][0]['key']
    assert os.path.getmtime(store.master_files(str(FOLDER), first)[0]) > old[first]
    for s in stems:
        assert store.has_files(str(FOLDER), s), s
        if s != first:
            assert os.path.getmtime(store.master_files(str(FOLDER), s)[0]) == old[s], s
    print(f"PASS: test_cancel (cancelled after {status['n_done']} of {status['n_total']}: {status['results'][0]['name']} "
          "re-baked, the others' masters kept unchanged)")


def test_tiles():
    """Session 19: a master baked in tiles of 64 px equals the untiled one but for noise; Cancel between tiles stops
    within one tile and keeps the object's old master (finish line 7)."""
    select(['A'])
    stem = store.items_for_objects([bpy.data.objects['A']])[0]
    png, mp, npz = core.master_paths(str(FOLDER), stem)
    untiled, _v = master_image('A')
    old = (os.path.getmtime(png), os.path.getmtime(npz), file_hash(png), file_hash(mp))
    # Cancel between tiles
    res = bpy.ops.fss.ao_bake_start(scope='SELECTED', hidden=True, wait=False, tile=64, test_tile_delay=1.0)
    assert res == {'FINISHED'}
    proc = store._run['proc']
    t = time.time()
    while time.time() - t < 120:
        st = store.read_status()
        if st and st.get('tile', 0) >= 2:
            break
        time.sleep(0.05)
    n_tiles = st['n_tiles']
    t_cancel = time.time()
    store.cancel()
    proc.wait(timeout=300)
    stop_s = time.time() - t_cancel
    ao_bake.finish_bake()
    status = store.read_status()
    assert status['state'] == 'cancelled' and status['n_done'] == 0, status
    r = status['results'][0]
    assert r['status'] == 'cancelled', r
    assert (os.path.getmtime(png), os.path.getmtime(npz), file_hash(png), file_hash(mp)) == old
    assert not any(os.path.exists(p + '.tmp') for p in (png, mp, npz)) and not os.path.exists(png + '.tmp.raw')
    log_text = (FOLDER / 'bake.log').read_text(encoding='utf-8')
    tile_s = max(float(x.split(', ')[-1].rstrip(' s')) for x in log_text.splitlines()
                 if 'tile ' in x and ' triangles, ' in x)
    # within one tile's time (and the test's pause of 1 s per tile, and Blender's quit)
    assert stop_s < 1.0 + tile_s + 5.0, (stop_s, tile_s)
    # a whole bake in tiles of 64 px
    res = bpy.ops.fss.ao_bake_start(scope='SELECTED', hidden=True, wait=True, tile=64)
    status = store.read_status()
    assert status['state'] == 'done' and status['results'][0]['status'] == 'baked', status
    assert status['results'][0]['n_tiles'] == n_tiles > 1
    tiled, _v = master_image('A')
    assert tiled['image'].shape == untiled['image'].shape and np.array_equal(tiled['filled'], untiled['filled'])
    assert np.array_equal(tiled['face_map'], untiled['face_map'])
    both = tiled['filled'] & untiled['filled']
    mae = float(np.abs(tiled['image'][both].astype(np.float64) - untiled['image'][both]).mean() / 65535.0)
    assert mae < 0.05, mae
    assert grade_of('A') == 'UP_TO_DATE'
    print(f"PASS: test_tiles (Cancel: {r['reason']}; stopped {stop_s:.1f} s after the cancel file, a tile "
          f"took at most {tile_s:.2f} s + the test's 1 s pause; the old master kept byte for byte; a bake in "
          f"{n_tiles} tiles of 64 px: the same layout, filled pixels and face map as the untiled master, MAE "
          f"{mae:.4f} at 16 samples)")


def test_paged():
    """Session 23 (decision 33): the master paged. A's master, baked in tiles of 64 px by test_tiles, came in several
    bands, composed and written band by band; its .npz holds no per-pixel array (they are in the .ao.map). Apply
    through the paged master (scratch files, a cache of tiles) writes the same file in bands of 5 rows as in bands of
    256 rows, and the same file as the copy of the whole master held in memory; it leaves no scratch file."""
    refresh()
    entry, stem = entry_of('A')
    tiles = entry['tiles']
    assert tiles['bands'] > 1 and tiles['n'] > tiles['bands'], tiles
    png, mp, npz = core.master_paths(str(FOLDER), stem)
    with np.load(npz) as z:
        assert not ({'filled', 'face_map'} & set(z.files)), z.files
    m = core.load_master(str(FOLDER), stem)
    assert m['image'].shape == (entry['H'], entry['W']) and m['filled'].any() and (m['face_map'] >= 0).any()
    sizes = {}
    for objects, tag in ((None, 'set'), ([bpy.data.objects['A']], 'object')):
        if objects:
            OUT.mkdir(parents=True, exist_ok=True)
            base = np.random.default_rng(3).integers(0, 65536, (SIZE, SIZE, 3))
            for b in ('5', '256', 'whole'):
                write_png(OUT / f'paged_{tag}_{b}.png', base)
        rep = apply_set('SET_A', objects, file_name=f'paged_{tag}_256.png')
        rep5 = apply_set('SET_A', objects, band_rows=5, file_name=f'paged_{tag}_5.png')
        assert rep['page_loads'] and rep5['page_loads'], (rep.get('page_loads'), rep5.get('page_loads'))
        opened = core.open_master

        def whole(folder, s, cache_bytes=0):
            out = core.load_master(folder, s)
            out['close'] = lambda: None
            return out
        core.open_master = whole
        try:
            repw = apply_set('SET_A', objects, file_name=f'paged_{tag}_whole.png')
        finally:
            core.open_master = opened
        h256, h5, hw = (file_hash(r['path']) for r in (rep, rep5, repw))
        assert h256 == h5 == hw, (tag, h256, h5, hw)
        assert rep['written_px'] == rep5['written_px'] == repw['written_px'] > 0
        sizes[tag] = rep['written_px']
    left = [f for f in os.listdir(FOLDER) if f.endswith(('.page', '.mappage', '.tmp', '.raw'))]
    assert not left, left
    print(f"PASS: test_paged (A's master {entry['W']} x {entry['H']} px in {tiles['n']} tiles, {tiles['bands']} bands; "
          f"no per-pixel array in the .npz; Apply of the set and of A alone: bands of 5 and 256 rows and the whole "
          f"master in memory give byte-identical files ({sizes} px written); no scratch file left)")


def test_formats():
    """Session 26 (decision 37), finish lines 5 and 6: the masters are JPEG XL; a PNG master as 0.55.2 wrote it is
    applied unchanged and a re-bake replaces it with a .jxl, removing the PNG; with the library made unloadable the
    bake writes PNG, says so once in the report, and Apply works."""
    lib = core.jxl()
    assert lib.available(), lib.error()
    refresh()
    folder = str(FOLDER)
    names = os.listdir(folder)
    assert not any(n.endswith('.ao.png') for n in names), [n for n in names if n.endswith('.ao.png')]
    index = store.read_index(folder, use_cache=False)
    assert index['schema'] == core.SCHEMA == 3
    jx = [e for e in index['masters'].values() if e.get('image', {}).get('format') == 'jxl']
    assert len(jx) == len(index['masters']) and all(e['schema'] == 3 for e in jx), len(jx)
    assert all(n.endswith('.ao.jxl') for n in names if '.ao.' in n and n.endswith(('.jxl', '.png')))
    entry, stem = entry_of('A')
    jpath, ppath = core.image_paths(folder, stem)
    img = core.read_image(jpath)
    m = core.load_master(folder, stem)
    assert m['image'].shape == (entry['H'], entry['W']) and np.array_equal(m['image'], img)
    ref = apply_set('SET_A', file_name='fmt_jxl.png')
    # a PNG master as 0.55.2 wrote it (its writer is unchanged): the same pixels, the .jxl removed, schema 2
    core.write_png_int(ppath, img)
    os.remove(jpath)
    index['masters'][stem]['schema'] = 2
    index['masters'][stem].pop('image', None)
    store.write_index(folder, index)
    refresh()
    assert grade_of('A') == 'UP_TO_DATE' and core.master_paths(folder, stem)[0] == ppath
    old = apply_set('SET_A', file_name='fmt_png_0552.png')
    assert file_hash(old['path']) == file_hash(ref['path']) and old['written_px'] == ref['written_px'] > 0
    # a re-bake replaces it with a .jxl and removes the PNG
    select(['A'])
    assert bpy.ops.fss.ao_bake_start(scope='SELECTED', hidden=True, wait=True) == {'FINISHED'}
    assert os.path.isfile(jpath) and not os.path.exists(ppath), os.listdir(folder)
    assert grade_of('A') == 'UP_TO_DATE'
    OUT.mkdir(parents=True, exist_ok=True)
    base = np.random.default_rng(7).integers(0, 65536, (SIZE, SIZE, 3))
    for tag in ('rebaked_jxl', 'nolib_png'):
        write_png(OUT / f'fmt_{tag}.png', base)
    # per object: without the library only A's master (PNG) can be read; the set's other masters are .jxl
    rebaked = apply_set('SET_A', [bpy.data.objects['A']], file_name='fmt_rebaked_jxl.png')
    # no library: the second Blender inherits the switch
    os.environ[lib.DISABLE_ENV] = '1'
    lib.reset()
    try:
        assert not lib.available() and lib.DISABLE_ENV in lib.error()
        assert bpy.ops.fss.ao_bake_start(scope='SELECTED', hidden=True, wait=True) == {'FINISHED'}
        report = bpy.context.window_manager.fss_ao_bake_state.report
        status = store.read_status(folder)
        assert status['master_format'] == 'png' and status['results'][0]['status'] == 'baked', status
        assert report.count('masters written as PNG') == 1, report
        assert os.path.isfile(ppath) and not os.path.exists(jpath), os.listdir(folder)
        log_lines = [x for x in (FOLDER / 'bake.log').read_text(encoding='utf-8').splitlines()[-6:]
                     if 'masters as PNG' in x]
        assert len(log_lines) == 1, log_lines
        refresh()
        assert grade_of('A') == 'UP_TO_DATE'
        nolib = apply_set('SET_A', [bpy.data.objects['A']], file_name='fmt_nolib_png.png')
        try:  # the whole set needs the other masters' .jxl: reported as an error, nothing written
            ao_bake_apply.apply_set(bpy.context, bpy.data.materials['SET_A'], None,
                                    ApplySettings(file_name='fmt_nolib_set.png'))
            set_error = None
        except OSError as exc:
            set_error = str(exc)
        assert set_error and 'JPEG XL library is not loaded' in set_error, set_error
        assert not (OUT / 'fmt_nolib_set.png').exists()
    finally:
        del os.environ[lib.DISABLE_ENV]
        lib.reset()
    assert lib.available()
    same_bake = file_hash(nolib['path']) == file_hash(rebaked['path'])  # reported: equal when Cycles repeats itself
    # and back to JPEG XL
    assert bpy.ops.fss.ao_bake_start(scope='SELECTED', hidden=True, wait=True) == {'FINISHED'}
    assert os.path.isfile(jpath) and not os.path.exists(ppath)
    left = [f for f in os.listdir(FOLDER) if f.endswith(('.page', '.mappage', '.tmp', '.raw'))]
    assert not left, left
    print(f"PASS: test_formats ({len(jx)} masters .jxl, schema 3; A as a 0.55.2 PNG master: up to date, Apply "
          f"byte-identical to the .jxl's ({ref['written_px']} px); a re-bake wrote the .jxl and removed the PNG; "
          f"without the library: PNG written, the report says so once ({[x for x in report.splitlines() if 'PNG' in x][0]}), "
          f"Apply of A written ({nolib['written_px']} px; the same file as the JPEG XL re-bake's: {same_bake}), the "
          f"whole set (other masters .jxl) refused with an error; back to .jxl; no scratch file left)")

def test_staleness():
    """FL2: each change gives its grade."""
    scene = bpy.context.scene
    a, o1, z = bpy.data.objects['A'], bpy.data.objects['O1'], bpy.data.objects['Z']
    assert refresh() and grade_of('A') == 'UP_TO_DATE'
    results = {}

    def check(label, expect):
        refresh()
        got = grade_of('A')
        results[label] = got
        assert got == expect, (label, got, expect)

    co = a.data.vertices[6].co.copy()
    a.data.vertices[6].co.z += 0.001
    a.data.update()
    check('moved vertex', 'MESH')
    a.data.vertices[6].co = co
    a.data.update()
    check('vertex back', 'UP_TO_DATE')
    normals = [(0.0, 0.3, 0.954)] * len(a.data.loops)
    a.data.normals_split_custom_set(normals)
    check('custom normals', 'MESH')
    a.data.free_normals_split() if hasattr(a.data, 'free_normals_split') else None
    a.data.attributes.remove(a.data.attributes['custom_normal']) if 'custom_normal' in a.data.attributes else None
    a.data.update()
    check('custom normals cleared', 'UP_TO_DATE')
    mod = a.modifiers.new('Subdivision', 'SUBSURF')
    check('added modifier', 'MESH')
    a.modifiers.remove(mod)
    check('modifier removed', 'UP_TO_DATE')
    o1.location.x += 0.01
    check('occluder moved inside the distance', 'SURROUNDINGS')
    o1.location.x -= 0.01
    check('occluder back', 'UP_TO_DATE')
    tags.set_tags(o1, ['noocc'])
    check('occluder tagged Non-AO-Occluder', 'SURROUNDINGS')
    tags.set_tags(o1, [])
    check('tag removed', 'UP_TO_DATE')
    scene.fss_ao_bake.distance = 0.12
    check('AO distance changed', 'SURROUNDINGS')
    scene.fss_ao_bake.distance = 0.1
    check('distance back', 'UP_TO_DATE')
    a.location.y += 0.01
    check('object moved', 'SURROUNDINGS')
    a.location.y -= 0.01
    check('object back', 'UP_TO_DATE')
    z.location.x += 0.05
    check('occluder outside the distance moved', 'UP_TO_DATE')
    z.location.x -= 0.05
    uv = a.data.uv_layers['UVMap']
    orig = np.empty(len(uv.data) * 2, np.float32)
    uv.data.foreach_get('uv', orig)
    uv.data.foreach_set('uv', orig + 0.01)
    check('UVs moved', 'UP_TO_DATE')
    uv.data.foreach_set('uv', orig * 0.5)
    check('UVs scaled', 'UP_TO_DATE')
    for poly in a.data.polygons:  # a different unwrap: islands per face
        for k, li in enumerate(poly.loop_indices):
            uv.data[li].uv = ((poly.index % 4 + 0.1 + 0.8 * (k in (1, 2))) / 4,
                              (poly.index // 4 + 0.1 + 0.8 * (k in (2, 3))) / 4)
    check('UVs re-unwrapped', 'UP_TO_DATE')
    uv.data.foreach_set('uv', orig)
    a.material_slots[0].material = bpy.data.materials['SET_PO']
    check('material changed', 'UP_TO_DATE')
    a.material_slots[0].material = bpy.data.materials['SET_A']
    a.data.update()
    _e, old_stem = entry_of('A')
    a.name = 'A_RENAMED'
    state = refresh()
    assert grade_of('A_RENAMED') == 'UP_TO_DATE' and ('A', 'A_RENAMED') in state['relinked'], state.get('relinked')
    assert not store.has_files(str(FOLDER), old_stem)
    results['renamed'] = 'relinked, UP_TO_DATE'
    a.name = 'A'
    state = refresh()
    assert grade_of('A') == 'UP_TO_DATE' and ('A_RENAMED', 'A') in state['relinked']
    print(f'PASS: test_staleness ({results})')


def test_apply_orm():
    """FL4: into the ORM slot texture, 16-bit and 8-bit."""
    refresh()
    p16 = str(WORK / 'orm16.png')
    p8 = str(WORK / 'orm8.png')
    orig16, bits16, _ = read(p16)
    bytes16 = Path(p16).read_bytes()
    orig8, bits8, _ = read(p8)
    before = datablocks()
    rep = apply_set('SET_ORM', target='ORM')
    assert datablocks() == before
    new, bits, ct = read(p16)
    assert bits == 16 and ct == 2, (bits, ct)
    assert np.array_equal(new[:, :, 1:], orig16[:, :, 1:])
    face = faces_mask('P')
    assert (new[:, :, 0][face] != 32768).all() and new[:, :, 0][face].min() < 0.9 * 65535
    assert Path(rep['backup']).read_bytes() == bytes16
    assert any('Substance' in w for w in rep['warnings'])
    rep8 = apply_set('SET_ORM8', target='ORM')
    new8, bits, _ = read(p8)
    assert bits == 16 and np.array_equal(new8[:, :, 1:], orig8[:, :, 1:].astype(np.uint32) * 257)
    assert any('8-bit' in w for w in rep8['warnings']), rep8['warnings']
    assert (new8[:, :, 0][faces_mask('P8')] != 128 * 257).all()
    print(f"PASS: test_apply_orm (red written on {int(face.sum())} face px, green and blue byte for byte, 16-bit, "
          f"backup identical; 8-bit ORM warned ({[w for w in rep8['warnings'] if '8-bit' in w][0]}) and written "
          f"16-bit with green and blue x 257; {rep['seconds']} s and {rep8['seconds']} s; no datablock added)")


def test_apply_per_object():
    """FL5: only the selected objects' faces and padding change; no padding inside another object's face."""
    refresh()
    rng = np.random.default_rng(11)
    path = OUT / 'SET_PO_ao.png'
    OUT.mkdir(parents=True, exist_ok=True)
    base = rng.integers(0, 65536, (SIZE, SIZE, 3))
    write_png(path, base)
    rep = apply_set('SET_PO', objects=[bpy.data.objects['Q1']])
    new, _bits, _ = read(str(path))
    changed = (new != base).any(axis=2)
    q1, q2 = faces_mask('Q1'), faces_mask('Q2')
    grown, steps = core.dilate_ids(np.where(q1, 0, -1), PAD)
    allowed = q1 | ((grown >= 0) & ~q2)
    assert not (changed & ~allowed).any(), int((changed & ~allowed).sum())
    assert not (changed & q2).any()
    padding_written = int((changed & ~q1).sum())
    assert padding_written > 0 and changed[q1].all()
    # the padding reached Q2's island: some allowed padding pixels lie next to Q2
    near_q2 = core.dilate_ids(np.where(q2, 0, -1), 2)[0] >= 0
    assert (changed & near_q2 & ~q2).any()
    print(f"PASS: test_apply_per_object ({int(changed.sum())} px changed: {int(q1.sum())} face px of Q1, "
          f"{padding_written} padding px; 0 outside Q1's faces and padding, 0 in Q2's {int(q2.sum())} face px; "
          f"{rep['seconds']} s)")


def test_apply_separate():
    """FL6: greyscale, ORM layout white and copied, another size and each sampling method, islands not mixed."""
    refresh()
    rep = apply_set('SET_A', file_name='grey.png')
    g, bits, ct = read(rep['path'])
    assert bits == 16 and ct == 2 and (g[:, :, 0] == g[:, :, 1]).all() and (g[:, :, 0] == g[:, :, 2]).all()
    assert g[:, :, 0].min() < 0.9 * 65535
    rep = apply_set('SET_ORM', file_name='orm_white.png', layout='ORM', green_blue='WHITE')
    w, _b, _ = read(rep['path'])
    assert (w[:, :, 1:] == 65535).all()
    orig16, _b, _ = read(str(WORK / 'orm16.png'))
    rep = apply_set('SET_ORM', file_name='orm_copy.png', layout='ORM', green_blue='COPY')
    c, _b, _ = read(rep['path'])
    assert np.array_equal(c[:, :, 1:], orig16[:, :, 1:]) and not rep['warnings'], rep['warnings']
    sizes = {}
    for res in ('128', '512'):
        for method in ('AUTOMATIC', 'NEAREST', 'BICUBIC'):
            rep = apply_set('SET_ORM', file_name=f'orm_{res}_{method}.png', layout='ORM', green_blue='COPY',
                            resolution=res, sampling=method)
            v, _b, _ = read(rep['path'])
            assert v.shape[:2] == (int(res), int(res)) and any('resampled' in x for x in rep['warnings'])
            sizes[(res, method)] = rep['seconds']
    # neighbour islands of different green and blue never mix
    parts, n1 = gb_texture()
    refresh()
    worst = 0
    for res in ('128', '512'):
        for method in ('AUTOMATIC', 'NEAREST', 'BICUBIC'):
            rep = apply_set('SET_GB', file_name=f'gb_{res}_{method}.png', layout='ORM', green_blue='COPY',
                            resolution=res, sampling=method)
            v, _b, _ = read(rep['path'])
            R = int(res)
            for name, gv, bv in (('G1', 0.2, 0.6), ('G2', 0.8, 0.1)):
                m = faces_mask(name, R, R)
                dg = np.abs(v[:, :, 1][m] / 65535.0 - gv).max()
                db = np.abs(v[:, :, 2][m] / 65535.0 - bv).max()
                worst = max(worst, dg, db)
                assert dg < 2e-5 and db < 2e-5, (res, method, name, dg, db)
    print(f"PASS: test_apply_separate (greyscale R = G = B; ORM layout white; copied byte for byte at the same size; "
          f"128 and 512 px with Automatic, Nearest and Bicubic warned and written {sizes}; G1 / G2 green and blue "
          f"within {worst:.1e} of their own value in every method and size)")


def test_rules_apply():
    """FL7: decal and glass faces not written; faces under 4 x counted."""
    refresh()
    rep = apply_set('SET_A', file_name='rules.png')
    assert 'F_DECAL' not in store._state['sets'] and 'F_GLASS' not in store._state['sets']
    v, _b, _ = read(rep['path'])
    dec = faces_mask('F', material='F_DECAL') | faces_mask('F', material='F_GLASS')
    a_faces = np.zeros_like(dec)
    for n in ('A', 'B', 'C', 'D', 'E', 'F'):
        a_faces |= faces_mask(n, material='SET_A')
    grown = core.dilate_ids(np.where(a_faces, 0, -1), PAD)[0] >= 0
    assert dec.any() and (v[:, :, 0][dec & ~grown] == 65535).all()
    assert rep['faces_under_4x'] == 0, rep['faces_under_4x']
    mat = bpy.data.materials['SET_A']
    mat.fss_uv_texture_size = '1024'
    rep2 = apply_set('SET_A', file_name='rules_1024.png')
    mat.fss_uv_texture_size = str(SIZE)
    assert rep2['size'] == [1024, 1024] and rep2['faces_under_4x'] == rep2['faces'] > 0, rep2
    print(f"PASS: test_rules_apply (no row for the decal and glass sets; their {int(dec.sum())} px in SET_A's file "
          f"not written; faces under 4 x: {rep['faces_under_4x']} of {rep['faces']} at {SIZE} px, "
          f"{rep2['faces_under_4x']} of {rep2['faces']} at 1024 px)")


class _Layout:
    def __init__(self, calls):
        self.calls = calls

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if name == 'operator':
                return SimpleNamespace()
            if name in ('row', 'column', 'box', 'split'):
                return _Layout(self.calls)
            return None
        return call


def test_draw():
    refresh()
    st = bpy.context.window_manager.fss_ao_bake_state

    def props():
        return ({p.identifier: getattr(st, p.identifier) for p in st.bl_rna.properties
                 if p.identifier not in ('rna_type', 'sets')},
                [(r.material, r.state, r.warn) for r in st.sets], datablocks(), bpy.context.scene.fss_ao_bake.samples)
    for i in range(len(st.sets)):
        st.active_set = i
        before = props()
        calls = []
        bpy.types.FSS_PT_ao_bake.draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
        assert props() == before
        ops = [args[0] for name, args, _kw in calls if name == 'operator']
        assert 'fss.ao_bake_start' in ops and 'fss.ao_apply' in ops, ops
    print(f"PASS: test_draw ({len(st.sets)} texture set rows drawn without writing; rows "
          f"{[(r.material, r.state) for r in st.sets]})")


def test_panel_selection():
    """Session 31 (decision 40): the texture-set list shows the selection's sets (all when nothing is selected); the
    Apply box names its set, and its Apply works only when the target can be written; an object's own pose count; the
    object's Default occluder names the scene's."""
    refresh()
    ctx = bpy.context
    st = ctx.window_manager.fss_ao_bake_state
    select([])
    assert ao_bake.selected_sets(ctx) is None
    flags = ao_bake.FSS_UL_AOSets.filter_items(SimpleNamespace(bitflag_filter_item=1 << 30), ctx, st, 'sets')[0]
    assert all(flags) and len(flags) == len(st.sets)
    select(['A'])
    sel = ao_bake.selected_sets(ctx)
    item = store._state['items'][store._state['by_object']['A']]
    assert sel and sel == set(item['sets']), (sel, item['sets'])
    flags = ao_bake.FSS_UL_AOSets.filter_items(SimpleNamespace(bitflag_filter_item=1 << 30), ctx, st, 'sets')[0]
    shown = [r.material for r, f in zip(st.sets, flags) if f]
    assert sorted(shown) == sorted(sel), (shown, sel)
    if len(sel) == 1:
        assert ao_bake.apply_material(ctx, st).name in sel
    mat = bpy.data.materials[sorted(sel)[0]]
    a = mat.fss_ao_apply
    old = a.target
    a.target = 'FILE'
    assert ao_bake.target_problem(ctx, mat) == ''
    a.target = 'ORM'
    refused = None
    if ao_bake.apply_mod.orm_image(mat) is None:
        assert ao_bake.target_problem(ctx, mat) == 'No texture in the ORM slot'
        try:
            refused = bpy.ops.fss.ao_apply(scope='SET', material=mat.name)
        except RuntimeError as e:  # an operator's ERROR report raises in a script
            refused = str(e)
        assert refused == {'CANCELLED'} or 'ORM slot' in str(refused), refused
    a.target = old
    o = bpy.data.objects['A'].fss_ao_bake
    o.poses = 0
    assert o.pose_mode == 'DEFAULT'
    o.pose_mode = 'MANUAL'
    assert o.poses == ctx.scene.fss_ao_bake.poses
    o.pose_mode = 'DEFAULT'
    assert o.poses == 0
    names = [i[1] for i in ao_bake.object_occluder_items(o, ctx)]
    assert names[0] == 'Default (Scene Rule)' and o.occluders == 'DEFAULT', (names, o.occluders)
    select([])
    print(f"PASS: test_panel_selection (A selected: {sorted(sel)} of {len(st.sets)} sets shown; Apply into a missing "
          f"ORM texture refused: {refused!r}; own poses on and off; occluder choices {names})")


def test_apply_no_datablock():
    refresh()
    before = snapshot()
    select(['A', 'D'])
    assert bpy.ops.fss.ao_apply(scope='ALL') == {'FINISHED'}
    assert bpy.ops.fss.ao_apply(scope='SELECTED') == {'FINISHED'}
    after = snapshot()
    assert after == before, [k for k in before if before[k] != after[k]]
    print('PASS: test_apply_no_datablock (Apply All and Apply Selected: datablock counts, matrices, materials, images '
          'and material slots unchanged)')


def wait_bake(poll=0.1, limit=300):
    """While the second Blender runs: the panel's progress timer step by step (a background Blender runs no timers);
    returns the states seen: (preview seq, preview digest, tile, pose, n_poses)."""
    proc = store._run['proc']
    seen = []
    t = time.time()
    while proc.poll() is None and time.time() - t < limit:
        ao_bake._poll_timer()
        st = bpy.context.window_manager.fss_ao_bake_state
        p = ao_bake._preview
        seen.append((p['seq'], p['digest'], st.tile, st.pose, st.n_poses))
        time.sleep(poll)
    proc.wait(timeout=60)
    ao_bake._poll_timer()  # the last step: the bake ended, finish_bake runs
    return seen


def test_custom_occluders():
    """Session 25, finish line 4 (decision 35): an object outside the scene rule (Non-AO-Occluder) in a custom list
    shades the target; an object not in the list does not."""
    refresh()
    b, f, o1, o2 = (bpy.data.objects[n] for n in ('B', 'F', 'O1', 'O2'))
    assert grade_of('B') == 'UP_TO_DATE' and float(master_image('B')[1].min()) > 0.999
    b.fss_ao_bake.occluders = 'CUSTOM'
    b.fss_ao_bake.custom.add().object = o2  # tagged Non-AO-Occluder: no occluder under the scene rule
    f.fss_ao_bake.occluders = 'CUSTOM'
    f.fss_ao_bake.custom.add().object = o2  # 5 m away: F's own cube O6 is not in the list
    refresh()
    assert grade_of('B') == grade_of('F') == 'SURROUNDINGS', (grade_of('B'), grade_of('F'))
    assert store._state['items'][store._state['by_object']['B']]['occluders'] == ['O2']
    select(['B', 'F'])
    assert bpy.ops.fss.ao_bake_start(scope='SELECTED', hidden=True, wait=True) == {'FINISHED'}
    assert grade_of('B') == grade_of('F') == 'UP_TO_DATE'
    b_min, f_min = float(master_image('B')[1].min()), float(master_image('F')[1].min())
    assert b_min < 0.9, b_min
    assert f_min > 0.999, f_min
    print(f"PASS: test_custom_occluders (B with O2, tagged Non-AO-Occluder, in its list: minimum {b_min:.3f} (scene "
          f"rule: 1.0); F with only O2 (5 m away) in its list: minimum {f_min:.3f}, its cube O6 not in the list shades "
          f"nothing)")


def test_option_staleness():
    """Session 25, finish line 5 (decisions 34, 35): pose count, occluder mode and custom list each make the master
    "surroundings changed", and restoring them "up to date"; never "mesh changed"."""
    scene = bpy.context.scene
    b, m, o1 = bpy.data.objects['B'], bpy.data.objects['M'], bpy.data.objects['O1']
    refresh()
    assert grade_of('B') == grade_of('M') == grade_of('A') == 'UP_TO_DATE'
    results = {}

    def check(label, name, expect):
        refresh()
        got = grade_of(name)
        results[label] = got
        assert got == expect, (label, name, got, expect)

    m.fss_ao_bake.poses = 3
    check("M's pose count 3", 'M', 'SURROUNDINGS')
    m.fss_ao_bake.poses = 0
    check("M's pose count back to the scene's", 'M', 'UP_TO_DATE')
    scene.fss_ao_bake.poses = 4
    check("the scene's pose count 4 (M)", 'M', 'SURROUNDINGS')
    check("the scene's pose count 4 (A, not a mover)", 'A', 'UP_TO_DATE')
    scene.fss_ao_bake.poses = 5
    check("the scene's pose count back", 'M', 'UP_TO_DATE')
    a = bpy.data.objects['A']
    a.fss_ao_bake.occluders = 'SELF'
    check("A's occluders Self only", 'A', 'SURROUNDINGS')
    a.fss_ao_bake.occluders = 'SCENE'
    check("A's occluders Scene rule (the default's value)", 'A', 'UP_TO_DATE')
    a.fss_ao_bake.occluders = 'DEFAULT'
    scene.fss_ao_bake.occluders = 'SELF'
    check("the scene's occluders Self only (A)", 'A', 'SURROUNDINGS')
    scene.fss_ao_bake.occluders = 'SCENE'
    check("the scene's occluders back", 'A', 'UP_TO_DATE')
    b.fss_ao_bake.custom.add().object = o1
    check("O1 added to B's list", 'B', 'SURROUNDINGS')
    b.fss_ao_bake.custom.remove(len(b.fss_ao_bake.custom) - 1)
    check("O1 removed", 'B', 'UP_TO_DATE')
    b.fss_ao_bake.occluders = 'SELF'
    check("B's occluders Self only", 'B', 'SURROUNDINGS')
    b.fss_ao_bake.occluders = 'CUSTOM'
    check("B's occluders Custom again", 'B', 'UP_TO_DATE')
    # the operators of the panel's list
    select(['B', 'O1', 'O2'])
    bpy.context.view_layer.objects.active = b
    n = len(b.fss_ao_bake.custom)
    assert bpy.ops.fss.ao_bake_custom_occluders(action='ADD') == {'FINISHED'}
    assert sorted(r.object.name for r in b.fss_ao_bake.custom) == ['O1', 'O2'], [r.object.name for r in b.fss_ao_bake.custom]
    check("Add Selected (O1)", 'B', 'SURROUNDINGS')
    b.fss_ao_bake.custom_index = [r.object.name for r in b.fss_ao_bake.custom].index('O1')
    assert bpy.ops.fss.ao_bake_custom_occluders(action='REMOVE') == {'FINISHED'} and len(b.fss_ao_bake.custom) == n
    check("Remove (O1)", 'B', 'UP_TO_DATE')
    assert bpy.ops.fss.ao_bake_custom_occluders(action='CLEAR') == {'FINISHED'} and not len(b.fss_ao_bake.custom)
    check("Clear", 'B', 'SURROUNDINGS')
    b.fss_ao_bake.custom.add().object = bpy.data.objects['O2']
    check("O2 back", 'B', 'UP_TO_DATE')
    print(f'PASS: test_option_staleness ({results})')


def test_run_mode():
    """Session 25, finish line 7 (decision 36): the bake hidden (and, with FSS_AO_BAKE_TEST_VISIBLE=1, visible) both
    finish; in both the panel's preview updates during a bake of several tiles (read at least twice while it runs); the
    .blend's hash, the datablock counts and is_dirty unchanged by the bake."""
    scene = bpy.context.scene
    modes = ['HIDDEN'] + (['VISIBLE'] if os.environ.get('FSS_AO_BAKE_TEST_VISIBLE') == '1' else [])
    out = {}
    for mode in modes:
        scene.fss_ao_bake.run_mode = mode
        refresh()
        select(['A'])
        before_hash, before_counts, before_dirty = file_hash(BLEND), datablocks(), bpy.data.is_dirty
        res = bpy.ops.fss.ao_bake_start(scope='SELECTED', hidden=False, wait=False, tile=64, test_tile_delay=0.3)
        assert res == {'FINISHED'}
        hidden_args = '-b' in store._run['proc'].args
        assert hidden_args == (mode == 'HIDDEN'), (mode, store._run['proc'].args)
        seen = wait_bake()
        status = store.read_status(str(FOLDER))
        assert status['state'] == 'done' and status['results'][0]['status'] == 'baked', status
        during = sorted({(s[0], s[1]) for s in seen if s[0] is not None})
        assert len(during) >= 2 and len({d for _s, d in during}) >= 2, during
        assert file_hash(BLEND) == before_hash and datablocks() == before_counts and bpy.data.is_dirty == before_dirty
        pv = ao_bake._preview
        assert pv['size'][0] > 0 and ao_bake.preview_icon() is not None
        out[mode] = dict(tiles=status['results'][0]['n_tiles'], preview_states_during=len(during),
                         updates=pv['updates'], size=pv['size'])
    scene.fss_ao_bake.run_mode = 'HIDDEN'
    print(f"PASS: test_run_mode ({out}; .blend hash, datablock counts and is_dirty unchanged"
          + ('' if 'VISIBLE' in out else '; visible not run: FSS_AO_BAKE_TEST_VISIBLE is not 1') + ')')


def test_object_preview():
    """Decision 43: after a bake the panel draws the bake buttons again (the live preview only while it runs); the
    Object box shows the active object's own master: its thumbnail, written with the master, or made from a master
    baked without one; it follows the active object."""
    refresh()
    calls = []
    bpy.types.FSS_PT_ao_bake.draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
    ops = [args[0] for name, args, _kw in calls if name == 'operator']
    # a preview from test_run_mode (icon ids are 0 in a background Blender: the count of updates), the buttons back
    assert ao_bake._preview['updates'] and 'fss.ao_bake_start' in ops, (ao_bake._preview['updates'], ops)
    stem_a = store._state['by_object']['A']
    thumb = FOLDER / (stem_a + core.THUMB_EXT)
    assert thumb.is_file(), thumb  # written by the bake of test_run_mode
    select(['A'])
    ao_bake._thumb_timer()
    first = ao_bake._thumb['mtime']
    assert ao_bake._thumb['icon_ok'] and ao_bake._thumb['name'] == 'A' and ao_bake._thumb['state'] == '', ao_bake._thumb
    thumb.unlink()  # as a master of 0.60.0: made from the master
    ao_bake._thumb_timer()
    assert thumb.is_file() and ao_bake._thumb['icon_ok'], (thumb, ao_bake._thumb)
    grey = core.read_preview(str(FOLDER), stem_a + core.THUMB_EXT)[1]
    others = [n for n, s in store._state['by_object'].items() if s != stem_a and (FOLDER / (s + core.THUMB_EXT)).is_file()]
    if others:
        select([others[0]])
        ao_bake._thumb_timer()
        assert ao_bake._thumb['name'] == others[0] and ao_bake._thumb['stem'] != stem_a
    select([])
    print(f"PASS: test_object_preview (bake buttons drawn after a bake; A's thumbnail {grey.shape[1]} x "
          f"{grey.shape[0]} px from the bake (mtime {first}) and made again from the master; follows the active "
          f"object{' (' + others[0] + ')' if others else ''})")


# ---------------------------------------------------------------------------------------------------------------------
# Movers in poses (Session 25, decision 34): a wheel half sunk in a slab
# ---------------------------------------------------------------------------------------------------------------------

WHEEL_R, WHEEL_T = 0.03, 0.012


def build_wheel_scene():
    """HUB (an empty) turns about X from 0 to 315 degrees over frames 0 to 100 (linear), so 8 poses are 45 degrees
    apart over a full turn; the wheel W (a cylinder about X, radius 3 cm) is its child, centred at the origin, half of
    it inside SLAB (a static box below z = 0); PEG, a small box also a child of HUB, sits on W's +X face at 90 degrees.
    The current frame is 37."""
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    scene = bpy.context.scene
    prefs = bpy.context.preferences.edit
    old_interp = prefs.keyframe_new_interpolation_type
    prefs.keyframe_new_interpolation_type = 'LINEAR'
    hub = link(bpy.data.objects.new('HUB', None))
    scene.frame_set(0)
    hub.rotation_euler = (0.0, 0.0, 0.0)
    hub.keyframe_insert('rotation_euler', index=0, frame=0)
    hub.rotation_euler = (math.radians(315.0), 0.0, 0.0)
    hub.keyframe_insert('rotation_euler', index=0, frame=100)
    prefs.keyframe_new_interpolation_type = old_interp
    act = hub.animation_data.action
    for layer in act.layers:  # linear, so that frames spread evenly give angles spread evenly
        for strip in layer.strips:
            for bag in strip.channelbags:
                for fc in bag.fcurves:
                    for kp in fc.keyframe_points:
                        kp.interpolation = 'LINEAR'
    seg = 48
    verts = []
    for side in (1, -1):
        for k in range(seg):
            a = 2 * math.pi * k / seg
            verts.append((side * WHEEL_T / 2, WHEEL_R * math.cos(a), WHEEL_R * math.sin(a)))
    faces = [tuple(range(seg)), tuple(range(2 * seg - 1, seg - 1, -1))]
    faces += [(k, seg + k, seg + (k + 1) % seg, (k + 1) % seg) for k in range(seg)]
    me = bpy.data.meshes.new('W')
    me.from_pydata(verts, [], faces)
    me.materials.append(material('SET_W', 512))
    uv = me.uv_layers.new(name='UVMap')
    for poly in me.polygons:
        lis = list(poly.loop_indices)
        if poly.index < 2:
            u0 = 0.05 if poly.index == 0 else 0.55
            for li in lis:
                _x, y, z = verts[me.loops[li].vertex_index]
                uv.data[li].uv = (u0 + 0.2 + 0.2 * y / WHEEL_R, 0.25 + 0.2 * z / WHEEL_R)
        else:
            for li in lis:
                vi = me.loops[li].vertex_index
                k = vi % seg
                if k == 0 and poly.index - 2 == seg - 1:
                    k = seg
                uv.data[li].uv = (0.05 + 0.9 * k / seg, 0.6 + (0.06 if vi < seg else 0.0))
    w = link(bpy.data.objects.new('W', me))
    w.parent = hub
    slab = bpy.data.meshes.new('SLAB')
    sv = [(x, y, z) for z in (-0.1, 0.0) for y in (-0.1, 0.1) for x in (-0.05, 0.05)]
    slab.from_pydata(sv, [], [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)])
    link(bpy.data.objects.new('SLAB', slab))
    peg = bpy.data.meshes.new('PEG')
    x0, x1, y0, y1, z0, z1 = WHEEL_T / 2, WHEEL_T / 2 + 0.01, -0.004, 0.004, 0.017, 0.026
    pv = [(x, y, z) for z in (z0, z1) for y in (y0, y1) for x in (x0, x1)]
    peg.from_pydata(pv, [], [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)])
    link(bpy.data.objects.new('PEG', peg)).parent = hub
    angles = []
    for f in (0, 50, 100):
        scene.frame_set(f)
        angles.append(round(math.degrees(hub.rotation_euler.x), 3))
    assert angles == [0.0, 157.5, 315.0], angles
    scene.frame_set(37)
    s = scene.fss_ao_bake
    s.poses, s.samples, s.threads, s.distance = 8, 16, 12, 0.1
    bpy.ops.wm.save_as_mainfile(filepath=str(WORK / 'wheel.blend'))


def sector_profile(name, nsec=16, radius=(0.55, 0.85)):
    """The AO of the object's master per angle sector about its X axis, at radii between radius x WHEEL_R, on its +X
    and -X faces (object space): {side: means (nsec,)}. Samples on a barycentric grid of every master triangle."""
    folder = store.bake_folder()
    stem = store._state['by_object'][name]
    m = core.load_master(folder, stem)
    ev = core.evaluated_triangles(bpy.data.objects[name], bpy.context.evaluated_depsgraph_get(), [])
    co = ev['co'][ev['tris'][m['tri_src']]]  # (T, 3, 3) object space
    k = 8
    g = np.array([(i, j, k - i - j) for i in range(k + 1) for j in range(k + 1 - i)], np.float64) / k
    g = 0.02 / 3 + 0.98 * g  # inside the triangles
    P = np.einsum('sk,tkd->tsd', g, co)
    UV = np.einsum('sk,tkd->tsd', g, m['muv'])
    n = np.cross(co[:, 1] - co[:, 0], co[:, 2] - co[:, 0])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-30)
    ix = np.clip(np.floor(UV[..., 0]).astype(np.int64), 0, m['W'] - 1)
    iy = np.clip(np.floor(UV[..., 1]).astype(np.int64), 0, m['H'] - 1)
    val = m['image'][iy, ix] / 65535.0
    ok = m['filled'][iy, ix]
    r = np.hypot(P[..., 1], P[..., 2])
    ang = np.degrees(np.arctan2(P[..., 2], P[..., 1])) % 360.0
    sec = np.minimum((ang / (360.0 / nsec)).astype(np.int64), nsec - 1)
    out = {}
    for side, sign in (('+X', 1), ('-X', -1)):
        face = (n[:, 0] * sign > 0.95)[:, None] & ok & (r >= radius[0] * WHEEL_R) & (r <= radius[1] * WHEEL_R)
        out[side] = np.array([float(val[face & (sec == q)].mean()) for q in range(nsec)])
    return out


def bake_wheel(label, poses=None, occluders=None, custom=(), watch=False):
    w = bpy.data.objects['W']
    w.fss_ao_bake.poses = poses or 0
    w.fss_ao_bake.occluders = occluders or 'DEFAULT'
    w.fss_ao_bake.custom.clear()
    for n in custom:
        w.fss_ao_bake.custom.add().object = bpy.data.objects[n]
    refresh()
    select(['W'])
    t = time.time()
    res = bpy.ops.fss.ao_bake_start(scope='SELECTED', hidden=True, wait=not watch, tile=512 if watch else 0)
    assert res == {'FINISHED'}
    seen = wait_bake() if watch else []
    status = store.read_status()
    r = status['results'][0]
    assert status['state'] == 'done' and r['status'] == 'baked', status
    assert grade_of('W') == 'UP_TO_DATE'
    prof = sector_profile('W')
    var = {side: float(v.max() - v.min()) for side, v in prof.items()}
    print(f"  {label}: {r.get('n_poses', 1)} pose(s), bake {r['bake_s']} s, second Blender {time.time() - t:.1f} s; "
          f"sector means +X {np.round(prof['+X'], 3).tolist()}, -X {np.round(prof['-X'], 3).tolist()}; "
          f"variation (max - min) {var}")
    return prof, var, r, seen


def test_poses():
    """Session 25, finish line 1 (decision 34): the wheel half sunk in the slab. At 1 pose (the current frame) the AO
    along the ring varies with the angle; at 8 poses over a full turn the variation per angle sector at a fixed radius
    is at most a quarter of the 1-pose variation; Self only shows no slab shadow; the panel shows "Pose p of N". A
    custom list's mover (PEG) is posed with the wheel: its shadow stays at its place on the wheel."""
    build_wheel_scene()
    refresh()
    item = store._state['items'][store._state['by_object']['W']]
    assert item['mover'] and len(item['poses']) == 8 and item['poses'][0] == 0 and item['poses'][-1] == 100, item
    assert item['occluders'] == ['SLAB'], item['occluders']  # PEG and HUB move: no occluders under the scene rule
    p1, v1, r1, _ = bake_wheel('1 pose', poses=1)
    p8, v8, r8, seen = bake_wheel('8 poses', watch=True)
    ps, vs, rs, _ = bake_wheel('Self only (one pose, decision 40)', occluders='SELF')
    assert rs.get('n_poses', 1) == 1, rs  # Self only: nothing moves with it, one pose
    pc, vc, _r, _ = bake_wheel('Custom (SLAB, PEG), 8 poses', occluders='CUSTOM', custom=('SLAB', 'PEG'))
    for side in ('+X', '-X'):
        assert v1[side] > 0.3, v1
        assert v8[side] <= v1[side] / 4, (side, v8[side], v1[side])
        assert ps[side].min() > 0.99 and vs[side] < 0.01, (side, ps[side])
    n_poses_seen = {s[4] for s in seen}
    poses_seen = sorted({s[3] for s in seen if s[4] == 8})
    assert 8 in n_poses_seen and len(poses_seen) >= 2 and max(poses_seen) > 1, (n_poses_seen, poses_seen)
    # PEG on the +X face at 90 degrees: sector 4 of 16 (90 to 112.5) and 3 (67.5 to 90) darker than the same sectors
    # without it (Scene rule: PEG is a mover), and the -X face as without it
    peg_drop = float(p8['+X'][3:5].mean() - pc['+X'][3:5].mean())
    other = float(np.abs(pc['-X'] - p8['-X']).max())
    assert peg_drop > 0.05 and other < 0.05, (peg_drop, other)
    # a mover whose mesh deforms between poses (bent about a static empty while HUB turns it): the current frame only
    anchor = link(bpy.data.objects.new('ANCHOR', None))
    anchor.location = (1.0, 0.0, 0.0)
    bend = plane('BEND', (1.0, 0.0, 0.05), material('SET_W', 512), 15, size=0.1)
    bend.parent = bpy.data.objects['HUB']
    mod = bend.modifiers.new('Bend', 'SIMPLE_DEFORM')
    mod.deform_method, mod.origin, mod.angle = 'BEND', anchor, math.radians(60)
    bpy.ops.wm.save_mainfile()
    refresh()
    assert store._state['items'][store._state['by_object']['BEND']]['poses'], 'BEND has poses'
    select(['BEND'])
    assert bpy.ops.fss.ao_bake_start(scope='SELECTED', hidden=True, wait=True) == {'FINISHED'}
    rb = store.read_status()['results'][0]
    report = bpy.context.window_manager.fss_ao_bake_state.report
    assert rb['status'] == 'baked' and rb['n_poses'] == 1 and 'deforms' in rb.get('note', ''), rb
    assert 'BEND: its mesh deforms between poses' in report, report
    # decision 41 (P59): a full turn (0 to 360 degrees over 0 to 100) is the same pose at both ends: 4 poses at 0, 25,
    # 50, 75; the wheel's 0 to 315 degrees is not: both ends kept
    turn = plane('TURN', (2.0, 0.0, 0.05), material('SET_W', 512), 15, size=0.1)
    turn.rotation_euler = (0.0, 0.0, 0.0)
    turn.keyframe_insert('rotation_euler', index=2, frame=0)
    turn.rotation_euler = (0.0, 0.0, 2 * math.pi)
    turn.keyframe_insert('rotation_euler', index=2, frame=100)
    turn.rotation_euler = (0.0, 0.0, 0.0)
    turn.fss_ao_bake.poses = 4
    refresh()
    full = store._state['items'][store._state['by_object']['TURN']]['poses']
    part = store._state['items'][store._state['by_object']['W']]['poses']
    assert full == [0.0, 25.0, 50.0, 75.0], full
    assert part[0] == 0 and part[-1] == 100 and len(part) == 8, part
    ad = turn.animation_data  # the same turn as an NLA strip (as the cockpit's VS selector)
    act = ad.action
    ad.nla_tracks.new().strips.new('TURN', 0, act)
    ad.action = None
    refresh()
    nla = store._state['items'][store._state['by_object']['TURN']]['poses']
    assert nla == full, nla
    ratio = {side: round(v8[side] / v1[side], 3) for side in v1}
    print(f"PASS: test_poses (variation per sector 1 pose {v1}, 8 poses {v8}: ratio {ratio} (at most 0.25); Self only "
          f"minimum {min(float(ps[s].min()) for s in ps):.4f}; the panel showed poses {poses_seen} of 8; PEG posed "
          f"with the wheel darkens its sectors by {peg_drop:.3f}, the -X face within {other:.3f}; bake 1 pose "
          f"{r1['bake_s']} s, 8 poses {r8['bake_s']} s; a deforming mover baked in the current frame, reported: "
          f"{rb['note']})")


if __name__ == '__main__' and '--' in sys.argv and any(a.startswith('only=') for a in sys.argv):
    # a quicker run of single tests that build their own scene: -- only=test_poses
    t0 = time.time()
    for name in next(a for a in sys.argv if a.startswith('only='))[5:].split(','):
        globals()[name]()
    print(f'SELECTED AO BAKE TESTS PASSED ({time.time() - t0:.1f} s)')
elif __name__ == '__main__':
    t0 = time.time()
    build_scene()
    test_bake_all()
    test_cancel()
    test_tiles()
    test_paged()
    test_formats()
    test_staleness()
    test_apply_orm()
    test_apply_per_object()
    test_apply_separate()
    test_rules_apply()
    test_apply_no_datablock()
    test_draw()
    test_panel_selection()
    test_custom_occluders()
    test_option_staleness()
    test_run_mode()
    test_object_preview()
    test_poses()  # last: it replaces the scene with the wheel's
    print(f'ALL AO BAKE TESTS PASSED ({time.time() - t0:.1f} s)')
