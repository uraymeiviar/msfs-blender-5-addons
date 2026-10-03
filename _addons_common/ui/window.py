import bpy

class ADDONSUTILS_OT_FloatingPanelWindow(bpy.types.Operator):
    bl_idname = "addonsutils.new_window_with_active_panel"
    bl_label = "New Window with Active Panel"
    bl_description = (
        "Duplicate the current area into a new window and display the active sidebar panel.\n"
        "This is a workaround for floating panels, which are not natively supported in Blender.\n"
        "You may need to resize the window or panel manually."
    )
    bl_options = {"INTERNAL"}

    def execute(self, context):
        if not bpy.app.version >= (4, 2, 0):
            return {"CANCELLED"}
        active_area = context.area
        if not active_area:
            self.report(type={"ERROR"}, message="No Active area found!")
            return {"CANCELLED"}

        ui_type = active_area.ui_type
        active_panel_category = get_active_panel_category(active_area)

        new_win = create_new_window()

        view_area = new_win.screen.areas[0]
        view_area.ui_type = ui_type

        set_blank_space(view_area)

        if active_panel_category:
            set_active_panel_category_delayed(active_panel_category, view_area)

        return {"FINISHED"}


def draw_new_window_ope(layout: bpy.types.UILayout):
    """Draw the operator button into panel header."""
    if not bpy.app.version >= (4, 2, 0):
        return
    layout.operator(
        ADDONSUTILS_OT_FloatingPanelWindow.bl_idname,
        text="",
        icon="TOPBAR",
        emboss=False
    )
    # Create a separator to prevent button to cover pin icon
    # when panel is pinned
    layout.separator(factor=4)


def get_active_panel_category(area: bpy.types.Area) -> None | str:
    """Only for blender version >= 4, 2, 0
    """
    active_panel_category = None
    for r in area.regions:
        if not r.type == "UI" or not hasattr(r, "active_panel_category"):
            continue

        if not r.active_panel_category or r.active_panel_category == "UNSUPPORTED":
            continue

        active_panel_category = r.active_panel_category
        break
    return active_panel_category


def set_active_panel_category(name: str, area: bpy.types.Area) -> bool:
    """Only for blender version >= 4, 2, 0
    """
    category_set = False
    if not bpy.app.version >= (4, 2, 0):
        return category_set

    for r in area.regions:
        if not r.type == "UI" or not hasattr(r, "active_panel_category"):
            continue

        if r.active_panel_category == "UNSUPPORTED":
            continue
        try:
            r.active_panel_category = name
        except:
            continue
        category_set = True
    return category_set


def set_active_panel_category_delayed(name: str, area: bpy.types.Area):
    """
    Set the active sidebar panel category after a delay.

    This is required when a new window or area is created during script
    execution, as the UI regions and space data may not be fully
    initialized yet.

    The function polls at a short interval until the area becomes
    ready and the panel category can be set successfully.

    Only for blender version >= 4, 2, 0
    
    """

    if not bpy.app.version >= (4, 2, 0):
        return

    def _timer_set_active_panel_category() -> float | None:
        category_set = set_active_panel_category(name, area)
        if not category_set:
            return 0.1  # Retry in 0.1 seconds
        return None

    bpy.app.timers.register(_timer_set_active_panel_category, first_interval=0.1)


def make_view3d_space_blank(space: bpy.types.Space):
    """Disable all overlays, and hide all object
     types in the 3D Viewport in order to create an empty view.
    """
    # Hide all object types in viewport
    space.show_object_viewport_mesh = False
    space.show_object_viewport_curve = False
    space.show_object_viewport_surf = False
    space.show_object_viewport_meta = False
    space.show_object_viewport_font = False
    space.show_object_viewport_curves = False
    space.show_object_viewport_pointcloud = False
    space.show_object_viewport_volume = False
    space.show_object_viewport_grease_pencil = False
    space.show_object_viewport_armature = False
    space.show_object_viewport_lattice = False
    space.show_object_viewport_empty = False
    space.show_object_viewport_light = False
    space.show_object_viewport_light_probe = False
    space.show_object_viewport_camera = False
    space.show_object_viewport_speaker = False

    space.shading.type = "SOLID"
    space.overlay.show_overlays = False
    space.show_gizmo = False


def create_new_window() -> bpy.types.Window:
    # Create a new preferences windows to get a small window
    # Since there is no way to set window size manually...
    bpy.ops.screen.userpref_show()
    # Newly created window is last in WM list
    win = bpy.context.window_manager.windows[-1]
    return win


def set_blank_space(
    view_area: bpy.types.Area,
) -> bpy.types.Area | None:

    space = view_area.spaces.active
    if not space:
        return

    space.show_region_toolbar = False
    space.show_region_ui = True
    space.show_region_header = False

    if view_area.ui_type == "VIEW_3D":
        make_view3d_space_blank(space)

    return view_area
