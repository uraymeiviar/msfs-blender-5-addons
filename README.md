# MSFS Blender Add-ons for Blender 5.2 (FSS unified)

One Blender 5.2 install that exports glTF for **Microsoft Flight Simulator 2024 and 2020**, chosen per scene.

Built from the Asobo MSFS 2024 Blender toolset (data model, UI, gizmos, LOD tools, multi-exporter) plus the
FSS production MSFS 2020 exporter, both ported to Blender 5.2:

- MSFS 2024 fork: <https://github.com/uraymeiviar/msfs2024-blender-addons>
- MSFS 2020 fork: <https://github.com/uraymeiviar/msfs2020-blender-addons>

## Add-ons

| Folder | Add-on | Notes |
| :--- | :--- | :--- |
| `io_scene_gltf2_msfs_fss` | Microsoft Flight Simulator 2020 + 2024: glTF Extension (FSS) | Replaces both `io_scene_gltf2_msfs_2024` and `io_scene_gltf2_msfs_2020`; do not enable those at the same time |
| `_addons_common` | Shared Asobo utilities | Required, not an add-on itself |
| `lod_tools_msfs_2024` | LOD Tools | Uses `io_scene_gltf2_msfs_fss` |
| `wipermask_generator_msfs_2024` | Wiper Mask Generator | |
| `max_bridge_msfs_2024` | 3ds Max Bridge | |

Install: copy the folders into a Blender scripts `addons` directory (or point Blender's script directory at a
folder containing them) and enable **Microsoft Flight Simulator 2020 + 2024: glTF Extension (FSS)**.

## Export target

`Scene.msfs_fss_export_target` (`MSFS2024` / `MSFS2020`) decides what a glTF export writes:

| | MSFS 2024 | MSFS 2020 |
| :--- | :--- | :--- |
| Export path | MSFS 2024 multi-exporter (as Asobo) | `File > Export > glTF 2.0` / script export, FSS production arguments |
| glTF hooks | MSFS 2024 extensions | MSFS 2020 extensions (FSS production add-on v3.3.1 + Asobo 3.3.2 additions) |
| Khronos patches | Asobo MSFS 2024 patches | FSS 2020 parity patches (no neutral bone, MSFS base color slot only) |
| Collision gizmos | Geometry nodes gizmos | Legacy gizmo empties (`msfs_gizmo_type`) |

New scenes default to MSFS 2024. Scenes without an explicit target that carry MSFS 2020 data (2020 export
settings, legacy gizmos or lights, materials with an MSFS 2020 preview node tree) are set to MSFS 2020 when the
file is loaded. Nothing is converted automatically: legacy gizmos and node trees stay as they are, so one file
can be exported for both simulators.

UI: the target is in the 3D View sidebar (*Microsoft Flight Simulator 2024 Tools > Export Target*) and in the
*File > Export > glTF 2.0* dialog. While a scene targets MSFS 2020, *MSFS 2020 Object Parameters* (legacy
collision gizmo, light flash settings) and *MSFS 2020 Material Parameters* (MSFS 2020-only material values)
panels appear in the Properties editor.

### One file, both simulators

- **Export For** (`Object.msfs_fss_export_only`: All / MSFS 2024 Only / MSFS 2020 Only) limits an object to
  one simulator. Independently, MSFS 2020 exports skip MSFS 2024 geometry nodes gizmos and MSFS 2024 exports
  skip legacy gizmo empties.
- **Prepare for MSFS 2024** (Export Target panel) adds an MSFS 2024 collision gizmo next to every legacy gizmo
  empty and an MSFS 2024 street light next to every legacy light (Asobo's light mapping), marks the originals
  MSFS 2020 Only and the new objects MSFS 2024 Only. Nothing is removed; the MSFS 2020 export is unchanged.
- Materials: an MSFS 2020 export reads the standard glTF fields from the MSFS 2020 preview node tree. Materials
  carrying the MSFS 2024 tree get the tree the MSFS 2020 add-on builds from the same properties for the
  duration of the export; afterwards every user is remapped to an untouched copy of the material.

FSS production script arguments on Blender 5.2 (versus `scripts/export-blend-to-gltf.py` on Blender 3.6):

```python
bpy.ops.export_scene.gltf(
    filepath=out_path,
    export_format="GLTF_SEPARATE",
    use_visible=True,
    export_image_format="AUTO",
    export_force_sampling=False,
    export_apply=True,
    export_rest_position_armature=True,
    export_vertex_color="ACTIVE",          # 3.6: export_colors=True
    export_merge_animation="NLA_TRACK",    # 3.6 behaviour; the 5.x default merges animations by action
    export_animation_mode="ACTIONS",
    export_reset_pose_bones=True,
    export_copyright="FlightSimStudio",
)
```

## How MSFS 2020 lives inside the MSFS 2024 add-on

- `io_scene_gltf2_msfs_fss/_msfs2020/` holds the MSFS 2020 exporter code. It has no `__init__.py` on purpose:
  the Asobo registration only discovers regular packages, so none of its panels or operators are registered.
- The MSFS 2020 code registered its properties as an import side effect; those statements were rewritten to
  fill `_msfs2020/legacy_props.py` instead. `msfs2020_target.py` registers only the 26 properties MSFS 2024 does
  not define.
- Both add-ons store material settings under the same names, but `msfs_material_type` items and a few defaults
  differ (e.g. `msfs_emissive_scale` 1.0 vs 1000.0). `_msfs2020/compat.py` presents materials to the MSFS 2020
  export code with MSFS 2020 type names and defaults for values the artist never set.
- MSFS 2024 behaviour that would change MSFS 2020 output is limited to MSFS 2024 scenes: automatic legacy
  gizmo replacement (on load and after Append) is off, the MSFS 2024 node graph rebuild on load is skipped while
  a scene targets MSFS 2020, the default white color attribute is not added to MSFS 2020 scenes, and the
  Asobo Khronos patches step aside for MSFS 2020 exports.

## Tests

Differential harness in `tests/` (see `tests/README.md`):

```bash
# unified add-on vs the per-simulator forks, Blender 5.2
python tests/run_tests.py --sim 2024 --ref-repo H:/git-repos/msfs2024-blender-5.2.x-addons --ref 5.2
python tests/run_tests.py --sim 2020 --ref-repo H:/git-repos/msfs2020-blender-5.2.x-addons --ref 5.2
```

## Status

- MSFS 2024: identical to the MSFS 2024 fork on every harness case.
- MSFS 2020: identical to the MSFS 2020 fork on every harness case (including materials authored with the MSFS
  2024 node tree). `assets/visual/cockpit/Cockpit.blend` (E195), opened for the first time (35 materials
  migrated), versus the FSS production Blender 3.6 export: only legacy normals, the Asobo 3.3.2 `alphaMode`
  addition and the emissive factor of 2 invisible collider materials (graph recreated, never rendered) differ.

## Material values: MSFS 2024 meaning

The .blend stores MSFS 2024 meaning; MSFS 2020 exports convert:

- `msfs_emissive_scale` is a brightness in cd/m2. MSFS 2020 exports divide it by
  `Scene.msfs_fss_msfs2020_emissive_reference` (*Emissive 1.0 (cd/m2)*, default 1000) in the export dialog and
  the Export Target panel.
- Materials authored with the MSFS 2020 add-on (MSFS 2020 preview node tree) are migrated once, on load, after
  Append and before any export (`migration.py`): values whose default differs are stored explicitly with the
  MSFS 2020 default, the emissive scale is multiplied by the reference, the MSFS 2024 graph is rebuilt and the
  material is marked `msfs_fss_migrated_from_msfs2020`.
- Graph rebuilds that are not an artist action keep every stored value (Asobo's builders reset properties the
  MSFS 2024 type does not use; MSFS 2020 exports still read some of them).

## Known issues

- `msfs_ghost_bias` / `msfs_ghost_power` have swapped ranges between the add-ons, which suggests swapped meaning;
  not converted yet (ghost materials only).
- Legacy normals migration tool (pre-4.1 Auto Smooth semantics) not written yet.
- Panels are verified to register; their drawing needs a manual check in the UI.
