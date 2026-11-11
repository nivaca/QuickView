# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Mustapha Alioglou
# Copyright (C) 2026 Nicolas Vaughan <nivaca@fastmail.com>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Office documents show the quick layout first, then LibreOffice's.

The worker is a stand-in that records each job, so these check the
daemon's decisions: what runs, in which order, and what is shown when.
The disk cache is a temporary directory.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([sys.argv[0]])

import common  # noqa: E402
import quickview  # noqa: E402
import view_document  # noqa: E402
import view_office  # noqa: E402

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def page_png(total: int) -> bytes:
    img = QImage(40, 60, QImage.Format_RGB32)
    img.fill(0xFFFFFF)
    img.setText("QuickView:PageCount", str(total))
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


class FakeJob:
    made = []

    def __init__(self, pool, path, job, on_frame, on_done, parent=None, **_kw):
        self.path, self.job = path, job
        self.on_frame, self.on_done = on_frame, on_done
        self.header = {"ok": True, "count": 2, "kind": "pages"}
        self.cancelled = False
        FakeJob.made.append(self)

    def cancel(self):
        self.cancelled = True

    def finish(self, pages=2, ok=True):
        for _ in range(pages):
            self.on_frame(page_png(pages))
        self.on_done(ok, "" if ok else "soffice failed")


class Upgrade(unittest.TestCase):
    def setUp(self):
        FakeJob.made = []
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for module, name, value in (
            (view_document, "SandboxJob", FakeJob),
            (view_office, "office_suite", lambda: "/usr/bin/soffice"),
            (common, "CACHE_DIR", tmp.name),
        ):
            saved = getattr(module, name)
            setattr(module, name, value)
            self.addCleanup(setattr, module, name, saved)
        saved = common.SETTINGS["office_engine"]
        common.SETTINGS["office_engine"] = "libreoffice"
        self.addCleanup(common.SETTINGS.__setitem__, "office_engine", saved)

        self.path = os.path.join(tmp.name, "memo.docx")
        with open(self.path, "wb") as fh:
            fh.write(b"PK stand-in; the worker is fake")
        self.window = quickview.QuickView()
        self.addCleanup(self.window.deleteLater)
        # Cleanups run last-first: the page stepper and any job stop before
        # the stand-in worker is swapped back for the real one.
        self.addCleanup(self.window.clear_content)

    def open(self, mime=DOCX):
        self.window.current_path = self.path
        self.window.clear_content()
        self.window.show_office(self.path, mime)

    def engines(self):
        return [j.job.get("engine") for j in FakeJob.made]

    def test_the_quick_layout_comes_first_and_libreoffice_alongside(self):
        self.open()
        self.assertEqual(self.engines(), ["builtin", "libreoffice"])
        quick, slow = FakeJob.made
        self.assertIs(self.window._render_job, quick, "the quick one is shown")
        self.assertIn(slow, self.window._preview_jobs)

    def test_libreoffice_pages_replace_the_quick_ones_when_ready(self):
        self.open()
        quick, slow = FakeJob.made
        quick.finish(pages=3)  # the layouts paginate differently,
        self.assertEqual(len(self.window._pdf_labels), 3)
        slow.finish(pages=2)   # which tells them apart on screen
        # Reopened from the cache, as LibreOffice's pages — no third job.
        self.assertEqual(len(FakeJob.made), 2)
        page_w, scale = self.window.page_geometry()
        st = os.stat(self.path)
        lo = self.window.office_page_key(self.path, st, page_w, scale, "lo")
        self.assertTrue(self.window.pages_cached(lo))
        self.assertEqual(len(self.window._pdf_labels), 2)

    def test_moving_on_cancels_the_upgrade(self):
        self.open()
        slow = FakeJob.made[1]
        self.window.current_path = "/elsewhere.txt"
        self.window.clear_content()
        self.assertTrue(slow.cancelled)
        self.assertEqual(self.window._preview_jobs, [])

    def test_a_failed_upgrade_leaves_the_quick_layout(self):
        self.open()
        quick, slow = FakeJob.made
        quick.finish()
        shown = list(self.window._pdf_labels)
        slow.finish(pages=0, ok=False)
        self.assertEqual(self.window._pdf_labels, shown)

    def test_cached_libreoffice_pages_open_directly(self):
        self.open()
        FakeJob.made[1].finish()
        FakeJob.made = []
        self.open()
        self.assertEqual(FakeJob.made, [], "straight from the cache")

    def test_no_upgrade_when_libreoffice_is_turned_off(self):
        common.SETTINGS["office_engine"] = "builtin"
        self.open()
        self.assertEqual(self.engines(), ["builtin"])

    def test_no_upgrade_for_a_deck(self):
        # A deck's built-in answer is a thumbnail, not pages: nothing to
        # show first, so it waits for LibreOffice as before.
        self.open(PPTX)
        self.assertEqual(self.engines(), ["libreoffice"])
        self.assertEqual(self.window._preview_jobs, [])


if __name__ == "__main__":
    unittest.main()
