"""Module containing the base class GenericUSDExporter.
"""

from __future__ import annotations


import json
import socket

from dataclasses import dataclass
from max_bridge_msfs_2024 import logger
from max_bridge_msfs_2024.common import (
    mat_utils,
    obj_utils,
    ui_utils,
    profiling,
    attrib_utils,
    anim_utils
)
from max_bridge_msfs_2024.common.usd_properties import *
from max_bridge_msfs_2024.host import HOST, MAXPORT

import bpy

logging = logger.getLogger()

# region Types
PARENT_OPE = tuple[bpy.types.Object, bpy.types.Object]
ATTRIB_OPE = list[tuple[str, str]]
# endregion

@dataclass
class PreProcessResult:
    objects: list[bpy.types.Object]
    materials: list[bpy.types.Material]
    export_def: ExportDef


class GenericUSDExporter:
    """Base Class for USD Exporters. It takes care of all basic things
    for proper usd export to Blender. On export, it generates
    a usdc an a json containing various definitions for 3dsMax import.

    It can be easily customized by overriding these functions :
        get_mat_custom_properties()
        get_obj_custom_properties()
        get_obj_custom_class_properties()

    In order to use get_obj_custom_class_properties() you need to 
    set custom_object_classes var with your own enum derived from CustomObjectClasses.

    Do not instantiate this class.
    """

    # region Exporter Def
    EXPORTER = "GenericUSDExporter"  
    FROM_DCC = DCCNames.blender.value  
    TARGET_DCC = DCCNames.max.value
    # endregion
    # Assign CustomObjectClasses if necessary
    custom_object_classes: CustomObjectClasses | None = None

    @classmethod
    def can_export(cls) -> bool:
        return True

    # region Custom Properties to reimplement

    @classmethod
    def get_mat_custom_properties(cls, material: bpy.types.Material) -> None | dict:
        """Reimplement this function to get custom material properties dict.

        Args:
            material: material to process.

        Returns:
            Custom material properties.
        """
        return None

    @classmethod
    def get_obj_custom_properties(cls, obj: bpy.types.Object) -> None | dict:
        """Reimplement this function to get custom object properties dict.

        Args:
            obj: object to process.

        Returns:
            Custom object properties
        """
        return None

    @classmethod
    def get_custom_class_name(cls, obj: bpy.types.Object) -> str | None:
        return None

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
        return None

    # endregion

    # region other hooks to reimplements
    @classmethod
    def preprocess_objects(cls, duplicated_objects: list[bpy.types.Object])-> list[bpy.types.Object]:
        """Use this function to edit object before processing them in bridge pipeline.
        """
        return duplicated_objects
    # endregion

    # region Preprocess
    # region Object Definition
    @classmethod
    def _construct_objects_definitions(
        cls,
        duplicated_objects: list[bpy.types.Object],
        original_objects: list[bpy.types.Object],
        custom_classes_defs: dict[CustomClassDef],
    ) -> list[ObjectDef]:

        object_definitions = []

        for handle, obj in enumerate(duplicated_objects):

            data_block_name = None
            try:
                data_block_name = obj.data.name
            except AttributeError:
                pass

            # Get custom class properties
            custom_class_properties = None
            custom_class_def: CustomClassDef = custom_classes_defs.get(
                str(handle), None
            )
            type = None
            if custom_class_def:
                custom_class_properties = custom_class_def.properties
                type = custom_class_def.name
            else:
                type = obj_utils.get_basic_obj_type(obj)

            original_object = original_objects[handle]
            node_def = ObjectDef(
                handle=handle,
                name=original_object.name,
                custom_properties=cls.get_obj_custom_properties(original_object),
                custom_class_properties=custom_class_properties,
                obj_data=data_block_name,
                animated=anim_utils.is_animated(obj),
                type=type,
            )

            object_definitions.append(node_def)

        return object_definitions

    @classmethod
    def _get_custom_class_def(cls, obj: bpy.types.Object) -> None | CustomClassDef:
        class_def = None
        if not cls.custom_object_classes:
            return None
        for cust_class in cls.custom_object_classes:
            cust_class: CustomObjectClasses
            if cust_class.blender_class_name == cls.get_custom_class_name(obj):
                obj_class_props = cls.get_obj_custom_class_properties(
                    obj, cust_class.class_properties
                )
                class_def = CustomClassDef(
                    name=cust_class.name, properties=obj_class_props
                )
                break
        return class_def

    # endregion

    # region Material Definition
    @classmethod
    def _construct_material_library(
        cls, materials: list[bpy.types.Material], original_names: list[str]
    ):
        """
        Material library is a list of material defintion.
        Material definition is defined by a unique handle and properties.
        Rename Material with a unique handle before export.
        """
        material_library = []
        for handle, mat in enumerate(materials):
            mat_def = MaterialDef(
                handle=handle,
                name=original_names[handle],
                custom_properties=cls.get_mat_custom_properties(mat),
            )

            material_library.append(mat_def)

        return material_library

    @staticmethod
    def _temp_rename_materials(materials: list[bpy.types.Material])->list[str]:
        return obj_utils.unique_rename_objects(materials)

    @staticmethod
    def _revert_temp_rename_materials(
        materials: list[bpy.types.Material],
        material_library: list[MaterialDef],
    ):
        for mat, mat_def in zip(materials, material_library):
            mat.name = mat_def.name

    @staticmethod
    def _prepare_color_attribs(objects: list[bpy.types.Object]) -> list[ATTRIB_OPE]:
        """
        Prepare obj color attributes for USD Export.
        """
        rename_operations = []
        for obj in objects:
            if not obj_utils.is_mesh(obj):
                continue
            color_attrib_name = USDMeshAttributes.VERTEX_COLOR.value
            alpha_attrib_name = USDMeshAttributes.VERTEX_ALPHA.value
            active_render_color_attribute = attrib_utils.get_render_color_attribute(obj)

            rename_ope = []
            # Store how we rename attribute for export in order to revert it back
            if active_render_color_attribute:
                # First we check if there are no attributes named exactly like USD color attribute.
                color_attrib = attrib_utils.get_attrib_by_name(obj, color_attrib_name)
                if (
                    color_attrib and color_attrib != active_render_color_attribute
                ):  # rename it to avoid conflict
                    unique_name = attrib_utils.get_unique_attrib_name(obj)
                    # ope is a tuple containing original name and new name.
                    ope: ATTRIB_OPE = (color_attrib.name, unique_name)
                    rename_ope.append(ope)
                    color_attrib.name = unique_name

                alpha_attrib = attrib_utils.get_attrib_by_name(obj, alpha_attrib_name)
                if alpha_attrib:
                    unique_name = attrib_utils.get_unique_attrib_name(obj)
                    ope = (alpha_attrib.name, unique_name)
                    rename_ope.append(ope)
                    alpha_attrib.name = unique_name

                # Rename active render color attribute
                ope = (active_render_color_attribute.name, color_attrib_name)
                rename_ope.append(ope)
                active_render_color_attribute.name = color_attrib_name

                attrib_utils.create_attrib_from_alpha(
                    obj, color_attrib_name, alpha_attrib_name
                )
            rename_operations.append(rename_ope)
        return rename_operations

    # @staticmethod
    # def _revert_color_attribs(
    #     objects: list[bpy.types.Object], rename_operations: list[ATTRIB_OPE]
    # ):
    #     """
    #     Revert attributes back to their original state before being processed by set_obj_color_attrib
    #     """
    #     for obj, rename_ope in zip(objects, rename_operations):
    #         if not obj_utils.is_mesh(obj):
    #             return
    #         alpha_attrib_name = USD_Mesh_Attributes.vertex_alpha.value
    #         attrib_utils.remove_attribute_by_name(obj, alpha_attrib_name)

    #         for ope in rename_ope:
    #             attrib = attrib_utils.get_attrib_by_name(obj, ope[1])
    #             if (
    #                 attrib
    #             ):  # attrib can be None when it's already treated, happens with linked meshes
    #                 attrib.name = ope[0]

    @classmethod
    def _replace_custom_classes_by_dummies(
        cls,
        objects: list[bpy.types.Object],
    ) -> tuple[list[bpy.types.Object], dict[CustomClassDef]]:
        """Replace objects with custom classes by dummies and store
        their properties inside a CustomClassDef.
        Usefull whend dealing with special objects classes not supported by usd.

        All CustomClassDef are stored inside a CustomClassDef dictionnary:
        custom_types_definitions key corresponds to object handle.
        custom_types_definitions value correspond to ObjectTypeDef

        Args:
            objects: _description_
        Returns:
            Tuple containing list of objects and a dict of custom object types
            definitions.
        """

        _objects=[]
        custom_classes_defs: dict[CustomClassDef] = {}
        if not cls.custom_object_classes:
            return (objects, custom_classes_defs)

        for obj in objects:
            handle = str(obj_utils.get_handle_from_name(obj.name))
            class_def = cls._get_custom_class_def(obj)

            if class_def:
                custom_classes_defs[handle] = class_def
                new_obj = obj_utils.replace_obj_by_dummy(obj)
                _objects.append(new_obj)
            else:
                _objects.append(obj)

        return (_objects, custom_classes_defs)

    # @staticmethod
    # def _temp_unparent(objects: list[bpy.types.Object]) -> list[PARENT_OPE]:
    #     """
    #     Blender USD Importer export parent object even when
    #     only children is in objects list.
    #     We temporary unparent children in place.
    #     """
    #     parent_operations = []
    #     for obj in objects:
    #         if obj.parent is None:
    #             continue
    #         if obj.parent not in objects:
    #             ope: PARENT_OPE = (obj, obj.parent)
    #             all_parents = obj_utils.get_all_parents(obj)
    #             # reparent to closest parent
    #             new_parent = None
    #             for parent in all_parents:
    #                 if parent in objects:
    #                     new_parent = parent
    #             obj_utils.set_parent(obj, new_parent)
    #             parent_operations.append(ope)
    #     return parent_operations

    # @staticmethod
    # def _revert_temp_reparent(parent_operations: list[PARENT_OPE]):
    #     for child, parent in parent_operations:
    #         obj_utils.set_parent(child, parent)

    @staticmethod
    def make_usd_exportable(objects: list[bpy.types.Object]):
        """Prevent USD Exporter crash by fixing
        empty curves.
        """
        for obj in objects:
            # Make sure curves have at least one point.
            # empty curve makes the usd exporter crash!
            if obj.type == "CURVE":
                curve_data: bpy.types.Curve = obj.data
                if not curve_data.splines:
                    spline = curve_data.splines.new("POLY")
                    spline.points.add(1)
                    
    @classmethod
    def _preprocess_objects(cls, objects: list[bpy.types.Object]) -> PreProcessResult:
        """Clone objects and prepare them for export:
        -Unique rename objects and their materials.
        -Replace Instances by dummies.
        -Replace custom classes by dummies.
        -Construct object definitions.

        Args:
            objects: objects to process.

        Returns:
            Tuple containing cloned objects, materials, and global export definition.
        """
        objects, duplicated_objects = obj_utils.duplicate_objects(objects)
        cls.make_usd_exportable(duplicated_objects)
        duplicated_objects = cls.preprocess_objects(duplicated_objects)
        cls._prepare_color_attribs(duplicated_objects)
        # attrib_operations = cls._prepare_color_attribs(duplicated_objects)
        # parent_operations = cls._temp_unparent(duplicated_objects)
        unique_materials = mat_utils.get_unique_materials(duplicated_objects)
        original_materials_names = cls._temp_rename_materials(unique_materials)
        material_library = cls._construct_material_library(
            unique_materials, original_materials_names
        )
        # Assign unique names containing handles
        original_object_names = []
        for obj in objects:
            original_object_names.append(obj.name)
        obj_utils.unique_rename_objects(duplicated_objects)

        # Replace custom object types by dummies
        duplicated_objects, custom_classes_defs = cls._replace_custom_classes_by_dummies(
            duplicated_objects
        )

        object_definitions = cls._construct_objects_definitions(
            duplicated_objects=duplicated_objects,
            original_objects=objects,
            custom_classes_defs=custom_classes_defs,
        )

        export_def = ExportDef(
            objects=object_definitions,
            layers=[],
            material_library=material_library,
        )

        return PreProcessResult(
            duplicated_objects,
            unique_materials,
            # parent_operations,
            # attrib_operations,
            export_def,
        )

    @classmethod
    def _revert_preprocess_objects(cls, preprocess_result: PreProcessResult):
        """Set scene back to its original state by reverting every
        editing done during objects preprocessing.

        Args:
            preprocess_result
        """

        for obj in preprocess_result.objects:
            bpy.data.objects.remove(obj)
        # cls._revert_temp_reparent(preprocess_result.parent_operations)
        cls._revert_temp_rename_materials(
            preprocess_result.materials,
            preprocess_result.export_def.material_library,
        )
        # cls._revert_temp_rename_objects(
        #     preprocess_result.objects, preprocess_result.export_def.objects
        # )
        # cls._revert_color_attribs(
        #     preprocess_result.objects, preprocess_result.attrib_operations
        # )

    # endregion

    # region Export

    @classmethod
    def export_usd(cls, objects: list[bpy.types.Object], usd_path: str) -> str:
        """Export objects to a usdc (binary).

        Args:
            objects: List of objects to export.
        Return:
            Exported USD path.
        """

        usd_path += ".usdc"

        preprocess_result: PreProcessResult = cls._preprocess_objects(objects)

        export_def = preprocess_result.export_def
        export_def.path = usd_path
        export_def.from_dcc = cls.FROM_DCC
        export_def.target_dcc = cls.TARGET_DCC
        export_def.exporter = cls.EXPORTER

        to_export = preprocess_result.objects 

        create_json_from_def(export_def)
        try:
            obj_utils.select_objects(to_export)
            bpy.ops.wm.usd_export(
                filepath=usd_path,
                selected_objects_only=True,
                visible_objects_only=False,
                export_animation=True,
                export_hair=False,
                export_uvmaps=True,
                export_normals=True,
                export_materials=True,
                use_instancing=True,
                evaluation_mode="VIEWPORT",
                generate_preview_surface=True,
                export_textures=False,
                root_prim_path="/root"
            )
        except:
            usd_path=""
            pass

        cls._revert_preprocess_objects(preprocess_result)

        obj_utils.select_objects(objects)
        return usd_path

    

    @classmethod
    def export_selected(cls, usd_path: str) -> str:
        """Export selected to usdc

        Args:
            usd_path: usd path without file extension.

        Returns:
            Export success state.
        """
        selected_objects = bpy.context.selected_objects
        if not selected_objects:
            ui_utils.message_popup(
                ui_utils.PopUpLevel.INFO,
                title="Bridge",
                message="No objects selected.",
            )
            return
        # rt.autosave.autobackupnow() #autoback in case of trouble during process
        # logging.info("Autobackup scene before bridge process.")

        usd_path = cls.export_usd(selected_objects, usd_path)

        return usd_path

    @classmethod
    def send_selected_to_max_socket(cls) -> bool:
        """Send selected objects to max socket.

        Returns:
            Export success state.
        """
        if not cls.can_export():
            logging.info("Export Cancelled")
            return False

        profiler = profiling.start_profiler()

        usd_path = str(DEFAULT_EXPORT_DIR / "from_blender")

        exported_usd_path = cls.export_selected(usd_path)
        if not exported_usd_path:
            return False
        try:
            json_data = {"path": exported_usd_path}
            json_data = json.dumps(json_data, default=vars).encode(
                "ascii"
            )  # return byte string for socket input
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((HOST, MAXPORT))
                s.sendall(json_data)

        except socket.error:
            ui_utils.message_popup(
                ui_utils.PopUpLevel.CRITICAL,
                title="Connection Error",
                message="Can't Connect to Bridge Server.\nCheck if bridge is started on your other DCC.",
            )
            return False
        logging.info("Export Done.")
        logging.info(f"Debug logs available here: {logger.log_filepath}")
        profiling.stop_profiler(profiler)

        return True

    # endregion
