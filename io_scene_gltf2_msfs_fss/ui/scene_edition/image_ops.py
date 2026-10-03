from __future__ import annotations
from typing import TYPE_CHECKING

import bpy

from _addons_common.ui.tree_widget.manager import TreeManager
from _addons_common.ui.tree_widget.view import UL_TreeView
from _addons_common.ui.tree_widget.view_ope import  TREEVIEW_OT_SelectAllItems

from io_scene_gltf2_msfs_fss.ui.scene_edition import image_panel

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
            checkable_items=False,
            multi_edit_properties=self.multi_edit_properties
        )

        self.images_tree_manager.generate_ui_tree_collection()
        wm = context.window_manager
        return wm.invoke_popup(self)

    def draw(self, context):
        # Title
        self.layout.label(text=self.bl_label)
        if bpy.app.version >= (4,2,0):
            self.layout.separator(type="LINE")
        else:
            self.layout.separator()
        if not len(self.images_tree_manager.get_ui_tree_collection()):
            self.layout.label(text="No Images found in this file.", icon="ERROR")
            return

        active_item = self.images_tree_manager.get_active_item()
        image = None
        if active_item:
            image = active_item.get_data()

        if image:
            icon = self.layout.icon(image)
            self.layout.template_icon(icon, scale=8)

        row = self.layout.row()
        select_all_ope = row.operator(
            TREEVIEW_OT_SelectAllItems.bl_idname,
            text="Select All",
            icon="RESTRICT_SELECT_OFF",
        )
        select_all_ope.tree_manager_name = MSFS2024_UL_Images.tree_manager_name
        select_all_ope.select = True
        deselect_all_ope = row.operator(
            TREEVIEW_OT_SelectAllItems.bl_idname,
            text="Deselect All",
            icon="RESTRICT_SELECT_ON",
        )
        deselect_all_ope.tree_manager_name = MSFS2024_UL_Images.tree_manager_name
        deselect_all_ope.select = False

        MSFS2024_UL_Images.draw_UL_TreeView(context, self.layout, rows=15)

        if image:

            image_panel.draw_image_properties(self.layout, image)