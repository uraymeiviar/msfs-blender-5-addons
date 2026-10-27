# Specification

What the FSS add-ons do (**implemented**), will do (**planned**) and might do (**wish**): one requirement per
statement, each with its decision and its test. Drafted on 20261028 from the [feature inventory](inventory.md),
checked against the code of fss_blender_tools 0.33.1 and the exporter at commit 4261fff (the Materials panel and the sidebar tabs against 0.35.0), and against the tests.

| Document | Holds | Audience |
| :--- | :--- | :--- |
| This specification | what holds today and what is decided | developers and agents |
| [inventory.md](inventory.md) | the status overview, and the rejected proposals (rejected items live only there) | developers and agents |
| [../journal/](../journal/README.md) | history, reasoning, measurements, hand-offs | developers and agents |
| [../user/](../user/README.md) | how to use the tools | artists |

When code, guide and specification disagree, the specification states what is decided; a deviation in the code is a
defect, a deviation in the guide is a documentation defect. A change of a requirement needs a maintainer decision
recorded in a journal first ([../../AGENTS.md](../../AGENTS.md#working-model)), then the specification follows.

## Files

| File | Prefix | Area |
| :--- | :--- | :--- |
| [data-formats.md](data-formats.md) | `DAT` | Properties and marks, name markers, the `.visibility` file, text blocks, what reaches the glTF |
| [exporter.md](exporter.md) | `EXP` | The exporter `io_scene_gltf2_msfs_fss` |
| [general-tools.md](general-tools.md) | `GEN` | Utilities: General, Empty Bounds, Heatmap, Checks; other wishes |
| [tags.md](tags.md) | `TAG` | Tags and their switches |
| [zones.md](zones.md) | `ZON` | Zone empties, zone rows, the zone tool |
| [merge-tree.md](merge-tree.md) | `MRG` | Export-time merge groups |
| [materials.md](materials.md) | `MTL` | The Materials panel: material list, warnings, kinds, zones, size estimate |
| [lod.md](lod.md) | `LOD` | LOD marks, size culling, quota, viewport LOD, LOD sphere |
| [uv.md](uv.md) | `UV-SEAM`, `UV-UNW`, `UV-VIS`, `UV-DEN`, `UV-PCK` | Seams, unwrap, Visibility Scoring, density, packing |
| [project-contract.md](project-contract.md) | `PRJ` | Tools that need the MSFS project contract |

## Principles

These hold for every requirement of fss_blender_tools (the exporter follows Asobo's design, see
[exporter.md](exporter.md)).

| ID | Principle | Decision |
| :--- | :--- | :--- |
| P-1 | **Two add-ons.** The exporter stays an exporter that tracks Asobo and stays mergeable; every other feature belongs in fss_blender_tools. | WL Session 1; AGENTS.md Upstream Policy |
| P-2 | **No enforced workflow.** Each tool is independent and optional, an aid next to the artist's manual work; no tool requires another tool to have been used. | UV 42 |
| P-3 | **Model-agnostic rules.** Tools work on any model; no decision by MSFS material type where a generic rule exists. Accepted exceptions: Auto Seam's skip by material class (UV-SEAM-008) and the material classes in Visibility Scoring (UV-VIS-007). | UV 100 |
| P-4 | **Accuracy first.** A tool meets its target exactly and reports what does not fit, rather than adjusting the result silently; the artist then chooses. | UV 112 |
| P-5 | **Tool data stays out of the model.** Settings and marks of fss_blender_tools never reach the exported glTF (DAT-040). | UV 87; TM Session 8, decision 5 |
| P-6 | **The `.blend` stays the artist's.** Export-time changes (merging, culling, padding, material swaps) act on throwaway copies or are undone; a saved file never carries a tool's temporary state. | TM Session 1, decision 7; LOD 35 |

## Statuses

| Status | Meaning |
| :--- | :--- |
| **implemented** | built and released; checked against the code of the version named at the top |
| **planned** | decided by the maintainer, not built |
| **wish** | proposed or listed, not decided |

A rejected proposal is not a requirement. If a requirement is rejected later, its entry stays as one line pointing
to the inventory's Rejected table, so references to its ID still resolve.

## IDs

- `<PREFIX>-<NNN>`, three digits, for example `MRG-004`; UV uses a section prefix, for example `UV-PCK-011`.
- An ID is never renumbered and never reused. New requirements take the next free number of their prefix, also
  when they belong between two existing ones.

## Requirement Template

```markdown
### UV-PCK-011: Keep UVs per texture set

- **Status:** implemented
- **Requirement:** A material can be marked Keep UVs. Pack is unavailable for its texture set and writes no UVs
  on its faces; Check All measures nothing for it and reports it as "kept". No material type decides this:
  only the mark does.
- **Data:** DAT-024
- **Decision:** UV 116 (rests on UV 100)
- **Test:** `tests/test_uv_pack.py::test_check_all_and_keep`
- **Code:** `fss_blender_tools/uv_pack.py`, `uv_marks.py`
- **Notes:** never checked in an interactive Blender (UV journal Session 102, open item 3)
```

| Field | Content |
| :--- | :--- |
| **Status** | one of the three statuses |
| **Requirement** | what holds, as statements that a test can check; no rationale (that is in the journal) |
| **Data** | the `DAT` entries it reads or writes; omitted when none |
| **Decision** | where the maintainer decided it (see Decision References); "none recorded" when the feature was built without a recorded decision |
| **Test** | `file::function` of an automated test; "harness: ..." for the differential harness; "manual: <journal> Session N" for a one-time check; "no test" |
| **Code** | the module and, where useful, the function; no line numbers |
| **Notes** | optional: limits, known issues, gaps; a gap between the requirement and its test is written as **NOT TESTED:** followed by what is not covered |

## Decision References

| Reference | Meaning |
| :--- | :--- |
| UV *n* | decision *n* of [20261019.automated-uv-unwrap.md](../journal/20261019.automated-uv-unwrap.md) (in force: Session 102) |
| LOD *n* | decision *n* of [20261010.automated-lod-generation.md](../journal/20261010.automated-lod-generation.md) |
| TM S*x*.*n* | decision *n* of Session *x* of [20261014.fss-blender-tools-tags-and-merge.md](../journal/20261014.fss-blender-tools-tags-and-merge.md) (numbering restarts per session) |
| CONV S*x*.*n* | decision *n* of Session *x* of [20261002.msfs2024-blender5-exporter-conversion.md](../journal/20261002.msfs2024-blender5-exporter-conversion.md); CONV S3 refers to its decision table, CONV S4 to its design list |
| W*n* | item *n* of the wish-list in [20261010.fss-blender-tools-wishlist.md](../journal/20261010.fss-blender-tools-wishlist.md); WL D*n* its maintainer decision *n* |
| EB, NC | the Session 1 decisions of [20261011.fss-blender-tools-empty-bounds.md](../journal/20261011.fss-blender-tools-empty-bounds.md) and [20261011.fss-blender-tools-name-check.md](../journal/20261011.fss-blender-tools-name-check.md), by their title or label (D1 to D5) |
| PERF S*x* | Session *x* of [20261017.export-performance.md](../journal/20261017.export-performance.md) |
| MAT *n* | decision *n* of [20261028.material-management.md](../journal/20261028.material-management.md) |

## Test References

The suites and how to run them: [../../tests/README.md](../../tests/README.md). A `file::function` reference to a unittest suite (`tests/test_lod_rules.py`) names the test method without its class. Two scripts outside that list are
referenced as well: `tests/build_lod_scene.py` (builds a synthetic LOD scene and checks its preview state) and
`tests/verify_lod_exports.py` (checks the seven LOD exports of that scene for both simulators). No runner or
document in this repository produces the export folder and the `lod-fs24.log` / `lod-fs20.log` files that
`verify_lod_exports.py` reads, so they count as tests that cannot be re-run as they stand; requirements tracing to
them say so.

## Known Gaps (20261028)

Gaps found while the specification was drafted; each shows at its requirement as "no test" or in its Notes.

| Gap | Requirements |
| :--- | :--- |
| The packer's margin check counts a violation below one margin; the requirement is two margins between islands | UV-PCK-007 |
| The merge rules have no unit test; the only export check is the LOD pair above, which cannot be re-run as it stands | MRG-001 to MRG-012, DAT-043 |
| Tags have no test | TAG-001 to TAG-007 |
| Exporter features without a test: target detection, migration and emissive reference, Prepare for MSFS 2024, legacy normals, instancing, export clean-up, the hidden Asobo workflow; Export For and the unchanged materials after an MSFS 2020 export only indirectly | EXP-002 to EXP-010 |
| General tools without a test: Add Empty Parent, Origin to Bounding Box, Empty Bounds, batch rename, Fix Broken Bone Parents; Scan Names tested for markers only | GEN-001 to GEN-004, GEN-008, GEN-009, GEN-013 |
| LOD features without a test: loose pieces, Smallest Part Kept, Refresh LOD Counts, hints, the LOD sphere and its padding, Print LOD Settings, hidden reference empties; the quota panel (its calculation is tested) | LOD-007, LOD-009 to LOD-012, LOD-015 to LOD-019 |
| Auto Seam's core rules (no diagonal cuts, chart acceptance) are only measured with prototype scripts, not in a unit suite | UV-SEAM-001 |
| How Visibility Scoring combines instances was not checked against the code | UV-VIS-005 |
| Never seen in an interactive Blender (UV journal Session 102, open item 3) | UV-DEN-005, UV-PCK-002, UV-PCK-008, UV-PCK-011, UV-PCK-014 |
| Registered properties of the exporter (`msfs_fss_*`) and the mesh property `msfs_fss_legacy_auto_smooth` are not stripped from glTF extras; whether they reach a glTF with Include Extras is not checked | DAT-041 |
