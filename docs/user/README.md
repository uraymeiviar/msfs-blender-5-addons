# FSS Blender Add-ons: Artist Guide

**Artist Guide**
***

This guide is for 3D artists who build Flight Sim Studio (FSS) aircraft in Blender 5.2. It assumes you already model, unwrap, animate, texture and export in Blender. It explains what MSFS needs on top of that, the order in which we prepare a model for it, and which of our tools help at each step and why.

It matches **FSS Blender Tools 0.24.1** and the FSS exporter based on Asobo exporter 8.4.1.

- **The pipeline** (below): the steps from a new model to a deployed one, in order.
- **The reference pages:** what each panel and button does, linked from the steps:

  | Page | Contents |
  | :--- | :--- |
  | [fss-tools.md](fss-tools.md) | The **FSS Tools** sidebar tab: **Tools**, **Empty Bounds**, **Tags**, **Merge Tree**, **UV Marks**, **Auto Seam**, **UV Heatmap**, **Checks** |
  | [lod.md](lod.md) | The **LOD** panel: automatic LODs, marks, size cut-offs, quota and hints, the LOD sphere, viewport preview, and exporting with LODs |
  | [uv.md](uv.md) | The **Auto Seam** panel (proposed and current seams, workflow, reports, limits) and the **UV Heatmap** panel (distortion and texel density on the model, the distribution chart, the UV grid) |
  | [exporter.md](exporter.md) | The exporter: export target MSFS 2024 or MSFS 2020, one `.blend` for both simulators, materials, instancing, legacy normals |

- **The MSFS rules behind the steps** (draw calls, LOD limits, materials, texture budgets, with their SDK sources) are in the aircraft repository's **MSFS Authoring Guide**, `doc/msfs-authoring/`. This guide links its steps to those rules by topic.

## The Pipeline

The cockpit and the exterior go through the same steps. They differ in their camera set for the visibility step, their LOD sphere, and the zones you choose. Each step says:

- **Why:** what MSFS needs, and why the step comes at this point.
- **Do:** what to do, and which tool helps.
- **Check:** how you know the step is done.

Steps marked **in development** describe what the tool will do, and how to get the same result by hand until it exists.

### 1. Scene, Hierarchy and Names

**Why:** every object becomes a glTF node with the object's name, and the model XML, `.cfg` files and attachments find nodes by that exact name. Object origins become node positions, and every origin counts for the LOD sphere (step 5), so they must lie inside their geometry. Getting names, hierarchy and origins right first avoids renaming referenced nodes later.

**Do:**

- The scene name is the `.blend` file name (for example `COCKPIT`); it is used in the material names (step 2).
- Give the model one root empty, with the zones (step 2) and parts below it.
- Use **Add Empty Parent** to group parts without moving them, and **Origin to Bounding Box** to bring origins back into their geometry (not on objects whose own transform is animated). See [Tools](fss-tools.md#tools).
- Run **Scan Names** and **Fix Broken Bone Parents** in [Checks](fss-tools.md#checks).
- **Empty Bounds** shows what each empty contains; use it to check the hierarchy. See [Empty Bounds](fss-tools.md#empty-bounds).

**Check:** Scan Names lists nothing you did not intend; the LOD panel's **Export Settings** show no warning about origins outside the geometry (see [lod.md](lod.md#origins-outside-the-geometry)).

### 2. Zones and Materials (in development)

**Why:** every material an object uses is one draw call, and every material has its own texture set. A **zone** is a part of the model with its own materials and texture sets, for example the overhead panel, the pedestal or the cabin rear. Zones are your choice; they depend on the scene. Within a zone there is one material, and one texture set, per **material class** (standard, emissive, decal, glass and so on). Packing (step 8) packs one texture set at a time, so zones and materials must be decided before UVs are packed.

**What the tool will do:** zones as empties named `@ZONE_<NAME>` below the root; materials named `<SCENE>_<ZONE>_<CLASS>`, for example `COCKPIT_OVHD_STD` or `COCKPIT_OVHD_DECAL`; the texture size taken from the zone's material (4K if none is set). Classes follow the MSFS material types: `STD`, `STD_EM`, `DECAL`, `DECAL_EM`, `DECAL_FROST`, `DECAL_BLEND`, `GLASS`, `WNDSHIELD`, `INVIS`, `OCCLUDER`, `SCREEN`, `ANISO`, `CLEARCOAT`, `PORTHOLE`, `PARALLAX`, `FRESNEL`, `PROPELLER`.

**Meanwhile, by hand:**

- Group each zone's parts under one empty with an ordinary name (the `@ZONE_` marker is not supported by the exporter yet).
- Name the materials `<SCENE>_<ZONE>_<CLASS>`, one per zone and class, and set each material's MSFS type to match its class. Auto Seam already skips objects whose materials are all decal, glass, windshield, invisible or occluder, by these class names or by the MSFS type.
- Keep the number of materials low: see `materials.md` in the MSFS Authoring Guide.

**Check:** every material name follows the pattern; no `Material.001` copies are left.

### 3. Units: What Is One Piece

**Why:** the LOD export removes whole **parts** (objects with their children) and, inside a mesh, **loose pieces** (connected geometry) when they are too small to see at a LOD. So the topology you model decides what disappears together. A floor plate and its screws are different units: each screw should be able to disappear on its own. But a screw whose head and body are not connected is two loose pieces: the head disappears first, then the body, which looks wrong. See [How the Automatic LODs Work](lod.md#how-the-automatic-lods-work).

**Do:**

- **Connect** what must disappear together: join the head and body of the screw with a few edges or faces, so they become one loose piece.
- **Separate** what should be able to disappear on its own: split it into its own loose piece, or its own object, so the size rule can remove it while the rest stays.
- This is a modelling decision about units and assemblies; no tool decides it for you. The LOD panel's hints (step 5) show which loose pieces would be dropped at each LOD.

**Check:** with the viewport LOD preview (step 5), small assemblies disappear as a whole, not piece by piece.

### 4. Merge Tree

**Why:** many small objects mean many draw calls. A merge group joins a subtree into one mesh at export, while every part stays a separate, editable object in the `.blend`. Merging happens after the LOD step, per LOD: a panel is merged with its screws in `_LOD00` and without them where they are too small.

**Do:**

- Put `@MERGE_<name>` on a high level of the hierarchy, for example the floor or the overhead panel, not on single small parts. Everything below it merges, except what must stay separate.
- What stays separate on its own: animated, skinned and bone-parented objects, meshes with shape keys, lights and cameras. See [What Stays Separate](fss-tools.md#what-stays-separate).
- What you must keep separate yourself: anything the model XML refers to that is not animated, such as gauge screens and clickspots. Use a [tag](fss-tools.md#tags) with **Don't Merge** (for example `SCREEN`) on those objects, or name them `@NOMERGE_<name>`.
- Use **Refresh** in [Merge Tree](fss-tools.md#merge-tree) to see the groups, their materials, and why objects were kept separate.

**Check:** the Merge Tree shows the groups you expect, every referenced node is kept separate, and the multiple-materials warnings are intended.

### 5. LOD

**Why:** MSFS shows one whole LOD file at a time, chosen by how large the model's LOD sphere is on screen, and skips a LOD that has too many vertices for that size. The export builds the LOD files from your full model by removing parts and loose pieces by size and by marks. The rules are in `lods.md` of the MSFS Authoring Guide.

**Do:**

- **LOD sphere:** check it with **Show LOD Sphere**; set **LOD Sphere Diameter** to the size you want MSFS to measure, so the LODs switch at the distances you intend. See [The LOD Sphere](lod.md#the-lod-sphere).
- **Marks:** **Keep** for small parts that must stay visible (annunciators, lights), **Hidden from** for parts not needed at lower detail, **Visible from** for simpler replacements. See [Marks](lod.md#marks).
- **Refresh LOD Counts**, then work through **Quota and Hints** until every LOD fits. See [Quota and Hints](lod.md#quota-and-hints).
- **Viewport LOD** previews what each LOD keeps; **Auto** follows the view distance. See [Viewport LOD](lod.md#viewport-lod).

**Check:** no LOD shows a vertex warning after **Refresh LOD Counts**; the preview looks right at each level. Set the preview to **Off** before exporting by hand.

### 6. Seams and Unwrap

**Why:** MSFS stores UVs with limited precision, and at most two UV maps per mesh reach the export. Seams decide where the texture splits; badly placed seams show in front of the pilot. The rules are in `uv-mapping.md` of the MSFS Authoring Guide.

**Do:**

- Mark the seams that matter to you by hand: panel joints, visible cuts, symmetry edges.
- **Auto Seam** proposes seams for hard-surface parts around yours. Review them, **Accept Proposed** or **Discard Proposed**. Objects such as fur, cables or decal soups get the **Skip Auto Seam** mark in [UV Marks](fss-tools.md#uv-marks). See [uv.md](uv.md).
- Unwrap with Blender's **Unwrap** (Angle Based). Apply the object's scale first where you can: Blender unwraps in object space.
- Check with the **UV Heatmap** in **Distortion** mode and the **UV Grid**: cells should stay square, labels upright. See [UV Heatmap](uv.md#uv-heatmap-distortion-and-texel-density).

**Check:** the heatmap's chart shows most of the surface near 1.0, with little above 1.25; nothing shows in magenta (Error).

### 7. Visibility Scoring (in development)

**Why:** texture space is limited. Parts the pilot sees up close deserve more texture than parts behind the seat or hidden behind other parts. The tool will measure, from the cockpit camera set (pilot and copilot eyes, quickviews) or the exterior camera set, how many screen pixels each face can get, over the animation states, and turn that into a texel density per part. Faces never seen are reported as candidates for removal.

**Meanwhile, by hand:** set the texel density marks in [UV Marks](fss-tools.md#uv-marks) from your own judgement of what the pilot sees: **Higher** (1.5 to 1.65) for prominent parts such as the glareshield and main panel, **Lower** (0.7 to 0.8) for parts that are hardly seen, the default 0.9 to 1.1 for the rest. Marks on an empty apply to everything below it.

**Check:** the marks match what you see from the pilot camera.

### 8. Packing (in development)

**Why:** each texture set (step 2) is one texture. All islands that use it must fit into it, at the texel density each part should get (step 7), with enough space between islands that they do not bleed into each other at lower mip levels.

**What the tool will do:** pack each texture set from its materials and zones, scale each island to its density range, turn islands only as their **direction** mark allows, keep mirrored or shared parts stacked, and use each material's **margin**.

**Meanwhile, by hand:** for each texture set, select the objects that use its material, then in the UV editor:

1. **Average Islands Scale**, then scale up the islands of parts marked **Higher** and down those marked **Lower**.
2. **Pack Islands** with the material's margin from [UV Marks](fss-tools.md#uv-marks), and rotation off for parts marked **Upright** (brushed metal, grain, text).

**Check:** the heatmap's **Density** mode shows each texture set near 1.0, except where you chose otherwise.

### 9. Texturing

**Why:** texture memory is the budget that matters most for frame rate. The texture sizes, atlas rules and memory budget are in `texturing.md` of the MSFS Authoring Guide.

**Do:** texture each texture set in Substance Painter from the packed UVs. Use material values (colour, metallic, roughness) instead of a texture where a flat value is enough.

### 10. Export and Deploy

**Why:** the deploy exports the `.blend` in the background with the FSS exporter, merges the merge groups, and writes the LOD files.

**Do:**

- Set the export target (MSFS 2024 or MSFS 2020) in the exporter's **Export Target** panel. See [exporter.md](exporter.md).
- Deploy with your aircraft repository's scripts: the LOD deploy for models with LODs, the single-file deploy otherwise. See [Exporting with LODs](lod.md#exporting-with-lods).
- After a deploy, check the console: the LOD lines, merge warnings, and vertex warnings.

**Check:** the model loads in the simulator, LODs switch where intended, and every referenced node is found.

## Where to Find the Tools

- **FSS Tools:** in the 3D Viewport, press `N` to open the sidebar, then pick the **FSS Tools** tab. The panels are, from top to bottom: **Tools**, **Empty Bounds**, **LOD**, **Tags**, **Merge Tree**, **UV Marks**, **Auto Seam**, **UV Heatmap**, **Checks**.
- **Exporter:** in the same sidebar, tab **Microsoft Flight Simulator 2024 Tools**, panel **Export Target** (also shown in **File > Export > glTF 2.0**, section **Microsoft Flight Simulator (FSS)**).
- **Material and object settings:** in the Properties editor, the MSFS panels of the Asobo add-on, plus **MSFS 2020 Object Parameters** and **MSFS 2020 Material Parameters** while the scene targets MSFS 2020.

## Installed Add-ons

The portable Blender in `tools/blender` of the aircraft repository enables these add-ons at every start:

| Add-on | Name in Blender | Role |
| :--- | :--- | :--- |
| `fss_blender_tools` | FSS Blender Tools | The **FSS Tools** sidebar tab |
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
| **Mark** | A setting stored on an object (a custom property) that tells a tool how to treat it, for example "hidden from LOD 3". |
| **Material class** | The kind of material (standard, emissive, decal, glass and so on), the last part of a material name `<SCENE>_<ZONE>_<CLASS>`. |
| **Merge group** | An object named `@MERGE_<name>` whose subtree becomes one mesh at export. |
| **Origin** | The object's own point (orange dot in Blender). In the glTF it becomes the node position. |
| **Part** | An object together with all objects below it in the hierarchy. |
| **Tag** | A free label on an object, used to select objects and to tell tools how to treat them. |
| **Texture set** | The textures of one material, shared by every object that uses it; one zone and class. |
| **Zone** | A part of the model with its own materials and texture sets, chosen by you for the scene. |
