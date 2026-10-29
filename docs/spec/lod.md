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
- **Requirement:** Each object has one of four marks: **Auto** (default, no property), **Keep** (never left out by
  size), **Hidden from n** (present in `_LOD00` to the LOD before n, absent from n on), **Visible from n** (absent up
  to the LOD before n, present from n on), n = 1 to 6. Setting one clears the others. Marks are never exported. The
  panel **Object LOD** sets them on the selected objects:
  - a line names the selection ("Selected: n object(s) (active: NAME)", or "Select objects to mark them"), a line
    gives the active object's mark ("Active object: Auto", "Keep", "Hidden from LODn", "Visible from LODn"), and
    "Selected objects: mixed marks" shows when the selected objects' marks differ (Hidden from n and Hidden from m
    count as different marks);
  - one row Auto / Keep / Hidden from / Visible from; the pressed button follows a pending choice, else the active
    object's mark. Auto and Keep apply at once. Hidden from and Visible from only make the pending choice (DAT-008;
    they need a selection) and show the number row; a number applies the mark;
  - the number row, "Visible in:" with LOD0 to LOD6, shows only for Hidden from and Visible from and lights the LODs
    in which the active object is visible under the shown mark. Under Hidden from a click on n (0 to 5) sets Hidden
    from n + 1 (n is the last visible LOD); under Visible from a click on n (1 to 6) sets Visible from n (the first
    visible LOD); the button outside that range (6, or 0) is disabled. Auto and Keep show no number row;
  - applying any mark clears the pending choice; drawing the panel writes nothing.
- **Data:** DAT-008, DAT-021
- **Decision:** LOD 1, 2, 3, 7; MAT 22 (the panel), MAT 23 (the Visible in row)
- **Test:** `tests/test_lod_rules.py::test_marks_and_parent_intervals`, `tests/test_panels.py::test_object_lod`
- **Code:** `lod.py` (`FSS_PT_lod`, `FSS_OT_SetObjectLod`, `FSS_OT_LodPending`, `object_mark`), `lod_rules.py`,
  `lod_model.py`
- **Notes:** never seen in an interactive Blender (button look, the number row appearing on a click; material
  management journal Sessions 23, 24).
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
    Exterior Diameter (and without an explicit table) Export Settings draws the Exterior Diameter field red with one
    message under it ("Exterior diameter missing: enter the exterior model's LOD sphere diameter"), and the export
    stops. An interior writes at most `_LOD05`. Edit Explicit minSize Table replaces the derived table and needs no
    exterior diameter.
  - **Scenery:** the same rules and table as Exterior part.
  - Tables FS24 and FS20 (unverified), seven ratios each, must not increase from one LOD to the next; editing FS24
    also changes FS20 until FS20 is edited. MSFS 2020 forces its second-to-last LOD to at least 1 %.
  - Preview Target (Export Settings > Advanced; MSFS 2024 or MSFS 2020) picks the table that LOD Settings, its
    hints and the preview use.
- **Data:** DAT-003
- **Decision:** LOD 10, 14; material management journal Session 26 (one red field instead of two messages)
- **Test:** `tests/test_lod_rules.py::test_interior_settings`, `tests/test_lod_rules.py::test_fs20_penultimate_floor`,
  `tests/test_panels.py::test_exterior_diameter_message` (one message)
- **Code:** `lod_rules.py`, `lod.py`

### LOD-009: Smallest Part Kept

- **Status:** implemented
- **Requirement:** The cut-offs are shown as physical sizes in Export Settings (subpanel of LOD Settings), once they
  can be computed (after the first Refresh). The field "LOD06 hides parts smaller than" (interior: LOD05) edits the
  Pixel Threshold so that LOD's cut-off becomes the typed size; the other cut-offs follow in proportion. The box
  "Hidden parts, smaller than:" lists LOD01 to that LOD with its cut-off and, after a Refresh, the number of objects
  and pieces each hides.
- **Data:** DAT-003
- **Decision:** LOD 21, 22; MAT 22 (in LOD Settings)
- **Test:** no test
- **Code:** `lod.py` (`FSS_PT_LodExport`)
## Panels

### LOD-010: Refresh LOD Counts

- **Status:** implemented
- **Requirement:** Refresh LOD Counts, in the panel **LOD Settings**, measures the model (visible objects only),
  counts per LOD the objects, the loose pieces dropped and the cut-off, names the first LOD that would not be
  written, fills the quota and hints, and exports nothing; opening a file does not run it (GEN-041). After a Refresh
  the panel shows "Cached source counts — Refresh after editing" and, per written LOD, a row: "LODnn", a bar whose
  full length is LOD00's object count, with the count and, from LOD01 on, its share of LOD00 ("1,852 obj (60 %)"),
  the dropped loose pieces ("-12,832 pcs", empty when none) and the cut-off ("hides < 1.1 cm", empty on LOD00). The
  first LOD without objects reads "LODnn: not written, no objects". Results are cached until the next Refresh; a
  changed LOD setting clears them, and Quota and Hints then asks for a Refresh.
- **Data:** DAT-003
- **Decision:** LOD 12; MAT 21 (stays manual), MAT 22 (the panel), MAT 25 (A: the bars)
- **Test:** `tests/test_panels.py::test_lod_settings_bars` (one bar per written LOD, factor count / LOD00 count, the
  share from LOD01 on, the cut-off text; drawing writes nothing)
- **Code:** `lod.py` (`FSS_OT_LodRefresh`, `FSS_PT_LodSettings`)
- **Notes:** never seen in an interactive Blender (whether the columns line up at a normal sidebar width; material
  management journal Session 28).
### LOD-011: Vertex quota

- **Status:** implemented
- **Requirement:** Per LOD, the estimated glTF vertex count (split where UVs, normals or materials differ; shared
  instances once; after culling and loose-piece dropping), the quota (the most vertices the LOD may have and still
  be shown from its own `minSize`, MSFS 2024 High), the share used, and the screen size from which MSFS will show it
  (the larger of its table value and what its vertex count needs, using MSFS Vertex Factor, default 1.15). The
  subpanel **Quota and Hints** of LOD Settings shows them after a Refresh (before it: "Click Refresh LOD Counts to
  compute estimates"):
  - the header sentence "A LOD is shown only when the model is large enough on screen for its vertex count." (on two
    lines);
  - a table with the columns LOD, Vertices, Quota, Used (a bar filled up to 100 %, red above it, with the
    percentage) and MSFS shows it from: "never (needs N %; table T %)" when the needed size is above 100 % of the
    screen, otherwise "N % of screen (table T %)"; the last written LOD gets ", fallback";
  - for the MSFS 2020 preview target, which has no vertex rule, the header "MSFS 2020 has no vertex rule: the
    vertex estimate per LOD only." and only the columns LOD and Vertices;
  - under the table, when pieces are dropped, one box "Dropped at export (loose pieces below the cut-off):" with
    "LODnn: N pcs, ~V vtx" per LOD that drops pieces.
- **Data:** DAT-003
- **Decision:** LOD 24; MAT 25 (B: the table)
- **Test:** `tests/test_lod_rules.py::test_stored_vertices_shared_accessors`,
  `tests/test_lod_rules.py::test_curve_matches_high_reference_points`,
  `tests/test_lod_rules.py::test_effective_min_sizes_match_msfs_debug_lods`,
  `tests/test_panels.py::test_lod_settings_bars` (header, columns, Used bars, the "never" text, ", fallback", MSFS
  2020 columns)
- **Code:** `lod_rules.py`, `lod_model.py`, `lod.py` (`FSS_PT_LodQuotaHints`)
- **Notes:** the MSFS 2020 header wording is the building agent's, not decided (material management journal
  Session 28). NOT TESTED: the box of dropped pieces. Never seen in an interactive Blender (whether the long cells
  fit the column).
### LOD-012: Hints

- **Status:** implemented
- **Requirement:** Under the quota table, **Per LOD Vertex Contributors** with one button per written LOD; the LOD
  shown is the one Viewport LOD previews when that is a written LOD, else the chosen button's. For that LOD:
  - a box "LODnn: ~N vtx" (the LOD's vertex estimate) with its five largest contributors (objects and merge groups
    with the most vertices), each with its name, a bar for its share of the LOD's vertices with the text
    "~80,316 (6.4 %)", and a select button; "None" when there are none;
  - from LOD 1 on, the meshes holding loose pieces below the cut-off ("Loose pieces below X m (dropped at
    export):") and the Auto parts just above the cut-off that cost many vertices ("Near cut-off (X m, candidates to
    hide):"), up to five each, with select buttons.
- **Decision:** none recorded (LOD journal Session 7); MAT 25 (C: the label and the bars)
- **Test:** `tests/test_panels.py::test_lod_settings_bars` (the label, the contributor bars)
- **Code:** `lod.py` (`FSS_PT_LodQuotaHints`), `lod_model.py`
- **Notes:** the total line "LODnn: ~N vtx" is the building agent's wording, not decided (material management
  journal Session 28). NOT TESTED: the loose-piece and near-cut-off lists, the select buttons.
### LOD-013: Viewport LOD

- **Status:** implemented
- **Requirement:** The panel **Viewport LOD** has the buttons Off, Auto (LOD-014) and 0 to 6. A level shows what that
  LOD file keeps: objects absent from it are hidden or shown as bounds; the viewport says "Filtered by LODn". LOD0 is
  not Off: it leaves out objects marked Visible from. A LOD after the last written one shows "not written". Off
  restores every object with its own display setting. The row Excluded (Hidden, default, or Bounds) shows only while
  a preview is on (a level or Auto); while Hidden is in use the panel reminds to set Viewport LOD Off before
  exporting by hand; a preview error is shown in the panel. Saving undoes the preview and re-applies it after;
  opening a file switches it Off and cleans files saved with hidden objects, so a saved file always contains every
  object as made.
- **Data:** DAT-004, DAT-022
- **Decision:** LOD 34, 35, 36; MAT 22 (the panel); material management journal Session 25 (Excluded only with a
  preview)
- **Test:** `tests/test_lod_preview.py::test_preview_active_bounds_and_visibility`,
  `tests/test_lod_preview.py::test_preview_off_restores_original_display_types`,
  `tests/test_lod_preview.py::test_save_with_preview_active_and_reopen`,
  `tests/test_lod_preview.py::test_legacy_file_cleaned_on_open`,
  `tests/test_lod_preview.py::test_single_file_export_contains_all_objects`,
  `tests/test_lod_preview.py::test_hidden_preview_saved_clean`,
  `tests/test_lod_preview.py::test_heatmap_and_preview_coexistence`,
  `tests/test_panels.py::test_viewport_lod_excluded`
- **Code:** `lod.py` (`FSS_PT_LodViewport`), `lod_model.py`
### LOD-014: Auto viewport LOD

- **Status:** implemented
- **Requirement:** Auto picks the LOD from the current view as MSFS would: the LOD sphere's screen ratio from the
  view's field of view and distance, switching the filter only when the LOD changes; after a Refresh it uses the
  effective `minSize` from the vertex counts (MSFS 2024 only). The viewport shows "Auto LODn (ratio)", the Viewport
  LOD panel "Auto: LODnn (screen ratio x %)".
- **Data:** DAT-004
- **Decision:** LOD 24
- **Test:** `tests/test_lod_rules.py::test_screen_ratio_and_lod_selection`
- **Code:** `lod.py`

## LOD Sphere

### LOD-015: LOD sphere measured as MSFS does; far origins

- **Status:** implemented
- **Requirement:** The LOD sphere is centred on the box around all `_LOD00` geometry and every exported node position
  (object origins, bone heads), with the radius to the farthest of those points. After a Refresh, Export Settings
  shows "Model diameter: X (measured at Refresh)" and warns when origins lie more than 5 cm outside the geometry box, with the sphere diameter with and without them and the
  five farthest objects, each with a select button. The tools never move origins. Objects inside merge groups count
  with their origin.
- **Data:** DAT-003
- **Decision:** LOD 29, 30
- **Test:** no test
- **Code:** `lod_model.py` (`_sphere_diameter`, `_far_nodes`)

### LOD-016: Show LOD Sphere

- **Status:** implemented
- **Requirement:** Show LOD Sphere (a toggle in Export Settings, shown after the first Refresh; not saved, needs the
  viewport overlays) draws from the last Refresh the sphere's box and three circles with a labelled centre
  ("(padded)" when padding is active), the geometry box when smaller, and for each of the six box faces the point
  that sets it (origin red, vertex yellow) with its object; while it is on, Export Settings lists the six points with
  select buttons.
- **Data:** DAT-004
- **Decision:** none recorded (LOD journal Session 18); MAT 22 (in LOD Settings)
- **Test:** no test
- **Code:** `lod.py`
### LOD-017: Pad LOD Sphere To (padding)

- **Status:** implemented
- **Requirement:** The field **Pad LOD Sphere To** in Export Settings (property `reference_size`, default 0 = no
  padding, the measured sphere) sets the diameter MSFS should use. The line under it gives the diameter MSFS uses
  without padding ("Without padding: 15.94 m (0 = no padding)"), or, before the first measurement, "0 = no padding;
  press Refresh LOD Counts to measure the model". When the value is larger than the geometry's sphere, the export
  adds the padding object (DAT-039) so MSFS measures that diameter; the tables, cut-offs and preview use the same
  diameter. The panel says when a Refresh is needed, the factor MSFS sees, when the value is too small to pad, and
  when origins outside the padding box enlarge the sphere further.
- **Data:** DAT-003, DAT-039
- **Decision:** LOD 30, 31 (supersede LOD 25, 28); MAT 24 (the label and the line)
- **Test:** `tests/test_panels.py::test_exterior_diameter_message` (the label and the line only)
- **Code:** `lod_model.py`, `lod.py` (`FSS_PT_LodExport`)
- **Notes:** NOT TESTED: the padding object and the messages.
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
