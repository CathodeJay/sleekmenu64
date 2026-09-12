/* SPDX-License-Identifier: AGPL-3.0-only */
#include "x7_probe.h"
#include <assert.h>
#include <string.h>

int main(void) {
    uint32_t lba = 0;
    uint8_t a[SM_PROBE_SECTOR_SIZE];
    uint8_t b[SM_PROBE_SECTOR_SIZE];
    char message[128];
    sm_probe_report_t report;

    /* Mirrors FatFs clst2sect(): database + csize * (cluster - 2). */
    assert(sm_probe_first_lba(100u, 8u, 4096u, 2u, &lba) == 0 && lba == 100u);
    assert(sm_probe_first_lba(100u, 8u, 4096u, 3u, &lba) == 0 && lba == 108u);
    assert(sm_probe_first_lba(2048u, 64u, 0x10000u, 1000u, &lba) == 0 &&
        lba == 2048u + 64u * 998u);

    /* Clusters 0 and 1 are reserved; the top bound matches clst2sect(). */
    assert(sm_probe_first_lba(100u, 8u, 4096u, 0u, &lba) != 0);
    assert(sm_probe_first_lba(100u, 8u, 4096u, 1u, &lba) != 0);
    assert(sm_probe_first_lba(100u, 8u, 4096u, 4096u, &lba) != 0);
    assert(sm_probe_first_lba(100u, 8u, 4096u, 4097u, &lba) != 0);
    assert(sm_probe_first_lba(100u, 0u, 4096u, 2u, &lba) != 0);
    assert(sm_probe_first_lba(100u, 8u, 1u, 2u, &lba) != 0);
    assert(sm_probe_first_lba(100u, 8u, 4096u, 2u, NULL) != 0);
    /* Overflow must be refused rather than wrapping into a valid-looking LBA. */
    assert(sm_probe_first_lba(0xFFFFFF00u, 64u, 0xFFFFFFFFu, 0x100000u, &lba) != 0);

    memset(a, 0x5A, sizeof(a));
    memcpy(b, a, sizeof(b));
    assert(sm_probe_first_difference(a, b, sizeof(a)) == SM_PROBE_SECTOR_SIZE);
    b[0] ^= 0xFFu;
    assert(sm_probe_first_difference(a, b, sizeof(a)) == 0u);
    memcpy(b, a, sizeof(b));
    b[511] ^= 0xFFu;
    assert(sm_probe_first_difference(a, b, sizeof(a)) == 511u);

    /* The scratch window must clear the running SleekMenu image at offset 0. */
    assert(SM_PROBE_CART_OFFSET >= 16u * 1024u * 1024u);
    assert(SM_PROBE_CART_PHYS == 0x10000000u + SM_PROBE_CART_OFFSET);
    assert(SM_PROBE_CART_KSEG1 == 0xB0000000u + SM_PROBE_CART_OFFSET);

    memset(&report, 0, sizeof(report));
    report.step = SM_PROBE_OK;
    report.lba = 1234u;
    report.reference_crc = 0xDEADBEEFu;
    sm_probe_format(&report, message, sizeof(message));
    assert(strstr(message, "OK") != NULL);
    assert(strstr(message, "1234") != NULL);
    assert(strstr(message, "DEADBEEF") != NULL);

    report.step = SM_PROBE_CARD_FAILED;
    report.card_rc = -1;
    sm_probe_format(&report, message, sizeof(message));
    assert(strstr(message, "CARD FAIL") != NULL);

    report.step = SM_PROBE_DISPATCH_MISMATCH;
    report.first_diff = 7u;
    report.dispatch_crc = 0x12345678u;
    sm_probe_format(&report, message, sizeof(message));
    assert(strstr(message, "DISPATCH MISMATCH") != NULL);

    /* Truncation must still leave a terminated string. */
    sm_probe_format(&report, message, 8u);
    assert(strlen(message) < 8u);
    sm_probe_format(NULL, message, sizeof(message));
    assert(message[0] == '\0');
    return 0;
}
