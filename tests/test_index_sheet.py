# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Nicolas Vaughan <nicolasvaughan@proton.me>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""The index sheet of a multi-file selection: the thumbnails, where they
come from, and getting in and out of it. A stand-in thumbnail cache and
worker; never the user's own cache.
"""

import hashlib
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QUrl  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([sys.argv[0]])

import quickview  # noqa: E402
import renderers  # noqa: E402
import view_index  # noqa: E402


class FakeJob:
    made = []

    def __init__(self, pool, path, job, on_frame, on_done, parent=None, **_kw):
        self.path, self.job, self.on_frame, self.on_done = path, job, on_frame, on_done
        self.header = {}
        self.cancelled = False
        FakeJob.made.append(self)

    def cancel(self):
        self.cancelled = True

    def answer(self, w=40, h=20):
        img = QImage(w, h, QImage.Format.Format_ARGB32)
        img.fill(QColor("red"))
        raw, geom = renderers.raw_frame(img)
        self.header.update(geom)
        self.on_frame(raw)
        self.on_done(True, "")


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        saved_env = os.environ.get("XDG_CACHE_HOME")
        os.environ["XDG_CACHE_HOME"] = os.path.join(self.dir, "cache")
        self.addCleanup(lambda: os.environ.__setitem__("XDG_CACHE_HOME", saved_env)
                        if saved_env is not None else os.environ.pop("XDG_CACHE_HOME", None))
        FakeJob.made = []
        saved = view_index.SandboxJob
        view_index.SandboxJob = FakeJob
        self.addCleanup(setattr, view_index, "SandboxJob", saved)

    def file(self, name, data=b"x"):
        path = os.path.join(self.dir, name)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def thumb(self, path, mtime=None, size="large", colour="blue"):
        uri = QUrl.fromLocalFile(path).toString(QUrl.ComponentFormattingOption.FullyEncoded)
        where = os.path.join(view_index.thumbnail_dir(), size)
        os.makedirs(where, exist_ok=True)
        img = QImage(64, 32, QImage.Format.Format_ARGB32)
        img.fill(QColor(colour))
        img.setText("Thumb::URI", uri)
        img.setText("Thumb::MTime", str(int(os.stat(path).st_mtime) if mtime is None else mtime))
        out = os.path.join(where, hashlib.md5(uri.encode()).hexdigest() + ".png")
        img.save(out, "PNG")
        return out


class Cache(Base):
    def test_a_current_thumbnail_is_used(self):
        path = self.file("a b é.pdf")
        self.thumb(path)
        self.assertEqual(view_index.cached_thumbnail(path).size().width(), 64)

    def test_a_thumbnail_of_an_older_file_is_not(self):
        path = self.file("a.pdf")
        self.thumb(path, mtime=1)
        self.assertTrue(view_index.cached_thumbnail(path).isNull())

    def test_only_png_is_decoded(self):
        path = self.file("a.pdf")
        out = self.thumb(path)
        with open(out, "wb") as fh:
            fh.write(b"%PDF-1.4 not a png")
        self.assertTrue(view_index.cached_thumbnail(path).isNull())

    def test_none_at_all(self):
        self.assertTrue(view_index.cached_thumbnail(self.file("a.pdf")).isNull())


class Sheet(Base):
    def setUp(self):
        super().setUp()
        self.w = quickview.QuickView()
        self.addCleanup(self.w.deleteLater)
        self.w.resize(900, 700)
        self.paths = [self.file("one.png"), self.file("two.txt", b"text"),
                      self.file("three.png")]
        self.thumb(self.paths[0])
        self.w.show_files(self.paths, 1)
        QApplication.processEvents()

    def test_the_button_shows_for_a_selection_only(self):
        self.assertTrue(self.w.titlebar.index_btn.isVisibleTo(self.w))
        self.w.show_files([self.paths[0]])
        self.assertFalse(self.w.titlebar.index_btn.isVisibleTo(self.w))

    def test_ctrl_enter_shows_every_file_on_the_current_one(self):
        QTest.keyClick(self.w, Qt.Key_Return, Qt.ControlModifier)
        grid = self.w._index_view
        self.assertIsNotNone(grid)
        self.assertEqual([grid.item(i).text() for i in range(grid.count())],
                         ["one.png", "two.txt", "three.png"])
        self.assertEqual(grid.currentRow(), 1)
        self.assertTrue(self.w.titlebar.index_btn.isChecked())
        self.assertEqual(self.w.titlebar.title.text(), "3 items")

    def test_thumbnails_from_the_cache_then_the_jail(self):
        self.w.toggle_index_sheet()
        grid = self.w._index_view
        self.assertFalse(grid.item(0).icon().isNull(), "from the cache")
        self.assertEqual([j.path for j in FakeJob.made], [self.paths[2]],
                         "one image, not the text file, not the cached one")
        self.assertEqual(FakeJob.made[0].job["op"], "image")
        FakeJob.made[0].answer()
        self.assertEqual(grid.item(2).icon().availableSizes()[0].width(), 40)

    def test_the_arrows_and_enter_belong_to_the_grid_then_come_back(self):
        self.w.toggle_index_sheet()
        keys = {sc.key()[0].key(): sc.isEnabled() for sc in self.w._nav_shortcuts}
        self.assertFalse(keys[Qt.Key_Left] or keys[Qt.Key_Return])
        self.assertTrue(keys[Qt.Key_Space] and keys[Qt.Key_Escape])
        grid = self.w._index_view
        grid.itemActivated.emit(grid.item(2))
        self.assertIsNone(self.w._index_view)
        self.assertEqual((self.w.sel_index, self.w.current_path), (2, self.paths[2]))
        self.assertTrue(all(sc.isEnabled() for sc in self.w._nav_shortcuts))
        self.assertFalse(self.w.titlebar.index_btn.isChecked())

    def test_toggling_again_goes_back_and_stops_the_thumbnails(self):
        self.w.toggle_index_sheet()
        job = FakeJob.made[0]
        self.w.toggle_index_sheet()
        self.assertIsNone(self.w._index_view)
        self.assertEqual(self.w.current_path, self.paths[1])
        self.assertTrue(job.cancelled)

    def test_one_file_has_no_sheet(self):
        self.w.show_files([self.paths[0]])
        self.w.toggle_index_sheet()
        self.assertIsNone(self.w._index_view)


if __name__ == "__main__":
    unittest.main()
