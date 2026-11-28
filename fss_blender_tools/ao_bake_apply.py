"""AO Bake, Apply (auto-bake journal, decisions 14, 19, 20, 22 to 28; P44, P45, P47): the masters copied into a texture.

Per texture set (a material, as UV Auto Packing groups them), for all texture sets, or for the selected objects:
- target: the red channel of the texture in the material's ORM slot, at its own size (green, blue and alpha byte for
  byte; an 8-bit file is reported and written as 16-bit with its values kept; a copy of the file is kept in the bake
  folder before the first write), or a separate file in the output folder: greyscale (the AO in R, G and B) or the ORM
  layout (the AO in red; green and blue white, or taken from the ORM slot's texture, resampled inside each island with
  a warning when the sizes differ);
- always 16-bit; the AO comes from the master, through the copy of the prototype (ao_bake_core.copy_master), with the
  padding of the scene setting;
- per object (P47): only the selected objects' faces and their padding are written, padding only into pixels of no
  other face of the texture set; every other pixel stays as it was. A separate file that does not exist yet is
  created white, green and blue as above;
- faces without an up-to-date master (missing, or the mesh changed) are written white and listed; faces whose master
  is under 4 x their density at the target's size are counted;
- paged (decision 33): a master is read through scratch files in the bake folder (deleted afterwards), the copy runs a
  band of target rows at a time, and the file is written row by row, so Apply needs no memory in proportion to a
  master.
Apply writes files only: no datablock is added to the .blend and no material is changed.

Material channels (decision 82): the albedo into the texture of the material's base colour slot, roughness and metal
into the green and blue of its ORM texture (AO stays in red), the emissive into the texture of its emissive slot, each
with its other channels and alpha byte for byte (Target ORM Texture: in place, a copy kept in the bake folder before
the first write, an 8-bit file written 16-bit with its values kept); with Target Separate File, <material>.albedo.png
and <material>.emissive.png in the output folder, and (decision 86) <material>.roughness.png and <material>.metal.png,
single-channel 16-bit grey files (black where nothing was written yet). The copy, padding, per-object rule and bands
are the AO's (no Soften); a channel whose mesh changed since its bake is applied anyway and reported (decision 85);
faces without a master of the channel keep their pixels in it, listed as the AO's missing faces are.
Decision 96: albedo and emissive follow their own Target (in place in the base colour or emissive slot's texture, or a
separate file), with their own output folder (empty: the AO's), file name, resolution and padding; roughness and metal
follow the AO's Target, folder, resolution and padding.

Fetch (decisions 93, 94; fetch_vertex_color): the other way, a master read at every face corner of the selected
objects into the colour attribute the vertex colour sources read; the masters are only read.
"""

import os
import shutil
import time

import bpy
import numpy as np

from . import ao_bake_core as core
from . import ao_bake_store as store

P_ORM = 'msfs_occlusion_metallic_roughness_texture'
P_BASE = 'msfs_base_color_texture'
P_EMIS = 'msfs_emissive_texture'
RESOLUTIONS = [str(1 << n) for n in range(8, 14)]
UNDER_TOLERANCE = 1e-3  # faces under 4 x: float32 UVs make equal densities differ by about 1e-7


def orm_image(material):
    image = getattr(material, P_ORM, None)
    return image if isinstance(image, bpy.types.Image) else None


def image_path(image):
    return os.path.normpath(bpy.path.abspath(image.filepath, library=image.library)) if image.filepath else ''


OWN_FOLDERS = ('curv', 'albedo', 'emis')  # decisions 54, 96: the files with an Output Folder of their own


def output_folder(scene, kind='ao'):
    """Where Apply writes separate files: the AO's Output Folder (also roughness and metal's); the curvature's, the
    albedo's and the emissive's own (empty: the AO's)."""
    folder = scene.fss_ao_bake.get(f'{kind}_output_folder', '') if kind in OWN_FOLDERS else ''
    folder = folder or scene.fss_ao_bake.output_folder
    if not folder:
        stem = os.path.splitext(os.path.basename(bpy.data.filepath))[0] if bpy.data.filepath else 'untitled'
        folder = f'//{stem}_ao/'
    return os.path.normpath(bpy.path.abspath(folder))


def orm_size(material):
    """(W, H) of the texture in the material's ORM slot (its file's header, else the image), or None."""
    orm = orm_image(material)
    if orm is None:
        return None
    path = image_path(orm)
    info = core.png_info(path) if path and os.path.isfile(path) else None
    if info is not None:
        return int(info[0]), int(info[1])
    w, h = orm.size[:]
    return (int(w), int(h)) if w and h else None


def existing_size(path):
    """(W, H) of the PNG at path, or None when there is no such file."""
    info = core.png_info(path) if os.path.isfile(path) else None
    return (int(info[0]), int(info[1])) if info is not None else None


def safe_name(material):
    return ''.join(c if (c.isalnum() or c in '-_.') else '_' for c in material.name)


def default_file_name(material):
    """Decision 111: <material>_COMP_RGB16.png (before it, <material>_ao.png)."""
    return safe_name(material) + '_COMP_RGB16.png'


def file_name(material, settings):
    name = settings.file_name.strip() if settings.file_name else ''
    if not name:
        name = default_file_name(material)
    if not name.lower().endswith('.png'):
        name += '.png'
    return name


def read_texture(path, threads=None):
    """(values (H, W, C) uint16 in the file's depth, bits, colour type): core.read_png (the C++ reader, every filter,
    on `threads`). PNGs it does not decode (a palette, interlace) are read through a temporary Blender image, removed
    again."""
    try:
        vals, bits, ct = core.read_png(path, threads=threads)
        if vals.ndim == 2:
            vals = vals[:, :, None]
        return vals, bits, ct
    except core.PngNotDecoded:
        info = core.png_info(path)
        if info is None:
            raise
        w, h, bits, ct, _il = info
        ch = {0: 1, 2: 3, 3: 3, 4: 2, 6: 4}[ct]
        image = bpy.data.images.load(path, check_existing=False)
        try:
            image.colorspace_settings.name = 'Non-Color'
            px = np.empty(w * h * 4, np.float32)
            image.pixels.foreach_get(px)
        finally:
            bpy.data.images.remove(image)
        px = px.reshape(h, w, 4)
        top = 65535.0 if bits == 16 else 255.0
        idx = {1: [0], 2: [0, 3], 3: [0, 1, 2], 4: [0, 1, 2, 3]}[ch]
        return np.rint(px[:, :, idx] * top).astype(np.uint16), bits, (2 if ct == 3 else ct)


class Target:
    """Where Apply writes for one texture set: the file, its size, its pixels before (uint16, 16-bit scale; None for a new`n    file, white)."""

    def __init__(self, scene, material, settings, per_object, folder):
        self.material = material
        self.warnings = []
        self.backup = None
        self.kind = settings.target
        orm = orm_image(material)
        self.orm_path = image_path(orm) if orm is not None else ''
        self.orm = None  # (values 16-bit scale (H, W, C), bits), read only when its pixels are needed
        self.orm_size = None  # (H, W)
        if self.orm_path and os.path.isfile(self.orm_path):
            info = core.png_info(self.orm_path)
            self.orm_size = (info[1], info[0]) if info else (orm.size[1], orm.size[0])
            needs = self.kind == 'ORM' or (settings.layout == 'ORM' and settings.green_blue == 'COPY')
            if needs:
                vals, bits, _ct = read_texture(self.orm_path, threads=int(scene.fss_ao_bake.threads))
                self.orm = (vals * np.uint16(257 if bits == 8 else 1), bits)
        if self.kind == 'ORM':
            if self.orm is None:
                raise ValueError(f'{material.name}: no texture file in the ORM slot')
            vals, bits = self.orm
            if vals.shape[2] < 3:
                raise ValueError(f'{material.name}: the ORM texture has {vals.shape[2]} channel(s), not RGB')
            self.path = self.orm_path
            self.H, self.W = vals.shape[:2]
            self.base = vals
            if bits == 8:
                self.warnings.append('the ORM file is 8-bit: written as 16-bit')
            backup_dir = os.path.join(folder, 'orm_backup')
            self.backup = os.path.join(backup_dir, os.path.basename(self.path))
            if not os.path.isfile(self.backup):
                os.makedirs(backup_dir, exist_ok=True)
                shutil.copy2(self.path, self.backup)
            self.layout = 'ORM'
            return
        self.layout = settings.layout
        self.path = os.path.join(output_folder(scene, getattr(settings, 'kind', 'ao')), file_name(material, settings))
        size = getattr(settings, 'size', None)  # (W, H): a measurement script's crop of a layout, never the panel
        info = core.png_info(self.path) if os.path.isfile(self.path) else None
        if size:
            self.W, self.H = int(size[0]), int(size[1])
        elif info is not None:  # the file is there: written at its own size (the panel shows it, no choice)
            self.W, self.H = int(info[0]), int(info[1])
        elif settings.resolution == 'ORM':
            if self.orm_size is not None:
                self.H, self.W = self.orm_size
            else:
                self.H = self.W = store.texture_size(material)
        else:
            self.H = self.W = int(settings.resolution)
        self.gb = settings.green_blue if self.layout == 'ORM' else 'AO'
        self.gb_values = (float(getattr(settings, 'orm_roughness', 1.0)),  # decision 98: Custom
                          float(getattr(settings, 'orm_metal', 0.0)))
        self.sampling = settings.sampling
        self.fills = ao_fills(scene, settings) if self.layout == 'ORM' else (False, False)  # decision 113
        if all(self.fills):  # both filled by their Apply: no choice made
            self.gb = 'WHITE'
        if self.gb == 'COPY' and self.orm is None:
            self.warnings.append('green and blue: no ORM texture to copy from, written white')
            self.gb = 'WHITE'
        if per_object and os.path.isfile(self.path):
            vals, bits, _ct = read_texture(self.path, threads=int(scene.fss_ao_bake.threads))
            if vals.shape[:2] != (self.H, self.W):
                raise ValueError(f'{self.path}: {vals.shape[1]} x {vals.shape[0]} px, the setting says '
                                 f'{self.W} x {self.H}')
            vals = vals * np.uint16(257 if bits == 8 else 1)
            if vals.shape[2] == 1:
                vals = np.repeat(vals, 3, axis=2)
            self.base = vals[:, :, :3] if vals.shape[2] != 4 else vals[:, :, :3]
            self.fresh = False
        else:
            self.base = None  # white, made a band at a time
            self.fresh = True

    def green_blue(self, labels):
        """Green and blue of a new ORM-layout file: white (None), the two Custom values (an array of 2, decision 98),
        or the ORM texture's (resampled inside islands); decision 113: a channel the roughness or metal Apply fills
        white (its pixels without a master stay white)."""
        gb = self._green_blue(labels)
        if gb is None or not any(self.fills):
            return gb
        gb = gb.copy()
        for c, filled in enumerate(self.fills):
            if filled:
                gb[..., c] = 65535
        return gb

    def _green_blue(self, labels):
        if self.layout == 'ORM' and self.gb == 'CUSTOM':
            return np.rint(np.clip(np.array(self.gb_values), 0, 1) * 65535.0).astype(np.uint16)
        if self.layout != 'ORM' or self.gb != 'COPY':
            return None
        src = self.orm[0][:, :, 1:3]
        if src.shape[:2] == (self.H, self.W):
            return src.copy()
        self.warnings.append(f'green and blue resampled from {src.shape[1]} x {src.shape[0]} to {self.W} x {self.H} '
                             f'px ({self.sampling.lower()}): the artist\'s roughness and metallic change')
        src_lab, dst_lab = labels()
        out = core.resample(src.astype(np.float64) / 65535.0, src_lab, dst_lab, self.sampling)
        return np.rint(np.clip(out, 0, 1) * 65535.0).astype(np.uint16)


CH_SLOTS = {'albedo': (P_BASE, 'base colour'), 'emis': (P_EMIS, 'emissive'), 'rough': (P_ORM, 'ORM'),
            'metal': (P_ORM, 'ORM')}
CH_COLUMNS = {'albedo': (0, 1, 2), 'emis': (0, 1, 2), 'rough': (1,), 'metal': (2,)}
CH_NEW = {'albedo': 65535, 'emis': 0, 'rough': 0, 'metal': 0}  # a new separate file where nothing is written
CH_FILES = {'albedo': '_ALBD_RGB16.png', 'emis': '.emissive.png', 'rough': '.roughness.png', 'metal': '.metal.png'}
ALBEDO_RGBA_FILE = '_ALBD_RGBA16.png'  # decision 111: the albedo's file with Alpha on


def albedo_alpha(material, settings=None):
    """Decision 111: whether the texture set's albedo has an alpha channel (its Albedo's Alpha switch)."""
    a = settings if settings is not None else getattr(material, 'fss_ao_apply', None)
    return bool(getattr(a, 'albedo_alpha', False))
CH_GREY = ('rough', 'metal')  # decision 86: their separate files are single-channel


CH_OWN = ('albedo', 'emis')  # decision 96: a Target, folder, file, resolution and padding of their own


def channel_file_name(material, kind):
    """Decisions 82, 86: <material>.emissive.png, .roughness.png or .metal.png (the name made safe as the AO's); decision
    111: the albedo <material>_ALBD_RGB16.png, or _ALBD_RGBA16.png with Alpha on."""
    if kind == 'albedo' and albedo_alpha(material):
        return safe_name(material) + ALBEDO_RGBA_FILE
    return safe_name(material) + CH_FILES[kind]


def channel_name(material, kind, settings=None):
    """Decision 96: the separate file's name of a channel: the albedo's and emissive's File (settings: the set's
    fss_ao_apply unless given), else the default; roughness and metal always the default."""
    a = settings if settings is not None else getattr(material, 'fss_ao_apply', None)
    name = (getattr(a, f'{kind}_file_name', '') or '').strip() if kind in CH_OWN and a is not None else ''
    name = name or channel_file_name(material, kind)
    return name if name.lower().endswith('.png') else name + '.png'


def channel_in_place(settings, kind):
    """Decision 96: whether a channel is written in place: albedo and emissive by their own Target (SLOT), roughness
    and metal by the AO's (ORM). Settings without the channel's own Target (a script's) follow the AO's."""
    own = getattr(settings, f'{kind}_target', None) if kind in CH_OWN else None
    return own == 'SLOT' if own is not None else settings.target == 'ORM'


def channel_into_ao(settings, kind):
    """Decision 113: roughness and metal into the green and blue of the AO's Separate File when its Channels are Red
    (ORM), instead of a grey file of their own."""
    return (kind in ('rough', 'metal') and getattr(settings, 'target', None) == 'FILE'
            and getattr(settings, 'layout', None) == 'ORM')


def ao_fills(scene, settings):
    """Decision 113: (green, blue) of the AO's Separate File that the roughness and metal Apply fill (ticked under
    Run): the Green and Blue choice gives only the others."""
    s = scene.fss_ao_bake
    return tuple(bool(getattr(s, f'apply_{g}', False)) and channel_into_ao(settings, g) for g in ('rough', 'metal'))


def channel_padding(scene, kind):
    """Decision 96: the albedo's and emissive's own Padding, else the AO's."""
    s = scene.fss_ao_bake
    return int(getattr(s, f'{kind}_padding') if kind in CH_OWN else s.padding)


class ChannelTarget:
    """Where Apply writes a material channel of one texture set (decision 82): the file, its size, its pixels before
    (uint16, 16-bit scale) and the columns the channel's components go into. In place (channel_in_place): the slot's
    texture; Separate File: the channel's file in the output folder (roughness and metal: a grey file of their own,
    decision 86; albedo and emissive: their own folder, name and resolution, decision 96)."""

    def __init__(self, scene, material, settings, folder, kind):
        self.material, self.channel = material, kind
        self.warnings, self.backup = [], None
        self.cols = CH_COLUMNS[kind]
        # decision 111: the albedo's alpha into the fourth column, with the set's Alpha on
        self.alpha = kind == 'albedo' and albedo_alpha(material, settings)
        in_place = channel_in_place(settings, kind)
        into_ao = not in_place and channel_into_ao(settings, kind)  # decision 113
        self.kind = ('SLOT' if kind in CH_OWN else 'ORM') if in_place else 'COMP' if into_ao else 'FILE'
        self.layout = kind
        threads = int(scene.fss_ao_bake.threads)
        prop, slot = CH_SLOTS[kind]
        if into_ao:  # decision 113: the AO's Separate File (Red (ORM)), its green or blue; new: white
            path = os.path.join(output_folder(scene), file_name(material, settings))
            if os.path.isfile(path):
                vals, bits, _ct = read_texture(path, threads=threads)
                vals = vals * np.uint16(257 if bits == 8 else 1)
                if vals.shape[2] < 3:
                    vals = np.repeat(vals[:, :, :1], 3, axis=2)
                self.base = vals
            else:
                if settings.resolution == 'ORM':
                    size = orm_size(material)
                    W, H = size if size is not None else (store.texture_size(material),) * 2
                else:
                    W = H = int(settings.resolution)
                self.base = np.full((int(H), int(W), 3), 65535, np.uint16)
        elif in_place:
            image = getattr(material, prop, None)
            path = image_path(image) if isinstance(image, bpy.types.Image) else ''
            if not path or not os.path.isfile(path):
                raise ValueError(f'{material.name}: no texture file in the {slot} slot')
            vals, bits, _ct = read_texture(path, threads=threads)
            if vals.shape[2] < 3:
                raise ValueError(f'{material.name}: the {slot} texture has {vals.shape[2]} channel(s), not RGB')
            if bits == 8:
                self.warnings.append(f'the {slot} file is 8-bit: written as 16-bit')
            if self.alpha and vals.shape[2] < 4:  # the artist's texture keeps its format
                self.warnings.append(f'the {slot} texture has no alpha channel: the alpha is not written')
                self.alpha = False
            self.base = vals * np.uint16(257 if bits == 8 else 1)
            backup_dir = os.path.join(folder, 'orm_backup' if prop == P_ORM else f'{kind}_backup')
            self.backup = os.path.join(backup_dir, os.path.basename(path))
            if not os.path.isfile(self.backup):
                os.makedirs(backup_dir, exist_ok=True)
                shutil.copy2(path, self.backup)
        else:
            grey = kind in CH_GREY  # decision 86: one channel, PNG colour type 0
            if grey:
                self.cols = (0,)
            nch = 1 if grey else 4 if self.alpha else 3
            own = kind in CH_OWN
            path = os.path.join(output_folder(scene, kind if own else 'ao'),
                                channel_name(material, kind, settings if own else None))
            if os.path.isfile(path):
                vals, bits, _ct = read_texture(path, threads=threads)
                vals = vals * np.uint16(257 if bits == 8 else 1)
                if vals.shape[2] < 3 and not grey:
                    vals = np.repeat(vals[:, :, :1], 3, axis=2)
                if nch == 4 and vals.shape[2] == 3:  # decision 111: an RGB file given an opaque alpha
                    vals = np.concatenate([vals, np.full(vals.shape[:2] + (1,), 65535, np.uint16)], axis=2)
                self.base = vals[:, :, :nch].copy() if vals.shape[2] != nch else vals
            else:
                res = (getattr(settings, f'{kind}_resolution', None) if own else None) or settings.resolution
                if res == 'ORM':
                    size = orm_size(material)
                    W, H = size if size is not None else (store.texture_size(material),) * 2
                else:
                    W = H = int(res)
                self.base = np.full((int(H), int(W), nch), CH_NEW[kind], np.uint16)
        if self.alpha:  # decision 111: a new file's alpha opaque where nothing is written
            self.cols = CH_COLUMNS[kind] + (3,)
        self.path = path
        self.H, self.W = self.base.shape[:2]

    def write_steps(self, Qs, written, threads, masks=None):
        """The file with the components Qs where written, every other pixel and channel as it was; a generator of
        'write' steps. Returns the PNG writer's `by`."""
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        H, W, C = self.base.shape
        tmp = self.path + '.tmp'
        writer = core.png_writer(tmp, W, H, 16, C, threads=threads)
        try:
            for top in range(0, H, 256):  # rows from the top
                yield 'write', top, H, os.path.basename(self.path)
                r0, r1 = H - min(H, top + 256), H - top
                vals = self.base[r0:r1].copy()
                wr = written[r0:r1]
                for i, (q, col) in enumerate(zip(Qs, self.cols)):  # decision 111: a component's own mask
                    m_ = masks[i][r0:r1] if masks is not None and masks[i] is not None else wr
                    vals[:, :, col] = np.where(m_, q[r0:r1], vals[:, :, col])
                writer.write(vals[::-1])
            writer.close()
        except BaseException:
            writer.abort()
            raise
        os.replace(tmp, self.path)
        return writer.by


def channel_problem(folder, stem, entry, kind, material, ev):
    """Decision 82: why a master's channel is not applied to these faces ('' when it is): missing, or skipped for this
    texture set (no Principled BSDF); 'mesh changed' when stale (decision 85: applied anyway, reported)."""
    c = ((entry or {}).get('channels') or {}).get(kind)
    _img, mp, npz = core.master_paths(folder, stem)
    if not c or not all(os.path.isfile(p) for p in core.channel_paths(folder, stem, kind) + [mp, npz]):
        return 'missing'
    if material.name in (c.get('skipped') or ()):
        return 'no Principled BSDF'
    if c.get('mesh_hash') != core.mesh_hash(ev):
        return 'mesh changed'
    return ''


GONE = 'not found (renamed or deleted since the last Refresh)'


def _set_tris(item, material, depsgraph):
    """The item's first user evaluated now, and the triangles (all of them) whose material is `material`; another
    user of its mesh when that one was renamed or deleted since the last Refresh; (None, None, None, None) when none
    is left (the master is skipped and reported, not an error that stops the Apply)."""
    obj = None
    for name in [item['object']] + list(item.get('users') or ()):
        o = bpy.data.objects.get(name)
        if o is not None and o.type == 'MESH' and o.data is not None:
            obj = o
            break
    if obj is None:
        return None, None, None, None
    uv = obj.data.uv_layers.active.name if obj.data.uv_layers.active else item['uv']
    ev = core.evaluated_triangles(obj, depsgraph, [uv])
    slots = [slot.material for slot in obj.material_slots]
    match = np.array([s == material for s in slots] + [False], bool)
    in_set = match[np.minimum(ev['mat'], len(match) - 1)]
    return obj, ev, ev['uv'].get(uv), in_set


def _overlap(a, b):
    """The overlap of two crops (x0, y0, w, h), or None."""
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    return (x0, y0, x1 - x0, y1 - y0) if x1 > x0 and y1 > y0 else None


def _crop(uvpx, W, H, border):
    x0, y0, w, h = core.crop_box(uvpx, border)
    x1, y1 = min(W, x0 + w), min(H, y0 + h)
    x0, y0 = max(0, x0), max(0, y0)
    return x0, y0, max(0, x1 - x0), max(0, y1 - y0)


APPLY_BAND = 256  # target rows copied at a time (Session 23); the result does not depend on it


def _quantize(values):
    return np.rint(np.clip(values, 0, 1) * 65535.0).astype(np.uint16)


def _finish(gen):
    """Runs a step generator to its end; its return value."""
    while True:
        try:
            next(gen)
        except StopIteration as stop:
            return stop.value


def apply_set(context, material, objects=None, settings=None, band_rows=APPLY_BAND, kind='ao'):
    """Apply for one texture set in one go (apply_set_steps run to its end). Returns the report."""
    return _finish(apply_set_steps(context, material, objects, settings, band_rows, kind))


def _chan_open(folder, stem, kind, threads, extra=False):
    """Decision 82: the master's images of a material channel, paged, all open at once (each with its own map page);
    None when one is missing (those opened are closed). extra (decision 111): its optional components too, where the
    master has them (the albedo's alpha), after the others."""
    out = []
    try:
        opt = core.CHANNEL_EXTRA.get(kind, ()) if extra else ()
        for comp in core.CHANNEL_KINDS[kind] + opt:
            if comp in opt and not os.path.isfile(core.image_paths(folder, stem, comp)[0]):
                continue
            m = core.open_master(folder, stem, kind=comp, threads=threads, map_page=f'.{comp}.mappage')
            if m is None:
                for o in out:
                    o['close']()
                return None
            out.append(m)
    except BaseException:
        for o in out:
            o['close']()
        raise
    return out


def default_curvature_name(material):
    """Decision 54: a texture set's curvature file, unless the set names its own."""
    return ''.join(c if (c.isalnum() or c in '-_.') else '_' for c in material.name) + '_curvature.png'


def curvature_name(material):
    """The set's curvature file name (its File under Curvature Map, else <material>_curvature.png)."""
    a = getattr(material, 'fss_ao_apply', None)
    name = (getattr(a, 'curv_file_name', '') or '').strip() if a is not None else ''
    name = name or default_curvature_name(material)
    return name if name.lower().endswith('.png') else name + '.png'


def curvature_settings(settings, material):
    """The curvature file: a separate grey file with its own name, size and folder (the Curvature Map rows; settings
    without them, as scripts pass: the AO settings' size), the AO settings' sampling."""
    from types import SimpleNamespace
    res = getattr(settings, 'curv_resolution', None)  # the panel's set; a script's settings: the AO size
    return SimpleNamespace(target='FILE', file_name=curvature_name(material), resolution=res or settings.resolution,
                           layout='GREY', green_blue='WHITE', sampling=settings.sampling, kind='curv')


CURV_MIN_PX = 2.0  # decision 55: a curvature band narrower than this many texture pixels fades in the file


def narrow_islands(pos_w, ev, tris, uvpx, W, H, width, threads=None):
    """Decision 55: the UV islands (of these triangles, uvpx in target pixels) where the curvature width covers fewer
    than CURV_MIN_PX texture pixels: (count, islands, their share of the 3D area, the width that reaches CURV_MIN_PX on
    every island), or None when none. threads: the UV islands' in C++ (core.uv_islands)."""
    if not len(tris):
        return None
    a3 = core.tri_areas_3d(pos_w, tris)
    a2 = np.abs(core.tri_areas_2d(uvpx))
    isl = core.uv_islands(core.weld_ids(ev['co'])[tris], uvpx / np.array([W, H], dtype=np.float64), threads=threads)
    n = int(isl.max()) + 1
    A3, A2 = np.bincount(isl, a3, n), np.bincount(isl, a2, n)
    ok = (A3 > 1e-16) & (A2 > 0)
    dens = np.zeros(n)
    dens[ok] = np.sqrt(A2[ok] / A3[ok])  # px per m of each island
    bad = ok & (width * dens < CURV_MIN_PX)
    if not bad.any():
        return None
    return (int(bad.sum()), int(ok.sum()), float(A3[bad].sum() / A3[ok].sum()),
            float(CURV_MIN_PX / dens[bad].min()))


def apply_set_steps(context, material, objects=None, settings=None, band_rows=APPLY_BAND, kind='ao',
                    ctx_cache=None):
    """Apply for one texture set; objects: the selected objects (per-object Apply, P47) or None for the whole set.
    settings: the material's fss_ao_apply or an object with the same attributes. A generator (decision 45): it yields
    (phase, done, total, name) between pieces of work (a master, a band of its copy, a strip of the file), so the
    panel's modal Apply shows progress and can stop; closing it early writes nothing (the file is written to a .tmp
    and replaced at the end). Returns the report. kind 'curv' (decision 54): the curvature masters into the set's
    curvature file (a separate grey file, flat grey where no master is), with its own folder, name and size (the
    Curvature Map rows), no softening.

    Paged (decision 33, Session 23): one master at a time is open, paged (ao_bake_core.open_master: decoded once into
    scratch files in the bake folder, deleted afterwards, read through a cache of tiles); the copy runs a band of
    band_rows target rows at a time (with a halo for the padding); the file is written row by row. Held for the whole
    target: the AO (uint16) and three masks, 8 bytes per target pixel; nothing in proportion to a master.

    kind 'albedo', 'rough', 'metal' or 'emis' (decision 82): a material channel into its target (ChannelTarget), its
    components' masters open at once; faces without an up-to-date master of the channel keep their pixels.
    ctx_cache: a dict shared by the channels of an Apply, so a master's copy_context is computed once per texture set
    and target size."""
    t0 = time.time()
    why = core.native_copy().unavailable()  # apply-native-copy decision 6: the DLL and libjxl are required
    if why:
        return dict(material=material.name, error=f'AO Bake not available: {why}')
    scene = context.scene
    folder = store.bake_folder()
    settings = settings or material.fss_ao_apply
    curv = kind == 'curv'
    chan = kind in core.CHANNEL_KINDS  # decision 82: a material channel
    comps = core.CHANNEL_KINDS[kind] if chan else (kind,)
    if curv:
        settings = curvature_settings(settings, material)
    # decision 96: the albedo and emissive with their own padding
    pad = int(scene.fss_ao_bake.curv_padding) if curv else channel_padding(scene, kind) if chan else int(
        scene.fss_ao_bake.padding)
    # decision 46: the darker side of convex sharp edges brightened toward the edge (m; at least a texel), or None
    soften_width = (float(scene.fss_ao_bake.soften_width) if scene.fss_ao_bake.soften_edges and not curv and not chan
                    else None)
    fill = core.CURV_FLAT if curv else 65535  # where no master is
    # decision 106: the AO's darkening scaled toward white (1.0: as baked), after Soften
    strength = 1.0 if curv or chan else float(scene.fss_ao_bake.ao_strength)
    threads = int(scene.fss_ao_bake.threads)  # the C++ work's threads (ao_bake_copy.threads_of: 0 is Auto)
    row = store._state['sets'].get(material.name)
    if row is None:
        return dict(material=material.name, error='not in the last Refresh (press Refresh)')
    stems = row['items']
    chosen = stems if objects is None else [s for s in store.items_for_objects(objects) if s in stems]
    if objects is not None and not chosen:
        return dict(material=material.name, error='no selected object in this texture set')
    target = (ChannelTarget(scene, material, settings, folder, kind) if chan
              else Target(scene, material, settings, objects is not None, folder))
    W, H = target.W, target.H
    masters = store.read_index(folder).get('masters', {}) if folder else {}
    depsgraph = context.evaluated_depsgraph_get()
    report = dict(material=material.name, path=target.path, size=[W, H], target=target.kind, layout=target.layout,
                  copied=[], white=[], outdated=[], mesh_changed=[], narrow=[], faces_under_4x=0, faces=0, stacked_px=0, softened_px=0,
                  soften_mm=None if soften_width is None else round(soften_width * 1000, 3), warnings=target.warnings,
                  strength=None if strength == 1.0 else round(strength, 4),
                  backup=target.backup, per_object=objects is not None, band_rows=int(band_rows), copy=None, open=None,
                  png=None, object_uv=[])
    copies = {}  # the copy's threads (apply-native-copy journal: C++)
    opens = {}  # who opened the masters (apply-native-copy journal, Session 4): 'C++ (n threads)'
    pending = []  # padding (flat index, values per component, step), written once every face of the set is known
    written = np.zeros((H, W), bool)
    cover = np.zeros((H, W), bool)
    pad_step = np.full((H, W), 1 << 30, np.int32)
    alpha = chan and target.alpha  # decision 111: the albedo's alpha too, where a master has it
    if alpha:
        comps = comps + core.CHANNEL_EXTRA[kind]
    written_a = np.zeros((H, W), bool) if alpha else None
    Qs = [np.zeros((H, W), np.uint16) for _c in comps]  # the AO (a channel's components) where written
    Q = Qs[0]
    label_parts = []
    halo = pad + 2  # the padding grows `pad` px: a band copied with this halo equals the whole crop's copy

    def bands(crop):
        x0, y0, w, h = crop
        for yb in range(y0, y0 + h, band_rows):
            yield yb, min(y0 + h, yb + band_rows), max(y0, yb - halo), min(y0 + h, yb + band_rows + halo)

    # Session 54: with the selection applied, the other objects of the set matter only where the applied objects'
    # padding can go, inside the applied objects' crops: their faces are rasterized there only
    near = None
    if objects is not None:
        near = []
        for stem in chosen:
            _o, ev_c, uv_c, in_c = _set_tris(store._state['items'][stem], material, depsgraph)
            if uv_c is not None and in_c.any():
                near.append(_crop(uv_c[np.nonzero(in_c)[0]] * np.array([W, H], dtype=np.float64), W, H, pad + 4))
            del ev_c, uv_c, in_c
    for k, stem in enumerate(stems):
        item = store._state['items'][stem]
        yield 'master', k, len(stems), item['name']
        obj, ev, uv, in_set = _set_tris(item, material, depsgraph)
        if obj is None:  # gone since the last Refresh: its faces keep their pixels, reported
            if stem in chosen:
                report['white'].append((item['name'], GONE, 0))
            continue
        if uv is None or not in_set.any():
            continue
        tri_ids = np.nonzero(in_set)[0]
        uvpx_all = uv * np.array([W, H], dtype=np.float64)
        label_parts.append((uv[tri_ids], ev, tri_ids))
        crop = _crop(uvpx_all[tri_ids], W, H, pad + 4)
        x0, y0, w, h = crop
        if w <= 0 or h <= 0:
            continue
        mine = stem in chosen
        if mine and chan:  # decision 82: without an up-to-date master of the channel the faces keep their pixels
            report['faces'] += int(len(np.unique(ev['poly'][tri_ids])))
            entry = masters.get(stem)
            why = channel_problem(folder, stem, entry, kind, material, ev)
            if why == 'mesh changed':  # decision 85: applied anyway, as the AO (decision 73)
                report['mesh_changed'].append(item['name'])
                why = ''
            usable = not why
            if why:
                report['white'].append((item['name'], why, int(len(np.unique(ev['poly'][tri_ids])))))
        elif mine:
            report['faces'] += int(len(np.unique(ev['poly'][tri_ids])))
            entry = masters.get(stem)
            # decision 73: a master whose mesh changed since its bake is applied anyway (reported); white only
            # where there is no master
            # decision 6: a master the C++ code does not read (a PNG image, schema 1) is white, to be baked again
            unreadable = entry is not None and bool(core.master_unreadable(folder, stem)
                                                    or (curv and core.master_unreadable(folder, stem, 'curv')))
            usable = entry is not None and not unreadable and store.has_files(folder, stem)
            if curv and usable and not os.path.isfile(core.master_paths(folder, stem, 'curv')[0]):
                usable = False
            if not usable:
                why = (core.REBAKE if unreadable else 'missing' if entry is None or not store.has_files(folder, stem)
                       else 'no curvature baked')
                report['white'].append((item['name'], why, int(len(np.unique(ev['poly'][tri_ids])))))
            elif entry.get('mesh_hash') != core.mesh_hash(ev):
                report['mesh_changed'].append(item['name'])
        # the faces of the set (also of the objects not chosen): no padding goes there; an object not chosen only
        # where it overlaps an applied object's crop (Session 54)
        windows = [crop] if mine or near is None else [r for r in (_overlap(crop, c) for c in near) if r]
        for wx0, _wy0, ww, _wh in windows:
            for yb, yb1, _h0, _h1 in bands((wx0, _wy0, ww, _wh)):
                own, _cnt = core.raster_window(uvpx_all[tri_ids], ww, yb1 - yb, 1, wx0, yb, threads=threads)
                inside = own >= 0
                cover[yb:yb1, wx0:wx0 + ww] |= inside
                if mine and not usable and not chan:
                    Q[yb:yb1, wx0:wx0 + ww][inside] = fill
                    written[yb:yb1, wx0:wx0 + ww] |= inside
                del own, _cnt
        if not mine or not usable:
            continue
        if entry.get('surround_hash') != item['surround_hash'] and not curv and not chan:
            report['outdated'].append(item['name'])
        baked_w = (entry.get('curvature') or {}).get('width')
        if curv and baked_w is not None and baked_w != round(float(scene.fss_ao_bake.curv_width), 6):
            report['warnings'].append(f"{item['name']}: curvature baked at {entry['curvature']['width'] * 1000:g} mm, "
                                      f"the setting is {scene.fss_ao_bake.curv_width * 1000:g} mm (re-bake)")
        why = 'missing'
        try:
            if chan:  # decision 82: the channel's components open at once, each with its own map page
                cmasters = _chan_open(folder, stem, kind, int(scene.fss_ao_bake.threads), extra=alpha)
                master = cmasters[0] if cmasters else None
            else:
                master = core.open_master(folder, stem, kind=kind, threads=int(scene.fss_ao_bake.threads))
                cmasters = [master]
        except core.MasterUnreadable:  # replaced by one the C++ code does not read since Refresh (decision 6)
            master, why = None, core.REBAKE
        if master is None:  # the files went away since Refresh: white, as a missing master
            report['white'].append((item['name'], why, int(len(np.unique(ev['poly'][tri_ids])))))
            if chan:  # a channel's faces keep their pixels
                continue
            for yb, yb1, _h0, _h1 in bands(crop):
                own, _cnt = core.raster_window(uvpx_all[tri_ids], w, yb1 - yb, 1, x0, yb, threads=threads)
                Q[yb:yb1, x0:x0 + w][own >= 0] = fill
                written[yb:yb1, x0:x0 + w] |= own >= 0
            continue
        if master.get('open'):
            opens.setdefault(master['open'], None)
        try:
            src = master['tri_src']
            if len(src) and int(src.max()) >= len(ev['tris']):  # decision 73: fewer triangles than baked
                report['white'].append((item['name'], 'triangles changed', int(len(np.unique(ev['poly'][tri_ids])))))
                if chan:  # a channel's faces keep their pixels
                    continue
                for yb, yb1, _h0, _h1 in bands(crop):
                    own, _cnt = core.raster_window(uvpx_all[tri_ids], w, yb1 - yb, 1, x0, yb, threads=threads)
                    Q[yb:yb1, x0:x0 + w][own >= 0] = fill
                    written[yb:yb1, x0:x0 + w] |= own >= 0
                continue
            pos_w, cn_w = core.to_world(ev)
            tris = ev['tris'][src]
            uvpx = uvpx_all[src]
            sel = in_set[src]
            uvpx = np.where(sel[:, None, None], uvpx, -1e6)
            tisl = np.zeros(len(tris), np.int64)
            ck = (material.name, stem, W, H)  # decision 82: one copy_context for a set's channels at this size
            ctx = ctx_cache.get(ck) if ctx_cache is not None and chan else None
            if ctx is None:
                ctx = core.copy_context(pos_w, tris, uvpx, master, core.K_MIN, core.K_MAX)
                if ctx_cache is not None and chan:
                    ctx_cache[ck] = ctx
            sctx = (core.soften_context(pos_w, tris, uvpx, ctx, soften_width, use=sel, cn=cn_w[src])
                    if soften_width is not None else None)
            box = _object_uv_box_ok(master, uvpx, sel)  # decision 107
            if box is not None:
                report['warnings'].append(f"{item['name']}: {box}")
                box = False
            else:
                box = bool((master.get('meta') or {}).get('object_uv'))
                if box:
                    report['object_uv'].append(item['name'])
            for yb, yb1, hy0, hy1 in bands(crop):
                yield 'master', k + (yb - y0) / max(h, 1), len(stems), item['name']
                outs = []
                for cm_ in cmasters:  # the AO's one master, or a channel's components (the same layout)
                    out, info, owner_c, steps, count_c = core.copy_master(
                        pos_w, tris, uvpx, tisl, cm_, (x0, hy0, w, hy1 - hy0), core.K_MIN, pad, outside_mode='tri',
                        kmax=core.K_MAX, surface_cos=core.SURFACE_COS, same_face=False, ctx=ctx, soften=sctx,
                        threads=int(scene.fss_ao_bake.threads), edge_filter=scene.fss_ao_bake.edge_filter)
                    outs.append(out)
                if box:  # decision 107: each covered texel the mean of its block of master pixels (no Soften)
                    jj, ii = np.nonzero(owner_c >= 0)
                    for o_, cm_ in zip(outs, cmasters):
                        v_, n_ = core.object_uv_box(cm_, uvpx, ii + x0, jj + hy0, threads=int(scene.fss_ao_bake.threads))
                        got = n_ > 0
                        o_[jj[got], ii[got]] = v_[got]
                if strength != 1.0:  # decision 106: -1 (no value) stays
                    outs = [np.where(o_ >= 0, 1.0 - strength * (1.0 - o_), o_) for o_ in outs]
                copies.setdefault(info['copy'], info['copy_threads'])
                r = slice(yb - hy0, yb1 - hy0)
                outs, owner_c, steps = [o_[r] for o_ in outs], owner_c[r], steps[r]
                out = outs[0]
                report['stacked_px'] += int((count_c[r] > 1).sum())
                report['softened_px'] += int(info.get('softened_px', 0))
                inside = (owner_c >= 0) & (out >= 0)
                for q_, o_ in zip(Qs, outs):
                    q_[yb:yb1, x0:x0 + w][inside] = _quantize(o_[inside])
                written[yb:yb1, x0:x0 + w] |= inside
                if alpha and len(outs) == len(Qs):  # decision 111: this master has the alpha
                    written_a[yb:yb1, x0:x0 + w] |= inside
                padm = (owner_c < 0) & (steps > 0) & (steps <= pad) & (out >= 0)
                jj, ii = np.nonzero(padm)
                if len(jj):
                    pending.append(((jj + yb) * W + ii + x0, [_quantize(o_[jj, ii]) for o_ in outs],
                                    steps[jj, ii].astype(np.int32)))
                del out, outs, owner_c, steps, count_c, padm
            report['copied'].append(item['name'])
            # faces under 4 x: the master's density against each face's density at the target's size
            d = core.densities(pos_w, tris[sel], uvpx[sel])
            low = (d > 0) & (master['density'] < 4.0 * d * (1 - UNDER_TOLERANCE))
            report['faces_under_4x'] += int(len(np.unique(ev['poly'][src[sel][low]])))
            if curv:  # decision 55: islands where the width is under CURV_MIN_PX texture pixels
                got = narrow_islands(pos_w, ev, tris[sel], uvpx[sel], W, H,
                                     float(baked_w if baked_w is not None else scene.fss_ao_bake.curv_width),
                                     threads=threads)
                if got:
                    report['narrow'].append((item['name'],) + got)
            report.setdefault('page_loads', []).append([int(p.loads) for p in master.get('pages', ())])
        finally:
            for cm_ in cmasters:
                cm_['close']()
    # padding only where no face of the set lies (P47), the nearest island's first
    flat_cover, flat_step, flat_w = cover.ravel(), pad_step.ravel(), written.ravel()
    flat_qs = [q_.ravel() for q_ in Qs]
    flat_wa = written_a.ravel() if alpha else None
    for idx, vals_, st in pending:
        take = ~flat_cover[idx] & (st < flat_step[idx])
        for fq, val in zip(flat_qs, vals_):
            fq[idx[take]] = val[take]
        flat_step[idx[take]] = st[take]
        flat_w[idx[take]] = True
        if alpha:  # decision 111: the nearest island's alpha, or none where it has none
            flat_wa[idx[take]] = len(vals_) == len(Qs)
    del pending, cover, pad_step
    if chan:  # decision 82: the components into their columns of the target, the rest as it was
        masks = [None] * (len(Qs) - 1) + [written_a] if alpha else None
        report['png'] = yield from target.write_steps(Qs, written, threads, masks)
        if alpha:
            report['alpha_px'] = int(written_a.sum())
        for image in bpy.data.images:
            if image.source == 'FILE' and image_path(image) == os.path.normpath(target.path) and not image.is_dirty:
                image.reload()
        report.update(written_px=int(written.sum()), seconds=round(time.time() - t0, 2), kind=kind)
        if copies:
            report['copy'] = ' and '.join(f"C++ ({v} thread{'s' if v != 1 else ''})"
                                          for _k, v in sorted(copies.items()))
        if opens:
            report['open'] = ' and '.join(sorted(opens))
        return report

    def labels():
        parts_src, parts_dst = [], []
        Hs, Ws = target.orm[0].shape[:2]
        for uv_t, ev, tri_ids in label_parts:
            wt = core.weld_ids(ev['co'])[ev['tris'][tri_ids]]
            isl = core.uv_islands(wt, uv_t, threads=threads)
            parts_src.append((uv_t * np.array([Ws, Hs]), isl))
            parts_dst.append((uv_t * np.array([W, H]), isl))
        return (core.island_labels(parts_src, Ws, Hs, pad * max(Ws / W, 1), threads=threads),
                core.island_labels(parts_dst, W, H, pad, threads=threads))

    gb = target.green_blue(labels) if target.kind != 'ORM' and target.fresh and target.layout == 'ORM' else None
    if target.kind != 'ORM':
        os.makedirs(os.path.dirname(target.path), exist_ok=True)
    channels = target.base.shape[2] if target.base is not None else 3
    tmp = target.path + '.tmp'
    # apply-native-copy journal decisions 4 and 6: the C++ writer
    writer = core.png_writer(tmp, W, H, 16, channels, threads=int(scene.fss_ao_bake.threads))
    report['png'] = writer.by
    try:
        for top in range(0, H, 256):  # rows from the top
            yield 'write', top, H, os.path.basename(target.path)
            r0, r1 = H - min(H, top + 256), H - top
            if target.base is not None:
                vals = target.base[r0:r1].copy()
            else:
                vals = np.full((r1 - r0, W, 3), fill, np.uint16)
                if gb is not None:
                    vals[:, :, 1:3] = gb if gb.ndim == 1 else gb[r0:r1]
            wr = written[r0:r1]
            vals[:, :, 0] = np.where(wr, Q[r0:r1], vals[:, :, 0])
            if target.kind != 'ORM' and target.layout == 'GREY':
                for c in (1, 2):
                    vals[:, :, c] = np.where(wr, Q[r0:r1], vals[:, :, c])
            writer.write(vals[::-1])
        writer.close()
    except BaseException:
        writer.abort()
        raise
    os.replace(tmp, target.path)
    for image in bpy.data.images:
        if image.source == 'FILE' and image_path(image) == os.path.normpath(target.path) and not image.is_dirty:
            image.reload()
    report.update(written_px=int(written.sum()), seconds=round(time.time() - t0, 2), kind=kind)
    if copies:
        report['copy'] = ' and '.join(f"C++ ({v} thread{'s' if v != 1 else ''})" for _k, v in sorted(copies.items()))
    if opens:
        report['open'] = ' and '.join(sorted(opens))
    return report


def apply(context, materials, objects=None):
    """Apply in one go (apply_steps run to its end). Returns the reports."""
    return _finish(apply_steps(context, materials, objects))


def apply_steps(context, materials, objects=None):
    """Apply for several texture sets as a generator (decision 45): yields (set index, number of sets, material name,
    fraction of this set done, what is being done); returns the reports. A set's error becomes its report."""
    reports = []
    n = len(materials)
    s = context.scene.fss_ao_bake
    kinds = (['ao'] if s.apply_ao else []) + (['curv'] if s.apply_cm else [])  # decisions 54, 55
    kinds += [g for g in core.CHANNEL_GROUPS if getattr(s, f'apply_{g}', False)]  # decision 82
    # decision 110: a set of Skip-AO-Bake objects only (decision 112) takes the material channels alone
    jobs = [(m, k) for m in materials for k in kinds
            if not (k in ('ao', 'curv') and (store._state['sets'].get(m.name) or {}).get('channels_only'))]
    n = len(jobs)
    ctx_cache = {}  # decision 82: a master's copy_context once for a texture set's channels
    for i, (material, kind) in enumerate(jobs):
        gen = apply_set_steps(context, material, objects, kind=kind, ctx_cache=ctx_cache)
        try:
            while True:
                try:
                    phase, done, total, name = next(gen)
                except StopIteration as stop:
                    reports.append(stop.value)
                    break
                if phase == 'master':
                    frac, what = 0.9 * done / max(total, 1), f'Master {int(done) + 1} of {total}: {name}'
                else:
                    frac, what = 0.9 + 0.1 * done / max(total, 1), f'Writing {name}'
                yield i, n, material.name, frac, what
        except Exception as exc:  # the set's error is its report; the other sets are applied
            reports.append(dict(material=material.name, error=f'{type(exc).__name__}: {exc}'
                                if not isinstance(exc, (ValueError, OSError)) else str(exc)))
        finally:
            gen.close()  # on Cancel: the set's master and its .tmp file closed and removed now
    return reports


def _object_uv_box_ok(master, uvpx, sel):
    """Decision 107: None when the master is not an Object UV one or its UVs equal the object's now (Apply then
    averages each texel's block), else why it is copied face by face instead."""
    ouv = (master.get('meta') or {}).get('object_uv')
    if not ouv:
        return None
    sel = np.asarray(sel, bool) & (np.asarray(master['island']) >= 0)  # degenerate triangles have no island
    now = (np.asarray(uvpx, np.float64) * float(ouv['scale']) - core.object_uv_offsets(master)[:, None, :])[sel]
    was = np.asarray(master['muv'], np.float64)[sel]
    if now.shape != was.shape or (len(now) and float(np.abs(now - was).max()) > 1e-3):
        return 'Object UV master baked for other UVs or another texture size: copied face by face (re-bake)'
    return None


def report_lines(rep):
    if rep.get('error'):
        return [f"{rep['material']}: {rep['error']}"]
    chan = rep.get('kind') in core.CHANNEL_KINDS
    what = f" {core.CHANNEL_NAMES[rep['kind']]}" if chan else ''
    lines = [f"{rep['material']}{what}: {os.path.basename(rep['path'])} {rep['size'][0]} x {rep['size'][1]}, "
             f"{len(rep['copied'])} copied, {rep['written_px']} px, {rep['seconds']} s"]
    if rep['white']:
        word = 'kept' if chan else 'flat' if rep.get('kind') == 'curv' else 'white'
        lines.append(f"  {word} (no up-to-date master): "
                     + ', '.join(f'{n} ({why})' for n, why, _f in rep['white']))
    if rep.get('mesh_changed'):
        lines.append('  mesh changed since its bake, applied anyway: ' + ', '.join(rep['mesh_changed']))
    if rep['outdated']:
        lines.append('  surroundings changed, re-bake recommended: ' + ', '.join(rep['outdated']))
    for name, k, n, share, need in rep.get('narrow', ()):
        lines.append(f"  {name}: curvature width under {CURV_MIN_PX:g} px on {k} of {n} islands ({share:.0%} of its "
                     f"area); {need * 1000:.2g} mm would reach {CURV_MIN_PX:g} px on all")
    if rep['faces_under_4x']:
        lines.append(f"  {rep['faces_under_4x']} of {rep['faces']} faces: master under 4 x their density")
    if rep.get('object_uv'):  # decision 107
        lines.append('  Object UV masters, each texel the mean of its master pixels: ' + ', '.join(rep['object_uv']))
    if rep.get('strength') is not None:  # decision 106
        lines.append(f"  strength {rep['strength']:g}: the darkening scaled toward white")
    if rep.get('soften_mm') is not None:
        lines.append(f"  sharp edges softened ({rep['soften_mm']:g} mm, at least a texel): {rep['softened_px']} px")
    lines += [f'  {w}' for w in rep['warnings']]
    return lines


# ---------------------------------------------------------------------------------------------------------------------
# Fetch (decisions 93, 94): a master read at every face corner into the mesh's colour attribute (the masters only read)
# ---------------------------------------------------------------------------------------------------------------------

FETCH = {'ALBEDO': ('albedo',), 'ORM': ('ao', 'rough', 'metal'), 'EMIS': ('emis',)}
FETCH_NAMES = {'ALBEDO': 'Albedo', 'ORM': 'ORM', 'EMIS': 'Emis'}
FETCH_COLS = {'ao': (0,), 'rough': (1,), 'metal': (2,), 'albedo': (0, 1, 2), 'emis': (0, 1, 2)}
FETCH_ATTR = 'FSS_Bake'  # decision 94: the second attribute added beside a mesh's only one
FETCH_RADIUS = 4  # px: a corner whose four nearest texels are none of its triangle's looks this far for one


def fetch_grade(item, group):
    """The grade of a master's group for Fetch: the AO's (item['grade']) or a channel's (ch_grades)."""
    if group == 'ao':
        return item.get('grade', 'MISSING')
    return (item.get('ch_grades') or {}).get(group, 'MISSING')


def fetch_ready(item, what):
    """Decision 93: the groups of `what` the master of this item has (a master not missing; a mesh change is said when
    fetching)."""
    return [g for g in FETCH[what] if fetch_grade(item, g) != 'MISSING']


def corner_values(folder, stem, group):
    """Decision 94: each master triangle's three corners' value of a group, (T, 3, C) linear 0..1 (albedo and
    emissive decoded from sRGB, as Apply decodes them), NaN where none was found: bilinear at the corner's master
    position over the four nearest texels that are the triangle's own baked ones (its face in the .ao.map, filled;
    never a neighbour's island), renormalized; with none of them, the nearest own texel within FETCH_RADIUS px.
    Returns (values, tri_src, fallbacks). The images are read whole."""
    kinds = core.CHANNEL_KINDS.get(group, ('ao',))
    m = core.load_master(folder, stem, kind=kinds[0])
    if m is None:
        return None, None, 0
    imgs = [m['image']] + [core.read_image(core.master_paths(folder, stem, k)[0]) for k in kinds[1:]]
    H, W = m['H'], m['W']
    own = np.where(m['filled'], m['face_map'], -1)
    muv = np.asarray(m['muv'], np.float64)
    T = len(muv)
    P = muv.reshape(-1, 2) - 0.5
    t = np.repeat(np.arange(T), 3)
    x0, y0 = np.floor(P[:, 0]).astype(np.int64), np.floor(P[:, 1]).astype(np.int64)
    fx, fy = P[:, 0] - x0, P[:, 1] - y0
    C = len(kinds)
    acc = np.zeros((len(P), C))
    wsum = np.zeros(len(P))
    for dx in (0, 1):
        for dy in (0, 1):
            xi, yi = x0 + dx, y0 + dy
            inside = (xi >= 0) & (xi < W) & (yi >= 0) & (yi < H)
            xc, yc = np.clip(xi, 0, W - 1), np.clip(yi, 0, H - 1)
            ok = inside & (own[yc, xc] == t)
            w = (fx if dx else 1.0 - fx) * (fy if dy else 1.0 - fy) * ok
            wsum += w
            for c, img in enumerate(imgs):
                acc[:, c] += w * img[yc, xc]
    vals = np.full((len(P), C), np.nan)
    good = wsum > 1e-12
    vals[good] = acc[good] / wsum[good, None] / 65535.0
    fallbacks = 0
    for i in np.nonzero(~good)[0]:  # the nearest of the triangle's own texels
        cx, cy = int(round(P[i, 0])), int(round(P[i, 1]))
        xa, xb = max(0, cx - FETCH_RADIUS), min(W, cx + FETCH_RADIUS + 1)
        ya, yb = max(0, cy - FETCH_RADIUS), min(H, cy + FETCH_RADIUS + 1)
        yy, xx = np.nonzero(own[ya:yb, xa:xb] == t[i])
        if not len(yy):
            continue
        k = int(np.argmin((xx + xa - P[i, 0]) ** 2 + (yy + ya - P[i, 1]) ** 2))
        vals[i] = [img[yy[k] + ya, xx[k] + xa] / 65535.0 for img in imgs]
        fallbacks += 1
    if group in ('albedo', 'emis'):
        vals = np.where(np.isnan(vals), vals, core.srgb_decode(np.nan_to_num(vals)))
    return vals.reshape(T, 3, C), np.asarray(m['tri_src'], np.int64), fallbacks


def _target_attribute(me, read):
    """Decisions 91, 94: (attribute, added, why) the Fetch writes: the second colour attribute (read SECOND; beside an
    only one, FSS_Bake added after it, white, corner, not active, not render) or the active one; None and why
    without (a first attribute is never made)."""
    ca = me.color_attributes
    if read == 'ACTIVE':
        a = ca.active_color
        return (a, False, '') if a is not None else (None, False, 'no colour attribute')
    if len(ca) == 0:
        return None, False, 'no colour attribute'
    if len(ca) >= 2:
        return ca[1], False, ''
    active, render = ca.active_color.name if ca.active_color else None, ca.default_color_name
    a = ca.new(FETCH_ATTR, 'FLOAT_COLOR', 'CORNER')
    name = a.name
    a.data.foreach_set('color', np.ones(len(a.data) * 4, np.float32))
    if active:
        ca.active_color = ca[active]
    if render:
        ca.default_color_name = render
    return ca[name], True, ''


def _corner_float(obj, attr):
    """Decision 94: a point-domain or byte attribute converted to a corner float colour attribute of the same name
    (its values kept), by Blender's Convert Color Attribute on it made active for the call; the active and render
    attributes as they were. Returns the attribute."""
    me = obj.data
    ca = me.color_attributes
    name = attr.name
    active, render = ca.active_color.name if ca.active_color else None, ca.default_color_name
    ca.active_color = attr
    with bpy.context.temp_override(object=obj, active_object=obj, selected_objects=[obj]):
        bpy.ops.geometry.color_attribute_convert(domain='CORNER', data_type='FLOAT_COLOR')
    if active and active in ca:
        ca.active_color = ca[active]
    if render and render in ca:
        ca.default_color_name = render
    return ca[name]


def fetch_vertex_color(context, objects, what, read='SECOND'):
    """Decisions 93, 94: for the selected mesh objects, the masters of `what` (ALBEDO, ORM: the AO in red, roughness in
    green, metal in blue, EMIS) read at every face corner of the faces they cover and written into the colour
    attribute `read` names; components without a master, and corners of faces without one, keep their values; alpha
    1 where written. A shared mesh is written once. Returns the report: per object a line, and the skipped ones with
    why. The masters are only read."""
    folder = store.bake_folder()
    items, by_object = store._state['items'], store._state['by_object']
    dg = context.evaluated_depsgraph_get()
    lines, done_meshes, written = [], {}, 0
    for obj in sorted((o for o in objects if o.type == 'MESH'), key=lambda o: o.name):
        stem = by_object.get(obj.name)
        item = items.get(stem) if stem else None
        if item is None:
            lines.append(f'{obj.name}: no master')
            continue
        groups = fetch_ready(item, what)
        if not groups:
            lines.append(f'{obj.name}: no {FETCH_NAMES[what]} master')
            continue
        me = obj.data
        if me.name in done_meshes:
            lines.append(f'{obj.name}: its mesh {me.name} written with {done_meshes[me.name]}')
            continue
        stale = [g for g in groups if fetch_grade(item, g) == 'MESH']
        groups = [g for g in groups if g not in stale]
        notes = [f"{', '.join(store.core.CHANNEL_NAMES.get(g, 'AO') for g in stale)} skipped (mesh changed since "
                 f"its bake)"] if stale else []
        if not groups:
            lines.append(f'{obj.name}: ' + '; '.join(notes))
            continue
        ev_me = obj.evaluated_get(dg).data
        lv = np.empty(len(me.loops), np.int64)
        me.loops.foreach_get('vertex_index', lv)
        if len(ev_me.loops) != len(me.loops):
            lines.append(f'{obj.name}: its modifiers change the mesh')
            continue
        ev_lv = np.empty(len(ev_me.loops), np.int64)
        ev_me.loops.foreach_get('vertex_index', ev_lv)
        if not np.array_equal(lv, ev_lv):
            lines.append(f'{obj.name}: its modifiers change the mesh')
            continue
        ev = core.evaluated_triangles(obj, dg, [])
        target, added, why = _target_attribute(me, read)
        if target is None:
            lines.append(f'{obj.name}: {why}')
            continue
        converted = target.domain != 'CORNER' or target.data_type != 'FLOAT_COLOR'
        was = f'{target.data_type.lower()} {target.domain.lower()}'
        if converted:
            target = _corner_float(obj, target)
            notes.append(f'{target.name} converted from {was} to float corner')
        if added:
            notes.append(f'{target.name} added as the second colour attribute')
        cols = np.empty(len(me.loops) * 4, np.float32)
        target.data.foreach_get('color', cols)
        cols = cols.reshape(-1, 4)
        got_any = np.zeros(len(me.loops), bool)
        fb = 0
        for g in groups:
            vals, tri_src, fallbacks = corner_values(folder, stem, g)
            if vals is None:
                notes.append(f"{store.core.CHANNEL_NAMES.get(g, 'AO')} skipped (its master files are missing)")
                continue
            if len(tri_src) and int(tri_src.max()) >= len(ev['loops']):
                notes.append(f"{store.core.CHANNEL_NAMES.get(g, 'AO')} skipped (fewer triangles than baked)")
                continue
            fb += fallbacks
            loops = ev['loops'][tri_src].ravel()
            v = vals.reshape(-1, vals.shape[2])
            ok = ~np.isnan(v[:, 0])
            n = len(me.loops)
            cnt = np.bincount(loops[ok], minlength=n)
            for c, col in enumerate(FETCH_COLS[g]):
                s = np.bincount(loops[ok], weights=v[ok, c], minlength=n)
                has = cnt > 0
                cols[has, col] = s[has] / cnt[has]  # a corner of several triangles of one polygon: the mean
            got_any |= cnt > 0
        if not got_any.any():
            lines.append(f'{obj.name}: nothing written' + (f" ({'; '.join(notes)})" if notes else ''))
            continue
        cols[got_any, 3] = 1.0
        target.data.foreach_set('color', cols.ravel())
        me.update()
        corners = int(got_any.sum())
        written += corners
        done_meshes[me.name] = obj.name
        names = ', '.join(store.core.CHANNEL_NAMES.get(g, 'AO') for g in groups)
        lines.append(f'{obj.name}: {corners} corners of {target.name} ({names})'
                     + (f', {fb} read from the nearest texel' if fb else '')
                     + (f"; {'; '.join(notes)}" if notes else ''))
    return dict(lines=lines, corners=written, meshes=sorted(done_meshes))
