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

"""Source and plain text, HTML, folders and archives.
"""

import json
import os

# What the daemon asks the renderers: which engine the workers will use for
# office documents, for the cache key, and the bounds a workbook is held to.
# renderers imports nothing at module level, so this loads no parser here.

from PySide6.QtCore import (
    Qt, QUrl, QThreadPool, QFileInfo,
)
from PySide6.QtGui import (
    QIcon, QColor, QTextCharFormat, QTextCursor,
)
from PySide6.QtWidgets import (
    QFileIconProvider, QFrame, QLabel, QPlainTextEdit, QVBoxLayout, QWidget,
)

from common import (
    human_size,
    log,
    MARKDOWN_EXTENSIONS,
    MARKDOWN_MIMES,
    OFFICE_MIMES,
    SETTINGS,
    text_limit,
)
from sandbox import (
    FileReader,
    SandboxJob,
)


class TextViewMixin:
    """Source and plain text, HTML, folders and archives.

    Mixed into QuickView, whose state (self.content, the render job,
    the current path…) these methods use; not usable on its own.
    """

    # ---------------------------------------------------------------- text
    # Text goes through the jail like everything else, for one reason: the
    # highlighter. Pygments lexers are regexes, and a file written to make
    # one backtrack would wedge whichever process runs it — which must not
    # be the one holding the window and the IPC socket. The worker sends
    # back the text plus colour spans; the daemon paints ranges and parses
    # nothing. If the sandbox is unavailable, show_text_direct() below reads
    # the bytes here instead, unhighlighted.

    def show_text(self, path: str):
        self.show_message("Loading preview…")
        # Size the window now, not when the text lands. show_message() sizes
        # the panel for a short message, and a window that is mapped small
        # and resized a moment later can keep the small size on Wayland —
        # which is what made the first open of a text file look cramped.
        self._size_for_text()
        state = {"job": None, "shown": False}

        def on_frame(payload: bytes):
            if self._render_job is not state["job"] or path != self.current_path:
                return
            try:
                doc = json.loads(payload)
                text = doc["text"]
                spans = doc.get("spans") or []
                styles = doc.get("styles") or []
            except (ValueError, TypeError, KeyError):
                log.warning("text worker sent a malformed payload: %s", path)
                return
            if doc.get("truncated"):
                text += "\n\n[... truncated ...]"
            self._clear_widgets()
            self._show_text_widget(text, spans, styles)
            state["shown"] = True

        def on_done(ok: bool, error: str):
            if self._render_job is not state["job"] or path != self.current_path:
                return
            self._render_job = None
            if not state["shown"]:
                log.debug(
                    "text worker unavailable (%s) — reading in-process", error[:200]
                )
                self.show_text_direct(path)

        state["job"] = self._render_job = SandboxJob(
            self.pool, path,
            {
                "op": "text", "name": os.path.basename(path),
                "limit": text_limit(), "style": SETTINGS["code_style"],
            },
            on_frame, on_done, self,
        )

    def show_text_direct(self, path: str):
        """The unhighlighted fallback: read the bytes here, off the event
        loop. No parser is involved (plain bytes, capped at 1 MiB), but a
        file on a stalled NFS or FUSE mount would freeze the window and the
        daemon socket with it."""

        def show(data: bytes, error: str):
            if path != self.current_path:
                return  # the user moved on while the read was in flight
            if error:
                self._clear_widgets()
                self.show_message(error)
                return
            truncated = len(data) > text_limit()
            text = data[:text_limit()].decode("utf-8", errors="replace")
            if truncated:
                text += "\n\n[... truncated ...]"
            self._clear_widgets()
            self._show_text_widget(text)

        # Every in-flight reader is held, not just the newest: previewing a
        # second file while the first is still blocked on a stalled mount
        # used to drop the only reference to a running reader.
        reader = FileReader(path, text_limit() + 1)
        reader.done.connect(show)
        reader.done.connect(lambda *_: self._text_readers.discard(reader))
        self._text_readers.add(reader)
        QThreadPool.globalInstance().start(reader.run)

    def _size_for_text(self):
        avail = self.screen_avail()
        self.set_panel_size(int(avail.width() * 0.5), int(avail.height() * 0.75))

    def _show_text_widget(self, text: str, spans=(), styles=()):
        edit = QPlainTextEdit()
        edit.setReadOnly(True)
        edit.setPlainText(text)
        edit.setFrameShape(QFrame.NoFrame)
        if spans and styles:
            self._paint_spans(edit, spans, styles)
        self.content.addWidget(edit)
        self._size_for_text()

    @staticmethod
    def _paint_spans(edit, spans, styles):
        """Colour [start, length, style] ranges over the document.

        The offsets come from a worker and are applied to a document this
        process built, so they are checked rather than trusted: a bad index
        or a range past the end is skipped, not clamped into something that
        paints the wrong text.
        """
        formats = []
        for colour in styles:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(colour))
            formats.append(fmt)
        doc = edit.document()
        end = doc.characterCount() - 1
        cursor = QTextCursor(doc)
        cursor.beginEditBlock()
        for span in spans:
            try:
                start, length, index = span
            except (TypeError, ValueError):
                continue
            if not 0 <= index < len(formats):
                continue
            if not 0 <= start < end or length <= 0 or start + length > end:
                continue
            cursor.setPosition(start)
            cursor.setPosition(start + length, QTextCursor.KeepAnchor)
            cursor.setCharFormat(formats[index])
        cursor.endEditBlock()

    # -------------------------------------------------------------- html
    # Rendered with QtWebEngine, hardened for untrusted files: JavaScript
    # and plugins off, every request outside file:/data: blocked before it
    # leaves the process (no phoning home), and an off-the-record profile
    # so nothing persists. Chromium's own multi-process sandbox still wraps
    # the renderer. The titlebar button flips to the plain source view;
    # QUICKVIEW_STRICT_SANDBOX=1 skips rendering entirely (code view only).

    def show_html(self, path: str):
        btn = self.titlebar.mode_btn
        btn.setVisible(True)
        if self._html_rendered:
            btn.setText("Code")
            self._show_html_rendered(path)
        else:
            btn.setText("Preview")
            self.show_text(path)

    def toggle_mode(self):
        """The titlebar's second button: HTML rendered/source, office
        thumbnail/text. Which one it means depends on what is open."""
        path = self.current_path
        if not path:
            return
        mime = self.mime_db.mimeTypeForFile(path).name()
        ext = os.path.splitext(path)[1].lower()
        if mime in OFFICE_MIMES:
            self._office_text = not self._office_text
            cached = self._office_doc
            if self._office_text and cached and cached[0] == path:
                self._render_office(path, cached[1])  # no second decode
                return
        elif mime in MARKDOWN_MIMES or ext in MARKDOWN_EXTENSIONS:
            self._md_rendered = not self._md_rendered
        else:
            self._html_rendered = not self._html_rendered
        self.show_file(path)

    def _show_html_rendered(self, path: str):
        from PySide6.QtWebEngineCore import (
            QWebEnginePage, QWebEngineProfile, QWebEngineSettings,
            QWebEngineUrlRequestInterceptor,
        )
        from PySide6.QtWebEngineWidgets import QWebEngineView

        class LocalOnlyInterceptor(QWebEngineUrlRequestInterceptor):
            def interceptRequest(self, info):
                if info.requestUrl().scheme() not in ("file", "data"):
                    info.block(True)

        if self._web_profile is None:
            # One off-the-record profile for the daemon's lifetime, parented
            # to the window: pages (parented to their view) can never
            # outlive it, which a per-view profile can't guarantee — Qt
            # destroys siblings in creation order and warns "Expect
            # troubles!" when the profile goes first.
            self._web_profile = QWebEngineProfile(self)
            self._web_interceptor = LocalOnlyInterceptor(self._web_profile)
            self._web_profile.setUrlRequestInterceptor(self._web_interceptor)
            settings = self._web_profile.settings()
            for attr in (
                QWebEngineSettings.WebAttribute.JavascriptEnabled,
                QWebEngineSettings.WebAttribute.PluginsEnabled,
                QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
            ):
                settings.setAttribute(attr, False)

        view = QWebEngineView()
        page = QWebEnginePage(self._web_profile, view)
        view.setPage(page)
        view.load(QUrl.fromLocalFile(path))
        self.content.addWidget(view)
        avail = self.screen_avail()
        self.set_panel_size(int(avail.width() * 0.6), int(avail.height() * 0.8))

    def show_folder(self, path: str):
        try:
            entries = sorted(
                (e for e in os.listdir(path) if not e.startswith(".")),
                key=str.lower,
            )
        except OSError as exc:
            self.show_message(str(exc))
            return
        icon = self.icon_provider.icon(QFileIconProvider.IconType.Folder)
        listing = "\n".join(entries[:200])
        if len(entries) > 200:
            listing += f"\n... and {len(entries) - 200} more"

        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        head = QLabel()
        head.setAlignment(Qt.AlignCenter)
        head.setPixmap(icon.pixmap(96, 96))
        sub = QLabel(f"{len(entries)} items")
        sub.setAlignment(Qt.AlignCenter)
        body = QPlainTextEdit()
        body.setReadOnly(True)
        body.setPlainText(listing)
        body.setFrameShape(QFrame.NoFrame)
        lay.addWidget(head)
        lay.addWidget(sub)
        lay.addWidget(body, 1)
        self.content.addWidget(wrap)
        self.set_panel_size(520, 560)

    # ------------------------------------------------------------ archives
    # A listing, not an extraction: the worker reads headers only, so an
    # archive that expands to terabytes costs nothing. zip and tar go through
    # the standard library; rar, 7z and the rest through bsdtar/7z/unrar,
    # which read the archive from /dev/fd — the jail has the descriptor and
    # no filesystem to find a path in.

    def show_archive(self, path: str, mime: str):
        self.show_message("Loading preview…")
        state = {"job": None, "shown": False}

        def on_frame(payload: bytes):
            if self._render_job is not state["job"] or path != self.current_path:
                return
            try:
                listing = json.loads(payload)
                entries = listing["entries"]
            except (ValueError, TypeError, KeyError):
                log.warning("archive worker sent a malformed listing: %s", path)
                return
            self._clear_widgets()
            self._show_archive_widget(path, listing, entries)
            state["shown"] = True

        def on_done(ok: bool, error: str):
            if self._render_job is not state["job"] or path != self.current_path:
                return
            self._render_job = None
            if not state["shown"]:
                # Encrypted, corrupt, or a format nothing here can list.
                log.debug("no listing for %s (%s)", path, error[:200])
                self._clear_widgets()
                self.show_fallback(path, mime)

        state["job"] = self._render_job = SandboxJob(
            self.pool, path,
            {"op": "archive", "name": os.path.basename(path)},
            on_frame, on_done, self,
        )

    def _show_archive_widget(self, path: str, listing: dict, entries: list):
        rows = []
        for entry in entries:
            try:
                name, size = entry
            except (TypeError, ValueError):
                continue
            rows.append(
                f"{name}    {human_size(size)}" if size else str(name)
            )
        if listing.get("truncated"):
            # count is a floor, not a total, when the lister stopped early —
            # subtracting from it would invent a number.
            if listing.get("count_exact", True):
                rows.append(f"... and {listing.get('count', 0) - len(rows)} more")
            else:
                rows.append("... and more")

        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        head = QLabel()
        head.setAlignment(Qt.AlignCenter)
        # The themed mime icon (a package for archives), falling back to the
        # provider's generic one when the icon theme has nothing.
        mime = self.mime_db.mimeTypeForFile(path)
        themed = QIcon.fromTheme(mime.iconName())
        if themed.isNull():
            themed = QIcon.fromTheme(mime.genericIconName())
        if themed.isNull():
            themed = self.icon_provider.icon(QFileInfo(path))
        head.setPixmap(themed.pixmap(96, 96))
        count = listing.get("count", len(rows))
        exact = listing.get("count_exact", True)
        summary = f"{count} items" if exact else f"{count}+ items"
        if listing.get("total"):
            size = human_size(listing["total"])
            summary += f"  ·  {size} uncompressed" if exact else (
                f"  ·  over {size} uncompressed"
            )
        sub = QLabel(summary)
        sub.setAlignment(Qt.AlignCenter)
        body = QPlainTextEdit()
        body.setReadOnly(True)
        body.setPlainText("\n".join(rows))
        body.setFrameShape(QFrame.NoFrame)
        lay.addWidget(head)
        lay.addWidget(sub)
        lay.addWidget(body, 1)
        self.content.addWidget(wrap)
        self.set_panel_size(640, 620)
