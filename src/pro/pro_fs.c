/* SPDX-License-Identifier: AGPL-3.0-only */
#include "pro_fs.h"
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>

typedef struct {
    bool used;
    char path[SM_PRO_FS_PATH_MAX];
    uint32_t position;
    uint32_t size;          /* known for readable files; grows as a writer writes */
    bool writable;
    bool readable;
} handle_t;

static const sm_pro_mcu_t *mcu;
static handle_t handles[SM_PRO_FS_HANDLES];
/* The handle the MCU's one file currently belongs to, and where the MCU's
   own pointer sits. NULL when the MCU holds nothing. */
static handle_t *current;
static uint32_t mcu_position;

/* The directory listing the MCU currently holds, for findfirst/findnext. */
static uint16_t listing_count;
static uint16_t listing_index;
static bool listing_loaded;

/* Read-ahead. newlib's stdio on this toolchain buffers 1 KiB whatever
   fstat says, so a 570 KiB catalog would cost 570 FIFO commands, each with
   its own handshake. One handle's most recent window is kept here instead:
   a small read that misses it pulls the next SM_PRO_FS_CACHE bytes in one
   command, and the 1 KiB reads that follow are memcpy. A read at least the
   window's size goes straight through. Any write drops the window, since a
   writer may have changed what it holds. */
static uint8_t cache[SM_PRO_FS_CACHE] __attribute__((aligned(16)));
static handle_t *cache_handle;
static uint32_t cache_offset;
static uint32_t cache_length;

/* Where the MCU's own pointer sits after a fast read is not tracked; this
   value in mcu_position makes the next transfer reposition first. */
#define POSITION_UNKNOWN UINT32_MAX

void sm_pro_fs_init(const sm_pro_mcu_t *cartridge) {
    mcu = cartridge;
    memset(handles, 0, sizeof(handles));
    current = NULL;
    mcu_position = 0;
    listing_count = listing_index = 0;
    listing_loaded = false;
    cache_handle = NULL;
    cache_offset = cache_length = 0;
}

bool sm_pro_fs_normalise(const char *name, char *out, size_t out_size) {
    size_t length;
    if (!name || !out || !out_size) return false;
    while (*name == '/') name++;
    length = strlen(name);
    if (length == 0 || length >= out_size) return false;
    memcpy(out, name, length + 1);
    return true;
}

static void drop_mcu_file(void) {
    if (current) {
        mcu->file_close();
        current = NULL;
    }
}

void sm_pro_fs_release_mcu(void) { drop_mcu_file(); }

/* Make `handle` the MCU's file, positioned where the handle says. */
static bool make_current(handle_t *handle) {
    if (current != handle) {
        unsigned mode;
        drop_mcu_file();
        /* Reopening never creates or truncates: that happened, if it was
           going to, when the handle was opened. */
        mode = (handle->readable ? SM_PRO_MCU_READ : 0u) | (handle->writable ? SM_PRO_MCU_WRITE : 0u);
        if (mcu->file_open(handle->path, mode) != 0) return false;
        current = handle;
        mcu_position = 0;
    }
    if (mcu_position != handle->position) {
        if (mcu->file_set_ptr(handle->position) != 0) return false;
        mcu_position = handle->position;
    }
    return true;
}

static void *fs_open(char *name, int flags) {
    handle_t *handle = NULL;
    uint32_t size = 0;
    bool is_dir = false;
    int access = flags & O_ACCMODE;
    unsigned i;

    for (i = 0; i < SM_PRO_FS_HANDLES; i++) {
        if (!handles[i].used) { handle = &handles[i]; break; }
    }
    if (!handle) { errno = EMFILE; return NULL; }
    memset(handle, 0, sizeof(*handle));
    if (!sm_pro_fs_normalise(name, handle->path, sizeof(handle->path))) {
        errno = ENAMETOOLONG;
        return NULL;
    }
    handle->readable = access == O_RDONLY || access == O_RDWR;
    handle->writable = access == O_WRONLY || access == O_RDWR;

    if (flags & (O_CREAT | O_TRUNC)) {
        /* Creating or truncating is the one thing that has to happen now,
           through the MCU, rather than lazily on the first write. */
        unsigned mode = (handle->readable ? SM_PRO_MCU_READ : 0u) | SM_PRO_MCU_WRITE |
            ((flags & O_TRUNC) ? SM_PRO_MCU_CREATE_ALWAYS : SM_PRO_MCU_OPEN_ALWAYS);
        cache_handle = NULL;    /* a reader of the same file would be stale */
        drop_mcu_file();
        if (mcu->file_open(handle->path, mode) != 0) { errno = EIO; return NULL; }
        handle->used = true;
        current = handle;
        mcu_position = 0;
        if (!(flags & O_TRUNC)) {
            if (mcu->file_info(handle->path, &size, &is_dir) == 0) handle->size = size;
            if (flags & O_APPEND) handle->position = handle->size;
        }
        return handle;
    }

    /* Asking about a file is itself an open on the real cartridge, so the
       MCU's file is given up first; whoever held it is reopened on demand. */
    drop_mcu_file();
    if (mcu->file_info(handle->path, &size, &is_dir) != 0 || is_dir) {
        errno = ENOENT;
        return NULL;
    }
    handle->size = size;
    handle->used = true;
    if (flags & O_APPEND) handle->position = size;
    /* Nothing is opened on the MCU yet: the first read does that, and a
       handle that is opened and closed without a read costs nothing. */
    return handle;
}

static int fs_read(void *file, uint8_t *ptr, int len) {
    handle_t *handle = file;
    uint32_t want, done = 0;
    if (!handle || !handle->used || len < 0) { errno = EBADF; return -1; }
    if (!handle->readable) { errno = EBADF; return -1; }
    if (handle->position >= handle->size) return 0;
    want = (uint32_t)len;
    if (want > handle->size - handle->position) want = handle->size - handle->position;
    while (done < want) {
        uint32_t remaining = want - done;
        if (cache_handle == handle && handle->position >= cache_offset &&
            handle->position < cache_offset + cache_length) {
            uint32_t at = handle->position - cache_offset;
            uint32_t take = cache_length - at;
            if (take > remaining) take = remaining;
            memcpy(ptr + done, cache + at, take);
            handle->position += take;
            done += take;
            continue;
        }
        if (!make_current(handle)) { errno = EIO; return -1; }
        if (remaining >= SM_PRO_FS_CACHE) {
            /* Big enough to be worth its own command; nothing kept. */
            if (mcu->file_read(ptr + done, remaining) != 0) { errno = EIO; return -1; }
            handle->position += remaining;
            mcu_position += remaining;
            done += remaining;
        } else {
            uint32_t fill = handle->size - handle->position;
            int rc;
            if (fill > SM_PRO_FS_CACHE) fill = SM_PRO_FS_CACHE;
            if (mcu->file_read_fast && fill >= SM_PRO_FS_FAST_MIN) {
                rc = mcu->file_read_fast(cache, fill);
                mcu_position = POSITION_UNKNOWN;
            } else {
                rc = mcu->file_read(cache, fill);
                mcu_position += fill;
            }
            if (rc != 0) { cache_handle = NULL; errno = EIO; return -1; }
            cache_handle = handle;
            cache_offset = handle->position;
            cache_length = fill;
        }
    }
    return (int)done;
}

static int fs_write(void *file, uint8_t *ptr, int len) {
    handle_t *handle = file;
    if (!handle || !handle->used || len < 0) { errno = EBADF; return -1; }
    if (!handle->writable) { errno = EBADF; return -1; }
    if (len == 0) return 0;
    cache_handle = NULL;
    if (!make_current(handle)) { errno = EIO; return -1; }
    if (mcu->file_write(ptr, (uint32_t)len) != 0) { errno = EIO; return -1; }
    handle->position += (uint32_t)len;
    mcu_position += (uint32_t)len;
    if (handle->position > handle->size) handle->size = handle->position;
    return len;
}

static int fs_lseek(void *file, int offset, int whence) {
    handle_t *handle = file;
    int64_t target;
    if (!handle || !handle->used) { errno = EBADF; return -1; }
    switch (whence) {
        case SEEK_SET: target = offset; break;
        case SEEK_CUR: target = (int64_t)handle->position + offset; break;
        case SEEK_END: target = (int64_t)handle->size + offset; break;
        default: errno = EINVAL; return -1;
    }
    if (target < 0 || target > INT32_MAX) { errno = EINVAL; return -1; }
    /* Deferred: the MCU is repositioned by the next read or write, so a
       seek followed by a seek costs one command, not two. */
    handle->position = (uint32_t)target;
    return (int)target;
}

static int fs_close(void *file) {
    handle_t *handle = file;
    if (!handle || !handle->used) { errno = EBADF; return -1; }
    if (current == handle) drop_mcu_file();
    if (cache_handle == handle) cache_handle = NULL;
    memset(handle, 0, sizeof(*handle));
    return 0;
}

static void fill_stat(struct stat *st, uint32_t size, bool is_dir) {
    memset(st, 0, sizeof(*st));
    st->st_size = (off_t)size;
    st->st_mode = is_dir ? (S_IFDIR | 0555) : (S_IFREG | 0666);
}

static int fs_fstat(void *file, struct stat *st) {
    handle_t *handle = file;
    if (!handle || !handle->used) { errno = EBADF; return -1; }
    fill_stat(st, handle->size, false);
    return 0;
}

static int fs_stat(char *name, struct stat *st) {
    char path[SM_PRO_FS_PATH_MAX];
    uint32_t size = 0;
    bool is_dir = false;
    if (!sm_pro_fs_normalise(name, path, sizeof(path))) { errno = ENAMETOOLONG; return -1; }
    drop_mcu_file();
    if (mcu->file_info(path, &size, &is_dir) != 0) { errno = ENOENT; return -1; }
    fill_stat(st, size, is_dir);
    return 0;
}

static int fs_findnext2(const char *path, dir_t *dir) {
    char name[256];
    uint32_t size = 0;
    bool is_dir = false;
    (void)path;
    if (!listing_loaded || listing_index >= listing_count) return -1;
    if (mcu->dir_record(listing_index, name, sizeof(name), &size, &is_dir) != 0) {
        errno = EIO;
        return -1;
    }
    listing_index++;
    snprintf(dir->d_name, sizeof(dir->d_name), "%s", name);
    dir->d_type = is_dir ? DT_DIR : DT_REG;
    dir->d_size = (int64_t)size;
    dir->d_cookie = listing_index;
    return 0;
}

static int fs_findfirst(char *name, dir_t *dir) {
    char path[SM_PRO_FS_PATH_MAX];
    /* The MCU keeps one file and one listing; whether a listing disturbs the
       file is not documented, so the file is given up and reopened lazily. */
    drop_mcu_file();
    listing_loaded = false;
    if (!sm_pro_fs_normalise(name, path, sizeof(path))) {
        /* The root: libdragon hands "/" for sd:/, which normalises to nothing. */
        path[0] = '\0';
    }
    if (mcu->dir_load(path, &listing_count) != 0) { errno = ENOENT; return -1; }
    listing_loaded = true;
    listing_index = 0;
    return fs_findnext2(name, dir);
}

static filesystem_t table = {
    .open = fs_open,
    .fstat = fs_fstat,
    .stat = fs_stat,
    .lseek = fs_lseek,
    .read = fs_read,
    .write = fs_write,
    .close = fs_close,
    .unlink = NULL,
    .findfirst = fs_findfirst,
    .findnext = NULL,
    .findnext2 = fs_findnext2,
    .ftruncate = NULL,
    .mkdir = NULL,
    .ioctl = NULL,
};

filesystem_t *sm_pro_fs(void) { return &table; }
