import bpy

from bpy.app.handlers import persistent

from lod_tools_msfs_2024 import lod_camera, prefs, lod_viewer, debug_draw, active_lod_viewer


active_object_callback = object()

def on_active_changed(*args):
    active_object = bpy.context.view_layer.objects.active
    active_lod_viewer.on_active_changed(active_object)
    debug_draw.on_active_changed(active_object)

def subscribe_active_object():
    # Active object callback
    # Automatically cleared on new scene loading
    bpy.msgbus.subscribe_rna(
            key=(bpy.types.LayerObjects, "active"),
            owner=active_object_callback,
            args=(),
            notify=on_active_changed,
    )

@persistent
def load_post_handler(filepath: str = ""):

    lod_camera.cancel_lod_camera()

    # Make sure debug are visible if enabled in prefs
    addon_prefs = prefs.get_addon_prefs()
    debug_settings = addon_prefs.debug_settings
    if debug_settings:
        debug_settings.update_all(bpy.context)
    
    subscribe_active_object()

    active_lod_viewer.ActiveLODViewer.reset()


def register():
    if load_post_handler not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(load_post_handler)
    subscribe_active_object()

def unregister():
    if load_post_handler in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(load_post_handler)

    bpy.msgbus.clear_by_owner(active_object_callback)
