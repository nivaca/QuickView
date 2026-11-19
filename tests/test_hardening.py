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
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([sys.argv[0]])

import common  # noqa: E402

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


if __name__ == "__main__":
    unittest.main()
