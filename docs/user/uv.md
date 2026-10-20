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

| Report Message | What It Means | What To Do |
| :--- | :--- | :--- |
| **1 island too stretched (N faces, distortion X.XX): add a seam by hand** | An island has an area distortion ratio greater than 1.25. | Add a manual seam across the high-curvature area to split the island into two flatter pieces. |
| **1 quad too distorted to flatten (2 faces, d=X.XX): check the mesh** | A single quad is non-planar or degenerate and cannot be flattened without tearing. | Inspect the mesh geometry. Straighten or planarize the quad, or cut it with a manual seam. |
| **1 chart too distorted to flatten (N faces, d=X.XX): check the mesh** | The algorithm could not find a safe cut path across this chart. | Inspect the mesh topology. Add manual seams through steep steps or sharp corners. |
| **1 island has overlapping triangles (N pairs, X faces): add a seam by hand** | Triangles overlap in the final 2D unwrap. | Add a relief seam across the fold or fillet causing the self-intersection. |
| **N sliver overlap(s) ignored (< 1e-8 m²)** | Microscopic sliver triangles (smaller than 0.01 mm²) touch in UV space. | Safe to ignore; texture quality is unaffected. |
| **Warning: Shared mesh '...' has differing or non-uniform scales** | Several objects share this mesh but have different scales. | Blender unwraps in object space. Apply scale (`Ctrl + A > Scale`) on the sharing objects where possible. |

## Limits and What to Watch Out For

- **Modal interface:** Blender processes one mesh per step with progress shown in the status bar. The interface is blocked while a single mesh is calculated. Large shells (such as `OVERHEAD_SHELL`) can take 2 to 2.5 minutes to process. Press **Esc** to cancel between meshes (finished meshes keep their results).
- **Modifiers:** seams are placed on the base mesh before **Mirror** and **Array** modifiers. The generated sides inherit the same seam positions.
- **Object scale:** Blender's Angle-Based unwrap operates in object space. If an object has non-uniform scale (`1.0, 1.0, 2.0`), unwrap will stretch unless you apply scale (`Ctrl + A > Scale`).
- **UV Marks panel:** density and orientation settings in the **UV Marks** panel are for texture baking and packing; they are not read by Auto Seam.
- **Undo:** a full run on multiple objects reverts in a single undo step (`Ctrl + Z`).
