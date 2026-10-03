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

from ..io.exp.export_settings import PerObjectTransformReset

def register():
    # region Objects
    bpy.types.Object.msfs_override_unique_id = bpy.props.BoolProperty(name='Override Unique ID', default=False)
    bpy.types.Object.msfs_unique_id = bpy.props.StringProperty(name='ID', default="")
    
    bpy.types.Object.msfs_export_transform = bpy.props.PointerProperty(name="Reset Transform", type=PerObjectTransformReset)
    # endregion
    
    # region Meshes
    bpy.types.Mesh.msfs_softbody = bpy.props.BoolProperty(name="Is SoftBody Mesh", default=False)
    # endregion
    
    # region Bones
    bpy.types.Bone.msfs_override_unique_id = bpy.props.BoolProperty(name='Override Unique ID', default=False)
    bpy.types.Bone.msfs_unique_id = bpy.props.StringProperty(name='ID', default="")

    bpy.types.Bone.msfs_facial_animation = bpy.props.BoolProperty(name='Enable Facial Animation', default=False)
    # endregion
    
    # region Actions
    bpy.types.Action.msfs_facial_animation = bpy.props.BoolProperty(name='Enable Facial Animation', default=False)
    # endregion
    
def unregister():
    try:
        del bpy.types.Object.msfs_override_unique_id
        del bpy.types.Object.msfs_unique_id
        del bpy.types.Object.msfs_collision_is_road_collider
        del bpy.types.Object.msfs_collision_is_ground_collider
        
        del bpy.types.Mesh.msfs_softbody
        
        del bpy.types.Bone.msfs_override_unique_id
        del bpy.types.Bone.msfs_unique_id
        del bpy.types.Bone.msfs_facial_animation
        
        del bpy.types.Action.msfs_facial_animation
    except:
        pass
