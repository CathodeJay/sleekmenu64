/* SPDX-License-Identifier: AGPL-3.0-only */
#include "rom_load.h"
#include "x7_save_reg.h"
#include <assert.h>
#include <string.h>

int main(void) {
    sm_load_report_t r;
    char m[128];

    /* FatFs stages a partial trailing sector through its RDRAM window, which
       cannot target cartridge space, so transfers must be sector-aligned. */
    assert(sm_load_padded_size(0u) == 0u);
    assert(sm_load_padded_size(1u) == 512u);
    assert(sm_load_padded_size(511u) == 512u);
    assert(sm_load_padded_size(512u) == 512u);
    assert(sm_load_padded_size(513u) == 1024u);
    assert(sm_load_padded_size(8u * 1024u * 1024u) == 8u * 1024u * 1024u);
    /* Never wrap: a size that cannot be padded is returned unchanged. */
    assert(sm_load_padded_size(0xFFFFFFFFu) == 0xFFFFFFFFu);

    /* A byteswapped dump compared against what the cartridge holds: the
       file's 37 80 40 12 is the cartridge's 80 37 12 40, pair by pair, and
       swapping twice gives the file back. An odd last byte stays. */
    {
        uint8_t v64[] = {0x37, 0x80, 0x40, 0x12, 0x00, 0x0F, 0xAB};
        static const uint8_t z64[] = {0x80, 0x37, 0x12, 0x40, 0x0F, 0x00, 0xAB};
        sm_load_swap16(v64, sizeof(v64));
        assert(!memcmp(v64, z64, sizeof(z64)));
        sm_load_swap16(v64, sizeof(v64));
        assert(v64[0] == 0x37 && v64[1] == 0x80 && v64[6] == 0xAB);
        sm_load_swap16(v64, 0);
        sm_load_swap16(NULL, 4);
        assert(v64[0] == 0x37);
    }

    /* A verified load names its CRC; an unverified one must not, because
       there is no CRC to name and a stale zero would read as a real number. */
    memset(&r, 0, sizeof(r));
    r.step = SM_LOAD_OK; r.bytes = 8u * 1024u * 1024u; r.crc = 0xDEADBEEFu;
    r.verified = true;
    sm_load_format(&r, m, sizeof(m));
    assert(strstr(m, "VERIFIED") && strstr(m, "8192") && strstr(m, "DEADBEEF"));

    r.verified = false; r.crc = 0u;
    sm_load_format(&r, m, sizeof(m));
    assert(strstr(m, "8192") && strstr(m, "not verified"));
    assert(!strstr(m, "DEADBEEF") && !strstr(m, "crc"));

    r.step = SM_LOAD_MISMATCH; r.first_diff = 0x1234u; r.file_byte = 0xAB; r.sdram_byte = 0xCD;
    sm_load_format(&r, m, sizeof(m));
    assert(strstr(m, "MISMATCH") && strstr(m, "00001234") && strstr(m, "AB") && strstr(m, "CD"));

    r.step = SM_LOAD_TOO_LARGE;
    sm_load_format(&r, m, sizeof(m));
    assert(strstr(m, "exceeds"));

    sm_load_format(&r, m, 6u);
    assert(strlen(m) < 6u);
    sm_load_format(NULL, m, sizeof(m));
    assert(m[0] == '\0');

    /* REG_GAM_CFG takes krikzz's save-type ID verbatim. */
    assert(SM_X7_REG_GAM_CFG == 0x1F808018u);
    assert(sm_x7_gam_cfg_value(SM_SAVE_OFF) == 0u);
    assert(sm_x7_gam_cfg_value(SM_SAVE_EEP4K) == 1u);
    assert(sm_x7_gam_cfg_value(SM_SAVE_EEP16K) == 2u);
    assert(sm_x7_gam_cfg_value(SM_SAVE_SRM32K) == 3u);
    assert(sm_x7_gam_cfg_value(SM_SAVE_SRM96K) == 4u);
    assert(sm_x7_gam_cfg_value(SM_SAVE_FLASH) == 5u);
    assert(sm_x7_gam_cfg_value(SM_SAVE_SRM128K) == 6u);
    /* Anything outside the documented set means backup RAM off, not garbage. */
    assert(sm_x7_gam_cfg_value((sm_save_type_t)7) == 0u);
    assert(sm_x7_gam_cfg_value((sm_save_type_t)0x10) == 0u);
    return 0;
}
