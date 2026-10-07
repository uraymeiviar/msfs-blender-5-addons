import bpy


from io_scene_gltf2_msfs_fss.io.exp import export_settings
from io_scene_gltf2_msfs_fss.ui.exp import exporter_panel, export_settings_ops

if bpy.app.version >= (4, 5, 0):
    # Public API since Khronos 4.5 (the draco module itself moved from io.com to io.exp in 5.x)
    from io_scene_gltf2 import is_draco_available
else:
    from io_scene_gltf2.io.com import gltf2_io_draco_compression_extension

    def is_draco_available():
        return gltf2_io_draco_compression_extension.dll_exists(quiet=True)

# region Panels
class MSFS2024_PT_export_settings_preset(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_label = ""
    bl_parent_id = "MSFS2024_PT_MultiExporter"
    bl_options = {"HIDE_HEADER"}

    def __init__(self, *args, **kwargs):
        export_settings.init_setting_presets(bpy.context.scene)
        super().__init__(*args, **kwargs)
    
    @classmethod
    def poll(cls, context: bpy.types.Context):
        return exporter_panel.get_active_tab(context.scene) == exporter_panel.PanelTab.SETTINGS

    def draw(self, context: bpy.types.Context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.


        row = layout.row()
        row.prop(
            context.scene,
            "msfs_multi_exporter_settings_presets_enum",
            text=""
        )
        row.operator(export_settings_ops.MSFS2024_OT_EditSettingsPresetName.bl_idname, text="", icon="TEXT")
        row.operator(export_settings_ops.MSFS2024_OT_AddSettingsPreset.bl_idname, text="", icon="ADD")
        row.operator(export_settings_ops.MSFS2024_OT_RemoveSettingsPreset.bl_idname, text="", icon="REMOVE")


class MSFS2024_PT_export_main(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_label = "General"
    bl_parent_id = "MSFS2024_PT_export_settings_preset"
    bl_options = {"DEFAULT_CLOSED"}


    def draw(self, context: bpy.types.Context):

        active_settings_preset = export_settings.get_active_export_settings(context.scene)
        
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.

        layout.prop(context.scene, "msfs_background_export")
        layout.separator()
        layout.prop(active_settings_preset, "export_copyright")
        layout.prop(active_settings_preset, "will_save_settings")

class MSFS2024_PT_export_texture(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_label = "Textures"
    bl_parent_id = "MSFS2024_PT_export_settings_preset"
    bl_options = {"DEFAULT_CLOSED"}


    def draw_header(self, context: bpy.types.Context):
        self.layout.label(icon="FILE_IMAGE")

    def draw(self, context: bpy.types.Context):
        active_settings_preset = export_settings.get_active_export_settings(context.scene)
        
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.

        layout.prop(active_settings_preset, "export_keep_originals")
        if active_settings_preset.export_keep_originals is False:
            layout.prop(active_settings_preset, "export_texture_dir", icon="FILE_FOLDER")

# region MSFS2024
class MSFS2024_PT_MSFS2024_export(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_label = "Microsoft Flight Simulator 2024"
    bl_parent_id = "MSFS2024_PT_export_settings_preset"
    bl_options = {"DEFAULT_CLOSED"}


    def draw_header(self, context: bpy.types.Context):
        active_settings_preset = export_settings.get_active_export_settings(context.scene)

        self.layout.label(icon='TOOL_SETTINGS')
        self.layout.prop(active_settings_preset, "enable_msfs_extension", text="")

    def draw(self, context: bpy.types.Context):
        return

class MSFS2024_PT_MSFS2024_texture(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_label = "Textures"
    bl_parent_id = "MSFS2024_PT_MSFS2024_export"
    bl_options = {"DEFAULT_CLOSED"}

    register_order = 1 # Register after MSFS2024_PT_MSFS2024_export class


    def draw(self, context: bpy.types.Context):
        active_settings_preset = export_settings.get_active_export_settings(context.scene)

        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.

        layout.active = active_settings_preset.enable_msfs_extension
        layout.prop(
            active_settings_preset,
            "generate_texturelib",
            text="Generate TextureLib"
        )

class MSFS2024_PT_MSFS2024_process(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_label = "Export Process"
    bl_parent_id = "MSFS2024_PT_MSFS2024_export"
    bl_options = {"DEFAULT_CLOSED"}

    
    def draw(self, context: bpy.types.Context):
        active_settings_preset = export_settings.get_active_export_settings(context.scene)

        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.

        layout.active = active_settings_preset.enable_msfs_extension
        
        row = layout.row()
        row.prop(active_settings_preset, "reset_origins")
        if active_settings_preset.reset_origins == "ALL_ROOTS":
            box = layout.box()
            box.prop(active_settings_preset.export_transform_properties, "reset_translation")
            box.prop(active_settings_preset.export_transform_properties, "reset_rotation")
            box.prop(active_settings_preset.export_transform_properties, "reset_scale")
            
        layout.prop(active_settings_preset, "remove_lod_prefix")
        layout.prop(active_settings_preset, "merge_nodes")
        layout.prop(active_settings_preset, "export_as_submodel")

# endregion

class MSFS2024_PT_export_include(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_label = "Include"
    bl_parent_id = "MSFS2024_PT_export_settings_preset"
    bl_options = {"DEFAULT_CLOSED"}
    
    def draw(self, context: bpy.types.Context):
        active_settings_preset = export_settings.get_active_export_settings(context.scene)
        
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.

        # To use the MultiExporter panel, it's important to have "use selected" to True
        col = layout.column(heading="", align=True)
        col.prop(active_settings_preset, "use_selection")
        col.enabled = False
        
        col = layout.column(heading="Limit to", align=True)
        col.prop(active_settings_preset, "use_visible")

        if not active_settings_preset.enable_msfs_extension:
            col = layout.column(heading="", align=True)
            col.prop(active_settings_preset, "export_extras")

        col = layout.column(heading="Data", align=True)
        col.prop(active_settings_preset, "export_cameras")
        col.prop(active_settings_preset, "export_lights")

class MSFS2024_PT_export_transform(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_label = "Transform"
    bl_parent_id = "MSFS2024_PT_export_settings_preset"
    bl_options = {"DEFAULT_CLOSED"}

    
    def draw(self, context: bpy.types.Context):
        active_settings_preset = export_settings.get_active_export_settings(context.scene)
        
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.
        layout.prop(active_settings_preset, "export_yup")
        # Yup is always enabled when using msfs extension
        layout.enabled = not active_settings_preset.enable_msfs_extension

class MSFS2024_PT_export_scene_graph(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_label = "Scene Graph"
    bl_parent_id = "MSFS2024_PT_export_settings_preset"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context: bpy.types.Context):
        active_settings_preset = export_settings.get_active_export_settings(context.scene)

        return (not active_settings_preset.enable_msfs_extension and bpy.app.version >= (4, 2, 0))

    def draw(self, context: bpy.types.Context):
        if bpy.app.version < (4, 2, 0):
            return
        
        active_settings_preset = export_settings.get_active_export_settings(context.scene)

        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.

        layout.prop(active_settings_preset, "export_gn_mesh")
        layout.prop(active_settings_preset, "export_gpu_instances")
        layout.prop(active_settings_preset, "export_hierarchy_flatten_objs")
        layout.prop(active_settings_preset, "export_hierarchy_full_collections")

class MSFS2024_PT_export_geometry(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_label = "Mesh"
    bl_parent_id = "MSFS2024_PT_export_settings_preset"
    bl_options = {"DEFAULT_CLOSED"}


    def draw_header(self, context: bpy.types.Context):
        active_settings_preset = export_settings.get_active_export_settings(context.scene)

        self.layout.label(icon="MESH_DATA")
        self.layout.prop(active_settings_preset, "export_mesh", text="")

    def draw(self, context: bpy.types.Context):
        active_settings_preset = export_settings.get_active_export_settings(context.scene)
        
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.

        layout.active = active_settings_preset.export_mesh
        layout.prop(active_settings_preset, "export_apply")
        layout.prop(active_settings_preset, "export_texcoords")
        layout.prop(active_settings_preset, "export_normals")

        col = layout.column()
        col.prop(active_settings_preset, "export_tangents")
        col.active = active_settings_preset.export_normals

        if bpy.app.version < (4, 2, 0):
            layout.prop(active_settings_preset, "export_colors")

        if bpy.app.version >= (3, 6, 0):
            layout.prop(active_settings_preset, "export_attributes")

        layout.prop(active_settings_preset, "use_mesh_edges")
        layout.prop(active_settings_preset, "use_mesh_vertices")

        if bpy.app.version >= (4, 2, 0):
            header, body = layout.panel("MSFS2024_PT_export_vertex_colors", default_closed=True)
            header.label(text="Vertex Colors")
            if body:
                body.prop(active_settings_preset, "export_vertex_color")
                body.prop(active_settings_preset, "export_all_vertex_colors")
                body.prop(active_settings_preset, "export_active_vertex_color_when_no_material")

class MSFS2024_PT_export_material(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_label = "Material"
    bl_parent_id = "MSFS2024_PT_export_settings_preset"
    bl_options = {"DEFAULT_CLOSED"}


    def draw_header(self, context: bpy.types.Context):
        self.layout.label(icon="MATERIAL_DATA")

    def draw(self, context: bpy.types.Context):
        active_settings_preset = export_settings.get_active_export_settings(context.scene)
        
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.

        layout.prop(active_settings_preset, "export_materials")
        col = layout.column()
        col.active = active_settings_preset.export_materials == "EXPORT"

        if active_settings_preset.enable_msfs_extension:
            return

        col.prop(active_settings_preset, "export_image_format")

        if bpy.app.version >= (3, 6, 0):
            col.prop(active_settings_preset, "export_jpeg_quality")

        if bpy.app.version >= (4, 2, 0):
            col.prop(active_settings_preset, "export_image_add_webp")
            col.prop(active_settings_preset, "export_image_webp_fallback")

            header, body = layout.panel("MSFS2024_PT_export_unused_images_textures", default_closed=True)
            header.label(text="Unused Textures & Images")
            if body:
                body.prop(active_settings_preset, "export_unused_images")
                body.prop(active_settings_preset, "export_unused_textures")

class MSFS2024_PT_export_shapekeys(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_label = "Shape Keys"
    bl_parent_id = "MSFS2024_PT_export_settings_preset"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context: bpy.types.Context):
        active_settings_preset = export_settings.get_active_export_settings(context.scene)

        self.layout.label(icon="SHAPEKEY_DATA")
        self.layout.prop(active_settings_preset, "export_morph", text="")

    def draw(self, context: bpy.types.Context):
        active_settings_preset = export_settings.get_active_export_settings(context.scene)
        
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.
        
        layout.active = active_settings_preset.export_morph

        layout.prop(active_settings_preset, "export_morph_normal")
        col = layout.column()
        col.active = active_settings_preset.export_morph_normal
        col.prop(active_settings_preset, "export_morph_tangent")

        if active_settings_preset.enable_msfs_extension:
            return

        if bpy.app.version >= (4, 2, 0) and not active_settings_preset.enable_msfs_extension:
            header, body = layout.panel("MSFS2024_PT_export_optimize_shapekeys", default_closed=True)
            header.label(text="Optimize Shape Keys")
            if not body:
                return
            col = body.column()
            col.prop(active_settings_preset, "export_try_sparse_sk")
            col = body.column()
            col.active = active_settings_preset.export_try_sparse_sk
            col.prop(active_settings_preset, "export_try_omit_sparse_sk")

class MSFS2024_PT_export_armature(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_label = "Armature"
    bl_parent_id = "MSFS2024_PT_export_settings_preset"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context: bpy.types.Context):
        return bpy.app.version >= (3, 3, 0) 
    

    def draw_header(self, context: bpy.types.Context):
        self.layout.label(icon="ARMATURE_DATA")

    def draw(self, context: bpy.types.Context):
        active_settings_preset = export_settings.get_active_export_settings(context.scene)
        
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.

        layout.active = active_settings_preset.export_skins

        if bpy.app.version >= (3, 6, 0) :
            # Export rest position is always enabled when using msfs extension
            sub_layout = layout.row()
            sub_layout.prop(active_settings_preset, "export_rest_position_armature")
            sub_layout.enabled = not active_settings_preset.enable_msfs_extension

        if bpy.app.version >= (3, 3, 0):
            row = layout.row()
            row.active = active_settings_preset.export_force_sampling
            row.prop(active_settings_preset, "export_def_bones")
            if (
                active_settings_preset.export_force_sampling is False
                and active_settings_preset.export_def_bones is True
            ):
                layout.label(text="Export only deformation bones is not possible when not sampling animation")

            if bpy.app.version >= (4, 2, 0):
                layout.prop(active_settings_preset, "export_armature_object_remove")

            if bpy.app.version >= (3, 6, 0):
                layout.prop(active_settings_preset, "export_hierarchy_flatten_bones")

class MSFS2024_PT_export_skinning(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_label = "Skinning"
    bl_parent_id = "MSFS2024_PT_export_settings_preset"
    bl_options = {"DEFAULT_CLOSED"}



    def draw_header(self, context: bpy.types.Context):
        active_settings_preset = export_settings.get_active_export_settings(context.scene)

        self.layout.label(icon="MOD_SKIN")
        self.layout.prop(active_settings_preset, "export_skins", text="")

    def draw(self, context: bpy.types.Context):
        active_settings_preset = export_settings.get_active_export_settings(context.scene)

        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.
        layout.active = active_settings_preset.export_skins

        if bpy.app.version >= (4, 2, 0):
            layout.prop(active_settings_preset, "export_influence_nb")

        if not active_settings_preset.enable_msfs_extension:
            layout.prop(active_settings_preset, "export_all_influences")

class MSFS2024_PT_export_Lighting(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_label = "Lighting"
    bl_parent_id = "MSFS2024_PT_export_settings_preset"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context: bpy.types.Context):
        active_settings_preset = export_settings.get_active_export_settings(context.scene)

        return ( bpy.app.version >= (3, 6, 0) and not active_settings_preset.enable_msfs_extension)

    def draw(self, context: bpy.types.Context):
        if bpy.app.version < (3, 6, 0):
            return

        active_settings_preset = export_settings.get_active_export_settings(context.scene)

        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.

        layout.prop(active_settings_preset, "export_import_convert_lighting_mode")

class MSFS2024_PT_export_geometry_compression(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_label = "Compression"
    bl_parent_id = "MSFS2024_PT_export_geometry"
    bl_options = {'DEFAULT_CLOSED'}

    register_order = 1 # Register after MSFS2024_PT_export_geometry class

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.is_draco_available = is_draco_available()

    @classmethod
    def poll(cls, context: bpy.types.Context):
        active_settings_preset = export_settings.get_active_export_settings(context.scene)

        return (
            active_settings_preset.export_draco_mesh_compression_enable
        )

    def draw_header(self, context: bpy.types.Context):
        active_settings_preset = export_settings.get_active_export_settings(context.scene)
        self.layout.prop(active_settings_preset, "export_draco_mesh_compression_enable", text="")

    def draw(self, context: bpy.types.Context):
        active_settings_preset = export_settings.get_active_export_settings(context.scene)
        
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.

        layout.active = active_settings_preset.export_draco_mesh_compression_enable
        layout.prop(active_settings_preset, "export_draco_mesh_compression_level")

        col = layout.column(align=True)
        col.prop(active_settings_preset, "export_draco_position_quantization", text="Quantize Position")
        col.prop(active_settings_preset, "export_draco_normal_quantization", text="Normal")
        col.prop(active_settings_preset, "export_draco_texcoord_quantization", text="Tex Coord")
        col.prop(active_settings_preset, "export_draco_color_quantization", text="Color")
        col.prop(active_settings_preset, "export_draco_generic_quantization", text="Generic")

class MSFS2024_PT_export_animation(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_label = "Animation"
    bl_parent_id = "MSFS2024_PT_export_settings_preset"
    bl_options = {"DEFAULT_CLOSED"}


    def draw_header(self, context: bpy.types.Context):
        active_settings_preset = export_settings.get_active_export_settings(context.scene)

        self.layout.label(icon="ANIM")
        self.layout.prop(active_settings_preset, "export_animations", text="")

    def draw(self, context: bpy.types.Context):
        active_settings_preset = export_settings.get_active_export_settings(context.scene)
        
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.

        layout.active = active_settings_preset.export_animations

        if bpy.app.version >= (3, 6, 0):                
            row = layout.row()
            row.prop(active_settings_preset, 'export_animation_mode')

            if active_settings_preset.export_animation_mode == "ACTIVE_ACTIONS":
                layout.prop(active_settings_preset, 'export_nla_strips_merged_animation_name')
            elif active_settings_preset.export_animation_mode == "ACTIONS" and bpy.app.version >= (4, 2, 0):
                layout.prop(active_settings_preset, 'export_merge_animation')

            row = layout.row()
            row.active = (
                active_settings_preset.export_force_sampling
                and active_settings_preset.export_animation_mode in ['ACTIONS', 'ACTIVE_ACTIONS']
            )
            row.prop(active_settings_preset, 'export_bake_animation')

            if active_settings_preset.export_animation_mode == "SCENE":
                layout.prop(active_settings_preset, 'export_anim_scene_split_object')
        else:
            layout.prop(active_settings_preset, "export_current_frame")
            layout.prop(active_settings_preset, "export_frame_range")
            layout.prop(active_settings_preset, "export_frame_step")
            layout.prop(active_settings_preset, "export_force_sampling")
            
            row = layout.row()
            row.prop(active_settings_preset, "export_nla_strips")

            if (
                active_settings_preset.export_nla_strips is False
                and bpy.app.version >= (3, 3, 0)
            ):
                layout.prop(active_settings_preset, "export_nla_strips_merged_animation_name")

            layout.prop(active_settings_preset, "export_optimize_animation_size")
            if bpy.app.version >= (3, 3, 0):
                layout.prop(active_settings_preset, "export_anim_single_armature")
            else:
                layout.prop(active_settings_preset, 'export_def_bones')

class MSFS2024_PT_export_animation_notes(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_label = "Notes"
    bl_parent_id = "MSFS2024_PT_export_animation"
    bl_options = {'DEFAULT_CLOSED'}

    register_order = 1 #Register after MSFS2024_PT_export_animation class

    @classmethod
    def poll(cls, context: bpy.types.Context):
        active_settings_preset = export_settings.get_active_export_settings(context.scene)

        return ( bpy.app.version >= (3, 6, 0)
            and active_settings_preset.export_animation_mode in ["NLA_TRACKS", "SCENE"]
        )

    def draw(self, context: bpy.types.Context):
        if bpy.app.version < (3, 6, 0):
            return

        active_settings_preset = export_settings.get_active_export_settings(context.scene)
        
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.

        if active_settings_preset.export_animation_mode == "SCENE":
            layout.label(text="Scene mode uses full bake mode:")
            layout.label(text="- sampling is active")
            layout.label(text="- baking all objects is active")
            layout.label(text="- Using scene frame range")
        elif active_settings_preset.export_animation_mode == "NLA_TRACKS":
            layout.label(text="Track mode uses full bake mode:")
            layout.label(text="- sampling is active")
            layout.label(text="- baking all objects is active")

class MSFS2024_PT_export_animation_ranges(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_label = "Rest & Ranges"
    bl_parent_id = "MSFS2024_PT_export_animation"
    bl_options = {'DEFAULT_CLOSED'}

    register_order = 1 #After MSFS2024_PT_export_animation register
    @classmethod
    def poll(cls, context: bpy.types.Context):
        return (bpy.app.version >= (3, 6, 0))

    def draw(self, context: bpy.types.Context):
        if bpy.app.version < (3, 6, 0):
            return
        
        active_settings_preset = export_settings.get_active_export_settings(context.scene)

        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.

        layout.prop(active_settings_preset, 'export_current_frame')
        row = layout.row()
        row.active = active_settings_preset.export_animation_mode in ['ACTIONS', 'ACTIVE_ACTIONS', 'NLA_TRACKS']
        row.prop(active_settings_preset, 'export_frame_range')
        layout.prop(active_settings_preset, 'export_anim_slide_to_zero')
        row = layout.row()
        row.active = active_settings_preset.export_animation_mode in ['ACTIONS', 'ACTIVE_ACTIONS', 'NLA_TRACKS']
        layout.prop(active_settings_preset, 'export_negative_frame')

class MSFS2024_PT_export_animation_armature(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_label = "Armature"
    bl_parent_id = "MSFS2024_PT_export_animation"
    bl_options = {'DEFAULT_CLOSED'}

    register_order = 1 #Register after MSFS2024_PT_export_animation class

    @classmethod
    def poll(cls, context: bpy.types.Context):
        return bpy.app.version >= (3, 6, 0)
        

    def draw(self, context: bpy.types.Context):
        if bpy.app.version < (3, 6, 0):
            return
        
        active_settings_preset = export_settings.get_active_export_settings(context.scene)

        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.

        layout.active = active_settings_preset.export_animations

        layout.prop(active_settings_preset, 'export_anim_single_armature')
        layout.prop(active_settings_preset, 'export_reset_pose_bones')

class MSFS2024_PT_export_animation_shapekeys(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_label = "Shape keys Animation"
    bl_parent_id = "MSFS2024_PT_export_animation"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context: bpy.types.Context):
        return bpy.app.version >= (3, 6, 0)

    def draw_header(self, context: bpy.types.Context):
        if bpy.app.version < (3, 6, 0):
            return

        active_settings_preset = export_settings.get_active_export_settings(context.scene)

        self.layout.active = (
            active_settings_preset.export_animations
            and active_settings_preset.export_morph
        )
        self.layout.prop(active_settings_preset, "export_morph_animation", text="")

    def draw(self, context: bpy.types.Context):
        if bpy.app.version < (3, 6, 0):
            return
        
        active_settings_preset = export_settings.get_active_export_settings(context.scene)
        
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.

        layout.active = active_settings_preset.export_animations
        layout.prop(active_settings_preset, "export_morph_reset_sk_data")

class MSFS2024_PT_export_animation_sampling(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_label = "Sampling Animations"
    bl_parent_id = "MSFS2024_PT_export_animation"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context: bpy.types.Context):
        return bpy.app.version >= (3, 6, 0)

    def draw_header(self, context: bpy.types.Context):
        if bpy.app.version < (3, 6, 0):
            return

        active_settings_preset = export_settings.get_active_export_settings(context.scene)

        self.layout.active = (
            active_settings_preset.export_animations
            and active_settings_preset.export_animation_mode in ['ACTIONS', 'ACTIVE_ACTIONS']
        )
        self.layout.prop(active_settings_preset, "export_force_sampling", text="")

    def draw(self, context: bpy.types.Context):
        if bpy.app.version < (3, 6, 0):
            return
        
        active_settings_preset = export_settings.get_active_export_settings(context.scene)
        
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.

        layout.active = active_settings_preset.export_animations
        layout.prop(active_settings_preset, 'export_frame_step')

class MSFS2024_PT_export_animation_optimize(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_label = "Optimize Animations"
    bl_parent_id = "MSFS2024_PT_export_animation"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context: bpy.types.Context):
        return bpy.app.version >= (3, 6, 0)

    def draw(self, context: bpy.types.Context):
        active_settings_preset = export_settings.get_active_export_settings(context.scene)
        
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.

        layout.active = active_settings_preset.export_animations

        layout.prop(active_settings_preset, "export_optimize_animation_size")

        row = layout.row()
        row.prop(active_settings_preset, "export_optimize_animation_keep_anim_armature")

        row = layout.row()
        row.prop(active_settings_preset, "export_optimize_animation_keep_anim_object")

        if bpy.app.version >= (4, 2, 0):
            row = layout.row()
            row.prop(active_settings_preset, "export_optimize_disable_viewport")

# endregion
