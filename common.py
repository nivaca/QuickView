#!/usr/bin/env python3
# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Mustapha Alioglou
# Copyright (C) 2026 Nicolas Vaughan <nivaca@fastmail.com>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Settings, constants, logging and the preview cache.

Everything the daemon's modules share and nothing that draws: the
parsed configuration, the file-type tables, the panel stylesheet and
the two-tier cache's disk side. Imported, never run, so it exists once
even though quickview.py itself runs as __main__.
"""

import faulthandler
import hashlib
import logging
import logging.handlers
import os
import sys
from string import Template

import config
import ipc
# What the daemon asks the renderers: which engine the workers will use for
# office documents, for the cache key, and the bounds a workbook is held to.
# renderers imports nothing at module level, so this loads no parser here.

from PySide6.QtGui import (
    QImage,
)


SOCKET_PATH = ipc.socket_path()
# User settings — see config.py for the file's shape and why the surface is
# deliberately this small. One dict for the daemon's whole life: a reload
# (reload_settings) updates it in place, so every module sees the new values
# as long as it reads SETTINGS[...] when it needs one, never a copy taken at
# import. Notes on particular keys:
#
#   book_theme  page colours for EPUB books and Markdown — see
#               renderers.BOOK_THEMES. Passed to the worker (which owns the
#               colours) and folded into the page cache key, so switching
#               themes re-renders instead of serving the old one's pages.
#   code_style  any Pygments style name: dracula, gruvbox-dark, nord…
#               one-dark's own background (#282C34) is a shade off the
#               panel's #222226, so it sits in this panel unrecoloured.
SETTINGS = config.load()


def text_limit() -> int:
    """How much of a text file is read, in bytes."""
    return SETTINGS["text_limit_kb"] * 1024


def reload_settings(path: str = config.CONFIG_FILE) -> set:
    """Re-read the config file into SETTINGS, in place; the changed keys.

    config.load() never raises, so a half-written or malformed file reads
    as defaults for whatever it gets wrong, and the next save fixes it.
    Environment variables still win over the file, as they do at startup.
    """
    new = config.load(path)
    changed = {k for k in new if new[k] != SETTINGS.get(k)}
    SETTINGS.clear()
    SETTINGS.update(new)
    return changed

# Listed by container, not by application: a preview of any of these is a
# listing of what is inside, never an extraction.
ARCHIVE_MIMES = (
    "application/zip", "application/vnd.rar", "application/x-7z-compressed",
    "application/x-compressed-tar", "application/x-tar", "application/gzip",
    "application/x-xz-compressed-tar", "application/x-bzip-compressed-tar",
    "application/vnd.debian.binary-package", "application/x-cd-image",
)
ARCHIVE_EXTENSIONS = {".zip", ".rar", ".7z", ".tar", ".tgz", ".txz", ".tbz2"}
# OOXML and ODF documents: zip containers full of XML. Shown as pages —
# laid out by LibreOffice in the jail when the system has it, and otherwise
# with the standard library alone. A slide deck is absolutely positioned
# graphics that only an office suite can lay out, so without one it shows
# the thumbnail the deck embeds, with its text a button away.
OFFICE_MIMES = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.oasis.opendocument.text",
    "application/vnd.oasis.opendocument.spreadsheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.presentationml.slideshow",
    "application/vnd.oasis.opendocument.presentation",
)
# The legacy binary formats and RTF, which nothing but an office suite can
# read: shown as pages when LibreOffice is there, and as the metadata card
# when it is not — or when office_engine = builtin turns it off.
SUITE_ONLY_MIMES = (
    "application/msword",
    "application/vnd.ms-excel",
    "application/vnd.ms-powerpoint",
    "application/rtf",
    "text/rtf",
)

# Markdown gets both views: rendered pages (Qt's own Markdown parser, run
# in the jail like every other one) and the highlighted source, with the
# titlebar button flipping between them the way it does for HTML.
MARKDOWN_MIMES = ("text/markdown", "text/x-markdown")
MARKDOWN_EXTENSIONS = {".md", ".markdown", ".mdown", ".mkd", ".mkdn"}

# Spreadsheets take a different route from the rest of OFFICE_MIMES: a
# workbook is a grid, so it gets a real table with a tab per sheet instead of
# being poured into page images. A file that will not parse as one falls back
# to the office page view, which is why these stay in OFFICE_MIMES too.
SPREADSHEET_MIMES = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel.sheet.macroEnabled.12",
    "application/vnd.oasis.opendocument.spreadsheet",
)
SPREADSHEET_EXTENSIONS = {".xlsx", ".xlsm", ".ods"}
# A legacy .xls gets the grid too, but only through LibreOffice, which
# converts it to xlsx in the jail first; without it, it keeps the card.
LEGACY_SPREADSHEET_MIMES = ("application/vnd.ms-excel",)

# A book is a zip of XHTML with a reading order, which the office page
# pipeline can lay out — see renderers.epub_pages. What it gets on top of a
# document is a table of contents, and the sidebar that lists it.
EPUB_MIMES = ("application/epub+zip",)
EPUB_EXTENSIONS = {".epub"}
# The chapter sidebar, in pixels. The panel grows by this much when the
# sidebar opens rather than squeezing the pages, which are already rendered
# at a fixed width and would only start scrolling sideways.
TOC_WIDTH = 260

# Painting formats Qt cannot read, which renderers.decode_image falls back
# to its own readers for once Qt reports no handler — see _decode_native.
# The extensions are listed because their MIME types are not all image/*
# (a .kra is application/x-krita, a .psb is usually nothing at all), so
# without this they would land on the metadata card rather than in the
# branch that can read them.
LAYERED_EXTENSIONS = {".psd", ".psb", ".kra", ".ora"}
AI_EXTENSIONS = {".ai"}

TEXT_EXTENSIONS = {
    ".txt", ".md", ".rst", ".log", ".ini", ".cfg", ".conf", ".toml",
    ".yaml", ".yml", ".json", ".xml", ".html", ".htm", ".css", ".js",
    ".ts", ".py", ".r", ".sh", ".bash", ".zsh", ".c", ".h", ".cpp",
    ".hpp", ".rs", ".go", ".java", ".kt", ".rb", ".pl", ".lua", ".sql",
    ".csv", ".tsv", ".tex", ".bib", ".desktop", ".service", ".env",
}


APP_DIR = os.path.dirname(os.path.abspath(__file__))
WORKER_HELPER = os.path.join(APP_DIR, "worker.py")
# Pages warmed per neighbouring document by the prefetch: enough for it to
# open instantly. The page view renders the rest when it reaches the first
# missing page, as it does for any partly cached document.
PREFETCH_PAGES = 2
# SETTINGS["pdf_max_pages"] caps rendered pages so a 2000-page (or hostile)
# PDF can't grind the helper for minutes; the title says when the preview is
# truncated.

CACHE_DIR = os.path.join(
    os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")),
    "quickview", "previews",
)
# Every cache key carries this. Entries are keyed on the source file's
# path, mtime, size and the box it was fitted to — nothing about *how* it
# was rendered — so without a version, changing a renderer would leave the
# old output being served for ever. Bump it whenever a change alters the
# bytes a preview produces. This replaces bumping variant strings by hand,
# which is what the PDF path's "v2" used to be.
CACHE_VERSION = 3



def cache_cap_bytes() -> int:
    """The disk tier's cap; 0 turns the disk cache off."""
    return SETTINGS["disk_cache_mb"] * 1024 * 1024


def mem_cache_bytes() -> int:
    """The memory tier holds screen-sized pixmaps (~25 MB each on a 4K
    display), so it must be bounded by bytes, not entry count, in a process
    that never exits."""
    return SETTINGS["memory_cache_mb"] * 1024 * 1024


DATA_DIR = os.path.join(
    os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")),
    "quickview",
)
LOG_FILE = os.path.join(DATA_DIR, "quickview.log")
LOG_MAX_BYTES = 5 * 1024 * 1024

PNG_MAGIC = b"\x89PNG"
JPEG_MAGIC = b"\xff\xd8\xff"
# Sanity bound on one frame of a helper's stdout stream. The largest a
# legitimate frame gets is a screen-sized raw image — 21 MB on a 4K panel —
# so anything past this is a broken or hostile helper.
MAX_FRAME_BYTES = 64 * 1024 * 1024
# Frame slots the media worker cycles through in shared memory.
MEDIA_SLOTS = 2
# Playback speeds offered by the speed button, slowest first. The worker
# clamps whatever it is sent; this is only the menu.
PLAYBACK_RATES = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0)
# The speed and mute buttons, which are sized together so they match. Wide
# enough for "0.25×", which needs 59 px of the 12 px label plus the 28 px
# of padding #openBtn carries.
MEDIA_BUTTON_W = 68
MEDIA_BUTTON_H = 28
# The worker caps frames too, but it is the untrusted side of the socket:
# 512 screen-sized pixmaps is gigabytes of daemon memory, so the frames a
# preview will actually hold are bounded here as well.
# Formats show_file() treats as animations by default: a still WebP would
# otherwise pay a decode round trip to learn it has one frame.
ANIM_MIMES = ("image/gif", "image/apng")
ANIM_MAX_FRAMES = 512
ANIM_MAX_PIXMAP_BYTES = 256 * 1024 * 1024

log = logging.getLogger("quickview")


def apply_log_level():
    # config.py's _CHOICES guarantees one of error/warning/info/debug, so the
    # attribute is always there; the default is belt and braces.
    log.setLevel(getattr(logging, SETTINGS["log_level"].upper(), logging.INFO))


def setup_logging():
    os.makedirs(DATA_DIR, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    file_h = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=LOG_MAX_BYTES, backupCount=1
    )
    file_h.setFormatter(fmt)
    err_h = logging.StreamHandler()
    err_h.setFormatter(fmt)
    log.addHandler(file_h)
    log.addHandler(err_h)
    apply_log_level()

    # Native crashes (a segfault inside a Qt decoder, etc.) can't be caught
    # by Python's exception machinery — faulthandler dumps a traceback to
    # crash.log on SIGSEGV/SIGABRT/SIGBUS/SIGFPE/SIGILL before exiting.
    crash_fh = open(os.path.join(DATA_DIR, "crash.log"), "a")
    faulthandler.enable(file=crash_fh, all_threads=True)
    sys.excepthook = lambda *exc: log.critical(
        "unhandled exception", exc_info=exc
    )


# ------------------------------------------------------------------ cache
# Two tiers, like macOS quicklookd: decoded pixmaps stay in the daemon's
# memory (see QuickView._mem_cache), and rendered PNGs persist on disk keyed
# by path + mtime + size, so a changed file re-renders and a repeat view of
# an unchanged one skips decoding entirely.

def cache_key(
    path: str, st: os.stat_result, max_w: int, max_h: int, variant: str = ""
) -> str:
    raw = (f"{CACHE_VERSION}\0{path}\0{st.st_mtime_ns}\0{st.st_size}"
           f"\0{max_w}x{max_h}")
    if variant:  # e.g. "pdf3" — page 3 of a PDF at this width
        raw += f"\0{variant}"
    # The .png suffix is part of an opaque key, not a claim about the
    # contents: an image entry is JPEG whenever it has no alpha.
    return hashlib.sha256(raw.encode()).hexdigest() + ".png"


# The panel's own stylesheet. A Template rather than a literal so both
# themes can fill it — see theme.py for the tokens.
PANEL_STYLE = Template("""
        #panel {
            background-color: $bg;
            border-radius: $radius_panel;
            border: 1px solid $border;
        }
        #titleLabel {
            color: $text; font-size: 13px; font-weight: 600;
        }
        #closeBtn {
            background-color: $close_bg; color: $text_soft;
            border: none; border-radius: $radius_close;
            font-size: 11px; font-weight: bold;
        }
        #closeBtn:hover {
            background-color: $close_hover; color: $close_hover_text;
        }
        #openBtn {
            background-color: $btn; color: $text;
            border: none; border-radius: $radius_btn; padding: 4px 14px;
            font-size: 12px;
        }
        #openBtn:hover { background-color: $btn_hover; }
        /* No dropdown arrow on the speed button: the label already says
           what it is set to, and the arrow only steals room from it. */
        #openBtn::menu-indicator { image: none; width: 0; }
        #tocBtn {
            background-color: $btn; color: $text_soft;
            border: none; border-radius: $radius_btn;
            font-size: 12px; font-weight: bold;
        }
        #tocBtn:hover { background-color: $btn_hover; }
        #tocBtn:checked { background-color: $accent; color: $accent_text; }
        /* The speed menu is a popup window, so it takes the desktop
           theme rather than the panel unless it is styled here. */
        QMenu {
            background-color: $surface; color: $text;
            border: 1px solid $border; border-radius: $radius_btn;
            padding: 4px;
        }
        QMenu::item { padding: 4px 24px 4px 24px; border-radius: 4px; }
        QMenu::item:selected { background-color: $btn_hover; }
        QMenu::indicator { width: 12px; height: 12px; left: 6px; }
        QPlainTextEdit {
            background-color: $bg; color: $text_dim;
            border: none; padding: 8px 14px;
            font-family: monospace; font-size: 12px;
        }
        QLabel { color: $text_dim; }
        QSlider::groove:horizontal {
            height: 4px; background: $slider_groove; border-radius: 2px;
        }
        QSlider::handle:horizontal {
            width: 12px; margin: -4px 0; border-radius: 6px;
            background: $slider_handle;
        }
    """)


def is_cache_blob(data: bytes) -> bool:
    """Whether a worker frame is an encodable image for the disk cache.

    The image op's cache frame is JPEG for photographs and PNG when the
    image has alpha (see renderers.encode_cached), so both magics count.
    """
    return data[:4] == PNG_MAGIC or data[:3] == JPEG_MAGIC


def png_size(data: bytes) -> tuple[int, int] | None:
    """(width, height) from a PNG's IHDR, without decoding the image."""
    if len(data) < 24 or data[:4] != PNG_MAGIC or data[12:16] != b"IHDR":
        return None
    w = int.from_bytes(data[16:20], "big")
    h = int.from_bytes(data[20:24], "big")
    return (w, h) if w > 0 and h > 0 else None


def image_from_raw(data: bytes, header: dict) -> QImage:
    """Rebuild a QImage from the worker's raw ARGB32 frame.

    The geometry is worker-supplied, and the worker is the process that
    just parsed a hostile file, so it is checked against the buffer before
    Qt is pointed at it: an overlarge stride or a short frame would have
    QImage read past the end of the allocation. Returns a null QImage when
    anything does not line up, which the caller already treats as a failed
    render.
    """
    try:
        w = int(header.get("w", 0))
        h = int(header.get("h", 0))
        stride = int(header.get("stride", 0))
    except (TypeError, ValueError):
        return QImage()
    if header.get("fmt") != "argb32":
        return QImage()
    if w <= 0 or h <= 0 or stride < w * 4:
        return QImage()
    if len(data) < stride * h:
        return QImage()
    # .copy() because the QImage above only borrows `data`, which is a
    # Python object free to be collected the moment this returns.
    return QImage(data, w, h, stride, QImage.Format.Format_ARGB32).copy()


def cache_read_head(key: str, n: int = 24) -> bytes | None:
    """The first n bytes of a cached file — enough for a PNG's IHDR."""
    try:
        with open(os.path.join(CACHE_DIR, key), "rb") as fh:
            return fh.read(n)
    except OSError:
        return None


def cache_read(key: str) -> bytes | None:
    fp = os.path.join(CACHE_DIR, key)
    try:
        with open(fp, "rb") as fh:
            data = fh.read()
    except OSError:
        return None
    try:
        os.utime(fp)  # freshen so the pruner drops oldest-viewed first
    except OSError:
        pass  # the data is already read — a failed freshen is no reason to drop it
    return data


def cache_has(key: str) -> bool:
    return os.path.exists(os.path.join(CACHE_DIR, key))


def cache_remove(key: str):
    try:
        os.unlink(os.path.join(CACHE_DIR, key))
    except OSError:
        pass


# Rescanning the whole cache dir on every write is O(entries); amortize by
# pruning only after an eighth of the cap in new bytes has accumulated.
# Starting below zero forces one prune on the first write of a session,
# which also cleans up an over-cap cache left behind by a previous run.
_unpruned_bytes = -1


def cache_write(key: str, png: bytes):
    global _unpruned_bytes
    cap = cache_cap_bytes()
    if cap <= 0:
        return  # disk cache turned off in the config file
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = os.path.join(CACHE_DIR, f".{key}.tmp")
        with open(tmp, "wb") as fh:
            fh.write(png)
        os.replace(tmp, os.path.join(CACHE_DIR, key))
    except OSError as exc:
        log.warning("cache write failed: %s", exc)
        return
    if _unpruned_bytes >= 0:
        _unpruned_bytes += len(png)
    # Reset the counter only after a successful prune — zeroing it before a
    # prune that fails would suppress the next attempt until another eighth
    # of the cap in writes accumulates, leaving an over-cap cache in place
    # for hours on a cache-hit-heavy workload.
    due = _unpruned_bytes < 0 or _unpruned_bytes >= cap // 8
    if due and prune_cache():
        _unpruned_bytes = 0


def prune_cache() -> bool:
    entries, total = [], 0
    try:
        with os.scandir(CACHE_DIR) as it:
            for e in it:
                if e.is_file():
                    st = e.stat()
                    entries.append((st.st_mtime, st.st_size, e.path))
                    total += st.st_size
    except OSError as exc:
        log.warning("cache prune failed: %s", exc)
        return False
    entries.sort()
    for _mtime, size, fp in entries:
        if total <= cache_cap_bytes():
            break
        try:
            os.unlink(fp)
            total -= size
        except OSError:
            pass
    return True


def clear_cache():
    removed = 0
    try:
        with os.scandir(CACHE_DIR) as it:
            for e in it:
                if e.is_file():
                    os.unlink(e.path)
                    removed += 1
    except OSError:
        pass
    print(f"Cleared {removed} cached previews from {CACHE_DIR}")


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
