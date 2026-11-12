"""Maintainer rules for the bake prototype (Session 2): skip materials, AO tags, animation.

Runs with --factory-startup, so the add-ons are not registered: registered properties are read through
id.bl_system_properties_get() (AGENTS.md pitfall "Registered properties reach glTF extras"). The rules copy those of
fss_blender_tools (uv_autoseam._is_skip_material, tags.is_ao_baked / is_ao_occluder / is_marked_animated) without
importing the add-on, which needs registration.
"""
import re

# fss_blender_tools/uv_autoseam.py
SKIP_MATERIAL_CLASSES = ('DECAL', 'DECAL_EM', 'DECAL_FROST', 'DECAL_BLEND', 'GLASS', 'WNDSHIELD', 'INVIS', 'OCCLUDER')
MSFS_SKIP_MATERIAL_TYPES = {'msfs_decal', 'msfs_geo_decal', 'msfs_geo_decal_frosted', 'msfs_geo_decal_blendmasked',
                            'msfs_glass', 'msfs_windshield', 'msfs_invisible', 'msfs_environment_occluder'}
# io_scene_gltf2_msfs_fss/io/com/extensions/material/asobo_material_common.py: msfs_material_type items, in order
# (an unregistered EnumProperty is stored as the item index)
MSFS_MATERIAL_TYPES = ('NONE', 'msfs_standard', 'msfs_decal', 'msfs_geo_decal_frosted', 'msfs_windshield',
                       'msfs_porthole', 'msfs_glass', 'msfs_clearcoat', 'msfs_parallax_window', 'msfs_anisotropic',
                       'msfs_hair', 'msfs_sss', 'msfs_invisible', 'msfs_fake_terrain', 'msfs_fresnel_fade',
                       'msfs_environment_occluder', 'msfs_ghost', 'msfs_geo_decal_blendmasked', 'msfs_sail',
                       'msfs_propeller', 'msfs_tree', 'msfs_vegetation', 'msfs_tire')
# fss_blender_tools/tags.py
TAGS_KEY = 'fss_tags'
AO_NO_OCCLUDER_PROP = 'fss_ao_no_occluder_tags'
AO_SKIP_BAKE_PROP = 'fss_ao_skip_bake_tags'
ANIMATED_PROP = 'fss_animated_tags'
NO_TEXTURE_PROP = 'fss_no_texture_tags'


def _sys_get(idb, key):
    try:
        sp = idb.bl_system_properties_get()
    except Exception:
        sp = None
    if sp is not None and key in sp:
        return sp[key]
    if key in idb.keys():
        return idb[key]
    return None


def material_type(mat):
    v = _sys_get(mat, 'msfs_material_type')
    if isinstance(v, int):
        return MSFS_MATERIAL_TYPES[v] if 0 <= v < len(MSFS_MATERIAL_TYPES) else f'index {v}'
    return v


def is_skip_material(mat):
    if mat is None:
        return False
    base = re.sub(r'\.\d+$', '', mat.name.upper())
    for c in SKIP_MATERIAL_CLASSES:
        if base == c or base.endswith('_' + c):
            return True
    return material_type(mat) in MSFS_SKIP_MATERIAL_TYPES


def _parse(text):
    if not isinstance(text, str):
        return []
    return [t for t in (p.strip() for p in text.replace(',', ';').split(';')) if t]


def get_tags(obj):
    return _parse(obj.get(TAGS_KEY))


def mark_tags(scene):
    return {p: _parse(_sys_get(scene, p)) for p in (AO_NO_OCCLUDER_PROP, AO_SKIP_BAKE_PROP, ANIMATED_PROP,
                                                     NO_TEXTURE_PROP)}


def is_ao_occluder(obj, marks):
    return not set(get_tags(obj)).intersection(marks[AO_NO_OCCLUDER_PROP])


def is_ao_baked(obj, marks):
    t = set(get_tags(obj))
    return not (t.intersection(marks[AO_SKIP_BAKE_PROP]) or t.intersection(marks[NO_TEXTURE_PROP]))


def is_marked_animated(obj, marks):
    return bool(set(get_tags(obj)).intersection(marks[ANIMATED_PROP]))


def _has_anim(idb):
    ad = idb.animation_data
    if ad is None:
        return False
    return bool(ad.action) or any(len(t.strips) for t in ad.nla_tracks) or bool(len(ad.drivers))


def animation_source(obj):
    """Name of the first object in the parent chain (the object itself first) with an action, NLA strip or driver."""
    o = obj
    while o is not None:
        if _has_anim(o):
            return o.name
        o = o.parent
    return None


def material_flags(obj):
    """(all slots skip, any slot skip, per-slot flags)."""
    flags = [is_skip_material(s.material) for s in obj.material_slots]
    if not flags:
        return False, False, flags
    return all(flags), any(flags), flags
