# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Mustapha Alioglou
# Copyright (C) 2026 Nicolas Vaughan <nivaca@fastmail.com>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Shared limits and the encoders every renderer hands its pixels to."""


# PNG quality 80 ≈ zlib level 2: encodes in roughly half the time of the
# default for ~20% larger files — the right trade for a preview a human is
# waiting on. Every encode below uses it.
PNG_QUALITY = 80


# Cache-only, and only for images with no alpha — see encode_cached.
JPEG_QUALITY = 85


# Above this, a file is shown as plain text. Pygments is a regex machine and
# the cost climbs with size: measured here, 83 KiB of Python lexes in 109 ms,
# but 1 MiB takes 1.5 s and yields a quarter of a million tokens — slower
# than the preview it is meant to decorate, and a payload bigger than the
# file itself.
HIGHLIGHT_MAX_BYTES = 256 * 1024


# An archive listing is a preview, not a file manager: enough entries to see
# what is in there, and a count for the rest.
ARCHIVE_MAX_ENTRIES = 500


# Nothing here decompresses an entry, so a zip bomb is inert — except in the
# office path, which does read one XML member. That read is bounded by this.
OFFICE_MAX_MEMBER_BYTES = 16 * 1024 * 1024


OFFICE_MAX_THUMB_BYTES = 8 * 1024 * 1024


# A rendered page, in pixels. Width comes from the caller (the panel width);
# the ratio is A4's, which is what these documents are written for.
PAGE_RATIO = 297 / 210


# Archive helpers, by absolute path: the jail runs --clearenv, so there is no
# PATH to search, and the user's own PATH may point at a conda build that
# does not exist inside the jail.
ARCHIVE_TOOLS = (
    ("/usr/bin/bsdtar", ["-tf"]),
    ("/usr/bin/7z", ["l", "-ba", "-slt"]),
    ("/usr/bin/unrar", ["lb"]),
)


# A PDF may declare any page geometry it likes, and the height is derived
# from the requested width: a 1 pt x 10000 pt page asks for a ten-million
# pixel column, i.e. tens of GB of QImage. The jail has no memory limit of
# its own, so the bound has to be here.
PDF_MAX_PAGE_PX = 10000


# A search that matches half the document is not a useful answer, and every
# hit costs a getSelectionAtIndex call and a rectangle on the wire.
PDF_MAX_HITS = 500


# Outline bounds. A generated PDF can carry a bookmark per paragraph, and a
# sidebar with ten thousand rows in it is not a table of contents.
PDF_MAX_OUTLINE = 2000


OUTLINE_MAX_TITLE = 200


# Text layer bounds, per page: what a page's selectable text may cost on
# the wire. A real page has a few thousand characters; a PDF built to be
# hostile can claim millions, and each word is a rectangle the daemon keeps.
PDF_TEXT_MAX_CHARS = 200_000
PDF_TEXT_MAX_WORDS = 20_000
# The fallback measures every word with its own QtPdf call, ~1 ms each, so
# it stops sooner: past this, the rest of the page is not selectable.
PDF_TEXT_MAX_WORDS_SLOW = 4_000
# Poppler's pdftotext lays a page's words out with their boxes in one pass,
# ~30 times faster than asking QtPdf word by word. By absolute path: the jail
# runs --clearenv, with no PATH to search.
PDFTOTEXT = "/usr/bin/pdftotext"
PDFTOTEXT_TIMEOUT = 15


def _encode(img, fmt: str = "PNG", quality: int = PNG_QUALITY) -> bytes:
    from PySide6.QtCore import QBuffer, QIODevice

    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    if not img.save(buf, fmt, quality):
        raise RuntimeError(f"{fmt} encode failed")
    return bytes(buf.data())


def encode_cached(img) -> bytes:
    """Encode a preview for the daemon's disk cache.

    JPEG for photographs: a preview-sized image costs ~24 ms to write and
    ~11 ms to read back against PNG's ~111 and ~37, and lands in a tenth of
    the space, so the fixed cache holds ten times as many previews before
    it starts evicting. The loss at this quality is invisible at preview
    size, and this is a cache — the original is never touched.

    PNG whenever the image really is transparent somewhere, because JPEG
    has no alpha and a transparent logo would come back on a black square.
    Qt writes the "QuickView:OrigSize" tEXt chunk into a JPEG comment
    marker, so the dimensions the cache-hit path reads survive either way.
    """
    if img.hasAlphaChannel() and not _is_opaque(img):
        return _encode(img)
    return _encode(img, "JPG", JPEG_QUALITY)


def _is_opaque(img) -> bool:
    """Whether every pixel is fully opaque.

    hasAlphaChannel() answers about the *format*, not the pixels, and a
    great many opaque images decode to ARGB32 anyway — screenshots and most
    PNGs among them. Trusting it alone cached those as multi-megabyte PNGs
    when a 200 KB JPEG would do. The scan is ~2 ms on a preview-sized image
    against the ~80 ms PNG encode it avoids, and it runs in the worker
    after the picture is already on screen.
    """
    from PySide6.QtGui import QImage

    if img.format() != QImage.Format.Format_ARGB32:
        img = img.convertToFormat(QImage.Format.Format_ARGB32)
    width, height = img.width(), img.height()
    row_len = width * 4
    stride = img.bytesPerLine()
    data = bytes(img.constBits())
    if stride == row_len:  # no row padding: one slice does the whole image
        return data[3::4].count(0xFF) == width * height
    # Qt pads rows to a 4-byte boundary; the padding is not pixel data and
    # must not be counted, so walk row by row.
    for y in range(height):
        start = y * stride
        if data[start:start + row_len][3::4].count(0xFF) != width:
            return False
    return True


def raw_frame(img) -> tuple:
    """(pixel bytes, geometry) for handing an image over a local socket.

    PNG costs ~100 ms to write and ~30 ms to read back for a preview-sized
    photo — more than the decode it follows — and buys nothing between two
    processes on the same machine. Raw ARGB32 is ~0.4 ms each way. BMP is
    the obvious middle ground and is wrong: Qt's BMP writer drops the alpha
    channel, so transparent PNGs and SVGs would come back opaque.

    The geometry travels beside the bytes because the receiver cannot infer
    stride: Qt pads rows, so bytesPerLine is not always width * 4.
    """
    from PySide6.QtGui import QImage

    if img.format() != QImage.Format.Format_ARGB32:
        img = img.convertToFormat(QImage.Format.Format_ARGB32)
    return bytes(img.constBits()), {
        "w": img.width(), "h": img.height(),
        "stride": img.bytesPerLine(), "fmt": "argb32",
    }


# The reading font arrives in a job from the daemon and is written into a
# page style sheet, so it is filtered again here rather than trusted: the
# same rule as config.clean_font_family. Sizes in points.
READING_FONT_SIZE_MIN = 6
READING_FONT_SIZE_MAX = 36
DEFAULT_READING_FONT_SIZE = 11


def reading_font(family, size) -> tuple:
    """(family, size) for page layout: a clean family name ("" for the
    built-in look) and a point size within bounds."""
    kept = "".join(c for c in str(family or "") if c.isalnum() or c in " -_.")
    try:
        size = int(size)
    except (TypeError, ValueError):
        size = DEFAULT_READING_FONT_SIZE
    size = max(READING_FONT_SIZE_MIN, min(READING_FONT_SIZE_MAX, size))
    return " ".join(kept.split())[:64], size


def _rewound(fd: int):
    """A private, rewound file object over an inherited descriptor."""
    import os

    os.lseek(fd, 0, os.SEEK_SET)
    return os.fdopen(os.dup(fd), "rb")


def _stderr():
    import sys

    return sys.stderr
