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


from ..com.extensions.material.asobo_material_invisible import AsoboMaterialInvisible
from ..com.extensions.material.asobo_tags import AsoboTag, AsoboTags


class MSFS2024_ImportUtils:

    @staticmethod
    def is_collision_prim(prim,gltf)->bool:
        """Check if MeshPrimitive is a collision.

        Args:
            prim: MeshPrimitive.
            gltf: gltf importer object.

        Returns:
            True if it is a collision prim, False otherwise..
        """
        mat_index = getattr(prim, "material", None)
        if mat_index is None:
            return False
        mat = gltf.data.materials[prim.material]
        extensions = getattr(mat, "extensions", None)
        if not extensions:
            return False
        asobo_tags = extensions.get(AsoboTags.extension_name)
        asobo_tag_invisible = extensions.get(
            AsoboMaterialInvisible.extension_name
        )

        if not asobo_tags or not asobo_tag_invisible:
            return False

        tags = asobo_tags.get("tags")
        if not tags:
            return False

        if AsoboTag.COLLISION.value in tags:
            return True
