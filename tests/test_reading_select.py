# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Nicolas Vaughan <nicolasvaughan@proton.me>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Selecting the text of a rendered Markdown file, a book or an office
document: the words and their boxes, from the layout the pages were
painted with, and the page view asking for them.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([sys.argv[0]])

import quickview  # noqa: E402
import renderers  # noqa: E402
import text_select  # noqa: E402
import view_selection  # noqa: E402
import worker  # noqa: E402
from renderers import suite as r_suite  # noqa: E402 — patched where read
from test_epub import SIMPLE, build_epub  # noqa: E402
from test_office import build_docx, para  # noqa: E402

PAGE_W = 400
PAGE_H = int(PAGE_W * renderers.PAGE_RATIO)

MARKDOWN = """# Title here

A paragraph of **bold** text that is long enough to wrap across more than
one line when the page is narrow, so wrapping is tested.

- item one
- item two

| a | b |
|---|---|
| c1 | d1 |

```
code line
```
"""


def in_file(data: bytes):
    fh = tempfile.TemporaryFile()
    fh.write(data)
    fh.flush()
    return fh


def md_text(text: str, pages=(0,), max_pages: int = 50) -> dict:
    with in_file(text.encode()) as fh:
        return renderers.markdown_text(fh.fileno(), list(pages), PAGE_W, max_pages)


def words_of(layer: dict) -> list:
    return [layer["text"][w[0]:w[1]] for w in layer["words"]]


class Markdown(unittest.TestCase):
    def setUp(self):
        self.out = md_text(MARKDOWN)
        self.page = self.out["pages"][0]

    def test_the_text_reads_as_it_is_copied(self):
        text = self.page["text"]
        self.assertTrue(text.startswith("Title here\nA paragraph of bold text"))
        self.assertIn("more than one line", text, "a wrapped line joins with a space")
        self.assertIn("\nitem one\nitem two\n", text)
        self.assertIn("\na\tb\nc1\td1\n", text, "a table row is one line, tab apart")
        self.assertTrue(text.endswith("\ncode line"))

    def test_every_word_has_a_box_on_the_page(self):
        self.assertEqual(words_of(self.page), self.page["text"].split())
        for _s, _e, x, y, w, h, _line in self.page["words"]:
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(x + w, PAGE_W)
            self.assertLessEqual(y + h, PAGE_H)

    def test_the_daemon_accepts_every_word(self):
        layers = text_select.parse(self.out, [(PAGE_W, PAGE_H)])
        self.assertEqual(len(layers[0].words), len(self.page["words"]))

    def test_words_on_one_line_share_it_and_lines_go_down(self):
        by_line = {}
        for word in self.page["words"]:
            by_line.setdefault(word[6], set()).add(word[3])
        tops = [min(ys) for _n, ys in sorted(by_line.items())]
        self.assertEqual(tops, sorted(tops))
        title, here = self.page["words"][:2]
        self.assertEqual((title[3], title[6]), (here[3], here[6]))
        self.assertLess(title[2] + title[4], here[2])

    def test_each_page_has_its_own_words(self):
        long = "\n\n".join(f"Paragraph {i} " + "word " * 30 for i in range(40))
        out = md_text(long, pages=[1, 0, 99])
        self.assertEqual([p["page"] for p in out["pages"]], [0, 1],
                         "sorted, and a page past the end is dropped")
        first, second = out["pages"]
        self.assertTrue(first["text"].startswith("Paragraph 0 "))
        self.assertFalse(second["text"].startswith("Paragraph 0 "))
        self.assertTrue(second["words"])

    def test_no_pages_asked_none_answered(self):
        self.assertEqual(md_text(MARKDOWN, pages=["x", True])["pages"], [])


class Book(unittest.TestCase):
    def test_a_book_page_has_its_words(self):
        with in_file(build_epub(SIMPLE)) as fh:
            out = renderers.epub_text(fh.fileno(), [0], PAGE_W, 50)
        page = out["pages"][0]
        self.assertTrue(page["text"].startswith("One\nThe harbour road was empty"))
        self.assertEqual(words_of(page), page["text"].split())
        layers = text_select.parse(out, [(PAGE_W, PAGE_H)])
        self.assertEqual(len(layers[0].words), len(page["words"]))


DOCX = build_docx(para("Hello office world") + para("second paragraph")
                  + para("next page", ppr="<w:pageBreakBefore/>"))


def office_text(engine="builtin", pages=(0,)):
    with in_file(DOCX) as fh:
        return renderers.office_text(fh.fileno(), list(pages), PAGE_W, 50, engine)


class Office(unittest.TestCase):
    def setUp(self):
        saved = r_suite.OFFICE_SUITES
        self.addCleanup(setattr, r_suite, "OFFICE_SUITES", saved)

    def test_the_built_in_layout_answers_every_page(self):
        r_suite.OFFICE_SUITES = ()
        out = office_text(pages=[0])
        self.assertEqual(out["engine"], "layout")
        first = out["pages"][0]
        self.assertTrue(first["text"].startswith("Hello office world\nsecond paragraph"))
        self.assertEqual(words_of(first), first["text"].split())
        layers = text_select.parse(out, [(PAGE_W, PAGE_H)] * len(out["pages"]))
        self.assertEqual(len(layers[0].words), len(first["words"]))

    def test_a_failing_suite_falls_back_to_the_layout_that_painted(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        fake = os.path.join(tmp.name, "soffice")
        with open(fake, "w") as fh:
            fh.write("#!/bin/sh\nexit 1\n")
        os.chmod(fake, 0o755)
        r_suite.OFFICE_SUITES = (fake,)
        self.assertEqual(office_text(engine="libreoffice")["engine"], "layout")

    @unittest.skipUnless(renderers.office_suite(), "LibreOffice not installed")
    def test_libreoffice_pages_take_their_text_from_its_pdf(self):
        out = office_text(engine="libreoffice", pages=[0])
        self.assertIn(out["engine"], ("poppler", "qtpdf"))
        self.assertEqual([p["page"] for p in out["pages"]], [0, 1],
                         "every page, from one conversion")
        self.assertIn("Hello office world", out["pages"][0]["text"])
        self.assertIn("next page", out["pages"][1]["text"])


class Out:
    def header(self, *args, **kw):
        pass

    def json(self, value):
        self.value = value


class WorkerOps(unittest.TestCase):
    def test_mdtext_and_epubtext(self):
        for op, data in (("mdtext", MARKDOWN.encode()), ("epubtext", build_epub(SIMPLE))):
            with self.subTest(op=op), in_file(data) as fh:
                out = Out()
                worker.OPS[op]({"op": op, "pages": [0], "page_w": PAGE_W,
                                "max_pages": 50, "theme": "sepia"},
                               None, fh.fileno(), out)
                self.assertEqual(out.value["pages"][0]["page"], 0)
                self.assertTrue(out.value["pages"][0]["words"])

    def test_officetext(self):
        saved = r_suite.OFFICE_SUITES
        self.addCleanup(setattr, r_suite, "OFFICE_SUITES", saved)
        r_suite.OFFICE_SUITES = ()
        with in_file(DOCX) as fh:
            out = Out()
            worker.OPS["officetext"]({"pages": [1], "page_w": PAGE_W, "max_pages": 50,
                                      "engine": "libreoffice"}, None, fh.fileno(), out)
        self.assertEqual([p["page"] for p in out.value["pages"]], [0, 1])

    def test_pages_must_be_a_list(self):
        with in_file(MARKDOWN.encode()) as fh, self.assertRaises(RuntimeError):
            worker.OPS["mdtext"]({"pages": "0", "page_w": PAGE_W, "max_pages": 50},
                                 None, fh.fileno(), Out())


class FakeJob:
    made = []

    def __init__(self, pool, path, job, on_frame, on_done, parent=None, **_kw):
        self.job, self.on_frame, self.on_done = job, on_frame, on_done
        FakeJob.made.append(self)

    def cancel(self):
        pass


class View(unittest.TestCase):
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

    def begin(self, op, extra=None):
        self.w._pdf_begin_view("/x", 1, [(PAGE_W, PAGE_H)], op=op,
                               page_w=PAGE_W, extra=extra)
        self.w.show()
        QApplication.processEvents()

    def test_markdown_asks_for_its_words_in_its_own_layout(self):
        self.begin("markdown", {"name": "x.md", "theme": "sepia",
                                "font": "Serif", "font_size": 14})
        QTest.keyClick(self.w, Qt.Key_A, Qt.ControlModifier)
        job = FakeJob.made[-1].job
        self.assertEqual((job["op"], job["pages"], job["page_w"]), ("mdtext", [0], PAGE_W))
        self.assertEqual((job["theme"], job["font"], job["font_size"]), ("sepia", "Serif", 14))
        # The real layer, as the worker would send it.
        FakeJob.made[-1].on_frame(json.dumps(md_text(MARKDOWN)).encode())
        FakeJob.made[-1].on_done(True, "")
        QTest.keyClick(self.w, Qt.Key_C, Qt.ControlModifier)
        copied = QGuiApplication.clipboard().text()
        self.assertTrue(copied.startswith("Title here\nA paragraph"))
        self.assertIn("c1\td1", copied)

    def test_a_book_uses_epubtext(self):
        self.begin("epub", {"name": "x.epub"})
        QTest.keyClick(self.w, Qt.Key_A, Qt.ControlModifier)
        self.assertEqual(FakeJob.made[-1].job["op"], "epubtext")

    def test_an_office_document_asks_with_its_engine(self):
        self.begin("office", {"name": "x.docx", "limit": 1024, "engine": "builtin"})
        QTest.keyClick(self.w, Qt.Key_A, Qt.ControlModifier)
        job = FakeJob.made[-1].job
        self.assertEqual((job["op"], job["engine"]), ("officetext", "builtin"))

    def test_pages_answered_beyond_those_asked_are_kept(self):
        self.w._pdf_begin_view("/x", 2, [(PAGE_W, PAGE_H)] * 2, op="office",
                               page_w=PAGE_W, extra={"engine": "builtin"})
        self.w.show()
        QApplication.processEvents()
        self.w._sel_need([0])
        job = FakeJob.made[-1]
        self.assertEqual(job.job["pages"], [0])
        both = {"pages": [{"page": p, "text": "word", "words": [[0, 4, 1, 1, 9, 9, 0]]}
                          for p in (0, 1)]}
        job.on_frame(json.dumps(both).encode())
        job.on_done(True, "")
        self.assertEqual(sorted(self.w._sel_layers), [0, 1])
        self.w._sel_need([1])
        self.assertEqual(len(FakeJob.made), 1, "page 1 is known: no second job")


if __name__ == "__main__":
    unittest.main()
