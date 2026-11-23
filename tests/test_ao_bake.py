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
- the masters as JPEG XL (Session 26, decision 37; apply-native-copy decision 6): every master .jxl; a PNG master as
  0.55.2 wrote it and a master of schema 1 are not read: graded missing, white in Apply ("re-bake needed"); a re-bake
  replaces the PNG with a .jxl and removes the PNG;
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
  Non-AO-Occluder darkens nothing; a mover darkens no other object; a shared mesh's copies are baked in their own surroundings (decision 47); faces
  under 4 x counted (finish line 7);
- the panel draws without writing;
- the options of Session 25 (decisions 34 to 36): a Non-AO-Occluder in a custom list shades the target, an object not
  in the list does not (finish line 4); Custom with Scene as occluder off and on and items added or ignored (decision
  60): the occluders of each combination, an older list unchanged, the eyedropper field and the Add/Ignore icon, the
  rows greyed and red, an ignored occluder's contact shadow gone; the Detected list (decision 62): the scene rule's
  occluders kept for every object, filtered by name, ignored from the list and back; the Detected tree (decision 63):
  parent rows, joined for several selected, fold and filter, [+] and [-] on a parent and a child (mixed state), Self
  Only and Scene Rule turned Custom, With its children in the Custom list (an item on a child wins), Add Selected and
  the eyedropper with an empty, the name selecting the object; the oriented boxes (decision 64): a bar turned 45
  degrees whose world box comes within A's AO distance but whose own box does not is no occluder of A, turned
  towards A it is; a sheared object keeps its world box; moving (decision 65): sliding away no occluder, turning
  towards A one; the pose count, occluder mode and custom list each give "surroundings changed"
  and back "up to date" (finish line 5); the run mode Hidden (and Visible with FSS_AO_BAKE_TEST_VISIBLE=1): the bake
  finishes, the panel's progress updates during it and no preview of the master is written (OptiX baker decision 30),
  the .blend, its datablocks and is_dirty unchanged (finish line 7);
  last, a wheel half sunk in a slab (wheel.blend): at 1 pose its AO per angle sector varies, at 8 poses over a full
  turn at most a quarter of that, Self only no slab shadow, a custom list's mover posed with it (finish line 1).
  `-- only=test_poses` runs that test alone;
- Soften Sharp Edges (decision 46) on a master built by hand: the darker side of a convex edge follows the smoothstep
  to the brighter side's value, a concave corner and the brighter side unchanged, a width under a texel raised to one;
  the copy in C++ there as recorded, softened;
- the C++ parts against the values the Python code gave before apply-native-copy decision 6 removed it (recorded in
  tests/data/ao_native_reference.json, tests/ao_native_reference.py), each at 12, 1 and all threads byte-identical:
  Apply's copy (Session 2; every Apply output: grey, ORM layout, another size, the ORM slot, per object, curvature,
  green and blue resampled; Soften Sharp Edges off and on; the master paged, paged with a cache of 2 tiles, and
  whole; the C++ raster, dilation, UV islands and Soften counted, Session 11), the opening (Session 4; every master's page files,
  every Apply output), the PNG writer (Session 7, decision 4: the Python writer's pixels) and reader, and the
  composition with the map writer (bake-post-native journal; every master's files);
- every Refresh and Detected-tree Refresh against the Python scene rule's results, recorded before its geometry moved
  to C++ (bake-post-native journal Session 5; tests/data/ao_scene_rule_reference.json): each item's mesh and
  surroundings hashes, grades, occluders, against and posed lists, the scene-rule lists, the gaps within 1e-9 m;
- decision 6: with fss_ao_copy.dll moved away, and with libjxl's jxl.dll moved away (each put back, md5 checked): the
  panel's first line says why, the AO Bake operators refuse, a job fails with the reason in its log and status, Apply
  refuses.

Last, in a scene of its own (tests/_work/ao_bake_channels), the material channels (decisions 79 to 83, Session 61's
step 2; `-- only=test_material_channels` runs it alone): constant Principled values baked and applied into the slot
textures in place and into separate files, every face pixel within 1/65535 after the sRGB step, an object without a
master and the pixels beyond the padding byte for byte; a textured albedo measured against its source, the samples
measured; a grey material put back leaves it up to date; AO alone with the material changed and after a repack keeps
the channels' and the layout's files byte for byte; a mesh change makes every channel stale and an Albedo bake makes a
new layout without the AO and curvature; the colour before the .Apply AO Group; a shared mesh's copy chosen by the
drop-down, the active object and the first name; a material without a Principled BSDF skipped and reported. Decisions
85 to 87 (Session 65's step 2): a mesh-changed albedo applied and reported; roughness and metal of Target File in their
own grey 16-bit files, the AO's ORM-layout file of the same run as AO alone; a shared mesh's emissive by Average, Most
Lit, Darkest and One Instance.

Then, in a scene of its own (tests/_work/ao_bake_vc; `-- only=test_vertex_color_channels`), the vertex colour sources
(decisions 88 to 92, Session 68's step 2, Session 70's step 2): Overwrite of the AO, roughness, metal and albedo
from FLOAT_COLOR and BYTE_COLOR attributes of point and corner domain equal to the second attribute's values (linear),
never the first's, the file's attributes unchanged; Active Attribute reading the active one; a grey painted at 0.5 in
Vertex Paint giving 0.5 from both types; an object with one colour attribute skipped; Multiply by 1.0, 0.5 and twice
0.5 on a traced, denoised AO; Multiply without a master and after a mesh edit as Overwrite; an Overwrite AO ignoring its surroundings, traced again when the
source is unticked; a denoise-only run keeping the product; an albedo multiplied in linear; an object without a colour
attribute skipped. In the same scene (`-- only=test_custom_value_channels`), the Custom values and colours (decisions
99, 100): each object's own roughness, metal, albedo and emissive by Overwrite, Multiply onto the master (colours in
linear), Multiply without a master as Overwrite; decision 101: the value written straight into the master equal within
1 on every pixel to Cycles' bake of it (FSS_AO_BAKE_CUSTOM_CYCLES), and a bake mixing the two.

Soften at a concave corner with a flat or a 2 um thin triangle along it (`-- only=test_soften_thin_faces`, decision
103): no fold at the flat one, the slopes left out over the thin one's step, every value between the faces'.

In a scene of its own (`-- only=test_shown_without_view`), decision 102: the bake's visibility test ignores a 3D
view's local view and equals Blender's visible_get without a 3D view over random collection and object hide states.

Last, in a scene of its own (tests/_work/ao_bake_fetch; `-- only=test_vertex_color_fetch`), Fetch (decisions 93 to 95,
Session 73's step 2): a vertex colour bake fetched back within one 8-bit step at every corner for ORM, Albedo and Emis;
a traced AO fetched into red alone; FSS_Bake added beside an only attribute, nothing for none; a Mirror modifier
skipped; the Emissive from Vertex Color's Overwrite and Multiply; undo where the background Blender has it.

The baker (OptiX baker journal, decision 22): Cycles, or the one FSS_AO_BAKE_TEST_BAKER names (AUTO, OPTIX), with
FSS OptiX at the suite's 16 samples.

To run (the second Blender inherits the CPU cap):
C:\\Users\\uray\\.claude\\tools\\cpucap\\cpucap.exe 50 G:\\e-jets-e2\\tools\\blender\\blender.exe -b --factory-startup
    --python tests/test_ao_bake.py
"""

import contextlib
import hashlib
import io
import math
import json
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

sys.path.insert(0, str(REPO_ROOT / 'tests'))
from ao_native_reference import Reference  # noqa: E402  (decision 6: the Python code's values, recorded)

REF = Reference('suite')
# bake-post-native journal Session 5: every Refresh and Detected-tree Refresh against the scene rule's results as the
# Python code gave them before its geometry moved to C++ (tests/data/ao_scene_rule_reference.json)
from ao_scene_rule_reference import RuleReference, digest as rule_digest, state_values  # noqa: E402
RULE = RuleReference('suite')


def recorded_padding(fn):
    """The test's reference values were recorded before auto-bake decision 78 (the padding hinged across every edge,
    also sharp folds): it runs with that rule; the rule of decision 78 is checked in test_ao_copy_native.py
    (test_fold_padding)."""
    def run(*args, **kwargs):
        keep, keep_blend = core.PADDING_FOLD_COS, core.APPLY_BLEND
        core.PADDING_FOLD_COS = -2.0
        core.APPLY_BLEND = False  # and before decision 108: only the owner's sub-samples
        try:
            return fn(*args, **kwargs)
        finally:
            core.PADDING_FOLD_COS, core.APPLY_BLEND = keep, keep_blend
    run.__name__ = fn.__name__
    return run
_RULE_CALLS = {}
_store_refresh, _store_detect = store.refresh, store.detect_occluders


def _rule_key(kind):
    """'<test>/<n>/<kind>': the innermost test function on the stack and the call's number in it."""
    f, name = sys._getframe(1), 'top'
    while f is not None:
        if f.f_code.co_name.startswith('test_') or f.f_code.co_name == 'build_scene':
            name = f.f_code.co_name
            break
        f = f.f_back
    _RULE_CALLS[name] = _RULE_CALLS.get(name, 0) + 1
    return f'{name}/{_RULE_CALLS[name]:02d}/{kind}'


_RULE_OFF = [0]  # > 0: Refreshes added after the reference was recorded (no Python values), neither checked nor counted


@contextlib.contextmanager
def rule_unrecorded():
    """Refreshes in this block are not checked against the scene rule reference and take no call number: the checks
    added after decision 6 removed the Python code (AO bake decision 77), whose values were never recorded."""
    _RULE_OFF[0] += 1
    try:
        yield
    finally:
        _RULE_OFF[0] -= 1


def _checked_refresh(context, relink=True, instances=None):
    st = _store_refresh(context, relink, instances)
    if _RULE_OFF[0]:
        return st
    exact, gaps = state_values(st)
    RULE.check(_rule_key('refresh'), rule_digest(exact), gaps, exact)
    return st


def _checked_detect(context, objs):
    done = _store_detect(context, objs)
    exact, gaps = state_values(store._state, done)
    RULE.check(_rule_key('detect'), rule_digest(exact), gaps, exact)
    return done


if __name__ == '__main__':  # this suite's own run (other suites import this module for its scene)
    store.refresh, store.detect_occluders = _checked_refresh, _checked_detect
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


def set_baker(s):
    """OptiX baker decision 22: Cycles, or the baker FSS_AO_BAKE_TEST_BAKER names, FSS OptiX at the Cycles samples."""
    s.baker = os.environ.get('FSS_AO_BAKE_TEST_BAKER', 'CYCLES')
    s.optix_samples = s.samples


def build_scene():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    scene = bpy.context.scene
    scene.frame_set(1)
    s = scene.fss_ao_bake
    s.distance, s.samples, s.threads, s.padding, s.curv_padding = 0.1, 16, 12, PAD, PAD
    set_baker(s)
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


def png_pixels(path):
    """A PNG's values (H, W, C) in file order (the top first), as the reference values of decision 6 hold them (files
    of the Python and the C++ writer have the same pixels, other bytes: apply-native-copy decision 4)."""
    return np.ascontiguousarray(read(path)[0][::-1])


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
    report = bpy.context.window_manager.fss_ao_bake_state.report  # decision 74: one line, no exclusions
    assert report.startswith('done ') and '\n' not in report and 'excluded' not in report, report
    # FL7: darkening
    mins = {n: float(master_image(n)[1].min()) for n in ('A', 'B', 'C', 'D', 'E', 'O1', 'S1', 'M')}
    assert mins['A'] < 0.9 and mins['D'] < 0.9 and mins['E'] < 0.9, mins  # O1, S1/S2, K (skip-bake) darken
    assert mins['B'] > 0.999, mins  # O2 Non-AO-Occluder darkens nothing
    # decision 59: M moves against C, so C is baked in the poses of M's motion with M placed in each, and darkened
    c_item = store._state['items'][store._state['by_object']['C']]
    assert c_item['against'] == ['M'] and c_item['posed'] == ['M'], c_item
    assert len(c_item['poses']) == bpy.context.scene.fss_ao_bake.poses, c_item['poses']
    assert mins['C'] < 0.9, mins
    assert mins['S1'] < 0.9, mins  # decision 47: the shared mesh's copies in their surroundings (plane D under them)
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

        def whole(folder, s, cache_bytes=0, kind='ao', threads=None):
            out = core.load_master(folder, s, kind)
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
    """Session 26 (decision 37) and apply-native-copy decision 6: the masters are JPEG XL. A PNG master as 0.55.2 and
    a bake without libjxl wrote it, and a master of schema 1 (its maps in the .npz), are masters the C++ code does not
    read: Refresh grades them missing (to be baked again), Apply leaves their faces white with the reason 're-bake
    needed'; a re-bake replaces the PNG with a .jxl, removing the PNG, and Apply writes the .jxl's file again."""
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
    a_faces = faces_mask('A', material='SET_A')
    # a master of schema 1 (a copy of A's files, its .npz with the maps): not read, to be baked again
    old_dir = WORK / 'schema1'
    if old_dir.exists():
        shutil.rmtree(old_dir)
    old_dir.mkdir(parents=True)
    _img, mp, npz = core.master_paths(folder, stem)
    shutil.copy2(jpath, old_dir / os.path.basename(jpath))
    shutil.copy2(mp, old_dir / os.path.basename(mp))
    with np.load(npz) as z:
        arrays = {k: z[k] for k in z.files}
    np.savez_compressed(old_dir / os.path.basename(npz), filled=m['filled'], face_map=m['face_map'], **arrays)
    why_s1 = core.master_unreadable(str(old_dir), stem)
    assert why_s1 and why_s1.endswith(core.REBAKE) and 'schema 1' in why_s1, why_s1
    assert not store.has_files(str(old_dir), stem)
    for fn in (core.open_master, core.load_master):
        try:
            fn(str(old_dir), stem)
            raise AssertionError(f'{fn.__name__} read a master of schema 1')
        except core.MasterUnreadable as exc:
            assert str(exc) == why_s1, exc
    shutil.rmtree(old_dir)
    # a PNG master as 0.55.2 wrote it: not read any more (decision 6), graded missing, white in Apply
    core.write_png_int(ppath, img)
    os.remove(jpath)
    index['masters'][stem]['schema'] = 2
    index['masters'][stem].pop('image', None)
    store.write_index(folder, index)
    refresh()
    why_png = core.master_unreadable(folder, stem)
    assert grade_of('A') == 'MISSING' and core.master_paths(folder, stem)[0] == ppath, grade_of('A')
    assert why_png == f'{os.path.basename(ppath)} is a PNG master: {core.REBAKE}', why_png
    old = apply_set('SET_A', file_name='fmt_png_0552.png')
    white = [w for w in old['white'] if w[0] == 'A']
    assert white == [('A', core.REBAKE, white[0][2])] and white[0][2] > 0, old['white']
    line = [x for x in ao_bake_apply.report_lines(old) if 'A (re-bake needed)' in x]
    assert line, ao_bake_apply.report_lines(old)
    vals = read(old['path'])[0][:, :, 0]
    assert a_faces.any() and (vals[a_faces] == 65535).all(), 'A not white'
    assert old['written_px'] < ref['written_px'], (old['written_px'], ref['written_px'])
    for fn in (core.open_master, core.load_master):
        try:
            fn(folder, stem)
            raise AssertionError(f'{fn.__name__} read a PNG master')
        except core.MasterUnreadable as exc:
            assert str(exc) == why_png, exc
    # a re-bake replaces it with a .jxl and removes the PNG; Apply copies A again (test_tiles' master was baked in
    # tiles, this one whole: other noise, the same pixels written)
    select(['A'])
    assert bpy.ops.fss.ao_bake_start(scope='SELECTED', hidden=True, wait=True) == {'FINISHED'}
    assert os.path.isfile(jpath) and not os.path.exists(ppath), os.listdir(folder)
    assert grade_of('A') == 'UP_TO_DATE'
    again = apply_set('SET_A', file_name='fmt_rebaked_jxl.png')
    assert 'A' in again['copied'] and not [w for w in again['white'] if w[0] == 'A'], again
    assert again['written_px'] == ref['written_px'] > 0, (again['written_px'], ref['written_px'])
    left = [f for f in os.listdir(FOLDER) if f.endswith(('.page', '.mappage', '.tmp', '.raw'))]
    assert not left, left
    print(f"PASS: test_formats ({len(jx)} masters .jxl, schema 3; a master of schema 1: \"{why_s1}\", not opened; A as "
          f"a 0.55.2 PNG master: graded missing, Apply white on its {white[0][2]} faces ({line[0].strip()}); a re-bake "
          f"wrote the .jxl and removed the PNG, Apply copied A again ({again['written_px']} px, as before); no scratch "
          f"file left)")


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
    assert not any('Substance' in w for w in rep['warnings'])  # decision 74: never named
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
    path = OUT / 'SET_PO_COMP_RGB16.png'
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
    # decision 106: Strength 0.5 moves every value half way to white (within the rounding), 0.0 writes white
    sc = bpy.context.scene.fss_ao_bake
    strength_err = {}
    try:
        for st in (0.5, 0.0):
            sc.ao_strength = st
            rep = apply_set('SET_A', file_name=f'grey_strength_{st:g}.png')
            gs, _b, _ = read(rep['path'])
            want = 65535.0 - st * (65535.0 - g[:, :, 0].astype(np.float64))
            strength_err[st] = float(np.abs(gs[:, :, 0] - want).max())
            assert strength_err[st] <= 1.0 and rep['strength'] == st, (st, strength_err[st], rep.get('strength'))
            assert any(f'strength {st:g}' in x for x in ao_bake_apply.report_lines(rep)), ao_bake_apply.report_lines(rep)
    finally:
        sc.ao_strength = 1.0
    assert apply_set('SET_A', file_name='grey_strength_1.png').get('strength') is None
    rep = apply_set('SET_ORM', file_name='orm_white.png', layout='ORM', green_blue='WHITE')
    w, _b, _ = read(rep['path'])
    assert (w[:, :, 1:] == 65535).all()
    # decision 98: Custom fills a new file's green and blue with the two values; red as with White
    rep = apply_set('SET_ORM', file_name='orm_custom.png', layout='ORM', green_blue='CUSTOM', orm_roughness=0.25,
                    orm_metal=0.75)
    cu, _b, _ = read(rep['path'])
    assert (cu[:, :, 1] == 16384).all() and (cu[:, :, 2] == 49151).all(), (np.unique(cu[:, :, 1]), np.unique(cu[:, :, 2]))
    assert np.array_equal(cu[:, :, 0], w[:, :, 0]), 'red differs from the White file'
    rep = apply_set('SET_ORM', file_name='orm_custom_default.png', layout='ORM', green_blue='CUSTOM', orm_roughness=1.0,
                    orm_metal=0.0)
    cd, _b, _ = read(rep['path'])
    assert (cd[:, :, 1] == 65535).all() and (cd[:, :, 2] == 0).all()
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
    print(f"PASS: test_apply_separate (greyscale R = G = B; Strength 0.5 and 0 within {strength_err} of the scaled "
          f"values; ORM layout white; copied byte for byte at the same size; "
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
            if name in ('row', 'column', 'box', 'split', 'grid_flow'):
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
        bpy.types.FSS_PT_ao_run.draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)  # decisions 75, 76
        assert props() == before
        ops = [args[0] for name, args, _kw in calls if name == 'operator']
        assert 'fss.ao_bake_refresh' in ops and 'fss.ao_run' in ops, ops
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
    assert ao_bake.pose_mode_items(o, ctx)[0][1] == f'Default ({ctx.scene.fss_ao_bake.poses})'
    names = [i[1] for i in ao_bake.object_occluder_items(o, ctx)]
    assert names[0] == 'Default (Scene Rule)' and o.occluders == 'DEFAULT', (names, o.occluders)
    # the set list: "n missing" and "n stale" are buttons that select those objects of the set
    r = st.sets[0]
    keep = (r.n_missing, r.n_stale)
    for nm, ns, want in ((0, 0, []), (2, 0, ['MISSING']), (0, 3, ['STALE']), (2, 3, ['MISSING', 'STALE'])):
        r.n_missing, r.n_stale = nm, ns
        calls = []
        ao_bake.FSS_UL_AOSets.draw_item(None, ctx, _Layout(calls), st, r, 0, st, 'active_set', 0)
        ops = [kw.get('text') for name, args, kw in calls if name == 'operator']
        assert len(ops) == len(want) and all(w.lower() in t for w, t in zip(want, ops)), (nm, ns, ops)
    r.n_missing, r.n_stale = keep
    items = store._state['items']
    stem = next(iter(store._state['sets'][r.material]['items']))
    grade = items[stem]['grade']
    items[stem]['grade'] = 'MISSING'  # one master of the set missing, as after a deleted file
    try:
        assert bpy.ops.fss.ao_bake_select(which='MISSING', material=r.material) == {'FINISHED'}
        got = {o.name for o in ctx.selected_objects}
        want = {n for st_ in store._state['sets'][r.material]['items'] if items[st_]['grade'] == 'MISSING'
                for n in items[st_]['users']}
        assert got == want and got, (got, want)
        assert bpy.ops.fss.ao_bake_select(which='STALE', material=r.material) == {'FINISHED'}
        assert not ctx.selected_objects or all(
            items[store._state['by_object'][o.name]]['grade'] in ('MESH', 'SURROUNDINGS') for o in ctx.selected_objects)
    finally:
        items[stem]['grade'] = grade
    select([])
    print(f"PASS: test_panel_selection (A selected: {sorted(sel)} of {len(st.sets)} sets shown; Apply into a missing "
          f"ORM texture refused: {refused!r}; own poses on and off; occluder choices {names})")


def test_apply_steps():
    """Decision 45: Apply in steps gives the file of Apply in one go; its steps report progress; closed early (Cancel)
    it leaves the file as it was and no .tmp."""
    refresh()
    ctx = bpy.context
    mat = bpy.data.materials['SET_A']
    a = mat.fss_ao_apply
    old = (a.target, a.file_name)
    a.target, a.file_name = 'FILE', 'steps.png'
    rep = ao_bake_apply.apply(ctx, [mat])[0]
    path = rep['path']
    one_go = file_hash(path)
    gen = ao_bake_apply.apply_steps(ctx, [mat])
    steps = []
    while True:
        try:
            steps.append(next(gen))
        except StopIteration as stop:
            reports = stop.value
            break
    assert file_hash(path) == one_go and not reports[0].get('error'), reports
    fracs = [s[3] for s in steps]
    assert len(steps) > 3 and fracs[-1] >= 0.9 and any(s[4].startswith('Writing') for s in steps), steps[:5]
    os.utime(path, (1, 1))
    gen = ao_bake_apply.apply_steps(ctx, [mat])
    for _ in range(len(steps) // 2):
        next(gen)
    gen.close()  # Cancel in the middle
    left = [f for f in os.listdir(os.path.dirname(path)) if f.endswith('.tmp')]
    assert file_hash(path) == one_go and os.path.getmtime(path) == 1 and not left, left
    a.target, a.file_name = old
    print(f"PASS: test_apply_steps ({len(steps)} steps, the file equal to Apply in one go; cancelled after "
          f"{len(steps) // 2}: the file untouched, no .tmp)")


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


def test_apply_ticked():
    """Apply Selected writes only the texture sets ticked in the list (each material's fss_ao_apply.use, ticked by
    default); none ticked: refused."""
    refresh()
    ctx = bpy.context
    # File shows the set's default name in the box; stored empty it follows the material's name
    fa = bpy.data.materials['SET_A'].fss_ao_apply
    raw = fa.get('file_name', '')
    fa['file_name'] = ''
    assert fa.file_name == 'SET_A_COMP_RGB16.png', fa.file_name
    fa.file_name = 'own.png'
    assert fa.file_name == 'own.png' and fa['file_name'] == 'own.png'
    fa.file_name = 'SET_A_COMP_RGB16.png'
    assert fa['file_name'] == ''
    fa.file_name = ''
    assert fa.file_name == 'SET_A_COMP_RGB16.png' and fa['file_name'] == ''
    fa['file_name'] = raw
    items, rows = store._state['items'], store._state['sets']
    pick = [items[rows[n]['items'][0]]['users'][0] for n in ('SET_A', 'SET_B')]  # an object of each
    select(pick)
    sets = sorted({n for stem in store.items_for_objects(ctx.selected_objects) for n in items[stem]['sets']})
    assert len(sets) >= 2, (pick, sets)
    mats = [bpy.data.materials[n] for n in sets]
    assert all(m.fss_ao_apply.use for m in mats)
    mats[0].fss_ao_apply.use = False
    st = ctx.window_manager.fss_ao_bake_state
    console = io.StringIO()  # decision 74: the whole report in the console, the panel only what failed
    with contextlib.redirect_stdout(console):
        assert bpy.ops.fss.ao_apply(scope='SELECTED') == {'FINISHED'}
    done = {line[len('AO Apply: '):].split(':')[0] for line in console.getvalue().splitlines()
            if line.startswith('AO Apply: ') and not line[len('AO Apply: '):].startswith(' ')}
    assert not st.apply_report, st.apply_report
    assert sets[0] not in done and set(sets[1:]) <= done, (sets, done)
    for m in mats:
        m.fss_ao_apply.use = False
    assert bpy.ops.fss.ao_apply(scope='SELECTED') == {'CANCELLED'}
    assert ao_bake.apply_check(ctx) == ([], [])
    for m in mats:
        m.fss_ao_apply.use = True
    # a ticked set whose target cannot be written (ORM without a texture): the button off, the operator refuses
    a = bpy.data.materials['SET_A'].fss_ao_apply
    old_target = a.target
    a.target = 'ORM'
    assert ao_bake.apply_mod.orm_image(bpy.data.materials['SET_A']) is None
    ticked, blocked = ao_bake.apply_check(ctx)
    assert 'SET_A' in ticked and [b[0] for b in blocked] == ['SET_A'], (ticked, blocked)
    try:
        refused = bpy.ops.fss.ao_apply(scope='SELECTED')
    except RuntimeError as e:  # an operator's ERROR report raises in a script
        refused = str(e)
    assert refused == {'CANCELLED'} or 'SET_A: No texture in the ORM slot' in str(refused), refused
    a.target = old_target
    assert ao_bake.apply_check(ctx)[1] == []
    print(f'PASS: test_apply_ticked (File shows SET_A_COMP_RGB16.png when empty; {sets[0]} unticked: not written, {sets[1:]} written; none ticked: refused; '
          f'a ticked set without its ORM texture: {blocked[0][1]!r}, refused)')


def wait_bake(poll=0.1, limit=300):
    """While the second Blender runs: the panel's progress timer step by step (a background Blender runs no timers);
    returns the states seen: (tile, pose, n_poses, progress)."""
    proc = store._run['proc']
    seen = []
    t = time.time()
    while proc.poll() is None and time.time() - t < limit:
        ao_bake._poll_timer()
        st = bpy.context.window_manager.fss_ao_bake_state
        seen.append((st.tile, st.pose, st.n_poses, round(st.progress, 4)))
        time.sleep(poll)
    proc.wait(timeout=60)
    ao_bake._poll_timer()  # the last step: the bake ended, finish_bake runs
    return seen


def test_shown_without_view():
    """Decision 102: the bake's visibility (store.shown) ignores a 3D view's local view; it equals Blender's visible_get
    without a 3D view (as in this background Blender) in a scene of its own, over random states of a collection tree
    (excluded, hidden in viewports, hidden in the view layer), the objects' own hide_viewport and hide_set, and an
    object linked into two collections and the scene collection. The local view itself is not tested (no 3D view in
    a background Blender); shown() reads no view."""
    import random
    t0 = time.time()
    sc = bpy.data.scenes.new('FSS_SHOWN_TEST')
    vl = sc.view_layers[0]
    mesh = bpy.data.meshes.new('FSS_SHOWN_MESH')
    colls, objs = {}, []
    try:
        def coll(name, parent):
            c = bpy.data.collections.new(name)
            parent.children.link(c)
            colls[name] = c
            return c
        a = coll('FSS_SH_A', sc.collection)
        b = coll('FSS_SH_B', a)
        c = coll('FSS_SH_C', b)
        d = coll('FSS_SH_D', sc.collection)
        for k, homes in enumerate(([a], [b], [c], [d], [b, d], [sc.collection], [c, sc.collection])):
            o = bpy.data.objects.new(f'FSS_SH_O{k}', mesh)
            for h in homes:
                h.objects.link(o)
            objs.append(o)
        vl.update()  # a new scene's layer collections exist after its first update

        def lcs(lc):
            yield lc
            for ch in lc.children:
                yield from lcs(ch)
        rng = random.Random(102)
        counts = dict(states=0, shown=0, hidden=0)
        for _state in range(400):
            for lc in list(lcs(vl.layer_collection))[1:]:
                lc.exclude = rng.random() < 0.15
                if not lc.exclude:
                    lc.hide_viewport = rng.random() < 0.25
            for cc in colls.values():
                cc.hide_viewport = rng.random() < 0.15
            for o in objs:
                o.hide_viewport = rng.random() < 0.1
                if o.name in vl.objects:
                    o.hide_set(rng.random() < 0.15, view_layer=vl)
            names = store.shown_names(vl)
            for o in objs:
                want = o.name in vl.objects and o.visible_get(view_layer=vl)
                got = store.shown(o, vl, names)
                tree = [(lc.name, lc.exclude, lc.hide_viewport, lc.collection.hide_viewport)
                        for lc in lcs(vl.layer_collection)]
                assert got == want, (o.name, got, want, tree, o.hide_viewport,
                                     o.name in vl.objects and o.hide_get(view_layer=vl))
                counts['shown' if got else 'hidden'] += 1
            counts['states'] += 1
    finally:
        for o in objs:
            bpy.data.objects.remove(o)
        bpy.data.meshes.remove(mesh)
        for cc in colls.values():
            bpy.data.collections.remove(cc)
        bpy.data.scenes.remove(sc)
    print(f'PASS: test_shown_without_view ({time.time() - t0:.1f} s; {counts})')
    return counts


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


def test_custom_add_ignore():
    """Decision 60: Custom with Scene as occluder off or on and items added or ignored gives the expected occluders;
    a list without the new settings keeps its occluders and master; the eyedropper field adds without selecting; the
    icon switches Add and Ignore; the rows draw without writing; an ignored occluder's contact shadow is gone."""
    def occluders(name):
        return store._state['items'][store._state['by_object'][name]]['occluders']
    a, b, o1, o2, z = (bpy.data.objects[n] for n in ('A', 'B', 'O1', 'O2', 'Z'))
    refresh()
    rule = occluders('A')  # the scene rule's occluders of A (Default: Scene Rule)
    assert 'O1' in rule and grade_of('A') == 'UP_TO_DATE', (rule, grade_of('A'))
    assert float(master_image('A')[1].min()) < 0.9  # O1's contact shadow
    # B's list from test_custom_occluders, saved without the new settings: the same occluders, still up to date
    assert not b.fss_ao_bake.custom_scene and not any(r.ignore for r in b.fss_ao_bake.custom)
    assert occluders('B') == ['O2'] and grade_of('B') == 'UP_TO_DATE', (occluders('B'), grade_of('B'))
    s = a.fss_ao_bake
    s.occluders = 'CUSTOM'
    results = {}

    def case(label, scene_on, items, expect):
        s.custom_scene = scene_on
        s.custom.clear()
        for name, ignore in items:
            ref = s.custom.add()
            ref.object, ref.ignore = bpy.data.objects[name], ignore
        refresh()
        got = occluders('A')
        results[label] = got
        assert got == sorted(expect), (label, got, sorted(expect))
    case('scene off, empty', False, [], [])
    case('scene off, O1 and Z added', False, [('O1', False), ('Z', False)], ['O1', 'Z'])
    case('scene off, O1 ignored', False, [('O1', True)], [])
    case('scene on, empty', True, [], rule)
    case('scene on, O1 ignored', True, [('O1', True)], [n for n in rule if n != 'O1'])
    case('scene on, O2 (Non-AO-Occluder) added', True, [('O2', False)], sorted(set(rule) | {'O2'}))
    case('scene on, O1 added (already in the rule)', True, [('O1', False)], rule)
    assert store._state['scene_rule']['A'] == rule
    # the rows: Ignore red; greyed: Ignore with the scene off, Add with the scene on for an object the rule includes
    s.custom.clear()
    for name, ignore in (('O1', False), ('O2', False), ('Z', True)):
        ref = s.custom.add()
        ref.object, ref.ignore = bpy.data.objects[name], ignore
    drawn = {}
    for scene_on in (True, False):
        s.custom_scene = scene_on
        for i, ref in enumerate(s.custom):
            calls = []
            row_holder = _Layout(calls)
            row = row_holder.row()
            row_holder.row = lambda **kw: row
            snap = [(r.object.name, r.ignore) for r in s.custom], s.custom_scene, s.custom_index
            ao_bake.FSS_UL_AOOccluders.draw_item(None, bpy.context, row_holder, s, ref, 0, s, 'custom_index', i)
            assert ([(r.object.name, r.ignore) for r in s.custom], s.custom_scene, s.custom_index) == snap
            drawn[(scene_on, ref.object.name)] = (row.active, row.alert)
    assert drawn == {(True, 'O1'): (False, False), (True, 'O2'): (True, False), (True, 'Z'): (True, True),
                     (False, 'O1'): (True, False), (False, 'O2'): (True, False), (False, 'Z'): (False, True)}, drawn
    # the icon (TOGGLE) and the eyedropper field
    bpy.context.view_layer.objects.active = a
    assert bpy.ops.fss.ao_bake_custom_occluders(action='TOGGLE', index=0) == {'FINISHED'} and s.custom[0].ignore
    assert bpy.ops.fss.ao_bake_custom_occluders(action='TOGGLE', index=0) == {'FINISHED'} and not s.custom[0].ignore
    s.custom.clear()
    selected = [o.name for o in bpy.context.selected_objects]
    s.pick = o1
    s.pick = o1  # not twice
    s.pick = a  # not the object itself
    assert [r.object.name for r in s.custom] == ['O1'] and s.pick is None, [r.object.name for r in s.custom]
    assert [o.name for o in bpy.context.selected_objects] == selected
    # the bake: scene on, O1 ignored: A's contact shadow from O1 is gone
    s.custom[0].ignore = True
    s.custom_scene = True
    refresh()
    assert grade_of('A') == 'SURROUNDINGS'
    select(['A'])
    assert bpy.ops.fss.ao_bake_start(scope='SELECTED', hidden=True, wait=True) == {'FINISHED'}
    ignored_min = float(master_image('A')[1].min())
    assert ignored_min > 0.99, ignored_min
    # back to the default, baked again for the tests after this one
    s.custom.clear()
    s.custom_scene = False
    s.occluders = 'DEFAULT'
    refresh()
    select(['A'])
    assert bpy.ops.fss.ao_bake_start(scope='SELECTED', hidden=True, wait=True) == {'FINISHED'}
    assert grade_of('A') == 'UP_TO_DATE' and float(master_image('A')[1].min()) < 0.9
    print(f"PASS: test_custom_add_ignore (scene rule of A {rule}; {results}; rows (active, red) {drawn}; A with "
          f"O1 ignored: minimum {ignored_min:.3f}, its contact shadow gone)")


def _shown(filter_name=''):
    """The Detected tree's rows, in their order (filter_items)."""
    flag = 1 << 30  # UIList.bitflag_filter_item (an instance attribute)
    objects = bpy.context.scene.objects
    flags, order = ao_bake.FSS_UL_AODetected.filter_items(
        SimpleNamespace(bitflag_filter_item=flag, filter_name=filter_name), bpy.context, bpy.context.scene, 'objects')
    return [o.name for o, _f, _k in sorted(((o, f, k) for o, f, k in zip(objects, flags, order) if f & flag),
                                           key=lambda x: x[2])]


def _tree_row(name, filter_name=''):
    """The Detected tree's row: ([+] lit, [-] lit, the operators' names), drawn without writing."""
    calls = []
    holder = _Layout(calls)
    snap = [(o.name, o.fss_ao_bake.occluders, o.fss_ao_bake.custom_scene,
             [(r.object.name, r.ignore, r.children) for r in o.fss_ao_bake.custom]) for o in bpy.data.objects]
    ao_bake.FSS_UL_AODetected.draw_item(SimpleNamespace(filter_name=filter_name), bpy.context, holder,
                                        bpy.context.scene, bpy.data.objects[name], 0, None, '', 0)
    assert snap == [(o.name, o.fss_ao_bake.occluders, o.fss_ao_bake.custom_scene,
                     [(r.object.name, r.ignore, r.children) for r in o.fss_ao_bake.custom]) for o in bpy.data.objects]
    sets = [kw.get('depress', False) for n, a, kw in calls if n == 'operator' and a[0] == 'fss.ao_bake_tree_set']
    ops = [a[0] for n, a, _kw in calls if n == 'operator']
    texts = [kw.get('text') for n, a, kw in calls if n == 'label' and kw.get('text')]
    return tuple(sets), ops, texts


def test_detected():
    """Decisions 62 and 63: every baked object's scene-rule occluders are kept at Refresh, also under Self Only; the
    Detected tree shows them (filtered by name too); [-] ignores one (Scene Rule becomes Custom with Scene as occluder)
    and [+] takes it back; the rows draw without writing."""
    a = bpy.data.objects['A']
    s = a.fss_ao_bake
    select(['A'])
    refresh()
    rule = store._state['scene_rule']['A']
    assert rule == store._state['items'][store._state['by_object']['A']]['occluders'] == ['O1'], rule
    s.occluders = 'SELF'
    refresh()
    assert store._state['scene_rule']['A'] == ['O1'] and store._state['items'][store._state['by_object']['A']]['occluders'] == []
    s.occluders = 'DEFAULT'
    refresh()
    assert _shown() == ['O1'] and _shown('o1') == ['O1'] and _shown('Z') == [], (_shown(), _shown('Z'))
    before = _tree_row('O1')[0]
    assert before == (True, False), before
    assert bpy.ops.fss.ao_bake_tree_set(name='O1', on=False) == {'FINISHED'}
    assert s.occluders == 'CUSTOM' and s.custom_scene and [(r.object.name, r.ignore) for r in s.custom] == [('O1', True)]
    refresh()
    assert store._state['items'][store._state['by_object']['A']]['occluders'] == [] and grade_of('A') == 'SURROUNDINGS'
    ignored = _tree_row('O1')[0]
    assert ignored == (False, True), ignored
    assert bpy.ops.fss.ao_bake_tree_set(name='O1', on=False) == {'CANCELLED'}  # already so: nothing to change
    assert bpy.ops.fss.ao_bake_tree_set(name='O1', on=True) == {'FINISHED'} and not len(s.custom)
    refresh()
    assert store._state['items'][store._state['by_object']['A']]['occluders'] == ['O1']
    s.custom_scene = False
    off = _tree_row('O1')[0]
    assert off == (False, True), off
    s.occluders, s.custom_scene = 'DEFAULT', False
    refresh()
    assert grade_of('A') == 'UP_TO_DATE', grade_of('A')
    print(f"PASS: test_detected (A's scene rule {rule}, also kept under Self Only; the tree shows {_shown()}, 'Z' "
          f"filters it to none; O1's row ([+], [-]) {before}, ignored {ignored} with A turned Custom and Scene as "
          f"occluder, [+] takes it back; without the scene {off})")


def test_tree():
    """Decision 63: the Detected tree with a parent (empty TP over O1, detected for A, and S1, detected for D), joined
    for A and D selected: its rows, counts, fold and filter; [-] on TP ignores the branch for both; [+] on O1 then
    adds it back for A alone (TP mixed); [+] on TP clears the branch's items; Self Only becomes Custom on [+]; the
    Custom list's With its children (an item on a child wins); Add Selected and the eyedropper with the empty; the
    name selects the object. Parenting keeps every master up to date."""
    a, d, o1, s1 = (bpy.data.objects[n] for n in ('A', 'D', 'O1', 'S1'))
    sa, sd = a.fss_ao_bake, d.fss_ao_bake
    refresh()
    rule_a, rule_d = list(store._state['scene_rule']['A']), list(store._state['scene_rule']['D'])
    assert rule_a == ['O1'] and {'S1', 'S2'} <= set(rule_d) and 'O1' not in rule_d, (rule_a, rule_d)
    occ_d = store._state['items'][store._state['by_object']['D']]['occluders']
    tp = bpy.data.objects.new('TP', None)
    bpy.context.scene.collection.objects.link(tp)
    worlds = [o.matrix_world.copy() for o in (o1, s1)]
    for o in (o1, s1):
        o.parent = tp
    bpy.context.view_layer.update()
    assert [o.matrix_world for o in (o1, s1)] == worlds
    refresh()
    assert grade_of('A') == grade_of('D') == 'UP_TO_DATE', (grade_of('A'), grade_of('D'))
    ao_bake._tree_open.clear()
    select(['A', 'D'])
    tree = ao_bake.detected_tree(bpy.context)
    rest = sorted(set(rule_d) - {'S1'})
    assert tree['targets'] == ['A', 'D'] and tree['children'] == {'TP': ['O1', 'S1']}, tree
    assert tree['roots'] == sorted(rest + ['TP']) and sorted(tree['members']['TP']) == ['O1', 'S1'], tree
    assert tree['count']['TP'] == 2 and tree['count']['O1'] == 1 and tree['depth']['O1'] == 1, tree
    # decision 70: each detected object's gap, a parent row's the smallest in its branch; the flat view
    gap_a, gap_d = store._state['scene_gap']['A'], store._state['scene_gap']['D']
    assert set(gap_a) == set(rule_a) and set(gap_d) == set(rule_d), (gap_a, gap_d)
    assert tree['gap']['TP'] == min(tree['own_gap']['O1'], tree['own_gap']['S1']), tree
    st = bpy.context.window_manager.fss_ao_bake_state
    st.detected_view = 'FLAT'
    flat = _shown()
    assert flat == sorted(set(rule_a) | set(rule_d)), flat  # by name
    st.detected_sort = 'DISTANCE'  # decision 71
    flat = _shown()
    assert [tree['own_gap'][n] for n in flat] == sorted(tree['own_gap'][n] for n in flat), flat
    st.detected_view, st.detected_sort = 'TREE', 'NAME'
    # an empty over one object only is no row; over two it is
    tq = bpy.data.objects.new('TQ', None)
    bpy.context.scene.collection.objects.link(tq)
    s2 = bpy.data.objects['S2']
    s2_world = s2.matrix_world.copy()
    s2.parent = tq
    s2.matrix_parent_inverse = tq.matrix_world.inverted()
    bpy.context.view_layer.update()
    ao_bake._tree_cache.update(key=None)
    tree_q = ao_bake.detected_tree(bpy.context)
    assert 'TQ' not in tree_q['members'] and 'S2' in tree_q['roots'], tree_q['roots']
    s2.parent = None
    s2.matrix_world = s2_world
    bpy.data.objects.remove(tq)
    bpy.context.view_layer.update()
    ao_bake._tree_cache.update(key=None)
    folded = _shown()
    assert folded == sorted(rest + ['TP']), folded
    assert bpy.ops.fss.ao_bake_tree_fold(name='TP') == {'FINISHED'}
    unfolded = _shown()
    assert unfolded[unfolded.index('TP'):unfolded.index('TP') + 3] == ['TP', 'O1', 'S1'], unfolded
    assert bpy.ops.fss.ao_bake_tree_fold(name='TP') == {'FINISHED'} and _shown() == folded
    assert _shown('s1') == ['TP', 'S1'], _shown('s1')  # the filter opens the branch
    lit, ops, texts = _tree_row('TP')
    assert lit == (True, False) and ops == ['fss.ao_bake_tree_set'] * 2 + [
        'fss.ao_bake_tree_highlight', 'fss.ao_bake_tree_select', 'fss.ao_bake_tree_fold'], (lit, ops)
    # the name a label (a click highlights the row), the distance column (decision 70), the count of targets
    assert len(texts) == 3 and texts[0] == 'TP  (2)' and texts[1].endswith(' mm') and texts[2] == '2/2', texts
    # [-] on the parent: both turn Custom with Scene as occluder and ignore TP with its children
    assert bpy.ops.fss.ao_bake_tree_set(name='TP', on=False) == {'FINISHED'}
    for st in (sa, sd):
        assert st.occluders == 'CUSTOM' and st.custom_scene, (st.occluders, st.custom_scene)
        assert [(r.object.name, r.ignore, r.children) for r in st.custom] == [('TP', True, True)]
    refresh()
    occ = {n: store._state['items'][store._state['by_object'][n]]['occluders'] for n in ('A', 'D')}
    assert occ == {'A': [], 'D': [n for n in occ_d if n != 'S1']}, occ
    assert _tree_row('TP')[0] == (False, True) and _tree_row('S2')[0] == (True, False)
    # [+] on the child O1: added back for A alone (D does not detect it); TP is mixed
    assert bpy.ops.fss.ao_bake_tree_set(name='O1', on=True) == {'FINISHED'}
    assert [(r.object.name, r.ignore, r.children) for r in sa.custom] == [('TP', True, True), ('O1', False, False)]
    assert [(r.object.name, r.ignore) for r in sd.custom] == [('TP', True)]
    refresh()
    assert store._state['items'][store._state['by_object']['A']]['occluders'] == ['O1']
    mixed = _tree_row('TP')[0]
    assert mixed == (False, False) and _tree_row('O1')[0] == (True, False), mixed
    # [+] on the parent: the branch's items go, the scene rule decides again
    assert bpy.ops.fss.ao_bake_tree_set(name='TP', on=True) == {'FINISHED'} and not len(sa.custom) and not len(sd.custom)
    refresh()
    assert store._state['items'][store._state['by_object']['D']]['occluders'] == occ_d
    # Self Only: [+] makes it Custom without the scene, with the object added
    select(['D'])
    sd.occluders = 'SELF'
    assert bpy.ops.fss.ao_bake_tree_set(name='S2', on=True) == {'FINISHED'}
    assert sd.occluders == 'CUSTOM' and not sd.custom_scene and [r.object.name for r in sd.custom] == ['S2']
    refresh()
    assert store._state['items'][store._state['by_object']['D']]['occluders'] == ['S2']
    # the Custom list: TP added with its children (scene off) adds O1 and S1 wherever they are; an item on S1 wins
    select(['A'])
    sa.occluders, sa.custom_scene = 'CUSTOM', False
    sa.pick = tp  # an empty: added with With its children on
    assert [(r.object.name, r.ignore, r.children) for r in sa.custom] == [('TP', False, True)]
    refresh()
    with_children = store._state['items'][store._state['by_object']['A']]['occluders']
    assert with_children == ['O1', 'S1'], with_children
    assert bpy.ops.fss.ao_bake_custom_occluders(action='CHILDREN', index=0) == {'FINISHED'} and not sa.custom[0].children
    refresh()
    assert store._state['items'][store._state['by_object']['A']]['occluders'] == []  # the empty alone darkens nothing
    sa.custom[0].children = True
    ref = sa.custom.add()
    ref.object, ref.ignore = s1, True
    refresh()
    child_wins = store._state['items'][store._state['by_object']['A']]['occluders']
    assert child_wins == ['O1'], child_wins
    sa.custom.clear()
    select(['A', 'TP'])
    bpy.context.view_layer.objects.active = a
    assert bpy.ops.fss.ao_bake_custom_occluders(action='ADD') == {'FINISHED'}
    assert [(r.object.name, r.children) for r in sa.custom] == [('TP', True)]
    # the select button: the object alone (no children) made active; with children, they too (decision 69)
    assert bpy.ops.fss.ao_bake_tree_select(name='S2') == {'FINISHED'}
    assert [o.name for o in bpy.context.selected_objects] == ['S2'] and bpy.context.view_layer.objects.active.name == 'S2'
    assert bpy.ops.fss.ao_bake_tree_select(name='TP') == {'FINISHED'}
    assert sorted(o.name for o in bpy.context.selected_objects) == ['O1', 'S1', 'TP']
    assert bpy.context.view_layer.objects.active.name == 'TP'
    assert bpy.ops.fss.ao_bake_tree_highlight(name='TP') == {'FINISHED'} and ao_bake._highlight['names'] == {'TP'}
    assert bpy.ops.fss.ao_bake_tree_highlight(name='TP') == {'FINISHED'} and not ao_bake._highlight['names']
    # back as before
    for st in (sa, sd):
        st.custom.clear()
        st.occluders, st.custom_scene = 'DEFAULT', False
    for o in (o1, s1):
        o.parent = None
    bpy.data.objects.remove(tp)
    bpy.context.view_layer.update()
    assert [o.matrix_world for o in (o1, s1)] == worlds
    ao_bake._tree_open.clear()
    refresh()
    assert grade_of('A') == grade_of('D') == 'UP_TO_DATE', (grade_of('A'), grade_of('D'))
    print(f"PASS: test_tree (A and D joined: rows {folded}, unfolded {unfolded}; [-] on TP: A {occ['A']}, D "
          f"{occ['D']}; [+] on O1: TP mixed {mixed}; Self Only + [+] S2: D ['S2']; TP with its children "
          f"{with_children}, S1 ignored on its own {child_wins})")


def own_box(obj):
    """The object's world box (lo, hi) and own box (centre, unit axes as columns, half sizes, ok: its axes square) at
    the current frame, from its bound_box and matrix_world (the own box by the DLL, as the scene rule makes it)."""
    c = np.array([tuple(v) for v in obj.bound_box], dtype=np.float64)
    M = np.array(obj.matrix_world, dtype=np.float64)
    w = c @ M[:3, :3].T + M[:3, 3]
    return (w.min(axis=0), w.max(axis=0)), core.native_copy().own_boxes(c.min(axis=0), c.max(axis=0), M,
                                                                          store.ORTHO_TOL)


def test_oriented_rule():
    """Decision 64: a bar (0.8 m x 2 cm) turned 45 degrees beside A: its world box comes within A's AO distance
    (0.1 m) but its own box does not, so it is no occluder of A and A's master stays up to date; turned towards A it
    becomes one (surroundings changed), back again up to date. The gap of two aligned boxes is their world boxes'; a
    child of a parent scaled unevenly and turned has no own box (a shear) and keeps its world box. Decision 65: the
    bar moving, its own box at each sampled frame: sliding away from A (its swept world box within the distance) no
    occluder, turning towards A one."""
    a = bpy.data.objects['A']
    refresh()
    rule = list(store._state['scene_rule']['A'])
    distance = store.item_distance(a, bpy.context.scene)
    h, w = 0.4, 0.01
    me = bpy.data.meshes.new('MESH_BAR')
    me.from_pydata([(x, y, z) for x in (-h, h) for y in (-w, w) for z in (-w, w)], [],
                   [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)])
    bar = bpy.data.objects.new('BAR', me)
    bpy.context.scene.collection.objects.link(bar)
    bar.location = (-0.4, 0.4, 0.0)
    bar.rotation_euler = (0.0, 0.0, math.radians(45))  # along (1, 1): its side faces A, 0.4 m away
    bpy.context.view_layer.update()
    (wa, oa), (wb, ob) = own_box(a), own_box(bar)
    world_gap = float(np.max(np.maximum(np.maximum(wa[0] - wb[1], wb[0] - wa[1]), 0.0)))
    own_gap = float(core.native_copy().box_gaps(oa[:3], *(np.array([x]) for x in ob[:3]))[0])
    assert world_gap <= distance < own_gap, (world_gap, distance, own_gap)
    refresh()
    beside = list(store._state['scene_rule']['A'])
    assert beside == rule and grade_of('A') == 'UP_TO_DATE', (beside, grade_of('A'))
    bar.rotation_euler = (0.0, 0.0, math.radians(-45))  # along (1, -1): its end 2 cm from A's corner
    bpy.context.view_layer.update()
    refresh()
    towards = list(store._state['scene_rule']['A'])
    assert 'BAR' in towards and grade_of('A') == 'SURROUNDINGS', (towards, grade_of('A'))
    # aligned boxes: the world boxes' gap; a shear: no own box
    box = (np.zeros(3), np.eye(3), np.ones(3))
    aligned = float(core.native_copy().box_gaps(box, np.array([[3.0, 0.5, 0.0]]), np.eye(3)[None],
                                                np.ones((1, 3)))[0])
    assert abs(aligned - 1.0) < 1e-12, aligned
    parent = bpy.data.objects.new('BAR_PARENT', None)
    bpy.context.scene.collection.objects.link(parent)
    parent.scale = (2.0, 1.0, 1.0)
    bar.parent = parent
    bpy.context.view_layer.update()
    assert not own_box(bar)[1][3]
    bar.parent = None
    bpy.data.objects.remove(parent)
    # decision 65, a moving bar: sliding away from A along the diagonal, turned beside it: its world box swept over
    # the motion comes within the distance (at frame 1 as above), its own box at no sampled frame
    scene = bpy.context.scene
    actions = set(bpy.data.actions)
    bar.rotation_euler = (0.0, 0.0, math.radians(45))
    bar.location = (-0.4, 0.4, 0.0)
    bar.keyframe_insert('location', frame=1)
    bar.location = (-0.6, 0.6, 0.0)
    bar.keyframe_insert('location', frame=50)
    scene.frame_set(1)
    refresh()
    sliding = list(store._state['scene_rule']['A'])
    assert sliding == rule and grade_of('A') == 'UP_TO_DATE', (sliding, grade_of('A'))
    # turning towards A during the motion: near at some sampled frames, so an occluder
    bar.animation_data_clear()
    bar.location = (-0.4, 0.4, 0.0)
    bar.keyframe_insert('rotation_euler', frame=1)
    bar.rotation_euler = (0.0, 0.0, math.radians(-45))
    bar.keyframe_insert('rotation_euler', frame=50)
    scene.frame_set(1)
    refresh()
    turning = list(store._state['scene_rule']['A'])
    assert 'BAR' in turning, turning
    bar.animation_data_clear()
    for act in set(bpy.data.actions) - actions:
        bpy.data.actions.remove(act)
    scene.frame_set(1)
    bpy.data.objects.remove(bar)
    bpy.data.meshes.remove(me)
    bpy.context.view_layer.update()
    refresh()
    assert store._state['scene_rule']['A'] == rule and grade_of('A') == 'UP_TO_DATE', grade_of('A')
    print(f"PASS: test_oriented_rule (AO distance {distance:.3f}; the bar turned beside A: world box gap "
          f"{world_gap:.3f}, own box gap {own_gap:.3f}, A's occluders {beside}, up to date; turned towards A: {towards}, "
          f"surroundings changed; aligned boxes gap {aligned:.3f}; a sheared child has no own box; moving: sliding "
          f"away {sliding}, turning towards A {turning})")


def test_shared_combine():
    """Decision 47: a shared mesh's copies (S1, S2 on plane D, 2 cm apart) are each baked in their own surroundings and
    combined per master pixel. Its -X face looks at S2 from S1 and at open space from S2: darkest < average < most lit
    there; the top stays lit; the plane's contact shadow is in every mode. The mesh's override and a moved copy make
    the master "surroundings changed"; the master's entry records the combine and the copies. Decision 77: One
    Instance bakes the selected copy alone (with several selected, the drop-down's, else the active one) and the
    entry's `instance` names it; a later selection, and Missing and Stale, keep it; an entry without `instance` (a
    master of decision 48) takes the old picked copy, else the first by name; a mesh never baked, or its copy renamed,
    the first by name. Decision 49: Split Samples gives each copy's view half the samples, Full Quality all; the
    averages agree."""
    refresh()
    item = store._state['items'][store._state['by_object']['S1']]
    assert item['combine'] == 'AVERAGE' and [c['object'] for c in item['copies']] == ['S1', 'S2'], item
    assert {'D', 'S2'} <= set(item['copies'][0]['occluders']), item['copies'][0]['occluders']
    me = bpy.data.meshes['MESH_SHARED_CUBE']
    s2 = bpy.data.objects['S2']

    def faces():
        m = core.load_master(str(FOLDER), store._state['by_object']['S1'])
        ev = core.evaluated_triangles(bpy.data.objects['S1'], bpy.context.evaluated_depsgraph_get(), [])
        P = ev['co'][ev['tris'][m['tri_src']]]
        nrm = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
        nrm /= np.linalg.norm(nrm, axis=1, keepdims=True)
        img = m['image'] / 65535.0
        out = {}
        for key, axis in (('-X', (-1, 0, 0)), ('+X', (1, 0, 0)), ('+Z', (0, 0, 1))):
            ids = np.nonzero(nrm @ np.array(axis, float) > 0.99)[0]
            sel = m['filled'] & np.isin(m['face_map'], ids)
            out[key] = round(float(img[sel].mean()), 4)
        out['min'] = round(float(img[m['filled']].min()), 4)
        return out
    got = {'AVERAGE': faces()}
    entry, _stem = entry_of('S1')
    assert entry['combine'] == 'AVERAGE' and entry['copies'] == 2, entry
    # decision 49: Split Samples (the default) gives each of the 2 copies half the samples; Full Quality all of them
    samples = int(bpy.context.scene.fss_ao_bake.samples)
    assert entry['sample_split'] and entry['view_samples'] == [samples // 2], entry
    bpy.context.scene.fss_ao_bake.sample_quality = 'FULL'
    refresh()
    split_grade = grade_of('S1')
    select(['S1'])
    assert bpy.ops.fss.ao_bake_start(scope='SELECTED', hidden=True, wait=True) == {'FINISHED'}
    full = entry_of('S1')[0]
    assert split_grade == 'SURROUNDINGS' and full['view_samples'] == [samples], (split_grade, full)
    got['AVERAGE full'] = faces()
    assert abs(got['AVERAGE full']['-X'] - got['AVERAGE']['-X']) < 0.03, got
    bpy.context.scene.fss_ao_bake.sample_quality = 'SPLIT'
    grades = {}
    for mode in ('LIGHTEST', 'DARKEST'):
        me.fss_ao_shared.combine = mode
        refresh()
        grades[mode] = grade_of('S1')
        select(['S1'])
        assert bpy.ops.fss.ao_bake_start(scope='SELECTED', hidden=True, wait=True) == {'FINISHED'}
        assert grade_of('S1') == 'UP_TO_DATE', grade_of('S1')
        got[mode] = faces()
    # decision 77: One Instance bakes the selected copy; its master's index entry remembers it (`instance`) and Refresh
    # grades against that copy. The Refreshes the scene rule reference recorded for decision 48 (S2 graded and baked,
    # then the first by name graded and baked) keep their place and values; the checks added around them run in
    # rule_unrecorded() blocks
    scene = bpy.context.scene
    s = scene.fss_ao_bake
    stem = store._state['by_object']['S1']
    one = {}  # what each step found, for the report

    def graded():
        it = store._state['items'][stem]
        return [c['object'] for c in it['copies']], it['grade'], it.get('instance_from'), it.get('baked_from')

    def remembered():
        return (entry_of('S1')[0] or {}).get('instance', 'no field')

    def bake(names, active=None, scope='SELECTED'):
        select(names)
        if active:
            bpy.context.view_layer.objects.active = bpy.data.objects[active]
        assert bpy.ops.fss.ao_bake_start(scope=scope, hidden=True, wait=True) == {'FINISHED'}
        return remembered()
    me.fss_ao_shared.combine = 'ONE'
    me.fss_ao_shared.instance = s2  # decision 48's picked copy: read only for an entry without `instance`
    refresh()  # the Darkest master's entry has no `instance`: the old picked copy (rule 1.3)
    one['old pointer S2'] = graded()
    assert one['old pointer S2'][:3] == (['S2'], 'SURROUNDINGS', 'pointer'), one
    grades['one instance S2'] = grade_of('S1')
    # step 2.1: S2 selected, Bake Selected: S2 baked, the entry names it, the faces as Most Lit's
    one['2.1 S2 selected, instance'] = bake(['S2'])
    assert one['2.1 S2 selected, instance'] == 'S2', one
    assert store._state['items'][stem]['baked_from'] == 'S2' and grade_of('S1') == 'UP_TO_DATE', graded()
    got['ONE S2'] = faces()
    with rule_unrecorded():
        # step 2.2: S1 selected, Refresh: a selection changes nothing
        select(['S1'])
        refresh()
        one['2.2 S1 selected, Refresh'] = graded()
        assert one['2.2 S1 selected, Refresh'] == (['S2'], 'UP_TO_DATE', 'entry', 'S2'), one
        # step 2.3: S2 moved, Missing and Stale with S1 selected: S2 baked again, the entry still names S2
        s2.location.y += 0.01
        bpy.context.view_layer.update()
        select(['S1'])
        refresh()
        def outdated():
            return sorted(store.bake_choice(list(store._state['items']), s.bake_ao, s.curvature, False,
                                            store.denoise_opts(scene))[0])
        stale = outdated()
        assert stem in stale, stale  # also plane D, which S2 shades
        one['2.3 S2 moved, stale'] = stale
        one['2.3 S2 moved, before'] = graded()
        assert one['2.3 S2 moved, before'][:2] == (['S2'], 'SURROUNDINGS'), one
        one['2.3 Missing and Stale, instance'] = bake(['S1'], scope='STALE')
        assert one['2.3 Missing and Stale, instance'] == 'S2' and grade_of('S1') == 'UP_TO_DATE', (one, graded())
        s2.location.y -= 0.01
        bpy.context.view_layer.update()
        # S2 back: Missing and Stale again, so every master is up to date as before (the recorded Refreshes after)
        assert bake(['S1'], scope='STALE') == 'S2', remembered()
        refresh()
        assert not outdated() and graded()[:2] == (['S2'], 'UP_TO_DATE'), (outdated(), graded())
        # step 2.4: S1 and S2 selected, S2 active, the drop-down set to S1: S1 baked (the faces as Darkest's)
        select(['S1', 'S2'])
        bpy.context.view_layer.objects.active = s2
        items = [i[0] for i in ao_bake.bake_copy_items(me.fss_ao_shared, bpy.context)]
        assert items == ['S1', 'S2'] and me.fss_ao_shared.bake_copy == 'S2', (items, me.fss_ao_shared.bake_copy)
        me.fss_ao_shared.bake_copy = 'S1'
        assert me.fss_ao_shared.bake_copy_name == 'S1' and me.fss_ao_shared.bake_copy == 'S1'
        one['2.4 drop-down S1, instance'] = bake(['S1', 'S2'], active='S2')
        assert one['2.4 drop-down S1, instance'] == 'S1', one
        got['ONE S1 drop-down'] = faces()
        # the drop-down naming a copy not selected: the active one
        select(['S2'])
        assert ao_bake.bake_instances(bpy.context) == {me.name: 'S2'}, ao_bake.bake_instances(bpy.context)
        # the drop-down unset, S2 active: S2 baked (the faces as Most Lit's)
        me.fss_ao_shared.bake_copy_name = ''
        one['2.4 drop-down unset, S2 active, instance'] = bake(['S1', 'S2'], active='S2')
        assert one['2.4 drop-down unset, S2 active, instance'] == 'S2', one
        got['ONE S2 active'] = faces()
        # step 2.5: an old master (its entry without `instance`), baked from S2, the old picked copy S2: up to date
        index = store.read_index(str(FOLDER), use_cache=False)
        del index['masters'][stem]['instance']
        store.write_index(str(FOLDER), index)
        assert remembered() == 'no field'
        refresh()
        one['2.5 old entry, pointer S2'] = graded()
        assert one['2.5 old entry, pointer S2'] == (['S2'], 'UP_TO_DATE', 'pointer', 'S2'), one
    # step 2.5, then the pointer empty: the first by name (S1), surroundings changed
    me.fss_ao_shared.instance = None
    refresh()
    one['2.5 old entry, pointer empty'] = graded()
    assert one['2.5 old entry, pointer empty'][:3] == (['S1'], 'SURROUNDINGS', 'first'), one
    grades['one instance first by name'] = grade_of('S1')
    one['S1 selected, instance'] = bake(['S1'])
    assert one['S1 selected, instance'] == 'S1', one
    got['ONE first'] = faces()
    with rule_unrecorded():
        # step 2.7: the remembered copy (S1) renamed: the first by name (S2)
        s1 = bpy.data.objects['S1']
        s1.name = 'S9_RENAMED'
        select([])
        refresh()
        one['2.7 S1 renamed'] = graded()
        assert one['2.7 S1 renamed'] == (['S2'], 'SURROUNDINGS', 'first', 'S1'), one
        s1.name = 'S1'
        # step 2.6: a mesh never baked (a copy of the mesh, two copies far away): its first copy by name
        me2 = me.copy()
        me2.name = 'MESH_NEVER_BAKED'
        me2.fss_ao_shared.combine = 'ONE'
        coll = s2.users_collection[0]
        news = []
        for name, x in (('NB_2', 50.0), ('NB_1', 50.2)):
            o = bpy.data.objects.new(name, me2)
            o.location = (x, 50.0, 50.0)
            coll.objects.link(o)
            news.append(o)
        bpy.context.view_layer.update()
        store.refresh(bpy.context, relink=False)  # no relink: the copy's mesh hash is the baked mesh's
        it = store._state['items'][store._state['by_object']['NB_1']]
        one['2.6 never baked'] = ([c['object'] for c in it['copies']], it['grade'], it['instance_from'],
                                  it['baked_from'])
        assert one['2.6 never baked'] == (['NB_1'], 'MISSING', 'first', None), one
        for o in news:
            bpy.data.objects.remove(o)
        bpy.data.meshes.remove(me2)
        bpy.context.view_layer.update()
    assert abs(got['ONE S2']['-X'] - got['LIGHTEST']['-X']) < 0.03, got
    assert abs(got['ONE S2 active']['-X'] - got['LIGHTEST']['-X']) < 0.03, got
    assert abs(got['ONE first']['-X'] - got['DARKEST']['-X']) < 0.03, got
    assert abs(got['ONE S1 drop-down']['-X'] - got['DARKEST']['-X']) < 0.03, got
    me.fss_ao_shared.combine = 'DEFAULT'
    refresh()
    grades['back to the default'] = grade_of('S1')
    s2.location.y += 0.01
    refresh()
    grades['S2 moved'] = grade_of('S1')
    s2.location.y -= 0.01
    select(['S1'])
    assert bpy.ops.fss.ao_bake_start(scope='SELECTED', hidden=True, wait=True) == {'FINISHED'}
    assert grade_of('S1') == 'UP_TO_DATE'
    assert all(g == 'SURROUNDINGS' for g in grades.values()), grades
    d, a, li = got['DARKEST']['-X'], got['AVERAGE']['-X'], got['LIGHTEST']['-X']
    assert d < a - 0.02 and a < li - 0.02, got
    assert all(v['+Z'] > 0.98 and v['min'] < 0.9 for v in got.values()), got
    print(f"PASS: test_shared_combine (per face mean / minimum: {got}; {grades}; decision 77: {one})")


def test_auto_distance():
    """Decision 51: Auto Distance gives the 6 cm cube O1 a 6 cm AO distance (its longest box axis, factor 1) and leaves
    the 20 cm plane A at the scene's 10 cm; only O1 becomes "surroundings changed". Baked, its entry records 6 cm and it
    is no darker than at 10 cm; factor 0.5 gives 3 cm; turned off, the scene's distance again."""
    scene = bpy.context.scene
    s = scene.fss_ao_bake
    refresh()
    assert grade_of('O1') == grade_of('A') == 'UP_TO_DATE', (grade_of('O1'), grade_of('A'))
    before = float(master_image('O1')[1].mean())
    s.auto_distance = True
    refresh()
    items, by = store._state['items'], store._state['by_object']
    d_o1, d_a = items[by['O1']]['ao_distance'], items[by['A']]['ao_distance']
    assert abs(d_o1 - 0.06) < 1e-6 and abs(d_a - 0.1) < 1e-6, (d_o1, d_a)
    assert grade_of('O1') == 'SURROUNDINGS' and grade_of('A') == 'UP_TO_DATE', (grade_of('O1'), grade_of('A'))
    select(['O1'])
    assert bpy.ops.fss.ao_bake_start(scope='SELECTED', hidden=True, wait=True) == {'FINISHED'}
    refresh()
    entry = entry_of('O1')[0]
    after = float(master_image('O1')[1].mean())
    assert abs(entry['ao_distance'] - 0.06) < 1e-6 and grade_of('O1') == 'UP_TO_DATE', (entry['ao_distance'],)
    assert after >= before - 0.01, (before, after)
    s.auto_distance_factor = 0.5
    refresh()
    d_half = store._state['items'][store._state['by_object']['O1']]['ao_distance']
    assert abs(d_half - 0.03) < 1e-6 and grade_of('O1') == 'SURROUNDINGS', (d_half, grade_of('O1'))
    s.auto_distance_factor = 1.0
    s.auto_distance = False
    refresh()
    assert grade_of('O1') == 'SURROUNDINGS' and grade_of('A') == 'UP_TO_DATE'
    select(['O1'])
    assert bpy.ops.fss.ao_bake_start(scope='SELECTED', hidden=True, wait=True) == {'FINISHED'}
    refresh()
    assert grade_of('O1') == 'UP_TO_DATE' and abs(entry_of('O1')[0]['ao_distance'] - 0.1) < 1e-6
    print(f'PASS: test_auto_distance (O1 at 10 cm {before:.4f}, at 6 cm {after:.4f})')


def test_falloff():
    """Decision 53: Distance Falloff (3 steps) makes O1 "surroundings changed" and A too (every master's key), the job
    and the entry carry the steps, and O1 baked with it is lighter than without (the plane's far part darkens less);
    turned off, the masters are up to date again after O1's re-bake."""
    s = bpy.context.scene.fss_ao_bake
    refresh()
    assert grade_of('O1') == grade_of('A') == 'UP_TO_DATE', (grade_of('O1'), grade_of('A'))
    before = float(master_image('O1')[1].mean())
    s.falloff, s.falloff_steps = True, 3
    refresh()
    item = store._state['items'][store._state['by_object']['O1']]
    assert item['falloff'] == 3 and grade_of('O1') == grade_of('A') == 'SURROUNDINGS', (item['falloff'],)
    select(['O1'])
    assert bpy.ops.fss.ao_bake_start(scope='SELECTED', hidden=True, wait=True) == {'FINISHED'}
    refresh()
    entry = entry_of('O1')[0]
    after = float(master_image('O1')[1].mean())
    assert entry['falloff'] == 3 and grade_of('O1') == 'UP_TO_DATE', entry.get('falloff')
    assert 'falloff_curve' not in entry or entry['falloff_curve'] is None, entry.get('falloff_curve')
    assert after > before + 0.02, (before, after)
    # decision 105: the curve changes every master's key; Sharp lighter than Linear, Root darker. Its Refreshes came
    # after the scene rule reference was recorded (rule_unrecorded)
    means = {'LINEAR': after}
    with rule_unrecorded():
        for curve in ('SHARP', 'ROOT'):
            s.falloff_curve = curve
            refresh()
            item = store._state['items'][store._state['by_object']['O1']]
            assert item['falloff_curve'] == curve and grade_of('O1') == grade_of('A') == 'SURROUNDINGS', (
                curve, item.get('falloff_curve'), grade_of('O1'), grade_of('A'))
            select(['O1'])
            assert bpy.ops.fss.ao_bake_start(scope='SELECTED', hidden=True, wait=True) == {'FINISHED'}
            refresh()
            assert grade_of('O1') == 'UP_TO_DATE' and entry_of('O1')[0].get('falloff_curve') == curve, (
                curve, entry_of('O1')[0].get('falloff_curve'))
            means[curve] = float(master_image('O1')[1].mean())
    assert means['SHARP'] > means['LINEAR'] + 0.002 and means['ROOT'] < means['LINEAR'] - 0.002, means
    s.falloff = False  # the curve (Root) without the falloff: the keys as without it
    refresh()
    assert grade_of('A') == 'UP_TO_DATE' and grade_of('O1') == 'SURROUNDINGS'
    select(['O1'])
    assert bpy.ops.fss.ao_bake_start(scope='SELECTED', hidden=True, wait=True) == {'FINISHED'}
    refresh()
    assert grade_of('O1') == 'UP_TO_DATE' and entry_of('O1')[0].get('falloff') is None
    assert entry_of('O1')[0].get('falloff_curve') is None
    s.falloff_curve = 'LINEAR'
    print(f'PASS: test_falloff (O1 without {before:.4f}, with 3 steps Linear {after:.4f}, Sharp '
          f"{means['SHARP']:.4f}, Root {means['ROOT']:.4f})")


def test_object_uv():
    """Decision 107: Master Layout Object UV makes A "surroundings changed"; its master is baked in A's own UVs at
    4 x 4 master pixels per texel (meta object_uv, scale 4, an offset of whole texels); Apply writes each texel inside
    the island as the mean of its 16 master pixels (within the 16-bit rounding) and names A in the report. A moved UV
    makes A stale and Apply copies face by face with a warning. Back to Auto Unwrap, A is baked in a new Auto layout.
    Its Refreshes came after the scene rule reference was recorded (rule_unrecorded)."""
    s = bpy.context.scene.fss_ao_bake
    a = bpy.data.objects['A']
    uvl = a.data.uv_layers.active
    with rule_unrecorded():
        refresh()
        assert grade_of('A') == 'UP_TO_DATE', grade_of('A')
        s.master_layout = 'OBJECT_UV'
        try:
            refresh()
            item = store._state['items'][store._state['by_object']['A']]
            assert item['master_layout'] == 'OBJECT_UV' and grade_of('A') == 'SURROUNDINGS', (
                item.get('master_layout'), grade_of('A'))
            select(['A'])
            assert bpy.ops.fss.ao_bake_start(scope='SELECTED', hidden=True, wait=True) == {'FINISHED'}
            refresh()
            assert grade_of('A') == 'UP_TO_DATE', grade_of('A')
            m, _v = master_image('A')
            ouv = m['meta'].get('object_uv')
            assert ouv and ouv['scale'] == 4 and all(float(o) % 4 == 0 for xy in ouv['offsets'] for o in xy), ouv
            # packed: the master no larger than its islands' texel boxes (with their margin) at 4 x 4
            assert m['W'] * m['H'] <= 1.2 * sum((r[2] * r[3]) for r in np.asarray(m['rects']).tolist()), (
                m['W'], m['H'], m['rects'])
            rep = apply_set('SET_A', objects=[a], file_name='object_uv.png')
            assert rep['object_uv'] == ['A'] and not rep['warnings'], (rep['object_uv'], rep['warnings'])
            assert any('Object UV' in x for x in ao_bake_apply.report_lines(rep))
            g, _b, _ = read(rep['path'])
            # the texels whose 3 x 3 neighbourhood is in A's faces: all 16 master pixels are A's, the plain mean
            uv = np.zeros(len(uvl.data) * 2)
            uvl.data.foreach_get('uv', uv)
            ev = core.evaluated_triangles(a, bpy.context.evaluated_depsgraph_get(), [uvl.name])
            uvpx = ev['uv'][uvl.name] * SIZE
            own, _c = core.raster_window(uvpx, SIZE, SIZE, 1, 0, 0)
            cov = own >= 0
            inner = cov.copy()
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    inner &= np.roll(np.roll(cov, dy, 0), dx, 1)
            Y, X = np.nonzero(inner)
            img = m['image'].astype(np.float64)
            assert len(ouv['offsets']) == 1, ouv  # A's plane is one UV island
            ox, oy = int(ouv['offsets'][0][0]), int(ouv['offsets'][0][1])
            want = np.zeros(len(X))
            for j in range(4):
                for i in range(4):
                    want += img[Y * 4 - oy + j, X * 4 - ox + i]
            want /= 16.0
            got = g[:, :, 0].astype(np.float64)[Y, X]
            err = float(np.abs(got - want).max())
            assert len(X) > 100 and err <= 1.0, (len(X), err)
            # a moved UV: stale, and Apply copies face by face
            moved = uv.copy()
            moved[0::2] += 0.5 / SIZE
            uvl.data.foreach_set('uv', moved)
            a.data.update()
            refresh()
            assert grade_of('A') == 'SURROUNDINGS', grade_of('A')
            rep = apply_set('SET_A', objects=[a], file_name='object_uv_moved.png')
            assert not rep['object_uv'] and any('other UVs' in w for w in rep['warnings']), rep['warnings']
            uvl.data.foreach_set('uv', uv)
            a.data.update()
        finally:
            s.master_layout = 'AUTO'
        refresh()
        assert grade_of('A') == 'SURROUNDINGS', grade_of('A')
        select(['A'])
        assert bpy.ops.fss.ao_bake_start(scope='SELECTED', hidden=True, wait=True) == {'FINISHED'}
        refresh()
        assert grade_of('A') == 'UP_TO_DATE' and not master_image('A')[0]['meta'].get('object_uv')
    print(f'PASS: test_object_uv ({len(X)} inner texels within {err:g} of the mean of their 16 master pixels)')


def test_falloff_distances():
    """Decision 105: Cycles' falloff distances. Linear: the distance times 1/n ... 1, as decision 53 computed them (the
    same floats); each curve: nearest first, the last at the distance, and the share of distances beyond t a staircase
    over the curve's weight (at most 1/n above it) at 2001 points, for 2 to 16 steps."""
    for n in range(2, 17):
        assert core.falloff_distances(0.25, n) == [0.25 * (k + 1) / n for k in range(n)], n
        for curve in core.FALLOFF_CURVES:
            d = np.array(core.falloff_distances(0.25, n, curve))
            assert np.all(np.diff(d) > 0) and abs(d[-1] - 0.25) < 1e-12, (curve, n, d)
            t = np.linspace(0.0, 0.25, 2001)
            share = (d[None, :] > t[:, None]).mean(axis=1)
            w = core.falloff_weight(curve, 1.0 - t / 0.25)
            assert np.all(share >= w - 1e-9) and np.all(share <= w + 1.0 / n + 1e-9), (curve, n)
    w = {c: round(float(core.falloff_weight(c, 0.5)), 4) for c in core.FALLOFF_CURVES}
    assert w == {'LINEAR': 0.5, 'SHARP': 0.25, 'SMOOTH': 0.5, 'ROOT': 0.7071}, w
    print(f'PASS: test_falloff_distances (2 to 16 steps, 4 curves; weight at half the distance {w})')


def test_curvature():
    """Decision 54: Curvature Map (5 mm) does not change the AO masters' keys; a bake of O1 (a flat-shaded cube, 12
    convex sharp edges) also writes its curvature master: flat grey (0.5) on most of it, none below grey, white at the
    edges. Apply writes SET_B_curvature.png, grey 16-bit, flat where no face is, with the edges' bright bands."""
    s = bpy.context.scene.fss_ao_bake
    refresh()
    assert grade_of('O1') == 'UP_TO_DATE'
    s.curvature, s.curv_width = True, 0.005
    refresh()
    assert grade_of('O1') == 'UP_TO_DATE'  # not in the AO key
    select(['O1'])
    assert bpy.ops.fss.ao_bake_start(scope='SELECTED', hidden=True, wait=True) == {'FINISHED'}
    refresh()
    entry, stem = entry_of('O1')
    assert entry['curvature']['width'] == 0.005 and entry['curvature']['edges'] == 12, entry.get('curvature')
    m = core.load_master(str(FOLDER), stem, kind='curv')
    v = m['image'][m['filled']] / 65535.0
    assert abs(float(np.median(v)) - 0.5) < 0.01 and v.min() > 0.49 and v.max() > 0.95, (np.median(v), v.min(), v.max())
    band = float((v > 0.55).mean())
    rep = ao_bake_apply.apply_set(bpy.context, bpy.data.materials['SET_B'], None, ApplySettings(), kind='curv')
    assert not rep.get('error') and rep['path'].endswith('SET_B_curvature.png'), rep
    vals, bits, _ct = read(rep['path'])
    assert bits == 16 and np.array_equal(vals[:, :, 0], vals[:, :, 1]), bits
    t = vals[:, :, 0] / 65535.0
    assert t.max() > 0.95 and t.min() > 0.49 and abs(float(np.median(t)) - 0.5) < 0.01, (t.min(), t.max())
    # the panel's Curvature Map rows: its own folder (empty: the AO's), file (empty: <set>_curvature.png) and size
    mat = bpy.data.materials['SET_B']
    a = mat.fss_ao_apply
    assert s.curv_output_folder == s.output_folder and a.curv_file_name == 'SET_B_curvature.png'
    own = str(OUT / 'curv_own')
    s.curv_output_folder, a.curv_file_name, a.curv_resolution = own, 'own_cm', '256'
    rep2 = ao_bake_apply.apply_set(bpy.context, mat, None, a, kind='curv')
    assert not rep2.get('error') and rep2['path'] == os.path.join(os.path.normpath(own), 'own_cm.png'), rep2
    assert tuple(rep2['size']) == (256, 256), rep2['size']
    s.curv_output_folder, a.curv_file_name = '', ''
    a['curv_resolution'] = 0  # back to the default (ORM Texture Size; without one, the set's size)
    assert s.curv_output_folder == s.output_folder and a.curv_file_name == 'SET_B_curvature.png'
    s.curvature = False
    print(f'PASS: test_curvature (O1: {entry["curvature"]["edges"]} sharp edges, {band * 100:.0f} % of its master in '
          f'the edge bands, max {v.max():.3f}; {os.path.basename(rep["path"])} max {t.max():.3f}; the Curvature Map '
          f'rows: curv_own/own_cm.png at 256 x 256)')


def test_curvature_only():
    """Decision 55: the bake row's AO and CM. CM alone (Bake Selected) writes only O1's curvature, in its AO master's
    layout, equal to the one an AO bake wrote, and leaves the AO master as it was; a width change makes only the
    curvature stale (CM grade WIDTH), and Missing and Stale with CM alone bakes it; an AO bake alone keeps a curvature
    of the same layout; a master without an up-to-date mesh needs its AO first; Apply's report of islands where the
    width is under 2 px."""
    s = bpy.context.scene.fss_ao_bake
    s.curvature, s.curv_width, s.bake_ao = True, 0.005, True
    refresh()
    entry, stem = entry_of('O1')
    item = store._state['items'][stem]
    assert item['cm_grade'] == 'UP_TO_DATE', item['cm_grade']
    before = core.load_master(str(FOLDER), stem, kind='curv')['image']
    ao_path = core.master_paths(str(FOLDER), stem)[0]
    ao_mtime, baked_at = os.path.getmtime(ao_path), entry['baked_at']
    s.bake_ao = False
    select(['O1'])
    assert bpy.ops.fss.ao_bake_start(scope='SELECTED', hidden=True, wait=True) == {'FINISHED'}
    refresh()
    entry, _ = entry_of('O1')
    assert entry['baked_at'] == baked_at and os.path.getmtime(ao_path) == ao_mtime, 'the AO was baked again'
    after = core.load_master(str(FOLDER), stem, kind='curv')['image']
    diff = int(np.abs(after.astype(np.int64) - before).max())
    assert diff <= 1, f'curvature alone differs from the AO bake by {diff}'
    s.curv_width = 0.003
    refresh()
    item = store._state['items'][stem]
    assert item['grade'] == 'UP_TO_DATE' and item['cm_grade'] == 'WIDTH', (item['grade'], item['cm_grade'])
    what, _needs = store.bake_choice([stem], False, True, False)
    assert what == {stem: (False, True, False)}, what
    assert store.bake_choice([stem], True, False, False)[0] == {}, 'AO up to date: nothing for Missing and Stale'
    assert bpy.ops.fss.ao_bake_start(scope='STALE', hidden=True, wait=True) == {'FINISHED'}
    refresh()
    entry, _ = entry_of('O1')
    item = store._state['items'][stem]
    assert entry['curvature']['width'] == 0.003 and item['cm_grade'] == 'UP_TO_DATE', entry['curvature']
    assert entry['baked_at'] == baked_at, 'the AO was baked again'
    # an AO bake alone: the same layout, so the curvature is kept
    s.bake_ao, s.curvature = True, False
    select(['O1'])
    assert bpy.ops.fss.ao_bake_start(scope='SELECTED', hidden=True, wait=True) == {'FINISHED'}
    refresh()
    entry, _ = entry_of('O1')
    item = store._state['items'][stem]
    assert entry['baked_at'] != baked_at and item['cm_grade'] == 'UP_TO_DATE', (entry['baked_at'], item['cm_grade'])
    # no up-to-date AO mesh: CM alone cannot, with AO it is written with it
    saved = item['grade'], item['cm_grade']
    item['grade'], item['cm_grade'] = 'MESH', 'NEEDS_AO'
    assert store.bake_choice([stem], False, True, True) == ({}, ['O1'])
    assert store.bake_choice([stem], True, True, False) == ({stem: (True, True, False)}, [])
    item['grade'], item['cm_grade'] = saved
    # Apply's narrow islands: a 1 m square at 100 px/m, 1 cm wide bands are 1 px
    pos = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], np.float64)
    tris = np.array([[0, 1, 2], [0, 2, 3]])
    uvpx = pos[tris][:, :, :2] * 100.0
    got = ao_bake_apply.narrow_islands(pos, dict(co=pos), tris, uvpx, 1024, 1024, 0.01)
    assert got is not None and got[:2] == (1, 1) and abs(got[3] - 0.02) < 1e-9, got
    assert ao_bake_apply.narrow_islands(pos, dict(co=pos), tris, uvpx, 1024, 1024, 0.03) is None
    s.curvature, s.bake_ao = False, True
    print(f'PASS: test_curvature_only (alone equal to the AO bake within {diff}, AO untouched; width stale and '
          f'baked alone; kept by an AO bake of the same layout; narrow islands {got})')


def test_corner_rule():
    """Decision 57, without a bake: a floor meeting a wall (an inside corner) and the wall meeting a cap (a rim), their
    master with known baked values; the pixels the corner rule checks set brighter than their inward pixel, half by
    0.1 (over CORNER_EXCESS) and half by 0.01 (under it). Composed, the first half takes the inward value, the second
    stays, no pixel of the rim's cap is checked, and without the pairs the composition keeps them all."""
    s = 0.02
    pos = np.array([(0, 0, 0), (s, 0, 0), (s, s, 0), (0, s, 0),            # floor, z = 0
                    (0, s, s), (s, s, s),                                   # the wall's top (the wall at y = s)
                    (0, 2 * s, s), (s, 2 * s, s)], np.float64)              # the cap beyond the wall's top
    tris = np.array([(0, 1, 2), (0, 2, 3),          # floor (normal +z)
                     (3, 2, 5), (3, 5, 4),          # wall (normal -y, facing the floor)
                     (4, 5, 7), (4, 7, 6)], np.int64)  # cap (normal +z)
    P = pos[tris]
    tn = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
    tn /= np.linalg.norm(tn, axis=1, keepdims=True)
    assert tn[0, 2] > 0.99 and tn[2, 1] < -0.99 and tn[4, 2] > 0.99, tn
    cn = np.repeat(tn[:, None, :], 3, axis=1)
    m = core.build_master(pos, tris, cn, 3000.0, gutter=core.GUTTER, order=core.ORDER, mirror_open=core.MIRROR_OPEN,
                          fold_split=core.FOLD_SPLIT)
    W, H = m['W'], m['H']
    pairs = core.corner_pairs(m, pos, tris)
    cy, cx, iy, ix = pairs
    assert len(cy) > 20, len(cy)
    own, _cnt = core.rasterize_ids(m['muv'], W, H)
    baked = own >= 0
    owners = set(own[cy, cx].tolist()) - {-1}
    assert owners and owners <= {0, 1, 2, 3}, owners  # floor and wall only: the rim's cap is never checked
    rng = np.random.default_rng(3)
    base = np.where(baked, rng.integers(10000, 40000, (H, W)), 65535).astype(np.uint16)
    M16 = base.copy()
    uniq = np.unique(np.stack([cy, cx], 1), axis=0)
    big = set(map(tuple, uniq[::2].tolist()))
    for (y, x), (yi, xi) in zip(zip(cy.tolist(), cx.tolist()), zip(iy.tolist(), ix.tolist())):
        if baked[y, x] and baked[yi, xi]:
            M16[y, x] = min(65535, int(base[yi, xi]) + (6554 if (y, x) in big else 655))
    for (y, x), (yi, xi) in zip(zip(cy.tolist(), cx.tolist()), zip(iy.tolist(), ix.tolist())):
        if baked[y, x] and baked[yi, xi] and (y, x) not in big:
            assert int(M16[y, x]) - int(M16[yi, xi]) <= int(core.CORNER_EXCESS * 65535), (y, x)
    m['corner_pairs'] = pairs
    counts, vals, _filled, _face = core.compose_whole(m, M16, baked)
    m['corner_pairs'] = None
    _c0, vals0, _f0, _fm0 = core.compose_whole(m, M16, baked)
    fixed = kept = 0
    for (y, x), (yi, xi) in zip(zip(cy.tolist(), cx.tolist()), zip(iy.tolist(), ix.tolist())):
        if not (baked[y, x] and baked[yi, xi]):
            continue
        if (y, x) in big:
            assert vals[y, x] <= M16[yi, xi] and vals[y, x] < M16[y, x], (y, x, vals[y, x], M16[y, x], M16[yi, xi])
            fixed += 1
        else:
            assert vals[y, x] == M16[y, x], (y, x)
            kept += 1
        assert vals0[y, x] == M16[y, x], (y, x)
    outside = baked.copy()
    outside[cy, cx] = False
    assert (vals[outside] == M16[outside]).all()
    assert counts['corner_px'] == len({(y, x) for y, x in zip(cy.tolist(), cx.tolist())
                                       if (y, x) in big and baked[y, x]}), counts['corner_px']
    print(f'PASS: test_corner_rule (master {W} x {H}, {len(uniq)} pixels checked at the inside corner, none on the rim; '
          f'{fixed} brighter by 0.1 took the inward value, {kept} brighter by 0.01 kept; without the pairs all kept)')


def test_denoise():
    """Decision 56: Denoise with the curvature guide (CM unticked): Bake Selected bakes O1 and filters it, its raw bake
    kept beside it, the curvature written for the guide; the noise measured on the master drops, pixels without a face
    keep their raw value; a changed Strength makes only the denoise stale, and Missing and Stale re-runs the filter
    from the raw bake without rays (Strength 0.5 halfway between raw and filtered); Denoise off restores the raw bake
    byte for byte; the panel draws its options without writing."""
    s = bpy.context.scene.fss_ao_bake
    s.bake_ao, s.curvature, s.denoise, s.dn_curv_mode, s.dn_strength = True, False, True, 'SIMILAR', 1.0
    s.dn_method = 'FILTER'  # this test: the Surface Filter (test_denoise_oidn: OIDN)
    refresh()
    entry, stem = entry_of('O1')
    assert store._state['items'][stem]['dn_grade'] == 'STALE'
    assert core.denoise_levels(1.0, 5) == 1 and core.denoise_levels(18.0, 5) == 5 and core.denoise_levels(200, 7) == 7
    calls = []
    bpy.types.FSS_PT_ao_bake.draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
    drawn = {args[1] for name, args, _kw in calls if name == 'prop' and len(args) > 1}
    assert {'dn_radius', 'dn_levels', 'dn_detail', 'dn_normal', 'dn_curv_mode', 'dn_curv_threshold', 'dn_noise',
            'dn_strength'} <= drawn, drawn
    assert not {p for p in drawn if 'gradient' in p or 'bridge' in p}, drawn  # Follow Gradient and Bridge Seams removed
    select(['O1'])
    assert bpy.ops.fss.ao_bake_start(scope='SELECTED', hidden=True, wait=True) == {'FINISHED'}
    refresh()
    entry, _ = entry_of('O1')
    item = store._state['items'][stem]
    raw_path = core.master_paths(str(FOLDER), stem, 'ao.raw')[0]
    assert os.path.isfile(raw_path) and entry['denoise']['settings'] == store.denoise_opts(bpy.context.scene), entry
    assert item['dn_grade'] == 'UP_TO_DATE' and item['cm_grade'] == 'UP_TO_DATE', (item['dn_grade'], item['cm_grade'])
    assert entry['denoise']['curvature'] == 'SIMILAR', entry['denoise']
    # a master denoised while Follow Gradient and Bridge Seams existed (both off) stays up to date
    old = dict(entry, denoise=dict(entry['denoise'], settings=dict(entry['denoise']['settings'], bridge=False,
                                                                  gradient=False)))
    want = store.denoise_opts(bpy.context.scene)
    assert store.dn_grade(item, old, str(FOLDER), want) == 'UP_TO_DATE'
    old['denoise']['settings']['bridge'] = True
    assert store.dn_grade(item, old, str(FOLDER), want) == 'STALE'
    raw = core.load_master(str(FOLDER), stem, kind='ao.raw')
    den = core.load_master(str(FOLDER), stem)
    a_raw, a_den = core.noise_alpha(raw, raw['W'], raw['H']), core.noise_alpha(den, den['W'], den['H'])
    assert a_den < 0.5 * a_raw, (a_raw, a_den)
    gutter = raw['filled'] & (raw['face_map'] < 0)
    assert np.array_equal(raw['image'][gutter], den['image'][gutter]), 'gutter changed'
    baked_at = entry['baked_at']
    # Strength 0.5: only the denoise is stale; Missing and Stale re-runs it from the raw bake
    s.dn_strength = 0.5
    refresh()
    item = store._state['items'][stem]
    assert item['grade'] == 'UP_TO_DATE' and item['dn_grade'] == 'STALE', (item['grade'], item['dn_grade'])
    assert store.bake_choice([stem], True, False, False, store.denoise_opts(bpy.context.scene))[0] == {
        stem: (False, False, True)}
    # the panel's flow: Select Missing and Stale, then Bake Selected (AUTO: the denoise alone, without rays)
    select([])
    assert bpy.ops.fss.ao_bake_select(which='OUTDATED') == {'FINISHED'}
    picked = {o.name for o in bpy.context.selected_objects}
    assert 'O1' in picked, picked
    assert store.bake_auto([stem], True, False, store.denoise_opts(bpy.context.scene))[0] == {stem: (False, False, True)}
    assert bpy.ops.fss.ao_bake_start(scope='AUTO', hidden=True, wait=True) == {'FINISHED'}
    refresh()
    entry, _ = entry_of('O1')
    assert entry['baked_at'] == baked_at and store._state['items'][stem]['dn_grade'] == 'UP_TO_DATE'
    assert store.dn_counts()['STALE'] == 0, store.dn_counts()
    # nothing out of date: Select Missing and Stale selects none of them, and Bake Selected bakes O1 in full
    assert bpy.ops.fss.ao_bake_select(which='OUTDATED') == {'FINISHED'}
    assert not bpy.context.selected_objects, [o.name for o in bpy.context.selected_objects]
    assert store.bake_auto([stem], True, False, store.denoise_opts(bpy.context.scene))[0][stem][0] is True
    half = core.load_master(str(FOLDER), stem)['image'].astype(np.int64)
    want = raw['image'].astype(np.int64) + 0.5 * (den['image'].astype(np.int64) - raw['image'])
    err = float(np.abs(half - want)[raw['filled'] & (raw['face_map'] >= 0)].max())
    assert err <= 1.0, err
    n_dn = sum(1 for e in store.read_index(str(FOLDER), use_cache=False)['masters'].values() if e.get('denoise'))
    # Denoise off: the raw bake back, byte for byte
    s.denoise = False
    refresh()
    assert store._state['items'][stem]['dn_grade'] == 'STALE'
    assert bpy.ops.fss.ao_bake_start(scope='STALE', hidden=True, wait=True) == {'FINISHED'}
    refresh()
    entry, _ = entry_of('O1')
    back = core.load_master(str(FOLDER), stem)['image']
    assert np.array_equal(back, raw['image']) and not os.path.isfile(raw_path) and entry.get('denoise') is None
    assert store.dn_counts()['STALE'] == 0, store.dn_counts()
    s.dn_strength = 1.0
    print(f'PASS: test_denoise (noise alpha {a_raw:.5f} raw, {a_den:.5f} denoised, gutter kept; strength 0.5 from the '
          f'raw bake without rays within {err:g}; {n_dn} masters denoised by Select Missing and Stale, Bake Selected; '
          f'Denoise off restored '
          f'the raw bake byte for byte; the options drawn)')


def test_denoise_oidn():
    """Denoise method OIDN (Open Image Denoise, islands isolated): O1's AO up to date, so Bake Selected only denoises
    it from its raw bake (no rays); the noise falls, the gutter keeps its raw values, the index records the method;
    the method or the strength changed makes only the denoise stale; the panel shows only Method and Strength;
    Denoise off restores the raw bake."""
    s = bpy.context.scene.fss_ao_bake
    s.bake_ao, s.curvature, s.denoise, s.dn_method, s.dn_strength = True, False, True, 'OIDN', 1.0
    refresh()
    entry, stem = entry_of('O1')
    item = store._state['items'][stem]
    assert item['grade'] == 'UP_TO_DATE' and item['dn_grade'] == 'STALE', (item['grade'], item['dn_grade'])
    assert store.denoise_opts(bpy.context.scene) == dict(method='OIDN', strength=1.0)
    baked_at = entry['baked_at']
    select(['O1'])
    assert bpy.ops.fss.ao_bake_start(scope='AUTO', hidden=True, wait=True) == {'FINISHED'}
    refresh()
    entry, _ = entry_of('O1')
    dn = entry.get('denoise') or {}
    assert entry['baked_at'] == baked_at, 'rays were cast'
    assert dn.get('method') == 'OIDN' and dn['settings'] == store.denoise_opts(bpy.context.scene), dn
    assert store._state['items'][stem]['dn_grade'] == 'UP_TO_DATE'
    raw = core.load_master(str(FOLDER), stem, kind='ao.raw')
    den = core.load_master(str(FOLDER), stem)
    a_raw, a_den = core.noise_alpha(raw, raw['W'], raw['H']), core.noise_alpha(den, den['W'], den['H'])
    assert a_den < 0.5 * a_raw, (a_raw, a_den)
    gutter = raw['filled'] & (raw['face_map'] < 0)
    assert np.array_equal(raw['image'][gutter], den['image'][gutter]), 'gutter changed'
    # another method or strength: only the denoise is stale
    for attr, val in (('dn_method', 'FILTER'), ('dn_strength', 0.5)):
        old = getattr(s, attr)
        setattr(s, attr, val)
        refresh()
        it = store._state['items'][stem]
        assert it['grade'] == 'UP_TO_DATE' and it['dn_grade'] == 'STALE', (attr, it['grade'], it['dn_grade'])
        setattr(s, attr, old)
    refresh()
    assert store._state['items'][stem]['dn_grade'] == 'UP_TO_DATE'
    calls = []
    bpy.types.FSS_PT_ao_bake.draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
    drawn = {args[1] for name, args, _kw in calls if name == 'prop' and len(args) > 1}
    assert {'dn_method', 'dn_strength'} <= drawn and not {'dn_radius', 'dn_levels', 'dn_detail', 'dn_normal',
                                                         'dn_curv_mode', 'dn_noise'} & drawn, drawn
    # Denoise off: the raw bake back
    s.denoise = False
    refresh()
    assert bpy.ops.fss.ao_bake_start(scope='STALE', hidden=True, wait=True) == {'FINISHED'}
    refresh()
    back = core.load_master(str(FOLDER), stem)['image']
    assert np.array_equal(back, raw['image']), 'raw bake not restored'
    s.dn_method = 'OIDN'
    select([])
    print(f"PASS: test_denoise_oidn (O1 denoised by OIDN on {dn.get('device')} without rays: noise alpha {a_raw:.5f} raw, "
          f"{a_den:.5f} denoised, {dn.get('groups')} island groups, gutter kept; method and strength each make only "
          f"the denoise stale; the panel shows Method and Strength only; Denoise off restored the raw bake)")


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
    finish; in both the panel's progress updates during a bake of several tiles (two states at least while it runs),
    and the bake writes no preview of the master into the bake folder (OptiX baker decision 30: the FSS OptiX window
    shows the only one); the .blend's hash, the datablock counts and is_dirty unchanged by the bake."""
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
        # OptiX baker decision 28: Foreground with FSS OptiX shows its window, the second Blender in the background
        optix_window = mode == 'VISIBLE' and scene.fss_ao_bake.baker != 'CYCLES' and ao_bake.native.available()[0]
        assert hidden_args == (mode == 'HIDDEN' or optix_window), (mode, store._run['proc'].args)
        seen = wait_bake()
        status = store.read_status(str(FOLDER))
        assert status['state'] == 'done' and status['results'][0]['status'] == 'baked', status
        during = sorted({(s[0], s[3]) for s in seen})
        assert len(during) >= 2, during
        assert not (FOLDER / 'preview.bin').exists(), 'a preview file was written'
        assert file_hash(BLEND) == before_hash and datablocks() == before_counts and bpy.data.is_dirty == before_dirty
        out[mode] = dict(tiles=status['results'][0]['n_tiles'], progress_states_during=len(during))
    scene.fss_ao_bake.run_mode = 'HIDDEN'
    print(f"PASS: test_run_mode ({out}; .blend hash, datablock counts and is_dirty unchanged"
          + ('' if 'VISIBLE' in out else '; visible not run: FSS_AO_BAKE_TEST_VISIBLE is not 1') + ')')


def test_unsaved():
    """The bake reads a snapshot of the current state: A's vertex moved and not saved, Bake Selected makes A up to date
    (its master from the moved mesh); the .blend on disk, the datablock counts and is_dirty unchanged; the job names
    the snapshot, the log says so, and no snapshot is left in the bake folder. The vertex back, re-baked."""
    a = bpy.data.objects['A']
    co = a.data.vertices[6].co.copy()
    a.data.vertices[6].co.z += 0.001
    a.data.update()
    refresh()
    assert grade_of('A') == 'MESH'
    before_hash, before_counts, before_dirty = file_hash(BLEND), datablocks(), bpy.data.is_dirty
    select(['A'])
    assert bpy.ops.fss.ao_bake_start(scope='SELECTED', hidden=True, wait=True) == {'FINISHED'}
    status = store.read_status(str(FOLDER))
    assert status['state'] == 'done' and status['results'][0]['status'] == 'baked', status
    assert not status['results'][0]['mesh_changed_since_job'], status['results'][0]
    refresh()
    assert grade_of('A') == 'UP_TO_DATE', grade_of('A')
    assert file_hash(BLEND) == before_hash and datablocks() == before_counts and bpy.data.is_dirty == before_dirty
    with open(FOLDER / 'job.json', encoding='utf-8') as f:
        job = json.load(f)
    assert os.path.normpath(job['source']) == os.path.normpath(str(FOLDER / store.SNAPSHOT)), job.get('source')
    assert os.path.normpath(job['blend']) == os.path.normpath(str(BLEND))
    log_text = (FOLDER / 'bake.log').read_text(encoding='utf-8')
    assert '(its current state)' in log_text, 'log'
    left = [n for n in os.listdir(FOLDER) if n.startswith('snapshot.blend')]
    assert not left, left
    a.data.vertices[6].co = co
    a.data.update()
    refresh()
    assert grade_of('A') == 'MESH'
    assert bpy.ops.fss.ao_bake_start(scope='SELECTED', hidden=True, wait=True) == {'FINISHED'}
    refresh()
    assert grade_of('A') == 'UP_TO_DATE'
    select([])
    print('PASS: test_unsaved (A changed and not saved: baked from the snapshot, up to date; .blend, datablocks and '
          'is_dirty unchanged; no snapshot left; changed back and re-baked)')


def test_object_preview():
    """Decision 43 as OptiX baker decision 31 and decision 66 left it: after a bake the panel draws the bake buttons
    again (only progress and Cancel while it runs); the Object box shows no picture of the master and no line on who
    baked it; the bake writes no thumbnail (<stem>.ao.thumb)."""
    refresh()
    select(['A'])
    calls = []
    bpy.types.FSS_PT_ao_bake.draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
    assert bpy.types.FSS_PT_ao_run.poll(bpy.context)  # decision 76: Run is shown again once the bake is done
    bpy.types.FSS_PT_ao_run.draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
    ops = [args[0] for name, args, _kw in calls if name == 'operator']
    assert 'fss.ao_run' in ops, ops  # the buttons back after test_run_mode's bake
    assert not any(name == 'template_icon' for name, _a, _kw in calls), 'a picture is drawn'
    labels = [kw.get('text', args[0] if args else '') for name, args, kw in calls if name == 'label']
    assert not any(str(t).startswith(('Baked by ', 'No master baked')) for t in labels), labels
    thumbs = [n for n in os.listdir(FOLDER) if n.endswith(core.THUMB_EXT)]
    assert not thumbs, thumbs
    select([])
    print("PASS: test_object_preview (bake buttons drawn after a bake; no picture of A's master, no 'Baked by ...' "
          "line; no thumbnail written)")


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
    set_baker(scene.fss_ao_bake)
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
    part moving with it (PEG, decision 59) shades it under the scene rule, placed in each pose: its shadow stays at its
    place on the wheel, as with a custom list (SLAB, PEG), and is missing with SLAB alone. Full Quality (decision 49):
    its limits compare bakes with all the samples in every pose; Split Samples is tested in test_shared_combine."""
    build_wheel_scene()
    bpy.context.scene.fss_ao_bake.sample_quality = 'FULL'
    refresh()
    item = store._state['items'][store._state['by_object']['W']]
    assert item['mover'] and len(item['poses']) == 8 and item['poses'][0] == 0 and item['poses'][-1] == 100, item
    # decision 59: PEG moves with W (an occluder placed in each pose), SLAB moves against it (the poses)
    assert item['occluders'] == ['PEG', 'SLAB'] and item['against'] == ['SLAB'] and item['posed'] == ['PEG'], item
    p1, v1, r1, _ = bake_wheel('1 pose', poses=1)
    p8, v8, r8, seen = bake_wheel('8 poses', watch=True)
    ps, vs, rs, _ = bake_wheel('Self only (one pose, decision 40)', occluders='SELF')
    assert rs.get('n_poses', 1) == 1, rs  # Self only: nothing moves with it, one pose
    pc, vc, _r, _ = bake_wheel('Custom (SLAB, PEG), 8 poses', occluders='CUSTOM', custom=('SLAB', 'PEG'))
    pn, vn, _r, _ = bake_wheel('Custom (SLAB), 8 poses', occluders='CUSTOM', custom=('SLAB',))
    for side in ('+X', '-X'):
        assert v1[side] > 0.3, v1
        assert vn[side] <= v1[side] / 4, (side, vn[side], v1[side])  # without PEG's own shadow (it stays)
        assert ps[side].min() > 0.99 and vs[side] < 0.01, (side, ps[side])
    n_poses_seen = {s[2] for s in seen}
    poses_seen = sorted({s[1] for s in seen if s[2] == 8})
    # FSS OptiX bakes a tile's 8 poses in one request (0.1 s here): the panel shows N, and the poses it was told
    many = 2 if bpy.context.scene.fss_ao_bake.baker == 'CYCLES' else 1
    assert 8 in n_poses_seen and len(poses_seen) >= many and max(poses_seen) > 1, (n_poses_seen, poses_seen)
    # PEG on the +X face at 90 degrees: sector 4 of 16 (90 to 112.5) and 3 (67.5 to 90) darker than the same sectors
    # without it (Custom: SLAB alone), as with the custom list (SLAB, PEG); the -X face as without it
    peg_drop = float(pn['+X'][3:5].mean() - p8['+X'][3:5].mean())
    as_custom = float(np.abs(pc['+X'] - p8['+X']).max())
    other = float(np.abs(pn['-X'] - p8['-X']).max())
    assert peg_drop > 0.05 and as_custom < 0.05 and other < 0.05, (peg_drop, as_custom, other)
    # a mover whose mesh deforms between poses (bent about a static empty while HUB turns it): the current frame only
    anchor = link(bpy.data.objects.new('ANCHOR', None))
    anchor.location = (1.0, 0.0, 0.0)
    bend = plane('BEND', (1.0, 0.0, 0.05), material('SET_W', 512), 15, size=0.1)
    bend.parent = bpy.data.objects['HUB']
    mod = bend.modifiers.new('Bend', 'SIMPLE_DEFORM')
    mod.deform_method, mod.origin, mod.angle = 'BEND', anchor, math.radians(60)
    cube('BEND_BASE', (1.0, 0.0, -0.2), material('SET_W', 512), 14)  # static, so something moves against BEND
    bpy.ops.wm.save_mainfile()
    refresh()
    assert store._state['items'][store._state['by_object']['BEND']]['poses'], 'BEND has poses'
    select(['BEND'])
    console = io.StringIO()
    with contextlib.redirect_stdout(console):
        assert bpy.ops.fss.ao_bake_start(scope='SELECTED', hidden=True, wait=True) == {'FINISHED'}
    rb = store.read_status()['results'][0]
    assert rb['status'] == 'baked' and rb['n_poses'] == 1 and 'deforms' in rb.get('note', ''), rb
    # decision 74: the bake's notes in the console's report
    assert 'BEND: its mesh deforms between poses' in console.getvalue(), console.getvalue()
    # decision 41 (P59): a full turn (0 to 360 degrees over 0 to 100) is the same pose at both ends: 4 poses at 0, 25,
    # 50, 75; the wheel's 0 to 315 degrees is not: both ends kept
    turn = plane('TURN', (2.0, 0.0, 0.05), material('SET_W', 512), 15, size=0.1)
    turn.rotation_euler = (0.0, 0.0, 0.0)
    turn.keyframe_insert('rotation_euler', index=2, frame=0)
    turn.rotation_euler = (0.0, 0.0, 2 * math.pi)
    turn.keyframe_insert('rotation_euler', index=2, frame=100)
    turn.rotation_euler = (0.0, 0.0, 0.0)
    turn.fss_ao_bake.poses = 4
    cube('TURN_BASE', (2.0, 0.0, 0.0), material('SET_W', 512), 13)  # static under it: TURN moves against it
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
    ratio = {side: round(vn[side] / v1[side], 3) for side in v1}
    print(f"PASS: test_poses (variation per sector 1 pose {v1}, 8 poses without PEG {vn}: ratio {ratio} (at most 0.25); Self only "
          f"minimum {min(float(ps[s].min()) for s in ps):.4f}; the panel showed poses {poses_seen} of 8; PEG (moves "
          f"with the wheel) darkens its sectors by {peg_drop:.3f}, as the custom list within {as_custom:.3f}, the -X "
          f"face within {other:.3f}; bake 1 pose "
          f"{r1['bake_s']} s, 8 poses {r8['bake_s']} s; a deforming mover baked in the current frame, reported: "
          f"{rb['note']})")


def test_move_together():
    """Decision 59, in the wheel's file: SEAT (a plane) and FRAME (a cube on it) slide together, each keyed on its own
    (no shared parent: only the sampled frames tell), 5 cm above FLOOR (static). FRAME shades SEAT as placed (moves
    with it, placed in each pose); FLOOR moves against both, so both have poses; FLOOR has poses for them. At one pose
    SEAT bakes at the current frame, FRAME darkening it, and another current frame makes it stale."""
    scene = bpy.context.scene
    mat = material('SET_W', 512)
    seat = plane('SEAT', (5.0, 0.0, 0.05), mat, 10)
    frame_ = cube('FRAME', (5.0, 0.0, 0.08), mat, 11)
    plane('FLOOR', (5.0, 0.0, 0.0), mat, 12)
    f0 = scene.frame_current
    for o in (seat, frame_):
        y = o.location.y
        o.keyframe_insert('location', index=1, frame=0)
        o.location.y = y + 0.05
        o.keyframe_insert('location', index=1, frame=100)
        o.location.y = y
    scene.frame_set(f0)
    refresh()
    items, by = store._state['items'], store._state['by_object']
    it_s, it_f, it_fl = items[by['SEAT']], items[by['FRAME']], items[by['FLOOR']]
    assert 'FRAME' in it_s['occluders'] and 'FRAME' not in it_s['against'] and 'FRAME' in it_s['posed'], it_s
    assert it_s['against'] == ['FLOOR'] and len(it_s['poses']) == scene.fss_ao_bake.poses, it_s
    assert 'SEAT' in it_f['occluders'] and it_f['against'] == ['FLOOR'], it_f
    assert set(it_fl['against']) == {'FRAME', 'SEAT'} and it_fl['poses'], it_fl
    assert it_s['pose_range'] == (0.0, 100.0), it_s['pose_range']
    # one pose: the current frame
    seat.fss_ao_bake.poses = 1
    refresh()
    it_s = store._state['items'][store._state['by_object']['SEAT']]
    assert it_s['poses'] is None and it_s['against'] == ['FLOOR'], it_s
    select(['SEAT'])
    assert bpy.ops.fss.ao_bake_start(scope='SELECTED', hidden=True, wait=True) == {'FINISHED'}
    r = store.read_status()['results'][0]
    assert r['status'] == 'baked' and r.get('n_poses', 1) == 1, r
    refresh()
    assert grade_of('SEAT') == 'UP_TO_DATE'
    m = core.load_master(store.bake_folder(), store._state['by_object']['SEAT'])  # the wheel file's bake folder
    seat_min = float((m['image'][m['filled']] / 65535.0).min())
    assert seat_min < 0.9, seat_min  # FRAME sits on it
    scene.frame_set(f0 + 20)
    refresh()
    moved = grade_of('SEAT')
    scene.frame_set(f0)
    refresh()
    assert moved == 'SURROUNDINGS' and grade_of('SEAT') == 'UP_TO_DATE', moved
    select([])
    print(f"PASS: test_move_together (FRAME shades SEAT as placed, both posed against FLOOR over frames 0 to 100, FLOOR "
          f"posed for both; at one pose SEAT baked at the current frame, minimum {seat_min:.3f}; another current frame "
          f"made it stale, back: up to date; {store._state.get('motion_frames')} frames sampled)")


def test_resolution_choice():
    """Resolution: "ORM Texture Size" is offered only with an ORM texture (its size in the name); without one the
    choice reads the texture set's size; an existing file keeps its size whatever the choice (the panel shows it)."""
    refresh()
    ctx = bpy.context
    with_orm, without = bpy.data.materials['SET_ORM'], bpy.data.materials['SET_A']
    w, h = ao_bake.apply_mod.orm_size(with_orm)
    ids = [i[0] for i in ao_bake.resolution_items(with_orm.fss_ao_apply, ctx)]
    names = [i[1] for i in ao_bake.resolution_items(with_orm.fss_ao_apply, ctx)]
    assert ids[0] == 'ORM' and names[0] == f'ORM Texture Size ({w} x {h})', names
    a = without.fss_ao_apply
    assert ao_bake.apply_mod.orm_size(without) is None
    assert 'ORM' not in [i[0] for i in ao_bake.resolution_items(a, ctx)]
    keep = a.get('resolution', 0)
    a['resolution'] = 0  # stored "ORM Texture Size" (the old default), no ORM texture: the set's size
    assert a.resolution == str(store.texture_size(without)), (a.resolution, store.texture_size(without))
    a.resolution = '512'
    assert a.resolution == '512'
    a['resolution'] = keep
    # an existing file keeps its size: written at 256, then applied again with 512 chosen
    path = os.path.join(ao_bake.apply_mod.output_folder(ctx.scene), 'keep_size.png')
    if os.path.isfile(path):
        os.remove(path)
    first = apply_set('SET_A', file_name='keep_size.png', resolution='256')
    again = apply_set('SET_A', file_name='keep_size.png', resolution='512')
    assert tuple(first['size']) == (256, 256) and tuple(again['size']) == (256, 256), (first['size'], again['size'])
    assert ao_bake.apply_mod.existing_size(path) == (256, 256)
    calls = []
    ao_bake._draw_size(_Layout(calls), a, 'resolution', path)
    texts = [kw.get('text') for name, args, kw in calls if name == 'label']
    assert "256 x 256 (the file's size)" in texts and not [c for c in calls if c[0] == 'prop'], calls
    print(f"PASS: test_resolution_choice (with an ORM texture: {names[0]!r} offered; without: not offered, the "
          f"choice reads {store.texture_size(without)}; an existing 256 px file stays 256 with 512 chosen, the panel "
          f"shows its size)")


@recorded_padding
def test_soften_edges():
    """Decisions 46 and 58: Apply's Soften Sharp Edges, on a master built by hand (no bake): a step of three 10 mm
    faces with UVs continuous across both edges (64 px per face): top (AO 1.0) over a convex lip to a wall (0.4), the
    wall over a concave corner to a floor (0.6). Only folds shaded smooth (corner normals the same on both sides) are
    softened; hard-shaded ones stay as baked. Lip smooth: the wall brightens toward the lip as the smoothstep from 1.0
    at the edge over the width; the top, the floor and the wall at the corner keep their values; nothing gets darker; a
    width under a texel is raised to one texel. Corner smooth: its step closes by half from each side (smoothstep). A V
    of the AO at the corner (rising 40 per m away from it on both faces) is rounded as a blur of the width would:
    k x W / 3 x (1 - d / W)^3; a ramp running through the corner (rising on the wall, falling on the floor) stays."""
    s = 0.01
    quads = [  # (corners in 3D, u offset): top x -1..0 at z 0, wall z 0..-1 at x 0, floor x 0..1 at z -1
        ([(-s, 0, 0), (0, 0, 0), (0, s, 0), (-s, s, 0)], 16),
        ([(0, 0, 0), (0, 0, -s), (0, s, -s), (0, s, 0)], 80),
        ([(0, 0, -s), (s, 0, -s), (s, s, -s), (0, s, -s)], 144)]
    pos, tris, uv = [], [], []
    for corners, u0 in quads:
        b = len(pos)
        pos += corners
        uv += [(u0, 16), (u0 + 64, 16), (u0 + 64, 80), (u0, 80)]
        tris += [(b, b + 1, b + 2), (b, b + 2, b + 3)]
    pos, tris, uv = np.array(pos, float), np.array(tris), np.array(uv, float)
    uvpx = uv[tris]
    P = pos[tris]
    fn = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
    fn /= np.linalg.norm(fn, axis=1, keepdims=True)
    assert fn[0] @ [0, 0, 1] > 0.99 and fn[2] @ [1, 0, 0] > 0.99 and fn[4] @ [0, 0, 1] > 0.99, fn

    def corner_normals(lip, corner):
        """Flat (hard) everywhere; the lip's or the corner's two vertices with one normal on both sides (smooth)."""
        cn = np.repeat(fn[:, None], 3, axis=1).copy()
        for smooth, z, faces in ((lip, 0.0, range(0, 4)), (corner, -s, range(2, 6))):
            if smooth:
                n = fn[faces[0]] + fn[faces[-1]]
                for t in faces:
                    for c in range(3):
                        p = pos[tris[t, c]]
                        if abs(p[0]) < 1e-9 and abs(p[2] - z) < 1e-9:
                            cn[t, c] = n / np.linalg.norm(n)
        return cn
    m = core.build_master(pos, tris, np.repeat(fn[:, None], 3, axis=1), 4 * 64 / s, gutter=core.GUTTER,
                          order=core.ORDER, mirror_open=core.MIRROR_OPEN, fold_split=core.FOLD_SPLIT)
    owner, _cnt = core.rasterize_ids(m['muv'], m['W'], m['H'])

    def master_of(value):
        """The master with value(p3 (n,3), triangle (n,)) at each face pixel's centre."""
        ys, xs = np.nonzero(owner >= 0)
        t = owner[ys, xs]
        bc = core.barycentric_many(np.stack([xs + 0.5, ys + 0.5], axis=1), m['muv'][t])
        p3 = np.einsum('nk,nkd->nd', bc, pos[tris[t]])
        img = np.zeros(owner.shape, np.uint16)
        img[ys, xs] = np.rint(np.clip(value(p3, t), 0, 1) * 65535)
        return dict(m, image=img, filled=owner >= 0, face_map=owner)
    face_ao = np.repeat([1.0, 0.4, 0.6], 2)
    master = master_of(lambda p3, t: face_ao[t])
    W, H = 224, 96
    kw = dict(padding=4, outside_mode='tri', kmax=core.K_MAX, surface_cos=core.SURFACE_COS)
    ctx = core.copy_context(pos, tris, uvpx, master, core.K_MIN, core.K_MAX)

    def copy(mst, sc=None):
        return core.copy_master(pos, tris, uvpx, np.zeros(len(tris), np.int64), mst, (0, 0, W, H), core.K_MIN,
                                ctx=ctx, soften=sc, **kw)[:2]
    base = copy(master)[0]
    width = 0.001  # 6.4 texels
    row = 48
    written = base >= 0
    # every edge shaded hard: nothing to soften
    assert core.soften_context(pos, tris, uvpx, ctx, width, cn=corner_normals(False, False)) is None
    # the lip shaded smooth, the corner hard
    sc = core.soften_context(pos, tris, uvpx, ctx, width, cn=corner_normals(True, False))
    assert sc is not None and sc['edges'] == 1 and sc['convex'].all(), sc and sc['edges']
    soft, info = copy(master, sc)
    assert (soft[written] >= base[written] - 1e-9).all(), 'softening darkened a pixel'
    assert np.allclose(soft[row, 16:80], base[row, 16:80]) and np.allclose(base[row, 16:80], 1.0, atol=1e-3)
    assert np.allclose(soft[row, 144:208], base[row, 144:208]), 'the floor changed'
    exp = []
    for i in range(80, 144):
        d = (i + 0.5 - 80) / 64 * s
        x = min(d / width, 1.0)
        exp.append(0.4 + 0.6 * (1 - x * x * (3 - 2 * x)))
    exp = np.array(exp)
    err = float(np.abs(soft[row, 80:144] - exp).max())
    assert err < 2e-3, (err, soft[row, 80:90], exp[:10])
    assert np.allclose(soft[row, 120:144], 0.4, atol=1e-3), 'the wall at the hard corner changed'
    # a width under one texel (0.156 mm here) is raised to one texel: only the first column, its centre half way
    sc1 = core.soften_context(pos, tris, uvpx, ctx, 1e-6, cn=corner_normals(True, False))
    thin = copy(master, sc1)[0]
    assert abs(thin[row, 80] - 0.7) < 2e-3 and abs(thin[row, 81] - 0.4) < 1e-3, thin[row, 78:84]
    # the corner shaded smooth, the lip hard: the step 0.4 | 0.6 closes by half from each side
    scc = core.soften_context(pos, tris, uvpx, ctx, width, cn=corner_normals(False, True))
    assert scc is not None and scc['edges'] == 1 and not scc['convex'].any()
    step = copy(master, scc)[0]
    assert np.allclose(step[row, 16:120], base[row, 16:120]), 'the top or the wall away from the corner changed'
    err_step = 0.0
    for i in range(120, 168):
        d = abs(i + 0.5 - 144) / 64 * s
        x = min(d / width, 1.0)
        want = (0.4 + 0.1 * (1 - x * x * (3 - 2 * x))) if i < 144 else (0.6 - 0.1 * (1 - x * x * (3 - 2 * x)))
        err_step = max(err_step, abs(float(step[row, i]) - want))
    assert err_step < 2e-3, (err_step, step[row, 138:150])
    # a V at the corner is rounded; a ramp through it stays
    k = 40.0

    def dist(p3, t):
        return np.where(t < 4, p3[:, 2] + s, p3[:, 0])  # from the corner line, on the wall (t 2, 3) and the floor
    vee = master_of(lambda p3, t: 0.3 + k * dist(p3, t))
    ramp = master_of(lambda p3, t: 0.5 + np.where(t < 4, k, -k) * dist(p3, t))
    err_v, err_r, peak = 0.0, 0.0, 0.0
    for mst, is_vee in ((vee, True), (ramp, False)):
        b0, s0 = copy(mst)[0], copy(mst, scc)[0]
        for i in range(132, 156):
            d = abs(i + 0.5 - 144) / 64 * s
            x = min(d / width, 1.0)
            got = float(s0[row, i] - b0[row, i])
            if is_vee:
                want = k * width / 3 * (1 - x) ** 3
                err_v = max(err_v, abs(got - want))
                peak = max(peak, got)
            else:
                err_r = max(err_r, abs(got))
    assert err_v < 2e-3 and peak > 0.01, (err_v, peak)
    assert err_r < 2e-3, err_r
    # the copy in C++ (apply-native-copy journal; decision 6: as the numpy copy gave it, recorded), unsoftened and
    # softened, the same at 1, 12 and all threads
    n_bits = 0
    for i_copy, (mst, sc_) in enumerate(((master, None), (master, sc), (master, sc1), (master, scc), (vee, scc),
                                         (ramp, scc))):
        tisl = np.zeros(len(tris), np.int64)
        ref = core.copy_master(pos, tris, uvpx, tisl, mst, (0, 0, W, H), core.K_MIN, ctx=ctx, soften=sc_, threads=1,
                               **kw)
        REF.check(f'soften_edges/{i_copy}', ref[0], ref[1]['softened_px'])
        for t in (12, ALL_THREADS):
            got = core.copy_master(pos, tris, uvpx, tisl, mst, (0, 0, W, H), core.K_MIN, ctx=ctx, soften=sc_,
                                   threads=t, **kw)
            assert np.array_equal(ref[0].view(np.uint64), got[0].view(np.uint64)), (sc_ is not None, t)
            assert ref[1]['softened_px'] == got[1]['softened_px'] and got[1]['copy'] == 'native', t
        n_bits += int((ref[0] >= 0).sum())
    print(f"PASS: test_soften_edges (hard edges: none softened; smooth lip: wall vs smoothstep max error {err:.5f}, "
          f"top, floor and the hard corner unchanged, {info['softened_px']} px brightened; at a width under a texel: "
          f"one column, {thin[row, 80]:.3f}; smooth corner: step closed by half within {err_step:.5f}; V rounded by "
          f"up to {peak:.4f} within {err_v:.5f} of the blur; ramp through the corner kept within {err_r:.5f}; the C++ "
          f"copy as recorded and at 1, 12 and {ALL_THREADS} threads bit-identical on {n_bits} px of 6 copies, 5 "
          f"softened)")


def test_soften_thin_faces():
    """Decision 103: Soften at a concave corner whose floor has a flat or a thin triangle at the fold, on a master
    built by hand (no bake). A wall (x 0, AO 0.4) over a smooth concave corner to a floor (z -10 mm, AO 0.6); the
    corner line carries a middle vertex M, so the floor's fan has the triangle A-B-M along it: flat (M on the line, as
    an n-gon's fan over corners in a line) or 2 um thin (M lifted). Flat: its edges are no folds (soften_context);
    thin: the concave slopes need a step of SOFT_SLOPE_MIN_STEP of the width (the DLL), else the half difference
    alone. Every softened value stays between the two faces' 0.4 and 0.6 (before: 0 and 1 where the step was 1 nm).
    With the flat triangle's folds kept (core.SOFT_FLAT 0) the values are recorded, not tested: the flat triangle has
    no pixels of its own in the master, so even the half difference reads none of its value."""
    s = 0.01
    width = 0.001
    found = {}
    for case, lift in (('flat', 0.0), ('thin', 2e-6)):
        A, B, M = (0, 0, -s), (0, s, -s), (0, s / 2, -s + lift)
        At, Bt, C, D = (0, 0, 0), (0, s, 0), (s, s, -s), (s, 0, -s)
        pos = np.array([A, B, M, At, Bt, C, D], float)
        iA, iB, iM, iAt, iBt, iC, iD = range(7)
        # the wall (A' A M, A' M B, A' B B'), the floor (A D C, A C B) and the triangle along the corner (A B M)
        tris = np.array([(iAt, iA, iM), (iAt, iM, iB), (iAt, iB, iBt), (iA, iD, iC), (iA, iC, iB), (iA, iB, iM)])

        def uv_of(p):  # the wall and the floor unfolded across the corner line, 64 px per 10 mm
            u = 80 + (p[0] / s * 64 if p[2] <= -s + 1e-5 and p[0] > 1e-9 else -(p[2] + s) / s * 64)
            return (u, 16 + p[1] / s * 64)
        uvpx = np.array([[uv_of(pos[i]) for i in t] for t in tris], float)
        P = pos[tris]
        fn = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
        fn /= np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-30)
        m = core.build_master(pos, tris, np.repeat(fn[:, None], 3, axis=1), 4 * 64 / s, gutter=core.GUTTER,
                              order=core.ORDER, mirror_open=core.MIRROR_OPEN, fold_split=core.FOLD_SPLIT)
        owner, _cnt = core.rasterize_ids(m['muv'], m['W'], m['H'])
        img = np.zeros(owner.shape, np.uint16)
        img[owner >= 0] = np.where(owner[owner >= 0] < 3, 0.4, 0.6) * 65535
        master = dict(m, image=img, filled=owner >= 0, face_map=owner)
        W, H = 224, 96
        kw = dict(padding=4, outside_mode='tri', kmax=core.K_MAX, surface_cos=core.SURFACE_COS)
        ctx = core.copy_context(pos, tris, uvpx, master, core.K_MIN, core.K_MAX)
        base = core.copy_master(pos, tris, uvpx, np.zeros(len(tris), np.int64), master, (0, 0, W, H), core.K_MIN,
                                ctx=ctx, **kw)[0]
        for flat_rule in (True, False):
            old = core.SOFT_FLAT
            core.SOFT_FLAT = old if flat_rule else 0.0
            try:
                sc = core.soften_context(pos, tris, uvpx, ctx, width)
            finally:
                core.SOFT_FLAT = old
            with_flat = sc is not None and bool((sc['E'][:, [0, 3]] == 5).any())
            if case == 'flat' and flat_rule:
                assert not with_flat, 'a fold at the flat triangle'
            if case == 'thin':
                assert with_flat, 'the thin triangle is no flat one'
            got = base if sc is None else core.copy_master(pos, tris, uvpx, np.zeros(len(tris), np.int64), master,
                                                           (0, 0, W, H), core.K_MIN, ctx=ctx, soften=sc, **kw)[0]
            w = got >= 0
            lo, hi = float(got[w].min()), float(got[w].max())
            if case == 'thin' or flat_rule:  # the flat triangle's folds kept: recorded (it reads no pixels of its own)
                assert lo >= 0.4 - 2e-3 and hi <= 0.6 + 2e-3, (case, flat_rule, lo, hi)
            found[f"{case}{'' if flat_rule else ' (folds kept)'}"] = (sc['edges'] if sc else 0, round(lo, 3),
                                                                      round(hi, 3))
    print(f'PASS: test_soften_thin_faces (folds, softened min and max: {found})')
    return found


ALL_THREADS = os.cpu_count() or 2  # decision 6: the C++ parts at 1, 12 and all threads


@recorded_padding
def test_native_copy():
    """Apply-native-copy journal, finish lines 1, 3 and 4, and decision 6: Apply's copy in C++ (fss_ao_copy.dll). Each
    Apply (grey, ORM layout with green and blue copied, SET_B at 512 px, into the ORM slot texture, per object over a
    random file, the curvature, green and blue resampled at 512 px), with Soften Sharp Edges off and on (1 mm), the
    master paged as Apply reads it, paged with a cache of 2 tiles and whole in memory (the C++ copy reads the page
    files mapped, not through the cache: no tile loads): the DLL at 12, 1 and all threads writes the same file, its pixels and counts those the numpy copy gave (recorded before
    decision 6 removed it), its bytes those the C++ writer gave then; the report says the C++ copy and its threads, and
    the C++ raster, dilation, UV islands and Soften ran (counted)."""
    nat = core.native_copy()
    assert nat.unavailable() is None, nat.unavailable()
    refresh()
    s = bpy.context.scene.fss_ao_bake
    old = (s.threads, s.soften_edges, s.soften_width)
    keep = WORK / 'native_copy'
    if keep.exists():
        shutil.rmtree(keep)
    keep.mkdir(parents=True)
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(17)
    po_base = rng.integers(0, 65536, (SIZE, SIZE, 3))
    orm_path = WORK / 'orm16.png'
    orm_bytes = orm_path.read_bytes()
    opened = core.open_master

    def tiny(folder, stem, cache_bytes=None, kind='ao', threads=None):
        out = opened(folder, stem, cache_bytes=1, kind=kind, threads=threads)
        for p in out.get('pages', ()):  # a cache of 2 tiles: masters of 3 or 4 tiles drop and read tiles again
            p.cap = 2
            p.cache = np.empty((2, p.T * p.T), p.dtype)
            p.tile_in = np.full(2, -1, np.int64)
            p.used = np.zeros(2, np.int64)
            p.slot_of[:] = -1
        return out

    def whole(folder, stem, cache_bytes=None, kind='ao', threads=None):
        out = core.load_master(folder, stem, kind)
        out['close'] = lambda: None
        return out
    cases = [('grey', 'SET_A', 'ao', dict(file_name='nc_grey.png'), None),
             ('orm_layout', 'SET_ORM', 'ao', dict(file_name='nc_orm_layout.png', layout='ORM', green_blue='COPY'),
              None),
             ('cubes_512', 'SET_B', 'ao', dict(file_name='nc_cubes_512.png', resolution='512'), None),
             ('orm_slot', 'SET_ORM', 'ao', dict(target='ORM'), None),
             ('per_object', 'SET_PO', 'ao', dict(file_name='nc_po.png'), ['Q1']),
             ('per_object_gb', 'SET_GB', 'ao', dict(file_name='nc_gb.png'), ['G2']),
             ('curvature', 'SET_B', 'curv', dict(), None),
             # Session 11: green and blue resampled inside islands (uv_islands, island_labels)
             ('orm_resampled', 'SET_GB', 'ao', dict(file_name='nc_gb_512.png', layout='ORM', green_blue='COPY',
                                                    resolution='512'), None)]
    # Session 11: the C++ raster, dilation, UV islands and Soften counted, to see which code ran
    calls = dict(raster_ids=0, dilate=0, soften=0, uv_islands=0)
    real = {n: getattr(nat, n) for n in calls}

    def counted(n):
        def fn(*a, **k):
            calls[n] += 1
            return real[n](*a, **k)
        return fn
    for n in calls:
        setattr(nat, n, counted(n))
    totals = dict.fromkeys(calls, 0)

    def run(label, name, kind, kw, objects, threads):
        calls.update({k: 0 for k in calls})
        s.threads = threads
        mat = bpy.data.materials[name]
        target = ApplySettings(**kw)
        if kind == 'ao' and target.target == 'FILE' and objects:
            write_png(OUT / target.file_name, po_base)
        if target.target == 'ORM':
            orm_path.write_bytes(orm_bytes)
        rep = ao_bake_apply.apply_set(bpy.context, mat, [bpy.data.objects[n] for n in objects] if objects else None,
                                      target, kind=kind)
        assert not rep.get('error') and rep['copied'], rep
        ran = {k: v for k, v in calls.items() if v}
        # the raster and the dilation always, Soften only when on, the UV islands when needed
        assert ran.get('raster_ids') and ran.get('dilate'), (label, ran)
        assert not ran.get('soften') or (s.soften_edges and kind == 'ao'), (label, ran)
        assert bool(ran.get('uv_islands')) == (label.startswith(('orm_resampled', 'curvature'))), (label, ran)
        for k_, v_ in ran.items():
            totals[k_] += v_
        want = f"C++ ({threads} thread{'s' if threads != 1 else ''})"
        assert rep['copy'] == want and rep['png'] == want, (rep['copy'], rep['png'], want)
        assert not any(x.startswith(('  copy:', '  open:', '  png:')) for x in ao_bake_apply.report_lines(rep))
        dst = keep / f'{label}_{threads}.png'
        shutil.copy2(rep['path'], dst)
        return rep, dst.read_bytes(), dst
    results = {}
    n_files = 0
    try:
        for soften in (False, True):
            s.soften_edges, s.soften_width = soften, 0.001
            for mode, opener in (('paged', opened), ('tiny', tiny), ('whole', whole)):
                if mode != 'paged' and not soften:
                    continue
                core.open_master = opener
                try:
                    for label, name, kind, kw, objects in cases:
                        tag = f'{label}_{mode}_{"soft" if soften else "plain"}'
                        reps = {threads: run(tag, name, kind, kw, objects, threads)
                                for threads in (12, 1, ALL_THREADS)}
                        n_files += len(reps)
                        ref = reps[12]
                        # decision 6: the numpy copy's pixels and counts, the C++ writer's bytes, as recorded
                        REF.check(f'native_copy/{tag}', png_pixels(ref[2]), ref[0]['written_px'],
                                  ref[0]['softened_px'])
                        REF.check(f'native_copy/{tag}/cpp_file', ref[1])
                        for t, r in reps.items():
                            assert r[1] == ref[1], (tag, f'C++ at 12 and {t} threads')
                            assert r[0]['written_px'] == ref[0]['written_px'] > 0, (tag, t)
                            assert r[0]['softened_px'] == ref[0]['softened_px'], (tag, t)
                        results[tag] = (ref[1], ref[0].get('page_loads'), ref[0]['written_px'])
                finally:
                    core.open_master = opened
        # the same file paged, through a cache of 2 tiles and whole
        for label, *_r in cases:
            assert len({results[f'{label}_{m}_soft'][0] for m in ('paged', 'tiny', 'whole')}) == 1, label
        po_loads = (results['per_object_paged_soft'][1], results['per_object_tiny_soft'][1])
    finally:
        s.threads, s.soften_edges, s.soften_width = old
        orm_path.write_bytes(orm_bytes)
        for n, fn in real.items():
            setattr(nat, n, fn)
    assert totals['raster_ids'] and totals['dilate'] and totals['uv_islands'], totals
    print(f"PASS: test_native_copy, Session 11 (the C++ calls {totals})")
    print(f"PASS: test_native_copy ({len(results)} Apply configurations x C++ 12, 1 and {ALL_THREADS} threads = "
          f"{n_files} files: "
          f"byte-identical per configuration, the pixels and counts of the numpy copy and the bytes of the C++ writer "
          f"as recorded ({sum(r[2] for r in results.values())} px written); paged, a 2-tile cache (SET_PO tile loads "
          f"{po_loads[0]} and {po_loads[1]}: the copy reads the mapped page files) and whole the same file)")


@recorded_padding
def test_native_open():
    """Apply-native-copy journal, Session 4, finish lines 1 to 3, and decision 6: the master opened by the DLL
    (fss_ao_copy_open_master). Every master of the suite (each kind it has: AO, curvature, raw) opened at 1, 12 and
    all threads writes the page files the Python opening wrote (recorded before decision 6 removed it). Each Apply of
    test_native_copy's configurations (Soften Sharp Edges off and on) writes the same file at 12, 1 and all threads as
    recorded, and its report says 'C++ (n threads)' without a console line."""
    nat = core.native_copy()
    assert nat.unavailable() is None, nat.unavailable()
    refresh()
    folder = str(FOLDER)
    s = bpy.context.scene.fss_ao_bake
    old = (s.threads, s.soften_edges, s.soften_width)

    def pages(stem, kind, threads):
        m = core.open_master(folder, stem, kind=kind, threads=threads)
        try:
            data = []
            for p in m['pages']:
                with open(p.path, 'rb') as f:
                    data.append(f.read())
        finally:
            m['close']()
        return data, m['open']
    # every master, each kind it has
    index = store.read_index(folder, use_cache=False)
    n_pages, n_bytes, kinds = 0, 0, set()
    for stem in index['masters']:
        for kind in ('ao', 'curv', 'ao.raw'):
            if not core.master_paths(folder, stem, kind)[0].endswith('.jxl') or \
                    not os.path.isfile(core.master_paths(folder, stem, kind)[0]):
                continue
            ref = None
            for threads in (1, 12, ALL_THREADS):
                got, how = pages(stem, kind, threads)
                assert how == f"C++ ({threads} thread{'s' if threads != 1 else ''})", how
                if ref is None:
                    ref = got
                    REF.check(f'native_open/pages/{stem}/{kind}', ref[0], ref[1])
                assert got[0] == ref[0] and got[1] == ref[1], (stem, kind, threads)
                n_pages += 2
                n_bytes += len(got[0]) + len(got[1])
            kinds.add(kind)
    n_masters = len(index['masters'])
    # Apply
    keep = WORK / 'native_open'
    if keep.exists():
        shutil.rmtree(keep)
    keep.mkdir(parents=True)
    OUT.mkdir(parents=True, exist_ok=True)
    po_base = np.random.default_rng(19).integers(0, 65536, (SIZE, SIZE, 3))
    orm_path = WORK / 'orm16.png'
    orm_bytes = orm_path.read_bytes()
    cases = [('grey', 'SET_A', 'ao', dict(file_name='no_grey.png'), None),
             ('orm_layout', 'SET_ORM', 'ao', dict(file_name='no_orm_layout.png', layout='ORM', green_blue='COPY'),
              None),
             ('cubes_512', 'SET_B', 'ao', dict(file_name='no_cubes_512.png', resolution='512'), None),
             ('orm_slot', 'SET_ORM', 'ao', dict(target='ORM'), None),
             ('per_object', 'SET_PO', 'ao', dict(file_name='no_po.png'), ['Q1']),
             ('per_object_gb', 'SET_GB', 'ao', dict(file_name='no_gb.png'), ['G2']),
             ('curvature', 'SET_B', 'curv', dict(), None)]

    def run(label, name, kind, kw, objects, threads):
        s.threads = threads
        target = ApplySettings(**kw)
        if kind == 'ao' and target.target == 'FILE' and objects:
            write_png(OUT / target.file_name, po_base)
        if target.target == 'ORM':
            orm_path.write_bytes(orm_bytes)
        rep = ao_bake_apply.apply_set(bpy.context, bpy.data.materials[name],
                                      [bpy.data.objects[n] for n in objects] if objects else None, target, kind=kind)
        assert not rep.get('error') and rep['copied'], rep
        dst = keep / f'{label}.png'
        shutil.copy2(rep['path'], dst)
        return rep, dst.read_bytes(), dst
    n_apply, px = 0, 0
    try:
        for soften in (False, True):
            s.soften_edges, s.soften_width = soften, 0.001
            for label, name, kind, kw, objects in cases:
                tag = f'{label}_{"soft" if soften else "plain"}'
                ref = None
                for threads in (12, 1, ALL_THREADS):
                    rep, data, dst = run(f'{tag}_cpp_{threads}', name, kind, kw, objects, threads)
                    assert rep['open'] == f"C++ ({threads} thread{'s' if threads != 1 else ''})", rep['open']
                    assert not any('open:' in x for x in ao_bake_apply.report_lines(rep))
                    if ref is None:
                        ref = (rep, data, dst)
                        # decision 6: the file the Python opening's Apply wrote (the C++ writer), as recorded
                        REF.check(f'native_open/{tag}', data, rep['written_px'], rep['softened_px'])
                    assert data == ref[1], (tag, threads)
                    assert rep['written_px'] == ref[0]['written_px'] > 0 and rep['softened_px'] == \
                        ref[0]['softened_px'], (tag, threads)
                    n_apply += 1
                px += ref[0]['written_px']
    finally:
        s.threads, s.soften_edges, s.soften_width = old
        orm_path.write_bytes(orm_bytes)
    left = [f for f in os.listdir(FOLDER) if f.endswith(('.page', '.mappage', '.tmp', '.raw'))]
    assert not left, left
    print(f"PASS: test_native_open ({n_masters} masters, kinds {sorted(kinds)}: {n_pages} page files of the DLL at 1, "
          f"12 and {ALL_THREADS} threads byte-identical and as recorded ({n_bytes / 2 ** 20:.1f} MiB); {n_apply} "
          f"Applies of {len(cases) * 2} configurations at 12, 1 and {ALL_THREADS} threads byte-identical, as recorded "
          f"({px} px written); no "
          f"scratch file left)")


@recorded_padding
def test_native_png():
    """Apply-native-copy journal, Session 7 (decision 4), finish lines 1 and 4, and decision 6: Apply's texture
    written by the C++ PNG writer for each of test_native_copy's configurations (Soften Sharp Edges off): its pixels
    those the Python writer wrote (recorded before decision 6 removed it), the same bytes at 12, 1 and all threads; the
    report says 'C++ (n threads)' without a console line. read_png reads the suite's ORM texture with the C++ reader."""
    nat = core.native_copy()
    assert nat.unavailable() is None, nat.unavailable()
    refresh()
    s = bpy.context.scene.fss_ao_bake
    old = (s.threads, s.soften_edges)
    keep = WORK / 'native_png'
    if keep.exists():
        shutil.rmtree(keep)
    keep.mkdir(parents=True)
    OUT.mkdir(parents=True, exist_ok=True)
    po_base = np.random.default_rng(23).integers(0, 65536, (SIZE, SIZE, 3))
    orm_path = WORK / 'orm16.png'
    orm_bytes = orm_path.read_bytes()
    cases = [('grey', 'SET_A', 'ao', dict(file_name='np_grey.png'), None),
             ('orm_layout', 'SET_ORM', 'ao', dict(file_name='np_orm_layout.png', layout='ORM', green_blue='COPY'),
              None),
             ('cubes_512', 'SET_B', 'ao', dict(file_name='np_cubes_512.png', resolution='512'), None),
             ('orm_slot', 'SET_ORM', 'ao', dict(target='ORM'), None),
             ('per_object', 'SET_PO', 'ao', dict(file_name='np_po.png'), ['Q1']),
             ('per_object_gb', 'SET_GB', 'ao', dict(file_name='np_gb.png'), ['G2']),
             ('curvature', 'SET_B', 'curv', dict(), None)]

    def run(label, name, kind, kw, objects, threads):
        s.threads = threads
        target = ApplySettings(**kw)
        if kind == 'ao' and target.target == 'FILE' and objects:
            write_png(OUT / target.file_name, po_base)
        if target.target == 'ORM':
            orm_path.write_bytes(orm_bytes)
        rep = ao_bake_apply.apply_set(bpy.context, bpy.data.materials[name],
                                      [bpy.data.objects[n] for n in objects] if objects else None, target, kind=kind)
        assert not rep.get('error') and rep['copied'], rep
        dst = keep / f'{label}.png'
        shutil.copy2(rep['path'], dst)
        return rep, dst
    n_cfg, px, sizes = 0, 0, []
    try:
        s.soften_edges = False
        for label, name, kind, kw, objects in cases:
            cpp = {}
            for threads in (12, 1, ALL_THREADS):
                rep, dst = run(f'{label}_cpp_{threads}', name, kind, kw, objects, threads)
                want = f"C++ ({threads} thread{'s' if threads != 1 else ''})"
                assert rep['png'] == want and rep['copy'] == want and rep['open'] == want, rep
                assert not any(x.startswith('  png:') for x in ao_bake_apply.report_lines(rep))
                if not cpp:
                    REF.check(f'native_png/{label}', png_pixels(dst), rep['written_px'])
                    written = rep['written_px']
                assert rep['written_px'] == written > 0, (label, threads)
                cpp[threads] = dst.read_bytes()
            assert all(v == cpp[12] for v in cpp.values()), label
            sizes.append(len(cpp[12]))
            n_cfg += 1
            px += written
        # the reader: the ORM texture by the C++ reader (2 threads at most: one decompresses, one unfilters)
        orm_path.write_bytes(orm_bytes)
        how = {}
        vals, bits, ct = core.read_png(str(orm_path), how=how)
        assert how['read'] == 'C++ (2 threads)' and bits == 16 and ct == 2, (how, bits, ct)
        assert np.array_equal(vals, png_pixels(orm_path)[::-1])
    finally:
        s.threads, s.soften_edges = old
        orm_path.write_bytes(orm_bytes)
    print(f"PASS: test_native_png ({n_cfg} Apply configurations, {px} px written: the C++ writer at 12, 1 and "
          f"{ALL_THREADS} threads "
          f"byte-identical, its pixels the Python writer's as recorded; {sum(sizes)} bytes; the ORM texture read by "
          f"the C++ reader)")


COMPOSE_FILES = ('.ao.jxl', '.ao.map', '.ao.npz', '.ao.raw.jxl', '.curv.jxl')


def test_native_compose():
    """Bake-post-native journal, finish lines 2 and 4, and decision 6: every master of the suite's scene baked in tiles
    of 64 px (bands of several strips) with the C++ composition and map writer at 12, 1 and all threads: each master's
    files byte-identical and those the Python composition wrote (recorded before decision 6 removed it), its index
    entry the same but its times; bake.log says 'composed by C++ (n threads)'. The bake folder is restored afterwards,
    so the later tests see the masters they had."""
    nat = core.native_copy()
    assert nat.unavailable() is None, nat.unavailable()
    refresh()
    folder = Path(store.bake_folder())
    backup = WORK / 'native_compose_backup'
    if backup.exists():
        shutil.rmtree(backup)
    shutil.copytree(folder, backup)
    s = bpy.context.scene.fss_ao_bake
    old_threads = s.threads
    objs = sorted({it['object'] for it in store._state['items'].values()} & set(bpy.data.objects.keys()))
    keys = sorted(store._state['items'])

    def bake(threads):
        s.threads = threads
        select(objs)
        res = bpy.ops.fss.ao_bake_start(scope='SELECTED', hidden=True, wait=True, tile=64)
        assert res == {'FINISHED'}, res
        status = store.read_status(str(folder))
        assert status['state'] == 'done' and all(r['status'] == 'baked' for r in status['results']), status
        files = {}
        for k in keys:
            for ext in COMPOSE_FILES:
                p = folder / (k + ext)
                if p.is_file():
                    files[(k, ext)] = file_hash(p)
        index = store.read_index(str(folder), use_cache=False)['masters']
        entries = {}
        for k in keys:
            e = json.loads(json.dumps(index[k]))
            for drop in ('times', 'baked_at'):
                e.pop(drop, None)
            e['tiles'] = {a: b for a, b in e['tiles'].items() if a not in ('in_use_gb', 'peak_working_set_gb',
                                                                          'budget_gb', 'estimate_gb')}
            # the JPEG XL encoder's seconds, and its threads (the setting this test changes)
            e['image'] = {a: b for a, b in (e.get('image') or {}).items() if a not in ('seconds', 'threads')}
            for sub in ('curvature', 'denoise'):
                if isinstance(e.get(sub), dict):
                    e[sub] = {a: b for a, b in e[sub].items() if 'second' not in a}
            entries[k] = e
        log = (folder / 'bake.log').read_text(encoding='utf-8')
        start = log.rfind('] baker ')  # this job's lines
        lines = [x.split('] ', 1)[-1].strip() for x in log[log.rfind('\n', 0, start) + 1:].splitlines()
                 if ': composed by ' in x]
        return dict(files=files, entries=entries, lines=lines, n=len(status['results']))
    runs = {}
    try:
        runs['C++ 12'] = bake(12)
        runs['C++ 1'] = bake(1)
        runs['C++ all'] = bake(ALL_THREADS)
    finally:
        s.threads = old_threads
        shutil.rmtree(folder)
        shutil.copytree(backup, folder)
        refresh()
    ref = runs['C++ 12']
    for k in keys:  # decision 6: each master's files as the Python composition wrote them
        REF.check(f'native_compose/{k}', {ext: h for (kk, ext), h in sorted(ref['files'].items()) if kk == k})
    assert ref['files'] and ref['n'] == len(keys) and len(ref['lines']) == len(keys), (len(ref['files']), ref['n'],
                                                                                       ref['lines'][:3])
    for label, run in runs.items():
        diff = sorted(k for k in set(ref['files']) | set(run['files']) if ref['files'].get(k) != run['files'].get(k))
        assert not diff, (label, diff[:6])
        bad = {k: sorted(f for f in set(ref['entries'][k]) | set(run['entries'][k])
                         if ref['entries'][k].get(f) != run['entries'][k].get(f)) for k in keys}
        bad = {k: v for k, v in bad.items() if v}
        assert not bad, (label, bad, [(f, ref['entries'][k].get(f), run['entries'][k].get(f))
                                      for k, v in list(bad.items())[:1] for f in v])
    def by(n):
        return f"C++ ({n} thread{'s' if n != 1 else ''})"
    want = {'C++ 12': f'composed by {by(12)} in ', 'C++ 1': f'composed by {by(1)} in ',
            'C++ all': f'composed by {by(ALL_THREADS)} in '}
    maps = {'C++ 12': f'the map written by {by(12)}', 'C++ 1': f'the map written by {by(1)}',
            'C++ all': f'the map written by {by(ALL_THREADS)}'}
    for label, run in runs.items():
        assert len(run['lines']) == len(keys) and all(want[label] in x and maps[label] in x for x in run['lines']), \
            (label, run['lines'][:2])
    print(f"PASS: test_native_compose ({len(keys)} masters in tiles of 64 px, {len(ref['files'])} files: the C++ "
          f"composition at 12, 1 and {ALL_THREADS} threads byte-identical and as recorded, the index entries the same "
          f"but their "
          f"times; the log: {' / '.join(r['lines'][0].split(': ', 1)[1] for r in runs.values())}; the bake folder "
          f"restored)")


AO_OPERATORS = ('ao_bake_refresh', 'ao_run', 'ao_object_step', 'ao_bake_start', 'ao_bake_select', 'ao_bake_tree_set',
                'ao_bake_detect', 'ao_bake_tree_fold', 'ao_bake_tree_select', 'ao_bake_tree_highlight',
                'ao_bake_tree_select_all', 'ao_bake_tree_highlight_all', 'ao_bake_tree_toggle',
                'ao_bake_custom_occluders', 'ao_apply')  # every AO Bake operator but the two Cancels


def md5_file(path):
    return hashlib.md5(Path(path).read_bytes()).hexdigest()


def test_unavailable():
    """Apply-native-copy decision 6: fss_ao_copy.dll and libjxl are required. With the DLL moved away, and with
    libjxl's jxl.dll moved away (each put back and its md5 checked): the panel's first line says why (icon ERROR), the
    AO Bake operators' polls refuse with that reason (their buttons greyed), a job started anyway (the Bake
    operator's execute, past its poll) fails in the second Blender with the reason in the log and the status and
    leaves the masters as they were, and Apply refuses with an error and writes nothing; back in place, all runs."""
    nat = core.native_copy()
    lib = core.jxl()
    refresh()
    folder = str(FOLDER)
    st = bpy.context.window_manager.fss_ao_bake_state
    entry, stem = entry_of('A')
    masters = {p: file_hash(p) for p in core.master_paths(folder, stem)}
    select(['A'])
    moves = {'DLL': os.path.join(nat.LIB_DIR, nat.DLL), 'libjxl': os.path.join(lib.LIB_DIR, 'jxl.dll')}
    md5 = {k: md5_file(p) for k, p in moves.items()}
    md5_jxl = {n: md5_file(os.path.join(lib.LIB_DIR, n)) for n in lib.DLLS}
    seen = {}
    for what, path in moves.items():
        away = path + '.away'
        os.rename(path, away)
        try:
            nat.reset()
            lib.reset()
            why = nat.unavailable()
            assert why and 'missing' in why and os.path.basename(path) in why, (what, why)
            assert why.startswith(f'{nat.DLL} could not be loaded' if what == 'DLL' else
                                  'the JPEG XL library (libjxl) could not be loaded'), why
            # the panel: one line with the reason first; the buttons greyed by the polls
            calls = []
            bpy.types.FSS_PT_ao_bake.draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
            labels = [(kw.get('text'), kw.get('icon')) for name, _a, kw in calls if name == 'label']
            assert labels[0] == (f'Not available: {why}', 'ERROR'), labels[:3]
            assert sum(1 for t, _i in labels if t and why in t) == 1, labels
            polls = {n: getattr(bpy.ops.fss, n).poll() for n in AO_OPERATORS}
            assert not any(polls.values()), polls
            try:
                bpy.ops.fss.ao_bake_refresh()
                raise AssertionError('Refresh ran')
            except RuntimeError as exc:
                refused = str(exc)
            assert f'AO Bake not available: {why}' in refused, refused
            # a job started anyway fails in the second Blender, the reason in the log and the status
            reports = []
            op = SimpleNamespace(scope='SELECTED', hidden=True, wait=True, test_delay=0.0, tile=0, test_tile_delay=0.0,
                                 report=lambda kind, msg: reports.append(msg))
            # Refresh needs the DLL too (its scene rule, bake-post-native journal Session 5): the job starts on the
            # Refresh made above, with the DLL in place
            keep, store.refresh = store.refresh, lambda context, relink=True, instances=None: store._state
            try:
                assert ao_bake.FSS_OT_AOBakeStart.execute(op, bpy.context) == {'FINISHED'}, reports
            finally:
                store.refresh = keep
            status = store.read_status(folder)
            reason = f'AO Bake not available: {why}'
            assert status['state'] == 'failed' and status['reason'] == reason, status
            assert status['results'] and all(r['status'] == 'failed' and r['reason'] == reason
                                             for r in status['results']), status['results']
            log = (FOLDER / 'bake.log').read_text(encoding='utf-8').splitlines()
            assert any(x.endswith(reason) for x in log[-3:]), log[-3:]
            assert f'failed: A ({reason})' in st.report, st.report
            assert {p: file_hash(p) for p in masters} == masters
            # Apply refuses, nothing written
            OUT.mkdir(parents=True, exist_ok=True)
            out = OUT / f'na_{what}.png'
            rep = ao_bake_apply.apply_set(bpy.context, bpy.data.materials['SET_A'], None,
                                          ApplySettings(file_name=out.name))
            assert rep.get('error') == reason and not out.exists(), rep
            seen[what] = why
        finally:
            os.rename(away, path)
            nat.reset()
            lib.reset()
        assert md5_file(path) == md5[what], (what, md5_file(path), md5[what])
    assert {n: md5_file(os.path.join(lib.LIB_DIR, n)) for n in lib.DLLS} == md5_jxl
    assert nat.unavailable() is None and lib.available()
    calls = []
    bpy.types.FSS_PT_ao_bake.draw(SimpleNamespace(layout=_Layout(calls)), bpy.context)
    assert not any('Not available' in (kw.get('text') or '') for name, _a, kw in calls if name == 'label')
    assert bpy.ops.fss.ao_bake_refresh.poll() and bpy.ops.fss.ao_bake_start.poll()
    refresh()
    assert grade_of('A') == 'UP_TO_DATE'
    rep = apply_set('SET_A', file_name='na_back.png')
    assert rep['copied'] and rep['written_px'] > 0
    print(f"PASS: test_unavailable (the DLL moved away: \"{seen['DLL']}\"; jxl.dll moved away: \"{seen['libjxl']}\"; "
          f"each: the panel's first line, {len(AO_OPERATORS)} AO operators refused by their polls, a job failed with "
          f"the reason in bake.log and status.json, the masters unchanged, Apply refused; moved back, md5s unchanged "
          f"({md5['DLL']}, jxl.dll {md5['libjxl']}), all runs again)")


# ---------------------------------------------------------------------------------------------------------------------
# Material channels (decisions 79 to 83): the albedo, roughness, metal and emissive in the master, Apply into targets
# ---------------------------------------------------------------------------------------------------------------------

CH_WORK = REPO_ROOT / 'tests' / '_work' / 'ao_bake_channels'
CH_BLEND = CH_WORK / 'channels.blend'
CH_BASE, CH_ROUGH, CH_METAL, CH_EMIS, CH_GROUP_RGB = (0.6, 0.3, 0.1), 0.3, 1.0, (0.2, 0.5, 0.9), (0.8, 0.4, 0.2)
CH_SAMPLE_COUNTS = (1, 4, 16, 64, 256)
# decision 87: three copies of a shared mesh, their emissive colours (linear) of different luminances (Rec. 709 0.270,
# 0.458, 0.251): Most Lit takes E2's, Darkest E3's; per component the highest would mix (0.9, 0.6, 0.9)
CH_E_EMIS = {'E1': (0.9, 0.1, 0.1), 'E2': (0.1, 0.6, 0.1), 'E3': (0.2, 0.2, 0.9)}
CH_E_BASE = {'E1': (0.7, 0.2, 0.2), 'E2': (0.2, 0.7, 0.2), 'E3': (0.2, 0.2, 0.7)}


def ch_material(name, base=(0.5, 0.5, 0.5), rough=0.5, metal=0.0, emis=(0.0, 0.0, 0.0), tex=None, ao_group=False,
                diffuse=False):
    """A plain Principled material built here (not the MSFS material's tree); tex: an image read through the render
    UV map (no UV Map node) into Base Color; ao_group: Base Color fed through a group named .Apply AO Group that
    halves the colour; diffuse: a Diffuse BSDF on the output, no Principled BSDF."""
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.fss_uv_texture_size = str(SIZE)
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    if diffuse:
        d = nt.nodes.new('ShaderNodeBsdfDiffuse')
        d.inputs['Color'].default_value = (*base, 1.0)
        nt.links.new(d.outputs[0], out.inputs['Surface'])
        return mat
    p = nt.nodes.new('ShaderNodeBsdfPrincipled')
    nt.links.new(p.outputs[0], out.inputs['Surface'])
    p.inputs['Base Color'].default_value = (*base, 1.0)
    p.inputs['Roughness'].default_value = rough
    p.inputs['Metallic'].default_value = metal
    p.inputs['Emission Color'].default_value = (*emis, 1.0)
    p.inputs['Emission Strength'].default_value = 3.0  # not baked: the emissive is the Emission Color's input
    colour = None
    if tex is not None:
        t = nt.nodes.new('ShaderNodeTexImage')
        t.image = tex
        colour = t.outputs['Color']
    if ao_group:
        grp = bpy.data.node_groups.new('.Apply AO Group', 'ShaderNodeTree')
        grp.interface.new_socket(name='Color', in_out='INPUT', socket_type='NodeSocketColor')
        grp.interface.new_socket(name='Occlusion', in_out='INPUT', socket_type='NodeSocketFloat')
        grp.interface.new_socket(name='Color', in_out='OUTPUT', socket_type='NodeSocketColor')
        gi, go = grp.nodes.new('NodeGroupInput'), grp.nodes.new('NodeGroupOutput')
        mul = grp.nodes.new('ShaderNodeVectorMath')
        mul.operation = 'MULTIPLY'
        mul.inputs[1].default_value = (0.5, 0.5, 0.5)
        grp.links.new(gi.outputs[0], mul.inputs[0])
        grp.links.new(mul.outputs[0], go.inputs[0])
        g = nt.nodes.new('ShaderNodeGroup')
        g.node_tree = grp
        if colour is None:
            rgb = nt.nodes.new('ShaderNodeRGB')
            rgb.outputs[0].default_value = (*base, 1.0)
            colour = rgb.outputs[0]
        nt.links.new(colour, g.inputs[0])
        colour = g.outputs[0]
    if colour is not None:
        nt.links.new(colour, p.inputs['Base Color'])
    return mat


def ch_plane(name, location, mat, uv=None, n=4, size=0.2):
    """plane() with UVMap (the texture set's, active) covering uv=(u0, v0, u1, v1), and a second map TexUV with the
    same coordinates as the render UV map (an Image Texture node without a UV Map node reads it)."""
    obj = plane(name, location, mat, 0, size=size, n=n)
    me = obj.data
    u0, v0, u1, v1 = uv or (0.1, 0.1, 0.9, 0.9)
    lay = me.uv_layers['UVMap']
    for poly in me.polygons:
        for li in poly.loop_indices:
            x, y, _z = me.vertices[me.loops[li].vertex_index].co
            lay.data[li].uv = (u0 + (x / size + 0.5) * (u1 - u0), v0 + (y / size + 0.5) * (v1 - v0))
    tex = me.uv_layers.new(name='TexUV')
    co = np.empty(len(me.loops) * 2, np.float32)
    lay.data.foreach_get('uv', co)
    tex.data.foreach_set('uv', co)
    me.uv_layers.active = lay
    tex.active_render = True
    return obj


def build_channel_scene():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    if CH_WORK.exists():
        shutil.rmtree(CH_WORK)
    CH_WORK.mkdir(parents=True)
    scene = bpy.context.scene
    scene.frame_set(1)
    s = scene.fss_ao_bake
    s.distance, s.samples, s.threads, s.padding, s.curv_padding = 0.1, 16, 12, PAD, PAD
    s.curv_width = 0.005
    set_baker(s)
    s.output_folder = str(CH_WORK / 'out')
    rng = np.random.default_rng(79)
    # the textures in CH_CONST's slots (Target ORM Texture writes them in place): base colour RGBA 16-bit, ORM RGB
    # 16-bit, emissive RGB 8-bit
    write_png(CH_WORK / 'base.png', rng.integers(0, 65536, (SIZE, SIZE, 4)))
    write_png(CH_WORK / 'orm.png', rng.integers(0, 65536, (SIZE, SIZE, 3)))
    write_png(CH_WORK / 'emis.png', rng.integers(0, 256, (SIZE, SIZE, 3)), bits=8)
    # T1's base colour texture: 8-bit sRGB, noise blurred by a 3 x 3 box (some detail at every scale)
    noise = rng.integers(40, 216, (SIZE + 2, SIZE + 2, 3)).astype(np.float64)
    blur = sum(noise[dy:dy + SIZE, dx:dx + SIZE] for dy in range(3) for dx in range(3)) / 9.0
    write_png(CH_WORK / 'albedo_src.png', np.rint(blur).astype(np.int64), bits=8)
    const = ch_material('CH_CONST', CH_BASE, CH_ROUGH, CH_METAL, CH_EMIS)
    for prop, f in ((ao_bake_apply.P_BASE, 'base.png'), (ao_bake_apply.P_ORM, 'orm.png'),
                    (ao_bake_apply.P_EMIS, 'emis.png')):
        setattr(const, prop, bpy.data.images.load(str(CH_WORK / f)))
    const = ch_material('CH_CONST', CH_BASE, CH_ROUGH, CH_METAL, CH_EMIS)  # the tree again, as built here
    ch_plane('K1', (0, 0, 0), const, (0.05, 0.05, 0.45, 0.45))
    ch_plane('K2', (1, 0, 0), const, (0.55, 0.55, 0.95, 0.95))
    src = bpy.data.images.load(str(CH_WORK / 'albedo_src.png'))
    ch_plane('T1', (2, 0, 0), ch_material('CH_TEX', rough=0.7, metal=0.25, emis=(0.1, 0.0, 0.3), tex=src))
    ch_plane('G1', (3, 0, 0), ch_material('CH_AOGRP', CH_GROUP_RGB, ao_group=True))
    ch_plane('N1', (4, 0, 0), ch_material('CH_DIFF', (0.2, 0.9, 0.2), diffuse=True))
    # a shared mesh with object-linked materials of different colours (rule item 6)
    red, blue = ch_material('CH_RED', (1.0, 0.0, 0.0)), ch_material('CH_BLUE', (0.0, 0.0, 1.0))
    s1 = ch_plane('S1', (5, 0, 0), red)
    s2 = link(bpy.data.objects.new('S2', s1.data))
    s2.location = (5.5, 0, 0)
    for o, m in ((s1, red), (s2, blue)):
        o.material_slots[0].link = 'OBJECT'
        o.material_slots[0].material = m
    # decision 87: a shared mesh of three copies, object-linked materials of their own base and emissive colours
    e1 = ch_plane('E1', (7, 0, 0), ch_material('CH_E1', CH_E_BASE['E1'], emis=CH_E_EMIS['E1']))
    for i, n in enumerate(('E1', 'E2', 'E3')):
        o = e1 if n == 'E1' else link(bpy.data.objects.new(n, e1.data))
        o.location = (7 + 0.5 * i, 0, 0)
        o.material_slots[0].link = 'OBJECT'
        o.material_slots[0].material = ch_material(f'CH_{n}', CH_E_BASE[n], emis=CH_E_EMIS[n])
    bpy.ops.wm.save_as_mainfile(filepath=str(CH_BLEND))
    return src


def ch_set(s, prefix, groups):
    for g in core.CHANNEL_GROUPS:
        setattr(s, f'{prefix}_{g}', g in groups)


def ch_bake(names, ao=False, cm=False, groups=(), active='first', samples=None, scope='SELECTED'):
    """A bake of the selection through the operator (hidden, waited for); returns the job's status."""
    s = bpy.context.scene.fss_ao_bake
    s.bake_ao, s.curvature = ao, cm
    ch_set(s, 'bake', groups)
    select(names)
    if active != 'first':
        bpy.context.view_layer.objects.active = bpy.data.objects[active] if active else None
    if samples:
        os.environ['FSS_AO_BAKE_CHANNEL_SAMPLES'] = str(samples)
    try:
        assert bpy.ops.fss.ao_bake_start(scope=scope, hidden=True, wait=True) == {'FINISHED'}
    finally:
        os.environ.pop('FSS_AO_BAKE_CHANNEL_SAMPLES', None)
    status = store.read_status(str(CH_WORK / 'channels.bake'))
    assert status['state'] == 'done' and all(r['status'] == 'baked' for r in status['results']), status['results']
    refresh()
    return status


def ch_item(name):
    return store._state['items'][store._state['by_object'][name]]


def ch_files(name, groups=core.CHANNEL_GROUPS):
    stem = store._state['by_object'][name]
    folder = str(CH_WORK / 'channels.bake')
    return {os.path.basename(p): file_hash(p) for g in groups for p in core.channel_paths(folder, stem, g)
            if os.path.isfile(p)}


def ch_layout_files(name):
    stem = store._state['by_object'][name]
    _img, mp, npz = core.master_paths(str(CH_WORK / 'channels.bake'), stem)
    return {os.path.basename(p): file_hash(p) for p in (mp, npz)}


def ch_master(name, comp):
    m = core.load_master(str(CH_WORK / 'channels.bake'), store._state['by_object'][name], kind=comp)
    return m['image'][m['filled']].astype(np.int64)


def q16(v):
    return int(np.round(np.clip(v, 0.0, 1.0) * 65535.0))


def ch_apply(material, groups, target='FILE', layout='ORM', objects=None, ao=False, own=True):
    """Apply of these channels (the scene's apply toggles; ao: the AO too, first) for one texture set; its reports.
    own: the albedo's and emissive's own Target (decision 96) set as the AO's (ORM: in place) at SIZE; False: as they
    are."""
    s = bpy.context.scene.fss_ao_bake
    keep = (s.apply_ao, s.apply_cm)
    s.apply_ao, s.apply_cm = ao, False
    ch_set(s, 'apply', groups)
    mat = bpy.data.materials[material]
    a = mat.fss_ao_apply
    a.target, a.layout, a.resolution = target, layout, str(SIZE)
    if own:
        a.albedo_target = a.emis_target = 'SLOT' if target == 'ORM' else 'FILE'
        a.albedo_resolution = a.emis_resolution = str(SIZE)
    try:
        reps = ao_bake_apply.apply(bpy.context, [mat], objects)
    finally:
        s.apply_ao, s.apply_cm = keep
        ch_set(s, 'apply', ())
    for r in reps:
        assert not r.get('error'), r
    return reps


def ch_measure(out, ref, mask):
    """The difference of a written albedo to the source (both 0..1 sRGB-encoded): mean, max, share within 1/255."""
    d = np.abs(out[mask] - ref[mask])
    return dict(mean=float(d.mean()), max=float(d.max()), within_1_255=float((d <= 1.0 / 255.0 + 1e-12).mean()),
                px=int(mask.sum()))


def ch_entry(name):
    stem = store._state['by_object'][name]
    return store.read_index(str(CH_WORK / 'channels.bake'), use_cache=False)['masters'].get(stem), stem


def ch_own_targets(exp, k1):
    """Decisions 96 and 97 (Session 76's step 2), on CH_CONST (K1 baked with every channel, K2 without a master) and
    CH_TEX (no texture in its base colour, emissive or ORM slot): Albedo and Emissive by their own Target, folder,
    file, resolution and padding, independent of the AO's; the problem line per ticked Apply channel, Run refused."""
    s = bpy.context.scene.fss_ao_bake
    mat = bpy.data.materials['CH_CONST']
    a = mat.fss_ao_apply
    out_dir = CH_WORK / 'out'
    base, orm = CH_WORK / 'base.png', CH_WORK / 'orm.png'
    alb_file, ao_file = out_dir / 'CH_CONST_ALBD_RGB16.png', out_dir / 'CH_CONST_COMP_RGB16.png'
    others = [out_dir / f'CH_CONST.{n}.png' for n in ('roughness', 'metal', 'emissive')] + [CH_WORK / 'emis.png']
    found = {}
    keep_s = {p: getattr(s, p) for p in ('apply_ao', 'apply_cm', 'emis_padding', 'albedo_padding')}

    def run(groups, ao=False):
        s.apply_ao, s.apply_cm = ao, False
        ch_set(s, 'apply', groups)
        try:
            reps = ao_bake_apply.apply(bpy.context, [mat])
        finally:
            ch_set(s, 'apply', ())
        for r in reps:
            assert not r.get('error'), r
        return {r['kind']: r for r in reps}

    def dev_k1(vals, g):
        return max(int(np.abs(vals[:, :, c][k1] - e).max()) for c, e in enumerate(exp[g]))
    try:
        # the defaults: Separate File, the AO's folder, <material>_ALBD_RGB16.png / .emissive.png, padding 8
        fresh = bpy.data.materials.new('CH_DEFAULTS')
        fa = fresh.fss_ao_apply
        assert (fa.albedo_target, fa.emis_target) == ('FILE', 'FILE'), (fa.albedo_target, fa.emis_target)
        assert (fa.albedo_file_name, fa.emis_file_name) == ('CH_DEFAULTS_ALBD_RGB16.png', 'CH_DEFAULTS.emissive.png')
        bpy.data.materials.remove(fresh)
        assert s.albedo_output_folder == s.emis_output_folder == s.output_folder
        assert s.bl_rna.properties['albedo_padding'].default == s.bl_rna.properties['emis_padding'].default == 8
        # (a) Albedo in place, the AO in a separate file
        a.target, a.layout, a.resolution = 'FILE', 'GREY', str(SIZE)
        a.albedo_target = 'SLOT'
        h_orm, h_alb = file_hash(orm), file_hash(alb_file)
        reps = run(['albedo'], ao=True)
        assert sorted(reps) == ['albedo', 'ao'], sorted(reps)
        assert os.path.normpath(reps['ao']['path']) == os.path.normpath(str(ao_file)), reps['ao']['path']
        assert os.path.normpath(reps['albedo']['path']) == os.path.normpath(str(base)) and \
            reps['albedo']['target'] == 'SLOT', (reps['albedo']['path'], reps['albedo']['target'])
        da = dev_k1(read(base)[0].astype(np.int64), 'albedo')
        assert da <= 1, da
        assert file_hash(orm) == h_orm and file_hash(alb_file) == h_alb, 'the ORM texture or the albedo file changed'
        found['76 (a)'] = (f"Albedo in place into base.png (max deviation {da}), AO into {ao_file.name}; orm.png and "
                           f"{alb_file.name} byte-identical")
        # (b) the other way round: the AO in place, the albedo in a separate file
        a.target, a.albedo_target, a.albedo_resolution = 'ORM', 'FILE', str(SIZE)
        h_base = file_hash(base)
        alb_file.unlink()
        reps = run(['albedo'], ao=True)
        assert os.path.normpath(reps['ao']['path']) == os.path.normpath(str(orm)), reps['ao']['path']
        assert os.path.normpath(reps['albedo']['path']) == os.path.normpath(str(alb_file)) and \
            reps['albedo']['target'] == 'FILE', reps['albedo']['path']
        db = dev_k1(read(alb_file)[0].astype(np.int64), 'albedo')
        assert db <= 1 and file_hash(base) == h_base, (db, 'base.png changed')
        found['76 (b)'] = (f"AO in place into orm.png, Albedo into a new {alb_file.name} (max deviation {db}); "
                           f"base.png byte-identical")
        # an Albedo-only Apply: the AO's files, the ORM texture and the other channels' files unchanged
        h_ao = {p.name: file_hash(p) for p in [orm, ao_file] + others}
        run(['albedo'])
        assert {p.name: file_hash(p) for p in [orm, ao_file] + others} == h_ao, 'an Albedo-only Apply changed them'
        found['76 albedo only'] = f'{len(h_ao)} files byte-identical ({", ".join(sorted(h_ao))})'
        # (c) the emissive into a separate file in its own folder at its own resolution and padding
        own = CH_WORK / 'emis_out'
        s.emis_output_folder = str(own)
        assert s.emis_output_folder == str(own) and s.output_folder == str(out_dir)
        a.emis_target, a.emis_file_name, a.emis_resolution = 'FILE', 'own_emis', '512'
        assert a.emis_file_name == 'own_emis'
        widths = {}
        for pad in (8, 2):
            s.emis_padding = pad
            target = own / 'own_emis.png'
            if target.exists():
                target.unlink()
            reps = run(['emis'])
            r = reps['emis']
            assert os.path.normpath(r['path']) == os.path.normpath(str(target)) and r['size'] == [512, 512], r
            vals = read(target)[0].astype(np.int64)
            k1_512 = faces_mask('K1', 512, 512)
            de = max(int(np.abs(vals[:, :, c][k1_512] - e).max()) for c, e in enumerate(exp['emis']))
            assert de <= 1, de
            beyond = core.dilate_ids(np.where(k1_512, 0, -1), 3)[0] < 0
            widths[pad] = (r['written_px'], int((vals[beyond].max(axis=1) > 0).sum()), de)
        assert widths[2][1] == 0 and widths[8][1] > 0 and widths[8][0] > widths[2][0], widths
        assert file_hash(out_dir / 'CH_CONST.emissive.png') == h_ao['CH_CONST.emissive.png']  # the AO folder's
        found['76 (c)'] = (f"emissive into emis_out/own_emis.png 512 x 512 (the AO's {SIZE}); padding 2: "
                           f"{widths[2][0]} px written, none beyond 3 px of K1's faces; padding 8: {widths[8][0]} px, "
                           f"{widths[8][1]} beyond; max deviation {widths[2][2]}")
        s.emis_output_folder = str(out_dir)
        assert s.get('emis_output_folder') == '', 'set to the AO folder: stored empty'
        # (d) decision 97: a set without textures in its slots; the problem line per ticked channel, Run refused
        tex = bpy.data.materials['CH_TEX']
        t = tex.fss_ao_apply
        assert getattr(tex, ao_bake_apply.P_BASE, None) is None and getattr(tex, ao_bake_apply.P_EMIS, None) is None
        t.albedo_target, t.emis_target, t.target = 'SLOT', 'SLOT', 'ORM'
        s.apply_ao, s.apply_cm = False, False
        ch_set(s, 'apply', ['albedo'])
        assert ao_bake.target_problems(bpy.context, tex) == ['No texture in the base colour slot']
        ch_set(s, 'apply', ['albedo', 'rough', 'emis'])
        got = ao_bake.target_problems(bpy.context, tex)
        assert got == ['No texture in the ORM slot', 'No texture in the base colour slot',
                       'No texture in the emissive slot'], got
        ch_set(s, 'apply', ['albedo'])
        keep_b = {p: getattr(s, p) for p in ['bake_ao', 'curvature'] + [f'bake_{g}' for g in core.CHANNEL_GROUPS]}
        for p in keep_b:
            setattr(s, p, False)
        select(['T1'])
        try:
            lines = ao_bake.run_problems(bpy.context)
            assert 'CH_TEX: No texture in the base colour slot' in lines, lines
            refused = bpy.ops.fss.ao_run(hidden=True, wait=True)
            assert refused == {'CANCELLED'}, refused
            t.albedo_target = 'FILE'
            assert not [x for x in ao_bake.run_problems(bpy.context) if x.startswith('CH_TEX')]
        finally:
            for p, v in keep_b.items():
                setattr(s, p, v)
            select([])
        found['76 (d)'] = (f"CH_TEX: {got}; Run with Apply Albedo: '{lines[0]}', CANCELLED; with Separate File no "
                           f"line")
    finally:
        for p, v in keep_s.items():
            setattr(s, p, v)
        ch_set(s, 'apply', ())
        s.emis_output_folder = ''
        a.emis_file_name = ''
        for m in (a, bpy.data.materials['CH_TEX'].fss_ao_apply):
            m.albedo_target = m.emis_target = 'FILE'
            m.albedo_resolution = m.emis_resolution = str(SIZE)
    return found


def test_material_channels():
    """Decisions 79 to 83 (Session 61's steps 2.1 to 2.9): the material channels baked into the master from Principled
    materials built here, and Apply into their targets; decisions 85 to 87 (Session 65's steps 2.1 to 2.3): a
    mesh-changed channel applied anyway, roughness and metal of Target File in their own grey files, a shared mesh's
    emissive combined over its copies; decisions 96 and 97 (Session 76's step 2, ch_own_targets): Albedo and Emissive
    by their own Target, folder, file, resolution and padding, the problem line per ticked Apply channel."""
    t0 = time.time()
    src = build_channel_scene()
    s = bpy.context.scene.fss_ao_bake
    folder = str(CH_WORK / 'channels.bake')
    out_dir = CH_WORK / 'out'
    ALL = list(core.CHANNEL_GROUPS)
    found = {}
    with rule_unrecorded():
        refresh()
        # FL1, steps 2.1, 2.6, 2.9: AO, curvature and the four channels of K1, T1, G1, N1 (K2 not: step 2.8)
        status = ch_bake(['K1', 'T1', 'G1', 'N1'], ao=True, cm=True, groups=ALL)
        for n in ('K1', 'T1', 'G1', 'N1'):
            it = ch_item(n)
            assert it['grade'] == 'UP_TO_DATE' and it['cm_grade'] == 'UP_TO_DATE', (n, it['grade'], it['cm_grade'])
            assert it['ch_grades'] == {g: 'UP_TO_DATE' for g in ALL}, (n, it['ch_grades'])
        assert ch_item('K2')['ch_grades'] == {} and ch_item('K2')['grade'] == 'MISSING'
        # step 2.9: N1's material has no Principled BSDF: skipped, said in the log and the report
        note = next(r for r in status['results'] if r['name'] == 'N1').get('note', '')
        assert 'Albedo skipped for CH_DIFF' in note and 'Emissive skipped for CH_DIFF' in note, note
        log_text = (CH_WORK / 'channels.bake' / 'bake.log').read_text(encoding='utf-8')
        assert 'Albedo skipped for CH_DIFF (no Principled BSDF on the Material Output)' in log_text
        entry_n, _ = ch_entry('N1')
        assert all(entry_n['channels'][g]['skipped'] == ['CH_DIFF'] for g in ALL), entry_n['channels']
        reps = ch_apply('CH_DIFF', ['albedo'])
        assert reps[0]['white'] == [('N1', 'no Principled BSDF', 16)] and reps[0]['written_px'] == 0, reps[0]
        lines = ao_bake_apply.report_lines(reps[0])
        assert 'kept (no up-to-date master): N1 (no Principled BSDF)' in lines[1], lines
        found['2.9'] = f"note \"{note.split(';')[0]}\", Apply: {lines[1].strip()}"
        # step 2.6: the colour before the .Apply AO Group, not halved
        want = [q16(core.srgb_encode(v)) for v in CH_GROUP_RGB]
        half = [q16(core.srgb_encode(v * 0.5)) for v in CH_GROUP_RGB]
        got = [ch_master('G1', k) for k in core.CHANNEL_KINDS['albedo']]
        dev = max(int(np.abs(g - w).max()) for g, w in zip(got, want))
        assert dev <= 1, (dev, [(int(g.min()), int(g.max())) for g in got], want)
        found['2.6'] = f'G1 albedo {want} (halved would be {half}), max deviation {dev}'
        # steps 2.1 and 2.8, Target ORM Texture: K1's faces get the values, K2 (no master) keeps its pixels
        before = {f: read(CH_WORK / f)[0].astype(np.int64) for f in ('base.png', 'orm.png', 'emis.png')}
        raw = {f: (CH_WORK / f).read_bytes() for f in ('base.png', 'orm.png', 'emis.png')}
        reps = ch_apply('CH_CONST', ALL, target='ORM')
        assert [r['white'] for r in reps] == [[('K2', 'missing', 16)]] * 4, [r['white'] for r in reps]
        k1, k2 = faces_mask('K1'), faces_mask('K2')
        grown = core.dilate_ids(np.where(k1, 0, -1), PAD + 1)[0] >= 0
        after = {f: read(CH_WORK / f) for f in ('base.png', 'orm.png', 'emis.png')}
        assert all(a[1] == 16 for a in after.values()), {f: a[1] for f, a in after.items()}
        after = {f: a[0].astype(np.int64) for f, a in after.items()}
        exp = dict(albedo=[q16(core.srgb_encode(v)) for v in CH_BASE], rough=[q16(CH_ROUGH)], metal=[q16(CH_METAL)],
                   emis=[q16(core.srgb_encode(v)) for v in CH_EMIS])
        devs = {}
        for g, f, cols in (('albedo', 'base.png', (0, 1, 2)), ('rough', 'orm.png', (1,)), ('metal', 'orm.png', (2,)),
                           ('emis', 'emis.png', (0, 1, 2))):
            devs[g] = max(int(np.abs(after[f][:, :, c][k1] - e).max()) for c, e in zip(cols, exp[g]))
        assert max(devs.values()) <= 1, devs
        scale = {'base.png': 1, 'orm.png': 1, 'emis.png': 257}  # the 8-bit emissive written 16-bit, values kept
        for f in before:
            b = before[f] * scale[f]
            assert np.array_equal(after[f][k2], b[k2]), f  # step 2.8: byte for byte
            assert np.array_equal(after[f][~grown], b[~grown]), f
        assert np.array_equal(after['base.png'][:, :, 3], before['base.png'][:, :, 3])  # alpha
        assert np.array_equal(after['orm.png'][:, :, 0], before['orm.png'][:, :, 0])  # the AO's red
        for d, f in (('albedo_backup', 'base.png'), ('orm_backup', 'orm.png'), ('emis_backup', 'emis.png')):
            assert (CH_WORK / 'channels.bake' / d / f).read_bytes() == raw[f], (d, f)
        found['2.1 in place'] = f'max deviation per channel {devs}; K2 and pixels beyond the padding byte for byte'
        # step 2.1, Target Separate File: <material>_ALBD_RGB16.png, .emissive.png, and (decision 86, Session 65's step
        # 2.2) .roughness.png and .metal.png, single-channel 16-bit grey; the AO's ORM-layout file of the same run
        # has the green and blue AO alone gives it
        orm_file = out_dir / 'CH_CONST_COMP_RGB16.png'
        reps = ch_apply('CH_CONST', ALL, target='FILE', layout='ORM', ao=True)
        assert [r['kind'] for r in reps] == ['ao'] + ALL, [r['kind'] for r in reps]
        orm_with = read(orm_file)[0].astype(np.int64)
        orm_file.unlink()
        ch_apply('CH_CONST', [], target='FILE', layout='ORM', ao=True)
        orm_alone = read(orm_file)[0].astype(np.int64)
        assert np.array_equal(orm_with, orm_alone), 'the channels changed the ORM-layout file'
        files, kinds = {}, {}
        for g, n in (('albedo', 'CH_CONST_ALBD_RGB16.png'), ('emis', 'CH_CONST.emissive.png'),
                     ('rough', 'CH_CONST.roughness.png'), ('metal', 'CH_CONST.metal.png')):
            vals, bits, ct = read(out_dir / n)
            files[g], kinds[g] = vals.astype(np.int64), (vals.shape[2], bits, ct)
        assert kinds['rough'] == kinds['metal'] == (1, 16, 0), kinds  # grey, 16-bit, colour type 0
        assert kinds['albedo'][0] == kinds['emis'][0] == 3, kinds
        fdev = {g: max(int(np.abs(files[g][:, :, c][k1] - e).max()) for c, e in enumerate(exp[g])) for g in ALL}
        assert max(fdev.values()) <= 1, fdev
        assert (files['emis'][~grown] == 0).all() and (files['albedo'][~grown] == 65535).all()
        assert (files['rough'][~grown] == 0).all() and (files['metal'][~grown] == 0).all()  # a new grey file: black
        found['2.1 files'] = (f'max deviation per channel {fdev}; roughness and metal {kinds["rough"][0]} channel, '
                              f'{kinds["rough"][1]}-bit, colour type {kinds["rough"][2]}, black beyond the padding; '
                              f'the ORM-layout file of AO with the channels equal to AO alone '
                              f'({orm_with.shape[1]} x {orm_with.shape[0]} x {orm_with.shape[2]})')
        # Channels Greyscale does not matter for the channels' own files any more
        before_r = file_hash(out_dir / 'CH_CONST.roughness.png')
        ch_apply('CH_CONST', ['rough'], target='FILE', layout='GREY')
        assert file_hash(out_dir / 'CH_CONST.roughness.png') == before_r
        # the samples (rule item 2): T1's textured albedo at 1 ... 256 samples, each bake of Albedo alone; the other
        # channels, the AO and the layout byte-identical meanwhile (FL1)
        others = ch_files('T1', ('rough', 'metal', 'emis'))
        keep = dict(ch_layout_files('T1'), ao=file_hash(core.master_paths(folder, store._state['by_object']['T1'])[0]))
        by_n, files_n, out_n = {}, {}, {}
        for n in CH_SAMPLE_COUNTS:
            ch_bake(['T1'], groups=['albedo'], samples=n)
            by_n[n] = np.stack([ch_master('T1', k) for k in core.CHANNEL_KINDS['albedo']])
            files_n[n] = ch_files('T1', ('albedo',))
            ch_apply('CH_TEX', ['albedo'])  # what the texture gets: Apply averages the master over each pixel
            out_n[n] = read(out_dir / 'CH_TEX_ALBD_RGB16.png')[0][:, :, :3].astype(np.int64)
            assert ch_files('T1', ('rough', 'metal', 'emis')) == others
            assert dict(ch_layout_files('T1'), ao=file_hash(core.master_paths(
                folder, store._state['by_object']['T1'])[0])) == keep
        assert len({tuple(sorted(f.items())) for f in files_n.values()}) == len(CH_SAMPLE_COUNTS)  # overwritten
        ref = by_n[CH_SAMPLE_COUNTS[-1]]
        tmask = np.repeat(faces_mask('T1')[:, :, None], 3, axis=2)
        table = {}
        for i, n in enumerate(CH_SAMPLE_COUNTS[:-1]):
            d_ref = np.abs(by_n[n] - ref)
            d_next = np.abs(by_n[n] - by_n[CH_SAMPLE_COUNTS[i + 1]])
            d_out = np.abs(out_n[n] - out_n[CH_SAMPLE_COUNTS[-1]])[tmask]
            table[n] = dict(master_vs_256_max=int(d_ref.max()), master_vs_256_p999=float(np.percentile(d_ref, 99.9)),
                            master_vs_256_within_1=round(float((d_ref <= 1).mean()), 4),
                            master_vs_next_max=int(d_next.max()), texture_vs_256_max=int(d_out.max()),
                            texture_vs_256_mean=round(float(d_out.mean()), 2),
                            texture_vs_256_within_1=round(float((d_out <= 1).mean()), 4))
        found['samples'] = table
        # step 2.2's comparison also with the texture read Closest (no bilinear blend between its texels)
        tnode = next(n for n in bpy.data.materials['CH_TEX'].node_tree.nodes if n.type == 'TEX_IMAGE')
        tnode.interpolation = 'Closest'
        ch_bake(['T1'], groups=['albedo'])
        ch_apply('CH_TEX', ['albedo'])
        srcv = read(CH_WORK / 'albedo_src.png')[0][:, :, :3].astype(np.float64) / 255.0
        closest = ch_measure(read(out_dir / 'CH_TEX_ALBD_RGB16.png')[0][:, :, :3].astype(np.float64) / 65535.0, srcv,
                             tmask)
        tnode.interpolation = 'Linear'
        ch_bake(['T1'], groups=['albedo'])  # back at the default samples, Linear
        # step 2.2: a grey material put back (T1's material: the texture unlinked); Albedo up to date; Apply against
        # the source texture
        tex_mat = bpy.data.materials['CH_TEX']
        p = tex_mat.node_tree.nodes['Principled BSDF']
        for link_ in list(p.inputs['Base Color'].links):
            tex_mat.node_tree.links.remove(link_)
        p.inputs['Base Color'].default_value = (0.5, 0.5, 0.5, 1.0)
        refresh()
        assert ch_item('T1')['ch_grades']['albedo'] == 'UP_TO_DATE', ch_item('T1')['ch_grades']
        srcv = read(CH_WORK / 'albedo_src.png')[0][:, :, :3].astype(np.float64) / 255.0
        ch_apply('CH_TEX', ['albedo'])
        outv = read(out_dir / 'CH_TEX_ALBD_RGB16.png')[0][:, :, :3].astype(np.float64) / 65535.0
        m22 = ch_measure(outv, srcv, np.repeat(faces_mask('T1')[:, :, None], 3, axis=2))
        found['2.2'] = m22
        found['2.2 baked with Closest interpolation'] = closest
        # step 2.5 (FL1): AO alone baked with the material changed: the channels' files byte-identical
        chans = ch_files('T1')
        e0, _ = ch_entry('T1')
        ch_bake(['T1'], ao=True)
        e1, _ = ch_entry('T1')
        assert ch_files('T1') == chans and len(chans) == 8, 'a material channel changed'
        assert e1['baked_at'] != e0['baked_at'] and e1['channels'] == e0['channels'], (e0['baked_at'], e1['baked_at'])
        found['2.5'] = f'{len(chans)} channel files byte-identical, the AO baked again ({e1["baked_at"]})'
        # step 2.3 (FL3): the texture set repacked (UVs moved and scaled, the density halved), AO alone baked: the
        # layout kept
        t1 = bpy.data.objects['T1']
        lay = t1.data.uv_layers['UVMap']
        uvs = np.empty(len(lay.data) * 2, np.float32)
        lay.data.foreach_get('uv', uvs)
        lay.data.foreach_set('uv', uvs * 0.5 + 0.203125)
        t1.data.update()
        refresh()
        assert ch_item('T1')['grade'] == 'UP_TO_DATE', ch_item('T1')['grade']
        layout0, alb0 = ch_layout_files('T1'), ch_files('T1', ('albedo',))
        ch_bake(['T1'], ao=True)
        e2, _ = ch_entry('T1')
        assert ch_layout_files('T1') == layout0, 'the layout files changed'
        assert ch_files('T1', ('albedo',)) == alb0 and ch_item('T1')['ch_grades']['albedo'] == 'UP_TO_DATE'
        assert e2['density'] == e1['density'] and e2['baked_at'] != e1['baked_at'], (e2['density'], e1['density'])
        ch_apply('CH_TEX', ['albedo'])
        outv = read(out_dir / 'CH_TEX_ALBD_RGB16.png')[0][:, :, :3].astype(np.float64) / 65535.0
        # the reference: the source's 2 x 2 block each written pixel covers (uv' = uv / 2 + 52 / 256)
        box = srcv.reshape(SIZE // 2, 2, SIZE // 2, 2, 3).mean(axis=(1, 3))
        refv = np.zeros_like(outv)
        lo = 52
        refv[lo:lo + SIZE // 2, lo:lo + SIZE // 2] = box
        mask = faces_mask('T1')
        m23 = ch_measure(outv, refv, np.repeat(mask[:, :, None], 3, axis=2))
        found['2.3'] = dict(m23, density=e2['density'])
        reps23 = ch_apply('CH_TEX', ['albedo'])  # the same Apply again (deterministic), for its written pixels
        m23_px = reps23[0]['written_px']
        # step 2.4: the mesh edited: every channel MESH; Albedo alone baked: a new layout, AO and curvature removed
        t1.data.vertices[6].co.z += 0.001
        t1.data.update()
        refresh()
        it = ch_item('T1')
        assert it['grade'] == 'MESH' and it['ch_grades'] == {g: 'MESH' for g in ALL}, (it['grade'], it['ch_grades'])
        # Session 65's step 2.1 (decision 85): Apply Albedo with the mesh changed: written from the master, reported
        written23 = (CH_WORK / 'out' / 'CH_TEX_ALBD_RGB16.png').read_bytes()
        reps = ch_apply('CH_TEX', ['albedo'])
        lines = ao_bake_apply.report_lines(reps[0])
        assert reps[0]['mesh_changed'] == ['T1'] and reps[0]['white'] == [], reps[0]
        assert 'mesh changed since its bake, applied anyway: T1' in '\n'.join(lines), lines
        out_mc = read(out_dir / 'CH_TEX_ALBD_RGB16.png')[0][:, :, :3].astype(np.int64)
        (CH_WORK / 'out' / 'CH_TEX_23_ALBD_RGB16.png').write_bytes(written23)
        out_23 = read(CH_WORK / 'out' / 'CH_TEX_23_ALBD_RGB16.png')[0][:, :, :3].astype(np.int64)
        d_mc = np.abs(out_mc - out_23)[np.repeat(mask[:, :, None], 3, axis=2)]
        assert reps[0]['written_px'] == m23_px and int(d_mc.max()) <= 257, (reps[0]['written_px'], m23_px,
                                                                             int(d_mc.max()))
        found['65 2.1'] = (f"{reps[0]['written_px']} px written (as before the edit), report "
                           f"'{[x for x in lines if 'applied anyway' in x][0].strip()}', against the Apply before the "
                           f"edit max {int(d_mc.max())}/65535, mean {float(d_mc.mean()):.3f}/65535")
        stem_t1 = store._state['by_object']['T1']
        ch_bake(['T1'], groups=['albedo'])
        it = ch_item('T1')
        assert it['grade'] == 'MISSING' and it['cm_grade'] == 'NEEDS_AO', (it['grade'], it['cm_grade'])
        assert it['ch_grades'] == {'albedo': 'UP_TO_DATE'}, it['ch_grades']
        assert not os.path.isfile(core.image_paths(folder, stem_t1)[0])
        assert not os.path.isfile(core.image_paths(folder, stem_t1, 'curv')[0])
        assert sorted(ch_files('T1')) == sorted(os.path.basename(p) for p in core.channel_paths(folder, stem_t1,
                                                                                               'albedo'))
        assert ch_layout_files('T1') != layout0
        e3, _ = ch_entry('T1')
        assert 'curvature' not in e3 and 'surround_hash' not in e3 and sorted(e3['channels']) == ['albedo'], e3
        found['2.4'] = f"AO {it['grade']}, CM {it['cm_grade']}, channels {it['ch_grades']}"
        # step 2.7: a shared mesh's albedo from the chosen copy (S1 red, S2 blue)
        red, blue = q16(1.0), q16(0.0)
        shared = {}
        for case, active, picked, want in (('drop-down', 'S2', 'S1', ('S1', red)), ('active', 'S2', '', ('S2', blue)),
                                           ('first by name', None, '', ('S1', red))):
            bpy.data.meshes[bpy.data.objects['S1'].data.name].fss_ao_shared.bake_copy_name = picked
            ch_bake(['S1', 'S2'], groups=['albedo'], active=active)
            e, _ = ch_entry('S1')
            r = ch_master('S1', 'albedo_r')
            assert e['channels']['albedo']['object'] == want[0] and int(np.abs(r - want[1]).max()) <= 1, \
                (case, e['channels']['albedo']['object'], int(r.min()), int(r.max()))
            shared[case] = e['channels']['albedo']['object']
        found['2.7'] = shared
        # Session 65's step 2.3 (decision 87): E1, E2, E3 share a mesh; the emissive by each Copies setting, the
        # albedo from the chosen copy (E1, the active one)
        e_mesh = bpy.data.objects['E1'].data
        enc = {n: [q16(core.srgb_encode(v)) for v in c] for n, c in CH_E_EMIS.items()}
        mean = np.mean(np.array(list(CH_E_EMIS.values()), np.float32), axis=0)
        want = dict(AVERAGE=[q16(core.srgb_encode(float(v))) for v in mean], LIGHTEST=enc['E2'], DARKEST=enc['E3'],
                    ONE=enc['E1'])
        emis_got = {}
        try:
            for mode in ('AVERAGE', 'LIGHTEST', 'DARKEST', 'ONE'):
                e_mesh.fss_ao_shared.combine = mode
                e_mesh.fss_ao_shared.bake_copy_name = ''
                ch_bake(['E1', 'E2', 'E3'], groups=['albedo', 'emis'])
                e, _ = ch_entry('E1')
                got = [ch_master('E1', k) for k in core.CHANNEL_KINDS['emis']]
                dev = max(int(np.abs(g - w).max()) for g, w in zip(got, want[mode]))
                assert dev <= 1, (mode, dev, [(int(g.min()), int(g.max())) for g in got], want[mode])
                ce = e['channels']['emis']
                assert ce.get('combine') == mode, ce
                assert ce['copies'] == (['E1'] if mode == 'ONE' else ['E1', 'E2', 'E3']), ce
                alb = [ch_master('E1', k) for k in core.CHANNEL_KINDS['albedo']]
                adev = max(int(np.abs(g - q16(core.srgb_encode(v))).max()) for g, v in zip(alb, CH_E_BASE['E1']))
                assert adev <= 1 and e['channels']['albedo']['object'] == 'E1', (mode, adev, e['channels']['albedo'])
                emis_got[mode] = f'{want[mode]} dev {dev} (albedo E1 dev {adev})'
        finally:
            e_mesh.fss_ao_shared.combine = 'DEFAULT'
        found['65 2.3'] = emis_got
        found.update(ch_own_targets(exp, k1))
        # FL2 (step 2.2): the material changes do not stale; a mesh change does (step 2.4)
    s.bake_ao, s.curvature = True, False
    ch_set(s, 'bake', ())
    select([])
    print(f'PASS: test_material_channels ({time.time() - t0:.1f} s; ' + '; '.join(f'{k}: {v}' for k, v in found.items())
          + ')')
    return found


# ---------------------------------------------------------------------------------------------------------------------
# Decisions 88 to 90: channels from the mesh's active colour attribute (Session 68's step 2)
# ---------------------------------------------------------------------------------------------------------------------

VC_WORK = REPO_ROOT / 'tests' / '_work' / 'ao_bake_vc'
VC_FOLDER = str(VC_WORK / 'vc.bake')
VC_RENDER = (0.1, 0.9, 0.6)  # the first attribute's colour (active and render; the material reads it)
VC_FLOAT = (0.8, 0.35, 0.15)  # the second attribute's colour, FLOAT_COLOR (stored linear)
VC_BYTES = (204, 89, 38)  # the second attribute's bytes, BYTE_COLOR (stored sRGB-encoded)
VC_GROUPS = ('ao', 'albedo', 'rough', 'metal', 'emis')


def vc_colors(obj, active_type='FLOAT_COLOR', domain='POINT', value=None, active='RENDER'):
    """The first attribute RENDER (FLOAT_COLOR, corners, VC_RENDER; render, and active unless active names PAINT) and
    the second one PAINT of active_type and domain, one colour everywhere: value (RGB 0..1; for BYTE_COLOR the stored
    byte / 255), else VC_FLOAT or VC_BYTES."""
    me = obj.data
    r = me.color_attributes.get('RENDER') or me.color_attributes.new('RENDER', 'FLOAT_COLOR', 'CORNER')
    r.data.foreach_set('color', np.tile([*VC_RENDER, 1.0], len(r.data)).astype(np.float32))
    a = me.color_attributes.get('PAINT') or me.color_attributes.new('PAINT', active_type, domain)
    if value is None:
        value = VC_FLOAT if active_type == 'FLOAT_COLOR' else tuple(b / 255.0 for b in VC_BYTES)
    prop = 'color' if active_type == 'FLOAT_COLOR' else 'color_srgb'
    a.data.foreach_set(prop, np.tile([*value, 1.0], len(a.data)).astype(np.float32))
    assert [c.name for c in me.color_attributes][:2] == ['RENDER', 'PAINT'], [c.name for c in me.color_attributes]
    me.color_attributes.active_color = me.color_attributes[active]
    me.color_attributes.default_color_name = 'RENDER'
    me.update()
    return a


def vc_attr_state(name):
    """A mesh's colour attributes as the file holds them: (names, types, domains, values' hash), active, render."""
    me = bpy.data.objects[name].data
    rows = []
    for a in me.color_attributes:
        v = np.empty(len(a.data) * 4, np.float32)
        a.data.foreach_get('color', v)
        rows.append((a.name, a.data_type, a.domain, hashlib.sha256(v.tobytes()).hexdigest()[:16]))
    return rows, me.color_attributes.active_color.name, me.color_attributes.default_color_name


def vc_material(name, base=(0.5, 0.5, 0.5)):
    """A Principled material whose Base Color reads the render colour attribute through a Color Attribute node named
    RENDER (rule step 2.8), roughness 0.5, metal 0."""
    mat = ch_material(name, base)
    nt = mat.node_tree
    node = nt.nodes.new('ShaderNodeVertexColor')
    node.layer_name = 'RENDER'
    nt.links.new(node.outputs['Color'], nt.nodes['Principled BSDF'].inputs['Base Color'])
    return mat


def vc_paint_grey(obj):
    """Vertex Paint's Set Vertex Colors with the brush at 0.5 grey into the second attribute PAINT (made active for
    the paint), RENDER active again afterwards."""
    me = obj.data
    me.color_attributes.active_color = me.color_attributes['PAINT']
    view_layer = bpy.context.view_layer
    for o in view_layer.objects:
        o.select_set(o == obj)
    view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='VERTEX_PAINT')
    vp = bpy.context.scene.tool_settings.vertex_paint
    ups = getattr(vp, 'unified_paint_settings', None) or bpy.context.scene.tool_settings.unified_paint_settings
    ups.use_unified_color = True
    ups.color = (0.5, 0.5, 0.5)
    assert bpy.ops.paint.vertex_color_set() == {'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    me.color_attributes.active_color = me.color_attributes['RENDER']


def build_vc_scene():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    if VC_WORK.exists():
        shutil.rmtree(VC_WORK)
    VC_WORK.mkdir(parents=True)
    scene = bpy.context.scene
    scene.frame_set(1)
    s = scene.fss_ao_bake
    s.distance, s.samples, s.threads, s.padding, s.curv_padding = 0.1, 16, 12, PAD, PAD
    s.curv_width = 0.005
    s.denoise, s.dn_method, s.dn_curv_mode, s.dn_strength = True, 'FILTER', 'OFF', 1.0
    set_baker(s)
    s.output_folder = str(VC_WORK / 'out')
    # Session 70's step 2.4: one colour attribute (the MSFS exporter's new_object_handler gives a new mesh a white
    # 'Color' once); Session 68's step 2.7: none (the test takes it away)
    ch_plane('VX', (13, 0, 0), ch_material('VC_MAT_VX', (0.3, 0.6, 0.9)))
    # step 2.1: the four kinds of second attribute (FLOAT_COLOR, BYTE_COLOR; point, corner), the first one (active
    # and render) another colour, the material reading the first one
    for i, (n, t, d) in enumerate((('VF_P', 'FLOAT_COLOR', 'POINT'), ('VF_C', 'FLOAT_COLOR', 'CORNER'),
                                   ('VB_P', 'BYTE_COLOR', 'POINT'), ('VB_C', 'BYTE_COLOR', 'CORNER'))):
        vc_colors(ch_plane(n, (i, 0, 0), vc_material(f'VC_MAT_{n}')), t, d)
    # the 0.5-grey report: Vertex Paint at 0.5 into a FLOAT_COLOR and a BYTE_COLOR attribute
    for i, (n, t) in enumerate((('VG_F', 'FLOAT_COLOR'), ('VG_B', 'BYTE_COLOR'))):
        o = ch_plane(n, (4 + i, 0, 0), vc_material(f'VC_MAT_{n}'))
        vc_colors(o, t, 'POINT', value=(1.0, 1.0, 1.0))
        vc_paint_grey(o)
    # steps 2.2, 2.4, 2.5: a traced, denoised AO under an occluder, its active attribute set per step
    va = ch_plane('VA', (7, 0, 0), vc_material('VC_MAT_VA'))
    vc_colors(va, 'FLOAT_COLOR', 'POINT', value=(1.0, 1.0, 1.0))
    occ = plane('VA_OCC', (7.02, 0.03, 0.03), None, 0, size=0.12, n=2)
    occ.rotation_euler = (0.0, 0.5, 0.0)
    # step 2.3: no master yet; step 2.6: a material albedo then multiplied; step 2.7: no colour attribute
    vc_colors(ch_plane('VN', (9, 0, 0), vc_material('VC_MAT_VN')), 'FLOAT_COLOR', 'POINT', value=(0.6, 0.4, 0.2))
    va2 = ch_plane('VM', (11, 0, 0), ch_material('VC_MAT_VM', (0.6, 0.3, 0.1)))
    vc_colors(va2, 'FLOAT_COLOR', 'CORNER', value=(0.5, 0.8, 0.25))
    bpy.ops.wm.save_as_mainfile(filepath=str(VC_WORK / 'vc.blend'))


def vc_set(sources):
    """The vertex colour sources {group: mode} ticked, the others off."""
    s = bpy.context.scene.fss_ao_bake
    for g in VC_GROUPS:
        setattr(s, f'vc_{g}', g in sources)
        if g in sources:
            setattr(s, f'vc_{g}_mode', sources[g])


def vc_bake(names, ao=False, groups=(), sources=None, scope='SELECTED', expect='baked'):
    """A bake through the operator (hidden, waited for) with these sources; returns the job's results by name."""
    s = bpy.context.scene.fss_ao_bake
    s.bake_ao, s.curvature = ao, False
    ch_set(s, 'bake', groups)
    vc_set(sources or {})
    select(names)
    try:
        assert bpy.ops.fss.ao_bake_start(scope=scope, hidden=True, wait=True) == {'FINISHED'}
    finally:
        vc_set({})
    status = store.read_status(VC_FOLDER)
    res = {r['name']: r for r in status['results']}
    assert status['state'] == 'done', status
    if expect:
        assert all(r['status'] == expect for r in res.values()), status['results']
    refresh()
    return res


def vc_stem(name):
    return store._state['by_object'][name]


def vc_entry(name):
    return store.read_index(VC_FOLDER, use_cache=False)['masters'].get(vc_stem(name))


def vc_values(name, kind):
    """The master's values of an image (kind 'ao' or a channel component) on its filled pixels."""
    m = core.load_master(VC_FOLDER, vc_stem(name), kind=kind)
    return m['image'][m['filled']].astype(np.int64)


def vc_file(name, kind):
    return core.image_paths(VC_FOLDER, vc_stem(name), kind)[0]


def vc_expect(active_type, value=None):
    """{image kind: the 16-bit value} of an Overwrite from an attribute of one colour (decision 92): its linear value
    (a byte colour's byte decoded from sRGB, as the Color Attribute node gives it) in AO, roughness and metal; the
    albedo that value sRGB-encoded."""
    if active_type == 'FLOAT_COLOR':
        lin = np.array(value or VC_FLOAT, np.float64)
    else:
        lin = core.srgb_decode(np.array(value or [b / 255.0 for b in VC_BYTES], np.float64))
    data = lin
    alb = core.srgb_encode(lin)
    return dict(ao=q16(data[0]), rough=q16(data[1]), metal=q16(data[2]), albedo_r=q16(alb[0]), albedo_g=q16(alb[1]),
                albedo_b=q16(alb[2]))


def vc_dev(name, want):
    """The largest difference of each image's filled pixels to its value."""
    return {k: int(np.abs(vc_values(name, k) - v).max()) for k, v in want.items()}


def test_vertex_color_channels():
    """Decisions 88 to 92 (Session 68's steps 2.1 to 2.8, Session 70's 2.1 to 2.5): the AO, roughness, metal and albedo
    baked from the mesh's second colour attribute (by default; never the first, active and render one, which stay so)
    or its active one, the values linear for float and byte attributes, Overwrite and Multiply; the AO's grade without
    surroundings, its product kept through a denoise-only run."""
    t0 = time.time()
    build_vc_scene()
    s = bpy.context.scene.fss_ao_bake
    found = {}
    ALLVC = {g: 'OVERWRITE' for g in VC_GROUPS}
    CH3 = ['albedo', 'rough', 'metal']
    with rule_unrecorded():
        refresh()
        # FL1, step 2.1: Overwrite of all four from the four kinds of active attribute; the render one nowhere
        names = ['VF_P', 'VF_C', 'VB_P', 'VB_C', 'VG_F', 'VG_B']
        assert s.vc_attribute == 'SECOND'  # decision 91: the default
        before = {n: vc_attr_state(n) for n in names}
        res = vc_bake(names, ao=True, groups=CH3, sources=ALLVC)
        after = {n: vc_attr_state(n) for n in names}
        assert after == before, (before, after)  # nothing switched in the file (Session 70's FL1)
        assert all(a[1] == 'RENDER' and a[2] == 'RENDER' for a in after.values()), after
        devs = {}
        for n in names[:4]:
            t = 'FLOAT_COLOR' if n.startswith('VF') else 'BYTE_COLOR'
            want = vc_expect(t)
            devs[n] = max(vc_dev(n, want).values())
            assert devs[n] <= 1, (n, vc_dev(n, want), want)
            render = vc_expect('FLOAT_COLOR', VC_RENDER)
            for k in want:  # the render attribute's value nowhere (every pixel far from it)
                assert int(np.abs(vc_values(n, k) - render[k]).min()) > 1000, (n, k)
            e = vc_entry(n)
            assert e['ao_source'] == dict(vertex_color='PAINT', attribute='SECOND', mode='OVERWRITE',
                                          attributes=['PAINT']), e['ao_source']
            assert all(e['channels'][g]['source'] == dict(vertex_color='PAINT', attribute='SECOND', mode='OVERWRITE')
                       for g in CH3)
            assert res[n]['vertex_color']['type'] == t and res[n]['vertex_color']['read'] == 'SECOND', res[n]
            assert not os.path.isfile(vc_file(n, 'ao.raw')) and e.get('denoise') is None
            it = ch_item_vc(n)
            assert it['grade'] == 'UP_TO_DATE' and it['dn_grade'] == 'UP_TO_DATE', (n, it['grade'], it['dn_grade'])
        found['2.1'] = (f'SECOND: max deviation {devs} (in 1/65535), the first attribute more than 1000 away '
                        f'everywhere; RENDER still active and render, the attributes\' names, types, domains and '
                        f'values unchanged')
        # Session 70's step 2.2: Active Attribute reads the active one (PAINT active: its values; RENDER: the first's)
        s.vc_attribute = 'ACTIVE'
        me_p = bpy.data.objects['VF_P'].data
        try:
            me_p.color_attributes.active_color = me_p.color_attributes['PAINT']
            vc_bake(['VF_P'], ao=True, groups=CH3, sources=ALLVC)
            d_paint = max(vc_dev('VF_P', vc_expect('FLOAT_COLOR')).values())
            src_a = vc_entry('VF_P')['ao_source']
            me_p.color_attributes.active_color = me_p.color_attributes['RENDER']
            vc_bake(['VF_P'], ao=True, groups=CH3, sources=ALLVC)
            d_render = max(vc_dev('VF_P', vc_expect('FLOAT_COLOR', VC_RENDER)).values())
            src_r = vc_entry('VF_P')['ao_source']
        finally:
            s.vc_attribute = 'SECOND'
        assert d_paint <= 1 and d_render <= 1, (d_paint, d_render)
        assert (src_a['vertex_color'], src_a['attribute'], src_r['vertex_color'], src_r['attribute']) == (
            'PAINT', 'ACTIVE', 'RENDER', 'ACTIVE'), (src_a, src_r)
        found['70 2.2'] = (f'ACTIVE: PAINT active, its values (deviation {d_paint}); RENDER active, the first '
                           f'attribute\'s (deviation {d_render})')
        vc_bake(['VF_P'], ao=True, groups=CH3, sources=ALLVC)  # back to the second attribute's values
        # the 0.5-grey report: what Vertex Paint at 0.5 stores and what the master gets
        grey = {}
        for n in ('VG_F', 'VG_B'):
            a = bpy.data.objects[n].data.color_attributes['PAINT']
            stored = round(float(a.data[0].color[0]), 6), round(float(a.data[0].color_srgb[0]), 6)
            ao = vc_values(n, 'ao')
            alb = vc_values(n, 'albedo_r')
            rough, metal = vc_values(n, 'rough'), vc_values(n, 'metal')
            grey[n] = dict(type=a.data_type, color=stored[0], color_srgb=stored[1], ao=int(ao.min()),
                           ao_max=int(ao.max()), rough=int(rough.max()), metal=int(metal.max()), albedo=int(alb.min()))
            assert ao.min() == ao.max() and rough.min() == rough.max() == ao.max() == metal.min() == metal.max(), n
        # decision 92: 0.5 within 1/65535 from the float one; from the byte one within the byte step it is stored in
        byte = round(grey['VG_B']['color_srgb'] * 255)
        step = q16(float(core.srgb_decode(byte / 255.0))) - q16(float(core.srgb_decode((byte - 1) / 255.0)))
        assert abs(grey['VG_F']['ao'] - 32768) <= 1, grey
        assert abs(grey['VG_B']['ao'] - 32768) <= step, (grey, step)
        found['0.5 grey'] = dict(grey, byte=byte, byte_step=step)
        # FL1, step 2.8: Albedo baked again from the material: the render attribute's colour, its source dropped
        vc_bake(['VF_C'], groups=['albedo'])
        want = vc_expect('FLOAT_COLOR', VC_RENDER)
        d28 = {k: int(np.abs(vc_values('VF_C', k) - want[k]).max()) for k in ('albedo_r', 'albedo_g', 'albedo_b')}
        assert max(d28.values()) <= 1, d28
        e = vc_entry('VF_C')
        assert 'source' not in e['channels']['albedo'] and e['channels']['rough']['source']['mode'] == 'OVERWRITE'
        found['2.8'] = f'albedo from the material: the render colour, deviation {max(d28.values())}, source dropped'
        # step 2.2 (FL2): a traced, denoised AO; Multiply by 1.0 byte-identical, by 0.5 half, twice a quarter
        va = bpy.data.objects['VA']
        vc_bake(['VA'], ao=True)
        e0 = vc_entry('VA')
        assert e0.get('denoise') and 'ao_source' not in e0 and os.path.isfile(vc_file('VA', 'ao.raw')), e0.keys()
        ao0, h0 = vc_values('VA', 'ao'), file_hash(vc_file('VA', 'ao'))
        assert int(ao0.max()) - int(ao0.min()) > 3000, (int(ao0.min()), int(ao0.max()))  # the occluder shows
        raw0 = file_hash(vc_file('VA', 'ao.raw'))
        vc_bake(['VA'], ao=True, sources={'ao': 'MULTIPLY'})
        assert file_hash(vc_file('VA', 'ao')) == h0, 'Multiply by 1.0 changed the AO image'
        vc_colors(va, 'FLOAT_COLOR', 'POINT', value=(0.5, 0.5, 0.5))
        vc_bake(['VA'], ao=True, sources={'ao': 'MULTIPLY'})
        half = int(np.abs(vc_values('VA', 'ao') - ao0 / 2.0).max())
        vc_bake(['VA'], ao=True, sources={'ao': 'MULTIPLY'})
        ao_q = vc_values('VA', 'ao')
        quarter = float(np.abs(ao_q - ao0 / 4.0).max())
        assert half <= 1 and quarter <= 1, (half, quarter)
        e1 = vc_entry('VA')
        assert e1['ao_source'] == dict(vertex_color='PAINT', attribute='SECOND', mode='MULTIPLY',
                                       attributes=['PAINT'] * 3), e1
        assert e1['denoise'] == e0['denoise'] and file_hash(vc_file('VA', 'ao.raw')) == raw0
        prod = core.load_master(VC_FOLDER, vc_stem('VA'), kind='ao_vc')
        pv = prod['image'][prod['filled']].astype(np.int64)
        assert int(np.abs(pv - 16384).max()) <= 1, (int(pv.min()), int(pv.max()))
        it = ch_item_vc('VA')
        assert it['grade'] == 'UP_TO_DATE' and it['dn_grade'] == 'UP_TO_DATE', (it['grade'], it['dn_grade'])
        found['2.2'] = (f'x 1.0 byte-identical; x 0.5 max {half} from half; twice max {quarter:g} from a quarter '
                        f'(in 1/65535); the product {int(pv.min())}..{int(pv.max())}, the raw bake and the denoise '
                        f'kept')
        # step 2.5 (FL4): a denoise-only run with another strength: the denoised raw bake times the kept product
        s.dn_strength = 0.5
        refresh()
        assert ch_item_vc('VA')['dn_grade'] == 'STALE', ch_item_vc('VA')['dn_grade']
        res = vc_bake(['VA'], ao=True, sources={'ao': 'MULTIPLY'}, scope='AUTO', expect='updated')
        assert 'vertex colour product' in res['VA']['what'], res['VA']
        got = vc_values('VA', 'ao')
        assert file_hash(vc_file('VA', 'ao_vc')) and vc_entry('VA')['ao_source']['mode'] == 'MULTIPLY'
        # the control: the same denoise of the same raw bake without the product (the entry as before the run, its
        # product and source taken away)
        index = store.read_index(VC_FOLDER, use_cache=False)
        ent = index['masters'][vc_stem('VA')]
        ent['denoise'] = e1['denoise']
        ent.pop('ao_source')
        store.write_index(VC_FOLDER, index)
        product = (Path(vc_file('VA', 'ao_vc'))).read_bytes()
        os.remove(vc_file('VA', 'ao_vc'))
        refresh()
        vc_bake(['VA'], ao=True, scope='AUTO', expect='updated')
        den = vc_values('VA', 'ao')
        want = np.round(den * (pv / 65535.0))
        d25 = int(np.abs(got - want).max())
        assert d25 <= 1 and int(np.abs(got - den).max()) > 1000, (d25, int(np.abs(got - den).max()))
        found['2.5'] = (f'max {d25} from the denoise (strength 0.5) of the raw bake times the product; '
                        f'{int(np.abs(got - den).max())} from that denoise alone')
        # put the product back (the master as the multiply left it) for step 2.4
        Path(vc_file('VA', 'ao_vc')).write_bytes(product)
        # step 2.4 (FL3): Overwrite: no raw bake, no product, the surroundings ignored; unticked: traced again
        vc_bake(['VA'], ao=True, sources={'ao': 'OVERWRITE'})
        e2 = vc_entry('VA')
        assert e2['ao_source']['mode'] == 'OVERWRITE' and e2.get('denoise') is None, e2
        assert not os.path.isfile(vc_file('VA', 'ao_vc')) and not os.path.isfile(vc_file('VA', 'ao.raw'))
        assert int(np.abs(vc_values('VA', 'ao') - q16(0.5)).max()) <= 1
        sur0 = ch_item_vc('VA')['surround_hash']
        s.distance = 0.12
        refresh()
        it = ch_item_vc('VA')
        assert it['surround_hash'] != sur0 and it['grade'] == 'UP_TO_DATE' and it['dn_grade'] == 'UP_TO_DATE', it
        assert ch_item_vc('VF_P')['grade'] == 'UP_TO_DATE'
        vc_bake(['VA'], ao=True)
        e3 = vc_entry('VA')
        assert 'ao_source' not in e3 and not os.path.isfile(vc_file('VA', 'ao_vc')) and e3.get('denoise'), e3.keys()
        ao3 = vc_values('VA', 'ao')
        assert int(ao3.max()) - int(ao3.min()) > 3000 and ch_item_vc('VA')['grade'] == 'UP_TO_DATE'
        s.distance = 0.1
        found['2.4'] = ('Overwrite: grade UP_TO_DATE after the AO distance changed (the surround hash changed), '
                        'denoise up to date; unticked: traced again (AO '
                        f'{int(ao3.min())}..{int(ao3.max())}), ao_source and .ao_vc.jxl gone')
        # step 2.3 (FL2): Multiply with no master, and after a mesh edit (a new layout): as Overwrite, reported
        want = vc_expect('FLOAT_COLOR', (0.6, 0.4, 0.2))
        res = vc_bake(['VN'], ao=True, groups=['rough'], sources={'ao': 'MULTIPLY', 'rough': 'MULTIPLY'})
        note = res['VN'].get('note', '')
        assert 'AO from Vertex Color Red: Multiply with no master of it, as Overwrite' in note, note
        dn = vc_dev('VN', {k: want[k] for k in ('ao', 'rough')})
        assert max(dn.values()) <= 1 and vc_entry('VN')['ao_source']['mode'] == 'OVERWRITE', dn
        vn = bpy.data.objects['VN']
        vn.data.vertices[6].co.z += 0.001
        vn.data.update()
        refresh()
        assert ch_item_vc('VN')['grade'] == 'MESH'
        layout0 = file_hash(core.master_paths(VC_FOLDER, vc_stem('VN'))[2])
        res = vc_bake(['VN'], ao=True, groups=['rough'], sources={'ao': 'MULTIPLY', 'rough': 'MULTIPLY'})
        note2 = res['VN'].get('note', '')
        assert 'Multiply with a new layout (the mesh changed), as Overwrite' in note2, note2
        dm = vc_dev('VN', {k: want[k] for k in ('ao', 'rough')})
        assert max(dm.values()) <= 1 and file_hash(core.master_paths(VC_FOLDER, vc_stem('VN'))[2]) != layout0, dm
        hm = {k: file_hash(vc_file('VN', k)) for k in ('ao', 'rough')}
        vc_bake(['VN'], ao=True, groups=['rough'], sources={'ao': 'OVERWRITE', 'rough': 'OVERWRITE'})
        assert {k: file_hash(vc_file('VN', k)) for k in ('ao', 'rough')} == hm, 'Overwrite differs from that Multiply'
        found['2.3'] = (f'no master: deviation {max(dn.values())}, note "{note}"; after the mesh edit: deviation '
                        f'{max(dm.values())}, a new layout, the AO and roughness images byte-identical to an '
                        f'Overwrite, note "{note2}"')
        # step 2.6: Albedo Multiply on a material albedo: the product in linear
        vc_bake(['VM'], groups=['albedo'])
        a_enc = [q16(core.srgb_encode(v)) for v in (0.6, 0.3, 0.1)]
        b_enc = [q16(core.srgb_encode(v)) for v in (0.5, 0.8, 0.25)]
        vc_bake(['VM'], groups=['albedo'], sources={'albedo': 'MULTIPLY'})
        want26 = {k: q16(core.srgb_encode(core.srgb_decode(a / 65535.0) * core.srgb_decode(b / 65535.0)))
                  for k, a, b in zip(core.CHANNEL_KINDS['albedo'], a_enc, b_enc)}
        ideal = {k: q16(core.srgb_encode(x * y)) for k, x, y in zip(core.CHANNEL_KINDS['albedo'], (0.6, 0.3, 0.1),
                                                                   (0.5, 0.8, 0.25))}
        d26, i26 = vc_dev('VM', want26), vc_dev('VM', ideal)
        assert max(d26.values()) <= 1 and max(i26.values()) <= 2, (d26, i26)
        assert vc_entry('VM')['channels']['albedo']['source'] == dict(vertex_color='PAINT', attribute='SECOND',
                                                                      mode='MULTIPLY')
        found['2.6'] = f'max {max(d26.values())} from the linear product of the two masters, {max(i26.values())} ' \
                       f'from (0.6, 0.3, 0.1) x (0.5, 0.8, 0.25) encoded'
        # Session 70's step 2.4: one colour attribute (the exporter's white) under SECOND: skipped, reported, the
        # master unchanged; Session 68's step 2.7: none, under ACTIVE: the same
        vx = bpy.data.objects['VX'].data
        added = [(a_.name, a_.data_type) for a_ in vx.color_attributes]  # the exporter's default white
        assert len(added) == 1, added
        vc_bake(['VX'], groups=['albedo'])
        files = {k: file_hash(vc_file('VX', k)) for k in core.CHANNEL_KINDS['albedo']}
        ent = vc_entry('VX')
        reasons = {}
        for case in ('SECOND', 'ACTIVE'):
            if case == 'ACTIVE':
                for a_ in list(vx.color_attributes):
                    vx.color_attributes.remove(a_)
                bpy.context.view_layer.update()
                assert len(vx.color_attributes) == 0, [a_.name for a_ in vx.color_attributes]
            s.vc_attribute = case
            try:
                res = vc_bake(['VX'], groups=['albedo'], sources={'albedo': 'OVERWRITE'}, expect='skipped')
            finally:
                s.vc_attribute = 'SECOND'
            reason = res['VX'].get('reason', '')
            why = 'no second colour attribute' if case == 'SECOND' else 'no colour attribute'
            assert f'Albedo from Vertex Color skipped: VX: {why}' in reason, res['VX']
            assert {k: file_hash(vc_file('VX', k)) for k in core.CHANNEL_KINDS['albedo']} == files
            assert vc_entry('VX') == ent
            log_text = (VC_WORK / 'vc.bake' / 'bake.log').read_text(encoding='utf-8')
            assert f'Albedo from Vertex Color skipped (VX: {why})' in log_text
            reasons[case] = reason
        found['70 2.4'] = (f'SECOND with one attribute {added}: "{reasons["SECOND"]}"; ACTIVE with none (taken '
                           f'away): "{reasons["ACTIVE"]}"; the albedo files and the entry unchanged')
    s.bake_ao, s.curvature, s.denoise = True, False, False
    ch_set(s, 'bake', ())
    select([])
    print(f'PASS: test_vertex_color_channels ({time.time() - t0:.1f} s; '
          + '; '.join(f'{k}: {v}' for k, v in found.items()) + ')')
    return found


def ch_item_vc(name):
    return store._state['items'][store._state['by_object'][name]]


def test_skip_sets_and_alpha():
    """Decision 110: an object of glass only is a master of the material channels alone (not in the AO counts, no AO
    bake or Apply for its set); an invisible material's object stays excluded. Decision 111: a Custom albedo's alpha
    in the master (albedo_a), Apply with the set's Alpha on into <material>_ALBD_RGBA16.png (alpha where baked,
    opaque elsewhere), off into <material>_ALBD_RGB16.png (RGB); a bake from the material removes the alpha."""
    t0 = time.time()
    build_vc_scene()
    s = bpy.context.scene.fss_ao_bake
    obs = bpy.data.objects
    glass = ch_material('VC_MAT_GLASS', (0.5, 0.5, 0.5))
    ch_plane('VGL', (15, 0, 0), glass)
    ch_plane('VIN', (17, 0, 0), ch_material('VC_MAT_INVIS'))
    found = {}
    try:
        with rule_unrecorded():
            refresh()
            it = ch_item_vc('VGL')
            assert it['channels_only'] and it['sets'] == ['VC_MAT_GLASS'], it
            assert store._state['excluded'].get('VIN') == 'skip materials only', store._state['excluded']
            assert 'VGL' not in store._state['excluded']
            n_ao = sum(1 for i_ in store._state['items'].values() if not i_.get('channels_only'))
            assert sum(store.counts()[g] for g in store.GRADES) == n_ao, (store.counts(), n_ao)
            row = store._state['sets']['VC_MAT_GLASS']
            assert row['channels_only'] and row['MISSING'] == 0, row
            assert store.bake_choice([vc_stem('VGL')], True, True, True)[0] == {}
            # a Custom albedo with its alpha, written straight into the master
            obs['VGL'].fss_ao_bake.albedo_value = (0.2, 0.5, 0.9)
            obs['VGL'].fss_ao_bake.albedo_alpha = 0.4
            s.albedo_source, s.cv_albedo_mode = 'CUSTOM', 'OVERWRITE'
            res = vc_bake(['VGL'], ao=True, groups=['albedo'])
            assert res['VGL']['baker'] == 'Custom value', res['VGL']
            assert not os.path.isfile(core.image_paths(VC_FOLDER, vc_stem('VGL'))[0]), 'an AO master was baked'
            ent = vc_entry('VGL')['channels']['albedo']
            assert ent.get('alpha') and ent['source'] == dict(custom=[0.2, 0.5, 0.9, 0.4], mode='OVERWRITE'), ent
            da = int(np.abs(vc_values('VGL', 'albedo_a') - q16(0.4)).max())
            assert da <= 1, da
            # Apply with Alpha on: RGBA, the alpha where baked, opaque elsewhere; the RGB the colour sRGB-encoded
            a = glass.fss_ao_apply
            a.albedo_target, a.albedo_alpha = 'FILE', True
            assert a.albedo_file_name == 'VC_MAT_GLASS_ALBD_RGBA16.png', a.albedo_file_name
            rep = ao_bake_apply.apply_set(bpy.context, glass, kind='albedo')
            assert 'error' not in rep, rep
            assert os.path.basename(rep['path']) == 'VC_MAT_GLASS_ALBD_RGBA16.png', rep['path']
            v, bits, ct = read(rep['path'])
            assert v.shape[2] == 4 and bits == 16 and ct == 6, (v.shape, bits, ct)
            wa = v[:, :, 3] != 65535
            assert wa.sum() == rep['alpha_px'] > 0, (int(wa.sum()), rep['alpha_px'])
            dal = int(np.abs(v[:, :, 3][wa].astype(np.int64) - q16(0.4)).max())
            enc = core.srgb_encode(np.array((0.2, 0.5, 0.9)))
            drgb = max(int(np.abs(v[:, :, c][wa].astype(np.int64) - q16(enc[c])).max()) for c in range(3))
            assert dal <= 1 and drgb <= 1, (dal, drgb)
            found['rgba'] = (int(wa.sum()), dal, drgb)
            # Alpha off: <material>_ALBD_RGB16.png, RGB
            a.albedo_alpha = False
            rep = ao_bake_apply.apply_set(bpy.context, glass, kind='albedo')
            assert os.path.basename(rep['path']) == 'VC_MAT_GLASS_ALBD_RGB16.png', rep['path']
            v3 = read(rep['path'])[0]
            assert v3.shape[2] == 3 and 'alpha_px' not in rep, (v3.shape, rep)
            assert np.array_equal(v3, v[:, :, :3]), 'the RGB differs from the RGBA file\'s'
            # the AO's default name, and no AO or curvature Apply for the glass set
            assert ao_bake_apply.default_file_name(glass) == 'VC_MAT_GLASS_COMP_RGB16.png'
            s.apply_ao, s.apply_cm = True, True
            for g in core.CHANNEL_GROUPS:
                setattr(s, f'apply_{g}', False)
            assert ao_bake_apply.apply(bpy.context, [glass]) == []
            assert ao_bake.target_problems(bpy.context, glass) == [], ao_bake.target_problems(bpy.context, glass)
            # from the material again: the alpha removed
            s.albedo_source = 'MATERIAL'
            vc_bake(['VGL'], groups=['albedo'])
            assert not os.path.isfile(vc_file('VGL', 'albedo_a')) and not vc_entry('VGL')['channels']['albedo'].get(
                'alpha'), vc_entry('VGL')['channels']['albedo']
    finally:
        s.albedo_source, s.cv_albedo_mode = 'MATERIAL', 'OVERWRITE'
        s.apply_ao, s.apply_cm = False, False
    print(f"PASS: test_skip_sets_and_alpha ({time.time() - t0:.1f} s; the glass object a master of the channels "
          f"alone, no AO baked or applied, the invisible one excluded; the alpha 0.4 in the master within {da}; "
          f"RGBA file: {found['rgba'][0]} px of alpha within {found['rgba'][1]}, RGB within {found['rgba'][2]}; "
          f"RGB file the same colours; a material bake removes the alpha)")


def test_custom_value_channels():
    """Decision 99: roughness and metal baked from each object's own value (Custom): Overwrite gives the value at every
    filled pixel, each object its own in one bake; Multiply onto the master's current value, as Overwrite without a
    master (reported); the entry's source and the result carry the value; a bake from the material drops the source.
    Decision 100: the albedo and emissive colours. Decision 101: the value written straight into the master gives
    Cycles' images within 1 on every pixel; a bake mixing the two. In the vertex colour test's scene."""
    t0 = time.time()
    build_vc_scene()
    s = bpy.context.scene.fss_ao_bake
    RM = ['rough', 'metal']
    obs = bpy.data.objects
    found = {}

    def dev(name, want):
        return {k: int(np.abs(vc_values(name, k) - q16(v)).max()) for k, v in want.items()}

    def cdev(name, g, lin):  # a colour channel's deviation from a linear colour, sRGB-encoded as the master keeps it
        enc = core.srgb_encode(np.array(lin, np.float64))
        return {f'{g}_{c}': int(np.abs(vc_values(name, f'{g}_{c}') - q16(enc[i])).max()) for i, c in enumerate('rgb')}
    try:
        with rule_unrecorded():
            refresh()
            vc_bake(['VM', 'VX'], groups=RM)  # from the material: roughness 0.5, metal 0.0
            assert max(dev('VM', dict(rough=0.5, metal=0.0)).values()) <= 1, dev('VM', dict(rough=0.5, metal=0.0))
            obs['VM'].fss_ao_bake.rough_value, obs['VM'].fss_ao_bake.metal_value = 0.3, 0.7
            obs['VX'].fss_ao_bake.rough_value, obs['VX'].fss_ao_bake.metal_value = 0.8, 0.2
            s.rough_source = s.metal_source = 'CUSTOM'
            assert s.cv_rough_mode == 'OVERWRITE' and s.cv_metal_mode == 'OVERWRITE'
            res = vc_bake(['VM', 'VX'], groups=RM)
            d = {n: dev(n, w) for n, w in (('VM', dict(rough=0.3, metal=0.7)), ('VX', dict(rough=0.8, metal=0.2)))}
            assert all(v <= 1 for dd in d.values() for v in dd.values()), d
            assert vc_entry('VM')['channels']['rough']['source'] == dict(custom=0.3, mode='OVERWRITE')
            assert vc_entry('VX')['channels']['metal']['source'] == dict(custom=0.2, mode='OVERWRITE')
            assert res['VM']['custom_value'] == {'rough': dict(value=0.3, mode='OVERWRITE'),
                                                 'metal': dict(value=0.7, mode='OVERWRITE')}, res['VM']
            assert 'vertex_color' not in res['VM'], res['VM']
            assert ch_item_vc('VM')['grade'] in ('MISSING', 'UP_TO_DATE')  # no AO baked here
            found['overwrite'] = d
            # decision 100: the albedo and the emissive from each object's own colour (linear, as Base Color gives
            # it), sRGB-encoded in the master; VX's emissive the default black
            obs['VM'].fss_ao_bake.albedo_value, obs['VM'].fss_ao_bake.emis_value = (0.2, 0.4, 0.8), (0.5, 0.25, 0.0)
            obs['VX'].fss_ao_bake.albedo_value = (0.9, 0.1, 0.3)
            s.albedo_source = s.emis_source = 'CUSTOM'
            res = vc_bake(['VM', 'VX'], groups=['albedo', 'emis'])
            dc = {n: dict(cdev(n, 'albedo', al), **cdev(n, 'emis', em))
                  for n, al, em in (('VM', (0.2, 0.4, 0.8), (0.5, 0.25, 0.0)), ('VX', (0.9, 0.1, 0.3), (0, 0, 0)))}
            assert all(v <= 1 for dd in dc.values() for v in dd.values()), dc
            assert vc_entry('VM')['channels']['albedo']['source'] == dict(custom=[0.2, 0.4, 0.8, 1.0],
                                                                          mode='OVERWRITE')  # decision 111: alpha
            assert res['VX']['custom_value']['emis'] == dict(value=[0.0, 0.0, 0.0], mode='OVERWRITE'), res['VX']
            # decision 101: written straight into the master, no Cycles: the same images, margins and all, as Cycles'
            # bake of the value (the test switch FSS_AO_BAKE_CUSTOM_CYCLES), Cycles first, the direct write last
            assert res['VM']['baker'] == 'Custom value' and 'direct_s' in res['VM'], res['VM']
            assert vc_entry('VM')['channels']['albedo']['samples'] == 0, vc_entry('VM')['channels']['albedo']
            all4 = ['albedo', 'rough', 'metal', 'emis']
            kinds8 = ['albedo_r', 'albedo_g', 'albedo_b', 'rough', 'metal', 'emis_r', 'emis_g', 'emis_b']

            def whole(n):
                return {k: core.load_master(VC_FOLDER, vc_stem(n), kind=k)['image'].astype(np.int64) for k in kinds8}
            os.environ['FSS_AO_BAKE_CUSTOM_CYCLES'] = '1'
            try:
                res_c = vc_bake(['VM', 'VX'], groups=all4)
            finally:
                os.environ.pop('FSS_AO_BAKE_CUSTOM_CYCLES', None)
            assert all(res_c[n]['baker'] == 'Cycles' and 'direct_s' not in res_c[n] for n in ('VM', 'VX')), res_c
            img_c = {n: whole(n) for n in ('VM', 'VX')}
            res_d = vc_bake(['VM', 'VX'], groups=all4)
            img_d = {n: whole(n) for n in ('VM', 'VX')}
            vs = {n: {k: int(np.abs(img_d[n][k] - img_c[n][k]).max()) for k in kinds8} for n in ('VM', 'VX')}
            n_px = {n: int(img_d[n]['rough'].size) for n in ('VM', 'VX')}
            assert all(v <= 1 for dd in vs.values() for v in dd.values()), vs
            # a kept layout: the value on exactly the stored map's filled pixels (VM's albedo has no 0 component)
            mvm = core.load_master(VC_FOLDER, vc_stem('VM'), kind='albedo_r')
            assert np.array_equal(mvm['image'] > 0, mvm['filled']), int(((mvm['image'] > 0) != mvm['filled']).sum())
            found['vs cycles'] = vs
            found['px'] = n_px
            found['map differs'] = {n: (res_c[n].get('map_differs_px'), res_d[n].get('map_differs_px'))
                                    for n in ('VM', 'VX')}
            found['times'] = {n: (res_c[n]['bake_s'], res_d[n]['direct_s'], res_d[n]['bake_s']) for n in ('VM', 'VX')}
            # Multiply in linear: VM's albedo (0.2, 0.4, 0.8) x (0.5, 1.0, 0.25)
            obs['VM'].fss_ao_bake.albedo_value = (0.5, 1.0, 0.25)
            s.cv_albedo_mode = 'MULTIPLY'
            s.emis_source = 'MATERIAL'
            vc_bake(['VM'], groups=['albedo'])
            dca = cdev('VM', 'albedo', (0.1, 0.4, 0.2))
            assert max(dca.values()) <= 2, dca
            found['colours'] = dc
            found['colour multiply'] = dca
            s.albedo_source = 'MATERIAL'
            # Multiply onto the current master: VM's roughness 0.3 x 0.5, its metal left as it is (Material off)
            obs['VM'].fss_ao_bake.rough_value = 0.5
            s.cv_rough_mode = 'MULTIPLY'
            s.metal_source = 'MATERIAL'
            vc_bake(['VM'], groups=['rough'])
            dm = dev('VM', dict(rough=0.15, metal=0.7))
            assert dm['rough'] <= 2 and dm['metal'] <= 1, dm
            assert vc_entry('VM')['channels']['rough']['source'] == dict(custom=0.5, mode='MULTIPLY')
            found['multiply'] = dm
            # Multiply without a master of it: as Overwrite, reported
            obs['VN'].fss_ao_bake.rough_value = 0.4
            res = vc_bake(['VN'], groups=['rough'])
            assert dev('VN', dict(rough=0.4))['rough'] <= 1, dev('VN', dict(rough=0.4))
            assert 'Roughness from Custom: Multiply with no master of it, as Overwrite' in res['VN'].get('note', ''), \
                res['VN']
            assert vc_entry('VN')['channels']['rough']['source'] == dict(custom=0.4, mode='OVERWRITE')
            # back to the material: its value, the source dropped
            s.rough_source = 'MATERIAL'
            vc_bake(['VM'], groups=['rough'])
            assert dev('VM', dict(rough=0.5))['rough'] <= 1 and 'source' not in vc_entry('VM')['channels']['rough']
            # decision 101, mixed: the albedo written directly, the roughness from the material through Cycles
            s.albedo_source, s.cv_albedo_mode = 'CUSTOM', 'OVERWRITE'
            res = vc_bake(['VM'], groups=['albedo', 'rough'])
            mix = dict(cdev('VM', 'albedo', (0.5, 1.0, 0.25)), **dev('VM', dict(rough=0.5)))
            assert max(mix.values()) <= 1, mix
            assert res['VM']['baker'] == 'Cycles' and 'direct_s' in res['VM'], res['VM']
            ch_vm = vc_entry('VM')['channels']
            assert ch_vm['albedo']['samples'] == 0 and ch_vm['rough']['samples'] > 0, ch_vm
            found['mixed'] = mix
    finally:
        s.rough_source = s.metal_source = s.albedo_source = s.emis_source = 'MATERIAL'
        s.cv_rough_mode = s.cv_metal_mode = s.cv_albedo_mode = s.cv_emis_mode = 'OVERWRITE'
    print(f"PASS: test_custom_value_channels ({time.time() - t0:.1f} s; Overwrite max deviation {found['overwrite']}, "
          f"each object its own value in one bake; the colours {found['colours']}, Multiply in linear "
          f"{found['colour multiply']}; Multiply 0.3 x 0.5 {found['multiply']}; Multiply without a master as "
          f"Overwrite, reported; the material again drops the source; decision 101: written directly, against "
          f"Cycles' bake of the value max {found['vs cycles']} on {found['px']} px, map differs (Cycles, direct) "
          f"{found['map differs']}, times (Cycles bake s, direct s, Cycles s in the direct bake) {found['times']}; "
          f"mixed direct and Cycles {found['mixed']})")


# ---------------------------------------------------------------------------------------------------------------------
# Decisions 93 to 95: Fetch the masters into the vertex colour, and the Emissive source (Session 73's step 2)
# ---------------------------------------------------------------------------------------------------------------------

FB_WORK = REPO_ROOT / 'tests' / '_work' / 'ao_bake_fetch'
FB_FOLDER = str(FB_WORK / 'fetch.bake')


def fb_attrs(obj, paint=None, first=True):
    """RENDER first (active and render, FLOAT_COLOR corner, VC_RENDER) and PAINT second (FLOAT_COLOR corner) with paint:
    an RGB triple everywhere or an (n_loops, 3) array; first=False: no RENDER (PAINT alone)."""
    me = obj.data
    if first:
        r = me.color_attributes.new('RENDER', 'FLOAT_COLOR', 'CORNER')
        r.data.foreach_set('color', np.tile([*VC_RENDER, 1.0], len(r.data)).astype(np.float32))
    if paint is not None:
        me.color_attributes.new('PAINT', 'FLOAT_COLOR', 'CORNER')
        fb_paint(obj, paint)
    if first:
        me.color_attributes.active_color = me.color_attributes['RENDER']
        me.color_attributes.default_color_name = 'RENDER'
    me.update()


def fb_paint(obj, paint, name='PAINT'):
    a = obj.data.color_attributes[name]
    n = len(a.data)
    v = np.ones((n, 4), np.float32)
    v[:, :3] = np.broadcast_to(np.asarray(paint, np.float32), (n, 3))
    a.data.foreach_set('color', v.ravel())
    obj.data.update()


def fb_colors(obj, name='PAINT'):
    a = obj.data.color_attributes[name]
    v = np.empty(len(a.data) * 4, np.float32)
    a.data.foreach_get('color', v)
    return v.reshape(-1, 4).astype(np.float64)


def build_fetch_scene():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    if FB_WORK.exists():
        shutil.rmtree(FB_WORK)
    FB_WORK.mkdir(parents=True)
    scene = bpy.context.scene
    scene.frame_set(1)
    s = scene.fss_ao_bake
    s.distance, s.samples, s.threads, s.padding, s.curv_padding = 0.1, 16, 12, PAD, PAD
    s.denoise = False
    set_baker(s)
    s.output_folder = str(FB_WORK / 'out')
    rng = np.random.default_rng(93)
    # step 2.1: per-corner random colours in the second attribute (2 x 2 quads: large faces against the texels)
    fr = ch_plane('FR', (0, 0, 0), vc_material('FB_MAT_FR'), n=2)
    fb_attrs(fr, rng.uniform(0.05, 0.95, (len(fr.data.loops), 3)))
    # step 2.2: a traced AO under an occluder, the second attribute constant
    ft = ch_plane('FT', (2, 0, 0), vc_material('FB_MAT_FT'), n=2)
    fb_attrs(ft, (0.3, 0.6, 0.9))
    occ = plane('FT_OCC', (2.02, 0.03, 0.03), None, 0, size=0.12, n=2)
    occ.rotation_euler = (0.0, 0.5, 0.0)
    # step 2.3: one colour attribute (RENDER alone), none (the exporter's white taken away in the test)
    fb_attrs(ch_plane('F1', (4, 0, 0), vc_material('FB_MAT_F1'), n=2))
    ch_plane('F0', (6, 0, 0), ch_material('FB_MAT_F0', (0.5, 0.5, 0.5)), n=2)
    # step 2.4: a Mirror modifier
    fm = ch_plane('FM', (8, 0, 0), vc_material('FB_MAT_FM'), n=2)
    fb_attrs(fm, (0.2, 0.4, 0.6))
    # step 2.6: a shared mesh of two copies (Average) and an object without a master, emissive from the vertex colour
    fe = ch_plane('FE', (10, 0, 0), vc_material('FB_MAT_FE'), n=2)
    fb_attrs(fe, (0.6, 0.3, 0.9))
    link(bpy.data.objects.new('FE2', fe.data)).location = (10.5, 0, 0)
    fb_attrs(ch_plane('FN', (12, 0, 0), vc_material('FB_MAT_FN'), n=2), (0.6, 0.3, 0.9))
    bpy.ops.wm.save_as_mainfile(filepath=str(FB_WORK / 'fetch.blend'))
    mod = fm.modifiers.new('Mirror', 'MIRROR')  # after the save: its master is baked from the plain mesh first
    mod.show_viewport = mod.show_render = False


def fb_bake(names, ao=False, groups=(), sources=None, scope='SELECTED', expect='baked'):
    s = bpy.context.scene.fss_ao_bake
    s.bake_ao, s.curvature = ao, False
    ch_set(s, 'bake', groups)
    vc_set(sources or {})
    select(names)
    try:
        assert bpy.ops.fss.ao_bake_start(scope=scope, hidden=True, wait=True) == {'FINISHED'}
    finally:
        vc_set({})
    status = store.read_status(FB_FOLDER)
    res = {r['name']: r for r in status['results']}
    assert status['state'] == 'done', status
    if expect:
        assert all(r['status'] == expect for r in res.values()), status['results']
    refresh()
    return res


def fb_values(name, kind):
    m = core.load_master(FB_FOLDER, store._state['by_object'][name], kind=kind)
    return m['image'][m['filled']].astype(np.int64)


def fb_fetch(names, what):
    """Fetch through the operator for these objects; (the operator's result, its report lines)."""
    from fss_blender_tools import ao_bake
    select(names)
    got = bpy.ops.fss.ao_fetch_vertex_color(what=what)
    return got, list(ao_bake._fetch_report)


def test_vertex_color_fetch():
    """Decisions 93 to 95 (Session 73's steps 2.1 to 2.6): Fetch Albedo, ORM and Emis read the masters at every face
    corner into the second colour attribute; the round trip from a vertex colour bake; only the channels with a master;
    a second attribute added only beside a first; modifiers that change the mesh skipped; undo; the Emissive from
    Vertex Color source."""
    t0 = time.time()
    build_fetch_scene()
    s = bpy.context.scene.fss_ao_bake
    found = {}
    OVER = {g: 'OVERWRITE' for g in ('ao', 'albedo', 'rough', 'metal', 'emis')}
    with rule_unrecorded():
        refresh()
        # step 2.1 (FL1): the round trip, each Fetch into a cleared attribute
        fr = bpy.data.objects['FR']
        painted = fb_colors(fr)[:, :3]
        fb_bake(['FR'], ao=True, groups=['albedo', 'rough', 'metal', 'emis'], sources=OVER)
        trip = {}
        for what in ('ORM', 'ALBEDO', 'EMIS'):
            fb_paint(fr, (0.0, 0.0, 0.0))
            got, lines = fb_fetch(['FR'], what)
            assert got == {'FINISHED'}, (what, lines)
            back = fb_colors(fr)
            d = np.abs(back[:, :3] - painted)
            assert (back[:, 3] == 1.0).all() and d.max() <= 1.0 / 255.0, (what, float(d.max()), lines)
            trip[what] = f'{float(d.max()) * 255:.3f}/255 at {len(back)} corners'
        assert [a.name for a in fr.data.color_attributes] == ['RENDER', 'PAINT']
        assert fr.data.color_attributes.active_color.name == 'RENDER' == fr.data.color_attributes.default_color_name
        found['2.1'] = f'largest difference {trip}; RENDER still active and render; the report "{lines[1]}"'
        # step 2.2 (FL2): a traced AO alone: red written, green and blue kept
        ft = bpy.data.objects['FT']
        fb_bake(['FT'], ao=True)
        got, lines = fb_fetch(['FT'], 'ORM')
        c = fb_colors(ft)
        ao = fb_values('FT', 'ao') / 65535.0
        assert got == {'FINISHED'} and (c[:, 1] == np.float32(0.6)).all() and (c[:, 2] == np.float32(0.9)).all(), c
        assert c[:, 0].min() >= ao.min() - 1e-6 and c[:, 0].max() <= ao.max() + 1e-6, (c[:, 0], ao.min(), ao.max())
        assert c[:, 0].max() - c[:, 0].min() > 0.05 and not np.any(np.isclose(c[:, 0], 0.3)), c[:, 0]
        assert '(AO)' in lines[1], lines
        found['2.2'] = (f'red {c[:, 0].min():.3f}..{c[:, 0].max():.3f} (the AO {ao.min():.3f}..{ao.max():.3f}), green '
                        f'and blue 0.6 and 0.9 at every corner; "{lines[1]}"')
        # step 2.3 (FL3): one attribute: FSS_Bake added after it; none: skipped, nothing added
        f1, f0 = bpy.data.objects['F1'], bpy.data.objects['F0']
        for a_ in list(f0.data.color_attributes):  # the exporter's default white
            f0.data.color_attributes.remove(a_)
        bpy.context.view_layer.update()
        fb_bake(['F1', 'F0'], ao=True)
        got, lines = fb_fetch(['F1', 'F0'], 'ORM')
        ca1 = f1.data.color_attributes
        assert [a.name for a in ca1] == ['RENDER', 'FSS_Bake'], [a.name for a in ca1]
        assert ca1.active_color.name == 'RENDER' and ca1.default_color_name == 'RENDER'
        assert ca1['FSS_Bake'].domain == 'CORNER' and ca1['FSS_Bake'].data_type == 'FLOAT_COLOR'
        c1 = fb_colors(f1, 'FSS_Bake')
        assert (c1[:, 1:] == 1.0).all(), c1  # white where no roughness and metal master is
        assert len(f0.data.color_attributes) == 0 and 'F0: no colour attribute' in lines, lines
        line1 = next(x for x in lines if x.startswith('F1:'))
        assert 'FSS_Bake added as the second colour attribute' in line1, lines
        found['2.3'] = f'"{line1}"; RENDER still active and render; "F0: no colour attribute", nothing added'
        # step 2.4 (FL4): a Mirror modifier: skipped, its attributes unchanged
        fm = bpy.data.objects['FM']
        fb_bake(['FM'], ao=True)
        fm.modifiers['Mirror'].show_viewport = True
        bpy.context.view_layer.update()
        before = vc_attr_state('FM')
        got, lines = fb_fetch(['FM'], 'ORM')
        assert got == {'CANCELLED'} and 'FM: its modifiers change the mesh' in lines, (got, lines)
        assert vc_attr_state('FM') == before
        fm.modifiers['Mirror'].show_viewport = False
        found['2.4'] = '"FM: its modifiers change the mesh", the attributes unchanged'
        # step 2.6 (FL5): Emissive from Vertex Color, Overwrite and Multiply; a shared mesh not combined
        bpy.data.objects['FE'].data.fss_ao_shared.combine = 'AVERAGE'
        res = fb_bake(['FE', 'FE2'], groups=['emis'], sources={'emis': 'OVERWRITE'})
        want = {k: q16(core.srgb_encode(v)) for k, v in zip(core.CHANNEL_KINDS['emis'], (0.6, 0.3, 0.9))}
        d_over = max(int(np.abs(fb_values('FE', k) - v).max()) for k, v in want.items())
        e = store.read_index(FB_FOLDER, use_cache=False)['masters'][store._state['by_object']['FE']]
        ce = e['channels']['emis']
        assert d_over <= 1 and ce['source'] == dict(vertex_color='PAINT', attribute='SECOND', mode='OVERWRITE'), ce
        assert 'combine' not in ce and 'copies' not in ce, ce
        h1 = {k: file_hash(core.image_paths(FB_FOLDER, store._state['by_object']['FE'], k)[0]) for k in want}
        fb_paint(bpy.data.objects['FE'], (1.0, 1.0, 1.0))
        fb_bake(['FE', 'FE2'], groups=['emis'], sources={'emis': 'MULTIPLY'})
        assert {k: file_hash(core.image_paths(FB_FOLDER, store._state['by_object']['FE'], k)[0]) for k in want} == h1
        before_half = {k: fb_values('FE', k) for k in want}
        fb_paint(bpy.data.objects['FE'], (0.5, 0.5, 0.5))
        fb_bake(['FE', 'FE2'], groups=['emis'], sources={'emis': 'MULTIPLY'})
        d_half = max(int(np.abs(fb_values('FE', k) - np.round(core.srgb_encode(
            core.srgb_decode(before_half[k] / 65535.0) * 0.5) * 65535.0)).max()) for k in want)
        res = fb_bake(['FN'], groups=['emis'], sources={'emis': 'MULTIPLY'})
        note = res['FN'].get('note', '')
        assert 'Emissive from Vertex Color: Multiply with no master of it, as Overwrite' in note, note
        d_none = max(int(np.abs(fb_values('FN', k) - v).max()) for k, v in want.items())
        assert d_half <= 1 and d_none <= 1, (d_half, d_none)
        found['2.6'] = (f'Overwrite deviation {d_over} (the shared mesh not combined: no combine in its entry); '
                        f'Multiply by 1.0 byte-identical, by 0.5 max {d_half} from half in linear; with no master '
                        f'deviation {d_none}, "{note}"')
        # step 2.5: undo (the background Blender's undo, if it has one)
        fr = bpy.data.objects['FR']
        fb_paint(fr, (0.25, 0.5, 0.75))
        prior = fb_colors(fr)
        undo = ''
        try:
            bpy.ops.ed.undo_push(message='before Fetch')
            got, lines = fb_fetch(['FR'], 'ALBEDO')
            assert got == {'FINISHED'} and not np.allclose(fb_colors(fr), prior)
            r_ = bpy.ops.ed.undo()
            fr = bpy.data.objects['FR']
            undo = (f'ed.undo {r_}: the attribute as before the Fetch' if np.allclose(fb_colors(fr), prior)
                    else f'ed.undo {r_}: the attribute NOT as before the Fetch')
        except RuntimeError as exc:
            undo = f'not available in the background Blender ({str(exc).splitlines()[0][:120]})'
        found['2.5'] = undo
    s.bake_ao, s.curvature = True, False
    ch_set(s, 'bake', ())
    select([])
    print(f'PASS: test_vertex_color_fetch ({time.time() - t0:.1f} s; '
          + '; '.join(f'{k}: {v}' for k, v in found.items()) + ')')
    return found


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
    test_apply_ticked()
    test_resolution_choice()
    test_soften_edges()
    test_soften_thin_faces()
    test_apply_steps()
    test_draw()
    test_panel_selection()
    test_shown_without_view()
    test_custom_occluders()
    test_custom_add_ignore()
    test_detected()
    test_tree()
    test_oriented_rule()
    test_option_staleness()
    test_auto_distance()
    test_falloff()
    test_falloff_distances()
    test_object_uv()
    test_curvature()
    test_curvature_only()
    test_native_copy()
    test_native_open()
    test_native_png()
    test_native_compose()  # bake-post-native journal: the composition in C++
    test_unavailable()  # apply-native-copy decision 6: the DLL and libjxl required
    test_corner_rule()
    test_denoise()
    test_denoise_oidn()
    test_shared_combine()
    test_run_mode()
    test_unsaved()
    test_object_preview()
    test_poses()  # last: it replaces the scene with the wheel's
    test_move_together()  # in the wheel's scene
    test_material_channels()  # decisions 79 to 83, in a scene of its own
    test_vertex_color_channels()  # decisions 88 to 90, in a scene of its own
    test_custom_value_channels()  # decision 99, in the vertex colour test's scene
    test_skip_sets_and_alpha()  # decisions 110 and 111, in the vertex colour test's scene built again
    test_vertex_color_fetch()  # decisions 93 to 95, in a scene of its own
    n_ref = REF.done(complete=True)
    print(f'PASS: reference values ({n_ref} cases equal to the values the Python code gave before decision 6)')
    n_rule = RULE.done(complete=True)
    print(f'PASS: scene rule reference ({n_rule} Refreshes and Detected-tree Refreshes equal to the Python code\'s '
          f'lists, hashes and grades; the largest gap difference {RULE.worst:.3g} m)')
    print(f'ALL AO BAKE TESTS PASSED ({time.time() - t0:.1f} s)')
