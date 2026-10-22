"""UV marks: per-object texel density factor and island direction, per-material texture size and margin.

Authoring data for the packing phase (journal 20261019.automated-uv-unwrap.md, decisions 105 to 110). Density marks
multiply down the hierarchy: an object's final range is the scene's density freedom x every own mark from the root
down to the object itself (zone empties included); an unmarked object counts as x1.0. An island's density range is
the target density (scene, px/cm) x that range x the island's visibility. Direction and Skip Auto Seam are inherited
from the nearest marked ancestor. Density marks, texture sizes and margins are registered properties; the export
hooks keep every fss_ key out of the glTF extras (merge._strip_fss_extras).
"""

from pathlib import Path

import bpy
from bpy.app.handlers import persistent

from . import visibility_core
from .tags import _editable

# On an object: the own density mark, a factor range [min, max] (one factor when min == max)
OWN_PROP = 'fss_uv_density_own'
MIN_PROP = 'fss_uv_density_min'
MAX_PROP = 'fss_uv_density_max'
DIRECTION_KEY = 'fss_uv_direction'
SKIP_AUTOSEAM_KEY = 'fss_uv_skip_autoseam'
# Before 0.31.0, read only to migrate: the density mark [min, max] (a custom property; the nearest marked ancestor
# replaced, not multiplied), the zone multiplier (a registered property: its data lies in the object's system
# properties) and the material margin as a fraction of the UV square (a custom property)
DENSITY_KEY = 'fss_uv_density'
ZONE_DENSITY_KEY = 'fss_zone_density'
MARGIN_KEY = 'fss_uv_margin'
MARGIN_REFERENCE = 4096  # old margin fractions convert at 4K (the old default 0.002 is 8 px)
DEFAULT_TARGET = 20.48  # px/cm: 2048 px per metre
DEFAULT_FREEDOM = (0.9, 1.1)
DEFAULT_MARGIN = 8  # px: islands stay apart to the second mip level after 4x4 block compression
DEFAULT_TEXTURE = '4096'
TEXTURE_SIZES = [(str(1 << n), str(1 << n), f'{1 << n} pixels') for n in range(8, 14)]  # 256 to 8192
DENSITY_PRESETS = {'LOWER': 0.75, 'HIGHER': 1.5}
NEVER_SEEN_FACTOR = 0.1  # decision 74: what never-seen faces get instead of visibility 0
MAX_LISTED = 5  # texture sets and nested marks shown in the panel
DIRECTIONS = [
    ('FREE', 'Free', 'Islands may rotate to any angle'),
    ('UPRIGHT', 'Upright', 'Islands keep their orientation (brushed metal, grain, text)'),
    ('FLIP', 'Flip', 'Islands may only turn by 180 degrees'),
    ('QUARTER', 'Quarter', 'Islands may only turn in 90-degree steps'),
]
DIRECTION_IDS = {item[0] for item in DIRECTIONS}
BLOCK_PIXELS = 4  # texture compression works in 4x4 blocks; a margin below this bleeds

_migration = {}  # what the migration converted in the open file (by file path), shown in the Packing panel
_vis_cache = {}  # object name -> (key, summary) of the Visibility row; dropped when the key or the geometry changes


def own_density(obj):
    """(min, max) of the object's own density mark, or None without one."""
    if obj is None or not getattr(obj, OWN_PROP, False):
        return None
    low, high = sorted((getattr(obj, MIN_PROP), getattr(obj, MAX_PROP)))
    return (low, high) if low > 0 else None


def scene_freedom(scene=None):
    scene = scene or bpy.context.scene
    if scene is None:
        return DEFAULT_FREEDOM
    return tuple(sorted((scene.fss_uv_density_freedom_min, scene.fss_uv_density_freedom_max)))


def target_density(scene=None):
    scene = scene or bpy.context.scene
    return DEFAULT_TARGET if scene is None else scene.fss_uv_target_density


def parent_density(obj, scene=None):
    """((low, high), source): the scene freedom x every own mark above obj (not its own); source is the nearest
    marked ancestor, or None."""
    low, high = scene_freedom(scene)
    source = None
    parent = obj.parent if obj is not None else None
    while parent is not None:
        own = own_density(parent)
        if own is not None:
            low, high = low * own[0], high * own[1]
            source = source or parent
        parent = parent.parent
    return (low, high), source


def density(obj, scene=None):
    """((low, high), source): the object's final factor range, the parent chain x its own mark; source is the
    nearest object at or above obj with an own mark, or None."""
    (low, high), source = parent_density(obj, scene)
    own = own_density(obj)
    if own is None:
        return (low, high), source
    return (low * own[0], high * own[1]), obj


def _own_direction(obj):
    value = obj.get(DIRECTION_KEY)
    return value if value in DIRECTION_IDS else None


def _effective(obj, own, default):
    """(value, object it comes from, or None for the default): the nearest marked ancestor wins."""
    while obj is not None:
        value = own(obj)
        if value is not None:
            return value, obj
        obj = obj.parent
    return default, None


def direction(obj):
    return _effective(obj, _own_direction, 'FREE')


def _own_skip_autoseam(obj):
    if SKIP_AUTOSEAM_KEY not in obj:
        return None
    return bool(obj[SKIP_AUTOSEAM_KEY])


def skip_autoseam(obj):
    return _effective(obj, _own_skip_autoseam, False)


def margin(material):
    """The island margin of the material's texture set, in pixels."""
    return getattr(material, 'fss_uv_margin_px', DEFAULT_MARGIN)


def texture_size(material):
    """(width, height) of the material's texture set, in pixels."""
    return (int(getattr(material, 'fss_uv_texture_width', DEFAULT_TEXTURE)),
            int(getattr(material, 'fss_uv_texture_height', DEFAULT_TEXTURE)))


def visibility_factor(score):
    """The density factor of a visibility score: never seen (0) gets the minimum of decision 74."""
    return score if score > 0 else NEVER_SEEN_FACTOR


def _factor_text(low, high):
    return f'x{low:.2f}' if abs(high - low) < 5e-3 else f'x{low:.2f} - x{high:.2f}'


def _source_text(obj, source):
    if source is None:
        return 'default'
    return 'own mark' if source == obj else f'from {source.name}'


def _selected(context):
    return [obj for obj in context.selected_objects if _editable(obj)]


def _object_visibility(obj):
    """The Visibility row: {'status', 'object', 'islands'}. Read through visibility_core.get_object_visibility
    (which caches the file by its modification time) and kept until the file, the mesh or its UVs change, so a
    redraw never scores the islands again."""
    if obj.type != 'MESH' or obj.data is None:
        return {'status': 'NOT_MESH'}
    if obj.mode == 'EDIT':
        return {'status': 'EDIT'}
    vis_path = Path(bpy.data.filepath).with_suffix('.visibility') if bpy.data.filepath else None
    try:
        mtime = vis_path.stat().st_mtime if vis_path is not None else None
    except OSError:
        mtime = None
    uv_layer = obj.data.uv_layers.active
    key = (obj.data.name, len(obj.data.polygons), uv_layer.name if uv_layer else '', str(vis_path), mtime)
    cached = _vis_cache.get(obj.name)
    if cached is not None and cached[0] == key:
        return cached[1]
    data = visibility_core.get_object_visibility(obj, vis_path=vis_path) if mtime is not None else {}
    if data.get('stale', True):
        summary = {'status': 'NO_DATA'}
    elif data.get('never_seen'):
        summary = {'status': 'NEVER_SEEN', 'object': NEVER_SEEN_FACTOR, 'islands': None}
    else:
        values = [visibility_factor(value) for value in data.get('island_values', {}).values()]
        summary = {'status': 'OK', 'object': visibility_factor(data.get('object_score', 1.0)),
                   'islands': (min(values), max(values)) if values else None}
    _vis_cache[obj.name] = (key, summary)
    return summary


@persistent
def _on_depsgraph_update_post(_scene, depsgraph=None):
    # New seams or an unwrap change the islands: drop the Visibility row of that object
    if depsgraph is None or not _vis_cache:
        return
    for update in depsgraph.updates:
        if not update.is_updated_geometry:
            continue
        idd = getattr(update.id, 'original', update.id)
        if isinstance(idd, bpy.types.Object):
            _vis_cache.pop(idd.name, None)
        elif isinstance(idd, bpy.types.Mesh):
            for name in [name for name, (key, _summary) in _vis_cache.items() if key[0] == idd.name]:
                del _vis_cache[name]


def _old_zone_groups(obj):
    """Where a zone multiplier of an earlier version may lie: the object's system properties (the registered
    property's data, readable without the property) and, written by a script, its custom properties."""
    return [group for group in (obj.bl_system_properties_get(), obj) if group is not None and ZONE_DENSITY_KEY in group]


def _old_zone_density(obj):
    for group in _old_zone_groups(obj):
        try:
            return float(group[ZONE_DENSITY_KEY])
        except (TypeError, ValueError):
            pass
    return None


def _old_density(obj):
    value = obj.get(DENSITY_KEY)
    try:
        low, high = float(value[0]), float(value[1])
    except (TypeError, ValueError, IndexError, KeyError):
        return None
    return (low, high) if 0 < low <= high else None


def migrate_marks():
    """Convert the marks of versions before 0.31.0 in the open file and remove the old keys (idempotent).

    A density mark [a, b] becomes an own mark Min a, Max b; a zone multiplier z becomes the zone empty's own mark z
    (both on one object: [a * z, b * z]; z = 1.0 needs no mark); a material margin fraction becomes pixels at 4K.
    An object that already has an own mark keeps it. Returns the counts and the converted density marks that now
    sit below another density mark: those multiply now, where the nearest one replaced the others before (below a
    zone multiplier nothing changes, it multiplied before too)."""
    report = {'density': 0, 'zone': 0, 'margin': 0, 'kept': 0, 'nested': []}
    marked = {obj for obj in bpy.data.objects if own_density(obj) is not None}
    converted = []
    for obj in bpy.data.objects:
        old, zone = _old_density(obj), _old_zone_density(obj)
        if (old is None and zone is None) or not _editable(obj):
            continue
        if obj in marked:
            report['kept'] += 1
        else:
            factor = zone if zone is not None and zone > 0 else 1.0
            if old is not None or abs(factor - 1.0) > 1e-6:
                low, high = old or (1.0, 1.0)
                setattr(obj, MAX_PROP, round(high * factor, 4))
                setattr(obj, MIN_PROP, round(low * factor, 4))
                setattr(obj, OWN_PROP, True)
            if old is not None:
                report['density'] += 1
                converted.append(obj)
            if zone is not None:
                report['zone'] += 1
        if old is not None:
            del obj[DENSITY_KEY]
        for group in _old_zone_groups(obj):
            del group[ZONE_DENSITY_KEY]
    marked |= set(converted)
    for obj in converted:
        parent = obj.parent
        while parent is not None and parent not in marked:
            parent = parent.parent
        if parent is not None:
            report['nested'].append((obj.name, parent.name))
    for material in bpy.data.materials:
        value = material.get(MARGIN_KEY)
        if material.library is None and isinstance(value, (int, float)):
            if value >= 0:
                material.fss_uv_margin_px = round(value * MARGIN_REFERENCE)
            del material[MARGIN_KEY]
            report['margin'] += 1
    return report


def run_migration():
    """Migrate the open file, print what changed and keep it for the Packing panel. A run that finds nothing keeps
    the report of the same file (a second load handler of a reloaded add-on runs right after the first)."""
    global _migration
    report = migrate_marks()
    report['file'] = bpy.data.filepath
    converted = report['density'] or report['zone'] or report['margin']
    if converted or _migration.get('file') != report['file']:
        _migration = report if converted else {}
    if converted:
        print(f"[FSS UV marks] converted old marks: {report['density']} density, {report['zone']} zone, "
              f"{report['margin']} margin; {report['kept']} newer mark(s) kept; {len(report['nested'])} converted "
              "mark(s) below another density mark (marks multiply now)")
        for name, parent in report['nested']:
            print(f"[FSS UV marks]   {name} below {parent}")
    return report


def _run_migration_timer():
    run_migration()
    return None


@persistent
def _on_load_post(*_dummy):
    _vis_cache.clear()
    run_migration()


def _keep_order(low_name, high_name, moved):
    """Update function: dragging one bound past the other moves the other along (Min never above Max)."""
    def update(self, _context):
        if getattr(self, low_name) > getattr(self, high_name):
            if moved == low_name:
                setattr(self, high_name, getattr(self, low_name))
            else:
                setattr(self, low_name, getattr(self, high_name))
    return update


class FSS_OT_UvSetDensity(bpy.types.Operator):
    bl_idname = 'fss.uv_set_density'
    bl_label = 'Set Texel Density Factor'
    bl_description = ('Mark the selected objects with a texel density factor; marks multiply down the hierarchy, '
                      'so everything below takes it too')
    bl_options = {'REGISTER', 'UNDO'}

    preset: bpy.props.EnumProperty(items=[
        ('LOWER', 'Lower', 'Less visible parts: x0.75'),
        ('HIGHER', 'Higher', 'Prominent parts such as the glareshield: x1.5'),
        ('CLEAR', 'Clear', 'Remove the own mark (x1.0): only the marks above apply'),
    ])

    @classmethod
    def poll(cls, context):
        return bool(_selected(context))

    def execute(self, context):
        factor = DENSITY_PRESETS.get(self.preset)
        objects = _selected(context)
        for obj in objects:
            setattr(obj, OWN_PROP, factor is not None)
            setattr(obj, MAX_PROP, factor or 1.0)
            setattr(obj, MIN_PROP, factor or 1.0)
        text = 'Cleared density mark' if factor is None else f'Density x{factor:g}'
        self.report({'INFO'}, f'{text} on {len(objects)} object(s)')
        return {'FINISHED'}


class FSS_OT_UvSetDirection(bpy.types.Operator):
    bl_idname = 'fss.uv_set_direction'
    bl_label = 'Set Island Direction'
    bl_description = ('Mark how the islands of the selected objects may rotate when packed; their children '
                      'inherit it unless marked themselves')
    bl_options = {'REGISTER', 'UNDO'}

    direction: bpy.props.EnumProperty(items=DIRECTIONS + [('CLEAR', 'Clear', 'Remove the mark')])

    @classmethod
    def poll(cls, context):
        return bool(_selected(context))

    def execute(self, context):
        objects = _selected(context)
        for obj in objects:
            if self.direction == 'CLEAR':
                obj.pop(DIRECTION_KEY, None)
            else:
                obj[DIRECTION_KEY] = self.direction
        self.report({'INFO'}, f'Direction {self.direction.lower()} on {len(objects)} object(s)')
        return {'FINISHED'}


class FSS_OT_UvSetSkipAutoseam(bpy.types.Operator):
    bl_idname = 'fss.uv_set_skip_autoseam'
    bl_label = 'Skip Auto Seam'
    bl_description = ('Mark the selected objects to be skipped by Auto Seam (e.g. fur, hair cards, wire bundles); '
                      'their children inherit it unless marked themselves')
    bl_options = {'REGISTER', 'UNDO'}

    action: bpy.props.EnumProperty(items=[
        ('SKIP', 'Skip', 'Mark selected objects to be skipped by Auto Seam'),
        ('CLEAR', 'Clear', 'Remove the mark: inherit from parent, else default (process)'),
    ], default='SKIP')

    @classmethod
    def poll(cls, context):
        return bool(_selected(context))

    def execute(self, context):
        objects = _selected(context)
        for obj in objects:
            if self.action == 'CLEAR':
                obj.pop(SKIP_AUTOSEAM_KEY, None)
            else:
                obj[SKIP_AUTOSEAM_KEY] = True
        text = 'Cleared Skip Auto Seam mark' if self.action == 'CLEAR' else 'Set Skip Auto Seam'
        self.report({'INFO'}, f'{text} on {len(objects)} object(s)')
        return {'FINISHED'}


def draw_skip_autoseam(layout, context):
    """The Skip Auto Seam mark, drawn in the Seams section (UV Tools > Seams)."""
    obj = context.active_object
    box = layout.box()
    if obj is not None:
        is_skip, source = skip_autoseam(obj)
        state = 'skipped' if is_skip else 'processed'
        box.label(text=f'{obj.name}: {state} by Propose Seams ({_source_text(obj, source)})')
    box.label(text=f'Mark {len(_selected(context))} selected object(s):')
    row = box.row(align=True)
    row.operator(FSS_OT_UvSetSkipAutoseam.bl_idname, text='Skip Auto Seam').action = 'SKIP'
    row.operator(FSS_OT_UvSetSkipAutoseam.bl_idname, text='Clear').action = 'CLEAR'


def _labelled(layout, text):
    """A row with a label column; returns the part right of the label."""
    split = layout.split(factor=0.3)
    split.label(text=text)
    return split.row(align=True)


def _visibility_text(summary):
    status = summary['status']
    if status == 'NOT_MESH':
        return 'not a mesh: x1.00'
    if status == 'EDIT':
        return 'shown in Object Mode'
    if status == 'NO_DATA':
        return 'no data: x1.00'
    if status == 'NEVER_SEEN':
        return f'never seen: x{NEVER_SEEN_FACTOR:.2f}'
    islands = summary['islands']
    text = f"x{summary['object']:.2f}"
    return text + (f'  islands {islands[0]:.2f}-{islands[1]:.2f}' if islands else '')


def result_range(obj, scene, summary):
    """((a, b), (c, d) or None): the object's density range in px/cm with its visibility score, and the range over
    its islands' visibility (target x parent x own x visibility)."""
    (low, high), _source = density(obj, scene)
    target = target_density(scene)
    vis = summary.get('object', 1.0)
    islands = summary.get('islands')
    return ((target * low * vis, target * high * vis),
            (target * low * islands[0], target * high * islands[1]) if islands else None)


def _draw_migration(layout):
    box = layout.box()
    box.label(text=f"Converted old marks: {_migration['density']} density, {_migration['zone']} zone, "
                   f"{_migration['margin']} margin", icon='INFO')
    nested = _migration['nested']
    if nested:
        box.label(text=f'{len(nested)} converted mark(s) below another mark: they multiply now', icon='ERROR')
        for name, parent in nested[:MAX_LISTED]:
            box.label(text=f'{name} below {parent}')
        if len(nested) > MAX_LISTED:
            box.label(text=f'... {len(nested) - MAX_LISTED} more (in the system console)')


def _draw_object(layout, scene, obj):
    from . import merge  # merge imports this module for the zone row

    box = layout.box()
    box.label(text=obj.name, icon='OBJECT_DATA')
    (low, high), source = parent_density(obj, scene)
    origin = f'from {source.name}' if source is not None else '(scene freedom)'
    _labelled(box, 'Parent').label(text=f'{_factor_text(low, high)} {origin}')
    zone = merge.nearest_zone(obj)
    if zone is None:
        _labelled(box, 'Zone').label(text='none')
    else:
        name = merge.logical_name(zone)[len(merge.ZONE_PREFIX):] or zone.name
        own = own_density(zone)
        _labelled(box, 'Zone').label(text=f'{name} {_factor_text(*own)}' if own else f'{name} x1.00 (no mark)')
    summary = _object_visibility(obj)
    _labelled(box, 'Visibility').label(text=_visibility_text(summary))
    row = _labelled(box, 'Density')
    row.prop(obj, OWN_PROP, text='own mark')
    fields = row.row(align=True)
    fields.enabled = getattr(obj, OWN_PROP)
    fields.prop(obj, MIN_PROP, text='Min')
    fields.prop(obj, MAX_PROP, text='Max')
    row = _labelled(box, '')
    for preset, text in (('LOWER', 'Lower'), ('HIGHER', 'Higher'), ('CLEAR', 'Clear')):
        row.operator(FSS_OT_UvSetDensity.bl_idname, text=text).preset = preset
    box.separator(type='LINE')
    (a, b), islands = result_range(obj, scene, summary)
    text = f'{a:.2f} - {b:.2f} px/cm'
    if islands:
        text += f'  (islands {islands[0]:.2f} - {islands[1]:.2f})'
    _labelled(box, 'Result').label(text=text)
    _labelled(box, '').label(text='= target x parent x own x visibility')
    value, source = direction(obj)
    row = _labelled(box, 'Direction')
    for item in DIRECTIONS + [('CLEAR', 'Clear', '')]:
        row.operator(FSS_OT_UvSetDirection.bl_idname, text=item[1], depress=item[0] == value).direction = item[0]
    if source is not None and source != obj:
        _labelled(box, '').label(text=f'{value.lower()} from {source.name}')

    materials = []
    for slot in obj.material_slots:
        if slot.material is not None and slot.material not in materials:
            materials.append(slot.material)
    for material in materials[:MAX_LISTED]:
        box = layout.box()
        box.label(text=f'Texture set: {material.name}', icon='MATERIAL')
        row = _labelled(box, 'Size')
        row.prop(material, 'fss_uv_texture_width', text='')
        row.label(text='x')
        row.prop(material, 'fss_uv_texture_height', text='')
        _labelled(box, 'Margin').prop(material, 'fss_uv_margin_px', text='')
        if margin(material) < BLOCK_PIXELS:
            box.label(text=f'Under {BLOCK_PIXELS} px: compressed 4x4 blocks bleed across islands', icon='ERROR')
    if len(materials) > MAX_LISTED:
        layout.label(text=f'... {len(materials) - MAX_LISTED} more')


class FSS_PT_UvMarks(bpy.types.Panel):
    bl_idname = 'FSS_PT_uv_marks'
    bl_label = 'Packing'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'FSS Tools'
    bl_parent_id = 'FSS_PT_uv_tools'
    bl_order = 1
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        if _migration:
            _draw_migration(layout)
        row = _labelled(layout, 'Target density')
        row.prop(scene, 'fss_uv_target_density', text='')
        row.label(text='px/cm')
        row = _labelled(layout, 'Density freedom')
        row.prop(scene, 'fss_uv_density_freedom_min', text='Min')
        row.prop(scene, 'fss_uv_density_freedom_max', text='Max')
        obj = context.active_object
        if obj is None:
            layout.label(text='No active object', icon='INFO')
        else:
            _draw_object(layout, scene, obj)


CLASSES = (FSS_OT_UvSetDensity, FSS_OT_UvSetDirection, FSS_OT_UvSetSkipAutoseam, FSS_PT_UvMarks)
HANDLERS = ((bpy.app.handlers.load_post, _on_load_post),
            (bpy.app.handlers.depsgraph_update_post, _on_depsgraph_update_post))


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    factor = dict(min=0.01, max=10.0, soft_min=0.1, soft_max=4.0, precision=2)
    bpy.types.Object.fss_uv_density_own = bpy.props.BoolProperty(
        name='Own Density Mark', default=False,
        description='This object has its own texel density factor: it multiplies the factors above it, and '
                    'everything below takes it too')
    bpy.types.Object.fss_uv_density_min = bpy.props.FloatProperty(
        name='Min', default=1.0, update=_keep_order(MIN_PROP, MAX_PROP, MIN_PROP),
        description='Lowest texel density factor of this mark (Alt+drag sets it on all selected objects)', **factor)
    bpy.types.Object.fss_uv_density_max = bpy.props.FloatProperty(
        name='Max', default=1.0, update=_keep_order(MIN_PROP, MAX_PROP, MAX_PROP),
        description='Highest texel density factor of this mark (Alt+drag sets it on all selected objects)', **factor)
    bpy.types.Scene.fss_uv_target_density = bpy.props.FloatProperty(
        name='Target Density', default=DEFAULT_TARGET, min=0.01, soft_min=1.0, soft_max=100.0, precision=2,
        description='Texel density at factor 1.0 for the whole scene, in pixels per centimetre (20.48 is 2048 px '
                    'per metre)')
    names = ('fss_uv_density_freedom_min', 'fss_uv_density_freedom_max')
    bpy.types.Scene.fss_uv_density_freedom_min = bpy.props.FloatProperty(
        name='Min', default=DEFAULT_FREEDOM[0], update=_keep_order(*names, names[0]),
        description='Lowest factor the packer may give any island, before the density marks', **factor)
    bpy.types.Scene.fss_uv_density_freedom_max = bpy.props.FloatProperty(
        name='Max', default=DEFAULT_FREEDOM[1], update=_keep_order(*names, names[1]),
        description='Highest factor the packer may give any island, before the density marks', **factor)
    for name, text in (('fss_uv_texture_width', 'Width'), ('fss_uv_texture_height', 'Height')):
        setattr(bpy.types.Material, name, bpy.props.EnumProperty(
            name=f'Texture {text}', items=TEXTURE_SIZES, default=DEFAULT_TEXTURE,
            description=f'{text} of this texture set in pixels'))
    bpy.types.Material.fss_uv_margin_px = bpy.props.IntProperty(
        name='UV Margin', default=DEFAULT_MARGIN, min=0, soft_max=64, subtype='PIXEL',
        description='Space around each island in pixels of this texture set (8 keeps islands apart to the second '
                    'mip level after 4x4 block compression)')
    for handlers, handler in HANDLERS:
        if handler not in handlers:
            handlers.append(handler)
    # The open file: at Blender startup the add-on is enabled before bpy.data can be read, so migrate from a timer
    if isinstance(bpy.data, bpy.types.BlendData):
        run_migration()
    else:
        bpy.app.timers.register(_run_migration_timer, first_interval=0.0)


def unregister():
    for handlers, handler in HANDLERS:
        if handler in handlers:
            handlers.remove(handler)
    if bpy.app.timers.is_registered(_run_migration_timer):
        bpy.app.timers.unregister(_run_migration_timer)
    _vis_cache.clear()
    for name in ('fss_uv_margin_px', 'fss_uv_texture_height', 'fss_uv_texture_width'):
        delattr(bpy.types.Material, name)
    for name in ('fss_uv_density_freedom_max', 'fss_uv_density_freedom_min', 'fss_uv_target_density'):
        delattr(bpy.types.Scene, name)
    for name in (MAX_PROP, MIN_PROP, OWN_PROP):
        delattr(bpy.types.Object, name)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
