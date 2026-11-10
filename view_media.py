#!/usr/bin/env python3
# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Mustapha Alioglou
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
        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 8)
        lay.setSpacing(6)

        avail = self.screen_avail()
        if video:
            surface = QLabel()
            surface.setAlignment(Qt.AlignCenter)
            surface.setStyleSheet("background: black;")
            surface.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
            lay.addWidget(surface, 1)
            max_w = int(avail.width() * 0.6)
            max_h = int(avail.height() * 0.65)
        else:
            surface = None
            icon = self.icon_provider.icon(QFileInfo(path))
            art = QLabel()
            art.setAlignment(Qt.AlignCenter)
            art.setPixmap(icon.pixmap(128, 128))
            lay.addWidget(art, 1)
            # Audio still needs a frame budget for cover art the decoder may
            # emit; keep it small.
            max_w, max_h = 640, 640

        controls = QHBoxLayout()
        controls.setContentsMargins(14, 0, 14, 0)
        play_btn = QPushButton("⏸")
        play_btn.setObjectName("openBtn")
        slider = SeekSlider(Qt.Horizontal)
        time_lbl = QLabel("0:00 / 0:00")
        speed_btn = QPushButton("1×")
        speed_btn.setObjectName("openBtn")
        speed_menu = QMenu(speed_btn)
        speed_btn.setMenu(speed_menu)
        mute_btn = QPushButton("🔊")
        mute_btn.setObjectName("openBtn")
        # Sized by hand rather than from sizeHint(). A button's natural
        # height follows the glyphs in its own label, and a pause bar, a
        # text label and an emoji do not agree — left to themselves the
        # three came out 29, 25 and 20 pixels tall in the same row. The
        # hints are not stable either: they report one width before the
        # stylesheet is applied and another after, so measuring at build
        # time gives whichever the timing happens to produce.
        play_btn.setFixedSize(40, MEDIA_BUTTON_H)
        speed_btn.setFixedSize(MEDIA_BUTTON_W, MEDIA_BUTTON_H)
        mute_btn.setFixedSize(MEDIA_BUTTON_W, MEDIA_BUTTON_H)
        controls.addWidget(play_btn)
        controls.addWidget(slider, 1)
        controls.addWidget(time_lbl)
        controls.addWidget(speed_btn)
        controls.addWidget(mute_btn)
        lay.addLayout(controls)

        self.content.addWidget(wrap)
        if video:
            self.set_panel_size(int(avail.width() * 0.6), int(avail.height() * 0.65))
        else:
            self.set_panel_size(520, 320)

        def fmt(ms):
            s = max(int(ms), 0) // 1000
            return f"{s // 60}:{s % 60:02d}"

        def fit_time_lbl():
            # The readout follows the handle during a drag, so a clip
            # crossing 9:59 into 10:00 would widen the label, shrink the
            # slider next to it and move the value out from under the
            # cursor. Widened once per duration instead — the position
            # never formats longer than the duration does — which happens
            # before playback starts and never mid-drag. Measured after
            # the panel stylesheet is on, unlike the buttons above.
            longest = f"{fmt(state['duration'])} / {fmt(state['duration'])}"
            time_lbl.setFixedWidth(
                time_lbl.fontMetrics().horizontalAdvance(longest) + 4
            )

        state = {"duration": 0, "playing": True, "rate": 1.0, "muted": False}
        fit_time_lbl()

        def on_frame(img: QImage):
            if surface is None:
                return
            pix = QPixmap.fromImage(img)
            if pix.width() > surface.width() or pix.height() > surface.height():
                pix = pix.scaled(
                    surface.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
            surface.setPixmap(pix)

        def on_meta(msg):
            state["duration"] = msg.get("duration", 0)
            slider.setRange(0, state["duration"])
            fit_time_lbl()

        def on_position(msg):
            p = msg.get("position", 0)
            if slider.isSliderDown():
                # Mid-drag: the player is still reporting where it was, and
                # writing that back would drag the handle out from under the
                # cursor until the seek lands. The readout still follows the
                # handle, so the drag shows where it is going to land.
                p = slider.value()
            else:
                slider.blockSignals(True)
                slider.setValue(p)
                slider.blockSignals(False)
            time_lbl.setText(f"{fmt(p)} / {fmt(state['duration'])}")

        def on_eof(_msg=None):
            state["playing"] = False
            play_btn.setText("▶")

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
                "frame": on_frame, "meta": on_meta, "position": on_position,
                "eof": on_eof, "error": on_error,
            },
        )

        def toggle():
            state["playing"] = not state["playing"]
            self.media.send({"t": "play" if state["playing"] else "pause"})
            play_btn.setText("⏸" if state["playing"] else "▶")

        def set_rate(rate: float):
            state["rate"] = rate
            # %g so 1.0 reads as "1×" and 1.25 keeps its decimals.
            speed_btn.setText(f"{rate:g}×")
            for act in speed_menu.actions():
                act.setChecked(act.data() == rate)
            self.media.send({"t": "rate", "rate": rate})

        for rate in PLAYBACK_RATES:
            action = speed_menu.addAction(f"{rate:g}×")
            action.setCheckable(True)
            action.setChecked(rate == 1.0)
            action.setData(rate)
            action.triggered.connect(
                lambda _checked=False, r=rate: set_rate(r)
            )

        def toggle_mute():
            state["muted"] = not state["muted"]
            mute_btn.setText("🔇" if state["muted"] else "🔊")
            self.media.send({"t": "mute", "muted": state["muted"]})

        play_btn.clicked.connect(toggle)
        mute_btn.clicked.connect(toggle_mute)
        slider.sliderMoved.connect(
            lambda p: self.media.send({"t": "seek", "position": p})
        )
