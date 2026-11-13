# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Mustapha Alioglou
# Copyright (C) 2026 Nicolas Vaughan <nivaca@fastmail.com>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Office documents as pages: through LibreOffice, or laid out here."""

from .base import (
    _encode,
    OFFICE_MAX_MEMBER_BYTES,
    OFFICE_MAX_THUMB_BYTES,
    PAGE_RATIO,
    PDF_TEXT_MAX_CHARS,
    PDF_TEXT_MAX_WORDS,
    _rewound,
)
from .pdf import (
    _scaled_px,
)
from .suite import (
    office_suite,
    _pages_via_office_suite,
)


def office_preview(fd: int, name: str, limit: int) -> dict:
    """Preview an OOXML or ODF document without an office suite.

    Both are zip containers, so the standard library is enough. Prefers the
    thumbnail the authoring application already embedded — that is its own
    rendering of page one for the cost of unzipping one member — and falls
    back to the document's text.
    """
    import zipfile

    out = {"kind": "empty", "image_b64": None, "image_type": None,
           "text": "", "truncated": False}
    with _rewound(fd) as fh:
        if not zipfile.is_zipfile(fh):
            raise RuntimeError("not an office document (no zip container)")
        fh.seek(0)
        with zipfile.ZipFile(fh) as zf:
            names = set(zf.namelist())
            thumb = _embedded_thumbnail(zf, names)
            if thumb is not None:
                import base64

                data, kind = thumb
                out["kind"] = "image"
                out["image_b64"] = base64.b64encode(data).decode("ascii")
                out["image_type"] = kind
            text = _office_text(zf, names, limit)
            if text:
                out["text"] = text[:limit]
                out["truncated"] = len(text) > limit
                if out["kind"] != "image":
                    out["kind"] = "text"
    if out["kind"] == "empty":
        raise RuntimeError("nothing previewable in this document")
    return out


def _embedded_thumbnail(zf, names):
    for member, kind in (
        ("docProps/thumbnail.jpeg", "jpeg"),
        ("docProps/thumbnail.jpg", "jpeg"),
        ("docProps/thumbnail.png", "png"),
        ("Thumbnails/thumbnail.png", "png"),
    ):
        if member not in names:
            continue
        info = zf.getinfo(member)
        if info.file_size > OFFICE_MAX_THUMB_BYTES:
            continue
        with zf.open(member) as fh:
            return fh.read(OFFICE_MAX_THUMB_BYTES), kind
    return None


def _member_xml(zf, member: str):
    """Parse one zip member as XML, bounded, with entities left unresolved."""
    from xml.etree import ElementTree as ET

    info = zf.getinfo(member)
    if info.file_size > OFFICE_MAX_MEMBER_BYTES:
        raise RuntimeError("%s is implausibly large" % member)
    with zf.open(member) as fh:
        data = fh.read(OFFICE_MAX_MEMBER_BYTES)
    # ET's parser does not expand external entities and caps internal ones,
    # so a billion-laughs document fails here rather than eating the worker.
    return ET.fromstring(data)


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


SS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


ODF_TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"


def _office_text(zf, names, limit: int) -> str:
    if "word/document.xml" in names:
        root = _member_xml(zf, "word/document.xml")
        return "\n".join(
            "".join(node.text or "" for node in para.iter(W + "t"))
            for para in root.iter(W + "p")
        )
    if any(n.startswith("ppt/slides/slide") for n in names):
        slides = sorted(
            n for n in names
            if n.startswith("ppt/slides/slide") and n.endswith(".xml")
        )
        chunks, size = [], 0
        for i, slide in enumerate(slides, 1):
            root = _member_xml(zf, slide)
            body = " ".join(
                node.text or "" for node in root.iter(A + "t")
            ).strip()
            chunks.append("—— slide %d ——\n%s" % (i, body))
            size += len(chunks[-1])
            if size > limit:
                break
        return "\n\n".join(chunks)
    if "xl/workbook.xml" in names:
        shared = []
        if "xl/sharedStrings.xml" in names:
            root = _member_xml(zf, "xl/sharedStrings.xml")
            shared = [
                "".join(node.text or "" for node in item.iter(SS + "t"))
                for item in root.iter(SS + "si")
            ]
        sheets = sorted(
            n for n in names
            if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")
        )
        rows, size = [], 0
        for sheet in sheets:
            root = _member_xml(zf, sheet)
            for row in root.iter(SS + "row"):
                cells = []
                for cell in row.iter(SS + "c"):
                    value = cell.find(SS + "v")
                    if value is None or value.text is None:
                        cells.append("")
                    elif cell.get("t") == "s":
                        # A shared-string cell should hold an integer index;
                        # a malformed one must cost that cell, not the whole
                        # document's preview.
                        try:
                            index = int(value.text)
                        except ValueError:
                            cells.append("")
                            continue
                        cells.append(
                            shared[index] if 0 <= index < len(shared) else ""
                        )
                    else:
                        cells.append(value.text)
                rows.append("\t".join(cells))
                size += len(rows[-1])
                if size > limit:
                    return "\n".join(rows)
        return "\n".join(rows)
    if "content.xml" in names:  # ODF
        root = _member_xml(zf, "content.xml")
        return "\n".join(
            "".join(node.itertext()).strip()
            for node in root.iter(ODF_TEXT + "p")
        )
    return ""


def office_pages(fd: int, name: str, page_w: int, max_pages: int, start: int = 0,
                 engine: str = "libreoffice", scale: float = 1.0):
    """Yield (page_count, png_bytes) for an office document, as page images.

    A document or slide deck goes to LibreOffice when the system has one —
    see _office_suite_kind for which, legacy binary formats and RTF
    included: converted to PDF in here, in the jail, and rendered by the PDF
    path, so the preview has the document's real fonts, image sizes and
    positions, text wrap, headers and EMF logos, and a deck has one page per
    slide. ~1.3 s where the fallback is ~15 ms, which is the price of
    looking like the document rather than like its text.

    Otherwise — no LibreOffice, a spreadsheet, or a conversion that failed —
    the document is converted to the HTML subset QTextDocument understands
    and laid out here: no office suite, no subprocess, ~8 ms to convert and
    ~7 ms a page. Slide decks and the binary formats have no path through
    that — a deck's content is absolutely positioned graphics, which
    QTextDocument cannot lay out — so they raise, and the caller falls back
    to the thumbnail a deck embeds plus its text, or to the metadata card.

    engine "builtin" skips LibreOffice even where it is installed: the
    office_engine setting, for people who would rather have the preview now
    than have it exact.
    """
    import sys

    if engine != "builtin" and office_suite():
        sent = False
        try:
            for item in _pages_via_office_suite(fd, page_w, max_pages, start,
                                                scale):
                sent = True
                yield item
            if sent:
                return
        except Exception as exc:
            if sent:
                raise  # pages already out: a fallback would repeat them
            print("office suite: %s — using the built-in layout" % exc,
                  file=sys.stderr)
    yield from _pages_via_qtextdocument(fd, name, page_w, max_pages, start,
                                        scale)


def _pages_via_qtextdocument(fd: int, name: str, page_w: int, max_pages: int,
                             start: int = 0, scale: float = 1.0):
    import zipfile

    from PySide6.QtCore import QSizeF, QUrl
    from PySide6.QtGui import QImage, QTextDocument

    page_h = int(page_w * PAGE_RATIO)
    with _rewound(fd) as fh:
        if not zipfile.is_zipfile(fh):
            raise RuntimeError("not an office document")
        fh.seek(0)
        with zipfile.ZipFile(fh) as zf:
            names = set(zf.namelist())
            body, images = _office_html(zf, names, page_w)
            if not body:
                raise RuntimeError("no layout for this document type")

            doc = QTextDocument()
            doc.setDocumentMargin(page_w * 0.06)
            for key, data in images.items():
                img = QImage.fromData(data)
                if not img.isNull():
                    doc.addResource(
                        QTextDocument.ResourceType.ImageResource,
                        QUrl(key), img,
                    )
            doc.setHtml(body)
            doc.setPageSize(QSizeF(page_w, page_h))
            count = min(doc.pageCount(), max_pages)
            yield from _document_pages(doc, page_w, page_h, count, start,
                                       scale=scale)


def _document_pages(doc, page_w: int, page_h: int, count: int, start: int,
                    background: str = "#ffffff", scale: float = 1.0):
    """Yield (count, png) for a laid-out QTextDocument, page by page.

    Shared by the office and EPUB paths: both end up with one long document
    that is sliced into page-sized images here, so a book and a report are
    cut, painted and counted by the same code.
    """
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QImage, QPainter

    colour = QColor(background)
    if not colour.isValid():
        colour = QColor("#ffffff")
    # The layout stays at page_w — that is what the headings, chapters and
    # search positions are measured in — and only the painting is scaled,
    # so a 1.5x screen gets the same page with 1.5x the pixels.
    sw, sh, used = _scaled_px(page_w, page_h, scale)
    for index in range(max(start, 0), count):
        page = QImage(sw, sh, QImage.Format.Format_RGB32)
        page.fill(colour)
        painter = QPainter(page)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.scale(sw / page_w, sh / page_h)
        painter.translate(0, -index * page_h)
        painter.setClipRect(QRectF(0, index * page_h, page_w, page_h))
        doc.drawContents(painter, QRectF(0, index * page_h, page_w, page_h))
        painter.end()
        page.setText("QuickView:PageCount", str(doc.pageCount()))
        page.setText("QuickView:Scale", "%.4f" % used)
        yield count, _encode(page)


def document_text(doc, pages: list, page_w: int, page_h: int,
                  count: int) -> dict:
    """The selectable text of some pages of a laid-out QTextDocument.

    The same answer as pdf.page_text — {"pages": [{"page", "text",
    "words": [[start, end, x, y, w, h, line], ...]}], "engine"} — so the
    daemon selects over a book or a Markdown file with the code it uses
    for a PDF. The boxes come from the layout the pages were painted
    from, in page pixels at page_w, so they sit on the words drawn.

    A line wrapped inside a paragraph is joined to the next with a space,
    and paragraphs (and table cells, list items, headings) end with a
    newline, which is how the text reads when copied; the cells of a
    table row are separated by tabs.
    """
    import re

    wanted = sorted({p for p in pages
                     if isinstance(p, int) and not isinstance(p, bool)
                     and 0 <= p < count})
    if not wanted:
        return {"pages": [], "engine": "layout"}
    from PySide6.QtGui import QTextCursor

    acc = {p: {"text": [], "len": 0, "words": [], "lines": 0,
               "block": None, "row": None, "full": False} for p in wanted}
    top, bottom = wanted[0] * page_h, (wanted[-1] + 1) * page_h
    layout_of = doc.documentLayout()
    word_re = re.compile(r"\S+")
    block = doc.begin()
    while block.isValid():
        rect = layout_of.blockBoundingRect(block)
        if rect.bottom() < top or rect.top() >= bottom:
            block = block.next()
            continue
        layout = block.layout()
        origin = rect.topLeft()
        # Cells of one table row are copied on one line, a tab apart, as
        # a spreadsheet pastes them.
        row = None
        table = QTextCursor(block).currentTable()
        if table is not None:
            cell = table.cellAt(block.position())
            row = (table.firstPosition(), cell.row())
        # An image or other embedded object is one U+FFFC character: a
        # picture, not a word.
        text = block.text().replace("\ufffc", " ")
        for number in range(layout.lineCount()):
            line = layout.lineAt(number)
            y = origin.y() + line.y()
            page = int(y // page_h)
            a = acc.get(page)
            if a is None or a["full"]:
                continue
            first = line.textStart()
            found = list(word_re.finditer(text, first, first + line.textLength()))
            if not found:
                continue
            if a["len"]:
                if a["block"] == block.blockNumber():
                    sep = " "
                elif row is not None and a["row"] == row:
                    sep = "\t"
                else:
                    sep = "\n"
                a["text"].append(sep)
                a["len"] += 1
            a["block"], a["row"] = block.blockNumber(), row
            y_in_page = y - page * page_h
            height = max(1, round(min(line.height(), page_h - y_in_page)))
            for k, match in enumerate(found):
                word = match.group()
                if (a["len"] + 1 + len(word) > PDF_TEXT_MAX_CHARS
                        or len(a["words"]) >= PDF_TEXT_MAX_WORDS):
                    a["full"] = True
                    break
                if k:
                    a["text"].append(" ")
                    a["len"] += 1
                x1 = origin.x() + line.cursorToX(match.start())[0]
                x2 = origin.x() + line.cursorToX(match.end())[0]
                x1, x2 = min(x1, x2), max(x1, x2)  # right-to-left runs
                a["words"].append([a["len"], a["len"] + len(word), round(x1),
                                   round(y_in_page), max(1, round(x2 - x1)),
                                   height, a["lines"]])
                a["text"].append(word)
                a["len"] += len(word)
            a["lines"] += 1
        block = block.next()
    return {"pages": [{"page": p, "text": "".join(acc[p]["text"]),
                       "words": acc[p]["words"]} for p in wanted],
            "engine": "layout"}


def _office_html(zf, names, page_w: int = 900) -> tuple:
    """(html, images) for the document types QTextDocument can lay out."""
    if "word/document.xml" in names:
        return _docx_html(zf, names, page_w)
    if "xl/workbook.xml" in names:
        return _xlsx_html(zf, names), {}
    if "content.xml" in names and "styles.xml" in names and not _odf_deck(zf, names):
        return _odf_html(zf, names)
    return "", {}  # slide decks land here: nothing to lay out, only a thumbnail


def _odf_deck(zf, names) -> bool:
    """An ODF presentation or drawing: frames on a canvas, not running text.

    Read as text it comes out as every text box in a column, which looks
    like a broken document; its embedded thumbnail looks like the deck.
    """
    if "mimetype" not in names:
        return False
    with zf.open("mimetype") as m:
        kind = m.read(64).strip()
    return kind.startswith((b"application/vnd.oasis.opendocument.presentation",
                            b"application/vnd.oasis.opendocument.graphics"))


_HTML_HEAD = (
    "<body style='font-family:serif; font-size:11pt; color:#111;'>"
)


def _escape(text: str) -> str:
    import html

    return html.escape(text or "")


# The built-in .docx layout: what a machine without LibreOffice sees. It is
# an approximation by design — QTextDocument has no floats, no text wrap, no
# headers and no EMF — so the aim is the things it *can* show faithfully:
# image sizes, alignment, indents, run formatting and page breaks.
_DOCX_WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"


_DOCX_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


_DOCX_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


_DOCX_V = "{urn:schemas-microsoft-com:vml}"


_DOCX_MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"


_DOCX_PAGE_IN = 210 / 25.4  # the page is laid out as A4, 8.27 in wide


# Vector formats Qt has no reader for. Leaving them out is better than the
# empty frame a failed <img> leaves in the layout.
_DOCX_NO_RASTER = (".emf", ".wmf", ".emz", ".wmz", ".svm")


_DOCX_PAGE_BREAK = "\0page\0"


class _DocxContext:
    """What every paragraph needs: the package, its images, and the scale."""

    def __init__(self, zf, names, page_w: int):
        self.zf = zf
        self.images = {}
        self.ppi = page_w / _DOCX_PAGE_IN
        # Room between the margins that _pages_via_qtextdocument sets.
        self.max_img_w = page_w * 0.88 - 8
        self.rels = _docx_rels(zf, names)
        self.styles, self.size_pt, self.font = _docx_styles(zf, names)

    def px(self, inches: float) -> int:
        return max(0, round(inches * self.ppi))


def _docx_rels(zf, names) -> dict:
    """Relationship id -> package member, for the images a run can embed."""
    import posixpath

    rels = {}
    if "word/_rels/document.xml.rels" not in names:
        return rels
    for rel in _member_xml(zf, "word/_rels/document.xml.rels"):
        if rel.get("TargetMode") == "External":
            continue  # a URL: the jail has no network, and wants none
        target = rel.get("Target", "")
        if target.startswith("/"):
            member = target.lstrip("/")
        else:
            member = posixpath.normpath(posixpath.join("word", target))
        if member in names:
            rels[rel.get("Id")] = member
    return rels


def _docx_styles(zf, names) -> tuple:
    """(styleId -> lower-case style name, body size in pt, body font).

    The id is not the name: a Greek or German Word writes ids like "1" or
    "berschrift1" for what styles.xml calls "heading 1", and it is the name
    that is stable across languages. The body size and font come from the
    document defaults, overridden by the default paragraph style, which is
    where Word keeps them.
    """
    out, size, font = {}, 11.0, ""
    if "word/styles.xml" not in names:
        return out, size, font
    root = _member_xml(zf, "word/styles.xml")

    def take(rpr):
        nonlocal size, font
        if rpr is None:
            return
        sz = _docx_val(rpr, W + "sz")
        if sz and sz.isdigit() and 8 <= int(sz) <= 200:
            size = int(sz) / 2
        fonts = rpr.find(W + "rFonts")
        if fonts is not None and (fonts.get(W + "ascii") or fonts.get(W + "hAnsi")):
            font = fonts.get(W + "ascii") or fonts.get(W + "hAnsi")

    take(root.find(W + "docDefaults/" + W + "rPrDefault/" + W + "rPr"))
    for style in root.iter(W + "style"):
        node = style.find(W + "name")
        if node is not None:
            out[style.get(W + "styleId", "")] = (node.get(W + "val") or "").lower()
        if style.get(W + "type") == "paragraph" and style.get(W + "default") in ("1", "true"):
            take(style.find(W + "rPr"))
    return out, size, font


def _docx_outer(node, tag: str):
    """Descendants with this tag, not looking inside a text box.

    A text box's paragraphs are laid out on their own (see _docx_inline);
    reaching into one from the drawing around it would show its pictures,
    and any text box nested in it, a second time.
    """
    for child in node:
        if child.tag == tag:
            yield child
        elif child.tag != W + "txbxContent":
            yield from _docx_outer(child, tag)


def _docx_on(props, tag: str) -> bool:
    """A toggle property: present and not switched off by its w:val."""
    node = props.find(W + tag) if props is not None else None
    if node is None:
        return False
    return node.get(W + "val", "true").lower() not in ("0", "false", "off", "none")


def _docx_val(props, path: str):
    node = props.find(path) if props is not None else None
    return node.get(W + "val") if node is not None else None


def _docx_twips(value, default: float = 0.0) -> float:
    """A twentieth-of-a-point measure, in inches."""
    try:
        return int(value) / 1440
    except (TypeError, ValueError):
        return default


def _docx_html(zf, names, page_w: int = 900) -> tuple:
    ctx = _DocxContext(zf, names, page_w)
    root = _member_xml(zf, "word/document.xml")
    body = root.find(W + "body")
    parts = _docx_blocks(body if body is not None else root, ctx)
    family = "'%s', serif" % ctx.font.replace("'", "") if ctx.font else "serif"
    head = "<body style=\"font-family:%s; font-size:%dpx; color:#111;\">" % (
        family, ctx.px(ctx.size_pt / 72))
    return head + "".join(p for p in parts if p) + "</body>", ctx.images


def _docx_blocks(container, ctx) -> list:
    """Paragraphs and tables, in order, from a body, cell or content control.

    Only direct children: a table's paragraphs belong to its cells, and
    walking every descendant — as this once did — printed each of them twice.
    """
    parts = []
    for block in container:
        if block.tag == W + "p":
            parts.append(_docx_paragraph(block, ctx))
        elif block.tag == W + "tbl":
            parts.append(_docx_table(block, ctx))
        elif block.tag in (W + "sdt", W + "customXml", W + "sdtContent"):
            inner = block.find(W + "sdtContent")
            parts += _docx_blocks(inner if inner is not None else block, ctx)
    return parts


def _docx_inline(node, ctx, pieces: list, boxes: list):
    """Collect a paragraph's runs in reading order.

    Recursive because runs hide inside hyperlinks, tracked insertions and
    content controls. A text box's paragraphs are *not* this paragraph's
    text: they are collected into `boxes` and set after it. Of an
    mc:AlternateContent, only the first choice is read — the fallback is
    the same drawing again, for older readers.
    """
    for child in node:
        tag = child.tag
        if tag == W + "r":
            _docx_run(child, ctx, pieces, boxes)
        elif tag == W + "del" or tag == W + "pPr":
            continue
        elif tag == _DOCX_MC + "AlternateContent":
            choice = child.find(_DOCX_MC + "Choice")
            if choice is not None:
                _docx_inline(choice, ctx, pieces, boxes)
        elif tag == W + "txbxContent":
            boxes += _docx_blocks(child, ctx)
        else:
            _docx_inline(child, ctx, pieces, boxes)


def _docx_run(run, ctx, pieces: list, boxes: list):
    props = run.find(W + "rPr")
    for child in run:
        tag = child.tag
        if tag == W + "t":
            pieces.append(_docx_styled(_escape(child.text), props, ctx))
        elif tag == W + "tab":
            pieces.append("&emsp;&emsp;")
        elif tag in (W + "br", W + "cr"):
            if child.get(W + "type") == "page":
                pieces.append(_DOCX_PAGE_BREAK)
            else:
                pieces.append("<br>")
        elif tag == W + "drawing":
            pieces.append(_docx_drawing(child, ctx))
            for box in _docx_outer(child, W + "txbxContent"):
                boxes += _docx_blocks(box, ctx)
        elif tag == W + "pict":
            pieces.append(_docx_vml(child, ctx))
            for box in _docx_outer(child, W + "txbxContent"):
                boxes += _docx_blocks(box, ctx)
        elif tag == _DOCX_MC + "AlternateContent":
            choice = child.find(_DOCX_MC + "Choice")
            if choice is not None:
                _docx_run(choice, ctx, pieces, boxes)


def _docx_styled(markup: str, props, ctx) -> str:
    if not markup or props is None:
        return markup
    css = []
    size = _docx_val(props, W + "sz")
    if size and size.isdigit():
        css.append("font-size:%dpx" % max(ctx.px(int(size) / 2 / 72), 4))
    colour = _docx_val(props, W + "color")
    if colour and len(colour) == 6 and colour.lower() != "auto":
        css.append("color:#%s" % colour)
    fonts = props.find(W + "rFonts")
    if fonts is not None:
        family = fonts.get(W + "ascii") or fonts.get(W + "hAnsi")
        if family:
            css.append("font-family:'%s'" % family.replace("'", ""))
    if _docx_on(props, "strike") or _docx_on(props, "dstrike"):
        css.append("text-decoration:line-through")
    if css:
        markup = "<span style=\"%s\">%s</span>" % (";".join(css), markup)
    if _docx_on(props, "b"):
        markup = "<b>%s</b>" % markup
    if _docx_on(props, "i"):
        markup = "<i>%s</i>" % markup
    if _docx_on(props, "u"):
        markup = "<u>%s</u>" % markup
    shift = _docx_val(props, W + "vertAlign")
    if shift == "superscript":
        markup = "<sup>%s</sup>" % markup
    elif shift == "subscript":
        markup = "<sub>%s</sub>" % markup
    return markup


def _docx_image(ctx, rel_id, w_in: float, h_in: float) -> str:
    member = ctx.rels.get(rel_id)
    if not member or member.lower().endswith(_DOCX_NO_RASTER):
        return ""
    if not _stash_image(ctx.zf, member, ctx.images):
        return ""
    w, h = ctx.px(w_in), ctx.px(h_in)
    if w <= 0 or h <= 0:
        return "<img src='%s' width='%d'>" % (_escape(member), min(420, ctx.max_img_w))
    if w > ctx.max_img_w:  # wider than the text column: shrink, keep aspect
        h = round(h * ctx.max_img_w / w)
        w = int(ctx.max_img_w)
    return "<img src='%s' width='%d' height='%d'>" % (_escape(member), w, h)


def _docx_drawing(drawing, ctx) -> str:
    """A DrawingML picture, at the size the document gives it.

    wp:extent is in EMUs, 914400 to the inch.
    """
    extent = drawing.find(".//" + _DOCX_WP + "extent")
    w_in = h_in = 0.0
    if extent is not None:
        try:
            w_in = int(extent.get("cx", 0)) / 914400
            h_in = int(extent.get("cy", 0)) / 914400
        except ValueError:
            pass
    out = []
    for blip in _docx_outer(drawing, _DOCX_A + "blip"):
        out.append(_docx_image(ctx, blip.get(_DOCX_R + "embed"), w_in, h_in))
    return "".join(out)


def _docx_vml(pict, ctx) -> str:
    """A legacy VML picture (Word 2003 and older), sized from its style."""
    import re

    out = []
    for shape in _docx_outer(pict, _DOCX_V + "shape"):
        dims = {}
        for key, num, unit in re.findall(
            r"(width|height)\s*:\s*([\d.]+)\s*(pt|in|px)?", shape.get("style", "")
        ):
            scale = {"in": 1.0, "px": 1 / 96}.get(unit, 1 / 72)
            try:
                dims[key] = float(num) * scale
            except ValueError:
                pass
        for data in _docx_outer(shape, _DOCX_V + "imagedata"):
            out.append(_docx_image(
                ctx, data.get(_DOCX_R + "id"),
                dims.get("width", 0.0), dims.get("height", 0.0),
            ))
    return "".join(out)


def _docx_paragraph(para, ctx) -> str:
    props = para.find(W + "pPr")
    style = ctx.styles.get(_docx_val(props, W + "pStyle") or "", "")
    pieces, boxes = [], []
    _docx_inline(para, ctx, pieces, boxes)

    css = []
    align = _docx_val(props, W + "jc")
    css_align = {"center": "center", "right": "right", "end": "right",
                 "both": "justify", "distribute": "justify"}.get(align or "")
    if css_align:
        css.append("text-align:%s" % css_align)
    ind = props.find(W + "ind") if props is not None else None
    numbered = props is not None and props.find(W + "numPr") is not None
    left = 0.0
    if ind is not None:
        left = _docx_twips(ind.get(W + "left") or ind.get(W + "start"))
        first = _docx_twips(ind.get(W + "firstLine"))
        first -= _docx_twips(ind.get(W + "hanging"))
        if first and not numbered:
            css.append("text-indent:%dpx" % ctx.px(first))
    spacing = props.find(W + "spacing") if props is not None else None
    if spacing is not None:
        for side, attr in (("top", "before"), ("bottom", "after")):
            if spacing.get(W + attr) is not None:
                css.append("margin-%s:%dpx" % (side, ctx.px(_docx_twips(spacing.get(W + attr)))))
    if props is not None and _docx_on(props, "pageBreakBefore"):
        css.append("page-break-before:always")

    bullet = numbered or style.startswith("list")
    if bullet:
        level = _docx_val(props, W + "numPr/" + W + "ilvl") or "0"
        depth = int(level) if level.isdigit() else 0
        left = max(left, 0.25 * (depth + 1))
        pieces.insert(0, "•&nbsp;&nbsp;")
    if left:
        css.append("margin-left:%dpx" % ctx.px(left))

    # A page break inside the paragraph splits it: what follows starts a page.
    chunks = "".join(pieces).split(_DOCX_PAGE_BREAK)
    out = []
    for n, body in enumerate(chunks):
        chunk_css = list(css)
        if n:
            chunk_css.append("page-break-before:always")
        out.append(_docx_block(body, style, chunk_css))
    return "".join(out) + "".join(boxes)


def _docx_block(body: str, style: str, css: list) -> str:
    attr = " style=\"%s\"" % ";".join(css) if css else ""
    if not body.strip():
        return "<p%s>&nbsp;</p>" % attr
    if style == "title":
        if not any(c.startswith("text-align") for c in css):
            attr = " style=\"%s\"" % ";".join(css + ["text-align:center"])
        return "<h1%s>%s</h1>" % (attr, body)
    if style.startswith("heading "):
        level = style.rsplit(" ", 1)[-1]
        level = min(int(level), 4) if level.isdigit() else 2
        return "<h%d%s>%s</h%d>" % (level, attr, body, level)
    return "<p%s>%s</p>" % (attr, body)


def _docx_table(table, ctx) -> str:
    rows = []
    for row in table.findall(W + "tr"):
        cells = []
        for cell in row.findall(W + "tc"):
            props = cell.find(W + "tcPr")
            if _docx_val(props, W + "vMerge") == "continue":
                continue  # the cell above spans down into this one
            span = _docx_val(props, W + "gridSpan")
            attr = " colspan='%s'" % span if span and span.isdigit() else ""
            shade = props.find(W + "shd") if props is not None else None
            fill = shade.get(W + "fill") if shade is not None else None
            style = "padding:4px"
            if fill and len(fill) == 6 and fill.lower() != "auto":
                style += ";background-color:#%s" % fill
            inner = "".join(_docx_blocks(cell, ctx))
            cells.append("<td%s style='%s'>%s</td>" % (attr, style, inner))
        rows.append("<tr>%s</tr>" % "".join(cells))
    return (
        "<table border='1' cellspacing='0' width='100%%'>%s</table>"
        % "".join(rows)
    )


def _stash_image(zf, member: str, images: dict) -> bool:
    if member in images:
        return True
    try:
        info = zf.getinfo(member)
    except KeyError:
        return False
    if info.file_size > OFFICE_MAX_THUMB_BYTES:
        return False
    with zf.open(member) as fh:
        images[member] = fh.read(OFFICE_MAX_THUMB_BYTES)
    return True


def _xlsx_html(zf, names) -> str:
    shared = []
    if "xl/sharedStrings.xml" in names:
        root = _member_xml(zf, "xl/sharedStrings.xml")
        shared = [
            "".join(node.text or "" for node in item.iter(SS + "t"))
            for item in root.iter(SS + "si")
        ]
    tables = []
    sheets = sorted(
        n for n in names
        if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")
    )
    for number, sheet in enumerate(sheets, 1):
        root = _member_xml(zf, sheet)
        rows = []
        for row in root.iter(SS + "row"):
            cells = []
            for cell in row.iter(SS + "c"):
                value = cell.find(SS + "v")
                if value is None or value.text is None:
                    text = ""
                elif cell.get("t") == "s":
                    try:  # see _office_text: one bad cell, not one bad file
                        index = int(value.text)
                    except ValueError:
                        index = -1
                    text = shared[index] if 0 <= index < len(shared) else ""
                else:
                    text = value.text
                cells.append(
                    "<td style='padding:3px 6px'>%s</td>" % _escape(text)
                )
            rows.append("<tr>%s</tr>" % "".join(cells))
            if len(rows) > 500:  # a preview, not the whole workbook
                break
        if rows:
            tables.append(
                "<h3>Sheet %d</h3><table border='1' cellspacing='0'>%s</table>"
                % (number, "".join(rows))
            )
    return _HTML_HEAD + "".join(tables) + "</body>" if tables else ""


def _odf_html(zf, names) -> tuple:
    ODF_H = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}h"
    ODF_TABLE = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
    images = {}
    root = _member_xml(zf, "content.xml")
    parts = []
    for node in root.iter():
        if node.tag == ODF_TEXT + "p":
            text = _escape("".join(node.itertext()).strip())
            parts.append("<p>%s</p>" % (text or "&nbsp;"))
        elif node.tag == ODF_H:
            parts.append("<h2>%s</h2>" % _escape("".join(node.itertext())))
        elif node.tag == ODF_TABLE + "table":
            rows = []
            for row in node.iter(ODF_TABLE + "table-row"):
                cells = [
                    "<td style='padding:3px 6px'>%s</td>"
                    % _escape("".join(cell.itertext()))
                    for cell in row.iter(ODF_TABLE + "table-cell")
                ]
                rows.append("<tr>%s</tr>" % "".join(cells))
            parts.append(
                "<table border='1' cellspacing='0'>%s</table>" % "".join(rows)
            )
    return _HTML_HEAD + "".join(parts) + "</body>", images
