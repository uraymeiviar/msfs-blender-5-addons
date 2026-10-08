from __future__ import annotations

from enum import Enum

import bpy

from _addons_common import data_utils

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
    STRAIGHT = "STRAIGHT"
    PREMUL = "PREMUL"
    CHANNEL_PACKED = "CHANNEL_PACKED"
    NONE = "NONE"

class ImageColorSpace(Enum):
    SRGB = "sRGB"
    NON_COLOR = "Non-Color"


def _validate_image_alpha_mode(
    image: bpy.types.Image, 
    alpha_mode: ImageAlphaMode
) -> bool:
    valid_alpha = image.alpha_mode == alpha_mode.value

    if valid_alpha:
        return True

    compatible_alpha_modes = (ImageAlphaMode.CHANNEL_PACKED.value, ImageAlphaMode.STRAIGHT.value)

    if alpha_mode == ImageAlphaMode.NONE and image.alpha_mode in compatible_alpha_modes:
        # can use an image with alpha in a slot that does not need it
        valid_alpha = True
    elif image.alpha_mode == ImageAlphaMode.NONE.value and alpha_mode.value in compatible_alpha_modes:
        # enable alpha on image
        image.alpha_mode = alpha_mode.value
        valid_alpha = True
    elif alpha_mode in compatible_alpha_modes and image.alpha_mode in compatible_alpha_modes:
        valid_alpha = True

    return valid_alpha


def validate_image(
    image: bpy.types.Image,
    alpha_mode: ImageAlphaMode = ImageAlphaMode.CHANNEL_PACKED,
    colorspace: ImageColorSpace = ImageColorSpace.SRGB,
) -> bpy.types.Image:
    """Ensure that an image has the expected alpha mode and colorspace.

    If the image does not match the expected settings, attempt to find another
    image with the same filepath that does. If none is found, create a new image
    with the correct settings.

    Returns:
        bpy.types.Image: A valid image matching the requested settings.
    """
    colorspace_settings_name = ""
    if image.colorspace_settings:
        colorspace_settings_name = image.colorspace_settings.name

    valid_colorspace_settings = colorspace_settings_name == colorspace.value
    if valid_colorspace_settings:

        if _validate_image_alpha_mode(image, alpha_mode):
            return image

    image_is_new = image.users <= 1

    # Check if another image has compatible settings, if not create a new image
    if not image_is_new:
        image_clean_name = data_utils.remove_number_suffix(image.name)

        alternative: bpy.types.Image | None = None
        for img in bpy.data.images:
            if img == image:
                continue

            if not image.filepath : # Image is packed in blend file
                # In this case, reuse image only if name are identical
                clean_name = data_utils.remove_number_suffix(img.name)
                if not image_clean_name == clean_name:
                    continue
            elif img.filepath != image.filepath:
                continue

            img_colorspace_settings = ""
            if img.colorspace_settings:
                img_colorspace_settings = img.colorspace_settings.name

            if img_colorspace_settings != colorspace.value:
                continue

            if _validate_image_alpha_mode(img, alpha_mode):
                alternative = img
                break

        original_name = image.name
        log_start = f"Image '{original_name}' does not have the expected colorspace or alpha mode: "
        if alternative:
            print(log_start + f"'{alternative.name}' instead.")
            return alternative
        
        if not image.filepath : #image is not saved on disk, can be packed in blend file
            image = image.copy()
        else:
            try:
                image = bpy.data.images.load(image.filepath, check_existing=False)
            except:
                # in case image is not found on disk
                image = image.copy()
    
        print(log_start + f"Use a copy '{image.name}'")

    image.alpha_mode = alpha_mode.value
    if image.colorspace_settings:
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
