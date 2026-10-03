from pathlib import Path

import bpy


def get_relative_path_to_scene(path: str) -> str:
    """Safely get relative path to scene.

    Args:
        path: path to resolve.

    Returns:
        Relative path with forward slashes.
        Return Original path with forward slashes if scene is not saved.
    """

    # Strip " and ' characters
    # windows adds "" when using 'copy as path'
    path = path.strip()
    path = path.strip('"')
    path = path.strip("'")
    
    if not path:
        return ""

    path: Path = Path(path)

    if path.is_file():
        path = path.parent

    relative_path = ""
    if bpy.data.is_saved and path.is_absolute():
        try:
            relative_path = bpy.path.relpath(path.as_posix())
        except ValueError:
            print("[ERROR] Cannot resolve path because it's on a different disk than the Blender scene.")
            # Fails if path is not on same disk as blender scene...
            pass

    final_path = relative_path if relative_path else str(path)

    # Force forward slashes in all cases
    final_path = final_path.replace("\\", "/")

    # Make sure path starts with // if it seems to be relative (starts with /)
    if final_path.startswith("/"):
        final_path = "//" + final_path.lstrip("/")

    if final_path != "//":
        # Make sure path ends with /
        final_path = final_path.rstrip("/")
        final_path += "/"
    else:
        # Format path because '//' doesnt work when using alt + click to open in windows explorer
        final_path = "//./"

    return final_path
