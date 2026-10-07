"""
Unified add-on UI: export target and the MSFS 2020-only settings.

The MSFS 2024 panels edit the shared data. These panels add the per-scene export target and, while a scene
targets MSFS 2020, the settings only the MSFS 2020 exporter uses (legacy collision gizmos, object level light
settings, MSFS 2020-only material values).
"""

import bpy

from .. import msfs2020_target


def _is_msfs2020(context) -> bool:
    return msfs2020_target.is_msfs2020_target(context.scene)


def draw_export_target(layout, scene):
    layout.prop(scene, "msfs_fss_export_target")
    if msfs2020_target.is_msfs2020_target(scene):
        settings = scene.msfs_exporter_settings
        layout.prop(settings, "enable_msfs_extension")
        layout.prop(settings, "use_unique_id")
        if scene.is_property_set("msfs_fss_msfs2020_emissive_reference"):
            layout.prop(scene, "msfs_fss_msfs2020_emissive_reference", text="Emissive 1.0 (cd/m²)")
        else:
            from .._msfs2020.compat import msfs2020_emissive_reference
            layout.label(text=f"Emissive 1.0: {msfs2020_emissive_reference(scene):g} cd/m² (add-on preference)")


class MSFS_FSS_PT_export_target(bpy.types.Panel):
    bl_label = "Export Target"
    bl_idname = "VIEW3D_PT_msfs_fss_export_target"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Microsoft Flight Simulator 2024 Tools"
    bl_order = -10  # above the multi-exporter

    register_order = -2

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        draw_export_target(layout, context.scene)
        if _is_msfs2020(context):
            col = layout.column()
            col.label(text="MSFS 2020 is exported with File > Export > glTF 2.0", icon="INFO")
            col.label(text="(the multi-exporter writes MSFS 2024 glTF)")
        if bpy.ops.msfs_fss.prepare_msfs2024.poll():
            layout.operator("msfs_fss.prepare_msfs2024", icon="EXPORT")
        from ..legacy_normals import candidates, misordered_auto_smooth
        off, misordered = len(candidates()), len(misordered_auto_smooth())
        if off or misordered:
            box = layout.box()
            if off:
                box.label(text=f"{off} mesh(es) from Blender 4.0 or older had Auto Smooth off", icon="ERROR")
            if misordered:
                box.label(text=f"{misordered} object(s): Auto Smooth modifier after Weighted Normal", icon="ERROR")
            box.label(text="and may shade differently than in Blender 3.6")
            box.operator("msfs_fss.restore_legacy_normals", icon="NORMALS_FACE")


class MSFS_FSS_PT_object_msfs2020(bpy.types.Panel):
    bl_label = "MSFS 2020 Object Parameters"
    bl_idname = "OBJECT_PT_msfs_fss_msfs2020"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type in {"EMPTY", "LIGHT"} and _is_msfs2020(context)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        obj = context.object
        if obj.type == "EMPTY":
            layout.prop(obj, "msfs_gizmo_type", text="Collision Gizmo")
            if obj.msfs_gizmo_type != "NONE":
                layout.prop(obj, "msfs_collision_is_road_collider")
        else:
            for name in ("msfs_light_has_symmetry", "msfs_light_flash_frequency", "msfs_light_flash_duration",
                         "msfs_light_flash_phase", "msfs_light_rotation_speed", "msfs_light_day_night_cycle"):
                layout.prop(obj, name)


# MSFS 2020-only material properties, grouped by the MSFS 2020 material types that use them
_MATERIAL_GROUPS = (
    ("Detail UV Offset", None, ("msfs_detail_uv_offset_u", "msfs_detail_uv_offset_v")),
    ("Windshield", {"msfs_windshield"},
     ("msfs_rain_drop_scale", "msfs_wiper_1_state", "msfs_wiper_2_state", "msfs_wiper_3_state", "msfs_wiper_4_state")),
    ("Glass", {"msfs_glass"}, ("msfs_glass_deformation_factor", "msfs_glass_reflection_mask_factor")),
    ("Parallax", {"msfs_parallax"}, ("msfs_parallax_scale", "msfs_parallax_room_number_xy")),
    ("Clearcoat", {"msfs_clearcoat"}, ("msfs_dirt_texture",)),
    ("Anisotropic / Hair", {"msfs_anisotropic", "msfs_hair"}, ("msfs_extra_slot1_texture",)),
    ("Rendering", None, ("msfs_responsive_aa",)),
)


class MSFS_FSS_PT_material_msfs2020(bpy.types.Panel):
    bl_label = "MSFS 2020 Material Parameters"
    bl_idname = "MATERIAL_PT_msfs_fss_msfs2020"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "material"

    @classmethod
    def poll(cls, context):
        mat = context.material
        return mat is not None and getattr(mat, "msfs_material_type", "NONE") != "NONE" and _is_msfs2020(context)

    def draw(self, context):
        from .._msfs2020.compat import legacy_material_type_name
        layout = self.layout
        layout.use_property_split = True
        mat = context.material
        legacy_type = legacy_material_type_name(mat.msfs_material_type)
        if legacy_type is None:
            layout.label(text="This material type does not exist in MSFS 2020: exported as standard", icon="ERROR")
            legacy_type = "msfs_standard"
        for title, types, names in _MATERIAL_GROUPS:
            if types is not None and legacy_type not in types:
                continue
            box = layout.box()
            box.label(text=title)
            for name in names:
                if hasattr(mat, name):
                    box.prop(mat, name)
