# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Mustapha Alioglou
# Copyright (C) 2026 Nicolas Vaughan <nivaca@fastmail.com>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""EPUB books laid out as pages, with search and a table of contents."""

from .base import (
    DEFAULT_READING_FONT_SIZE,
    reading_font,
    OFFICE_MAX_MEMBER_BYTES,
    OUTLINE_MAX_TITLE,
    PAGE_RATIO,
    PDF_MAX_HITS,
    _rewound,
    _stderr,
)
from .office import (
    _document_pages,
    _escape,
    _member_xml,
    _stash_image,
)


# -------------------------------------------------------------------- epub
# An EPUB is a zip of XHTML documents with a reading order and a table of
# contents, which is almost exactly what QTextDocument lays out — so a book
# is previewed by the same page pipeline as an office document, with no
# reader engine anywhere. What the office path cannot do is say *where* a
# chapter starts, and a book without that is a wall of pages: the spine is
# inserted chunk by chunk through a cursor, and the cursor position at each
# chunk's start is what turns the table of contents into page numbers.
# How a book is painted. A preview of a novel is something a person reads
# for minutes rather than glances at, so the page colours are a setting —
# see config.book_theme. Only the page is themed: the panel around it is
# application chrome and stays as it is.
BOOK_THEMES = {
    "paper": {"bg": "#ffffff", "fg": "#141414", "head": "#000000",
              "muted": "#555555"},
    "sepia": {"bg": "#f4ecd8", "fg": "#4a3f35", "head": "#33291f",
              "muted": "#7a6a58"},
    "dark": {"bg": "#1e1e21", "fg": "#d6d6da", "head": "#ffffff",
             "muted": "#9a9aa2"},
    # gruvbox, from the palette itself: bg0/fg1 for the page, bright yellow
    # (dark) and neutral orange (light) for headings, gray for quotations.
    "gruvbox-dark": {"bg": "#282828", "fg": "#ebdbb2", "head": "#fabd2f",
                     "muted": "#a89984"},
    "gruvbox-light": {"bg": "#fbf1c7", "fg": "#3c3836", "head": "#af3a03",
                      "muted": "#7c6f64"},
}


DEFAULT_BOOK_THEME = "paper"


EPUB_MAX_CHARS = 1_500_000     # markup pulled from the spine, total


EPUB_MAX_SPINE_ITEMS = 300


EPUB_MAX_IMAGES = 40


EPUB_MAX_TOC = 500


# Tags QTextDocument understands, mapped from the ones books actually use.
# Anything absent contributes its text and its children but no markup of its
# own — a <section> or a <span> is a container, not something to render.
_EPUB_TAGS = {
    "h1": ("<h2>", "</h2>"), "h2": ("<h2>", "</h2>"),
    "h3": ("<h3>", "</h3>"), "h4": ("<h3>", "</h3>"),
    "h5": ("<h4>", "</h4>"), "h6": ("<h4>", "</h4>"),
    "p": ("<p>", "</p>"), "blockquote": ("<blockquote>", "</blockquote>"),
    "ul": ("<ul>", "</ul>"), "ol": ("<ol>", "</ol>"), "li": ("<li>", "</li>"),
    "b": ("<b>", "</b>"), "strong": ("<b>", "</b>"),
    "i": ("<i>", "</i>"), "em": ("<i>", "</i>"), "u": ("<u>", "</u>"),
    "sup": ("<sup>", "</sup>"), "sub": ("<sub>", "</sub>"),
    "table": ("<table border='1' cellspacing='0' width='100%'>", "</table>"),
    "tr": ("<tr>", "</tr>"), "td": ("<td>", "</td>"), "th": ("<th>", "</th>"),
    "pre": ("<pre>", "</pre>"), "code": ("<code>", "</code>"),
    "hr": ("<hr>", ""), "br": ("<br>", ""),
}


# Never rendered: script and style would print as text, and the navigation
# document is the table of contents, not a chapter.
_EPUB_SKIP = {"script", "style", "head", "svg", "iframe", "object", "video",
              "audio", "nav", "template"}


_HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")


def book_theme(name: str) -> dict:
    """The named palette, or the default. An unknown name is a typo in a
    config file, which must not stop a book from opening."""
    return BOOK_THEMES.get(
        (name or "").strip().lower(), BOOK_THEMES[DEFAULT_BOOK_THEME]
    )


def _book_css(palette: dict, font: str = "",
              font_size: int = DEFAULT_READING_FONT_SIZE) -> str:
    """The document style sheet a themed book is laid out with.

    Selectors rather than a body rule: the spine is inserted as HTML
    fragments through a cursor, and a fragment has no body element for a
    body rule to reach. font is the reader's chosen family, "" for the
    built-in serif; either way serif stays as the fallback.
    """
    font, font_size = reading_font(font, font_size)
    family = f"'{font}', serif" if font else "serif"
    return (
        "p, li, td, th, pre, code { font-family: %(family)s;"
        " font-size: %(size)dpt; color: %(fg)s; }"
        "h1, h2, h3, h4 { font-family: %(family)s; color: %(head)s; }"
        "blockquote { font-family: %(family)s; font-size: %(size)dpt;"
        " color: %(muted)s; }"
        "hr { color: %(muted)s; }"
    ) % {**palette, "family": family, "size": font_size}


def epub_pages(fd: int, name: str, page_w: int, max_pages: int,
               start: int = 0, theme: str = DEFAULT_BOOK_THEME,
               scale: float = 1.0, font: str = "",
               font_size: int = DEFAULT_READING_FONT_SIZE):
    """Yield (info, png_bytes) for a book, as page images.

    info is the same dict on every page — {"count", "chapters", "title"} —
    so the caller can build its sidebar from the first frame it receives
    without waiting for the book to finish rendering.
    """
    page_h = int(page_w * PAGE_RATIO)
    book = _epub_document(fd, page_w, theme, font, font_size)
    doc = book["doc"]
    count = min(doc.pageCount(), max_pages)
    info = {
        "count": count,
        "title": book["title"],
        "chapters": _epub_chapters(
            doc, book["toc"], book["positions"], book["headings"],
            page_h, count,
        ),
    }
    for _n, png in _document_pages(
        doc, page_w, page_h, count, start, book["palette"]["bg"], scale
    ):
        yield info, png


def _epub_document(fd: int, page_w: int, theme: str, font: str = "",
                   font_size: int = DEFAULT_READING_FONT_SIZE) -> dict:
    """Lay a book out once: the document, and what was needed to build it.

    Rendering and searching both need the same laid-out document — a match
    rectangle is only meaningful in the layout the pages were painted from —
    so the whole of it lives here rather than in either caller.
    """
    import zipfile

    from PySide6.QtCore import Qt, QSizeF, QUrl
    from PySide6.QtGui import (
        QImage, QTextBlockFormat, QTextCursor, QTextDocument, QTextFormat,
    )

    page_h = int(page_w * PAGE_RATIO)
    with _rewound(fd) as fh:
        if not zipfile.is_zipfile(fh):
            raise RuntimeError("not an epub")
        fh.seek(0)
        with zipfile.ZipFile(fh) as zf:
            names = set(zf.namelist())
            spine, toc, title = _epub_parts(zf, names)
            if not spine:
                raise RuntimeError("no readable spine")

            # Converted before anything is inserted: an image resource has
            # to be registered with the document before the HTML naming it
            # is laid out, and which images a book uses is only known once
            # its markup has been walked.
            wanted = {e["target"] for e in toc if "#" in e["target"]}
            images, headings, chunks, chars = {}, {}, [], 0
            for member in spine[:EPUB_MAX_SPINE_ITEMS]:
                try:
                    part = _epub_chunks(zf, member, images, wanted, headings)
                except Exception as exc:  # noqa: BLE001 — see below
                    # One chapter that will not parse (a broken XHTML file,
                    # an encoding nothing here can read) must cost that
                    # chapter, not the book.
                    print("epub: skipping %s (%s)" % (member, exc),
                          file=_stderr())
                    continue
                for anchor, html in part:
                    if not html.strip():
                        continue
                    chunks.append((anchor, html))
                    chars += len(html)
                if chars > EPUB_MAX_CHARS:
                    break

            palette = book_theme(theme)
            doc = QTextDocument()
            doc.setDefaultStyleSheet(_book_css(palette, font, font_size))
            doc.setDocumentMargin(page_w * 0.06)
            doc.setPageSize(QSizeF(page_w, page_h))
            for key, data in images.items():
                img = QImage.fromData(data)
                if img.isNull():
                    continue
                # Scaled here rather than with a width attribute in the
                # markup: QTextDocument draws an image at its natural size
                # and lets it run off the page, and a book's illustrations
                # are routinely wider than the page they are printed on.
                limit = int(page_w * 0.8)
                if img.width() > limit:
                    img = img.scaledToWidth(limit, Qt.SmoothTransformation)
                doc.addResource(
                    QTextDocument.ResourceType.ImageResource, QUrl(key), img,
                )
            cursor = QTextCursor(doc)
            positions = {}
            for anchor, html in chunks:
                if cursor.position():
                    # A new spine document starts a new page, which is what
                    # a reader does with a chapter and what makes the page
                    # numbers in the sidebar mean something. A chunk split
                    # out of the *middle* of a file (a fragment the table of
                    # contents points at) does not: the book's own author
                    # chose to keep those on one page.
                    fmt = QTextBlockFormat()
                    if "#" not in anchor:
                        fmt.setPageBreakPolicy(
                            QTextFormat.PageBreakFlag.PageBreak_AlwaysBefore
                        )
                    cursor.insertBlock(fmt)
                # setdefault: two chapters may point at the same place (a
                # part title and its first section), and the first one to
                # claim a position is the one the reader means.
                positions.setdefault(anchor, cursor.position())
                cursor.insertHtml(html)
            if not doc.characterCount() > 1:
                raise RuntimeError("nothing to lay out")

            doc.setPageSize(QSizeF(page_w, page_h))
            return {"doc": doc, "positions": positions, "toc": toc,
                    "headings": headings, "title": title, "palette": palette}


def search_epub(fd: int, query: str, page_w: int, max_pages: int,
                theme: str = DEFAULT_BOOK_THEME,
                max_hits: int = PDF_MAX_HITS, font: str = "",
                font_size: int = DEFAULT_READING_FONT_SIZE) -> dict:
    """Case-insensitive search over a book, as rectangles in page pixels.

    The same answer shape as search_pdf, so the daemon paints both with the
    same code: {"matches": [{"page": n, "rects": [[x, y, w, h], ...]}, ...]}.

    The book is laid out again here rather than searched as flat text. A
    rectangle only means something in a layout, and this is the same layout
    the pages were painted from — same width, same style sheet — so a match
    lands where the reader can see it.
    """
    from PySide6.QtGui import QTextDocument

    if not query.strip():
        return {"matches": [], "capped": False}

    page_h = int(page_w * PAGE_RATIO)
    doc = _epub_document(fd, page_w, theme, font, font_size)["doc"]
    # Also forces the layout: a block's lines do not exist until something
    # asks for them, and without them every match measures as no rectangle
    # at all.
    count = min(doc.pageCount(), max_pages)
    matches, at = [], 0
    while True:
        cursor = doc.find(query, at, QTextDocument.FindFlag(0))
        if cursor.isNull():
            break
        # Guard against a zero-width match looping forever on the same spot.
        at = max(cursor.selectionEnd(), cursor.selectionStart() + 1)
        rects = _selection_rects(
            doc, cursor.selectionStart(), cursor.selectionEnd(),
            page_w, page_h, count,
        )
        for page, boxes in rects.items():
            matches.append({"page": page, "rects": boxes})
        if len(matches) >= max_hits:
            return {"matches": matches[:max_hits], "capped": True}
    return {"matches": matches, "capped": False}


def _selection_rects(doc, start: int, end: int, page_w: int, page_h: int,
                     count: int) -> dict:
    """{page: [[x, y, w, h], ...]} for one selection, in page pixels.

    A match that wraps gets one rectangle per line it occupies, the way the
    PDF path does it — a single bounding box would be a slab covering the
    gap between the lines as well.
    """
    layout_of = doc.documentLayout()
    out = {}
    block = doc.findBlock(start)
    while block.isValid() and block.position() < end:
        layout = block.layout()
        # The block's own origin in document coordinates. cursorToX is
        # measured from the *layout*, so without this every rectangle lands
        # one page margin to the left of the words it belongs to.
        origin = layout_of.blockBoundingRect(block).topLeft()
        first = max(start - block.position(), 0)
        last = min(end - block.position(), block.length() - 1)
        line = layout.lineForTextPosition(first)
        if not line.isValid():
            block = block.next()
            continue
        for number in range(line.lineNumber(), layout.lineCount()):
            current = layout.lineAt(number)
            line_start = current.textStart()
            line_end = line_start + current.textLength()
            if line_start >= last:
                break
            begin, finish = max(first, line_start), min(last, line_end)
            if finish <= begin:
                continue
            x1 = origin.x() + current.cursorToX(begin)[0]
            x2 = origin.x() + current.cursorToX(finish)[0]
            y = origin.y() + current.y()
            page = int(y // page_h)
            if not 0 <= page < count:
                continue
            height = current.height()
            y_in_page = y - page * page_h
            # A line sitting on a page boundary is drawn on one page only;
            # clamp rather than paint half a highlight off the bottom.
            height = min(height, page_h - y_in_page)
            if height <= 0:
                continue
            out.setdefault(page, []).append([
                round(min(x1, x2)), round(y_in_page),
                max(1, round(abs(x2 - x1))), max(1, round(height)),
            ])
        block = block.next()
    return out


def _epub_chapters(doc, toc: list, positions: dict, headings: dict,
                   page_h: int, count: int) -> list:
    """Table of contents entries as [{title, level, page}, ...].

    A target that was never laid out (past the size budget, or a file the
    spine does not include) is dropped rather than guessed at, and so is one
    that lands past the last rendered page: a sidebar row that scrolls
    nowhere is worse than no row.
    """
    layout = doc.documentLayout()

    def place(position: int) -> tuple:
        """(page, offset down that page) for a document position."""
        block = doc.findBlock(position)
        if not block.isValid():
            return -1, 0
        top = layout.blockBoundingRect(block).top()
        page = int(top // page_h)
        return page, int(top - page * page_h)

    entries = []
    for entry in toc[:EPUB_MAX_TOC]:
        target = entry["target"]
        position = positions.get(target)
        if position is None:  # a fragment inside a chapter we did not split
            position = positions.get(target.split("#", 1)[0])
        if position is None:
            continue
        page, y = place(position)
        if 0 <= page < count:
            entries.append({
                "title": entry["title"][:OUTLINE_MAX_TITLE],
                "level": min(entry["level"], 5), "page": page, "y": y,
            })
    if entries:
        return entries
    # No usable table of contents — most books have one, but a hand-rolled
    # EPUB may not. The spine still gives a chapter list: each file's first
    # heading, or its name when it has none.
    for member, position in positions.items():
        page, y = place(position)
        if 0 <= page < count:
            entries.append({
                "title": (headings.get(member)
                          or member.rsplit("/", 1)[-1])[:OUTLINE_MAX_TITLE],
                "level": 0, "page": page, "y": y,
            })
    return entries[:EPUB_MAX_TOC]


def _epub_parts(zf, names) -> tuple:
    """(spine members, toc entries, book title) for an open EPUB."""
    import posixpath

    opf = _epub_opf_path(zf, names)
    base = posixpath.dirname(opf)
    root = _member_xml(zf, opf)

    manifest, title = {}, ""
    for node in root.iter():
        tag = _tag(node)
        if tag == "item":
            manifest[node.get("id")] = (
                _zip_path(base, node.get("href", "")),
                node.get("media-type", ""),
                node.get("properties", "") or "",
            )
        elif tag == "title" and not title and node.text:
            title = node.text.strip()[:200]

    spine, toc_id = [], None
    for node in root.iter():
        if _tag(node) != "spine":
            continue
        toc_id = node.get("toc")
        for ref in node:
            if _tag(ref) != "itemref":
                continue
            item = manifest.get(ref.get("idref"))
            # Only the readable documents: a spine may also list an SVG
            # cover, which has no text to lay out.
            if item and item[0] in names and "html" in item[1]:
                spine.append(item[0])
        break

    return spine, _epub_toc(zf, names, manifest, toc_id), title


def _epub_toc(zf, names, manifest: dict, toc_id) -> list:
    """[{title, level, target}, ...] from the EPUB 3 nav doc or the EPUB 2
    NCX, whichever the book carries. Targets are "member" or "member#id"."""
    nav = next(
        (path for path, _media, props in manifest.values()
         if "nav" in props.split() and path in names),
        None,
    )
    if nav:
        try:
            return _epub_nav_toc(zf, nav)
        except Exception as exc:  # noqa: BLE001
            print("epub: unreadable nav (%s)" % exc, file=_stderr())
    ncx = None
    if toc_id and toc_id in manifest:
        ncx = manifest[toc_id][0]
    if ncx is None:
        ncx = next(
            (path for path, media, _props in manifest.values()
             if "dtbncx" in media and path in names),
            None,
        )
    if ncx and ncx in names:
        try:
            return _epub_ncx_toc(zf, ncx)
        except Exception as exc:  # noqa: BLE001
            print("epub: unreadable ncx (%s)" % exc, file=_stderr())
    return []


def _epub_nav_toc(zf, member: str) -> list:
    """EPUB 3: <nav epub:type="toc"><ol><li><a href=…>Title</a>…"""
    import posixpath

    root = _epub_dom(zf, member)
    base = posixpath.dirname(member)
    navs = [n for n in root.iter() if _tag(n) == "nav"]
    chosen = next(
        (n for n in navs
         if "toc" in (n.get("{http://www.idpf.org/2007/ops}type") or "")),
        navs[0] if navs else None,
    )
    if chosen is None:
        return []
    out = []

    def walk(node, level: int):
        for item in node:
            if _tag(item) != "li" or len(out) >= EPUB_MAX_TOC:
                continue
            link = next((c for c in item.iter() if _tag(c) == "a"), None)
            if link is not None and link.get("href"):
                text = " ".join("".join(link.itertext()).split())
                if text:
                    out.append({
                        "title": text, "level": level,
                        "target": _zip_target(base, link.get("href")),
                    })
            for child in item:
                if _tag(child) in ("ol", "ul"):
                    walk(child, level + 1)

    for node in chosen:
        if _tag(node) in ("ol", "ul"):
            walk(node, 0)
    return out


def _epub_ncx_toc(zf, member: str) -> list:
    """EPUB 2: <navMap><navPoint><navLabel><text>…, nested for subsections."""
    import posixpath

    root = _member_xml(zf, member)
    base = posixpath.dirname(member)
    out = []

    def walk(node, level: int):
        for point in node:
            if _tag(point) != "navpoint" or len(out) >= EPUB_MAX_TOC:
                continue
            label = next(
                (c for c in point.iter() if _tag(c) == "text"), None
            )
            content = next(
                (c for c in point.iter() if _tag(c) == "content"), None
            )
            if label is not None and content is not None and content.get("src"):
                text = " ".join("".join(label.itertext()).split())
                if text:
                    out.append({
                        "title": text, "level": level,
                        "target": _zip_target(base, content.get("src")),
                    })
            walk(point, level + 1)

    for node in root.iter():
        if _tag(node) == "navmap":
            walk(node, 0)
            break
    return out


def _epub_opf_path(zf, names) -> str:
    """The package document, from META-INF/container.xml."""
    if "META-INF/container.xml" in names:
        root = _member_xml(zf, "META-INF/container.xml")
        for node in root.iter():
            if _tag(node) == "rootfile" and node.get("full-path") in names:
                return node.get("full-path")
    # A container that does not say (or lies): take the one package
    # document in the archive rather than refusing to open the book.
    opfs = sorted(n for n in names if n.lower().endswith(".opf"))
    if opfs:
        return opfs[0]
    raise RuntimeError("no package document")


def _tag(node) -> str:
    """Local name of an element, namespace and case dropped."""
    tag = node.tag
    if not isinstance(tag, str):  # a comment or a processing instruction
        return ""
    return tag.rsplit("}", 1)[-1].lower()


def _zip_path(base: str, href: str) -> str:
    """An href inside the book, as the zip member it names."""
    import posixpath
    import urllib.parse

    href = urllib.parse.unquote((href or "").split("#", 1)[0])
    if not href:
        return ""
    path = posixpath.normpath(posixpath.join(base, href))
    return path.lstrip("./")


def _zip_target(base: str, href: str) -> str:
    """Same, but keeping the fragment: "text/ch1.xhtml#part2"."""
    import urllib.parse

    raw, _, fragment = (href or "").partition("#")
    path = _zip_path(base, raw)
    return path + "#" + urllib.parse.unquote(fragment) if fragment else path


def _epub_dom(zf, member: str):
    """Parse one XHTML member, with HTML named entities resolved first.

    Books are full of &nbsp; and &mdash;, which are HTML entities that no
    XML parser is required to know: left alone they abort the parse of an
    otherwise perfectly good chapter.
    """
    import re
    from html.entities import html5
    from xml.etree import ElementTree as ET

    info = zf.getinfo(member)
    if info.file_size > OFFICE_MAX_MEMBER_BYTES:
        raise RuntimeError("%s is implausibly large" % member)
    with zf.open(member) as fh:
        text = fh.read(OFFICE_MAX_MEMBER_BYTES).decode(
            "utf-8", errors="replace"
        )

    def entity(match):
        name = match.group(1)
        if name in ("amp;", "lt;", "gt;", "quot;", "apos;"):
            return match.group(0)  # XML knows these five
        value = html5.get(name)
        return value if value is not None else ""

    text = re.sub(r"&([a-zA-Z][a-zA-Z0-9]{1,31};)", entity, text)
    # A DOCTYPE pointing at an external DTD is common and harmless, but ET
    # will not fetch it — and must not be asked to, in here.
    return ET.fromstring(text)


def _epub_chunks(zf, member: str, images: dict, wanted: set,
                 headings: dict) -> list:
    """[(anchor, html), ...] for one chapter.

    Normally one chunk per file, anchored on the file itself. A book that
    keeps several chapters in one XHTML document and points its table of
    contents at fragments inside it gets one chunk per referenced id, so
    those entries still land on the page they name rather than at the top of
    the file.
    """
    import posixpath

    root = _epub_dom(zf, member)
    body = next((n for n in root.iter() if _tag(n) == "body"), root)
    base = posixpath.dirname(member)
    chunks, buf, current = [], [], member

    def flush(anchor: str):
        nonlocal current
        chunks.append((current, "".join(buf)))
        buf.clear()
        current = anchor

    def walk(node):
        tag = _tag(node)
        if tag in _EPUB_SKIP:
            return
        ident = node.get("id")
        if ident:
            key = "%s#%s" % (member, ident)
            if key in wanted and buf:
                flush(key)
        if tag == "img" or tag == "image":
            _epub_image(zf, base, node, images, buf)
            return
        open_tag, close_tag = _EPUB_TAGS.get(tag, ("", ""))
        buf.append(open_tag)
        if node.text:
            buf.append(_escape(node.text))
        if tag in _HEADINGS and member not in headings:
            text = " ".join("".join(node.itertext()).split())
            if text:
                headings[member] = text
        for child in node:
            walk(child)
            if child.tail:
                buf.append(_escape(child.tail))
        buf.append(close_tag)

    walk(body)
    flush("")
    return chunks


def _epub_image(zf, base: str, node, images: dict, buf: list):
    """Embed a chapter image, bounded in count and size."""
    href = (
        node.get("src")
        or node.get("{http://www.w3.org/1999/xlink}href")
        or node.get("href")
    )
    member = _zip_path(base, href or "")
    if not member or len(images) >= EPUB_MAX_IMAGES:
        return
    if member not in images and not _stash_image(zf, member, images):
        return
    buf.append("<img src='%s'>" % member)
