/* SPDX-License-Identifier: AGPL-3.0-only */
/* The card scan the browser runs when there is no catalog, over a real
   directory tree: games anywhere on the card are found and recorded
   relative to the card, and the files that are not games -- the browser's
   own ROM, the firmware's folder, another menu's, an unpacked art
   collection, macOS and Windows bookkeeping -- are left alone. */
#include <dirent.h>
#include <sys/stat.h>
/* dirent.h and the libdragon stub both name DT_DIR; the host's values are
   not needed once every entry is stat()ed. */
#undef DT_DIR
#undef DT_REG
#include "card_paths.h"
#include "catalog.h"
#include <libdragon.h>
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* dir_findfirst/dir_findnext over POSIX, with "sd:/" mapped onto the scratch
   root. One open directory at a time is what the scan needs: it lists a
   folder to the end before opening the next. */
static char root[512];
static DIR *open_dir;
static char open_host[768];

static const char *host_path(const char *sd_path, char *out, size_t size) {
    if (!strncmp(sd_path, "sd:/", 4)) sd_path += 4;
    snprintf(out, size, "%s/%s", root, sd_path);
    return out;
}

static int fill(dir_t *entry) {
    struct dirent *item;
    while ((item = readdir(open_dir)) != NULL) {
        char full[1100];
        struct stat st;
        if (!strcmp(item->d_name, ".") || !strcmp(item->d_name, "..")) continue;
        snprintf(entry->d_name, sizeof(entry->d_name), "%s", item->d_name);
        snprintf(full, sizeof(full), "%s/%s", open_host, item->d_name);
        entry->d_type = (stat(full, &st) == 0 && S_ISDIR(st.st_mode)) ? DT_DIR : DT_REG;
        return 0;
    }
    closedir(open_dir);
    open_dir = NULL;
    return -1;
}

int dir_findfirst(const char *path, dir_t *entry) {
    if (open_dir) closedir(open_dir);
    open_dir = opendir(host_path(path, open_host, sizeof(open_host)));
    if (!open_dir) return -1;
    return fill(entry);
}

int dir_findnext(const char *path, dir_t *entry) {
    (void)path;
    if (!open_dir) return -1;
    return fill(entry);
}

static void make_dir(const char *relative) {
    char host[768];
    snprintf(host, sizeof(host), "%s/%s", root, relative);
    assert(mkdir(host, 0700) == 0);
}

static void make_file(const char *relative) {
    char host[768];
    snprintf(host, sizeof(host), "%s/%s", root, relative);
    FILE *file = fopen(host, "wb");
    assert(file);
    fputs("\x80\x37\x12\x40", file);
    fclose(file);
}

static bool listed(const sm_catalog_t *catalog, const char *path) {
    for (uint32_t i = 0; i < catalog->count; i++) {
        sm_game_t game;
        if (catalog_get(catalog, i, &game) && !strcmp(game.path, path)) return true;
    }
    return false;
}

int main(void) {
    char template[] = "/tmp/sleekmenu-scan-XXXXXX";
    assert(mkdtemp(template));
    snprintf(root, sizeof(root), "%s", template);

    make_dir("Games");            make_file("Games/Alpha.z64");
    make_dir("Games/Hacks");      make_file("Games/Hacks/Beta.v64");
    make_dir("roms");             make_file("roms/Gamma.n64");
    make_file("Loose.z64");
    make_file("SleekMenu64.z64");                 /* the browser itself */
    make_file("._Loose.z64");                     /* macOS twin */
    make_file("notes.txt");
    make_dir("ED64");             make_file("ED64/OS64.v64");
    make_dir("ED64.bk2");         make_dir("ED64.bk2/edapp");
    make_file("ED64.bk2/edapp/app.n64");          /* a copy of the firmware folder */
    make_dir("sleekmenu");        make_file("sleekmenu/stale.z64");
    make_dir("menu");             make_file("menu/sc64menu.n64");
    make_dir("metadata");         make_file("metadata/art.z64");
    make_dir("System Volume Information"); make_file("System Volume Information/x.z64");
    make_dir(".Trashes");         make_file(".Trashes/y.z64");
    make_dir("$RECYCLE.BIN");     make_file("$RECYCLE.BIN/z.z64");

    sm_catalog_t catalog;
    memset(&catalog, 0, sizeof(catalog));
    char error[128] = "";
    assert(catalog_discover_sd(&catalog, SM_SD_ROOT, error, sizeof(error), NULL, NULL));
    assert(catalog.count == 4);
    /* Recorded relative to the card, spelled as the card spells them. */
    assert(listed(&catalog, "Games/Alpha.z64"));
    assert(listed(&catalog, "Games/Hacks/Beta.v64"));
    assert(listed(&catalog, "roms/Gamma.n64"));
    assert(listed(&catalog, "Loose.z64"));
    assert(!listed(&catalog, "SleekMenu64.z64"));
    assert(!listed(&catalog, "._Loose.z64"));
    assert(!listed(&catalog, "menu/sc64menu.n64"));
    assert(!listed(&catalog, "ED64.bk2/edapp/app.n64"));
    catalog_close(&catalog);

    /* A card with nothing on it is an error with a message, not a crash. */
    char empty[] = "/tmp/sleekmenu-empty-XXXXXX";
    assert(mkdtemp(empty));
    snprintf(root, sizeof(root), "%s", empty);
    assert(!catalog_discover_sd(&catalog, SM_SD_ROOT, error, sizeof(error), NULL, NULL));
    assert(strstr(error, "No N64 ROMs"));
    catalog_close(&catalog);
    puts("catalog scan: games anywhere on the card, bookkeeping skipped");
    return 0;
}
