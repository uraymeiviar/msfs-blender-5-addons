import bpy

from io_scene_gltf2_msfs_fss.blender.msfs_image import MSFS2024ImageFlagsEnum

def draw_image_properties(layout: bpy.types.UILayout, image: bpy.types.Image):
    flags = image.msfs_flags

    layout = layout
    box = layout.box()

    row = box.row()
    row.prop(flags, MSFS2024ImageFlagsEnum.QUALITYHIGH.attribute_name())
    row = box.row()
    row.prop(flags, MSFS2024ImageFlagsEnum.ALPHAPRESERVATION.attribute_name())
    row = box.row()
    row.prop(flags, MSFS2024ImageFlagsEnum.NOREDUCTION.attribute_name())
    row = box.row()
    row.prop(flags, MSFS2024ImageFlagsEnum.NOMIPMAP.attribute_name())
    row = box.row()
    row.prop(flags, MSFS2024ImageFlagsEnum.PRECOMPUTEDINVAVG.attribute_name())
    row = box.row()
    row.prop(flags, MSFS2024ImageFlagsEnum.ANISOTROPIC.attribute_name())

    row = layout.row()
    return

class MSFS2024_PT_ImageProperties(bpy.types.Panel):
    bl_label = "MSFS2024 Image Flags"
    bl_idname = "IMAGE_PT_msfs2024_image_properties"
    bl_space_type = "IMAGE_EDITOR"
    bl_region_type = "UI"
    bl_category = "MSFS2024"

    @classmethod
    def poll(cls, context):
        return context.edit_image is not None
    
    def draw(self, context):
        image = context.edit_image
        draw_image_properties(self.layout, image)