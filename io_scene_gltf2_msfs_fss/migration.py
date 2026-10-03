"""
One-time migration of materials authored with the MSFS 2020 add-on.

The .blend and the UI use MSFS 2024 meaning for material properties; MSFS 2020 exports convert back
(`_msfs2020/compat.py`). A material whose preview node tree was built by the MSFS 2020 add-on still stores
MSFS 2020 meaning, so the first time it is used here it is migrated:

1. Values: every property whose MSFS 2020 default differs from the MSFS 2024 one is stored explicitly with
   the MSFS 2020 default when the artist never set it (an unset value would otherwise silently read the
   MSFS 2024 default). The emissive strength becomes cd/m2: `value x MSFS 2020 emissive reference`.
   Values are written to the property storage directly, so no MSFS 2024 update callback runs against the
   MSFS 2020 node tree.
2. Node tree: rebuilt as the MSFS 2024 preview graph, like the MSFS 2024 add-on does for every material on
   load. Artists edit material parameters, not graphs, so the look is kept as far as the graphs allow.
3. The material is marked (MIGRATED_KEY) so it is never converted twice.

Runs on file load, after Append, and before every glTF export (scripts may export before load handlers ran).
"""

import bpy

from ._msfs2020 import compat


def _property_store(material, create=False):
    # Blender 5.0+ keeps bpy.props values apart from user custom properties
    getter = getattr(material, "bl_system_properties_get", None)
    return getter(do_create=create) if getter else material


def _snapshot(value):
    if isinstance(value, bpy.types.ID):  # pointer properties (textures) store the datablock itself
        return value
    if hasattr(value, "to_list"):  # IDPropertyArray
        return value.to_list()
    if hasattr(value, "to_dict"):  # IDPropertyGroup
        return value.to_dict()
    return value


def rebuild_preview_tree(material):
    """
    Rebuild the MSFS 2024 preview graph of a material without changing any of its values.

    The MSFS 2024 builders reset every property the material type does not use to its default (by design:
    MSFS 2024 exports ignore them). The unified add-on also exports MSFS 2020, which uses some of them
    (e.g. `msfs_no_cast_shadow` on decals), so values are restored exactly as stored, without callbacks.
    Restored properties are by definition not part of that type's MSFS 2024 graph.
    """
    from .blender.material.msfs_material_properties_update import MSFS2024_MaterialPropUpdate
    store = _property_store(material)
    before = {k: _snapshot(v) for k, v in store.items()} if store is not None else {}
    MSFS2024_MaterialPropUpdate.update_msfs_material_type(material=material, rebuild_native_mat=False)
    store = _property_store(material, create=bool(before))
    if store is None:
        return
    for key in [k for k in store.keys() if k not in before]:
        del store[key]
    for key, value in before.items():
        if key in store and _snapshot(store[key]) == value:
            continue
        if value is None:  # empty pointer (texture slot): unset reads as None as well
            store.pop(key, None)
            continue
        try:
            store[key] = value
        except TypeError:
            # Stored with another type than the current definition (e.g. saved by an older add-on
            # version) and re-created by the rebuild: put the original data back as it was
            store.pop(key, None)
            store[key] = value


def legacy_materials():
    return [m for m in bpy.data.materials if not m.library and compat.is_unmigrated_legacy(m)]


def migrate_materials(scene=None) -> list:
    """Migrate every unmigrated legacy material; returns the migrated materials."""
    materials = legacy_materials()
    if not materials:
        return []
    reference = compat.msfs2020_emissive_reference(scene)
    defaults = compat.legacy_defaults()

    for material in materials:
        store = _property_store(material, create=True)
        for name, legacy_default in defaults.items():
            if name not in store:
                store[name] = legacy_default
        store[compat.EMISSIVE_SCALE] = float(store[compat.EMISSIVE_SCALE]) * reference
        material[compat.MIGRATED_KEY] = 1
        if material.msfs_material_type != "NONE":
            rebuild_preview_tree(material)

    print(f"[MSFS FSS] Migrated {len(materials)} MSFS 2020 material(s) "
          f"(emissive reference {reference:g} cd/m2 = 1.0)")
    return materials
