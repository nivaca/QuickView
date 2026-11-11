# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Mustapha Alioglou
# Copyright (C) 2026 Nicolas Vaughan <nivaca@fastmail.com>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""← → neighbours are warmed in the background: images, PDFs, documents.

Real files in a temporary folder (the routing reads their contents), a
stand-in worker that records each job, and a temporary disk cache.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([sys.argv[0]])

import common  # noqa: E402
import quickview  # noqa: E402
import view_document  # noqa: E402
import view_image  # noqa: E402
import view_office  # noqa: E402
import samplepdf  # noqa: E402
import test_office  # noqa: E402
from test_office_upgrade import FakeJob  # noqa: E402


class Prefetch(unittest.TestCase):
    def setUp(self):
        FakeJob.made = []
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = os.path.join(tmp.name, "folder")
        os.makedirs(self.dir)
        cache = os.path.join(tmp.name, "cache")
        self.suite = "/usr/bin/soffice"
        for module, name, value in (
            (view_document, "SandboxJob", FakeJob),
            (view_image, "SandboxJob", FakeJob),
            (view_office, "office_suite", lambda: self.suite),
            (common, "CACHE_DIR", cache),
        ):
            saved = getattr(module, name)
            setattr(module, name, value)
            self.addCleanup(setattr, module, name, saved)
        saved = common.SETTINGS["office_engine"]
        common.SETTINGS["office_engine"] = "libreoffice"
        self.addCleanup(common.SETTINGS.__setitem__, "office_engine", saved)

        # Sorted: a.pdf, b.docx, c.png — each is the others' neighbour.
        self.pdf = os.path.join(self.dir, "a.pdf")
        samplepdf.write(self.pdf) if hasattr(samplepdf, "write") else open(
            self.pdf, "wb").write(samplepdf.build())
        self.docx = os.path.join(self.dir, "b.docx")
        with open(self.docx, "wb") as fh:
            fh.write(test_office.build_docx(test_office.para("hello")))
        self.png = os.path.join(self.dir, "c.png")
        img = QImage(8, 8, QImage.Format_RGB32)
        img.fill(QColor("blue"))
        img.save(self.png)

        self.window = quickview.QuickView()
        self.addCleanup(self.window.deleteLater)
        # Cleanups run last-first: the page stepper and any job stop before
        # the stand-in worker is swapped back for the real one.
        self.addCleanup(self.window.clear_content)

    def prefetch_around(self, path):
        self.window.current_path = path
        self.window._prefetch_neighbors()

    def ops(self):
        return [(j.job["op"], j.path) for j in FakeJob.made]

    def test_a_documents_neighbours_are_warmed_one_at_a_time(self):
        self.prefetch_around(self.docx)
        # → is c.png, ← is a.pdf; only the first has started.
        self.assertEqual(self.ops(), [("image", self.png)])
        FakeJob.made[0].on_done(True, "")
        self.assertEqual(self.ops(), [("image", self.png), ("pdf", self.pdf)])

    def test_a_warmed_pdf_opens_from_the_cache(self):
        self.prefetch_around(self.png)  # → wraps to a.pdf
        pdf_job = next(j for j in FakeJob.made if j.job["op"] == "pdf")
        self.assertEqual(pdf_job.job["max_pages"], common.PREFETCH_PAGES)
        pdf_job.finish(pages=2)
        FakeJob.made = []
        self.window.current_path = self.pdf
        self.window.show_pdf(self.pdf)
        self.assertNotIn("pdf", [j.job["op"] for j in FakeJob.made],
                         "the pages came from the cache")

    def test_an_office_neighbour_is_warmed_in_its_final_layout(self):
        self.prefetch_around(self.pdf)  # → is b.docx
        job = FakeJob.made[0]
        self.assertEqual((job.job["op"], job.job["engine"]),
                         ("office", "libreoffice"))
        job.finish(pages=2)
        # Opening it now shows LibreOffice's pages at once: no quick
        # layout first, and no upgrade to wait for.
        FakeJob.made = []
        self.window.current_path = self.docx
        self.window.show_office(self.docx, test_office_upgrade_docx())
        self.assertEqual(FakeJob.made, [])
        self.assertEqual(self.window._preview_jobs, [])

    def test_without_libreoffice_the_quick_layout_is_warmed(self):
        self.suite = ""
        self.prefetch_around(self.pdf)
        self.assertEqual(FakeJob.made[0].job["engine"], "builtin")

    def test_nothing_starts_while_the_preview_has_background_work(self):
        self.window._preview_jobs.append(FakeJob(None, "x", {}, None, None))
        self.prefetch_around(self.docx)
        self.assertEqual(len(FakeJob.made), 1, "only the stand-in itself")
        self.window._preview_jobs.clear()
        self.window._start_next_prefetch()
        started = [(j.job["op"], j.path) for j in FakeJob.made[1:]]
        self.assertEqual(started, [("image", self.png)])

    def test_cached_neighbours_are_not_warmed_again(self):
        self.prefetch_around(self.docx)
        while FakeJob.made and len(FakeJob.made) < 3:
            before = len(FakeJob.made)
            FakeJob.made[-1].finish(pages=2)
            if len(FakeJob.made) == before:
                break
        FakeJob.made = []
        self.prefetch_around(self.docx)
        self.assertEqual(FakeJob.made, [])


def test_office_upgrade_docx():
    return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


if __name__ == "__main__":
    unittest.main()
