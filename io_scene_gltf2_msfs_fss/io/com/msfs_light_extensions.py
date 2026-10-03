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

import math
import bpy

from mathutils import Quaternion, Vector

from .extensions.light.asobo_street_light import AsoboStreetLight
from .extensions.light.asobo_advanced_light import AsoboAdvancedLight
from .extensions.light.asobo_skyportal_light import AsoboSkyPortalLight
from .extensions.light.asobo_macro_light import DeprecatedAsoboMacroLight


class MSFS2024_LightExtension:
    bl_options = {"UNDO"}

    extensions = [
        AsoboStreetLight,
        AsoboAdvancedLight,
        AsoboSkyPortalLight
    ]

    import_extensions = [
        AsoboStreetLight,
        AsoboAdvancedLight,
        AsoboSkyPortalLight,
        DeprecatedAsoboMacroLight,
    ]

    def __new__(cls, *args, **kwargs):
        raise RuntimeError(f"{cls} should not be instantiated")

    @classmethod
    def export(cls, gltf2_object, blender_object):
        if blender_object.type != "LIGHT":
            return

        # start quick dirty fix to solve rotation problem
        current_rotation_quat = Quaternion()
        if gltf2_object.rotation:
            current_rotation_quat = Quaternion(
                (
                    gltf2_object.rotation[3], 
                    gltf2_object.rotation[0], 
                    gltf2_object.rotation[1], 
                    gltf2_object.rotation[2]
                )
            )

        angle = math.radians(90.0 if bpy.app.version < (3, 2, 0) else 180)
        quat_a = Quaternion((1.0, 0.0, 0.0), angle)
        rotation = current_rotation_quat @ quat_a
        gltf2_object.rotation = [
            rotation.x, 
            rotation.y, 
            rotation.z, 
            rotation.w
        ]

        if gltf2_object.extensions is None:
            gltf2_object.extensions = {}

        for ext in cls.extensions:
            ext.export(gltf2_object, blender_object)

    @classmethod
    def import_light(cls, vnode, gltf2_object, blender_object):
        if not gltf2_object:
            return

        if not gltf2_object.extensions:
            return

        light_extensions = []
        for ext in cls.import_extensions:
            extension = gltf2_object.extensions.get(ext.extension_name)
            if extension:
                light_extensions.append(ext)

        if not light_extensions:
            return

        # Fix light rotation
        blender_object.rotation_mode = "QUATERNION"
        angle = math.radians(-90)
        # Create a rotation quaternion for the X-axis
        axis = Vector((1.0, 0.0, 0.0))
        quat_a = Quaternion(axis, angle)

        blender_object.rotation_quaternion @= quat_a

        if gltf2_object.extensions is None:
            gltf2_object.extensions = {}

        for ext in light_extensions:
            ext.from_extension(vnode, gltf2_object, blender_object)
