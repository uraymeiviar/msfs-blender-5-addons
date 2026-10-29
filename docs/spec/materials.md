# Materials

[Specification](README.md) / **materials.md**

The Materials panel: every material of the file with its users, zones, kind and surface, in the sidebar tab FSS MSFS
Tools. Artist guide: [../user/materials.md](../user/materials.md). Decisions: material management journal (MAT).

## Panel

### MTL-001: Materials panel and Refresh

- **Status:** implemented
- **Requirement:** The panel Materials is second in the 3D Viewport sidebar tab FSS MSFS Tools, after Zones & Merge Tree (GEN-040). Refresh (Object
  Mode) fills `Scene.fss_materials` (DAT-007) from the view layer and changes nothing else; the panel only reads those
  rows and does not follow changes until the next Refresh, which it says. Before the first Refresh it asks for one.
- **Data:** DAT-007
- **Decision:** MAT 1, 7, 11
- **Test:** `tests/test_materials.py::test_rows`, `tests/test_materials.py::test_draw`, `tests/test_panels.py::test_layout`
- **Code:** `fss_blender_tools/materials.py` (`scan`, `FSS_OT_MaterialsRefresh`, `FSS_PT_Materials`)
- **Notes:** Refresh on the E2 cockpit copy (3,628 objects): 0.4 to 0.7 s (material management journal Sessions 7, 10).

### MTL-002: Material list

- **Status:** implemented
- **Requirement:** One row per material of the file except grease pencil materials, filterable by name and by All /
  Warnings, with:
  - a warning when the material is **never used** (no face of a mesh object of the view layer, visible or hidden, uses
    it; a material only in an empty slot, on objects outside the view layer, or in no slot) or **shared across zones**
    (its objects lie in more than one zone; objects outside every zone count as the zone "(no zone)");
  - the marks **transparent** (MSFS alpha mode Blend, not an alpha value) and **emissive** (an MSFS emissive texture
    assigned), read without error when the exporter add-on is absent; a legend explains the icons;
  - the number of using objects, their zones, the texture size and the last Pack or Check All result.
- **Data:** DAT-007, DAT-025
- **Decision:** MAT 3, 9, 11; objectives 1, 3 (Session 1)
- **Test:** `tests/test_materials.py::test_rows`, `tests/test_materials.py::test_kinds`
- **Code:** `materials.py` (`FSS_UL_Materials`)

### MTL-003: Active material box

- **Status:** implemented
- **Requirement:** For the clicked row: objects (total, hidden, meshes shared by several users of the material); per zone
  the objects and world-space 3D area, with a warning when there is more than one zone; the total area and the estimate
  (MTL-004) or "kept" (MTL-005); the texture size and last result; Keep UVs (MTL-006); Select Objects and, with several
  zones, Select in <zone> (MTL-007). A mesh shared by several objects counts its area once, in the zone of its first
  user by name; faces whose material index lies past the last slot use no material.
- **Data:** DAT-007
- **Decision:** MAT 1 (Session 1, Proposed Content); Session 7 (accepted proposals)
- **Test:** `tests/test_materials.py::test_rows`, `tests/test_materials.py::test_draw`
- **Code:** `materials.py` (`_draw_active`)

### MTL-004: Texture size estimate

- **Status:** implemented
- **Requirement:** The side in pixels of a square that holds the material's faces at the top of their density range
  times their visibility: `sqrt(sum over faces of area_cm2 x (target density x factor_high x visibility)^2)`, where
  `factor_high` is the high end of the object's density range (UV-DEN-003) and visibility is the object's score from the
  `.visibility` file, never below 0.1, and 1.0 without data (unsaved file, missing file, stale or missing mesh; UV-VIS-008).
  A shared mesh uses its first user. It ignores margins and island shapes and is labelled "estimate, with visibility" or
  "estimate, no visibility data"; Check All gives the packed result.
- **Data:** DAT-023, DAT-036
- **Decision:** MAT 12
- **Test:** `tests/test_materials.py::test_rows`, `tests/test_materials.py::test_visibility`
- **Code:** `materials.py` (`scan`, `visibility_reader`)
- **Notes:** on the E2 cockpit copy the estimate lies within about 0.8 to 1.3 times the side of the packed islands' area
  for sets that fit (Rear_doors 1,242 px against about 1,250 px; Sessions 9, 10); it cannot see layouts that a few
  islands push out (Cockpit_STD).

### MTL-005: Kept sets have no estimate

- **Status:** implemented
- **Requirement:** For a material with Keep UVs (DAT-024) the box says "kept (Keep UVs): no estimate" instead of the
  estimate; Keep UVs is read from the material while drawing, so a change shows without Refresh.
- **Data:** DAT-024
- **Decision:** MAT 13
- **Test:** `tests/test_materials.py::test_keep_uvs`
- **Code:** `materials.py` (`estimate_text`)

### MTL-006: Keep UVs in the panel

- **Status:** implemented
- **Requirement:** The box shows the Keep UVs checkbox of the material (the same property as in Packing, UV-PCK-011). It
  is the panel's only control that changes data.
- **Data:** DAT-024
- **Decision:** MAT 14
- **Test:** `tests/test_materials.py::test_keep_uvs`
- **Code:** `materials.py` (`_draw_active`)
- **Notes:** the click itself was never tried in an interactive Blender.

### MTL-007: Select Objects

- **Status:** implemented
- **Requirement:** Select Objects selects the visible objects that use the material (in one zone with Select in
  <zone>), makes the first active, and changes nothing else; Object Mode. The artist tags them, for example with a
  Don't Merge tag (TAG-005); the tool sets no tags.
- **Decision:** MAT 4, 8
- **Test:** `tests/test_materials.py::test_select`
- **Code:** `materials.py` (`FSS_OT_MaterialsSelect`)

### MTL-008: Check All from the panel

- **Status:** implemented
- **Requirement:** The panel offers Check All (UV-PCK-008); while it runs, the panel shows its progress in place of the
  button.
- **Decision:** MAT 1 (Proposed Content)
- **Test:** `tests/test_materials.py::test_draw` (drawn); NOT TESTED: a run started from this panel
- **Code:** `materials.py`, `uv_marks.py`

### MTL-009: By Zone

- **Status:** implemented
- **Requirement:** A subpanel, closed by default, lists per zone, and for "(no zone)", its materials with objects, area
  and share of the zone's area, from the rows of the last Refresh.
- **Decision:** MAT 1 (Proposed Content)
- **Test:** `tests/test_materials.py::test_draw`
- **Code:** `materials.py` (`FSS_PT_MaterialsByZone`, `zone_table`)

## Planned and Wishes

### MTL-020: MSFS material checks

- **Status:** planned
- **Requirement:** The panel reports materials without an MSFS material, MSFS materials that make no sense without a
  texture (informational before texturing), and MSFS material parameters that make no sense or can lead to an error.
  The rules come from the SDK documentation and are reviewed with the maintainer rule by rule before they are built.
- **Decision:** objectives 2, 5, 6 (material management journal Session 1); MAT 7 (in FSS MSFS Tools)
- **Test:** no test

### MTL-021: Split helpers for oversized sets

- **Status:** planned
- **Requirement:** For a set that does not fit even at 8192, the panel suggests and, on request, makes a second material
  (by zone or by a group of objects) and reassigns the chosen objects.
- **Decision:** objectives (Session 1: "8K itself won't fit so we need two textures")
- **Test:** no test

### MTL-022: Emissive texture imbalance

- **Status:** planned
- **Requirement:** For a material with an emissive texture, after painting, the panel measures the emissive image under
  each object's islands and reports when only a small part of the set emits light, so the artist can split the
  emitting parts into their own material. Before painting, and for materials without an emissive texture, it reports
  nothing.
- **Decision:** MAT 3, 10; objectives (Session 1)
- **Test:** no test
