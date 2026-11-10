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

"""Paged documents: PDFs, Markdown, EPUB books, the contents
sidebar and find-in-document.
"""

import json
import os
from string import Template

# What the daemon asks the renderers: which engine the workers will use for
# office documents, for the cache key, and the bounds a workbook is held to.
# renderers imports nothing at module level, so this loads no parser here.

from PySide6.QtCore import (
    Qt, QPoint, QTimer,
)
from PySide6.QtGui import (
    QImage, QPixmap, QColor,
)
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QPushButton,
    QScrollArea, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from common import (
    cache_key,
    cache_read,
    cache_read_head,
    cache_remove,
    cache_write,
    log,
    png_size,
    SETTINGS,
    TOC_WIDTH,
)
from sandbox import (
    SandboxJob,
)
from widgets import (
    MatchOverlay,
)


class DocumentViewMixin:
    """Paged documents: PDFs, Markdown, EPUB books, the contents

    Mixed into QuickView, whose state (self.content, the render job,
    the current path…) these methods use; not usable on its own.
    """

    # -------------------------------------------------------------- pdf
    # PDFs render out of process like still images: render_pdf.py streams
    # page PNGs from inside the bubblewrap jail and the daemon shows page 1
    # the moment it arrives. Pages land in the disk cache individually, so
    # a repeat view never touches the PDF parser at all.

    def show_pdf(self, path: str):
        avail = self.screen_avail()
        page_w = max(int(avail.width() * 0.55) - 44, 400)
        self._page_scale = scale = self.page_scale()
        try:
            st = os.stat(path)
        except OSError as exc:
            self.show_message(str(exc))
            return

        def page_key(i: int) -> str:
            return cache_key(path, st, page_w, 0, f"pdf{i}@{scale:g}")

        # The bookmarks, for the sidebar. Cached like a page is, because
        # the alternative is a second worker on every open of every PDF —
        # and most of the cost of one is the spawn, not the parse.
        toc_key = cache_key(path, st, page_w, 0, "toc2")
        cached_toc = cache_read(toc_key)
        if cached_toc is not None:
            try:
                self._toc_entries = json.loads(cached_toc)
            except ValueError:
                cache_remove(toc_key)
                cached_toc = None
        if cached_toc is None:
            self._fetch_outline(path, toc_key, page_w)

        png0 = cache_read(page_key(0))
        img0 = QImage.fromData(png0) if png0 is not None else QImage()
        total = 0
        if not img0.isNull():
            try:
                total = int(img0.text("QuickView:PageCount"))
            except ValueError:
                pass
        if total > 0:
            log.debug("disk cache hit (pdf): %s", path)
            self._pdf_show_cached(path, page_key, page_w, total, img0)
        else:
            if png0 is not None:
                cache_remove(page_key(0))
            self._pdf_render(path, page_key, page_w)

    def _pdf_begin_view(self, path: str, total: int, sizes: list,
                        op: str = "pdf", page_w: int = 0):
        """Swap in the page column, at its full height from the start.

        Every page gets a placeholder of its real size before any pixels
        arrive, so the scrollable range is final on the first paint. Adding
        pages as they decoded meant the range grew for a second or two, and
        a reader who scrolled in that window was clamped to a two-page
        document and left near the top of a thirty-page one — which looks
        exactly like the view scrolling itself back up.
        """
        self._clear_widgets()
        col = QWidget()
        lay = QVBoxLayout(col)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(12)
        self._pdf_labels = []
        self._pdf_overlays = []
        # Sizes come from the page images, which are in device pixels; the
        # column is laid out in logical ones.
        ratio = self._page_scale
        for w, h in sizes:
            w, h = round(w / ratio), round(h / ratio)
            label = QLabel()
            label.setFixedSize(w, h)
            # An unfilled page, before its render arrives.
            label.setStyleSheet(f"background: {self.theme['surface_alt']};")
            lay.addWidget(label, 0, Qt.AlignHCenter)
            self._pdf_labels.append(label)
            overlay = MatchOverlay(label)
            overlay.setGeometry(0, 0, w, h)
            self._pdf_overlays.append(overlay)
        lay.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"background: {self.theme['bg']};")
        scroll.setWidget(col)
        # Wrapper so the find row can sit above the pages and scroll with
        # neither of them, and the contents sidebar beside both.
        holder = QWidget()
        hlay = QVBoxLayout(holder)
        hlay.setContentsMargins(0, 0, 0, 0)
        hlay.setSpacing(0)
        find_bar = self._build_find_bar()
        hlay.addWidget(find_bar)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(scroll, 1)
        hlay.addLayout(body, 1)
        self.content.addWidget(holder)
        self._page_scroll = scroll
        self._toc_body = body
        # Find works for documents whose text the jail can locate on a
        # page: a PDF through its text layer, a book through the layout it
        # was rendered from. Office documents share this view but have
        # neither, so for them the row stays hidden.
        self._find_op = {"pdf": "pdfsearch", "epub": "epubsearch"}.get(op)
        if self._find_op:
            self._find_bar = find_bar
            self._find_scroll = scroll
            self._find_path = path
            self._find_page_w = page_w
        else:
            find_bar.hide()
        avail = self.screen_avail()
        self._page_size = (
            int(avail.width() * 0.55), int(avail.height() * 0.85)
        )
        # Built after the panel has a size so the tree is laid out once.
        self._refresh_toc()
        self.titlebar.toc_btn.setVisible(bool(self._toc_entries))
        self.titlebar.toc_btn.setChecked(
            self._toc_open and bool(self._toc_entries)
        )
        self._size_page_view()
        pages = f"{total} pages"
        if total > SETTINGS["pdf_max_pages"]:
            pages += f" (showing first {SETTINGS['pdf_max_pages']})"
        self.set_title(f"{os.path.basename(path)}  —  {pages}")
        return lay

    # ------------------------------------------------------------ markdown
    # Two views of the same file, on the titlebar button: rendered pages by
    # default, the highlighted source behind "Code". The render goes through
    # the page pipeline — Qt's Markdown parser runs in the jail and the
    # daemon receives page images, exactly as it does for a PDF.

    def show_markdown(self, path: str):
        btn = self.titlebar.mode_btn
        btn.setVisible(True)
        if not self._md_rendered:
            btn.setText("Preview")
            self.show_text(path)
            return
        btn.setText("Code")

        avail = self.screen_avail()
        page_w = max(int(avail.width() * 0.55) - 44, 400)
        self._page_scale = scale = self.page_scale()
        try:
            st = os.stat(path)
        except OSError as exc:
            self.show_message(str(exc))
            return

        def page_key(i: int) -> str:
            return cache_key(path, st, page_w, 0, f"md-{SETTINGS['book_theme']}{i}@{scale:g}")

        toc_key = cache_key(path, st, page_w, 0, "toc2")
        cached_toc = cache_read(toc_key)
        if cached_toc is not None:
            try:
                self._toc_entries = json.loads(cached_toc)
            except ValueError:
                cache_remove(toc_key)
                cached_toc = None

        png0 = cache_read(page_key(0))
        img0 = QImage.fromData(png0) if png0 is not None else QImage()
        total = 0
        if not img0.isNull():
            try:
                total = int(img0.text("QuickView:PageCount"))
            except ValueError:
                pass
        extra = {"name": os.path.basename(path), "theme": SETTINGS["book_theme"]}
        # Pages and headings are produced together, so a cache holding one
        # without the other is half a preview: re-render instead. The
        # contents entry is written even when a document has no headings at
        # all, so "no entry" means unknown rather than none.
        if total > 0 and cached_toc is not None:
            log.debug("disk cache hit (markdown): %s", path)
            self._pdf_show_cached(
                path, page_key, page_w, total, img0, op="markdown", extra=extra
            )
            return
        if png0 is not None:
            cache_remove(page_key(0))
        self._pdf_render(
            path, page_key, page_w, op="markdown", extra=extra, toc_key=toc_key
        )

    # ---------------------------------------------------------------- epub
    # A book goes through the page pipeline PDFs and office documents use:
    # the jail lays the spine out as pages and streams them, and the header
    # of that stream carries the table of contents, which is a property of
    # the layout that produced the pages and so can only be computed there.

    def show_epub(self, path: str):
        avail = self.screen_avail()
        page_w = max(int(avail.width() * 0.55) - 44, 400)
        self._page_scale = scale = self.page_scale()
        try:
            st = os.stat(path)
        except OSError as exc:
            self.show_message(str(exc))
            return

        def page_key(i: int) -> str:
            return cache_key(path, st, page_w, 0, f"epub-{SETTINGS['book_theme']}{i}@{scale:g}")

        toc_key = cache_key(path, st, page_w, 0, "toc2")
        cached_toc = cache_read(toc_key)
        if cached_toc is not None:
            try:
                self._toc_entries = json.loads(cached_toc)
            except ValueError:
                cache_remove(toc_key)

        png0 = cache_read(page_key(0))
        img0 = QImage.fromData(png0) if png0 is not None else QImage()
        total = 0
        if not img0.isNull():
            try:
                total = int(img0.text("QuickView:PageCount"))
            except ValueError:
                pass
        extra = {"name": os.path.basename(path), "theme": SETTINGS["book_theme"]}
        # A cached book with no cached contents is a cache from before the
        # sidebar existed (or a pruned entry): re-render rather than show a
        # book with its chapters missing, since the two are produced
        # together and there is no cheaper way to get one back. An empty
        # contents *entry* is an answer, though — see show_markdown.
        if total > 0 and cached_toc is not None:
            log.debug("disk cache hit (epub): %s", path)
            self._pdf_show_cached(
                path, page_key, page_w, total, img0, op="epub", extra=extra
            )
            return
        if png0 is not None:
            cache_remove(page_key(0))
        self._pdf_render(
            path, page_key, page_w, op="epub", extra=extra, toc_key=toc_key,
        )

    # ------------------------------------------------------------ contents
    # One sidebar for two kinds of document: a PDF's bookmarks (op
    # "pdfoutline") and a book's chapters (folded into the "epub" render's
    # header). Both arrive as [{title, level, page}] and are shown by the
    # same tree, so the reader gets the same button in the same corner
    # whichever one is open.

    TOC_STYLE = Template("""
        QWidget { background-color: $bg_alt; }
        #tocHead {
            color: $text_head; font-size: 11px; font-weight: 600;
            padding: 10px 12px 6px 12px; letter-spacing: 1px;
        }
        QTreeWidget {
            background-color: $bg_alt; color: $tree_text; border: none;
            border-right: 1px solid $line; font-size: 12px;
            outline: none; padding: 6px 0;
        }
        QTreeWidget::item { padding: 4px 2px; border-radius: 4px; }
        QTreeWidget::item:hover { background-color: $tree_hover; }
        QTreeWidget::item:selected {
            background-color: $sel_tree; color: $accent_text;
        }
        QTreeWidget::branch { background: transparent; }
        QScrollBar:vertical { background: $bg_alt; border: none; width: 10px; }
        QScrollBar::handle:vertical {
            background: $scroll_handle; border-radius: 5px; min-height: 30px;
        }
        QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
        QScrollBar::add-page, QScrollBar::sub-page { background: none; }
    """)

    def _fetch_outline(self, path: str, toc_key: str, page_w: int):
        """Ask the jail for a PDF's bookmarks, alongside the page render.

        page_w goes with the request because a bookmark's destination comes
        back as an offset into the rendered page, which only means anything
        at the width the pages are rendered at.
        """
        if self._toc_job is not None:
            self._toc_job.cancel()
            self._toc_job = None
        got = {"blob": None, "job": None}

        def on_frame(payload: bytes):
            got["blob"] = payload

        def on_done(ok: bool, error: str):
            if self._toc_job is not got["job"]:
                return
            self._toc_job = None
            if not ok:
                log.debug("no outline for %s (%s)", path, error[:200])
                return
            try:
                entries = json.loads(got["blob"] or b"[]")
            except ValueError:
                log.warning("outline worker sent malformed json: %s", path)
                return
            self._set_toc(path, entries, toc_key)

        got["job"] = self._toc_job = SandboxJob(
            self.pool, path,
            {"op": "pdfoutline", "page_w": page_w,
             "max_pages": SETTINGS["pdf_max_pages"]},
            on_frame, on_done, self,
        )

    def _set_toc(self, path: str, entries: list, toc_key: str = None):
        """Adopt a table of contents, cache it, and show its button."""
        if path != self.current_path:
            return  # the reader moved on while the worker was parsing
        entries = [e for e in entries if isinstance(e, dict)]
        self._toc_entries = entries
        if toc_key:
            # Cached even when empty: that a document has no contents is
            # itself the answer, and one worth not asking for twice.
            cache_write(toc_key, json.dumps(entries).encode())
        self.titlebar.toc_btn.setVisible(bool(entries))
        self.titlebar.toc_btn.setChecked(self._toc_open and bool(entries))
        self._refresh_toc()

    def _refresh_toc(self):
        """Rebuild the sidebar for whatever is in _toc_entries."""
        if self._toc_body is None:
            return  # nothing that can hold a sidebar is showing
        if self._toc_sidebar is not None:
            self._toc_body.removeWidget(self._toc_sidebar)
            self._toc_sidebar.deleteLater()
            self._toc_sidebar = None
        if not self._toc_entries:
            return
        self._toc_sidebar = self._build_toc(self._toc_entries)
        self._toc_body.insertWidget(0, self._toc_sidebar)
        self._toc_sidebar.setVisible(self._toc_open)
        self._size_page_view()

    def _build_toc(self, entries: list) -> QWidget:
        tree = QTreeWidget()
        tree.setHeaderHidden(True)
        tree.setColumnCount(2)
        tree.setIndentation(12)
        tree.setFocusPolicy(Qt.NoFocus)  # keys stay with the preview
        # Levels come from the document, so they can skip a step (a level-3
        # bookmark under a level-1 one) or start deep. Each entry hangs off
        # the nearest shallower one that came before it, which is what the
        # document meant however it numbered things.
        last = {}
        for entry in entries:
            title = str(entry.get("title", "")).strip()
            if not title:
                continue
            try:
                page = int(entry.get("page", 0))
                level = max(0, int(entry.get("level", 0)))
            except (TypeError, ValueError):
                continue
            parent = None
            for depth in range(level - 1, -1, -1):
                if depth in last:
                    parent = last[depth]
                    break
            item = QTreeWidgetItem(parent) if parent else QTreeWidgetItem(tree)
            item.setText(0, title)
            item.setText(1, str(page + 1))
            item.setToolTip(0, f"{title}  ·  page {page + 1}")
            item.setForeground(1, QColor(self.theme["text_muted"]))
            item.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
            try:
                offset = max(0, int(entry.get("y", 0)))
            except (TypeError, ValueError):
                offset = 0
            item.setData(0, Qt.UserRole, (page, offset))
            last[level] = item
            for deeper in [d for d in last if d > level]:
                del last[deeper]
        tree.expandAll()
        # The page-number column takes what it needs and the titles get the
        # rest. Without turning the last section's stretch off, Qt gives the
        # slack to the numbers and elides every title at half width.
        tree.header().setStretchLastSection(False)
        tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        tree.itemClicked.connect(self._toc_clicked)
        tree.itemActivated.connect(self._toc_clicked)

        panel = QWidget()
        panel.setStyleSheet(self.TOC_STYLE.substitute(self.theme))
        panel.setFixedWidth(TOC_WIDTH)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        head = QLabel("Contents")
        head.setObjectName("tocHead")
        lay.addWidget(head)
        lay.addWidget(tree, 1)
        return panel

    def _toc_clicked(self, item, _column: int = 0):
        where = item.data(0, Qt.UserRole)
        if isinstance(where, (tuple, list)) and len(where) == 2:
            self.scroll_to_page(int(where[0]), int(where[1]))

    def toggle_toc(self):
        """The titlebar's ☰ : show or hide the chapter sidebar."""
        self._toc_open = not self._toc_open
        self.titlebar.toc_btn.setChecked(self._toc_open)
        if self._toc_sidebar is not None:
            self._toc_sidebar.setVisible(self._toc_open)
        self._size_page_view()

    def scroll_to_page(self, page: int, offset: int = 0):
        """Put a point on a page at the top of the view.

        offset is how far down that page the entry actually sits. Scrolling
        to the top of the page is not enough: a page here is routinely
        taller than the window (2326 px against 1451 on a 3072x1728 screen),
        so five sections of one chapter would all scroll to the same place
        and clicking any of them would look like nothing happening.
        """
        if self._page_scroll is None or not 0 <= page < len(self._pdf_labels):
            return
        label = self._pdf_labels[page]
        top = label.mapTo(self._page_scroll.widget(), QPoint(0, 0)).y()
        # Never past the end of the page it belongs to.
        top += max(0, min(offset, label.height() - 1))
        bar = self._page_scroll.verticalScrollBar()
        bar.setValue(max(0, top - 14))  # 14 = the column's top margin

    def _size_page_view(self):
        """Size the panel for the page column, plus the sidebar if open."""
        if self._page_size is None:
            return
        w, h = self._page_size
        showing = self._toc_sidebar is not None and self._toc_open
        self.set_panel_size(w + (TOC_WIDTH if showing else 0), h)

    # ------------------------------------------------------------ find
    # Ctrl+F over a PDF. The daemon owns no parser, so the query goes to a
    # jailed worker (op "pdfsearch") which answers with match rectangles
    # already in page pixels; everything here is navigation and painting.

    def _set_nav_shortcuts(self, on: bool):
        for sc in self._nav_shortcuts:
            sc.setEnabled(on)

    def open_find(self):
        """Ctrl+F: reveal the find row, if a PDF is what is showing."""
        if self._find_bar is None:
            return  # not a PDF (or nothing open) — Ctrl+F does nothing
        self._find_bar.show()
        self._find_input.setFocus()
        self._find_input.selectAll()

    def close_find(self):
        if self._find_bar is None:
            return
        self._find_bar.hide()
        self._set_nav_shortcuts(True)
        self._find_hits = []
        self._find_of = None
        self._find_at = -1
        self._paint_matches()
        self._find_label.setText("")

    def _build_find_bar(self) -> QWidget:
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 8, 14, 0)
        row.setSpacing(8)
        self._find_input = QLineEdit()
        self._find_input.setPlaceholderText("Find in document…")
        self._find_input.setStyleSheet(
            "QLineEdit {{ background:{surface_alt}; color:{text};"
            " border:1px solid {input_border}; border-radius:{radius_btn};"
            " padding:5px 8px; }}".format(**self.theme)
        )
        # The nav shortcuts are single keys and outrank this field's own key
        # events, so they are off precisely while it holds focus.
        self._find_input.focusInEvent = self._wrap_focus(
            self._find_input.focusInEvent, False
        )
        self._find_input.focusOutEvent = self._wrap_focus(
            self._find_input.focusOutEvent, True
        )
        self._find_input.returnPressed.connect(self._find_submit)
        self._find_input.keyPressEvent = self._find_keys(
            self._find_input.keyPressEvent
        )
        self._find_label = QLabel("")
        self._find_label.setStyleSheet(f"color:{self.theme['text_faint']};")
        prev_btn = QPushButton("‹")
        next_btn = QPushButton("›")
        close_btn = QPushButton("✕")
        for b, fn in (
            (prev_btn, lambda: self._find_step(-1)),
            (next_btn, lambda: self._find_step(+1)),
            (close_btn, self.close_find),
        ):
            b.setFixedWidth(28)
            b.setStyleSheet(
                "QPushButton {{ background:{surface_alt}; color:{text};"
                " border:1px solid {input_border};"
                " border-radius:{radius_btn}; padding:4px; }}"
                "QPushButton:hover {{ background:{input_hover}; }}"
                .format(**self.theme)
            )
            b.setFocusPolicy(Qt.NoFocus)  # never steal focus from the field
            b.clicked.connect(fn)
        row.addWidget(self._find_input, 1)
        row.addWidget(self._find_label)
        row.addWidget(prev_btn)
        row.addWidget(next_btn)
        row.addWidget(close_btn)
        bar.hide()
        return bar

    def _find_keys(self, original):
        """Escape closes the find row; Enter steps, Shift+Enter steps back.

        Escape is handled here rather than by the window shortcut because
        that one is disabled while this field has focus — and it should be:
        the first Escape belongs to the find row, only the second to the
        preview.
        """
        def handler(event):
            if event.key() == Qt.Key_Escape:
                self.close_find()
                self.setFocus()
                return
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                if self._find_hits and self._find_input.text() == self._find_of:
                    # Same query as the standing results: step, don't re-run.
                    self._find_step(
                        -1 if event.modifiers() & Qt.ShiftModifier else +1
                    )
                    return
                self._find_submit()
                return
            original(event)
        return handler

    def _wrap_focus(self, original, nav_on: bool):
        def handler(event):
            self._set_nav_shortcuts(nav_on)
            original(event)
        return handler

    def _find_submit(self):
        query = self._find_input.text()
        if not query or self._find_path is None:
            return
        self._find_label.setText("…")
        self._find_of = query
        got = {"blob": None}

        def on_frame(data: bytes):
            got["blob"] = data

        def on_done(ok: bool, error: str):
            self._find_job = None
            try:
                payload = json.loads(got["blob"]) if ok and got["blob"] else {}
            except (ValueError, TypeError):
                payload = {}
            if not ok:
                log.warning("find failed: %s (%s)", self._find_path, error[:200])
            self._find_hits = payload.get("matches", [])
            self._find_at = 0 if self._find_hits else -1
            if not self._find_hits:
                self._find_label.setText("no matches")
            else:
                self._find_scroll_to(self._find_at)
            self._paint_matches()
            self._update_find_label(
                payload.get("capped", False), payload.get("loose", False)
            )

        job = {"op": self._find_op, "query": query,
               "page_w": self._find_page_w, "max_pages": SETTINGS["pdf_max_pages"]}
        if self._find_op == "epubsearch":
            # The book has to be laid out again to place a match, and a
            # different palette is a different style sheet — so the search
            # is told which one the pages on screen were rendered with.
            job["theme"] = SETTINGS["book_theme"]
        self._find_job = SandboxJob(
            self.pool, self._find_path, job, on_frame, on_done, self,
        )

    def _update_find_label(self, capped: bool = False, loose: bool = None):
        if not self._find_hits:
            return
        if loose is not None:
            self._find_loose = loose
        total = f"{len(self._find_hits)}{'+' if capped else ''}"
        # "≈" means the exact phrase was not in the text layer and the hits
        # come from the spaces-ignored fallback — the reader should know the
        # match is the renderer's best guess, not a literal one.
        mark = " ≈" if self._find_loose else ""
        self._find_label.setText(f"{self._find_at + 1} / {total}{mark}")

    def _find_step(self, delta: int):
        if not self._find_hits:
            return
        self._find_at = (self._find_at + delta) % len(self._find_hits)
        self._find_scroll_to(self._find_at)
        self._paint_matches()
        self._update_find_label()

    def _find_scroll_to(self, index: int):
        if not (0 <= index < len(self._find_hits)) or self._find_scroll is None:
            return
        hit = self._find_hits[index]
        page, rects = hit.get("page", 0), hit.get("rects") or []
        if not rects or not 0 <= page < len(self._pdf_labels):
            return
        # First rectangle: a match wrapped over a line break has one per
        # line, and the reader wants to land where it starts.
        x, y, w, h = rects[0]
        label = self._pdf_labels[page]
        # Map the match into the scrolled column's coordinates, then ask for
        # it with a generous margin so it lands mid-view rather than jammed
        # against the top edge.
        col = self._find_scroll.widget()
        top_left = label.mapTo(col, QPoint(int(x), int(y)))
        self._find_scroll.ensureVisible(
            top_left.x() + int(w) // 2, top_left.y() + int(h) // 2,
            80, self._find_scroll.viewport().height() // 2,
        )

    def _paint_matches(self):
        """Push the current hits onto each page's overlay.

        One hit can be several rectangles — a phrase that wraps over a line
        break — so the overlay is told the span belonging to the current
        match rather than a single index.
        """
        per_page = {}
        current = {}
        for i, hit in enumerate(self._find_hits):
            page = hit.get("page", 0)
            rects = [tuple(int(v) for v in r) for r in hit.get("rects") or []]
            if not rects:
                continue
            start = len(per_page.setdefault(page, []))
            per_page[page].extend(rects)
            if i == self._find_at:
                current = {page: range(start, start + len(rects))}
        for page, overlay in enumerate(self._pdf_overlays):
            if overlay is None:
                continue
            overlay.set_matches(per_page.get(page, []), current.get(page))

    def _pdf_fill_page(self, i: int, img: QImage):
        """Put a decoded page into its placeholder."""
        if not 0 <= i < len(self._pdf_labels):
            return
        label = self._pdf_labels[i]
        # Shown at logical size with all its pixels: the ratio is the one
        # the worker actually rendered at, read off the page itself.
        try:
            ratio = float(img.text("QuickView:Scale") or 1.0)
        except ValueError:
            ratio = 1.0
        img.setDevicePixelRatio(max(ratio, 1.0))
        size = img.deviceIndependentSize().toSize()
        if label.size() != size:  # an estimate that missed
            label.setFixedSize(size)
            overlay = self._pdf_overlays[i] if i < len(self._pdf_overlays) else None
            if overlay is not None:
                overlay.setGeometry(0, 0, size.width(), size.height())
        label.setPixmap(QPixmap.fromImage(img))
        label.setStyleSheet("")

    def _pdf_show_cached(
        self, path: str, page_key, page_w: int, total: int, img0: QImage,
        op: str = "pdf", extra: dict = None
    ):
        # Fill cached pages one per event-loop turn: page 1 paints
        # immediately and a 50-page reopen never freezes input.
        count = min(total, SETTINGS["pdf_max_pages"])
        # Sizes come from the cached PNGs' headers — 24 bytes each, no
        # decode — so the column is the right height before any page is
        # decoded. A page missing from the cache falls back to page 1's
        # size; the resumed render corrects it when it lands.
        fallback = (img0.width(), img0.height())
        sizes = [fallback]
        for i in range(1, count):
            head = cache_read_head(page_key(i))
            sizes.append((head and png_size(head)) or fallback)
        lay = self._pdf_begin_view(
            path, total, sizes, op=op, page_w=page_w
        )
        gen = object()
        self._pdf_gen = gen
        state = {"i": 0}

        def step():
            if self._pdf_gen is not gen:
                return  # the view was cleared under us
            i = state["i"]
            if i >= count:
                return
            img = (
                img0 if i == 0
                else QImage.fromData(cache_read(page_key(i)) or b"")
            )
            if img.isNull():
                # A page is missing (the pruner dropped it, or an earlier
                # render was cut short when the panel closed). Resume the
                # render at that page and keep appending to the view we
                # already built: restarting from page 0 would throw away
                # what is on screen and jump the reader back to the top.
                log.debug("pdf cache incomplete at page %d: %s", i, path)
                self._pdf_gen = None  # stop this stepper; the job takes over
                self._pdf_render(
                    path, page_key, page_w, start=i, lay=lay, op=op, extra=extra
                )
                return
            self._pdf_fill_page(i, img)
            state["i"] = i + 1
            QTimer.singleShot(0, step)

        step()

    def _pdf_render(self, path: str, page_key, page_w: int, start: int = 0,
                    lay=None, op: str = "pdf", extra: dict = None,
                    on_doc=None, toc_key: str = None):
        """Render pages start.. into the view, streaming from the jail.

        With lay given the pages append to an existing page column (a
        resumed partial cache); otherwise the column is created when the
        first page arrives.
        """
        self._cancel_render()
        if lay is None:
            self._clear_widgets()
            self.show_message("Loading preview…")
            self._pdf_labels = []
        # got: frames received, which is what fixes a page's number;
        # shown: pages actually on screen. They differ when a page fails to
        # decode, and the page number must not slide down to fill that gap —
        # caching the next page under the failed page's key would put every
        # later page one position too low, and a cache that wrong looks
        # complete on the next open.
        state = {"got": 0, "shown": 0, "lay": lay, "job": None}

        def on_frame(png: bytes):
            if not self._is_current(state["job"], path):
                return
            if on_doc is not None and state["job"].header.get("kind") == "doc":
                # Not page images: a thumbnail-and-text payload, which is
                # what a slide deck answers with.
                on_doc(png)
                state["shown"] += 1
                return
            page = start + state["got"]
            state["got"] += 1
            img = QImage.fromData(png)
            if img.isNull():
                # Left uncached, so the next open resumes the render here.
                log.warning("pdf page %d decode failed: %s", page, path)
                return
            if state["lay"] is None:
                try:
                    total = int(img.text("QuickView:PageCount"))
                except ValueError:
                    # No usable tEXt chunk — fall back to what the worker
                    # said it would stream.
                    total = state["job"].header.get("count", page + 1)
                # Page 1's size stands in for the rest until they arrive:
                # pages of one document almost always match, and any that
                # does not is corrected as it lands. What matters is that
                # the column is its full height before the reader scrolls.
                count = min(total, SETTINGS["pdf_max_pages"])
                log.debug("pdf first page: %s", path)
                # A book's chapters ride on the render's header: they come
                # out of the same layout pass that produced these pages, so
                # they are here before the view that shows them is built.
                header_toc = state["job"].header.get("toc")
                if header_toc is not None:
                    self._set_toc(path, header_toc, toc_key)
                state["lay"] = self._pdf_begin_view(
                    path, total, [(img.width(), img.height())] * count,
                    op=op, page_w=page_w,
                )
            cache_write(page_key(page), png)
            self._pdf_fill_page(page, img)
            state["shown"] += 1

        def on_done(ok: bool, error: str):
            if not self._is_current(state["job"], path):
                return
            self._render_job = None
            if state["shown"] == 0 and start == 0:
                log.warning("%s render failed: %s (%s)", op, path, error[:500])
                self._clear_widgets()
                self.show_fallback(
                    path, self.mime_db.mimeTypeForFile(path).name()
                )
            elif not ok:
                # Keep the pages that made it; just note the truncation.
                log.warning("pdf render truncated: %s (%s)", path, error[:500])

        job = {"op": op, "page_w": page_w, "max_pages": SETTINGS["pdf_max_pages"],
               "start": start, "scale": self._page_scale}
        if extra:
            job.update(extra)
        state["job"] = self._render_job = SandboxJob(
            self.pool, path, job, on_frame, on_done, self,
        )
