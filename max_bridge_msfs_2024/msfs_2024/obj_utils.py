from __future__ import annotations
import bpy

from mathutils import Vector
from max_bridge_msfs_2024 import logger
from max_bridge_msfs_2024.common import obj_utils
from max_bridge_msfs_2024.common.usd_properties import *
from max_bridge_msfs_2024.msfs_2024.msfs_properties import *

from io_scene_gltf2_msfs_fss.blender import msfs_lights
from io_scene_gltf2_msfs_fss.blender import msfs_gizmo

logging = logger.getLogger()
def _create_msfs2024_light(
    obj_class: MSFS2024_CustomObjectClasses, properties: dict
) -> bpy.types.Light | None:
    """Create a msfs2024 light

    Args:
        dummy: _description_
        properties: _description_
    """
    light_type = msfs_lights.MSFS2024LightType.from_identifier(obj_class.blender_class_name)
    if light_type is None:
        logging.error(f"Light type {obj_class.blender_class_name} is unsupported")
        return None
    light = msfs_lights.create_light_object(light_type)
    msfs_light_properties = getattr(light.data, "msfs_light_properties")
    
    for prop in obj_class.class_properties:
        prop: CustomClassPropertiesDef
        prop_name = prop.name
        try:
            value = properties[prop_name]
            logging.info(f"Set prop {prop.blender_name} to {value}")
        except KeyError:
            logging.error(f"Can't set prop {prop.blender_name} to {value}")
            continue
        prop_blender_name = prop.blender_name
        if prop_blender_name == NOTIMPLEMENTED:
            continue

        if prop.prop_type == PropertyTypes.COLOR:

            value = value[:3]  # exclude alpha component

        setattr(msfs_light_properties, prop_blender_name, value)
    
    return light

def _create_msfs2024_collision(
    dummy:bpy.types.Object,
    obj_class: MSFS2024_CustomObjectClasses, properties: dict
) -> bpy.types.Object | None:
    """Create a msfs2024 collision. 
    Set dummy transforms to prepare it to be replaced by gizmo object later.
    """
    gizmo_type = msfs_gizmo.GizmoTypes.from_identifier(obj_class.blender_class_name)
    if gizmo_type is None:
        logging.error(f"Collision type {obj_class.blender_class_name} is unsupported")
        return None
    gizmo = msfs_gizmo.create_gizmo(gizmo_type)

    # Unparent children before setting dummy transforms
    children = dummy.children
    for child in children:
        obj_utils.set_parent_keep_transform(child, None)

    # Completely ignore node scale here, exporting a scaled collision in 3dsMax doesnt work.
    if obj_class == MSFS2024_CustomObjectClasses.BOX_COLLISION:

        class_props = obj_class.class_properties
        class_props: MSFS2024_BoxCollision

        scale_x = properties.get(class_props.SCALE_X.name,class_props.SCALE_X.blender_default)
        scale_y = properties.get(class_props.SCALE_Y.name,class_props.SCALE_Y.blender_default)
        scale_z = properties.get(class_props.SCALE_Z.name,class_props.SCALE_Z.blender_default)

        # Offset pivot since 3dsMax pivot is as the base of the collision instead at the center in blender.
        offset = Vector((0,0,scale_z))
        obj_utils.offset_object_along_local_axis(dummy,offset)

        # we set collision scale directly on dummy since it will be replaced by collision later while retaining dummy scale values
        dummy.scale[0] = scale_x
        dummy.scale[1] = scale_y
        dummy.scale[2] = scale_z

    elif obj_class == MSFS2024_CustomObjectClasses.SPHERE_COLLISION or obj_class == MSFS2024_CustomObjectClasses.SPHERE_BOUNDING_COLLISION :
        class_props = obj_class.class_properties 
        class_props: MSFS2024_SphereCollision 

        scale = properties.get(class_props.SCALE.name,class_props.SCALE.blender_default)

        # we set collision scale directly on dummy since it will be replaced by collision later while retaining dummy scale values
        dummy.scale = [scale, scale, scale]

    elif obj_class == MSFS2024_CustomObjectClasses.CYLINDER_COLLISION:

        class_props = obj_class.class_properties
        class_props: MSFS2024_CylinderCollision

        scale_xy = properties.get(class_props.SCALE_XY.name,class_props.SCALE_XY.blender_default)
        scale_z = properties.get(class_props.SCALE_Z.name,class_props.SCALE_Z.blender_default)

        # Offset pivot since 3dsMax pivot is as the base of the collision instead at the center in blender.
        offset = Vector((0,0,scale_z))

        obj_utils.offset_object_along_local_axis(dummy,offset)

        # we set collision scale directly on dummy since it will be replaced by collision later while retaining dummy scale values
        dummy.scale[0] = scale_xy
        dummy.scale[1] = scale_xy
        dummy.scale[2] = scale_z

    if obj_class.class_properties in COLLISIONS_CLASS_PROPERTIES_DEF:

        is_road = properties.get(
            class_props.IS_ROAD_COLLIDER.name,
            class_props.IS_ROAD_COLLIDER.blender_default,
        )
        is_ground = properties.get(
            class_props.IS_GROUND_COLLIDER.name,
            class_props.IS_ROAD_COLLIDER.blender_default,
        )
        collision_modifier = msfs_gizmo.get_collision_mod(gizmo)
        if collision_modifier:
            msfs_gizmo.set_is_road_collider(collision_modifier, is_road)
            msfs_gizmo.set_is_ground_collider(collision_modifier, is_ground)

    bpy.context.view_layer.update()
    
    # Reattach children
    for child in children:
        obj_utils.set_parent_keep_transform(child, dummy)

    return gizmo

def create_msfs2024_object(dummy:bpy.types.Object, type:str, properties:dict) -> bpy.types.Object | None:

    custom_object_class = None
    for obj_class in MSFS2024_CustomObjectClasses:
        if type == obj_class.name:
            custom_object_class = obj_class
            break
            
    if custom_object_class.class_properties in LIGHTS_CLASS_PROPERTIES_DEFS:
        logging.info(f"Create MSFS light {custom_object_class.blender_class_name}")
        light = _create_msfs2024_light(custom_object_class, properties)
        if not light:
            return None
        light = obj_utils.replace_obj_by(dummy, light, transform=True, delete=True)
        return light

    elif custom_object_class.class_properties in COLLISIONS_CLASS_PROPERTIES_DEF:
        collision = _create_msfs2024_collision(dummy,custom_object_class, properties)
        logging.info(f"Create MSFS Collision {custom_object_class.blender_class_name}")
        if not collision:
            return None
        collision = obj_utils.replace_obj_by(dummy, collision, transform=True, delete=True)
        return collision
