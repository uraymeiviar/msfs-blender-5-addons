import bpy

from io_scene_gltf2_msfs_fss.blender.msfs_lights import MSFS2024LightType, MSFS2024LightPropertiesEnum


class MSFS2024_PT_LightProperties(bpy.types.Panel):
    bl_label = "MSFS2024 Light Parameters"
    bl_idname = "LIGHT_PT_msfs2024_light_properties"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "data"

    @classmethod
    def poll(cls, context):

        return context.active_object is not None and context.active_object.type == 'LIGHT'     

    def draw_color(self, context, prop, layout):
        box = layout.box()
        box.label(text="Color")
        box.prop(prop, MSFS2024LightPropertiesEnum.USE_LIGHT_TEMPERATURE.attribute_name())

        use_light_temperature = getattr(
            prop,
            MSFS2024LightPropertiesEnum.USE_LIGHT_TEMPERATURE.attribute_name()
        )

        if use_light_temperature:
            row = box.row()
            row.prop(prop, MSFS2024LightPropertiesEnum.LIGHT_TEMPERATURE.attribute_name())
            row = row.row()
            row.enabled = False
            row.scale_x = 0.5
            row.prop(
                prop,
                MSFS2024LightPropertiesEnum.LIGHT_TEMPERATURE_PREVIEW.attribute_name(),
                text="",
            )

        else:
            row = box.row(heading=MSFS2024LightPropertiesEnum.LIGHTCOLOR.property_name())
            row.prop(
                prop,
                MSFS2024LightPropertiesEnum.LIGHTCOLOR.attribute_name(),
                text=""
            )

    def draw_fast_light_properties(self, context, prop, layout):
        self.draw_color(context, prop, layout)

        box = layout.box()
        box.label(text="Power")
        box.prop(prop, MSFS2024LightPropertiesEnum.LIGHTINTENSITY.attribute_name())
        box.prop(prop, MSFS2024LightPropertiesEnum.LIGHTDAYNIGHTCYCLE.attribute_name())
        if not getattr(prop, MSFS2024LightPropertiesEnum.LIGHTDAYNIGHTCYCLE.attribute_name()):
            box.prop(prop, MSFS2024LightPropertiesEnum.LIGHTDAYTIMEINTENSITY.attribute_name())

        box = layout.box()
        box : bpy.types.UILayout
        box.label(text="Distribution")
        box.prop(prop, MSFS2024LightPropertiesEnum.LIGHTCONEANGLE.attribute_name())

        sub_row = box.row(align=True)    
        sub_row.prop(prop, MSFS2024LightPropertiesEnum.HASLIGHTSYMMETRY.attribute_name())

        box = layout.box()
        box.label(text="Animation")
        box.prop(prop, MSFS2024LightPropertiesEnum.LIGHTFLASHFREQUENCY.attribute_name())
        box.prop(prop, MSFS2024LightPropertiesEnum.LIGHTFLASHDURATION.attribute_name())
        box.prop(prop, MSFS2024LightPropertiesEnum.LIGHTFLASHPHASE.attribute_name())
        box.prop(prop, MSFS2024LightPropertiesEnum.LIGHTROTATIONSPEED.attribute_name())
        box.prop(prop, MSFS2024LightPropertiesEnum.LIGHTROTATIONPHASE.attribute_name())
        box.prop(prop, MSFS2024LightPropertiesEnum.LIGHTRANDOMPHASE.attribute_name())

        box = layout.box()
        box.label(text="Lens Flare")
        box.prop(prop, MSFS2024LightPropertiesEnum.FLARE_ENABLED.attribute_name())
        if getattr(prop, MSFS2024LightPropertiesEnum.FLARE_ENABLED.attribute_name()):
            box.prop(prop, MSFS2024LightPropertiesEnum.FLARE_ONLY.attribute_name())

    def draw_advanced_light_properties(self, context, prop, layout):
        self.draw_color(context, prop, layout)

        box = layout.box()
        box.label(text="Power")
        box.prop(prop, MSFS2024LightPropertiesEnum.LIGHTINTENSITY.attribute_name())

        box = layout.box()
        box.label(text="Shape")
        box.prop(prop, MSFS2024LightPropertiesEnum.LIGHTSHAPE.attribute_name())
        light_shape = getattr(prop,MSFS2024LightPropertiesEnum.LIGHTSHAPE.attribute_name())

        if not light_shape == "point":
            box.prop(prop, MSFS2024LightPropertiesEnum.LIGHTSOURCERADIUS.attribute_name())

        box.prop(prop, MSFS2024LightPropertiesEnum.LIGHTINNERANGLE.attribute_name())
        box.prop(prop, MSFS2024LightPropertiesEnum.LIGHTOUTERANGLE.attribute_name())

        box = layout.box()
        box.label(text="Channels")
        box.prop(prop, MSFS2024LightPropertiesEnum.LIGHTCHANNELEXTERIOR.attribute_name())
        box.prop(prop, MSFS2024LightPropertiesEnum.LIGHTCHANNELINTERIOR.attribute_name())

        box = layout.box()
        box.label(text="Lens Flare")
        box.prop(prop, MSFS2024LightPropertiesEnum.FLARE_ENABLED.attribute_name())

    def draw_skyportal_light_properties(self, context, prop, layout):
        box = layout.box()

        box.label(text="Shape")
        box.label(text="Skyportal Preview is not supported in Evee", icon="INFO")
        box.prop(prop, MSFS2024LightPropertiesEnum.LIGHTSOURCERADIUS.attribute_name())
        box.prop(prop, MSFS2024LightPropertiesEnum.LIGHTINNERANGLE.attribute_name())
        box.prop(prop, MSFS2024LightPropertiesEnum.LIGHTOUTERANGLE.attribute_name())

    def draw(self, context):
        layout = self.layout
        active_object = context.object

        if active_object.type != 'LIGHT':
            return

        blender_light = active_object.data
        if blender_light is None:
            return

        prop = blender_light.msfs_light_properties

        layout.prop(blender_light, "msfs_light_type")

        if blender_light.msfs_light_type == MSFS2024LightType.STREET_LIGHT.identifier:
            self.draw_fast_light_properties(context, prop, layout)
        elif blender_light.msfs_light_type == MSFS2024LightType.ADVANCED_LIGHT.identifier:
            self.draw_advanced_light_properties(context, prop, layout)
        elif blender_light.msfs_light_type == MSFS2024LightType.SKYPORTAL_LIGHT.identifier:
            self.draw_skyportal_light_properties(context, prop, layout)