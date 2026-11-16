// fss_ao_png: PNG files for Apply and the bake (see fss_ao_png_* in fss_ao_copy.h; apply-native-copy journal, Session 7).
//
// The writer replaces fss_blender_tools/ao_bake_core.py's PngRowWriter for the same pixels (decision 4: the file's bytes
// differ, its pixels do not): signature, IHDR, filter 0 on every row, IDAT chunks, IEND; one zlib stream at level 6.
// The filtered stream is cut into blocks of BLOCK bytes at fixed offsets (not at the rows handed in); each block is
// compressed as raw deflate on a worker thread with the DICT bytes before it as its dictionary and ended with a sync
// flush, the last one finished (the method of pigz); the blocks are written in order, one IDAT chunk each, the zlib
// header before the first and the Adler-32 of the whole stream (combined from the blocks') after the last. The bytes
// therefore depend on the pixels only, not on the thread count or the blocking of the rows. write() copies the rows
// into the current block and returns; a full block goes to a bounded queue (write() waits while it is full), so the
// caller builds its next rows while the workers compress, and nothing in proportion to the image is held.
//
// The reader replaces read_png (PngRows): grey, grey + alpha, RGB and RGBA at 8 or 16 bits, every filter (None, Sub,
// Up, Average, Paeth), into the caller's (H, W, C) uint16 array, row 0 at the bottom. Inflating is serial; with two
// threads or more the unfiltering runs beside it on a second thread. A palette, interlace or another depth gives
// FSS_AO_COPY_E_UNSUPPORTED (Python then reads the file another way).

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
#include <condition_variable>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <map>
#include <memory>
#include <mutex>
#include <new>
#include <string>
#include <thread>
#include <vector>

#include "../third_party/zlib/zlib.h"

namespace {

const int64_t BLOCK = (int64_t)512 << 10;  // bytes of the filtered stream per compressed block (fixed: the file's bytes
                                           // depend on it)
const int64_t DICT = 32768;                // the bytes before a block given as its dictionary
const int64_t MAX_THREADS = 1024;          // threads accepted at most
const int64_t QUEUE_MAX = 64;              // blocks in flight at most (each about 1 MiB with its output)
const int LEVEL = 6;
const size_t READ_CHUNK = (size_t)4 << 20;  // bytes of a file read at a time
const uint8_t SIGNATURE[8] = {0x89, 'P', 'N', 'G', 0x0d, 0x0a, 0x1a, 0x0a};

// ---------------------------------------------------------------------------------------------------------------------
// Errors and small helpers
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
    while (n > 0 && n < text.size() && ((unsigned char)text[n] & 0xC0) == 0x80) n--;  // not inside a UTF-8 sequence
    std::memcpy(message, text.data(), n);
    message[n] = 0;
}

// The first error (thread safe)
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
    std::string get_text() {
        std::lock_guard<std::mutex> lock(mu);
        return text;
    }
};

void put_be32(uint8_t *p, uint32_t v) {
    p[0] = (uint8_t)(v >> 24);
    p[1] = (uint8_t)(v >> 16);
    p[2] = (uint8_t)(v >> 8);
    p[3] = (uint8_t)v;
}

uint32_t get_be32(const uint8_t *p) {
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | (uint32_t)p[3];
}

// A chunk: length, tag, data, CRC-32 of tag and data
void append_chunk(std::vector<uint8_t> &out, const char *tag, const uint8_t *data, size_t n) {
    const size_t at = out.size();
    out.resize(at + 12 + n);
    uint8_t *p = out.data() + at;
    put_be32(p, (uint32_t)n);
    std::memcpy(p + 4, tag, 4);
    if (n) std::memcpy(p + 8, data, n);
    uLong crc = crc32_z(0L, p + 4, 4 + n);
    put_be32(p + 8 + n, (uint32_t)crc);
}

int colour_type(int64_t channels) {
    switch (channels) {
        case 1: return 0;
        case 2: return 4;
        case 3: return 2;
        case 4: return 6;
        default: return -1;
    }
}

int64_t channels_of(int ct) {
    switch (ct) {
        case 0: return 1;
        case 4: return 2;
        case 2: return 3;
        case 6: return 4;
        default: return 0;
    }
}

}  // namespace

// ---------------------------------------------------------------------------------------------------------------------
// The writer
// ---------------------------------------------------------------------------------------------------------------------

struct fss_ao_png_writer {
    struct Job {
        int64_t index = 0, raw_len = 0;  // raw_len: bytes of the filtered stream (kept after `in` is released)
        bool last = false;
        std::vector<uint8_t> in, dict, out;
        uint32_t adler = 1;
    };

    std::wstring path;
    std::string name;
    HANDLE file = INVALID_HANDLE_VALUE;
    bool created = false, closed = false;
    int64_t W = 0, H = 0, bits = 0, C = 0, rowlen = 0, total = 0, n_workers = 0, bound = 0;
    // the caller's side
    int64_t rows_in = 0, pos = 0, next_index = 0;
    std::unique_ptr<Job> cur;
    std::vector<uint8_t> tail, rowbuf;
    double t0 = 0, wait_seconds = 0;
    // shared
    std::mutex mu;
    std::condition_variable cv_work, cv_space;
    std::deque<std::unique_ptr<Job>> todo;
    std::map<int64_t, std::unique_ptr<Job>> ready;
    int64_t next_write = 0, inflight = 0, most_inflight = 0;
    bool writing = false, stop = false;
    std::vector<std::thread> workers;
    Failure fail;
    // the writing worker's (one at a time)
    uint32_t adler = 1;
    int64_t file_bytes = 0, limit = -1;
    std::vector<uint8_t> chunk_buf;

    void new_block() {
        cur.reset(new Job());
        cur->in.reserve((size_t)std::min(BLOCK, total));
    }

    bool raw_write(const uint8_t *p, size_t n) {
        if (limit >= 0 && file_bytes + (int64_t)n > limit) {  // tests: a full disk
            fail.set(FSS_AO_COPY_E_IO, name + ": not written: " + win_error(ERROR_DISK_FULL));
            return false;
        }
        size_t done = 0;
        while (done < n) {
            DWORD want = (DWORD)std::min<size_t>(n - done, (size_t)1 << 30), got = 0;
            if (!WriteFile(file, p + done, want, &got, nullptr) || got == 0) {
                fail.set(FSS_AO_COPY_E_IO, name + ": not written: " + win_error(GetLastError()));
                return false;
            }
            done += got;
        }
        file_bytes += (int64_t)n;
        return true;
    }

    void compress(z_stream &zs, Job &job) {
        if (deflateReset(&zs) != Z_OK) {
            fail.set(FSS_AO_COPY_E_INTERNAL, name + ": deflateReset failed");
            return;
        }
        if (!job.dict.empty() && deflateSetDictionary(&zs, job.dict.data(), (uInt)job.dict.size()) != Z_OK) {
            fail.set(FSS_AO_COPY_E_INTERNAL, name + ": deflateSetDictionary failed");
            return;
        }
        job.out.resize((size_t)deflateBound(&zs, (uLong)job.in.size()) + 64);
        zs.next_in = job.in.data();
        zs.avail_in = (uInt)job.in.size();
        size_t have = 0;
        for (;;) {
            zs.next_out = job.out.data() + have;
            zs.avail_out = (uInt)(job.out.size() - have);
            int rc = deflate(&zs, job.last ? Z_FINISH : Z_SYNC_FLUSH);
            have = job.out.size() - zs.avail_out;
            if (rc == Z_STREAM_ERROR) {
                fail.set(FSS_AO_COPY_E_INTERNAL, name + ": deflate failed");
                return;
            }
            const bool done = job.last ? rc == Z_STREAM_END : (zs.avail_in == 0 && zs.avail_out > 0);
            if (done) break;
            job.out.resize(job.out.size() * 2);
        }
        job.out.resize(have);
        job.adler = (uint32_t)adler32_z(1L, job.in.data(), job.in.size());
        std::vector<uint8_t>().swap(job.in);
        std::vector<uint8_t>().swap(job.dict);
    }

    void write_block(Job &job) {
        chunk_buf.clear();
        std::vector<uint8_t> data;
        data.reserve(job.out.size() + 6);
        if (job.index == 0) {  // the zlib header: deflate, 32 KiB window, level 6 (FLEVEL 2), no dictionary
            data.push_back(0x78);
            data.push_back(0x9C);
        }
        data.insert(data.end(), job.out.begin(), job.out.end());
        adler = (uint32_t)adler32_combine(adler, job.adler, (z_off_t)job.raw_len);
        if (job.last) {
            uint8_t a[4];
            put_be32(a, adler);
            data.insert(data.end(), a, a + 4);
        }
        append_chunk(chunk_buf, "IDAT", data.data(), data.size());
        raw_write(chunk_buf.data(), chunk_buf.size());
    }

    void work() {
        z_stream zs;
        std::memset(&zs, 0, sizeof(zs));
        const bool ok = deflateInit2(&zs, LEVEL, Z_DEFLATED, -15, 8, Z_DEFAULT_STRATEGY) == Z_OK;
        if (!ok) fail.set(FSS_AO_COPY_E_MEMORY, name + ": zlib's deflate not initialized");
        for (;;) {
            std::unique_ptr<Job> job;
            {
                std::unique_lock<std::mutex> lock(mu);
                cv_work.wait(lock, [&] { return stop || !todo.empty(); });
                if (todo.empty()) break;
                job = std::move(todo.front());
                todo.pop_front();
            }
            if (ok && !fail.any.load()) {
                try {
                    compress(zs, *job);
                } catch (const std::bad_alloc &) {
                    fail.set(FSS_AO_COPY_E_MEMORY, name + ": out of memory");
                } catch (...) {
                    fail.set(FSS_AO_COPY_E_INTERNAL, name + ": internal error");
                }
            }
            std::unique_lock<std::mutex> lock(mu);
            const int64_t index = job->index;
            ready[index] = std::move(job);
            if (writing) continue;
            writing = true;  // this worker writes every block that is next in order
            for (;;) {
                auto it = ready.find(next_write);
                if (it == ready.end()) break;
                std::unique_ptr<Job> j = std::move(it->second);
                ready.erase(it);
                lock.unlock();
                if (!fail.any.load()) {
                    try {
                        write_block(*j);
                    } catch (const std::bad_alloc &) {
                        fail.set(FSS_AO_COPY_E_MEMORY, name + ": out of memory");
                    } catch (...) {
                        fail.set(FSS_AO_COPY_E_INTERNAL, name + ": internal error");
                    }
                }
                j.reset();
                lock.lock();
                next_write++;
                inflight--;
                cv_space.notify_all();
            }
            writing = false;
        }
        if (ok) deflateEnd(&zs);
    }

    // the current block to the queue (waits while the queue is full)
    void submit() {
        std::unique_ptr<Job> job = std::move(cur);
        job->index = next_index++;
        job->last = pos == total;
        job->raw_len = (int64_t)job->in.size();
        job->dict = tail;
        const size_t k = (size_t)std::min<int64_t>(DICT, (int64_t)job->in.size());
        tail.assign(job->in.end() - (ptrdiff_t)k, job->in.end());
        {
            std::unique_lock<std::mutex> lock(mu);
            if (inflight >= bound && !fail.any.load()) {
                const double t = now();
                cv_space.wait(lock, [&] { return inflight < bound || fail.any.load(); });
                wait_seconds += now() - t;
            }
            inflight++;
            most_inflight = std::max(most_inflight, inflight);
            todo.push_back(std::move(job));
        }
        cv_work.notify_one();
        if (pos < total) new_block();
    }

    void append(const uint8_t *src, int64_t n) {
        while (n > 0 && !fail.any.load()) {
            const int64_t room = BLOCK - (int64_t)cur->in.size();
            const int64_t k = std::min(room, n);
            cur->in.insert(cur->in.end(), src, src + k);
            src += k;
            n -= k;
            pos += k;
            if ((int64_t)cur->in.size() == BLOCK || pos == total) submit();
        }
    }

    // the workers stopped and joined
    void stop_workers() {
        {
            std::lock_guard<std::mutex> lock(mu);
            stop = true;
        }
        cv_work.notify_all();
        for (std::thread &t : workers)
            if (t.joinable()) t.join();
        workers.clear();
    }

    // closed; on an error (or when told) the file removed
    void finish(bool remove) {
        stop_workers();
        if (file != INVALID_HANDLE_VALUE) CloseHandle(file);
        file = INVALID_HANDLE_VALUE;
        if (remove && created) DeleteFileW(path.c_str());
        created = false;
        closed = true;
    }
};

extern "C" {

FSS_AO_COPY_API int32_t fss_ao_png_open(const wchar_t *path, int64_t W, int64_t H, int64_t bits, int64_t channels,
                                        int64_t threads, fss_ao_png_writer **writer, char *message,
                                        int64_t message_size) {
    if (message && message_size > 0) message[0] = 0;
    if (writer) *writer = nullptr;
    if (!path || !writer || W <= 0 || H <= 0 || W > 0x7fffffff || H > 0x7fffffff || (bits != 8 && bits != 16) ||
        channels < 1 || channels > 4 || threads < 1) {
        message_out(message, message_size, "fss_ao_png_open: bad arguments");
        return FSS_AO_COPY_E_ARGS;
    }
    fss_ao_png_writer *w = nullptr;
    try {
        w = new fss_ao_png_writer();
        w->t0 = now();
        w->path = path;
        w->name = utf8(w->path);
        w->W = W;
        w->H = H;
        w->bits = bits;
        w->C = channels;
        w->rowlen = 1 + W * channels * (bits / 8);
        w->total = w->rowlen * H;
        const int64_t blocks = (w->total + BLOCK - 1) / BLOCK;
        const int64_t t = std::min(threads, MAX_THREADS);
        w->bound = std::max<int64_t>(2, std::min<int64_t>(2 * t, QUEUE_MAX));
        w->n_workers = std::max<int64_t>(1, std::min({t, w->bound, blocks}));
        w->rowbuf.assign((size_t)w->rowlen, 0);
        w->file = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ, nullptr, CREATE_ALWAYS,
                              FILE_ATTRIBUTE_NORMAL | FILE_FLAG_SEQUENTIAL_SCAN, nullptr);
        if (w->file == INVALID_HANDLE_VALUE) {
            const std::string text = w->name + ": not created: " + win_error(GetLastError());
            delete w;
            message_out(message, message_size, text);
            return FSS_AO_COPY_E_IO;
        }
        w->created = true;
        std::vector<uint8_t> head(SIGNATURE, SIGNATURE + 8);
        uint8_t ihdr[13];
        put_be32(ihdr, (uint32_t)W);
        put_be32(ihdr + 4, (uint32_t)H);
        ihdr[8] = (uint8_t)bits;
        ihdr[9] = (uint8_t)colour_type(channels);
        ihdr[10] = ihdr[11] = ihdr[12] = 0;
        append_chunk(head, "IHDR", ihdr, sizeof(ihdr));
        if (w->raw_write(head.data(), head.size())) {
            w->new_block();
            for (int64_t i = 0; i < w->n_workers; i++) w->workers.emplace_back(&fss_ao_png_writer::work, w);
        }
    } catch (const std::bad_alloc &) {
        if (w) w->fail.set(FSS_AO_COPY_E_MEMORY, "out of memory");
    } catch (...) {
        if (w) w->fail.set(FSS_AO_COPY_E_INTERNAL, w->name + ": a thread did not start");
    }
    if (!w) {
        message_out(message, message_size, "out of memory");
        return FSS_AO_COPY_E_MEMORY;
    }
    if (w->fail.any.load()) {
        const int32_t rc = w->fail.code;
        const std::string text = w->fail.get_text();
        w->finish(true);
        delete w;
        message_out(message, message_size, text);
        return rc;
    }
    *writer = w;
    return FSS_AO_COPY_OK;
}

FSS_AO_COPY_API int32_t fss_ao_png_write(fss_ao_png_writer *w, const void *rows, int64_t n, char *message,
                                         int64_t message_size) {
    if (message && message_size > 0) message[0] = 0;
    if (!w || (n > 0 && !rows) || n < 0) {
        message_out(message, message_size, "fss_ao_png_write: bad arguments");
        return FSS_AO_COPY_E_ARGS;
    }
    if (!w->closed && !w->fail.any.load()) {
        try {
            if (w->rows_in + n > w->H) {
                w->fail.set(FSS_AO_COPY_E_ARGS, fmt("%s: %lld rows handed in, the image has %lld", w->name.c_str(),
                                                    (long long)(w->rows_in + n), (long long)w->H));
            } else {
                const int64_t per_row = w->W * w->C;
                uint8_t *dst = w->rowbuf.data() + 1;
                for (int64_t r = 0; r < n && !w->fail.any.load(); r++) {
                    w->rowbuf[0] = 0;  // filter None
                    if (w->bits == 16) {
                        const uint16_t *s = (const uint16_t *)rows + r * per_row;
                        for (int64_t i = 0; i < per_row; i++) {
                            const uint16_t v = s[i];
                            dst[2 * i] = (uint8_t)(v >> 8);
                            dst[2 * i + 1] = (uint8_t)v;
                        }
                    } else {
                        std::memcpy(dst, (const uint8_t *)rows + r * per_row, (size_t)per_row);
                    }
                    w->append(w->rowbuf.data(), w->rowlen);
                    w->rows_in++;
                }
            }
        } catch (const std::bad_alloc &) {
            w->fail.set(FSS_AO_COPY_E_MEMORY, w->name + ": out of memory");
        } catch (...) {
            w->fail.set(FSS_AO_COPY_E_INTERNAL, w->name + ": internal error");
        }
    }
    if (w->fail.any.load()) {
        if (!w->closed) w->finish(true);  // the error closes and removes the file; close or abort frees the handle
        message_out(message, message_size, w->fail.get_text());
        return w->fail.code;
    }
    return FSS_AO_COPY_OK;
}

FSS_AO_COPY_API int32_t fss_ao_png_close(fss_ao_png_writer *w, fss_ao_png_stats *stats, char *message,
                                         int64_t message_size) {
    if (message && message_size > 0) message[0] = 0;
    if (stats) std::memset(stats, 0, sizeof(*stats));
    if (!w) {
        message_out(message, message_size, "fss_ao_png_close: bad arguments");
        return FSS_AO_COPY_E_ARGS;
    }
    try {
        if (!w->closed && !w->fail.any.load()) {
            if (w->rows_in != w->H) {
                w->fail.set(FSS_AO_COPY_E_ARGS, fmt("%s: %lld of %lld rows written", w->name.c_str(),
                                                    (long long)w->rows_in, (long long)w->H));
            } else {
                {
                    std::unique_lock<std::mutex> lock(w->mu);
                    w->cv_space.wait(lock, [&] { return w->inflight == 0; });
                }
                w->stop_workers();
                if (!w->fail.any.load()) {
                    std::vector<uint8_t> end;
                    append_chunk(end, "IEND", nullptr, 0);
                    w->raw_write(end.data(), end.size());
                }
            }
        }
    } catch (const std::bad_alloc &) {
        w->fail.set(FSS_AO_COPY_E_MEMORY, w->name + ": out of memory");
    } catch (...) {
        w->fail.set(FSS_AO_COPY_E_INTERNAL, w->name + ": internal error");
    }
    if (!w->closed) {
        w->stop_workers();
        if (!w->fail.any.load() && w->file != INVALID_HANDLE_VALUE) {
            HANDLE f = w->file;
            w->file = INVALID_HANDLE_VALUE;
            if (!CloseHandle(f)) w->fail.set(FSS_AO_COPY_E_IO, w->name + ": not closed: " + win_error(GetLastError()));
        }
        w->finish(w->fail.any.load());  // an error: the file removed
    }
    int32_t rc = FSS_AO_COPY_OK;
    if (w->fail.any.load()) {
        rc = w->fail.code;
        message_out(message, message_size, w->fail.get_text());
    }
    if (stats) {
        stats->seconds = now() - w->t0;
        stats->wait_seconds = w->wait_seconds;
        stats->threads = w->n_workers;
        stats->blocks = w->next_index;
        stats->most_in_flight = w->most_inflight;
        stats->raw_bytes = w->pos;
        stats->file_bytes = w->file_bytes;
    }
    delete w;
    return rc;
}

FSS_AO_COPY_API void fss_ao_png_abort(fss_ao_png_writer *w) {
    if (!w) return;
    try {
        w->fail.set(FSS_AO_COPY_E_INTERNAL, w->name + ": aborted");
        if (!w->closed) w->finish(true);
    } catch (...) {
    }
    delete w;
}

FSS_AO_COPY_API int32_t fss_ao_png_test_limit(fss_ao_png_writer *w, int64_t bytes) {
    if (!w) return FSS_AO_COPY_E_ARGS;
    std::lock_guard<std::mutex> lock(w->mu);
    w->limit = bytes;
    return FSS_AO_COPY_OK;
}

}  // extern "C"

// ---------------------------------------------------------------------------------------------------------------------
// The reader
// ---------------------------------------------------------------------------------------------------------------------

namespace {

// A file read in pieces of READ_CHUNK bytes
struct BufReader {
    HANDLE h = INVALID_HANDLE_VALUE;
    std::vector<uint8_t> buf;
    size_t at = 0, end = 0;
    bool eof = false;
    int64_t bytes = 0;

    ~BufReader() {
        if (h != INVALID_HANDLE_VALUE) CloseHandle(h);
    }
    bool open(const wchar_t *p, const std::string &name, Failure &fail) {
        h = CreateFileW(p, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
                        OPEN_EXISTING, FILE_FLAG_SEQUENTIAL_SCAN, nullptr);
        if (h == INVALID_HANDLE_VALUE) {
            fail.set(FSS_AO_COPY_E_IO, name + ": not opened: " + win_error(GetLastError()));
            return false;
        }
        buf.resize(READ_CHUNK);
        return true;
    }
    // more bytes in the buffer; false at the end of the file or on an error
    bool fill(const std::string &name, Failure &fail) {
        if (at < end) return true;
        if (eof) return false;
        DWORD got = 0;
        if (!ReadFile(h, buf.data(), (DWORD)buf.size(), &got, nullptr)) {
            fail.set(FSS_AO_COPY_E_IO, name + ": not read: " + win_error(GetLastError()));
            return false;
        }
        at = 0;
        end = got;
        bytes += got;
        if (got == 0) eof = true;
        return got > 0;
    }
    // n bytes into dst; the count read (less at the end of the file)
    size_t read(uint8_t *dst, size_t n, const std::string &name, Failure &fail) {
        size_t done = 0;
        while (done < n && fill(name, fail)) {
            size_t k = std::min(n - done, end - at);
            std::memcpy(dst + done, buf.data() + at, k);
            at += k;
            done += k;
        }
        return done;
    }
    // up to n bytes in place (a pointer into the buffer)
    size_t peek(size_t n, const uint8_t **p, const std::string &name, Failure &fail) {
        if (!fill(name, fail)) return 0;
        size_t k = std::min(n, end - at);
        *p = buf.data() + at;
        at += k;
        return k;
    }
};

inline uint8_t paeth(int a, int b, int c) {
    const int p = a + b - c;
    const int pa = std::abs(p - a), pb = std::abs(p - b), pc = std::abs(p - c);
    if (pa <= pb && pa <= pc) return (uint8_t)a;
    if (pb <= pc) return (uint8_t)b;
    return (uint8_t)c;
}

// row (n bytes after its filter byte) unfiltered in place against prev (the unfiltered row above; zeros for the first)
void unfilter(int type, uint8_t *row, const uint8_t *prev, int64_t n, int64_t bpp) {
    switch (type) {
        case 0: break;
        case 1:
            for (int64_t i = bpp; i < n; i++) row[i] = (uint8_t)(row[i] + row[i - bpp]);
            break;
        case 2:
            for (int64_t i = 0; i < n; i++) row[i] = (uint8_t)(row[i] + prev[i]);
            break;
        case 3:
            for (int64_t i = 0; i < bpp && i < n; i++) row[i] = (uint8_t)(row[i] + (prev[i] >> 1));
            for (int64_t i = bpp; i < n; i++) row[i] = (uint8_t)(row[i] + (((int)row[i - bpp] + (int)prev[i]) >> 1));
            break;
        case 4:
            for (int64_t i = 0; i < bpp && i < n; i++) row[i] = (uint8_t)(row[i] + prev[i]);
            for (int64_t i = bpp; i < n; i++) row[i] = (uint8_t)(row[i] + paeth(row[i - bpp], prev[i], prev[i - bpp]));
            break;
        default: break;
    }
}

struct Batch {
    std::vector<uint8_t> data;  // n rows of rowlen bytes, filtered
    int64_t y0 = 0, n = 0;
};

struct ReadJob {
    std::string name;
    int64_t W = 0, H = 0, C = 0, bits = 0, rowlen = 0, bpp = 0;
    uint16_t *out = nullptr;
    std::vector<uint8_t> prev;
    Failure *fail = nullptr;

    // a batch's rows unfiltered and stored (row y of the file is array row H - 1 - y)
    void rows(Batch &b) {
        const int64_t n = rowlen - 1, per_row = W * C;
        for (int64_t r = 0; r < b.n; r++) {
            uint8_t *row = b.data.data() + r * rowlen;
            const int64_t y = b.y0 + r;
            if (row[0] > 4) {
                fail->set(FSS_AO_COPY_E_FORMAT, fmt("%s: row %lld has filter type %d", name.c_str(), (long long)y,
                                                    (int)row[0]));
                return;
            }
            unfilter(row[0], row + 1, prev.data(), n, bpp);
            std::memcpy(prev.data(), row + 1, (size_t)n);
            uint16_t *dst = out + (H - 1 - y) * per_row;
            const uint8_t *s = row + 1;
            if (bits == 16) {
                for (int64_t i = 0; i < per_row; i++) dst[i] = (uint16_t)(((uint16_t)s[2 * i] << 8) | s[2 * i + 1]);
            } else {
                for (int64_t i = 0; i < per_row; i++) dst[i] = s[i];
            }
        }
    }
};

}  // namespace

extern "C" {

FSS_AO_COPY_API int32_t fss_ao_png_read(const wchar_t *path, int64_t W, int64_t H, int64_t channels, int64_t bits,
                                        uint16_t *out, int64_t threads, fss_ao_png_stats *stats, char *message,
                                        int64_t message_size) {
    if (message && message_size > 0) message[0] = 0;
    if (stats) std::memset(stats, 0, sizeof(*stats));
    if (!path || !out || W <= 0 || H <= 0 || channels < 1 || channels > 4 || (bits != 8 && bits != 16) ||
        threads < 1) {
        message_out(message, message_size, "fss_ao_png_read: bad arguments");
        return FSS_AO_COPY_E_ARGS;
    }
    const double t0 = now();
    Failure fail;
    z_stream zs;
    std::memset(&zs, 0, sizeof(zs));
    bool zinit = false;
    const bool side = threads > 1;
    int64_t n_batches = 0;
    double wait_seconds = 0;
    BufReader in;
    std::string name = utf8(path);
    try {
        if (in.open(path, name, fail)) {
            uint8_t head[8 + 8 + 13 + 4];
            size_t got = in.read(head, sizeof(head), name, fail);
            if (fail.any.load()) {
            } else if (got < 8 || std::memcmp(head, SIGNATURE, 8) != 0) {
                fail.set(FSS_AO_COPY_E_FORMAT, name + ": not a PNG");
            } else if (got < sizeof(head) || get_be32(head + 8) != 13 || std::memcmp(head + 12, "IHDR", 4) != 0) {
                fail.set(FSS_AO_COPY_E_FORMAT, name + ": no IHDR");
            } else {
                const uint8_t *ih = head + 16;
                const int64_t fw = get_be32(ih), fh = get_be32(ih + 4);
                const int fbits = ih[8], ct = ih[9], comp = ih[10], filt = ih[11], il = ih[12];
                const int64_t fc = channels_of(ct);
                if (!fc || (fbits != 8 && fbits != 16) || il != 0 || comp != 0 || filt != 0) {
                    fail.set(FSS_AO_COPY_E_UNSUPPORTED, fmt("%s: colour type %d, %d bits, interlace %d: not read here",
                                                            name.c_str(), ct, fbits, il));
                } else if (fw != W || fh != H || fc != channels || fbits != bits) {
                    fail.set(FSS_AO_COPY_E_ARGS,
                             fmt("%s: %lld x %lld px, %lld channel(s), %d bits; expected %lld x %lld, %lld, %lld",
                                 name.c_str(), (long long)fw, (long long)fh, (long long)fc, fbits, (long long)W,
                                 (long long)H, (long long)channels, (long long)bits));
                } else if (inflateInit(&zs) != Z_OK) {
                    fail.set(FSS_AO_COPY_E_MEMORY, name + ": zlib's inflate not initialized");
                } else {
                    zinit = true;
                }
            }
            if (zinit) {
                ReadJob job;
                job.name = name;
                job.W = W;
                job.H = H;
                job.C = channels;
                job.bits = bits;
                job.bpp = channels * bits / 8;
                job.rowlen = 1 + W * job.bpp;
                job.out = out;
                job.prev.assign((size_t)(job.rowlen - 1), 0);
                job.fail = &fail;
                const int64_t per_batch = std::max<int64_t>(1, ((int64_t)1 << 20) / job.rowlen);
                // the unfiltering beside the inflate: a queue of filled batches and a pool of free ones
                std::mutex mu;
                std::condition_variable cv;
                std::deque<std::unique_ptr<Batch>> full, empty;
                bool done_in = false;
                for (int k = 0; k < (side ? 4 : 2); k++) {  // the current batch and the next at least
                    std::unique_ptr<Batch> b(new Batch());
                    b->data.resize((size_t)(per_batch * job.rowlen));
                    empty.push_back(std::move(b));
                }
                std::thread un;
                if (side) {
                    un = std::thread([&] {
                        for (;;) {
                            std::unique_ptr<Batch> b;
                            {
                                std::unique_lock<std::mutex> lock(mu);
                                cv.wait(lock, [&] { return done_in || !full.empty(); });
                                if (full.empty()) return;
                                b = std::move(full.front());
                                full.pop_front();
                            }
                            if (!fail.any.load()) job.rows(*b);
                            {
                                std::lock_guard<std::mutex> lock(mu);
                                empty.push_back(std::move(b));
                            }
                            cv.notify_all();
                        }
                    });
                }
                auto take_empty = [&]() -> std::unique_ptr<Batch> {
                    std::unique_lock<std::mutex> lock(mu);
                    if (empty.empty()) {
                        const double t = now();
                        cv.wait(lock, [&] { return !empty.empty(); });
                        wait_seconds += now() - t;
                    }
                    std::unique_ptr<Batch> b = std::move(empty.front());
                    empty.pop_front();
                    return b;
                };
                auto hand = [&](std::unique_ptr<Batch> b) {
                    n_batches++;
                    if (side) {
                        {
                            std::lock_guard<std::mutex> lock(mu);
                            full.push_back(std::move(b));
                        }
                        cv.notify_all();
                    } else {
                        job.rows(*b);
                        std::lock_guard<std::mutex> lock(mu);
                        empty.push_back(std::move(b));
                    }
                };
                std::unique_ptr<Batch> cur = take_empty();
                cur->y0 = 0;
                cur->n = 0;
                size_t filled = 0;  // bytes of cur holding inflated data
                int64_t rows_done = 0;
                bool stream_end = false, iend = false;
                std::vector<uint8_t> extra(65536);  // inflated bytes after the last row (read to check the stream)
                // the chunks
                while (!fail.any.load() && !iend && !stream_end) {
                    uint8_t ch[8];
                    size_t g = in.read(ch, 8, name, fail);
                    if (fail.any.load() || g < 8) break;  // the file ends
                    const uint32_t len = get_be32(ch);
                    const bool idat = std::memcmp(ch + 4, "IDAT", 4) == 0;
                    if (std::memcmp(ch + 4, "IEND", 4) == 0) {
                        iend = true;
                        break;
                    }
                    size_t left = len;
                    while (left > 0 && !fail.any.load()) {
                        const uint8_t *p = nullptr;
                        size_t k = in.peek(left, &p, name, fail);
                        if (k == 0) break;  // the file ends inside the chunk
                        left -= k;
                        if (!idat || stream_end) continue;
                        zs.next_in = const_cast<Bytef *>(p);
                        zs.avail_in = (uInt)k;
                        while (zs.avail_in > 0 && !stream_end && !fail.any.load()) {
                            const bool rows_left = rows_done < H;
                            uint8_t *dst = rows_left ? cur->data.data() + filled : extra.data();
                            const size_t room = rows_left ? (size_t)(per_batch * job.rowlen) - filled : extra.size();
                            zs.next_out = dst;
                            zs.avail_out = (uInt)room;
                            int rc = inflate(&zs, Z_NO_FLUSH);
                            const size_t made = room - zs.avail_out;
                            if (rc == Z_STREAM_END) {
                                stream_end = true;
                            } else if (rc != Z_OK && rc != Z_BUF_ERROR) {
                                fail.set(FSS_AO_COPY_E_FORMAT, fmt("%s: the zlib stream is corrupt (%s)", name.c_str(),
                                                                   zs.msg ? zs.msg : "zlib error"));
                                break;
                            }
                            if (!rows_left) continue;
                            filled += made;
                            const int64_t whole = (int64_t)(filled / (size_t)job.rowlen);
                            const int64_t want = std::min(per_batch, H - cur->y0);
                            if (whole >= want) {  // the batch is complete
                                cur->n = want;
                                const size_t used = (size_t)(want * job.rowlen), rest = filled - used;
                                rows_done = cur->y0 + want;
                                std::unique_ptr<Batch> next = take_empty();
                                next->y0 = rows_done;
                                next->n = 0;
                                if (rest) std::memcpy(next->data.data(), cur->data.data() + used, rest);
                                filled = rest;
                                hand(std::move(cur));
                                cur = std::move(next);
                            }
                        }
                    }
                    if (fail.any.load()) break;
                    if (left > 0) break;  // truncated inside a chunk
                    uint8_t crc[4];
                    if (in.read(crc, 4, name, fail) < 4) break;
                }
                if (!fail.any.load() && rows_done < H) {
                    // rows inflated so far but not a whole batch (the stream or the file ends): stored, then counted
                    const int64_t whole = (int64_t)(filled / (size_t)job.rowlen);
                    if (whole > 0) {
                        cur->n = std::min(whole, H - cur->y0);
                        rows_done = cur->y0 + cur->n;
                        hand(std::move(cur));
                    }
                    if (rows_done < H)
                        fail.set(FSS_AO_COPY_E_FORMAT, fmt("%s: %lld of %lld rows decoded", name.c_str(),
                                                           (long long)rows_done, (long long)H));
                }
                if (side) {
                    {
                        std::lock_guard<std::mutex> lock(mu);
                        done_in = true;
                    }
                    cv.notify_all();
                    un.join();
                }
            }
        }
    } catch (const std::bad_alloc &) {
        fail.set(FSS_AO_COPY_E_MEMORY, name + ": out of memory");
    } catch (...) {
        fail.set(FSS_AO_COPY_E_INTERNAL, name + ": internal error");
    }
    if (zinit) inflateEnd(&zs);
    if (stats) {
        stats->seconds = now() - t0;
        stats->wait_seconds = wait_seconds;
        stats->threads = side ? 2 : 1;
        stats->blocks = n_batches;
        stats->raw_bytes = (int64_t)zs.total_out;
        stats->file_bytes = in.bytes;
    }
    if (fail.any.load()) {
        message_out(message, message_size, fail.get_text());
        return fail.code;
    }
    return FSS_AO_COPY_OK;
}

}  // extern "C"
