"""Object visibility marks, scene LOD settings and explicit viewport preview."""

import blf
import bpy

from . import lod_model, lod_rules

LOD_KEY = lod_model.HIDE_KEY
LOD_HIDDEN_KEY = lod_model.HIDDEN_KEY
_text_handle = None


def _editable(obj):
    return obj.library is None and obj.override_library is None


def parent_interval(obj):
    hide, show = 7, 0
    parent = obj.parent
    while parent is not None:
        hide = min(hide, lod_model.mark(parent, LOD_KEY) or 7)
        show = max(show, lod_model.mark(parent, lod_model.SHOW_KEY))
        parent = parent.parent
    return hide, show


def _tree_depth(obj):
    depth = 0
    while obj.parent is not None:
        depth += 1
        obj = obj.parent
    return depth


def apply_marks(objects, mode, level):
    changed, clamped = 0, set()
    for obj in sorted((o for o in objects if _editable(o)), key=_tree_depth):
        hide, show = parent_interval(obj)
        assigned = min(level, hide) if mode == 'HIDE' else max(level, show) if mode == 'SHOW' else level
        for key in (LOD_KEY, lod_model.SHOW_KEY, lod_model.KEEP_KEY):
            if key in obj:
                del obj[key]
        if mode == 'HIDE':
            obj[LOD_KEY] = assigned
        elif mode == 'SHOW':
            obj[lod_model.SHOW_KEY] = assigned
        elif mode == 'KEEP':
            obj[lod_model.KEEP_KEY] = 1
        changed += 1
        if assigned != level:
            clamped.add(obj)
        queue = list(obj.children)
        while queue:
            child = queue.pop(0)
            if _editable(child):
                hide, show = parent_interval(child)
                own_hide = lod_model.mark(child, LOD_KEY)
                own_show = lod_model.mark(child, lod_model.SHOW_KEY)
                if own_hide and own_hide > hide:
                    child[LOD_KEY] = hide
                    clamped.add(child)
                if own_show and own_show < show:
                    child[lod_model.SHOW_KEY] = show
                    clamped.add(child)
            queue.extend(child.children)
    return changed, len(clamped)


def apply_viewport_lod(context):
    scene = context.scene
    level = scene.fss_viewport_lod
    lod_model.restore_filter(context)
    if level < 0:
        scene.fss_lod_settings.preview_error = ''
        return
    try:
        plan = lod_model.build_plan(context, scene.fss_lod_settings.preview_target)
    except ValueError as error:
        scene.fss_lod_settings.preview_error = str(error)
        return
    scene.fss_lod_settings.preview_error = ''
    present = plan['decisions'][level].present if level < plan['write_count'] else set()
    if level >= plan['write_count']:
        scene.fss_lod_settings.preview_error = f'LOD{level:02}: not written (first empty LOD{plan["write_count"]:02})'
    for obj in context.view_layer.objects:
        if obj.name not in present and obj.visible_get(view_layer=context.view_layer):
            obj[LOD_HIDDEN_KEY] = True
            obj.hide_set(True, view_layer=context.view_layer)
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def _draw_viewport_lod_text():
    context = bpy.context
    if not context.space_data or not context.space_data.overlay.show_overlays:
        return
    level = context.scene.fss_viewport_lod
    if level < 0:
        return
    text = context.scene.fss_lod_settings.preview_error or f'Filtered by LOD{level}'
    blf.size(0, 13 * context.preferences.system.ui_scale)
    blf.position(0, 16, 16, 0)
    blf.color(0, 1.0, .78, .25, 1.0)
    blf.draw(0, text)


def _settings_changed(settings, context):
    settings.scanned = False
    if context and context.scene and context.scene.fss_viewport_lod >= 0:
        apply_viewport_lod(context)


def _fs24_table_changed(settings, context):
    settings.explicit_fs24 = True
    if not settings.explicit_fs20:
        settings['min_sizes_fs20'] = tuple(settings.min_sizes_fs24)
    _settings_changed(settings, context)


def _fs20_table_changed(settings, context):
    settings.explicit_fs20 = True
    _settings_changed(settings, context)


class FSS_LodHintItem(bpy.types.PropertyGroup):
    lod_level: bpy.props.IntProperty()
    kind: bpy.props.EnumProperty(items=[
        ('CONTRIBUTOR', 'Largest Contributor', ''),
        ('LOOSE_PIECES', 'Loose Pieces Below Cut-off', ''),
        ('NEAR_CUTOFF', 'Near Cut-off', ''),
    ])
    object_name: bpy.props.StringProperty()
    vertices: bpy.props.IntProperty()
    pieces: bpy.props.IntProperty()
    size_m: bpy.props.FloatProperty()
    cutoff_m: bpy.props.FloatProperty()
    is_merge_group: bpy.props.BoolProperty()


class FSS_LodSettings(bpy.types.PropertyGroup):
    model_type: bpy.props.EnumProperty(name='Model Type', default='EXTERIOR', update=_settings_changed,
        items=[('EXTERIOR', 'Exterior part', ''), ('INTERIOR', 'Interior', ''), ('SCENERY', 'Scenery', '')])
    min_sizes_fs24: bpy.props.FloatVectorProperty(name='FS24 minSize', size=7, min=0,
        default=lod_rules.DEFAULT_MIN_SIZES, update=_fs24_table_changed)
    min_sizes_fs20: bpy.props.FloatVectorProperty(name='FS20 minSize (unverified)', size=7, min=0,
        default=lod_rules.DEFAULT_MIN_SIZES, update=_fs20_table_changed)
    explicit_fs24: bpy.props.BoolProperty(default=False)
    explicit_fs20: bpy.props.BoolProperty(default=False)
    exterior_diameter: bpy.props.FloatProperty(name='Exterior Diameter (m)', min=0, update=_settings_changed)
    reference_size: bpy.props.FloatProperty(name='Reference Diameter (m)', min=0, update=_settings_changed,
        description='0 computes a sphere enclosing LOD00; otherwise use this diameter in metres')
    screen_height: bpy.props.IntProperty(name='Screen Height (px)', default=1440, min=1, update=_settings_changed)
    pixel_threshold: bpy.props.FloatProperty(name='Pixel Threshold', default=2, min=0, update=_settings_changed)
    keep_tags: bpy.props.StringProperty(name='Keep Tags', update=_settings_changed)
    preview_target: bpy.props.EnumProperty(name='Preview Target', default='fs24', update=_settings_changed,
        items=[('fs24', 'MSFS 2024', ''), ('fs20', 'MSFS 2020 (unverified)', '')])
    preview_error: bpy.props.StringProperty(options={'SKIP_SAVE'})
    scanned: bpy.props.BoolProperty(options={'SKIP_SAVE'})
    counts: bpy.props.IntVectorProperty(size=7, options={'SKIP_SAVE'})
    cutoffs: bpy.props.FloatVectorProperty(size=7, options={'SKIP_SAVE'})
    resolved_table: bpy.props.FloatVectorProperty(size=7, options={'SKIP_SAVE'})
    write_count: bpy.props.IntProperty(options={'SKIP_SAVE'})
    vertex_estimates: bpy.props.IntVectorProperty(size=7, options={'SKIP_SAVE'})
    quotas: bpy.props.IntVectorProperty(size=7, options={'SKIP_SAVE'})
    quota_percents: bpy.props.FloatVectorProperty(size=7, options={'SKIP_SAVE'})
    over_quota: bpy.props.BoolVectorProperty(size=7, options={'SKIP_SAVE'})
    dropped_pieces: bpy.props.IntVectorProperty(size=7, options={'SKIP_SAVE'})
    dropped_vertices: bpy.props.IntVectorProperty(size=7, options={'SKIP_SAVE'})
    hints: bpy.props.CollectionProperty(type=FSS_LodHintItem, options={'SKIP_SAVE'})
    inspect_lod: bpy.props.IntProperty(name='Inspect LOD', default=0, min=0, max=6, options={'SKIP_SAVE'})


class FSS_OT_LodRefresh(bpy.types.Operator):
    bl_idname = 'fss.lod_refresh'
    bl_label = 'Refresh LOD Counts'
    bl_description = 'Evaluate source bounds, loose pieces, vertex estimates, quotas and hints'

    def execute(self, context):
        settings = context.scene.fss_lod_settings
        try:
            stats = lod_model.estimate_scene_stats(context)
            plan = stats['plan']
            settings.counts = [len(d.present) for d in plan['decisions']]
            settings.cutoffs = [d.cutoff for d in plan['decisions']]
            settings.resolved_table = plan['table']
            settings.write_count = plan['write_count']
            settings.vertex_estimates = [s['vertices'] for s in stats['lods']]
            settings.quotas = [s['quota'] for s in stats['lods']]
            settings.quota_percents = [s['percent'] for s in stats['lods']]
            settings.over_quota = [s['over'] for s in stats['lods']]
            settings.dropped_pieces = [s['dropped_pieces'] for s in stats['lods']]
            settings.dropped_vertices = [s['dropped_vertices'] for s in stats['lods']]
            settings.hints.clear()
            for s in stats['lods'][:plan['write_count']]:
                level = s['level']
                for obj_name, verts, is_group in s['contributors']:
                    item = settings.hints.add()
                    item.lod_level = level
                    item.kind = 'CONTRIBUTOR'
                    item.object_name = obj_name
                    item.vertices = verts
                    item.is_merge_group = is_group
                for obj_name, n_pieces, verts, cutoff in s['loose_pieces']:
                    item = settings.hints.add()
                    item.lod_level = level
                    item.kind = 'LOOSE_PIECES'
                    item.object_name = obj_name
                    item.pieces = n_pieces
                    item.vertices = verts
                    item.cutoff_m = cutoff
                for obj_name, size_m, verts in s['near_cutoff']:
                    item = settings.hints.add()
                    item.lod_level = level
                    item.kind = 'NEAR_CUTOFF'
                    item.object_name = obj_name
                    item.size_m = size_m
                    item.vertices = verts
            if settings.inspect_lod >= settings.write_count:
                settings.inspect_lod = max(0, settings.write_count - 1)
            settings.scanned = True
            for warning in plan['decisions'][0].warnings:
                self.report({'WARNING'}, warning)
        except ValueError as error:
            settings.scanned = False
            settings.preview_error = str(error)
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        finally:
            apply_viewport_lod(context)
        return {'FINISHED'}


class FSS_OT_LodSelectHint(bpy.types.Operator):
    bl_idname = 'fss.lod_select_hint'
    bl_label = 'Select'
    bl_description = 'Select this object or merge group root in the 3D View (Shift: add to selection)'
    bl_options = {'REGISTER', 'UNDO'}

    object_name: bpy.props.StringProperty(name='Object')
    extend: bpy.props.BoolProperty(options={'SKIP_SAVE'})

    def invoke(self, context, event):
        self.extend = event.shift
        return self.execute(context)

    def execute(self, context):
        view_layer = context.view_layer
        obj = view_layer.objects.get(self.object_name)
        if obj is None:
            self.report({'WARNING'}, f'Object {self.object_name} not found in view layer')
            return {'CANCELLED'}
        if not obj.visible_get(view_layer=view_layer):
            self.report({'WARNING'}, f'{self.object_name} is currently hidden in the viewport')
            return {'CANCELLED'}
        if not self.extend:
            for other in context.selected_objects:
                other.select_set(False)
        obj.select_set(True)
        view_layer.objects.active = obj
        self.report({'INFO'}, f'Selected {self.object_name}')
        return {'FINISHED'}


class FSS_OT_SetObjectLod(bpy.types.Operator):
    bl_idname = 'fss.set_object_lod'
    bl_label = 'Set Object LOD'
    bl_description = 'Set visibility marks; parent visibility limits still apply'
    bl_options = {'REGISTER', 'UNDO'}
    level: bpy.props.IntProperty(min=0, max=6, default=0)
    mode: bpy.props.EnumProperty(default='HIDE', items=[('AUTO', 'Auto', ''), ('HIDE', 'Hidden from', ''),
                                                       ('SHOW', 'Visible from', ''), ('KEEP', 'Keep', '')])

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects)

    def execute(self, context):
        mode = 'AUTO' if self.level == 0 and self.mode == 'HIDE' else self.mode
        changed, clamped = apply_marks(context.selected_objects, mode, max(1, self.level))
        apply_viewport_lod(context)
        self.report({'INFO'}, f'Set {mode} on {changed} object(s); {clamped} clamped by parent')
        return {'FINISHED'}


class FSS_OT_SetViewportLod(bpy.types.Operator):
    bl_idname = 'fss.set_viewport_lod'
    bl_label = 'Viewport LOD Filter'
    bl_description = 'Preview export membership; Off restores only objects hidden by this filter'
    bl_options = {'REGISTER', 'UNDO'}
    level: bpy.props.IntProperty(min=-1, max=6, default=-1)

    def execute(self, context):
        context.scene.fss_viewport_lod = self.level
        apply_viewport_lod(context)
        error = context.scene.fss_lod_settings.preview_error
        if error:
            self.report({'WARNING'}, error)
        return {'FINISHED'}


class FSS_OT_LodPrintSettings(bpy.types.Operator):
    bl_idname = 'fss.lod_print_settings'
    bl_label = 'Print LOD Settings / XML'
    base_name: bpy.props.StringProperty(name='Model Base Name', default='MODEL')

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)

    def execute(self, context):
        import xml.sax.saxutils
        try:
            plan = lod_model.build_plan(context, context.scene.fss_lod_settings.preview_target)
            print('<LODS>')
            for level, value in enumerate(plan['table'][:plan['write_count']]):
                filename = xml.sax.saxutils.quoteattr(f'{self.base_name}_LOD{level:02}.gltf')
                print(f'    <LOD minSize="{value * 100:g}" ModelFile={filename}/>')
            print('</LODS>')
            for level, decision in enumerate(plan['decisions'][:plan['write_count']]):
                print(f'[FSS LOD] _LOD{level:02}: {len(decision.present)} objects, cut-off {decision.cutoff:g} m')
                for warning in decision.warnings:
                    print(f'[FSS LOD] WARNING {warning}')
            lod_model.report_end(plan)
        except ValueError as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        finally:
            apply_viewport_lod(context)
        return {'FINISHED'}


class FSS_OT_LodEditTable(bpy.types.Operator):
    bl_idname = 'fss.lod_edit_table'
    bl_label = 'Edit Explicit minSize Table'
    bl_options = {'REGISTER', 'UNDO'}
    target: bpy.props.EnumProperty(items=[('fs24', 'FS24', ''), ('fs20', 'FS20 (unverified)', '')])
    values: bpy.props.FloatVectorProperty(size=7, min=0, default=lod_rules.DEFAULT_MIN_SIZES)

    def invoke(self, context, event):
        settings = context.scene.fss_lod_settings
        self.values = getattr(settings, 'min_sizes_' + self.target)
        try:
            self.values = lod_model.build_plan(context, self.target)['table']
        except ValueError:
            # The user can explicitly author a table without a known exterior diameter.
            pass
        finally:
            apply_viewport_lod(context)
        return context.window_manager.invoke_props_dialog(self, width=350)

    def draw(self, context):
        self.layout.label(text='Explicit screen ratios: 1 = 100%')
        self.layout.label(text='No exterior diameter is needed for this table')
        for level in range(7):
            self.layout.prop(self, 'values', index=level, text=f'LOD{level:02}')

    def execute(self, context):
        try:
            lod_rules.min_sizes('INTERIOR', True, self.values, 0, 0, self.target)
        except ValueError as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        setattr(context.scene.fss_lod_settings, 'min_sizes_' + self.target, self.values)
        return {'FINISHED'}


class FSS_PT_Lod(bpy.types.Panel):
    bl_idname = 'FSS_PT_lod'
    bl_label = 'LOD'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'FSS Tools'

    def draw(self, context):
        layout = self.layout
        active = context.active_object
        row = layout.row(align=True)
        for mode, label in [('AUTO', 'Auto'), ('KEEP', 'Keep')]:
            marked = (active is not None and (bool(active.get(lod_model.KEEP_KEY)) if mode == 'KEEP' else
                      not any(active.get(key) for key in (LOD_KEY, lod_model.SHOW_KEY, lod_model.KEEP_KEY))))
            row.operator('fss.set_object_lod', text=label, depress=marked).mode = mode
        for mode, label, key in [('HIDE', 'Hidden from', LOD_KEY), ('SHOW', 'Visible from', lod_model.SHOW_KEY)]:
            layout.label(text=label)
            row = layout.row(align=True)
            for level in range(1, 7):
                op = row.operator('fss.set_object_lod', text=str(level),
                                  depress=active is not None and lod_model.mark(active, key) == level)
                op.mode, op.level = mode, level
        layout.label(text='Viewport LOD')
        row = layout.row(align=True)
        for level in range(-1, 7):
            row.operator('fss.set_viewport_lod', text='Off' if level < 0 else str(level),
                         depress=context.scene.fss_viewport_lod == level).level = level
        if context.scene.fss_lod_settings.preview_error:
            layout.label(text=context.scene.fss_lod_settings.preview_error, icon='ERROR')
        layout.operator('fss.lod_refresh', icon='FILE_REFRESH')
        settings = context.scene.fss_lod_settings
        if settings.scanned:
            layout.label(text='Cached source counts — Refresh after editing')
            for level in range(settings.write_count):
                text = f'LOD{level:02}: {settings.counts[level]} obj'
                if settings.dropped_pieces[level]:
                    text += f', -{settings.dropped_pieces[level]} pcs'
                text += f'; cut-off {settings.cutoffs[level]:.4g} m'
                layout.label(text=text)
            if settings.write_count < 7:
                layout.label(text=f'LOD{settings.write_count:02}: not written, no objects', icon='INFO')


class FSS_PT_LodQuotaHints(bpy.types.Panel):
    bl_idname = 'FSS_PT_lod_quota_hints'
    bl_label = 'Quota and Hints'
    bl_parent_id = 'FSS_PT_lod'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'FSS Tools'

    def draw(self, context):
        layout = self.layout
        settings = context.scene.fss_lod_settings
        if not settings.scanned:
            layout.label(text='Click Refresh LOD Counts to compute estimates', icon='INFO')
            return
        layout.label(text='Vertex estimates (per material/UV/normal corner, High quota):')
        col = layout.column(align=True)
        for level in range(settings.write_count):
            verts = settings.vertex_estimates[level]
            quota = settings.quotas[level]
            pct = settings.quota_percents[level]
            over = settings.over_quota[level]
            forced = settings.model_type == 'INTERIOR' and level == 0
            row = col.row(align=True)
            if settings.preview_target == 'fs20':
                row.label(text=f'_LOD{level:02}  ~{verts:,} vtx (FS20: no vertex curve)')
            elif forced:
                row.label(text=f'_LOD{level:02}  ~{verts:,} / {quota:,}  {pct:.0f}%  FORCED')
            elif over:
                row.alert = True
                row.label(text=f'_LOD{level:02}  ~{verts:,} / {quota:,}  {pct:.0f}%  OVER', icon='ERROR')
            else:
                row.label(text=f'_LOD{level:02}  ~{verts:,} / {quota:,}  {pct:.0f}%', icon='CHECKMARK')
            if settings.dropped_pieces[level]:
                sub = col.row(align=True)
                sub.enabled = False
                sub.label(text=f'    -{settings.dropped_pieces[level]:,} loose pieces '
                               f'(~{settings.dropped_vertices[level]:,} vtx) dropped at export')

        layout.separator()
        layout.label(text='Hints for LOD:')
        sel_row = layout.row(align=True)
        active_lod = (context.scene.fss_viewport_lod
                      if 0 <= context.scene.fss_viewport_lod < settings.write_count
                      else min(settings.inspect_lod, max(0, settings.write_count - 1)))
        for level in range(settings.write_count):
            op = sel_row.operator('fss.lod_inspect_level', text=str(level), depress=(level == active_lod))
            op.level = level

        lod_hints = [h for h in settings.hints if h.lod_level == active_lod]
        contributors = [h for h in lod_hints if h.kind == 'CONTRIBUTOR'][:5]
        loose = [h for h in lod_hints if h.kind == 'LOOSE_PIECES'][:5]
        near = [h for h in lod_hints if h.kind == 'NEAR_CUTOFF'][:5]

        box = layout.box()
        box.label(text=f'Largest contributors in _LOD{active_lod:02}:', icon='MESH_DATA')
        if contributors:
            for h in contributors:
                r = box.row(align=True)
                r.label(text=f'{h.object_name}: ~{h.vertices:,} vtx')
                r.operator('fss.lod_select_hint', text='', icon='RESTRICT_SELECT_OFF').object_name = h.object_name
        else:
            box.label(text='None')

        if active_lod > 0:
            box = layout.box()
            box.label(text=f'Loose pieces below {settings.cutoffs[active_lod]:.4g} m (dropped at export):',
                      icon='MOD_EXPLODE')
            if loose:
                for h in loose:
                    r = box.row(align=True)
                    r.label(text=f'{h.object_name}: {h.pieces:,} pcs, ~{h.vertices:,} vtx')
                    r.operator('fss.lod_select_hint', text='', icon='RESTRICT_SELECT_OFF').object_name = h.object_name
            else:
                box.label(text='None')

            box = layout.box()
            box.label(text=f'Near cut-off ({settings.cutoffs[active_lod]:.4g} m, candidates to hide):',
                      icon='FILTER')
            if near:
                for h in near:
                    r = box.row(align=True)
                    r.label(text=f'{h.object_name} ({h.size_m:.3g} m): ~{h.vertices:,} vtx')
                    r.operator('fss.lod_select_hint', text='', icon='RESTRICT_SELECT_OFF').object_name = h.object_name
            else:
                box.label(text='None')


class FSS_OT_LodInspectLevel(bpy.types.Operator):
    bl_idname = 'fss.lod_inspect_level'
    bl_label = 'Inspect LOD Hints'
    bl_description = 'Show Quota and Hints details for this LOD level'
    level: bpy.props.IntProperty(min=0, max=6, default=0)

    def execute(self, context):
        context.scene.fss_lod_settings.inspect_lod = self.level
        return {'FINISHED'}


class FSS_PT_LodExport(bpy.types.Panel):
    bl_idname = 'FSS_PT_lod_export'
    bl_label = 'Export Settings'
    bl_parent_id = 'FSS_PT_lod'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'FSS Tools'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.fss_lod_settings
        layout.prop(settings, 'model_type')
        layout.prop(settings, 'preview_target')
        if settings.model_type == 'INTERIOR':
            layout.prop(settings, 'exterior_diameter')
            target = settings.preview_target
            explicit = getattr(settings, 'explicit_' + target) or (target == 'fs20' and settings.explicit_fs24)
            if not explicit and settings.exterior_diameter <= 0:
                layout.label(text='exterior diameter missing', icon='ERROR')
        layout.prop(settings, 'reference_size')
        layout.prop(settings, 'screen_height')
        layout.prop(settings, 'pixel_threshold')
        layout.label(text='Vertex reports: High; counts do not affect culling')
        for target in ('fs24', 'fs20'):
            layout.label(text='FS20 minSize (unverified)' if target == 'fs20' else 'FS24 minSize')
            layout.label(text='Screen ratios: 1 = 100%')
            explicit = getattr(settings, 'explicit_' + target) or (target == 'fs20' and settings.explicit_fs24)
            if settings.model_type == 'INTERIOR' and not explicit:
                layout.label(text='Derived from interior / exterior diameter')
                layout.operator('fss.lod_edit_table').target = target
                if settings.scanned and target == settings.preview_target:
                    for level, value in enumerate(settings.resolved_table):
                        layout.label(text=f'LOD{level:02}: {value:.2%}')
            else:
                for level in range(7):
                    layout.prop(settings, 'min_sizes_' + target, index=level, text=f'LOD{level:02}')
        layout.operator('fss.lod_print_settings', icon='CONSOLE')


CLASSES = (FSS_LodHintItem, FSS_LodSettings, FSS_OT_LodRefresh, FSS_OT_LodSelectHint, FSS_OT_LodInspectLevel,
           FSS_OT_SetObjectLod, FSS_OT_SetViewportLod, FSS_OT_LodPrintSettings,
           FSS_OT_LodEditTable, FSS_PT_Lod, FSS_PT_LodQuotaHints, FSS_PT_LodExport)


def register():
    global _text_handle
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.fss_lod_settings = bpy.props.PointerProperty(type=FSS_LodSettings)
    bpy.types.Scene.fss_viewport_lod = bpy.props.IntProperty(default=-1, min=-1, max=6)
    bpy.types.Scene.fss_lod_export_level = bpy.props.IntProperty(default=-1, min=-1, max=6, options={'SKIP_SAVE'})
    if not bpy.app.background:
        _text_handle = bpy.types.SpaceView3D.draw_handler_add(_draw_viewport_lod_text, (), 'WINDOW', 'POST_PIXEL')


def unregister():
    global _text_handle
    if _text_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_text_handle, 'WINDOW')
        _text_handle = None
    for name in ('fss_lod_settings', 'fss_viewport_lod', 'fss_lod_export_level'):
        delattr(bpy.types.Scene, name)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
