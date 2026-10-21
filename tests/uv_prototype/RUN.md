# UV prototype, round 3: how to reproduce `results3\`

Research prototype only (round 3 of [docs/journal/20261019.automated-uv-unwrap.md](../../docs/journal/20261019.automated-uv-unwrap.md)).

**Copy this folder to a scratch location before running it** (the original runs used a folder named `uvproto\`): the scripts write their outputs (`results3\`, `work3.blend`, `venv\`, `.npz`, `.png`) next to themselves, which must never happen inside the repository. Every relative path below is relative to that copy.

Only the round-3 script set is kept here; the obsolete scripts mentioned below (v1, `prep.py`, `prep2.py`, `evaluate.py`, `evaluate2.py`, `list_objs.py`, `ovdiag.py`, `patch_v3*.py`, `ringframe_block.py`) are not in the repository.

## 1. Script set

Current set for round 3:

| file | runs in | role |
| :--- | :--- | :--- |
| `list_seams3.py` | Blender | survey: artist seams per object, does UVMap[0] split at them (`seams3.json`) |
| `prep3.py` | Blender | builds `work3.blend` (evaluated, world-space, triangulated copies + edge attributes) |
| `proto_blender_v3.py` | Blender | proto3 + smart66 + `existing` export + `__seams.npy` / `__nsplit_T.npy` |
| `proto_blender_v2.py` | Blender | proto2 reference **and** `__splitmesh.npz`, which `xatlas_run.py` needs |
| `xatlas_run.py` | venv | xatlas on plain mesh (`xatlas`) and on mesh split at proto2 cuts (`xatlascut`) |
| `repack_blender.py` | Blender | loads xatlas UVs, Average Islands Scale + Pack Islands (`*_bpack`) |
| `evaluate3.py` | venv | all metrics + PNGs (`metrics.json`, `png\`) |
| `evaluate3_extra.py` | venv | imported by `evaluate3.py`: artist-seam crossing/following, texel density |
| `uvmetrics.py` | both | numpy metrics, imported by the Blender scripts and by the evaluators |
| `pack_grid.py` | venv / both | Phase 3 packing prototype: density scaling, directional rotation, stacking, coarse-to-fine FFT/skyline nesting, comparisons |

Not needed for round 3, keep only for history: `proto_blender.py` (v1), `prep.py`, `prep2.py`,
`evaluate.py`, `evaluate2.py` (`evaluate3.py` is a generated copy of it and no longer imports it),
`list_objs.py`, `ovdiag.py`, and `patch_v3.py`, `patch_v3b.py`, `patch_v3c.py`, `ringframe_block.py`
(all already folded into `proto_blender_v3.py`; do not re-run them, they patch the file in place).

Note: the header comment of `proto_blender_v3.py` still shows the v2 usage line; ignore it.

## 2. Commands, in order

Working directory for every command: `uvproto\`. Blender: `G:\e-jets-e2\tools\blender\blender.exe`
(5.2.2 LTS), background only, one Blender process at a time. Blender scripts run on Blender's own
bundled Python (numpy comes with Blender); `xatlas_run.py` and `evaluate3.py` run on the venv
(`venv\Scripts\python.exe -I`). Shell syntax below is Git Bash.

```bash
B=/g/e-jets-e2/tools/blender/blender.exe
O='W_AUDIO_L_VOLUME_KNOB,W_TRIM_PANEL,W_LEVER_FLAP_LOCK,W_@MERGE_PEDESTAL_SHELL,W_COCKPIT_SHELL_L,W_COCKPIT_SHELL_FLOOR,W_OVERHEAD_SHELL'

# 0. copy the source (never open the original)
cp "C:/Users/uray/Downloads/E2_190_COCKPIT2.blend" E2_COCKPIT2_copy.blend

# 1. survey (optional, writes seams3.json)
$B -b E2_COCKPIT2_copy.blend --python list_seams3.py

# 2. prep -> work3.blend, objects_info3.json   (object names WITHOUT the W_ prefix)
$B -b E2_COCKPIT2_copy.blend --python prep3.py -- AUDIO_L_VOLUME_KNOB TRIM_PANEL LEVER_FLAP_LOCK \
   @MERGE_PEDESTAL_SHELL COCKPIT_SHELL_L COCKPIT_SHELL_FLOOR OVERHEAD_SHELL

# 3. proto3 + smart66 (+ existing, seams, nsplit exports). --out is required: the default is results2
$B -b work3.blend --python proto_blender_v3.py -- --objects $O --out results3

# 4. proto2 reference + splitmesh (needed by step 5)
$B -b work3.blend --python proto_blender_v2.py -- --objects $O --out results3 --skip_smart 1

# 5. xatlas (venv)
./venv/Scripts/python.exe -I xatlas_run.py results3 < /dev/null

# 6. Blender repack of xatlas charts (positional args: out dir, object list)
$B -b work3.blend --python repack_blender.py -- results3 $O

# 7. metrics + PNGs (venv), about 8 minutes
./venv/Scripts/python.exe -I evaluate3.py results3 < /dev/null
```

`evaluate3.py results3 m1,m2` re-evaluates only those methods (plus `existing`) and merges them into
the existing `metrics.json`.

History (not needed to reproduce): `results3\` was produced by step 3 once, then proto3 was re-run
twice with `--skip_smart 1` after the repair step was patched (logs `log_r3b.txt`, `log_r3c.txt`),
and `evaluate3.py` was run in full once, then with method filters. One step-3 run with the final
`proto_blender_v3.py` gives the same proto3 inputs, since no time budget was hit (`budget_hit`
false in the logs).

## 3. venv

```bash
python -m venv venv                 # system Python (Anaconda), venv Python is 3.13.9
./venv/Scripts/python.exe -I -m pip install xatlas numpy scipy matplotlib
```

Versions installed (`pip freeze`): xatlas 0.0.11, numpy 2.5.4, scipy 1.18.1, matplotlib 3.11.2
(plus its dependencies contourpy 1.4.0, cycler 0.12.1, fonttools 4.67.0, kiwisolver 1.5.1,
packaging 26.3, pillow 13.0.0, pyparsing 3.3.3, python-dateutil 2.9.0.post0, six 1.17.0).
trimesh is not installed and not used. Nothing is installed into Blender's Python.

## 4. proto3 parameters

All command-line overridable via `--name value`; defaults are in the `A = dict(...)` at the top of
`proto_blender_v3.py` (lines 13-15). Hard-coded constants are listed with where they are.

| parameter | value | meaning |
| :--- | :--- | :--- |
| `soft` | 30 deg | dihedral angle above which an edge is a soft seed cut |
| `thr` | 1.25 | max mean area distortion (PartUV measure) for any accepted trial |
| `method` | ANGLE_BASED | `bpy.ops.uv.unwrap` method for trials and final unwrap |
| `min_split` | 12 | seed charts with fewer faces are not checked for box split |
| `tries` | 4 | neighbours tried per chart in the merge pass (strip pass tries all) |
| `strip_k` | 0.0075 | strip if area / perimeter^2 < this ... |
| `strip_area` | 0.001 | ... or area < this fraction of object area |
| `worst` | 2.0 | per-chart max face distortion that triggers the worst-triangle pass |
| `ms_iter` | 50 | `minimize_stretch` iterations in the worst pass |
| `fill_min` | 0.5 | ring/frame pass only for charts with fill (uv area / min-area rectangle) below this |
| `fill_gain` | 1.25 | ring/frame cut kept only if fill improves by this factor |
| `margin` | 0.004 | pack margin, `margin_method='FRACTION'` |
| `budget` | 600 s | merge stops at budget; strips 1.5x, worst pass 2x, ring/frame 2.5x (of time since start) |
| `forced_seams` / `forced_nsplit` | 1 / 0 | artist seams forced, shading splits not forced |
| `skip_smart`, `only_smart`, `tag`, `out`, `objects` | 0, 0, proto3, results2 (!), '' | run control |

Hard-coded in `proto_blender_v3.py`:

- forced cuts (`forced_flags_bm`): border / non-manifold edges, `fss_seam` edges, material borders
- smoothing: 5 iterations; re-verify at most 4 rounds, then full revert
- final-vs-trial mismatch: |d - d_trial| > 1% of d_trial, or an overlap
- repair: projection without box split if all normals have dot > 0.05 with the mean normal; at most one sub-split level
- ring/frame pass: charts with >= 8 faces and >= 6 boundary edges; k=1 cut and k=4 corner cuts; pieces need d <= thr, no overlap, max <= max(1.1 x old max, `worst`)
- unwrap: `fill_holes=False, correct_aspect=True, margin=0`
- pack (`pack()`): `average_islands_scale()`, then `pack_islands(udim_source='CLOSEST_UDIM', rotate=True, rotate_method='ANY', scale=True, merge_overlap=False, margin_method='FRACTION', margin=0.004, pin=False, shape_method='CONCAVE')`
- smart66: `smart_project(angle_limit=66 deg, island_margin=0, area_weight=0, correct_aspect=True, scale_to_bounds=False)` after clearing all seams, then the same `pack()`

Other scripts:

- `prep3.py`: shading-split tolerance 1 deg between corner normals across an edge
- `repack_blender.py`: same average + pack settings as `pack()`, margin 0.004
- `xatlas_run.py`: default `ChartOptions` / `PackOptions`; UVs rescaled by width/height so the aspect is kept
- `uvmetrics.overlap_pairs`: tolerance `eps_rel=1e-6` x UV extent

## 5. Files

`prep3.py` writes `work3.blend` (next to the opened blend), containing only objects `W_<name>`
with modifiers applied, world transform baked in, triangulated, and INT edge attributes
`fss_nsplit` (corner normals differ by more than 1 deg across the edge) and `fss_seam` (artist
seam). It also writes `objects_info3.json` in the working directory (counts per object).

Per object `W_<name>`, in `results3\`:

- `<obj>__<method>.npz` for methods `existing`, `proto3`, `proto2`, `smart66`, `xatlas`, `xatlascut`, `xatlas_bpack`, `xatlascut_bpack`. Arrays: `P` (V,3) vertex positions in metres; `T` (F,3) triangle vertex indices; `UV` (F,3,2) per-corner UVs; `mat` (F) material index; `extra` (JSON string: stats and timings of that method).
- `<obj>__seams.npy` (k,2): artist-seam edges as vertex pairs (from step 3)
- `<obj>__nsplit_T.npy` (F,3): per-corner vertex id after splitting at shading splits (steps 3 and 6)
- `<obj>__splitmesh.npz` (`Ps`, `Ts`, `orig`): mesh split at proto2's forced cuts (step 4)
- `blender_log_<tag>_<unixtime>.json`: per-object stats of each Blender run (counts, stage times)
- `metrics.json`: one row per object x method
- `png\<obj>__<method>.png`: UV layout, islands coloured, overlapping triangles outlined red
- `table.md`: built ad hoc from `metrics.json` by an inline command, not by a script

Metric definitions (`uvmetrics.py`, `evaluate3.py`, `evaluate3_extra.py`):

- **Area distortion (`area_distortion`)**: per triangle, (UV area / 3D area) / (total UV / total 3D), mirrored to >= 1. Mean and max are over triangles with nonzero area; zero-UV-area triangles are reported separately. This is PartUV `calculate_distortion_area`.
- **Angle distortion (`angle_distortion`)**: mean absolute difference between corner angles in 3D and in UV, in degrees.
- **Overlaps (`overlap_pairs`, `flipped_count`)**: triangle pairs whose UV interiors intersect, found with a grid broad phase and a 2D separating-axis test with tolerance, so touching neighbours do not count. Flipped triangles are the minority winding within an island.
- **Islands, seams, extra vertices**: a split vertex is a (3D vertex, exact UV) pair. Islands are triangles connected through shared split edges. Seam length is the summed length of 3D edges whose sides have different split edges. extraV = split vertices minus 3D vertices; ">N" = unique (shading-split vertex, UV) minus shading-split vertices.
- **Packing efficiency (`uv_area`)**: summed UV area, valid as packing efficiency only when the UVs lie in 0..1 and do not overlap.
- **Artist seams (`evaluate3_extra.artist_texel`)**: crossed = manifold artist-seam edge with continuous UVs. Stubs = seam edges removed by iteratively pruning interior seam-degree-1 tips. An island follows the seams if it is not crossed and has no UV split off the artist seams.
- **Texel density**: per island, UV area / 3D area. Reported as max/min, p95/p5, and area-weighted coefficient of variation.

## 6. Hard-coded paths and assumptions

- `C:\Users\uray\Downloads\E2_190_COCKPIT2.blend` (source, copy step only) and `G:\e-jets-e2\tools\blender\blender.exe` appear only in the commands above, not in the scripts.
- Scripts locate `uvmetrics.py` / `evaluate3_extra.py` via their own folder (`HERE`). Output folders (`--out`, positional `results3`) are taken relative to the script folder, not the working directory.
- `prep3.py` writes `objects_info3.json` to the working directory and `work3.blend` next to the opened blend (`//work3.blend`). `list_seams3.py` writes `seams3.json` to the working directory.
- `proto_blender_v3.py` defaults `--out` to `results2`: always pass `--out results3`.
- Object names: `prep3.py` takes source names; all later steps expect the `W_` prefix it adds.
- `xatlas_run.py` requires `__splitmesh.npz` from the `proto_blender_v2.py` run. `repack_blender.py` requires both `__xatlas.npz` and `__xatlascut.npz`, and the `fss_nsplit` attribute in `work3.blend`.
- `evaluate3.py` skips any file whose name contains `splitmesh` or `xatlascut` (so `xatlascut_bpack` is not evaluated). It takes P/T from the first npz of each object; every method must share the same triangulation.
- The Blender scripts assume Blender 5.2 operator signatures (`unwrap` method `MINIMUM_STRETCH` / `margin_method`, `pack_islands(shape_method=...)`, `Mesh.corner_normals`) and the UV select sync toggle.

## 7. Round 4 auto-seam experiments

`proto_blender_v4.py` is an opt-in research harness derived from round 3. It is
not an installed add-on and does not save a `.blend`. Copy it with the baseline
helpers into `tests/_work/uv_prototype/` before running. Use the same `work3.blend`,
venv, Blender executable, seven objects and evaluator as above. No packages are
installed into Blender. No external algorithm source was copied.

Independent switches (each takes `0` or `1`, default `0`):

| Switch | Experiment | Limits |
| :--- | :--- | :--- |
| `--tree 1` | Binary normal-cluster tree inside loose/forced-cut components; compare verified parent against child chart count; centroid median breaks normal ties | Parent trials capped by `--tree_faces 512`; this is bounded tree search, not a global optimum. Baseline strip absorption remains after the tree. |
| `--visibility 1` | Length weighted by three-ray outward AO, signed concavity and edge-chain continuation; expensive cuts are preferred for merging away | AO is object self-occlusion, not visibility from pilot cameras. It cannot measure actual cockpit back sides or scene occluders. |
| `--borders 1` | Replace local two-edge boundary paths by a lower-cost path weighted by collinear continuation; baseline unwrap/overlap re-verification remains | Local triangle moves, not arbitrary global seam rerouting; triangulated edge chains approximate original loops. |
| `--strips 1` | Increase trial mean-distortion allowance by up to 0.10 as strip area decreases below `strip_area` of total object area | Artist/material cuts remain forced. Final acceptance must still use the object-level pass criteria. |
| `--frames 1` | Add paths from every inner boundary to the largest boundary with turn/continuation penalties; try one, two and four starts per hole | Reject candidates whose worst distortion exceeds the old chart's; not a guarantee that every lattice is decomposed. |

The baseline angle, worst-triangle repair, overlap predicate, density normalization,
and packing settings are retained. Flags can interact; a single passing case does
not validate a switch for other objects. Consult the appended journal results before
adopting any output. All switches remain off unless explicitly requested.

PowerShell example, from the scratch folder:

```powershell
$uvObjects = 'W_AUDIO_L_VOLUME_KNOB,W_TRIM_PANEL,W_LEVER_FLAP_LOCK,W_@MERGE_PEDESTAL_SHELL,W_COCKPIT_SHELL_L,W_COCKPIT_SHELL_FLOOR,W_OVERHEAD_SHELL'
if (Get-Process blender -ErrorAction SilentlyContinue) { throw 'Close Blender first' }
& 'G:\e-jets-e2\tools\blender\blender.exe' -b work3.blend --python-exit-code 1 --python proto_blender_v4.py -- --objects $uvObjects --out results3 --skip_smart 1 --tag tree --tree 1
& .\venv\Scripts\python.exe -I -u evaluate3.py results3 tree
```

Run each switch with its own tag, serially; never run another Blender alongside it.
Do not run evaluation concurrently with timed Blender benchmarks. The all-switch
combination adds `--tree 1 --visibility 1 --borders 1 --strips 1 --frames 1` and uses
`--tag all`. The `--tag` names are arbitrary evaluator method names.

`--phase benchmark` (default) explicitly creates a temporary UV map for measurement,
normalizes density and packs with the baseline packer. It exports the `.npz`, seam
proposal and stage log. This combined *benchmark* is not the eventual UI pipeline.

`--phase seams` skips packing, emits `<object>__<tag>_proposal.npy` (vertex pairs),
marks generated edges with the boolean `fss_auto_seam` attribute in memory, then
removes the temporary UV layer and asserts every original UV map is unchanged.
The scratch mesh's `fss_seam` attribute is the immutable artist mask; existing
automatic seams are replaced on rerun. No `.blend` is saved in either mode.
The seam-only log and timing are separate from benchmark timings.

This harness still requires `prep3.py`'s evaluated, triangulated, world-space
meshes for apples-to-apples baseline comparison. It does **not** validate the
future original-datablock/Mirror/Array workflow, scene-camera visibility, material
texture-set packing, or Substance Painter appearance.

Read strip counts as the counts immediately before/after strip absorption, before
later smoothing, repair and frame cuts. `extraV` in evaluator console text is
total UV splitting; use JSON `render_extra_vs_normals` for the 5% pass criterion.
Timings are single runs, not statistical performance guarantees. A smaller chart
distortion in the stage log is not the final packed global area-distortion metric.

## 8. Round 5 packing prototype (`pack_grid.py`)

> **Corrected on 20261019 (journal Session 16):** the Blender comparison now keeps islands intact, uses the same margin and packs into one square (`scale=True`); `GridPacker1Tile` is the grid packer in one square for comparison; coarse masks are max-pooled; oversized islands shrink the whole set uniformly. The Session 15 numbers are superseded.

`pack_grid.py` is the standalone research prototype for Phase 3 (packing across material texture sets),
implementing coarse-to-fine nesting, directional alignment, density scaling, and stacking units.

### Features
1. **Density Scaling:** Reads `pixels_per_metre` and per-object `density_factors` from JSON config (`pack_config.json`).
   Target UV area = `3D_area * (PPM / Resolution)^2 * density_factor`.
2. **Directional Constraint:** Objects marked as directional are restricted to rotations of 0° or 180° only.
3. **Stacking Units:** Identical islands from Mirror modifiers or shared mesh datablocks are grouped, packed as single
   units, and exempted from overlap penalties.
4. **Coarse-to-Fine Grid Packing:**
   - Half-margin dilation on rasterized island masks.
   - 2D FFT convolution for placing top concave islands into matching cavities.
   - Skyline packing with lowest-horizon cavity filling for small and medium islands.
5. **Overflow Handling:** Multi-tile mode (`--overflow tiles`) and uniform shrink mode (`--overflow scale`).
6. **Triple Comparison:** Compares GridPacker against Blender's native `pack_islands` (concave) and `xatlas`.
7. **Comprehensive Metrics:** Share of square, min distance, margin violations, SAT triangle overlaps, texel density
   deviation, directional rotation check, mip-level merge survival (levels 1-4), texture memory, and run time.

### Commands

Run in the venv from the prototype working directory (e.g. `tests/_work/uv_packing/`):

```powershell
# 1. Synthetic stacking unit verification
.\venv\Scripts\python.exe pack_grid.py --test_stacking

# 2. Benchmark runs across texture sets
# 4K @ 8px margin
.\venv\Scripts\python.exe pack_grid.py --resolution 4096 --margin 8 --overflow tiles --compare all --out pack_output_4096_8px

# 4K @ 4px margin
.\venv\Scripts\python.exe pack_grid.py --resolution 4096 --margin 4 --overflow tiles --compare all --out pack_output_4096_4px

# 8K @ 8px margin
.\venv\Scripts\python.exe pack_grid.py --resolution 8192 --margin 8 --overflow tiles --compare all --out pack_output_8192_8px

# 8K @ 16px margin
.\venv\Scripts\python.exe pack_grid.py --resolution 8192 --margin 16 --overflow tiles --compare all --out pack_output_8192_16px
```

### Options
- `--results`: Path to directory containing `W_*__proto3.npz` files (default `results3\`).
- `--config`: Path to packing configuration JSON (default `pack_config.json`).
- `--resolution`: 4096 or 8192 (default 4096).
- `--margin`: Margin in pixels, e.g. 4, 8, 16 (default 8).
- `--overflow`: `tiles` (UDIM/multi-tile) or `scale` (shrink to fit single tile).
- `--set`: Specific texture set name or `all` (default `all`).
- `--compare`: Methods to run: `all`, `grid`, `blender`, `xatlas`, or `none`.
- `--save_png`: Save UV layout visualization PNGs (default True).
- `--test_stacking`: Execute synthetic stacking unit assertion test.


## 9. Round 5 artist reference set (Package 2)

These ten additional objects supplement the original seven. Use the first UV layer,
unchanged, as `existing`; seam consistency is verified but UV aesthetic quality and
artist authorship are not certified. Reasons describe the intended coverage.

| Object | Triangles | UV islands | Interior artist seam edges | Selection reason |
| :--- | ---: | ---: | ---: | :--- |
| `B_GS_AFCS_AP_BUTTON` | 110 | 1 | 16 | Small button; single-chart control reference. |
| `CCD_LEFT_ROTARY_OUTER` | 1290 | 5 | 261 | Rotary control; curved control candidate with dense shading splits. |
| `CIRCUIT_BREAKER_COVER_L` | 889 | 5 | 100 | Panel/cover; test a larger cover with five charts. |
| `COCKPIT_REAR_OBS_SEAT_MOUNTING_FRAME` | 904 | 6 | 66 | Mounting frame; test long frame boundaries and multiple charts. |
| `DISC_HANDLE_AILERON` | 660 | 11 | 183 | Handle; more fragmented eleven-chart reference. |
| `EFB_HINGE_ARM_1` | 760 | 7 | 123 | Hinge arm; elongated mechanical part and seven charts. |
| `EFB_HINGE_CLAMP_ROTATOR` | 252 | 6 | 114 | Clamp/rotator; compact part with many normal splits. |
| `EFB_HINGE_ROTATOR_2` | 684 | 4 | 132 | Second curved mechanical candidate; four charts, no modifiers. |
| `LEVER_FLAP` | 734 | 2 | 75 | Lever; few UV charts despite many triangles, including border seams. |
| `POWERPLANT_COVER_L` | 556 | 3 | 57 | Second cover; different three-chart topology and normal splits. |

Run from `tests/_work/uv_shape/` only. Copy `prep3.py`, `proto_blender_v3.py`,
`uvmetrics.py`, and `evaluate3_extra.py` from `tests/uv_prototype/` into this folder.
Copy the source `C:\Users\uray\Downloads\E2_190_COCKPIT2.blend` here as
`E2_COCKPIT2_copy.blend`; open only that copy. Use the local venv for validation
(NumPy required); never install packages globally. All outputs below are scratch.

Save the following as `prepare_references.py` in the work folder. It runs the
unchanged prep3 evaluation/world-transform/triangulation pipeline, then loads only
the two export function definitions from proto3: no optimization or packing runs.
It writes `work3.blend`, `objects_info3.json`, ten `__existing.npz` files and their
`__seams.npy` and `__nsplit_T.npy` sidecars in `reference_results/`. The arrays use
the same P/T/UV/mat schema as the original seven. `extra.time=0` is a placeholder
for existing UVs, not an observed runtime. Source mesh names and first UV-layer
names are saved in `source_metadata.json`.

```python
import ast, json, os, runpy, sys
from pathlib import Path
import bpy, bmesh
import numpy as np
HERE = Path(__file__).resolve().parent
os.chdir(HERE)
names = ['COCKPIT_REAR_OBS_SEAT_MOUNTING_FRAME', 'CIRCUIT_BREAKER_COVER_L', 'POWERPLANT_COVER_L', 'LEVER_FLAP', 'DISC_HANDLE_AILERON', 'EFB_HINGE_ARM_1', 'EFB_HINGE_CLAMP_ROTATOR', 'CCD_LEFT_ROTARY_OUTER', 'B_GS_AFCS_AP_BUTTON', 'EFB_HINGE_ROTATOR_2']
metadata = {}
for name in names:
    obj = bpy.data.objects[name]
    metadata[name] = dict(mesh=obj.data.name, uv_layer=obj.data.uv_layers[0].name, dimensions=list(obj.dimensions))
assert len({v['mesh'] for v in metadata.values()}) == len(names)
sys.argv = ['prep3.py', '--'] + names
runpy.run_path(str(HERE / 'prep3.py'), run_name='__main__')
functions = ast.parse((HERE / 'proto_blender_v3.py').read_text())
functions.body = [n for n in functions.body if isinstance(n, ast.FunctionDef) and n.name in ('export', 'export_seams_nsplit')]
exec(compile(functions, 'proto_blender_v3.py', 'exec'))
out = HERE / 'reference_results'
out.mkdir(exist_ok=True)
for name in names:
    obj = bpy.data.objects['W_' + name]
    assert obj.data.uv_layers[0].name == metadata[name]['uv_layer']
    export(obj, obj.data.uv_layers[0].name, str(out / (obj.name + '__existing.npz')), dict(time=0, method='existing', **metadata[name]))
    export_seams_nsplit(obj, str(out), obj.name)
(out / 'source_metadata.json').write_text(json.dumps(metadata, indent=2))
print('REFERENCE_EXPORT_OK', len(names))


```

With no other Blender running, execute serially from the work folder:

```powershell
if (Get-Process blender -ErrorAction SilentlyContinue) { throw 'Blender already running' }
& 'G:\e-jets-e2\tools\blender\blender.exe' -b E2_COCKPIT2_copy.blend --python-exit-code 1 --python prepare_references.py
if ($LASTEXITCODE -ne 0) { throw 'Reference preparation failed' }
Copy-Item work3.blend references.blend
```

`references.blend` is the prepared reference set for subsequent proto3/proto4 runs;
its objects are prefixed `W_`. Keep this separate from the original-seven prepared
mesh. Use a clean `reference_results/` directory for recreation so stale rejected
candidates cannot enter the dataset. Check the repository root for stray thumbnail
folders after Blender exits (the known thumbnail warning may occur in scratch).

Save the following as `validate_references.py` in the work folder and run
`& .\venv\Scripts\python.exe -I validate_references.py`. This uses exact UV
endpoint equality, stronger than the source survey's 1e-6 tolerance. It requires
positive manifold artist seams, no crossed artist seam edges (including stubs),
and no extra UV cuts across unmarked manifold edges. Boundary seams are excluded
from the interior-edge count. It writes `reference_results/validation.json`.

```python
import sys, json
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
import uvmetrics as um
from evaluate3_extra import artist_texel
rows=[]
for p in sorted(Path('reference_results').glob('*__existing.npz')):
    d=np.load(p, allow_pickle=False); P,T,UV=(d[k] for k in ('P','T','UV'))
    assert np.isfinite(P).all() and np.isfinite(UV).all()
    assert T.min()>=0 and T.max()<len(P)
    labels=um._uv_topology(T,UV)[-1]
    seams=np.load(p.parent/(p.name.replace('__existing.npz','__seams.npy')))
    r=artist_texel(P,T,UV,labels,seams)
    r.update(name=p.name.split('__')[0], vertices=len(P), triangles=len(T), islands=int(labels.max()+1))
    rows.append(r)
Path('reference_results/validation.json').write_text(json.dumps(rows,indent=2))
for r in rows: print(r['name'],r['triangles'],r['islands'],r['artist_seam_edges'],r['artist_seam_crossed_edges'],r['offseam_split_edges'])
assert all(r['artist_seam_crossed_edges']==0 and r['offseam_split_edges']==0 and r['artist_seam_edges']>0 for r in rows)

```

Package 2 validated all ten objects with zero seam crossings and zero off-seam
cuts. Shape distortion, overlap, winding, texel quality and algorithm comparisons
remain Package 3 work; a consistent seam map alone does not certify those properties.

## 10. Round 5 Candidates Reproduction (Package 10)

Round 5 Package 10 combines the prototype features developed in Packages 4 through 9
into two candidate unwrap pipelines evaluated across all 17 objects (7 original cockpit
components in `work3.blend` and 10 reference objects in `references.blend`).

### Candidate Configurations

All runs execute using `tests/uv_prototype/proto_blender_v5.py` with Blender 5.2.2 LTS
in background mode (`-b`), evaluated via `uvmetrics.py` and `evaluate3_extra.py`.

- **Candidate C1 (Wall Cuts + Frame Protection + Alignment):**
  ```powershell
  --keep_trials 1 --wall_cuts 1 --frame_protect 1 --frames 1 --align 1 --straighten 0 --shape_accept 0 --fold_rule 0 --fold_border_fix 0
  ```
- **Candidate C2 (Wall Cuts + Fold Rule + Fold Border Fix + Frame Protection + Alignment):**
  ```powershell
  --keep_trials 1 --wall_cuts 1 --fold_rule 1 --fold_border_fix 1 --frame_protect 1 --frames 1 --keep_trials 1 --align 1 --straighten 0 --shape_accept 0
  ```

### Switch Roles & Behavior

| Switch | Default | Role in Code |
| :--- | :---: | :--- |
| `--keep_trials 1` | `0` | Preserves accepted per-chart unwrap coordinates; avoids bounding-box solver divergence and spurious repair splits. |
| `--wall_cuts 1` | `0` | Detects recessed wall loops and bevels at planar boundaries, cutting 45° corner miters to fold walls outward as opened boxes. |
| `--frame_protect 1` | `0` | Shields accepted wall-box charts from subsequent round-3/4 `ringframe` multi-hole lattice cutting, preserving large open frames intact. |
| `--frames 1` | `0` | Enables Codex's round-4 frame weighting and multi-hole Dijkstra cuts on non-protected charts (prevents excessive cuts on ribbed floor plates). |
| `--align 1` | `0` | Post-processes 2D island orientations by rotating dominant boundary edges to cardinal UV axes (0°, 90°, 180°, 270°). |
| `--fold_rule 1` | `0` | Checks dihedral angles across candidate merges (>45°); rejects merges that introduce severe conformal distortion across hard folds. |
| `--fold_border_fix 1` | `0` | Selectively unseams flat/smooth edges across rejected fold boundaries while keeping steep edges and normal splits as seams. |
| `--straighten 0` | `0` | Stays disabled (ineffective on non-developable surfaces; caused triangle overlaps on `LEVER_FLAP_LOCK`). |
| `--shape_accept 0` | `0` | Stays disabled pending size-dependent limits (Decision 39; fixed 1.10 threshold over-fragments small control knobs). |

### Reproduction Commands

Execute serially from the scratch working directory (e.g. `tests/_work/uv_shape/`),
ensuring no other Blender instances are running:

```powershell
$B = "G:\e-jets-e2\tools\blender\blender.exe"
$O_ORIG = "W_AUDIO_L_VOLUME_KNOB,W_TRIM_PANEL,W_LEVER_FLAP_LOCK,W_@MERGE_PEDESTAL_SHELL,W_COCKPIT_SHELL_L,W_COCKPIT_SHELL_FLOOR,W_OVERHEAD_SHELL"
$O_REFS = "W_COCKPIT_REAR_OBS_SEAT_MOUNTING_FRAME,W_CIRCUIT_BREAKER_COVER_L,W_POWERPLANT_COVER_L,W_LEVER_FLAP,W_DISC_HANDLE_AILERON,W_EFB_HINGE_ARM_1,W_EFB_HINGE_CLAMP_ROTATOR,W_CCD_LEFT_ROTARY_OUTER,W_B_GS_AFCS_AP_BUTTON,W_EFB_HINGE_ROTATOR_2"

# 1. Run Candidate C1 on original 7 objects and 10 reference objects
& $B -b work3.blend --python proto_blender_v5.py -- --objects $O_ORIG --out candidate_c1 --tag c1 --tree 1 --visibility 1 --borders 1 --strips 1 --frames 1 --keep_trials 1 --wall_cuts 1 --frame_protect 1 --align 1 --straighten 0 --shape_accept 0 --fold_rule 0 --fold_border_fix 0
& $B -b references.blend --python proto_blender_v5.py -- --objects $O_REFS --out candidate_c1 --tag c1 --tree 1 --visibility 1 --borders 1 --strips 1 --frames 1 --keep_trials 1 --wall_cuts 1 --frame_protect 1 --align 1 --straighten 0 --shape_accept 0 --fold_rule 0 --fold_border_fix 0

# 2. Run Candidate C2 on original 7 objects and 10 reference objects
& $B -b work3.blend --python proto_blender_v5.py -- --objects $O_ORIG --out candidate_c2 --tag c2 --tree 1 --visibility 1 --borders 1 --strips 1 --frames 1 --keep_trials 1 --wall_cuts 1 --frame_protect 1 --align 1 --straighten 0 --shape_accept 0 --fold_rule 1 --fold_border_fix 1
& $B -b references.blend --python proto_blender_v5.py -- --objects $O_REFS --out candidate_c2 --tag c2 --tree 1 --visibility 1 --borders 1 --strips 1 --frames 1 --keep_trials 1 --wall_cuts 1 --frame_protect 1 --align 1 --straighten 0 --shape_accept 0 --fold_rule 1 --fold_border_fix 1
```

### Side-by-Side Image Generation

To visually compare candidate UV unwraps against artist UV layouts without packer bias,
repack the artist UVs (`__existing.npz`) using Blender's identical concave packing operator
(`average_islands_scale()` followed by `pack_islands(shape_method='CONCAVE', margin=0.004, rotate_method='CARDINAL')`),
then render the resulting UV meshes side-by-side using `matplotlib`:

```powershell
# In the venv:
.\venv\Scripts\python.exe -I repack_artist_uvs.py
.\venv\Scripts\python.exe -I generate_side_by_side_images.py
```

## 11. Visibility-Based Texel Demand Prototype (`visibility_proto.py`)

Measures per-face visibility sums (weighted visible solid angle $\Omega_{\text{vis}, w}$ and unoccluded solid angle $\Omega_{\text{unocc}}$) from reference cameras across multiple animation states, using background GPU face-ID rendering and group scoring (Round 3, Sessions 72 & 73, Decision 78).

Decisions implemented:
- **Visibility Model & Sums:** Accumulates per-face weighted visible solid angle and unoccluded solid angle across views and instances; stores no ratio at the face level (Decision 78).
- **Group Scoring:** Computes $\sum \Omega_{\text{vis}, w} / \sum \Omega_{\text{unocc}} \in [0, 1]$ per group (UV islands and objects) per view and instance, taking the maximum over views and instances. Groups smaller than 10 reference pixels fall back to their object's score (Decision 78).
- **Direction Weight:** MSFS free-look weight $w = \max(\text{floor}, \cos(\theta)^\text{falloff})$ to camera default forward; floor 0.2, falloff 1.0 (Decision 73). Fixed-view frustum mode kept as per-camera option.
- **Animations:** Normalized percentage states of each action's own frame range (Decision 69), default 3 states (0%, 50%, 100%), option for 5 states.
- **Material Classes:** Invisible/collision/occluder materials (e.g. `InvisibleCollider` clickspots) omitted completely from geometry extraction, analytical calculations, counts, and rendering (Decision 77, Finding 2). Decal/glass/windshield rendered in a second pass with depth write disabled (`depth_mask=False`, depth test `LESS_EQUAL`) so they are scored without occluding underlying panels.
- **Original Face Attribute Transfer:** Adds temporary integer attribute `_fss_orig_face_idx` to base meshes, automatically transferred through modifiers (Triangulate, Mirror, Subsurf) to evaluated polygons, cleaned up in `finally` (Finding 3). No modulo or clamp index fallbacks.
- **Instances & Mirror Modifiers:** Every object using a mesh and every Mirror copy is an instance; takes $\max$ over instances and views (Decisions 68, 78).
- **Never-Seen Reporting:** Groups with zero visible solid angle above the size threshold reported as "never seen in the analysed views and states" (Decision 74).
- **Storage:** External `<blend_name>.visibility` file alongside the `.blend` with schema version 3 (compressed NPZ with views, options, mesh instances, and `(N_views, N_instances, N_faces)` float32 arrays).
- **Color Scale:** Never seen in magenta (error color); $0.0 < s \le 0.5$ graded red to neutral grey; $0.5 < s \le 1.0$ graded neutral grey to blue. Rendered by island score with fallback to object score; clickspots omitted.

### Commands

Execute from the repository root with Blender 5.2.2 LTS in background mode:

```powershell
$B = "G:\e-jets-e2\tools\blender\blender.exe"

# 1. Run synthetic validation on 11 test cases (Distance Invariance, Half-Covered, Direction Weight, Back Face, Invisible Collider, Decal Pass, Action 100-200, Multi-Face Grid Invariance, Mirror Blocked, Triangulate Modifier, Linked Duplicates)
& $B -b --factory-startup --python tests/uv_prototype/visibility_proto.py -- --synthetic

# 2. Run resolution check comparing 1,024 vs 4,096 px cube face resolution on the cockpit copy
& $B -b "tests/_work/uv_visibility/COCKPIT_copy.blend" --factory-startup --python tests/uv_prototype/visibility_proto.py -- --resolution-check

# 3. Run complete analysis on E2 Cockpit copy (2 look-around cameras, 3 percentage states, renders graded heatmap images and checks glTF export)
& $B -b "tests/_work/uv_visibility/COCKPIT_copy.blend" --factory-startup --python tests/uv_prototype/visibility_proto.py -- --cockpit
```

Optional CLI parameters:
- `--states 3` or `--states 5`: Number of normalized animation states (default 3: 0%, 50%, 100%).
- `--floor 0.2`: Minimum direction weight for side/rear views (default 0.2).
- `--falloff 1.0`: Cosine power falloff for direction weight (default 1.0).
- `--cube-res 1024`: Face resolution of the look-around cube map (default 1024).
- `--out-dir tests/_work/uv_visibility`: Output directory for `.visibility` file and PNG images.

Outputs written to `tests/_work/uv_visibility/`:
- `<blend_name>.visibility`: Compressed NPZ archive (schema version 3) containing JSON metadata, camera configurations, animation states, per-mesh arrays `(N_views, N_instances, N_faces)`, and group summaries.
- `pilot_demand.png`: 1080p offscreen render from the pilot camera colored by group visibility score (blue = high forward view, neutral grey = mid score, red = glancing angle; clickspots omitted).
- `outside_demand.png`: 1080p offscreen render from an exterior isometric view highlighting never-seen exterior fuselage/structure (magenta) and interior instruments (blue/grey).
