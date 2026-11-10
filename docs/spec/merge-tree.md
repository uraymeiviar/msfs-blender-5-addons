# Merge Tree

[Specification](README.md) / **merge-tree.md**

Export-time merge groups: many small objects become one mesh in the glTF while every part stays a separate,
editable object in the `.blend`. The merge runs inside the glTF exporter's `pre_export_hook` (EXP-013). Artist
guide: [../user/fss-tools.md](../user/fss-tools.md#zones--merge-tree).

Common test note: the merge rules have no unit test. `tests/verify_lod_exports.py` checks one group (`@MERGE_Panel`
with a `@NOMERGE_Button`) in seven LOD exports for both simulators, and cannot be re-run as it stands
([README.md](README.md#test-references)).

## Groups

### MRG-001: Merge groups

- **Status:** implemented
- **Requirement:** An object (empty or mesh, any type that may merge) named `@MERGE_<name>` is a group root. At
  export, it and its subtree become one mesh node named `<name>`, at the root's place in the hierarchy; a mesh root
  merges its own geometry too. Merging is on by default and can be turned off per scene (Merge on Export, DAT-002).
- **Data:** DAT-002, DAT-033, DAT-043
- **Decision:** W8; TM S1.3, S1.6, S1.7; TM S2.1, S2.2
- **Test:** `tests/verify_lod_exports.py` (`Panel` node; cannot be re-run as it stands)
- **Code:** `merge.py` (`collect_group`, `merge_group`, `run`)

### MRG-002: Nested groups

- **Status:** implemented
- **Requirement:** A nested `@MERGE_` group is not absorbed: the outer group stops at it, it merges its own subtree,
  and it stays a child node of the outer merged mesh. Groups merge deepest first.
- **Decision:** TM S1.4; TM S2.3
- **Test:** no test
- **Code:** `merge.py`

### MRG-003: What stays separate

- **Status:** implemented
- **Requirement:** Inside a group, these objects stay their own nodes, with their subtrees: a nested `@MERGE_` group;
  a `@NOMERGE_` object (MRG-004); a `@ROOT_` object (MRG-015); an animated object (an action or NLA tracks); a skinned object (an armature, or an
  object with an Armature modifier); an object parented to a bone (except the root); a mesh with shape keys; an
  object with a Don't Merge tag (TAG-005); an object that is not a mesh, curve, surface, text, metaball or empty. If
  the root itself is animated or skinned, the whole group stays unmerged, with a warning. A bone-parented root
  merges, and the merged mesh keeps the bone parent.
- **Decision:** TM S1.4; TM Sessions 3 and 5
- **Test:** no test
- **Code:** `merge.py` (`skip_reason`, `_unmergeable`)
- **Notes:** NOT TESTED: every rule; only an animated `@NOMERGE_` button is exercised by the LOD pair.

### MRG-004: `@NOMERGE_`

- **Status:** implemented
- **Requirement:** An object named `@NOMERGE_<name>` inside a group stays out of the merge with its subtree; it stays
  a child node of the merged mesh and is exported as `<name>`.
- **Data:** DAT-033
- **Decision:** TM S3 "`@NOMERGE_<name>`"
- **Test:** `tests/verify_lod_exports.py` (`Button`; cannot be re-run as it stands)
- **Code:** `merge.py`

### MRG-005: Exact pivots of kept objects

- **Status:** implemented
- **Requirement:** When an object stays separate deep inside a group, every object above it that the merge removes
  is replaced by an empty with the same name and world transform, so kept objects (for example animated buttons)
  keep their exact pivot and animation.
- **Data:** DAT-043
- **Decision:** TM S1.4
- **Test:** `tests/verify_lod_exports.py` (world matrices and animations unchanged against the baseline; cannot be
  re-run as it stands)
- **Code:** `merge.py`

### MRG-006: Transparent parts apart

- **Status:** implemented
- **Requirement:** Faces with a transparent material (MSFS alpha mode Blend; without MSFS data, Blender's Blended
  render method) never share a mesh with opaque ones: they become a child mesh `<name>_TRANSPARENT` of the merged
  mesh, also for a bone-parented group.
- **Data:** DAT-043
- **Decision:** TM Session 7
- **Test:** no test
- **Code:** `merge.py` (`_material_kind`)

### MRG-007: Warnings

- **Status:** implemented
- **Requirement:** The merge warns (console; in deploys also on stderr, and in the exporter's log) when a group has
  several materials (they stay several materials), more than two UV maps (only two are exported), UV maps that
  differ in name between members (then matched by position), a transparent part, a merged name equal to a kept
  object's name, or an unmerged root (with the reason).
- **Decision:** TM S1.5; TM S3 (merge report on the console)
- **Test:** no test
- **Code:** `merge.py`

## When the Merge Runs

### MRG-008: Only on throwaway objects

- **Status:** implemented
- **Requirement:** The merge runs only where the exported objects are throwaway: in the MSFS 2024 multi-exporter
  (every root carries `msfs_original_name`, DAT-038) or in a background Blender (the deploy scripts quit without
  saving). An interactive plain glTF export leaves the groups unmerged and warns. An export limited to the active
  collection is not merged, with a warning. The merge respects the export's selection and visibility filters.
- **Decision:** TM S1.7
- **Test:** no test
- **Code:** `merge.py` (`pre_export_hook`)

### MRG-009: After LOD culling, from the unchanged file

- **Status:** implemented
- **Requirement:** In a LOD export, parts absent from the LOD are left out before merging (also when Merge on Export
  is off), so each LOD merges only what it keeps. The `.blend` is not changed.
- **Decision:** LOD 8; LOD 18
- **Test:** `tests/verify_lod_exports.py` (vertex and triangle counts of `Panel` per LOD; cannot be re-run as it
  stands)
- **Code:** `merge.py`, `lod_model.py` (`cull_export`)

## Panel

### MRG-010: Zones & Merge Tree panel

- **Status:** implemented
- **Requirement:** Refresh lists the visible objects' zones (ZON-002) and merge groups, nested as in the scene, with
  objects, materials and kept-separate counts per group, and `@NOMERGE_` rows one level below their group.
  Clicking a row selects the object. The active group shows its materials, the transparency split, its UV map names
  and why objects were kept separate. Materials and the transparency split come from the faces, as in the export: a
  slot no face uses does not count, and faces without a material count as one. A group row shows a warning triangle
  exactly when the export would warn about the group (MRG-007). The list does not follow later changes until the next
  Refresh.
- **Data:** DAT-002
- **Decision:** TM Session 4; TM S8.1 to S8.3; TM S9.5
- **Test:** `tests/test_zone_tree.py::test_tree_rows`, `tests/test_zone_tree.py::test_draw_smoke`,
  `tests/test_zone_tree.py::test_totals`
- **Code:** `merge.py` (`FSS_OT_MergeRefresh`)

### MRG-011: New Merge Group

- **Status:** implemented
- **Requirement:** With objects selected that share one parent (or one parent bone), New Merge Group asks for a name
  and creates the empty `@MERGE_<name>` under that parent (or bone), at its position, in the active object's
  collections, and moves the objects under it without moving them in the world. Objects with different parents or
  parent bones are refused with an error. One undo step; Object Mode only.
- **Decision:** none recorded
- **Test:** no test
- **Code:** `merge.py`

### MRG-012: Selecting from the group's details

- **Status:** implemented
- **Requirement:** The rows of the active group's details (each material, transparent parts, each UV map with a
  warning, each reason for staying separate) are buttons with their object count. A click selects those visible
  objects, and Shift adds to the selection; the objects come from the scene at that moment, not from the last Refresh.
  Objects are not listed in the panel. This replaces the Print Details console listing; the export still writes each
  kept object and its reason to its log.
- **Decision:** TM S9.1; TM S9.2
- **Test:** `tests/test_zone_tree.py::test_group_picks`
- **Code:** `merge.py` (`FSS_OT_MergeSelect`, `pick_objects`)

### MRG-013: Scene totals and zone counts

- **Status:** implemented
- **Requirement:** A line above the list shows, for the visible objects, the zones, merge groups, `@NOMERGE_` rows,
  rows with a warning, and the materials faces use. Each zone row shows the meshes below the zone before and after the
  merge. After the merge, each group counts one mesh, or two with both opaque and transparent faces; a mesh without
  faces counts in neither number unless a modifier other than a normals modifier could give it faces. A second line
  shows the same before and after counts for every visible object, in a zone or not, with the change in percent.
- **Decision:** TM S9.3; TM S9.4; TM S14.1, S14.2
- **Test:** `tests/test_zone_tree.py::test_totals` (the count after the merge against the mesh nodes of an export, for a
  zone and for the scene)
- **Code:** `merge.py` (`_totals_text`, `_objects_text`, `_merged_mesh_count`, `_has_geometry`)

### MRG-014: Stray objects

- **Status:** implemented
- **Requirement:** Two buttons below the totals show, at the last Refresh, the visible objects with geometry that no
  group merges, that are not `@NOMERGE_` themselves, are not marked Invisible (TAG-012), are not animated (an action,
  NLA tracks or TAG-013, on the object or on an empty directly above it), and can merge (MRG-003). **Stray**: no
  `@MERGE_` or `@NOMERGE_` node above them. **Below `@NOMERGE_`**: such a node above them. A click selects them from the
  scene as it is now, Shift adds to the selection.
- **Decision:** TM S15.1
- **Test:** `tests/test_zone_tree.py::test_stray`
- **Code:** `merge.py` (`stray_objects`, `is_animated_object`, `FSS_OT_MergeSelectStray`)

### MRG-015: `@ROOT_`

- **Status:** implemented
- **Requirement:** An object named `@ROOT_<name>` is never written. Each of its direct children goes to the glTF root
  and keeps its world position, rotation and scale; their own children stay below them. This holds anywhere in the
  tree (below a zone, below another node) and in every export (File > Export and the MSFS 2024 multi-exporter, for
  both simulators). Inside a merge group it stays out of the merge with its subtree (MRG-003), so its children still
  reach the root. When the `@ROOT_` object or a node above it is animated or follows a bone, the export warns: a child
  that is not animated itself is written once, in place, without that motion. No Export (UV journal decision 130) still removes a
  tagged subtree. Scan Names accepts the name and never reports it as a clash, as it is never exported.
- **Data:** DAT-033
- **Decision:** tags-and-merge journal S17.1
- **Test:** `tests/test_root_marker.py`
- **Code:** `merge.py` (`ROOT_PREFIX`, `_lift_root_markers`, `gather_tree_filter_tag_hook`, `skip_reason`);
  `name_check.py` (`check_names`)

## Wishes

### MRG-020: Decal merge by zone, material and Draw Order

- **Status:** wish
- **Requirement:** Static decals merge per zone, decal material and Draw Order in the export copy; decals parented to
  animated objects are skipped. (Today decals, as blended surfaces, merge into their group's `_TRANSPARENT` mesh
  without grouping by Draw Order.)
- **Decision:** W14
- **Test:** no test
