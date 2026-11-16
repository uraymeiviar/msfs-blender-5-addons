/* fss_ao_copy: the per-pixel work of AO Bake's Apply copy (fss_blender_tools/ao_bake_core.py, copy_master) in C++,
 * the opening of a master into its tiled page files (open_master; fss_ao_open.cpp), PNG files written on several
 * threads and read (PngRowWriter, read_png; fss_ao_png.cpp), the bake's composition of a master and its .ao.map
 * writer (compose_block, MapRowWriter; fss_ao_compose.cpp), and Refresh's scene rule geometry and mesh hash
 * (ao_bake_store's near and moves_against, ao_bake_core.mesh_hash; fss_ao_scene.cpp).
 *
 * Plain C interface, loaded with ctypes (fss_blender_tools/ao_bake_copy.py). The caller owns every buffer; the
 * library allocates only internally (freed before each call returns), throws nothing across the boundary, keeps no
 * global state, and its results do not depend on the thread count. Float64 throughout, the same operations in the
 * same order as the numpy copy, so the results are bit-identical to it (apply-native-copy journal, Session 2).
 *
 * Coordinates: target pixels (X, Y) are integers, pixel (X, Y) spans X..X+1, Y..Y+1; master pixel (x, y) has its
 * centre at (x + 0.5, y + 0.5); arrays are row-major [y][x] (row 0 at the bottom, as in the add-on).
 */
#ifndef FSS_AO_COPY_H
#define FSS_AO_COPY_H

#include <stdint.h>
#include <wchar.h>

#ifdef _WIN32
#define FSS_AO_COPY_API __declspec(dllexport)
#else
#define FSS_AO_COPY_API
#endif

#ifdef __cplusplus
extern "C" {
#endif

#define FSS_AO_COPY_VERSION 6

#define FSS_AO_COPY_OK 0
#define FSS_AO_COPY_E_ARGS (-1)     /* a null pointer, a size or a level out of range */
#define FSS_AO_COPY_E_MEMORY (-2)   /* an internal allocation failed */
#define FSS_AO_COPY_E_INTERNAL (-3) /* anything else (a thread could not start) */
#define FSS_AO_COPY_E_IO (-4)       /* a file could not be opened, read, created, sized or mapped (a full disk) */
#define FSS_AO_COPY_E_FORMAT (-5)   /* a file truncated or corrupt, or its size not the layout's */
#define FSS_AO_COPY_E_LIBRARY (-6)  /* libjxl could not be loaded from the folder given */
#define FSS_AO_COPY_E_UNSUPPORTED (-7) /* a PNG this library does not read (a palette, interlace, another depth) */
#define FSS_AO_COPY_E_SPACE (-8)    /* an output buffer too small: the size it needs is returned */

#define FSS_AO_COPY_MAX_LEVEL 64 /* sub-samples per pixel axis at most */

/* The master as copy_master reads it. Every field is 8 bytes (no padding between fields). */
typedef struct fss_ao_master {
    int64_t W, H;             /* master size, px */
    int64_t tile;             /* 0: image and code row-major (H, W); else square tiles of `tile` px (a power of two),
                                 tile (ty, tx) at index ty * tiles_x + tx, its pixels row-major (open_master's page
                                 files) */
    int64_t tiles_x;          /* tiles per row (tile > 0) */
    const uint16_t *image;    /* the AO, 0..65535 */
    const int32_t *code;      /* the map codes: (face + 1) * 2 + filled */
    const double *muv;        /* (n_tris, 3, 2) master px of each triangle's corners */
    const int64_t *island;    /* (n_tris) island of each triangle (-1: none) */
    const int64_t *rects;     /* (n_rects, 4) island rectangles x, y, w, h */
    int64_t n_rects;
    const double *tri_normal; /* (n_tris, 3) unit normals */
    int64_t n_tris;
    double surface_cos;       /* surface != 0: texels of faces whose normal is within this cosine count */
    int64_t surface;          /* 1: the surface-aware bilinear read (_surface_bilinear); 0: plain bilinear */
} fss_ao_master;

/* The library's version (FSS_AO_COPY_VERSION). */
FSS_AO_COPY_API int32_t fss_ao_copy_version(void);

/* Inside pixels (copy_master's inside_step, outside_mode 'tri'): for each pixel n, at target pixel px[2n], px[2n+1]
 * with owner triangle owner[n] (indices into uvpx and the master's triangles) and level[n] = L: the L x L sub-samples,
 * those whose owner (the last triangle covering them, rasterize_ids on the grid of L x L samples per pixel that starts
 * at the pixel origin[2n], origin[2n+1] of the pixel's group) is owner[n] read from the master and averaged; none:
 * the value at the pixel's centre. uvpx: (master->n_tris, 3, 2) target px. out[n]: the value; *clamped: the number of
 * sub-samples whose read was clamped (info['clamped_inside_points']). threads: 1 to 1024. */
FSS_AO_COPY_API int32_t fss_ao_copy_inside(const fss_ao_master *master, const double *uvpx, int64_t n_px,
                                           const int64_t *px, const int64_t *owner, const int64_t *level,
                                           const int64_t *origin, int64_t threads, double *out, int64_t *clamped);

/* Padding pixels: for each pixel n at target pixel px[2n], px[2n+1], the L x L points (L = level[n]) of the pixel in
 * the UV triangle tri_uv[n] (3 x 2 target px), their barycentrics clamped onto it and renormalized, read on the
 * master's triangle src[n], averaged. *clamped: the points whose read was clamped. */
FSS_AO_COPY_API int32_t fss_ao_copy_padding(const fss_ao_master *master, int64_t n_px, const int64_t *px,
                                            const int64_t *src, const double *tri_uv, const int64_t *level,
                                            int64_t threads, double *out, int64_t *clamped);

/* Apply's per-pixel work around the copy (interface version 4, apply-native-copy journal Sessions 10 and 11; source in
 * fss_ao_pixels.cpp and, for Soften, fss_ao_copy.cpp). Each equals the Python function it replaces bit for bit, for
 * any thread count (threads 1 to 1024; threads split rows or pixels, never one result). */

/* rasterize_ids(uvpx, W, H, k, x0, y0, eps): the owner (the last triangle whose integer sample box contains the sample
 * and whose barycentrics are all at least -eps) of each of the (H * k) x (W * k) samples of the grid of W x H target
 * pixels from pixel (x0, y0), k x k samples per pixel at (x0 + (a + 0.5) / k, y0 + (b + 0.5) / k); count: how many
 * triangles cover each sample. uvpx: (n_tris, 3, 2) target px. select 1: only the triangles raster_window takes
 * (tris_in_window, a margin of 1 px), which gives the same owners and counts. label null: owner gets the triangle's
 * index; else label[t]. keep 0: owner set to -1 and count to 0 first; keep 1: only the covered samples written and
 * count added to (island_labels' merge of several meshes). count may be null. owner, count: row-major, row 0 at y0. */
FSS_AO_COPY_API int32_t fss_ao_copy_raster_ids(const double *uvpx, int64_t n_tris, int64_t x0, int64_t y0, int64_t W,
                                               int64_t H, int64_t k, double eps, int64_t select, const int64_t *label,
                                               int64_t keep, int64_t threads, int64_t *owner, int32_t *count);

/* dilate_ids(owner, iterations, allowed): owners (>= 0) grown into the pixels without one (< 0) by `iterations`
 * 8-neighbour steps, the directions in dilate_ids' order (the first that has an owner at the start of the step gives
 * it); allowed (H x W, 0 or 1) may be null. out_owner: the owners; out_steps: 0 where an owner was, the step at which
 * one came, -1 where none came. Every array H x W row-major. */
FSS_AO_COPY_API int32_t fss_ao_copy_dilate(const int64_t *owner, int64_t W, int64_t H, int64_t iterations,
                                           const uint8_t *allowed, int64_t threads, int64_t *out_owner,
                                           int64_t *out_steps);

/* uv_islands(wtris, uv, tol): the island label (0 ..) of each triangle; triangles sharing an edge (welded vertex ids
 * wtris, (n_tris, 3)) whose UVs (uv, (n_tris, 3, 2)) agree within tol at both ends are in one island. The same
 * union-find in the same order as the Python code (the edges in the order of their first appearance), the labels the
 * roots ranked (np.unique). The union-find is serial; threads compare the UVs of the edge pairs. */
FSS_AO_COPY_API int32_t fss_ao_copy_uv_islands(const int64_t *wtris, const double *uv, int64_t n_tris, double tol,
                                               int64_t threads, int64_t *label);

/* The folds of Soften Sharp Edges (ao_bake_core.soften_context). Every field 8 bytes. */
typedef struct fss_ao_soften {
    int64_t n_edges;
    const int64_t *E;      /* (n_edges, 6): t1, i1, j1, t2, iy, jy (the two faces and their corners at the edge) */
    const double *A;       /* (n_edges, 3) the edge's ends */
    const double *B;
    const double *mX;      /* (n_edges, 3) each face's direction away from the edge, in its plane */
    const double *mY;
    const double *hX;      /* (n_edges) each face's height over the edge */
    const double *hY;
    const uint8_t *convex; /* (n_edges) 1: convex */
    int64_t n_tris;        /* the master's n_tris */
    const int64_t *start;  /* (n_tris + 1) each triangle's candidates: cand[start[t] .. start[t + 1]) */
    const int64_t *cand;   /* edges */
    const double *Wt;      /* (n_tris) the width each triangle softens over, m */
    int64_t n_verts;
    const double *pos;     /* (n_verts, 3) */
    const int64_t *tris;   /* (n_tris, 3) */
    double surface_cos;    /* _soften's surface_cos */
} fss_ao_soften;

/* _soften(sc, tri_ids, P3, vals, read, tri_normal, surface_cos): the n values vals at points P3 (n, 3) on triangles
 * tri_ids softened near the folds, the master read as copy_master's read() (fss_ao_copy_read) with the master's
 * tri_normal; out[n] the values, *changed the points changed. Its (1 - x) ** 3 is the pow of ucrtbase.dll, the C
 * runtime numpy calls (the static runtime's pow differs from it in the last bit), loaded from System32 for the call:
 * FSS_AO_COPY_E_LIBRARY when it cannot be. */
FSS_AO_COPY_API int32_t fss_ao_copy_soften(const fss_ao_master *master, const fss_ao_soften *soften, int64_t n,
                                           const int64_t *tri_ids, const double *P3, const double *vals,
                                           int64_t threads, double *out, int64_t *changed);

/* The bake's post-processing (interface version 5, bake-post-native journal; source in fss_ao_compose.cpp). */

/* A master's layout as compose_block reads it (ao_bake_core.build_master's dict). Every field 8 bytes. */
typedef struct fss_ao_compose_layout {
    int64_t fill;              /* FILL: the steps of the nearest fill and of the face map's growth */
    int64_t corner_excess;     /* int(CORNER_EXCESS * 65535): the corner rule's excess in 16-bit values */
    const int64_t *rects;      /* (n_rects, 4) island rectangles x, y, w, h */
    int64_t n_rects;
    const double *core_uv;     /* (n_core, 3, 2) master px: muv[core_tris] */
    const int64_t *core_face;  /* (n_core) core_tris */
    int64_t n_core;
    const double *skirt_uv;    /* (n_skirt, 3, 2) master px */
    const int64_t *skirt_face; /* (n_skirt) skirt_src */
    int64_t n_skirt;           /* 0 when the master has no skirt */
    const int64_t *corner;     /* (n_corner, 4) the corner rule's pairs cy, cx, iy, ix, sorted by cy */
    int64_t n_corner;
} fss_ao_compose_layout;

/* compose_block(m, M16e, baked_e, ex0, ey0, (x0, y0, w, h)): the composition of the window x0, y0, w, h of a master
 * from the block of ew x eh px around it whose bottom-left pixel is (ex0, ey0): values (uint16) and baked (0 or 1) of
 * the block, row-major with row strides in elements, row 0 at ey0. The corner rule, the nearest fill of FILL steps
 * inside the rectangles, the face map (core faces, then skirt faces inside rectangles, grown FILL steps inside
 * rectangles); out (h x w, row stride out_stride elements): out_values, and when not null out_filled (0 or 1),
 * out_face (-1 for none) and out_code ((face + 1) * 2 + filled, the .ao.map's code); counts[4]: nearest_fill_px,
 * rect_px_unfilled, rect_px, corner_px. Equal to the Python code for any thread count (threads 1 to 1024: a team for
 * the call splits rows). */
FSS_AO_COPY_API int32_t fss_ao_compose_block(const fss_ao_compose_layout *layout, const uint16_t *values,
                                             int64_t values_stride, const uint8_t *baked, int64_t baked_stride,
                                             int64_t ex0, int64_t ey0, int64_t ew, int64_t eh, int64_t x0, int64_t y0,
                                             int64_t w, int64_t h, int64_t threads, uint16_t *out_values,
                                             uint8_t *out_filled, int32_t *out_face, int32_t *out_code,
                                             int64_t out_stride, int64_t *counts);

/* What a map writer did (every field 8 bytes). */
typedef struct fss_ao_map_stats {
    double seconds;         /* open to close */
    double wait_seconds;    /* time write() waited for room in the queue */
    double deflate_seconds; /* time in deflate and the file's writes */
    int64_t threads;        /* 1: compressed on a thread beside the caller; 0: in the caller */
    int64_t raw_bytes;      /* the rows' bytes */
    int64_t file_bytes;     /* the file */
} fss_ao_map_stats;

typedef struct fss_ao_map_writer fss_ao_map_writer; /* opaque; freed by fss_ao_map_close or fss_ao_map_abort */

/* A master's .ao.map (ao_bake_core.MapRowWriter) created at path (replaced if there): "FSSAOMAP", then version 1, W, H
 * and 0 as little-endian uint32, then one zlib stream (deflateInit2 at `level`, a 32 KiB window, memLevel 8, the
 * default strategy: zlib.compressobj(level)) of the H rows of W int32 codes from the top, compressed with Z_NO_FLUSH
 * as they come and finished at close. threads 2 or more: on one thread beside the caller (write() copies the rows and
 * returns, waiting while 3 writes are queued); 1: in write() itself. message (UTF-8) gets the reason of an error. */
FSS_AO_COPY_API int32_t fss_ao_map_open(const wchar_t *path, int64_t W, int64_t H, int64_t level, int64_t threads,
                                        fss_ao_map_writer **writer, char *message, int64_t message_size);

/* n rows in file order (the top first), each W int32 codes; row r at rows + r * stride (stride in elements, may be
 * negative). On an error the file is closed and removed; the handle stays until close or abort. */
FSS_AO_COPY_API int32_t fss_ao_map_write(fss_ao_map_writer *writer, const int32_t *rows, int64_t n, int64_t stride,
                                         char *message, int64_t message_size);

/* The queued rows compressed, the stream finished, the file closed. An error (fewer rows than H, a write that failed):
 * the file removed. The handle is freed in every case. stats may be null. */
FSS_AO_COPY_API int32_t fss_ao_map_close(fss_ao_map_writer *writer, fss_ao_map_stats *stats, char *message,
                                         int64_t message_size);

/* Stopped, closed and removed; the handle freed. */
FSS_AO_COPY_API void fss_ao_map_abort(fss_ao_map_writer *writer);

/* Refresh's scene rule (interface version 6, bake-post-native journal Sessions 4 and 5; source in fss_ao_scene.cpp):
 * ao_bake_store._rule_tools' near and moves_against, many objects in one call, with numpy's order of operations (the
 * same keep or drop as the Python code; gaps equal to it but for rounding). Threads split the objects or pairs. */

/* One Refresh pass's candidates (every field 8 bytes): motion()'s rows. */
typedef struct fss_ao_scene {
    int64_t n_rows;          /* the candidates */
    int64_t n_poses;         /* 1 + the sampled frames (motion()'s M.shape[1]) */
    const double *M;         /* (n_rows, n_poses, 4, 4) world matrices, pose 0 the current frame */
    const uint8_t *moving;   /* (n_rows) motion()'s moving */
    const double *now;       /* (n_rows, 4, 4) matrix_world after motion() (the world boxes now) */
    const double *corners;   /* (n_rows, 8, 3) bound_box, object space */
    int64_t n_occ;           /* the occluders */
    const int64_t *occ_rows; /* (n_occ) their rows, in the order of their names */
    double ortho_tol;        /* ORTHO_TOL: axes further from square have no own box */
    double motion_tol;       /* MOTION_TOL */
} fss_ao_scene;

/* What fss_ao_scene_near decided, for the report of near cases (every field 8 bytes). */
typedef struct fss_ao_near_stats {
    double closest_world; /* the smallest |world-box gap - distance| of every occluder tested */
    double closest_own;   /* the smallest |own-box gap - distance| */
    int64_t within;       /* tests whose gap lay within 1e-9 m of the distance */
    int64_t world_tests;  /* (object, occluder) world-box tests */
    int64_t own_tests;    /* own-box tests (the smallest over the poses counted once) */
} fss_ao_near_stats;

/* near(obj, which, distance, gaps) for n objects: row rows[q], which[q] 0 'now' (the world boxes now, the own boxes at
 * the current frame), 1 'swept' (a moving object's world box over its poses; the own boxes at each pose, the smallest
 * gap counting, unless the object and every occluder whose world box is near are still), the distance, self_occ[q]
 * its index among the occluders or -1. Out: the occluders kept for object q are out_occ[offsets[q] .. offsets[q + 1])
 * (indices among the occluders, in their order) with their gaps out_gap (decision 70: the larger of the world-box
 * and own-box gaps, m); offsets has n + 1 entries. FSS_AO_COPY_E_SPACE when offsets[n] > capacity (offsets set, call
 * again with that capacity). stats may be null. */
FSS_AO_COPY_API int32_t fss_ao_scene_near(const fss_ao_scene *scene, int64_t n, const int64_t *rows,
                                          const int64_t *which, const double *distance, const int64_t *self_occ,
                                          int64_t threads, int64_t *offsets, int64_t *out_occ, double *out_gap,
                                          int64_t capacity, fss_ao_near_stats *stats);

/* moves_against for n pairs (rows a = pairs[2k], b = pairs[2k + 1]): out[k] 1 when one of them moves and b's placement
 * relative to a at the current frame (inv(M[a, 0]) @ M[b, 0]) differs at some pose by more than motion_tol. inv:
 * (n_rows, 4, 4), numpy's np.linalg.inv of M[a, 0] at every row a of a pair where a or b moves (other rows not read).
 * *closest (may be null): the smallest |largest difference - motion_tol| of the pairs that move. */
FSS_AO_COPY_API int32_t fss_ao_scene_moves(const fss_ao_scene *scene, int64_t n, const int64_t *pairs,
                                           const double *inv, int64_t threads, uint8_t *out, double *closest);

/* Tests: oriented_boxes_at(lo, hi, mats) of n boxes (lo, hi (n, 3), mats (n, 4, 4)): centres (n, 3), unit axes as
 * columns (n, 3, 3), half sizes (n, 3), ok (n). */
FSS_AO_COPY_API int32_t fss_ao_scene_boxes(int64_t n, const double *lo, const double *hi, const double *mats,
                                           double ortho_tol, double *centres, double *axes, double *halves,
                                           uint8_t *ok);

/* Tests: oriented_gaps((centre, axes, halves), centres, others, other_halves) of k boxes into out (k). */
FSS_AO_COPY_API int32_t fss_ao_scene_gaps(const double *centre, const double *axes, const double *halves, int64_t k,
                                          const double *centres, const double *others, const double *other_halves,
                                          double *out);

/* mesh_hash(ev) (decision 17): SHA-1 of the n_tris int64 vertex ids as int32, the n_co float64 positions as float32
 * and the n_cn float64 corner normals rounded as np.round(x, 4) + 0.0, as float32, one stream; digest: its 20 bytes.
 * threads: the corner normals converted on threads. impl 0: the SHA instructions where the CPU has them, else plain
 * C++; 1: plain C++; 2: the SHA instructions (FSS_AO_COPY_E_UNSUPPORTED without them). The same digest by each. */
FSS_AO_COPY_API int32_t fss_ao_mesh_hash(const int64_t *tris, int64_t n_tris, const double *co, int64_t n_co,
                                         const double *cn, int64_t n_cn, int64_t threads, int64_t impl,
                                         uint8_t *digest);

/* Tests: copy_master's read() of n points (triangle tri[n], barycentrics bary[3n..3n+2]) into out[n]; clamped[n] 1
 * where the point was clamped into its island. */
FSS_AO_COPY_API int32_t fss_ao_copy_read(const fss_ao_master *master, int64_t n, const int64_t *tri,
                                         const double *bary, double *out, uint8_t *clamped);

/* Tests: rasterize_ids' owners on a grid of gw x gh pixels from target pixel (gx, gy), L x L samples per pixel:
 * owner[(gh * L) x (gw * L)], -1 where no triangle covers a sample, else the last covering triangle. */
FSS_AO_COPY_API int32_t fss_ao_copy_raster(const double *uvpx, int64_t n_tris, int64_t gx, int64_t gy, int64_t gw,
                                           int64_t gh, int64_t level, int64_t *owner);

/* Tests: numpy's np.add.reduce of a contiguous float64 array (pairwise summation) as this library computes it. */
FSS_AO_COPY_API double fss_ao_copy_sum(const double *a, int64_t n);

/* What fss_ao_copy_open_master did (every field 8 bytes). */
typedef struct fss_ao_open_stats {
    double seconds;          /* the whole call */
    double image_seconds;    /* the JPEG XL decoded into its page file */
    double map_seconds;      /* the .ao.map inflated into its page file */
    int64_t decode_threads;  /* libjxl's runner threads */
    int64_t threads;         /* threads busy at a time in all (the runner's and the map's) */
    int64_t most_open_tile_rows; /* rows of tiles of the image's page file mapped at a time at most */
} fss_ao_open_stats;

/* Opening a master for Apply (ao_bake_core.open_master, apply-native-copy journal Session 4): the image `image` (a
 * 16-bit grey JPEG XL of W x H px) decoded by libjxl (jxl.dll and jxl_threads.dll loaded from the folder jxl_dir)
 * with its thread runner and a multithreaded image-out callback, and the map `map` (.ao.map: "FSSAOMAP", version, W,
 * H, 0 as little-endian uint32, then one zlib stream of H rows of W int32 codes from the top) inflated, each into a
 * tiled page file: page_image (uint16) and page_map (int32), created with FILE_ATTRIBUTE_TEMPORARY, square tiles of
 * `tile` px (a power of two), tile (ty, tx) at index ty * ntx + tx, its pixels row-major, array row 0 at the bottom,
 * zeros outside the image: byte for byte the files of open_master's Python code. The files are filled through
 * mappings of one row of tiles at a time, unmapped and closed before the call returns; on an error both are removed.
 * threads: 1 to 1024 in all; above 1 the map runs beside the decode on one of them. stats may be null. message (UTF-8,
 * message_size bytes with its 0) gets the reason of an error, with the file's path. */
FSS_AO_COPY_API int32_t fss_ao_copy_open_master(const wchar_t *jxl_dir, const wchar_t *image, const wchar_t *map,
                                                const wchar_t *page_image, const wchar_t *page_map, int64_t W,
                                                int64_t H, int64_t tile, int64_t threads, fss_ao_open_stats *stats,
                                                char *message, int64_t message_size);

/* PNG files (apply-native-copy journal, Session 7). */

/* What a PNG writer or reader did (every field 8 bytes). */
typedef struct fss_ao_png_stats {
    double seconds;         /* writer: open to close; reader: the whole read */
    double wait_seconds;    /* writer: time write() waited for room in the queue; reader: time the inflate waited
                               for a free batch of rows */
    int64_t threads;        /* writer: compressing threads; reader: 1, or 2 with the unfiltering beside the inflate */
    int64_t blocks;         /* writer: compressed blocks; reader: batches of rows */
    int64_t most_in_flight; /* writer: blocks queued or being compressed at a time at most */
    int64_t raw_bytes;      /* the filtered stream (filter bytes and rows) */
    int64_t file_bytes;     /* the file */
} fss_ao_png_stats;

typedef struct fss_ao_png_writer fss_ao_png_writer; /* opaque; freed by fss_ao_png_close or fss_ao_png_abort */

/* A PNG of W x H px, bits 8 or 16, channels 1 to 4 (grey, grey + alpha, RGB, RGBA), created at path (replaced if
 * there): signature, IHDR, filter 0 on every row, IDAT chunks, IEND; one zlib stream at level 6. The filtered stream
 * is cut into blocks of 512 KiB at fixed offsets, each compressed on one of `threads` worker threads (1 or more; at most
 * 64 blocks in flight, so at most 64 compress at a time) with the 32 KiB before it as its dictionary, ended with a sync
 * flush, the last one finished (the method of pigz). The file's bytes depend only on the pixels, not on the thread
 * count or on how the rows are handed in. *writer: the handle (null on an error, nothing created or left). message
 * (UTF-8, message_size bytes with its 0) gets the reason of an error, with the file's path. */
FSS_AO_COPY_API int32_t fss_ao_png_open(const wchar_t *path, int64_t W, int64_t H, int64_t bits, int64_t channels,
                                        int64_t threads, fss_ao_png_writer **writer, char *message,
                                        int64_t message_size);

/* n rows in file order (the top first): n x W x channels unsigned integers of the file's depth (uint8 or uint16 in
 * the machine's byte order), contiguous. Copied into the current block; a full block is queued (this waits while the
 * queue is full). On an error the file is closed and removed; the handle stays until close or abort. */
FSS_AO_COPY_API int32_t fss_ao_png_write(fss_ao_png_writer *writer, const void *rows, int64_t n, char *message,
                                         int64_t message_size);

/* The last block, then IEND; the file closed. An error (fewer rows than H, a write that failed, a full disk): the file
 * removed. The handle is freed in every case. stats may be null. */
FSS_AO_COPY_API int32_t fss_ao_png_close(fss_ao_png_writer *writer, fss_ao_png_stats *stats, char *message,
                                         int64_t message_size);

/* Stopped, closed and removed; the handle freed. */
FSS_AO_COPY_API void fss_ao_png_abort(fss_ao_png_writer *writer);

/* Tests: the writer fails as on a full disk once the file would exceed `bytes` (-1: no limit). */
FSS_AO_COPY_API int32_t fss_ao_png_test_limit(fss_ao_png_writer *writer, int64_t bytes);

/* A PNG read into out (H x W x channels uint16 values in the file's depth, row 0 at the bottom): grey, grey + alpha,
 * RGB or RGBA, 8 or 16 bits, not interlaced, every filter (None, Sub, Up, Average, Paeth). W, H, channels and bits
 * are the file's (from its header; another value gives FSS_AO_COPY_E_ARGS). The inflate is serial; with threads 2 or
 * more the unfiltering runs beside it. FSS_AO_COPY_E_UNSUPPORTED: a palette, interlace or another depth;
 * FSS_AO_COPY_E_FORMAT: not a PNG, truncated, a corrupt zlib stream, a bad filter type. stats may be null. */
FSS_AO_COPY_API int32_t fss_ao_png_read(const wchar_t *path, int64_t W, int64_t H, int64_t channels, int64_t bits,
                                        uint16_t *out, int64_t threads, fss_ao_png_stats *stats, char *message,
                                        int64_t message_size);

#ifdef __cplusplus
}
#endif

#endif
