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
from _addons_common.reload import reload_addon
reload_addon(__name__)

import bpy

bl_info = {
    "name": "Microsoft Flight Simulator 2020 + 2024: glTF Extension (FSS)",
    "module_name": "io_scene_gltf2_msfs_fss",
    "author": "Asobo Studio (ykhodja and mrichecoeur), FlightSimStudio",
    "description": "Toolkit to export/import GLTF Models for Microsoft Flight Simulator 2024 and 2020 (per scene export target)",
    "location": "View 3d Tools and Menus, Objects properties, Material properties and Light properties",
    "blender": (3, 3, 0),
    "version": (7, 4, 3),
    "category": "Import-Export",
    "doc_url": "https://docs.flightsimulator.com/msfs2024/html/3_Models_And_Textures/Plugins/Blender_Plugin/Blender_Plugin_Properties.htm"
}


class MSFS2024AddonPrefs(bpy.types.AddonPreferences):

    bl_idname = __name__

    make_relative_on_save: bpy.props.BoolProperty(
        name="Make Paths Relative On Save",
        description=(
            "Save external files (textures, linked libraries, etc.) with \n"
            "relative paths instead of absolute ones, so the .blend can \n"
            "be shared without missing file issues."
        ),
        default=True,
    )  # type: ignore

    # Unified add-on: project-wide calibration of the MSFS 2020 <-> MSFS 2024 emissive conversion
    msfs2020_emissive_reference: bpy.props.FloatProperty(
        name="MSFS 2020 Emissive Reference",
        description=("Emission brightness (cd/m²) of MSFS 2020 emissive strength 1.0, for scenes that do not set "
                     "their own: used when MSFS 2020 materials are migrated (the scene then keeps the value) and "
                     "by MSFS 2020 exports of such scenes"),
        default=1000.0,
        min=0.001,
        soft_max=20000.0,
    )  # type: ignore

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "make_relative_on_save")
        layout.prop(self, "msfs2020_emissive_reference")

def get_addon_prefs():
    addon_name = __package__
    return bpy.context.preferences.addons[addon_name].preferences

def get_version_string():
    return str(bl_info['version'][0]) + '.' + str(bl_info['version'][1]) + '.' + str(bl_info['version'][2])

# endregion

# region ######################### REGISTRATION #################################
from _addons_common.registration import Registration

RG = Registration(
    file=__file__,
    package=__package__
)


def _delayed_init():

    # Convert current file in case addon is enabled after blender opening
    from io_scene_gltf2_msfs_fss.blender import scene_loading

    scene_loading.prepare_scenes()

    return None  # Don't repeat


def register():
    try:
        bpy.utils.register_class(MSFS2024AddonPrefs)
    except:
        pass
    RG.register()
    # After the MSFS 2024 registration: only adds what MSFS 2024 does not define
    from . import msfs2020_target
    msfs2020_target.register_target()
    # We can't access bpy.data during addon registering, so we need to wait
    bpy.app.timers.register(_delayed_init, first_interval=0.1)

def unregister():
    try:
        bpy.utils.unregister_class(MSFS2024AddonPrefs)
    except:
        pass
    from . import msfs2020_target
    msfs2020_target.unregister_target()
    RG.unregister()

# endregion

# region ######################### IMPORT #################################
from .io.imp.msfs_import import Import
from .ui.imp import import_panel

# region importer panel blender < 4.2

def register_panel():
    """
    Entry point for the glTF add-on (blender < 4.2) to register or unregister
    the importer panel.
    """
    try:
        bpy.utils.register_class(import_panel.MSFS2024_PT_importer_panel)
    except Exception:
        pass

    return unregister_panel

def unregister_panel():
    try:
        bpy.utils.unregister_class(import_panel.MSFS2024_PT_importer_panel)
    except Exception:
        pass

# endregion

# region importer panel blender >= 4.2
def draw_import(context: bpy.types.Context, layout: bpy.types.UILayout):
    """
    Draws the importer panel for the glTF add-on (Blender ≥ 4.2).
    """
    header, body = layout.panel("MSFS2024_PT_importer_panel", default_closed=False)
    header.use_property_split = False
    if header:
        import_panel.draw_importer_header(context, header)
    if body:
        import_panel.draw_importer_panel(context, body)
# enregion

class glTF2ImportUserExtension(Import):
    def __init__(self):
        super().__init__()

# endregion

# region ######################### EXPORT #################################
from .io.exp.gltf_hooks import Export


class _ExportMSFS2024(Export):
    def gather_tree_filter_tag_hook(self, vtree, khronos_export_settings):
        # Unified add-on: skip MSFS 2020-only objects (e.g. legacy gizmo empties)
        from .msfs2020_target import TARGET_MSFS2024, filter_export_tree
        filter_export_tree(vtree, TARGET_MSFS2024)


class glTF2ExportUserExtension:
    """
    Khronos creates one instance per export and looks hooks up with getattr(), so the instance
    forwards to the MSFS 2024 or the MSFS 2020 hook implementation according to the scene's
    export target.
    """

    def __init__(self):
        from .msfs2020_target import is_msfs2020_target
        from . import migration
        # Scripts can export before the load handlers ran: never export unmigrated MSFS 2020 materials
        migration.migrate_materials(bpy.context.scene)
        if is_msfs2020_target(bpy.context.scene):
            from ._msfs2020.io.msfs_export import Export as Export2020
            self._impl = Export2020()
        else:
            self._impl = _ExportMSFS2024()

    def __getattr__(self, name):
        # Only called for attributes not found on the dispatcher itself
        impl = self.__dict__.get("_impl")
        if impl is None:
            raise AttributeError(name)
        return getattr(impl, name)
# endregion
