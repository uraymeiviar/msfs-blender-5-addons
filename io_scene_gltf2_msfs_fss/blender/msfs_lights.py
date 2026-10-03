from __future__ import annotations
from typing import TYPE_CHECKING
import math

from enum import Enum

from mathutils import Color
import bpy

from .utils.msfs_utils import MSFS2024_Enum_Properties

if TYPE_CHECKING:
    from mathutils import Vector

class MSFS2024LightType(Enum):
    NONE = ("NONE", "Disabled")
    STREET_LIGHT = ("streetLight", "MSFS2024 Street Light")
    ADVANCED_LIGHT =("advancedLight", "MSFS2024 Advanced Light")
    SKYPORTAL_LIGHT = ("skyPortalLight", "MSFS2024 SkyPortal Light")

    def __init__(self, identifier: str, label: str):
        self.identifier = identifier
        self.label = label

    @classmethod
    def from_identifier(cls, identifier: str) -> MSFS2024LightType | None:
        for mode in cls:
            if mode.identifier == identifier:
                return mode
        return None

class MSFS2024LightPropertiesEnum(MSFS2024_Enum_Properties):
    """
        Enum describing the parameters of lights contains Tuples of:
        ( 
            The name that appears in the UI, 
            Default Value, 
            attribute name of the property, 
            name that appear in the extension when it's exported/imported
        )
    """

    ## Parameters
    LIGHTTYPE = "Light Type", MSFS2024LightType.NONE.identifier, "msfs_light_type", None
    LIGHT_TEMPERATURE = "Kelvin", 6500, "msfs_light_temperature", None
    LIGHT_TEMPERATURE_PREVIEW = "Kelvin Preview", [1.0, 1.0, 1.0], "msfs_light_temperature_preview", None 
    USE_LIGHT_TEMPERATURE = "Use Kelvin", False, "msfs_light_use_temperature", None
    LIGHTCOLOR = "RGB", [1.0, 1.0, 1.0], "msfs_light_color", "color"
    LIGHTINTENSITY = "Intensity (cd)", 10000.0, "msfs_light_intensity", "intensity"
    LIGHTDAYTIMEINTENSITY = "Daytime Intensity Override (cd)", 10000.0, "msfs_light_daytime_intensity", "daytime_intensity"
    HASLIGHTSYMMETRY = "Has symmetry", False, "msfs_light_has_symmetry", "has_symmetry"
    LIGHTDAYNIGHTCYCLE = "Day/Night Cycle", False, "msfs_light_day_night_cycle", "day_night_cycle"
    LIGHTFLASHFREQUENCY = "Frequency (1/min)", 0.0, "msfs_light_flash_frequency", "flash_frequency"
    LIGHTFLASHDURATION = "Duration (s)", 0.2, "msfs_light_flash_duration", "flash_duration"
    LIGHTFLASHPHASE = "Phase (s)", 0.0, "msfs_light_flash_phase", "flash_phase"
    LIGHTROTATIONPHASE = "Rotation Phase", 0.0, "msfs_light_rotation_phase", "rotation_phase"
    LIGHTROTATIONSPEED = "Rotation Speed (RPM)", 0.0, "msfs_light_rotation_speed", "rotation_speed"
    LIGHTRANDOMPHASE = "Random Phase", True, "msfs_light_random_phase", "random_phase"
    LIGHTCONEANGLE = "Cone Angle", 45.0, "msfs_light_cone_angle", "cone_angle"
    LIGHTSHAPE = "Shape", "point", "msfs_light_shape_type", "shape_type"
    LIGHTSOURCERADIUS = "Source Radius (cm)", 50.0, "msfs_light_source_radius", "source_radius"
    LIGHTINNERANGLE = "Inner Angle", 0.0, "msfs_light_inner_angle", "inner_cone_angle"
    LIGHTOUTERANGLE = "Outer Angle", 160.0, "msfs_light_outer_angle", "outer_cone_angle"
    LIGHTCHANNELEXTERIOR = "Exterior", True, "msfs_light_channel_exterior", "channel_exterior"
    LIGHTCHANNELINTERIOR = "Interior", True, "msfs_light_channel_interior", "channel_interior"
    FLARE_ENABLED = "Lens Flare", True, "msfs_light_lens_flare", "flare_enabled"
    FLARE_ONLY = "Flare Only", False, "msfs_light_flare_only", "flare_only"

class MSFS2024LightProperties(bpy.types.PropertyGroup):

    @staticmethod
    def sync_blender_params(_self, context):
        """
        Set Blender light params in order to match
        engine rendering.
        """
        msfs_light_properties = None
        if isinstance(_self, bpy.types.Light):
            msfs_light_properties = _self.msfs_light_properties
        elif isinstance(_self, MSFS2024LightProperties):
            msfs_light_properties = _self

        if not msfs_light_properties:
            return

        msfs_light_properties: MSFS2024LightProperties
        light_data = msfs_light_properties.get_active_light_data()
        if light_data is None:
            return
        light_type = light_data.msfs_light_type
        if light_type == MSFS2024LightType.STREET_LIGHT.identifier:
            msfs_light_properties.set_street_light(light_data)
        elif light_type == MSFS2024LightType.ADVANCED_LIGHT.identifier:
            msfs_light_properties.set_advanced_light(light_data)
        elif light_type == MSFS2024LightType.SKYPORTAL_LIGHT.identifier:
            msfs_light_properties.set_skyportal_light(light_data)

    # region Common Light Methods
    def get_active_light_data(self):

        if isinstance(self, bpy.types.Light):
            return self

        light_data = self.id_data
        if not light_data:
            return None

        if not isinstance(light_data, bpy.types.Light):
            return None

        return light_data

    @staticmethod
    def set_change_attr(obj, attrib_name, value):
        """
        Only set Prop if value is different.
        Prevents unecessary assignment and viewport redraw.
        """
        old_value = getattr(obj, attrib_name, None)
        if old_value == value:
            return
        setattr(obj, attrib_name, value)

    @staticmethod
    def temperatureToColor(temperature):
        # Temperature to CIE 1960
        u = (
            (0.860117757 + 0.000154118254 * temperature + 0.000000128641212 * temperature * temperature)
            / (1.0 + 0.000842420235 * temperature + 0.000000708145163 * temperature * temperature)
        )
        v = (
            (0.317398726 + 0.0000422806245 * temperature + 0.0000000420481691 * temperature * temperature)
            / (1.0 - 0.0000289741816 * temperature + 0.000000161456053 * temperature * temperature)
        )

        # CIE to xyY
        xx = 3.0 * u / (2.0 * u - 8.0 * v + 4.0)
        yy = 2.0 * v / (2.0 * u - 8.0 * v + 4.0)
        Y = 1.0

        # xyY to XYZ
        X = xx * Y / yy
        Z = (1.0 - xx - yy) * Y / yy

        # XYZ to RGB (color primaries and white point from sRGB)
        R = 3.2404542 * X - 1.5371385 * Y - 0.4985314 * Z
        G = - 0.9692660 * X + 1.8760108 * Y + 0.0415560 * Z
        B = 0.0556434 * X - 0.2040259 * Y + 1.0572252 * Z

        # Normalize
        m = B
        if R > G and R > B:
            m = R

        if R <= G and G > B:
            m = G

        R /= m
        G /= m
        B /= m

        if R < 0: R = 0
        if G < 0: G = 0
        if B < 0: B = 0

        # convert to linear
        R=math.pow(R,2.2)
        G=math.pow(G,2.2)
        B=math.pow(B,2.2)

        return [R, G, B]

    @staticmethod
    def update_light_color(light_data):
        use_light_temperature = getattr(
            light_data.msfs_light_properties,
            MSFS2024LightPropertiesEnum.USE_LIGHT_TEMPERATURE.attribute_name(),
        )
        new_light_color = None
        if not use_light_temperature:

            new_light_color = getattr(
                light_data.msfs_light_properties,
                MSFS2024LightPropertiesEnum.LIGHTCOLOR.attribute_name(),
            )

        else:
            temperature = getattr(
                light_data.msfs_light_properties,
                MSFS2024LightPropertiesEnum.LIGHT_TEMPERATURE.attribute_name(),
            )

            new_light_color = Color(MSFS2024LightProperties.temperatureToColor(temperature))

            # Use [] operator to set attrib
            # It prevents infinite recursion with properties update calls
            light_data.msfs_light_properties[
                MSFS2024LightPropertiesEnum.LIGHTCOLOR.attribute_name()
            ] = new_light_color

            # Set color preview for UI Feedback
            setattr(
                light_data.msfs_light_properties,
                MSFS2024LightPropertiesEnum.LIGHT_TEMPERATURE_PREVIEW.attribute_name(),
                new_light_color,
            )

        MSFS2024LightProperties.set_change_attr(light_data, "color", new_light_color)

    @staticmethod
    def set_custom_distance(light_data, distance):
        """
        Set light cutoff distance
        """
        light_data.use_custom_distance = True
        light_data.cutoff_distance = distance

    @staticmethod
    def update_light_intensity(light_data):

        intensity = getattr(
            light_data.msfs_light_properties,
            MSFS2024LightPropertiesEnum.LIGHTINTENSITY.attribute_name(),
        )

        intensity = intensity * 4 * math.pi / 683  # cd to Watt
        distance = min(intensity / 3, 200)
        MSFS2024LightProperties.set_custom_distance(light_data, distance)
        intensity *= 10  # Compensate game exposure
        # Multiply lm/steradian by 4Pi to obtain total lumen as it was emitted in all direction
        MSFS2024LightProperties.set_change_attr(light_data, "energy", intensity)

    def switch_blender_light_type(self, light_data, type):
        """
        Switch blender light type and return light_data
        """
        MSFS2024LightProperties.set_change_attr(light_data, "type", type)
        # Force light Data refresh after type setup
        light_data = self.get_active_light_data()
        return light_data

    # endregion

    # region StreeLight

    def update_cone_angle(self, light_data):

        light_type = light_data.msfs_light_type
        if light_type == MSFS2024LightType.STREET_LIGHT.identifier:

            cone_angle = getattr(
                light_data.msfs_light_properties,
                MSFS2024LightPropertiesEnum.LIGHTCONEANGLE.attribute_name(),
            )
            if cone_angle <= 180:
                light_data = self.switch_blender_light_type(light_data, "SPOT")
                cone_angle = math.radians(cone_angle)
                light_data.spot_size = cone_angle
            else:
                # Switch to point since spot doesn't go over 180 angle
                light_data = self.switch_blender_light_type(light_data, "POINT")

    def update_flare_only(self, light_data):
        flare_only = getattr(
            light_data.msfs_light_properties,
            MSFS2024LightPropertiesEnum.FLARE_ONLY.attribute_name(),
        )
        if not flare_only:
            return
        # Switch to point light without energy
        light_data = self.switch_blender_light_type(light_data, "POINT")

        MSFS2024LightProperties.set_change_attr(light_data, "energy", 0)
        MSFS2024LightProperties.set_change_attr(light_data, "shadow_soft_size", 0.5)

    def set_street_light(self, light_data):
        # Setup Spot
        light_data = self.switch_blender_light_type(light_data, "SPOT")
        MSFS2024LightProperties.set_change_attr(light_data, "shadow_soft_size", 0)
        MSFS2024LightProperties.set_change_attr(light_data, "spot_blend", 1)
        MSFS2024LightProperties.set_change_attr(light_data, "use_shadow", False)

        MSFS2024LightProperties.update_light_color(light_data)
        MSFS2024LightProperties.update_light_intensity(light_data)
        self.update_cone_angle(light_data)
        self.update_flare_only(light_data)

    # endregion

    # region AdvancedLight and SkyportalLight
    @staticmethod
    def _update_spot_blend(light_data):
        inner_angle = getattr(
            light_data.msfs_light_properties,
            MSFS2024LightPropertiesEnum.LIGHTINNERANGLE.attribute_name(),
        )
        outer_angle = getattr(
            light_data.msfs_light_properties,
            MSFS2024LightPropertiesEnum.LIGHTOUTERANGLE.attribute_name(),
        )
        if outer_angle <= 0:
            light_data.spot_size = math.radians(1)
            return

        # Clamp outer angle because blend is not visible at 180°
        outer_angle = min(outer_angle, 179)

        inner_angle = min(inner_angle, outer_angle)

        outer_angle = math.radians(outer_angle)
        inner_angle = math.radians(inner_angle)

        light_data.spot_size = outer_angle

        # Pythagorean Trigonometric
        outer_opposite_distance = math.sin(outer_angle * 0.5)
        inner_opposite_distance = math.sin(inner_angle * 0.5)
        # Blend corresponds to amount of space that the inner cone should occupy inside the outer cone.
        # Subtracting the area of the smaller circle from the area of the larger one instead.
        outer_circle_area = math.pow(outer_opposite_distance, 2)
        inner_circle_area = math.pow(inner_opposite_distance, 2)
        blend = (outer_circle_area - inner_circle_area) / outer_circle_area
        MSFS2024LightProperties.set_change_attr(light_data, "spot_blend", blend)

    def update_inner_outer_angle(self, light_data, switch_to_point = False):
        """
        Inner outer angle for best visual fidelity.
        Can switch to point light when spot angle > 180
        """
        light_data: bpy.types.Light

        outer_angle = getattr(
            light_data.msfs_light_properties,
            MSFS2024LightPropertiesEnum.LIGHTOUTERANGLE.attribute_name(),
        )

        if switch_to_point and outer_angle >= 180 :
            light_data = self.switch_blender_light_type(light_data, "POINT")

        else :
            # Switch to point since spot doesn't go over 180 angle
            light_data = self.switch_blender_light_type(light_data, "SPOT")   
            MSFS2024LightProperties._update_spot_blend(light_data)

    def set_advanced_light(self, light_data):

        light_data = self.switch_blender_light_type(light_data, "SPOT")
        shape = getattr(
            light_data.msfs_light_properties,
            MSFS2024LightPropertiesEnum.LIGHTSHAPE.attribute_name(),
        )
        if shape == "point":
            MSFS2024LightProperties.set_change_attr(
                light_data,
                "shadow_soft_size",
                0
            )
        else:
            radius = getattr(
                light_data.msfs_light_properties,
                MSFS2024LightPropertiesEnum.LIGHTSOURCERADIUS.attribute_name(),
            )
            radius_meter = radius / 100
            MSFS2024LightProperties.set_change_attr(
                light_data, 
                "shadow_soft_size", 
                radius_meter
            )

        MSFS2024LightProperties.set_change_attr(light_data, "spot_blend", 1)
        MSFS2024LightProperties.set_change_attr(light_data, "use_shadow", False)

        MSFS2024LightProperties.update_light_color(light_data)
        MSFS2024LightProperties.update_light_intensity(light_data)
        self.update_inner_outer_angle(light_data, switch_to_point=True)

    def set_skyportal_light(self, light_data):
        """
        Not rendered in evee. We use a spotlight with no energy 
        to visualize gizmo.
        """
        light_data = self.switch_blender_light_type(light_data, "SPOT")

        # Set light shape, important for extension export
        MSFS2024LightProperties.set_change_attr(
            light_data.msfs_light_properties, 
            MSFS2024LightPropertiesEnum.LIGHTSHAPE.attribute_name(), 
            "disc"
        )

        radius = getattr(
            light_data.msfs_light_properties,
            MSFS2024LightPropertiesEnum.LIGHTSOURCERADIUS.attribute_name(),
        )
        radius_meter = radius / 100

        MSFS2024LightProperties.set_change_attr(
            light_data, 
            "shadow_soft_size", 
            radius_meter
        )

        MSFS2024LightProperties.set_change_attr(light_data, "use_shadow", False)

        MSFS2024LightProperties.set_change_attr(light_data, "energy", 0)
        # Set cutoff distance to 0 to remove useless distance preview
        MSFS2024LightProperties.set_change_attr(light_data, "use_custom_distance", True)
        MSFS2024LightProperties.set_change_attr(light_data, "cutoff_distance", 0)

        self.update_inner_outer_angle(light_data, switch_to_point=False)

    # endregion

    msfs_light_use_temperature: bpy.props.BoolProperty(
        name=MSFS2024LightPropertiesEnum.USE_LIGHT_TEMPERATURE.property_name(),
        default=MSFS2024LightPropertiesEnum.USE_LIGHT_TEMPERATURE.default_value(),
        update=MSFS2024LightProperties.sync_blender_params
    ) # type: ignore

    msfs_light_temperature: bpy.props.FloatProperty(
        name=MSFS2024LightPropertiesEnum.LIGHT_TEMPERATURE.property_name(),
        default=MSFS2024LightPropertiesEnum.LIGHT_TEMPERATURE.default_value(),
        min=1000.0,
        max=10000,
        update=MSFS2024LightProperties.sync_blender_params,
        subtype = "TEMPERATURE",
        step=100
    ) # type: ignore

    msfs_light_temperature_preview: bpy.props.FloatVectorProperty(
        name=MSFS2024LightPropertiesEnum.LIGHT_TEMPERATURE_PREVIEW.property_name(),
        default=MSFS2024LightPropertiesEnum.LIGHT_TEMPERATURE_PREVIEW.default_value(),
        min=0,
        max=1,
        subtype="COLOR",
        size=3
    ) # type: ignore

    msfs_light_color: bpy.props.FloatVectorProperty(
        name=MSFS2024LightPropertiesEnum.LIGHTCOLOR.property_name(),
        default=MSFS2024LightPropertiesEnum.LIGHTCOLOR.default_value(),
        min=0,
        max=1,
        subtype="COLOR",
        size=3,
        update=MSFS2024LightProperties.sync_blender_params
    )  # type: ignore

    msfs_light_intensity: bpy.props.FloatProperty(
        name=MSFS2024LightPropertiesEnum.LIGHTINTENSITY.property_name(),
        default=MSFS2024LightPropertiesEnum.LIGHTINTENSITY.default_value(),
        soft_max=1000000,
        step=100,
        update=MSFS2024LightProperties.sync_blender_params
    )  # type: ignore

    msfs_light_daytime_intensity: bpy.props.FloatProperty(
        name=MSFS2024LightPropertiesEnum.LIGHTDAYTIMEINTENSITY.property_name(),
        default=MSFS2024LightPropertiesEnum.LIGHTDAYTIMEINTENSITY.default_value(),
        soft_max=1000000,
        step=100
    )  # type: ignore

    msfs_light_has_symmetry: bpy.props.BoolProperty(
        name=MSFS2024LightPropertiesEnum.HASLIGHTSYMMETRY.property_name(),
        default=MSFS2024LightPropertiesEnum.HASLIGHTSYMMETRY.default_value(),
        description=("Enable Light Symmetry.\n"
                     "INFO : Light Symmetry preview not supported in Evee")
    )  # type: ignore

    msfs_light_flash_frequency: bpy.props.FloatProperty(
        name=MSFS2024LightPropertiesEnum.LIGHTFLASHFREQUENCY.property_name(),
        default=MSFS2024LightPropertiesEnum.LIGHTFLASHFREQUENCY.default_value(),
        min=0.0
    )  # type: ignore

    msfs_light_flash_duration: bpy.props.FloatProperty(
        name=MSFS2024LightPropertiesEnum.LIGHTFLASHDURATION.property_name(),
        default=MSFS2024LightPropertiesEnum.LIGHTFLASHDURATION.default_value(),
        min=0.0
    )  # type: ignore

    msfs_light_flash_phase: bpy.props.FloatProperty(
        name=MSFS2024LightPropertiesEnum.LIGHTFLASHPHASE.property_name(),
        default=MSFS2024LightPropertiesEnum.LIGHTFLASHPHASE.default_value()
    )  # type: ignore

    msfs_light_rotation_speed: bpy.props.FloatProperty(
        name=MSFS2024LightPropertiesEnum.LIGHTROTATIONSPEED.property_name(),
        default=MSFS2024LightPropertiesEnum.LIGHTROTATIONSPEED.default_value()
    )  # type: ignore

    msfs_light_rotation_phase: bpy.props.FloatProperty(
        name=MSFS2024LightPropertiesEnum.LIGHTROTATIONPHASE.property_name(),
        default=MSFS2024LightPropertiesEnum.LIGHTROTATIONPHASE.default_value()
    )  # type: ignore

    msfs_light_random_phase: bpy.props.BoolProperty(
        name=MSFS2024LightPropertiesEnum.LIGHTRANDOMPHASE.property_name(),
        default=MSFS2024LightPropertiesEnum.LIGHTRANDOMPHASE.default_value()
    )  # type: ignore

    msfs_light_day_night_cycle: bpy.props.BoolProperty(
        name=MSFS2024LightPropertiesEnum.LIGHTDAYNIGHTCYCLE.property_name(),
        default=MSFS2024LightPropertiesEnum.LIGHTDAYNIGHTCYCLE.default_value(),
        description="Set this value to 'true' if you want the light to be visible at night only."
    )  # type: ignore

    msfs_light_cone_angle: bpy.props.FloatProperty(
        name=MSFS2024LightPropertiesEnum.LIGHTCONEANGLE.property_name(),
        min = 0,
        max = 360,
        default=MSFS2024LightPropertiesEnum.LIGHTCONEANGLE.default_value(),
        description="This value sets the cone angle of the light.",
        update=MSFS2024LightProperties.sync_blender_params
    )  # type: ignore

    msfs_light_shape_type: bpy.props.EnumProperty(
        name=MSFS2024LightPropertiesEnum.LIGHTSHAPE.property_name(),
        description="Shape of the light",
        items=(
            ("point", "Point", ""),
            ("sphere", "Sphere", ""),
            ("disc", "Disc", "")
        ),
        default=MSFS2024LightPropertiesEnum.LIGHTSHAPE.default_value(),
        update=MSFS2024LightProperties.sync_blender_params
        
    )  # type: ignore

    msfs_light_source_radius: bpy.props.FloatProperty(
        name=MSFS2024LightPropertiesEnum.LIGHTSOURCERADIUS.property_name(),
        default=MSFS2024LightPropertiesEnum.LIGHTSOURCERADIUS.default_value(),
        min=1.0,
        update=MSFS2024LightProperties.sync_blender_params,
        description=("Light source radius.\n"
                     "INFO : Disc Source Radius preview not supported in Evee")
    )  # type: ignore

    msfs_light_inner_angle: bpy.props.FloatProperty(
        name=MSFS2024LightPropertiesEnum.LIGHTINNERANGLE.property_name(),
        default=MSFS2024LightPropertiesEnum.LIGHTINNERANGLE.default_value(),
        min = 0,
        max = 360,
        update=MSFS2024LightProperties.sync_blender_params
    )  # type: ignore

    msfs_light_outer_angle: bpy.props.FloatProperty(
        name=MSFS2024LightPropertiesEnum.LIGHTOUTERANGLE.property_name(),
        default=MSFS2024LightPropertiesEnum.LIGHTOUTERANGLE.default_value(),
        min = 0,
        max = 360,
        update=MSFS2024LightProperties.sync_blender_params
    )  # type: ignore

    msfs_light_channel_exterior: bpy.props.BoolProperty(
        name=MSFS2024LightPropertiesEnum.LIGHTCHANNELEXTERIOR.property_name(),
        default=MSFS2024LightPropertiesEnum.LIGHTCHANNELEXTERIOR.default_value()
    )  # type: ignore

    msfs_light_channel_interior: bpy.props.BoolProperty(
        name=MSFS2024LightPropertiesEnum.LIGHTCHANNELINTERIOR.property_name(),
        default=MSFS2024LightPropertiesEnum.LIGHTCHANNELINTERIOR.default_value()
    )  # type: ignore

    msfs_light_lens_flare: bpy.props.BoolProperty(
        name=MSFS2024LightPropertiesEnum.FLARE_ENABLED.property_name(),
        default=MSFS2024LightPropertiesEnum.FLARE_ENABLED.default_value(),
        description=("Enable light lens flare.\n"
                     "INFO : Lens Flare preview not supported in Evee")
    )  # type: ignore

    msfs_light_flare_only: bpy.props.BoolProperty(
        name=MSFS2024LightPropertiesEnum.FLARE_ONLY.property_name(),
        default=MSFS2024LightPropertiesEnum.FLARE_ONLY.default_value(),
        update=MSFS2024LightProperties.sync_blender_params,
        description=("Enable light without energy, only flare.\n"
                     "INFO : Flare preview not supported in Evee")
    )  # type: ignore


# region Light creation
def set_light_data(
    msfs_light_type: MSFS2024LightType, light_data: bpy.types.Light
) -> bpy.types.Light:
    label = msfs_light_type.label

    light_data.name = label

    setattr(
        light_data,
        MSFS2024LightPropertiesEnum.LIGHTTYPE.attribute_name(),
        msfs_light_type.identifier,
    )
    setattr(
        light_data.msfs_light_properties,
        MSFS2024LightPropertiesEnum.LIGHTINTENSITY.attribute_name(),
        MSFS2024LightPropertiesEnum.LIGHTINTENSITY.default_value(),
    )

    return light_data


def _create_light_data(msfs_light_type: MSFS2024LightType) -> bpy.types.Light:
    light_data = bpy.data.lights.new(name=msfs_light_type.label, type="POINT")
    set_light_data(msfs_light_type, light_data)

    return light_data


def create_light_object(msfs_light_type: MSFS2024LightType) -> bpy.types.Object:
    light_data = _create_light_data(msfs_light_type)
    light_object = bpy.data.objects.new(light_data.name, light_data)
    return light_object


def add_light(
    msfs_light_type: MSFS2024LightType,
    view_layer: bpy.types.ViewLayer,
    collection: bpy.types.Collection,
    location: list | Vector = [0, 0, 0],
):
    """Add light in provided collection.
    Deselect other objects and set light object as active
    """
    light_obj = create_light_object(msfs_light_type)
    try:
        collection.objects.link(light_obj)
    except:
        pass
    light_obj.location = location

    for obj in view_layer.objects:
        obj.select_set(False)  # Deselect all objects

    # Set new light as active
    view_layer.objects.active = light_obj
    light_obj.select_set(True)  # Select the new light
    return light_obj

def _force_update_msfs_properties(light_data: bpy.types.Light):
    """
    Force msfs_properties update.
    """
    if light_data.msfs_light_type == MSFS2024LightType.NONE.identifier:
        return

    light_data.msfs_light_type = light_data.msfs_light_type

def force_update_all_lights():

    for light_data in bpy.data.lights:
        _force_update_msfs_properties(light_data)
# endregion


def register():
    bpy.types.Light.msfs_light_type = bpy.props.EnumProperty(
        name="Type",
        description="Type of light to add",
        items=((MSFS2024LightType.NONE.identifier, MSFS2024LightType.NONE.label, ""),
               (MSFS2024LightType.STREET_LIGHT.identifier, MSFS2024LightType.STREET_LIGHT.label, ""),
               (MSFS2024LightType.ADVANCED_LIGHT.identifier, MSFS2024LightType.ADVANCED_LIGHT.label, ""),
               (MSFS2024LightType.SKYPORTAL_LIGHT.identifier, MSFS2024LightType.SKYPORTAL_LIGHT.label, "")
               ),
        default=MSFS2024LightType.NONE.identifier,
        update=MSFS2024LightProperties.sync_blender_params
    )

    bpy.types.Light.msfs_light_properties = bpy.props.PointerProperty(type=MSFS2024LightProperties)

def unregister():
    
    try:
        del bpy.types.Light.msfs_light_type
        del bpy.types.Light.msfs_light_properties
    except :
        pass
