# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Nicolas Vaughan <nivaca@fastmail.com>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Selecting and copying a PDF's text with the mouse, in the window.

A two-page view with a stand-in worker the test answers by hand, and real
mouse and key events.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([sys.argv[0]])

import quickview  # noqa: E402
import view_selection  # noqa: E402

# Each page: "alpha beta" over "gamma".
WORDS = [[0, 5, 10, 10, 40, 10, 0], [6, 10, 60, 10, 30, 10, 0],
         [11, 16, 10, 30, 50, 10, 1]]


def spin(ms=20):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class FakeJob:
    made = []

    def __init__(self, pool, path, job, on_frame, on_done, parent=None, **_kw):
        self.job, self.on_frame, self.on_done = job, on_frame, on_done
        self.cancelled = False
        FakeJob.made.append(self)

    def cancel(self):
        self.cancelled = True

    def answer(self):
        pages = [{"page": p, "text": f"alpha beta\ngamma{p}",
                  "words": WORDS[:2] + [[11, 17, 10, 30, 50, 10, 1]]}
                 for p in self.job["pages"]]
        self.on_frame(json.dumps({"pages": pages, "engine": "poppler"}).encode())
        self.on_done(True, "")


class Selection(unittest.TestCase):
    def setUp(self):
        FakeJob.made = []
        saved = view_selection.SandboxJob
        view_selection.SandboxJob = FakeJob
        self.addCleanup(setattr, view_selection, "SandboxJob", saved)
        QGuiApplication.clipboard().setText("before")
        self.w = quickview.QuickView()
        self.addCleanup(self.w.deleteLater)
        self.w.resize(800, 900)
        self.w._page_scale = 1.0
        self.w._pdf_begin_view("/x.pdf", 2, [(200, 100), (200, 100)],
                               op="pdf", page_w=200)
        self.w.show()
        spin()
        self.labels = self.w._pdf_labels

    def drag(self, page_from, at_from, page_to, at_to, answer=True):
        QTest.mousePress(self.labels[page_from], Qt.LeftButton, Qt.NoModifier,
                         QPoint(*at_from))
        if answer and FakeJob.made and not FakeJob.made[-1].cancelled:
            FakeJob.made[-1].answer()
        target = self.labels[page_to]
        QTest.mouseMove(target, QPoint(*at_to))
        # The drag continues on the label the press grabbed.
        gpos = target.mapToGlobal(QPoint(*at_to))
        self.w._sel_on_move(gpos)
        while FakeJob.made and FakeJob.made[-1].job["pages"] and \
                not getattr(FakeJob.made[-1], "done", False) and answer:
            job = FakeJob.made[-1]
            job.done = True
            if any(p not in self.w._sel_layers for p in job.job["pages"]):
                job.answer()
        QTest.mouseRelease(self.labels[page_from], Qt.LeftButton, Qt.NoModifier,
                           self.labels[page_from].mapFromGlobal(gpos))

    def copy(self):
        QTest.keyClick(self.w, Qt.Key_C, Qt.ControlModifier)
        return QGuiApplication.clipboard().text()

    def test_a_press_asks_the_jail_for_that_page_only(self):
        QTest.mousePress(self.labels[1], Qt.LeftButton, Qt.NoModifier, QPoint(20, 15))
        self.assertEqual(FakeJob.made[0].job["op"], "pdftext")
        self.assertEqual(FakeJob.made[0].job["pages"], [1])

    def test_a_drag_selects_and_ctrl_c_copies(self):
        self.drag(0, (15, 15), 0, (70, 35))
        self.assertEqual(self.copy(), "alpha beta\ngamma0")
        self.assertEqual(len(self.w._sel_overlays[0]._rects), 2, "one band per line")

    def test_a_drag_across_pages(self):
        self.drag(0, (65, 35), 1, (65, 15))
        self.assertEqual(self.copy(), "gamma0\nalpha beta")

    def test_a_plain_click_clears(self):
        self.drag(0, (15, 15), 0, (70, 35))
        QTest.mouseClick(self.labels[0], Qt.LeftButton, Qt.NoModifier, QPoint(15, 15))
        self.assertIsNone(self.w._sel)
        self.assertEqual(self.copy(), "before", "nothing to copy")

    def test_text_arriving_after_a_click_does_not_select(self):
        QTest.mouseClick(self.labels[0], Qt.LeftButton, Qt.NoModifier, QPoint(15, 15))
        FakeJob.made[0].answer()  # late: the click is over
        self.assertIsNone(self.w._sel)

    def test_double_click_selects_a_word(self):
        self.drag(0, (15, 15), 0, (16, 15))  # loads the page's text
        QTest.mouseDClick(self.labels[0], Qt.LeftButton, Qt.NoModifier, QPoint(65, 15))
        QTest.mouseRelease(self.labels[0], Qt.LeftButton, Qt.NoModifier, QPoint(65, 15))
        self.assertEqual(self.copy(), "beta")

    def test_ctrl_a_selects_every_page_in_one_job(self):
        QTest.keyClick(self.w, Qt.Key_A, Qt.ControlModifier)
        self.assertEqual(FakeJob.made[-1].job["pages"], [0, 1])
        FakeJob.made[-1].answer()
        self.assertEqual(self.copy(), "alpha beta\ngamma0\nalpha beta\ngamma1")

    def test_the_pages_show_a_text_cursor(self):
        self.assertEqual(self.labels[0].cursor().shape(), Qt.IBeamCursor)

    def test_leaving_the_document_drops_its_text_and_job(self):
        QTest.mousePress(self.labels[0], Qt.LeftButton, Qt.NoModifier, QPoint(20, 15))
        job = FakeJob.made[0]
        self.w.clear_content()
        self.assertTrue(job.cancelled)
        self.assertIsNone(self.w._sel_path)
        self.assertEqual(self.copy(), "before")


class NotAPdf(unittest.TestCase):
    def test_keys_do_nothing_without_a_pdf(self):
        w = quickview.QuickView()
        self.addCleanup(w.deleteLater)
        QGuiApplication.clipboard().setText("kept")
        QTest.keyClick(w, Qt.Key_C, Qt.ControlModifier)
        QTest.keyClick(w, Qt.Key_A, Qt.ControlModifier)
        self.assertEqual(QGuiApplication.clipboard().text(), "kept")

    def test_an_office_page_view_is_not_selectable(self):
        w = quickview.QuickView()
        self.addCleanup(w.deleteLater)
        w._page_scale = 1.0
        w._pdf_begin_view("/x.docx", 1, [(200, 100)], op="office", page_w=200)
        self.assertIsNone(w._sel_path)


if __name__ == "__main__":
    unittest.main()
