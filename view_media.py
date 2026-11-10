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

"""Audio and video, played by a jailed worker.
"""


# What the daemon asks the renderers: which engine the workers will use for
# office documents, for the cache key, and the bounds a workbook is held to.
# renderers imports nothing at module level, so this loads no parser here.

from PySide6.QtCore import (
    Qt, QFileInfo,
)
from PySide6.QtGui import (
    QImage, QPixmap,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel, QMenu, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from common import (
    log,
    MEDIA_BUTTON_H,
    MEDIA_BUTTON_W,
    PLAYBACK_RATES,
)
from sandbox import (
    MediaSession,
)
from widgets import (
    SeekSlider,
)

def _clock(ms) -> str:
    s = max(int(ms), 0) // 1000
    return f"{s // 60}:{s % 60:02d}"


class PlaybackBar(QWidget):
    """The row under a playing file: play/pause, timeline, time, speed, mute.

    Holds the playback state the row shows, and talks to the player only
    through send(msg) — so it is built before the player exists, and the
    player's reports come back in through set_duration(), set_position()
    and ended().
    """

    def __init__(self, send):
        super().__init__()
        self._send = send
        self.duration = 0
        self.playing = True
        self.rate = 1.0
        self.muted = False

        controls = QHBoxLayout(self)
        controls.setContentsMargins(14, 0, 14, 0)
        self.play_btn = QPushButton("⏸")
        self.play_btn.setObjectName("openBtn")
        self.slider = SeekSlider(Qt.Horizontal)
        self.time_lbl = QLabel("0:00 / 0:00")
        self.speed_btn = QPushButton("1×")
        self.speed_btn.setObjectName("openBtn")
        self.speed_menu = QMenu(self.speed_btn)
        self.speed_btn.setMenu(self.speed_menu)
        self.mute_btn = QPushButton("🔊")
        self.mute_btn.setObjectName("openBtn")
        # Sized by hand rather than from sizeHint(). A button's natural
        # height follows the glyphs in its own label, and a pause bar, a
        # text label and an emoji do not agree — left to themselves the
        # three came out 29, 25 and 20 pixels tall in the same row. The
        # hints are not stable either: they report one width before the
        # stylesheet is applied and another after, so measuring at build
        # time gives whichever the timing happens to produce.
        self.play_btn.setFixedSize(40, MEDIA_BUTTON_H)
        self.speed_btn.setFixedSize(MEDIA_BUTTON_W, MEDIA_BUTTON_H)
        self.mute_btn.setFixedSize(MEDIA_BUTTON_W, MEDIA_BUTTON_H)
        controls.addWidget(self.play_btn)
        controls.addWidget(self.slider, 1)
        controls.addWidget(self.time_lbl)
        controls.addWidget(self.speed_btn)
        controls.addWidget(self.mute_btn)

        for rate in PLAYBACK_RATES:
            action = self.speed_menu.addAction(f"{rate:g}×")
            action.setCheckable(True)
            action.setChecked(rate == 1.0)
            action.setData(rate)
            action.triggered.connect(
                lambda _checked=False, r=rate: self.set_rate(r)
            )
        self.play_btn.clicked.connect(self.toggle)
        self.mute_btn.clicked.connect(self.toggle_mute)
        self.slider.sliderMoved.connect(
            lambda p: self._send({"t": "seek", "position": p})
        )

    def fit_time_label(self):
        # The readout follows the handle during a drag, so a clip
        # crossing 9:59 into 10:00 would widen the label, shrink the
        # slider next to it and move the value out from under the
        # cursor. Widened once per duration instead — the position
        # never formats longer than the duration does — which happens
        # before playback starts and never mid-drag. Measured with the
        # panel stylesheet on, unlike the buttons' fixed sizes: so not
        # here in the constructor, but once the row is in the panel
        # (show_media calls this) and on every new duration.
        longest = f"{_clock(self.duration)} / {_clock(self.duration)}"
        self.time_lbl.setFixedWidth(
            self.time_lbl.fontMetrics().horizontalAdvance(longest) + 4
        )

    # -------------------------------------------------- player → the row
    def set_duration(self, ms):
        self.duration = ms
        self.slider.setRange(0, ms)
        self.fit_time_label()

    def set_position(self, p):
        if self.slider.isSliderDown():
            # Mid-drag: the player is still reporting where it was, and
            # writing that back would drag the handle out from under the
            # cursor until the seek lands. The readout still follows the
            # handle, so the drag shows where it is going to land.
            p = self.slider.value()
        else:
            self.slider.blockSignals(True)
            self.slider.setValue(p)
            self.slider.blockSignals(False)
        self.time_lbl.setText(f"{_clock(p)} / {_clock(self.duration)}")

    def ended(self):
        self.playing = False
        self.play_btn.setText("▶")

    # -------------------------------------------------- the row → player
    def toggle(self):
        self.playing = not self.playing
        self._send({"t": "play" if self.playing else "pause"})
        self.play_btn.setText("⏸" if self.playing else "▶")

    def set_rate(self, rate: float):
        self.rate = rate
        # %g so 1.0 reads as "1×" and 1.25 keeps its decimals.
        self.speed_btn.setText(f"{rate:g}×")
        for act in self.speed_menu.actions():
            act.setChecked(act.data() == rate)
        self._send({"t": "rate", "rate": rate})

    def toggle_mute(self):
        self.muted = not self.muted
        self.mute_btn.setText("🔇" if self.muted else "🔊")
        self._send({"t": "mute", "muted": self.muted})


class MediaViewMixin:
    """Audio and video, played by a jailed worker.

    Mixed into QuickView, whose state (self.content, the render job,
    the current path…) these methods use; not usable on its own.
    """

    # ------------------------------------------------------------ media
    # Audio and video are decoded by media_worker.py inside the jail, which
    # also owns the audio clock (so Qt keeps doing A/V sync in there). What
    # arrives here is finished RGB frames in shared memory plus position
    # updates — the daemon runs no demuxer and no codec.

    def show_media(self, path: str, video: bool):
        wrap, surface, (max_w, max_h) = self._media_stage(path, video)
        bar = PlaybackBar(lambda msg: self.media.send(msg))
        wrap.layout().addWidget(bar)
        self.content.addWidget(wrap)
        if video:
            avail = self.screen_avail()
            self.set_panel_size(int(avail.width() * 0.6), int(avail.height() * 0.65))
        else:
            self.set_panel_size(520, 320)
        bar.fit_time_label()

        def on_frame(img: QImage):
            if surface is not None:
                self._paint_video_frame(surface, img)

        def on_error(msg):
            error = msg if isinstance(msg, str) else msg.get("error", "failed")
            log.warning("media playback failed: %s (%s)", path, error[:500])
            if self.current_path != path:
                return
            self.clear_content()
            self.show_fallback(path, self.mime_db.mimeTypeForFile(path).name())

        self.media = MediaSession(
            self, path, max_w, max_h,
            {
                "frame": on_frame,
                "meta": lambda msg: bar.set_duration(msg.get("duration", 0)),
                "position": lambda msg: bar.set_position(msg.get("position", 0)),
                "eof": lambda _msg=None: bar.ended(),
                "error": on_error,
            },
        )

    def _media_stage(self, path: str, video: bool):
        """The area above the controls: (wrap, video surface or None, the
        frame budget the player decodes to)."""
        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 8)
        lay.setSpacing(6)
        if video:
            avail = self.screen_avail()
            surface = QLabel()
            surface.setAlignment(Qt.AlignCenter)
            surface.setStyleSheet("background: black;")
            surface.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
            lay.addWidget(surface, 1)
            return wrap, surface, (int(avail.width() * 0.6),
                                   int(avail.height() * 0.65))
        icon = self.icon_provider.icon(QFileInfo(path))
        art = QLabel()
        art.setAlignment(Qt.AlignCenter)
        art.setPixmap(icon.pixmap(128, 128))
        lay.addWidget(art, 1)
        # Audio still needs a frame budget for cover art the decoder may
        # emit; keep it small.
        return wrap, None, (640, 640)

    @staticmethod
    def _paint_video_frame(surface: QLabel, img: QImage):
        pix = QPixmap.fromImage(img)
        if pix.width() > surface.width() or pix.height() > surface.height():
            pix = pix.scaled(
                surface.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        surface.setPixmap(pix)
