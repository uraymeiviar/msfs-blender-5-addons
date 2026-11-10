"""Texture Sets (material-management journal, Session 33): for each used material of the last Materials Refresh, the
texture of each MSFS 2024 slot with its role, channels and bit depth, and warnings against the project's standard.

- Roles (S33.2) come from the material type and the slot, never from the file name. The slots each type uses follow
  the exporter's MSFS 2024 material panels (io_scene_gltf2_msfs_fss/blender/material/msfs_material_*.py).
- Bit depth and channels come from the PNG header, read at Refresh (reads only a few bytes per file).
- Warnings (S33.3, S33.4): a channel the role does not use; an 8-bit file where the role needs 16-bit; alpha in the
  albedo of an Opaque material; a texture in a slot the type does not use.
- Check Data Depth (S33.5) reads the pixels of each 16-bit PNG: a channel whose values lie on the 8-bit grid (value x 257)
  holds 8-bit data. Results are kept in Scene.fss_texture_sets.checks with the file's size and modification time and
  reused until the file changes. It runs one texture per timer step, so Blender stays usable between textures.

Texture XMLs (journal Session 34, part 2; decisions S34.1 to S34.3, S35.1): one row per image file of the materials the
MSFS 2024 export would write (the objects of the enabled multi-exporter presets' enabled layers, else the visible objects),
with the BitmapSlot its XML gets, its six image flags (edited on the row: image.msfs_flags of the image Asobo's TextureLib
reads, the first one named like the file), and its XML in the scene's MSFS Texture Folder: missing, matches or differs
from what the export would write, or no PNG there. Refresh first reads each XML that was never read into its images
(texture_folder.read_xml_once), so an XML on disk is not lost; from then on Blender's flags win. Write XMLs writes them
with Asobo's TextureLib (create_xml), as the export does, without exporting.

Material properties are read with getattr, so nothing breaks without the exporter add-on (no MSFS slots then).
"""

import os
import time
from pathlib import Path

import bpy
import numpy as np

# --- roles and slots -----------------------------------------------------------------------------------------------

RGBA = ('R', 'G', 'B', 'A')
OMR = ('O', 'R', 'M')
XYZ = ('X', 'Y', 'Z')
RGB = ('R', 'G', 'B')
ONE = ('L',)

# role: channel labels in file order (R, G, B, A); a channel past the labels is not used by the role
ROLES = {
    'ALB': RGBA, 'ORM': OMR, 'NML': XYZ, 'EMIS': RGB, 'AO2': ONE,
    'ALB-D': RGBA, 'ORM-D': OMR, 'NML-D': XYZ, 'MASK': ONE, 'ALB-2': RGBA, 'ORM-2': OMR,
    'DIR': ('Dx', 'Dy', 'Ry'), 'COAT': ('R', 'G', 'B', 'Ro'), 'NML-C': XYZ, 'MELT': ('Mp', 'R', 'M'),
    'ALB-G': RGBA, 'NML-G': XYZ, 'ALB-R': RGBA, 'EMIS-R': ('R', 'G', 'B', 'T'),
    'RRM': ('Rf', 'R', 'M'), 'RRM-D': ('Rf', 'R', 'M'), 'MASK-D': ('D1', 'Ice', 'D2'), 'NML-I': XYZ, 'NML-S': XYZ,
    'MASK-R': ONE, 'WIPE': ('In', 'Out', 'Len', 'Msk'), 'IRID': ONE, 'ALB-B': RGBA, 'MASK-B': ('A',),
    'ALB-W': ('R', 'G', 'B', 'Msk'), 'ORM-W': ('O', 'R', 'M', 'I'), 'OPAC': ONE, 'FOL': ('Fm', 'Tr', 'Wm'),
    'MASK-M': ONE, 'NML-M': XYZ, 'MASK-T': ('Mud', 'Dust'),
}

# S33.3: roles that need 16-bit on every material, and per material type
NEEDS_16 = {'ORM', 'ORM-D', 'ORM-2', 'ORM-W', 'AO2', 'RRM', 'RRM-D', 'MELT', 'DIR', 'COAT',
            'NML', 'NML-D', 'NML-C', 'NML-G', 'NML-I', 'NML-S', 'NML-M'}
NEEDS_16_ON = {'ALB': {'msfs_standard'}, 'EMIS': {'msfs_standard', 'msfs_decal'}}

# the exporter's MSFS 2024 texture slot properties, and the role each has on most types (used to name a slot that a
# material's type does not use)
P_BASE = 'msfs_base_color_texture'
P_ORM = 'msfs_occlusion_metallic_roughness_texture'
P_NML = 'msfs_normal_texture'
P_EMIS = 'msfs_emissive_texture'
P_DCOL = 'msfs_detail_color_texture'
P_DORM = 'msfs_detail_occlusion_metallic_roughness_texture'
P_DNML = 'msfs_detail_normal_texture'
P_MASK = 'msfs_blend_mask_texture'
P_DMASK = 'msfs_decal_blend_mask_texture'
P_AO2 = 'msfs_occlusion_uv2'
P_WEAR_ALB = 'msfs_wear_albedo_mask'
P_WEAR_ORM = 'msfs_wear_omr_intensity'
P_COAT = 'msfs_clearcoat_color_roughness_texture'
P_COAT_NML = 'msfs_clearcoat_normal_texture'
P_DIR = 'msfs_anisotropic_direction_roughness_y_texture'
P_BEHIND = 'msfs_behind_glass_color_texture'
P_OPAC = 'msfs_opacity_texture'
P_WIPE = 'msfs_windshield_wiper_mask_texture'
P_WS_DNML = 'msfs_windshield_detail_normal_texture'
P_SCR = 'msfs_windshield_scratches_normal_texture'
P_IRID = 'msfs_iridescent_thickness_texture'
P_BUG_ALB = 'msfs_windshield_insects_albedo_texture'
P_BUG_MSK = 'msfs_windshield_insects_mask_texture'
P_FOL = 'msfs_foliage_mask_texture'
P_MUD_MSK = 'msfs_tire_mud_cutout_texture'
P_TIRE = 'msfs_tire_details_texture'
P_MUD_NML = 'msfs_tire_mud_normal_texture'

SLOT_ROLE = {
    P_BASE: 'ALB', P_ORM: 'ORM', P_NML: 'NML', P_EMIS: 'EMIS', P_DCOL: 'ALB-D', P_DORM: 'ORM-D', P_DNML: 'NML-D',
    P_MASK: 'MASK', P_DMASK: 'MASK', P_AO2: 'AO2', P_WEAR_ALB: 'ALB-W', P_WEAR_ORM: 'ORM-W', P_COAT: 'COAT',
    P_COAT_NML: 'NML-C', P_DIR: 'DIR', P_BEHIND: 'ALB-R', P_OPAC: 'OPAC', P_WIPE: 'WIPE', P_WS_DNML: 'NML-D',
    P_SCR: 'NML-S', P_IRID: 'IRID', P_BUG_ALB: 'ALB-B', P_BUG_MSK: 'MASK-B', P_FOL: 'FOL', P_MUD_MSK: 'MASK-M',
    P_TIRE: 'MASK-T', P_MUD_NML: 'NML-M',
}
SLOT_ORDER = tuple(SLOT_ROLE)

CORE = ((P_BASE, 'ALB'), (P_ORM, 'ORM'), (P_NML, 'NML'), (P_EMIS, 'EMIS'))
DETAIL = ((P_DCOL, 'ALB-D'), (P_DORM, 'ORM-D'), (P_DNML, 'NML-D'))
FULL = CORE + DETAIL + ((P_MASK, 'MASK'), (P_AO2, 'AO2'))
WEAR = ((P_WEAR_ALB, 'ALB-W'), (P_WEAR_ORM, 'ORM-W'))

# type: (label, ((slot property, role), ...)); a type with an empty tuple uses no texture
TYPES = {
    'msfs_standard': ('Standard', FULL + WEAR),
    'msfs_decal': ('Decal', FULL),
    'msfs_porthole': ('Porthole', FULL),
    'msfs_glass': ('Glass', FULL),
    'msfs_fake_terrain': ('Fake Terrain', FULL),
    'msfs_ghost': ('Ghost', FULL),
    'msfs_sail': ('Sail', FULL),
    'msfs_propeller': ('Propeller', FULL),
    'msfs_geo_decal_blendmasked': ('GeoDecal Blend Masked', CORE + DETAIL + ((P_DMASK, 'MASK'), (P_AO2, 'AO2'))),
    'msfs_geo_decal_frosted': ('GeoDecal Frosted', CORE + ((P_DCOL, 'ALB-D'), (P_DORM, 'MELT'), (P_DNML, 'NML-D'),
                                                           (P_AO2, 'AO2'))),
    'msfs_clearcoat': ('Clearcoat', FULL + ((P_COAT, 'COAT'), (P_COAT_NML, 'NML-C')) + WEAR),
    'msfs_anisotropic': ('Anisotropic', FULL + ((P_DIR, 'DIR'),)),
    'msfs_hair': ('Hair', CORE + ((P_AO2, 'AO2'), (P_DIR, 'DIR'))),
    'msfs_sss': ('SSS', CORE + ((P_AO2, 'AO2'), (P_OPAC, 'OPAC'))),
    'msfs_fresnel_fade': ('Fresnel Fade', CORE + ((P_AO2, 'AO2'),)),
    'msfs_parallax_window': ('Parallax Window', ((P_BASE, 'ALB-G'), (P_ORM, 'ORM'), (P_NML, 'NML-G'),
                                                 (P_EMIS, 'EMIS-R'), (P_BEHIND, 'ALB-R'), (P_AO2, 'AO2'))),
    'msfs_windshield': ('Windshield', ((P_BASE, 'ALB'), (P_ORM, 'RRM'), (P_NML, 'NML'), (P_EMIS, 'ALB-2'),
                                       (P_DCOL, 'MASK-D'), (P_DORM, 'RRM-D'), (P_DNML, 'NML-I'), (P_AO2, 'MASK-R'),
                                       (P_WIPE, 'WIPE'), (P_WS_DNML, 'NML-D'), (P_SCR, 'NML-S'), (P_IRID, 'IRID'),
                                       (P_BUG_ALB, 'ALB-B'), (P_BUG_MSK, 'MASK-B'))),
    'msfs_tree': ('Tree', FULL + ((P_FOL, 'FOL'),)),
    'msfs_vegetation': ('Vegetation', FULL + ((P_FOL, 'FOL'),)),
    'msfs_tire': ('Tire', CORE + DETAIL + ((P_MUD_MSK, 'MASK-M'), (P_AO2, 'AO2'), (P_TIRE, 'MASK-T'),
                                           (P_MUD_NML, 'NML-M'))),
    'msfs_invisible': ('Invisible', ()),
    'msfs_environment_occluder': ('Environment Occluder', ()),
}


def material_type(material):
    return getattr(material, 'msfs_material_type', 'NONE') or 'NONE'


def type_label(material):
    kind = material_type(material)
    return TYPES[kind][0] if kind in TYPES else ('not an MSFS material' if kind == 'NONE' else kind)


def _image(material, prop):
    image = getattr(material, prop, None)
    return image if isinstance(image, bpy.types.Image) else None


def slot_roles(material):
    """[(slot property, role, labels)] the material's type uses, with the exporter's conditions applied: Clearcoat's
    colour slot only without inverse roughness, Windshield's iridescent slot only with iridescence on; the detail maps
    become secondary maps when a blend mask is set (SDK)."""
    kind = material_type(material)
    if kind not in TYPES:
        return []
    masked = _image(material, P_MASK) is not None or (kind == 'msfs_geo_decal_blendmasked'
                                                      and _image(material, P_DMASK) is not None)
    inverse = kind == 'msfs_clearcoat' and getattr(material, 'msfs_clearcoat_inverse_roughness', False)
    result = []
    for prop, role in TYPES[kind][1]:
        if prop == P_COAT and inverse:
            continue
        if prop == P_IRID and not getattr(material, 'msfs_use_iridescent', False):
            continue
        if masked and role in ('ALB-D', 'ORM-D'):
            role = role[:3] + '-2'
        labels = ROLES[role]
        if role == 'ORM' and kind in ('msfs_anisotropic', 'msfs_hair'):
            labels = ('O', 'Rx', 'M')
        elif role == 'ORM' and inverse:
            labels = ('O', 'Cr', 'M')
        result.append((prop, role, labels))
    return result


def needs_16(role, kind):
    return role in NEEDS_16 or kind in NEEDS_16_ON.get(role, ())


# --- BitmapSlots ---------------------------------------------------------------------------------------------------

# Blender slot property: (BitmapSlot, base user flags, ForceNoAlpha) of the XML the MSFS 2024 export writes for its
# image, in the order texture_lib/__init__.py (_get_gltf_material_config) reads the glTF slots. Mirrors
# io_scene_gltf2_msfs_fss/io/exp/texture_lib/gltf_material.py (glTF slot to BitmapSlot; the BitmapSlot is its index in
# bitmap_config.py, not the name in its comments) and the material extensions that put the image in that glTF slot
# (io/com/extensions/material/*.py). gltf_material.py's only base flag, FL_BITMAP_SDF, belongs to the distance field
# layer, which no Blender property exports. The ORM image is also the glTF occlusion texture, which TextureLib skips
# then. BitmapSlot '': the glTF slot TextureLib does not read, so no XML is written for it.
BITMAP_SLOTS = {
    P_BASE: ('MTL_BITMAP_DECAL0', '', False),
    P_ORM: ('MTL_BITMAP_METAL_ROUGH_AO', '', True),
    P_NML: ('MTL_BITMAP_NORMAL', '', False),
    P_EMIS: ('MTL_BITMAP_EMISSIVE', '', False),
    P_MASK: ('MTL_BITMAP_BLENDMASK', '', False),
    P_DCOL: ('MTL_BITMAP_DETAILDIFFUSE', '', False),
    P_DNML: ('MTL_BITMAP_ADD_NORMAL', '', False),
    P_DORM: ('MTL_BITMAP_DETAIL_METAL_ROUGH_AO', '', False),
    P_DIR: ('MTL_BITMAP_ANISO_DIR_ROUGH', '', True),
    P_BEHIND: ('MTL_BITMAP_ADD_DECAL0', '', False),
    P_WIPE: ('MTL_BITMAP_WIPERMASK', '', False),
    P_WS_DNML: ('MTL_BITMAP_WINDSHIELDDETAILNORMAL', '', False),
    P_SCR: ('MTL_BITMAP_SCRATCHESNORMAL', '', False),
    P_BUG_ALB: ('MTL_BITMAP_WINDSHIELDINSECTS', '', False),
    P_BUG_MSK: ('MTL_BITMAP_WINDSHIELDINSECTSMASK', '', False),
    P_FOL: ('MTL_BITMAP_ALPHABLENDMASK', '', False),
    P_AO2: ('MTL_BITMAP_OCCLUSION', '', False),
    P_COAT: ('MTL_BITMAP_CLEARCOATCOLORROUGHNESS', '', False),
    P_COAT_NML: ('MTL_BITMAP_CLEARCOATNORMAL', '', False),
    P_DMASK: ('MTL_BITMAP_BLENDMASK', '', False),
    P_IRID: ('MTL_BITMAP_IRIDESCENTTHICKNESS', '', False),
    P_WEAR_ALB: ('MTL_BITMAP_DIRTOVERLAY', '', False),
    P_WEAR_ORM: ('MTL_BITMAP_DIRTOVERLAY_METAL_ROUGH_AO', '', False),
    P_TIRE: ('MTL_BITMAP_TIREDETAILS', '', False),
    P_MUD_NML: ('MTL_BITMAP_TIREMUDNORMAL', '', False),
    P_OPAC: ('', '', False),
    P_MUD_MSK: ('', '', False),
}
# the detail maps when the detail blend mask (msfs_blend_mask_texture, not the decal's) is set
BITMAP_SLOTS_MASKED = {P_DCOL: 'MTL_BITMAP_ADD_DECAL0', P_DNML: 'MTL_BITMAP_DETAILNORMAL',
                       P_DORM: 'MTL_BITMAP_ADD_METAL_ROUGH_AO'}
WINDSHIELD_ONLY = {P_WIPE, P_WS_DNML, P_SCR, P_BUG_ALB, P_BUG_MSK}


def _exported(material, kind, prop):
    """True when the MSFS 2024 export writes the slot's image into the glTF (the extensions' own conditions)."""
    if prop in WINDSHIELD_ONLY:
        return kind == 'msfs_windshield'
    if prop == P_BEHIND:
        return kind == 'msfs_parallax_window'
    if prop == P_COAT:
        return kind == 'msfs_clearcoat' and not getattr(material, 'msfs_clearcoat_inverse_roughness', False)
    if prop == P_COAT_NML:
        return kind == 'msfs_clearcoat'
    if prop == P_DMASK:
        return bool(getattr(material, 'msfs_decal_mode', ''))
    if prop == P_IRID:
        return getattr(material, 'msfs_use_iridescent', False)
    if prop == P_OPAC:
        return kind in ('msfs_sss', 'msfs_hair')
    return True


def bitmap_slots(material):
    """[(slot property, BitmapSlot, base user flags, ForceNoAlpha)] of the material's images the export writes."""
    kind = material_type(material)
    masked = _image(material, P_MASK) is not None
    result = []
    for prop, (slot, base, no_alpha) in BITMAP_SLOTS.items():
        if _image(material, prop) is None or not _exported(material, kind, prop):
            continue
        result.append((prop, BITMAP_SLOTS_MASKED.get(prop, slot) if masked else slot, base, no_alpha))
    return result


def short_slot(slot):
    return slot.removeprefix('MTL_BITMAP_') if slot else 'no XML'


# --- what the export writes ----------------------------------------------------------------------------------------

def exporter():
    """The exporter's texture_folder module (part 1), or None when the exporter is not enabled."""
    if not hasattr(bpy.types.Scene, 'msfs_fss_texture_folder'):
        return None
    from io_scene_gltf2_msfs_fss import texture_folder
    return texture_folder


def exported_objects(scene, view_layer):
    """The objects the MSFS 2024 export writes (S34.3): those of the enabled layers of the enabled multi-exporter
    presets, as the multi-exporter takes them (MultiExporterPreset.get_preset_objects: each layer's own collection
    objects; every collection has its own layer) and only those in the view layer; without an enabled preset, the
    visible objects of the view layer (what the FSS deploy exports)."""
    in_view = set(view_layer.objects)
    presets = [preset for preset in getattr(scene, 'msfs_multi_exporter_presets', ()) if preset.enabled]
    if not presets:
        return {obj for obj in in_view if obj.visible_get(view_layer=view_layer)}
    found = set()
    for preset in presets:
        for layer in preset.layers:
            collection = layer.collection if layer.enabled else None
            if collection is not None:
                found.update(obj for obj in collection.objects if obj in in_view)
    return found


def exported_materials(objects):
    """The materials of the objects' faces (every slot of an object without faces of its own), by name."""
    found = set()
    for obj in objects:
        slots = [slot.material for slot in obj.material_slots]
        if obj.type == 'MESH' and obj.data is not None:
            mi = np.zeros(len(obj.data.polygons), np.int64)
            obj.data.polygons.foreach_get('material_index', mi)
            found.update(slots[index] for index in np.unique(mi).tolist() if index < len(slots))
        else:
            found.update(slots)
    found.discard(None)
    return sorted(found, key=lambda material: material.name)


def export_file(image):
    """The file name the glTF gives the image: its file's name, else the image name (Khronos exporter, image.py
    __gather_name), as a PNG."""
    stem, extension = os.path.splitext(os.path.basename(image.filepath))
    if not stem or extension.lower() not in ('.png', '.jpg', '.jpeg'):
        stem = os.path.splitext(image.name)[0]
    return stem + '.png'


def _compatible(slot, other):
    """Asobo's BitmapConfig.is_compatible_id: two BitmapSlots one image may have in one export."""
    from io_scene_gltf2_msfs_fss.io.exp.texture_lib.bitmap_config import BitmapConfig, BitmapSlots
    return BitmapConfig(BitmapSlots.get_index_from_flag(slot)).is_compatible_id(
        BitmapConfig(BitmapSlots.get_index_from_flag(other)))


def flag_text(texture):
    """The image flags the export writes into the texture's XML (empty without the image Asobo reads)."""
    flags = getattr(bpy.data.images.get(texture.image), 'msfs_flags', None) if texture.image else None
    return flags.to_string() if flags is not None else ''


def read_xml(texture, folder):
    """Fill the texture's PNG and XML fields from the folder, the XML as Asobo's XmlSerializer reads it."""
    from io_scene_gltf2_msfs_fss.io.exp.texture_lib.bitmap_config import BitmapSlots
    from io_scene_gltf2_msfs_fss.io.exp.texture_lib.texture_xml import XmlSerializer
    png = folder / texture.name
    xml = Path(str(png) + '.xml')
    texture.png = png.is_file()
    texture.xml = xml.is_file()
    serializer = XmlSerializer(str(xml))
    try:
        texture.xml_valid = texture.xml and serializer.open()
    except OSError:
        texture.xml_valid = False
    config = serializer.xml_bmp_config
    texture.xml_slot = (BitmapSlots.get_flag_from_index(config.material_bitmap) or '') if texture.xml_valid else ''
    texture.xml_flags = (config.user_flags or '') if texture.xml_valid else ''
    texture.xml_no_alpha = bool(config.force_no_alpha) if texture.xml_valid else False


def xml_state(settings, texture):
    """'' (no folder, or no XML for the slot), 'no PNG', 'missing', 'matches' or 'differs' (what the export would
    rewrite: Asobo's BitmapConfig.compare of slot, user flags and ForceNoAlpha)."""
    if not settings.xml_folder or not texture.slot:
        return ''
    if not texture.png:
        return 'no PNG'
    if not texture.xml:
        return 'missing'
    if texture.xml_valid and (texture.xml_slot, texture.xml_flags, texture.xml_no_alpha) == (
            texture.slot, texture.base_flags + flag_text(texture), texture.no_alpha):
        return 'matches'
    return 'differs'


def texture_warn(settings, texture):
    return (texture.conflict or not texture.slot or not texture.image
            or xml_state(settings, texture) in ('no PNG', 'missing', 'differs'))


# --- files ---------------------------------------------------------------------------------------------------------

PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
PNG_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}  # colour type: channels


def png_header(data):
    """(bit depth, colour type) from a PNG's first 26 bytes, or None for another format."""
    if len(data) < 26 or data[:8] != PNG_SIGNATURE or data[12:16] != b'IHDR':
        return None
    return data[24], data[25]


def image_path(image):
    return os.path.normpath(bpy.path.abspath(image.filepath, library=image.library)) if image.filepath else ''


def stamp(path):
    """The file's size and modification time: a data check is reused while they stay the same."""
    try:
        st = os.stat(path)
    except OSError:
        return ''
    return f'{st.st_size}:{st.st_mtime_ns}'


def read_file(image):
    """(status, bits, colour type, path, stamp) of an image's file: status ok, packed, missing, no file or other
    format."""
    path = image_path(image)
    if image.packed_file is not None:
        head = png_header(bytes(image.packed_file.data[:26]))
        return ('packed', head[0], head[1], path, '') if head else ('other', 0, 0, path, '')
    if image.source != 'FILE' or not path:
        return 'no file', 0, 0, path, ''
    try:
        with open(path, 'rb') as f:
            head = png_header(f.read(26))
    except OSError:
        return 'missing', 0, 0, path, ''
    if head is None:
        return 'other', 0, 0, path, stamp(path)
    return 'ok', head[0], head[1], path, stamp(path)


# --- data check ----------------------------------------------------------------------------------------------------

GRID_SHARE = 0.9  # a channel with this share of its values on the 8-bit grid holds 8-bit data


def file_channels(colour_type):
    """Indices into Blender's RGBA pixels of the file's channels, in file order."""
    return {0: (0,), 2: (0, 1, 2), 3: (0,), 4: (0, 3), 6: (0, 1, 2, 3)}[colour_type]


def channel_depth(values):
    """'flat' (two values or fewer), '8' (8-bit data stored in 16 bits) or '16', for uint16 values."""
    low, high = values.min(), values.max()
    if not np.count_nonzero((values != low) & (values != high)):
        return 'flat'
    return '8' if np.count_nonzero(values % 257 == 0) >= GRID_SHARE * values.size else '16'


def check_file(path, colour_type):
    """The data depth of each channel of a 16-bit PNG, comma-separated in file order. Loaded into a temporary
    Non-Color image (exact values, journal Session 33), removed afterwards."""
    image = bpy.data.images.load(path, check_existing=False)
    try:
        image.colorspace_settings.name = 'Non-Color'
        width, height = image.size
        pixels = np.empty(width * height * 4, np.float32)
        image.pixels.foreach_get(pixels)
    finally:
        bpy.data.images.remove(image)
    pixels = pixels.reshape(-1, 4)
    depths = []
    for index in file_channels(colour_type):
        values = np.rint(pixels[:, index] * 65535.0).astype(np.uint16)
        depths.append(channel_depth(values))
    return ','.join(depths)


# --- what a slot row shows -----------------------------------------------------------------------------------------

def tokens(slot, depths=None):
    """[(text, warn)] for a slot row's channels. depths: the data check's result for the file, or None."""
    if slot.status in ('missing', 'no file'):
        return [(slot.status, True)]
    if slot.status == 'other':
        return [('?', False)]
    if slot.colour_type == 3:
        return [('indexed', True)]
    count = PNG_CHANNELS.get(slot.colour_type, 0)
    names = ('L', 'A') if count <= 2 else RGBA  # the file's own channel names
    alpha = count - 1 if count in (2, 4) else None
    labels = tuple(slot.labels.split(',')) if slot.labels else ()
    data = depths.split(',') if depths else []
    result = []
    for index in range(count):
        if len(labels) == 1:
            # a one-channel role: an alpha mask reads the alpha when there is one, the others the first channel
            used = index == (alpha if labels == ('A',) and alpha is not None else 0)
            label = labels[0] if used else names[index]
            grey_in_colour = False
        elif count <= 2:
            # a grey file in a colour role: its grey channel is warned, its alpha is used when the role has one
            used = index == alpha and len(labels) == 4
            label = labels[3] if used else names[index]
            grey_in_colour = index == 0
        else:
            used = index < len(labels)
            label = labels[index] if used else names[index]
            grey_in_colour = False
        text = f'{label}{slot.bits}'
        warn = not used or grey_in_colour or (slot.need16 and slot.bits < 16)
        if used and slot.alpha_warn and index == alpha:
            warn = True
        if index < len(data) and data[index] == '8' and slot.bits == 16:
            text += '→8'
            warn = warn or (used and slot.need16)
        result.append((text, warn))
    return result


def depth_for(settings, slot):
    """The kept data check of a slot's file, when it is still current."""
    if slot.status != 'ok' or slot.bits != 16:
        return None
    entry = settings.checks.get(slot.path)
    return entry.depths if entry is not None and entry.stamp == slot.stamp else None


def slot_warn(settings, slot):
    return slot.unused_slot or any(warn for _text, warn in tokens(slot, depth_for(settings, slot)))


def to_check(settings):
    """[(path, colour type)] of the 16-bit PNG files of the rows without a current data check, each once."""
    found = {}
    for row in settings.rows:
        for slot in row.slots:
            if slot.status == 'ok' and slot.bits == 16 and depth_for(settings, slot) is None:
                found.setdefault(slot.path, slot.colour_type)
    return list(found.items())


# --- data ----------------------------------------------------------------------------------------------------------

class FSS_TextureSlot(bpy.types.PropertyGroup):
    # name (built in) is the slot property
    role: bpy.props.StringProperty()
    labels: bpy.props.StringProperty()  # comma-separated channel labels of the role
    file: bpy.props.StringProperty()
    path: bpy.props.StringProperty()
    stamp: bpy.props.StringProperty()
    status: bpy.props.StringProperty()  # ok, packed, missing, no file, other
    bits: bpy.props.IntProperty()
    colour_type: bpy.props.IntProperty()
    need16: bpy.props.BoolProperty()
    alpha_warn: bpy.props.BoolProperty()  # albedo of an Opaque material: its alpha is not used
    unused_slot: bpy.props.BoolProperty()  # the material's type does not use this slot


class FSS_TextureSetRow(bpy.types.PropertyGroup):
    # name (built in) is the material name
    kind: bpy.props.StringProperty()  # the MSFS type's label
    slots: bpy.props.CollectionProperty(type=FSS_TextureSlot)


class FSS_TextureCheck(bpy.types.PropertyGroup):
    # name (built in) is the file path
    stamp: bpy.props.StringProperty()
    depths: bpy.props.StringProperty()  # per channel in file order: 16, 8 or flat


class FSS_TextureFile(bpy.types.PropertyGroup):
    # name (built in) is the file name in the glTF and the texture folder
    image: bpy.props.StringProperty()  # the image whose flags the export writes ('' none is named like the file)
    slot: bpy.props.StringProperty()  # the BitmapSlot of its XML: of its first slot, as TextureLib ('' no XML)
    slots: bpy.props.StringProperty()  # every BitmapSlot it gets, comma-separated
    base_flags: bpy.props.StringProperty()
    no_alpha: bpy.props.BoolProperty()
    conflict: bpy.props.BoolProperty()  # a slot needs a BitmapSlot that is not compatible with the first
    png: bpy.props.BoolProperty()  # the PNG is in the texture folder
    xml: bpy.props.BoolProperty()  # its XML is there
    xml_valid: bpy.props.BoolProperty()  # and Asobo's XmlSerializer reads it
    xml_slot: bpy.props.StringProperty()
    xml_flags: bpy.props.StringProperty()
    xml_no_alpha: bpy.props.BoolProperty()


class FSS_TextureSetsSettings(bpy.types.PropertyGroup):
    rows: bpy.props.CollectionProperty(type=FSS_TextureSetRow)
    checks: bpy.props.CollectionProperty(type=FSS_TextureCheck)
    textures: bpy.props.CollectionProperty(type=FSS_TextureFile)
    xml_folder: bpy.props.StringProperty()  # the texture folder the XML states were read from ('' none)
    show: bpy.props.EnumProperty(
        name='Show', items=(('ALL', 'All', 'List every used material'),
                            ('WARNINGS', 'Warnings', 'List only materials with a warning')))


def refresh(scene, used_materials):
    """Fill Scene.fss_texture_sets.rows from the materials (called by the Materials Refresh; reads only headers)."""
    settings = scene.fss_texture_sets
    settings.rows.clear()
    for material in used_materials:
        kind = material_type(material)
        row = settings.rows.add()
        row.name = material.name
        row.kind = type_label(material)
        if kind == 'NONE':
            continue
        used = slot_roles(material)
        used_props = {prop for prop, _role, _labels in used}
        opaque = getattr(material, 'msfs_alpha_mode', 'OPAQUE') == 'OPAQUE'
        entries = [(prop, role, labels, False) for prop, role, labels in used]
        entries += [(prop, SLOT_ROLE[prop], ROLES[SLOT_ROLE[prop]], True) for prop in SLOT_ORDER
                    if prop not in used_props and _image(material, prop) is not None]
        for prop, role, labels, unused in entries:
            image = _image(material, prop)
            if image is None:
                continue
            slot = row.slots.add()
            slot.name = prop
            slot.role = role
            slot.labels = ','.join(labels)
            slot.file = os.path.basename(image_path(image)) or image.name
            slot.status, slot.bits, slot.colour_type, slot.path, slot.stamp = read_file(image)
            slot.need16 = needs_16(role, kind)
            slot.alpha_warn = role == 'ALB' and opaque
            slot.unused_slot = unused


def refresh_textures(context):
    """Fill Scene.fss_texture_sets.textures from what the export writes, after reading each XML that was never read
    into its images (S34.2; called by the Materials Refresh, so also when a file opens)."""
    scene = context.scene
    settings = scene.fss_texture_sets
    settings.textures.clear()
    texture_folder = exporter()
    folder = texture_folder.texture_folder(scene) if texture_folder is not None else None
    if folder is not None and not folder.is_dir():
        folder = None
    settings.xml_folder = str(folder) if folder is not None else ''
    if texture_folder is None:
        return
    found = {}  # file name: [(BitmapSlot, base flags, ForceNoAlpha)] in the order TextureLib reads them
    for material in exported_materials(exported_objects(scene, context.view_layer)):
        for prop, slot, base, no_alpha in bitmap_slots(material):
            found.setdefault(export_file(_image(material, prop)), []).append((slot, base, no_alpha))
    for name in sorted(found, key=str.lower):
        configs = found[name]
        texture = settings.textures.add()
        texture.name = name
        stem = Path(name).stem
        images = texture_folder.images_named(stem)
        texture.image = images[0].name if images else ''
        with_xml = [config for config in configs if config[0]]
        texture.slots = ', '.join(dict.fromkeys(short_slot(slot) for slot, _b, _n in configs))
        if not with_xml:
            continue
        texture.slot, texture.base_flags, texture.no_alpha = with_xml[0]
        texture.conflict = any(not _compatible(texture.slot, slot) for slot, _b, _n in with_xml[1:])
        if folder is not None:
            texture_folder.read_xml_once(stem, folder / (name + '.xml'))
            read_xml(texture, folder)


# --- Write XMLs ----------------------------------------------------------------------------------------------------

class FSS_OT_TextureXmlWrite(bpy.types.Operator):
    bl_idname = 'fss.texture_xml_write'
    bl_label = 'Write XMLs'
    bl_description = ('Write the texture XML of each listed texture whose PNG is in the MSFS Texture Folder, as the '
                      'MSFS 2024 export does, without exporting. An XML never read is first read into its images')
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        settings = context.scene.fss_texture_sets
        return bool(settings.xml_folder) and len(settings.textures) > 0 and exporter() is not None

    def execute(self, context):
        settings = context.scene.fss_texture_sets
        texture_folder = exporter()
        folder = texture_folder.texture_folder(context.scene)
        if folder is None or not folder.is_dir() or str(folder) != settings.xml_folder:
            self.report({'ERROR'}, 'The MSFS Texture Folder changed or does not exist: press Refresh')
            return {'CANCELLED'}
        from io_scene_gltf2_msfs_fss.io.com import msfs_logs
        from io_scene_gltf2_msfs_fss.io.exp import texture_lib
        from io_scene_gltf2_msfs_fss.io.exp.texture_lib.bitmap_config import BitmapConfig, BitmapSlots
        texture_lib.MSFS2024_LOGGER = msfs_logs.get_logger()  # create_xml logs there; the export sets it the same way
        written, matched, missing, spaces, failed = 0, 0, [], [], []
        for texture in settings.textures:
            if not texture.slot:
                continue
            stem = Path(texture.name).stem
            png = folder / texture.name
            if not png.is_file():
                missing.append(texture.name)
                continue
            if ' ' in stem:  # the export writes no XML for it either (texture_lib.export_gltfs_texture_lib)
                spaces.append(texture.name)
                continue
            texture_folder.read_xml_once(stem, Path(str(png) + '.xml'))
            read_xml(texture, folder)
            if xml_state(settings, texture) == 'matches':
                texture_folder.mark_written(stem)  # the file says what Blender says: it counts as read
                matched += 1
                continue
            config = BitmapConfig(BitmapSlots.get_index_from_flag(texture.slot),
                                  texture.base_flags + flag_text(texture), texture.no_alpha)
            texture_lib.create_xml((config, png.resolve().as_posix()))
            read_xml(texture, folder)
            if xml_state(settings, texture) == 'matches':
                texture_folder.mark_written(stem)  # written from Blender's flags: a later read never takes it back
                written += 1
            else:
                failed.append(texture.name)
        text = f'Wrote {written} XML(s), {matched} already matched'
        if missing:
            text += '; PNG not in the folder: ' + ', '.join(missing)
        if spaces:
            text += '; not written (a space in the name): ' + ', '.join(spaces)
        if failed:
            text += '; could not write: ' + ', '.join(failed)
        self.report({'WARNING'} if missing or spaces or failed else {'INFO'}, text)
        return {'FINISHED'}


# --- Check Data Depth ----------------------------------------------------------------------------------------------

_progress = None  # dict: index, count, file
_cancel_requested = False


def _redraw():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def _keep(settings, path, depths):
    entry = settings.checks.get(path) or settings.checks.add()
    entry.name = path
    entry.stamp = stamp(path)
    entry.depths = depths


class FSS_OT_TextureDepthCheck(bpy.types.Operator):
    bl_idname = 'fss.texture_depth_check'
    bl_label = 'Check Data Depth'
    bl_description = ('Read the pixels of each 16-bit PNG of the list: whether a channel holds real 16-bit data or 8-bit '
                      'values saved as 16-bit. Results are kept in the .blend until the file changes; Esc stops')
    bl_options = {'REGISTER'}

    _timer = None

    @classmethod
    def poll(cls, context):
        return _progress is None and len(context.scene.fss_texture_sets.rows) > 0

    def execute(self, context):
        global _progress, _cancel_requested
        settings = context.scene.fss_texture_sets
        self._files = to_check(settings)
        self._index = 0
        self._failed = []
        self._t_start = time.perf_counter()
        if bpy.app.background or not self._files:
            for path, colour_type in self._files:
                self._step(settings, path, colour_type)
            return self._finish(context)
        _cancel_requested = False
        _progress = {'index': 1, 'count': len(self._files), 'file': os.path.basename(self._files[0][0])}
        self._timer = context.window_manager.event_timer_add(0.01, window=context.window)
        context.window_manager.modal_handler_add(self)
        _redraw()
        return {'RUNNING_MODAL'}

    def _step(self, settings, path, colour_type):
        try:
            _keep(settings, path, check_file(path, colour_type))
        except Exception as ex:  # an unreadable file: reported, the others go on
            self._failed.append(f'{os.path.basename(path)}: {ex}')

    def _finish(self, context, cancelled=False):
        global _progress, _cancel_requested
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        _progress = None
        _cancel_requested = False
        if not bpy.app.background:
            _redraw()
        done = self._index if not bpy.app.background else len(self._files)
        text = (f'Checked {done - len(self._failed)} of {len(self._files)} 16-bit file(s) in '
                f'{time.perf_counter() - self._t_start:.1f} s' + (', cancelled' if cancelled else ''))
        if self._failed:
            self.report({'WARNING'}, text + '; not read: ' + '; '.join(self._failed))
        else:
            self.report({'INFO'}, text if self._files else 'Every 16-bit file is checked already')
        return {'FINISHED'}

    def modal(self, context, event):
        if event.type == 'ESC' or _cancel_requested:
            return self._finish(context, cancelled=True)
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}
        if self._index >= len(self._files):
            return self._finish(context)
        path, colour_type = self._files[self._index]
        self._step(context.scene.fss_texture_sets, path, colour_type)
        self._index += 1
        if self._index < len(self._files):
            _progress.update(index=self._index + 1, file=os.path.basename(self._files[self._index][0]))
        _redraw()
        return {'RUNNING_MODAL'}


class FSS_OT_TextureDepthCancel(bpy.types.Operator):
    bl_idname = 'fss.texture_depth_cancel'
    bl_label = 'Cancel'
    bl_description = 'Stop Check Data Depth after the file in work (as Esc)'
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return _progress is not None

    def execute(self, context):
        global _cancel_requested
        _cancel_requested = True
        return {'FINISHED'}


# --- panel ---------------------------------------------------------------------------------------------------------

ROLE_UNITS = 3.0
TOKEN_UNITS = 3.0


def _draw_slot(layout, settings, slot):
    line = layout.row(align=True)
    role = line.row(align=True)
    role.ui_units_x = ROLE_UNITS
    role.alert = slot.unused_slot
    role.label(text=slot.role)
    cells = line.row(align=True)
    for text, warn in tokens(slot, depth_for(settings, slot)):
        cell = cells.row(align=True)
        cell.ui_units_x = TOKEN_UNITS
        cell.alert = warn
        cell.label(text=text, icon='ERROR' if warn else 'NONE')
    note = slot.file
    if slot.unused_slot:
        note += '  (slot not used by this type)'
    elif slot.status == 'packed':
        note += '  (packed)'
    elif slot.status == 'ok' and slot.bits == 16 and depth_for(settings, slot) is None:
        note += '  (data not checked)'
    line.label(text=note)


def _row_warn(settings, row):
    return any(slot_warn(settings, slot) for slot in row.slots)


# image.msfs_flags: (property, text on the row); the anisotropic level is the menu after them
FLAG_CELLS = (('msfs_image_quality_high', 'HQ'), ('msfs_image_alpha_preserv', 'Alpha'),
              ('msfs_image_no_reduction', 'NoRed'), ('msfs_image_no_mipmap', 'NoMip'),
              ('msfs_image_prec_inv_avg', 'InvAvg'))


def _folder_note(scene, settings, texture_folder):
    folder = texture_folder.texture_folder(scene)
    if folder is None:
        return 'Set the folder to compare and write the XMLs'
    if not folder.is_dir():
        return 'The folder does not exist'
    if str(folder) != settings.xml_folder:
        return 'The folder changed: press Refresh'
    return ''


def _draw_texture(layout, settings, texture):
    state = xml_state(settings, texture)
    column = layout.column(align=True)
    line = column.row(align=True)
    line.label(text=texture.name, icon='ERROR' if texture_warn(settings, texture) else 'IMAGE_DATA')
    cell = line.row(align=True)
    cell.alert = texture.conflict or not texture.slot
    cell.label(text=texture.slots)
    cell = line.row(align=True)
    cell.ui_units_x = 4.0
    cell.alert = state in ('no PNG', 'missing', 'differs')
    cell.label(text=state)
    flags = getattr(bpy.data.images.get(texture.image), 'msfs_flags', None) if texture.image else None
    if flags is not None:
        cells = column.row(align=True)
        for prop, text in FLAG_CELLS:
            cells.prop(flags, prop, text=text, toggle=True)
        cells.prop(flags, 'msfs_image_anisotropic', text='')
    else:
        column.label(text=f'No image named {Path(texture.name).stem}: the export writes no flags', icon='ERROR')
    if texture.conflict:
        column.label(text='Used in slots that need different BitmapSlots', icon='ERROR')
    if not texture.slot:
        column.label(text='TextureLib writes no XML for this slot', icon='ERROR')
    if state == 'differs':
        xml = (f"{short_slot(texture.xml_slot)} {texture.xml_flags or 'no flags'}"
               + (' ForceNoAlpha' if texture.xml_no_alpha else '')) if texture.xml_valid else 'not readable'
        column.label(text=f'XML: {xml}')


def _draw_xmls(layout, context, settings):
    """The texture XMLs of what the MSFS 2024 export writes (journal Session 34, part 2)."""
    box = layout.box()
    box.label(text='Texture XMLs (MSFS 2024 export)', icon='FILE')
    texture_folder = exporter()
    if texture_folder is None:
        box.label(text='The MSFS exporter add-on is not enabled', icon='INFO')
        return
    box.prop(context.scene, 'msfs_fss_texture_folder', text='Folder')
    note = _folder_note(context.scene, settings, texture_folder)
    if note:
        box.label(text=note, icon='INFO')
    box.operator(FSS_OT_TextureXmlWrite.bl_idname, icon='FILE_TICK')
    shown = 0
    for texture in settings.textures:
        if settings.show == 'WARNINGS' and not texture_warn(settings, texture):
            continue
        shown += 1
        _draw_texture(box, settings, texture)
    if not shown:
        box.label(text='No texture with a warning' if settings.show == 'WARNINGS' else 'No exported texture')


class FSS_PT_TextureSets(bpy.types.Panel):
    bl_idname = 'FSS_PT_texture_sets'
    bl_label = 'Texture Sets'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'FSS MSFS Tools'
    bl_parent_id = 'FSS_PT_materials'
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 1

    def draw(self, context):
        layout = self.layout
        settings = context.scene.fss_texture_sets
        if not context.scene.fss_materials.scanned:
            layout.label(text='Press Refresh to list the texture sets', icon='INFO')
            return
        if _progress is not None:
            box = layout.box()
            box.progress(factor=(_progress['index'] - 1) / max(_progress['count'], 1), type='BAR',
                         text=f"Checking {_progress['index']} of {_progress['count']}: {_progress['file']}")
            box.operator(FSS_OT_TextureDepthCancel.bl_idname, text='Cancel', icon='CANCEL')
        else:
            pending = len(to_check(settings))
            text = f'Check Data Depth ({pending} not checked)' if pending else 'Check Data Depth'
            layout.operator(FSS_OT_TextureDepthCheck.bl_idname, text=text, icon='VIEWZOOM')
        layout.row().prop(settings, 'show', expand=True)
        _draw_xmls(layout, context, settings)
        shown = 0
        for row in settings.rows:
            warn = _row_warn(settings, row)
            if settings.show == 'WARNINGS' and not warn:
                continue
            shown += 1
            box = layout.box()
            head = box.row()
            head.label(text=row.name, icon='ERROR' if warn else 'MATERIAL')
            head.label(text=row.kind)
            if not row.slots:
                box.label(text='no texture')
            for slot in row.slots:
                _draw_slot(box, settings, slot)
        if not shown:
            layout.label(text='No material with a warning' if settings.show == 'WARNINGS' else 'No used material')


CLASSES = (FSS_TextureSlot, FSS_TextureSetRow, FSS_TextureCheck, FSS_TextureFile, FSS_TextureSetsSettings,
           FSS_OT_TextureDepthCheck, FSS_OT_TextureDepthCancel, FSS_OT_TextureXmlWrite, FSS_PT_TextureSets)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.fss_texture_sets = bpy.props.PointerProperty(type=FSS_TextureSetsSettings)


def unregister():
    del bpy.types.Scene.fss_texture_sets
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
