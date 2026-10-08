import os
import stat

from pathlib import Path

def is_read_only(filepath: str | Path) -> bool:
    """Check if a file is read only."""
    filepath = Path(filepath)
    try:
        info = os.stat(filepath)
    except FileNotFoundError:
        return False
    if info.st_file_attributes & stat.FILE_ATTRIBUTE_READONLY:
        return True
    return False

def set_read_only(path: str | Path, read_only: bool = False) -> bool:
    """Set or clear the read-only state of a file."""
    path = Path(path)

    if not path.is_file():
        return False

    try:
        path.chmod(mode=stat.S_IWRITE)
        return True

    except:
        return False
