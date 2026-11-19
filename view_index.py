# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Nicolas Vaughan <nicolasvaughan@proton.me>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""The index sheet: every file of a multi-file selection as a thumbnail,
as Quick Look shows them.

The grid button in the title bar, or Ctrl+Enter, shows it whenever more
than one file was selected; the arrows move through the grid, and Enter
or a click opens that file in the preview (Ctrl+Enter or the button go
back to the file that was showing).

A thumbnail comes from the freedesktop thumbnail cache when there is one
(~/.cache/thumbnails), which Dolphin has usually filled already for the
files it shows: a PNG named after the file's URI, kept only while its
Thumb::MTime matches the file. Otherwise an image is decoded in the jail,
like every preview, one file at a time; anything else shows its type's
icon.
"""

import hashlib
import os
from string import Template

from PySide6.QtCore import QMimeDatabase, QSize, Qt, QUrl
from PySide6.QtGui import QIcon, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import QListView, QListWidget, QListWidgetItem

from common import image_from_raw, log
from sandbox import SandboxJob

THUMB_PX = 160            # a tile's picture, in logical pixels
THUMB_DIRS = ("x-large", "large", "xx-large", "normal")
THUMB_MAX_BYTES = 4 * 1024 * 1024
TILE = (THUMB_PX + 40, THUMB_PX + 52)   # a tile: the picture and two lines
# The keys the grid takes for itself while it shows: the arrows move
# through it, and Enter opens the file under the cursor.
GRID_KEYS = (Qt.Key_Left, Qt.Key_Right, Qt.Key_Return, Qt.Key_Enter)


def thumbnail_dir() -> str:
    cache = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(cache, "thumbnails")


def cached_thumbnail(path: str) -> QImage:
    """The freedesktop cache's thumbnail of a file, or a null QImage when
    there is none, or it was made of an older version of the file."""
    try:
        mtime = int(os.stat(path).st_mtime)
    except OSError:
        return QImage()
    uri = QUrl.fromLocalFile(path).toString(QUrl.ComponentFormattingOption.FullyEncoded)
    name = hashlib.md5(uri.encode("utf-8", "surrogateescape")).hexdigest() + ".png"
    for size in THUMB_DIRS:
        thumb = os.path.join(thumbnail_dir(), size, name)
        try:
            if os.path.getsize(thumb) > THUMB_MAX_BYTES:
                continue
        except OSError:
            continue
        img = QImage()
        # PNG named, never sniffed: whatever is in the file, only the PNG
        # decoder sees it.
        if not img.load(thumb, "PNG"):
            continue
        stamp = img.text("Thumb::MTime")
        if stamp and stamp != str(mtime):
            continue  # made before the file last changed
        return img
    return QImage()


class IndexSheetMixin:
    """Mixed into QuickView: uses its selection, title bar, content stack,
    worker pool and navigation shortcuts."""

    INDEX_STYLE = Template("""
        QListWidget {
            background-color: $bg; color: $text_dim; border: none;
            font-size: $ui; outline: none; padding: 10px;
        }
        QListWidget::item { border-radius: 6px; padding: 6px; }
        QListWidget::item:hover { background-color: $tree_hover; }
        QListWidget::item:selected {
            background-color: $sel_tree; color: $accent_text;
        }
        QScrollBar:vertical { background: $bg; border: none; width: 10px; }
        QScrollBar::handle:vertical {
            background: $scroll_handle; border-radius: 5px; min-height: 30px;
        }
        QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
        QScrollBar::add-page, QScrollBar::sub-page { background: none; }
    """)

    def _init_index(self):
        self._index_view = None
        self._index_jobs = []        # images waiting for the jail, in order
        self._index_job = None       # the one running
        QShortcut(QKeySequence(Qt.CTRL | Qt.Key_Return), self,
                  activated=self.toggle_index_sheet)
        QShortcut(QKeySequence(Qt.CTRL | Qt.Key_Enter), self,
                  activated=self.toggle_index_sheet)

    def _grid_keys(self, on: bool):
        """The arrows and Enter: the window's (step, open) or the grid's."""
        for shortcut in self._nav_shortcuts:
            if shortcut.key()[0].key() in GRID_KEYS:
                shortcut.setEnabled(on)

    def _forget_index(self):
        """Called as the content is torn down: the grid goes with it."""
        if self._index_view is None:
            return
        self._index_view = None
        self._index_jobs = []
        if self._index_job is not None:
            self._index_job.cancel()
            self._index_job = None
        self._grid_keys(True)
        self.titlebar.index_btn.setChecked(False)

    def toggle_index_sheet(self):
        if len(self.selection) < 2:
            return
        if self._index_view is not None:
            self.show_file(self.selection[self.sel_index])
        else:
            self.show_index_sheet()

    def show_index_sheet(self):
        self.disarm_idle_exit()
        self.clear_content()
        grid = QListWidget()
        grid.setObjectName("indexSheet")
        grid.setViewMode(QListView.ViewMode.IconMode)
        grid.setMovement(QListView.Movement.Static)
        grid.setResizeMode(QListView.ResizeMode.Adjust)
        grid.setIconSize(QSize(THUMB_PX, THUMB_PX))
        grid.setGridSize(QSize(*TILE))
        grid.setSpacing(4)
        grid.setStyleSheet(self.INDEX_STYLE.substitute(self.theme))
        grid.setWordWrap(True)
        grid.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        mimes = QMimeDatabase()
        for path in self.selection:
            item = QListWidgetItem(os.path.basename(path) or path)
            item.setToolTip(path)
            # Sized now: the pictures arrive later, and a tile measured
            # before them would keep room for its name alone.
            item.setSizeHint(QSize(TILE[0] - 4, TILE[1] - 4))
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            mime = mimes.mimeTypeForFile(path)
            item.setIcon(QIcon.fromTheme(mime.iconName(),
                                         QIcon.fromTheme(mime.genericIconName())))
            grid.addItem(item)
        grid.setCurrentRow(self.sel_index)
        grid.itemActivated.connect(lambda item: self._index_open(grid.row(item)))
        self._index_view = grid
        self.content.addWidget(grid)
        self._grid_keys(False)
        self.titlebar.index_btn.setChecked(True)
        self.titlebar.title.setText(f"{len(self.selection)} items")
        avail = self.screen_avail()
        self.set_panel_size(int(avail.width() * 0.6), int(avail.height() * 0.7))
        self.fit_overlay()
        self.show()
        self.raise_()
        self.activateWindow()
        grid.setFocus()
        self._index_thumbnails(grid)

    def _index_open(self, row: int):
        if 0 <= row < len(self.selection):
            self.sel_index = row
            self.show_file(self.selection[row])

    # -------------------------------------------------------- thumbnails
    def _index_thumbnails(self, grid):
        for row, path in enumerate(self.selection):
            img = cached_thumbnail(path)
            if not img.isNull():
                self._index_set(grid, row, img)
            elif os.path.isfile(path) and self.route(path)[0] == "image":
                self._index_jobs.append((row, path))
        self._index_next(grid)

    def _index_set(self, grid, row: int, img: QImage):
        if self._index_view is not grid or not 0 <= row < grid.count():
            return
        side = int(THUMB_PX * self.devicePixelRatioF())
        if img.width() > side or img.height() > side:
            img = img.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        pix = QPixmap.fromImage(img)
        pix.setDevicePixelRatio(self.devicePixelRatioF())
        grid.item(row).setIcon(QIcon(pix))

    def _index_next(self, grid):
        if self._index_view is not grid or self._index_job is not None \
                or not self._index_jobs:
            return
        row, path = self._index_jobs.pop(0)
        side = int(THUMB_PX * self.devicePixelRatioF())
        got = {"job": None, "shown": False}

        def on_frame(data: bytes):
            if got["shown"] or got["job"] is not self._index_job:
                return
            img = image_from_raw(data, got["job"].header)
            if not img.isNull():
                got["shown"] = True
                self._index_set(grid, row, img)

        def on_done(ok: bool, error: str):
            if got["job"] is not self._index_job:
                return
            self._index_job = None
            if not ok:
                log.debug("index thumbnail failed: %s (%s)", path, error[:200])
            self._index_next(grid)

        got["job"] = self._index_job = SandboxJob(
            self.pool, path, {"op": "image", "max_w": side, "max_h": side},
            on_frame, on_done, self)
