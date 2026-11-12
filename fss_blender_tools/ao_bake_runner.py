"""AO Bake: the script of the second Blender that bakes the masters (auto-bake journal, decisions 12, 15, 16 and 27).

Started by ao_bake_store.start_bake on the saved .blend:
    blender --factory-startup [-b] <file.blend> --python ao_bake_runner.py -- <job.json>
With a window (the default) it bakes one master per timer step, so the window keeps updating, and shows each master in
an Image Editor; with -b (tests only) it bakes them one after another. It loads ao_bake_core.py by its path (the
add-on is not enabled in this Blender), prints one line per object, writes status.json after each object and stops
after the current object when a file `cancel` appears in the bake folder. It never saves the .blend and quits without
saving when done.

Per master (P35, decision 15; the prototype's step3_master.py): the target's evaluated triangles without the faces of
skip materials, in world space moved so the target's bounds are centred at the origin; the occluders the job lists
(evaluated, skip faces dropped, moved the same way); every other object hidden from rendering. The master layout at
4 x the target's median density, the core and the skirt baked Selected to Active from the target, composed, and saved
as <stem>.ao.png and <stem>.ao.npz; index.json gets the master's entry.
"""
import importlib.util
import json
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


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


state = dict(state='running', n_done=0, n_total=len(ITEMS), current='', started=time.time(), elapsed_s=0.0,
             left_s=None, results=[], pid=os.getpid(), job=os.path.basename(JOB_PATH))


def write_status():
    state['elapsed_s'] = round(time.time() - state['started'], 2)
    done = state['n_done']
    if done:
        state['left_s'] = round(state['elapsed_s'] / done * (state['n_total'] - done), 1)
    tmp = STATUS + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=1)
    os.replace(tmp, STATUS)


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
    os.replace(tmp, path)


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
    px = np.full(int(w) * int(h) * 4, -1.0, dtype=np.float32)
    px[3::4] = 1.0
    img.pixels.foreach_set(px)
    return img


def image_to_array(img):
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    return px.reshape(h, w, 4)[:, :, 0].astype(np.float64)


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
# One master
# ---------------------------------------------------------------------------------------------------------------------

_shown = {}


def show_master(image):
    """The master in the window's Image Editor (the largest area turned into one if there is none)."""
    if bpy.app.background:
        return
    H, W = image.shape
    old = _shown.get('img')
    if old is not None and old.name in bpy.data.images:
        bpy.data.images.remove(old)
    img = bpy.data.images.new('AO master', W, H, alpha=False, float_buffer=True, is_data=True)
    px = np.ones((H, W, 4), dtype=np.float32)
    px[:, :, :3] = image[:, :, None]
    img.pixels.foreach_set(px.ravel())
    _shown['img'] = img
    wm = bpy.context.window_manager
    for window in wm.windows:
        areas = sorted(window.screen.areas, key=lambda a: -a.width * a.height)
        area = next((a for a in areas if a.type == 'IMAGE_EDITOR'), None)
        if area is None and areas:
            area = areas[0]
            area.type = 'IMAGE_EDITOR'
        if area is not None:
            area.spaces.active.image = img
            area.tag_redraw()


def bake_item(item, coll):
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
    skip = set(item['skip_slots'])
    sel = np.array([m not in skip for m in ev['mat'].tolist()], dtype=bool)
    tri_src = np.nonzero(sel)[0]
    if not len(tri_src):
        return dict(status='skipped', reason='no face to bake (skip materials only)')
    pos_w, _ = core.to_world(ev)
    used = np.unique(ev['tris'][tri_src])
    lo, hi = pos_w[used].min(axis=0), pos_w[used].max(axis=0)
    shift = (lo + hi) / 2
    pos, cn = core.to_world(ev, shift)
    tris = ev['tris'][tri_src]
    cnm = cn[tri_src]
    sizes = item['tex_size']
    size = np.array([float(sizes.get(str(int(m)), sizes.get('default', 4096))) for m in ev['mat'][tri_src]])
    uvpx = ev['uv'][uv_name][tri_src] * size[:, None, None]
    D = core.master_density(pos, tris, uvpx)
    if D <= 0:
        return dict(status='skipped', reason='no face with UV area')
    tb = time.time()
    m = core.build_master(pos, tris, cnm, D, gutter=core.GUTTER, order=core.ORDER, mirror_open=core.MIRROR_OPEN,
                          fold_split=core.FOLD_SPLIT)
    t_build = time.time() - tb
    W, H = m['W'], m['H']
    scale = np.array([W, H], dtype=np.float64)
    # the target (selected) and the occluders, moved by -shift; every original object is hidden from rendering
    temps = []
    distinct = np.array([len(set(r)) == 3 for r in tris.tolist()])
    tme = build_mesh('FSS_AO_TARGET', pos, tris[distinct], cnm[distinct])
    tme.materials.clear()
    target = temp_object(coll, 'FSS_AO_TARGET', tme)
    temps.append(target)
    for occ in item['occluders']:
        o = bpy.data.objects.get(occ['name'])
        if o is None or o.type != 'MESH' or o == obj:
            continue
        temps.append(temp_object(coll, 'FSS_AO_OCC', occluder_mesh(o, dg, set(occ['skip_slots']), shift)))
    core_tris = m['core_tris']
    core_me = build_mesh('FSS_AO_CORE', pos[tris[core_tris]].reshape(-1, 3),
                         np.arange(len(core_tris) * 3).reshape(-1, 3), cnm[core_tris], m['muv'][core_tris] / scale)
    core_obj = temp_object(coll, 'FSS_AO_CORE', core_me)
    set_ray_invisible(core_obj)
    temps.append(core_obj)
    img = new_float_image('FSS_AO_CORE', W, H)
    t_core = bake(core_obj, img, core.SEEDS[0], target)
    A = image_to_array(img)
    bpy.data.images.remove(img)
    B = np.full((H, W), -1.0)
    t_skirt = 0.0
    ns = len(m['skirt_pos'])
    if ns:
        sk_me = build_mesh('FSS_AO_SKIRT', m['skirt_pos'].reshape(-1, 3), np.arange(ns * 3).reshape(-1, 3),
                           m['skirt_n'], m['skirt_uv'] / scale)
        sk_obj = temp_object(coll, 'FSS_AO_SKIRT', sk_me)
        set_ray_invisible(sk_obj)
        temps.append(sk_obj)
        img = new_float_image('FSS_AO_SKIRT', W, H)
        t_skirt = bake(sk_obj, img, core.SEEDS[1], target)
        B = image_to_array(img)
        bpy.data.images.remove(img)
    for o in temps:
        me = o.data
        bpy.data.objects.remove(o)
        bpy.data.meshes.remove(me)
    image, filled, face_map, _rect_id, counts = core.compose_master(m, A, B)
    meta = dict(schema=core.SCHEMA, key=item['key'], kind=item['kind'], name=item['name'], object=obj.name,
                mesh_hash=mh, ao_distance=SET['ao_distance'], samples=SET['samples'], **core.method_settings())
    core.save_master(FOLDER, item['key'], image, m, filled, face_map, tri_src, meta)
    show_master(image)
    entry = dict(key=item['key'], kind=item['kind'], name=item['name'], object=obj.name, mesh=obj.data.name,
                 mesh_hash=mh, mesh_hash_at_job=item.get('mesh_hash'), surround_hash=item['surround_hash'],
                 density=float(D), W=int(W), H=int(H), tris=int(len(tri_src)), islands=int(m['n_islands']),
                 samples=int(SET['samples']), ao_distance=float(SET['ao_distance']), method=core.METHOD,
                 uv=uv_name, occluders=[o['name'] for o in item['occluders']], mover=bool(item.get('mover')),
                 frame=item.get('frame'), baked_at=time.strftime('%Y-%m-%d %H:%M:%S'),
                 times=dict(build_s=round(t_build, 3), core_s=round(t_core, 3), skirt_s=round(t_skirt, 3),
                            bake_s=round(t_core + t_skirt, 3), total_s=round(time.time() - t0, 3)),
                 compose=counts)
    update_index(entry)
    return dict(status='baked', W=int(W), H=int(H), bake_s=round(t_core + t_skirt, 3),
                total_s=round(time.time() - t0, 3), mesh_changed_since_job=bool(item.get('mesh_hash') and
                                                                                 item['mesh_hash'] != mh))


_run = dict(i=0, coll=None)


def step():
    """Bakes the next master; returns False when the run is over."""
    i = _run['i']
    if i >= len(ITEMS) or os.path.exists(CANCEL):
        return False
    item = ITEMS[i]
    state['current'] = item['name']
    write_status()
    t = time.time()
    try:
        res = bake_item(item, _run['coll'])
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        res = dict(status='failed', reason=f'{type(exc).__name__}: {exc}')
    res.update(key=item['key'], name=item['name'], seconds=round(time.time() - t, 2))
    state['results'].append(res)
    state['n_done'] = i + 1
    _run['i'] = i + 1
    log(f"{i + 1}/{len(ITEMS)} {item['name']}: {res['status']}"
        + (f" {res.get('W')}x{res.get('H')} px, bake {res.get('bake_s')} s" if res['status'] == 'baked' else '')
        + (f" ({res['reason']})" if res.get('reason') else '') + f", {res['seconds']} s")
    write_status()
    delay = float(JOB.get('test_delay_s') or 0)
    if delay:
        time.sleep(delay)
    return _run['i'] < len(ITEMS)


def finish():
    cancelled = os.path.exists(CANCEL) and state['n_done'] < state['n_total']
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
    log(f"AO bake of {len(ITEMS)} masters from {JOB['blend']}: distance {SET['ao_distance']} m, samples "
        f"{SET['samples']}, device {SET['device']}, threads {SET['threads']}")
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
