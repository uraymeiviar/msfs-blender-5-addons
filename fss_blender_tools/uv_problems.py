"""Problems of a texture set, one row each, under the texture set table of UV Auto Packing (UV journal decision 151).

Rows that point at objects or faces: a shared mesh left out of the set (its first user by name shows another
material, uv_pack.shared_differences), a user without a material where other users of its mesh show the set, faces
with triangles without UV area (decision 118) and faces without area (decision 117), one row per mesh or object. They
are collected after each Pack and Check All of the set and by Recheck, from the scene as it is then, and kept per set
for the session. A click on a row checks that problem again: when it is gone the row is ticked as fixed, else its
objects are selected (faces: Edit Mode with only those faces selected) and the 3D viewports zoom to them. Rows that
only inform (the layout does not fit, the margin under 4 px) are read live from the last result and the material.
"""

import blf
import bpy

from . import checks, uv_marks, uv_pack

PROBLEM_ROWS = 12  # rows shown; the rest are counted
LEFT_OUT, NO_MATERIAL, NO_UV_AREA, NO_AREA = 'LEFT_OUT', 'NO_MATERIAL', 'NO_UV_AREA', 'NO_AREA'
ICONS = {LEFT_OUT: 'UNLINKED', NO_MATERIAL: 'MATERIAL', NO_UV_AREA: 'UV', NO_AREA: 'MESH_DATA'}
TEXT_PADDING = 40  # px of the problem box's frame and the row icon, for fitting a row's text

_problems = {}  # texture set name -> [row]; row: kind, text, tip, mesh, objects, fixed


def rows(material):
    """The problem rows of a texture set, None before they were collected."""
    return _problems.get(material.name) if material is not None else None


def _by_mesh(found):
    """{mesh name: (object names, face indices)} from {object: face indices}; the users of a mesh share its faces."""
    out = {}
    for obj, faces in found.items():
        names, _faces = out.setdefault(obj.data.name, ([], faces))
        names.append(obj.name)
    return {mesh: (sorted(names), faces) for mesh, (names, faces) in out.items()}


def faces_without_uv_area(view_layer, material):
    """{mesh name: (users, faces)} of the set's faces with a triangle without UV area inside an island with UV area."""
    found, _faces, _islands = checks.faces_without_uv_area(view_layer, material)
    return _by_mesh(found)


def faces_without_area(view_layer, material):
    """{mesh name: (users, faces)} of the set's faces without 3D area (on the first user, as the packer measures)."""
    cm2 = uv_pack._cm_per_unit(bpy.context.scene) ** 2
    out = {}
    for md, users, faces in uv_pack.gather(view_layer, material)[0]:
        hit = faces[md.face_areas_world(users[0].matrix_world, cm2)[faces] <= uv_pack.FACE_AREA_MIN_CM2]
        if len(hit):
            out[md.me.name] = (sorted(u.name for u in users), hit)
    return out


def _face_rows(kind, found, what, fix):
    out = []
    for mesh, (names, faces) in sorted(found.items(), key=lambda item: (-len(item[1][1]), item[0])):
        users = uv_pack._names(names, 4)
        out.append({'kind': kind, 'mesh': mesh, 'objects': names, 'text': f"{what}: {mesh} ({len(faces)} face(s))",
                    'tip': f"{len(faces)} face(s) of {mesh} {fix}. Used by {users}"})
    return out


def collect(view_layer, material):
    """The set's problem rows from the scene as it is: shared meshes left out, users without a material, then the
    meshes with faces without UV area and without area, the most faces first."""
    out = []
    diffs = uv_pack.shared_differences(view_layer, material)
    named = set()
    for d in diffs:
        if d['in_set']:
            continue
        shows = uv_pack._material_text(d['first_shows'])
        out.append({'kind': LEFT_OUT, 'mesh': d['mesh'], 'objects': [d['first_user']],
                    'text': f"Left out: {d['mesh']} ({d['first_user']})",
                    'tip': (f"The shared mesh {d['mesh']} is not packed with this set, its UVs stay as they are. A "
                            f"shared mesh takes the materials of its first user by name, {d['first_user']}, which "
                            f"shows {shows} where {len(d['users'])} other user(s) show this set. Give "
                            f"{d['first_user']} this set's material")})
        if None in d['first_shows']:
            named.add(d['first_user'])  # its row says it already
    for name in uv_pack.no_material_users(diffs):
        if name not in named:
            out.append({'kind': NO_MATERIAL, 'mesh': None, 'objects': [name], 'text': f"No material: {name}",
                        'tip': (f"{name} shows no material where other users of its shared mesh show this set: it "
                                "exports without a material there. Give it this set's material")})
    out += _face_rows(NO_UV_AREA, faces_without_uv_area(view_layer, material), 'No UV area',
                      'have triangles without UV area: they push islands out of the layout. Re-unwrap them, for '
                      'example with Accept + Unwrap')
    out += _face_rows(NO_AREA, faces_without_area(view_layer, material), 'No area',
                      'have no area: they push islands out of the layout. Fix the geometry')
    for row in out:
        row['fixed'] = False
    return out


def update(material, view_layer=None):
    """Collect the set's rows again (after Pack, Check All, Recheck). Returns them."""
    if material is None:
        return []
    found = collect(view_layer or bpy.context.view_layer, material)
    _problems[material.name] = found
    return found


def current(view_layer, material, row):
    """What is left of a row's problem now: True or (users, faces) while it is there, None when it is gone."""
    kind = row['kind']
    if kind == LEFT_OUT:
        return True if any(d['mesh'] == row['mesh'] and not d['in_set']
                           for d in uv_pack.shared_differences(view_layer, material)) else None
    if kind == NO_MATERIAL:
        return True if row['objects'][0] in uv_pack.no_material_users(
            uv_pack.shared_differences(view_layer, material)) else None
    found = (faces_without_uv_area if kind == NO_UV_AREA else faces_without_area)(view_layer, material)
    return found.get(row['mesh'])


def live_rows(material):
    """(icon, text) of the rows read from the last result and the material: they only inform."""
    out = []
    result = uv_marks._results.get(material.name)
    if uv_marks.margin(material) < uv_marks.BLOCK_PIXELS:
        out.append(('ERROR', f'Margin under {uv_marks.BLOCK_PIXELS} px: compressed 4x4 blocks bleed across islands'))
    if result and result.get('mode') == 'overflow' and not uv_pack.is_kept(material):
        out.append(('ERROR', 'Does not fit this texture size'))
    return out


def summary(material):
    """The tooltip lines of a texture set's problems: the live ones, then the rows not fixed."""
    found = rows(material) or []
    lines = [text for _icon, text in live_rows(material)] + [row['text'] for row in found if not row['fixed']]
    return lines[:8] + ([f"... {len(lines) - 8} more"] if len(lines) > 8 else [])


def shown_material(context):
    """The texture set whose problems the list shows: the highlighted row of the texture set table, None when no row
    of the table is highlighted (the maintainer, Session 120)."""
    name = context.window_manager.fss_uv_pack_active_name
    return next((m for m in uv_marks.texture_set_materials(context) if m.name == name), None) if name else None


def _frame_selected(context):
    """Zoom the window's 3D viewports to the selection (none in background mode); a viewport looking through the
    camera is left alone (zooming it could move the camera)."""
    window = context.window
    if window is None:
        return
    for area in window.screen.areas:
        if area.type != 'VIEW_3D' or area.spaces.active.region_3d.view_perspective == 'CAMERA':
            continue
        region = next((r for r in area.regions if r.type == 'WINDOW'), None)
        if region is not None:
            with context.temp_override(window=window, area=area, region=region):
                bpy.ops.view3d.view_selected()


def _show_objects(context, objects):
    """Make the first visible object active, add the objects to the selection and zoom to them alone. The earlier
    selection stays: an object without the set's material would otherwise take the set out of the table, and its
    Problems list with it."""
    shown = [obj for obj in objects if obj is not None and obj.visible_get()]
    if not shown:
        return shown
    others = [obj for obj in context.selected_objects if obj not in shown]
    for obj in others:
        obj.select_set(False)
    for obj in shown:
        obj.select_set(True)
    context.view_layer.objects.active = shown[0]
    _frame_selected(context)
    for obj in others:
        obj.select_set(True)
    return shown


def _redraw():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type in uv_marks.SPACES:
                area.tag_redraw()


class FSS_OT_UvProblemShow(bpy.types.Operator):
    """A problem row: checks it again, then selects its objects or faces and zooms to them."""
    bl_idname = 'fss.uv_problem_show'
    bl_label = 'Show Problem'
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    material: bpy.props.StringProperty(options={'HIDDEN'})
    index: bpy.props.IntProperty(options={'HIDDEN'})

    @classmethod
    def _row(cls, properties):
        found = _problems.get(properties.material) or []
        return found[properties.index] if 0 <= properties.index < len(found) else None

    @classmethod
    def description(cls, context, properties):
        row = cls._row(properties)
        if row is None:
            return ''
        if row['fixed']:
            return row['tip'] + '.\nFixed: gone at the last click; Recheck drops it'
        click = ('make it active and zoom to it (the selection stays)' if row['kind'] in (LEFT_OUT, NO_MATERIAL) else
                 'Edit Mode with only those faces selected, the view zoomed to them')
        return f"{row['tip']}.\nClick: check it again, then {click}"

    def execute(self, context):
        row = self._row(self)
        material = bpy.data.materials.get(self.material)
        if row is None or material is None:
            return {'CANCELLED'}
        # the list keeps showing this set when the selection changes to objects without it
        context.window_manager.fss_uv_pack_active_name = material.name
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')  # the mesh data is current only in Object Mode
        view_layer = context.view_layer
        now = current(view_layer, material, row)
        if now is None:
            row['fixed'] = True
            _redraw()
            self.report({'INFO'}, f"Fixed: {row['text']}")
            return {'FINISHED'}
        row['fixed'] = False
        if row['kind'] in (LEFT_OUT, NO_MATERIAL):
            shown = _show_objects(context, [view_layer.objects.get(name) for name in row['objects']])
        else:  # the objects with those faces use the set: the table keeps it
            names, faces = now
            shown = checks._select_found(context, {obj: faces for obj in
                                                   (view_layer.objects.get(name) for name in names) if obj})
            if shown:
                bpy.ops.object.mode_set(mode='EDIT')
                _frame_selected(context)
        if not shown:
            self.report({'WARNING'}, f"{row['text']}: on hidden objects ({uv_pack._names(row['objects'], 4)})")
            return {'FINISHED'}
        how = 'made active' if row['kind'] in (LEFT_OUT, NO_MATERIAL) else 'selected in Edit Mode'
        self.report({'WARNING'}, f"{row['text']}: {uv_pack._names([o.name for o in shown], 4)} {how}")
        return {'FINISHED'}


class FSS_OT_UvProblemsRecheck(bpy.types.Operator):
    bl_idname = 'fss.uv_problems_recheck'
    bl_label = 'Recheck'
    bl_description = ("Look for this texture set's problems again, without packing: fixed ones leave the list")
    bl_options = {'REGISTER', 'INTERNAL'}

    material: bpy.props.StringProperty(options={'HIDDEN'})

    def execute(self, context):
        material = bpy.data.materials.get(self.material)
        if material is None:
            return {'CANCELLED'}
        context.window_manager.fss_uv_pack_active_name = material.name
        if context.mode == 'EDIT_MESH':
            bpy.ops.object.mode_set(mode='OBJECT')
            found = update(material)
            bpy.ops.object.mode_set(mode='EDIT')
        else:
            found = update(material)
        _redraw()
        self.report({'WARNING'} if found else {'INFO'},
                    f"{material.name}: {len(found)} problem(s)" if found else f"{material.name}: no problems found")
        return {'FINISHED'}


def _fitted_end(context, text):
    """The text with its end replaced by '...' to fit the panel (the kind of problem stays readable)."""
    region = context.region
    if region is None or region.width <= 1:
        return text
    scale = context.preferences.system.ui_scale
    blf.size(0, context.preferences.ui_styles[0].widget.points * scale)
    width = region.width - (uv_marks.PANEL_PADDING + TEXT_PADDING) * scale - uv_marks.BUTTON_PADDING * scale
    if blf.dimensions(0, text)[0] <= width:
        return text
    for count in range(len(text) - 1, 0, -1):
        if blf.dimensions(0, text[:count] + '...')[0] <= width:
            return text[:count] + '...'
    return text[:1]


def draw(layout, context):
    """The Problems box of the shown texture set: its rows, Recheck."""
    material = shown_material(context)
    if material is None:
        if uv_marks.texture_set_materials(context):
            layout.box().label(text="Click a texture set's name to see its problems", icon='INFO')
        return
    if uv_pack.is_kept(material):
        return
    box = layout.box()
    head = box.row()
    head.label(text=_fitted_end(context, f"Problems: {material.name}"))
    head.operator(FSS_OT_UvProblemsRecheck.bl_idname, text='Recheck', icon='FILE_REFRESH').material = material.name
    live = live_rows(material)
    for icon, text in live:
        box.label(text=text, icon=icon)
    found = rows(material)
    if found is None:
        if not live:
            box.label(text='Not checked yet: Recheck, Pack or Check All', icon='INFO')
        return
    if not found and not live:
        box.label(text='No problems found', icon='CHECKMARK')
        return
    column = box.column(align=True)
    for index, row in enumerate(found[:PROBLEM_ROWS]):
        line = column.row()
        line.alignment = 'LEFT'
        line.active = not row['fixed']
        op = line.operator(FSS_OT_UvProblemShow.bl_idname, text=_fitted_end(context, row['text']),
                           icon='CHECKMARK' if row['fixed'] else ICONS[row['kind']], emboss=False)
        op.material = material.name
        op.index = index
    if len(found) > PROBLEM_ROWS:
        box.label(text=f"{len(found) - PROBLEM_ROWS} more: fix these and Recheck")


CLASSES = (FSS_OT_UvProblemShow, FSS_OT_UvProblemsRecheck)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    _problems.clear()
