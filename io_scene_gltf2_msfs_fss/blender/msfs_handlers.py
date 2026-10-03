import os

import bpy

from bpy.app.handlers import persistent

from _addons_common import p4
from io_scene_gltf2_msfs_fss import get_addon_prefs

from io_scene_gltf2_msfs_fss.blender.utils import  msfs_mesh_utils
from io_scene_gltf2_msfs_fss.blender import scene_loading

from io_scene_gltf2_msfs_fss.io.exp import lod_groups as exp_lod_groups
from io_scene_gltf2_msfs_fss.io.exp import presets as exp_presets


from ..io.com import msfs_path_utils

HANDLER_DISABLED_ENV_VAR = "MSFS_HANDLERS_DISABLED"

# region Handlers
known_mesh_names = set()
@persistent
def new_object_handler(scene: bpy.types.Scene, depsgraph: bpy.types.Depsgraph):
    """
    Add a default vertex color on new created meshes or converted object (curve to mesh for example). 

    When there is no color attribute, shader vertex color node outputs
    a black color. Since there is no way to detect the presence of a color attribute 
    in shaders, we assign a default white color every time a mesh is created.

    Be carefull, this function is launched on depspgraph update, 
    it must be fast.
    """
    # Store obj and it's current type in a tuple
    global known_mesh_names
    current_mesh_names = set(bpy.data.meshes.keys())
    new_mesh_names = current_mesh_names - known_mesh_names
    known_mesh_names = current_mesh_names
    if not new_mesh_names:
        return

    # Unified add-on: MSFS 2020 assets are exported with the active color attribute (FSS pipeline), so an
    # added default color would add COLOR_0 to every primitive. Meshes are shared between scenes.
    from io_scene_gltf2_msfs_fss import msfs2020_target
    if any(msfs2020_target.is_msfs2020_target(s) for s in bpy.data.scenes):
        return

    for name in new_mesh_names:
        mesh = bpy.data.meshes.get(name)
        if mesh:
            msfs_mesh_utils.add_default_vcolor(mesh)

converting_old_gizmo = False
if bpy.app.version >= (4,5,0):

    @persistent  
    def blend_import_post_handler(blend_import_context:bpy.types.BlendImportContext):
        """Replace old gizmo after scene append.

        Unified add-on: gizmo replacement disabled (legacy gizmo empties are the MSFS 2020 export
        representation of collisions; converting them is an explicit step). Appended materials authored
        with the MSFS 2020 add-on are migrated to MSFS 2024 meaning.
        """
        from io_scene_gltf2_msfs_fss import migration
        migration.migrate_materials(bpy.context.scene)

# scene_opened_for_edit marks scenes that should trigger a Perforce edit on save.
#
# A scene is marked as opened_for_edit when:
# - the user creates a new scene from scratch
# - the user creates a new file via "Save As"
#
# For new scenes, p4.p4_edit is triggered on the first save.
# For "Save As", the first save creates the file, and p4.p4_edit is triggered on the next save.

scene_opened_for_edit = "" 

@persistent
def load_post_handler(filepath:str):
    global scene_opened_for_edit
    if bpy.app.version < (3,6,0):
        filepath = bpy.path.abspath(bpy.data.filepath)
    scene_opened_for_edit = filepath

    scene_loading.prepare_scenes()

new_scene = False

@persistent
def on_save_pre(filepath:str):
    """
    Convert paths to be relative.
    """
    global scene_opened_for_edit
    global new_scene
    # We can't set relative path if scene is not saved
    # So return here in order to save again using save_post handler

    if not bpy.data.is_saved :
        # No opened scene file, and we are trying to save for the first time
        new_scene = True
        return

    for scene in bpy.data.scenes:
        for lod_group in exp_lod_groups.get_scene_lod_groups(scene):
            lod_group["folder_path"] = msfs_path_utils.get_relative_path_to_scene(
                lod_group.folder_path
            )

        for preset in exp_presets.get_scene_exporter_presets(scene):
            preset["folder_path"] = msfs_path_utils.get_relative_path_to_scene(
                preset.folder_path
            )

        for preset_group in exp_presets.get_scene_exporter_preset_groups(scene):
            preset_group["folder_path"] = msfs_path_utils.get_relative_path_to_scene(
                preset_group.folder_path
            )

    # Make other paths relative (image, scene link etc)
    addon_prefs = get_addon_prefs()
    if not addon_prefs:
        print("[MSFS2024][SAVE][ERROR] Addon prefs not found!")
    if addon_prefs and addon_prefs.make_relative_on_save:
        bpy.ops.file.make_paths_relative()

    new_scene = False

    if filepath and scene_opened_for_edit == filepath:
        if p4.use_p4():
            p4_output = p4.P4LogOutput()
            if not p4.p4_edit(filepath, p4_output=p4_output):
                print("Blender scene p4 edit failed:\n")
                print(p4_output)

@persistent
def on_save_post(filepath:str):
    """
    Save new scene again to convert paths to relative.
    """
    global new_scene
    global scene_opened_for_edit


    scene_opened_for_edit = filepath
    if not new_scene:
        return
    try:
        bpy.ops.wm.save_mainfile()

    except:
        pass
# endregion

# region Handlers Activation

class HandlersDisabled:
    def __enter__(self):
        unregister()

    def __exit__(self, exc_type, exc_val, exc_tb):
        register()
        
def enable_default_vertex_color_handlers():
    if new_object_handler not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(new_object_handler)
    if new_object_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(new_object_handler)

def disable_default_vertex_color_handlers():
    if new_object_handler in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(new_object_handler)
    if new_object_handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(new_object_handler)

def enable_loading_saving_handlers():
    if on_save_pre not in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.append(on_save_pre)
    if on_save_post not in bpy.app.handlers.save_post:
        bpy.app.handlers.save_post.append(on_save_post)
    
    if bpy.app.version >= (4,5,0):
        if blend_import_post_handler not in bpy.app.handlers.blend_import_post:
            bpy.app.handlers.blend_import_post.append(blend_import_post_handler)
    if load_post_handler not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(load_post_handler)

def disable_loading_saving_handlers():
    if on_save_pre in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.remove(on_save_pre)
    if on_save_post in bpy.app.handlers.save_post:
        bpy.app.handlers.save_post.remove(on_save_post)

    if bpy.app.version >= (4,5,0):
        if blend_import_post_handler in bpy.app.handlers.blend_import_post:
            bpy.app.handlers.blend_import_post.remove(blend_import_post_handler)
    if load_post_handler in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(load_post_handler)


# endregion

def register():
    if os.environ.get(HANDLER_DISABLED_ENV_VAR, None):
        # Disable handlers if addon is loaded in subprocess
        return
    enable_default_vertex_color_handlers()
    enable_loading_saving_handlers()


def unregister():
    disable_default_vertex_color_handlers()
    disable_loading_saving_handlers()


    
