"""
Read MSFS 2024-registered material properties the way the MSFS 2020 exporter expects them.

Both add-ons store material settings under the same property names, but some definitions differ:

- `msfs_material_type`: the stored value is the item index of the MSFS 2020 list; the MSFS 2024 list
  renames two items at the same index (`msfs_geo_decal` -> `msfs_decal`, `msfs_parallax` ->
  `msfs_parallax_window`) and appends 2024-only types.
- Defaults: a .blend only stores values an artist changed, everything else reads the registered
  default, and a few defaults differ between the add-ons (e.g. `msfs_emissive_scale` 1.0 vs 1000.0).

- Units: `msfs_emissive_scale` is an emission brightness in cd/m2 for MSFS 2024 (default 1000) but a
  1.0-based strength for MSFS 2020.

The .blend stores MSFS 2024 meaning. Materials authored with the MSFS 2020 add-on are migrated once
(`migration.py`). `LegacyMaterialView` wraps a material for the MSFS 2020 export code: the material type is
translated and the emissive strength divided by the scene's MSFS 2020 emissive reference. A legacy material
that was not migrated yet keeps its MSFS 2020 meaning (unset properties return MSFS 2020 defaults).
"""

import struct

import bpy

from .legacy_props import LEGACY_PROPS


def _float32(value):
    return struct.unpack("f", struct.pack("f", value))[0]

_type_map = None       # MSFS 2024 material type identifier -> MSFS 2020 identifier
_legacy_defaults = None  # property name -> MSFS 2020 default, only where it differs from MSFS 2024


def _legacy_definition(name):
    return LEGACY_PROPS.get(("Material", name))


def _build_tables():
    global _type_map, _legacy_defaults
    _type_map = {}
    legacy_type = _legacy_definition("msfs_material_type")
    legacy_items = [item[0] for item in legacy_type.keywords["items"]] if legacy_type else []
    rna_type = bpy.types.Material.bl_rna.properties["msfs_material_type"]
    for item in rna_type.enum_items:
        if item.value < len(legacy_items):
            _type_map[item.identifier] = legacy_items[item.value]

    _legacy_defaults = {}
    rna_props = bpy.types.Material.bl_rna.properties
    for (owner, name), definition in LEGACY_PROPS.items():
        if owner != "Material" or name not in rna_props or "default" not in definition.keywords:
            continue
        rna = rna_props[name]
        legacy_default = definition.keywords["default"]
        if rna.type == "ENUM":
            current_default = rna.default
        elif getattr(rna, "is_array", False) and rna.array_length:
            current_default = tuple(rna.default_array)
            legacy_default = tuple(legacy_default)
        else:
            current_default = rna.default
        if legacy_default != current_default:
            # A real FloatProperty reads back single precision (0.1 -> 0.10000000149...); the MSFS 2020
            # export code compares against Python literals, so keep the exact float32 value
            if rna.type == "FLOAT":
                legacy_default = (tuple(_float32(v) for v in legacy_default) if isinstance(legacy_default, tuple)
                                  else _float32(legacy_default))
            _legacy_defaults[name] = legacy_default


def legacy_material_type_name(identifier):
    """MSFS 2020 identifier for an MSFS 2024 material type identifier, None for 2024-only types."""
    if _type_map is None:
        _build_tables()
    return _type_map.get(identifier)


def legacy_material_type(material):
    """MSFS 2020 identifier of a material's type; MSFS 2024-only types export as standard."""
    if _type_map is None:
        _build_tables()
    current = material.msfs_material_type
    legacy = _type_map.get(current)
    if legacy is None:
        print(f"[MSFS2020] Material '{material.name}': type '{current}' does not exist in MSFS 2020, "
              "exported as msfs_standard")
        return "msfs_standard"
    return legacy


class LegacyMaterialView:
    __slots__ = ("_material",)

    def __init__(self, material):
        object.__setattr__(self, "_material", material)

    def __getattr__(self, name):
        material = object.__getattribute__(self, "_material")
        if name == "msfs_material_type":
            return legacy_material_type(material)
        if is_unmigrated_legacy(material):
            # Still MSFS 2020 meaning: values as the MSFS 2020 add-on read them
            if name in legacy_defaults() and not material.is_property_set(name):
                return legacy_defaults()[name]
            return getattr(material, name)
        if name == EMISSIVE_SCALE:
            return _float32(material.msfs_emissive_scale / msfs2020_emissive_reference())
        return getattr(material, name)

    def __setattr__(self, name, value):
        setattr(object.__getattribute__(self, "_material"), name, value)

    @property
    def material(self):
        return object.__getattribute__(self, "_material")


EMISSIVE_SCALE = "msfs_emissive_scale"
MIGRATED_KEY = "msfs_fss_migrated_from_msfs2020"  # custom property set by migration.py
DEFAULT_EMISSIVE_REFERENCE = 1000.0  # cd/m2 exported as 1.0 for MSFS 2020


def msfs2020_emissive_reference(scene=None) -> float:
    scene = scene or bpy.context.scene
    value = getattr(scene, "msfs_fss_msfs2020_emissive_reference", DEFAULT_EMISSIVE_REFERENCE)
    return value if value > 0.0 else DEFAULT_EMISSIVE_REFERENCE


def legacy_defaults():
    """Property name -> MSFS 2020 default, for properties whose MSFS 2024 default differs."""
    if _legacy_defaults is None:
        _build_tables()
    return _legacy_defaults


def has_msfs2020_node_tree(material) -> bool:
    """True when the material's preview node tree was built by the MSFS 2020 code (legacy assets)."""
    tree = getattr(material, "node_tree", None)
    return bool(tree and tree.nodes.get("Shader Output Material"))


EXPORT_TREE_KEY = "msfs_fss_msfs2020_export_tree"  # set on materials carrying a temporary export tree


def is_unmigrated_legacy(material) -> bool:
    """Authored with the MSFS 2020 add-on and not migrated to MSFS 2024 meaning yet."""
    return (has_msfs2020_node_tree(material) and not material.get(MIGRATED_KEY)
            and not material.get(EXPORT_TREE_KEY))


def legacy_only_definition(definition):
    """
    Definition of an MSFS 2020-only property for the unified add-on.

    Its MSFS 2020 update callback edits the MSFS 2020 preview node tree, so it only runs for materials
    that still have one; materials using the MSFS 2024 node tree have nothing to update.
    """
    update = definition.keywords.get("update")
    if update is None:
        return definition

    def update_legacy_tree(owner, context):  # Blender requires exactly (self, context)
        if not isinstance(owner, bpy.types.Material) or has_msfs2020_node_tree(owner):
            update(owner, context)

    return definition.function(**{**definition.keywords, "update": update_legacy_tree})


def reset_tables():
    """Rebuild after (re)registration of the properties."""
    global _type_map, _legacy_defaults
    _type_map = None
    _legacy_defaults = None
