"""Script runned by subprocess during background export.
"""
import bpy
import traceback
import os
import sys
import importlib


 


def subprocess_export(
    scene:str,
    export_mode:str,
    additionnal_exporter_addons: dict[str, str|None],
    profiling: bool = False,
    debug: bool = False,
):
    try:
        # gltf hooks are not loaded if addon is not mark as enabled.
        bpy.ops.preferences.addon_enable(module='io_scene_gltf2_msfs_fss')
        # Open scene after enabling addon
        bpy.ops.wm.open_mainfile(filepath=scene)
        
        

        # Enable other external addons
        for mod_name, mod_dir in additionnal_exporter_addons.items():
            if mod_dir:
                # Add to the user script directory so that GLTF hooks can be found by the built-in GLTF exporter 
                if mod_dir not in sys.path:
                    sys.path.append(mod_dir)   
            try:
                module = importlib.import_module(mod_name)
                if hasattr(module, "register"):
                    module.register()
            except Exception as e :
                print(f"Error while loading module {mod_name}")
                exc = traceback.format_exc()
                print(exc)
        if debug:
            bpy.ops.preferences.addon_enable(module="debugpy_launcher")
            bpy.ops.debug.start_debugpy(wait_for_client=True)
            print("Waiting for attach")

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