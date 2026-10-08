import bpy

from max_bridge_asobo import logger

from max_bridge_msfs_2024.bridge_extension.msfs_properties import *


from io_scene_gltf2_msfs_fss.io.exp import export_settings

logging = logger.getLogger()

def create_settings_preset_from_def(
    export_option_def: MSFS2024_ExportOptionsPresetDef,
) -> bpy.types.PropertyGroup:
    """
    Create a settings preset from a definition.

    Args:
        settings_preset_def: The definition of the settings preset.

    Returns:
        A new settings preset.
    """
    settings_presets = export_settings.get_scene_settings_presets(bpy.context.scene)
    settings_preset = settings_presets.add()
    if export_option_def.name == "default":
        export_option_def.name = "default_imported"
    settings_preset.name = export_option_def.name
    
    # Set Properties
    for prop in MSFS2024_ExportOptionPresetProperties:
        if prop.blender_name is NOTIMPLEMENTED:
            continue
        try:
            value = export_option_def.options_dict[prop.name]
        except KeyError:
            continue

        # TODO create enum with max/blender corresponding values
        # Special cases
        if prop == MSFS2024_ExportOptionPresetProperties.EXPORT_MATERIALS:
            if value :
                value = "EXPORT"
            else:
                value = "NONE"
        elif prop == MSFS2024_ExportOptionPresetProperties.EXPORT_HIDDEN:
            value = not value # Invert the value for hidden export
        elif prop == MSFS2024_ExportOptionPresetProperties.WRITE_TEXTURES:
            value = not value # Invert the value for texture writing
        try:
            setattr(settings_preset, prop.blender_name, value)
        except :
            print(f"Error setting property {prop.blender_name} to Value: {value}")
            logging.error(f"Error setting property {prop.blender_name} to Value: {value}")
            continue


    return settings_preset