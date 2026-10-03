import os

import threading
import queue
import subprocess
import time
import secrets
from pathlib import Path
import sys

import bpy

from . import pre_export

from . import multi_export_mode
from ..com import msfs_logs
from . import subprocess_cancel
from io_scene_gltf2_msfs_fss.blender import msfs_handlers
MSFS2024_LOGGER : msfs_logs.Logger


class SubProcessReport:
    """
    Functions used to communicate from a subprocess to blender main instance.
    """

    tag_progress = "[SUBPROCESS][PROGRESS]"
    tag_progress_text = "[SUBPROCESS][PROGRESS_TEXT]"
    tag_other_logs = "[SUBPROCESS][OTHER_LOGS]"

    @staticmethod
    def report_progress(progress: int):
        print(f"\n{SubProcessReport.tag_progress} {progress}", flush=True)

    @staticmethod
    def report_progress_text(text: str = ""):
        print(f"\n{SubProcessReport.tag_progress_text} {text}", flush=True)

    @staticmethod
    def get_report_text(text: str):
        result = text.split(" ",1)
        if len(result)>1:
            return result[1]
        return ""


class MSFS2024_OT_SubProcessExport(bpy.types.Operator):
    """
    Export in another Blender process:
    Save a temp copy of blender scene in same folder.
    Open the scene in a subprocess and call multi_export_gltf operator.
    Temp copy of blender scene is deleted at the end of process. 
    """

    bl_idname = "msfs2024.subprocess_export"
    bl_label = "Export MSFS2024 GLTFs in another process"
    bl_options = {"INTERNAL"}

    export_mode: bpy.props.EnumProperty(
        items=multi_export_mode.EXPORT_MODE_ENUM_ITEMS
    )  # type: ignore

    _subprocess : None | subprocess.Popen = None
    _queue: None | queue.SimpleQueue = None

    _progress: int = -1
    _progress_text: str = "Exporting..."
    _debug: bool = False
    _profiling: bool = False
    _timer: bpy.types.Timer | None = None
    _thread_finished: bool = False
    _thread: threading.Thread | None = None

    _blend_file_path: str | None = None

    @staticmethod
    def _get_additionnal_exporter_addons(gltf2_exporter_script_dir:str) -> dict[str, str| None]:
        """Get additionnal addons that needs to be enabled during exporter.
        In order to force an addon to be enabled during export,
        dev should had a "is_gltf_exporter_addon":True in bl_info dict.

        return:
            dict containing module name and directory containing module.
        """
        enabled_addons = bpy.context.preferences.addons

        exporter_addons = {}

        for addon in enabled_addons:
            module_name = addon.module

            # The module should already be loaded if enabled
            module = sys.modules.get(module_name)
            is_gltf_export_addon = False
            if module and hasattr(module, "bl_info"):
                is_gltf_export_addon = module.bl_info.get(
                    "is_gltf_exporter_addon", False
                )

            if is_gltf_export_addon:
                addon_dir = Path(module.__file__)
                if len(addon_dir.parents) >= 2:
                    addon_dir = addon_dir.parents[1]
                else:
                    continue
                addon_dir = addon_dir.as_posix()
                if addon_dir == gltf2_exporter_script_dir:
                    # No need to include gltf2 exporter script dir
                    addon_dir = None
                exporter_addons[module_name] = addon_dir
        return exporter_addons

    @staticmethod
    def _get_user_scripts_dirs() -> list[str]:

        user_script_dirs = []
        if bpy.app.version >= (3, 6, 0):
            for entry in bpy.context.preferences.filepaths.script_directories:
                if entry.directory:
                    user_script_dirs.append(Path(entry.directory).as_posix())
        else:
            prefs = bpy.context.preferences.filepaths
            custom_dir = prefs.script_directory

            if custom_dir and os.path.isdir(custom_dir):
                user_script_dirs.append(Path(custom_dir).as_posix())

        return user_script_dirs

    def thread_target(self, scene_path: str, blender_exe_path: str, debug: bool = False):

        addon_name = "io_scene_gltf2_msfs_fss"

        _user_scripts_dirs = self._get_user_scripts_dirs()
        gltf2_exporter_script_dir = ""
        to_remove = []
        for dir in _user_scripts_dirs:
            script_path = Path(dir)
            if Path(__file__).is_relative_to(script_path):
                to_remove.append(dir)
                gltf2_exporter_script_dir = script_path.as_posix()

        for dir in to_remove:
            _user_scripts_dirs.remove(dir)

        # We can provide only one user script dir with environment var
        if gltf2_exporter_script_dir:
            env = os.environ.copy()
            env["BLENDER_USER_SCRIPTS"] = gltf2_exporter_script_dir
            # Disable handlers in subprocess for faster scene loading
            env[msfs_handlers.HANDLER_DISABLED_ENV_VAR] = "True"

        additionnal_exporter_addons = self._get_additionnal_exporter_addons(gltf2_exporter_script_dir)

        for mod_name, mod_dir in additionnal_exporter_addons.items():
            if mod_dir == gltf2_exporter_script_dir:
                additionnal_exporter_addons[mod_name] = None

        python_script = (
            "try: \n"
                "\tfrom io_scene_gltf2_msfs_fss.io.exp.subprocess_script import subprocess_export\n"
                "\tsubprocess_export("
                    f"export_mode='{self.export_mode}',"
                    f"additionnal_exporter_addons={additionnal_exporter_addons},"
                    f"profiling={self._profiling},"
                    f"debug={self._debug}"
                ")\n"
            "except:\n"
                "\texc = traceback.format_exc()\n"
                "\tprint(exc)\n"
            "finally:\n"
                "\tos._exit(1)\n" # force exit for old blender version
        )
        self._queue.put((SubProcessReport.tag_progress,0))
        # Start a new blender process with only addon io_scene_gltf2_msfs_fss enabled
        args = [
                blender_exe_path,
                scene_path,
                "--background",
                "--factory-startup",
                "--addons", addon_name,
                "--disable-autoexec",
                "-noaudio",
                "--python-expr",python_script,        
            ]
        if bpy.app.version >= (4, 2, 0):
            args.append("--offline-mode")
        if debug:
            args.append("--debug")
        self._subprocess = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env
        )

        logs = []
        try:
            # Read output from subprocess
            for out in iter(self._subprocess.stdout.readline, ''):
                if out.startswith(SubProcessReport.tag_progress):

                    progress = SubProcessReport.get_report_text(out)
                    self._queue.put((SubProcessReport.tag_progress,int(float(progress))))
                elif out.startswith(SubProcessReport.tag_progress_text):
                    progress_text = SubProcessReport.get_report_text(out)
                    self._queue.put((SubProcessReport.tag_progress_text,progress_text))
                elif out.strip():
                    logs.append(out)

            self._queue.put((SubProcessReport.tag_other_logs,logs))
            # Make sure progress is 100%
            self._queue.put((SubProcessReport.tag_progress,100))
        except:
            pass
        finally:
            self._thread_finished = True
            self._subprocess.stdout.close()  
            self._subprocess.kill()
            self._subprocess = None

    def request_cancel(self, context: bpy.types.Context):
        if self._subprocess:
            subprocess_cancel.send_cancel_request(self._subprocess)

    # Event handler
    def modal(self, context: bpy.types.Context, event: bpy.types.Event):

        if not event.type == "TIMER":
            return {"PASS_THROUGH"}

        global MSFS2024_LOGGER
        # Safely get results from thread queue
        while True:
            try:
                msg = self._queue.get_nowait()
            except queue.Empty:
                break

            tag = None
            value = None
            if isinstance(msg, tuple):  # (progress, text)
                tag, value = msg
            if tag == SubProcessReport.tag_progress_text :
                self._progress_text = value
            elif tag == SubProcessReport.tag_progress:
                self._progress = value 
            elif tag == SubProcessReport.tag_other_logs:
                MSFS2024_LOGGER.logs_from_strings(value)
                for _ in value:
                    print(_, flush=True)

        # Only set when changed in order to prevent ui stuttering
        if bpy.context.window_manager.msfs_progress_bar_text != self._progress_text:
            bpy.context.window_manager.msfs_progress_bar_text = self._progress_text
        if bpy.context.window_manager.msfs_progress_bar != self._progress:
            bpy.context.window_manager.msfs_progress_bar = self._progress

        # Check if user requested export cancel
        if context.window_manager.cancel_export_requested:
            self.request_cancel(context)
        # check if thread is alive or if _progress == 100, just to be sure
        # on blender 3.6 and inferior thread is always alive.. even when operation is done
        if not self._thread.is_alive() or self._thread_finished:
            self.stop(context)

            msfs_logs.process_logger_report(self, MSFS2024_LOGGER)
            self._set_msfs_subprocess_exporting(False)
            context.window_manager.cancel_export_requested = False

            return {"FINISHED"}

        return {"PASS_THROUGH"}

    def create_blender_file_copy(self, context: bpy.types.Context) -> None | str:
        """Save a temporary copy of the blend file and store the path.
        Make sure the path doesn't exist first.
        All Export will be done using this copy so the user can continue working in this session.
        """

        current_scene = bpy.path.abspath(bpy.data.filepath)
        if not current_scene:
            self.report({"ERROR"}, "Save scene before export")
            return None
        blend_name = secrets.token_hex(6)
        directory = os.path.dirname(current_scene)
        blend_file = os.path.join(directory, blend_name)
        blend_file += ".blend"

        scene_preview = context.preferences.filepaths.file_preview_type

        while os.path.exists(blend_file):
            blend_name = secrets.token_hex(6)
            blend_file = os.path.join(directory, blend_name)
            blend_file += ".blend"

        print(f"Create blend file copy {blend_file}")
        failed = False

        # Disable file preview for faster save
        # File Preview enabled do a render, which can take some time when
        # viewport is in material or render mode
        context.preferences.filepaths.file_preview_type = "NONE"

        with msfs_handlers.HandlersDisabled():
            # Prevent temp blender file to be processed by save handlers
            try:
                bpy.ops.wm.save_as_mainfile(
                    filepath=blend_file, copy=True, compress=False, relative_remap=False
                )
                if not os.path.exists(blend_file):
                    self.report({"ERROR"}, "Blend file copy failed")
                    failed = True

            except RuntimeError:

                self.report({"ERROR"}, "Blend file copy failed")
                failed = True

        # Restore original save settings
        context.preferences.filepaths.file_preview_type = scene_preview

        if failed:
            return None
        return blend_file

    def _set_msfs_subprocess_exporting(self, state: bool):
        bpy.context.window_manager.msfs_subprocess_exporting = state

    def execute(self, context: bpy.types.Context):

        self._start_time = time.perf_counter()

        context.window_manager.cancel_export_requested = False

        global MSFS2024_LOGGER
        MSFS2024_LOGGER = msfs_logs.get_logger()
        MSFS2024_LOGGER.clear_logs()
        export_mode = multi_export_mode.ExportMode.from_identifier(self.export_mode)
        if not export_mode:
            return {"CANCELLED"}
        if not pre_export.pre_export_check(export_mode, self):
            return {"CANCELLED"}

        self._blend_file_path = self.create_blender_file_copy(context)
        if not self._blend_file_path:
            return {"CANCELLED"}

        if self._progress != -1:
            self.report({"INFO"}, "Export already in progress!")
            return {"CANCELLED"}

        context.window_manager.msfs_progress_bar = 0
        context.window_manager.msfs_progress_bar_text = "Starting Export..."

        self._progress = 0

        # Create a thread which will launch a background instance of blender running a script that does all the work.
        self._queue = queue.SimpleQueue()
        blend_exec = bpy.path.abspath(bpy.app.binary_path)
        self._thread = threading.Thread(
            target=self.thread_target, 
            args=(self._blend_file_path, blend_exec, self._debug), 
            daemon=True
        )

        # Periodically check if the export has finished
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.5, window=context.window)
        wm.modal_handler_add(self)
        self._set_msfs_subprocess_exporting(True)
        self._thread.start()

        return {"RUNNING_MODAL"}

    def stop(self, context: bpy.types.Context):

        if self._timer:
            wm = context.window_manager
            wm.event_timer_remove(self._timer)
            self._timer = None

        if self._blend_file_path and os.path.exists(self._blend_file_path):

            try:
                os.remove(self._blend_file_path)
            except OSError as err:
                print("Temporary file removal failed")
        try:
            if self._thread:
                # Timeout at 0 for blender 3.6 and inferior
                self._thread.join(timeout=0)
        except:
            pass

        context.window_manager.msfs_progress_bar = -1
        export_time =time.perf_counter() - self._start_time
        print(f"Entire Subprocess Export took {export_time:.3f} seconds.")

def draw_cancel_button(context: bpy.types.Context, layout: bpy.types.UILayout):
    row = layout.row(align=True)
    row.alert = True
    text = "Cancel Export"
    if context.window_manager.cancel_export_requested:
        text = "Cancelling ..."
        row.enabled = False
    row.operator(MSFS2024_OT_CancelSubProcessExport.bl_idname, text=text, icon="CANCEL")


class MSFS2024_OT_CancelSubProcessExport(bpy.types.Operator):
    bl_idname = "msfs2024.cancel_subprocess_export"
    bl_label = "Cancel SubProcess export"
    bl_options = {"INTERNAL"}

    def execute(self, context: bpy.types.Context):
        context.window_manager.cancel_export_requested = True
        return {"CANCELLED"}

def is_msfs_subprocess_exporting() -> bool:
    return bpy.context.window_manager.msfs_subprocess_exporting


def register():
    bpy.types.WindowManager.msfs_subprocess_exporting = bpy.props.BoolProperty(  # type: ignore
        name="MSFS Export",
        description="Indicates whether a MSFS subprocess export is currently in progress",
        default=False,
    )

    bpy.types.WindowManager.cancel_export_requested = bpy.props.BoolProperty(  # type: ignore
        default=False, description="Export cancel flag"
    )


def unregister():
    try:
        del bpy.types.WindowManager.msfs_subprocess_exporting  # type: ignore
        del bpy.types.WindowManager.cancel_export_requested  # type: ignore
    except:
        pass
