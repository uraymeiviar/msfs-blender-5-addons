# fss_ao_copy

The per-pixel work of AO Bake's Apply copy in C++: `fss_blender_tools/ao_bake_core.py`, `copy_master`, its inside
pixels (the L x L sub-samples, the raster of their owners, the master reads, the mean) and its padding pixels (the
reads of the hinged or own triangle, the mean). The add-on loads the DLL with ctypes (`fss_blender_tools/ao_bake_copy.py`).
Since interface version 2 it also opens a master for Apply (`open_master`): the JPEG XL image decoded by libjxl with
its thread runner and the `.ao.map` inflated by zlib, into the two tiled page files. Since interface version 3 it
writes and reads PNG files (`png_writer`, `read_png`): the writer compresses on several threads, so its files have
the former Python writer's pixels but other bytes (decision 4); the reader reads every filter. Since interface
version 4 it also does Apply's per-pixel work around the copy: the raster of triangle owners (`rasterize_ids`,
`raster_window`), the dilation into the padding (`dilate_ids`), the UV islands (`uv_islands`, and with the raster and
the dilation `island_labels`) and Soften Sharp Edges (reading the master as the copy does). Since interface version 5
it also does the bake's post-processing: the composition of a master's window (`compose_block`: the corner rule, the
nearest fill inside the island rectangles, the face map of the core and the skirt, the counts) and the `.ao.map`
writer (compressed on a thread beside the composition). Since interface version 6 it also does Refresh's scene-rule
geometry (`ao_bake_store`'s `near`: the world-box and own-box gaps of every occluder, the keep test, for every object
of a pass in one call; the test of two placements moving against each other) and the mesh hash (`mesh_hash`'s SHA-1,
with the CPU's SHA instructions where it has them). Each part was bit-identical to the Python code it replaced
(byte-identical files); decision 6 removed that code: the DLL and libjxl are required (without them the AO Bake panel
says why, its operators and Apply refuse, a job fails with the reason), and the tests compare the DLL with the values
the Python code gave, recorded before it was removed (`tests/data/ao_native_reference.json`,
`tests/data/ao_scene_rule_reference.json`). Design and measurements: the journals
[20261114.apply-native-copy.md](../../docs/journal/20261114.apply-native-copy.md) and
[20261116.bake-post-native.md](../../docs/journal/20261116.bake-post-native.md).

## Build

MSVC x64 (Visual Studio 18), six source files (`fss_ao_copy.cpp`, `fss_ao_open.cpp`, `fss_ao_png.cpp`,
`fss_ao_pixels.cpp`, `fss_ao_compose.cpp`, `fss_ao_scene.cpp`) and zlib's inflate and deflate (`native/third_party/zlib`, zlib 1.3.2 with its LICENSE, compiled
first at `/W3`, linked in statically), the static C runtime (`/MT`), no dependency but `KERNEL32.dll` (libjxl is loaded
at run time from the folder Python passes; Soften loads `pow` from the system's `ucrtbase.dll`, see Rules):

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

- **Bit-identical to the numpy copy it replaced** (the recorded values). Float64, the same formulas in the same
  operation order, `/fp:precise`, no `/arch:AVX2` (no FMA contraction). numpy's reductions are reproduced as numpy
  2.3 computes them: `np.add.reduce` over a contiguous axis is the identity 0 plus a pairwise sum (eight partial sums
  up to 128 values, halves above);
  `np.einsum('nk,nkd->nd')` is `(p0 + p1) + p2`; `np.einsum('nd,nd->n')` (the normals' dot) is `(p0 + p2) + p1`.
  The scene rule (Session 5 of the bake-post journal, measured on Blender's numpy 2.3): `matmul` and the einsums
  that reduce a strided axis (`'kmx,kxj->kmj'`) sum in order, `((p0 + p1) + p2) + ...`; the einsums that reduce a
  contiguous axis of both operands (`'kij,nj->kni'`, `'...ij,...j->...i'`, `'kmx,kx->km'`) are `(p0 + p2) + p1`;
  `np.cross`, `np.linalg.norm` and sums of three in order. `np.linalg.inv` stays numpy's (the caller passes it).
  A new numpy in Blender can change these: `tests/test_ao_copy_native.py` checks them first. numpy 2.3's
  `np.maximum` and `np.minimum` on arrays propagate NaN and give the second value when both are equal; `np.clip` keeps
  the value when it equals a bound. `x ** 3` is the C runtime's `pow` of the process (`ucrtbase.dll`), which differs
  from the static runtime's `pow` in the last bit: Soften calls `ucrtbase.dll`'s, loaded from System32 for the call.
- **The same `.ao.map` bytes as Python's zlib:** zlib 1.3.2's deflate here and Python's zlib 1.3.1 give the same
  stream at level 1 for every map the harness and the bake wrote (compared byte for byte); a new zlib on either side
  can change that, and `tests/test_ao_copy_native.py` checks it.
- **Deterministic for any thread count:** threads take pixels; a pixel's sums never split. A PNG's bytes depend only on
  its pixels: the filtered stream is cut into blocks at fixed byte offsets, whatever the threads and the rows handed in.
- **C interface:** plain functions and structs (`fss_ao_copy.h`), error codes, no exception across the boundary, no
  global state, `fss_ao_copy_version()`. The caller owns every buffer; the DLL frees what it allocates before
  returning.

## Interface

| Function | Does |
| :--- | :--- |
| `fss_ao_copy_version` | the interface version (6) |
| `fss_ao_scene_near` | `near` of many objects (`fss_ao_scene`: every candidate's `bound_box`, its matrix after `motion()` and at each pose, who moves, the occluders' rows): the world boxes' gap (now, or swept over the poses of a moving one), the own boxes' separating-axis gap at the current frame or at each pose (the smallest counting), the keep test at the distance; out each object's occluders (in their order) with their gaps, and how close a gap came to its distance; threads take objects |
| `fss_ao_scene_moves` | `moves_against` of many pairs: one of them moves and the placement of one relative to the other changes by more than `MOTION_TOL` at some pose; the inverses are numpy's (passed in); threads take pairs |
| `fss_ao_mesh_hash` | `mesh_hash`: SHA-1 of the triangles as int32, the positions as float32, the corner normals rounded to 4 decimals as float32 (`rint(x * 10000) / 10000 + 0.0`); the SHA instructions where the CPU has them, else plain C++ (the same digest); threads round the corner normals of large meshes |
| `fss_ao_scene_boxes`, `fss_ao_scene_gaps` | test entry points: the own boxes of bounds placed by matrices; the separating-axis gaps of one own box to others |
| `fss_ao_compose_block` | `compose_block` of one window: the corner rule, the island rectangles, the nearest fill (`FILL` steps of the baked pixels inside their rectangle), the face map (the core triangles' raster, the skirt's inside the rectangles, grown `FILL` steps), the counts; out the values and, when asked, the filled flags, the faces and the `.ao.map` codes, written with a row stride (a strip's columns); a team of threads for the call splits rows, the dilation follows its frontier after the first step |
| `fss_ao_map_open`, `fss_ao_map_write`, `fss_ao_map_close`, `fss_ao_map_abort` | the `.ao.map` writer: its header, then one zlib stream (zlib's deflate at the level given, as `zlib.compressobj`) of the rows from the top, `Z_NO_FLUSH` as they come, finished at close; on a thread beside the caller (2 threads or more; at most 3 writes queued) or in the caller (1); an error or abort removes the file; stats |
| `fss_ao_copy_raster_ids` | `rasterize_ids` (or, selecting the triangles as `tris_in_window` does, `raster_window`): the owner (last covering triangle, or a label per triangle) and the count of every sample of a grid of W x H px at k x k samples per pixel; optionally written only where covered (`island_labels` merges several meshes); threads take rows |
| `fss_ao_copy_dilate` | `dilate_ids`: owners grown into the pixels without one, step by step in its eight directions' order, with an optional mask; out the owners and the steps; threads take rows within a step |
| `fss_ao_copy_uv_islands` | `uv_islands`: the island of each triangle, the same union-find in the same edge order, labelled as `np.unique` ranks the roots; threads compare the UVs of the edge pairs |
| `fss_ao_copy_soften` | Soften Sharp Edges (the former `_soften`): values at points on triangles softened near the folds of `soften_context` (`fss_ao_soften`), the master read as `fss_ao_copy_read` reads it; out the values and the count changed; threads take pixels; a concave fold's slopes need a step of `SOFT_SLOPE_MIN_STEP` (0.1) of the width (auto-bake decision 103) |
| `fss_ao_copy_inside` | the inside pixels: per pixel its target position, owner triangle, level L and the corner of its block's raster grid; out the values and the count of clamped sub-samples |
| `fss_ao_copy_padding` | the padding pixels: per pixel its target position, source triangle, UV triangle and level; out the means and the count of clamped points |
| `fss_ao_copy_open_master` | opening a master: the `.jxl` (libjxl's `jxl.dll` and `jxl_threads.dll` loaded from the folder given, its runner at the threads given less one, the multithreaded image-out callback) and the `.ao.map` (zlib, on the last thread beside the decode) into the page files (uint16 and int32 tiles of 256 px, `FILE_ATTRIBUTE_TEMPORARY`, filled through a mapped view of one row of tiles at a time); on an error a code, a message naming the file, and both files removed; stats (seconds, threads, rows of tiles mapped at most) |
| `fss_ao_png_open`, `fss_ao_png_write`, `fss_ao_png_close`, `fss_ao_png_abort` | the PNG writer: W x H px, 8 or 16 bits, 1 to 4 channels, filter 0 on every row, level 6; rows from the top in any blocks, copied into blocks of 512 KiB of the filtered stream at fixed offsets, each compressed on a worker thread (any count of 1 or more; at most 64 blocks in flight) with the 32 KiB before it as its dictionary and a sync flush (the method of pigz), written in order as IDAT chunks, one zlib stream; an error or abort removes the file; stats (seconds, waits, threads, blocks, bytes) |
| `fss_ao_png_read` | the PNG reader: grey, grey + alpha, RGB, RGBA at 8 or 16 bits, every filter, into the caller's (H, W, C) uint16 array, row 0 at the bottom; the inflate serial, the unfiltering beside it on a second thread; a palette, interlace or another depth gives `-7` (not read here), a truncated or corrupt file `-5` with the file's name |
| `fss_ao_copy_read`, `fss_ao_copy_raster`, `fss_ao_copy_sum`, `fss_ao_png_test_limit` | test entry points: `read()`, `rasterize_ids`' owners, `np.add.reduce`; a writer that fails as on a full disk after a number of bytes |

The master (`fss_ao_master`) is the AO (uint16) and the map codes (int32, `(face + 1) * 2 + filled`) either as
open_master's page files (tiles of 256 px, memory-mapped read-only by `PagedArray.address`) or as row-major arrays
(`load_master`), plus the layout's corners, islands and rectangles and the mesh's triangle normals.
