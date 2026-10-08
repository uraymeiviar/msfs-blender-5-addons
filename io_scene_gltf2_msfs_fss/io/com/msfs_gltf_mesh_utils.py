from __future__ import annotations
from typing import TYPE_CHECKING
import bpy
import re 

from io_scene_gltf2_msfs_fss.blender.utils import msfs_mesh_utils
if TYPE_CHECKING:
    from io_scene_gltf2.io.com import gltf2_io


def clean_color_attributes(gltf2_mesh: gltf2_io.Mesh, blender_mesh:bpy.types.Mesh):
    """Remove color attributes not used by the engine.

    MSFS 2024 only uses COLOR_0. Remove COLOR_0 if it is uniformly white.
    """
    active_color_attribute = msfs_mesh_utils.get_active_render_color_attribute(blender_mesh)
    if not active_color_attribute:
        return
    keep_color = not msfs_mesh_utils.is_color_attribute_uniform_white(active_color_attribute)

    pattern = r"COLOR_(\d+)$"
    for primitive in gltf2_mesh.primitives:
        for primitive in gltf2_mesh.primitives:
            for attribute_name in list(primitive.attributes.keys()):
                match = re.match(pattern, attribute_name)
                # delete all color attrib except active one
                if match and (not keep_color or int(match.group(1)) != 0):
                    primitive.attributes.pop(attribute_name)

def clean_texcoord_attributes(gltf2_mesh: gltf2_io.Mesh, blender_mesh:bpy.types.Mesh):
    """Remove UV sets not used by the engine.

    MSFS 2024 shaders only use the first two UV sets.
    """
    pattern = r"^TEXCOORD_(\d+)$"

    for primitive in gltf2_mesh.primitives:
        for attribute_name in list(primitive.attributes.keys()):
            match = re.match(pattern, attribute_name)
            if match and int(match.group(1)) > 1:
                primitive.attributes.pop(attribute_name)
