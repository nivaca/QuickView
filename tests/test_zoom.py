# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Nicolas Vaughan <nivaca@fastmail.com>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Zooming: the keys and Ctrl+wheel, on an image, a page view and text,
with stand-in workers the tests answer by hand."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QPoint, QPointF, QSize, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFontInfo, QImage, QPixmap, QWheelEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QPlainTextEdit, QWidget  # noqa: E402

_app = QApplication.instance() or QApplication([sys.argv[0]])

import common  # noqa: E402
import quickview  # noqa: E402
import renderers  # noqa: E402
import view_zoom  # noqa: E402


class FakeJob:
    made = []

    def __init__(self, pool, path, job, on_frame, on_done, parent=None, **_kw):
        self.path, self.job, self.on_frame, self.on_done = path, job, on_frame, on_done
        self.header = {"ok": True, "count": 1}
        self.cancelled = False
        FakeJob.made.append(self)

    def cancel(self):
        self.cancelled = True


def png(w, h, colour="white"):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(colour))
    buf = QBuffer()
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


class Base(unittest.TestCase):
    def setUp(self):
        FakeJob.made = []
        saved = view_zoom.SandboxJob
        view_zoom.SandboxJob = FakeJob
        self.addCleanup(setattr, view_zoom, "SandboxJob", saved)
        self.w = quickview.QuickView()
        self.addCleanup(self.w.deleteLater)
        self.w.resize(900, 900)
        self.w.current_path = "/x"
        self.w.show()
        self.w.activateWindow()
        QApplication.processEvents()

    def key(self, key, mods=Qt.ControlModifier):
        QTest.keyClick(self.w, key, mods)

    def wheel(self, widget, dy, mods=Qt.ControlModifier):
        pos = QPointF(widget.width() / 2, widget.height() / 2)
        event = QWheelEvent(pos, QPointF(widget.mapToGlobal(pos.toPoint())),
                            QPoint(0, 0), QPoint(0, dy), Qt.NoButton, mods,
                            Qt.ScrollPhase.NoScrollPhase, False)
        QApplication.sendEvent(widget, event)


class Steps(unittest.TestCase):
    def test_up_and_down_the_steps(self):
        self.assertEqual(view_zoom.next_zoom(1.0, 1), 1.1)
        self.assertEqual(view_zoom.next_zoom(1.0, -1), 0.9)
        self.assertEqual(view_zoom.next_zoom(1.05, 1), 1.1)
        self.assertEqual(view_zoom.next_zoom(4.0, 1), 4.0, "the top is the top")
        self.assertEqual(view_zoom.next_zoom(0.25, -1), 0.25)


class Image(Base):
    def show(self, dims="4000×2000"):
        pix = QPixmap(200, 100)
        pix.fill(QColor("red"))
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        # The disk cache is keyed by the file's stat, so it has to exist;
        # the stand-in worker never reads it.
        path = os.path.join(tmp.name, "x.png")
        open(path, "wb").close()
        saved = common.CACHE_DIR
        common.CACHE_DIR = tmp.name  # never the user's own cache
        self.addCleanup(setattr, common, "CACHE_DIR", saved)
        self.w._display_image(path, pix, dims, hires=True)
        self.label = self.w._image_zoom["label"]

    def test_the_keys_grow_shrink_and_reset(self):
        self.show()
        self.key(Qt.Key_Equal)
        self.assertEqual(self.label.size(), QSize(220, 110))
        self.key(Qt.Key_Minus)
        self.key(Qt.Key_Minus)
        self.assertEqual(self.label.size(), QSize(180, 90))
        self.key(Qt.Key_0)
        self.assertEqual(self.label.size(), QSize(200, 100))

    def test_ctrl_plus_and_the_keypad(self):
        self.show()
        self.key(Qt.Key_Plus)
        self.assertAlmostEqual(self.w._zoom, 1.1)
        self.key(Qt.Key_Plus, Qt.ControlModifier | Qt.KeypadModifier)
        self.assertAlmostEqual(self.w._zoom, 1.25)
        self.key(Qt.Key_0, Qt.ControlModifier | Qt.KeypadModifier)
        self.assertAlmostEqual(self.w._zoom, 1.0)

    def test_ctrl_wheel_zooms_and_a_plain_wheel_does_not(self):
        self.show()
        self.wheel(self.label, 120)
        self.assertAlmostEqual(self.w._zoom, 1.1)
        self.wheel(self.label, -240)  # two notches: 110% -> 100% -> 90%
        self.assertAlmostEqual(self.w._zoom, 0.9)
        self.wheel(self.label, 120, Qt.NoModifier)
        self.assertAlmostEqual(self.w._zoom, 0.9)

    def test_a_touchpad_adds_up_to_a_notch(self):
        self.show()
        for _ in range(3):
            self.wheel(self.label, 40)
        self.assertAlmostEqual(self.w._zoom, 1.1)

    def test_zoomed_in_it_is_decoded_again_at_the_new_size(self):
        self.show()
        self.w._zoom_to(2.0, None)
        self.w._hires_now()
        job = FakeJob.made[-1]
        self.assertEqual((job.job["op"], job.job["max_w"], job.job["max_h"]),
                         ("image", 400, 200))
        img = QImage(400, 200, QImage.Format.Format_RGB32)
        img.fill(QColor("blue"))
        raw, geom = renderers.raw_frame(img)
        job.header.update(geom)
        job.on_frame(raw)
        self.assertEqual(self.label.pixmap().size(), QSize(400, 200))
        self.assertEqual(self.label.size(), QSize(400, 200))

    def test_never_past_the_original(self):
        self.show(dims="300×150")
        self.w._zoom_to(4.0, None)
        self.w._hires_now()
        job = FakeJob.made[-1]
        self.assertEqual((job.job["max_w"], job.job["max_h"]), (300, 150))

    def test_an_image_already_at_full_size_asks_for_nothing(self):
        self.show(dims="200×100")
        self.w._zoom_to(2.0, None)
        self.w._hires_now()
        self.assertEqual(FakeJob.made, [])

    def test_a_new_file_starts_at_100(self):
        self.show()
        self.key(Qt.Key_Equal)
        self.w.show_file("/nonexistent/file.png")
        self.assertEqual(self.w._zoom, 1.0)


class Pages(Base):
    def setUp(self):
        super().setUp()
        self.w._page_scale = 1.0
        self.w._pdf_begin_view("/x.pdf", 2, [(200, 100), (200, 100)],
                               op="pdf", page_w=200)
        for i in range(2):
            self.w._pdf_fill_page(i, QImage.fromData(png(200, 100)))
        self.w.show()
        QApplication.processEvents()
        self.labels = self.w._pdf_labels

    def test_pages_and_their_overlays_scale(self):
        self.w._zoom_to(2.0, None)
        self.assertEqual(self.labels[0].size(), QSize(400, 200))
        self.assertEqual(self.w._pdf_overlays[0].size(), QSize(400, 200))
        self.assertEqual(view_zoom.label_zoom(self.labels[0]), 2.0)

    def test_the_mouse_is_mapped_back_to_page_pixels(self):
        self.w._zoom_to(2.0, None)
        QApplication.processEvents()  # the column lays the pages out again
        gpos = self.labels[1].mapToGlobal(QPoint(130, 30))
        self.assertEqual(self.w._page_at(gpos), (1, 65, 15))

    def test_the_pages_on_screen_are_rendered_sharper(self):
        self.w._zoom_to(2.0, None)
        self.w._hires_now()
        job = FakeJob.made[-1]
        self.assertEqual((job.job["op"], job.job["scale"], job.job["start"]),
                         ("pdf", 2.0, 0))
        job.on_frame(png(400, 200, "blue"))
        label = self.labels[0]
        self.assertEqual(label.pixmap().size(), QSize(400, 200))
        self.assertEqual(label.property("qv_hires"), 2.0)
        # Back at 100%, the page returns to its own pixels.
        self.w._zoom_to(1.0, None)
        self.w._hires_now()
        self.assertEqual(label.pixmap().size(), QSize(200, 100))
        self.assertIsNone(label.property("qv_hires"))

    def test_a_late_page_lands_at_the_zoom(self):
        self.w._zoom_to(2.0, None)
        self.w._pdf_fill_page(1, QImage.fromData(png(200, 120)))
        self.assertEqual(self.labels[1].size(), QSize(400, 240))
        self.assertEqual(self.w.page_base(self.labels[1]), QSize(200, 120))

    def test_ctrl_wheel_on_a_page(self):
        self.wheel(self.labels[0], 120)
        self.assertAlmostEqual(self.w._zoom, 1.1)

    def test_an_office_rebuild_of_the_same_file_keeps_the_zoom(self):
        self.w._zoom_to(1.5, None)
        self.w._pdf_begin_view("/x.pdf", 1, [(200, 100)], op="office", page_w=200)
        self.assertEqual(self.w._pdf_labels[0].size(), QSize(300, 150))


class Text(Base):
    def test_the_font_grows_and_returns(self):
        self.w._show_text_widget("hello")
        edit = self.w.content.currentWidget()
        self.assertIsInstance(edit, QPlainTextEdit)
        edit.ensurePolished()
        before = QFontInfo(edit.font()).pixelSize()
        self.w._zoom_to(2.0, None)
        edit.ensurePolished()
        self.assertEqual(QFontInfo(edit.font()).pixelSize(), before * 2)
        self.w.zoom_reset()
        edit.ensurePolished()
        self.assertEqual(QFontInfo(edit.font()).pixelSize(), before)

    def test_ctrl_wheel_does_not_reach_the_text_box(self):
        self.w._show_text_widget("hello")
        edit = self.w.content.currentWidget()
        self.wheel(edit.viewport(), 120)
        self.assertAlmostEqual(self.w._zoom, 1.1, "the window's zoom, not the box's own")

    def test_a_web_page_uses_its_own_zoom(self):
        # A stand-in for QWebEngineView, which cannot start without a
        # display: anything with setZoomFactor() is zoomed through it.
        class Web(QWidget):
            factor = 1.0

            def setZoomFactor(self, factor):
                self.factor = factor

        self.w._clear_widgets()
        web = Web()
        self.w.content.addWidget(web)
        self.w._zoom_to(1.5, None)
        self.assertEqual(web.factor, 1.5)
        self.w.zoom_reset()
        self.assertEqual(web.factor, 1.0)

    def test_a_message_does_not_zoom(self):
        self.w.show_message("Nothing to see")
        self.key(Qt.Key_Equal)
        self.assertEqual(self.w._zoom, 1.0)
        self.assertIsNone(self.w._zoom_toast)


if __name__ == "__main__":
    unittest.main()
