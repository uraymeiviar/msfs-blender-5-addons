"""
Anisotropy in Blender's Material Preview and Rendered views for MSFS Anisotropic and Hair materials.

Asobo's node tree creates the anisotropic texture node and leaves it unconnected. This module adds two preview
branches next to the tree, only while the material has an anisotropic texture:

- Cycles: a Principled BSDF with true anisotropy, on a Material Output with target CYCLES.
- EEVEE, which ignores Principled anisotropy: isotropic lobes fanned along the rough axis, on a Material Output
  with target EEVEE. This is an approximation.

The material's own Principled BSDF and its Material Output (target ALL) are never touched. Each engine prefers the
output of its own target, while the glTF exporter follows the ALL output, so exports stay as they were. The MSFS
exports replace the node tree before they gather the material anyway.

Texture meaning (MSFS SDK): comp G is the roughness along the direction, anisotropic RG the direction in tangent
space (0.5, 0.5 is the default orientation, the tangent), anisotropic B the roughness across the direction.

Group names carry a version: a changed group gets a new name, and "Update Material Nodes" moves materials to it.
"""

import bpy

from .blender.utils.msfs_material_nodes_utils import (
    add_node,
    get_node_by_name,
    get_or_create_group_by_name,
    link,
    MSFS2024_AnisotropicNodes,
    MSFS2024_GroupNodes,
    MSFS2024_PrincipledBSDFInputs,
    MSFS2024_ShaderNodes,
    MSFS2024_ShaderNodeTypes,
    unlink_node_input_by_name,
)
from .blender.utils.msfs_material_utils import MSFS2024_MaterialProperties, MSFS2024_MaterialTypes

NODE_PREFIX = "FSS Aniso "
EEVEE_GROUP = ".FSS Anisotropic EEVEE v2"
CYCLES_GROUP = ".FSS Anisotropic Cycles v1"

# Normal offsets of the EEVEE lobes along the rough axis, in units of (roughness high^2 - roughness low^2). Fitted to
# Cycles on a seat belt, in image lighting as in Material Preview, with lobes of the mean roughness as Cycles uses:
# sharper lobes or smaller offsets make stronger stripes, and from about 1.7 the bright and dark bands swap
LOBE_OFFSETS = (-1.2, -0.6, 0.0, 0.6, 1.2)
# The diffuse is added to the lobes, not layered under them as in a Principled BSDF: take the specular's share out
DIFFUSE_ENERGY = 0.96

NON_COLOR = "Non-Color"
_IMAGE_COPY_SUFFIX = ".fss_aniso_preview"
_IMAGE_ATTRIBUTE = MSFS2024_MaterialProperties.ANISODIRECTIONROUGHNESSTEXTURE.attribute_name()
_MATERIAL_TYPES = (MSFS2024_MaterialTypes.ANISOTROPIC.value, MSFS2024_MaterialTypes.HAIR.value)
_INPUTS = MSFS2024_PrincipledBSDFInputs


class _Graph:
    """Small helper to build node groups: returns output sockets, so math reads as nested calls."""

    def __init__(self, group):
        self.group = group
        self.nodes = group.nodes
        self.links = group.links
        self.count = 0

    def node(self, type_name):
        node = self.nodes.new(type_name)
        node.location = (200.0 * (self.count % 8), -200.0 * (self.count // 8))
        self.count += 1
        return node

    def _set(self, socket, value):
        if isinstance(value, (int, float)):
            socket.default_value = value
        else:
            self.links.new(value, socket)

    def math(self, operation, a, b=None):
        node = self.node("ShaderNodeMath")
        node.operation = operation
        self._set(node.inputs[0], a)
        if b is not None:
            self._set(node.inputs[1], b)
        return node.outputs[0]

    def vector(self, operation, a, b=None, scale=None):
        node = self.node("ShaderNodeVectorMath")
        node.operation = operation
        self.links.new(a, node.inputs[0])
        if b is not None:
            self.links.new(b, node.inputs[1])
        if scale is not None:
            self._set(node.inputs["Scale"], scale)
        return node.outputs["Vector"]


def _direction_from_channels(graph, red, green):
    """Direction in tangent space from the texture's red and green channels."""
    dx = graph.math("SUBTRACT", graph.math("MULTIPLY", red, 2.0), 1.0)
    dy = graph.math("SUBTRACT", graph.math("MULTIPLY", green, 2.0), 1.0)
    return dx, dy


def _add_sockets(group, sockets):
    for name, in_out, socket_type in sockets:
        group.interface.new_socket(name, in_out=in_out, socket_type=socket_type)


def _create_eevee_group(group):
    _add_sockets(group, (
        ("Base Color", "INPUT", "NodeSocketColor"),
        ("Metallic", "INPUT", "NodeSocketFloat"),
        ("Roughness X", "INPUT", "NodeSocketFloat"),
        ("Roughness Y", "INPUT", "NodeSocketFloat"),
        ("Direction R", "INPUT", "NodeSocketFloat"),
        ("Direction G", "INPUT", "NodeSocketFloat"),
        ("Normal", "INPUT", "NodeSocketVector"),
        ("Tangent", "INPUT", "NodeSocketVector"),
        ("BSDF", "OUTPUT", "NodeSocketShader"),
    ))
    graph = _Graph(group)
    group_in = graph.node("NodeGroupInput").outputs
    group_out = graph.node("NodeGroupOutput")
    normal, tangent = group_in["Normal"], group_in["Tangent"]
    roughness_x, roughness_y = group_in["Roughness X"], group_in["Roughness Y"]
    metallic = group_in["Metallic"]

    dx, dy = _direction_from_channels(graph, group_in["Direction R"], group_in["Direction G"])
    # The default orientation (no direction in the texture) is the tangent
    no_direction = graph.math("LESS_THAN", graph.math("MAXIMUM", graph.math("ABSOLUTE", dx), graph.math("ABSOLUTE", dy)), 1e-3)
    bitangent = graph.vector("CROSS_PRODUCT", normal, tangent)
    axis_x = graph.vector("NORMALIZE", graph.vector(
        "ADD",
        graph.vector("SCALE", tangent, scale=graph.math("ADD", dx, no_direction)),
        graph.vector("SCALE", bitangent, scale=dy),
    ))
    axis_y = graph.vector("NORMALIZE", graph.vector("CROSS_PRODUCT", normal, axis_x))

    low = graph.math("MINIMUM", roughness_x, roughness_y)
    high = graph.math("MAXIMUM", roughness_x, roughness_y)
    across_is_rough = graph.math("LESS_THAN", roughness_x, roughness_y)
    rough_axis = graph.vector(
        "ADD",
        graph.vector("SCALE", axis_y, scale=across_is_rough),
        graph.vector("SCALE", axis_x, scale=graph.math("SUBTRACT", 1.0, across_is_rough)),
    )
    spread = graph.math("SUBTRACT", graph.math("MULTIPLY", high, high), graph.math("MULTIPLY", low, low))
    lobe_roughness = graph.math("SQRT", graph.math("MULTIPLY", low, high))

    # Metal: coloured lobes and no diffuse. Dielectric: uncoloured lobes and the diffuse on the unbent normal
    specular_color = graph.vector("SCALE", group_in["Base Color"], scale=metallic)
    lobes = None
    for index, offset in enumerate(LOBE_OFFSETS):
        lobe = graph.node("ShaderNodeBsdfPrincipled")
        graph.links.new(specular_color, lobe.inputs[_INPUTS.BASECOLOR.value])
        graph.links.new(metallic, lobe.inputs[_INPUTS.METALLIC.value])
        graph.links.new(lobe_roughness, lobe.inputs[_INPUTS.ROUGHNESS.value])
        graph.links.new(
            graph.vector("NORMALIZE", graph.vector(
                "ADD", normal, graph.vector("SCALE", rough_axis, scale=graph.math("MULTIPLY", spread, offset))
            )),
            lobe.inputs[_INPUTS.NORMAL.value],
        )
        if lobes is None:
            lobes = lobe.outputs[0]
            continue
        mix = graph.node("ShaderNodeMixShader")
        mix.inputs[0].default_value = 1.0 / (index + 1)
        graph.links.new(lobes, mix.inputs[1])
        graph.links.new(lobe.outputs[0], mix.inputs[2])
        lobes = mix.outputs[0]

    diffuse = graph.node("ShaderNodeBsdfDiffuse")
    graph.links.new(
        graph.vector("SCALE", group_in["Base Color"], scale=graph.math("MULTIPLY", graph.math("SUBTRACT", 1.0, metallic), DIFFUSE_ENERGY)),
        diffuse.inputs["Color"],
    )
    graph.links.new(normal, diffuse.inputs["Normal"])

    add = graph.node("ShaderNodeAddShader")
    graph.links.new(diffuse.outputs[0], add.inputs[0])
    graph.links.new(lobes, add.inputs[1])
    graph.links.new(add.outputs[0], group_out.inputs["BSDF"])


def _create_cycles_group(group):
    _add_sockets(group, (
        ("Roughness X", "INPUT", "NodeSocketFloat"),
        ("Roughness Y", "INPUT", "NodeSocketFloat"),
        ("Direction R", "INPUT", "NodeSocketFloat"),
        ("Direction G", "INPUT", "NodeSocketFloat"),
        ("Roughness", "OUTPUT", "NodeSocketFloat"),
        ("Anisotropic", "OUTPUT", "NodeSocketFloat"),
        ("Anisotropic Rotation", "OUTPUT", "NodeSocketFloat"),
    ))
    graph = _Graph(group)
    group_in = graph.node("NodeGroupInput").outputs
    group_out = graph.node("NodeGroupOutput").inputs
    roughness_x, roughness_y = group_in["Roughness X"], group_in["Roughness Y"]

    low = graph.math("MINIMUM", roughness_x, roughness_y)
    high = graph.math("MAXIMUM", roughness_x, roughness_y)
    ratio = graph.math("DIVIDE", low, graph.math("MAXIMUM", high, 1e-4))
    dx, dy = _direction_from_channels(graph, group_in["Direction R"], group_in["Direction G"])
    angle = graph.math("DIVIDE", graph.math("ARCTAN2", dy, dx), 6.283185307)

    graph.links.new(graph.math("SQRT", graph.math("MULTIPLY", low, high)), group_out["Roughness"])
    graph.links.new(
        graph.math("MINIMUM", 1.0, graph.math("DIVIDE", graph.math("SUBTRACT", 1.0, graph.math("MULTIPLY", ratio, ratio)), 0.9)),
        group_out["Anisotropic"],
    )
    # Principled stretches along its tangent, which must be the rougher axis
    graph.links.new(
        graph.math("ADD", angle, graph.math("MULTIPLY", graph.math("LESS_THAN", roughness_x, roughness_y), 0.25)),
        group_out["Anisotropic Rotation"],
    )


def _get_group(name, create):
    group, is_new = get_or_create_group_by_name(group_name=name)
    if is_new:
        create(group)
    return group


def _preview_node(owner, name):
    return get_node_by_name(owner.nodes, NODE_PREFIX + name)


def _add_preview_node(owner, name, type_name, location, frame):
    return add_node(
        nodes=owner.nodes,
        name=NODE_PREFIX + name,
        type_node=type_name,
        location=location,
        hidden=False,
        frame=frame,
    )


def _remove_preview_nodes(owner):
    for node in [node for node in owner.nodes if node.name.startswith(NODE_PREFIX)]:
        owner.nodes.remove(node)


def _principled(owner):
    return get_node_by_name(owner.nodes, MSFS2024_ShaderNodes.PRINCIPLEDBSDF.value)


def relink_normal(owner):
    """The preview branches follow the material's normal. `_update_normal_links` removes all links of the normal group."""
    bsdf, group = _preview_node(owner, "Cycles BSDF"), _preview_node(owner, "EEVEE")
    if bsdf is None or group is None:
        return
    if _principled(owner).inputs[_INPUTS.NORMAL.value].is_linked:
        normal = get_node_by_name(owner.nodes, MSFS2024_GroupNodes.NORMALGROUP.value).outputs[0]
    else:
        normal = _preview_node(owner, "Geometry").outputs["Normal"]
    link(owner.links, normal, bsdf.inputs[_INPUTS.NORMAL.value])
    link(owner.links, normal, group.inputs["Normal"])


def relink_alpha(owner):
    """The preview branches follow the material's alpha: linked only when the alpha mode needs it, as Asobo's tree."""
    bsdf = _preview_node(owner, "Cycles BSDF")
    output = _preview_node(owner, "EEVEE Output")
    if bsdf is None or output is None:
        return
    mix = _preview_node(owner, "Alpha")
    surface = _preview_node(owner, "Surface")
    if _principled(owner).inputs[_INPUTS.ALPHA.value].is_linked:
        alpha = get_node_by_name(owner.nodes, MSFS2024_GroupNodes.ALPHAGROUP.value).outputs[0]
        link(owner.links, alpha, bsdf.inputs[_INPUTS.ALPHA.value])
        link(owner.links, alpha, mix.inputs[0])
        link(owner.links, mix.outputs[0], output.inputs[0])
    else:
        unlink_node_input_by_name(owner.links, bsdf, _INPUTS.ALPHA.value)
        link(owner.links, surface.outputs[0], output.inputs[0])


def _build_preview(owner, required):
    nodes, links = owner.nodes, owner.links
    omr = required[MSFS2024_GroupNodes.OMRGROUP.value]
    base_color = required[MSFS2024_GroupNodes.APPLYAOGROUP.value].outputs[0]
    emissive_color = required[MSFS2024_GroupNodes.EMISSIVEGROUP.value].outputs[0]
    emissive_scale = required[MSFS2024_ShaderNodes.EMISSIVESCALE.value].outputs[0]
    separate = required[MSFS2024_AnisotropicNodes.SEPARATEANISOTROPIC.value]
    roughness_x = omr.outputs[1]
    metallic = omr.outputs[0]

    frame = add_node(
        nodes=nodes,
        name=NODE_PREFIX + "Preview",
        type_node=MSFS2024_ShaderNodeTypes.NODEFRAME.value,
        color=(0.35, 0.6, 0.1),
    )
    add = lambda name, type_name, location: _add_preview_node(owner, name, type_name, location, frame)

    roughness_y_node = add("Roughness Y", "ShaderNodeMath", (700.0, -700.0))
    roughness_y_node.operation = "MULTIPLY"
    link(links, separate.outputs[2], roughness_y_node.inputs[0])
    link(links, required[MSFS2024_ShaderNodes.ROUGHNESSSCALE.value].outputs[0], roughness_y_node.inputs[1])
    roughness_y = roughness_y_node.outputs[0]

    geometry = add("Geometry", "ShaderNodeNewGeometry", (700.0, -900.0))
    tangent = add("Tangent", "ShaderNodeTangent", (700.0, -1150.0))
    tangent.direction_type = "UV_MAP"

    # Cycles
    values = add("Cycles", MSFS2024_ShaderNodeTypes.SHADERNODEGROUP.value, (1000.0, -700.0))
    values.node_tree = _get_group(CYCLES_GROUP, _create_cycles_group)
    link(links, roughness_x, values.inputs["Roughness X"])
    link(links, roughness_y, values.inputs["Roughness Y"])
    link(links, separate.outputs[0], values.inputs["Direction R"])
    link(links, separate.outputs[1], values.inputs["Direction G"])

    bsdf = add("Cycles BSDF", MSFS2024_ShaderNodeTypes.SHADENODEBSDFPRINCIPLED.value, (1300.0, -700.0))
    link(links, base_color, bsdf.inputs[_INPUTS.BASECOLOR.value])
    link(links, metallic, bsdf.inputs[_INPUTS.METALLIC.value])
    link(links, emissive_color, bsdf.inputs[_INPUTS.EMISSION.value])
    link(links, emissive_scale, bsdf.inputs[_INPUTS.EMISSIONSTRENGTH.value])
    link(links, values.outputs["Roughness"], bsdf.inputs[_INPUTS.ROUGHNESS.value])
    link(links, values.outputs["Anisotropic"], bsdf.inputs[_INPUTS.ANISOTROPIC.value])
    link(links, values.outputs["Anisotropic Rotation"], bsdf.inputs[_INPUTS.ANISOTROPICROTATION.value])
    link(links, tangent.outputs[0], bsdf.inputs["Tangent"])

    cycles_output = add("Cycles Output", MSFS2024_ShaderNodeTypes.SHADERNODEOUTPUTMATERIAL.value, (1600.0, -700.0))
    cycles_output.target = "CYCLES"
    link(links, bsdf.outputs[0], cycles_output.inputs[0])

    # EEVEE
    group = add("EEVEE", MSFS2024_ShaderNodeTypes.SHADERNODEGROUP.value, (1000.0, -1300.0))
    group.node_tree = _get_group(EEVEE_GROUP, _create_eevee_group)
    link(links, base_color, group.inputs["Base Color"])
    link(links, metallic, group.inputs["Metallic"])
    link(links, roughness_x, group.inputs["Roughness X"])
    link(links, roughness_y, group.inputs["Roughness Y"])
    link(links, separate.outputs[0], group.inputs["Direction R"])
    link(links, separate.outputs[1], group.inputs["Direction G"])
    link(links, tangent.outputs[0], group.inputs["Tangent"])

    emission = add("Emission", "ShaderNodeEmission", (1000.0, -1600.0))
    link(links, emissive_color, emission.inputs[0])
    link(links, emissive_scale, emission.inputs[1])

    surface = add("Surface", "ShaderNodeAddShader", (1300.0, -1300.0))
    link(links, group.outputs[0], surface.inputs[0])
    link(links, emission.outputs[0], surface.inputs[1])

    transparent = add("Transparent", "ShaderNodeBsdfTransparent", (1300.0, -1500.0))
    mix = add("Alpha", "ShaderNodeMixShader", (1500.0, -1300.0))
    link(links, transparent.outputs[0], mix.inputs[1])
    link(links, surface.outputs[0], mix.inputs[2])

    eevee_output = add("EEVEE Output", MSFS2024_ShaderNodeTypes.SHADERNODEOUTPUTMATERIAL.value, (1700.0, -1300.0))
    eevee_output.target = "EEVEE"

    relink_normal(owner)
    relink_alpha(owner)


def _non_color_image(image):
    """
    The image for the preview node, read as data.

    The artist's image stays as it is, unlike the other texture slots: the material property is what gets exported,
    and an image that is also used in another slot with another colour space must not become two images in the glTF.
    """
    if image is None or image.colorspace_settings.name == NON_COLOR:
        return image
    name = image.name + _IMAGE_COPY_SUFFIX
    copy = bpy.data.images.get(name)
    if copy is None:
        copy = image.copy()
        copy.name = name
        copy.colorspace_settings.name = NON_COLOR
    return copy


def sync(owner, image):
    """Set the anisotropic image on the tree of `owner` (an MSFS2024_Material) and rebuild the preview branches."""
    required = {
        name: get_node_by_name(owner.nodes, name)
        for name in (
            MSFS2024_AnisotropicNodes.ANISOTROPICTEX.value,
            MSFS2024_AnisotropicNodes.SEPARATEANISOTROPIC.value,
            MSFS2024_GroupNodes.OMRGROUP.value,
            MSFS2024_GroupNodes.APPLYAOGROUP.value,
            MSFS2024_GroupNodes.EMISSIVEGROUP.value,
            MSFS2024_GroupNodes.UVGROUP.value,
            MSFS2024_GroupNodes.NORMALGROUP.value,
            MSFS2024_GroupNodes.ALPHAGROUP.value,
            MSFS2024_ShaderNodes.EMISSIVESCALE.value,
            MSFS2024_ShaderNodes.ROUGHNESSSCALE.value,
            MSFS2024_ShaderNodes.PRINCIPLEDBSDF.value,
        )
    }
    if not all(required.values()):
        return  # not an MSFS 2024 preview tree, for instance a legacy MSFS 2020 one

    texture = required[MSFS2024_AnisotropicNodes.ANISOTROPICTEX.value]
    texture.image = _non_color_image(image)
    link(owner.links, required[MSFS2024_GroupNodes.UVGROUP.value].outputs[0], texture.inputs[0])

    _remove_preview_nodes(owner)
    if image is not None:
        _build_preview(owner, required)


class AnisotropicPreviewMixin:
    """For MSFS2024_Material subclasses that use the anisotropic texture: keeps the preview branches up to date."""

    def set_aniso_tex(self, image: bpy.types.Image | None):
        sync(self, image)

    def force_update_nodes(self):
        super().force_update_nodes()
        self.set_aniso_tex(getattr(self.material, _IMAGE_ATTRIBUTE))

    def _update_normal_links(self):
        super()._update_normal_links()
        relink_normal(self)

    def _set_alpha_link(self, linked: bool):
        super()._set_alpha_link(linked)
        relink_alpha(self)


def update_image(material, context):
    """Update callback of the anisotropic texture property."""
    from .blender.material.msfs_material_properties_update import MSFS2024_MaterialPropUpdate

    msfs_material = MSFS2024_MaterialPropUpdate.get_material(material)
    if isinstance(msfs_material, AnisotropicPreviewMixin):
        msfs_material.set_aniso_tex(getattr(material, _IMAGE_ATTRIBUTE))


class MSFS_FSS_OT_update_material_nodes(bpy.types.Operator):
    bl_idname = "msfs_fss.update_material_nodes"
    bl_label = "Update Material Nodes"
    bl_description = (
        "Update the preview nodes of every Anisotropic and Hair material in this file, so their anisotropic texture "
        "shows in Material Preview and Rendered views. Materials saved before this feature need it once. "
        "Exports do not change"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from .blender.material.msfs_material_properties_update import MSFS2024_MaterialPropUpdate

        updated = 0
        for material in bpy.data.materials:
            if material.library or getattr(material, "msfs_material_type", "") not in _MATERIAL_TYPES:
                continue
            msfs_material = MSFS2024_MaterialPropUpdate.get_material(material)
            image = getattr(material, _IMAGE_ATTRIBUTE)
            msfs_material.set_aniso_tex(image)
            updated += image is not None
        self.report({"INFO"}, f"Updated the preview nodes of {updated} material(s) with an anisotropic texture")
        return {"FINISHED"}


def draw_update_operator(layout, material):
    if getattr(material, _IMAGE_ATTRIBUTE) is not None:
        layout.operator(MSFS_FSS_OT_update_material_nodes.bl_idname)
