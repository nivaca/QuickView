# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Mustapha Alioglou
# Copyright (C) 2026 Nicolas Vaughan <nivaca@fastmail.com>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""PDF pages, text search and the bookmark outline."""

from .base import (
    _encode,
    OUTLINE_MAX_TITLE,
    PDF_MAX_HITS,
    PDF_MAX_OUTLINE,
    PDF_MAX_PAGE_PX,
    PDF_TEXT_MAX_CHARS,
    PDF_TEXT_MAX_WORDS,
    PDF_TEXT_MAX_WORDS_SLOW,
    PDFTOTEXT,
    PDFTOTEXT_TIMEOUT,
)


def _open_pdf(source):
    """Load a PDF, raising rather than returning a half-built document."""
    from PySide6.QtPdf import QPdfDocument

    doc = QPdfDocument()
    # The path overload returns an Error; the QIODevice one returns None and
    # reports through error()/status() instead. Ask the document either way.
    err = doc.load(source)
    if err is None:
        err = doc.error()
    if err != QPdfDocument.Error.None_:
        raise RuntimeError(f"pdf load failed: {err}")
    return doc


def _page_px(doc, i: int, page_w: int) -> tuple:
    """(width, height) in pixels for page i rendered at page_w.

    Shared by render_pdf and search_pdf on purpose. Search maps a match's
    bounding rectangle from points into this pixel space, so the two must
    agree exactly — if they drift, every highlight lands in the wrong place,
    and only on the page shapes that hit the clamps below.
    """
    pt = doc.pagePointSize(i)
    w = max(min(page_w, PDF_MAX_PAGE_PX), 1)
    h = max(1, round(w * pt.height() / max(pt.width(), 1)))
    if h > PDF_MAX_PAGE_PX:
        # Absurdly tall page: keep the aspect ratio and let it be narrow
        # rather than allocating by its declared height.
        h = PDF_MAX_PAGE_PX
        w = max(1, round(h * pt.width() / max(pt.height(), 1)))
    return w, h


def _flatten(text: str, drop_spaces: bool = False) -> tuple:
    """Casefold and normalize whitespace, keeping a map back to the original.

    A PDF's text layer breaks lines with \r\n, so a phrase the reader sees
    as continuous ("degree of Master") is not continuous in the string.
    Collapsing every run of whitespace to one space makes the phrase
    findable; the returned list maps each flattened index back to its index
    in `text`, which is what getSelectionAtIndex needs to place the match.

    drop_spaces removes whitespace altogether, for the fallback described in
    search_pdf: some PDFs position their glyphs instead of emitting spaces,
    and Qt's extractor hands those back as "accordingtoyoursoftskills".
    """
    out, back, space = [], [], False
    for i, ch in enumerate(text):
        if ch.isspace():
            if drop_spaces:
                continue
            if out and not space:  # one space per run, never a leading one
                out.append(" ")
                back.append(i)
                space = True
            continue
        space = False
        low = ch.casefold()
        # casefold can expand (ß -> ss); every produced char points at the
        # single source character it came from, so the map stays aligned.
        out.append(low)
        back.extend([i] * len(low))
    while out and out[-1] == " ":
        out.pop()
        back.pop()
    return "".join(out), back


def search_pdf(source, query: str, page_w: int, max_pages: int,
               max_hits: int = PDF_MAX_HITS) -> dict:
    """Case-insensitive substring search, as rectangles in page pixels.

    Returns {"matches": [{"page": n, "rects": [[x, y, w, h], ...]}, ...],
    "capped": bool} — one entry per match, and one rectangle per line it
    spans. The
    daemon holds no PDF parser, so the text extraction and the geometry both
    happen in here and it receives something it can paint directly.

    Only the pages the viewer actually shows are searched: a hit reported on
    page 73 of a document that stops rendering at 50 is worse than silence.
    """
    if not _flatten(query)[0]:
        return {"matches": [], "capped": False}

    doc = _open_pdf(source)
    pages = [doc.getAllText(i).text() for i in range(min(doc.pageCount(),
                                                        max_pages))]
    out = _scan(doc, pages, query, page_w, max_hits, drop_spaces=False)
    # Nothing found and the query has a space in it? Try again ignoring
    # spaces entirely. Qt's getAllText does not always reconstruct the gaps
    # between glyphs, so a page that reads "soft skills" can extract as
    # "softskills" and no amount of whitespace *collapsing* will match it.
    # Only as a fallback, and only for multi-word queries: matching without
    # spaces would otherwise let "the rap" hit "therapy".
    if not out["matches"] and any(c.isspace() for c in query.strip()):
        loose = _scan(doc, pages, query, page_w, max_hits, drop_spaces=True)
        if loose["matches"]:
            loose["loose"] = True
            return loose
    return out


def _scan(doc, pages: list, query: str, page_w: int, max_hits: int,
          drop_spaces: bool) -> dict:
    """One search pass over already-extracted page text."""
    needle = _flatten(query, drop_spaces)[0]
    matches = []
    if not needle:
        return {"matches": [], "capped": False, "loose": False}
    for i, page_text in enumerate(pages):
        hay, back = _flatten(page_text, drop_spaces)
        if not hay:
            continue
        w_px, h_px = _page_px(doc, i, page_w)
        pt = doc.pagePointSize(i)
        sx = w_px / max(pt.width(), 1)
        sy = h_px / max(pt.height(), 1)
        at = hay.find(needle)
        while at != -1:
            # back[] maps flattened offsets to real ones: a phrase broken
            # over a line is contiguous in `hay` but not in the page text.
            start = back[at]
            end = back[at + len(needle) - 1]
            sel = doc.getSelectionAtIndex(i, start, end - start + 1)
            if sel.isValid():
                # bounds(), not boundingRectangle(): a match crossing a line
                # gets one polygon per line, where the single bounding box
                # would be a slab covering both lines and the gap between.
                rects = []
                for poly in sel.bounds():
                    r = poly.boundingRect()
                    rects.append([
                        round(r.x() * sx), round(r.y() * sy),
                        max(1, round(r.width() * sx)),
                        max(1, round(r.height() * sy)),
                    ])
                if rects:
                    matches.append({"page": i, "rects": rects})
                    if len(matches) >= max_hits:
                        return {"matches": matches, "capped": True,
                                "loose": False}
            at = hay.find(needle, at + 1)
    return {"matches": matches, "capped": False, "loose": False}


def page_text(source, fd: int, pages: list, page_w: int,
              max_pages: int) -> dict:
    """The selectable text of some pages, for copying.

    Returns {"pages": [{"page": n, "text": str, "words": [[start, end, x,
    y, w, h, line], ...]}, ...], "engine": "poppler" | "qtpdf"}: each page's
    text as it should be copied, and each word's span in that text and its
    box in page pixels — the space search and the rendered pages share, so
    the daemon draws a selection over a page without parsing anything.
    `line` numbers the page's lines, so a selection can be drawn as one
    band per line instead of a row of word boxes.

    Poppler's pdftotext does the work when it is installed: one pass lays
    the words out in reading order, columns and all, with the paragraph
    structure the copied text keeps. Without it, QtPdf's own text is used,
    measured word by word — slower, and in the order the file stores it.
    """
    doc = _open_pdf(source)
    count = min(doc.pageCount(), max_pages)
    wanted = sorted({p for p in pages if isinstance(p, int) and 0 <= p < count})
    if not wanted:
        return {"pages": [], "engine": ""}
    layout = _poppler_layout(fd, wanted[0], wanted[-1])
    out = []
    for i in wanted:
        w_px, h_px = _page_px(doc, i, page_w)
        if layout is not None and i in layout:
            width_pt, height_pt, lines = layout[i]
            sx, sy = w_px / max(width_pt, 1), h_px / max(height_pt, 1)
            out.append(_layer_from_lines(i, lines, sx, sy))
        else:
            out.append(_layer_from_qtpdf(doc, i, w_px, h_px))
    return {"pages": out, "engine": "poppler" if layout is not None else "qtpdf"}


def _poppler_layout(fd: int, first: int, last: int):
    """{page: (width, height, [[(paragraph, x0, y0, x1, y1, word), ...]
    per line])} in points, from pdftotext -bbox-layout; or None when it is
    missing or its answer cannot be read."""
    import os
    import subprocess
    import xml.etree.ElementTree as ET

    if not os.access(PDFTOTEXT, os.X_OK):
        return None
    try:
        proc = subprocess.run(
            [PDFTOTEXT, "-q", "-bbox-layout", "-f", str(first + 1),
             "-l", str(last + 1), "/dev/fd/%d" % fd, "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            pass_fds=(fd,), timeout=PDFTOTEXT_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    try:
        root = ET.fromstring(proc.stdout)
    except ET.ParseError:
        return None  # a control character in the text can do this
    layout = {}
    for n, page in enumerate(e for e in root.iter() if _local(e.tag) == "page"):
        try:
            width = float(page.get("width"))
            height = float(page.get("height"))
        except (TypeError, ValueError):
            continue
        lines, paragraph = [], 0
        for block in (e for e in page.iter() if _local(e.tag) == "block"):
            paragraph += 1
            for line in (e for e in block if _local(e.tag) == "line"):
                words = []
                for word in (e for e in line if _local(e.tag) == "word"):
                    try:
                        box = [float(word.get(k)) for k in
                               ("xMin", "yMin", "xMax", "yMax")]
                    except (TypeError, ValueError):
                        continue
                    if word.text:
                        words.append((paragraph, *box, word.text))
                if words:
                    lines.append(words)
        layout[first + n] = (width, height, lines)
    return layout


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _line_break(previous: tuple, line: tuple) -> str:
    """What goes between two laid-out lines, from where they sit, each
    (x0, y0, x1, y1) in points. Measured on real pages: lines of a
    paragraph are ~0.4 line heights apart, tight list items ~0.8, and
    paragraphs 1.2 and more.

    * " " when the next one is on the same visual line, to the right:
      pdftotext splits a heading's number from its title ("1.2" | "hwloc
      Overview") into lines of their own;
    * "\n" when it is no more than a line height below;
    * "\n\n" for a larger gap, or a jump back up the page — a new column,
      or a running head printed after the body.
    """
    px0, py0, px1, py1 = previous
    x0, y0, x1, y1 = line
    height = max(1e-6, min(py1 - py0, y1 - y0))
    if y0 < py1 and y1 > py0:  # they overlap vertically
        return " " if x0 >= px1 - height * 0.5 else "\n\n"
    gap = y0 - py1
    if gap < 0:
        return "\n\n"
    return "\n" if gap <= height else "\n\n"


def _layer_from_lines(page: int, lines: list, sx: float, sy: float) -> dict:
    """Join laid-out words into the copy text: a space between words, and
    between lines whatever _line_break says their positions call for."""
    text, words, previous = [], [], None
    length = 0
    for line_no, line in enumerate(lines):
        box = (min(w[1] for w in line), min(w[2] for w in line),
               max(w[3] for w in line), max(w[4] for w in line))
        if previous is not None:
            sep = _line_break(previous, box)
            text.append(sep)
            length += len(sep)
        previous = box
        for k, (_p, x0, y0, x1, y1, word) in enumerate(line):
            if k:
                text.append(" ")
                length += 1
            if (length + len(word) > PDF_TEXT_MAX_CHARS
                    or len(words) >= PDF_TEXT_MAX_WORDS):
                return {"page": page, "text": "".join(text), "words": words}
            words.append([length, length + len(word),
                          round(x0 * sx), round(y0 * sy),
                          max(1, round((x1 - x0) * sx)),
                          max(1, round((y1 - y0) * sy)), line_no])
            text.append(word)
            length += len(word)
    return {"page": page, "text": "".join(text), "words": words}


def _layer_from_qtpdf(doc, page: int, w_px: int, h_px: int) -> dict:
    """The fallback: QtPdf's text, each word measured on its own."""
    import re

    pt = doc.pagePointSize(page)
    sx, sy = w_px / max(pt.width(), 1), h_px / max(pt.height(), 1)
    text = doc.getAllText(page).text()[:PDF_TEXT_MAX_CHARS].replace("\r\n", "\n")
    words = []
    for match in re.finditer(r"\S+", text):
        if len(words) >= PDF_TEXT_MAX_WORDS_SLOW:
            break
        start, end = match.span()
        sel = doc.getSelectionAtIndex(page, start, end - start)
        if not sel.isValid():
            continue
        r = sel.boundingRectangle()
        words.append([start, end, round(r.x() * sx), round(r.y() * sy),
                      max(1, round(r.width() * sx)),
                      max(1, round(r.height() * sy)),
                      text.count("\n", 0, start)])
    return {"page": page, "text": text, "words": words}


def render_pdf(source, page_w: int, max_pages: int, start: int = 0,
               scale: float = 1.0):
    """Yield (page_count, png_bytes) for pages start..max_pages-1.

    Every yielded page carries the document's real page count in a
    "QuickView:PageCount" tEXt chunk — it can exceed the number of pages
    streamed when the cap truncates. Pages are yielded one at a time so the
    caller can show page 1 before the rest exist. start skips pages the
    caller already has (a partially cached document resumes there instead
    of re-rendering the prefix).

    scale is the screen's device pixel ratio: the page keeps its page_w
    geometry — the one search and the outline are measured in — but is
    rendered with scale times the pixels, so a 1.5x screen shows it sharp
    instead of stretching it. See _scaled_px.
    """
    from PySide6.QtCore import QSize, Qt
    from PySide6.QtGui import QImage, QPainter

    doc = _open_pdf(source)
    total = doc.pageCount()
    count = min(total, max_pages)
    for i in range(max(start, 0), count):
        w, h = _page_px(doc, i, page_w)
        sw, sh, used = _scaled_px(w, h, scale)
        rendered = doc.render(i, QSize(sw, sh))
        if rendered.isNull():
            raise RuntimeError(f"render failed on page {i}")
        # Qt renders onto transparency: a PDF paints its glyphs but almost
        # never its own page background, so the raw image is black text on
        # nothing. Composite it over white to get the sheet of paper the
        # reader expects (and drop the alpha channel while we're at it).
        img = QImage(rendered.size(), QImage.Format.Format_RGB32)
        img.fill(Qt.GlobalColor.white)
        painter = QPainter(img)
        painter.drawImage(0, 0, rendered)
        painter.end()
        img.setText("QuickView:PageCount", str(total))
        img.setText("QuickView:Scale", "%.4f" % used)
        yield count, _encode(img)


def _scaled_px(w: int, h: int, scale: float) -> tuple:
    """(w, h, scale actually used) for a page drawn at a pixel ratio.

    The ratio is clamped to [1, 4] — it comes from the daemon, but it is
    still a number that sizes an allocation — and shrunk further if it
    would take the page past PDF_MAX_PAGE_PX. The ratio used is what the
    page's "QuickView:Scale" chunk records, so the daemon always divides by
    the factor that was really applied rather than the one it asked for.
    """
    try:
        scale = min(max(float(scale), 1.0), 4.0)
    except (TypeError, ValueError):
        scale = 1.0
    # w and h are already within PDF_MAX_PAGE_PX, so this never goes below 1.
    scale = max(1.0, min(scale, PDF_MAX_PAGE_PX / max(w, h, 1)))
    return max(1, round(w * scale)), max(1, round(h * scale)), scale


def pdf_outline(source, page_w: int, max_pages: int,
                max_entries: int = PDF_MAX_OUTLINE) -> list:
    """The document's bookmarks, flattened: [{title, level, page, y}, ...].

    Qt builds the outline as a tree model, which is walked here rather than
    in the daemon: the daemon owns no PDF parser, and shipping a model over
    a socket is not a thing. Entries past the last rendered page are
    dropped — an outline row that cannot scroll anywhere is a dead link.

    y is where on its page the destination sits, in the pixels the page will
    be rendered at. A section is not a page: five subsections of one chapter
    share page 7 of the sample this was built against, and without y all
    five scroll to the same place — which, on a page taller than the window,
    looks like the sidebar doing nothing at all.
    """
    from PySide6.QtCore import QModelIndex
    from PySide6.QtPdf import QPdfBookmarkModel

    doc = _open_pdf(source)
    model = QPdfBookmarkModel()
    model.setDocument(doc)
    role = QPdfBookmarkModel.Role
    limit = min(doc.pageCount(), max_pages)
    out = []

    def walk(parent, level: int):
        for row in range(model.rowCount(parent)):
            if len(out) >= max_entries:
                return
            index = model.index(row, 0, parent)
            title = (model.data(index, role.Title.value) or "").strip()
            try:
                page = int(model.data(index, role.Page.value) or 0)
            except (TypeError, ValueError):
                page = 0
            if title and 0 <= page < limit:
                out.append({
                    "title": title[:OUTLINE_MAX_TITLE],
                    "level": min(level, 5),
                    "page": page,
                    "y": _outline_y(doc, page, page_w,
                                    model.data(index, role.Location.value)),
                })
            walk(index, level + 1)

    walk(QModelIndex(), 0)
    return out


def _outline_y(doc, page: int, page_w: int, location) -> int:
    """A bookmark's destination as an offset down the rendered page.

    The model gives it in points from the top of the page; the daemon
    scrolls in the pixels the page was rendered at.
    """
    if location is None:
        return 0
    _w, h_px = _page_px(doc, page, page_w)
    height_pt = doc.pagePointSize(page).height()
    if height_pt <= 0:
        return 0
    try:
        y_pt = float(location.y())
    except (AttributeError, TypeError, ValueError):
        return 0
    return max(0, min(h_px - 1, round(y_pt * h_px / height_pt)))
