// fss_uv_pack: the raster placement of UV islands for fss_blender_tools (native UV packer journal, step b).
//
// A port of fss_blender_tools/uv_fill.py (Grid, Shape, _place_once and the loop of repair) with the same rules, the
// same order of every search and tie-break and the same floating point operations, so the layouts equal the Python
// code's (tests/uv_fill_reference.py keeps that code for the comparison). Python keeps the cheap setup (the order of the
// islands, the cell size, the reach table) and calls these functions for the work.
//
// Built with /fp:precise and without /arch:AVX2 (no FMA contraction), as fss_ao_copy.

#include "fss_uv_pack.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <utility>
#include <vector>

namespace {

constexpr int BLOCK = 16;
constexpr int CHUNK = 128;
constexpr int LEVELS[6] = {2, 4, 8, 16, 32, 64};
constexpr int N_LEVELS = 6;
constexpr int RING_SAMPLES = 200;
constexpr int TOUCH_STEPS = 4;
constexpr int MAX_CANDIDATES = 2048;

typedef std::vector<uint8_t> Bytes;

struct Mask {
    int h = 0, w = 0;
    Bytes v;
    Mask() {}
    Mask(int h_, int w_) : h(h_), w(w_), v((size_t)h_ * (size_t)w_, 0) {}
    uint8_t at(int y, int x) const { return v[(size_t)y * w + x]; }
    uint8_t &at(int y, int x) { return v[(size_t)y * w + x]; }
};

// uv_fill.turned: points turned by turns x 90 degrees counter-clockwise
inline void turned(double x, double y, int turns, double &ox, double &oy) {
    switch (((turns % 4) + 4) % 4) {
    case 0: ox = x; oy = y; break;
    case 1: ox = -y; oy = x; break;
    case 2: ox = -x; oy = -y; break;
    default: ox = y; oy = -x; break;
    }
}

// uv_fill.spans + solid_mask: the cells the triangles T (k x 3 x 2, in cells, not negative) touch
Mask solid_of(const std::vector<double> &T) {
    const size_t k = T.size() / 6;
    struct Span { int64_t row, lo, hi; };
    std::vector<Span> spans;
    int64_t max_row = 0, max_hi = 0;
    std::vector<std::pair<int64_t, int64_t>> rowspan;  // per row of the triangle: (lo, hi)
    for (size_t t = 0; t < k; ++t) {
        const double *v = &T[t * 6];
        int64_t tri_r0 = INT64_MAX, tri_r1 = INT64_MIN;
        // first pass: the rows of the triangle
        for (int e = 0; e < 3; ++e) {
            double ay = v[e * 2 + 1], by = v[((e + 1) % 3) * 2 + 1];
            double py = ay > by ? by : ay, ry = ay > by ? ay : by;
            tri_r0 = std::min(tri_r0, (int64_t)std::floor(py));
            tri_r1 = std::max(tri_r1, (int64_t)std::floor(ry));
        }
        rowspan.assign((size_t)(tri_r1 - tri_r0 + 1), {INT64_MAX, INT64_MIN});
        for (int e = 0; e < 3; ++e) {
            double ax = v[e * 2], ay = v[e * 2 + 1];
            double bx = v[((e + 1) % 3) * 2], by = v[((e + 1) % 3) * 2 + 1];
            bool swap = ay > by;
            double px = swap ? bx : ax, py = swap ? by : ay;
            double rx = swap ? ax : bx, ry = swap ? ay : by;
            int64_t r0 = (int64_t)std::floor(py), r1 = (int64_t)std::floor(ry);
            double dy = ry - py, dx = rx - px;
            bool flat = dy <= 1e-12;
            double slope = flat ? 0.0 : dx / (flat ? 1.0 : dy);
            for (int64_t row = r0; row <= r1; ++row) {
                double rowf = (double)row;
                double xa = px + (std::max(py, rowf) - py) * slope;
                double xb = flat ? px + dx : px + (std::min(py + dy, rowf + 1.0) - py) * slope;
                double end = px + dx;
                int64_t lo = (int64_t)std::floor(std::max(std::min(xa, xb), std::min(px, end)));
                int64_t hi = (int64_t)std::floor(std::min(std::max(xa, xb), std::max(px, end)));
                auto &s = rowspan[(size_t)(row - tri_r0)];
                s.first = std::min(s.first, lo);
                s.second = std::max(s.second, hi);
            }
        }
        for (int64_t r = tri_r0; r <= tri_r1; ++r) {
            auto &s = rowspan[(size_t)(r - tri_r0)];
            if (s.first == INT64_MAX) continue;
            spans.push_back({r, s.first, s.second});
            max_row = std::max(max_row, r);
            max_hi = std::max(max_hi, s.second);
        }
    }
    Mask m((int)max_row + 1, (int)max_hi + 1);
    for (const Span &s : spans)
        for (int64_t x = s.lo; x <= s.hi; ++x) m.at((int)s.row, (int)x) = 1;
    return m;
}

struct Run { int r, s, n; };

// uv_fill.runs_of: the runs of a mask per row, spread over the rows (the order only speeds up the search)
std::vector<Run> runs_of(const Mask &m) {
    std::vector<Run> runs;
    for (int y = 0; y < m.h; ++y) {
        int x = 0;
        while (x < m.w) {
            if (!m.at(y, x)) { ++x; continue; }
            int s = x;
            while (x < m.w && m.at(y, x)) ++x;
            runs.push_back({y, s, x - s});
        }
    }
    std::stable_sort(runs.begin(), runs.end(), [](const Run &a, const Run &b) {
        int la = (a.r + 1) & -(a.r + 1), lb = (b.r + 1) & -(b.r + 1);
        if (la != lb) return la > lb;
        return a.n > b.n;
    });
    return runs;
}

// uv_fill.grown_mask: the mask grown by the reach table; its (0, 0) is the solid mask's (-pad, -pad)
Mask grown_of(const Mask &solid, const std::vector<int> &reach, int &pad) {
    const int L = (int)reach.size();
    pad = std::max(L - 1, reach[0]);
    Mask g(solid.h + 2 * pad, solid.w + 2 * pad);
    for (int y = 0; y < solid.h; ++y) {
        int x = 0;
        while (x < solid.w) {
            if (!solid.at(y, x)) { ++x; continue; }
            int s = x;
            while (x < solid.w && solid.at(y, x)) ++x;
            int n = x - s;
            for (int dy = -(L - 1); dy < L; ++dy) {
                int grow = reach[std::abs(dy)];
                int row = y + dy + pad;
                uint8_t *line = &g.v[(size_t)row * g.w];
                for (int c = s - grow + pad; c < s + n + grow + pad; ++c) line[c] = 1;
            }
        }
    }
    return g;
}

// uv_fill.probe_of: the largest level of a square the mask contains, and where (side, y, x)
void probe_of(const Mask &mask, int &side, int &py, int &px) {
    side = LEVELS[0]; py = 0; px = 0;
    Mask cur = mask;
    for (int li = 0; li < N_LEVELS; ++li) {
        int level = LEVELS[li], half = level / 2;
        if (std::min(cur.h, cur.w) <= half) break;
        Mask nxt(cur.h - half, cur.w - half);
        int wy = -1, wx = -1;
        for (int y = 0; y < nxt.h; ++y)
            for (int x = 0; x < nxt.w; ++x) {
                uint8_t b = cur.at(y, x) & cur.at(y + half, x) & cur.at(y, x + half) & cur.at(y + half, x + half);
                nxt.at(y, x) = b;
                if (b && wy < 0) { wy = y; wx = x; }
            }
        if (wy < 0) break;
        cur = std::move(nxt);
        side = level; py = wy; px = wx;
    }
}

// uv_fill.ring_of: cells just outside a mask (a sample of them), relative to its (0, 0)
void ring_of(const Mask &mask, std::vector<int> &ry, std::vector<int> &rx) {
    const int H = mask.h + 2, W = mask.w + 2;
    auto wide = [&](int y, int x) -> uint8_t {
        if (y < 1 || x < 1 || y > mask.h || x > mask.w) return 0;
        return mask.at(y - 1, x - 1);
    };
    std::vector<int> ay, ax;
    for (int y = 0; y < H; ++y)
        for (int x = 0; x < W; ++x) {
            if (wide(y, x)) continue;
            bool g = (y > 0 && wide(y - 1, x)) || (y < H - 1 && wide(y + 1, x)) || (x > 0 && wide(y, x - 1)) ||
                     (x < W - 1 && wide(y, x + 1));
            if (g) { ay.push_back(y); ax.push_back(x); }
        }
    size_t step = std::max(ay.size() / RING_SAMPLES, (size_t)1);
    ry.clear(); rx.clear();
    for (size_t i = 0; i < ay.size(); i += step) { ry.push_back(ay[i] - 1); rx.push_back(ax[i] - 1); }
}

struct Shape {
    int turn = 0;
    double low_x = 0, low_y = 0;
    Mask solid, mask;
    int inner_h = 0, inner_w = 0, pad = 0;
    std::vector<Run> runs;
    int side = 2, py = 0, px = 0;
    std::vector<int> ry, rx;
};

// uv_fill.Shape: local (k x 3 x 2, pixels from the island's low corner) at one turn
void make_shape(const double *local, size_t k, int turn, double cell, const std::vector<int> &reach, Shape &s) {
    s.turn = turn;
    std::vector<double> T(k * 6);
    double lx = INFINITY, ly = INFINITY;
    for (size_t i = 0; i < k * 3; ++i) {
        double ox, oy;
        turned(local[i * 2], local[i * 2 + 1], turn, ox, oy);
        T[i * 2] = ox; T[i * 2 + 1] = oy;
        lx = std::min(lx, ox); ly = std::min(ly, oy);
    }
    s.low_x = lx; s.low_y = ly;
    for (size_t i = 0; i < k * 3; ++i) {
        T[i * 2] = (T[i * 2] - lx) / cell;
        T[i * 2 + 1] = (T[i * 2 + 1] - ly) / cell;
    }
    s.solid = solid_of(T);
    s.inner_h = s.solid.h; s.inner_w = s.solid.w;
    s.mask = grown_of(s.solid, reach, s.pad);
    s.runs = runs_of(s.mask);
    probe_of(s.mask, s.side, s.py, s.px);
    ring_of(s.mask, s.ry, s.rx);
}

struct Found {
    bool ok = false;
    int64_t lowest = 0, y = 0, x = 0, touch = 0;
    bool inside = false;
};

// uv_fill.Grid
struct Grid {
    int c = 0, b = 0;
    Bytes occ, hole;
    std::vector<int16_t> run;
    Bytes free_sq[N_LEVELS];
    Bytes sq_any[N_LEVELS];
    std::vector<int32_t> hole_count;

    explicit Grid(int64_t cells) {
        c = (int)((cells / BLOCK + 1) * BLOCK);
        b = c / BLOCK;
        const size_t cc = (size_t)c * c;
        occ.assign(cc, 0);
        hole.assign(cc, 0);
        run.resize(cc);
        for (int y = 0; y < c; ++y)
            for (int x = 0; x < c; ++x) run[(size_t)y * c + x] = (int16_t)(c - x);
        for (int li = 0; li < N_LEVELS; ++li) {
            int level = LEVELS[li];
            free_sq[li].assign(cc, 0);
            for (int y = 0; y < c - level + 1; ++y)
                std::memset(&free_sq[li][(size_t)y * c], 1, (size_t)(c - level + 1));
            sq_any[li].assign((size_t)b * b, 0);
            for (int by = 0; by < b; ++by)
                for (int bx = 0; bx < b; ++bx) sq_any[li][(size_t)by * b + bx] = block_any(li, by, bx);
        }
        hole_count.assign((size_t)b * b, 0);
    }

    uint8_t block_any(int li, int by, int bx) const {
        const Bytes &f = free_sq[li];
        for (int iy = 0; iy < BLOCK; ++iy) {
            const uint8_t *p = &f[(size_t)(by * BLOCK + iy) * c + bx * BLOCK];
            for (int ix = 0; ix < BLOCK; ++ix)
                if (p[ix]) return 1;
        }
        return 0;
    }

    // Occupy a mask's cells with its (0, 0) at cell (y, x), inside the grid, and update the tables
    void paint(const Mask &mask, int y, int x) {
        const int h = mask.h, w = mask.w;
        for (int r = 0; r < h; ++r) {
            uint8_t *o = &occ[(size_t)(y + r) * c + x];
            const uint8_t *m = &mask.v[(size_t)r * w];
            for (int i = 0; i < w; ++i) o[i] |= m[i];
        }
        // free cells to the right, for the rows painted, up to the window's end
        for (int r = y; r < y + h; ++r) {
            int16_t *rr = &run[(size_t)r * c];
            const uint8_t *o = &occ[(size_t)r * c];
            int64_t next = (x + w >= c) ? c : (int64_t)(x + w) + rr[x + w];
            for (int xx = x + w - 1; xx >= 0; --xx) {
                if (o[xx]) next = xx;
                rr[xx] = (int16_t)(next - xx);
            }
        }
        // the free squares of every level
        int half = 1;
        const Bytes *below = nullptr;  // nullptr: the free cells (~occ)
        for (int li = 0; li < N_LEVELS; ++li) {
            int level = LEVELS[li];
            int y0 = std::max(y - level + 1, 0), x0 = std::max(x - level + 1, 0);
            int y1 = std::min(y + h, c - level + 1), x1 = std::min(x + w, c - level + 1);
            if (y1 > y0 && x1 > x0) {
                Bytes &f = free_sq[li];
                for (int yy = y0; yy < y1; ++yy)
                    for (int xx = x0; xx < x1; ++xx) {
                        auto B = [&](int a, int bb) -> uint8_t {
                            size_t i = (size_t)a * c + bb;
                            return below ? (*below)[i] : (uint8_t)!occ[i];
                        };
                        f[(size_t)yy * c + xx] = B(yy, xx) & B(yy + half, xx) & B(yy, xx + half) & B(yy + half, xx + half);
                    }
                int by0 = y0 / BLOCK, by1 = (y1 - 1) / BLOCK + 1, bx0 = x0 / BLOCK, bx1 = (x1 - 1) / BLOCK + 1;
                for (int by = by0; by < by1; ++by)
                    for (int bx = bx0; bx < bx1; ++bx) sq_any[li][(size_t)by * b + bx] = block_any(li, by, bx);
            }
            below = &free_sq[li];
            half = level;
        }
        // the island's own enclosed cells: free cells with the island in all four directions
        Mask lft(h, w), rgt(h, w), up(h, w), dn(h, w);
        for (int r = 0; r < h; ++r) {
            uint8_t a = 0;
            for (int i = 0; i < w; ++i) { a |= mask.at(r, i); lft.at(r, i) = a; }
            a = 0;
            for (int i = w - 1; i >= 0; --i) { a |= mask.at(r, i); rgt.at(r, i) = a; }
        }
        for (int i = 0; i < w; ++i) {
            uint8_t a = 0;
            for (int r = 0; r < h; ++r) { a |= mask.at(r, i); up.at(r, i) = a; }
            a = 0;
            for (int r = h - 1; r >= 0; --r) { a |= mask.at(r, i); dn.at(r, i) = a; }
        }
        for (int r = 0; r < h; ++r)
            for (int i = 0; i < w; ++i)
                if (lft.at(r, i) && rgt.at(r, i) && up.at(r, i) && dn.at(r, i) && !mask.at(r, i))
                    hole[(size_t)(y + r) * c + x + i] = 1;
        int by0 = y / BLOCK, by1 = (y + h - 1) / BLOCK + 1, bx0 = x / BLOCK, bx1 = (x + w - 1) / BLOCK + 1;
        for (int by = by0; by < by1; ++by)
            for (int bx = bx0; bx < bx1; ++bx) {
                int32_t n = 0;
                for (int iy = 0; iy < BLOCK; ++iy) {
                    size_t base = (size_t)(by * BLOCK + iy) * c + bx * BLOCK;
                    for (int ix = 0; ix < BLOCK; ++ix) n += hole[base + ix] && !occ[base + ix];
                }
                hole_count[(size_t)by * b + bx] = n;
            }
    }

    // The best position of a Shape (uv_fill.Grid.find)
    Found find(const Shape &s, int64_t extent, int64_t start) const {
        Found best;
        int li = 0;
        while (LEVELS[li] != s.side) ++li;
        const int p = s.pad, h = s.mask.h, w = s.mask.w;
        struct Hit { int by, bx; int64_t cost; bool no_hole; int diag; };
        std::vector<Hit> hits;
        for (int by = 0; by < b; ++by)
            for (int bx = 0; bx < b; ++bx)
                if (sq_any[li][(size_t)by * b + bx]) {
                    int64_t cost = std::max(std::max((int64_t)by * BLOCK - s.py + s.inner_h + p,
                                                     (int64_t)bx * BLOCK - s.px + s.inner_w + p), extent);
                    hits.push_back({by, bx, cost, hole_count[(size_t)by * b + bx] == 0, by + bx});
                }
        if (hits.empty()) return best;
        std::stable_sort(hits.begin(), hits.end(), [](const Hit &a, const Hit &bb) {
            if (a.cost != bb.cost) return a.cost < bb.cost;
            if (a.no_hole != bb.no_hole) return !a.no_hole;
            return a.diag < bb.diag;
        });
        const Bytes &f = free_sq[li];
        std::vector<int64_t> ys, xs;
        for (size_t c0 = 0; c0 < hits.size(); c0 += CHUNK) {
            size_t c1 = std::min(hits.size(), c0 + CHUNK);
            if (best.ok && hits[c0].cost >= best.lowest) break;
            ys.clear(); xs.clear();
            for (size_t q = c0; q < c1; ++q) {
                const Hit &hh = hits[q];
                for (int iy = 0; iy < BLOCK; ++iy)
                    for (int ix = 0; ix < BLOCK; ++ix) {
                        if (!f[(size_t)(hh.by * BLOCK + iy) * c + hh.bx * BLOCK + ix]) continue;
                        int64_t yy = (int64_t)hh.by * BLOCK + iy - s.py, xx = (int64_t)hh.bx * BLOCK + ix - s.px;
                        if (yy + p >= start && xx + p >= start && yy + h <= c && xx + w <= c) {
                            ys.push_back(yy); xs.push_back(xx);
                        }
                    }
            }
            // every run of the grown mask must lie on free cells
            size_t kept = ys.size();
            for (const Run &r : s.runs) {
                if (kept == 0) break;
                size_t o = 0;
                for (size_t i = 0; i < kept; ++i)
                    if (run[(size_t)(ys[i] + r.r) * c + xs[i] + r.s] >= r.n) { ys[o] = ys[i]; xs[o] = xs[i]; ++o; }
                kept = o;
            }
            if (kept == 0) continue;
            int64_t lowest = INT64_MAX;
            std::vector<int64_t> grown(kept);
            for (size_t i = 0; i < kept; ++i) {
                grown[i] = std::max(std::max(ys[i] + p + s.inner_h, xs[i] + p + s.inner_w), extent);
                lowest = std::min(lowest, grown[i]);
            }
            std::vector<size_t> m;
            for (size_t i = 0; i < kept; ++i)
                if (grown[i] == lowest) m.push_back(i);
            if (m.size() > (size_t)MAX_CANDIDATES) {
                size_t step = m.size() / (MAX_CANDIDATES / 2);
                std::vector<size_t> mm;
                for (size_t i = 0; i < m.size(); i += step) mm.push_back(m[i]);
                m.swap(mm);
            }
            const int L = std::max((int)s.ry.size(), 1);
            struct Cand { int64_t y, x, touch; bool inside; int64_t k_touch; };
            std::vector<Cand> cands;
            cands.reserve(m.size());
            for (size_t i : m) {
                int64_t yy = ys[i], xx = xs[i], touch = 0;
                for (size_t j = 0; j < s.ry.size(); ++j) {
                    int64_t cy = std::min(std::max(yy + s.ry[j], (int64_t)0), (int64_t)c - 1);
                    int64_t cx = std::min(std::max(xx + s.rx[j], (int64_t)0), (int64_t)c - 1);
                    touch += occ[(size_t)cy * c + cx];
                }
                bool inside = hole[(size_t)(yy + p + s.inner_h / 2) * c + xx + p + s.inner_w / 2] != 0;
                cands.push_back({yy, xx, touch, inside, -(touch * TOUCH_STEPS / L)});
            }
            // inside first, then the most contact (in quarters), then nearest the origin, then the lowest x
            size_t j = 0;
            for (size_t i = 1; i < cands.size(); ++i) {
                const Cand &a = cands[i], &bb = cands[j];
                if (a.inside != bb.inside) { if (a.inside) j = i; continue; }
                if (a.k_touch != bb.k_touch) { if (a.k_touch < bb.k_touch) j = i; continue; }
                if (a.y + a.x != bb.y + bb.x) { if (a.y + a.x < bb.y + bb.x) j = i; continue; }
                if (a.x < bb.x) j = i;
            }
            if (!best.ok || lowest < best.lowest) {
                best.ok = true; best.lowest = lowest; best.y = cands[j].y; best.x = cands[j].x;
                best.inside = cands[j].inside; best.touch = cands[j].touch;
            }
            if (lowest <= extent) break;
        }
        return best;
    }
};

// uv_fill._footprint: the cells triangles T (pixels from the origin) touch, with the row and column of its (0, 0) on a
// grid whose origin is `shift` cells in
Mask footprint(const double *tri, size_t k, double cell, int64_t shift, int64_t &y, int64_t &x) {
    double mx = INFINITY, my = INFINITY;
    for (size_t i = 0; i < k * 3; ++i) { mx = std::min(mx, tri[i * 2]); my = std::min(my, tri[i * 2 + 1]); }
    double cx = std::floor(mx / cell), cy = std::floor(my / cell);
    std::vector<double> T(k * 6);
    for (size_t i = 0; i < k * 3; ++i) {
        T[i * 2] = std::max((tri[i * 2] - cx * cell) / cell, 0.0);
        T[i * 2 + 1] = std::max((tri[i * 2 + 1] - cy * cell) / cell, 0.0);
    }
    y = (int64_t)cy + shift;
    x = (int64_t)cx + shift;
    return solid_of(T);
}

// uv_fill._window: the part of a mask at (y, x) that lies on a square of `size` cells
bool window(int h, int w, int64_t y, int64_t x, int64_t size, int &sy, int &sx, int &ey, int &ex) {
    sy = (int)std::max(-y, (int64_t)0); sx = (int)std::max(-x, (int64_t)0);
    ey = (int)std::min((int64_t)h, size - y); ex = (int)std::min((int64_t)w, size - x);
    return ey > sy && ex > sx;
}

Mask crop(const Mask &m, int sy, int sx, int ey, int ex) {
    Mask out(ey - sy, ex - sx);
    for (int r = sy; r < ey; ++r) std::memcpy(&out.v[(size_t)(r - sy) * out.w], &m.v[(size_t)r * m.w + sx], (size_t)(ex - sx));
    return out;
}

void paint_footprint(Grid &g, const Mask &solid, int64_t y, int64_t x) {
    int sy, sx, ey, ex;
    if (window(solid.h, solid.w, y, x, g.c, sy, sx, ey, ex)) g.paint(crop(solid, sy, sx, ey, ex), (int)(y + sy), (int)(x + sx));
}

std::vector<int> reach_vec(const int32_t *reach, int64_t n) { return std::vector<int>(reach, reach + n); }

}  // namespace

extern "C" {

FSS_UV_API int32_t fss_uv_pack_version(void) { return FSS_UV_PACK_VERSION; }

FSS_UV_API int32_t fss_uv_solid(const double *T, int64_t k, uint8_t *out, int64_t capacity, int64_t *h,
                                int64_t *w) {
    try {
        std::vector<double> v(T, T + k * 6);
        Mask m = solid_of(v);
        *h = m.h;
        *w = m.w;
        if ((int64_t)m.v.size() > capacity) return 0;
        std::memcpy(out, m.v.data(), m.v.size());
        return 1;
    } catch (...) {
        return -1;
    }
}

FSS_UV_API int32_t fss_uv_place_once(const double *tri, const int64_t *start, int64_t n, const double *lo,
                                     const int64_t *order, int64_t n_order, const uint8_t *can_turn, double gap,
                                     double cell, const int32_t *reach, int64_t n_reach, int64_t grid_cells,
                                     const int64_t *fixed_ids, int64_t n_fixed, int32_t *turns, double *offset) {
    (void)n;
    try {
        const std::vector<int> rv = reach_vec(reach, n_reach);
        const int64_t shift = std::max((int64_t)rv.size() - 1, (int64_t)rv[0]) + 1;
        const int64_t first = shift + (int64_t)std::ceil(0.5 * gap / cell);
        Grid grid(grid_cells);
        int64_t extent = shift;
        for (int64_t f = 0; f < n_fixed; ++f) {
            int64_t i = fixed_ids[f], y, x;
            Mask solid = footprint(tri + start[i] * 6, (size_t)(start[i + 1] - start[i]), cell, shift, y, x);
            paint_footprint(grid, solid, y, x);
            extent = std::max(extent, std::min(std::max(y + solid.h, x + solid.w), (int64_t)grid.c));
        }
        std::vector<double> local;
        for (int64_t oi = 0; oi < n_order; ++oi) {
            const int64_t i = order[oi];
            const size_t k = (size_t)(start[i + 1] - start[i]);
            local.resize(k * 6);
            for (size_t j = 0; j < k * 3; ++j) {
                local[j * 2] = tri[start[i] * 6 + j * 2] - lo[i * 2];
                local[j * 2 + 1] = tri[start[i] * 6 + j * 2 + 1] - lo[i * 2 + 1];
            }
            bool have = false;
            Shape best_shape;
            Found best_pos;
            int64_t bk0 = 0; bool bk1 = false; double bk2 = 0; int64_t bk3 = 0; int bk4 = 0;
            for (int t = 0; t < (can_turn[i] ? 2 : 1); ++t) {
                Shape shape;
                make_shape(local.data(), k, t, cell, rv, shape);
                Found pos = grid.find(shape, extent, first);
                if (!pos.ok) continue;
                int64_t k0 = pos.lowest; bool k1 = !pos.inside;
                double k2 = -(double)pos.touch / (double)std::max((int)shape.ry.size(), 1);
                int64_t k3 = pos.y + pos.x;
                bool better = !have || k0 < bk0 || (k0 == bk0 && (k1 < bk1 || (k1 == bk1 && (k2 < bk2 ||
                              (k2 == bk2 && (k3 < bk3 || (k3 == bk3 && t < bk4)))))));
                if (better) {
                    have = true; bk0 = k0; bk1 = k1; bk2 = k2; bk3 = k3; bk4 = t;
                    best_shape = std::move(shape); best_pos = pos;
                }
            }
            if (!have) return 0;
            extent = best_pos.lowest;
            grid.paint(best_shape.solid, (int)(best_pos.y + best_shape.pad), (int)(best_pos.x + best_shape.pad));
            turns[i] = best_shape.turn;
            offset[i * 2] = (double)(best_pos.x + best_shape.pad - shift) * cell - best_shape.low_x;
            offset[i * 2 + 1] = (double)(best_pos.y + best_shape.pad - shift) * cell - best_shape.low_y;
        }
        return 1;
    } catch (...) {
        return -1;
    }
}

FSS_UV_API int32_t fss_uv_repair(const double *tri, const int64_t *start, int64_t n, const double *lo,
                                 const double *key, uint8_t *inside, const uint8_t *fixed, const uint8_t *active,
                                 const uint8_t *can_turn, double gap, double cell, const int32_t *reach,
                                 int64_t n_reach, int64_t half, double lim_x, double lim_y, uint8_t *moved,
                                 int32_t *turns, double *offset, int64_t *left, int64_t *n_left) {
    (void)gap;  // the columns of the islands left outside are laid out in Python
    try {
        const std::vector<int> rv = reach_vec(reach, n_reach);
        const int64_t shift = std::max((int64_t)rv.size() - 1, (int64_t)rv[0]) + 1;
        const int64_t first = shift + half;
        const int64_t wall_x = shift + (int64_t)std::floor(lim_x / cell) + half;
        const int64_t wall_y = shift + (int64_t)std::floor(lim_y / cell) + half;
        const int64_t wall = std::max(wall_x, wall_y);
        Grid grid(wall + shift + BLOCK);
        const int64_t cells = grid.c;
        {
            Mask a((int)cells, (int)(cells - wall_x));
            std::fill(a.v.begin(), a.v.end(), (uint8_t)1);
            grid.paint(a, 0, (int)wall_x);
            Mask bb((int)(cells - wall_y), (int)wall_x);
            std::fill(bb.v.begin(), bb.v.end(), (uint8_t)1);
            grid.paint(bb, (int)wall_y, 0);
        }
        bool any_fixed = false;
        for (int64_t i = 0; i < n; ++i) any_fixed |= fixed[i] != 0;
        if (any_fixed) {
            Bytes forbidden((size_t)cells * cells, 0);
            for (int64_t i = 0; i < n; ++i) {
                if (!fixed[i]) continue;
                int64_t y, x;
                Mask solid = footprint(tri + start[i] * 6, (size_t)(start[i + 1] - start[i]), cell, shift, y, x);
                paint_footprint(grid, solid, y, x);
                int pad;
                Mask grown = grown_of(solid, rv, pad);
                int sy, sx, ey, ex;
                if (window(grown.h, grown.w, y - pad, x - pad, cells, sy, sx, ey, ex)) {
                    int64_t wy = y - pad + sy, wx = x - pad + sx;
                    for (int r = sy; r < ey; ++r)
                        for (int q = sx; q < ex; ++q)
                            if (grown.at(r, q)) forbidden[(size_t)(wy + r - sy) * cells + wx + q - sx] = 1;
                }
            }
            for (int64_t i = 0; i < n; ++i) {
                if (!inside[i]) continue;
                int64_t y, x;
                Mask solid = footprint(tri + start[i] * 6, (size_t)(start[i + 1] - start[i]), cell, shift, y, x);
                int sy, sx, ey, ex;
                if (!window(solid.h, solid.w, y, x, cells, sy, sx, ey, ex)) continue;
                int64_t wy = y + sy, wx = x + sx;
                bool hit = false;
                for (int r = sy; r < ey && !hit; ++r)
                    for (int q = sx; q < ex; ++q)
                        if (solid.at(r, q) && forbidden[(size_t)(wy + r - sy) * cells + wx + q - sx]) { hit = true; break; }
                if (hit) inside[i] = 0;
            }
            bool any_out = false;
            for (int64_t i = 0; i < n; ++i) any_out |= active[i] && !fixed[i] && !inside[i];
            if (!any_out) { *n_left = 0; return 2; }
        }
        for (int64_t i = 0; i < n; ++i) {
            if (!inside[i]) continue;
            int64_t y, x;
            Mask solid = footprint(tri + start[i] * 6, (size_t)(start[i + 1] - start[i]), cell, shift, y, x);
            paint_footprint(grid, solid, y, x);
        }
        std::vector<int64_t> out_ids;
        for (int64_t i = 0; i < n; ++i)
            if (active[i] && !fixed[i] && !inside[i]) out_ids.push_back(i);
        std::stable_sort(out_ids.begin(), out_ids.end(), [&](int64_t a, int64_t bb) { return -key[a] < -key[bb]; });
        int64_t nl = 0;
        std::vector<double> local;
        for (int64_t i : out_ids) {
            const size_t k = (size_t)(start[i + 1] - start[i]);
            local.resize(k * 6);
            for (size_t j = 0; j < k * 3; ++j) {
                local[j * 2] = tri[start[i] * 6 + j * 2] - lo[i * 2];
                local[j * 2 + 1] = tri[start[i] * 6 + j * 2 + 1] - lo[i * 2 + 1];
            }
            bool have = false;
            Shape best_shape;
            Found best_pos;
            double best_low[2] = {0, 0};
            int64_t bk0 = 0; bool bk1 = false; double bk2 = 0; int64_t bk3 = 0; int bk4 = 0;
            for (int t = 0; t < (can_turn[i] ? 2 : 1); ++t) {
                Shape shape;
                make_shape(local.data(), k, t, cell, rv, shape);
                Found pos = grid.find(shape, wall, first);
                if (!pos.ok) continue;
                double low_x = (double)(pos.x + shape.pad - shift) * cell;
                double low_y = (double)(pos.y + shape.pad - shift) * cell;
                // np.ptp of the turned island
                double mnx = INFINITY, mny = INFINITY, mxx = -INFINITY, mxy = -INFINITY;
                for (size_t j = 0; j < k * 3; ++j) {
                    double ox, oy;
                    turned(local[j * 2], local[j * 2 + 1], t, ox, oy);
                    mnx = std::min(mnx, ox); mxx = std::max(mxx, ox); mny = std::min(mny, oy); mxy = std::max(mxy, oy);
                }
                if (low_x < 0.0 || low_y < 0.0 || low_x + (mxx - mnx) > lim_x || low_y + (mxy - mny) > lim_y) continue;
                int64_t k0 = pos.lowest; bool k1 = !pos.inside;
                double k2 = -(double)pos.touch / (double)std::max((int)shape.ry.size(), 1);
                int64_t k3 = pos.y + pos.x;
                bool better = !have || k0 < bk0 || (k0 == bk0 && (k1 < bk1 || (k1 == bk1 && (k2 < bk2 ||
                              (k2 == bk2 && (k3 < bk3 || (k3 == bk3 && t < bk4)))))));
                if (better) {
                    have = true; bk0 = k0; bk1 = k1; bk2 = k2; bk3 = k3; bk4 = t;
                    best_shape = std::move(shape); best_pos = pos; best_low[0] = low_x; best_low[1] = low_y;
                }
            }
            if (!have) { left[nl++] = i; continue; }
            grid.paint(best_shape.solid, (int)(best_pos.y + best_shape.pad), (int)(best_pos.x + best_shape.pad));
            moved[i] = 1;
            turns[i] = best_shape.turn;
            offset[i * 2] = best_low[0] - best_shape.low_x;
            offset[i * 2 + 1] = best_low[1] - best_shape.low_y;
        }
        *n_left = nl;
        return 1;
    } catch (...) {
        return -1;
    }
}

}  // extern "C"
