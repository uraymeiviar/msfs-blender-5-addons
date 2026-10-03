"""
Base USD importer class
"""
from __future__ import annotations

import json

import bpy

from max_bridge_msfs_2024 import logger, addon_prefs

from max_bridge_msfs_2024.common import (
    path_utils,
    attrib_utils,
    obj_utils,
    collection_utils,
    anim_utils,
    profiling
)
from max_bridge_msfs_2024.common.usd_properties import *

logging = logger.getLogger()

# Types aliases
GENERIC_DEFS = dict[bpy.types.ID,SeriazableDef]
OBJECT_DEFS = dict[bpy.types.Object|bpy.types.Bone,ObjectDef]
MATERIAL_DEFS = dict[bpy.types.Material,MaterialDef]

class GenericUSDImporter:
    """Base Class for USD Importers. It takes care of all basic things
    for proper usd import from max to Blender.

    It can be easily customized by overriding these functions :
        set_obj_with_custom_class()
        set_additional_custom_properties()
        on_after_rename()
        set_obj_custom_properties()
        set_material_custom_properties()

    Do not instantiate this class.
    """

    IMPORTER = "GenericUSDImporter"
    TARGET_DCC = DCCNames.max.value

    @classmethod
    def can_import(cls) -> bool:
        return True

    # region Custom Properties functions to reimplement
    @classmethod
    def set_obj_with_custom_class(
        cls,
        obj:bpy.types.Object,
        obj_def: ObjectDef
    )->bpy.types.Object:
        """
        Setup object class.
        Provided object is a placeholder meant to be replaced by a custom object.

        This function is launched before instances restoration.
        """
        return obj

    @classmethod
    def set_additional_custom_properties(
        cls,
        properties: dict,
        imported_object_defs: OBJECT_DEFS,
        imported_material_defs: MATERIAL_DEFS
    ):
        """
        Set miscellenous properties  
        Imported objects are not renamed yet for this step, so unique handles
        are still accessibles.
        """
        pass

    @classmethod
    def set_obj_custom_properties(cls, obj:bpy.types.Object, properties: dict):
        """
        Reimplement this function to setup object using ObjectDef.
        This is launched at end of import process, object is already renamed 
        withs its original name.
        """
        pass 

    @classmethod
    def set_material_custom_properties(cls, material:bpy.types.Material, properties: dict):
        """
        Reimplement this function to set material using MaterialDef.
        This is launched at end of import process, material is already renamed 
        withs its original name.
        """
        pass 
    # endregion

    @classmethod
    def on_before_definitions_set(
        cls,
        imported_objects: list[bpy.types.Object],
        objects_definitions:OBJECT_DEFS,
        materials_definitions:MATERIAL_DEFS
    ):
        """
        Do things before object and material definitions are set
        """
        pass 

    @classmethod
    def on_after_import(
        cls,
        imported_objects: list[bpy.types.Object],
        objects_definitions:OBJECT_DEFS,
        materials_definitions:MATERIAL_DEFS
    ):
        """
        Do things after import process.
        """
        pass 

    # region Post Import Process

    @classmethod
    def _recreate_hierarchy(cls, imported_object_defs: OBJECT_DEFS)->OBJECT_DEFS:
        """Arrange objects in order to reflect 3dsMax hierarchy.
        USD importer create a Dummy in place of original object.
        Objective is to replace these created dummies by their associated object while
        preserving parent/children relation in overall hierarchy.
        """
        obj_to_delete = set()

        for obj, obj_def in imported_object_defs.items():
            if obj in obj_to_delete:
                continue

            if not obj_def:
                continue
            obj_handle = obj_utils.get_handle_from_name(obj.name)
            # Check if Dummy was created by usd importer
            # If obj_def.type is not same as obj type, then it's created by usd importer
            is_usd_dummy = obj_utils.is_dummy(obj) and obj_def.type != BasicObjectTypes.DUMMY

            if not is_usd_dummy:
                continue
            # Find object associated with Dummy created by usd
            associated_obj = None
            for _obj in imported_object_defs.keys():
                if _obj is obj:
                    continue
                if obj_handle == obj_utils.get_handle_from_name(_obj.name):
                    associated_obj = _obj
                    break

            if associated_obj:
                # Replace empty by associated obj
                if obj_utils.has_armature_mod(associated_obj) and obj.parent_type == "BONE":
                    # Do not reparent objects with armature to bones, this is not supported by gltf
                    continue
                # Associated obj should have the same origin and animation as obj
                obj_utils.replace_obj_by(
                    obj, 
                    associated_obj, 
                    transform=False, 
                    delete=False
                )

                anim_utils.copy_animation(obj, associated_obj)

                obj_to_delete.add(obj)

        obj_utils.delete_objects(list(obj_to_delete))

        imported_object_defs = cls._remove_invalid_defs(imported_object_defs)

        return imported_object_defs

    @staticmethod
    def _get_armature_first_bone_handle(armature_obj:bpy.types.Object)-> None|int:

        armature_data : bpy.types.Armature = armature_obj.data
        first_bone = None
        try:
            first_bone = armature_data.bones[0]
        except IndexError:
            return
        return obj_utils.get_handle_from_name(first_bone.name)

    @staticmethod
    def _set_armature_collections(obj:bpy.types.Object, imported_objects:list[bpy.types.Object]):
        """Assign armature in all collections that contains one of its bones
        """
        armature_data : bpy.types.Armature = obj.data
        for bone in armature_data.bones:
            handle = obj_utils.get_handle_from_name(bone.name)
            bone_empty = obj_utils.get_obj_by_handle(imported_objects, handle)
            if not bone_empty:
                continue
            for collection in bpy.context.scene.collection.children_recursive:
                collection: bpy.types.Collection
                if bone_empty in collection.objects.values():
                    collection_utils.add_object_to_collection(obj, collection)

    @staticmethod
    def _recreate_layers(imported_objects:list[bpy.types.Object], layers_definitions: list[LayerDef]):

        for obj in imported_objects:
            collection_utils.unlink_from_all_collections(obj)

        # First create all collections from layer_def
        new_collections = {}
        prefs = addon_prefs.get_addon_prefs()
        for layer_def in layers_definitions:
            collection = None
            if prefs.reuse_existing_collections:
                collection = collection_utils.get_collection(layer_def.name)
            if not collection:
                collection = collection_utils.create_collection(layer_def.name)
            new_collections[layer_def.name] = collection

        scene_collection = bpy.context.scene.collection
        objects_referenced_in_layer = set()
        # Then assign objects in their layers

        for layer_def in layers_definitions:

            collection_objects = []

            for obj in imported_objects:
                handle = obj_utils.get_handle_from_name(obj.name)
                if handle in layer_def.nodes_handle:
                    collection_objects.append(obj)
                    objects_referenced_in_layer.add(obj)

            collection = new_collections[layer_def.name]

            collection_utils.add_objects_to_collection(collection_objects,collection)

            if layer_def.parent_name:
                parent_collection = new_collections.get(layer_def.parent_name,None)
                if not parent_collection:
                    logging.error(f"Collection {collection.name} was not linked in scene because parent collection {layer_def.parent_name} is missing")
                    continue
                collection_utils.link_collection_in_collection(collection,parent_collection)
                logging.info(f"Collection {collection.name} linked in parent collection {parent_collection.name}")
            else:
                collection_utils.link_collection_in_scene(collection)
                logging.info(f"Collection {collection.name} linked in scene")

        # Special case for armatures
        for obj in imported_objects:
            if obj_utils.is_armature(obj) :
                GenericUSDImporter._set_armature_collections(obj, imported_objects)
                objects_referenced_in_layer.add(obj)

        # Finally link all objects not in any layer to scene collection
        scene_collection_objects = []
        for obj in imported_objects:
            if obj not in objects_referenced_in_layer:
                scene_collection_objects.append(obj)

        collection_utils.add_objects_to_collection(scene_collection_objects,scene_collection)
        collection_utils.sort_collection_children(
            bpy.context.view_layer.layer_collection.collection
        )
    @classmethod
    def _clean_usd_import(cls, imported_objects:list[bpy.types.Object])->list[bpy.types.Object]:
        """Remove objects without handle except armatures.
        Objects without handles are created by usd importer (Root, Mtl, etc.)
        Remove useless duplicated children dummies.
        Args:
            imported_objects: List of objects.

        Returns:
            List of objects after clean.
        """

        to_delete = []
        for obj in bpy.context.scene.collection.all_objects:
            if not obj in imported_objects:
                continue
            if obj_utils.is_armature(obj):
                obj.name = "Armature"
                continue
            handle = obj_utils.get_handle_from_name(obj.name)
            if handle is None:
                to_delete.append(obj)

            # Duplicated empty children
            if obj_utils.is_dummy(obj):
                parent = obj.parent
                if not parent:
                    continue
                parent_handle = obj_utils.get_handle_from_name(parent.name)
                if handle == parent_handle and not obj.children:
                    to_delete.append(obj)

        if not to_delete:
            return imported_objects

        for obj in to_delete:
            try:
                imported_objects.remove(obj)
            except ValueError:
                pass
        obj_utils.delete_objects(to_delete)

        cls._fix_skinned_objects_offset(imported_objects)

        return imported_objects

    @classmethod
    def _fix_skinned_objects_offset(cls, imported_objects:list[bpy.types.Object]):
        """
        Fix transform issues introduced by usd importer. 
        Issue happens when skinned object is under an animated dummy (animation addition)
        """
        for obj in imported_objects:
            # Remove armature modifier
            for mod in obj.modifiers:
                if type(mod) == bpy.types.ArmatureModifier:
                    obj.parent = None
        bpy.context.view_layer.update()

    @classmethod
    def _parent_skinned_objects_to_armature(cls, imported_objects:list[bpy.types.Object]):
        """
        Parent skinned objects to armature.
        """
        for obj in imported_objects:
            # Remove armature modifier
            for mod in obj.modifiers:
                if type(mod) == bpy.types.ArmatureModifier:
                    # Reparent and keep transform
                    obj_utils.set_parent_keep_transform(
                        obj, mod.object
                    )

    @classmethod
    def _set_objects_custom_classes(cls, imported_object_defs: OBJECT_DEFS)->OBJECT_DEFS:

        new_object_defs = {}
        for obj, obj_def in imported_object_defs.items():
            if not obj_def:
                continue
            if obj_def.custom_class_properties:
                new_obj = cls.set_obj_with_custom_class(
                    obj, obj_def
                )

                new_object_defs[new_obj] = obj_def

        imported_object_defs.update(new_object_defs)
        imported_object_defs = cls._remove_invalid_defs(imported_object_defs)

        return imported_object_defs

    @classmethod
    def _restore_instances(cls, imported_object_defs: OBJECT_DEFS)->OBJECT_DEFS:
        """
        Replace dummies by their corresponding instances.
        
        """

        new_object_defs = {}
        for obj, obj_def in imported_object_defs.items():

            if not obj_def:
                continue
            source_handle = obj_def.obj_data
            if source_handle is None:
                continue
            source_obj = obj_utils.get_obj_by_handle(imported_object_defs.keys(), source_handle)
            if not source_obj :
                continue

            new_instance = obj_utils.instance_setup(source_obj, obj)
            if new_instance:
                new_object_defs[new_instance] = obj_def

        imported_object_defs.update(new_object_defs)

        imported_object_defs = cls._remove_invalid_defs(imported_object_defs)

        return imported_object_defs

    @staticmethod
    def _set_original_name(obj:bpy.types.Object, obj_def: SeriazableDef):
        obj.name = obj_def.name

        if hasattr(obj, "data") and obj.data != None:
            obj.data.name = obj_def.name
        # Special case for bones
        # They must not have same names as scenes objects for gltf export
        if type(obj) == bpy.types.Bone:
            name = obj.name
            counter = 1
            while name in bpy.data.objects:
                name = f"{name}.{counter:03d}"
                counter += 1
            obj.name = name

    @classmethod
    def _set_objects_original_names(cls, imported_object_defs: dict[bpy.types.ID,ObjectDef]):
        for obj, obj_def in imported_object_defs.items():
            if not obj_def:
                continue
            cls._set_original_name(obj, obj_def)

    @classmethod
    def _set_objects_from_def(
        cls,
        imported_object_defs: OBJECT_DEFS
    ):
        treated_obj_data = []
        for obj, obj_def in imported_object_defs.items():
            if not obj_def:
                continue
            obj_def: ObjectDef
            # cls._set_original_name(obj, obj_def)

            if hasattr(obj, "data") and obj.data not in treated_obj_data:
                attrib_utils.set_obj_color_attrib(obj)
                attrib_utils.rename_uv_maps(obj)
                treated_obj_data.append(obj.data)
            custom_properties = obj_def.custom_properties
            if custom_properties:
                cls.set_obj_custom_properties(obj, custom_properties)

    @classmethod
    def _set_materials_from_def(
        cls,
        imported_material_defs: dict[bpy.types.bpy_struct,MaterialDef]
    ):
        for mat, mat_def in imported_material_defs.items():
            if not mat_def:
                continue
            mat_def: MaterialDef
            cls._set_original_name(mat, mat_def)
            custom_properties = mat_def.custom_properties
            if custom_properties:
                cls.set_material_custom_properties(mat, custom_properties)

    @classmethod
    def _get_animated_objects(
        cls,
        imported_object_defs: OBJECT_DEFS,
    )->list[bpy.types.Object]:
        """Get animated objects.

        Returns:
            Tuple containing a list of animated objects, and a list of static objects
        """
        animated_objects = []

        for obj, obj_def in imported_object_defs.items():
            if obj_def and obj_def.animated:

                animated_objects.append(obj)

        return animated_objects

    @classmethod
    def _get_static_objects(
        cls,
        imported_object_defs: OBJECT_DEFS,
    )->list[bpy.types.Object]:
        """Get static objects

        Returns:
            Tuple containing a list of animated objects, and a list of static objects
        """
        static_objects = []

        for obj, obj_def in imported_object_defs.items():
            if obj_def and not obj_def.animated:

                static_objects.append(obj)

        return static_objects

    @classmethod
    def _get_armatures_bone_object_couples(
        cls,
        imported_object_defs: OBJECT_DEFS,

    )->dict[bpy.types.Object, dict[bpy.types.Bone,bpy.types.Object]]:
        """USD importer can create an object for a corresponding armature bone.
        This can be identified using their handle.
        This function generate a dict of bone/empty couples for each armatures.

        Add bones and associated defs in imported_objects_defs.
        """
        bone_object_couples = {}
        imported_armatures = obj_utils.get_armatures(imported_object_defs.keys())

        armatures_bones = {}
        for armature_obj in imported_armatures:
            armatures_bones[armature_obj] = armature_obj.data.bones
            bone_object_couples[armature_obj] = {}

        new_bone_defs = {}
        for obj, obj_def in imported_object_defs.items():
            if not obj.name in bpy.context.view_layer.objects:
                continue

            obj_handle = obj_utils.get_handle_from_name(obj.name)
            for armature_obj, bones in armatures_bones.items():

                for bone in bones :
                    bone_handle = obj_utils.get_handle_from_name(bone.name)
                    if obj_handle == bone_handle:
                        bone_object_couples[armature_obj][bone] = obj
                        # Create a new entry imported_object_defs using bone
                        new_bone_defs[bone] = obj_def

        imported_object_defs.update(new_bone_defs)

        return bone_object_couples

    @classmethod
    def _process_bones_children(
        cls,
        imported_object_defs: OBJECT_DEFS,

    )->OBJECT_DEFS:
        """USD importer can parent objects under an empty instead of a bone.
        In this function we reparent empties children under associated bone.

        Skip parenting skinned children to bones, this is not supported by gltf.

        Also delete empties that were associated with a bone and are no longer used.
        """

        # to_bone_parent = [] # FOR DEBUG

        armatures_bone_object_couples = cls._get_armatures_bone_object_couples(imported_object_defs)

        animated_world_matrices = {}
        for armature_obj, bone_object_couple in armatures_bone_object_couples.items():
            for bone, obj in bone_object_couple.items():
                # to_bone_parent.extend(obj.children)

                for child in obj.children:
                    if obj_utils.has_armature_mod(child):
                        # Do not reparent objects with armature to bones, this is not supported by gltf
                        continue
                    animated = False
                    if anim_utils.is_animated(child):
                        animated = True
                        animated_world_matrices[child] = child.matrix_world.copy()

                    # Parenting without inverse doesnt work for animated object
                    obj_utils.set_parent_to_bone_keep_transform(
                        child, 
                        armature_obj, 
                        bone.name, 
                        without_inverse=not animated
                    )
        # Correct animated object position after frame evaluation
        obj_utils.frame_eval_and_correct_objects(animated_world_matrices)
        # # DEBUG
        # collection = collection_utils.create_collection("To Bone Parent")
        # collection_utils.add_objects_to_collection(to_bone_parent,collection)
        # collection_utils.link_collection_in_scene(collection)

        useless_dummies = []
        for armature_obj, bone_object_couple in armatures_bone_object_couples.items():
            for bone, obj in bone_object_couple.items():
                if obj_utils.is_dummy(obj) and obj_utils.has_only_empty_children(obj):
                    useless_dummies.append(obj)

        # print(f"useless objects : {useless_dummies}")

        obj_utils.delete_objects(useless_dummies)

        imported_object_defs = cls._remove_invalid_defs(imported_object_defs)
        return imported_object_defs

    @classmethod
    def _convert_hair_curves(
        cls,
        imported_object_defs: OBJECT_DEFS,
    )->OBJECT_DEFS:
        """
        USD importer create hair curve instead of regular curve.
        So we convert them to regular curve here.
        """

        for obj, obj_def in imported_object_defs.items():
            converted_curve = obj_utils.hair_curve_to_regular_curve(obj)
            if converted_curve:
                imported_object_defs[converted_curve] = obj_def

        imported_object_defs = cls._remove_invalid_defs(imported_object_defs)

        return imported_object_defs

    @classmethod
    def _remove_invalid_defs(cls, defs_dict:GENERIC_DEFS)->GENERIC_DEFS:
        """
        Remove defs that referenced deleted data
        """
        updated_defs = {}
        for obj,obj_def in defs_dict.items():
            if obj_utils.obj_is_valid(obj):
                updated_defs[obj] = obj_def

        return updated_defs

    @classmethod
    def _generate_imported_defs_dict(
        cls,
        imported_data: list[bpy.types.bpy_struct],
        object_definitions: list[SeriazableDef]
    ) -> GENERIC_DEFS:
        """
        Associate imported data (key) and their defs (value) into an easy to use dict
        """
        imported_data_defs = {}
        for data in imported_data:
            imported_data_defs[data] = obj_utils.get_obj_def(data, object_definitions)
        return imported_data_defs 
    @classmethod
    def _process_imported_objects(
        cls,
        imported_objects: list[bpy.types.Object],
        imported_materials: list[bpy.types.Material],
        json_data: dict,
    ) -> list[bpy.types.Object]:
        """
        Process imported objects using json data:
        - Bake Animation/ Apply constraints.
        - Recreate 3dsMax hierarchy.
        - Set objects with custom classses.
        - Convert Hair Curves to Regular Curves.
        - Restore Instances.
        - Create Layers (collections).
        - Set additionnal custom properties (scen properties for example).
        - Set objects original names.
        - Set objects from def.
        - Set materials from def.

        Return:
            Processed imported Objects.
        """
        object_definitions = get_object_definitions_from_json(json_data)
        material_definitions = get_material_definitions_from_json(json_data)
        layer_definitions = get_layer_definitions_from_json(json_data)
        custom_property_definitions = get_additional_custom_properties_from_json(
            json_data
        )

        imported_object_defs: OBJECT_DEFS = cls._generate_imported_defs_dict(imported_objects, object_definitions)
        imported_material_defs: MATERIAL_DEFS = cls._generate_imported_defs_dict(imported_materials, material_definitions)

        # Animation
        animated_objects = cls._get_animated_objects(imported_object_defs)
        static_objects = cls._get_static_objects(imported_object_defs)

        if animated_objects:
            anim_utils.bake_objects_animation(animated_objects)

        if static_objects:

            anim_utils.clear_objects_animation(static_objects)

        # Clear modifiers except ArmatureModifier
        obj_utils.clear_modifiers_except(imported_object_defs.keys(), whitelist=[bpy.types.ArmatureModifier])

        cls._parent_skinned_objects_to_armature(imported_object_defs.keys())

        obj_utils.clear_all_constraints(imported_object_defs.keys())

        imported_object_defs = cls._recreate_hierarchy(imported_object_defs)

        imported_object_defs = cls._set_objects_custom_classes(imported_object_defs)

        imported_object_defs = cls._convert_hair_curves(imported_object_defs)

        imported_object_defs = cls._restore_instances(imported_object_defs)

        cls._recreate_layers(imported_object_defs.keys(),layer_definitions)

        # Can't parent a skinned object to a bone , not supported by gltf
        imported_object_defs = cls._process_bones_children(imported_object_defs)

        cls.set_additional_custom_properties(
            custom_property_definitions,
            imported_object_defs,
            imported_material_defs
        )

        # Rename objects to their original names
        # Unique handles are lost after this
        cls._set_objects_original_names(imported_object_defs)
        cls._set_objects_original_names(imported_material_defs)

        # Rename armature bones
        # cls._set_objects_original_names(imported_bone_defs)

        cls.on_before_definitions_set(
            imported_objects,
            imported_object_defs,
            imported_material_defs
        )

        # Object data process, Object and Material Custom Properties
        cls._set_objects_from_def(imported_object_defs)

        cls._set_materials_from_def(imported_material_defs)

        cls.on_after_import(
            imported_objects,
            imported_object_defs,
            imported_material_defs
        )

        return list(imported_object_defs.keys())

    # endregion

    # region Import
    @classmethod
    def _import_usd(
        cls, usd_path:str
    ) -> tuple[list[bpy.types.Object], list[bpy.types.Material]]:
        # clean caches files in order to force usd files refresh
        bpy.data.batch_remove(bpy.data.cache_files)

        scene_materials = list(bpy.data.materials)
        kwargs = {
            "filepath": usd_path,
            "check_existing": False,
            "filter_usd": True,
            "filter_folder": True,
            "filemode": 8,
            "relative_path": True,
            "display_type": "DEFAULT",
            # sort_method:'',
            "filter_glob": "*.usd",
            "scale": 1.0,
            "set_frame_range": True,
            "import_cameras": True,
            "import_curves": True,
            "import_lights": True,
            "import_materials": True,
            "import_meshes": True,
            "import_volumes": True,
            "import_shapes": True,
            "import_subdiv": True,
            # import_instance_proxies:True,
            "import_visible_only": False,
            "create_collection": False,
            "read_mesh_uvs": True,
            "read_mesh_colors": True,
            "prim_path_mask": "",
            "import_guide": False,
            "import_proxy": False,
            "import_render": False,
            "import_all_materials": False,
            "import_usd_preview": False,
            "set_material_blend": True,
            "light_intensity_scale": 1.0,
            "mtl_name_collision_mode": "MAKE_UNIQUE",
            "import_textures_mode": "IMPORT_NONE",
        }
        if bpy.app.version >= (4, 1, 0):
            kwargs["support_scene_instancing"] = False

        bpy.ops.wm.usd_import(**kwargs)
    
        imported_objects = []
        # Get clean obj pointer from bpy.data
        for obj in bpy.context.selected_objects:
            imported_objects.append(bpy.data.objects[obj.name])
        imported_objects = cls._clean_usd_import(imported_objects)
        imported_materials = []
        for mat in bpy.data.materials:
            if mat not in scene_materials:
                imported_materials.append(mat)
        return (imported_objects, imported_materials)

    # do not reimplement
    @classmethod
    def import_usd(cls, usd_path: str) -> bool:
        """
        Import USD created by 3dsMax bridge.

        Args:
            usd_path: absolute usd path.
        """
        if not cls.can_import():
            logging.info("Import Cancelled")
            return False
        profiler = profiling.start_profiler()

        logging.info("Begin Import.")

        json_data = ""
        json_path = path_utils.get_associated_json(usd_path)
        with open(json_path, "r") as file:
            json_data = json.load(file)

        logging.debug(f"JSON_DATA: {json_data}")

        imported_objects, imported_materials = cls._import_usd(usd_path)

        imported_objects = cls._process_imported_objects(
            imported_objects, imported_materials, json_data
        )

        obj_utils.select_objects(imported_objects)
        logging.info("Import Done")

        profiling.stop_profiler(profiler)

        return True

    # endregion
