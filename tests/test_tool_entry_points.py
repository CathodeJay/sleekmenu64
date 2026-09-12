# SPDX-License-Identifier: AGPL-3.0-only
"""Every tool has to run as a script, not only import as a module.

`make test` imports the tools as `tools.x`, which puts the repository root on
sys.path. The Makefile and the README run them as `python3 tools/x.py`, which
does not. The two disagree, and the suite only ever exercised the first -- so
adding `from tools import card_layout` to three modules broke every documented
command line while all 363 tests stayed green. It took a CI run on a fresh
clone to notice.

These tests run each tool the way a person does. `--help` is enough: argparse
exits 0 only after the module has been imported top to bottom, which is where
this class of failure lives.
"""

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = sorted(p for p in (ROOT / "tools").glob("*.py") if p.name != "__init__.py")


def runnable(path: Path) -> bool:
    """A tool with a __main__ guard is one somebody can start."""
    return '__name__ == "__main__"' in path.read_text(encoding="utf-8")


class EntryPointTests(unittest.TestCase):
    def test_there_are_tools_to_check(self):
        """A glob that quietly matched nothing would make every test below
        pass without running anything."""
        self.assertGreater(len(TOOLS), 10)
        self.assertTrue(any(p.name == "prepare_card.py" for p in TOOLS))

    def test_every_tool_runs_as_a_script_from_the_repository_root(self):
        for path in TOOLS:
            if not runnable(path):
                continue
            with self.subTest(tool=path.name):
                result = subprocess.run(
                    [sys.executable, str(path.relative_to(ROOT)), "--help"],
                    cwd=ROOT, capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0,
                                 f"python3 {path.relative_to(ROOT)} --help failed:\n"
                                 f"{result.stderr}")

    def test_every_tool_runs_as_a_script_from_somewhere_else(self):
        """Nothing may depend on the working directory being the repository:
        `python3 ~/src/sleekmenu64/tools/prepare_card.py` is a fair way to start
        one, and the path bootstrap is keyed on __file__ rather than on the cwd
        for exactly that reason.

        --help rather than no arguments: a tool whose options all have defaults
        starts doing real work when given none, which says nothing about its
        imports and quite a lot about the current directory."""
        for path in TOOLS:
            if not runnable(path):
                continue
            with self.subTest(tool=path.name):
                result = subprocess.run(
                    [sys.executable, str(path), "--help"], cwd="/",
                    capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0,
                                 f"python3 {path} --help failed from /:\n"
                                 f"{result.stderr}")
                self.assertNotIn("ModuleNotFoundError", result.stderr)

    def test_every_tool_also_imports_as_a_module(self):
        """The other half of the contract, which is what the rest of the suite
        relies on."""
        for path in TOOLS:
            with self.subTest(tool=path.name):
                result = subprocess.run(
                    [sys.executable, "-c", f"import tools.{path.stem}"],
                    cwd=ROOT, capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_no_tool_carries_the_old_dual_import_branch(self):
        """`if __package__:` with two parallel import lists is what this
        replaced. Ten copies had to be kept in step by hand, and the one that
        was not is the bug these tests exist for."""
        for path in TOOLS:
            with self.subTest(tool=path.name):
                for number, line in enumerate(
                        path.read_text(encoding="utf-8").splitlines(), 1):
                    self.assertFalse(line.startswith("if __package__:"),
                                     f"{path.name}:{number} is back to branching")


if __name__ == "__main__":
    unittest.main()
