import bpy

from .wipermaskgen_utils import bake_texture


# region OPERATORS
class MSFS2024_OT_WiperMask_Add_Configuration(bpy.types.Operator):
    bl_idname = "msfs2024.wipermaskgen_addconfiguration"
    bl_label = "Add configuration"

    def execute(self, context):
        configurations = (
            context.scene.msfs2024_wiper_mask_properties.wiper_mask_configurations
        )
        configurations.add()

        return {"FINISHED"}


class MSFS2024_OT_WiperMask_Remove_Last_Configuration(bpy.types.Operator):
    bl_idname = "msfs2024.wipermaskgen_removelastconf"
    bl_label = "Remove last configuration"

    def execute(self, context):
        configurations = (
            context.scene.msfs2024_wiper_mask_properties.wiper_mask_configurations
        )
        configurations.remove(len(configurations) - 1)

        return {"FINISHED"}


class MSFS2024_OT_WiperMask_Bake(bpy.types.Operator):
    bl_idname = "msfs2024.wipermaskgen_bake"
    bl_label = "Bake Texture"
    bl_description = "All the parameters MUST be set up to enable the bake"

    def execute(self, context):
        props = context.scene.msfs2024_wiper_mask_properties
        bake_texture(
            start_time=props.animation_in_start,
            end_time=props.animation_in_end + 1,
            configurations=props.wiper_mask_configurations,
            output_texture_name=props.output_texture_name,
            output_texture_size=props.output_texture_size,
            output_path=props.output_path,
        )
        return {"FINISHED"}


# endregion


# region PROPERTIES
class MSFS2024_WiperMask_Configuration(bpy.types.PropertyGroup):
    windshield_object: bpy.props.PointerProperty(
        type=bpy.types.Object,
        name="Windshield Object"
    )
    wiper_point_a: bpy.props.PointerProperty(type=bpy.types.Object)
    wiper_point_b: bpy.props.PointerProperty(type=bpy.types.Object)


class MSFS2024_WiperMask_Properties(bpy.types.PropertyGroup):
    register_order = 1  # register after MSFS2024_WiperMask_Configuration

    animation_in_start: bpy.props.IntProperty(name="Action In Start")
    animation_in_end: bpy.props.IntProperty(name="Action In End")

    wiper_mask_configurations: bpy.props.CollectionProperty(
        type=MSFS2024_WiperMask_Configuration
    )

    output_texture_size: bpy.props.IntProperty(default=1024, min=256, max=4096)
    output_texture_name: bpy.props.StringProperty(
        name="Output Texture Name",
        default="WiperMask"
    )
    output_path: bpy.props.StringProperty(
        name="Output Path",
        default="",
        subtype="DIR_PATH"
    )


# endregion


# region PANELS
class MSFS2024_PT_WiperMask_Panel(bpy.types.Panel):
    bl_label = "Wiper Mask Generator"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Microsoft Flight Simulator 2024 Tools"
    bl_options = {"HEADER_LAYOUT_EXPAND"}

    def has_all_configuration_set(self, configurations):
        if len(configurations) == 0:
            return False

        for configuration in configurations:
            if configuration.windshield_object is None:
                return False
            if configuration.wiper_point_a is None:
                return False
            if configuration.wiper_point_b is None:
                return False
        return True

    def ready_to_bake(self, context):
        props = context.scene.msfs2024_wiper_mask_properties

        if props.output_texture_size is None:
            return False

        if props.output_path is None or props.output_path == "":
            return False

        if not self.has_all_configuration_set(props.wiper_mask_configurations):
            return False

        return True

    def draw(self, context):
        layout = self.layout

        box = layout.box()
        row = box.row(align=True)
        row.label(text="Create 2 point helper.")
        row = box.row(align=True)
        row.label(
            text="Parent them to the wiper mesh and position on the exterior point of the wipe mesh."
        )
        row = box.row(align=True)
        row.label(
            text="It is up to you to define the area impacted by the cleaner part of the wiper."
        )

        layout.row().separator()

        props = context.scene.msfs2024_wiper_mask_properties

        box = layout.box()
        row = box.row()
        row.label(text="Action In")
        row.prop(data=props, property="animation_in_start", text="Start Time")
        row.prop(data=props, property="animation_in_end", text="End Time")

        row = box.row()

        layout.row().separator()

        box = layout.box()
        box.label(text="Wipers")

        row = box.row()
        row.operator(
            MSFS2024_OT_WiperMask_Remove_Last_Configuration.bl_idname, 
            text=" - "
        )
        row.operator(
            MSFS2024_OT_WiperMask_Add_Configuration.bl_idname, 
            text=" + "
        )

        for configuration in props.wiper_mask_configurations:
            row = box.row()
            row.prop(configuration, "windshield_object")
            row = box.row()
            row.prop(configuration, "wiper_point_a", text="Wiper A")
            row = box.row()
            row.prop(configuration, "wiper_point_b", text="Wiper B")
            row = box.row()
            row.separator()

        layout.row().separator()

        box = layout.box()
        row = box.row(align=True, heading="Output Texture Size:")
        row.prop(props, "output_texture_size", text="")
        row = box.row()
        row.prop(props, "output_texture_name")
        row = box.row()
        row.prop(props, "output_path", text="Output Path")

        layout.row().separator()
        col = layout.column()
        col.operator(MSFS2024_OT_WiperMask_Bake.bl_idname, text="Bake Texture")
        col.enabled = self.ready_to_bake(context)


# endregion
