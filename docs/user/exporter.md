# The FSS Exporter

[Repository Root](../../README.md) / [User Guide](README.md) / **exporter.md**
***

The add-on **Microsoft Flight Simulator 2020 + 2024: glTF Extension (FSS)** exports glTF for **MSFS 2024** and **MSFS 2020** from the same Blender install. It is the Asobo MSFS 2024 exporter with the FSS MSFS 2020 exporter built in. Do not enable the separate `io_scene_gltf2_msfs_2024` or `io_scene_gltf2_msfs_2020` add-ons next to it.

## Export Target

Each scene has an **Export Target**: **MSFS 2024** or **MSFS 2020**. It decides what an export writes: the glTF extensions, the material data, which collision gizmos and lights are exported.

Where to set it:

- 3D Viewport sidebar (`N`) > tab **Microsoft Flight Simulator 2024 Tools** > panel **Export Target**;
- **File > Export > glTF 2.0**, section **Microsoft Flight Simulator (FSS)**.

How it is chosen:

- New scenes are **MSFS 2024**.
- An older `.blend` without a saved target that contains MSFS 2020 data (MSFS 2020 export settings, legacy collision gizmos or lights, materials made with the MSFS 2020 add-on) is set to **MSFS 2020** when it is opened. Nothing is converted.

While the target is **MSFS 2020**, the panel also shows:

- **Microsoft Flight Simulator 2020 Extensions** and **Use ASOBO Unique ID** (both on by default);
- the emissive reference (see [Emissive Brightness](#emissive-brightness));
- a note that MSFS 2020 is exported with **File > Export > glTF 2.0**, because the multi-exporter writes MSFS 2024 glTF;
- in the Properties editor, the panels **MSFS 2020 Object Parameters** (legacy collision gizmo and light flash settings) and **MSFS 2020 Material Parameters** (material values only MSFS 2020 uses).

In the FSS workflow the deploy scripts of the aircraft repository do the export; they decide which simulator they deploy for.

## One File for Both Simulators

### Export For

Every object has an **Export For** setting: **All Targets** (default), **MSFS 2024 Only** or **MSFS 2020 Only**. An object marked for one simulator is skipped by the other's export.

In this version there is no field for it in the panels; **Prepare for MSFS 2024** sets it.

Independently of **Export For**, an MSFS 2020 export always skips MSFS 2024 collision gizmos, and an MSFS 2024 export always skips legacy MSFS 2020 collision gizmo empties.

### Prepare for MSFS 2024

The button appears in the **Export Target** panel when the file has legacy MSFS 2020 collision gizmos or lights without an MSFS 2024 counterpart. It makes such a file export correctly for both simulators:

1. It adds an MSFS 2024 collision gizmo next to every legacy gizmo empty (named `<empty name>_2024`), and an MSFS 2024 light next to every legacy light (with Asobo's light conversion).
2. It marks the originals **MSFS 2020 Only** and the new objects **MSFS 2024 Only**.
3. Nothing is removed, so the MSFS 2020 export stays the same.

## Materials

- **Materials store MSFS 2024 values.** Edit them in the normal MSFS material panels.
- **Materials made with the MSFS 2020 add-on are converted once**, automatically, when the file is opened, when they are appended, or before an export. Their values are kept; the MSFS 2024 node tree is built from them.
- **MSFS 2020 exports** use, for the export only, the material setup the MSFS 2020 add-on would have built from the same values. Your materials are unchanged afterwards.
- A material type that does not exist in MSFS 2020 is exported as a standard material; the **MSFS 2020 Material Parameters** panel says so.
- Only two UV maps per mesh are exported.

### Emissive Brightness

MSFS 2024 stores emissive brightness in cd/m² (the material default is 1000); MSFS 2020 uses a factor where 1.0 is full brightness. An MSFS 2020 export divides the brightness by the **emissive reference**: the cd/m² that MSFS 2020 shows as 1.0.

The reference is shown in the **Export Target** panel while the target is **MSFS 2020**:

- When a scene has its own reference, the panel shows the field **Emissive 1.0 (cd/m²)**. Materials converted from MSFS 2020 save the reference they were converted with in the scene, so their brightness keeps its meaning.
- Otherwise the panel shows the add-on preference (**MSFS 2020 Emissive Reference**, in **Edit > Preferences > Add-ons**). The portable Blender of the aircraft repository sets it at every start; the value is noted in `tools/blender/FSS-ADDONS-VERSION.txt`.

Do not change the reference of a scene with converted materials unless you mean to change how bright they are in MSFS 2020.

## Instancing

When several objects share one mesh, the export writes the mesh once and every object refers to it (an instance). This keeps files small, for example for hundreds of identical screws.

Blender 4.1 and later turned the old Auto Smooth setting into a Geometry Nodes modifier named **Auto Smooth**. The glTF exporter writes a separate mesh copy for every object that has any modifier. The FSS exporter keeps the instancing when all of these hold:

- every user of the shared mesh is exported;
- each user's only modifier is **Auto Smooth**, enabled in the viewport, with the same angle on all users;
- the mesh has no shape keys and no custom normals, and is not linked from a library.

Any other modifier (for example Weighted Normal) gives each object its own copy. To keep instances, apply such a modifier once on the shared mesh data and remove it from the objects.

## Legacy Normals (Files from Blender 4.0 or Older)

Blender 4.0 and older ignored sharp edges, custom normals and Weighted Normal modifiers on meshes with Auto Smooth **off**. Blender 4.1 and later always apply them, so such meshes shade differently after the upgrade. Blender also drops the old setting when the file is loaded.

- When an old file is opened, the exporter reads each mesh's Auto Smooth setting from the file on disk and keeps it with the mesh, so it survives saving.
- If meshes are affected, the **Export Target** panel shows a box, for example "12 mesh(es) from Blender 4.0 or older had Auto Smooth off", or objects whose **Auto Smooth** modifier is not where Blender 3.6 applied it.
- **Restore Blender 3.6 Normals** (asks for confirmation) stores the normals Blender 3.6 showed as custom normals on the meshes that had Auto Smooth off, removes their Weighted Normal modifiers (which had no effect in 3.6), and moves misplaced **Auto Smooth** modifiers back to where Blender 3.6 applied Auto Smooth: before the first enabled Weighted Normal or Normal Edit modifier, otherwise at the end of the stack.

Do it once per old file, check the shading, then save.

## Automatic Clean-Up on Export

The MSFS 2024 multi-exporter (used by MSFS 2024 deploys) does this for you:

- **NLA tweak mode:** objects left in NLA tweak mode are exported as if tweak mode were off; tweak mode is restored afterwards.
- **Edit Mode and Pose Mode:** objects in these modes are switched to Object Mode for the export.

## Asobo Export Workflow Hidden

In the FSS workflow the deploy scripts, merge groups and LOD marks replace Asobo's export workflow, so parts of the Asobo UI are hidden by default:

- The **Multi-Export glTF 2.0** panel shows only its settings, with the note "Export settings used by FSS deploys (fs24; fs20 uses fixed parameters)". The Hierarchy tab (LOD groups, export folders, Generate XML, Enable Auto LOD), the Export button and the Logs are hidden.
- Settings the deploy always overrides (MSFS extension, lights, apply modifiers, animation mode and sampling, texture library and texture folder) are hidden, so a stale value cannot mislead you. The remaining settings of the active settings preset are saved in the `.blend` and used by MSFS 2024 deploys.
- The **LOD Tools** panel is hidden. Use the FSS [LOD](lod.md) panel instead.

To see everything as Asobo ships it, turn on **Show Asobo export workflow** in **Edit > Preferences > Add-ons**, in the settings of the FSS exporter.

## Known Issue

- `msfs_ghost_bias` and `msfs_ghost_power` (ghost materials) have swapped value ranges between MSFS 2020 and MSFS 2024 and are not converted. Check ghost materials in both simulators.
