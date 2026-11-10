# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Mustapha Alioglou
# Copyright (C) 2026 Nicolas Vaughan <nivaca@fastmail.com>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""A worker's late answer never lands on the wrong preview.

Workers answer asynchronously. By the time one does, the user may have
pressed → or opened another file, and painting the old answer then would
show one file's contents under another's name.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPlainTextEdit  # noqa: E402

_app = QApplication.instance() or QApplication([sys.argv[0]])

import quickview  # noqa: E402
import view_text  # noqa: E402


class FakeJob:
    """Stands in for SandboxJob: records the callbacks, runs nothing."""
    made = []

    def __init__(self, pool, path, job, on_frame, on_done, parent=None, **_kw):
        self.path, self.on_frame, self.on_done = path, on_frame, on_done
        self.header = {}
        FakeJob.made.append(self)

    def cancel(self):
        pass


class StaleAnswers(unittest.TestCase):
    def setUp(self):
        FakeJob.made = []
        saved = view_text.SandboxJob
        view_text.SandboxJob = FakeJob
        self.addCleanup(setattr, view_text, "SandboxJob", saved)
        self.window = quickview.QuickView()
        self.addCleanup(self.window.deleteLater)

    def shown_text(self):
        edits = self.window.findChildren(QPlainTextEdit)
        return [e.toPlainText() for e in edits]

    def answer(self, job, text):
        job.on_frame(json.dumps({"text": text}).encode())
        job.on_done(True, "")

    def preview(self, path):
        self.window.current_path = path
        self.window.show_text(path)
        return FakeJob.made[-1]

    def test_the_current_answer_is_shown(self):
        job = self.preview("/a.txt")
        self.answer(job, "contents of a")
        self.assertIn("contents of a", self.shown_text())

    def test_an_answer_for_a_file_left_behind_is_dropped(self):
        old = self.preview("/a.txt")
        self.window.current_path = "/b.txt"  # the user pressed →
        self.answer(old, "contents of a")
        self.assertNotIn("contents of a", self.shown_text())

    def test_an_answer_from_a_replaced_job_is_dropped(self):
        # Same file, opened again: the first job's answer is still stale.
        old = self.preview("/a.txt")
        new = self.preview("/a.txt")
        self.answer(old, "first render")
        self.assertNotIn("first render", self.shown_text())
        self.answer(new, "second render")
        self.assertIn("second render", self.shown_text())

    def test_no_job_is_never_current(self):
        self.window.current_path = "/a.txt"
        self.window._render_job = None
        self.assertFalse(self.window._is_current(None, "/a.txt"))


if __name__ == "__main__":
    unittest.main()
