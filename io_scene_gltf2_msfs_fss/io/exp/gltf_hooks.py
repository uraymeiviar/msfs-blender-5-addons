from __future__ import annotations
import traceback
from typing import TYPE_CHECKING
from types import FunctionType

from copy import copy
from pathlib import Path
import traceback

import bpy

from io_scene_gltf2_msfs_fss import get_version_string
from io_scene_gltf2_msfs_fss.io.exp import export_settings
from io_scene_gltf2.io.com.gltf2_io_extensions import Extension

from io_scene_gltf2_msfs_fss.io.com.extensions.object.asobo_facial_animation import AsoboFacialAnimation
from io_scene_gltf2_msfs_fss.io.com.extensions.object.asobo_gizmo_object import AsoboGizmoObject
from io_scene_gltf2_msfs_fss.io.com.extensions.object.asobo_softbody_mesh import AsoboSoftBodyMesh
from io_scene_gltf2_msfs_fss.io.com.extensions.object.asobo_unique_id import AsoboUniqueId
from io_scene_gltf2_msfs_fss.io.com.extensions import asobo_property_animation
from io_scene_gltf2_msfs_fss.io.com.msfs_material_extensions import MSFS2024_MaterialExtension
from io_scene_gltf2_msfs_fss.io.com.msfs_light_extensions import MSFS2024_LightExtension
from io_scene_gltf2_msfs_fss.io.com.msfs_nodes_utils import MSFS2024_NodeUtils
from io_scene_gltf2_msfs_fss.io.com import msfs_gltf_mesh_utils
from io_scene_gltf2_msfs_fss.io.com.msfs_material_utils import MSFS2024_MaterialUtils
from io_scene_gltf2_msfs_fss.io.com.msfs_data_utils import MSFS2024_DataUtils

from io_scene_gltf2_msfs_fss.io.com import msfs_logs


if TYPE_CHECKING:
    from io_scene_gltf2.io.com import gltf2_io
    if bpy.app.version > (4,5,0):
        from io_scene_gltf2.blender.exp import gltf2_blender_gather_tree as gltf2_tree
    else:
        from io_scene_gltf2.blender.exp import tree as gltf2_tree


def hook_wrapper(func: FunctionType):
    """Safely execute hook and push exception to logs.
    """
    def inner(*args, **kwargs):
        try:
            func(*args, **kwargs)
        except:
            MSFS2024_LOGGER = msfs_logs.get_logger()
            MSFS2024_LOGGER.error(
                message=f"Exception in Hook '{func.__name__}'",
                details=f"Report this error to DevSupport:\n{str(traceback.format_exc())}",
            )
        
    return inner

class Export:
    """
    Class containing functions (alias hooks) called by gltf addon during export process.

    Hooks call order :
        - gather_asset_hook
        - vtree_before_filter_hook
        - vtree_after_filter_hook
        - gather_material_hook
        - gather_image_hook
        - gather_mesh_hook
        - gather_joint_hook
        - gather_skin_hook
        - gather_node_hook
        - gather_scene_hook
        - pre_gather_tracks_hook

        animation hooks:
        - gather_animation_hook #only on version < 4.5

        - gather_gltf_hook
        - gather_gltf_extensions_hook

    List of all available hooks:
    https://github.com/KhronosGroup/glTF-Blender-IO/blob/main/example-addons/example_gltf_exporter_extension/readme.md
    """
    msfs_export_settings: None | export_settings.MSFS2024_MultiExporterSettings = None

    def __init__(self):

        self.node_name_blender_object_map : dict[str, bpy.types.Object] = {}
        # scene_vexport_nodes_copy contains all scene vnodes even the ones that are not exported
        self.scene_vexport_nodes_copy: dict[bpy.types.Object | bpy.types.PoseBone, gltf2_tree.VExportNode] = {} 
        self.node_transforms: dict[bpy.types.Object, None | tuple] = {}

    def _get_blender_version_string(self) -> str:
        return (
            str(bpy.app.version[0])
            + "."
            + str(bpy.app.version[1])
            + "."
            + str(bpy.app.version[2])
        )

    def _hooks_enabled(self)->bool:
        return (
            self.msfs_export_settings
            and self.msfs_export_settings.enable_msfs_extension
        ) # type: ignore

    @hook_wrapper
    def gather_asset_hook(
        self,
        gltf2_asset: gltf2_io.Asset,
        khronos_export_settings: dict
    ):
        """
        Used to define gltf metadata.
        """
        if not self._hooks_enabled():
            return

        # Dict image_name -> texture_info to avoid duplicated textures in gltf
        if gltf2_asset.extensions is None:
            gltf2_asset.extensions = {}

        gltf2_asset.extensions["ASOBO_normal_map_convention"] = Extension(
            name="ASOBO_normal_map_convention",
            extension={"tangent_space_convention": "DirectX"},
            required=False,
        )

        gltf2_asset.generator += (
            f" and Asobo Studio MSFS2024 Blender I/O v{get_version_string()}"
        )
        gltf2_asset.generator += f" with Blender v{self._get_blender_version_string()}"

        asobo_property_animation.prepare_for_export(khronos_export_settings)
        # Reset Texture infos Cache
        MSFS2024_MaterialUtils.reset_tex_infos_cache()

    @hook_wrapper   
    def vtree_before_filter_hook(self, vtree: gltf2_tree.VExportTree, khronos_export_settings: dict):
        """
        Launched before Vtree filter. 
        Vtree filter process modify vtree by removing VNodes that should not be exported,
        for example the VNode that are not selected in scene.
        """
        if not self._hooks_enabled():
            return

        for vnode in vtree.nodes.values():
            if self.msfs_export_settings.export_as_submodel:
                if vnode.blender_object:
                    # Construct a dict mapping export gltf node name to blender objects
                    self.node_name_blender_object_map[vnode.blender_object.name] = (
                        vnode.blender_object
                    )

            # Store all scene vnodes
            # These will later be used in vtree_after_filter_hook and gather_node_hook to edit gltf2_node transforms
            if not vnode.blender_object and not vnode.blender_bone:
                continue
            if vnode.blender_bone:
                # Store vnode for each bone
                pose_bone: bpy.types.PoseBone = vnode.blender_bone
                if not pose_bone:
                    continue
                self.scene_vexport_nodes_copy[pose_bone] = copy(vnode)
            else:
                self.scene_vexport_nodes_copy[vnode.blender_object] = copy(vnode)

    def _gather_nodes_transforms(self, vnodes:list[gltf2_tree.VExportNode], vtree: gltf2_tree.VExportTree):
        for vnode in vnodes:
            blender_object = vnode.blender_object
            if not blender_object:
                continue
            self.node_transforms[blender_object] = (
                MSFS2024_NodeUtils.gather_gltf2_node_transform(
                    blender_object,
                    self.scene_vexport_nodes_copy,
                    self.msfs_export_settings,
                    vtree,
                )
            )
            if vnode.children:
                children_vnodes = []
                for child_uuid in vnode.children:
                    _vnode = vtree.nodes.get(child_uuid, None)
                    if _vnode:
                        children_vnodes.append(_vnode)

                self._gather_nodes_transforms(children_vnodes, vtree)

    @hook_wrapper
    def vtree_after_filter_hook(self, vtree: gltf2_tree.VExportTree, khronos_export_settings:dict):
        # Retrieve the glTF node transform here because this hook runs on parent nodes
        # before their children. This ensures children later inherit the updated parent
        # transforms. The transforms are applied later in gather_node_hook.
        if vtree.nodes:
            self._gather_nodes_transforms(vtree.nodes.values(), vtree)

    @hook_wrapper
    def gather_material_hook(
        self,
        gltf2_material: gltf2_io.Material,
        blender_material: bpy.types.Material,
        khronos_export_settings: dict
    ):  
        """Called on each material before processing mesh with gather_mesh_hook.
        Not called if material was already treated on a previous mesh.
        """
        if not self._hooks_enabled():
            return

        # Clear textures detected by the built-in glTF exporter.
        # Bug found in io_scene_gltf2/blender/exp/nodes.py (__gather_mesh()):
        # The following line can return invalid materials from the evaluated mesh
        # when Apply Modifiers is enabled:
        # materials = tuple(mat for mat in blender_mesh.materials)
        # Bug occurs when "Export In Background" Export is disabled.
        gltf2_material.emissive_texture = None
        gltf2_material.normal_texture = None
        gltf2_material.occlusion_texture = None
        pbr_metallic_roughness = gltf2_material.pbr_metallic_roughness
        if pbr_metallic_roughness:
            pbr_metallic_roughness.base_color_texture = None
            pbr_metallic_roughness.metallic_roughness_texture = None

        if bpy.app.version >= (5, 2, 0):
            # in 5.2 passed blender_material is bpy.types.InlineShaderNodes instead of bpy.types.Material ...
            # Retrieve material with name
            blender_material = bpy.data.materials.get(gltf2_material.name)

        _blender_material = blender_material
        original = MSFS2024_MaterialUtils.get_original_material(blender_material)
        if original:
            _blender_material = original
            # Rename gltf2_material correctly after pre export duplication
            gltf2_material.name = original.name

        MSFS2024_MaterialExtension.export(
            gltf2_material=gltf2_material,
            blender_material=_blender_material,
            export_settings=khronos_export_settings
        )
        # Material Animation
        if self.msfs_export_settings.export_animations:
            asobo_property_animation.gather_material_animations(
                _blender_material,
                khronos_export_settings,
            )
    @staticmethod
    def _fix_gltf2_image(gltf2_image: gltf2_io.Image):
        # Correct image name when it ends with unwanted suffixes like '.png.png' or '.png.001'
        gltf2_image.name = gltf2_image.name.split(".", 1)[0]
        image_data = gltf2_image.uri
        if not image_data:
            return
        
        if hasattr(image_data, "_name"):
            image_data._name = gltf2_image.name
        if hasattr(image_data, "_adjusted_name"):
            image_data._adjusted_name = image_data.name + image_data.file_extension
        if hasattr(image_data, "uri"):
            uri = Path(image_data.uri).with_name(image_data.name)
            uri = uri.with_suffix(image_data.file_extension)
            image_data.uri = uri.as_posix()

    if bpy.app.version < (4, 5, 0):
        @hook_wrapper
        def gather_image_hook(self, gltf2_image: gltf2_io.Image, blender_shader_sockets, khronos_export_settings: dict):

            self._fix_gltf2_image(gltf2_image)
    else:
        @hook_wrapper
        def gather_image_hook(self, gltf2_image: gltf2_io.Image, mapping, blender_shader_sockets, khronos_export_settings: dict):

            self._fix_gltf2_image(gltf2_image)

    def _gather_mesh_hook(self, 
            gltf2_mesh: gltf2_io.Mesh,
            blender_mesh: bpy.types.Mesh
        ):
        if not self._hooks_enabled():
            return

        if not self.msfs_export_settings.export_mesh:
            gltf2_mesh.primitives = []
            return

        # Rename gltf2_mesh correctly after pre export duplication
        original_mesh_name = MSFS2024_DataUtils.get_msfs_original_name(blender_mesh)
        if original_mesh_name is not None:
            gltf2_mesh.name = original_mesh_name

        msfs_gltf_mesh_utils.clean_color_attributes(
            gltf2_mesh=gltf2_mesh,
            blender_mesh=blender_mesh
        )
        msfs_gltf_mesh_utils.clean_texcoord_attributes(
            gltf2_mesh=gltf2_mesh,
            blender_mesh=blender_mesh
        )

    if bpy.app.version < (3, 6, 0):
        @hook_wrapper
        def gather_mesh_hook(
            self,
            gltf2_mesh: gltf2_io.Mesh,
            blender_mesh: bpy.types.Mesh,
            blender_object: bpy.types.Object,
            vertex_groups: list[bpy.types.VertexGroup],
            modifiers: list[bpy.types.Modifier],
            skip_filter: bool,
            materials: list[bpy.types.Material],
            khronos_export_settings:dict,
        ):

            self._gather_mesh_hook(gltf2_mesh, blender_mesh)
    else:
        @hook_wrapper
        def gather_mesh_hook(
            self,
            gltf2_mesh: gltf2_io.Mesh,
            blender_mesh: bpy.types.Mesh,
            blender_object: None | bpy.types.Object,
            vertex_groups: bpy.types.VertexGroups,
            modifiers: None | bpy.types.ObjectModifiers,
            materials: tuple[bpy.types.Material, ...],
            khronos_export_settings: dict,
        ):
            self._gather_mesh_hook(gltf2_mesh, blender_mesh)
    
    @hook_wrapper
    def gather_joint_hook(
        self,
        gltf2_node: gltf2_io.Node,
        blender_bone: bpy.types.PoseBone,
        khronos_export_settings: dict
    ):
        
        if not self._hooks_enabled():
            return

        gltf2_node.extensions = {}
        AsoboUniqueId.export(
            gltf2_object=gltf2_node,
            blender_object=blender_bone
        )

        AsoboFacialAnimation.export(
            gltf2_object=gltf2_node, 
            blender_object=blender_bone
        )
        return
    
    @hook_wrapper
    def gather_node_hook(
        self, 
        gltf2_node: gltf2_io.Node,
        blender_object: bpy.types.Object,
        khronos_export_settings: dict
    ):  
        
        if not self._hooks_enabled():
            return

        node_transform = self.node_transforms.get(blender_object, None)
        if node_transform:
            gltf2_node.translation = node_transform[0]
            gltf2_node.rotation = node_transform[1]
            gltf2_node.scale = node_transform[2]

        # Rename gltf2_object correctly after pre export duplication
        original_object_name = MSFS2024_DataUtils.get_msfs_original_name(blender_object)
        if original_object_name is not None:
            gltf2_node.name = original_object_name

        AsoboUniqueId.export(
            gltf2_object=gltf2_node,
            blender_object=blender_object
        )

        MSFS2024_LightExtension.export(
            gltf2_object=gltf2_node,
            blender_object=blender_object
        )

        AsoboSoftBodyMesh.export(
            gltf2_object=gltf2_node,
            blender_object=blender_object
        )

        if not self.msfs_export_settings.export_mesh:
            gltf2_node.mesh = None

        asobo_property_animation.gather_node(
            blender_object, self.scene_vexport_nodes_copy
        )

    if bpy.app.version >= (3, 6, 0):
        @hook_wrapper
        def pre_gather_tracks_hook(self, blender_object: bpy.types.Object, khronos_export_settings: dict):
            if not self._hooks_enabled():
                return
            # Prevent a bug on blender 3.6, 4.2, 4.5
            # Bug affects export of obj and bone constant animations in NLA Track Mode.
            # In this case we force export of these channels

            # We do not have this issue in Action mode (which may be a bug also?)
            if not blender_object.animation_data or not blender_object.animation_data.nla_tracks:
                return
            for track in blender_object.animation_data.nla_tracks:
                asobo_property_animation.gather_track_animated_channels(blender_object, track, self.scene_vexport_nodes_copy)
    
    @hook_wrapper
    def gather_scene_hook(
        self,
        gltf2_scene: gltf2_io.Scene,
        blender_scene: bpy.types.Scene,
        khronos_export_settings: dict
    ):
        if not self._hooks_enabled():
            return

        AsoboGizmoObject.export(
            nodes=gltf2_scene.nodes,
            blender_scene=blender_scene,
            export_settings=khronos_export_settings,
        )

        # Add unique id to "neutral_bone"
        # This bone is added by KHRONOS exporter during export armature

        neutral_nodes_parent_map = {}
        MSFS2024_NodeUtils.find_neutral_bones(
            gltf2_scene.nodes, neutral_nodes_parent_map
        )

        for parent_name, neutral_node in neutral_nodes_parent_map.items():
            AsoboUniqueId.add_unique_id_to_neutral_bone(neutral_node, parent_name)
    
    @hook_wrapper
    def gather_animation_hook(
        self,
        gltf2_animation: gltf2_io.Animation,
        blender_action: bpy.types.Action,
        blender_object: bpy.types.Object,
        khronos_export_settings: dict
    ):  
        """Only for version < 4.5
        """
        # TODO doesnt exist in blender 4.5
        if not self._hooks_enabled():
            return

        AsoboFacialAnimation.export(
            gltf2_object=gltf2_animation,
            blender_object=blender_action
        )
    
    @hook_wrapper
    def gather_gltf_hook(
        self,
        active_scene_idx: int,
        scenes: list[gltf2_io.Scene],
        animations: list[gltf2_io.Animation],
        khronos_export_settings: dict
    ):
        if not self._hooks_enabled():
            return

        if self.msfs_export_settings.export_as_submodel:
            MSFS2024_NodeUtils.create_submodel_scenes(scenes, self.node_name_blender_object_map)

        # Initialize the material animation extension in this hook by inserting
        # material animation samplers into glTF animation samplers.
        # This must be done in this hook because it is called before the exporter's
        # `__create_buffer` function (see `__export` function in the glTF addon).
        asobo_property_animation.init_mat_anim_extensions(animations)
    
    @hook_wrapper
    def gather_gltf_extensions_hook(
        self,
        gltf2_plan: gltf2_io.Gltf,
        khronos_export_settings: dict
    ):

        if not self._hooks_enabled():
            return

        if not self.msfs_export_settings.export_mesh:
            gltf2_plan.meshs = []

        # Set animation channels.
        # This must be done in this hook because the channel target must correspond
        # to the final glTF material index.
        asobo_property_animation.finalize_material_animations(gltf2_plan)

        # Rename nodes at the end of export process, just to make sure that any functions
        # relying on node.name works correctly.
        # For example, MSFS2024_NodeUtils.create_submodel_scenes() in  gather_gltf_hook() uses node.name
        # to parse node_name_blender_object_map.
        if self.msfs_export_settings.remove_lod_prefix and gltf2_plan.nodes:
            for node in gltf2_plan.nodes:
                MSFS2024_NodeUtils.remove_lod_prefix(gltf2_node=node)

    # endregion
