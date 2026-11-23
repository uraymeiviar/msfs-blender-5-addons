// fss_ao_copy: the per-pixel work of AO Bake's Apply copy (see fss_ao_copy.h).
//
// Every formula below is the numpy copy's (fss_blender_tools/ao_bake_core.py: copy_master, its read() and
// _surface_bilinear, barycentric_many, rasterize_ids, bilinear), written with the same operations in the same order,
// so that the results are bit-identical. The orders numpy 2.3 uses for its reductions were measured (the harness in
// tests/test_ao_copy_native.py checks them against numpy):
// - np.add.reduce over a contiguous axis (sum, mean): 0 + pairwise sum (fewer than 8 values: one after the other;
//   up to 128: eight partial sums; more: split in two halves, the first a multiple of 8);
// - np.einsum('nk,nkd->nd') (barycentrics times corners): (p0 + p1) + p2;
// - np.einsum('nd,nd->n') (normal dot normal): (p0 + p2) + p1 (numpy's two-lane SIMD accumulator).
// Built with /fp:precise and without /arch:AVX2: no FMA contraction, no reassociation.

#include "fss_ao_copy.h"

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstring>
#include <new>
#include <thread>
#include <vector>

namespace {

const double RASTER_EPS = 1e-9;  // rasterize_ids' eps
const int64_t CELL = 8;          // px per side of a cell of the triangle bins
const int64_t BIN_MARGIN = 3;    // px: a triangle is binned this far beyond its bounds (its box test reaches 1 px)
const int64_t PX_CHUNK = 64;     // pixels taken by a thread at a time
// Soften's concave slopes (auto-bake decision 103): read over a step of at least this share of the softening width,
// else left out (the half difference alone); a thinner face's step made the slope, and the value, explode
const double SOFT_SLOPE_MIN_STEP = 0.1;

// numpy's float64 -> int64 cast on x86-64 (cvttsd2si): truncation, NaN and out-of-range values give INT64_MIN
inline int64_t to_i64(double x) {
    if (!(x >= -9223372036854775808.0 && x < 9223372036854775808.0)) return INT64_MIN;
    return (int64_t)x;
}

inline int64_t clip64(int64_t v, int64_t lo, int64_t hi) { return v < lo ? lo : (v > hi ? hi : v); }

// np.maximum(a, b) with b not NaN: NaN in a propagates
inline double np_max(double a, double b) { return (a != a) ? a : (a >= b ? a : b); }

// numpy's pairwise summation (DOUBLE_pairwise_sum)
double pairwise(const double *a, int64_t n) {
    if (n < 8) {
        double res = 0.;
        for (int64_t i = 0; i < n; i++) res += a[i];
        return res;
    }
    if (n <= 128) {
        double r[8];
        for (int j = 0; j < 8; j++) r[j] = a[j];
        int64_t i;
        for (i = 8; i < n - (n % 8); i += 8) {
            r[0] += a[i + 0];
            r[1] += a[i + 1];
            r[2] += a[i + 2];
            r[3] += a[i + 3];
            r[4] += a[i + 4];
            r[5] += a[i + 5];
            r[6] += a[i + 6];
            r[7] += a[i + 7];
        }
        double res = ((r[0] + r[1]) + (r[2] + r[3])) + ((r[4] + r[5]) + (r[6] + r[7]));
        for (; i < n; i++) res += a[i];
        return res;
    }
    int64_t n2 = n / 2;
    n2 -= n2 % 8;
    return pairwise(a, n2) + pairwise(a + n2, n - n2);
}

// np.add.reduce of a contiguous axis: the identity 0, then the pairwise sum added
inline double np_sum(const double *a, int64_t n) { return 0.0 + pairwise(a, n); }

// A triangle in target px for barycentric_many and rasterize_ids
struct Tri {
    double ax, ay, v0x, v0y, v1x, v1y, d;
    double mnx, mny, mxx, mxy;
    int64_t bx0, by0, bx1, by1;  // px whose samples its box test can reach (with BIN_MARGIN)
    bool raster;                 // rasterize_ids considers it (finite, |d| >= 1e-30)
};

// floor(v) + add, saturated far beyond any pixel (only bounds the bins)
inline int64_t bound(double v, int64_t add) {
    const double lim = 4e18;
    double f = std::floor(v);
    if (f < -lim) return -(int64_t)4000000000000000000;
    if (f > lim) return (int64_t)4000000000000000000;
    return (int64_t)f + add;
}

void make_tri(const double *uv, Tri &t) {
    // barycentric_many / barycentric: a, b, c = corners; v0 = b - a; v1 = c - a; d = v0x v1y - v0y v1x
    t.ax = uv[0];
    t.ay = uv[1];
    t.v0x = uv[2] - uv[0];
    t.v0y = uv[3] - uv[1];
    t.v1x = uv[4] - uv[0];
    t.v1y = uv[5] - uv[1];
    t.d = t.v0x * t.v1y - t.v0y * t.v1x;
    t.mnx = std::min(std::min(uv[0], uv[2]), uv[4]);
    t.mxx = std::max(std::max(uv[0], uv[2]), uv[4]);
    t.mny = std::min(std::min(uv[1], uv[3]), uv[5]);
    t.mxy = std::max(std::max(uv[1], uv[3]), uv[5]);
    bool finite = true;
    for (int i = 0; i < 6; i++) finite = finite && std::isfinite(uv[i]);
    t.raster = finite && !(std::fabs(t.d) < 1e-30);
    if (t.raster) {
        t.bx0 = bound(t.mnx, -BIN_MARGIN);
        t.bx1 = bound(t.mxx, BIN_MARGIN);
        t.by0 = bound(t.mny, -BIN_MARGIN);
        t.by1 = bound(t.mxy, BIN_MARGIN);
    } else {
        t.bx0 = t.by0 = 1;
        t.bx1 = t.by1 = 0;
    }
}

// barycentric_many of point (x, y): (1 - l1 - l2, l1, l2)
inline void bary(const Tri &t, double x, double y, double &b0, double &b1, double &b2) {
    double wx = x - t.ax, wy = y - t.ay;
    double l1 = (wx * t.v1y - wy * t.v1x) / t.d;
    double l2 = (t.v0x * wy - t.v0y * wx) / t.d;
    b0 = 1.0 - l1 - l2;
    b1 = l1;
    b2 = l2;
}

// rasterize_ids' test of sample (a, b) of the grid that starts at pixel (gx, gy) with L samples per pixel, at the
// sample's position (rx, ry): the triangle's integer sample box, then its barycentrics all at least -eps
inline bool covers(const Tri &t, int64_t a, int64_t b, double rx, double ry, int64_t gx, int64_t gy, double Ld) {
    if (!t.raster) return false;
    int64_t lo = to_i64(std::floor((t.mnx - (double)gx) * Ld - 0.5));
    if (a < lo) return false;
    int64_t hi = to_i64(std::ceil((t.mxx - (double)gx) * Ld - 0.5));
    if (a > hi) return false;
    lo = to_i64(std::floor((t.mny - (double)gy) * Ld - 0.5));
    if (b < lo) return false;
    hi = to_i64(std::ceil((t.mxy - (double)gy) * Ld - 0.5));
    if (b > hi) return false;
    double b0, b1, b2;
    bary(t, rx, ry, b0, b1, b2);
    return b0 >= -RASTER_EPS && b1 >= -RASTER_EPS && b2 >= -RASTER_EPS;
}

// The master's reads
struct Master {
    const fss_ao_master *m;
    int64_t sh, mask, tt;

    explicit Master(const fss_ao_master *mm) : m(mm), sh(0), mask(0), tt(0) {
        if (m->tile > 0) {
            while ((int64_t(1) << sh) < m->tile) sh++;
            mask = m->tile - 1;
            tt = m->tile * m->tile;
        }
    }

    inline size_t at(int64_t y, int64_t x) const {
        if (m->tile <= 0) return (size_t)(y * m->W + x);
        return (size_t)(((y >> sh) * m->tiles_x + (x >> sh)) * tt + (((y & mask) << sh) | (x & mask)));
    }

    // bilinear(M, x, y, 65535)
    double bilinear(double x, double y) const {
        const int64_t W = m->W, H = m->H;
        double fx = x - 0.5, fy = y - 0.5;
        int64_t x0 = to_i64(std::floor(fx)), y0 = to_i64(std::floor(fy));
        double ax = fx - (double)x0, ay = fy - (double)y0;
        int64_t x0c = clip64(x0, 0, W - 1), x1c = clip64(x0 + 1, 0, W - 1);
        int64_t y0c = clip64(y0, 0, H - 1), y1c = clip64(y0 + 1, 0, H - 1);
        const uint16_t *img = m->image;
        double v = ((((1 - ax) * (1 - ay)) * (double)img[at(y0c, x0c)] + (ax * (1 - ay)) * (double)img[at(y0c, x1c)])
                    + ((1 - ax) * ay) * (double)img[at(y1c, x0c)])
                   + (ax * ay) * (double)img[at(y1c, x1c)];
        return v / 65535.0;
    }

    // _surface_bilinear (same_face False)
    double surface(double x, double y, int64_t t) const {
        const int64_t W = m->W, H = m->H;
        double fx = x - 0.5, fy = y - 0.5;
        int64_t xa = to_i64(std::floor(fx)), ya = to_i64(std::floor(fy));
        double ax = fx - (double)xa, ay = fy - (double)ya;
        double acc = 0.0, wsum = 0.0;
        const double *nt = m->tri_normal + 3 * t;
        const double wg[4] = {(1 - ax) * (1 - ay), ax * (1 - ay), (1 - ax) * ay, ax * ay};
        const int64_t dxs[4] = {0, 1, 0, 1}, dys[4] = {0, 0, 1, 1};
        for (int k = 0; k < 4; k++) {
            int64_t xc = clip64(xa + dxs[k], 0, W - 1), yc = clip64(ya + dys[k], 0, H - 1);
            size_t i = at(yc, xc);
            int64_t f = (int64_t)((m->code[i] >> 1) - 1);
            bool ok = false;
            if (f >= 0 && f < m->n_tris) {
                const double *fn = m->tri_normal + 3 * f;
                double dot = (fn[0] * nt[0] + fn[2] * nt[2]) + fn[1] * nt[1];
                ok = dot >= m->surface_cos;
            }
            double wv = ok ? wg[k] : 0.0;
            double mv = (double)m->image[i] / 65535.0;
            acc += wv * mv;
            wsum += wv;
        }
        if (wsum > 1e-9) return acc / np_max(wsum, 1e-30);
        return bilinear(x, y);
    }

    // copy_master's read() of one point: the value (when need), and whether it was clamped into its island
    double read(int64_t t, double b0, double b1, double b2, bool need, bool &clamped) const {
        const double *mu = m->muv + 6 * t;
        double mx = ((0.0 + b0 * mu[0]) + b1 * mu[2]) + b2 * mu[4];
        double my = ((0.0 + b0 * mu[1]) + b1 * mu[3]) + b2 * mu[5];
        int64_t xi = clip64(to_i64(std::floor(mx)), 0, m->W - 1);
        int64_t yi = clip64(to_i64(std::floor(my)), 0, m->H - 1);
        int64_t isl = m->island[t];
        bool ok = false;
        if (isl >= 0 && isl < m->n_rects) {
            const int64_t *r = m->rects + 4 * isl;
            ok = xi >= r[0] && xi < r[0] + r[2] && yi >= r[1] && yi < r[1] + r[3] && (m->code[at(yi, xi)] & 1) != 0;
        }
        clamped = !ok;
        if (!need) return 0.0;
        if (!ok) {
            double c0 = np_max(b0, 0.0), c1 = np_max(b1, 0.0), c2 = np_max(b2, 0.0);
            double s = np_max(((0.0 + c0) + c1) + c2, 1e-30);
            c0 /= s;
            c1 /= s;
            c2 /= s;
            mx = ((0.0 + c0 * mu[0]) + c1 * mu[2]) + c2 * mu[4];
            my = ((0.0 + c0 * mu[1]) + c1 * mu[3]) + c2 * mu[5];
        }
        return m->surface ? surface(mx, my, t) : bilinear(mx, my);
    }
};

bool master_ok(const fss_ao_master *m) {
    if (!m || !m->image || !m->code || !m->muv || !m->island || !m->rects || !m->tri_normal) return false;
    if (m->W <= 0 || m->H <= 0 || m->n_tris < 0 || m->n_rects < 0) return false;
    if (m->tile > 0 && ((m->tile & (m->tile - 1)) != 0 || m->tiles_x * m->tile < m->W)) return false;
    return true;
}

// Runs body(begin, end, thread) over n items in chunks on `threads` threads (each item's result depends only on
// its inputs, so the split does not change any result). Returns an error code.
template <class Body>
int32_t parallel(int64_t n, int64_t threads, Body body) {
    int64_t chunks = (n + PX_CHUNK - 1) / PX_CHUNK;
    int64_t nt = std::max<int64_t>(1, std::min<int64_t>(threads, chunks));
    std::atomic<int64_t> next(0);
    std::atomic<int32_t> err(FSS_AO_COPY_OK);
    auto work = [&](int64_t tid) {
        try {
            for (;;) {
                int64_t c = next.fetch_add(1);
                if (c >= chunks || err.load() != FSS_AO_COPY_OK) break;
                int64_t b = c * PX_CHUNK, e = std::min(n, b + PX_CHUNK);
                body(b, e, tid);
            }
        } catch (const std::bad_alloc &) {
            err.store(FSS_AO_COPY_E_MEMORY);
        } catch (...) {
            err.store(FSS_AO_COPY_E_INTERNAL);
        }
    };
    if (nt == 1) {
        work(0);
        return err.load();
    }
    std::vector<std::thread> pool;
    try {
        pool.reserve((size_t)nt - 1);
        for (int64_t i = 1; i < nt; i++) pool.emplace_back(work, i);
    } catch (...) {
        err.store(FSS_AO_COPY_E_INTERNAL);
    }
    work(0);
    for (auto &th : pool) th.join();
    return err.load();
}

// Triangle bins over a window of target pixels: per cell of CELL x CELL px, the triangles (ascending) whose box test
// can reach a sample of a pixel of the cell
struct Bins {
    int64_t x0 = 0, y0 = 0, nx = 0, ny = 0;
    std::vector<int64_t> start, ids;

    void build(const std::vector<Tri> &tris, int64_t xmin, int64_t ymin, int64_t xmax, int64_t ymax) {
        x0 = xmin;
        y0 = ymin;
        nx = (xmax - xmin) / CELL + 1;
        ny = (ymax - ymin) / CELL + 1;
        start.assign((size_t)(nx * ny + 1), 0);
        for (int pass = 0; pass < 2; pass++) {
            std::vector<int64_t> fill;
            if (pass == 1) {
                for (size_t i = 1; i < start.size(); i++) start[i] += start[i - 1];
                ids.assign((size_t)start.back(), 0);
                fill.assign(start.begin(), start.end() - 1);
            }
            for (size_t t = 0; t < tris.size(); t++) {
                const Tri &tr = tris[t];
                if (!tr.raster) continue;
                int64_t ax0 = std::max(tr.bx0, xmin), ax1 = std::min(tr.bx1, xmax);
                int64_t ay0 = std::max(tr.by0, ymin), ay1 = std::min(tr.by1, ymax);
                if (ax1 < ax0 || ay1 < ay0) continue;
                int64_t cx0 = (ax0 - xmin) / CELL, cx1 = (ax1 - xmin) / CELL;
                int64_t cy0 = (ay0 - ymin) / CELL, cy1 = (ay1 - ymin) / CELL;
                for (int64_t cy = cy0; cy <= cy1; cy++)
                    for (int64_t cx = cx0; cx <= cx1; cx++) {
                        int64_t c = cy * nx + cx;
                        if (pass == 0)
                            start[(size_t)c + 1]++;
                        else
                            ids[(size_t)fill[(size_t)c]++] = (int64_t)t;
                    }
            }
        }
    }

    // the triangles of the cell of pixel (X, Y): [b, e) into ids
    inline void cell(int64_t X, int64_t Y, int64_t &b, int64_t &e) const {
        int64_t c = ((Y - y0) / CELL) * nx + (X - x0) / CELL;
        b = start[(size_t)c];
        e = start[(size_t)c + 1];
    }
};

// _soften's numpy operations on arrays (numpy 2.3's SIMD loops, measured: tests/_work/ao_copy/s11_probe.py):
// np.maximum / np.minimum propagate NaN and give the second value when the two are equal; np.clip keeps x when it
// equals a bound; np.add.reduce of three values is ((0 + a) + b) + c
inline double vmax(double a, double b) { return (a != a) ? a : ((b != b) ? b : (a > b ? a : b)); }
inline double vmin(double a, double b) { return (a != a) ? a : ((b != b) ? b : (a < b ? a : b)); }
inline double vclip(double x, double lo, double hi) {
    if (x != x) return x;
    double m = x < lo ? lo : x;
    return m > hi ? hi : m;
}
inline double dot3(const double *a, const double *b) { return ((0.0 + a[0] * b[0]) + a[1] * b[1]) + a[2] * b[2]; }

bool soften_ok(const fss_ao_soften *s, int64_t n_tris) {
    if (!s || s->n_edges < 0 || s->n_tris != n_tris || s->n_verts < 0 || !s->start || !s->Wt || !s->pos || !s->tris)
        return false;
    if (s->n_edges > 0 && (!s->E || !s->A || !s->B || !s->mX || !s->mY || !s->hX || !s->hY || !s->convex))
        return false;
    if (s->start[0] != 0) return false;
    for (int64_t t = 0; t < n_tris; t++)
        if (s->start[t + 1] < s->start[t]) return false;
    const int64_t nc = s->start[n_tris];
    if (nc > 0 && !s->cand) return false;
    for (int64_t c = 0; c < nc; c++)
        if (s->cand[c] < 0 || s->cand[c] >= s->n_edges) return false;
    for (int64_t e = 0; e < s->n_edges; e++) {
        const int64_t *r = s->E + 6 * e;
        if (r[0] < 0 || r[0] >= n_tris || r[3] < 0 || r[3] >= n_tris) return false;
        for (int k : {1, 2, 4, 5})
            if (r[k] < 0 || r[k] > 2) return false;
    }
    for (int64_t i = 0; i < 3 * n_tris; i++)
        if (s->tris[i] < 0 || s->tris[i] >= s->n_verts) return false;
    return true;
}

// numpy's x ** 3 on float64 is the C runtime's pow (npy_pow), the one of the process: ucrtbase.dll. The static C
// runtime's pow of this DLL can differ from it in the last bit (measured, Session 11), so _soften's (1 - x) ** 3 calls
// ucrtbase's, loaded from System32 for the call and freed after it.
typedef double (*pow_fn)(double, double);

struct CrtPow {
    HMODULE lib = nullptr;
    pow_fn fn = nullptr;
    CrtPow() {
        lib = LoadLibraryExW(L"ucrtbase.dll", nullptr, LOAD_LIBRARY_SEARCH_SYSTEM32);
        if (lib) fn = reinterpret_cast<pow_fn>(reinterpret_cast<void *>(GetProcAddress(lib, "pow")));
    }
    ~CrtPow() {
        if (lib) FreeLibrary(lib);
    }
    CrtPow(const CrtPow &) = delete;
    CrtPow &operator=(const CrtPow &) = delete;
};

// _bary3 of one point p in the triangle of corners q0, q1, q2: clamped onto it
inline void bary3(const double *p, const double *q0, const double *q1, const double *q2, double bc[3]) {
    double v0[3], v1[3], v2[3];
    for (int d = 0; d < 3; d++) {
        v0[d] = q1[d] - q0[d];
        v1[d] = q2[d] - q0[d];
        v2[d] = p[d] - q0[d];
    }
    const double d00 = dot3(v0, v0), d01 = dot3(v0, v1), d11 = dot3(v1, v1);
    const double d20 = dot3(v2, v0), d21 = dot3(v2, v1);
    const double den = vmax(d00 * d11 - d01 * d01, 1e-30);
    const double v = (d11 * d20 - d01 * d21) / den;
    const double w = (d00 * d21 - d01 * d20) / den;
    bc[0] = vmax(1.0 - v - w, 0.0);
    bc[1] = vmax(v, 0.0);
    bc[2] = vmax(w, 0.0);
    const double s = vmax(((0.0 + bc[0]) + bc[1]) + bc[2], 1e-30);
    bc[0] /= s;
    bc[1] /= s;
    bc[2] /= s;
}

}  // namespace

extern "C" {

FSS_AO_COPY_API int32_t fss_ao_copy_version(void) { return FSS_AO_COPY_VERSION; }

FSS_AO_COPY_API int32_t fss_ao_copy_soften(const fss_ao_master *master, const fss_ao_soften *soften, int64_t n,
                                           const int64_t *tri_ids, const double *P3, const double *vals,
                                           int64_t threads, double *out, int64_t *changed) {
    if (!master_ok(master) || !changed || n < 0 || threads < 1 || threads > 1024) return FSS_AO_COPY_E_ARGS;
    *changed = 0;
    if (!soften_ok(soften, master->n_tris)) return FSS_AO_COPY_E_ARGS;
    if (n == 0) return FSS_AO_COPY_OK;
    if (!tri_ids || !P3 || !vals || !out) return FSS_AO_COPY_E_ARGS;
    for (int64_t i = 0; i < n; i++)
        if (tri_ids[i] < 0 || tri_ids[i] >= master->n_tris) return FSS_AO_COPY_E_ARGS;
    try {
        const CrtPow crt;
        if (!crt.fn) return FSS_AO_COPY_E_LIBRARY;
        const pow_fn cpow = crt.fn;
        const Master m(master);
        const fss_ao_soften &sc = *soften;
        const double *tn = master->tri_normal;
        int64_t nthreads = std::max<int64_t>(1, std::min<int64_t>(threads, (n + PX_CHUNK - 1) / PX_CHUNK));
        std::vector<int64_t> counts((size_t)nthreads, 0);
        int32_t rc = parallel(n, nthreads, [&](int64_t b, int64_t e_, int64_t tid) {
            int64_t done_n = 0;
            for (int64_t i = b; i < e_; i++) {
                const int64_t s = tri_ids[i];
                const int64_t c0 = sc.start[s], c1 = sc.start[s + 1];
                if (c1 <= c0) {
                    out[i] = vals[i];
                    continue;
                }
                const double *p = P3 + 3 * i;
                const double W = sc.Wt[s];
                double add = 0.0, cadd = 0.0;
                for (int64_t c = c0; c < c1; c++) {
                    const int64_t e = sc.cand[c];
                    const int64_t *E = sc.E + 6 * e;
                    const double *a = sc.A + 3 * e, *bb = sc.B + 3 * e;
                    double ab[3], pa[3];
                    for (int d = 0; d < 3; d++) {
                        ab[d] = bb[d] - a[d];
                        pa[d] = p[d] - a[d];
                    }
                    const double u = vclip(dot3(pa, ab) / vmax(dot3(ab, ab), 1e-30), 0.0, 1.0);
                    double q[3], pq[3];
                    for (int d = 0; d < 3; d++) {
                        q[d] = a[d] + ab[d] * u;
                        pq[d] = p[d] - q[d];
                    }
                    const double dist = std::sqrt(dot3(pq, pq));
                    const double cx = dot3(tn + 3 * s, tn + 3 * E[0]);
                    const double cy = dot3(tn + 3 * s, tn + 3 * E[3]);
                    const bool on_x = cx >= cy;
                    const double *mm = on_x ? sc.mX + 3 * e : sc.mY + 3 * e;
                    const bool keep = (vmax(cx, cy) >= sc.surface_cos) && (dot3(pq, mm) >= -1e-3 * W) && (dist < W);
                    if (!keep) continue;
                    bool cl = false;
                    double bx[3] = {0.0, 0.0, 0.0}, by[3] = {0.0, 0.0, 0.0};
                    bx[E[1]] = 1.0 - u;
                    bx[E[2]] += u;
                    by[E[4]] = 1.0 - u;
                    by[E[5]] += u;
                    const double vx = m.read(E[0], bx[0], bx[1], bx[2], true, cl);
                    const double vy = m.read(E[3], by[0], by[1], by[2], true, cl);
                    const double delta = on_x ? vy - vx : vx - vy;
                    const double x = dist / W;
                    const double fade = 1.0 - x * x * (3.0 - 2.0 * x);
                    const bool cv = sc.convex[e] != 0;
                    const double gain = (cv && delta > 0) ? delta * fade : 0.0;
                    add = (gain > add) ? gain : add;  // np.maximum.at (no NaN reaches it, both values >= 0)
                    if (cv) continue;
                    // concave: the slopes away from the edge, read half a width in (at most 0.9 of each face's
                    // height over the edge); decision 103: under SOFT_SLOPE_MIN_STEP of the width, no slopes
                    const double pd = vmin(0.5 * W, 0.9 * vmin(sc.hX[e], sc.hY[e]));
                    if (!(pd >= SOFT_SLOPE_MIN_STEP * W)) {
                        cadd = cadd + 0.5 * delta * fade;
                        continue;
                    }
                    double ac[3];
                    for (int d = 0; d < 3; d++) ac[d] = a[d] + (bb[d] - a[d]) * u;
                    double pr[2];
                    for (int side = 0; side < 2; side++) {
                        const int64_t t = side == 0 ? E[0] : E[3];
                        const double *mv = side == 0 ? sc.mX + 3 * e : sc.mY + 3 * e;
                        double pt[3], bc[3];
                        for (int d = 0; d < 3; d++) pt[d] = ac[d] + mv[d] * pd;
                        const int64_t *tv = sc.tris + 3 * t;
                        bary3(pt, sc.pos + 3 * tv[0], sc.pos + 3 * tv[1], sc.pos + 3 * tv[2], bc);
                        pr[side] = m.read(t, bc[0], bc[1], bc[2], true, cl);
                    }
                    const double s_own = ((on_x ? pr[0] : pr[1]) - (on_x ? vx : vy)) / pd;
                    const double s_other = ((on_x ? pr[1] : pr[0]) - (on_x ? vy : vx)) / pd;
                    const double corr = 0.5 * delta * fade + 0.5 * (s_own + s_other) * (W / 3.0) * cpow(1.0 - x, 3.0);
                    cadd = cadd + corr;
                }
                const bool done = (add > 1e-9) || (std::fabs(cadd) > 1e-9);
                out[i] = done ? vclip(vals[i] + add + cadd, 0.0, 1.0) : vals[i];
                done_n += done ? 1 : 0;
            }
            counts[(size_t)tid] += done_n;
        });
        if (rc != FSS_AO_COPY_OK) return rc;
        int64_t total = 0;
        for (int64_t c : counts) total += c;
        *changed = total;
    } catch (const std::bad_alloc &) {
        return FSS_AO_COPY_E_MEMORY;
    } catch (...) {
        return FSS_AO_COPY_E_INTERNAL;
    }
    return FSS_AO_COPY_OK;
}

FSS_AO_COPY_API double fss_ao_copy_sum(const double *a, int64_t n) {
    if (!a || n <= 0) return 0.0;
    return np_sum(a, n);
}

FSS_AO_COPY_API int32_t fss_ao_copy_read(const fss_ao_master *master, int64_t n, const int64_t *tri,
                                         const double *bry, double *out, uint8_t *clamped) {
    if (!master_ok(master) || n < 0 || (n > 0 && (!tri || !bry || !out || !clamped))) return FSS_AO_COPY_E_ARGS;
    try {
        Master m(master);
        for (int64_t i = 0; i < n; i++) {
            if (tri[i] < 0 || tri[i] >= master->n_tris) return FSS_AO_COPY_E_ARGS;
            bool c = false;
            out[i] = m.read(tri[i], bry[3 * i], bry[3 * i + 1], bry[3 * i + 2], true, c);
            clamped[i] = c ? 1 : 0;
        }
    } catch (...) {
        return FSS_AO_COPY_E_INTERNAL;
    }
    return FSS_AO_COPY_OK;
}

FSS_AO_COPY_API int32_t fss_ao_copy_raster(const double *uvpx, int64_t n_tris, int64_t gx, int64_t gy, int64_t gw,
                                           int64_t gh, int64_t level, int64_t *owner) {
    if (!uvpx || !owner || n_tris < 0 || gw <= 0 || gh <= 0 || level < 1 || level > FSS_AO_COPY_MAX_LEVEL)
        return FSS_AO_COPY_E_ARGS;
    try {
        std::vector<Tri> tris((size_t)n_tris);
        for (int64_t t = 0; t < n_tris; t++) make_tri(uvpx + 6 * t, tris[(size_t)t]);
        const double Ld = (double)level;
        const int64_t GW = gw * level, GH = gh * level;
        for (int64_t b = 0; b < GH; b++) {
            double ry = (double)gy + ((double)b + 0.5) / Ld;
            for (int64_t a = 0; a < GW; a++) {
                double rx = (double)gx + ((double)a + 0.5) / Ld;
                int64_t own = -1;
                for (int64_t t = n_tris - 1; t >= 0; t--)
                    if (covers(tris[(size_t)t], a, b, rx, ry, gx, gy, Ld)) {
                        own = t;
                        break;
                    }
                owner[b * GW + a] = own;
            }
        }
    } catch (const std::bad_alloc &) {
        return FSS_AO_COPY_E_MEMORY;
    } catch (...) {
        return FSS_AO_COPY_E_INTERNAL;
    }
    return FSS_AO_COPY_OK;
}

FSS_AO_COPY_API int32_t fss_ao_copy_inside(const fss_ao_master *master, const double *uvpx, int64_t n_px,
                                           const int64_t *px, const int64_t *owner, const int64_t *level,
                                           const int64_t *origin, int64_t threads, double *out, int64_t *clamped) {
    if (!master_ok(master) || !uvpx || !clamped || n_px < 0 || threads < 1 || threads > 1024) return FSS_AO_COPY_E_ARGS;
    *clamped = 0;
    if (n_px == 0) return FSS_AO_COPY_OK;
    if (!px || !owner || !level || !origin || !out) return FSS_AO_COPY_E_ARGS;
    const int64_t T = master->n_tris;
    int64_t xmin = INT64_MAX, ymin = INT64_MAX, xmax = INT64_MIN, ymax = INT64_MIN;
    for (int64_t n = 0; n < n_px; n++) {
        if (owner[n] < 0 || owner[n] >= T || level[n] < 1 || level[n] > FSS_AO_COPY_MAX_LEVEL) return FSS_AO_COPY_E_ARGS;
        xmin = std::min(xmin, px[2 * n]);
        xmax = std::max(xmax, px[2 * n]);
        ymin = std::min(ymin, px[2 * n + 1]);
        ymax = std::max(ymax, px[2 * n + 1]);
    }
    try {
        std::vector<Tri> tris((size_t)T);
        for (int64_t t = 0; t < T; t++) make_tri(uvpx + 6 * t, tris[(size_t)t]);
        Bins bins;
        bins.build(tris, xmin, ymin, xmax, ymax);
        const Master m(master);
        int64_t most = 0;
        for (size_t c = 0; c + 1 < bins.start.size(); c++) most = std::max(most, bins.start[c + 1] - bins.start[c]);
        int64_t nthreads = std::max<int64_t>(1, std::min<int64_t>(threads, (n_px + PX_CHUNK - 1) / PX_CHUNK));
        const int64_t S = FSS_AO_COPY_MAX_LEVEL * FSS_AO_COPY_MAX_LEVEL;
        std::vector<double> buf((size_t)(nthreads * (2 * S + FSS_AO_COPY_MAX_LEVEL)));
        std::vector<int64_t> cand((size_t)(nthreads * (most + 1)));
        std::vector<int64_t> counts((size_t)nthreads, 0);
        int32_t rc = parallel(n_px, nthreads, [&](int64_t b, int64_t e, int64_t tid) {
            double *wv = buf.data() + tid * (2 * S + FSS_AO_COPY_MAX_LEVEL);
            double *vw = wv + S;
            double *sub = vw + S;
            int64_t *cd = cand.data() + tid * (most + 1);
            int64_t n_cl = 0;
            for (int64_t n = b; n < e; n++) {
                const int64_t X = px[2 * n], Y = px[2 * n + 1], t = owner[n], L = level[n];
                const int64_t gx = origin[2 * n], gy = origin[2 * n + 1];
                const double Ld = (double)L;
                const Tri &own = tris[(size_t)t];
                // the triangles after the owner that can cover a sample of this pixel
                int64_t cb, ce, nc = 0;
                bins.cell(X, Y, cb, ce);
                for (int64_t i = ce - 1; i >= cb && bins.ids[(size_t)i] > t; i--) {
                    const Tri &c = tris[(size_t)bins.ids[(size_t)i]];
                    if (X >= c.bx0 && X <= c.bx1 && Y >= c.by0 && Y <= c.by1) cd[nc++] = bins.ids[(size_t)i];
                }
                for (int64_t i = 0; i < L; i++) sub[i] = ((double)i + 0.5) / Ld;
                const int64_t ax0 = (X - gx) * L, ay0 = (Y - gy) * L;
                for (int64_t ay = 0; ay < L; ay++) {
                    const int64_t sb = ay0 + ay;
                    const double ry = (double)gy + ((double)sb + 0.5) / Ld;
                    const double pyv = (double)Y + sub[ay];
                    for (int64_t ax = 0; ax < L; ax++) {
                        const int64_t sa = ax0 + ax;
                        const double rx = (double)gx + ((double)sa + 0.5) / Ld;
                        bool same = covers(own, sa, sb, rx, ry, gx, gy, Ld);
                        for (int64_t k = 0; same && k < nc; k++)
                            if (covers(tris[(size_t)cd[k]], sa, sb, rx, ry, gx, gy, Ld)) same = false;
                        double b0, b1, b2;
                        bary(own, (double)X + sub[ax], pyv, b0, b1, b2);
                        bool c = false;
                        double v = m.read(t, b0, b1, b2, same, c);
                        n_cl += c ? 1 : 0;
                        const int64_t s = ay * L + ax;
                        wv[s] = same ? 1.0 : 0.0;
                        vw[s] = same ? v * 1.0 : 0.0;
                    }
                }
                const int64_t LL = L * L;
                double sw = np_sum(wv, LL);
                if (sw > 0) {
                    out[n] = np_sum(vw, LL) / np_max(sw, 1e-30);
                } else {
                    double b0, b1, b2;
                    bary(own, (double)X + 0.5, (double)Y + 0.5, b0, b1, b2);
                    bool c = false;
                    out[n] = m.read(t, b0, b1, b2, true, c);
                }
            }
            counts[(size_t)tid] += n_cl;
        });
        if (rc != FSS_AO_COPY_OK) return rc;
        int64_t total = 0;
        for (int64_t c : counts) total += c;
        *clamped = total;
    } catch (const std::bad_alloc &) {
        return FSS_AO_COPY_E_MEMORY;
    } catch (...) {
        return FSS_AO_COPY_E_INTERNAL;
    }
    return FSS_AO_COPY_OK;
}

FSS_AO_COPY_API int32_t fss_ao_copy_padding(const fss_ao_master *master, int64_t n_px, const int64_t *px,
                                            const int64_t *src, const double *tri_uv, const int64_t *level,
                                            int64_t threads, double *out, int64_t *clamped) {
    if (!master_ok(master) || !clamped || n_px < 0 || threads < 1 || threads > 1024) return FSS_AO_COPY_E_ARGS;
    *clamped = 0;
    if (n_px == 0) return FSS_AO_COPY_OK;
    if (!px || !src || !tri_uv || !level || !out) return FSS_AO_COPY_E_ARGS;
    for (int64_t n = 0; n < n_px; n++)
        if (src[n] < 0 || src[n] >= master->n_tris || level[n] < 1 || level[n] > FSS_AO_COPY_MAX_LEVEL)
            return FSS_AO_COPY_E_ARGS;
    try {
        const Master m(master);
        int64_t nthreads = std::max<int64_t>(1, std::min<int64_t>(threads, (n_px + PX_CHUNK - 1) / PX_CHUNK));
        const int64_t S = FSS_AO_COPY_MAX_LEVEL * FSS_AO_COPY_MAX_LEVEL;
        std::vector<double> buf((size_t)(nthreads * (S + FSS_AO_COPY_MAX_LEVEL)));
        std::vector<int64_t> counts((size_t)nthreads, 0);
        int32_t rc = parallel(n_px, nthreads, [&](int64_t b, int64_t e, int64_t tid) {
            double *vals = buf.data() + tid * (S + FSS_AO_COPY_MAX_LEVEL);
            double *sub = vals + S;
            int64_t n_cl = 0;
            for (int64_t n = b; n < e; n++) {
                const int64_t X = px[2 * n], Y = px[2 * n + 1], t = src[n], L = level[n];
                const double Ld = (double)L;
                Tri tri;
                make_tri(tri_uv + 6 * n, tri);
                for (int64_t i = 0; i < L; i++) sub[i] = ((double)i + 0.5) / Ld;
                for (int64_t ay = 0; ay < L; ay++)
                    for (int64_t ax = 0; ax < L; ax++) {
                        double b0, b1, b2;
                        bary(tri, (double)X + sub[ax], (double)Y + sub[ay], b0, b1, b2);
                        // stay on the face: clamped and renormalized
                        b0 = np_max(b0, 0.0);
                        b1 = np_max(b1, 0.0);
                        b2 = np_max(b2, 0.0);
                        double s = np_max(((0.0 + b0) + b1) + b2, 1e-30);
                        b0 /= s;
                        b1 /= s;
                        b2 /= s;
                        bool c = false;
                        vals[ay * L + ax] = m.read(t, b0, b1, b2, true, c);
                        n_cl += c ? 1 : 0;
                    }
                out[n] = np_sum(vals, L * L) / (double)(L * L);
            }
            counts[(size_t)tid] += n_cl;
        });
        if (rc != FSS_AO_COPY_OK) return rc;
        int64_t total = 0;
        for (int64_t c : counts) total += c;
        *clamped = total;
    } catch (const std::bad_alloc &) {
        return FSS_AO_COPY_E_MEMORY;
    } catch (...) {
        return FSS_AO_COPY_E_INTERNAL;
    }
    return FSS_AO_COPY_OK;
}

}  // extern "C"
