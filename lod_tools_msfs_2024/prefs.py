from __future__ import annotations

from enum import Enum

import bpy
import mathutils

from lod_tools_msfs_2024 import (
    lod_viewer_node_groups,
    debug_draw,
)

class RenderPreset(Enum):
    LOW = ("LOW", "Low", 0.25)
    MEDIUM = ("MEDIUM", "Medium", 0.5)
    HIGH = ("HIGH", "High", 1)
    ULTRA = ("ULTRA", "Ultra", 2)

    def __init__(self, identifier: str, label: str, lod_factor: float) -> None:
        self.identifier = identifier
        self.label = label
        self.lod_factor = lod_factor

    @classmethod
    def from_identifier(cls, identifier: str)->RenderPreset|None:
        for item in cls:
            if item.identifier == identifier:
                return item
        return None

class RenderSettings(bpy.types.PropertyGroup):
    def update_all(self, context: bpy.types.Context):
        self.update_render_preset(context)


    def update_render_preset(self, context: bpy.types.Context):
        render_preset = RenderPreset.from_identifier(self.render_preset)
        if not render_preset:
            return
        self.lod_factor = render_preset.lod_factor

    def update_lod_factor(self, context: bpy.types.Context):
        scene = context.scene
        if not scene:
            return 
        lod_viewer_constants_grp: bpy.types.NodeGroup | None = lod_viewer_node_groups.get_scene_lod_viewer_constants_group(scene)
        if not lod_viewer_constants_grp:
            return
        lod_viewer_node_groups.set_lod_factor(lod_viewer_constants_grp, self.lod_factor)


    lod_factor: bpy.props.FloatProperty(
        name="LOD Factor",
        description=("LOD Factor, affected by render presets\n" 
                     f"(Low:0.25, Medium:0.5, High:1, Ultra:2)"),
        min=0.01,
        max=2,
        default=1,
        update=update_lod_factor # type: ignore
    ) # type: ignore

    render_preset: bpy.props.EnumProperty(
        name="Render Preset",
        description="Render Preset",
        default = RenderPreset.HIGH.identifier,
        items = [
            (RenderPreset.LOW.identifier,
             RenderPreset.LOW.label,
             (f"LOD screen sizes are multiplied by {RenderPreset.LOW.lod_factor},\n" 
              "causing lower-detail LODs to appear much sooner."),
             "",
             0
            ),
            (RenderPreset.MEDIUM.identifier,
             RenderPreset.MEDIUM.label,
             (f"LOD screen sizes are multiplied by {RenderPreset.MEDIUM.lod_factor},\n" 
              "making lower-detail LODs appear sooner than normal ."),
             "",
             1
            ),
            (RenderPreset.HIGH.identifier,
             RenderPreset.HIGH.label,
             (f"LOD screen sizes are multiplied by {RenderPreset.HIGH.lod_factor}.\n" 
              "Uses the default LOD distances and intended visual quality.\n"
              "This is the recommended preset when authoring LODs."),
              "",
              2
            ),
            (RenderPreset.ULTRA.identifier,
             RenderPreset.ULTRA.label,
             (f"LOD screen sizes are multiplied by {RenderPreset.ULTRA.lod_factor},\n" 
              "keeping high-detail LODs visible much farther from the camera.\n" 
              "Best visual quality, highest performance cost."),
              "",
              3
            ),
        ],
        update=update_render_preset  # type: ignore
    ) # type: ignore

class LODViewerOffsetDirection(Enum):
    NONE = ("NONE", "None", None)
    FRONT = ("FRONT", "Front", mathutils.Vector((0, -1, 0)), 1)
    BACK = ("BACK", "Back", mathutils.Vector((0, 1, 0)), 1)
    TOP = ("TOP", "Top", mathutils.Vector((0, 0, 1)), 2)
    DOWN = ("DOWN", "Down", mathutils.Vector((0, 0, -1)), 2)
    RIGHT = ("RIGHT", "Right", mathutils.Vector((1, 0, 0)), 0)
    LEFT = ("LEFT", "Left", mathutils.Vector((-1, 0, 0)), 0)

    def __init__(self, identifier: str, label: str, vector: mathutils.Vector | None, axis_index: int = 0):
        self.identifier = identifier
        self.label = label
        self.vector = vector
        self.axis_index = axis_index # x,y,z index

    @classmethod
    def from_identifier(cls, identifier: str) -> LODViewerOffsetDirection | None:
        for mode in cls:
            if mode.identifier == identifier:
                return mode
        return None


class LODViewerSettings(bpy.types.PropertyGroup):
    align_lod_viewer_to_source: bpy.props.BoolProperty(
        name="Align LOD Viewer to Source",
        description=(
            "Place LOD Viewer objects at the same location as their source objects.\n"
            "When disabled, they are placed at the world origin."
        ),
        default=True,
    )  # type: ignore

    lod_viewer_offset: bpy.props.EnumProperty(
        name="Offset",
        description=(
            "Offset LOD Viewer objects in the selected direction.\n"
            "Makes both the source and LOD Viewer objects visible side by side.\n"
            "The offset equals the scene bounding box size along the chosen axis."
        ),
        default=LODViewerOffsetDirection.RIGHT.identifier,
        items=[
            (
                LODViewerOffsetDirection.NONE.identifier,
                LODViewerOffsetDirection.NONE.label,
                "",
                "",
                0,
            ),
            (
                LODViewerOffsetDirection.FRONT.identifier,
                LODViewerOffsetDirection.FRONT.label,
                "",
                "",
                1,
            ),
            (
                LODViewerOffsetDirection.BACK.identifier,
                LODViewerOffsetDirection.BACK.label,
                "",
                "",
                2,
            ),
            (
                LODViewerOffsetDirection.TOP.identifier,
                LODViewerOffsetDirection.TOP.label,
                "",
                "",
                3,
            ),
            (
                LODViewerOffsetDirection.DOWN.identifier,
                LODViewerOffsetDirection.DOWN.label,
                "",
                "",
                4,
            ),
            (
                LODViewerOffsetDirection.RIGHT.identifier,
                LODViewerOffsetDirection.RIGHT.label,
                "",
                "",
                5,
            ),
            (
                LODViewerOffsetDirection.LEFT.identifier,
                LODViewerOffsetDirection.LEFT.label,
                "",
                "",
                6,
            ),
        ],
    )  # type: ignore


class DebugSettings(bpy.types.PropertyGroup):
    def update_all(self, context: bpy.types.Context):
        self.update_display_bsphere(context)
        self.update_force_active_lod(context)
        self.update_debug_draw(context)

    def update_display_bsphere(self, context: bpy.types.Context| None = None):
        scene = context.scene
        if not scene:
            return
        lod_viewer_constants_grp: bpy.types.NodeGroup | None = lod_viewer_node_groups.get_scene_lod_viewer_constants_group(scene)
        if not lod_viewer_constants_grp:
            return
        display_bsphere = self.display_bounding_spheres
        if not self.enable_debug:
            display_bsphere = False
        lod_viewer_node_groups.set_display_bpshere(lod_viewer_constants_grp, display_bsphere)

    def update_force_active_lod(self, context: bpy.types.Context| None = None):
        scene = context.scene
        if not scene:
            return
        lod_viewer_constants_grp: bpy.types.NodeGroup | None = lod_viewer_node_groups.get_scene_lod_viewer_constants_group(scene)
        if not lod_viewer_constants_grp:
            return
        enable_force_active_lod = self.enable_force_active_lod

        lod_viewer_node_groups.set_force_active_lod(lod_viewer_constants_grp, enable_force_active_lod, self.active_lod)

    def update_debug_draw(self, context: bpy.types.Context | None = None):
        if not self.enable_debug:
            debug_draw.disable_debug_draw()
            return
        debug_draw.enable_debug_draw(
            self.active_viewer_stats,
            self.display_name,
            self.display_lod_index,
            self.display_lod_screen_size,
            self.display_lod_min_size,
            self.display_lod_distance,
            self.display_vertex_count,
        )
        if not context:
            context = bpy.context
        self.update_force_active_lod(context)

    enable_debug: bpy.props.BoolProperty(
        name="Enable Debug",
        description="Enable LOD Debug",
        default = True,
        update=update_all # type: ignore
    ) # type: ignore

    active_viewer_stats: bpy.props.BoolProperty(
        name="Active LOD Viewer Stats",
        description="Display selected LOD viewer statistics",
        default = True,
        update=update_debug_draw # type: ignore
    ) # type: ignore

    display_name: bpy.props.BoolProperty(
        name="Name",
        description="Display LOD Name",
        default = False,
        update=update_debug_draw # type: ignore
    ) # type: ignore

    display_lod_index: bpy.props.BoolProperty(
        name="LOD index",
        description="Display LOD Index",
        default = True,
        update=update_debug_draw # type: ignore
    ) # type: ignore

    display_lod_screen_size: bpy.props.BoolProperty(
        name="LOD Screen Size",
        description="Display LOD Screen Size",
        default = False,
        update=update_debug_draw # type: ignore
    ) # type: ignore

    display_lod_min_size: bpy.props.BoolProperty(
        name="LOD Minimum Size",
        description="Display LOD Minimum Size",
        default = False,
        update=update_debug_draw # type: ignore
    ) # type: ignore

    display_lod_distance: bpy.props.BoolProperty(
        name="LOD Distance",
        description="Display LOD Distance",
        default = False,
        update=update_debug_draw # type: ignore
    ) # type: ignore

    display_vertex_count: bpy.props.BoolProperty(
        name="Vertex Count",
        description="Display Vertex Count",
        default = False,
        update=update_debug_draw # type: ignore
    ) # type: ignore

    display_bounding_spheres: bpy.props.BoolProperty(
        name="Display Bounding Spheres",
        description="Display Bounding Sphere",
        default = False,
        update=update_display_bsphere # type: ignore
    ) # type: ignore

    enable_force_active_lod: bpy.props.BoolProperty(
        name="Force Active LOD",
        description="Enable force Active LOD",
        default = False,
        update=update_force_active_lod # type: ignore
    ) # type: ignore

    active_lod: bpy.props.IntProperty(
        name="Active LOD Index",
        default = 0,
        min=0,
        max=8,
        update=update_force_active_lod # type: ignore
    ) # type: ignore

class MSFS2024_LODTools_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    render_settings: bpy.props.PointerProperty(type=RenderSettings) # type: ignore
    lod_viewer_settings: bpy.props.PointerProperty(type=LODViewerSettings) # type: ignore
    debug_settings: bpy.props.PointerProperty(type=DebugSettings) # type: ignore

    @staticmethod
    def draw_render_preset(render_settings: RenderSettings, layout: bpy.types.UILayout):
        row = layout.row()
        row.label(text="Render Preset")
        row = row.row()
        row.prop(render_settings, "render_preset", text="")

    @staticmethod
    def draw_render_settings(render_settings: RenderSettings, layout: bpy.types.UILayout):
        layout.prop(render_settings, "lod_factor")

    @staticmethod
    def draw_debug_settings(debug_settings: DebugSettings, layout: bpy.types.UILayout):
  
        layout.prop(debug_settings, "enable_debug", text="Debug")
        box = layout.box()
        box.alignment ="RIGHT"
        box.enabled = debug_settings.enable_debug
        box.prop(debug_settings, "active_viewer_stats")
        box.prop(debug_settings, "display_name")
        box.prop(debug_settings, "display_lod_index")
        box.prop(debug_settings, "display_lod_screen_size")
        box.prop(debug_settings, "display_lod_min_size")
        box.prop(debug_settings, "display_lod_distance")
        box.prop(debug_settings, "display_vertex_count")
        box.prop(debug_settings, "display_bounding_spheres")

        box = layout.box()
        box.prop(debug_settings, "enable_force_active_lod")
        if debug_settings.enable_force_active_lod:
            box.prop(debug_settings, "active_lod")

def get_addon_prefs() -> None | MSFS2024_LODTools_AddonPreferences:
    addon_name = __package__
    prefs = bpy.context.preferences.addons.get(addon_name)
    if not prefs:
        return None
    else:
        return prefs.preferences