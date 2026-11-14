/* fss_ao_copy: the per-pixel work of AO Bake's Apply copy (fss_blender_tools/ao_bake_core.py, copy_master) in C++.
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

#ifdef _WIN32
#define FSS_AO_COPY_API __declspec(dllexport)
#else
#define FSS_AO_COPY_API
#endif

#ifdef __cplusplus
extern "C" {
#endif

#define FSS_AO_COPY_VERSION 1

#define FSS_AO_COPY_OK 0
#define FSS_AO_COPY_E_ARGS (-1)     /* a null pointer, a size or a level out of range */
#define FSS_AO_COPY_E_MEMORY (-2)   /* an internal allocation failed */
#define FSS_AO_COPY_E_INTERNAL (-3) /* anything else (a thread could not start) */

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
 * sub-samples whose read was clamped (info['clamped_inside_points']). threads: 1 to 64. */
FSS_AO_COPY_API int32_t fss_ao_copy_inside(const fss_ao_master *master, const double *uvpx, int64_t n_px,
                                           const int64_t *px, const int64_t *owner, const int64_t *level,
                                           const int64_t *origin, int64_t threads, double *out, int64_t *clamped);

/* Padding pixels: for each pixel n at target pixel px[2n], px[2n+1], the L x L points (L = level[n]) of the pixel in
 * the UV triangle tri_uv[n] (3 x 2 target px), their barycentrics clamped onto it and renormalized, read on the
 * master's triangle src[n], averaged. *clamped: the points whose read was clamped. */
FSS_AO_COPY_API int32_t fss_ao_copy_padding(const fss_ao_master *master, int64_t n_px, const int64_t *px,
                                            const int64_t *src, const double *tri_uv, const int64_t *level,
                                            int64_t threads, double *out, int64_t *clamped);

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

#ifdef __cplusplus
}
#endif

#endif
