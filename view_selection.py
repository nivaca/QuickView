# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Nicolas Vaughan <nivaca@fastmail.com>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Selecting and copying the text of a page view with the mouse, as Quick
Look does: a PDF's, a book's or a rendered Markdown file's.

Drag over the pages to select, double-click a word, Ctrl+A for everything,
Ctrl+C to copy; a click without a drag clears the selection. The pages are
pictures, so their text is fetched from the jail (op "pdftext", or
"epubtext" / "mdtext", which lay the text out again as it was painted)
the first time it is needed — a press on a page asks for that page, Select All for
all of them in one job — and kept for as long as the document is open.
The selection logic itself is text_select; this wires it to the view.
"""

import json

from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtGui import QClipboard, QGuiApplication, QKeySequence
from PySide6.QtWidgets import QApplication, QLabel

import text_select
from common import (
    log,
    SETTINGS,
)
from sandbox import (
    SandboxJob,
)
from view_zoom import label_zoom
from widgets import (
    SelectionOverlay,
)


class TextSelectionMixin:
    """Mouse selection and copying over a page column.

    Mixed into QuickView, whose page labels (self._pdf_labels), scroll area
    and worker pool it uses; not usable on its own.
    """

    # --------------------------------------------------------------- state
    def _reset_text_selection(self):
        """Forget the document's text and selection; selection is off until
        enable_text_selection() turns it on for a new page column."""
        job = getattr(self, "_sel_job", None)
        if job is not None:
            job.cancel()
        timer = getattr(self, "_sel_scroll_timer", None)
        if timer is not None:
            timer.stop()
        self._sel_job = None
        self._sel_path = None        # None: no selectable text in this view
        self._sel_page_w = 0
        self._sel_op = "pdftext"     # the jail's op that places the words
        self._sel_extra = {}         # and what it lays the text out with
        self._sel_layers = {}        # page -> text_select.PageText
        self._sel_pending = set()    # pages to fetch
        self._sel_waiting = []       # callables run when text arrives
        self._sel = None             # text_select.Selection, or None
        self._sel_visible = False    # a bare click makes one but shows none
        self._sel_press = None       # global press position, button down
        self._sel_pointer = None     # latest global pointer position
        self._sel_anchor_at = None   # (page, x, y) of the press
        self._sel_keep = False       # a double-click's word outlives release
        self._sel_overlays = {}      # page -> SelectionOverlay

    def enable_text_selection(self, path: str, page_w: int,
                              op: str = "pdftext", extra: dict = None):
        """Make the page column selectable: called once its labels exist.
        op is the worker op that answers with the pages' words; extra, what
        a book or Markdown file was laid out with (theme, font), so the
        words are placed in that same layout."""
        self._sel_path = path
        self._sel_page_w = page_w
        self._sel_op = op
        self._sel_extra = dict(extra or {})
        for i, label in enumerate(self._pdf_labels):
            label.setProperty("qv_page", i)
            label.setCursor(Qt.IBeamCursor)
            label.installEventFilter(self)
        if getattr(self, "_sel_scroll_timer", None) is None:
            # Scrolls while a drag holds the pointer above or below the
            # pages, so a selection can run past what is on screen.
            self._sel_scroll_timer = QTimer(self)
            self._sel_scroll_timer.setInterval(30)
            self._sel_scroll_timer.timeout.connect(self._sel_autoscroll)

    # --------------------------------------------------------------- mouse
    def eventFilter(self, obj, event):
        if self._sel_path is None or not isinstance(obj, QLabel) \
                or obj.property("qv_page") is None:
            return super().eventFilter(obj, event)
        kind = event.type()
        if kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self._sel_on_press(event.globalPosition().toPoint())
            return True
        if kind == QEvent.MouseButtonDblClick and event.button() == Qt.LeftButton:
            self._sel_on_double(event.globalPosition().toPoint())
            return True
        if kind == QEvent.MouseMove and self._sel_press is not None:
            self._sel_on_move(event.globalPosition().toPoint())
            return True
        if (kind == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton
                and self._sel_press is not None):
            self._sel_on_release()
            return True
        return super().eventFilter(obj, event)

    def _page_at(self, gpos) -> tuple:
        """(page, x, y) for a global point: the page under it, or — in the
        gap between pages, or above or below them all — the nearest page,
        with the point moved onto it."""
        best = None
        for i, label in enumerate(self._pdf_labels):
            p = label.mapFromGlobal(gpos)
            h = label.height()
            dy = 0 if 0 <= p.y() < h else (-p.y() if p.y() < 0 else p.y() - h + 1)
            if best is None or dy < best[0]:
                best = (dy, i, p, label)
            if dy == 0:
                break
        _dy, page, p, label = best
        # In the page's own pixels, which the words are placed in; the
        # label may be zoomed.
        z = label_zoom(label)
        base = self.page_base(label)
        x = min(max(int(p.x() / z), 0), base.width() - 1)
        y = min(max(int(p.y() / z), 0), base.height() - 1)
        return page, x, y

    def _sel_on_press(self, gpos):
        self._sel_press = self._sel_pointer = gpos
        self._sel_keep = False
        self._sel_visible = False
        self._sel = None
        self._sel_anchor_at = self._page_at(gpos)
        self._sel_need([self._sel_anchor_at[0]], self._sel_follow)
        self._sel_paint()

    def _sel_on_move(self, gpos):
        self._sel_pointer = gpos
        if not self._sel_visible and \
                (gpos - self._sel_press).manhattanLength() >= QApplication.startDragDistance():
            self._sel_visible = True
        self._sel_follow()
        viewport = self._page_scroll.viewport() if self._page_scroll else None
        if viewport is not None:
            y = viewport.mapFromGlobal(gpos).y()
            outside = y < 0 or y >= viewport.height()
            if outside and not self._sel_scroll_timer.isActive():
                self._sel_scroll_timer.start()
            elif not outside:
                self._sel_scroll_timer.stop()

    def _sel_on_release(self):
        self._sel_scroll_timer.stop()
        self._sel_press = None
        if not (self._sel_visible or self._sel_keep):
            # A click, not a drag: clears the selection — and its anchor, so
            # a page's text arriving after the click cannot bring it back.
            self._sel = None
            self._sel_anchor_at = None
        self._sel_paint()
        self._sel_publish_primary()

    def _sel_on_double(self, gpos):
        """Select the word under the pointer, as a double-click does."""
        self._sel_press = self._sel_pointer = gpos
        self._sel_keep = True
        page, x, y = self._page_at(gpos)

        def select_word():
            layer = self._sel_layers.get(page)
            if layer is None:
                return False
            word = text_select.hit(layer, x, y)
            if word is not None:
                self._sel = text_select.Selection((page, word))
                self._sel_visible = True
                self._sel_paint()
                self._sel_publish_primary()
            return True

        self._sel_need([page], select_word)

    def _sel_follow(self):
        """Point the selection at the pointer: the anchor once the press's
        page has text, the head wherever the pointer is now."""
        if self._sel_anchor_at is None or self._sel_pointer is None:
            return True
        apage, ax, ay = self._sel_anchor_at
        alayer = self._sel_layers.get(apage)
        if alayer is None:
            return False  # the press's page is still being fetched
        if self._sel is None:
            word = text_select.hit(alayer, ax, ay)
            if word is None:
                return True  # a page with no text
            self._sel = text_select.Selection((apage, word))
        page, x, y = self._page_at(self._sel_pointer)
        layer = self._sel_layers.get(page)
        if layer is None:
            self._sel_need([page], self._sel_follow)
            return True
        word = text_select.hit(layer, x, y)
        if word is not None:
            self._sel.head = (page, word)
        elif page != apage:
            # A page with no text between: stop at the edge of the last one.
            self._sel.head = (page, 0)
        # Every page the drag spans is highlighted, so fetch them too.
        self._sel_need(list(self._sel.pages()), self._sel_paint_when_ready)
        self._sel_paint()
        return True

    def _sel_paint_when_ready(self):
        self._sel_paint()
        return True

    def _sel_autoscroll(self):
        if self._sel_press is None or self._page_scroll is None:
            self._sel_scroll_timer.stop()
            return
        viewport = self._page_scroll.viewport()
        y = viewport.mapFromGlobal(self._sel_pointer).y()
        over = y if y < 0 else y - viewport.height() + 1 if y >= viewport.height() else 0
        if over == 0:
            self._sel_scroll_timer.stop()
            return
        bar = self._page_scroll.verticalScrollBar()
        step = max(4, min(abs(over) // 2, 60))
        bar.setValue(bar.value() + (step if over > 0 else -step))
        self._sel_follow()

    # ---------------------------------------------------------------- keys
    def keyPressEvent(self, event):
        # Reached only by keys no child took: the code view's own Ctrl+C
        # and Ctrl+A stay its own.
        if self._sel_path is not None:
            if event.matches(QKeySequence.StandardKey.Copy):
                self.copy_selection()
                event.accept()
                return
            if event.matches(QKeySequence.StandardKey.SelectAll):
                self.select_all_text()
                event.accept()
                return
        super().keyPressEvent(event)

    def copy_selection(self):
        """Put the selected text on the clipboard, once every page in the
        selection has its text."""
        if self._sel is None or not self._sel_visible:
            return
        selection = self._sel

        def copy():
            if any(p not in self._sel_layers for p in selection.pages()):
                return False
            text = selection.text(self._sel_layers)
            if text:
                QGuiApplication.clipboard().setText(text)
            return True

        self._sel_need(list(selection.pages()), copy)

    def select_all_text(self):
        """Select the whole document's text — one job for all its pages."""
        pages = list(range(len(self._pdf_labels)))

        def select_all():
            if any(p not in self._sel_layers for p in pages):
                return False
            with_text = [p for p in pages if self._sel_layers[p].words]
            if with_text:
                first, last = with_text[0], with_text[-1]
                self._sel = text_select.Selection(
                    (first, 0), (last, len(self._sel_layers[last].words) - 1))
                self._sel_visible = self._sel_keep = True
                self._sel_paint()
                self._sel_publish_primary()
            return True

        self._sel_need(pages, select_all)

    def _sel_publish_primary(self):
        """The selection also goes to X11/Wayland's primary selection, so a
        middle click elsewhere pastes it, as everywhere on Linux."""
        if self._sel is None or not self._sel_visible:
            return
        if any(p not in self._sel_layers for p in self._sel.pages()):
            return
        clipboard = QGuiApplication.clipboard()
        if clipboard.supportsSelection():
            text = self._sel.text(self._sel_layers)
            if text:
                clipboard.setText(text, QClipboard.Mode.Selection)

    # --------------------------------------------------------------- paint
    def _sel_paint(self):
        ranges = (self._sel.ranges(self._sel_layers)
                  if self._sel is not None and self._sel_visible else {})
        for page, overlay in self._sel_overlays.items():
            if page not in ranges:
                overlay.set_rects([])
        for page, (a, b) in ranges.items():
            overlay = self._sel_overlays.get(page)
            if overlay is None:
                label = self._pdf_labels[page]
                overlay = SelectionOverlay(label, self.theme["accent"])
                overlay.setGeometry(label.rect())
                overlay.show()
                overlay.raise_()
                self._sel_overlays[page] = overlay
            overlay.set_rects(text_select.rects(self._sel_layers[page], a, b))

    # --------------------------------------------------------- the jail's text
    def _sel_need(self, pages: list, then=None):
        """Make sure these pages' text is known, then run `then`: at once if
        it all is, otherwise each time new text arrives, until it returns
        True. Never run while its own pages are missing — an action that
        asks for a page and waits on itself would otherwise call itself
        for ever."""
        absent = [p for p in pages if p not in self._sel_layers]
        missing = [p for p in absent if p not in self._sel_pending]
        if then is not None and (absent or not then()):
            if then not in self._sel_waiting:
                self._sel_waiting.append(then)
        if missing:
            self._sel_pending.update(missing)
            self._sel_fetch_next()

    def _sel_fetch_next(self):
        if self._sel_job is not None or not self._sel_pending or self._sel_path is None:
            return
        pages = sorted(self._sel_pending)
        state = {"blob": None, "job": None}

        def on_frame(data: bytes):
            state["blob"] = data

        def on_done(ok: bool, error: str):
            if state["job"] is not self._sel_job:
                return  # the document changed; this text is not its
            self._sel_job = None
            try:
                payload = json.loads(state["blob"]) if ok and state["blob"] else {}
            except (ValueError, TypeError):
                payload = {}
            if not ok:
                log.warning("page text failed: %s (%s)", self._sel_path, error[:200])
            sizes = [(self.page_base(label).width(), self.page_base(label).height())
                     for label in self._pdf_labels]
            got = text_select.parse(payload, sizes)
            for page in pages:
                # A page the worker could not read counts as one with no
                # text, rather than being asked for again on every move.
                self._sel_layers[page] = got.get(page) or text_select.PageText(page, "", [])
            self._sel_pending.difference_update(pages)
            # Run what was waiting; each may ask for more, which lands in the
            # fresh list, so keep both the new requests and the still-unmet.
            waiting, self._sel_waiting = self._sel_waiting, []
            for then in waiting:
                if not then() and then not in self._sel_waiting:
                    self._sel_waiting.append(then)
            self._sel_fetch_next()

        state["job"] = self._sel_job = SandboxJob(
            self.pool, self._sel_path,
            {**self._sel_extra, "op": self._sel_op, "pages": pages,
             "page_w": self._sel_page_w,
             "max_pages": SETTINGS["pdf_max_pages"]},
            on_frame, on_done, self,
        )
