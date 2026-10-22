# FSS Blender Tools

Authoring tools for FSS aircraft in Blender 5.2, in the 3D View sidebar tab "FSS Tools". Independent of the Asobo
add-ons; the only coupling to the exporter is the glTF user-extension hook in `merge.py`. Working rules for this
repository are in [../AGENTS.md](../AGENTS.md).

## Modules

| Module | Panel (sidebar path) | What it does |
| :--- | :--- | :--- |
| `panels.py` | **UV Tools**, **Utilities** | The two group panels; every section below is a subpanel registered by its module (`bl_parent_id`), with `bl_order` setting the sidebar order: Zones & Merge Tree, Tags, LOD, UV Tools, Utilities |
| `tools.py` | **Utilities > General** | Scene helpers: **Add Empty Parent** (Manual / Suffix / Prefix naming rules), **Origin to Bounding Box** (minimum-volume OBB orientation with 8 corners, 6 face centers and 12 edge centers) |
| `empty_bounds.py` | **Utilities > Empty Bounds** | Draws the bounds of empties' subtrees (`All` / `Selected` / `Off`, `In Front`) and a clickable hierarchy text in the viewport |
| `lod.py`, `lod_model.py`, `lod_rules.py` | **LOD** | Auto size culling (objects and loose mesh pieces), hidden-from / visible-from / Keep marks, Quota and Hints subpanel, scene export settings, and viewport membership preview |
| `tags.py` | **Tags** | Generic object tags (`fss_tags`, semicolon-separated), per-row `[-]`/`[+]` assignment, selection, and per-tag skip-merge and Keep toggles |
| `merge.py` | **Zones & Merge Tree** | Export-time merge groups (`@MERGE_<name>` / `@NOMERGE_<name>`), New Merge Group, tree preview of zones (`@ZONE_<NAME>`), groups and `@NOMERGE_` nodes with Unzoned and nesting warnings, console details; per-zone texel density multiplier (`fss_zone_density` on the zone empty, read with `zone_density()`) |
| `uv_marks.py` | **UV Tools > Packing** (the Skip Auto Seam mark is drawn in Seams) | Authoring marks for UV unwrapping and packing: per-object texel density range (`fss_uv_density`, default 0.9 to 1.1, presets Lower 0.7 to 0.8 and Higher 1.5 to 1.65), island direction (`fss_uv_direction`: Free, Upright, Flip, Quarter), and Skip Auto Seam mark (`fss_uv_skip_autoseam`), inherited from the nearest marked ancestor; per-material island margin as a fraction of the UV square (`fss_uv_margin`, default 0.002) |
| `uv_autoseam.py`, `uv_autoseam_core.py` | **UV Tools > Seams** | Proposes UV seams on hard surface meshes keeping the current seams, normal splits, and distortion limits; Accept Proposed, Discard Proposed, Clear Current, Edit Mode selection, and report in Text Editor |
| `visibility.py`, `visibility_core.py` | **UV Tools > Packing > Visibility Scoring** | Evaluates solid-angle visibility from scene cameras (Look Around cubemap / Fixed View frustum) across 2 to 10 animation states; writes `<blend_name>.visibility`, Select Never Seen, Select Stale, report in Text Editor |
| `uv_heatmap.py` | **Utilities > Heatmap** | Viewport heatmap: Distortion (conformal singular-value ratio), Density (relative to material median and object range), and Visibility (from `<blend_name>.visibility`), RizomUV-style diverging colours, legend, and evaluated Mirror/Array support |
| `checks.py`, `name_check.py` | **Utilities > Checks** | **Scan Names** (lists object and bone names that break FSS naming rules and renames them in batch; `@MERGE_` / `@NOMERGE_` allowed) and **Fix Broken Bone Parents** |

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

Part size is the largest dimension of the evaluated subtree's world bounding box in metres. The automatic
reference diameter is the diagonal of the world bounding box enclosing the LOD00 source set; a scene can supply
an explicit reference diameter instead. For LOD k above zero, Auto parts disappear below
`reference diameter * pixel threshold / (minSize[k-1] * screen height)`. On throwaway export meshes (for LOD01–06),
disconnected mesh pieces (evaluated connected components) whose own largest world bounding-box dimension is below
that same cut-off are also dropped before `@MERGE_` groups run; `Keep` on an object or tag protects all of its
pieces, and skinned or shape-keyed meshes keep all of their pieces.
**Only the XML minSize table affects size culling. Vertex counts never affect membership.**

**Export Settings** present this in physical sizes: the model diameter measured by **Refresh LOD Counts** (or an
**Override Diameter** for parts merged into a bigger model), one field **LODnn hides parts smaller than** for the
lowest-detail LOD (LOD06, interiors LOD05), and the resulting size below which each LOD hides parts, with the
objects and pieces hidden after a Refresh. All cut-offs scale together, so the field stores the pixel threshold
(the inverse of the formula above) and the export is unchanged. The minSize tables, screen height and pixel
threshold are under **Advanced**.

The default exterior table is 100, 75, 55, 35, 8, 5, 1 percent. Settings store ratios (1 means 100 percent).
An interior's derived table needs a positive exterior diameter saved in the scene. Missing it stops export with
**exterior diameter missing**. Editing an explicit interior table removes that requirement. Interior LOD06 has
no objects and is not written. The first empty LOD ends the list; later visible-from objects produce a warning,
not more files. FS20 has its own table, initially following FS24, with its second-to-last entry at least 1 percent;
FS20 values remain unverified in the simulator.

Viewport buttons 0–6 preview the same object membership as export (whole objects only, absent objects hidden or displayed as bounds,
`fss_lod_preview_display`; dropped loose pieces are counted in the panel and removed at export); **Auto** computes the model's
bounding-sphere screen ratio from the active 3D viewport (vertical FOV and camera distance, matching
`lod_tools_msfs_2024`), picks the LOD from the `minSize` table, and applies the filter only when the active LOD
changes. **Off** unhides and restores original display types. The preview is restored before saving and on file load, so saved files
never carry it and all export paths see visible objects. **Refresh LOD Counts** caches object
counts, cut-offs, estimated glTF vertex counts (accounting for UV/normal corner splits, piece dropping, and shared
instances), High quotas, and per-LOD hints in the **Quota and Hints** subpanel (**Largest Contributors**, **Loose
Pieces Below Cut-off**, and **Near Cut-off (Mark Candidates)**, each with a **Select** button); refresh after
editing geometry or marks. **Print LOD Settings / XML** prints only the XML
entries for written LODs, for maintainer review without modifying any model XML.

The export driver calls `lod_model.build_plan` once, then `begin_export` for each nonempty LOD up to LOD06. The shared
pre-export hook culls before merging, even when Merge on Export is disabled. The driver starts each export from
an intact source scene and calls `report_file` on the written glTF. Console counts sum distinct POSITION accessor
counts (stored geometry, instances counted once). Quotas and effective-minSize warnings use the High SDK curve;
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
    density range (inside the range neutral 1.0, above up to 2.0x blue, below down to 0.5x red, log scale).
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

## Testing

Background Blender with a synthetic scene that covers: nested groups, a mesh root, an animated child, a tagged child,
a `@NOMERGE_` child, a transparent part, a bone-parented root, and an animated root. Export through the multi-exporter
and the plain exporter into a scratch folder, and compare with the same scene exported with Merge on Export off:
world positions of kept nodes, merged vertex and triangle counts and bounds, animations, and that no exported name
contains a marker.

## Decisions

Rationale and history: `codes/wasm/doc/journal/20261014.fss-blender-tools-tags-and-merge.md` and
`20261010.fss-blender-tools-wishlist.md` in the FSS aircraft repository.
