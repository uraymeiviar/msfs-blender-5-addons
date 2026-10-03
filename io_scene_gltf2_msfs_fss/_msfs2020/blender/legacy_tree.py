"""
MSFS 2020 preview node trees for the duration of an MSFS 2020 glTF export.

The MSFS 2020 exporter lets Khronos gather the standard glTF material fields (base color, metallic /
roughness / occlusion, normal, emissive, alpha) from the material's node tree, and that tree is the one
the MSFS 2020 add-on builds from the MSFS properties. Materials authored in the unified add-on carry the
MSFS 2024 preview node tree instead, which Khronos reads differently (e.g. the 2024 emissive scale).

So an MSFS 2020 export temporarily gives those materials the tree the MSFS 2020 add-on would have built
from the same properties (same code, `buildTree=True` rebuilds the full tree from the properties without
changing them).

Restoring cannot rebuild the MSFS 2024 tree: the tree an artist has depends on the order properties were
edited in (an incremental update may not have wired a texture a full rebuild would), so a rebuild would
silently change it. Instead each material is copied before the swap, and afterwards every user is remapped
back to the untouched copy, which takes the original name.
"""

import bpy

from ..compat import EXPORT_TREE_KEY, LegacyMaterialView, has_msfs2020_node_tree, legacy_material_type_name
from .material.msfs_material_anisotropic import MSFS2020_Anisotropic
from .material.msfs_material_clearcoat import MSFS2020_Clearcoat
from .material.msfs_material_environment_occluder import MSFS2020_Environment_Occluder
from .material.msfs_material_fake_terrain import MSFS2020_Fake_Terrain
from .material.msfs_material_fresnel_fade import MSFS2020_Fresnel_Fade
from .material.msfs_material_geo_decal import MSFS2020_Geo_Decal
from .material.msfs_material_geo_decal_frosted import MSFS2020_Geo_Decal_Frosted
from .material.msfs_material_ghost import MSFS2020_Ghost
from .material.msfs_material_glass import MSFS2020_Glass
from .material.msfs_material_hair import MSFS2020_Hair
from .material.msfs_material_invisible import MSFS2020_Invisible
from .material.msfs_material_parallax import MSFS2020_Parallax
from .material.msfs_material_porthole import MSFS2020_Porthole
from .material.msfs_material_sss import MSFS2020_SSS
from .material.msfs_material_standard import MSFS2020_Standard
from .material.msfs_material_windshield import MSFS2020_Windshield

# Same type -> builder table as MSFS2020_Material_Property_Update.update_msfs_material_type
_BUILDERS = {
    "msfs_standard": MSFS2020_Standard,
    "msfs_geo_decal": MSFS2020_Geo_Decal,
    "msfs_geo_decal_frosted": MSFS2020_Geo_Decal_Frosted,
    "msfs_windshield": MSFS2020_Windshield,
    "msfs_porthole": MSFS2020_Porthole,
    "msfs_glass": MSFS2020_Glass,
    "msfs_clearcoat": MSFS2020_Clearcoat,
    "msfs_parallax": MSFS2020_Parallax,
    "msfs_anisotropic": MSFS2020_Anisotropic,
    "msfs_hair": MSFS2020_Hair,
    "msfs_sss": MSFS2020_SSS,
    "msfs_invisible": MSFS2020_Invisible,
    "msfs_fake_terrain": MSFS2020_Fake_Terrain,
    "msfs_fresnel_fade": MSFS2020_Fresnel_Fade,
    "msfs_environment_occluder": MSFS2020_Environment_Occluder,
    "msfs_ghost": MSFS2020_Ghost,
}

_swapped = []  # (material name, name of its untouched copy) while a temporary MSFS 2020 tree is in place
_BACKUP_SUFFIX = ".msfs_fss_2024_tree"


def build_legacy_trees():
    """Give every MSFS material with an MSFS 2024 preview tree its MSFS 2020 tree."""
    restore_trees()  # leftovers of an export that raised before post_export_hook
    for material in list(bpy.data.materials):
        if material.library or material.name.endswith(_BACKUP_SUFFIX):
            continue
        if not material.use_nodes or material.node_tree is None or has_msfs2020_node_tree(material):
            continue
        if material.msfs_material_type == "NONE":
            continue
        builder = _BUILDERS.get(legacy_material_type_name(material.msfs_material_type) or "msfs_standard")
        backup = material.copy()
        backup.name = material.name + _BACKUP_SUFFIX
        _swapped.append((material.name, backup.name))
        # MSFS 2024 meaning despite the MSFS 2020 tree; this material is replaced by the copy afterwards
        material[EXPORT_TREE_KEY] = 1
        builder(LegacyMaterialView(material), buildTree=True)


def restore_trees():
    """Put back the untouched copy of every material changed by build_legacy_trees()."""
    while _swapped:
        name, backup_name = _swapped.pop()
        material = bpy.data.materials.get(name)
        backup = bpy.data.materials.get(backup_name)
        if backup is None:
            continue
        if material is not None:
            material.user_remap(backup)  # object / mesh slots, drivers, ... now use the copy
            bpy.data.materials.remove(material)
        backup.name = name
