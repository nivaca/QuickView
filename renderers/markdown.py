# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Mustapha Alioglou
# Copyright (C) 2026 Nicolas Vaughan <nivaca@fastmail.com>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Markdown laid out as pages, with its headings as contents."""

from .base import (
    DEFAULT_READING_FONT_SIZE,
    reading_font,
    OUTLINE_MAX_TITLE,
    PAGE_RATIO,
    _rewound,
)
from .epub import (
    book_theme,
    DEFAULT_BOOK_THEME,
    EPUB_MAX_TOC,
)
from .office import (
    _document_pages,
)


# ---------------------------------------------------------------- markdown
# Qt parses Markdown itself (md4c, behind QTextDocument.setMarkdown), so a
# rendered preview needs no library and no HTML engine — but the parse is a
# parse, and it happens in here rather than in the daemon like every other
# one. What comes back is page images, so Markdown scrolls, caches and
# streams exactly like a PDF.
MARKDOWN_MAX_BYTES = 2 * 1024 * 1024


def markdown_pages(fd: int, name: str, page_w: int, max_pages: int,
                   start: int = 0, theme: str = DEFAULT_BOOK_THEME,
                   scale: float = 1.0, font: str = "",
                   font_size: int = DEFAULT_READING_FONT_SIZE):
    """Yield (info, png_bytes) for a Markdown file, rendered as pages.

    info is {"count", "chapters"} and is the same dict on every page, like
    the EPUB path: the headings are a property of the layout that produced
    the pages, so the sidebar can be built from the first frame.
    """
    from PySide6.QtCore import QSizeF
    from PySide6.QtGui import QTextDocument

    with _rewound(fd) as fh:
        data = fh.read(MARKDOWN_MAX_BYTES)
    text = data.decode("utf-8", errors="replace")
    if not text.strip():
        raise RuntimeError("empty document")

    page_h = int(page_w * PAGE_RATIO)
    palette = book_theme(theme)
    doc = QTextDocument()
    doc.setDocumentMargin(page_w * 0.06)
    # "" keeps Qt's default family; code blocks keep their fixed pitch
    # either way, as they carry it in their own character format.
    family, size = reading_font(font, font_size)
    base = doc.defaultFont()
    if family:
        base.setFamily(family)
    base.setPointSize(size)
    doc.setDefaultFont(base)
    # The GitHub dialect is the one people actually write: tables, task
    # lists, strikethrough, fenced code.
    doc.setMarkdown(
        _strip_markdown_html(text),
        QTextDocument.MarkdownFeature.MarkdownDialectGitHub,
    )
    _theme_markdown(doc, palette)
    _label_markdown_images(doc, palette)
    doc.setPageSize(QSizeF(page_w, page_h))
    count = min(doc.pageCount(), max_pages)
    info = {"count": count, "chapters": _markdown_headings(doc, page_h, count)}
    for _n, png in _document_pages(doc, page_w, page_h, count, start,
                                   palette["bg"], scale):
        yield info, png


def _markdown_headings(doc, page_h: int, count: int) -> list:
    """The document's headings as sidebar entries, with page numbers.

    A Markdown file has no table of contents of its own — its headings are
    the table of contents, which is what every reader that shows one does
    with them. Levels come straight from the hashes, so ## sits under #.
    """
    layout = doc.documentLayout()
    out = []
    block = doc.begin()
    while block.isValid() and len(out) < EPUB_MAX_TOC:
        level = block.blockFormat().headingLevel()
        title = " ".join(block.text().split())
        if level and title:
            top = layout.blockBoundingRect(block).top()
            page = int(top // page_h)
            if 0 <= page < count:
                out.append({
                    "title": title[:OUTLINE_MAX_TITLE],
                    "level": min(level - 1, 5),  # "#" is the top level
                    "page": page,
                    # Where on the page, not just which page: a page is
                    # taller than the window, so a heading halfway down one
                    # must scroll halfway down it.
                    "y": int(top - page * page_h),
                })
        block = block.next()
    return out


def _strip_markdown_html(text: str) -> str:
    """Remove raw HTML tags, outside code, before Qt parses the document.

    Qt hands an HTML block to its own rich-text importer mid-parse, and an
    unbalanced one — a `<p align="center">` wrapping two `<img>` tags is the
    canonical README opening — swallows the rest of the file: this project's
    own README imported as 2,420 characters of the 22,222 it has, with every
    paragraph after the block silently gone. Dropping the tags costs the
    badges and centred images (which could not be loaded in here anyway,
    see _label_markdown_images) and keeps the document.

    Fenced blocks and inline code are left alone: a README that documents
    HTML should still show it.
    """
    import re

    tag = re.compile(r"<[^>\n]{0,300}>")
    out, fence = [], None
    for line in text.splitlines():
        stripped = line.lstrip()
        if fence is not None:
            out.append(line)
            if stripped.startswith(fence):
                fence = None
            continue
        if stripped.startswith("```") or stripped.startswith("~~~"):
            fence = stripped[:3]
            out.append(line)
            continue
        # Odd-numbered segments are inside `backticks` and keep their text.
        parts = line.split("`")
        out.append("`".join(
            part if index % 2 else tag.sub("", part)
            for index, part in enumerate(parts)
        ))
    return "\n".join(out)


def _theme_markdown(doc, palette: dict):
    """Recolour a parsed Markdown document to the page palette.

    setMarkdown builds the document directly rather than through the CSS
    engine, so a default style sheet does not reach it — the colours have to
    be merged onto the text afterwards. Without this the document renders in
    whatever the worker's Qt palette happens to be, which on a dark page is
    black text on a dark background.
    """
    from PySide6.QtGui import (
        QColor, QTextBlockFormat, QTextCharFormat, QTextCursor,
        QTextFrameFormat, QTextLength,
    )

    body = QTextCharFormat()
    body.setForeground(QColor(palette["fg"]))
    everything = QTextCursor(doc)
    everything.select(QTextCursor.SelectionType.Document)
    everything.mergeCharFormat(body)

    code_bg = _mix(palette["bg"], palette["muted"], 0.18)
    block = doc.begin()
    while block.isValid():
        fmt = block.blockFormat()
        whole = QTextCursor(block)
        whole.select(QTextCursor.SelectionType.BlockUnderCursor)
        if fmt.nonBreakableLines():
            # Fenced code is imported as unbreakable lines, which a page
            # cannot scroll sideways to show: a long line is simply cut off
            # at the margin. Wrapping it reads slightly wrong; losing half
            # of it reads as a bug.
            wrapped = QTextBlockFormat(fmt)
            wrapped.setNonBreakableLines(False)
            QTextCursor(block).setBlockFormat(wrapped)
        if fmt.headingLevel():
            heading = QTextCharFormat()
            heading.setForeground(QColor(palette["head"]))
            whole.mergeCharFormat(heading)
        elif fmt.leftMargin() > 0 and block.textList() is None:
            # An indented block that is not a list item is a blockquote —
            # the importer marks it with a margin and nothing else.
            quote = QTextCharFormat()
            quote.setForeground(QColor(palette["muted"]))
            quote.setFontItalic(True)
            whole.mergeCharFormat(quote)
        for fragment in _fragments(block):
            char = fragment.charFormat()
            span = QTextCursor(doc)
            span.setPosition(fragment.position())
            span.setPosition(
                fragment.position() + fragment.length(),
                QTextCursor.MoveMode.KeepAnchor,
            )
            if char.isAnchor():
                # Links keep their underline but take the page's accent:
                # Qt's default blue is unreadable on half of these palettes.
                link = QTextCharFormat()
                link.setForeground(QColor(palette["head"]))
                link.setFontUnderline(True)
                span.mergeCharFormat(link)
            elif char.fontFixedPitch():
                code = QTextCharFormat()
                code.setBackground(code_bg)
                span.mergeCharFormat(code)
        block = block.next()

    # Markdown tables arrive with no width of their own and collapse to
    # whatever their content forces, which is unreadable at any page size.
    for frame in doc.rootFrame().childFrames():
        if not hasattr(frame, "columns"):
            continue  # not a table
        table = frame.format().toTableFormat()
        table.setWidth(QTextLength(QTextLength.Type.PercentageLength, 100))
        table.setCellPadding(6)
        table.setCellSpacing(0)
        table.setBorder(1)
        table.setBorderBrush(QColor(palette["muted"]))
        table.setBorderStyle(QTextFrameFormat.BorderStyle.BorderStyle_Solid)
        frame.setFormat(table)


def _label_markdown_images(doc, palette: dict):
    """Replace every image with a note naming it.

    A Markdown file's images sit next to it on disk, and the jail has no
    disk — the file arrives as a descriptor and nothing else. Qt would
    resolve those relative paths against the worker's working directory,
    which means an image loads only when the document happens to live
    inside this application's own folder: right for the project's README,
    wrong for every file a person actually previews. Naming the image is
    the honest version of that, and it is the same everywhere.

    Applied after the recolouring above, whose select-all would otherwise
    take the colour back off these labels.
    """
    from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor

    found = []
    block = doc.begin()
    while block.isValid():
        for fragment in _fragments(block):
            if fragment.charFormat().isImageFormat():
                name = fragment.charFormat().toImageFormat().name() or ""
                found.append((fragment.position(), fragment.length(), name))
        block = block.next()

    label = QTextCharFormat()
    label.setForeground(QColor(palette["muted"]))
    label.setFontItalic(True)
    # Back to front: every replacement moves the positions after it.
    for position, length, name in reversed(found):
        cursor = QTextCursor(doc)
        cursor.setPosition(position)
        cursor.setPosition(position + length, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(
            "[image: %s]" % (name.rsplit("/", 1)[-1] or "unnamed"), label
        )


def _fragments(block) -> list:
    """The text fragments of one block, as a list (the iterator is a C++
    one and does not survive the formatting done to what it points at)."""
    out = []
    it = block.begin()
    while not it.atEnd():
        fragment = it.fragment()
        if fragment.isValid():
            out.append(fragment)
        it += 1
    return out


def _mix(base: str, other: str, ratio: float):
    """base blended ratio-of-the-way towards other."""
    from PySide6.QtGui import QColor

    first, second = QColor(base), QColor(other)
    return QColor(
        round(first.red() * (1 - ratio) + second.red() * ratio),
        round(first.green() * (1 - ratio) + second.green() * ratio),
        round(first.blue() * (1 - ratio) + second.blue() * ratio),
    )
