// fss_uv_pack: the raster placement of UV islands (C interface, loaded with ctypes by fss_blender_tools/uv_fill.py).
#pragma once

#include <cstdint>

#ifdef _WIN32
#define FSS_UV_API __declspec(dllexport)
#else
#define FSS_UV_API __attribute__((visibility("default")))
#endif

#define FSS_UV_PACK_VERSION 1

extern "C" {

// The interface version (FSS_UV_PACK_VERSION).
FSS_UV_API int32_t fss_uv_pack_version(void);

// uv_fill.spans + solid_mask: the cells k triangles T (k x 3 x 2, in cells, not negative) touch, as an h x w mask
// written to out when it holds capacity bytes. Returns 1, 0 when out is too small (h and w set), -1 on an error.
FSS_UV_API int32_t fss_uv_solid(const double *T, int64_t k, uint8_t *out, int64_t capacity, int64_t *h, int64_t *w);

// uv_fill._place_once. tri: the triangles grouped per island (pixels, 6 doubles each), island i's are start[i] to
// start[i + 1]; lo: each island's low corner (n x 2); order: the islands to place, in that order; can_turn per island;
// reach: the reach table; grid_cells: the raster's side asked for; fixed_ids: islands painted where they are first.
// Writes turns and offset (n x 2) of the placed islands. Returns 1, 0 when an island fits nowhere, -1 on an error.
FSS_UV_API int32_t fss_uv_place_once(const double *tri, const int64_t *start, int64_t n, const double *lo,
                                     const int64_t *order, int64_t n_order, const uint8_t *can_turn, double gap,
                                     double cell, const int32_t *reach, int64_t n_reach, int64_t grid_cells,
                                     const int64_t *fixed_ids, int64_t n_fixed, int32_t *turns, double *offset);

// The work of uv_fill.repair after its setup. inside (n) is updated (an island too close to a fixed one is no longer
// inside). Writes moved, turns and offset of the islands placed inside, and left (n_left of them): the islands that fit
// nowhere, in the order tried. Returns 1, 2 when no island is outside after the fixed ones were painted (nothing
// written), -1 on an error.
FSS_UV_API int32_t fss_uv_repair(const double *tri, const int64_t *start, int64_t n, const double *lo,
                                 const double *key, uint8_t *inside, const uint8_t *fixed, const uint8_t *active,
                                 const uint8_t *can_turn, double gap, double cell, const int32_t *reach,
                                 int64_t n_reach, int64_t half, double lim_x, double lim_y, uint8_t *moved,
                                 int32_t *turns, double *offset, int64_t *left, int64_t *n_left);
}
