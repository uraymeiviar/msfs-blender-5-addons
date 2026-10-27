# LOD

[Specification](README.md) / **lod.md**

Automatic levels of detail: the artist models the full detail once; a LOD deploy writes one glTF per LOD, each
leaving out parts too small to see at that LOD. No geometry is cut or reduced. Artist guide:
[../user/lod.md](../user/lod.md).

Terms: a **part** is an object with everything below it, its **size** the largest side of the world bounding box of
the whole part; a **loose piece** is a connected piece of geometry inside one mesh (touching without shared vertices
counts as separate); the **cut-off** of a LOD is the size below which Auto parts and loose pieces are left out.

## Marks

### LOD-001: Marks

- **Status:** implemented
- **Requirement:** Each object has one of four marks, set on the selected objects by the panel's buttons (the
  pressed buttons show the active object's mark): **Auto** (default, no property), **Keep** (never left out by size),
  **Hidden from n** (present in `_LOD00` to the LOD before n, absent from n on), **Visible from n** (absent up to the
  LOD before n, present from n on), n = 1 to 6. Setting one clears the others. Marks are never exported.
- **Data:** DAT-021
- **Decision:** LOD 1, 2, 3, 7
- **Test:** `tests/test_lod_rules.py::test_marks_and_parent_intervals`
- **Code:** `lod.py`, `lod_rules.py`, `lod_model.py`

### LOD-002: A child is never present where its parent is absent

- **Status:** implemented
- **Requirement:** A parent's Hidden from and Visible from limit every object below it, also when the parent itself
  is not exported. The buttons clamp the marks of the selection and of their children to the parent's limits and
  report how many were clamped.
- **Decision:** LOD 13
- **Test:** `tests/test_lod_rules.py::test_marks_and_parent_intervals`,
  `tests/test_lod_rules.py::test_ancestor_outside_export_set_still_constrains_marks`
- **Code:** `lod_rules.py`

### LOD-003: Keep

- **Status:** implemented
- **Requirement:** A Keep object, and an object with a Keep tag (TAG-006), is never left out by size. An Auto
  ancestor stays as long as a Keep object below it is present; its other small Auto children can still be left out.
  A Keep object below an ancestor marked Hidden from n is still absent from n on; Refresh LOD Counts warns "Keep under
  hidden ancestor".
- **Data:** DAT-003, DAT-021
- **Decision:** LOD 11, 13
- **Test:** `tests/test_lod_rules.py::test_keep_protects_only_ancestor_chain`,
  `tests/test_lod_rules.py::test_hidden_keep_does_not_protect_auto_ancestors`
- **Code:** `lod_rules.py`

### LOD-004: Explicit marks win over size

- **Status:** implemented
- **Requirement:** An object with Hidden from or Visible from is never culled by size; within its interval it follows
  its parent (LOD-002). Animated, skinned and Don't Merge objects follow the same rules as all other parts.
- **Decision:** LOD 13
- **Test:** `tests/test_lod_rules.py::test_explicit_marks_override_size_but_not_parent`
- **Code:** `lod_rules.py`

## Export

### LOD-005: Per-LOD export

- **Status:** implemented
- **Requirement:** The LOD deploy script of the aircraft repository writes `<name>_LOD00.gltf` (the full model) up to
  the last LOD that still has objects, at most `_LOD06`; the first LOD without objects ends the list, even if
  Visible from marks would fill later ones. Each LOD starts from the unchanged `.blend`, clears a saved viewport
  filter first, and leaves out parts before merging (MRG-009). The single-file deploy, a plain File > Export and the
  multi-exporter write one file and ignore the marks. The deploy prints one line per LOD (objects in, culled by mark,
  by size, pieces, merged meshes, vertices, the screen range, from which screen size MSFS shows it) and a WARNING when
  MSFS will skip it over part of that range.
- **Data:** DAT-045
- **Decision:** LOD 4, 8, 9, 12, 16, 17
- **Test:** `tests/test_lod_rules.py::test_first_empty_ends_export_list`; `tests/verify_lod_exports.py` (node sets,
  transforms, animations and vertex counts per LOD for both simulators; cannot be re-run as it stands, see
  [README.md](README.md#test-references))
- **Code:** `lod_model.py` (`begin_export`, `cull_export`)

### LOD-006: Size culling of parts

- **Status:** implemented
- **Requirement:** Per LOD k >= 1, an Auto part whose size is below the cut-off of LOD k is left out of `_LODk` and
  later LODs. The cut-off is the size that would be smaller than Pixel Threshold pixels (default 4) on a screen of
  Screen Height pixels (default 1440) at the largest screen size LOD k is shown, from the LOD sphere diameter and the
  XML `minSize` table only (never the effective, vertex-dependent `minSize`). Vertex counts never decide which parts
  are left out. A large child keeps a small parent present.
- **Data:** DAT-003
- **Decision:** LOD 3, 10, 15, 22
- **Test:** `tests/test_lod_rules.py::test_size_boundary_and_large_child`,
  `tests/test_lod_rules.py::test_counts_are_not_culling_inputs`
- **Code:** `lod_rules.py`, `lod_model.py`

### LOD-007: Loose pieces inside a mesh

- **Status:** implemented
- **Requirement:** Per LOD, in the export copy of each mesh, the faces of loose pieces whose size is below the cut-off
  are removed, before merging. The `.blend` is not changed; the viewport preview does not show dropped pieces, the
  panel counts them.
- **Decision:** LOD 18
- **Test:** no test
- **Code:** `lod_model.py` (`mesh_pieces`)
- **Notes:** checked once on the E2 cockpit (LOD journal Session 6).

### LOD-008: Model type and `minSize` tables

- **Status:** implemented
- **Requirement:**
  - **Exterior part** (default): the SDK aircraft table 100, 75, 55, 35, 8, 5, 1 % for `_LOD00` to `_LOD06`.
  - **Interior:** LOD00 100 %, the others the exterior values × interior diameter / Exterior Diameter; without an
    Exterior Diameter the panel shows "exterior diameter missing" and the export stops. An interior writes at most
    `_LOD05`. Edit Explicit minSize Table replaces the derived table and needs no exterior diameter.
  - **Scenery:** the same rules and table as Exterior part.
  - Tables FS24 and FS20 (unverified), seven ratios each, must not increase from one LOD to the next; editing FS24
    also changes FS20 until FS20 is edited. MSFS 2020 forces its second-to-last LOD to at least 1 %.
  - Preview Target (MSFS 2024 or MSFS 2020) picks the table the panel, hints and preview use.
- **Data:** DAT-003
- **Decision:** LOD 10, 14
- **Test:** `tests/test_lod_rules.py::test_interior_settings`, `tests/test_lod_rules.py::test_fs20_penultimate_floor`
- **Code:** `lod_rules.py`, `lod.py`

### LOD-009: Smallest Part Kept

- **Status:** implemented
- **Requirement:** The cut-offs are shown as physical sizes. The field "LOD06 hides parts smaller than" (interior:
  LOD05) edits the Pixel Threshold so that LOD's cut-off becomes the typed size; the other cut-offs follow in
  proportion and are listed per LOD with the number of objects and pieces each hides after a Refresh.
- **Data:** DAT-003
- **Decision:** LOD 21, 22
- **Test:** no test
- **Code:** `lod.py`

## Panel

### LOD-010: Refresh LOD Counts

- **Status:** implemented
- **Requirement:** Refresh LOD Counts measures the model (visible objects only), counts per LOD the objects, the loose
  pieces dropped and the cut-off, names the first LOD that would not be written, fills the quota and hints, and
  exports nothing. Results are cached until the next Refresh; after a change the panel asks for a new one.
- **Data:** DAT-003
- **Decision:** LOD 12
- **Test:** no test
- **Code:** `lod.py`

### LOD-011: Vertex quota

- **Status:** implemented
- **Requirement:** Per LOD: the estimated glTF vertex count (split where UVs, normals or materials differ; shared
  instances once; after culling and loose-piece dropping), the quota (the most vertices the LOD may have and still
  be shown from its own `minSize`, MSFS 2024 High), the share used (red over 100 %), and the screen size from which
  MSFS will show it (the larger of its table value and what its vertex count needs, using MSFS Vertex Factor,
  default 1.15); the last LOD is marked as fallback. For the MSFS 2020 preview target only the vertex count.
- **Data:** DAT-003
- **Decision:** LOD 24
- **Test:** `tests/test_lod_rules.py::test_stored_vertices_shared_accessors`,
  `tests/test_lod_rules.py::test_curve_matches_high_reference_points`,
  `tests/test_lod_rules.py::test_effective_min_sizes_match_msfs_debug_lods`
- **Code:** `lod_rules.py`, `lod_model.py`, `lod.py`
- **Notes:** NOT TESTED: the panel lines.

### LOD-012: Hints

- **Status:** implemented
- **Requirement:** For a chosen LOD, with a select button per hint: the largest contributors (objects and merge
  groups with the most vertices); from LOD 1 on, the meshes holding loose pieces below the cut-off, and the Auto parts
  just above the cut-off that cost many vertices. While Viewport LOD is on, the hints show that LOD.
- **Decision:** none recorded (LOD journal Session 7)
- **Test:** no test
- **Code:** `lod.py`, `lod_model.py`

### LOD-013: Viewport LOD

- **Status:** implemented
- **Requirement:** Viewport LOD 0 to 6 shows what that LOD file keeps: objects absent from it are hidden or shown as
  bounds (Excluded: Hidden, default, or Bounds); the viewport says "Filtered by LODn". A LOD after the last written
  one shows "not written". Off restores every object with its own display setting. Saving undoes the preview and
  re-applies it after; opening a file switches it Off and cleans files saved with hidden objects, so a saved file
  always contains every object as made. While Hidden is in use the panel reminds to turn it Off before exporting by
  hand.
- **Data:** DAT-004, DAT-022
- **Decision:** LOD 34, 35, 36
- **Test:** `tests/test_lod_preview.py::test_preview_active_bounds_and_visibility`,
  `tests/test_lod_preview.py::test_preview_off_restores_original_display_types`,
  `tests/test_lod_preview.py::test_save_with_preview_active_and_reopen`,
  `tests/test_lod_preview.py::test_legacy_file_cleaned_on_open`,
  `tests/test_lod_preview.py::test_single_file_export_contains_all_objects`,
  `tests/test_lod_preview.py::test_hidden_preview_saved_clean`,
  `tests/test_lod_preview.py::test_heatmap_and_preview_coexistence`
- **Code:** `lod.py`, `lod_model.py`

### LOD-014: Auto viewport LOD

- **Status:** implemented
- **Requirement:** Auto picks the LOD from the current view as MSFS would: the LOD sphere's screen ratio from the
  view's field of view and distance, switching the filter only when the LOD changes; after a Refresh it uses the
  effective `minSize` from the vertex counts (MSFS 2024 only). The viewport shows "Auto LODn (ratio)".
- **Data:** DAT-004
- **Decision:** LOD 24
- **Test:** `tests/test_lod_rules.py::test_screen_ratio_and_lod_selection`
- **Code:** `lod.py`

## LOD Sphere

### LOD-015: LOD sphere measured as MSFS does; far origins

- **Status:** implemented
- **Requirement:** The LOD sphere is centred on the box around all `_LOD00` geometry and every exported node position
  (object origins, bone heads), with the radius to the farthest of those points. After a Refresh, the panel warns
  when origins lie more than 5 cm outside the geometry box, with the sphere diameter with and without them and the
  five farthest objects, each with a select button. The tools never move origins. Objects inside merge groups count
  with their origin.
- **Data:** DAT-003
- **Decision:** LOD 29, 30
- **Test:** no test
- **Code:** `lod_model.py` (`_sphere_diameter`, `_far_nodes`)

### LOD-016: Show LOD Sphere

- **Status:** implemented
- **Requirement:** With Show LOD Sphere on (not saved, needs the viewport overlays), the viewport draws from the last
  Refresh the sphere's box and three circles with a labelled centre ("(padded)" when padding is active), the geometry
  box when smaller, and for each of the six box faces the point that sets it (origin red, vertex yellow) with its
  object; the panel lists the six points with select buttons.
- **Data:** DAT-004
- **Decision:** none recorded (LOD journal Session 18)
- **Test:** no test
- **Code:** `lod.py`

### LOD-017: LOD Sphere Diameter (padding)

- **Status:** implemented
- **Requirement:** LOD Sphere Diameter (default 0 = measured) sets the diameter MSFS should use. When it is larger
  than the geometry's sphere, the export adds the padding object (DAT-039) so MSFS measures that diameter; the tables,
  cut-offs and preview use the same diameter. The panel says when a Refresh is needed, the factor MSFS sees, when the
  value is too small to pad, and when origins outside the padding box enlarge the sphere further.
- **Data:** DAT-003, DAT-039
- **Decision:** LOD 30, 31 (supersede LOD 25, 28)
- **Test:** no test
- **Code:** `lod_model.py`, `lod.py`

### LOD-018: Print LOD Settings / XML

- **Status:** implemented
- **Requirement:** Asks for the Model Base Name and prints to the system console the `<LODS>` block for the model XML,
  one entry per written LOD with its `minSize` from the Preview Target's table, plus object counts and warnings per
  LOD. It changes nothing.
- **Data:** DAT-003
- **Decision:** none recorded
- **Test:** no test
- **Code:** `lod.py`

### LOD-019: Children of a hidden reference empty

- **Status:** implemented
- **Requirement:** A hidden empty is not exported and does not count for the LOD sphere; its visible children are
  exported at the same world position, attached to the nearest exported parent or to the glTF root.
- **Decision:** LOD 32, 33 (the exporter's behaviour, accepted)
- **Test:** no test
- **Notes:** checked once on the E2 cockpit's `LIGHTPOS_*` nodes (LOD journal Session 21); verified only for
  unanimated children (UV 33).

## Wishes

### LOD-030: Automated LOD generator with polygon reduction

- **Status:** wish
- **Requirement:** Generates reduced geometry for lower LODs (part classification, per-part decimation, render
  comparison).
- **Decision:** W27; LOD 6 (a later stage); LOD 26 and 27 fix the constraints if it is built: reduction only where the
  artist enables it per object or group, each part reduced before merging with an absolute error bound
- **Test:** no test
- **Notes:** research only (LOD journal Sessions 1 and 15: flow-lod, meshoptimizer).

### LOD-031: Cockpit LOD1 from window visibility

- **Status:** wish
- **Requirement:** Lists the cockpit parts seen through the windows from exterior viewpoints, as the content of the
  cockpit's lower LODs.
- **Decision:** W21
- **Test:** no test

### LOD-032: Silhouette check across LODs

- **Status:** wish
- **Requirement:** Compares silhouette masks of LOD0 and each lower LOD at its switch distance from several angles and
  flags differences.
- **Decision:** W23
- **Test:** no test
