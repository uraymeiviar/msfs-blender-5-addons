# Copyright 2026 FlightSimStudio
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

"""
Behaviour changes to the bundled Khronos glTF exporter, applied only while the MSFS extension is
enabled, so exports match the FSS production pipeline (Blender 3.6 with an edited Khronos copy).
Bundled add-ons cannot be edited on Blender 4.2+, so they are applied at runtime instead.
"""

import importlib

import bpy

# (module, attribute, original) for every applied patch, restored by unregister()
_patched = []


def _msfs_extension_enabled() -> bool:
    # Unified add-on: these are MSFS 2020 pipeline patches, MSFS 2024 exports keep Khronos behaviour
    from ...msfs2020_target import is_msfs2020_target
    scene = bpy.context.scene
    if not is_msfs2020_target(scene):
        return False
    settings = getattr(scene, "msfs_exporter_settings", None)
    return bool(settings and settings.enable_msfs_extension)


def _import_first(*names):
    for name in names:
        try:
            return importlib.import_module(name)
        except ImportError:
            continue
    return None


def _patch(owner, attribute, make_wrapper):
    original = getattr(owner, attribute)
    setattr(owner, attribute, make_wrapper(original))
    _patched.append((owner, attribute, original))


# region Neutral bone
def _patch_neutral_bone():
    """
    No neutral bone for skinned vertices without bone weights.

    Khronos binds vertices that have no bone influence to an extra "neutral_bone" joint it appends
    to the skin. The FSS production exporter disabled that ("compatibility fix for msfs" in
    gltf2_blender_gather_primitives_extract.py).
    """
    module = _import_first(
        "io_scene_gltf2.blender.exp.primitive_extract",                      # Blender 4.5+
        "io_scene_gltf2.blender.exp.gltf2_blender_gather_primitives_extract",  # Blender 3.6 .. 4.4
    )
    creator = getattr(module, "PrimitiveCreator", None)
    if creator is None or not hasattr(creator, "_PrimitiveCreator__get_bone_data"):
        print("[MSFS2020] Khronos PrimitiveCreator not found, neutral bone patch not applied")
        return

    def make_wrapper(original):
        def get_bone_data(self):
            original(self)
            if _msfs_extension_enabled():
                self.need_neutral_bone = False
        return get_bone_data

    _patch(creator, "_PrimitiveCreator__get_bone_data", make_wrapper)
# endregion


# region Base color texture
def _patch_base_color_texture():
    """
    The base color texture of an MSFS material comes from msfs_base_color_texture only.

    The add-on's node tree is a viewport preview: detail / blend maps are mixed into the Principled
    "Base Color" and "Alpha" inputs through Mix and Math nodes. Khronos 4.5+ searches through those
    nodes and exports the first image it meets (e.g. the windshield detail map) as baseColorTexture,
    which also renames the real detail map image (GLASS_COMP-1.png). Khronos 3.6 (FSS production)
    stopped at those nodes. With an empty MSFS base color slot, report no base color texture.
    """
    module = _import_first("io_scene_gltf2.blender.exp.material.pbr_metallic_roughness")  # Blender 4.5+
    attribute = "__gather_base_color_texture"  # module level: no name mangling
    if module is None or not hasattr(module, attribute):
        return  # older Khronos layouts do not search through mix nodes

    def make_wrapper(original):
        def gather_base_color_texture(material, export_settings):
            blender_material = material.get_used_material() if hasattr(material, "get_used_material") else material
            if (_msfs_extension_enabled()
                    and getattr(blender_material, "msfs_material_type", "NONE") != "NONE"
                    and getattr(blender_material, "msfs_base_color_texture", None) is None):
                return None, {}, {}, None
            return original(material, export_settings)
        return gather_base_color_texture

    _patch(module, attribute, make_wrapper)
# endregion


def register():
    if _patched:
        return
    _patch_neutral_bone()
    _patch_base_color_texture()


def unregister():
    while _patched:
        owner, attribute, original = _patched.pop()
        setattr(owner, attribute, original)
