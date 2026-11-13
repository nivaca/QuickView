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

"""Still images, neighbour prefetch and animations.
"""

import os
import re
import struct

# What the daemon asks the renderers: which engine the workers will use for
# office documents, for the cache key, and the bounds a workbook is held to.
# renderers imports nothing at module level, so this loads no parser here.

from PySide6.QtCore import (
    QSize, Qt, QTimer,
)
from PySide6.QtGui import (
    QImage, QPixmap,
)
from PySide6.QtWidgets import (
    QLabel,
)

from common import (
    ANIM_MAX_FRAMES,
    ANIM_MAX_PIXMAP_BYTES,
    cache_has,
    cache_key,
    cache_read,
    cache_remove,
    cache_write,
    image_from_raw,
    is_cache_blob,
    log,
    mem_cache_bytes,
)
from sandbox import (
    SandboxJob,
)


def original_size(dims: str):
    """The original's size from the titlebar's "W×H", or None."""
    m = re.match(r"\s*(\d+)\s*[×x]\s*(\d+)", dims or "")
    return QSize(int(m.group(1)), int(m.group(2))) if m else None


class ImageViewMixin:
    """Still images, neighbour prefetch and animations.

    Mixed into QuickView, whose state (self.content, the render job,
    the current path…) these methods use; not usable on its own.
    """

    def image_fit_box(self) -> tuple:
        avail = self.screen_avail()
        return int(avail.width() * 0.85) - 48, int(avail.height() * 0.85) - 96

    def show_image(self, path: str):
        max_w, max_h = self.image_fit_box()
        try:
            st = os.stat(path)
        except OSError as exc:
            self.show_message(str(exc))
            return
        key = cache_key(path, st, max_w, max_h)
        if not self._show_cached_image(path, key):
            self._render_image(path, key, max_w, max_h)

    def _show_cached_image(self, path: str, key: str) -> bool:
        """Show the preview from the memory or disk tier, if either has it."""
        hit = self._mem_cache.get(key)
        if hit is not None:
            self._mem_cache.move_to_end(key)
            log.debug("memory cache hit: %s", path)
            pix, dims, _nbytes = hit
            self._display_image(path, pix, dims, hires=True)
            return True

        png = cache_read(key)
        if png is not None:
            img = QImage.fromData(png)
            if not img.isNull():
                log.debug("disk cache hit: %s", path)
                self._show_decoded(path, key, img)
                return True
            # A bad entry would otherwise be served on every view until the
            # source file's mtime changes — drop it and fall through to a
            # fresh render.
            log.warning("dropping corrupt cache entry for %s", path)
            cache_remove(key)
        return False

    def _render_image(self, path: str, key: str, max_w: int, max_h: int):
        """Decode in the jail, show the pixels, then cache the encoded copy."""
        # Decode asynchronously in the jail: a slow or hostile file must not
        # freeze the event loop — keys, the close button and the daemon socket
        # stay live while the worker works.
        self.show_message("Loading preview…")
        # Frame 0 is raw pixels to show, frame 1 the encoded copy to cache
        # — see the worker's module docstring.
        got = {"frames": [], "job": None, "shown": False}

        def on_frame(data: bytes):
            got["frames"].append(data)
            if len(got["frames"]) != 1:
                return  # frame 2 is the cache copy; on_done deals with it
            job = got["job"]
            if not self._is_current(job, path):
                return  # superseded, or the user moved on while we rendered
            # Painted here rather than in on_done: the pixels are complete
            # the moment they land, and waiting for the worker's cache copy
            # would put that encode back in front of the user.
            img = image_from_raw(data, job.header)
            if img.isNull():
                return  # on_done reports it
            got["shown"] = True
            log.debug("rendered: %s", path)
            # Hand the job off before displaying. _show_decoded clears the
            # panel, clear_content() calls _cancel_render(), and that would
            # kill the worker halfway through the encode this still needs
            # for the cache. Nothing cancels it now; it is parented to the
            # window, finishes in tens of ms and tears itself down.
            self._render_job = None
            self._show_decoded(path, key, img, job.header.get("orig"))

        def on_done(ok: bool, error: str):
            frames = got["frames"]
            if got["shown"]:
                # Not gated on the job still being current: the cache is
                # keyed by path and size, so a frame that lands after the
                # user has moved on is still the right answer for this file.
                # Persisted only once the full stream arrives — a truncated
                # blob behind a valid magic must not become a sticky cache
                # entry. A worker that died after the pixels but before the
                # encode leaves the image on screen and nothing cached.
                if ok and len(frames) > 1 and is_cache_blob(frames[1]):
                    cache_write(key, frames[1])
                else:
                    # The image is on screen either way; say so, or a cache
                    # that silently never fills looks like a fast renderer.
                    log.warning(
                        "not cached: %s (ok=%s frames=%d error=%s)",
                        path, ok, len(frames), error[:200],
                    )
                return
            if not self._is_current(got["job"], path):
                return  # superseded, or the user moved on while we rendered
            self._render_job = None
            log.warning("render failed: %s (%s)", path, error[:500])
            self.clear_content()
            self.show_fallback(
                path, self.mime_db.mimeTypeForFile(path).name()
            )

        got["job"] = self._render_job = SandboxJob(
            self.pool, path,
            {"op": "image", "max_w": max_w, "max_h": max_h},
            on_frame, on_done, self,
        )

    def _show_decoded(self, path: str, key: str, img: QImage, dims: str = ""):
        """Display a successfully decoded preview and remember its pixmap.

        `dims` comes from the worker's header on a fresh render; the disk
        cache-hit path passes nothing and falls back to the text chunk in
        the cached image.
        """
        dims = dims or img.text("QuickView:OrigSize") or (
            f"{img.width()}×{img.height()}"
        )
        pix = QPixmap.fromImage(img)
        nbytes = pix.width() * pix.height() * max(pix.depth(), 1) // 8
        self._mem_cache.pop(key, None)
        self._mem_cache[key] = (pix, dims, nbytes)
        # The byte total is recomputed from the stored entries rather than
        # tracked in a separate counter: the cache holds a few dozen entries
        # at most, and derived state can't drift in a process that never
        # exits.
        while (
            sum(nb for *_, nb in self._mem_cache.values()) > mem_cache_bytes()
            and len(self._mem_cache) > 1
        ):
            self._mem_cache.popitem(last=False)
        self._display_image(path, pix, dims, hires=True)

    def _display_image(self, path: str, pix: QPixmap, dims: str,
                       hires: bool = False):
        """Show a still image. hires: it is the file's own image, decoded
        to fit, so a zoom past that size can have the jail decode more of
        its pixels (see view_zoom)."""
        self.clear_content()
        label = QLabel()
        label.setAlignment(Qt.AlignCenter)
        label.setPixmap(pix)
        orig = original_size(dims) if hires else None
        self.content.addWidget(self.zoomable_image(
            label, pix.deviceIndependentSize().toSize(),
            (path, orig) if orig is not None else None))
        self.set_panel_size(pix.width() + 24, pix.height() + 24)
        self.set_title(f"{os.path.basename(path)}  —  {dims}")
        self._prefetch_neighbors()

    # ------------------------------------------------------------- prefetch
    # Warm the disk cache for the files ← → would show next, so paging
    # through a folder of photos never waits on a cold decode. Same sandboxed
    # helper, same cache key — show_image() then hits the disk tier. The
    # queue itself, shared with documents, is QuickView._prefetch_neighbors.

    def _image_prefetch(self, path: str, mime: str):
        """A prefetch task warming show_image()'s cache entry, or None."""
        max_w, max_h = self.image_fit_box()
        try:
            st = os.stat(path)
        except OSError:
            return None
        key = cache_key(path, st, max_w, max_h)
        if key in self._mem_cache or cache_has(key):
            return None

        def start(done):
            got = {"blob": None}

            def on_frame(data: bytes):
                # Only the encoded frame belongs in the cache. "raw": False
                # below means that is the one frame we get, but check rather
                # than trust the frame order — this consumer never displays.
                if is_cache_blob(data):
                    got["blob"] = data

            def on_done(ok: bool, _error: str):
                blob = got["blob"]
                if ok and blob:
                    log.debug("prefetched: %s", path)
                    cache_write(key, blob)
                done()

            return SandboxJob(
                self.pool, path,
                # No raw frame: prefetch fills the disk cache and shows
                # nothing, so the pixels would be several megabytes copied
                # to be dropped.
                {"op": "image", "max_w": max_w, "max_h": max_h, "raw": False},
                on_frame, on_done, self,
            )
        return start

    # ------------------------------------------------------- animation
    # QMovie decodes an untrusted GIF frame by frame for as long as the
    # window is open, so it never ran in the daemon safely. Instead the
    # jailed worker decodes every frame up front and streams them here as
    # PNGs; playback is then a timer cycling pixmaps the daemon already
    # holds — no animation parser in this process at all.

    def show_anim(self, path: str):
        max_w, max_h = self.image_fit_box()
        self.show_message("Loading preview…")
        state = {"frames": [], "bytes": 0, "job": None}

        def on_frame(payload: bytes):
            if not self._is_current(state["job"], path):
                return
            if len(payload) < 4:  # the worker is untrusted: no short reads
                return
            delay = struct.unpack(">I", payload[:4])[0]
            img = QImage.fromData(payload[4:])
            if img.isNull():
                return
            pix = QPixmap.fromImage(img)
            state["bytes"] += pix.width() * pix.height() * 4
            state["frames"].append((pix, delay))
            if len(state["frames"]) == 1:
                self._begin_anim(path, state)
            if (
                len(state["frames"]) >= ANIM_MAX_FRAMES
                or state["bytes"] >= ANIM_MAX_PIXMAP_BYTES
            ):
                # Enough: play what we have rather than let a worker that
                # streams for ever fill the daemon's heap.
                log.debug(
                    "animation capped at %d frames: %s",
                    len(state["frames"]), path,
                )
                self._cancel_render()

        def on_done(ok: bool, error: str):
            if not self._is_current(state["job"], path):
                return
            self._render_job = None
            if state["frames"]:
                return  # partial decodes still animate what arrived
            log.warning("animation decode failed: %s (%s)", path, error[:500])
            # Not an animation we can decode — a still frame is still useful.
            self.clear_content()
            self.show_image(path)

        state["job"] = self._render_job = SandboxJob(
            self.pool, path, {"op": "anim", "max_w": max_w, "max_h": max_h},
            on_frame, on_done, self,
        )

    def _begin_anim(self, path: str, state: dict):
        """Show frame 0 and start the cycle; later frames join as they land."""
        label = QLabel()
        label.setAlignment(Qt.AlignCenter)
        pix, _delay = state["frames"][0]
        label.setPixmap(pix)
        self._clear_widgets()
        self.content.addWidget(
            self.zoomable_image(label, pix.deviceIndependentSize().toSize()))
        self.set_panel_size(pix.width() + 24, pix.height() + 24)

        idx = {"i": 0}
        timer = QTimer(self)
        timer.setSingleShot(True)
        self.anim_timer = timer

        def tick():
            frames = state["frames"]
            if not frames or self.current_path != path:
                return
            idx["i"] = (idx["i"] + 1) % len(frames)
            pix, delay = frames[idx["i"]]
            label.setPixmap(pix)
            timer.start(delay)

        timer.timeout.connect(tick)
        timer.start(state["frames"][0][1])
