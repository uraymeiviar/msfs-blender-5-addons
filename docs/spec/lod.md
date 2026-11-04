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
  SDK's aircraft table 100, 75, 55, 35, 8, 5, 1 % only, unless the artist has set Hides Under (LOD-009). Neither the
  `minSize` written to the XML nor the vertex count enters it: vertex counts never decide which parts are left out. A
  large child keeps a small parent present.
- **Data:** DAT-003
- **Decision:** LOD 3, 10, 15, 22, 43
- **Test:** `tests/test_lod_rules.py::test_size_boundary_and_large_child`,
  `tests/test_lod_rules.py::test_counts_are_not_culling_inputs`
- **Code:** `lod_rules.py`, `lod_model.py`

### LOD-007: Loose pieces inside a mesh

- **Status:** implemented
- **Requirement:** Per LOD, in the export copy of each mesh, the faces of loose pieces whose size is below the cut-off
  are removed, before merging, except on an object with Keep or a Whole tag (TAG-014), a mesh with shape keys, or a mesh
  with an Armature modifier. The `.blend` is not changed; the viewport preview does not show dropped pieces, the panel
  counts them.
- **Decision:** LOD 18; TM S15.2
- **Test:** `tests/test_zone_tree.py::test_whole` (Whole only)
- **Code:** `lod_model.py` (`mesh_pieces`)
- **Notes:** checked once on the E2 cockpit (LOD journal Session 6).

### LOD-008: One `minSize` table

- **Status:** implemented
- **Requirement:** Every model has the same rules: there is no model type and no exterior diameter. One table of seven
  percentages, default 7, 6, 5, 4, 3, 2, 1 (the SDK's convention of leaving the choice to the vertex rule), is written
  to the XML for both simulators; a high value holds a LOD back. Values must not increase from one LOD to the next
  (Refresh and export stop with "minSize values must be in descending order"). MSFS 2020 is predicted with the same
  vertex rule, and its second-to-last LOD is forced to at least 1 %. Changing a value keeps the counts valid and updates
  Shows From and the view table at once. The table is drawn with LOD-009.
- **Data:** DAT-003
- **Decision:** LOD 37, 38, 43 (replace LOD 14 and the model types of LOD 10)
- **Test:** `tests/test_lod_rules.py::test_one_table_for_every_model`, `tests/test_lod_rules.py::test_fs20_penultimate_floor`,
  `tests/test_panels.py::test_export_settings_one_table`, `tests/test_panels.py::test_lod_settings_bars` (a typed value)
- **Code:** `lod_rules.py` (`MSFS_MIN_SIZES`, `min_sizes`), `lod.py`
- **Notes:** MSFS 2020's vertex rule is assumed, not checked; the maintainer accepted the inaccuracy (LOD 38).

### LOD-009: Settings per LOD

- **Status:** implemented
- **Requirement:** Export Settings (subpanel of LOD Settings) has one table per LOD, with the columns LOD, Hides Under
  (metres, an input; `-` on LOD00), minSize % (an input, LOD-008) and Shows From (the larger of minSize and what the
  vertex count needs at MSFS Quality; `fallback` on the last written LOD; `-` when not written or before a Refresh), and
  two lines above it saying what the first two columns do. Hides Under replaces the cut-off of LOD-006; a value of 0
  takes the cut-off from LOD-006, and Refresh writes it in, so later changes of the diameter leave the values alone.
- **Data:** DAT-003
- **Decision:** LOD 43; MAT 22 (in LOD Settings); replaces LOD 21 (Smallest Part Kept) and the box of hidden parts
- **Test:** `tests/test_lod_rules.py::test_hides_under_wins`, `tests/test_panels.py::test_export_settings_one_table`,
  `tests/test_panels.py::test_lod_settings_bars` (written at the first Refresh and kept)
- **Code:** `lod.py` (`_draw_hides_table`), `lod_rules.py` (`decide`)

## Panels

### LOD-010: Refresh LOD Counts

- **Status:** implemented
- **Requirement:** Refresh LOD Counts, in the panel **LOD Settings**, measures the model (visible objects only), counts
  per LOD the objects, the vertices and the loose pieces dropped, fills the hints, names the first LOD that would not
  be written, and exports nothing. It also runs when a file opens (GEN-041). After a Refresh the panel shows "Cached
  counts: Refresh after editing" above the view table (LOD-011), and "LODnn: not written, no objects" for the first LOD
  without objects. Results are cached until the next Refresh; a changed Hides Under or padding clears them, a changed
  minSize or MSFS Quality does not. Counts saved in a file are not trusted: the Refresh on opening replaces them.
- **Data:** DAT-003
- **Decision:** LOD 12, 42, 45 (replaces MAT 21 for this operator); MAT 22 (the panel)
- **Test:** `tests/test_panels.py::test_lod_settings_bars` (drawing writes nothing), `tests/test_materials.py::test_refresh_on_open`
- **Code:** `lod.py` (`FSS_OT_LodRefresh`, `FSS_PT_LodSettings`)

### LOD-011: The table at this view

- **Status:** implemented
- **Requirement:** LOD Settings shows what MSFS does at the Blender view, whatever Viewport LOD is set to: the screen
  ratio follows the view (a timer that keeps running without a preview, reading the sphere of the last Refresh, hiding
  nothing). Above the table, the dropdown MSFS Quality (Ultra, High, Medium, Low; default High) and the line "This
  view: LODnn (screen ratio x %)". One row per written LOD:
  - **LOD:** "00 -", "01 <1.1cm" (the cut-off); the LOD MSFS shows here is a highlighted button that does nothing;
  - **Vert/Obj:** estimated glTF vertices (split where UVs, normals or materials differ; shared instances once; after
    culling and loose-piece dropping) and objects, in two decimals ("1.11M/3.48K");
  - **Used:** a bar with the percentage: vertices against the limit at this view;
  - **ToReduce:** vertices minus limit on LODs more detailed than the one shown, when above the limit; else `-`;
  - **Reduced:** a bar of the share of the previous LOD's vertices this step removed (not scaled to the largest step,
    which would favour the heavy LODs), with the step as text, vertices and objects ("-1.29K/-180").

  The limit at a screen ratio is the most vertices the High SDK curve allows, with the ratio divided by the quality
  factor (Ultra 0.7071, High 1, Medium 1.4142, Low 2), divided by MSFS Vertex Factor (default 1.15) to convert to the
  panel's count. The same limit holds for every LOD at one view. Below the table, "Over the limit, shown as the last
  LOD" when even the last LOD is above it. Before a Refresh, one line asks for it.
- **Data:** DAT-003, DAT-004
- **Decision:** LOD 24, 39, 40, 41
- **Test:** `tests/test_panels.py::test_viewport_lod_view_quota`,
  `tests/test_lod_rules.py::test_quota_at_view_agrees_with_selection`,
  `tests/test_lod_rules.py::test_quality_columns_match_sdk_table`,
  `tests/test_lod_rules.py::test_stored_vertices_shared_accessors`,
  `tests/test_lod_rules.py::test_curve_matches_high_reference_points`,
  `tests/test_lod_rules.py::test_effective_min_sizes_match_msfs_debug_lods`
- **Code:** `lod_rules.py` (`vertex_quota_at`, `effective_min_sizes`), `lod.py` (`_draw_view_quota`, `update_view_ratio`)
- **Notes:** only High is measured against the simulator; the other qualities follow the SDK's table. A bar above 100 %
  is full and blue, not red (`alert` does not colour a progress bar; left for later).

### LOD-012: Hints

- **Status:** implemented
- **Requirement:** The subpanel **Hints** of LOD Settings has **Per LOD Vertex Contributors** with one button per
  written LOD; the LOD shown is the one Viewport LOD previews when that is a written LOD, else the chosen button's. For
  that LOD:
  - a box "LODnn: ~N vtx" (the LOD's vertex estimate) with its five largest contributors (objects and merge groups
    with the most vertices), each with its name, a bar for its share of the LOD's vertices with the text
    "~80,316 (6.4 %)", and a select button; "None" when there are none;
  - from LOD 1 on, the meshes holding loose pieces below the cut-off ("Loose pieces below X m (dropped at
    export):") and the Auto parts just above the cut-off that cost many vertices ("Near cut-off (X m, candidates to
    hide):"), up to five each, with select buttons.
- **Decision:** none recorded (LOD journal Session 7); MAT 25 (C: the label and the bars); LOD 42 (the quota table left
  this subpanel)
- **Test:** `tests/test_panels.py::test_lod_settings_bars` (the label, the contributor bars)
- **Code:** `lod.py` (`FSS_PT_LodQuotaHints`), `lod_model.py`
- **Notes:** the total line "LODnn: ~N vtx" is the building agent's wording, not decided (material management
  journal Session 28). NOT TESTED: the loose-piece and near-cut-off lists, the select buttons.

### LOD-013: Viewport LOD

- **Status:** implemented
- **Requirement:** The panel **Viewport LOD** holds only the viewport's settings: the buttons Off, Auto (LOD-014) and
  0 to 6, the row Excluded, a reminder and a preview error. A level shows what that
  LOD file keeps: objects absent from it are hidden or shown as bounds; the viewport says "Filtered by LODn". LOD0 is
  not Off: it leaves out objects marked Visible from. A LOD after the last written one shows "not written". Off
  restores every object with its own display setting. The row Excluded (Hidden, default, or Bounds) shows only while
  a preview is on (a level or Auto); while Hidden is in use the panel reminds to set Viewport LOD Off before
  exporting by hand; a preview error is shown in the panel. Saving undoes the preview and re-applies it after;
  opening a file switches it Off and cleans files saved with hidden objects, so a saved file always contains every
  object as made.
- **Data:** DAT-004, DAT-022
- **Decision:** LOD 34, 35, 36, 39; MAT 22 (the panel); material management journal Session 25 (Excluded only with a
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
  effective `minSize` from the vertex counts at MSFS Quality. The viewport shows "Auto LODn (ratio)".
- **Data:** DAT-004
- **Decision:** LOD 24
- **Test:** `tests/test_lod_rules.py::test_screen_ratio_and_lod_selection`
- **Code:** `lod.py`

## LOD Sphere

### LOD-015: LOD sphere measured as MSFS does; far origins

- **Status:** implemented
- **Requirement:** The LOD sphere is centred on the box around all `_LOD00` geometry and every exported node position
  (object origins, bone heads), with the radius to the farthest of those points. After a Refresh, Export Settings
  shows "Model diameter: X (measured at Refresh)" and warns when origins lie more than 5 cm outside the geometry box,
  with the sphere diameter with and without them and the five farthest objects, each with a select button. With
  padding, the warning measures against the padding box instead and reads "origins outside the padding"; an origin
  inside the box does not change the sphere, one outside it enlarges the box and moves the centre. While the padding
  has changed without a Refresh, the warning is not shown. The tools never move origins. Objects inside merge groups
  count with their origin.
- **Data:** DAT-003
- **Decision:** LOD 29, 30, 47
- **Test:** `tests/test_panels.py::test_lod_settings_bars` (the warning at 1x, 2x and 10x, and before a Refresh)
- **Code:** `lod_model.py` (`_sphere_diameter`, `_far_nodes`)

### LOD-016: Show LOD Sphere

- **Status:** implemented
- **Requirement:** Show LOD Sphere (a toggle in Export Settings, shown after the first Refresh; not saved, needs the
  viewport overlays) draws from the last Refresh the sphere's box and three circles with a labelled centre
  ("(padded)" when padding is active), the geometry box when smaller, and for each of the six box faces the point
  that sets it (origin red, vertex yellow) with its object. The panel does not list those points.
- **Data:** DAT-004
- **Decision:** none recorded (LOD journal Session 18); MAT 22 (in LOD Settings); LOD 44 (no list in the panel)
- **Test:** no test
- **Code:** `lod.py`
### LOD-017: Pad LOD Sphere Multiplier (padding)

- **Status:** implemented
- **Requirement:** The field **Pad LOD Sphere Multiplier** in Export Settings (property `pad_factor`, 1.00 to 10.00,
  default 1.00 = no padding) multiplies the geometry's sphere. Above 1, the export adds the padding object (DAT-039) so
  that MSFS measures that diameter; the view table, Shows From and the preview use the same diameter. Typed Hides Under
  values stay. The line under the field gives "MSFS sees: X (no padding)" or "MSFS sees: X (geometry Y)", or asks for a
  Refresh after a change; above 5 a line says that it has not been tested in the simulator. A diameter saved by an older
  version (`reference_size`) is still honoured by the export until a Refresh converts it to the multiplier.
- **Data:** DAT-003, DAT-039
- **Decision:** LOD 46 (supersedes LOD 31); LOD 30; replaces MAT 24
- **Test:** `tests/test_panels.py::test_export_settings_one_table` (the field), `tests/test_panels.py::test_lod_settings_bars`
  (the diameter at 2x and 10x, no padding at 1x, the conversion), `tests/build_lod_scene.py` (an old file's diameter)
- **Code:** `lod_model.py` (`build_plan`), `lod.py` (`FSS_PT_LodExport`, `FSS_OT_LodRefresh`)
- **Notes:** padding has been measured to a radius of 11 m (LOD journal Session 17). The maintainer tested an
  older-field 10 m on the E2 cockpit (about 2.6x): LOD06 became LOD03 at the same view. NOT TESTED: the padding object
  in an export by this version.

### LOD-018: Print LOD Settings / XML

- **Status:** implemented
- **Requirement:** Asks for the Model Base Name and prints to the system console the `<LODS>` block for the model XML,
  one entry per written LOD with its `minSize` (LOD-008), plus object counts, cut-offs and warnings per
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
