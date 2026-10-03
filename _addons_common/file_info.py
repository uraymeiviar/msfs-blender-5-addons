import os
import stat

from pathlib import Path

def is_read_only(filepath: str | Path) -> bool:
    """Check if a file is read only."""
    filepath = Path(filepath).as_posix()
    try:
        info = os.stat(filepath)
    except FileNotFoundError:
        return False
    if info.st_file_attributes & stat.FILE_ATTRIBUTE_READONLY:
        return True
    return False
