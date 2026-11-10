# FSS MSFS Tools and FSS Tools Panels

[Artist Guide](README.md) / **fss-tools.md**
***

FSS Blender Tools has two tabs in the 3D Viewport sidebar (`N`).

**FSS MSFS Tools**, its panels from top to bottom in the order of the pipeline:

- **Zones & Merge Tree**
- **Materials**, its own page [materials.md](materials.md)
- **Tags**
- **Object LOD**, **Viewport LOD** and **LOD Settings**, their own page [lod.md](lod.md)
- **UV Auto Seam**, closed at first: proposes UV seams (the full guide is on its own page, [uv.md](uv.md))
- **UV Auto Packing**, closed at first: the UV marks and the packer per texture set, with the section **Visibility Scoring** inside

**FSS Tools**, its panels from top to bottom, all closed at first:

- **General**
- **Empty Bounds**
- **Heatmap**
- **Checks**

This page describes all of them except Materials and the three LOD panels. Each panel and section opens and closes on its own; Blender remembers that in the `.blend`.

The **UV Editor**'s sidebar (`N`) has an **FSS MSFS Tools** tab too, with the **UV Auto Packing** panel (without Visibility Scoring); it shows in the UV Editor only, not in the Image Editor's image view.

**When you open a `.blend`,** **Zones & Merge Tree**, **Materials** and **Scan Names** (in **Checks**) fill their lists by themselves, so they show the file's own data without a click on **Refresh**. Materials does this only when the file opens in Object Mode. After that, the lists do not follow your changes: press **Refresh** (or **Scan Names**) again. **Refresh LOD Counts** and **Check All** take longer and stay manual.

## Zones & Merge Tree

Merge groups join many small objects into one mesh at export, while every part stays a separate, editable object in the `.blend`. Fewer meshes means fewer draw calls in the simulator. Zones hold the merge groups: the panel lists each zone with its groups, and edits the zone's density mark.

### Name Prefixes

- **`@ZONE_<NAME>`:** a zone empty (see [step 2 of the Artist Guide](README.md#2-zones-and-materials-in-development)). Every merge group belongs below one zone; a zone never lies inside a merge group or inside another zone.
- **`@MERGE_<name>`:** an object (empty or mesh) with this name prefix starts a merge group. At export, it and its subtree become one mesh named `<name>`. A mesh root merges its own geometry too.
- **`@NOMERGE_<name>`:** an object inside a group with this prefix stays out of the merge, with its subtree, and is exported as `<name>`.
- The prefixes never reach the glTF: exported names are always without them.
- Any other name starting with `@` loses only the `@` at export: a zone empty `@ZONE_FWD` exports as `ZONE_FWD`. Make sure no other object exports under the same name; **Scan Names** reports it (`CLS`).

### What Stays Separate

Inside a group, these objects stay their own nodes, together with everything below them:

- a nested `@MERGE_` group (it merges on its own and becomes a child of the outer merged mesh);
- a `@NOMERGE_` object;
- an animated object (an action or NLA tracks);
- a skinned object (an armature, or a mesh with an Armature modifier);
- an object parented to a bone (the group root itself may be bone-parented: the merged mesh keeps that bone parent);
- a mesh with shape keys;
- an object with a **Don't Merge** tag;
- any object that is not a mesh, curve, surface, text, metaball or empty (for example lights and cameras).

If the root itself is animated or skinned, the whole group stays unmerged, with a warning.

When an object stays separate deep inside a group, every object above it that the merge removes is replaced by an empty with the same name and position, so animated buttons keep their exact pivot.

Transparent materials (MSFS alpha mode Blend) never share a mesh with opaque ones: the transparent parts become a child mesh `<name>_TRANSPARENT`.

### Panel

- **Merge on Export:** turns merging on or off for the scene (on by default).
- **New Merge Group:** select objects with the same parent (or the same parent bone), press the button and type a name (for example `OVHD_PANEL`). It creates the empty `@MERGE_OVHD_PANEL` at the parent's position and moves the objects under it without moving them in the world.
- **Refresh:** lists the zones and merge groups of the visible objects. The list fills by itself when you open a `.blend`. Click a row to select that object. The list does not follow later changes in the scene; press **Refresh** again.
  - **Totals**, the line above the list, for all visible objects: zones, merge groups (`merge`), `@NOMERGE_` rows (`no-merge`), rows with a warning triangle, and the materials their faces use.
  - **Objects**, the line below the totals: the objects with geometry before and after the merge, with the change in percent, for example `Objects: 2241 -> 1332 (-41%)`. It counts every visible object, inside a zone or not, because the deploy exports the visible objects, so it can be higher than the sum of the zone rows. It is the full model, before the LOD rules leave anything out of the far LODs. Refresh with the Viewport LOD preview off: objects the preview hides are not counted.
  - **Stray** and **Below `@NOMERGE_`**, the two buttons below that line: visible objects with geometry that could merge but that no group merges, with their count at the last **Refresh**. **Stray** objects have no `@MERGE_` or `@NOMERGE_` node above them, so they may have missed a group. **Below `@NOMERGE_`** objects sit below a `@NOMERGE_` node or another node that stays out of a group; many of those are meant to stay, so review them. Click a button to select them, **Shift**-click to add to the selection. Not counted: `@NOMERGE_` objects themselves, objects that cannot merge (see [What Stays Separate](#what-stays-separate)), objects with a tag marked **Invisible** or **Animated**, animated objects, and the direct children of an empty that is animated or has such a tag.
  - **Zone rows** (`@ZONE_` empties, without the prefix): the meshes below the zone before and after the merge, for example `951 -> 128 obj`, which is the number of mesh nodes the export writes there. Meshes without faces are not counted, because they export as plain nodes. A merged mesh with 6 materials is one object but still 6 draw calls. The row also has the zone empty's own **density mark** (see [UV Auto Packing](#uv-auto-packing)): a tick for the mark, then its **Min** and **Max** factors, greyed while the tick is off. Marks multiply down the hierarchy, so the zone's factor applies to everything below it: 2.0 for twice the texels per metre, 0.5 for half; type the same value in both fields for one factor. A change is stored on the zone empty at once, without **Refresh**, and is the same mark the **UV Auto Packing** panel shows for that empty.
  - **Merge group rows**, below their zone and nested as in the scene, with objects, materials and kept-separate counts per group. Materials are read from the faces, as the export does: a slot no face uses does not count, and faces without a material count as one, shown as **(no material)**.
  - **Warning triangle on a group row:** the export would warn about this group: several materials, opaque and transparent parts together, UV maps named differently at the same position or a third UV map, a merged mesh named like a node that stays, or a root that cannot merge.
  - **Details below the list:** the active group's materials, transparency split, UV map problems and reasons for keeping objects separate are buttons with their object count. Click one to select those objects, for example every part using a material or every animated part. **Shift**-click adds to the selection. The selection comes from the scene as it is now, so a button can find fewer objects than its count until the next **Refresh**.
  - **`@NOMERGE_` rows**, one level below the group they belong to: these objects stay their own nodes under the merged mesh.
  - **Unzoned** (warning): merge groups with no zone above them. Move them below a `@ZONE_` empty.
  - **Warnings on zone rows:** a zone inside a merge group (it would be merged into the group's mesh) or inside another zone.

### Merge Pitfalls

- **Merging only happens in a deploy** (or the MSFS 2024 multi-exporter), where the exported objects are throwaway copies. A plain **File > Export > glTF 2.0** of the open file leaves the groups unmerged and warns.
- **The merge does not read the model XML.** An object the XML refers to (a screen, a clickspot, an animation target) is merged away unless it is animated, tagged **Don't Merge**, named `@NOMERGE_`, or kept for another reason. Check the Zones & Merge Tree before deploying.
- **Transparent parts share one mesh per group** (`<name>_TRANSPARENT`), and MSFS sorts transparent surfaces by the centre of each mesh: two glasses that overlap on screen can flicker, and a decal on a surface far behind others can show on a surface in front. Keep such glass or decals out of the group with a **Don't Merge** tag; see [step 4 of the Artist Guide](README.md#4-merge-tree).
- **Several materials in one group** stay several materials; the panel and the console warn so you can check that this is intended.
- **More than two UV maps** in a group: only two are exported. UV maps are matched by name; if members name them differently, they are matched by position, with a warning.
- **A merged name equal to a kept object's name** gives a warning; rename one of them.

## Tags

A tag is a free label you put on objects, for example `SCREEN` or `KEEP_LOD`. An object can have several tags. Tags replace extra collections for grouping, and toggles on each tag set how tagged objects are treated by the export, by the panels and by a later AO auto-bake. Tags are stored in the object's custom property `fss_tags` (separated by `;`), so you can also read them under **Object Properties > Custom Properties**.

- **Top row:** type one or more tag names (separate several with `;` or `,`), then **+** adds them to the selected objects, **-** removes them.
- **Active object box** (only while the active object is selected): the tags of the active object; **X** removes one from the active object only.
- **Tag list** (every tag in the file, with the number of objects that carry it). Per row:
  - **-** and **+** (only with a selection): remove the tag from, or add it to, the selected objects. They are greyed out when there is nothing to do and highlighted red when several objects are selected.
  - **Rename** (pencil): renames the tag on every object in the file, and in the settings of the toggles below.
  - **Tag name:** select the visible objects with this tag (**Shift + click** adds to the selection). Hidden objects are counted but not selected. The name has a blue fill when at least one selected object has this tag.
  - **Don't Merge** (merge icon): objects with this tag, and everything below them, stay out of merge groups (see [Zones & Merge Tree](#zones--merge-tree)).
  - **Keep** (pin icon, pinned and blue when on): objects with this tag are never hidden for being small. The automatic LOD size rule leaves them, and the Auto objects above them, in every LOD, like the **Keep** mark (see [Object LOD](lod.md#object-lod)). They cost vertices in the far LODs. A **Hidden from** or **Visible from** mark on the object or a parent still wins.
  - **Non-AO-Occluder** (ghost icon, blue when on): objects with this tag never darken other objects in the AO auto-bake. They can still get AO of their own.
  - **Skip-AO-Bake** (render icon, crossed out and blue when on): objects with this tag get no AO in the AO auto-bake. They can still darken other objects.
  - **Invisible** (eye icon, blue when on): marks objects that MSFS does not draw. They no longer count as **Stray**. Only a mark: the model and the export do not change.
  - **Animated** (action icon, blue when on): marks parts Blender has no animation for, because the model XML animates them. They no longer count as **Stray**, nor do the direct children of a marked empty. Only a mark: the merge does not read it, so such a part inside a group needs **Don't Merge** as well.
  - **Whole** (cube icon, blue when on): the LOD export does not drop the small loose pieces of these objects one by one. The object still leaves by the size rule or a mark, all at once (see [How Nesting Affects the Size Rule](lod.md#how-nesting-affects-the-size-rule)).
  - **No Texture** (texture icon, blue when on): for objects that need no texture, for example gauge screens. A material leaves [By Texture Need](materials.md#by-texture-need) at the next **Refresh** in **Materials** once every object using it, hidden ones too, has such a tag. The AO auto-bake skips these objects, but they can still darken others. **Pack** does not read it yet.
  - **No Export** (export icon, blue when on): objects with this tag, and everything below them, are left out of every glTF export and out of merge groups, for example the probe lights of [Visibility Scoring](#visibility-scoring) and the empty above them. They stay in the `.blend` and in the viewport.
  - **Delete** (bin): asks for confirmation, then removes the tag from every object in the file. The objects stay.

The two AO toggles only record your choice for now: there is no AO auto-bake tool yet, so they change nothing in the model or the export. They apply to the objects that carry the tag, not to their children. With both on, the bake is meant to ignore the object completely, which suits collision meshes, clickspots, helpers and decals.

Tip: to tag a whole collection, right-click it in the Outliner, **Select Objects**, then press **+** on the tag row.

## UV Auto Seam

In the tab **FSS MSFS Tools**, closed at first. Seams come first in the UV work, packing after: the steps 6 to 8 of the [Artist Guide](README.md#the-pipeline).

Automated UV seam proposal for hard-surface meshes, with a **Distortion Limit** slider between less distortion and fewer islands, and **Accept + Unwrap** (Angle Based). See [uv.md](uv.md) for the complete guide, workflow, readable reports, and limits.

- **Skip Auto Seam / Clear:** marks the selected objects to be skipped by **Propose Seams** (for example fur, hair cards, wire bundles, cables, or decal soups). Children inherit the mark unless cleared or marked themselves. The box shows whether the active object is processed or skipped, and where that comes from (**own mark**, **from** an ancestor, or **default**).

## UV Auto Packing

In the tab **FSS MSFS Tools**, closed at first. How much texture each part gets, the settings of each texture set, and the packer. The marks are also read by the heatmap's Density mode. Every field takes effect as you change it; there is no Apply button.

The same panel is also in the **UV Editor**'s sidebar (**N**), tab **FSS MSFS Tools** > **UV Auto Packing**, so you can pack and see the result side by side. **Visibility Scoring** is only in the 3D viewport's panel.

- **Target density** (for the scene): the texel density at factor 1.0, in pixels per centimetre. The default 20.48 is 2048 pixels per metre.
- **Density freedom Min / Max** (for the scene, default 0.90 and 1.10): how far the packer may scale any island down or up. It applies once, at the top of the hierarchy.
- **Active object box:** for the active object, how its density comes together:
  - **Parent:** the factor range of everything above it, for example `x1.35 - x1.82 from DOOR_L` (the nearest marked parent is named), or `x0.90 - x1.10 (scene freedom)` when nothing above it is marked.
  - **Zone:** the zone the object lies in and the zone empty's own factor. It is already part of **Parent**; the row only shows where the zone stands.
  - **Visibility:** the object's score from [Visibility Scoring](#visibility-scoring) and the range of its islands' scores. **no data: x1.00** when the `.visibility` file is missing or the mesh changed since; **never lit: x0.10** when no probe light reaches it in any step: it scores the **Ambient** of Visibility Scoring (0.1 by default), the lowest score there is. Shown in Object Mode. The **Heatmap**'s Density mode follows a change of a mark (on the object or above it) shortly after you stop dragging.
  - **Density:** the object's own mark. Tick **own mark** to give it a factor, then set **Min** and **Max** (the same value in both for one factor); the fields are greyed while the tick is off. An object without its own mark counts as x1.0.
  - **Lower** (x0.75, for parts that are hardly seen), **Higher** (x1.5, for prominent parts such as the glareshield) and **Clear** (remove the own mark) act on all selected objects.
  - **Result:** the density range in pixels per centimetre that the packer may give the object's islands: target × parent × own mark × visibility, and in brackets the range over its islands' visibility.
  - **Direction:** how islands may turn when packed; the active object's direction is highlighted, and the box names the parent it comes from. The buttons act on all selected objects:
    - **Free:** any angle.
    - **Upright:** no rotation (brushed metal, wood grain, text).
    - **Flip:** 0 or 180 degrees only.
    - **Quarter:** 90-degree steps only.
    - **Clear:** remove the mark (inherit from the parent, else Free).
- **Texture set list:** every material of the selected objects, the active object's first. Each row shows the material and its last result (see **Last run**; empty before the first run). The list shows 5 rows and scrolls; drag its lower edge to show more, or type in its filter field to find a material by name. A lock marks a set with **Keep UVs**, a warning sign a set whose last run found faces without area or triangles without UV area. With nothing selected, the panel says so.
- **Texture set box**, below the list: the row you clicked (before you click one, the first row):
  - **Size:** the texture set's size, square, 256 to 8192 pixels per side (default 4096 × 4096). Choose the size; **Pack** and **Check All** report when the islands do not fit at their density, or leave space, and which size would fit. Files from versions before 0.33.0 had a width and a height: the larger of the two becomes the size when the file opens.
  - **Margin:** the gap between two islands, in pixels of this texture set (default 8). 8 pixels keep islands apart down to the second mip level after the 4 × 4 block compression of the textures; below 4 pixels the box warns that compressed blocks bleed across islands.
  - **Keep UVs:** leave this texture set alone: **Pack** is greyed out and **Check All** lists it as **kept**. For fur and hair cards, decal sheets and colliders, whose UVs map onto a strand or label sheet on purpose, and for any material whose UVs you laid out by hand: **Pack** would replace them. It is stored on the material.
  - **Pack:** packs the texture set (see [Pack](#pack) below). It replaces the UVs of every face with this material; **Ctrl + Z** undoes it.
  - **Last run:** the result of the last **Pack** or **Check All** of this texture set in this Blender session (not saved in the file; cleared when a file is opened), with **(checked)** when it came from Check All:
    - **fits 73 %:** the islands fit at their density and fill 73 % of the texture; **, 2048 x 2048 would do** when a smaller size would still hold them.
    - **needs x1.40: 8192 x 8192:** the islands need 1.4 times the texture's side; the size names the smallest one that holds them.
    - **does not fit even at 8192 (x2.51):** not even 8192 pixels per side would hold them.
    - **kept:** Keep UVs is on.
  - Below **Last run**, a warning when the last run found islands with triangles without UV area, or objects with faces without area (see the [Packing Report](#packing-report)).
- **Check All:** below the texture set box. Measures every texture set of the scene's view layer as **Pack** would, but writes no UVs, and fills each set's **Last run**. Use it as the overview of which texture sizes give a consistent density. While it runs, the panel shows a progress bar instead of its fields; **Cancel** or **Esc** stops after the texture set in work.

- **Advanced:** a section below the packing panel, closed at first. **Layout corner** (default **Bottom-Left**) is the corner of the texture every **Pack** moves its layout to, for the whole scene: the layout moves as one block, and its size, gaps and densities stay the same. It only makes a difference when the layout has free space. It changes UVs at the next **Pack** only, so choose it before painting. A layout that does not fit spills past the edges opposite the corner.

### Pack

**Pack** takes every face that uses the texture set's material in the view layer, also on objects that are not selected or are hidden: a texture set is one texture, so all its islands share one layout. A mesh used by several objects is packed once.

- **Density first:** every island gets its density from its range (the **Result** row above), at one common position inside the ranges for the whole set: the top of the ranges when the islands fit with space left, the highest density that still fits, or the bottom of the ranges when they do not fit.
- **When the islands do not fit,** they are still written at their density: the layout then reaches beyond the texture, from the **Layout corner**, and the result names the size it needs. Fitting it into the texture is your choice: a larger **Size** and **Pack** again, Blender's **Pack Islands** with scaling, or by hand.
- **Free space is used:** small islands go inside closed shapes (the inside of a window frame, for example) and into the gaps beside large islands, so the layout is smaller than Blender's **Pack Islands** alone gives. **Pack** makes both layouts, keeps the smaller and names in the report which one it is. An island only moves and turns here; its density stays.
- **Direction marks:** **Upright** and **Flip** islands keep their rotation; a set with a **Quarter** island turns its islands in 90-degree steps only.
- **Margin:** two islands are at least the margin apart, measured between their closest points. The report's smallest gap shows the actual value.
- **Kept unchanged:** islands without UV area (a line or a point in the UVs) keep their UVs; the report lists them.
- Works in Object Mode and Edit Mode; the selection, the mode and the active UV map stay as they were.
- Blender waits while a texture set packs (up to about a minute and a half for a set of over a thousand islands); the panel and the status bar show the step in work.

### Packing Report

**Pack** and **Check All** write the text **FSS Packing Report** (open it in a **Text Editor**). Per texture set:

- the result, the mode (fit, underflow: room even at the top of the ranges, or overflow), the position in the ranges (t, 0 to 1) and k, the layout's size against the texture's;
- the needed size, the fill of the needed size and of the current size;
- the smallest gap between islands, margin violations and overlapping triangles (both should be 0), and how far any island's density lies outside its range;
- the number of islands and which layout was kept: **placed into free space**, or **Pack Islands** with the shapes it used and the islands it packed by their bounding box (when Blender's outline of an island fails);
- islands kept unchanged, and islands not checked for density (a sliver in the UVs, or no 3D area);
- **WARNING faces without area:** objects of the set with faces that have no area. Fix them with [Find Faces Without Area](#find-faces-without-area);
- **WARNING triangles without UV area:** the number of islands of the set that contain a triangle with area on the model but none in the UVs (a needle: its corners on one line in the UVs), and their objects, the one whose island spans the most layout pixels first (so the parts that push the layout out lead the list, not small screws). Such islands land far out of the layout, so k and the needed size grow; the set is still packed. Re-unwrap those parts (for example **Accept + Unwrap**, or Blender's **Unwrap**) and pack again; [Find Faces Without UV Area](#find-faces-without-uv-area) selects them;
- after **Pack**, the objects that were included but not selected;
- the time.

**Marks multiply down the hierarchy.** An object's density range is the scene's density freedom × every density mark from the root down to the object itself, zone empties included. A door empty marked x1.5 inside a zone marked x0.8 gives everything in the door x1.2 (with the freedom: x1.08 to x1.32); a knob inside the door marked x0.75 gets x0.81 to x0.99.

To set a field on several objects at once, select them, make one of them active, and hold **Alt** while you drag or type in the field (Blender's own way to edit all selected objects).

### Visibility Scoring

A section inside **UV Auto Packing**. Measures how brightly the probe lights you include light each face over the animation steps, as the viewport shows it, as a factor from 0 to 1 (the most visible island is 1). Writes `<blend_name>.visibility` for the packer and the Heatmap's Visibility mode. See [visibility.md](visibility.md) for the settings and the workflow.

## General

In the tab **FSS Tools**. Helpers for parenting, object origins and mesh names. All work in Object Mode on the selected objects, and all can be undone.

### Add Parent

Puts one new empty above the selected objects.

- **Several objects must be siblings:** they need the same parent (the same bone, if parented to a bone), or no parent at all. Otherwise the button is greyed out and a note below it says so. This guards against selecting everything by mistake.
- The empty sits at the active object's location and rotation, with scale 1, so choose the active object to place it. If the active object is not selected, the first selected object is used. It is a small Plain Axes empty.
- The empty takes over the objects' parent (also a parent bone) and the active object's collections. The objects become its children and do not move.
- **Name:** pick the naming rule from the menu next to the button, then edit the text field:
  - **Manual:** type the full name; the default is `<active object name>_PARENT`.
  - **Suffix:** active object's name plus the suffix (default `_PARENT`).
  - **Prefix:** prefix (default `PARENT_`) plus the active object's name.
  - **@MERGE_**, **@NOMERGE_**, **@ZONE_:** the marker plus the name you type, which starts as the active object's name. For example **@MERGE_** and `PANEL` give `@MERGE_PANEL`. A marker already in the name is not doubled.

### Origin to Bounding Box

Moves the origin of each selected object to a point of its tightest bounding box, without moving the geometry or the children.

- The box is fitted to the object's own geometry (children are ignored) and can be rotated. The object's axes are turned to match the box, staying as close to the old axes as possible.
- Pick the point in the menu next to the button: **Corners** (8), **Face-Center** (6, default **Bottom (-Z)**) or **Edge-Center** (12). Names describe the local axes, for example **Front (-Y)** or **Top Back Left (-X +Y +Z)**.
- After the tool runs, Blender's transform orientation is set to **Local**, so the gizmo shows the new axes.
- A mesh shared by several objects is first made single-user for the changed object.
- Use it to bring an origin back into its geometry; far origins change the LOD switch distances (see [lod.md](lod.md#origins-outside-the-geometry)).

Pitfall: the object's rotation values change. Do not use it on an object whose own transform is animated; the animation keys would no longer match.

### Rename Meshes

Names the meshes of the selected objects and of everything below them, hidden objects too. Object names stay as they are.

- A mesh used by one object becomes `MESH_<object name>`.
- A mesh used by several objects in the file becomes `MESH_SHARED_<first object name>`, with the first name in alphabetical order (`SCREW_10` comes before `SCREW_2`). All its users count, selected or not, so the name also changes for objects outside the selection.
- `@MERGE_`, `@NOMERGE_` and `@ZONE_` are left out: a mesh on `@NOMERGE_PANEL` becomes `MESH_PANEL`.
- If a name is taken by a mesh outside the selection or is too long, Blender changes it (for example `.001` at the end), and the report warns about it. Meshes linked from another file are skipped.
- UV results kept for the session, such as visibility scores and seam counts, may need running again after a rename.

## Empty Bounds

In the tab **FSS Tools**. Draws, for each empty, a box around everything below it, and lists the parents of the active object. It only draws in the viewport: nothing is added to the scene or exported.

- **All / Selected / Off:**
  - **All:** boxes of every empty. While a non-empty object is selected, only the selection's parents: the direct parent solid (with a cross at its origin), the empties further up dashed.
  - **Selected:** boxes of the selected empties and of the empties above any selected object.
  - **Off:** no boxes.
- **In Front:** draw the boxes over the geometry (on by default), so they stay visible inside the fuselage or cockpit.
- **Hierarchy Text:** in the bottom-right corner of the viewport, the parent chain of the active object, root first (Object Mode only). Click a row to select that object; **Shift + click** adds it to or removes it from the selection.

The boxes include hidden children.

## Heatmap

In the tab **FSS Tools**. Colours the selected objects directly in the 3D viewport:

- **Distortion:** Does each face keep its shape? (Conformal singular-value ratio)
- **Density:** Does each face get the right amount of texture relative to the texture set median and object marks?
- **Visibility:** How brightly do the probe lights of Visibility Scoring light each face (from `<blend_name>.visibility`)?

Includes a distribution chart in the panel and an optional UV grid with cell labels. See [uv.md](uv.md#heatmap-distortion-texel-density-and-visibility) for how to read it.

## Checks

In the tab **FSS Tools**. Repairs for problems that break the export without an error message.

### Scan Names

The object or bone name becomes the glTF node name, and the model XML, `.cfg` files and attachments find nodes by that exact name. **Scan Names** lists every object (and, with **Bones** on, every bone) whose name breaks the FSS naming rules:

| Tag | Rule | What it finds | Proposal |
| :--- | :--- | :--- | :--- |
| `SFX` | **Suffix** | Ends in `.NNN` and the name without it is free | Remove the suffix |
| `COL` | **Collision** | Ends in `.NNN` and the name without it is taken | None: rename by hand |
| `CASE` | **Case** | Lower-case letters | Upper case (an Asobo `x0_` to `x9_` prefix stays as written) |
| `CHR` | **Characters** | Characters other than `A-Z`, `0-9` and `_` (a leading `@`, as in `@MERGE_` or `@ZONE_`, is allowed: the export strips it) | Replace with `_` |
| `DEF` | **Default** | A Blender default name such as `Cube`, `Empty`, `Plane`, `Bone` | None: rename by hand |
| `TKN` | **Taken** | The proposed name is already used | Unticked; edit the proposal or rename the other item first |
| `CLS` | **Clash** | Exports under the same name as another item once the export strips the `@` (for example `@ABCD` next to `ABCD`) | None: rename by hand |

How to use it:

1. Press **Scan Names**. When you open a `.blend`, the list is filled by itself; press the button again after you add or rename objects.
2. Use the rule buttons to show only some rules.
3. Click a row to select that object (or bone); **Frame** zooms the viewport to it.
4. Edit a proposal in its field if you want another name. Untick rows you do not want renamed; **Tick All** and **Untick All** act on the rows shown.
5. Press **Rename Selected (N)**. The list is scanned again afterwards.

The check does not read the MSFS project: it cannot know which names the XML uses. Before renaming, make sure the old name is not referenced, or update the reference. Linked (library) items are listed but cannot be renamed here. Bones of an armature in Edit Mode are skipped.

### Find Faces Without Area

A face without area (its corners on one point or one line, at most 0.000001 cm²) has no surface to texture, and re-unwrapping does not give it one. **Find Faces Without Area** checks every mesh object of the view layer and selects the visible ones with such faces, the first one active; it also selects those faces in their meshes, so **Tab** into Edit Mode shows them. The message counts the faces and objects (hidden objects are counted, not selected); the system console lists each object. Fix the geometry, for example with **Mesh > Clean Up > Degenerate Dissolve** or **Merge by Distance**, then run the check again. It works in Object Mode.

### Find Faces Without UV Area

A face whose model has area but whose UVs have none, or only part of it: one of its triangles lies on one line (or one point) in the UVs, inside an island that otherwise has area. Such a needle covers no texels, but the packer cannot pack around it: the island lands far out of the layout and the texture set needs a larger texture than its islands would (on the cockpit, these triangles turned a set that needed about 1.15 times 4096 into one that does not fit even at 8192). **Find Faces Without UV Area** checks every mesh object of the view layer with a UV map, per texture set at its **Size**, and selects the visible objects with such faces, the first one active, and those faces in their meshes, so **Tab** into Edit Mode shows them. The message counts the faces, the islands and the objects (hidden objects are counted, not selected); the system console lists each object.

- **Threshold:** a triangle counts when its UV area is at most 0.000001 pixel² of its texture set, or when it is a line (its UV area at most 0.00001 × its longest UV edge squared, the rule the packer uses for islands that are lines). Triangles without area on the model are left to **Find Faces Without Area**; islands with no UV area at all are not counted (the packer leaves them unchanged and lists them in its report).
- **Fix:** re-unwrap those parts, for example with **Accept + Unwrap** in [UV Auto Seam](#uv-auto-seam) or Blender's **Unwrap**, then run the check again and pack.
- It works in Object Mode. On the cockpit it takes about 3 seconds.

### Find Animations Not 0 to 100

Every animation of the project runs from frame 0 to 100. This is a project rule that keeps the files consistent: MSFS itself plays any range from its start to its end, so an animation outside the rule still works in the simulator. **Find Animations Not 0 to 100** checks the local objects of the view layer: the active action, each NLA strip's placement and each strip's action. Muted strips count, because they can be unmuted.

- It selects the visible objects that break the rule and reports how many, with the first ranges. Hidden ones are counted but not selected. The system console lists every range.
- It changes no animation: you correct the keys.
- It works in Object Mode.

### Fix Broken Bone Parents

When a bone-parented object gets a new parent through the parent field (instead of `Ctrl + P`), Blender keeps the old parent bone. Blender then reports "Failed to add relation Bone Parent" on every update, and the Relations panel cannot fix it. **Fix Broken Bone Parents** finds every such object in the file and resets it to normal object parenting, without moving it. It reports how many objects it fixed.
