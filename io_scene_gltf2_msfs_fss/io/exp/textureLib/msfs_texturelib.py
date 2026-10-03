# Copyright 2023-2024 The glTF-Blender-IO-MSFS2024 authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import time
import os
import bpy

from urllib.parse import unquote
from os.path import normpath

from json import load
from _addons_common import p4

from ....blender.utils.msfs_material_utils import MSFS2024_MaterialProperties

from .msfs_bitmap_config import BitmapConfig
from .msfs_texture_xml import XmlSerializer
from .msfs_gltf_material import GltfMaterial
from .msfs_texture_config import TextureConfig
from ...com import msfs_logs

MSFS2024_LOGGER : msfs_logs.Logger

def get_texture_config_from_bl_material(texture_name, materials):
    texture_configs: dict = {}
    for material in materials:
        texture_configs[material] = None

        if hasattr(material, MSFS2024_MaterialProperties.BASECOLORTEXTURE.attribute_name()):
            texture = getattr(material, MSFS2024_MaterialProperties.BASECOLORTEXTURE.attribute_name())

            if texture.name == texture_name:
                texture_configs[material] = TextureConfig(
                    bitmap_config=BitmapConfig(
                        material_bitmap=1, 
                        user_flags="", 
                        force_no_alpha=False
                    )
                )

        print(material)


def get_gltf_material_config(material):
    """
        Convert the material definition in a gltf to texture index and flags
    """
    gltf_material = GltfMaterial(material)
    result: list = []

    #region Material Textures
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
    #endregion

    if gltf_material.extensions is None:
        return result

    #region Extensions Texture

    #region Distance Field Layer
    texture_config = gltf_material.get_distance_field_layer_mask_tex_config()
    if texture_config is not None:
        result.append(texture_config)

    texture_config = gltf_material.get_distance_field_color_tex_config()
    if texture_config is not None:
        result.append(texture_config)
    #endregion

    #region Detail Map
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
    #endregion

    #region Anisotropic
    texture_config = gltf_material.get_aniso_direction_roughness_tex_config()
    if texture_config is not None:
        result.append(texture_config)
    #endregion

    #region Parallax Window
    texture_config = gltf_material.get_behind_window_text_config()
    if texture_config is not None:
        result.append(texture_config)
    #endregion

    #region Windshield
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
    #endregion

    #region Foliage
    texture_config = gltf_material.get_foliage_mask_tex_config()
    if texture_config is not None:
        result.append(texture_config)
    #endregion

    #region Extra Occlusion
    texture_config = gltf_material.get_extra_occlusion_tex_config()
    if texture_config is not None:
        result.append(texture_config)
    #endregion

    #region Clearcoat
    texture_config = gltf_material.get_clearcoat_color_rough_tex_config()
    if texture_config is not None:
        result.append(texture_config)

    texture_config = gltf_material.get_clearcoat_normal_tex_config()
    if texture_config is not None:
        result.append(texture_config)
    #endregion

    #region Geometry Decal
    texture_config = gltf_material.get_dirt_mask_tex_config()
    if texture_config is not None:
        result.append(texture_config)
    #endregion

    #region Iridescent
    texture_config = gltf_material.get_iridescent_tex_config()
    if texture_config is not None:
        result.append(texture_config)
    #endregion

    #region Dirt
    texture_config = gltf_material.get_dirt_tex_config()
    if texture_config is not None:
        result.append(texture_config)

    texture_config = gltf_material.get_dirt_occ_rough_metal_tex_config()
    if texture_config is not None:
        result.append(texture_config)
    #endregion

    #region Tire
    texture_config = gltf_material.get_tire_details_tex_config()
    if texture_config is not None:
        result.append(texture_config)

    texture_config = gltf_material.get_tire_mud_normal_tex_config()
    if texture_config is not None:
        result.append(texture_config)
    #endregion

    #endregion
    return result

def get_texture_flags(texture_name):
    flags = ""
    if texture_name in bpy.data.images:
        blender_image = bpy.data.images[texture_name]
        flags = blender_image.msfs_flags.to_string()
    return flags

def get_gltf_texture_configs(gltf_path):
    """
        Return a dict of the texture with bitmap config associated from a gltf
        In : gltf_path -> str
        Out: dict[str, Tuple(BitmapConfig, image_path)]
    """
    texture_configs_result = {}

    if not os.path.exists(gltf_path):
        return texture_configs_result

    json_file = None
    with open(gltf_path, 'r', encoding="utf-8") as file:
        json_file = load(file)

    if json_file is None:
        return texture_configs_result
    
    gltf_materials = json_file.get("materials")
    gltf_textures = json_file.get("textures")
    gltf_images = json_file.get("images")

    if (gltf_materials is None) or (gltf_textures is None) or (gltf_images is None):
        print(f"[TextureLib][GLTF][WARNING] No textures found in {gltf_path}.")
        return texture_configs_result

    for gltf_material in gltf_materials:
        texture_configs = get_gltf_material_config(gltf_material)

        for texture_config in texture_configs:
            gltf_texture_id = gltf_textures[texture_config.gltf_texture_id].get("source")

            uri = gltf_images[gltf_texture_id].get("uri")
            uri = str.replace(uri, '\\', '/')
            uri = unquote(uri)

            image_path = normpath(uri)
            image_path = os.path.join(os.path.dirname(gltf_path), image_path)
            image_path = os.path.abspath(image_path)
            image_name = os.path.basename(image_path)

            texture_config.bitmap_config.user_flags += get_texture_flags(image_name)

            if image_name not in texture_configs_result:
                texture_configs_result[image_name] = (texture_config.bitmap_config, image_path, texture_config.material_name)
            
            else:
                saved_bmp_texture_config = texture_configs_result[image_name][0] # BitmapConfig
                saved_texture_config_material_name = texture_configs_result[image_name][2] # BitmapConfig
                has_same_configs = texture_config.bitmap_config.compare(saved_bmp_texture_config)
                has_compatible_configs = texture_config.bitmap_config.is_compatible_id(saved_bmp_texture_config)

                if not has_same_configs and not has_compatible_configs:
                    MSFS2024_LOGGER.error(
                        message=f"'{image_name}' : Assigned to multiple material slot types.",
                        details= (f"Found in material '{texture_config.material_name}':\n"
                                f"- {texture_config.bitmap_config.to_string()}\n" 
                                f"- {saved_bmp_texture_config.to_string()}")
                    )
                
    if len(gltf_images) > len(texture_configs_result):
        print(f"[GLTF][WARNING] Some images used in the gltf {gltf_path} aren't referenced by any material")
        
    return texture_configs_result

def get_gltfs_texture_configs(gltf_paths, keep_originals=True, texture_dst_dir=''):
    """
        Out: dict[name of texture: str, tuple(BitmapConfig, texture_folder_path)]
    """
    result = dict()
    for gltf_path in gltf_paths:
        gltf_path = os.path.abspath(gltf_path)
        texture_configs = get_gltf_texture_configs(gltf_path)

        gltf_dir_path = os.path.dirname(gltf_path)
        if not os.path.isabs(texture_dst_dir):
            texture_dst_dir = os.path.join(gltf_dir_path, texture_dst_dir)

        if not keep_originals and texture_dst_dir != '':
            for texture_name, texture_config in texture_configs.items():
                new_texture_path = os.path.join(texture_dst_dir, texture_name)
                new_texture_config = (texture_config[0], new_texture_path)
                texture_config = new_texture_config
        
        result.update(texture_configs)     
    return result

def create_xml(texture_config):
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
    if os.path.exists(xml_path):
        if serializer.open():
            if serializer.bmp_config.compare(texture_bmp_config):
                if p4.use_p4():
                    p4_output = p4.P4LogOutput()
                    if not p4.p4_add(texture_path,p4_output=p4_output):  
                        MSFS2024_LOGGER.error(
                            message=f"'{texture_base_name}' : Could not be Marked for Add.",
                            details=f"P4 error:\n{str(p4_output)}",
                        )
                    p4_output = p4.P4LogOutput()
                    if  not p4.p4_add(xml_path,p4_output=p4_output):
                        MSFS2024_LOGGER.error(
                            message=f"'{xml_base_name}' : Could not be Marked for Add.",
                            details=f"P4 error:\n{str(p4_output)}",
                        )

                MSFS2024_LOGGER.info(
                    message=f"'{xml_base_name}' : Has been generated.",
                    details=("Xml generation skipped since it already exists:\n"
                             f"{texture_path}")
                )
                return
        else:
            os.remove(xml_path)

    log_details="Xml was created:\n"
    if not serializer.bmp_config.compare(texture_bmp_config):
        log_details="Xml was overwritten with a new config:\n"

    serializer.bmp_config.copy(texture_bmp_config)

    if p4.use_p4():
        p4_output = p4.P4LogOutput()
        if not p4.p4_edit(texture_path,p4_output=p4_output):
            MSFS2024_LOGGER.error(
                message=f"'{texture_base_name}' : Could not be opened for edit.",
                details=f"P4 error:\n{str(p4_output)}",
            )
        p4_output = p4.P4LogOutput()
        if not p4.p4_edit(xml_path,p4_output=p4_output):
            MSFS2024_LOGGER.error(
                message=f"'{xml_base_name}' : Could not be opened for edit.",
                details=f"P4 error:\n{str(p4_output)}",
            )

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
    
    return

def export_texturelib_with_gltf(gltf_paths, keep_originals=True, texture_dst_dir=''):
    """
        Use a list of gltf paths to parse them and create the xml textures 
        needed next to all textures found in the devmod project
    """
    if len(gltf_paths) < 1:
        return
    global MSFS2024_LOGGER
    MSFS2024_LOGGER = msfs_logs.get_logger()
    print(f"[TextureLib] New TextureLib generation started at {str(datetime.datetime.now())}")
    time_start = time.time()

    texture_configs = get_gltfs_texture_configs(gltf_paths, keep_originals, texture_dst_dir)

    for texture_name, texture_config in texture_configs.items():
        if ' ' in texture_name:
            MSFS2024_LOGGER.error(
                message=f"'{texture_name}' : Contains whitespaces.",
                details=(f"Texture name '{texture_name}' contains whitespaces,\n"
                    "XML will not be generated. Please remove the whitespace before regenerating."
                )
            )
            continue

        print(f"[TextureLib] Generating XML for texture '{texture_name}'.")
        create_xml(texture_config)
    
    delta = round(time.time() - time_start, 3)
    print(f"[TextureLib] Operation completed in {delta}")
