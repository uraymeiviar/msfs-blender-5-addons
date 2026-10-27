# General Tools and Checks

[Specification](README.md) / **general-tools.md**

The Utilities panel of fss_blender_tools (General, Empty Bounds, Heatmap, Checks), the check wishes, and other
wishes without an area of their own. Artist guide: [../user/fss-tools.md](../user/fss-tools.md#utilities),
[../user/uv.md](../user/uv.md#heatmap-distortion-texel-density-and-visibility).

## Sidebar

### GEN-040: Two sidebar tabs

- **Status:** implemented
- **Requirement:** fss_blender_tools draws its 3D Viewport panels in two tabs: **FSS Tools** for tools that work on any
  model (Zones & Merge Tree, Tags, UV Tools, Utilities, in that order) and **FSS MSFS Tools** for tools that follow MSFS
  rules (Materials, LOD). The UV Editor's Packing panel is in its own FSS Tools tab. One add-on; only the UI is split.
- **Decision:** MAT 7
- **Test:** `tests/test_panels.py::test_layout`
- **Code:** `panels.py`, `lod.py`, `materials.py`

## General

### GEN-001: Add Empty Parent

- **Status:** implemented
- **Requirement:** In Object Mode, for each selected object, a new Plain Axes empty is created at the object's world
  location and rotation with scale 1. The empty takes over the object's parent (including a parent bone) and its
  collections; the object becomes its child without moving. Naming: Manual (one selected object only, default
  `<object>_PARENT`; with several objects Suffix is used), Suffix (object name + suffix, default `_PARENT`), Prefix
  (prefix + object name, default `PARENT_`). One undo step.
- **Data:** DAT-006
- **Decision:** none recorded
- **Test:** no test
- **Code:** `tools.py` (`FSS_OT_AddEmptyParent`)

### GEN-002: Origin to Bounding Box

- **Status:** implemented
- **Requirement:** In Object Mode, for each selected object, the origin moves to a chosen point of the tightest
  (rotatable) bounding box of the object's own geometry, children ignored: one of 8 corners, 6 face centres (default
  Bottom -Z) or 12 edge centres. The object's axes turn to match the box, as close to the old axes as possible.
  Neither the geometry nor the children move in the world. A mesh shared by several objects is made single-user for
  the changed object first. The transform orientation is set to Local afterwards. One undo step.
- **Data:** DAT-006
- **Decision:** none recorded
- **Test:** no test
- **Code:** `tools.py` (`FSS_OT_OriginToBounds`)
- **Notes:** the object's rotation values change; an object whose own transform is animated no longer matches its
  keys.

## Empty Bounds

### GEN-003: Boxes around empties' subtrees

- **Status:** implemented
- **Requirement:** A viewport overlay draws, per empty, a box around everything below it, hidden descendants
  included, built from the direct children's boxes. Modes: All (every empty; while a non-empty object is selected,
  only the selection's parents), Selected (selected empties and the empties above a selected object), Off. The
  direct parent of a selected object is drawn solid with a cross at its origin, the empties further up dashed. In
  Front draws over the geometry (default on). Nothing is added to the scene, the Outliner or an export; the overlay
  is controlled only from the sidebar. In a background Blender no handler is registered.
- **Data:** DAT-006
- **Decision:** W29; EB "No scene data", "Box extent", "Global switch only", "Parents of a selected object"; PERF S1
  (no handler in background)
- **Test:** `tests/test_panels.py::test_draw_all` (panel only)
- **Code:** `empty_bounds.py`
- **Notes:** NOT TESTED: the boxes.

### GEN-004: Hierarchy text

- **Status:** implemented
- **Requirement:** With Hierarchy Text on (default), the bottom-right corner of the viewport lists the active
  object's parent chain, root first, in Object Mode. Clicking a row selects that object; Shift + click adds it to or
  removes it from the selection.
- **Data:** DAT-006
- **Decision:** EB "Clickable boxes" (the text is clickable instead)
- **Test:** no test
- **Code:** `empty_bounds.py`

## Heatmap

### GEN-005: Heatmap modes and display

- **Status:** implemented
- **Requirement:** Show Heatmap colours the selected mesh objects per face in the 3D viewport, in one of three
  exclusive modes: Distortion (GEN-006), Density, Visibility.
  - **Density:** per triangle, UV area / 3D area relative to the area-weighted median of every triangle in the
    scene with the same material; read against the object's density range (scene freedom × density marks, DAT-023,
    without visibility): inside the range neutral, above it towards blue up to x2.0, below it towards red down to
    x0.5, on a log scale.
  - **Visibility:** the face scores of the `.visibility` file (DAT-036), 0 red, 0.5 neutral, 1 blue; never seen
    magenta, undetermined cyan, missing or stale meshes dark grey. Meshes without UVs are drawn.
  - Faces that cannot be measured (no area in the UVs or on the model) are magenta, called Error (Distortion and
    Density).
  - While it is shown, its objects display as Wire and the heatmap draws their surface; their own display type
    comes back when it is turned off, when they are deselected, and before the file is saved. In Edit Mode the
    heatmap is hidden.
  - It updates by itself after geometry or UV changes (on leaving Edit Mode), selection changes, a changed
    `.visibility` file, and a density mark change; Refresh rebuilds it.
  - Nothing is written to meshes or materials; the export is unchanged. Modifiers are evaluated (Mirror and Array
    copies are drawn).
- **Data:** DAT-006, DAT-023, DAT-036
- **Decision:** UV 57, 58, 61, 62, 84
- **Test:** `tests/uv_prototype/test_uv_heatmap.py::test_wire_display_takeover`,
  `tests/uv_prototype/test_uv_heatmap.py::test_updates_after_uv_change`,
  `tests/uv_prototype/test_uv_heatmap.py::test_degenerate_triangles`,
  `tests/uv_prototype/test_uv_heatmap.py::test_gltf_export_unchanged`,
  `tests/uv_prototype/test_visibility.py::test_visibility_heatmap_mode`,
  `tests/uv_prototype/test_visibility.py::test_heatmap_modifier_face_mapping`,
  `tests/test_density_marks.py::test_heatmap_after_mark_change`
- **Code:** `uv_heatmap.py`

### GEN-006: Distortion mode

- **Status:** implemented
- **Requirement:** Distortion shows two measures per face, from 1.0 (white) to 2.0 and more (full colour): shear
  (blue), the ratio of the stretch in the two directions, independent of object scale; area (green), the face's UV
  size relative to its own island's average, as a ratio either way. Both shows them together (cyan where both
  meet); Shear and Area show one alone. The area measure is the one Auto Seam's Distortion Limit limits
  (UV-SEAM-004).
- **Data:** DAT-006
- **Decision:** UV 59, 89
- **Test:** `tests/uv_prototype/test_uv_heatmap.py::test_uv_sheared`,
  `tests/uv_prototype/test_uv_heatmap.py::test_area_distortion_and_islands`,
  `tests/uv_prototype/test_uv_heatmap.py::test_flat_plane_undistorted`,
  `tests/uv_prototype/test_uv_heatmap.py::test_uv_scaled_by_two`
- **Code:** `uv_heatmap.py`

### GEN-007: Chart, legend and UV grid

- **Status:** implemented
- **Requirement:** The panel shows an area-weighted distribution chart of the selected objects' surface (square-root
  bar scale), with the colour band, marks (shear 1.10 and 1.25; area at the current Distortion Limit; Density 1.0;
  Visibility 0.5), the middle 90 % range, and shares (over 1.10 and 1.25, outside the density range, never seen or
  undetermined, islands over the limit). A viewport legend shows the mode, its shares, the Error count and skipped
  objects. An optional UV grid (default on, 8, 16, 32 or 64 cells, default 16) with cell labels (column letter, row
  number) is drawn in UV space over the heatmap; its settings are saved with the file.
- **Data:** DAT-006
- **Decision:** UV 60, 63, 66
- **Test:** `tests/uv_prototype/test_uv_heatmap.py::test_distribution_chart`,
  `tests/uv_prototype/test_uv_heatmap.py::test_uv_grid_and_labels`
- **Code:** `uv_heatmap.py`

## Checks

### GEN-008: Scan Names

- **Status:** implemented
- **Requirement:** Scan Names lists every object in the file and, with Bones on (default), every bone, whose name
  breaks a rule, with a proposal:

  | Tag | Finds | Proposal, ticked |
  | :--- | :--- | :--- |
  | `SFX` | ends in `.NNN` and the name without it is free (the lowest number wins) | the name without the suffix, ticked |
  | `COL` | ends in `.NNN` and the name without it is taken | none (report only) |
  | `CASE` | lower-case letters, ignoring the suffix and an `x0_` to `x9_` prefix | upper case, ticked |
  | `CHR` | characters outside `A-Z`, `0-9`, `_`; a leading `@` is allowed | `_` for each, ticked |
  | `DEF` | a Blender default base name (`Cube`, `Empty`, `Bone`, ...) | none (typed by hand) |
  | `TKN` | the proposed name is already used or proposed twice | never applied |
  | `CLS` | exports under the same name as another item once leading `@` are stripped | none (report only) |

  Rule buttons filter the list; clicking a row selects the item; Frame zooms to it. Objects form one namespace, the
  bones of each armature another. The MSFS project is not read.
- **Data:** DAT-006
- **Decision:** W2 (without the project contract); NC D1 to D4; UV 87 (`@` allowed, `CLS`)
- **Test:** `tests/test_markers.py::test_scan_names` (markers and `CLS` only)
- **Code:** `name_check.py`
- **Notes:** NOT TESTED: `SFX`, `COL`, `CASE`, `CHR`, `DEF`, `TKN`.

### GEN-009: Batch rename

- **Status:** implemented
- **Requirement:** Rename Selected (N) renames every ticked row shown, in one undo step, then scans again; a
  proposal can be edited in its field. A target name that is taken at that moment is skipped and listed in the
  console, never forced. Linked (library) items are listed but not renamed; bones of an armature in Edit Mode are
  skipped. Tick All and Untick All act on the rows shown.
- **Data:** DAT-006
- **Decision:** NC (Solution: Rename Selected); WL D3 (rename the objects, no export-time alias)
- **Test:** no test
- **Code:** `name_check.py`

### GEN-010: Find Faces Without Area

- **Status:** implemented
- **Requirement:** In Object Mode, checks every mesh object of the view layer for faces of at most 0.000001 cm² on
  the model; selects the visible objects that have them (the first active) and those faces in their meshes; reports
  the face and object counts (hidden objects counted, not selected) and lists each object on the console.
- **Decision:** UV 117
- **Test:** `tests/test_uv_pack.py::test_faces_without_area`
- **Code:** `checks.py` (`FSS_OT_FindFacesWithoutArea`)

### GEN-011: Find Faces Without UV Area

- **Status:** implemented
- **Requirement:** In Object Mode, checks every mesh object of the view layer with a UV map, per texture set at its
  size (DAT-025): a face counts when one of its triangles has area on the model but, in the UVs, at most 0.000001
  pixel² of its texture set, or lies on a line (UV area at most 0.00001 × its longest UV edge squared), inside an
  island that otherwise has UV area. Triangles without area on the model and islands without any UV area are not
  counted. Selects the visible objects (first active) and those faces; reports faces, islands and objects; lists
  each object on the console.
- **Data:** DAT-025
- **Decision:** UV 118
- **Test:** `tests/test_uv_pack.py::test_faces_without_uv_area`
- **Code:** `checks.py` (`FSS_OT_FindFacesWithoutUvArea`)

### GEN-012: Find Thin UV Faces

- **Status:** wish
- **Requirement:** One check replacing GEN-011: a face is thin when any of its UV triangles is less than a width
  (default 1 px) wide on a texture of a size (default 1K), the width being the triangle's UV height over its
  longest UV edge; covers empty faces and thin or short needles. Texture size and width are settings; selects
  objects and faces.
- **Decision:** none (proposed 20261023, UV journal Session 102, open item 1)
- **Test:** no test
- **Notes:** legitimately tiny parts packed small can fall under 1 px at 1K.

### GEN-013: Fix Broken Bone Parents

- **Status:** implemented
- **Requirement:** Finds every local (not linked) object in the file that has a parent bone while its parent is
  missing or not an armature, and resets it to Object parenting (`parent_type = 'OBJECT'`, empty `parent_bone`)
  without moving it in the world; reports how many objects it fixed. One undo step.
- **Decision:** W28 (first rule); TM Session 6
- **Test:** no test
- **Code:** `checks.py` (`FSS_OT_FixBoneParents`)

## Check Wishes

### GEN-020: Stupidity check

- **Status:** wish
- **Requirement:** One report, each finding with severity, the object and a fix: duplicate vertices and faces,
  faces without area, loose geometry, hierarchy problems, unapplied transforms, bloat, data of external add-ons.
- **Decision:** W28 (two rules built: GEN-010, GEN-013)
- **Test:** no test

### GEN-021: Texture and path check

- **Status:** wish
- **Requirement:** Reports missing images, absolute paths and paths outside the project, and missing `.png.xml`
  files.
- **Decision:** W11
- **Test:** no test

### GEN-022: Material consolidation

- **Status:** wish
- **Requirement:** Finds duplicate materials (`.001` copies, identical textures and parameters) and objects split
  only by such duplicates.
- **Decision:** W10
- **Test:** no test

### GEN-023: Instancing candidates

- **Status:** wish
- **Requirement:** Finds meshes with identical geometry that are not linked, and modifiers that block instancing;
  offers to bake shared modifiers.
- **Decision:** W9
- **Test:** no test

### GEN-024: Exported glTF diff

- **Status:** wish
- **Requirement:** Compares a new export against the deployed glTF: nodes, animations, materials and primitive
  counts added, removed or changed.
- **Decision:** W12
- **Test:** no test
- **Notes:** `tests/harness/compare.py` already compares two glTFs.

### GEN-025: Draw-call and LOD prediction

- **Status:** wish
- **Requirement:** Predicts draw calls, batches and the active LOD; an approximate count is enough.
- **Decision:** W7; WL D6
- **Test:** no test

## Other Wishes

Wishes from the wish-list without an area of their own. Each is a wish with no test; the wish-list item holds the
description.

| ID | Wish | Decision |
| :--- | :--- | :--- |
| GEN-030 | Legend bake helper: bake a button's decal text into its texture sheet | W15 |
| GEN-031 | Decal text generator from a glyph atlas | W16 |
| GEN-032 | Cockpit bake operator (AO, sky light, flood circuits) | W18 |
| GEN-033 | Dirt, grime and ice shell generator | W19 |
| GEN-034 | Sky portal placer per window glass | W20 |
| GEN-035 | Transparency sorting-risk check from the pilot eye points | W22 |
| GEN-036 | Registration mesh check | W24 |
| GEN-037 | Exterior light audit | W25 |
| GEN-038 | Wing-flex joint helper | W26 |
| GEN-039 | Tools for passive (AI traffic) aircraft, deferred until a passive E-Jet is planned | wish-list |
