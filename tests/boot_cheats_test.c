/* SPDX-License-Identifier: AGPL-3.0-only */
/* Compiled after the production decoder by test_boot_cheats.py. */
#include <assert.h>
#include <stddef.h>

static void expect_single(uint32_t **cursor, uint8_t type, uint32_t address, uint16_t value) {
    uint32_t *before = *cursor;
    cheat_entry_t entry = {0};
    assert(cheats_get_next(cursor, &entry));
    assert(*cursor == before + 2);
    assert(entry.main.type == type);
    assert(entry.main.address == address);
    assert(entry.main.value == value);
    assert(entry.sub.type == 0);
}

static void expect_end(uint32_t **cursor) {
    uint32_t *before = *cursor;
    cheat_entry_t entry = {0};
    assert(!cheats_get_next(cursor, &entry));
    assert(*cursor == before + 2);
}

static void test_master_preserves_expansion_pak_code(void) {
    uint32_t words[] = {0xDE000400, 0, 0xEE000000, 0, 0, 0};
    uint32_t *cursor = words;
    expect_single(&cursor, 0xDE, 0x80000400, 0);
    expect_single(&cursor, 0xEE, 0xA0000000, 0);
    expect_end(&cursor);
    assert(cursor == words + sizeof(words) / sizeof(words[0]));
}

static void test_master_preserves_runtime_write(void) {
    uint32_t words[] = {0xDE000400, 0, 0x8026B1CB, 3, 0, 0};
    uint32_t *cursor = words;
    expect_single(&cursor, 0xDE, 0x80000400, 0);
    expect_single(&cursor, 0x80, 0x8026B1CB, 3);
    expect_end(&cursor);
}

static void test_master_preserves_engine_location(void) {
    uint32_t words[] = {0xDE000400, 0, 0xFF3E0000, 0, 0, 0};
    uint32_t *cursor = words;
    expect_single(&cursor, 0xDE, 0x80000400, 0);
    expect_single(&cursor, 0xFF, 0xA03E0000, 0);
    expect_end(&cursor);
}

static void test_master_at_end(void) {
    uint32_t words[] = {0xDE000400, 0, 0, 0};
    uint32_t *cursor = words;
    expect_single(&cursor, 0xDE, 0x80000400, 0);
    expect_end(&cursor);
    assert(cursor == words + sizeof(words) / sizeof(words[0]));
}

static void test_expansion_pak_code_alone(void) {
    uint32_t words[] = {0xEE000000, 0, 0, 0};
    uint32_t *cursor = words;
    expect_single(&cursor, 0xEE, 0xA0000000, 0);
    expect_end(&cursor);
}

static void test_consecutive_master_codes(void) {
    uint32_t words[] = {0xDE000400, 0, 0xDE000800, 0, 0xEE000000, 0, 0, 0};
    uint32_t *cursor = words;
    expect_single(&cursor, 0xDE, 0x80000400, 0);
    expect_single(&cursor, 0xDE, 0x80000800, 0);
    expect_single(&cursor, 0xEE, 0xA0000000, 0);
    expect_end(&cursor);
}

static void test_conditionals_and_repeater(void) {
    const uint32_t codes[] = {0xD0001000, 0xD1001000, 0xD2001000, 0xD3001000, 0x50000102};
    for (size_t i = 0; i < sizeof(codes) / sizeof(codes[0]); i++) {
        uint32_t words[] = {codes[i], 0xABCD, 0x81234566, 0x1234, 0x8026B1CB, 3, 0, 0};
        uint32_t *cursor = words;
        cheat_entry_t entry = {0};
        assert(cheats_get_next(&cursor, &entry));
        assert(cursor == words + 4);
        assert(entry.main.type == codes[i] >> 24);
        assert(entry.main.value == 0xABCD);
        assert(entry.sub.type == 0x81);
        assert(entry.sub.address == 0x80234566);
        assert(entry.sub.value == 0x1234);
        expect_single(&cursor, 0x80, 0x8026B1CB, 3);
        expect_end(&cursor);
    }
}

static void test_other_d_opcodes_preserve_following_write(void) {
    for (uint8_t type = 0xD4; type <= 0xDF; type++) {
        uint32_t words[] = {((uint32_t)type << 24) | 0x1000, 0xABCD, 0x8026B1CB, 3, 0, 0};
        uint32_t *cursor = words;
        expect_single(&cursor, type, 0x80001000, 0xABCD);
        expect_single(&cursor, 0x80, 0x8026B1CB, 3);
        expect_end(&cursor);
    }
}

int main(void) {
    test_master_preserves_expansion_pak_code();
    test_master_preserves_runtime_write();
    test_master_preserves_engine_location();
    test_master_at_end();
    test_expansion_pak_code_alone();
    test_consecutive_master_codes();
    test_conditionals_and_repeater();
    test_other_d_opcodes_preserve_following_write();
    return 0;
}
