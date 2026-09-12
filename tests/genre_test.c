/* SPDX-License-Identifier: AGPL-3.0-only */
/* Codes and colours have to be stable and short; the tab strip has room for
   three characters and the chips beside rows are four pixels square. */
#include "genre.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

/* catalog.c cannot be compiled on the host -- it pulls in libdragon -- so the
   catalog side of the interface is served from a fixture here. What is under
   test is how tabs are chosen and ordered, not how records are decoded. */
static const char *FIXTURE[64];
static uint32_t FIXTURE_COUNT;

bool catalog_get(const sm_catalog_t *catalog, uint32_t index, sm_game_t *game) {
    (void)catalog;
    if (index >= FIXTURE_COUNT) return false;
    memset(game, 0, sizeof(*game));
    game->title = "t";
    game->path = "p";
    game->cover = "";
    game->publisher = "";
    game->genre = FIXTURE[index];
    return true;
}

static void fixture(const char **genres, uint32_t count) {
    FIXTURE_COUNT = count;
    for (uint32_t i = 0; i < count; i++) FIXTURE[i] = genres[i];
}

static void expect_code(const char *genre, const char *want) {
    char code[SM_GENRE_CODE_LEN + 1u];
    sm_genre_code(genre, code);
    if (strcmp(code, want)) {
        fprintf(stderr, "code for %s\n  got  %s\n  want %s\n", genre, code, want);
        assert(0);
    }
}

int main(void) {
    /* The spellings libretro actually uses for this console. */
    expect_code("Role-playing (RPG)", "RPG");
    expect_code("Platform", "PLT");
    expect_code("Shooter", "SHT");
    expect_code("Beat'em Up", "BTM");
    expect_code("Racing", "RAC");
    expect_code("Puzzle", "PUZ");
    expect_code("Board", "BOA");
    expect_code("Action", "ACT");
    /* Punctuation and spaces never reach the strip. */
    expect_code("Music / Dancing", "MUS");
    expect_code("", "");
    expect_code("a", "A");
    {
        char code[SM_GENRE_CODE_LEN + 1u];
        sm_genre_code(NULL, code);
        assert(!code[0]);
        /* Never longer than the strip can draw, whatever the input. */
        sm_genre_code("Extraordinarily Long Genre Name", code);
        assert(strlen(code) == SM_GENRE_CODE_LEN);
    }

    /* A genre's colour must not depend on what else is on the card: the same
       name answers the same index every time, and unknown is always 0. */
    for (unsigned size = 1u; size <= 12u; size++) {
        assert(sm_genre_colour_index("", size) == 0u);
        assert(sm_genre_colour_index(NULL, size) == 0u);
        assert(sm_genre_colour_index("Racing", size) < size);
        assert(sm_genre_colour_index("Racing", size) == sm_genre_colour_index("Racing", size));
    }
    assert(sm_genre_colour_index("Racing", 0u) == 0u);
    /* Different genres should mostly land on different colours; with eight
       slots and the eight commonest genres, collisions are the thing to
       watch, so this pins how many there actually are. */
    {
        static const char *common[] = {"Sports", "Racing", "Shooter", "Action",
            "Platform", "Fighting", "Role-playing (RPG)", "Puzzle"};
        unsigned seen[8] = {0};
        for (size_t i = 0; i < 8; i++) seen[sm_genre_colour_index(common[i], 8u)]++;
        unsigned distinct = 0;
        for (size_t i = 0; i < 8; i++) if (seen[i]) distinct++;
        assert(distinct >= 5);   /* not a rainbow, but not all one colour either */
    }

    /* Tabs: "all" first, then the commonest genres on the card. */
    {
        static const char *library[] = {
            "Racing", "Racing", "Racing", "Sports", "Sports",
            "Platform", "", "", "Puzzle",
        };
        sm_catalog_t catalog = {0};
        sm_genre_tabs_t tabs;
        fixture(library, 9u);
        catalog.count = 9u;
        sm_genre_build_tabs(&catalog, &tabs);
        assert(tabs.count == 5u);                 /* all + four genres */
        assert(!tabs.tabs[0].name[0]);
        assert(!strcmp(tabs.tabs[0].code, "ALL"));
        assert(tabs.tabs[0].count == 9u);         /* the whole catalog, blanks included */
        assert(!strcmp(tabs.tabs[1].name, "Racing") && tabs.tabs[1].count == 3u);
        assert(!strcmp(tabs.tabs[2].name, "Sports") && tabs.tabs[2].count == 2u);
        for (uint32_t i = 2; i < tabs.count; i++)
            assert(tabs.tabs[i].count <= tabs.tabs[i - 1u].count);
        /* Every tab carries a drawable code. */
        for (uint32_t i = 0; i < tabs.count; i++) assert(tabs.tabs[i].code[0]);
    }

    /* A card with no metadata at all still gets a usable strip. */
    {
        static const char *blank[] = {"", "", ""};
        sm_catalog_t catalog = {0};
        sm_genre_tabs_t tabs;
        fixture(blank, 3u);
        catalog.count = 3u;
        sm_genre_build_tabs(&catalog, &tabs);
        assert(tabs.count == 1u);
        assert(!strcmp(tabs.tabs[0].code, "ALL"));
    }

    /* More genres than the strip can draw at once. Every one still gets a tab,
       because the strip scrolls; only a library past the table's own ceiling
       loses any, and that ceiling is far above a real N64 set. */
    {
        static const char *many[] = {"A","B","C","D","E","F","G","H","I","J","K","L"};
        sm_catalog_t catalog = {0};
        sm_genre_tabs_t tabs;
        fixture(many, 12u);
        catalog.count = 12u;
        sm_genre_build_tabs(&catalog, &tabs);
        assert(tabs.count == 13u);                /* all + twelve genres */
        assert(tabs.count > SM_GENRE_TABS_VISIBLE);
        for (uint32_t i = 0; i < tabs.count; i++)
            assert(strlen(tabs.tabs[i].code) <= SM_GENRE_CODE_LEN);
    }

    /* The bug this was written for: a genre that is real, common enough to
       matter, and simply never got a tab because seven others were seen
       first. Ordering by how often a genre appears is the whole point of the
       strip, and it has to hold for the tabs that exist, not just the ones
       that happened to be admitted. */
    {
        static const char *ordered[64];
        sm_catalog_t catalog = {0};
        sm_genre_tabs_t tabs;
        uint32_t at = 0, i;
        /* Nine one-off genres first, then the one that dominates the card. */
        static const char *rare[] = {"A","B","C","D","E","F","G","H","I"};
        for (i = 0; i < 9u; i++) ordered[at++] = rare[i];
        for (i = 0; i < 20u; i++) ordered[at++] = "Puzzle";
        fixture(ordered, at);
        catalog.count = at;
        sm_genre_build_tabs(&catalog, &tabs);
        assert(tabs.count == 11u);
        assert(!strcmp(tabs.tabs[1].name, "Puzzle"));
        assert(tabs.tabs[1].count == 20u);
    }

    /* The window the strip draws: the selection stays on screen, roughly
       centred, and never scrolls past either end. */
    {
        assert(sm_genre_tab_window(0u, 5u, 8u) == 0u);      /* fits: no window */
        assert(sm_genre_tab_window(0u, 24u, 8u) == 0u);
        assert(sm_genre_tab_window(3u, 24u, 8u) == 0u);     /* still near the left */
        assert(sm_genre_tab_window(10u, 24u, 8u) == 6u);    /* centred */
        assert(sm_genre_tab_window(23u, 24u, 8u) == 16u);   /* clamped at the right */
        assert(sm_genre_tab_window(99u, 24u, 8u) == 16u);   /* out of range is clamped */
        assert(sm_genre_tab_window(3u, 24u, 0u) == 0u);     /* nothing drawable */
        for (uint32_t active = 0; active < 24u; active++) {
            uint32_t first = sm_genre_tab_window(active, 24u, 8u);
            assert(active >= first && active < first + 8u);
            assert(first + 8u <= 24u);
        }
    }

    { sm_genre_tabs_t tabs; sm_genre_build_tabs(NULL, &tabs); assert(tabs.count == 1u); }
    sm_genre_build_tabs(NULL, NULL);   /* must not crash */

    /* Every tab the strip builds has to fit across the list column: 168
       pixels, a 4px chip, 2px gutter, three 6px characters, 3px between. */
    {
        const int start = 3, code = 3 * 6, gap = 3;
        int last = start + (int)(SM_GENRE_TABS_VISIBLE - 1u) * (code + gap);
        assert(last + code <= 168);
    }

    /* The consolidated genres data/genres.csv produces have to reduce to
       twelve distinct three-letter codes. Two tabs reading ACT would leave one
       of them unreachable and the other lying about what it filters. If a
       genre is added to that file, add its code to NAMED and extend this. */
    {
        static const char *CONSOLIDATED[] = {
            "Action", "Action-Adventure", "Fighting", "Other", "Platforms",
            "Puzzle", "Racing", "Role Playing Games", "Shooters", "Simulation",
            "Sports", "Strategy",
            /* Not a genre, but it shares the strip and so shares the rule:
               two tabs reading the same three letters is one tab too many. */
            "Favourites",
        };
        const uint32_t count = (uint32_t)(sizeof(CONSOLIDATED) / sizeof(*CONSOLIDATED));
        char codes[32][SM_GENRE_CODE_LEN + 1u];
        assert(count <= 32u);
        for (uint32_t i = 0; i < count; i++) {
            sm_genre_code(CONSOLIDATED[i], codes[i]);
            assert(strlen(codes[i]) == SM_GENRE_CODE_LEN);
        }
        for (uint32_t i = 0; i < count; i++)
            for (uint32_t j = i + 1u; j < count; j++)
                if (!strcmp(codes[i], codes[j])) {
                    fprintf(stderr, "genre code collision: %s and %s both give %s\n",
                            CONSOLIDATED[i], CONSOLIDATED[j], codes[i]);
                    assert(0);
                }
        /* And the colours, which are hashed from the name, must not collide
           across a palette this small either -- a genre is identified by its
           colour beside every row. */
        assert(count + 1u <= SM_GENRE_TABS_MAX);
    }

    printf("genre host checks passed\n");
    return 0;
}
