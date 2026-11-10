# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Mustapha Alioglou
# Copyright (C) 2026 Nicolas Vaughan <nivaca@fastmail.com>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Settings change when the config file does, without a restart.

Against a temporary config file: the user's own is never read or written.
"""

import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([sys.argv[0]])

import common  # noqa: E402
import quickview  # noqa: E402
import view_document  # noqa: E402


class Reload(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "quickview.conf")
        saved = dict(common.SETTINGS)
        self.addCleanup(lambda: (common.SETTINGS.clear(),
                                 common.SETTINGS.update(saved)))
        # An environment override would win over the file and hide a reload.
        for name in ("QUICKVIEW_PDF_MAX_PAGES", "QUICKVIEW_PANEL_THEME",
                     "QUICKVIEW_DISK_CACHE_MB"):
            if name in os.environ:
                value = os.environ.pop(name)
                self.addCleanup(os.environ.__setitem__, name, value)

    def write(self, text, atomically=False):
        if atomically:  # as editors that save by rename do
            tmp = self.path + ".new"
            with open(tmp, "w") as fh:
                fh.write(text)
            os.replace(tmp, self.path)
        else:
            with open(self.path, "w") as fh:
                fh.write(text)

    def wait_for(self, condition, timeout=3.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if condition():
                return True
            loop = QEventLoop()
            QTimer.singleShot(50, loop.quit)
            loop.exec()
        return condition()

    def test_every_module_sees_the_new_value(self):
        self.write("[preview]\npdf_max_pages = 7\n")
        before = common.SETTINGS
        changed = common.reload_settings(self.path)
        self.assertIn("pdf_max_pages", changed)
        self.assertIs(common.SETTINGS, before, "updated in place, not replaced")
        self.assertEqual(view_document.SETTINGS["pdf_max_pages"], 7)

    def test_nothing_changed_is_reported_as_nothing(self):
        self.write("[preview]\npdf_max_pages = 7\n")
        common.reload_settings(self.path)
        self.assertEqual(common.reload_settings(self.path), set())

    def test_a_malformed_file_falls_back_rather_than_failing(self):
        self.write("[preview\npdf_max_pages = lots\n")
        common.reload_settings(self.path)
        self.assertEqual(common.SETTINGS["pdf_max_pages"], 50)

    def test_the_daemon_picks_up_a_saved_file(self):
        self.write("[preview]\npdf_max_pages = 7\n")
        window = quickview.QuickView()
        self.addCleanup(window.deleteLater)
        window.watch_settings(self.path)
        self.write("[preview]\npdf_max_pages = 9\n")
        self.assertTrue(self.wait_for(
            lambda: common.SETTINGS["pdf_max_pages"] == 9))
        # And again after an editor replaces the file outright.
        self.write("[preview]\npdf_max_pages = 11\n", atomically=True)
        self.assertTrue(self.wait_for(
            lambda: common.SETTINGS["pdf_max_pages"] == 11))

    def test_an_edit_made_before_the_watch_began_is_not_missed(self):
        # The daemon loads SETTINGS at import and only starts watching once
        # its window exists; a save in between must still count.
        self.write("[preview]\npdf_max_pages = 7\n")
        common.reload_settings(self.path)
        window = quickview.QuickView()
        self.addCleanup(window.deleteLater)
        self.write("[preview]\npdf_max_pages = 13\n")  # no watch yet
        window.watch_settings(self.path)
        self.assertEqual(common.SETTINGS["pdf_max_pages"], 13)

    def test_a_new_panel_theme_applies_to_the_open_window(self):
        self.write("[appearance]\npanel_theme = quicklook\n")
        common.reload_settings(self.path)
        window = quickview.QuickView()
        self.addCleanup(window.deleteLater)
        lay = window.titlebar.layout()
        self.assertIs(lay.itemAt(0).widget(), window.titlebar.close_btn)

        window.watch_settings(self.path)
        self.write("[appearance]\npanel_theme = breeze\n")
        window.reload_settings()
        self.assertEqual(window.theme_name, "breeze")
        self.assertIs(lay.itemAt(lay.count() - 1).widget(),
                      window.titlebar.close_btn, "close button moves right")
        self.assertEqual(lay.count(), 5, "every button laid out exactly once")

    def test_turning_the_disk_cache_off_applies_at_once(self):
        self.write("[cache]\ndisk_cache_mb = 0\n")
        common.reload_settings(self.path)
        written = []
        saved = common.os.replace
        common.os.replace = lambda *a: written.append(a)
        try:
            common.cache_write("k", b"data")
        finally:
            common.os.replace = saved
        self.assertEqual(written, [])


if __name__ == "__main__":
    unittest.main()
