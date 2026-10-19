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

Working directory for every command: `uvproto\`. Blender: `D:\fss-e2\tools\blender\blender.exe`
(5.2.2 LTS), background only, one Blender process at a time. Blender scripts run on Blender's own
bundled Python (numpy comes with Blender); `xatlas_run.py` and `evaluate3.py` run on the venv
(`venv\Scripts\python.exe -I`). Shell syntax below is Git Bash.

```bash
B=/d/fss-e2/tools/blender/blender.exe
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

- `C:\Users\uray\Downloads\E2_190_COCKPIT2.blend` (source, copy step only) and `D:\fss-e2\tools\blender\blender.exe` appear only in the commands above, not in the scripts.
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
& 'D:\fss-e2\tools\blender\blender.exe' -b work3.blend --python-exit-code 1 --python proto_blender_v4.py -- --objects $uvObjects --out results3 --skip_smart 1 --tag tree --tree 1
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

