# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Nicolas Vaughan <nivaca@fastmail.com>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Selecting and copying a PDF's text, over the rendered pages.

The pages on screen are pictures. Their text comes from the jail, page by
page, as renderers.page_text() lays it out: the text to copy, and each
word's span in it and its box in page pixels — the space the page labels
are sized in. This module is the daemon's side of that: it checks what the
worker sent, finds the word under the pointer, and turns a selection into
highlight rectangles and into the text to put on the clipboard. Plain
Python, no Qt: the view wires it to the mouse and the keyboard.

A position is (page, word index); a selection runs from an anchor (where
the press was) to a head (where the pointer is), in reading order, across
pages if the drag crosses them.
"""

from renderers.base import PDF_TEXT_MAX_CHARS, PDF_TEXT_MAX_WORDS


class PageText:
    """One page's text layer: words are (start, end, x, y, w, h, line)."""

    __slots__ = ("page", "text", "words", "_lines")

    def __init__(self, page: int, text: str, words: list):
        self.page = page
        self.text = text
        self.words = words
        self._lines = None

    def lines(self) -> list:
        """[(top, bottom, [word index, ...]), ...], one per line, in order."""
        if self._lines is None:
            by_line = {}
            for i, word in enumerate(self.words):
                by_line.setdefault(word[6], []).append(i)
            lines = []
            for _line, members in sorted(by_line.items()):
                top = min(self.words[i][3] for i in members)
                bottom = max(self.words[i][3] + self.words[i][5] for i in members)
                lines.append((top, bottom, members))
            self._lines = lines
        return self._lines


def parse(payload, page_sizes: list) -> dict:
    """{page: PageText} from a worker's page_text() answer, keeping only
    what is well formed: the worker parsed an untrusted file, so its answer
    is checked like one. page_sizes is each page label's (width, height);
    boxes are clamped to their page."""
    layers = {}
    if not isinstance(payload, dict) or not isinstance(payload.get("pages"), list):
        return layers
    for entry in payload["pages"]:
        if not isinstance(entry, dict):
            continue
        page, text, words = entry.get("page"), entry.get("text"), entry.get("words")
        if (not isinstance(page, int) or isinstance(page, bool)
                or not 0 <= page < len(page_sizes)
                or not isinstance(text, str) or len(text) > PDF_TEXT_MAX_CHARS
                or not isinstance(words, list) or len(words) > PDF_TEXT_MAX_WORDS):
            continue
        width, height = page_sizes[page]
        kept = []
        for word in words:
            if (not isinstance(word, list) or len(word) != 7
                    or not all(isinstance(v, int) and not isinstance(v, bool)
                               for v in word)):
                continue
            start, end, x, y, w, h, line = word
            if not 0 <= start < end <= len(text) or line < 0 or w <= 0 or h <= 0:
                continue
            x, y = max(0, min(x, width - 1)), max(0, min(y, height - 1))
            kept.append((start, end, x, y, min(w, width - x), min(h, height - y), line))
        layers[page] = PageText(page, text, kept)
    return layers


def hit(layer: PageText, x: float, y: float):
    """The word at (x, y) on the page, or the nearest one: on the nearest
    line, the nearest word along it. None for a page with no text."""
    if not layer.words:
        return None
    for i, (_s, _e, wx, wy, ww, wh, _l) in enumerate(layer.words):
        if wx <= x < wx + ww and wy <= y < wy + wh:
            return i

    def gap(lo, hi, v):
        return 0 if lo <= v <= hi else min(abs(v - lo), abs(v - hi))

    _top, _bottom, members = min(layer.lines(), key=lambda ln: gap(ln[0], ln[1], y))
    return min(members, key=lambda i: gap(layer.words[i][2],
                                          layer.words[i][2] + layer.words[i][4], x))


class Selection:
    """From an anchor to a head, each (page, word index), in either order."""

    def __init__(self, anchor: tuple, head: tuple = None):
        self.anchor = anchor
        self.head = head if head is not None else anchor

    def bounds(self) -> tuple:
        return tuple(sorted((self.anchor, self.head)))

    def pages(self) -> range:
        (first, _), (last, _) = self.bounds()
        return range(first, last + 1)

    def ranges(self, layers: dict) -> dict:
        """{page: (first word, last word)} for each page in the selection
        whose text is known."""
        (p0, i0), (p1, i1) = self.bounds()
        out = {}
        for page in range(p0, p1 + 1):
            layer = layers.get(page)
            if layer is None or not layer.words:
                continue
            a = i0 if page == p0 else 0
            b = i1 if page == p1 else len(layer.words) - 1
            a, b = max(0, a), min(b, len(layer.words) - 1)
            if a <= b:
                out[page] = (a, b)
        return out

    def text(self, layers: dict) -> str:
        """The selected text as the page has it — line breaks, paragraph
        breaks and all — with a line break between pages."""
        parts = []
        for page, (a, b) in sorted(self.ranges(layers).items()):
            layer = layers[page]
            parts.append(layer.text[layer.words[a][0]:layer.words[b][1]])
        return "\n".join(parts).replace("\r\n", "\n")


def rects(layer: PageText, a: int, b: int) -> list:
    """Highlight rectangles for words a..b: one band per line, from the
    line's first selected word to its last, rather than a row of boxes."""
    out, run = [], []
    for i in range(a, b + 1):
        word = layer.words[i]
        if run and word[6] != layer.words[run[-1]][6]:
            out.append(_band(layer, run))
            run = []
        run.append(i)
    if run:
        out.append(_band(layer, run))
    return out


def _band(layer: PageText, run: list) -> tuple:
    words = [layer.words[i] for i in run]
    x0 = min(w[2] for w in words)
    y0 = min(w[3] for w in words)
    x1 = max(w[2] + w[4] for w in words)
    y1 = max(w[3] + w[5] for w in words)
    return (x0, y0, x1 - x0, y1 - y0)
