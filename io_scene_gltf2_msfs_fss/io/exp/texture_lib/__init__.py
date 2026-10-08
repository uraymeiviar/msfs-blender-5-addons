import datetime

from pathlib import Path
import time
import os
import bpy

from urllib.parse import unquote
from os.path import normpath

from json import load
from _addons_common import p4, file_info

from io_scene_gltf2_msfs_fss.blender.utils.msfs_material_utils import MSFS2024_MaterialProperties

from io_scene_gltf2_msfs_fss.io.com import msfs_logs


from .bitmap_config import BitmapConfig
from .texture_xml import XmlSerializer
from .gltf_material import GltfMaterial
from .texture_config import TextureConfig

MSFS2024_LOGGER : msfs_logs.Logger

def _get_texture_flags(texture_name: str) -> str:

    flags = ""
    for image in bpy.data.images:
        image_name = image.name
        if not image_name:
            continue
        # Remove image extension and .001 suffix
        image_name = image_name.split(".", 1)[0]
        if image_name == texture_name:
           flags =  image.msfs_flags.to_string()
           break
    return flags

# region Texture LIB From GLTF
def _get_gltf_material_config(material: dict) -> list[TextureConfig]:
    """
    Convert the material definition in a gltf to texture index and flags
    """
    gltf_material = GltfMaterial(material)
    result: list = []

    # region Material Textures
    # MTL_BITMAP_DECAL0
    texture_config = gltf_material.get_base_color_tex_config()
    if texture_config is not None:
        result.append(texture_config)

    # MTL_BITMAP_METAL_ROUGH_AO
    metal_rough_texture_index = -1
    metal_rough_texture_config = gltf_material.get_metal_rough_ao_tex_config()
    if metal_rough_texture_config is not None:
        metal_rough_texture_index = metal_rough_texture_config.gltf_texture_id
        result.append(metal_rough_texture_config)

    # MTL_BITMAP_OCCLUSION
    texture_config = gltf_material.get_occlusion_tex_config(metal_rough_texture_index)
    if texture_config is not None:
        result.append(texture_config)

    # MTL_BITMAP_NORMAL
    texture_config = gltf_material.get_normal_tex_config()
    if texture_config is not None:
        result.append(texture_config)

    # MTL_BITMAP_EMISSIVE
    texture_config = gltf_material.get_emissive_tex_config()
    if texture_config is not None:
        result.append(texture_config)
    # endregion

    if gltf_material.extensions is None:
        return result

    # region Extensions Texture

    # region Distance Field Layer
    texture_config = gltf_material.get_distance_field_layer_mask_tex_config()
    if texture_config is not None:
        result.append(texture_config)

    texture_config = gltf_material.get_distance_field_color_tex_config()
    if texture_config is not None:
        result.append(texture_config)
    # endregion

    # region Detail Map
    blend_mask_texture_index = -1
    blend_mask_texture_config = gltf_material.get_blend_mask_tex_config()
    if blend_mask_texture_config is not None:
        blend_mask_texture_index = blend_mask_texture_config.gltf_texture_id
        result.append(blend_mask_texture_config)

    texture_config = gltf_material.get_detail_color_tex_config(blend_mask_texture_index)
    if texture_config is not None:
        result.append(texture_config)

    texture_config = gltf_material.get_detail_normal_tex_config(blend_mask_texture_index)
    if texture_config is not None:
        result.append(texture_config)

    texture_config = gltf_material.get_detail_metal_rough_ao_tex_config(blend_mask_texture_index)
    if texture_config is not None:
        result.append(texture_config)
    # endregion

    # region Anisotropic
    texture_config = gltf_material.get_aniso_direction_roughness_tex_config()
    if texture_config is not None:
        result.append(texture_config)
    # endregion

    # region Parallax Window
    texture_config = gltf_material.get_behind_window_text_config()
    if texture_config is not None:
        result.append(texture_config)
    # endregion

    # region Windshield
    texture_config = gltf_material.get_wiper_mask_tex_config()
    if texture_config is not None:
        result.append(texture_config)

    texture_config = gltf_material.get_windshield_detail_normal_tex_config()
    if texture_config is not None:
        result.append(texture_config)

    texture_config = gltf_material.get_scratches_normal_tex_config()
    if texture_config is not None:
        result.append(texture_config)

    texture_config = gltf_material.get_windshield_insects_tex_config()
    if texture_config is not None:
        result.append(texture_config)

    texture_config = gltf_material.get_windshield_insects_mask_tex_config()
    if texture_config is not None:
        result.append(texture_config)
    # endregion

    # region Foliage
    texture_config = gltf_material.get_foliage_mask_tex_config()
    if texture_config is not None:
        result.append(texture_config)
    # endregion

    # region Extra Occlusion
    texture_config = gltf_material.get_extra_occlusion_tex_config()
    if texture_config is not None:
        result.append(texture_config)
    # endregion

    # region Clearcoat
    texture_config = gltf_material.get_clearcoat_color_rough_tex_config()
    if texture_config is not None:
        result.append(texture_config)

    texture_config = gltf_material.get_clearcoat_normal_tex_config()
    if texture_config is not None:
        result.append(texture_config)
    # endregion

    # region Geometry Decal
    texture_config = gltf_material.get_dirt_mask_tex_config()
    if texture_config is not None:
        result.append(texture_config)
    # endregion

    # region Iridescent
    texture_config = gltf_material.get_iridescent_tex_config()
    if texture_config is not None:
        result.append(texture_config)
    # endregion

    # region Dirt
    texture_config = gltf_material.get_dirt_tex_config()
    if texture_config is not None:
        result.append(texture_config)

    texture_config = gltf_material.get_dirt_occ_rough_metal_tex_config()
    if texture_config is not None:
        result.append(texture_config)
    # endregion

    # region Tire
    texture_config = gltf_material.get_tire_details_tex_config()
    if texture_config is not None:
        result.append(texture_config)

    texture_config = gltf_material.get_tire_mud_normal_tex_config()
    if texture_config is not None:
        result.append(texture_config)
    # endregion

    # endregion
    return result


def _get_gltf_texture_configs(gltf_path: str, tex_to_process: set[str] | None = None) -> tuple[dict[str, tuple[BitmapConfig, str]], set[str] | None]:
    """
    Return a dict of the texture with bitmap config associated from a gltf

    Returns:
        Tuple containing gltf texture configs dict and set of remaining textures to find.
    """
    texture_configs_result = {}

    if not os.path.exists(gltf_path):
        return texture_configs_result, tex_to_process

    json_file = None
    with open(gltf_path, 'r', encoding="utf-8") as file:
        json_file = load(file)

    if json_file is None:
        return texture_configs_result, tex_to_process

    gltf_materials = json_file.get("materials")
    gltf_textures = json_file.get("textures")
    gltf_images = json_file.get("images")

    if (gltf_materials is None) or (gltf_textures is None) or (gltf_images is None):
        return texture_configs_result, tex_to_process
    
    filter_texture = isinstance(tex_to_process, set)
    if filter_texture:
        tex_to_process = tex_to_process.copy()
    for gltf_material in gltf_materials:
        texture_configs = _get_gltf_material_config(gltf_material)

        for texture_config in texture_configs:
            gltf_texture_id = gltf_textures[texture_config.gltf_texture_id].get("source")

            uri = gltf_images[gltf_texture_id].get("uri")
            uri = str.replace(uri, '\\', '/')
            uri = unquote(uri)

            image_path = normpath(uri)
            image_path = Path(gltf_path).parent / image_path
            image_path = image_path.resolve()
            image_name = image_path.stem

            texture_config.bitmap_config.user_flags += _get_texture_flags(image_name)

            if filter_texture:
                
                if image_name in tex_to_process:
                    tex_to_process.remove(image_name)
                else: 
                    continue
                    
            if image_name not in texture_configs_result:
                texture_configs_result[image_name] = (texture_config.bitmap_config, image_path.as_posix(), texture_config.material_name)

            else:
                saved_bmp_texture_config = texture_configs_result[image_name][0] # BitmapConfig
                has_same_configs = texture_config.bitmap_config.compare(saved_bmp_texture_config)
                has_compatible_configs = texture_config.bitmap_config.is_compatible_id(saved_bmp_texture_config)

                if not has_same_configs and not has_compatible_configs:
                    MSFS2024_LOGGER.error(
                        message=f"'{image_name}' : Assigned to multiple material slot types.",
                        details= (f"Found in material '{texture_config.material_name}':\n"
                                f"- {texture_config.bitmap_config.to_string()}\n" 
                                f"- {saved_bmp_texture_config.to_string()}")
                    )


    return texture_configs_result, tex_to_process


def get_gltfs_texture_configs(
    gltf_paths: list[str],
    tex_to_process: set[str] | None = None
)->dict[str, tuple[BitmapConfig, str]]:
    """
    Get gltfs texture configs and 
    """
    result = dict()

    filter_texture = isinstance(tex_to_process, set)
    if filter_texture:
        tex_to_process = tex_to_process.copy()
    
    for gltf_path in gltf_paths:
        gltf_path = os.path.abspath(gltf_path)
        texture_configs, tex_to_process = _get_gltf_texture_configs(gltf_path, tex_to_process)
        
        result.update(texture_configs)
        if filter_texture and not tex_to_process:
            # all textures were found
            break
    return result


def create_xml(texture_config: tuple[BitmapConfig, str]):
    """
        Write a new xml with the textureConfig at the xmlPath location
        Return True when succesfully created
        In:
            texture_config : Tuple(BitmapConfig, path: str)
    """
    texture_path = texture_config[1]
    texture_base_name = os.path.basename(texture_path)
    if not os.path.exists(texture_path):
        MSFS2024_LOGGER.error(
            message=f"'{texture_base_name}' : Does not exist.",
            details=f"Texture path does not exist:\n{texture_path}."
        )
        return

    xml_path = texture_path + ".xml"
    xml_base_name = os.path.basename(xml_path)
    serializer = XmlSerializer(xml_path)

    texture_bmp_config = texture_config[0]
    already_set = False
    if os.path.exists(xml_path):
        if serializer.open():
            already_set = serializer.bmp_config.compare(texture_bmp_config)    
        else:
            os.remove(xml_path)

    if already_set:
        MSFS2024_LOGGER.info(
                    message=f"'{xml_base_name}' : Has been generated.",
                    details=("Xml generation skipped since it already exists:\n"
                                f"{texture_path}")
                )

        return

    if p4.USE_P4:
        if not p4.p4_session_edit(xml_path):
            MSFS2024_LOGGER.error(
                message=f"'{xml_base_name}' : Could not be opened for edit.",
            )
    

    if file_info.is_read_only(xml_path):
        MSFS2024_LOGGER.error(
            message=f"'{xml_base_name}' : File is read-only.",
            details=(
                "Xml generation skipped since file is read-only.\n"
                "Disable the read-only attribute to make the file writable:\n"
                f"{texture_path}"
            ),
        )
        return
    
    log_details="Xml was created:\n"
    if not already_set:
        log_details="Xml was overwritten with a new config:\n"

    serializer.bmp_config.copy(texture_bmp_config)

    if serializer.save():    
        MSFS2024_LOGGER.info(
            message=f"'{xml_base_name}' : Has been generated.",
            details=log_details+f"{texture_path}"  
        )
    else:   
        MSFS2024_LOGGER.error(
            message=f"'{xml_base_name}' : Could not be Saved!",
            details=f"Writing of xml failed:\n{xml_path}",
        )


def export_gltfs_texture_lib(
    gltf_paths: list[str],
    tex_to_process: set[str] | None = None
)->set[str]:
    """
    Parse provided gltf and create the texture xmls.

    Returns:
        Texture name found in gltfs.
    """
    found_tex = set()
    if len(gltf_paths) < 1:
        return found_tex
    global MSFS2024_LOGGER
    MSFS2024_LOGGER = msfs_logs.get_logger()
    print(f"[TextureLib] New TextureLib generation started at {str(datetime.datetime.now())}")
    time_start = time.time()

    texture_configs = get_gltfs_texture_configs(gltf_paths, tex_to_process)
    
    for texture_name, texture_config in texture_configs.items():
        if " " in texture_name:
            MSFS2024_LOGGER.error(
                message=f"'{texture_name}' : Contains whitespaces.",
                details=(f"Texture name '{texture_name}' contains whitespaces,\n"
                    "XML will not be generated. Please remove the whitespace before regenerating."
                )
            )
            continue

        print(f"[TextureLib] Generating XML for texture '{texture_name}'.")
        create_xml(texture_config)
        found_tex.add(texture_name)

    delta = round(time.time() - time_start, 3)
    print(f"[TextureLib] Operation completed in {delta}")

    return found_tex
# endregion
