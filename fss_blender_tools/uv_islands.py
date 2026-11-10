"""The island list of the active object, below UV Auto Packing's table: every island as the packer forms it, with
its multiplier and density, so an artist can see what Pack will give each island before packing. A click on a column's
title sorts by it, highest first, and a second click reverses; a bar under each number shows it against the list's largest.
A click on a row, or Select Faces for the row already active, enters Edit Mode and selects the island's faces; nothing
else is changed.

Set and Clear give the ticked islands a multiplier by hand, stored on their faces (uv_marks.set_face_overrides). A density
in px/cm is turned into that multiplier when set, against the scene's target density; only the multiplier is stored.

The rows come from uv_pack.object_islands, so they are the packer's own values. A panel may not write while drawing, so
the draw compares a key and a timer fills the rows right after it (as visibility.schedule_light_sync). The list is
closed by default and costs nothing until opened. In Edit Mode the mesh's own data is not current, so the rows stay as
they were when Edit Mode was entered.
"""

from pathlib import Path

import bmesh
import bpy
import numpy as np
from bpy.app.handlers import persistent

from . import uv_marks, uv_pack

LIST_ROWS = 5
NO_AREA = ('no UV area', 'no 3D area')
ROW_TEXT_SCALE = 0.72  # a row holds its number and, under it, a bar: together one list row high
ROW_BAR_SCALE = 0.28
DETAIL_SCALE = 0.8  # the details below the list, closer together
SORT_ITEMS = (('AREA', 'Area', 'Sort by the area on the model'),
              ('MULTIPLIER', 'Multiplier', 'Sort by the multiplier'),
              ('DENSITY', 'Density px/cm', 'Sort by the density'))
OVERRIDE_KINDS = (('MULTIPLIER', 'Multiplier', 'Give the ticked islands this multiplier'),
                  ('DENSITY', 'Density px/cm', 'Give the ticked islands this density: stored as a multiplier of the target density'))
_state = {'key': None, 'object': None, 'mesh': None, 'faces': [], 'stale': False, 'users': 1, 'nf': 0, 'error': '',
          'largest': {'AREA': 1.0, 'MULTIPLIER': 1.0, 'DENSITY': 1.0}}
_generation = 0  # raised by a geometry change of the listed mesh and by opening a file
_pending = False
_syncing = False  # the rows are being filled: setting the active row is not a click


class FSS_UvIslandRow(bpy.types.PropertyGroup):
    """One island in the list. `name` (number and material) is what the list's filter field searches."""
    number: bpy.props.IntProperty()
    material: bpy.props.StringProperty()
    kept: bpy.props.BoolProperty()
    area: bpy.props.FloatProperty()
    factor: bpy.props.FloatProperty()  # the visibility multiplier alone
    multiplier: bpy.props.FloatProperty()  # the island's top density over the target: every mark, visibility and facing
    low: bpy.props.FloatProperty()
    high: bpy.props.FloatProperty()
    now: bpy.props.FloatProperty()
    seen: bpy.props.FloatProperty(default=-1.0)  # the seen share of the surface, below 0 without visibility data
    facing: bpy.props.FloatProperty(default=-1.0)  # 0 facing away to 1 facing the cameras, below 0 without facing data
    faces: bpy.props.IntProperty()
    status: bpy.props.StringProperty()
    ticked: bpy.props.BoolProperty(name='Tick', description='Set and Clear below act on the ticked islands')
    override: bpy.props.FloatProperty()  # the multiplier set by hand, 0 for none
    override_mixed: bpy.props.BoolProperty()  # the island's faces do not all have that multiplier


def _key(obj, scene):
    """What the rows depend on, cheap enough for every redraw."""
    me = obj.data
    layer = me.uv_layers.active
    vis_path = Path(bpy.data.filepath).with_suffix('.visibility') if bpy.data.filepath else None
    try:
        mtime = vis_path.stat().st_mtime if vis_path is not None else None
    except OSError:
        mtime = None
    materials = [slot.material for slot in obj.material_slots if slot.material is not None]
    overrides = uv_marks.face_overrides(me)
    return (_generation, obj.name, me.name, len(me.polygons), layer.name if layer else '', mtime,
            None if overrides is None else hash(overrides.tobytes()), uv_marks.density(obj, scene)[0], uv_marks.uses_visibility(obj), uv_marks.target_density(scene), uv_marks.partly_seen(scene),
            tuple((uv_marks.texture_size(m), uv_pack.is_kept(m), uv_marks.material_density(m), id(uv_marks._results.get(m.name))) for m in materials))


def sync(obj, scene, view_layer, wm):
    """Fill the rows of obj. Not from a draw."""
    global _syncing
    key = _key(obj, scene)
    active = wm.fss_uv_island_rows[wm.fss_uv_island_active].number if (
        _state['object'] == obj.name and 0 <= wm.fss_uv_island_active < len(wm.fss_uv_island_rows)) else None
    # ticks go by the island's first face: its number can change with a refill
    ticked = set()
    if _state['object'] == obj.name and len(_state['faces']) == len(wm.fss_uv_island_rows):
        ticked = {int(faces[0]) for item, faces in zip(wm.fss_uv_island_rows, _state['faces']) if item.ticked and len(faces)}
    error = ''
    try:
        found = uv_pack.object_islands(obj, scene, view_layer)
    except Exception as ex:  # a redraw must not ask again and again: the list says what went wrong
        found, error = None, str(ex)
    rows, users, stale = found if found is not None else ([], [obj], False)
    for number, row in enumerate(rows, 1):
        row['number'] = number
    rows.sort(key=lambda r: (r['status'] in NO_AREA, -r['high'], -r['area'], r['number']))
    _state.update(key=key, object=obj.name, mesh=obj.data.name, stale=stale, users=len(users), error=error,
                  nf=len(obj.data.polygons), faces=[row['faces'] for row in rows])
    _syncing = True
    try:
        items = wm.fss_uv_island_rows
        items.clear()
        index = 0
        for position, row in enumerate(rows):
            item = items.add()
            material = row['material']
            name = material.name if material is not None else '(no material)'
            item.name = f"{row['number']} {name}"
            item.number = row['number']
            item.material = name
            item.kept = uv_pack.is_kept(material)
            item.area = row['area']
            item.factor = row['factor']
            item.multiplier = row['high'] / max(uv_marks.target_density(scene), 1e-9)
            item.low = row['low']
            item.high = row['high']
            item.now = row['now']
            item.seen = -1.0 if row['seen'] is None else row['seen']
            item.facing = -1.0 if row['facing'] is None else row['facing']
            item.faces = len(row['faces'])
            item.status = row['status']
            item.override = row['override']
            item.override_mixed = row['override_mixed']
            item.ticked = len(row['faces']) > 0 and int(row['faces'][0]) in ticked and can_override(item)
            if row['number'] == active:
                index = position
        wm.fss_uv_island_active = index
        _state['largest'] = {key: max((value(item) for item in items), default=1.0) for key, value in _SORT_VALUES.items()}
    finally:
        _syncing = False


def _schedule(obj, scene, view_layer, wm):
    """Panels may not write while drawing: fill the rows once, right after the draw. A timer has no active object, so
    the names go with it."""
    global _pending
    if _pending:
        return
    _pending = True
    names = (obj.name, scene.name, view_layer.name)

    def run():
        global _pending
        _pending = False
        target = bpy.data.objects.get(names[0])
        target_scene = bpy.data.scenes.get(names[1])
        if target is None or target_scene is None or names[2] not in target_scene.view_layers \
                or not hasattr(bpy.types.WindowManager, 'fss_uv_island_rows'):
            return None
        sync(target, target_scene, target_scene.view_layers[names[2]], bpy.context.window_manager)
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type in ('VIEW_3D', 'IMAGE_EDITOR'):
                    area.tag_redraw()
        return None

    bpy.app.timers.register(run, first_interval=0.0)


def can_override(row):
    """Pack leaves a kept set's islands and islands without an area alone, so a value would do nothing."""
    return not row.kept and row.status not in NO_AREA


def density_value(row):
    """The density as a number, for sorting and the bar: the last Pack or Check All of the set, else the top of the range;
    0 for an island that has none."""
    if row.kept or row.status in NO_AREA:
        return 0.0
    result = uv_marks._results.get(row.material)
    t = result.get('t') if result else None
    return row.low + t * (row.high - row.low) if t is not None else row.high


_SORT_VALUES = {'AREA': lambda row: row.area, 'MULTIPLIER': lambda row: row.multiplier, 'DENSITY': density_value}


def island_order(rows, sort_by, reverse):
    """Each row's position in the list, as UIList.filter_items wants it: the sorted column highest first (lowest when
    reversed), islands without an area always last. The rows keep their indices, so a selection stays right."""
    value = _SORT_VALUES[sort_by]
    sign = 1.0 if reverse else -1.0
    shown = sorted(range(len(rows)), key=lambda i: (rows[i].status in NO_AREA, sign * value(rows[i]), rows[i].number))
    order = [0] * len(shown)
    for position, index in enumerate(shown):
        order[index] = position
    return order


def density_text(row):
    """The Density column: the density of the last Pack or Check All of the set when there is one, else the range."""
    if row.kept:
        return 'kept'
    if row.status in NO_AREA:
        return row.status
    result = uv_marks._results.get(row.material)
    t = result.get('t') if result else None
    if t is not None:
        return f'{row.low + t * (row.high - row.low):.2f}'
    return f'{row.low:.2f}' if row.high - row.low < 5e-3 else f'{row.low:.2f} - {row.high:.2f}'


def _area_text(area):
    return f'{area:.1f} cm²' if area < 10000 else f'{area / 10000:.2f} m²'


def _cells(layout):
    """The list's four columns, the same in the header and the rows: each split holds a cell and the next split."""
    split = layout.split(factor=0.2)
    number = split.column()
    split = split.split(factor=0.24)
    area = split.column()
    split = split.split(factor=0.30)
    return number, area, split.column(), split.column()


def _value_cell(cell, text, fraction=None, icon='NONE'):
    """A number with, under it, a bar of fraction of the cell's width (no bar for None)."""
    column = cell.column(align=True)
    top = column.column(align=True)
    top.scale_y = ROW_TEXT_SCALE
    top.label(text=text, icon=icon)
    if fraction is not None:
        bar = column.column(align=True)
        bar.scale_y = ROW_BAR_SCALE
        bar.progress(factor=max(0.0, min(fraction, 1.0)), type='BAR', text=' ')  # a blank: no text on the bar


def _share(row, key):
    value = _SORT_VALUES[key](row)
    return value / _state['largest'][key] if _state['largest'][key] > 0.0 else 0.0


class FSS_UL_UvIslands(bpy.types.UIList):
    bl_idname = 'FSS_UL_uv_islands'

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        number, area, multiplier, density = _cells(layout)
        line = number.row(align=True)
        line.scale_y = ROW_TEXT_SCALE
        if can_override(item):
            line.prop(item, 'ticked', text='')
        line.label(text=str(item.number))
        _value_cell(area, _area_text(item.area), _share(item, 'AREA'))
        icon = 'NONE' if item.override <= 0.0 else 'ERROR' if item.override_mixed else 'PINNED'
        _value_cell(multiplier, f'x{item.multiplier:.2f}', _share(item, 'MULTIPLIER'), icon=icon)
        has_density = not (item.kept or item.status in NO_AREA)
        _value_cell(density, density_text(item), _share(item, 'DENSITY') if has_density else None)

    def filter_items(self, context, data, propname):
        rows = getattr(data, propname)
        wm = context.window_manager
        flags = []
        if self.filter_name:
            flags = bpy.types.UI_UL_list.filter_items_by_name(self.filter_name, self.bitflag_filter_item, rows, 'name',
                                                              reverse=self.use_filter_invert)
        return flags, island_order(rows, wm.fss_uv_island_sort, wm.fss_uv_island_sort_reverse)


class FSS_OT_UvIslandSort(bpy.types.Operator):
    bl_idname = 'fss.uv_island_sort'
    bl_label = 'Sort Islands'
    bl_description = 'Sort the list by this column, highest first; click again to reverse'
    bl_options = {'INTERNAL'}

    sort_by: bpy.props.EnumProperty(items=SORT_ITEMS)

    def execute(self, context):
        wm = context.window_manager
        if wm.fss_uv_island_sort == self.sort_by:
            wm.fss_uv_island_sort_reverse = not wm.fss_uv_island_sort_reverse
        else:
            wm.fss_uv_island_sort = self.sort_by
            wm.fss_uv_island_sort_reverse = False
        return {'FINISHED'}


def _draw_header(layout, wm):
    number, *columns = _cells(layout)
    number.label(text='#')
    for cell, (key, title, _description) in zip(columns, SORT_ITEMS):
        icon = 'NONE'
        if wm.fss_uv_island_sort == key:
            icon = 'TRIA_UP' if wm.fss_uv_island_sort_reverse else 'TRIA_DOWN'
        left = cell.row()
        left.alignment = 'LEFT'
        left.operator(FSS_OT_UvIslandSort.bl_idname, text=title, icon=icon, emboss=False).sort_by = key


def select_island(context, index):
    """Select the island's faces in Edit Mode (entered when needed). False when the list no longer fits the mesh."""
    obj = context.active_object
    if obj is None or obj.name != _state['object'] or not 0 <= index < len(_state['faces']):
        return False
    if obj.mode != 'EDIT':
        bpy.ops.object.mode_set(mode='EDIT')
    me = obj.data
    bm = bmesh.from_edit_mesh(me)
    if len(bm.faces) != _state['nf']:
        return False
    bm.faces.ensure_lookup_table()
    context.tool_settings.mesh_select_mode = (False, False, True)
    bm.select_mode = {'FACE'}
    for face in bm.faces:
        face.select_set(False)
    for face in _state['faces'][index].tolist():
        bm.faces[face].select_set(True)
    bm.select_flush_mode()
    bmesh.update_edit_mesh(me, loop_triangles=False, destructive=False)
    return True


def _row_clicked(wm, context):
    """A click on a row enters Edit Mode when needed and selects the island, to show which one the row is."""
    if _syncing or context.active_object is None:
        return
    try:
        select_island(context, wm.fss_uv_island_active)
    except RuntimeError as ex:  # a mode Blender cannot leave here: the row is still active, the details still show
        print(f'[FSS UV islands] could not select the island: {ex}')


class FSS_OT_UvIslandSelect(bpy.types.Operator):
    bl_idname = 'fss.uv_island_select'
    bl_label = 'Select Faces'
    bl_description = "Select the faces of the list's active island, in Edit Mode"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.name == _state['object']

    def execute(self, context):
        if not select_island(context, context.window_manager.fss_uv_island_active):
            self.report({'WARNING'}, 'The mesh changed: open the list again in Object Mode')
            return {'CANCELLED'}
        return {'FINISHED'}


def apply_override(context, value):
    """Give the ticked islands this multiplier, 0 to clear it. In Edit Mode the mesh's data is not current, so the island
    list is read again outside it first. Returns the number of islands changed, or None when the list is of another object."""
    obj = context.active_object
    wm = context.window_manager
    if obj is None or obj.name != _state['object']:
        return None
    was_editing = obj.mode == 'EDIT'
    if was_editing:
        bpy.ops.object.mode_set(mode='OBJECT')
    try:
        sync(obj, context.scene, context.view_layer, wm)
        rows = wm.fss_uv_island_rows
        chosen = [faces for row, faces in zip(rows, _state['faces']) if row.ticked and can_override(row)]
        if not chosen:
            return 0
        uv_marks.set_face_overrides(obj.data, np.concatenate(chosen), value)
        sync(obj, context.scene, context.view_layer, wm)
        return len(chosen)
    finally:
        if was_editing:
            bpy.ops.object.mode_set(mode='EDIT')


def _any_ticked(context):
    obj = context.active_object
    return (obj is not None and obj.name == _state['object']
            and any(row.ticked for row in context.window_manager.fss_uv_island_rows))


class FSS_OT_UvIslandOverrideSet(bpy.types.Operator):
    bl_idname = 'fss.uv_island_override_set'
    bl_label = 'Set'
    bl_description = ('Give the ticked islands this value: final for Pack, whatever the marks and the visibility say. '
                      'Tick islands in the list first')
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _any_ticked(context)

    def execute(self, context):
        wm = context.window_manager
        target = uv_marks.target_density(context.scene)
        value = wm.fss_uv_override_multiplier if wm.fss_uv_override_kind == 'MULTIPLIER' else wm.fss_uv_override_density / max(target, 1e-9)
        done = apply_override(context, value)
        if done is None:
            self.report({'WARNING'}, 'The list is of another object: open it again')
            return {'CANCELLED'}
        self.report({'INFO'}, f'{done} island(s) set to x{value:.3f}, {value * target:.2f} px/cm')
        return {'FINISHED'}


class FSS_OT_UvIslandOverrideClear(bpy.types.Operator):
    bl_idname = 'fss.uv_island_override_clear'
    bl_label = 'Clear'
    bl_description = 'The ticked islands go back to what the marks and the visibility give them. Tick islands in the list first'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _any_ticked(context)

    def execute(self, context):
        done = apply_override(context, 0.0)
        if done is None:
            self.report({'WARNING'}, 'The list is of another object: open it again')
            return {'CANCELLED'}
        self.report({'INFO'}, f'{done} island(s) cleared')
        return {'FINISHED'}


class FSS_OT_UvIslandUntick(bpy.types.Operator):
    bl_idname = 'fss.uv_island_untick'
    bl_label = 'Untick All'
    bl_description = 'Untick every island in the list'
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return _any_ticked(context)

    def execute(self, context):
        for row in context.window_manager.fss_uv_island_rows:
            row.ticked = False
        return {'FINISHED'}


def _draw_override(layout, wm, rows, scene):
    """Set by hand: what the ticked islands get, as a multiplier or a density."""
    target = uv_marks.target_density(scene)
    count = sum(1 for row in rows if row.ticked)
    box = layout.box().column(align=True)
    title = box.row(align=True)
    title.label(text=f'Set by hand: {count} ticked')
    title.operator(FSS_OT_UvIslandUntick.bl_idname, text='', icon='X')
    box.row(align=True).prop(wm, 'fss_uv_override_kind', expand=True)
    line = box.row(align=True)
    if wm.fss_uv_override_kind == 'MULTIPLIER':
        line.prop(wm, 'fss_uv_override_multiplier', text='')
        hint = f'{wm.fss_uv_override_multiplier * target:.2f} px/cm'
    else:
        line.prop(wm, 'fss_uv_override_density', text='')
        hint = f'x{wm.fss_uv_override_density / max(target, 1e-9):.3f}'
    line.label(text=hint)
    buttons = box.row(align=True)
    buttons.operator(FSS_OT_UvIslandOverrideSet.bl_idname, text='Set')
    buttons.operator(FSS_OT_UvIslandOverrideClear.bl_idname, text='Clear')


def _draw_details(layout, row):
    labelled = uv_marks._labelled
    details = layout.column(align=True)
    details.scale_y = DETAIL_SCALE
    labelled(details, 'Material').label(text=row.material)
    labelled(details, 'Faces').label(text=str(row.faces))
    if row.override > 0.0:
        labelled(details, 'Set by hand').label(text=f'x{row.override:.3f}: final for Pack')
    if row.override_mixed:
        details.label(text='Its faces have different values: the highest counts', icon='ERROR')
    labelled(details, 'Visibility').label(text=f'x{row.factor:.2f}')
    labelled(details, 'Seen').label(text='no data' if row.seen < 0 else f'{row.seen * 100:.0f} % of its surface')
    labelled(details, 'Facing').label(text='no data: top of the range' if row.facing < 0 else f'{row.facing:.2f}')
    if row.status not in NO_AREA:
        labelled(details, 'On the UVs now').label(text=f'{row.now:.2f} px/cm')
    if row.status == 'line in UV':
        details.label(text='A line in UV: Pack scales it by its length, not by this density', icon='INFO')
    if _state['users'] > 1:
        details.label(text=f"Mesh shared by {_state['users']} objects: the one needing the most texture counts", icon='INFO')
    layout.operator(FSS_OT_UvIslandSelect.bl_idname, text='Select Faces', icon='RESTRICT_SELECT_OFF')


def listed_count(obj, wm):
    """The number of islands in the open list of this object, or None when the list is closed or of another object."""
    return len(wm.fss_uv_island_rows) if wm.fss_uv_islands_open and _state['object'] == obj.name else None


def draw(layout, context, obj):
    """The island list, opened by the arrow of the table's Islands row."""
    wm = context.window_manager
    if not wm.fss_uv_islands_open:
        return
    if obj.type != 'MESH' or obj.data is None:
        layout.label(text='Not a mesh', icon='INFO')
        return
    if obj.mode == 'EDIT':
        if _state['object'] != obj.name:
            layout.label(text='Open the list in Object Mode', icon='INFO')
            return
    elif _state['key'] != _key(obj, context.scene):
        _schedule(obj, context.scene, context.view_layer, wm)
        if _state['object'] != obj.name:
            layout.label(text='Reading the islands', icon='INFO')
            return
    if _state['error']:
        layout.label(text=_state['error'], icon='ERROR')
        return
    rows = wm.fss_uv_island_rows
    if not rows:
        layout.label(text='No islands: the mesh has no faces or no UV map', icon='INFO')
        return
    if _state['stale']:
        layout.label(text='No visibility data: multipliers are x1.00', icon='INFO')
    elif any(row.facing < 0 for row in rows):
        layout.label(text='No facing data: run Update Visibility once', icon='INFO')
    _draw_header(layout, wm)
    layout.template_list(FSS_UL_UvIslands.bl_idname, '', wm, 'fss_uv_island_rows', wm, 'fss_uv_island_active',
                         rows=LIST_ROWS)
    if 0 <= wm.fss_uv_island_active < len(rows):
        _draw_details(layout, rows[wm.fss_uv_island_active])
    _draw_override(layout, wm, rows, context.scene)


@persistent
def _on_depsgraph_update_post(_scene, depsgraph=None):
    # New seams, an unwrap or a Pack change the islands of the listed mesh
    global _generation
    if depsgraph is None or _state['object'] is None:
        return
    for update in depsgraph.updates:
        if not update.is_updated_geometry:
            continue
        idd = getattr(update.id, 'original', update.id)
        if (isinstance(idd, bpy.types.Object) and idd.name == _state['object']) or (
                isinstance(idd, bpy.types.Mesh) and idd.name == _state['mesh']):
            _generation += 1
            return


@persistent
def _on_load_post(*_args):
    global _generation
    _generation += 1
    _state.update(key=None, object=None, mesh=None, faces=[], error='')


CLASSES = (FSS_UvIslandRow, FSS_UL_UvIslands, FSS_OT_UvIslandSelect, FSS_OT_UvIslandSort, FSS_OT_UvIslandOverrideSet,
           FSS_OT_UvIslandOverrideClear, FSS_OT_UvIslandUntick)
HANDLERS = ((bpy.app.handlers.depsgraph_update_post, _on_depsgraph_update_post),
            (bpy.app.handlers.load_post, _on_load_post))


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    wm = bpy.types.WindowManager
    wm.fss_uv_islands_open = bpy.props.BoolProperty(name='Islands', default=False,
                                                    description="The active object's islands, with what Pack will give each")
    wm.fss_uv_island_sort = bpy.props.EnumProperty(name='Sort Islands', items=SORT_ITEMS, default='DENSITY')
    wm.fss_uv_island_sort_reverse = bpy.props.BoolProperty(name='Lowest First', default=False)
    wm.fss_uv_override_kind = bpy.props.EnumProperty(name='Set By', items=OVERRIDE_KINDS, default='MULTIPLIER')
    wm.fss_uv_override_multiplier = bpy.props.FloatProperty(name='Multiplier', default=1.0, min=0.001, soft_max=10.0,
                                                            description='The multiplier for the ticked islands')
    wm.fss_uv_override_density = bpy.props.FloatProperty(name='Density', default=uv_marks.DEFAULT_TARGET, min=0.001, soft_max=200.0,
                                                         description='The density in px/cm for the ticked islands')
    wm.fss_uv_island_rows = bpy.props.CollectionProperty(type=FSS_UvIslandRow)
    wm.fss_uv_island_active = bpy.props.IntProperty(name='Active Island', update=_row_clicked,
                                                    description='The island whose details are shown below the list')
    for handlers, handler in HANDLERS:
        handlers.append(handler)


def unregister():
    for handlers, handler in HANDLERS:
        if handler in handlers:
            handlers.remove(handler)
    _on_load_post()
    wm = bpy.types.WindowManager
    del wm.fss_uv_island_active
    del wm.fss_uv_island_rows
    del wm.fss_uv_override_density
    del wm.fss_uv_override_multiplier
    del wm.fss_uv_override_kind
    del wm.fss_uv_island_sort_reverse
    del wm.fss_uv_island_sort
    del wm.fss_uv_islands_open
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
