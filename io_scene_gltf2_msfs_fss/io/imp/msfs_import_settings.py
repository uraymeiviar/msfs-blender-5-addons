# glTF-Blender-IO-MSFS2024
# Copyright 2018-2021 The glTF-Blender-IO authors
# Copyright 2022 The glTF-Blender-IO-MSFS2024 authors
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

class DirItem(bpy.types.PropertyGroup):
    path: bpy.props.StringProperty(
        name="Folder Path",
        description="Path to the folder"
    )

class MSFS2024_ImporterSettings(bpy.types.PropertyGroup):

    register_order = 1 #After DirItem register
    #region MSFS2024 Parameters
    enable_msfs_extension: bpy.props.BoolProperty(
        name="Use Microsoft Flight Simulator 2024 Extensions",
        description="Enable Microsoft Flight Simulator 2024 Extensions",
        default=True,
    ) # type: ignore

    # Additionnal texture directory
    additionnal_texture_dirs: bpy.props.CollectionProperty(
        type = DirItem,
        name="Additionnal Texture Dirs",
        description = ("Additionnal directories to parse for texture paths."
                       "Especially usefull when GLTF references textures " 
                       "used in an external package.")
    ) # type: ignore

    active_tex_dir_index: bpy.props.IntProperty(name="",
                                                default=0)# type: ignore
    #endregion

    #region Material
    import_materials: bpy.props.BoolProperty(
        name="Materials",
        description="Import materials",
        default=True,
    ) # type: ignore

    import_collisions: bpy.props.BoolProperty(
        name="Collisions",
        description="Import collisions",
        default=True,
    ) # type: ignore
    #endregion

def register():
    bpy.types.Scene.msfs_importer_settings = bpy.props.PointerProperty(type=MSFS2024_ImporterSettings)
