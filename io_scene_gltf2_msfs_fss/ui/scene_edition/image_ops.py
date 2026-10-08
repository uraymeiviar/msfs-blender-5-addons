from __future__ import annotations
from typing import TYPE_CHECKING

from pathlib import Path

import bpy
import os
import re

from _addons_common import p4
from _addons_common.ui import window
from _addons_common.ui.tree_widget.manager import TreeManager
from _addons_common.ui.tree_widget.view import UL_TreeView
from _addons_common.ui.tree_widget.view_ope import  TREEVIEW_OT_SelectAllItems

from io_scene_gltf2_msfs_fss.io.com import msfs_logs
from io_scene_gltf2_msfs_fss.ui.scene_edition import image_panel

from io_scene_gltf2_msfs_fss.io.exp import multi_export_mode
from io_scene_gltf2_msfs_fss.io.exp import presets as exp_presets
from io_scene_gltf2_msfs_fss.io.exp import lod_groups as exp_lod_groups
from io_scene_gltf2_msfs_fss.io.exp import texture_lib


if TYPE_CHECKING:
    from _addons_common.ui.tree_widget.item import TreeItem

class ImagesTreeManager(TreeManager):
    # Only used by operator below
    pass

class MSFS2024_UL_Images(bpy.types.UIList, UL_TreeView):
    use_filter_invert: bpy.props.BoolProperty(
        name="Filter Invert", 
        default=False,
        options=set()
    )  # type: ignore

    # Inherited Methods
    @classmethod
    def custom_draw_item(cls, context, index, item, layout):
        item: TreeItem
        data = item.get_data()
        if not data:
            return
        if isinstance(data, bpy.types.Image):
            cls.draw_image(data, item, index, layout)

    @staticmethod
    def draw_image(image: bpy.types.Image, item, index, row:bpy.types.UILayout):
        row.label(text=image.name)

    def draw_filter(self, context, layout):
        row = layout.row(align=True)
        row.prop(self, "filter_name", text="", icon="VIEWZOOM")
        row.prop(
            self, "use_filter_invert", text="", icon="ARROW_LEFTRIGHT", icon_only=True
        )


    def filter_items(self, context, data, propname):
        """
        This function gets the collection property (as the usual tuple (data, propname)), and must return two lists:
        * The first one is for filtering, it must contain 32bit integers were self.bitflag_filter_item marks the
          matching item as filtered (i.e. to be shown). The upper 16 bits (including self.bitflag_filter_item) are
          reserved for internal use, the lower 16 bits are free for custom use.
        * The second one is for reordering, it must return a list containing the new indices of the items (which
          gives us a mapping org_idx -> new_idx).

        Please note that the default UI_UL_list defines helper functions for common tasks (see its doc for more info).
        If you do not make filtering and/or ordering, return empty list(s) (this will be more efficient than
        returning full lists doing nothing!).

        """
        flt_flags, flt_neworder = super().filter_items(context, data, propname)

        ui_tree = getattr(data, propname)
        helper_funcs = bpy.types.UI_UL_list

        # Filtering by name
        if self.filter_name:
            flt_flags = helper_funcs.filter_items_by_name(
                self.filter_name,
                self.bitflag_filter_item,
                ui_tree,
                "name",
                reverse=self.use_filter_invert
            )
        if not flt_flags:
            flt_flags = [self.bitflag_filter_item] * len(ui_tree)

        return flt_flags, flt_neworder


class MSFS2024_OT_SetImageFlags(bpy.types.Operator):
    bl_idname = "msfs2024.set_image_flags"
    bl_label = "Set Image Flags"
    bl_description = (
        "Set flags on images.\n"
        "Supports multi-selection (Shift and Alt), allowing you to \n"
        "edit flags on multiple images at once.\n"
        "WARNING: Flags are set in xml during export!"
    )
    bl_options = {"INTERNAL"}

    images_tree_manager: ImagesTreeManager | None = None
    multi_edit_properties = {bpy.types.Image :[
            "msfs_flags.msfs_image_quality_high",
            "msfs_flags.msfs_image_alpha_preserv",
            "msfs_flags.msfs_image_no_reduction",
            "msfs_flags.msfs_image_no_mipmap",
            "msfs_flags.msfs_image_prec_inv_avg",
            "msfs_flags.msfs_image_anisotropic"
        ]}

    def execute(self, context):
        return {"FINISHED"}

    def __del__(self):
        try:
            self.images_tree_manager.unregister()
        except:
            pass
    def invoke(self, context, event):

        # Register Image Tree Manager
        self.images_tree_manager = ImagesTreeManager(
            ul_tree_view_class=MSFS2024_UL_Images,
            data_collection_getter=lambda: bpy.data.images,
            alphabetical_order=True,
            multiselection_support=True,
            checkable_items=True,
            multi_edit_properties=self.multi_edit_properties
        )

        self.images_tree_manager.generate_tree_collection()
        wm = context.window_manager
        return wm.invoke_popup(self)

    def draw(self, context):
        # Title
        self.layout.label(text=self.bl_label)
        if bpy.app.version >= (4,2,0):
            self.layout.separator(type="LINE")
        else:
            self.layout.separator()
        if not len(self.images_tree_manager.get_tree_collection()):
            self.layout.label(text="No Images found in this file.", icon="ERROR")
            return

        active_item = self.images_tree_manager.get_active_item()
        image = None
        if active_item:
            image = active_item.get_data()

        if image:
            icon = self.layout.icon(image)
            self.layout.template_icon(icon, scale=8)

        MSFS2024_UL_Images.draw_UL_TreeView(context, self.layout, rows=15)

        if image:

            image_panel.draw_image_properties(self.layout, image)

        self.layout.operator(MSFS2024_OT_GenerateTextureLib.bl_idname)


class MSFS2024_OT_GenerateTextureLib(bpy.types.Operator):
    bl_idname = "msfs2024.generate_texture_lib"
    bl_label = "Generate Texture Lib"
    bl_description = (
        "Standalone Texture Library Generation.\n"
        "Generate a XML file for each checked image.\n"
        "The glTF containing the edited textures must already be exported."
    )
    bl_options = {"INTERNAL"}

    def _get_export_folder(self, dir: str) -> Path:
        dir_path = bpy.path.abspath(dir)
        gltf_path = Path(dir_path)
        gltf_path = gltf_path.resolve()
        return gltf_path

    def _get_autolod_filename(self, lod_name: str):
        """
        Get lod_name that ends with _LOD0
        """
        pattern = re.compile(r"_lod[0-9]+$", re.IGNORECASE)
        new_name = lod_name
        if pattern.search(new_name):
            new_name = pattern.sub("_LOD0", new_name)
        else:
            new_name += "_LOD0"
        return new_name

    def _get_exported_gltf_paths(self, scene: bpy.types.Scene) -> list[str]:

        exported_gltf_paths = set()
        export_mode = multi_export_mode.get_active_export_mode(scene)
        if (
            export_mode == multi_export_mode.ExportMode.OBJECTS
            or export_mode == multi_export_mode.ExportMode.COLLECTIONS
        ):
            lod_groups = exp_lod_groups.get_scene_lod_groups(scene)
            for grp in lod_groups:
                export_folder = self._get_export_folder(grp.folder_path)
                if not export_folder.exists():
                    continue
                for lod in grp.lods:

                    lod_name = os.path.splitext(lod.file_name)[0]
                    if grp.autogenerate_lods and not lod_name.endswith("_LOD0"):
                        lod_name = self._get_autolod_filename(lod_name)

                    gltf_path = export_folder / lod_name
                    gltf_path = gltf_path.with_suffix(".gltf")

                    if gltf_path.exists():
                        exported_gltf_paths.add(gltf_path.as_posix())
        else:
            presets = exp_presets.get_scene_exporter_presets(scene)
            for preset in presets:
                export_folder = self._get_export_folder(preset.folder_path)
                if not export_folder.exists():
                    continue
                gltf_path = export_folder / preset.preset_name
                gltf_path = gltf_path.with_suffix(".gltf")
                if gltf_path.exists():
                    exported_gltf_paths.add(gltf_path.as_posix())
        return list(exported_gltf_paths)

    def get_checked_textures(self)->set[str] | None:
        image_tree_manager = ImagesTreeManager.get_tree_manager_instance()
        if not image_tree_manager:
            return None
        checked_items = image_tree_manager.get_checked_items()
        texture_names = set()
        for item in checked_items:
            data = item.get_data()
            if not isinstance(data, bpy.types.Image):
                continue
            data: bpy.types.Image
            image_name = data.name
            if not image_name:
                continue
            # Remove image extension and .001 suffix
            image_name = image_name.split(".", 1)[0]
            texture_names.add(image_name)
        return texture_names

    def execute(self, context):
        window.set_cursor_wait()
        MSFS2024_LOGGER = msfs_logs.get_logger()
        MSFS2024_LOGGER.clear_logs()
        gltf_paths = self._get_exported_gltf_paths(context.scene)
        if not gltf_paths:
            self.report({"ERROR"}, "No exported glTFs found in scene")
            window.set_cursor_default()
            return {"CANCELLED"}

        
        checked_textures = self.get_checked_textures()
        if not checked_textures:
            self.report({"ERROR"}, "No Image checked!")
            window.set_cursor_default()
            return {"CANCELLED"}

        print("Scanning glTF files to find textures:")
        for _path in gltf_paths:
            print(_path)

        p4.reset_p4_session()
        found_tex = texture_lib.export_gltfs_texture_lib(
            gltf_paths, tex_to_process=checked_textures
        )
        missing_tex = checked_textures - found_tex

        if missing_tex:
            for tex in missing_tex:
                MSFS2024_LOGGER.error(
                    message=f"'{tex}' not found in glTFs files.",
                    details="Texture was not found in glTFs",
                )

        if not found_tex:
            self.report({"ERROR"}, "No Textures found in exported glTFs files!")
            window.set_cursor_default()
            msfs_logs.process_logger_report(self, MSFS2024_LOGGER)
            return {"FINISHED"}


        p4_output = p4.P4LogOutput()
        if not p4.push_p4_session(p4_output=p4_output):
            MSFS2024_LOGGER.error(
                message="Error when trying to open files for edits.",
                details=f"P4 error:\n{str(p4_output)}",
            )
        self.report({"INFO"}, "Texture Library generated. More infos in exporter logs")

        msfs_logs.process_logger_report(self, MSFS2024_LOGGER)
        window.set_cursor_default()
        return {"FINISHED"}
