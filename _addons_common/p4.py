from typing import Iterable
import subprocess
import codecs
from dataclasses import dataclass
from pathlib import Path
import os
from contextlib import contextmanager
import tempfile

from _addons_common import file_info


@dataclass
class WorkspaceInfo:
    name: str
    root: Path

    def __hash__ (self):
        return hash(self.root)

class P4LogOutput:
    def __init__(self):
        self.logs = []

    @staticmethod
    def decode_output(output: str|bytes)->str:
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        return codecs.unicode_escape_decode(output.encode("unicode_escape"))[0]

    def add_process_result(self, process: subprocess.CompletedProcess):

        if process.stdout:
            self.logs.append(self.decode_output(process.stdout))
        if process.stderr:
            self.logs.append(self.decode_output(process.stderr))

    def add_log(self, message: str):
        self.logs.append(message)

    def __str__(self):
        return "".join(self.logs)


def is_process_success(process: subprocess.CompletedProcess ) -> bool:

    # process.stderr can be None or b"" on success
    stderr = None
    if process.stderr is not None:
        stderr = P4LogOutput.decode_output(process.stderr)

    if stderr:
        return False

    return True

def run_p4_cmd(cmd: list[str], env: dict | None = None) -> subprocess.CompletedProcess:

    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        env=env
    )


def _use_p4():
    """
    Check if p4 is available on system.
    
    Cache the result instead of running the p4 command each time.
    
    Subprocess creation is slow, and p4 can be slow to respond. 
    """
    try:
        process = run_p4_cmd(["p4", "info"])
        if is_process_success(process):
            return True
    except Exception as e:  # in case p4 is not installed

        return False

    return False

USE_P4 = _use_p4()


def get_client_workspaces()->list[WorkspaceInfo]:
    # Fork: p4 may not be installed (push_p4_session calls this after every export)
    if not USE_P4:
        return []

    cmd = ["p4", "clients", "--me"]
    process = subprocess.run(
        cmd, 
        stdout=subprocess.PIPE, 
        stderr=subprocess.PIPE,
        check=False
    )
    if not is_process_success(process):
        return []
    output = P4LogOutput.decode_output(process.stdout)
    workspaces = []
    for line in output.splitlines():
        if not line.strip():
            continue
        line = line.strip()
        infos = line.split(" ")
        if not len(infos)>=5:
            continue
        name = infos[1].strip()
        root = Path(infos[4].strip())
        workspace = WorkspaceInfo(name, root)
        workspaces.append(workspace)

    return workspaces

def get_file_workspace(filepath: str| Path, workspaces: list[WorkspaceInfo] | None = None) ->None|WorkspaceInfo:
    if workspaces is None:
        workspaces = get_client_workspaces()
    filepath = Path(filepath)
    for wp in workspaces:
        relative = filepath.is_relative_to(wp.root)
        if not relative:
            continue
        return wp
    return None

def create_p4_client_env(workspace_name:str)->dict:
    environ = os.environ.copy()
    environ["P4CLIENT"] = workspace_name
    return environ

def p4_edit(filepath: str | Path, 
            changelist_name:str="default", 
            p4_output: P4LogOutput | None = None)->bool:
    """This function can be quite slow. 
    Consider using a p4_session_edit to group your p4 commands into one.
    """
    filepath = Path(filepath).as_posix()
    file_workspace = get_file_workspace(filepath)

    environ = None
    if file_workspace:
        environ = create_p4_client_env(file_workspace.name)
    else:
        # Ignore if file is not in a workspace
        return True

    # Check if file is synced to latest revision
    check_synced = run_p4_cmd(["p4", "sync", "-n", filepath], environ)

    if check_synced.stdout: 
        if p4_output is not None:
            p4_output.add_log(f"Not synced to the latest revision!\n{filepath}")
        return False

    process = None
    # Check file status first
    fstat_process = run_p4_cmd(["p4", "fstat", filepath], environ)
    if fstat_process.stdout:
        process = run_p4_cmd(["p4", "edit", "-c", changelist_name, filepath], environ)

    else:
        # stdout is an empty string if not in depot
        process = run_p4_cmd(["p4", "add", "-c", changelist_name, filepath], environ)

    if process and not is_process_success(process):
        if p4_output is not None:
            p4_output.add_process_result(fstat_process)
        return False

    return True


def p4_add(filepath: str | Path, 
           changelist_name:str="default",
           p4_output: P4LogOutput | None = None)->bool:
    """This function can be quite slow. 
        Consider using a p4_session_edit to group your p4 commands into one.
    """
    filepath = Path(filepath).as_posix()
    file_workspace = get_file_workspace(filepath)

    environ = None
    if file_workspace:
        environ = create_p4_client_env(file_workspace.name)
    else:
        # Ignore if file is not in a workspace
        return True

    process = run_p4_cmd(["p4", "add", "-c", changelist_name, "-v", filepath], environ)
    if p4_output is not None:
        p4_output.add_process_result(process)

    if not is_process_success(process):
        return False

    return True

# region p4 session

_p4_session_cache: list[str] = []


def p4_session_edit(filepath: str | Path, remove_read_only: bool = True) -> bool:
    """Mark file to be opened for edit later when push_p4_session is launched.

    Returns:
        True if the file is not read only. True if remove_read_only is not enabled.
    """
    filepath = Path(filepath)
    remove_read_only_result = True

    if remove_read_only and filepath.exists():
        remove_read_only_result = file_info.set_read_only(filepath, False)

    if not remove_read_only_result:
        return False
    filepath = filepath.as_posix()

    global _p4_session_cache
    _p4_session_cache.append(filepath)
    return True


def reset_p4_session():
    global _p4_session_cache
    _p4_session_cache = []


def __format_path(filepath: str) -> str:
    return Path(filepath).resolve().as_posix()

@contextmanager
def filepaths_to_temp_file(filepaths: Iterable[str]):
    """
    Create a temporary text file containing the given filepaths.

    Avoids Windows' command-line length limitation when passing a
    large number of args to a subprocess.
    """
     
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".txt",
        encoding="utf-8",
        delete=False,
    ) as f:
        f.write("\n".join(filepaths))
        path = Path(f.name)

    try:
        yield path
    finally:
        path.unlink(missing_ok=True)
    
def files_in_depot(filepaths: Iterable[str], environ: dict = {}) -> set[str]:
    """
    Return files that are in depot.
    """
    filepaths = list(filepaths)

    if not filepaths:
        return set()
    
    with filepaths_to_temp_file(filepaths) as txt_file: 
        fstat_process = run_p4_cmd(["p4", "-x", txt_file.as_posix(), "fstat"], environ)

    tracked = set()
    client_file_tag = "... clientFile "
    len_client_file_tag = len(client_file_tag)
    for line in fstat_process.stdout.splitlines():
        if line.startswith(client_file_tag):
            path = line[len_client_file_tag:].strip()
            tracked.add(__format_path(path))

    in_depot = set()
    for filepath in filepaths:
        filepath = __format_path(filepath)
        if filepath in tracked:
            in_depot.add(filepath)
    return in_depot


def push_p4_session(
    changelist_name: str = "default", p4_output: P4LogOutput | None = None
) -> bool:
    """
    Open all files added via `p4_session_edit` for edit in Perforce.

    Returns:
        True if all files were successfully opened for edit; otherwise False.
    """
    global _p4_session_cache
    # Split files in workspaces
    workspace_files: dict[WorkspaceInfo, set[str]] = {}
    workspaces = get_client_workspaces()
    if not workspaces:
        return True
    for file in _p4_session_cache:
        file_workspace = get_file_workspace(file, workspaces)
        if not file_workspace:
            continue
        _workspace_files = workspace_files.get(file_workspace, None)
        if not _workspace_files:
            _workspace_files = set((__format_path(file),))
            workspace_files[file_workspace] = _workspace_files
        else:
            _workspace_files.add(__format_path(file))

    full_success = True
    for workspace, files in workspace_files.items():
        environ = create_p4_client_env(workspace.name)

        to_edit = files_in_depot(files, environ)
        to_add = files.difference(to_edit)
        if to_edit:
            with filepaths_to_temp_file(to_edit) as txt_file:
                edit_process = run_p4_cmd(
                    ["p4", "-x", txt_file.as_posix(), "edit", "-c", changelist_name, "-v", ], environ
                )
            if not is_process_success(edit_process):
                full_success = False
                if p4_output is not None:
                    p4_output.add_process_result(edit_process)

        if to_add:
            with filepaths_to_temp_file(to_add) as txt_file:
                add_process = run_p4_cmd(
                    ["p4", "-x", txt_file.as_posix(), "add", "-c", changelist_name, "-v"], environ
                )

            if not is_process_success(add_process):
                full_success = False
                if p4_output is not None:
                    p4_output.add_process_result(add_process)

    reset_p4_session()
    return full_success


# endregion
