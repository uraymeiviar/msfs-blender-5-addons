"""
Keep glTF mesh instancing for objects sharing mesh data whose only modifier is Blender's converted Auto Smooth.

With modifiers applied, the glTF exporter writes one mesh per object that has a modifier, even when objects share
mesh data. Blender 4.1+ turns the mesh setting Auto Smooth into a Geometry Nodes modifier ("Auto Smooth"), so
objects that shared a mesh and were exported once by Blender 4.0 or older now export one copy each.

For the export only: when every exported user of a mesh has that modifier as its only modifier, with the same
angle, its result (the `sharp_edge` / `sharp_face` attributes; it changes nothing else) is written into the
shared mesh and the modifier is removed, so the mesh is exported once. Both are restored by `restore()`.

For throwaway objects only (`instance_throwaways`: multi-exporter duplicates, background runs): users of a mesh whose
only modifiers are Weighted Normal or the converted Auto Smooth and that evaluate identically share one new mesh holding
that result, without modifiers. MSFS batches instances of one mesh with one material into one draw call.
"""

import bpy
import numpy as np

from .legacy_normals import is_converted_auto_smooth

_ATTRIBUTES = ("sharp_edge", "sharp_face")
_MODIFIER_FLAGS = ("show_viewport", "show_render", "show_in_editmode", "show_on_cage", "show_expanded")
# Two evaluated users count as the same result within these
_POSITION_TOLERANCE = 1e-5
_NORMAL_TOLERANCE = 1e-3
_UV_TOLERANCE = 1e-4


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


def _foreach(collection, name, count, size, dtype):
    values = np.empty(count * size, dtype)
    collection.foreach_get(name, values)
    return values


def _evaluated_result(owner):
    """What a user exports: topology, positions, corner normals, UVs and the material of each face."""
    mesh = owner.to_mesh()
    try:
        faces, corners, verts = len(mesh.polygons), len(mesh.loops), len(mesh.vertices)
        slots = [slot.material.original if slot.material else None for slot in owner.material_slots]
        pointers = np.array([m.as_pointer() if m else 0 for m in slots] or [0], np.uint64)
        material_index = _foreach(mesh.polygons, "material_index", faces, 1, np.int32)
        return {
            "exact": (_foreach(mesh.loops, "vertex_index", corners, 1, np.int32),
                      _foreach(mesh.polygons, "loop_start", faces, 1, np.int32),
                      pointers[np.clip(material_index, 0, len(pointers) - 1)]),
            "close": [(_foreach(mesh.vertices, "co", verts, 3, np.float32), _POSITION_TOLERANCE),
                      (_foreach(mesh.corner_normals, "vector", corners, 3, np.float32), _NORMAL_TOLERANCE)]
                     + [(_foreach(layer.uv, "vector", corners, 2, np.float32), _UV_TOLERANCE)
                        for layer in mesh.uv_layers],
            "slots": slots,
        }
    finally:
        owner.to_mesh_clear()


def _same_result(a, b):
    if len(a["close"]) != len(b["close"]):
        return False
    if not all(np.array_equal(x, y) for x, y in zip(a["exact"], b["exact"])):
        return False
    return all(x.shape == y.shape and (not x.size or np.abs(x - y).max() <= tolerance)
               for (x, tolerance), (y, _tolerance) in zip(a["close"], b["close"]))


def _keeps_result(modifier):
    return modifier.type == "WEIGHTED_NORMAL" or is_converted_auto_smooth(modifier)


def _throwaway_candidates(objects, export_settings):
    """{mesh: exported users} where the rule may act: no other modifier, no shape keys, no skinning, nothing linked."""
    exported = _exported_objects(export_settings)
    users = {}
    for obj in objects:
        if obj.type == "MESH" and obj.data is not None and obj in exported:
            users.setdefault(obj.data, []).append(obj)
    return {mesh: group for mesh, group in users.items()
            if len(group) > 1 and mesh.library is None and mesh.shape_keys is None and len(mesh.polygons)
            and any(obj.modifiers for obj in group)
            and all(obj.library is None and obj.find_armature() is None
                    and all(_keeps_result(modifier) for modifier in obj.modifiers) for obj in group)}


def instance_throwaways(objects, export_settings) -> dict:
    """
    Users of a mesh that evaluate identically share one new mesh and lose their modifiers. Only for objects whose
    changes are discarded after the export, so nothing is restored; the source mesh is not touched and the export purges
    the new meshes with its other temporary data. Returns {new mesh name: name the glTF mesh keeps}.
    """
    if not export_settings.get("gltf_apply"):
        return {}
    candidates = _throwaway_candidates(objects, export_settings)
    if not candidates:
        return {}
    depsgraph = bpy.context.evaluated_depsgraph_get()
    names, assignments, users = {}, [], 0
    for mesh, objs in candidates.items():
        owners = [obj.evaluated_get(depsgraph) for obj in objs]
        if not all(owner.is_evaluated for owner in owners):
            continue
        groups = []
        for obj, owner in zip(objs, owners):
            result = _evaluated_result(owner)
            for group in groups:
                if _same_result(group["result"], result):
                    group["objects"].append(obj)
                    break
            else:
                groups.append({"result": result, "owner": owner, "objects": [obj]})
        # Users without a modifier already share the source mesh
        shared = [group for group in groups
                  if len(group["objects"]) > 1 and any(obj.modifiers for obj in group["objects"])]
        for group in shared:
            new_mesh = bpy.data.meshes.new_from_object(group["owner"], preserve_all_data_layers=True,
                                                       depsgraph=depsgraph)
            new_mesh.materials.clear()
            for material in group["result"]["slots"]:
                new_mesh.materials.append(material)
            for key in mesh.keys():
                if key not in new_mesh:
                    new_mesh[key] = mesh[key]
            names[new_mesh.name] = mesh.get("msfs_original_name", mesh.name)
            assignments.append((new_mesh, group["objects"]))
            users += len(group["objects"])
    for new_mesh, objs in assignments:
        for obj in objs:
            obj.modifiers.clear()
            obj.data = new_mesh
            for slot in obj.material_slots:
                if slot.link == "OBJECT":
                    slot.link = "DATA"
    if assignments:
        print(f"[MSFS FSS] Instancing: {users} objects with Weighted Normal or Auto Smooth share "
              f"{len(assignments)} meshes for this export")
    return names
