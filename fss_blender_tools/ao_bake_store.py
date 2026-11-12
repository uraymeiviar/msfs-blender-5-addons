"""AO Bake: the masters outside the .blend, their staleness, and the bake in a second Blender (auto-bake journal,
decisions 12 to 18, 21 and 27; P32 to P35).

- Storage (decisions 13, 18, 21): `<blend_name>.bake/` beside the .blend holds index.json (schema, settings, each
  master's keys) and per master `<stem>.ao.png` (16-bit grey) and `<stem>.ao.npz` (the layout). A master belongs to an
  object, or to a mesh that several objects share (self-shading only, P35). Its stem is the name made safe for the file
  system plus a short hash of the name (ao_bake_core.safe_stem).
- Staleness (decision 17, P33): mesh changed when the hash of the evaluated triangles, positions and corner normals
  differs; surroundings changed when the hash of the object's world matrix, each occluder within the AO distance of its
  bounds (name, world matrix, geometry hash, tags) and the settings differs. A master missing for an object whose
  geometry hash matches exactly one orphaned master (its object or mesh gone) is linked to it again (a rename).
- Rules (P35, decision 15): baked are the visible LOD0 mesh objects with faces and a UV map, without the Skip-AO-Bake,
  No Texture, Invisible or No Export tags, and only their faces of a texture set: a material that is not a skip
  material (uv_autoseam._is_skip_material); an object without such faces is excluded (decision 30).
  Occluders are the visible LOD0 meshes without the Non-AO-Occluder, Invisible or No Export tags, without their skip
  faces, and not movers (animated, or under an animated parent, or tagged Animated): movers cast no AO onto other
  objects and are baked in the current frame's pose. A shared mesh gets its self-shading only.
- The bake (decision 12, P34) runs in a second Blender on the saved file (ao_bake_runner.py); this module writes the
  job, starts it, reads its status.json and creates the `cancel` file.
The hashes are computed by refresh(), never while a panel draws.
"""

import json
import os
import subprocess
import time
from pathlib import Path

import bpy
import numpy as np

from . import ao_bake_core as core
from . import lod_model, tags

RUNNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ao_bake_runner.py')
GRADES = ('UP_TO_DATE', 'SURROUNDINGS', 'MESH', 'MISSING')
GRADE_TEXT = {'UP_TO_DATE': 'up to date', 'SURROUNDINGS': 'surroundings changed', 'MESH': 'mesh changed',
              'MISSING': 'missing'}

# the last refresh (computed by refresh(), read by the panel and Apply)
_state = dict(items={}, by_object={}, excluded={}, sets={}, refreshed=None, folder=None)
_index_cache = {}
_run = dict(proc=None, folder=None, job=None, started=None, log=None)


# ---------------------------------------------------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------------------------------------------------

def bake_folder(blend_path=None):
    """`<blend_name>.bake` beside the .blend, or None for an unsaved file."""
    blend_path = blend_path if blend_path is not None else bpy.data.filepath
    if not blend_path:
        return None
    p = Path(blend_path)
    return str(p.with_name(p.stem + '.bake'))


def read_index(folder, use_cache=True):
    """index.json of a bake folder ({'schema', 'settings', 'masters': {stem: entry}}), cached by modification time."""
    empty = dict(schema=core.SCHEMA, settings={}, masters={})
    if not folder:
        return empty
    path = os.path.join(folder, 'index.json')
    try:
        mtime = os.stat(path).st_mtime_ns
    except OSError:
        return empty
    cached = _index_cache.get(path)
    if use_cache and cached is not None and cached[0] == mtime:
        return cached[1]
    try:
        with open(path, encoding='utf-8') as f:
            index = json.load(f)
    except (OSError, ValueError):
        return empty
    index.setdefault('masters', {})
    _index_cache[path] = (mtime, index)
    return index


def write_index(folder, index):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, 'index.json')
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(index, f, indent=1)
    os.replace(tmp, path)
    _index_cache.pop(path, None)


def master_files(folder, stem):
    return os.path.join(folder, stem + '.ao.png'), os.path.join(folder, stem + '.ao.npz')


def has_files(folder, stem):
    return all(os.path.isfile(p) for p in master_files(folder, stem))


# ---------------------------------------------------------------------------------------------------------------------
# Rules (P35)
# ---------------------------------------------------------------------------------------------------------------------

def is_skip_material(material):
    from .uv_autoseam import _is_skip_material
    return _is_skip_material(material)


def skip_slots(obj):
    return [i for i, slot in enumerate(obj.material_slots) if is_skip_material(slot.material)]


def all_skip(obj):
    slots = obj.material_slots
    return bool(len(slots)) and all(is_skip_material(slot.material) for slot in slots)


def in_lod0(obj):
    """In LOD0: no Visible-from mark above LOD0 on the object or a parent (Object LOD's marks)."""
    while obj is not None:
        if lod_model.mark(obj, lod_model.SHOW_KEY) > 0:
            return False
        obj = obj.parent
    return True


def _has_animation(idb):
    ad = getattr(idb, 'animation_data', None)
    if ad is None:
        return False
    return bool(ad.action) or any(len(t.strips) for t in ad.nla_tracks) or bool(len(ad.drivers))


def is_mover(obj, scene):
    """Animated (an action, NLA strip or driver on the object or a parent) or tagged Animated."""
    if tags.is_marked_animated(obj, scene):
        return True
    o = obj
    while o is not None:
        if _has_animation(o):
            return True
        o = o.parent
    return False


def _visible_meshes(view_layer):
    return [o for o in view_layer.objects if o.type == 'MESH' and o.data is not None and len(o.data.polygons)
            and o.visible_get(view_layer=view_layer) and not o.hide_render and in_lod0(o)]


def bake_exclusion(obj, scene):
    """Why a visible LOD0 mesh gets no master, or ''."""
    if not tags.is_ao_baked(obj, scene):
        return 'Skip-AO-Bake or No Texture tag'
    if tags.is_marked_invisible(obj, scene):
        return 'Invisible tag'
    if tags.is_no_export(obj, scene):
        return 'No Export tag'
    if obj.data.uv_layers.active is None:
        return 'no UV map'
    if all_skip(obj):
        return 'skip materials only'
    return ''


def is_occluder(obj, scene):
    return (tags.is_ao_occluder(obj, scene) and not tags.is_marked_invisible(obj, scene)
            and not tags.is_no_export(obj, scene) and not all_skip(obj) and not is_mover(obj, scene))


def texture_size(material):
    from .uv_marks import texture_size as size_of
    return size_of(material)


def _world_box(obj):
    M = np.array(obj.matrix_world, dtype=np.float64)
    c = np.array([tuple(v) for v in obj.bound_box], dtype=np.float64) @ M[:3, :3].T + M[:3, 3]
    return c.min(axis=0), c.max(axis=0)


def settings_dict(scene):
    s = scene.fss_ao_bake
    return dict(ao_distance=round(float(s.distance), 6), samples=int(s.samples), device=s.device,
                threads=int(s.threads))


def _surround_settings(scene):
    s = settings_dict(scene)
    return dict(ao_distance=s['ao_distance'], **core.method_settings())


def _hash(obj):
    import hashlib
    return hashlib.sha1(json.dumps(obj, sort_keys=True).encode('utf-8')).hexdigest()[:20]


# ---------------------------------------------------------------------------------------------------------------------
# Refresh: the items to bake, their hashes and grades
# ---------------------------------------------------------------------------------------------------------------------

def refresh(context, relink=True):
    """Computes every master's keys and grade against index.json; links renamed masters again. Returns _state."""
    scene = context.scene
    view_layer = context.view_layer
    depsgraph = context.evaluated_depsgraph_get()
    folder = bake_folder()
    index = read_index(folder, use_cache=False) if folder else dict(masters={})
    meshes = _visible_meshes(view_layer)
    excluded = {}
    baked = []
    for obj in meshes:
        why = bake_exclusion(obj, scene)
        if why:
            excluded[obj.name] = why
        else:
            baked.append(obj)
    occluders = [o for o in meshes if is_occluder(o, scene)]
    boxes = {o.name: _world_box(o) for o in set(baked) | set(occluders)}
    geo = {}
    evs = {}

    def ev_of(obj, uv_names=()):
        if obj.name not in evs or (uv_names and not set(uv_names) <= set(evs[obj.name]['uv'])):
            evs[obj.name] = core.evaluated_triangles(obj, depsgraph, uv_names)
        return evs[obj.name]

    def geo_hash(obj):
        if obj.name not in geo:
            geo[obj.name] = core.mesh_hash(ev_of(obj))
        return geo[obj.name]

    users = {}
    for obj in baked:
        users.setdefault(obj.data, []).append(obj)
    distance = float(scene.fss_ao_bake.distance)
    base = _surround_settings(scene)
    frame = scene.frame_current
    items = {}
    by_object = {}
    for me, objs in sorted(users.items(), key=lambda kv: kv[0].name):
        objs = sorted(objs, key=lambda o: o.name)
        shared = len(objs) > 1
        first = objs[0]
        kind, name = ('mesh', me.name) if shared else ('object', first.name)
        stem = core.safe_stem(kind, name)
        uv = me.uv_layers.active.name
        ev = ev_of(first, [uv])
        slots = [slot.material for slot in first.material_slots]
        skip = skip_slots(first)
        mats = sorted(set(int(m) for m in np.unique(ev['mat']).tolist()))
        # decision 30: only faces whose material is a texture set (a material, not a skip material) are baked
        set_mats = [m for m in mats if m < len(slots) and slots[m] is not None and m not in skip]
        if not set_mats:
            for o in objs:
                excluded[o.name] = 'no face with a texture set (material)'
            continue
        mh = geo_hash(first)
        mover = is_mover(first, scene)
        if shared:
            occ = []
            scale = [round(float(v), 6) for v in first.matrix_world.to_scale()]
            sur = _hash(dict(base, shared=True, scale=scale))
        else:
            box = boxes[first.name]
            occ = sorted(o.name for o in occluders if o != first and core.box_gap(box, boxes[o.name]) <= distance)
            sur = _hash(dict(base, matrix=core.matrix_key(first.matrix_world), mover=mover,
                             frame=frame if mover else None,
                             occluders=[(n, core.matrix_key(bpy.data.objects[n].matrix_world),
                                         geo_hash(bpy.data.objects[n]), sorted(tags.get_tags(bpy.data.objects[n])))
                                        for n in occ]))
        sets = sorted({slots[m].name for m in set_mats})
        tex = {str(m): int(texture_size(slots[m])) for m in set_mats}  # faces of other indices are not baked
        item = dict(key=stem, kind=kind, name=name, object=first.name, mesh=me.name, users=[o.name for o in objs],
                    uv=uv, mesh_hash=mh, surround_hash=sur, occluders=occ, mover=mover, frame=frame,
                    skip_slots=skip, tex_size=tex, sets=sets, grade='MISSING')
        items[stem] = item
        for o in objs:
            by_object[o.name] = stem
    masters = index.get('masters', {})
    relinked = []
    if relink and folder:
        orphans = {k: e for k, e in masters.items() if k not in items}
        for stem, item in items.items():
            if stem in masters:
                continue
            match = [k for k, e in orphans.items() if e.get('mesh_hash') == item['mesh_hash']
                     and e.get('kind') == item['kind']]
            if len(match) != 1:
                continue
            old = match[0]
            entry = orphans.pop(old)
            for src, dst in zip(master_files(folder, old), master_files(folder, stem)):
                if os.path.isfile(src):
                    os.replace(src, dst)
            entry.update(key=stem, name=item['name'], object=item['object'], mesh=item['mesh'],
                         relinked_from=entry.get('name'))
            del masters[old]
            masters[stem] = entry
            relinked.append((entry['relinked_from'], item['name']))
        if relinked:
            write_index(folder, index)
    for stem, item in items.items():
        item['grade'] = grade(item, masters.get(stem), folder)
    _state.update(items=items, by_object=by_object, excluded=excluded, refreshed=time.time(), folder=folder,
                  relinked=relinked, sets=texture_set_rows(items, masters))
    return _state


def grade(item, entry, folder):
    if entry is None or not folder or not has_files(folder, item['key']):
        return 'MISSING'
    if entry.get('mesh_hash') != item['mesh_hash']:
        return 'MESH'
    if entry.get('surround_hash') != item['surround_hash']:
        return 'SURROUNDINGS'
    return 'UP_TO_DATE'


def regrade():
    """After a bake: the grades again from index.json, with the hashes of the last refresh."""
    folder = _state.get('folder')
    masters = read_index(folder, use_cache=False).get('masters', {}) if folder else {}
    for stem, item in _state['items'].items():
        item['grade'] = grade(item, masters.get(stem), folder)
    _state['sets'] = texture_set_rows(_state['items'], masters)


def texture_set_rows(items, masters):
    """{material name: dict(items, MISSING, MESH, SURROUNDINGS, UP_TO_DATE)} over the baked items' faces."""
    rows = {}
    for stem, item in items.items():
        for name in item['sets']:
            row = rows.setdefault(name, dict(items=[], MISSING=0, MESH=0, SURROUNDINGS=0, UP_TO_DATE=0))
            row['items'].append(stem)
            row[item['grade']] += 1
    return rows


def counts():
    c = {g: 0 for g in GRADES}
    for item in _state['items'].values():
        c[item['grade']] += 1
    c['EXCLUDED'] = len(_state['excluded'])
    return c


def items_for_objects(objects):
    """The item stems of these objects (a shared mesh once)."""
    out = []
    for obj in objects:
        stem = _state['by_object'].get(obj.name)
        if stem and stem not in out:
            out.append(stem)
    return out


# ---------------------------------------------------------------------------------------------------------------------
# The bake in a second Blender
# ---------------------------------------------------------------------------------------------------------------------

def make_job(context, stems, test_delay_s=0.0, tile_px=0, test_tile_delay_s=0.0):
    scene = context.scene
    folder = bake_folder()
    os.makedirs(folder, exist_ok=True)
    items = []
    for stem in stems:
        item = _state['items'][stem]
        occ = [dict(name=n, skip_slots=skip_slots(bpy.data.objects[n])) for n in item['occluders']]
        items.append(dict(key=stem, kind=item['kind'], name=item['name'], object=item['object'], uv=item['uv'],
                          skip_slots=item['skip_slots'], tex_size=item['tex_size'], occluders=occ,
                          surround_hash=item['surround_hash'], mesh_hash=item['mesh_hash'], mover=item['mover'],
                          frame=item['frame']))
    job = dict(schema=core.SCHEMA, blend=bpy.data.filepath, folder=folder, settings=settings_dict(scene),
               items=items, created=time.strftime('%Y-%m-%d %H:%M:%S'), test_delay_s=float(test_delay_s),
               tile_px=int(tile_px), test_tile_delay_s=float(test_tile_delay_s))
    path = os.path.join(folder, 'job.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(job, f, indent=1)
    return path


def start_bake(job_path, hidden=False):
    """Starts the second Blender on the saved file (with its window unless hidden). Returns the process."""
    folder = os.path.dirname(job_path)
    for name in ('status.json', 'cancel'):
        try:
            os.remove(os.path.join(folder, name))
        except OSError:
            pass
    args = [bpy.app.binary_path, '--factory-startup']
    if hidden:
        args.append('-b')
    args += [bpy.data.filepath, '--python', RUNNER, '--', job_path]
    kw = {}
    if hidden:
        log = open(os.path.join(folder, 'runner.log'), 'w', encoding='utf-8')
        kw.update(stdout=log, stderr=subprocess.STDOUT)
        _run['log'] = log
    elif os.name == 'nt':
        kw['creationflags'] = subprocess.CREATE_NEW_CONSOLE
    proc = subprocess.Popen(args, cwd=folder, **kw)
    _run.update(proc=proc, folder=folder, job=job_path, started=time.time())
    return proc


def read_status(folder=None):
    folder = folder or _run.get('folder')
    if not folder:
        return None
    try:
        with open(os.path.join(folder, 'status.json'), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def running():
    proc = _run.get('proc')
    return proc is not None and proc.poll() is None


def cancel():
    folder = _run.get('folder')
    if folder:
        with open(os.path.join(folder, 'cancel'), 'w', encoding='utf-8') as f:
            f.write('cancel\n')


def finish_run():
    """After the second Blender ended: close its log, read index.json again and grade."""
    log = _run.get('log')
    if log is not None:
        log.close()
        _run['log'] = None
    _run['proc'] = None
    regrade()
    return read_status()
