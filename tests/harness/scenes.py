"""
Deterministic test scenes for the MSFS add-on differential harness.

Everything here must run unchanged on every Blender version the harness
compares (3.6 .. 5.2), so only long-stable bpy APIs are used and MSFS
properties are discovered through RNA instead of being hard-coded.
"""
import math
import os
import zlib

import bpy

# Set by blender_case.py before a case is built
SIM = "2024"     # "2024" or "2020": simulator the scene is exported for
ADDON = ""       # add-on module under test


def _stable_unit(name: str) -> float:
    """Deterministic value in [0, 1) derived from a name (no Python hash randomization)."""
    return (zlib.crc32(name.encode("utf-8")) % 10007) / 10007.0


def clear_scene():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.lights,
                 bpy.data.cameras, bpy.data.armatures, bpy.data.images, bpy.data.actions):
        for block in list(coll):
            coll.remove(block)
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = 20
    scene.frame_set(1)


def _link(obj):
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _mesh_object(name, verts, faces, location=(0, 0, 0)):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = _link(bpy.data.objects.new(name, mesh))
    obj.location = location
    return obj


def _box(name, location=(0, 0, 0), size=1.0, uv=True):
    s = size * 0.5
    verts = [(-s, -s, -s), (s, -s, -s), (s, s, -s), (-s, s, -s),
             (-s, -s, s), (s, -s, s), (s, s, s), (-s, s, s)]
    faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    obj = _mesh_object(name, verts, faces, location)
    if uv:
        _add_uv(obj.data, "UVMap", 0.0)
    return obj


def _add_uv(mesh, name, phase):
    layer = mesh.uv_layers.new(name=name)
    for poly in mesh.polygons:
        for k, li in enumerate(poly.loop_indices):
            ang = (k / max(1, poly.loop_total)) * 2.0 * math.pi + phase
            layer.data[li].uv = (0.5 + 0.5 * math.cos(ang), 0.5 + 0.5 * math.sin(ang))
    return layer


def _make_image(name, out_dir, size=8, non_color=False):
    img = bpy.data.images.new(name, size, size, alpha=True)
    seed = _stable_unit(name)
    px = []
    for y in range(size):
        for x in range(size):
            px += [((x + 1) * (seed + 0.1)) % 1.0, ((y + 1) * (seed + 0.3)) % 1.0, seed, 1.0]
    img.pixels = px
    tex_dir = os.path.join(out_dir, "src_textures")
    os.makedirs(tex_dir, exist_ok=True)
    img.filepath_raw = os.path.join(tex_dir, name + ".png")
    img.file_format = "PNG"
    img.save()
    if non_color:
        try:
            img.colorspace_settings.name = "Non-Color"
        except Exception:
            pass
    return img


def _keyframe(target, path, frames_values, index=-1):
    for frame, value in frames_values:
        if index >= 0:
            getattr(target, path)[index] = value
        else:
            setattr(target, path, value)
        target.keyframe_insert(data_path=path, frame=frame, index=index)


def _fcurves(id_data):
    """F-curves of an ID's active action on every Blender version (5.x only exposes them per slot)."""
    ad = id_data.animation_data
    act = ad.action if ad else None
    if act is None:
        return []
    slot = getattr(ad, "action_slot", None)
    if slot is not None:
        from bpy_extras import anim_utils
        bag = anim_utils.action_get_channelbag_for_slot(act, slot)
        return list(bag.fcurves) if bag else []
    return list(act.fcurves)


def _rna_props(rna_type, prefix):
    return [p for p in rna_type.bl_rna.properties if p.identifier.startswith(prefix)]


def _enum_ids(rna_type, prop_name):
    prop = rna_type.bl_rna.properties.get(prop_name)
    if prop is None:
        return []
    return [item.identifier for item in prop.enum_items]


class CaseLog:
    """Collects non-fatal problems while building a scene (identical inputs on every Blender)."""

    def __init__(self):
        self.messages = []

    def warn(self, msg):
        self.messages.append(msg)


# --------------------------------------------------------------------------- cases

def _unified_msfs2020():
    return SIM == "2020" and ADDON == "io_scene_gltf2_msfs_fss"


def _material_types():
    """[(identifier to assign, MSFS 2020/2024 name used for object names and value keys)]."""
    ids = [t for t in _enum_ids(bpy.types.Material, "msfs_material_type") if t not in {"NONE", "msfs_none"}]
    if _unified_msfs2020():
        # Same scene as the MSFS 2020 add-on builds: only types MSFS 2020 has, under their 2020 names
        from io_scene_gltf2_msfs_fss._msfs2020 import compat
        return [(t, compat.legacy_material_type_name(t)) for t in ids if compat.legacy_material_type_name(t)]
    return [(t, t) for t in ids]


# Material properties whose definition (range or default) differs between the MSFS 2020 and MSFS 2024
# add-ons. Assigned values would land differently, so MSFS 2020 runs leave them unset; the unified
# add-on's MSFS 2020 defaults for them are covered by the production asset benchmark instead.
CONFLICTING_2020_2024 = {
    "msfs_detail_blend_threshold", "msfs_emissive_scale", "msfs_ghost_bias", "msfs_ghost_power",
    "msfs_parallax_room_size_x", "msfs_parallax_room_size_y", "msfs_uv_tiling_u", "msfs_uv_tiling_v",
}


def _material_props():
    props = _rna_props(bpy.types.Material, "msfs_")
    if SIM != "2020":
        return props
    props = [p for p in props if p.identifier not in CONFLICTING_2020_2024]
    if _unified_msfs2020():
        # Only properties the MSFS 2020 add-on defines, like a scene built with it
        from io_scene_gltf2_msfs_fss._msfs2020.legacy_props import LEGACY_PROPS
        props = [p for p in props if ("Material", p.identifier) in LEGACY_PROPS]
    return props


def case_materials(out_dir, log: CaseLog):
    """One box per MSFS material type, every texture slot bound, scalars set to stable non-defaults."""
    types = _material_types()
    if not types:
        log.warn("Material.msfs_material_type not registered")
        return
    props = _material_props()
    tex_props = [p for p in props
                 if p.type == "POINTER" and getattr(p.fixed_type, "identifier", "") == "Image"]
    scalar_props = [p for p in props
                    if p.type in {"FLOAT", "INT", "BOOLEAN"} and not p.is_readonly
                    and p.identifier != "msfs_material_type"]
    images = {}
    for i, (mtype, type_name) in enumerate(types):
        obj = _box("MAT_" + type_name, location=(i * 2.0, 0, 0))
        mat = bpy.data.materials.new("M_" + type_name)
        mat.use_nodes = True
        obj.data.materials.append(mat)
        try:
            mat.msfs_material_type = mtype
        except Exception as e:  # noqa: BLE001
            log.warn(f"{mtype}: set type failed: {e!r}")
            continue
        mtype = type_name
        for p in tex_props:
            img_name = p.identifier.replace("msfs_", "").replace("_texture", "")
            if img_name not in images:
                images[img_name] = _make_image(img_name, out_dir, non_color=("normal" in img_name or "occlusion" in img_name))
            try:
                setattr(mat, p.identifier, images[img_name])
            except Exception as e:  # noqa: BLE001
                log.warn(f"{mtype}.{p.identifier}: {e!r}")
        for p in scalar_props:
            key = mtype + "." + p.identifier
            try:
                if p.type == "BOOLEAN":
                    if p.is_array:
                        continue
                    setattr(mat, p.identifier, _stable_unit(key) > 0.5)
                elif p.type == "INT":
                    lo, hi = int(p.soft_min), int(p.soft_max)
                    if p.is_array or hi <= lo:
                        continue
                    setattr(mat, p.identifier, lo + int(_stable_unit(key) * min(hi - lo, 8)))
                else:
                    lo, hi = float(p.soft_min), float(p.soft_max)
                    if hi <= lo or hi - lo > 1e6:
                        lo, hi = 0.0, 1.0
                    v = lo + (hi - lo) * (0.25 + 0.5 * _stable_unit(key))
                    if p.is_array:
                        setattr(mat, p.identifier, [min(hi, v * (0.9 + 0.05 * k)) for k in range(p.array_length)])
                    else:
                        setattr(mat, p.identifier, v)
            except Exception as e:  # noqa: BLE001
                log.warn(f"{key}: {e!r}")


def case_skinning(out_dir, log: CaseLog):
    """Two-bone skinned column with explicit weights, bone + object animation, and a morph target."""
    arm_data = bpy.data.armatures.new("Rig")
    rig = _link(bpy.data.objects.new("Rig", arm_data))
    bpy.context.view_layer.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    root = arm_data.edit_bones.new("Root")
    root.head, root.tail = (0, 0, 0), (0, 0, 1)
    tip = arm_data.edit_bones.new("Tip")
    tip.head, tip.tail = (0, 0, 1), (0.2, 0, 2)
    tip.parent = root
    tip.use_connect = True
    bpy.ops.object.mode_set(mode="OBJECT")

    rings, seg = 5, 8
    verts, faces = [], []
    for r in range(rings):
        z = 2.0 * r / (rings - 1)
        for s in range(seg):
            a = 2 * math.pi * s / seg
            verts.append((0.3 * math.cos(a), 0.3 * math.sin(a), z))
    for r in range(rings - 1):
        for s in range(seg):
            a, b = r * seg + s, r * seg + (s + 1) % seg
            faces.append((a, b, b + seg, a + seg))
    col = _mesh_object("Column", verts, faces)
    _add_uv(col.data, "UVMap", 0.0)
    g_root = col.vertex_groups.new(name="Root")
    g_tip = col.vertex_groups.new(name="Tip")
    for v in col.data.vertices:
        w = min(1.0, max(0.0, v.co.z / 2.0))
        g_root.add([v.index], 1.0 - w, "REPLACE")
        g_tip.add([v.index], w, "REPLACE")
    col.parent = rig
    mod = col.modifiers.new("Armature", "ARMATURE")
    mod.object = rig

    # Half of these vertices carry no bone weight: Khronos binds them to an extra "neutral bone"
    # (the FSS 2020 exporter disables that, see msfs_khronos_patches.py)
    partial = _box("PartlyWeighted", location=(-1.5, 0, 0.5))
    g_part = partial.vertex_groups.new(name="Root")
    g_part.add([v.index for v in partial.data.vertices if v.co.z > 0], 1.0, "REPLACE")
    partial.parent = rig
    partial.modifiers.new("Armature", "ARMATURE").object = rig

    pb = rig.pose.bones["Tip"]
    pb.rotation_mode = "XYZ"
    _keyframe(pb, "rotation_euler", [(1, 0.0), (10, 0.8), (20, -0.4)], index=0)
    _keyframe(pb, "location", [(1, 0.0), (20, 0.3)], index=2)
    _keyframe(rig, "location", [(1, 0.0), (20, 1.5)], index=1)

    morph = _box("Morph", location=(3, 0, 0))
    morph.shape_key_add(name="Basis")
    key = morph.shape_key_add(name="Bulge")
    for i, v in enumerate(key.data):
        v.co = v.co * 1.4 if i % 2 == 0 else v.co
    _keyframe(key, "value", [(1, 0.0), (20, 1.0)])


def case_hierarchy(out_dir, log: CaseLog):
    """Parented nodes with negative/non-uniform scale, mixed interpolation, object animation."""
    root = _link(bpy.data.objects.new("H_Root", None))
    root.rotation_euler = (0.1, 0.2, 0.3)
    child = _box("H_Child", location=(1, 2, 3))
    child.parent = root
    child.scale = (1.0, -2.0, 0.5)
    grand = _box("H_Grand", location=(0, 1, 0), size=0.5)
    grand.parent = child
    grand.rotation_mode = "QUATERNION"
    grand.rotation_quaternion = (0.9238795, 0.3826834, 0, 0)
    _keyframe(child, "rotation_euler", [(1, 0.0), (7, 1.0), (20, 3.0)], index=2)
    _keyframe(grand, "scale", [(1, 1.0), (20, 2.0)], index=0)
    for fc in _fcurves(child):
        for kp in fc.keyframe_points:
            kp.interpolation = "CONSTANT"
    try:
        child.msfs_override_unique_id = True
        child.msfs_unique_id = "harness_fixed_id"
    except Exception as e:  # noqa: BLE001
        log.warn(f"unique id: {e!r}")


def case_lights(out_dir, log: CaseLog):
    """Every Blender light type, plus one light per MSFS light type when the add-on defines them."""
    for i, ltype in enumerate(["POINT", "SPOT", "SUN", "AREA"]):
        ld = bpy.data.lights.new("L_" + ltype, ltype)
        ld.color = (1.0, 0.5 + 0.1 * i, 0.25)
        ld.energy = 10.0 + i
        obj = _link(bpy.data.objects.new("L_" + ltype, ld))
        obj.location = (i * 2.0, 0, 1)
        obj.rotation_euler = (0.3 * i, 0.1, 0)
        for name in ("msfs_light_day_night_cycle", "msfs_light_has_symmetry"):
            if hasattr(obj, name):
                setattr(obj, name, True)
        for name, val in (("msfs_light_flash_frequency", 2.0), ("msfs_light_flash_duration", 0.25),
                          ("msfs_light_flash_phase", 0.5), ("msfs_light_rotation_speed", 15.0)):
            if hasattr(obj, name):
                setattr(obj, name, val)
    if SIM == "2020":
        return  # MSFS 2024 light types (Light.msfs_light_type) do not exist for MSFS 2020
    for i, mtype in enumerate(_enum_ids(bpy.types.Light, "msfs_light_type")):
        if mtype.upper() == "NONE":
            continue
        ld = bpy.data.lights.new("ML_" + mtype, "POINT")
        obj = _link(bpy.data.objects.new("ML_" + mtype, ld))
        obj.location = (i * 2.0, 4, 1)
        try:
            ld.msfs_light_type = mtype
        except Exception as e:  # noqa: BLE001
            log.warn(f"light {mtype}: {e!r}")


def case_gizmos(out_dir, log: CaseLog):
    """One collision gizmo per gizmo type, parented under a mesh."""
    holder = _box("G_Holder")
    GizmoTypes = None
    if SIM == "2024":
        import importlib
        GizmoTypes = importlib.import_module(ADDON + ".blender.msfs_gizmo").GizmoTypes
    if GizmoTypes is not None:
        # MSFS 2024: gizmos are geometry-node meshes created by the add-on's own operator
        add_gizmo = bpy.ops.msfs2024.add_gizmo
        for i, gtype in enumerate(GizmoTypes):
            for obj in bpy.context.view_layer.objects:
                obj.select_set(False)
            holder.select_set(True)
            bpy.context.view_layer.objects.active = holder
            try:
                add_gizmo(gizmo_type=gtype.identifier)
            except Exception as e:  # noqa: BLE001
                log.warn(f"add_gizmo {gtype.identifier}: {e!r}")
                continue
            giz = bpy.context.view_layer.objects.active
            if giz is not None and giz is not holder:
                giz.name = "G_" + gtype.identifier
                giz.location = (i * 1.5, 0, 0)
                giz.scale = (1.0, 0.5 + 0.25 * i, 2.0)
        return
    # MSFS 2020: gizmos are empties tagged with msfs_gizmo_type
    for i, gtype in enumerate(_enum_ids(bpy.types.Object, "msfs_gizmo_type")):
        if gtype == "NONE":
            continue
        emp = _link(bpy.data.objects.new("G_" + gtype, None))
        emp.parent = holder
        emp.location = (i * 1.5, 0, 0)
        emp.scale = (1.0, 0.5 + 0.25 * i, 2.0)
        try:
            emp.msfs_gizmo_type = gtype
        except Exception as e:  # noqa: BLE001
            log.warn(f"gizmo {gtype}: {e!r}")
        if hasattr(emp, "msfs_collision_is_road_collider"):
            emp.msfs_collision_is_road_collider = (i % 2 == 0)


def case_vertex_data(out_dir, log: CaseLog):
    """Two UV maps, a color attribute, sharp edges + smooth shading, and stacked modifiers."""
    obj = _box("VD_Box")
    _add_uv(obj.data, "UVMap.001", 1.0)
    mesh = obj.data
    try:
        attr = mesh.color_attributes.new("Col", "BYTE_COLOR", "CORNER")
        for i, d in enumerate(attr.data):
            d.color = (_stable_unit("c%d" % i), 0.5, 1.0 - _stable_unit("c%d" % i), 1.0)
    except Exception as e:  # noqa: BLE001
        log.warn(f"color attribute: {e!r}")
    for poly in mesh.polygons:
        poly.use_smooth = True
    try:
        for e in mesh.edges[:4]:
            e.use_edge_sharp = True
    except Exception as e:  # noqa: BLE001
        log.warn(f"sharp edges: {e!r}")
    mirror = obj.modifiers.new("Mirror", "MIRROR")
    mirror.use_axis = (True, False, False)
    obj.location = (1.0, 0, 0)
    bevel = obj.modifiers.new("Bevel", "BEVEL")
    bevel.width = 0.05
    bevel.segments = 2


def push_actions_to_nla(track_name="HarnessAnim"):
    """MSFS exports animations from NLA tracks (export_animation_mode = NLA_TRACKS).
    Tracks sharing a name across objects are merged into one glTF animation."""
    ids = list(bpy.data.objects) + list(bpy.data.shape_keys)
    for id_data in ids:
        ad = id_data.animation_data
        if ad is None or ad.action is None:
            continue
        act = ad.action
        name = track_name if isinstance(id_data, bpy.types.Object) else track_name + "_Morph"
        track = ad.nla_tracks.new()
        track.name = name
        strip = track.strips.new(name, int(act.frame_range[0]), act)
        if hasattr(strip, "action_slot") and getattr(ad, "action_slot", None) is not None:
            strip.action_slot = ad.action_slot
        ad.action = None


CASES = {
    "materials": case_materials,
    "skinning": case_skinning,
    "hierarchy": case_hierarchy,
    "lights": case_lights,
    "gizmos": case_gizmos,
    "vertex_data": case_vertex_data,
}
