# UV

[Specification](README.md) / **uv.md**

Seams, unwrap, Visibility Scoring, density and packing. They are separate phases and separate tools: each runs on
its own and can be repeated, none requires another to have run (UV 7, 42). Artist guide:
[../user/uv.md](../user/uv.md), [../user/visibility.md](../user/visibility.md),
[../user/fss-tools.md](../user/fss-tools.md#uv-tools). Current design: UV journal Session 102.

## Seams (Auto Seam)

### UV-SEAM-001: Propose Seams

- **Status:** implemented
- **Requirement:** Propose Seams adds proposed seams (DAT-029) to the selected mesh objects, one mesh at a time, with
  the C1 algorithm:
  - the artist's current seams are kept and act as forced cuts; marked sharp edges are not seams;
  - internal triangle diagonals of quads and n-gons are never cut;
  - a chart is accepted only when an Angle Based unwrap of it keeps its area distortion within the Distortion Limit
    (UV-SEAM-004); shape fidelity comes before island count;
  - a new proposal replaces only the earlier proposed seams;
  - no UV map is changed.
  Seams are placed on the base mesh, before Mirror and Array modifiers.
- **Data:** DAT-029
- **Decision:** UV 2, 5, 35, 40, 43, 45, 48, 49, 64
- **Test:** `tests/uv_prototype/test_autoseam_operators.py::test_artist_seams_preservation`,
  `tests/uv_prototype/test_autoseam_operators.py::test_second_propose_replaces_only_auto_seams`,
  `tests/uv_prototype/test_autoseam_operators.py::test_uv_maps_unchanged_after_propose`; core rules: manual, UV
  journal Sessions 39 to 47 (`tests/uv_prototype/parity_autoseam_core.py`, `measure_autoseam_real.py`)
- **Code:** `uv_autoseam.py`, `uv_autoseam_core.py`
- **Notes:** NOT TESTED in a unit suite: the no-diagonal rule and the chart acceptance.

### UV-SEAM-002: Accept, Discard, Clear, Select

- **Status:** implemented
- **Requirement:** Accept Proposed makes the proposed seams current seams; Discard Proposed removes them; Clear Current
  (with confirmation) removes the current seams and keeps the proposed ones; Select Proposed and Select Current select
  those edges of the active mesh in Edit Mode. Accept, Discard and Clear act on whole objects, also from Edit Mode;
  each is one undo step. The panel shows the active object's counts ("Proposed: n | Current: m").
- **Data:** DAT-029
- **Decision:** UV 64, 65
- **Test:** `tests/uv_prototype/test_autoseam_operators.py::test_keep_as_artist_seams`,
  `tests/uv_prototype/test_autoseam_operators.py::test_keep_and_clear_from_edit_mode`,
  `tests/uv_prototype/test_autoseam_operators.py::test_select_operators_in_edit_mode`
- **Code:** `uv_autoseam.py`

### UV-SEAM-003: Accept + Unwrap

- **Status:** implemented
- **Requirement:** Accept + Unwrap (with confirmation, it replaces UVs) accepts the proposed seams and unwraps the
  selected objects with Blender's Angle Based method. Faces with decal, glass, windshield, invisible or occluder
  materials (UV-SEAM-008) keep their UVs. Objects with non-uniform scale are named in a warning. The mode is restored.
- **Decision:** UV 90, 91
- **Test:** `tests/uv_prototype/test_autoseam_operators.py::test_accept_and_unwrap`
- **Code:** `uv_autoseam.py`

### UV-SEAM-004: Distortion Limit

- **Status:** implemented
- **Requirement:** A scene setting (DAT-006), 1.05 to 2.0 (slider 1.05 to 1.75), default 1.25, saved with the file:
  the largest average area distortion per island that a proposal accepts (the Area half of the Heatmap's Distortion
  mode, GEN-006); shear is not limited by it. It applies to the next Propose Seams; the report states the limit used.
- **Data:** DAT-006
- **Decision:** UV 88 (amends 45)
- **Test:** `tests/uv_prototype/test_autoseam_operators.py::test_distortion_limit`
- **Code:** `uv_autoseam.py`, `uv_autoseam_core.py`
- **Notes:** only 1.10 to 1.60 has been measured (UV journal Sessions 87 to 89).

### UV-SEAM-005: Auto Seam report

- **Status:** implemented
- **Requirement:** Each run writes the text block FSS Auto Seam Report (DAT-037): totals, run time, the limit used,
  meshes needing attention first, then clean meshes; repeated problems on one mesh grouped into one line with count,
  largest island and worst value (islands too stretched, faces too distorted to flatten, zero-area face groups, charts
  too distorted, islands with overlapping triangles, ignored sliver overlaps, shared meshes with differing scales).
  The panel shows the totals.
- **Data:** DAT-037
- **Decision:** UV 51, 54
- **Test:** `tests/uv_prototype/test_autoseam_operators.py::test_report_attention_counts`,
  `tests/uv_prototype/test_autoseam_operators.py::test_shared_mesh_and_report`
- **Code:** `uv_autoseam.py`

### UV-SEAM-006: Progress and buttons

- **Status:** implemented
- **Requirement:** Propose Seams and Accept + Unwrap run modally, one mesh at a time; while they run a progress bar
  (mesh n of m, name, stage inside the mesh, face count) replaces the buttons and the slider, and the status bar shows
  the same. Cancel or Esc stops after the mesh in work; finished meshes keep their proposal. A run over several
  objects is one undo step. In Object Mode only buttons that can act are shown (Accept, Accept + Unwrap, Discard with
  proposed seams; Clear Current with current seams); in Edit Mode all.
- **Decision:** UV 44, 53, 92, 93, 94
- **Test:** `tests/uv_prototype/test_autoseam_operators.py::test_progress_and_buttons`,
  `tests/uv_prototype/test_autoseam_operators.py::test_state_restoration`
- **Code:** `uv_autoseam.py`

### UV-SEAM-007: Skip Auto Seam mark

- **Status:** implemented
- **Requirement:** Skip Auto Seam and Clear set and clear the mark (DAT-028) on the selected objects; children inherit
  it unless cleared or marked themselves. Marked objects are skipped by Propose Seams and listed as skipped. The panel
  shows whether the active object is processed or skipped and where that comes from (own mark, from an ancestor,
  default).
- **Data:** DAT-028
- **Decision:** UV 56
- **Test:** `tests/uv_prototype/test_autoseam_operators.py::test_gathering_and_skipped`,
  `tests/uv_prototype/test_uv_heatmap.py::test_skip_auto_seam_mark`
- **Code:** `uv_marks.py`, `uv_autoseam.py`

### UV-SEAM-008: Skip by material class

- **Status:** implemented
- **Requirement:** An object whose materials are all of the classes decal, glass, windshield, invisible or occluder
  is skipped, with that reason. A material belongs to them by its name class (`DECAL`, `DECAL_EM`, `DECAL_FROST`,
  `DECAL_BLEND`, `GLASS`, `WNDSHIELD`, `INVIS`, `OCCLUDER`) or by its MSFS decal material type. Objects with mixed
  materials are processed. Other skip reasons listed: not a mesh, not editable, no faces, no free UV map slot.
- **Decision:** UV 55; UV 30 (class names); exception to UV 100 (P-3)
- **Test:** `tests/uv_prototype/test_autoseam_operators.py::test_decal_skip`,
  `tests/uv_prototype/test_autoseam_operators.py::test_gathering_and_skipped`
- **Code:** `uv_autoseam.py` (`SKIP_MATERIAL_CLASSES`)

### UV-SEAM-009: Shared meshes and slivers

- **Status:** implemented
- **Requirement:** A mesh shared by several objects is processed once; the report warns when its users have differing
  or non-uniform scales. Overlaps between two triangles that both have a 3D area below 1e-8 m² are ignored and
  counted.
- **Decision:** UV 3, 52
- **Test:** `tests/uv_prototype/test_autoseam_operators.py::test_shared_mesh_and_report`,
  `tests/uv_prototype/test_autoseam_operators.py::test_overlap_check_collapsed_unwrap`
- **Code:** `uv_autoseam.py`, `uv_autoseam_core.py`

## Unwrap

### UV-UNW-001: Unwrap with Angle Based

- **Status:** implemented
- **Requirement:** The unwrap for Auto Seam's seams is Blender's Angle Based unwrap, run by Accept + Unwrap
  (UV-SEAM-003) or by the artist (UV > Unwrap). fss_blender_tools has no unwrapper of its own; Minimum Stretch is not
  used for hard-surface parts.
- **Decision:** UV 36, 37, 90, 91
- **Test:** `tests/uv_prototype/test_autoseam_operators.py::test_accept_and_unwrap`
- **Code:** `uv_autoseam.py`

## Visibility Scoring

### UV-VIS-001: Artist cameras

- **Status:** implemented
- **Requirement:** Visibility is analysed only from cameras the artist has placed and included (DAT-005). The camera
  list follows the scene's cameras (renames and deletions). Per camera: Look Around (a full cube map around the camera
  position, weighted by the angle from its forward direction) or Fixed View (the camera's own frustum at its focal
  length and sensor aspect, 2560 × 1440, full weight).
- **Data:** DAT-005
- **Decision:** UV 18 (replaced by 80), 73, 80, 83
- **Test:** `tests/uv_prototype/test_visibility.py::test_camera_renaming_and_deletion`,
  `tests/uv_prototype/test_visibility.py::test_camera_sync_after_draw`
- **Code:** `visibility.py`

### UV-VIS-002: Animation steps

- **Status:** implemented
- **Requirement:** The scene is evaluated at Animation Steps (2 to 10, default 5) states, evenly spaced over each
  action's (and NLA track's) own length: 2 gives 0 and 100 %, 3 gives 0, 50 and 100 %, 5 gives quarters.
- **Data:** DAT-005
- **Decision:** UV 86 (replaces 21, 69)
- **Test:** `tests/uv_prototype/test_visibility.py::test_synthetic_15_cases`
- **Code:** `visibility_core.py`

### UV-VIS-003: Visibility score

- **Status:** implemented
- **Requirement:** Per face, the visible and unoccluded solid angle is summed over cameras and states (DAT-036). The
  score is a factor from 0 to 1, independent of distance and size. The direction weight is 1 in the camera's forward
  direction, falling with the cosine of the angle to the power Falloff (default 1.0), never below Direction Floor
  (default 0.2). A face's score comes from geometric patches of at least Pixel Threshold reference pixels (default
  10); pieces too small are undetermined and take their score from the hierarchy. A face set's value (an island, an
  object) is computed from the sums over its seen faces (`visibility_core.score_face_set`).
- **Data:** DAT-005, DAT-036
- **Decision:** UV 72, 73, 78, 79, 82, 95
- **Test:** `tests/uv_prototype/test_visibility.py::test_synthetic_15_cases`,
  `tests/uv_prototype/test_visibility.py::test_packer_interface_and_cache`
- **Code:** `visibility_core.py`

### UV-VIS-004: Update Visibility

- **Status:** implemented
- **Requirement:** Update Visibility is available only for a saved `.blend` with at least one included camera; it
  writes `<blend name>.visibility` beside it (DAT-036). In an interactive Blender it runs modally with progress in the
  status bar; Esc cancels and writes nothing. The scene (frame, actions, NLA tracks, temporary attributes) is restored
  exactly after a run, a cancel or an error.
- **Data:** DAT-030, DAT-036
- **Decision:** UV 67
- **Test:** `tests/uv_prototype/test_visibility.py::test_operator_on_saved_scene`,
  `tests/uv_prototype/test_visibility.py::test_scene_unchanged_after_run_and_esc`,
  `tests/uv_prototype/test_visibility.py::test_disabled_states`
- **Code:** `visibility.py`

### UV-VIS-005: Modifiers and instances

- **Status:** implemented
- **Requirement:** Evaluated geometry (Mirror, Array) is analysed and mapped back to the original mesh's faces, and
  every object using a shared mesh is analysed; the result is stored once per original mesh face (DAT-036), because
  all instances share the texture. A group keeps the maximum over views and instances.
- **Data:** DAT-030
- **Decision:** UV 68 (mapping), UV 78 (instances)
- **Test:** `tests/uv_prototype/test_visibility.py::test_heatmap_modifier_face_mapping`
- **Code:** `visibility_core.py`
- **Notes:** NOT VERIFIED while drafting: that the code combines instances as the maximum (UV 78); the face mapping
  is tested.

### UV-VIS-006: Visibility report and panel

- **Status:** implemented
- **Requirement:** After a run the panel shows the file's time, cameras and step count, the surface totals, the
  never-seen objects and islands (Select Never Seen), the undetermined objects, and stale meshes (Select Stale); the
  full report goes to the text block FSS Visibility Report (DAT-037). Never-seen faces are not candidates for
  deletion; nothing is deleted.
- **Data:** DAT-036, DAT-037
- **Decision:** UV 74 (replaces 20), UV 83
- **Test:** `tests/uv_prototype/test_visibility.py::test_operator_on_saved_scene`
- **Code:** `visibility.py`

### UV-VIS-007: Material classes in the analysis

- **Status:** implemented
- **Requirement:** Objects with invisible, collision or occluder materials neither hide other faces nor are scored.
- **Decision:** UV 77; exception to UV 100 (P-3)
- **Test:** `tests/uv_prototype/test_visibility.py::test_synthetic_15_cases`
- **Code:** `visibility_core.py` (`is_invisible_object`)

### UV-VIS-008: Missing or stale data

- **Status:** implemented
- **Requirement:** An object without data in the `.visibility` file, or whose mesh is stale (DAT-036), counts as
  visibility 1.0 for density; the panels say "no data".
- **Data:** DAT-036
- **Decision:** UV 97
- **Test:** `tests/uv_prototype/test_visibility.py::test_packer_interface_and_cache`
- **Code:** `visibility_core.py`, `uv_marks.py`

### UV-VIS-010: Exterior camera set

- **Status:** wish
- **Requirement:** A camera set for exterior models (the artist's own exterior views) with which Visibility Scoring of
  an exterior is tried and tuned.
- **Decision:** UV 80 (any artist camera, implemented); the exterior set itself is not decided
- **Test:** no test
- **Notes:** Visibility Scoring was never run on an exterior model (UV journal Session 102, open item 5).

## Density

### UV-DEN-001: Target density

- **Status:** implemented
- **Requirement:** One target texel density per scene, in pixels per centimetre, default 20.48 (2048 px per metre):
  the density at factor 1.0.
- **Data:** DAT-006
- **Decision:** UV 106
- **Test:** `tests/test_density_marks.py::test_defaults`
- **Code:** `uv_marks.py`

### UV-DEN-002: Scene density freedom

- **Status:** implemented
- **Requirement:** Density freedom Min and Max (default 0.9 and 1.1, kept in order) is how far the packer may scale any
  island down or up; it applies once, at the top of the hierarchy.
- **Data:** DAT-006
- **Decision:** UV 108 (the range freedom of UV 85)
- **Test:** `tests/test_density_marks.py::test_defaults`, `tests/test_density_marks.py::test_multiplication`
- **Code:** `uv_marks.py`

### UV-DEN-003: Density marks multiply

- **Status:** implemented
- **Requirement:** An object's density range is the scene freedom × every density mark (DAT-023) from the root down to
  the object itself, zone empties included; a mark that is off counts as x1.0. Lower (x0.75), Higher (x1.5) and Clear
  act on all selected objects; Alt + drag or type sets a field on all selected objects.
- **Data:** DAT-023
- **Decision:** UV 16, 108 (replaces 4, 12, 14, 75, 76, 85)
- **Test:** `tests/test_density_marks.py::test_multiplication`, `tests/test_density_marks.py::test_presets_and_clear`
- **Code:** `uv_marks.py`

### UV-DEN-004: Island density range

- **Status:** implemented
- **Requirement:** An island's density range is target density × the object's density range × the island's
  visibility value (UV-VIS-003), where visibility is never below 0.1 (also for never-seen islands) and is 1.0 without
  data (UV-VIS-008). Islands scale continuously inside their range; there are no tiers.
- **Data:** DAT-023, DAT-036
- **Decision:** UV 74, 81, 108, 111, 113
- **Test:** `tests/test_density_marks.py::test_visibility_floor`, `tests/test_uv_pack.py::test_exact_density`
- **Code:** `uv_marks.py`, `uv_pack.py`

### UV-DEN-005: The density chain in the panel

- **Status:** implemented
- **Requirement:** The Packing section shows for the active object, live: Parent (the factor range of everything above
  it and the nearest marked parent, or the scene freedom), Zone (the zone and its factor, already part of Parent),
  Visibility (object score and island range; "no data: x1.00", "never seen: x0.10"; Object Mode), its own Density mark
  (tick, Min, Max, greyed while off), and Result (the px/cm range: target × parent × own mark × visibility, with the
  range over its islands). The Heatmap's Density mode follows a mark change shortly after dragging stops.
- **Data:** DAT-023, DAT-036
- **Decision:** UV 109 (amended by 121)
- **Test:** `tests/test_density_marks.py::test_panel`, `tests/test_density_marks.py::test_panel_visibility`,
  `tests/test_density_marks.py::test_heatmap_after_mark_change`
- **Code:** `uv_marks.py`
- **Notes:** never checked in an interactive Blender: the live update while dragging and Alt + drag (UV journal
  Session 102, open item 3).

## Packing

### UV-PCK-001: Per texture set

- **Status:** implemented
- **Requirement:** A texture set is one material with all its faces in the view layer, also on objects that are not
  selected or are hidden; every face that has a UV map is packed, whatever the material's type or textures. A mesh
  used by several objects is packed once.
- **Decision:** UV 8, 100, 114 (replace 96)
- **Test:** `tests/test_uv_pack.py::test_linked_and_split`, `tests/test_uv_pack.py::test_pack_operator_and_undo`
- **Code:** `uv_pack.py`

### UV-PCK-002: Texture set list

- **Status:** implemented
- **Requirement:** The Packing section lists every material of the selected objects, the active object's first, in a
  scrollable list (5 rows, resizable, filterable by name), each row with its last result (UV-PCK-015), a lock for Keep
  UVs, and a warning sign when its last run found faces without area or triangles without UV area. Below it the
  clicked row's box (before a click, the first row): Size, Margin, Keep UVs, Pack, Last run. With nothing selected the
  section says so.
- **Data:** DAT-031
- **Decision:** UV 114, 121
- **Test:** `tests/test_uv_pack.py::test_texture_set_list`, `tests/test_uv_pack.py::test_panel_rows`
- **Code:** `uv_marks.py`
- **Notes:** never checked in an interactive Blender (UV journal Session 102, open item 3).

### UV-PCK-003: Pack

- **Status:** implemented
- **Requirement:** Pack replaces the UVs of every face of the texture set (UV-PCK-001) by the packed layout, in Object
  or Edit Mode; the selection, the mode and the active UV map stay as they were; Ctrl + Z undoes it. It is unavailable
  for a Keep UVs set. Blender waits while a set packs; the section and the status bar show the step.
- **Decision:** UV 109, 114
- **Test:** `tests/test_uv_pack.py::test_pack_operator_and_undo`, `tests/test_uv_pack.py::test_edit_mode`
- **Code:** `uv_pack.py`

### UV-PCK-004: Density first, one common position

- **Status:** implemented
- **Requirement:** Every island is scaled to a density inside its range (UV-DEN-004), always. All islands of a set take
  one common position t inside their ranges: the top (t = 1) when they fit with space left (underflow), the highest t
  that still fits, or the bottom (t = 0) when they do not fit even there (overflow). No island's density lies outside
  its range beyond the test tolerance.
- **Decision:** UV 112, 113 (replace 10, 13)
- **Test:** `tests/test_uv_pack.py::test_exact_density`, `tests/test_uv_pack.py::test_fit`,
  `tests/test_uv_pack.py::test_underflow_and_sizes`, `tests/test_uv_pack.py::test_overflow_and_clamp`
- **Code:** `uv_pack.py`

### UV-PCK-005: Square size, spill and needed size

- **Status:** implemented
- **Requirement:** Each set has a square size, 256 to 8192 px per side (DAT-025), chosen by the artist. When the
  islands do not fit at their density they are still written at their density: the layout reaches beyond the texture
  from the corner at the UV origin, and the result names the smallest power-of-two size that holds them, or that none
  up to 8192 does. When a smaller size would hold them, the result says so. Results: "fits n %", ", s × s would do",
  "needs xk: s × s", "does not fit even at 8192 (xk)", "kept".
- **Data:** DAT-025
- **Decision:** UV 9, 110, 112, 120 (replace 15, 31)
- **Test:** `tests/test_uv_pack.py::test_underflow_and_sizes`, `tests/test_uv_pack.py::test_overflow_and_clamp`
- **Code:** `uv_pack.py`

### UV-PCK-006: Packing engine

- **Status:** implemented
- **Requirement:** Islands are placed by Blender's Pack Islands with our scaling (scale off, our densities applied
  first); an island whose outline Blender cannot handle is packed by its bounding box, and the report counts those.
- **Decision:** UV 107
- **Test:** `tests/test_uv_pack.py::test_fit`, `tests/test_uv_pack.py::test_zero_area_and_spike`
- **Code:** `uv_pack.py`

### UV-PCK-007: Margin in pixels

- **Status:** implemented
- **Requirement:** Each set has a margin in pixels of its texture (DAT-026, default 8). Every island keeps the margin
  on every side, so two islands are at least twice the margin apart, and no triangles of different islands overlap.
  Below 4 px the box warns that compressed blocks bleed across islands.
- **Data:** DAT-026
- **Decision:** UV 105
- **Test:** `tests/test_uv_pack.py::test_fit` and the other packer tests (helper `ok`: 0 margin violations,
  0 overlaps)
- **Code:** `uv_pack.py` (`layout_metrics`)
- **Notes:** NOT TESTED: the two-margin gap. `layout_metrics` counts a violation only when a gap is below one margin,
  so a layout with gaps between one and two margins passes. The report's "smallest gap" shows the actual value.

### UV-PCK-008: Check All

- **Status:** implemented
- **Requirement:** Check All measures every texture set of the view layer as Pack would, writes no UVs, and fills each
  set's Last run (marked "(checked)"); Keep UVs sets are listed as kept. While it runs a progress bar replaces the
  section's fields; Cancel or Esc stops after the set in work.
- **Decision:** UV 115
- **Test:** `tests/test_uv_pack.py::test_check_all_and_keep`
- **Code:** `uv_pack.py`, `uv_marks.py`
- **Notes:** the progress bar and Cancel were never checked in an interactive Blender (UV journal Session 102, open
  item 3).

### UV-PCK-009: Direction marks

- **Status:** implemented
- **Requirement:** Free, Upright, Flip, Quarter and Clear set or clear the direction mark (DAT-027) on the selected
  objects; the panel highlights the active object's direction and names the parent it comes from. Upright and Flip
  islands keep their rotation; a set with a Quarter island turns its islands in 90-degree steps only; otherwise
  islands rotate freely.
- **Data:** DAT-027
- **Decision:** UV 11, 16, 17
- **Test:** `tests/test_uv_pack.py::test_directions`
- **Code:** `uv_marks.py`, `uv_pack.py`

### UV-PCK-010: Stacking

- **Status:** implemented
- **Requirement:** Islands share texture space only from explicit signals: objects sharing one mesh share its UVs
  (packed once); Mirror and Array copies share UVs by construction.
- **Decision:** UV 3
- **Test:** `tests/test_uv_pack.py::test_linked_and_split`
- **Code:** `uv_pack.py`

### UV-PCK-011: Keep UVs per texture set

- **Status:** implemented
- **Requirement:** A material can be marked Keep UVs. Pack is unavailable for its texture set and writes no UVs on its
  faces; Check All measures nothing for it and reports it as "kept". No material type decides this: only the mark
  does.
- **Data:** DAT-024
- **Decision:** UV 116 (rests on UV 100)
- **Test:** `tests/test_uv_pack.py::test_check_all_and_keep`
- **Code:** `uv_pack.py`, `uv_marks.py`
- **Notes:** never checked in an interactive Blender (UV journal Session 102, open item 3).

### UV-PCK-012: Packing Report

- **Status:** implemented
- **Requirement:** Pack and Check All write the text block FSS Packing Report (DAT-037), per set: the result, the mode
  (fit, underflow, overflow), t and k (the layout's size against the texture's); the needed size and the fill of the
  needed and current size; the smallest gap, margin violations and overlapping triangles, and how far any island's
  density lies outside its range; the number of islands and those packed by their bounding box; islands kept
  unchanged and islands not checked for density; a warning for objects with faces without area; a warning for islands
  with triangles without UV area, with their objects ordered by the layout pixels their island spans, largest first;
  after Pack, the objects included but not selected; the time.
- **Data:** DAT-037
- **Decision:** UV 115, 117, 118
- **Test:** `tests/test_uv_pack.py::test_report_order`, `tests/test_uv_pack.py::test_faces_without_area`,
  `tests/test_uv_pack.py::test_faces_without_uv_area`
- **Code:** `uv_pack.py`

### UV-PCK-013: Islands without UV area

- **Status:** implemented
- **Requirement:** Islands without UV area (a line or a point in the UVs) keep their UVs and are listed. Islands with a
  needle (a triangle with area on the model and none in the UVs, GEN-011) are still packed and reported; they are not
  checked for density.
- **Decision:** UV 117, 118
- **Test:** `tests/test_uv_pack.py::test_zero_area_and_spike`, `tests/test_uv_pack.py::test_faces_without_uv_area`
- **Code:** `uv_pack.py`

### UV-PCK-014: Packing in the UV Editor

- **Status:** implemented
- **Requirement:** The UV Editor's sidebar has an FSS MSFS Tools tab with the same Packing section, without Visibility
  Scoring; it shows in the UV Editor only, not in the Image Editor's image view.
- **Decision:** UV 99, 119 (replace 104); MAT 15 (tab)
- **Test:** `tests/test_uv_pack.py::test_uv_editor_panel`, `tests/test_panels.py::test_layout`
- **Code:** `uv_marks.py`
- **Notes:** never checked in an interactive Blender (UV journal Session 102, open item 3).

### UV-PCK-015: Last run

- **Status:** implemented
- **Requirement:** Each set's Last run shows the result of its last Pack or Check All in this Blender session; it is
  not saved and is cleared when a file is opened.
- **Decision:** UV 115
- **Test:** `tests/test_uv_pack.py::test_texture_set_list`
- **Code:** `uv_pack.py`, `uv_marks.py`

### UV-PCK-020: Packing picked per material

- **Status:** wish
- **Requirement:** The texture set to pack is picked directly as a material, not through the object selection.
- **Decision:** none (waits for artists' feedback, UV journal Session 102, open item 2)
- **Test:** no test

### UV-PCK-021: Add to Layout

- **Status:** wish
- **Requirement:** Packs selected new islands into the free space of a set with the rest pinned, for parts added
  after texturing.
- **Decision:** none (UV journal Session 99; open item 2 of Session 102)
- **Test:** no test

### UV-PCK-022: Ignore short needles

- **Status:** wish
- **Requirement:** The checks and the packer report ignore needles too short to matter.
- **Decision:** none (waits for artists' feedback, UV journal Session 100)
- **Test:** no test
