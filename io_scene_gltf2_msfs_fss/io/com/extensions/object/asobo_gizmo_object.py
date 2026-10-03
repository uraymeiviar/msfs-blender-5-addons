import bpy
import mathutils

from _addons_common import geometry_node_utils
from io_scene_gltf2.io.com import gltf2_io_extensions

from io_scene_gltf2_msfs_fss.blender import msfs_gizmo
    
  
from io_scene_gltf2_msfs_fss.datafiles.asset_library import MSFS2024CollisionInputs


class AsoboGizmoObject:
    bl_options = {"UNDO"}

    extension_name = "ASOBO_gizmo_object"

    def __new__(cls, *args, **kwargs):
        raise RuntimeError(f"{cls} should not be instantiated")

    @staticmethod
    def _create_object_gizmos(blender_object:bpy.types.Object,extension:dict):
        """
        Create gizmo under blender_object using AsoboGizmoObject mesh extension.
        """
        for gizmo_obj in extension.get("gizmo_objects"):
            gizmo_type = gizmo_obj.get("type")

            gizmo_obj_ext = gizmo_obj.get("extensions", {})
            is_road_collider = True
            is_ground_collider = False
            if gizmo_obj_ext:
                asobo_tags = gizmo_obj_ext.get("ASOBO_tags", {})
                asobo_tags = asobo_tags.get("tags", [])

                if "SkinBoundingVolume" in asobo_tags:
                    gizmo_type = "boundingSphere"

                is_road_collider = "Road" in asobo_tags
                is_ground_collider = "Ground" in asobo_tags

            center = gizmo_obj.get("translation", [0, 0, 0])
            # convert to blender location
            center = [center[0], -center[2], center[1]]

            rotation = gizmo_obj.get("rotation", [0, 0, 0, 0])
            # convert to blender WXYZ Quaternion
            rotation = [rotation[3], rotation[0], -rotation[2], rotation[1]]

            size = gizmo_obj.get("params", {})

            scale = [1.0, 1.0, 1.0]
            if gizmo_type == "sphere" or gizmo_type == "boundingSphere":
                scale[0] = size.get("radius")
                scale[1] = size.get("radius")
                scale[2] = size.get("radius")

            elif gizmo_type == "box":
                scale[0] = size.get("width") / 2
                scale[1] = size.get("length") / 2
                scale[2] = size.get("height") / 2

            elif gizmo_type == "cylinder":
                scale[0] = size.get("radius")
                scale[1] = size.get("radius")
                scale[2] = size.get("height") / 2

            _gizmo_type = msfs_gizmo.GizmoTypes.from_identifier(gizmo_type)
            if not _gizmo_type:
                raise TypeError("AsoboGizmoObject type '{gizmo_type}' is not supported!")
            gizmo_type = _gizmo_type

            gizmo_obj = msfs_gizmo.create_gizmo(gizmo_type)

            if gizmo_type != msfs_gizmo.GizmoTypes.BOUNDING_SPHERE:
                modifier = msfs_gizmo.get_collision_mod(gizmo_obj)
                geometry_node_utils.set_modifier_input(
                    modifier, 
                    MSFS2024CollisionInputs.TYPE.input_label, 
                    gizmo_type.index
                )
                geometry_node_utils.set_modifier_input(
                    modifier, 
                    MSFS2024CollisionInputs.ROAD_COLLIDER.input_label, 
                    is_road_collider
                )
                geometry_node_utils.set_modifier_input(
                    modifier,
                    MSFS2024CollisionInputs.GROUND_COLLIDER.input_label,
                    is_ground_collider,
                )
            
            desired_location = mathutils.Vector(center)
            desired_rotation = mathutils.Quaternion(rotation)
            desired_scale = mathutils.Vector(scale)

            desired_matrix = (
                mathutils.Matrix.Translation(desired_location)
                @ desired_rotation.to_matrix().to_4x4()
                @ mathutils.Matrix.Scale(desired_scale.x, 4, (1, 0, 0))
                @ mathutils.Matrix.Scale(desired_scale.y, 4, (0, 1, 0))
                @ mathutils.Matrix.Scale(desired_scale.z, 4, (0, 0, 1))
            )

            local_matrix = blender_object.matrix_world.inverted() @ desired_matrix

            gizmo_obj.parent = blender_object

            gizmo_obj.matrix_parent_inverse = blender_object.matrix_world.inverted()
            gizmo_obj.matrix_local = local_matrix

            # Link to same collections
            for collection in blender_object.users_collection:
                collection.objects.link(gizmo_obj)

    @staticmethod
    def from_extension(gltf2_node, blender_object, import_settings, import_collisions=True):

        if not gltf2_node:
            return

        # region boundingSphere
        if gltf2_node.extensions:
            node_extension = gltf2_node.extensions.get(AsoboGizmoObject.extension_name)
            if node_extension:
                AsoboGizmoObject._create_object_gizmos(blender_object, node_extension)
        # endregion

        # region standard gizmos
        if not import_collisions:
            return

        if gltf2_node.mesh is None:
            return
        if not import_settings.data.meshes:
            return
        try:
            gltf2_mesh = import_settings.data.meshes[gltf2_node.mesh]
        except IndexError:
            return

        if not gltf2_mesh.extensions:
            return

        mesh_extension = gltf2_mesh.extensions.get(AsoboGizmoObject.extension_name)

        if not mesh_extension:
            return

        AsoboGizmoObject._create_object_gizmos(blender_object, mesh_extension)
        # endregion

    @staticmethod
    def export(nodes, blender_scene, export_settings):
        """
        Let the Khronos exporter gather the gizmo to calculate the proper TRS with the parent to make sure everything is correct,
        then remove the gizmo from the collected nodes and set the proper mesh extensions
        """
        if nodes is None:
            return

        for node in nodes:
            node_extensions = []
            mesh_extensions = []

            if node.children is None:
                continue

            for child in list(node.children):
                # The glTF exporter will ALWAYS
                # set the node name as the blender name
                blender_object = blender_scene.objects.get(child.name)

                # However, there are cases where the exporter
                # creates fake nodes that don't exist in the scene
                if blender_object is None: 
                    continue

                # We only need the collision gizmos
                # that are parented to a mesh
                if blender_object.parent is None:  
                    continue

                if (blender_object.parent.type != "MESH") \
                   and (blender_object.parent.type != "ARMATURE") \
                   and (blender_object.parent_type  != "BONE"):
                    continue

                gizmo_attributes = msfs_gizmo.get_gizmo_attributes(blender_object)
                if not gizmo_attributes:
                    continue

                result = {}
                gizmo_type = gizmo_attributes.gizmo_type
                is_road_collider = gizmo_attributes.is_road_collider
                is_ground_collider = gizmo_attributes.is_ground_collider

                if not gizmo_type:
                    raise TypeError("AsoboGizmoObject type not found on provided object!")

                result["type"] = gizmo_type.identifier

                result["translation"] = child.translation if child.translation else [0.0, 0.0, 0.0]

                if child.rotation:
                    result["rotation"] = child.rotation if child.rotation else [0.0, 0.0, 0.0]

                # If the scale is default, it will be exported
                # as None which will raise an error here
                if child.scale is None: 
                    child.scale = [1.0, 1.0, 1.0]

                # Flip scale to match MSFS gizmo scale system
                if export_settings["gltf_yup"]:
                    child.scale = [child.scale[2], child.scale[0], child.scale[1]]
                else:
                    child.scale = [child.scale[1], child.scale[0], child.scale[2]]

                # Calculate scale per gizmo type
                scale = {}
                if (gizmo_type == msfs_gizmo.GizmoTypes.SPHERE or gizmo_type == msfs_gizmo.GizmoTypes.BOUNDING_SPHERE):
                    scale["radius"] = abs(max(child.scale))
                elif gizmo_type == msfs_gizmo.GizmoTypes.BOX:
                    scale["length"] = abs(child.scale[0]) * 2
                    scale["width"] = abs(child.scale[1]) * 2
                    scale["height"] = abs(child.scale[2]) * 2
                elif gizmo_type == msfs_gizmo.GizmoTypes.CYLINDER:
                    scale["radius"] = abs(max(child.scale[:2]))
                    scale["height"] = abs(child.scale[2]) * 2

                result["params"] = scale

                tags = []

                if gizmo_type == msfs_gizmo.GizmoTypes.BOUNDING_SPHERE:
                    # Skin Bounding Volume Type
                    tags.append("SkinBoundingVolume")
                else:
                    # Collision type
                    tags.append("Collision")
                    if is_road_collider:
                        tags.append("Road")
                    if is_ground_collider:
                        tags.append("Ground")

                result["extensions"] = {
                    "ASOBO_tags": gltf2_io_extensions.Extension(name="ASOBO_tags",
                                                                extension={"tags": tags},
                                                                required=False)
                }

                mesh_extensions.append(result)

                node.children.remove(child)

            if node_extensions:
                node.extensions[AsoboGizmoObject.extension_name] = gltf2_io_extensions.Extension(
                    name=AsoboGizmoObject.extension_name,
                    extension={"gizmo_objects": node_extensions},
                    required=False
                )

            if mesh_extensions:
                node.mesh.extensions[AsoboGizmoObject.extension_name] = gltf2_io_extensions.Extension(
                    name=AsoboGizmoObject.extension_name,
                    extension={"gizmo_objects": mesh_extensions},
                    required=False
                )

            AsoboGizmoObject.export(node.children, blender_scene, export_settings)
