# Bake: AO, Curvature and Material Channels

[Artist Guide](README.md) / **bake.md**
***

The **Bake** panel (sidebar `N` > **FSS MSFS Tools** > **Bake**, with its sub-panel **Run**) bakes ambient occlusion (AO), a curvature map (CM) and the material channels (albedo, roughness, metal, emissive) of your objects, and writes them into the texture sets' textures. It works in Object Mode, on a saved `.blend`.

## How It Works

- **Bake and Apply are two steps.** A bake writes **masters**; **Apply** copies the masters into the textures of each texture set. **Run** (in the sub-panel) does either or both, for the selected objects.
- **A master** is the baked data of one mesh, in a layout of its own: AO, and when you bake them, the curvature and the material channels. It does not depend on your UVs. When you move, scale or repack the UVs, or make the texture larger, the master stays valid: **Apply** copies it into the UVs the texture set has now. Only a change of the mesh itself makes a master out of date.
- **The bake folder:** the masters are kept in `<blend name>.bake` beside the `.blend`, never inside it. So the `.blend` must be saved once: until then the panel says **Save the file once: the masters are kept beside it**. The masters are not committed to the aircraft repository; each artist bakes their own.
- **The bake runs in a second Blender,** on a snapshot of the scene as it is now, unsaved changes included. Your Blender, its scene and the `.blend` on disk are not touched, and you can keep working while it bakes.
- **Apply writes files only:** the texture files of the material, or separate files in an output folder. It adds nothing to the `.blend` and changes no material. A texture that Blender has open from such a file is reloaded, unless it has unsaved changes.
- **A mesh shared by several objects** (screws, identical knobs) has one master for all its copies, as it has one place in the texture.

## What Is Baked

- **Baked:** every visible mesh object of `_LOD00` with faces and a UV map, and only its faces whose material is a texture set. An object hidden in the viewport or from rendering, or marked **Visible from** a later LOD in [Object LOD](lod.md#object-lod), gets no master.
- **Left out by themselves:** faces with decal, glass, windshield, invisible or occluder materials. They get no AO and darken nothing.
- **Left out by tags** (see [Tags](#tags)): objects with a tag that has **Skip-AO-Bake**, **No Texture**, **Invisible** or **No Export** on get no master.
- After a **Refresh**, the **Excluded** count says how many visible meshes get no master. A bake's console report lists them with the reason: the tag, **no UV map**, **skip materials only**, or **no face with a texture set (material)**.

## The Panel

From top to bottom:

- **Not available:** and a reason, only when the add-on could not load its bake libraries (`fss_ao_copy.dll` or the JPEG XL library in its `lib` folder). The buttons then stay greyed until the add-on is installed again in full.
- **Masters:** the state of the masters, with **Refresh** and the Select buttons.
- **Object** (or **Objects (n)**): the settings of the active object.
- **Bake:** the settings of the bake, for the whole file.
- **Texture Target:** the texture sets and where Apply writes.
- **Run** (sub-panel): what to bake and apply, and the **Run** button.

While a bake or an Apply runs, the panel shows only its progress and **Cancel**; **Run** is hidden.

## Masters and Refresh

**Refresh** compares every master in the bake folder with the scene and grades it. The panel does not follow your changes by itself: press **Refresh** again after you edit the scene. A bake refreshes by itself before it starts.

| Line | Meaning | What Apply does |
| :--- | :--- | :--- |
| **Up to date** | Nothing has changed since the bake. | Copies the master. |
| **Surroundings changed** | The mesh is the same, but something around it changed: the object moved, a nearby object that darkens it moved, changed or got another tag, or a bake setting changed (the AO distance, for example). | Copies the master; bake again for the right AO. |
| **Mesh changed** | The object's geometry changed: its triangles, their positions or their normals, modifiers included. | Copies the master anyway and warns. Where the mesh has fewer triangles than baked, the faces are written white. |
| **Missing** | The object has no master yet. | Writes white AO there. |
| **Excluded** | A visible mesh that gets no master (see [What Is Baked](#what-is-baked)). | Nothing. |

Below them:

- **Curvature:** how many curvature masters are **up to date**, baked at **other width** (the **Curvature Width** setting changed), **missing**, or **need AO** (the curvature needs an AO master of the same mesh first).
- **Denoise** (while **Denoise** is on, or a denoise is out of date): how many are **up to date**, **to re-run** (the denoise settings changed) or **need AO**.
- **Select Missing**, **Select Stale** (surroundings or mesh changed) and **Missing and Stale** select those objects, by the last Refresh. **Missing and Stale** counts what is ticked to bake in **Run**: a missing or out-of-date master, curvature, denoise or material channel. Hidden objects are counted in the message but not selected.

A renamed object finds its master again at the next Refresh, when its geometry matches exactly one master whose object is gone.

## Bake Settings

The **Bake** box holds the settings for the whole file. Changing a setting that changes the AO makes the masters it affects **Surroundings changed**.

### AO Distance and Falloff

- **AO Distance** (default 250 mm): how far other geometry darkens a surface. Good values are about the gaps where large parts should still shade each other; in a cockpit, a few cm to 10 cm.
- **Auto Distance** and **Factor:** small objects bake with a shorter distance, the factor times the longest side of the object's own box. The distance field is then named **Max Distance**: the most any object gets. A small part is then shaded by its own shape and what is close to it. The Object box shows the object's own distance when it is shorter (**AO distance 40 mm (Auto Distance)**). The copies of a shared mesh all use the first copy's distance.
- **Distance Falloff** and **Steps:** an occluder darkens less the farther it is, from full at the surface to nothing at the AO distance. The bake takes about **Steps** times longer.

### Baker and Samples

- **Baker:**
  - **Auto** (default): **FSS OptiX** when it can run here (an NVIDIA GPU), else **Cycles**.
  - **FSS OptiX:** the add-on's own AO baker on the NVIDIA GPU, with its own denoiser. Where it cannot run, or fails, Cycles bakes, and the report says why. When it cannot run on this PC, a line under the setting says so.
  - **Cycles:** Blender's Cycles bakes every master.
  - A master baked by the other baker is not out of date.
- **FSS OptiX Samples** (default 4096): rays per master pixel with FSS OptiX. Shown unless the baker is Cycles.
- **Cycles Samples** (named **Samples** when the baker is Cycles; default 256), **Device** (**CPU** or **GPU**) and, with CPU, **Threads** (the CPU threads of the bake and of Apply; 0: half of this PC's logical processors). Shown unless the baker is FSS OptiX.
- **Channel Samples** (default 64): samples per master pixel of the material channels, which always bake with Cycles.

### Poses, Shared Meshes and Occluders

These are the defaults of the file; an object (or a shared mesh) can override them in the [Object box](#the-object-box).

- **Default Poses** (default 5): an object with something moving against it (it moves, or a part near it does) is baked in this many poses spread over that animation, and the poses are averaged. A shadow that only one pose has then shows only faintly. 1 bakes the current frame only.
- **Shared Meshes:** how the copies of a shared mesh become its one AO. Each copy is baked in its own surroundings, then:
  - **Average** (default): a shadow all copies have (the panel under a knob) shows fully, one copy's neighbour only faintly;
  - **Most Lit:** each pixel takes its lightest copy: only shadows every copy has;
  - **Darkest:** each pixel takes its darkest copy: every copy's shadows;
  - **One Instance:** only one copy is baked, and all copies use it (see [Shared Meshes](#shared-meshes)).
- **Quality** (shown with more than one pose, or a Shared Meshes setting other than One Instance): how the samples are spent when a master averages several views (poses or copies). **Split Samples** (default) shares them, so the bake takes about as long as one view; **Full Quality** bakes every view with all samples: less noise, as many times slower as there are views.
- **Default Occluders:** what darkens an object.
  - **Scene Rule** (default): every visible mesh near the object (within its AO distance), except objects whose tags have **Non-AO-Occluder**, **Invisible** or **No Export** on. Parts that move with the object darken it as placed; parts that move against it darken it in each pose.
  - **Self Only:** each object darkens only itself.

### Denoise

**Denoise** and **Strength** (1: the filtered value, 0: the bake): each AO master is cleaned of noise after its bake. The raw bake is kept beside it, so changing these settings later re-runs only the denoise at the next Run with **AO Bake** ticked, without baking again.

- **Method:**
  - **OIDN** (default): Intel Open Image Denoise, on each group of islands apart, so islands do not bleed into each other. Fast; only **Strength** to set.
  - **Surface Filter:** a filter that smooths along the surface and keeps sharp edges, curvature changes and contact shadows. Its settings: **Radius** (how far a pixel is averaged with others), **Max Levels** (how far the filter can reach at most), **Smoothing** (higher smooths more and can soften contact shadows; lower keeps more detail and more noise), **Sharp Angle Threshold** (faces of an edge sharper than this are never averaged), **Curvature** (**Similar**, **Shrink** or **Off**) with its **Threshold**, and **Noise** (**Measured** on the master, or **From Samples**, which usually smooths more).

### Curvature Width

**Curvature Width** (shown while **CM Bake Selected** is ticked in Run, or while the Surface Filter uses the curvature): how far from a sharp edge its curvature band reaches, the same on every island. Changing it makes the curvature masters out of date (**other width**); the AO is not touched.

## The Object Box

The settings of the active mesh object, from the last Refresh where they need one.

- **Object: NAME**, or with several meshes selected **Objects (n)** over a row with the active one's name, `(2 of 5)` and two arrows: the arrows make the previous or next selected mesh the active one; the selection stays. The settings below are always the active object's. Hold **Alt** while you change one to set it on every selected object.
- **Material channel lines,** one for each channel the master has, for example **Albedo: up to date**, **Roughness: mesh changed** or **Metal: missing**.
- **AO distance … (Auto Distance)**, when the object's own distance is shorter than **Max Distance**.
- **Occluders:** **Default (Scene Rule)** (the file's **Default Occluders**), **Scene Rule**, **Self Only** or **Custom** (see [Custom Occluders](#custom-occluders)).
- **Moving parts and Poses** (see [Moving Parts](#moving-parts)).
- **The Detected list** (see [The Detected List](#the-detected-list)).

### Shared Meshes

When the active object's mesh is used by several objects, the box shows **Shared mesh, N copies:** and the mesh's **Copies** setting: **Default (Average)** (the file's **Shared Meshes**), **Average**, **Most Lit**, **Darkest** or **One Instance**. The setting belongs to the mesh, so every copy shows the same.

**One Instance** bakes one copy for all:

- A bake bakes the copy that is selected. With several copies selected, the **Bake Copy** drop-down lists them and names the one to bake; without a choice there, the active object, else the first selected by name.
- The master remembers that copy until a bake of another selected copy. A mesh never baked takes its first copy by name.
- **One Instance: baked from NAME** says which copy the master was baked from (**One Instance: NAME (first by name)** before the first bake). **Bake Selected bakes NAME** shows when the selection would bake another copy.
- **Select Missing** and the other Select buttons select every copy of the mesh, so the next Run bakes the copy **Bake Copy** names (or the active one).

The material channels of a shared mesh:

- **Albedo, Roughness and Metal** come from one copy. While one of them is ticked to bake and several copies are selected, **Bake Copy** names that copy (with any **Copies** setting).
- **Emissive** is combined over the copies by the **Copies** setting, as the AO is.

### Moving Parts

An object moves when it or a parent is animated, or carries a tag marked **Animated**.

- After a Refresh, the box says what moves: **Moves against 3 objects, frames 0 to 100** (the object moves), **Moving nearby: 3 objects, frames 0 to 100** (something near it moves), or **Moves with everything around it: one pose**.
- **Poses:** **Default (5)** (the file's **Default Poses**) or **Manual**, with **Number of Poses**. It shows on every object that moves, also before a Refresh.
- A part that moves without keys (a driver only, or the **Animated** tag) is baked in the current frame, and the box says so.

### Custom Occluders

With **Occluders** set to **Custom**:

- **Scene as occluder:** on, the scene rule darkens the object, minus the list's ignored objects, plus its added ones; off, only the list's added objects.
- **The list:** each row's first icon switches **Add** (green plus: it darkens the object) and **Ignore** (red cross, the row in red: it never darkens the object). The second icon, **With its children**, makes the row also cover the object's children at every depth; a row on a child wins. A greyed row has no effect.
- **Add** (eyedropper field): pick an object to add it without changing the selection. **Add Selected** adds the selected objects but the active one; **Remove** removes the highlighted row; **Clear** empties the list.

### The Detected List

The objects that the scene rule finds near the object, with their parents, from the last **Refresh** or **Find Occluders**. With several meshes selected, the list joins theirs.

- **Find Occluders** fills the list. It only searches; the master counts stay as the last Refresh left them.
- **Detected by the scene rule: n objects** (or **Detected for 3 selected: n objects**), and **2 selected not found yet** when some of the selection have no search result.
- **Each row:** **+** (lit: it darkens) and **-** (lit red: it never darkens; both unlit: mixed), then a highlight button (draws the object and its children as a bright wire over the viewport; again to clear) and a select button (selects the object and its children and makes it active). A parent row has a fold arrow and the number of detected objects below it. On the right: the gap to the object in mm (on a parent row the smallest in its branch) and, with several selected, how many of them detect it.
- **+** and **-** change the object's **Occluders**: **Self Only** becomes **Custom** with the row added; **Scene Rule** becomes **Custom** with **Scene as occluder** on and the row ignored.
- **Right-click a row** for **Find Occluders**, **Tree View** or **Flat View**, **Sort by Distance** or **Sort by Name**, **Select All**, **Highlight All** and **Clear Highlight**. The list's filter field finds rows by name.

## Texture Target

The texture sets and where Apply writes. It needs a Refresh first (**Refresh first**).

- **The list:** the texture sets of the selected objects (**Texture sets of the selection: n (none selected: all)**). Each row:
  - **The tick:** whether **Run** applies this texture set; unticked, it is left as it is.
  - **n complete**, or the buttons **n missing** and **n stale**, which select those objects of the set.
- **Texture set: NAME:** the settings of the only texture set of the selection, else of the row you clicked (**Pick a texture set in the list**).

### AO

- **Target:**
  - **Separate File:** a file of its own in the output folder.
  - **ORM Texture:** the texture in the material's ORM slot, in place: the AO goes into its red channel, green and blue stay byte for byte. The box names the texture, and **8-bit file: written as 16-bit** when it is 8-bit (its values are kept). A copy of the file is kept in the bake folder before the first write.
  - The **Target** also decides where the material channels go (see [Where Apply Writes](#where-apply-writes)).
- **With Separate File:**
  - **Output Folder:** empty, a folder `<blend name>_ao` beside the `.blend`.
  - **File:** default `<material>_ao.png`; clear it to go back to the default.
  - **Resolution:** the size of a new file: **ORM Texture Size** (when the material has an ORM texture) or 256 to 8192 pixels per side. An existing file keeps its own size, shown as **Resolution: 4096 x 4096 (the file's size)**.
  - **Channels:** **Greyscale** (the AO in red, green and blue) or **Red (ORM)** (the AO in red). With Red (ORM), **Green and Blue:** **White** (MSFS then uses the material's roughness and metallic factors) or **From ORM Texture** (the roughness and metallic of the ORM texture). At another size than the ORM texture, the box warns **Another size: roughness and metallic are resampled** and offers **Sampling**: **Automatic**, **Nearest** (hard metallic edges stay hard) or **Bicubic** (sharper).
- **Padding** (default 8 px): the pixels written around each island. It applies to the AO and the material channels.
- **Soften Sharp Edges** and **Width:** Apply treats convex sharp edges (a lip, a rim; faces more than 30 degrees apart) as slightly rounded: the darker side brightens toward the brighter side at the edge. Inside corners keep their contact shadow. The AO only; the masters are not changed.

### Curvature Map

The curvature is always written into a separate 16-bit grey file: 50 % grey where the surface is flat, lighter on convex edges, darker in concave ones. Where an object has no curvature master, the file is flat grey.

- **Output Folder:** empty, the AO's.
- **File:** default `<material>_curvature.png`.
- **Resolution** and **Padding:** as the AO's, for this file.

A line with a warning icon under the box names what stops Apply for this set, for example **No texture in the ORM slot** or **Output folder cannot be made: …**.

## Run

The **Run** sub-panel chooses what to do for the selected objects and does it.

- **Run In:** **Background** (default: the second Blender has no window) or **Foreground** (with FSS OptiX, its window shows the bake and a preview of the master; with Cycles, the second Blender opens a window). The panel shows the progress in both.
- **The grid:** a row for **AO**, **CM**, **Albedo**, **Roughness**, **Metal** and **Emissive**. Left, **<Channel> Bake Selected (n)**; right, **Apply <Channel> to Texture (n objs, m sets)**, where n counts the selected objects and m their ticked texture sets. **AO Bake Selected** and **Apply AO to Texture** are ticked by default, the others not.
- **An Apply tick in red:** a selected master of that channel has **mesh changed** since its bake. The line **n mesh changed since its bake: applied anyway** counts them. Apply copies them anyway.
- **The vertex colour sources** and **Fetch** buttons, under the grid: see [Vertex Colour Sources](#vertex-colour-sources) and [Fetch](#fetch-masters-into-the-vertex-colour).
- **Run** bakes what is ticked, then, when the bake has finished, applies what is ticked to the objects that were selected when you pressed it. With only Apply ticked it applies at once. When Run cannot start, the lines under it say why, for example **Tick what to run**, **Select the objects to run**, or a texture set's problem.

What a bake bakes, per selected object: what is missing or out of date for the ticked channels (a denoise alone re-runs from the raw bake, without rays). An object whose ticked channels are all up to date is baked again in full. **CM** without **AO** bakes only objects whose AO master has the same mesh; the others are named in a warning.

What Apply writes: only the faces of the selected objects and their padding, and padding only where no other face of the texture set lies. Every other pixel stays as it was. A new separate AO file starts white.

### While It Runs

- **Baking:** **Object 3 of 12, 25 %**, the object's name, the tile (or the denoise's band), the copy and the pose being baked, **Spent** and **left** times, **Then: apply to the textures** when Run applies after the bake, and **Cancel**. Cancel stops after the current tile: finished masters are kept, the object being baked keeps its old master, and nothing is applied.
- **Applying:** **Texture set 1 of 3**, the texture set and what is being done, the times, and **Cancel**: the texture set being applied keeps its file as it was; sets already applied stay written.
- **After it:** one line, for example **done 12 of 12, in 312.4 s, 2026-11-18 14:05**, and a line per object that failed. The whole report goes to the system console (**Window > Toggle System Console**), Apply's too.

## Material Channels

A bake of **Albedo**, **Roughness**, **Metal** or **Emissive** reads the object's material as it is at the time of the bake: what reaches the Principled BSDF's Base Color (the colour before the MSFS AO multiply), Roughness, Metallic and Emission Color sockets. So you can bake from a temporary material and put the real one back afterwards, for example:

- a high-resolution texture assigned for the bake only;
- a changed colour or value.

How the channels behave:

- **They go out of date only when the mesh changes,** not when the material or the surroundings change. Putting the material back after the bake keeps them **up to date**.
- **A bake overwrites only the ticked channels.** The master's other channels stay as they are.
- **The master keeps its layout while the mesh is unchanged.** After a mesh change, a bake makes a new layout and removes the channels it does not bake: baking only Albedo after a mesh edit leaves the AO **Missing**.
- **A material without a Principled BSDF** on its Material Output: the channel is skipped for that texture set and the report says so.
- **Apply** copies a channel whose mesh changed anyway, with the warning. Faces without a master of the channel keep their pixels in that channel.
- Shared meshes: see [Shared Meshes](#shared-meshes).

### Where Apply Writes

| Channel | Target ORM Texture (in place) | Target Separate File (output folder) |
| :--- | :--- | :--- |
| AO | red of the ORM slot's texture | `<material>_ao.png` (or its **File**) |
| Albedo | the base colour slot's texture (red, green, blue) | `<material>.albedo.png` |
| Roughness | green of the ORM slot's texture | `<material>.roughness.png` |
| Metal | blue of the ORM slot's texture | `<material>.metal.png` |
| Emissive | the emissive slot's texture (red, green, blue) | `<material>.emissive.png` |
| Curvature | (always a separate file) | `<material>_curvature.png` (or its **File**) |

- **In place:** the texture's other channels and its alpha stay byte for byte. An 8-bit file is written as 16-bit with its values kept, and a copy is kept in the bake folder before the first write. Without a texture file in the slot, Apply reports the texture set as failed.
- **Separate files** are 16-bit; roughness and metal are single-channel grey files. A new file takes the AO's **Resolution**; an existing one keeps its size. Where nothing is written yet, a new albedo file is white, a new emissive, roughness or metal file black.

## Vertex Colour Sources

A channel can be baked from a colour attribute of the mesh instead of being traced (AO) or read from the material. Paint the values in Vertex Paint, then bake.

Under the grid, one row for each channel whose Bake tick is on:

| Row | Reads |
| :--- | :--- |
| **AO from Vertex Color Red** | the red |
| **Albedo from Vertex Color** | the colour (red, green, blue) |
| **Roughness from Vertex Color Green** | the green |
| **Metal from Vertex Color Blue** | the blue |
| **Emissive from Vertex Color** | the colour (red, green, blue) |

Ticked, a row offers:

- **Overwrite:** the master's channel becomes the vertex colour's value. For AO nothing is traced or denoised, and such an AO never goes **Surroundings changed**. The next bake with the source unticked traces the AO again.
- **Multiply** (default): the master's channel times the vertex colour's value: 1.0 changes nothing, 0.5 halves it. Each bake multiplies again. Without a master of the channel, or after a mesh change, it is the same as Overwrite. On AO it multiplies the traced AO after its denoise, and a later denoise-only run keeps it. Use it to paint a mask over a baked result.
- The curvature is not affected: it comes from the geometry.
- The values are linear: a grey painted at 0.5 gives 0.5, in a float or a byte attribute.

**Read** (once, while a source is ticked) chooses the attribute:

- **Second Color Attribute** (default): the second row of the mesh's **Color Attributes** list (**Object Data Properties**), whatever is active or render. An object with fewer than two is skipped for those channels and listed in the report; its master stays unchanged.
- **Active Attribute:** the mesh's active colour attribute (the one Vertex Paint paints). An object without one is skipped.

**Keep the real vertex colours as the first attribute,** active and render, and paint the bake values into a second one:

- Only one colour attribute is exported per mesh: the render one by the MSFS 2024 export, the active one in a merge group and by the MSFS 2020 export. A painted bake attribute left active can ship as the model's vertex colour.
- Vertex Paint paints the active attribute: make the second one active while you paint, then make the first one active again. With **Second Color Attribute**, the bake reads the second attribute whichever is active.
- A new mesh gets a white `Color` attribute from the MSFS exporter. It is the first attribute, so **Second Color Attribute** never reads it.

A shared mesh's attribute belongs to the mesh, so every copy gets the same values; a vertex colour emissive is not combined over the copies.

## Fetch: Masters Into the Vertex Colour

**Fetch Albedo**, **Fetch ORM** and **Fetch Emis** (in Run, under the sources) read the selected objects' masters into the attribute **Read** names, so you can paint over them and bake them back.

- **Fetch ORM:** red the AO, green the roughness, blue the metal. A channel without a master keeps that component as it is.
- **Fetch Albedo** and **Fetch Emis:** the colour.
- The three write into the same attribute, so a Fetch replaces what is painted there. **Ctrl+Z** undoes it.
- A button is greyed while it cannot run; the line under the buttons says why: **Fetch: press Refresh first**, **Fetch: select the objects**, or **Fetch: no Albedo master in the selection**. The last Fetch's report shows below it.

The round trip:

1. **Refresh**, select the objects, and press a Fetch button.
2. Make the attribute active and paint over it in Vertex Paint; then make the first attribute active again.
3. Tick the channel's Bake and its vertex colour source, and **Run**.

What to know:

- **One value per face corner:** a vertex shared by two faces can hold two values. Detail between the vertices is lost: baking a fetched master back with **Overwrite** smooths it. To keep the detail, paint a mask and bake it back with **Multiply**.
- **The attribute:** with **Second Color Attribute**, a mesh that has only its first attribute gets a second one, `FSS_Bake` (white, not active, not render). A mesh without any colour attribute is skipped: Fetch never makes a first one. An attribute on points or in bytes is converted to a float attribute on face corners, with the same name and its values kept; the report says so.
- **Skipped,** with the reason in the report: an object whose modifiers change the mesh (Mirror, Subdivision, Bevel), and a channel whose mesh changed since its bake.
- A shared mesh is written once.

## Tags

Two toggles of each tag in the [Tags](fss-tools.md#tags) panel act in the bake, on the objects that carry the tag (not on their children):

- **Non-AO-Occluder:** the object never darkens other objects. It still gets a master of its own.
- **Skip-AO-Bake:** the object gets no master (no AO, curvature or material channels). It still darkens other objects.
- With both on, the bake ignores the object completely: suits collision meshes, clickspots, helpers and decals.

Other toggles: objects whose tag has **No Texture** on get no master but still darken others; with **Invisible** or **No Export** on, they get no master and darken nothing (**No Export**: everything below them too).

## The Workflow

1. **Save the `.blend`** once.
2. **Tag** what must not darken or be baked (see [Tags](#tags)).
3. Press **Refresh** in **Masters**.
4. **Select** the objects, or use **Select Missing** or **Missing and Stale**.
5. In **Run**, tick what to bake and apply (**AO Bake Selected** and **Apply AO to Texture** by default) and press **Run**.
6. Read the result line and, for details, the system console.

- **After a new Pack or a larger texture:** untick the Bake ticks, keep the Apply ticks, select the objects and **Run**: the masters are applied into the new UVs.
- **After a mesh edit:** **Refresh** shows **Mesh changed**; select those objects and bake them again.

## Limits and What to Watch Out For

- **A master follows the mesh, not the UVs.** A bake keeps the master's layout while the mesh is unchanged, so a larger texture does not give the master more detail. Apply's console report counts the faces whose master has less than 4 times their texture's detail.
- **A changed mesh is applied anyway.** The result can be wrong where the mesh changed; bake those objects again.
- **One master per shared mesh:** all copies show the same AO.
- **The masters live only in the bake folder.** Deleting or moving `<blend name>.bake` loses them; renaming the `.blend` starts a new, empty bake folder.
- **Apply writes into files on disk.** With **Target ORM Texture** it changes your texture files in place; the first version of each is kept in the bake folder.
