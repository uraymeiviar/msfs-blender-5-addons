"""Merge groups: at export, a node named @MERGE_<name> and its subtree become one mesh named <name>.

The root may be any node: an empty, or a mesh whose own geometry is merged too. The .blend keeps every part as its own
object; only the export sees the merged mesh. A nested @MERGE_ node is not absorbed: it merges its own subtree and
stays a child node of the merged mesh around it, so merged meshes can form a hierarchy. A node that cannot be merged
(animated, skinned, with shape keys, not a mesh or an empty, or carrying one of the "don't merge" tags) is skipped with
its subtree, and the rest of the group still merges; skipped nodes keep their exact transforms because every node
above them that the merge removes is replaced by an object with the same world matrix. The prefix never reaches the
glTF: merged meshes are named without it, and node names are stripped of it as the glTF is written.

The merge edits the objects being exported, so it only runs where those are throwaway: the MSFS 2024 multi-exporter
(it exports duplicates and purges everything created during the export) or a background Blender run (the deploy
scripts quit without saving). An interactive plain glTF export is left unmerged, with a warning.
Rules and decisions: codes/wasm/doc/journal/20261014.fss-blender-tools-tags-and-merge.md (FSS repository).
"""

import bpy
import numpy as np

from . import tags

# "@" keeps the marker from clashing with real node names and is stripped before the glTF is written
PREFIX = "@MERGE_"
# Set by the MSFS 2024 multi-exporter on its duplicates; the exporter writes it as the glTF node name
ORIGINAL_NAME_KEY = "msfs_original_name"
# Set by the multi-exporter on its export copies of materials: the material the artist assigned
ORIGINAL_DATA_KEY = "msfs_original_data"
MESH_LIKE = {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META'}
LOG_PREFIX = "[FSS merge]"


def logical_name(obj) -> str:
    """The name the node gets in the glTF (duplicates carry their source name)."""
    name = obj.get(ORIGINAL_NAME_KEY)
    return name if isinstance(name, str) else obj.name


def is_merge_root(obj) -> bool:
    return logical_name(obj).startswith(PREFIX)


def _is_animated(obj) -> bool:
    data = obj.animation_data
    return data is not None and (data.action is not None or len(data.nla_tracks) > 0)


def skip_reason(obj, skip_tags) -> str:
    """Why obj (and its subtree) stays out of the group being merged, or "" when it can be merged."""
    if is_merge_root(obj):
        return f"own {PREFIX} group"
    return _unmergeable(obj, skip_tags)


def _unmergeable(obj, skip_tags) -> str:
    """Why obj itself cannot be merged, or "" (also decides whether a group root can merge)."""
    if _is_animated(obj):
        return "animated"
    if obj.type == 'ARMATURE' or obj.parent_type == 'BONE' or any(m.type == 'ARMATURE' for m in obj.modifiers):
        return "skinned"
    hit = skip_tags.intersection(tags.get_tags(obj))
    if hit:
        return "tag " + ", ".join(sorted(hit))
    if obj.type == 'MESH' and obj.data.shape_keys is not None and len(obj.data.shape_keys.key_blocks) > 1:
        return "shape keys"
    if obj.type not in MESH_LIKE and obj.type != 'EMPTY':
        return obj.type.lower()
    return ""


def source_material(material):
    """The artist's material behind an export copy made by the multi-exporter."""
    if material is None:
        return None
    original = material.get(ORIGINAL_DATA_KEY)
    return original if isinstance(original, bpy.types.Material) else material


def _material_kind(material) -> str:
    """Opaque and blended surfaces never share a merged mesh: transparent parts sort by their mesh centre."""
    material = source_material(material)
    if material is None:
        return "OPAQUE"
    alpha_mode = getattr(material, "msfs_alpha_mode", None)
    if alpha_mode is not None:
        return "TRANSPARENT" if alpha_mode == 'BLEND' else "OPAQUE"
    return "TRANSPARENT" if getattr(material, "surface_render_method", "") == 'BLENDED' else "OPAQUE"


class _Group:
    def __init__(self, root):
        self.root = root
        self.members = []       # mesh-like objects whose geometry is merged
        self.removed = []       # nodes the merge removes (members and pass-through empties)
        self.kept = []          # nodes that stay because a skipped node lies below them (replaced by empties)
        self.skipped = []       # (object, reason)
        self.root_reason = ""   # why the whole group stays unmerged


def _collect(group, obj, skip_tags, exported):
    """Walks the children of obj; returns True when something below obj stays as its own node."""
    keeps_below = False
    for child in obj.children:
        if not exported(child):
            continue
        reason = skip_reason(child, skip_tags)
        if reason:
            group.skipped.append((child, reason))
            keeps_below = True
            continue
        child_keeps = _collect(group, child, skip_tags, exported)
        if child.type in MESH_LIKE:
            group.members.append(child)
        if child_keeps:
            group.kept.append(child)
            keeps_below = True
        else:
            group.removed.append(child)
    return keeps_below


def merge_roots(scene, exported):
    """@MERGE_ nodes of the export, outermost first: an outer group stops at an inner one, which then merges in place."""
    roots = [obj for obj in scene.objects if exported(obj) and is_merge_root(obj)]

    def depth(obj):
        count = 0
        while obj.parent is not None:
            obj, count = obj.parent, count + 1
        return count

    return sorted(roots, key=depth)


def collect_group(root, exported, skip_tags):
    """The root's own reason not to merge (animated, skinned, ...) leaves the whole group unmerged."""
    group = _Group(root)
    reason = _unmergeable(root, skip_tags)
    if reason:
        group.root_reason = reason
        return group
    if root.type in MESH_LIKE:
        group.members.append(root)
    _collect(group, root, skip_tags, exported)
    return group


def plan(scene, exported, skip_tags):
    """Merge groups as they are now: for the preview."""
    return [collect_group(root, exported, skip_tags) for root in merge_roots(scene, exported)]


def _read(collection, attribute, count, width, dtype):
    values = np.empty(count * width, dtype=dtype)
    collection.foreach_get(attribute, values)
    return values


class _Buffer:
    """Geometry of one material kind, gathered from several evaluated meshes."""

    def __init__(self):
        self.positions, self.loop_starts, self.vertex_indices, self.material_indices = [], [], [], []
        self.normals, self.uvs, self.colors = [], {}, []
        self.vertex_count = self.loop_count = 0
        self.has_color = False

    def add(self, mesh, matrix, normal_matrix, faces, slot_globals):
        if not len(faces):
            return
        positions = _read(mesh.vertices, "co", len(mesh.vertices), 3, np.float32).reshape(-1, 3)
        loop_starts = _read(mesh.polygons, "loop_start", len(mesh.polygons), 1, np.int32)
        loop_ends = np.append(loop_starts[1:], len(mesh.loops))
        vertex_indices = _read(mesh.loops, "vertex_index", len(mesh.loops), 1, np.int32)
        corner_normals = _read(mesh.corner_normals, "vector", len(mesh.corner_normals), 3, np.float32).reshape(-1, 3)
        materials = _read(mesh.polygons, "material_index", len(mesh.polygons), 1, np.int32)

        loops = np.concatenate([np.arange(loop_starts[f], loop_ends[f]) for f in faces])
        used_vertices, remapped = np.unique(vertex_indices[loops], return_inverse=True)

        world = np.c_[positions[used_vertices], np.ones(len(used_vertices))] @ np.array(matrix).T
        self.positions.append(world[:, :3].astype(np.float32))
        self.vertex_indices.append((remapped + self.vertex_count).astype(np.int32))
        sizes = loop_ends[faces] - loop_starts[faces]
        self.loop_starts.append((np.concatenate(([0], np.cumsum(sizes)[:-1])) + self.loop_count).astype(np.int32))
        self.material_indices.append(slot_globals[np.clip(materials[faces], 0, len(slot_globals) - 1)])
        normals = corner_normals[loops] @ np.array(normal_matrix).T
        lengths = np.linalg.norm(normals, axis=1, keepdims=True)
        self.normals.append((normals / np.where(lengths > 0, lengths, 1)).astype(np.float32))

        for layer in mesh.uv_layers:
            values = _read(layer.uv, "vector", len(mesh.loops), 2, np.float32).reshape(-1, 2)[loops]
            self.uvs.setdefault(layer.name, {})[len(self.positions) - 1] = values

        color = mesh.color_attributes.active_color
        if color is not None:
            values = _read(color.data, "color", len(color.data), 4, np.float32).reshape(-1, 4)
            values = values[vertex_indices[loops]] if color.domain == 'POINT' else values[loops]
            self.colors.append(values)
            self.has_color = True
        else:
            self.colors.append(np.ones((len(loops), 4), dtype=np.float32))

        self.vertex_count += len(used_vertices)
        self.loop_count += len(loops)

    def build(self, name, materials):
        mesh = bpy.data.meshes.new(name)
        positions = np.concatenate(self.positions)
        mesh.vertices.add(len(positions))
        mesh.vertices.foreach_set("co", positions.ravel())
        mesh.loops.add(self.loop_count)
        mesh.loops.foreach_set("vertex_index", np.concatenate(self.vertex_indices))
        loop_starts = np.concatenate(self.loop_starts)
        mesh.polygons.add(len(loop_starts))
        mesh.polygons.foreach_set("loop_start", loop_starts)
        mesh.polygons.foreach_set("material_index", np.concatenate(self.material_indices))
        for material in materials:
            mesh.materials.append(material)
        mesh.update(calc_edges=True)

        for layer_name, parts in self.uvs.items():
            layer = mesh.uv_layers.new(name=layer_name)
            values = np.concatenate([parts.get(index, np.zeros((len(self.normals[index]), 2), dtype=np.float32))
                                     for index in range(len(self.positions))])
            layer.uv.foreach_set("vector", values.ravel())
        if self.has_color:
            color = mesh.color_attributes.new("Color", 'FLOAT_COLOR', 'CORNER')
            color.data.foreach_set("color", np.concatenate(self.colors).ravel())
            mesh.color_attributes.active_color = color
            mesh.color_attributes.render_color_index = mesh.color_attributes.active_color_index

        mesh.polygons.foreach_set("use_smooth", np.ones(len(loop_starts), dtype=bool))
        mesh.normals_split_custom_set(np.concatenate(self.normals).tolist())
        return mesh


def _new_object(name, data, like, collections):
    obj = bpy.data.objects.new(name, data)
    for collection in collections:
        collection.objects.link(obj)
    obj.parent = like.parent
    if like.parent is not None:
        obj.parent_type = like.parent_type
        obj.parent_bone = like.parent_bone
    obj.matrix_world = like.matrix_world.copy()
    return obj


def _replace_parent(old, new):
    """Moves the children of old under new, which has the same world matrix, so their transforms do not change."""
    for child in list(old.children):
        inverse = child.matrix_parent_inverse.copy()
        child.parent = new
        child.matrix_parent_inverse = inverse


def merge_group(group, context, log):
    """Builds the merged mesh(es) of one group and swaps them into the export. Returns the new objects."""
    root = group.root
    root_name = logical_name(root)
    target = root_name[len(PREFIX):] or root_name
    collections = list(root.users_collection)
    depsgraph = context.evaluated_depsgraph_get()
    inverse = root.matrix_world.inverted()

    materials, material_users, kinds, uv_names = [], {}, {}, []
    buffers = {}

    def to_global(material):
        if material not in materials:
            materials.append(material)
        return materials.index(material)

    for obj in group.members:
        obj_eval = obj.evaluated_get(depsgraph)
        mesh = obj_eval.to_mesh()
        try:
            if mesh is None or not len(mesh.polygons):
                continue
            face_materials = _read(mesh.polygons, "material_index", len(mesh.polygons), 1, np.int32)
            # The evaluated object returns evaluated copies of its materials; meshes may only use the originals
            slots = [slot.material.original if slot.material else None for slot in obj_eval.material_slots] or [None]
            face_materials = np.clip(face_materials, 0, len(slots) - 1)
            used = np.unique(face_materials)
            slot_globals = np.array([to_global(slots[i]) if i in used else 0 for i in range(len(slots))],
                                    dtype=np.int32)
            face_kinds = np.array([_material_kind(slots[i]) for i in face_materials])
            for name in (layer.name for layer in mesh.uv_layers):
                if name not in uv_names:
                    uv_names.append(name)
            for material in {slots[i] for i in used}:
                source = source_material(material)
                material_users.setdefault(source.name if source else "(none)", []).append(logical_name(obj))
            matrix = inverse @ obj.matrix_world
            normal_matrix = matrix.to_3x3().inverted_safe().transposed()
            for kind in np.unique(face_kinds):
                kinds.setdefault(kind, []).append(logical_name(obj))
                buffers.setdefault(kind, _Buffer()).add(mesh, matrix, normal_matrix,
                                                         np.nonzero(face_kinds == kind)[0], slot_globals)
        finally:
            obj_eval.to_mesh_clear()

    if not buffers:
        log(f"{root_name}: nothing to merge", warning=False)
        return []

    kept_names = {logical_name(node) for node in group.kept} | {logical_name(obj) for obj, _ in group.skipped}
    names = [target] + ([f"{target}_TRANSPARENT"] if len(buffers) > 1 else [])
    for name in names:
        if name in kept_names:
            log(f"{root_name}: the merged mesh {name} has the same name as a node that stays in the group; "
                "rename one of them", warning=True)
    # Replaced originals (plain export without duplicates) give up their names so the merged objects get them
    kept_names_by_node = {node: logical_name(node) for node in group.kept}
    for obj in dict.fromkeys([root] + group.members + group.kept):
        if ORIGINAL_NAME_KEY not in obj and not obj.name.endswith(".fssmerge"):
            obj.name = obj.name + ".fssmerge"

    new_objects = []
    main = None
    for kind in ("OPAQUE", "TRANSPARENT"):
        if kind not in buffers:
            continue
        name = target if main is None else f"{target}_{kind}"
        obj = _new_object(name, buffers[kind].build(name, materials), root, collections)
        obj[ORIGINAL_NAME_KEY] = name
        new_objects.append(obj)
        if main is None:
            main = obj
        else:
            obj.parent = main
            obj.matrix_parent_inverse.identity()
            obj.matrix_basis.identity()

    # Nodes that stay because a skipped node lies below them become empties with the same world matrix
    for node in group.kept:
        empty = _new_object(kept_names_by_node[node], None, node, list(node.users_collection))
        empty.empty_display_size = 0.01
        empty[ORIGINAL_NAME_KEY] = kept_names_by_node[node]
        _replace_parent(node, empty)
        new_objects.append(empty)
        group.removed.append(node)

    _replace_parent(root, main)
    group.removed.append(root)

    merged_count = len(group.members)
    log(f"{root_name} -> {target}: {merged_count} object(s) merged into {len(buffers)} mesh(es), "
        f"{len(materials)} material(s), {len(group.skipped)} node(s) kept separate", warning=False)
    for obj, reason in group.skipped:
        log(f"  kept separate: {logical_name(obj)} ({reason})", warning=False)
    if len(materials) > 1:
        parts = []
        for name, users in sorted(material_users.items(), key=lambda item: -len(item[1])):
            parts.append(f"{name}: {len(users)}" + (f" [{', '.join(users)}]" if len(users) <= 3 else ""))
        detail = ", ".join(parts)
        log(f"{root_name}: {len(materials)} materials merged ({detail}); check that this is intended",
            warning=True)
    if len(kinds) > 1:
        log(f"{root_name}: opaque and transparent parts found; transparent parts exported separately as "
            f"{target}_TRANSPARENT", warning=True)
    if len(uv_names) > 2:
        log(f"{root_name}: {len(uv_names)} UV map names ({', '.join(uv_names)}); the exporter keeps only two",
            warning=True)
    return new_objects


def run(context, exported, selected_export, log):
    """Merges every group of the export. Returns (groups merged, objects created)."""
    settings = context.scene.fss_merge
    skip_tags = set(tags.parse_tag_list(settings.skip_tags))
    created = []
    merged = 0
    for root in merge_roots(context.scene, exported):
        group = collect_group(root, exported, skip_tags)
        if group.root_reason:
            log(f"{logical_name(root)}: not merged ({group.root_reason} {PREFIX} node)", warning=True)
            continue
        new_objects = merge_group(group, context, log)
        if not new_objects:
            continue
        merged += 1
        for obj in group.removed:
            obj.select_set(False)
            obj.hide_set(True)
        for obj in new_objects:
            obj.hide_set(False)
            if selected_export:
                obj.select_set(True)
        created.extend(new_objects)
        context.view_layer.update()
    return merged, created


class glTF2ExportUserExtension:
    """Found by the glTF exporter on every enabled add-on; pre_export_hook runs before it collects the objects."""

    def gather_node_hook(self, gltf2_node, blender_object, export_settings):
        # A group that was not merged still exports its root: the marker never reaches the glTF. Runs after the MSFS
        # exporter's node hook (enabled first), which writes msfs_original_name into the node name.
        name = gltf2_node.name
        if isinstance(name, str) and name.startswith(PREFIX):
            gltf2_node.name = name[len(PREFIX):] or name

    def pre_export_hook(self, export_settings):
        context = bpy.context
        settings = getattr(context.scene, "fss_merge", None)
        if settings is None or not settings.enabled:
            return

        def log(message, warning):
            print(f"{LOG_PREFIX} {'WARNING ' if warning else ''}{message}")
            logger = export_settings.get("log")
            if warning and logger is not None:
                logger.warning(f"{LOG_PREFIX} {message}")

        if export_settings.get("gltf_active_collection"):
            log("export limited to the active collection: merge groups are not merged", warning=True)
            return
        selected_export = bool(export_settings.get("gltf_selected"))
        visible_export = bool(export_settings.get("gltf_visible"))
        view_layer = context.view_layer

        def exported(obj):
            if obj.name not in view_layer.objects:
                return False
            if selected_export and not obj.select_get(view_layer=view_layer):
                return False
            if visible_export and not obj.visible_get(view_layer=view_layer):
                return False
            return True

        roots = [obj for obj in context.scene.objects if exported(obj) and is_merge_root(obj)]
        if not roots:
            return
        throwaway = bpy.app.background or all(ORIGINAL_NAME_KEY in obj for obj in roots)
        if not throwaway:
            log(f"{len(roots)} merge group(s) not merged: an interactive export of the original objects; use the "
                "MSFS 2024 multi-exporter or a background export", warning=True)
            return
        merged, created = run(context, exported, selected_export, log)
        log(f"{merged} merge group(s) merged, {len(created)} object(s) created for the export", warning=False)


class FSS_MergeSettings(bpy.types.PropertyGroup):
    enabled: bpy.props.BoolProperty(
        name="Merge on Export", default=True,
        description=f"At export, merge every node named {PREFIX}<name> and its subtree into one mesh named <name>")
    skip_tags: bpy.props.StringProperty(
        name="Don't Merge Tags",
        description="Objects with any of these tags (separate with ;) are never merged, with their subtree")


class FSS_OT_MergePreview(bpy.types.Operator):
    bl_idname = "fss.merge_preview"
    bl_label = "Preview Merge"
    bl_description = "Print what the export would merge (visible objects) to the console, without changing anything"

    def execute(self, context):
        settings = context.scene.fss_merge
        skip_tags = set(tags.parse_tag_list(settings.skip_tags))
        view_layer = context.view_layer
        groups = plan(context.scene, lambda obj: obj.visible_get(view_layer=view_layer), skip_tags)
        if not groups:
            self.report({'INFO'}, f"No visible {PREFIX} empties")
            return {'FINISHED'}
        for group in groups:
            materials = {slot.material.name for obj in group.members for slot in obj.material_slots if slot.material}
            print(f"{LOG_PREFIX} {logical_name(group.root)}: {len(group.members)} mesh(es) to merge, "
                  f"{len(materials)} material(s) {sorted(materials)}, {len(group.skipped)} kept separate")
            for obj, reason in group.skipped:
                print(f"{LOG_PREFIX}   kept separate: {obj.name} ({reason})")
        total = sum(len(group.members) for group in groups)
        self.report({'INFO'}, f"{len(groups)} group(s), {total} mesh(es) would merge; details in the console")
        return {'FINISHED'}


class FSS_OT_MergeCreateGroup(bpy.types.Operator):
    bl_idname = "fss.merge_create_group"
    bl_label = "New Merge Group"
    bl_description = (f"Create an empty named {PREFIX}<name> at the active object's parent and parent the selected "
                      "objects to it, keeping their transforms")
    bl_options = {'REGISTER', 'UNDO'}

    group_name: bpy.props.StringProperty(name="Name", default="GROUP")

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and context.selected_objects

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        active = context.active_object or context.selected_objects[0]
        empty = bpy.data.objects.new(PREFIX + self.group_name.strip(), None)
        empty.empty_display_type = 'PLAIN_AXES'
        empty.empty_display_size = 0.02
        for collection in active.users_collection:
            collection.objects.link(empty)
        empty.parent = active.parent
        empty.matrix_world = (active.parent.matrix_world.copy() if active.parent else empty.matrix_world)
        for obj in context.selected_objects:
            world = obj.matrix_world.copy()
            obj.parent = empty
            obj.matrix_world = world
        self.report({'INFO'}, f"{empty.name}: {len(context.selected_objects)} object(s)")
        return {'FINISHED'}


class FSS_PT_Merge(bpy.types.Panel):
    bl_idname = "FSS_PT_merge"
    bl_label = "Merge Groups"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "FSS Tools"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.fss_merge
        layout.prop(settings, "enabled")
        layout.prop(settings, "skip_tags", icon='BOOKMARKS')
        row = layout.row(align=True)
        row.operator(FSS_OT_MergeCreateGroup.bl_idname, icon='EMPTY_AXIS')
        row.operator(FSS_OT_MergePreview.bl_idname, icon='VIEWZOOM')
        layout.label(text=f"{PREFIX}<name> nodes merge with their subtree at export", icon='INFO')


CLASSES = (
    FSS_MergeSettings,
    FSS_OT_MergePreview,
    FSS_OT_MergeCreateGroup,
    FSS_PT_Merge,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.fss_merge = bpy.props.PointerProperty(type=FSS_MergeSettings)


def unregister():
    del bpy.types.Scene.fss_merge
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
