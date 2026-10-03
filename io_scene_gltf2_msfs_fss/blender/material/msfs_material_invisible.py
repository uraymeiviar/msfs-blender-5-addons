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

from ..utils.msfs_material_nodes_utils import (
    get_node_by_name,
    MSFS2024_ShaderNodes
)

from ..utils.msfs_material_utils import (
    MSFS2024_MaterialProperties,
    MSFS2024_MaterialUtilsUI
)
from .msfs_material import MSFS2024_Material


class MSFS2024_Invisible(MSFS2024_Material):

    attributes = [
        MSFS2024_MaterialProperties.BASECOLOR,

        MSFS2024_MaterialProperties.COLLISIONMATERIAL,
        MSFS2024_MaterialProperties.ROADCOLLISIONMATERIAL,
        MSFS2024_MaterialProperties.GROUNDCOLLISIONMATERIAL
    ]

    default_preview_color = (0.16, 0.34, 1, 0.2)
    preview_color_prop_name = "msfs_invisible_preview_color"

    def __init__(self, material, build_tree=False):

        super().__init__(material=material, build_tree=build_tree)

        if build_tree:
            self.set_default_properties(attributes=self.attributes)
            self.force_update_nodes()
            self.switch_to_blend_render()

    def force_update_nodes(self):
        preview_color = getattr(self.material, MSFS2024_Invisible.preview_color_prop_name)
        setattr(self.material, MSFS2024_Invisible.preview_color_prop_name, preview_color)

    def set_default_properties(self, attributes=None):
        super().set_default_properties(attributes=attributes)

    def custom_shader_tree(self):
        # We dont need to use the default shader tree because this is a simple colored material with transparency
        pass

    @staticmethod
    def draw_panel(layout, material):
        MSFS2024_Invisible.draw_parameters_panel(layout=layout, material=material)

    @staticmethod
    def draw_parameters_panel(layout, material):
        ## Base Color
        layout.prop(material, MSFS2024_Invisible.preview_color_prop_name)

        # region Gameplay Parameters
        MSFS2024_MaterialUtilsUI.draw_gameplay_panel(
            layout=layout,
            material=material
        )
        # endregion

# region Properties update
def update_color_preview(self, context):

    nodes = []
    if self.node_tree:
        nodes = self.node_tree.nodes

    if not nodes:
        return

    principled_bsdf_node = get_node_by_name(
        nodes, MSFS2024_ShaderNodes.PRINCIPLEDBSDF.value
    )
    if not principled_bsdf_node:
        return

    preview_color = getattr(self, MSFS2024_Invisible.preview_color_prop_name)
    principled_bsdf_node.inputs[0].default_value = preview_color
    principled_bsdf_node.inputs[4].default_value = preview_color[3]
# endregion

def register():

    preview_color_bpy_prop = bpy.props.FloatVectorProperty(
        name="Preview Color",
        description="Material preview color, not used In Game",
        subtype="COLOR",
        min=0.0,
        max=1.0,
        size=4,
        default=MSFS2024_Invisible.default_preview_color,
        precision=3,
        update=update_color_preview
    )
    setattr(bpy.types.Material, MSFS2024_Invisible.preview_color_prop_name, preview_color_bpy_prop)


def unregister():
    try:
        delattr(bpy.types.Material, MSFS2024_Invisible.preview_color_prop_name)
    except:
        pass
