"""FSS Blender Tools: Visibility Scoring panel (inside UV Auto Packing), settings and operators.

The artist includes probe lights from the scene's lights, sets animation steps and the island rules, runs the
analysis, and reads the report (UV journal decisions 124 to 130; earlier 80, 81, 83, 86).
"""

from pathlib import Path
import math
import bpy
from bpy.props import BoolProperty, CollectionProperty, FloatProperty, IntProperty, PointerProperty, StringProperty

from . import visibility_core


# ---------------------------------------------------------------------------
# Light List Item & Settings PropertyGroup (decision 129)
# ---------------------------------------------------------------------------

class FSS_VisibilityLightItem(bpy.types.PropertyGroup):
    """A light of the scene in the probe light list."""
    light: PointerProperty(
        name="Light",
        type=bpy.types.Object,
        poll=lambda self, obj: obj.type == 'LIGHT',
        description="Probe light object"
    )
    include: BoolProperty(name="Include", default=False,
                          description="Use this light as a probe light: the surfaces it lights count as seen, as "
                                      "bright as it makes them in the viewport (Rendered, View Transform Standard)")

    @property
    def light_name(self):
        return self.light.name if self.light else ""


class FSS_VisibilitySettings(bpy.types.PropertyGroup):
    """Scene visibility test settings."""
    lights: CollectionProperty(type=FSS_VisibilityLightItem)
    active_light_index: IntProperty(default=0)

    states: IntProperty(
        name="Animation Steps",
        default=5,
        min=2,
        max=10,
        description="Animation steps evenly spaced over each animation's length: 2 gives 0 and 100 %, 5 gives 0, 25, 50, "
                    "75 and 100 %. A face takes its brightest step. Animated probe lights move with the steps"
    )

    island_percentile: FloatProperty(
        name="Island Value",
        default=90.0, min=50.0, max=100.0, precision=0, subtype='PERCENTAGE',
        description="What an island takes from its faces: the brightness that this share of its surface (by area) stays "
                    "below. 90 % follows the island's well-lit part, so a partly shadowed island is not marked down; "
                    "50 % is the median; 100 % the brightest face. Update Visibility uses it"
    )

    step_limit: FloatProperty(
        name="Step Limit",
        default=1.5, min=1.0, max=4.0, precision=2,
        description="How much two islands that touch on the model may differ: a darker island rises to its brighter "
                    "neighbour divided by this; no island is lowered. 1 makes touching islands equal. Update "
                    "Visibility uses it"
    )

    ambient: FloatProperty(
        name="Ambient",
        default=0.1, min=0.0, max=0.5, precision=2,
        description="Light every surface gets, lit or not: the lowest visibility any island can have (0.1 keeps a "
                    "tenth of the density for what no probe light reaches). Every score is lifted by the same share "
                    "of the way to 1. Update Visibility uses it"
    )

    shadow_samples: IntProperty(
        name="Shadow Samples",
        default=4, min=1, max=16,
        description="Points spread over each light's Radius that the shadows are measured from: soft shadows, as the "
                    "viewport draws them. A light with Radius 0 uses one. Each sample is one more view"
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
        description="Display advanced parameters (shadow samples, cube resolution, thresholds)"
    )


_light_sync_pending = False
# While Update Visibility runs, its section shows this instead of the button: fraction 0 to 1, text
_progress = None
# What reaches Blender during a run: moving around the viewport and scrolling. Clicks and keys could change the scene under
# the work (an Undo would leave it holding removed data), and Esc is handled first.
EVENTS_DURING_RUN = {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE', 'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'TRACKPADPAN',
                     'TRACKPADZOOM', 'NDOF_MOTION'}
LIGHT_ICONS = {'POINT': 'LIGHT_POINT', 'SPOT': 'LIGHT_SPOT', 'AREA': 'LIGHT_AREA', 'SUN': 'LIGHT_SUN'}


def _scene_lights(scene):
    return sorted([o for o in scene.objects if o.type == 'LIGHT'], key=lambda o: o.name)


def light_list_in_sync(scene):
    """True when the light list holds exactly the scene's lights, in name order (read only)."""
    settings = getattr(scene, 'fss_visibility', None)
    if settings is None:
        return True
    return [item.light for item in settings.lights] == _scene_lights(scene)


def schedule_light_sync(scene):
    """Panels may not write to the scene while drawing; sync once, right after the draw."""
    global _light_sync_pending
    if _light_sync_pending:
        return
    _light_sync_pending = True
    name = scene.name

    def run():
        global _light_sync_pending
        _light_sync_pending = False
        target = bpy.data.scenes.get(name)
        if target is not None:
            sync_light_list(target)
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == 'VIEW_3D':
                        area.tag_redraw()
        return None

    bpy.app.timers.register(run, first_interval=0.0)


def sync_light_list(scene):
    """Follow the scene's lights (added, renamed or deleted), keeping each light's Include."""
    settings = getattr(scene, 'fss_visibility', None)
    if settings is None:
        return
    included = {item.light for item in settings.lights if item.light and item.include}
    settings.lights.clear()
    for light_obj in _scene_lights(scene):
        item = settings.lights.add()
        item.light = light_obj
        item.include = light_obj in included


def included_lights(scene):
    """The included probe lights that light anything: point, spot and area lights (a sun has no position)."""
    settings = getattr(scene, 'fss_visibility', None)
    if settings is None:
        return []
    return [item.light for item in settings.lights
            if item.include and item.light and item.light.type == 'LIGHT' and item.light.data.type != 'SUN']


def light_summary(light_obj):
    """A short line about a light for the list: type, power and cone."""
    data = light_obj.data
    text = f"{data.type.title()} {data.energy:g} W"
    if data.type == 'SPOT':
        text += f" {math.degrees(data.spot_size):.0f}°"
    return text


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

    lines.append("PROBE LIGHTS:")
    states = results.get('light_states', [])
    for entry in results.get('lights', []):
        first = states[0].get(entry['name']) if states else None
        if first is None:
            lines.append(f"  - {entry['name']:<32} lights nothing (a sun, or no power)")
            continue
        lines.append(f"  - {entry['name']:<32} {first['type'].title()} {first['power']:g} W | radius {first['radius']:.3f} m"
                     f" | reach {first['reach']:.2f} m | {entry['samples']} shadow sample(s)")
    lines.append(f"  Views: {len(results.get('views', []))} | Animation steps: "
                 f"{', '.join(str(int(round(v * 100))) + ' %' for v in sorted({v['state'] for v in results.get('views', [])}))}")
    lines.append("")

    step = results.get('step_limit_result', {})
    lines.append("ISLANDS:")
    lines.append(f"  Island value: the {results.get('island_percentile', 0.9) * 100:.0f} % brightness of its faces by area")
    lines.append(f"  Most visible island before scaling to 1.0: {results.get('scale', 0.0):.4f} "
                 f"(brightest face {results.get('brightest_face', 0.0):.4f}; 1.0 is white in the viewport)")
    lines.append(f"  Ambient {results.get('ambient', 0.1):.2f}: the lowest island value")
    lines.append(f"  Step limit {results.get('step_limit', 1.5):.2f}: {step.get('raised', 0)} island(s) raised "
                 f"({step.get('raised_area_m2', 0.0):.2f} m², at most x{step.get('largest_raising', 1.0):.3f}), "
                 "none lowered")
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

def _redraw_sidebars():
    """Only the sidebars: redrawing the viewport of a large scene after every piece would slow the work down."""
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                for region in area.regions:
                    if region.type == 'UI':
                        region.tag_redraw()


def _set_status(text):
    try:
        bpy.context.workspace.status_text_set(text)
    except AttributeError:  # no workspace (background)
        pass


def _show_progress(fraction, text):
    global _progress
    _progress = {'fraction': max(0.0, min(fraction, 1.0)), 'text': text}
    _set_status(f'FSS Visibility: {text}')
    _redraw_sidebars()


def _stop_run(op, context):
    """The end of a run, however it ended: nothing stays behind."""
    global _progress
    if op._timer:
        context.window_manager.event_timer_remove(op._timer)
        op._timer = None
    if op._analyzer:
        op._analyzer.cleanup()
        op._analyzer = None
    _progress = None
    _set_status(None)
    for area in context.screen.areas if context.screen else []:
        area.tag_redraw()


def _run_piece(op, context):
    """One timer event of a run: a small piece of work, then back to Blender, which draws and reads Esc."""
    try:
        next(op._pieces)
    except StopIteration as done:
        results = done.value
    else:
        _show_progress(op._analyzer.fraction_done(), op._analyzer.activity)
        return {'RUNNING_MODAL'}
    vis_path = visibility_core.save_visibility_file(bpy.data.filepath, results, settings=op._get_settings_dict(context))
    write_visibility_report_text(results, vis_path, results['total_time_s'])
    _stop_run(op, context)
    op.report({'INFO'}, f"Visibility updated in {results['total_time_s']:.2f}s. Saved '{vis_path.name}'. "
                        f"See '{REPORT_TEXT_NAME}'.")
    return {'FINISHED'}


class FSS_OT_UpdateVisibility(bpy.types.Operator):
    """Score the scene's visibility from the included probe lights across animation states."""
    bl_idname = 'fss.update_visibility'
    bl_label = 'Update Visibility'
    bl_description = ("Score every surface by the light the included probe lights cast on it, and write "
                      "<blend_name>.visibility beside the file")
    bl_options = {'REGISTER'}

    _timer = None
    _analyzer = None
    _pieces = None

    @classmethod
    def poll(cls, context):
        if _progress is not None or not bpy.data.is_saved or not bpy.data.filepath:
            return False
        return bool(included_lights(context.scene))

    def _get_anim_states(self, context):
        n_states = max(2, min(10, context.scene.fss_visibility.states))
        return tuple(i / (n_states - 1) for i in range(n_states))

    def _get_settings_dict(self, context):
        s = context.scene.fss_visibility
        return {
            'lights': [light.name for light in included_lights(context.scene)],
            'states': s.states,
            'island_percentile': s.island_percentile,
            'step_limit': s.step_limit,
            'ambient': s.ambient,
            'shadow_samples': s.shadow_samples,
            'cube_res': s.cube_res,
            'min_px_threshold': s.min_px_threshold,
        }

    def _make_analyzer(self, context):
        s = context.scene.fss_visibility
        return visibility_core.VisibilityAnalyzer(
            scene=context.scene,
            view_layer=context.view_layer,
            lights=[light.name for light in included_lights(context.scene)],
            anim_states=self._get_anim_states(context),
            cube_res=s.cube_res,
            min_px_threshold=s.min_px_threshold,
            blend_path=bpy.data.filepath,
            shadow_samples=s.shadow_samples,
            island_percentile=s.island_percentile / 100.0,
            step_limit=s.step_limit,
            ambient=s.ambient,
        )

    def invoke(self, context, event):
        if not self.poll(context):
            self.report({'WARNING'}, "Cannot run: .blend must be saved and at least one point, spot or area light "
                                     "included.")
            return {'CANCELLED'}
        self._analyzer = self._make_analyzer(context)

        # Modal execution in interactive Blender: the bar first, then the work, a piece per timer event
        if not bpy.app.background:
            wm = context.window_manager
            self._pieces = self._analyzer.run_pieces()
            self._timer = wm.event_timer_add(0.01, window=context.window)
            wm.modal_handler_add(self)
            _show_progress(0.0, 'Reading the scene')
            return {'RUNNING_MODAL'}

        try:
            self._analyzer.prepare()
        except Exception as e:
            self._analyzer.cleanup()
            self._analyzer = None
            self.report({'ERROR'}, f"Failed to prepare visibility analysis: {e}")
            return {'CANCELLED'}
        return self.execute(context)

    def modal(self, context, event):
        if event.type == 'ESC':
            _stop_run(self, context)
            self.report({'INFO'}, "Visibility analysis cancelled by Esc. Nothing was written.")
            return {'CANCELLED'}
        if event.type != 'TIMER':
            return {'PASS_THROUGH'} if event.type in EVENTS_DURING_RUN else {'RUNNING_MODAL'}
        try:
            return _run_piece(self, context)
        except Exception as e:
            _stop_run(self, context)
            self.report({'ERROR'}, f"Visibility analysis stopped: {e}. Nothing was written.")
            return {'CANCELLED'}

    def execute(self, context):
        if self._analyzer is None:
            if not included_lights(context.scene):
                self.report({'WARNING'}, "No point, spot or area light included.")
                return {'CANCELLED'}
            self._analyzer = self._make_analyzer(context)
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


class FSS_OT_VisibilitySelectLight(bpy.types.Operator):
    """Select a probe light in the scene."""
    bl_idname = 'fss.visibility_select_light'
    bl_label = 'Select Light'
    bl_description = "Select this light in the scene and make it active"
    bl_options = {'REGISTER', 'UNDO'}

    light_name: StringProperty(name='Light')

    def execute(self, context):
        light = bpy.data.objects.get(self.light_name)
        if light is None:
            self.report({'WARNING'}, f"Light '{self.light_name}' no longer exists.")
            return {'CANCELLED'}
        view_layer = context.view_layer
        if light.name not in view_layer.objects:
            # Turning the collection on is the artist's call: what it holds would then count in Visibility and Pack
            names = ', '.join(collection.name for collection in light.users_collection)
            self.report({'WARNING'}, f"{light.name} is in collection {names}, which is off in this view layer. "
                                     "Turn the collection on to select the light.")
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        if light.hide_get(view_layer=view_layer):
            light.hide_set(False, view_layer=view_layer)
        if not light.visible_get(view_layer=view_layer) or light.hide_select:
            self.report({'WARNING'}, f"{light.name} is hidden or not selectable: change that in the Outliner.")
            return {'CANCELLED'}
        for obj in list(view_layer.objects.selected):
            obj.select_set(False, view_layer=view_layer)
        light.select_set(True, view_layer=view_layer)
        view_layer.objects.active = light
        self.report({'INFO'}, f"Selected {light.name}.")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# UI List for Lights
# ---------------------------------------------------------------------------

class FSS_UL_VisibilityLightList(bpy.types.UIList):
    """Light item row: Include, name, select, and the light's type, power and cone."""
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        light = item.light
        name = light.name if light else "(deleted)"
        icon_name = LIGHT_ICONS.get(light.data.type, 'LIGHT') if light else 'LIGHT'
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row.prop(item, 'include', text="")
            row.label(text=name, icon=icon_name)
            if light:
                row.operator(FSS_OT_VisibilitySelectLight.bl_idname, text='', icon='RESTRICT_SELECT_OFF').light_name = name
                sub = row.row(align=True)
                sub.enabled = item.include
                sub.label(text=light_summary(light))
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text=name, icon=icon_name)


# ---------------------------------------------------------------------------
# Visibility Scoring Panel (Decision 83), a section of UV Auto Packing
# ---------------------------------------------------------------------------

class FSS_PT_Visibility(bpy.types.Panel):
    """Visibility Scoring section of UV Auto Packing in sidebar FSS MSFS Tools."""
    bl_idname = 'FSS_PT_visibility'
    bl_label = 'Visibility Scoring'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'FSS MSFS Tools'
    bl_parent_id = 'FSS_PT_uv_marks'

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # Keep the light list in sync with the scene's lights (written after the draw: panels may not write while drawing)
        if not light_list_in_sync(scene):
            schedule_light_sync(scene)
        settings = scene.fss_visibility

        layout.label(text='Whole scene', icon='SCENE_DATA')

        # 1. Probe lights
        box = layout.box()
        box.label(text="Probe Lights:", icon='OUTLINER_OB_LIGHT')
        if len(settings.lights) == 0:
            box.label(text="No lights in the scene. Add a spot or point light.", icon='INFO')
        else:
            box.template_list(
                "FSS_UL_VisibilityLightList",
                "",
                settings,
                "lights",
                settings,
                "active_light_index",
                rows=min(max(len(settings.lights), 2), 6),
            )
            if any(item.include and item.light and item.light.data.type == 'SUN' for item in settings.lights):
                box.label(text="Sun lights have no position: they do not count", icon='ERROR')
            box.label(text="Preview: Rendered, world off, white material,", icon='SHADING_RENDERED')
            box.label(text="View Transform Standard: white is 1.0")

        # 2. Main Parameters
        col = layout.column(align=True)
        col.prop(settings, 'states', slider=True)
        col.prop(settings, 'island_percentile', slider=True)
        col.prop(settings, 'step_limit', slider=True)
        col.prop(settings, 'ambient', slider=True)

        # 3. Advanced Parameters Subpanel
        adv_box = layout.box()
        adv_box.prop(settings, 'show_advanced', toggle=True, icon='PREFERENCES')
        if settings.show_advanced:
            adv_col = adv_box.column(align=True)
            adv_col.prop(settings, 'shadow_samples')
            adv_col.separator()
            adv_col.label(text="Resolution & Threshold (alters scores):", icon='ERROR')
            adv_col.prop(settings, 'cube_res')
            adv_col.prop(settings, 'min_px_threshold')

        layout.separator()

        # 4. Update Visibility Action Button, or the run in progress
        btn_col = layout.column(align=True)
        if _progress is not None:
            box = layout.box()
            box.progress(factor=_progress['fraction'], type='BAR', text=f"Update Visibility: {int(_progress['fraction'] * 100)} %")
            box.label(text=_progress['text'], icon='TIME')
            box.label(text='Esc cancels: nothing is written')
        elif not bpy.data.is_saved or not bpy.data.filepath:
            btn_col.enabled = False
            btn_col.operator(FSS_OT_UpdateVisibility.bl_idname, text="Update Visibility", icon='FILE_REFRESH')
            layout.label(text="Save .blend file first to enable analysis", icon='ERROR')
        elif not included_lights(scene):
            btn_col.enabled = False
            btn_col.operator(FSS_OT_UpdateVisibility.bl_idname, text="Update Visibility", icon='FILE_REFRESH')
            layout.label(text="Include at least one light above", icon='INFO')
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
        lights_used = [entry['name'] for entry in meta.get('lights', [])]
        rep_box.label(text=f"Lights: {', '.join(lights_used)} ({len(views)} views)")

        # Settings mismatch check
        saved_settings = meta.get('settings', {})
        if saved_settings:
            diff = False
            now = {'states': settings.states, 'cube_res': settings.cube_res,
                   'island_percentile': round(settings.island_percentile, 3), 'step_limit': round(settings.step_limit, 3),
                   'ambient': round(settings.ambient, 3),
                   'shadow_samples': settings.shadow_samples,
                   'lights': [light.name for light in included_lights(scene)]}
            saved = {key: round(value, 3) if isinstance(value, float) else value
                     for key, value in saved_settings.items() if key in now}
            diff = any(saved.get(key) != value for key, value in now.items() if key in saved)
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
        if visibility_core.is_old_visibility_file(meta):
            rep_box.label(text="Scored by an older version: not used", icon='ERROR')
            rep_box.label(text="Click 'Update Visibility' to score it again", icon='INFO')
        elif stale_meshes:
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
    FSS_VisibilityLightItem,
    FSS_VisibilitySettings,
    FSS_OT_UpdateVisibility,
    FSS_OT_VisibilitySelectNeverSeen,
    FSS_OT_VisibilitySelectStale,
    FSS_OT_VisibilitySelectLight,
    FSS_UL_VisibilityLightList,
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
