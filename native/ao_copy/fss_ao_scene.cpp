// fss_ao_scene: Refresh's scene rule geometry and the mesh hash (see fss_ao_scene_* and fss_ao_mesh_hash in
// fss_ao_copy.h, interface version 6; bake-post-native journal, Session 4).
//
// fss_ao_scene_near is ao_bake_store._rule_tools' near for many objects at once (auto-bake decisions 15, 59, 64, 65
// and 70): the world boxes' gap of each occluder (now, or swept over the sampled frames), then the gap of the objects'
// own boxes as placed at the current frame or at each sampled frame (the separating-axis gap of two oriented boxes,
// the smallest over the poses), the keep test against the distance, the final gaps. fss_ao_scene_moves is
// moves_against for many pairs. Every formula is the numpy code's with numpy's order of operations (float64,
// /fp:precise, no FMA), measured on Blender's numpy 2 (Session 5): matmul and einsum with a strided reduction sum
// their products in order, ((p0 + p1) + p2) + ...; the einsums that reduce a contiguous axis of both operands
// ('kij,nj->kni', '...ij,...j->...i', 'kmx,kx->km') sum three products as (p0 + p2) + p1; np.cross, np.linalg.norm and
// sums of three in order; min, max, np.minimum and np.maximum with NaN propagating. Threads split the objects (or
// pairs), never one result, so nothing depends on the thread count.
//
// fss_ao_mesh_hash is ao_bake_core.mesh_hash: SHA-1 (with the SHA instructions where the CPU has them, else in plain
// C++; the same digest) of the triangles as int32, the positions as float32 and the corner normals rounded as
// np.round(x, 4) + 0.0 (rint(x * 10000) / 10000) as float32; threads convert the corner normals.

#include "fss_ao_copy.h"

#include <intrin.h>
#include <immintrin.h>

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstring>
#include <limits>
#include <memory>
#include <new>
#include <thread>
#include <vector>

namespace {

const double INF = std::numeric_limits<double>::infinity();
const double QNAN = std::numeric_limits<double>::quiet_NaN();
const double NEAR_TOL = 1e-9;  // m: a gap this close to the distance is counted in the stats

// np.maximum / np.minimum: NaN when either is NaN
inline double nmax(double a, double b) { return (a != a || b != b) ? QNAN : (a > b ? a : b); }
inline double nmin(double a, double b) { return (a != a || b != b) ? QNAN : (a < b ? a : b); }

// Runs body(i) for i in [0, n) on up to `threads` threads, `per` items a job; an error code.
template <class Body>
int32_t parallel_for(int64_t n, int64_t per, int64_t threads, Body body) {
    if (n <= 0) return FSS_AO_COPY_OK;
    const int64_t jobs = (n + per - 1) / per;
    const int64_t nt = std::max<int64_t>(1, std::min<int64_t>(threads, jobs));
    std::atomic<int64_t> next(0);
    std::atomic<int32_t> err(FSS_AO_COPY_OK);
    auto work = [&]() {
        try {
            for (;;) {
                const int64_t j = next.fetch_add(1);
                if (j >= jobs || err.load() != FSS_AO_COPY_OK) break;
                const int64_t e = std::min(n, (j + 1) * per);
                for (int64_t i = j * per; i < e; i++) body(i);
            }
        } catch (const std::bad_alloc &) {
            err.store(FSS_AO_COPY_E_MEMORY);
        } catch (...) {
            err.store(FSS_AO_COPY_E_INTERNAL);
        }
    };
    std::vector<std::thread> pool;
    try {
        for (int64_t t = 1; t < nt; t++) pool.emplace_back(work);
    } catch (...) {
        // fewer threads: the jobs are shared by those that started
    }
    work();
    for (auto &th : pool) th.join();
    return err.load();
}

// The world box (lo, hi) of 8 corners placed by a matrix as _world_box does: c @ R.T + t (matmul: products in order)
void world_box(const double *c, const double *M, double *lo, double *hi) {
    for (int i = 0; i < 3; i++) {
        lo[i] = INF;
        hi[i] = -INF;
    }
    bool nan[3] = {false, false, false};
    for (int n = 0; n < 8; n++) {
        const double *p = c + 3 * n;
        for (int i = 0; i < 3; i++) {
            const double w = ((p[0] * M[4 * i] + p[1] * M[4 * i + 1]) + p[2] * M[4 * i + 2]) + M[4 * i + 3];
            if (w != w) nan[i] = true;
            if (w < lo[i]) lo[i] = w;
            if (w > hi[i]) hi[i] = w;
        }
    }
    for (int i = 0; i < 3; i++)
        if (nan[i]) lo[i] = hi[i] = QNAN;
}

// _swept_box: the corners at every pose, einsum('kij,nj->kni', R, c) + t: (p0 + p2) + p1
void swept_box(const double *c, const double *Ms, int64_t P, double *lo, double *hi) {
    for (int i = 0; i < 3; i++) {
        lo[i] = INF;
        hi[i] = -INF;
    }
    bool nan[3] = {false, false, false};
    for (int64_t k = 0; k < P; k++) {
        const double *M = Ms + 16 * k;
        for (int n = 0; n < 8; n++) {
            const double *p = c + 3 * n;
            for (int i = 0; i < 3; i++) {
                const double w = ((M[4 * i] * p[0] + M[4 * i + 2] * p[2]) + M[4 * i + 1] * p[1]) + M[4 * i + 3];
                if (w != w) nan[i] = true;
                if (w < lo[i]) lo[i] = w;
                if (w > hi[i]) hi[i] = w;
            }
        }
    }
    for (int i = 0; i < 3; i++)
        if (nan[i]) lo[i] = hi[i] = QNAN;
}

// The bounds of 8 corners (np.min / np.max over them, NaN propagating)
void local_bounds(const double *c, double *lo, double *hi) {
    for (int i = 0; i < 3; i++) {
        double a = c[i], b = c[i];
        bool nan = a != a;
        for (int n = 1; n < 8; n++) {
            const double v = c[3 * n + i];
            if (v != v) nan = true;
            if (v < a) a = v;
            if (v > b) b = v;
        }
        lo[i] = nan ? QNAN : a;
        hi[i] = nan ? QNAN : b;
    }
}

// An own box: centre, unit axes as columns (U[3 * row + col]), half sizes, ok
struct OBox {
    double c[3], U[9], e[3];
    bool ok;
};

// oriented_boxes_at(lo, hi, M) for one matrix (row-major 4 x 4)
void oriented_box(const double *lo, const double *hi, const double *M, double ortho_tol, OBox &b) {
    double lens[3];
    for (int j = 0; j < 3; j++) {  // np.linalg.norm(cols, axis=-2): the columns' norms
        const double a = M[j], c = M[4 + j], d = M[8 + j];
        lens[j] = std::sqrt((a * a + c * c) + d * d);
    }
    bool ok = lens[0] >= 1e-12 && lens[1] >= 1e-12 && lens[2] >= 1e-12;  // lens.min() >= 1e-12 (NaN: False)
    for (int i = 0; i < 3; i++)
        for (int j = 0; j < 3; j++) b.U[3 * i + j] = M[4 * i + j] / (lens[j] < 1e-12 ? 1.0 : lens[j]);
    // np.abs(axes.T @ axes - eye).max() <= ORTHO_TOL (matmul: in order; NaN: False)
    double worst = 0.0;
    bool nan = false;
    for (int a = 0; a < 3; a++)
        for (int c = 0; c < 3; c++) {
            const double g = (b.U[a] * b.U[c] + b.U[3 + a] * b.U[3 + c]) + b.U[6 + a] * b.U[6 + c];
            const double v = std::fabs(g - (a == c ? 1.0 : 0.0));
            if (v != v) nan = true;
            if (v > worst) worst = v;
        }
    ok = ok && !nan && worst <= ortho_tol;
    double mid[3];
    for (int j = 0; j < 3; j++) mid[j] = (lo[j] + hi[j]) / 2;
    for (int i = 0; i < 3; i++)  // einsum('...ij,...j->...i', cols, mid) + t: (p0 + p2) + p1
        b.c[i] = ((M[4 * i] * mid[0] + M[4 * i + 2] * mid[2]) + M[4 * i + 1] * mid[1]) + M[4 * i + 3];
    for (int j = 0; j < 3; j++) b.e[j] = (hi[j] - lo[j]) / 2 * lens[j];
    b.ok = ok;
}

// oriented_gaps((c, U, e), ...) of one other box: the largest separation along the 15 axes (each box's 3 edge
// directions and their 9 cross products, parallel edges skipped), at least 0
double oriented_gap(const OBox &A, const OBox &B) {
    double L[15][3];
    bool okc[15];
    for (int a = 0; a < 3; a++)
        for (int x = 0; x < 3; x++) {
            L[a][x] = A.U[3 * x + a];      // U.T: A's axis a
            L[3 + a][x] = B.U[3 * x + a];  // B's axis a
        }
    for (int m = 0; m < 6; m++) okc[m] = true;
    for (int a = 0; a < 3; a++)
        for (int bb = 0; bb < 3; bb++) {
            const double u0 = A.U[a], u1 = A.U[3 + a], u2 = A.U[6 + a];
            const double v0 = B.U[bb], v1 = B.U[3 + bb], v2 = B.U[6 + bb];
            const double c0 = u1 * v2 - u2 * v1, c1 = u2 * v0 - u0 * v2, c2 = u0 * v1 - u1 * v0;  // np.cross
            const double nrm = std::sqrt((c0 * c0 + c1 * c1) + c2 * c2);
            const int m = 6 + 3 * a + bb;
            okc[m] = nrm > 1e-9;
            L[m][0] = okc[m] ? c0 / nrm : 0.0;
            L[m][1] = okc[m] ? c1 / nrm : 0.0;
            L[m][2] = okc[m] ? c2 / nrm : 0.0;
        }
    const double dv[3] = {B.c[0] - A.c[0], B.c[1] - A.c[1], B.c[2] - A.c[2]};
    double best = 0.0;
    bool any = false, nan = false;
    for (int m = 0; m < 15; m++) {
        double ra = 0.0, rb = 0.0;
        double ta[3], tb[3];
        for (int j = 0; j < 3; j++) {
            // (L @ U)[m, j] (matmul) and einsum('kmx,kxj->kmj', L, axes) (strided: in order)
            const double pa = (L[m][0] * A.U[j] + L[m][1] * A.U[3 + j]) + L[m][2] * A.U[6 + j];
            const double pb = (L[m][0] * B.U[j] + L[m][1] * B.U[3 + j]) + L[m][2] * B.U[6 + j];
            ta[j] = std::fabs(pa) * A.e[j];
            tb[j] = std::fabs(pb) * B.e[j];
        }
        ra = (ta[0] + ta[1]) + ta[2];
        rb = (tb[0] + tb[1]) + tb[2];
        const double d = std::fabs((L[m][0] * dv[0] + L[m][2] * dv[2]) + L[m][1] * dv[1]);  // einsum('kmx,kx->km')
        double sep = (d - ra) - rb;
        if (m >= 6 && !okc[m]) sep = -INF;  // parallel edges: no axis
        if (sep != sep) nan = true;
        if (!any || sep > best) best = sep;
        any = true;
    }
    if (nan) return QNAN;
    return nmax(best, 0.0);
}

struct RowBoxes {
    double now_lo[3], now_hi[3], sw_lo[3], sw_hi[3], loc_lo[3], loc_hi[3];
};

int32_t check_scene(const fss_ao_scene *S) {
    if (!S || S->n_rows < 0 || S->n_poses < 1 || S->n_occ < 0 || S->n_occ > S->n_rows ||
        (S->n_rows && (!S->M || !S->moving || !S->now || !S->corners)) || (S->n_occ && !S->occ_rows))
        return FSS_AO_COPY_E_ARGS;
    for (int64_t j = 0; j < S->n_occ; j++)
        if (S->occ_rows[j] < 0 || S->occ_rows[j] >= S->n_rows) return FSS_AO_COPY_E_ARGS;
    return FSS_AO_COPY_OK;
}

// ---------------------------------------------------------------------------------------------------------------------
// SHA-1
// ---------------------------------------------------------------------------------------------------------------------

inline uint32_t rol(uint32_t x, int n) { return (x << n) | (x >> (32 - n)); }

void sha1_blocks_c(uint32_t st[5], const uint8_t *p, size_t n_blocks) {
    for (size_t blk = 0; blk < n_blocks; blk++, p += 64) {
        uint32_t w[80];
        for (int i = 0; i < 16; i++)
            w[i] = ((uint32_t)p[4 * i] << 24) | ((uint32_t)p[4 * i + 1] << 16) | ((uint32_t)p[4 * i + 2] << 8) |
                   (uint32_t)p[4 * i + 3];
        for (int i = 16; i < 80; i++) w[i] = rol(w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16], 1);
        uint32_t a = st[0], b = st[1], c = st[2], d = st[3], e = st[4];
        for (int i = 0; i < 80; i++) {
            uint32_t f, k;
            if (i < 20) {
                f = (b & c) | (~b & d);
                k = 0x5A827999u;
            } else if (i < 40) {
                f = b ^ c ^ d;
                k = 0x6ED9EBA1u;
            } else if (i < 60) {
                f = (b & c) | (b & d) | (c & d);
                k = 0x8F1BBCDCu;
            } else {
                f = b ^ c ^ d;
                k = 0xCA62C1D6u;
            }
            const uint32_t t = rol(a, 5) + f + e + k + w[i];
            e = d;
            d = c;
            c = rol(b, 30);
            b = a;
            a = t;
        }
        st[0] += a;
        st[1] += b;
        st[2] += c;
        st[3] += d;
        st[4] += e;
    }
}

// The SHA extensions (SHA-NI): the same compression, four rounds an instruction
void sha1_blocks_ni(uint32_t st[5], const uint8_t *data, size_t n_blocks) {
    const __m128i MASK = _mm_set_epi64x(0x0001020304050607LL, 0x08090a0b0c0d0e0fLL);
    __m128i ABCD = _mm_loadu_si128((const __m128i *)st);
    __m128i E0 = _mm_set_epi32((int)st[4], 0, 0, 0);
    ABCD = _mm_shuffle_epi32(ABCD, 0x1B);
    __m128i E1, MSG0, MSG1, MSG2, MSG3;
    for (size_t blk = 0; blk < n_blocks; blk++, data += 64) {
        const __m128i ABCD_SAVE = ABCD, E0_SAVE = E0;
        MSG0 = _mm_shuffle_epi8(_mm_loadu_si128((const __m128i *)(data + 0)), MASK);
        E0 = _mm_add_epi32(E0, MSG0);
        E1 = ABCD;
        ABCD = _mm_sha1rnds4_epu32(ABCD, E0, 0);
        MSG1 = _mm_shuffle_epi8(_mm_loadu_si128((const __m128i *)(data + 16)), MASK);
        E1 = _mm_sha1nexte_epu32(E1, MSG1);
        E0 = ABCD;
        ABCD = _mm_sha1rnds4_epu32(ABCD, E1, 0);
        MSG0 = _mm_sha1msg1_epu32(MSG0, MSG1);
        MSG2 = _mm_shuffle_epi8(_mm_loadu_si128((const __m128i *)(data + 32)), MASK);
        E0 = _mm_sha1nexte_epu32(E0, MSG2);
        E1 = ABCD;
        ABCD = _mm_sha1rnds4_epu32(ABCD, E0, 0);
        MSG1 = _mm_sha1msg1_epu32(MSG1, MSG2);
        MSG0 = _mm_xor_si128(MSG0, MSG2);
        MSG3 = _mm_shuffle_epi8(_mm_loadu_si128((const __m128i *)(data + 48)), MASK);
        E1 = _mm_sha1nexte_epu32(E1, MSG3);
        E0 = ABCD;
        MSG0 = _mm_sha1msg2_epu32(MSG0, MSG3);
        ABCD = _mm_sha1rnds4_epu32(ABCD, E1, 0);
        MSG2 = _mm_sha1msg1_epu32(MSG2, MSG3);
        MSG1 = _mm_xor_si128(MSG1, MSG3);
        // rounds 16 to 79: (E, MSG) pairs rotate; the function index is rounds / 20
#define FSS_SHA_STEP(Ea, Eb, Ma, Mb, Mc, Md, F)            \
    Ea = _mm_sha1nexte_epu32(Ea, Ma);                      \
    Eb = ABCD;                                             \
    Mb = _mm_sha1msg2_epu32(Mb, Ma);                       \
    ABCD = _mm_sha1rnds4_epu32(ABCD, Ea, F);               \
    Md = _mm_sha1msg1_epu32(Md, Ma);                       \
    Mc = _mm_xor_si128(Mc, Ma);
        FSS_SHA_STEP(E0, E1, MSG0, MSG1, MSG2, MSG3, 0)  // 16-19
        FSS_SHA_STEP(E1, E0, MSG1, MSG2, MSG3, MSG0, 1)  // 20-23
        FSS_SHA_STEP(E0, E1, MSG2, MSG3, MSG0, MSG1, 1)  // 24-27
        FSS_SHA_STEP(E1, E0, MSG3, MSG0, MSG1, MSG2, 1)  // 28-31
        FSS_SHA_STEP(E0, E1, MSG0, MSG1, MSG2, MSG3, 1)  // 32-35
        FSS_SHA_STEP(E1, E0, MSG1, MSG2, MSG3, MSG0, 1)  // 36-39
        FSS_SHA_STEP(E0, E1, MSG2, MSG3, MSG0, MSG1, 2)  // 40-43
        FSS_SHA_STEP(E1, E0, MSG3, MSG0, MSG1, MSG2, 2)  // 44-47
        FSS_SHA_STEP(E0, E1, MSG0, MSG1, MSG2, MSG3, 2)  // 48-51
        FSS_SHA_STEP(E1, E0, MSG1, MSG2, MSG3, MSG0, 2)  // 52-55
        FSS_SHA_STEP(E0, E1, MSG2, MSG3, MSG0, MSG1, 2)  // 56-59
        FSS_SHA_STEP(E1, E0, MSG3, MSG0, MSG1, MSG2, 3)  // 60-63
        FSS_SHA_STEP(E0, E1, MSG0, MSG1, MSG2, MSG3, 3)  // 64-67
#undef FSS_SHA_STEP
        // 68-71
        E1 = _mm_sha1nexte_epu32(E1, MSG1);
        E0 = ABCD;
        MSG2 = _mm_sha1msg2_epu32(MSG2, MSG1);
        ABCD = _mm_sha1rnds4_epu32(ABCD, E1, 3);
        MSG3 = _mm_xor_si128(MSG3, MSG1);
        // 72-75
        E0 = _mm_sha1nexte_epu32(E0, MSG2);
        E1 = ABCD;
        MSG3 = _mm_sha1msg2_epu32(MSG3, MSG2);
        ABCD = _mm_sha1rnds4_epu32(ABCD, E0, 3);
        // 76-79
        E1 = _mm_sha1nexte_epu32(E1, MSG3);
        E0 = ABCD;
        ABCD = _mm_sha1rnds4_epu32(ABCD, E1, 3);
        E0 = _mm_sha1nexte_epu32(E0, E0_SAVE);
        ABCD = _mm_add_epi32(ABCD, ABCD_SAVE);
    }
    ABCD = _mm_shuffle_epi32(ABCD, 0x1B);
    _mm_storeu_si128((__m128i *)st, ABCD);
    st[4] = (uint32_t)_mm_extract_epi32(E0, 3);
}

bool cpu_has_sha() {
    int r[4];
    __cpuid(r, 0);
    if (r[0] < 7) return false;
    __cpuid(r, 1);
    const bool ssse3 = ((r[2] >> 9) & 1) != 0, sse41 = ((r[2] >> 19) & 1) != 0;
    __cpuidex(r, 7, 0);
    return ssse3 && sse41 && ((r[1] >> 29) & 1) != 0;
}

class Sha1 {
  public:
    explicit Sha1(bool ni) : ni_(ni) {}
    void update(const void *data, size_t n) {
        const uint8_t *p = (const uint8_t *)data;
        total_ += n;
        if (fill_) {
            const size_t k = std::min(n, (size_t)64 - fill_);
            std::memcpy(buf_ + fill_, p, k);
            fill_ += k;
            p += k;
            n -= k;
            if (fill_ == 64) {
                blocks(buf_, 1);
                fill_ = 0;
            }
        }
        if (n >= 64) {
            blocks(p, n / 64);
            p += n / 64 * 64;
            n %= 64;
        }
        if (n) {
            std::memcpy(buf_, p, n);
            fill_ = n;
        }
    }
    void final(uint8_t out[20]) {
        const uint64_t bits = (uint64_t)total_ * 8;
        uint8_t pad[72] = {0x80};
        const size_t k = (fill_ < 56 ? 56 : 120) - fill_;
        uint8_t len[8];
        for (int i = 0; i < 8; i++) len[i] = (uint8_t)(bits >> (56 - 8 * i));
        update(pad, k);
        update(len, 8);
        for (int i = 0; i < 5; i++)
            for (int j = 0; j < 4; j++) out[4 * i + j] = (uint8_t)(st_[i] >> (24 - 8 * j));
    }

  private:
    void blocks(const uint8_t *p, size_t n) {
        if (ni_)
            sha1_blocks_ni(st_, p, n);
        else
            sha1_blocks_c(st_, p, n);
    }
    bool ni_;
    uint32_t st_[5] = {0x67452301u, 0xEFCDAB89u, 0x98BADCFEu, 0x10325476u, 0xC3D2E1F0u};
    uint8_t buf_[64] = {};
    size_t fill_ = 0;
    uint64_t total_ = 0;
};

// np.round(x, 4) + 0.0 as float32
inline float round4(double x) { return (float)(std::nearbyint(x * 10000.0) / 10000.0 + 0.0); }

const int64_t HASH_BLOCK = 16384;     // values converted at a time
const int64_t HASH_THREADED = 1 << 20;  // corner normal values from which threads convert them (fewer: one thread is
                                        // faster than starting threads, Session 5)

}  // namespace

extern "C" {

FSS_AO_COPY_API int32_t fss_ao_scene_near(const fss_ao_scene *S, int64_t n, const int64_t *rows, const int64_t *which,
                                          const double *distance, const int64_t *self_occ, int64_t threads,
                                          int64_t *offsets, int64_t *out_occ, double *out_gap, int64_t capacity,
                                          fss_ao_near_stats *stats) {
    if (check_scene(S) != FSS_AO_COPY_OK || n < 0 || threads < 1 || threads > 1024 || !offsets || capacity < 0 ||
        (n && (!rows || !which || !distance || !self_occ)) || (capacity && (!out_occ || !out_gap)))
        return FSS_AO_COPY_E_ARGS;
    for (int64_t q = 0; q < n; q++)
        if (rows[q] < 0 || rows[q] >= S->n_rows || (which[q] != 0 && which[q] != 1) || self_occ[q] < -1 ||
            self_occ[q] >= S->n_occ)
            return FSS_AO_COPY_E_ARGS;
    try {
        const int64_t R = S->n_rows, P = S->n_poses, K = S->n_occ;
        // every row's boxes: the world box now (its matrix after motion()), swept over the poses (moving), its bounds
        std::vector<RowBoxes> rb((size_t)std::max<int64_t>(R, 1));
        int32_t rc = parallel_for(R, 64, threads, [&](int64_t r) {
            RowBoxes &b = rb[(size_t)r];
            const double *c = S->corners + 24 * r;
            world_box(c, S->now + 16 * r, b.now_lo, b.now_hi);
            if (S->moving[r]) {
                swept_box(c, S->M + 16 * P * r, P, b.sw_lo, b.sw_hi);
            } else {
                std::memcpy(b.sw_lo, b.now_lo, sizeof b.sw_lo);
                std::memcpy(b.sw_hi, b.now_hi, sizeof b.sw_hi);
            }
            local_bounds(c, b.loc_lo, b.loc_hi);
        });
        if (rc != FSS_AO_COPY_OK) return rc;
        // the occluders' own boxes at every pose (pose 0: the current frame)
        std::vector<OBox> ob((size_t)std::max<int64_t>(K * P, 1));
        rc = parallel_for(K * P, 256, threads, [&](int64_t i) {
            const int64_t j = i / P, f = i % P, r = S->occ_rows[j];
            oriented_box(rb[(size_t)r].loc_lo, rb[(size_t)r].loc_hi, S->M + 16 * (P * r + f), S->ortho_tol,
                         ob[(size_t)i]);
        });
        if (rc != FSS_AO_COPY_OK) return rc;
        struct Out {
            std::vector<int64_t> occ;
            std::vector<double> gap;
            double cw = INF, co = INF;
            int64_t within = 0, wt = 0, ot = 0;
        };
        std::vector<Out> res((size_t)std::max<int64_t>(n, 1));
        rc = parallel_for(n, 4, threads, [&](int64_t q) {
            Out &o = res[(size_t)q];
            const int64_t r = rows[q];
            const bool swept = which[q] == 1;
            const double dist = distance[q];
            const RowBoxes &t = rb[(size_t)r];
            const double *lo = swept ? t.sw_lo : t.now_lo, *hi = swept ? t.sw_hi : t.now_hi;
            std::vector<int64_t> idx;
            std::vector<double> wgap;
            bool occ_moves = false;
            for (int64_t j = 0; j < K; j++) {
                const RowBoxes &b = rb[(size_t)S->occ_rows[j]];
                const double *olo = swept ? b.sw_lo : b.now_lo, *ohi = swept ? b.sw_hi : b.now_hi;
                double g = 0.0;
                bool nan = false;
                for (int i = 0; i < 3; i++) {
                    const double m = nmax(nmax(lo[i] - ohi[i], olo[i] - hi[i]), 0.0);
                    if (m != m) nan = true;
                    if (i == 0 || m > g) g = m;
                }
                if (nan) g = QNAN;
                if (j == self_occ[q]) continue;
                o.wt++;
                if (std::fabs(g - dist) < o.cw) o.cw = std::fabs(g - dist);
                if (std::fabs(g - dist) <= NEAR_TOL) o.within++;
                if (g <= dist) {
                    idx.push_back(j);
                    wgap.push_back(g);
                    if (S->moving[S->occ_rows[j]]) occ_moves = true;
                }
            }
            if (idx.empty()) return;
            const bool still = !swept || (!S->moving[r] && !occ_moves);
            std::vector<double> least(idx.size(), INF);
            for (int64_t f = 0; f < (still ? 1 : P); f++) {
                OBox tb;
                oriented_box(t.loc_lo, t.loc_hi, S->M + 16 * (P * r + f), S->ortho_tol, tb);
                if (!tb.ok) {  // no own box: the world box decides
                    std::fill(least.begin(), least.end(), 0.0);
                    break;
                }
                for (size_t i = 0; i < idx.size(); i++) {
                    const OBox &b = ob[(size_t)(idx[i] * P + f)];
                    const double g = b.ok ? oriented_gap(tb, b) : 0.0;
                    least[i] = nmin(least[i], g);
                }
            }
            for (size_t i = 0; i < idx.size(); i++) {
                o.ot++;
                const double dd = std::fabs(least[i] - dist);
                if (dd < o.co) o.co = dd;
                if (dd <= NEAR_TOL) o.within++;
                if (least[i] > dist) continue;
                o.occ.push_back(idx[i]);
                o.gap.push_back(nmax(wgap[i], least[i]));
            }
        });
        if (rc != FSS_AO_COPY_OK) return rc;
        int64_t total = 0;
        fss_ao_near_stats st = {INF, INF, 0, 0, 0};
        for (int64_t q = 0; q < n; q++) {
            offsets[q] = total;
            total += (int64_t)res[(size_t)q].occ.size();
            st.closest_world = std::min(st.closest_world, res[(size_t)q].cw);
            st.closest_own = std::min(st.closest_own, res[(size_t)q].co);
            st.within += res[(size_t)q].within;
            st.world_tests += res[(size_t)q].wt;
            st.own_tests += res[(size_t)q].ot;
        }
        offsets[n] = total;
        if (stats) *stats = st;
        if (total > capacity) return FSS_AO_COPY_E_SPACE;
        for (int64_t q = 0; q < n; q++) {
            const Out &o = res[(size_t)q];
            if (!o.occ.empty()) {
                std::memcpy(out_occ + offsets[q], o.occ.data(), o.occ.size() * sizeof(int64_t));
                std::memcpy(out_gap + offsets[q], o.gap.data(), o.gap.size() * sizeof(double));
            }
        }
        return FSS_AO_COPY_OK;
    } catch (const std::bad_alloc &) {
        return FSS_AO_COPY_E_MEMORY;
    } catch (...) {
        return FSS_AO_COPY_E_INTERNAL;
    }
}

FSS_AO_COPY_API int32_t fss_ao_scene_moves(const fss_ao_scene *S, int64_t n, const int64_t *pairs, const double *inv,
                                           int64_t threads, uint8_t *out, double *closest) {
    if (check_scene(S) != FSS_AO_COPY_OK || n < 0 || threads < 1 || threads > 1024 || (n && (!pairs || !out || !inv)))
        return FSS_AO_COPY_E_ARGS;
    for (int64_t i = 0; i < 2 * n; i++)
        if (pairs[i] < 0 || pairs[i] >= S->n_rows) return FSS_AO_COPY_E_ARGS;
    try {
        const int64_t P = S->n_poses;
        std::vector<double> margin((size_t)std::max<int64_t>(n, 1), INF);
        const int32_t rc = parallel_for(n, 64, threads, [&](int64_t k) {
            const int64_t a = pairs[2 * k], b = pairs[2 * k + 1];
            out[k] = 0;
            if (!(S->moving[a] || S->moving[b])) return;
            const double *Ma = S->M + 16 * P * a, *Mb = S->M + 16 * P * b, *Ia = inv + 16 * a;
            double rel[16];  // inv(Ma[0]) @ Mb[0]
            for (int i = 0; i < 4; i++)
                for (int j = 0; j < 4; j++)
                    rel[4 * i + j] = ((Ia[4 * i] * Mb[j] + Ia[4 * i + 1] * Mb[4 + j]) + Ia[4 * i + 2] * Mb[8 + j]) +
                                     Ia[4 * i + 3] * Mb[12 + j];
            double worst = 0.0;
            bool nan = false;
            for (int64_t p = 0; p < P; p++) {
                const double *A = Ma + 16 * p, *B = Mb + 16 * p;
                for (int i = 0; i < 4; i++)
                    for (int j = 0; j < 4; j++) {
                        const double v = ((A[4 * i] * rel[j] + A[4 * i + 1] * rel[4 + j]) + A[4 * i + 2] * rel[8 + j]) +
                                         A[4 * i + 3] * rel[12 + j];
                        const double d = std::fabs(v - B[4 * i + j]);
                        if (d != d) nan = true;
                        if (d > worst) worst = d;
                    }
            }
            if (nan) return;  // np.max is NaN: NaN > MOTION_TOL is False
            out[k] = (uint8_t)(worst > S->motion_tol ? 1 : 0);
            margin[(size_t)k] = std::fabs(worst - S->motion_tol);
        });
        if (rc != FSS_AO_COPY_OK) return rc;
        if (closest) {
            double c = INF;
            for (int64_t k = 0; k < n; k++) c = std::min(c, margin[(size_t)k]);
            *closest = c;
        }
        return FSS_AO_COPY_OK;
    } catch (const std::bad_alloc &) {
        return FSS_AO_COPY_E_MEMORY;
    } catch (...) {
        return FSS_AO_COPY_E_INTERNAL;
    }
}

FSS_AO_COPY_API int32_t fss_ao_scene_boxes(int64_t n, const double *lo, const double *hi, const double *mats,
                                           double ortho_tol, double *centres, double *axes, double *halves,
                                           uint8_t *ok) {
    if (n < 0 || (n && (!lo || !hi || !mats || !centres || !axes || !halves || !ok))) return FSS_AO_COPY_E_ARGS;
    for (int64_t i = 0; i < n; i++) {
        OBox b;
        oriented_box(lo + 3 * i, hi + 3 * i, mats + 16 * i, ortho_tol, b);
        std::memcpy(centres + 3 * i, b.c, sizeof b.c);
        std::memcpy(axes + 9 * i, b.U, sizeof b.U);
        std::memcpy(halves + 3 * i, b.e, sizeof b.e);
        ok[i] = (uint8_t)(b.ok ? 1 : 0);
    }
    return FSS_AO_COPY_OK;
}

FSS_AO_COPY_API int32_t fss_ao_scene_gaps(const double *centre, const double *axes, const double *halves, int64_t k,
                                          const double *centres, const double *others, const double *other_halves,
                                          double *out) {
    if (!centre || !axes || !halves || k < 0 || (k && (!centres || !others || !other_halves || !out)))
        return FSS_AO_COPY_E_ARGS;
    OBox A;
    std::memcpy(A.c, centre, sizeof A.c);
    std::memcpy(A.U, axes, sizeof A.U);
    std::memcpy(A.e, halves, sizeof A.e);
    A.ok = true;
    for (int64_t i = 0; i < k; i++) {
        OBox B;
        std::memcpy(B.c, centres + 3 * i, sizeof B.c);
        std::memcpy(B.U, others + 9 * i, sizeof B.U);
        std::memcpy(B.e, other_halves + 3 * i, sizeof B.e);
        B.ok = true;
        out[i] = oriented_gap(A, B);
    }
    return FSS_AO_COPY_OK;
}

FSS_AO_COPY_API int32_t fss_ao_mesh_hash(const int64_t *tris, int64_t n_tris, const double *co, int64_t n_co,
                                         const double *cn, int64_t n_cn, int64_t threads, int64_t impl,
                                         uint8_t *digest) {
    if (n_tris < 0 || n_co < 0 || n_cn < 0 || threads < 1 || threads > 1024 || impl < 0 || impl > 2 || !digest ||
        (n_tris && !tris) || (n_co && !co) || (n_cn && !cn))
        return FSS_AO_COPY_E_ARGS;
    try {
        const bool has = cpu_has_sha();
        if (impl == 2 && !has) return FSS_AO_COPY_E_UNSUPPORTED;
        Sha1 h(impl == 0 ? has : impl == 2);
        std::vector<int32_t> ib((size_t)std::min<int64_t>(std::max<int64_t>(n_tris, 1), HASH_BLOCK));
        for (int64_t s = 0; s < n_tris; s += HASH_BLOCK) {  // the triangles as int32 (numpy's cast: the low 32 bits)
            const int64_t e = std::min(n_tris, s + HASH_BLOCK);
            for (int64_t i = s; i < e; i++) ib[(size_t)(i - s)] = (int32_t)(uint32_t)(uint64_t)tris[i];
            h.update(ib.data(), (size_t)(e - s) * 4);
        }
        std::vector<float> fb((size_t)std::min<int64_t>(std::max<int64_t>(n_co, 1), HASH_BLOCK));
        for (int64_t s = 0; s < n_co; s += HASH_BLOCK) {  // the positions as float32
            const int64_t e = std::min(n_co, s + HASH_BLOCK);
            for (int64_t i = s; i < e; i++) fb[(size_t)(i - s)] = (float)co[i];
            h.update(fb.data(), (size_t)(e - s) * 4);
        }
        if (threads > 1 && n_cn >= HASH_THREADED) {  // the corner normals rounded on the threads, then hashed
            std::vector<float> all((size_t)n_cn);
            const int64_t jobs = (n_cn + HASH_BLOCK - 1) / HASH_BLOCK;
            const int32_t rc = parallel_for(jobs, 1, threads, [&](int64_t j) {
                const int64_t e = std::min(n_cn, (j + 1) * HASH_BLOCK);
                for (int64_t i = j * HASH_BLOCK; i < e; i++) all[(size_t)i] = round4(cn[i]);
            });
            if (rc != FSS_AO_COPY_OK) return rc;
            h.update(all.data(), (size_t)n_cn * 4);
        } else {
            fb.resize((size_t)std::min<int64_t>(std::max<int64_t>(n_cn, 1), HASH_BLOCK));
            for (int64_t s = 0; s < n_cn; s += HASH_BLOCK) {
                const int64_t e = std::min(n_cn, s + HASH_BLOCK);
                for (int64_t i = s; i < e; i++) fb[(size_t)(i - s)] = round4(cn[i]);
                h.update(fb.data(), (size_t)(e - s) * 4);
            }
        }
        h.final(digest);
        return FSS_AO_COPY_OK;
    } catch (const std::bad_alloc &) {
        return FSS_AO_COPY_E_MEMORY;
    } catch (...) {
        return FSS_AO_COPY_E_INTERNAL;
    }
}

}  // extern "C"
