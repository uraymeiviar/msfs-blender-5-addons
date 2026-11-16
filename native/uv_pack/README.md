# fss_uv_pack

The UV packer's raster work in C++: `fss_blender_tools/uv_fill.py`'s placement of islands into free space (`place`)
and the move of islands outside the texture into it (`repair`). The add-on loads the DLL with ctypes
(`uv_fill.load`); Python keeps the cheap setup (the order of the islands, the cell size, the reach table) and the
columns of the islands that fit nowhere. There is no Python fallback: without the DLL, Pack and Check refuse with the
reason (native UV packer decision 13). Design, decisions and measurements: the journal
[20261116.native-uv-packer.md](../../docs/journal/20261116.native-uv-packer.md).

Interface version 1 (`FSS_UV_PACK_VERSION` in `fss_uv_pack.h`, checked by `uv_fill.VERSION`):

| Export | What it does |
| :--- | :--- |
| `fss_uv_pack_version` | the interface version |
| `fss_uv_solid` | the cells a set of triangles touches (an island's footprint) |
| `fss_uv_place_once` | one placement of the islands on a raster of a given size; 0 when one fits nowhere |
| `fss_uv_repair` | the islands outside the texture moved into its free space, the ones that fit nowhere listed |

## Build

MSVC x64 (Visual Studio 18), one source file, the static C runtime (`/MT`), no dependency but `KERNEL32.dll`:

```bat
native\uv_pack\build.cmd
```

On the maintainer's PC through the CPU cap (AGENTS.md):

```bat
C:\Users\uray\.claude\tools\cpucap\cpucap.exe 50 cmd /c native\uv_pack\build.cmd
```

Output: `fss_blender_tools/lib/uv_pack/windows-x64/fss_uv_pack.dll` (committed); intermediates in
`native/uv_pack/build/` (git-ignored). Then run `tests/test_uv_pack.py` (tests/README.md).

## Rules

- **Version 1 is bit-identical to the Python code it replaced**, kept as `tests/uv_fill_reference.py`;
  `test_fill_native_matches_reference` compares footprints, placements and repairs on random sets. Float64, the same
  formulas in the same order, `/fp:precise`, no `/arch:AVX2` (no FMA contraction); numpy's stable sorts and `lexsort`
  tie-breaks reproduced with `std::stable_sort`.
- Later steps of the journal (rotation, scale, priority, aligned edges) change the layouts on purpose; from then on
  the finish lines of the journal judge them, not the reference.
- Raise `FSS_UV_PACK_VERSION` and `uv_fill.VERSION` together whenever an export changes.
