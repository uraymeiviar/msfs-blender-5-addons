# LOD: Automatic Levels of Detail

[Artist Guide](README.md) / **lod.md**
***

Three panels in the sidebar (`N` > **FSS MSFS Tools**) prepare a model for export as several LOD files. You model the full detail once; the export leaves out parts that are too small to see at each lower level of detail.

| Panel | What it is for |
| :--- | :--- |
| **Object LOD** | The marks of the selected objects: let the size rule decide (**Auto**), never leave out (**Keep**), or choose the LODs in which an object is visible (**Hidden from**, **Visible from**). See [Object LOD](#object-lod). |
| **Viewport LOD** | A preview in the viewport of what each LOD file keeps. See [Viewport LOD](#viewport-lod). |
| **LOD Settings** | **Refresh LOD Counts** and the object count per LOD, with the sections **Quota and Hints** (will MSFS show each LOD, and which objects cost the most vertices) and **Export Settings** (model type, LOD sphere, cut-offs). See [LOD Settings](#lod-settings). |

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

## Object LOD

The **Object LOD** panel sets a mark on the **selected** objects. Its first lines say what you are acting on:

- **Selected: 3 objects (active: KNOB_HDG)**, or **Select objects to mark them** when nothing is selected (the buttons are greyed out then).
- **Active object: Hidden from LOD3**: the mark of the active object (**Auto**, **Keep**, **Hidden from LODn** or **Visible from LODn**).
- **Selected objects: mixed marks**, when the selected objects do not all carry the same mark. **Hidden from LOD3** and **Hidden from LOD4** count as different marks. A mark you set replaces the marks of all selected objects.

Below them, one row with the four marks **Auto**, **Keep**, **Hidden from** and **Visible from**. The pressed button is the active object's mark.

- **Auto** and **Keep** apply at once to the selected objects.
- **Hidden from** and **Visible from** do not change anything yet: they open the row **Visible in** below, and a number there applies the mark.

### The Visible In Row

The row **Visible in** has the buttons **0** to **6**, for `LOD00` to `LOD06`. The lit buttons show the LODs in which the active object is visible. You click the LOD where the visible range ends or starts:

- **Under Hidden from:** click the **last** LOD in which the objects should still be visible. Clicking **2** makes them visible in LOD 0 to 2 and leaves them out from LOD 3 on; the panel then reads **Active object: Hidden from LOD3**. **6** is greyed out: an object visible in every LOD needs no Hidden from mark.
- **Under Visible from:** click the **first** LOD in which the objects should be visible. Clicking **2** leaves them out of LOD 0 and 1 and makes them visible from LOD 2 on. **0** is greyed out: visible from LOD 0 is every LOD.

The button you click is always lit afterwards. While you have pressed **Hidden from** or **Visible from** on an object that does not carry that mark yet, nothing is lit until you click a number. **Auto** and **Keep** show no **Visible in** row.

### What the Marks Mean

| Mark | Meaning |
| :--- | :--- |
| **Auto** | The default. The size rule decides from which LOD the part is left out. Setting it removes any other mark. |
| **Keep** | Never left out by size, in any LOD. |
| **Hidden from** LOD 1 to 6 | Visible from `_LOD00` up to the LOD before n; left out from LOD n on. |
| **Visible from** LOD 1 to 6 | Left out up to the LOD before n; visible from LOD n on. Meant for simpler replacement meshes. |

Rules:

- An object has one mark at a time; setting one clears the others.
- **A child is never present where its parent is absent.** A parent's hidden-from and visible-from limit all objects below it. Setting a mark clamps the marks of the selection and of the children to the parent's limits, and Blender's status bar reports how many were clamped.
- **Explicit marks win over size.** A marked object is never culled by size.
- **Keep protects the way up:** an Auto parent stays as long as a Keep child is present below it. Its other small Auto children can still disappear.
- **Hidden ancestors win over Keep:** a Keep object under a parent marked hidden from n is still left out from n on. **Refresh LOD Counts** warns with "Keep under hidden ancestor".
- The **Keep** toggle of a tag in the [Tags](fss-tools.md#tags) panel works like the Keep mark on every object with that tag.
- Animated, skinned and **Don't Merge** objects follow the same rules as all other parts.
- Marks are custom properties (`fss_lod`, `fss_lod_show_from`, `fss_lod_keep`); they are not exported.

When to use them:

- **Keep:** small parts that must stay visible from far away, for example annunciators, beacon lights, emissive LEDs.
- **Hidden from:** a large part that costs many vertices but is not needed at lower detail (for example seat covers from LOD 1), or a part that sits just above a cut-off (see [Near cut-off](#per-lod-vertex-contributors)).
- **Visible from:** a simplified replacement that should take over from a LOD; mark the detailed original **Hidden from** the same LOD.

## Viewport LOD

The **Viewport LOD** panel shows in the viewport what an export would put in each file. Its row of buttons:

- **Off:** no preview. Every object shows again, with its own display setting; objects you had set to Wire or Bounds yourself keep that setting.
- **0** to **6:** shows what that LOD file keeps; objects absent from it are hidden or shown as boxes, as **Excluded** says (below). The bottom-left corner of the viewport says "Filtered by LODn".
- **Auto:** picks the LOD from the current view, as MSFS would: it measures how large the LOD sphere is on screen (from the view's field of view and distance) and switches the filter when the LOD changes. The viewport shows "Auto LODn (ratio)", the panel "Auto: LODnn (screen ratio ...)". After a **Refresh LOD Counts** it also accounts for the vertex counts, as MSFS does (MSFS 2024 only).

**0 is not the same as Off.** LOD 0 shows what `_LOD00` keeps, and `_LOD00` leaves out the objects marked **Visible from** (the simpler replacements). In a file without Visible from marks the two look the same.

While a preview is on (a number or **Auto**), the panel shows two more things:

- **Excluded: Hidden / Bounds:** how the preview shows objects absent from the previewed LOD. **Hidden** (default) gives a clean view of what the LOD keeps; **Bounds** shows them as box outlines, to see where the excluded parts are. With **Off** nothing is excluded, so the row is not shown.
- While **Hidden** is in use, the reminder "Excluded objects hidden: set Viewport LOD Off before exporting by hand": exporting only visible objects from Blender would leave the hidden ones out.

Notes:

- Loose pieces that the export drops are not shown in the viewport, only counted in **LOD Settings**.
- **Saving and opening:** saving undoes the preview first and puts it back afterwards; opening a file switches it **Off** (older files saved with hidden objects are cleaned too). A saved file therefore always contains every object as you made it, and the deploy scripts export the full model.
- Choosing a LOD after the last written one shows "LODnn: not written (first empty LODmm)".
- The preview only looks at **visible** objects, as the export does. Hidden objects are not part of the model.

## LOD Settings

The **LOD Settings** panel holds **Refresh LOD Counts**, the object count of each LOD, and the sections [Quota and Hints](#quota-and-hints) and [Export Settings](#export-settings).

### Refresh LOD Counts

Press **Refresh LOD Counts** after editing geometry, marks or settings. It measures the model, counts vertices and fills the hints. It does not export anything, and it does not run by itself when you open a file (on a cockpit it takes a few seconds). The results stay as they were at the last Refresh, as the line "Cached source counts — Refresh after editing" reminds you; changing a setting in **Export Settings** clears them until the next Refresh.

### Object Count per LOD

After a Refresh, the panel shows one row per written LOD, for example:

`LOD02 | 326 obj (11 %) | -40,851 pcs | hides < 18.8 cm`

- **LODnn** and a **bar**: the bar is full for `LOD00` and shows how many of `LOD00`'s objects the LOD still has; the text gives the object count and, from LOD 1 on, that share in brackets. A bar that hardly shrinks from one LOD to the next means the size rule removes little there.
- **-40,851 pcs:** loose pieces the export drops from that LOD (empty when none).
- **hides < 18.8 cm:** the cut-off of that LOD.
- **LODnn: not written, no objects:** the first empty LOD. The export stops there; later LODs are not written, even if **Visible from** marks would put objects in them.

## Quota and Hints

This section of **LOD Settings** shows whether MSFS will actually use each LOD, and which objects to work on when it will not. Before the first Refresh it says "Click Refresh LOD Counts to compute estimates".

### Vertex Quota

What it means for you: MSFS shows a LOD file only when the model is large enough on screen for its vertex count; the section's first sentence says so. A LOD with too many vertices for its place in the table is shown only from a larger screen size than the table asks for. If it would need more than the whole screen, MSFS in practice never shows it and uses another LOD instead.

The table has one row per written LOD:

| Column | Meaning |
| :--- | :--- |
| **LOD** | `00` to `06`. |
| **Vertices** | Estimated vertices of that file, counted as the glTF stores them (split where UVs, normals or materials differ; shared instances once). |
| **Quota** | The most vertices the LOD may have and still be shown from its own table size (MSFS 2024, High graphics setting). |
| **Used** | A bar: the vertices as a share of the quota. Up to 100 % the LOD fits; above 100 % the bar is full and red. |
| **MSFS shows it from** | The screen size from which MSFS will show this LOD: the larger of its table value and what its vertex count needs. |

The **MSFS shows it from** column reads:

- `55 % of screen (table 55 %)`: the LOD fits its quota and is shown from its table value.
- `96 % of screen (table 2.7 %)`: too many vertices; MSFS shows the LOD only when the model fills 96 % of the screen instead of 2.7 %.
- `never (needs 240 %; table 100 %)`: the LOD would need more than the whole screen, so MSFS never shows it.
- `, fallback` after the last LOD: the LOD MSFS falls back to.

Below the table, a box **Dropped at export (loose pieces below the cut-off)** lists per LOD how many loose pieces the export removes and their vertices, for example `LOD01: 12,832 pcs, ~248,613 vtx`. It is not shown when nothing is dropped.

For MSFS 2020 (preview target, see [Advanced](#advanced)) the section says "MSFS 2020 has no vertex rule" and the table shows only the **LOD** and **Vertices** columns.

### Per LOD Vertex Contributors

Pick a LOD with the number buttons under **Per LOD Vertex Contributors**. Each entry has a select button (**Shift + click** adds to the selection).

- The first box starts with the LOD's vertex count, for example `LOD00: ~1,257,938 vtx`, then lists the five objects and merge groups with the most vertices in that LOD. Each has a bar for its share of the LOD's vertices, with its vertex count and that share, for example `~80,316 (6.4 %)`. Candidates for **Hidden from**, or for splitting.
- From LOD 1 on, two more boxes:
  - **Loose pieces below ... m (dropped at export):** meshes that hold small loose pieces the export removes from that LOD.
  - **Near cut-off (... m, candidates to hide):** Auto parts just above the cut-off that cost many vertices. Marking them **Hidden from** this LOD saves those vertices.

The usual loop: **Refresh LOD Counts**, find a LOD with a red **Used** bar, select a contributor, split the mesh or set a mark, **Refresh LOD Counts** again, until the LODs fit. Then deploy.

Splitting tip: a joined mesh with many small parts (screws, decals, cables) keeps all of them until its loose pieces are below the cut-off. Separate the small parts into their own objects, or keep them as separate loose pieces, and the size rule removes them.

Pitfall: while **Viewport LOD** is set to a number (or **Auto**), the contributors show that LOD and the number buttons have no effect. Set **Viewport LOD** to **Off** to pick the LOD freely.

## Export Settings

The **Export Settings** section of **LOD Settings** (closed by default) holds the per-scene LOD settings. They are saved in the `.blend`.

### Model Type

- **Exterior part:** the default. Uses the SDK aircraft table 100, 75, 55, 35, 8, 5, 1 % (the screen size from which `_LOD00` to `_LOD06` are shown).
- **Interior:** for a cockpit or cabin. The interior's LODs only matter when it is seen through the windows from outside, so its table is derived from the exterior's: LOD00 stays at 100 %, the others are the exterior values times interior diameter / exterior diameter. Enter **Exterior Diameter (m)** (the diameter of the exterior model's LOD sphere). While it is 0 (and you have not typed an explicit table, see [Advanced](#advanced)), the field is drawn red with the message "Exterior diameter missing: enter the exterior model's LOD sphere diameter", and **Refresh LOD Counts** and the export stop with "exterior diameter missing". An interior writes at most `_LOD00` to `_LOD05`; its `_LOD06` is always empty.
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

### Pad LOD Sphere To

**Pad LOD Sphere To** (in **Export Settings**) is the diameter you want MSFS to use for the LOD sphere. It is a setting, not a measurement: 0 (the default) means no padding, and MSFS uses the measured sphere. The line under the field shows that measured diameter, for example "Without padding: 15.94 m (0 = no padding)"; before the first Refresh it reads "0 = no padding; press Refresh LOD Counts to measure the model".

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
- **A LOD's Used bar stays red although many parts are hidden:** the vertices sit in a few large meshes. Hide those meshes from that LOD, or split them; the tools do not reduce polygons.
- **Interior export stops with "exterior diameter missing":** enter **Exterior Diameter (m)** (the field drawn red in **Export Settings**).
- **No LOD after an empty one:** the export stops at the first empty LOD, even if **Visible from** marks would fill later ones.
