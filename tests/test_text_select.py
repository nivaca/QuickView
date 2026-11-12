# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Nicolas Vaughan <nivaca@fastmail.com>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Selecting a PDF's text: the selection logic, and the text layer the
jail sends for it, with Poppler and with the QtPdf fallback."""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QFile, QIODevice  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([sys.argv[0]])

import renderers  # noqa: E402
import samplepdf  # noqa: E402
import text_select as ts  # noqa: E402
from renderers import pdf  # noqa: E402


def layer(page=0):
    """Two lines: "alpha beta" over "gamma", boxes on a 200x100 page."""
    text = "alpha beta\ngamma"
    words = [(0, 5, 10, 10, 40, 10, 0), (6, 10, 60, 10, 30, 10, 0),
             (11, 16, 10, 30, 50, 10, 1)]
    return ts.PageText(page, text, words)


class Parse(unittest.TestCase):
    SIZES = [(200, 100), (200, 100)]

    def test_a_good_answer_is_kept(self):
        got = ts.parse({"pages": [{"page": 1, "text": "hi there", "words": [
            [0, 2, 1, 2, 3, 4, 0], [3, 8, 5, 2, 9, 4, 0]]}]}, self.SIZES)
        self.assertEqual(list(got), [1])
        self.assertEqual(len(got[1].words), 2)

    def test_anything_malformed_is_dropped(self):
        bad_pages = [None, {"page": 7, "text": "", "words": []},
                     {"page": True, "text": "", "words": []},
                     {"page": 0, "text": 5, "words": []},
                     {"page": 0, "text": "x" * (ts.PDF_TEXT_MAX_CHARS + 1), "words": []}]
        for entry in bad_pages:
            with self.subTest(entry=str(entry)[:40]):
                self.assertEqual(ts.parse({"pages": [entry]}, self.SIZES), {})
        bad_words = [[0, 9, 0, 0, 1, 1, 0],      # past the text
                     [3, 2, 0, 0, 1, 1, 0],      # backwards
                     [0, 1, 0, 0, 0, 1, 0],      # no width
                     [0, 1, 0, 0, 1, 1],         # short
                     [0, 1, 0, 0, 1.5, 1, 0],    # not an int
                     [0, 1, True, 0, 1, 1, 0]]   # a bool is not an int
        got = ts.parse({"pages": [{"page": 0, "text": "abc", "words": bad_words}]},
                       self.SIZES)
        self.assertEqual(got[0].words, [])
        self.assertEqual(ts.parse("nonsense", self.SIZES), {})

    def test_boxes_are_clamped_to_their_page(self):
        got = ts.parse({"pages": [{"page": 0, "text": "ab", "words": [
            [0, 2, 190, 95, 500, 500, 0]]}]}, self.SIZES)
        x, y, w, h = got[0].words[0][2:6]
        self.assertLessEqual(x + w, 200)
        self.assertLessEqual(y + h, 100)


class Hit(unittest.TestCase):
    def test_the_word_under_the_pointer(self):
        self.assertEqual(ts.hit(layer(), 65, 15), 1)

    def test_the_nearest_word_otherwise(self):
        self.assertEqual(ts.hit(layer(), 52, 15), 0, "between two words, nearer the first")
        self.assertEqual(ts.hit(layer(), 150, 12), 1, "past the end of a line")
        self.assertEqual(ts.hit(layer(), 30, 90), 2, "below the last line")
        self.assertEqual(ts.hit(layer(), 0, 0), 0, "above the first")

    def test_a_page_without_text(self):
        self.assertIsNone(ts.hit(ts.PageText(0, "", []), 5, 5))


class Selecting(unittest.TestCase):
    def test_either_direction_selects_the_same(self):
        layers = {0: layer()}
        forward = ts.Selection((0, 0), (0, 2))
        backward = ts.Selection((0, 2), (0, 0))
        self.assertEqual(forward.text(layers), "alpha beta\ngamma")
        self.assertEqual(backward.text(layers), forward.text(layers))

    def test_the_text_is_the_pages_own_between_the_ends(self):
        self.assertEqual(ts.Selection((0, 1), (0, 2)).text({0: layer()}),
                         "beta\ngamma")

    def test_across_pages(self):
        layers = {0: layer(0), 1: layer(1)}
        sel = ts.Selection((0, 2), (1, 0))
        self.assertEqual(sel.ranges(layers), {0: (2, 2), 1: (0, 0)})
        self.assertEqual(sel.text(layers), "gamma\nalpha")

    def test_pages_whose_text_has_not_arrived_are_skipped(self):
        sel = ts.Selection((0, 0), (2, 0))
        self.assertEqual(list(sel.ranges({0: layer(0)})), [0])
        self.assertEqual(list(sel.pages()), [0, 1, 2])

    def test_one_band_per_line(self):
        self.assertEqual(ts.rects(layer(), 0, 2),
                         [(10, 10, 80, 10), (10, 30, 50, 10)])


class LineBreaks(unittest.TestCase):
    """Between laid-out lines: (x0, y0, x1, y1) in points, 10 pt high."""

    def test_a_paragraphs_lines_are_one_break_apart(self):
        self.assertEqual(pdf._line_break((0, 0, 100, 10), (0, 14, 100, 24)), "\n")

    def test_a_larger_gap_is_a_new_paragraph(self):
        self.assertEqual(pdf._line_break((0, 0, 100, 10), (0, 25, 100, 35)), "\n\n")

    def test_the_same_visual_line_is_joined_by_a_space(self):
        # pdftotext gives "1.2" and "hwloc Overview" lines of their own.
        self.assertEqual(pdf._line_break((0, 0, 20, 10), (30, 0, 100, 10)), " ")

    def test_a_jump_back_up_is_a_new_paragraph(self):
        self.assertEqual(pdf._line_break((0, 500, 100, 510), (0, 20, 100, 30)), "\n\n")


class PageTextFromAPdf(unittest.TestCase):
    """renderers.page_text over a real (generated) PDF, both engines."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = os.path.join(cls.tmp.name, "sample.pdf")
        samplepdf.write(cls.path)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def page_text(self, pages, poppler=True):
        saved = pdf.PDFTOTEXT
        if not poppler:
            pdf.PDFTOTEXT = "/nonexistent/pdftotext"
        fd = os.open(self.path, os.O_RDONLY)
        src = QFile()
        try:
            src.open(fd, QIODevice.OpenModeFlag.ReadOnly)
            return renderers.page_text(src, fd, pages, 600, 50)
        finally:
            src.close()
            os.close(fd)
            pdf.PDFTOTEXT = saved

    def check(self, result, engine):
        self.assertEqual(result["engine"], engine)
        page = result["pages"][0]
        self.assertIn(samplepdf.WORD, page["text"])
        self.assertTrue(page["words"])
        for start, end, x, y, w, h, line in page["words"]:
            self.assertEqual(page["text"][start:end].strip(), page["text"][start:end])
            self.assertTrue(0 <= x < 600 and w > 0 and h > 0)
        # Words on a line run left to right; lines run down the page.
        first, last = page["words"][0], page["words"][-1]
        self.assertLess(first[3], last[3])

    @unittest.skipUnless(os.access(pdf.PDFTOTEXT, os.X_OK), "poppler-utils not installed")
    def test_poppler(self):
        self.check(self.page_text([0]), "poppler")

    def test_the_qtpdf_fallback(self):
        self.check(self.page_text([0], poppler=False), "qtpdf")

    def test_pages_out_of_range_are_ignored(self):
        result = self.page_text([-1, 999, "x"])
        self.assertEqual(result["pages"], [])

    @unittest.skipUnless(os.access(pdf.PDFTOTEXT, os.X_OK), "poppler-utils not installed")
    def test_a_phrase_broken_over_lines_copies_with_a_line_break(self):
        page = next(p for p in self.page_text(list(range(len(samplepdf.PAGES))))["pages"]
                    if "degree of" in p["text"])
        self.assertIn("degree of\nMaster", page["text"])


@unittest.skipUnless(shutil.which("pdftotext"), "poppler-utils not installed")
class ParseRealOutput(unittest.TestCase):
    def test_the_daemon_accepts_what_the_worker_sends(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "sample.pdf")
        samplepdf.write(path)
        fd = os.open(path, os.O_RDONLY)
        src = QFile()
        src.open(fd, QIODevice.OpenModeFlag.ReadOnly)
        try:
            result = renderers.page_text(src, fd, [0], 600, 50)
        finally:
            src.close()
            os.close(fd)
        page = result["pages"][0]
        height = max(w[3] + w[5] for w in page["words"]) + 10
        layers = ts.parse(result, [(600, height)])
        self.assertEqual(len(layers[0].words), len(page["words"]))


if __name__ == "__main__":
    unittest.main()
