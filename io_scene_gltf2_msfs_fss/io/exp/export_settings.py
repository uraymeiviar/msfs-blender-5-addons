from __future__ import annotations

from enum import Enum

import bpy

from io_scene_gltf2_msfs_fss.blender.utils import bpy_props as bpy_props_utils
from _addons_common import collection_prop_utils

from ..com.msfs_constants import (
    EXPORT_ANIMATION_MODE,
    EXPORT_IMAGE_FORMAT
)

# region Properties Group
class PerObjectTransformReset(bpy.types.PropertyGroup):
    """Transform export settings, used when MSFS2024_MultiExporterSettings.reset_origins
    is set to "PER_OBJECT"
    """
    reset_translation: bpy.props.BoolProperty(
        name="Reset Translation",
        default=False,
        description=(
            "Reset translation of the node.\n" 
            "If enabled, the translation will be reset to (0.0, 0.0, 0.0).\n"
            "WARNING : Effective only when reset origins is set to 'Per Object' in export settings"
        )
    ) # type: ignore
    
    reset_rotation: bpy.props.BoolProperty(
        name="Reset Rotation",
        default=False,
        description=(
            "Reset rotation of the node.\n" 
            "If enabled, the rotation will be reset to (0.0, 0.0, 0.0).\n"
            "WARNING : Effective only when reset origins is set to 'Per Object' in export settings"
        )
    ) # type: ignore
    
    reset_scale: bpy.props.BoolProperty(
        name="Reset Scale",
        default=False,
        description=(
            "Reset scale of the node.\n" 
            "If enabled, the scale will be reset to (0.0, 0.0, 0.0).\n"
            "WARNING : Effective only when reset origins is set to 'Per Object' in export settings"
        )
    ) # type: ignore

class RootTransformReset(bpy.types.PropertyGroup):
    """Transform export settings for root nodes, used when MSFS2024_MultiExporterSettings.reset_origins
    is set to ALL_ROOTS.
    """
    reset_translation: bpy.props.BoolProperty(
        name="Reset Translation",
        default=True,
        description=(
            "Reset translation of the root node.\n" 
            "If enabled, the translation will be reset to (0.0, 0.0, 0.0).\n"
        )
    ) # type: ignore

    reset_rotation: bpy.props.BoolProperty(
        name="Reset Rotation",
        default=True,
        description=(
            "Reset rotation of the root node.\n" 
            "If enabled, the rotation will be reset to (0.0, 0.0, 0.0).\n"
        )
    ) # type: ignore

    reset_scale: bpy.props.BoolProperty(
        name="Reset Scale",
        default=True,
        description=(
            "Reset scale of the root node.\n" 
            "If enabled, the scale will be reset to (0.0, 0.0, 0.0).\n"
        )
    ) # type: ignore


class ResetOriginMode(Enum):
    DISABLED = ("DISABLED", "Disabled")
    ALL_ROOTS = ("ALL_ROOTS", "All Roots")
    PER_OBJECT = ("PER_OBJECT", "Per Object")

    def __init__(self, identifier: str, label: str):
        self.identifier = identifier
        self.label = label

    @classmethod
    def from_identifier(cls, identifier: str) -> ResetOriginMode | None:
        for mode in cls:
            if mode.identifier == identifier:
                return mode
        return None


class MSFS2024_MultiExporterSettings(bpy.types.PropertyGroup):

    DEFAULT_PRESET_NAME = "Default"
    register_order = 1 #register after ResetTransform Class

    def _on_enable_msfs_extension(self, context: bpy.types.Context):
        if bpy.app.version < (4, 2, 0):
            self.export_nla_strips = True
            return

        self.export_animation_mode = 'NLA_TRACKS'
        if self.enable_msfs_extension:
            self.export_influence_nb = min(self.export_influence_nb, 4)

    def _set_influence_nb(self, value: int):
        self["export_influence_nb"] = value
        if not self.enable_msfs_extension:
            return

        if value > 4:
            self["export_influence_nb"] = 4

    def _get_influence_nb(self):
        return self.get("export_influence_nb", 4)

    def _get_export_animation_mode(self)->int:
        """
        Safely get export animation mode.
        """
        return bpy_props_utils.safe_enum_prop_get(
            _self=self,
            enum_name= "export_animation_mode",
            enum_indexes= range(len(EXPORT_ANIMATION_MODE)), 
            default_index=1
        )

    def _set_export_animation_mode(self, value: int):
        """Does nothing  special, enum_property needs to be provided a set function
        when defining a custom get function.
        """
        self["export_animation_mode"] = value

    # region General Options

    # keep original texture option Check
    export_keep_originals: bpy.props.BoolProperty(
        name="Keep original",
        description=(
            "Keep original textures files if possible. "
            "WARNING: if you use more than one texture, "
            "where pbr standard requires only one, only one texture will be used. "
            "This can lead to unexpected results"
        ),
        default=True,
    )  # type: ignore

    # Texture directory path
    export_texture_dir: bpy.props.StringProperty(
        name="Textures",
        description="Folder to place texture files in (if you don't set an absolute path,"
                     "it will be relative to your exported models)",
        default=""
    ) # type: ignore

    # Copyright string UI
    export_copyright: bpy.props.StringProperty(
        name="Copyright",
        description="Legal rights and conditions for the model",
        default=""
    ) # type: ignore

    # Remember export settings check
    will_save_settings: bpy.props.BoolProperty(
        name="Remember Export Settings",
        description="Store glTF export settings in the Blender project.",
        default=True
    ) # type: ignore
    # endregion

    # region MSFS2024 Parameters
    enable_msfs_extension: bpy.props.BoolProperty(
        name="Use Microsoft Flight Simulator 2024 Extensions",
        description="Enable Microsoft Flight Simulator 2024 Extensions",
        default=True,
        update=_on_enable_msfs_extension
    ) # type: ignore

    # Texture Lib
    generate_texturelib: bpy.props.BoolProperty(
        name="Generate TextureLib",
        description="Generate XMLs for the textures after the export",
        default=True,
    ) # type: ignore

    # Export Process
    reset_origins: bpy.props.EnumProperty(
        name="Reset Origins",
        items=(
                (
                    ResetOriginMode.DISABLED.identifier,
                    ResetOriginMode.DISABLED.label,
                    "Disable reset of origins"
                ),
                (
                    ResetOriginMode.ALL_ROOTS.identifier,
                    ResetOriginMode.ALL_ROOTS.label,
                    "Reset translation, rotation and scale of exported gltf's root nodes"
                ),
                (
                    ResetOriginMode.PER_OBJECT.identifier,
                    ResetOriginMode.PER_OBJECT.label,
                    "Reset translation, rotation and scale of specified nodes according\n"
                    "to the object parameters specified in the MSFS2024 Transform Properties panel:\n"
                    "Reset translation, Reset rotation and Reset scale"
                )
            ),
            description="Reset Origins options",
            default=ResetOriginMode.DISABLED.identifier
    ) # type: ignore

    export_transform_properties: bpy.props.PointerProperty(
        name="Export Transform Properties",
        type=RootTransformReset,
        description="Reset Transform Properties for MSFS2024 Root Nodes"
    ) # type: ignore

    remove_lod_prefix: bpy.props.BoolProperty(
        name="Remove LOD prefix",
        description="Remove LOD prefixes 'x0_/x1_...' on node names",
        default=False
    ) # type: ignore

    merge_nodes: bpy.props.BoolProperty(
        name="Merge nodes",
        description="Merge Meshes into one root mesh to export",
        default=False
    ) # type: ignore

    export_as_submodel: bpy.props.BoolProperty(
        name="Export as submodel",
        description="This option is dedicated to 'Merge models'\n"
                    "(You need to use it for models contained in <MergeModel> element in the xml only)",
        default=False
    ) # type: ignore
    # endregion

    # region Include Options
    # Export Selected Only Check
    use_selection: bpy.props.BoolProperty(
        name="Selected Objects",
        description=(
            "Export selected objects only. "
            "Disabled for the use of the MultiExporter (Needs to be always checked)"
        ),
        default=True
    ) # type: ignore

    # Export Visible Only Check
    use_visible: bpy.props.BoolProperty(
        name="Visible Objects",
        description="Export visible objects only",
        default=False
    ) # type: ignore

    # Export Custom Properties Check
    export_extras: bpy.props.BoolProperty(
        name="Custom Properties",
        description="Export custom properties as glTF extras. "
                    "Must be disabled for export dedicated to Microsoft Flight Simulator 2024",
        default=False,
    ) # type: ignore

    # Export Camera Check
    export_cameras: bpy.props.BoolProperty(
        name="Cameras",
        description="Export cameras",
        default=False
    ) # type: ignore

    # Export Punctual Lights Check
    export_lights: bpy.props.BoolProperty(
        name="Punctual Lights",
        description=(
            "Export directional, point, and spot lights. "
            "Uses 'KHR_lights_punctual' glTF extension"
        ),
        default=True,
    ) # type: ignore
    # endregion

    # region Transform Options
    # Y Up Check
    export_yup: bpy.props.BoolProperty(
        name="+Y Up", description="Export using glTF convention, +Y up", default=True
    ) # type: ignore
    # endregion

    # region Scene Graph
    if bpy.app.version >= (4, 2, 0):
        # Export geometry node instances
        export_gn_mesh: bpy.props.BoolProperty(
            name="Geometry Nodes Instances (Experimental)",
            description="Export Geometry nodes instance meshes",
            default=False
        ) # type: ignore

        # Export GPU instances
        export_gpu_instances: bpy.props.BoolProperty(
            name="GPU Instances",
            description="Export using EXT_mesh_gpu_instancing. "
                        "Limited to children of a given Empty. "
                        "Multiple materials might be omitted",
            default=False
        ) # type: ignore

        # Flatten Objects
        export_hierarchy_flatten_objs: bpy.props.BoolProperty(
            name="Flatten Object Hierarchy",
            description="Flatten Object Hierarchy. "
                        "Useful in case of non decomposable transformation matrix",
            default=False
        ) # type: ignore

        export_hierarchy_full_collections: bpy.props.BoolProperty(
            name="Full Collection Hierarchy",
            description="Export full hierarchy, including intermediate collections",
            default=False
        ) # type: ignore
    # endregion

    # region Mesh
    # Export Meshes
    export_mesh: bpy.props.BoolProperty(
        name="",
        description=(
            "Enable/Disable export meshes"
            "(Useful to export animations only)"
        ),
        default=True,
    ) # type: ignore

    # Export Apply Modifiers Check
    export_apply: bpy.props.BoolProperty(
        name="Apply Modifiers",
        description=(
            "Apply modifiers (excluding Armatures) to mesh objects. "
            "WARNING: prevents exporting shape keys"
        ),
        default=False,
    ) # type: ignore

    # Export UVs Check
    export_texcoords: bpy.props.BoolProperty(
        name="UVs",
        description="Export UVs (texture coordinates) with meshes",
        default=True,
    ) # type: ignore

    # Export Normals Check
    export_normals: bpy.props.BoolProperty(
        name="Normals",
        description="Export vertex normals with meshes",
        default=True
    ) # type: ignore

    # Export Tangents Check
    export_tangents: bpy.props.BoolProperty(
        name="Tangents",
        description="Export vertex tangents with meshes",
        default=False
    ) # type: ignore

    if bpy.app.version < (4, 2, 0):
        # Export Vertex Colors Check
        export_colors: bpy.props.BoolProperty(
            name="Vertex Colors",
            description="Export vertex colors with meshes",
            default=True,
        ) # type: ignore
    else:
        export_vertex_color: bpy.props.EnumProperty(
            name="Use Vertex Color",
            items=(
                (
                    'MATERIAL',
                    'Material',
                    "Export vertex color when used by material"
                ),
                (
                    'NONE',
                    'None',
                    "Do not export vertex color"
                )
            ),
            description="How to export vertex color",
            default='MATERIAL'
        ) # type: ignore

        export_all_vertex_colors: bpy.props.BoolProperty(
            name='Export all vertex colors',
            description=(
                'Export all vertex colors, even if not used by any material. '
                'If no Vertex Color is used in the mesh materials, a fake COLOR_0 will be created, '
                'in order to keep material unchanged'
            ),
            default=True
        ) # type: ignore

        export_active_vertex_color_when_no_material: bpy.props.BoolProperty(
            name='Export active vertex color when no material',
            description='When there is no material on object, export active vertex color',
            default=True
        ) # type: ignore

    # Export Attributes Colors Check
    export_attributes: bpy.props.BoolProperty(
        name='Attributes',
        description='Export Attributes (when starting with underscore)',
        default=False
    ) # type: ignore

    # Export Loose Edge Check
    use_mesh_edges: bpy.props.BoolProperty(
        name="Loose Edges",
        description=(
            "Export loose edges as lines, using the material from the first material slot"
        ),
        default=False,
    ) # type: ignore

    # Export Loose Points Check
    use_mesh_vertices: bpy.props.BoolProperty(
        name="Loose Points",
        description=(
            "Export loose points as glTF points, using the material from the first material slot"
        ),
        default=False,
    ) # type: ignore

    # endregion

    # region Material
    # Export materials option Check
    export_materials: bpy.props.EnumProperty(
        name="Materials",
        items=(
            ("EXPORT", "Export", "Export all materials used by included objects"),
            (
                "PLACEHOLDER",
                "Placeholder",
                "Do not export materials, but write multiple primitive groups per mesh, keeping material slot information",
            ),
            (
                "NONE",
                "No export",
                "Do not export materials, and combine mesh primitive groups, losing material slot information",
            ),
        ),
        description="Export materials ",
        default="EXPORT",
    ) # type: ignore

    # Export Image format UI (Auto/Jpeg/None)
    export_image_format: bpy.props.EnumProperty(
        name="Images",
        items=EXPORT_IMAGE_FORMAT,
        description=(
            "Output format for images. PNG is lossless and generally preferred, but JPEG might be preferable for web "
            "applications due to the smaller file size. Alternatively they can be omitted if they are not needed"
        ),
        default="AUTO",
    ) # type: ignore

    # JPEG Quality
    export_jpeg_quality: bpy.props.IntProperty(
        name='Image quality',
        description='Quality of image export',
        default=75,
        min=0,
        max=100
    ) # type: ignore

    # Create WebP
    export_image_add_webp: bpy.props.BoolProperty(
        name="Create WebP",
        description=(
            "Creates WebP textures for every texture. "
            "For already WebP textures, nothing happens"
        ),
        default=False
    ) # type: ignore

    # WebP Fallback
    export_image_webp_fallback: bpy.props.BoolProperty(
        name="WebP fallback",
        description=(
            "For all WebP textures, create a PNG fallback texture"
        ),
        default=False
    ) # type: ignore

    # Export unused images
    export_unused_images: bpy.props.BoolProperty(
        name="Unused images",
        description="Export images not assigned to any material",
        default=False
    ) # type: ignore

    # Export unused Textures
    export_unused_textures: bpy.props.BoolProperty(
        name="Prepare Unused textures",
        description=(
            "Export image texture nodes not assigned to any material. "
            "This feature is not standard and needs an external extension to be included in the glTF file"
        ),
        default=False
    ) # type: ignore
    # endregion

    # region Compression
    # Draco compression check
    export_draco_mesh_compression_enable: bpy.props.BoolProperty(
        name='Draco mesh compression',
        description=(
            "Compress mesh using Draco. "
            "WARNING: Draco compression is not supported in Microsoft Flight Simulator 2024"
        ),
        default=False
    ) # type: ignore

    # Draco compression level
    export_draco_mesh_compression_level: bpy.props.IntProperty(
        name='Compression level',
        description='Compression level (0 = most speed, 6 = most compression, higher values currently not supported)',
        default=6,
        min=0,
        max=10
    ) # type: ignore

    # Draco compression position quatization
    export_draco_position_quantization: bpy.props.IntProperty(
        name='Position quantization bits',
        description='Quantization bits for position values (0 = no quantization)',
        default=14,
        min=0,
        max=30
    ) # type: ignore

    # Draco compression normal quatization
    export_draco_normal_quantization: bpy.props.IntProperty(
        name='Normal quantization bits',
        description='Quantization bits for normal values (0 = no quantization)',
        default=10,
        min=0,
        max=30
    ) # type: ignore

    # Draco compression texture coordinate quatization
    export_draco_texcoord_quantization: bpy.props.IntProperty(
        name='Texcoord quantization bits',
        description='Quantization bits for texture coordinate values (0 = no quantization)',
        default=12,
        min=0,
        max=30
    ) # type: ignore

    # Draco compression vertex color quatization
    export_draco_color_quantization: bpy.props.IntProperty(
        name='Color quantization bits',
        description='Quantization bits for color values (0 = no quantization)',
        default=10,
        min=0,
        max=30
    ) # type: ignore

    # Draco compression generic quantization
    export_draco_generic_quantization: bpy.props.IntProperty(
        name="Generic quantization bits",
        description="Quantization bits for generic coordinate "
                    "values like weights or joints (0 = no quantization)",
        default=12,
        min=0,
        max=30
    ) # type: ignore
    # endregion

    # region Lighting
    if bpy.app.version >= (3, 6, 0):
        # Lighting Modes
        export_import_convert_lighting_mode: bpy.props.EnumProperty(
            name="Lighting Mode",
            items=(
                (
                    "SPEC",
                    "Standard",
                    "Physically-based glTF lighting units (cd, lx, nt)"
                ),
                (
                    "COMPAT",
                    "Unitless",
                    "Non-physical,"
                    " unitless lighting. Useful when exposure controls are not available"
                ),
                (
                    "RAW",
                    "Raw (Deprecated)",
                    "Blender lighting strengths with no conversion"
                )
            ),
            description="Optional backwards compatibility for non-standard render engines. Applies to lights",
            default="SPEC"
        ) # type: ignore

    # endregion

    # region Shape Keys
    # Export Shape Keys check
    export_morph: bpy.props.BoolProperty(
        name="Shape Keys",
        description=(
            "Export shape keys (morph targets). "
        ),
        default=False
    ) # type: ignore

    # Export Shape Keys Normals check
    export_morph_normal: bpy.props.BoolProperty(
        name="Shape Key Normals",
        description=(
            "Export vertex normals with shape keys (morph targets). "
        ),
        default=False
    ) # type: ignore

    # Export Shape Keys Tangent check
    export_morph_tangent: bpy.props.BoolProperty(
        name="Shape Key Tangents",
        description=(
            "Export vertex tangents with shape keys (morph targets). "
        ),
        default=False
    ) # type: ignore

    if bpy.app.version > (4, 2, 0):
        # Use Sparse Accessors
        export_try_sparse_sk: bpy.props.BoolProperty(
            name="Use Sparse Accessor if better",
            description="Try using Sparse Accessor if it saves space",
            default=True
        ) # type: ignore

        # Omit Sparse accessors if empty
        export_try_omit_sparse_sk: bpy.props.BoolProperty(
            name="Omitting Sparse Accessor if data is empty",
            description="Omitting Sparse Accessor if data is empty",
            default=False
        ) # type: ignore
    # endregion

    # region Skinning
    # Skinning Option Check
    export_skins: bpy.props.BoolProperty(
        name="Skinning", description="Export skinning (armature) data", default=True
    ) # type: ignore

    # Export All Bone Influences Check
    export_all_influences: bpy.props.BoolProperty(
        name="Include All Bone Influences",
        description="Allow > 4 joint vertex influences. Models may appear incorrectly in many viewers",
        default=False,
    ) # type: ignore

    if bpy.app.version >= (4, 2, 0):
        # Nb bone influence
        export_influence_nb: bpy.props.IntProperty(
            name="Bone Influences",
            description="Choose how many Bone influences to export",
            default=4,
            min=1,
            set=_set_influence_nb,
            get=_get_influence_nb
        ) # type: ignore

    # endregion

    # region Armature

    # Deformation Bones Only Check
    export_def_bones: bpy.props.BoolProperty(
        name="Export Deformation Bones Only",
        description="Export Deformation bones only (and needed bones for hierarchy)",
        default=False,
    ) # type: ignore

    if bpy.app.version >= (3, 6, 0):
        # Use rest position check
        export_rest_position_armature: bpy.props.BoolProperty(
            name="Use Rest Position Armature",
            description=(
                "Export armatures using rest position as joints' rest pose. "
                "When off, current frame pose is used as rest pose"
            ),
            default=True
        ) # type: ignore

        # Flatten Bones Check
        export_hierarchy_flatten_bones: bpy.props.BoolProperty(
            name="Flatten Bone Hierarchy",
            description="Flatten Bone Hierarchy. Useful in case of non decomposable transformation matrix",
            default=False
        ) # type: ignore

    if bpy.app.version >= (4, 2, 0):
        # Remove Armature Object
        export_armature_object_remove: bpy.props.BoolProperty(
            name="Remove Armature Object",
            description=(
                "Remove Armature object if possible. "
                "If Armature has multiple root bones, object will not be removed"
            ),
            default=False
        ) # type: ignore
    # endregion

    # region Animation Options
    # Export Animation Options Check
    export_animations: bpy.props.BoolProperty(
        name="Animations",
        description="Exports active actions and NLA tracks as glTF animations",
        default=True,
    ) # type: ignore

    # Use Current Frame Check
    export_current_frame: bpy.props.BoolProperty(
        name="Use Current Frame",
        description="Export the scene in the current animation frame",
        default=False,
    ) # type: ignore

    # Limit to Playback Range Check
    export_frame_range: bpy.props.BoolProperty(
        name="Limit to Playback Range",
        description="Clips animations to selected playback range",
        default=True,
    ) # type: ignore

    # Always Sample Animations Check
    export_force_sampling: bpy.props.BoolProperty(
        name="Always Sample Animations",
        description="Apply sampling to all animations",
        default=True,
    ) # type: ignore

    # Sampling Rate Slider (1-120)
    export_frame_step: bpy.props.IntProperty(
        name="Sampling Rate",
        description="How often to evaluate animated values (in frames)",
        default=1,
        min=1,
        max=120,
    ) # type: ignore

    # Animation mode export
    if bpy.app.version >= (3, 6, 0):
        export_animation_mode: bpy.props.EnumProperty(
            name="Animation mode",
            items=EXPORT_ANIMATION_MODE,
            description="Export Animation mode",
            default="NLA_TRACKS",
            get=_get_export_animation_mode,
            set=_set_export_animation_mode,
        )  # type: ignore

        # Merge Animation (Blender 4.2+, Actions mode): Khronos default merges animations by action
        export_merge_animation: bpy.props.EnumProperty(
            name="Merge Animation",
            items=(
                ("NLA_TRACK", "NLA Track Names", "Merge by NLA Track Names"),
                ("ACTION", "Actions", "Merge by Actions"),
                ("NONE", "No Merge", "Do Not Merge Animations"),
            ),
            description="Merge Animations",
            default="ACTION",
        )  # type: ignore

        # Optimize Animation Force keeping channels for bones Check
        export_optimize_animation_keep_anim_armature: bpy.props.BoolProperty(
            name="Force keeping channels for bones",
            description=(
                "if all keyframes are identical in a rig, "
                "force keeping the minimal animation. "
                "When off, all possible channels for "
                "the bones will be exported, even if empty "
                "(minimal animation, 2 keyframes)"
            ),
            default=False
        ) # type: ignore

        # Optimize Animation Force keeping channels for objects Check
        export_optimize_animation_keep_anim_object: bpy.props.BoolProperty(
            name='Force keeping channel for objects',
            description=(
                "If all keyframes are identical for object transformations, "
                "force keeping the minimal animation"
            ),
            default=False
        ) # type: ignore

        # Export negative frames check
        export_negative_frame: bpy.props.EnumProperty(
            name='Negative Frames',
            items=(
                (
                    'SLIDE',
                    'Slide',
                    'Slide animation to start at frame 0'
                ),
               (
                   'CROP',
                   'Crop',
                   'Keep only frames above frame 0'
               )
           ),
            description='Negative Frames are slid or cropped',
            default='CROP'
        ) # type: ignore

        # Set all glTF Animation starting at 0 check
        export_anim_slide_to_zero: bpy.props.BoolProperty(
            name='Set all glTF Animation starting at 0',
            description=(
                "Set all glTF animation starting at 0.0s. "
                "Can be useful for looping animations"
            ),
            default=False
        ) # type: ignore

        # Bake all objects animation check
        export_bake_animation: bpy.props.BoolProperty(
            name='Bake All Objects Animations',
            description=(
                "Force exporting animation on every object. "
                "Can be useful when using constraints or driver. "
                "Also useful when exporting only selection"
            ),
            default=False
        ) # type: ignore

        # Split animation by object when animation mode is set to scene check
        export_anim_scene_split_object: bpy.props.BoolProperty(
            name='Split Animation by Object',
            description=(
                "Export Scene as seen in Viewport, "
                "But split animation by Object"
            ),
            default=True
        ) # type: ignore

        # Reset pose bones between actions check
        export_reset_pose_bones: bpy.props.BoolProperty(
            name='Reset pose bones between actions',
            description=(
                "Reset pose bones between each action exported. "
                "This is needed when some bones are not keyed on some animations"
            ),
            default=True
        ) # type: ignore

    else:
        # Group by NLA Track Check
        export_nla_strips: bpy.props.BoolProperty(
            name="Group by NLA Track",
            description=(
                "When on, multiple actions become part of the same glTF animation if "
                "they're pushed onto NLA tracks with the same name. "
                "When off, all the currently assigned actions become one glTF animation"
            ),
            default=True,
        ) # type: ignore

        # Export NLA strips merged animation name
        export_nla_strips_merged_animation_name: bpy.props.StringProperty(
            name='Merged Animation Name',
            description=(
                "Name of single glTF animation to be exported"
            ),
            default='Animation'
        ) # type: ignore

    # Optimize Animation Size Check
    export_optimize_animation_size: bpy.props.BoolProperty(
        name="Optimize Animation Size",
        description=(
            "Reduces exported filesize by removing duplicate keyframes"
            "Can cause problems with stepped animation"
        ),
        default=True,
    ) # type: ignore

    # Export all armature actions check
    export_anim_single_armature: bpy.props.BoolProperty(
        name="Export all Armature Actions",
        description=(
            "Export all actions, bound to a single armature. "
            "WARNING: Option does not support exports including multiple armatures"
        ),
        default=False
    ) # type: ignore

    # Export shape key animation check
    export_morph_animation: bpy.props.BoolProperty(
        name='Shape Key Animations',
        description='Export shape keys animations (morph targets)',
        default=False
    ) # type: ignore

    # Reset shape keys between actions check
    export_morph_reset_sk_data: bpy.props.BoolProperty(
        name='Reset shape keys between actions',
        description=(
            "Reset shape keys between each action exported. "
            "This is needed when some SK channels are not keyed on some animations"
        ),
        default=False
    ) # type: ignore

    if bpy.app.version >= (4, 2, 0):
        # Disable viewport for objects when exporting animations
        export_optimize_disable_viewport: bpy.props.BoolProperty(
            name="Disable viewport for other objects",
            description=(
                "When exporting animations, disable viewport for other objects "
                "(for performance)"
            ),
            default=False
        ) # type: ignore

    # endregion
# endregion


# region Utilities
def get_scene_settings_presets(
    scene: bpy.types.Scene,
) -> bpy.types.bpy_prop_collection_idprop[MSFS2024_MultiExporterSettings]:
    return scene.msfs_multi_exporter_settings_presets


def get_settings_preset_by_name(scene: bpy.types.Scene, name: str) -> MSFS2024_MultiExporterSettings | None:
    settings_presets = get_scene_settings_presets(scene)
    if not scene:
        return None
    return settings_presets.get(name, None)

def set_active_export_settings(scene: bpy.types.Scene, preset_name: str):
    scene.msfs_multi_exporter_settings_presets_enum = preset_name

def get_active_export_settings(
    scene: bpy.types.Scene,
) -> MSFS2024_MultiExporterSettings | None:
    settings_presets = get_scene_settings_presets(scene)
    active_settings_preset_name = scene.msfs_multi_exporter_settings_presets_enum
    return settings_presets.get(active_settings_preset_name, None)


def active_export_settings_is_default(
    scene: bpy.types.Scene,
) -> bool:
    settings_presets = get_active_export_settings(scene)
    if settings_presets is None:
        return False
    return settings_presets.name == MSFS2024_MultiExporterSettings.DEFAULT_PRESET_NAME


def _apply_version_dependent_defaults(preset: MSFS2024_MultiExporterSettings):
    """Apply Blender-version-dependent default settings to the preset."""

    if bpy.app.version >= (3, 6, 0):
        defaut_anim_mode = "ACTIONS" if bpy.app.version >= (4, 5, 0) else "NLA_TRACKS"
        preset.export_animation_mode = defaut_anim_mode


def get_unique_preset_name(
    scene: bpy.types.Scene ,
    name: str,
) -> str:
    settings_presets = get_scene_settings_presets(scene)
    unique_name = collection_prop_utils.get_unique_name(settings_presets, name)
    return unique_name


def add_export_settings_preset(scene: bpy.types.Scene, set_active: bool = False):

    settings_presets = get_scene_settings_presets(scene)

    name = MSFS2024_MultiExporterSettings.DEFAULT_PRESET_NAME
    if len(settings_presets) >= 1:
        name = "Settings preset"

    settings_preset : MSFS2024_MultiExporterSettings= settings_presets.add()
    settings_preset.name = collection_prop_utils.get_unique_name(settings_presets, name)
    _apply_version_dependent_defaults(settings_preset)
    if set_active:
        set_active_export_settings(scene, settings_preset.name)


def init_setting_presets(scene: bpy.types.Scene):
    """
    Make sure that msfs_multi_exporter_settings_presets contains
    one default setting preset.
    """

    settings_presets = get_scene_settings_presets(scene)
    if len(settings_presets) <= 0:
        add_export_settings_preset(scene)

def remove_export_settings_preset(scene: bpy.types.Scene, preset_name: str):
    settings_presets = get_scene_settings_presets(scene)
    if preset_name == MSFS2024_MultiExporterSettings.DEFAULT_PRESET_NAME or len(settings_presets) == 1:
        return 

    setting_preset_idx = settings_presets.find(preset_name)
    settings_presets.remove(setting_preset_idx)
    set_active_export_settings(scene, settings_presets[setting_preset_idx - 1].name)

# end region

def get_setting_presets_items(self, context: bpy.types.Context)->list[tuple[str, str, str]]:
    """Property Update function
    """
    init_setting_presets(context.scene)
    settings_presets = get_scene_settings_presets(context.scene)
    enum_items = []
    for settings_preset in settings_presets:
        data = str(settings_preset.name)
        item = (data, data, data)
        enum_items.append(item)
    return enum_items

def register():

    bpy.types.Scene.msfs_multi_exporter_settings_presets = bpy.props.CollectionProperty( # type: ignore
        type=MSFS2024_MultiExporterSettings
    )
    
    bpy.types.Scene.msfs_multi_exporter_settings_presets_enum = bpy.props.EnumProperty( # type: ignore
        name="Settings Presets",
        items=get_setting_presets_items
    )

    bpy.types.Scene.msfs_background_export = bpy.props.BoolProperty( # type: ignore
        name="Export In Background", 
        description=(
            "Export in a separate background process, allowing you\n"
            "to continue working in Blender.\n"
            "WARNING: This setting is global and common to all export presets"
        ),
        default=True,
    )

def unregister():
    try:
        del bpy.types.Scene.msfs_multi_exporter_settings_presets # type: ignore
        del bpy.types.Scene.msfs_multi_exporter_settings_presets_enum # type: ignore
        del bpy.types.Scene.msfs_background_export # type: ignore
    except:
        pass
