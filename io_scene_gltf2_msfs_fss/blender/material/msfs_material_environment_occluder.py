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

from ..utils.msfs_material_utils import (
    MSFS2024_MaterialProperties,
    MSFS2024_MaterialUtilsUI
)
from .msfs_material import MSFS2024_Material


class MSFS2024_Environment_Occluder(MSFS2024_Material):

    attributes = [
        MSFS2024_MaterialProperties.BASECOLOR
    ]

    def __init__(self, material, build_tree=False):
        super().__init__(material=material, build_tree=build_tree)
        if build_tree:
            self.set_default_properties(attributes=self.attributes)
            self.force_update_nodes()

    def custom_shader_tree(self):
        super().default_shader_tree()

    def set_default_properties(self, attributes=None):
        super().set_default_properties(attributes=attributes)
        setattr(self.material, MSFS2024_MaterialProperties.ALPHAMODE.attribute_name(), "BLEND")
        setattr(self.material, MSFS2024_MaterialProperties.NOCASTSHADOW.attribute_name(), True)

    @staticmethod
    def draw_panel(layout, material):
        MSFS2024_Environment_Occluder.draw_parameters_panel(layout=layout, material=material)

    @staticmethod
    def draw_parameters_panel(layout, material):
        ## Base Color
        MSFS2024_MaterialUtilsUI.draw_base_color_prop(
            layout=layout,
            material=material
        )
