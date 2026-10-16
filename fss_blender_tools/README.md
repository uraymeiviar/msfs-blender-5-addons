# FSS Blender Tools

Authoring tools for FSS aircraft in Blender 5.2, in the 3D View sidebar tab "FSS Tools". Independent of the Asobo
add-ons; the only coupling to the exporter is the glTF user-extension hook in `merge.py`. Working rules for this
repository are in [../AGENTS.md](../AGENTS.md).

## Modules

| Module | Panel | What it does |
| :--- | :--- | :--- |
| `tools.py` | **Tools** | Scene helpers: **Add Empty Parent** (Manual / Suffix / Prefix naming rules), **Origin to Bounding Box** (minimum-volume OBB orientation with 8 corners, 6 face centers and 12 edge centers) |
| `empty_bounds.py` | **Empty Bounds** | Draws the bounds of empties' subtrees (`All` / `Selected` / `Off`, `In Front`) and a clickable hierarchy text in the viewport |
| `lod.py` | **LOD** | Explicit per-object LOD level marking (`[6][5][4][3][2][1][0]`, stored as `fss_lod`, default `0`) with top-down parent clamping and viewport LOD filter |
| `tags.py` | **Tags** | Generic object tags (`fss_tags`, semicolon-separated), per-row `[-]`/`[+]` assignment, selection, and per-tag skip-merge toggle |
| `merge.py` | **Merge Tree** | Export-time merge groups (`@MERGE_<name>` / `@NOMERGE_<name>`), New Merge Group, tree preview and console details |
| `checks.py`, `name_check.py` | **Checks** | **Scan Names** (lists object and bone names that break FSS naming rules and renames them in batch; `@MERGE_` / `@NOMERGE_` allowed) and **Fix Broken Bone Parents** |

## Tags

A tag is any name the artist chooses; nothing is inferred and nothing is MSFS-specific. An object can carry several
tags. Tags are used by the merge (per-tag skip-merge toggle) and are meant for further tools.

## Merge Groups

At export, a node named `@MERGE_<name>` and its subtree become one mesh named `<name>`. The `.blend` keeps every part
as its own object.

- **Roots:** any node. A mesh root merges its own geometry too; the result takes the root's place and parent,
  including a parent bone.
- **Walk:** the whole subtree below the root. It stops at, and keeps as their own nodes with their subtrees: a nested
  `@MERGE_` node (it merges on its own and becomes a child mesh), a `@NOMERGE_` node, and nodes that are animated,
  skinned (armature or armature modifier), bone-parented, have shape keys, are not meshes or empties, or carry a
  "don't merge" tag. A root that is animated or skinned leaves its group unmerged with a warning.
- **Placeholders:** a node that the merge removes but that has a kept node below it is replaced by an empty with the
  same world matrix and name, so kept nodes (animated buttons) keep exact transforms.
- **Transparent parts** (MSFS alpha mode Blend, or Blender's Blended render method) never share a mesh with opaque
  ones: they become `<name>_TRANSPARENT`, a child of the merged mesh.
- **Geometry:** evaluated meshes (modifiers applied) joined with numpy: positions, faces, material slots mapped to the
  original materials, UV maps by name, the active colour attribute, and corner normals as custom normals.
- **Markers never reach the glTF:** merged meshes are named without them, and the node and mesh hooks strip
  `@MERGE_` / `@NOMERGE_` from every exported name. Animation names are left as authored.
- **When it runs:** in `pre_export_hook`, only where the exported objects are throwaway (multi-exporter duplicates, or
  any background run); an interactive plain glTF export is left unmerged with a warning.
- **Reporting:** one summary line per group plus warnings (several materials, opaque and transparent parts, more than
  two UV maps, a merged name equal to a kept node). In background runs these also go to stderr, so deploys show them
  on the console; per-node details stay in the export log.
- **Known trap:** the merge does not read the model XML. A node the XML refers to (a screen, a clickspot) is merged
  away unless it is tagged, marked `@NOMERGE_`, or kept for another reason.

## Testing

Background Blender with a synthetic scene that covers: nested groups, a mesh root, an animated child, a tagged child,
a `@NOMERGE_` child, a transparent part, a bone-parented root, and an animated root. Export through the multi-exporter
and the plain exporter into a scratch folder, and compare with the same scene exported with Merge on Export off:
world positions of kept nodes, merged vertex and triangle counts and bounds, animations, and that no exported name
contains a marker.

## Decisions

Rationale and history: `codes/wasm/doc/journal/20261014.fss-blender-tools-tags-and-merge.md` and
`20261010.fss-blender-tools-wishlist.md` in the FSS aircraft repository.
