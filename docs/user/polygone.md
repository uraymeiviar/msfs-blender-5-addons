# Polygone: Mesh Reduction

[Artist Guide](README.md) / **polygone.md**
***

The **Polygone** add-on reduces the meshes of the selected objects with libPolygone, the FSS mesh reduction library.
It keeps the shape first, and keeps UVs, normals, colours, materials and vertex groups on the reduced mesh. It is
separate from FSS Blender Tools and from the exporter: enable **Polygone** in **Edit > Preferences > Add-ons**.

The panel is in the 3D Viewport's sidebar (**N**), tab **Polygone**.

## Reduce

| Setting | What it does |
| :--- | :--- |
| **Target** | **Ratio**: keep this fraction of each mesh's triangles. **Triangles**: keep this many per mesh. **Error Only**: no triangle count; reduce until **Max Error** stops it |
| **Max Error** | No collapse moves the surface further than this from the original, in scene units (0 = no limit). The library measures it on samples of the surface: it is not a guarantee |
| **Output** | **New Object**: a reduced copy named `<object>_polygone` next to each object; the original stays. **Replace Mesh**: the object gets the reduced mesh (made from its mesh before modifiers; the modifiers stay) |
| **Apply Modifiers** | New Object only. On: the mesh with its modifiers applied is reduced, and the copy has no modifiers. Off: the base mesh is reduced and the copy keeps the modifiers (use this for meshes with an Armature) |
| **Hide Originals** | New Object only: hide each original so the copy shows in its place. Unhide the original (**Alt+H**) to compare |
| **Reduce Selected** | Reduces every selected mesh object. Objects that share one mesh are reduced once in Replace Mesh |

The result is triangles only. Ngons and quads of the original are triangulated before the reduction.

## Attribute Weights

How strongly each kind of data is kept where points merge (0 = carried along, but not protected):

- **Normals** (default 0.5): the shading normals.
- **UVs** (default 1): every UV map.
- **Colors** (default 1): every colour attribute.

These are the defaults the library is measured with. Higher weights keep texture and shading better and remove
fewer triangles where they change.

## Feature Lines and Locks

| Setting | What it does |
| :--- | :--- |
| **Sharp Edges** | Edges marked sharp are feature lines: their points move only along the line. The number is the line's weight (how strongly its shape is kept) |
| **Marked Seams** | Edges marked as seam are feature lines. Not needed for UV seams: where the UVs split, the library keeps the seam anyway |
| **Creases** | Creased edges are feature lines, weighted by their crease value |
| **Feature Angle** | Edges whose two faces meet at more than this angle are feature lines (0 = off) |
| **Lock Group** | Vertices of this vertex group with weight 0.5 or more are never moved or removed |
| **Importance Group** | Vertices of this group cost more to move: a vertex of weight 1 counts **Strength** times as much (1 = neutral, below 1 = removed first) |

UV seams, normal splits, material borders and borders between flat and smooth faces are kept as lines without any
setting.

## Last Run

For each reduced mesh: triangles and vertices before and after, the error (in scene units and as a percentage of
the mesh's size), why the reduction stopped, and the time:

- **target reached**: the triangle target was met.
- **max error reached**: Max Error stopped it.
- **no collapse left**: locks, feature lines or the library's validity rules leave nothing more to remove. Fewer locks
  or lower weights let it go further.

## Advanced

| Setting | What it does |
| :--- | :--- |
| **Placement** | **Optimal**: merged points go where the error is lowest, with computed UVs and normals. **Subset**: every vertex of the result is an original vertex with its original values |
| **Max Normal Turn** | No triangle turns further than this from the original triangle it came from (degrees) |
| **Normal Merge Angle** | Corners at one position with the same UVs whose normals differ by less than this are one vertex. Blender stores custom normals with a small error; 1 degree joins what was one normal in an imported glTF (0 = exactly equal only) |
| **Lock Open Borders** | Open borders (edges with one face) are kept exactly |
| **Lock Material Borders** | Borders between materials, and between flat and smooth faces, are kept exactly |
| **Parallel Meshes** | How many meshes are reduced at the same time (each mesh on one CPU thread) |
| **Switches** | The library's experimental switches, for testing. Each is listed at its default |

## Library

Shows whether the library loaded. The add-on ships its own `polygone.dll`. In the add-on's preferences, **DLL** can
name another `polygone.dll` (a newer build of libPolygone); **Reload Library** loads it without restarting Blender.

## Limits

- **Windows 64-bit only:** the library ships as a Windows DLL.
- **Not kept:** shape keys, and the vertex weights of vertices the reduction moved come from the original vertex
  each one descends from.
- **Double-sided geometry:** two faces on the same three points stay, each on its own vertices.
