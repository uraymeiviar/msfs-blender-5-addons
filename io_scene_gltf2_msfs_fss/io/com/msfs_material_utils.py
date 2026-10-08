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

import bpy
import os

from _addons_common import data_utils

if bpy.app.version >= (4, 5, 0):
    from io_scene_gltf2.blender.imp.image import BlenderImage
    from io_scene_gltf2.blender.exp.material.search_node_tree import (
        NodeSocket
    )
    from io_scene_gltf2.blender.exp.material.texture_info import (
        gather_texture_info
    )
else:
    from io_scene_gltf2.blender.imp.gltf2_blender_image import BlenderImage
    
    if bpy.app.version >= (4, 2, 0):
        from io_scene_gltf2.blender.exp.material.gltf2_blender_search_node_tree import (
            NodeSocket
        )
        
    if bpy.app.version >= (3, 6, 0):
        from io_scene_gltf2.blender.exp.material.gltf2_blender_gather_texture_info import (
            gather_texture_info
        )
    else:
        from io_scene_gltf2.blender.exp.gltf2_blender_gather_texture_info import (
            gather_texture_info
        )


from ...blender.utils.msfs_material_nodes_utils import (
    add_node,
    link,
    MSFS2024_ShaderNodeTypes,
    MSFS2024_PrincipledBSDFInputs
)

from .msfs_data_utils import MSFS2024_DataUtils

class MSFS2024_MaterialUtils:

    # key : absolute texture path, value : gltf texture info
    _tex_infos_cache: dict = {}
    @staticmethod
    def reset_tex_infos_cache():
        MSFS2024_MaterialUtils._tex_infos_cache = {}

    @staticmethod
    def _add_tex_info_to_cache(image_name: str, texture_info):
        image_name = bpy.path.abspath(image_name)
        MSFS2024_MaterialUtils._tex_infos_cache[image_name] = texture_info

    @staticmethod
    def _get_tex_info_from_cache(image_name: str):
        image_name = bpy.path.abspath(image_name)
        return MSFS2024_MaterialUtils._tex_infos_cache.get(image_name, None)

    @staticmethod
    def get_texture_info(
        blender_material: bpy.types.Material,
        attribute: str,
        export_settings: dict,
    ):
        image = getattr(
            blender_material,
            attribute
        )

        if image is None:
            return None

        texture_info = MSFS2024_MaterialUtils._get_tex_info_from_cache(image.name)

        if texture_info is None:
            texture_info = MSFS2024_MaterialUtils.export_image(
                blender_image=image,
                export_settings=export_settings
            )

            # Add texture in exported_textures map
            if texture_info is not None:
                MSFS2024_MaterialUtils._add_tex_info_to_cache(image.name, texture_info)

        return texture_info

    @staticmethod
    def create_image(index, import_settings):
        pytexture = import_settings.data.textures[index]
        pyimg = import_settings.data.images[pytexture.source]

        if pyimg and pyimg.blender_image_name and pyimg.blender_image_name in bpy.data.images:
            return bpy.data.images[pyimg.blender_image_name]

        BlenderImage.create(import_settings, pytexture.source)
        return bpy.data.images[pyimg.blender_image_name]

    @staticmethod
    def export_image(blender_image: bpy.types.Image, export_settings):
        # Make sure image is editable or gather_texture_info will return None
        # It happens when image is linked
        if not data_utils.is_editable(blender_image):
            blender_image = blender_image.copy()
            blender_image.make_local()

        if export_settings["gltf_keep_original_textures"] and not blender_image.filepath:
            print(
                f"Skip image '{blender_image.name}': 'Keep Original Texture' is enabled, "
                "but the image data has no associated file path."
            )
            return None
        # Create a new temp material dedicated to image export
        # Prevents issue with gltf addon gather_texture_info()
        # This material will be automatically deleted by MSFS2024_DataUtils.purge_new_data()
        temp_mat = bpy.data.materials.new("temp_image_export_mat")
        temp_mat.use_nodes = True

        nodes = temp_mat.node_tree.nodes
        links = temp_mat.node_tree.links

        # Create a fake texture node temporarily (unfortunately this is the only solid way of doing this)
        texture_node = add_node(
            nodes=nodes,
            name="Base Color Texture Output",
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODETEXIMAGE.value
        )
        texture_node.image = blender_image

        # Save image path before converting it to an absolute path
        saved_image_path = blender_image.filepath

        # Make sure that the path of the image is absolute
        texture_node.image.filepath = bpy.path.abspath(texture_node.image.filepath)
        texture_node.image.filepath = os.path.realpath(texture_node.image.filepath)

        # Create shader to plug texture into
        principled_bsdf_node = add_node(
            nodes=nodes,
            name="Principled BSDF Temp Node",
            type_node=MSFS2024_ShaderNodeTypes.SHADENODEBSDFPRINCIPLED.value
        )

        texture_info = None

        # region Gather texture info
  
        link(
            links,
            texture_node.outputs[0],
            principled_bsdf_node.inputs[MSFS2024_PrincipledBSDFInputs.BASECOLOR.value]
        )

        if bpy.app.version >= (4, 2, 0):
            node_socket = NodeSocket(
                principled_bsdf_node.inputs[MSFS2024_PrincipledBSDFInputs.BASECOLOR.value],
                [temp_mat.node_tree]
            )

            texture_info = gather_texture_info(
                node_socket,
                (node_socket,),
                export_settings
            )
        else:
            texture_info = gather_texture_info(
                principled_bsdf_node.inputs[MSFS2024_PrincipledBSDFInputs.BASECOLOR.value],
                (principled_bsdf_node.inputs[MSFS2024_PrincipledBSDFInputs.BASECOLOR.value],),
                export_settings
            )

        

        # endregion

        # Restore saved image file path
        blender_image.filepath = saved_image_path

        if texture_info is None:
            return None

        # Some versions of the Khronos exporter have gather_texture_info return a tuple
        if isinstance(texture_info, tuple):
            texture_info = texture_info[0]

        if hasattr(texture_info, "tex_coord"):
            texture_info.tex_coord = None

        return texture_info

    @staticmethod
    def _set_material_for_export(material: bpy.types.Material):
        """Replaces the material node tree with a Principled BSDF that uses vertex color
        and vertex alpha.
        This is mandatory in order to export vertex color and vertex alpha
        with gltf exporter in blender 4.2.

        Args:
            material: Material to modify.
        """

        if not material or not material.use_nodes:
            return None

        # Get the node tree
        node_tree = material.node_tree
        nodes = node_tree.nodes
        links = node_tree.links

        nodes.clear()

        # Create new nodes
        principled_bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
        vertex_color_node = nodes.new(type="ShaderNodeVertexColor")
        material_output = nodes.new(type="ShaderNodeOutputMaterial")

        # use active vertex color
        vertex_color_node.layer_name = ""

        links.new(
            vertex_color_node.outputs["Color"],
            principled_bsdf.inputs["Base Color"]
        )
        links.new(
            vertex_color_node.outputs["Alpha"],
            principled_bsdf.inputs["Alpha"]
        )
        links.new(principled_bsdf.outputs["BSDF"],
                  material_output.inputs["Surface"]
        )

    @staticmethod
    def create_export_material(mat: bpy.types.Material) -> bpy.types.Material:
        """Create export material from original material.
        This export material is only used during export and is purged after.
        Export Material has an attribute msfs_original name containing
        the name of original material.

        Args:
            mat: Original material.

        Returns:
            Export material.
        """
        new_mat = bpy.data.materials.new("mat_export")
        new_mat.use_nodes = mat.use_nodes
        # Store original name in order to use it later in process
        # cf gather_material_hook in msfs_export.py
        MSFS2024_DataUtils.set_msfs_original_data(new_mat, mat)
        MSFS2024_MaterialUtils._set_material_for_export(new_mat)
        return new_mat

    @staticmethod
    def get_original_material(
        mat_copy: bpy.types.Material,
    ) -> None | bpy.types.Material:

        return MSFS2024_DataUtils.get_msfs_original_data(mat_copy)

    @staticmethod
    def set_obj_materials_for_export(
        obj: bpy.types.Object,
        export_materials: set,
        duplicate_materials: bool = True, 
    ) -> dict[bpy.types.Material]:
        """Set objects materials for export.
        Duplicate materials and set them with a simple Node tree.

        Args:
            obj: blender object.

        Returns:
            List of duplicated materials.
        """
        if not hasattr(obj, "material_slots"):
            return {}

        if not obj.material_slots:

            return {}

        for slot in obj.material_slots:
            mat = slot.material
            if not mat:
                continue

            _mat = export_materials.get(mat.name, None)
            if not _mat:
                if duplicate_materials :
                    _mat = MSFS2024_MaterialUtils.create_export_material(mat)
                else:
                    _mat = mat
                    MSFS2024_MaterialUtils._set_material_for_export(_mat)
                export_materials[mat.name] = _mat  

            # Force object-level material assignment.
            # This prevents material changes from propagating to other objects
            # that share the same mesh.
            slot.link = "OBJECT"
            slot.material = _mat

        return export_materials

    @staticmethod
    def set_objects_materials_for_export(
        objects: list[bpy.types.Object],
        duplicate_materials: bool = True
    ) -> list[bpy.types.Material]:
        """Set all objects materials for export.

        Args:
            objects: list of blender objects.
            duplicate_materials: create new materials instead of treating 
            object's material directly.
        Returns:
            List of duplicated materials.
        """
        export_materials = {}
        for obj in objects:
            MSFS2024_MaterialUtils.set_obj_materials_for_export(
                obj,
                export_materials,
                duplicate_materials
            )

        return list(export_materials.values())

    @staticmethod
    def get_extension_parameter(extension, material, attribute):
        value = extension.get(attribute.extension_name())
        if attribute.extension_name() and value is not None:
            # Safety cast Float to Int in case attribute is an int property
            attr_type = type(getattr(material, attribute.attribute_name()))
            if attr_type is int and isinstance(value, float):
                value = int(value)

            # Safely support same length of value and attribute
            if isinstance(value, list):
                attr_value = getattr(material, attribute.attribute_name())
                value = value[:len(attr_value)]
                value.extend([1.0] * (len(attr_value) - len(value)))

            setattr(
                material,
                attribute.attribute_name(),
                value
            )

    @staticmethod
    def get_extension_texture(extension, material, attribute, settings):
        if (
            attribute.extension_name()
            and extension.get(attribute.extension_name()) is not None
        ):
            texture = MSFS2024_MaterialUtils.create_image(
                index=extension.get(attribute.extension_name(), {}).get("index"),
                import_settings=settings
            )

            setattr(
                material,
                attribute.attribute_name(),
                texture
            )

    @staticmethod
    def set_extension_parameter(extension, material, attribute, with_default_value=False):
        material_value = getattr(material, attribute.attribute_name())
        if (
            attribute.extension_name()
            and (material_value != attribute.default_value())
            or with_default_value
        ):
            extension[attribute.extension_name()] = material_value

    @staticmethod
    def set_extension_texture(
        extension,
        material,
        attribute,
        settings
    ):
        material_value = getattr(material, attribute.attribute_name())
        if material_value is None:
            return

        if (
            attribute.extension_name()
            and material_value != attribute.default_value()
        ):
            texture_info = MSFS2024_MaterialUtils.get_texture_info(material, attribute.attribute_name(), settings)

            if not texture_info:
                return
            extension[attribute.extension_name()] = texture_info
