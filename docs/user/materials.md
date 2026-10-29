# Materials: Users, Zones and Surface per Material

[Artist Guide](README.md) / **materials.md**
***

The **Materials** panel (sidebar `N` > **FSS MSFS Tools** > **Materials**, below **Zones & Merge Tree**) lists every material of the `.blend` with the objects that use it, their zones, and how much surface each material covers. It shows what Blender's own material lists scatter over many places: which materials are never used, which are used in more than one zone, which are transparent or emissive, and roughly which texture size a material needs.

The panel only reads, with one exception: the **Keep UVs** checkbox of the active material, the same setting as in [Packing](fss-tools.md#packing). It changes no other material setting, no object and no tag; **Select Objects** only changes the selection.

## Refresh

Press **Refresh** (in Object Mode) to fill the panel. Before the first Refresh the panel only shows the button.

The panel shows the scene as it was at the last Refresh: it does not follow your changes. Press Refresh again after you assign materials, move objects into another zone, or change density marks.

What Refresh counts:

- **Objects using a material:** the mesh objects of the view layer, visible or hidden, with at least one face that has the material. A material that sits only in a slot without faces, only on objects outside the view layer, or in no slot is **never used**.
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
| Texture | The texture size set in [Packing](fss-tools.md#packing) and the last **Pack** or **Check All** result of this session |

The legend below the list repeats the three icons. The transparent and emissive marks need the FSS exporter add-on, which defines the MSFS material settings; without it the panel shows no marks.

Why the warnings matter:

- **Never used:** a material no face uses still sits in the file. Delete it, or assign it where you meant to.
- **Shared across zones:** each zone should have its own materials (step 2 of the [pipeline](README.md#2-zones-and-materials-in-development)). A material used in two zones keeps the texture of both zones in memory while only one is seen. Give one zone a material of its own, or move the objects into the right zone.

## The Active Material

Click a row to show its details below the list:

- **Objects:** how many objects use the material, how many of them are hidden, and how many meshes are shared by more than one of these objects.
- **Zones:** per zone, the objects and the surface. With more than one zone, each line carries the warning icon and a line says how many zones share the material.
- **Surface:** the total area, and **about N px square (estimate, with visibility)**: the side of a square texture that would hold the material's faces at the top of their texel density range, lowered for the parts the pilot sees little. It reads **(estimate, no visibility data)** when none of the material's objects had visibility data. A material with **Keep UVs** shows **kept (Keep UVs): no estimate** instead.
- **Texture:** the texture size and the last **Pack** or **Check All** result (**not packed or checked yet** before the first), or **kept**.
- **Keep UVs:** leaves the material's texture set out of **Pack** and **Check All** and keeps its UVs as they are. It is the same checkbox as in [Packing](fss-tools.md#packing): ticking it here ticks it there. The box shows **kept** at once, without **Refresh**.
- **Select Objects:** selects the visible objects that use the material and makes the first one active. With more than one zone, a **Select in** button per zone selects only that zone's objects.

## The Estimate and Check All

The estimate is the surface times the density each part asks for: the target density times the high end of its density range (the density freedom times the density marks above it, zone marks included; see [Packing](fss-tools.md#packing)) times the object's visibility. The visibility is the object's score that the **Visibility** line of **Packing** shows: a part the pilot never sees counts with 0.1, a part seen a little never with less than 0.1. Without visibility data (the `.blend` not saved, no `.visibility` file beside it, or an object changed since the analysis) a part counts with 1.0, as for packing. Refresh reads the `.visibility` file again; run **Refresh** after a new analysis.

The estimate uses one score per object, while packing scores each island, and it leaves out the margins between islands and the gaps that packing cannot fill. Take it as a first hint of whether a material needs 1024 or 8192 pixels, not as the size.

**Check All** below the active material box is the same button as in **Packing**: it packs every texture set as **Pack** would, without writing UVs, and reports for each whether its islands fit the texture size at their density, and which size they need. Its result appears in the list's texture column and in the active material's **Texture** line. While it runs, the panel shows its progress; **Cancel** or **Esc** stops it after the texture set in work.

## Colliders, Fur and Decal Sheets: Keep UVs

Some materials get no texture packed by the FSS tools: colliders (an invisible material), fur and hair cards, decal sheets whose UVs you laid out by hand. Without a mark, the panel gives them a size estimate as if they needed a texture, and they often show the largest estimates of the file. Mark such a material once:

1. Click the material's row.
2. Tick **Keep UVs** in the box below the list.

You do not need **Select Objects** for this: the mark sits on the material, so it covers every object that uses it, now and later. The box then shows **kept** instead of the estimate, and **Pack** and **Check All** leave the material alone.

## Keeping a Material's Objects out of Merging

Some objects must stay their own nodes although they could be merged: colliders, clickspots, screens, a glass that overlaps another glass (see [Merge Tree](README.md#4-merge-tree)). When those objects share a material, the material is the quickest way to find them all:

1. Click the material's row, then **Select Objects** (or **Select in** for one zone).
2. In [Tags](fss-tools.md#tags), give the selected objects a tag, for example `COLLIDER`.
3. Switch on the tag's **Don't Merge**.

The merge never decides by material: the tag keeps the objects separate, also when you later assign them another material.

## By Zone

The **By Zone** subpanel (closed by default) lists, per zone and for **(no zone)**, the materials used there, largest surface first: for each, the objects in that zone, their surface, and its share of the zone's surface. Use it to see how full a zone's materials are compared with each other. It shows the same Refresh as the list.
