"""AO Bake: the script of the second Blender that bakes the masters (auto-bake journal, decisions 12, 15, 16, 27, 34 to
36).

Started by ao_bake_store.start_bake on the saved .blend:
    blender --factory-startup [-b] <file.blend> --python ao_bake_runner.py -- <job.json>
Hidden (-b, the default run mode, decision 36) it bakes the tiles one after another; with a window it bakes one tile
per timer step, so the window keeps updating, and shows a reduced preview of the master in an Image Editor (its 3D
views are turned into Image Editors, so the scene is not drawn). In both it writes a small preview of the master
being baked (core.PREVIEW_FILE) for the artist's Blender after each tile and composed strip (at most every 0.25 s). It
loads ao_bake_core.py by its path (the add-on is not enabled in this Blender), prints one line per object (and per
tile), writes status.json (object n of m, tile i of n) and stops when a file `cancel` appears in the bake folder:
between objects, or between tiles, in which case the object keeps its old master. It never saves the .blend and quits
without saving when done.

Per master (P35, decisions 15 and 30; the prototype's step3_master.py): the target's evaluated triangles of a texture
set (a material that is not a skip material), in world space moved so the target's bounds are centred at the origin;
the occluders the job lists (evaluated, skip faces dropped, moved the same way); every other object hidden from
rendering. The master layout at 4 x the target's median density. The bake in tiles (decisions 31, 32): the master's
pixel area is cut into square tiles whose size fits the memory budget (ao_bake_core.choose_tile); each tile is one
Cycles bake of the core triangles that overlap it, then one of the skirt's, with UVs relative to the tile, into a
tile-sized image (Cycles clips a triangle at the image's edges: Session 20), each tile with its own seed. The master is
paged (decision 33, Session 23): a row of tiles is a band; the bands are baked from the top, and once a band is baked
the band above it is composed (it now has its halo) and written to <stem>.ao.map and, for the AO, to a raw scratch file
row by row, then dropped; only two bands are held, never the whole master. At the end the AO is encoded as lossless
JPEG XL, <stem>.ao.jxl (decision 37; PNG, <stem>.ao.png, when the library cannot be loaded, logged once), then
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

JOB_PATH = sys.argv[sys.argv.index('--') + 1]
with open(JOB_PATH, encoding='utf-8') as _f:
    JOB = json.load(_f)
FOLDER = JOB['folder']
STATUS = os.path.join(FOLDER, 'status.json')
CANCEL = os.path.join(FOLDER, 'cancel')
LOG = os.path.join(FOLDER, 'bake.log')
SET = JOB['settings']
ITEMS = JOB['items']
TMP = 'FSS_AO_BAKE_TMP'
# the memory budget (decision 32): FSS_AO_BAKE_MEMORY_GB (tests) or the job's, else a share of the free memory
_override = os.environ.get('FSS_AO_BAKE_MEMORY_GB') or JOB.get('memory_budget_gb')
BUDGET = core.memory_budget(_override)
SEED_OFFSET = int(os.environ.get('FSS_AO_BAKE_SEED_OFFSET') or 0)  # tests only: a control bake with other noise
BUDGET_SOURCE = f'override {_override} GB' if _override else (
    f'{core.BUDGET_SHARE:.0%} of the free memory, at most {core.BUDGET_MAX // 2 ** 30} GB')


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
    done = state['n_done']
    if done:
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
    index['settings'] = dict(ao_distance=SET['ao_distance'], samples=SET['samples'], **core.method_settings())
    index.setdefault('masters', {})[entry['key']] = entry
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(index, f, indent=1)
    _replace(tmp, path)


# ---------------------------------------------------------------------------------------------------------------------
# Scene and Cycles (tests/bake_prototype/bake_common.py)
# ---------------------------------------------------------------------------------------------------------------------

def setup_scene():
    scene = bpy.context.scene
    for obj in bpy.data.objects:
        obj.hide_render = True
    coll = bpy.data.collections.new(TMP)
    scene.collection.children.link(coll)
    scene.render.engine = 'CYCLES'
    cy = scene.cycles
    cy.use_denoising = False
    cy.use_adaptive_sampling = False
    cy.use_animated_seed = False
    scene.render.threads_mode = 'FIXED'
    scene.render.threads = int(SET['threads'])
    if scene.world is None:
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


def bake(obj, img, seed, from_obj):
    """The prototype's bake: AO Selected to Active from `from_obj` into img (pre-filled with -1), margin 0."""
    scene = bpy.context.scene
    scene.cycles.samples = int(SET['samples'])
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
    for o in bpy.context.view_layer.objects:
        if o is not None:
            o.select_set(False)
    from_obj.select_set(True)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    rb = scene.render.bake
    rb.margin = 0
    rb.use_clear = False
    rb.use_selected_to_active = True
    rb.target = 'IMAGE_TEXTURES'
    t = time.time()
    kw = dict(type='AO', margin=0, margin_type='ADJACENT_FACES', use_clear=False, use_selected_to_active=True,
              target='IMAGE_TEXTURES', cage_extrusion=core.EXTRUSION, max_ray_distance=core.RAY_DISTANCE,
              use_cage=False)
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

PREVIEW_MAX = 2048  # the long side of the preview in the window
PREVIEW_EVERY_S = 0.25  # the preview file at most this often (and at the end of each master)


class Preview:
    """A reduced copy of the master being baked (every f-th pixel, at most PREVIEW_MAX px on the long side with a
    window, core.PREVIEW_FILE_MAX without), updated from each tile and each composed strip. Written to the bake
    folder's preview file for the artist's Blender (decision 36), at most every PREVIEW_EVERY_S seconds and at the end;
    with a window also shown in its Image Editor. Its size does not depend on the master's."""

    seq = 0  # over the whole run, so the artist's Blender sees each update

    def __init__(self, W, H):
        self.on = not bpy.app.background
        self.f = max(1, -(-max(W, H) // (PREVIEW_MAX if self.on else core.PREVIEW_FILE_MAX)))
        self.pv = np.zeros((-(-H // self.f), -(-W // self.f)), np.uint16)
        self.written = 0.0

    def put(self, x0, y0, block):
        """block (h, w) uint16 at (x0, y0) of the master."""
        f = self.f
        h, w = block.shape
        ax, ay = -x0 % f, -y0 % f
        if ax >= w or ay >= h:
            return
        part = block[ay::f, ax::f]
        px, py = (x0 + ax) // f, (y0 + ay) // f
        self.pv[py:py + part.shape[0], px:px + part.shape[1]] = part

    def show(self, final=False):
        now = time.time()
        if not final and now - self.written < PREVIEW_EVERY_S:
            return
        Preview.seq += 1
        core.write_preview(FOLDER, self.pv, Preview.seq)
        self.written = now
        if not self.on:
            return
        pv = self.pv
        ph, pw = pv.shape
        img = _shown.get('img')
        if img is None or img.name not in bpy.data.images or tuple(img.size) != (pw, ph):
            if img is not None and img.name in bpy.data.images:
                bpy.data.images.remove(img)
            img = bpy.data.images.new('AO master', pw, ph, alpha=False, float_buffer=True, is_data=True)
            _shown['img'] = img
        px = np.ones((ph, pw, 4), dtype=np.float32)
        px[:, :, :3] = (pv.astype(np.float32) / 65535.0)[:, :, None]
        img.pixels.foreach_set(px.ravel())
        img.update()
        wm = bpy.context.window_manager
        for window in wm.windows:
            # decision 36: no 3D view, so the window does not draw the whole scene; the master instead
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.type = 'IMAGE_EDITOR'
            areas = sorted(window.screen.areas, key=lambda a: -a.width * a.height)
            if areas and not any(a.type == 'IMAGE_EDITOR' for a in areas):
                areas[0].type = 'IMAGE_EDITOR'
            for area in areas:
                if area.type == 'IMAGE_EDITOR':
                    area.spaces.active.image = img
                    area.tag_redraw()


_shown = {}


def _remove(objs):
    for o in objs:
        if o is None or o.name not in bpy.data.objects:
            continue
        me = o.data
        bpy.data.objects.remove(o)
        if me is not None and me.users == 0:
            bpy.data.meshes.remove(me)
    bpy.context.view_layer.update()  # else the view layer's object list keeps the removed objects as None


def _bake_piece(coll, name, positions, normals, uv, img, px, seed, target, matrix=None):
    """One Cycles bake of these triangles (already relative to the tile) into the tile image; returns (red, seconds).
    matrix: the pose's placement of the target (decision 34), None for the current frame."""
    n = len(positions)
    me = build_mesh(name, positions.reshape(-1, 3), np.arange(n * 3).reshape(-1, 3), normals, uv)
    obj = temp_object(coll, name, me)
    if matrix is not None:
        obj.matrix_world = matrix
    set_ray_invisible(obj)
    try:
        clear_image(img, px)
        dt = bake(obj, img, seed, target)
    finally:
        _remove([obj])
    return read_red(img, px), dt


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


def bake_item(item, coll):
    """Bakes one master; a generator that yields after each tile (the caller checks Cancel between tiles and, with a
    window, lets it redraw), and returns the result. Closing it between tiles leaves the old master as it was.

    Paged (decision 33): the bands are baked from the top (the PNG is written from the top), each band's tiles from the
    left; once a band is baked, the band above it has its halo and is composed and written; nothing is held for the
    whole master. Each tile keeps the seed of its place in core.tile_grid, so the result is Session 20's."""
    t0 = time.time()
    obj = bpy.data.objects.get(item['object'])
    if obj is None or obj.type != 'MESH':
        return dict(status='skipped', reason='object not in the saved file')
    dg = bpy.context.evaluated_depsgraph_get()
    uv_name = item['uv']
    ev = core.evaluated_triangles(obj, dg, [uv_name])
    if uv_name not in ev['uv']:
        return dict(status='skipped', reason=f'no UV map {uv_name} in the saved file')
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
    t_build = time.time() - tb
    W, H = m['W'], m['H']
    # the tile size, which is also the band's height (decisions 32, 33): forced by a test, else the largest that fits
    ws0, _peak0 = core.process_memory()
    forced = int(JOB.get('tile_px') or 0)
    if forced:
        tile, est, fits = forced, None, True
    else:
        tile, est, fits = core.choose_tile(W, H, BUDGET, ws0 or 0)
    tiles = core.tile_grid(W, H, tile)
    n = len(tiles)
    nb = -(-H // tile)  # bands
    gb = 2 ** 30
    log(f"  {item['name']}: master {W} x {H} px ({W * H / 1e6:.1f} Mpx), tile {tile} px, {n} tile(s) in {nb} band(s); "
        f"budget {BUDGET / gb:.1f} GB" + (f", estimate {est / gb:.2f} GB" if est else ' (tile forced)')
        + ('' if fits else ', the smallest tile exceeds the budget'))
    state.update(tile=0, n_tiles=n, size=[int(W), int(H)], tile_px=int(tile))
    write_status()
    temps = []
    counts = dict(core_px=0, skirt_px=0)
    times = dict(core=0.0, skirt=0.0, tiles=0.0)
    core_tris = m['core_tris']
    cuv = m['muv'][core_tris]
    ns = len(m['skirt_pos'])
    preview = Preview(W, H)
    files = core.MasterWriter(FOLDER, item['key'], W, H, threads=int(SET['threads']))
    finished = False
    done = [0]
    poses = dict(mats=None, posed=[])  # decision 34: per pose the target's placement and the posed occluders

    def set_pose(p):
        target.matrix_world = poses['mats'][p]
        for q, objs in enumerate(poses['posed']):
            for o in objs:
                o.hide_render = q != p

    def bake_tile_poses(i, rect, win, baked, csel, ssel, img, px, off, wh):
        """Decision 34: the tile in every pose, summed per pixel in the tile's own buffers and averaged; each pose with
        its own seed. Yields between poses (Cancel)."""
        x0, y0, w, h = rect
        npose = len(poses['mats'])
        csum, ccnt = np.zeros((h, w), np.float64), np.zeros((h, w), np.int32)
        ssum, scnt = np.zeros((h, w), np.float64), np.zeros((h, w), np.int32)
        for p in range(npose):
            state['pose'] = p + 1
            write_status()
            set_pose(p)
            mat = poses['mats'][p]
            if len(csel):
                ct = core_tris[csel]
                A, dt = _bake_piece(coll, 'FSS_AO_CORE', pos[tris[ct]], cnm[ct], (cuv[csel] - off) / wh, img, px,
                                    core.tile_seed(core.pose_seed(core.SEEDS[0] + SEED_OFFSET, p), i, n), target, mat)
                times['core'] += dt
                ok = A >= 0
                csum[ok] += A[ok]
                ccnt[ok] += 1
                del A, ok
            if len(ssel):
                B, dt = _bake_piece(coll, 'FSS_AO_SKIRT', m['skirt_pos'][ssel], m['skirt_n'][ssel],
                                    (m['skirt_uv'][ssel] - off) / wh, img, px,
                                    core.tile_seed(core.pose_seed(core.SEEDS[1] + SEED_OFFSET, p), i, n), target, mat)
                times['skirt'] += dt
                ok = B >= 0
                ssum[ok] += B[ok]
                scnt[ok] += 1
                del B, ok
            if p < npose - 1:
                yield done[0]
        cm = ccnt > 0
        win[cm] = core.quantize16(csum[cm] / ccnt[cm])
        counts['core_px'] += int(cm.sum())
        sm = (~cm) & (scnt > 0) & (core.rect_window(m['rects'], x0, y0, w, h) >= 0)
        win[sm] = core.quantize16(ssum[sm] / scnt[sm])
        counts['skirt_px'] += int(sm.sum())
        baked |= cm | sm

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
        if (len(csel) or len(ssel)) and poses['mats']:
            img = new_float_image('FSS_AO_TILE', w, h)
            px = np.empty(w * h * 4, dtype=np.float32)
            try:
                yield from bake_tile_poses(i, rect, win, baked, csel, ssel, img, px, off, wh)
            finally:
                bpy.data.images.remove(img)
                del px
        elif len(csel) or len(ssel):
            img = new_float_image('FSS_AO_TILE', w, h)
            px = np.empty(w * h * 4, dtype=np.float32)
            try:
                cm = np.zeros((h, w), dtype=bool)
                if len(csel):
                    ct = core_tris[csel]
                    A, dt = _bake_piece(coll, 'FSS_AO_CORE', pos[tris[ct]], cnm[ct], (cuv[csel] - off) / wh, img, px,
                                        core.tile_seed(core.SEEDS[0] + SEED_OFFSET, i, n), target)
                    times['core'] += dt
                    cm = A >= 0
                    win[cm] = core.quantize16(A[cm])
                    counts['core_px'] += int(cm.sum())
                    del A
                sm = np.zeros((h, w), dtype=bool)
                if len(ssel):
                    B, dt = _bake_piece(coll, 'FSS_AO_SKIRT', m['skirt_pos'][ssel], m['skirt_n'][ssel],
                                        (m['skirt_uv'][ssel] - off) / wh, img, px,
                                        core.tile_seed(core.SEEDS[1] + SEED_OFFSET, i, n), target)
                    times['skirt'] += dt
                    sm = (~cm) & (B >= 0) & (core.rect_window(m['rects'], x0, y0, w, h) >= 0)
                    win[sm] = core.quantize16(B[sm])
                    counts['skirt_px'] += int(sm.sum())
                    del B
                baked |= cm | sm
                del cm, sm
            finally:
                bpy.data.images.remove(img)
                del px
        if n > 1:
            log(f"    tile {done[0]}/{n} at ({x0}, {y0}) {w} x {h}: {len(csel)} core and {len(ssel)} skirt "
                f"triangles, {time.time() - tt:.2f} s")
        preview.put(x0, y0, win)
        preview.show()
        times['tiles'] += time.time() - tt
        yield done[0]

    try:
        # the target (selected) and the occluders, moved by -shift; every original object is hidden from rendering
        distinct = np.array([len(set(r)) == 3 for r in tris.tolist()])
        tme = build_mesh('FSS_AO_TARGET', pos, tris[distinct], cnm[distinct])
        tme.materials.clear()
        target = temp_object(coll, 'FSS_AO_TARGET', tme)
        temps.append(target)
        posed_occ = []
        for occ in item['occluders']:
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
        state.update(pose=0, n_poses=len(frames) if frames else 1)
        # paged (decision 33): bands from the top, each composed and written once the band below it is baked
        tp = time.time()
        times['tiles'] = 0.0
        yield from core.bake_paged(m, tile, bake_tile, files.write_rows, counts,
                                   lambda y, v: (preview.put(0, y, v), preview.show()))
        t_compose = time.time() - tp - times['tiles']
        t_core, t_skirt = times['core'], times['skirt']
        counts['image_px'] = int(W * H)
        meta = dict(schema=core.SCHEMA, key=item['key'], kind=item['kind'], name=item['name'], object=obj.name,
                    mesh_hash=mh, ao_distance=SET['ao_distance'], samples=SET['samples'], **core.method_settings())
        ts = time.time()
        files.finish(m, tri_src, meta)
        finished = True
        core.write_preview(FOLDER, preview.pv, 0, name=item['key'] + core.THUMB_EXT)  # the object's preview
        t_save = time.time() - ts
    finally:
        _remove(temps)
        if not finished:
            files.abort()
    preview.show(final=True)
    _ws, peak = core.process_memory()
    if pose_note:
        log(f"  {item['name']}: {pose_note}")
    entry = dict(key=item['key'], kind=item['kind'], name=item['name'], object=obj.name, mesh=obj.data.name,
                 poses=frames, n_poses=len(frames) if frames else 1, pose_note=pose_note,
                 occluder_mode=item.get('occluder_mode', 'SCENE'),
                 mesh_hash=mh, mesh_hash_at_job=item.get('mesh_hash'), surround_hash=item['surround_hash'],
                 density=float(D), W=int(W), H=int(H), tris=int(len(tri_src)), islands=int(m['n_islands']),
                 samples=int(SET['samples']), ao_distance=float(SET['ao_distance']), method=core.METHOD,
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
               n_poses=entry['n_poses'])
    if pose_note:
        res['note'] = pose_note
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
        + (f" {res.get('W')}x{res.get('H')} px in {res.get('n_tiles')} tile(s) of {res.get('tile')} px, bake "
           f"{res.get('bake_s')} s" if res['status'] == 'baked' else '')
        + (f", {res['n_poses']} poses" if (res.get('n_poses') or 1) > 1 else '')
        + (f" ({res['reason']})" if res.get('reason') else '') + f", {res['seconds']} s"
        + (f", peak working set {state['peak_working_set_gb']} GB" if peak else ''))
    state.update(tile=0, n_tiles=0, pose=0, n_poses=0)
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
        state.update(tile=0, n_tiles=0, pose=0, n_poses=0)
        write_status()
        _run.update(t=time.time(), gen=bake_item(ITEMS[i], _run['coll']), tiles_done=0)
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


def finish():
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
    log(f"AO bake of {len(ITEMS)} masters from {JOB['blend']}: distance {SET['ao_distance']} m, samples "
        f"{SET['samples']}, device {SET['device']}, threads {SET['threads']}; memory budget {BUDGET / gb:.1f} GB"
        + (f" ({BUDGET_SOURCE}; physical {total / gb:.1f} GB, free {avail / gb:.1f} GB)" if total else
           f' ({BUDGET_SOURCE})'))
    state.update(budget_gb=round(BUDGET / gb, 2), budget_source=BUDGET_SOURCE)
    lib = core.jxl()  # decision 37: JPEG XL masters; PNG when the library cannot be loaded, said once
    if lib.available():
        state.update(master_format='jxl', jxl_library=lib.version())
        log(f'masters as lossless JPEG XL (libjxl {lib.version()}, effort {lib.EFFORT})')
    else:
        state.update(master_format='png', jxl_error=lib.error())
        log(f'masters as PNG: the JPEG XL library could not be loaded ({lib.error()})')
    _run['coll'] = setup_scene()
    write_status()
    if bpy.app.background:
        while step():
            pass
        finish()
    else:
        bpy.app.timers.register(timer_step, first_interval=0.5)


try:
    main()
except Exception:  # noqa: BLE001
    traceback.print_exc()
    state['state'] = 'failed'
    write_status()
    if not bpy.app.background:
        bpy.ops.wm.quit_blender()
