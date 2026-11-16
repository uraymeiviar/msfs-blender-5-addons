// fss_ao_open: a master opened for Apply (see fss_ao_copy_open_master in fss_ao_copy.h).
//
// The Python code it replaces (fss_blender_tools/ao_bake_core.py, open_master with _TiledSink, _TiledWriter and
// map_rows; ao_bake_jxl.py, decode_rows) writes two tiled page files; this file writes the same bytes:
// - the image: libjxl (the add-on's lib/jxl/windows-x64 DLLs, loaded here by their full paths and declared by hand as
//   ao_bake_jxl.py declares them, libjxl 0.12) decodes the file, read 4 MiB at a time, with its thread runner; its
//   multithreaded image-out callback copies each piece of a row straight into the tiles of its row of tiles;
// - the map: the .ao.map's zlib stream (zlib 1.3.2 compiled in, native/third_party/zlib) inflated row by row from the
//   top, each row copied into its tiles;
// - the page files: created with FILE_ATTRIBUTE_TEMPORARY, sized (zeros), filled through a mapped view of one row of
//   tiles at a time (mapped when its first pixel comes, unmapped when its last has come), so the process maps only
//   the rows of tiles being filled, never the whole file.
// The bytes do not depend on the thread count: every pixel has one place in the file, written once.

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
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <functional>
#include <mutex>
#include <new>
#include <string>
#include <thread>
#include <vector>

#include "../third_party/zlib/zlib.h"

namespace {

const size_t READ_CHUNK = (size_t)4 << 20;  // bytes of a file read at a time (ao_bake_jxl.READ_CHUNK)
const int64_t MAP_ROWS = 64;                // rows of the map inflated at a time
const char MAP_MAGIC[8] = {'F', 'S', 'S', 'A', 'O', 'M', 'A', 'P'};

// ---------------------------------------------------------------------------------------------------------------------
// libjxl 0.12's C API, the part used here (jxl/decode.h, codestream_header.h, types.h, thread_parallel_runner.h)
// ---------------------------------------------------------------------------------------------------------------------

const int JXL_DEC_SUCCESS = 0, JXL_DEC_ERROR = 1, JXL_DEC_NEED_MORE_INPUT = 2, JXL_DEC_NEED_IMAGE_OUT_BUFFER = 5;
const int JXL_DEC_BASIC_INFO = 0x40, JXL_DEC_FULL_IMAGE = 0x1000;
const int JXL_TYPE_UINT16 = 3, JXL_LITTLE_ENDIAN = 1;

struct JxlPixelFormat {
    uint32_t num_channels;
    int data_type;
    int endianness;
    size_t align;
};

struct JxlBasicInfo {
    int have_container;
    uint32_t xsize, ysize, bits_per_sample, exponent_bits_per_sample;
    float intensity_target, min_nits;
    int relative_to_max_display;
    float linear_below;
    int uses_original_profile, have_preview, have_animation, orientation;
    uint32_t num_color_channels, num_extra_channels, alpha_bits, alpha_exponent_bits;
    int alpha_premultiplied;
    uint32_t preview_xsize, preview_ysize;
    uint32_t tps_numerator, tps_denominator, num_loops;
    int have_timecodes;
    uint32_t intrinsic_xsize, intrinsic_ysize;
    uint8_t padding[100];
};

typedef void *(*ImageOutInit)(void *init_opaque, size_t num_threads, size_t num_pixels_per_thread);
typedef void (*ImageOutRun)(void *run_opaque, size_t thread_id, size_t x, size_t y, size_t num_pixels,
                            const void *pixels);
typedef void (*ImageOutDestroy)(void *run_opaque);

struct Jxl {
    HMODULE jxl = nullptr, threads = nullptr;
    void *(*DecoderCreate)(const void *) = nullptr;
    void (*DecoderDestroy)(void *) = nullptr;
    int (*DecoderSetParallelRunner)(void *, void *, void *) = nullptr;
    int (*DecoderSubscribeEvents)(void *, int) = nullptr;
    int (*DecoderSetInput)(void *, const uint8_t *, size_t) = nullptr;
    size_t (*DecoderReleaseInput)(void *) = nullptr;
    void (*DecoderCloseInput)(void *) = nullptr;
    int (*DecoderProcessInput)(void *) = nullptr;
    int (*DecoderGetBasicInfo)(const void *, JxlBasicInfo *) = nullptr;
    int (*DecoderSetMultithreadedImageOutCallback)(void *, const JxlPixelFormat *, ImageOutInit, ImageOutRun,
                                                   ImageOutDestroy, void *) = nullptr;
    void *ParallelRunner = nullptr;  // JxlThreadParallelRunner, handed to the decoder as it is
    void *(*RunnerCreate)(const void *, size_t) = nullptr;
    void (*RunnerDestroy)(void *) = nullptr;

    ~Jxl() {
        if (jxl) FreeLibrary(jxl);
        if (threads) FreeLibrary(threads);
    }
};

template <class F>
bool sym(HMODULE h, const char *name, F &fn) {
    FARPROC p = GetProcAddress(h, name);
    if (!p) return false;
    fn = reinterpret_cast<F>(reinterpret_cast<void *>(p));
    return true;
}

// ---------------------------------------------------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------------------------------------------------

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

// The first error of a job (thread safe: the decoder's threads may report one each)
struct Failure {
    std::mutex mu;
    int32_t code = FSS_AO_COPY_OK;
    std::string text;
    std::atomic<bool> any{false};

    void set(int32_t c, const std::string &t) {
        std::lock_guard<std::mutex> lock(mu);
        if (code == FSS_AO_COPY_OK) {
            code = c;
            text = t;
        }
        any.store(true);
    }
};

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

// ---------------------------------------------------------------------------------------------------------------------
// A tiled page file, filled through views of one row of tiles each
// ---------------------------------------------------------------------------------------------------------------------

struct PageFile {
    std::wstring path;
    std::string name;  // the path in UTF-8, for messages
    HANDLE file = INVALID_HANDLE_VALUE, mapping = nullptr;
    bool created = false;
    int64_t W = 0, H = 0, T = 0, elem = 0, ntx = 0, nty = 0, row_bytes = 0, gran = 65536;
    struct Row {
        uint8_t *base = nullptr;  // the view (from an allocation-granularity offset)
        uint8_t *data = nullptr;  // the row of tiles in it
        int64_t got = 0;          // pixels received
        int64_t busy = 0;         // writers copying into it now
    };
    std::vector<Row> rows;
    std::mutex mu;
    int64_t open = 0, most_open = 0;

    bool create(const wchar_t *p, int64_t w, int64_t h, int64_t tile, int64_t e, Failure &fail) {
        path = p;
        name = utf8(path);
        W = w;
        H = h;
        T = tile;
        elem = e;
        ntx = (W + T - 1) / T;
        nty = (H + T - 1) / T;
        row_bytes = ntx * T * T * elem;
        SYSTEM_INFO si;
        GetSystemInfo(&si);
        gran = (int64_t)si.dwAllocationGranularity;
        rows.assign((size_t)nty, Row());
        file = CreateFileW(p, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_DELETE, nullptr, CREATE_ALWAYS,
                           FILE_ATTRIBUTE_TEMPORARY, nullptr);
        if (file == INVALID_HANDLE_VALUE) {
            fail.set(FSS_AO_COPY_E_IO, name + ": not created: " + win_error(GetLastError()));
            return false;
        }
        created = true;
        LARGE_INTEGER size;
        size.QuadPart = row_bytes * nty;
        if (!SetFilePointerEx(file, size, nullptr, FILE_BEGIN) || !SetEndOfFile(file)) {
            fail.set(FSS_AO_COPY_E_IO, fmt("%s: not sized to %lld bytes: %s", name.c_str(), (long long)size.QuadPart,
                                           win_error(GetLastError()).c_str()));
            return false;
        }
        mapping = CreateFileMappingW(file, nullptr, PAGE_READWRITE, (DWORD)((uint64_t)size.QuadPart >> 32),
                                     (DWORD)((uint64_t)size.QuadPart & 0xffffffffu), nullptr);
        if (!mapping) {
            fail.set(FSS_AO_COPY_E_IO, name + ": not mapped: " + win_error(GetLastError()));
            return false;
        }
        return true;
    }

    // the row of tiles ty mapped (the lock held)
    uint8_t *map_row(int64_t ty, Failure &fail) {
        Row &r = rows[(size_t)ty];
        if (!r.data) {
            int64_t off = ty * row_bytes;
            int64_t base = off - off % gran;
            void *v = MapViewOfFile(mapping, FILE_MAP_WRITE, (DWORD)((uint64_t)base >> 32),
                                    (DWORD)((uint64_t)base & 0xffffffffu), (SIZE_T)(off - base + row_bytes));
            if (!v) {
                fail.set(FSS_AO_COPY_E_IO, fmt("%s: row of tiles %lld not mapped: %s", name.c_str(), (long long)ty,
                                               win_error(GetLastError()).c_str()));
                return nullptr;
            }
            r.base = (uint8_t *)v;
            r.data = r.base + (off - base);
            open++;
            most_open = std::max(most_open, open);
        }
        return r.data;
    }

    void unmap_row(Row &r) {
        if (r.base) {
            UnmapViewOfFile(r.base);
            r.base = r.data = nullptr;
            open--;
        }
    }

    int64_t row_pixels(int64_t ty) const { return W * std::min(T, H - ty * T); }

    // n values (elem bytes each) of array row j from column x, copied into their tiles
    bool put(int64_t j, int64_t x, int64_t n, const uint8_t *src, Failure &fail) {
        const int64_t ty = j / T, local = j - ty * T;
        uint8_t *data;
        {
            std::lock_guard<std::mutex> lock(mu);
            data = map_row(ty, fail);
            if (!data) return false;
            rows[(size_t)ty].busy++;
        }
        int64_t p = x, left = n;
        while (left > 0) {
            const int64_t tx = p / T, in = p - tx * T, k = std::min(left, T - in);
            std::memcpy(data + ((tx * T + local) * T + in) * elem, src, (size_t)(k * elem));
            src += k * elem;
            p += k;
            left -= k;
        }
        {
            std::lock_guard<std::mutex> lock(mu);
            Row &r = rows[(size_t)ty];
            r.busy--;
            r.got += n;
            if (r.got >= row_pixels(ty) && r.busy == 0) unmap_row(r);
        }
        return true;
    }

    // rows of tiles not complete
    int64_t incomplete() const {
        int64_t k = 0;
        for (int64_t ty = 0; ty < nty; ty++)
            if (rows[(size_t)ty].got < row_pixels(ty)) k++;
        return k;
    }

    void close() {
        for (Row &r : rows) unmap_row(r);
        if (mapping) CloseHandle(mapping);
        mapping = nullptr;
        if (file != INVALID_HANDLE_VALUE) CloseHandle(file);
        file = INVALID_HANDLE_VALUE;
    }

    void remove() {
        close();
        if (created) DeleteFileW(path.c_str());
        created = false;
    }
};

// A file read in pieces
struct Reader {
    HANDLE h = INVALID_HANDLE_VALUE;
    ~Reader() {
        if (h != INVALID_HANDLE_VALUE) CloseHandle(h);
    }
    bool open(const std::wstring &p, const std::string &name, Failure &fail) {
        h = CreateFileW(p.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
                        OPEN_EXISTING, FILE_FLAG_SEQUENTIAL_SCAN, nullptr);
        if (h == INVALID_HANDLE_VALUE) {
            fail.set(FSS_AO_COPY_E_IO, name + ": not opened: " + win_error(GetLastError()));
            return false;
        }
        return true;
    }
    // bytes read into buf (0 at the end), -1 on an error
    int64_t read(uint8_t *buf, size_t n, const std::string &name, Failure &fail) {
        size_t done = 0;
        while (done < n) {
            DWORD want = (DWORD)std::min<size_t>(n - done, (size_t)1 << 30), got = 0;
            if (!ReadFile(h, buf + done, want, &got, nullptr)) {
                fail.set(FSS_AO_COPY_E_IO, name + ": not read: " + win_error(GetLastError()));
                return -1;
            }
            if (got == 0) break;
            done += got;
        }
        return (int64_t)done;
    }
};

// ---------------------------------------------------------------------------------------------------------------------
// The image: libjxl into the uint16 page file
// ---------------------------------------------------------------------------------------------------------------------

struct ImageJob {
    const Jxl *lib;
    std::wstring path;
    std::string name;
    PageFile *page;
    int64_t W, H, runner_threads;
    Failure *fail;
    double seconds = 0;
};

void image_out(void *opaque, size_t /*thread_id*/, size_t x, size_t y, size_t n, const void *pixels) {
    ImageJob *job = (ImageJob *)opaque;
    if (job->fail->any.load()) return;
    try {
        if ((int64_t)y >= job->H || (int64_t)(x + n) > job->W) {
            job->fail->set(FSS_AO_COPY_E_FORMAT, fmt("%s: a piece of row %llu outside the image", job->name.c_str(),
                                                     (unsigned long long)y));
            return;
        }
        job->page->put(job->H - 1 - (int64_t)y, (int64_t)x, (int64_t)n, (const uint8_t *)pixels, *job->fail);
    } catch (...) {
        job->fail->set(FSS_AO_COPY_E_INTERNAL, job->name + ": the image's callback failed");
    }
}

void *image_out_init(void *opaque, size_t, size_t) { return opaque; }
void image_out_destroy(void *) {}

void run_image(ImageJob &job) {
    const double t0 = now();
    const Jxl &L = *job.lib;
    Failure &fail = *job.fail;
    Reader in;
    if (!in.open(job.path, job.name, fail)) return;
    void *dec = L.DecoderCreate(nullptr);
    void *runner = L.RunnerCreate(nullptr, (size_t)job.runner_threads);
    try {
        if (!dec || !runner) {
            fail.set(FSS_AO_COPY_E_MEMORY, job.name + ": the JPEG XL decoder or its runner not created");
        } else if (L.DecoderSetParallelRunner(dec, L.ParallelRunner, runner) != JXL_DEC_SUCCESS) {
            fail.set(FSS_AO_COPY_E_INTERNAL, job.name + ": JxlDecoderSetParallelRunner failed");
        } else if (L.DecoderSubscribeEvents(dec, JXL_DEC_BASIC_INFO | JXL_DEC_FULL_IMAGE) != JXL_DEC_SUCCESS) {
            fail.set(FSS_AO_COPY_E_INTERNAL, job.name + ": JxlDecoderSubscribeEvents failed");
        } else {
            std::vector<uint8_t> buf;
            size_t have = 0;
            bool given = false, eof = false;
            const JxlPixelFormat format = {1, JXL_TYPE_UINT16, JXL_LITTLE_ENDIAN, 0};
            for (;;) {
                int status = L.DecoderProcessInput(dec);
                if (fail.any.load()) break;
                if (status == JXL_DEC_NEED_MORE_INPUT) {
                    size_t rest = given ? L.DecoderReleaseInput(dec) : 0;
                    if (eof) {
                        fail.set(FSS_AO_COPY_E_FORMAT, job.name + ": the file ends before the image");
                        break;
                    }
                    rest = std::min(rest, have);
                    if (rest) std::memmove(buf.data(), buf.data() + (have - rest), rest);
                    buf.resize(rest + READ_CHUNK);
                    int64_t got = in.read(buf.data() + rest, READ_CHUNK, job.name, fail);
                    if (got < 0) break;
                    have = rest + (size_t)got;
                    if (L.DecoderSetInput(dec, buf.data(), have) != JXL_DEC_SUCCESS) {
                        fail.set(FSS_AO_COPY_E_INTERNAL, job.name + ": JxlDecoderSetInput failed");
                        break;
                    }
                    given = true;
                    if (got == 0) {  // the rest given, then the input closed: a truncated file ends with an error
                        eof = true;
                        L.DecoderCloseInput(dec);
                    }
                } else if (status == JXL_DEC_BASIC_INFO) {
                    JxlBasicInfo info;
                    std::memset(&info, 0, sizeof(info));
                    if (L.DecoderGetBasicInfo(dec, &info) != JXL_DEC_SUCCESS) {
                        fail.set(FSS_AO_COPY_E_FORMAT, job.name + ": JxlDecoderGetBasicInfo failed");
                        break;
                    }
                    if (info.num_color_channels != 1 || info.num_extra_channels || info.bits_per_sample != 16) {
                        fail.set(FSS_AO_COPY_E_FORMAT,
                                 fmt("%s: %u colour channel(s), %u extra, %u bits: not a 16-bit grey master",
                                     job.name.c_str(), info.num_color_channels, info.num_extra_channels,
                                     info.bits_per_sample));
                        break;
                    }
                    if ((int64_t)info.xsize != job.W || (int64_t)info.ysize != job.H) {
                        fail.set(FSS_AO_COPY_E_FORMAT,
                                 fmt("%s: %u x %u px, the layout says %lld x %lld", job.name.c_str(), info.xsize,
                                     info.ysize, (long long)job.W, (long long)job.H));
                        break;
                    }
                } else if (status == JXL_DEC_NEED_IMAGE_OUT_BUFFER) {
                    if (L.DecoderSetMultithreadedImageOutCallback(dec, &format, image_out_init, image_out,
                                                                  image_out_destroy, &job) != JXL_DEC_SUCCESS) {
                        fail.set(FSS_AO_COPY_E_INTERNAL,
                                 job.name + ": JxlDecoderSetMultithreadedImageOutCallback failed");
                        break;
                    }
                } else if (status == JXL_DEC_FULL_IMAGE) {
                    continue;
                } else if (status == JXL_DEC_SUCCESS) {
                    break;
                } else if (status == JXL_DEC_ERROR) {
                    fail.set(FSS_AO_COPY_E_FORMAT, job.name + ": not decoded (decoder error)");
                    break;
                } else {
                    fail.set(FSS_AO_COPY_E_FORMAT, fmt("%s: unexpected decoder status %d", job.name.c_str(), status));
                    break;
                }
            }
            if (!fail.any.load()) {
                int64_t k = job.page->incomplete();
                if (k) fail.set(FSS_AO_COPY_E_FORMAT, fmt("%s: %lld rows of tiles incomplete", job.page->name.c_str(),
                                                          (long long)k));
            }
        }
    } catch (const std::bad_alloc &) {
        fail.set(FSS_AO_COPY_E_MEMORY, job.name + ": out of memory");
    } catch (...) {
        fail.set(FSS_AO_COPY_E_INTERNAL, job.name + ": internal error");
    }
    if (dec) L.DecoderDestroy(dec);
    if (runner) L.RunnerDestroy(runner);
    job.seconds = now() - t0;
}

// ---------------------------------------------------------------------------------------------------------------------
// The map: zlib into the int32 page file
// ---------------------------------------------------------------------------------------------------------------------

struct MapJob {
    std::wstring path;
    std::string name;
    PageFile *page;
    int64_t W, H;
    Failure *fail;
    double seconds = 0;
};

void run_map(MapJob &job) {
    const double t0 = now();
    Failure &fail = *job.fail;
    Reader in;
    z_stream zs;
    std::memset(&zs, 0, sizeof(zs));
    bool zinit = false;
    try {
        if (!in.open(job.path, job.name, fail)) return;
        uint8_t head[24];
        int64_t got = in.read(head, sizeof(head), job.name, fail);
        if (got < 0) return;
        if (got < (int64_t)sizeof(head) || std::memcmp(head, MAP_MAGIC, 8) != 0) {
            fail.set(FSS_AO_COPY_E_FORMAT, job.name + ": not an AO map");
            return;
        }
        uint32_t v[4];
        std::memcpy(v, head + 8, 16);
        if ((int64_t)v[1] != job.W || (int64_t)v[2] != job.H) {
            fail.set(FSS_AO_COPY_E_FORMAT, fmt("%s: %u x %u px, the layout says %lld x %lld", job.name.c_str(), v[1],
                                               v[2], (long long)job.W, (long long)job.H));
            return;
        }
        if (inflateInit(&zs) != Z_OK) {
            fail.set(FSS_AO_COPY_E_MEMORY, job.name + ": zlib not initialized");
            return;
        }
        zinit = true;
        const int64_t rowlen = 4 * job.W;
        std::vector<uint8_t> src(READ_CHUNK), out((size_t)(rowlen * MAP_ROWS));
        int64_t done = 0;    // rows placed
        size_t filled = 0;   // bytes of out holding inflated data
        bool eof = false, end = false;
        while (done < job.H && !fail.any.load()) {
            if (zs.avail_in == 0 && !eof && !end) {
                int64_t n = in.read(src.data(), src.size(), job.name, fail);
                if (n < 0) break;
                if (n == 0) eof = true;
                zs.next_in = src.data();
                zs.avail_in = (uInt)n;
            }
            zs.next_out = out.data() + filled;
            zs.avail_out = (uInt)(out.size() - filled);
            const uInt before = zs.avail_out;
            int rc = end ? Z_STREAM_END : inflate(&zs, Z_NO_FLUSH);
            if (rc == Z_STREAM_END) {
                end = true;
            } else if (rc == Z_BUF_ERROR) {
                // no progress: input used up (more is read above) or, at the end of the file, a truncated stream
            } else if (rc != Z_OK) {
                fail.set(FSS_AO_COPY_E_FORMAT, fmt("%s: the zlib stream is corrupt (%s)", job.name.c_str(),
                                                   zs.msg ? zs.msg : "zlib error"));
                break;
            }
            filled += before - zs.avail_out;
            int64_t whole = (int64_t)(filled / (size_t)rowlen);
            int64_t k = std::min(whole, job.H - done);
            for (int64_t r = 0; r < k; r++)
                if (!job.page->put(job.H - 1 - (done + r), 0, job.W, out.data() + r * rowlen, fail)) break;
            if (fail.any.load()) break;
            done += k;
            size_t used = (size_t)(whole * rowlen);
            if (used && filled > used) std::memmove(out.data(), out.data() + used, filled - used);
            filled -= used;
            if (done >= job.H) break;
            if ((end || eof) && before == zs.avail_out && zs.avail_in == 0) {
                fail.set(FSS_AO_COPY_E_FORMAT,
                         fmt("%s: %lld of %lld rows", job.name.c_str(), (long long)done, (long long)job.H));
                break;
            }
        }
    } catch (const std::bad_alloc &) {
        fail.set(FSS_AO_COPY_E_MEMORY, job.name + ": out of memory");
    } catch (...) {
        fail.set(FSS_AO_COPY_E_INTERNAL, job.name + ": internal error");
    }
    if (zinit) inflateEnd(&zs);
    job.seconds = now() - t0;
}

void message_out(char *message, int64_t size, const std::string &text) {
    if (!message || size <= 0) return;
    size_t n = std::min<size_t>(text.size(), (size_t)(size - 1));
    // do not cut a UTF-8 sequence
    while (n > 0 && n < text.size() && ((unsigned char)text[n] & 0xC0) == 0x80) n--;
    std::memcpy(message, text.data(), n);
    message[n] = 0;
}

bool load_jxl(const wchar_t *dir, Jxl &L, Failure &fail) {
    std::wstring d(dir);
    if (!d.empty() && d.back() != L'\\' && d.back() != L'/') d += L'\\';
    const std::wstring pj = d + L"jxl.dll", pt = d + L"jxl_threads.dll";
    L.jxl = LoadLibraryExW(pj.c_str(), nullptr, LOAD_WITH_ALTERED_SEARCH_PATH);
    if (!L.jxl) {
        fail.set(FSS_AO_COPY_E_LIBRARY, utf8(pj) + ": not loaded: " + win_error(GetLastError()));
        return false;
    }
    L.threads = LoadLibraryExW(pt.c_str(), nullptr, LOAD_WITH_ALTERED_SEARCH_PATH);
    if (!L.threads) {
        fail.set(FSS_AO_COPY_E_LIBRARY, utf8(pt) + ": not loaded: " + win_error(GetLastError()));
        return false;
    }
    bool ok = sym(L.jxl, "JxlDecoderCreate", L.DecoderCreate) && sym(L.jxl, "JxlDecoderDestroy", L.DecoderDestroy) &&
              sym(L.jxl, "JxlDecoderSetParallelRunner", L.DecoderSetParallelRunner) &&
              sym(L.jxl, "JxlDecoderSubscribeEvents", L.DecoderSubscribeEvents) &&
              sym(L.jxl, "JxlDecoderSetInput", L.DecoderSetInput) &&
              sym(L.jxl, "JxlDecoderReleaseInput", L.DecoderReleaseInput) &&
              sym(L.jxl, "JxlDecoderCloseInput", L.DecoderCloseInput) &&
              sym(L.jxl, "JxlDecoderProcessInput", L.DecoderProcessInput) &&
              sym(L.jxl, "JxlDecoderGetBasicInfo", L.DecoderGetBasicInfo) &&
              sym(L.jxl, "JxlDecoderSetMultithreadedImageOutCallback", L.DecoderSetMultithreadedImageOutCallback) &&
              sym(L.threads, "JxlThreadParallelRunnerCreate", L.RunnerCreate) &&
              sym(L.threads, "JxlThreadParallelRunnerDestroy", L.RunnerDestroy);
    FARPROC runner = GetProcAddress(L.threads, "JxlThreadParallelRunner");
    L.ParallelRunner = reinterpret_cast<void *>(runner);
    if (!ok || !runner) {
        fail.set(FSS_AO_COPY_E_LIBRARY, utf8(pj) + ": a function of libjxl 0.12 is missing");
        return false;
    }
    return true;
}

}  // namespace

extern "C" {

FSS_AO_COPY_API int32_t fss_ao_copy_open_master(const wchar_t *jxl_dir, const wchar_t *image, const wchar_t *map,
                                                const wchar_t *page_image, const wchar_t *page_map, int64_t W,
                                                int64_t H, int64_t tile, int64_t threads, fss_ao_open_stats *stats,
                                                char *message, int64_t message_size) {
    if (message && message_size > 0) message[0] = 0;
    if (stats) std::memset(stats, 0, sizeof(*stats));
    if (!jxl_dir || !image || !map || !page_image || !page_map || W <= 0 || H <= 0 || W > (1 << 30) ||
        H > (1 << 30) || tile <= 0 || (tile & (tile - 1)) != 0 || tile > 4096 || threads < 1 || threads > 1024) {
        message_out(message, message_size, "fss_ao_copy_open_master: bad arguments");
        return FSS_AO_COPY_E_ARGS;
    }
    const double t0 = now();
    Failure fail;
    PageFile pimg, pmap;
    int32_t rc = FSS_AO_COPY_OK;
    try {
        Jxl lib;
        const bool side = threads > 1;  // the map beside the decode, on one of the threads
        const int64_t runner_threads = side ? threads - 1 : 1;
        ImageJob ij{&lib, image, utf8(image), &pimg, W, H, runner_threads, &fail};
        MapJob mj{map, utf8(map), &pmap, W, H, &fail};
        if (load_jxl(jxl_dir, lib, fail) && pimg.create(page_image, W, H, tile, 2, fail) &&
            pmap.create(page_map, W, H, tile, 4, fail)) {
            if (side) {
                std::thread mt;
                bool started = false;
                try {
                    mt = std::thread(run_map, std::ref(mj));
                    started = true;
                } catch (...) {
                    fail.set(FSS_AO_COPY_E_INTERNAL, "the map's thread did not start");
                }
                if (started) {
                    run_image(ij);
                    mt.join();
                }
            } else {
                run_image(ij);
                if (!fail.any.load()) run_map(mj);
            }
        }
        if (stats) {
            stats->image_seconds = ij.seconds;
            stats->map_seconds = mj.seconds;
            stats->decode_threads = runner_threads;
            stats->threads = side ? threads : 1;
            stats->most_open_tile_rows = pimg.most_open;
        }
        pimg.close();
        pmap.close();
    } catch (const std::bad_alloc &) {
        fail.set(FSS_AO_COPY_E_MEMORY, "out of memory");
    } catch (...) {
        fail.set(FSS_AO_COPY_E_INTERNAL, "internal error");
    }
    if (fail.code != FSS_AO_COPY_OK) {
        pimg.remove();
        pmap.remove();
        rc = fail.code;
        message_out(message, message_size, fail.text);
    }
    if (stats) stats->seconds = now() - t0;
    return rc;
}

}  // extern "C"
