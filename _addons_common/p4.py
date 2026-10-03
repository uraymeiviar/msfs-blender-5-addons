import subprocess
import codecs
from dataclasses import dataclass
from pathlib import Path
import os

@dataclass
class WorkspaceInfo:
    name: str
    root: Path


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


def use_p4():
    try:
        process = run_p4_cmd(["p4", "info"])
        if is_process_success(process):
            return True
    except Exception as e:  # in case p4 is not installed
        return False

    return False


def run_p4_cmd(cmd: list[str], env: dict | None = None) -> subprocess.CompletedProcess:

    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        env=env
    )


def get_client_workspaces()->list[WorkspaceInfo]:

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

def get_file_workspace(filepath: str| Path) ->None|WorkspaceInfo:
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
    
    filepath = Path(filepath).as_posix()
    file_workspace = get_file_workspace(filepath)

    environ = None
    if file_workspace:
        environ = create_p4_client_env(file_workspace.name)
    

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

    filepath = Path(filepath).as_posix()
    file_workspace = get_file_workspace(filepath)

    environ = None
    if file_workspace:
        environ = create_p4_client_env(file_workspace.name)

    process = run_p4_cmd(["p4", "add", "-c", changelist_name, "-v", filepath], environ)
    if p4_output is not None:
        p4_output.add_process_result(process)

    if not is_process_success(process):
        return False

    return True

