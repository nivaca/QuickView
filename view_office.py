#!/usr/bin/env python3
# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Mustapha Alioglou
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Office documents, slide decks and spreadsheets.
"""

import base64
import json
import os
from string import Template

# What the daemon asks the renderers: which engine the workers will use for
# office documents, for the cache key, and the bounds a workbook is held to.
# renderers imports nothing at module level, so this loads no parser here.
from renderers import (
    SHEET_MAX_CELL_CHARS, SHEET_MAX_COLS, SHEET_MAX_ROWS, SHEET_MAX_SHEETS,
    office_suite,
)

from PySide6.QtCore import (
    Qt,
)
from PySide6.QtGui import (
    QFont, QImage, QPixmap, QColor,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHeaderView, QLabel, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)

from common import (
    cache_key,
    cache_read,
    cache_remove,
    cache_write,
    LEGACY_SPREADSHEET_MIMES,
    log,
    OFFICE_ENGINE,
    OFFICE_MIMES,
    SUITE_ONLY_MIMES,
    TEXT_PREVIEW_LIMIT,
)
from sandbox import (
    SandboxJob,
)


class OfficeViewMixin:
    """Office documents, slide decks and spreadsheets.

    Mixed into QuickView, whose state (self.content, the render job,
    the current path…) these methods use; not usable on its own.
    """

    # -------------------------------------------------------------- office
    # OOXML and ODF are zip containers full of XML, so no office suite is
    # needed. When the system has LibreOffice anyway, the worker uses it for
    # documents and slide decks — inside the jail, like every other parser —
    # because only a real layout engine gets them to look like themselves
    # (see renderers.office_pages); the legacy binary formats and RTF come
    # here only then. Without one, the worker lays documents out itself,
    # and for a deck it prefers the thumbnail the authoring application
    # embedded and extracts text when there is none.

    @staticmethod
    def office_suite_in_use() -> bool:
        """Whether office documents go to LibreOffice: installed, not refused."""
        return OFFICE_ENGINE != "builtin" and bool(office_suite())

    def show_office(self, path: str, mime: str):
        # Laid out as pages, cached page by page, and shown by the same code
        # that shows a PDF — a document with pages gets the page view. A
        # slide deck with no LibreOffice to lay it out gets the thumbnail it
        # embeds plus its text instead.
        if self._office_text and self._office_doc and self._office_doc[0] == path:
            self._render_office(path, self._office_doc[1])
            return
        avail = self.screen_avail()
        page_w = max(int(avail.width() * 0.55) - 44, 400)
        self._page_scale = scale = self.page_scale()
        try:
            st = os.stat(path)
        except OSError as exc:
            self.show_message(str(exc))
            return

        # The engine is part of the key: pages laid out by the built-in
        # converter must not outlive a LibreOffice install, or a change of
        # office_engine, or vice versa.
        engine = "lo" if self.office_suite_in_use() else "qt2"

        def page_key(i: int) -> str:
            return cache_key(path, st, page_w, 0, f"off{engine}{i}@{scale:g}")

        def on_doc(payload: bytes):
            try:
                doc = json.loads(payload)
            except ValueError:
                log.warning("office worker sent a malformed payload: %s", path)
                return
            self._office_doc = (path, doc)
            self._render_office(path, doc)

        png0 = cache_read(page_key(0))
        img0 = QImage.fromData(png0) if png0 is not None else QImage()
        total = 0
        if not img0.isNull():
            try:
                total = int(img0.text("QuickView:PageCount"))
            except ValueError:
                pass
        extra = {"name": os.path.basename(path), "limit": TEXT_PREVIEW_LIMIT,
                 "engine": OFFICE_ENGINE}
        if total > 0:
            log.debug("disk cache hit (office): %s", path)
            self._pdf_show_cached(
                path, page_key, page_w, total, img0, op="office", extra=extra
            )
            return
        if png0 is not None:
            cache_remove(page_key(0))
        self._pdf_render(
            path, page_key, page_w, op="office", extra=extra, on_doc=on_doc
        )

    def _render_office(self, path: str, doc: dict):
        """Show the cached payload in whichever mode is selected."""
        image = doc.get("image_b64")
        text = doc.get("text") or ""
        btn = self.titlebar.mode_btn
        # The button only appears when there is something to switch to.
        btn.setVisible(bool(image) and bool(text))
        if image and not self._office_text:
            btn.setText("Text")
            img = QImage.fromData(base64.b64decode(image))
            if not img.isNull():
                max_w, max_h = self.image_fit_box()
                # Embedded thumbnails are small — 256x144 for a PowerPoint
                # deck — and a slide shown at that size reads as a mistake.
                # Enlarge to fill the panel, but never past 3x, beyond which
                # it stops looking like a slide and starts looking like mush.
                scale = min(
                    max_w / img.width(), max_h / img.height(), 3.0
                )
                if scale > 1.0 or img.width() > max_w or img.height() > max_h:
                    img = img.scaled(
                        int(img.width() * min(scale, 3.0)),
                        int(img.height() * min(scale, 3.0)),
                        Qt.KeepAspectRatio, Qt.SmoothTransformation,
                    )
                self._display_image(
                    path, QPixmap.fromImage(img), f"{img.width()}×{img.height()}"
                )
                btn.setVisible(bool(text))
                return
            log.warning("office thumbnail did not decode: %s", path)
        btn.setText("Preview")
        if doc.get("truncated"):
            text += "\n\n[... truncated ...]"
        self._clear_widgets()
        self._show_text_widget(text)
        self.set_title(os.path.basename(path))

    # -------------------------------------------------------- spreadsheets
    # A workbook shown as what it is: a grid per sheet, with the sheet tabs
    # along the bottom the way the authoring application draws them. The
    # cells are parsed in the jail and arrive as text, so nothing here
    # evaluates a formula or touches the file.

    SHEET_CELL_MAX_W = 300
    SHEET_STYLE = Template("""
        QTableWidget {
            background-color: $bg; alternate-background-color: $bg_alt;
            color: $text_dim; gridline-color: $line; border: none;
            font-size: 12px;
        }
        QTableWidget::item { padding: 2px 6px; }
        QTableWidget::item:selected {
            background-color: $sel_table; color: $accent_text;
        }
        QHeaderView { background-color: $surface; }
        QHeaderView::section {
            background-color: $surface; color: $text_faint; border: none;
            border-right: 1px solid $line;
            border-bottom: 1px solid $line;
            padding: 3px 6px; font-size: 11px;
        }
        QTableCornerButton::section {
            background-color: $surface; border: none;
            border-right: 1px solid $line;
            border-bottom: 1px solid $line;
        }
        QTabWidget::pane { border: none; }
        QTabBar { qproperty-drawBase: 0; }
        QTabBar::tab {
            background-color: $surface; color: $tab_text;
            border: 1px solid $line; border-top: none;
            border-bottom-left-radius: $radius_btn;
            border-bottom-right-radius: $radius_btn;
            padding: 4px 14px; margin-right: 3px; font-size: 12px;
        }
        QTabBar::tab:selected {
            background-color: $tab_sel; color: $tab_sel_text;
        }
        QTabBar::tab:hover:!selected { background-color: $line; }
        QScrollBar:vertical, QScrollBar:horizontal {
            background: $bg; border: none;
        }
        QScrollBar:vertical { width: 10px; }
        QScrollBar:horizontal { height: 10px; }
        QScrollBar::handle {
            background: $scroll_handle; border-radius: 5px; min-height: 30px;
            min-width: 30px;
        }
        QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
        QScrollBar::add-page, QScrollBar::sub-page { background: none; }
    """)

    def show_sheets(self, path: str, mime: str):
        # A legacy workbook costs a LibreOffice conversion, ~0.6 s, so its
        # grid is kept on disk like a rendered page; a current one parses
        # in milliseconds and is not worth the space.
        key = None
        if mime in LEGACY_SPREADSHEET_MIMES:
            try:
                key = cache_key(path, os.stat(path), 0, 0, "sheets-lo")
            except OSError:
                pass
        cached = cache_read(key) if key else None
        if cached is not None:
            if self._show_workbook(path, cached):
                log.debug("disk cache hit (sheets): %s", path)
                return
            cache_remove(key)

        self.show_message("Loading preview…")
        state = {"job": None, "shown": False}

        def on_frame(payload: bytes):
            if self._render_job is not state["job"] or path != self.current_path:
                return
            if self._show_workbook(path, payload):
                state["shown"] = True
                if key:
                    cache_write(key, payload)

        def on_done(ok: bool, error: str):
            if self._render_job is not state["job"] or path != self.current_path:
                return
            self._render_job = None
            if not state["shown"]:
                # Encrypted, corrupt, or a shape this parser does not know.
                # The office path can still lay it out, or show its thumbnail.
                log.debug("no grid for %s (%s)", path, error[:200])
                self._clear_widgets()
                if mime in OFFICE_MIMES or (
                    mime in SUITE_ONLY_MIMES and self.office_suite_in_use()
                ):
                    self.show_office(path, mime)
                else:
                    self.show_fallback(path, mime)

        state["job"] = self._render_job = SandboxJob(
            self.pool, path,
            {"op": "sheets", "name": os.path.basename(path),
             "engine": OFFICE_ENGINE},
            on_frame, on_done, self,
        )

    def _show_workbook(self, path: str, payload: bytes) -> bool:
        """Show a workbook payload as tabs; False when it is not one.

        The payload is either a worker's answer or a disk cache entry, and
        the cache directory is writable by anything running as this user,
        so both are checked for shape before a widget is built from them.
        """
        try:
            book = json.loads(payload)
        except ValueError:
            book = None
        if not valid_workbook(book):
            log.warning("malformed workbook for %s", path)
            return False
        sheets = [s for s in book["sheets"] if s["rows"]]
        if not sheets:
            return False  # on_done falls back to the page view
        self._clear_widgets()
        self._show_sheets_widget(sheets, book.get("clipped", False))
        return True

    def _show_sheets_widget(self, sheets: list, clipped: bool):
        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        wrap.setStyleSheet(self.SHEET_STYLE.substitute(self.theme))

        status = QLabel()
        status.setStyleSheet(
            "color:{text_status}; font-size:11px; padding:5px 12px;"
            "background-color:{bg};".format(**self.theme)
        )

        widths = []
        if len(sheets) == 1:
            table, width = self._sheet_table(sheets[0])
            widths.append(width)
            lay.addWidget(table, 1)
        else:
            tabs = QTabWidget()
            # Tabs at the bottom, as a spreadsheet draws them.
            tabs.setTabPosition(QTabWidget.South)
            tabs.setDocumentMode(True)
            for sheet in sheets:
                table, width = self._sheet_table(sheet)
                widths.append(width)
                tabs.addTab(table, sheet.get("name") or "Sheet")
            # The line under the tabs describes the sheet being looked at,
            # not the first one in the book.
            tabs.currentChanged.connect(
                lambda index: status.setText(
                    self._sheet_summary(sheets, clipped, index)
                )
            )
            lay.addWidget(tabs, 1)

        status.setText(self._sheet_summary(sheets, clipped, 0))
        lay.addWidget(status)

        self.content.addWidget(wrap)
        rows = max(len(sheet["rows"]) for sheet in sheets)
        self.set_panel_size(
            min(max(widths) + 24, 1400),
            min(rows * 24 + 96, 900),
        )

    @staticmethod
    def _sheet_summary(sheets: list, clipped: bool, index: int = 0) -> str:
        sheet = sheets[index] if 0 <= index < len(sheets) else sheets[0]
        parts = []
        if len(sheets) > 1:
            parts.append(f"{len(sheets)} sheets")
        parts.append(
            "%d rows × %d columns" % (len(sheet["rows"]), sheet.get("cols", 0))
        )
        if clipped or sheet.get("clipped"):
            parts.append("preview truncated")
        return "  ·  ".join(parts)

    def _sheet_table(self, sheet: dict):
        """One sheet as a table, plus the width it would like to be.

        Columns keep their spreadsheet letters and rows their real numbers,
        so a cell in the preview is the same cell the user would find in
        Excel — the trimmed-away empty margin included.
        """
        rows = sheet["rows"]
        cols = sheet.get("cols") or (len(rows[0]) if rows else 0)
        align = sheet.get("align") or []
        first_col = int(sheet.get("first_col", 0))
        first_row = int(sheet.get("first_row", 1))

        table = QTableWidget(len(rows), cols)
        table.setHorizontalHeaderLabels(
            [self._column_letters(first_col + c) for c in range(cols)]
        )
        table.setVerticalHeaderLabels(
            [str(first_row + r) for r in range(len(rows))]
        )
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setAlternatingRowColors(True)
        table.setShowGrid(True)
        table.setWordWrap(False)
        table.setFrameShape(QFrame.NoFrame)
        table.verticalHeader().setDefaultSectionSize(24)

        header_row = self._looks_like_header(rows)
        bold = QFont()
        bold.setBold(True)
        for r, row in enumerate(rows):
            for c in range(cols):
                text = row[c] if c < len(row) else ""
                item = QTableWidgetItem(text)
                if r == 0 and header_row:
                    item.setFont(bold)
                    item.setForeground(QColor(self.theme["text_bright"]))
                    item.setBackground(QColor(self.theme["surface_head"]))
                    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                elif (align[c] if c < len(align) else "l") == "r":
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                else:
                    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                table.setItem(r, c, item)

        table.resizeColumnsToContents()
        width = table.verticalHeader().width() + 2
        for c in range(cols):
            # Wide enough to read, never so wide that one paragraph-sized
            # cell pushes every other column off the panel.
            size = min(max(table.columnWidth(c) + 12, 64), self.SHEET_CELL_MAX_W)
            table.setColumnWidth(c, size)
            width += size
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        return table, width

    @staticmethod
    def _looks_like_header(rows: list) -> bool:
        """Row one is a header when it is full of text and there is data
        under it — the shape almost every real workbook has."""
        if len(rows) < 2:
            return False
        first = [cell for cell in rows[0] if cell]
        if len(first) < max(1, len(rows[0]) // 2):
            return False
        return not any(
            cell.replace(".", "", 1).replace("-", "", 1).isdigit()
            for cell in first
        )

    @staticmethod
    def _column_letters(index: int) -> str:
        """0 -> "A", 26 -> "AA"."""
        letters = ""
        index += 1
        while index > 0:
            index, rest = divmod(index - 1, 26)
            letters = chr(65 + rest) + letters
        return letters


def valid_workbook(book) -> bool:
    """Is this the shape renderers.read_workbook returns, within its bounds?

    The table is sized from these numbers, so a payload claiming a billion
    columns must be refused here rather than handed to QTableWidget.
    """
    def count(value, low, high):
        return isinstance(value, int) and not isinstance(value, bool) and (
            low <= value <= high)

    if not isinstance(book, dict) or not isinstance(book.get("sheets"), list):
        return False
    if len(book["sheets"]) > SHEET_MAX_SHEETS:
        return False
    for sheet in book["sheets"]:
        if not isinstance(sheet, dict):
            return False
        rows = sheet.get("rows")
        if not isinstance(rows, list) or len(rows) > SHEET_MAX_ROWS:
            return False
        for row in rows:
            if not isinstance(row, list) or len(row) > SHEET_MAX_COLS:
                return False
            if not all(isinstance(cell, str) and len(cell) <= SHEET_MAX_CELL_CHARS
                       for cell in row):
                return False
        align = sheet.get("align", [])
        if not isinstance(align, list) or not all(isinstance(a, str) for a in align):
            return False
        if not (count(sheet.get("cols", 0), 0, SHEET_MAX_COLS)
                and count(sheet.get("first_col", 0), 0, 16383)
                and count(sheet.get("first_row", 1), 0, 1048576)
                and isinstance(sheet.get("name", ""), str)):
            return False
    return True
