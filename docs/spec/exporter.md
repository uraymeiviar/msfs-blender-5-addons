# Exporter

[Specification](README.md) / **exporter.md**

The add-on `io_scene_gltf2_msfs_fss`: Asobo's MSFS 2024 exporter 8.4.1 for Blender 5.2 with the FSS MSFS 2020
exporter built in. Asobo's behaviour is not specified here; these requirements cover what FSS adds or changes.
FSS changes live in FSS-owned modules so Asobo releases stay mergeable (AGENTS.md, Upstream Policy). Artist guide:
[../user/exporter.md](../user/exporter.md).

The differential harness (`tests/run_tests.py`) compares this add-on's export with the per-simulator forks on six
cases (materials, skinning, hierarchy, lights, gizmos, vertex data); it shows that both targets export as the
forks do, not that a single FSS feature works.

## Targets

### EXP-001: Export Target per scene

- **Status:** implemented
- **Requirement:** Each scene has an Export Target, MSFS 2024 or MSFS 2020 (DAT-046); new scenes are MSFS 2024. The
  target decides the glTF extensions, the material data, and which collision gizmos and lights are exported. It is
  set in the 3D Viewport sidebar (Export Target panel) and in the glTF export dialog.
- **Data:** DAT-046
- **Decision:** CONV S3 (unified add-on, per-scene target, default MSFS 2024); CONV S4 design 2 and 6
- **Test:** harness: `tests/run_tests.py --sim 2024`, `tests/run_tests.py --sim 2020`
- **Code:** `msfs2020_target.py`, `ui/target_panels.py`

### EXP-002: Target detection on open, nothing converted

- **Status:** implemented
- **Requirement:** A `.blend` without a saved target that contains MSFS 2020 data (MSFS 2020 export settings,
  legacy collision gizmos or lights, materials made with the MSFS 2020 add-on) gets the target MSFS 2020 when it is
  opened. Opening converts no gizmos or lights (Asobo's automatic gizmo replacement on load and Append is off);
  materials follow EXP-004.
- **Decision:** CONV S4 design 2 and 3
- **Test:** no test

### EXP-003: MSFS 2020 export

- **Status:** implemented
- **Requirement:** With the target MSFS 2020, the plain glTF exporter writes MSFS 2020 glTF. Materials are exported
  with, for the export only, the node setup the MSFS 2020 add-on would build from the same values; afterwards the
  artist's materials are unchanged. A material type that MSFS 2020 lacks is exported as a standard material and the
  MSFS 2020 Material Parameters panel says so. The multi-exporter writes MSFS 2024 glTF only; the Export Target
  panel says that MSFS 2020 is exported with File > Export > glTF 2.0.
- **Decision:** CONV S3 (MSFS 2020 parity with the production add-on); CONV S4 design 4
- **Test:** harness: `tests/run_tests.py --sim 2020 --ref-repo <msfs2020 fork>` (cases materials, hierarchy,
  lights, gizmos, skinning, vertex data)
- **Code:** `msfs2020_target.py`, `io/exp/gltf_exporter_patches.py`
- **Notes:** NOT TESTED: that the artist's materials are unchanged after an MSFS 2020 export.

## Materials

### EXP-004: Material values with MSFS 2024 meaning; one-time migration

- **Status:** implemented
- **Requirement:** Material values in the `.blend` have their MSFS 2024 meaning. A material made with the MSFS 2020
  add-on is converted once, automatically, when the file is opened, when it is appended, and before an export: its
  values are kept with MSFS 2024 meaning and the MSFS 2024 node tree is built from them. Emissive brightness is
  stored in cd/m²; an MSFS 2020 export divides it by the emissive reference, which is the scene's
  `msfs_fss_msfs2020_emissive_reference` when set (converted scenes save the reference they were converted with),
  else the add-on preference. The reference is shown in the Export Target panel while the target is MSFS 2020.
- **Data:** DAT-046
- **Decision:** CONV S5.1, S5.2; CONV S6.4
- **Test:** no test
- **Code:** `migration.py`, `msfs2020_target.py`

### EXP-012: Ghost material ranges converted

- **Status:** wish
- **Requirement:** `msfs_ghost_bias` and `msfs_ghost_power` are converted between the MSFS 2020 and MSFS 2024 value
  ranges, which are swapped between the simulators.
- **Decision:** none recorded (Known Issue of the exporter guide)
- **Test:** no test

## One File for Both Simulators

### EXP-005: Export For

- **Status:** implemented
- **Requirement:** Every object has Export For: All Targets (default), MSFS 2024 Only or MSFS 2020 Only. An object
  marked for one simulator is skipped by the other's export, with its subtree as the glTF exporter's filter does.
  Independently of it, an MSFS 2020 export skips MSFS 2024 collision gizmos and an MSFS 2024 export skips legacy
  MSFS 2020 gizmo empties. No panel shows the field; Prepare for MSFS 2024 sets it.
- **Data:** DAT-046
- **Decision:** CONV S4 design 5
- **Test:** harness: case gizmos (each target exports only its own gizmos)
- **Code:** `msfs2020_target.py`
- **Notes:** NOT TESTED: the Export For filter itself.

### EXP-006: Prepare for MSFS 2024

- **Status:** implemented
- **Requirement:** The Export Target panel shows Prepare for MSFS 2024 while the file has legacy MSFS 2020 collision
  gizmos or lights without an MSFS 2024 counterpart. It adds an MSFS 2024 collision gizmo next to every legacy gizmo
  empty (named `<empty name>_2024`) and an MSFS 2024 light next to every legacy light (Asobo's light conversion),
  marks the originals MSFS 2020 Only and the new objects MSFS 2024 Only, and removes nothing, so the MSFS 2020
  export stays the same.
- **Decision:** CONV S4 design 5
- **Test:** no test
- **Code:** `ui/prepare_msfs2024.py`

## Geometry

### EXP-007: Blender 3.6 normals for old files

- **Status:** implemented
- **Requirement:** When a file is opened, each mesh's Auto Smooth setting as saved by Blender 4.0 or older is read
  from the file on disk and kept on the mesh (DAT-046), so it survives saving. The Export Target panel reports
  affected meshes, and objects whose Auto Smooth modifier is not where Blender 3.6 applied Auto Smooth. Restore
  Blender 3.6 Normals (with confirmation) stores the normals Blender 3.6 showed as custom normals on meshes that had
  Auto Smooth off, removes their Weighted Normal modifiers, and moves misplaced Auto Smooth modifiers before the
  first enabled Weighted Normal or Normal Edit modifier, otherwise to the end of the stack.
- **Data:** DAT-046
- **Decision:** CONV S3 (legacy normals inside Blender 5.2); CONV S5.3; CONV S6.3
- **Test:** no test
- **Code:** `legacy_normals.py`

### EXP-008: Instancing with Auto Smooth

- **Status:** implemented
- **Requirement:** A mesh shared by several objects is exported once, with every object referring to it, also when
  each user's only modifier is Auto Smooth, enabled in the viewport, with the same angle on all users, provided every
  user is exported and the mesh has no shape keys, no custom normals and is not linked from a library. Any other
  modifier gives each user its own copy.
- **Decision:** LOD 23 (instancing kept on trimmed meshes); none recorded for the Auto Smooth rule (CONV Session 12)
- **Test:** no test
- **Code:** `instancing.py`

### EXP-009: Clean-up on export

- **Status:** implemented
- **Requirement:** The MSFS 2024 multi-exporter exports objects left in NLA tweak mode as if tweak mode were off and
  restores tweak mode afterwards, and switches objects in Edit or Pose Mode to Object Mode for the export.
- **Decision:** none recorded (CONV Session 12)
- **Test:** no test
- **Code:** `io/exp/multi_export.py` (marked FSS spots)

### EXP-011: Two UV maps

- **Status:** implemented
- **Requirement:** At most two UV maps per mesh are exported.
- **Decision:** Asobo design
- **Test:** harness: case vertex_data

## Workflow

### EXP-010: Asobo export workflow hidden

- **Status:** implemented
- **Requirement:** By default the Multi-Export glTF 2.0 panel shows only its settings, with the note that FSS
  deploys use them; the Hierarchy tab, the Export button and the Logs are hidden, as are the settings the deploy
  always overrides (MSFS extension, lights, apply modifiers, animation mode and sampling, texture library and
  folder). The LOD Tools panel is hidden. The preference Show Asobo export workflow shows everything as Asobo ships
  it. The settings stay in the `.blend` and are used by MSFS 2024 deploys.
- **Data:** DAT-046
- **Decision:** LOD 20
- **Test:** no test
- **Code:** `fss_workflow_ui.py`
- **Notes:** the LOD Tools panel is hidden by a timer after start-up; enabling the LOD Tools add-on later shows it
  until the next start (LOD journal Session 9).

### EXP-013: Hooks for fss_blender_tools

- **Status:** implemented
- **Requirement:** The exporter calls the glTF export hooks of fss_blender_tools in both the plain exporter and the
  multi-exporter: `pre_export_hook` before objects are collected (merge, LOD culling and padding act there), and
  the node, mesh, material and scene hooks (name stripping, DAT-042; extras stripping, DAT-040).
- **Decision:** TM S1.6
- **Test:** `tests/test_markers.py::test_export_hooks`
- **Code:** `io/exp/multi_export.py` (marked FSS spots); `fss_blender_tools/merge.py`
