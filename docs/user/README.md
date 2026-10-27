# FSS Blender Add-ons: Artist Guide

**Artist Guide**
***

This guide is for 3D artists who build Flight Sim Studio (FSS) aircraft in Blender 5.2. It assumes you already model, unwrap, animate, texture and export in Blender. It explains what MSFS needs on top of that, the order in which we prepare a model for it, and which of our tools help at each step and why.

It matches **FSS Blender Tools 0.34.0** and the FSS exporter based on Asobo exporter 8.4.1.

- **The pipeline** (below): the steps from a new model to a deployed one, in order.
- **The reference pages:** what each panel and button does, linked from the steps:

  | Page | Contents |
  | :--- | :--- |
  | [fss-tools.md](fss-tools.md) | The **FSS Tools** sidebar tab: **Zones & Merge Tree**, **Tags**, **UV Tools** (**Seams**, **Packing** with **Visibility Scoring**) and **Utilities** (**General**, **Empty Bounds**, **Heatmap**, **Checks**) |
  | [lod.md](lod.md) | The **FSS MSFS Tools** sidebar tab, with the **LOD** panel: automatic LODs, marks, size cut-offs, quota and hints, the LOD sphere, viewport preview, and exporting with LODs |
  | [uv.md](uv.md) | Auto Seam in **UV Tools > Seams** (proposed and current seams, workflow, reports, limits) and the **Heatmap** in **Utilities** (distortion, texel density and visibility on the model, the distribution chart, the UV grid) |
  | [exporter.md](exporter.md) | The exporter: export target MSFS 2024 or MSFS 2020, one `.blend` for both simulators, materials, instancing, legacy normals |

- **The MSFS rules behind the steps** (draw calls, LOD limits, materials, texture budgets, with their SDK sources) are in the aircraft repository's **MSFS Authoring Guide**, `doc/msfs-authoring/`. This guide links its steps to those rules by topic.

## The Pipeline

The cockpit and the exterior go through the same steps. They differ in their camera set for the visibility step, their LOD sphere, and the zones you choose. Each step says:

- **Why:** what MSFS needs, and why the step comes at this point.
- **Do:** what to do, and which tool helps.
- **Check:** how you know the step is done.
- **Redo when:** what makes the step worth doing again, and what that costs.

The order follows what each step needs from the ones before it: packing needs the texture sets (step 2) and the densities (step 7); the LOD export needs the loose pieces you modelled (step 3). It is not a fixed sequence. Everything before texturing is cheap to change, and you will go back and forth: a new part, a moved zone or a changed mark means running the later steps again. Texturing is where changes start to cost: once a texture set is painted, changing its UVs, zone or material means baking again and carrying the painting over. Settle what feeds a texture set before you paint it.

Steps marked **in development** describe what the tool will do, and how to get the same result by hand until it exists.

| Step | Tools | Tool status | MSFS Authoring Guide |
| :--- | :--- | :--- | :--- |
| [1. Scene, Hierarchy and Names](#1-scene-hierarchy-and-names) | Tools, Empty Bounds, Checks | available | `modeling.md` |
| [2. Zones and Materials](#2-zones-and-materials-in-development) | Zones & Merge Tree, zone tool | zone density marks available; the rest by hand | `materials.md`, `texturing.md` |
| [3. Loose Pieces](#3-loose-pieces-what-disappears-together) | LOD hints, Viewport LOD | a modelling decision | `lods.md` |
| [4. Merge Tree](#4-merge-tree) | Tags, Zones & Merge Tree | available | `modeling.md` |
| [5. LOD](#5-lod) | LOD | available | `lods.md` |
| [6. Seams and Unwrap](#6-seams-and-unwrap) | UV Tools > Seams, Utilities > Heatmap | available | `uv-mapping.md` |
| [7. Visibility Scoring](#7-visibility-scoring) | UV Tools > Packing > Visibility Scoring | available | [visibility.md](visibility.md) |
| [8. Packing](#8-packing) | UV Tools > Packing | available | `uv-mapping.md` |
| [9. Texturing](#9-texturing) | Substance Painter | outside Blender | `texturing.md`, `baking.md` |
| [10. Export and Deploy](#10-export-and-deploy) | exporter, deploy scripts | available | `blender-export.md` |

### 1. Scene, Hierarchy and Names

**Why:** every object becomes a glTF node with the object's name, and the model XML, `.cfg` files and attachments find nodes by that exact name. Object origins become node positions, and every origin counts for the LOD sphere (step 5), so they must lie inside their geometry. Getting names, hierarchy and origins right first avoids renaming referenced nodes later.

**Do:**

- The scene name is the `.blend` file name (for example `COCKPIT`); it is used in the root's name (below) and in the material names (step 2).
- Give the model one root empty, `EMPTY_ROOT_<SCENE>` (for example `EMPTY_ROOT_COCKPIT`, `EMPTY_ROOT_CABIN`, `EMPTY_ROOT_WING`), with the zones (step 2) and parts below it. The root is the anchor of the scene:
  - **Its position relative to the aircraft datum** (the world origin) places the scene in the aircraft. Everything below it moves with it: a longer variant's cockpit is the same cockpit with its root moved forward.
  - **Place it at the centre of the LOD sphere**, inside the scene, never on the datum. MSFS measures how large the model is on screen from that centre, so a camera there always sees `_LOD00`. MSFS works out the centre itself, from the geometry and every origin; the root does not set it, but a root far outside the geometry would move and enlarge the sphere (the root is exported, and its origin counts like every other). Compare it with **Show LOD Sphere** (step 5).
  - To move the root without moving what is below it, turn on **Options > Transform > Affect Only: Parents** in the 3D Viewport header, move it, and turn the option off again.
- Use **Add Empty Parent** to group parts without moving them, and **Origin to Bounding Box** to bring origins back into their geometry (not on objects whose own transform is animated). See [General](fss-tools.md#general) in **Utilities**.
- Run **Scan Names** and **Fix Broken Bone Parents** in [Checks](fss-tools.md#checks) (**Utilities**).
- **Empty Bounds** shows what each empty contains; use it to check the hierarchy. See [Empty Bounds](fss-tools.md#empty-bounds).

**Check:** Scan Names lists nothing you did not intend. For the origins, press **Refresh LOD Counts** in the [LOD](lod.md) panel (sidebar tab **FSS MSFS Tools**; no LOD marks are needed for it; for an interior, first enter **Exterior Diameter** under **Export Settings**, or Refresh stops with "exterior diameter missing"): its **Export Settings** show no warning about origins outside the geometry, and **Show LOD Sphere** draws the sphere around the model, not far beyond it. See [Origins Outside the Geometry](lod.md#origins-outside-the-geometry).

**Redo when:** you add or rename parts. Renaming a node that the model XML, a `.cfg` or an attachment refers to also means updating that reference.

### 2. Zones and Materials (in development)

**Why:** a **zone** is a part of the scene that is seen together, for example the forward cockpit (main panel, glareshield, pedestal) and the rear cockpit (behind the seats, the aft ceiling), or the front and rear cabin. Zones are your choice; they depend on the scene. Each zone has its own materials and texture sets, for three reasons:

- **Video memory:** a texture stays loaded as long as any part of it may be on screen. If forward and rear parts share a texture, the rear half stays in memory while the pilot looks forward, although it is never seen. Separate zones keep what is out of view from holding memory for what is in view. See "When Separate Textures Are Better" in `texturing.md` of the MSFS Authoring Guide.
- **Texel density:** each zone empty can carry its own density mark, set in [Zones & Merge Tree](fss-tools.md#zones--merge-tree), so the packer can give the rarely seen rear zone less texture and the forward zone more (step 7).
- **Culling:** MSFS leaves out what is out of view by each node's bounding box. An object with parts both at the windshield and at the rear has a box across the whole cockpit, and is never left out. Zones make such objects easy to find: select a zone's empty, and [Empty Bounds](fss-tools.md#empty-bounds) shows its box reaching into the other zone. They also keep merge groups apart (step 4).

Within a zone, each kind of surface (standard, emissive, decal, glass and so on) gets its own material, and so its own texture set, and no material is used in two zones. Packing (step 8) packs one texture set at a time, so it follows the zones and materials.

Zones are empties named `@ZONE_<NAME>` below the root, every part below one zone:

![EMPTY_ROOT_COCKPIT contains the zones @ZONE_FWD and @ZONE_AFT. @ZONE_FWD uses the materials COCKPIT_FWD_STD and so on, and holds the merge group @MERGE_MAIN_PANEL: the panel shell and screws merge into one mesh, while the animated SWITCH_APU and the tagged MFD_SCREEN stay their own nodes. @ZONE_AFT uses COCKPIT_AFT_STD and so on.](images/scene-hierarchy.svg)

Name the materials as you like; a name that says the zone and the kind of surface, such as `COCKPIT_FWD_STD` in the picture, makes the material list easy to read. The texture size is set per material in [Packing](fss-tools.md#packing) (default 4096 × 4096).

**Do:**

- Create the zone empties now, named `@ZONE_<NAME>` below the root, and put every part below one of them. The export drops the leading `@`: `@ZONE_FWD` becomes the node `ZONE_FWD`.
- Press **Refresh** in [Zones & Merge Tree](fss-tools.md#zones--merge-tree) to see the zones, and give a zone a **density mark** there where it needs one (no mark keeps the density; for example 0.5 for a rarely seen zone). Marks multiply down the hierarchy, so everything below the zone takes it.
- Give each zone its own materials, one per kind of surface, and set each material's MSFS type. Auto Seam skips objects whose materials are all decal, glass, windshield, invisible or occluder (see [What Is Skipped](uv.md#what-is-skipped)).
- Keep the number of materials low: see `materials.md` in the MSFS Authoring Guide.

**Check:** no material is used in two zones; no `Material.001` copies are left.

**Redo when:** a zone turns out too full or nearly empty for its texture. Each change here changes a texture set, so packing follows, and repainting if the set was already textured.

### 3. Loose Pieces: What Disappears Together

**Why:** a LOD deploy exports your `.blend` once for each LOD file, every time from the full model: first it removes what is too small to see at that LOD, then it merges (step 4) and exports. Lower LODs have fewer vertices only because things are removed; nothing is simplified.

![For each LOD file, the deploy reloads the full model from the saved .blend, removes parts by marks and size, removes small loose pieces, merges each merge group and writes COCKPIT_LODnn.gltf; it stops at the first empty LOD, and the .blend is never changed.](images/lod-export-flow.svg)

Two kinds of things are removed by their size:

- **parts:** an object with everything below it, sized by the box around all of it;
- **loose pieces:** connected geometry inside one mesh. Geometry that shares no vertices with the rest is its own loose piece, however you combined it: in one object, joined with `Ctrl+J`, or in a merge group. Each loose piece is sized and removed on its own.

So the topology you model decides what disappears together. A floor plate and its screws should come apart: each screw can disappear on its own. But a screw whose head and body are not connected is two loose pieces: the head disappears first, then the body, which looks wrong. See [How the Automatic LODs Work](lod.md#how-the-automatic-lods-work).

**Do:**

- **Connect** what must disappear together: join the head and body of the screw with a few edges or faces, so they become one loose piece.
- **Separate** what should be able to disappear on its own: split it into its own loose piece, or its own object, so the size rule can remove it while the rest stays.
- This is a modelling decision about what belongs together; no tool decides it for you. The LOD panel's hints (step 5) show which loose pieces would be dropped at each LOD.

**Check:** with the viewport LOD preview (step 5), small assemblies disappear as a whole, not piece by piece.

**Redo when:** the LOD preview shows small assemblies disappearing piece by piece.

### 4. Merge Tree

**Why:** every mesh costs at least one draw call, one per material it uses (see `how-msfs-renders.md` in the MSFS Authoring Guide), so a cockpit of thousands of small static objects costs thousands. The usual answer in Blender is to join them, but a joined mesh is flattened: you can no longer select, move, mark or unwrap one part on its own. A merge group defers the join to the export: in the `.blend` every part stays its own object, and the export joins the group into one mesh, separately for each LOD (a panel with its screws in `_LOD00`, without them where they are too small).

**Do:** decide what to merge as you would decide what to join by hand, aiming for as few draw calls as the model allows. The rules are in `modeling.md` ("When to Merge") of the MSFS Authoring Guide; in short:

- Merge what is static and drawn together: parts that never move on their own, that nothing refers to by name, that are seen together and share materials. Merging parts with different materials saves nodes, not draw calls.
- Keep separate what has a life of its own: a switch, a lever or a door with its handle must move on its own, which it cannot do as part of the panel's mesh. The merge keeps animated, skinned and bone-parented objects, meshes with shape keys, lights and cameras separate by itself. See [What Stays Separate](fss-tools.md#what-stays-separate).
- The merge cannot see the model XML: a gauge screen or a clickspot that is not animated would be merged away. Give it a [tag](fss-tools.md#tags) with **Don't Merge** (for example `SCREEN`), or name it `@NOMERGE_<name>`.
- Transparent surfaces sort by their mesh. MSFS draws glass, windshields and decals after the opaque surfaces, back to front, sorted by the centre of each mesh's bounding box, not by triangle (see `how-msfs-renders.md` in the MSFS Authoring Guide). A merge group puts all its transparent parts into one mesh, `<name>_TRANSPARENT`, with one centre:
  - two glasses that overlap on screen (gauge glass in front of a display glass) can no longer be sorted against each other and may flicker: give one of them a tag with **Don't Merge**;
  - decals spread over surfaces at different depths are drawn as one mesh after all of them: a label of the rear surface can then show on the front surface at some view angles. Merge decals of one surface, or of surfaces at the same depth; keep a decal on a surface far behind others out of the group.
  - **Draw Order** (decal, glass and windshield materials) sorts separate meshes; it cannot sort parts inside one merged mesh.
- Keep each merge group inside one zone (step 2): a group that spans two zones becomes one mesh across both, so MSFS cannot leave one zone out of view without the other, and the mesh carries both zones' materials. The Zones & Merge Tree lists groups outside every zone under **Unzoned**, and warns on a zone inside a merge group.
- Put `@MERGE_<name>` on the empty above a set of parts that may become one mesh. A group can be large, a whole panel with everything on it: what must stay separate inside it stays separate by itself or by its tag, so you rarely need many small groups.
- Use **Refresh** in [Zones & Merge Tree](fss-tools.md#zones--merge-tree) to see the zones and groups, their materials, and why objects were kept separate.

**Check:** the Zones & Merge Tree shows the groups you expect, each inside one zone, and no **Unzoned** row; every referenced node is kept separate, and the multiple-materials warnings are intended.

**Redo when:** you add parts, or the model XML starts referring to a node that is merged away. Merging happens only at export, so it never touches UVs or textures.

### 5. LOD

**Why:** MSFS shows one whole LOD file at a time, chosen by how large the model's LOD sphere is on screen, and skips a LOD that has too many vertices for that size. The export builds the LOD files from your full model by removing parts and loose pieces by size and by marks. The rules are in `lods.md` of the MSFS Authoring Guide.

**Do:** in the **FSS MSFS Tools** tab > **LOD**:

- **LOD sphere:** check it with **Show LOD Sphere**; set **LOD Sphere Diameter** to the size you want MSFS to measure, so the LODs switch at the distances you intend. See [The LOD Sphere](lod.md#the-lod-sphere).
- **Marks:** **Keep** for small parts that must stay visible (annunciators, lights), **Hidden from** for parts not needed at lower detail, **Visible from** for simpler replacements. See [Marks](lod.md#marks).
- **Refresh LOD Counts**, then work through **Quota and Hints** until every LOD fits. See [Quota and Hints](lod.md#quota-and-hints).
- **Viewport LOD** previews what each LOD keeps; **Auto** follows the view distance. See [Viewport LOD](lod.md#viewport-lod).

**Check:** no LOD shows a vertex warning after **Refresh LOD Counts**; the preview looks right at each level. Set the preview to **Off** before exporting by hand.

**Redo when:** geometry, marks or the LOD sphere change: press **Refresh LOD Counts**. LODs are built at export from the full model, so this never touches UVs or textures.

### 6. Seams and Unwrap

**Why:** MSFS stores UVs with limited precision, and at most two UV maps per mesh reach the export. Seams decide where the texture splits; badly placed seams show in front of the pilot. The rules are in `uv-mapping.md` of the MSFS Authoring Guide.

**Do:**

- Mark the seams that matter to you by hand: panel joints, visible cuts, symmetry edges.
- **Auto Seam** (**UV Tools > Seams**) proposes seams for hard-surface parts around yours. Review them, **Accept Proposed** or **Discard Proposed**. Objects such as fur, cables or decal soups get the **Skip Auto Seam** mark in the same section. See [uv.md](uv.md).
- Unwrap with Blender's **Unwrap** (Angle Based). Apply the object's scale first where you can: Blender unwraps in object space.
- Check with the **Heatmap** in **Distortion** mode and the **UV Grid**: cells should stay square, labels upright. See [Heatmap](uv.md#heatmap-distortion-texel-density-and-visibility).

**Check:** the heatmap's chart shows most of the surface near 1.0, with little above 1.25; nothing shows in magenta (Error).

**Redo when:** the heatmap shows stretched islands, or a part changes shape. A new unwrap changes the islands, so packing follows; on a textured set it costs rework.

### 7. Visibility Scoring

**Why:** texture space is limited. Parts the pilot sees deserve more texture than parts hidden behind other parts or behind the seat.

**What it measures:** from the cameras you include (for the cockpit the pilot and copilot eyes; for the exterior your own exterior cameras) and over the animation steps, how much of each face is actually visible, weighted by how far the head has to turn from the camera's default view. The score is a factor from 0 to 1 per face that depends neither on distance nor on size: a small knob in plain view scores as high as a large panel. Parts too small to measure (screw heads, small labels) take the value of the part they belong to.

**How packing uses it:** each island gets a texel density (pixels per centimetre) within the target density × its object's density range × the island's visibility. The density range is the scene's density freedom times every density mark from the root down to the object, zone marks included, all set in [Packing](fss-tools.md#packing). An island's visibility comes from its seen faces only, so a partly hidden island keeps the density its visible part needs. No island gets less than a small minimum (x0.10), whether it is seen a little or never seen in the analysed views and steps; nothing is deleted.

**Do:**

- In **FSS Tools** > **UV Tools** > **Packing** > **Visibility Scoring**, tick **Include** for your cameras and set each to **Look Around** (the head can turn) or **Fixed View** (only what the camera's own frame shows).
- Set **Animation Steps** (default 5: 0, 25, 50, 75 and 100 % of each animation).
- Save the `.blend`, then **Update Visibility**. The results go to `<blend name>.visibility` beside the `.blend`. See [visibility.md](visibility.md).

**Check:**

- The [Heatmap](uv.md#heatmap-distortion-texel-density-and-visibility) in **Visibility** mode: what the pilot looks at is blue, what is hidden or far to the side is red, never seen is magenta.
- **Select Never Seen** and judge the list: switch positions and parts shown only under some conditions are not seen in every analysed step. Hide or delete only what really is never visible.

**Redo when:** cameras, animations or the geometry change; the panel lists stale meshes. New seams or a new unwrap do not count: the scores belong to faces, not islands.

### 8. Packing

**Why:** each texture set (step 2) is one texture. All islands that use it must fit into it, at the texel density each part should get (step 7), with enough space between islands that they do not bleed into each other at lower mip levels.

![Seams, from Auto Seam or by hand, and the unwrap produce the UV islands; each island's visibility comes from the scores of its seen faces. The scene's density freedom times the density marks from the root down to the object (zone marks included) times the island visibility gives a density ratio range without unit; that ratio times the target density gives the island's density range in pixels per centimetre. The zone also decides the texture set: the packer packs one texture set per zone and class, each island inside its range.](images/zone-visibility-packing.svg)

**What the tool does:** **Pack** packs one texture set: every face with its material in the scene, selected or not. It scales each island to its density range (target density × the density marks × the island's visibility), at one common position inside the ranges for the whole set, turns islands only as their **direction** mark allows, and keeps each material's **margin** in pixels. When the islands do not fit the texture **size**, it still writes them at their density, reaching beyond the texture, and says which size they need; when they leave space even at the top of their ranges, it says which smaller size would do. **Check All** does the same for every texture set without writing UVs. See [Packing](fss-tools.md#packing).

**Do:** in **FSS Tools** > **UV Tools** > **Packing** (the same section is in the UV Editor's sidebar, tab **FSS Tools**):

1. Set **Target density** and the density marks (step 7 explains them). Select the objects; the list shows their texture sets. Click a row and set that set's **Size** (square: 256 to 8192 pixels per side) and **Margin**.
2. Tick **Keep UVs** on texture sets that must not be packed: fur and hair cards, decal sheets, colliders.
3. Before packing, run [Find Faces Without UV Area](fss-tools.md#find-faces-without-uv-area) (**Utilities** > **Checks**) and re-unwrap the parts it selects (for example **Accept + Unwrap**): their islands would land far out of the layout and make the set need a larger texture.
4. **Check All**, then read each set's **Last run** and the **FSS Packing Report**. If a set's report warns about **triangles without UV area**, re-unwrap the objects it names and check again. Change sizes or marks until each set fits at a size you accept.
5. Click the set's row and press **Pack**. **Ctrl + Z** undoes it.
6. If the report warns about **faces without area**, run [Find Faces Without Area](fss-tools.md#find-faces-without-area) and fix them.

**Check:**

- The set's **Last run** says **fits**, and the report shows 0 margin violations and 0 overlapping triangles.
- The heatmap's **Density** mode shows each texture set near 1.0, except where you chose otherwise.
- In the UV editor, no island lies outside the texture. Islands without UV area (lines, points) keep their old place; the report lists their objects.

**Redo when:** zones, materials, sizes, density marks or visibility scores change. It's quick to repeat until texturing has started; after that, moving islands means baking again.

### 9. Texturing

**Why:** texture memory is the budget that matters most for frame rate. The texture sizes, atlas rules and memory budget are in `texturing.md` of the MSFS Authoring Guide. Baked ambient occlusion and sky light go into the texture set's occlusion channel; see `baking.md`.

**Do:** texture each texture set in Substance Painter from the packed UVs. Use material values (colour, metallic, roughness) instead of a texture where a flat value is enough.

**Texture imbalance:** every map of a texture set covers the whole set and costs the same memory, whatever it shows. If only a few parts of a material emit light, its emissive map is mostly black, yet it takes as much memory as the albedo and ORM maps, which are full. Give the emitting parts their own material (and texture set) when they cover only a small part of the set; the rest then needs no emissive map. The same holds for any map only a few parts need.

For tiling patterns (brushed metal, fabric, grip), use tri-planar projection instead of UV projection: islands are packed at different densities, and a UV-projected pattern would change size from island to island.

Bake ambient occlusion once the texture set's packing is final: a bake follows the UVs. Move moving parts away from their panels before baking, so no shadow is baked under a button that moves, and leave clickspots, collision meshes and decals out of the bake.

Instanced parts (screws, identical knobs) share their texture and get generic AO in it; unique AO per copy needs a second UV map and gives up the instancing. See "AO Versus Instancing" in `baking.md`.

**Redo when:** the UVs of a textured set change: bakes are redone and the painting carried over. This step is why changes to the earlier steps get expensive.

### 10. Export and Deploy

**Why:** the deploy exports the `.blend` in the background with the FSS exporter, merges the merge groups, and writes the LOD files.

**Do:**

- Set the export target (MSFS 2024 or MSFS 2020) in the exporter's **Export Target** panel. See [exporter.md](exporter.md).
- Deploy with your aircraft repository's scripts: the LOD deploy for models with LODs, the single-file deploy otherwise. See [Exporting with LODs](lod.md#exporting-with-lods).
- After a deploy, check the console: the LOD lines, merge warnings, and vertex warnings.

**Check:** the model loads in the simulator, LODs switch where intended, and every referenced node is found.

**Redo when:** after every change you want to see in the simulator. The deploy exports the saved `.blend`, so save first.

## Alongside the Pipeline

Some work has no step of its own, because it runs through several:

- **Animation** (`animation.md` in the MSFS Authoring Guide): an animated part stays its own node through the merge (step 4), and its origin is its pivot, so do not move it with Origin to Bounding Box (step 1). The visibility analysis (step 7) will look at each animation at several points of its own length (0, 50 and 100 % by default): animate before scoring visibility, or score again afterwards.
- **Clickspots and collision** (`clickspots-and-collision.md`): meshes with an invisible material. MSFS recognises them by the material type and never draws them, so their seams and UVs have no effect: Auto Seam skips them to save time, and they need no packing, but unwrapping them does no harm. Give them an invisible material of their own, the `INVIS` class (step 2), never a zone's visible material. Keep the ones the model XML refers to by name separate with a **Don't Merge** tag or `@NOMERGE_` (step 4).

## Where to Find the Tools

- **FSS Tools and FSS MSFS Tools:** in the 3D Viewport, press `N` to open the sidebar. FSS Blender Tools has two tabs there:
  - **FSS Tools**, the tools that work on any model. The panels are, from top to bottom: **Zones & Merge Tree**, **Tags**, **UV Tools** (sections **Seams** and **Packing**, with **Visibility Scoring** inside Packing) and **Utilities** (sections **General**, **Empty Bounds**, **Heatmap** and **Checks**).
  - **FSS MSFS Tools**, the tools that follow MSFS rules: the **LOD** panel.
- **Exporter:** in the same sidebar, tab **Microsoft Flight Simulator 2024 Tools**, panel **Export Target** (also shown in **File > Export > glTF 2.0**, section **Microsoft Flight Simulator (FSS)**).
- **Material and object settings:** in the Properties editor, the MSFS panels of the Asobo add-on, plus **MSFS 2020 Object Parameters** and **MSFS 2020 Material Parameters** while the scene targets MSFS 2020.

## Installed Add-ons

The portable Blender in `tools/blender` of the aircraft repository enables these add-ons at every start:

| Add-on | Name in Blender | Role |
| :--- | :--- | :--- |
| `fss_blender_tools` | FSS Blender Tools | The **FSS Tools** and **FSS MSFS Tools** sidebar tabs |
| `io_scene_gltf2_msfs_fss` | Microsoft Flight Simulator 2020 + 2024: glTF Extension (FSS) | glTF export for MSFS 2024 and MSFS 2020 from one `.blend`; replaces the separate MSFS 2024 and MSFS 2020 exporters |
| `lod_tools_msfs_2024` | LOD Tools | Asobo LOD utilities; its panel is hidden by default (see [exporter.md](exporter.md#asobo-export-workflow-hidden)) |
| `wipermask_generator_msfs_2024` | Wiper Mask Generator | Asobo windshield wiper mask generator |
| `_addons_common` | (shared code) | Required by the Asobo add-ons; not an add-on itself |

Do not enable the original `io_scene_gltf2_msfs_2024` or `io_scene_gltf2_msfs_2020` add-ons next to the FSS exporter.

## Which Version Do I Have?

- **In the aircraft repository:** open `tools/blender/FSS-ADDONS-VERSION.txt`. It names the add-on commit and the **FSS Blender Tools** version.
- **In Blender:** **Edit > Preferences > Add-ons**, search for "FSS Blender Tools"; the version is shown in the add-on details.

If your version is newer than 0.24.1, some labels or buttons may differ from this guide.

## Terms Used in This Guide

| Term | Meaning |
| :--- | :--- |
| **Deploy** | Exporting a `.blend` to glTF with the aircraft repository's scripts and copying the files into the simulator package. The deploy runs Blender in the background. |
| **LOD** | Level of detail. `_LOD00` is the full model; `_LOD01` to `_LOD06` are lighter versions MSFS shows when the model is small on screen. |
| **Loose piece** | A connected piece of geometry inside one mesh. Pieces that only touch without sharing vertices count as separate. |
| **Mark** | Something you put on an object to tell an automatic tool what it cannot work out itself: an override or a hint. Marks live in the `.blend`; MSFS never sees them. Three kinds: **LOD marks** in the [LOD](lod.md#marks) panel (from which LOD a part is left out or shown, or **Keep**); **UV marks** in **UV Tools** ([Packing](fss-tools.md#packing): the density factor, multiplied down the hierarchy, and how islands may turn; [Seams](fss-tools.md#seams): **Skip Auto Seam**), which reach the objects below; and **tags**. |
| **Material class** | The kind of material (standard, emissive, decal, glass and so on), the last part of a material name `<SCENE>_<ZONE>_<CLASS>`. |
| **Merge group** | An object named `@MERGE_<name>` whose subtree becomes one mesh at export. |
| **Name prefix** | `@MERGE_`, `@NOMERGE_` (see [Zones & Merge Tree](fss-tools.md#zones--merge-tree)) and `@ZONE_` (step 2): a prefix in an object's name that the tools act on. The export removes `@MERGE_` and `@NOMERGE_` entirely, and the leading `@` of any other name: `@ZONE_FWD` becomes `ZONE_FWD`. |
| **Origin** | The object's own point (orange dot in Blender). In the glTF it becomes the node position. |
| **Part** | An object together with all objects below it in the hierarchy. |
| **Root** | The empty `EMPTY_ROOT_<SCENE>` at the top of a scene's hierarchy: the anchor that places the scene relative to the aircraft datum. |
| **Tag** | A mark you define yourself: a label that classifies objects, for example `SCREEN`. You select objects by tag, and a tag's **Don't Merge** and **Keep** settings apply to every object that carries it. |
| **Texture set** | The textures of one material, shared by every object that uses it; one zone and class. |
| **Zone** | A part of the model with its own materials and texture sets, chosen by you for the scene. |
