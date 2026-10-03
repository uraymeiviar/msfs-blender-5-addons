"""Script runned by subprocess during background export.
"""
import bpy
import traceback
import os
import sys


def _set_user_scripts_dirs(user_script_dir: str):
    if not bpy.app.version >= (3, 6, 0):
        print("Additionnal user script directories are not supported on version < 3.6.0")
        return

    entry = bpy.context.preferences.filepaths.script_directories.new()
    entry.directory = user_script_dir
 


def subprocess_export(
    export_mode:str,
    additionnal_exporter_addons: dict[str, str|None],
    profiling: bool = False,
    debug: bool = False,
):
    try:
        if debug:
            bpy.ops.preferences.addon_enable(module="debugpy_launcher")
            bpy.ops.debug.start_debugpy(wait_for_client=True)
            print("Waiting for attach")

        # Addon is already loaded with --addons arg, but its not marked as enabled...
        # gltf hooks are not loaded if addon is not mark as enabled.
        bpy.ops.preferences.addon_enable(module="io_scene_gltf2_msfs_fss")
        # Enable other external addons
        for mod_name, mod_dir in additionnal_exporter_addons.items():
            if mod_dir:
                # Add to the user script directory so that GLTF hooks can be found by the built-in GLTF exporter 
                _set_user_scripts_dirs(mod_dir) 
                sys.path.append(mod_dir)   
            try:
                bpy.ops.preferences.addon_enable(module=mod_name)
            except:
                print(f"Error while loading module {mod_name}")
                exc = traceback.format_exc()
                print(exc)

        bpy.ops.msfs2024.multi_export_gltf(
            export_mode=export_mode,
            called_in_subprocess=True,
            profiling=profiling,
        )
    except:
        exc = traceback.format_exc()
        print(exc)
    finally:
        os._exit(1)  # force exit for old blender version