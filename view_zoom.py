# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Nicolas Vaughan <nivaca@fastmail.com>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Zooming the preview: Ctrl++ / Ctrl+= / Ctrl+-, Ctrl+0, Ctrl+wheel.

What zooming means depends on what is showing:

- an image grows inside a scrolling area, and once it is shown larger
  than it was decoded, the jail decodes it again at the size it now has;
- a page view (PDF, office document, book, Markdown) scales its pages,
  and the pages on screen are rendered again at the new resolution, so
  zoomed text stays sharp. Find highlights and the text selection scale
  with the pages: they stay in page pixels, and the overlays and the
  mouse mapping multiply or divide by the zoom;
- text, code, folder and archive listings and spreadsheets change their
  font size; an HTML page uses the browser's own zoom.

The level belongs to the file: a new file starts at 100%, while a view
rebuilt for the same file (an office document's exact layout replacing
its quick one, Markdown's rendered/source switch) keeps it. Everything
else — a message, audio, video — does not zoom.
"""

import os

from PySide6.QtCore import QEvent, QObject, QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QFontInfo, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication, QFrame, QLabel, QPlainTextEdit, QScrollArea, QTableWidget, QWidget,
)

from common import cache_key, cache_read, cache_write, image_from_raw, is_cache_blob, log
from sandbox import SandboxJob

ZOOM_STEPS = (0.25, 0.33, 0.5, 0.67, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75,
              2.0, 2.5, 3.0, 4.0)
# The jail renders pages at most at this device pixel ratio: a page is
# about 1000 px wide, so 4x is 4000 px — about 60 MB of pixels a page.
HIRES_MAX_SCALE = 4.0
# How long the zoom (or the scrolling) must rest before the pages on
# screen are rendered again; renders that would be thrown away a moment
# later are not started.
HIRES_DELAY_MS = 250
# Pages kept at a zoomed-in resolution: the ones on screen. Scrolled-away
# pages go back to their normal pixels, so a long read at 400% does not
# accumulate a gigabyte of page images.
HIRES_MAX_PAGES = 4
IMAGE_MAX_SIDE = 8192
TOAST_MS = 900


def next_zoom(zoom: float, direction: int) -> float:
    """The next step up (direction > 0) or down from zoom."""
    if direction > 0:
        return next((s for s in ZOOM_STEPS if s > zoom + 1e-6), ZOOM_STEPS[-1])
    return next((s for s in reversed(ZOOM_STEPS) if s < zoom - 1e-6), ZOOM_STEPS[0])


def scaled(size: QSize, zoom: float) -> QSize:
    return QSize(max(1, round(size.width() * zoom)), max(1, round(size.height() * zoom)))


def label_zoom(widget) -> float:
    """The zoom a page label is shown at; overlays paint through it."""
    value = widget.property("qv_zoom") if widget is not None else None
    return float(value) if value else 1.0


def fit_label(label: QLabel):
    """Scale the pixmap only when it is not already the label's size: a
    scaled QLabel keeps a second, scaled copy of its pixmap."""
    pix = label.pixmap()
    label.setScaledContents(
        not pix.isNull() and pix.deviceIndependentSize().toSize() != label.size())


class _CtrlWheel(QObject):
    """Ctrl+wheel anywhere in the window, before the widget under the
    pointer sees it: a text box would zoom its own font, a web page its
    own zoom, and the window would lose track of the level."""

    def __init__(self, view):
        super().__init__(view)
        self.view = view
        self.rest = 0  # a touchpad scrolls in fractions of a notch

    def eventFilter(self, obj, event):
        if (event.type() == QEvent.Type.Wheel
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier
                and isinstance(obj, QWidget) and obj.window() is self.view):
            self.rest += event.angleDelta().y()
            notches = int(self.rest / 120)
            if notches:
                self.rest -= notches * 120
                self.view.zoom_step(notches, event.globalPosition().toPoint())
            return True
        return False


class ZoomMixin:
    """Mixed into QuickView; see the module docstring."""

    def _init_zoom(self, app):
        self._zoom = 1.0
        self._zoom_target = None   # fn(zoom, old, anchor) for the current view
        self._hires_job = None
        self._hires_timer = QTimer(self)
        self._hires_timer.setSingleShot(True)
        self._hires_timer.timeout.connect(self._hires_now)
        self._page_base_pix = {}   # page -> its normal-resolution pixmap
        self._page_job = None      # how the page view was rendered
        self._image_zoom = None    # the zoomable image, while one shows
        self._zoom_toast = None
        keys = (("Ctrl++", 1), ("Ctrl+=", 1), ("Ctrl+-", -1), ("Ctrl+0", 0))
        for text, step in keys:
            fn = self.zoom_reset if step == 0 else (lambda s=step: self.zoom_step(s))
            QShortcut(QKeySequence(text), self, activated=fn)
        # The keypad's + - 0 arrive with KeypadModifier, which no sequence
        # above matches.
        for key, step in ((Qt.Key.Key_Plus, 1), (Qt.Key.Key_Minus, -1), (Qt.Key.Key_0, 0)):
            fn = self.zoom_reset if step == 0 else (lambda s=step: self.zoom_step(s))
            QShortcut(QKeySequence(Qt.KeyboardModifier.ControlModifier
                                   | Qt.KeyboardModifier.KeypadModifier | key),
                      self, activated=fn)
        self._ctrl_wheel = _CtrlWheel(self)
        app.installEventFilter(self._ctrl_wheel)

    def _forget_zoom_view(self):
        """The view is being torn down; the level itself stays (see the
        module docstring) until a new file resets it."""
        self._zoom_target = None
        self._image_zoom = None
        self._page_base_pix = {}
        self._page_job = None
        self._hires_timer.stop()
        if self._hires_job is not None:
            self._hires_job.cancel()
            self._hires_job = None

    def _set_zoom_target(self, fn):
        """The view now showing zooms with fn; bring it to the file's level."""
        self._zoom_target = fn
        if abs(self._zoom - 1.0) > 1e-6:
            fn(self._zoom, 1.0, None)

    # ------------------------------------------------------------ the keys
    def zoom_step(self, steps: int, anchor: QPoint = None):
        zoom = self._zoom
        for _ in range(abs(steps)):
            zoom = next_zoom(zoom, steps)
        self._zoom_to(zoom, anchor)

    def zoom_reset(self):
        self._zoom_to(1.0, None)

    def _zoom_to(self, zoom: float, anchor):
        target = self._zoom_target or self._generic_zoom_target()
        if target is None:
            return  # nothing here zooms
        old, self._zoom = self._zoom, zoom
        if abs(zoom - old) > 1e-6:
            target(zoom, old, anchor)
        self._show_zoom_toast(zoom)

    def _show_zoom_toast(self, zoom: float):
        if self._zoom_toast is None:
            toast = QLabel(self.panel)
            toast.setObjectName("zoomToast")
            toast.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            timer = QTimer(toast)
            timer.setSingleShot(True)
            timer.timeout.connect(toast.hide)
            toast.timer = timer
            self._zoom_toast = toast
        toast = self._zoom_toast
        t = self.theme
        toast.setStyleSheet(
            f"background: {t['surface']}; color: {t['text']};"
            f" border: 1px solid {t['border']}; border-radius: 8px;"
            " padding: 6px 14px; font-weight: 600;")
        toast.setText(f"{round(zoom * 100)}%")
        toast.adjustSize()
        toast.move((self.panel.width() - toast.width()) // 2,
                   self.panel.height() - toast.height() - 28)
        toast.raise_()
        toast.show()
        toast.timer.start(TOAST_MS)

    # --------------------------------------------------- text, tables, web
    def _generic_zoom_target(self):
        """For the views without a zoom of their own: the fonts of their
        text boxes and tables, or an HTML page's zoom."""
        top = self.content.currentWidget()
        if top is None:
            return None
        widgets = [top] + top.findChildren(QWidget)
        texts = [w for w in widgets if isinstance(w, (QPlainTextEdit, QTableWidget))]
        webs = [w for w in widgets if hasattr(w, "setZoomFactor")]
        if not texts and not webs:
            return None

        def apply(zoom, _old, _anchor):
            for w in texts:
                self._zoom_font(w, zoom)
            for w in webs:
                w.setZoomFactor(zoom)
        return apply

    @staticmethod
    def _zoom_font(widget, zoom: float):
        # The font comes from the panel's stylesheet, which wins over
        # setFont(), so the zoom is a stylesheet rule of the widget's own.
        if widget.property("qv_font_px") is None:
            widget.setProperty("qv_font_px", QFontInfo(widget.font()).pixelSize())
            widget.setProperty("qv_style", widget.styleSheet())
        base, style = widget.property("qv_font_px"), widget.property("qv_style")
        if abs(zoom - 1.0) < 1e-6:
            widget.setStyleSheet(style)
        else:
            px = max(4, round(base * zoom))
            kind = "QTableWidget, QHeaderView" if isinstance(widget, QTableWidget) \
                else type(widget).__name__
            widget.setStyleSheet(f"{style}\n{kind} {{ font-size: {px}px; }}")
        if isinstance(widget, QTableWidget):
            widget.resizeRowsToContents()

    # -------------------------------------------------------------- images
    def zoomable_image(self, label: QLabel, size: QSize, hires=None) -> QWidget:
        """Wrap an image label for zooming; the widget to show instead.

        size is the image's shown (logical) size. hires, for a still image
        decoded smaller than the original, is (path, original QSize): a
        zoom past the decoded size then asks the jail for more pixels.
        """
        label.setFixedSize(size)
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll.setWidgetResizable(False)
        scroll.setStyleSheet("background: transparent;")
        scroll.setWidget(label)
        self._image_zoom = {"label": label, "scroll": scroll, "base": QSize(size),
                            "hires": hires, "shown": QSize(size)}
        self._set_zoom_target(self._zoom_image)
        return scroll

    def _zoom_image(self, zoom, old, anchor):
        state = self._image_zoom
        if state is None:
            return
        label, scroll = state["label"], state["scroll"]
        point, fx, fy = self._anchor_in(scroll, label, anchor)
        label.setFixedSize(scaled(state["base"], zoom))
        fit_label(label)
        self._restore_anchor(scroll, label, point, fx, fy)
        if state["hires"] is not None:
            self._hires_timer.start(HIRES_DELAY_MS)

    def _image_hires(self):
        """Decode the image again at the size it is now shown, if the
        original has more pixels than the label does."""
        state = self._image_zoom
        path, orig = state["hires"]
        want = state["label"].size()
        if want.width() <= state["shown"].width() or \
                state["shown"].width() >= orig.width():
            return
        want = want.boundedTo(orig).boundedTo(QSize(IMAGE_MAX_SIDE, IMAGE_MAX_SIDE))
        try:
            st = os.stat(path)
        except OSError:
            return
        key = cache_key(path, st, want.width(), want.height())
        png = cache_read(key)
        if png is not None:
            img = QImage.fromData(png)
            if not img.isNull():
                self._image_more_pixels(state, img)
                return
        got = {"frames": [], "job": None}

        def on_frame(data: bytes):
            got["frames"].append(data)
            if len(got["frames"]) == 1 and self._image_zoom is state:
                img = image_from_raw(data, got["job"].header)
                if not img.isNull():
                    self._image_more_pixels(state, img)

        def on_done(ok: bool, error: str):
            if self._hires_job is got["job"]:
                self._hires_job = None
            frames = got["frames"]
            if ok and len(frames) > 1 and is_cache_blob(frames[1]):
                cache_write(key, frames[1])
            elif not ok:
                log.debug("zoomed image render failed: %s (%s)", path, error[:200])

        if self._hires_job is not None:
            self._hires_job.cancel()
        got["job"] = self._hires_job = SandboxJob(
            self.pool, path, {"op": "image", "max_w": want.width(), "max_h": want.height()},
            on_frame, on_done, self)

    @staticmethod
    def _image_more_pixels(state, img: QImage):
        if img.width() <= state["shown"].width():
            return
        state["shown"] = img.size()
        label = state["label"]
        label.setPixmap(QPixmap.fromImage(img))
        fit_label(label)

    # ---------------------------------------------------------- page views
    def zoomable_pages(self, path: str, op: str, page_w: int, extra: dict):
        """The page column now showing zooms; called once it is built."""
        self._page_job = {"path": path, "op": op, "page_w": page_w,
                          "extra": dict(extra or {})}
        bar = self._page_scroll.verticalScrollBar()
        bar.valueChanged.connect(self._schedule_hires)
        self._page_scroll.horizontalScrollBar().valueChanged.connect(self._schedule_hires)
        self._set_zoom_target(self._zoom_pages)

    def page_label_sized(self, label: QLabel, base: QSize):
        """Give a page label its normal size, shown at the current zoom."""
        label.setProperty("qv_base", QSize(base))
        label.setProperty("qv_zoom", self._zoom)
        label.setFixedSize(scaled(base, self._zoom))
        for child in label.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly):
            child.setGeometry(label.rect())

    @staticmethod
    def page_base(label: QLabel) -> QSize:
        base = label.property("qv_base")
        return QSize(base) if base is not None else label.size()

    def page_pixmap(self, page: int, label: QLabel, pix: QPixmap):
        """A page's normal pixels have arrived."""
        self._page_base_pix[page] = pix
        label.setPixmap(pix)
        label.setProperty("qv_hires", None)
        fit_label(label)
        self._schedule_hires()

    def _zoom_pages(self, zoom, old, anchor):
        scroll = self._page_scroll
        if scroll is None:
            return
        page, point, fx, fy = self._page_anchor(anchor)
        for label in self._pdf_labels:
            self.page_label_sized(label, self.page_base(label))
            fit_label(label)
        if page is not None:
            # The column lays itself out again, and the scroll area takes
            # its new size, on posted events; run them now, or the anchor
            # is put back against the old geometry (and no horizontal range).
            scroll.widget().layout().activate()
            QApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
            self._restore_anchor(scroll, self._pdf_labels[page], point, fx, fy)
        self._schedule_hires()

    def _page_anchor(self, anchor):
        """(page, viewport point, fractions) to keep still while zooming:
        the point under the pointer, or the middle of the view."""
        scroll = self._page_scroll
        vp = scroll.viewport()
        point = vp.mapFromGlobal(anchor) if anchor is not None else None
        if point is None or not vp.rect().contains(point):
            point = vp.rect().center()
        best = None
        for i, label in enumerate(self._pdf_labels):
            top = label.mapTo(vp, QPoint(0, 0)).y()
            dy = 0 if top <= point.y() < top + label.height() else \
                min(abs(point.y() - top), abs(point.y() - top - label.height()))
            if best is None or dy < best[0]:
                best = (dy, i)
        if best is None:
            return None, point, 0.0, 0.0
        label = self._pdf_labels[best[1]]
        local = label.mapFrom(vp, point)
        return (best[1], point, local.x() / max(label.width(), 1),
                local.y() / max(label.height(), 1))

    @staticmethod
    def _anchor_in(scroll, label, anchor):
        vp = scroll.viewport()
        point = vp.mapFromGlobal(anchor) if anchor is not None else None
        if point is None or not vp.rect().contains(point):
            point = vp.rect().center()
        local = label.mapFrom(vp, point)
        return (point, local.x() / max(label.width(), 1),
                local.y() / max(label.height(), 1))

    @staticmethod
    def _restore_anchor(scroll, label, point, fx, fy):
        if label is None:
            return
        target = label.mapTo(scroll.viewport(), QPoint(round(fx * label.width()),
                                                       round(fy * label.height())))
        h, v = scroll.horizontalScrollBar(), scroll.verticalScrollBar()
        h.setValue(h.value() + target.x() - point.x())
        v.setValue(v.value() + target.y() - point.y())

    # ----------------------------------------------- sharper zoomed pages
    def _schedule_hires(self, *_):
        if self._zoom_target is not None and (
                self._zoom > 1.0 + 1e-6 or self._hires_held()):
            self._hires_timer.start(HIRES_DELAY_MS)

    def _hires_held(self) -> bool:
        return any(label.property("qv_hires") for label in self._pdf_labels)

    def _visible_pages(self) -> list:
        scroll = self._page_scroll
        if scroll is None:
            return []
        vp = scroll.viewport()
        out = []
        for i, label in enumerate(self._pdf_labels):
            top = label.mapTo(vp, QPoint(0, 0)).y()
            if top < vp.height() and top + label.height() > 0:
                out.append(i)
        return out[:HIRES_MAX_PAGES]

    def _hires_now(self):
        if self._image_zoom is not None:
            if self._image_zoom["hires"] is not None:
                self._image_hires()
            return
        if self._page_job is None or self._page_scroll is None:
            return
        want = round(min(self._page_scale * self._zoom, HIRES_MAX_SCALE), 2)
        zoomed_in = self._zoom > 1.0 + 1e-6
        visible = self._visible_pages() if zoomed_in else []
        # Pages off screen, or back at 100%, return to their own pixels.
        for i, label in enumerate(self._pdf_labels):
            if label.property("qv_hires") and i not in visible and i in self._page_base_pix:
                label.setPixmap(self._page_base_pix[i])
                label.setProperty("qv_hires", None)
                fit_label(label)
        need = [i for i in visible if i in self._page_base_pix
                and (self._pdf_labels[i].property("qv_hires") or 0) < want - 0.01]
        if not need or want <= self._page_scale + 0.01:
            return
        if self._hires_job is not None:
            self._hires_job.cancel()
        spec = self._page_job
        first, end = min(need), max(need) + 1
        job = {"op": spec["op"], "page_w": spec["page_w"], "max_pages": end,
               "start": first, "scale": want, **spec["extra"]}
        state = {"n": 0, "job": None}

        def on_frame(png: bytes):
            if self._hires_job is not state["job"]:
                return
            if state["job"].header.get("kind", "pages") != "pages":
                return
            page = first + state["n"]
            state["n"] += 1
            if not 0 <= page < len(self._pdf_labels) or \
                    round(min(self._page_scale * self._zoom, HIRES_MAX_SCALE), 2) != want:
                return
            img = QImage.fromData(png)
            if img.isNull():
                return
            label = self._pdf_labels[page]
            label.setPixmap(QPixmap.fromImage(img))
            label.setProperty("qv_hires", want)
            fit_label(label)

        def on_done(ok: bool, error: str):
            if self._hires_job is state["job"]:
                self._hires_job = None
                if not ok:
                    log.debug("zoomed pages render failed: %s (%s)",
                              spec["path"], error[:200])

        state["job"] = self._hires_job = SandboxJob(
            self.pool, spec["path"], job, on_frame, on_done, self)


__all__ = ["ZoomMixin", "ZOOM_STEPS", "next_zoom", "label_zoom", "fit_label"]
