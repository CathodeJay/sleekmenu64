/* SPDX-License-Identifier: AGPL-3.0-only */
/* Each line of standard input, spelled as the console spells a name it
   finds on the card, one per line of standard output. tests/
   test_build_catalog.py compares the answers with the builder's own. */
#include "folder_scan.h"

#include <stdio.h>
#include <string.h>

int main(void) {
    char line[256], out[256];
    while (fgets(line, sizeof(line), stdin) != NULL) {
        line[strcspn(line, "\n")] = '\0';
        sm_ascii_fold(line, out, sizeof(out));
        printf("%s\n", out);
    }
    return 0;
}
