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

The layout (decision 81): while the mesh is unchanged (the index entry's mesh hash) a bake keeps the master's layout,
built again at its stored density whatever the texture set's UVs or size are now; a new layout (no master, the mesh
changed, or the stored one cannot be built again) removes what was baked into the old one and does not fit.

Material channels (decisions 79 to 83; channel_item): after the AO, or alone, the job item's chosen channels (albedo,
roughness, metal, emissive) baked from the object's material as Cycles shades it: per tile a temporary mesh of the
master's triangles (core and skirt, as the AO's) with every UV map and attribute of the evaluated mesh at its corners
and the master's UV as the active map (the render UV map stays the mesh's own), each material copied with the source
of its Principled BSDF's socket routed to an Emission shader (albedo before the MSFS AO multiply), one EMIT bake per
channel; one 16-bit grey JPEG XL image per component in the master's layout, albedo and emissive sRGB-encoded. A
shared mesh's channels come from the copy the job names; its emissive, unless Copies is One Instance, from every
copy, combined per pixel as the AO's copies (decision 87). A material without such a BSDF bakes black for that
channel, and its texture set is listed as skipped in the entry (Apply keeps its pixels). No occluders, poses or denoise.

Vertex colour sources (decisions 88 to 92; the job's settings['vertex_color'], {group: OVERWRITE or MULTIPLY}): the
AO (red), roughness (green), metal (blue) or albedo (RGB) baked through the same channel path from the mesh's second
colour attribute (settings['vc_attribute'] SECOND), or its active one (ACTIVE), read by name (an Emission shader fed by
a Color Attribute node, the same material on every slot; the values linear for every attribute type): no trace, no
material. Multiply multiplies the master's current image of the channel in the kept layout (decision 81), onto 1.0
where there is none. The AO's: Overwrite removes the raw bake and the product; Multiply of a traced AO keeps the
product of its multiplies as <stem>.ao_vc.jxl, so a later denoise-only run gives the denoised raw bake times it.

Custom values (decisions 99 and 100; settings['custom_value'], {group: OVERWRITE or MULTIPLY}, the item's
custom_values {group: value}): the roughness, metal, albedo or emissive baked through the same path from an Emission
shader of the object's own value or linear colour, Overwrite or Multiply as a vertex colour source.
"""
import importlib.util
import json
import math
import os
import shutil
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
    curve = item.get('falloff_curve') or 'LINEAR'  # decision 105: the steps placed along the curve
    steps = core.falloff_distances(dist, nf, curve) if nf > 1 else None
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
    # decision 81: the master's layout is kept while its mesh is unchanged (its density, whatever the UVs are now)
    m, kept, old_entry = layout_for(item, mh, tri_src, pos, tris, cnm, D, uvpx)
    if kept or m.get('object_uv'):
        D = m['density']
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
        log(f"  {item['name']}: falloff in {nf} steps" + ('' if curve == 'LINEAR' else f", curve {curve.title()}")
            + ', ' + ', '.join(f'{d * 1000:.3g}' for d in steps) + ' mm')
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
                                       occluders=nat['occluders'],
                                       falloff=core.FALLOFF_CODE.get(curve, 1) if nf > 1 else 0, combine=nat['combine'],
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
        if m.get('object_uv'):  # decision 107: Apply averages each texel's block of this master
            meta['object_uv'] = m['object_uv']
        # decision 55: an AO bake without CM keeps the old curvature only when the layout is the same
        keep_curv = None if item.get('cm', SET.get('curvature')) else _same_layout_curvature(item['key'], m, tri_src, mh)
        ts = time.time()
        files.finish(m, tri_src, meta)
        finished = True
        if not kept:  # decision 81: a new layout; the material channels of the old one no longer fit
            _remove_files([p for g in core.CHANNEL_GROUPS for p in core.channel_paths(FOLDER, item['key'], g, True)])
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
        _remove_files(core.image_paths(FOLDER, item['key'], 'ao_vc'))  # decision 89: a trace drops the product
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
                 falloff_curve=curve if nf > 1 and curve != 'LINEAR' else None,
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
    if item.get('combine') == 'ONE' and item.get('copies'):  # decision 77: the copy One Instance was baked from
        entry['instance'] = item['copies'][0]['object']
    if kept and (old_entry or {}).get('channels'):  # decision 81: the material channels in the kept layout stay
        entry['channels'] = old_entry['channels']
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


def kept_layout(key, mh, tri_src):
    """Decision 81: the master's stored layout (core._layout of its .ao.npz) and its index entry when the entry's
    mesh hash is the item's and its .ao.npz (not of schema 1) and .ao.map are there with these triangles; else
    (None, entry)."""
    old = _index_entry(key)
    if old is None or old.get('mesh_hash') != mh:
        return None, old
    _img, mp, npz = core.master_paths(FOLDER, key)
    if not (os.path.isfile(mp) and os.path.isfile(npz)) or core.has_maps_in_npz(npz):
        return None, old
    try:
        with np.load(npz) as z:
            lay = core._layout(z)
    except (OSError, ValueError, KeyError):
        return None, old
    if not np.array_equal(np.asarray(lay['tri_src'], np.int64), np.asarray(tri_src, np.int64)):
        return None, old
    return lay, old


def layout_for(item, mh, tri_src, pos, tris, cnm, D, uvpx=None):
    """Decision 81: (m, kept, old entry). While the mesh is unchanged the master keeps its layout, whatever the
    texture set's UVs or size are now: built again at its stored density (the skirt is not stored) and used when it
    equals the stored one; otherwise (no master, the mesh changed, or it cannot be built again: said in the log) a new
    layout at density D. Decision 107: an Object UV item's layout from uvpx (the texture set's pixels), kept when the
    stored one is the same."""
    lay, old = kept_layout(item['key'], mh, tri_src)
    if item.get('master_layout') == 'OBJECT_UV' and uvpx is not None:  # decision 107: the object's own UVs
        m = core.object_uv_layout(pos, tris, cnm, uvpx, gutter=core.GUTTER)
        if lay is not None and (lay.get('meta') or {}).get('object_uv') == m['object_uv'] and not core.same_layout(m, lay):
            return m, True, old
        log(f"  {item['name']}: Object UV layout, {m['n_islands']} UV islands at {core.OBJECT_UV_SCALE} x "
            f"{core.OBJECT_UV_SCALE} px per texel")
        return m, False, old
    kw = dict(gutter=core.GUTTER, order=core.ORDER, mirror_open=core.MIRROR_OPEN, fold_split=core.FOLD_SPLIT)
    if lay is not None and (lay.get('meta') or {}).get('object_uv'):  # decision 107: back to Auto Unwrap
        lay = None
    if lay is not None:
        m = core.build_master(pos, tris, cnm, float(lay['density']), **kw)
        why = core.same_layout(m, lay)
        if not why:
            if abs(float(lay['density']) - float(D)) > 1e-9 * max(float(D), 1.0):
                log(f"  {item['name']}: its layout kept ({float(lay['density']):.6g} px/m; the UVs now give "
                    f"{float(D):.6g})")
            return m, True, old
        log(f"  {item['name']}: its layout could not be built again ({why}): a new layout")
    return core.build_master(pos, tris, cnm, D, **kw), False, old


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


def multiply_product(item, entry):
    """Rule item 4 of decision 88's hand-off: a master whose AO was multiplied by a vertex colour (ao_source MULTIPLY)
    gets its product (<stem>.ao_vc.jxl) again after a denoise-only run: the master times the product, per pixel.
    Returns True when it did. The images are read whole (not paged)."""
    key = item['key']
    vc = core.image_paths(FOLDER, key, 'ao_vc')[0]
    img = core.master_paths(FOLDER, key)[0]
    if (entry.get('ao_source') or {}).get('mode') != 'MULTIPLY' or not os.path.isfile(vc) or not img.endswith('.jxl'):
        return False
    lib = core.jxl()
    a, b = lib.read_whole(img), lib.read_whole(vc)
    if a.shape != b.shape:
        log(f"  {item['name']}: the vertex colour product is {b.shape[1]} x {b.shape[0]} px, the master "
            f"{a.shape[1]} x {a.shape[0]}: not applied")
        return False
    w_ = core.ChannelWriter(FOLDER, key, 'ao', a.shape[1], a.shape[0], threads=int(SET['threads']))
    try:
        for y in range(0, a.shape[0], 256):
            w_.write_rows(core.quantize16(a[y:y + 256] / 65535.0 * (b[y:y + 256] / 65535.0)), None)
        w_.encode()
        w_.commit()
    except BaseException:
        w_.abort()
        raise
    log(f"  {item['name']}: the vertex colour product ({', '.join(entry['ao_source'].get('attributes') or ())}) "
        f"multiplied again")
    return True


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
        if multiply_product(item, entry):  # decision 89: the AO's vertex colour multiplies kept
            done.append('vertex colour product')
    return dict(status='updated', what=done, total_s=round(time.time() - t0, 3))


# ---------------------------------------------------------------------------------------------------------------------
# Material channels (decisions 79 to 83): the object's material as Cycles shades it, baked into the master's layout
# ---------------------------------------------------------------------------------------------------------------------

CH_SAMPLES = (int(os.environ.get('FSS_AO_BAKE_CHANNEL_SAMPLES') or 0)  # tests: other samples
              or int(SET.get('channel_samples') or 0) or core.CHANNEL_SAMPLES)  # the Channel Samples setting
APPLY_AO_GROUP = '.Apply AO Group'  # the MSFS material multiplies the base colour by the occlusion there
CH_SOCKETS = {'albedo': 'Base Color', 'rough': 'Roughness', 'metal': 'Metallic', 'emis': 'Emission Color'}
CH_BAKE_UV = 'FSS_CHANNEL_BAKE_UV'
CH_SKIP_ATTRS = {'position', 'material_index', 'sharp_face', 'sharp_edge', 'custom_normal'}
CH_TYPES = {'FLOAT': ('value', 1, np.float32), 'INT': ('value', 1, np.int32), 'INT8': ('value', 1, np.int32),
            'BOOLEAN': ('value', 1, bool), 'FLOAT2': ('vector', 2, np.float32),
            'FLOAT_VECTOR': ('vector', 3, np.float32), 'FLOAT_COLOR': ('color', 4, np.float32),
            'BYTE_COLOR': ('color', 4, np.float32)}


def _through_reroutes(sock):
    """The socket feeding `sock` past reroute nodes, or None when unlinked."""
    while sock is not None and sock.is_linked:
        link = sock.links[0]
        if link.from_node.type == 'REROUTE':
            sock = link.from_node.inputs[0]
            continue
        return link.from_socket
    return None


def principled_of(material):
    """Rule item 1: (the Principled BSDF that feeds the Material Output's Surface, its output node) in the material's
    tree, or (None, why)."""
    nt = getattr(material, 'node_tree', None)
    if nt is None:
        return None, 'no node tree'
    outs = [n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL' and n.target in ('ALL', 'CYCLES')]
    out = next((n for n in outs if n.is_active_output), outs[0] if outs else None)
    if out is None:
        return None, 'no Material Output'
    src = _through_reroutes(out.inputs['Surface'])
    if src is None or src.node.type != 'BSDF_PRINCIPLED':
        return None, 'no Principled BSDF on the Material Output'
    return src.node, out


def _is_apply_ao(node):
    tree = getattr(node, 'node_tree', None) if node.type == 'GROUP' else None
    return tree is not None and (tree.name == APPLY_AO_GROUP or tree.name.startswith(APPLY_AO_GROUP + '.'))


def channel_material(material, group, image):
    """Rule items 1 and 2: a temporary copy of the material whose Material Output's Surface is an Emission shader
    (strength 1) fed by what reaches the Principled BSDF's socket of the group (albedo: before the MSFS AO multiply),
    with an Image Texture node of `image` active for the bake; (copy, '') or (None, why) without such a BSDF."""
    p, out = principled_of(material)
    if p is None:
        return None, out
    mat = material.copy()
    mat.name = f'FSS_CH_{group}_{material.name}'
    nt = mat.node_tree
    p, out = principled_of(mat)
    sock = p.inputs[CH_SOCKETS[group]]
    src = _through_reroutes(sock)
    if group == 'albedo' and src is not None and _is_apply_ao(src.node):
        sock = src.node.inputs[0]  # the colour before the group multiplies it by the occlusion
        src = _through_reroutes(sock)
    em = nt.nodes.new('ShaderNodeEmission')
    em.inputs['Strength'].default_value = 1.0
    if src is not None:
        nt.links.new(src, em.inputs['Color'])
    else:
        v = sock.default_value
        em.inputs['Color'].default_value = (tuple(v)[:3] + (1.0,)) if hasattr(v, '__len__') else (v, v, v, 1.0)
    for name in ('Surface', 'Volume'):
        for link in list(out.inputs[name].links):
            nt.links.remove(link)
    nt.links.new(em.outputs[0], out.inputs['Surface'])
    tex = nt.nodes.new('ShaderNodeTexImage')
    tex.image = image
    nt.nodes.active = tex
    return mat, ''


def _black_material(image):
    """Faces of a texture set skipped for a channel (no Principled BSDF) bake black; Apply keeps their pixels."""
    mat = bpy.data.materials.new('FSS_CH_SKIPPED')
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    em = nt.nodes.new('ShaderNodeEmission')
    em.inputs['Color'].default_value = (0.0, 0.0, 0.0, 1.0)
    nt.links.new(em.outputs[0], out.inputs['Surface'])
    tex = nt.nodes.new('ShaderNodeTexImage')
    tex.image = image
    nt.nodes.active = tex
    return mat


def channel_source(obj, dg, tri_src):
    """Rule item 2: per master triangle (tri_src, loop triangles of the evaluated mesh) its corners' object-space
    positions and corner normals, its material index and every UV map, colour and generic attribute of the evaluated
    mesh at its corners (point, corner and face domains), so a bake mesh carries what the material reads. Returns a
    dict, or raises ValueError when the evaluated mesh has another triangulation."""
    me = bpy.data.meshes.new_from_object(obj.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
    try:
        me.calc_loop_triangles()
        nt = len(me.loop_triangles)
        if len(tri_src) and int(np.max(tri_src)) >= nt:
            raise ValueError(f'{obj.name}: {nt} triangles, the master has more')
        loops = np.empty(nt * 3, np.int64)
        me.loop_triangles.foreach_get('loops', loops)
        verts = np.empty(nt * 3, np.int64)
        me.loop_triangles.foreach_get('vertices', verts)
        poly = np.empty(nt, np.int64)
        me.loop_triangles.foreach_get('polygon_index', poly)
        mat = np.empty(nt, np.int64)
        me.loop_triangles.foreach_get('material_index', mat)
        L = np.asarray(tri_src, np.int64)
        loops, verts = loops.reshape(nt, 3)[L], verts.reshape(nt, 3)[L]
        co = np.empty(len(me.vertices) * 3, np.float32)
        me.vertices.foreach_get('co', co)
        cn = np.empty(len(me.loops) * 3, np.float32)
        me.corner_normals.foreach_get('vector', cn)
        uv_names = [layer.name for layer in me.uv_layers]
        render_uv = next((layer.name for layer in me.uv_layers if layer.active_render), None)
        colors = {a.name for a in me.color_attributes}
        try:
            active_color = me.color_attributes.active_color_name
            render_color = me.color_attributes.default_color_name
        except AttributeError:
            active_color = render_color = ''
        attrs = []
        for a in me.attributes:
            info = CH_TYPES.get(a.data_type)
            if (a.name.startswith('.') or a.name in CH_SKIP_ATTRS or info is None
                    or a.domain not in ('POINT', 'CORNER', 'FACE')):
                continue
            prop, C, dt = info
            buf = np.empty(len(a.data) * C, dt)
            a.data.foreach_get(prop, buf)
            buf = buf.reshape(-1, C).astype(np.float32)
            idx = verts if a.domain == 'POINT' else loops if a.domain == 'CORNER' else np.repeat(poly[L][:, None], 3, 1)
            kind = 'uv' if a.name in uv_names else 'color' if a.name in colors else 'attr'
            attrs.append((a.name, kind, {1: 'FLOAT', 2: 'FLOAT2', 3: 'FLOAT_VECTOR', 4: 'FLOAT_COLOR'}[C], buf[idx]))
        bake_uv = CH_BAKE_UV
        while bake_uv in me.attributes:
            bake_uv += '_'
        src = dict(co=co.reshape(-1, 3)[verts].astype(np.float64), cn=cn.reshape(-1, 3)[loops].astype(np.float64),
                   mat=mat[L], attrs=attrs, render_uv=render_uv, active_color=active_color, render_color=render_color,
                   bake_uv=bake_uv, n_uv=len(uv_names))
    finally:
        bpy.data.meshes.remove(me)
    data = obj.data
    src['texspace'] = (tuple(data.texspace_location), tuple(data.texspace_size)) if hasattr(data, 'texspace_size') \
        else None
    return src


def _bary3(p, a, b, c):
    """Barycentric weights (n, 3) of points p (n, 3) in the triangles (a, b, c), each (n, 3)."""
    v0, v1, v2 = b - a, c - a, p - a
    d00, d01, d11 = (v0 * v0).sum(-1), (v0 * v1).sum(-1), (v1 * v1).sum(-1)
    d20, d21 = (v2 * v0).sum(-1), (v2 * v1).sum(-1)
    den = d00 * d11 - d01 * d01
    den = np.where(np.abs(den) > 1e-30, den, 1e-30)
    v = (d11 * d20 - d01 * d21) / den
    w = (d00 * d21 - d01 * d20) / den
    return np.stack([1.0 - v - w, v, w], axis=-1)


def channel_mesh(name, src, idx, B, tile_uv, materials):
    """A bake mesh of master triangles idx (B: per corner the weights (n, 3, 3) of the source triangle's corners, for
    the skirt; None: the triangle itself) with the source's attributes at its corners, the master's UV relative to the
    tile as the active UV map and the mesh's own render UV map still the render one (Image Texture nodes without a UV
    Map node read it)."""
    def at(a):
        a = a[idx]
        return a if B is None else np.einsum('nkj,njc->nkc', B, a)
    n = len(idx)
    co = at(src['co'])
    cn = at(src['cn'])
    cn /= np.maximum(np.linalg.norm(cn, axis=2, keepdims=True), 1e-30)
    me = bpy.data.meshes.new(name)
    me.from_pydata(co.reshape(-1, 3).tolist(), [], np.arange(n * 3).reshape(-1, 3).tolist())
    me.update(calc_edges=True)
    if len(me.polygons) != n:
        raise RuntimeError(f'{name}: from_pydata kept {len(me.polygons)} of {n} faces')
    me.polygons.foreach_set('material_index', np.asarray(src['mat'][idx], np.int32))
    for aname, kind, dtype, vals in src['attrs']:
        v = np.ascontiguousarray(at(vals), np.float32)
        if kind == 'uv':
            layer = me.uv_layers.new(name=aname)
            layer.uv.foreach_set('vector', v.ravel())
        elif kind == 'color':
            ca = me.color_attributes.new(aname, 'FLOAT_COLOR', 'CORNER')
            ca.data.foreach_set('color', v.ravel())
        else:
            ga = me.attributes.new(aname, dtype, 'CORNER')
            ga.data.foreach_set({'FLOAT': 'value', 'FLOAT_COLOR': 'color'}.get(dtype, 'vector'), v.ravel())
    bake = me.uv_layers.new(name=src['bake_uv'])
    if bake is None:
        raise RuntimeError(f"{name}: no UV map can be added beside its {src['n_uv']}")
    bake.uv.foreach_set('vector', np.asarray(tile_uv, np.float32).ravel())
    me.uv_layers.active = bake
    if src['render_uv'] and src['render_uv'] in me.uv_layers:
        me.uv_layers[src['render_uv']].active_render = True
    try:
        if src['active_color']:
            me.color_attributes.active_color_name = src['active_color']
        if src['render_color']:
            me.color_attributes.default_color_name = src['render_color']
    except (AttributeError, TypeError):
        pass
    if src.get('texspace'):
        me.use_auto_texspace = False
        me.texspace_location, me.texspace_size = src['texspace']
    me.shade_smooth()
    me.normals_split_custom_set(cn.reshape(-1, 3).tolist())
    for m_ in materials:
        me.materials.append(m_)
    me.update()
    return me


def bake_emit(obj, img, px, samples):
    """One Cycles EMIT bake of obj into img (pre-filled with -1, margin 0), in the bake's own scene; the RGB (h, w, 3)
    of each pixel, -1 where none was baked."""
    scene = BAKE['scene']
    view_layer = scene.view_layers[0]
    scene.cycles.samples = int(samples)
    scene.cycles.seed = core.SEEDS[0]
    clear_image(img, px)
    for o in view_layer.objects:
        if o is not None:
            o.select_set(False, view_layer=view_layer)
    obj.select_set(True, view_layer=view_layer)
    view_layer.objects.active = obj
    rb = scene.render.bake
    rb.margin = 0
    rb.use_clear = False
    rb.use_selected_to_active = False
    rb.target = 'IMAGE_TEXTURES'
    sel = [obj]
    with bpy.context.temp_override(scene=scene, view_layer=view_layer, active_object=obj, object=obj,
                                   selected_objects=sel, selected_editable_objects=sel):
        bpy.ops.object.bake(type='EMIT', margin=0, margin_type='ADJACENT_FACES', use_clear=False,
                            use_selected_to_active=False, target='IMAGE_TEXTURES')
    w, h = img.size
    img.pixels.foreach_get(px)
    return px.reshape(h, w, 4)[:, :, :3].copy()


VC = dict(SET.get('vertex_color') or {})  # decisions 88 to 90: {group: 'OVERWRITE' or 'MULTIPLY'}
VC_ATTRIBUTE = SET.get('vc_attribute') or 'SECOND'  # decision 91: the second colour attribute, or the active one
CV = dict(SET.get('custom_value') or {})  # decision 99: {group: 'OVERWRITE' or 'MULTIPLY'}, the object's own value
CV_NAMES = {'rough': 'Roughness from Custom', 'metal': 'Metal from Custom', 'albedo': 'Albedo from Custom',
            'emis': 'Emissive from Custom'}  # decision 100: the colours too


# decision 101: a Custom group is written straight into the master; tests set FSS_AO_BAKE_CUSTOM_CYCLES to bake it
# through Cycles as before (value_material), to compare the two
CV_DIRECT = not os.environ.get('FSS_AO_BAKE_CUSTOM_CYCLES')


class _MapBands:
    """Decision 101: the stored map's filled pixels (the pixels Apply reads) of a kept layout, read from the top in the
    order bake_paged_multi bakes its bands; only the rows of the current band are held."""

    def __init__(self, path, W, H):
        mW, mH, self.gen = core.map_rows(path)
        if (mW, mH) != (W, H):
            self.gen.close()
            raise ValueError(f'{path}: map {mW} x {mH}, layout {W} x {H}')
        self.W = W
        self.buf = np.zeros((0, W), bool)  # rows lo..hi-1 (row 0 = bottom), bottom first
        self.lo = self.hi = H

    def window(self, x0, y0, w, h):
        while self.lo > y0:
            blk = next(self.gen)  # file order: the top first
            self.buf = np.concatenate([core.code_filled(blk)[::-1], self.buf])
            self.lo -= blk.shape[0]
        if y0 + h < self.hi:
            self.buf = self.buf[:y0 + h - self.lo]
            self.hi = y0 + h
        return self.buf[y0 - self.lo:y0 + h - self.lo, x0:x0 + w].copy()

    def close(self):
        self.gen.close()


class _MapRows:
    """Decision 101: a kept layout's stored map codes, read in file order (the top first) as many rows at a time as the
    composition writes."""

    def __init__(self, path, W, H):
        mW, mH, self.gen = core.map_rows(path)
        if (mW, mH) != (W, H):
            self.gen.close()
            raise ValueError(f'{path}: map {mW} x {mH}, layout {W} x {H}')
        self.buf = np.zeros((0, W), np.int32)

    def read(self, n):
        while len(self.buf) < n:
            self.buf = np.concatenate([self.buf, next(self.gen)])
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def close(self):
        self.gen.close()


def _cv_json(v):
    """A Custom value for the index and the result: a float, or a colour's list of 3."""
    return [float(c) for c in v] if isinstance(v, (list, tuple)) else float(v)
VC_COMP = {'ao': 0, 'rough': 1, 'metal': 2, 'albedo': None, 'emis': None}  # the colour's component (None: RGB)
VC_NAMES = {'ao': 'AO from Vertex Color Red', 'rough': 'Roughness from Vertex Color Green',
            'metal': 'Metal from Vertex Color Blue', 'albedo': 'Albedo from Vertex Color',
            'emis': 'Emissive from Vertex Color'}  # decision 95: the emissive too
KINDS = dict(core.CHANNEL_KINDS, ao=('ao',))  # the images of a group (the AO: the master's own)
NAMES = dict(core.CHANNEL_NAMES, ao='AO')


def source_color(obj, dg):
    """Decisions 90 and 91: (name, data type, why) of the colour attribute the vertex colour sources read: the second
    of the original mesh's Color Attributes list (SECOND, whatever is active or render) or its active one (ACTIVE),
    found on the evaluated mesh by its name; (None, None, why) without one."""
    ca = obj.data.color_attributes
    if VC_ATTRIBUTE == 'ACTIVE':
        try:
            a = ca.active_color
        except AttributeError:
            a = None
        if a is None:
            return None, None, 'no colour attribute'
    else:
        if len(ca) < 2:
            return None, None, 'no second colour attribute'
        a = ca[1]
    ev = obj.evaluated_get(dg).data
    if getattr(ev, 'color_attributes', None) is None or ev.color_attributes.get(a.name) is None:
        return None, None, f'{a.name} not on the evaluated mesh'
    return a.name, a.data_type, ''


def vc_material(attr, group, image):
    """Decision 88: an Emission shader (strength 1) fed by a Color Attribute node of `attr` (its component for the AO,
    roughness and metal, the colour for the albedo), with an Image Texture node of `image` active for the bake."""
    mat = bpy.data.materials.new(f'FSS_VC_{group}')
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    em = nt.nodes.new('ShaderNodeEmission')
    em.inputs['Strength'].default_value = 1.0
    ca = nt.nodes.new('ShaderNodeVertexColor')
    ca.layer_name = attr
    comp = VC_COMP[group]
    if comp is None:
        nt.links.new(ca.outputs['Color'], em.inputs['Color'])
    else:
        sep = nt.nodes.new('ShaderNodeSeparateColor')
        nt.links.new(ca.outputs['Color'], sep.inputs[0])
        nt.links.new(sep.outputs[comp], em.inputs['Color'])
    nt.links.new(em.outputs[0], out.inputs['Surface'])
    tex = nt.nodes.new('ShaderNodeTexImage')
    tex.image = image
    nt.nodes.active = tex
    return mat


def value_material(value, group, image):
    """Decisions 99 and 100: an Emission shader (strength 1) of one grey value or one linear colour (a list of 3),
    with an Image Texture node of `image` active for the bake."""
    mat = bpy.data.materials.new(f'FSS_CV_{group}')
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    em = nt.nodes.new('ShaderNodeEmission')
    em.inputs['Strength'].default_value = 1.0
    # decision 111: a Custom albedo's alpha (its 4th value) is not part of the colour
    rgb = [float(c) for c in value][:3] if isinstance(value, (list, tuple)) else [float(value)] * 3
    em.inputs['Color'].default_value = (*rgb, 1.0)
    nt.links.new(em.outputs[0], out.inputs['Surface'])
    tex = nt.nodes.new('ShaderNodeTexImage')
    tex.image = image
    nt.nodes.active = tex
    return mat


REC709 = np.array([0.2126, 0.7152, 0.0722], np.float32)  # decision 87: the luminance of linear RGB


def combine_copies(arrs, combine):
    """Decision 87: a shared mesh's emissive over its copies' bakes (each (h, w, 3), linear, -1 where none was baked;
    the copies cover the same pixels): AVERAGE the mean; LIGHTEST and DARKEST the colour of the copy whose luminance
    (Rec. 709) is the highest or lowest at that pixel, its three components together (the first copy on a tie)."""
    st = np.stack(arrs)
    if combine in ('LIGHTEST', 'DARKEST'):
        y = st @ REC709
        pick = (np.argmax if combine == 'LIGHTEST' else np.argmin)(y, axis=0)
        return np.take_along_axis(st, pick[None, :, :, None], axis=0)[0]
    return st.mean(axis=0)


def channel_item(item, coll, ao=False):
    """Decisions 79 to 81: the material channels the job asks for (item['channels']) baked from the object's
    material as Cycles shades it (EMIT through an Emission shader on a copy of each material), from the copy
    item['channel_object'] names (rule item 6), into the master's layout: the stored one while the mesh is unchanged,
    else a new one, which removes the master's AO, curvature and other channels (they no longer fit). The core and
    the skirt of each tile as the AO's, the composition as the AO's without the corner rule. Decision 87: a shared
    mesh's emissive (Copies not One Instance) baked from every copy (its own material slots) and combined per pixel
    (combine_copies). Decisions 88 to 90: a group whose vertex colour source is ticked (VC) from the active colour
    attribute instead of the material, Overwrite or Multiply; ao: the AO from the vertex colour too (into the master's
    own image). A generator like bake_item."""
    t0 = time.time()
    groups = (['ao'] if ao else []) + [g for g in core.CHANNEL_GROUPS if g in (item.get('channels') or ())]
    obj = bpy.data.objects.get(item['object'])
    if obj is None or obj.type != 'MESH':
        return dict(status='skipped', reason='object not in the baked file')
    key = item['key']
    dg = bpy.context.evaluated_depsgraph_get()
    uv_name = item['uv']
    ev = core.evaluated_triangles(obj, dg, [uv_name])
    if uv_name not in ev['uv']:
        return dict(status='skipped', reason=f'no UV map {uv_name} in the baked file')
    mh = core.mesh_hash(ev)
    sizes = item['tex_size']
    skip = set(item['skip_slots'])
    sel = np.array([(m_ not in skip) and (str(int(m_)) in sizes) for m_ in ev['mat'].tolist()], dtype=bool)
    tri_src = np.nonzero(sel)[0]
    if not len(tri_src):
        return dict(status='skipped', reason='no face of a texture set')
    pos_w, _ = core.to_world(ev)
    used = np.unique(ev['tris'][tri_src])
    shift = (pos_w[used].min(axis=0) + pos_w[used].max(axis=0)) / 2  # as the AO bake moves it
    pos, cn = core.to_world(ev, shift)
    tris, cnm = ev['tris'][tri_src], cn[tri_src]
    size = np.array([float(sizes[str(int(m_))]) for m_ in ev['mat'][tri_src]])
    uvpx = ev['uv'][uv_name][tri_src] * size[:, None, None]
    D = core.master_density(pos, tris, uvpx)
    if D <= 0:
        return dict(status='skipped', reason='no face with UV area')
    # rule item 6: a shared mesh's channels from one copy (the bake's choice); its mesh must be the master's
    src_obj, notes = obj, []
    want = item.get('channel_object')
    if want and want != obj.name:
        o = bpy.data.objects.get(want)
        if o is not None and o.type == 'MESH' and core.mesh_hash(core.evaluated_triangles(o, dg)) == mh:
            src_obj = o
        else:
            notes.append(f'{want}: not the same evaluated mesh, baked from {obj.name}')
    # decision 87: a shared mesh's emissive from each copy, combined as the AO's copies (not One Instance)
    combine = item.get('combine') if item.get('copies') else None
    emis_copies = []
    # decision 95: a vertex colour emissive is the mesh's, the same for every copy: not combined; decision 100: a
    # Custom emissive is the copy's the channels come from, not combined either
    if 'emis' in groups and combine and combine != 'ONE' and 'emis' not in VC and 'emis' not in CV:
        for c in item['copies']:
            o = bpy.data.objects.get(c['object'])
            if o is None or o.type != 'MESH':
                notes.append(f"{c['object']}: not in the baked file, its emissive left out")
            elif o is not obj and core.mesh_hash(core.evaluated_triangles(o, dg)) != mh:
                notes.append(f'{o.name}: not the same evaluated mesh, its emissive left out')
            else:
                emis_copies.append(o)
        emis_copies = emis_copies or [src_obj]
    # decisions 88 to 91: the groups from the source colour attribute; without one they are skipped for this object
    vc = {g: VC[g] for g in groups if g in VC and g in VC_COMP and g not in CV}
    cv_vals = dict(item.get('custom_values') or {})
    cv = {g: CV[g] for g in groups if g in CV and g in cv_vals}  # decision 99: the object's own value
    dv = cv if CV_DIRECT else {}  # decision 101: the Custom groups written directly
    vc_attr, vc_type, vc_why = source_color(src_obj, dg) if vc else (None, None, '')
    vc_skipped = []
    if vc and vc_attr is None:
        vc_skipped = list(vc)
        for g in vc_skipped:
            notes.append(f'{VC_NAMES[g]} skipped: {src_obj.name}: {vc_why}')
            log(f"  {item['name']}: {VC_NAMES[g]} skipped ({src_obj.name}: {vc_why})")
        groups = [g for g in groups if g not in vc]
        vc = {}
        if not groups:
            return dict(status='skipped', reason='; '.join(notes), vc_skipped=vc_skipped)
    # decision 111: a Custom albedo with its alpha (4 values) writes the albedo's alpha too
    kinds_of = {g: KINDS[g] + (core.CHANNEL_EXTRA.get(g, ()) if g in cv and len(np.atleast_1d(cv_vals[g])) == 4
                               else ()) for g in groups}
    tb = time.time()
    m, kept, old = layout_for(item, mh, tri_src, pos, tris, cnm, D, uvpx)
    t_build = time.time() - tb
    W, H = m['W'], m['H']
    src = channel_source(src_obj, dg, tri_src)
    # decision 89: Multiply onto the master's current image of the group (the kept layout); without one, onto 1.0
    old_ch = (old or {}).get('channels') or {}
    old_src = (old or {}).get('ao_source') or {}
    mult, eff = {}, {}
    for g, mode in list(vc.items()) + list(cv.items()):  # decision 99: a Custom value as a vertex colour source
        src_name = CV_NAMES[g] if g in cv else VC_NAMES[g]
        paths = [core.image_paths(FOLDER, key, k)[0] for k in KINDS[g]]
        have = kept and all(os.path.isfile(p_) for p_ in paths) and (g == 'ao' or g in old_ch)
        if mode == 'MULTIPLY' and have:
            # decision 111: an optional component (the albedo's alpha) without an image of it is written as it comes
            mult[g] = paths + [p_ if os.path.isfile(p_) else None
                               for p_ in (core.image_paths(FOLDER, key, k)[0] for k in kinds_of[g][len(paths):])]
            eff[g] = 'MULTIPLY'
        else:
            eff[g] = 'OVERWRITE'
            if mode == 'MULTIPLY':
                why = 'a new layout (the mesh changed)' if not kept and old else 'no master of it'
                notes.append(f'{src_name}: Multiply with {why}, as Overwrite')
                log(f"  {item['name']}: {src_name} Multiply with {why}: multiplied onto 1.0 (as Overwrite)")
    # the AO's product of its multiplies since the last trace or Overwrite (rule item 4)
    ao_traced = 'ao' in mult and old_src.get('mode') != 'OVERWRITE'
    vc_prev = core.image_paths(FOLDER, key, 'ao_vc')[0]
    vc_prev = vc_prev if ao_traced and old_src.get('mode') == 'MULTIPLY' and os.path.isfile(vc_prev) else None
    # the skirt's corners as weights of their source triangle's corners (build_master's skirt_src, its 3D points)
    S = len(m['skirt_pos'])
    if S:
        P = pos[tris[m['skirt_src']]]
        Bs = np.stack([_bary3(m['skirt_pos'][:, k], P[:, 0], P[:, 1], P[:, 2]) for k in range(3)], axis=1)
    else:
        Bs = np.zeros((0, 3, 3))
    ws0, _peak0 = core.process_memory()
    forced = int(JOB.get('tile_px') or 0)
    tile = forced or core.choose_tile(W, H, BUDGET, ws0 or 0, views=1)[0]
    tiles = core.tile_grid(W, H, tile)
    n = len(tiles)
    # the components' images and writers: the first writes the map and the layout (a new layout) or compares its
    # codes with the stored map (a kept one)
    kinds = [(g, c, k) for g in groups for c, k in enumerate(kinds_of[g])]
    j_of = {}  # a group's first image
    for j, (g, _c, _k) in enumerate(kinds):
        j_of.setdefault(g, j)
    map_bands, map_readers = None, []
    writers, mats_made, temps_img = [], [], []
    vc_writer = None
    group_mats, skipped = {}, {}
    finished = False
    try:
        for j, (g, c, k) in enumerate(kinds):
            writers.append(core.ChannelWriter(FOLDER, key, k, W, H, threads=int(SET['threads']),
                                              map_mode=(None if j else ('check' if kept else 'write'))))
        # per group, the materials of the copy's slots routed to an Emission shader (temporary copies)
        slot_mats = [s.material for s in src_obj.material_slots]
        used_slots = sorted(set(int(v) for v in np.unique(src['mat']).tolist()))
        holder = new_float_image('FSS_CH_TILE', 4, 4)
        temps_img.append(holder)

        def routed(slots_, g):  # the slots' materials routed to the channel's Emission shader
            lst = []
            for si, mat in enumerate(slots_):
                cp, why = (channel_material(mat, g, holder) if mat is not None else (None, 'no material'))
                if cp is None:
                    if si in used_slots and mat is not None and mat.name not in skipped.get(g, ()):
                        skipped.setdefault(g, []).append(mat.name)
                        log(f"  {item['name']}: {NAMES[g]} skipped for {mat.name} ({why})")
                    cp = _black_material(holder)
                mats_made.append(cp)
                lst.append(cp)
            if not lst:
                lst = [_black_material(holder)]
                mats_made.extend(lst)
            return lst

        for g in groups:
            if g in vc:  # decision 88: the same vertex colour material on every slot
                vm = vc_material(vc_attr, g, holder)
                mats_made.append(vm)
                group_mats[g] = [vm] * max(1, len(slot_mats))
            elif g in dv:  # decision 101: the object's own value written straight into the master, no Cycles
                continue
            elif g in cv:  # decision 99 (tests, FSS_AO_BAKE_CUSTOM_CYCLES): the value on every slot, through Cycles
                vm = value_material(cv_vals[g], g, holder)
                mats_made.append(vm)
                group_mats[g] = [vm] * max(1, len(slot_mats))
            else:
                group_mats[g] = routed(slot_mats, g)
        copy_mats = [(o, routed([s_.material for s_ in o.material_slots], 'emis')) for o in emis_copies]
        cyc = [g for g in groups if g not in dv]  # decision 101: the groups Cycles bakes
        log(f"  {item['name']}: {', '.join(NAMES[g] for g in groups)} from {src_obj.name}, master {W} x "
            f"{H} px ({'its layout kept' if kept else 'a new layout'}), tile {tile} px, {n} tile(s), "
            + (f"{CH_SAMPLES} samples" if cyc else 'no Cycles'))
        if copy_mats:
            log(f"    Emissive from {len(copy_mats)} copies ({combine.lower()}): "
                + ', '.join(o.name for o, _l in copy_mats))
        if vc:
            log(f"    from the colour attribute {vc_attr} ({vc_type}, {VC_ATTRIBUTE.lower()}): "
                + ', '.join(f'{VC_NAMES[g]} ({eff[g].lower()})' for g in vc))
        if cv:
            log("    from the object's own value" + (', written directly: ' if dv else ': ')
                + ', '.join(f'{CV_NAMES[g]} {cv_vals[g]} ({eff[g].lower()})' for g in cv))
        state.update(tile=0, n_tiles=n, size=[int(W), int(H)], tile_px=int(tile))
        write_status()
        core_tris = m['core_tris']
        cuv = m['muv'][core_tris]
        times = dict(bake=0.0, direct=0.0)
        done = [0]
        # decision 101: a Custom group's 16-bit value per component, as the master keeps it (the colours sRGB-encoded,
        # as a bake of the colour gives them); its pixels: those the core and the skirt cover, as Cycles fills them
        cv_q = {}
        for g in dv:
            v = np.atleast_1d(np.asarray(cv_vals[g], dtype=np.float64))
            enc = core.srgb_encode(v) if g in ('albedo', 'emis') else np.clip(v, 0.0, 1.0)
            if g == 'albedo' and len(v) == 4:  # decision 111: the alpha linear
                enc = np.concatenate([enc[:3], np.clip(v[3:], 0.0, 1.0)])
            cv_q[g] = [int(q) for q in np.atleast_1d(core.quantize16(enc))][:len(kinds_of[g])]
        n_threads = int(SET['threads'])
        # decision 101: a kept layout's Custom pixels are the stored map's filled ones (the pixels Apply reads, whatever
        # rasterized them); a new layout's those Cycles fills for another group of the bake, else the raster's
        mpath = core.master_paths(FOLDER, key)[1]
        if dv and kept and os.path.isfile(mpath):
            map_bands = _MapBands(mpath, W, H)

        def covered(csel, ssel, x0, y0, w, h, rect_ok):
            """Decision 101: the pixels of a tile a bake fills: the core triangles' (pixel centres inside), then the
            skirt's within the island rectangles where the core is not."""
            cm = np.zeros((h, w), bool)
            sm = np.zeros((h, w), bool)
            if len(csel):
                own, _c = core.raster_window(cuv[csel], w, h, 1, x0, y0, threads=n_threads)
                cm = own >= 0
            if len(ssel):
                own, _c = core.raster_window(m['skirt_uv'][ssel], w, h, 1, x0, y0, threads=n_threads)
                sm = (own >= 0) & ~cm & rect_ok
            return cm, sm

        def set_image(img):
            for lst in list(group_mats.values()) + [l_ for _o, l_ in copy_mats]:
                for mat in lst:
                    mat.node_tree.nodes.active.image = img

        def bake_tile(i, rect, vals, baked):
            x0, y0, w, h = rect
            done[0] += 1
            state['tile'] = done[0]
            write_status()
            off = np.array([x0, y0], dtype=np.float64)
            wh = np.array([w, h], dtype=np.float64)
            csel = core.tris_in_window(cuv, x0, y0, w, h)
            ssel = core.tris_in_window(m['skirt_uv'], x0, y0, w, h) if S else np.zeros(0, dtype=np.int64)
            if len(csel) or len(ssel):
                rect_ok = core.rect_window(m['rects'], x0, y0, w, h) >= 0
                img = px = None
                objs = []
                dm = None
                td = time.time()
                if dv and map_bands is not None:
                    dm = map_bands.window(x0, y0, w, h)
                elif dv and not cyc:
                    dcm, dsm = covered(csel, ssel, x0, y0, w, h, rect_ok)
                    dm = dcm | dsm
                times['direct'] += time.time() - td
                try:
                    if cyc:
                        img = new_float_image('FSS_CH_TILE', w, h)
                        px = np.empty(w * h * 4, dtype=np.float32)
                        set_image(img)
                    first = group_mats[cyc[0]] if cyc else None
                    if cyc and len(csel):
                        me = channel_mesh('FSS_CH_CORE', src, core_tris[csel], None, (cuv[csel] - off) / wh, first)
                        objs.append(('core', temp_object(coll, 'FSS_CH_CORE', me)))
                    if cyc and len(ssel):
                        me = channel_mesh('FSS_CH_SKIRT', src, m['skirt_src'][ssel], Bs[ssel],
                                          (m['skirt_uv'][ssel] - off) / wh, first)
                        objs.append(('skirt', temp_object(coll, 'FSS_CH_SKIRT', me)))
                    for o in (o for _k, o in objs):
                        o.matrix_world = src_obj.matrix_world  # Object and Position coordinates as the original's
                    for g in cyc + list(dv):  # the Cycles groups first: their pixels serve a new layout's Custom ones
                        j = j_of[g]
                        if g in dv:  # decision 101: the value into the covered pixels
                            for c in range(len(kinds_of[g])):
                                vals[j][dm] = cv_q[g][c]
                                baked[j] |= dm
                                j += 1
                            continue
                        got = {}
                        if g == 'emis' and copy_mats:  # decision 87: each copy, combined per pixel
                            per = []
                            for o_c, lst_c in copy_mats:
                                got_c = {}
                                for part, o in objs:
                                    o.matrix_world = o_c.matrix_world
                                    for si, mat in enumerate(lst_c):
                                        o.data.materials[si] = mat
                                    tb_ = time.time()
                                    got_c[part] = bake_emit(o, img, px, CH_SAMPLES)
                                    times['bake'] += time.time() - tb_
                                per.append(got_c)
                            got = {part: combine_copies([p_[part] for p_ in per], combine) for part, _o in objs}
                            for _part, o in objs:
                                o.matrix_world = src_obj.matrix_world
                        for part, o in ([] if got else objs):
                            for si, mat in enumerate(group_mats[g]):
                                o.data.materials[si] = mat
                            tb_ = time.time()
                            got[part] = bake_emit(o, img, px, CH_SAMPLES)
                            times['bake'] += time.time() - tb_
                        A, B = got.get('core'), got.get('skirt')
                        cm = A[:, :, 0] >= 0 if A is not None else np.zeros((h, w), bool)
                        sm = ((~cm) & (B[:, :, 0] >= 0) & rect_ok) if B is not None else np.zeros((h, w), bool)
                        # albedo and emissive sRGB-encoded; the other data linear as it is (decision 92: a
                        # vertex colour's value as the node gives it, a byte colour's too)
                        srgb = g in ('albedo', 'emis')
                        enc = core.srgb_encode if srgb else (lambda v: np.clip(v, 0.0, 1.0))
                        for c in range(len(kinds_of[g])):
                            if c == 3:  # decision 111: a Custom albedo's alpha, the object's value (no Cycles)
                                vals[j][cm | sm] = core.quantize16(np.clip(float(cv_vals[g][3]), 0.0, 1.0))
                            if c < 3 and A is not None:
                                vals[j][cm] = core.quantize16(enc(A[:, :, c][cm]))
                            if c < 3 and B is not None:
                                vals[j][sm] = core.quantize16(enc(B[:, :, c][sm]))
                            baked[j] |= cm | sm
                            j += 1
                        if dv and dm is None:
                            dm = cm | sm
                finally:
                    _remove([o for _k, o in objs])
                    if img is not None:
                        set_image(holder)
                        bpy.data.images.remove(img)
            yield done[0]
        # decision 89: Multiply: each row times the current image's (the albedo in linear), the product of the AO's
        # multiplies kept; pixels this bake does not fill keep their old value. The current images are read whole.
        lib = core.jxl()
        if ao_traced:
            vc_writer = core.ChannelWriter(FOLDER, key, 'ao_vc', W, H, threads=int(SET['threads']))
        prev = lib.read_whole(vc_prev) if vc_prev else None

        def rows_of(j, g, c):
            """Decision 101: a Custom group of a kept layout: its value on exactly the stored map's filled pixels (those
            Apply reads; the bake's margins already in them), 0 elsewhere, with the stored codes, whatever the
            composition of its pixels gave; then Overwrite or Multiply as for a baked group."""
            inner = rows_base(j, g, c)
            if g not in dv or map_bands is None:
                return inner
            rd = _MapRows(mpath, W, H)
            map_readers.append(rd)
            q = np.uint16(cv_q[g][c])

            def rows(values, codes):
                sc = rd.read(values.shape[0])
                inner(np.where(core.code_filled(sc), q, np.uint16(0)).astype(np.uint16), sc)
            return rows

        def rows_base(j, g, c):
            w_ = writers[j]
            if g not in mult or mult[g][c] is None:
                return w_.write_rows
            cur = lib.read_whole(mult[g][c])
            at = [0]

            def rows(values, codes):
                y0, n_ = at[0], values.shape[0]
                at[0] += n_
                o_ = cur[y0:y0 + n_]
                filled = core.code_filled(codes)
                a_, b_ = o_.astype(np.float64) / 65535.0, values.astype(np.float64) / 65535.0
                if g in ('albedo', 'emis') and c < 3:  # the colours multiplied in linear (an alpha as it is)
                    prod = core.srgb_encode(core.srgb_decode(a_) * core.srgb_decode(b_))
                else:
                    prod = a_ * b_
                w_.write_rows(np.where(filled, core.quantize16(prod), o_).astype(np.uint16), codes)
                if g == 'ao' and vc_writer is not None:
                    pv = prev[y0:y0 + n_].astype(np.float64) / 65535.0 if prev is not None else 1.0
                    vc_writer.write_rows(np.where(filled, core.quantize16(pv * b_), 65535).astype(np.uint16), None)
            return rows
        tp = time.time()
        counts = yield from core.bake_paged_multi(m, tile, len(kinds), bake_tile,
                                                  [rows_of(j, g, c) for j, (g, c, _k) in enumerate(kinds)],
                                                  threads=int(SET['threads']))
        t_compose = time.time() - tp - times['bake'] - times['direct']
        for w_ in writers + ([vc_writer] if vc_writer is not None else []):
            w_.encode()
        meta = dict(schema=core.SCHEMA, key=key, kind=item['kind'], name=item['name'], object=obj.name, mesh_hash=mh,
                    **core.method_settings())
        if m.get('object_uv'):  # decision 107
            meta['object_uv'] = m['object_uv']
        if not kept:  # decision 81: a new layout; what was baked into the old one is removed
            _remove_files(list(core.image_paths(FOLDER, key)) + list(core.image_paths(FOLDER, key, 'curv'))
                          + list(core.image_paths(FOLDER, key, 'ao.raw')) + [os.path.join(FOLDER, key + core.THUMB_EXT)]
                          + list(core.image_paths(FOLDER, key, 'ao_vc'))
                          + [p for g in core.CHANNEL_GROUPS for p in core.channel_paths(FOLDER, key, g, True)])
        raw = core.image_paths(FOLDER, key, 'ao.raw')[0]
        if ao_traced and not os.path.isfile(raw):  # the traced AO before the multiply: what a denoise starts from
            shutil.copy2(core.image_paths(FOLDER, key)[0], raw)
        for j, w_ in enumerate(writers):
            w_.commit(m, tri_src, meta)
        if vc_writer is not None:
            vc_writer.commit()
        for g in groups:  # decision 111: an optional component this bake did not write no longer matches the
            if eff.get(g) != 'MULTIPLY':  # others (a Multiply onto the colours keeps it)
                _remove_files([core.image_paths(FOLDER, key, k)[0] for k in core.CHANNEL_EXTRA.get(g, ())
                               if k not in kinds_of[g]])
        if 'ao' in groups and not ao_traced:  # an AO from the vertex colour alone: no raw bake, no product
            _remove_files(list(core.image_paths(FOLDER, key, 'ao.raw')) + list(core.image_paths(FOLDER, key, 'ao_vc')))
        finished = True
    finally:
        if map_bands is not None:
            map_bands.close()
        for rd in map_readers:
            rd.close()
        if not finished:
            for w_ in writers + ([vc_writer] if vc_writer is not None else []):
                w_.abort()
        for mat in mats_made:
            if mat.name in bpy.data.materials:
                bpy.data.materials.remove(mat)
        for img in temps_img:
            if img.name in bpy.data.images:
                bpy.data.images.remove(img)
    differs = writers[0].map_differs if kept else 0
    if kept and differs:
        log(f"  {item['name']}: {differs} px of the stored map differ from this bake's coverage")
    stamp = time.strftime('%Y-%m-%d %H:%M:%S')
    entry = _index_entry(key) if kept else None
    if entry is None:  # a new layout: an entry of the layout and the channels only (AO missing, decision 81)
        entry = dict(key=key, kind=item['kind'], name=item['name'], object=obj.name, mesh=obj.data.name,
                     mesh_hash=mh, density=float(m['density']), W=int(W), H=int(H), tris=int(len(tri_src)),
                     islands=int(m['n_islands']), uv=uv_name, method=core.METHOD, schema=core.SCHEMA, baked_at=stamp)
    ch = dict(entry.get('channels') or {})
    for g in groups:
        if g == 'ao':
            continue
        ch[g] = dict(mesh_hash=mh, baked_at=stamp, samples=0 if g in dv else int(CH_SAMPLES), object=src_obj.name,
                     skipped=sorted(skipped.get(g, [])), map_differs_px=int(differs))
        if g in vc:  # rule item 5: the source; a bake from the material drops it (the entry written anew)
            ch[g]['source'] = dict(vertex_color=vc_attr, attribute=VC_ATTRIBUTE, mode=eff[g])
        elif g in cv:  # decision 99
            ch[g]['source'] = dict(custom=_cv_json(cv_vals[g]), mode=eff[g])
        if len(kinds_of[g]) > len(KINDS[g]) or (eff.get(g) == 'MULTIPLY' and (old_ch.get(g) or {}).get('alpha')):
            ch[g]['alpha'] = True  # decision 111: the albedo's alpha
    if 'ao' in groups:  # rule item 4: the AO from the vertex colour
        attrs = (list(old_src.get('attributes') or ()) if 'ao' in mult else []) + [vc_attr]
        entry['ao_source'] = dict(vertex_color=vc_attr, attribute=VC_ATTRIBUTE,
                                  mode='MULTIPLY' if ao_traced else 'OVERWRITE', attributes=attrs)
        if not ao_traced:
            entry['denoise'] = None
        entry.update(mesh_hash=mh, baked_at=stamp)
    if 'emis' in groups and combine and 'emis' not in vc and 'emis' not in cv:  # decision 87: how it was combined
        ch['emis'].update(combine=combine,
                          copies=[o.name for o, _l in copy_mats] if copy_mats else [src_obj.name])
    entry['channels'] = ch
    update_index(entry)
    for g, names in sorted(skipped.items()):
        notes.append(f"{NAMES[g]} skipped for {', '.join(names)} (no Principled BSDF on the Material "
                     f"Output)")
    log(f"  {item['name']}: channels composed in {t_compose:.2f} s, baked in {times['bake']:.2f} s"
        + (f", Custom written in {times['direct']:.2f} s" if dv else '')
        + f"; layout {t_build:.2f} s; {len(kinds)} images")
    cyc = [g for g in groups if g not in dv]
    res = dict(status='baked', W=int(W), H=int(H), tile=int(tile), n_tiles=int(n), bake_s=round(times['bake'], 3),
               total_s=round(time.time() - t0, 3), baker='Cycles' if cyc else 'Custom value', channels=groups,
               layout_kept=bool(kept), map_differs_px=int(differs))
    if dv:  # decision 101
        res['direct_s'] = round(times['direct'], 3)
    if vc or vc_skipped:
        res['vertex_color'] = dict(attribute=vc_attr, type=vc_type, read=VC_ATTRIBUTE,
                                   modes={g: eff[g] for g in vc}, skipped=vc_skipped)
    if cv:  # decision 99
        res['custom_value'] = {g: dict(value=_cv_json(cv_vals[g]), mode=eff[g]) for g in cv}
    if notes:
        res['note'] = '; '.join(notes)
    return res


def run_item(item, coll):
    """One job item (a generator, as bake_item): its AO (with curvature and denoise), or its curvature and denoise
    alone, then its material channels (decision 79)."""
    res = None
    vc_ao = item.get('ao', True) and 'ao' in VC  # decision 88: the AO from the vertex colour, not traced
    if item.get('ao', True) and not vc_ao:
        res = yield from bake_item(item, coll)
    elif not vc_ao and (item.get('cm') or item.get('dn') or not item.get('channels')):
        res = yield from curvature_item(item, coll)
    if (vc_ao or item.get('channels')) and (res is None or res.get('status') in ('baked', 'updated')):
        got = yield from channel_item(item, coll, ao=vc_ao)
        if vc_ao and item.get('cm') and got.get('status') == 'baked':  # the curvature as before (from geometry)
            cres = yield from curvature_item(dict(item, cm=True, dn=False), coll)
            if cres.get('status') != 'updated':
                got['note'] = '; '.join(x for x in (got.get('note'), f"curvature: {cres.get('reason')}") if x)
        if res is None or got.get('status') != 'baked':
            note = '; '.join(x for x in ((res or {}).get('note'), got.get('note')) if x)
            res = dict(got, **({'note': note} if note else {}))
        else:
            res['channels'] = got['channels']
            note = '; '.join(x for x in (res.get('note'), got.get('note')) if x)
            if note:
                res['note'] = note
    return res


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
        # decision 55: the AO, or the curvature and denoise alone; decision 79: then the material channels
        _run.update(t=time.time(), gen=run_item(ITEMS[i], _run['coll']), tiles_done=0)
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
        _run.update(gen=run_item(item, _run['coll']), tiles_done=0)
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
