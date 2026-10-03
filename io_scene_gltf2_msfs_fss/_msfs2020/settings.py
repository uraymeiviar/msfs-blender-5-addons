"""
MSFS 2020 scene export settings (Scene.msfs_exporter_settings / Scene.msfs_importer_properties).

Same property names and defaults as the MSFS 2020 add-on, so values saved in existing .blend files are
read unchanged. The MSFS 2020 multi-exporter is not part of the unified add-on, so the enable flag no
longer syncs to Scene.msfs_multi_exporter_settings.
"""

import bpy


class MSFS2020_ImporterProperties(bpy.types.PropertyGroup):
    enable_msfs_extension: bpy.props.BoolProperty(
        name="Microsoft Flight Simulator 2020 Extensions",
        description="Enable MSFS2020 glTF import extensions",
        default=True,
    )  # type: ignore


class MSFS2020_ExporterProperties(bpy.types.PropertyGroup):
    enable_msfs_extension: bpy.props.BoolProperty(
        name="Microsoft Flight Simulator 2020 Extensions",
        description="Enable MSFS2020 glTF export extensions",
        default=True,
    )  # type: ignore

    use_unique_id: bpy.props.BoolProperty(
        name="Use ASOBO Unique ID",
        description="use ASOBO Unique ID extension",
        default=True,
    )  # type: ignore


CLASSES = (MSFS2020_ImporterProperties, MSFS2020_ExporterProperties)
