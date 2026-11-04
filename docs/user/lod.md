# LOD: Automatic Levels of Detail

[Artist Guide](README.md) / **lod.md**
***

Three panels in the sidebar (`N` > **FSS MSFS Tools**) prepare a model for export as several LOD files. You model the full detail once; the export leaves out parts that are too small to see at each lower level of detail.

| Panel | What it is for |
| :--- | :--- |
| **Object LOD** | The marks of the selected objects: let the size rule decide (**Auto**), never leave out (**Keep**), or choose the LODs in which an object is visible (**Hidden from**, **Visible from**). See [Object LOD](#object-lod). |
| **Viewport LOD** | A preview in the viewport of what each LOD file keeps. See [Viewport LOD](#viewport-lod). |
| **LOD Settings** | **Refresh LOD Counts** and the table of what MSFS does at your current view, with the sections **Hints** (which objects cost the most vertices) and **Export Settings** (the LOD sphere and the settings per LOD). See [LOD Settings](#lod-settings). |

## How the Automatic LODs Work

- MSFS picks one whole glTF file per LOD by how large the model looks on screen. It never hides single parts inside a file. So each LOD file must already contain only the parts worth drawing at that size.
- A LOD deploy writes `<name>_LOD00.gltf` (the full model) to at most `<name>_LOD06.gltf`. Each file has the parts of `_LOD00` minus:
  - parts you **marked** hidden from that LOD (or not visible yet),
  - **Auto** parts smaller than that LOD's size cut-off,
  - inside a mesh, **loose pieces** smaller than that cut-off.
- Merge groups are merged after this, per LOD: `_LOD00` merges a panel with its screws, `_LOD04` merges the panel without them.
- No geometry is cut or reduced. Every boundary that disappears is one you modelled. **Model parts as separate objects** (or at least as separate loose pieces) and the LODs follow from their size.
- Vertex counts never decide which parts are left out; only marks and sizes do. Vertex counts are reported so you can see which LOD MSFS will show (see [The Table at This View](#the-table-at-this-view)).

Terms:

- **Part:** an object with everything below it. Its **size** is the largest side of the world bounding box around the whole part.
- **Loose piece:** a connected piece of geometry inside one mesh. Pieces that only touch without sharing vertices count as separate.
- **Cut-off:** for each LOD, the size below which Auto parts and loose pieces are left out. You see and set it as **Hides Under**.
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

### How Nesting Affects the Size Rule

**A mesh with children is measured together with them.** Its size is the box around its own mesh and everything below it, including the distance between them. A tiny mesh with a large child, or with a small child far away, therefore counts as large, and the size rule keeps it in every LOD. This is easy to miss, because the mesh looks small enough to disappear.

| Hierarchy | What the size rule does with the small mesh |
| :--- | :--- |
| Small mesh with children, as one connected piece | **Stays** as long as the box around it and its children is above the cut-off, also in LODs where those children are already gone |
| Small mesh with children, made of two or more loose pieces | Disappears: its pieces are dropped by their own size, although the object stays. A tag with **Whole** prevents this |
| Small mesh without children, directly under an empty or under nested empties | Disappears at its own size |

Empties are free: nesting under empties changes nothing for the meshes below them, because each mesh is still measured on its own. A group is not held together either: a small mesh under an empty disappears alone, even if its neighbours stay.

What to do:

- **A part that sits on a body** (a screw on its panel): parent it to the body's mesh. The body then cannot disappear while the part stays, so no screw is left floating.
- **Parts that are only grouped:** put them under empties, so that each disappears at its own size. Inside a `@MERGE_` group, keep the root itself an empty.
- **A small mesh with a large or distant child that does not sit on it** (for example, the child only follows its animation): move the mesh to a new child of its own, so that an empty carries the children and the animation:

  ```text
  A (empty, carries any animation)
  ├── A_MESH (the small mesh)
  └── B (the large mesh)
  ```

- **A small mesh that should stay because of its child:** leave it as it is, but use **Keep** if it must stay in every LOD. The child's size only holds it while the box is above the cut-off.
- **A mesh of loose pieces that must stay complete:** give it a tag with [Whole](fss-tools.md#tags). The pieces then stay together, and the object leaves all at once.
- **To check:** with **Viewport LOD** on a number, a mesh that should be gone but is still there often has children. Loose pieces are not shown as dropped in the viewport, so a mesh of loose pieces can look present in the preview and still be missing from the file.

## Viewport LOD

The **Viewport LOD** panel shows in the viewport what an export would put in each file. Its row of buttons:

- **Off:** no preview. Every object shows again, with its own display setting; objects you had set to Wire or Bounds yourself keep that setting.
- **0** to **6:** shows what that LOD file keeps; objects absent from it are hidden or shown as boxes, as **Excluded** says (below). The bottom-left corner of the viewport says "Filtered by LODn".
- **Auto:** picks the LOD from the current view, as MSFS would: it measures how large the LOD sphere is on screen (from the view's field of view and distance) and switches the filter when the LOD changes. The viewport shows "Auto LODn (ratio)". After a **Refresh LOD Counts** it also accounts for the vertex counts, as MSFS does, at the **MSFS Quality** chosen in **LOD Settings**.

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

The **LOD Settings** panel holds **Refresh LOD Counts**, [the table at this view](#the-table-at-this-view), and the sections [Hints](#hints) and [Export Settings](#export-settings).

### Refresh LOD Counts

**Refresh LOD Counts** measures the model and counts objects and vertices per LOD. It exports nothing. It runs by itself when you open a file (a few seconds on a cockpit, shortly after the file appears). Press it after editing geometry or marks: the results stay as they were at the last Refresh, as the line "Cached counts: Refresh after editing" reminds you. Changing **Hides Under** or the padding clears them until the next Refresh; **MSFS Quality** and **minSize %** apply at once.

### The Table at This View

What it means for you: MSFS has a vertex limit that depends on how large the model is on screen. Close up the limit is high; further away it is low. MSFS shows the most detailed LOD that fits the limit, so **a model with fewer vertices gets a better LOD at the same view**. The table tells you which LOD MSFS shows at your current Blender view, and how many vertices to remove to get a better one.

The table follows the Blender view: zoom or move and the numbers change. It does so whatever **Viewport LOD** is set to, also on **Off**.

- **MSFS Quality:** the simulator's graphics setting to predict, **High** by default. The higher the setting, the higher the limit at the same view. Only High has been checked against the simulator.
- **This view: LOD04 (screen ratio 158 %):** the LOD MSFS shows here, and how large the model is on screen. Above 100 %, the LOD sphere is larger than the screen height. This is the same measure as **Viewport LOD > Auto**.

The table has one row per written LOD:

| Column | Meaning |
| :--- | :--- |
| **LOD** | The LOD and its cut-off: `00 -`, `01 <1.1cm`. The highlighted button is the LOD MSFS shows at this view; clicking it does nothing. |
| **Vert/Obj** | Estimated vertices and objects of that file, `1.11M/3.48K`. Vertices are counted as the glTF stores them (split where UVs, normals or materials differ; shared instances once), after small loose pieces are dropped. |
| **Used** | A bar: the vertices as a share of the limit at this view. At 100 % or less, the vertex count lets the LOD show here. |
| **ToReduce** | The vertices to remove from that LOD so MSFS shows it here. Only on LODs more detailed than the one shown; `-` on the others. |
| **Reduced** | A bar: how much of the previous LOD's vertices this step removed, so you can compare the steps. The text gives the step itself, vertices and objects. |

An example at one view, where the limit is 542K:

| LOD | Vert/Obj | ToReduce | What it means |
| :--- | :--- | :--- | :--- |
| 03 | 561K | 19K | Too heavy, by 19K. Remove 19K vertices from LOD03 and MSFS shows LOD03 here instead of LOD04. |
| 04 (highlighted) | 482K | - | Fits, so this is the LOD MSFS shows. |

Other messages:

- **Over the limit, shown as the last LOD:** even the last LOD is above the limit; MSFS still shows it, because it has nothing lower.
- **LODnn: not written, no objects:** the first empty LOD. The export stops there; later LODs are not written, even if **Visible from** marks would put objects in them.
- A LOD with `-` in **ToReduce** and less than 100 % in **Used** that is still not shown is held back by its **minSize %** (see [Settings per LOD](#settings-per-lod)).

## Hints

This section of **LOD Settings** shows which objects to work on when a LOD is too heavy. Before the first Refresh it says "Click Refresh LOD Counts to compute estimates".

### Per LOD Vertex Contributors

Pick a LOD with the number buttons under **Per LOD Vertex Contributors**. Each entry has a select button (**Shift + click** adds to the selection).

- The first box starts with the LOD's vertex count, for example `LOD00: ~1,257,938 vtx`, then lists the five objects and merge groups with the most vertices in that LOD. Each has a bar for its share of the LOD's vertices, with its vertex count and that share, for example `~80,316 (6.4 %)`. Candidates for **Hidden from**, or for splitting.
- From LOD 1 on, two more boxes:
  - **Loose pieces below ... m (dropped at export):** meshes that hold small loose pieces the export removes from that LOD.
  - **Near cut-off (... m, candidates to hide):** Auto parts just above the cut-off that cost many vertices. Marking them **Hidden from** this LOD saves those vertices.

The usual loop: frame the model as MSFS would see it, read **ToReduce** on the LOD you want at that view, select a contributor of that LOD, split the mesh or set a mark, **Refresh LOD Counts** again. Then deploy.

Splitting tip: a joined mesh with many small parts (screws, decals, cables) keeps all of them until its loose pieces are below the cut-off. Separate the small parts into their own objects, or keep them as separate loose pieces, and the size rule removes them.

Pitfall: while **Viewport LOD** is set to a number (or **Auto**), the contributors show that LOD and the number buttons have no effect. Set **Viewport LOD** to **Off** to pick the LOD freely.

## Export Settings

The **Export Settings** section of **LOD Settings** (closed by default) holds the per-scene LOD settings. They are saved in the `.blend`. They work the same for a cockpit, a cabin, an exterior part and scenery.

### Model Diameter

After a Refresh, the panel shows **Model diameter: ... (measured at Refresh)**: the diameter of the LOD sphere without padding, always measured from the model itself. Before the first Refresh it asks for one.

### Settings per LOD

One table, with one row per LOD:

| Column | Meaning |
| :--- | :--- |
| **Hides Under** | Auto parts and loose pieces smaller than this are left out of that LOD. This decides what is in the file. |
| **minSize %** | The LOD never shows below this screen size. It goes into the model XML. |
| **Shows From** | The screen size from which MSFS shows the LOD: the larger of **minSize %** and what its vertex count needs, at the chosen **MSFS Quality**. `fallback` on the last written LOD, which MSFS shows when nothing else fits; `-` on a LOD that is not written. |

**Hides Under** is yours to set. The first Refresh fills in a starting value for each LOD from the model's diameter (what would be smaller than 4 pixels on a 1440 pixel screen, using the SDK's aircraft table 100, 75, 55, 35, 8, 5, 1 %). After that your values stay, also when the diameter changes. Set a value to 0 to get the starting value back at the next Refresh.

- **The LOD is too heavy:** raise its value, so more small parts go. For example, setting `LOD06` to 1.46 m makes the far view of a cockpit light.
- **Something visible disappears too early:** lower the value, or give that object [Keep](#what-the-marks-mean).

**minSize %** starts at 7, 6, 5, 4, 3, 2, 1, the values the SDK recommends to leave the choice to MSFS's vertex rule. A low value does nothing beyond that. A high value holds the LOD back: with `150` on `LOD00`, MSFS uses a lower LOD below 150 % even when the vertices of `LOD00` would fit. The values must not increase from one LOD to the next; otherwise Refresh and the export stop with "minSize values must be in descending order".

MSFS 2020 uses the same table and is predicted with the same vertex rule; this has not been checked in the simulator. Its second-to-last LOD is forced to at least 1 % at export.

### Print LOD Settings / XML

Asks for the **Model Base Name** and prints the `<LODS>` block for the model XML to the system console (**Window > Toggle System Console**), with one entry per written LOD and its `minSize`, plus the object counts, the cut-offs and warnings per LOD. It changes nothing; give the block to whoever maintains the model XML.

## The LOD Sphere

MSFS measures a model's screen size with one sphere per model, the same for every LOD file. The sphere is centred on the box around all `_LOD00` geometry **and every object origin** (bone heads included), and reaches the farthest of those points.

### Origins Outside the Geometry

One origin far outside the model moves the sphere's centre and makes it larger, for every LOD. MSFS then thinks the model is larger than it is, and measures its distance from the wrong place. LODs switch at the wrong distances, and the screen size can be largest somewhere outside the model.

After a Refresh, the **Export Settings** show a warning when origins lie more than 5 cm outside the geometry box, for example "16 origins outside the geometry: LOD sphere 4.42 m -> 26.70 m", with the five farthest objects and a select button for each. With padding, the warning only lists origins more than 5 cm outside the padding box, for example "1 origins outside the padding: LOD sphere 7.66 m -> 15.39 m"; origins inside it no longer matter, and when there are none the warning is gone.

How to fix it:

- Move the origin into the object's geometry, for example with [Origin to Bounding Box](fss-tools.md#origin-to-bounding-box). Do not do this on an object whose own transform is animated.
- A reference empty that only marks a position (for example the root of the light positions) can be hidden. Hidden objects are not exported and do not count for the sphere; their visible children are still exported, in the same world position, attached to the nearest exported parent or to the glTF root. Never hide a parent that carries animation: its children export but no longer move.
- Objects that belong to another model (cabin empties in a cockpit file) belong in that model's file.

Objects inside a merge group are counted with their origin, although their node disappears in the merge. A far origin inside a merge group can therefore show up even though MSFS will not see it.

### Show LOD Sphere

The **Show LOD Sphere** toggle (in **Export Settings**, after a Refresh) draws, from the last Refresh:

- the sphere's box and three circles (orange), and an orange cross at the centre labelled with the radius, "(padded)" when padding is active;
- the box of the geometry alone (green), when it is smaller than the sphere's box;
- for each of the six sides of the box, the point that sets it, labelled with the side, the object and its kind: red for an origin, yellow for a vertex. One stray vertex or origin shows up here at once.

The toggle is not saved with the file, and it needs the viewport overlays on.

### Pad LOD Sphere Multiplier

**Pad LOD Sphere Multiplier** (in **Export Settings**) makes MSFS see the model larger than it is, from **1.00** (no padding, the default) to **10.00** times the geometry's sphere.

What it means for you: at the same camera position, the limit is higher, so MSFS shows a more detailed LOD. **This is a trick, and it costs frame rate:** MSFS draws more vertices at the same view, and the detailed LODs stay on further out in outside views.

- The export adds eight tiny invisible triangles (material invisible, no collision) at the corners of a box around the geometry centre. They exist only in the exported files, never in your `.blend`.
- The table at this view, **Shows From** and the viewport preview use the padded sphere. **Hides Under** values you already have stay as they are.
- A file saved with the older **Pad LOD Sphere To** diameter gets the matching multiplier at its first Refresh.

Use it when the LODs drop too early and the model cannot lose more vertices. Leave it at 1.00 otherwise.

Lines under the field:

- **MSFS sees: 3.83 m (no padding)**, or **MSFS sees: 7.66 m (geometry 3.83 m)** with padding.
- **Press Refresh LOD Counts to apply:** a changed multiplier needs a Refresh.
- **Above 5x has not been tested in the simulator:** a reminder, nothing stops it.

## Advanced

The **Advanced** sub-panel (inside **Export Settings**, closed by default) holds one number, which most artists never need:

- **MSFS Vertex Factor:** default 1.15. MSFS counts vertices differently from the file; the vertex estimate is multiplied by this factor to predict which LOD MSFS shows. Vertex counts never change which parts are left out.

## Exporting with LODs

- LOD files are written by **the LOD deploy script of your aircraft repository**. It writes `<name>_LOD00.gltf` up to the last LOD that still has objects and copies the files into the package.
- The normal single-file deploy, a plain **File > Export > glTF 2.0** and the multi-exporter write one file and ignore the LOD marks.
- The export starts every LOD from the unchanged `.blend`, clears a saved viewport filter first, and leaves out parts before merging (also when **Merge on Export** is off). Your `.blend` is not changed.
- The model XML must list the written files in its `<LODS>` block (see [Print LOD Settings / XML](#print-lod-settings--xml)). A model moved to LODs gets a deploy name without `-LOD00`, for example `E2-190-Cockpit_LOD00.gltf`. Coordinate this with the maintainer of the model XML.
- An old `_LODxx` file from an earlier deploy can stay in the package. The XML does not reference it, so it is harmless.

The deploy prints one line per LOD to the console, for example:

`[FSS LOD] _LOD03: 3099 objects in, 210 culled by mark, 1245 culled by size, 812 culled by size (pieces), 41 merged meshes; 211,143 vertices ...`

It ends with the exact vertex count of the file, the screen range from its `minSize` values, and the screen size from which MSFS will show it (`effective minSize`).

## Pitfalls

- **Forgot to Refresh:** counts, hints and the LOD sphere are from the last **Refresh LOD Counts**. The export always measures again, so it is correct, but the panel may be out of date.
- **Far origins:** the most common cause of LODs switching at strange distances. Check the warning in **Export Settings** and **Show LOD Sphere**.
- **Exporting by hand with the preview on:** with **Excluded: Hidden**, objects absent from the previewed LOD are hidden, and an export of visible objects only leaves them out. Set **Viewport LOD** to **Off** first. The deploy scripts are not affected.
- **Important small parts disappear:** give them **Keep** (or a tag with **Keep**).
- **A LOD's ToReduce stays high although many parts are hidden:** the vertices sit in a few large meshes. Hide those meshes from that LOD, or split them; the tools do not reduce polygons.
- **No LOD after an empty one:** the export stops at the first empty LOD, even if **Visible from** marks would fill later ones.
