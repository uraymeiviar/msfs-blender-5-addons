"""AO Bake (auto-bake journal, Sessions 15 to 17): masters in a second Blender, their staleness, and Apply.

A synthetic scene of small groups (plane with a cube near it, 1 m apart, AO distance 0.1 m) is saved to
tests/_work/ao_bake_suite/suite.blend and baked through the tool's operators in hidden mode (a second, background
Blender). Checked:
- the second Blender: status.json reaches m of m; Cancel stops after the current object and keeps the finished masters
  (finish line 8);
- the bake in tiles (Session 19): a master in tiles of 64 px has the untiled master's layout, filled pixels and face
  map, and differs by noise only; Cancel between tiles stops within one tile and keeps the object's old master; an
  object's faces without a material are not baked, an object without one is excluded and listed (decision 30);
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
- the panel draws without writing.

To run (the second Blender inherits the CPU cap):
C:\\Users\\uray\\.claude\\tools\\cpucap\\cpucap.exe 50 G:\\e-jets-e2\\tools\\blender\\blender.exe -b --factory-startup
    --python tests/test_ao_bake.py
"""

import hashlib
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


def apply_set(name, objects=None, **kw):
    mat = bpy.data.materials[name]
    rep = ao_bake_apply.apply_set(bpy.context, mat, objects, ApplySettings(**kw))
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
    png, npz = store.master_files(str(FOLDER), stem)
    untiled, _v = master_image('A')
    old = (os.path.getmtime(png), os.path.getmtime(npz), file_hash(png))
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
    assert (os.path.getmtime(png), os.path.getmtime(npz), file_hash(png)) == old
    assert not os.path.exists(png + '.tmp') and not os.path.exists(npz + '.tmp')
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


if __name__ == '__main__':
    t0 = time.time()
    build_scene()
    test_bake_all()
    test_cancel()
    test_tiles()
    test_staleness()
    test_apply_orm()
    test_apply_per_object()
    test_apply_separate()
    test_rules_apply()
    test_apply_no_datablock()
    test_draw()
    print(f'ALL AO BAKE TESTS PASSED ({time.time() - t0:.1f} s)')
