from __future__ import annotations

from enum import Enum

import bpy

class MSFS2024ImageFlagsEnum(Enum):
    """
        Enum describing the parameters of image contains Tuples of:
        ( 
            The name that appears in the UI, 
            Default Value, 
            attribute name of the property, 
            name that appear in the flags when it's exported/imported
        )
    """

    ## Parameters
    QUALITYHIGH = "Quality High", False, "msfs_image_quality_high", "+QUALITYHIGH"
    ALPHAPRESERVATION = "Alpha Preservation", False, "msfs_image_alpha_preserv", "+ALPHAPRESERVATION"
    NOREDUCTION = "No Reduction", False, "msfs_image_no_reduction", "+NOREDUCE"
    NOMIPMAP = "No Mipmap", False, "msfs_image_no_mipmap", "+NOMIPMAP"
    PRECOMPUTEDINVAVG = "PreComputed Inverse Average", False, "msfs_image_prec_inv_avg", "+PRECOMPUTEDINVAVG"
    ANISOTROPIC = "Anisotropic", None, "msfs_image_anisotropic", "+ANISOTROPIC="

    def flag_name(self):
        assert isinstance(self.value, tuple) and len(self.value) > 0
        if isinstance(self.value, tuple) and len(self.value) > 0:
            return self.value[0]
        return None

    def default_value(self):
        assert isinstance(self.value, tuple) and len(self.value) > 1
        if isinstance(self.value, tuple) and len(self.value) > 1:
            return self.value[1]
        return None

    def attribute_name(self):
        assert isinstance(self.value, tuple) and len(self.value) > 2
        if isinstance(self.value, tuple) and len(self.value) > 2:
            return self.value[2]
        return None

    def flag_code(self):
        assert isinstance(self.value, tuple) and len(self.value) > 3
        if isinstance(self.value, tuple) and len(self.value) > 3:
            return self.value[3]
        return None

class MSFS2024ImageFlags(bpy.types.PropertyGroup):
    

    msfs_image_quality_high: bpy.props.BoolProperty(
        name=MSFS2024ImageFlagsEnum.QUALITYHIGH.flag_name(),
        default=MSFS2024ImageFlagsEnum.QUALITYHIGH.default_value(),
    ) # type: ignore

    msfs_image_alpha_preserv: bpy.props.BoolProperty(
        name=MSFS2024ImageFlagsEnum.ALPHAPRESERVATION.flag_name(),
        default=MSFS2024ImageFlagsEnum.ALPHAPRESERVATION.default_value(),
    ) # type: ignore

    msfs_image_no_reduction: bpy.props.BoolProperty(
        name=MSFS2024ImageFlagsEnum.NOREDUCTION.flag_name(),
        default=MSFS2024ImageFlagsEnum.NOREDUCTION.default_value(),
    ) # type: ignore

    msfs_image_no_mipmap: bpy.props.BoolProperty(
        name=MSFS2024ImageFlagsEnum.NOMIPMAP.flag_name(),
        default=MSFS2024ImageFlagsEnum.NOMIPMAP.default_value(),
    ) # type: ignore

    msfs_image_prec_inv_avg: bpy.props.BoolProperty(
        name=MSFS2024ImageFlagsEnum.PRECOMPUTEDINVAVG.flag_name(),
        default=MSFS2024ImageFlagsEnum.PRECOMPUTEDINVAVG.default_value(),

    ) # type: ignore

    msfs_image_anisotropic: bpy.props.EnumProperty(
        name=MSFS2024ImageFlagsEnum.ANISOTROPIC.flag_name(),
        items = (
            ("NONE", "Disabled", ""),
            ("0", "x0 (Standard)", ""),
            ("2", "x2 (High)", ""),
            ("4", "x4 (Very High)", ""),
            ("8", "x8 (Extreme)", ""),
            ("16", "x16 (Insane)", "")
        ),
    ) # type: ignore

    def to_string(self):
        result = ""
        result += MSFS2024ImageFlagsEnum.QUALITYHIGH.flag_code() if self.msfs_image_quality_high else ""
        result += MSFS2024ImageFlagsEnum.ALPHAPRESERVATION.flag_code() if self.msfs_image_alpha_preserv else ""
        result += MSFS2024ImageFlagsEnum.NOREDUCTION.flag_code() if self.msfs_image_no_reduction else ""
        result += MSFS2024ImageFlagsEnum.NOMIPMAP.flag_code() if self.msfs_image_no_mipmap else ""
        result += MSFS2024ImageFlagsEnum.PRECOMPUTEDINVAVG.flag_code() if self.msfs_image_prec_inv_avg else ""
        result += MSFS2024ImageFlagsEnum.ANISOTROPIC.flag_code() +  self.msfs_image_anisotropic if self.msfs_image_anisotropic != "NONE" else ""
        return result

class ImageAlphaMode(Enum):
    straight = "STRAIGHT"
    premul = "PREMUL"
    channel_packed = "CHANNEL_PACKED"
    none = "NONE"

class ImageColorSpace(Enum):
    srgb = "sRGB"
    non_color = "Non-Color"

def validate_image(
    image: bpy.types.Image,
    alpha_mode: ImageAlphaMode = ImageAlphaMode.channel_packed,
    colorspace: ImageColorSpace = ImageColorSpace.srgb,
) -> bpy.types.Image:
    """Ensure that an image has the expected alpha mode and colorspace.

    If the image does not match the expected settings, attempt to find another
    image with the same filepath that does. If none is found, create a new image
    with the correct settings.

    Returns:
        bpy.types.Image: A valid image matching the requested settings.
    """
    if (
        image.alpha_mode == alpha_mode.value
        and image.colorspace_settings.name == colorspace.value
    ):
        return image

    image_is_new = image.users <= 1

    # Check if another image has same settings, if not create a new image
    if not image_is_new:
        same_settings_image = None
        for img in bpy.data.images:
            if img == image:
                continue
            if (
                img.filepath == image.filepath
                and img.alpha_mode == alpha_mode.value
                and img.colorspace_settings.name == colorspace.value
            ):
                same_settings_image = img
                break

        if same_settings_image:
            return same_settings_image

        image = bpy.data.images.load(image.filepath, check_existing=False)

    image.alpha_mode = alpha_mode.value
    image.colorspace_settings.name = colorspace.value

    return image


def register():
    bpy.types.Image.msfs_flags = bpy.props.PointerProperty(
        name="Flags", 
        type=MSFS2024ImageFlags
    )

def unregister():
    try:
        del bpy.types.Image.msfs_flags
    except:
        pass
