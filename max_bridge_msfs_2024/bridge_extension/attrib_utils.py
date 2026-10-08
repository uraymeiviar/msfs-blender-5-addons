import bpy


def rename_uv_maps(obj:bpy.types.Object):
    """
    Rename UV maps of the specified object or the active object in Blender.

    Args:
        obj : The object whose UV maps will be renamed.
    """

    if not obj.data or not hasattr(obj.data, 'uv_layers'):
        return

    uv_layers = obj.data.uv_layers
    for index, uv_map in enumerate(uv_layers):
        # Construct the new name
        uv_map.name = f"UV{index+1}"