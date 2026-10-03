"""
MSFS 2020 export target for the unified add-on.

The data model and UI are the MSFS 2024 add-on's. This module adds what exporting for MSFS 2020 needs:

- `Scene.msfs_fss_export_target`: which simulator the glTF export writes for (per scene).
- The MSFS 2020 properties the MSFS 2024 add-on does not define (legacy gizmos, object level light
  settings, wiper states, ...), from the vendored MSFS 2020 code in `_msfs2020`.
- MSFS 2020 scene export settings, collision gizmo drawing for legacy gizmo empties, and the Khronos
  exporter patches the FSS MSFS 2020 pipeline relies on.

`register_target()` / `unregister_target()` are called explicitly from the package `__init__`, after the
MSFS 2024 registration, so "already defined by MSFS 2024" is known when the 2020 properties are added.
"""

import bpy
from bpy.app.handlers import persistent

TARGET_MSFS2024 = "MSFS2024"
TARGET_MSFS2020 = "MSFS2020"

TARGET_ITEMS = (
    (TARGET_MSFS2024, "MSFS 2024", "Export glTF for Microsoft Flight Simulator 2024"),
    (TARGET_MSFS2020, "MSFS 2020", "Export glTF for Microsoft Flight Simulator 2020"),
)

_registered_props = []   # (bpy type, property name) registered from the MSFS 2020 definitions
_registered_classes = []


def get_export_target(scene) -> str:
    if not hasattr(scene, "msfs_fss_export_target"):
        return TARGET_MSFS2024
    # Scripts may export right after enabling the add-on, before the load handlers ran
    detect_export_target(scene)
    return scene.msfs_fss_export_target


def is_msfs2020_target(scene) -> bool:
    return get_export_target(scene) == TARGET_MSFS2020


# region Legacy file detection
def _stored(id_data, name):
    """
    Value stored in the file for an add-on property, without creating it.

    Reading a PointerProperty through RNA creates its (empty) storage, so `is_property_set()` cannot
    tell "saved by an add-on" from "looked at". Only values that differ from the default are stored.
    """
    getter = getattr(id_data, "bl_system_properties_get", None)  # Blender 5.0+: bpy.props storage
    group = getter() if getter else id_data
    if group is None:
        return None
    value = group.get(name)
    if hasattr(value, "keys") and not value.keys():
        return None  # created by a read, nothing saved
    return value


def _has_msfs2024_data(scene) -> bool:
    return any(_stored(scene, name) for name in (
        "msfs_multi_exporter_settings_presets", "msfs_multi_exporter_lod_groups", "msfs_multi_exporter_presets"))


def _has_msfs2020_data(scene) -> bool:
    from ._msfs2020.compat import has_msfs2020_node_tree
    if any(_stored(scene, name) is not None for name in ("msfs_exporter_settings", "msfs_multi_exporter_settings")):
        return True
    for obj in scene.objects:
        if any(_stored(obj, name) is not None for name in (
                "msfs_gizmo_type", "msfs_light_has_symmetry", "msfs_light_flash_frequency",
                "msfs_light_day_night_cycle")):
            return True
        for slot in getattr(obj, "material_slots", ()):
            # Preview node tree built by the MSFS 2020 add-on: every legacy MSFS material has one
            if slot.material and has_msfs2020_node_tree(slot.material):
                return True
    return False


_detected_scenes = set()  # Scene.session_uid already checked since the file was loaded


def detect_export_target(scene):
    """Scenes without an explicit target that only carry MSFS 2020 data are MSFS 2020 assets."""
    if scene.session_uid in _detected_scenes:
        return
    _detected_scenes.add(scene.session_uid)
    if scene.is_property_set("msfs_fss_export_target"):
        return
    if _has_msfs2020_data(scene) and not _has_msfs2024_data(scene):
        scene.msfs_fss_export_target = TARGET_MSFS2020
        print(f"[MSFS FSS] Scene '{scene.name}': MSFS 2020 data found, export target set to MSFS 2020")


@persistent
def _on_load_post(*_args):
    _detected_scenes.clear()
    for scene in bpy.data.scenes:
        detect_export_target(scene)
# endregion


def _vendored_modules():
    # Importing fills LEGACY_PROPS (see _msfs2020/legacy_props.py)
    from ._msfs2020.com import msfs_material_props  # noqa: F401
    from ._msfs2020.blender import gizmo, li_properties  # noqa: F401
    from ._msfs2020.io import msfs_khronos_patches
    from ._msfs2020 import settings
    return gizmo, msfs_khronos_patches, settings


def register_target():
    gizmo, khronos_patches, settings = _vendored_modules()
    from ._msfs2020.legacy_props import LEGACY_PROPS
    from ._msfs2020 import compat

    bpy.types.Scene.msfs_fss_export_target = bpy.props.EnumProperty(
        name="Export Target",
        description="Simulator the glTF export is written for",
        items=TARGET_ITEMS,
        default=TARGET_MSFS2024,
    )

    for cls in settings.CLASSES + (gizmo.MSFS2020CollisionGizmo, gizmo.MSFS2020CollisionGizmoGroup):
        bpy.utils.register_class(cls)
        _registered_classes.append(cls)
    for scene_prop, cls in (("msfs_exporter_settings", settings.MSFS2020_ExporterProperties),
                            ("msfs_importer_properties", settings.MSFS2020_ImporterProperties)):
        setattr(bpy.types.Scene, scene_prop, bpy.props.PointerProperty(type=cls))
        _registered_props.append((bpy.types.Scene, scene_prop))

    # MSFS 2020 properties that MSFS 2024 does not define
    for (owner_name, prop_name), definition in LEGACY_PROPS.items():
        owner = getattr(bpy.types, owner_name)
        if prop_name in owner.bl_rna.properties:
            continue
        setattr(owner, prop_name, compat.legacy_only_definition(definition))
        _registered_props.append((owner, prop_name))

    compat.reset_tables()
    khronos_patches.register()
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)


def unregister_target():
    _gizmo, khronos_patches, _settings = _vendored_modules()
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    khronos_patches.unregister()
    while _registered_props:
        owner, prop_name = _registered_props.pop()
        try:
            delattr(owner, prop_name)
        except AttributeError:
            pass
    while _registered_classes:
        bpy.utils.unregister_class(_registered_classes.pop())
    try:
        del bpy.types.Scene.msfs_fss_export_target
    except AttributeError:
        pass
