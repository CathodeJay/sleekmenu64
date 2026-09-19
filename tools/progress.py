# SPDX-License-Identifier: AGPL-3.0-only
"""A progress line for the parts of a run that take a while.

Three phases of a card build are long enough to look like a hang: reading a
few thousand ROM headers off an SD card, downloading a few hundred pictures,
and converting them. Each printed one line at the start and one at the end,
and a person watching a terminal that has not changed in two minutes has no
way to tell "working" from "stuck" -- which is exactly the report that led
here.

On a terminal this rewrites one line in place, a few times a second at most.
Anywhere else -- CI logs, a pipe -- it prints a line at each tenth, so the
output is still readable afterwards rather than a wall of carriage returns.

The steps are also where a run is stopped on request. A window's Stop
button cannot interrupt a thread; what it can do is set a flag, and
`stoppable()` wraps any progress factory so that the flag is looked at
before every step and answered with Cancelled between two files, or between
two pieces of a download, never in the middle of one.
"""

from __future__ import annotations

import sys
import time


class Cancelled(Exception):
    """The run was asked to stop, and did, at a step."""


def stoppable(progress_factory, cancel):
    """`progress_factory` with `cancel()` asked before every step: true, and
    the step raises Cancelled instead of counting."""
    def factory(total: int, label: str):
        return _Stoppable(progress_factory(total, label), cancel, label)
    return factory


class _Stoppable:
    def __init__(self, bar, cancel, label: str):
        self.bar, self.cancel, self.label = bar, cancel, label

    def step(self, detail: str = "", n: int = 1) -> None:
        if self.cancel():
            raise Cancelled(f"stopped while {self.label}")
        self.bar.step(detail, n)

    def done(self, summary: str = "") -> None:
        self.bar.done(summary)


class Progress:
    def __init__(self, total: int, label: str, stream=None, interval: float = 0.2):
        self.total = max(0, int(total))
        self.label = label
        self.stream = stream or sys.stdout
        self.interval = interval
        self.count = 0
        self.detail = ""
        self._last_draw = 0.0
        self._last_milestone = -1
        self._started = time.monotonic()
        self._open = False
        try:
            self.tty = bool(self.stream.isatty())
        except (AttributeError, ValueError):
            self.tty = False
        if self.total:
            self._draw(force=True)

    def step(self, detail: str = "", n: int = 1) -> None:
        self.count += n
        if detail:
            self.detail = detail
        self._draw()

    def _draw(self, force: bool = False) -> None:
        if not self.total:
            return
        now = time.monotonic()
        if self.tty:
            if not force and now - self._last_draw < self.interval and self.count < self.total:
                return
            self._last_draw = now
            width = 3 + len(str(self.total)) * 2
            line = f"{self.label}: {self.count}/{self.total}".ljust(len(self.label) + width)
            if self.detail:
                line += f"  {self.detail}"
            # Trim so a long game title cannot wrap and leave the previous
            # line's tail behind on the row above.
            self.stream.write("\r" + line[:110].ljust(110))
            self.stream.flush()
            self._open = True
        else:
            milestone = self.count * 10 // self.total
            if force or milestone != self._last_milestone:
                self._last_milestone = milestone
                self.stream.write(f"{self.label}: {self.count}/{self.total}\n")
                self.stream.flush()

    def done(self, summary: str = "") -> None:
        """Finish the line. `summary` replaces the count, so the terminal is
        left with what happened rather than with 750/750."""
        elapsed = time.monotonic() - self._started
        text = summary or f"{self.label}: {self.count}/{self.total}"
        if elapsed >= 2.0:
            text += f"  ({elapsed:.0f}s)"
        if self.tty and self._open:
            self.stream.write("\r" + text.ljust(110) + "\n")
        else:
            self.stream.write(text + "\n")
        self.stream.flush()
        self._open = False
