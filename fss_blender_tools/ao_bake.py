"""AO Bake panel (auto-bake journal, decision 29 and P46): bake masters in a second Blender, apply them to textures.

FSS MSFS Tools > AO Bake:
- Bake: AO distance (scene, decision 16), samples, device; poses of moving parts and the occluders (scene defaults,
  decisions 34 and 35), the run mode (Hidden or Visible, decision 36); the active object's overrides (poses, occluders,
  its custom list of occluders with Add Selected, Remove, Clear); the masters' counts (up to date, surroundings
  changed, mesh changed, missing, excluded); Bake Missing and Stale, Bake Selected, Select Stale, Select Missing; while
  a bake runs, object n of m, its name, tile and pose, time spent and left, Cancel, and a preview of the master being
  baked (bpy.utils.previews: no datablock, the file not marked changed); a warning when the .blend has unsaved changes
  (the bake reads the saved file); the report of the last bake.
- Apply: padding and output folder; a row per texture set with its state (masters complete, or the number missing or
  stale; faces under 4 x); for the active row: target (ORM slot texture or separate file) and the separate file's
  name, resolution, layout, green and blue, sampling; the warnings; Apply, Apply All, Apply Selected.
The panel draws without writing: the hashes are computed by Refresh (and before a bake), index.json is read when a
file opens and after a bake.
"""

import hashlib
import os
import time

import bpy
import numpy as np
from bpy.app.handlers import persistent

from . import ao_bake_apply as apply_mod
from . import ao_bake_core as core
from . import ao_bake_store as store

DEVICES = [('CPU', 'CPU', 'Bake on the CPU'), ('GPU', 'GPU', 'Bake on the first GPU type found (OptiX, CUDA, HIP, oneAPI)')]
RESOLUTION_ITEMS = [('ORM', 'ORM Texture Size', "The size of the texture in the material's ORM slot (else the "
                     "texture set's size)")] + [(r, r, f'{r} x {r} pixels') for r in apply_mod.RESOLUTIONS]


def _redraw():
    wm = bpy.context.window_manager
    for window in getattr(wm, 'windows', ()):
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


class FSS_AOBakeSettings(bpy.types.PropertyGroup):
    distance: bpy.props.FloatProperty(name="AO Distance", default=0.1, min=0.001, soft_max=1.0, unit='LENGTH',
                                      precision=3, description="How far other geometry darkens a surface. One value "
                                      "for the whole file; changing it makes every master's surroundings stale")
    samples: bpy.props.IntProperty(name="Samples", default=64, min=1, soft_max=1024,
                                   description="Cycles samples per master pixel")
    device: bpy.props.EnumProperty(name="Device", items=DEVICES, default='CPU')
    threads: bpy.props.IntProperty(name="Threads", default=12, min=1, max=64,
                                   description="CPU threads of the bake")
    padding: bpy.props.IntProperty(name="Padding", default=8, min=0, max=64, subtype='PIXEL',
                                   description="Pixels written around each island by Apply")
    output_folder: bpy.props.StringProperty(name="Output Folder", default='', subtype='DIR_PATH',
                                            description="Where Apply writes separate AO files. Empty: a folder "
                                            "<blend name>_ao beside the .blend")
    poses: bpy.props.IntProperty(name="Default Poses", default=5, min=1, max=64,
                                 description="Moving parts (animated objects) are baked in this many poses spread "
                                 "evenly over their own animation and averaged, so a shadow that only one pose has "
                                 "does not stay on the part. 1: the current frame only. An object can override it")
    occluders: bpy.props.EnumProperty(name="Default Occluders", default='SCENE', items=[
        ('SCENE', 'Scene Rule', 'Every visible static mesh near the object darkens it (not moving parts, not '
         'Non-AO-Occluder or Invisible objects)'),
        ('SELF', 'Self Only', 'Each object darkens only itself')],
        description="What darkens an object; an object can override it")
    run_mode: bpy.props.EnumProperty(name="Bake Window", default='HIDDEN', items=[
        ('HIDDEN', 'Hidden', 'The second Blender bakes in the background, without a window'),
        ('VISIBLE', 'Visible', 'The second Blender opens a window that shows the master being baked')],
        description="How the second Blender that bakes runs; this panel shows the progress and a preview in both")


OBJECT_OCCLUDERS = [
    ('DEFAULT', 'Default', "The scene's Default Occluders"),
    ('SCENE', 'Scene Rule', 'Every visible static mesh near the object darkens it'),
    ('SELF', 'Self Only', 'Only the object itself'),
    ('CUSTOM', 'Custom', 'The objects in the list below, posed with this object when it moves')]
SCENE_OCCLUDER_NAMES = {'SCENE': 'Scene Rule', 'SELF': 'Self Only'}
_occluder_items = []  # Blender keeps no reference to a dynamic enum's strings: kept here


def object_occluder_items(self, context):
    """The object's occluder choices; Default names the scene's Default Occluders (values as the static list had)."""
    scene = getattr(context, 'scene', None) if context is not None else None
    default = SCENE_OCCLUDER_NAMES.get(scene.fss_ao_bake.occluders, 'Scene Rule') if scene is not None else 'Scene Rule'
    items = [(k, f'Default ({default})' if k == 'DEFAULT' else name, desc, i)
             for i, (k, name, desc) in enumerate(OBJECT_OCCLUDERS)]
    _occluder_items[:] = items
    return items


def _get_own_poses(self):
    return self.poses > 0


def _set_own_poses(self, value):
    if not value:
        self.poses = 0
    elif self.poses <= 0:
        self.poses = int(bpy.context.scene.fss_ao_bake.poses)


class FSS_AOOccluderRef(bpy.types.PropertyGroup):
    object: bpy.props.PointerProperty(type=bpy.types.Object, name="Object")


class FSS_AOObjectSettings(bpy.types.PropertyGroup):
    """Per-object overrides of the bake (decisions 34 and 35); `fss_` on the object, so the glTF extras drop them."""
    poses: bpy.props.IntProperty(name="Poses", default=0, min=0, max=64,
                                 description="This object's pose count when it moves. 0: the scene's Default Poses")
    own_poses: bpy.props.BoolProperty(name="Own Poses", get=_get_own_poses, set=_set_own_poses,
                                      description="Bake this moving object in its own number of poses instead of "
                                      "the scene's Default Poses")
    occluders: bpy.props.EnumProperty(name="Occluders", items=object_occluder_items, default=0,
                                      description="What darkens this object")
    custom: bpy.props.CollectionProperty(type=FSS_AOOccluderRef)
    custom_index: bpy.props.IntProperty()


class FSS_AOApplySettings(bpy.types.PropertyGroup):
    target: bpy.props.EnumProperty(name="Target", default='FILE', items=[
        ('FILE', 'Separate File', 'A file of its own in the output folder'),
        ('ORM', 'ORM Texture', "The red channel of the texture in the material's ORM slot; green and blue stay")])
    file_name: bpy.props.StringProperty(name="File", default='', description="Empty: <material>_ao.png")
    resolution: bpy.props.EnumProperty(name="Resolution", items=RESOLUTION_ITEMS, default='ORM')
    layout: bpy.props.EnumProperty(name="Layout", default='GREY', items=[
        ('GREY', 'Greyscale', 'The AO in red, green and blue'),
        ('ORM', 'ORM', 'The AO in red; green and blue as chosen')])
    green_blue: bpy.props.EnumProperty(name="Green and Blue", default='WHITE', items=[
        ('WHITE', 'White', 'Empty: MSFS then uses the material\'s roughness and metallic factors'),
        ('COPY', 'From ORM Texture', "Roughness and metallic taken from the texture in the material's ORM slot")])
    sampling: bpy.props.EnumProperty(name="Sampling", default='AUTOMATIC', items=[
        ('AUTOMATIC', 'Automatic', 'The mean of the covered pixels when smaller, bilinear when larger'),
        ('NEAREST', 'Nearest', 'No in-between values: hard metallic edges stay hard'),
        ('BICUBIC', 'Bicubic', 'A sharper enlargement; may overshoot slightly at hard edges (clamped)')])


class FSS_AOSetRow(bpy.types.PropertyGroup):
    material: bpy.props.StringProperty()
    state: bpy.props.StringProperty()
    warn: bpy.props.BoolProperty()


class FSS_AOBakeState(bpy.types.PropertyGroup):
    """What the panel shows (written by Refresh, the bake's status and Apply; never while drawing)."""
    refreshed: bpy.props.BoolProperty()
    up_to_date: bpy.props.IntProperty()
    surroundings: bpy.props.IntProperty()
    mesh: bpy.props.IntProperty()
    missing: bpy.props.IntProperty()
    excluded: bpy.props.IntProperty()
    index_masters: bpy.props.IntProperty()
    running: bpy.props.BoolProperty()
    n_done: bpy.props.IntProperty()
    n_total: bpy.props.IntProperty()
    tile: bpy.props.IntProperty()
    n_tiles: bpy.props.IntProperty()
    pose: bpy.props.IntProperty()
    n_poses: bpy.props.IntProperty()
    current: bpy.props.StringProperty()
    elapsed: bpy.props.FloatProperty()
    left: bpy.props.FloatProperty(default=-1.0)
    report: bpy.props.StringProperty()
    apply_report: bpy.props.StringProperty()
    sets: bpy.props.CollectionProperty(type=FSS_AOSetRow)
    active_set: bpy.props.IntProperty()


def _state(context=None):
    return (context or bpy.context).window_manager.fss_ao_bake_state


def sync_state(context):
    """Copies the store's last refresh into the window manager's state for drawing."""
    st = _state(context)
    c = store.counts()
    st.refreshed = store._state['refreshed'] is not None
    st.up_to_date, st.surroundings, st.mesh, st.missing, st.excluded = (
        c['UP_TO_DATE'], c['SURROUNDINGS'], c['MESH'], c['MISSING'], c['EXCLUDED'])
    active = st.sets[st.active_set].material if 0 <= st.active_set < len(st.sets) else ''
    st.sets.clear()
    for name, row in sorted(store._state['sets'].items()):
        r = st.sets.add()
        r.material = name
        bad = row['MISSING'] + row['MESH']
        parts = []
        if bad:
            parts.append(f"{row['MISSING']} missing" if row['MISSING'] else '')
            parts.append(f"{row['MESH']} mesh changed" if row['MESH'] else '')
        if row['SURROUNDINGS']:
            parts.append(f"{row['SURROUNDINGS']} stale")
        parts = [p for p in parts if p]
        r.state = ', '.join(parts) if parts else f"{len(row['items'])} complete"
        r.warn = bool(parts)
    for i, r in enumerate(st.sets):
        if r.material == active:
            st.active_set = i


# The preview of the master being baked (decision 36): read from the runner's preview file by the progress timer (never
# while drawing) into an image preview of bpy.utils.previews, which is no datablock of the file and does not mark it
# changed. `updates` counts the images taken, `seq` is the runner's number of the last one.
_preview = dict(coll=None, seq=None, updates=0, size=(0, 0), digest='')


def preview_icon():
    """The icon id of the preview, or 0 (for drawing)."""
    coll = _preview['coll']
    if coll is None or 'master' not in coll or not _preview['updates']:
        return 0
    return coll['master'].icon_id


def update_preview(folder=None):
    """Takes a new preview image from the bake folder when the runner wrote one. Returns True when it changed."""
    folder = folder or store._run.get('folder')
    if not folder:
        return False
    got = core.read_preview(folder)
    if got is None or got[0] == _preview['seq']:
        return False
    seq, grey = got
    if _preview['coll'] is None:
        import bpy.utils.previews
        _preview['coll'] = bpy.utils.previews.new()
    coll = _preview['coll']
    pv = coll['master'] if 'master' in coll else coll.new('master')
    h, w = grey.shape
    rgba = np.ones((h, w, 4), np.float32)
    rgba[:, :, :3] = (grey.astype(np.float32) / 255.0)[:, :, None]
    pv.image_size = (w, h)
    pv.image_pixels_float.foreach_set(rgba.ravel())
    _preview.update(seq=seq, updates=_preview['updates'] + 1, size=(w, h),
                    digest=hashlib.sha1(grey.tobytes()).hexdigest()[:12])
    return True


def clear_preview():
    if _preview['coll'] is not None:
        import bpy.utils.previews
        bpy.utils.previews.remove(_preview['coll'])
    _preview.update(coll=None, seq=None, updates=0, size=(0, 0), digest='')


def read_index_on_open():
    st = _state()
    folder = store.bake_folder()
    st.index_masters = len(store.read_index(folder).get('masters', {})) if folder else 0


# ---------------------------------------------------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------------------------------------------------

class FSS_OT_AOBakeRefresh(bpy.types.Operator):
    bl_idname = 'fss.ao_bake_refresh'
    bl_label = 'Refresh'
    bl_description = "Compute the masters' hashes and states against the bake folder (links renamed objects again)"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        t = time.time()
        state = store.refresh(context)
        sync_state(context)
        read_index_on_open()
        msg = f"AO Bake: {len(state['items'])} masters checked in {time.time() - t:.1f} s"
        if state.get('relinked'):
            msg += f"; linked again: {', '.join(f'{a} -> {b}' for a, b in state['relinked'])}"
        self.report({'INFO'}, msg)
        return {'FINISHED'}


def _poll_timer():
    st = _state()
    status = store.read_status()
    if status:
        st.n_done = status.get('n_done', 0)
        st.n_total = status.get('n_total', 0)
        st.current = status.get('current', '')
        st.elapsed = status.get('elapsed_s', 0.0)
        st.left = status.get('left_s') if status.get('left_s') is not None else -1.0
        st.tile = status.get('tile', 0) or 0
        st.n_tiles = status.get('n_tiles', 0) or 0
        st.pose = status.get('pose', 0) or 0
        st.n_poses = status.get('n_poses', 0) or 0
    update_preview()
    if store.running():
        _redraw()
        return 0.5
    finish_bake()
    return None


def excluded_lines(limit=8):
    """The objects the last Refresh excluded, per reason (decision 30: also those without a face of a texture set)."""
    by = {}
    for name, why in sorted(store._state.get('excluded', {}).items()):
        by.setdefault(why, []).append(name)
    lines = []
    for why, names in sorted(by.items()):
        more = f' and {len(names) - limit} more' if len(names) > limit else ''
        lines.append(f"excluded ({why}): {len(names)}: {', '.join(names[:limit])}{more}")
        for name in names:
            print(f'AO Bake: excluded {name} ({why})')
    return lines


def finish_bake():
    st = _state()
    status = store.finish_run() or {}
    update_preview()
    st.running = False
    results = status.get('results', [])
    by = {}
    for r in results:
        by.setdefault(r['status'], []).append(r)
    lines = [f"{status.get('state', 'ended')}: {status.get('n_done', 0)} of {status.get('n_total', 0)} in "
             f"{status.get('elapsed_s', 0)} s; baked {len(by.get('baked', []))}"]
    if status.get('master_format') == 'png':  # decision 37: said once per bake
        lines.append(f"masters written as PNG: the JPEG XL library could not be loaded ({status.get('jxl_error')})")
    for kind in ('skipped', 'failed', 'cancelled'):
        for r in by.get(kind, []):
            lines.append(f"{kind}: {r['name']} ({r.get('reason', '')})")
    for r in by.get('baked', []):  # decision 34: a mover not baked in its poses, and why
        if r.get('note'):
            lines.append(f"{r['name']}: {r['note']}")
    lines += excluded_lines()
    st.report = '\n'.join(lines)
    sync_state(bpy.context)
    read_index_on_open()
    _redraw()


class FSS_OT_AOBakeStart(bpy.types.Operator):
    bl_idname = 'fss.ao_bake_start'
    bl_label = 'Bake'
    bl_description = ("Bake masters in a second Blender on the saved file; this Blender and its scene are not touched. "
                      "The bake reads the last saved state")
    bl_options = {'REGISTER'}

    scope: bpy.props.EnumProperty(items=[('STALE', 'Missing and Stale', ''), ('SELECTED', 'Selected', '')],
                                  default='STALE')
    hidden: bpy.props.BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})  # tests: hidden, whatever the run mode
    wait: bpy.props.BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})  # tests: return when done
    test_delay: bpy.props.FloatProperty(default=0.0, options={'HIDDEN', 'SKIP_SAVE'})  # tests: pause per object
    test_tile_delay: bpy.props.FloatProperty(default=0.0, options={'HIDDEN', 'SKIP_SAVE'})  # tests: pause per tile
    tile: bpy.props.IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})  # tests: force the tile size

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and bool(bpy.data.filepath) and not store.running()

    def execute(self, context):
        store.refresh(context)
        sync_state(context)
        items = store._state['items']
        if self.scope == 'SELECTED':
            stems = store.items_for_objects(context.selected_objects)
        else:
            stems = [s for s, it in sorted(items.items(), key=lambda kv: kv[1]['name']) if it['grade'] != 'UP_TO_DATE']
        if not stems:
            self.report({'INFO'}, 'AO Bake: nothing to bake')
            return {'CANCELLED'}
        job = store.make_job(context, stems, self.test_delay, self.tile, self.test_tile_delay)
        hidden = self.hidden or context.scene.fss_ao_bake.run_mode == 'HIDDEN'  # decision 36
        clear_preview()
        proc = store.start_bake(job, hidden=hidden)
        st = _state(context)
        st.running, st.n_done, st.n_total, st.current, st.report = True, 0, len(stems), '', ''
        st.tile = st.n_tiles = st.pose = st.n_poses = 0
        if self.wait:
            proc.wait()
            finish_bake()
        elif not bpy.app.timers.is_registered(_poll_timer):
            bpy.app.timers.register(_poll_timer, first_interval=0.5)
        self.report({'INFO'}, f'AO Bake: {len(stems)} masters in a second Blender')
        return {'FINISHED'}


class FSS_OT_AOBakeCancel(bpy.types.Operator):
    bl_idname = 'fss.ao_bake_cancel'
    bl_label = 'Cancel'
    bl_description = ('Stop the bake after the current tile; the finished masters are kept, the object being baked '
                      'keeps its old master')
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return store.running()

    def execute(self, context):
        store.cancel()
        return {'FINISHED'}


class FSS_OT_AOBakeSelect(bpy.types.Operator):
    bl_idname = 'fss.ao_bake_select'
    bl_label = 'Select'
    bl_description = 'Select the objects whose master is in this state (from the last Refresh)'
    bl_options = {'REGISTER', 'UNDO'}

    which: bpy.props.EnumProperty(items=[('STALE', 'Stale', ''), ('MISSING', 'Missing', '')], default='STALE')

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and store._state['refreshed'] is not None

    def execute(self, context):
        grades = {'STALE': ('MESH', 'SURROUNDINGS'), 'MISSING': ('MISSING',)}[self.which]
        names = {n for it in store._state['items'].values() if it['grade'] in grades for n in it['users']}
        for obj in context.view_layer.objects:
            obj.select_set(obj.name in names)
        self.report({'INFO'}, f'{len(names)} objects selected')
        return {'FINISHED'}


def _active_mesh(context):
    obj = context.active_object
    return obj if obj is not None and obj.type == 'MESH' else None


class FSS_OT_AOCustomOccluders(bpy.types.Operator):
    bl_idname = 'fss.ao_bake_custom_occluders'
    bl_label = 'Custom Occluders'
    bl_description = "Edit the active object's list of occluders"
    bl_options = {'REGISTER', 'UNDO'}

    action: bpy.props.EnumProperty(items=[
        ('ADD', 'Add Selected', 'Add the selected objects (but the active one) to the list'),
        ('REMOVE', 'Remove', 'Remove the highlighted object from the list'),
        ('CLEAR', 'Clear', 'Empty the list')], default='ADD')

    @classmethod
    def description(cls, context, properties):
        return {'ADD': "Add the selected objects (but the active one) to the active object's occluders",
                'REMOVE': 'Remove the highlighted object from the list',
                'CLEAR': "Empty the active object's list of occluders"}[properties.action]

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and _active_mesh(context) is not None

    def execute(self, context):
        obj = _active_mesh(context)
        s = obj.fss_ao_bake
        if self.action == 'ADD':
            have = {r.object for r in s.custom if r.object is not None}
            added = 0
            for o in context.selected_objects:
                if o != obj and o.type == 'MESH' and o not in have:
                    s.custom.add().object = o
                    added += 1
            self.report({'INFO'}, f'{added} added to the occluders of {obj.name}')
        elif self.action == 'REMOVE':
            if 0 <= s.custom_index < len(s.custom):
                s.custom.remove(s.custom_index)
                s.custom_index = min(s.custom_index, len(s.custom) - 1)
        else:
            s.custom.clear()
        return {'FINISHED'}


class FSS_OT_AOApply(bpy.types.Operator):
    bl_idname = 'fss.ao_apply'
    bl_label = 'Apply'
    bl_description = "Copy the masters into the texture set's AO target (writes files only)"
    bl_options = {'REGISTER'}

    scope: bpy.props.EnumProperty(items=[('SET', 'Texture Set', ''), ('ALL', 'All', ''),
                                         ('SELECTED', 'Selected', '')], default='SET')
    material: bpy.props.StringProperty(options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and store._state['refreshed'] is not None and bool(bpy.data.filepath)

    def execute(self, context):
        sets = store._state['sets']
        objects = None
        if self.scope == 'SET':
            names = [self.material] if self.material in sets else []
            if names and self.material in bpy.data.materials:
                problem = target_problem(context, bpy.data.materials[self.material])
                if problem:
                    self.report({'ERROR'}, f'AO Apply: {self.material}: {problem}')
                    return {'CANCELLED'}
        elif self.scope == 'ALL':
            names = sorted(sets)
        else:
            objects = list(context.selected_objects)
            stems = set(store.items_for_objects(objects))
            names = sorted(n for n, row in sets.items() if stems & set(row['items']))
        materials = [bpy.data.materials[n] for n in names if n in bpy.data.materials]
        if not materials:
            self.report({'WARNING'}, 'AO Apply: no texture set')
            return {'CANCELLED'}
        reports = apply_mod.apply(context, materials, objects)
        lines = [line for rep in reports for line in apply_mod.report_lines(rep)]
        _state(context).apply_report = '\n'.join(lines)
        self._reports = reports
        for line in lines:
            print('AO Apply:', line)
        self.report({'WARNING'} if any(r.get('error') for r in reports) else {'INFO'},
                    f'AO Apply: {len(reports)} texture set(s)')
        return {'FINISHED'}


# ---------------------------------------------------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------------------------------------------------

def selected_sets(context):
    """The texture sets of the selected objects' masters (from the last Refresh); None when nothing is selected."""
    objs = list(getattr(context, 'selected_objects', None) or [])
    if not objs:
        return None
    items = store._state['items']
    return {m for s in store.items_for_objects(objs) if s in items for m in items[s]['sets']}


def apply_material(context, st):
    """The texture set the Apply box is for: the only one of the selection, else the highlighted row when the list
    shows it; None when there is no such row."""
    sel = selected_sets(context)
    shown = [r.material for r in st.sets if sel is None or r.material in sel]
    if sel is not None and len(shown) == 1:
        name = shown[0]
    else:
        row = st.sets[st.active_set] if 0 <= st.active_set < len(st.sets) else None
        name = row.material if row is not None and row.material in shown else None
    return bpy.data.materials.get(name) if name else None


def target_problem(context, material):
    """Why Apply cannot write this texture set's target, or '' (the ORM texture's file, or the output folder)."""
    a = material.fss_ao_apply
    if a.target == 'ORM':
        orm = apply_mod.orm_image(material)
        if orm is None:
            return 'No texture in the ORM slot'
        path = apply_mod.image_path(orm)
        if not path or not os.path.isfile(path):
            return f'ORM texture file not found: {path or orm.name}'
        return ''
    folder = apply_mod.output_folder(context.scene)
    if not (os.path.isdir(folder) or os.path.isdir(os.path.dirname(folder.rstrip('\\/')))):
        return f'Output folder cannot be made: {folder}'
    return ''


class FSS_UL_AOSets(bpy.types.UIList):
    """The texture sets; with objects selected, only theirs."""

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.label(text=item.material, icon='MATERIAL')
        sub = row.row()
        sub.alert = item.warn
        sub.label(text=item.state, icon='ERROR' if item.warn else 'CHECKMARK')

    def filter_items(self, context, data, propname):
        sel = selected_sets(context)
        rows = getattr(data, propname)
        return [self.bitflag_filter_item if (sel is None or r.material in sel) else 0 for r in rows], []


class FSS_UL_AOOccluders(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if item.object is None:
            layout.label(text='(deleted)', icon='ERROR')
        else:
            layout.label(text=item.object.name, icon='OBJECT_DATA')


def _draw_object(layout, context):
    """The active object's overrides (decisions 34 and 35)."""
    obj = _active_mesh(context)
    if obj is None:
        return
    scene = context.scene
    box = layout.box()
    box.label(text=f'Object: {obj.name}', icon='OBJECT_DATA')
    o = obj.fss_ao_bake
    col = box.column(align=True)
    col.prop(o, 'occluders')
    if store.is_mover(obj, scene):
        rng = store.mover_range(obj)
        n = store.pose_count(obj, scene)
        if rng is None:
            col.label(text='Moves, without keys: baked in the current frame', icon='INFO')
        elif store.occluder_mode(obj, scene) == 'SELF':
            col.label(text=f'Moves over frames {rng[0]:g} to {rng[1]:g}; Self Only: one pose', icon='INFO')
        else:
            col.label(text=f'Moves over frames {rng[0]:g} to {rng[1]:g}: {n} pose{"s" if n != 1 else ""}', icon='INFO')
            row = col.row(align=True)
            row.prop(o, 'own_poses')
            if o.own_poses:
                row.prop(o, 'poses', text='Poses')
            else:
                row.label(text=f'Default: {scene.fss_ao_bake.poses}')
    if o.occluders == 'CUSTOM':
        box.template_list('FSS_UL_AOOccluders', '', o, 'custom', o, 'custom_index', rows=3)
        row = box.row(align=True)
        row.operator('fss.ao_bake_custom_occluders', text='Add Selected', icon='ADD').action = 'ADD'
        row.operator('fss.ao_bake_custom_occluders', text='Remove', icon='REMOVE').action = 'REMOVE'
        row.operator('fss.ao_bake_custom_occluders', text='Clear', icon='X').action = 'CLEAR'


def _lines(layout, text, icon='NONE'):
    for i, line in enumerate(text.splitlines()):
        layout.label(text=line, icon=icon if i == 0 else 'BLANK1')


def _fmt_time(seconds):
    seconds = max(0, int(seconds))
    return f'{seconds // 60}:{seconds % 60:02d}'


class FSS_PT_AOBake(bpy.types.Panel):
    bl_idname = 'FSS_PT_ao_bake'
    bl_label = 'AO Bake'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'FSS MSFS Tools'
    bl_order = 8

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        s = scene.fss_ao_bake
        st = _state(context)
        box = layout.box()
        box.label(text='Bake', icon='RENDER_STILL')
        col = box.column(align=True)
        col.prop(s, 'distance')
        col.prop(s, 'samples')
        row = col.row(align=True)
        row.prop(s, 'device', expand=True)
        if s.device == 'CPU':
            col.prop(s, 'threads')
        col.prop(s, 'poses')
        col.prop(s, 'occluders')
        row = col.row(align=True)
        row.label(text='Bake Window')
        row.prop(s, 'run_mode', expand=True)
        _draw_object(box, context)
        if not bpy.data.filepath:
            box.label(text='Save the file first: the bake reads the saved file', icon='ERROR')
        elif bpy.data.is_dirty:
            box.label(text='Unsaved changes: the bake reads the last saved state', icon='ERROR')
        box.operator('fss.ao_bake_refresh', icon='FILE_REFRESH')
        if st.refreshed:
            grid = box.column(align=True)
            for label, value in (('Up to date', st.up_to_date), ('Surroundings changed', st.surroundings),
                                 ('Mesh changed', st.mesh), ('Missing', st.missing), ('Excluded', st.excluded)):
                r = grid.row()
                r.label(text=label)
                r.label(text=str(value))
        else:
            box.label(text=f'{st.index_masters} masters in the bake folder; Refresh to compare', icon='INFO')
        if st.running:
            col = box.column(align=True)
            col.progress(factor=st.n_done / max(st.n_total, 1),
                         text=f'Object {min(st.n_done + 1, st.n_total)} of {st.n_total}')
            col.label(text=st.current or '...')
            if st.n_tiles > 1:
                col.label(text=f'Tile {st.tile} of {st.n_tiles}')
            if st.n_poses > 1:
                col.label(text=f'Pose {max(st.pose, 1)} of {st.n_poses}')
            left = _fmt_time(st.left) if st.left >= 0 else '-'
            col.label(text=f'Spent {_fmt_time(st.elapsed)}, left {left}')
            col.operator('fss.ao_bake_cancel', icon='CANCEL')
        icon = preview_icon()
        if icon:
            box.template_icon(icon_value=icon, scale=8.0)
        else:
            row = box.row(align=True)
            op = row.operator('fss.ao_bake_start', text='Bake Missing and Stale')
            op.scope = 'STALE'
            op = row.operator('fss.ao_bake_start', text='Bake Selected')
            op.scope = 'SELECTED'
            row = box.row(align=True)
            row.operator('fss.ao_bake_select', text='Select Stale').which = 'STALE'
            row.operator('fss.ao_bake_select', text='Select Missing').which = 'MISSING'
        if st.report:
            _lines(box.column(align=True), st.report, 'INFO')
        box = layout.box()
        box.label(text='Apply', icon='TEXTURE')
        col = box.column(align=True)
        col.prop(s, 'padding')
        col.prop(s, 'output_folder')
        if not st.refreshed:
            box.label(text='Refresh first', icon='INFO')
            return
        sel = selected_sets(context)
        if sel is not None:
            box.label(text=f'Texture sets of the selection: {len(sel)} (none selected: all)', icon='RESTRICT_SELECT_OFF')
        box.template_list('FSS_UL_AOSets', '', st, 'sets', st, 'active_set', rows=4)
        material = apply_material(context, st)
        problem = ''
        if material is None:
            box.label(text='Pick a texture set in the list', icon='INFO')
        else:
            a = material.fss_ao_apply
            sub = box.column(align=True)
            sub.label(text=f'Texture set: {material.name}', icon='MATERIAL')
            sub.prop(a, 'target', expand=True)
            orm = apply_mod.orm_image(material)
            problem = target_problem(context, material)
            if a.target == 'ORM':
                if orm is not None:
                    sub.label(text=f'ORM texture: {orm.name}', icon='IMAGE_DATA')
                if problem:
                    sub.label(text=problem, icon='ERROR')
                else:
                    sub.label(text='Red is written; green and blue kept')
                    if orm.depth and orm.depth < 48 and not orm.is_float:
                        sub.label(text='8-bit file: written as 16-bit, green and blue kept', icon='ERROR')
                    sub.label(text='The next ORM export from Substance replaces red again', icon='ERROR')
            else:
                sub.prop(a, 'file_name')
                sub.prop(a, 'resolution')
                sub.prop(a, 'layout', expand=True)
                if a.layout == 'ORM':
                    sub.prop(a, 'green_blue')
                    if a.green_blue == 'COPY':
                        if orm is None:
                            sub.label(text='No ORM texture: green and blue white', icon='ERROR')
                        elif a.resolution != 'ORM' and tuple(orm.size) != (int(a.resolution), int(a.resolution)):
                            sub.label(text="Another size: roughness and metallic are resampled", icon='ERROR')
                            sub.prop(a, 'sampling')
                if problem:
                    sub.label(text=problem, icon='ERROR')
        row = box.row(align=True)
        cell = row.row(align=True)
        cell.enabled = material is not None and not problem  # the set's Apply only when its target can be written
        op = cell.operator('fss.ao_apply', text='Apply')
        op.scope = 'SET'
        op.material = material.name if material is not None else ''
        row.operator('fss.ao_apply', text='Apply All').scope = 'ALL'
        row.operator('fss.ao_apply', text='Apply Selected').scope = 'SELECTED'
        if st.apply_report:
            _lines(box.column(align=True), st.apply_report, 'INFO')


@persistent
def _on_load_post(*_args):
    store._state.update(items={}, by_object={}, excluded={}, sets={}, refreshed=None, folder=None)
    try:
        wm = bpy.context.window_manager
        st = wm.fss_ao_bake_state
        st.refreshed = False
        st.sets.clear()
        st.report = st.apply_report = ''
        read_index_on_open()
    except AttributeError:
        pass


CLASSES = (FSS_AOBakeSettings, FSS_AOOccluderRef, FSS_AOObjectSettings, FSS_AOApplySettings, FSS_AOSetRow,
           FSS_AOBakeState, FSS_OT_AOBakeRefresh, FSS_OT_AOBakeStart, FSS_OT_AOBakeCancel, FSS_OT_AOBakeSelect,
           FSS_OT_AOCustomOccluders, FSS_OT_AOApply, FSS_UL_AOSets, FSS_UL_AOOccluders, FSS_PT_AOBake)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.fss_ao_bake = bpy.props.PointerProperty(type=FSS_AOBakeSettings)
    bpy.types.Object.fss_ao_bake = bpy.props.PointerProperty(type=FSS_AOObjectSettings)
    bpy.types.Material.fss_ao_apply = bpy.props.PointerProperty(type=FSS_AOApplySettings)
    bpy.types.WindowManager.fss_ao_bake_state = bpy.props.PointerProperty(type=FSS_AOBakeState)
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)


def unregister():
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    if bpy.app.timers.is_registered(_poll_timer):
        bpy.app.timers.unregister(_poll_timer)
    clear_preview()
    del bpy.types.WindowManager.fss_ao_bake_state
    del bpy.types.Object.fss_ao_bake
    del bpy.types.Material.fss_ao_apply
    del bpy.types.Scene.fss_ao_bake
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
