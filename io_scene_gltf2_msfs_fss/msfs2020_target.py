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


EXPORT_ONLY_ITEMS = (
    ("ALL", "All Targets", "Exported for every simulator"),
    (TARGET_MSFS2024, "MSFS 2024 Only", "Only exported for Microsoft Flight Simulator 2024"),
    (TARGET_MSFS2020, "MSFS 2020 Only", "Only exported for Microsoft Flight Simulator 2020"),
)


def keep_for_export(obj, target: str) -> bool:
    """
    Whether an object belongs in a glTF export for `target`.

    One file can carry both representations of the same thing (e.g. legacy gizmo empties for MSFS 2020
    and geometry nodes gizmos for MSFS 2024, see "Prepare for MSFS 2024"): each export skips the other's.
    """
    only = getattr(obj, "msfs_fss_export_only", "ALL")
    if only != "ALL" and only != target:
        return False
    if target == TARGET_MSFS2020:
        from .blender import msfs_gizmo
        if msfs_gizmo.is_valid_gizmo_obj(obj):
            return False
    elif obj.type == "EMPTY" and getattr(obj, "msfs_gizmo_type", "NONE") != "NONE":
        return False  # MSFS 2020 collision gizmo empty
    return True


def filter_export_tree(vtree, target: str):
    """Khronos gather_tree_filter_tag_hook: untag nodes that do not belong in this target's export."""
    for vnode in vtree.nodes.values():
        obj = vnode.blender_object
        if obj is None or vnode.blender_bone is not None or vnode.keep_tag is not True:
            continue
        if not keep_for_export(obj, target):
            vnode.keep_tag = False


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


def _has_msfs2020_data(scene) -> bool:
    from ._msfs2020.compat import MIGRATED_KEY, has_msfs2020_node_tree
    if any(_stored(scene, name) is not None for name in ("msfs_exporter_settings", "msfs_multi_exporter_settings")):
        return True
    for obj in scene.objects:
        if any(_stored(obj, name) is not None for name in (
                "msfs_gizmo_type", "msfs_light_has_symmetry", "msfs_light_flash_frequency",
                "msfs_light_day_night_cycle")):
            return True
        for slot in getattr(obj, "material_slots", ()):
            # Preview node tree built by the MSFS 2020 add-on (every legacy MSFS material has one until it
            # is migrated, see migration.py)
            if slot.material and (has_msfs2020_node_tree(slot.material) or slot.material.get(MIGRATED_KEY)):
                return True
    return False


_detected_scenes = set()  # Scene.session_uid already checked since the file was loaded


def detect_export_target(scene):
    """
    Scenes without an explicit target that carry MSFS 2020 data are MSFS 2020 assets.

    MSFS 2024 data is not a counter-indication: the MSFS 2024 code creates its export presets and LOD groups
    in every file it opens, and a file that was meant for MSFS 2024 has its target set explicitly.
    """
    if scene.session_uid in _detected_scenes:
        return
    _detected_scenes.add(scene.session_uid)
    if scene.is_property_set("msfs_fss_export_target"):
        return
    if _has_msfs2020_data(scene):
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
    bpy.types.Scene.msfs_fss_msfs2020_emissive_reference = bpy.props.FloatProperty(
        name="MSFS 2020 Emissive Reference",
        description=("Emission brightness (cd/m²) exported as emissive strength 1.0 for MSFS 2020. "
                     "Materials store MSFS 2024 brightness; MSFS 2020 exports divide by this value, and MSFS 2020 "
                     "materials are migrated with it on first use"),
        default=compat.DEFAULT_EMISSIVE_REFERENCE,
        min=0.001,
        soft_max=20000.0,
    )
    _registered_props.append((bpy.types.Scene, "msfs_fss_msfs2020_emissive_reference"))
    bpy.types.Object.msfs_fss_export_only = bpy.props.EnumProperty(
        name="Export For",
        description="Simulators this object is exported for",
        items=EXPORT_ONLY_ITEMS,
        default="ALL",
    )
    _registered_props.append((bpy.types.Object, "msfs_fss_export_only"))

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
    _register_gltf_export_ui()


def _draw_gltf_export(context, layout):
    """Export target in the File > Export > glTF 2.0 dialog."""
    from .ui.target_panels import draw_export_target
    header, body = layout.panel("MSFS_FSS_PT_gltf_export_target", default_closed=False)
    header.label(text="Microsoft Flight Simulator (FSS)")
    if body:
        body.use_property_split = True
        draw_export_target(body, context.scene)


def _register_gltf_export_ui():
    if bpy.app.version >= (4, 2, 0):
        from io_scene_gltf2 import exporter_extension_layout_draw
        exporter_extension_layout_draw["Microsoft Flight Simulator (FSS)"] = _draw_gltf_export


def _unregister_gltf_export_ui():
    if bpy.app.version >= (4, 2, 0):
        from io_scene_gltf2 import exporter_extension_layout_draw
        exporter_extension_layout_draw.pop("Microsoft Flight Simulator (FSS)", None)


def unregister_target():
    _gizmo, khronos_patches, _settings = _vendored_modules()
    _unregister_gltf_export_ui()
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
