/* SPDX-License-Identifier: AGPL-3.0-only */
#include "history.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static sm_history_t h;

static void record_n(unsigned n) {
    char path[64];
    unsigned i;
    for (i = 0; i < n; i++) { snprintf(path, sizeof(path), "/ROMS/g%u.z64", i); assert(sm_history_record(&h, path)); }
}

int main(void) {
    sm_history_reset(&h);
    assert(sm_history_count(&h) == 0);
    assert(h.paths[0][0] == '\0');

    /* most recent first */
    assert(sm_history_record(&h, "/ROMS/a.z64"));
    assert(sm_history_record(&h, "/ROMS/b.z64"));
    assert(sm_history_count(&h) == 2);
    assert(!strcmp(h.paths[0], "/ROMS/b.z64"));
    assert(!strcmp(h.paths[1], "/ROMS/a.z64"));

    /* replaying moves to front rather than duplicating */
    assert(sm_history_record(&h, "/ROMS/a.z64"));
    assert(sm_history_count(&h) == 2);
    assert(!strcmp(h.paths[0], "/ROMS/a.z64"));
    assert(!strcmp(h.paths[1], "/ROMS/b.z64"));

    /* recording the current head is a no-op, not a shuffle */
    assert(sm_history_record(&h, "/ROMS/a.z64"));
    assert(sm_history_count(&h) == 2);
    assert(!strcmp(h.paths[0], "/ROMS/a.z64"));

    /* case-insensitive, like the card */
    assert(sm_history_position(&h, "/roms/A.Z64") == 0);

    /* the cap holds and the oldest falls off */
    sm_history_reset(&h);
    record_n(SM_HISTORY_MAX + 5u);
    assert(sm_history_count(&h) == SM_HISTORY_MAX);
    assert(!strcmp(h.paths[0], "/ROMS/g19.z64"));
    assert(!strcmp(h.paths[SM_HISTORY_MAX - 1u], "/ROMS/g5.z64"));
    assert(sm_history_position(&h, "/ROMS/g0.z64") == -1);

    /* replaying the oldest rescues it without losing anyone else */
    assert(sm_history_record(&h, "/ROMS/g5.z64"));
    assert(sm_history_count(&h) == SM_HISTORY_MAX);
    assert(!strcmp(h.paths[0], "/ROMS/g5.z64"));
    assert(sm_history_position(&h, "/ROMS/g19.z64") == 1);
    assert(sm_history_position(&h, "/ROMS/g6.z64") == (int32_t)SM_HISTORY_MAX - 1);

    /* format/parse round trip preserves order */
    {
        char text[SM_HISTORY_MAX * SM_HISTORY_PATH_MAX];
        sm_history_t back;
        size_t used = sm_history_format(&h, text, sizeof(text));
        assert(used && used < sizeof(text));
        sm_history_reset(&back);
        sm_history_parse(&back, text, used);
        assert(sm_history_count(&back) == sm_history_count(&h));
        for (uint32_t i = 0; i < sm_history_count(&h); i++)
            assert(!strcmp(back.paths[i], h.paths[i]));
    }

    /* a file with more than the cap keeps the most recent */
    {
        const char *text = "/a\n/b\n/c\n/d\n/e\n/f\n/g\n/h\n/i\n/j\n/k\n/l\n/m\n/n\n/o\n/p\n/q\n";
        sm_history_reset(&h);
        sm_history_parse(&h, text, strlen(text));
        assert(sm_history_count(&h) == SM_HISTORY_MAX);
        assert(!strcmp(h.paths[0], "/a"));
    }

    /* a hand-edited file with a repeat keeps the first, more recent, copy */
    {
        const char *text = "/a\n/b\n/a\n/c\n";
        sm_history_reset(&h);
        sm_history_parse(&h, text, strlen(text));
        assert(sm_history_count(&h) == 3);
        assert(!strcmp(h.paths[0], "/a"));
        assert(!strcmp(h.paths[1], "/b"));
        assert(!strcmp(h.paths[2], "/c"));
    }

    /* blank and over-long lines are skipped, not fatal */
    {
        char text[SM_HISTORY_PATH_MAX * 2];
        memset(text, 'x', sizeof(text));
        memcpy(text, "/keep\n\n\n", 8);
        text[sizeof(text) - 1] = '\0';
        sm_history_reset(&h);
        sm_history_parse(&h, text, strlen(text));
        assert(sm_history_count(&h) == 1);
        assert(!strcmp(h.paths[0], "/keep"));
    }

    /* a path too long to record is refused rather than truncated: a truncated
       path would name a different file, or none. */
    sm_history_reset(&h);
    {
        char oversize[SM_HISTORY_PATH_MAX + 8];
        memset(oversize, 'x', sizeof(oversize));
        oversize[sizeof(oversize) - 1] = '\0';
        assert(!sm_history_record(&h, oversize));
        assert(sm_history_count(&h) == 0);
    }
    assert(!sm_history_record(&h, ""));
    assert(!sm_history_record(&h, NULL));
    assert(!sm_history_record(NULL, "/x"));

    printf("history: ok\n");
    return 0;
}
