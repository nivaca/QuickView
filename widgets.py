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

"""Small widgets the panel is built from.
"""


# What the daemon asks the renderers: which engine the workers will use for
# office documents, for the cache key, and the bounds a workbook is held to.
# renderers imports nothing at module level, so this loads no parser here.

from PySide6.QtCore import (
    Qt, QRect,
)
from PySide6.QtGui import (
    QPainter, QColor,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel, QPushButton,
    QSlider, QStyle,
    QStyleOptionSlider, QWidget,
)


class SeekSlider(QSlider):
    """A slider that seeks to where you click, not one page nearer to it.

    A QSlider's groove is a page-step control by default: clicking it moves
    the handle a fixed amount towards the cursor, which on a seek bar means
    a click halfway through a film moves it a few seconds and the only way
    to get anywhere is to drag the handle. Every media player treats the
    whole timeline as the target, so this does too.

    The press is turned into a value and the handle moved there *before*
    the base class sees the event, so the handle is under the cursor by the
    time Qt starts its drag — one press then either seeks or begins a drag,
    with no special case for which the user meant.
    """

    def _value_at(self, x: int) -> int:
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        groove = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, opt,
            QStyle.SubControl.SC_SliderGroove, self,
        )
        handle = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, opt,
            QStyle.SubControl.SC_SliderHandle, self,
        )
        # The handle has width, so the travel is shorter than the groove and
        # the usable span starts half a handle in. Without both corrections
        # a click at either end lands short of the end of the file.
        span = groove.width() - handle.width()
        pos = x - groove.x() - handle.width() // 2
        return QStyle.sliderValueFromPosition(
            self.minimum(), self.maximum(), pos, max(span, 1)
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.maximum() > self.minimum():
            self.setSliderPosition(self._value_at(int(event.position().x())))
            self.sliderMoved.emit(self.value())
        super().mousePressEvent(event)


class MatchOverlay(QWidget):
    """Translucent highlight boxes drawn over one rendered PDF page.

    Parented to the page's QLabel and sized to it, so the rectangles the
    worker sends — already in page pixels — need no further transform. The
    widget is transparent to clicks so it never swallows a drag on the page
    underneath.
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._rects = []
        self._current = ()  # indices of the active match, empty on this page

    def set_matches(self, rects: list, current=None):
        """`current` is the range of indices belonging to the active match."""
        self._rects = rects
        self._current = current or ()
        self.update()

    def paintEvent(self, _event):
        if not self._rects:
            return
        painter = QPainter(self)
        for i, (x, y, w, h) in enumerate(self._rects):
            # The match the reader is standing on is opaque enough to find
            # at a glance; the rest are a soft wash so the page stays legible.
            painter.fillRect(
                QRect(x, y, w, h),
                QColor(255, 190, 40, 200) if i in self._current
                else QColor(255, 220, 90, 90),
            )
        painter.end()


class TitleBar(QWidget):
    """Quick Look style header: close button left, centered file name."""

    def __init__(self, window):
        super().__init__()
        self._window = window
        self._drag_from = None    # cursor position where a drag started
        self._drag_origin = None  # panel position at that moment
        self.setFixedHeight(40)

        self.close_btn = QPushButton("✕")
        self.close_btn.setObjectName("closeBtn")
        self.close_btn.setFixedSize(24, 24)
        self.close_btn.clicked.connect(window.close)

        self.title = QLabel("")
        self.title.setObjectName("titleLabel")
        self.title.setAlignment(Qt.AlignCenter)

        self.open_btn = QPushButton("Open")
        self.open_btn.setObjectName("openBtn")
        self.open_btn.clicked.connect(window.open_externally)

        # Documents with a table of contents: opens the chapter sidebar.
        # Top left, next to the close button, where every reader puts it.
        self.toc_btn = QPushButton("☰")
        self.toc_btn.setObjectName("tocBtn")
        self.toc_btn.setFixedSize(24, 24)
        self.toc_btn.setCheckable(True)
        self.toc_btn.setToolTip("Contents")
        self.toc_btn.clicked.connect(window.toggle_toc)
        self.toc_btn.hide()

        # HTML only: flips between rendered preview and source view.
        self.mode_btn = QPushButton("Code")
        self.mode_btn.setObjectName("openBtn")
        self.mode_btn.clicked.connect(window.toggle_mode)
        self.mode_btn.hide()

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        # Quick Look puts the close button top left, next to the traffic
        # lights it borrows its colour from; a Plasma window decoration puts
        # it on the right. This is the one part of the theme that is layout
        # rather than paint, which is why it lives here and not in the
        # stylesheet.
        if window.theme["close_side"] == "left":
            order = (self.close_btn, self.toc_btn, None,
                     self.mode_btn, self.open_btn)
        else:
            order = (self.toc_btn, None, self.mode_btn,
                     self.open_btn, self.close_btn)
        for widget in order:
            if widget is None:
                lay.addWidget(self.title, 1)   # the stretch, wherever it falls
            else:
                lay.addWidget(widget)

    # The window is a full-screen overlay, so there is nothing for the
    # compositor to move: dragging the titlebar slides the panel inside it.
    # startSystemMove() would be a no-op here (and is ignored outright on
    # Wayland, which is what kept the panel off centre in the first place).
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_from = event.globalPosition().toPoint()
            self._drag_origin = self._window.panel.pos()
            # Accepted, not propagated: the press has to land here for the
            # move events of the drag to follow it.
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_from is not None:
            delta = event.globalPosition().toPoint() - self._drag_from
            self._window.move_panel(self._drag_origin + delta)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_from = None
        super().mouseReleaseEvent(event)
