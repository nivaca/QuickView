#!/usr/bin/env python3
# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Mustapha Alioglou
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.
"""Warm, jailed preview worker for QuickView.

Usage: worker.py <socket-fd>

The daemon spawns this inside bubblewrap *before* it is needed, so PySide6
is already imported by the time a file shows up — that import, not the jail
(~3 ms), is what made the old spawn-per-file helpers cost ~150 ms each.

Because the file arrives as a file descriptor over SCM_RIGHTS, the jail
needs no access to the user's filesystem at all: nothing but /usr, this app
dir and the fonts are visible in here.

Wire protocol on the socket, both directions framed as 4-byte big-endian
length + payload:

    daemon -> worker   one JSON request {"op": ..., ...}, with the target
                       file's fd attached as ancillary data

The "text" op answers with JSON rather than pixels: the file's text plus the
colour spans of its syntax (see renderers.highlight_text). So does
"pdfsearch", which returns the rectangles of a query's matches already in
page pixels.
    worker -> daemon   one JSON header {"ok": true, "count": N} (or
                       {"ok": false, "error": "..."}), then N frames, each
                       flushed as it is produced, then a zero-length frame
                       as the end-of-stream marker

Frames are encoded images (PNG, or JPEG for the cache copy of a
photograph), with one exception: the "image" op sends two, the first being
raw ARGB32 pixels — the header carries "w", "h", "stride", "fmt" and
"orig" — and the second the encoded copy for the daemon's disk cache.
Compressing pixels to move them between two processes on one machine cost
more than the decode did; see renderers.raw_frame and encode_cached.

The marker is what tells the daemon a stream ended because it was finished
rather than because the worker died: once the header has gone out there is
no way to take it back, so a failure after that point closes the socket
without a marker and explains itself on stderr (which the daemon collects).

One worker handles exactly one file and then exits: that keeps per-file
isolation identical to the old throwaway helpers while the daemon hides the
startup cost behind a pre-spawned spare.
"""

import array
import json
import os
import socket
import struct
import sys

import renderers

# Animation bounds — a GIF header may claim far more frames than it has.
ANIM_MAX_FRAMES = 512
ANIM_MAX_BYTES = 256 * 1024 * 1024


def send(sock: socket.socket, payload: bytes):
    sock.sendall(struct.pack(">I", len(payload)) + payload)


def recv_request(sock: socket.socket) -> tuple[dict, int]:
    """Read the one request, returning (job, fd). Raises on a short read."""
    fds = array.array("i")
    header = b""
    # The fd rides on the first recvmsg; the JSON may need more reads.
    chunk, anc, _flags, _addr = sock.recvmsg(4, socket.CMSG_SPACE(4))
    for level, type_, data in anc:
        if level == socket.SOL_SOCKET and type_ == socket.SCM_RIGHTS:
            fds.frombytes(data[: len(data) - (len(data) % fds.itemsize)])
    if len(chunk) < 4 or not fds:
        raise RuntimeError("truncated request")
    (size,) = struct.unpack(">I", chunk)
    while len(header) < size:
        part = sock.recv(size - len(header))
        if not part:
            raise RuntimeError("truncated request body")
        header += part
    return json.loads(header), fds[0]


class Reply:
    """The answer stream for one job: one header, then frames.

    Tracks whether the header has gone out, because that decides how a
    failure is reported — see serve().
    """

    def __init__(self, sock: socket.socket):
        self.sock = sock
        self.started = False

    def header(self, count: int, **extra):
        self.started = True
        send(self.sock, json.dumps({"ok": True, "count": count, **extra}).encode())

    def frame(self, payload: bytes):
        send(self.sock, payload)

    def json(self, value):
        self.frame(json.dumps(value).encode())


# ------------------------------------------------------------------ ops
# One function per op: (job, src, fd, out). src is the file as a QFile, for
# the Qt decoders; fd is the raw descriptor, for the parsers that want a
# Python file object or /dev/fd. Each streams through out and returns; any
# exception is reported by serve().

def op_image(job, src, fd, out):
    # Two frames, in this order on purpose. The raw pixels let the
    # daemon paint immediately; the encoded copy that follows is
    # only for its disk cache, so that cost lands in here, after the
    # image is already on screen, instead of in front of it.
    img, orig = renderers.decode_image(src, job["max_w"], job["max_h"])
    # "raw": False is the daemon's prefetch, which only warms the
    # disk cache — sending it pixels it will drop is megabytes of
    # copying for nothing.
    want_raw = job.get("raw", True)
    geom = {}
    raw = b""
    if want_raw:
        raw, geom = renderers.raw_frame(img)
    out.header(2 if want_raw else 1, orig=orig, **geom)
    if want_raw:
        out.frame(raw)
    # Read back by the daemon's cache-hit path, which still takes
    # the dimensions from this chunk — Qt carries it through JPEG as
    # a comment marker as well as through PNG's tEXt.
    img.setText("QuickView:OrigSize", orig)
    out.frame(renderers.encode_cached(img))


def op_pdf(job, src, fd, out):
    first = True
    for count, png in renderers.render_pdf(
        src, job["page_w"], job["max_pages"], job.get("start", 0),
        job.get("scale", 1.0),
    ):
        if first:
            out.header(count)
            first = False
        out.frame(png)
    if first:  # a zero-page document
        out.header(0)


def op_text(job, src, fd, out):
    doc = renderers.highlight_text(
        src, job.get("name", ""), job["limit"],
        job.get("style", "one-dark"),
    )
    out.header(1)
    out.json(doc)


def op_pdfsearch(job, src, fd, out):
    # Answers with JSON, not pixels: the rectangles are already in
    # page pixels, so the daemon paints them without owning a parser
    # or repeating the render geometry.
    out.header(1)
    out.json(renderers.search_pdf(
        src, job.get("query", ""), job["page_w"], job["max_pages"],
    ))


def op_archive(job, src, fd, out):
    # Takes the raw descriptor, not the QFile: zipfile/tarfile want a
    # Python file object and the external listers read /dev/fd.
    out.header(1)
    out.json(renderers.list_archive(fd, job.get("name", "")))


def op_epub(job, src, fd, out):
    # Page images like the office path, but the header carries the
    # book's table of contents as well: the chapters are a property
    # of the layout that produced the pages, so they are computed
    # once, in here, and travel with the first frame.
    first = True
    for info, png in renderers.epub_pages(
        fd, job.get("name", ""), job["page_w"],
        job["max_pages"], job.get("start", 0),
        theme=job.get("theme", renderers.DEFAULT_BOOK_THEME),
        scale=job.get("scale", 1.0),
        font=job.get("font", ""), font_size=job.get("font_size", 11),
    ):
        if first:
            out.header(info["count"], kind="pages", toc=info["chapters"],
                       title=info.get("title", ""))
            first = False
        out.frame(png)
    if first:
        raise RuntimeError("no pages laid out")


def op_markdown(job, src, fd, out):
    # Page images, like the office and epub paths: Qt's Markdown
    # parser runs in here, and the daemon only ever sees pixels.
    first = True
    for info, png in renderers.markdown_pages(
        fd, job.get("name", ""), job["page_w"], job["max_pages"],
        job.get("start", 0),
        job.get("theme", renderers.DEFAULT_BOOK_THEME),
        job.get("scale", 1.0),
        font=job.get("font", ""), font_size=job.get("font_size", 11),
    ):
        if first:
            # The headings travel with the pages, as a book's
            # chapters do — same header, same sidebar.
            out.header(info["count"], kind="pages", toc=info["chapters"])
            first = False
        out.frame(png)
    if first:
        raise RuntimeError("nothing to render")


def op_epubsearch(job, src, fd, out):
    # The book equivalent of "pdfsearch", and the same answer
    # shape: the daemon paints rectangles without knowing which
    # kind of document produced them.
    out.header(1)
    out.json(renderers.search_epub(
        fd, job.get("query", ""),
        job["page_w"], job["max_pages"],
        job.get("theme", renderers.DEFAULT_BOOK_THEME),
        font=job.get("font", ""), font_size=job.get("font_size", 11),
    ))


def op_pdftext(job, src, fd, out):
    # The words of some pages and their boxes, for selecting and copying
    # text. Asked for when the reader first presses on a page (or for every
    # page at once, for Select All) — not with every render, which would
    # tax every preview for a feature most never use.
    pages = job.get("pages") or []
    if not isinstance(pages, list):
        raise RuntimeError("pages must be a list")
    out.header(1)
    out.json(renderers.page_text(src, fd, pages[:job["max_pages"]],
                                 job["page_w"], job["max_pages"]))


def _reading_text(fn):
    """An op answering like "pdftext", for pages laid out from text — a
    Markdown file's or a book's — from the same layout the pages were
    painted with."""
    def op(job, src, fd, out):
        pages = job.get("pages") or []
        if not isinstance(pages, list):
            raise RuntimeError("pages must be a list")
        out.header(1)
        out.json(fn(
            fd, pages[:job["max_pages"]], job["page_w"], job["max_pages"],
            job.get("theme", renderers.DEFAULT_BOOK_THEME),
            font=job.get("font", ""), font_size=job.get("font_size", 11),
        ))
    return op


op_mdtext = _reading_text(renderers.markdown_text)
op_epubtext = _reading_text(renderers.epub_text)


def op_pdfoutline(job, src, fd, out):
    # The bookmarks, for the sidebar. A separate op rather than a
    # field on the render's header: the render streams from a
    # generator that has already sent its header by the time a
    # second parse of the document could finish.
    out.header(1)
    out.json(renderers.pdf_outline(
        src, job["page_w"], job.get("max_pages", 50)
    ))


def op_sheets(job, src, fd, out):
    # A workbook as a grid of text, one entry per sheet: the daemon
    # shows it in a table with tabs rather than as page images.
    out.header(1)
    out.json(renderers.read_workbook(
        fd, job.get("name", ""), job.get("engine", "libreoffice")
    ))


def op_office(job, src, fd, out):
    # Two shapes of answer, and the header says which: laid-out
    # page images when the document can be rendered, or a JSON
    # payload (embedded thumbnail plus text) when it cannot, which
    # is what happens for a slide deck.
    first = True
    try:
        for count, png in renderers.office_pages(
            fd, job.get("name", ""), job["page_w"],
            job["max_pages"], job.get("start", 0),
            job.get("engine", "libreoffice"),
            job.get("scale", 1.0),
        ):
            if first:
                out.header(count, kind="pages")
                first = False
            out.frame(png)
    except Exception as exc:
        if not first:
            raise  # already streaming: the trailer's absence reports it
        print("office_pages: %s" % exc, file=sys.stderr)
    if first:  # nothing rendered — fall back to thumbnail and text
        doc = renderers.office_preview(
            fd, job.get("name", ""), job["limit"]
        )
        out.header(1, kind="doc")
        out.json(doc)


def op_anim(job, src, fd, out):
    first = True
    for count, delay, png in renderers.render_anim(
        src, job["max_w"], job["max_h"], ANIM_MAX_FRAMES, ANIM_MAX_BYTES
    ):
        if first:
            out.header(count)
            first = False
        # Frame delay rides in front of the PNG: 4 bytes, then bytes.
        out.frame(struct.pack(">I", delay) + png)
    if first:
        raise RuntimeError("no frames decoded")


OPS = {
    "image": op_image,
    "pdf": op_pdf,
    "text": op_text,
    "pdfsearch": op_pdfsearch,
    "pdftext": op_pdftext,
    "mdtext": op_mdtext,
    "epubtext": op_epubtext,
    "archive": op_archive,
    "epub": op_epub,
    "markdown": op_markdown,
    "epubsearch": op_epubsearch,
    "pdfoutline": op_pdfoutline,
    "sheets": op_sheets,
    "office": op_office,
    "anim": op_anim,
}


def serve(sock: socket.socket) -> int:
    """Answer the one request on sock. Needs a Qt application already."""
    from PySide6.QtCore import QFile, QIODevice

    job, fd = recv_request(sock)
    src = QFile()
    if not src.open(fd, QIODevice.OpenModeFlag.ReadOnly):
        send(sock, json.dumps({"ok": False, "error": "cannot open fd"}).encode())
        return 1

    op = job.get("op")
    out = Reply(sock)
    try:
        handler = OPS.get(op)
        if handler is None:
            raise RuntimeError(f"unknown op: {op!r}")
        handler(job, src, fd, out)
        send(sock, b"")  # end of stream: everything above got through
    except Exception as exc:  # a hostile file must not look like a crash
        if out.started:
            # Too late for {"ok": false}: the daemon has taken the header
            # and reads anything further as a frame. Closing without the
            # marker is what tells it this stream is truncated.
            print(exc, file=sys.stderr)
        else:
            try:
                send(sock, json.dumps({"ok": False, "error": str(exc)}).encode())
            except OSError:
                pass  # daemon moved on and closed the socket
        return 1
    finally:
        sock.close()
    return 0


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    sock = socket.socket(fileno=int(sys.argv[1]))

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    # Imported before the socket read so the whole Qt boot happens while the
    # worker is still a spare — the point of the pool.
    from PySide6.QtCore import QFile, QIODevice  # noqa: F401 — warmed here
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication([sys.argv[0]])  # noqa: F841 — the parsers need it
    return serve(sock)


if __name__ == "__main__":
    sys.exit(main())
