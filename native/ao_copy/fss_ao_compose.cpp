// fss_ao_compose: the bake's post-processing (see fss_ao_compose_* and fss_ao_map_* in fss_ao_copy.h, interface version
// 5; bake-post-native journal, Session 1).
//
// fss_ao_compose_block is ao_bake_core.compose_block for one window: the corner rule (corner_fix), the island
// rectangles (rect_window), the nearest fill inside each rectangle (dilate_ids of the baked pixels' indices, FILL steps,
// the mask in_rect, a source of the same rectangle), the face map (rasterize_ids of the core triangles, then of the
// skirt's inside the rectangles, grown FILL steps inside the rectangles) and the counts. Integer work but the raster,
// whose formulas are fss_ao_copy_raster_ids' (bit-identical to rasterize_ids); so the window's values, flags, faces
// and counts equal the Python code's. The window's work runs on a team of threads made for the call: they split rows,
// never one pixel's result, and meet at a barrier between the steps, so the result does not depend on the thread count.
//
// The dilation is dilate_ids' rule computed by its frontier: in step s a pixel without an owner (and allowed) takes the
// owner of its first neighbour, in dilate_ids' order of the eight directions, that had one at the start of the step;
// such a neighbour got its owner in step s - 1 (or the pixel would have taken one earlier), so after the first step
// (a scan of every pixel) only the neighbours of the pixels that grew in the step before are looked at. The owner a
// pixel takes is the same as dilate_ids gives it; only the pixels visited differ.
//
// fss_ao_map_* write a master's .ao.map (MapRowWriter): the header, then one zlib stream at the level given of the
// rows handed in, compressed with Z_NO_FLUSH on a thread beside the caller (or in the caller at threads 1).

#include "fss_ao_copy.h"

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <deque>
#include <memory>
#include <mutex>
#include <new>
#include <string>
#include <thread>
#include <vector>

#include "../third_party/zlib/zlib.h"

namespace {

const int64_t ROWS = 8;            // rows of a window per job
const int64_t MIN_PX_PER_THREAD = 16384;  // a window of fewer pixels per thread takes fewer threads (not the result)
const int64_t MAX_FILL = 1 << 20;  // FILL steps at most

// numpy's float64 -> int64 cast on x86-64 (cvttsd2si): truncation, NaN and out-of-range values give INT64_MIN
inline int64_t to_i64(double x) {
    if (!(x >= -9223372036854775808.0 && x < 9223372036854775808.0)) return INT64_MIN;
    return (int64_t)x;
}
inline double nan_min3(double a, double b, double c) {
    if (a != a || b != b || c != c) return NAN;
    return std::min(std::min(a, b), c);
}
inline double nan_max3(double a, double b, double c) {
    if (a != a || b != b || c != c) return NAN;
    return std::max(std::max(a, b), c);
}

// An array of n values, not initialized (the team fills it row by row)
template <class T>
struct Buffer {
    std::unique_ptr<T[]> p;
    explicit Buffer(int64_t n) : p(new T[(size_t)std::max<int64_t>(n, 1)]) {}
    T *data() { return p.get(); }
    const T *data() const { return p.get(); }
    T &operator[](size_t i) { return p[i]; }
    const T &operator[](size_t i) const { return p[i]; }
};

// A barrier for the team of one call
class Barrier {
  public:
    void set_size(int64_t n) { n_ = n; }
    void sync() {
        if (n_ <= 1) return;
        std::unique_lock<std::mutex> lock(mu_);
        const int64_t g = gen_;
        if (++count_ == n_) {
            count_ = 0;
            ++gen_;
            cv_.notify_all();
        } else {
            cv_.wait(lock, [&] { return gen_ != g; });
        }
    }

  private:
    std::mutex mu_;
    std::condition_variable cv_;
    int64_t n_ = 1, count_ = 0, gen_ = 0;
};

// Runs body(tid, nt) on up to `want` threads (the caller is one): nt is the team's size, the threads that started.
// body must reach every barrier.sync() the others reach.
template <class Body>
void run_team(int64_t want, Barrier &barrier, Body body) {
    std::vector<std::thread> pool;
    std::mutex mu;
    std::condition_variable cv;
    bool go = false;
    int64_t nt = 1;
    try {
        pool.reserve((size_t)std::max<int64_t>(0, want - 1));
        for (int64_t i = 1; i < want; i++)
            pool.emplace_back([&, i]() {
                {
                    std::unique_lock<std::mutex> lock(mu);
                    cv.wait(lock, [&] { return go; });
                }
                body(i, nt);
            });
    } catch (...) {
        // fewer threads: the team is the ones that started
    }
    {
        std::lock_guard<std::mutex> lock(mu);
        nt = (int64_t)pool.size() + 1;
        barrier.set_size(nt);
        go = true;
    }
    cv.notify_all();
    body(0, nt);
    for (auto &th : pool) th.join();
}

// A triangle of rasterize_ids (fss_ao_copy_raster_ids' RTri): its corner a, edges v0 = b - a, v1 = c - a, d, its
// clipped sample box and its face
struct RTri {
    double ax, ay, v0x, v0y, v1x, v1y, d;
    int64_t sx0, sx1, sy0, sy1, face;
};

// The triangles raster_window(uv, ew, eh, 1, ex0, ey0) draws, in index order (tris_in_window with a margin of 1 px,
// the sample box, |d| >= 1e-30), each with face[t]; and per job of ROWS rows the triangles that reach it
struct Raster {
    std::vector<RTri> tris;
    std::vector<int64_t> start;
    std::vector<int32_t> ids;

    void build(const double *uv, const int64_t *face, int64_t n, int64_t ex0, int64_t ey0, int64_t ew, int64_t eh,
               int64_t jobs) {
        const double margin = 1.0;
        for (int64_t t = 0; t < n; t++) {
            const double *u = uv + 6 * t;
            const double mnx = nan_min3(u[0], u[2], u[4]), mxx = nan_max3(u[0], u[2], u[4]);
            const double mny = nan_min3(u[1], u[3], u[5]), mxy = nan_max3(u[1], u[3], u[5]);
            if (!(mxx >= (double)ex0 - margin && mnx <= (double)(ex0 + ew) + margin && mxy >= (double)ey0 - margin &&
                  mny <= (double)(ey0 + eh) + margin))
                continue;
            const int64_t lox = to_i64(std::floor((mnx - (double)ex0) * 1.0 - 0.5));
            const int64_t loy = to_i64(std::floor((mny - (double)ey0) * 1.0 - 0.5));
            const int64_t hix = to_i64(std::ceil((mxx - (double)ex0) * 1.0 - 0.5));
            const int64_t hiy = to_i64(std::ceil((mxy - (double)ey0) * 1.0 - 0.5));
            RTri r;
            r.sx0 = std::max<int64_t>(lox, 0);
            r.sy0 = std::max<int64_t>(loy, 0);
            r.sx1 = std::min<int64_t>(hix, ew - 1);
            r.sy1 = std::min<int64_t>(hiy, eh - 1);
            if (r.sx1 < r.sx0 || r.sy1 < r.sy0) continue;
            r.ax = u[0];
            r.ay = u[1];
            r.v0x = u[2] - u[0];
            r.v0y = u[3] - u[1];
            r.v1x = u[4] - u[0];
            r.v1y = u[5] - u[1];
            r.d = r.v0x * r.v1y - r.v0y * r.v1x;
            if (std::fabs(r.d) < 1e-30) continue;  // barycentric() returns None (NaN does not)
            r.face = face[t];
            tris.push_back(r);
        }
        start.assign((size_t)jobs + 1, 0);
        for (const RTri &r : tris)
            for (int64_t j = r.sy0 / ROWS; j <= r.sy1 / ROWS; j++) start[(size_t)j + 1]++;
        for (size_t j = 1; j < start.size(); j++) start[j] += start[j - 1];
        ids.assign((size_t)start.back(), 0);
        std::vector<int64_t> fill(start.begin(), start.end() - 1);
        for (size_t i = 0; i < tris.size(); i++)
            for (int64_t j = tris[i].sy0 / ROWS; j <= tris[i].sy1 / ROWS; j++)
                ids[(size_t)fill[(size_t)j]++] = (int32_t)i;
    }

    // rows b0..b1 (of job j) of out (ew per row): the last covering triangle's face; out's rows set to -1 first
    void draw(int64_t j, int64_t b0, int64_t b1, int64_t ex0, int64_t ey0, int64_t ew, int32_t *out) const {
        std::fill(out + b0 * ew, out + b1 * ew, (int32_t)-1);
        const double meps = -1e-9;
        for (int64_t i = start[(size_t)j]; i < start[(size_t)j + 1]; i++) {
            const RTri &r = tris[(size_t)ids[(size_t)i]];
            const int64_t rb0 = std::max(b0, r.sy0), rb1 = std::min(b1 - 1, r.sy1);
            const int32_t value = (int32_t)r.face;
            for (int64_t b = rb0; b <= rb1; b++) {
                const double py = (double)ey0 + ((double)b + 0.5) / 1.0;
                const double wy = py - r.ay;
                int32_t *row = out + b * ew;
                for (int64_t a = r.sx0; a <= r.sx1; a++) {
                    const double px = (double)ex0 + ((double)a + 0.5) / 1.0;
                    const double wx = px - r.ax;
                    const double l1 = (wx * r.v1y - wy * r.v1x) / r.d;
                    const double l2 = (r.v0x * wy - r.v0y * wx) / r.d;
                    const double l0 = 1.0 - l1 - l2;
                    if (l0 >= meps && l1 >= meps && l2 >= meps) row[a] = value;
                }
            }
        }
    }
};

// dilate_ids(own, iterations, mask_allowed=rid >= 0) on a team, in place: own (ew x eh, int32 indices >= 0 or -1),
// pend all -1 (left so). jobs of ROWS rows; tid takes jobs tid, tid + nt, ...
struct Dilation {
    int64_t ew = 0, eh = 0, jobs = 0, iterations = 0;
    const int32_t *rid = nullptr;
    int32_t *own = nullptr, *pend = nullptr;
    std::vector<std::vector<int32_t>> cur, nxt;  // per job: its pixels that grew in the step before / in this step
    std::vector<int64_t> grown;                  // per step and thread: the pixels that grew
    std::atomic<bool> *failed = nullptr;

    void setup(int64_t ew_, int64_t eh_, int64_t jobs_, int64_t iterations_, const int32_t *rid_, int32_t *own_,
               int32_t *pend_, int64_t nt, std::atomic<bool> *failed_) {
        ew = ew_;
        eh = eh_;
        jobs = jobs_;
        iterations = iterations_;
        rid = rid_;
        own = own_;
        pend = pend_;
        failed = failed_;
        cur.assign((size_t)jobs, std::vector<int32_t>());
        nxt.assign((size_t)jobs, std::vector<int32_t>());
        grown.assign((size_t)(iterations + 1) * (size_t)nt, 0);
    }

    // the first neighbour in dilate_ids' order with an owner, or -1
    inline int32_t taker(int64_t y, int64_t x) const {
        static const int64_t DY[8] = {0, 0, 1, -1, 1, 1, -1, -1};
        static const int64_t DX[8] = {1, -1, 0, 0, 1, -1, 1, -1};
        for (int d = 0; d < 8; d++) {
            const int64_t yy = y + DY[d], xx = x + DX[d];
            if (yy < 0 || yy >= eh || xx < 0 || xx >= ew) continue;
            const int32_t v = own[yy * ew + xx];
            if (v >= 0) return v;
        }
        return -1;
    }

    void run(Barrier &barrier, int64_t tid, int64_t nt) {
        for (int64_t it = 1; it <= iterations; it++) {
            int64_t g = 0;
            for (int64_t j = tid; j < jobs; j += nt) {
                const int64_t b0 = j * ROWS, b1 = std::min(eh, b0 + ROWS);
                std::vector<int32_t> &out = nxt[(size_t)j];
                try {
                    out.clear();
                    if (it == 1) {
                        for (int64_t y = b0; y < b1; y++)
                            for (int64_t x = 0; x < ew; x++) {
                                const int64_t i = y * ew + x;
                                if (own[i] >= 0 || rid[i] < 0) continue;
                                const int32_t v = taker(y, x);
                                if (v >= 0) {
                                    pend[i] = v;
                                    out.push_back((int32_t)i);
                                }
                            }
                    } else {
                        // the neighbours in rows b0..b1 of the pixels that grew in the step before (jobs j - 1 to j + 1)
                        for (int64_t k = std::max<int64_t>(0, j - 1); k <= std::min(jobs - 1, j + 1); k++) {
                            for (const int32_t f : cur[(size_t)k]) {
                                const int64_t fy = f / ew, fx = f % ew;
                                if (fy < b0 - 1 || fy > b1) continue;
                                for (int64_t yy = std::max(fy - 1, b0); yy <= std::min(fy + 1, b1 - 1); yy++)
                                    for (int64_t xx = std::max<int64_t>(fx - 1, 0); xx <= std::min(fx + 1, ew - 1);
                                         xx++) {
                                        const int64_t i = yy * ew + xx;
                                        if (own[i] >= 0 || rid[i] < 0 || pend[i] >= 0) continue;
                                        const int32_t v = taker(yy, xx);
                                        if (v >= 0) {
                                            pend[i] = v;
                                            out.push_back((int32_t)i);
                                        }
                                    }
                            }
                        }
                    }
                } catch (...) {
                    failed->store(true);
                    out.clear();
                }
                g += (int64_t)out.size();
            }
            grown[(size_t)it * (size_t)nt + (size_t)tid] = g;
            barrier.sync();
            int64_t total = 0;
            for (int64_t t = 0; t < nt; t++) total += grown[(size_t)it * (size_t)nt + (size_t)t];
            if (total == 0) return;  // nothing grew: the later steps change nothing either (every thread returns here)
            for (int64_t j = tid; j < jobs; j += nt) {
                std::vector<int32_t> &out = nxt[(size_t)j];
                for (const int32_t i : out) {
                    own[i] = pend[i];
                    pend[i] = -1;
                }
                cur[(size_t)j].swap(out);
            }
            barrier.sync();
        }
    }
};

}  // namespace

extern "C" {

FSS_AO_COPY_API int32_t fss_ao_compose_block(const fss_ao_compose_layout *L, const uint16_t *values,
                                             int64_t values_stride, const uint8_t *baked, int64_t baked_stride,
                                             int64_t ex0, int64_t ey0, int64_t ew, int64_t eh, int64_t x0, int64_t y0,
                                             int64_t w, int64_t h, int64_t threads, uint16_t *out_values,
                                             uint8_t *out_filled, int32_t *out_face, int32_t *out_code,
                                             int64_t out_stride, int64_t *counts) {
    if (!L || !counts || threads < 1 || threads > 1024 || ew < 0 || eh < 0 || w < 0 || h < 0 || L->fill < 0 ||
        L->fill > MAX_FILL || L->n_rects < 0 || L->n_core < 0 || L->n_skirt < 0 || L->n_corner < 0)
        return FSS_AO_COPY_E_ARGS;
    for (int k = 0; k < 4; k++) counts[k] = 0;
    if (w == 0 || h == 0) return FSS_AO_COPY_OK;
    // the window inside the block
    const int64_t wx = x0 - ex0, wy = y0 - ey0;
    if (wx < 0 || wy < 0 || wx + w > ew || wy + h > eh || !values || !baked || !out_values || out_stride < w ||
        values_stride < ew || baked_stride < ew || ew * eh > (int64_t)INT32_MAX ||
        (L->n_rects && !L->rects) || (L->n_core && (!L->core_uv || !L->core_face)) ||
        (L->n_skirt && (!L->skirt_uv || !L->skirt_face)) || (L->n_corner && !L->corner))
        return FSS_AO_COPY_E_ARGS;
    try {
        const int64_t N = ew * eh;
        const int64_t jobs = (eh + ROWS - 1) / ROWS;
        // the values, the corner rule applied (decision 57; against the values as baked: one pass, in no order)
        Buffer<uint16_t> M(N);
        for (int64_t y = 0; y < eh; y++) std::memcpy(M.data() + y * ew, values + y * values_stride, (size_t)ew * 2);
        int64_t n_corner = 0;
        if (L->n_corner) {
            const int64_t *P = L->corner;  // (n, 4): cy, cx, iy, ix, sorted by cy
            int64_t a = 0, b = L->n_corner;
            {  // np.searchsorted(cy, ey0) and (cy, ey0 + eh), side left
                int64_t lo = 0, hi = L->n_corner;
                while (lo < hi) {
                    const int64_t mid = (lo + hi) / 2;
                    if (P[4 * mid] < ey0) lo = mid + 1; else hi = mid;
                }
                a = lo;
                lo = a;
                hi = L->n_corner;
                while (lo < hi) {
                    const int64_t mid = (lo + hi) / 2;
                    if (P[4 * mid] < ey0 + eh) lo = mid + 1; else hi = mid;
                }
                b = lo;
            }
            std::vector<int64_t> inside;
            const int64_t excess = L->corner_excess;
            for (int64_t p = a; p < b; p++) {
                const int64_t cy = P[4 * p] - ey0, cx = P[4 * p + 1] - ex0, iy = P[4 * p + 2] - ey0,
                              ix = P[4 * p + 3] - ex0;
                if (!(cx >= 0 && cx < ew && iy >= 0 && iy < eh && ix >= 0 && ix < ew)) continue;
                if (!(baked[cy * baked_stride + cx] && baked[iy * baked_stride + ix])) continue;
                const int64_t vc = values[cy * values_stride + cx], vi = values[iy * values_stride + ix];
                if (!(vc - vi > excess)) continue;
                uint16_t &o = M[(size_t)(cy * ew + cx)];
                if ((uint16_t)vi < o) o = (uint16_t)vi;
                if (cx + ex0 >= x0 && cx + ex0 < x0 + w && cy + ey0 >= y0 && cy + ey0 < y0 + h)
                    inside.push_back(cy * ew + cx);
            }
            std::sort(inside.begin(), inside.end());
            n_corner = (int64_t)(std::unique(inside.begin(), inside.end()) - inside.begin());
        }
        // the rectangles that reach the block, in index order (rect_window: a later one wins)
        struct Rect {
            int64_t i, x0, y0, x1, y1;
        };
        std::vector<Rect> rects;
        for (int64_t i = 0; i < L->n_rects; i++) {
            const int64_t *r = L->rects + 4 * i;
            const int64_t ax0 = std::max(r[0], ex0), ay0 = std::max(r[1], ey0);
            const int64_t ax1 = std::min(r[0] + r[2], ex0 + ew), ay1 = std::min(r[1] + r[3], ey0 + eh);
            if (ax1 > ax0 && ay1 > ay0) rects.push_back(Rect{i, ax0 - ex0, ay0 - ey0, ax1 - ex0, ay1 - ey0});
        }
        Raster core, skirt;
        core.build(L->core_uv, L->core_face, L->n_core, ex0, ey0, ew, eh, jobs);
        skirt.build(L->skirt_uv, L->skirt_face, L->n_skirt, ex0, ey0, ew, eh, jobs);
        // not initialized here: the team's first step sets rid, own and pend, the raster face and sk, row by row
        Buffer<int32_t> rid(N), own(N), pend(N), face(N), sk(L->n_skirt ? N : 1);
        Buffer<uint8_t> filled(w * h);
        const int64_t want = std::max<int64_t>(1, std::min({threads, jobs, std::max<int64_t>(1, N / MIN_PX_PER_THREAD)}));
        std::vector<int64_t> part((size_t)want * 3, 0);
        std::atomic<bool> failed(false);
        Barrier barrier;
        Dilation d1, d2;
        d1.setup(ew, eh, jobs, L->fill, rid.data(), own.data(), pend.data(), want, &failed);
        d2.setup(ew, eh, jobs, L->fill, rid.data(), own.data(), pend.data(), want, &failed);
        run_team(want, barrier, [&](int64_t tid, int64_t nt) {
            // the rectangle id of each pixel; the baked pixels' indices
            for (int64_t j = tid; j < jobs; j += nt) {
                const int64_t b0 = j * ROWS, b1 = std::min(eh, b0 + ROWS);
                std::fill(rid.data() + b0 * ew, rid.data() + b1 * ew, (int32_t)-1);
                for (const Rect &r : rects) {
                    const int64_t r0 = std::max(r.y0, b0), r1 = std::min(r.y1, b1);
                    for (int64_t y = r0; y < r1; y++)
                        std::fill(rid.data() + y * ew + r.x0, rid.data() + y * ew + r.x1, (int32_t)r.i);
                }
                for (int64_t y = b0; y < b1; y++) {
                    const uint8_t *bk = baked + y * baked_stride;
                    int32_t *o = own.data() + y * ew;
                    for (int64_t x = 0; x < ew; x++) o[x] = bk[x] ? (int32_t)(y * ew + x) : -1;
                }
                std::fill(pend.data() + b0 * ew, pend.data() + b1 * ew, (int32_t)-1);
            }
            barrier.sync();
            // the nearest fill: the baked pixels' indices grown FILL steps inside the rectangles
            d1.run(barrier, tid, nt);
            // the window's values, filled flags and counts; the face map of the core, then the skirt's inside the
            // rectangles; the face pixels' indices for the second dilation
            int64_t n_fill = 0, n_rect = 0, n_unfilled = 0;
            for (int64_t j = tid; j < jobs; j += nt) {
                const int64_t b0 = j * ROWS, b1 = std::min(eh, b0 + ROWS);
                for (int64_t y = std::max(b0, wy); y < std::min(b1, wy + h); y++) {
                    uint16_t *ov = out_values + (y - wy) * out_stride;
                    uint8_t *of = filled.data() + (y - wy) * w;
                    for (int64_t x = wx; x < wx + w; x++) {
                        const int64_t i = y * ew + x;
                        const bool bk = baked[y * baked_stride + x] != 0;
                        const int32_t g = own[(size_t)i];
                        const int32_t r = rid[(size_t)i];
                        const bool fm = !bk && g >= 0 && rid[(size_t)g] == r;
                        ov[x - wx] = fm ? M[(size_t)g] : M[(size_t)i];
                        const bool fl = bk || fm;
                        of[x - wx] = fl ? 1 : 0;
                        n_fill += fm ? 1 : 0;
                        if (r >= 0) {
                            n_rect++;
                            if (!fl) n_unfilled++;
                        }
                    }
                }
                core.draw(j, b0, b1, ex0, ey0, ew, face.data());
                if (L->n_skirt) {
                    skirt.draw(j, b0, b1, ex0, ey0, ew, sk.data());
                    for (int64_t i = b0 * ew; i < b1 * ew; i++)
                        if (face[(size_t)i] < 0 && sk[(size_t)i] >= 0 && rid[(size_t)i] >= 0) face[(size_t)i] = sk[(size_t)i];
                }
                for (int64_t i = b0 * ew; i < b1 * ew; i++) own[(size_t)i] = face[(size_t)i] >= 0 ? (int32_t)i : -1;
            }
            part[(size_t)tid * 3] = n_fill;
            part[(size_t)tid * 3 + 1] = n_unfilled;
            part[(size_t)tid * 3 + 2] = n_rect;
            barrier.sync();
            // the face map grown FILL steps inside the rectangles
            d2.run(barrier, tid, nt);
            for (int64_t j = tid; j < jobs; j += nt) {
                const int64_t b0 = j * ROWS, b1 = std::min(eh, b0 + ROWS);
                for (int64_t y = std::max(b0, wy); y < std::min(b1, wy + h); y++) {
                    const uint8_t *of = filled.data() + (y - wy) * w;
                    for (int64_t x = wx; x < wx + w; x++) {
                        const int64_t i = y * ew + x;
                        int32_t f = face[(size_t)i];
                        if (f < 0 && own[(size_t)i] >= 0) f = face[(size_t)own[(size_t)i]];
                        const int64_t o = (y - wy) * out_stride + (x - wx);
                        if (out_face) out_face[o] = f;
                        if (out_filled) out_filled[o] = of[x - wx];
                        if (out_code) out_code[o] = (int32_t)(((int64_t)f + 1) * 2 + (int64_t)of[x - wx]);
                    }
                }
            }
        });
        if (failed.load()) return FSS_AO_COPY_E_MEMORY;
        for (int64_t t = 0; t < want; t++) {
            counts[0] += part[(size_t)t * 3];
            counts[1] += part[(size_t)t * 3 + 1];
            counts[2] += part[(size_t)t * 3 + 2];
        }
        counts[3] = n_corner;
    } catch (const std::bad_alloc &) {
        return FSS_AO_COPY_E_MEMORY;
    } catch (...) {
        return FSS_AO_COPY_E_INTERNAL;
    }
    return FSS_AO_COPY_OK;
}

}  // extern "C"

// ---------------------------------------------------------------------------------------------------------------------
// The .ao.map writer
// ---------------------------------------------------------------------------------------------------------------------

namespace {

const int64_t MAP_QUEUE = 3;  // blocks of rows waiting at most (each one write's rows)
const size_t OUT_CHUNK = (size_t)1 << 20;

std::string utf8(const std::wstring &w) {
    if (w.empty()) return std::string();
    int n = WideCharToMultiByte(CP_UTF8, 0, w.c_str(), (int)w.size(), nullptr, 0, nullptr, nullptr);
    std::string s((size_t)std::max(n, 0), '\0');
    if (n > 0) WideCharToMultiByte(CP_UTF8, 0, w.c_str(), (int)w.size(), &s[0], n, nullptr, nullptr);
    return s;
}

std::string win_error(DWORD e) {
    char buf[256] = {0};
    DWORD n = FormatMessageA(FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS, nullptr, e, 0, buf,
                             (DWORD)sizeof(buf), nullptr);
    while (n && (buf[n - 1] == '\n' || buf[n - 1] == '\r' || buf[n - 1] == ' ' || buf[n - 1] == '.')) buf[--n] = 0;
    char out[320];
    std::snprintf(out, sizeof(out), "%s (Windows error %lu)", n ? buf : "error", (unsigned long)e);
    return out;
}

std::string fmt(const char *f, ...) {
    char buf[1024];
    va_list ap;
    va_start(ap, f);
    std::vsnprintf(buf, sizeof(buf), f, ap);
    va_end(ap);
    return buf;
}

double now() {
    return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();
}

void message_out(char *message, int64_t size, const std::string &text) {
    if (!message || size <= 0) return;
    size_t n = std::min<size_t>(text.size(), (size_t)(size - 1));
    while (n > 0 && n < text.size() && ((unsigned char)text[n] & 0xC0) == 0x80) n--;
    std::memcpy(message, text.data(), n);
    message[n] = 0;
}

void put_le32(uint8_t *p, uint32_t v) {
    p[0] = (uint8_t)v;
    p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16);
    p[3] = (uint8_t)(v >> 24);
}

}  // namespace

struct fss_ao_map_writer {
    std::wstring path;
    std::string name;
    HANDLE file = INVALID_HANDLE_VALUE;
    bool created = false, closed = false, zinit = false;
    int64_t W = 0, H = 0, rows_in = 0, threads = 1, raw_bytes = 0, file_bytes = 0;
    double t0 = 0, wait_seconds = 0, deflate_seconds = 0;
    z_stream zs;
    std::vector<uint8_t> out;
    // the worker (threads >= 2)
    std::mutex mu;
    std::condition_variable cv_work, cv_space;
    std::deque<std::vector<uint8_t>> todo;
    int64_t inflight = 0;  // blocks queued or being compressed
    bool stop = false;
    std::thread worker;
    std::mutex fail_mu;
    std::atomic<bool> failed{false};
    int32_t code = FSS_AO_COPY_OK;
    std::string text;

    void fail(int32_t c, const std::string &t) {
        std::lock_guard<std::mutex> lock(fail_mu);
        if (code == FSS_AO_COPY_OK) {
            code = c;
            text = t;
        }
        failed.store(true);
    }

    bool raw_write(const uint8_t *p, size_t n) {
        size_t done = 0;
        while (done < n) {
            DWORD want = (DWORD)std::min<size_t>(n - done, (size_t)1 << 30), got = 0;
            if (!WriteFile(file, p + done, want, &got, nullptr) || got == 0) {
                fail(FSS_AO_COPY_E_IO, name + ": not written: " + win_error(GetLastError()));
                return false;
            }
            done += got;
        }
        file_bytes += (int64_t)n;
        return true;
    }

    // one block through deflate (Z_NO_FLUSH, or Z_FINISH for the end), its output written
    void deflate_block(const uint8_t *data, size_t n, bool finish) {
        const double t = now();
        zs.next_in = const_cast<Bytef *>(data);
        zs.avail_in = 0;
        size_t left = n;
        for (;;) {
            if (zs.avail_in == 0 && left) {
                const size_t k = std::min<size_t>(left, (size_t)1 << 30);
                zs.avail_in = (uInt)k;
                left -= k;
            }
            zs.next_out = out.data();
            zs.avail_out = (uInt)out.size();
            const int flush = (finish && left == 0) ? Z_FINISH : Z_NO_FLUSH;
            const int rc = deflate(&zs, flush);
            if (rc == Z_STREAM_ERROR) {
                fail(FSS_AO_COPY_E_INTERNAL, name + ": deflate failed");
                return;
            }
            const size_t have = out.size() - zs.avail_out;
            if (have && !raw_write(out.data(), have)) return;
            if (flush == Z_FINISH) {
                if (rc == Z_STREAM_END) break;
            } else if (zs.avail_in == 0 && left == 0 && zs.avail_out != 0) {
                break;
            }
        }
        deflate_seconds += now() - t;
    }

    void work() {
        for (;;) {
            std::vector<uint8_t> block;
            {
                std::unique_lock<std::mutex> lock(mu);
                cv_work.wait(lock, [&] { return stop || !todo.empty(); });
                if (todo.empty()) break;
                block.swap(todo.front());
                todo.pop_front();
            }
            if (!failed.load()) {
                try {
                    deflate_block(block.data(), block.size(), false);
                } catch (...) {
                    fail(FSS_AO_COPY_E_INTERNAL, name + ": internal error");
                }
            }
            std::vector<uint8_t>().swap(block);
            {
                std::lock_guard<std::mutex> lock(mu);
                inflight--;
            }
            cv_space.notify_all();
        }
    }

    void stop_worker() {
        if (!worker.joinable()) return;
        {
            std::lock_guard<std::mutex> lock(mu);
            stop = true;
        }
        cv_work.notify_all();
        worker.join();
    }

    void finish(bool remove) {
        stop_worker();
        if (zinit) deflateEnd(&zs);
        zinit = false;
        if (file != INVALID_HANDLE_VALUE) CloseHandle(file);
        file = INVALID_HANDLE_VALUE;
        if (remove && created) DeleteFileW(path.c_str());
        created = false;
        closed = true;
    }
};

extern "C" {

FSS_AO_COPY_API int32_t fss_ao_map_open(const wchar_t *path, int64_t W, int64_t H, int64_t level, int64_t threads,
                                        fss_ao_map_writer **writer, char *message, int64_t message_size) {
    if (message && message_size > 0) message[0] = 0;
    if (writer) *writer = nullptr;
    if (!path || !writer || W < 0 || H < 0 || W > 0xffffffffLL || H > 0xffffffffLL || level < -1 || level > 9 ||
        threads < 1 || threads > 1024) {
        message_out(message, message_size, "fss_ao_map_open: bad arguments");
        return FSS_AO_COPY_E_ARGS;
    }
    fss_ao_map_writer *w = nullptr;
    try {
        w = new fss_ao_map_writer();
        std::memset(&w->zs, 0, sizeof(w->zs));
        w->t0 = now();
        w->path = path;
        w->name = utf8(w->path);
        w->W = W;
        w->H = H;
        w->threads = threads;
        w->out.assign(OUT_CHUNK, 0);
        // zlib.compressobj(level): deflate, a 32 KiB window, memLevel 8, the default strategy
        if (deflateInit2(&w->zs, (int)level, Z_DEFLATED, MAX_WBITS, 8, Z_DEFAULT_STRATEGY) != Z_OK) {
            w->fail(FSS_AO_COPY_E_MEMORY, w->name + ": zlib's deflate not initialized");
        } else {
            w->zinit = true;
            w->file = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ, nullptr, CREATE_ALWAYS,
                                  FILE_ATTRIBUTE_NORMAL | FILE_FLAG_SEQUENTIAL_SCAN, nullptr);
            if (w->file == INVALID_HANDLE_VALUE) {
                w->fail(FSS_AO_COPY_E_IO, w->name + ": not created: " + win_error(GetLastError()));
            } else {
                w->created = true;
                uint8_t head[24];
                std::memcpy(head, "FSSAOMAP", 8);
                put_le32(head + 8, 1);  // MAP_VERSION
                put_le32(head + 12, (uint32_t)W);
                put_le32(head + 16, (uint32_t)H);
                put_le32(head + 20, 0);
                if (w->raw_write(head, sizeof(head)) && threads >= 2) w->worker = std::thread(&fss_ao_map_writer::work, w);
            }
        }
    } catch (const std::bad_alloc &) {
        if (w) w->fail(FSS_AO_COPY_E_MEMORY, "out of memory");
    } catch (...) {
        if (w) w->fail(FSS_AO_COPY_E_INTERNAL, w->name + ": a thread did not start");
    }
    if (!w) {
        message_out(message, message_size, "out of memory");
        return FSS_AO_COPY_E_MEMORY;
    }
    if (w->failed.load()) {
        const int32_t rc = w->code;
        const std::string text = w->text;
        w->finish(true);
        delete w;
        message_out(message, message_size, text);
        return rc;
    }
    *writer = w;
    return FSS_AO_COPY_OK;
}

FSS_AO_COPY_API int32_t fss_ao_map_write(fss_ao_map_writer *w, const int32_t *rows, int64_t n, int64_t stride,
                                         char *message, int64_t message_size) {
    if (message && message_size > 0) message[0] = 0;
    if (!w || n < 0 || (n > 0 && w->W > 0 && !rows)) {
        message_out(message, message_size, "fss_ao_map_write: bad arguments");
        return FSS_AO_COPY_E_ARGS;
    }
    if (!w->closed && !w->failed.load() && n > 0) {
        try {
            if (w->rows_in + n > w->H) {
                w->fail(FSS_AO_COPY_E_ARGS, fmt("%s: %lld rows handed in, the map has %lld", w->name.c_str(),
                                                (long long)(w->rows_in + n), (long long)w->H));
            } else {
                const size_t rowb = (size_t)w->W * 4;
                std::vector<uint8_t> block(rowb * (size_t)n);
                if (rowb)
                    for (int64_t r = 0; r < n; r++)
                        std::memcpy(block.data() + rowb * (size_t)r, rows + r * stride, rowb);  // little-endian int32
                w->rows_in += n;
                w->raw_bytes += (int64_t)block.size();
                if (w->worker.joinable()) {
                    {
                        std::unique_lock<std::mutex> lock(w->mu);
                        if (w->inflight >= MAP_QUEUE && !w->failed.load()) {
                            const double t = now();
                            w->cv_space.wait(lock, [&] { return w->inflight < MAP_QUEUE || w->failed.load(); });
                            w->wait_seconds += now() - t;
                        }
                        w->inflight++;
                        w->todo.push_back(std::move(block));
                    }
                    w->cv_work.notify_one();
                } else {
                    w->deflate_block(block.data(), block.size(), false);
                }
            }
        } catch (const std::bad_alloc &) {
            w->fail(FSS_AO_COPY_E_MEMORY, w->name + ": out of memory");
        } catch (...) {
            w->fail(FSS_AO_COPY_E_INTERNAL, w->name + ": internal error");
        }
    }
    if (w->failed.load()) {
        if (!w->closed) w->finish(true);
        message_out(message, message_size, w->text);
        return w->code;
    }
    return FSS_AO_COPY_OK;
}

FSS_AO_COPY_API int32_t fss_ao_map_close(fss_ao_map_writer *w, fss_ao_map_stats *stats, char *message,
                                         int64_t message_size) {
    if (message && message_size > 0) message[0] = 0;
    if (stats) std::memset(stats, 0, sizeof(*stats));
    if (!w) {
        message_out(message, message_size, "fss_ao_map_close: bad arguments");
        return FSS_AO_COPY_E_ARGS;
    }
    try {
        if (!w->closed && !w->failed.load()) {
            w->stop_worker();  // the queued blocks compressed first
            if (!w->failed.load()) {
                if (w->rows_in != w->H) {
                    w->fail(FSS_AO_COPY_E_ARGS, fmt("%s: %lld of %lld rows written", w->name.c_str(),
                                                    (long long)w->rows_in, (long long)w->H));
                } else {
                    w->deflate_block(nullptr, 0, true);
                }
            }
        }
    } catch (const std::bad_alloc &) {
        w->fail(FSS_AO_COPY_E_MEMORY, w->name + ": out of memory");
    } catch (...) {
        w->fail(FSS_AO_COPY_E_INTERNAL, w->name + ": internal error");
    }
    if (!w->closed) {
        if (!w->failed.load() && w->file != INVALID_HANDLE_VALUE) {
            HANDLE f = w->file;
            w->file = INVALID_HANDLE_VALUE;
            if (!CloseHandle(f)) w->fail(FSS_AO_COPY_E_IO, w->name + ": not closed: " + win_error(GetLastError()));
        }
        w->finish(w->failed.load());
    }
    int32_t rc = FSS_AO_COPY_OK;
    if (w->failed.load()) {
        rc = w->code;
        message_out(message, message_size, w->text);
    }
    if (stats) {
        stats->seconds = now() - w->t0;
        stats->wait_seconds = w->wait_seconds;
        stats->deflate_seconds = w->deflate_seconds;
        stats->threads = w->threads >= 2 ? 1 : 0;
        stats->raw_bytes = w->raw_bytes;
        stats->file_bytes = w->file_bytes;
    }
    delete w;
    return rc;
}

FSS_AO_COPY_API void fss_ao_map_abort(fss_ao_map_writer *w) {
    if (!w) return;
    try {
        w->fail(FSS_AO_COPY_E_INTERNAL, w->name + ": aborted");
        if (!w->closed) w->finish(true);
    } catch (...) {
    }
    delete w;
}

}  // extern "C"
