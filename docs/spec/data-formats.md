# Data Formats

[Specification](README.md) / **data-formats.md**

What the add-ons store in a `.blend`, beside it, and what they write into the glTF. Each entry names the
requirements that use it. Properties that are registered (`bpy.props`) are saved with the file unless marked
"not saved" (`SKIP_SAVE`); custom properties (`obj["..."]`) are always saved.

## General

### DAT-001: Naming of FSS data

- **Status:** implemented
- **Requirement:** Every property, custom property, mesh attribute and scene setting written by fss_blender_tools
  is named `fss_<module>_<name>` or `fss_<name>`; data that only lives during a run or a preview starts with
  `_fss_`. Text blocks are named `FSS <Tool> Report`. Exporter data of the FSS fork is named `msfs_fss_<name>`.
- **Decision:** UV 87 (`fss_` keys stripped from extras rely on it); AGENTS.md, Pitfalls ("name new properties
  `fss_...`")
- **Test:** `tests/test_zone_tree.py::test_gltf_leak` (relies on the prefix)
- **Notes:** the exporter's `msfs_fss_` prefix is not covered by the `fss_` strip (DAT-041).

## Scene Settings (fss_blender_tools)

### DAT-002: `Scene.fss_merge`

- **Status:** implemented
- **Requirement:** Property group with `enabled` (Merge on Export, bool, default on) and `skip_tags` (Don't Merge
  tags, `;`-separated string). `items`, `active` and `scanned` hold the last Refresh of the Zones & Merge Tree
  panel and are rebuilt by Refresh.
- **Used by:** MRG-001, MRG-010, TAG-005, ZON-002
- **Decision:** TM S1.6; TM S8.2
- **Test:** `tests/test_zone_tree.py::test_tree_rows`
- **Code:** `merge.py` (`FSS_MergeSettings`)

### DAT-003: `Scene.fss_lod_settings`

- **Status:** implemented
- **Requirement:** Property group of the LOD export settings, saved per scene: `model_type` (EXTERIOR, INTERIOR,
  SCENERY; default EXTERIOR), `min_sizes_fs24` and `min_sizes_fs20` (seven ratios each), `explicit_fs24` and
  `explicit_fs20` (the table was edited by hand), `exterior_diameter` (m), `reference_size` (LOD Sphere Diameter,
  0 = measured), `screen_height` (px, default 1440), `pixel_threshold` (px, default 4), `msfs_vertex_factor`
  (default 1.15, 0.5 to 2.0), `keep_tags` (`;`-separated string), `preview_target` (fs24 or fs20). Measured
  values of the last Refresh LOD Counts (diameters, boxes, counts, cut-offs, quotas, hints) are fields that are
  not saved.
- **Used by:** LOD-001 to LOD-019, TAG-006
- **Decision:** LOD 5, 8, 10, 22, 31
- **Test:** `tests/test_lod_rules.py::test_interior_settings`
- **Code:** `lod.py` (`FSS_LodSettings`)

### DAT-004: LOD viewport settings

- **Status:** implemented
- **Requirement:** `Scene.fss_viewport_lod` (-1 = Off, 0 to 6), `fss_viewport_lod_auto` (not saved),
  `fss_lod_preview_display` (HIDDEN or BOUNDS, default HIDDEN), `fss_lod_export_level` (not saved, set during a
  LOD export), `fss_lod_show_sphere` (not saved, default off).
- **Used by:** LOD-012, LOD-013, LOD-016
- **Decision:** LOD 36
- **Test:** `tests/test_lod_preview.py::test_preview_active_bounds_and_visibility`
- **Code:** `lod.py`

### DAT-005: `Scene.fss_visibility`

- **Status:** implemented
- **Requirement:** Property group of Visibility Scoring: `cameras` (per scene camera: `camera` pointer, `include`,
  default off, `mode` LOOK_AROUND or FIXED_VIEW, default LOOK_AROUND), `states` (Animation Steps, 2 to 10,
  default 5), `floor` (Direction Floor, 0 to 1, default 0.2), `falloff` (0.1 to 10, default 1.0), `cube_res`
  (256 to 4096, default 1024), `min_px_threshold` (1 to 100 px, default 10).
- **Used by:** UV-VIS-001 to UV-VIS-006
- **Decision:** UV 80, 83, 86, 103
- **Test:** `tests/uv_prototype/test_visibility.py::test_camera_renaming_and_deletion`
- **Code:** `visibility.py` (`FSS_VisibilitySettings`)

### DAT-006: Other scene settings

- **Status:** implemented
- **Requirement:** Saved with the scene:

  | Property | Type, default | Used by |
  | :--- | :--- | :--- |
  | `fss_name_check` | group: scan results, `include_bones` (on), `show_rules` (all) | GEN-008 |
  | `fss_tag_name` | string, the tag field of the Tags panel | TAG-002 |
  | `fss_origin_target` | enum, default `FACE_NZ` (Bottom -Z) | GEN-002 |
  | `fss_empty_parent_mode`, `_suffix`, `_prefix`, `_manual_name` | enum MANUAL / SUFFIX / PREFIX; `_PARENT`; `PARENT_` | GEN-001 |
  | `fss_empty_bounds_mode`, `_in_front`, `_hierarchy_text` | ALL / SELECTED / OFF, default ALL; on; on | GEN-003 |
  | `fss_uv_heatmap_mode`, `_grid`, `_grid_cells`, `_grid_labels` | SHAPE / DENSITY / VISIBILITY; on; 16; on | GEN-005 |
  | `fss_uv_heatmap_show`, `_distortion`, `_opacity` | not saved; off; BOTH | GEN-005 |
  | `fss_uv_autoseam_limit` | float 1.05 to 2.0, default 1.25 | UV-SEAM-004 |
  | `fss_uv_target_density` | float px/cm, default 20.48 | UV-DEN-001 |
  | `fss_uv_density_freedom_min`, `_max` | float, default 0.9 and 1.1 | UV-DEN-002 |

  The scene custom properties `_fss_empty_parent_custom_name` and `_fss_empty_parent_custom_obj` remember a
  manual empty-parent name for one object.
- **Decision:** UV 66 (heatmap grid saved), UV 88, UV 106; others none recorded
- **Test:** `tests/test_panels.py::test_draw_all` (every panel draws with these properties)

## Object Data

### DAT-020: `fss_tags`

- **Status:** implemented
- **Requirement:** Custom string property on an object: its tags, separated by `;`, each tag any non-empty name
  without `;`. An object without tags has no property.
- **Used by:** TAG-001 to TAG-007, MRG-007, LOD-003
- **Decision:** TM S1.1
- **Test:** no test of the format; read in `tests/build_lod_scene.py`
- **Code:** `tags.py`

### DAT-021: LOD marks `fss_lod`, `fss_lod_show_from`, `fss_lod_keep`

- **Status:** implemented
- **Requirement:** Custom integer properties on an object: `fss_lod` = n hides it from LOD n on (1 to 6),
  `fss_lod_show_from` = n shows it from LOD n on (1 to 6), `fss_lod_keep` = 1 protects it from size culling. An
  object has at most one of them; none means Auto. Values outside 0 to 6 are clamped when read.
- **Used by:** LOD-001 to LOD-004
- **Decision:** LOD 1, 2, 3, 7, 13
- **Test:** `tests/test_lod_rules.py::test_marks_and_parent_intervals`
- **Code:** `lod_model.py`

### DAT-022: `_fss_lod_hidden`

- **Status:** implemented
- **Requirement:** Custom property set by the viewport LOD preview on an object it changed: `True` when it hid
  the object, or the original display type (string) when it showed the object as bounds. It is removed when the
  preview is turned off, before a save (and set again after), and when a file is opened.
- **Used by:** LOD-012
- **Decision:** LOD 34, 35, 36
- **Test:** `tests/test_lod_preview.py::test_hidden_preview_saved_clean`,
  `tests/test_lod_preview.py::test_legacy_file_cleaned_on_open`
- **Code:** `lod_model.py` (`restore_filter`), `lod.py`

### DAT-023: Density mark `fss_uv_density_own`, `fss_uv_density_min`, `fss_uv_density_max`

- **Status:** implemented
- **Requirement:** Registered object properties: `fss_uv_density_own` (bool, default off) turns the mark on;
  `fss_uv_density_min` and `fss_uv_density_max` (float, default 1.0) are its factor range, kept in order
  (min <= max) when edited. A mark that is off counts as x1.0.
- **Used by:** UV-DEN-003, ZON-003
- **Decision:** UV 108
- **Test:** `tests/test_density_marks.py::test_defaults`, `tests/test_density_marks.py::test_multiplication`
- **Code:** `uv_marks.py`

### DAT-027: Direction mark `fss_uv_direction`

- **Status:** implemented
- **Requirement:** Custom string property on an object: FREE, UPRIGHT, FLIP or QUARTER. Missing means inherited
  from the nearest marked ancestor, else FREE.
- **Used by:** UV-PCK-009
- **Decision:** UV 11, 16, 17
- **Test:** `tests/test_uv_pack.py::test_directions`
- **Code:** `uv_marks.py`

### DAT-028: Skip Auto Seam mark `fss_uv_skip_autoseam`

- **Status:** implemented
- **Requirement:** Custom bool property on an object: True skips it, False clears an inherited skip. Missing means
  inherited from the nearest marked ancestor, else processed.
- **Used by:** UV-SEAM-007
- **Decision:** UV 56
- **Test:** `tests/uv_prototype/test_uv_heatmap.py::test_skip_auto_seam_mark`,
  `tests/uv_prototype/test_autoseam_operators.py::test_gathering_and_skipped`
- **Code:** `uv_marks.py`

## Material Data

### DAT-024: `Material.fss_uv_keep_uvs`

- **Status:** implemented
- **Requirement:** Registered bool, default off: the texture set of this material keeps its UVs (UV-PCK-011).
- **Decision:** UV 116
- **Test:** `tests/test_uv_pack.py::test_check_all_and_keep`
- **Code:** `uv_marks.py`

### DAT-025: `Material.fss_uv_texture_size`

- **Status:** implemented
- **Requirement:** Registered enum: the side of the square texture set in pixels, 256, 512, 1024, 2048, 4096 or
  8192, default 4096.
- **Used by:** UV-PCK-005, GEN-011
- **Decision:** UV 110, 120
- **Test:** `tests/test_uv_pack.py::test_square_size_migration`
- **Code:** `uv_marks.py`

### DAT-026: `Material.fss_uv_margin_px`

- **Status:** implemented
- **Requirement:** Registered integer, pixels of the texture set, minimum 0, default 8.
- **Used by:** UV-PCK-007
- **Decision:** UV 105
- **Test:** `tests/test_uv_pack.py::test_panel_rows`
- **Code:** `uv_marks.py`

## Mesh and Window Data

### DAT-029: Edge attribute `fss_auto_seam`

- **Status:** implemented
- **Requirement:** Boolean edge attribute on a mesh: the proposed seams of Auto Seam (true on an edge that is
  proposed and not accepted). Accept moves them into Blender's seams and removes the attribute's marks; Discard
  removes them. Other edges' seams are the current seams.
- **Used by:** UV-SEAM-001 to UV-SEAM-003
- **Decision:** UV 64
- **Test:** `tests/uv_prototype/test_autoseam_operators.py::test_second_propose_replaces_only_auto_seams`
- **Code:** `uv_autoseam.py`

### DAT-030: Face attribute `_fss_orig_face_idx`

- **Status:** implemented
- **Requirement:** Temporary integer face attribute that Visibility Scoring adds to map evaluated faces (Mirror,
  Array) back to the original mesh; removed when the run ends, is cancelled or fails.
- **Used by:** UV-VIS-005
- **Decision:** UV 68 (mapping kept; the pass structure replaced by UV 86)
- **Test:** `tests/uv_prototype/test_visibility.py::test_scene_unchanged_after_run_and_esc`
- **Code:** `visibility_core.py`

### DAT-031: Active texture set

- **Status:** implemented
- **Requirement:** `WindowManager.fss_uv_pack_active_name` (string) holds the name of the texture set row the
  artist clicked; `fss_uv_pack_active` (integer) reads and writes it as the list index. Not saved with the file.
- **Used by:** UV-PCK-002
- **Decision:** UV 121
- **Test:** `tests/test_uv_pack.py::test_texture_set_list`
- **Code:** `uv_marks.py`

### DAT-032: Migration of older files

- **Status:** implemented
- **Requirement:** When a file is opened, appended, or the add-on is registered, older data is converted once and
  the old key removed:
  - `fss_uv_density` (custom [min, max], before 0.31.0) becomes the own density mark;
  - `fss_zone_density` (registered zone multiplier, before 0.31.0) becomes the zone empty's own density mark;
  - `fss_uv_margin` (fraction of the UV square) becomes `fss_uv_margin_px` at 4096 px (0.002 = 8 px);
  - `fss_uv_texture_width` / `_height` (before 0.33.0) become `fss_uv_texture_size` = the larger of the two.
  Linked (library) data is not changed.
- **Decision:** UV 105, 108, 120
- **Test:** `tests/test_density_marks.py::test_migration`,
  `tests/test_density_marks.py::test_migration_at_load_and_register`,
  `tests/test_uv_pack.py::test_square_size_migration`
- **Code:** `uv_marks.py`

## Name Markers

### DAT-033: Markers in object names

- **Status:** implemented
- **Requirement:** Object names may start with these markers:

  | Marker | Meaning | Exported as |
  | :--- | :--- | :--- |
  | `@ZONE_<NAME>` | zone empty (ZON-001) | `ZONE_<NAME>` |
  | `@MERGE_<name>` | merge group root (MRG-001) | `<name>` |
  | `@NOMERGE_<name>` | kept out of its group (MRG-004) | `<name>` |
  | `@<other>` | any other leading `@` | `<other>` |

  `@` has no meaning in Blender, glTF, the model XML or `.cfg` files. A name that is only `@` characters is
  exported unchanged.
- **Decision:** TM S2.1; UV 28, 87
- **Test:** `tests/test_markers.py::test_strip_markers`
- **Code:** `merge.py` (`strip_markers`)

## Files and Text Blocks

### DAT-036: The `.visibility` file

- **Status:** implemented
- **Requirement:**
  - Location and name: beside the `.blend`, `<blend name>.visibility`; written only for a saved `.blend`, and
    not written when a run is cancelled.
  - Format: a NumPy `.npz` archive (compressed), schema version 4. Key `_meta_json` holds one JSON string with
    `schema_version`, the run's settings and views, totals and summaries, and `mesh_face_counts` (mesh name to
    face count). Per mesh (name with `/` and `\` replaced by `_`): `<mesh>__vis_omega` and
    `<mesh>__unocc_omega` (float32 per face: visible and unoccluded solid angle sums), `<mesh>__face_scores`
    (float32, 0 to 1), `<mesh>__face_undetermined` and `<mesh>__face_never_seen` (bool),
    `<mesh>__face_patch_size_px` (float32). Per object with an evaluated face map: `eval_map__<object>` (int32).
  - Staleness: a mesh is stale when it is missing from the scene or its face count differs from
    `mesh_face_counts`. Stale and missing data count as visibility 1.0 (UV-VIS-008).
- **Used by:** UV-VIS-004, UV-VIS-008, UV-DEN-004, GEN-005
- **Decision:** UV 67, 78, 97
- **Test:** `tests/uv_prototype/test_visibility.py::test_operator_on_saved_scene`,
  `tests/uv_prototype/test_visibility.py::test_packer_interface_and_cache`
- **Code:** `visibility_core.py` (`save_visibility_file`, `load_visibility_file`)
- **Notes:** the file holds per-mesh data by mesh name; renaming a mesh makes its data stale.

### DAT-037: Report text blocks

- **Status:** implemented
- **Requirement:** Tools write their report into a Blender text block, replacing its content on every run:
  **FSS Auto Seam Report** (Propose Seams), **FSS Visibility Report** (Update Visibility), **FSS Packing Report**
  (Pack and Check All). Reports are saved with the `.blend` like any text block and never exported.
- **Used by:** UV-SEAM-005, UV-VIS-006, UV-PCK-012
- **Decision:** UV 115 (Packing Report); none recorded for the others
- **Test:** `tests/test_uv_pack.py::test_report_order`,
  `tests/uv_prototype/test_autoseam_operators.py::test_shared_mesh_and_report`

## Export-Time Data

### DAT-038: Export copies

- **Status:** implemented
- **Requirement:** In the MSFS 2024 multi-exporter, the duplicates carry the custom property
  `msfs_original_name` (written as the glTF node name) and export copies of materials carry
  `msfs_original_data` (the artist's material). fss_blender_tools reads names through them (MRG, LOD).
- **Decision:** Asobo design; AGENTS.md, How Export Works
- **Test:** harness: `tests/run_tests.py --sim 2024` (node names)
- **Code:** `io_scene_gltf2_msfs_fss/io/exp/multi_export.py`, `fss_blender_tools/merge.py`

### DAT-039: LOD padding object

- **Status:** implemented
- **Requirement:** When the LOD sphere is padded (LOD-017), the export adds one object, mesh and material named
  `FSS_LOD_PADDING`: eight triangles of 1 mm legs at the corners of the padding box, material invisible, no
  collision. It exists only in the export; the `.blend` never contains it.
- **Decision:** LOD 30, 31
- **Test:** no test
- **Code:** `lod_model.py`

## What Reaches the glTF

### DAT-040: No FSS tool data in the glTF

- **Status:** implemented
- **Requirement:** With Include Extras on or off, no key starting with `fss_` appears in the extras of a glTF
  node, mesh, material or scene. Other custom properties of the artist stay. Edge and face attributes of FSS
  tools (`fss_auto_seam`, `_fss_orig_face_idx`) do not change the exported geometry.
- **Decision:** TM S8.5; UV 87; AGENTS.md, Pitfalls (registered properties reach extras)
- **Test:** `tests/test_zone_tree.py::test_gltf_leak`, `tests/uv_prototype/test_visibility.py::test_gltf_leak_check`,
  `tests/uv_prototype/test_uv_heatmap.py::test_gltf_export_unchanged`,
  `tests/uv_prototype/test_autoseam_operators.py::test_export_check`
- **Code:** `merge.py` (`_strip_fss_extras`, glTF hooks)

### DAT-041: Exporter properties in extras

- **Status:** wish
- **Requirement:** The exporter's own data (`msfs_fss_export_target`, `msfs_fss_export_only`,
  `msfs_fss_msfs2020_emissive_reference`, the mesh custom properties `msfs_fss_legacy_auto_smooth` and
  `msfs_fss_legacy_normals_restored`) does not reach glTF extras either.
- **Decision:** none recorded
- **Test:** no test
- **Notes:** found while drafting (20261028): `_strip_fss_extras` drops keys starting with `fss_` only; whether
  these properties appear in a glTF exported with Include Extras is not checked. FSS deploys' extras setting
  decides whether it matters.

### DAT-042: Node and mesh names

- **Status:** implemented
- **Requirement:** Every exported node and mesh name is stripped of its leading markers (DAT-033), in the plain
  glTF exporter and in the multi-exporter, for merged and unmerged roots and for `@NOMERGE_` nodes. In the
  multi-exporter the name comes from `msfs_original_name`, in the plain exporter from the object name.
- **Decision:** TM S2.1, TM S3 "`@NOMERGE_<name>`"; UV 87
- **Test:** `tests/test_markers.py::test_export_hooks`
- **Code:** `merge.py` (`gather_node_hook`, `gather_mesh_hook`)

### DAT-043: Merged meshes

- **Status:** implemented
- **Requirement:** A merge group exports as one node `<name>` with one mesh; its transparent part (MSFS alpha mode
  Blend) as a child node `<name>_TRANSPARENT`. Objects the merge removes but that hold kept-separate children are
  replaced by empties of the same name and world transform.
- **Used by:** MRG-001, MRG-005, MRG-006
- **Decision:** TM S1.3, TM S2.2, TM S7
- **Test:** `tests/verify_lod_exports.py` (the `Panel` node only; cannot be re-run as it stands, see
  [README.md](README.md#test-references))
- **Notes:** NOT TESTED: `_TRANSPARENT` and the replacement empties.

### DAT-044: Animation names

- **Status:** implemented
- **Requirement:** Animation (action) names are exported as authored; markers in them are not stripped, because
  the model XML refers to animations by name.
- **Decision:** TM S1 Known Issues (accepted behaviour)
- **Test:** no test
- **Notes:** an action named after a `@MERGE_` root (for example `@MERGE_ANIMAction`) keeps the marker in the
  glTF; name such actions without it.

### DAT-045: LOD file names

- **Status:** implemented
- **Requirement:** A LOD deploy writes `<name>_LOD00.gltf` to at most `<name>_LOD06.gltf`, two digits, `_LOD00`
  the full model; the deploy base name has no `-LOD00` suffix.
- **Decision:** LOD 4, 9, 16, 17
- **Test:** `tests/verify_lod_exports.py` (cannot be re-run as it stands)
- **Code:** `lod_model.py`; the LOD deploy script of the aircraft repository

## Exporter Data

### DAT-046: Exporter properties and preferences

- **Status:** implemented
- **Requirement:**

  | Data | Type, default | Used by |
  | :--- | :--- | :--- |
  | `Scene.msfs_fss_export_target` | enum MSFS 2024 / MSFS 2020, default MSFS 2024 | EXP-001 |
  | `Object.msfs_fss_export_only` | enum ALL / MSFS 2024 / MSFS 2020, default ALL (Export For) | EXP-005 |
  | `Scene.msfs_fss_msfs2020_emissive_reference` | float cd/m², set only on scenes with converted materials | EXP-004 |
  | mesh custom property `msfs_fss_legacy_auto_smooth` | 0 / 1, Auto Smooth as saved by Blender 4.0 or older | EXP-007 |
  | mesh custom property `msfs_fss_legacy_normals_restored` | set after Restore Blender 3.6 Normals | EXP-007 |
  | preference `show_asobo_export_workflow` | bool, default off | EXP-010 |
  | preference MSFS 2020 Emissive Reference | float cd/m² | EXP-004 |

  The MSFS 2024 and MSFS 2020 material and object properties are Asobo's; the 26 MSFS 2020-only properties are
  registered next to them.
- **Decision:** CONV S4 (design 1, 2, 5); CONV S6.4; LOD 20
- **Test:** harness: `tests/run_tests.py --sim 2024` and `--sim 2020` (the target is set per run)
- **Code:** `io_scene_gltf2_msfs_fss/msfs2020_target.py`, `legacy_normals.py`, `fss_workflow_ui.py`
