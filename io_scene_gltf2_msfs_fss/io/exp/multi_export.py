from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

import os
import re
import json
import traceback
from shutil import copyfile, _samefile
import time


import bpy

from _addons_common import p4, file_info

from .textureLib import msfs_texturelib


from io_scene_gltf2_msfs_fss.io.com.msfs_material_utils import MSFS2024_MaterialUtils
from io_scene_gltf2_msfs_fss.io.com.msfs_data_utils import MSFS2024_DataUtils
from io_scene_gltf2_msfs_fss.io.com import msfs_logs

from io_scene_gltf2_msfs_fss.blender.utils import msfs_object_utils
from io_scene_gltf2_msfs_fss.blender.utils.msfs_constants import DefaultVertexColor, DefaultUV
from io_scene_gltf2_msfs_fss.blender.utils import msfs_context_utils
from io_scene_gltf2_msfs_fss.blender.utils import msfs_mesh_utils

from io_scene_gltf2_msfs_fss.blender import msfs_gizmo, msfs_handlers

from io_scene_gltf2_msfs_fss.io.exp import presets as exp_presets
from io_scene_gltf2_msfs_fss.io.exp import lod_groups as exp_lod_groups

from . import  subprocess_cancel
from .subprocess import SubProcessReport


from .gltf_hooks import Export
from . import export_settings
from .export_settings import MSFS2024_MultiExporterSettings
from . import multi_export_mode
from . import pre_export
from . import xml_export

if TYPE_CHECKING:
    
    from .lod_groups import MultiExporterLODGroup, MultiExporterLOD
    from .presets import MultiExporterPreset

MSFS2024_LOGGER : msfs_logs.Logger

_DUPLICATE_SOURCE_KEY = "msfs_fss_duplicate_source"  # temporary: source object name, copied to its duplicate

# region Operators
class MSFS2024_OT_MultiExportGLTF2(bpy.types.Operator):
    bl_idname = "msfs2024.multi_export_gltf"
    bl_label = "Multi-Export 2024 glTF 2.0"
    bl_cursor_pending = "WAIT"
    bl_options = {"INTERNAL"}

    msfs_export_settings: MSFS2024_MultiExporterSettings

    export_mode: bpy.props.EnumProperty(
        items=multi_export_mode.EXPORT_MODE_ENUM_ITEMS
    )  # type: ignore

    _export_mode_value: multi_export_mode.ExportMode

    called_in_subprocess : bpy.props.BoolProperty(
        default=False,
        description="Is operator launched from a blender subprocess"
    ) # type: ignore

    profiling : bpy.props.BoolProperty(
        default=False,
        description="Internal Only"
    ) # type: ignore

    _start_export_time = 0

    # dict mapping objects and their parents layer collection
    # list of layer collection is ordered by proximity, last parent is the direct parent of object
    _object_layer_collections: dict[bpy.types.Object, list[bpy.types.LayerCollection]]
    # Track layer collections that were forced to be selectable by self.prepare_objects_for_selection()
    _treated_layer_collections: set[bpy.types.LayerCollection]

    def set_export_settings(self, settings: export_settings.MSFS2024_MultiExporterSettings):
        self.msfs_export_settings = settings
        # Also set settings for gltf hooks
        Export.msfs_export_settings = settings

    # region Export
    def _export_blender_under_3_3(
        self,
        context: bpy.types.Context,
        file_path: str,
        settings: MSFS2024_MultiExporterSettings,
    ):
        return bpy.ops.export_scene.gltf(
            filepath=file_path,
            check_existing=True,
            export_format="GLTF_SEPARATE",
            export_copyright=settings.export_copyright,
            export_image_format=("AUTO" if settings.enable_msfs_extension else settings.export_image_format),
            export_texture_dir=(settings.export_texture_dir if not settings.export_keep_originals else ""),
            export_keep_originals=settings.export_keep_originals,
            export_texcoords=settings.export_texcoords,
            export_normals=settings.export_normals,
            export_draco_mesh_compression_enable=settings.export_draco_mesh_compression_enable,
            export_draco_mesh_compression_level=settings.export_draco_mesh_compression_level,
            export_draco_position_quantization=settings.export_draco_position_quantization,
            export_draco_normal_quantization=settings.export_draco_normal_quantization,
            export_draco_texcoord_quantization=settings.export_draco_texcoord_quantization,
            export_draco_color_quantization=settings.export_draco_color_quantization,
            export_draco_generic_quantization=settings.export_draco_generic_quantization,
            export_tangents=settings.export_tangents,
            export_materials=settings.export_materials,
            export_colors=settings.export_colors,
            use_mesh_edges=settings.use_mesh_edges,
            use_mesh_vertices=settings.use_mesh_vertices,
            export_cameras=settings.export_cameras,
            use_selection=settings.use_selection,
            use_visible=settings.use_visible,
            use_renderable=False,
            use_active_collection=False,
            use_active_scene=True,
            export_yup=(True if settings.enable_msfs_extension else settings.export_yup),
            export_apply=settings.export_apply,
            export_animations=settings.export_animations,
            export_frame_range=settings.export_frame_range,
            export_frame_step=settings.export_frame_step,
            export_force_sampling=settings.export_force_sampling,
            export_def_bones=settings.export_def_bones,
            optimize_animation_size=settings.export_optimize_animation_size,
            export_current_frame=settings.export_current_frame,
            export_skins=settings.export_skins,
            export_all_influences=settings.export_all_influences,
            export_morph=settings.export_morph,
            export_morph_normal=settings.export_morph_normal,
            export_morph_tangent=settings.export_morph_tangent,
            export_lights=settings.export_lights,
            will_save_settings=settings.will_save_settings,
            export_extras=(False if settings.enable_msfs_extension else settings.export_extras),
        )

    def _export_blender_3_3(
        self,
        context: bpy.types.Context,
        file_path: str,
        settings: MSFS2024_MultiExporterSettings,
    ):
        return bpy.ops.export_scene.gltf(
            filepath=file_path,
            check_existing=True,
            export_format="GLTF_SEPARATE",
            export_copyright=settings.export_copyright,
            export_image_format=("AUTO" if settings.enable_msfs_extension else settings.export_image_format),
            export_texture_dir=(settings.export_texture_dir if not settings.export_keep_originals else ""),
            export_keep_originals=settings.export_keep_originals,
            export_texcoords=settings.export_texcoords,
            export_normals=settings.export_normals,
            export_draco_mesh_compression_enable=settings.export_draco_mesh_compression_enable,
            export_draco_mesh_compression_level=settings.export_draco_mesh_compression_level,
            export_draco_position_quantization=settings.export_draco_position_quantization,
            export_draco_normal_quantization=settings.export_draco_normal_quantization,
            export_draco_texcoord_quantization=settings.export_draco_texcoord_quantization,
            export_draco_color_quantization=settings.export_draco_color_quantization,
            export_draco_generic_quantization=settings.export_draco_generic_quantization,
            export_tangents=settings.export_tangents,
            export_materials=settings.export_materials,
            export_original_specular=False,
            ## No need to add option for MSFS uses PBR materials with comp texture for Roughness/Metallic/Occlusion
            export_colors=settings.export_colors,
            use_mesh_edges=settings.use_mesh_edges,
            use_mesh_vertices=settings.use_mesh_vertices,
            export_cameras=settings.export_cameras,
            use_selection=settings.use_selection,
            use_visible=settings.use_visible,
            use_renderable=False,
            use_active_collection=False,
            use_active_scene=True,
            export_yup=(True if settings.enable_msfs_extension else settings.export_yup),
            export_apply=settings.export_apply,
            export_animations=settings.export_animations,
            export_frame_range=settings.export_frame_range,
            export_frame_step=settings.export_frame_step,
            export_force_sampling=settings.export_force_sampling,
            export_nla_strips_merged_animation_name=settings.export_nla_strips_merged_animation_name,
            export_def_bones=settings.export_def_bones,
            export_optimize_animation_size=settings.export_optimize_animation_size,
            export_anim_single_armature=settings.export_anim_single_armature,
            export_current_frame=settings.export_current_frame,
            export_skins=settings.export_skins,
            export_all_influences=settings.export_all_influences,
            export_morph=settings.export_morph,
            export_morph_normal=settings.export_morph_normal,
            export_morph_tangent=settings.export_morph_tangent,
            export_lights=settings.export_lights,
            will_save_settings=settings.will_save_settings,
            export_extras=(False if settings.enable_msfs_extension else settings.export_extras),
        )

    def _export_blender_3_6(
        self,
        context: bpy.types.Context,
        file_path: str,
        settings: MSFS2024_MultiExporterSettings,
    ):
        return bpy.ops.export_scene.gltf(
            filepath=file_path,
            check_existing=True,
            export_format="GLTF_SEPARATE",
            export_copyright=settings.export_copyright,
            export_image_format=("AUTO" if settings.enable_msfs_extension else settings.export_image_format),
            export_jpeg_quality=(75 if settings.enable_msfs_extension else settings.export_jpeg_quality),
            export_texture_dir=(settings.export_texture_dir if not settings.export_keep_originals else ""),
            export_keep_originals=settings.export_keep_originals,
            export_texcoords=settings.export_texcoords,
            export_normals=settings.export_normals,
            export_draco_mesh_compression_enable=settings.export_draco_mesh_compression_enable,
            export_draco_mesh_compression_level=settings.export_draco_mesh_compression_level,
            export_draco_position_quantization=settings.export_draco_position_quantization,
            export_draco_normal_quantization=settings.export_draco_normal_quantization,
            export_draco_texcoord_quantization=settings.export_draco_texcoord_quantization,
            export_draco_color_quantization=settings.export_draco_color_quantization,
            export_draco_generic_quantization=settings.export_draco_generic_quantization,
            export_tangents=settings.export_tangents,
            export_materials=settings.export_materials,
            export_original_specular=False,
            ## No need to add option for MSFS uses PBR materials with comp texture for Roughness/Metallic/Occlusion
            export_colors=settings.export_colors,
            export_attributes=settings.export_attributes,
            use_mesh_edges=settings.use_mesh_edges,
            use_mesh_vertices=settings.use_mesh_vertices,
            export_cameras=settings.export_cameras,
            use_selection=settings.use_selection,
            use_visible=settings.use_visible,
            use_renderable=False,
            use_active_collection=False,
            use_active_scene=True,
            export_yup=(True if settings.enable_msfs_extension else settings.export_yup),
            export_apply=settings.export_apply,
            export_animations=settings.export_animations,
            export_frame_range=settings.export_frame_range,
            export_frame_step=settings.export_frame_step,
            export_force_sampling=settings.export_force_sampling,
            export_animation_mode=settings.export_animation_mode,
            export_def_bones=settings.export_def_bones,
            export_optimize_animation_size=settings.export_optimize_animation_size,
            export_optimize_animation_keep_anim_armature=settings.export_optimize_animation_keep_anim_armature,
            export_optimize_animation_keep_anim_object=settings.export_optimize_animation_keep_anim_object,
            export_negative_frame=settings.export_negative_frame,
            export_anim_slide_to_zero=settings.export_anim_slide_to_zero,
            export_reset_pose_bones=settings.export_reset_pose_bones,
            export_bake_animation=settings.export_bake_animation,
            export_anim_single_armature=settings.export_anim_single_armature,
            export_current_frame=settings.export_current_frame,
            export_rest_position_armature=(True if settings.enable_msfs_extension else settings.export_rest_position_armature), # Must be enabled for correct bone and skin export
            export_anim_scene_split_object=settings.export_anim_scene_split_object,
            export_skins=settings.export_skins,
            export_all_influences=settings.export_all_influences,
            export_morph=settings.export_morph,
            export_morph_normal=settings.export_morph_normal,
            export_morph_tangent=settings.export_morph_tangent,
            export_morph_animation=settings.export_morph_animation,
            export_lights=settings.export_lights,
            will_save_settings=settings.will_save_settings,
            export_extras=(False if settings.enable_msfs_extension else settings.export_extras),
        )

    def _export_blender_4_2(
        self,
        context: bpy.types.Context,
        file_path: str,
        settings: MSFS2024_MultiExporterSettings,
    ):
        return bpy.ops.export_scene.gltf(
            filepath=file_path,
            check_existing=True,
            export_format="GLTF_SEPARATE",
            export_copyright=settings.export_copyright,
            export_image_format=("AUTO" if settings.enable_msfs_extension else settings.export_image_format),
            export_jpeg_quality=(75 if settings.enable_msfs_extension else settings.export_jpeg_quality),
            export_texture_dir=(settings.export_texture_dir if not settings.export_keep_originals else ""),
            export_keep_originals=settings.export_keep_originals,
            export_texcoords=settings.export_texcoords,
            export_normals=settings.export_normals,
            export_draco_mesh_compression_enable=settings.export_draco_mesh_compression_enable,
            export_draco_mesh_compression_level=settings.export_draco_mesh_compression_level,
            export_draco_position_quantization=settings.export_draco_position_quantization,
            export_draco_normal_quantization=settings.export_draco_normal_quantization,
            export_draco_texcoord_quantization=settings.export_draco_texcoord_quantization,
            export_draco_color_quantization=settings.export_draco_color_quantization,
            export_draco_generic_quantization=settings.export_draco_generic_quantization,
            export_tangents=settings.export_tangents,
            export_materials=settings.export_materials,
            ## No need to add option for that MSFS uses PBR materials with comp texture for Roughness/Metallic/Occlusion
            export_original_specular=False,
            export_attributes=settings.export_attributes,
            use_mesh_edges=settings.use_mesh_edges,
            use_mesh_vertices=settings.use_mesh_vertices,
            export_cameras=settings.export_cameras,
            use_selection=settings.use_selection,
            use_visible=settings.use_visible,
            use_renderable=False,
            use_active_collection=False,
            use_active_scene=True,
            export_yup=(True if settings.enable_msfs_extension else settings.export_yup),
            export_apply=settings.export_apply,
            export_animations=settings.export_animations,
            export_frame_range=settings.export_frame_range,
            export_frame_step=settings.export_frame_step,
            export_force_sampling=settings.export_force_sampling,
            export_animation_mode=settings.export_animation_mode,
            export_merge_animation=settings.export_merge_animation,
            export_def_bones=settings.export_def_bones,
            export_optimize_animation_size=settings.export_optimize_animation_size,
            export_optimize_animation_keep_anim_armature=settings.export_optimize_animation_keep_anim_armature,
            export_optimize_animation_keep_anim_object=settings.export_optimize_animation_keep_anim_object,
            export_negative_frame=settings.export_negative_frame,
            export_anim_slide_to_zero=settings.export_anim_slide_to_zero,
            export_reset_pose_bones=settings.export_reset_pose_bones,
            export_bake_animation=settings.export_bake_animation,
            export_anim_single_armature=settings.export_anim_single_armature,
            export_current_frame=settings.export_current_frame,
            export_rest_position_armature=(True if settings.enable_msfs_extension else settings.export_rest_position_armature), # Must be enabled for correct bone and skin export
            export_anim_scene_split_object=settings.export_anim_scene_split_object,
            export_skins=settings.export_skins,
            export_all_influences=(False if settings.enable_msfs_extension else settings.export_all_influences),
            export_morph=settings.export_morph,
            export_morph_normal=settings.export_morph_normal,
            export_morph_tangent=settings.export_morph_tangent,
            export_morph_animation=settings.export_morph_animation,
            export_lights=settings.export_lights,
            will_save_settings=settings.will_save_settings,
            export_extras=(False if settings.enable_msfs_extension else settings.export_extras),
            export_gn_mesh=(False if settings.enable_msfs_extension else settings.export_gn_mesh),
            export_gpu_instances=(False if settings.enable_msfs_extension else settings.export_gpu_instances),
            export_hierarchy_flatten_objs=(
                False if settings.enable_msfs_extension else settings.export_hierarchy_flatten_objs),
            export_hierarchy_full_collections=(
                False if settings.enable_msfs_extension else settings.export_hierarchy_full_collections),
            export_vertex_color=settings.export_vertex_color,
            export_all_vertex_colors=settings.export_all_vertex_colors,
            export_active_vertex_color_when_no_material=settings.export_active_vertex_color_when_no_material,
            export_image_add_webp=(False if settings.enable_msfs_extension else settings.export_image_add_webp),
            export_image_webp_fallback=(
                False if settings.enable_msfs_extension else settings.export_image_webp_fallback),
            export_unused_images=(False if settings.enable_msfs_extension else settings.export_unused_images),
            export_unused_textures=(False if settings.enable_msfs_extension else settings.export_unused_textures),
            export_try_sparse_sk=(False if settings.enable_msfs_extension else settings.export_try_sparse_sk),
            export_try_omit_sparse_sk=(False if settings.enable_msfs_extension else settings.export_try_omit_sparse_sk),
            export_armature_object_remove=settings.export_armature_object_remove,
            export_influence_nb=settings.export_influence_nb,
            export_import_convert_lighting_mode=(
                "SPEC" if settings.enable_msfs_extension else settings.export_import_convert_lighting_mode),
            export_optimize_disable_viewport=settings.export_optimize_disable_viewport
        )

    def _export(self, context: bpy.types.Context, file_path: str):

        # Safely execute export so we can clean duplicated object in case of error
        try:
            gltf_base_name = os.path.basename(file_path)
            if bpy.app.version < (3, 3, 0):
                gltf = self._export_blender_under_3_3(
                    context,
                    file_path,
                    self.msfs_export_settings
                )
            elif bpy.app.version < (3, 6, 0):
                gltf = self._export_blender_3_3(
                    context, 
                    file_path, 
                    self.msfs_export_settings
                )
            elif bpy.app.version < (4, 2, 0):
                gltf = self._export_blender_3_6(
                    context,
                    file_path,
                    self.msfs_export_settings
                )
            else: # 4.2+
                gltf = self._export_blender_4_2(
                    context,
                    file_path,
                    self.msfs_export_settings
                )

            if gltf is None:
                MSFS2024_LOGGER.error(
                    message=f"'{gltf_base_name}' : Export Failed.", 
                    details=f"Could not export glTF:\n'{file_path}'"
                )
            else:
                current_time = time.perf_counter()
                export_time = current_time - self._start_export_time
                self._start_export_time = current_time

                MSFS2024_LOGGER.info(message=f"'{gltf_base_name}' : Export Done.",
                                     details=(f"Export took {export_time:.3f} seconds.\n"
                                         f"Gltf path:\n{file_path}"))

        except :
            MSFS2024_LOGGER.error(
                message=f"'{gltf_base_name}' : Error During Gltf export.", 
                details=(f"Error while exporting {gltf_base_name}.\n"
                         f"Gltf path:\n{file_path}\n"+
                         f"Python Traceback:\n"+
                traceback.format_exc())
            )
        base_name = os.path.basename(file_path)
        # Check if the gltf is not empty
        json_file_object = None
        try:
            with open(file_path, 'r', encoding="utf-8") as file:
                json_file_object = json.load(file)
        except IOError:

            MSFS2024_LOGGER.error(
                message=f"'{base_name}' : Could not be opened.",
                details=f"Access denied:\n{file_path}"
            )
            return

        if json_file_object is None:
            return

        gltf_nodes = json_file_object.get("nodes")        
        if gltf_nodes is None or len(gltf_nodes) == 0:
            MSFS2024_LOGGER.error(
                message=f"'{base_name}' : Seems to be empty.",
                details=f"Empty Gltf:\n{file_path}",
            )

    # endregion

    # region Common
    @staticmethod
    def _construct_object_layer_collections_dict(
        layer_collection: None | bpy.types.LayerCollection = None,
        object_layer_collections: None | dict[bpy.types.Object, list[bpy.types.LayerCollection]]= None,
        parents: None | list[bpy.types.LayerCollection] = None,
    ) -> dict[bpy.types.Object, list[bpy.types.LayerCollection]]:
        """
        Create a dict mapping each object to the list of LayerCollections it belongs to.

        The list represents the LayerCollection parent chain for the object and is
        ordered by proximity: the last element is the direct LayerCollection containing
        the object, while preceding elements are its parent LayerCollections.
        """
        if layer_collection is None:
            # Get layer_collection from bpy.data to prevent invalid memory adress
            _scene = bpy.data.scenes[bpy.context.scene.name]
            _view_layer = _scene.view_layers[bpy.context.view_layer.name]
            layer_collection = _view_layer.layer_collection
        if object_layer_collections is None:
            object_layer_collections = {}
        if parents is None:
            parents = []

        parents.append(layer_collection)
        for obj in layer_collection.collection.objects:
            if not object_layer_collections.get(obj):
                object_layer_collections[obj] = parents
            else:
                object_layer_collections[obj] += parents

        for layer in layer_collection.children:
            MSFS2024_OT_MultiExportGLTF2._construct_object_layer_collections_dict(
                layer, object_layer_collections, parents.copy()
            )

        return object_layer_collections

    def prepare_objects_for_selection(self, objects: list[bpy.types.Object]):
        """Force objects to be selectable by export process.
        Set object 'hide_select' to False
        Set object collection 'hide_select' to False (parent collection and all parents of parent collection)
        Set objects view_layer 'exclude' to False (only direct parent view_layer is necessary).

        Objects with 'hide_select' enabled can't be selected or unselected 
        via code.
        """
        reveal_hidden_objects = not self.msfs_export_settings.use_visible

        for obj in objects:
            layer_collections = self._object_layer_collections.get(obj, [])
            for layer in layer_collections:
                if layer in self._treated_layer_collections:
                    # Prevent unhidding layer collection multiple times
                    # This can be very very slow on big scenes
                    continue
                layer.exclude = False 
                layer.collection.hide_select = False
                if reveal_hidden_objects:
                    layer.hide_viewport = False
                    layer.collection.hide_viewport = False

                self._treated_layer_collections.add(layer)

            obj.hide_select = False

            if reveal_hidden_objects:
                obj.hide_set(False)
                obj.hide_viewport= False

    def get_clean_object_refs(
        self, objects: Iterable[bpy.types.Object]
    ) -> list[bpy.types.Object]:
        """
        IMPORTANT:
        Re-resolve objects from bpy.data to ensure stable RNA references.

        Objects obtained from context-dependent sources (e.g. Collection.all_objects)
        may become invalid if collections are modified, view layers change, or undo/redo
        occurs. Always re-fetch objects from bpy.data before performing selection or
        other mutating operations.
        """
        _objects = []
        for obj in objects:
            data_obj = bpy.data.objects.get(obj.name, None)
            if data_obj:
                _objects.append(data_obj)
        return _objects

    def force_objects_selection(
        self, 
        objects: Iterable[bpy.types.Object], 
        select: bool = True,
        check_context: bool = False
    ):
        """
        Set object select state even if they are hidden are excluded in a layer collection.
        Can be very slow if done on a lot of objects, try to minimize processed objects count.
        """
        to_select = self.get_clean_object_refs(objects)
        self.prepare_objects_for_selection(to_select)
        for obj in to_select:
            try:
                obj.select_set(select)
            except RuntimeError:
                # not in view layer
                pass
        if not check_context:
            return
        # Make sure context.selected_objects does not contain additional objects.
        # context.selected_objects may contain objects that belong to excluded collections.
        # Blender keeps objects marked as selected even if their collection is excluded
        # from the view layer.
        invalid_objects = []
        for obj in bpy.context.selected_objects:
            if obj in objects:
                continue
            invalid_objects.append(obj)
        self.force_objects_selection(objects=invalid_objects, select=False, check_context=False)

    def select_objects(
        self, 
        context: bpy.types.Context, 
        blender_objects: list[bpy.types.Object], 
        recursive: bool = False
    ):
        for blender_object in blender_objects:
            self.select_object(context, blender_object, recursive)

    def select_object(
        self, 
        context: bpy.types.Context, 
        blender_object: bpy.types.Object, 
        recursive: bool = True
    ):
        if blender_object not in list(context.view_layer.objects):
            return

        blender_object.select_set(True)
        context.selected_objects.append(blender_object)

        if not recursive:
            return

        for child in blender_object.children:
            self.select_object(context, child, recursive)

    def set_active(self, context: bpy.types.Context, blender_object: bpy.types.Object):
        try:
            context.view_layer.objects.active = blender_object
            return True
        except RuntimeError:
            # Not in View layer
            return False

    def set_first_valid_object_as_active(
        self, 
        context: bpy.types.Context, 
        blender_objects: list[bpy.types.Object]
    ):
        for obj in blender_objects:
            if self.set_active(context, obj):
                return

    def clear_selection(self, context: bpy.types.Context):
        for blender_object in context.scene.objects:
            blender_object.select_set(False)

    def _force_duplicated_refresh(
        self, 
        context: bpy.types.Context, 
        duplicated_objects: list[bpy.types.Object]
    ):
        """
        --- Blender bug workaround (affects 3.6, 4.0, and 4.1) ---
        In these versions, modifying a duplicated object can unexpectedly affect
        the original object — even when the mesh data is not linked.

        In our case, this caused UV corruption when calling order_uv_layers().
        We force a data refresh by toggling EDIT / OBJECT mode to rebuild mesh data.
        """

        if not (3, 6, 0) <= bpy.app.version <= (4, 1, 1):
            return
        # Active object should be editable
        editable_active_object = None
        for obj in duplicated_objects:
            if obj and hasattr(obj.data, "is_editmode"):
                editable_active_object = obj
                self.set_active(context, obj)
                break

        if editable_active_object:

            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.object.mode_set(mode="OBJECT")

    def duplicate_selected_objects(self, context: bpy.types.Context):
        """Duplicate selected objects.
        Do not duplicate hidden objects.
        Assign a msfs_original name to duplicated object, used to retrieve original source object.
        Duplicates keep the original actions.

        Returns:
            Duplicated Objects
        """
        source_objects = context.selected_objects
        # Unified add-on: the duplicate operator skips objects saved in Pose or Edit mode (still selected), which
        # shifted the pairing below by one: duplicates got the original name of another object
        view_layer = context.view_layer
        active = view_layer.objects.active
        for obj in source_objects:
            if obj.mode != "OBJECT":
                view_layer.objects.active = obj
                bpy.ops.object.mode_set(mode="OBJECT")
        view_layer.objects.active = active
        # Pair each duplicate with its source by a tag the duplicate operator copies, not by list order
        for obj in source_objects:
            obj[_DUPLICATE_SOURCE_KEY] = obj.name
        # Unified add-on: duplicates use the source objects' actions in NLA strips as well as the active action.
        # Blender would copy the actions; reassigning only the active one left a copy with the same animation
        # twice when the active action is also in an NLA track
        edit_prefs = context.preferences.edit
        duplicate_action = edit_prefs.use_duplicate_action
        edit_prefs.use_duplicate_action = False
        try:
            bpy.ops.object.duplicate(linked=False)
        finally:
            edit_prefs.use_duplicate_action = duplicate_action
            for obj in source_objects:
                obj.pop(_DUPLICATE_SOURCE_KEY, None)
        duplicated_objects = context.selected_objects
        pairs = []
        for duplicate in duplicated_objects:
            pairs.append((bpy.data.objects[duplicate.pop(_DUPLICATE_SOURCE_KEY)], duplicate))
        missing = set(o.name for o in source_objects) - set(source.name for source, _duplicate in pairs)
        if missing:
            raise RuntimeError(f"Objects could not be duplicated for export: {sorted(missing)}")
        # Store original name in order reassign it later in process
        # cf gather_node_hook in msfs_export.py
        # cf gather_mesh_hook in msfs_export.py
        for source, duplicate in pairs:
            MSFS2024_DataUtils.set_msfs_original_name(duplicate, source.name)
            if source.data:
                MSFS2024_DataUtils.set_msfs_original_name(
                    duplicate.data, source.data.name
                )
        self._force_duplicated_refresh(context, duplicated_objects)
        return duplicated_objects

    def _unify_uv_layers(self, obj: bpy.types.Object):
        """Renames  UV layers to a consistent sequential naming scheme, UV1 and UV2,
        based on their order in the mesh UV map list.

        Also remove unecessary uv layers.
        """

        # Rename uv_layers first to prevent name conflict and numbered suffixes ".001" added to name
        uv_layers = obj.data.uv_layers
        for uv_layer in uv_layers:
            uv_layer.name = "temp"

        layer_count = len(uv_layers)
        if layer_count > 0:
            uv_layers.values()[0].name = DefaultUV.UV1_NAME
        if layer_count > 1:
            uv_layers.values()[1].name = DefaultUV.UV2_NAME

        # Remove other uv layers
        if layer_count > 2:
            # Remove from last uv_layers
            for i in range(layer_count - 1, 1, -1):
                to_delete = uv_layers.values()[i]
                uv_layers.remove(to_delete)

    def _convert_to_unique_mesh(
        self, 
        context: bpy.types.Context, 
        objects: list[bpy.types.Object]
    ):
        self.select_objects(context, objects, recursive=False)
        context.view_layer.objects.active = objects[0]
        # Remove instances to prevent issues
        bpy.ops.object.make_single_user(
            object=True,
            obdata=True,
            material=False,
            animation=False,
            obdata_animation=False,
        )
        bpy.ops.object.convert(target="MESH", keep_original=False)

    def _prepare_for_merge(self, context: bpy.types.Context, obj:bpy.types.Object):
        """
        Select object and prepare it for join operator.
        Object must be of type "MESH".
        """
        self.select_object(context, obj, recursive=False)

        # Rename all color attribs first to prevent name conflict with unused vertex color attributes
        # Must be done before get_active_color_attribute() to prevent issues
        for color_attrib in obj.data.color_attributes:
            color_attrib.name = "temp"

        # Make sure vertex color have same name and type
        v_color = msfs_mesh_utils.get_active_color_attribute(
            obj.data
        )
        if v_color:
            # Color Attribute name, domain and type must be identitical on all objects for join operator
            v_color.name = DefaultVertexColor.NAME

            if not msfs_mesh_utils.complies_with_default_vertex_color(v_color):
                msfs_mesh_utils.convert_active_color_attribute(
                    obj, 
                    DefaultVertexColor.DOMAIN, 
                    DefaultVertexColor.TYPE
                )

        self._unify_uv_layers(obj)
        # Assign an empty material slots to prevents invalid
        # material assignment on join
        if not obj.material_slots:
            obj.data.materials.append(None)

    def merge_objects(
        self, 
        context: bpy.types.Context, 
        duplicated_objects: list[bpy.types.Object]
    ) -> list[bpy.types.Object]:
        """Merge meshes and reparent non meshes object (lights, collisions ...)
        if they lost their parent during join process.
        """
        # Remove useless root dummies resulting of collection instances
        for obj in duplicated_objects.copy():
            if obj.type == "EMPTY" and not obj.children:
                duplicated_objects.remove(obj)
                bpy.data.objects.remove(obj)

        self.clear_selection(context)
        # Try to convert all to mesh, except gizmo objects
        to_convert = []
        for obj in duplicated_objects:
            if msfs_gizmo.is_valid_gizmo_obj(obj):
                continue
            to_convert.append(obj)

        # Apply modifiers and convert to mesh if possible
        self._convert_to_unique_mesh(context, to_convert)

        duplicated_objects_to_merge = []
        # Save objects that are children of a valid type
        # They will need to be reparented after join
        objects_to_reparent = []

        for obj in duplicated_objects:
            if obj.type == "MESH":
                duplicated_objects_to_merge.append(obj)
            elif obj.parent and obj.parent.type in "MESH":
                objects_to_reparent.append(obj)

        if len(duplicated_objects_to_merge) <= 1:
            return None

        # Unparent before join
        for obj in objects_to_reparent:
            msfs_object_utils.set_parent_keep_transform(obj, None)

        # Select objects ready to merge
        self.clear_selection(context)
        root = None

        for obj in duplicated_objects_to_merge:

            self._prepare_for_merge(context, obj)
            # Find first root
            if (root is None and 
                not obj.parent in duplicated_objects_to_merge):
                root = obj
        # Merge
        if not root:
            root = duplicated_objects_to_merge[0]

        context.view_layer.objects.active = root

        # Apply rotation and scale to prevent issues with shaders (for example, detail color map uvs can depends on node scale)
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        bpy.ops.object.join()

        merged_object = context.active_object
        if merged_object.data is not None:
            merged_object.data.name = merged_object.name

        # Reparent objects that lost their parent after join ope
        for obj in objects_to_reparent:
            if not obj.parent:
                msfs_object_utils.set_parent_keep_transform(obj, merged_object)

        return merged_object

    def checkout_gltf_path(
        self, 
        context: bpy.types.Context, 
        gltf_path: str, 
        bin_path: str
    ):
        if not p4.use_p4():
            return
        p4_output = p4.P4LogOutput()
        if not p4.p4_edit(gltf_path,p4_output=p4_output):
            gltf_base_name = os.path.basename(gltf_path)
            MSFS2024_LOGGER.error(
                message=f"'{gltf_base_name}' : Could not be opened for edit.",
                details=f"P4 error:\n{str(p4_output)}",
            )
            return

        p4_output = p4.P4LogOutput()
        if not p4.p4_edit(bin_path,p4_output=p4_output):
            bin_base_name = os.path.basename(bin_path)
            MSFS2024_LOGGER.error(
                message=f"'{bin_base_name}' : Could not be opened for edit.",
                details=f"P4 error:\n{str(p4_output)}",
            )

    def is_gltf_read_only(self, gltf_path: str, bin_path: str) -> bool:
        """Check if gltf and bin files are set to read only.

        Returns:
            True if gltf and/or bin file are set to read-o, False otherwise.
        """
        gltf_read_only = file_info.is_read_only(gltf_path)
        bin_read_only = file_info.is_read_only(bin_path)

        if gltf_read_only:
            gltf_base_name = os.path.basename(gltf_path)
            MSFS2024_LOGGER.error(
                message=f"'{gltf_base_name}' : File is read-only.",
                details=(
                    "Disable the read-only attribute to make the file writable:\n"
                    + gltf_path
                ),
            )

        if bin_read_only:
            bin_base_name = os.path.basename(bin_path)
            MSFS2024_LOGGER.error(
                message=f"'{bin_base_name}' : File is read-only.",
                details=(
                    "Disable the read-only attribute to make the file writable:\n"
                    + bin_path
                ),
            )
        if gltf_read_only or bin_read_only:
            return True

        return False

    def get_export_path(self, path:str, gltf_name:str):

        path = path.strip()
        if path == "":
            MSFS2024_LOGGER.error(
                message=f"'{gltf_name}' : No export folder set.",
                details=(f"No export folder assigned for '{gltf_name}' in the exporter list.\n"
                         "Please assign one in the exporter list.")
            )
            return None
        path = bpy.path.abspath(path)
        path = os.path.realpath(path)
        if not os.path.exists(path):
            MSFS2024_LOGGER.error(
                message=f"'{gltf_name}' : Export folder doesn't exist.",
                details=f"Folder doesn't exists on disk:\n{path}"
            )
            return None
        return path

    def check_for_cancel_request(self):
        """
        Check for cancel request and exit Blender if requested.
        This must be called at safe points where it is safe to exit Blender
        (i.e., not during glTF writing).

        Call this at strategic moments, just before or after a long operation
        that cannot be cancelled.
        """
        if not self.called_in_subprocess:
            return

        if subprocess_cancel.is_cancel_requested():
            MSFS2024_LOGGER.warning(
                message="Export was Cancelled",
                details="",
            )
        subprocess_cancel.process_cancel_request()

    def realize_collection_instances(self, objects:list[bpy.types.Object]):
        """
        Convert empties instantiating collections to real objects.
        Update provided objects list with new objects.
        """
        depsgraph = bpy.context.evaluated_depsgraph_get()
        new_objects = []
        for obj in objects:
            if obj.type == "EMPTY" and obj.instance_type == 'COLLECTION':
                new_objects.extend(msfs_object_utils.realize_instance_and_reparent(obj, depsgraph))

        objects.extend(new_objects)

    def order_uv_layers(self, objects: list[bpy.types.Object]):
        """Make sure active render uv layer 'UV1' is first in uv layers list
        and uv_layer 'UV2' is second in uv layers list.

        WHY? gltf importer set first gltf uv channels as active_render uv.
        
        Also usefull to unify layers order to prepare for other 
        processes like merge_objects().

        If there are multiple uv layers but no uv layer named 'UV2' then
        the first uv layer found (that is not the active uv layer) will be considered 'UV2'.

        Do not rename uv layer here, it can cause issues with modifiers referencing UVs by name.
        """
        for obj in objects:

            if not obj.type == "MESH":
                continue

            mesh: bpy.types.Mesh = obj.data
            uv_layers = mesh.uv_layers
            if not uv_layers:
                continue

            if len(uv_layers) == 1:
                continue

            # Active render layer corresponds to the uv index used by shaders
            active_render_index = 0
            for i, uv_layer in enumerate(uv_layers):
                if uv_layer.active_render:
                    active_render_index = i
                    break

            # Make sure that active uv layer is first in the list
            if active_render_index > 0:
                msfs_mesh_utils.swap_uv_layers(mesh, active_render_index, 0)

            # Check if there is a UV2 layer
            uv2_layer_index = None
            for i, uv_layer in enumerate(uv_layers[1:], start=1):
                if uv_layer.name == DefaultUV.UV2_NAME:
                    uv2_layer_index = i
                    break

            if uv2_layer_index is None:
                continue

            if uv2_layer_index != 1:
                # Move uv2 layer at second place in uv_layers
                msfs_mesh_utils.swap_uv_layers(mesh, uv2_layer_index, 1)

    def prepare_objects_for_export(
        self,
        context: bpy.types.Context,
        objects: list[bpy.types.Object]
    ) -> list[bpy.types.Object]:
        """
        Set objects visibility and selection state.
        Duplicate objects and their data in order to modify them.
        Duplicated objects will be cleaned later during process.
        
        Prepare skinned objects.

        Provided objects list can be modified during process.

        Args:
            context: current Blender context.
            select_function: Function to launch for objects selection.
            select_args: Args for selection function.

        Returns:
            List of duplicated objects.
        """
        self.clear_selection(context)

        self.force_objects_selection(objects=objects, select=True, check_context=True)
        objects = context.selected_objects

        # Set armature to pose mode in order to prevent gltf2 export crash
        for obj in objects:
            if obj.type == "ARMATURE":
                obj.data.pose_position = "POSE"

        if not self.msfs_export_settings.enable_msfs_extension:
            # Skip rest of process if user disabled msfs_extension
            return objects

        # Duplicate objects if operator is not launched from a subprocess
        if not self.called_in_subprocess:
            objects = self.duplicate_selected_objects(context)

        # Convert collections instances
        self.realize_collection_instances(objects)

        self.order_uv_layers(objects)

        MSFS2024_MaterialUtils.set_objects_materials_for_export(
            objects,
            duplicate_materials=(not self.called_in_subprocess)
        )

        if self.msfs_export_settings.merge_nodes:
            merged_object = self.merge_objects(context,objects)
            if merged_object:
                objects = MSFS2024_DataUtils.filter_deleted(objects)

        self.select_objects(context, objects, recursive=False)

        self.set_first_valid_object_as_active(context, objects)

        return objects

    # endregion

    # region LODs
    def _get_autolod_filename(self, lod_name:str):
        """
        Get lod_name that ends with _LOD0
        """

        pattern = re.compile(r"_lod[0-9]+$",re.IGNORECASE)
        new_name = lod_name
        if pattern.search(new_name):
            new_name = pattern.sub("_LOD0", new_name)
        else:
            new_name += "_LOD0"
        return new_name

    def _export_lod(
        self,
        context: bpy.types.Context,
        export_folder_path: str,
        lod: MultiExporterLOD,
        lod_group: MultiExporterLODGroup,
    ) -> tuple[bool, str]:
        if not export_folder_path:
            return False, ""

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # Setup export settings to send to KHRONOS exporter
        self.set_export_settings(
            export_settings.get_settings_preset_by_name(
                context.scene, lod_group.settings_preset
            )
        )

        objects = list(lod.get_lod_objects(self._export_mode_value))
        _ = self.prepare_objects_for_export(
            context,
            objects
        )

        self.check_for_cancel_request()

        if len(context.selected_objects) < 1:
            MSFS2024_LOGGER.error(
                message=f"'{lod.name}' : No object to export!"
            )
            return False, ""
        # Remove .001 suffix
        lod_name = os.path.splitext(lod.file_name)[0]
        if lod_group.autogenerate_lods and not lod_name.endswith("_LOD0"):
            lod_name = self._get_autolod_filename(lod_name)

        gltf_path = bpy.path.ensure_ext(
            os.path.join(
                export_folder_path,
                lod_name
            ),
            ".gltf"
        )

        bin_path = bpy.path.ensure_ext(
            os.path.join(
                export_folder_path,
                lod_name
            ),
            ".bin"
        )

        self.checkout_gltf_path(context, gltf_path, bin_path)

        gltf_read_only = self.is_gltf_read_only(gltf_path, bin_path)

        if gltf_read_only :
            return False, "" 

        clean_lod_name = bpy.path.clean_name(lod_name)
        SubProcessReport.report_progress_text(f"Exporting {clean_lod_name}")

        self.check_for_cancel_request()

        self._export(context, gltf_path)

        self.check_for_cancel_request()

        return True, gltf_path

    def _export_lod_group(
        self, 
        context: bpy.types.Context, 
        lod_group: MultiExporterLODGroup
    )->list[str]:
        exported_paths = []
        # Export glTF
        export_folder_path = self.get_export_path(lod_group.folder_path, lod_group.name)
        if not export_folder_path:
            return exported_paths

        for lod in lod_group.lods:

            self.check_for_cancel_request()

            if not lod.enabled:
                continue

            exported, exported_path = self._export_lod(
                context,
                export_folder_path,
                lod,
                lod_group
            )
            if exported:
                exported_paths.append(exported_path)

            if lod_group.autogenerate_lods:
                # Only export first enabled lod when autogenerate lods is enabled
                break
        # Generate XML if needed
        if exported_paths and lod_group.generate_xml:

            xml_export.generate_xml(lod_group, export_folder_path)

        return exported_paths

    def _is_lod_group_enabled(self, lod_group: MultiExporterLODGroup):
        if lod_group.enabled:
            return True
        return lod_group.enabled_lod_count() > 0

    def export_lod_groups(self, context: bpy.types.Context):
        scene_lod_groups = exp_lod_groups.get_scene_lod_groups(context.scene)

        if not self.called_in_subprocess:
            original_data_blocks = MSFS2024_DataUtils.get_all_data_blocks()
            save_context = msfs_context_utils.save_context()

        self.check_for_cancel_request()

        enabled_lod_groups = []
        for lod_group in scene_lod_groups:
            if self._is_lod_group_enabled(lod_group):
                enabled_lod_groups.append(lod_group)

        enabled_lod_groups_count = len(enabled_lod_groups)
        if enabled_lod_groups_count < 1:
            MSFS2024_LOGGER.error(
                message="Nothing to export!",
                details="No item checked in the exporter list. Please check one to export."
            )
            return []

        exported_paths = []
        progress = 0
        progress_step = 100 / (enabled_lod_groups_count + 1)

        for lod_group in enabled_lod_groups:

            self.check_for_cancel_request()

            progress += progress_step
            SubProcessReport.report_progress(progress)
            exported_lod_group_paths = self._export_lod_group(context, lod_group)
            exported_paths.extend(exported_lod_group_paths)
            if not self.called_in_subprocess:
                # Clean process orphan data
                new_data_blocks = MSFS2024_DataUtils.get_all_data_blocks()
                # Super Important to purge data after each export in order to prevent slow gltf export
                MSFS2024_DataUtils.purge_new_data(original_data_blocks, new_data_blocks)

        if not self.called_in_subprocess:
            msfs_context_utils.restore_context(save_context)

        return exported_paths

    # endregion

    # region Presets

    def _export_preset(
        self,
        context: bpy.types.Context,
        preset: MultiExporterPreset,
        group_name: str = "",
    ):
        export_folder_path = self.get_export_path(
            preset.folder_path, preset.preset_name
        )
        if not export_folder_path:
            return False, ""

        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        # Setup export settings to send to KHRONOS exporter
        self.set_export_settings(
            export_settings.get_settings_preset_by_name(
                context.scene, preset.settings_preset
            )
        )

        preset_objects = list(preset.get_preset_objects())
        _ = self.prepare_objects_for_export(
            context,
            objects=preset_objects,
        )

        self.check_for_cancel_request()

        if len(context.selected_objects) < 1:
            MSFS2024_LOGGER.error(
                message=f"'{preset.preset_name}' : No object to export!"
            )
            return False, ""

        export_path = os.path.join(export_folder_path, preset.preset_name)

        gltf_path = bpy.path.ensure_ext(export_path, ".gltf")

        bin_path = bpy.path.ensure_ext(export_path, ".bin")

        self.checkout_gltf_path(context, gltf_path, bin_path)

        gltf_read_only = self.is_gltf_read_only(gltf_path, bin_path)

        if gltf_read_only :
            return False, "" 

        clean_preset_name = bpy.path.clean_name(preset.preset_name)
        msg = f"Exporting {clean_preset_name}"
        if group_name:
            msg = f"Exporting {group_name} : {clean_preset_name}"
        SubProcessReport.report_progress_text(msg)

        self.check_for_cancel_request()

        self._export(context, gltf_path)

        self.check_for_cancel_request()
        return True, gltf_path

    def export_presets(self, context: bpy.types.Context)->list[str]:
        scene_presets = exp_presets.get_scene_exporter_presets(context.scene)
        exported_paths = []
        if not self.called_in_subprocess:
            original_data_blocks = MSFS2024_DataUtils.get_all_data_blocks()
            save_context = msfs_context_utils.save_context()

        self.check_for_cancel_request()

        enabled_presets: list[MultiExporterPreset] = []
        for preset in scene_presets:
            if preset.enabled:
                enabled_presets.append(preset)
        enabled_presets_count = len(enabled_presets)
        if enabled_presets_count < 1 : 
            MSFS2024_LOGGER.error(
                message="Nothing to export!",
                details="No item checked in the exporter list. Please check one to export."
                )
            return []

        progress = 0
        progress_step = 100 / (enabled_presets_count + 1)

        # Group preset by groups
        preset_groups = {}
        scene_preset_groups = exp_presets.get_scene_exporter_preset_groups(context.scene)
        for preset in enabled_presets:
            group_name = ""
            group = scene_preset_groups.get(
                preset.group_id, None
            )
            if group:
                group_name = group.group_name
            if not preset_groups.get(group_name, None):
                preset_groups[group_name] = []
            preset_groups[group_name].append(preset)

        # Export group of presets in alphabetical order
        for group_name, presets in sorted(preset_groups.items()):
            presets.sort(key=lambda p: p.preset_name)
            for preset in presets:

                self.check_for_cancel_request()

                progress += progress_step
                SubProcessReport.report_progress(progress)
                exported, exportpath = self._export_preset(context, preset, group_name)
                if exported:
                    exported_paths.append(exportpath)
                # Clean process orphan data
                if not self.called_in_subprocess:
                    new_data_blocks = MSFS2024_DataUtils.get_all_data_blocks()
                    # Super Important to purge data after each export in order to prevent slow gltf export
                    MSFS2024_DataUtils.purge_new_data(original_data_blocks, new_data_blocks)

        if not self.called_in_subprocess:
            msfs_context_utils.restore_context(save_context)

        return exported_paths

    # endregion

    # region Textures
    def _export_gltf_texture(
        self, context: bpy.types.Context, gltf_path: str, texture_dir: str
    ):
        if not os.path.exists(gltf_path):
            return

        gltf_dir_path = os.path.dirname(gltf_path)

        if not os.path.isabs(texture_dir):
            texture_dir = os.path.join(gltf_dir_path, texture_dir)
            texture_dir = os.path.abspath(texture_dir)

        if not os.path.exists(texture_dir):
            try:
                os.mkdir(texture_dir)
            except OSError:
                MSFS2024_LOGGER.error(
                    message=f"Texture folder could not be created.",
                    details=f"Couldn't create texture folder:\n{texture_dir}"
                )
                return

        json_file_object = None
        try:
            with open(gltf_path, 'r', encoding="utf-8") as file:
                json_file_object = json.load(file)
        except IOError:
            gltf_base_name = os.path.basename(gltf_path)
            MSFS2024_LOGGER.error(
                message=f"'{gltf_base_name}' : Could not be opened. Textures will not be written.",
                details=("Textures will not be written.\n"
                "File access denied:\n"
                f"{gltf_path}"
                )
            )

            return

        if json_file_object is None:
            return

        gltf_images = json_file_object.get("images")
        if gltf_images is None:
            return

        for gltf_image in gltf_images:
            image_path = gltf_image.get("uri")
            if image_path is None:
                continue

            image_path = os.path.join(gltf_dir_path, image_path)
            image_path = image_path.replace('/', '\\')
            image_path = os.path.abspath(image_path)

            # Check if there is a whitespace and replace it in path
            if '%20' in image_path:
                image_path = image_path.replace('%20', ' ')

            if not os.path.exists(image_path):
                image_name = gltf_image.get("name", image_path)
                MSFS2024_LOGGER.error(message=f"'{image_name}' : Does not exist.",
                                      details=f"File '{image_path}' does not exist.")
                continue

            image_name = os.path.basename(image_path)

            new_image_path = os.path.join(texture_dir, image_name)
            new_image_path = os.path.abspath(new_image_path)

            # Change texture path in gltf
            if len(os.path.commonprefix([new_image_path, gltf_path])) != 0:
                gltf_image['uri'] = os.path.relpath(path=new_image_path, start=gltf_dir_path)

            # Copy image if the image not already exists in the folder
            if _samefile(image_path, new_image_path):
                continue
            if p4.use_p4():
                p4_output = p4.P4LogOutput()
                if not p4.p4_edit(new_image_path,p4_output=p4_output):
                    MSFS2024_LOGGER.error(
                        message=f"'{new_image_path}' : Could not be opened for edit.",
                        details=f"P4 error:\n{str(p4_output)}",
                    )
            copyfile(image_path, new_image_path)
            MSFS2024_LOGGER.info(
                message=f"'{image_name}' : Texture was copied successfully!",
                details=f"Texture copied from '{image_path}' to '{new_image_path}'",
            )

        # Serializing json
        json_object = json.dumps(json_file_object, indent=4)

        # Write in file
        try:
            file = open(gltf_path, 'w+', encoding="utf-8")
            if file:
                file.write(json_object)
            file.close()
        except IOError:
            gltf_base_name = os.path.basename(gltf_path)
            MSFS2024_LOGGER.error(
                message=f"'{gltf_base_name}' : Could not be written.",
                details=f"Access Denied:\n{gltf_path}",
            )
            return

    def export_gltf_textures(
        self, 
        context: bpy.types.Context, 
        gltf_paths: list[str], 
        texture_dir: str
    ):
        for gltf_path in gltf_paths:
            self._export_gltf_texture(context, gltf_path, texture_dir)

    # endregion

    def _execute(self, context: bpy.types.Context):

        export_settings.init_setting_presets(context.scene)
        gltf_paths = []
        # Reset Texture Cache
        MSFS2024_MaterialUtils.reset_exported_textures_cache()

        self._object_layer_collections = MSFS2024_OT_MultiExportGLTF2._construct_object_layer_collections_dict()
        self._treated_layer_collections = set()
        # region Objects
        if (
            self._export_mode_value == multi_export_mode.ExportMode.OBJECTS
            or self._export_mode_value == multi_export_mode.ExportMode.COLLECTIONS
        ):
            exported_paths = self.export_lod_groups(context)
            gltf_paths.extend(exported_paths)
        # endregion

        # region Presets
        elif self._export_mode_value == multi_export_mode.ExportMode.PRESETS:
            exported_paths = self.export_presets(context)
            gltf_paths.extend(exported_paths)
        # endregion

        if len(gltf_paths) < 1:
            process_exceptions = []
            traceback.format_list(process_exceptions)
            if process_exceptions:
                MSFS2024_LOGGER.error(
                    message="An error occurred during export, no glTF files were exported.",
                    details=str(process_exceptions),
                )
                msfs_logs.process_logger_report(self, MSFS2024_LOGGER)
                return {"CANCELLED"}

            msfs_logs.process_logger_report(self, MSFS2024_LOGGER)
            return {"FINISHED"}

        self.check_for_cancel_request()
        # region Textures

        texture_dir = self.msfs_export_settings.export_texture_dir

        if not self.msfs_export_settings.export_keep_originals:
            SubProcessReport.report_progress_text("Exporting Textures...")
            self.export_gltf_textures(
                context,
                gltf_paths,
                texture_dir
            )

        self.check_for_cancel_request()

        if self.msfs_export_settings.generate_texturelib:
            SubProcessReport.report_progress_text("Generating Tex Lib...")
            msfs_texturelib.export_texturelib_with_gltf(
                gltf_paths,
                self.msfs_export_settings.export_keep_originals,
                texture_dir
            )

        return {"FINISHED"}

    def execute(self, context: bpy.types.Context):

        self._start_export_time = time.perf_counter()
        if self.profiling:
            import cProfile
            import pstats
            import io
            profiler = cProfile.Profile()
            profiler.enable()

        global MSFS2024_LOGGER
        MSFS2024_LOGGER = msfs_logs.get_logger()
        MSFS2024_LOGGER.clear_logs()
        # Convert string to ExportMode Enum value
        self._export_mode_value = multi_export_mode.ExportMode.from_identifier(self.export_mode)
        if not self._export_mode_value:
            MSFS2024_LOGGER.error(
                    message="Invalid Export Mode!"
                )
            return {"CANCELLED"}

        if self.called_in_subprocess:
            subprocess_cancel.read_cancel_requests_from_stdin()
        else:

            if not pre_export.pre_export_check(self._export_mode_value, self):
                return {"CANCELLED"}

        self.check_for_cancel_request()

        result = {"FINISHED"}
        # Safely launch _execute
        try:
            # Disable unecessary handlers during export
            with msfs_handlers.HandlersDisabled():
                result = self._execute(context)
        except :
            MSFS2024_LOGGER.error(
                    message="An error occurred during export",
                    details=str(traceback.format_exc()),
                )
            result = {"CANCELLED"}

        # endregion

        if self.profiling:
            profiler.disable()
            # Print stats to the console
            s = io.StringIO()
            ps = pstats.Stats(profiler, stream=s).sort_stats("cumtime")
            ps.print_stats(50)
            print(s.getvalue())

        # Report progress finish after end of profiling
        # Prevents process to be closed too soon
        SubProcessReport.report_progress(100)
        msfs_logs.process_logger_report(self, MSFS2024_LOGGER)

        return result
# endregion

def launch_export(context: bpy.types.Context, export_mode: multi_export_mode.ExportMode | str):
    """Launch the appropriate MSFS export operator.

    Depending on whether background export is enabled in the scene,
    this will either start the export in a Blender subprocess or
    run the multi-export operator directly.
    """
    
    if isinstance(export_mode, str):
        _export_mode = multi_export_mode.ExportMode.from_identifier(export_mode)

        if not export_mode:
            raise ValueError(f"Export mode is not valid : {export_mode}")
        else:
            export_mode = _export_mode
    
    if context.scene.msfs_background_export:
        bpy.ops.msfs2024.subprocess_export(export_mode=export_mode.identifier)
    else:
        bpy.ops.msfs2024.multi_export_gltf(export_mode=export_mode.identifier)
