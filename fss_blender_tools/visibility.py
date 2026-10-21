"""FSS Blender Tools: Visibility Test panel, settings and operators.

Enables artists to select cameras, configure animation states, run visibility analysis,
and view inspection reports (Decisions 80, 81, 83, 86).
"""

import json
from pathlib import Path
import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty
from mathutils import Vector

from . import visibility_core


# ---------------------------------------------------------------------------
# Camera List Item & Settings PropertyGroup (Decision 83 & 86)
# ---------------------------------------------------------------------------

class FSS_VisibilityCameraItem(bpy.types.PropertyGroup):
    """Camera entry in the visibility test list."""
    camera_name: StringProperty(name="Camera Name")
    include: BoolProperty(name="Include", default=False, description="Include this camera in visibility analysis")
    mode: EnumProperty(
        name="Mode",
        items=[
            ('LOOK_AROUND', 'Look Around', 'Full 360-degree cube map view centered at camera position'),
            ('FIXED_VIEW', 'Fixed View', 'Fixed perspective camera frustum matching camera focal length and resolution'),
        ],
        default='LOOK_AROUND',
        description="Camera viewing mode"
    )


class FSS_VisibilitySettings(bpy.types.PropertyGroup):
    """Scene visibility test settings."""
    cameras: CollectionProperty(type=FSS_VisibilityCameraItem)
    active_camera_index: IntProperty(default=0)

    states: IntProperty(
        name="States",
        default=5,
        min=2,
        max=10,
        description="Animation states evenly spaced over each action length (2 to 10, Decision 86)"
    )

    floor: FloatProperty(
        name="Direction Floor",
        default=0.2,
        min=0.0,
        max=1.0,
        precision=2,
        description="Minimum weight for side/rear views during look-around (Decision 73)"
    )

    falloff: FloatProperty(
        name="Direction Falloff",
        default=1.0,
        min=0.1,
        max=10.0,
        precision=1,
        description="Direction falloff power from forward view (Decision 73)"
    )

    cube_res: IntProperty(
        name="Cube Resolution",
        default=1024,
        min=256,
        max=4096,
        description="Resolution per cube map face in pixels (changing alters scores)"
    )

    min_px_threshold: FloatProperty(
        name="Min Threshold (px)",
        default=10.0,
        min=1.0,
        max=100.0,
        precision=1,
        description="Reference cube pixel threshold for measurable geometry (changing alters scores)"
    )

    show_advanced: BoolProperty(
        name="Advanced Settings",
        default=False,
        description="Display advanced parameters (cube resolution, thresholds)"
    )


def sync_camera_list(scene):
    """Synchronize camera collection with scene cameras (follow added, renamed or deleted)."""
    settings = getattr(scene, 'fss_visibility', None)
    if settings is None:
        return

    existing_settings = {item.camera_name: (item.include, item.mode) for item in settings.cameras}
    scene_cams = sorted([o.name for o in scene.objects if o.type == 'CAMERA'])

    # Rebuild collection preserving settings
    settings.cameras.clear()
    for cam_name in scene_cams:
        item = settings.cameras.add()
        item.camera_name = cam_name
        if cam_name in existing_settings:
            item.include, item.mode = existing_settings[cam_name]
        else:
            item.include = False
            item.mode = 'LOOK_AROUND'


# ---------------------------------------------------------------------------
# Report Text Generation
# ---------------------------------------------------------------------------

REPORT_TEXT_NAME = "FSS Visibility Report"


def write_visibility_report_text(results, vis_path, elapsed_time):
    """Write comprehensive human-readable summary into Blender Text datablock."""
    txt = bpy.data.texts.get(REPORT_TEXT_NAME)
    if not txt:
        txt = bpy.data.texts.new(REPORT_TEXT_NAME)
    txt.clear()

    lines = []
    lines.append("=" * 80)
    lines.append("                        FSS VISIBILITY REPORT")
    lines.append("=" * 80)
    lines.append(f"Blend File:    {results.get('blend_file', '')}")
    lines.append(f"Saved Data:    {vis_path}")
    lines.append(f"Elapsed Time:  {elapsed_time:.2f} s (Patch Expansion: {results.get('patch_expansion_time_s', 0):.2f} s)")
    lines.append("")

    lines.append("VIEWS ANALYSED:")
    for v in results.get('views', []):
        lines.append(f"  - Camera: {v['camera']:<24} Mode: {v.get('type', 'LOOK_AROUND'):<14} State: {int(v['state']*100)}%")
    lines.append("")

    lines.append("GEOMETRY TOTALS:")
    lines.append(f"  Total Evaluated Faces:  {results.get('total_faces', 0):,}")
    lines.append(f"  Total Surface Area:     {results.get('total_surface_area_m2', 0):.2f} m²")
    lines.append(f"  Total Objects:          {results.get('total_objects', 0):,}")
    lines.append(f"  Total UV Islands:       {results.get('total_islands', 0):,}")
    lines.append("")

    lines.append("VISIBILITY & OCCLUSION:")
    tot_f = max(results.get('total_faces', 1), 1)
    tot_a = max(results.get('total_surface_area_m2', 1e-6), 1e-6)
    nv_f = results.get('total_never_seen_faces', 0)
    nv_a = results.get('total_never_seen_face_area_m2', 0.0)
    ud_f = results.get('total_undetermined_faces', 0)
    ud_a = results.get('total_undetermined_face_area_m2', 0.0)

    lines.append(f"  Never-Seen Faces:       {nv_f:,} ({nv_f / tot_f:.1%}) | Area: {nv_a:.2f} m² ({nv_a / tot_a:.1%})")
    lines.append(f"  Never-Seen Objects:     {results.get('never_seen_objects_count', 0):,}")
    lines.append(f"  Never-Seen UV Islands:  {results.get('never_seen_islands_count', 0):,}")
    lines.append(f"  Undetermined Faces:     {ud_f:,} ({ud_f / tot_f:.1%}) | Area: {ud_a:.2f} m² ({ud_a / tot_a:.1%})")
    lines.append(f"  Undetermined Objects:   {results.get('undetermined_objects_count', 0):,}")
    lines.append("")

    fp = results.get('face_percentiles', {})
    ip = results.get('island_percentiles', {})
    lines.append("SCORE DISTRIBUTION (Area-Weighted):")
    lines.append(f"  Faces:    p50 = {fp.get('p50', 0):.4f} | p90 = {fp.get('p90', 0):.4f} | p95 = {fp.get('p95', 0):.4f}")
    lines.append(f"  Islands:  p50 = {ip.get('p50', 0):.4f} | p90 = {ip.get('p90', 0):.4f} | p95 = {ip.get('p95', 0):.4f}")
    lines.append("")

    obj_sums = results.get('object_summaries', {})
    never_seen_objs = [name for name, d in obj_sums.items() if d.get('never_seen')]
    if never_seen_objs:
        lines.append("NEVER-SEEN OBJECTS (Candidates to inspect):")
        for name in sorted(never_seen_objs)[:50]:
            lines.append(f"  - {name} ({obj_sums[name].get('area_m2', 0):.4f} m²)")
        if len(never_seen_objs) > 50:
            lines.append(f"  ... and {len(never_seen_objs) - 50} more")
        lines.append("")

    measurable = [(name, d) for name, d in obj_sums.items() if not d.get('never_seen') and not d.get('undetermined')]
    measurable.sort(key=lambda x: x[1].get('score', 0.0), reverse=True)

    lines.append("TOP 20 MOST VISIBLE MEASURABLE OBJECTS:")
    for name, d in measurable[:20]:
        lines.append(f"  {d.get('score', 0.0):.4f} | {d.get('size_px', 0):6.1f} px | {d.get('area_m2', 0):.4f} m² | {name}")
    lines.append("")

    lines.append("BOTTOM 20 LEAST VISIBLE MEASURABLE OBJECTS:")
    for name, d in measurable[-20:]:
        lines.append(f"  {d.get('score', 0.0):.4f} | {d.get('size_px', 0):6.1f} px | {d.get('area_m2', 0):.4f} m² | {name}")
    lines.append("")

    lines.append("=" * 80)
    txt.write("\n".join(lines))


# ---------------------------------------------------------------------------
# Operators (Update Visibility, Select Never-Seen, Select Stale)
# ---------------------------------------------------------------------------

class FSS_OT_UpdateVisibility(bpy.types.Operator):
    """Analyse scene visibility from artist-defined cameras across animation states."""
    bl_idname = 'fss.update_visibility'
    bl_label = 'Update Visibility'
    bl_description = "Measure visibility from included cameras and write <blend_name>.visibility beside the file"
    bl_options = {'REGISTER'}

    _timer = None
    _analyzer = None

    @classmethod
    def poll(cls, context):
        if not bpy.data.is_saved or not bpy.data.filepath:
            return False
        settings = getattr(context.scene, 'fss_visibility', None)
        if not settings or not any(item.include for item in settings.cameras):
            return False
        return True

    def _get_included_cameras(self, context):
        settings = context.scene.fss_visibility
        cams = []
        for item in settings.cameras:
            if not item.include:
                continue
            cam_obj = bpy.data.objects.get(item.camera_name)
            if cam_obj is None or cam_obj.type != 'CAMERA':
                continue
            cams.append({
                'name': cam_obj.name,
                'type': item.mode,
                'pos': cam_obj.matrix_world.translation.copy(),
                'forward': visibility_core.get_camera_forward(cam_obj),
                'obj_name': cam_obj.name,
            })
        return cams

    def _get_anim_states(self, context):
        n_states = max(2, min(10, context.scene.fss_visibility.states))
        return tuple(i / (n_states - 1) for i in range(n_states))

    def _get_settings_dict(self, context):
        s = context.scene.fss_visibility
        return {
            'cameras': [{'name': item.camera_name, 'mode': item.mode} for item in s.cameras if item.include],
            'states': s.states,
            'floor': s.floor,
            'falloff': s.falloff,
            'cube_res': s.cube_res,
            'min_px_threshold': s.min_px_threshold,
        }

    def invoke(self, context, event):
        if not self.poll(context):
            self.report({'WARNING'}, "Cannot run: .blend must be saved and at least one camera included.")
            return {'CANCELLED'}

        cameras = self._get_included_cameras(context)
        if not cameras:
            self.report({'WARNING'}, "No included cameras found in the scene.")
            return {'CANCELLED'}

        anim_states = self._get_anim_states(context)
        s = context.scene.fss_visibility

        self._analyzer = visibility_core.VisibilityAnalyzer(
            scene=context.scene,
            view_layer=context.view_layer,
            cameras=cameras,
            anim_states=anim_states,
            cube_res=s.cube_res,
            floor=s.floor,
            falloff=s.falloff,
            min_px_threshold=s.min_px_threshold,
            blend_path=bpy.data.filepath,
        )

        try:
            self._analyzer.prepare()
        except Exception as e:
            if self._analyzer:
                self._analyzer.cleanup()
                self._analyzer = None
            self.report({'ERROR'}, f"Failed to prepare visibility analysis: {e}")
            return {'CANCELLED'}

        # Modal execution in interactive Blender
        if not bpy.app.background:
            wm = context.window_manager
            self._timer = wm.event_timer_add(0.01, window=context.window)
            wm.modal_handler_add(self)
            context.workspace.status_text_set("FSS Visibility: Starting analysis...")
            return {'RUNNING_MODAL'}

        return self.execute(context)

    def modal(self, context, event):
        if event.type == 'ESC':
            if self._timer:
                context.window_manager.event_timer_remove(self._timer)
                self._timer = None
            context.workspace.status_text_set(None)
            if self._analyzer:
                self._analyzer.cleanup()
                self._analyzer = None
            self.report({'INFO'}, "Visibility analysis cancelled by Esc. Nothing was written.")
            return {'CANCELLED'}

        if event.type == 'TIMER':
            if self._analyzer and not self._analyzer.is_finished():
                try:
                    step_info = self._analyzer.execute_next_step()
                    if step_info:
                        pct = int(round(step_info['state_pct'] * 100))
                        msg = (f"FSS Visibility: State {pct}%, Camera '{step_info['camera']}' "
                               f"({step_info['step']}/{step_info['total_steps']})...")
                        context.workspace.status_text_set(msg)
                except Exception as e:
                    if self._timer:
                        context.window_manager.event_timer_remove(self._timer)
                        self._timer = None
                    context.workspace.status_text_set(None)
                    if self._analyzer:
                        self._analyzer.cleanup()
                        self._analyzer = None
                    self.report({'ERROR'}, f"Error during visibility step: {e}")
                    return {'CANCELLED'}
                return {'RUNNING_MODAL'}

            # Completed!
            if self._timer:
                context.window_manager.event_timer_remove(self._timer)
                self._timer = None
            context.workspace.status_text_set(None)

            try:
                results = self._analyzer.finalize()
                settings = self._get_settings_dict(context)
                vis_path = visibility_core.save_visibility_file(bpy.data.filepath, results, settings=settings)
                write_visibility_report_text(results, vis_path, results['total_time_s'])
                self.report(
                    {'INFO'},
                    f"Visibility updated in {results['total_time_s']:.2f}s. Saved '{vis_path.name}'. "
                    f"See '{REPORT_TEXT_NAME}'."
                )
            finally:
                if self._analyzer:
                    self._analyzer.cleanup()
                    self._analyzer = None

            for area in context.screen.areas if context.screen else []:
                area.tag_redraw()
            return {'FINISHED'}

        return {'PASS_THROUGH'}

    def execute(self, context):
        if self._analyzer is None:
            cameras = self._get_included_cameras(context)
            if not cameras:
                self.report({'WARNING'}, "No included cameras found.")
                return {'CANCELLED'}
            anim_states = self._get_anim_states(context)
            s = context.scene.fss_visibility
            self._analyzer = visibility_core.VisibilityAnalyzer(
                scene=context.scene,
                view_layer=context.view_layer,
                cameras=cameras,
                anim_states=anim_states,
                cube_res=s.cube_res,
                floor=s.floor,
                falloff=s.falloff,
                min_px_threshold=s.min_px_threshold,
                blend_path=bpy.data.filepath,
            )
            self._analyzer.prepare()

        try:
            while not self._analyzer.is_finished():
                self._analyzer.execute_next_step()
            results = self._analyzer.finalize()
            settings = self._get_settings_dict(context)
            vis_path = visibility_core.save_visibility_file(bpy.data.filepath, results, settings=settings)
            write_visibility_report_text(results, vis_path, results['total_time_s'])
            self.report(
                {'INFO'},
                f"Visibility updated in {results['total_time_s']:.2f}s. Saved '{vis_path.name}'. "
                f"See '{REPORT_TEXT_NAME}'."
            )
        finally:
            self._analyzer.cleanup()
            self._analyzer = None

        return {'FINISHED'}


class FSS_OT_VisibilitySelectNeverSeen(bpy.types.Operator):
    """Select scene objects that were never seen in the visibility analysis."""
    bl_idname = 'fss.visibility_select_never_seen'
    bl_label = 'Select Never Seen'
    bl_description = "Select objects classified as never seen in the current .visibility file"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if not bpy.data.filepath:
            return False
        vis_path = Path(bpy.data.filepath).with_suffix('.visibility')
        return vis_path.exists()

    def execute(self, context):
        vis_path = Path(bpy.data.filepath).with_suffix('.visibility')
        try:
            meta, _, _ = visibility_core.load_visibility_file(vis_path, scene_meshes=bpy.data.meshes)
        except Exception as e:
            self.report({'ERROR'}, f"Failed to load visibility file: {e}")
            return {'CANCELLED'}

        obj_sums = meta.get('object_summaries', {})
        never_seen_names = {name for name, d in obj_sums.items() if d.get('never_seen')}

        count = 0
        bpy.ops.object.select_all(action='DESELECT')
        first_selected = None
        for obj in context.view_layer.objects:
            if obj.name in never_seen_names:
                obj.select_set(True)
                if first_selected is None:
                    first_selected = obj
                count += 1

        if first_selected:
            context.view_layer.objects.active = first_selected

        self.report({'INFO'}, f"Selected {count} never-seen object(s).")
        return {'FINISHED'}


class FSS_OT_VisibilitySelectStale(bpy.types.Operator):
    """Select scene objects whose mesh polygon counts changed since visibility analysis."""
    bl_idname = 'fss.visibility_select_stale'
    bl_label = 'Select Stale'
    bl_description = "Select objects whose meshes have changed since the last visibility analysis"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if not bpy.data.filepath:
            return False
        vis_path = Path(bpy.data.filepath).with_suffix('.visibility')
        return vis_path.exists()

    def execute(self, context):
        vis_path = Path(bpy.data.filepath).with_suffix('.visibility')
        try:
            _, _, stale_meshes = visibility_core.load_visibility_file(vis_path, scene_meshes=bpy.data.meshes)
        except Exception as e:
            self.report({'ERROR'}, f"Failed to load visibility file: {e}")
            return {'CANCELLED'}

        if not stale_meshes:
            self.report({'INFO'}, "All meshes are up to date; none are stale.")
            return {'FINISHED'}

        stale_set = set(stale_meshes)
        count = 0
        bpy.ops.object.select_all(action='DESELECT')
        first_selected = None
        for obj in context.view_layer.objects:
            if obj.type == 'MESH' and obj.data and obj.data.name in stale_set:
                obj.select_set(True)
                if first_selected is None:
                    first_selected = obj
                count += 1

        if first_selected:
            context.view_layer.objects.active = first_selected

        self.report({'INFO'}, f"Selected {count} object(s) with stale meshes ({', '.join(stale_meshes[:5])}).")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# UI List for Cameras
# ---------------------------------------------------------------------------

class FSS_UL_VisibilityCameraList(bpy.types.UIList):
    """Camera item row rendering."""
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row.prop(item, 'include', text="")
            row.label(text=item.camera_name, icon='CAMERA_DATA')
            sub = row.row(align=True)
            sub.enabled = item.include
            sub.prop(item, 'mode', text="")
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text=item.camera_name, icon='CAMERA_DATA')


# ---------------------------------------------------------------------------
# Visibility Test Panel (Decision 83)
# ---------------------------------------------------------------------------

class FSS_PT_Visibility(bpy.types.Panel):
    """Visibility Test panel in sidebar FSS Tools."""
    bl_idname = 'FSS_PT_visibility'
    bl_label = 'Visibility Test'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'FSS Tools'

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # Keep camera list in sync with scene cameras
        sync_camera_list(scene)
        settings = scene.fss_visibility

        # 1. Cameras list
        box = layout.box()
        box.label(text="Reference Cameras:", icon='OUTLINER_OB_CAMERA')
        if len(settings.cameras) == 0:
            box.label(text="No cameras in scene. Add a camera first.", icon='INFO')
        else:
            box.template_list(
                "FSS_UL_VisibilityCameraList",
                "",
                settings,
                "cameras",
                settings,
                "active_camera_index",
                rows=min(max(len(settings.cameras), 2), 6),
            )

        # 2. Main Parameters
        col = layout.column(align=True)
        col.prop(settings, 'states', slider=True)

        # 3. Advanced Parameters Subpanel
        adv_box = layout.box()
        adv_box.prop(settings, 'show_advanced', toggle=True, icon='PREFERENCES')
        if settings.show_advanced:
            adv_col = adv_box.column(align=True)
            adv_col.prop(settings, 'floor', slider=True)
            adv_col.prop(settings, 'falloff', slider=True)
            adv_col.separator()
            adv_col.label(text="Resolution & Threshold (alters scores):", icon='ERROR')
            adv_col.prop(settings, 'cube_res')
            adv_col.prop(settings, 'min_px_threshold')

        layout.separator()

        # 4. Update Visibility Action Button
        can_run = bpy.data.is_saved and bool(bpy.data.filepath) and any(item.include for item in settings.cameras)
        btn_col = layout.column(align=True)
        if not bpy.data.is_saved or not bpy.data.filepath:
            btn_col.enabled = False
            btn_col.operator(FSS_OT_UpdateVisibility.bl_idname, text="Update Visibility", icon='FILE_REFRESH')
            layout.label(text="Save .blend file first to enable analysis", icon='ERROR')
        elif not any(item.include for item in settings.cameras):
            btn_col.enabled = False
            btn_col.operator(FSS_OT_UpdateVisibility.bl_idname, text="Update Visibility", icon='FILE_REFRESH')
            layout.label(text="Include at least one camera above", icon='INFO')
        else:
            btn_col.operator(FSS_OT_UpdateVisibility.bl_idname, text="Update Visibility", icon='FILE_REFRESH')

        layout.separator()

        # 5. Visibility Report Section
        rep_box = layout.box()
        rep_box.label(text="Visibility Status:", icon='TEXT')

        if not bpy.data.filepath:
            rep_box.label(text="File not saved yet.", icon='INFO')
            return

        vis_path = Path(bpy.data.filepath).with_suffix('.visibility')
        if not vis_path.exists():
            rep_box.label(text="No .visibility file found beside .blend.", icon='INFO')
            rep_box.label(text="Click 'Update Visibility' to create it.")
            return

        try:
            meta, _, stale_meshes = visibility_core.load_visibility_file(vis_path, scene_meshes=bpy.data.meshes)
        except Exception as e:
            rep_box.label(text=f"Error reading .visibility: {e}", icon='ERROR')
            return

        # Display file summary
        rep_box.label(text=f"File: {meta.get('timestamp', 'Unknown')}", icon='TIME')
        views = meta.get('views', [])
        cams_used = sorted({v['camera'] for v in views})
        rep_box.label(text=f"Cameras: {', '.join(cams_used)} ({len(views)} views)")

        # Settings mismatch check
        saved_settings = meta.get('settings', {})
        if saved_settings:
            diff = False
            if saved_settings.get('states') != settings.states:
                diff = True
            elif abs(saved_settings.get('floor', 0.2) - settings.floor) > 1e-4:
                diff = True
            elif saved_settings.get('cube_res', 1024) != settings.cube_res:
                diff = True
            if diff:
                rep_box.label(text="File was made with different settings", icon='QUESTION')

        # Never-seen counts & button
        nv_objs = meta.get('never_seen_objects_count', 0)
        nv_isls = meta.get('never_seen_islands_count', 0)
        row = rep_box.row(align=True)
        row.label(text=f"Never Seen: {nv_objs} objs, {nv_isls} islands")
        if nv_objs > 0:
            row.operator(FSS_OT_VisibilitySelectNeverSeen.bl_idname, text="Select Never Seen", icon='RESTRICT_SELECT_OFF')

        # Undetermined counts
        ud_objs = meta.get('undetermined_objects_count', 0)
        ud_faces = meta.get('total_undetermined_faces', 0)
        rep_box.label(text=f"Undetermined: {ud_objs} objs ({ud_faces} faces)")

        # Staleness detection & button
        if stale_meshes:
            stale_row = rep_box.row(align=True)
            stale_row.label(text=f"Stale: {len(stale_meshes)} mesh(es) changed", icon='ERROR')
            stale_row.operator(FSS_OT_VisibilitySelectStale.bl_idname, text="Select Stale", icon='RESTRICT_SELECT_OFF')
            rep_box.label(text="Mesh geometry changed - update visibility", icon='INFO')
        else:
            rep_box.label(text="All meshes up to date", icon='CHECKMARK')


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

CLASSES = (
    FSS_VisibilityCameraItem,
    FSS_VisibilitySettings,
    FSS_OT_UpdateVisibility,
    FSS_OT_VisibilitySelectNeverSeen,
    FSS_OT_VisibilitySelectStale,
    FSS_UL_VisibilityCameraList,
    FSS_PT_Visibility,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.fss_visibility = PointerProperty(type=FSS_VisibilitySettings)


def unregister():
    if hasattr(bpy.types.Scene, 'fss_visibility'):
        delattr(bpy.types.Scene, 'fss_visibility')
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
