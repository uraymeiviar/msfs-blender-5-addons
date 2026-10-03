"""
MSFS 2020 property definitions, collected instead of registered.

The vendored MSFS 2020 exporter code (this `_msfs2020` folder) defined its Blender properties as a side
effect of importing its modules (`bpy.types.Material.msfs_x = bpy.props...` in class bodies). Those lines
were rewritten to fill this table, so importing the 2020 code never overrides the MSFS 2024 definitions.

`io_scene_gltf2_msfs_fss.msfs2020_target` registers the entries the MSFS 2024 code does not define, and
uses the rest to recover MSFS 2020 defaults (see `_msfs2020.compat`).

Key: (bpy.types class name, property name). Value: the deferred bpy.props definition.
"""

LEGACY_PROPS = {}
