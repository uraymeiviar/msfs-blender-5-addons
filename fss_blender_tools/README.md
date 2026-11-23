# FSS Blender Tools

Authoring tools for FSS aircraft in Blender 5.2, in the 3D View sidebar tabs "FSS MSFS Tools" and "FSS Tools"
(General, Empty Bounds, Heatmap, Checks; UV Auto Packing also in the UV Editor's "FSS MSFS Tools" tab). Independent of the Asobo
add-ons; the only coupling to the exporter is the glTF user-extension hook in `merge.py`. Working rules for this
repository are in [../AGENTS.md](../AGENTS.md).

## Modules

| Module | Panel (sidebar path) | What it does |
| :--- | :--- | :--- |
| `panels.py` | (none) | Registers no panel; its docstring documents the layout (material-management decisions 16, 22 and 26). Each module registers its own panels; `bl_order` sets the order of the top-level panels in each tab: Zones & Merge Tree, Materials, Tags, Object LOD, Viewport LOD, LOD Settings, UV Auto Seam, UV Auto Packing in the tab FSS MSFS Tools (UV Auto Seam and UV Auto Packing closed by default); General, Empty Bounds, Heatmap, Checks in the tab FSS Tools (all closed by default). Subpanels: By Texture Need (Materials), Hints and Export Settings with Advanced (LOD Settings), Visibility Scoring (UV Auto Packing) |
| `autorefresh.py` | (none) | Refresh on opening a file (decision 21): a persistent `load_post` handler starts a timer that runs `fss.merge_refresh`, `fss.materials_refresh`, `fss.name_check_scan` and `fss.lod_refresh` in the first window's context, each only when its poll passes (Materials needs Object Mode), without undo steps; nothing in a background Blender. Check All stays manual |
| `tools.py` | **General** (tab FSS Tools) | Scene helpers: **Add Parent** (one empty above the selected siblings, at the active object; Manual / Suffix / Prefix / `@MERGE_` / `@NOMERGE_` / `@ZONE_` naming rules), **Origin to Bounding Box** (minimum-volume OBB orientation with 8 corners, 6 face centers and 12 edge centers), **Rename Meshes** (`MESH_<object>` or `MESH_SHARED_<first object>` for the selection and everything below it) |
| `empty_bounds.py` | **Empty Bounds** (tab FSS Tools) | Draws the bounds of empties' subtrees (`All` / `Selected` / `Off`, `In Front`) and a clickable hierarchy text in the viewport |
| `lod.py`, `lod_model.py`, `lod_rules.py` | **Object LOD**, **Viewport LOD**, **LOD Settings** (with **Hints** and **Export Settings**) | Auto size culling (objects and loose mesh pieces); Object LOD: Auto / Keep / Hidden from / Visible from marks of the selection with the **Visible in** row (the pending choice in `WindowManager.fss_lod_pending`, not saved, set by `fss.lod_pending`); Viewport LOD: the membership preview; LOD Settings: Refresh LOD Counts, the table of what MSFS does at the current view, the per-LOD vertex contributors, and the scene export settings |
| `tags.py` | **Tags** | Generic object tags (`fss_tags`, semicolon-separated), per-row `[-]`/`[+]` assignment, selection by the tag name (filled when a selected object has the tag), and per-tag skip-merge, Keep, Non-AO-Occluder, Skip-AO-Bake (stored for a later bake), Invisible and Animated (marks read by the stray counts), Whole (the LOD export keeps all loose pieces), No Texture and No Export (`merge.py`'s `gather_tree_filter_tag_hook` drops the tagged objects with their subtrees from every export, and the merge leaves them out) toggles |
| `merge.py` | **Zones & Merge Tree** | Export-time merge groups (`@MERGE_<name>` / `@NOMERGE_<name>`), New Merge Group, tree preview of zones (`@ZONE_<NAME>`), groups and `@NOMERGE_` nodes with Unzoned and nesting warnings, console details; the zone row edits the zone empty's own density mark (`uv_marks`); `nearest_zone()` finds an object's zone |
| `materials.py` | **Materials** with **By Texture Need** | Read-only overview of every material (phase 1 of the material-management journal): Refresh fills `Scene.fss_materials` from the view layer (objects with faces using each material, hidden users, shared meshes, zones by `merge.nearest_zone`, world 3D area per zone, an area-based texture size estimate at the top of the density range, with visibility); the active material's Keep UVs checkbox (`Material.fss_uv_keep_uvs`, as in Packing; the only control that changes data), a kept material shows kept instead of the estimate; warnings never used and shared across zones; kind marks transparent (`msfs_alpha_mode` Blend) and emissive (`msfs_emissive_texture`), read with `getattr`; Select Objects (all zones or one, holders only for a material never used); Check All of Packing; By Texture Need compares the materials' estimates with their texture sizes, without materials never used, not rendered, or used only by No Texture objects |
| `texture_sets.py` | **Texture Sets** (sub-panel of **Materials**) | Per used material its texture slots with role, channels and bit depth from the PNG header, warnings and **Check Data Depth** (material journal Session 33); the texture XML list of what the MSFS 2024 export writes (Sessions 34, 35): one row per texture file of the exported objects (enabled multi-exporter presets, else the visible objects) with its BitmapSlot (`BITMAP_SLOTS`, mirroring the exporter's `texture_lib/gltf_material.py`), a slot conflict warning, the six `image.msfs_flags` and the XML state in `Scene.msfs_fss_texture_folder`; **Write XMLs** (`fss.texture_xml_write`); Refresh reads never-read XMLs once (`texture_folder.read_xml_once`) |
| `uv_marks.py` | **UV Auto Packing**, also in the UV Editor's sidebar (the Skip Auto Seam mark is drawn in UV Auto Seam) | Authoring marks for UV unwrapping and packing: per-object density mark, a factor range (`fss_uv_density_own`, `fss_uv_density_min`, `fss_uv_density_max`; presets Lower x0.75 and Higher x1.5) that multiplies down the hierarchy with the scene's target density (`fss_uv_target_density`, 20.48 px/cm) and density freedom (`fss_uv_density_freedom_min` / `_max`, 0.9 to 1.1): `density()` gives the final range, `parent_density()` the chain above, `own_density()` the own factor; island direction (`fss_uv_direction`: Free, Upright, Flip, Quarter) and Skip Auto Seam (`fss_uv_skip_autoseam`), inherited from the nearest marked ancestor; per material the square texture set size (`fss_uv_texture_size`, 256 to 8192, default 4096, `texture_size()`) and island margin in pixels (`fss_uv_margin_px`, default 8, `margin()`), and **Keep UVs** (`fss_uv_keep_uvs`: the set is not packed), a density factor with its tick (`fss_uv_material_density`, `fss_uv_material_density_use`) and the sun switch (`fss_uv_material_use_visibility`, `material_uses_visibility()`: off, its islands count as fully visible on every object); the same sun on zones, parents and objects (`fss_uv_use_visibility`, `uses_visibility()` and `visibility_off_source()` walk up the parents: off anywhere above wins). The texture set list (`FSS_UL_TextureSets`, a UIList over `bpy.data.materials` whose `filter_items` shows the selection's materials, active object's first, so drawing writes nothing; active row in `WindowManager.fss_uv_pack_active`) shows each set's last result of the session; the active row's box below carries Size, Margin, Keep UVs, **Pack** (`fss.uv_pack_texture_set`, undoable) and Last run; **Check All** (`fss.uv_pack_check_all`, modal, one set per step, progress bar with Cancel and Esc) measures every set without writing. One draw (`_PackingSection`) serves `FSS_PT_uv_marks` (3D viewport) and `FSS_PT_uv_marks_image` (Image Editor's UI region). Marks of earlier versions (`fss_uv_density`, `fss_zone_density`, the margin fraction `fss_uv_margin`, and before 0.33.0 `fss_uv_texture_width` / `_height`, which become the larger of the two) are converted on file load and at register |
| `uv_pack.py` | (core of **UV Auto Packing**) | The packer per texture set (decisions 112 to 121; it takes a material, never the selection): every face of one material in the view layer, islands by exact UV equality and split by material, each scaled to target x `uv_marks.density()` x visibility (`visibility_core.score_face_set`, floor 0.1) at one t per set; Blender's Pack Islands (`scale=False`, ADD margin, ORIGINAL_AABB region set by anchor triangles, CONCAVE with bounding-box proxies and an AABB fallback) on a temporary mesh, so the source selection, modes, pins and UV maps stay; every pack also places the islands on a raster (`uv_fill.py`) and the smaller layout counts; overflow spills into [0, k]^2; square sizes, needed size 256 to 8192 or "does not fit even at 8192"; `measure()`, `pack()`, `texture_sets()`, the **FSS Packing Report** text; `FACE_AREA_MIN_CM2` for faces without area; triangles with 3D area but no UV area (`UV_TRI_AREA_MIN_PX2` 1e-6 px^2, or a line by `FLAT_RATIO`) inside islands with UV area counted per set and warned about (`uv_zero_faces()`, `MeshData.uv_zero_faces()`). Since 0.97.0 the islands are placed by the FSS packer in C++ (`uv_fill.py`, below), not Blender's Pack Islands: the native UV packer journal is the current design |
| `uv_fill.py` | (core of **UV Auto Packing**) | The FSS packer (native UV packer journal, steps b to d): islands placed on a raster into the free space between and inside each other, turns, Scale to Fill, Object Priority, the repair of islands outside the texture and the straightening of Free islands, done by `lib/uv_pack/windows-x64/fss_uv_pack.dll` (source `native/uv_pack/`, required: without it Pack and Check refuse with the reason); Python keeps the setup and the islands that fit nowhere |
| `uv_align.py`, `uv_align_draw.py` | **UV Auto Packing** (marks in Edit Mode menus) | UV Align marks (native UV packer decisions 7 and 12): edges marked Horizontal, Vertical or Either (edge attribute `fss_uv_align`) that the packer turns along that axis; `uv_align_draw.py` draws them in the 3D view and the UV editor from numpy copies made in a timer, never touching the BMesh while drawing (native UV packer Session 10) |
| `uv_islands.py`, `uv_problems.py` | **UV Auto Packing** | The island list of the active object (each island as the packer forms it, its multiplier and density; a click selects its faces) and the problems of a texture set, one row each (shared meshes left out, users without a material, faces without UV area or without area) |
| `uv_autoseam.py`, `uv_autoseam_core.py` | **UV Auto Seam** | Proposes UV seams on hard surface meshes keeping the current seams, normal splits, and distortion limits; Accept Proposed, Discard Proposed, Clear Current, Edit Mode selection, and report in Text Editor |
| `visibility.py`, `visibility_core.py` | **UV Auto Packing > Visibility Scoring** | Probe-light visibility (UV decisions 124 to 130): included point, spot and area lights score each face by the brightness EEVEE shows (power, distance, cone, light threshold), shadows from cube maps rendered at each light, soft shadows from samples over the light's radius, the brightest of 2 to 10 animation steps; an island takes a weighted percentile of its faces, the most visible island is 1.0, every score is lifted by the Ambient (the floor Pack used to apply), and a darker touching island rises to its neighbour over the Step Limit (never lowered; UV decisions 133, 134); writes `<blend_name>.visibility`, Select Never Seen, Select Stale, report in Text Editor |
| `ao_bake.py`, `ao_bake_store.py`, `ao_bake_apply.py`, `ao_bake_core.py`, `ao_bake_runner.py`, `ao_bake_copy.py`, `ao_bake_jxl.py`, `ao_bake_native.py` | **Bake** with **Run** | The bake of masters and their Apply into the texture sets (auto-bake journal, decisions 9 to 95): AO, curvature (CM) and the material channels Albedo, Roughness, Metal and Emissive, each from the scene (AO), the material or the vertex colour, stored per mesh in `<blend_name>.bake/` and copied into the textures by Apply. Start with [Bake: Current Design](#bake-current-design); the older sections below give the details of the options, FSS OptiX and the JPEG XL masters |
| `uv_heatmap.py` | **Heatmap** (tab FSS Tools) | Viewport heatmap: Distortion (conformal singular-value ratio), Density (relative to material median and object range), and Visibility (from `<blend_name>.visibility`), RizomUV-style diverging colours, legend, and evaluated Mirror/Array support |
| `checks.py`, `name_check.py` | **Checks** (tab FSS Tools) | **Scan Names** (lists object and bone names that break FSS naming rules and renames them in batch; `@MERGE_` / `@NOMERGE_` allowed), **Fix Broken Bone Parents**, **Find Faces Without Area** (selects mesh objects, and their faces, with a world-space face area of at most 1e-6 cm^2) and **Find Faces Without UV Area** (selects mesh objects, and their faces, with a triangle without UV area inside an island with UV area, per texture set at its size: the needles that push islands out in packing), **Find Bent N-gons** (selects mesh objects, and their faces, with an n-gon of 5 or more corners whose split has a triangle more than 30 degrees off the face or without area: slivers that bake dark and shade wrong; auto-bake decision 104) and **Find Animations Not 0 to 100** (selects objects whose action or NLA strips break the project's frame rule, changes nothing) |

## Tags

A tag is any name the artist chooses; nothing is inferred and nothing is MSFS-specific. An object can carry several
tags. Tags are used by the merge (per-tag skip-merge toggle) and are meant for further tools.

## Merge Groups

At export, a node named `@MERGE_<name>` and its subtree become one mesh named `<name>`. The `.blend` keeps every part
as its own object.

- **Roots:** any node. A mesh root merges its own geometry too; the result takes the root's place and parent,
  including a parent bone.
- **Walk:** the whole subtree below the root. It stops at, and keeps as their own nodes with their subtrees: a nested
  `@MERGE_` node (it merges on its own and becomes a child mesh), a `@NOMERGE_` node, and nodes that are animated,
  skinned (armature or armature modifier), bone-parented, have shape keys, are not meshes or empties, or carry a
  "don't merge" tag. A root that is animated or skinned leaves its group unmerged with a warning.
- **Placeholders:** a node that the merge removes but that has a kept node below it is replaced by an empty with the
  same world matrix and name, so kept nodes (animated buttons) keep exact transforms.
- **Transparent parts** (MSFS alpha mode Blend, or Blender's Blended render method) never share a mesh with opaque
  ones: they become `<name>_TRANSPARENT`, a child of the merged mesh.
- **Geometry:** evaluated meshes (modifiers applied) joined with numpy: positions, faces, material slots mapped to the
  original materials, UV maps by name, the active colour attribute, and corner normals as custom normals.
- **Markers never reach the glTF:** merged meshes are named without them, and the node and mesh hooks strip
  `@MERGE_` / `@NOMERGE_` from every exported name. Animation names are left as authored.
- **When it runs:** in `pre_export_hook`, only where the exported objects are throwaway (multi-exporter duplicates, or
  any background run); an interactive plain glTF export is left unmerged with a warning.
- **Reporting:** one summary line per group plus warnings (several materials, opaque and transparent parts, more than
  two UV maps, a merged name equal to a kept node). In background runs these also go to stderr, so deploys show them
  on the console; per-node details stay in the export log.
- **Known trap:** the merge does not read the model XML. A node the XML refers to (a screen, a clickspot) is merged
  away unless it is tagged, marked `@NOMERGE_`, or kept for another reason.

## LOD Marks and Size Culling

The deploy script chooses whether LODs are written: a LOD deploy script writes `_LOD00` up to the last non-empty
LOD; the existing single-file deploy is unchanged and ignores marks. Migrating a model means deploying it with the
LOD script under a name without `-LOD00` and updating its model XML `<LODS>` entries.

Unmarked objects use Auto. `fss_lod = n` means **hidden from LOD n**, with no conversion of existing marks.
`fss_lod_show_from = n` means visible from n; `fss_lod_keep = 1` means Keep. Assignment clears the other own
mark properties. A tag's Keep toggle has the same size protection as an object's Keep mark.

A parent's visibility interval limits its descendants. Keep protects its Auto ancestor chain against size culling;
other small children can still disappear. An explicit hidden ancestor wins, with a **Keep under hidden ancestor**
warning. Animated, skinned and Don't Merge objects follow the same visibility rules.

Part size is the largest dimension of the evaluated subtree's world bounding box in metres. For LOD k above zero, Auto
parts disappear below the LOD's **Hides Under** (`hide_sizes`). A value of 0 takes
`LOD sphere diameter * pixel threshold / (SDK table[k-1] * screen height)`, with the SDK aircraft table 100, 75, 55,
35, 8, 5, 1 percent, and Refresh writes it in. On throwaway export meshes (for LOD01–06),
disconnected mesh pieces (evaluated connected components) whose own largest world bounding-box dimension is below
that same cut-off are also dropped before `@MERGE_` groups run; `Keep` on an object or tag protects all of its
pieces, and skinned or shape-keyed meshes keep all of their pieces.
**Neither the XML minSize nor the vertex count affects membership.**

**Export Settings** draw one table per LOD: Hides Under, minSize % and Shows From (the effective minSize at the chosen
MSFS Quality), plus the model diameter measured by **Refresh LOD Counts**, Show LOD Sphere and **Pad LOD Sphere
Multiplier** (`pad_factor`, 1 to 10, of the geometry's sphere). Every model has the same rules; there is no model type.

The minSize table defaults to 7, 6, 5, 4, 3, 2, 1 percent (`lod_rules.MSFS_MIN_SIZES`, the SDK's convention): the vertex
rule decides when a LOD shows, and a high value only holds a LOD back. Both simulators get the same table; MSFS 2020's
second-to-last entry is at least 1 percent, and its vertex rule is assumed the same, unverified. The first empty LOD ends
the list; later visible-from objects produce a warning, not more files.

The **Viewport LOD** panel's buttons 0–6 preview the same object membership as export (whole objects only, absent objects hidden or displayed as bounds,
`fss_lod_preview_display`; dropped loose pieces are counted in the panel and removed at export); **Auto** computes the model's
bounding-sphere screen ratio from the active 3D viewport (vertical FOV and camera distance, matching
`lod_tools_msfs_2024`), picks the LOD from the effective `minSize`, and applies the filter only when the active LOD
changes. **Off** unhides and restores original display types; the Excluded row (Hidden / Bounds) shows only while a
preview is on. The preview is restored before saving and on file load, so saved files
never carry it and all export paths see visible objects. **Refresh LOD Counts** caches object
counts, cut-offs, estimated glTF vertex counts (accounting for UV/normal corner splits, piece dropping, and shared
instances), and per-LOD hints; it also runs when a file opens (`autorefresh.py`). **LOD Settings** draws what MSFS does at
the Blender view, with or without a preview (`update_view_ratio` keeps the screen ratio from a timer): MSFS Quality, the LOD
shown, and the table LOD / Vert/Obj / Used / ToReduce / Reduced. The limit at a ratio is `lod_rules.vertex_quota_at`.
The **Hints** subpanel draws **Per LOD Vertex Contributors** (a share bar per contributor, then the loose pieces below and
the parts near the cut-off, each with a **Select** button). **Print LOD Settings / XML** prints only the XML entries for
written LODs, for maintainer review without modifying any model XML.

The export driver calls `lod_model.build_plan` once, then `begin_export` for each nonempty LOD up to LOD06. The shared
pre-export hook culls before merging, even when Merge on Export is disabled. The driver starts each export from
an intact source scene and calls `report_file` on the written glTF. Console counts sum distinct POSITION accessor
counts (stored geometry, instances counted once). Limits and the effective minSize use the SDK curve (High as measured; the other qualities by the SDK's table);
MSFS's actual counting of seam splits and instances remains unverified. No polygon reduction is performed.

## Auto Seam

Automated hard-surface seam placement for untextured geometry (`uv_autoseam.py` operators and UI,
`uv_autoseam_core.py` seam placement algorithm). Operates on selected mesh objects in Object Mode.

- **Non-destructive:** proposes seams without modifying existing artist seams or changing UV maps.
  Proposed seams are tagged with the boolean edge attribute `fss_auto_seam` and written as Blender edge seams.
- **Progress:** while Propose Seams or Accept + Unwrap runs, the panel shows only a progress bar (module state
  `_progress`; weighted by face count) and Cancel (`fss.uv_cancel_auto_seam`, acts between meshes like Esc). Inside
  one mesh the core reports its stage through `propose_seams(progress=...)`, at most every `PROGRESS_INTERVAL`
  (0.25 s), from the trial unwraps and each stage start (`PROGRESS_STAGES` with measured average shares); the
  operator then draws only the sidebar with `bpy.ops.wm.redraw_timer(type='DRAW_SWAP')`, because the window shows the
  core's temporary scene during a mesh. Buttons are shown by the selected meshes' seam counts (`seam_buttons`,
  cached per mesh in `_count_cache`, dropped by the seam writers and the depsgraph handler).
- **Workflow:** **Propose Seams** computes seams modally with progress reporting. Seams are **proposed** (marked
  `fss_auto_seam`) or **current** (all others; internally artist seams). **Accept Proposed** removes the mark,
  **Discard Proposed** removes the proposed seams, **Clear Current** removes the current ones (confirmation), and
  **Select Proposed** / **Select Current** select them in Edit Mode. Accept, Discard and Clear switch to Object Mode
  for their work when clicked in Edit Mode.
- **Distortion Limit:** the scene property `fss_uv_autoseam_limit` (saved with the file; default `THR` = 1.25,
  allowed 1.05 to 2.0, slider 1.05 to 1.75) is passed as `limit` to `propose_seams` (every merge and
  verification test), to the final-unwrap check and to the report, which states it. Measured on the 17 reference
  objects in journal Session 87.
- **Accept + Unwrap** (`fss.uv_accept_and_unwrap`, confirmation): accepts the proposed seams, then
  `unwrap_angle_based` unwraps one user per mesh in a single multi-object Edit Mode pass with Angle Based (the
  method the core verifies with); faces whose material is a skip class keep their UVs; mode, selection and active
  object are restored; objects with non-uniform scale are named in a warning.
- **Exclusions:** objects whose materials are all in decal, glass, windshield, invisible, or occluder
  classes (by name class or MSFS material type) are skipped automatically.
- **Reporting:** overwrites the text datablock `FSS Auto Seam Report` with execution totals, listing meshes
  needing manual attention first with plain-language recommendations.
- **Design and history:** documented in [../docs/journal/20261019.automated-uv-unwrap.md](../docs/journal/20261019.automated-uv-unwrap.md).

## UV Heatmap

Per-face distortion and texel density on the model, for inspecting UV quality (`uv_heatmap.py`). Operates on selected
mesh objects.

- **Drawing:** while shown, the heatmap's objects are displayed as wire (`display_type`) and the heatmap draws their
  surface itself, opaque and lightly shaded, with its own GPU shader (`gpu`), so there is no second surface to
  z-fight with. The display type is the only setting changed; it is restored when the heatmap is off, the object is
  deselected, in Edit Mode, before saving, after undo or redo, and when the add-on is disabled. Selection changes
  are followed through a `depsgraph_update_post` handler and a timer. No mesh or material data are written.
- **Evaluated geometry:** loop triangles of the evaluated mesh, including copies from Mirror and Array modifiers;
  measures in world space, drawing in object space with the object's current matrix (it follows moves).
- **Modes:**
  - **Distortion**, views Both / Shear / Area (`fss_uv_heatmap_distortion`): shear is the per-triangle conformal
    distortion (\(\sigma_1 / \sigma_2 \ge 1.0\), scale-independent), white to blue; area is the triangle's
    \(A_{UV} / A_{3D}\) against its UV island's, folded to \(\ge 1.0\) (`uv_islands`, `area_distortion`; the
    island average equals `uv_autoseam_core._area_distortion`), white to green up to `AREA_TOP` 2.0; both blend
    bilinearly to cyan. The chart counts islands whose average is over Auto Seam's current Distortion Limit.
  - **Density:** per-triangle texel density (\(A_{UV} / A_{3D}\)) relative to its texture set, the area-weighted
    median over every object in the view layer that uses the same material, read against the object's authored
    density range from `uv_marks.density()` (inside the range neutral 1.0, above up to 2.0x blue, below down to 0.5x red,
    log scale).
  - **Error** (degenerate faces): faces with zero 3D or UV area, drawn in magenta and counted separately.
- **Updates:** results are cached per object and recomputed when the object's geometry or UVs change (a
  `depsgraph_update_post` geometry update) and for newly selected objects; texture set references are cached per
  material. **Refresh** recomputes everything (after scale or material changes).
- **UV grid:** optional cell borders in UV space (8 to 64 cells) with cell labels (column letter, row number) from a
  glyph texture drawn with `blf`; labels fade in for cells of 22 to 34 px on screen.
- **Panel chart:** a square card drawn offscreen into a preview image (`bpy.utils.previews`): area-weighted histogram
  (square-root heights) over the colour band, marks at 1.10 and 1.25, the range of the middle 90 % of the surface,
  and the shares over the limits.
- **Legend:** viewport corner text with the mode, the scale, the shares beyond the limits, the error count, and
  objects skipped because they have no UVs. Hidden in Edit Mode.

## Bake: Current Design

The entry point for an agent continuing the bake (0.107.0, auto-bake journal decisions up to 95). The decisions and
their reasons are in [the auto-bake journal](../docs/journal/20261112.auto-bake-ao-curvature.md): read its latest
session first, then the sessions named here. The artist's view is in [the artist guide](../docs/user/bake.md).

**What it does.** A master is the baked values of one mesh (or one shared mesh) in a layout of its own, at 4 x the
median texel density of its texture sets, so it survives UV changes; Apply copies it into the texture set's textures
in whatever UV layout the set has then. The Object UV layout (decision 107) bakes it in the object's UVs instead. Masters live in `<blend_name>.bake/` beside the `.blend`, with `index.json`
(one entry per master: hashes, grades' inputs, the baker, the channels).

**Channels and their sources:**

| Channel | Baked from | Files (`<stem>.<kind>.jxl`) | Apply target (in place / separate file) |
| :--- | :--- | :--- | :--- |
| AO | the scene, traced (Cycles or FSS OptiX), poses and copies combined, denoised | `ao` (+ `ao.raw` before the denoise, `ao_vc` the vertex colour product) | ORM red / grey or ORM-layout file |
| CM (curvature) | the geometry, in the AO's layout | `curv` | `<material>_curvature.png` (or the set's own name) in its output folder |
| Albedo | the material (Base Color, before the MSFS `.Apply AO Group`), the vertex colour or the object's Custom colour | `albedo_r`, `albedo_g`, `albedo_b` (sRGB-encoded) | base colour slot / `<material>.albedo.png` |
| Roughness, Metal | the material (Roughness, Metallic), the vertex colour's green, blue, or the object's Custom value | `rough`, `metal` (linear) | ORM green, blue / `<material>.roughness.png`, `.metal.png` (grey 16-bit) |
| Emissive | the material (Emission Color, not its strength), the vertex colour or the object's Custom colour | `emis_r`, `emis_g`, `emis_b` (sRGB-encoded) | emissive slot / `<material>.emissive.png` |

Every channel shares the master's layout (`<stem>.ao.npz`, `<stem>.ao.map`). Decision 81: a bake keeps the layout
while the mesh is unchanged (the mesh hash ignores UVs); a new layout (mesh changed or no master) removes the channels
that bake does not bake.

**The flow:**

1. **Refresh** (`ao_bake_store.refresh`): per mesh with a texture set an item with its key (stem), mesh hash,
   surroundings hash (occluders by the scene rule in C++, poses, copies, settings), grade (`UP_TO_DATE`,
   `SURROUNDINGS`, `MESH`, `MISSING`), the curvature's and denoise's grades and a grade per material channel
   (decision 80: only the mesh makes one stale). Shared meshes: one item, its copies listed; One Instance bakes the
   copy chosen from the selection (decision 77, `bake_instances`).
2. **Bake** (`FSS_OT_AOBakeStart`, through Run): a job (`make_job`, the ticked channels, the vertex colour sources)
   for a second Blender on a snapshot of the file (`ao_bake_runner.py`, never saved): per master the layout
   (`layout_for`), the AO in tiles and bands (Cycles, or `aobaker.exe` through `ao_bake_native.py`), then the
   curvature, the denoise and the channels (`channel_item`: a temporary mesh of the master's triangles with every
   attribute of the evaluated mesh; an Emission material routed from the Principled BSDF's socket, or from a Color
   Attribute node for a vertex colour source; Cycles `EMIT` at Channel Samples, default 64).
3. **Apply** (`ao_bake_apply.py`, through Run): per texture set and ticked channel, `ao_bake_core.copy_master` in the
   C++ DLL (`ao_bake_copy.py`, `lib/ao_copy/`, source `native/ao_copy/`), with padding (decision 78: beyond a fold
   over 30 degrees the padding continues its own face), Soften and the per-object rule; a channel whose mesh changed
   is applied anyway, with a warning (decisions 73, 85); faces without a master keep their pixels.
4. **Fetch** (`fss.ao_fetch_vertex_color`, in `ao_bake_apply.py`): the masters read at every face corner into the
   colour attribute named by Read (decisions 93, 94).

**Vertex colour sources** (decisions 88 to 95): per channel a checkbox (AO from red, Roughness from green, Metal from
blue, Albedo and Emissive from RGB), Overwrite or Multiply (Multiply edits the master, compounds, and acts as Overwrite
without a master), the attribute read by name in the snapshot: the mesh's second colour attribute by default (Read),
or the active one; values linear. The exporter writes one colour attribute per mesh (the render one; the merge and
MSFS 2020 the active one), so the second is not exported while it is neither.

**Custom values and colours** (decisions 99, 100): Albedo, Roughness, Metal and Emissive take Material, Vertex Color
or Custom as one choice (`<g>_source`, kept in the `vc_<g>` and `cv_<g>` booleans). Custom bakes the object's own
`fss_ao_bake.<g>_value` (a linear colour for Albedo and Emissive; the copy the channels come from, sent per job item as
`custom_values`); Overwrite by default, Multiply as for a vertex colour source; a Custom emissive is not combined over
a shared mesh's copies. Decision 101: a Custom channel is written straight into the master without Cycles. A kept
layout: the value on exactly the stored map's filled pixels (the baked ones and their margins, what Apply reads), 0
elsewhere, the stored codes kept (`_MapRows`); the map's filled pixels are not fed back as baked ones, which would grow
the margin twice. A new layout: the pixels Cycles fills for another group of the bake, else the core's and the skirt's
by `raster_window`, composed as a baked channel (the map is written from them). Samples 0 in the index, baker `Custom
value` when no channel needed Cycles; `FSS_AO_BAKE_CUSTOM_CYCLES` (tests) bakes it through an Emission shader as
before.

**Visibility** (decision 102): the targets and occluders are the meshes the view layer shows, whatever a 3D view
shows (`ao_bake_store.shown`: the collections' exclude and hide flags, the object's `hide_viewport` and `hide_get`),
not `visible_get`, which follows the local view of the 3D view an operator runs in. A bake started in local view thus
takes the same objects as the Refresh at file opening, which has no 3D view.

**Required libraries:** `fss_ao_copy.dll` and libjxl (`lib/jxl/`); without them the panel says why and its operators
refuse (apply-native-copy decision 6). FSS OptiX (`lib/ao_baker/`, Git LFS) is optional: Cycles bakes without it.
Building `native/ao_copy` uses `build.cmd` under the CPU rule of the maintainer's global instructions
(`cpucap.exe 50`, at most 12 compiler threads).

**Entry sessions of the journal:** 15 (the master's design), 17 to 23 (storage, tiles, paging), 29 and 37 (poses,
occluders, shared meshes), 50 to 52 (Run panel, apply anyway, the panel named Bake), 56 to 58 (One Instance), 60
(padding at folds), 61 to 75 (material channels, Run grid, vertex colour sources, Fetch). Tests: `tests/test_ao_bake.py`
(`test_material_channels`, `test_vertex_color_channels`, `test_vertex_color_fetch` for the newest work), `tests/test_panels.py`,
`tests/test_ao_copy_native.py`, `tests/test_ao_bake_native.py`, `tests/test_ao_bake_native_job.py`; the reference
values in `tests/data/` are locked (never record them again).

**Open:** the received-light emissive (decision 83, a later hand-off); the maintainer's feedback on the material
channels and vertex colours in a live Blender (Sessions 63, 69, 75 list what was not verified).

## AO Bake Options

The AO Bake panel's options (auto-bake journal, decisions 34 to 36), each a scene setting; poses and occluders also
per object, under the panel's **Object** box for the active mesh (`fss_ao_bake` on the object, so the glTF extras
leave them out):

- **Default Poses** (scene, 5; per object **Poses** Default or Manual with a number, stored as `poses`, 0 for the
  default; shown only for a mover whose occluders are not Self Only, which is baked in one pose): a mover (animated, under an animated parent, or
  tagged Animated) is baked in N poses spread evenly over its own animation range, both ends included, or without
  its end when both ends are the same pose, as a full turn (decision 41; read from the F-curves of the action or the
  one NLA strip of the object and each animated parent; anything else keeps both ends) (the actions
  and NLA strips of the object and its animated parents; not the project's 0 to 100 rule), and the poses' AO is
  averaged per pixel. The layout and the mesh are the current frame's; per pose the target is placed by its world
  matrix at that frame relative to the current frame. Each tile is baked in every pose before the next tile, summed in
  the tile's own buffers, so memory does not grow with N; time grows N times. Pose p adds `POSE_SEED` x p (7919) to
  both seeds. N = 1, a mover without a range (a driver only, the Animated tag without keys) and a mover whose mesh
  deforms between poses (shape keys, an armature) are baked in the current frame; the last two are said in the bake
  report.
- **Default Occluders** (scene: Scene Rule or Self Only; per object Default (naming the scene's), Scene Rule, Self
  Only or Custom): Scene Rule is decision 15's (visible static
  meshes near the object; movers, Non-AO-Occluder, Invisible and No Export objects cast no AO); Self Only bakes the
  object alone; Custom takes the object's own list (Add Selected, Remove, Clear), whatever the objects' tags, and
  poses its movers at the same frame as the target in every pose.
- **Run In** (Background, the default, or Foreground; stored as `HIDDEN` and `VISIBLE`): Hidden starts the second Blender in the background without a window or
  console; Foreground with FSS OptiX keeps it in the background and opens FSS OptiX's window (OptiX baker decision 28),
  with Cycles it opens the second Blender's window, whose 3D views are turned into empty Image Editors so the scene is
  not drawn. Blender shows no preview of the master being baked (OptiX baker decision 30): the panel shows object,
  tile and pose (`Pose p of N`), time and Cancel; FSS OptiX's window shows the master as its tiles finish.
- **Staleness:** a changed pose count (for a mover), occluder mode or custom list makes the master "surroundings
  changed". At one pose with the scene rule the hashes are those of 0.57, so its masters stay up to date.
- **No picture of a master in Blender** (OptiX baker decisions 30 and 31): while a bake runs the panel shows only its
  progress (the bake buttons return when it ends); the Object box says who baked the active object's master ("Baked
  by ...") or "No master baked yet", with no picture: a master's layout is not the artist's UVs, so its image misleads.
  The thumbnails of 0.60.1 to 0.77.2 (`<stem>.ao.thumb`, auto-bake decision 43) are no longer written or read; a bake
  removes the master's old one.
- **Apply box** (decision 40): with objects selected the texture-set list shows only their sets (all when nothing is
  selected); the box names the set it is for (the selection's only set, else the highlighted row). Separate File shows
  the file name, resolution and layout; ORM Texture shows the slot's texture, read only. The set's Apply is disabled
  (and refused) when its target cannot be written: no ORM texture or its file missing, or an output folder that
  cannot be made.
- **Shared meshes** (decision 47; scene setting Shared Meshes, default Average, overridden on the mesh by
  `Mesh.fss_ao_shared.combine`, shown in the Object box of any copy): a mesh used by several baked objects still has
  one master, but every copy is baked in its own surroundings (its own occluder setting and list, its own poses when
  it moves). Refresh keeps per copy its occluders, poses and surroundings key (`item['copies']`); the master's
  surroundings hash covers the combine choice and every copy's key, so moving one copy or its neighbours makes the
  master stale. The runner (`setup_copies`) makes one view per copy and pose: the target placed at the copy (relative
  to the first copy, whose world positions it has), with only that copy's occluders rendered (each occluder built
  once, shared between copies' lists; other copies of the same mesh occlude like any object). Per tile, a copy's
  poses are averaged, then the copies are combined per pixel: their average, the lightest (Most Lit) or the darkest.
  Each view has its own seed. Cost: one bake per copy and pose.
- **Soften Sharp Edges** (decision 46; scene setting, off by default, Width 0.3 mm): Apply treats convex sharp edges
  as slightly rounded. `ao_bake_core.soften_context` finds, once per master, the welded edges whose faces differ by
  more than 30 degrees (the copy's surface angle) and whose far corners each lie behind the other face, and per
  triangle of the set its width (the setting, at least one target texel of that triangle) and the edges near it (a
  KD-tree of points along the edges). `_soften` then raises each inside and padding pixel within the width of such an
  edge, on the darker side only, toward the brighter side's value at the nearest point of the edge (both read from
  the master), by a smoothstep that is 1 at the edge and 0 at the width; near several edges the largest raise wins.
  The brighter side, concave corners and the masters are unchanged; the report counts the pixels raised.
  Decision 103: an edge of a flat triangle (its far corner within `SOFT_FLAT`, 1 um, of the edge: an n-gon's fan
  triangle over corners in a line) is no fold, its normal being no direction; a concave fold's slopes are read over a
  step of at least `SOFT_SLOPE_MIN_STEP` (0.1) of the width, else left out (the DLL), where a thin face's step of
  1 nm had made them, and the value, 0 or 1.
- **Falloff Curve** (decision 105; scene setting `falloff_curve`, default Linear, used with Distance Falloff): Linear,
  Sharp, Smooth or Root, the weights of Blender's proportional editing: an occluder at t darkens by w(1 - t / d),
  `ao_bake_core.falloff_weight`. Cycles bakes the Steps' distances from `falloff_distances` (Linear: d x 1/n ... 1,
  the same floats as decision 53; another curve: where the weight is (n - 1)/n ... 0, so the n bakes averaged are a
  staircase at most 1/n over the curve); FSS OptiX takes the curve's code in the scene header's `falloff` (scene
  version 2) and counts each hit 1 - w(1 - min(t / d, 1)). A curve other than Linear adds `falloff_curve` to the
  surroundings key, so masters baked without it keep their hashes.
- **Strength** (decision 106; scene setting `ao_strength`, default 1.0): Apply writes the AO as 1 - s (1 - v), after
  Soften, inside and in the padding; curvature and the material channels are not scaled. The report says the
  strength when it is not 1.
- **Master Layout** (decision 107; scene setting `master_layout`, default `AUTO`): `OBJECT_UV` bakes an object whose
  baked faces are in one texture set in its own UVs at `OBJECT_UV_SCALE` (4) master pixels per texture pixel each way
  (`ao_bake_core.object_uv_layout`: UV islands by union-find over edges with equal UVs, shelf-packed in whole texels
  with a one-texel margin, not turned; skirts as in `build_master`). The meta's `object_uv` holds the scale and each
  island's offset (master UV = texture pixels x 4 - offset). The surroundings key adds `master_layout` with the SHA-1
  of the set faces' UVs and the texture size, so a UV or size change grades the master Surroundings changed. Apply
  (`_object_uv_box_ok`, `object_uv_box`) writes each covered texel the mean of its 4 x 4 master pixels, per island,
  without Soften; when the UVs moved since the bake it copies face by face and warns.
- **Blend at texels across faces** (decision 108; `ao_bake_core.APPLY_BLEND`, True): the C++ copy
  (`fss_ao_copy_inside_blend`) reads each sub-sample from the triangle covering it, not from the texel's owner, at
  least `BLEND_MIN_LEVEL` (4) sub-samples per axis. The locked references were recorded with the owner rule: their
  tests set `APPLY_BLEND = False`.
- **Edge Filter** (decision 109; scene setting `edge_filter`, `BOX` default or `ADAPTIVE`, every channel):
  `fss_ao_copy_inside_filter`, only on texels whose sub-samples lie on two or more faces: with s = min(1, the
  largest angle between their normals / 90 degrees), a sub-sample at (dx, dy) texels from the centre weighs
  (1 - 2 s |dx|)(1 - 2 s |dy|). Object UV texels are not filtered.

## AO Bake with FSS OptiX

The panel's **Baker** (OptiX baker journal `docs/journal/20261114.optix-baker.md`, decisions 21 to 25): Auto (the
default), FSS OptiX or Cycles. FSS OptiX is Glider's `aobaker.exe` (built in `F:\glider`, module
`src/modules/ao-baker`), an OptiX 9.1 AO baker on the NVIDIA GPU with its own OIDN 2.5.1:

- **Files:** `lib/ao_baker/windows-x64/`: `aobaker.exe`, `oidn/` (OIDN's DLLs, TBB, the Visual C++ runtime, the
  licences) and `VERSION.txt` (Glider's commit and the build's time), copied from a Glider Release build by
  `tools/update-ao-baker.ps1`; the exe and the DLLs are in Git LFS (a clone needs git-lfs, else the baker is missing
  and Cycles bakes). It needs NVIDIA's driver (CUDA, OptiX, and `vulkan-1.dll` for its window).
- **Client:** `ao_bake_native.py` (no `bpy`): the channel (shared memory with two rings, named events, messages
  1 to 25 of Glider's `AoBakeProtocol.h`), the scene, curvature and denoise blocks, and `Baker`, which starts the exe
  for a job (`--headless`, or with its window in a Foreground run) and says why when its GPU does not work
  (`FSS_AO_BAKER_NO_CUDA` makes it start without one; `FSS_AO_BAKER_EXE` points at another exe; both for tests).
- **The runner:** with Auto or FSS OptiX and a working GPU, each master's scene is sent once (the target, the
  occluders as arrays, the views of its poses and copies, built as for Cycles), and each tile is one request whose
  answer is the core's and the skirt's AO with the views already combined; the composition, bands, Cancel
  (also inside a tile) and writer are unchanged. The scene names the master's size, from which the baker makes its
  window's preview of the finished tiles itself (OptiX baker decision 29; the window and app are titled FSS OptiX). The curvature (byte-identical to `ao_bake_core.write_curvature`) and
  the OIDN denoise (islands isolated, each area's mean kept, no pixel moved further than its noise) run in the baker.
  It bakes at **FSS OptiX Samples** (default 4096; Cycles keeps its own Samples). When the exe is missing or its GPU
  does not work, Cycles bakes the job; when the baker fails on a master, that master and the rest of the job bake with
  Cycles. The log and the bake report say which baker baked and why Cycles did.
- **The index:** each entry's `baker` (name, version, device; for FSS OptiX its trace and scene times) and its
  curvature's and denoise's `baker`; the panel shows it under the active object's master. A master baked by the
  other baker is not stale.

## AO Bake Masters as JPEG XL

A master's AO image is `<stem>.ao.jxl`, 16-bit grey, lossless JPEG XL (auto-bake journal, decision 37; about 40 %
smaller than the PNG of 0.55). It is encoded and decoded by the reference library, libjxl, shipped in this add-on:

- **Files:** `lib/jxl/windows-x64/`: `jxl.dll`, `jxl_threads.dll`, `jxl_cms.dll`, `brotlicommon.dll`,
  `brotlidec.dll`, `brotlienc.dll` from libjxl 0.12.0's release asset `jxl-x64-windows.zip`
  (`github.com/libjxl/libjxl`), unchanged; Highway is linked into them. Their sizes and SHA-256 are in the
  auto-bake journal, Session 27. They need the Microsoft C++ runtime (`msvcp140.dll`, `vcruntime140.dll`), which
  Blender ships and has loaded.
- **Licences:** `LICENSE.libjxl` (BSD 3-clause), `LICENSE.brotli` (MIT), `LICENSE.highway` (Apache 2.0),
  `LICENSE.skcms` (BSD 3-clause, inside `jxl_cms.dll`), in the same folder; they travel with every deployed copy.
- **Access:** `ao_bake_jxl.py` loads the DLLs with `ctypes` (no Python package). Encode: the bake writes the rows to
  a raw scratch file (`<stem>.ao.jxl.tmp.raw`, 2 bytes per master pixel, deleted afterwards), then libjxl's chunked
  frame input reads it a rectangle at a time and an output processor writes the file as it goes; effort 7, at most
  the bake's thread setting. Decode (Apply): the file is fed in chunks and the pixels arrive through the image-out
  callback into Apply's tiled scratch files. Neither holds the whole image.
- **Without the library** (another OS, a missing file, or `FSS_AO_BAKE_NO_JXL` set for tests) the bake writes
  `<stem>.ao.png` as before and the bake report says so once. PNG masters (schemas 1 and 2) are read and applied
  as they are; a re-bake replaces one with a `.jxl` and removes the PNG.

## Testing

Background Blender with a synthetic scene that covers: nested groups, a mesh root, an animated child, a tagged child,
a `@NOMERGE_` child, a transparent part, a bone-parented root, and an animated root. Export through the multi-exporter
and the plain exporter into a scratch folder, and compare with the same scene exported with Merge on Export off:
world positions of kept nodes, merged vertex and triangle counts and bounds, animations, and that no exported name
contains a marker.

## Decisions

Rationale and history are in this repository's journals ([../docs/journal/](../docs/journal/README.md)): tags and merge groups in `20261014.fss-blender-tools-tags-and-merge.md`, the wish-list in `20261010.fss-blender-tools-wishlist.md`, LOD in `20261010.automated-lod-generation.md`, UV seams, heatmap, visibility, density and packing in `20261019.automated-uv-unwrap.md` (start with its Session 102, which indexes the decisions in force), and the Materials panel, the sidebar tabs, refresh on opening and the LOD panels' layout in `20261028.material-management.md`; the bake in `20261112.auto-bake-ao-curvature.md` (see [Bake: Current Design](#bake-current-design) for its entry sessions), `20261114.optix-baker.md`, `20261114.apply-native-copy.md` and `20261116.bake-post-native.md`; the FSS UV packer in `20261116.native-uv-packer.md`.
