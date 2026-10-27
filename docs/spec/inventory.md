# Feature Inventory

Input for the specification to be written in `docs/spec/`: every feature of the two FSS add-ons, sorted by status, each with its source. Compiled on 20261027 from the code (fss_blender_tools 0.33.1, commit 188bf24), the artist guide ([../user/](../user/)) and the journals ([../journal/](../journal/README.md)). The specification itself (requirement IDs, data formats, test traces) is not written yet.

| Status | Meaning |
| :--- | :--- |
| **implemented** | built, released and documented in the artist guide; checked against the code |
| **planned** | decided by the maintainer, not built |
| **wish** | proposed or listed, not decided |
| **rejected** | considered and turned down; listed so it is not proposed again |

Sources: **W***n* = item *n* of the wish-list journal (`20261010.fss-blender-tools-wishlist.md`); **UV** *n*, **LOD** *n* = decision *n* of the UV or LOD journal; other journals by name.

## Principles (maintainer)

- **Two add-ons:** the exporter (`io_scene_gltf2_msfs_fss`, a fork of Asobo's MSFS exporter) stays an exporter that tracks Asobo and stays mergeable; everything else belongs in **fss_blender_tools** (wish-list Session 1).
- **fss_blender_tools does not enforce a workflow:** each tool is independent and optional, an aid alongside the artist's manual work, never a requirement (UV 42).
- **Tools work on any model,** not only MSFS ones: no decisions by MSFS material type where a generic rule exists (UV 100). Exceptions so far: Auto Seam's decal skip by material class (UV 55) and the material classes in Visibility Scoring (UV 77).
- Further working preferences: [../../AGENTS.md](../../AGENTS.md#maintainer-preferences).

## 1. Exporter (`io_scene_gltf2_msfs_fss`)

Based on Asobo's MSFS 2024 exporter 8.4.1 for Blender 5.2; FSS changes live in FSS-owned modules (`instancing.py`, `migration.py`, `legacy_normals.py`, `msfs2020_target.py`, `fss_workflow_ui.py`, `io/exp/gltf_exporter_patches.py`, marked spots in `io/exp/multi_export.py`). Guide: [../user/exporter.md](../user/exporter.md); journal: `20261002.msfs2024-blender5-exporter-conversion.md`.

| Feature | Status | Source |
| :--- | :--- | :--- |
| One `.blend` for both simulators: Export Target MSFS 2024 or MSFS 2020; MSFS 2020 exports build, for the export only, the material setup the MSFS 2020 add-on would have made | implemented | exporter conversion journal; `msfs2020_target.py` |
| One-time conversion of materials made with the MSFS 2020 add-on (values to MSFS 2024 meaning, emissive to cd/m²), on open, append and before export | implemented | `migration.py` |
| Restore Blender 3.6 normals for files from Blender 4.0 or older | implemented | `legacy_normals.py` |
| Instancing: a shared mesh exported once, also when its users have only Auto Smooth with the same angle | implemented | `instancing.py` |
| Clean-up on export: NLA tweak mode, Edit and Pose Mode | implemented | exporter guide |
| Asobo's export workflow hidden (Multi-Export Hierarchy tab, LOD Tools panel) in favour of the FSS deploy, merge groups and LOD marks | implemented | `fss_workflow_ui.py` |
| Export speed of the LOD deploy (E2 cockpit 973 s to 67 s) | implemented | `20261017.export-performance.md` |
| Hooks used by fss_blender_tools: merge groups, leading `@` stripped, `fss_` keys out of glTF extras | implemented | `fss_blender_tools/merge.py` (runs inside the exporter) |
| Ghost material ranges (`msfs_ghost_bias`, `msfs_ghost_power`) converted between simulators | wish (known issue) | exporter guide, Known Issue |
| Five "Mesh is not valid" warnings in the E195 cockpit export | wish (not investigated) | exporter conversion journal, Session 14 |
| Upstream Asobo releases merged per file (three-way) | implemented (process) | `AGENTS.md`, Upstream Policy |

## 2. fss_blender_tools

### 2.1 General Tools (Utilities)

| Feature | Status | Source |
| :--- | :--- | :--- |
| Add Empty Parent (Manual, Suffix, Prefix naming) | implemented | `tools.py` |
| Origin to Bounding Box (tightest box, corners, faces, edges) | implemented | `tools.py` |
| Empty Bounds: boxes of empties' subtrees, parent highlight, clickable hierarchy text | implemented | W29; `20261011.fss-blender-tools-empty-bounds.md` |
| Heatmap: Distortion (shear, area, both), Density, Visibility; chart, legend, UV grid with labels | implemented | UV 57 to 63, 66, 84, 89 |
| Scan Names: suffix, collision, case, characters, default names, taken, clash; batch rename | implemented | W2 (without the project contract); `20261011.fss-blender-tools-name-check.md`; UV 87 |
| Fix Broken Bone Parents | implemented | W28 (first rule); tags-and-merge journal Session 6 |
| Find Faces Without Area (3D) | implemented | UV 117 |
| Find Faces Without UV Area (needles) | implemented | UV 118 |
| Find Thin UV Faces: any UV triangle under 1 px wide on a 1K texture, size and width as settings, replacing Find Faces Without UV Area | wish (proposed 20261023) | UV journal Session 102, open item 1 |
| Stupidity check: one report with severity and fixes (duplicate vertices and faces, loose geometry, hierarchy, transforms, bloat, external add-on data) | wish (two rules built: bone parents, faces without area) | W28 |
| Texture and path check (missing images, absolute paths, `.png.xml`) | wish | W11 |
| Material consolidation (duplicate materials) | wish | W10 |
| Instancing candidates and "bake shared modifiers" | wish | W9 |
| Exported glTF diff against the deployed one | wish (the test harness can compare two glTFs: `tests/harness/compare.py`) | W12 |
| Draw-call, batch and active-LOD prediction | wish | W7 |

### 2.2 Tags

| Feature | Status | Source |
| :--- | :--- | :--- |
| Free, multi-valued tags per object (`fss_tags`), independent of collections; add, remove, select, rename, delete | implemented | W5 (as generic tags); tags-and-merge journal |
| Tag switches: Don't Merge (merge), Keep (LOD) | implemented | tags-and-merge journal; LOD journal |
| Functional roles with meaning (clickspot, screen, light mesh, emitter, debug mesh) inferred from materials and `panel.cfg` | wish (tags were built instead, without inference) | W5 |
| Conversion of the functional collections into tags or roles | wish | W5 |

### 2.3 Zones

| Feature | Status | Source |
| :--- | :--- | :--- |
| `@ZONE_<NAME>` empties; exported as `ZONE_<NAME>` | implemented | UV 28, 33, 87 |
| Zones listed in Zones & Merge Tree; warnings for merge groups outside every zone, zones inside merge groups or zones | implemented | UV 34; tags-and-merge journal Session 8 |
| A zone's density factor = its own density mark, inherited below it | implemented | UV 108 |
| The zone tool: materials per zone and class (`<SCENE>_<ZONE>_<CLASS>`), created from template materials and assigned automatically, so no material spans zones; texture size from the zone material | planned (not built) | UV 22 to 27, 29 to 32 |
| Mirror across zones handling | planned | UV 27 |

### 2.4 Merge Tree

| Feature | Status | Source |
| :--- | :--- | :--- |
| Export-time merge of each `@MERGE_` group's subtree into one mesh; `@NOMERGE_`, animated, skinned, bone-parented, shape-key, Don't Merge and non-mesh objects stay separate; transparent parts as `<name>_TRANSPARENT` | implemented | W8; tags-and-merge journal |
| Only in a deploy or the MSFS 2024 multi-exporter, never in a plain File > Export | implemented | tags-and-merge journal |
| New Merge Group, Refresh tree, Print Details | implemented | `merge.py` |
| Decal merge per zone, decal material and Draw Order | wish (today decals, as blended surfaces, merge into their group's `<name>_TRANSPARENT` mesh, without grouping by Draw Order) | W14 |
| Merged animation names keep a `@MERGE_` marker when the action is named after the root | known issue | tags-and-merge journal, Known Issues |

### 2.5 LOD

| Feature | Status | Source |
| :--- | :--- | :--- |
| LOD marks: Auto, Keep, Hidden from, Visible from; per-LOD export | implemented | LOD journal stage 1 |
| Automatic size culling of whole parts and of loose pieces inside a mesh, before merging (no geometry is cut) | implemented | LOD 18; [../user/lod.md](../user/lod.md) |
| Quota and Hints (vertex quota per LOD, near cut-off and loose-piece lists) | implemented | LOD journal Session 7 |
| Viewport LOD: a level or Auto (as MSFS would pick); excluded objects Hidden or Bounds | implemented | LOD journal Session 8; LOD 36 |
| LOD sphere padding (diameter) controlling MSFS's LOD switch; model type Exterior, Interior (exterior diameter derives the table), Scenery; explicit `minSize` table; Print LOD Settings / XML | implemented | LOD journal; [../user/lod.md](../user/lod.md) |
| Children of a hidden reference empty (for example the `LIGHTPOS_*` nodes MSFS lights refer to) stay exported at the glTF root | implemented (the exporter's behaviour, accepted) | LOD 33 |
| Automated LOD generator with decimation (flow-lod, meshoptimizer), render comparison | wish (research only) | W27; LOD journal |
| Cockpit LOD1 from window visibility | wish | W21 |
| Silhouette check across LODs | wish | W23 |

### 2.6 UV

| Feature | Status | Source |
| :--- | :--- | :--- |
| Auto Seam: Propose (C1, around the artist's seams, no diagonal cuts), Accept, Accept + Unwrap (Angle Based), Discard, Clear Current, Select; Distortion Limit; progress; report | implemented | UV 35 to 54, 64, 65, 88, 90 to 94 |
| Skip Auto Seam mark; decal-only objects skipped | implemented | UV 55, 56 |
| Unwrap: Blender's Angle Based (through Accept + Unwrap) | implemented | UV 90, 91 |
| Visibility Scoring: artist cameras, Look Around or Fixed View, 2 to 10 animation steps, `.visibility` file, per-face sums, seen-face island values, floor 0.1 | implemented | UV 67, 72 to 74, 77 to 80, 82, 83, 86, 111 |
| Density: scene target (px/cm), density freedom, multiplying density marks with presets, the chain shown live | implemented | UV 105, 106, 108, 109 |
| Packing per texture set (Blender's Pack Islands with our scaling): density first, spill and needed size, one common position, square sizes 256 to 8192, margin in px, direction marks, Keep UVs, Check All, texture set list, also in the UV Editor | implemented | UV 100, 107, 110, 112 to 116, 119 to 121 |
| Packing picked per material directly instead of through the object selection | wish (waits for artists' feedback) | UV journal Session 102, open item 2 |
| Add to Layout: pack new islands into free space with the rest pinned | wish | UV journal Session 99 |
| Ignore short needles in the checks | wish (waits for artists' feedback) | UV journal Session 100 |
| Visibility Scoring of an exterior (the artist's own exterior cameras) | implemented generically (any artist camera, UV 80), never tried on an exterior model | UV 80 |
| Stacking units (shared meshes, Mirror, Array) | implemented for shared meshes; Mirror and Array copies share UVs by construction | UV 3 |

### 2.7 Project Contract and MSFS Project Tools

All need the project contract (what the MSFS project expects from a glTF), to come from `project-tree` in the FSS aircraft repository (wish-list Shared Foundation; maintainer decision 2 of the wish-list: ask project-tree, transport open).

| Feature | Status | Source |
| :--- | :--- | :--- |
| Sub-model and attachment preview | wish | W1 |
| Name check against the project (names the XML expects) | wish (Scan Names works without it) | W2 |
| Missing nodes and animations expected by the project | wish | W3 |
| Clickspot and collision mesh generator (Invisible material meshes) | wish | W4 |
| MSFS project view (tree of referenced objects, playback) | wish | W6 |
| E1-to-E2 name mapping | wish | W13 |
| Input normalizer and adaptor-empty collapse | wish | W17 |

### 2.8 Other Wishes

| Feature | Status | Source |
| :--- | :--- | :--- |
| Legend bake helper; decal text generator (glyph atlas) | wish | W15, W16 |
| Cockpit bake operator (AO, sky light, flood circuits) | wish | W18 |
| Dirt, grime and ice shell generator | wish | W19 |
| Sky portal placer | wish | W20 |
| Transparency sorting-risk check | wish | W22 |
| Registration mesh check; exterior light audit; wing-flex joint helper | wish | W24 to W26 |
| Tools for passive (AI traffic) aircraft | wish (deferred until a passive E-Jet is planned) | wish-list |

## 3. Rejected

| Proposal | Why | Source |
| :--- | :--- | :--- |
| Baked normal maps from a high-poly model for the E2 cockpit | not used | UV 1 |
| xatlas packer | ignores the requested margin, does not keep the density | UV journal Session 16 |
| Our own grid packer as the default | no density gain over Blender's Pack Islands; kept as a prototype | UV journal Sessions 16, 97; UV 107 |
| Minimum Stretch (SLIM) for hard-surface parts | does not reproduce the trial results | UV 37 |
| Shape acceptance, fold rule, straightening as switches | C1 adopted, no switches (one slider later) | UV 39 to 41, 45, 88 |
| Never-seen faces as delete candidates | switch states and conditional parts are never seen in some states | UV 74 (replaces 20) |
| Visibility as screen pixels per area with a reference view | depends on resolution and view; replaced by the 0-to-1 visible fraction | UV 70, 72 |
| Tiered island scaling | arbitrary ratios are no problem in Substance Painter | UV 81 |
| Deciding packing by material type or texture presence | tools must work on any model; textures do not exist before texturing | UV 96, 100 |
| Overflow by default into UDIM tiles or a scale-down to fit | density first; fitting is the artist's choice | UV 10, 13, 112 |
| A maximum texture size per material | the artist chooses the size freely | UV 106 |
| Non-square texture sizes | square only | UV 120 |
| Margins as a fraction of the texture | pixels give every set the same protection at one global density | UV 105 |
| Export-time name alias for duplicate names | rename the Blender objects instead | W2, wish-list decision 3 |
| A separate repository for fss_blender_tools | it lives next to the exporter in this repository | wish-list Session 2 |
