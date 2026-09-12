# SPDX-License-Identifier: AGPL-3.0-only
"""SleekMenu host tools.

Every tool here has to work two ways: imported as `tools.x` by the test suite,
and run as `python3 tools/x.py` by the Makefile and by anyone following the
README. Those two put different things on sys.path -- the second does not
include the repository root, so `from tools import ...` fails.

Each runnable module therefore begins with four lines that put the repository
root on the path when it was started as a script. That is what lets every
import below them be a plain `from tools import ...`.

One shared preamble rather than a per-file `if __package__:` branch with
its own list of imports: those lists have to be kept in step by hand, and
an import added to a file without its branch is exactly how a script stops
working while `make test` stays green. tests/test_tool_entry_points.py runs
every tool as a script so the two invocations cannot drift.
"""
