/* SPDX-License-Identifier: AGPL-3.0-only */
#include "cheat_pack.h"
#include <ctype.h>
#include <string.h>
#include <strings.h>

/* -- regions ---------------------------------------------------------------- */

uint16_t sm_region_from_code(char letter) {
    switch (letter) {
    case 'E': return SM_CART_REGION_USA;
    case 'J': return SM_CART_REGION_JAPAN;
    case 'P': case 'X': case 'Y': return SM_CART_REGION_EUROPE;
    case 'D': return SM_CART_REGION_GERMANY;
    case 'F': return SM_CART_REGION_FRANCE;
    case 'I': return SM_CART_REGION_ITALY;
    case 'S': return SM_CART_REGION_SPAIN;
    case 'U': return SM_CART_REGION_AUSTRALIA;
    /* 'A' is the NTSC cartridge sold in both Japan and America (1080). */
    case 'A': return SM_CART_REGION_USA | SM_CART_REGION_JAPAN;
    default: return 0;
    }
}

const char *sm_region_name(uint16_t one) {
    switch (one) {
    case SM_CART_REGION_USA: return "USA";
    case SM_CART_REGION_EUROPE: return "Europe";
    case SM_CART_REGION_JAPAN: return "Japan";
    case SM_CART_REGION_FRANCE: return "France";
    case SM_CART_REGION_GERMANY: return "Germany";
    case SM_CART_REGION_ITALY: return "Italy";
    case SM_CART_REGION_SPAIN: return "Spain";
    case SM_CART_REGION_AUSTRALIA: return "Australia";
    default: return "unknown";
    }
}

size_t sm_region_list(uint16_t set, char *out, size_t out_size) {
    size_t n = 0;
    unsigned bit;
    if (!out || !out_size) return 0;
    out[0] = '\0';
    for (bit = 0; bit < 8; bit++) {
        const char *name;
        size_t length;
        if (!(set & (1u << bit))) continue;
        name = sm_region_name((uint16_t)(1u << bit));
        length = strlen(name);
        if (n + (n ? 2 : 0) + length >= out_size) break;
        if (n) { memcpy(out + n, ", ", 2); n += 2; }
        memcpy(out + n, name, length);
        n += length;
        out[n] = '\0';
    }
    return n;
}

/* GoodN64's tag letters, as the pack uses them. */
static uint16_t region_from_tag(const char *token, size_t length) {
    if (length == 1) {
        switch (token[0]) {
        case 'U': return SM_CART_REGION_USA;
        case 'E': return SM_CART_REGION_EUROPE;
        case 'J': return SM_CART_REGION_JAPAN;
        case 'F': return SM_CART_REGION_FRANCE;
        case 'G': return SM_CART_REGION_GERMANY;
        case 'I': return SM_CART_REGION_ITALY;
        case 'S': return SM_CART_REGION_SPAIN;
        case 'A': return SM_CART_REGION_AUSTRALIA;
        default: return 0;
        }
    }
    if (length == 4 && !strncasecmp(token, "NTSC", 4)) return SM_CART_REGION_USA;
    if (length == 3 && !strncasecmp(token, "PAL", 3)) return SM_CART_REGION_EUROPE;
    return 0;
}

/* -- the untagged files ------------------------------------------------------ */

/* The pack's files without a region tag, by their folded name, with the
   region their codes turned out to belong to. Settled once, on the desk,
   by matching each file's codes against libretro's region-named files for
   the same game (the pack is the older half of that database, byte for
   byte): a file whose codes sit in the Europe file and not the USA one is
   the Europe file under another name. Files whose codes matched nothing
   clearly are not here, and are handed over marked unverified. `alias` is
   the game's usual name folded the same way, for the few files named
   after neither the ROM file nor the header title. */
typedef struct {
    const char *base;
    uint16_t regions;
    const char *alias;
} untagged_t;

static const untagged_t UNTAGGED[] = {
    {"aerofightersassaul", SM_CART_REGION_EUROPE, NULL},
    {"aerogauge", SM_CART_REGION_EUROPE, NULL},
    {"armymensarge", SM_CART_REGION_EUROPE, "armymensargesheroes"},
    {"banjotooie", SM_CART_REGION_AUSTRALIA, NULL},
    {"banjokazooie", SM_CART_REGION_USA, NULL},
    {"bustamove3dx", SM_CART_REGION_EUROPE, NULL},
    {"castlevania", SM_CART_REGION_EUROPE, NULL},
    {"daffyduckstarring", SM_CART_REGION_EUROPE, "daffyduckstarringasduckdodgers"},
    {"dancedancerevolutiondisneydancingmuseum", SM_CART_REGION_JAPAN, NULL},
    {"donaldduckquackat", SM_CART_REGION_EUROPE, "donaldduckquackattack"},
    {"dukenukemzerohour", SM_CART_REGION_USA, NULL},
    {"excitebike64", SM_CART_REGION_EUROPE, NULL},
    {"flyingdragon", SM_CART_REGION_EUROPE, NULL},
    {"gauntletlegends", SM_CART_REGION_USA, NULL},
    {"goldeneye", SM_CART_REGION_USA, "goldeneye007"},
    {"hybridheavenpal", SM_CART_REGION_EUROPE, "hybridheaven"},
    {"iggysreckinballs", SM_CART_REGION_EUROPE, NULL},
    {"jetforcegemini", SM_CART_REGION_EUROPE, NULL},
    {"kinghill64", SM_CART_REGION_JAPAN, "kinghill64extremesnowboarding"},
    {"lamborghini", SM_CART_REGION_EUROPE, "automobililamborghini"},
    {"mickeyusapal", SM_CART_REGION_EUROPE, "mickeysspeedwayusa"},
    {"mysticalninja", SM_CART_REGION_EUROPE, "mysticalninjastarringgoemon"},
    {"nbajam2000", SM_CART_REGION_USA, NULL},
    {"operationwinback", SM_CART_REGION_EUROPE, NULL},
    {"pilotwings64", SM_CART_REGION_EUROPE, NULL},
    {"rainbowsix", SM_CART_REGION_USA, "tomclancysrainbowsix"},
    {"roadrash64", SM_CART_REGION_USA, NULL},
    {"roadsterstrophy", SM_CART_REGION_EUROPE, "roadsters"},
    {"smashbrothers", SM_CART_REGION_USA, "supersmashbros"},
    {"supermario64", SM_CART_REGION_EUROPE, NULL},
    {"siliconvalley", SM_CART_REGION_EUROPE, "spacestationsiliconvalley"},
    {"topgearrally", SM_CART_REGION_EUROPE, NULL},
    {"twistededge", SM_CART_REGION_USA, "twistededgeextremesnowboarding"},
    {"wcwnworevenge", SM_CART_REGION_USA | SM_CART_REGION_EUROPE, NULL},
    {"wcwmayhem", SM_CART_REGION_EUROPE, NULL},
    {"wipeout64", SM_CART_REGION_EUROPE, NULL},
    /* Named after neither file nor title; region not settled. */
    {"kirby64", 0, "kirby64thecrystalshards"},
    {"mariogolf64", 0, "mariogolf"},
    {"shadowoftheempire", 0, "starwarsshadowsoftheempire"},
    {"tgrally2", 0, "topgearrally2"},
    {"tomandjerry", 0, "tomandjerryinfistsoffurry"},
    {"gaspfightersne", 0, "gaspfightersnextream"},
};

static const untagged_t *untagged_lookup(const char *base) {
    size_t i;
    for (i = 0; i < sizeof(UNTAGGED) / sizeof(UNTAGGED[0]); i++)
        if (!strcmp(UNTAGGED[i].base, base)) return &UNTAGGED[i];
    return NULL;
}

/* -- names ------------------------------------------------------------------- */

size_t sm_cheat_pack_normalise(const char *text, char *out, size_t out_size) {
    size_t n = 0;
    int depth = 0;
    if (!out || !out_size) return 0;
    out[0] = '\0';
    if (!text) return 0;
    for (; *text; text++) {
        unsigned char c = (unsigned char)*text;
        if (c == '(' || c == '[') { depth++; continue; }
        if (c == ')' || c == ']') { if (depth) depth--; continue; }
        if (depth) continue;
        if (c == '&') {
            if (n + 3 >= out_size) break;
            memcpy(out + n, "and", 3);
            n += 3;
            continue;
        }
        if (!isalnum(c)) continue;
        if (n + 1 >= out_size) break;
        out[n++] = (char)tolower(c);
    }
    out[n] = '\0';
    return n;
}

/* The stem of a file name: past the last '/', before the last '.'. */
static size_t stem_of(const char *path, const char **start) {
    const char *slash = path ? strrchr(path, '/') : NULL;
    const char *name = slash ? slash + 1 : path;
    const char *dot = name ? strrchr(name, '.') : NULL;
    *start = name;
    if (!name) return 0;
    return dot ? (size_t)(dot - name) : strlen(name);
}

/* The tags of a name: every "(...)" and "[...]" group, split on commas
   and spaces. Regions add up; a version tag ("V1.1", "v1.0", "1.2") gives
   its minor number. */
static void read_tags(const char *text, size_t length, uint16_t *regions, uint8_t *version) {
    size_t i = 0;
    *regions = 0;
    *version = 0xFF;
    while (i < length) {
        char open = text[i];
        char close;
        size_t end;
        if (open != '(' && open != '[') { i++; continue; }
        close = open == '(' ? ')' : ']';
        for (end = i + 1; end < length && text[end] != close; end++) {}
        {
            size_t at = i + 1;
            while (at < end) {
                size_t token_end = at;
                while (token_end < end && text[token_end] != ',' && text[token_end] != ' ') token_end++;
                if (token_end > at) {
                    const char *token = text + at;
                    size_t token_length = token_end - at;
                    uint16_t region = region_from_tag(token, token_length);
                    if (region) *regions |= region;
                    else {
                        size_t v = (token[0] == 'V' || token[0] == 'v') ? 1 : 0;
                        if (token_length == v + 3 && isdigit((unsigned char)token[v]) && token[v + 1] == '.' &&
                            isdigit((unsigned char)token[v + 2]))
                            *version = (uint8_t)(token[v + 2] - '0');
                    }
                }
                at = token_end + 1;
            }
        }
        i = end + 1;
    }
}

/* A ROM's revision from its No-Intro tags: "(Rev 1)", "(Rev A)" (= 1),
   "(Rev B)" (= 2); a GoodN64 "(V1.1)" counts too. 0 when none. */
static uint8_t read_revision(const char *text, size_t length) {
    size_t i;
    for (i = 0; i + 5 < length; i++) {
        if (text[i] == '(' && !strncasecmp(text + i + 1, "Rev ", 4)) {
            char c = text[i + 5];
            if (isdigit((unsigned char)c)) return (uint8_t)(c - '0');
            if (c >= 'A' && c <= 'Z') return (uint8_t)(c - 'A' + 1);
        }
    }
    {
        uint16_t regions;
        uint8_t version;
        read_tags(text, length, &regions, &version);
        return version == 0xFF ? 0 : version;
    }
}

/* -- the pack ---------------------------------------------------------------- */

void sm_cheat_pack_reset(sm_cheat_pack_t *pack) {
    if (!pack) return;
    memset(pack, 0, sizeof(*pack));
}

static bool pool_add(sm_cheat_pack_t *pack, const char *text, size_t length, uint16_t *at) {
    if (pack->used + length + 1u > sizeof(pack->pool)) return false;
    *at = (uint16_t)pack->used;
    memcpy(pack->pool + pack->used, text, length);
    pack->pool[pack->used + length] = '\0';
    pack->used += (uint32_t)(length + 1u);
    return true;
}

bool sm_cheat_pack_add(sm_cheat_pack_t *pack, const char *name) {
    size_t length, stem;
    char base[128];
    size_t base_length;
    uint16_t regions;
    uint8_t version;
    uint32_t before;
    if (!pack || !name) return false;
    length = strlen(name);
    if (length < 5 || strcasecmp(name + length - 4, ".cht")) return false;
    /* macOS leaves an AppleDouble twin ("._X.cht") beside a file it copied
       to a FAT card; it is resource-fork bookkeeping, not a cheat file. */
    if (name[0] == '.' && name[1] == '_') return false;
    if (pack->count >= SM_CHEAT_PACK_MAX) { pack->dropped++; return false; }
    stem = length - 4;
    {
        char stem_text[256];
        if (stem >= sizeof(stem_text)) { pack->dropped++; return false; }
        memcpy(stem_text, name, stem);
        stem_text[stem] = '\0';
        base_length = sm_cheat_pack_normalise(stem_text, base, sizeof(base));
        read_tags(stem_text, stem, &regions, &version);
    }
    if (!base_length) { pack->dropped++; return false; }
    if (!regions) {
        const untagged_t *known = untagged_lookup(base);
        if (known) regions = known->regions;
    }
    before = pack->used;
    if (!pool_add(pack, name, length, &pack->name_at[pack->count]) ||
        !pool_add(pack, base, base_length, &pack->base_at[pack->count])) {
        pack->used = before;
        pack->dropped++;
        return false;
    }
    pack->regions[pack->count] = regions;
    pack->version[pack->count] = version;
    pack->count++;
    return true;
}

const char *sm_cheat_pack_name(const sm_cheat_pack_t *pack, uint32_t index) {
    if (!pack || index >= pack->count) return NULL;
    return pack->pool + pack->name_at[index];
}

/* -- the match --------------------------------------------------------------- */

/* Whether a pack entry is the same game as a ROM: by the folded name of
   the ROM file, or of the header title, against the entry's folded name
   or its alias. */
static bool same_game(const sm_cheat_pack_t *pack, uint32_t index, const char *rom_base,
    const char *title_base) {
    const char *base = pack->pool + pack->base_at[index];
    const untagged_t *known;
    if (rom_base[0] && !strcmp(base, rom_base)) return true;
    if (title_base[0] && !strcmp(base, title_base)) return true;
    known = untagged_lookup(base);
    if (known && known->alias) {
        if (rom_base[0] && !strcmp(known->alias, rom_base)) return true;
        if (title_base[0] && !strcmp(known->alias, title_base)) return true;
    }
    return false;
}

/* Among files of the right region, the one whose version tag matches the
   ROM's revision, else the one without a version tag, else the lowest. */
static int version_rank(uint8_t version, uint8_t revision) {
    if (version == revision) return 0;
    if (version == 0xFF) return 1;
    return 2 + version;
}

sm_cheat_match_t sm_cheat_pack_find(const sm_cheat_pack_t *pack, const char *rom_path,
    const uint8_t *header, size_t header_length) {
    sm_cheat_match_t match;
    const char *stem;
    size_t stem_length;
    char rom_base[128], title_base[64];
    uint8_t revision;
    uint32_t i;
    int best_region = -1, best_pal = -1, best_unverified = -1;

    memset(&match, 0, sizeof(match));
    if (!pack || !rom_path) return match;
    stem_length = stem_of(rom_path, &stem);
    if (!stem_length) return match;

    /* 1. Named exactly like the ROM: nothing to decide. */
    for (i = 0; i < pack->count; i++) {
        const char *name = pack->pool + pack->name_at[i];
        if (strlen(name) == stem_length + 4u && !strncasecmp(name, stem, stem_length)) {
            match.kind = SM_CHEAT_MATCH_EXACT;
            match.name = name;
            return match;
        }
    }

    /* 2. The same game under the pack's own naming. */
    {
        char stem_text[256];
        if (stem_length >= sizeof(stem_text)) return match;
        memcpy(stem_text, stem, stem_length);
        stem_text[stem_length] = '\0';
        sm_cheat_pack_normalise(stem_text, rom_base, sizeof(rom_base));
        revision = read_revision(stem_text, stem_length);
    }
    title_base[0] = '\0';
    if (header && header_length >= 0x40u) {
        char title[21];
        memcpy(title, header + 0x20, 20);
        title[20] = '\0';
        sm_cheat_pack_normalise(title, title_base, sizeof(title_base));
        match.rom_region = sm_region_from_code((char)header[0x3E]);
    }
    for (i = 0; i < pack->count; i++) {
        uint16_t regions;
        if (!same_game(pack, i, rom_base, title_base)) continue;
        regions = pack->regions[i];
        match.found |= regions;
        if (regions & match.rom_region) {
            if (best_region < 0 || version_rank(pack->version[i], revision) <
                version_rank(pack->version[(uint32_t)best_region], revision))
                best_region = (int)i;
        } else if (!regions) {
            if (best_unverified < 0) best_unverified = (int)i;
        } else if ((match.rom_region & SM_CART_REGION_PAL) && (regions & SM_CART_REGION_EUROPE)) {
            if (best_pal < 0) best_pal = (int)i;
        }
    }
    if (best_region >= 0) {
        match.kind = SM_CHEAT_MATCH_REGION;
        match.name = pack->pool + pack->name_at[(uint32_t)best_region];
    } else if (best_pal >= 0) {
        match.kind = SM_CHEAT_MATCH_PAL;
        match.name = pack->pool + pack->name_at[(uint32_t)best_pal];
    } else if (best_unverified >= 0) {
        match.kind = SM_CHEAT_MATCH_UNVERIFIED;
        match.name = pack->pool + pack->name_at[(uint32_t)best_unverified];
    } else if (match.found) {
        match.kind = SM_CHEAT_MATCH_OTHER_REGION;
    }
    return match;
}
