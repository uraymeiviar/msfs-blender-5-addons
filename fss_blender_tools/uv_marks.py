"""UV marks: per-object texel density range and island direction, per-material margin.

Authoring data for the planned auto-seam, unwrap and packing phases (journal 20261019.automated-uv-unwrap.md,
decisions 11 and 12); nothing reads it yet. Marks are custom properties, which the exporter does not write to glTF.
An object without its own mark inherits the nearest marked ancestor's.
"""

import bpy

from .tags import _editable

DENSITY_KEY = 'fss_uv_density'  # [min, max] x the base texel density
DIRECTION_KEY = 'fss_uv_direction'
SKIP_AUTOSEAM_KEY = 'fss_uv_skip_autoseam'
MARGIN_KEY = 'fss_uv_margin'  # on a material: island margin as a fraction of the UV square
DEFAULT_DENSITY = (0.9, 1.1)
DEFAULT_MARGIN = 0.002
DENSITY_PRESETS = {'LOWER': (0.7, 0.8), 'HIGHER': (1.5, 1.65)}
DIRECTIONS = [
    ('FREE', 'Free', 'Islands may rotate to any angle'),
    ('UPRIGHT', 'Upright', 'Islands keep their orientation (brushed metal, grain, text)'),
    ('FLIP', 'Flip', 'Islands may only turn by 180 degrees'),
    ('QUARTER', 'Quarter', 'Islands may only turn in 90-degree steps'),
]
DIRECTION_IDS = {item[0] for item in DIRECTIONS}
BLOCK_PIXELS = 4  # texture compression works in 4x4 blocks; a margin below this bleeds at that resolution


def _own_density(obj):
    value = obj.get(DENSITY_KEY)
    try:
        low, high = float(value[0]), float(value[1])
    except (TypeError, ValueError, IndexError, KeyError):
        return None
    return (low, high) if 0 < low <= high else None


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


def density(obj):
    return _effective(obj, _own_density, DEFAULT_DENSITY)


def direction(obj):
    return _effective(obj, _own_direction, 'FREE')


def _own_skip_autoseam(obj):
    if SKIP_AUTOSEAM_KEY not in obj:
        return None
    return bool(obj[SKIP_AUTOSEAM_KEY])


def skip_autoseam(obj):
    return _effective(obj, _own_skip_autoseam, False)


def margin(material):
    value = material.get(MARGIN_KEY)
    return float(value) if isinstance(value, (int, float)) and value >= 0 else DEFAULT_MARGIN


def _set_margin(material, value):
    material[MARGIN_KEY] = float(value)


def _source_text(obj, source):
    if source is None:
        return 'default'
    return 'own mark' if source == obj else f'from {source.name}'


def _selected(context):
    return [obj for obj in context.selected_objects if _editable(obj)]


class FSS_OT_UvSetDensity(bpy.types.Operator):
    bl_idname = 'fss.uv_set_density'
    bl_label = 'Set Texel Density Range'
    bl_description = ('Mark the selected objects with a texel density range (x base density); their children '
                      'inherit it unless marked themselves')
    bl_options = {'REGISTER', 'UNDO'}

    preset: bpy.props.EnumProperty(items=[
        ('CUSTOM', 'Custom', 'Use the Min and Max fields'),
        ('LOWER', 'Lower', 'Less visible parts (0.7 to 0.8)'),
        ('HIGHER', 'Higher', 'Prominent parts such as the glareshield (1.5 to 1.65)'),
        ('CLEAR', 'Clear', 'Remove the mark: inherit from the parent, else the default 0.9 to 1.1'),
    ])

    @classmethod
    def poll(cls, context):
        return bool(_selected(context))

    def execute(self, context):
        scene = context.scene
        if self.preset == 'CUSTOM':
            low, high = scene.fss_uv_density_min, scene.fss_uv_density_max
            if low > high:
                self.report({'ERROR'}, 'Min is larger than Max')
                return {'CANCELLED'}
            value = (round(low, 4), round(high, 4))
        else:
            value = DENSITY_PRESETS.get(self.preset)
        objects = _selected(context)
        for obj in objects:
            if value is None:
                obj.pop(DENSITY_KEY, None)
            else:
                obj[DENSITY_KEY] = list(value)
        text = 'Cleared density mark' if value is None else f'Density {value[0]:g} to {value[1]:g}'
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


class FSS_OT_UvSelectMarked(bpy.types.Operator):
    bl_idname = 'fss.uv_select_marked'
    bl_label = 'Select Marked'
    bl_description = 'Select the objects that carry their own UV density or direction mark'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        view_layer = context.view_layer
        marked = [obj for obj in view_layer.objects if DENSITY_KEY in obj or DIRECTION_KEY in obj or SKIP_AUTOSEAM_KEY in obj]
        for obj in context.selected_objects:
            obj.select_set(False)
        for obj in marked:
            if obj.visible_get(view_layer=view_layer):
                obj.select_set(True)
        self.report({'INFO'}, f'{len(marked)} marked object(s)')
        return {'FINISHED'}


class FSS_OT_UvClearMargin(bpy.types.Operator):
    bl_idname = 'fss.uv_clear_margin'
    bl_label = 'Default Margin'
    bl_description = 'Remove the margin setting of this material (use the default)'
    bl_options = {'REGISTER', 'UNDO'}

    material: bpy.props.StringProperty()

    def execute(self, context):
        material = bpy.data.materials.get(self.material)
        if material is not None:
            material.pop(MARGIN_KEY, None)
        return {'FINISHED'}


class FSS_PT_UvMarks(bpy.types.Panel):
    bl_idname = 'FSS_PT_uv_marks'
    bl_label = 'UV Marks'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'FSS Tools'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        obj = context.active_object
        box = layout.box()
        if obj is None:
            box.label(text='No active object', icon='INFO')
        else:
            box.label(text=obj.name, icon='OBJECT_DATA')
            (low, high), source = density(obj)
            box.label(text=f'Density {low:g} to {high:g} ({_source_text(obj, source)})')
            value, source = direction(obj)
            box.label(text=f'Direction {value.lower()} ({_source_text(obj, source)})')
            is_skip, source = skip_autoseam(obj)
            if is_skip:
                box.label(text=f'Skip Auto Seam ({_source_text(obj, source)})')
            else:
                box.label(text=f'Auto Seam: process ({_source_text(obj, source)})')

        selected = _selected(context)
        box = layout.box()
        box.label(text=f'Set on {len(selected)} selected object(s):')
        box.label(text='Texel density range (x base):')
        row = box.row(align=True)
        row.prop(scene, 'fss_uv_density_min', text='Min')
        row.prop(scene, 'fss_uv_density_max', text='Max')
        row.operator(FSS_OT_UvSetDensity.bl_idname, text='Apply').preset = 'CUSTOM'
        row = box.row(align=True)
        for preset, text in (('LOWER', 'Lower'), ('HIGHER', 'Higher'), ('CLEAR', 'Clear')):
            row.operator(FSS_OT_UvSetDensity.bl_idname, text=text).preset = preset
        box.label(text='Island direction:')
        row = box.row(align=True)
        for item in DIRECTIONS + [('CLEAR', 'Clear', '')]:
            row.operator(FSS_OT_UvSetDirection.bl_idname, text=item[1]).direction = item[0]
        box.label(text='Auto Seam:')
        row = box.row(align=True)
        row.operator(FSS_OT_UvSetSkipAutoseam.bl_idname, text='Skip Auto Seam').action = 'SKIP'
        row.operator(FSS_OT_UvSetSkipAutoseam.bl_idname, text='Clear').action = 'CLEAR'
        layout.operator(FSS_OT_UvSelectMarked.bl_idname, icon='RESTRICT_SELECT_OFF')

        materials = sorted({slot.material for obj in selected for slot in obj.material_slots if slot.material},
                           key=lambda material: material.name)
        box = layout.box()
        box.label(text='Texture sets (materials of the selection):')
        if not materials:
            box.label(text='None')
        for material in materials[:20]:
            row = box.row(align=True)
            row.label(text=material.name, icon='MATERIAL')
            row.prop(material, 'fss_uv_margin', text='Margin')
            if MARGIN_KEY in material:
                row.operator(FSS_OT_UvClearMargin.bl_idname, text='', icon='LOOP_BACK').material = material.name
            value = margin(material)
            hint = f'about {value * 4096:.0f} px at 4K, {value * 8192:.0f} px at 8K'
            if MARGIN_KEY not in material:
                hint += ' (default)'
            warn = value * 2048 < BLOCK_PIXELS
            box.label(text=hint + (', under 4 px at 2K' if warn else ''), icon='ERROR' if warn else 'BLANK1')
        if len(materials) > 20:
            box.label(text=f'... and {len(materials) - 20} more')


CLASSES = (FSS_OT_UvSetDensity, FSS_OT_UvSetDirection, FSS_OT_UvSetSkipAutoseam, FSS_OT_UvSelectMarked, FSS_OT_UvClearMargin, FSS_PT_UvMarks)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.fss_uv_density_min = bpy.props.FloatProperty(
        name='Min', default=DEFAULT_DENSITY[0], min=0.01, soft_max=4, precision=2, options={'SKIP_SAVE'})
    bpy.types.Scene.fss_uv_density_max = bpy.props.FloatProperty(
        name='Max', default=DEFAULT_DENSITY[1], min=0.01, soft_max=4, precision=2, options={'SKIP_SAVE'})
    bpy.types.Material.fss_uv_margin = bpy.props.FloatProperty(
        name='UV Margin', min=0, soft_max=0.02, precision=4, step=0.01, get=margin, set=_set_margin,
        description='Space around each island as a fraction of the UV square; the same share at every texture '
                    'resolution')


def unregister():
    del bpy.types.Material.fss_uv_margin
    del bpy.types.Scene.fss_uv_density_max
    del bpy.types.Scene.fss_uv_density_min
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
