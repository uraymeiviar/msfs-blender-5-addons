"""UV Align marks (native UV packer decisions 7 and 12): edges the artist marks Horizontal, Vertical or Either, so that
the packer turns their island until those edges lie along that axis of the texture.

The mark is the integer edge attribute fss_uv_align (0 none, 1 Horizontal, 2 Vertical, 3 Either: the nearer of the two
axes). Mark UV Align and Clear UV Align act on the selected edges in Edit Mode: in the 3D view's Edge menu and context
menu, and in the UV editor's UV menu and context menu (there, without UV sync selection, on the edges selected in the UV
editor). A seam edge belongs to two islands; its mark counts in both.

The packer (uv_pack) turns each island with marked edges by the angle that fits all of them best, each edge weighted by
its UV length (best_fit), and from there turns it only as keeps them on their axes: by 180 degrees with a Horizontal or
Vertical edge, in 90-degree steps with only Either edges, never more than the island's direction allows. An edge left
more than MAX_OFF_DEG off its axis is reported. Select UV Align Edges selects the marked edges; uv_align_draw draws
them (Show UV Align in the same menu).
"""

import math

import bmesh
import bpy
import numpy as np

ALIGN_KEY = 'fss_uv_align'
NONE, HORIZONTAL, VERTICAL, EITHER = 0, 1, 2, 3
KINDS = [
    ('HORIZONTAL', 'Horizontal', 'The packer turns the island until these edges lie horizontally in the UV map'),
    ('VERTICAL', 'Vertical', 'The packer turns the island until these edges lie vertically in the UV map'),
    ('EITHER', 'Either', 'The packer turns the island until these edges lie along the nearer axis of the UV map'),
]
CODES = {'HORIZONTAL': HORIZONTAL, 'VERTICAL': VERTICAL, 'EITHER': EITHER}
MAX_OFF_DEG = 0.5  # an aligned edge further off its axis than this is reported (decision 12)
SCAN_STEP_DEG, REFINE_STEP_DEG = 0.5, 0.01


def edge_marks(me):
    """The marks of a mesh's edges (an int array), or None when none is marked. In Object Mode."""
    attribute = me.attributes.get(ALIGN_KEY)
    if attribute is None or attribute.domain != 'EDGE' or attribute.data_type != 'INT':
        return None
    values = np.zeros(len(me.edges), np.int32)
    attribute.data.foreach_get('value', values)
    return values if values.any() else None


def residual(angle, kind):
    """How far (radians, signed) segments at `angle` lie from their axis: Horizontal from 0 or 180 degrees, Vertical
    from 90 or 270, Either from the nearer of them."""
    half = math.pi / 2.0
    return np.where(kind == EITHER, np.mod(angle + half / 2.0, half) - half / 2.0,
                    np.where(kind == VERTICAL, np.mod(angle, math.pi) - half, np.mod(angle + half, math.pi) - half))


def best_fit(angle, weight, kind):
    """The turn (radians, -90 to 90 degrees) that brings segments of these angles (radians), weights (UV lengths) and
    kinds closest to their axes: the least weighted sum of squared residuals, scanned in SCAN_STEP_DEG and refined in
    REFINE_STEP_DEG; of equals the smallest turn. Returns (turn, the largest residual after it, radians)."""
    angle, weight, kind = np.asarray(angle, np.float64), np.asarray(weight, np.float64), np.asarray(kind)

    def cost(turns):
        r = residual(angle[None] + turns[:, None], kind[None])
        return (weight[None] * r * r).sum(1)

    turns = np.radians(np.arange(-90.0, 90.0, SCAN_STEP_DEG))
    c = cost(turns)
    best = turns[np.lexsort((np.abs(turns), c))[0]]
    fine = best + np.radians(np.arange(-SCAN_STEP_DEG, SCAN_STEP_DEG + 1e-9, REFINE_STEP_DEG))
    c = cost(fine)
    best = float(fine[np.lexsort((np.abs(fine), c))[0]])
    if abs(best) < 1e-12:
        best = 0.0
    return best, float(np.abs(residual(angle + best, kind)).max())


def _uv_editor_selection(context):
    """True when the edges to mark are those selected in the UV editor (it is the area, without UV sync selection)."""
    area = getattr(context, 'area', None)
    return area is not None and area.type == 'IMAGE_EDITOR' and not context.scene.tool_settings.use_uv_select_sync


def _selected_edges(bm, uv_editor):
    if not uv_editor:
        return [e for e in bm.edges if e.select]
    # Blender 5.2 keeps the UV editor's selection on the loops (BMLoop.uv_select_edge)
    return [e for e in bm.edges if any(loop.uv_select_edge for loop in e.link_loops)]


def mark(context, code):
    """Set the mark of the selected edges of the meshes in Edit Mode (0 clears it). Returns the edges changed."""
    uv_editor = _uv_editor_selection(context)
    count = 0
    for obj in {o.data: o for o in context.objects_in_mode_unique_data if o.type == 'MESH'}.values():
        me = obj.data
        bm = bmesh.from_edit_mesh(me)
        layer = bm.edges.layers.int.get(ALIGN_KEY)
        indices = [e.index for e in _selected_edges(bm, uv_editor)]
        if not indices or (layer is None and code == NONE):
            continue
        if layer is None:
            layer = bm.edges.layers.int.new(ALIGN_KEY)  # a new layer drops the references to the edges taken before
        bm.edges.ensure_lookup_table()
        for e in (bm.edges[i] for i in indices):
            if e[layer] != code:
                e[layer] = code
                count += 1
        if code == NONE and not any(e[layer] for e in bm.edges):
            bm.edges.layers.int.remove(layer)  # a mesh without marks keeps no attribute
        bmesh.update_edit_mesh(me, loop_triangles=False, destructive=False)
    return count


class FSS_OT_UvMarkAlign(bpy.types.Operator):
    bl_idname = 'fss.uv_mark_align'
    bl_label = 'Mark UV Align'
    bl_description = ('Mark the selected edges: Pack turns their island until they lie along this axis of the UV map; '
                      'with several marked edges, the turn that fits all of them best')
    bl_options = {'REGISTER', 'UNDO'}

    kind: bpy.props.EnumProperty(name='Axis', items=KINDS, default='HORIZONTAL')

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        count = mark(context, CODES[self.kind])
        label = next(item[1] for item in KINDS if item[0] == self.kind)
        self.report({'INFO'}, f'{count} edge(s) marked UV Align {label}')
        return {'FINISHED'}


class FSS_OT_UvClearAlign(bpy.types.Operator):
    bl_idname = 'fss.uv_clear_align'
    bl_label = 'Clear UV Align'
    bl_description = 'Clear the UV Align mark of the selected edges'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        self.report({'INFO'}, f'UV Align cleared on {mark(context, NONE)} edge(s)')
        return {'FINISHED'}


class FSS_OT_UvSelectAlign(bpy.types.Operator):
    bl_idname = 'fss.uv_select_align'
    bl_label = 'Select UV Align Edges'
    bl_description = ('Select the edges marked UV Align. In the UV editor without UV sync selection, their UV edges '
                      'on the faces it shows')
    bl_options = {'REGISTER', 'UNDO'}

    extend: bpy.props.BoolProperty(name='Extend', default=False, description='Add to the selection')

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        uv_editor = _uv_editor_selection(context)
        if not uv_editor and not self.extend:
            bpy.ops.mesh.select_all(action='DESELECT')
        count = 0
        for obj in {o.data: o for o in context.objects_in_mode_unique_data if o.type == 'MESH'}.values():
            bm = bmesh.from_edit_mesh(obj.data)
            layer = bm.edges.layers.int.get(ALIGN_KEY)
            if uv_editor and not self.extend:  # the UV selection only: the mesh selection says which faces show
                for face in bm.faces:
                    for loop in face.loops:
                        loop.uv_select_edge_set(False)
                        loop.uv_select_vert_set(False)
            if layer is None:
                bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
                continue
            for e in bm.edges:
                if not e[layer] or e.hide:
                    continue
                count += 1
                if uv_editor:
                    for loop in e.link_loops:
                        loop.uv_select_edge_set(True)
                        loop.uv_select_vert_set(True)
                        loop.link_loop_next.uv_select_vert_set(True)
                else:
                    e.select_set(True)
            if not uv_editor:
                bm.select_flush_mode()
            bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
        self.report({'INFO'}, f'{count} UV Align edge(s) selected')
        return {'FINISHED'}


class FSS_MT_UvAlign(bpy.types.Menu):
    bl_idname = 'FSS_MT_uv_align'
    bl_label = 'UV Align'

    def draw(self, context):
        layout = self.layout
        for key, label, _text in KINDS:
            layout.operator(FSS_OT_UvMarkAlign.bl_idname, text=f'Mark {label}').kind = key
        layout.separator()
        layout.operator(FSS_OT_UvClearAlign.bl_idname, text='Clear')
        layout.separator()
        layout.operator(FSS_OT_UvSelectAlign.bl_idname, text='Select UV Align Edges')
        layout.prop(context.window_manager, 'fss_uv_align_show')  # uv_align_draw's overlay


def _menu(self, context):
    self.layout.separator()
    self.layout.menu(FSS_MT_UvAlign.bl_idname)


MENUS = ('VIEW3D_MT_edit_mesh_edges', 'VIEW3D_MT_edit_mesh_context_menu', 'IMAGE_MT_uvs', 'IMAGE_MT_uvs_context_menu')
CLASSES = (FSS_OT_UvMarkAlign, FSS_OT_UvClearAlign, FSS_OT_UvSelectAlign, FSS_MT_UvAlign)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    for name in MENUS:
        menu = getattr(bpy.types, name, None)
        if menu is not None:
            menu.append(_menu)


def unregister():
    for name in MENUS:
        menu = getattr(bpy.types, name, None)
        if menu is not None:
            menu.remove(_menu)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
