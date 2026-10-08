"""
Keep glTF mesh instancing for objects sharing mesh data whose only modifier is Blender's converted Auto Smooth.

With modifiers applied, the glTF exporter writes one mesh per object that has a modifier, even when objects share
mesh data. Blender 4.1+ turns the mesh setting Auto Smooth into a Geometry Nodes modifier ("Auto Smooth"), so
objects that shared a mesh and were exported once by Blender 4.0 or older now export one copy each.

For the export only: when every exported user of a mesh has that modifier as its only modifier, with the same
angle, its result (the `sharp_edge` / `sharp_face` attributes; it changes nothing else) is written into the
shared mesh and the modifier is removed, so the mesh is exported once. Both are restored by `restore()`.
"""

import bpy
import numpy as np

from .legacy_normals import is_converted_auto_smooth

_ATTRIBUTES = ("sharp_edge", "sharp_face")
_MODIFIER_FLAGS = ("show_viewport", "show_render", "show_in_editmode", "show_on_cage", "show_expanded")


def _angle_identifier(modifier):
    for item in modifier.node_group.interface.items_tree:
        if item.item_type == "SOCKET" and item.in_out == "INPUT" and item.name == "Angle":
            return item.identifier
    return None


def _angle(modifier):
    identifier = _angle_identifier(modifier)
    return getattr(modifier.properties.inputs, identifier).value if identifier else None


def _exported_objects(export_settings) -> set:
    objects = list(bpy.context.view_layer.objects)
    if export_settings.get("gltf_selected"):
        objects = [o for o in objects if o.select_get()]
    if export_settings.get("gltf_visible"):
        objects = [o for o in objects if o.visible_get()]
    return set(objects)


def _read(attribute, count):
    values = np.zeros(count, dtype=bool)
    if attribute is not None:
        attribute.data.foreach_get("value", values)
    return values


def _write(mesh, name, domain, values):
    attribute = mesh.attributes.get(name)
    if attribute is None:
        if not values.any():
            return
        attribute = mesh.attributes.new(name, "BOOLEAN", domain)
    attribute.data.foreach_set("value", values)


def _candidates(export_settings):
    exported = _exported_objects(export_settings)
    users = {}
    for obj in bpy.data.objects:
        if obj.type == "MESH" and obj.data is not None:
            users.setdefault(obj.data, []).append(obj)
    for mesh, objects in users.items():
        if (len(objects) < 2 or mesh.library is not None or mesh.shape_keys is not None
                or mesh.has_custom_normals or not all(obj in exported for obj in objects)):
            continue
        settings = set()
        for obj in objects:
            modifiers = list(obj.modifiers)
            if len(modifiers) != 1 or not is_converted_auto_smooth(modifiers[0]) or not modifiers[0].show_viewport:
                break
            settings.add((modifiers[0].node_group.name, round(_angle(modifiers[0]) or 0.0, 6)))
        else:
            if len(settings) == 1:
                yield mesh, objects


def prepare(export_settings) -> list:
    """Instance shared meshes for this export; returns the state `restore()` needs."""
    if not export_settings.get("gltf_apply"):
        return []
    state = []
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for mesh, objects in list(_candidates(export_settings)):
        evaluated_owner = objects[0].evaluated_get(depsgraph)
        evaluated = evaluated_owner.to_mesh()
        try:
            counts = {"sharp_edge": len(mesh.edges), "sharp_face": len(mesh.polygons)}
            if len(evaluated.edges) != counts["sharp_edge"] or len(evaluated.polygons) != counts["sharp_face"]:
                continue
            result = {name: _read(evaluated.attributes.get(name), counts[name]) for name in _ATTRIBUTES}
        finally:
            evaluated_owner.to_mesh_clear()
        saved = {name: (mesh.attributes.get(name) is not None, _read(mesh.attributes.get(name), counts[name]))
                 for name in _ATTRIBUTES}
        for name, domain in (("sharp_edge", "EDGE"), ("sharp_face", "FACE")):
            _write(mesh, name, domain, result[name])
        removed = []
        for obj in objects:
            modifier = obj.modifiers[0]
            removed.append((obj, modifier.name, modifier.node_group, _angle_identifier(modifier), _angle(modifier),
                            {flag: getattr(modifier, flag) for flag in _MODIFIER_FLAGS}))
            obj.modifiers.remove(modifier)
        state.append((mesh, saved, removed))
    return state


def restore(state):
    """Put the sharp attributes and the Auto Smooth modifiers back as they were before `prepare()`."""
    for mesh, saved, removed in state:
        for name, (existed, values) in saved.items():
            if existed:
                mesh.attributes[name].data.foreach_set("value", values)
            elif mesh.attributes.get(name) is not None:
                mesh.attributes.remove(mesh.attributes[name])
        for obj, name, node_group, identifier, angle, flags in removed:
            modifier = obj.modifiers.new(name, "NODES")
            modifier.node_group = node_group
            if identifier is not None and angle is not None:
                getattr(modifier.properties.inputs, identifier).value = angle
            for flag, value in flags.items():
                setattr(modifier, flag, value)
