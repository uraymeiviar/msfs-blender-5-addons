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
  is under 4 x their density at the target's size are counted.
Apply writes files only: no datablock is added to the .blend and no material is changed.
"""

import os
import shutil
import time

import bpy
import numpy as np

from . import ao_bake_core as core
from . import ao_bake_store as store

P_ORM = 'msfs_occlusion_metallic_roughness_texture'
RESOLUTIONS = [str(1 << n) for n in range(8, 14)]
UNDER_TOLERANCE = 1e-3  # faces under 4 x: float32 UVs make equal densities differ by about 1e-7


def orm_image(material):
    image = getattr(material, P_ORM, None)
    return image if isinstance(image, bpy.types.Image) else None


def image_path(image):
    return os.path.normpath(bpy.path.abspath(image.filepath, library=image.library)) if image.filepath else ''


def output_folder(scene):
    folder = scene.fss_ao_bake.output_folder
    if not folder:
        stem = os.path.splitext(os.path.basename(bpy.data.filepath))[0] if bpy.data.filepath else 'untitled'
        folder = f'//{stem}_ao/'
    return os.path.normpath(bpy.path.abspath(folder))


def file_name(material, settings):
    name = settings.file_name.strip() if settings.file_name else ''
    if not name:
        name = ''.join(c if (c.isalnum() or c in '-_.') else '_' for c in material.name) + '_ao.png'
    if not name.lower().endswith('.png'):
        name += '.png'
    return name


def read_texture(path):
    """(values (H, W, C) uint16 in the file's depth, bits, colour type). PNGs this module's reader does not decode are
    read through a temporary Blender image, removed again."""
    try:
        vals, bits, ct = core.read_png(path)
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
    """Where Apply writes for one texture set: the file, its size, its pixels before (uint16, 16-bit scale)."""

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
                vals, bits, _ct = read_texture(self.orm_path)
                self.orm = (vals.astype(np.uint32) * (257 if bits == 8 else 1), bits)
        if self.kind == 'ORM':
            if self.orm is None:
                raise ValueError(f'{material.name}: no texture file in the ORM slot')
            vals, bits = self.orm
            if vals.shape[2] < 3:
                raise ValueError(f'{material.name}: the ORM texture has {vals.shape[2]} channel(s), not RGB')
            self.path = self.orm_path
            self.H, self.W = vals.shape[:2]
            self.base = vals.copy()
            if bits == 8:
                self.warnings.append('the ORM file is 8-bit: written as 16-bit, green and blue kept')
            self.warnings.append('the next ORM export from Substance Painter replaces the red channel again')
            backup_dir = os.path.join(folder, 'orm_backup')
            self.backup = os.path.join(backup_dir, os.path.basename(self.path))
            if not os.path.isfile(self.backup):
                os.makedirs(backup_dir, exist_ok=True)
                shutil.copy2(self.path, self.backup)
            self.layout = 'ORM'
            return
        self.layout = settings.layout
        self.path = os.path.join(output_folder(scene), file_name(material, settings))
        size = getattr(settings, 'size', None)  # (W, H): a measurement script's crop of a layout, never the panel
        if size:
            self.W, self.H = int(size[0]), int(size[1])
        elif settings.resolution == 'ORM':
            if self.orm_size is not None:
                self.H, self.W = self.orm_size
            else:
                self.H = self.W = store.texture_size(material)
        else:
            self.H = self.W = int(settings.resolution)
        self.gb = settings.green_blue if self.layout == 'ORM' else 'AO'
        self.sampling = settings.sampling
        if self.gb == 'COPY' and self.orm is None:
            self.warnings.append('green and blue: no ORM texture to copy from, written white')
            self.gb = 'WHITE'
        if per_object and os.path.isfile(self.path):
            vals, bits, _ct = read_texture(self.path)
            if vals.shape[:2] != (self.H, self.W):
                raise ValueError(f'{self.path}: {vals.shape[1]} x {vals.shape[0]} px, the setting says '
                                 f'{self.W} x {self.H}')
            vals = vals.astype(np.uint32) * (257 if bits == 8 else 1)
            if vals.shape[2] == 1:
                vals = np.repeat(vals, 3, axis=2)
            self.base = vals[:, :, :3] if vals.shape[2] != 4 else vals[:, :, :3]
            self.fresh = False
        else:
            self.base = np.full((self.H, self.W, 3), 65535, dtype=np.uint32)
            self.fresh = True

    def green_blue(self, labels):
        """Green and blue of a new ORM-layout file: white, or the ORM texture's (resampled inside islands)."""
        if self.layout != 'ORM' or self.gb != 'COPY':
            return None
        src = self.orm[0][:, :, 1:3]
        if src.shape[:2] == (self.H, self.W):
            return src.copy()
        self.warnings.append(f'green and blue resampled from {src.shape[1]} x {src.shape[0]} to {self.W} x {self.H} '
                             f'px ({self.sampling.lower()}): the artist\'s roughness and metallic change')
        src_lab, dst_lab = labels()
        out = core.resample(src.astype(np.float64) / 65535.0, src_lab, dst_lab, self.sampling)
        return np.rint(np.clip(out, 0, 1) * 65535.0).astype(np.uint32)


def _set_tris(item, material, depsgraph):
    """The item's first user evaluated now, and the triangles (all of them) whose material is `material`."""
    obj = bpy.data.objects[item['object']]
    uv = obj.data.uv_layers.active.name if obj.data.uv_layers.active else item['uv']
    ev = core.evaluated_triangles(obj, depsgraph, [uv])
    slots = [slot.material for slot in obj.material_slots]
    match = np.array([s == material for s in slots] + [False], bool)
    in_set = match[np.minimum(ev['mat'], len(match) - 1)]
    return obj, ev, ev['uv'].get(uv), in_set


def _crop(uvpx, W, H, border):
    x0, y0, w, h = core.crop_box(uvpx, border)
    x1, y1 = min(W, x0 + w), min(H, y0 + h)
    x0, y0 = max(0, x0), max(0, y0)
    return x0, y0, max(0, x1 - x0), max(0, y1 - y0)


def apply_set(context, material, objects=None, settings=None):
    """Apply for one texture set; objects: the selected objects (per-object Apply, P47) or None for the whole set.
    settings: the material's fss_ao_apply or an object with the same attributes. Returns the report."""
    t0 = time.time()
    scene = context.scene
    folder = store.bake_folder()
    settings = settings or material.fss_ao_apply
    pad = int(scene.fss_ao_bake.padding)
    row = store._state['sets'].get(material.name)
    if row is None:
        return dict(material=material.name, error='not in the last Refresh (press Refresh)')
    stems = row['items']
    chosen = stems if objects is None else [s for s in store.items_for_objects(objects) if s in stems]
    if objects is not None and not chosen:
        return dict(material=material.name, error='no selected object in this texture set')
    target = Target(scene, material, settings, objects is not None, folder)
    W, H = target.W, target.H
    masters = store.read_index(folder).get('masters', {}) if folder else {}
    depsgraph = context.evaluated_depsgraph_get()
    report = dict(material=material.name, path=target.path, size=[W, H], target=target.kind, layout=target.layout,
                  copied=[], white=[], outdated=[], faces_under_4x=0, faces=0, stacked_px=0, warnings=target.warnings,
                  backup=target.backup, per_object=objects is not None)
    pending = []  # padding, written once every face of the set is known
    written = np.zeros((H, W), bool)
    cover = np.zeros((H, W), bool)
    pad_step = np.full((H, W), 1 << 30, np.int64)
    Rbuf = np.full((H, W), -1.0)
    label_parts = []
    for stem in stems:
        item = store._state['items'][stem]
        obj, ev, uv, in_set = _set_tris(item, material, depsgraph)
        if uv is None or not in_set.any():
            continue
        tri_ids = np.nonzero(in_set)[0]
        uvpx_all = uv * np.array([W, H], dtype=np.float64)
        label_parts.append((uv[tri_ids], ev, tri_ids))
        crop = _crop(uvpx_all[tri_ids], W, H, pad + 4)
        x0, y0, w, h = crop
        if w <= 0 or h <= 0:
            continue
        own, cnt = core.rasterize_ids(uvpx_all[tri_ids], w, h, 1, x0, y0)
        cover[y0:y0 + h, x0:x0 + w] |= own >= 0
        if stem not in chosen:
            continue
        report['faces'] += int(len(np.unique(ev['poly'][tri_ids])))
        entry = masters.get(stem)
        mh = core.mesh_hash(ev)
        usable = entry is not None and entry.get('mesh_hash') == mh and store.has_files(folder, stem)
        if not usable:
            why = 'missing' if entry is None or not store.has_files(folder, stem) else 'mesh changed'
            report['white'].append((item['name'], why, int(len(np.unique(ev['poly'][tri_ids])))))
            inside = own >= 0
            Rbuf[y0:y0 + h, x0:x0 + w][inside] = 1.0
            written[y0:y0 + h, x0:x0 + w] |= inside
            continue
        if entry.get('surround_hash') != item['surround_hash']:
            report['outdated'].append(item['name'])
        master = core.load_master(folder, stem)
        src = master['tri_src']
        pos_w, _cn = core.to_world(ev)
        tris = ev['tris'][src]
        uvpx = uvpx_all[src]
        sel = in_set[src]
        uvpx = np.where(sel[:, None, None], uvpx, -1e6)
        out, info, owner_c, steps, count_c = core.copy_master(
            pos_w, tris, uvpx, np.zeros(len(tris), np.int64), master, crop, core.K_MIN, pad, outside_mode='tri',
            kmax=core.K_MAX, surface_cos=core.SURFACE_COS, same_face=False)
        report['copied'].append(item['name'])
        report['stacked_px'] += info['stacked_px']
        inside = (owner_c >= 0) & (out >= 0)
        Rbuf[y0:y0 + h, x0:x0 + w][inside] = out[inside]
        written[y0:y0 + h, x0:x0 + w] |= inside
        padm = (owner_c < 0) & (steps > 0) & (steps <= pad) & (out >= 0)
        pending.append((y0, x0, h, w, out, padm, steps))
        # faces under 4 x: the master's density against each face's density at the target's size
        d = core.densities(pos_w, tris[sel], uvpx[sel])
        low = (d > 0) & (master['density'] < 4.0 * d * (1 - UNDER_TOLERANCE))
        report['faces_under_4x'] += int(len(np.unique(ev['poly'][src[sel][low]])))
    # padding only where no face of the set lies (P47), the nearest island's first
    for y0, x0, h, w, out, padm, steps in pending:
        sub_cover = cover[y0:y0 + h, x0:x0 + w]
        sub_step = pad_step[y0:y0 + h, x0:x0 + w]
        take = padm & ~sub_cover & (steps < sub_step)
        Rbuf[y0:y0 + h, x0:x0 + w][take] = out[take]
        sub_step[take] = steps[take]
        written[y0:y0 + h, x0:x0 + w] |= take

    def labels():
        parts_src, parts_dst = [], []
        Hs, Ws = target.orm[0].shape[:2]
        for uv_t, ev, tri_ids in label_parts:
            wt = core.weld_ids(ev['co'])[ev['tris'][tri_ids]]
            isl = core.uv_islands(wt, uv_t)
            parts_src.append((uv_t * np.array([Ws, Hs]), isl))
            parts_dst.append((uv_t * np.array([W, H]), isl))
        return core.island_labels(parts_src, Ws, Hs, pad * max(Ws / W, 1)), core.island_labels(parts_dst, W, H, pad)

    q = np.rint(np.clip(Rbuf, 0, 1) * 65535.0).astype(np.uint32)
    if target.kind == 'ORM':
        vals = target.base.copy()
        vals[:, :, 0] = np.where(written, q, vals[:, :, 0])
    else:
        vals = target.base.copy()
        if target.fresh and target.layout == 'ORM':
            gb = target.green_blue(labels)
            if gb is not None:
                vals[:, :, 1:3] = gb
        vals[:, :, 0] = np.where(written, q, vals[:, :, 0])
        if target.layout == 'GREY':
            for c in (1, 2):
                vals[:, :, c] = np.where(written, q, vals[:, :, c])
        os.makedirs(os.path.dirname(target.path), exist_ok=True)
    core.write_png_int(target.path, vals.astype(np.uint16), 16)
    for image in bpy.data.images:
        if image.source == 'FILE' and image_path(image) == os.path.normpath(target.path) and not image.is_dirty:
            image.reload()
    report.update(written_px=int(written.sum()), seconds=round(time.time() - t0, 2))
    return report



def apply(context, materials, objects=None):
    reports = []
    for material in materials:
        try:
            reports.append(apply_set(context, material, objects))
        except (ValueError, OSError) as exc:
            reports.append(dict(material=material.name, error=str(exc)))
    return reports


def report_lines(rep):
    if rep.get('error'):
        return [f"{rep['material']}: {rep['error']}"]
    lines = [f"{rep['material']}: {os.path.basename(rep['path'])} {rep['size'][0]} x {rep['size'][1]}, "
             f"{len(rep['copied'])} copied, {rep['written_px']} px, {rep['seconds']} s"]
    if rep['white']:
        lines.append(f"  white (no up-to-date master): " + ', '.join(f'{n} ({why})' for n, why, _f in rep['white']))
    if rep['outdated']:
        lines.append('  surroundings changed, re-bake recommended: ' + ', '.join(rep['outdated']))
    if rep['faces_under_4x']:
        lines.append(f"  {rep['faces_under_4x']} of {rep['faces']} faces: master under 4 x their density")
    lines += [f'  {w}' for w in rep['warnings']]
    return lines
