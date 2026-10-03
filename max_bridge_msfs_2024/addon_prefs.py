import bpy

import max_bridge_msfs_2024.exporters as exporters #do not import using from in order to prevent circular import


class BridgePreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    PRESETS_ENUM=exporters.get_presets_for_enum_prop()

    bridge_preset : bpy.props.EnumProperty(
            name="Bridge Preset",
            description="Affects how assets are exported",
            items=PRESETS_ENUM,
            default=PRESETS_ENUM[1][0]
        ) # type: ignore
    
    reuse_existing_collections: bpy.props.BoolProperty(
        name="Reuse Existing Collections",
        description=("Reuse existing collections with the same names when\n" 
                     "recreating 3ds Max layers in Blender.\n"
                    "Consider enabling this option when importing\n"
                    "multiple times into the same scene to prevent\n"
                    "duplicated collections."),
        default=False,
    )  # type: ignore

    # MSFS2024 Preset settings
    msfs_2024_set_exporter_settings: bpy.props.BoolProperty(
        name="Set Exporter Settings",
        description=("Create 3dsMax LOD Groups, Presets and Export Settings in Blender.\n"
                    "Consider disabling this option when importing\n"
                    "multiple times into the same scene to prevent\n"
                    "duplicate export presets and settings."),
        default=True,
    )  # type: ignore

    


def get_addon_prefs() -> BridgePreferences:
    return bpy.context.preferences.addons[__package__].preferences
