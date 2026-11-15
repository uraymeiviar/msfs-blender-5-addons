"""The Polygone panel (3D View > Sidebar > Polygone), its settings and the Reduce operator."""

import os
import time
from concurrent.futures import ThreadPoolExecutor

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty

from . import mesh_io, native

LAST_RUN = []  # one dict per reduced mesh of the last run, for the panel (not saved)


def _prefs(context):
    addon = context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


def library(context):
    prefs = _prefs(context)
    return native.load(prefs.dll_path if prefs else '')


_SWITCH_ITEMS = [(str(bit), name, f'Bit {bit}, default {"on" if on else "off"}') for bit, name, on in native.SWITCHES]
_SWITCH_DEFAULT = {str(bit) for bit, _name, on in native.SWITCHES if on}


class PolygoneSettings(bpy.types.PropertyGroup):
    target_mode: EnumProperty(
        name='Target', default='RATIO',
        items=[('RATIO', 'Ratio', 'Keep this fraction of the triangles'),
               ('COUNT', 'Triangles', 'Keep this many triangles per mesh'),
               ('ERROR', 'Error Only', 'No triangle target: reduce until Max Error stops it')])
    ratio: FloatProperty(name='Ratio', default=0.5, min=0.001, max=1.0, precision=3,
                         description='Fraction of the input triangles to keep')
    triangles: IntProperty(name='Triangles', default=1000, min=1, description='Triangles to keep per mesh')
    max_error: FloatProperty(name='Max Error', default=0.0, min=0.0, precision=5, unit='LENGTH',
                             description='No collapse takes the surface further than this from the input, in scene '
                                         'units (0 = no limit). Measured on samples, not certified')

    output: EnumProperty(
        name='Output', default='NEW',
        items=[('NEW', 'New Object', 'A reduced copy next to each object (<name>_polygone); the original stays'),
               ('REPLACE', 'Replace Mesh', "Replace the object's mesh (before modifiers; the modifiers stay)")])
    apply_modifiers: BoolProperty(name='Apply Modifiers', default=True,
                                  description='New Object: reduce the mesh with its modifiers applied, and leave the '
                                              'copy without modifiers. Off: reduce the base mesh, keep the modifiers')
    hide_originals: BoolProperty(name='Hide Originals', default=True,
                                 description='New Object: hide each original, so the copy shows in its place')

    normal_weight: FloatProperty(name='Normals', default=0.5, min=0.0, max=100.0,
                                 description='How strongly the shading normals are kept (0 = carried only)')
    uv_weight: FloatProperty(name='UVs', default=1.0, min=0.0, max=100.0,
                             description='How strongly the UVs are kept (0 = carried only)')
    color_weight: FloatProperty(name='Colors', default=1.0, min=0.0, max=100.0,
                                description='How strongly the colour attributes are kept (0 = carried only)')

    use_sharp: BoolProperty(name='Sharp Edges', default=True, description='Sharp edges are feature lines')
    sharp_weight: FloatProperty(name='Weight', default=1.0, min=0.001, max=1000.0)
    use_seams: BoolProperty(name='Marked Seams', default=False,
                            description='Edges marked as seam are feature lines (UV splits are seams anyway)')
    seam_weight: FloatProperty(name='Weight', default=1.0, min=0.001, max=1000.0)
    use_creases: BoolProperty(name='Creases', default=False, description='Creased edges are feature lines, weighted '
                                                                          'by their crease')
    crease_weight: FloatProperty(name='Weight', default=1.0, min=0.001, max=1000.0)
    feature_angle: FloatProperty(name='Feature Angle', default=0.0, min=0.0, max=179.0,
                                 description='Edges whose two faces meet at more than this angle are feature lines '
                                             '(0 = off)')
    angle_weight: FloatProperty(name='Weight', default=1.0, min=0.001, max=1000.0)

    lock_group: StringProperty(name='Lock Group',
                               description='Vertices of this vertex group (weight 0.5 or more) are never removed or moved')
    importance_group: StringProperty(name='Importance Group',
                                     description="Vertices of this group cost more (or less) to move, by their weight")
    importance_strength: FloatProperty(name='Strength', default=10.0, min=0.0, max=1000.0,
                                       description='Importance of a vertex of weight 1 in the group (1 = neutral, '
                                                   'below 1 = removed first)')

    placement: EnumProperty(
        name='Placement', default='OPTIMAL',
        items=[('OPTIMAL', 'Optimal', 'Merged points go where the error is lowest, with computed UVs and normals'),
               ('SUBSET', 'Subset', 'Every output vertex is an input vertex, values unchanged')])
    max_normal: FloatProperty(name='Max Normal Turn', default=90.0, min=1.0, max=180.0,
                              description='No triangle turns this far from the input triangle it came from (degrees)')
    normal_merge_angle: FloatProperty(name='Normal Merge Angle', default=1.0, min=0.0, max=10.0,
                                      description='Corners at one position with the same UVs whose normals differ by '
                                                  'less than this (degrees) are one vertex: Blender stores custom '
                                                  'normals with a small error (0 = equal only)')
    lock_open_borders: BoolProperty(name='Lock Open Borders', default=False)
    lock_group_borders: BoolProperty(name='Lock Material Borders', default=False,
                                     description='Borders between materials, and between flat and smooth faces, are '
                                                 'kept exactly')
    switches: EnumProperty(name='Switches', items=_SWITCH_ITEMS, options={'ENUM_FLAG'}, default=_SWITCH_DEFAULT,
                           description='The library\'s experimental switches (unstable, for testing)')
    threads: IntProperty(name='Parallel Meshes', default=4, min=1, max=12,
                         description='Meshes reduced at the same time (each mesh on one thread)')


def _experimental(s):
    on = set(s.switches)
    return sum(bit for bit, _name, default in native.SWITCHES if (str(bit) in on) != default)


def _settings(s, triangles, scale):
    if s.target_mode == 'RATIO':
        target = max(1, int(round(triangles * s.ratio)))
    elif s.target_mode == 'COUNT':
        target = min(triangles, s.triangles)
    else:
        target = 0
    flags = (native.LOCK_OPEN_BORDERS if s.lock_open_borders else 0) | \
            (native.LOCK_GROUP_BORDERS if s.lock_group_borders else 0)
    return dict(target=target, max_error=s.max_error / scale if s.max_error > 0 else 0.0, flags=flags,
                placement=native.PLACEMENT_SUBSET if s.placement == 'SUBSET' else native.PLACEMENT_OPTIMAL,
                max_normal=s.max_normal, experimental=_experimental(s))


def _scale(obj):
    return max(abs(v) for v in obj.matrix_world.to_scale()) or 1.0


def _selected_meshes(context):
    return [o for o in context.selected_objects if o.type == 'MESH']


class POLYGONE_OT_reduce(bpy.types.Operator):
    bl_idname = 'polygone.reduce_selected'
    bl_label = 'Reduce Selected'
    bl_description = 'Reduce the meshes of the selected objects with libPolygone'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(_selected_meshes(context))

    def execute(self, context):
        s = context.scene.fss_polygone
        dll = library(context)
        if dll is None:
            self.report({'ERROR'}, f'libPolygone not loaded: {native.error()}')
            return {'CANCELLED'}
        if s.target_mode == 'ERROR' and s.max_error <= 0:
            self.report({'ERROR'}, 'Error Only needs a Max Error above 0')
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        objects = _selected_meshes(context)
        depsgraph = context.evaluated_depsgraph_get()
        # Jobs: one per mesh to reduce. New Object: one per object; Replace: one per mesh data, for all its selected users.
        jobs = []
        if s.output == 'REPLACE':
            by_data = {}
            for obj in objects:
                by_data.setdefault(obj.data.name, []).append(obj)
            for users in by_data.values():
                jobs.append(dict(objects=users, source=users[0].data, evaluated=None))
        else:
            for obj in objects:
                if s.apply_modifiers:
                    evaluated = obj.evaluated_get(depsgraph)
                    jobs.append(dict(objects=[obj], source=evaluated.to_mesh(), evaluated=evaluated))
                else:
                    jobs.append(dict(objects=[obj], source=obj.data, evaluated=None))

        wm = context.window_manager
        wm.progress_begin(0, 3)
        LAST_RUN.clear()
        failed = []
        try:
            for job in jobs:
                obj = job['objects'][0]
                names = [g.name for g in obj.vertex_groups]
                job['group_names'] = names
                if len(job['source'].polygons) == 0:
                    job['skip'] = 'no faces'
                    continue
                job['mesh'], job['info'] = mesh_io.read(job['source'], names, s)
                job['scale'] = _scale(obj)
                job['settings'] = _settings(s, job['info']['triangles'], job['scale'])
            wm.progress_update(1)

            def run(job):
                start = time.perf_counter()
                try:
                    job['result'] = native.reduce(dll, job['mesh'], job['settings'])
                except RuntimeError as exc:
                    job['skip'] = str(exc)
                job['seconds'] = time.perf_counter() - start

            work = [j for j in jobs if 'skip' not in j]
            with ThreadPoolExecutor(max_workers=max(1, min(s.threads, len(work) or 1))) as pool:
                list(pool.map(run, work))
            wm.progress_update(2)

            created = []
            for job in jobs:
                obj = job['objects'][0]
                if 'skip' in job:
                    failed.append(f'{obj.name}: {job["skip"]}')
                    continue
                me, dropped, vertex_source = mesh_io.build(f'{job["source"].name}_polygone', job['result'],
                                                           job['info'], job['source'] if job['evaluated'] is None
                                                           else obj.data)
                if s.output == 'REPLACE':
                    for user in job['objects']:
                        user.data = me
                    targets = job['objects']
                else:
                    copy = obj.copy()
                    copy.data = me
                    copy.name = f'{obj.name}_polygone'
                    if job['evaluated'] is not None:
                        copy.modifiers.clear()
                    for collection in obj.users_collection:
                        collection.objects.link(copy)
                    created.append(copy)
                    targets = [copy]
                for target in targets:
                    mesh_io.copy_vertex_groups(target, job['info'], vertex_source, job['group_names'])
                r, info = job['result'], job['info']
                LAST_RUN.append(dict(
                    name=targets[0].name, tris_in=info['triangles'], tris_out=len(me.polygons),
                    verts_in=info['vertices'], verts_out=len(me.vertices), split_in=info['split_vertices'],
                    split_out=len(r['positions']), error=r['error'] * job['scale'],
                    relative=r['error'] / info['diagonal'] if info['diagonal'] > 0 else 0.0, stop=r['stop'],
                    seconds=job['seconds'], dropped=dropped, features=info['feature_edges']))
            if created:
                for obj in objects:
                    obj.select_set(False)
                    if s.hide_originals:
                        obj.hide_set(True)
                for copy in created:
                    copy.select_set(True)
                context.view_layer.objects.active = created[-1]
            wm.progress_update(3)
        finally:
            for job in jobs:
                if job['evaluated'] is not None:
                    job['evaluated'].to_mesh_clear()
            wm.progress_end()

        tris_in = sum(r['tris_in'] for r in LAST_RUN)
        tris_out = sum(r['tris_out'] for r in LAST_RUN)
        seconds = sum(r['seconds'] for r in LAST_RUN)
        message = f'Polygone: {len(LAST_RUN)} mesh(es), {tris_in} -> {tris_out} triangles, {seconds:.2f} s'
        if failed:
            self.report({'WARNING'}, message + '; failed: ' + '; '.join(failed))
        else:
            self.report({'INFO'}, message)
        return {'FINISHED'} if LAST_RUN else {'CANCELLED'}


class POLYGONE_OT_reload(bpy.types.Operator):
    bl_idname = 'polygone.reload_library'
    bl_label = 'Reload Library'
    bl_description = 'Load the libPolygone DLL again (picks up a new build of the DLL named in the preferences)'

    def execute(self, context):
        native.reset()
        if library(context) is None:
            self.report({'ERROR'}, f'libPolygone not loaded: {native.error()}')
            return {'CANCELLED'}
        self.report({'INFO'}, f'libPolygone loaded from {native.source()}')
        return {'FINISHED'}


class PolygonePreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    dll_path: StringProperty(name='DLL', subtype='FILE_PATH',
                             description='Another polygone.dll to use, for example a fresh build of libPolygone '
                                         '(empty = the DLL bundled with the add-on)')

    def draw(self, context):
        self.layout.prop(self, 'dll_path')
        self.layout.operator(POLYGONE_OT_reload.bl_idname)


class _Panel:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Polygone'


class POLYGONE_PT_main(_Panel, bpy.types.Panel):
    bl_label = 'Polygone'

    def draw(self, context):
        s = context.scene.fss_polygone
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(s, 'target_mode')
        if s.target_mode == 'RATIO':
            layout.prop(s, 'ratio', slider=True)
        elif s.target_mode == 'COUNT':
            layout.prop(s, 'triangles')
        layout.prop(s, 'max_error')
        layout.separator()
        layout.prop(s, 'output')
        col = layout.column()
        col.enabled = s.output == 'NEW'
        col.prop(s, 'apply_modifiers')
        col.prop(s, 'hide_originals')
        layout.separator()
        count = len(_selected_meshes(context))
        row = layout.row()
        row.scale_y = 1.4
        row.operator(POLYGONE_OT_reduce.bl_idname, text=f'Reduce Selected ({count})', icon='MOD_DECIM')


class POLYGONE_PT_attributes(_Panel, bpy.types.Panel):
    bl_label = 'Attribute Weights'
    bl_parent_id = 'POLYGONE_PT_main'

    def draw(self, context):
        s = context.scene.fss_polygone
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(s, 'normal_weight')
        layout.prop(s, 'uv_weight')
        layout.prop(s, 'color_weight')


class POLYGONE_PT_guidance(_Panel, bpy.types.Panel):
    bl_label = 'Feature Lines and Locks'
    bl_parent_id = 'POLYGONE_PT_main'

    def draw(self, context):
        s = context.scene.fss_polygone
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        for flag, weight in (('use_sharp', 'sharp_weight'), ('use_seams', 'seam_weight'),
                             ('use_creases', 'crease_weight')):
            row = layout.row(heading='')
            row.prop(s, flag)
            sub = row.row()
            sub.enabled = getattr(s, flag)
            sub.prop(s, weight, text='')
        row = layout.row()
        row.prop(s, 'feature_angle')
        sub = row.row()
        sub.enabled = s.feature_angle > 0
        sub.prop(s, 'angle_weight', text='')
        layout.separator()
        obj = context.active_object
        if obj is not None and obj.type == 'MESH':
            layout.prop_search(s, 'lock_group', obj, 'vertex_groups')
            layout.prop_search(s, 'importance_group', obj, 'vertex_groups')
        else:
            layout.prop(s, 'lock_group')
            layout.prop(s, 'importance_group')
        col = layout.column()
        col.enabled = bool(s.importance_group)
        col.prop(s, 'importance_strength')


class POLYGONE_PT_advanced(_Panel, bpy.types.Panel):
    bl_label = 'Advanced'
    bl_parent_id = 'POLYGONE_PT_main'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        s = context.scene.fss_polygone
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(s, 'placement')
        layout.prop(s, 'max_normal')
        layout.prop(s, 'normal_merge_angle')
        layout.prop(s, 'lock_open_borders')
        layout.prop(s, 'lock_group_borders')
        layout.prop(s, 'threads')
        layout.label(text=f'Switches (experimental bits {_experimental(s)})')
        col = layout.column(align=True)
        col.use_property_split = False
        col.prop(s, 'switches')


class POLYGONE_PT_results(_Panel, bpy.types.Panel):
    bl_label = 'Last Run'
    bl_parent_id = 'POLYGONE_PT_main'

    def draw(self, context):
        layout = self.layout
        if not LAST_RUN:
            layout.label(text='Nothing reduced yet in this session')
            return
        for r in LAST_RUN:
            box = layout.box()
            box.label(text=r['name'], icon='MESH_DATA')
            col = box.column(align=True)
            col.label(text=f'Triangles {r["tris_in"]} -> {r["tris_out"]}   Vertices {r["verts_in"]} -> {r["verts_out"]}')
            col.label(text=f'Error {r["error"]:.5g} ({100 * r["relative"]:.3f} % of size)')
            col.label(text=f'{r["stop"]}, {r["seconds"]:.2f} s, {r["features"]} feature edges')
            if r['dropped']:
                col.label(text=f'{r["dropped"]} triangles dropped (corners welded)', icon='ERROR')


class POLYGONE_PT_library(_Panel, bpy.types.Panel):
    bl_label = 'Library'
    bl_parent_id = 'POLYGONE_PT_main'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        dll = library(context)
        if dll is None:
            layout.label(text='Not loaded', icon='ERROR')
            layout.label(text=str(native.error()))
        else:
            layout.label(text=f'Interface version {native.INTERFACE_VERSION}', icon='CHECKMARK')
            layout.label(text=os.path.basename(native.source()) + ' from ' + os.path.dirname(native.source()))
        layout.operator(POLYGONE_OT_reload.bl_idname, icon='FILE_REFRESH')


classes = (PolygoneSettings, POLYGONE_OT_reduce, POLYGONE_OT_reload, PolygonePreferences, POLYGONE_PT_main,
           POLYGONE_PT_attributes, POLYGONE_PT_guidance, POLYGONE_PT_advanced, POLYGONE_PT_results,
           POLYGONE_PT_library)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.fss_polygone = PointerProperty(type=PolygoneSettings)


def unregister():
    del bpy.types.Scene.fss_polygone
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
