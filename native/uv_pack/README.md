# fss_uv_pack

The UV packer in C++: `fss_blender_tools/uv_fill.py`'s placement of islands on a raster (`place`, the FSS packer
since step c replaced Blender's Pack Islands), the move of islands outside the texture into its free space (`repair`)
and the straightening of Free islands (`straighten`). The add-on loads the DLL with ctypes (`uv_fill.load`); Python
keeps the cheap setup (the order of the islands, the cell size, the reach table) and the columns of the islands that
fit nowhere. There is no Python fallback: without the DLL, Pack and Check refuse with the
reason (native UV packer decision 13). Design, decisions and measurements: the journal
[20261116.native-uv-packer.md](../../docs/journal/20261116.native-uv-packer.md).

Interface version 2 (`FSS_UV_PACK_VERSION` in `fss_uv_pack.h`, checked by `uv_fill.VERSION`; version 1 had no turn
sets, only a quarter turn or none):

| Export | What it does |
| :--- | :--- |
| `fss_uv_pack_version` | the interface version |
| `fss_uv_solid` | the cells a set of triangles touches (an island's footprint) |
| `fss_uv_place_once` | one placement of the islands on a raster of a given size, each turned as its turn set allows after its base angle; 0 when one fits nowhere |
| `fss_uv_repair` | the islands outside the texture moved into its free space, the ones that fit nowhere listed |
| `fss_uv_straighten` | per island the angle that gives it its smallest bounding box (for Free islands) |

Turn sets: 0 Upright (no turn), 1 Flip (180 degrees), 2 Quarter (90-degree steps), 3 Eighth (45-degree steps). The
turns are tried in the order no turn, 180, 90, 270, then the 45-degree ones, which also breaks ties (native UV packer
decision 20).

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

- **For islands that do not turn, the library is bit-identical to the Python code of step b**, kept as
  `tests/uv_fill_reference.py`; `test_fill_native_matches_reference` compares footprints, placements and repairs on
  random sets. Float64, the same formulas in the same order, `/fp:precise`, no `/arch:AVX2` (no FMA contraction);
  numpy's stable sorts and `lexsort` tie-breaks reproduced with `std::stable_sort`.
- Turns other than multiples of 90 degrees use the cosine and sine of the angle, as `uv_fill.apply` does; the
  footprints are conservative, so a difference in the last bit does not take a gap below the margin.
- The turns of step c and the later steps (priority, aligned edges) change the layouts on purpose; the finish lines of
  the journal judge them, not the reference.
- Raise `FSS_UV_PACK_VERSION` and `uv_fill.VERSION` together whenever an export changes.
