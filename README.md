# MSFS Blender Add-ons for Blender 5.2 (FSS unified)

One Blender 5.2 install that exports glTF for **Microsoft Flight Simulator 2024 and 2020**, chosen per scene.

Built from the Asobo MSFS 2024 Blender toolset (data model, UI, gizmos, LOD tools, multi-exporter) plus the
FSS production MSFS 2020 exporter, both ported to Blender 5.2:

- MSFS 2024 fork: <https://github.com/uraymeiviar/msfs2024-blender-addons> — Asobo exporter **8.4.1**
  (SDK 1.8.1 Flighting, which supports Blender 5.2 itself) plus a fix for exports without Perforce installed;
  the `upstream` branch holds the vanilla Asobo versions
- MSFS 2020 fork: <https://github.com/uraymeiviar/msfs2020-blender-addons>

## Documentation

| For | Where |
| :--- | :--- |
| Artists: how to use the panels and the exporter | [docs/user/](docs/user/README.md) (also deployed into each aircraft repository's `tools/blender/docs/`) |
| Developers and agents: working rules | [AGENTS.md](AGENTS.md) |
| Developers and agents: design, decisions, progress | [docs/journal/](docs/journal/README.md) |
| Developers: design of the FSS tools | [fss_blender_tools/README.md](fss_blender_tools/README.md) |

The sections below are developer notes on the exporter; the artist-facing behaviour (export target, one file for both
simulators, materials, legacy normals, instancing) is described in [docs/user/exporter.md](docs/user/exporter.md).

## Add-ons

| Folder | Add-on | Notes |
| :--- | :--- | :--- |
| `io_scene_gltf2_msfs_fss` | Microsoft Flight Simulator 2020 + 2024: glTF Extension (FSS) | Replaces both `io_scene_gltf2_msfs_2024` and `io_scene_gltf2_msfs_2020`; do not enable those at the same time |
| `_addons_common` | Shared Asobo utilities | Required, not an add-on itself |
| `lod_tools_msfs_2024` | LOD Tools | Uses `io_scene_gltf2_msfs_fss` |
| `wipermask_generator_msfs_2024` | Wiper Mask Generator | |
| `max_bridge_msfs_2024` | 3ds Max Bridge | |
| `fss_blender_tools` | FSS Blender Tools | FSS authoring tools (Tools, Empty Bounds, LOD with automatic LOD export, Tags, Zones & Merge Tree, UV Marks, Auto Seam, Heatmap, Visibility Test, Checks); independent of the Asobo add-ons and `_addons_common` |

Install: copy the folders into a Blender scripts `addons` directory (or point Blender's script directory at a
folder containing them) and enable **Microsoft Flight Simulator 2020 + 2024: glTF Extension (FSS)**.

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

## MSFS 2020 script export arguments

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

## Known issues

- `msfs_ghost_bias` / `msfs_ghost_power` have swapped ranges between the add-ons, which suggests swapped meaning;
  not converted yet (ghost materials only).
- Two small cockpit meshes (`Cube`, `Cube.001`) export fewer duplicated vertices than Blender 3.6 (same shape).
- Panels were checked once in the UI; the Restore Normals box needs a manual check.
