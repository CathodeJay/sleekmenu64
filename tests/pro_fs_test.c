/* SPDX-License-Identifier: AGPL-3.0-only */
/* The Pro filesystem driver against a fake cartridge that enforces the one
   rule the real one has: one file open at a time. The browser keeps the
   cover pack open all session and reads everything else around it; the
   driver has to make that true on a cartridge that cannot. */
#include "pro/pro_fs.h"
#include <assert.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* --- the fake cartridge ------------------------------------------------ */
#define FAKE_FILES 12
#define FAKE_DATA (48u * 1024u)
typedef struct { char path[128]; uint8_t data[FAKE_DATA]; uint32_t size; bool is_dir; } fake_file_t;
static fake_file_t files[FAKE_FILES];
static int file_count;
static fake_file_t *open_file;      /* the MCU's one file */
static uint32_t open_pointer;
static int opens, closes, seeks, reads, fast_reads;
static bool offer_fast;             /* whether the fake advertises file_read_fast */

static fake_file_t *find(const char *path) {
    for (int i = 0; i < file_count; i++)
        if (!strcmp(files[i].path, path)) return &files[i];
    return NULL;
}

static fake_file_t *add(const char *path, const char *content, bool is_dir) {
    fake_file_t *f;
    assert(file_count < FAKE_FILES);
    f = &files[file_count++];
    memset(f, 0, sizeof(*f));
    snprintf(f->path, sizeof(f->path), "%s", path);
    f->size = (uint32_t)strlen(content);
    memcpy(f->data, content, f->size);
    f->is_dir = is_dir;
    return f;
}

static int fake_open(const char *path, unsigned mode) {
    fake_file_t *f;
    assert(open_file == NULL && "the real MCU holds one file; opening a second is a driver bug");
    assert(path[0] != '/' && "the MCU wants card-relative paths");
    f = find(path);
    if (!f) {
        if (!(mode & (SM_PRO_MCU_CREATE_ALWAYS | SM_PRO_MCU_OPEN_ALWAYS))) return 4;  /* FR_NO_FILE */
        f = add(path, "", false);
    } else if (mode & SM_PRO_MCU_CREATE_ALWAYS) {
        f->size = 0;
    }
    open_file = f;
    open_pointer = 0;
    opens++;
    return 0;
}

static int fake_close(void) {
    assert(open_file != NULL);
    open_file = NULL;
    closes++;
    return 0;
}

static int fake_set_ptr(uint32_t offset) {
    assert(open_file != NULL);
    open_pointer = offset;
    seeks++;
    return 0;
}

static int fake_read(void *dst, uint32_t length) {
    assert(open_file != NULL);
    assert(open_pointer + length <= open_file->size && "read past end: the driver must clamp");
    memcpy(dst, open_file->data + open_pointer, length);
    open_pointer += length;
    reads++;
    return 0;
}

/* The fast road: the real one goes through cartridge memory and leaves the
   MCU's pointer wherever it leaves it, so the fake moves the pointer to
   somewhere wrong on purpose -- the driver must not trust it afterwards. */
static int fake_read_fast(void *dst, uint32_t length) {
    assert(open_file != NULL);
    assert(length >= SM_PRO_FS_FAST_MIN && "short reads take the FIFO");
    assert(((uintptr_t)dst % 8) == 0 && "the fast read DMAs: 8-byte alignment");
    assert(open_pointer + length <= open_file->size);
    memcpy(dst, open_file->data + open_pointer, length);
    open_pointer = 7;
    fast_reads++;
    return 0;
}

static int fake_write(const void *src, uint32_t length) {
    assert(open_file != NULL);
    assert(open_pointer + length <= sizeof(open_file->data));
    memcpy(open_file->data + open_pointer, src, length);
    open_pointer += length;
    if (open_pointer > open_file->size) open_file->size = open_pointer;
    return 0;
}

static int fake_info(const char *path, uint32_t *size, bool *is_dir) {
    fake_file_t *f = find(path);
    assert(open_file == NULL && "the real cartridge answers file_info by opening the path");
    if (!f) return 4;
    *size = f->size;
    *is_dir = f->is_dir;
    return 0;
}

static char listed[FAKE_FILES][128];
static uint16_t listed_count;

static int fake_dir_load(const char *path, uint16_t *count) {
    size_t prefix = strlen(path);
    listed_count = 0;
    for (int i = 0; i < file_count; i++) {
        const char *rest;
        if (prefix && (strncmp(files[i].path, path, prefix) || files[i].path[prefix] != '/')) continue;
        rest = prefix ? files[i].path + prefix + 1 : files[i].path;
        if (strchr(rest, '/')) continue;        /* not a direct child */
        snprintf(listed[listed_count++], 128, "%s", rest);
    }
    *count = listed_count;
    return 0;
}

static int fake_dir_record(uint16_t index, char *name, size_t name_size, uint32_t *size, bool *is_dir) {
    fake_file_t *f;
    char full[256];
    if (index >= listed_count) return 1;
    snprintf(name, name_size, "%s", listed[index]);
    snprintf(full, sizeof(full), "ROMS/%s", listed[index]);
    f = find(full);
    if (!f) f = find(listed[index]);
    *size = f ? f->size : 0;
    *is_dir = f ? f->is_dir : false;
    return 0;
}

static const sm_pro_mcu_t fake = {
    .file_open = fake_open, .file_close = fake_close, .file_set_ptr = fake_set_ptr,
    .file_read = fake_read, .file_write = fake_write, .file_info = fake_info,
    .dir_load = fake_dir_load, .dir_record = fake_dir_record,
};
static const sm_pro_mcu_t fake_with_fast = {
    .file_open = fake_open, .file_close = fake_close, .file_set_ptr = fake_set_ptr,
    .file_read = fake_read, .file_write = fake_write, .file_info = fake_info,
    .dir_load = fake_dir_load, .dir_record = fake_dir_record,
    .file_read_fast = fake_read_fast,
};

/* A file bigger than the read-ahead window, with a byte pattern that
   tells every offset apart. */
static uint8_t pattern_at(uint32_t offset) { return (uint8_t)((offset * 7u) ^ (offset >> 8)); }

static fake_file_t *add_big(const char *path, uint32_t size) {
    fake_file_t *f = add(path, "", false);
    for (uint32_t i = 0; i < size; i++) f->data[i] = pattern_at(i);
    f->size = size;
    return f;
}

static void reset(void) {
    memset(files, 0, sizeof(files));
    file_count = 0;
    open_file = NULL;
    opens = closes = seeks = reads = fast_reads = 0;
    add("sleekmenu/catalog.ebc", "CATALOG-BYTES-HERE", false);
    add("sleekmenu/covers.pak", "PACK:0123456789abcdef", false);
    add("sleekmenu/favorites.txt", "ROMS/a.z64\n", false);
    add("ROMS", "", true);
    add("ROMS/a.z64", "\x80\x37\x12\x40ROM-A", false);
    add("ROMS/b.z64", "\x80\x37\x12\x40ROM-B", false);
    add("ROMS/Hacks", "", true);
    sm_pro_fs_init(offer_fast ? &fake_with_fast : &fake);
}

int main(void) {
    filesystem_t *fs = sm_pro_fs();
    uint8_t buf[64];
    char path[SM_PRO_FS_PATH_MAX];

    /* --- paths ------------------------------------------------------- */
    assert(sm_pro_fs_normalise("/sleekmenu/catalog.ebc", path, sizeof(path)) && !strcmp(path, "sleekmenu/catalog.ebc"));
    assert(sm_pro_fs_normalise("sleekmenu/catalog.ebc", path, sizeof(path)) && !strcmp(path, "sleekmenu/catalog.ebc"));
    assert(!sm_pro_fs_normalise("/", path, sizeof(path)));
    assert(!sm_pro_fs_normalise("x", path, 1));

    /* --- two handles, one MCU file, interleaved ----------------------- */
    reset();
    {
        void *pack = fs->open("sleekmenu/covers.pak", O_RDONLY);
        void *cat = fs->open("sleekmenu/catalog.ebc", O_RDONLY);
        assert(pack && cat);
        /* Opening costs no MCU file: the first read does. */
        assert(opens == 0 && open_file == NULL);

        assert(fs->read(cat, buf, 7) == 7 && !memcmp(buf, "CATALOG", 7));
        assert(open_file && !strcmp(open_file->path, "sleekmenu/catalog.ebc"));
        assert(fs->read(pack, buf, 5) == 5 && !memcmp(buf, "PACK:", 5));
        assert(open_file && !strcmp(open_file->path, "sleekmenu/covers.pak"));
        /* Back to the catalog where it left off, not at the start. */
        assert(fs->read(cat, buf, 6) == 6 && !memcmp(buf, "-BYTES", 6));
        /* The pack was reopened and repositioned to where it was, too. */
        assert(fs->read(pack, buf, 4) == 4 && !memcmp(buf, "0123", 4));
        assert(opens == 4 && closes == 3);

        /* A run of reads on one handle reopens nothing. */
        opens = 0;
        assert(fs->read(pack, buf, 4) == 4 && !memcmp(buf, "4567", 4));
        assert(fs->read(pack, buf, 4) == 4 && !memcmp(buf, "89ab", 4));
        assert(opens == 0);

        /* Seek then read: the whole 21-byte pack is in the read-ahead
           window by now, so neither the seeks nor the read reach the MCU. */
        seeks = 0; reads = 0;
        assert(fs->lseek(pack, 5, SEEK_SET) == 5);
        assert(fs->lseek(pack, 2, SEEK_CUR) == 7);
        assert(seeks == 0);
        assert(fs->read(pack, buf, 3) == 3 && !memcmp(buf, "234", 3));
        assert(seeks == 0 && reads == 0);
        /* SEEK_END knows the size without asking the MCU. */
        assert(fs->lseek(pack, 0, SEEK_END) == 21);
        assert(fs->read(pack, buf, 10) == 0);          /* at end: nothing, no error */
        assert(fs->lseek(pack, -4, SEEK_END) == 17);
        assert(fs->read(pack, buf, 64) == 4 && !memcmp(buf, "cdef", 4));  /* clamped */
        assert(fs->lseek(pack, -1, SEEK_SET) == -1);

        /* fstat answers from the handle. */
        {
            struct stat st;
            assert(fs->fstat(pack, &st) == 0 && st.st_size == 21);
        }

        assert(fs->close(cat) == 0);
        assert(open_file && !strcmp(open_file->path, "sleekmenu/covers.pak"));
        assert(fs->close(pack) == 0);
        assert(open_file == NULL);
    }

    /* --- a file that is not there ------------------------------------- */
    reset();
    assert(fs->open("sleekmenu/history.txt", O_RDONLY) == NULL);
    {
        struct stat st;
        assert(fs->stat("/sleekmenu/history.txt", &st) == -1);
        assert(fs->stat("/ROMS/a.z64", &st) == 0 && st.st_size == 9 && S_ISREG(st.st_mode));
        assert(fs->stat("/ROMS", &st) == 0 && S_ISDIR(st.st_mode));
    }
    assert(fs->open("ROMS", O_RDONLY) == NULL);       /* a folder is not a file */

    /* --- writing: favourites and history are written whole ------------ */
    reset();
    {
        void *pack = fs->open("sleekmenu/covers.pak", O_RDONLY);
        void *fav;
        assert(fs->read(pack, buf, 5) == 5);
        fav = fs->open("sleekmenu/favorites.txt", O_WRONLY | O_CREAT | O_TRUNC);
        assert(fav);
        /* Truncation happened at open, through the MCU, and it took the file. */
        assert(open_file && !strcmp(open_file->path, "sleekmenu/favorites.txt"));
        assert(find("sleekmenu/favorites.txt")->size == 0);
        assert(fs->write(fav, (uint8_t *)"ROMS/b.z64\n", 11) == 11);
        /* Reading the pack in between does not lose the writer's place. */
        assert(fs->read(pack, buf, 4) == 4 && !memcmp(buf, "0123", 4));
        assert(fs->write(fav, (uint8_t *)"ROMS/a.z64\n", 11) == 11);
        assert(fs->close(fav) == 0);
        assert(find("sleekmenu/favorites.txt")->size == 22);
        assert(!memcmp(find("sleekmenu/favorites.txt")->data, "ROMS/b.z64\nROMS/a.z64\n", 22));
        assert(fs->close(pack) == 0);
    }
    /* A new file, created rather than truncated. */
    {
        void *hist = fs->open("sleekmenu/history.txt", O_WRONLY | O_CREAT | O_TRUNC);
        assert(hist);
        assert(fs->write(hist, (uint8_t *)"x", 1) == 1);
        assert(fs->close(hist) == 0);
        assert(find("sleekmenu/history.txt") && find("sleekmenu/history.txt")->size == 1);
    }
    /* Append lands at the end. */
    {
        void *hist = fs->open("sleekmenu/history.txt", O_WRONLY | O_APPEND);
        assert(hist);
        assert(fs->write(hist, (uint8_t *)"y", 1) == 1);
        assert(fs->close(hist) == 0);
        assert(find("sleekmenu/history.txt")->size == 2);
        assert(!memcmp(find("sleekmenu/history.txt")->data, "xy", 2));
    }
    /* A reader cannot write and a writer cannot read. */
    {
        void *ro = fs->open("ROMS/a.z64", O_RDONLY);
        void *wo = fs->open("sleekmenu/history.txt", O_WRONLY);
        assert(fs->write(ro, buf, 1) == -1);
        assert(fs->read(wo, buf, 1) == -1);
        fs->close(ro); fs->close(wo);
    }

    /* --- a backend borrowing the MCU for a ROM load -------------------- */
    reset();
    {
        void *pack = fs->open("sleekmenu/covers.pak", O_RDONLY);
        assert(fs->read(pack, buf, 5) == 5);
        sm_pro_fs_release_mcu();
        assert(open_file == NULL);
        /* ...the backend does its own open/close here... */
        assert(fake_open("ROMS/a.z64", SM_PRO_MCU_READ) == 0);
        assert(fake_close() == 0);
        /* and stdio carries on where it was. */
        assert(fs->read(pack, buf, 4) == 4 && !memcmp(buf, "0123", 4));
        fs->close(pack);
    }

    /* --- listing a folder, with the MCU's file given up first --------- */
    reset();
    {
        dir_t entry;
        void *pack = fs->open("sleekmenu/covers.pak", O_RDONLY);
        assert(fs->read(pack, buf, 5) == 5);
        assert(fs->findfirst("/ROMS", &entry) == 0);
        assert(open_file == NULL);
        assert(!strcmp(entry.d_name, "a.z64") && entry.d_type == DT_REG && entry.d_size == 9);
        assert(fs->findnext2("/ROMS", &entry) == 0 && !strcmp(entry.d_name, "b.z64"));
        assert(fs->findnext2("/ROMS", &entry) == 0 && !strcmp(entry.d_name, "Hacks") && entry.d_type == DT_DIR);
        assert(fs->findnext2("/ROMS", &entry) == -1);
        /* The pack comes back on its own. */
        assert(fs->read(pack, buf, 4) == 4 && !memcmp(buf, "0123", 4));
        fs->close(pack);
        /* The card root is a listing too. */
        assert(fs->findfirst("/", &entry) == 0);
    }

    /* --- read-ahead: stdio's 1 KiB reads must not become 1 KiB commands -- */
    reset();
    {
        static uint8_t big[40u * 1024u];
        const uint32_t size = 36u * 1024u + 100u;
        void *f;
        add_big("sleekmenu/catalog.big", size);
        f = fs->open("sleekmenu/catalog.big", O_RDONLY);
        assert(f);
        /* Sequential 1 KiB reads, the way newlib's fread arrives. */
        reads = 0; seeks = 0;
        for (uint32_t at = 0; at < size; ) {
            int got = fs->read(f, big + at, 1024);
            assert(got > 0);
            at += (uint32_t)got;
        }
        for (uint32_t i = 0; i < size; i++) assert(big[i] == pattern_at(i));
        /* 36 KiB + 100 bytes in 16 KiB windows: three commands, not 37. */
        assert(reads == 3 && seeks == 0);
        /* A random cover-sized read elsewhere is one command. */
        reads = 0;
        assert(fs->lseek(f, 5000, SEEK_SET) == 5000);
        assert(fs->read(f, big, 14000) == 14000);
        for (uint32_t i = 0; i < 14000; i++) assert(big[i] == pattern_at(5000 + i));
        assert(reads == 1 && seeks == 1);
        /* And the 1 KiB that follows it comes out of the same window. */
        assert(fs->read(f, big, 1024) == 1024 && big[0] == pattern_at(19000));
        assert(reads == 1);
        /* A read the size of the window or larger goes straight through. */
        reads = 0;
        assert(fs->lseek(f, 0, SEEK_SET) == 0);
        assert(fs->read(f, big, 20000) == 20000 && big[19999] == pattern_at(19999));
        assert(reads == 1);
        /* Another handle's read does not serve from this one's window. */
        {
            void *g = fs->open("sleekmenu/catalog.big", O_RDONLY);
            reads = 0;
            assert(fs->read(g, big, 8) == 8 && big[0] == pattern_at(0));
            assert(reads == 1);
            fs->close(g);
        }
        /* A write drops the window: what comes next is read again. */
        {
            void *w = fs->open("sleekmenu/catalog.big", O_WRONLY);
            assert(fs->lseek(f, 100, SEEK_SET) == 100);
            assert(fs->read(f, big, 4) == 4 && big[0] == pattern_at(100));
            assert(fs->lseek(w, 104, SEEK_SET) == 104);
            assert(fs->write(w, (uint8_t *)"NEW!", 4) == 4);
            fs->close(w);
            reads = 0;
            assert(fs->read(f, big, 4) == 4 && !memcmp(big, "NEW!", 4));
            assert(reads == 1);
        }
        fs->close(f);
    }

    /* --- the fast read: window fills go through cartridge memory --------- */
    offer_fast = true;
    reset();
    {
        static uint8_t big[40u * 1024u];
        const uint32_t size = 36u * 1024u + 100u;
        void *f;
        add_big("sleekmenu/catalog.big", size);
        f = fs->open("sleekmenu/catalog.big", O_RDONLY);
        assert(f);
        reads = fast_reads = seeks = 0;
        for (uint32_t at = 0; at < size; ) {
            int got = fs->read(f, big + at, 1024);
            assert(got > 0);
            at += (uint32_t)got;
        }
        for (uint32_t i = 0; i < size; i++) assert(big[i] == pattern_at(i));
        /* Two full windows by the fast road, the 4 KiB+100 tail too (it is
           over the threshold); nothing over the FIFO. Each fast read leaves
           the MCU's pointer unknown, so every window after the first was
           repositioned first rather than trusted. */
        assert(fast_reads == 3 && reads == 0);
        assert(seeks == 2);
        /* A tail under the threshold takes the FIFO. */
        {
            void *g;
            add_big("sleekmenu/small.tail", 16u * 1024u + 1000u);
            g = fs->open("sleekmenu/small.tail", O_RDONLY);
            reads = fast_reads = 0;
            for (uint32_t at = 0; at < 16u * 1024u + 1000u; ) {
                int got = fs->read(g, big + at, 1024);
                assert(got > 0);
                at += (uint32_t)got;
            }
            assert(fast_reads == 1 && reads == 1);
            for (uint32_t i = 0; i < 16u * 1024u + 1000u; i++) assert(big[i] == pattern_at(i));
            fs->close(g);
        }
        /* And a cover-sized read from the middle is one fast read. */
        reads = fast_reads = 0;
        assert(fs->lseek(f, 5000, SEEK_SET) == 5000);
        assert(fs->read(f, big, 14000) == 14000 && big[13999] == pattern_at(18999));
        assert(fast_reads == 1 && reads == 0);
        fs->close(f);
    }
    offer_fast = false;

    /* --- running out of handles is an error, not a crash --------------- */
    reset();
    {
        void *h[SM_PRO_FS_HANDLES + 1];
        for (unsigned i = 0; i < SM_PRO_FS_HANDLES; i++) {
            h[i] = fs->open("ROMS/a.z64", O_RDONLY);
            assert(h[i]);
        }
        h[SM_PRO_FS_HANDLES] = fs->open("ROMS/a.z64", O_RDONLY);
        assert(h[SM_PRO_FS_HANDLES] == NULL);
        for (unsigned i = 0; i < SM_PRO_FS_HANDLES; i++) fs->close(h[i]);
    }

    printf("pro fs checks passed\n");
    return 0;
}
