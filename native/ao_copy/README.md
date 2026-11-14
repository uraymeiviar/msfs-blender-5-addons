# fss_ao_copy

The per-pixel work of AO Bake's Apply copy in C++: `fss_blender_tools/ao_bake_core.py`, `copy_master`, its inside
pixels (the L x L sub-samples, the raster of their owners, the master reads, the mean) and its padding pixels (the
reads of the hinged or own triangle, the mean). The add-on loads the DLL with ctypes (`fss_blender_tools/ao_bake_copy.py`);
the numpy copy stays the reference and the fallback. Design and measurements: the journal
[20261114.apply-native-copy.md](../../docs/journal/20261114.apply-native-copy.md).

## Build

MSVC x64 (Visual Studio 18), one source file, the static C runtime (`/MT`), no dependency but `KERNEL32.dll`:

```bat
native\ao_copy\build.cmd
```

On the maintainer's PC through the CPU cap (AGENTS.md):

```bat
C:\Users\uray\.claude\tools\cpucap\cpucap.exe 50 cmd /c native\ao_copy\build.cmd
```

Output: `fss_blender_tools/lib/ao_copy/windows-x64/fss_ao_copy.dll` (committed); intermediates in `native/ao_copy/build/`
(git-ignored). Then run the harness and the AO suite (tests/README.md).

## Rules

- **Bit-identical to the numpy copy.** Float64, the same formulas in the same operation order, `/fp:precise`, no
  `/arch:AVX2` (no FMA contraction). numpy's reductions are reproduced as numpy 2.3 computes them: `np.add.reduce`
  over a contiguous axis is the identity 0 plus a pairwise sum (eight partial sums up to 128 values, halves above);
  `np.einsum('nk,nkd->nd')` is `(p0 + p1) + p2`; `np.einsum('nd,nd->n')` (the normals' dot) is `(p0 + p2) + p1`.
  A new numpy in Blender can change these: `tests/test_ao_copy_native.py` checks them first.
- **Deterministic for any thread count:** threads take pixels; a pixel's sums never split.
- **C interface:** plain functions and structs (`fss_ao_copy.h`), error codes, no exception across the boundary, no
  global state, `fss_ao_copy_version()`. The caller owns every buffer; the DLL frees what it allocates before
  returning.

## Interface

| Function | Does |
| :--- | :--- |
| `fss_ao_copy_version` | the interface version (1) |
| `fss_ao_copy_inside` | the inside pixels: per pixel its target position, owner triangle, level L and the corner of its block's raster grid; out the values and the count of clamped sub-samples |
| `fss_ao_copy_padding` | the padding pixels: per pixel its target position, source triangle, UV triangle and level; out the means and the count of clamped points |
| `fss_ao_copy_read`, `fss_ao_copy_raster`, `fss_ao_copy_sum` | test entry points: `read()`, `rasterize_ids`' owners, `np.add.reduce` |

The master (`fss_ao_master`) is the AO (uint16) and the map codes (int32, `(face + 1) * 2 + filled`) either as
open_master's page files (tiles of 256 px, memory-mapped read-only by `PagedArray.address`) or as row-major arrays
(`load_master`), plus the layout's corners, islands and rectangles and the mesh's triangle normals.
