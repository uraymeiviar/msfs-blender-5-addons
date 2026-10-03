import bpy
from pathlib import Path
from ..utils.msfs_material_utils import MSFS2024_MaterialProperties


class MSFS2024_OT_SetPbrTextureSet(bpy.types.Operator):
    bl_idname = "msfs2024.set_pbr_texture_set"
    bl_label = "Assign Base Texture Set"
    bl_description = (
        "Browse for a base texture and automatically assign\n"
        "associated textures based on the following filename suffixes:\n"
        "Albedo Map : _albd\n"
        "Comp Map : _comp\n"
        "Normal Map : _norm\n"
        "Emissive Map : _emis\n"
    )
    bl_options = {"INTERNAL"}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")  # type: ignore
    material_name: bpy.props.StringProperty()  # type: ignore
    set_base_color: bpy.props.BoolProperty(default=True)  # type: ignore
    set_composite: bpy.props.BoolProperty(default=True)  # type: ignore
    set_normal: bpy.props.BoolProperty(default=True)  # type: ignore
    set_emissive: bpy.props.BoolProperty(default=True)  # type: ignore

    
    def execute(self, context):

        # Convert the selected file path to a Path object
        selected_path = Path(self.filepath)
        directory = selected_path.parent
        filename_stem = selected_path.stem
        extension = selected_path.suffix

        # Define labels and their corresponding suffixes
        suffixes = {
            "base_color": ["albd", "albedo"],
            "composite": ["comp"],
            "normal": ["norm", "normal"],
            "emisive": ["emis", "emissive"],
        }

        # Attempt to split the stem into base name and suffix
        parts = filename_stem.rsplit("_", 1)
        if len(parts) != 2:
            self.report({"ERROR"}, "Filename does not match expected pattern")
            return {"CANCELLED"}

        base_name, current_suffix = parts

        # Load images
        images = {}
        for label, suffixes in suffixes.items():
            for suffix in suffixes:
                image_name = f"{base_name}_{suffix}{extension}"
                image_path = directory / image_name
                if image_path.exists():
                    try:
                        image = bpy.data.images.load(
                            str(image_path), check_existing=True
                        )
                        images[label] = image
                    except Exception as e:
                        print({"WARNING"}, f"Failed to load {label} texture: {e}")

                    break
                else:
                    self.report({"INFO"}, f"{label} texture not found: {image_name}")

        if not images:
            self.report({"ERROR"}, "Invalid File")
            return {"CANCELLED"}
        mat = None
        if self.material_name:
            mat = bpy.data.materials.get(self.material_name, None)
            if not mat:
                return {"CANCELLED"}
        else:
            self.report({"ERROR"}, "Invalid Material")
            return {"CANCELLED"}

        albd_attrib = MSFS2024_MaterialProperties.BASECOLORTEXTURE.attribute_name()
        comp_attrib = MSFS2024_MaterialProperties.OMRTEXTURE.attribute_name()
        norm_attrib = MSFS2024_MaterialProperties.NORMALTEXTURE.attribute_name()
        emis_attrib = MSFS2024_MaterialProperties.EMISSIVETEXTURE.attribute_name()

        # Link textures to the principled shader
        if self.set_base_color and "base_color" in images:
            setattr(mat, albd_attrib, images["base_color"])
        if self.set_composite and "composite" in images:
            setattr(mat, comp_attrib, images["composite"])
        if self.set_normal and "normal" in images:
            setattr(mat, norm_attrib, images["normal"])
        if self.set_emissive and "emisive" in images:
            setattr(mat, emis_attrib, images["emisive"])

        self.report({"INFO"}, "Textures assigned successfully")
        return {"FINISHED"}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}
    
    set_default_filter_settings = True
    def draw(self, context):
        # Only show image when selecting file
        if self.set_default_filter_settings:
            context.space_data.params.use_filter = True
            context.space_data.params.use_filter_image = True
            context.space_data.params.use_filter_folder = True
            self.set_default_filter_settings = False
