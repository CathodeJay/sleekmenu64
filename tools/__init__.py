# SPDX-License-Identifier: AGPL-3.0-only
"""SleekMenu host tools.

Every tool here has to work two ways: imported as `tools.x` by the test suite,
and run as `python3 tools/x.py` by the Makefile and by anyone following the
README. Those two put different things on sys.path -- the second does not
include the repository root, so `from tools import ...` fails.

Each runnable module therefore begins with four lines that put the repository
root on the path when it was started as a script. That is what lets every
import below them be a plain `from tools import ...`.

It used to be done per file with an `if __package__:` branch carrying two
parallel lists of imports. There were ten of those, they had to be kept in step
by hand, and adding `from tools import card_layout` to a file without noticing
its branch is precisely how `python3 tools/prepare_card.py` stopped working
while `make test` stayed green. tests/test_tool_entry_points.py now runs every
one of them as a script so the two invocations cannot drift again.
"""
