"""Materials panel (phase 1, read-only): every material of the file with its users, zones, kind and surface.

Material-management journal (20261028.material-management.md), decisions 1, 3, 7 to 9 and 11, hand-off of Session 5.
Refresh fills Scene.fss_materials from the view layer; the panel only reads those rows, so a redraw never counts users
or areas, and nothing is written while drawing. The panel does not follow changes until the next Refresh. Nothing here
changes objects or tags: Refresh writes only Scene.fss_materials, the select operator only the selection. The one
control that changes data is the active material's Keep UVs checkbox (decision 14: Material.fss_uv_keep_uvs, the same
property as in Packing), which Blender writes on the artist's click; a kept material shows "kept" instead of the
estimate (decision 13), read from the material when drawing, so it shows without Refresh.

- Used: a mesh object of the view layer (visible or hidden) has a face whose material index points at a slot with the
  material. A material only in an empty slot, only on objects outside the view layer, or in no slot is never used.
- Zones: the nearest @ZONE_ empty at or above each using object (merge.nearest_zone); objects outside every zone count
  as (no zone), which counts as a zone for "shared across zones".
- Kinds (decisions 3, 9, 11): transparent when the MSFS alpha mode is Blend, emissive when an MSFS emissive texture is
  assigned; read with getattr, so the panel works without the exporter add-on.
- Area: world-space 3D area of the faces using the material. A mesh shared by several objects counts once (its UVs are
  shared), measured on its first user by name that uses the material, and in that user's zone; objects count each.
- Estimate (decision 12): the side of a square that holds the faces at the top of their density range, with each
  object's visibility, without packing or margins: sqrt(sum of area_cm2 x (target density x high end of
  uv_marks.density(obj) x visibility)^2). Visibility is the object score the Packing section shows
  (uv_marks._object_visibility: never below 0.1, never seen 0.1), 1.0 when the .blend is unsaved, its .visibility
  file is missing or the mesh is stale; a shared mesh uses its first user, as for the area. The file is read once per
  Refresh (visibility_core's cache). Check All (uv_pack.measure) gives the packed truth.
"""

import math
import time
from pathlib import Path

import bpy
import numpy as np

from . import merge, uv_marks, uv_pack, visibility_core

NO_ZONE = '(no zone)'
NO_ZONE_SHORT = '–'  # an en dash: a list row's zone column for objects outside every zone
LIST_ROWS = 6
ICON_WARNING = 'ERROR'
ICON_TRANSPARENT = 'XRAY'
ICON_EMISSIVE = 'LIGHT'


def in_scope(material):
    """Every material of the file except grease pencil materials."""
    return material is not None and not material.is_grease_pencil


def is_transparent(material):
    """Decision 9: MSFS alpha mode Blend (an alpha value below 1 does not count: alpha can come from a texture)."""
    return getattr(material, 'msfs_alpha_mode', None) == 'BLEND'


def is_emissive(material):
    """Decision 3: an emissive texture is assigned."""
    return getattr(material, 'msfs_emissive_texture', None) is not None


def zone_label(zone):
    """The zone's name without the @ZONE_ marker, or (no zone)."""
    if zone is None:
        return NO_ZONE
    name = merge.logical_name(zone)
    return name[len(merge.ZONE_PREFIX):] or name


def _uses(obj, material_indices, material):
    """True when a face of obj (its material indices given) points at a slot holding material."""
    slots = [slot.material for slot in obj.material_slots]
    return any(index < len(slots) and slots[index] == material for index in material_indices)


def using_objects(view_layer, material, visible_only=False):
    """The mesh objects of the view layer with a face that uses material, by name."""
    found = []
    for obj in view_layer.objects:
        if obj.type != 'MESH' or obj.data is None or not len(obj.data.polygons):
            continue
        if visible_only and not obj.visible_get(view_layer=view_layer):
            continue
        if not any(slot.material == material for slot in obj.material_slots):
            continue
        mi = np.zeros(len(obj.data.polygons), np.int64)
        obj.data.polygons.foreach_get('material_index', mi)
        if _uses(obj, np.unique(mi).tolist(), material):
            found.append(obj)
    return sorted(found, key=lambda obj: obj.name)


class _Stats:
    def __init__(self):
        self.objects = []        # using objects
        self.hidden = 0
        self.shared_meshes = 0   # meshes with more than one user of this material
        self.zones = {}          # zone empty name ('' outside every zone) -> [label, objects, area m2]
        self.area = 0.0          # m2
        self.estimate_sq = 0.0   # px^2
        self.with_visibility = False  # an object measured for the estimate had visibility data


def visibility_reader():
    """A function obj -> visibility factor, or None without data (unsaved .blend, no .visibility file, a stale mesh
    or one not in the file). The object score as the Packing section's Visibility row reads it
    (uv_marks._object_visibility), without scoring islands: the file is loaded once (visibility_core's cache) and the
    stale meshes are found once."""
    if not bpy.data.filepath:
        return lambda obj: None
    vis_path = Path(bpy.data.filepath).with_suffix('.visibility')
    if not vis_path.exists():
        return lambda obj: None
    try:
        meta, data, stale = visibility_core.load_visibility_file(vis_path, scene_meshes=bpy.data.meshes)
    except Exception:
        return lambda obj: None
    stale = set(stale)
    counts = meta.get('mesh_face_counts', {})
    files = set(data.files)
    summaries = meta.get('object_summaries', {})

    def factor(obj):
        me = obj.data
        key = me.name.replace('/', '_').replace('\\', '_') + '__face_scores'
        if me.name in stale or key not in files:
            return None
        # the saved face count; the face score array itself only when the file lists no count for the mesh
        saved = counts.get(me.name)
        if (saved if saved is not None else len(data[key])) != len(me.polygons):
            return None
        summary = summaries.get(obj.name, {})
        if summary.get('never_seen', False):
            return uv_marks.NEVER_SEEN_FACTOR
        return uv_marks.visibility_factor(summary.get('score', 1.0))

    return factor


def scan(context):
    """{material: _Stats} over the materials in scope, from the view layer (reads only)."""
    scene = context.scene
    view_layer = context.view_layer
    stats = {material: _Stats() for material in bpy.data.materials if in_scope(material)}
    target = uv_marks.target_density(scene)
    visibility = visibility_reader()
    by_mesh = {}
    for obj in view_layer.objects:
        if obj.type == 'MESH' and obj.data is not None and len(obj.data.polygons):
            by_mesh.setdefault(obj.data, []).append(obj)
    zones, densities = {}, {}

    def zone_of(obj):
        if obj not in zones:
            zone = merge.nearest_zone(obj)
            zones[obj] = (zone.name if zone is not None else '', zone_label(zone))
        return zones[obj]

    for me, users in by_mesh.items():
        users.sort(key=lambda obj: obj.name)
        mi = np.zeros(len(me.polygons), np.int64)
        me.polygons.foreach_get('material_index', mi)
        used = np.unique(mi).tolist()
        measured = set()   # materials whose area this mesh has given already (on its first user using them)
        mesh_users = {}    # material -> users of this mesh
        for obj in users:
            slots = [slot.material for slot in obj.material_slots]
            materials = {slots[index] for index in used if index < len(slots)}
            materials = [material for material in materials if material in stats]
            if not materials:
                continue
            visible = obj.visible_get(view_layer=view_layer)
            zone_key, label = zone_of(obj)
            areas = None
            for material in materials:
                entry = stats[material]
                entry.objects.append(obj)
                entry.hidden += not visible
                mesh_users.setdefault(material, []).append(obj)
                zone = entry.zones.setdefault(zone_key, [label, 0, 0.0])
                zone[1] += 1
                if material in measured:
                    continue
                measured.add(material)
                if areas is None:
                    face_cm2 = uv_pack.face_areas_cm2(obj, scene)
                    # faces whose index lies past the last slot use no material (as uv_pack counts them)
                    areas = np.bincount(np.minimum(mi, len(slots)), weights=face_cm2, minlength=len(slots) + 1)
                    if obj not in densities:
                        vis = visibility(obj)
                        densities[obj] = (uv_marks.density(obj, scene)[0][1], vis)
                high, vis = densities[obj]
                cm2 = sum(areas[index] for index, slot in enumerate(slots) if slot == material)
                entry.area += cm2 * 1e-4
                zone[2] += cm2 * 1e-4
                entry.estimate_sq += cm2 * (target * high * (1.0 if vis is None else vis)) ** 2
                entry.with_visibility |= vis is not None
        for material, material_users in mesh_users.items():
            if len(material_users) > 1:
                stats[material].shared_meshes += 1
    return stats


def _zone_order(item):
    key, (label, _objects, _area) = item
    return (key == '', label.lower(), key)


class FSS_MaterialZone(bpy.types.PropertyGroup):
    # name (built in) is the zone's label: the zone empty's name without @ZONE_, or (no zone)
    zone: bpy.props.StringProperty()  # the zone empty's object name, '' outside every zone
    objects: bpy.props.IntProperty()
    area: bpy.props.FloatProperty()  # m2


class FSS_MaterialRow(bpy.types.PropertyGroup):
    # name (built in) is the material name, so the list's name filter works
    objects: bpy.props.IntProperty()
    hidden: bpy.props.IntProperty()
    shared_meshes: bpy.props.IntProperty()
    zone_names: bpy.props.StringProperty()  # the list row's zone column
    zones: bpy.props.CollectionProperty(type=FSS_MaterialZone)
    area: bpy.props.FloatProperty()  # m2
    estimate: bpy.props.FloatProperty()  # px, side of the square
    with_visibility: bpy.props.BoolProperty()  # the estimate used visibility data of at least one object
    never_used: bpy.props.BoolProperty()
    shared_zones: bpy.props.BoolProperty()
    transparent: bpy.props.BoolProperty()
    emissive: bpy.props.BoolProperty()

    @property
    def warning(self):
        return self.never_used or self.shared_zones


def _get_active(settings):
    """The active row is kept by material name, as the texture set list does: a new Refresh reorders the rows."""
    return settings.rows.find(settings.active_name)


def _set_active(settings, index):
    settings.active_name = settings.rows[index].name if 0 <= index < len(settings.rows) else ''


class FSS_MaterialsSettings(bpy.types.PropertyGroup):
    rows: bpy.props.CollectionProperty(type=FSS_MaterialRow)
    active_name: bpy.props.StringProperty()
    active: bpy.props.IntProperty(get=_get_active, set=_set_active)
    scanned: bpy.props.BoolProperty()
    show: bpy.props.EnumProperty(
        name='Show', items=(('ALL', 'All', 'List every material'),
                            ('WARNINGS', 'Warnings', 'List only materials never used or shared across zones')))


def active_row(settings):
    index = settings.active
    return settings.rows[index] if 0 <= index < len(settings.rows) else None


class FSS_OT_MaterialsRefresh(bpy.types.Operator):
    bl_idname = 'fss.materials_refresh'
    bl_label = 'Refresh'
    bl_description = ('List every material with the objects of the view layer that use it, their zones and surface, '
                      'without changing anything (Object Mode)')

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        start = time.perf_counter()
        stats = scan(context)
        settings = context.scene.fss_materials
        settings.rows.clear()
        for material in sorted(stats, key=lambda material: material.name.lower()):
            entry = stats[material]
            row = settings.rows.add()
            row.name = material.name
            row.objects = len(entry.objects)
            row.hidden = entry.hidden
            row.shared_meshes = entry.shared_meshes
            row.area = entry.area
            row.estimate = math.sqrt(entry.estimate_sq)
            row.with_visibility = entry.with_visibility
            row.never_used = not entry.objects
            row.shared_zones = len(entry.zones) > 1
            row.transparent = is_transparent(material)
            row.emissive = is_emissive(material)
            ordered = sorted(entry.zones.items(), key=_zone_order)
            row.zone_names = ', '.join(NO_ZONE_SHORT if key == '' else label for key, (label, _o, _a) in ordered)
            for key, (label, objects, area) in ordered:
                zone = row.zones.add()
                zone.name = label
                zone.zone = key
                zone.objects = objects
                zone.area = area
        settings.scanned = True
        if settings.active < 0 and settings.rows:
            settings.active = 0
        never = sum(row.never_used for row in settings.rows)
        shared = sum(row.shared_zones for row in settings.rows)
        self.report({'INFO'}, f'{len(settings.rows)} material(s): {never} never used, {shared} shared across zones '
                              f'({time.perf_counter() - start:.1f} s)')
        return {'FINISHED'}


class FSS_OT_MaterialsSelect(bpy.types.Operator):
    bl_idname = 'fss.materials_select'
    bl_label = 'Select Objects'
    bl_description = ('Select the visible objects that use this material (for example to give them a tag with Don\'t '
                      'Merge); the first becomes active')
    bl_options = {'REGISTER', 'UNDO'}

    material: bpy.props.StringProperty(name='Material')
    in_zone: bpy.props.BoolProperty(name='In Zone', description='Only the objects in the zone given by Zone')
    zone: bpy.props.StringProperty(name='Zone', description='The zone empty\'s name; empty for objects outside every '
                                                             'zone')

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        material = bpy.data.materials.get(self.material)
        if material is None:
            self.report({'ERROR'}, f"No material '{self.material}'")
            return {'CANCELLED'}
        view_layer = context.view_layer
        objects = using_objects(view_layer, material, visible_only=True)
        if self.in_zone:
            def zone_name(obj):
                zone = merge.nearest_zone(obj)
                return zone.name if zone is not None else ''
            objects = [obj for obj in objects if zone_name(obj) == self.zone]
        zone = bpy.data.objects.get(self.zone) if self.zone else None
        where = f' in {zone_label(zone)}' if self.in_zone else ''
        if not objects:
            self.report({'WARNING'}, f'{material.name}: no visible object uses it{where}')
            return {'CANCELLED'}
        for obj in view_layer.objects:
            if obj.select_get(view_layer=view_layer):
                obj.select_set(False, view_layer=view_layer)
        for obj in objects:
            obj.select_set(True, view_layer=view_layer)
        view_layer.objects.active = objects[0]
        self.report({'INFO'}, f'{material.name}: {len(objects)} object(s) selected{where}')
        return {'FINISHED'}


def area_text(m2):
    return f'{m2:.3f} m²' if m2 >= 1e-3 else f'{m2 * 1e4:.1f} cm²'


def _texture_text(row, short):
    material = bpy.data.materials.get(row.name)
    if material is None:
        return 'deleted since Refresh'
    result = uv_marks.last_result_text(material, short=short)
    size = str(uv_marks.texture_size(material))
    return f'{size}  {result}' if result else size


def _filter(row, show):
    return show == 'ALL' or row.warning


class FSS_UL_Materials(bpy.types.UIList):
    bl_idname = 'FSS_UL_materials'

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.label(text='', icon=ICON_WARNING if item.warning else 'BLANK1')
        row.label(text='', icon=ICON_TRANSPARENT if item.transparent else 'BLANK1')
        row.label(text='', icon=ICON_EMISSIVE if item.emissive else 'BLANK1')
        split = row.split(factor=0.45)
        split.label(text=item.name)
        split.label(text=f'{item.objects} obj  {item.zone_names}' if item.objects else 'never used')
        split.label(text=_texture_text(item, short=True))

    def filter_items(self, context, data, propname):
        rows = getattr(data, propname)
        show = data.show
        flags = [self.bitflag_filter_item if _filter(row, show) else 0 for row in rows]
        if self.filter_name:
            named = bpy.types.UI_UL_list.filter_items_by_name(self.filter_name, self.bitflag_filter_item, rows, 'name')
            flags = [flag & by_name for flag, by_name in zip(flags, named)]
        return flags, []


def _labelled(layout, text):
    split = layout.split(factor=0.3)
    split.label(text=text)
    return split.column(align=True)


def _select_button(layout, row, text, zone=None):
    op = layout.operator(FSS_OT_MaterialsSelect.bl_idname, text=text, icon='RESTRICT_SELECT_OFF')
    op.material = row.name
    op.in_zone = zone is not None
    op.zone = zone or ''


def estimate_text(row, material):
    """The Surface line's estimate, or that the set is kept (decision 13): Keep UVs is read from the material when
    drawing, not from the last Refresh, so ticking it shows at once."""
    if uv_pack.is_kept(material):
        return 'kept (Keep UVs): no estimate'
    source = 'with visibility' if row.with_visibility else 'no visibility data'
    return f'about {round(row.estimate)} px square (estimate, {source})'


def _draw_active(layout, row):
    material = bpy.data.materials.get(row.name)
    box = layout.box()
    box.label(text=row.name, icon='MATERIAL')
    kinds = [text for flag, text in ((row.transparent, 'transparent (alpha mode Blend)'),
                                     (row.emissive, 'emissive (emissive texture)')) if flag]
    if kinds:
        box.label(text=', '.join(kinds), icon=ICON_TRANSPARENT if row.transparent else ICON_EMISSIVE)
    if row.never_used:
        box.label(text='Never used: no face of a mesh in the view layer has it', icon=ICON_WARNING)
    else:
        _labelled(box, 'Objects').label(text=f'{row.objects} ({row.hidden} hidden, {row.shared_meshes} shared '
                                             'mesh(es))')
        column = _labelled(box, 'Zones')
        for zone in row.zones:
            column.label(text=f'{zone.name}: {zone.objects} obj, {area_text(zone.area)}',
                         icon=ICON_WARNING if row.shared_zones else 'OUTLINER_OB_EMPTY')
        if row.shared_zones:
            box.label(text=f'Shared across {len(row.zones)} zones', icon=ICON_WARNING)
        column = _labelled(box, 'Surface')
        column.label(text=area_text(row.area))
        column.label(text=estimate_text(row, material))
    _labelled(box, 'Texture').label(text=_texture_text(row, short=False))
    if material is not None:
        # decision 14: the panel's only control that changes data; Blender writes it on the artist's click
        _labelled(box, '').prop(material, uv_marks.KEEP_UVS_PROP, text='Keep UVs')
    if not row.never_used:
        column = box.column(align=True)
        _select_button(column, row, 'Select Objects')
        if len(row.zones) > 1:
            for zone in row.zones:
                _select_button(column, row, f'Select in {zone.name}', zone.zone)


class FSS_PT_Materials(bpy.types.Panel):
    bl_idname = 'FSS_PT_materials'
    bl_label = 'Materials'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'FSS MSFS Tools'
    bl_order = 1

    def draw(self, context):
        layout = self.layout
        settings = context.scene.fss_materials
        layout.operator(FSS_OT_MaterialsRefresh.bl_idname, icon='FILE_REFRESH')
        if not settings.scanned:
            layout.label(text='Press Refresh to list the materials', icon='INFO')
            return
        layout.label(text='Shows the scene at the last Refresh', icon='INFO')
        layout.row().prop(settings, 'show', expand=True)
        layout.template_list(FSS_UL_Materials.bl_idname, '', settings, 'rows', settings, 'active', rows=LIST_ROWS)
        legend = layout.row()
        legend.label(text='warning', icon=ICON_WARNING)
        legend.label(text='transparent', icon=ICON_TRANSPARENT)
        legend.label(text='emissive', icon=ICON_EMISSIVE)
        row = active_row(settings)
        if row is not None:
            _draw_active(layout, row)
        if uv_marks._progress is not None:
            # Check All in progress: its progress, as the Packing section shows it
            uv_marks._draw_progress(layout)
        else:
            layout.operator(uv_marks.FSS_OT_UvPackCheckAll.bl_idname, text='Check All', icon='VIEWZOOM')


def zone_table(settings):
    """[(label, total area m2, [(row, zone entry)])] per zone, (no zone) last, from the rows (reads only)."""
    table = {}
    for row in settings.rows:
        for zone in row.zones:
            table.setdefault(zone.zone, (zone.name, []))[1].append((row, zone))
    result = []
    for key in sorted(table, key=lambda key: (key == '', table[key][0].lower(), key)):
        label, entries = table[key]
        entries.sort(key=lambda entry: -entry[1].area)
        result.append((label, sum(zone.area for _row, zone in entries), entries))
    return result


class FSS_PT_MaterialsByZone(bpy.types.Panel):
    bl_idname = 'FSS_PT_materials_by_zone'
    bl_label = 'By Zone'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'FSS MSFS Tools'
    bl_parent_id = 'FSS_PT_materials'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.fss_materials
        table = zone_table(settings) if settings.scanned else []
        if not table:
            layout.label(text='Press Refresh to list the materials per zone', icon='INFO')
            return
        for label, total, entries in table:
            box = layout.box()
            box.label(text=f'{label}: {len(entries)} material(s), {area_text(total)}', icon='OUTLINER_OB_EMPTY')
            column = box.column(align=True)
            for row, zone in entries:
                share = zone.area / total if total > 0 else 0.0
                column.label(text=f'{row.name}: {zone.objects} obj, {area_text(zone.area)}, {share:.0%}',
                             icon=ICON_WARNING if row.shared_zones else 'MATERIAL')


CLASSES = (FSS_MaterialZone, FSS_MaterialRow, FSS_MaterialsSettings, FSS_OT_MaterialsRefresh, FSS_OT_MaterialsSelect,
           FSS_UL_Materials, FSS_PT_Materials, FSS_PT_MaterialsByZone)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.fss_materials = bpy.props.PointerProperty(type=FSS_MaterialsSettings)


def unregister():
    del bpy.types.Scene.fss_materials
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
