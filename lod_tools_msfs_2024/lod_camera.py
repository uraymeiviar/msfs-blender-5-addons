import uuid

import bpy
import math
import mathutils

from lod_tools_msfs_2024 import data_properties, lod_viewer_node_groups


class LODCameraVars:
    running: bool = False
    region_3d: bpy.types.RegionView3D | None = None
    ui_space: bpy.types.Space | None= None
    camera_proxy_name: str | None = None
    interval: float = 0.2
    last_matrix: type[mathutils.Matrix] | None = None
    last_fov: float | None = None


def _lod_camera_callback():
    """
    Update the LOD camera proxy transform at regular intervals.
    """
    if not LODCameraVars.running:
        cancel_lod_camera()
        return None  # stop timer

    target = bpy.data.objects.get(LODCameraVars.camera_proxy_name)
    if target is None:
        cancel_lod_camera()
        return None

    context = bpy.context
    current_matrix_world = get_viewport_matrix_world(LODCameraVars.region_3d)
    current_fov = get_viewport_vertical_fov(LODCameraVars.region_3d)
    if current_matrix_world is None:
        cancel_lod_camera()
        return None
    elif (
        LODCameraVars.last_matrix is None
        or current_matrix_world != LODCameraVars.last_matrix
    ):
        target.matrix_world = current_matrix_world
        LODCameraVars.last_matrix = current_matrix_world.copy()
    if current_fov is None:
        cancel_lod_camera()
        return None
    elif LODCameraVars.last_fov is None or current_fov != LODCameraVars.last_fov:
        grp = lod_viewer_node_groups.get_scene_lod_viewer_constants_group(context.scene)
        if grp:
            lod_viewer_node_groups.set_fov_y(grp, current_fov)
            LODCameraVars.last_fov = current_fov

    return LODCameraVars.interval


def cancel_lod_camera():
    LODCameraVars.running = False
    LODCameraVars.region_3d = None
    LODCameraVars.ui_space = None
    LODCameraVars.camera_proxy_name = None
    LODCameraVars.last_matrix = None
    LODCameraVars.last_fov = None
    try:
        bpy.app.timers.unregister(_lod_camera_callback)
    except:
        pass


def enable_lod_camera(context: bpy.types.Context, camera_proxy_name: str, state: bool):

    enable_camera_view(context, False)
    cancel_lod_camera()

    if not state:
        return

    if not bpy.data.objects.get(camera_proxy_name):
        return

    LODCameraVars.region_3d = get_region_view_3d(context)
    if not LODCameraVars.region_3d:
        return
    LODCameraVars.ui_space = context.space_data
    LODCameraVars.camera_proxy_name = camera_proxy_name

    LODCameraVars.last_matrix = None
    LODCameraVars.last_fov = None
    LODCameraVars.running = True

    bpy.app.timers.register(
        _lod_camera_callback,
        first_interval=LODCameraVars.interval,
    )


_ORTHO_FAKE_FOV = math.radians(1.0)

def get_viewport_vertical_fov(region_3d: bpy.types.RegionView3D) -> float | None:
    m = region_3d.window_matrix
    if region_3d.is_perspective:
        try:
            fov_y = 2.0 * math.atan(1.0 / m[1][1])
        except ZeroDivisionError:
            return None
        return fov_y
    else:
        # In orthographic view, fov should be 0
        # but we fake it by using a very small fov
        return _ORTHO_FAKE_FOV


def is_lod_camera_active(context: bpy.types.Context) -> bool:
    """Is lod camera being used in current viewport."""
    region_3d = get_region_view_3d(context)
    return (LODCameraVars.running and region_3d == LODCameraVars.region_3d)

def is_lod_camera_active_in_ui_space(context: bpy.types.Context) -> bool:
    """Is lod camera being used in current ui space."""
    return (LODCameraVars.running and context.space_data == LODCameraVars.ui_space)

def get_all_lod_cameras() -> list[bpy.types.Object]:
    """Get All LOD cameras used in scenes.
    """
    lod_cameras = []
    for obj in bpy.data.objects:
        if data_properties.is_lod_camera(obj):
            lod_cameras.append(obj)
    return lod_cameras

def delete_scene_lod_camera(scene: bpy.types.Scene):
    lod_camera_proxy = get_scene_lod_camera_proxy(scene)

    if lod_camera_proxy:
        bpy.data.batch_remove((lod_camera_proxy,))
    data_properties.set_scene_lod_camera(scene, None)

def get_scene_lod_camera_proxy(scene: bpy.types.Scene) -> bpy.types.Object |None:
    """
    Get Scene LOD Camera Proxy.
    """
    lod_viewer_scene_props : data_properties.LODViewerScene = data_properties.get_msfs_lod_viewer_prop(scene)
    if lod_viewer_scene_props is None:
        return None

    return lod_viewer_scene_props.lod_camera_proxy

def get_viewport_matrix_world(region_3d: bpy.types.RegionView3D ) -> mathutils.Matrix | None:
    """
    Returns the world matrix (Matrix) of the current 3D viewport or None.
    """

    if region_3d.is_perspective:
        return region_3d.view_matrix.inverted()

    # Adapt matrix distance in orthographic
    # Place the camera the distance that reproduces the current
    # ortho_height under the _ORTHO_FAKE_FOV
    m = region_3d.window_matrix
    try:
        ortho_height = 2.0 / m[1][1]
    except ZeroDivisionError:
        return None
    virtual_distance = ortho_height / (2.0 * math.tan(_ORTHO_FAKE_FOV / 2.0))

    matrix = region_3d.view_rotation.to_matrix().to_4x4()
    forward = region_3d.view_rotation @ mathutils.Vector((0.0, 0.0, -1.0))
    matrix.translation = region_3d.view_location - forward * virtual_distance

    return matrix

def get_region_view_3d(context: bpy.types.Context)->bpy.types.RegionView3D | None:
    region_3d = context.region_data
    if not region_3d:
        return None
    return region_3d


def get_context_fov_y(context: bpy.types.Context) -> float | None:
    region_3d = get_region_view_3d(context)
    if not region_3d:
        return None
    fov_y = get_viewport_vertical_fov(region_3d)
    return fov_y

def create_lod_camera_proxy():
    """Create empty object holding camera transforms.
    """
    empty_obj = bpy.data.objects.new(
            name=f".LOD_Cam_proxy_{str(uuid.uuid4())}", object_data=None
        )
    data_properties.tag_as_lod_viewer_data(empty_obj)
    return empty_obj

def init_scene_lod_camera_proxy(
    scene: bpy.types.Scene
) -> tuple[bpy.types.Object, float]:
    """Get or create scene lod camera proxy.
    Lod Camera proxy is an empty object that follow viewport 
    camera.
    """
    lod_camera_proxy = get_scene_lod_camera_proxy(scene)
    if not lod_camera_proxy:
        lod_camera_proxy = create_lod_camera_proxy()
        data_properties.set_scene_lod_camera(scene, lod_camera_proxy)

    return lod_camera_proxy


def enable_camera_view(context: bpy.types.Context, state: bool):
    """Switch between camera and perspective view.
    """
    space = context.space_data
    if not space:
        return
    if state:
        space.region_3d.view_perspective = "CAMERA"
    else:
        space.region_3d.view_perspective = "PERSP"


def toggle_lod_camera(context: bpy.types.Context):
    """Enter or Exit LOD Camera View."""

    state = is_lod_camera_active(context)

    if not context.scene:
        return
    used_lod_camera = get_scene_lod_camera_proxy(context.scene)
    if not used_lod_camera:
        return
    enable_lod_camera(context, used_lod_camera.name, not state)
