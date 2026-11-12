"""AO Bake panel (auto-bake journal, decision 29 and P46): bake masters in a second Blender, apply them to textures.

FSS MSFS Tools > AO Bake:
- Bake: AO distance (scene, decision 16), samples, device; the masters' counts (up to date, surroundings changed,
  mesh changed, missing, excluded); Bake Missing and Stale, Bake Selected, Select Stale, Select Missing; while a bake
  runs, object n of m, its name, time spent and left, Cancel; a warning when the .blend has unsaved changes (the bake
  reads the saved file); the report of the last bake.
- Apply: padding and output folder; a row per texture set with its state (masters complete, or the number missing or
  stale; faces under 4 x); for the active row: target (ORM slot texture or separate file) and the separate file's
  name, resolution, layout, green and blue, sampling; the warnings; Apply, Apply All, Apply Selected.
The panel draws without writing: the hashes are computed by Refresh (and before a bake), index.json is read when a
file opens and after a bake.
"""

import os
import time

import bpy
from bpy.app.handlers import persistent

from . import ao_bake_apply as apply_mod
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
    if store.running():
        _redraw()
        return 0.5
    finish_bake()
    return None


def finish_bake():
    st = _state()
    status = store.finish_run() or {}
    st.running = False
    results = status.get('results', [])
    by = {}
    for r in results:
        by.setdefault(r['status'], []).append(r)
    lines = [f"{status.get('state', 'ended')}: {status.get('n_done', 0)} of {status.get('n_total', 0)} in "
             f"{status.get('elapsed_s', 0)} s; baked {len(by.get('baked', []))}"]
    for kind in ('skipped', 'failed'):
        for r in by.get(kind, []):
            lines.append(f"{kind}: {r['name']} ({r.get('reason', '')})")
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
    hidden: bpy.props.BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})  # tests: no window
    wait: bpy.props.BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})  # tests: return when done
    test_delay: bpy.props.FloatProperty(default=0.0, options={'HIDDEN', 'SKIP_SAVE'})  # tests: pause per object

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
        job = store.make_job(context, stems, self.test_delay)
        proc = store.start_bake(job, hidden=self.hidden)
        st = _state(context)
        st.running, st.n_done, st.n_total, st.current, st.report = True, 0, len(stems), '', ''
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
    bl_description = 'Stop the bake after the current object; the finished masters are kept'
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

class FSS_UL_AOSets(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.label(text=item.material, icon='MATERIAL')
        sub = row.row()
        sub.alert = item.warn
        sub.label(text=item.state, icon='ERROR' if item.warn else 'CHECKMARK')


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
            left = _fmt_time(st.left) if st.left >= 0 else '-'
            col.label(text=f'Spent {_fmt_time(st.elapsed)}, left {left}')
            col.operator('fss.ao_bake_cancel', icon='CANCEL')
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
        box.template_list('FSS_UL_AOSets', '', st, 'sets', st, 'active_set', rows=4)
        row_set = st.sets[st.active_set] if 0 <= st.active_set < len(st.sets) else None
        material = bpy.data.materials.get(row_set.material) if row_set else None
        if material is not None:
            a = material.fss_ao_apply
            sub = box.column(align=True)
            sub.prop(a, 'target', expand=True)
            orm = apply_mod.orm_image(material)
            if a.target == 'ORM':
                if orm is None:
                    sub.label(text='No texture in the ORM slot', icon='ERROR')
                else:
                    sub.label(text=f'{os.path.basename(orm.filepath)}: red only, green and blue kept')
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
            row = box.row(align=True)
            op = row.operator('fss.ao_apply', text='Apply')
            op.scope = 'SET'
            op.material = material.name
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


CLASSES = (FSS_AOBakeSettings, FSS_AOApplySettings, FSS_AOSetRow, FSS_AOBakeState, FSS_OT_AOBakeRefresh,
           FSS_OT_AOBakeStart, FSS_OT_AOBakeCancel, FSS_OT_AOBakeSelect, FSS_OT_AOApply, FSS_UL_AOSets,
           FSS_PT_AOBake)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.fss_ao_bake = bpy.props.PointerProperty(type=FSS_AOBakeSettings)
    bpy.types.Material.fss_ao_apply = bpy.props.PointerProperty(type=FSS_AOApplySettings)
    bpy.types.WindowManager.fss_ao_bake_state = bpy.props.PointerProperty(type=FSS_AOBakeState)
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)


def unregister():
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    if bpy.app.timers.is_registered(_poll_timer):
        bpy.app.timers.unregister(_poll_timer)
    del bpy.types.WindowManager.fss_ao_bake_state
    del bpy.types.Material.fss_ao_apply
    del bpy.types.Scene.fss_ao_bake
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
