"""
FSS: Levels for the Occlusion/Roughness/Metallic texture and the detail ORM texture of MSFS materials (ORM levels
journal, 20261114).

Five values per channel (occlusion R, roughness G, metallic B): input black, gamma, input white, output black, output
white. For a channel value x in 0..1:

    t = clamp((x - in_black) / (in_white - in_black), 0, 1)     (in_white <= in_black: t = 1 where x >= in_black, else 0)
    out = out_black + (out_white - out_black) * t ^ (1 / gamma)

Defaults (0, 1, 1, 0, 1) change nothing.

- Stored on the image (`Image.fss_orm_levels`): every material using the texture shares the values, and one file name
  holds one filtered version.
- Preview: in each MSFS material, a group node (LEVELS_NODES) sits between the ORM or detail ORM texture node and
  every node that reads its colour. It is always there; at the defaults it passes the texture through. It is made of
  Vector Math nodes only (no Separate Color), so the Khronos exporter, which follows node links back to the texture
  and takes the channel from the last Separate Color on the way, finds the same texture and channels as without it.
  Asobo's `_update_omr_links` (marked # FSS) and the Update Material Nodes operator call `apply`; a value change
  updates every material whose ORM or detail ORM texture node shows the image.
- Export: the dispatcher's `gather_image_hook` (package `__init__`) calls `filter_gltf_image`, which replaces the
  bytes the exporter is about to write for an image with levels (a PNG, all channels taken from that one image as they
  are) by the same PNG with the levels applied: same file name, size, bit depth, colour type and alpha. Nothing in the
  artist's file changes; textures on disk are never written. A cache keyed by the source bytes and the 15 values
  filters a texture once for several exports (presets, LODs). The formula, the PNG code and the cache are in
  `orm_levels_filter.py` (no Blender). After the export, `write_levels_list` writes `<glTF name>.fss-levels.json`
  beside the glTF with every texture file of the glTF whose image has levels (name and the 15 values), only when
  there is one: the FSS deploy filters the source of each with `orm_levels_filter` itself (journal decision 8).
- Panel: `draw` under the ORM and detail ORM slots (two marked lines in Asobo's MaterialUtilsUI): per channel a
  histogram with the markers, the sliders, and the result's range. The histogram is read from the image's pixels in
  memory, cached per image and file (path, size, modification time), and drawn as a preview icon; drawing writes no
  ID data.
"""

import hashlib
import json
import os
from urllib.parse import unquote

import bpy
import numpy as np

# The formula, the PNG code and the export cache need no Blender: they are in orm_levels_filter, which the FSS deploy
# also loads (journal decision 8)
from .orm_levels_filter import (  # noqa: F401  (part of this module's interface)
    CHANNELS, DEFAULT, DEFAULTS, FIELDS, PNG_SIGNATURE, apply_levels, clear_cache, decode_png, encode_png, filter_png,
    filtered_bytes, levels_float, png_header, stats,
)

CHANNEL_LABELS = ("Occlusion (R)", "Roughness (G)", "Metallic (B)")
PROP = "fss_orm_levels"

GROUP_NAME = ".FSS ORM Levels v1"
# Texture node name (Asobo's tree) -> FSS levels node name
LEVELS_NODES = {
    "Occlusion (R), Roughness (G), Metallic (B)": "FSS ORM Levels",
    "Detail Occlusion (R), Roughness (G), Metallic (B)": "FSS Detail ORM Levels",
}
# Material property -> texture node name
SLOT_ATTRIBUTES = {
    "msfs_occlusion_metallic_roughness_texture": "Occlusion (R), Roughness (G), Metallic (B)",
    "msfs_detail_occlusion_metallic_roughness_texture": "Detail Occlusion (R), Roughness (G), Metallic (B)",
}
_STEP_WIDTH = 1e-5  # in_white <= in_black: a ramp this wide below in_black stands in for the step

HIST_BINS = 256
HIST_SIZE = 128  # pixels of the square histogram image (two bins per column)


# region Properties

def levels_of(image):
    """The 15 values of `image` as three (in_black, gamma, in_white, out_black, out_white) tuples; DEFAULTS when the
    image is None or has no values."""
    group = getattr(image, PROP, None) if image is not None else None
    if group is None:
        return DEFAULTS
    return tuple(tuple(float(getattr(getattr(group, channel), field)) for field in FIELDS) for channel in CHANNELS)


def is_default(image):
    return levels_of(image) == DEFAULTS


def _on_change(self, context):
    image = self.id_data
    if isinstance(image, bpy.types.Image):
        refresh_image(image)


class FSS_ORMChannelLevels(bpy.types.PropertyGroup):
    in_black: bpy.props.FloatProperty(
        name="Input Black", description="Texture value that becomes Output Black; values below it too",
        default=0.0, min=0.0, max=1.0, precision=3, update=_on_change,
    )  # type: ignore
    gamma: bpy.props.FloatProperty(
        name="Gamma", description=("Midtones: above 1 brightens the values between Input Black and Input White, below "
                                   "1 darkens them. The marker in the histogram is the value that becomes the middle "
                                   "of the output range"),
        default=1.0, min=0.01, max=10.0, soft_min=0.1, soft_max=5.0, precision=3, update=_on_change,
    )  # type: ignore
    in_white: bpy.props.FloatProperty(
        name="Input White", description="Texture value that becomes Output White; values above it too",
        default=1.0, min=0.0, max=1.0, precision=3, update=_on_change,
    )  # type: ignore
    out_black: bpy.props.FloatProperty(
        name="Output Black", description="Lowest value written", default=0.0, min=0.0, max=1.0, precision=3,
        update=_on_change,
    )  # type: ignore
    out_white: bpy.props.FloatProperty(
        name="Output White", description="Highest value written", default=1.0, min=0.0, max=1.0, precision=3,
        update=_on_change,
    )  # type: ignore


class FSS_ORMLevels(bpy.types.PropertyGroup):
    register_order = 1  # after FSS_ORMChannelLevels

    occlusion: bpy.props.PointerProperty(type=FSS_ORMChannelLevels)  # type: ignore
    roughness: bpy.props.PointerProperty(type=FSS_ORMChannelLevels)  # type: ignore
    metallic: bpy.props.PointerProperty(type=FSS_ORMChannelLevels)  # type: ignore

# endregion


# region Preview nodes

def node_values(levels):
    """The group node's input values for three channels' levels: Scale, Bias, Inverse Gamma, Output Black, Output
    Range, each an (R, G, B) vector, so that out = black + range * clamp(x * scale + bias, 0, 1) ^ inverse_gamma."""
    scale, bias, inverse, black, span = [], [], [], [], []
    for in_black, gamma, in_white, out_black, out_white in levels:
        if in_white > in_black:
            s = 1.0 / (in_white - in_black)
            b = -in_black * s
        else:
            s = 1.0 / _STEP_WIDTH
            b = -(in_black - _STEP_WIDTH) * s
        scale.append(s)
        bias.append(b)
        inverse.append(1.0 / gamma)
        black.append(out_black)
        span.append(out_white - out_black)
    return {"Scale": scale, "Bias": bias, "Inverse Gamma": inverse, "Output Black": black, "Output Range": span}


def levels_group():
    """The shared node group: Color in, Color out; Vector Math only (see the module docstring)."""
    group = bpy.data.node_groups.get(GROUP_NAME)
    if group is not None and group.bl_idname == "ShaderNodeTree":
        return group
    group = bpy.data.node_groups.new(GROUP_NAME, "ShaderNodeTree")
    interface = group.interface
    interface.new_socket("Color", in_out="INPUT", socket_type="NodeSocketColor")
    for name in ("Scale", "Bias", "Inverse Gamma", "Output Black", "Output Range"):
        interface.new_socket(name, in_out="INPUT", socket_type="NodeSocketVector")
    interface.new_socket("Color", in_out="OUTPUT", socket_type="NodeSocketColor")
    nodes, links = group.nodes, group.links
    group_in = nodes.new("NodeGroupInput")
    group_in.location = (-800.0, 0.0)
    group_out = nodes.new("NodeGroupOutput")
    group_out.location = (400.0, 0.0)

    def vector(operation, x, *inputs):
        node = nodes.new("ShaderNodeVectorMath")
        node.operation = operation
        node.location = (x, 0.0)
        for index, value in enumerate(inputs):
            if isinstance(value, bpy.types.NodeSocket):
                links.new(value, node.inputs[index])
            else:
                node.inputs[index].default_value = value
        return node.outputs[0]

    ramp = vector("MULTIPLY_ADD", -600.0, group_in.outputs["Color"], group_in.outputs["Scale"], group_in.outputs["Bias"])
    low = vector("MAXIMUM", -400.0, ramp, (0.0, 0.0, 0.0))
    t = vector("MINIMUM", -200.0, low, (1.0, 1.0, 1.0))
    curved = vector("POWER", 0.0, t, group_in.outputs["Inverse Gamma"])
    result = vector("MULTIPLY_ADD", 200.0, curved, group_in.outputs["Output Range"], group_in.outputs["Output Black"])
    links.new(result, group_out.inputs["Color"])
    return group


def _set_values(node, levels):
    for name, value in node_values(levels).items():
        socket = node.inputs[name]
        if tuple(round(v, 7) for v in socket.default_value) != tuple(round(v, 7) for v in value):
            socket.default_value = value


def _apply_slot(nodes, links, texture_name, levels_name):
    texture = nodes.get(texture_name)
    if texture is None or texture.bl_idname != "ShaderNodeTexImage":
        return
    node = nodes.get(levels_name)
    if node is None or node.bl_idname != "ShaderNodeGroup":
        if node is not None:
            nodes.remove(node)
        node = nodes.new("ShaderNodeGroup")
        node.name = node.label = levels_name
        node.parent = texture.parent
        node.location = (texture.location.x + texture.width + 20.0, texture.location.y)
        node.hide = True
    if node.node_tree is None or node.node_tree.name != GROUP_NAME:
        node.node_tree = levels_group()
    _set_values(node, levels_of(texture.image))
    source = texture.outputs[0]
    if not (node.inputs[0].is_linked and node.inputs[0].links[0].from_socket == source):
        links.new(source, node.inputs[0])
    for link in [link for link in source.links if link.to_node != node]:
        target = link.to_socket
        links.remove(link)
        links.new(node.outputs[0], target)


def apply_tree(node_tree):
    """Insert or update the levels nodes of both slots in an MSFS material's node tree; a second call adds nothing."""
    if node_tree is None:
        return
    for texture_name, levels_name in LEVELS_NODES.items():
        _apply_slot(node_tree.nodes, node_tree.links, texture_name, levels_name)


def apply(owner):
    """For an MSFS2024_Material (Asobo's tree builder)."""
    apply_tree(getattr(owner, "node_tree", None))


def output_socket(nodes, texture):
    """The socket that carries `texture`'s colour after the levels (the texture's own Color output without them)."""
    name = LEVELS_NODES.get(texture.name)
    node = nodes.get(name) if name else None
    if node is not None and node.bl_idname == "ShaderNodeGroup" and node.inputs[0].is_linked \
            and node.inputs[0].links[0].from_node == texture:
        return node.outputs[0]
    return texture.outputs[0]


def materials_using(image):
    """(material, slot attribute) pairs of local MSFS materials that use `image` as ORM or detail ORM texture."""
    pairs = []
    if image is None:
        return pairs
    for material in bpy.data.materials:
        if material.library or getattr(material, "msfs_material_type", "NONE") == "NONE":
            continue
        for attribute in SLOT_ATTRIBUTES:
            if getattr(material, attribute, None) == image:
                pairs.append((material, attribute))
    return pairs


def refresh_image(image):
    """After a value change: every MSFS material whose ORM or detail ORM texture node shows `image`."""
    for material in bpy.data.materials:
        if material.library or material.node_tree is None or getattr(material, "msfs_material_type", "NONE") == "NONE":
            continue
        nodes = material.node_tree.nodes
        for texture_name, levels_name in LEVELS_NODES.items():
            texture = nodes.get(texture_name)
            if texture is not None and getattr(texture, "image", None) == image:
                _apply_slot(nodes, material.node_tree.links, texture_name, levels_name)

# endregion


# region Export

def _report(level, message, details=""):
    print(f"[FSS ORM Levels] {level.upper()}: {message}" + (f"\n{details}" if details else ""))
    try:
        from .io.com import msfs_logs
        logger = msfs_logs.get_logger()
    except Exception:  # no MSFS 2024 export has set the logger up (MSFS 2020, File > Export)
        logger = None
    if logger is not None:
        try:
            getattr(logger, level)(message=message, details=details)
        except Exception:
            pass


def _gltf_bytes(gltf_image):
    """(holder, attribute) of the bytes the exporter writes for `gltf_image`: its ImageData (.gltf + files) or its
    BinaryData buffer view (.glb)."""
    uri = getattr(gltf_image, "uri", None)
    if uri is not None and hasattr(uri, "_data"):
        return uri, "_data"
    view = getattr(gltf_image, "buffer_view", None)
    if view is not None and hasattr(view, "data"):
        return view, "data"
    return None, None


def _fill_images(export_image):
    """The Blender images an ExportImage takes its channels from, each once."""
    images = []
    for _channel, fill in getattr(export_image, "fills", {}).items():
        image = getattr(fill, "image", None)
        if image is not None and image not in images:
            images.append(image)
    return images


def filter_gltf_image(gltf_image, export_image, export_settings):
    """Khronos gather_image_hook: the levels on the bytes of an image the exporter writes. Returns True when the
    bytes were replaced."""
    if export_image is None:
        return False
    original = getattr(export_image, "original", None)
    if original is not None:
        if not is_default(original):
            _report("warning", f"'{original.name}' : ORM levels not applied, 'Keep Original' references the "
                               "texture file itself.")
        return False
    fills = list(getattr(export_image, "fills", {}).items())
    images = _fill_images(export_image)
    leveled = [image for image in images if not is_default(image)]
    if not leveled:
        return False
    image = leveled[0]
    same_image = len(images) == 1 and all(type(fill).__name__ == "FillImage" and channel == fill.src_chan
                                          for channel, fill in fills)
    if not same_image:
        _report("warning", f"'{image.name}' : ORM levels not applied, the exporter composes this texture from "
                           "several channels or images.")
        return False
    holder, attribute = _gltf_bytes(gltf_image)
    data = getattr(holder, attribute, None) if holder is not None else None
    if not data:
        return False
    if not data.startswith(PNG_SIGNATURE):
        _report("warning", f"'{image.name}' : ORM levels not applied, only PNG textures are filtered.")
        return False
    levels = levels_of(image)
    try:
        result = filtered_bytes(data, levels)
    except ValueError as error:
        _report("warning", f"'{image.name}' : ORM levels not applied, {error}.")
        return False
    setattr(holder, attribute, result)
    try:
        from . import msfs2020_target, texture_folder
        scene = bpy.context.scene
        if not msfs2020_target.is_msfs2020_target(scene) and texture_folder.texture_folder(scene) is not None:
            _report("warning", f"'{image.name}' : the image URI is pointed at the PNG in the MSFS Texture Folder, "
                               "which has no ORM levels; the filtered PNG is the one written beside the glTF.")
    except Exception:
        pass
    return True


def leveled_image(export_image):
    """The Blender image with levels (not the defaults) an ExportImage is made from: its 'Keep Original' image, or the
    first of the images it takes its channels from. None without levels."""
    if export_image is None:
        return None
    original = getattr(export_image, "original", None)
    if original is not None:
        return None if is_default(original) else original
    return next((image for image in _fill_images(export_image) if not is_default(image)), None)


def levels_record(gltf_image, export_image, filtered):
    """In gather_image_hook, after `filter_gltf_image`: (where the file name will be, image, filtered) for an image of
    the glTF whose Blender image has levels, whether or not the exporter could filter it; None for the others and for
    images without a file (.glb). Where the name will be: the ImageData (.gltf with files; the exporter gives it its
    URI later and replaces the glTF image's ImageData by that string) or the URI string ('Keep Original')."""
    image = leveled_image(export_image)
    if image is None:
        return None
    uri = getattr(gltf_image, "uri", None)
    if uri is None or not (hasattr(uri, "_data") or isinstance(uri, str)):
        return None
    return uri, image, bool(filtered)


LEVELS_LIST_SUFFIX = ".fss-levels.json"


def levels_list_path(gltf_path):
    """`<glTF path without extension>.fss-levels.json`: the list of the glTF's texture files with levels."""
    return os.path.splitext(gltf_path)[0] + LEVELS_LIST_SUFFIX


def write_levels_list(export_settings, records):
    """After an export (post_export_hook): beside the glTF, `<name>.fss-levels.json` lists every texture file the glTF
    references whose image has levels, whether or not the exporter wrote it filtered: per file its URI decoded
    (relative to the glTF), the image, its 15 values and, as information, the SHA-1 of the bytes the export wrote for
    it. The FSS deploy filters the source of each file with these values itself (ORM levels journal decision 8).
    `records` are `levels_record`'s. Without any, no list is written and a list left by an earlier export of the same
    glTF is removed. Never raises: an error is reported."""
    try:
        gltf_path = export_settings.get("gltf_filepath")
        if not gltf_path:
            return None
        path = levels_list_path(gltf_path)
        gltf_dir = os.path.dirname(os.path.abspath(gltf_path))
        entries = {}
        separate = export_settings.get("gltf_format") == "GLTF_SEPARATE"
        for holder, image, filtered in records:
            data = getattr(holder, "_data", None)
            uri = holder if isinstance(holder, str) else getattr(holder, "uri", None)
            if not separate or not isinstance(uri, str) or not uri or uri.startswith("data:"):
                continue  # .glb or embedded: the levels are in the glTF itself, no file to list
            file = unquote(uri).replace("\\", "/")
            if file in entries:
                continue
            entry = {"file": file}
            if data:
                entry["sha1"] = hashlib.sha1(data).hexdigest()
                written = os.path.join(gltf_dir, file)
                on_disk = None
                if filtered and os.path.isfile(written):
                    with open(written, "rb") as f:
                        on_disk = hashlib.sha1(f.read()).hexdigest()
                if filtered and on_disk != entry["sha1"]:
                    _report("warning", f"'{file}' : the file beside the glTF is not the one written with ORM levels "
                                       f"({'missing' if on_disk is None else 'other bytes'}).")
            entry["image"] = image.name
            entry["levels"] = {channel: dict(zip(FIELDS, values)) for channel, values in zip(CHANNELS, levels_of(image))}
            entries[file] = entry
        if not entries:
            if os.path.isfile(path):
                os.remove(path)
            return None
        content = {"gltf": os.path.basename(gltf_path), "images": [entries[name] for name in sorted(entries)]}
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(content, f, indent=2)
            f.write("\n")
        return path
    except Exception as error:  # the export itself succeeded; a deploy then finds no list and takes the sources
        _report("error", f"the list of textures with ORM levels could not be written: {error}")
        return None

# endregion


# region Panel

_histograms = {}  # cache key -> (counts (3 x HIST_BINS), minimum (3), maximum (3))
_previews = None
_preview_state = {}  # preview name -> (histogram key, levels) its pixels show


def _histogram_key(image):
    if image.packed_file is not None:
        return (image.name_full, "packed", image.packed_file.size, tuple(image.size))
    path = bpy.path.abspath(image.filepath_raw, library=image.library)
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return (image.name_full, os.path.normcase(os.path.normpath(path)), stat.st_size, stat.st_mtime_ns,
            tuple(image.size), image.is_dirty)


def histogram(image):
    """(counts, minimum, maximum) of the image's R, G and B: counts per 8-bit level (values rounded to the nearest of
    256), minimum and maximum in 0..1. None when the image has no pixels. Read only; cached per image and file."""
    if image is None:
        return None
    key = _histogram_key(image)
    if key is None:
        return None
    cached = _histograms.get(key)
    if cached is not None:
        return cached
    width, height = image.size
    if width == 0 or height == 0:
        return None
    buffer = np.empty(width * height * 4, np.float32)
    image.pixels.foreach_get(buffer)
    rgb = buffer.reshape(-1, 4)[:, :3]
    counts = np.stack([np.bincount(np.clip(np.floor(rgb[:, c].astype(np.float64) * 255.0 + 0.5), 0, 255)
                                   .astype(np.int64), minlength=HIST_BINS) for c in range(3)])
    result = (counts, rgb.min(axis=0).astype(np.float64), rgb.max(axis=0).astype(np.float64))
    key = _histogram_key(image) or key  # reading the pixels may load the image, which can change its state
    for old in [k for k in _histograms if k[0] == key[0]]:
        del _histograms[old]
    _histograms[key] = result
    return result


def gamma_marker(levels):
    """The input value that becomes the middle of the output range."""
    in_black, gamma, in_white, _out_black, _out_white = levels
    if in_white <= in_black:
        return in_black
    return in_black + (in_white - in_black) * 0.5 ** gamma


def histogram_pixels(counts, levels, channel):
    """RGBA float pixels (rows bottom to top) of a HIST_SIZE square: the channel's counts (two bins per column), the
    range outside input black..white dimmed, markers at input black (black), gamma (grey) and input white (white)."""
    size = HIST_SIZE
    columns = counts.reshape(size, -1).sum(axis=1).astype(np.float64)
    peak = columns.max()
    heights = np.zeros(size) if peak <= 0 else np.ceil(columns / peak * (size - 4)).astype(np.int64)
    pixels = np.empty((size, size, 4), np.float32)
    pixels[:] = (0.16, 0.16, 0.16, 1.0)
    tint = np.zeros(3)
    tint[channel] = 0.35
    bar = np.clip(np.array((0.6, 0.6, 0.6)) + tint, 0.0, 1.0)
    rows = np.arange(size)[:, None]
    filled = rows < heights[None, :]
    pixels[filled, :3] = bar
    in_black, _gamma, in_white = levels[0], levels[1], levels[2]
    x = (np.arange(size) + 0.5) / size
    outside = (x < in_black) | (x > max(in_white, in_black))
    pixels[:, outside, :3] *= 0.45

    def marker(value, color):
        column = int(np.clip(round(value * (size - 1)), 0, size - 1))
        pixels[:, column, :3] = color

    marker(in_black, (0.0, 0.0, 0.0))
    marker(in_white, (1.0, 1.0, 1.0))
    marker(gamma_marker(levels), (0.55, 0.55, 0.55))
    return pixels.ravel()


def _histogram_icon(image, channel, levels, counts):
    """The icon id of the channel's histogram preview (0 when previews are not available). A preview is not ID
    data: writing its pixels while a panel draws is allowed."""
    global _previews
    try:
        from bpy.utils import previews
        if _previews is None:
            _previews = previews.new()
        name = f"{image.name_full}|{channel}"
        preview = _previews.get(name)
        if preview is None:
            preview = _previews.new(name)
        state = (_histogram_key(image), tuple(round(v, 4) for v in levels))
        if _preview_state.get(name) != state:
            preview.image_size = (HIST_SIZE, HIST_SIZE)
            preview.image_pixels_float.foreach_set(histogram_pixels(counts, levels, channel))
            _preview_state[name] = state
        return preview.icon_id
    except Exception:
        return 0


def draw(layout, material, attribute):
    """The Levels under an ORM or detail ORM texture slot. Draws only; writes no data."""
    image = getattr(material, attribute, None)
    if image is None or not hasattr(image, PROP):
        return
    panel = layout.panel(f"FSS_PT_orm_levels_{attribute}", default_closed=True)
    header, body = panel if isinstance(panel, tuple) else (layout, layout)
    changed = not is_default(image)
    header.label(text="Levels (adjusted)" if changed else "Levels", icon="IMAGE_RGB_ALPHA")
    if not body:
        return
    users = materials_using(image)
    if len(users) > 1:
        body.label(text=f"'{image.name}' is used by {len(users)} material slots: changes apply to all", icon="INFO")
    body.label(text="Applied to the exported texture only; the file stays as it is")
    data = histogram(image)
    group = getattr(image, PROP)
    for channel, (name, label) in enumerate(zip(CHANNELS, CHANNEL_LABELS)):
        levels = levels_of(image)[channel]
        values = getattr(group, name)
        box = body.box()
        box.label(text=label)
        if data is None:
            box.label(text="No histogram: the texture has no pixels", icon="ERROR")
        else:
            counts, minimum, maximum = data
            icon = _histogram_icon(image, channel, levels, counts[channel])
            if icon:
                box.template_icon(icon_value=icon, scale=7.0)
            low, high = sorted(float(v) for v in levels_float(np.array([minimum[channel], maximum[channel]]), levels))
            box.label(text=f"Texture {minimum[channel]:.3f} to {maximum[channel]:.3f}, result {low:.3f} to {high:.3f}")
        column = box.column(align=True)
        column.prop(values, "in_black")
        column.prop(values, "gamma")
        column.prop(values, "in_white")
        column = box.column(align=True)
        column.prop(values, "out_black")
        column.prop(values, "out_white")

# endregion


def register():
    bpy.types.Image.fss_orm_levels = bpy.props.PointerProperty(
        type=FSS_ORMLevels, name="ORM Levels",
        description="Levels of the texture's occlusion, roughness and metallic channels, applied when exporting",
    )


def unregister():
    global _previews
    if hasattr(bpy.types.Image, PROP):
        del bpy.types.Image.fss_orm_levels
    if _previews is not None:
        from bpy.utils import previews
        previews.remove(_previews)
        _previews = None
    _preview_state.clear()
    _histograms.clear()
