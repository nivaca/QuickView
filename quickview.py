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
"""QuickView — a macOS Quick Look style previewer for KDE.

Usage: quickview <file> [file ...]
       quickview --daemon       run resident (systemd user service does this)
       quickview --clear-cache  empty the disk preview cache

Keys:
  Space / Esc / Q   close the preview
  Left / Right      previous / next file (the selection if several files
                    were passed, otherwise siblings in the same folder)
  Enter             open the file in its default application

A second invocation while a preview is open is forwarded to the running
instance: same file toggles the window closed (like Quick Look), a
different file switches the preview.
"""

import html
import os
import sys
from collections import OrderedDict

import config
import ipc
import theme
# What the daemon asks the renderers: which engine the workers will use for
# office documents, for the cache key, and the bounds a workbook is held to.
# renderers imports nothing at module level, so this loads no parser here.

from PySide6.QtCore import (
    Qt, QUrl, QEvent, QPoint, QSize, QTimer, QFileInfo, QFileSystemWatcher,
    QMimeDatabase,
)
from PySide6.QtGui import (
    QGuiApplication, QKeySequence, QRegion,
    QShortcut, QColor, QDesktopServices,
)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication, QFileIconProvider, QFrame, QLabel, QStackedLayout, QVBoxLayout, QWidget,
    QGraphicsDropShadowEffect,
)

from common import (
    AI_EXTENSIONS,
    ANIM_MIMES,
    apply_log_level,
    ARCHIVE_EXTENSIONS,
    ARCHIVE_MIMES,
    clear_cache,
    EPUB_EXTENSIONS,
    EPUB_MIMES,
    human_size,
    LAYERED_EXTENSIONS,
    LEGACY_SPREADSHEET_MIMES,
    log,
    LOG_FILE,
    MARKDOWN_EXTENSIONS,
    MARKDOWN_MIMES,
    OFFICE_MIMES,
    PANEL_STYLE,
    prune_cache,
    SETTINGS,
    setup_logging,
    SOCKET_PATH,
    SPREADSHEET_EXTENSIONS,
    SPREADSHEET_MIMES,
    SUITE_ONLY_MIMES,
    TEXT_EXTENSIONS,
)
# Aliased: QuickView.reload_settings() is the window's, which applies what
# this one reads.
from common import reload_settings as read_settings_file
from sandbox import (
    WorkerPool,
)
from view_document import (
    DocumentViewMixin,
)
from view_image import (
    ImageViewMixin,
)
from view_media import (
    MediaViewMixin,
)
from view_office import (
    OfficeViewMixin,
)
from view_text import (
    TextViewMixin,
)
from widgets import (
    TitleBar,
)

class QuickView(ImageViewMixin, DocumentViewMixin, MediaViewMixin,
                TextViewMixin, OfficeViewMixin, QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Dialog
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("QuickView")

        # Resolved first: the titlebar's layout and every stylesheet below
        # read from it. QApplication.palette() is the running desktop's,
        # which is what "breeze" follows — so this has to happen after the
        # application exists, not at import time with the rest of SETTINGS.
        self.theme_name = SETTINGS["panel_theme"]
        self.theme = theme.load(self.theme_name, QApplication.palette())
        self.mime_db = QMimeDatabase()
        self.icon_provider = QFileIconProvider()
        self.current_path = None
        self.selection = []
        self.sel_index = 0
        self.anim_timer = None
        self.media = None
        self._mem_cache = OrderedDict()  # key -> (pixmap, dims, nbytes)
        self.pool = WorkerPool()
        self._render_job = None
        self._prefetch_job = None
        self._prefetch_queue = []  # (path, key, job) awaiting a warm render
        self._pdf_gen = None  # token invalidating in-flight page appends
        self._pdf_labels = []  # one placeholder per page of the open PDF
        self._pdf_overlays = []  # a MatchOverlay per page, for find results
        self._find_bar = None    # the Ctrl+F row, while a PDF is showing
        self._find_scroll = None  # the page column's QScrollArea
        self._find_path = None   # the document find is currently bound to
        self._find_op = None     # which search op that document needs
        self._find_hits = []     # [[page, x, y, w, h], ...] for the query
        self._find_of = None     # the query _find_hits belongs to
        self._find_loose = False  # hits came from the spaces-ignored pass
        self._find_at = -1       # index into _find_hits
        self._find_page_w = 0    # pixel width the hits were computed for
        self._page_scale = 1.0   # device pixel ratio the page images are for
        self._find_job = None
        self._text_readers = set()  # readers still on a pool thread
        self._html_rendered = True  # HTML mode: rendered page vs. source
        self._md_rendered = True    # Markdown mode: rendered pages vs. source
        self._office_text = False   # office mode: thumbnail vs. extracted text
        self._office_doc = None     # (path, payload) so the toggle is instant
        self._toc_entries = []   # chapters/bookmarks of the open document
        self._toc_sidebar = None  # the tree widget, while one is showing
        self._toc_body = None     # layout it lives in, for a late arrival
        self._toc_open = False    # sidebar shown? remembered across files
        self._toc_job = None      # the PDF outline fetch, while in flight
        self._page_scroll = None  # the page column, for scroll-to-page
        self._page_size = None    # panel size without the sidebar
        self._web_profile = None  # lazy; one hardened profile for all pages

        self.panel = QFrame(self)
        self.panel.setObjectName("panel")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(40)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 160))
        self.panel.setGraphicsEffect(shadow)

        # Room left around the panel for the drop shadow; the panel is
        # placed inside the overlay by _place_panel(), not by a layout.
        self._margins = (24, 24, 24, 32)  # left, top, right, bottom
        self._panel_size = QSize(520 + 48, 320 + 56 + 40)
        self._panel_pos = None  # None = centred; a point once dragged

        self.titlebar = TitleBar(self)
        self.content = QStackedLayout()
        self.content.setContentsMargins(0, 0, 0, 0)

        panel_lay = QVBoxLayout(self.panel)
        panel_lay.setContentsMargins(1, 0, 1, 1)
        panel_lay.setSpacing(0)
        panel_lay.addWidget(self.titlebar)
        panel_lay.addLayout(self.content, 1)

        # Fully opaque: every colour below is solid, including the ones that
        # used to be white-over-panel blends. WA_TranslucentBackground stays
        # on above — it is what lets the rounded corners and the drop shadow
        # composite against the desktop — but nothing shows through the panel
        # itself any more.
        self.setStyleSheet(PANEL_STYLE.substitute(self.theme))

        # Kept in a list because every one of them is a *single* key, and a
        # QShortcut outranks the key events of a focused child widget: with
        # the find field open, typing a space or a "q" would dismiss the
        # preview and the arrows would switch files. _set_nav_shortcuts()
        # turns them off for exactly as long as that field has focus.
        self._nav_shortcuts = [
            QShortcut(QKeySequence(keys), self, activated=fn)
            for keys, fn in (
                (Qt.Key_Space, lambda: self.dismiss("space")),
                (Qt.Key_Escape, lambda: self.dismiss("escape")),
                (Qt.Key_Q, lambda: self.dismiss("q")),
                (Qt.Key_Left, lambda: self.step_sibling(-1)),
                (Qt.Key_Right, lambda: self.step_sibling(+1)),
                (Qt.Key_Return, self.open_externally),
                (Qt.Key_Enter, self.open_externally),
            )
        ]
        QShortcut(
            QKeySequence(Qt.CTRL | Qt.Key_F), self,
            activated=self.open_find,
        )
        QShortcut(
            QKeySequence(Qt.CTRL | Qt.Key_Q), self,
            activated=QApplication.instance().quit,
        )

    def dismiss(self, reason: str = "request"):
        """Hide the preview but keep the process resident for instant reuse."""
        if self.isVisible():
            log.debug("dismissed (%s)", reason)
        self.clear_content()
        self.hide()
        # The next preview starts centred again, whatever this one was
        # dragged to.
        self._panel_pos = None

    def closeEvent(self, event):
        event.ignore()
        self.dismiss("window closed")

    def event(self, event):
        # Handled here rather than in changeEvent() because changeEvent()
        # never sees it: QWidget.event() consumes ApplicationPaletteChange
        # itself and passes on only the widget-level PaletteChange, which
        # also arrives mid-__init__ and on every stylesheet re-polish.
        #
        # The daemon outlives any number of colour-scheme changes: there is
        # one QuickView for its whole lifetime, so a theme resolved once in
        # __init__ would keep the scheme that happened to be set at login.
        # Only breeze reads the palette, so only breeze has to be redone.
        if (event.type() == QEvent.ApplicationPaletteChange
                and getattr(self, "theme_name", None) == "breeze"):
            self.theme = theme.load("breeze", QApplication.palette())
            # The panel only. Content widgets carry stylesheets built when
            # the preview was made, and the sole way to recolour those is to
            # re-render, which would lose the scroll position, the PDF page,
            # the EPUB chapter. A preview lasts seconds and nobody reaches
            # System Settings past it — the next one is built from the new
            # palette anyway.
            self.setStyleSheet(PANEL_STYLE.substitute(self.theme))
        return super().event(event)

    # ------------------------------------------------------------ settings
    # The config file is re-read when it changes, so a setting takes effect
    # on the next preview without restarting the daemon. Everything that
    # reads SETTINGS at the point of use picks the new value up by itself;
    # what is built once — the log level, the panel theme — is redone here.

    def watch_settings(self, path: str = config.CONFIG_FILE):
        self._settings_path = path
        self._settings_watcher = QFileSystemWatcher(self)
        # Editors save in bursts (truncate, write, rename), and a reload
        # halfway through would read a half-written file: wait for quiet.
        self._settings_quiet = QTimer(self)
        self._settings_quiet.setSingleShot(True)
        self._settings_quiet.setInterval(250)
        self._settings_quiet.timeout.connect(self.reload_settings)
        self._settings_watcher.fileChanged.connect(self._settings_quiet.start)
        # The directory as well: an editor that saves by renaming a new
        # file into place leaves a file watch on the old, unlinked one, and
        # a file created after startup has nothing to watch yet.
        self._settings_watcher.directoryChanged.connect(
            self._settings_quiet.start)
        # Read once more now that the watch is in place: SETTINGS was loaded
        # at import, and an edit saved while the daemon was still starting
        # up would otherwise wait for the next save to be noticed.
        self.reload_settings()

    def _rewatch_settings(self):
        watcher, path = self._settings_watcher, self._settings_path
        folder = os.path.dirname(path)
        if os.path.isdir(folder) and folder not in watcher.directories():
            watcher.addPath(folder)
        if os.path.isfile(path) and path not in watcher.files():
            watcher.addPath(path)

    def reload_settings(self) -> set:
        """Apply the config file as it is now; the names that changed."""
        self._rewatch_settings()
        changed = read_settings_file(self._settings_path)
        if not changed:
            return changed
        log.info("settings reloaded: %s", ", ".join(sorted(changed)))
        if "log_level" in changed:
            apply_log_level()
        if "panel_theme" in changed:
            self.apply_panel_theme(SETTINGS["panel_theme"])
        if "disk_cache_mb" in changed:
            prune_cache()  # a smaller cap applies now, not after more writes
        return changed

    def apply_panel_theme(self, name: str):
        """Switch the panel's theme in place. Content already on screen
        keeps the colours it was built with, as on a palette change."""
        self.theme_name = name
        self.theme = theme.load(name, QApplication.palette())
        self.titlebar.arrange()
        self.setStyleSheet(PANEL_STYLE.substitute(self.theme))

    # ---------------------------------------------------------------- helpers

    def screen_avail(self) -> QSize:
        screen = self.screen() or QGuiApplication.primaryScreen()
        return screen.availableGeometry().size()

    def page_scale(self) -> float:
        """Device pixels per logical pixel, for rendering page images.

        Pages were rendered at their logical width and then stretched by
        the compositor on a scaled screen — 1.25x or 1.5x on a 4K monitor
        — which is what made them blurry next to Okular. The window's own
        ratio is asked first: under Wayland fractional scaling only the
        window knows the exact 1.25; the screen reports it rounded up.
        """
        handle = self.windowHandle()
        ratio = handle.devicePixelRatio() if handle else 0.0
        if ratio <= 0:
            screen = self.screen() or QGuiApplication.primaryScreen()
            ratio = screen.devicePixelRatio() if screen else 1.0
        return round(min(max(ratio, 1.0), 4.0), 2)

    def set_panel_size(self, w: int, h: int):
        avail = self.screen_avail()
        w = min(max(w, 480), int(avail.width() * 0.85))
        h = min(max(h, 320), int(avail.height() * 0.85))
        # Sizes the panel, not the window: the window is a full-screen
        # overlay, so a preview that grows (a PDF swapping its "Loading…"
        # card for the page column) re-centres instead of drifting away
        # from wherever the compositor first put it.
        self._panel_size = QSize(w + 48, h + 56 + 40)
        self._place_panel()
        # Which caller sized the panel, and against which screen. A preview
        # that opens too small is either a fallback card sized 520x320 or a
        # screen this ran before the window had one.
        log.debug(
            "panel sized %dx%d (panel %dx%d at %d,%d in overlay %dx%d, "
            "screen %dx%d)",
            w, h, self.panel.width(), self.panel.height(),
            self.panel.x(), self.panel.y(), self.width(), self.height(),
            avail.width(), avail.height(),
        )

    def fit_overlay(self):
        """Cover the work area. Only the size lands on Wayland; that is
        enough, because the panel is centred against the screen below."""
        screen = self.screen() or QGuiApplication.primaryScreen()
        self.setGeometry(screen.availableGeometry())

    def _place_panel(self):
        """Lay the panel out inside the overlay: centred unless dragged."""
        left, top, right, bottom = self._margins
        pw = min(self._panel_size.width(), self.width()) - left - right
        ph = min(self._panel_size.height(), self.height()) - top - bottom
        self.panel.resize(max(pw, 1), max(ph, 1))
        if self._panel_pos is None:
            self.center_panel()
        else:
            self.move_panel(self._panel_pos)
        self._apply_mask()

    def _apply_mask(self):
        """Take input only where the panel is.

        The overlay spans the work area so the panel can be positioned
        exactly, but it must not *behave* like a window that size: without
        this mask every click meant for Dolphin lands on the preview
        instead. Masked, the rest of the overlay is not even there as far
        as clicks are concerned — they go to whatever is underneath, as
        they did when the window was panel-sized.
        """
        handle = self.windowHandle()
        if handle is None:
            return  # not created yet; _place_panel runs again after show()
        left, top, right, bottom = self._margins
        # QWindow.setMask(), not QWidget.setMask(): the widget one clips
        # painting as well as input, so shrinking it left the previous,
        # larger panel's pixels on screen with the new panel drawn inside
        # them — a window within a window. The window one is an input hint
        # and nothing more.
        handle.setMask(
            QRegion(
                # Grown by the margins so the drop shadow stays clickable
                # rather than being cut out of the input region.
                self.panel.geometry().adjusted(-left, -top, right, bottom)
            )
        )
        self.clearMask()  # undo any widget-level mask from an older build
        self.update()     # repaint the whole overlay, stale frame included

    def center_panel(self):
        """Centre the panel on the screen itself and forget any drag.

        Centred in global coordinates, not in the overlay: a compositor
        that puts the overlay somewhere other than the work-area origin
        then still leaves the panel dead centre on screen.
        """
        self._panel_pos = None
        screen = self.screen() or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        target = QPoint(
            geo.x() + (geo.width() - self.panel.width()) // 2,
            geo.y() + (geo.height() - self.panel.height()) // 2,
        )
        self.panel.move(self._clamped(self.mapFromGlobal(target)))

    def move_panel(self, pos):
        """Move the panel within the overlay (a titlebar drag)."""
        self._panel_pos = self._clamped(pos)
        self.panel.move(self._panel_pos)

    def _clamped(self, pos) -> QPoint:
        """A panel position kept fully inside the overlay."""
        left, top, right, bottom = self._margins
        return QPoint(
            max(left, min(pos.x(), self.width() - self.panel.width() - right)),
            max(top, min(pos.y(), self.height() - self.panel.height() - bottom)),
        )

    def resizeEvent(self, event):
        # The overlay follows the screen (resolution change, another output).
        super().resizeEvent(event)
        self._place_panel()
        log.debug(
            "overlay %dx%d, panel %dx%d at %d,%d",
            self.width(), self.height(), self.panel.width(),
            self.panel.height(), self.panel.x(), self.panel.y(),
        )

    def _cancel_render(self):
        job = self._render_job
        self._render_job = None
        if job is not None:
            job.cancel()

    def _is_current(self, job, path: str) -> bool:
        """Whether an answer from job is still wanted.

        Workers answer asynchronously, and the user may have moved on in the
        meantime: only the job rendering the panel now — none has replaced
        it — and only for the file the panel now shows, may touch the view.
        Every render callback starts with this; an answer that skipped it
        would paint one file's preview under another's name.
        """
        return (job is not None and job is self._render_job
                and path == self.current_path)

    def clear_content(self):
        self._cancel_render()
        # A table of contents belongs to one document. Cleared here rather
        # than in _clear_widgets(), which also runs mid-render when the
        # page column replaces the loading card — and would throw away a
        # sidebar the worker has already delivered.
        self._toc_entries = []
        if self._toc_job is not None:
            self._toc_job.cancel()
            self._toc_job = None
        if self.media is not None:
            # Killing the worker is the whole teardown: the decoder, the
            # audio stream and the frame buffer all live in that process, so
            # no late signal can reach widgets we are about to destroy.
            self.media.stop()
            self.media.deleteLater()
            self.media = None
        if self.anim_timer is not None:
            self.anim_timer.stop()
            self.anim_timer.deleteLater()
            self.anim_timer = None
        self._clear_widgets()

    def _clear_widgets(self):
        # Widgets only — no process/player teardown. The PDF path swaps its
        # "Loading…" message for the page column while its helper is still
        # streaming, so it must not go through clear_content().
        self._pdf_gen = None
        self._pdf_labels = []  # they are about to be deleted with the view
        self._pdf_overlays = []
        # The sidebar is a child of the view being torn down; the entries
        # themselves belong to the file and are cleared by clear_content().
        self._toc_sidebar = None
        self._toc_body = None
        self._page_scroll = None
        self._page_size = None
        # The find row is a child of the view being torn down, so drop every
        # reference to it rather than leaving Ctrl+F pointed at a dead widget.
        self._find_bar = None
        self._find_scroll = None
        self._find_path = None
        self._find_op = None
        self._find_hits = []
        self._find_of = None
        self._find_at = -1
        if self._find_job is not None:
            self._find_job.cancel()
            self._find_job = None
        self._set_nav_shortcuts(True)
        while self.content.count():
            w = self.content.takeAt(0).widget()
            if w is not None:
                w.deleteLater()

    def open_externally(self):
        if self.current_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.current_path))
            self.dismiss("opened externally")

    def step_sibling(self, delta: int):
        # With a multi-file selection, ← → page through it (like Quick Look
        # on several selected files); otherwise walk the folder's siblings.
        if len(self.selection) > 1:
            self.sel_index = (self.sel_index + delta) % len(self.selection)
            self.show_file(self.selection[self.sel_index])
            return
        if not self.current_path:
            return
        folder = os.path.dirname(self.current_path) or "."
        try:
            names = sorted(
                (n for n in os.listdir(folder) if not n.startswith(".")),
                key=str.lower,
            )
        except OSError:
            return
        if not names:
            return
        cur = os.path.basename(self.current_path)
        idx = names.index(cur) if cur in names else 0
        nxt = names[(idx + delta) % len(names)]
        self.show_files([os.path.join(folder, nxt)])

    # ---------------------------------------------------------------- preview

    def set_title(self, text: str):
        if len(self.selection) > 1:
            text = f"{text}  ·  {self.sel_index + 1}/{len(self.selection)}"
        self.titlebar.title.setText(text)

    def show_files(self, paths, index: int = 0):
        self.selection = [os.path.abspath(p) for p in paths]
        self.sel_index = max(0, min(index, len(self.selection) - 1))
        self.show_file(self.selection[self.sel_index])

    def show_file(self, path: str):
        path = os.path.abspath(path)
        self.current_path = path
        self.clear_content()
        log.info("preview: %s", path)

        name = os.path.basename(path) or path
        self.set_title(name)
        self.titlebar.mode_btn.setVisible(False)  # show_html() re-enables
        self.titlebar.toc_btn.setVisible(False)   # _set_toc() re-enables

        if not os.path.exists(path):
            self.show_message(f"File not found:\n{path}")
        elif os.path.isdir(path):
            self.show_folder(path)
        else:
            mime = self.mime_db.mimeTypeForFile(path).name()
            ext = os.path.splitext(path)[1].lower()
            # This routing is the sandbox enforcement point. Every branch
            # below hands the file to a jailed worker (show_image, show_pdf,
            # show_anim, show_media) or reads plain bytes (text/fallback).
            # The one exception is HTML, which QtWebEngine parses in its own
            # Chromium renderer sandbox rather than in our jail;
            # QUICKVIEW_STRICT_SANDBOX=1 drops it to the source view for
            # anyone who would rather not rely on that.
            allow_webengine = os.environ.get("QUICKVIEW_STRICT_SANDBOX") != "1"
            if mime in ANIM_MIMES:
                self.show_anim(path)
            elif mime.startswith("image/") or ext in LAYERED_EXTENSIONS:
                self.show_image(path)
            elif mime == "application/pdf" or (
                ext in AI_EXTENSIONS and self.is_pdf(path)
            ):
                self.show_pdf(path)
            elif (
                mime == "text/html" or ext in (".html", ".htm")
            ) and allow_webengine:
                self.show_html(path)
            elif mime.startswith(("video/", "audio/")):
                self.show_media(path, video=mime.startswith("video/"))
            elif mime in EPUB_MIMES or ext in EPUB_EXTENSIONS:
                self.show_epub(path)
            elif mime in ARCHIVE_MIMES or ext in ARCHIVE_EXTENSIONS:
                self.show_archive(path, mime)
            elif mime in SPREADSHEET_MIMES or ext in SPREADSHEET_EXTENSIONS or (
                mime in LEGACY_SPREADSHEET_MIMES and self.office_suite_in_use()
            ):
                self.show_sheets(path, mime)
            elif mime in OFFICE_MIMES or (
                mime in SUITE_ONLY_MIMES and self.office_suite_in_use()
            ):
                self.show_office(path, mime)
            elif mime in MARKDOWN_MIMES or ext in MARKDOWN_EXTENSIONS:
                self.show_markdown(path)
            elif mime.startswith("text/") or ext in TEXT_EXTENSIONS:
                self.show_text(path)
            else:
                self.show_fallback(path, mime)

        # Transparent overlay the size of the work area, with the panel
        # centred inside it: the one way to put a preview at a chosen spot
        # under Wayland, which ignores move() outright. Deliberately *not*
        # fullscreen — KWin lowers an inactive fullscreen window below the
        # focused one, so a preview raised without an activation token
        # (from the daemon, not a click) would vanish behind other windows.
        self.fit_overlay()
        self.show()
        self.raise_()
        self.activateWindow()

    def is_pdf(self, path: str) -> bool:
        """Does this file start with %PDF?

        Illustrator has written PDF-compatible .ai files by default since
        version 9 — the artwork is in there as PDF pages, which the existing
        page view renders for free. Older, PostScript-only .ai files are not,
        and get the metadata card as before. Reading four bytes is a sniff
        rather than a parse, so it does not put a decoder back in the daemon;
        QPdfDocument still runs in the jail like every other one.
        """
        try:
            with open(path, "rb") as fh:
                return fh.read(4) == b"%PDF"
        except OSError:
            return False

    def show_message(self, text: str):
        label = QLabel(text)
        label.setAlignment(Qt.AlignCenter)
        label.setWordWrap(True)
        self.content.addWidget(label)
        self.set_panel_size(520, 320)

    def show_fallback(self, path: str, mime: str):
        info = QFileInfo(path)
        icon = self.icon_provider.icon(info)
        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        lay.setAlignment(Qt.AlignCenter)
        pic = QLabel()
        pic.setAlignment(Qt.AlignCenter)
        pic.setPixmap(icon.pixmap(128, 128))
        details = QLabel(
            f"<div align='center'>"
            f"<b>{html.escape(info.fileName())}</b><br><br>"
            f"{html.escape(mime)}<br>"
            f"{human_size(info.size())}<br>"
            f"Modified {info.lastModified().toString('yyyy-MM-dd hh:mm')}"
            f"</div>"
        )
        details.setTextFormat(Qt.RichText)
        lay.addWidget(pic)
        lay.addWidget(details)
        self.content.addWidget(wrap)
        self.set_panel_size(520, 360)


def connect_to_daemon() -> QLocalSocket | None:
    sock = QLocalSocket()
    sock.connectToServer(SOCKET_PATH)
    if not sock.waitForConnected(300):
        return None
    return sock


def forward_to_running_instance(paths: list) -> bool:
    sock = connect_to_daemon()
    if sock is None:
        return False
    # Already-normalized absolute paths, sent through the same request
    # format the other clients use; normalize_arg is idempotent on them,
    # so the daemon re-running it is a no-op.
    sock.write(ipc.encode_request(os.getcwd(), paths))
    sock.flush()
    sock.waitForBytesWritten(500)
    sock.disconnectFromServer()
    return True


def daemon_already_running() -> bool:
    sock = connect_to_daemon()
    if sock is None:
        return False
    sock.disconnectFromServer()
    return True


def main():
    args = sys.argv[1:]
    if "--clear-cache" in args:
        clear_cache()
        return 0
    daemon = "--daemon" in args
    args = [a for a in args if a != "--daemon"]

    paths = [ipc.normalize_arg(raw) for raw in args]
    if not paths and not daemon:
        print(__doc__)
        return 1

    # Fail with a clear message instead of letting QApplication abort —
    # e.g. the systemd unit started before the session env was imported,
    # or `systemctl --user start` from an SSH login. RestartSec in the
    # unit paces the retries so this can't trip the start limit.
    if not (
        os.environ.get("DISPLAY")
        or os.environ.get("WAYLAND_DISPLAY")
        or os.environ.get("QT_QPA_PLATFORM")
    ):
        print(
            "quickview: no DISPLAY or WAYLAND_DISPLAY — graphical session "
            "not up yet?",
            file=sys.stderr,
        )
        return 1

    # QtWebEngine (HTML previews) is imported lazily on first use, which Qt
    # only allows if contexts are shareable from the start.
    QGuiApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    # Draw with Qt's own style, not the desktop's. The panel is painted
    # entirely by the stylesheets below, so a third-party QStyle has nothing
    # to contribute here — but it can still act on the window, and some do:
    # Kvantum reads blurring/blur_translucent from its theme and asks KWin
    # to blur behind any translucent window, which turns the overlay's
    # WA_TranslucentBackground (there for the rounded corners and the drop
    # shadow) into a blur over the whole desktop, and reduce_window_opacity
    # makes the deliberately opaque panel see-through.
    #
    # This only became visible when the installer started preferring a
    # system PySide6: a bundled Qt cannot see /usr/lib/qt6/plugins, so it
    # always fell back to Fusion. Pinning it keeps the two installs
    # identical. Colours are unaffected — panel_theme = breeze follows the
    # Plasma scheme through QApplication.palette(), which the platform
    # theme still provides.
    app.setStyle("Fusion")
    app.setApplicationName("QuickView")
    # Stay resident after the window is dismissed so the next preview is
    # instant — Qt/Python startup only ever happens once.
    app.setQuitOnLastWindowClosed(False)

    # Single instance: forward the paths to a running viewer, which toggles
    # or switches the preview — like pressing Space again in Finder.
    if paths and forward_to_running_instance(paths):
        return 0
    if daemon and not paths and daemon_already_running():
        return 0

    setup_logging()
    log.info("daemon starting (pid %d), logging to %s", os.getpid(), LOG_FILE)
    # A commented template, so the settings are discoverable without going
    # to the README. Only ever created, never rewritten.
    if config.write_default_if_missing():
        log.info("wrote default settings to %s", config.CONFIG_FILE)

    # A name containing '/' makes QLocalServer use it as the literal socket
    # path instead of placing it in QDir::tempPath(), keeping the location
    # independent of TMPDIR and identical to what client.py computes.
    QLocalServer.removeServer(SOCKET_PATH)
    server = QLocalServer()
    if not server.listen(SOCKET_PATH):
        # Without the socket every later invocation spawns another daemon;
        # better to fail loudly and let systemd retry.
        log.error(
            "cannot listen on %s: %s", SOCKET_PATH, server.errorString()
        )
        return 1

    viewer = QuickView()
    viewer.watch_settings()

    def on_connection():
        conn = server.nextPendingConnection()
        if conn is None:
            return
        # A large selection arrives in several chunks; accumulate until the
        # client closes its end (that close is the message framing) instead
        # of acting on the first readyRead and truncating the path list.
        buf = bytearray()

        def on_ready():
            buf.extend(bytes(conn.readAll()))

        def on_done():
            buf.extend(bytes(conn.readAll()))
            conn.deleteLater()
            new_paths = ipc.decode_request(bytes(buf))
            if not new_paths:
                return
            if (
                len(new_paths) == 1
                and viewer.isVisible()
                and viewer.current_path
                # realpath, so re-triggering through a symlink still toggles
                and os.path.realpath(new_paths[0])
                == os.path.realpath(viewer.current_path)
            ):
                viewer.dismiss("same path sent again")
            else:
                viewer.show_files(new_paths)

        conn.readyRead.connect(on_ready)
        conn.disconnected.connect(on_done)

        def on_guard_timeout():
            # The message is incomplete by definition here — detach on_done
            # first so the forced close drops the buffer instead of acting
            # on a truncated path list.
            conn.disconnected.disconnect(on_done)
            conn.abort()
            conn.deleteLater()

        # A client that never closes must not hold the slot open forever;
        # the timer dies with conn, so it can't fire on a deleted socket.
        guard = QTimer(conn)
        guard.setSingleShot(True)
        guard.timeout.connect(on_guard_timeout)
        guard.start(2000)

    server.newConnection.connect(on_connection)
    # Boot the first workers now, while the user is still reaching for the
    # keyboard: the ~150 ms Qt import in the jail is what previews used to
    # wait on, and a resident daemon can pay it ahead of time.
    QTimer.singleShot(0, viewer.pool.prime)
    app.aboutToQuit.connect(viewer.pool.shutdown)
    if paths:
        viewer.show_files(paths)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
