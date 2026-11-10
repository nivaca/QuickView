# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Mustapha Alioglou
# Copyright (C) 2026 Nicolas Vaughan <nivaca@fastmail.com>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""A job that fails before reaching its worker still reports back.

The file can vanish, or lose its read permission, between being selected
and being previewed. The error is delivered from a zero-delay timer, after
the `except` block has ended — and Python unbinds `except ... as exc` at the
end of that block, so a callback that read `exc` lazily raised NameError and
`on_done` never fired, leaving the panel waiting on a preview that was never
coming.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

import sandbox


class _FakeWorker:
    sock = None

    def __init__(self):
        self.killed = False

    def kill(self):
        self.killed = True


class _FakePool:
    def __init__(self):
        self.worker = _FakeWorker()

    def take(self):
        return self.worker


class EarlyFailure(unittest.TestCase):
    def test_an_unopenable_file_reports_its_error(self):
        pool = _FakePool()
        done = []
        loop = QEventLoop()

        def on_done(ok, error):
            done.append((ok, error))
            loop.quit()

        sandbox.SandboxJob(
            pool, "/nonexistent/quickview-test.pdf", {"op": "image"},
            lambda payload: None, on_done,
        )
        QTimer.singleShot(2000, loop.quit)  # a hang fails, not wedges, the suite
        loop.exec()

        self.assertEqual(len(done), 1)
        ok, error = done[0]
        self.assertFalse(ok)
        self.assertIn("No such file", error)
        self.assertTrue(pool.worker.killed)


if __name__ == "__main__":
    unittest.main()
