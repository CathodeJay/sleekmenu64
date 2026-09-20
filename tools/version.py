# SPDX-License-Identifier: AGPL-3.0-only
"""The release's number: what the window's title, `sleekmenu-prep
--version` and the browser's start screen say, so a question about a card
can start from which SleekMenu prepared it and which one reads it.

src/version.h carries the same number for the console, and
tests/test_portability.py holds the two together. A release is a tag
`v<VERSION>`; the release workflow refuses a tag that says otherwise, so
the number is changed here and in version.h before tagging, never after.
"""

VERSION = "1.1.0"
