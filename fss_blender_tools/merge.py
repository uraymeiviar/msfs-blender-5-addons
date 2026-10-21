"""Merge groups: at export, a node named @MERGE_<name> and its subtree become one mesh named <name>.

The root may be any node: an empty, or a mesh whose own geometry is merged too. The .blend keeps every part as its own
object; only the export sees the merged mesh. A nested @MERGE_ node is not absorbed: it merges its own subtree and
stays a child node of the merged mesh around it, so merged meshes can form a hierarchy. A node that cannot be merged
(animated, skinned, with shape keys, not a mesh or an empty, or carrying one of the "don't merge" tags) is skipped with
its subtree, and the rest of the group still merges; skipped nodes keep their exact transforms because every node
above them that the merge removes is replaced by an object with the same world matrix. The prefix never reaches the
glTF: merged meshes are named without it, and node names are stripped of it as the glTF is written.
A node named @NOMERGE_<name> inside a group is the opposite marker: it and its subtree are not merged and stay child
nodes of the merged mesh, exported as <name>.

The merge edits the objects being exported, so it only runs where those are throwaway: the MSFS 2024 multi-exporter
(it exports duplicates and purges everything created during the export) or a background Blender run (the deploy
scripts quit without saving). An interactive plain glTF export is left unmerged, with a warning.
Rules and decisions: codes/wasm/doc/journal/20261014.fss-blender-tools-tags-and-merge.md (FSS repository).
"""

import sys

import bpy
import numpy as np

from . import lod_model, tags

# "@" keeps markers from clashing with real node names; every leading "@" is stripped before the glTF is written
PREFIX = "@MERGE_"
NO_MERGE_PREFIX = "@NOMERGE_"
MARKERS = (PREFIX, NO_MERGE_PREFIX)
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


def strip_markers(name):
    """The exported name: without a leading @MERGE_ or @NOMERGE_, and without any other leading '@' (@ZONE_FWD
    exports as ZONE_FWD); unchanged when that would leave it empty."""
    if isinstance(name, str):
        for marker in MARKERS:
            if name.startswith(marker) and len(name) > len(marker):
                return name[len(marker):]
        stripped = name.lstrip("@")
        if stripped:
            return stripped
    return name


def is_merge_root(obj) -> bool:
    return logical_name(obj).startswith(PREFIX)


def _is_animated(obj) -> bool:
    data = obj.animation_data
    return data is not None and (data.action is not None or len(data.nla_tracks) > 0)


def skip_reason(obj, skip_tags) -> str:
    """Why obj (and its subtree) stays out of the group being merged, or "" when it can be merged."""
    if is_merge_root(obj):
        return f"own {PREFIX} group"
    if logical_name(obj).startswith(NO_MERGE_PREFIX):
        return f"{NO_MERGE_PREFIX} node"
    return _unmergeable(obj, skip_tags)


def _unmergeable(obj, skip_tags, is_root=False) -> str:
    """Why obj itself cannot be merged, or "" (also decides whether a group root can merge).

    A root that follows a bone rigidly can merge: the merged mesh keeps the same bone parent. A member that follows a
    bone of its own moves differently from the group, so it stays separate.
    """
    if _is_animated(obj):
        return "animated"
    if obj.type == 'ARMATURE' or any(m.type == 'ARMATURE' for m in obj.modifiers):
        return "skinned"
    if obj.parent_type == 'BONE' and not is_root:
        return "bone-parented"
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
    reason = _unmergeable(root, skip_tags, is_root=True)
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
        # UV maps by position, not by name: MSFS materials address them by index (texCoord 0, 1), and members
        # may name the same map differently. uv_names counts the corners using each name at each position.
        self.normals, self.uvs, self.uv_names, self.colors = [], {}, {}, []
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

        for index, layer in enumerate(mesh.uv_layers):
            values = _read(layer.uv, "vector", len(mesh.loops), 2, np.float32).reshape(-1, 2)[loops]
            self.uvs.setdefault(index, {})[len(self.positions) - 1] = values
            names = self.uv_names.setdefault(index, {})
            names[layer.name] = names.get(layer.name, 0) + len(loops)

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

        for index in sorted(self.uvs):
            parts = self.uvs[index]
            names = self.uv_names[index]
            layer = mesh.uv_layers.new(name=max(names, key=names.get))
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


def merge_group(group, context, log, depsgraph):
    """Reads the evaluated meshes of one group and returns a function that builds the merged mesh(es) and swaps
    them into the export, returning the new objects. Reading every group before building any keeps the scene
    evaluated once: each built group adds objects, and the next evaluation re-evaluates the whole scene."""
    root = group.root
    root_name = logical_name(root)
    target = root_name[len(PREFIX):] or root_name
    collections = list(root.users_collection)
    inverse = root.matrix_world.inverted()

    materials, material_users, kinds, uv_slots = [], {}, {}, []
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
            _add_uv_names(uv_slots, mesh)
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
        return lambda: []
    return lambda: _build_group(group, log, root, root_name, target, collections, materials, material_users, kinds,
                                uv_slots, buffers)


def _build_group(group, log, root, root_name, target, collections, materials, material_users, kinds, uv_slots,
                 buffers):

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
            # A plain child of the main mesh: drop the bone parent copied from a bone-parented root
            obj.parent = main
            obj.parent_type = 'OBJECT'
            obj.parent_bone = ""
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
        log(f"  kept separate: {logical_name(obj)} ({reason})", warning=False, detail=True)
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
    if len(uv_slots) > 2:
        log(f"{root_name}: {len(uv_slots)} UV maps; the exporter keeps only two", warning=True)
    for index, names in enumerate(uv_slots):
        if len(names) > 1:
            log(f"{root_name}: UV map {index + 1} is named differently by its members ({', '.join(names)}); "
                f"merged by position", warning=True)
    return new_objects


def run(context, exported, selected_export, log):
    """Merges every group of the export. Returns (groups merged, objects created)."""
    settings = context.scene.fss_merge
    skip_tags = set(tags.parse_tag_list(settings.skip_tags))
    created = []
    merged = 0
    depsgraph = context.evaluated_depsgraph_get()
    pending = []
    for root in merge_roots(context.scene, exported):
        group = collect_group(root, exported, skip_tags)
        if group.root_reason:
            log(f"{logical_name(root)}: not merged ({group.root_reason} {PREFIX} node)", warning=True)
            continue
        pending.append((group, merge_group(group, context, log, depsgraph)))
    for group, build in pending:
        new_objects = build()
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
    if created:
        context.view_layer.update()
    return merged, created


class glTF2ExportUserExtension:
    """Found by the glTF exporter on every enabled add-on; pre_export_hook runs before it collects the objects."""

    def gather_node_hook(self, gltf2_node, blender_object, export_settings):
        # Unmerged roots and @NOMERGE_ nodes still export: the markers never reach the glTF. Runs after the MSFS
        # exporter's node hook (enabled first), which writes msfs_original_name into the node name.
        gltf2_node.name = strip_markers(gltf2_node.name)

    def gather_mesh_hook(self, gltf2_mesh, blender_mesh, blender_object, vertex_groups, modifiers, materials,
                         export_settings):
        # Mesh data is often named after its object, marker included
        gltf2_mesh.name = strip_markers(gltf2_mesh.name)

    def pre_export_hook(self, export_settings):
        context = bpy.context
        settings = getattr(context.scene, "fss_merge", None)
        if settings is None:
            return

        def log(message, warning, detail=False):
            line = f"{LOG_PREFIX} {'WARNING ' if warning else ''}{message}"
            print(line)
            # Deploys run in background with stdout going to the export log: summaries and warnings also go to stderr,
            # which stays on the console; per-node details stay in the log
            if bpy.app.background and not detail:
                print(line, file=sys.stderr, flush=True)
            logger = export_settings.get("log")
            if warning and logger is not None:
                logger.warning(f"{LOG_PREFIX} {message}")

        if export_settings.get("gltf_active_collection"):
            log("export limited to the active collection: merge groups are not merged", warning=True)
            return
        selected_export = bool(export_settings.get("gltf_selected"))
        visible_export = bool(export_settings.get("gltf_visible"))
        view_layer = context.view_layer
        # A name lookup in view_layer.objects scans the collection; called for every object several times per export
        # (146,666 times for the E2 cockpit's seven LODs). Objects created later (merged meshes) use the lookup.
        view_layer_names = {obj.name for obj in view_layer.objects}

        def exported(obj):
            if obj.name not in view_layer_names and obj.name not in view_layer.objects:
                return False
            if selected_export and not obj.select_get(view_layer=view_layer):
                return False
            if visible_export and not obj.visible_get(view_layer=view_layer):
                return False
            return True

        lod_model.cull_export(context, exported, log)
        if not settings.enabled:
            return
        roots = [obj for obj in context.scene.objects if exported(obj) and is_merge_root(obj)]
        if not roots:
            return
        throwaway = bpy.app.background or all(ORIGINAL_NAME_KEY in obj for obj in roots)
        if not throwaway:
            log(f"{len(roots)} merge group(s) not merged: an interactive export of the original objects; use the "
                "MSFS 2024 multi-exporter or a background export", warning=True)
            return
        merged, created = run(context, exported, selected_export, log)
        lod_model.record_merge(created)
        log(f"{merged} merge group(s) merged, {len(created)} object(s) created for the export", warning=False)


def _group_summary(group):
    """Counts shown in the Merge Groups tree, from the original objects (no evaluation, cheap)."""
    materials, kinds, uv_slots = [], set(), []
    for obj in group.members:
        for slot in obj.material_slots:
            material = source_material(slot.material)
            if material is not None and material not in materials:
                materials.append(material)
                kinds.add(_material_kind(material))
        if obj.type == 'MESH':
            _add_uv_names(uv_slots, obj.data)
    reasons = {}
    for _obj, reason in group.skipped:
        reasons[reason] = reasons.get(reason, 0) + 1
    return materials, kinds, ["/".join(names) for names in uv_slots], reasons


def _add_uv_names(uv_slots, mesh):
    """Adds the mesh's UV map names to uv_slots, a list of name lists by map position."""
    for index, layer in enumerate(mesh.uv_layers):
        if index == len(uv_slots):
            uv_slots.append([])
        if layer.name not in uv_slots[index]:
            uv_slots[index].append(layer.name)


def _on_tree_active(settings, context):
    if 0 <= settings.active < len(settings.items):
        obj = context.scene.objects.get(settings.items[settings.active].root)
        if obj is not None and obj.visible_get():
            for other in context.selected_objects:
                other.select_set(False)
            obj.select_set(True)
            context.view_layer.objects.active = obj


class FSS_MergeTreeItem(bpy.types.PropertyGroup):
    # name (built in) is the merged mesh name, so the list's name filter works
    root: bpy.props.StringProperty()
    depth: bpy.props.IntProperty()
    objects: bpy.props.IntProperty()
    material_count: bpy.props.IntProperty()
    kept: bpy.props.IntProperty()
    transparent: bpy.props.BoolProperty()
    root_reason: bpy.props.StringProperty()
    material_names: bpy.props.StringProperty()
    reasons: bpy.props.StringProperty()
    uv_names: bpy.props.StringProperty()


class FSS_MergeSettings(bpy.types.PropertyGroup):
    items: bpy.props.CollectionProperty(type=FSS_MergeTreeItem)
    active: bpy.props.IntProperty(update=_on_tree_active)
    scanned: bpy.props.BoolProperty()
    enabled: bpy.props.BoolProperty(
        name="Merge on Export", default=True,
        description=f"At export, merge every node named {PREFIX}<name> and its subtree into one mesh named <name>")
    skip_tags: bpy.props.StringProperty(
        name="Don't Merge Tags",
        description="Objects with any of these tags (separate with ;) are never merged, with their subtree")


class FSS_OT_MergeRefresh(bpy.types.Operator):
    bl_idname = "fss.merge_refresh"
    bl_label = "Refresh"
    bl_description = "List the merge groups of the visible objects, nested as they are, without changing anything"

    def execute(self, context):
        settings = context.scene.fss_merge
        skip_tags = set(tags.parse_tag_list(settings.skip_tags))
        view_layer = context.view_layer
        groups = plan(context.scene, lambda obj: obj.visible_get(view_layer=view_layer), skip_tags)
        by_root = {group.root: group for group in groups}

        def parent_group(obj):
            obj = obj.parent
            while obj is not None and obj not in by_root:
                obj = obj.parent
            return obj

        children = {}
        for group in groups:
            children.setdefault(parent_group(group.root), []).append(group.root)
        settings.items.clear()

        def add(root, depth):
            group = by_root[root]
            materials, kinds, uv_names, reasons = _group_summary(group)
            item = settings.items.add()
            item.name = strip_markers(logical_name(root))
            item.root = root.name
            item.depth = depth
            item.objects = len(group.members)
            item.material_count = len(materials)
            item.kept = len(group.skipped)
            item.transparent = len(kinds) > 1
            item.root_reason = group.root_reason
            item.material_names = ", ".join(material.name for material in materials)
            ordered = sorted(reasons.items(), key=lambda entry: -entry[1])
            item.reasons = ", ".join(f"{reason}: {count}" for reason, count in ordered)
            item.uv_names = ", ".join(uv_names)
            for child in sorted(children.get(root, []), key=lambda obj: obj.name):
                add(child, depth + 1)

        for root in sorted(children.get(None, []), key=lambda obj: obj.name):
            add(root, 0)
        settings.scanned = True
        if settings.active >= len(settings.items):
            settings.active = max(len(settings.items) - 1, 0)
        self.report({'INFO'}, f"{len(settings.items)} merge group(s)")
        return {'FINISHED'}


class FSS_UL_MergeTree(bpy.types.UIList):
    bl_idname = "FSS_UL_merge_tree"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        for _ in range(item.depth):
            row.label(icon='BLANK1')
        if item.root_reason:
            row.label(text=f"{item.name} (not merged: {item.root_reason})", icon='ERROR')
            return
        warning = item.material_count > 1 or item.transparent
        row.label(text=item.name, icon='ERROR' if warning else 'MESH_DATA')
        row.label(text=f"{item.objects} obj  {item.material_count} mat  {item.kept} kept")


class FSS_OT_MergePreview(bpy.types.Operator):
    bl_idname = "fss.merge_preview"
    bl_label = "Print Details"
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
    bl_description = (f"Create an empty named {PREFIX}<name> under the selected objects' parent (or parent bone) and "
                      "parent them to it, keeping their transforms")
    bl_options = {'REGISTER', 'UNDO'}

    group_name: bpy.props.StringProperty(name="Name", default="GROUP")

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and context.selected_objects

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        selected = list(context.selected_objects)
        active = context.active_object if context.active_object in selected else selected[0]
        owners = {(obj.parent, obj.parent_type if obj.parent else 'OBJECT', obj.parent_bone if obj.parent else "")
                  for obj in selected}
        if len(owners) > 1:
            self.report({'ERROR'}, "The selected objects have different parents or parent bones: group them separately")
            return {'CANCELLED'}
        parent, parent_type, parent_bone = owners.pop()
        empty = bpy.data.objects.new(PREFIX + self.group_name.strip(), None)
        empty.empty_display_type = 'PLAIN_AXES'
        empty.empty_display_size = 0.02
        for collection in active.users_collection:
            collection.objects.link(empty)
        # The empty takes over the selection's parent, including a parent bone, so the group moves as the parts did
        empty.parent = parent
        if parent is not None and parent_type == 'BONE':
            empty.parent_type = 'BONE'
            empty.parent_bone = parent_bone
            pose_bone = parent.pose.bones.get(parent_bone) if parent.pose else None
            if pose_bone is not None:
                empty.matrix_world = parent.matrix_world @ pose_bone.matrix
        elif parent is not None:
            empty.matrix_world = parent.matrix_world.copy()
        context.view_layer.update()
        for obj in selected:
            world = obj.matrix_world.copy()
            obj.parent = empty
            obj.parent_type = 'OBJECT'
            obj.parent_bone = ""
            obj.matrix_world = world
        self.report({'INFO'}, f"{empty.name}: {len(context.selected_objects)} object(s)")
        return {'FINISHED'}


class FSS_PT_Merge(bpy.types.Panel):
    bl_idname = "FSS_PT_merge"
    bl_label = "Merge Tree"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "FSS Tools"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.fss_merge
        layout.prop(settings, "enabled")
        row = layout.row(align=True)
        row.operator(FSS_OT_MergeCreateGroup.bl_idname, icon='EMPTY_AXIS')
        row.operator(FSS_OT_MergeRefresh.bl_idname, icon='FILE_REFRESH')
        if not settings.scanned:
            layout.label(text=f"{PREFIX}name merges, {NO_MERGE_PREFIX}name stays", icon='INFO')
            return
        if not settings.items:
            layout.label(text=f"No visible {PREFIX} nodes", icon='INFO')
            return
        layout.template_list(FSS_UL_MergeTree.bl_idname, "", settings, "items", settings, "active", rows=6)
        if 0 <= settings.active < len(settings.items):
            item = settings.items[settings.active]
            box = layout.box()
            box.label(text=f"{item.root} -> {item.name}", icon='OUTLINER_OB_EMPTY')
            if item.root_reason:
                box.label(text=f"Not merged: {item.root_reason}", icon='ERROR')
            else:
                column = box.column(align=True)
                column.label(text=f"Merged: {item.objects} object(s), {item.material_count} material(s)")
                if item.material_names:
                    column.label(text=item.material_names, icon='MATERIAL')
                if item.transparent:
                    column.label(text=f"Transparent parts become {item.name}_TRANSPARENT", icon='ERROR')
                if item.uv_names:
                    uv_icon = 'ERROR' if item.uv_names.count(",") >= 2 or "/" in item.uv_names else 'GROUP_UVS'
                    column.label(text=f"UV maps: {item.uv_names}", icon=uv_icon)
                column.label(text=f"Kept separate: {item.kept}", icon='OUTLINER_OB_GROUP_INSTANCE')
                if item.reasons:
                    column.label(text=item.reasons)
        layout.operator(FSS_OT_MergePreview.bl_idname, icon='CONSOLE')


CLASSES = (
    FSS_MergeTreeItem,
    FSS_MergeSettings,
    FSS_OT_MergeRefresh,
    FSS_UL_MergeTree,
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
