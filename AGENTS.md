# Agent Guide: MSFS Blender Add-ons (FSS)

Onboarding for AI agents and developers working in this repository. User-facing documentation is in
[README.md](README.md); the FSS add-on's design is in [fss_blender_tools/README.md](fss_blender_tools/README.md).

## What This Repository Is

Blender 5.2 add-ons used by Flight Sim Studio (FSS) to author and export MSFS 2020 and MSFS 2024 aircraft. The
add-ons ship inside the portable Blender of each FSS aircraft repository (`tools/blender`), and artists may also
install them into their own Blender.

| Folder | Owner | Role |
| :--- | :--- | :--- |
| `io_scene_gltf2_msfs_fss` | Asobo, forked by FSS | The glTF exporter for MSFS 2024 and 2020 (unified). Asobo code plus FSS changes in FSS-owned modules |
| `_addons_common` | Asobo | Shared helpers of the Asobo add-ons |
| `lod_tools_msfs_2024`, `wipermask_generator_msfs_2024`, `max_bridge_msfs_2024` | Asobo | Asobo tools, unchanged |
| `fss_blender_tools` | FSS | FSS authoring tools: Tools (Add Empty Parent, Origin to Bounding Box), Empty Bounds, LOD level marking, Tags, Merge Tree, and Checks (Name Check, Fix Broken Bone Parents) |
| `tests` | FSS | Differential test harness ([tests/README.md](tests/README.md)) |
| `tools` | FSS | `deploy.ps1` / `deploy.bat` |

## Upstream Policy (the exporter)

- Asobo's releases are tracked in the per-simulator fork repositories (`msfs2024-blender-5.2.x-addons`, branch
  `upstream` holds the releases as published). This unified repository has no `upstream` branch: a new Asobo
  release comes in as a per-file three-way merge of the fork's change (old release to new release), committed as
  `merge: Asobo exporter <version>` with the hand-resolved conflicts listed (see commit ab96b86 for 8.4.1).
- Keep FSS changes in FSS-owned modules so those merges stay small: `instancing.py`, `migration.py`,
  `legacy_normals.py`, `msfs2020_target.py`, `io/exp/gltf_exporter_patches.py`, and marked spots in
  `io/exp/multi_export.py`.
- Line endings differ between Asobo's files and checkouts with `core.autocrlf`; normalize before merging, or a merge
  shows whole files as conflicts.
- New features that are not exporter fixes belong in `fss_blender_tools`, not in the exporter.

## How Export Works (what FSS code relies on)

- The Khronos glTF exporter instantiates `glTF2ExportUserExtension` from every enabled add-on and calls its hooks in
  the order the add-ons are enabled. `pre_export_hook` runs before the exporter collects the objects; changes made
  there are exported. `post_export_hook` is not called when the export raises, so never depend on it for restoring
  the user's scene.
- The MSFS 2024 multi-exporter duplicates the objects, exports the selection, and after each preset purges every data
  block created during the export (`purge_new_data`). Hooks therefore see throwaway copies. Duplicates carry the
  custom property `msfs_original_name` (written as the glTF node name); export copies of materials carry
  `msfs_original_data` (the artist's material).
- The FSS deploy script (`scripts/export-blend-to-gltf.py` in the aircraft repository) exports MSFS 2024 through the
  multi-exporter and MSFS 2020 through the plain glTF exporter, both in a background Blender that quits without
  saving.
- A shared mesh is exported once only when none of its users has a modifier; `instancing.py` rescues users whose only
  modifier is Auto Smooth with the same angle.

## Testing

- Run Blender in background only (`blender -b ... --python ...`). Build synthetic scenes in the script, or open a
  copy of a production `.blend`.
- Write exports to a scratch folder. Never export into an aircraft repository's `msfs24-projects` or `msfs-projects`:
  people work there live, and the simulator reads from there.
- Compare glTFs, not screenshots: node names and hierarchy, world matrices, triangle and vertex counts, primitives and
  materials, animation channels. Test an unchanged export as the baseline.
- A portable Blender loads add-ons from its own `5.2/scripts/addons_core` before a `BLENDER_USER_SCRIPTS` folder: a
  test then silently runs the deployed copy, not the code under test. Deploy first, or use `--factory-startup` with
  a Blender that has no copy.
- `tests/run_tests.py` diffs exports between two add-on sides; see [tests/README.md](tests/README.md).

## Deploying

Targets are machine-specific, so they live in `deploy.local.json` (git-ignored). Copy
[deploy.local.json.example](deploy.local.json.example) and list the machine's installs:

| Type | Path | What deploy does |
| :--- | :--- | :--- |
| `portable` | `<aircraft repository>/tools/blender` | copies into `5.2/scripts/addons_core`, updates the commit and `fss_blender_tools` version in `FSS-ADDONS-VERSION.txt`, notes add-ons missing from `5.2/scripts/startup/fss_enable_addons.py` |
| `user` | a Blender user add-on folder, on Windows `%APPDATA%\Blender Foundation\Blender\5.2\scripts\addons` | copies the add-ons |

```bat
tools\deploy.bat -DryRun
tools\deploy.bat
tools\deploy.bat -Addons fss_blender_tools
```

- Deploy refuses uncommitted add-on changes and target files that are newer than the repository's (edited in place)
  unless `-Force`. It never deletes files in a target.
- A running Blender keeps the add-on version it started with; restart it.
- The copies in an aircraft repository are files of that repository: commit them there, following its own rules
  (FSS: `codes/wasm/AGENTS.md`, journals in `codes/wasm/doc/journal/`).
- Raise `bl_info["version"]` of `fss_blender_tools` with each functional change, so deployed copies can be told apart.

## Git

- Conventional commit messages (`feat(fss-blender-tools): ...`, `fix(...)`), one topic per commit.
- This repository is not under the FSS aircraft repository's agent rules; pushing `main` is allowed. Never force-push.

## Pitfalls Learned

- **Evaluated datablocks:** materials read from an evaluated object (`obj.evaluated_get(...).material_slots`) are
  evaluated copies. Assigning them to a real mesh crashes Blender on the next depsgraph update; use `.original`.
- **Parent bones:** setting `obj.parent` keeps `parent_type` and `parent_bone`. Moving a bone-parented object under
  an empty leaves an invalid parent type and "Failed to add relation Bone Parent" on every depsgraph build. Reset
  `parent_type = 'OBJECT'` and `parent_bone = ""` (Blender's Ctrl+P does).
- **Names:** Blender appends `.001` when a name is taken; in the multi-exporter, names come from
  `msfs_original_name`, in the plain exporter from the object names.
- **Batch files:** on machines with `NoDefaultCurrentDirectoryInExePath` set, run `.bat` files by full path, or with
  `cmd /c "set NoDefaultCurrentDirectoryInExePath=&& ..."`.

## Where Decisions Are Recorded

New work is recorded in this repository's task journals, `docs/journal/<yyyymmdd>.<topic>.md`, starting with
[docs/journal/20261010.automated-lod-generation.md](docs/journal/20261010.automated-lod-generation.md) (LOD export:
design, decisions, progress, handoffs). Journals are append-only: add `## Session <N>: <Title>` at the bottom and never
rewrite an earlier, committed session. Read only the journal of your task, latest session first. Record decisions,
runtime behaviour and what was verified, not machine-local files. Commit journal updates together with the work.

Testing in an aircraft repository happens on the E2 testbed (`D:ss-e2`, not under git; back up a file into its
`codes/wasm/.cache/backup/` before editing it). The FSS aircraft repository (E1) receives add-on updates only when the
maintainer asks.

Earlier rationale is in the FSS aircraft repository's task journals (`codes/wasm/doc/journal/`):
`20261002.msfs2024-blender5-exporter-conversion.md` (exporter port and fixes),
`20261010.fss-blender-tools-wishlist.md` (planned tools), `20261014.fss-blender-tools-tags-and-merge.md` (tags,
merge groups, checks), `20261011.fss-blender-tools-name-check.md` (name check), and the authoring guide
`doc/msfs-authoring/`.
