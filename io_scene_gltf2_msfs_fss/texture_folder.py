"""
FSS: the MSFS 2024 texture folder (material-management journal, Sessions 34 and 35).

The MSFS 2024 package tool compiles a texture only when the glTF image URI resolves, relative to the glTF, to the PNG,
and a Texture XML `<name>.png.xml` sits beside that PNG. With the scene's MSFS Texture Folder set (a Blender path,
`//` relative to the `.blend`), every MSFS 2024 export, after each glTF is written:

1. points each image URI at the PNG of the same file name in that folder; a PNG that is not there is reported and its
   URI left as it was, as a warning so the export still finishes (the exporter copies nothing, decision S35.2);
2. reads the XML already beside a PNG into its image's flags, once per image (`Image.fss_texture_xml_read`), so an
   XML on disk is not lost (decision S34.2); from then on Blender's flags win;
3. writes the XMLs of those PNGs with Asobo's TextureLib (decision S34.1): the slot from the material, the flags from
   `image.msfs_flags`.

An empty folder keeps the export as it was. The MSFS 2020 target is not touched (the dispatcher in `__init__` calls
`process_export` for MSFS 2024 only).

- `Scene.msfs_fss_texture_folder`: the folder.
- `Image.fss_texture_xml_read`: the image's flags were read from its XML.
"""
import json
import os
from pathlib import Path
from urllib.parse import quote, unquote
from xml.etree import ElementTree

import bpy

FOLDER_PROP = "msfs_fss_texture_folder"
READ_PROP = "fss_texture_xml_read"


def texture_folder(scene) -> Path | None:
    """The scene's MSFS Texture Folder as an absolute path, or None when it is not set."""
    value = getattr(scene, FOLDER_PROP, "")
    if not value:
        return None
    return Path(os.path.normpath(bpy.path.abspath(value)))


def _logger():
    from .io.com import msfs_logs
    try:
        return msfs_logs.get_logger()
    except NameError:  # no MSFS 2024 export has set it up
        return None


def _report(level, message, details=""):
    print(f"[FSS Texture Folder] {message}" + (f"\n{details}" if details else ""))
    logger = _logger()
    if logger is not None:
        getattr(logger, level)(message=message, details=details)


def _file_name(uri: str) -> str:
    return Path(unquote(uri.replace("\\", "/"))).name


def point_uris(gltf_path, folder: Path):
    """Point every image URI of a written .gltf at the PNG of the same file name in `folder`.

    Returns three lists of file names: pointed, missing (no such file in the folder) and unreachable (on another drive,
    no relative path). The file is rewritten only when a URI changes, in the format Khronos writes.
    """
    gltf_path = Path(gltf_path)
    pointed, missing, unreachable = [], [], []
    if gltf_path.suffix.lower() != ".gltf" or not gltf_path.is_file():
        return pointed, missing, unreachable
    data = json.loads(gltf_path.read_text(encoding="utf8"))
    changed = False
    for image in data.get("images", []):
        uri = image.get("uri")
        if not uri or uri.startswith("data:"):
            continue
        name = _file_name(uri)
        target = folder / name
        if not target.is_file():
            missing.append(name)
            continue
        try:
            relative = os.path.relpath(target, gltf_path.parent)
        except ValueError:  # another drive
            unreachable.append(name)
            continue
        new_uri = quote(Path(relative).as_posix(), safe="/")
        pointed.append(name)
        if new_uri != uri:
            image["uri"] = new_uri
            changed = True
    if changed:
        # As io_scene_gltf2/io/exp/export.py save_gltf writes a .gltf
        text = json.dumps(data, indent="\t", separators=(",", ":"), allow_nan=False)
        with open(gltf_path, "w", encoding="utf8", newline="\n") as file:
            file.write(text)
            file.write("\n")
    return pointed, missing, unreachable


def images_named(stem: str):
    """The images whose name without extension and numeric suffix is `stem`, as Asobo's TextureLib finds them."""
    return [image for image in bpy.data.images if image.name and image.name.split(".", 1)[0] == stem]


def parse_user_flags(text: str) -> dict:
    """`<UserFlags>` text to `image.msfs_flags` values; codes that are not image flags (slot flags) are ignored."""
    from .blender.msfs_image import MSFS2024ImageFlagsEnum as F
    codes = [code for code in (text or "").replace(" ", "").split("+") if code]
    values = {F.QUALITYHIGH.attribute_name(): False, F.ALPHAPRESERVATION.attribute_name(): False,
              F.NOREDUCTION.attribute_name(): False, F.NOMIPMAP.attribute_name(): False,
              F.PRECOMPUTEDINVAVG.attribute_name(): False, F.ANISOTROPIC.attribute_name(): "NONE"}
    for flag in (F.QUALITYHIGH, F.ALPHAPRESERVATION, F.NOREDUCTION, F.NOMIPMAP, F.PRECOMPUTEDINVAVG):
        if flag.flag_code().lstrip("+") in codes:
            values[flag.attribute_name()] = True
    prefix = F.ANISOTROPIC.flag_code().lstrip("+")
    for code in codes:
        if code.startswith(prefix):
            level = code[len(prefix):]
            if level in {"0", "2", "4", "8", "16"}:
                values[F.ANISOTROPIC.attribute_name()] = level
    return values


def read_xml_user_flags(xml_path: Path) -> str | None:
    """The `<UserFlags>` text of a Texture XML ("" when it has none), or None when it cannot be read."""
    try:
        root = ElementTree.parse(xml_path).getroot()
    except (OSError, ElementTree.ParseError):
        return None
    node = root.find("UserFlags")
    return (node.text or "") if node is not None else ""


def read_xml_once(stem: str, xml_path: Path) -> bool:
    """Read an XML's flags into every image named `stem` that was never read; True when something was read."""
    images = [image for image in images_named(stem) if not getattr(image, READ_PROP, True)]
    if not images or not xml_path.is_file():
        return False
    text = read_xml_user_flags(xml_path)
    if text is None:
        _report("warning", f"'{xml_path.name}' : could not be read, Blender's flags are used.", str(xml_path))
        return False
    values = parse_user_flags(text)
    for image in images:
        flags = getattr(image, "msfs_flags", None)
        if flags is None:
            continue
        for attribute, value in values.items():
            setattr(flags, attribute, value)
        setattr(image, READ_PROP, True)
    return True


def mark_written(stem: str):
    """The XML of `stem` was written from Blender's flags: its images count as read, so a later read never takes the
    file back over a flag changed in Blender since."""
    for image in images_named(stem):
        if hasattr(image, READ_PROP):
            setattr(image, READ_PROP, True)


def process_export(gltf_path, scene):
    """After an MSFS 2024 glTF is written: point its URIs at the texture folder, read XMLs once, write the XMLs."""
    folder = texture_folder(scene)
    if folder is None:
        return
    if not folder.is_dir():
        _report("error", "MSFS Texture Folder does not exist: image URIs and texture XMLs not written.", str(folder))
        return
    pointed, missing, unreachable = point_uris(gltf_path, folder)
    gltf_name = Path(gltf_path).name
    for name in missing:
        _report("warning", f"'{name}' : not in the MSFS Texture Folder, its URI in '{gltf_name}' is unchanged.",
                f"Copy the texture to:\n{folder}")
    for name in unreachable:
        _report("error", f"'{name}' : the MSFS Texture Folder is on another drive than '{gltf_name}'.",
                f"No relative path from:\n{Path(gltf_path).parent}\nto:\n{folder}")
    if not pointed:
        return
    for name in pointed:
        read_xml_once(Path(name).stem, folder / (name + ".xml"))
    from .io.exp import texture_lib
    written = texture_lib.export_gltfs_texture_lib([str(gltf_path)], {Path(name).stem for name in pointed})
    for stem in written:
        mark_written(stem)


def register():
    bpy.types.Scene.msfs_fss_texture_folder = bpy.props.StringProperty(
        name="MSFS Texture Folder",
        description=("Package texture folder of the MSFS 2024 export (a path relative to the .blend). Each export "
                     "points the glTF image URIs at the PNGs there and writes their texture XMLs beside them. "
                     "Empty: URIs are file names and no XML is written"),
        subtype="DIR_PATH",
        default="",
    )
    bpy.types.Image.fss_texture_xml_read = bpy.props.BoolProperty(
        name="Texture XML Read",
        description="The image's MSFS flags were read from its texture XML; from then on Blender's flags are written",
        default=False,
    )


def unregister():
    for owner, name in ((bpy.types.Scene, FOLDER_PROP), (bpy.types.Image, READ_PROP)):
        if hasattr(owner, name):
            delattr(owner, name)
