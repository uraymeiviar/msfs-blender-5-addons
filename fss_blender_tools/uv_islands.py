"""The island list of the active object, inside UV Auto Packing's Object box: every island as the packer forms it, with
its multiplier and density, highest density first, so an artist can see what Pack will give each island before packing.
A click on a row, or Select Faces for the row already active, enters Edit Mode and selects the island's faces; nothing
else is changed.

The rows come from uv_pack.object_islands, so they are the packer's own values. A panel may not write while drawing, so
the draw compares a key and a timer fills the rows right after it (as visibility.schedule_camera_sync). The list is
closed by default and costs nothing until opened. In Edit Mode the mesh's own data is not current, so the rows stay as
they were when Edit Mode was entered.
"""

from pathlib import Path

import bmesh
import bpy
from bpy.app.handlers import persistent

from . import uv_marks, uv_pack

LIST_ROWS = 5
_state = {'key': None, 'object': None, 'mesh': None, 'faces': [], 'stale': False, 'users': 1, 'nf': 0, 'error': ''}
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
    return (_generation, obj.name, me.name, len(me.polygons), layer.name if layer else '', mtime,
            uv_marks.density(obj, scene)[0], uv_marks.target_density(scene), uv_marks.partly_seen(scene),
            tuple((uv_marks.texture_size(m), uv_pack.is_kept(m), id(uv_marks._results.get(m.name))) for m in materials))


def sync(obj, scene, view_layer, wm):
    """Fill the rows of obj. Not from a draw."""
    global _syncing
    key = _key(obj, scene)
    active = wm.fss_uv_island_rows[wm.fss_uv_island_active].number if (
        _state['object'] == obj.name and 0 <= wm.fss_uv_island_active < len(wm.fss_uv_island_rows)) else None
    error = ''
    try:
        found = uv_pack.object_islands(obj, scene, view_layer)
    except Exception as ex:  # a redraw must not ask again and again: the list says what went wrong
        found, error = None, str(ex)
    rows, users, stale = found if found is not None else ([], [obj], False)
    for number, row in enumerate(rows, 1):
        row['number'] = number
    rows.sort(key=lambda r: (r['status'] in ('no UV area', 'no 3D area'), -r['high'], -r['area'], r['number']))
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
            if row['number'] == active:
                index = position
        wm.fss_uv_island_active = index
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


def density_text(row):
    """The Density column: the density of the last Pack or Check All of the set when there is one, else the range."""
    if row.kept:
        return 'kept'
    if row.status in ('no UV area', 'no 3D area'):
        return row.status
    result = uv_marks._results.get(row.material)
    t = result.get('t') if result else None
    if t is not None:
        return f'{row.low + t * (row.high - row.low):.2f}'
    return f'{row.low:.2f}' if row.high - row.low < 5e-3 else f'{row.low:.2f} - {row.high:.2f}'


def _area_text(area):
    return f'{area:.1f} cm²' if area < 10000 else f'{area / 10000:.2f} m²'


def _columns(layout, number, area, factor, value):
    """The list's four columns, the same in the header and the rows: each split holds a label and the next split."""
    split = layout.split(factor=0.14)
    split.label(text=number)
    split = split.split(factor=0.24)
    split.label(text=area)
    split = split.split(factor=0.30)
    split.label(text=factor)
    split.label(text=value)


class FSS_UL_UvIslands(bpy.types.UIList):
    bl_idname = 'FSS_UL_uv_islands'

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        _columns(layout, str(item.number), _area_text(item.area), f'x{item.multiplier:.2f}', density_text(item))


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


def _draw_details(layout, row):
    labelled = uv_marks._labelled
    labelled(layout, 'Material').label(text=row.material)
    labelled(layout, 'Faces').label(text=str(row.faces))
    labelled(layout, 'Visibility').label(text=f'x{row.factor:.2f}')
    labelled(layout, 'Seen').label(text='no data' if row.seen < 0 else f'{row.seen * 100:.0f} % of its surface')
    labelled(layout, 'Facing').label(text='no data: top of the range' if row.facing < 0 else f'{row.facing:.2f}')
    if row.status not in ('no UV area', 'no 3D area'):
        labelled(layout, 'On the UVs now').label(text=f'{row.now:.2f} px/cm')
    if row.status == 'line in UV':
        layout.label(text='A line in UV: Pack scales it by its length, not by this density', icon='INFO')
    if _state['users'] > 1:
        layout.label(text=f"Mesh shared by {_state['users']} objects: the one needing the most texture counts", icon='INFO')
    layout.operator(FSS_OT_UvIslandSelect.bl_idname, text='Select Faces', icon='RESTRICT_SELECT_OFF')


def draw(layout, context, obj):
    """The Islands section of the Object box."""
    wm = context.window_manager
    is_open = wm.fss_uv_islands_open
    layout.prop(wm, 'fss_uv_islands_open', text='Islands', emboss=False, icon='TRIA_DOWN' if is_open else 'TRIA_RIGHT')
    if not is_open:
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
    _columns(layout, '#', 'Area', 'Multiplier', 'Density px/cm')
    layout.template_list(FSS_UL_UvIslands.bl_idname, '', wm, 'fss_uv_island_rows', wm, 'fss_uv_island_active',
                         rows=LIST_ROWS)
    if 0 <= wm.fss_uv_island_active < len(rows):
        _draw_details(layout, rows[wm.fss_uv_island_active])


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


CLASSES = (FSS_UvIslandRow, FSS_UL_UvIslands, FSS_OT_UvIslandSelect)
HANDLERS = ((bpy.app.handlers.depsgraph_update_post, _on_depsgraph_update_post),
            (bpy.app.handlers.load_post, _on_load_post))


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    wm = bpy.types.WindowManager
    wm.fss_uv_islands_open = bpy.props.BoolProperty(name='Islands', default=False,
                                                    description="The active object's islands, highest density first")
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
    del wm.fss_uv_islands_open
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
