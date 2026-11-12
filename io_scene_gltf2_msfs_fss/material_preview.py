"""
Viewport preview of MSFS 2024 material parameters that Asobo's node tree ignores: the clearcoat layer and the
Occlusion Strength.

Clearcoat: Asobo's tree sends the clearcoat texture to Coat Tint and leaves Coat Weight at 0, so no coat shows, and
none of the clearcoat parameters reaches a node. This module adds a preview branch next to the tree of a Clearcoat
material: a copy of the material's Principled BSDF with the coat layer, on two Material Outputs with targets EEVEE and
CYCLES. The material's own Principled BSDF and its Material Output (target ALL) stay as Asobo builds them, and the
glTF exporter follows the ALL output, so exports stay as they were (the same design as anisotropic_preview).

Clearcoat texture layout: the MSFS 2024 SDK documents "Clearcoat Colour (RGB), ClearCoat Roughness (A)", and Asobo's
texture library groups this slot with the colour textures (base colour, emissive, detail colour). Asobo's panel label
"Clearcoat amount (R), Clearcoat rough (G)" is the MSFS 2020 layout. The preview follows the SDK: RGB tints the coat
(white is a clear varnish), A is the coat roughness. The coat covers the whole material (Coat Weight 1).

- Coat roughness: texture A times Clearcoat Roughness Factor. With Use Uniform Roughness, the coat roughness is the
  green channel of the Occlusion/Roughness/Metallic texture instead, the clearcoat texture is not used, and the base
  layer under the coat gets the flat Base Roughness.
- Coat normal: the Clearcoat Normal texture through a Normal Map node of strength Clearcoat Normal Factor. With Base
  Normal Affect Coat, the base normal is added (both normals' offsets from the surface normal, summed; an
  approximation).
- Tilings scale the material's UV (after its UV offset, tiling and rotation) for each clearcoat texture.

Occlusion Strength: glTF's rule, occlusion = 1 + strength * (texture - 1), on the occlusion that Asobo's tree feeds to
its Apply AO group. Not on Windshield materials, where the same property is the Reflection Mask Strength.
"""

import bpy

from .blender.utils.msfs_material_nodes_utils import (
    add_node,
    get_node_by_name,
    link,
    unlink_node_input_by_name,
    MSFS2024_GroupNodes,
    MSFS2024_PrincipledBSDFInputs,
    MSFS2024_ShaderNodes,
    MSFS2024_ShaderNodeTypes,
)
from .blender.utils.msfs_material_utils import MSFS2024_MaterialProperties, MSFS2024_MaterialTypes

COAT_PREFIX = "FSS Coat "
OCCLUSION_NODE = "FSS Occlusion Strength"
_IMAGE_COPY_SUFFIX = ".fss_coat_preview"
_INPUTS = MSFS2024_PrincipledBSDFInputs
_P = MSFS2024_MaterialProperties


def _attr(material, prop):
    return getattr(material, prop.attribute_name())


# region Occlusion Strength

def apply_occlusion_strength(owner):
    """Put the Occlusion Strength between the occlusion and Asobo's Apply AO group of `owner` (an MSFS2024_Material)."""
    nodes, links = owner.nodes, owner.links
    apply_ao = get_node_by_name(nodes, MSFS2024_GroupNodes.APPLYAOGROUP.value)
    if apply_ao is None:
        return
    node = get_node_by_name(nodes, OCCLUSION_NODE)
    socket = apply_ao.inputs[1]
    source = socket.links[0].from_socket if socket.is_linked else None
    if source is not None and source.node == node:
        source = node.inputs[0].links[0].from_socket if node.inputs[0].is_linked else None
    material_type = getattr(owner.material, _P.MATERIALTYPE.attribute_name(), "")
    if source is None or material_type == MSFS2024_MaterialTypes.WINDSHIELD.value:
        if node is not None:
            nodes.remove(node)
            if source is not None:
                link(links, source, socket)
        return
    if node is None:
        node = add_node(
            nodes=nodes,
            name=OCCLUSION_NODE,
            type_node=MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value,
            location=(apply_ao.location.x - 200.0, apply_ao.location.y - 250.0),
            hidden=False,
            operation="MULTIPLY_ADD",
        )
        node.use_clamp = True
    strength = _attr(owner.material, _P.OCCLUSIONSTRENGTH)
    node.inputs[1].default_value = strength
    node.inputs[2].default_value = 1.0 - strength
    link(links, source, node.inputs[0])
    link(links, node.outputs[0], socket)


def update_occlusion_strength(material, context):
    """Update callback of the Occlusion Strength property."""
    from .blender.material.msfs_material_properties_update import MSFS2024_MaterialPropUpdate

    msfs_material = MSFS2024_MaterialPropUpdate.get_material(material)
    if msfs_material is not None and msfs_material.node_tree is not None:
        apply_occlusion_strength(msfs_material)

# endregion


# region Clearcoat

def _remove_coat_nodes(owner):
    for node in [node for node in owner.nodes if node.name.startswith(COAT_PREFIX)]:
        owner.nodes.remove(node)


def _preview_image(image, colorspace):
    """
    The image for a preview node, read in `colorspace` with its alpha as data.

    The artist's image stays as it is: the material property is what gets exported, and Asobo's slot validation
    keeps it Non-Color.
    """
    if image is None or (image.colorspace_settings.name == colorspace and image.alpha_mode == "CHANNEL_PACKED"):
        return image
    name = image.name + _IMAGE_COPY_SUFFIX + "." + colorspace
    copy = bpy.data.images.get(name)
    if copy is None or copy.filepath != image.filepath:
        if copy is not None:
            bpy.data.images.remove(copy)
        copy = image.copy()
        copy.name = name
        copy.colorspace_settings.name = colorspace
        copy.alpha_mode = "CHANNEL_PACKED"
    return copy


def _build_coat(owner, principled, uv):
    nodes, links, material = owner.nodes, owner.links, owner.material
    frame = add_node(
        nodes=nodes,
        name=COAT_PREFIX + "Preview",
        type_node=MSFS2024_ShaderNodeTypes.NODEFRAME.value,
        color=(0.35, 0.6, 0.1),
    )
    x, y = principled.location.x, principled.location.y - 1400.0

    def add(name, type_name, dx, dy, **kwargs):
        return add_node(nodes=nodes, name=COAT_PREFIX + name, type_node=type_name, location=(x + dx, y + dy),
                        hidden=False, frame=frame, **kwargs)

    # A copy of today's Principled BSDF: same values and same incoming links, coat inputs aside
    bsdf = add("BSDF", MSFS2024_ShaderNodeTypes.SHADENODEBSDFPRINCIPLED.value, 600.0, 0.0)
    bsdf.distribution = principled.distribution
    bsdf.subsurface_method = principled.subsurface_method
    for socket in principled.inputs:
        if socket.name.startswith("Coat") or not socket.enabled:
            continue
        target = bsdf.inputs[socket.identifier]
        if hasattr(socket, "default_value"):
            try:
                target.default_value = socket.default_value
            except (TypeError, AttributeError):
                pass
        if socket.is_linked:
            link(links, socket.links[0].from_socket, target)
    bsdf.inputs["Coat Weight"].default_value = 1.0

    uniform = _attr(material, _P.CLEARCOATINVERSEROUGHNESS)
    coat_image = None if uniform else _attr(material, _P.CLEARCOATCOLORROUGHNESSTEXTURE)

    def tiled_uv(name, tiling, dy):
        scale = add(name, MSFS2024_ShaderNodeTypes.SHADERNODEVECTORMATH.value, -600.0, dy, operation="SCALE")
        link(links, uv, scale.inputs[0])
        scale.inputs["Scale"].default_value = tiling
        return scale.outputs[0]

    # Coat colour and roughness
    roughness_factor = add("Roughness", MSFS2024_ShaderNodeTypes.SHADERNODEMATH.value, 300.0, -300.0, operation="MULTIPLY")
    roughness_factor.use_clamp = True
    roughness_factor.inputs[0].default_value = 1.0
    roughness_factor.inputs[1].default_value = _attr(material, _P.CLEARCOATROUGHNESSFACTOR)
    link(links, roughness_factor.outputs[0], bsdf.inputs[_INPUTS.CLEARCOATROUGHNESS.value])
    if uniform:
        bsdf.inputs[_INPUTS.ROUGHNESS.value].default_value = _attr(material, _P.CLEARCOATBASEROUGHNESS)
        unlink_node_input_by_name(links, bsdf, _INPUTS.ROUGHNESS.value)
        omr = get_node_by_name(nodes, MSFS2024_ShaderNodes.COMPTEX.value)
        if omr is not None and omr.image is not None:
            separate = add("OMR Separate", MSFS2024_ShaderNodeTypes.SHADERNODESEPARATECOLOR.value, 0.0, -300.0)
            link(links, omr.outputs[0], separate.inputs[0])
            link(links, separate.outputs[1], roughness_factor.inputs[0])
    elif coat_image is not None:
        texture = add("Color Roughness", MSFS2024_ShaderNodeTypes.SHADERNODETEXIMAGE.value, -300.0, -200.0)
        texture.image = _preview_image(coat_image, "sRGB")
        link(links, tiled_uv("Color Roughness UV", _attr(material, _P.CLEARCOATCOLORROUGHNESSTILING), -200.0), texture.inputs[0])
        link(links, texture.outputs[0], bsdf.inputs["Coat Tint"])
        link(links, texture.outputs[1], roughness_factor.inputs[0])

    # Coat normal
    base_normal = principled.inputs[_INPUTS.NORMAL.value]
    base_normal = base_normal.links[0].from_socket if base_normal.is_linked and _attr(material, _P.BASE_NORMAL_AFFECT_COAT) else None
    coat_normal = None
    normal_image = _attr(material, _P.CLEARCOATNORMALTEXTURE)
    if normal_image is not None:
        texture = add("Normal Texture", MSFS2024_ShaderNodeTypes.SHADERNODETEXIMAGE.value, -300.0, -600.0)
        texture.image = _preview_image(normal_image, "Non-Color")
        link(links, tiled_uv("Normal UV", _attr(material, _P.CLEARCOATNORMALTILING), -600.0), texture.inputs[0])
        normal_map = add("Normal Map", MSFS2024_ShaderNodeTypes.SHADERNODENORMALMAP.value, 0.0, -600.0)
        normal_map.inputs["Strength"].default_value = _attr(material, _P.CLEARCOATNORMALFACTOR)
        link(links, texture.outputs[0], normal_map.inputs["Color"])
        coat_normal = normal_map.outputs[0]
    if base_normal is not None and coat_normal is not None:
        geometry = add("Geometry", "ShaderNodeNewGeometry", 0.0, -900.0)
        add_normals = add("Normal Sum", MSFS2024_ShaderNodeTypes.SHADERNODEVECTORMATH.value, 200.0, -700.0, operation="ADD")
        link(links, base_normal, add_normals.inputs[0])
        link(links, coat_normal, add_normals.inputs[1])
        offset = add("Normal Offset", MSFS2024_ShaderNodeTypes.SHADERNODEVECTORMATH.value, 350.0, -700.0, operation="SUBTRACT")
        link(links, add_normals.outputs[0], offset.inputs[0])
        link(links, geometry.outputs["Normal"], offset.inputs[1])
        normalize = add("Normal", MSFS2024_ShaderNodeTypes.SHADERNODEVECTORMATH.value, 500.0, -700.0, operation="NORMALIZE")
        link(links, offset.outputs[0], normalize.inputs[0])
        coat_normal = normalize.outputs[0]
    elif base_normal is not None:
        coat_normal = base_normal
    if coat_normal is not None:
        link(links, coat_normal, bsdf.inputs[_INPUTS.CLEARCOATNORMAL.value])

    for index, target in enumerate(("EEVEE", "CYCLES")):
        output = add(f"{target.title()} Output", MSFS2024_ShaderNodeTypes.SHADERNODEOUTPUTMATERIAL.value, 900.0, -200.0 * index)
        output.target = target
        link(links, bsdf.outputs[0], output.inputs[0])


def sync(owner):
    """Rebuild the clearcoat preview branch of `owner` (an MSFS2024_Material of type Clearcoat)."""
    if owner.node_tree is None:
        return
    principled = get_node_by_name(owner.nodes, MSFS2024_ShaderNodes.PRINCIPLEDBSDF.value)
    uv_group = get_node_by_name(owner.nodes, MSFS2024_GroupNodes.UVGROUP.value)
    _remove_coat_nodes(owner)
    if principled is None or uv_group is None:
        return  # not an MSFS 2024 preview tree, for instance a legacy MSFS 2020 one
    # Asobo's links from the clearcoat textures to today's Principled (Coat Tint, Coat Roughness, Coat Normal) stay:
    # File > Export writes them as KHR_materials_clearcoat, and that export must not change
    _build_coat(owner, principled, uv_group.outputs[0])


class ClearcoatPreviewMixin:
    """For the MSFS2024 Clearcoat material: keeps the coat preview branch up to date."""

    # Asobo's set_clearcoat_tex and set_clearcoat_normal_tex call sync (marked # FSS); Asobo's force_update_nodes
    # does not call them, and calling them here would add coat links that a reopened file has not had before

    def force_update_nodes(self):
        super().force_update_nodes()
        sync(self)

    def _update_normal_links(self):
        super()._update_normal_links()
        sync(self)

    def _set_alpha_link(self, linked: bool):
        super()._set_alpha_link(linked)
        sync(self)


def update_clearcoat(material, context):
    """Update callback of the clearcoat parameters."""
    from .blender.material.msfs_material_properties_update import MSFS2024_MaterialPropUpdate

    msfs_material = MSFS2024_MaterialPropUpdate.get_material(material)
    if isinstance(msfs_material, ClearcoatPreviewMixin):
        sync(msfs_material)


def update_all(materials):
    """Rebuild the previews of `materials`; returns how many have a clearcoat preview."""
    from .blender.material.msfs_material_properties_update import MSFS2024_MaterialPropUpdate

    count = 0
    for material in materials:
        if material.library or getattr(material, "msfs_material_type", "NONE") == "NONE":
            continue
        msfs_material = MSFS2024_MaterialPropUpdate.get_material(material)
        if msfs_material is None or msfs_material.node_tree is None:
            continue
        apply_occlusion_strength(msfs_material)
        if isinstance(msfs_material, ClearcoatPreviewMixin):
            sync(msfs_material)
            count += 1
    return count

# endregion
