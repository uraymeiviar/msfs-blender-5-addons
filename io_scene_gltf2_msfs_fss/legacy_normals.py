"""
Restore Blender 3.6 shading on meshes from pre-4.1 files.

Blender 4.1 removed the mesh Auto Smooth option. With Auto Smooth off, Blender <= 4.0 shaded smooth faces with
plain vertex normals and ignored sharp edges, custom normals and Weighted Normal modifiers; Blender 4.1+ always
applies them, and also splits smooth corners at flat faces. Meshes authored that way therefore shade (and export)
differently after the upgrade, and the setting itself is dropped when the file is loaded.

- `record_legacy_auto_smooth()` (file load): reads each mesh's saved Auto Smooth flag from the .blend on disk
  (the DNA is self-describing; zstd-compressed files supported) and keeps it on the mesh as a custom property,
  so the information survives saving with Blender 5.
- `MSFS_FSS_OT_restore_legacy_normals`: for meshes that had Auto Smooth off and now shade differently, stores the
  Blender 3.6 normals (angle-weighted vertex normals on smooth faces, face normals on flat faces) as custom
  normals and removes the Weighted Normal modifiers that had no effect. Meshes that had Auto Smooth on are left to
  Blender's own conversion ("Smooth by Angle").
"""

import gzip
import re
import struct

import bpy
import numpy as np

LEGACY_AUTO_SMOOTH_KEY = "msfs_fss_legacy_auto_smooth"  # 0 / 1: Auto Smooth as saved by Blender <= 4.0
RESTORED_KEY = "msfs_fss_legacy_normals_restored"
_ME_AUTOSMOOTH = 1 << 5
_TOLERANCE_DEG = 0.05


# region .blend reader
def _open(path):
    with open(path, "rb") as f:
        magic = f.read(4)
    if magic == b"\x28\xb5\x2f\xfd":
        import zstandard  # bundled with Blender 5
        return zstandard.open(path, "rb")
    if magic[:2] == b"\x1f\x8b":
        return gzip.open(path, "rb")
    return open(path, "rb")


def _parse_sdna(dna, end):
    p = 8  # "SDNA" "NAME"
    (n,) = struct.unpack_from(end + "i", dna, p); p += 4
    names = []
    for _ in range(n):
        e = dna.index(b"\0", p); names.append(dna[p:e].decode()); p = e + 1
    p = (p + 3) & ~3
    p += 4  # "TYPE"
    (n,) = struct.unpack_from(end + "i", dna, p); p += 4
    types = []
    for _ in range(n):
        e = dna.index(b"\0", p); types.append(dna[p:e].decode()); p = e + 1
    p = (p + 3) & ~3
    p += 4  # "TLEN"
    tlen = list(struct.unpack_from(end + "%dh" % n, dna, p)); p += 2 * n
    p = (p + 3) & ~3
    p += 4  # "STRC"
    (n,) = struct.unpack_from(end + "i", dna, p); p += 4
    structs = []
    for _ in range(n):
        t, nf = struct.unpack_from(end + "hh", dna, p); p += 4
        structs.append((t, [struct.unpack_from(end + "hh", dna, p + 4 * k) for k in range(nf)]))
        p += 4 * nf
    return names, types, tlen, structs


def read_auto_smooth_flags(path) -> dict:
    """{mesh name: Auto Smooth on} as saved in a Blender <= 4.0 .blend file."""
    with _open(path) as f:
        data = f.read()
    if data[:7] != b"BLENDER":
        raise ValueError("not a .blend file")
    ptr = 8 if data[7:8] == b"-" else 4
    end = "<" if data[8:9] == b"v" else ">"
    head = struct.Struct(end + "4si" + ("Q" if ptr == 8 else "I") + "ii")
    pos, blocks, dna = 12, [], None
    while pos < len(data):
        code, size, _old, sdna, _count = head.unpack_from(data, pos)
        pos += head.size
        if code == b"DNA1":
            dna = data[pos:pos + size]
        elif code == b"ENDB":
            break
        elif code == b"ME\0\0":
            blocks.append((pos, sdna))
        pos += size
    names, types, tlen, structs = _parse_sdna(dna, end)

    def offsets(struct_index):
        out, off = {}, 0
        for ftype, fname in structs[struct_index][1]:
            name = names[fname]
            count = 1
            for d in re.findall(r"\[(\d+)\]", name):
                count *= int(d)
            size = ptr if name.startswith(("*", "(*")) else tlen[ftype]
            out[re.sub(r"\[.*", "", name).lstrip("*")] = (off, types[ftype])
            off += size * count
        return out

    id_struct = next(i for i, s in enumerate(structs) if types[s[0]] == "ID")
    name_off = offsets(id_struct)["name"][0]
    fmt = {"short": "h", "ushort": "H", "int": "i", "uint": "I", "char": "b", "uchar": "B"}
    result = {}
    for pos, sdna in blocks:
        fields = offsets(sdna)
        id_off = fields["id"][0]
        raw = data[pos + id_off + name_off: pos + id_off + name_off + 66]
        mesh_name = raw.split(b"\0", 1)[0][2:].decode("utf-8", "replace")
        flag_off, flag_type = fields["flag"]
        (flag,) = struct.unpack_from(end + fmt[flag_type], data, pos + flag_off)
        result[mesh_name] = bool(flag & _ME_AUTOSMOOTH)
    return result
# endregion


def record_legacy_auto_smooth():
    """On load of a Blender <= 4.0 file: keep each mesh's Auto Smooth flag on the mesh."""
    if tuple(bpy.data.version) >= (4, 1, 0) or not bpy.data.filepath:
        return 0
    try:
        flags = read_auto_smooth_flags(bpy.data.filepath)
    except Exception as e:  # noqa: BLE001 - never block loading a file
        print(f"[MSFS FSS] Could not read legacy Auto Smooth flags: {e!r}")
        return 0
    count = 0
    for mesh in bpy.data.meshes:
        if mesh.library is None and mesh.name in flags and LEGACY_AUTO_SMOOTH_KEY not in mesh:
            mesh[LEGACY_AUTO_SMOOTH_KEY] = int(flags[mesh.name])
            count += 1
    return count


def legacy_corner_normals(mesh) -> np.ndarray:
    """Corner normals Blender <= 4.0 used with Auto Smooth off."""
    n_verts, n_corners, n_faces = len(mesh.vertices), len(mesh.loops), len(mesh.polygons)
    co = np.empty(n_verts * 3, np.float32); mesh.vertices.foreach_get("co", co); co = co.reshape(-1, 3).astype(np.float64)
    corner_vert = np.empty(n_corners, np.int32); mesh.loops.foreach_get("vertex_index", corner_vert)
    start = np.empty(n_faces, np.int32); mesh.polygons.foreach_get("loop_start", start)
    total = np.empty(n_faces, np.int32); mesh.polygons.foreach_get("loop_total", total)
    fnorm = np.empty(n_faces * 3, np.float32); mesh.polygons.foreach_get("normal", fnorm); fnorm = fnorm.reshape(-1, 3)
    smooth = np.empty(n_faces, bool); mesh.polygons.foreach_get("use_smooth", smooth)

    face_of = np.repeat(np.arange(n_faces), total)
    first = start[face_of]
    last = first + total[face_of] - 1
    idx = np.arange(n_corners)
    prev_c = np.where(idx == first, last, idx - 1)
    next_c = np.where(idx == last, first, idx + 1)
    p = co[corner_vert]
    e1 = co[corner_vert[prev_c]] - p
    e2 = co[corner_vert[next_c]] - p
    l1 = np.linalg.norm(e1, axis=1); l2 = np.linalg.norm(e2, axis=1)
    valid = (l1 > 0) & (l2 > 0)
    cos = np.einsum("ij,ij->i", e1, e2) / np.where(valid, l1 * l2, 1.0)
    angle = np.where(valid, np.arccos(np.clip(cos, -1.0, 1.0)), 0.0)

    vnorm = np.zeros((n_verts, 3))
    np.add.at(vnorm, corner_vert, fnorm[face_of] * angle[:, None])
    length = np.linalg.norm(vnorm, axis=1)
    vnorm = np.where(length[:, None] > 0, vnorm / np.where(length, length, 1.0)[:, None], (0.0, 0.0, 1.0))
    return np.where(smooth[face_of][:, None], vnorm[corner_vert], fnorm[face_of]).astype(np.float32)


def _current_corner_normals(mesh) -> np.ndarray:
    out = np.empty(len(mesh.loops) * 3, np.float32)
    mesh.corner_normals.foreach_get("vector", out)
    return out.reshape(-1, 3)


def _users(mesh):
    return [obj for obj in bpy.data.objects if obj.data is mesh]


def candidates():
    """Meshes recorded with Auto Smooth off that were not restored yet."""
    return [m for m in bpy.data.meshes
            if m.library is None and m.get(LEGACY_AUTO_SMOOTH_KEY) == 0 and not m.get(RESTORED_KEY)]


_NORMAL_MODIFIERS = {"WEIGHTED_NORMAL", "NORMAL_EDIT"}


def is_converted_auto_smooth(modifier) -> bool:
    """The Geometry Nodes modifier Blender 4.1+ adds when loading a mesh saved with Auto Smooth on."""
    return (modifier.type == "NODES" and modifier.node_group is not None
            and modifier.node_group.name.split(".")[0] == "Auto Smooth")


def _auto_smooth_index(mods, smooth) -> int:
    """
    Where Blender <= 4.0 effectively evaluated Auto Smooth (a mesh setting applied to the final mesh, which
    Weighted Normal / Normal Edit worked on top of): before the first enabled normal modifier, otherwise at the
    end of the stack. The export evaluates the viewport stack, so disabled modifiers do not count.
    """
    others = [m for i, m in enumerate(mods) if i != smooth]
    normal = next((i for i, m in enumerate(others) if m.type in _NORMAL_MODIFIERS and m.show_viewport), None)
    return normal if normal is not None else len(others)


def misordered_auto_smooth() -> list:
    """
    Objects of meshes saved with Auto Smooth on whose converted Auto Smooth modifier is not where Blender <= 4.0
    evaluated Auto Smooth (Blender 4.1+ may place it after Weighted Normal, discarding its custom normals, or
    before a Subdivision Surface). Returns [(object, from index, to index)].
    """
    result = []
    for obj in bpy.data.objects:
        if obj.library is not None or obj.type != "MESH" or obj.data.get(LEGACY_AUTO_SMOOTH_KEY) != 1:
            continue
        mods = list(obj.modifiers)
        smooth = next((i for i, m in enumerate(mods) if is_converted_auto_smooth(m)), None)
        if smooth is None:
            continue
        target = _auto_smooth_index(mods, smooth)
        if target != smooth:
            result.append((obj, smooth, target))
    return result


def reorder_auto_smooth() -> int:
    """Move the converted Auto Smooth modifier where Blender 3.6 evaluated Auto Smooth."""
    moved = misordered_auto_smooth()
    for obj, smooth, normal in moved:
        obj.modifiers.move(smooth, normal)
    return len(moved)


def pending() -> int:
    """Meshes and objects the Restore Blender 3.6 Normals operator would change."""
    return len(candidates()) + len(misordered_auto_smooth())


def restore(meshes=None) -> tuple:
    """
    Restore Blender 3.6 normals; returns (meshes changed, Weighted Normal modifiers removed, Auto Smooth
    modifiers moved). The modifier order is only restored when all meshes are processed (meshes is None).
    """
    reordered = reorder_auto_smooth() if meshes is None else 0
    changed, removed = 0, 0
    for mesh in (meshes if meshes is not None else candidates()):
        if not mesh.loops:
            mesh[RESTORED_KEY] = 1
            continue
        target = legacy_corner_normals(mesh)
        users = _users(mesh)
        weighted = [(obj, mod) for obj in users for mod in obj.modifiers if mod.type == "WEIGHTED_NORMAL"]
        current = _current_corner_normals(mesh)
        dots = np.clip(np.einsum("ij,ij->i", target, current), -1.0, 1.0)
        differs = np.degrees(np.arccos(dots)).max() > _TOLERANCE_DEG
        if differs:
            mesh.normals_split_custom_set(target.tolist())
            changed += 1
        for obj, mod in weighted:  # no effect with Auto Smooth off in Blender <= 4.0
            obj.modifiers.remove(mod)
            removed += 1
        mesh[RESTORED_KEY] = 1
    return changed, removed, reordered


class MSFS_FSS_OT_restore_legacy_normals(bpy.types.Operator):
    bl_idname = "msfs_fss.restore_legacy_normals"
    bl_label = "Restore Blender 3.6 Normals"
    bl_description = ("Meshes saved by Blender 4.0 or older shade differently in Blender 4.1+. With Auto Smooth off, "
                      "sharp edges, custom normals and Weighted Normal modifiers now apply: store the normals Blender "
                      "3.6 showed as custom normals and remove the Weighted Normal modifiers that had no effect. With "
                      "Auto Smooth on, move the converted Auto Smooth modifier where Blender 3.6 applied Auto Smooth")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return pending() > 0

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        count = len(candidates())
        changed, removed, reordered = restore()
        self.report({"INFO"}, f"Checked {count} mesh(es): restored normals on {changed}, "
                              f"removed {removed} Weighted Normal modifier(s), "
                              f"moved {reordered} Auto Smooth modifier(s)")
        return {"FINISHED"}
