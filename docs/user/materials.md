# Materials: Users, Zones and Surface per Material

[Artist Guide](README.md) / **materials.md**
***

The **Materials** panel (sidebar `N` > **FSS MSFS Tools** > **Materials**, below **Zones & Merge Tree**) lists the materials of the `.blend` with the objects that use them, their zones, and how much surface each material covers. It shows what Blender's own material lists scatter over many places: which materials are never used, which are used in more than one zone, which are transparent or emissive, and roughly which texture size a material needs.

The panel only reads, with these exceptions: the **Keep UVs** checkbox of the active material, the same setting as in [UV Auto Packing](fss-tools.md#uv-auto-packing), and the texture flags and **Write XMLs** of [Texture Sets and Texture XMLs](#texture-sets-and-texture-xmls). It changes no other material setting, no object and no tag; **Select Objects** only changes the selection.

## Refresh

The panel fills itself when you open a `.blend` in Object Mode, so it shows the file's materials at once. Otherwise, press **Refresh** (in Object Mode) to fill it; until then the panel only shows the button and "Press Refresh to list the materials".

The panel shows the scene as it was at the last Refresh ("Shows the scene at the last Refresh"): it does not follow your changes. Press Refresh again after you assign materials, move objects into another zone, or change density marks.

What Refresh counts:

- **Objects using a material:** the mesh objects of the view layer, visible or hidden, with at least one face that has the material. A material that sits only in a slot without faces or in no slot is **never used**. A material whose faces are only on objects outside the view layer (for example in an excluded collection) is not part of the model and gets no row.
- **Zones:** the nearest `@ZONE_` empty above each of those objects (see [Zones and Materials](README.md#2-zones-and-materials-in-development)); objects outside every zone count as **(no zone)**.
- **Surface:** the 3D area of the faces with the material, in the world (scale included). A mesh shared by several objects (a linked duplicate) shares its UVs, so its area counts once, on the first of its objects by name, and in that object's zone.

## The Material List

Click **All** to list every material, **Warnings** to list only those with a warning. The filter below the list (the small arrow) finds materials by name.

Each row shows, from left to right:

| Column | Meaning |
| :--- | :--- |
| Warning icon | The material is **never used**, or **shared across zones** (used by objects in more than one zone, **(no zone)** counting as a zone) |
| Transparent icon | The material's MSFS **Alpha Mode** is **Blend** (glass, windshields, decals drawn transparent). Alpha below 1 alone does not count: alpha can come from a texture |
| Emissive icon | An **Emissive** texture is assigned in the material's MSFS settings |
| Name | The material's name |
| Objects and zones | How many objects use it, and their zones (`–` for objects outside every zone); **never used** when none does |
| Texture | The texture size set in [UV Auto Packing](fss-tools.md#uv-auto-packing) and the last **Pack** or **Check All** result of this session |

**Name Width**, the slider below the list, sets how wide the name column is; the zones get the rest. The texture column is narrow, so a long **Check All** result shows in full only in the details below the list. The legend below the list repeats the three icons. The transparent and emissive marks need the FSS exporter add-on, which defines the MSFS material settings; without it the panel shows no marks.

Why the warnings matter:

- **Never used:** a material no face uses still sits in the file. Delete it, or assign it where you meant to. If it stays in the file, **Select Objects** finds the objects that hold it, also in a mesh slot that an object-linked material replaces. To clear such a slot: set the slot's **Link** to **Data**, remove the material with **X**, and set **Link** back to **Object**. The material leaves the file when you save and reopen it.
- **Shared across zones:** each zone should have its own materials (step 2 of the [pipeline](README.md#2-zones-and-materials-in-development)). A material used in two zones keeps the texture of both zones in memory while only one is seen. Give one zone a material of its own, or move the objects into the right zone.

## The Active Material

Click a row to show its details below the list:

- **Objects:** how many objects use the material, how many of them are hidden, and how many meshes are shared by more than one of these objects. For a material never used: how many objects hold it in a slot no face uses.
- **Zones:** per zone, the objects and the surface. With more than one zone, each line carries the warning icon and a select button for that zone's objects, and a line says how many zones share the material.
- **Surface:** the total area, and **about N px square (estimate, with visibility)**: the side of a square texture that would hold the material's faces at the top of their texel density range, lowered for the parts the pilot sees little. It reads **(estimate, no visibility data)** when none of the material's objects had visibility data. A material with **Keep UVs** shows **kept (Keep UVs): no estimate** instead.
- **Texture:** the texture size and the last **Pack** or **Check All** result (**not packed or checked yet** before the first), or **kept**.
- **Keep UVs:** leaves the material's texture set out of **Pack** and **Check All** and keeps its UVs as they are. It is the same checkbox as in [UV Auto Packing](fss-tools.md#uv-auto-packing): ticking it here ticks it there. The box shows **kept** at once, without **Refresh**.
- **Select Objects:** selects the visible objects that use the material and makes the first one active. For a material never used, it selects the visible objects that hold it in a slot instead.

## The Estimate and Check All

The estimate is the surface times the density each part asks for: the target density times the high end of its density range (the density freedom times the density marks above it, zone marks included; see [UV Auto Packing](fss-tools.md#uv-auto-packing)) times the object's visibility. The visibility is the object's score that the **Visibility** line of **UV Auto Packing** shows: a part the pilot never sees counts with 0.1, a part seen a little never with less than 0.1. Without visibility data (the `.blend` not saved, no `.visibility` file beside it, or an object changed since the analysis) a part counts with 1.0, as for packing. Refresh reads the `.visibility` file again; run **Refresh** after a new analysis.

The estimate uses one score per object, while packing scores each island, and it leaves out the margins between islands and the gaps that packing cannot fill. Take it as a first hint of whether a material needs 1024 or 8192 pixels, not as the size. It comes from the surface of the mesh, not from the UVs: faces stacked on one UV area, such as the layers of fur shells, each count, so it can ask for far more than such a material's texture holds. Mark those with **Keep UVs**.

**Check All** below the active material box is the same button as in **UV Auto Packing**: it packs every texture set as **Pack** would, without writing UVs, and reports for each whether its islands fit the texture size at their density, and which size they need. Its result appears in the list's texture column and in the active material's **Texture** line. While it runs, the panel shows its progress; **Cancel** or **Esc** stops it after the texture set in work.

## Colliders, Fur and Decal Sheets: Keep UVs

Some materials get no texture packed by the FSS tools: colliders (an invisible material), fur and hair cards, decal sheets, and any material whose UVs you laid out by hand. **Pack** would replace those UVs. Without a mark, the panel gives them a size estimate as if they needed a texture, and they often show the largest estimates of the file. Mark such a material once:

1. Click the material's row.
2. Tick **Keep UVs** in the box below the list.

You do not need **Select Objects** for this: the mark sits on the material, so it covers every object that uses it, now and later. The box then shows **kept** instead of the estimate, and **Pack** and **Check All** leave the material alone.

## Keeping a Material's Objects out of Merging

Some objects must stay their own nodes although they could be merged: colliders, clickspots, screens, a glass that overlaps another glass (see [Merge Tree](README.md#4-merge-tree)). When those objects share a material, the material is the quickest way to find them all:

1. Click the material's row, then **Select Objects** (or the select button on a zone's line for one zone).
2. In [Tags](fss-tools.md#tags), give the selected objects a tag, for example `COLLIDER`.
3. Switch on the tag's **Don't Merge**.

The merge never decides by material: the tag keeps the objects separate, also when you later assign them another material.

## By Texture Need

The **By Texture Need** subpanel (closed by default) compares the materials: which texture size each one needs, largest estimate first. Use it to plan texture sizes. Each line shows the material, its estimate, its texture size and one of these:

| Text | Meaning |
| :--- | :--- |
| **about right** | The estimate fits this size, and the next smaller one is too small |
| **oversized, 2048 would do** | A smaller size would hold the estimate |
| **too small, 8192 needed** | The estimate needs a larger size (warning icon) |
| **too small, 8192 or more** | The estimate is above 8192 (warning icon) |
| A **Check All** result | Once a material is checked, the packed result replaces the verdict, which is only an estimate |
| **kept** | **Keep UVs** is on; these materials come last, by name |

Left out: materials never used, the MSFS material types **Invisible**, **Environment Occluder** and **Collision** (by type, not by name), and materials whose objects all have a tag with [No Texture](fss-tools.md#tags). It shows the same Refresh as the list. **Check All** writes no UVs, so nothing here changes the model.

## Texture Sets and Texture XMLs

The **Texture Sets** subpanel lists the textures of the used materials: for each material its slots with the slot's role (such as `ALB`, `ORM`, `NML`), the file's channels and bit depth, and warnings where the file does not suit the role (for example an 8-bit normal map). **Check Data Depth** reads the pixels of 16-bit files and marks 8-bit data saved as 16-bit.

Above the materials, the texture XML list shows what an MSFS 2024 export writes for the package (see [exporter.md](exporter.md#texture-folder-and-texture-xmls-msfs-2024)): the textures of the objects the export takes (the enabled multi-exporter presets, or the visible objects when there are none). The **Texture Folder** is shown at the top. Each texture has one row:

- its **slot** in the package (read from the material, not editable); a warning when one texture is used in slots that do not go together;
- its six **flags**: Quality High, Alpha Preservation, No Reduction, No Mipmap, Precomputed Inverse Average and the Anisotropic level. They are saved with the image and written into its XML;
- the state of its XML in the folder: **missing**, **matches**, **differs** (what the file says is shown), or **no PNG** when the PNG is not in the folder.

**Write XMLs** writes the XMLs of the listed textures without exporting, the same files an export writes. **Refresh** (also when the file opens) reads an XML already in the folder into Blender once, so flags set in it are kept; after that, Blender's flags win.
