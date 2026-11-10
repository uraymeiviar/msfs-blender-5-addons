"""UV marks: per-object texel density factor and island direction, per-material texture size and margin.

Authoring data for the packing phase (journal 20261019.automated-uv-unwrap.md, decisions 105 to 110). Density marks
multiply down the hierarchy: an object's final range is the scene's density freedom x every own mark from the root
down to the object itself (zone empties included); an unmarked object counts as x1.0. An island's density range is
the target density (scene, px/cm) x that range x its material's factor x the island's visibility. Direction and Skip Auto Seam are inherited
from the nearest marked ancestor. Density marks, texture sizes and margins are registered properties; the export
hooks keep every fss_ key out of the glTF extras (merge._strip_fss_extras).

The Packing section has two boxes. The table has a row for the scene (target density, density freedom, Check All:
uv_pack.measure on every texture set, decision 115), the zone, the direct parent and the marked parents up to the zone, the
materials the active object's faces use (decision 146), the active object, and its islands, then the resulting density and direction (decisions 134 to 143). Texture sets: a table of
the texture sets of the selected objects (decisions 121, 144): the tick (off is Keep UVs, decision 116), a select button,
the name, size (square, decision 120), margin and Pack (uv_pack.pack, decision 114), then Pack All (decision 145). Check
Results, a sub-panel (decision 148): every texture set measured so far, tightest first, with its layout and the room for a
higher density. The section is drawn in the 3D viewport's and the UV editor's
sidebar (decision 119). The results stay in memory for the session (not in the file) and are cleared when a file is
loaded.
"""

from pathlib import Path

import time

import blf
import bpy
import numpy as np
from bpy.app.handlers import persistent

from . import uv_pack, visibility_core  # uv_pack imports this module too (density, direction, sizes)
from .tags import _editable

# On an object: the own density mark, a factor range [min, max] (one factor when min == max)
OWN_PROP = 'fss_uv_density_own'  # the row's tick: unticked, the factor stays but is ignored (decision 139)
FACTOR_PROP = 'fss_uv_density_factor'  # the table's field: one factor, read from and written to Min and Max
USE_VISIBILITY_PROP = 'fss_uv_use_visibility'  # the Islands row's tick: unticked, the object's islands ignore visibility
MIN_PROP = 'fss_uv_density_min'
MAX_PROP = 'fss_uv_density_max'
DIRECTION_KEY = 'fss_uv_direction'
DIRECTION_MARK_PROP = 'fss_uv_direction_mark'  # the table's pulldown, read from and written to DIRECTION_KEY
SKIP_AUTOSEAM_KEY = 'fss_uv_skip_autoseam'
KEEP_UVS_PROP = 'fss_uv_keep_uvs'  # on a material: its texture set is not packed (decision 116)
MATERIAL_FACTOR_PROP = 'fss_uv_material_density'  # on a material: the density factor of all its islands (decision 146)
MATERIAL_TICK_PROP = 'fss_uv_material_density_use'  # the Material row's tick: unticked, the factor stays but is ignored
SIZE_PROP = 'fss_uv_texture_size'  # on a material: the square texture size (decision 120)
OVERRIDE_KEY = 'fss_uv_island_multiplier'  # a face attribute: the island's multiplier set by hand, 0 for none
# Before 0.31.0, read only to migrate: the density mark [min, max] (a custom property; the nearest marked ancestor
# replaced, not multiplied), the zone multiplier (a registered property: its data lies in the object's system
# properties) and the material margin as a fraction of the UV square (a custom property)
DENSITY_KEY = 'fss_uv_density'
ZONE_DENSITY_KEY = 'fss_zone_density'
MARGIN_KEY = 'fss_uv_margin'
# Before 0.33.0, read only to migrate: width and height of the texture set (registered enums: their data, the item
# index, lies in the material's system properties)
OLD_SIZE_KEYS = ('fss_uv_texture_width', 'fss_uv_texture_height')
MARGIN_REFERENCE = 4096  # old margin fractions convert at 4K (the old default 0.002 is 8 px)
DEFAULT_TARGET = 20.48  # px/cm: 2048 px per metre
DEFAULT_FREEDOM = (0.9, 1.1)
PACK_CORNERS = (('BOTTOM_LEFT', 'Bottom-Left', 'The UV origin, as the layout comes out of packing'),
                ('TOP_LEFT', 'Top-Left', 'U at 0, V at 1'),
                ('TOP_RIGHT', 'Top-Right', 'U at 1, V at 1'),
                ('BOTTOM_RIGHT', 'Bottom-Right', 'U at 1, V at 0'))
DEFAULT_MARGIN = 8  # px: islands stay apart to the second mip level after 4x4 block compression
DEFAULT_TEXTURE = '4096'
TEXTURE_SIZES = [(str(1 << n), str(1 << n), f'{1 << n} pixels') for n in range(8, 14)]  # 256 to 8192
# The visibility score carries its own floor, the Ambient of Visibility Scoring (UV decision 133, replacing the x0.10 of
# decisions 74 and 111); this only keeps a density above 0 when Ambient is 0 or Partly Seen scales an island down
MIN_VISIBILITY = 0.01
FULLY_SEEN = 0.9999  # a seen share counted as the whole island (areas are rounded)
DEFAULT_PARTLY_SEEN = 1.0  # Island Value already follows the lit part (UV decision 132)
MAX_LISTED = 5  # nested marks shown in the panel
LIST_ROWS = 5  # rows the texture set list shows before it scrolls (the artist can drag it longer)
DIRECTIONS = [
    ('FREE', 'Free', 'No mark: as the nearest marked parent, any angle when none is marked'),
    ('UPRIGHT', 'Upright', 'Islands keep their orientation (brushed metal, grain, text)'),
    ('FLIP', 'Flip', 'Islands may only turn by 180 degrees'),
    ('QUARTER', 'Quarter', 'Islands may only turn in 90-degree steps'),
]
DIRECTION_IDS = {item[0] for item in DIRECTIONS}
TICK_COLUMN = 0.13  # the table's columns: the tick and icon, then shares of the rest
VALUE_COLUMN, DIRECTION_COLUMN, NAME_COLUMN = 0.25, 0.25, 0.5
CHECK_COLUMN = 0.16
SET_NAME_COLUMN, SET_SIZE_COLUMN, SET_MARGIN_COLUMN, SET_PACK_COLUMN = 0.42, 0.21, 0.16, 0.21  # the texture set rows
TABLE_ICONS = {'SCENE': 'SCENE_DATA', 'ZONE': 'OUTLINER_OB_EMPTY', 'PARENT': 'ORIENTATION_PARENT', 'MATERIAL': 'MATERIAL',
               'OBJECT': 'OBJECT_DATA', 'ISLANDS': 'UV_ISLANDSEL'}
TABLE_HINTS = {
    'SCENE': 'Scene: the target density and the freedom the packer has around it, for everything',
    'ZONE': 'Zone: its factor and direction apply to everything in the zone',
    'PARENT': 'Parent: the direct parent, or a parent with a density mark. Its factor and direction apply to everything below it',
    'MATERIAL': 'Material: its factor applies to every island with this material, on all objects',
    'OBJECT': 'Object: the active object',
    'ISLANDS': "Islands: the range of the visibility multipliers of this object's islands",
}
PANEL_PADDING, LIST_PADDING, BUTTON_PADDING = 56, 30, 14  # pixels at UI scale 1: what the panel, a list and a button take
BAR_SPAN = 2.0  # the density bar runs from 0 to this x the target density, so the target mark stays in the middle
BAR_MARK = 0.008  # the width of the target mark, as a share of the bar
BAR_MIN_RANGE = 0.012  # a narrower range is still drawn this wide
BAR_SCALE = 0.5
BAR_COLORS = {'TRACK': ('fss_uv_bar_track', (0.16, 0.16, 0.16)), 'RANGE': ('fss_uv_bar_range', (0.3, 0.6, 1.0)),
              'MARK': ('fss_uv_bar_mark', (1.0, 1.0, 1.0))}
BLOCK_PIXELS = 4  # texture compression works in 4x4 blocks; a margin below this bleeds
RESULT_NAME_COLUMN, RESULT_BAR_COLUMN = 0.34, 0.50  # the Check Results table; the room takes the rest
FULL_ROOM = 1.005  # less room than this counts as a full texture

_migration = {}  # what the migration converted in the open file (by file path), shown in the Packing panel
_vis_cache = {}  # object name -> (key, summary) of the Visibility row; dropped when the key or the geometry changes
_results = {}  # texture set name -> the last uv_pack result (Pack or Check All) in this session
_settings_generation = 0  # raised by every setting a result depends on: a result of an older one is out of date
# While Pack or Check All runs, the Packing section shows this progress instead of its rows and buttons
_progress = None  # dict: verb ('Packing' or 'Checking'), index, count, set, stage, fraction (of the set in work)
_cancel_requested = False


def own_density(obj):
    """(min, max) of the object's own density mark, or None without one."""
    if obj is None or not getattr(obj, OWN_PROP, False):
        return None
    low, high = sorted((getattr(obj, MIN_PROP), getattr(obj, MAX_PROP)))
    return (low, high) if low > 0 and (low, high) != (1.0, 1.0) else None  # x1.00 is no mark (decision 141)


def scene_freedom(scene=None):
    scene = scene or bpy.context.scene
    if scene is None:
        return DEFAULT_FREEDOM
    return tuple(sorted((scene.fss_uv_density_freedom_min, scene.fss_uv_density_freedom_max)))


def target_density(scene=None):
    scene = scene or bpy.context.scene
    return DEFAULT_TARGET if scene is None else scene.fss_uv_target_density


def pack_corner(scene):
    """The corner of the texture Pack moves a layout to (decision 123)."""
    return scene.fss_uv_pack_corner


def partly_seen(scene):
    """The scene's Partly Seen Islands value, see island_visibility."""
    return scene.fss_uv_partly_seen_value


def partly_seen_factor(seen_share, value):
    """What an island keeps of its score when only a share of it is seen. value 1: all of it, any seen part makes the
    island visible. 0.5: the share itself. 0: nothing unless the whole island is seen. Between them the share to the
    power (1 - value) / value: 0.75 is biased towards visible (cube root), 0.25 towards scaling down (cube)."""
    if value >= 1.0 or seen_share >= FULLY_SEEN:
        return 1.0
    if value <= 0.0:
        return 0.0
    return seen_share ** ((1.0 - value) / value)


def island_visibility(score, seen_share, value, floor=MIN_VISIBILITY):
    """The density factor of an island: its score x partly_seen_factor, never below floor (the file's Ambient,
    decision 133)."""
    return max(score * partly_seen_factor(seen_share, value), floor, MIN_VISIBILITY)


def face_overrides(me):
    """Per face: the multiplier the artist set by hand, 0 where none; None when the mesh has none at all."""
    attribute = me.attributes.get(OVERRIDE_KEY)
    if attribute is None or attribute.domain != 'FACE' or attribute.data_type != 'FLOAT':
        return None
    values = np.zeros(len(me.polygons), np.float32)
    attribute.data.foreach_get('value', values)
    return values


def set_face_overrides(me, faces, value):
    """Set the multiplier of these faces, 0 to clear it. In Object Mode. A mesh left without any loses the attribute."""
    values = face_overrides(me)
    if values is None:
        if value <= 0.0:
            return
        values = np.zeros(len(me.polygons), np.float32)
    values[faces] = value
    attribute = me.attributes.get(OVERRIDE_KEY)
    if not values.any():
        if attribute is not None:
            me.attributes.remove(attribute)
        return
    if attribute is None or attribute.domain != 'FACE' or attribute.data_type != 'FLOAT':
        if attribute is not None:
            me.attributes.remove(attribute)
        attribute = me.attributes.new(OVERRIDE_KEY, 'FLOAT', 'FACE')
    attribute.data.foreach_set('value', values)
    me.update()


def corner_label(corner):
    return next(label for key, label, _text in PACK_CORNERS if key == corner)


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


def material_density(material):
    """The density factor of a material: 1.0 without a material or with its row unticked (decision 146)."""
    if material is None or not getattr(material, MATERIAL_TICK_PROP, True):
        return 1.0
    return getattr(material, MATERIAL_FACTOR_PROP, 1.0)


def object_materials(obj):
    """The materials the object's faces use, in slot order, each once. A slot no face uses has no row."""
    if obj is None or obj.type != 'MESH' or obj.data is None or not len(obj.data.polygons):
        return []
    indices = np.zeros(len(obj.data.polygons), np.int32)
    obj.data.polygons.foreach_get('material_index', indices)
    used = set(np.unique(indices).tolist())
    materials = []
    for index, slot in enumerate(obj.material_slots):
        if index in used and slot.material is not None and slot.material not in materials:
            materials.append(slot.material)
    return materials


def _own_direction(obj):
    # Free is no mark (decision 137): an object left Free, also one marked Free before, takes the mark above it
    value = obj.get(DIRECTION_KEY)
    return value if value in DIRECTION_IDS and value != 'FREE' else None


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
    """The size of the material's square texture set, in pixels per side."""
    return int(getattr(material, SIZE_PROP, DEFAULT_TEXTURE))


def uses_visibility(obj):
    """False when the artist unticked the Islands row of this object: its islands count as fully visible."""
    return getattr(obj, USE_VISIBILITY_PROP, True)


def visibility_factor(score):
    """The density factor of a visibility score. The score is at least the file's Ambient (decision 133); the small
    minimum here only keeps a density above 0."""
    return max(score, MIN_VISIBILITY)


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
        summary = {'status': 'NEVER_SEEN', 'object': visibility_factor(data.get('object_score', 0.0)), 'islands': None}
    else:
        values = [visibility_factor(value) for value in data.get('island_values', {}).values()]
        summary = {'status': 'OK', 'object': visibility_factor(data.get('object_score', 1.0)),
                   'islands': (min(values), max(values)) if values else None, 'count': len(values)}
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


def _old_groups(idd, key):
    """Where a registered property of an earlier version may lie: the ID's system properties (the property's data,
    readable without the property) and, written by a script, its custom properties."""
    return [group for group in (idd.bl_system_properties_get(), idd) if group is not None and key in group]


def _old_zone_density(obj):
    for group in _old_groups(obj, ZONE_DENSITY_KEY):
        try:
            return float(group[ZONE_DENSITY_KEY])
        except (TypeError, ValueError):
            pass
    return None


def _old_side(material, key):
    """A texture side of an earlier version in pixels, or None: the enum's item index (system properties), or a size
    written as text or number by a script."""
    sizes = [int(item[0]) for item in TEXTURE_SIZES]
    for group in _old_groups(material, key):
        value = group[key]
        if isinstance(value, int) and 0 <= value < len(sizes):
            return sizes[value]
        try:
            if int(value) in sizes:
                return int(value)
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
    """Convert the marks of versions before 0.31.0, and the texture sizes before 0.33.0, in the open file and remove
    the old keys (idempotent).

    A density mark [a, b] becomes an own mark Min a, Max b; a zone multiplier z becomes the zone empty's own mark z
    (both on one object: [a * z, b * z]; z = 1.0 needs no mark); a material margin fraction becomes pixels at 4K; a
    texture width and height become one square size, the larger of the two (a side never set was the default 4096).
    An object that already has an own mark keeps it, a material that already has a square size keeps it. Returns the
    counts and the converted density marks that now sit below another density mark: those multiply now, where the
    nearest one replaced the others before (below a zone multiplier nothing changes, it multiplied before too)."""
    report = {'density': 0, 'zone': 0, 'margin': 0, 'size': 0, 'kept': 0, 'nested': []}
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
        for group in _old_groups(obj, ZONE_DENSITY_KEY):
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
        sides = [_old_side(material, key) for key in OLD_SIZE_KEYS]
        if material.library is not None or sides == [None, None]:
            continue
        system = material.bl_system_properties_get()
        if system is not None and SIZE_PROP in system:
            report['kept'] += 1
        else:
            setattr(material, SIZE_PROP, str(max(side or int(DEFAULT_TEXTURE) for side in sides)))
            report['size'] += 1
        for key in OLD_SIZE_KEYS:
            for group in _old_groups(material, key):
                del group[key]
    return report


def run_migration():
    """Migrate the open file, print what changed and keep it for the Packing panel. A run that finds nothing keeps
    the report of the same file (a second load handler of a reloaded add-on runs right after the first)."""
    global _migration
    report = migrate_marks()
    report['file'] = bpy.data.filepath
    converted = report['density'] or report['zone'] or report['margin'] or report['size']
    if converted or _migration.get('file') != report['file']:
        _migration = report if converted else {}
    if converted:
        print(f"[FSS UV marks] converted old marks: {report['density']} density, {report['zone']} zone, "
              f"{report['margin']} margin, {report['size']} texture size (square now); {report['kept']} newer mark(s) "
              f"kept; {len(report['nested'])} converted mark(s) below another density mark (marks multiply now)")
        for name, parent in report['nested']:
            print(f"[FSS UV marks]   {name} below {parent}")
    return report


def _run_migration_timer():
    run_migration()
    return None


@persistent
def _on_load_post(*_dummy):
    global _progress, _cancel_requested
    _vis_cache.clear()
    _results.clear()
    _progress = None
    _cancel_requested = False
    run_migration()


def _keep_order(low_name, high_name, moved):
    """Update function: dragging one bound past the other moves the other along (Min never above Max)."""
    def update(self, context):
        if getattr(self, low_name) > getattr(self, high_name):
            if moved == low_name:
                setattr(self, high_name, getattr(self, low_name))
            else:
                setattr(self, low_name, getattr(self, high_name))
        _marks_changed(self, context)
    return update


def _settings_changed():
    """A setting Pack depends on changed: the results measured so far are out of date."""
    global _settings_generation
    _settings_generation += 1


def _marks_changed(_self, _context):
    """Update function: a mark or the scene freedom changes the density of everything below it, so the heatmap's
    Density mode recomputes its objects (imported here: uv_heatmap imports this module)."""
    from . import uv_heatmap
    _settings_changed()
    uv_heatmap.marks_changed()


def _pack_result_changed():
    """A Pack or Check All gave a set its final densities: the heatmap's Calculated density follows."""
    from . import uv_heatmap
    uv_heatmap.pack_result_changed()


def _stored_range(obj):
    """(min, max) as stored, also while the row is unticked."""
    return tuple(sorted((getattr(obj, MIN_PROP), getattr(obj, MAX_PROP))))


def _get_factor(obj):
    return _stored_range(obj)[0]


def _set_factor(obj, value):
    """One factor for the row (decision 135); the row's tick decides whether it counts."""
    setattr(obj, MAX_PROP, value)
    setattr(obj, MIN_PROP, value)


def _get_direction_mark(obj):
    return next(index for index, item in enumerate(DIRECTIONS) if item[0] == (_own_direction(obj) or 'FREE'))


def _set_direction_mark(obj, index):
    _settings_changed()
    if DIRECTIONS[index][0] == 'FREE':
        obj.pop(DIRECTION_KEY, None)
    else:
        obj[DIRECTION_KEY] = DIRECTIONS[index][0]


class FSS_OT_UvTableHint(bpy.types.Operator):
    """A table icon: Blender has tooltips on buttons only, so the icon is a flat button that does nothing (decision 140)."""
    bl_idname = 'fss.uv_table_hint'
    bl_label = 'Table Row'
    bl_options = {'INTERNAL'}

    kind: bpy.props.StringProperty(options={'HIDDEN'})

    @classmethod
    def description(cls, context, properties):
        return TABLE_HINTS.get(properties.kind, '')

    def execute(self, context):
        return {'CANCELLED'}


class FSS_OT_UvTextureSetInfo(bpy.types.Operator):
    """The name in a texture set row: a flat button, for the tooltip with the last run (decision 144)."""
    bl_idname = 'fss.uv_texture_set_info'
    bl_label = 'Texture Set'
    bl_options = {'INTERNAL'}

    material: bpy.props.StringProperty(options={'HIDDEN'})

    @classmethod
    def description(cls, context, properties):
        material = bpy.data.materials.get(properties.material)
        if material is None:
            return properties.material
        return chr(10).join([material.name, f'Last run: {last_result_text(material)}'] + set_problems(material))

    def execute(self, context):
        return {'CANCELLED'}


class FSS_OT_UvSelectObject(bpy.types.Operator):
    bl_idname = 'fss.uv_select_object'
    bl_label = 'Select Object'
    bl_options = {'REGISTER', 'UNDO'}

    target: bpy.props.StringProperty(name='Object', description='Name of the object to select')

    @classmethod
    def description(cls, context, properties):
        return f'{properties.target}: select only this object and make it active'

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        view_layer = context.view_layer
        obj = view_layer.objects.get(self.target)
        if obj is None or not obj.visible_get(view_layer=view_layer):
            self.report({'WARNING'}, f"'{self.target}' is hidden or not in this view layer")
            return {'CANCELLED'}
        for other in context.selected_objects:
            other.select_set(False)
        obj.select_set(True)
        view_layer.objects.active = obj
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
    """The Skip Auto Seam mark, drawn in the UV Auto Seam panel."""
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


def _island_text(summary):
    """The value column of the Islands row."""
    status = summary['status']
    if status in ('NOT_MESH', 'EDIT', 'NO_DATA', 'NEVER_SEEN'):
        return {'NOT_MESH': 'not a mesh', 'EDIT': 'Object Mode', 'NO_DATA': 'no data', 'NEVER_SEEN': 'never lit'}[status]
    islands = summary['islands']
    return f'{islands[0]:.2f} - {islands[1]:.2f}' if islands else f"{summary['object']:.2f}"


def result_range(obj, scene, summary):
    """((a, b), (c, d) or None): the object's density range in px/cm with its visibility score, and the range over
    its islands' visibility (target x parent x material x own x visibility). With the Islands row unticked, visibility
    is 1. With several materials: from the lowest factor to the highest."""
    (low, high), _source = density(obj, scene)
    factors = [material_density(material) for material in object_materials(obj)] or [1.0]
    low, high = low * min(factors), high * max(factors)
    target = target_density(scene)
    use = uses_visibility(obj)
    vis = summary.get('object', 1.0) if use else 1.0
    islands = summary.get('islands') if use else None
    return ((target * low * vis, target * high * vis),
            (target * low * islands[0], target * high * islands[1]) if islands else None)


def _draw_migration(layout):
    box = layout.box()
    box.label(text=f"Converted old marks: {_migration['density']} density, {_migration['zone']} zone, "
                   f"{_migration['margin']} margin, {_migration['size']} texture size", icon='INFO')
    nested = _migration['nested']
    if nested:
        box.label(text=f'{len(nested)} converted mark(s) below another mark: they multiply now', icon='ERROR')
        for name, parent in nested[:MAX_LISTED]:
            box.label(text=f'{name} below {parent}')
        if len(nested) > MAX_LISTED:
            box.label(text=f'... {len(nested) - MAX_LISTED} more (in the system console)')


def _cells(layout, *widths):
    """A table row: the tick and icon cell and one cell per width (shares of the rest; the last takes what is left)."""
    split = layout.split(factor=TICK_COLUMN)
    cells = [split.row(align=True)]
    left = 1.0
    for width in widths[:-1]:
        split = split.split(factor=width / left)
        cells.append(split.row(align=True))
        left -= width
    cells.append(split.row(align=True))
    return cells


def trim_start(text, width, measure):
    """The text with its start replaced by '...' so that measure(text) fits width; the end stays (decision 142)."""
    if width <= 0 or measure(text) <= width:
        return text
    for count in range(len(text) - 1, 0, -1):
        trimmed = '...' + text[-count:]
        if measure(trimmed) <= width:
            return trimmed
    return text[-1:]


def _fitted(context, text, share, padding=0):
    """The text as trim_start fits it into a column of this share of the panel. Blender cuts long text by itself, in a
    way it decides, so a name that would not fit is trimmed before it is drawn. Without a region (background): as it is."""
    region = context.region
    if region is None or region.width <= 1:
        return text
    scale = context.preferences.system.ui_scale
    blf.size(0, context.preferences.ui_styles[0].widget.points * scale)
    width = (region.width - (PANEL_PADDING + padding) * scale) * share - BUTTON_PADDING * scale
    return trim_start(text, width, lambda value: blf.dimensions(0, value)[0])


def _hint_icon(cell, kind):
    cell.operator(FSS_OT_UvTableHint.bl_idname, text='', icon=TABLE_ICONS[kind], emboss=False).kind = kind


def _no_tick(cell, kind):
    """The tick and icon cell of a row without a tick: the icon stays in its column."""
    cell.label(text='', icon='BLANK1')
    _hint_icon(cell, kind)


def _draw_mark_row(context, layout, kind, obj, title=None):
    """A row of the table: the tick, the object's factor, its direction and a button that selects it."""
    tick, value, turn, name = _cells(layout, VALUE_COLUMN, DIRECTION_COLUMN, NAME_COLUMN)
    tick.prop(obj, OWN_PROP, text='')
    _hint_icon(tick, kind)
    value.enabled = getattr(obj, OWN_PROP)
    low, high = _stored_range(obj)
    if high - low >= 5e-3:  # a range set in an earlier version stays visible and editable
        value.prop(obj, MIN_PROP, text='')
        value.prop(obj, MAX_PROP, text='')
    else:
        value.prop(obj, FACTOR_PROP, text='')
    turn.prop(obj, DIRECTION_MARK_PROP, text='')
    text = _fitted(context, title or obj.name, (1.0 - TICK_COLUMN) * NAME_COLUMN)
    name.operator(FSS_OT_UvSelectObject.bl_idname, text=text).target = obj.name


def _draw_material_row(context, layout, material):
    """A Material row: as _draw_mark_row without a direction; the name selects the objects that use the material."""
    tick, value, _turn, name = _cells(layout, VALUE_COLUMN, DIRECTION_COLUMN, NAME_COLUMN)
    tick.prop(material, MATERIAL_TICK_PROP, text='')
    _hint_icon(tick, 'MATERIAL')
    value.enabled = getattr(material, MATERIAL_TICK_PROP)
    value.prop(material, MATERIAL_FACTOR_PROP, text='')
    text = _fitted(context, material.name, (1.0 - TICK_COLUMN) * NAME_COLUMN)
    name.operator('fss.materials_select', text=text).material = material.name


def _draw_absent_row(layout, kind, text):
    """A dimmed row where the table has no object to show."""
    row = layout.row(align=True)
    row.active = False
    tick, rest = _cells(row, 1.0)
    _no_tick(tick, kind)
    rest.label(text=text)


def parent_rows(obj, zone):
    """The parents the table shows, topmost first: the direct parent and every one with a density mark up to the zone
    (without it). A mark is a number other than 1.00, ticked or not: an unticked one needs its row to be ticked again."""
    rows = []
    parent = obj.parent
    while parent is not None and parent != zone:
        if parent == obj.parent or _stored_range(parent) != (1.0, 1.0):
            rows.append(parent)
        parent = parent.parent
    return rows[::-1]


def bar_segments(low, high, mark=BAR_MARK):
    """[(width, kind)] of the density bar from left to right (shares of the bar; kind TRACK, RANGE or MARK). low and high
    are shares of the bar; the target is its middle, and the mark lies over everything else."""
    low, high = max(min(low, 1.0), 0.0), max(min(high, 1.0), 0.0)
    if high - low < BAR_MIN_RANGE:
        low = max(min(low, 1.0 - BAR_MIN_RANGE), 0.0)
        high = low + BAR_MIN_RANGE
    mark_low, mark_high = 0.5 - mark / 2.0, 0.5 + mark / 2.0
    points = sorted({0.0, 1.0, low, high, mark_low, mark_high})
    segments = []
    for left, right in zip(points, points[1:]):
        if right - left < 1e-6:
            continue
        middle = (left + right) / 2.0
        kind = 'MARK' if mark_low <= middle <= mark_high else 'RANGE' if low <= middle <= high else 'TRACK'
        segments.append((right - left, kind))
    return segments


def _draw_density_bar(layout, wm, low, high):
    """The result against the target density, as one bar. Blender cannot lay one widget over another in a panel, and
    gives no position of a row to draw at, so the bar is a row of colour fields, the target mark one of them (decision 143)."""
    bar = layout.row(align=True)
    bar.enabled = False  # the fields are colours to look at, a click must not open the colour picker
    bar.scale_y = BAR_SCALE
    segments = bar_segments(low, high)
    left = 1.0
    for width, kind in segments[:-1]:
        split = bar.split(factor=width / left, align=True)
        split.prop(wm, BAR_COLORS[kind][0], text='')
        bar = split
        left -= width
    bar.prop(wm, BAR_COLORS[segments[-1][1]][0], text='')


def _draw_scene_row(layout, scene):
    tick, value, freedom, check = _cells(layout, VALUE_COLUMN, 1.0 - VALUE_COLUMN - CHECK_COLUMN, CHECK_COLUMN)
    _no_tick(tick, 'SCENE')
    value.prop(scene, 'fss_uv_target_density', text='px/cm')
    freedom.prop(scene, 'fss_uv_density_freedom_min', text='Min')
    freedom.prop(scene, 'fss_uv_density_freedom_max', text='Max')
    check.operator(FSS_OT_UvPackCheckAll.bl_idname, text='Check')


def _draw_table(layout, context, scene, obj):
    from . import merge, uv_islands  # both import this module

    box = layout.box()
    table = box.column(align=True)
    _draw_scene_row(table, scene)
    if obj is None:
        table.label(text='No active object', icon='INFO')
        return
    zone = merge.nearest_zone(obj.parent)
    if zone is not None:
        _draw_mark_row(context, table, 'ZONE', zone, merge.logical_name(zone)[len(merge.ZONE_PREFIX):] or zone.name)
    else:
        _draw_absent_row(table, 'ZONE', 'this object is the zone' if merge.is_zone(obj) else 'no zone')
    parents = parent_rows(obj, zone)
    for parent in parents:
        _draw_mark_row(context, table, 'PARENT', parent)
    if not parents:
        _draw_absent_row(table, 'PARENT', 'the parent is the zone' if obj.parent else 'no parent')
    materials = object_materials(obj)
    for material in materials:
        _draw_material_row(context, table, material)
    if not materials:
        _draw_absent_row(table, 'MATERIAL', 'no material')
    _draw_mark_row(context, table, 'OBJECT', obj)
    summary = _object_visibility(obj)
    wm = context.window_manager
    tick, value, rest = _cells(table, VALUE_COLUMN, 1.0 - VALUE_COLUMN)
    tick.prop(obj, USE_VISIBILITY_PROP, text='')
    tick.prop(wm, 'fss_uv_islands_open', text='', emboss=False,
              icon='TRIA_DOWN' if wm.fss_uv_islands_open else 'TRIA_RIGHT')
    value.active = uses_visibility(obj)
    value.label(text=_island_text(summary))
    count = uv_islands.listed_count(obj, wm)
    count = summary.get('count') if count is None else count
    _hint_icon(rest, 'ISLANDS')
    rest.label(text='' if count is None else f"{count} island{'' if count == 1 else 's'}")
    box.separator(factor=0.5, type='LINE')
    (a, b), islands = result_range(obj, scene, summary)
    low, high = islands or (a, b)
    turn, source = direction(obj)
    text = next(item[1] for item in DIRECTIONS if item[0] == turn)
    result = box.column(align=True)
    blank, density_cell, turn_cell = _cells(result, VALUE_COLUMN + DIRECTION_COLUMN, NAME_COLUMN)
    blank.label(text='')
    density_cell.label(text=f'{low:.2f} - {high:.2f} px/cm')
    turn_cell.label(text=f'{text} ({source.name})' if source is not None and source != obj else text)
    target = max(target_density(scene), 1e-9)
    _blank, bar_cell = _cells(result, 1.0)
    _draw_density_bar(bar_cell, wm, low / (BAR_SPAN * target), high / (BAR_SPAN * target))
    uv_islands.draw(box, context, obj)


def texture_set_materials(context):
    """The materials of the selected mesh objects, the active object's first (decision 114)."""
    objects = sorted((o for o in context.selected_objects if o.type == 'MESH'), key=lambda o: o.name)
    active = context.active_object
    if active is not None:
        objects = [active] + [o for o in objects if o != active]
    materials = []
    for obj in objects:
        for slot in obj.material_slots:
            if slot.material is not None and slot.material not in materials:
                materials.append(slot.material)
    return materials


def last_result_text(material, short=False):
    """The Last run row of a texture set: the last Pack or Check All result of this session, or 'kept'; short (a list
    row): nothing before the first run."""
    if uv_pack.is_kept(material):
        return 'kept'
    result = _results.get(material.name)
    if result is None or result['mode'] == 'kept':
        return '' if short else 'not packed or checked yet'
    return uv_pack.result_text(result) + ('' if result['written'] else ' (checked)')


def texture_set_rows(context, materials):
    """(flags, order) of the texture set list over bpy.data.materials (FSS_UL_TextureSets.filter_items): shown are the
    materials of the selection, in texture_set_materials' order. Only reads, as drawing must."""
    position = {material.as_pointer(): index for index, material in enumerate(texture_set_materials(context))}
    flags, order = [], []
    rest = len(position)
    for material in materials:
        index = position.get(material.as_pointer())
        flags.append(0 if index is None else 1)
        if index is None:
            index, rest = rest, rest + 1
        order.append(index)
    return flags, order


def _get_active_index(wm):
    """The list's active row is kept by material name: adding a material moves the indices of bpy.data.materials,
    the name stays (a renamed material falls back to the first row)."""
    return bpy.data.materials.find(wm.fss_uv_pack_active_name)


def _set_active_index(wm, index):
    wm.fss_uv_pack_active_name = bpy.data.materials[index].name if 0 <= index < len(bpy.data.materials) else ''


def set_problems(material):
    """What the artist should know about a texture set, one sentence each (the row's warning icon and tooltip)."""
    problems = []
    if margin(material) < BLOCK_PIXELS:
        problems.append(f'Margin under {BLOCK_PIXELS} px: compressed 4x4 blocks bleed across islands')
    result = _results.get(material.name)
    if not result or uv_pack.is_kept(material):
        return problems
    if result.get('mode') == 'overflow':
        problems.append('Does not fit this texture size')
    if result.get('uv_zero_islands'):
        problems.append(f"{result['uv_zero_islands']} island(s) with triangles without UV area: re-unwrap them")
    if result.get('no_area_objects'):
        problems.append(f"Faces without area in {len(result['no_area_objects'])} object(s)")
    return problems


class FSS_OT_UvCheckSelect(bpy.types.Operator):
    """A texture set's name in Check Results: selects its objects; the tooltip has the set's result."""
    bl_idname = 'fss.uv_check_select'
    bl_label = 'Select Objects'
    bl_options = {'INTERNAL'}

    material: bpy.props.StringProperty(options={'HIDDEN'})

    @classmethod
    def description(cls, context, properties):
        result = _results.get(properties.material)
        if result is None:
            return properties.material
        width, height = result['extent_px']
        material = bpy.data.materials.get(properties.material)
        lines = [properties.material, f"Last run: {uv_pack.result_text(result)}{'' if result['written'] else ' (checked)'}",
                 f"Layout {width:.0f} x {height:.0f} px of {result['size']} x {result['size']}, "
                 f"the islands cover {result['fill_current_pct']:.0f} %",
                 f"Density at {result['t'] * 100:.0f} % of its range"]
        return chr(10).join(lines + (set_problems(material) if material else []) + ['Click: select the objects that use it'])

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        return bpy.ops.fss.materials_select(material=self.material)


class FSS_UL_CheckResults(bpy.types.UIList):
    """Every measured texture set: a list over bpy.data.materials that shows only those, so nothing is written while drawing."""
    bl_idname = 'FSS_UL_check_results'

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        result = _results.get(item.name)
        if result is None or result.get('mode') in ('kept', 'empty'):
            return
        layout.active = not is_stale(result)
        name, used, room = _result_cells(layout)
        over = result['mode'] == 'overflow'
        name.alignment = 'LEFT'
        name.operator(FSS_OT_UvCheckSelect.bl_idname, text=_fitted(context, item.name, RESULT_NAME_COLUMN, LIST_PADDING),
                      icon='ERROR' if over else 'RESTRICT_SELECT_OFF', emboss=False).material = item.name
        width, height = result['extent_px']
        used.alert = over
        used.progress(factor=result_used(result), type='BAR', text=f"{width:.0f} x {height:.0f} / {result['size']}")
        room.alert = over
        room.label(text='full' if result['mode'] == 'fit' else f'x{result_room(result):.2f}')

    def filter_items(self, context, data, propname):
        items = getattr(data, propname)
        flags, order = result_order(items)
        flags = [self.bitflag_filter_item if shown else 0 for shown in flags]
        if self.filter_name:
            named = bpy.types.UI_UL_list.filter_items_by_name(self.filter_name, self.bitflag_filter_item, items, 'name')
            flags = [flag & by_name for flag, by_name in zip(flags, named)]
        return flags, order


class FSS_UL_TextureSets(bpy.types.UIList):
    """The texture sets of the selection (decision 121): a list over bpy.data.materials that shows only the
    selection's materials, so nothing is written while drawing."""
    bl_idname = 'FSS_UL_texture_sets'

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        kept = uv_pack.is_kept(item)
        tick, name, size, gap, pack = _cells(layout, SET_NAME_COLUMN, SET_SIZE_COLUMN, SET_MARGIN_COLUMN, SET_PACK_COLUMN)
        tick.prop(item, KEEP_UVS_PROP, text='', invert_checkbox=True)
        tick.operator('fss.materials_select', text='', icon='RESTRICT_SELECT_OFF', emboss=False).material = item.name
        for cell in (name, size, gap):
            cell.active = not kept
        name.alignment = 'LEFT'
        text = _fitted(context, item.name, (1.0 - TICK_COLUMN) * SET_NAME_COLUMN, LIST_PADDING)
        name.operator(FSS_OT_UvTextureSetInfo.bl_idname, text=text, icon='ERROR' if set_problems(item) else 'NONE',
                      emboss=False).material = item.name
        size.prop(item, SIZE_PROP, text='')
        gap.prop(item, 'fss_uv_margin_px', text='')
        pack.enabled = not kept
        pack.operator(FSS_OT_UvPackTextureSet.bl_idname, text='Pack').material = item.name

    def filter_items(self, context, data, propname):
        items = getattr(data, propname)
        flags, order = texture_set_rows(context, items)
        flags = [self.bitflag_filter_item if shown else 0 for shown in flags]
        if self.filter_name:
            named = bpy.types.UI_UL_list.filter_items_by_name(self.filter_name, self.bitflag_filter_item, items, 'name')
            flags = [flag & by_name for flag, by_name in zip(flags, named)]
        return flags, order


def _draw_texture_sets(layout, context):
    materials = texture_set_materials(context)
    box = layout.box()
    if not materials:
        box.label(text='Select objects to list their texture sets', icon='INFO')
        return
    box.template_list(FSS_UL_TextureSets.bl_idname, '', bpy.data, 'materials', context.window_manager,
                      'fss_uv_pack_active', rows=min(len(materials), LIST_ROWS))
    ticked = sum(1 for material in materials if not uv_pack.is_kept(material))
    row = box.row()
    row.enabled = ticked > 0
    row.operator(FSS_OT_UvPackAll.bl_idname, text=f'Pack All ({ticked})', icon='UV')


def _store_result(result):
    result['generation'] = _settings_generation
    _results[result['set']] = result
    _pack_result_changed()


def measured_results():
    """The results with a layout, of texture sets that still exist: not Keep UVs, not empty."""
    return [result for name, result in _results.items() if result.get('mode') not in ('kept', 'empty')
            and (name == uv_pack.set_name(None) or name in bpy.data.materials)]


def result_room(result):
    """How far the density could rise with the layout still fitting: the layout grows about as the density does, so 1 / k.
    A set the packer already had to lower inside its range has none. Below 1: an overflow, how far it would have to drop."""
    return 1.0 if result['mode'] == 'fit' else 1.0 / max(result['k'], 1e-9)


def result_used(result):
    """The share of the texture the layout's bounding box takes, 0 to 1."""
    width, height = result['extent_px']
    return min(width * height / max(result['size'] ** 2, 1), 1.0)


def is_stale(result):
    return result.get('generation', _settings_generation) != _settings_generation


def result_order(materials):
    """(flags, order) of the Check Results table over bpy.data.materials: the measured sets, tightest first."""
    def result_of(material):
        result = _results.get(material.name)
        return result if result is not None and result.get('mode') not in ('kept', 'empty') else None

    shown = sorted((index for index, material in enumerate(materials) if result_of(material) is not None),
                   key=lambda index: (result_room(result_of(materials[index])), materials[index].name))
    order = [0] * len(materials)
    flags = [0] * len(materials)
    for position, index in enumerate(shown):
        order[index], flags[index] = position, 1
    rest = len(shown)
    for index, flag in enumerate(flags):
        if not flag:
            order[index], rest = rest, rest + 1
    return flags, order


def results_summary(target):
    """(icon, headline, detail) over all measured sets. What limits a change of the scene's target is the tightest set."""
    results = measured_results()
    rooms = sorted(result_room(result) for result in results)
    count = len(results)
    overflow = sum(1 for result in results if result['mode'] == 'overflow')
    if overflow:
        return ('ERROR', f'{overflow} of {count} sets overflow',
                f'Target {target * rooms[0]:.2f} px/cm (x{rooms[0]:.2f}), or larger textures')
    full = sum(1 for room in rooms if room < FULL_ROOM)
    if full:
        return ('CHECKMARK', f'All {count} sets fit', f"{full} full, typical room x{rooms[count // 2]:.2f}")
    return ('CHECKMARK', f'All {count} sets fit', f'Target can rise x{rooms[0]:.2f}, to {target * rooms[0]:.2f} px/cm')


def _result_cells(layout):
    split = layout.split(factor=RESULT_NAME_COLUMN)
    name = split.row(align=True)
    split = split.split(factor=RESULT_BAR_COLUMN / (1.0 - RESULT_NAME_COLUMN))
    return name, split.row(align=True), split.row(align=True)


def _draw_results(layout, context):
    icon, headline, detail = results_summary(target_density(context.scene))
    head = layout.column(align=True)
    head.label(text=headline, icon=icon)
    head.label(text=detail)
    if any(is_stale(result) for result in measured_results()):
        head.label(text='Numbers changed: press Check again', icon='INFO')
    name, used, room = _result_cells(layout)
    name.label(text='Texture set')
    used.label(text='Layout / texture')
    room.label(text='Room')
    layout.template_list(FSS_UL_CheckResults.bl_idname, 'check_results', bpy.data, 'materials', context.window_manager,
                         'fss_uv_pack_active', rows=min(len(measured_results()), LIST_ROWS))


def _draw_progress(layout):
    p = _progress
    box = layout.box()
    if _several_sets(p):
        box.progress(factor=(p['index'] - 1 + p['fraction']) / max(p['count'], 1), type='BAR',
                     text=f"{p['verb']} {p['index']} of {p['count']}: {p['set']}")
        box.label(text=p['stage'] or 'Starting', icon='TIME')
        box.operator(FSS_OT_UvPackCancel.bl_idname, text='Cancel', icon='CANCEL')
        box.label(text='Cancel and Esc stop after the texture set in work')
    else:
        box.progress(factor=p['fraction'], type='BAR', text=f"Packing {p['set']}: {int(p['fraction'] * 100)} %")
        box.label(text=p['stage'] or 'Starting', icon='TIME')
        box.label(text='Blender waits until each pack is done')


def _several_sets(progress):
    """Check All, or Pack All with more than one set: shown with its count, and it can be cancelled between sets."""
    return progress['verb'] == 'Checking' or progress['count'] > 1


SPACES = ('VIEW_3D', 'IMAGE_EDITOR')  # the sidebars that draw the Packing section (decision 119)


def _redraw_panels():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type in SPACES:
                area.tag_redraw()


def _status(text):
    try:
        bpy.context.workspace.status_text_set(text)
    except AttributeError:  # no workspace (background)
        pass


def _on_stage(stage, fraction):
    """uv_pack progress: the stage in the status bar, and the sidebar drawn at once (Blender blocks in each pack). The bar
    never goes back: a new round of packs after a margin problem keeps it where it is."""
    from .uv_autoseam import _redraw_sidebar_now  # uv_autoseam imports this module
    if _progress is None:
        return
    _progress['stage'] = stage
    _progress['fraction'] = max(_progress['fraction'], fraction)
    count = f" {_progress['index']}/{_progress['count']}" if _several_sets(_progress) else ''
    _status(f"FSS {_progress['verb']}{count}: {_progress['set']} ({stage})...")
    _redraw_sidebar_now(SPACES)


def _summary(result):
    text = f"{result['set']}: {uv_pack.result_text(result)}"
    if result.get('no_area_objects'):
        text += f"; faces without area in {len(result['no_area_objects'])} object(s)"
    if result.get('uv_zero_islands'):
        text += f"; {result['uv_zero_islands']} island(s) with triangles without UV area"
    return text


class FSS_OT_UvPackTextureSet(bpy.types.Operator):
    bl_idname = 'fss.uv_pack_texture_set'
    bl_label = 'Pack Texture Set'
    bl_description = ('Pack this texture set: every face with this material in the view layer, also on objects that '
                      'are not selected, each island at its texel density. Replaces their UVs')
    bl_options = {'REGISTER', 'UNDO'}

    material: bpy.props.StringProperty(name='Material', description='Material of the texture set to pack')

    @classmethod
    def poll(cls, context):
        return _progress is None and context.mode in {'OBJECT', 'EDIT_MESH'}

    def execute(self, context):
        global _progress
        material = bpy.data.materials.get(self.material)
        if material is None:
            self.report({'ERROR'}, f"No material '{self.material}'")
            return {'CANCELLED'}
        if uv_pack.is_kept(material):
            self.report({'WARNING'}, f'{material.name}: Keep UVs is set, nothing packed')
            return {'CANCELLED'}
        self._material = material
        self._selected = {o.name for o in context.selected_objects}
        if bpy.app.background:
            return self._run(context)
        # draw the progress first: each pack is one Blender call, Blender waits until it is done
        _progress = {'verb': 'Packing', 'index': 1, 'count': 1, 'set': material.name, 'stage': '', 'fraction': 0.0}
        _status(f'FSS Packing: {material.name}...')
        _redraw_panels()
        self._timer = context.window_manager.event_timer_add(0.05, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        global _progress
        if event.type != 'TIMER':
            return {'RUNNING_MODAL'}
        context.window_manager.event_timer_remove(self._timer)
        try:
            return self._run(context)
        except Exception as ex:
            self.report({'ERROR'}, f'Packing {self._material.name} stopped: {ex}')
            return {'CANCELLED'}
        finally:
            _progress = None
            _status(None)
            _redraw_panels()

    def _run(self, context):
        result = uv_pack.pack(self._material, progress=None if bpy.app.background else _on_stage)
        _store_result(result)
        uv_pack.write_report([result], 'Pack', result['time_s'], selected=self._selected)
        extra = [name for name in result.get('objects', []) if name not in self._selected]
        text = _summary(result) + (f'; {len(extra)} object(s) not selected included' if extra else '')
        self.report({'WARNING'} if result.get('no_area_objects') or result.get('uv_zero_islands') else {'INFO'},
                    f"{text} ({result['time_s']:.1f} s). See '{uv_pack.REPORT_TEXT_NAME}'.")
        return {'FINISHED'}


class _SetRunner:
    """One texture set after the other, with progress and Cancel: Check All and Pack All."""
    _timer = None
    _verb = ''
    _done_word = ''
    _report_kind = ''

    @classmethod
    def poll(cls, context):
        return _progress is None and context.mode in {'OBJECT', 'EDIT_MESH'}

    def _choose(self, context):
        raise NotImplementedError

    def _work(self, material, progress):
        raise NotImplementedError

    def _report_selected(self, context):
        return None

    def execute(self, context):
        global _progress, _cancel_requested
        self._sets = self._choose(context)
        self._selected = self._report_selected(context)
        self._done = []
        self._vis_cache = {}
        self._index = 0
        self._announced = False
        self._t_start = time.perf_counter()
        if bpy.app.background:
            for material in self._sets:
                self._step(material)
            return self._finish(context)
        _cancel_requested = False
        _progress = {'verb': self._verb, 'index': 1, 'count': len(self._sets), 'set': '', 'stage': '', 'fraction': 0.0}
        self._timer = context.window_manager.event_timer_add(0.01, window=context.window)
        context.window_manager.modal_handler_add(self)
        _redraw_panels()
        return {'RUNNING_MODAL'}

    def _step(self, material):
        result = self._work(material, None if bpy.app.background else _on_stage)
        _store_result(result)
        self._done.append(result)

    def _finish(self, context, cancelled=False):
        global _progress, _cancel_requested
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        _progress = None
        _cancel_requested = False
        _status(None)
        _redraw_panels()
        seconds = time.perf_counter() - self._t_start
        uv_pack.write_report(self._done, self._report_kind, seconds, selected=self._selected, cancelled=cancelled)
        over = sum(1 for r in self._done if r['mode'] == 'overflow')
        kept = sum(1 for r in self._done if r['mode'] == 'kept')
        needles = sum(1 for r in self._done if r.get('uv_zero_islands'))
        self.report({'WARNING'} if needles else {'INFO'},
                    f"{self._done_word} {len(self._done)} of {len(self._sets)} texture set(s) in {seconds:.1f} s"
                    f"{', cancelled' if cancelled else ''}: {over} overflow, {kept} kept"
                    + (f", {needles} with triangles without UV area" if needles else '')
                    + f". See '{uv_pack.REPORT_TEXT_NAME}'.")
        return {'FINISHED'}

    def modal(self, context, event):
        if event.type == 'ESC' or _cancel_requested:
            return self._finish(context, cancelled=True)
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}
        if self._index >= len(self._sets):
            return self._finish(context)
        material = self._sets[self._index]
        if not self._announced:
            # show which set comes next before Blender blocks on it
            _progress.update(index=self._index + 1, set=uv_pack.set_name(material), stage='Starting', fraction=0.0)
            _status(f"FSS {self._verb} {self._index + 1}/{len(self._sets)}: {uv_pack.set_name(material)}...")
            _redraw_panels()
            self._announced = True
            return {'RUNNING_MODAL'}
        try:
            self._step(material)
        except Exception as ex:
            self._finish(context, cancelled=True)
            self.report({'ERROR'}, f'{self._verb} stopped at {uv_pack.set_name(material)}: {ex}')
            return {'CANCELLED'}
        self._index += 1
        self._announced = False
        return {'RUNNING_MODAL'}


class FSS_OT_UvPackCheckAll(_SetRunner, bpy.types.Operator):
    bl_idname = 'fss.uv_pack_check_all'
    bl_label = 'Check All'
    bl_description = ('Measure every texture set of the view layer as Pack would, without writing UVs: which sets fit, '
                      'leave space or overflow, and the texture size each one needs')
    bl_options = {'REGISTER'}

    _verb = 'Checking'
    _done_word = 'Checked'
    _report_kind = 'Check All'

    def _choose(self, context):
        return uv_pack.texture_sets(context.view_layer)

    def _work(self, material, progress):
        return uv_pack.measure(material, progress=progress, vis_cache=self._vis_cache)


class FSS_OT_UvPackAll(_SetRunner, bpy.types.Operator):
    bl_idname = 'fss.uv_pack_all'
    bl_label = 'Pack All'
    bl_description = ('Pack every ticked texture set of the list, one after the other: all faces with those materials in '
                      'the view layer, also on objects that are not selected. Replaces their UVs')
    bl_options = {'REGISTER', 'UNDO'}

    _verb = 'Packing'
    _done_word = 'Packed'
    _report_kind = 'Pack'

    def _choose(self, context):
        return [material for material in texture_set_materials(context) if not uv_pack.is_kept(material)]

    def _report_selected(self, context):
        return {o.name for o in context.selected_objects}

    def _work(self, material, progress):
        return uv_pack.pack(material, progress=progress, vis_cache=self._vis_cache)


class FSS_OT_UvPackCancel(bpy.types.Operator):
    bl_idname = 'fss.uv_pack_cancel'
    bl_label = 'Cancel'
    bl_description = 'Stop after the texture set in work (as Esc)'
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return _progress is not None and _several_sets(_progress)

    def execute(self, context):
        global _cancel_requested
        _cancel_requested = True
        return {'FINISHED'}


class _PackingSection:
    """The Packing section, drawn by the 3D viewport's and the UV editor's panel (decision 119)."""

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        if _progress is not None:
            # Pack or Check All in progress: only the progress (the active object may be the temporary mesh)
            _draw_progress(layout)
            return
        if _migration:
            _draw_migration(layout)
        _draw_table(layout, context, scene, context.active_object)
        _draw_texture_sets(layout, context)


class _PackingAdvanced:
    bl_label = 'Advanced'
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 1

    def draw(self, context):
        self.layout.label(text='Whole scene', icon='SCENE_DATA')
        _labelled(self.layout, 'Layout corner').prop(context.scene, 'fss_uv_pack_corner', text='')
        _labelled(self.layout, 'Partly Seen Islands').prop(context.scene, 'fss_uv_partly_seen_value', text='', slider=True)


class _PackingResults:
    bl_label = 'Check Results'
    bl_order = 0

    @classmethod
    def poll(cls, context):
        return _progress is None and bool(measured_results())

    def draw(self, context):
        _draw_results(self.layout, context)


class FSS_PT_UvMarks(_PackingSection, bpy.types.Panel):
    bl_idname = 'FSS_PT_uv_marks'
    bl_label = 'UV Auto Packing'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'FSS MSFS Tools'
    bl_order = 7
    bl_options = {'DEFAULT_CLOSED'}


class FSS_PT_UvMarksImageEditor(_PackingSection, bpy.types.Panel):
    """UV Auto Packing in the UV editor's sidebar (the Image Editor's UI region)."""
    bl_idname = 'FSS_PT_uv_marks_image'
    bl_label = 'UV Auto Packing'
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category = 'FSS MSFS Tools'

    @classmethod
    def poll(cls, context):
        # Only in the UV editor: the image viewer shows no UVs to pack against
        return getattr(context.space_data, 'mode', 'UV') == 'UV'


class FSS_PT_UvMarksResults(_PackingResults, bpy.types.Panel):
    bl_idname = 'FSS_PT_uv_marks_results'
    bl_parent_id = 'FSS_PT_uv_marks'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'FSS MSFS Tools'


class FSS_PT_UvMarksImageEditorResults(_PackingResults, bpy.types.Panel):
    bl_idname = 'FSS_PT_uv_marks_image_results'
    bl_parent_id = 'FSS_PT_uv_marks_image'
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category = 'FSS MSFS Tools'


class FSS_PT_UvMarksAdvanced(_PackingAdvanced, bpy.types.Panel):
    bl_idname = 'FSS_PT_uv_marks_advanced'
    bl_parent_id = 'FSS_PT_uv_marks'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'FSS MSFS Tools'


class FSS_PT_UvMarksImageEditorAdvanced(_PackingAdvanced, bpy.types.Panel):
    bl_idname = 'FSS_PT_uv_marks_image_advanced'
    bl_parent_id = 'FSS_PT_uv_marks_image'
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category = 'FSS MSFS Tools'


CLASSES = (FSS_OT_UvTableHint, FSS_OT_UvTextureSetInfo, FSS_OT_UvSelectObject, FSS_OT_UvSetSkipAutoseam, FSS_OT_UvPackTextureSet,
           FSS_OT_UvPackCheckAll, FSS_OT_UvPackAll, FSS_OT_UvPackCancel, FSS_OT_UvCheckSelect, FSS_UL_TextureSets, FSS_UL_CheckResults,
           FSS_PT_UvMarks, FSS_PT_UvMarksImageEditor, FSS_PT_UvMarksResults, FSS_PT_UvMarksImageEditorResults,
           FSS_PT_UvMarksAdvanced, FSS_PT_UvMarksImageEditorAdvanced)
HANDLERS = ((bpy.app.handlers.load_post, _on_load_post),
            (bpy.app.handlers.depsgraph_update_post, _on_depsgraph_update_post))


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    factor = dict(min=0.01, max=10.0, soft_min=0.1, soft_max=4.0, precision=2)
    bpy.types.Object.fss_uv_density_own = bpy.props.BoolProperty(
        name='Use Density Factor', default=True, update=_marks_changed,
        description='Use the texel density factor of this row: it multiplies the factors above it, and everything '
                    'below takes it too. Unticked, the number is kept but ignored (Alt: all selected objects)')
    bpy.types.Object.fss_uv_density_min = bpy.props.FloatProperty(
        name='Min', default=1.0, update=_keep_order(MIN_PROP, MAX_PROP, MIN_PROP),
        description='Lowest texel density factor of this mark (Alt+drag sets it on all selected objects)', **factor)
    bpy.types.Object.fss_uv_density_max = bpy.props.FloatProperty(
        name='Max', default=1.0, update=_keep_order(MIN_PROP, MAX_PROP, MAX_PROP),
        description='Highest texel density factor of this mark (Alt+drag sets it on all selected objects)', **factor)
    bpy.types.Object.fss_uv_density_factor = bpy.props.FloatProperty(
        name='Density Factor', get=_get_factor, set=_set_factor,
        description='Texel density factor of this row, used when its tick is on (Alt: all selected objects)', **factor)
    bpy.types.Object.fss_uv_use_visibility = bpy.props.BoolProperty(
        name='Use Visibility', default=True, update=_marks_changed,
        description="Use the visibility of this object's islands. Unticked, they count as fully visible (x1.00)")
    bpy.types.Object.fss_uv_direction_mark = bpy.props.EnumProperty(
        name='Island Direction', items=DIRECTIONS, get=_get_direction_mark, set=_set_direction_mark,
        description='How the islands may rotate when packed; everything below that is Free takes it too '
                    '(Alt: all selected objects)')
    bpy.types.Scene.fss_uv_target_density = bpy.props.FloatProperty(
        name='Target Density', default=DEFAULT_TARGET, update=_marks_changed, min=0.01, soft_min=1.0, soft_max=100.0, precision=2,
        description='Texel density at factor 1.0 for the whole scene, in pixels per centimetre (20.48 is 2048 px '
                    'per metre)')
    bpy.types.Scene.fss_uv_partly_seen_value = bpy.props.FloatProperty(
        name='Partly Seen Islands', default=DEFAULT_PARTLY_SEEN, update=_marks_changed, min=0.0, max=1.0, precision=2,
        description='What happens to an island when only part of it is seen. 1: any seen part makes the whole island visible. '
                    '0.75: scaled by the seen share, biased towards visible. 0.5: scaled by the seen share of its area. '
                    '0.25: biased towards scaling down. 0: only an island seen whole counts, any other gets the minimum. '
                    'Lower saves texture but blurs the part you see. Used by Pack and Check All, with no new Update Visibility')
    bpy.types.Scene.fss_uv_pack_corner = bpy.props.EnumProperty(
        name='Layout Corner', items=PACK_CORNERS, default='BOTTOM_LEFT',
        description='The corner of the texture Pack moves each layout to, as one block. Changes the UVs at the next '
                    'Pack only, so choose it before painting')
    names = ('fss_uv_density_freedom_min', 'fss_uv_density_freedom_max')
    bpy.types.Scene.fss_uv_density_freedom_min = bpy.props.FloatProperty(
        name='Min', default=DEFAULT_FREEDOM[0], update=_keep_order(*names, names[0]),
        description='Lowest factor the packer may give any island, before the density marks', **factor)
    bpy.types.Scene.fss_uv_density_freedom_max = bpy.props.FloatProperty(
        name='Max', default=DEFAULT_FREEDOM[1], update=_keep_order(*names, names[1]),
        description='Highest factor the packer may give any island, before the density marks', **factor)
    bpy.types.Material.fss_uv_texture_size = bpy.props.EnumProperty(
        name='Texture Size', items=TEXTURE_SIZES, default=DEFAULT_TEXTURE, update=_marks_changed,
        description='Size of this square texture set in pixels per side')
    bpy.types.Material.fss_uv_margin_px = bpy.props.IntProperty(
        name='UV Margin', default=DEFAULT_MARGIN, update=_marks_changed, min=0, soft_max=64, subtype='PIXEL',
        description='The gap between two islands in pixels of this texture set (8 keeps islands apart to the second '
                    'mip level after 4x4 block compression)')
    bpy.types.Material.fss_uv_keep_uvs = bpy.props.BoolProperty(
        name='Keep UVs', default=False, update=_marks_changed,
        description='Leave this texture set out of Pack and Check All and keep its UVs (fur and hair cards, decal '
                    'sheets, colliders). In the packing table: unticked')
    setattr(bpy.types.Material, MATERIAL_TICK_PROP, bpy.props.BoolProperty(
        name='Use Material Factor', default=True, update=_marks_changed,
        description='Use the texel density factor of this material. Unticked, the number is kept but ignored'))
    setattr(bpy.types.Material, MATERIAL_FACTOR_PROP, bpy.props.FloatProperty(
        name='Material Factor', default=1.0, update=_marks_changed,
        description='Texel density factor of every island with this material, on all objects, used when its tick is on',
        **factor))
    bpy.types.WindowManager.fss_uv_pack_active_name = bpy.props.StringProperty(name='Active Texture Set')
    bar_tips = {'TRACK': 'From 0 to twice the target density', 'RANGE': 'The range of the density of this object',
                'MARK': 'The target density of the scene'}
    for kind, (name, color) in BAR_COLORS.items():
        setattr(bpy.types.WindowManager, name, bpy.props.FloatVectorProperty(
            name='Density Bar', subtype='COLOR', size=3, min=0.0, max=1.0, default=color, description=bar_tips[kind]))
    bpy.types.WindowManager.fss_uv_pack_active = bpy.props.IntProperty(
        name='Active Texture Set', get=_get_active_index, set=_set_active_index,
        description='The highlighted row of the texture set table')
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
    _results.clear()
    del bpy.types.WindowManager.fss_uv_pack_active
    del bpy.types.WindowManager.fss_uv_pack_active_name
    for name, _color in BAR_COLORS.values():
        delattr(bpy.types.WindowManager, name)
    for name in (MATERIAL_FACTOR_PROP, MATERIAL_TICK_PROP, KEEP_UVS_PROP, 'fss_uv_margin_px', SIZE_PROP):
        delattr(bpy.types.Material, name)
    for name in ('fss_uv_density_freedom_max', 'fss_uv_density_freedom_min', 'fss_uv_pack_corner', 'fss_uv_partly_seen_value', 'fss_uv_target_density'):
        delattr(bpy.types.Scene, name)
    for name in (DIRECTION_MARK_PROP, USE_VISIBILITY_PROP, FACTOR_PROP, MAX_PROP, MIN_PROP, OWN_PROP):
        delattr(bpy.types.Object, name)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
