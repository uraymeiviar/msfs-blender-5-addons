"""AO Bake: the masters outside the .blend, their staleness, and the bake in a second Blender (auto-bake journal,
decisions 12 to 18, 21 and 27; P32 to P35).

- Storage (decisions 13, 18, 21): `<blend_name>.bake/` beside the .blend holds index.json (schema, settings, each
  master's keys) and per master `<stem>.ao.jxl` (16-bit grey, lossless JPEG XL, decision 37; a `<stem>.ao.png` of
  0.55, or one baked without the JPEG XL library, counts as missing: apply-native-copy decision 6), `<stem>.ao.map`
  (filled pixels and the face map, written row by row; Session 23) and `<stem>.ao.npz` (the layout). A master belongs to an
  object, or to a mesh that several objects share (self-shading only, P35). Its stem is the name made safe for the file
  system plus a short hash of the name (ao_bake_core.safe_stem).
- Staleness (decision 17, P33): mesh changed when the hash of the evaluated triangles, positions and corner normals
  differs; surroundings changed when the hash of the object's world matrix, each occluder within the AO distance of its
  bounds (name, world matrix, geometry hash, tags) and the settings differs. A master missing for an object whose
  geometry hash matches exactly one orphaned master (its object or mesh gone) is linked to it again (a rename).
- Rules (P35, decision 15; decision 112: the tags alone, no rule of material classes): baked are the visible LOD0
  mesh objects with faces and a UV map, without the Skip-AO-Bake, No Texture, Invisible or No Export tags, and their
  faces with a material (a texture set); an object without such faces is excluded (decision 30). An object with the
  Skip-AO-Bake tag alone gets a master of the material channels only (decision 110). Occluders are the visible LOD0
  meshes without the Non-AO-Occluder, Invisible or No Export tags, all their faces. Before decision 112 decal, glass,
  windshield, invisible and occluder materials (uv_autoseam._is_skip_material) were neither baked nor occluders
  (MATERIAL_RULE, kept for the tests' recorded references). Moving ones too (decision 59): Refresh steps through the frames of the file's animation once (motion()) and
  compares every object's placement; an occluder rigid to the object (both static, or moving together) shades it as
  placed; one that moves against it (or the object against it) is placed at each of the object's poses, spread over
  their animation, and averaged (one pose: the current frame). Near means within the AO distance (decisions 15 and
  64 and 65): the world boxes' gap first, then the gap of the objects' own boxes as placed (rotated with the
  object): at the current frame for one pose, else at each sampled frame, near when near at any of them. A mover whose motion cannot be sampled (a driver only,
  or the Animated tag without keys that move it) casts no AO, as before. A shared mesh gets its self-shading only.
- Options (decisions 34 and 35; a scene default and a per-object override, `fss_ao_bake` on the object): an object
  with something moving against it is baked in N poses spread over that motion's frames and averaged (N = 1: the
  current frame, decision 59); the occluders are the
  scene rule, the object alone (Self only) or Custom: the scene rule when its Scene as occluder is on, else none,
  minus the list's ignored objects, plus its added ones (decision 60; posed with the target). Changing one makes the
  master "surroundings changed"; at one pose and the scene rule the hashes are those of 0.57.
- The bake (decisions 12 and 36, P34) runs in a second Blender (ao_bake_runner.py), hidden or with its window, on a
  snapshot of the current state (a copy of the open file written into the bake folder, unsaved changes included, the
  .blend untouched; removed after the bake); this module writes the snapshot and the job, starts it, reads its
  status.json and creates the `cancel` file.
- Material channels (decisions 79 to 81): the entry's `channels` ({group: mesh_hash, baked_at, samples, object,
  skipped}); a channel's grade is UP_TO_DATE, MESH (baked for another mesh) or MISSING, never stale from the material
  or the surroundings; a bake bakes only the chosen channels (Missing and Stale: those not up to date).
The hashes are computed by refresh(), never while a panel draws.
"""

import hashlib
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
# decision 55: a master's curvature: up to date, baked at another width, missing, or waiting for an AO bake (no AO
# master or its mesh changed: the curvature is written in the AO master's layout)
CURV_GRADES = ('UP_TO_DATE', 'WIDTH', 'MISSING', 'NEEDS_AO')
# decision 56: a master's denoise against the panel's: as set, to re-run (from the raw bake kept beside it), or waiting
# for an AO bake (no master, its mesh changed, or its raw bake is gone)
DN_GRADES = ('UP_TO_DATE', 'STALE', 'NEEDS_AO')
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
    """(image, npz) of a master: its .ao.jxl, or its .ao.png when only that exists (0.55, or baked without the JPEG XL
    library; not read any more, decision 6); its third file, <stem>.ao.map (schema 2), is in core.master_paths."""
    image, _mp, npz = core.master_paths(folder, stem)
    return image, npz


def has_files(folder, stem):
    """The master's files are there and the C++ code reads them: the image (.ao.jxl), the .npz and the .ao.map. A
    master it does not read (an .ao.png, schema 1 with its per-pixel data in the .npz; apply-native-copy decision 6,
    core.master_unreadable) counts as missing: Refresh grades it to be baked again."""
    image, mp, npz = core.master_paths(folder, stem)
    if not (os.path.isfile(image) and os.path.isfile(npz) and os.path.isfile(mp)):
        return False
    return core.master_unreadable(folder, stem) is None


# ---------------------------------------------------------------------------------------------------------------------
# Rules (P35)
# ---------------------------------------------------------------------------------------------------------------------

# Decision 112: the bake reads the tags alone. True: the rule before it, by material class (decal, glass, windshield,
# invisible and occluder materials neither baked nor occluding), for the tests whose references were recorded with it
MATERIAL_RULE = False


def is_skip_material(material):
    from .uv_autoseam import _is_skip_material
    return _is_skip_material(material)


def material_skip_slots(obj):
    """The slots of the material rule before decision 112 (its skip materials), whatever rule is in force."""
    return [i for i, slot in enumerate(obj.material_slots) if is_skip_material(slot.material)]


def skip_slots(obj):
    """The slots whose faces are neither baked nor occluding: none since decision 112."""
    return material_skip_slots(obj) if MATERIAL_RULE else []


def all_skip(obj):
    """An object of skip materials only, under the material rule (MATERIAL_RULE); never since decision 112."""
    slots = obj.material_slots
    return MATERIAL_RULE and bool(len(slots)) and all(is_skip_material(slot.material) for slot in slots)


# decision 110: the skip classes that never carry a material channel (no texture of their own)
NO_CHANNEL_CLASSES = ('INVIS', 'OCCLUDER')
NO_CHANNEL_TYPES = ('msfs_invisible', 'msfs_environment_occluder')


def is_channel_material(material):
    """Decision 110: a skip material whose faces take the material channels (albedo, roughness, metal, emissive):
    glass, windshield and decals; not invisible or occluder materials."""
    if material is None or not is_skip_material(material):
        return False
    import re
    base = re.sub(r'\.\d+$', '', material.name.upper())
    if any(base == c or base.endswith('_' + c) for c in NO_CHANNEL_CLASSES):
        return False
    mtype = getattr(material, 'msfs_material_type', None)
    if (mtype is None or mtype == 'NONE') and 'msfs_material_type' in material:
        mtype = material['msfs_material_type']
    return mtype not in NO_CHANNEL_TYPES


def channels_only(obj, why):
    """Decision 110: a master of the material channels alone (no AO, no curvature) for an object with this exclusion
    (bake_exclusion): decision 112, the Skip-AO-Bake tag alone; under the material rule, an object of skip materials
    only, with at least one that takes the material channels."""
    if MATERIAL_RULE:
        return why == SKIP_ONLY and any(is_channel_material(slot.material) for slot in obj.material_slots)
    return why == SKIP_AO


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


def _anim_range(idb):
    """(start, end) frames of the action and the unmuted NLA strips of one ID, or None."""
    ad = getattr(idb, 'animation_data', None)
    if ad is None:
        return None
    lo, hi = float('inf'), float('-inf')
    act = ad.action
    if act is not None and not getattr(act, 'is_empty', False):
        r = act.frame_range
        lo, hi = min(lo, float(r[0])), max(hi, float(r[1]))
    for track in ad.nla_tracks:
        if track.mute:
            continue
        for strip in track.strips:
            if not strip.mute:
                lo, hi = min(lo, float(strip.frame_start)), max(hi, float(strip.frame_end))
    return (lo, hi) if lo <= hi else None


def mover_range(obj):
    """Decision 34: the frame range of a mover's own animation, from the actions and NLA strips of the object and its
    animated parents; None when there is none (a driver only, or the Animated tag without keys)."""
    lo, hi = float('inf'), float('-inf')
    o = obj
    while o is not None:
        r = _anim_range(o)
        if r is not None:
            lo, hi = min(lo, r[0]), max(hi, r[1])
        o = o.parent
    return (lo, hi) if lo <= hi else None


def _fcurves_of(act, slot):
    """The F-curves of an action for a slot (its channel bag in a layered action)."""
    if act is None:
        return []
    try:
        from bpy_extras import anim_utils
        bag = anim_utils.action_get_channelbag_for_slot(act, slot)
        return list(bag.fcurves) if bag is not None else []
    except (ImportError, AttributeError):
        return list(getattr(act, 'fcurves', ()))


def _fcurves(ad):
    """The F-curves of an animation data's action."""
    return _fcurves_of(getattr(ad, 'action', None), getattr(ad, 'action_slot', None))


def _channels(obj, frame):
    """[(F-curve, the frame to evaluate it at)] of the object's own animation at a scene frame: its action, or its one
    unmuted NLA strip (time mapped: start, scale, repeat; held outside the strip); [] without animation; None when it
    cannot be read this way (an action and strips together, several strips)."""
    ad = obj.animation_data
    if ad is None:
        return []
    strips = [s for t in ad.nla_tracks if not t.mute for s in t.strips if not s.mute]
    if not strips:
        return [(fc, frame) for fc in _fcurves(ad)]
    if ad.action is not None or len(strips) != 1:
        return None
    s = strips[0]
    a0, a1 = float(s.action_frame_start), float(s.action_frame_end)
    if frame <= s.frame_start:
        af = a0
    elif frame >= s.frame_end:
        af = a1
    else:
        local = (frame - s.frame_start) / (s.scale or 1.0)
        af = a0 + (local % (a1 - a0) if s.repeat > 1 and a1 > a0 else local)
    return [(fc, af) for fc in _fcurves_of(s.action, getattr(s, 'action_slot', None))]


def _basis_at(obj, frame, channels=None):
    """The object's own transform (matrix_basis) at a frame, from its animation's F-curves over its current values."""
    from mathutils import Euler, Matrix, Quaternion, Vector
    loc, scale = Vector(obj.location), Vector(obj.scale)
    mode = obj.rotation_mode
    eul = Euler(obj.rotation_euler, mode if mode not in ('QUATERNION', 'AXIS_ANGLE') else 'XYZ')
    quat, aa = Quaternion(obj.rotation_quaternion), list(obj.rotation_axis_angle)
    if channels is None:
        channels = _channels(obj, frame) or []
    for fc, f in channels:
        p, i, v = fc.data_path, fc.array_index, fc.evaluate(f)
        if p == 'location':
            loc[i] = v
        elif p == 'scale':
            scale[i] = v
        elif p == 'rotation_euler':
            eul[i] = v
        elif p == 'rotation_quaternion':
            quat[i] = v
        elif p == 'rotation_axis_angle':
            aa[i] = v
    if mode == 'QUATERNION':
        rot = quat.normalized()
    elif mode == 'AXIS_ANGLE':
        rot = Quaternion(Vector(aa[1:]), aa[0])
    else:
        rot = eul.to_quaternion()
    return Matrix.LocRotScale(loc, rot, scale)


def ends_coincide(obj, lo, hi, tol=1e-5):
    """P59 (decision 41): the mover is in the same pose at both ends of its range (a full turn): the transforms of the
    object and of every animated parent equal at lo and hi. Read from an action or one NLA strip per object; anything
    else (both, several strips) is taken as not coinciding."""
    o, seen = obj, False
    while o is not None:
        c_lo, c_hi = _channels(o, lo), _channels(o, hi)
        if c_lo is None or c_hi is None:
            return False
        if c_lo:
            a, b = _basis_at(o, lo, c_lo), _basis_at(o, hi, c_hi)
            if max(abs(a[r][c] - b[r][c]) for r in range(4) for c in range(4)) > tol:
                return False
            seen = True
        o = o.parent
    return seen


def pose_count(obj, scene):
    """Decision 34: the object's pose count (its override, else the scene's default)."""
    n = int(getattr(getattr(obj, 'fss_ao_bake', None), 'poses', 0) or 0)
    return n if n > 0 else int(scene.fss_ao_bake.poses)


def pose_frames(obj, scene, n=None):
    """Decision 34: (frames, note) of a mover's poses: n frames spread evenly over its animation range, both ends
    included; when both ends are the same pose (a full turn, decision 41), n frames spread over the range without its
    end, so no pose counts twice; (None, note) for the current frame only (n = 1, or no range)."""
    n = pose_count(obj, scene) if n is None else int(n)
    if n <= 1:
        return None, ''
    r = mover_range(obj)
    if r is None:
        return None, 'no animation range (a driver only, or the Animated tag without keys): baked in the current frame'
    lo, hi = r
    if hi <= lo:
        return None, f'its animation range is one frame ({lo:g}): baked in the current frame'
    if ends_coincide(obj, lo, hi):
        return [round(lo + (hi - lo) * k / n, 4) for k in range(n)], ''
    return [round(lo + (hi - lo) * k / (n - 1), 4) for k in range(n)], ''


def motion_frames(obj, scene, involved, sampled, n=None):
    """Decision 59: (frames, note, range) of the poses of an object with something moving against it: n poses (its
    count) spread evenly over the animation of the objects that move (involved: the object itself when it moves, and
    its occluders that move against it), both ends included; when every one of them is in the same pose at both ends
    (decision 41), spread without the end. A mover whose range cannot be read (a constraint, a driver) counts with
    the sampled frames' range. (None, note, range) for the current frame (n = 1, or no range)."""
    n = pose_count(obj, scene) if n is None else int(n)
    lo, hi = float('inf'), float('-inf')
    for o in involved:
        r = mover_range(o) or ((sampled[0], sampled[-1]) if sampled else None)
        if r is not None:
            lo, hi = min(lo, r[0]), max(hi, r[1])
    rng = (lo, hi) if lo <= hi else None
    if n <= 1:
        return None, '', rng
    if rng is None:
        return None, 'no animation range: baked in the current frame', rng
    if hi <= lo:
        return None, f'its animation range is one frame ({lo:g}): baked in the current frame', rng
    if all(ends_coincide(o, lo, hi) for o in involved):
        return [round(lo + (hi - lo) * k / n, 4) for k in range(n)], '', rng
    return [round(lo + (hi - lo) * k / (n - 1), 4) for k in range(n)], '', rng


def occluder_mode(obj, scene):
    """Decision 35: 'SCENE' (the scene rule, decision 15), 'SELF' (the object alone) or 'CUSTOM' (its own list): the
    object's override, else the scene's default."""
    mode = getattr(getattr(obj, 'fss_ao_bake', None), 'occluders', 'DEFAULT') or 'DEFAULT'
    return scene.fss_ao_bake.occluders if mode == 'DEFAULT' else mode


SHARED_COMBINES = ('AVERAGE', 'LIGHTEST', 'DARKEST', 'ONE')


def shared_combine(mesh, scene):
    """Decision 47: how a shared mesh's copies are combined into its one master: the mesh's override, else the
    scene's default ('AVERAGE', 'LIGHTEST' (most lit) or 'DARKEST')."""
    mode = getattr(getattr(mesh, 'fss_ao_shared', None), 'combine', 'DEFAULT') or 'DEFAULT'
    return scene.fss_ao_bake.shared_combine if mode == 'DEFAULT' else mode


def shared_instance(mesh, copies, entry=None, chosen=None):
    """Decision 77: the copy One Instance grades against and bakes, and where it came from, first that applies:
    ('bake') `chosen`, the bake's choice from the selection, when it is one of `copies`; ('entry') the master's index
    entry's `instance` when that object is still one of them; ('pointer') an entry without `instance` (a master baked
    before decision 77): the mesh's old picked copy (decision 48) when it is one of them; ('first') the first copy by
    name. Returns (object, source)."""
    by_name = {o.name: o for o in copies}
    if chosen in by_name:
        return by_name[chosen], 'bake'
    if entry is not None:
        if 'instance' in entry:
            if entry['instance'] in by_name:
                return by_name[entry['instance']], 'entry'
        else:
            picked = getattr(getattr(mesh, 'fss_ao_shared', None), 'instance', None)
            if picked is not None and picked.name in by_name:
                return picked, 'pointer'
    return by_name[min(by_name)], 'first'


def shown_names(view_layer):
    """Decision 102: the names of the objects the view layer shows, whatever a 3D view shows (its local view, local
    collections and object type filters): the object in a collection that is not excluded, nor hidden in viewports
    (the monitor) or in the view layer (the eye) itself or by a parent collection. As Blender's visible_get without a 3D
    view (the file opening's Refresh); with the object's own hide_viewport and hide_get, see shown()."""
    names = set()

    def walk(lc, hidden):  # as Blender's sync: the hiding inherited, the exclusion not (a child may be included)
        hidden = hidden or lc.collection.hide_viewport or lc.hide_viewport
        if not hidden and not lc.exclude:
            names.update(o.name for o in lc.collection.objects)
        for c in lc.children:
            walk(c, hidden)
    if view_layer.layer_collection is not None:  # None in a view layer never synced, which has no objects either
        walk(view_layer.layer_collection, False)
    return names


def shown(obj, view_layer, names=None):
    """Decision 102: is the object visible in the view layer, ignoring any 3D view's local view (shown_names)."""
    if names is None:
        names = shown_names(view_layer)
    return obj.name in names and not obj.hide_viewport and not obj.hide_get(view_layer=view_layer)


def bakeable_copy(obj, view_layer, scene, names=None):
    """Whether this object is one of the copies Refresh bakes: a visible LOD0 mesh with faces and no exclusion
    (visible: decision 102, a 3D view's local view does not count)."""
    return (obj.type == 'MESH' and obj.data is not None and len(obj.data.polygons) > 0
            and shown(obj, view_layer, names) and not obj.hide_render and in_lod0(obj)
            and not bake_exclusion(obj, scene))


def instance_choice(selected, active=None, picked=''):
    """Decision 77: the copy a bake of the selection bakes for a One Instance mesh, from the names of its selected
    copies: the drop-down's copy when it is one of them, else the active object when it is, else the first by name;
    None without a selected copy."""
    if not selected:
        return None
    if picked and picked in selected:
        return picked
    if active and active in selected:
        return active
    return min(selected)


def custom_refs(obj):
    """Decisions 60 and 63: the object's Custom list by object name: (ignore, with its children); an object listed
    twice is ignored when one of its items ignores it."""
    refs = {}
    for ref in getattr(getattr(obj, 'fss_ao_bake', None), 'custom', ()):
        o = ref.object
        if o is None:
            continue
        ignore, children = refs.get(o.name, (False, False))
        refs[o.name] = (ignore or bool(getattr(ref, 'ignore', False)),
                        children or bool(getattr(ref, 'children', False)))
    return refs


def custom_state(refs, o):
    """Decision 63: what the Custom list says about object `o`: 'ADD', 'IGNORE' or None. An item on the object
    itself decides; else the nearest parent whose item has With its children on."""
    entry = refs.get(o.name)
    if entry is not None:
        return 'IGNORE' if entry[0] else 'ADD'
    p = o.parent
    while p is not None:
        entry = refs.get(p.name)
        if entry is not None and entry[1]:
            return 'IGNORE' if entry[0] else 'ADD'
        p = p.parent
    return None


def custom_state_chain(refs, chain):
    """custom_state by names: `chain` is the object's name and its parents' names, nearest first (Session 53: the
    panel's tree draws without looking objects up by name, which scans every object)."""
    entry = refs.get(chain[0])
    if entry is not None:
        return 'IGNORE' if entry[0] else 'ADD'
    for name in chain[1:]:
        entry = refs.get(name)
        if entry is not None and entry[1]:
            return 'IGNORE' if entry[0] else 'ADD'
    return None


def custom_occluders(obj, view_layer, scene_names=()):
    """Decisions 35, 60 and 63: the occluders of a Custom object, by name, sorted: `scene_names` (the scene rule's
    occluders, given when Scene as occluder is on) minus the objects the list ignores, plus the objects it adds that
    can occlude (meshes with faces in the view layer, not the object itself). An item with With its children on
    covers the object's children at every depth; an item nearer to an object wins."""
    settings = getattr(obj, 'fss_ao_bake', None)
    if settings is None:
        return []
    refs = custom_refs(obj)
    candidates = {n: view_layer.objects.get(n) for n in refs}
    for ref in settings.custom:
        if ref.object is not None and getattr(ref, 'children', False):
            candidates.update((c.name, c) for c in ref.object.children_recursive)
    names = set(scene_names) if getattr(settings, 'custom_scene', False) else set()
    occ = set()
    for n in names | set(candidates):
        o = candidates.get(n) or view_layer.objects.get(n)
        if o is None or o == obj:
            continue
        state = custom_state(refs, o)
        if state == 'IGNORE':
            continue
        if n in names:
            occ.add(n)
        elif (state == 'ADD' and o.type == 'MESH' and o.data is not None and len(o.data.polygons)
                and n in view_layer.objects):
            occ.add(n)
    return sorted(occ)


def _visible_meshes(view_layer):
    """The visible LOD0 meshes, the bake's targets and occluders; decision 102: whatever a 3D view's local view shows,
    so a bake started there takes the same objects as the file opening's Refresh."""
    names = shown_names(view_layer)
    return [o for o in view_layer.objects if o.type == 'MESH' and o.data is not None and len(o.data.polygons)
            and shown(o, view_layer, names) and not o.hide_render and in_lod0(o)]


def bake_exclusion(obj, scene):
    """Why a visible LOD0 mesh gets no master, or ''."""
    skip_ao = False
    if not tags.is_ao_baked(obj, scene):
        if MATERIAL_RULE or tags.needs_no_texture(obj, scene):
            return 'Skip-AO-Bake or No Texture tag'
        skip_ao = True  # decision 112: the material channels alone, if nothing below excludes it
    if tags.is_marked_invisible(obj, scene):
        return 'Invisible tag'
    if tags.is_no_export(obj, scene):
        return 'No Export tag'
    if obj.data.uv_layers.active is None:
        return 'no UV map'
    if skip_ao:
        return SKIP_AO
    if all_skip(obj):
        return SKIP_ONLY
    return ''


SKIP_ONLY = 'skip materials only'  # the material rule (before decision 112)
SKIP_AO = 'Skip-AO-Bake tag'  # decision 112: a master of the material channels alone (decision 110)


def is_occluder(obj, scene):
    """Can shade others (decision 15); a mover too (decision 59: refresh() leaves out the movers it cannot sample)."""
    return (tags.is_ao_occluder(obj, scene) and not tags.is_marked_invisible(obj, scene)
            and not tags.is_no_export(obj, scene) and not all_skip(obj))


MOTION_TOL = 1e-4  # decision 59: placements this close (m, and rotation-scale matrix units) are the same
MOTION_SAMPLES = 64  # frames sampled at most


def _key_times(idb):
    """The frames of an ID's own animation: its range's ends, its action's keyframes, its strips' ends."""
    ad = getattr(idb, 'animation_data', None)
    if ad is None:
        return []
    out = []
    r = _anim_range(idb)
    if r is not None:
        out += [r[0], r[1]]
    for fc in _fcurves(ad):
        n = len(fc.keyframe_points)
        if n:
            co = np.empty(2 * n, np.float64)
            fc.keyframe_points.foreach_get('co', co)
            out += co[0::2].tolist()
    for track in ad.nla_tracks:
        for strip in track.strips:
            out += [float(strip.frame_start), float(strip.frame_end)]
    return out


def sample_frames(view_layer):
    """Decision 59: the frames Refresh steps through: every key and range end of the view layer's animated objects
    and the middles between them, at most MOTION_SAMPLES (spread evenly, both ends kept)."""
    t = set()
    for o in view_layer.objects:
        t.update(round(float(x), 4) for x in _key_times(o))
    t = sorted(t)
    if len(t) < 2:
        return t
    mids = [round(0.5 * (a + b), 4) for a, b in zip(t, t[1:])]
    t = sorted(set(t) | set(mids))
    if len(t) > MOTION_SAMPLES:
        idx = np.unique(np.rint(np.linspace(0, len(t) - 1, MOTION_SAMPLES)).astype(int))
        t = [t[i] for i in idx]
    return t


def motion(scene, view_layer, objs):
    """Decision 59: every object's world placement at the current frame and at each sampled frame (the scene set to
    each, then back to the current frame). Returns dict(frames, index {name: row}, M (n, 1 + frames, 4, 4), moving
    (n,) bool: its placement changes)."""
    import math
    frames = sample_frames(view_layer)
    objs = list(objs)
    index = {o.name: i for i, o in enumerate(objs)}

    def grab():
        return np.array([np.array(o.matrix_world, dtype=np.float64) for o in objs]).reshape(len(objs), 4, 4)
    mats = [grab()]
    if frames and objs:
        f0, s0 = scene.frame_current, scene.frame_subframe
        try:
            for f in frames:
                fi = int(math.floor(f))
                scene.frame_set(fi, subframe=float(f - fi))
                mats.append(grab())
        finally:
            scene.frame_set(f0, subframe=s0)
    M = np.stack(mats, axis=1)
    moving = (np.abs(M - M[:, :1]).max(axis=(1, 2, 3)) > MOTION_TOL) if len(objs) else np.zeros(0, bool)
    return dict(frames=frames, index=index, M=M, moving=moving)


def texture_size(material):
    from .uv_marks import texture_size as size_of
    return size_of(material)


# an object's axes further from square than this (a shear from a parent's scale): its world box only (decision 64)
ORTHO_TOL = 1e-4


def denoise_opts(scene):
    """Decision 56: the denoise options as core.denoise_master takes them, or None when Denoise is off. What a
    master's denoise is compared with (the curvature width too when the curvature guides it)."""
    import math
    s = scene.fss_ao_bake
    if not s.denoise:
        return None
    if s.dn_method == 'OIDN':  # Open Image Denoise: only the strength (the device does not change the result's kind)
        return dict(method='OIDN', strength=round(float(s.dn_strength), 4))
    o = dict(method='FILTER', radius=round(float(s.dn_radius), 6), strength=round(float(s.dn_strength), 4),
             max_levels=int(s.dn_levels), detail=round(float(s.dn_detail), 4),
             normal_deg=round(math.degrees(float(s.dn_normal)), 3), curv_mode=s.dn_curv_mode, noise=s.dn_noise)
    if s.dn_curv_mode != 'OFF':
        o.update(curv_threshold=round(float(s.dn_curv_threshold), 4), curv_width=round(float(s.curv_width), 6))
    if s.dn_noise == 'SAMPLES':
        o['samples'] = int(s.samples)
    return o


def settings_dict(scene):
    s = scene.fss_ao_bake
    return dict(ao_distance=round(float(s.distance), 6), samples=int(s.samples), device=s.device,
                threads=core.native_copy().threads_of(s.threads),  # decision 5 of apply-native-copy: 0 is Auto
                sample_split=s.sample_quality == 'SPLIT', curvature=bool(s.curvature),
                curv_width=round(float(s.curv_width), 6), denoise=denoise_opts(scene),
                baker=s.baker, optix_samples=int(s.optix_samples),  # OptiX baker decisions 22, 24
                channel_samples=int(s.channel_samples), vertex_color=vertex_color_sources(s),
                vc_attribute=s.vc_attribute,  # decision 91
                custom_value=custom_value_sources(s))  # decision 99


VC_GROUPS = ('ao', 'albedo', 'rough', 'metal', 'emis')  # decisions 88, 95: the channels with a vertex colour source


def vertex_color_sources(s):
    """Decision 88: {group: 'OVERWRITE' or 'MULTIPLY'} of the ticked vertex colour sources (the runner uses one only
    for a channel it bakes)."""
    return {g: getattr(s, f'vc_{g}_mode') for g in VC_GROUPS
            if getattr(s, f'vc_{g}', False) and not getattr(s, f'cv_{g}', False)}


# decisions 99 and 100: the channels with a Custom source (the object's own value or colour)
CV_GROUPS = ('albedo', 'rough', 'metal', 'emis')
CHANNEL_NAMES_CV = {'albedo': 'Albedo', 'rough': 'Roughness', 'metal': 'Metal', 'emis': 'Emissive'}
CV_DEFAULTS = {'albedo': (1.0, 1.0, 1.0), 'rough': 1.0, 'metal': 0.0, 'emis': (0.0, 0.0, 0.0)}


def custom_value_sources(s):
    """Decision 99: {group: 'OVERWRITE' or 'MULTIPLY'} of the channels whose source is Custom."""
    return {g: getattr(s, f'cv_{g}_mode') for g in CV_GROUPS if getattr(s, f'cv_{g}', False)}


def custom_values(obj):
    """Decisions 99 and 100: {group: value} of an object's own Custom values (a colour: a list of 3, linear; decision
    111: the albedo a list of 4, its alpha last)."""
    o = getattr(obj, 'fss_ao_bake', None)
    out = {}
    for g in CV_GROUPS:
        v = getattr(o, f'{g}_value', CV_DEFAULTS[g])
        out[g] = [round(float(c), 6) for c in v] if isinstance(CV_DEFAULTS[g], tuple) else round(float(v), 6)
    out['albedo'].append(round(float(getattr(o, 'albedo_alpha', 1.0)), 6))
    return out


def vc_overwritten(entry):
    """Rule item 4 of decision 88's hand-off: the AO is the vertex colour's alone (Overwrite): it does not depend on
    the surroundings and has no denoise."""
    return ((entry or {}).get('ao_source') or {}).get('mode') == 'OVERWRITE'


def item_distance(obj, scene):
    """Decision 51: a master's AO distance. The scene's; with Auto Distance, the factor times the longest axis of the
    object's own box (its local bounding box at its world scale), at most the scene's, so only small objects get a
    shorter one. A shared mesh measures its first copy, so every copy bakes at one distance."""
    s = scene.fss_ao_bake
    d = round(float(s.distance), 6)
    if not s.auto_distance:
        return d
    c = np.array([tuple(v) for v in obj.bound_box], dtype=np.float64)
    scale = np.linalg.norm(np.array(obj.matrix_world, dtype=np.float64)[:3, :3], axis=0)
    longest = float(((c.max(axis=0) - c.min(axis=0)) * scale).max())
    return min(d, round(max(float(s.auto_distance_factor) * longest, 0.001), 6))


def falloff_steps(scene):
    """Decision 53: the steps of the distance falloff (0: off). Each view is baked at the master's AO distance times
    1/n, 2/n ... 1 and the results averaged, so an occluder darkens less the farther it is (linear, 0 at the
    distance)."""
    s = scene.fss_ao_bake
    return int(s.falloff_steps) if s.falloff else 0


def falloff_curve(scene):
    """Decision 105: the falloff's curve (core.FALLOFF_CURVES), 'LINEAR' when the falloff is off."""
    s = scene.fss_ao_bake
    return str(s.falloff_curve) if s.falloff and s.falloff_curve in core.FALLOFF_CODE else 'LINEAR'


def _surround_settings(scene):
    s = settings_dict(scene)
    return dict(ao_distance=s['ao_distance'], **core.method_settings())


def _hash(obj):
    import hashlib
    return hashlib.sha1(json.dumps(obj, sort_keys=True).encode('utf-8')).hexdigest()[:20]


# ---------------------------------------------------------------------------------------------------------------------
# Refresh: the items to bake, their hashes and grades
# ---------------------------------------------------------------------------------------------------------------------

RULE_STATS = {}  # the last pass's scene rule: how close a gap came to its distance (fss_ao_near_stats), the pairs


def _rule_tools(scene, view_layer, meshes, baked):
    """The scene rule's state for one pass (decisions 15, 59, 64 and 65): the candidates, their motion and boxes.
    Returns dict(candidates, occluders, mo, moving, unknown, obj_of, near, prepare, against, prepare_against);
    near(obj, 'now' or 'swept', distance) gives the object's occluders by name, sorted; prepare(queries) computes the
    near() of many (obj, which, distance) in one call; against(obj, names) the names that move against obj
    (decision 59), prepare_against(pairs) many (name, name) pairs in one call. The geometry is the C++ DLL's
    (ao_bake_copy.SceneRule, bake-post-native journal Session 5), on the bake's Threads."""
    candidates = sorted(set(baked) | {o for o in meshes if is_occluder(o, scene)}, key=lambda o: o.name)
    mo = motion(scene, view_layer, candidates)  # decision 59: who moves, and against whom

    def moving(o):
        return bool(mo['moving'][mo['index'][o.name]])

    def unknown(o):
        """A mover whose motion is not sampled: tagged Animated, or animated without a range (a driver only)."""
        return (not moving(o) and is_mover(o, scene)
                and (tags.is_marked_animated(o, scene) or mover_range(o) is None))
    occluders = [o for o in candidates if is_occluder(o, scene) and not unknown(o)]
    by_name = {o.name: o for o in candidates}  # bpy.data.objects[name] scans the whole list: looked up here instead

    def obj_of(name):
        o = by_name.get(name)
        if o is None:
            o = by_name[name] = bpy.data.objects[name]
        return o
    # decisions 15, 64 and 65 in C++: each candidate's bound_box and its world matrix now; motion()'s placements at
    # the sampled frames (mo['M'][:, 0] is the current frame). The DLL makes the world boxes (now, and swept over the
    # sampled frames for a moving one) and the own boxes (an object whose axes are not square, a shear, keeps its world
    # box only)
    corners = np.array([[tuple(v) for v in o.bound_box] for o in candidates], dtype=np.float64).reshape(-1, 8, 3)
    now = np.array([np.array(o.matrix_world, dtype=np.float64) for o in candidates]).reshape(-1, 4, 4)
    occ_names = [o.name for o in occluders]
    occ_pos = {n: i for i, n in enumerate(occ_names)}
    geo = core.native_copy().SceneRule(corners, now, mo['M'], mo['moving'], [mo['index'][n] for n in occ_names],
                                       ORTHO_TOL, MOTION_TOL)
    threads = int(scene.fss_ao_bake.threads)  # decision 5 of apply-native-copy: 0 is Auto
    found = {}  # (name, which, distance): (occluder names, {name: gap})
    moved = {}  # (name, name): moves against
    RULE_STATS.clear()

    def note(st):
        for k, v in st.items():
            if k.startswith('closest'):
                RULE_STATS[k] = min(RULE_STATS.get(k, float('inf')), v)
            else:
                RULE_STATS[k] = RULE_STATS.get(k, 0) + v

    def prepare(queries):
        """near() of many objects in one call: queries [(obj, 'now' or 'swept', distance)]."""
        todo = list({(o.name, w, d): (o, w, d) for o, w, d in queries if (o.name, w, d) not in found}.values())
        if not todo:
            return
        res = geo.near([mo['index'][o.name] for o, _w, _d in todo], [1 if w == 'swept' else 0 for _o, w, _d in todo],
                       [d for _o, _w, d in todo], [occ_pos.get(o.name, -1) for o, _w, _d in todo], threads)
        for (o, w, d), (idx, gap) in zip(todo, res):
            names = [occ_names[i] for i in idx.tolist()]
            found[(o.name, w, d)] = (names, dict(zip(names, gap.tolist())))
        note(geo.stats)

    def near(obj, which, distance, gaps=None):
        """The occluders within the distance of the object (decisions 15, 64 and 65): their world boxes' gap first
        ('swept': over the sampled frames of a moving one), then the gap of the objects' own boxes as placed: at the
        current frame ('now'), else at each sampled frame, the smallest counting (one frame when neither moves). With
        `gaps` (a dict), each occluder's gap is put in it (decision 70: the larger of the two boxes' gaps, in metres;
        0 where the boxes touch)."""
        if (obj.name, which, distance) not in found:
            prepare([(obj, which, distance)])
        names, g = found[(obj.name, which, distance)]
        if gaps is not None:
            gaps.update(g)
        return sorted(names)

    def prepare_against(pairs):
        """Decision 59 for many (object name, occluder name) pairs in one call."""
        todo = sorted({p for p in pairs if p not in moved})
        if not todo:
            return
        res, singular = geo.moves([(mo['index'][a], mo['index'][b]) for a, b in todo], threads)
        moved.update(zip(todo, [None if s else r for r, s in zip(res.tolist(), singular.tolist())]))
        note(geo.stats)

    def against(obj, names):
        """Decision 59: the names (in motion()) whose placement relative to the object changes over the sampled frames
        (one moves, the other does not, or both move differently)."""
        prepare_against([(obj.name, n) for n in names])
        if any(moved[(obj.name, n)] is None for n in names):  # its matrix singular (a zero scale), as before
            raise np.linalg.LinAlgError('Singular matrix')
        return [n for n in names if moved[(obj.name, n)]]
    return dict(candidates=candidates, occluders=occluders, mo=mo, moving=moving, unknown=unknown, obj_of=obj_of,
                near=near, prepare=prepare, against=against, prepare_against=prepare_against)


def detect_occluders(context, objs):
    """Decision 68: the scene rule alone for these objects (the Detected tree's Refresh): their occluders by the rule,
    as Refresh finds them, written into _state['scene_rule'] (a new dict, so the panel's tree cache sees the change);
    no hashes, no grades. Returns the names done (objects that get a master)."""
    scene, view_layer = context.scene, context.view_layer
    meshes = _visible_meshes(view_layer)
    baked = [o for o in meshes if not bake_exclusion(o, scene)]
    tools = _rule_tools(scene, view_layer, meshes, baked)
    names = {o.name for o in baked}
    rule = dict(_state.get('scene_rule') or {})
    rule_gap = dict(_state.get('scene_gap') or {})
    done = []
    plan = []
    for obj in objs:
        if obj.name not in names:
            continue
        copies = sorted((u for u in baked if u.data is obj.data), key=lambda u: u.name)
        distance = item_distance(copies[0] if len(copies) > 1 else obj, scene)
        plan.append((obj, 'swept' if pose_count(obj, scene) > 1 else 'now', distance))
    tools['prepare'](plan)  # every object's scene rule in one call into the DLL
    for obj, which, distance in plan:
        rule_gap[obj.name] = {}
        rule[obj.name] = tools['near'](obj, which, distance, rule_gap[obj.name])
        done.append(obj.name)
    _state['scene_rule'], _state['scene_gap'] = rule, rule_gap
    _state['rule_gen'] = _state.get('rule_gen', 0) + 1
    return done


def refresh(context, relink=True, instances=None):
    """Computes every master's keys and grade against index.json; links renamed masters again. Returns _state.
    instances: {mesh name: object name}, a bake's choice of the copy of One Instance meshes (decision 77)."""
    scene = context.scene
    view_layer = context.view_layer
    depsgraph = context.evaluated_depsgraph_get()
    folder = bake_folder()
    index = read_index(folder, use_cache=False) if folder else dict(masters={})
    masters = index.get('masters', {})
    instances = instances or {}
    meshes = _visible_meshes(view_layer)
    excluded = {}
    baked = []
    chan_only = []  # decision 110: the material channels alone (outside the scene rule)
    for obj in meshes:
        why = bake_exclusion(obj, scene)
        if why and channels_only(obj, why):
            chan_only.append(obj)
        elif why:
            excluded[obj.name] = why
        else:
            baked.append(obj)
    tools = _rule_tools(scene, view_layer, meshes, baked)
    candidates, occluders, mo, obj_of, near = (tools[k] for k in ('candidates', 'occluders', 'mo', 'obj_of', 'near'))
    moving, unknown = tools['moving'], tools['unknown']
    occ_key = {}  # an occluder's part of the surroundings key, once per Refresh
    scene_rule = {}  # decisions 60 and 62: each baked object's scene-rule occluders (names, sorted), for the panel
    scene_gap = {}  # decision 70: their gaps {name: metres}, for the panel's distance column
    geo = {}
    evs = {}

    def ev_of(obj, uv_names=()):
        if obj.name not in evs or (uv_names and not set(uv_names) <= set(evs[obj.name]['uv'])):
            evs[obj.name] = core.evaluated_triangles(obj, depsgraph, uv_names)
        return evs[obj.name]

    threads = int(scene.fss_ao_bake.threads)

    def geo_hash(obj):
        if obj.name not in geo:
            geo[obj.name] = core.mesh_hash(ev_of(obj), threads)
        return geo[obj.name]

    users = {}
    for obj in baked:
        users.setdefault(obj.data, []).append(obj)
    chan_names = {o.name for o in chan_only}
    for obj in chan_only:
        if obj.data not in users:  # a mesh also used by a baked object stays that object's
            users.setdefault(obj.data, [])
        users[obj.data].append(obj)
    # the scene rule of every baked object, then the motion of every (object, occluder) pair, each in one call into the
    # DLL (bake-post-native journal Session 5): each object at its master's AO distance (a shared mesh's first copy's)
    plan = {}  # name: (which, distance)
    for objs in users.values():
        d = item_distance(sorted(objs, key=lambda o: o.name)[0], scene)
        for o in objs:
            plan[o.name] = ('swept' if pose_count(o, scene) > 1 else 'now', d)
    tools['prepare']([(o, *plan[o.name]) for o in baked])
    chosen = {}  # name: (mode, the scene rule's occluders, the occluders)
    for o in baked:
        mode = occluder_mode(o, scene)
        rule = near(o, *plan[o.name])
        if mode == 'SELF':
            occ = []
        elif mode == 'CUSTOM':  # decision 60: the scene rule (when on) minus the ignored, plus the added
            occ = custom_occluders(o, view_layer, rule)
        else:
            occ = rule
        chosen[o.name] = (mode, rule, occ)
    tools['prepare_against']([(o.name, n) for o in baked for n in chosen[o.name][2] if n in mo['index']])
    base = _surround_settings(scene)
    frame = scene.frame_current
    items = {}
    by_object = {}
    split = scene.fss_ao_bake.sample_quality == 'SPLIT'
    samples = int(scene.fss_ao_bake.samples)
    falloff = falloff_steps(scene)
    curve = falloff_curve(scene)

    def occluder_key(n):
        if n not in occ_key:
            o = obj_of(n)
            occ_key[n] = (n, core.matrix_key(o.matrix_world), geo_hash(o), sorted(tags.get_tags(o)))
            if not MATERIAL_RULE and material_skip_slots(o):
                # decision 112: faces the material rule left out now shade: the masters near it are stale
                occ_key[n] += (True,)
        return occ_key[n]

    def surroundings(obj, mover, distance):
        """One object's occluders within its master's AO distance (a moving one's box over its motion), poses and
        surroundings key (decisions 15, 34, 35, 51, 59): (mode, occluder names, pose frames or None, pose note, posed
        occluder names, key, the occluders moving against it, the poses' frame range)."""
        frames, pose_note, rng = None, '', None
        # the scene rule: several poses, what comes near over the motion; one pose, what is near at the current frame.
        # Kept for every object for the panel's Detected list (decision 62), whatever its occluders
        scene_gap[obj.name] = {}
        near(obj, *plan[obj.name], scene_gap[obj.name])
        mode, rule, occ = chosen[obj.name]
        scene_rule[obj.name] = list(rule)
        known = [n for n in occ if n in mo['index']]
        posed = [n for n in known if moving(obj_of(n))]  # placed at each pose frame
        against = tools['against'](obj, known)
        if against:
            involved = ([obj] if moving(obj) else []) + [obj_of(n) for n in against if moving(obj_of(n))]
            frames, pose_note, rng = motion_frames(obj, scene, involved, mo['frames'])
        elif unknown(obj) and mode != 'SELF':
            pose_note = 'moves without keys (a driver or the Animated tag): baked in the current frame'
        one_pose = (bool(against) or unknown(obj)) and not frames  # its current frame matters
        key = dict(base, ao_distance=distance, matrix=core.matrix_key(obj.matrix_world), mover=mover,
                   frame=frame if one_pose else None,
                   occluders=[occluder_key(n) for n in occ])
        if falloff:  # decision 53: a key only with falloff, so the hashes without it stay
            key['falloff'] = falloff
            if curve != 'LINEAR':  # decision 105: a key only for another curve
                key['falloff_curve'] = curve
        # decisions 34 and 35: keys only when not the 0.57 bake (one pose, the scene rule), so its hashes stay
        if mode != 'SCENE':
            key['occluder_mode'] = mode
        if frames:
            key['poses'] = frames
            key['posed'] = posed
            if split:  # decision 49: the poses share the samples
                key['samples_per_view'] = core.view_samples(samples, len(frames), True)
        return mode, occ, frames, pose_note, posed, key, against, rng
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
        # decision 30: only faces with a material (a texture set) are baked; under the material rule, not a skip one
        set_mats = [m for m in mats if m < len(slots) and slots[m] is not None and m not in skip]
        chan = all(o.name in chan_names for o in objs)  # decision 110: the material channels alone
        if chan and MATERIAL_RULE:
            set_mats = [m for m in mats if m < len(slots) and is_channel_material(slots[m])]
            skip = [i for i in skip if i not in set_mats]
        if not set_mats:
            for o in objs:
                excluded[o.name] = ((SKIP_ONLY if MATERIAL_RULE else SKIP_AO) if chan
                                    else 'no face with a texture set (material)')
            continue
        mh = geo_hash(first)
        if not MATERIAL_RULE:
            # decision 112: faces the material rule left out of the master are in it now: the master's mesh changed
            old = set(material_skip_slots(first))
            old_mats = ([m for m in mats if m < len(slots) and is_channel_material(slots[m])] if chan
                        else [m for m in set_mats if m not in old])
            if old_mats != set_mats:
                mh = _hash(dict(mesh=mh, all_faces=True))
        mover = False if chan else (moving(first) or unknown(first))
        dist = item_distance(first, scene)
        copies, combine = None, None
        one = None  # decision 77: One Instance's (copy, source, the copy the master was baked from)
        if chan:  # decision 110: no AO, so no surroundings (the scene rule does not see these objects)
            key = dict(channels_only=True)
            sur = _hash(key)
            mode, occ, frames, pose_note, posed, against, rng = 'SCENE', [], None, '', [], [], None
        elif shared:
            # decision 47: every copy baked in its own surroundings, its own poses; combined per master pixel
            combine = shared_combine(me, scene)
            copies, keys = [], []
            if combine == 'ONE':
                # decision 77: One Instance bakes one copy for all of them: the bake's choice from the selection,
                # else the copy its master was baked from, else the first by name
                entry = masters.get(stem)
                rep, src = shared_instance(me, objs, entry, instances.get(me.name))
                baked_from = None
                if entry is not None:
                    baked_from = entry['instance'] if 'instance' in entry else shared_instance(me, objs, entry)[0].name
                one = (rep, src, baked_from)
            for o in ([one[0]] if one else objs):
                m_o = moving(o) or unknown(o)
                c_mode, c_occ, c_frames, c_note, c_posed, c_key, c_against, c_rng = surroundings(o, m_o, dist)
                copies.append(dict(object=o.name, occluder_mode=c_mode, occluders=c_occ, poses=c_frames,
                                   pose_note=c_note, posed=c_posed, mover=m_o, against=c_against, pose_range=c_rng))
                keys.append([o.name, c_key])
            sur = dict(base, ao_distance=dist, shared=True, combine=combine, copies=keys, sample_split=split)
            if falloff:
                sur['falloff'] = falloff
                if curve != 'LINEAR':
                    sur['falloff_curve'] = curve
            sur = _hash(sur)
            mode = 'COPIES'
            occ = sorted({n for c in copies for n in c['occluders']})
            frames, pose_note, posed, against, rng = None, '', [], [], None
        else:
            mode, occ, frames, pose_note, posed, key, against, rng = surroundings(first, mover, dist)
            sur = _hash(key)
        sets = sorted({slots[m].name for m in set_mats})
        tex = {str(m): int(texture_size(slots[m])) for m in set_mats}  # faces of other indices are not baked
        # decision 107: an Object UV master for an object whose baked faces are in one texture set; its key holds the
        # UVs of those faces and the texture size, so a UV change makes it stale
        layout = 'AUTO'
        if scene.fss_ao_bake.master_layout == 'OBJECT_UV' and len(sets) == 1:
            layout = 'OBJECT_UV'
            sel_t = np.isin(ev['mat'], np.array(set_mats))
            uvh = hashlib.sha1(np.ascontiguousarray(ev['uv'][uv][sel_t], np.float32).tobytes()).hexdigest()
            lay_key = dict(master_layout=layout, uv_hash=uvh, uv_size=sorted(set(tex.values())))
            if shared:
                sur = _hash(dict(sur=sur, **lay_key))
            else:
                sur = _hash(dict(key, **lay_key))
        item = dict(key=stem, kind=kind, name=name, object=first.name, mesh=me.name, users=[o.name for o in objs],
                    uv=uv, mesh_hash=mh, surround_hash=sur, occluders=occ, mover=mover, frame=frame,
                    skip_slots=skip, tex_size=tex, sets=sets, grade='MISSING', occluder_mode=mode, poses=frames,
                    pose_note=pose_note, posed=posed, copies=copies, combine=combine, ao_distance=dist,
                    falloff=falloff, falloff_curve=curve if falloff else None, against=against, pose_range=rng,
                    master_layout=layout, channels_only=chan)
        if one:  # decision 77: the copy graded and baked, where it came from, the copy the master was baked from
            item.update(instance=one[0].name, instance_from=one[1], baked_from=one[2])
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
            for src, dst in zip(core.all_master_files(folder, old), core.all_master_files(folder, stem)):
                if os.path.isfile(src):
                    os.replace(src, dst)
            entry.update(key=stem, name=item['name'], object=item['object'], mesh=item['mesh'],
                         relinked_from=entry.get('name'))
            del masters[old]
            masters[stem] = entry
            relinked.append((entry['relinked_from'], item['name']))
        if relinked:
            write_index(folder, index)
    width = round(float(scene.fss_ao_bake.curv_width), 6)
    dn_want = denoise_opts(scene)
    for stem, item in items.items():
        item['grade'] = grade(item, masters.get(stem), folder)
        item['cm_grade'] = curv_grade(item, masters.get(stem), folder, width)
        item['dn_grade'] = dn_grade(item, masters.get(stem), folder, dn_want)
        item['ch_grades'] = channel_grades(item, masters.get(stem), folder)
    _state.update(items=items, by_object=by_object, excluded=excluded, refreshed=time.time(), folder=folder,
                  relinked=relinked, sets=texture_set_rows(items, masters), curv_width=width,
                  dn_want=dn_want, motion_frames=len(mo['frames']), moving=int(mo['moving'].sum()),
                  scene_rule=scene_rule, scene_gap=scene_gap, rule_gen=_state.get('rule_gen', 0) + 1)
    return _state


def grade(item, entry, folder):
    if entry is None or not folder or not has_files(folder, item['key']):
        return 'MISSING'
    if entry.get('mesh_hash') != item['mesh_hash']:
        return 'MESH'
    if entry.get('surround_hash') != item['surround_hash'] and not vc_overwritten(entry):  # decision 88
        return 'SURROUNDINGS'
    return 'UP_TO_DATE'


def curv_grade(item, entry, folder, width):
    """Decision 55: the state of a master's curvature (CURV_GRADES); item['grade'] is its AO grade."""
    if item['grade'] in ('MISSING', 'MESH'):
        return 'NEEDS_AO'
    c = (entry or {}).get('curvature')
    if not c or not os.path.isfile(core.image_paths(folder, item['key'], 'curv')[0]):  # .curv.jxl (decision 6)
        return 'MISSING'
    if round(float(c.get('width', -1.0)), 6) != round(float(width), 6):
        return 'WIDTH'
    return 'UP_TO_DATE'


def dn_grade(item, entry, folder, want):
    """Decision 56: the state of a master's denoise (DN_GRADES) against the options wanted (None: off)."""
    if item['grade'] in ('MISSING', 'MESH'):
        return 'NEEDS_AO'
    if vc_overwritten(entry):  # decision 88: an AO from the vertex colour alone is not denoised
        return 'UP_TO_DATE'
    have = ((entry or {}).get('denoise') or {}).get('settings')
    if have is not None:  # masters denoised before Follow Gradient and Bridge Seams were removed (both off)
        have = {k: v for k, v in have.items() if not (k in ('bridge', 'gradient') and v is False)}
        have.setdefault('method', 'FILTER')  # denoised before the method choice: the Surface Filter
    if have == want:
        return 'UP_TO_DATE'
    if have is not None and not os.path.isfile(core.image_paths(folder, item['key'], 'ao.raw')[0]):
        return 'NEEDS_AO'
    return 'STALE'


def channel_grade(item, entry, folder, group):
    """Decisions 79 and 80: a material channel's grade (UP_TO_DATE, MESH, MISSING): MISSING without its entry or a
    file of it (an image, the layout's .ao.npz or .ao.map), MESH when the mesh it was baked from is not the item's; not
    stale when the material or the surroundings change."""
    c = ((entry or {}).get('channels') or {}).get(group)
    if not c or not folder:
        return 'MISSING'
    _img, mp, npz = core.master_paths(folder, item['key'])
    if not all(os.path.isfile(p) for p in core.channel_paths(folder, item['key'], group) + [mp, npz]):
        return 'MISSING'
    if c.get('mesh_hash') != item['mesh_hash']:
        return 'MESH'
    return 'UP_TO_DATE'


def channel_grades(item, entry, folder):
    """{group: grade} of the material channels the master's entry has (decision 79); the others are missing."""
    have = ((entry or {}).get('channels') or {})
    return {g: channel_grade(item, entry, folder, g) for g in core.CHANNEL_GROUPS if g in have}


def channel_choice(stems, groups, selected):
    """Decision 80: {stem: [groups]} a bake bakes of the chosen material channels: Selected, all of them; Missing and
    Stale, those not up to date (a channel the master does not have is missing)."""
    out = {}
    for stem in stems:
        have = _state['items'][stem].get('ch_grades') or {}
        got = [g for g in core.CHANNEL_GROUPS if g in groups and (selected or have.get(g, 'MISSING') != 'UP_TO_DATE')]
        if got:
            out[stem] = got
    return out


def dn_counts():
    c = {g: 0 for g in DN_GRADES}
    for item in _state['items'].values():
        if not item.get('channels_only'):  # decision 110
            c[item.get('dn_grade', 'UP_TO_DATE')] += 1
    return c


def curv_counts():
    c = {g: 0 for g in CURV_GRADES}
    for item in _state['items'].values():
        if not item.get('channels_only'):  # decision 110
            c[item.get('cm_grade', 'MISSING')] += 1
    return c


def bake_choice(stems, want_ao, want_cm, selected, denoise=None):
    """Decision 55: what a bake button bakes of each master: ({stem: (ao, cm, dn)}, names that need an AO bake before
    their curvature). Selected: everything ticked; Missing and Stale: the stale parts. When the AO is baked and CM is
    ticked, the curvature is written with it (the layout may change). Decision 56: with AO ticked, a master whose AO
    is up to date but whose denoise is not gets the filter again from its raw bake (dn, no rays); when the curvature
    guides the denoise (denoise: the options, None off), a stale curvature is written first, CM ticked or not."""
    what, needs_ao = {}, []
    guide = denoise is not None and denoise.get('curv_mode', 'OFF') != 'OFF'
    for stem in stems:
        it = _state['items'][stem]
        if it.get('channels_only'):  # decision 110: no AO, curvature or denoise
            continue
        ao = want_ao and (selected or it['grade'] != 'UP_TO_DATE')
        dn = want_ao and not ao and it.get('dn_grade') == 'STALE'
        cm = want_cm and (ao or selected or it.get('cm_grade') != 'UP_TO_DATE')
        if guide and (ao or dn) and (ao or it.get('cm_grade') != 'UP_TO_DATE'):
            cm = True
        if cm and not ao and it.get('cm_grade') == 'NEEDS_AO':
            needs_ao.append(it['name'])
            cm = False
        if ao or cm or dn:
            what[stem] = (ao, cm, dn)
    return what, needs_ao


def bake_auto(stems, want_ao, want_cm, denoise=None, groups=(), channels=None):
    """The panel's Bake Selected: per master, its missing or stale parts as
    Missing and Stale bakes them (a stale denoise alone re-run from the raw bake, without rays); a master with
    nothing out of date is baked in full (everything ticked). Returns bake_choice's pair. groups: the chosen material
    channels (decision 80), their choice per master put into `channels` ({stem: [groups]}) the same way."""
    what, needs_ao, full = {}, [], []
    channels = {} if channels is None else channels
    for stem in stems:
        w, n = bake_choice([stem], want_ao, want_cm, False, denoise)
        c = channel_choice([stem], groups, False)
        if w or n or c:
            what.update(w)
            needs_ao += n
            channels.update(c)
        else:
            full.append(stem)
    w, n = bake_choice(full, want_ao, want_cm, True, denoise)
    what.update(w)
    channels.update(channel_choice(full, groups, True))
    return what, needs_ao + n


def regrade():
    """After a bake: the grades again from index.json, with the hashes of the last refresh."""
    folder = _state.get('folder')
    masters = read_index(folder, use_cache=False).get('masters', {}) if folder else {}
    for stem, item in _state['items'].items():
        if 'baked_from' in item:  # decision 77: One Instance's master, baked from the copy its entry names
            entry = masters.get(stem)
            if entry is None:
                item['baked_from'] = None
            elif 'instance' in entry:
                item['baked_from'] = entry['instance']
        item['grade'] = grade(item, masters.get(stem), folder)
        item['cm_grade'] = curv_grade(item, masters.get(stem), folder, _state.get('curv_width', 0.0))
        item['dn_grade'] = dn_grade(item, masters.get(stem), folder, _state.get('dn_want'))
        item['ch_grades'] = channel_grades(item, masters.get(stem), folder)
    _state['sets'] = texture_set_rows(_state['items'], masters)


def texture_set_rows(items, masters):
    """{material name: dict(items, MISSING, MESH, SURROUNDINGS, UP_TO_DATE)} over the baked items' faces."""
    rows = {}
    for stem, item in items.items():
        for name in item['sets']:
            row = rows.setdefault(name, dict(items=[], MISSING=0, MESH=0, SURROUNDINGS=0, UP_TO_DATE=0,
                                             channels_only=True))
            row['items'].append(stem)
            if item.get('channels_only'):  # decision 110: a set of the material channels alone has no AO grades
                continue
            row['channels_only'] = False
            row[item['grade']] += 1
    return rows


def counts():
    c = {g: 0 for g in GRADES}
    for item in _state['items'].values():
        if item.get('channels_only'):  # decision 110: no AO
            continue
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

SNAPSHOT = 'snapshot.blend'  # the current state the second Blender opens (in the bake folder)


def remove_snapshot(folder):
    """The snapshot (and a .blend1 Blender may have kept of an older one) removed, if there."""
    for name in (SNAPSHOT, SNAPSHOT + '1'):
        try:
            os.remove(os.path.join(folder, name))
        except OSError:
            pass


def write_snapshot(folder):
    """The open file's current state, unsaved changes included, written as a copy into the bake folder: the .blend
    on disk, its path and its unsaved state stay as they are; relative paths are remapped to the copy's folder.
    Returns its path."""
    remove_snapshot(folder)
    path = os.path.join(folder, SNAPSHOT)
    bpy.ops.wm.save_as_mainfile(filepath=path, copy=True, check_existing=False, compress=False, relative_remap=True)
    return path


def make_job(context, stems, test_delay_s=0.0, tile_px=0, test_tile_delay_s=0.0, what=None, baker_window=False,
             channels=None, channel_objects=None):
    """The job file of a bake, and the snapshot of the current state the bake opens. what: {stem: (ao, cm, dn)}
    (decisions 55, 56), else the AO of each, with the curvature when CM is ticked. baker_window: FSS OptiX shows its
    window although the second Blender runs in the background (OptiX baker decision 28). channels: {stem: [groups]},
    the material channels to bake (decision 79), from the copy channel_objects names ({stem: object name}, a shared
    mesh's bake choice; else the master's object)."""
    scene = context.scene
    folder = bake_folder()
    os.makedirs(folder, exist_ok=True)
    items = []
    for stem in stems:
        item = _state['items'][stem]
        posed = set(item.get('posed') or ())
        occ = [dict(name=n, skip_slots=skip_slots(bpy.data.objects[n]), posed=n in posed) for n in item['occluders']]
        job_item = dict(key=stem, kind=item['kind'], name=item['name'], object=item['object'], uv=item['uv'],
                        skip_slots=item['skip_slots'], tex_size=item['tex_size'], occluders=occ,
                        surround_hash=item['surround_hash'], mesh_hash=item['mesh_hash'], mover=item['mover'],
                        frame=item['frame'], occluder_mode=item.get('occluder_mode', 'SCENE'),
                        poses=item.get('poses'), pose_note=item.get('pose_note', ''),
                        ao_distance=item['ao_distance'], falloff=item.get('falloff', 0),
                        falloff_curve=item.get('falloff_curve') or 'LINEAR',
                        master_layout=item.get('master_layout') or 'AUTO')
        ao, cm, dn = (what or {}).get(stem, (True, bool(scene.fss_ao_bake.curvature), False))
        job_item.update(ao=bool(ao), cm=bool(cm), dn=bool(dn))
        if (channels or {}).get(stem):  # decision 79
            job_item.update(channels=list(channels[stem]),
                            channel_object=(channel_objects or {}).get(stem) or item['object'])
            src = bpy.data.objects.get(job_item['channel_object']) or bpy.data.objects.get(item['object'])
            if src is not None:  # decision 99: the Custom values of the object the channels come from
                job_item['custom_values'] = custom_values(src)
        if item.get('copies'):  # decision 47: a shared mesh's copies, each with its own surroundings
            job_item['combine'] = item['combine']
            job_item['copies'] = [dict(c, occluders=[dict(name=n, skip_slots=skip_slots(bpy.data.objects[n]),
                                                          posed=n in c['posed']) for n in c['occluders']])
                                  for c in item['copies']]
        items.append(job_item)
    source = write_snapshot(folder)
    job = dict(schema=core.SCHEMA, blend=bpy.data.filepath, source=source, folder=folder, settings=settings_dict(scene),
               items=items, created=time.strftime('%Y-%m-%d %H:%M:%S'), test_delay_s=float(test_delay_s),
               tile_px=int(tile_px), test_tile_delay_s=float(test_tile_delay_s), baker_window=bool(baker_window))
    path = os.path.join(folder, 'job.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(job, f, indent=1)
    return path


def start_bake(job_path, hidden=False):
    """Starts the second Blender on the job's snapshot (the saved file for a job without one): hidden (decision 36:
    in the background, no window and no console, its output in runner.log) or with its window. Returns the process."""
    folder = os.path.dirname(job_path)
    with open(job_path, encoding='utf-8') as f:
        source = json.load(f).get('source') or bpy.data.filepath
    for name in ('status.json', 'cancel'):
        try:
            os.remove(os.path.join(folder, name))
        except OSError:
            pass
    args = [bpy.app.binary_path, '--factory-startup']
    if hidden:
        args.append('-b')
    args += [source, '--python', RUNNER, '--', job_path]
    kw = {}
    if hidden:
        log = open(os.path.join(folder, 'runner.log'), 'w', encoding='utf-8')
        kw.update(stdout=log, stderr=subprocess.STDOUT)
        _run['log'] = log
        if os.name == 'nt':
            kw['creationflags'] = subprocess.CREATE_NO_WINDOW
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
    if _run.get('folder'):
        remove_snapshot(_run['folder'])
    regrade()
    return read_status()
