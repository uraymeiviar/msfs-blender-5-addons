# Auto Seam: Automated UV Seams

[Artist Guide](README.md) / **uv.md**
***

The **Auto Seam** panel (sidebar `N` > **FSS Tools** > **Auto Seam**) proposes automatic UV seams for hard-surface meshes. It is designed to save time on complex, untextured cockpit and airframe parts.

Using Auto Seam is completely **optional**. It works alongside manual seams: it never removes or overwrites seams you marked yourself.

## How It Works

- The tool analyzes the 3D surface, sharp edges, and normal splits of your mesh to find natural seams where islands can flatten with minimal distortion.
- Proposed seams are stored as regular Blender edge seams and marked with a boolean attribute (`fss_auto_seam`).
- Existing seams that you marked by hand are preserved as **artist seams**. A new proposal replaces only earlier automatic seams.
- Running **Propose Seams** does not change your existing UV maps or unwrapped UV coordinates. You decide when to unwrap.

## The Workflow

1. **Mark your critical seams by hand:** place seams wherever you want a specific texture layout (for example along panel joints, visible exterior cuts, or mirrored symmetry edges).
2. **Select objects:** select the mesh objects in Object Mode.
3. **Propose Seams:** click **Propose Seams** in the Auto Seam panel. A dialog lists the meshes to process, shared meshes, and any skipped objects. Click **OK** to run.
4. **Review in Edit Mode:** select a mesh and switch to Edit Mode (`Tab`):
   - **Select Auto:** selects only the edges proposed by the tool.
   - **Select Artist:** selects only your manual seams.
5. **Adjust if needed:** add seams where you want more cuts, or clear unwanted seams.
6. **Keep as Artist Seams:** in Object Mode, click **Keep as Artist Seams**. This removes the automatic mark; from now on, all seams are treated as authored artist seams and will not be overwritten by future proposals.
7. **Unwrap and Pack:** switch to Edit Mode, select all faces, and unwrap with **UV > Unwrap** (Angle Based). Then pack your islands with your packing tool.

## What Is Skipped

The confirmation dialog and report list objects skipped by the tool, along with the reason:

| Reason | Explanation |
| :--- | :--- |
| **not a mesh** | Empties, lights, cameras, and curves have no mesh data. |
| **not editable** | Linked library objects or objects whose collections are not editable. |
| **no faces** | Meshes with zero polygons. |
| **no free UV map slot** | Blender supports up to 8 UV maps. The tool needs one temporary slot for calculation. |
| **only decal, glass, invisible or occluder materials** | Objects textured solely with decals, screen glass, windshields, collision boxes, or shadow occluders. Decals and projections rely on custom planar mapping, so automatic unwrapping is skipped. |

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
- **UV Marks panel:** density and direction marks in the **UV Marks** panel are for the coming packing step; they are not read by Auto Seam.
- **Undo:** a full run on multiple objects reverts in a single undo step (`Ctrl + Z`).
