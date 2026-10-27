# Project Contract Tools

[Specification](README.md) / **project-contract.md**

Tools that need the project contract: what the MSFS project (model XML, `.cfg` files, attachments) expects from a
glTF. The contract is to come from `project-tree` in the FSS aircraft repository, which fss_blender_tools asks as an
API or an MCP-like endpoint; the transport is open (WL D2). None of these tools is decided or built. Each traces to
its wish-list item, which holds the description.

### PRJ-001: Project contract source

- **Status:** wish
- **Requirement:** fss_blender_tools reads the project contract of the model being edited (expected node names,
  animations, attachments, clickspots) from `project-tree`; tools that need it are unavailable without it, and no
  other tool depends on it (P-2).
- **Decision:** WL D2 (ask project-tree; transport open); wish-list Shared Foundation
- **Test:** no test

### PRJ-002: Sub-model and attachment preview

- **Status:** wish
- **Requirement:** Shows the sub-models and attachments the project places on the model, in place.
- **Decision:** W1
- **Test:** no test

### PRJ-003: Name check against the project

- **Status:** wish
- **Requirement:** Scan Names (GEN-008) also reports names the project expects but the file lacks or spells
  differently, and warns before a rename that breaks a reference.
- **Decision:** W2 (GEN-008 works without it)
- **Test:** no test

### PRJ-004: Missing nodes and animations

- **Status:** wish
- **Requirement:** Lists nodes and animations the project expects that the export does not contain.
- **Decision:** W3
- **Test:** no test

### PRJ-005: Clickspot and collision mesh generator

- **Status:** wish
- **Requirement:** Generates clickspot and collision meshes, with the Invisible material, for the project's
  interactive parts.
- **Decision:** W4; WL D4 (clickspots are meshes with the Invisible material)
- **Test:** no test

### PRJ-006: MSFS project view

- **Status:** wish
- **Requirement:** A tree of the objects the project references, with playback of their animations.
- **Decision:** W6
- **Test:** no test

### PRJ-007: E1-to-E2 name mapping

- **Status:** wish
- **Requirement:** A mapping table from E2 Blender names to the E1 contract names, applied as a batch rename of the
  objects.
- **Decision:** W13
- **Test:** no test

### PRJ-008: Input normalizer and adaptor-empty collapse

- **Status:** wish
- **Requirement:** Reports inputs whose local axis is off their motion axis or whose origin is far from the pivot, and
  collapses adaptor empties.
- **Decision:** W17
- **Test:** no test
