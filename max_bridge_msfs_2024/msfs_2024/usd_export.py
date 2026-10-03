from __future__ import annotations
import re

import bpy

from _addons_common import geometry_node_utils

from max_bridge_msfs_2024 import logger

from max_bridge_msfs_2024.common.usd_properties import *
from max_bridge_msfs_2024.common import obj_utils
from max_bridge_msfs_2024.common.usd_export import GenericUSDExporter

from max_bridge_msfs_2024.msfs_2024.msfs_properties import *
from max_bridge_msfs_2024.msfs_2024 import export_utils, dependencies

from io_scene_gltf2_msfs_fss.blender import msfs_gizmo
from io_scene_gltf2_msfs_fss.io.exp import lod_groups as exp_lod_groups

logging=logger.getLogger()

class MSFS2024USDExporter(GenericUSDExporter):
    EXPORTER = "MSFS2024USDExporter"  # used in export_definition

    custom_object_classes = MSFS2024_CustomObjectClasses

    @classmethod
    def can_export(cls) -> bool:

        return dependencies.are_dependencies_loaded(show_warning=True)

    # region Custom Properties

    @classmethod
    def get_mat_custom_properties(cls, material: bpy.types.Material) -> None | dict:
        """Reimplement this function to get custom material properties dict.

        Args:
            material: material to process.

        Returns:
            Custom material properties.
        """
        properties={}
        for prop in MSFS2024_MaterialProperties:

            if hasattr(material,prop.blender_name):
                value=getattr(material,prop.blender_name)
                properties[prop.name]=export_utils.convert_mat_prop(prop,value)
            else :
                logging.debug(f"No attrib {prop.name} on material {material.name}")

        return properties

    @classmethod
    def get_obj_custom_properties(cls, obj: bpy.types.Object) -> None | dict:
        """Get MSFS 2024 export properties.

        Args:
            obj: object to process.

        Returns:
            Custom object properties
        """
        if obj.parent is not None:#artists can only export node that at scene root level
            return None

        export_props = {}

        target_lod_group = None
        target_lod = None
        scene_lod_groups = exp_lod_groups.get_scene_lod_groups(bpy.context.scene)
        for lod_group in scene_lod_groups:
            for lod in lod_group.lods:
                if lod.objectLOD == obj:
                    target_lod = lod
                    target_lod_group = lod_group
                    break

        if target_lod_group:
            for prop in MSFS2024_ObjectExportProperties:
                prop_blender_name = prop.blender_name

                if prop.blender_name == NOTIMPLEMENTED:
                    continue

                if prop == MSFS2024_ObjectExportProperties.LOD_VALUE:
                    # if hasattr(target_lod,prop_blender_name):
                    export_props[prop.name] = getattr(
                        target_lod, prop_blender_name, None
                    )

                else:
                    # if hasattr(target_lod_group,prop_blender_name):
                    export_props[prop.name] = getattr(
                        target_lod_group, prop_blender_name, None
                    )

        if export_props:
            return export_props
        return None

    @classmethod
    def get_custom_class_name(cls, obj: bpy.types.Object) -> str | None:

        custom_class_name = None

        if obj.type == "LIGHT" :
            try:
                msfs_light_type = obj.data.msfs_light_type
                if msfs_light_type is not None:
                    return msfs_light_type
            except AttributeError:
                return custom_class_name

        if obj.type == "CURVE" :
            gizmo_attributes = msfs_gizmo.get_gizmo_attributes(obj)
            if gizmo_attributes:
                return gizmo_attributes.gizmo_type.identifier

        return custom_class_name

    @classmethod
    def get_obj_custom_class_properties(
        cls,
        obj: bpy.types.Object,
        class_properties_def: CustomClassPropertiesDef,
    ) -> None | dict:
        """
        Args:
            obj: object to process.

        Returns:
            Custom object properties
        """
        class_properties = {}
        to_parse = obj
        if class_properties_def in LIGHTS_CLASS_PROPERTIES_DEFS:
            try:
                to_parse = obj.data.msfs_light_properties
            except AttributeError:
                pass
          
        for prop in class_properties_def:
            blender_name :str = prop.blender_name
            if blender_name == NOTIMPLEMENTED:
                continue

            if blender_name.startswith("Modifiers["):
                # Prop is a modifier input
                try:
                    modifier_id_name = re.search("\[(.+?)\]", blender_name).group(1)
                except :
                    continue

                if not modifier_id_name:
                    continue
                modifier = geometry_node_utils.get_modifier_by_node_group(obj, modifier_id_name)
                if not modifier:
                    continue

                # property is a modifier input
                parts = blender_name.split(":", maxsplit=1)
                if not len(parts) == 2:
                    print(f"{prop.name} in {class_properties_def} is not properly formatted")
                    continue
                input_label = parts[-1]
                value = geometry_node_utils.get_modifier_input(modifier, input_label)
                if value is geometry_node_utils.NotFound:
                    logging.debug(f"No class property {prop.name} on obj '{obj.name}'")
                    logging.debug(f"{obj.name} - Modifier {modifier_id_name}: {blender_name} was not found!")
                    class_properties[prop.name] = prop.blender_default
                    continue

                value = export_utils.convert_custom_class_prop(prop.prop_type, value)
                class_properties[prop.name] = value

            else:
                try:
                    value = obj_utils.get_nested_attr_value(to_parse, prop.blender_name)
                    value = export_utils.convert_custom_class_prop(
                        prop.prop_type, value
                    )
                    class_properties[prop.name] = value
                except (AttributeError, KeyError):
                    logging.debug(f"No class property {prop.name} on obj '{obj.name}'")
                    class_properties[prop.name] = prop.blender_default

        return class_properties

    # endregion
