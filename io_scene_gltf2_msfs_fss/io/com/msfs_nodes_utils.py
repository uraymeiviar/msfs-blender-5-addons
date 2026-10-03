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
from __future__ import annotations
from typing import TYPE_CHECKING

import bpy
import mathutils
import re

from io_scene_gltf2_msfs_fss.io.exp.export_settings import MSFS2024_MultiExporterSettings

from .extensions.object.asobo_unique_id import AsoboUniqueId

from .msfs_data_utils import MSFS2024_DataUtils

from io_scene_gltf2_msfs_fss.blender.utils import msfs_object_utils

from io_scene_gltf2.io.com.gltf2_io import Scene
from io_scene_gltf2.io.com.gltf2_io_extensions import Extension
if TYPE_CHECKING:
    from io_scene_gltf2.io.com import gltf2_io
    if bpy.app.version > (4,5,0):
        from io_scene_gltf2.blender.exp import gltf2_blender_gather_tree as gltf2_tree
    else:
        from io_scene_gltf2.blender.exp import tree as gltf2_tree

    NODE_TRANSFORM = tuple[list | None, list | None, list | None]

class MSFS2024_NodeUtils:
    bl_options = {"UNDO"}

    @staticmethod
    def find_neutral_bones(roots, neutral_bones_armature_map, parent=None):
        for node in roots:
            if node.name == "neutral_bone":
                neutral_bones_armature_map[parent.name] = node

            if node.children is None:
                continue

            if len(node.children) <= 0:
                continue

            MSFS2024_NodeUtils.find_neutral_bones(
                node.children, neutral_bones_armature_map, node
            )

    @staticmethod
    def _convert_to_gltf_transform(
        location: mathutils.Vector,
        rotation: mathutils.Quaternion,
        scale: mathutils.Vector,
    ) -> NODE_TRANSFORM:
        """Convert blender transform to gltf transforms.
        cf __gather_trans_rot_scale in io_scene_gltf2 addon.
        Assume that gltf yup is enabled.
        """

        def _round_if_near(value: float, target: float) -> float:
            """If value is very close to target, round to target."""
            return value if abs(value - target) > 2.0e-6 else target

        # Make sure the rotation is normalized
        rotation.normalize()

        # swizzle
        # gltf yup
        trans = [location[0], location[2], -location[1]]
        rot = [rotation[0], rotation[1], rotation[3], -rotation[2]]
        sca = [scale[0], scale[2], scale[1]]

        c_translation, c_rotation, c_scale = (None, None, None)
        # Rounding
        trans[0], trans[1], trans[2] = (
            _round_if_near(trans[0], 0.0),
            _round_if_near(trans[1], 0.0),
            _round_if_near(trans[2], 0.0),
        )

        rot[0], rot[1], rot[2], rot[3] = (
            _round_if_near(rot[0], 1.0),
            _round_if_near(rot[1], 0.0),
            _round_if_near(rot[2], 0.0),
            _round_if_near(rot[3], 0.0),
        )
        sca[0], sca[1], sca[2] = (
            _round_if_near(sca[0], 1.0),
            _round_if_near(sca[1], 1.0),
            _round_if_near(sca[2], 1.0),
        )

        if trans[0] != 0.0 or trans[1] != 0.0 or trans[2] != 0.0:
            c_translation = trans
        if rot[0] != 1.0 or rot[1] != 0.0 or rot[2] != 0.0 or rot[3] != 0.0:
            c_rotation = [rot[1], rot[2], rot[3], rot[0]]
        if sca[0] != 1.0 or sca[1] != 1.0 or sca[2] != 1.0:
            c_scale = sca
        return (c_translation, c_rotation, c_scale)

    @staticmethod
    def _get_parent_vnode(
        blender_object: bpy.types.Object,
        scene_vexport_nodes: dict[
            bpy.types.Object | bpy.types.PoseBone, gltf2_tree.VExportNode
        ],
    ) -> None | gltf2_tree.VExportNode:

        parent = blender_object.parent
        if parent and blender_object.parent.type == "ARMATURE":
            parent_bone = msfs_object_utils.get_parent_bone(
                blender_object,
                pose_bone=True
            )
            if parent_bone:
                parent = parent_bone

        if parent:
            parent_vnode = scene_vexport_nodes.get(parent)
            if parent_vnode:
                return parent_vnode
        return None

    @staticmethod
    def _get_gltf2_node_transform(
        vnode,
        parent_vnode,
        matrix_world_override: None | mathutils.Matrix = None,
    ) -> None | NODE_TRANSFORM:
        """Compute the object's local transform following the glTF spec.

        This reproduces the logic from the built-in gltf exporter
        (see __gather_trans_rot_scale).
        """

        matrix_world = vnode.matrix_world
        if matrix_world_override:
            matrix_world = matrix_world_override

        local_matrix = matrix_world
        if parent_vnode:
            local_matrix = parent_vnode.matrix_world.inverted_safe() @ matrix_world

        trans, rot, scale = local_matrix.decompose()

        c_trans, c_rot, c_scale = MSFS2024_NodeUtils._convert_to_gltf_transform(
            trans, rot, scale
        )

        return c_trans, c_rot, c_scale

    @staticmethod
    def _get_last_armature_modifier(
            obj: bpy.types.Object,
        ) -> None | bpy.types.ArmatureModifier:
        arm_mod = None
        for mod in reversed(obj.modifiers):
            if isinstance(mod, bpy.types.ArmatureModifier):
                arm_mod = mod
                break
        return arm_mod

    @staticmethod
    def gather_gltf2_node_transform(
        blender_object: bpy.types.Object,
        scene_vexport_nodes_copy: dict[
            bpy.types.Object | bpy.types.PoseBone, gltf2_tree.VExportNode
        ],
        msfs_export_settings: MSFS2024_MultiExporterSettings,
        vtree: gltf2_tree.VExportTree,
    ) -> None | NODE_TRANSFORM:
        """
        - Forces relative transforms for skinned nodes
        (required by MSFS and not strictly gltf-spec compliant).

        - Adjusts node transforms based on export settings
        (e.g. submodel export, origin reset).


        This function must run on parent nodes before their children
        so child transforms are computed in the correct parent space.
        """

        vnode = scene_vexport_nodes_copy.get(blender_object)

        transform = None 

        if not vnode :
            return transform

        parent_vnode = MSFS2024_NodeUtils._get_parent_vnode(
            blender_object, scene_vexport_nodes_copy
        )
        if parent_vnode and not msfs_export_settings.export_as_submodel:
            # Set parent to None if it is not included in export
            parent_vnode = parent_vnode if parent_vnode.uuid in vtree.nodes.keys() else None

        arm_mode = MSFS2024_NodeUtils._get_last_armature_modifier(blender_object)
        vnode_has_skin = bool(msfs_export_settings.export_skins and arm_mode)

        parent_vnode_has_skin = False
        if parent_vnode and parent_vnode.blender_object:
            arm_mode = MSFS2024_NodeUtils._get_last_armature_modifier(blender_object)
            parent_vnode_has_skin = msfs_export_settings.export_skins and arm_mode

        if vnode_has_skin or (parent_vnode and parent_vnode_has_skin):
            # By default the gltf exporter does not compute TRS for skinned nodes or their children.
            # However the engine does not follow the gltf spec and requires them,
            # because skinned node meshes are stored in local space instead of
            # world space (see msfs_get_positions in gltf_exporter_patches).

            transform = MSFS2024_NodeUtils._get_gltf2_node_transform(
                vnode,
                parent_vnode,
            )
            # Store matrix world in order to correctly recompute transforms of children
            vnode.matrix_world = blender_object.matrix_world.copy()

        if msfs_export_settings.export_as_submodel:
            if blender_object.parent and not blender_object.parent.select_get():
                # Ensure children of excluded parents use a transform relative to their parent.
                # Otherwise the node would be exported with a transform relative to the world origin.
                transform = MSFS2024_NodeUtils._get_gltf2_node_transform(
                    vnode, parent_vnode
                )

        if vnode.skin or blender_object.type == "ARMATURE":
            # Can't reset origins of skinned objects or armature object
            return transform

        if msfs_export_settings.reset_origins == "ALL_ROOTS":
            # Reset all root nodes.
            msfs_export_transform = msfs_export_settings.export_transform_properties
            # Reset if no parent or unincluded parent
            if (not blender_object.parent or not blender_object.parent.select_get()):  
                
                current_trans, current_rot, current_scale = MSFS2024_NodeUtils._get_gltf2_node_transform(
                    vnode,
                    parent_vnode
                )
    
                trans, rot, scale = vnode.matrix_world.decompose()
                export_transform_props = msfs_export_settings.export_transform_properties
                if export_transform_props.reset_translation:
                    trans = mathutils.Vector((0, 0, 0))
                if export_transform_props.reset_rotation:
                    rot = mathutils.Quaternion()
                if export_transform_props.reset_scale:
                    scale = mathutils.Vector((1, 1, 1))

                new_matrix_world = mathutils.Matrix.LocRotScale(trans, rot, scale)
                
                new_trans, new_rot, new_scale = MSFS2024_NodeUtils._get_gltf2_node_transform(
                    vnode,
                    parent_vnode,
                    matrix_world_override=new_matrix_world,
                )
    
                if export_transform_props.reset_translation:
                    current_trans = new_trans
                if export_transform_props.reset_rotation:
                    current_rot = new_rot
                if export_transform_props.reset_scale:
                    current_scale = new_scale
    
                transform = (current_trans, current_rot, current_scale)

                # Save transform edits
                vnode.matrix_world = new_matrix_world

        elif msfs_export_settings.reset_origins == "PER_OBJECT":
            msfs_export_transform = blender_object.msfs_export_transform
            has_transform_reset = (
                msfs_export_transform.reset_translation
                or msfs_export_transform.reset_rotation
                or msfs_export_transform.reset_scale
            )
            if not has_transform_reset:
                return transform

            current_trans, current_rot, current_scale = MSFS2024_NodeUtils._get_gltf2_node_transform(
                vnode,
                parent_vnode
            )

            trans, rot, scale = vnode.matrix_world.decompose()
            if msfs_export_transform.reset_translation:
                trans = mathutils.Vector((0, 0, 0))
            if msfs_export_transform.reset_rotation:
                rot = mathutils.Quaternion()
            if msfs_export_transform.reset_scale:
                scale = mathutils.Vector((1, 1, 1))

            new_matrix_world = mathutils.Matrix.LocRotScale(trans, rot, scale)

            new_trans, new_rot, new_scale = MSFS2024_NodeUtils._get_gltf2_node_transform(
                vnode,
                parent_vnode,
                matrix_world_override=new_matrix_world,
            )

            if msfs_export_transform.reset_translation:
                current_trans = new_trans
            if msfs_export_transform.reset_rotation:
                current_rot = new_rot
            if msfs_export_transform.reset_scale:
                current_scale = new_scale

            transform = (current_trans, current_rot, current_scale)

            # Save transform edits
            vnode.matrix_world = new_matrix_world

        return transform

    @staticmethod
    def remove_lod_prefix(gltf2_node: gltf2_io.Node):
        pattern = r"(?i)x[0-9]_"
        gltf2_node.name = re.sub(pattern, "", gltf2_node.name)

    @staticmethod
    def get_unique_id(gltf2_node: gltf2_io.Node):
        if gltf2_node.extensions is None:
            return None

        asobo_unique_id_extension = gltf2_node.extensions.get(
            AsoboUniqueId.extension_name, None
        )
        if asobo_unique_id_extension is None:
            return None

        extension = asobo_unique_id_extension.extension
        if extension is None:
            return None

        return extension.get("id", None)

    @staticmethod
    def create_submodel_scenes(scenes: list[gltf2_io.Scene], node_name_blender_object_map: dict[str, bpy.types.Object]):
        """
        Create a gltf scene for each unincluded parent of nodes to export.
        """
        parent_nodes_map = {}
        root_nodes = []
        for scene in scenes:

            for node in scene.nodes:
                obj = node_name_blender_object_map.get(node.name, None)

                if not obj:
                    continue

                parent_name = ""
                parent_obj : None | bpy.types.Object | bpy.types.Bone= obj.parent

                if not parent_obj:
                    root_nodes.append(node)
                    continue
                if parent_obj.type == "ARMATURE":
                    parent_obj = msfs_object_utils.get_parent_bone(obj)

                parent_name = MSFS2024_DataUtils.get_msfs_original_name(parent_obj)
                if not parent_name:
                    parent_name = parent_obj.name

                if hasattr(parent_obj, "msfs_override_unique_id") and parent_obj.msfs_override_unique_id:
                    parent_name = parent_obj.msfs_unique_id

                if parent_name not in parent_nodes_map:
                    parent_nodes_map[parent_name] = []

                parent_nodes_map[parent_name].append(node)

        new_scenes = []
        if root_nodes:
            scene = Scene(extensions=None, extras=None, name=None, nodes=root_nodes)
            new_scenes.append(scene)
        for parent_name, nodes in parent_nodes_map.items():
            scene = Scene(extensions=None, extras=None, name=None, nodes=nodes)

            if parent_name != "":
                extension = {}
                extension["id"] = parent_name

                scene.extensions = {}
                scene.extensions[AsoboUniqueId.extension_name] = Extension(
                    name=AsoboUniqueId.extension_name,
                    extension=extension,
                    required=False,
                )

            new_scenes.append(scene)

        scenes.clear()
        scenes.extend(new_scenes)
