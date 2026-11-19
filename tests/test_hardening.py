# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Nicolas Vaughan <nicolasvaughan@proton.me>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""What the daemon refuses to do with what an untrusted file, a worker or
the disk cache hands it, and files that are not what their names say.
"""

import os
import signal
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([sys.argv[0]])

import common  # noqa: E402
import quickview  # noqa: E402
import sandbox  # noqa: E402

# The smallest PDF QtPdf's image plugin renders: if the daemon's decoder
# were chosen by sniffing, this would come back as a picture.
TINY_PDF = (b"%PDF-1.1\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 20 20]>>endobj\n"
            b"trailer<</Root 1 0 R>>\n%%EOF\n")
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="9" height="9"/>'


def encoded(fmt: str) -> bytes:
    img = QImage(8, 4, QImage.Format.Format_RGB32)
    img.fill(QColor("green"))
    buf = QBuffer()
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    img.save(buf, fmt)
    return bytes(buf.data())


class DecodeFrame(unittest.TestCase):
    def test_png_and_jpeg_decode(self):
        for fmt in ("PNG", "JPEG"):
            with self.subTest(fmt=fmt):
                self.assertEqual(common.decode_frame(encoded(fmt)).width(), 8)

    def test_nothing_else_reaches_a_decoder(self):
        for name, data in (("pdf", TINY_PDF), ("svg", SVG), ("bmp", encoded("BMP")),
                           ("empty", b""), ("none", None)):
            with self.subTest(name):
                self.assertTrue(common.decode_frame(data).isNull())

    def test_a_png_header_on_something_else_fails_as_png(self):
        self.assertTrue(common.decode_frame(b"\x89PNG" + TINY_PDF).isNull())


class NotARegularFile(unittest.TestCase):
    """A named pipe opened for reading waits for a writer: on the GUI
    thread, that froze the daemon for good."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        # A hang fails the test instead of the whole suite.
        signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(
            AssertionError("blocked on a FIFO")))
        signal.alarm(10)
        self.addCleanup(signal.alarm, 0)

    def fifo(self, name):
        path = os.path.join(self.dir, name)
        os.mkfifo(path)
        return path

    def test_a_fifo_named_like_a_document_gets_the_card(self):
        w = quickview.QuickView()
        self.addCleanup(w.deleteLater)
        for name in ("a.zip", "a.txt", "a.md", "a.pdf", "a.psd"):
            with self.subTest(name):
                w.show_files([self.fifo(name)])
                self.assertIsNone(w._render_job)
                self.assertEqual(w._preview_jobs, [])

    def test_the_sandbox_refuses_one_without_blocking(self):
        with self.assertRaises(OSError):
            sandbox.open_regular(self.fifo("b.png"))

    def test_a_regular_file_opens_blocking(self):
        path = os.path.join(self.dir, "c.txt")
        with open(path, "w") as fh:
            fh.write("x")
        fd = sandbox.open_regular(path)
        self.addCleanup(os.close, fd)
        self.assertTrue(os.get_blocking(fd))

    def test_the_ai_sniff_does_not_open_a_fifo(self):
        w = quickview.QuickView()
        self.addCleanup(w.deleteLater)
        self.assertFalse(w.is_pdf(self.fifo("d.ai")))


class NotUtf8(unittest.TestCase):
    def test_a_latin1_name_is_previewed(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        raw = os.path.join(os.fsencode(tmp.name), b"caf\xe9.txt")
        with open(raw, "wb") as fh:
            fh.write(b"hello")
        path = os.fsdecode(raw)  # what ipc.decode_request hands on
        st = os.stat(path)
        self.assertNotEqual(common.cache_key(path, st, 1, 1),
                            common.cache_key(path.replace("\udce9", "e"), st, 1, 1))
        w = quickview.QuickView()
        self.addCleanup(w.deleteLater)
        w.show_files([path])  # raised UnicodeEncodeError before
        self.assertEqual(w.current_path, path)


if __name__ == "__main__":
    unittest.main()
