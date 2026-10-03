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

from enum import Enum

from .....blender.utils.msfs_material_utils import (
    MSFS2024_MaterialProperties, 
    MSFS2024_MaterialTypes
)

class MaterialCode(Enum):
    PORTHOLE = "Porthole"
    GEODECALFROSTED = "GeoDecalFrosted"
    PROPELLER = "Propeller"
    TREE = "Tree"
    VEGETATION = "Vegetation"
    
class AsoboMaterialCode:

    extension_name = "ASOBO_material_code"

    @staticmethod
    def from_dict(blender_material, gltf2_material, import_settings):
        extras = gltf2_material.extras
        if extras is None:
            return

        assert isinstance(extras, dict)
        extra = extras.get(AsoboMaterialCode.extension_name)
        if extra is None:
            return

        match extra:
            case MaterialCode.PORTHOLE.value:
                setattr(blender_material, MSFS2024_MaterialProperties.MATERIALTYPE.attribute_name(), MSFS2024_MaterialTypes.PORTHOLE.value)
            case MaterialCode.GEODECALFROSTED.value:
                setattr(blender_material, MSFS2024_MaterialProperties.MATERIALTYPE.attribute_name(), MSFS2024_MaterialTypes.GEODECALFROSTED.value)
            case MaterialCode.PROPELLER.value:
                setattr(blender_material, MSFS2024_MaterialProperties.MATERIALTYPE.attribute_name(), MSFS2024_MaterialTypes.PROPELLER.value)
            case MaterialCode.TREE.value:
                setattr(blender_material, MSFS2024_MaterialProperties.MATERIALTYPE.attribute_name(), MSFS2024_MaterialTypes.TREE.value)
            case MaterialCode.VEGETATION.value:
                setattr(blender_material, MSFS2024_MaterialProperties.MATERIALTYPE.attribute_name(), MSFS2024_MaterialTypes.VEGETATION.value)
            

    @staticmethod
    def to_extension(blender_material, gltf2_material, export_settings):
        result = ""
        
        match getattr(blender_material, MSFS2024_MaterialProperties.MATERIALTYPE.attribute_name()):
            case MSFS2024_MaterialTypes.PORTHOLE.value:
                result = MaterialCode.PORTHOLE.value
            case MSFS2024_MaterialTypes.PROPELLER.value:
                result = MaterialCode.PROPELLER.value
            case MSFS2024_MaterialTypes.TREE.value:
                result = MaterialCode.TREE.value
            case MSFS2024_MaterialTypes.VEGETATION.value:
                result = MaterialCode.VEGETATION.value

        if gltf2_material.extras is None:
            gltf2_material.extras = {}
        
        if result != "":
            gltf2_material.extras[AsoboMaterialCode.extension_name] = result
            