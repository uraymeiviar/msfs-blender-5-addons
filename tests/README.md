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
| `tests/test_uv_pack.py` | the packer: the raster step that uses free space (footprints, islands inside a ring, direction marks, fallback to Pack Islands), density per island, fit, underflow, overflow and needed size, directions, linked duplicates, Pack and Check All, Keep UVs, faces without 3D or UV area, the texture set list, the UV editor panel, report order |
| `tests/test_density_marks.py` | density marks multiplying down the hierarchy, scene freedom, presets, migration of older files, the UV Auto Packing chain drawn, visibility floor, heatmap refresh after a mark change |
| `tests/test_panels.py` | the sidebar layout (both tabs and the UV editor): every panel's label, parent, order and tab, the FSS Tools panels closed by default, every panel drawn; Add Parent (one empty above siblings at the active object, nothing moves, refused with a note otherwise, the naming rules); Rename Meshes (the tree below the selection with hidden objects, shared meshes, markers, swapped names, a taken name); Object LOD (selection line, mixed marks, the pending Hidden from / Visible from choice, the Visible in row, drawing writes nothing); Viewport LOD (the Excluded row only with a preview); LOD Settings (the table at this view, contributor bars, the table per LOD in Export Settings, Pad LOD Sphere Multiplier and the far-origin warning with it) |
| `tests/test_zone_tree.py` | Zones & Merge Tree rows and flags, zone marks, nearest zone, what the Tags panel draws, selecting from a group's details, totals and zone counts against an export, no `fss_` key in the glTF extras |
| `tests/test_materials.py` | the Materials panel: Refresh rows (never used, shared across zones, hidden users, shared meshes, area per zone, the estimate with and without a `.visibility` file), kind marks with and without the exporter, the select operators, panels drawn without writing, Keep UVs in the active material box (kept instead of the estimate, without Refresh), no `fss_` key in the glTF extras, refresh on opening a file (Zones & Merge Tree, Materials and Scan Names; nothing scheduled in background) |
| `tests/test_texture_sets.py` | the Texture Sets sub-panel: the role table against the exporter's slots and types, rows from PNG headers (roles per type, secondary maps with a blend mask, slots the type does not use, missing, other and packed files), channel warnings (unused channels, 16-bit need per role and type, alpha of an Opaque albedo, grey files), Check Data Depth (8-bit data in 16 bits, flat channels, results reused until the file changes), drawing writes nothing |
| `tests/test_texture_xml_panel.py` | the texture XMLs of the Texture Sets sub-panel: the list follows the multi-exporter presets or the visible objects, the BitmapSlot of each slot (detail maps with and without a blend mask, Windshield, Tire, a slot without XML), the slot conflict, the XML states (missing, matches, differs, no PNG), Write XMLs byte for byte the same as a multi-exporter export, XMLs read once on Refresh, on opening a file and before writing, then Blender's flags win, drawing writes nothing, the panel without the exporter |
| `tests/test_texture_xml.py` | the MSFS Texture Folder at export (`io_scene_gltf2_msfs_fss/texture_folder.py`): URIs point at the PNGs and resolve, one XML per texture with slot and flags, a missing PNG kept and reported, an XML on disk read once and then Blender wins, the 16-bit PNG untouched, the glTF unchanged but the URIs, File > Export and the multi-exporter, MSFS 2020 and an empty or missing folder unchanged, ForceNoAlpha kept on rewrite (with the patch off it is dropped), the detail normal slot with and without a blend mask and the windshield icing normal (with the patch off they are swapped) |
| `tests/test_no_export.py` | the No Export tag mark: the tagged objects and everything below them, a renamed tag, a glTF export without them (lights included) and a merge group that leaves a tagged member out |
| `tests/test_animation_ranges.py` | Find Animations Not 0 to 100: what it reports and selects, and that it changes nothing |
| `tests/test_markers.py` | leading `@` stripped at export, Scan Names markers and the Clash rule |
| `tests/test_root_marker.py` | a `@ROOT_` empty (moved, rotated and scaled, below a moved zone) is not written, its two meshes go to the glTF root with their world transforms and the child of one stays below it, a `@ROOT_` inside a merge group stays out of the merge; plain exports for both simulators and the multi-exporter; Scan Names never reports it as a clash; an animated `@ROOT_` warns |
| `tests/test_name_clash.py` | a marker node whose exported name or unique id is taken gets `_GROUP` (`_GROUP_2`, ...) with a log line, the unmarked node keeps its name: the E2 cockpit button case, a group named like an object elsewhere, a `@NOMERGE_` node, through the multi-exporter and plain exports for both simulators; shared unique ids of unmarked nodes are reported |
| `tests/test_ao_bake.py` | AO Bake: a synthetic scene baked through the operators in a hidden second Blender (run the suite under `cpucap.exe 50`, the second Blender inherits the cap): status m of m and Cancel after the current object; staleness grades per edit and the relink after a rename; the `.blend` and its datablocks unchanged by a bake and by Apply; Apply into the ORM slot texture (16-bit and 8-bit), per object, into separate files (greyscale, ORM layout, another size with each sampling method, islands not mixed); the occluder rules; the panel drawn without writing |
| `tests/test_lod_preview.py` | LOD viewport preview (hidden and bounds), save and load handlers |
| `tests/uv_prototype/test_visibility.py` | Visibility Scoring with probe lights: brightness against EEVEE (point, spot, area, distance, cone edge, light threshold), synthetic cases, shadows and soft shadows, an animated light, Island Value and Step Limit, the light list (sync, select), operator, scene unchanged, heatmap mode, glTF leak, packer interface |
| `tests/uv_prototype/test_autoseam_operators.py` | Auto Seam operators: propose, accept, Accept + Unwrap, discard, clear, progress, buttons |
| `tests/uv_prototype/test_uv_heatmap.py` | the heatmap: distortion, density, visibility modes, display takeover, chart, grid |

The exporter has one such suite too, run the same way: `tests/test_anisotropic_preview.py` (the preview nodes with and without the anisotropic texture, normal and alpha changes, each engine's output after save and load, metal, emission and alpha rendered in both engines, the update operator, exports identical with and without the preview for both simulators and File > Export), and `tests/test_material_animation.py` (`ASOBO_property_animation` read back from the written glTF against what Blender shows on each frame: easing, partly keyed colors, Emissive Scale, frame range, shared actions, sampler indices, NLA strips, a material track merged into another object's animation of the same name in Actions mode; its `acceptance` export in `tests/_work/material_animation_scratch/` is the Glider test file), and `tests/test_export_settings_reference.py` (a plain MSFS 2024 export after a multi-export and a new or opened file: the multi-exporter's settings are cleared on load, and with `FSS_SETTINGS_FIX_OFF=1` the suite must fail), and `tests/test_instancing.py` (users of one mesh with Weighted Normal or Auto Smooth exported once when they evaluate identically, against the same scene with the rule off through `harness/compare.py`: different settings and object-linked materials split, Mirror, shape keys and skinning left alone, interactive-style export and source objects unchanged; with `FSS_INSTANCING_RULE_OFF=1` it must fail), and `tests/test_normal_scale.py` (materials sharing one normal image keep their own Normal Scale and Detail Normal Scale in the multi-exporter and File > Export, the FSS patch over Asobo 8.4.2; with the patch switched off the multi-exporter gives one scale to all, so the suite shows the bug it guards against).

Without Blender: `python -m unittest tests.test_lod_rules` (LOD rules), and `tests/uv_prototype/test_uvmetrics_shape.py` (see its header). A traceback about `ImagePreviewCollection ... left open` at start-up comes from purging the deployed copy and is harmless. Prototype scripts and real-data runs are described in [uv_prototype/RUN.md](uv_prototype/RUN.md).
