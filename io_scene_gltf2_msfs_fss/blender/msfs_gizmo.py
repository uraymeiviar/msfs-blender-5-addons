from __future__ import annotations
from enum import Enum

import bpy
import bmesh
from mathutils import Vector
from dataclasses import dataclass

from _addons_common import geometry_node_utils

from io_scene_gltf2_msfs_fss.datafiles.asset_library import NodeGroupLibrary, MSFS2024CollisionInputs


class GizmoTypes(Enum):
    # Collisions
    BOX = (0, "box", "MSFS2024 Box Collision")
    SPHERE = (1, "sphere", "MSFS2024 Sphere Collision")
    CYLINDER = (2, "cylinder", "MSFS2024 Cylinder Collision")

    # Bounding Volumes
    BOUNDING_SPHERE = (3, "boundingSphere", "MSFS2024 Skin Bounding Volume")

    def __init__(self, index:int, identifier:str, default_obj_name:str):
        self.index = index
        self.identifier = identifier
        self.default_obj_name = default_obj_name
        

    @staticmethod
    def from_identifier(identifier: str) -> GizmoTypes | None:
        for gizmo_type in GizmoTypes:
            if gizmo_type.identifier == identifier:
                return gizmo_type
        return None

    @staticmethod
    def get_by_index(index: int) -> GizmoTypes | None:
        for gizmo_type in GizmoTypes:
            if gizmo_type.index == index:
                return gizmo_type
        return None


# region Gizmo Utils
def is_valid_gizmo_obj(obj:bpy.types.Object):
    if not obj.type == "CURVE":
        return False
    
    collision_modifier = get_collision_mod(obj)
    bounding_volume_modifier = get_bounding_volume_mod(obj)
    
    if not collision_modifier and not bounding_volume_modifier:
        return False
    
    return True

def get_collision_mod(
    obj: bpy.types.Object,
) -> bpy.types.Modifier | None:
    """
    Get the first valid collision modifier of an object.
    """

    return NodeGroupLibrary.COLLISIONS.get_modifier(obj)


def get_bounding_volume_mod(
    obj: bpy.types.Object,
) -> bpy.types.Modifier | None:
    """
    Get the first collision modifier of an object.
    """
    return NodeGroupLibrary.BOUNDING_VOLUME.get_modifier(obj)


@dataclass
class GizmoAttributes:
    gizmo_type: GizmoTypes
    is_road_collider: bool
    is_ground_collider: bool


def get_gizmo_attributes(obj: bpy.types.Object) -> GizmoAttributes | None:

    if not is_valid_gizmo_obj(obj):
        return None

    collision_modifier = get_collision_mod(obj)
    bounding_volume_modifier = get_bounding_volume_mod(obj)

    gizmo_type = None
    is_road_collider = False
    is_ground_collider = False

    if collision_modifier:
        modifier_type_index: int = geometry_node_utils.get_modifier_input(
            collision_modifier, MSFS2024CollisionInputs.TYPE.input_label
        )  # type: ignore
        gizmo_type = GizmoTypes.get_by_index(modifier_type_index)
        if gizmo_type is geometry_node_utils.NotFound:
            print(
                f"{obj.name} - Modifier {collision_modifier.name}: {MSFS2024CollisionInputs.TYPE.input_label} was not found!"
            )
            gizmo_type = None

        is_road_collider = geometry_node_utils.get_modifier_input(
            collision_modifier,
            MSFS2024CollisionInputs.ROAD_COLLIDER.input_label,
        )
        if is_road_collider is geometry_node_utils.NotFound:
            print(
                f"{obj.name} - Modifier {collision_modifier.name}: {MSFS2024CollisionInputs.ROAD_COLLIDER.input_label} was not found!"
            )
            is_road_collider = False
        is_ground_collider = geometry_node_utils.get_modifier_input(
            collision_modifier,
            MSFS2024CollisionInputs.GROUND_COLLIDER.input_label,
        )
        if is_ground_collider is geometry_node_utils.NotFound:
            print(
                f"{obj.name} - Modifier {collision_modifier.name}: {MSFS2024CollisionInputs.GROUND_COLLIDER.input_label} was not found!"
            )
            is_ground_collider = False
    elif bounding_volume_modifier:
        gizmo_type = GizmoTypes.BOUNDING_SPHERE

    if not gizmo_type:
        raise TypeError(f"{obj.name} Gizmo Type was not found!")

    return GizmoAttributes(gizmo_type, is_road_collider, is_ground_collider)

def set_collision_type(collision_mod: bpy.types.Modifier, gizmo_type: GizmoTypes):

    inputs: MSFS2024CollisionInputs = NodeGroupLibrary.COLLISIONS.node_group_inputs
    geometry_node_utils.set_modifier_input(
        collision_mod, inputs.TYPE.input_label, gizmo_type.index
    )

def set_is_road_collider(collision_mod: bpy.types.Modifier, value: bool):

    inputs: MSFS2024CollisionInputs = NodeGroupLibrary.COLLISIONS.node_group_inputs
    geometry_node_utils.set_modifier_input(
        collision_mod, inputs.ROAD_COLLIDER.input_label, value
    )

def set_is_ground_collider(collision_mod: bpy.types.Modifier, value: bool):

    inputs: MSFS2024CollisionInputs = NodeGroupLibrary.COLLISIONS.node_group_inputs
    geometry_node_utils.set_modifier_input(
        collision_mod, inputs.GROUND_COLLIDER.input_label, value
    )

def create_gizmo(gizmo_type: GizmoTypes) -> bpy.types.Object:
    """
    Create a gizmo object (curve with a geometry node modifier)

    Returns:
        bpy.types.Object: The created collision object.
    """
    obj_name = gizmo_type.default_obj_name
    node_group_asset = NodeGroupLibrary.COLLISIONS

    if gizmo_type == GizmoTypes.BOUNDING_SPHERE:
        node_group_asset = NodeGroupLibrary.BOUNDING_VOLUME

    curve_data = bpy.data.curves.new(name=node_group_asset.label_name, type="CURVE")
    gizmo_obj = bpy.data.objects.new(obj_name, curve_data)

    modifier = node_group_asset.add_modifier(object=gizmo_obj)

    if node_group_asset == NodeGroupLibrary.COLLISIONS:
        set_collision_type(modifier, gizmo_type)
    gizmo_obj.name = obj_name

    return gizmo_obj


def _set_gizmo_scale(gizmo_obj: bpy.types.Object, scale: list[float]):
    # Set minimum scale value
    for i, s in enumerate(scale):
        if s <= 0:
            scale[i] = 0.01

    collision_modifier = get_collision_mod(gizmo_obj)
    bounding_volume_modifier = get_bounding_volume_mod(gizmo_obj)

    if bounding_volume_modifier:
        max_value = max(scale)
        gizmo_obj.scale = [max_value] * 3
    elif collision_modifier:
        gizmo_type = geometry_node_utils.get_modifier_input(
            collision_modifier, MSFS2024CollisionInputs.TYPE.value
        )
        if gizmo_type is geometry_node_utils.NotFound:
            print(
                f"{gizmo_obj.name} - Modifier {collision_modifier.name}: {MSFS2024CollisionInputs.TYPE.input_label} was not found!"
            )
            return
        if gizmo_type == GizmoTypes.BOX.index:
            gizmo_obj.scale = scale
        elif gizmo_type == GizmoTypes.SPHERE.index:
            max_value = max(scale)
            gizmo_obj.scale = [max_value] * 3
        elif gizmo_type == GizmoTypes.CYLINDER.index:
            max_value = max(scale[:2])
            gizmo_obj.scale = [max_value, max_value, scale[2]]


def _set_gizmo_transform(
    gizmo_obj: bpy.types.Object,
    center: Vector,
    scale: Vector,
    parent: None | bpy.types.Object = None,
):

    gizmo_obj.location = center
    _set_gizmo_scale(gizmo_obj, scale)
    # set parent while preserving transforms
    bpy.context.view_layer.update()
    if parent:
        gizmo_obj.parent = parent
        gizmo_obj.matrix_parent_inverse = parent.matrix_world.inverted()


def add_gizmo_under_obj(gizmo_type: GizmoTypes, parent: bpy.types.Object):
    """Create a gizmo object that fits provided parent.

    Args:
        context: Current Context.
        parent: Mesh to parent collisio.
    """
    if not parent.type == "MESH":
        return

    dummy = create_gizmo(gizmo_type)

    # Link to same collections
    for collection in parent.users_collection:
        try:
            collection.objects.link(dummy)
        except:
            pass

    center = [0, 0, 0]
    scale = [1, 1, 1]

    verts_world_pos = _get_selected_verts_world_pos(parent)
    if verts_world_pos:
        center, scale = _get_verts_bbox(verts_world_pos)

    _set_gizmo_transform(dummy, center, scale, parent)
    return dummy


def add_gizmo(gizmo_type: GizmoTypes):

    collision = create_gizmo(gizmo_type)
    try:
        bpy.context.collection.objects.link(collision)
    except:
        pass
    return collision


def _get_selected_verts_world_pos(obj: bpy.types.Object) -> list[Vector]:
    """
    Get world positions of selected vertices.
    """
    if not obj.type == "MESH":
        return []

    if bpy.context.mode == "EDIT_MESH":
        # force refresh of face selection
        obj.update_from_editmode()
        # Calculate bounding of selection
        mesh = obj.data
        bm = bmesh.new()

        bm.from_mesh(mesh, face_normals=False, vertex_normals=False)
        verts_world_pos = []

        for vert in bm.verts:
            if not vert.select:
                continue
            world_pos = obj.matrix_world @ vert.co
            verts_world_pos.append(world_pos)

        bm.free()
        return verts_world_pos
    elif bpy.context.mode == "OBJECT":
        # Calculate bounding of entire mesh
        mesh = obj.data
        bm = bmesh.new()
        bm.from_mesh(mesh, face_normals=False, vertex_normals=False)
        verts_world_pos = []
        for vert in bm.verts:
            world_pos = obj.matrix_world @ vert.co
            verts_world_pos.append(world_pos)
        bm.free()
        return verts_world_pos
    else:
        return []


def _get_verts_bbox(verts_world_pos: list[Vector]) -> tuple[Vector, Vector]:
    """Calculate world bounding box of vertices.

    Args:
        verts_world_pos: vertices world position

    Returns:
        Tuple containing bounding box center and its scale.
    """
    # Calculate the bounding box of the selected faces using world coordinates
    min_coord = Vector((float("inf"), float("inf"), float("inf")))
    max_coord = Vector((float("-inf"), float("-inf"), float("-inf")))

    for world_pos in verts_world_pos:
        min_coord = Vector(
            (
                min(min_coord.x, world_pos.x),
                min(min_coord.y, world_pos.y),
                min(min_coord.z, world_pos.z),
            )
        )
        max_coord = Vector(
            (
                max(max_coord.x, world_pos.x),
                max(max_coord.y, world_pos.y),
                max(max_coord.z, world_pos.z),
            )
        )

    center = (min_coord + max_coord) / 2
    scale = (max_coord - min_coord) / 2

    return center, scale


# endregion

class MSFS2024AddGizmo(bpy.types.Operator):
    bl_idname = "msfs2024.add_gizmo"
    bl_label = "Add MSFS2024 Gizmo"
    bl_options = {"REGISTER", "UNDO"}

    gizmo_type: bpy.props.StringProperty() # type: ignore

    def execute(self, context):
        parent = context.view_layer.objects.active
        gizmo_obj = None
        gizmo_type = GizmoTypes.from_identifier(self.gizmo_type)
        if not gizmo_type:
            print("Invalid Gizmo type")
            return {"CANCELLED"}
        
        if parent and parent.select_get() and parent.type == "MESH":
            
            gizmo_obj = add_gizmo_under_obj(gizmo_type, parent)
        else:
            gizmo_obj = add_gizmo(gizmo_type)
        if not gizmo_obj:
            return {"FINISHED"}

        if bpy.context.mode == "OBJECT":
            for obj in context.view_layer.objects:
                obj.select_set(False)
            gizmo_obj.select_set(True)
            context.view_layer.objects.active = gizmo_obj
        return {"FINISHED"}


class MSFS2024CollisionAddMenu(bpy.types.Menu):
    bl_idname = "VIEW3D_MT_msfs_collision2024_add_menu"
    bl_label = "Microsoft Flight Simulator 2024 Collisions"

    def draw(self, context):
        self.layout.operator(MSFS2024AddGizmo.bl_idname, text="Sphere Collision", icon="MESH_UVSPHERE").gizmo_type = GizmoTypes.SPHERE.identifier
        self.layout.operator(MSFS2024AddGizmo.bl_idname, text="Box Collision", icon="MESH_CUBE").gizmo_type = GizmoTypes.BOX.identifier
        self.layout.operator(MSFS2024AddGizmo.bl_idname, text="Cylinder Collision", icon="MESH_CYLINDER").gizmo_type = GizmoTypes.CYLINDER.identifier

class MSFS2024BoundingVolumeAddMenu(bpy.types.Menu):
    bl_idname = "VIEW3D_MT_msfs_boundingvolume2024_add_menu"
    bl_label = "Microsoft Flight Simulator 2024 Bounding Volumes"

    def draw(self, context):
        self.layout.operator(MSFS2024AddGizmo.bl_idname, text="Bounding Volume Sphere", icon="MESH_UVSPHERE").gizmo_type = GizmoTypes.BOUNDING_SPHERE.identifier


#####################################################
def draw_collision_menu(self, context):
    self.layout.menu(menu=MSFS2024CollisionAddMenu.bl_idname, icon="SHADING_BBOX")

def draw_bounding_volume_menu(self, context):
    self.layout.menu(menu=MSFS2024BoundingVolumeAddMenu.bl_idname, icon="SHADING_BBOX")

def register():
    bpy.types.VIEW3D_MT_add.append(draw_collision_menu)
    bpy.types.VIEW3D_MT_mesh_add.append(draw_collision_menu)
    bpy.types.VIEW3D_MT_add.append(draw_bounding_volume_menu)
    bpy.types.VIEW3D_MT_mesh_add.append(draw_bounding_volume_menu)


def unregister():
    bpy.types.VIEW3D_MT_add.remove(draw_collision_menu)
    bpy.types.VIEW3D_MT_mesh_add.remove(draw_collision_menu)
    
    bpy.types.VIEW3D_MT_add.remove(draw_bounding_volume_menu)
    bpy.types.VIEW3D_MT_mesh_add.remove(draw_bounding_volume_menu)
