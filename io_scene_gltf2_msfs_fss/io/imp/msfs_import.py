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
import mathutils

from ..com.extensions.object.asobo_facial_animation import AsoboFacialAnimation
from ..com.extensions.object.asobo_gizmo_object import AsoboGizmoObject
from ..com.extensions.object.asobo_unique_id import AsoboUniqueId
from ..com.extensions.object.asobo_softbody_mesh import AsoboSoftBodyMesh

from ..com.msfs_light_extensions import MSFS2024_LightExtension

from ..com.msfs_material_extensions import MSFS2024_MaterialExtension

from ..com.msfs_texture_utils import MSFS2024_TextureUtils
from ..imp.msfs_import_utils import MSFS2024_ImportUtils


class Import:

    def __init__(self):
        self.texture_dirs = []
        self.parent_scene_node_map = {}
        
    def gather_import_scene_before_hook(
        self,
        gltf_scene,
        blender_scene,
        import_settings
    ):
        use_msfs_parameters = bpy.context.scene.msfs_importer_settings.enable_msfs_extension
        if not use_msfs_parameters:
            return
        
        self.texture_dirs = MSFS2024_TextureUtils.get_gltf_texture_dirs(
            import_settings.filename
        )
            
    def gather_import_scene_after_nodes_hook(self, gltf_scene, blender_scene, gltf):
        # We need to reparent objects if the model contains a scene extension
        # It means that it has been exported as submodel
        for sub_gltf_scene in gltf.data.scenes:
            if not sub_gltf_scene:
                continue

            if not sub_gltf_scene.extensions:
                continue

            extension = sub_gltf_scene.extensions.get(AsoboUniqueId.extension_name)
            if not extension:
                continue
            
            parent_name = extension.get("id", None)
            if not parent_name:
                continue
            
            parent_blender_object = blender_scene.objects.get(parent_name, None)
                     
            for gltf_node_id in sub_gltf_scene.nodes:
                gltf_node_data = gltf.data.nodes[gltf_node_id]
                if not gltf_node_data:
                    continue
                
                child_name = AsoboUniqueId.get_asobo_unique_id(gltf_node_data)
                if child_name is None:
                    child_name = gltf_node_data.name
                
                if not parent_blender_object:
                    gltf.log.warning(f"Parent object '{parent_name}' of '{child_name}' not found in the scene. Could be in another gltf model.")
                    continue
                    
                child_blender_object = blender_scene.objects.get(child_name, None)
                if not child_blender_object:
                    gltf.log.warning(f"Child object '{child_name}' not found in the scene.")
                    continue
                
                child_blender_object.parent = parent_blender_object

    def gather_import_image_before_hook(self, gltf_img, gltf):
        use_msfs_parameters = bpy.context.scene.msfs_importer_settings.enable_msfs_extension
        if not use_msfs_parameters:
            return
        gltf_img.uri = MSFS2024_TextureUtils.resolve_texture_path(
            gltf_img.uri, self.texture_dirs
        )

    def gather_import_node_after_hook(
        self,
        vnode,
        gltf2_node,
        blender_object,
        import_settings
    ):
        if blender_object is None:
            return

        importer_settings = bpy.context.scene.msfs_importer_settings
        use_msfs_parameters = bpy.context.scene.msfs_importer_settings.enable_msfs_extension

        if not use_msfs_parameters:
            return

        AsoboGizmoObject.from_extension(
            gltf2_node,
            blender_object,
            import_settings,
            importer_settings.import_collisions,
        )
        # Disable systematic unique id on import
        # AsoboUniqueId.from_extension(gltf2_node, blender_object)
        AsoboFacialAnimation.from_extension(gltf2_node, blender_object)
        AsoboSoftBodyMesh.from_extension(gltf2_node, blender_object)
        # Lights
        MSFS2024_LightExtension.import_light(vnode, gltf2_node, blender_object)

    
    def gather_import_mesh_before_hook(self, gltf_mesh, gltf):
        importer_settings = bpy.context.scene.msfs_importer_settings
        use_msfs_parameters = importer_settings.enable_msfs_extension
        if not use_msfs_parameters:
            return

        if not importer_settings.import_materials:
            # Remove Materials
            for prim in gltf_mesh.primitives:
                if getattr(prim, "material", None) is not None:
                    prim.material = None

        if not importer_settings.import_collisions:
            # Remove Collisions
            for prim in gltf_mesh.primitives:
                if MSFS2024_ImportUtils.is_collision_prim(prim, gltf):
                    prim.attributes = {}
                    prim.material = None

    def gather_import_material_after_hook(
        self,
        gltf2_material,
        vertex_color,
        blender_material,
        import_settings
    ):
        use_msfs_parameters = bpy.context.scene.msfs_importer_settings.enable_msfs_extension
        if not use_msfs_parameters:
            return
        # Create materials
        MSFS2024_MaterialExtension.create(
            gltf2_material, blender_material, import_settings
        )

    def gather_import_animation_channel_after_hook(
        self,
        gltf_animation,
        gltf_node,
        path,
        channel,
        blender_action,
        gltf
    ):
        use_msfs_parameters = bpy.context.scene.msfs_importer_settings.enable_msfs_extension
        if not use_msfs_parameters:
            return
        AsoboFacialAnimation.from_extension(gltf_animation, blender_action)
