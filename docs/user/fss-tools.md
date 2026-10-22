# FSS Tools Panels

[Artist Guide](README.md) / **fss-tools.md**
***

All panels are in the 3D Viewport sidebar (`N`), tab **FSS Tools**. The **LOD** and **Auto Seam** panels have their own pages: [lod.md](lod.md) and [uv.md](uv.md).

## Tools

Helpers for parenting and object origins. Both work in Object Mode on the selected objects, and both can be undone.

### Add Empty Parent

Puts a new empty above each selected object.

- The empty sits at the object's location and rotation, with scale 1. It is a small Plain Axes empty.
- The empty takes over the object's old parent (also a parent bone) and its collections. The object becomes its child and does not move.
- **Name:** pick the naming rule from the menu next to the button, then edit the text field:
  - **Manual:** type the full name. Only for one selected object; the default is `<object name>_PARENT`. With several objects selected, the tool uses **Suffix**.
  - **Suffix:** object name plus the suffix (default `_PARENT`).
  - **Prefix:** prefix (default `PARENT_`) plus the object name.

### Origin to Bounding Box

Moves the origin of each selected object to a point of its tightest bounding box, without moving the geometry or the children.

- The box is fitted to the object's own geometry (children are ignored) and can be rotated. The object's axes are turned to match the box, staying as close to the old axes as possible.
- Pick the point in the menu next to the button: **Corners** (8), **Face-Center** (6, default **Bottom (-Z)**) or **Edge-Center** (12). Names describe the local axes, for example **Front (-Y)** or **Top Back Left (-X +Y +Z)**.
- After the tool runs, Blender's transform orientation is set to **Local**, so the gizmo shows the new axes.
- A mesh shared by several objects is first made single-user for the changed object.
- Use it to bring an origin back into its geometry; far origins change the LOD switch distances (see [lod.md](lod.md#origins-outside-the-geometry)).

Pitfall: the object's rotation values change. Do not use it on an object whose own transform is animated; the animation keys would no longer match.

## Empty Bounds

Draws, for each empty, a box around everything below it, and lists the parents of the active object. It only draws in the viewport: nothing is added to the scene or exported.

- **All / Selected / Off:**
  - **All:** boxes of every empty. While a non-empty object is selected, only the selection's parents: the direct parent solid (with a cross at its origin), the empties further up dashed.
  - **Selected:** boxes of the selected empties and of the empties above any selected object.
  - **Off:** no boxes.
- **In Front:** draw the boxes over the geometry (on by default), so they stay visible inside the fuselage or cockpit.
- **Hierarchy Text:** in the bottom-right corner of the viewport, the parent chain of the active object, root first (Object Mode only). Click a row to select that object; **Shift + click** adds it to or removes it from the selection.

The boxes include hidden children.

## Tags

A tag is a free label you put on objects, for example `SCREEN` or `KEEP_LOD`. An object can have several tags. Tags replace extra collections for grouping, and two toggles tell the export what to do with tagged objects. Tags are stored in the object's custom property `fss_tags` (separated by `;`), so you can also read them under **Object Properties > Custom Properties**.

- **Top row:** type one or more tag names (separate several with `;` or `,`), then **+** adds them to the selected objects, **-** removes them.
- **Active object box:** the tags of the active object; **X** removes one from the active object only.
- **Tag list** (every tag in the file, with the number of objects that carry it). Per row:
  - **-** and **+** (only with a selection): remove the tag from, or add it to, the selected objects. They are greyed out when there is nothing to do and highlighted red when several objects are selected.
  - **Select icon or tag name:** select the visible objects with this tag (**Shift + click** adds to the selection). Hidden objects are counted but not selected.
  - **Don't Merge** (merge icon): objects with this tag, and everything below them, stay out of merge groups (see [Zones & Merge Tree](#zones--merge-tree)).
  - **Keep:** objects with this tag are never hidden by the automatic LOD size rule, like the **Keep** mark (see [lod.md](lod.md#marks)).
  - **Rename** (pencil): renames the tag on every object in the file, and in the Don't Merge and Keep settings.
  - **Delete** (bin): asks for confirmation, then removes the tag from every object in the file. The objects stay.

Tip: to tag a whole collection, right-click it in the Outliner, **Select Objects**, then press **+** on the tag row.

## Zones & Merge Tree

Merge groups join many small objects into one mesh at export, while every part stays a separate, editable object in the `.blend`. Fewer meshes means fewer draw calls in the simulator. Zones hold the merge groups: the panel lists each zone with its groups, and sets the zone's texel density multiplier.

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
- **Refresh:** lists the zones and merge groups of the visible objects. Click a row to select that object. The list does not follow later changes in the scene; press **Refresh** again.
  - **Zone rows** (`@ZONE_` empties, without the prefix): the number of merge groups and objects below the zone, and the zone's **density multiplier** (default 1.0, from 0.1 to 10). The packer (in development) will multiply the texel density of everything below the zone by it: 2.0 for twice the texels per metre, 0.5 for half. A change is stored on the zone empty at once, without **Refresh**.
  - **Merge group rows**, below their zone and nested as in the scene, with objects, materials and kept-separate counts per group. Below the list, the active group shows its materials, a transparency split, its UV map names, and why objects were kept separate.
  - **`@NOMERGE_` rows**, one level below the group they belong to: these objects stay their own nodes under the merged mesh.
  - **Unzoned** (warning): merge groups with no zone above them. Move them below a `@ZONE_` empty.
  - **Warnings on zone rows:** a zone inside a merge group (it would be merged into the group's mesh) or inside another zone.
- **Print Details:** prints every group, and every object kept separate with its reason, to the system console (**Window > Toggle System Console**).

### Merge Pitfalls

- **Merging only happens in a deploy** (or the MSFS 2024 multi-exporter), where the exported objects are throwaway copies. A plain **File > Export > glTF 2.0** of the open file leaves the groups unmerged and warns.
- **The merge does not read the model XML.** An object the XML refers to (a screen, a clickspot, an animation target) is merged away unless it is animated, tagged **Don't Merge**, named `@NOMERGE_`, or kept for another reason. Check the Zones & Merge Tree before deploying.
- **Several materials in one group** stay several materials; the panel and the console warn so you can check that this is intended.
- **More than two UV maps** in a group: only two are exported. UV maps are matched by name; if members name them differently, they are matched by position, with a warning.
- **A merged name equal to a kept object's name** gives a warning; rename one of them.

## UV Marks

Marks for automatic UV unwrapping, packing, and heatmap review. The panel is closed by default.

- **Active object box:** the effective texel density range, island direction, and Skip Auto Seam mark of the active object, and where each comes from: **own mark**, **from** an ancestor, or **default**. An object without its own mark takes the mark of its nearest marked parent (for example an empty that groups a door).
- **Texel density range (x base):** how sharp the object's texture should be compared with the base density, as a range the packer may choose from. Type **Min** and **Max** and press **Apply**, or use a preset:
  - **Lower:** 0.7 to 0.8, for parts that are hardly seen.
  - **Higher:** 1.5 to 1.65, for prominent parts such as the glareshield.
  - **Clear:** remove the mark (inherit from the parent, else the default 0.9 to 1.1).
- **Island direction:** how islands may turn when packed:
  - **Free:** any angle.
  - **Upright:** no rotation (brushed metal, wood grain, text).
  - **Flip:** 0 or 180 degrees only.
  - **Quarter:** 90-degree steps only.
  - **Clear:** remove the mark.
- **Auto Seam (Skip Auto Seam / Clear):** marks the selected objects to be skipped by Auto Seam (for example fur, hair cards, wire bundles, cables, or decal soups). Children inherit the skip mark unless cleared or marked themselves. **Clear** removes the mark.
- **Select Marked:** select every visible object with its own density, direction, or skip mark.
- **Texture sets:** one row per material of the selection (up to 20) with its **Margin**, the space around each island as a fraction of the UV square (default 0.002). The line below shows what that means in pixels at 4K and 8K, and warns when the margin is under 4 px at 2K (texture compression works in 4 x 4 pixel blocks, so smaller margins bleed). A material with its own margin shows an arrow button that returns it to the default.

The density, direction, and skip buttons act on all selected objects. The **Min** and **Max** fields are not saved with the file.

## Auto Seam

Automated UV seam proposal for hard-surface meshes, with a **Distortion Limit** slider between less distortion and fewer islands, and **Accept + Unwrap** (Angle Based). See [uv.md](uv.md) for the complete guide, workflow, readable reports, and limits.

## Visibility Test

Analyses pilot and copilot camera visibility across animation states to determine unoccluded solid angles for every face and UV island. Writes `<blend_name>.visibility` to guide the automatic packer and the Heatmap. See [visibility.md](visibility.md) for full settings and workflow.

## Heatmap

Colours the selected objects directly in the 3D viewport:
- **Distortion:** Does each face keep its shape? (Conformal singular-value ratio)
- **Density:** Does each face get the right amount of texture relative to the texture set median and object marks?
- **Visibility:** How well is each face seen from the reference cameras (from `<blend_name>.visibility`)?

Includes a distribution chart in the panel and an optional UV grid with cell labels. See [uv.md](uv.md#heatmap-distortion-texel-density-and-visibility) for how to read it.

## Checks

Repairs for problems that break the export without an error message.

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

1. Press **Scan Names**.
2. Use the rule buttons to show only some rules.
3. Click a row to select that object (or bone); **Frame** zooms the viewport to it.
4. Edit a proposal in its field if you want another name. Untick rows you do not want renamed; **Tick All** and **Untick All** act on the rows shown.
5. Press **Rename Selected (N)**. The list is scanned again afterwards.

The check does not read the MSFS project: it cannot know which names the XML uses. Before renaming, make sure the old name is not referenced, or update the reference. Linked (library) items are listed but cannot be renamed here. Bones of an armature in Edit Mode are skipped.

### Fix Broken Bone Parents

When a bone-parented object gets a new parent through the parent field (instead of `Ctrl + P`), Blender keeps the old parent bone. Blender then reports "Failed to add relation Bone Parent" on every update, and the Relations panel cannot fix it. **Fix Broken Bone Parents** finds every such object in the file and resets it to normal object parenting, without moving it. It reports how many objects it fixed.
