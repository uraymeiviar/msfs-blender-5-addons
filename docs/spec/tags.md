# Tags

[Specification](README.md) / **tags.md**

Free labels on objects, independent of collections, and two switches that tell the export what to do with tagged
objects. Artist guide: [../user/fss-tools.md](../user/fss-tools.md#tags).

## Tags

### TAG-001: Free, multi-valued tags

- **Status:** implemented
- **Requirement:** An object has any number of tags, each a name the artist chooses (not empty, without `;`), stored
  in `fss_tags` (DAT-020) without duplicates. Nothing is inferred from materials, names or the MSFS project, and no
  tag name has a built-in meaning. Tags are readable and editable without the add-on (Custom Properties).
- **Data:** DAT-020
- **Decision:** TM S1.1, S1.2; W5 (realised as generic tags)
- **Test:** no test
- **Code:** `tags.py`

### TAG-002: Add and remove

- **Status:** implemented
- **Requirement:** The tag field takes one or more names separated by `;` or `,`; **+** adds them to the selected
  objects, **-** removes them. While the active object is selected, its tags are listed, each with **X** to remove it
  from the active object only. In the tag list, per tag, **-** and **+** remove it from or add it to the selected objects; they are
  greyed out when they would change nothing. Linked and library-override objects are not changed.
- **Data:** DAT-006, DAT-020
- **Decision:** TM S1.2
- **Test:** no test
- **Code:** `tags.py` (`FSS_OT_TagAdd`, `FSS_OT_TagRemove`)

### TAG-003: Tag list and selection

- **Status:** implemented
- **Requirement:** The panel lists every tag in the file with the number of objects that carry it. Clicking a tag
  selects the visible objects with it (Shift + click adds to the selection); hidden objects are counted but not
  selected. The name is highlighted when at least one selected object has the tag. Per row, from the left: **-** and
  **+**, rename, the name; on the right, at the same place in every row, Don't Merge, Keep, Non-AO-Occluder,
  Skip-AO-Bake, a small gap, delete.
- **Decision:** TM S1.2; TM S10.1 to S10.6; TM S13.1
- **Test:** `tests/test_zone_tree.py::test_tags_panel` (what the panel draws, not the selection)
- **Code:** `tags.py` (`FSS_OT_TagSelect`)

### TAG-004: Rename and delete

- **Status:** implemented
- **Requirement:** Rename changes a tag to exactly one new name on every editable object in the file and in the
  settings of its switches (TAG-005, TAG-006, TAG-008, TAG-009). Delete asks for confirmation, then removes the tag from
  every editable object and from those settings; the objects stay.
- **Data:** DAT-002, DAT-003, DAT-006, DAT-020
- **Decision:** none recorded
- **Test:** `tests/test_zone_tree.py::test_tags_panel` (the AO settings only)
- **Code:** `tags.py` (`FSS_OT_TagRename`, `FSS_OT_TagDelete`)

## Switches

### TAG-005: Don't Merge

- **Status:** implemented
- **Requirement:** A tag's Don't Merge toggle adds it to or removes it from `fss_merge.skip_tags`. An object with such
  a tag stays out of merge groups with its subtree (MRG-003); a refreshed Zones & Merge Tree panel is refreshed
  again after the change.
- **Data:** DAT-002
- **Decision:** TM Session 1 (Don't Merge switch)
- **Test:** no test
- **Code:** `tags.py` (`FSS_OT_TagToggleSkipMerge`)

### TAG-006: Keep (LOD)

- **Status:** implemented
- **Requirement:** A tag's Keep toggle adds it to or removes it from `fss_lod_settings.keep_tags`. An object with
  such a tag is treated like an object with the Keep mark (LOD-003). The toggle is a pin icon, with a tooltip saying
  what it does.
- **Data:** DAT-003
- **Decision:** LOD 11; TM S10.7
- **Test:** `tests/build_lod_scene.py` (`keep_tags` with one tagged object; cannot be re-run as it stands, see
  [README.md](README.md#test-references))
- **Code:** `tags.py` (`FSS_OT_TagToggleKeep`), `lod_model.py`

### TAG-007: Tags are not exported

- **Status:** implemented
- **Requirement:** `fss_tags` never reaches the glTF (DAT-040).
- **Decision:** TM S8.5 (by the same rule); UV 87
- **Test:** no test of `fss_tags` in particular; the strip rule is tested in `tests/test_zone_tree.py::test_gltf_leak`

### TAG-008: Non-AO-Occluder

- **Status:** implemented as a setting; no AO auto-bake reads it yet (GEN-032)
- **Requirement:** A tag's Non-AO-Occluder toggle (ghost icon) adds it to or removes it from
  `Scene.fss_ao_no_occluder_tags`. An object carrying such a tag is never used as an occluder by the AO auto-bake;
  `tags.is_ao_occluder(obj, scene)` answers this for the bake. Only the objects that carry the tag count, not their
  children.
- **Data:** DAT-006
- **Decision:** TM S13.1, S13.2
- **Test:** `tests/test_zone_tree.py::test_tags_panel`, `tests/test_zone_tree.py::test_gltf_leak`
- **Code:** `tags.py` (`FSS_OT_TagToggleAONoOccluder`, `is_ao_occluder`)

### TAG-009: Skip-AO-Bake

- **Status:** implemented as a setting; no AO auto-bake reads it yet (GEN-032)
- **Requirement:** A tag's Skip-AO-Bake toggle (render icon) adds it to or removes it from
  `Scene.fss_ao_skip_bake_tags`. An object carrying such a tag is never a target of the AO auto-bake;
  `tags.is_ao_baked(obj, scene)` answers this for the bake. Only the objects that carry the tag count, not their
  children.
- **Data:** DAT-006
- **Decision:** TM S13.1, S13.2
- **Test:** `tests/test_zone_tree.py::test_tags_panel`, `tests/test_zone_tree.py::test_gltf_leak`
- **Code:** `tags.py` (`FSS_OT_TagToggleAOSkipBake`, `is_ao_baked`)

## Wishes

### TAG-010: Functional roles

- **Status:** wish
- **Requirement:** Roles with a meaning (clickspot, screen, light mesh, emitter, debug mesh), inferred from materials
  and `panel.cfg`.
- **Decision:** W5 (TM S1.1 chose generic tags instead)
- **Test:** no test

### TAG-011: Collections to tags

- **Status:** wish
- **Requirement:** Converts the functional collections of an existing file into tags or roles.
- **Decision:** W5
- **Test:** no test
