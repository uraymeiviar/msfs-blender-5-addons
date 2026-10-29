# Differential Test Harness

Exports identical, procedurally built scenes on two **sides** and diffs the output. A side is an add-on
repository plus a Blender version; `--sim` selects the simulator (MSFS 2024 or 2020) both sides export for.

```bash
# any Python 3.10+ works; Blender's bundled one is convenient
PY="C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe"
# unified add-on vs the per-simulator fork, both on Blender 5.2
$PY tests/run_tests.py --sim 2024 --ref-repo H:/git-repos/msfs2024-blender-5.2.x-addons --ref 5.2
$PY tests/run_tests.py --sim 2020 --ref-repo H:/git-repos/msfs2020-blender-5.2.x-addons --ref 5.2
# this repo on Blender 4.5 vs 5.2
$PY tests/run_tests.py --sim 2024 --case skinning
$PY tests/run_tests.py --target-only            # smoke test, no comparison
```

Blender installs are found at `%BLENDER_ROOT%\Blender <version>\blender.exe`
(default root `C:\Program Files\Blender Foundation`). Output goes to `tests/_work/` (git-ignored).
The add-ons are copied into a private `BLENDER_USER_SCRIPTS` per run, and Blender is started with
`--factory-startup`, so the local Blender setup is never touched.

## What a run does

For every case and both Blender versions, the scene is exported twice:

| Mode | Purpose |
| :--- | :--- |
| `msfs` | MSFS extension enabled: the artist's real export |
| `vanilla` | MSFS extension disabled: isolates changes coming from the bundled Khronos exporter |

A diff that also shows up between the two `vanilla` exports is tagged `[khronos]`; everything else is
attributed to the MSFS add-on. A run is also flagged as a problem when Blender printed a Python traceback
(property-update callbacks only print their errors, they never raise) or the MSFS logger recorded an error.

- **MSFS 2024**: drives the full artist path. Each case is parented under `<case>_LOD0`, LOD groups are
  discovered in `OBJECTS` mode and `msfs2024.multi_export_gltf` runs (object duplication, modifier apply,
  mesh merge, glTF export, model XML, texture XML).
- **MSFS 2020**: plain `export_scene.gltf` with the FSS production arguments (`scripts/export-blend-to-gltf.py`,
  mapped to Khronos 4.2+ option names). Scenes only use what the MSFS 2020 add-on can represent: MSFS 2020
  material types and names, gizmo empties, no MSFS 2024 light types; properties whose definition differs
  between the add-ons (`CONFLICTING_2020_2024` in `scenes.py`) are left unset.
- For the unified add-on the export target is set before a scene is built, like an artist would.

## Cases (`harness/scenes.py`)

| Case | Covers |
| :--- | :--- |
| `materials` | One mesh per MSFS material type; every texture slot bound to a generated image; scalar props set to stable non-defaults (node tree building and material extensions) |
| `skinning` | Two-bone skinned column with explicit weights, bone + object animation, animated shape key |
| `hierarchy` | Parenting with negative / non-uniform scale, quaternion rotation, constant interpolation, unique id override |
| `lights` | Every Blender light type, MSFS light properties / types |
| `gizmos` | Every collision gizmo type (2024: created by `msfs2024.add_gizmo`) |
| `vertex_data` | Two UV maps, color attribute, sharp edges + smooth shading, mirror + bevel modifiers |

Animations are moved into NLA tracks before export, because the MSFS presets export with
`export_animation_mode = NLA_TRACKS`.

## Comparison (`harness/compare.py`)

Index references are resolved into an order-independent tree: nodes keyed by name, primitives turned into a
sorted multiset of triangles (every vertex attribute, joints mapped to joint names, morph deltas), texture
references inlined as image file names. Floats compare with `1e-4` tolerance. It can be used standalone:

```bash
python tests/harness/compare.py ref.gltf new.gltf
```

## Reference versions

- MSFS 2024: Blender **4.5 LTS** (the add-on's newest version branch, which 5.x inherits).
- MSFS 2020: Blender **4.5 LTS** as well. Blender 3.6 is a poor reference for material textures: Khronos 3.6
  caches texture info keyed on socket objects, and the add-on's temporary shader nodes reuse freed sockets,
  so 3.6 itself exports stale texture references (`--ref 3.6` shows these as diffs).

## Unit Suites of fss_blender_tools

Background-Blender scripts that build synthetic scenes, purge the add-on copy deployed in the portable Blender (`5.2/scripts/addons_core`), import this repository's `fss_blender_tools` and print `PASS:` lines and a final `ALL ... PASSED`. Run from the repository root, one Blender at a time:

```powershell
$B = "G:\e-jets-e2\tools\blender\blender.exe"
& $B -b --factory-startup --python tests/test_uv_pack.py
```

| Suite | Covers |
| :--- | :--- |
| `tests/test_uv_pack.py` | the packer: density per island, fit, underflow, overflow and needed size, directions, linked duplicates, Pack and Check All, Keep UVs, faces without 3D or UV area, the texture set list, the UV editor panel, report order |
| `tests/test_density_marks.py` | density marks multiplying down the hierarchy, scene freedom, presets, migration of older files, the UV Auto Packing chain drawn, visibility floor, heatmap refresh after a mark change |
| `tests/test_panels.py` | the sidebar layout (both tabs and the UV editor): every panel's label, parent, order and tab, the FSS Tools panels closed by default, every panel drawn; Object LOD (selection line, mixed marks, the pending Hidden from / Visible from choice, the Visible in row, drawing writes nothing); Viewport LOD (the Excluded row only with a preview); LOD Settings (count bars, the quota table, contributor bars, one exterior diameter message, the Pad LOD Sphere To line) |
| `tests/test_zone_tree.py` | Zones & Merge Tree rows and flags, zone marks, nearest zone, no `fss_` key in the glTF extras |
| `tests/test_materials.py` | the Materials panel: Refresh rows (never used, shared across zones, hidden users, shared meshes, area per zone, the estimate with and without a `.visibility` file), kind marks with and without the exporter, the select operators, panels drawn without writing, Keep UVs in the active material box (kept instead of the estimate, without Refresh), no `fss_` key in the glTF extras, refresh on opening a file (Zones & Merge Tree, Materials and Scan Names; nothing scheduled in background) |
| `tests/test_markers.py` | leading `@` stripped at export, Scan Names markers and the Clash rule |
| `tests/test_lod_preview.py` | LOD viewport preview (hidden and bounds), save and load handlers |
| `tests/uv_prototype/test_visibility.py` | Visibility Scoring: synthetic cases, operator, scene unchanged, heatmap mode, glTF leak, packer interface |
| `tests/uv_prototype/test_autoseam_operators.py` | Auto Seam operators: propose, accept, Accept + Unwrap, discard, clear, progress, buttons |
| `tests/uv_prototype/test_uv_heatmap.py` | the heatmap: distortion, density, visibility modes, display takeover, chart, grid |

Without Blender: `python -m unittest tests.test_lod_rules` (LOD rules), and `tests/uv_prototype/test_uvmetrics_shape.py` (see its header). A traceback about `ImagePreviewCollection ... left open` at start-up comes from purging the deployed copy and is harmless. Prototype scripts and real-data runs are described in [uv_prototype/RUN.md](uv_prototype/RUN.md).
