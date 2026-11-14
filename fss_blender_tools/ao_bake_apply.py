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


def output_folder(scene, kind='ao'):
    """Where Apply writes separate files: the AO's Output Folder; the curvature's own (empty: the AO's)."""
    folder = scene.fss_ao_bake.get('curv_output_folder', '') if kind == 'curv' else ''
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


def default_file_name(material):
    return ''.join(c if (c.isalnum() or c in '-_.') else '_' for c in material.name) + '_ao.png'


def file_name(material, settings):
    name = settings.file_name.strip() if settings.file_name else ''
    if not name:
        name = default_file_name(material)
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
                vals, bits, _ct = read_texture(self.orm_path)
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
        self.sampling = settings.sampling
        if self.gb == 'COPY' and self.orm is None:
            self.warnings.append('green and blue: no ORM texture to copy from, written white')
            self.gb = 'WHITE'
        if per_object and os.path.isfile(self.path):
            vals, bits, _ct = read_texture(self.path)
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
        return np.rint(np.clip(out, 0, 1) * 65535.0).astype(np.uint16)


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


def narrow_islands(pos_w, ev, tris, uvpx, W, H, width):
    """Decision 55: the UV islands (of these triangles, uvpx in target pixels) where the curvature width covers fewer
    than CURV_MIN_PX texture pixels: (count, islands, their share of the 3D area, the width that reaches CURV_MIN_PX on
    every island), or None when none."""
    if not len(tris):
        return None
    a3 = core.tri_areas_3d(pos_w, tris)
    a2 = np.abs(core.tri_areas_2d(uvpx))
    isl = core.uv_islands(core.weld_ids(ev['co'])[tris], uvpx / np.array([W, H], dtype=np.float64))
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


def apply_set_steps(context, material, objects=None, settings=None, band_rows=APPLY_BAND, kind='ao'):
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
    target: the AO (uint16) and three masks, 8 bytes per target pixel; nothing in proportion to a master."""
    t0 = time.time()
    scene = context.scene
    folder = store.bake_folder()
    settings = settings or material.fss_ao_apply
    curv = kind == 'curv'
    if curv:
        settings = curvature_settings(settings, material)
    pad = int(scene.fss_ao_bake.curv_padding if curv else scene.fss_ao_bake.padding)
    # decision 46: the darker side of convex sharp edges brightened toward the edge (m; at least a texel), or None
    soften_width = float(scene.fss_ao_bake.soften_width) if scene.fss_ao_bake.soften_edges and not curv else None
    fill = core.CURV_FLAT if curv else 65535  # where no master is
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
                  copied=[], white=[], outdated=[], narrow=[], faces_under_4x=0, faces=0, stacked_px=0, softened_px=0,
                  soften_mm=None if soften_width is None else round(soften_width * 1000, 3), warnings=target.warnings,
                  backup=target.backup, per_object=objects is not None, band_rows=int(band_rows), copy=None)
    copies = {}  # which copy ran (apply-native-copy journal): 'native' (C++, its threads) or 'numpy' (why)
    pending = []  # padding (flat index, value, step), written once every face of the set is known
    written = np.zeros((H, W), bool)
    cover = np.zeros((H, W), bool)
    pad_step = np.full((H, W), 1 << 30, np.int32)
    Q = np.zeros((H, W), np.uint16)  # the AO where written
    label_parts = []
    halo = pad + 2  # the padding grows `pad` px: a band copied with this halo equals the whole crop's copy

    def bands(crop):
        x0, y0, w, h = crop
        for yb in range(y0, y0 + h, band_rows):
            yield yb, min(y0 + h, yb + band_rows), max(y0, yb - halo), min(y0 + h, yb + band_rows + halo)

    for k, stem in enumerate(stems):
        item = store._state['items'][stem]
        yield 'master', k, len(stems), item['name']
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
        mine = stem in chosen
        if mine:
            report['faces'] += int(len(np.unique(ev['poly'][tri_ids])))
            entry = masters.get(stem)
            mh = core.mesh_hash(ev)
            usable = entry is not None and entry.get('mesh_hash') == mh and store.has_files(folder, stem)
            if curv and usable and not os.path.isfile(core.master_paths(folder, stem, 'curv')[0]):
                usable = False
            if not usable:
                why = ('missing' if entry is None or not store.has_files(folder, stem) else
                       'mesh changed' if entry.get('mesh_hash') != mh else 'no curvature baked')
                report['white'].append((item['name'], why, int(len(np.unique(ev['poly'][tri_ids])))))
        # the faces of the set (also of the objects not chosen): no padding goes there
        for yb, yb1, _h0, _h1 in bands(crop):
            own, _cnt = core.raster_window(uvpx_all[tri_ids], w, yb1 - yb, 1, x0, yb)
            inside = own >= 0
            cover[yb:yb1, x0:x0 + w] |= inside
            if mine and not usable:
                Q[yb:yb1, x0:x0 + w][inside] = fill
                written[yb:yb1, x0:x0 + w] |= inside
            del own, _cnt
        if not mine or not usable:
            continue
        if entry.get('surround_hash') != item['surround_hash'] and not curv:
            report['outdated'].append(item['name'])
        baked_w = (entry.get('curvature') or {}).get('width')
        if curv and baked_w is not None and baked_w != round(float(scene.fss_ao_bake.curv_width), 6):
            report['warnings'].append(f"{item['name']}: curvature baked at {entry['curvature']['width'] * 1000:g} mm, "
                                      f"the setting is {scene.fss_ao_bake.curv_width * 1000:g} mm (re-bake)")
        master = core.open_master(folder, stem, kind=kind)
        if master is None:  # the files went away since Refresh: white, as a missing master
            report['white'].append((item['name'], 'missing', int(len(np.unique(ev['poly'][tri_ids])))))
            for yb, yb1, _h0, _h1 in bands(crop):
                own, _cnt = core.raster_window(uvpx_all[tri_ids], w, yb1 - yb, 1, x0, yb)
                Q[yb:yb1, x0:x0 + w][own >= 0] = fill
                written[yb:yb1, x0:x0 + w] |= own >= 0
            continue
        try:
            src = master['tri_src']
            pos_w, cn_w = core.to_world(ev)
            tris = ev['tris'][src]
            uvpx = uvpx_all[src]
            sel = in_set[src]
            uvpx = np.where(sel[:, None, None], uvpx, -1e6)
            tisl = np.zeros(len(tris), np.int64)
            ctx = core.copy_context(pos_w, tris, uvpx, master, core.K_MIN, core.K_MAX)
            sctx = (core.soften_context(pos_w, tris, uvpx, ctx, soften_width, use=sel, cn=cn_w[src])
                    if soften_width is not None else None)
            for yb, yb1, hy0, hy1 in bands(crop):
                yield 'master', k + (yb - y0) / max(h, 1), len(stems), item['name']
                out, info, owner_c, steps, count_c = core.copy_master(
                    pos_w, tris, uvpx, tisl, master, (x0, hy0, w, hy1 - hy0), core.K_MIN, pad, outside_mode='tri',
                    kmax=core.K_MAX, surface_cos=core.SURFACE_COS, same_face=False, ctx=ctx, soften=sctx,
                    threads=int(scene.fss_ao_bake.threads))
                copies.setdefault(info['copy'], info['copy_threads'] if info['copy'] == 'native' else info['copy_why'])
                r = slice(yb - hy0, yb1 - hy0)
                out, owner_c, steps = out[r], owner_c[r], steps[r]
                report['stacked_px'] += int((count_c[r] > 1).sum())
                report['softened_px'] += int(info.get('softened_px', 0))
                inside = (owner_c >= 0) & (out >= 0)
                Q[yb:yb1, x0:x0 + w][inside] = _quantize(out[inside])
                written[yb:yb1, x0:x0 + w] |= inside
                padm = (owner_c < 0) & (steps > 0) & (steps <= pad) & (out >= 0)
                jj, ii = np.nonzero(padm)
                if len(jj):
                    pending.append(((jj + yb) * W + ii + x0, _quantize(out[jj, ii]), steps[jj, ii].astype(np.int32)))
                del out, owner_c, steps, count_c, padm
            report['copied'].append(item['name'])
            # faces under 4 x: the master's density against each face's density at the target's size
            d = core.densities(pos_w, tris[sel], uvpx[sel])
            low = (d > 0) & (master['density'] < 4.0 * d * (1 - UNDER_TOLERANCE))
            report['faces_under_4x'] += int(len(np.unique(ev['poly'][src[sel][low]])))
            if curv:  # decision 55: islands where the width is under CURV_MIN_PX texture pixels
                got = narrow_islands(pos_w, ev, tris[sel], uvpx[sel], W, H,
                                     float(baked_w if baked_w is not None else scene.fss_ao_bake.curv_width))
                if got:
                    report['narrow'].append((item['name'],) + got)
            report.setdefault('page_loads', []).append([int(p.loads) for p in master.get('pages', ())])
        finally:
            master['close']()
    # padding only where no face of the set lies (P47), the nearest island's first
    flat_cover, flat_step, flat_q, flat_w = cover.ravel(), pad_step.ravel(), Q.ravel(), written.ravel()
    for idx, val, st in pending:
        take = ~flat_cover[idx] & (st < flat_step[idx])
        flat_q[idx[take]] = val[take]
        flat_step[idx[take]] = st[take]
        flat_w[idx[take]] = True
    del pending, cover, pad_step

    def labels():
        parts_src, parts_dst = [], []
        Hs, Ws = target.orm[0].shape[:2]
        for uv_t, ev, tri_ids in label_parts:
            wt = core.weld_ids(ev['co'])[ev['tris'][tri_ids]]
            isl = core.uv_islands(wt, uv_t)
            parts_src.append((uv_t * np.array([Ws, Hs]), isl))
            parts_dst.append((uv_t * np.array([W, H]), isl))
        return core.island_labels(parts_src, Ws, Hs, pad * max(Ws / W, 1)), core.island_labels(parts_dst, W, H, pad)

    gb = target.green_blue(labels) if target.kind != 'ORM' and target.fresh and target.layout == 'ORM' else None
    if target.kind != 'ORM':
        os.makedirs(os.path.dirname(target.path), exist_ok=True)
    channels = target.base.shape[2] if target.base is not None else 3
    tmp = target.path + '.tmp'
    writer = core.PngRowWriter(tmp, W, H, 16, channels)
    try:
        for top in range(0, H, 256):  # rows from the top
            yield 'write', top, H, os.path.basename(target.path)
            r0, r1 = H - min(H, top + 256), H - top
            if target.base is not None:
                vals = target.base[r0:r1].copy()
            else:
                vals = np.full((r1 - r0, W, 3), fill, np.uint16)
                if gb is not None:
                    vals[:, :, 1:3] = gb[r0:r1]
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
        parts = [f"C++ ({v} thread{'s' if v != 1 else ''})" if k == 'native' else f'numpy ({v})'
                 for k, v in sorted(copies.items())]
        report['copy'] = ' and '.join(parts)
        report['copy_backends'] = sorted(copies)
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
    jobs = [(m, k) for m in materials for k in kinds]
    n = len(jobs)
    for i, (material, kind) in enumerate(jobs):
        gen = apply_set_steps(context, material, objects, kind=kind)
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
        except (ValueError, OSError) as exc:
            reports.append(dict(material=material.name, error=str(exc)))
        finally:
            gen.close()  # on Cancel: the set's master and its .tmp file closed and removed now
    return reports


def report_lines(rep):
    if rep.get('error'):
        return [f"{rep['material']}: {rep['error']}"]
    lines = [f"{rep['material']}: {os.path.basename(rep['path'])} {rep['size'][0]} x {rep['size'][1]}, "
             f"{len(rep['copied'])} copied, {rep['written_px']} px, {rep['seconds']} s"]
    if rep['white']:
        lines.append(f"  {'flat' if rep.get('kind') == 'curv' else 'white'} (no up-to-date master): "
                     + ', '.join(f'{n} ({why})' for n, why, _f in rep['white']))
    if rep['outdated']:
        lines.append('  surroundings changed, re-bake recommended: ' + ', '.join(rep['outdated']))
    for name, k, n, share, need in rep.get('narrow', ()):
        lines.append(f"  {name}: curvature width under {CURV_MIN_PX:g} px on {k} of {n} islands ({share:.0%} of its "
                     f"area); {need * 1000:.2g} mm would reach {CURV_MIN_PX:g} px on all")
    if rep['faces_under_4x']:
        lines.append(f"  {rep['faces_under_4x']} of {rep['faces']} faces: master under 4 x their density")
    if rep.get('soften_mm') is not None:
        lines.append(f"  sharp edges softened ({rep['soften_mm']:g} mm, at least a texel): {rep['softened_px']} px")
    lines += [f'  {w}' for w in rep['warnings']]
    if rep.get('copy') and 'numpy' in rep.get('copy_backends', ()):
        lines.append(f"  copy: {rep['copy']}")
    return lines
