import bpy

class MSFS2024BridgePreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    # MSFS2024 Preset settings
    msfs_2024_set_exporter_settings: bpy.props.BoolProperty(
        name="Set Exporter Settings",
        description=("Create 3dsMax LOD Groups, Presets and Export Settings in Blender.\n"
                    "Consider disabling this option when importing\n"
                    "multiple times into the same scene to prevent\n"
                    "duplicate export presets and settings."),
        default=True,
    )  # type: ignore


def get_addon_prefs() -> MSFS2024BridgePreferences:
    return bpy.context.preferences.addons[__package__].preferences
