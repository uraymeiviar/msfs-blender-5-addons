# Journals

Task journals of this repository: design, decisions, progress and hand-offs, one file per topic
(`<yyyymmdd>.<topic>.md`, the date the topic started). Rules for writing them are in [../../AGENTS.md](../../AGENTS.md)
(append-only, read the latest session first). End-user documentation for artists is in [../user/](../user/).

| Journal | Topic | Status |
| :--- | :--- | :--- |
| [20261002.msfs2024-blender5-exporter-conversion.md](20261002.msfs2024-blender5-exporter-conversion.md) | Unified MSFS 2020 + 2024 exporter for Blender 5.2, differential test harness | In progress |
| [20261010.fss-blender-tools-wishlist.md](20261010.fss-blender-tools-wishlist.md) | Wish-list and feasibility of FSS authoring tools | Exploratory |
| [20261010.automated-lod-generation.md](20261010.automated-lod-generation.md) | Automated LOD export, size culling, MSFS LOD sphere and padding | Implemented, continuing |
| [20261011.fss-blender-tools-empty-bounds.md](20261011.fss-blender-tools-empty-bounds.md) | Empty Bounds overlay and hierarchy text | In review |
| [20261011.fss-blender-tools-name-check.md](20261011.fss-blender-tools-name-check.md) | Name Check and batch rename | In review |
| [20261014.fss-blender-tools-tags-and-merge.md](20261014.fss-blender-tools-tags-and-merge.md) | Tags and export-time merge groups | In review |
| [20261017.export-performance.md](20261017.export-performance.md) | Export speed of the LOD deploy | Phase 2 done |
| [20261019.automated-uv-unwrap.md](20261019.automated-uv-unwrap.md) | UV auto-seam, unwrap and packing; material classes and zones; visibility-based texel density | Implemented (0.33.1); entry point Session 102: current design, decisions in force, open items |
| [20261021.artist-pipeline-guide.md](20261021.artist-pipeline-guide.md) | The artist guide's pipeline (`docs/user/`): reasoning, redo points, terms | In progress |
| [20261028.material-management.md](20261028.material-management.md) | Materials panel: material checks, zone distribution, texture sizes and splits; zone tool on hold | Design |
| [20261103.anisotropic-preview.md](20261103.anisotropic-preview.md) | Anisotropic and Hair textures in Material Preview and Rendered views, exports unchanged | Implemented, review open |
| [20261103.weighted-normal-instancing.md](20261103.weighted-normal-instancing.md) | Shared meshes with Weighted Normal exported once, for batched draw calls | Reviewed, MSFS check open |
| [20261105.uv-seam-mismatch-substance.md](20261105.uv-seam-mismatch-substance.md) | Artists' seam mismatch in Substance Painter (triplanar), and 16-bit UVs | Paused, waiting for a session with Substance |
| [20261110.wiper-mask-16bit.md](20261110.wiper-mask-16bit.md) | Wiper Mask Generator saves 16 bits per channel | Done, MSFS check open |
| [20261112.auto-bake-ao-curvature.md](20261112.auto-bake-ao-curvature.md) | Auto-bake of AO and curvature; masters that survive UV changes | Prototype of master and copy (Session 2), reviewed (Session 3); P12 stopped at step 1 (Session 4); P15 (Session 6): the open border is the largest cause, a mirrored skirt helps a little; P18 (Session 8): master islands split at folds lower the panel's seam ratio (still NOT MET in (d), (e)) for +51 % (panel) and +74 % (cap) master pixels; maximum-error line still NOT MET; 4 x master (Session 11): seam line MET on the panel in every layout, wrong pixels and MAE down, about 4 x the master pixels; maximum line still NOT MET (panel (b), (d); at (d) the GT disagrees with a high-resolution GT); a same-face read (step 3) helps little and is proposed to be dropped; proposals P16, P17, P19 to P25 open |

The first five were started in the FSS aircraft repository (`codes/wasm/doc/journal/`) and moved here; their copies
there end with a session pointing here.
