# FSS Blender Add-ons: Artist Guide

**Artist Guide**
***

This guide is for 3D artists who model and texture Flight Sim Studio (FSS) aircraft in Blender 5.2. It explains what each panel and button does, how to use it, and what to watch out for.

It matches **FSS Blender Tools 0.20.0** and the FSS exporter based on Asobo exporter 8.4.1.

## Pages

| Page | Contents |
| :--- | :--- |
| [fss-tools.md](fss-tools.md) | The **FSS Tools** sidebar tab: **Tools**, **Empty Bounds**, **Tags**, **Merge Tree**, **UV Marks**, **Checks** |
| [lod.md](lod.md) | The **LOD** panel: automatic LODs, marks, size cut-offs, quota and hints, the LOD sphere, viewport preview, and exporting with LODs |
| [exporter.md](exporter.md) | The exporter: export target MSFS 2024 or MSFS 2020, one `.blend` for both simulators, materials, instancing, legacy normals |

## Where to Find the Tools

- **FSS Tools:** in the 3D Viewport, press `N` to open the sidebar, then pick the **FSS Tools** tab. The panels are, from top to bottom: **Tools**, **Empty Bounds**, **LOD**, **Tags**, **Merge Tree**, **UV Marks**, **Checks**.
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

If your version is newer than 0.20.0, some labels or buttons may differ from this guide.

## Terms Used in This Guide

| Term | Meaning |
| :--- | :--- |
| **Deploy** | Exporting a `.blend` to glTF with the aircraft repository's scripts and copying the files into the simulator package. The deploy runs Blender in the background. |
| **LOD** | Level of detail. `_LOD00` is the full model; `_LOD01` to `_LOD06` are lighter versions MSFS shows when the model is small on screen. |
| **Mark** | A setting stored on an object (a custom property) that tells a tool how to treat it, for example "hidden from LOD 3". |
| **Origin** | The object's own point (orange dot in Blender). In the glTF it becomes the node position. |
| **Part** | An object together with all objects below it in the hierarchy. |
| **Tag** | A free label on an object, used to select objects and to tell tools how to treat them. |
| **Merge group** | An object named `@MERGE_<name>` whose subtree becomes one mesh at export. |
