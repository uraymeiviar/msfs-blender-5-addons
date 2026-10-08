from math import floor

import bpy
import blf
from bpy.types import SpaceView3D

from bpy_extras.view3d_utils import location_3d_to_region_2d


from lod_tools_msfs_2024 import (
    data_properties,
    lod_camera,
    lod_viewer_collections,
    lod_viewer_outputs,
    data_utils,
    lod_viewer,
    active_lod_viewer
)
from lod_tools_msfs_2024.constants import IS_BLENDER_4_2_OR_SUP
debug_draw_handle = None

def _text_dimensions(text, size: int, font_id: int = 0) -> tuple[float, float]:
    blf.size(font_id, size)
    return blf.dimensions(font_id, text)

# Region Statics
# Outline not supported in 3.6 and inferior
SHADOW_LEVEL = 6 if IS_BLENDER_4_2_OR_SUP else 0
WHITE_COLOR = (1, 1, 1)
LOD_DEBUG_COLORS_COUNT = 100
LOD_DEBUG_COLORS = []

# LOD Camera Text
FONT_SIZE = 16
LOD_CAMERA_TEXT = "LOD Camera Active"
CAMERA_TEXT_WIDTH, CAMERA_TEXT_HEIGHT = blf.dimensions(0, LOD_CAMERA_TEXT)
# LOD Stats table
HORIZONTAL_LINE_WIDTH = _text_dimensions("_", FONT_SIZE)[0]
VERTICAL_LINE_WIDTH = _text_dimensions("|", FONT_SIZE)[0]
TABLE_WIDTH_PADDING = 5
TABLE_HEIGHT_PADDING = 5
TABLE_GREY_COLOR = (0.8, 0.8, 0.8)
TABLE_ACTIVE_COLOR = (0.95, 0.49, 0.05)
TABLE_ROW_HEIGHT = _text_dimensions("|", FONT_SIZE)[1]
# Endregion


class LODEntriesTableCache:
    ready_to_draw: bool = False
    table_title: str = ""
    lod_entries_table: list[tuple[str, ...]] | None = None
    lod_entries_count: int = 0
    max_column_widths: list[float] | None = None
    table_width: float | None = None
    horizontal_line: str = ""
    draw_pos: tuple[float, float] = (0, 0)

    @classmethod
    def reset(cls):
        cls.ready_to_draw = False
        cls.table_title = ""
        cls.lod_entries_table = None
        cls.lod_entries_count = 0
        cls.max_column_widths = None
        cls.table_width = None
        cls.horizontal_line = ""
        cls.draw_pos = (0,0)

def get_lod_entries_table(
    lod_entries: list[data_properties.LODStats],
) -> list[tuple[str, ...]]:
    table: list[tuple[str, ...]] = [("LODS", "Verts", "User MinSize", "Engine MinSize")]

    def _get_entry_row(entry: data_properties.LODStats) -> tuple[str, ...]:
        return (
            f"LOD{entry.index}",
            f"{entry.vertex_count}",
            f"{entry.min_size * 100:.3f}",
            f"{entry.estimated_min_size* 100:.3f}",
        )

    for entry in lod_entries:
        table.append(_get_entry_row(entry))

    return table


def get_column_width_infos(table: list[tuple[str, ...]]) -> tuple[list[float], float]:
    """Get list of width for each column.
    and total column width
    """
    column_count = len(table[0])
    max_column_width: list[float] = [1] * column_count
    for row in table:
        for i, col in enumerate(row):
            max_column_width[i] = max(max_column_width[i], _text_dimensions(col, FONT_SIZE)[0])

    table_width = sum(max_column_width) + (
        column_count * ((TABLE_WIDTH_PADDING * 4) + VERTICAL_LINE_WIDTH)
    )
    return max_column_width, table_width

def update_lod_entry_cache(obj: bpy.types.Object):
    lod_entries = data_properties.get_lod_stats_entries(obj)
    if not lod_entries:
        LODEntriesTableCache.reset()
        return

    LODEntriesTableCache.table_title = f"Stats - {obj.name} : "
    LODEntriesTableCache.lod_entries_table = get_lod_entries_table(lod_entries)
    LODEntriesTableCache.lod_entries_count = len(LODEntriesTableCache.lod_entries_table)
    LODEntriesTableCache.max_column_widths, LODEntriesTableCache.table_width = get_column_width_infos(LODEntriesTableCache.lod_entries_table)
    LODEntriesTableCache.ready_to_draw = True
    LODEntriesTableCache.horizontal_line = "_" * int(
            LODEntriesTableCache.table_width / HORIZONTAL_LINE_WIDTH
        )
    LODEntriesTableCache.draw_pos = (
        15,
        LODEntriesTableCache.lod_entries_count
        * (TABLE_ROW_HEIGHT + TABLE_HEIGHT_PADDING)
    )

def on_active_changed(active_object: bpy.types.Object | None):
    if not debug_draw_handle:
        return
    if not active_object:
        return
    
    if not data_utils.data_is_valid(active_object):
        return
    
    if not active_object.select_get():
        LODEntriesTableCache.reset()
        return
    
    if not active_object == active_lod_viewer.ActiveLODViewer.object:
        return

    update_lod_entry_cache(active_object)


def _clamp(n, min, max):
    if n < min:
        return min
    elif n > max:
        return max
    else:
        return n

def hsv_to_rgb( h, s, v ) -> tuple[float, float, float]:
    if s:
        if h == 1.0: 
            h = 0.0
        if h == 6:
            h = 0

        i = int(floor(h))
        f = h - i

        w = v * (1.0 - s)
        q = v * (1.0 - s * f)
        t = v * (1.0 - s * (1.0 - f))

        if i==0: 
            return (v, t, w)
        if i==1: 
            return (q, v, w)
        if i==2: 
            return (w, v, t)
        if i==3: 
            return (w, q, v)
        if i==4: 
            return (t, w, v)
        if i==5: 
            return (v, w, q)

    return (v, v, v)


def get_debug_string(
    obj: bpy.types.Object,
    outputs: lod_viewer_outputs.LODViewerOutputs,
    name: bool = False,
    lod_index: bool = False,
    screen_size: bool = False,
    min_size: bool = False,
    distance: bool = False,
    vertex_count: bool = False
) -> str:

    parts = []
    if name:
        parts.append(obj.name)
    if lod_index:
        parts.append( f" Lod [{outputs.current_lod_index}/{outputs.lod_count-1}] ")
    if screen_size:
        parts.append(f" Size {outputs.lod_screen_ratio:.2f}% ")
    if min_size:
        lod_stats_entry = data_properties.get_lod_stats_entry(obj, outputs.current_lod_index)
        if lod_stats_entry:
            parts.append( f" MinSize {lod_stats_entry.get_size_to_use(percentage=True):.2f}% ")
    if vertex_count:
        lod_stats_entry = data_properties.get_lod_stats_entry(obj, outputs.current_lod_index)
        if lod_stats_entry:
            parts.append( f" V {lod_stats_entry.vertex_count} ")
    if distance:
        parts.append( f" Distance {outputs.distance_to_cam:.2f} m" )
    return "".join(parts)


def _get_lod_debug_color(lod_screen_ratio: float)->tuple[float, float, float]:
    var = 1 - _clamp((lod_screen_ratio / 100 * 0.5), 0, 1)
    display_hue = (1 - var * var) * 5

    color = hsv_to_rgb(display_hue, 1, 1)
    return color


def get_debug_color(outputs: lod_viewer_outputs.LODViewerOutputs)->tuple[float, float, float]:
    i = max(0, min(LOD_DEBUG_COLORS_COUNT, round(outputs.lod_screen_ratio)))
    return LOD_DEBUG_COLORS[i]

def draw_active_lod_stats(
    outputs: lod_viewer_outputs.LODViewerOutputs,
):
    if not LODEntriesTableCache.ready_to_draw:
        return
    blf.color(0, *TABLE_GREY_COLOR, 1)

    x, y = LODEntriesTableCache.draw_pos

    blf.position(0, x, y, 0)
    blf.draw(0, LODEntriesTableCache.table_title)

    active_index = outputs.current_lod_index
    active_index += 1  # Ignore table title row

    for i, row in enumerate(LODEntriesTableCache.lod_entries_table):
        y -= TABLE_ROW_HEIGHT
        _x = x
        if i == active_index:
            # Limit blf.color call, they are expensive
            blf.color(0, *TABLE_ACTIVE_COLOR, 1)
        for j, col in enumerate(row):
            _x += TABLE_WIDTH_PADDING
            blf.position(0, _x, y, 0)

            blf.draw(
                0,
                col,
            )
            _x += LODEntriesTableCache.max_column_widths[j]
            _x += VERTICAL_LINE_WIDTH
            blf.position(0, _x, y, 0)
            blf.draw(
                0,
                "|",
            )
            _x += TABLE_WIDTH_PADDING

        if i == active_index:
            blf.color(0, *TABLE_GREY_COLOR, 1)

        if i == 0:
            # Top horizontal line
            blf.position(0, x + TABLE_WIDTH_PADDING, y - TABLE_HEIGHT_PADDING, 0)
            blf.draw(
                0,
                LODEntriesTableCache.horizontal_line,
            )
            y -= TABLE_HEIGHT_PADDING
# region Draw vars


def draw(
    active_viewer_stats: bool = False,
    name: bool = False,
    lod_index: bool = False,
    screen_size: bool = False,
    min_size: bool = False,
    distance: bool = False,
    vertex_count: bool = False,
):
    context = bpy.context
    lod_viewer_collection = lod_viewer_collections.get_scene_lod_viewer_collection(context.scene)
    if lod_viewer_collection is None:
        return
    depsgraph = context.evaluated_depsgraph_get()

    blf.enable(0, blf.SHADOW)
    blf.shadow(0, SHADOW_LEVEL, 0, 0, 0, 1)
    blf.size(0, FONT_SIZE)
    region = context.region

    # Draw lod camera active debug
    if lod_camera.is_lod_camera_active(context): 
        width = region.width
        height = region.height
        x = (width - CAMERA_TEXT_WIDTH) / 2
        y = height - FONT_SIZE - 70
        blf.color(0, 0, 1, 0, 1)
        blf.position(0, x, y, 0)
        blf.draw(0, LOD_CAMERA_TEXT)

    # Get active obj
    region_3d = context.space_data.region_3d
    active_outputs = None

    active_object = active_lod_viewer.ActiveLODViewer.object
    if active_object and not data_utils.data_is_valid(active_object):
        active_object = None


    # loop only on lod viewer collection objects
    for obj in lod_viewer_collection.objects:
        if (not obj.type == "MESH" or 
            not data_properties.get_lod_viewer_tag(obj) == data_properties.LODViewerTags.LOD_VIEWER or 
            not obj.visible_get() ):
            continue

        _outputs = lod_viewer_outputs.get_lod_viewer_outputs(depsgraph, obj)

        if not _outputs or _outputs.current_lod_index < 0 :
            continue
        if obj == active_object:
            active_outputs = _outputs
        text = get_debug_string(obj, _outputs, name, lod_index, screen_size, min_size, distance, vertex_count)
        color = get_debug_color(_outputs)

        world_pos = obj.location + _outputs.bpshere_location

        screen_pos = location_3d_to_region_2d(
            region,
            region_3d,
            world_pos
        )

        if screen_pos is None:
            continue

        x, y = screen_pos

        blf.color(0,*color, 1)
        blf.position(0, x, y, 0)

        blf.draw(0, text)

    if active_viewer_stats and active_outputs:
        draw_active_lod_stats(active_outputs)

    # Disable outline because it has an impact on builtin outliner text render (bug?)
    blf.disable(0, blf.SHADOW)

def enable_debug_draw(
    active_viewer_stats: bool = True,
    name: bool = False,
    lod_index: bool = False,
    screen_size: bool = False,
    min_size: bool = False,
    distance: bool = False,
    vertex_count: bool = False,
):
    args = (active_viewer_stats, name, lod_index, screen_size, min_size, distance, vertex_count)
    global debug_draw_handle
    if not True in args:
        disable_debug_draw()
        return

    disable_debug_draw()
    debug_draw_handle = SpaceView3D.draw_handler_add(
        draw,
        args,
        "WINDOW",
        "POST_PIXEL",
    )

def register():
    # Cache lod debug colors
    global LOD_DEBUG_COLORS
    LOD_DEBUG_COLORS = []
    for i in range(101):
        LOD_DEBUG_COLORS.append(_get_lod_debug_color(i))


def disable_debug_draw():

    global debug_draw_handle

    if debug_draw_handle:
        SpaceView3D.draw_handler_remove(debug_draw_handle, "WINDOW")
        debug_draw_handle = None

def unregister():
    disable_debug_draw()
