# LOD: Automatic Levels of Detail

[Artist Guide](README.md) / **lod.md**
***

The **LOD** panel (sidebar `N` > **FSS Tools** > **LOD**) prepares a model for export as several LOD files. You model the full detail once; the export leaves out parts that are too small to see at each lower level of detail.

## How the Automatic LODs Work

- MSFS picks one whole glTF file per LOD by how large the model looks on screen. It never hides single parts inside a file. So each LOD file must already contain only the parts worth drawing at that size.
- A LOD deploy writes `<name>_LOD00.gltf` (the full model) to at most `<name>_LOD06.gltf`. Each file has the parts of `_LOD00` minus:
  - parts you **marked** hidden from that LOD (or not visible yet),
  - **Auto** parts smaller than that LOD's size cut-off,
  - inside a mesh, **loose pieces** smaller than that cut-off.
- Merge groups are merged after this, per LOD: `_LOD00` merges a panel with its screws, `_LOD04` merges the panel without them.
- No geometry is cut or reduced. Every boundary that disappears is one you modelled. **Model parts as separate objects** (or at least as separate loose pieces) and the LODs follow from their size.
- Vertex counts never decide which parts are left out; only marks and sizes do. Vertex counts are reported so you can see whether MSFS will actually show each LOD (see [Quota and Hints](#quota-and-hints)).

Terms:

- **Part:** an object with everything below it. Its **size** is the largest side of the world bounding box around the whole part.
- **Loose piece:** a connected piece of geometry inside one mesh. Pieces that only touch without sharing vertices count as separate.
- **Cut-off:** for each LOD, the size below which Auto parts and loose pieces are left out.
- **LOD sphere:** the sphere MSFS uses to measure how large the model is on screen (see [The LOD Sphere](#the-lod-sphere)).

## Marks

The buttons at the top of the panel set a mark on the **selected** objects. The buttons that are pressed show the mark of the **active** object.

| Button | Meaning |
| :--- | :--- |
| **Auto** | The default. The size rule decides from which LOD the part is left out. Pressing it removes any other mark. |
| **Keep** | Never left out by size, in any LOD. |
| **Hidden from** 1 to 6 | In `_LOD00` up to the LOD before n; left out from LOD n on. |
| **Visible from** 1 to 6 | Left out up to the LOD before n; present from LOD n on. Meant for simpler replacement meshes. |

Rules:

- An object has one mark at a time; setting one clears the others.
- **A child is never present where its parent is absent.** A parent's hidden-from and visible-from limit all objects below it. The buttons clamp the marks of the selection and of the children to the parent's limits and report how many were clamped.
- **Explicit marks win over size.** A marked object is never culled by size.
- **Keep protects the way up:** an Auto parent stays as long as a Keep child is present below it. Its other small Auto children can still disappear.
- **Hidden ancestors win over Keep:** a Keep object under a parent marked hidden from n is still left out from n on. **Refresh LOD Counts** warns with "Keep under hidden ancestor".
- The **Keep** toggle of a tag in the [Tags](fss-tools.md#tags) panel works like the Keep mark on every object with that tag.
- Animated, skinned and **Don't Merge** objects follow the same rules as all other parts.
- Marks are custom properties (`fss_lod`, `fss_lod_show_from`, `fss_lod_keep`); they are not exported.

When to use them:

- **Keep:** small parts that must stay visible from far away, for example annunciators, beacon lights, emissive LEDs.
- **Hidden from:** a large part that costs many vertices but is not needed at lower detail (for example seat covers from LOD 1), or a part that sits just above a cut-off (see [Near cut-off](#hints)).
- **Visible from:** a simplified replacement that should take over from a LOD; mark the detailed original **Hidden from** the same LOD.

## Viewport LOD

The **Viewport LOD** row shows in the viewport what an export would put in each file.

- **0** to **6:** shows what that LOD file keeps; objects absent from it are hidden or shown as boxes, as **Excluded** says (below). The bottom-left corner of the viewport says "Filtered by LODn".
- **Auto:** picks the LOD from the current view, as MSFS would: it measures how large the LOD sphere is on screen (from the view's field of view and distance) and switches the filter when the LOD changes. The viewport shows "Auto LODn (ratio)", the panel "Auto: LODnn (screen ratio ...)". After a **Refresh LOD Counts** it also accounts for the vertex counts, as MSFS does (MSFS 2024 only).
- **Off:** shows every object again, with its own display setting. Objects you had set to Wire or Bounds yourself keep that setting.
- **Excluded: Hidden / Bounds:** how the preview shows objects absent from the previewed LOD. **Hidden** (default) gives a clean view of what the LOD keeps; **Bounds** shows them as box outlines, to see where the excluded parts are. While **Hidden** is in use, the panel reminds you to set Viewport LOD to **Off** before exporting by hand from Blender, because exporting only visible objects would leave the hidden ones out.

Notes:

- Loose pieces that the export drops are not shown in the viewport, only counted in the panel.
- **Saving and opening:** saving undoes the preview first and puts it back afterwards; opening a file switches it **Off** (older files saved with hidden objects are cleaned too). A saved file therefore always contains every object as you made it, and the deploy scripts export the full model.
- Choosing a LOD after the last written one shows "LODnn: not written (first empty LODmm)".
- The preview only looks at **visible** objects, as the export does. Hidden objects are not part of the model.
## Refresh LOD Counts

Press **Refresh LOD Counts** after editing geometry, marks or settings. It measures the model, counts vertices and fills the hints. It does not export anything. The results are cached until the next Refresh; after a change the panel asks for a new Refresh.

Under the button, the panel then lists per LOD:

- `LOD00: 3099 obj`: objects in that file;
- `-1234 pcs`: loose pieces the export drops;
- `hides < 1.2 cm`: the cut-off of that LOD;
- `LODnn: not written, no objects`: the first empty LOD. The export stops there; later LODs are not written, even if **Visible from** marks would put objects in them.

## Quota and Hints

This sub-panel shows whether MSFS will actually use each LOD, and what to change when it will not.

### Vertex Quota

MSFS shows a LOD file only when the model is large enough on screen for its vertex count. A LOD with too many vertices is skipped, and MSFS uses the next one (or falls back to the last LOD). The quota is the most vertices a LOD may have and still be shown from its own minimum screen size (MSFS 2024, High graphics setting).

Each line reads, for example:

`_LOD02  ~160,000 / 137,500  116%  MSFS from 73.6%`

- `~160,000`: estimated vertices of that file, counted as the glTF stores them (split where UVs, normals or materials differ; shared instances once).
- `137,500`: the quota; `116%` how much of it is used. Over 100 % the line turns red.
- `MSFS from 66.0%`: the screen size from which MSFS will show this LOD (the larger of its table value and what its vertex count needs). The last LOD is marked as fallback.
- A grey line below tells how many loose pieces the export drops.

For MSFS 2020 (preview target, see [Advanced](#advanced)) only the vertex count is shown; MSFS 2020 has no vertex rule.

### Hints

Pick a LOD with the number buttons under **Hints for LOD**. Each hint has a select button. The loose-piece and near-cut-off lists exist from LOD 1 on.

- **Largest contributors:** the objects and merge groups with the most vertices in that LOD. Candidates for **Hidden from**, or for splitting.
- **Loose pieces below the cut-off (dropped at export):** meshes that hold small loose pieces the export removes from that LOD.
- **Near cut-off (candidates to hide):** Auto parts just above the cut-off that cost many vertices. Marking them **Hidden from** this LOD saves those vertices.

The usual loop: **Refresh LOD Counts**, pick a red LOD, select a hint, split the mesh or set a mark, **Refresh LOD Counts** again, until the LODs fit. Then deploy.

Splitting tip: a joined mesh with many small parts (screws, decals, cables) keeps all of them until its loose pieces are below the cut-off. Separate the small parts into their own objects, or keep them as separate loose pieces, and the size rule removes them.

Pitfall: while **Viewport LOD** is set to a number (or **Auto**), the hints show that LOD and the number buttons have no effect. Set **Viewport LOD** to **Off** to pick the hint LOD freely.

## Export Settings

The **Export Settings** sub-panel (closed by default) holds the per-scene LOD settings. They are saved in the `.blend`.

### Model Type

- **Exterior part:** the default. Uses the SDK aircraft table 100, 75, 55, 35, 8, 5, 1 % (the screen size from which `_LOD00` to `_LOD06` are shown).
- **Interior:** for a cockpit or cabin. The interior's LODs only matter when it is seen through the windows from outside, so its table is derived from the exterior's: LOD00 stays at 100 %, the others are the exterior values times interior diameter / exterior diameter. Enter **Exterior Diameter (m)** (the diameter of the exterior model's LOD sphere); without it the panel shows "exterior diameter missing" and the export stops. An interior writes at most `_LOD00` to `_LOD05`; its `_LOD06` is always empty.
- **Scenery:** in this version the same rules and table as **Exterior part**.

### Model Diameter

After a Refresh, the panel shows **Model diameter: ... (measured at Refresh)**: the diameter of the LOD sphere. All cut-offs are proportional to it.

### Smallest Part Kept

The field **LOD06 hides parts smaller than** (for an interior **LOD05 hides parts smaller than**) sets how aggressive the size rule is. Its tooltip calls it **Smallest Part Kept**. All other LODs follow in proportion; the box **Hidden parts, smaller than** lists the cut-off of every LOD and, after a Refresh, how many objects and pieces each LOD hides.

Example with the defaults on a 3 m model:

| LOD | Shown up to | Hides parts smaller than |
| :--- | :--- | :--- |
| `_LOD01` | 100 % | 0.8 cm |
| `_LOD02` | 75 % | 1.1 cm |
| `_LOD03` | 55 % | 1.5 cm |
| `_LOD04` | 35 % | 2.4 cm |
| `_LOD05` | 8 % | 10.4 cm |
| `_LOD06` | 5 % | 16.7 cm |

A larger value hides more and makes the lower LODs lighter; a smaller value keeps more. The field appears once a Refresh has measured the model. Behind the scenes it is the **Pixel Threshold** (default 4 px at a 1440 px screen height, see [Advanced](#advanced)): a part is left out when it would be smaller than that many pixels at the largest size its LOD is shown.

### Print LOD Settings / XML

Asks for the **Model Base Name** and prints the `<LODS>` block for the model XML to the system console (**Window > Toggle System Console**), with one entry per written LOD and its `minSize` (from the table of the **Preview Target**), plus the object counts and warnings per LOD. It changes nothing; give the block to whoever maintains the model XML.

## The LOD Sphere

MSFS measures a model's screen size with one sphere per model, the same for every LOD file. The sphere is centred on the box around all `_LOD00` geometry **and every object origin** (bone heads included), and reaches the farthest of those points.

### Origins Outside the Geometry

One origin far outside the model moves the sphere's centre and makes it larger, for every LOD:

- MSFS then thinks the model is larger than it is, and measures its distance from the wrong place. LODs switch at the wrong distances, and the screen size can be largest somewhere outside the model.
- All cut-offs grow with the diameter, so too many parts disappear.

After a Refresh, the **Export Settings** show a warning when origins lie more than 5 cm outside the geometry box, for example "16 origins outside the geometry: LOD sphere 4.42 m -> 26.70 m", with the five farthest objects and a select button for each.

How to fix it:

- Move the origin into the object's geometry, for example with [Origin to Bounding Box](fss-tools.md#origin-to-bounding-box). Do not do this on an object whose own transform is animated.
- A reference empty that only marks a position (for example the root of the light positions) can be hidden. Hidden objects are not exported and do not count for the sphere; their visible children are still exported, in the same world position, attached to the nearest exported parent or to the glTF root. Never hide a parent that carries animation: its children export but no longer move.
- Objects that belong to another model (cabin empties in a cockpit file) belong in that model's file.

Objects inside a merge group are counted with their origin, although their node disappears in the merge. A far origin inside a merge group can therefore show up even though MSFS will not see it.

### Show LOD Sphere

The **Show LOD Sphere** toggle (in **Export Settings**, after a Refresh) draws, from the last Refresh:

- the sphere's box and three circles (orange), and an orange cross at the centre labelled with the radius, "(padded)" when padding is active;
- the box of the geometry alone (green), when it is smaller than the sphere's box;
- for each of the six sides of the box, the point that sets it, labelled with the side, the object and its kind: red for an origin, yellow for a vertex.

The panel lists the same six points with a select button. One stray vertex or origin shows up here at once. The toggle is not saved with the file, and it needs the viewport overlays on.

### LOD Sphere Diameter (Padding)

**LOD Sphere Diameter** sets the diameter MSFS should use. 0 (the default) uses the measured sphere.

- A value larger than the geometry's own sphere **pads** the sphere at export: the export adds eight tiny invisible triangles (material invisible, no collision) at the corners of a box around the geometry centre. They exist only in the exported files, never in your `.blend`.
- MSFS then sees the model that many times larger: every LOD holds to a proportionally larger distance, and each LOD's vertex count gets more room.
- The tables, the cut-offs and the viewport preview use the same diameter. The cut-offs therefore grow too.
- The cost: the detailed LODs are also drawn farther away in outside views, which costs frame rate.

Use it when the LODs switch too early, for example when heavy LODs are skipped because the model is small on screen. Leave it at 0 otherwise.

Messages under the field:

- **Press Refresh LOD Counts to apply:** a changed value needs a Refresh.
- **Export pads the LOD sphere: MSFS sees the model N.NNx larger:** padding is active.
- **Not larger than the geometry sphere (...): no padding:** the value is too small to do anything.
- **Origins outside the padding: MSFS uses ...:** origins lie outside the padding box and enlarge the sphere further. Fix them as described above; origins inside the padding box no longer matter.

## Advanced

The **Advanced** sub-panel (inside **Export Settings**, closed by default) holds the numbers behind the cut-offs. Most artists never need it.

- **Preview Target:** **MSFS 2024** or **MSFS 2020 (unverified)**: which table the panel, the hints and the viewport preview use.
- **Screen Height (px):** default 1440.
- **Pixel Threshold:** default 4 px. **Smallest Part Kept** edits this value.
- **MSFS Vertex Factor:** default 1.15. MSFS counts vertices differently from the file; the vertex estimate is multiplied by this factor to predict from which screen size MSFS shows each LOD. Vertex counts never change which parts are left out.
- **FS24 minSize** and **FS20 minSize (unverified):** the screen sizes from which `LOD00` to `LOD06` are shown, as ratios (1 = 100 %). They must not increase from one LOD to the next. Editing the FS24 table also changes the FS20 table, until you edit the FS20 table yourself. MSFS 2020 forces its second-to-last LOD to at least 1 %. The MSFS 2020 values have not been checked in the simulator.
- For an **Interior** with the derived table, the tables are not editable fields; **Edit Explicit minSize Table** lets you type your own. An explicit interior table needs no exterior diameter.

## Exporting with LODs

- LOD files are written by **the LOD deploy script of your aircraft repository**. It writes `<name>_LOD00.gltf` up to the last LOD that still has objects and copies the files into the package.
- The normal single-file deploy, a plain **File > Export > glTF 2.0** and the multi-exporter write one file and ignore the LOD marks.
- The export starts every LOD from the unchanged `.blend`, clears a saved viewport filter first, and leaves out parts before merging (also when **Merge on Export** is off). Your `.blend` is not changed.
- The model XML must list the written files in its `<LODS>` block (see [Print LOD Settings / XML](#print-lod-settings--xml)). A model moved to LODs gets a deploy name without `-LOD00`, for example `E2-190-Cockpit_LOD00.gltf`. Coordinate this with the maintainer of the model XML.
- An old `_LODxx` file from an earlier deploy can stay in the package. The XML does not reference it, so it is harmless.

The deploy prints one line per LOD to the console, for example:

`[FSS LOD] _LOD03: 3099 objects in, 210 culled by mark, 1245 culled by size, 812 culled by size (pieces), 41 merged meshes; 211,143 vertices ...`

It ends with the vertex count of the file, the screen range the LOD is meant for, the screen size from which MSFS will show it, and a **WARNING High vertex limit** when MSFS will skip it over part of that range.

## Pitfalls

- **Forgot to Refresh:** cut-offs, counts, hints and the LOD sphere are from the last **Refresh LOD Counts**. The export always measures again, so it is correct, but the panel may be out of date.
- **Far origins:** the most common cause of LODs switching at strange distances. Check the warning in **Export Settings** and **Show LOD Sphere**.
- **Exporting by hand with the preview on:** with **Excluded: Hidden**, objects absent from the previewed LOD are hidden, and an export of visible objects only leaves them out. Set **Viewport LOD** to **Off** first. The deploy scripts are not affected.
- **Important small parts disappear:** give them **Keep** (or a tag with **Keep**).
- **A LOD stays red although many parts are hidden:** the vertices sit in a few large meshes. Hide those meshes from that LOD, or split them; the tools do not reduce polygons.
- **Interior export stops with "exterior diameter missing":** enter **Exterior Diameter (m)**.
- **No LOD after an empty one:** the export stops at the first empty LOD, even if **Visible from** marks would fill later ones.
