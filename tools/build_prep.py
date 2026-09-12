#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Build sleekmenu-prep.pyz: the whole host toolchain as one file.

A Python zipapp is a zip with a #! line and a __main__.py. Python runs it
directly -- `python3 sleekmenu-prep.pyz` -- with the archive itself on the
import path, so the tools package inside works exactly as it does from a
checkout. It needs Python 3.9+ and Pillow on the machine and nothing else.

What goes in: the tools package, the two data files the pipeline is derived
from, and a generated entry point. What does not: tests, docs, the ROM, and
anything image-shaped. The archive is about 200 KB, of which the database is
half.

Reproducible: file timestamps inside the zip are pinned, so the same tree
produces the same bytes and a release can be checked against a rebuild.
"""

from __future__ import annotations

# Runnable as a script as well as importable -- see tools/__init__.py.
import sys as _sys
from pathlib import Path as _Path
if __package__ in (None, ""):
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import argparse
import shutil
import stat
import sys
import tempfile
import zipapp
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_PACKAGE = "sleekmenu_data"
DATA_FILES = ("coverdb.csv", "genres.csv")
#: Fixed so a rebuild of the same tree is byte-identical.
EPOCH = (2020, 1, 1, 0, 0, 0)
#: What zipapp would have generated, written by hand for the reason in stage()
#: -- with one improvement: zipapp's template discards main()'s return value,
#: so an archive built its way exits 0 whatever happened. A script that wraps
#: this tool deserves to know.
MAIN = """# -*- coding: utf-8 -*-
import sys
import tools.sleekmenu_prep
sys.exit(tools.sleekmenu_prep.main())
"""


def stage(into: Path) -> None:
    """Lay out exactly what the archive will contain."""
    tools = into / "tools"
    tools.mkdir(parents=True)
    for source in sorted((ROOT / "tools").glob("*.py")):
        if source.name == "build_prep.py":
            continue                    # the builder does not ship in what it builds
        shutil.copy2(source, tools / source.name)

    data = into / DATA_PACKAGE
    data.mkdir()
    (data / "__init__.py").write_text(
        '"""The database and genre map, carried inside sleekmenu-prep.pyz.\n'
        'Licensed CC BY-SA 4.0; see data/LICENSE in the repository."""\n',
        encoding="utf-8")
    for name in DATA_FILES:
        shutil.copy2(ROOT / "data" / name, data / name)
    shutil.copy2(ROOT / "data" / "LICENSE", data / "LICENSE")

    # The entry point is written here, as a file, rather than through zipapp's
    # main= option. zipapp generates that one with writestr(), which stamps the
    # zip entry with the current time -- so two builds a second apart differed
    # in one timestamp and the reproducibility test failed about one run in
    # ten. A file on disk gets the pinned mtime like everything else.
    (into / "__main__.py").write_text(MAIN, encoding="utf-8")

    # Pinned timestamps: zipapp records mtimes, and a build that differs only
    # in when it ran is not a build anyone can verify.
    import os, time
    fixed = time.mktime(EPOCH + (0, 0, -1))
    for path in into.rglob("*"):
        os.utime(path, (fixed, fixed))


def build(target: Path, interpreter: str = "/usr/bin/env python3") -> Path:
    with tempfile.TemporaryDirectory(prefix="sleekmenu-prep-build-") as scratch:
        staging = Path(scratch) / "app"
        stage(staging)
        target.parent.mkdir(parents=True, exist_ok=True)
        zipapp.create_archive(staging, target, interpreter=interpreter, compressed=True)
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return target


def contents(archive: Path) -> list[str]:
    with zipfile.ZipFile(archive) as z:
        return sorted(z.namelist())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build sleekmenu-prep.pyz.")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "build" / "release" / "sleekmenu-prep.pyz")
    parser.add_argument("--list", action="store_true", help="print what went in")
    args = parser.parse_args(argv)
    target = build(args.output)
    size = target.stat().st_size
    print(f"built {target} ({size // 1024} KB)")
    if args.list:
        for name in contents(target):
            print(f"  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
