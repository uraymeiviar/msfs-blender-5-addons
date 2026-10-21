# Auto Seam: Automated UV Seams

[Artist Guide](README.md) / **uv.md**
***

The **Auto Seam** panel (sidebar `N` > **FSS Tools** > **Auto Seam**) proposes automatic UV seams for hard-surface meshes. It is designed to save time on complex, untextured cockpit and airframe parts.

Using Auto Seam is completely **optional**. It works alongside manual seams: it never removes or overwrites seams you made yourself, unless you click **Clear Current**.

## How It Works

- The tool analyzes the 3D surface, sharp edges, and normal splits of your mesh to find natural seams where islands can flatten with minimal distortion.
- A mesh has two kinds of seams:
  - **Proposed** seams: written by the tool and not accepted yet (marked with the edge attribute `fss_auto_seam`);
  - **Current** seams: every other seam, whether you marked it by hand or accepted it from an earlier proposal.
- The panel shows both counts for the active object, for example "Proposed: 575 | Current: 347".
- **Propose Seams** keeps the current seams; they steer the proposal. A new proposal replaces only the earlier proposed seams.
- None of the buttons changes your UV maps. You decide when to unwrap.

## The Buttons

| Button | Does |
| :--- | :--- |
| **Propose Seams** | Adds proposed seams to the selected objects. Current seams stay. |
| **Accept Proposed** | Makes the proposed seams current seams. Later proposals keep them. |
| **Discard Proposed** | Removes the proposed seams. Current seams stay. |
| **Clear Current** | Removes the current seams (asks first). Proposed seams stay. Use it to propose from scratch. |
| **Select Proposed** / **Select Current** | In Edit Mode, selects those edges on the active mesh. |

Accept, Discard and Clear act on whole objects, also when clicked in Edit Mode. **Ctrl+Z** undoes each of them.

## The Workflow

1. **Mark your critical seams by hand** (optional): wherever you want a specific texture layout, for example along panel joints, visible exterior cuts, or mirrored symmetry edges.
2. **Select objects** in Object Mode.
3. **Propose Seams:** a dialog lists the meshes to process, shared meshes, and any skipped objects. Click **OK** to run.
4. **Review in Edit Mode** (`Tab`) with **Select Proposed** and **Select Current**, and with the **UV Heatmap** after a test unwrap.
5. **Adjust if needed:** add seams by hand, or remove unwanted ones.
6. **Accept Proposed** when you are happy, or **Discard Proposed** to drop the proposal.
7. **Unwrap and Pack:** in Edit Mode, select all faces and unwrap with **UV > Unwrap** (Angle Based). Then pack your islands.

**To replace the current seams with a fresh proposal:** **Clear Current**, then **Propose Seams**, then **Accept Proposed**. The order matters: proposing first would let the old seams steer the proposal.

## What Is Skipped

The confirmation dialog and report list objects skipped by the tool, along with the reason:

| Reason | Explanation |
| :--- | :--- |
| **not a mesh** | Empties, lights, cameras, and curves have no mesh data. |
| **not editable** | Linked library objects or objects whose collections are not editable. |
| **no faces** | Meshes with zero polygons. |
| **no free UV map slot** | Blender supports up to 8 UV maps. The tool needs one temporary slot for calculation. |
| **only decal, glass, invisible or occluder materials** | Objects textured solely with decals, screen glass, windshields, collision boxes, or shadow occluders. Decals and projections rely on custom planar mapping, so automatic unwrapping is skipped. |
| **marked Skip Auto Seam** | The object or one of its ancestors is marked **Skip Auto Seam** in the UV Marks panel (for example fur, hair cards, wire bundles, cables, or decal soups without decal materials). |

An object with mixed materials (for example a cockpit shell with standard paint and decal details) is processed normally.

## Reading the Report

Each run writes or overwrites a text datablock named **FSS Auto Seam Report** in Blender's Text Editor. The panel summary shows the totals and how many meshes need attention.

To open the full report: switch any workspace area to the **Text Editor**, click the file browser dropdown in the header, and select `FSS Auto Seam Report`.

### Report Structure

1. **Summary at the top:**
   - Total meshes processed and total runtime in seconds.
   - Number of meshes needing attention (and how many are clean).
2. **Meshes needing attention first:** any mesh with high distortion, unflattenable charts, or overlapping triangles is listed at the top so you can address issues quickly.
3. **Clean meshes:** listed below the attention block.

### Plain-Language Advice

Repeated problems on one mesh are grouped into one line, with the count, the largest island and the worst value.

| Report Message | What It Means | What To Do |
| :--- | :--- | :--- |
| **N island(s) too stretched: add a seam by hand** | Islands whose area distortion is above 1.25. | Add a manual seam across the high-curvature area to split the island into two flatter pieces. |
| **N quad(s) or face(s) too distorted to flatten: split or flatten them in the mesh** | Single quads or faces that are strongly bent or skewed. A seam cannot run through the inside of a face, so no seam helps. | Fix the mesh: split the quad with an edge (`J` between two corners), or flatten it. |
| **N group(s) of faces with zero area: clean up the mesh** | Collapsed or duplicate faces without area. They cannot be unwrapped at all. | Remove them, for example with **Mesh > Clean Up > Merge by Distance**, then run Propose again. |
| **N chart(s) too distorted to flatten: add seams by hand** | The tool found no safe cut through these larger pieces. | Add manual seams through steep steps or sharp corners. |
| **N island(s) with overlapping triangles: add a seam by hand across the fold** | Triangles overlap in the final 2D unwrap. | Add a relief seam across the fold or fillet causing the overlap. |
| **N sliver overlap(s) ignored (< 1e-8 m²)** | Microscopic sliver triangles (smaller than 0.01 mm²) touch in UV space. | Safe to ignore; texture quality is unaffected. |
| **Warning: Shared mesh '...' has differing or non-uniform scales** | Several objects share this mesh but have different scales. | Blender unwraps in object space, so one UV layout cannot fit all of them. Scale cannot be applied on a shared mesh; either accept the stretch, or give the differently scaled objects their own mesh (**Object > Relations > Make Single User**) and apply scale there. |

## Limits and What to Watch Out For

- **Modal interface:** Blender processes one mesh per step with progress shown in the status bar. The interface is blocked while a single mesh is calculated. Large shells (such as `OVERHEAD_SHELL`) can take 2 to 2.5 minutes to process. Press **Esc** to cancel between meshes (finished meshes keep their results).
- **Modifiers:** seams are placed on the base mesh before **Mirror** and **Array** modifiers. The generated sides inherit the same seam positions.
- **Object scale:** Blender's Angle-Based unwrap operates in object space. If an object has non-uniform scale (`1.0, 1.0, 2.0`), unwrap will stretch unless you apply scale (`Ctrl + A > Scale`).
- **UV Marks panel:** density and direction marks in the **UV Marks** panel are for the packing step and the UV Heatmap; the **Skip Auto Seam** mark in that panel tells Auto Seam to skip marked objects.
- **Undo:** a full run on multiple objects reverts in a single undo step (`Ctrl + Z`).

## UV Heatmap: Distortion and Texel Density

The **UV Heatmap** panel (sidebar `N` > **FSS Tools** > **UV Heatmap**) displays a live per-face distortion overlay directly on the 3D surface in the viewport. It helps review UV quality, identify stretched charts, and verify texel density distribution before packing or texturing.

### Turning It On

- Click **Show UV Heatmap** in the panel to toggle the overlay on selected mesh objects.
- Switch between **Distortion** and **Density** modes.
- The heatmap updates by itself when an object's UVs or geometry change (after an unwrap, as soon as you leave Edit Mode), and when the selection changes. Moving an object keeps its colours on it. Click **Refresh** after changing an object's scale or materials, or whenever the colours look out of date.
- **Opacity** sets how strongly the heatmap colours cover the plain grey shading of the surface (0.3 to 1.0).
- **UV Grid** draws a grid in UV space over the heatmap (8, 16, 32 or 64 cells across the UV square), with a label in each cell (column letter, row number, for example B7). Good UVs give square cells with upright labels; stretched UVs stretch the cells and their labels the same way, and the labels show where each part of the texture ends up. Labels appear when cells are large enough on screen to read; zoom in, or choose fewer cells.
- While the heatmap is on, its objects are shown with **Display As: Wire** and the heatmap draws their surface itself. Their own display setting comes back when the heatmap is off, when you deselect them, and before the file is saved.

### How to Read the Colours

The overlay uses a diverging colour scheme centred on **Neutral 1.0**:

- **Neutral 1.0 (light grey / white):** ideal shape or within the authored density range.
- **Above 1.0 (towards blue):** stretched or sheared triangles (in Distortion mode); over-dense texture resolution (in Density mode).
- **Below 1.0 (towards red):** under-dense texture resolution (in Density mode).
- **Magenta (Error):** faces that cannot be measured because they have no area, in the UVs (collapsed to a point or a line) or on the model. Check them in the UV editor or clean up the mesh.
- Faces are shaded lightly by their angle to the view, so a neutral face turned away looks light grey, not white.

### Modes

1. **Distortion:**
   - Measures the ratio of the larger to the smaller singular value of the affine 3D-to-UV mapping for each triangle (\(\sigma_1 / \sigma_2 \ge 1.0\)).
   - Completely independent of object scale.
   - Values scale from 1.0 (neutral) to 2.0+ (blue).
   - If an area shows dark blue, the geometry is distorted or sheared in UV space. Add manual seams across high-curvature areas to allow the island to relax flatter.
2. **Density (Texel Density):**
   - Measures the triangle's UV area / 3D area relative to its texture set: the area-weighted median over every object in the scene that uses the same material (one atlas per material). The colours therefore do not change with what is selected.
   - Evaluated against the object's authored texel density range (set in the **UV Marks** panel, default 0.9 to 1.1):
     - Inside the authored range: displays as neutral 1.0.
     - Above the range: turns blue on a log scale up to 2.0x.
     - Below the range: turns red on a log scale down to 0.5x.
   - If an object is marked with a higher density preset (such as the glareshield at 1.5 to 1.65), it remains neutral when its density matches that authored target.

### Distribution Chart in the Panel

The panel shows a chart of the selected objects' surface:

- **Colour band:** the same colours as on the model, with the values below it (Distortion 1.0 to 2.0 and more; Density 0.5 to 2.0, with 1.0 inside the object's range).
- **Histogram above the band:** how much of the surface lies at each value, weighted by area. Bar heights use a square-root scale, so small tails stay visible; a tall bar at 1.0 with little else is a good result.
- **Marks:** at 1.10 (our shape target) and 1.25 (the limit Auto Seam uses to accept an island) in Distortion mode; at 1.0 in Density mode.
- **Range bar:** the middle 90 % of the surface (5 % lies below its left end, 5 % above its right end), with its values.
- **Percentages:** the share of the surface over 1.10 and over 1.25, or outside the density range (too low, too high).

### Viewport Legend

A legend in the corner of the viewport displays:

- The active mode (**Distortion** or **Density**) and colour scale.
- For Distortion: the share of the selected objects' surface distorted more than **1.10** (our shape target) and more than **1.25** (the limit Auto Seam uses to accept an island).
- For Density: the share of the surface outside its object's density range (too low and too high).
- **Error:** how many faces cannot be measured, and their share of the surface.
- Skipped objects: mesh objects without active UV maps are safely skipped and listed in the legend without interrupting the tool.

### Non-Destructive and Modifiers

- **Non-destructive:** nothing is written to the mesh or the materials. The only setting changed is the object's **Display As**, temporarily (see above). Exports are untouched.
- **Evaluated geometry:** the overlay evaluates the full modifier stack, displaying generated copies from **Mirror** and **Array** modifiers.
- **Edit Mode:** the heatmap is hidden in Edit Mode, and the object shows its own display setting, because the mesh data are not synced during editing. Switch back to Object Mode to review changes.
