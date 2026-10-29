# Zones

[Specification](README.md) / **zones.md**

A zone is a part of the model with its own materials and texture sets, culled together; its empty holds the merge
groups of that part. Artist guide: [../user/README.md](../user/README.md#2-zones-and-materials-in-development),
[../user/fss-tools.md](../user/fss-tools.md#zones--merge-tree).

## Zone Empties

### ZON-001: `@ZONE_<NAME>` empties

- **Status:** implemented
- **Requirement:** An object whose name starts with `@ZONE_` is a zone; its zone is the nearest `@ZONE_` object at or
  above an object (`merge.nearest_zone`), none outside every zone. The zone empty is exported, as `ZONE_<NAME>`
  (DAT-033), so the children's local coordinates stay consistent.
- **Data:** DAT-033
- **Decision:** UV 23, 28, 33, 87
- **Test:** `tests/test_zone_tree.py::test_nearest_zone`, `tests/test_markers.py::test_strip_markers`
- **Code:** `merge.py`

### ZON-002: Zones in the Zones & Merge Tree panel

- **Status:** implemented
- **Requirement:** Refresh lists the visible objects' zones as top-level rows (name without the marker) with the
  number of merge groups and objects below each, and their merge groups nested below them (MRG-010). Warnings: an
  Unzoned entry for merge groups with no zone above them; on a zone row, a zone inside a merge group or inside
  another zone. Clicking a row selects the object.
- **Data:** DAT-002
- **Decision:** UV 34; TM S8.1 to S8.3
- **Test:** `tests/test_zone_tree.py::test_tree_rows`, `tests/test_zone_tree.py::test_draw_smoke`
- **Code:** `merge.py`

### ZON-003: Zone density factor

- **Status:** implemented
- **Requirement:** A zone's density factor is the zone empty's own density mark (DAT-023); like every mark it
  multiplies everything below it (UV-DEN-003). The zone row edits the mark (tick, Min, Max, greyed while off); a
  change is stored on the empty at once, without Refresh, and is the same mark the panel UV Auto Packing shows for
  that empty.
- **Data:** DAT-023
- **Decision:** UV 108 (replaces UV 76, 98, 101 and TM S8.4, S8.6)
- **Test:** `tests/test_zone_tree.py::test_zone_mark`, `tests/test_density_marks.py::test_multiplication`
- **Code:** `merge.py`, `uv_marks.py`

### ZON-004: Merge groups do not cross zones

- **Status:** implemented
- **Requirement:** A merge group's topmost marked ancestor is a zone; a zone never lies inside a merge group or a
  zone. The tools report violations (ZON-002); nothing enforces them.
- **Decision:** UV 34
- **Test:** `tests/test_zone_tree.py::test_tree_rows` (flags)
- **Code:** `merge.py`

## The Zone Tool

### ZON-010: Materials per zone and class

- **Status:** planned
- **Requirement:**
  - Hierarchy: one root empty per scene, zone empties below it; every object belongs to its nearest zone; objects
    under the root but outside every zone are listed as unzoned.
  - Every material belongs to a class of UV 30 (`STD`, `STD_EM`, `DECAL`, `DECAL_EM`, `GLASS`, `WNDSHIELD`,
    `INVIS`, `OCCLUDER`, `SCREEN`, and the special MSFS types by name).
  - Each zone has one material, and so one texture set, per class it contains (set = zone × class), named freely by
    the artist; screens always
    have their own material. No material spans zones.
  - A live, read-only check reports objects whose materials do not match their zone and class. An explicit Sync Zone
    Materials action creates missing zone materials from a template material per class (MSFS settings carried
    over), reassigns the slots, resolves shared meshes with users in different zones explicitly, and reports every
    change as one undo step. Special-class materials are not touched. No background handler changes materials.
  - The texture size stays the artist's setting per material (UV-PCK-005).
- **Decision:** UV 22 (replaced by 30), 24, 25, 26, 30; UV 29 and 32 (naming `<SCENE>_<ZONE>_<CLASS>`) withdrawn by
  MAT 2; UV 31 (size from the zone material's textures) replaced by UV 110 and 120; on hold by MAT 6
- **Test:** no test
- **Notes:** ON HOLD: not built, not cancelled (MAT 6). The material classes may come back without a naming rule
  through the Materials panel (material management journal).

### ZON-011: Mirror across zones

- **Status:** planned
- **Requirement:** Stacking (UV-PCK-010) applies only within a zone. A mirrored object stays in one zone with both
  halves by default. On request, a Split Mirror into Zones action applies the modifier and puts each half under its
  zone empty as a normal object (explicit, undoable); the zone check flags mirrored objects marked as spanning two
  zones and offers the split, never splitting on its own.
- **Decision:** UV 27; on hold by MAT 6
- **Test:** no test
- **Notes:** ON HOLD with ZON-010 (MAT 6).
