import bpy

class FOLDER_UL_List(bpy.types.UIList):
    def draw_item(
        self, context, layout, data, item, icon, active_data, active_propname, index
    ):
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            layout.prop(item, "path", text="", emboss=False, icon="FILE_FOLDER")
        elif self.layout_type in {"GRID"}:
            layout.alignment = "CENTER"
            layout.label(text="")

class MSFS2024_OT_AddAdditionnalTexDir(bpy.types.Operator):
    bl_idname = "msfs2024.add_additionnal_import_tex_dir"
    bl_label = "Add Folder"
    bl_description = "Add a new folder to the list"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        importer_settings = context.scene.msfs_importer_settings
        importer_settings.additionnal_texture_dirs.add()
        # Update the active index
        importer_settings.active_tex_dir_index = len(importer_settings.additionnal_texture_dirs) - 1
        return {'FINISHED'}

class MSFS2024_OT_RemoveAdditionnalTexDir(bpy.types.Operator):
    bl_idname = "msfs2024.remove_additionnal_import_tex_dir"
    bl_label = "Remove Folder"
    bl_description = "Remove the selected folder from the list"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        importer_settings = context.scene.msfs_importer_settings
        if (importer_settings.additionnal_texture_dirs and
            0 <= importer_settings.active_tex_dir_index < len(importer_settings.additionnal_texture_dirs)
        ):
            importer_settings.additionnal_texture_dirs.remove(importer_settings.active_tex_dir_index)

        return {'FINISHED'}

def draw_importer_header(context,layout):
    props = context.scene.msfs_importer_settings
    layout.label(icon="TOOL_SETTINGS")
    text = ""
    if bpy.app.version >= (4, 2, 0):
        text = "Microsoft Flight Simulator 2024"
    layout.prop(props, "enable_msfs_extension", text=text)

def draw_importer_panel(context, layout):
    """
    MSFS2024_PT_importer_panel draw functions. 
    
    This independent functions can be used by blender 4.2 gltf extension to 
    draw MSFS2024 import panel.
    """

    props = context.scene.msfs_importer_settings
    layout.use_property_split = True
    layout.use_property_decorate = False  # No animation.

    layout.active = props.enable_msfs_extension
    layout.prop(props, "import_materials", text="Import Materials")
    layout.prop(props, "import_collisions", text="Import Collisions")

    layout.label(text="Additional Texture Directories :")
    row = layout.row()
    row.template_list(
        "FOLDER_UL_List",
        "additionnal_texture_dirs",
        props,
        "additionnal_texture_dirs",
        props,
        "active_tex_dir_index",
        rows=3,
    )

    # Buttons for adding and removing folders
    col = row.column(align=True)
    col.operator("msfs2024.add_additionnal_import_tex_dir", icon="ADD", text="")
    col.operator("msfs2024.remove_additionnal_import_tex_dir", icon="REMOVE", text="")

class MSFS2024_PT_importer_panel(bpy.types.Panel):
    """
    Only used for Blender < 4.2 
    """
    skip_register = True # This will be register by gltf addon

    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOL_PROPS'
    bl_label = "Microsoft Flight Simulator 2024"
    bl_parent_id = "GLTF_PT_import_user_extensions" #only works with blender version < 4.2
    bl_location = "File > Import > glTF 2.0"

    @classmethod
    def poll(cls, context):
        sfile = context.space_data
        operator = sfile.active_operator
        return operator.bl_idname == "IMPORT_SCENE_OT_gltf"

    def draw_header(self, context):
        layout = self.layout
        draw_importer_header(context, layout)

    def draw(self, context):
        draw_importer_panel(context,self.layout)
