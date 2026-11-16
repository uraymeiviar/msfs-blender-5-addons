"""AO Bake: the script of the second Blender that bakes the masters (auto-bake journal, decisions 12, 15, 16, 27, 34 to
36).

Started by ao_bake_store.start_bake on a snapshot of the artist's current state (the bake folder's snapshot.blend):
    blender --factory-startup [-b] <snapshot.blend> --python ao_bake_runner.py -- <job.json>
Hidden (-b, the default run mode, decision 36) it bakes the tiles one after another; with a window it bakes one tile
per timer step, so the window keeps updating (its 3D views are turned into empty Image Editors, so the scene is not
drawn). It shows and writes no picture of the master (OptiX baker decisions 30 and 31: the FSS OptiX window shows the
only one); a thumbnail an older version wrote (<stem>.ao.thumb) is removed when the master is baked again. It
loads ao_bake_core.py by its path (the add-on is not enabled in this Blender), prints one line per object (and per
tile), writes status.json (object n of m, tile i of n) and stops when a file `cancel` appears in the bake folder:
between objects, or between tiles, in which case the object keeps its old master. It never saves the .blend and quits
without saving when done.

Per master (P35, decisions 15 and 30; the prototype's step3_master.py): the target's evaluated triangles of a texture
set (a material that is not a skip material), in world space moved so the target's bounds are centred at the origin;
the occluders the job lists (evaluated, skip faces dropped, moved the same way), as temporary objects in a scene of
the bake's own that holds nothing else (decision 52). The master layout at 4 x the target's median density. The bake
in tiles (decisions 31, 32): the master's pixel area is cut into square tiles whose size fits the memory budget
(ao_bake_core.choose_tile); each tile is one Cycles bake of the core triangles that overlap it, then one of the
skirt's, with UVs relative to the tile, into a tile-sized image (Cycles clips a triangle at the image's edges: Session
20), each tile with its own seed. The master is
paged (decision 33, Session 23): a row of tiles is a band; the bands are baked from the top, and once a band is baked
the band above it is composed (it now has its halo) and written to <stem>.ao.map and, for the AO, to a raw scratch file
row by row, then dropped; only two bands are held, never the whole master. At the end the AO is encoded as lossless
JPEG XL, <stem>.ao.jxl (decision 37; apply-native-copy decision 6: without libjxl or fss_ao_copy.dll the job fails
at its start, the reason in the log and the status), then
<stem>.ao.npz (the layout); index.json gets the master's entry with the tile size, the peak working set and the
image's format, size and encoding time.

A mover in N poses (decision 34): the layout and the target's triangles are those of the current frame; for each pose
frame the scene is set to that frame once, before the tiles, to read the target's placement (its world matrix
relative to the current frame) and to build the meshes of the occluders posed with it (a custom list's movers,
decision 35); then the scene goes back to the current frame. Each tile is baked in every pose before the next tile:
the target and its bake pieces are placed by the pose's matrix, the posed occluders of the other poses are hidden from
rendering, and the pose's red channel is summed per pixel in the tile's own buffers (float64 and a count, 12 bytes
per tile pixel); the mean is quantized once. So memory does not grow with N; time grows N times (the Cycles bakes).
Pose p's seeds add core.POSE_SEED x p (pose 0 keeps the one-pose seeds). A mover whose evaluated mesh deforms between
poses is baked in the current frame only, said in the log and the report.

FSS OptiX (OptiX baker journal 20261114.optix-baker.md, decisions 21 to 25): with the job's Baker Auto or FSS OptiX the
runner starts the add-on's aobaker.exe (ao_bake_native.Baker: its window in a Visible run, hidden otherwise) and,
when its GPU works, every master's scene goes to it once (the target, the occluders as arrays, the views of its poses
and copies, built as for Cycles) and each tile is one request that returns the core's and the skirt's AO with the
views already combined; the composition, the bands, Cancel and the writer are the same; the baker
makes its window's preview from the tiles it bakes (decision 29). The curvature and the OIDN denoise then run in the
baker too. Its samples are the job's optix_samples (decision 24). When it cannot
start, or fails on a master, that master and the rest of the job bake with Cycles, and the log says why (decision 22).
The index entry records the baker that made the master (decision 23).
"""
import importlib.util
import json
import math
import os
import sys
import time
import traceback

import bpy
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location('_fss_ao_bake_core', os.path.join(HERE, 'ao_bake_core.py'))
core = importlib.util.module_from_spec(_spec)
sys.modules['_fss_ao_bake_core'] = core
_spec.loader.exec_module(core)
_nspec = importlib.util.spec_from_file_location('_fss_ao_bake_native', os.path.join(HERE, 'ao_bake_native.py'))
native = importlib.util.module_from_spec(_nspec)
sys.modules['_fss_ao_bake_native'] = native
_nspec.loader.exec_module(native)
native.CORE = core

JOB_PATH = sys.argv[sys.argv.index('--') + 1]
with open(JOB_PATH, encoding='utf-8') as _f:
    JOB = json.load(_f)
FOLDER = JOB['folder']
STATUS = os.path.join(FOLDER, 'status.json')
CANCEL = os.path.join(FOLDER, 'cancel')
LOG = os.path.join(FOLDER, 'bake.log')
SET = JOB['settings']
SPLIT = bool(SET.get('sample_split'))  # decision 49: averaged views share the sample count
ITEMS = JOB['items']
BAKE = {}  # decision 52: the bake's own scene
TMP = 'FSS_AO_BAKE_TMP'
# the memory budget (decision 32): FSS_AO_BAKE_MEMORY_GB (tests) or the job's, else a share of the free memory
_override = os.environ.get('FSS_AO_BAKE_MEMORY_GB') or JOB.get('memory_budget_gb')
BUDGET = core.memory_budget(_override)
PROFILE = {} if os.environ.get('FSS_AO_BAKE_PROFILE') else None  # Session 38: per-call times in the log
SEED_OFFSET = int(os.environ.get('FSS_AO_BAKE_SEED_OFFSET') or 0)  # tests only: a control bake with other noise
BUDGET_SOURCE = f'override {_override} GB' if _override else (
    f'{core.BUDGET_SHARE:.0%} of the free memory, at most {core.BUDGET_MAX // 2 ** 30} GB')
BAKER = SET.get('baker', 'CYCLES')  # OptiX baker decision 22: AUTO, OPTIX or CYCLES (a job of an older add-on: Cycles)
OPTIX_SAMPLES = int(SET.get('optix_samples') or 4096)  # decision 24: FSS OptiX's own samples
NATIVE = dict(baker=None, why='', failed=False)  # the running FSS OptiX baker, or why Cycles bakes
STATUS_EVERY_S = 0.5  # status.json during a tile of FSS OptiX at most this often


class NativeFailed(RuntimeError):
    """FSS OptiX failed on a master: it is baked again with Cycles, and so is the rest of the job (decision 22)."""


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


state = dict(state='running', n_done=0, n_total=len(ITEMS), current='', tile=0, n_tiles=0, started=time.time(),
             elapsed_s=0.0, left_s=None, results=[], pid=os.getpid(), job=os.path.basename(JOB_PATH))


def _replace(tmp, path, tries=100):
    """os.replace, retried while the artist's Blender has the file open for reading (Windows refuses the replace)."""
    for k in range(tries):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if k == tries - 1:
                raise
            time.sleep(0.01)


def write_status():
    state['elapsed_s'] = round(time.time() - state['started'], 2)
    # done: the objects finished plus the current one's share (its tiles, and its poses or views inside a tile)
    done = state['n_done']
    nt, npz = state.get('n_tiles') or 0, state.get('n_poses') or 0
    if nt and done < state['n_total']:
        done += ((max(state.get('tile') or 1, 1) - 1) + (max(state.get('pose') or 1, 1) - 1) / max(npz, 1)) / nt
    state['progress'] = round(done / max(state['n_total'], 1), 4)  # the panel's bar moves with tiles and views
    if done > 0:
        state['left_s'] = round(state['elapsed_s'] / done * (state['n_total'] - done), 1)
    tmp = STATUS + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=1)
    _replace(tmp, STATUS)


def update_index(entry):
    path = os.path.join(FOLDER, 'index.json')
    index = dict(schema=core.SCHEMA, masters={})
    if os.path.isfile(path):
        try:
            with open(path, encoding='utf-8') as f:
                index = json.load(f)
        except (OSError, ValueError):
            log('index.json unreadable, written anew')
    index['schema'] = core.SCHEMA
    index['settings'] = dict(ao_distance=SET['ao_distance'], samples=SET['samples'], baker=BAKER,
                             optix_samples=OPTIX_SAMPLES, **core.method_settings())
    index.setdefault('masters', {})[entry['key']] = entry
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(index, f, indent=1)
    _replace(tmp, path)


# ---------------------------------------------------------------------------------------------------------------------
# Scene and Cycles (tests/bake_prototype/bake_common.py)
# ---------------------------------------------------------------------------------------------------------------------

def setup_scene():
    """Decision 52: the bake runs in a scene of its own that holds only the bake's temporary objects, so Cycles and
    the depsgraph do not go through the file's objects on every bake call; the file's scene is left as loaded (its
    frames are still set for the poses). Returns the collection of the temporary objects."""
    scene = bpy.data.scenes.new('FSS_AO_BAKE_SCENE')
    BAKE['scene'] = scene
    coll = bpy.data.collections.new(TMP)
    scene.collection.children.link(coll)
    scene.render.engine = 'CYCLES'
    cy = scene.cycles
    cy.use_denoising = False
    cy.use_adaptive_sampling = False
    cy.use_animated_seed = False
    scene.render.threads_mode = 'FIXED'
    scene.render.threads = int(SET['threads'])
    scene.world = bpy.data.worlds.new('FSS_AO_BAKE_WORLD')
    scene.world.light_settings.distance = float(SET['ao_distance'])
    cy.device = 'CPU'
    try:
        prefs = bpy.context.preferences.addons['cycles'].preferences
        prefs.compute_device_type = 'NONE'
        if SET['device'] == 'GPU':
            for kind in ('OPTIX', 'CUDA', 'HIP', 'ONEAPI', 'METAL'):
                try:
                    prefs.compute_device_type = kind
                except TypeError:
                    continue
                prefs.get_devices()
                gpus = [d for d in prefs.devices if d.type == kind]
                if gpus:
                    for d in prefs.devices:
                        d.use = d.type == kind
                    cy.device = 'GPU'
                    log(f'device GPU ({kind}: {", ".join(d.name for d in gpus)})')
                    break
            else:
                prefs.compute_device_type = 'NONE'
                log('device GPU asked, none found: CPU')
    except Exception as exc:  # noqa: BLE001
        log(f'device setup: {exc}; CPU')
    return coll


def build_mesh(name, positions, tris, corner_normals, uv_tc2=None):
    me = bpy.data.meshes.new(name)
    me.from_pydata(np.asarray(positions, dtype=np.float64).tolist(), [], np.asarray(tris).tolist())
    me.update(calc_edges=True)
    if len(me.polygons) != len(tris):
        raise RuntimeError(f'{name}: from_pydata kept {len(me.polygons)} of {len(tris)} faces')
    if uv_tc2 is not None:
        layer = me.uv_layers.new(name='BAKE_UV')
        layer.uv.foreach_set('vector', np.asarray(uv_tc2, dtype=np.float32).ravel())
    me.shade_smooth()
    me.normals_split_custom_set(np.asarray(corner_normals, dtype=np.float64).reshape(-1, 3).tolist())
    me.update()
    return me


def set_ray_invisible(obj):
    for attr in ('visible_camera', 'visible_diffuse', 'visible_glossy', 'visible_transmission',
                 'visible_volume_scatter', 'visible_shadow'):
        setattr(obj, attr, False)


def new_float_image(name, w, h):
    img = bpy.data.images.new(name, int(w), int(h), alpha=False, float_buffer=True, is_data=True)
    img.colorspace_settings.name = 'Non-Color'
    return img


def clear_image(img, px):
    """The image filled with -1 (not baked), alpha 1; px: the tile's float buffer, reused."""
    px.fill(-1.0)
    px[3::4] = 1.0
    img.pixels.foreach_set(px)


def read_red(img, px):
    """The bake's red channel (h, w) float32, a view into px."""
    w, h = img.size
    img.pixels.foreach_get(px)
    return px.reshape(h, w, 4)[:, :, 0]


def bake(obj, img, seed, from_obj, samples=None):
    """The prototype's bake: AO Selected to Active from `from_obj` into img (pre-filled with -1), margin 0; in the
    bake's own scene (decision 52)."""
    scene = BAKE['scene']
    view_layer = scene.view_layers[0]
    scene.cycles.samples = int(samples or SET['samples'])
    scene.cycles.seed = seed
    mat = bpy.data.materials.new('FSS_AO_BAKE_MAT')
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    bsdf = nt.nodes.new('ShaderNodeBsdfDiffuse')
    nt.links.new(bsdf.outputs[0], out.inputs[0])
    tex = nt.nodes.new('ShaderNodeTexImage')
    tex.image = img
    nt.nodes.active = tex
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    uv = obj.data.uv_layers['BAKE_UV']
    obj.data.uv_layers.active = uv
    uv.active_render = True
    for o in view_layer.objects:
        if o is not None:
            o.select_set(False, view_layer=view_layer)
    from_obj.select_set(True, view_layer=view_layer)
    obj.select_set(True, view_layer=view_layer)
    view_layer.objects.active = obj
    rb = scene.render.bake
    rb.margin = 0
    rb.use_clear = False
    rb.use_selected_to_active = True
    rb.target = 'IMAGE_TEXTURES'
    t = time.time()
    kw = dict(type='AO', margin=0, margin_type='ADJACENT_FACES', use_clear=False, use_selected_to_active=True,
              target='IMAGE_TEXTURES', cage_extrusion=core.EXTRUSION, max_ray_distance=core.RAY_DISTANCE,
              use_cage=False)
    sel = [from_obj, obj]  # the operator reads these from the context, not from the view layer
    with bpy.context.temp_override(scene=scene, view_layer=view_layer, active_object=obj, object=obj,
                                   selected_objects=sel, selected_editable_objects=sel):
        bpy.ops.object.bake(**kw)
    dt = time.time() - t
    bpy.data.materials.remove(mat)
    return dt


def temp_object(coll, name, me):
    obj = bpy.data.objects.new(name, me)
    coll.objects.link(obj)
    obj.hide_render = False
    return obj


def occluder_mesh(obj, depsgraph, skip_slots, shift):
    import bmesh
    from mathutils import Matrix, Vector
    me = bpy.data.meshes.new_from_object(obj.evaluated_get(depsgraph), preserve_all_data_layers=True,
                                         depsgraph=depsgraph)
    if skip_slots:
        bm = bmesh.new()
        bm.from_mesh(me)
        faces = [f for f in bm.faces if f.material_index in skip_slots]
        bmesh.ops.delete(bm, geom=faces, context='FACES')
        bm.to_mesh(me)
        bm.free()
    me.materials.clear()
    me.transform(Matrix.Translation(Vector(-shift)) @ obj.matrix_world)
    return me


# ---------------------------------------------------------------------------------------------------------------------
# One master, in tiles (decisions 31 and 32)
# ---------------------------------------------------------------------------------------------------------------------

def hide_views():
    """Decision 36: in a window, no 3D view, so the window does not draw the whole scene."""
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.type = 'IMAGE_EDITOR'
    except Exception as exc:  # noqa: BLE001  (only what the window draws; the bake goes on)
        log(f'the 3D views stay ({type(exc).__name__}: {exc})')


def _remove(objs):
    for o in objs:
        if o is None or o.name not in bpy.data.objects:
            continue
        me = o.data
        bpy.data.objects.remove(o)
        if me is not None and me.users == 0:
            bpy.data.meshes.remove(me)
    BAKE['scene'].view_layers[0].update()  # else the view layer's object list keeps the removed objects as None


def _bake_piece(coll, name, positions, normals, uv, img, px, seed, target, matrix=None, samples=None):
    """One Cycles bake of these triangles (already relative to the tile) into the tile image; returns (red, seconds).
    matrix: the pose's placement of the target (decision 34), None for the current frame."""
    t0 = time.perf_counter()
    n = len(positions)
    me = build_mesh(name, positions.reshape(-1, 3), np.arange(n * 3).reshape(-1, 3), normals, uv)
    obj = temp_object(coll, name, me)
    if matrix is not None:
        obj.matrix_world = matrix
    set_ray_invisible(obj)
    t1 = time.perf_counter()
    try:
        clear_image(img, px)
        t2 = time.perf_counter()
        dt = bake(obj, img, seed, target, samples)
        t3 = time.perf_counter()
    finally:
        _remove([obj])
    t4 = time.perf_counter()
    red = read_red(img, px)
    if PROFILE is not None:  # Session 38: where a bake call's time goes
        for k, v in (('build', t1 - t0), ('clear', t2 - t1), ('bake', t3 - t2), ('remove', t4 - t3),
                     ('read', time.perf_counter() - t4)):
            PROFILE[k] = PROFILE.get(k, 0.0) + v
        PROFILE['calls'] = PROFILE.get('calls', 0) + 1
        PROFILE['px'] = PROFILE.get('px', 0) + img.size[0] * img.size[1]
    return red, dt


def pose_setup(obj, frames, ref_co, shift, posed_occ):
    """Decision 34: for each pose frame, the target's placement relative to the current frame (in the bake's space,
    moved by -shift) and the meshes of the occluders posed with it; the scene back at the current frame afterwards.
    None when the target's mesh deforms between poses (its evaluated vertices in object space differ)."""
    from mathutils import Matrix
    scene = bpy.context.scene
    f0, s0 = scene.frame_current, scene.frame_subframe
    to_bake = np.eye(4)
    to_bake[:3, 3] = -shift
    from_bake = np.eye(4)
    from_bake[:3, 3] = shift
    inv_ref = np.linalg.inv(np.array(obj.matrix_world, dtype=np.float64))
    mats, meshes = [], []
    deforms = False
    try:
        for f in frames:
            fi = int(math.floor(f))
            scene.frame_set(fi, subframe=float(f - fi))
            dg = bpy.context.evaluated_depsgraph_get()
            co = core.evaluated_triangles(obj, dg)['co']
            if co.shape != ref_co.shape or not np.allclose(co, ref_co, rtol=0.0, atol=1e-6):
                deforms = True
                break
            M = to_bake @ np.array(obj.matrix_world, dtype=np.float64) @ inv_ref @ from_bake
            mats.append(Matrix(M.tolist()))
            meshes.append([occluder_mesh(o, dg, skip, shift) for o, skip in posed_occ])
    finally:
        scene.frame_set(f0, subframe=s0)
    if deforms:
        for mes in meshes:
            for me in mes:
                bpy.data.meshes.remove(me)
        return None
    return mats, meshes


def setup_copies(item, first, dg, shift, coll, temps, poses):
    """Decision 47: the views of a shared mesh. Per copy (its object in the snapshot): the target's placement at the
    copy (relative to the first copy, whose world positions the target has), each occluder of its list once as a
    temporary object (shared between copies' lists), and per pose of a moving copy its placement and its posed
    occluders. Fills poses['views'] ({mat, vis: occluder names shown, copy}), ['occ_all'], ['combine']; returns (number
    of views, notes)."""
    from mathutils import Matrix
    to_bake = np.eye(4)
    to_bake[:3, 3] = -shift
    from_bake = np.eye(4)
    from_bake[:3, 3] = shift
    inv_first = np.linalg.inv(np.array(first.matrix_world, dtype=np.float64))
    static = {}
    views, notes = [], []
    for ci, c in enumerate(item['copies']):
        o = bpy.data.objects.get(c['object'])
        if o is None or o.type != 'MESH':
            notes.append(f"{c['object']}: not in the baked file, left out")
            continue
        X = to_bake @ np.array(o.matrix_world, dtype=np.float64) @ inv_first @ from_bake
        vis, posed_occ = [], []
        for occ in c['occluders']:
            oc = bpy.data.objects.get(occ['name'])
            if oc is None or oc.type != 'MESH':
                continue  # another copy of the same mesh nearby does occlude (as a temporary object, like any other)
            if c.get('poses') and occ.get('posed'):
                posed_occ.append((oc, set(occ['skip_slots'])))
                continue
            if oc.name not in static:
                t = temp_object(coll, 'FSS_AO_OCC', occluder_mesh(oc, dg, set(occ['skip_slots']), shift))
                temps.append(t)
                static[oc.name] = t
            vis.append(static[oc.name].name)
        got = None
        if c.get('poses'):
            ref_co = core.evaluated_triangles(o, dg)['co']
            got = pose_setup(o, c['poses'], ref_co, shift, posed_occ)
            if got is None:
                notes.append(f"{o.name}: its mesh deforms between poses: baked in the current frame")
        if got is None:
            for oc, skip in posed_occ:  # at the current frame
                t = temp_object(coll, 'FSS_AO_OCC', occluder_mesh(oc, dg, skip, shift))
                temps.append(t)
                vis.append(t.name)
            views.append(dict(mat=Matrix(X.tolist()), vis=set(vis), copy=ci, name=o.name, cpose=1, cposes=1))
        else:
            mats, meshes = got
            for p, mes in enumerate(meshes):
                objs = [temp_object(coll, 'FSS_AO_OCC_POSE', me) for me in mes]
                temps.extend(objs)
                M = np.array(mats[p], dtype=np.float64) @ X
                views.append(dict(mat=Matrix(M.tolist()), vis=set(vis) | {t.name for t in objs}, copy=ci, name=o.name,
                                  cpose=p + 1, cposes=len(meshes)))
    order = {c: k + 1 for k, c in enumerate(dict.fromkeys(v['copy'] for v in views))}
    combine = item.get('combine') or 'AVERAGE'
    for v in views:
        v['n'] = order[v['copy']]
        # decision 49: samples in proportion to the view's weight in the result: the average of copies weighs each
        # view 1 / (copies x its copy's poses); lightest and darkest keep each copy whole, split over its poses only
        share = v['cposes'] * (len(order) if combine in ('AVERAGE', 'ONE') else 1)
        v['samples'] = core.view_samples(SET['samples'], share, SPLIT)
    poses['n_copies'] = len(order)
    poses['views'] = views
    poses['occ_all'] = [t for t in temps if t.name.startswith('FSS_AO_OCC')]
    poses['combine'] = combine
    return len(views), notes


def native_scene(item, obj, dg, shift, frames, ref_co, samples):
    """The FSS OptiX scene of a master: the occluders as arrays in the bake's space (each object's evaluated triangles
    without its skip faces, moved by -shift, as occluder_mesh) and the views the baker combines per pixel, built as
    setup_copies and pose_setup build Cycles' (decisions 34, 35, 47, 49): per view the target's placement (4 x 4, bake
    space), its copy (numbered from 0, a copy's views together), its samples and the occluders it sees. Returns
    dict(occluders, views, combine, frames, pose_note, log)."""
    occluders = []
    lines = []
    to_bake = np.eye(4)
    to_bake[:3, 3] = -shift
    from_bake = np.eye(4)
    from_bake[:3, 3] = shift

    def add(o, skip, depsgraph=None):
        ev = core.evaluated_triangles(o, depsgraph or dg)
        p, _cn = core.to_world(ev, shift)
        keep = ~np.isin(ev['mat'], list(skip)) if skip else np.ones(len(ev['tris']), dtype=bool)
        occluders.append((p.astype(np.float32), ev['tris'][keep].astype(np.uint32)))
        return len(occluders) - 1

    def poses_of(o, frs, ref, posed):
        """pose_setup: per frame the placement relative to the current frame and the posed occluders' indices; None
        when the mesh deforms between poses (the occluders added for it dropped)."""
        scene = bpy.context.scene
        f0, s0 = scene.frame_current, scene.frame_subframe
        inv_ref = np.linalg.inv(np.array(o.matrix_world, dtype=np.float64))
        n0 = len(occluders)
        out = []
        try:
            for f in frs:
                fi = int(math.floor(f))
                scene.frame_set(fi, subframe=float(f - fi))
                d = bpy.context.evaluated_depsgraph_get()
                co = core.evaluated_triangles(o, d)['co']
                if co.shape != ref.shape or not np.allclose(co, ref, rtol=0.0, atol=1e-6):
                    out = None
                    break
                M = to_bake @ np.array(o.matrix_world, dtype=np.float64) @ inv_ref @ from_bake
                out.append((M, [add(oc, skip, d) for oc, skip in posed]))
        finally:
            scene.frame_set(f0, subframe=s0)
        if out is None:
            del occluders[n0:]
        return out

    views, notes = [], []
    combine = 'AVERAGE'
    pose_note = item.get('pose_note') or ''
    if item.get('copies'):  # decision 47: each copy in its own placement, surroundings and poses
        frames = None
        combine = item.get('combine') or 'AVERAGE'
        inv_first = np.linalg.inv(np.array(obj.matrix_world, dtype=np.float64))
        static = {}
        for ci, c in enumerate(item['copies']):
            o = bpy.data.objects.get(c['object'])
            if o is None or o.type != 'MESH':
                notes.append(f"{c['object']}: not in the baked file, left out")
                continue
            X = to_bake @ np.array(o.matrix_world, dtype=np.float64) @ inv_first @ from_bake
            vis, posed = [], []
            for occ in c['occluders']:
                oc = bpy.data.objects.get(occ['name'])
                if oc is None or oc.type != 'MESH':
                    continue
                if c.get('poses') and occ.get('posed'):
                    posed.append((oc, set(occ['skip_slots'])))
                    continue
                if oc.name not in static:
                    static[oc.name] = add(oc, set(occ['skip_slots']))
                vis.append(static[oc.name])
            got = None
            if c.get('poses'):
                got = poses_of(o, c['poses'], core.evaluated_triangles(o, dg)['co'], posed)
                if got is None:
                    notes.append(f"{o.name}: its mesh deforms between poses: baked in the current frame")
            if got is None:
                views.append(dict(transform=X, copy=ci, occluders=vis + [add(oc, skip) for oc, skip in posed],
                                  cposes=1))
            else:
                for M, idx in got:
                    views.append(dict(transform=M @ X, copy=ci, occluders=vis + idx, cposes=len(got)))
        order = {c: k for k, c in enumerate(dict.fromkeys(v['copy'] for v in views))}
        for v in views:
            v['copy'] = order[v['copy']]
            share = v['cposes'] * (len(order) if combine in ('AVERAGE', 'ONE') else 1)  # decision 49
            v['samples'] = core.view_samples(samples, share, SPLIT)
        pose_note = '; '.join(notes)
        lines.append(f"    {len(item['copies'])} copies ({combine.lower()}), {len(views)} views")
    else:
        static, posed = [], []
        for occ in item['occluders']:
            o = bpy.data.objects.get(occ['name'])
            if o is None or o.type != 'MESH' or o == obj:
                continue
            if frames and occ.get('posed'):
                posed.append((o, set(occ['skip_slots'])))  # decision 35
                continue
            static.append(add(o, set(occ['skip_slots'])))
        got = poses_of(obj, frames, ref_co, posed) if frames else None
        if frames and got is None:
            pose_note = 'its mesh deforms between poses (shape keys or an armature): baked in the current frame only'
            frames = None
            static += [add(o, skip) for o, skip in posed]
        if got:
            vs = core.view_samples(samples, len(got), SPLIT)
            views = [dict(transform=M, copy=0, samples=vs, occluders=static + idx) for M, idx in got]
            lines.append(f"    {len(frames)} poses at frames {', '.join(f'{f:g}' for f in frames)}"
                         + (f'; {len(posed)} occluder(s) posed with it' if posed else ''))
        else:
            views = [dict(transform=np.eye(4), copy=0, samples=int(samples), occluders=static)]
    return dict(occluders=occluders, views=views, combine=combine, frames=frames, pose_note=pose_note, log=lines)


def native_failed(what, exc):
    """Decision 22: FSS OptiX failed; it is closed, and the rest of the job bakes with Cycles (said in the log)."""
    bk = NATIVE['baker']
    NATIVE.update(baker=None, why=f'{what}: {type(exc).__name__}: {exc}', failed=True)
    state.update(baker='Cycles', baker_why=NATIVE['why'])
    log(f"  {native.NAME} failed ({NATIVE['why']}): Cycles from here on")
    if bk is not None:
        try:
            bk.close()
        except Exception:  # noqa: BLE001
            traceback.print_exc()


def bake_item(item, coll):
    """Bakes one master; a generator that yields after each tile (the caller checks Cancel between tiles and, with a
    window, lets it redraw), and returns the result. Closing it between tiles leaves the old master as it was.

    Paged (decision 33): the bands are baked from the top (the PNG is written from the top), each band's tiles from the
    left; once a band is baked, the band above it has its halo and is composed and written; nothing is held for the
    whole master. Each tile keeps the seed of its place in core.tile_grid, so the result is Session 20's."""
    t0 = time.time()
    curv = dn = None
    obj = bpy.data.objects.get(item['object'])
    if obj is None or obj.type != 'MESH':
        return dict(status='skipped', reason='object not in the baked file')
    bk = NATIVE['baker']  # FSS OptiX, or None: Cycles
    samples = OPTIX_SAMPLES if bk is not None else int(SET['samples'])
    nat = None
    dist = float(item.get('ao_distance', SET['ao_distance']))  # decision 51: Auto Distance gives small objects less
    BAKE['scene'].world.light_settings.distance = dist
    nf = int(item.get('falloff') or 0)  # decision 53: each view at dist x 1/n, 2/n ... 1, averaged: linear falloff
    steps = [dist * (k + 1) / nf for k in range(nf)] if nf > 1 else None
    dg = bpy.context.evaluated_depsgraph_get()
    uv_name = item['uv']
    ev = core.evaluated_triangles(obj, dg, [uv_name])
    if uv_name not in ev['uv']:
        return dict(status='skipped', reason=f'no UV map {uv_name} in the baked file')
    mh = core.mesh_hash(ev)
    sizes = item['tex_size']  # per material index of a texture set (decision 30: no other face is baked)
    skip = set(item['skip_slots'])
    sel = np.array([(m not in skip) and (str(int(m)) in sizes) for m in ev['mat'].tolist()], dtype=bool)
    tri_src = np.nonzero(sel)[0]
    if not len(tri_src):
        return dict(status='skipped', reason='no face of a texture set')
    pos_w, _ = core.to_world(ev)
    used = np.unique(ev['tris'][tri_src])
    lo, hi = pos_w[used].min(axis=0), pos_w[used].max(axis=0)
    shift = (lo + hi) / 2
    pos, cn = core.to_world(ev, shift)
    frames = item.get('poses') or None  # decision 34: a mover's pose frames, None for the current frame
    pose_note = item.get('pose_note') or ''
    ref_co = ev['co'] if frames else None
    tris = ev['tris'][tri_src]
    cnm = cn[tri_src]
    size = np.array([float(sizes[str(int(m))]) for m in ev['mat'][tri_src]])
    uvpx = ev['uv'][uv_name][tri_src] * size[:, None, None]
    D = core.master_density(pos, tris, uvpx)
    del ev, pos_w, cn
    if D <= 0:
        return dict(status='skipped', reason='no face with UV area')
    tb = time.time()
    m = core.build_master(pos, tris, cnm, D, gutter=core.GUTTER, order=core.ORDER, mirror_open=core.MIRROR_OPEN,
                          fold_split=core.FOLD_SPLIT)
    m['corner_pairs'] = core.corner_pairs(m, pos, tris)  # decision 57
    t_build = time.time() - tb
    W, H = m['W'], m['H']
    # the tile size, which is also the band's height (decisions 32, 33): forced by a test, else the largest that fits
    ws0, _peak0 = core.process_memory()
    forced = int(JOB.get('tile_px') or 0)
    if forced:
        tile, est, fits = forced, None, True
    else:
        # decision 50: the bakes each tile gets (a shared mesh's copies times their poses, or the poses)
        n_views = (sum(len(c.get('poses') or [0]) for c in item['copies']) if item.get('copies')
                   else len(frames or [0]))
        tile, est, fits = core.choose_tile(W, H, BUDGET, ws0 or 0, views=n_views)
    if bk is not None:  # the baker's largest tile
        while tile > core.TILE_MIN and tile * tile > int(bk.ready['max_tile_pixels'] or tile * tile):
            tile //= 2
    tiles = core.tile_grid(W, H, tile)
    n = len(tiles)
    nb = -(-H // tile)  # bands
    gb = 2 ** 30
    if dist != float(SET['ao_distance']):
        log(f"  {item['name']}: AO distance {dist * 1000:g} mm (auto, its longest box axis)")
    if steps:
        log(f"  {item['name']}: falloff in {nf} steps, " + ', '.join(f'{d * 1000:.3g}' for d in steps) + ' mm')
    log(f"  {item['name']}: master {W} x {H} px ({W * H / 1e6:.1f} Mpx), tile {tile} px, {n} tile(s) in {nb} band(s); "
        f"budget {BUDGET / gb:.1f} GB" + (f", estimate {est / gb:.2f} GB" if est else ' (tile forced)')
        + ('' if fits else ', the smallest tile exceeds the budget'))
    state.update(tile=0, n_tiles=n, size=[int(W), int(H)], tile_px=int(tile))
    write_status()
    temps = []
    counts = dict(core_px=0, skirt_px=0)
    times = dict(core=0.0, skirt=0.0, tiles=0.0, trace=0.0, scene=0.0)
    core_tris = m['core_tris']
    cuv = m['muv'][core_tris]
    ns = len(m['skirt_pos'])
    files = core.MasterWriter(FOLDER, item['key'], W, H, threads=int(SET['threads']))
    finished = False
    done = [0]
    # decision 34: per pose the target's placement and the posed occluders; decision 47: a shared mesh's views
    poses = dict(mats=None, posed=[], views=None, occ_all=[], combine=None)

    def bake_both(pcs, img, px, seeds, mat=None, samples=None):
        """A tile's core and skirt, one Cycles bake each (they may overlap in the tile). pcs: (core, skirt), each
        (positions, normals, UV in the tile) or None. Returns (A, B): per tile pixel the value or -1, None for a
        missing piece. Decision 53: with falloff, both at each step's distance (the samples split over the steps with
        Split Samples), averaged."""
        if not steps:
            return bake_pieces(pcs, img, px, seeds, mat, samples)
        sk = core.view_samples(samples or SET['samples'], len(steps), SPLIT)
        acc = [None, None]
        for k, d in enumerate(steps):
            BAKE['scene'].world.light_settings.distance = d
            got = bake_pieces(pcs, img, px, [sd + 7919 * (k + 1) for sd in seeds], mat, sk)
            for j, v in enumerate(got):
                if v is not None:
                    acc[j] = v.astype(np.float64) if acc[j] is None else np.where(v >= 0, acc[j] + v, acc[j])
        BAKE['scene'].world.light_settings.distance = dist
        return tuple(None if a is None else np.where(a >= 0, a / len(steps), -1.0) for a in acc)

    def bake_pieces(pcs, img, px, seeds, mat=None, samples=None):
        pc, ps = pcs
        A = B = None
        if pc is not None:
            A, dt = _bake_piece(coll, 'FSS_AO_CORE', *pc, img, px, seeds[0], target, mat, samples)
            times['core'] += dt
            if ps is not None:
                A = A.copy()  # the skirt's bake reuses px
        if ps is not None:
            B, dt = _bake_piece(coll, 'FSS_AO_SKIRT', *ps, img, px, seeds[1], target, mat, samples)
            times['skirt'] += dt
        return A, B

    def set_pose(p):
        target.matrix_world = poses['mats'][p]
        for q, objs in enumerate(poses['posed']):
            for o in objs:
                o.hide_render = q != p

    def bake_tile_poses(i, rect, win, baked, pcs, img, px):
        """Decision 34: the tile in every pose, summed per pixel in the tile's own buffers and averaged; each pose with
        its own seed. Yields between poses (Cancel)."""
        x0, y0, w, h = rect
        npose = len(poses['mats'])
        spv = core.view_samples(SET['samples'], npose, SPLIT)  # decision 49
        csum, ccnt = np.zeros((h, w), np.float64), np.zeros((h, w), np.int32)
        ssum, scnt = np.zeros((h, w), np.float64), np.zeros((h, w), np.int32)
        for p in range(npose):
            state['pose'] = p + 1
            write_status()
            set_pose(p)
            A, B = bake_both(pcs, img, px, [core.tile_seed(core.pose_seed(sd + SEED_OFFSET, p), i, n)
                                            for sd in core.SEEDS[:2]], poses['mats'][p], spv)
            if A is not None:
                ok = A >= 0
                csum[ok] += A[ok]
                ccnt[ok] += 1
            if B is not None:
                ok = B >= 0
                ssum[ok] += B[ok]
                scnt[ok] += 1
            del A, B
            if p < npose - 1:
                yield done[0]
        cm = ccnt > 0
        win[cm] = core.quantize16(csum[cm] / ccnt[cm])
        counts['core_px'] += int(cm.sum())
        sm = (~cm) & (scnt > 0) & (core.rect_window(m['rects'], x0, y0, w, h) >= 0)
        win[sm] = core.quantize16(ssum[sm] / scnt[sm])
        counts['skirt_px'] += int(sm.sum())
        baked |= cm | sm

    def set_view(v):
        view = poses['views'][v]
        target.matrix_world = view['mat']
        for o in poses['occ_all']:
            o.hide_render = o.name not in view['vis']

    def bake_tile_views(i, rect, win, baked, pcs, img, px):
        """Decision 47: a shared mesh's tile in every view (each copy in its own placement and surroundings, in each
        of its poses); a copy's poses averaged, then the copies combined per pixel (average, lightest or darkest).
        Each view with its own seed. Yields between views (Cancel)."""
        x0, y0, w, h = rect
        views, combine = poses['views'], poses['combine']
        nv = len(views)

        def fold(tot, cnt, s, c):
            ok = c > 0
            v = np.where(ok, s / np.maximum(c, 1), 0.0)
            if combine == 'LIGHTEST':
                tot[ok] = np.maximum(tot[ok], v[ok])
            elif combine == 'DARKEST':
                tot[ok] = np.minimum(tot[ok], v[ok])
            else:
                tot[ok] += v[ok]
            cnt[ok] += 1
        init = -1.0 if combine == 'LIGHTEST' else (2.0 if combine == 'DARKEST' else 0.0)
        ctot, ccn = np.full((h, w), init), np.zeros((h, w), np.int32)
        stot, scn = np.full((h, w), init), np.zeros((h, w), np.int32)
        csum = ccnt = ssum = scnt = None
        for v in range(nv):
            if csum is None:  # a copy's first view
                csum, ccnt = np.zeros((h, w)), np.zeros((h, w), np.int32)
                ssum, scnt = np.zeros((h, w)), np.zeros((h, w), np.int32)
            state.update(pose=v + 1, copy=views[v]['n'], n_copies=poses['n_copies'], copy_name=views[v]['name'],
                         copy_pose=views[v]['cpose'], copy_poses=views[v]['cposes'])
            write_status()
            set_view(v)
            A, B = bake_both(pcs, img, px, [core.tile_seed(core.pose_seed(sd + SEED_OFFSET, v), i, n)
                                            for sd in core.SEEDS[:2]], views[v]['mat'], views[v]['samples'])
            if A is not None:
                ok = A >= 0
                csum[ok] += A[ok]
                ccnt[ok] += 1
            if B is not None:
                ok = B >= 0
                ssum[ok] += B[ok]
                scnt[ok] += 1
            del A, B
            if v == nv - 1 or views[v + 1]['copy'] != views[v]['copy']:  # the copy's last view
                fold(ctot, ccn, csum, ccnt)
                fold(stot, scn, ssum, scnt)
                csum = None
            if v < nv - 1:
                yield done[0]
        cm = ccn > 0
        val = ctot if combine in ('LIGHTEST', 'DARKEST') else ctot / np.maximum(ccn, 1)
        win[cm] = core.quantize16(np.clip(val[cm], 0.0, 1.0))
        counts['core_px'] += int(cm.sum())
        sm = (~cm) & (scn > 0) & (core.rect_window(m['rects'], x0, y0, w, h) >= 0)
        sval = stot if combine in ('LIGHTEST', 'DARKEST') else stot / np.maximum(scn, 1)
        win[sm] = core.quantize16(np.clip(sval[sm], 0.0, 1.0))
        counts['skirt_px'] += int(sm.sum())
        baked |= cm | sm

    def native_tile(rect):
        """The tile from FSS OptiX: (A, B, TileDone), the views already combined; None when cancelled in the tile (the
        job's cancel file, or the baker window's Cancel). NativeFailed when the baker fails."""
        asked = [False]
        last = [time.time()]

        def on_progress(p):
            if not asked[0] and os.path.exists(CANCEL):
                asked[0] = True
                bk.cancel_tile()
            if (p.get('views') or 1) > 1:
                state['pose'] = min(int(p['view']) + 1, int(p['views']))
            if time.time() - last[0] >= STATUS_EVERY_S:
                last[0] = time.time()
                write_status()
        try:
            return bk.bake_tile(rect, tile=done[0], tiles=n, on_progress=on_progress)
        except Exception as exc:  # noqa: BLE001
            raise NativeFailed(f'tile {done[0]} of {n}') from exc

    def bake_tile(i, rect, win, baked):
        """Tile i of tile_grid (its place gives its seed) into the band's views of it; yields once it is baked (and
        between its poses)."""
        x0, y0, w, h = rect
        done[0] += 1
        state['tile'] = done[0]
        write_status()
        tt = time.time()
        off = np.array([x0, y0], dtype=np.float64)
        wh = np.array([w, h], dtype=np.float64)
        csel = core.tris_in_window(cuv, x0, y0, w, h)
        ssel = core.tris_in_window(m['skirt_uv'], x0, y0, w, h) if ns else np.zeros(0, dtype=np.int64)
        if bk is not None and (len(csel) or len(ssel)):
            got = native_tile(rect)
            if got is None:  # cancelled in the tile: the job stops as after a tile (step closes this master)
                if not os.path.exists(CANCEL):
                    with open(CANCEL, 'w', encoding='utf-8') as f:
                        f.write('cancel\n')
                while True:
                    yield done[0]
            A, B, td = got
            cm = A >= 0
            win[cm] = core.quantize16(A[cm])
            counts['core_px'] += int(cm.sum())
            sm = (~cm) & (B >= 0) & (core.rect_window(m['rects'], x0, y0, w, h) >= 0)
            win[sm] = core.quantize16(B[sm])
            counts['skirt_px'] += int(sm.sum())
            baked |= cm | sm
            times['core'] += td['seconds']
            times['trace'] += td['trace_s']
            del A, B, cm, sm
        elif len(csel) or len(ssel):
            ct = core_tris[csel]
            pc = (pos[tris[ct]], cnm[ct], (cuv[csel] - off) / wh) if len(csel) else None
            ps = ((m['skirt_pos'][ssel], m['skirt_n'][ssel], (m['skirt_uv'][ssel] - off) / wh) if len(ssel)
                  else None)
            pcs = (pc, ps)
            img = new_float_image('FSS_AO_TILE', w, h)
            px = np.empty(w * h * 4, dtype=np.float32)
            try:
                if poses['views']:
                    yield from bake_tile_views(i, rect, win, baked, pcs, img, px)
                elif poses['mats']:
                    yield from bake_tile_poses(i, rect, win, baked, pcs, img, px)
                else:
                    A, B = bake_both(pcs, img, px, [core.tile_seed(sd + SEED_OFFSET, i, n) for sd in core.SEEDS[:2]])
                    cm = np.zeros((h, w), dtype=bool)
                    if A is not None:
                        cm = A >= 0
                        win[cm] = core.quantize16(A[cm])
                        counts['core_px'] += int(cm.sum())
                    sm = np.zeros((h, w), dtype=bool)
                    if B is not None:
                        sm = (~cm) & (B >= 0) & (core.rect_window(m['rects'], x0, y0, w, h) >= 0)
                        win[sm] = core.quantize16(B[sm])
                        counts['skirt_px'] += int(sm.sum())
                    baked |= cm | sm
                    del A, B, cm, sm
            finally:
                bpy.data.images.remove(img)
                del px
        if n > 1:
            log(f"    tile {done[0]}/{n} at ({x0}, {y0}) {w} x {h}: {len(csel)} core and {len(ssel)} skirt "
                f"triangles, {time.time() - tt:.2f} s")
        times['tiles'] += time.time() - tt
        yield done[0]

    try:
        if bk is not None:  # FSS OptiX: the master's scene once, the views combined in the baker
            nat = native_scene(item, obj, dg, shift, frames, ref_co, samples)
            frames, pose_note = nat['frames'], nat['pose_note']
            for line in nat['log']:
                log(line)
            try:
                bk.job_info(_run['i'] + 1, len(ITEMS), item['name'])
                ready = bk.load_master(pos, tris, cnm, m, dist, samples, views=nat['views'],
                                       occluders=nat['occluders'], falloff=nf > 1, combine=nat['combine'],
                                       seed=core.SEEDS[0] + SEED_OFFSET)
            except Exception as exc:  # noqa: BLE001
                raise NativeFailed('its scene') from exc
            times['scene'] = ready['seconds']
            log(f"    {native.NAME}: {ready['triangles']} triangles, {ready['instances']} instances, {ready['views']} "
                f"view(s), {samples} samples, {ready['gpu_bytes'] / 2 ** 20:.0f} MB on the GPU, in "
                f"{ready['seconds']:.2f} s")
            state.update(pose=0, n_poses=len(nat['views']))
        else:
            # the target (selected) and the occluders, moved by -shift, in the bake's own scene (decision 52)
            distinct = np.array([len(set(r)) == 3 for r in tris.tolist()])
            tme = build_mesh('FSS_AO_TARGET', pos, tris[distinct], cnm[distinct])
            tme.materials.clear()
            target = temp_object(coll, 'FSS_AO_TARGET', tme)
            temps.append(target)
            posed_occ = []
            if item.get('copies'):
                frames = None  # decision 47: each copy has its own poses, as views
                n_views, notes = setup_copies(item, obj, dg, shift, coll, temps, poses)
                pose_note = '; '.join(notes)
                log(f"    {len(item['copies'])} copies ({item['combine'].lower()}), {n_views} views")
            for occ in ([] if item.get('copies') else item['occluders']):
                o = bpy.data.objects.get(occ['name'])
                if o is None or o.type != 'MESH' or o == obj:
                    continue
                if frames and occ.get('posed'):
                    posed_occ.append((o, set(occ['skip_slots'])))  # decision 35: posed with the target, built per pose
                    continue
                temps.append(temp_object(coll, 'FSS_AO_OCC', occluder_mesh(o, dg, set(occ['skip_slots']), shift)))
            if frames:
                got = pose_setup(obj, frames, ref_co, shift, posed_occ)
                if got is None:
                    pose_note = ('its mesh deforms between poses (shape keys or an armature): baked in the current '
                                 'frame only')
                    frames = None
                    for o, skip in posed_occ:  # at the current frame, as at one pose
                        temps.append(temp_object(coll, 'FSS_AO_OCC', occluder_mesh(o, dg, skip, shift)))
                else:
                    poses['mats'], meshes = got
                    for p, mes in enumerate(meshes):
                        objs = [temp_object(coll, 'FSS_AO_OCC_POSE', me) for me in mes]
                        temps.extend(objs)
                        poses['posed'].append(objs)
                    log(f"    {len(frames)} poses at frames {', '.join(f'{f:g}' for f in frames)}"
                        + (f'; {len(posed_occ)} occluder(s) posed with it' if posed_occ else ''))
            state.update(pose=0, n_poses=len(poses['views']) if poses['views'] else (len(frames) if frames else 1))
        # paged (decision 33): bands from the top, each composed and written once the band below it is baked
        tp = time.time()
        times['tiles'] = 0.0
        yield from core.bake_paged(m, tile, bake_tile, files.write_rows, counts, threads=int(SET['threads']))
        t_compose = time.time() - tp - times['tiles']
        log(f"  {item['name']}: composed by {core.compose_by(int(SET['threads']))} in {t_compose:.2f} s, the map "
            f"written by {getattr(files.map, 'by', 'Python')}")
        t_core, t_skirt = times['core'], times['skirt']
        counts['image_px'] = int(W * H)
        meta = dict(schema=core.SCHEMA, key=item['key'], kind=item['kind'], name=item['name'], object=obj.name,
                    mesh_hash=mh, ao_distance=dist, samples=int(samples), **core.method_settings())
        # decision 55: an AO bake without CM keeps the old curvature only when the layout is the same
        keep_curv = None if item.get('cm', SET.get('curvature')) else _same_layout_curvature(item['key'], m, tri_src, mh)
        ts = time.time()
        files.finish(m, tri_src, meta)
        finished = True
        _remove_files([os.path.join(FOLDER, item['key'] + core.THUMB_EXT)])  # decision 31: no thumbnail any more
        t_save = time.time() - ts
        if item.get('cm', SET.get('curvature')):  # decision 54: the curvature master in this layout, from geometry
            curv = write_curvature(item, m, pos, tris, cnm, float(SET['curv_width']))
            curv['width'] = float(SET['curv_width'])
            log(f"  {item['name']}: curvature ({curv['width'] * 1000:g} mm, {curv['edges']} sharp edges) in "
                f"{curv['seconds']:.1f} s")
        elif keep_curv:
            curv = dict(keep_curv)
        else:  # decision 55: a curvature of another layout is removed (the CM grade is then missing)
            for p in core.image_paths(FOLDER, item['key'], 'curv'):
                try:
                    os.remove(p)
                except OSError:
                    pass
        _remove_files(core.image_paths(FOLDER, item['key'], 'ao.raw'))  # decision 56: the new bake is the raw one
        if SET.get('denoise'):
            dn = denoise(item, pos, tris, cnm)
    finally:
        _remove(temps)
        if not finished:
            files.abort()
        if bk is not None and NATIVE['baker'] is bk:
            try:
                bk.release_master()
            except Exception:  # noqa: BLE001
                pass
    _ws, peak = core.process_memory()
    if pose_note:
        log(f"  {item['name']}: {pose_note}")
    if PROFILE:
        log('  profile: ' + ', '.join(f'{k} {v:.2f}' if isinstance(v, float) else f'{k} {v}'
                                      for k, v in PROFILE.items()))
        PROFILE.clear()
    if nat is not None:
        n_poses = len(nat['views']) if item.get('copies') else (len(frames) if frames else 1)
        view_samples = sorted({int(v['samples']) for v in nat['views']})
        baker = dict(name=native.NAME, version=bk.version, device=bk.ready['device'], trace_s=round(times['trace'], 3),
                     scene_s=round(times['scene'], 3))
    else:
        n_poses = len(poses['views']) if poses['views'] else (len(frames) if frames else 1)
        view_samples = sorted({v['samples'] for v in poses['views']}) if poses['views'] else (
            [core.view_samples(SET['samples'], len(frames), SPLIT)] if frames else [int(SET['samples'])])
        baker = dict(name='Cycles', version=bpy.app.version_string, device=SET['device'],
                     why=NATIVE['why'] or None)
    entry = dict(key=item['key'], kind=item['kind'], name=item['name'], object=obj.name, mesh=obj.data.name,
                 poses=frames, n_poses=n_poses, pose_note=pose_note,
                 combine=item.get('combine'), copies=len(item['copies']) if item.get('copies') else None,
                 falloff=nf if nf > 1 else None,
                 curvature=None if curv is None else dict(width=curv['width'], edges=curv['edges'],
                                                          seconds=curv['seconds'], baker=curv.get('baker', 'add-on')),
                 denoise=dn,
                 corner_rule=core.CORNER_RULE,
                 sample_split=SPLIT,
                 view_samples=view_samples, baker=baker,
                 occluder_mode=item.get('occluder_mode', 'SCENE'),
                 mesh_hash=mh, mesh_hash_at_job=item.get('mesh_hash'), surround_hash=item['surround_hash'],
                 density=float(D), W=int(W), H=int(H), tris=int(len(tri_src)), islands=int(m['n_islands']),
                 samples=int(samples), ao_distance=dist, method=core.METHOD,
                 uv=uv_name, occluders=[o['name'] for o in item['occluders']], mover=bool(item.get('mover')),
                 frame=item.get('frame'), baked_at=time.strftime('%Y-%m-%d %H:%M:%S'), schema=core.SCHEMA,
                 tiles=dict(size=int(tile), n=int(n), bands=int(nb), forced=bool(forced),
                            budget_gb=round(BUDGET / gb, 2), estimate_gb=round(est / gb, 2) if est else None,
                            in_use_gb=round(ws0 / gb, 3) if ws0 else None,
                            peak_working_set_gb=round(peak / gb, 3) if peak else None),
                 times=dict(build_s=round(t_build, 3), core_s=round(t_core, 3), skirt_s=round(t_skirt, 3),
                            bake_s=round(t_core + t_skirt, 3), compose_s=round(t_compose, 3),
                            save_s=round(t_save, 3), total_s=round(time.time() - t0, 3)),
                 compose=counts, image=files.stats)
    update_index(entry)
    res = dict(status='baked', W=int(W), H=int(H), tile=int(tile), n_tiles=int(n), bake_s=round(t_core + t_skirt, 3),
               total_s=round(time.time() - t0, 3), peak_working_set_gb=entry['tiles']['peak_working_set_gb'],
               mesh_changed_since_job=bool(item.get('mesh_hash') and item['mesh_hash'] != mh),
               n_poses=entry['n_poses'], baker=baker['name'])
    if pose_note:
        res['note'] = pose_note
    return res


def _index_entry(key):
    try:
        with open(os.path.join(FOLDER, 'index.json'), encoding='utf-8') as f:
            return json.load(f).get('masters', {}).get(key)
    except (OSError, ValueError):
        return None


def _same_layout_curvature(key, m, tri_src, mh):
    """The old entry's curvature when the master's old layout (its .ao.npz) equals the new one, else None."""
    old = _index_entry(key)
    c = (old or {}).get('curvature')
    if not c or old.get('mesh_hash') != mh or not os.path.isfile(core.master_paths(FOLDER, key, 'curv')[0]):
        return None
    try:
        with np.load(core.master_paths(FOLDER, key)[2]) as z:
            same = (int(z['W']) == int(m['W']) and int(z['H']) == int(m['H'])
                    and np.array_equal(z['tri_src'], np.asarray(tri_src, dtype=np.int64))
                    and np.array_equal(z['muv'], m['muv']))
    except (OSError, ValueError, KeyError):
        return None
    return c if same else None


def _remove_files(paths):
    for p in paths:
        try:
            os.remove(p)
        except OSError:
            pass


def write_curvature(item, m, pos, tris, cn, width):
    """Decision 54: the curvature master, by FSS OptiX when it runs (byte for byte the same file), else here. A failure
    of the baker writes it here and leaves Cycles for the rest of the job (decision 22)."""
    bk = NATIVE['baker']
    if bk is not None:
        try:
            curv = bk.write_curvature(FOLDER, item['key'], m, pos, tris, cn, width, threads=int(SET['threads']))
            curv['baker'] = native.NAME
            return curv
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            native_failed(f"the curvature of {item['name']}", exc)
    return core.write_curvature(FOLDER, item['key'], m, pos, tris, cn, width, threads=int(SET['threads']))


def denoise(item, pos, tris, cn):
    """Decision 56: the master filtered with the job's options; the master as it is becomes the raw one when there is
    none (just baked, or never denoised). Returns the index entry's denoise (settings and stats). On an error the
    master is left as it was."""
    key = item['key']
    img = core.master_paths(FOLDER, key)[0]
    rjx, rpn = core.image_paths(FOLDER, key, 'ao.raw')
    raw = rjx if img.endswith('.jxl') else rpn
    moved = False
    if not os.path.isfile(raw):
        os.replace(img, raw)
        moved = True

    def on_band(i, n):
        state.update(phase='Denoising', tile=i, n_tiles=n)
        write_status()

    try:
        st = None
        if SET['denoise'].get('method') == 'OIDN' and NATIVE['baker'] is not None:  # the baker's OIDN (Session 8)
            try:
                st = NATIVE['baker'].denoise_master(FOLDER, key, cn, SET['denoise'], device='GPU', on_band=on_band)
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                native_failed(f"the denoise of {item['name']}", exc)
        if st is None and SET['denoise'].get('method') == 'OIDN':
            st = core.denoise_master_oidn(FOLDER, key, pos, tris, cn, SET['denoise'], device=SET.get('device', 'GPU'),
                                          on_band=on_band)
        elif st is None:
            st = core.denoise_master(FOLDER, key, pos, tris, cn, SET['denoise'], threads=int(SET['threads']),
                                     on_band=on_band)
    except BaseException:
        if moved and not os.path.isfile(img):
            os.replace(raw, img)
        raise
    finally:
        state.update(phase='')
    if st.get('method') == 'OIDN':
        by = f"{st['baker']}'s OIDN {st['oidn']}" if st.get('baker') else 'OIDN'
        log(f"  {item['name']}: denoised by {by} ({st['device']}) in {st['seconds']:.1f} s ({st['groups']} island "
            f"groups, {st['windows']} windows, mean change {st['mean_change']:.4f})")
    else:
        log(f"  {item['name']}: denoised in {st['seconds']:.1f} s ({st['levels']} levels, radius {st['radius_px']:g} "
            f"px, noise {st['noise']:.4f} at 50 %, curvature {st['curvature']}, mean change {st['mean_change']:.4f})")
    return dict(settings=SET['denoise'], **st)


def undenoise(item):
    """Decision 56: Denoise turned off: the raw bake becomes the master again."""
    key = item['key']
    for raw in core.image_paths(FOLDER, key, 'ao.raw'):
        if os.path.isfile(raw):
            dst = os.path.join(FOLDER, key) + ('.ao.jxl' if raw.endswith('.jxl') else '.ao.png')
            _remove_files(core.image_paths(FOLDER, key))
            os.replace(raw, dst)
            log(f"  {item['name']}: the raw bake restored (Denoise off)")
            return True
    return False


def curvature_item(item, coll=None):
    """Decisions 55, 56: without rays, the curvature master (cm) and the denoise (dn) of a master whose AO master is
    up to date in mesh: in its layout (its .ao.npz: the master UVs and the triangles), from the baked file's geometry.
    A generator like bake_item (no steps: it returns its result)."""
    yield from ()
    t0 = time.time()
    obj = bpy.data.objects.get(item['object'])
    if obj is None or obj.type != 'MESH':
        return dict(status='skipped', reason='object not in the baked file')
    key = item['key']
    entry = _index_entry(key)
    _img, mp, npz = core.master_paths(FOLDER, key)
    if entry is None or not (os.path.isfile(npz) and os.path.isfile(mp)):
        return dict(status='skipped', reason='no AO master: bake its AO first')
    uv_name = item['uv']
    ev = core.evaluated_triangles(obj, bpy.context.evaluated_depsgraph_get(), [uv_name])
    mh = core.mesh_hash(ev)
    if mh != entry.get('mesh_hash'):
        return dict(status='skipped', reason='mesh changed since its AO bake: bake its AO')
    with np.load(npz) as z:
        muv, tri_src = z['muv'], z['tri_src']
    pos_w, _ = core.to_world(ev)
    used = np.unique(ev['tris'][tri_src])
    shift = (pos_w[used].min(axis=0) + pos_w[used].max(axis=0)) / 2  # as the AO bake moved it
    pos, cn = core.to_world(ev, shift)
    tris, cnm = ev['tris'][tri_src], cn[tri_src]
    done = []
    if item.get('cm', True):
        width = float(SET['curv_width'])
        curv = write_curvature(item, dict(muv=muv), pos, tris, cnm, width)
        log(f"  {item['name']}: curvature only ({width * 1000:g} mm, {curv['edges']} sharp edges) in "
            f"{curv['seconds']:.1f} s")
        entry = _index_entry(key) or entry
        entry['curvature'] = dict(width=width, edges=curv['edges'], seconds=curv['seconds'],
                                  baker=curv.get('baker', 'add-on'))
        update_index(entry)
        done.append('curvature')
    if item.get('dn'):
        if SET.get('denoise'):
            dn = denoise(item, pos, tris, cnm)
        else:
            undenoise(item)
            dn = None
        entry = _index_entry(key) or entry
        entry['denoise'] = dn
        update_index(entry)
        done.append('denoise')
    return dict(status='updated', what=done, total_s=round(time.time() - t0, 3))


_run = dict(i=0, coll=None, gen=None, t=None, tiles_done=0)


def _record(item, res):
    i = _run['i']
    res.update(key=item['key'], name=item['name'], seconds=round(time.time() - _run['t'], 2))
    state['results'].append(res)
    cancelled = res['status'] == 'cancelled'
    if not cancelled:
        state['n_done'] = i + 1
    _run['i'] = i + 1
    _run['gen'] = None
    _ws, peak = core.process_memory()
    state['peak_working_set_gb'] = round(peak / 2 ** 30, 3) if peak else None
    log(f"{i + 1}/{len(ITEMS)} {item['name']}: {res['status']}"
        + (f" by {res.get('baker')}, {res.get('W')}x{res.get('H')} px in {res.get('n_tiles')} tile(s) of "
           f"{res.get('tile')} px, bake {res.get('bake_s')} s" if res['status'] == 'baked' else '')
        + (f", {res['n_poses']} poses" if (res.get('n_poses') or 1) > 1 else '')
        + (f" ({res['reason']})" if res.get('reason') else '') + f", {res['seconds']} s"
        + (f", peak working set {state['peak_working_set_gb']} GB" if peak else ''))
    state.update(tile=0, n_tiles=0, pose=0, n_poses=0, copy=0, n_copies=0, copy_pose=0, copy_poses=0, phase='')
    write_status()
    return not cancelled


def step():
    """One step of the run: the start of an object, one tile, or its end. Returns False when the run is over.
    Cancel is checked before each object and between tiles; a cancelled object keeps its old master."""
    if _run['gen'] is None:
        i = _run['i']
        if i >= len(ITEMS) or os.path.exists(CANCEL):
            return False
        state['current'] = ITEMS[i]['name']
        state.update(tile=0, n_tiles=0, pose=0, n_poses=0, copy=0, n_copies=0, copy_pose=0, copy_poses=0)
        write_status()
        run = bake_item if ITEMS[i].get('ao', True) else curvature_item  # decision 55
        _run.update(t=time.time(), gen=run(ITEMS[i], _run['coll']), tiles_done=0)
    item = ITEMS[_run['i']]
    gen = _run['gen']
    if _run['tiles_done'] and os.path.exists(CANCEL):
        gen.close()
        res = dict(status='cancelled', reason=f"cancelled after tile {state.get('tile')} of {state.get('n_tiles')}"
                   + (f", pose {state.get('pose')} of {state.get('n_poses')}" if (state.get('n_poses') or 0) > 1 else '')
                   + '; its old master kept')
        _record(item, res)
        return False
    try:
        next(gen)
        _run['tiles_done'] += 1
        write_status()
        delay = float(JOB.get('test_tile_delay_s') or 0)
        if delay:
            time.sleep(delay)
        return True
    except StopIteration as stop:
        res = stop.value or dict(status='failed', reason='no result')
    except NativeFailed as exc:  # decision 22: this master again with Cycles, and the rest of the job
        traceback.print_exc()
        native_failed(f"{item['name']}, {exc}", exc.__cause__ or exc)
        _run.update(gen=bake_item(item, _run['coll']), tiles_done=0)
        return True
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        try:
            gen.close()
        except Exception:  # noqa: BLE001
            pass
        res = dict(status='failed', reason=f'{type(exc).__name__}: {exc}')
    _record(item, res)
    delay = float(JOB.get('test_delay_s') or 0)
    if delay:
        time.sleep(delay)
    return _run['i'] < len(ITEMS)


def start_baker():
    """Decision 22: FSS OptiX for the job when the Baker setting asks for it and its GPU works, else Cycles, and why."""
    if BAKER == 'CYCLES':
        state.update(baker='Cycles')
        log('baker Cycles (the Baker setting)')
        return
    have, why = native.available()
    if have:
        try:
            # its window in a Visible run, and in a Foreground run with FSS OptiX, whose Blender is hidden (decision 28)
            window = bool(JOB.get('baker_window')) or not bpy.app.background
            bk = native.Baker(foreground=window, client='ao_bake_runner', tag=str(os.getpid()))
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            why = f'it did not start ({type(exc).__name__}: {exc})'
        else:
            if bk.ok:
                NATIVE['baker'] = bk
                state.update(baker=native.NAME, baker_version=bk.version, baker_device=bk.ready['device'])
                log(f"baker {native.NAME} ({bk.ready['device']}; {bk.version}), {OPTIX_SAMPLES} samples")
                return
            why = bk.why
            bk.close()
    NATIVE['why'] = why
    state.update(baker='Cycles', baker_why=why)
    log(f'baker Cycles: {native.NAME} cannot run here ({why})')


def close_baker():
    bk = NATIVE['baker']
    NATIVE['baker'] = None
    if bk is not None:
        try:
            bk.close()
        except Exception:  # noqa: BLE001
            traceback.print_exc()


def finish():
    close_baker()
    cancelled = os.path.exists(CANCEL) and (state['n_done'] < state['n_total']
                                            or any(r['status'] == 'cancelled' for r in state['results']))
    state['state'] = 'cancelled' if cancelled else 'done'
    state['current'] = ''
    write_status()
    counts = {}
    for r in state['results']:
        counts[r['status']] = counts.get(r['status'], 0) + 1
    log(f"{state['state']}: {state['n_done']} of {state['n_total']} ({counts}), {state['elapsed_s']} s")


def timer_step():
    """One master per timer step, in the window's context (a timer has no window of its own)."""
    try:
        wm = bpy.context.window_manager
        window = wm.windows[0] if wm.windows else None
        if window is not None:
            with bpy.context.temp_override(window=window, screen=window.screen):
                more = step()
        else:
            more = step()
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        more = False
    if more:
        return 0.05
    finish()
    bpy.ops.wm.quit_blender()
    return None


def main():
    total, avail = core.memory_status()
    gb = 2 ** 30
    log(f"AO bake of {len(ITEMS)} masters from {JOB['blend']}{' (its current state)' if JOB.get('source') else ''}: distance {SET['ao_distance']} m, samples "
        f"{SET['samples']}, device {SET['device']}, threads {SET['threads']}; memory budget {BUDGET / gb:.1f} GB"
        + (f" ({BUDGET_SOURCE}; physical {total / gb:.1f} GB, free {avail / gb:.1f} GB)" if total else
           f' ({BUDGET_SOURCE})'))
    state.update(budget_gb=round(BUDGET / gb, 2), budget_source=BUDGET_SOURCE)
    why = core.native_copy().unavailable()  # apply-native-copy decision 6: fss_ao_copy.dll and libjxl are required
    if why:
        reason = f'AO Bake not available: {why}'
        log(reason)
        state.update(state='failed', reason=reason, current='')
        for item in ITEMS:
            state['results'].append(dict(status='failed', reason=reason, key=item['key'], name=item['name'],
                                         seconds=0.0))
        write_status()
        if not bpy.app.background:
            bpy.ops.wm.quit_blender()
        return
    lib = core.jxl()  # decision 37: JPEG XL masters
    state.update(master_format='jxl', jxl_library=lib.version())
    log(f'masters as lossless JPEG XL (libjxl {lib.version()}, effort {lib.EFFORT})')
    _run['coll'] = setup_scene()
    start_baker()
    write_status()
    if bpy.app.background:
        while step():
            pass
        finish()
    else:
        hide_views()
        bpy.app.timers.register(timer_step, first_interval=0.5)


try:
    main()
except Exception:  # noqa: BLE001
    traceback.print_exc()
    close_baker()
    state['state'] = 'failed'
    write_status()
    if not bpy.app.background:
        bpy.ops.wm.quit_blender()
