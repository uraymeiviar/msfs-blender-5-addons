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

from ..utils.msfs_material_utils import (
    MSFS2024_MaterialProperties,
    MSFS2024_MaterialUtilsUI,
    MSFS2024_MaterialTypes
)

from .msfs_material_anisotropic import MSFS2024_Anisotropic
from .msfs_material_clearcoat import MSFS2024_Clearcoat
from .msfs_material_environment_occluder import MSFS2024_Environment_Occluder
from .msfs_material_fake_terrain import MSFS2024_Fake_Terrain
from .msfs_material_fresnel_fade import MSFS2024_Fresnel_Fade
from .msfs_material_geo_decal import MSFS2024_Geo_Decal
from .msfs_material_geo_decal_blendmasked import MSFS2024_Geo_Decal_BlendMasked
from .msfs_material_geo_decal_frosted import MSFS2024_Geo_Decal_Frosted
from .msfs_material_ghost import MSFS2024_Ghost
from .msfs_material_glass import MSFS2024_Glass
from .msfs_material_hair import MSFS2024_Hair
from .msfs_material_invisible import MSFS2024_Invisible
from .msfs_material_parallax import MSFS2024_Parallax
from .msfs_material_porthole import MSFS2024_Porthole
from .msfs_material_propeller import MSFS2024_Propeller
from .msfs_material_sail import MSFS2024_Sail
from .msfs_material_sss import MSFS2024_SSS
from .msfs_material_standard import MSFS2024_Standard
from .msfs_material_tree import MSFS2024_Tree
from .msfs_material_vegetation import MSFS2024_Vegetation
from .msfs_material_windshield import MSFS2024_Windshield
from .msfs_material_tire import MSFS2024_Tire


class MSFS2024_PT_Material(bpy.types.Panel):
    bl_label = "MSFS2024 Material Parameters"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "material"

    @classmethod
    def poll(cls, context):
        return context.active_object.active_material is not None

    def draw(self, context):
        layout = self.layout
        material = context.active_object.active_material

        # If there is no active material we can cut the draw
        if not material:
            return

        ## Material Types
        MSFS2024_MaterialUtilsUI.draw_prop(
            layout=layout,
            material=material,
            prop=MSFS2024_MaterialProperties.MATERIALTYPE.attribute_name()
        )

        # If we don't have any material type set we can cut the draw
        if getattr(material, MSFS2024_MaterialProperties.MATERIALTYPE.attribute_name()) == "NONE":
            return

        match getattr(material, MSFS2024_MaterialProperties.MATERIALTYPE.attribute_name()):
            case MSFS2024_MaterialTypes.STANDARD.value:
                MSFS2024_Standard.draw_panel(layout=layout, material=material)
            case MSFS2024_MaterialTypes.DECAL.value:
                MSFS2024_Geo_Decal.draw_panel(layout=layout, material=material)
            case MSFS2024_MaterialTypes.WINDSHIELD.value:
                MSFS2024_Windshield.draw_panel(layout=layout, material=material)
            case MSFS2024_MaterialTypes.PORTHOLE.value:
                MSFS2024_Porthole.draw_panel(layout=layout, material=material)
            case MSFS2024_MaterialTypes.GLASS.value:
                MSFS2024_Glass.draw_panel(layout=layout, material=material)
            case MSFS2024_MaterialTypes.GEODECALFROSTED.value:
                MSFS2024_Geo_Decal_Frosted.draw_panel(layout=layout, material=material)
            case MSFS2024_MaterialTypes.GEODECALBLENDMASKED.value:
                MSFS2024_Geo_Decal_BlendMasked.draw_panel(layout=layout, material=material)
            case MSFS2024_MaterialTypes.CLEARCOAT.value:
                MSFS2024_Clearcoat.draw_panel(layout=layout, material=material)
            case MSFS2024_MaterialTypes.PARALLAXWINDOW.value:
                MSFS2024_Parallax.draw_panel(layout=layout, material=material)
            case MSFS2024_MaterialTypes.ANISOTROPIC.value:
                MSFS2024_Anisotropic.draw_panel(layout=layout, material=material)
            case MSFS2024_MaterialTypes.HAIR.value:
                MSFS2024_Hair.draw_panel(layout=layout, material=material)
            case MSFS2024_MaterialTypes.SUBSURFACESCATTERING.value:
                MSFS2024_SSS.draw_panel(layout=layout, material=material)
            case MSFS2024_MaterialTypes.INVISIBLE.value:
                MSFS2024_Invisible.draw_panel(layout=layout, material=material)
            case MSFS2024_MaterialTypes.FAKETERRAIN.value:
                MSFS2024_Fake_Terrain.draw_panel(layout=layout, material=material)
            case MSFS2024_MaterialTypes.FRESNELFADE.value:
                MSFS2024_Fresnel_Fade.draw_panel(layout=layout, material=material)
            case MSFS2024_MaterialTypes.ENVIRONMENTOCCLUDER.value:
                MSFS2024_Environment_Occluder.draw_panel(layout=layout, material=material)
            case MSFS2024_MaterialTypes.GHOST.value:
                MSFS2024_Ghost.draw_panel(layout=layout, material=material)
            case MSFS2024_MaterialTypes.SAIL.value:
                MSFS2024_Sail.draw_panel(layout=layout, material=material)
            case MSFS2024_MaterialTypes.PROPELLER.value:
                MSFS2024_Propeller.draw_panel(layout=layout, material=material)
            case MSFS2024_MaterialTypes.TREE.value:
                MSFS2024_Tree.draw_panel(layout=layout, material=material)
            case MSFS2024_MaterialTypes.VEGETATION.value:
                MSFS2024_Vegetation.draw_panel(layout=layout, material=material)
            case MSFS2024_MaterialTypes.TIRE.value:
                MSFS2024_Tire.draw_panel(layout=layout, material=material)
