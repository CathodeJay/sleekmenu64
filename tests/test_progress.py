# SPDX-License-Identifier: AGPL-3.0-only
"""The progress line, and the stop it answers."""

import io
import unittest

from tools import progress


class ProgressTests(unittest.TestCase):
    def test_off_a_terminal_it_prints_a_line_at_each_tenth(self):
        out = io.StringIO()
        bar = progress.Progress(100, "scanning", stream=out)
        for _ in range(100):
            bar.step()
        bar.done("scanned 100")
        lines = out.getvalue().splitlines()
        self.assertEqual(lines[0], "scanning: 0/100")
        self.assertIn("scanning: 50/100", lines)
        self.assertEqual(lines[-1], "scanned 100")
        self.assertLess(len(lines), 15)


class StoppableTests(unittest.TestCase):
    def test_a_stop_is_answered_at_the_next_step_and_names_the_pass(self):
        steps = []

        class Bar:
            def __init__(self, total, label):
                self.total, self.label = total, label

            def step(self, detail="", n=1):
                steps.append(detail)

            def done(self, summary=""):
                steps.append(("done", summary))

        stopping = []
        factory = progress.stoppable(Bar, cancel=lambda: bool(stopping))
        bar = factory(3, "converting")
        bar.step("one")
        stopping.append(True)
        with self.assertRaises(progress.Cancelled) as caught:
            bar.step("two")
        self.assertEqual(str(caught.exception), "stopped while converting")
        self.assertEqual(steps, ["one"], "the step that was refused never counted")
        bar.done("still allowed")
        self.assertEqual(steps[-1], ("done", "still allowed"))

    def test_without_a_stop_it_is_the_bar_it_wraps(self):
        out = io.StringIO()
        factory = progress.stoppable(lambda total, label: progress.Progress(total, label, stream=out),
                                     cancel=lambda: False)
        bar = factory(2, "packing")
        bar.step()
        bar.step()
        bar.done()
        self.assertIn("packing: 2/2", out.getvalue())


if __name__ == "__main__":
    unittest.main()
