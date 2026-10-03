import bpy

def draw_progress_bar(context: bpy.types.Context, layout: bpy.types.UILayout):
    text = context.window_manager.msfs_progress_bar_text
    row = layout.row()
    if bpy.app.version < (4, 0, 0):
        # Use a slider instead of a progress bar for blender 3.3 and 3.6 compatibility
        row.enabled = False
        row.prop(context.window_manager, "msfs_progress_bar", text=text, slider=True)
    else:
        row.progress(text=text, factor=context.window_manager.msfs_progress_bar / 100)


def redraw_view3d(context: bpy.types.Context):
    window = getattr(context, "window", None)
    if not window:
        return
    areas = getattr(window.screen, "areas", None)
    if not areas:
        return
    for area in areas:
        if area.type == "VIEW_3D":
            area.tag_redraw()

def _update(self, context):
    redraw_view3d(context)


def register():

    # Important to register these props in window manager so it's not affected by undo/redo 
    bpy.types.WindowManager.msfs_progress_bar = bpy.props.FloatProperty( # type: ignore
        default=-1,
        subtype="PERCENTAGE",
        precision=1,
        min=-1,
        max=100,
        update=_update
    )

    bpy.types.WindowManager.msfs_progress_bar_text = bpy.props.StringProperty( # type: ignore
        default="",
        update=_update
    )
def unregister():
    try:
        del bpy.types.WindowManager.msfs_progress_bar # type: ignore
        del bpy.types.WindowManager.msfs_progress_bar_text # type: ignore
    except:
        pass
