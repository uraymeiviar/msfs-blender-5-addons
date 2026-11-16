// fss_ao_pixels: Apply's per-pixel work around the copy (see fss_ao_copy.h, interface version 4; apply-native-copy
// journal, Sessions 10 and 11): the raster of triangle owners (ao_bake_core.rasterize_ids and raster_window), the
// dilation of owners into the padding (dilate_ids) and the UV islands of a mesh (uv_islands).
//
// Every formula is the Python code's, with the same operations in the same order (float64, /fp:precise, no FMA), so
// the results are identical to it; threads split rows or pixels, never one result, so they do not depend on the
// thread count.

#include "fss_ao_copy.h"

#include <algorithm>
#include <atomic>
#include <cmath>
#include <new>
#include <thread>
#include <vector>

namespace {

const int64_t RASTER_ROWS = 8;  // grid rows per job of the raster
const int64_t DILATE_ROWS = 16; // rows per job of the dilation

// numpy's float64 -> int64 cast on x86-64 (cvttsd2si): truncation, NaN and out-of-range values give INT64_MIN
inline int64_t to_i64(double x) {
    if (!(x >= -9223372036854775808.0 && x < 9223372036854775808.0)) return INT64_MIN;
    return (int64_t)x;
}

// np.min / np.max of three values: NaN propagates
inline double nan_min3(double a, double b, double c) {
    if (a != a || b != b || c != c) return NAN;
    return std::min(std::min(a, b), c);
}
inline double nan_max3(double a, double b, double c) {
    if (a != a || b != b || c != c) return NAN;
    return std::max(std::max(a, b), c);
}

// Runs body(begin, end) over jobs of `per` items of n on up to `threads` threads; returns an error code.
template <class Body>
int32_t parallel_jobs(int64_t n, int64_t per, int64_t threads, Body body) {
    if (n <= 0) return FSS_AO_COPY_OK;
    const int64_t jobs = (n + per - 1) / per;
    const int64_t nt = std::max<int64_t>(1, std::min<int64_t>(threads, jobs));
    std::atomic<int64_t> next(0);
    std::atomic<int32_t> err(FSS_AO_COPY_OK);
    auto work = [&]() {
        try {
            for (;;) {
                int64_t j = next.fetch_add(1);
                if (j >= jobs || err.load() != FSS_AO_COPY_OK) break;
                body(j * per, std::min(n, (j + 1) * per));
            }
        } catch (const std::bad_alloc &) {
            err.store(FSS_AO_COPY_E_MEMORY);
        } catch (...) {
            err.store(FSS_AO_COPY_E_INTERNAL);
        }
    };
    if (nt == 1) {
        work();
        return err.load();
    }
    std::vector<std::thread> pool;
    try {
        pool.reserve((size_t)nt - 1);
        for (int64_t i = 1; i < nt; i++) pool.emplace_back(work);
    } catch (...) {
        err.store(FSS_AO_COPY_E_INTERNAL);
    }
    work();
    for (auto &th : pool) th.join();
    return err.load();
}

// A triangle of rasterize_ids: its corner a, edges v0 = b - a, v1 = c - a, d, and its clipped sample box
struct RTri {
    double ax, ay, v0x, v0y, v1x, v1y, d;
    int64_t sx0, sx1, sy0, sy1, t;
};

}  // namespace

extern "C" {

FSS_AO_COPY_API int32_t fss_ao_copy_raster_ids(const double *uvpx, int64_t n_tris, int64_t x0, int64_t y0, int64_t W,
                                               int64_t H, int64_t k, double eps, int64_t select, const int64_t *label,
                                               int64_t keep, int64_t threads, int64_t *owner, int32_t *count) {
    if (n_tris < 0 || (n_tris > 0 && !uvpx) || W < 0 || H < 0 || k < 1 || k > (int64_t(1) << 20) || !owner ||
        threads < 1 || threads > 1024)
        return FSS_AO_COPY_E_ARGS;
    if (W == 0 || H == 0) return FSS_AO_COPY_OK;
    const int64_t GW = W * k, GH = H * k;
    if (GW / k != W || GH / k != H || GW > (int64_t(1) << 40) / std::max<int64_t>(1, GH)) return FSS_AO_COPY_E_ARGS;
    try {
        const double Ld = (double)k;
        // the triangles rasterize_ids draws, in index order: raster_window's selection (tris_in_window, margin 1)
        // when asked, then the box of samples, then |d| >= 1e-30
        std::vector<RTri> tris;
        for (int64_t t = 0; t < n_tris; t++) {
            const double *u = uvpx + 6 * t;
            const double mnx = nan_min3(u[0], u[2], u[4]), mxx = nan_max3(u[0], u[2], u[4]);
            const double mny = nan_min3(u[1], u[3], u[5]), mxy = nan_max3(u[1], u[3], u[5]);
            if (select) {
                const double margin = 1.0;
                if (!(mxx >= (double)x0 - margin && mnx <= (double)(x0 + W) + margin && mxy >= (double)y0 - margin &&
                      mny <= (double)(y0 + H) + margin))
                    continue;
            }
            int64_t lox = to_i64(std::floor((mnx - (double)x0) * Ld - 0.5));
            int64_t loy = to_i64(std::floor((mny - (double)y0) * Ld - 0.5));
            int64_t hix = to_i64(std::ceil((mxx - (double)x0) * Ld - 0.5));
            int64_t hiy = to_i64(std::ceil((mxy - (double)y0) * Ld - 0.5));
            RTri r;
            r.sx0 = std::max<int64_t>(lox, 0);
            r.sy0 = std::max<int64_t>(loy, 0);
            r.sx1 = std::min<int64_t>(hix, GW - 1);
            r.sy1 = std::min<int64_t>(hiy, GH - 1);
            if (r.sx1 < r.sx0 || r.sy1 < r.sy0) continue;
            r.ax = u[0];
            r.ay = u[1];
            r.v0x = u[2] - u[0];
            r.v0y = u[3] - u[1];
            r.v1x = u[4] - u[0];
            r.v1y = u[5] - u[1];
            r.d = r.v0x * r.v1y - r.v0y * r.v1x;
            if (std::fabs(r.d) < 1e-30) continue;  // barycentric() returns None (NaN does not)
            r.t = t;
            tris.push_back(r);
        }
        if (tris.size() > (size_t)INT32_MAX) return FSS_AO_COPY_E_ARGS;
        // per job of RASTER_ROWS grid rows, the triangles whose rows reach it (ascending)
        const int64_t jobs = (GH + RASTER_ROWS - 1) / RASTER_ROWS;
        std::vector<int64_t> start((size_t)jobs + 1, 0);
        for (const RTri &r : tris)
            for (int64_t j = r.sy0 / RASTER_ROWS; j <= r.sy1 / RASTER_ROWS; j++) start[(size_t)j + 1]++;
        for (size_t j = 1; j < start.size(); j++) start[j] += start[j - 1];
        std::vector<int32_t> ids((size_t)start.back());
        {
            std::vector<int64_t> fill(start.begin(), start.end() - 1);
            for (size_t i = 0; i < tris.size(); i++)
                for (int64_t j = tris[i].sy0 / RASTER_ROWS; j <= tris[i].sy1 / RASTER_ROWS; j++)
                    ids[(size_t)fill[(size_t)j]++] = (int32_t)i;
        }
        const double meps = -eps;
        return parallel_jobs(GH, RASTER_ROWS, threads, [&](int64_t b0, int64_t b1) {
            const int64_t j = b0 / RASTER_ROWS;
            if (!keep) {
                for (int64_t b = b0; b < b1; b++) {
                    std::fill(owner + b * GW, owner + (b + 1) * GW, (int64_t)-1);
                    if (count) std::fill(count + b * GW, count + (b + 1) * GW, 0);
                }
            }
            for (int64_t i = start[(size_t)j]; i < start[(size_t)j + 1]; i++) {
                const RTri &r = tris[(size_t)ids[(size_t)i]];
                const int64_t rb0 = std::max(b0, r.sy0), rb1 = std::min(b1 - 1, r.sy1);
                const int64_t value = label ? label[r.t] : r.t;
                for (int64_t b = rb0; b <= rb1; b++) {
                    const double py = (double)y0 + ((double)b + 0.5) / Ld;
                    const double wy = py - r.ay;
                    int64_t *orow = owner + b * GW;
                    int32_t *crow = count ? count + b * GW : nullptr;
                    for (int64_t a = r.sx0; a <= r.sx1; a++) {
                        const double px = (double)x0 + ((double)a + 0.5) / Ld;
                        const double wx = px - r.ax;
                        const double l1 = (wx * r.v1y - wy * r.v1x) / r.d;
                        const double l2 = (r.v0x * wy - r.v0y * wx) / r.d;
                        const double l0 = 1.0 - l1 - l2;
                        if (l0 >= meps && l1 >= meps && l2 >= meps) {
                            orow[a] = value;
                            if (crow) crow[a] += 1;
                        }
                    }
                }
            }
        });
    } catch (const std::bad_alloc &) {
        return FSS_AO_COPY_E_MEMORY;
    } catch (...) {
        return FSS_AO_COPY_E_INTERNAL;
    }
}

FSS_AO_COPY_API int32_t fss_ao_copy_dilate(const int64_t *owner, int64_t W, int64_t H, int64_t iterations,
                                           const uint8_t *allowed, int64_t threads, int64_t *out_owner,
                                           int64_t *out_steps) {
    if (W < 0 || H < 0 || iterations < 0 || threads < 1 || threads > 1024) return FSS_AO_COPY_E_ARGS;
    if (W == 0 || H == 0) return FSS_AO_COPY_OK;
    if (!owner || !out_owner || !out_steps || W > (int64_t(1) << 40) / H) return FSS_AO_COPY_E_ARGS;
    int64_t *own = out_owner, *steps = out_steps;
    int32_t rc = parallel_jobs(H, DILATE_ROWS, threads, [&](int64_t y0, int64_t y1) {
        for (int64_t i = y0 * W; i < y1 * W; i++) {
            own[i] = owner[i];
            steps[i] = owner[i] >= 0 ? 0 : -1;
        }
    });
    if (rc != FSS_AO_COPY_OK) return rc;
    // dilate_ids' eight directions (dy, dx) in its order: the first neighbour that has an owner at the start of the
    // step gives it. A step in two passes: (1) each pixel without an owner (and allowed) finds its taker in `own`,
    // which this pass does not change, and keeps it in its own `steps` as -2 - owner; (2) those pixels take it.
    static const int64_t DY[8] = {0, 0, 1, -1, 1, 1, -1, -1};
    static const int64_t DX[8] = {1, -1, 0, 0, 1, -1, 1, -1};
    for (int64_t it = 1; it <= iterations; it++) {
        std::atomic<int64_t> grown(0);
        rc = parallel_jobs(H, DILATE_ROWS, threads, [&](int64_t y0, int64_t y1) {
            int64_t g = 0;
            for (int64_t y = y0; y < y1; y++)
                for (int64_t x = 0; x < W; x++) {
                    const int64_t i = y * W + x;
                    if (own[i] >= 0 || (allowed && !allowed[i])) continue;
                    for (int d = 0; d < 8; d++) {
                        const int64_t yy = y + DY[d], xx = x + DX[d];
                        if (yy < 0 || yy >= H || xx < 0 || xx >= W) continue;
                        const int64_t v = own[yy * W + xx];
                        if (v >= 0) {
                            steps[i] = -2 - v;
                            g++;
                            break;
                        }
                    }
                }
            grown.fetch_add(g);
        });
        if (rc != FSS_AO_COPY_OK) return rc;
        if (grown.load() == 0) break;  // nothing grew: the later steps change nothing either
        rc = parallel_jobs(H, DILATE_ROWS, threads, [&](int64_t y0, int64_t y1) {
            for (int64_t i = y0 * W; i < y1 * W; i++)
                if (steps[i] <= -2) {
                    own[i] = -2 - steps[i];
                    steps[i] = it;
                }
        });
        if (rc != FSS_AO_COPY_OK) return rc;
    }
    return FSS_AO_COPY_OK;
}

FSS_AO_COPY_API int32_t fss_ao_copy_uv_islands(const int64_t *wtris, const double *uv, int64_t n_tris, double tol,
                                               int64_t threads, int64_t *label) {
    if (n_tris < 0 || threads < 1 || threads > 1024) return FSS_AO_COPY_E_ARGS;
    if (n_tris == 0) return FSS_AO_COPY_OK;
    if (!wtris || !uv || !label) return FSS_AO_COPY_E_ARGS;
    try {
        // edge_map: per edge (welded ids sorted) its (t, i, j) in the order they were made; the edges in the order of
        // their first appearance (the dict's order)
        struct Item {
            int64_t a, b, seq;
        };
        const int64_t n_items = 3 * n_tris;
        std::vector<Item> items((size_t)n_items);
        static const int CI[3] = {0, 1, 2}, CJ[3] = {1, 2, 0};
        for (int64_t t = 0; t < n_tris; t++)
            for (int c = 0; c < 3; c++) {
                const int64_t va = wtris[3 * t + CI[c]], vb = wtris[3 * t + CJ[c]];
                Item &it = items[(size_t)(3 * t + c)];
                it.a = va < vb ? va : vb;
                it.b = va < vb ? vb : va;
                it.seq = 3 * t + c;
            }
        std::sort(items.begin(), items.end(), [](const Item &p, const Item &q) {
            if (p.a != q.a) return p.a < q.a;
            if (p.b != q.b) return p.b < q.b;
            return p.seq < q.seq;
        });
        struct Group {
            int64_t first, begin, end;  // first item's seq; [begin, end) into items
        };
        std::vector<Group> groups;
        for (int64_t i = 0; i < n_items;) {
            int64_t j = i + 1;
            while (j < n_items && items[(size_t)j].a == items[(size_t)i].a && items[(size_t)j].b == items[(size_t)i].b)
                j++;
            if (j - i >= 2) groups.push_back(Group{items[(size_t)i].seq, i, j});
            i = j;
        }
        std::sort(groups.begin(), groups.end(), [](const Group &p, const Group &q) { return p.first < q.first; });
        // the pairs t1 < t2 of each edge, in the loops' order, and whether their UVs agree at both ends
        struct Pair {
            int64_t s1, s2;  // seq of (t1, i1, j1) and (t2, i2, j2)
            uint8_t ok;
        };
        std::vector<Pair> pairs;
        for (const Group &g : groups)
            for (int64_t p = g.begin; p < g.end; p++)
                for (int64_t q = g.begin; q < g.end; q++) {
                    const int64_t s1 = items[(size_t)p].seq, s2 = items[(size_t)q].seq;
                    if (s2 / 3 <= s1 / 3) continue;
                    pairs.push_back(Pair{s1, s2, 0});
                }
        int32_t rc = parallel_jobs((int64_t)pairs.size(), 4096, threads, [&](int64_t b, int64_t e) {
            for (int64_t n = b; n < e; n++) {
                Pair &pr = pairs[(size_t)n];
                const int64_t t1 = pr.s1 / 3, i1 = CI[pr.s1 % 3], j1 = CJ[pr.s1 % 3];
                const int64_t t2 = pr.s2 / 3, i2 = CI[pr.s2 % 3], j2 = CJ[pr.s2 % 3];
                bool ok = true;
                const int64_t cs[2] = {i2, j2};
                for (int k = 0; k < 2; k++) {
                    const int64_t c = cs[k];
                    // ends1 = {wt[t1, i1]: uv[t1, i1], wt[t1, j1]: uv[t1, j1]} (the later key wins)
                    const int64_t corner = wtris[3 * t2 + c] == wtris[3 * t1 + j1] ? j1 : i1;
                    const double *e1 = uv + 6 * t1 + 2 * corner;
                    const double *e2 = uv + 6 * t2 + 2 * c;
                    const double d0 = std::fabs(e1[0] - e2[0]), d1 = std::fabs(e1[1] - e2[1]);
                    // np.max propagates NaN, and NaN > tol is False
                    if (!(d0 != d0 || d1 != d1) && (d0 > tol || d1 > tol)) ok = false;
                }
                pr.ok = ok ? 1 : 0;
            }
        });
        if (rc != FSS_AO_COPY_OK) return rc;
        std::vector<int64_t> parent((size_t)n_tris);
        for (int64_t i = 0; i < n_tris; i++) parent[(size_t)i] = i;
        auto find = [&](int64_t x) {
            while (parent[(size_t)x] != x) {
                parent[(size_t)x] = parent[(size_t)parent[(size_t)x]];
                x = parent[(size_t)x];
            }
            return x;
        };
        for (const Pair &pr : pairs) {
            if (!pr.ok) continue;
            const int64_t a = find(pr.s1 / 3), b = find(pr.s2 / 3);
            if (a != b) parent[(size_t)a] = b;
        }
        // np.unique(roots, return_inverse=True): each triangle's root ranked among the roots
        std::vector<int64_t> roots((size_t)n_tris);
        for (int64_t i = 0; i < n_tris; i++) roots[(size_t)i] = find(i);
        std::vector<int64_t> rank((size_t)n_tris, 0);
        for (int64_t i = 0; i < n_tris; i++) rank[(size_t)roots[(size_t)i]] = 1;
        int64_t r = 0;
        for (int64_t i = 0; i < n_tris; i++)
            if (rank[(size_t)i]) rank[(size_t)i] = r++;
        for (int64_t i = 0; i < n_tris; i++) label[i] = rank[(size_t)roots[(size_t)i]];
    } catch (const std::bad_alloc &) {
        return FSS_AO_COPY_E_MEMORY;
    } catch (...) {
        return FSS_AO_COPY_E_INTERNAL;
    }
    return FSS_AO_COPY_OK;
}

}  // extern "C"
