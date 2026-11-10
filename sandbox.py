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

"""The bubblewrap jail and the workers that run inside it.

Every parser runs here, out of process: SandboxJob for one-shot
renders, MediaSession for a playing file. The daemon only ever sees
finished pixels and text.
"""

import array
import json
import mmap
import os
import shutil
import socket
import struct
import subprocess
import sys

# What the daemon asks the renderers: which engine the workers will use for
# office documents, for the cache key, and the bounds a workbook is held to.
# renderers imports nothing at module level, so this loads no parser here.

from PySide6.QtCore import (
    QObject, QSocketNotifier,
    QTimer, Signal,
)
from PySide6.QtGui import (
    QImage,
)

from common import (
    APP_DIR,
    log,
    MAX_FRAME_BYTES,
    MEDIA_SLOTS,
    OFFICE_ENGINE,
    WORKER_HELPER,
)
import renderers


# ---------------------------------------------------------------- sandbox

_warned_no_bwrap = False
_bwrap_path = ...  # ... = not looked up yet; None = not installed


def find_bwrap() -> str | None:
    """shutil.which("bwrap"), resolved once — every render asked before."""
    global _bwrap_path
    if _bwrap_path is ...:
        _bwrap_path = shutil.which("bwrap")
    return _bwrap_path


def _font_binds() -> list:
    """Read-only binds that let Qt find fonts *and* their prebuilt cache.

    Without these the jail has no /etc/fonts, so fontconfig rebuilds its
    index on every single spawn: measured 583 ms vs 148 ms for a one-page
    PDF. /etc/fonts alone is worse than neither (749 ms) — it turns on the
    scan without supplying the cache that makes it cheap — so the config
    is only bound when a cache is there to go with it.
    """
    # The jail runs with --clearenv and HOME=/tmp, so fontconfig looks for
    # a user cache in /tmp/.cache/fontconfig — binding ~/.cache/fontconfig
    # at its real path leaves it invisible in there, which is how a system
    # with no /var/cache/fontconfig ended up with /etc/fonts and no usable
    # cache: the 749 ms worst case above.
    caches = []
    if os.path.isdir("/var/cache/fontconfig"):
        caches.append(("/var/cache/fontconfig", "/var/cache/fontconfig"))
    user = os.path.expanduser("~/.cache/fontconfig")
    if os.path.isdir(user):
        caches.append((user, "/tmp/.cache/fontconfig"))
    if not caches or not os.path.isdir("/etc/fonts"):
        return []
    binds = ["--ro-bind", "/etc/fonts", "/etc/fonts"]
    for src, dest in caches:
        binds += ["--ro-bind", src, dest]
    return binds


def _toplevel_binds() -> list:
    """Recreate the host's /lib, /lib64, /bin, /sbin inside the jail.

    Only /usr is bound, so the loader's own path has to be rebuilt. Where
    these point differs per distro — /lib64 -> usr/lib on Arch, but
    usr/lib64 on Fedora and Debian, where guessing "usr/lib" leaves the
    jail with no ld.so and every helper dies before main() — so copy the
    host's real link target rather than assume one. A distro that never
    merged /usr has these as real directories: bind those read-only.
    """
    flags = []
    for path in ("/lib", "/lib64", "/bin", "/sbin"):
        if os.path.islink(path):
            flags += ["--symlink", os.readlink(path), path]
        elif os.path.isdir(path):
            flags += ["--ro-bind", path, path]
    return flags


def sandbox_flags(bwrap: str) -> list:
    """The jail every helper runs in: read-only /usr + this app dir, no
    network, no writes, no capabilities, its own everything."""
    return [
        bwrap,
        "--ro-bind", "/usr", "/usr",
        *_toplevel_binds(),
        "--proc", "/proc",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
        "--ro-bind", APP_DIR, APP_DIR,
        *_font_binds(),
        "--unshare-all",
        "--cap-drop", "ALL",
        "--die-with-parent",
        "--new-session",
        "--clearenv",
        "--setenv", "QT_QPA_PLATFORM", "offscreen",
        "--setenv", "HOME", "/tmp",
        "--setenv", "XDG_RUNTIME_DIR", "/tmp",
    ]


# --------------------------------------------------------- worker pool
# The jail costs ~3 ms; importing PySide6 in the helper costs ~150 ms. So
# the helper is booted *before* it is needed and parked on a socket, and the
# file reaches it as a file descriptor (SCM_RIGHTS) rather than a bind
# mount — the jail then needs no access to the user's filesystem at all.
#
# Isolation is unchanged from the old throwaway helpers: a worker handles
# one file and exits. What changed is who waits for the boot — a spare, not
# the user.

WORKER_SPARES = 2
JOB_TIMEOUT_MS = 20000
MEDIA_HELPER = os.path.join(APP_DIR, "media_worker.py")


def _office_suite_binds() -> list:
    """A Flatpak LibreOffice, read-only, for the render workers alone.

    A distro LibreOffice is under /usr and needs nothing. A Flatpak one
    lives in the user's (or the system's) flatpak directory, so its app
    and runtime trees — and the user's own fonts, which documents are
    written in — are bound under renderers.FLATPAK_SUITE_ROOT, where the
    worker's renderers.suite_command() finds them. Code and fonts only:
    nothing writable, and no user document.
    """
    if OFFICE_ENGINE == "builtin":
        return []
    try:
        return renderers.flatpak_suite_binds()
    except OSError as exc:
        log.warning("Flatpak LibreOffice not bound into the jail: %s", exc)
        return []


def build_worker_command(fd: int) -> list | None:
    """bwrap command for a warm worker, or None when we must refuse.

    Note what is *not* here: no --ro-bind of any user file. The worker sees
    /usr, this app dir and fonts, and gets its file as a descriptor.
    """
    helper = [sys.executable, WORKER_HELPER, str(fd)]
    bwrap = find_bwrap()
    if bwrap:
        return sandbox_flags(bwrap) + _office_suite_binds() + ["--"] + helper
    if os.environ.get("QUICKVIEW_ALLOW_UNSANDBOXED") == "1":
        return helper
    global _warned_no_bwrap
    if not _warned_no_bwrap:
        _warned_no_bwrap = True
        log.warning(
            "bwrap not found — refusing to decode untrusted files "
            "(install bubblewrap, or set QUICKVIEW_ALLOW_UNSANDBOXED=1 "
            "to accept the risk)"
        )
    return None


class Worker:
    """A booted, idle, jailed process waiting for its one job."""

    def __init__(self, proc, sock):
        self.proc = proc
        self.sock = sock
        self.err = bytearray()
        # Drained from the moment it is spawned, not from the moment it is
        # given a job: a spare that chatters during Qt's boot (a broken font
        # cache, QT_LOGGING_RULES) would otherwise fill the 64 KiB pipe
        # buffer and block before it ever reads its request.
        self._errnotifier = QSocketNotifier(
            proc.stderr.fileno(), QSocketNotifier.Type.Read
        )
        self._errnotifier.activated.connect(self._drain_err)

    def _drain_err(self):
        try:
            chunk = os.read(self.proc.stderr.fileno(), 4096)
        except OSError:
            self._errnotifier.setEnabled(False)
            return
        if not chunk:
            self._errnotifier.setEnabled(False)
            return
        # Bounded: a hostile file can make Qt chatter indefinitely and we
        # only ever log the first few hundred characters.
        if len(self.err) < 4096:
            self.err += chunk

    def kill(self):
        self._errnotifier.setEnabled(False)
        for close in (self.sock.close, self.proc.kill):
            try:
                close()
            except OSError:
                pass
        try:
            # Reap it. SIGKILL is already delivered, so this returns at once;
            # skipping the wait would leave one zombie per preview behind in
            # a daemon that runs for weeks.
            self.proc.wait(timeout=2)
        except (subprocess.TimeoutExpired, OSError):
            log.warning("worker %d would not die", self.proc.pid)
        try:
            self.proc.stderr.close()
        except OSError:
            pass


class WorkerPool:
    """Keeps a couple of workers pre-booted so a preview never waits."""

    def __init__(self):
        self._spares = []

    def prime(self):
        """Top the pool back up. Cheap: fork+exec returns immediately and
        the Qt import happens in the child while the user reads."""
        while len(self._spares) < WORKER_SPARES:
            w = self._spawn()
            if w is None:
                return  # refused (no bwrap) — callers fall back
            self._spares.append(w)

    def take(self) -> Worker | None:
        while self._spares:
            w = self._spares.pop(0)
            if w.proc.poll() is None:  # still alive
                QTimer.singleShot(0, self.prime)
                return w
            log.debug("discarding dead spare worker")
            w.kill()
        w = self._spawn()  # pool was empty or stale — pay the boot cost
        QTimer.singleShot(0, self.prime)
        return w

    def shutdown(self):
        for w in self._spares:
            w.kill()
        self._spares.clear()

    def _spawn(self) -> Worker | None:
        parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        cmd = build_worker_command(child.fileno())
        if cmd is None:
            parent.close()
            child.close()
            return None
        try:
            os.set_inheritable(child.fileno(), True)
            proc = subprocess.Popen(
                cmd,
                pass_fds=(child.fileno(),),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            log.warning("worker spawn failed: %s", exc)
            parent.close()
            child.close()
            return None
        finally:
            child.close()
        return Worker(proc, parent)


def build_media_worker_command(fd: int) -> list | None:
    """Jail for the media player: the standard one plus an audio socket.

    Playing sound is the single capability the media worker has that the
    render workers don't. PipeWire (and its PulseAudio shim) are reached
    through sockets under the real XDG_RUNTIME_DIR, so they are bound into
    the jail's /tmp, which is where its XDG_RUNTIME_DIR points. Everything
    else — the filesystem, the network, the user's files — stays shut off.
    """
    helper = [sys.executable, MEDIA_HELPER, str(fd)]
    bwrap = find_bwrap()
    if not bwrap:
        if os.environ.get("QUICKVIEW_ALLOW_UNSANDBOXED") == "1":
            return helper
        return None
    run_dir = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    audio = []
    for name in ("pipewire-0", "pulse"):
        src = os.path.join(run_dir, name)
        if os.path.exists(src):
            audio += ["--ro-bind", src, f"/tmp/{name}"]
    if os.path.isdir("/etc/pipewire"):
        audio += ["--ro-bind", "/etc/pipewire", "/etc/pipewire"]
    if not audio:
        log.warning("no PipeWire/PulseAudio socket found — preview is muted")
    return sandbox_flags(bwrap) + audio + ["--"] + helper


class MediaSession(QObject):
    """A jailed QMediaPlayer, driven over a socket.

    The daemon holds no decoder: it sends transport commands, receives
    status, and blits frames the worker has written into shared memory.
    """

    def __init__(self, window, path, max_w, max_h, handlers):
        super().__init__(window)
        self._handlers = handlers
        self._buf = bytearray()
        self._alive = False
        self._mm = None
        self.slot_bytes = max_w * max_h * 4

        parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        cmd = build_media_worker_command(child.fileno())
        if cmd is None:
            parent.close()
            child.close()
            QTimer.singleShot(
                0, lambda: handlers["error"]("sandbox refused (no bwrap)")
            )
            return
        try:
            media_fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
        except OSError as exc:
            parent.close()
            child.close()
            QTimer.singleShot(0, lambda msg=str(exc): handlers["error"](msg))
            return

        # A memfd is the frame transport: an anonymous shared buffer that
        # crosses the jail as a descriptor, so it works with --unshare-ipc
        # (SysV/POSIX shared memory would not).
        frame_fd = os.memfd_create("quickview-frames")
        os.ftruncate(frame_fd, self.slot_bytes * MEDIA_SLOTS)
        self._mm = mmap.mmap(frame_fd, self.slot_bytes * MEDIA_SLOTS)

        try:
            os.set_inheritable(child.fileno(), True)
            self._proc = subprocess.Popen(
                cmd,
                pass_fds=(child.fileno(),),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            for fd in (media_fd, frame_fd):
                os.close(fd)
            # stop() is a no-op for a session that never started, so the
            # frame buffer is unmapped here or not at all.
            self._mm.close()
            self._mm = None
            parent.close()
            child.close()
            QTimer.singleShot(0, lambda msg=str(exc): handlers["error"](msg))
            return
        finally:
            child.close()

        self._sock = parent
        self._alive = True
        self._notifier = QSocketNotifier(
            parent.fileno(), QSocketNotifier.Type.Read, self
        )
        self._notifier.activated.connect(self._readable)

        job = json.dumps({
            "op": "media", "max_w": max_w, "max_h": max_h,
            "slot_bytes": self.slot_bytes,
        }).encode()
        try:
            parent.sendmsg(
                [struct.pack(">I", len(job))],
                [(
                    socket.SOL_SOCKET, socket.SCM_RIGHTS,
                    array.array("i", [media_fd, frame_fd]),
                )],
            )
            parent.sendall(job)
        except OSError as exc:
            QTimer.singleShot(0, lambda msg=str(exc): handlers["error"](msg))
        finally:
            os.close(media_fd)
            os.close(frame_fd)  # the worker and our mmap keep it alive

    # ------------------------------------------------------------ control
    def send(self, msg: dict):
        if not self._alive:
            return
        payload = json.dumps(msg).encode()
        try:
            self._sock.sendall(struct.pack(">I", len(payload)) + payload)
        except OSError:
            self.stop()

    def stop(self):
        if not self._alive:
            return
        self._alive = False
        self._notifier.setEnabled(False)
        try:
            self._sock.close()
        except OSError:
            pass
        try:
            self._proc.kill()
        except OSError:
            pass
        try:
            # Bounded, like Worker.kill(): SIGKILL is already delivered, so
            # this normally returns at once — but a worker wedged in an
            # uninterruptible read on a stalled mount must not take the
            # window, the shortcuts and the IPC socket down with it.
            self._proc.wait(timeout=2)
        except (subprocess.TimeoutExpired, OSError):
            log.warning("media worker %d would not die", self._proc.pid)
        if self._mm is not None:
            self._mm.close()
            self._mm = None

    # ------------------------------------------------------------ reading
    def _readable(self):
        if not self._alive:
            return
        try:
            chunk = self._sock.recv(1 << 16)
        except OSError as exc:
            self._handlers["error"](str(exc))
            self.stop()
            return
        if not chunk:
            self.stop()
            self._handlers["error"]("player exited")
            return
        self._buf += chunk
        while len(self._buf) >= 4:
            (n,) = struct.unpack(">I", self._buf[:4])
            if n > MAX_FRAME_BYTES or len(self._buf) < 4 + n:
                if n > MAX_FRAME_BYTES:
                    self.stop()
                return
            try:
                msg = json.loads(bytes(self._buf[4:4 + n]))
            except ValueError:
                self.stop()
                return
            del self._buf[:4 + n]
            self._dispatch(msg)

    def _dispatch(self, msg: dict):
        kind = msg.get("t")
        if kind == "frame":
            img = self.read_frame(msg)
            if img is not None:
                self._handlers["frame"](img)
        elif kind in self._handlers:
            self._handlers[kind](msg)

    def read_frame(self, msg: dict):
        """Copy one frame out of shared memory as a QImage."""
        if self._mm is None:
            return None
        try:
            slot, w, h = int(msg["slot"]), int(msg["w"]), int(msg["h"])
            stride = int(msg["stride"])
        except (KeyError, TypeError, ValueError):
            return None
        if not 0 <= slot < MEDIA_SLOTS:
            return None  # no such slot to release either
        img = self._copy_frame(slot, w, h, stride)
        # The slot is free for the worker to fill again — either because
        # the pixels are copied out, or because the frame was rejected and
        # there is nothing left to preserve. Until this ack lands, the
        # worker holds off, so a daemon busy with layout can no longer be
        # handed a slot whose contents have already been replaced.
        self.send({"t": "ack", "slot": slot})
        return img

    def _copy_frame(self, slot: int, w: int, h: int, stride: int):
        # The worker is untrusted, so every number is checked before it
        # reaches QImage: a frame claiming w=100000, h=1, stride=4 passes a
        # size check on stride * h alone and then reads far past the slot.
        if w <= 0 or h <= 0:
            return None
        if stride < w * 4:  # Format_RGB32: four bytes a pixel, minimum
            return None
        need = stride * h
        if need <= 0 or need > self.slot_bytes:
            return None
        # Copied, not wrapped: the worker fills this slot again as soon as
        # it is acked, and QImage would still be pointing at it.
        off = slot * self.slot_bytes
        data = bytes(self._mm[off:off + need])
        if len(data) < need:  # a short mmap slice would be read past, too
            return None
        return QImage(data, w, h, stride, QImage.Format.Format_RGB32).copy()


class FileReader(QObject):
    """Reads a bounded slice of a file on a pool thread.

    Only used for the text preview, which parses nothing — but a file on a
    stalled network mount blocks just as hard as a hostile parser, and the
    daemon's socket has to keep answering.

    Deliberately not a QRunnable: the pool touches a runnable again *after*
    run() returns (to check autoDelete), so a reader whose last reference
    was dropped by the daemon in the meantime would be a use-after-free.
    Handing the pool a bound method instead leaves the lifetime to Python —
    the pool's own wrapper holds this object until run() has finished.
    """

    done = Signal(bytes, str)

    def __init__(self, path: str, limit: int):
        super().__init__()
        self._path = path
        self._limit = limit

    def run(self):
        try:
            with open(self._path, "rb") as fh:
                self.done.emit(fh.read(self._limit), "")
        except OSError as exc:
            self.done.emit(b"", str(exc))


class SandboxJob(QObject):
    """One file parsed by one jailed worker, asynchronously.

    on_frame(payload) fires per frame as it arrives (so PDF page 1 shows
    while page 2 renders); on_done(ok, error) fires exactly once. Frames are
    length-prefixed the same way the standalone helpers stream them.
    """

    def __init__(self, pool, path, job, on_frame, on_done, parent=None,
                 timeout_ms: int = JOB_TIMEOUT_MS):
        super().__init__(parent)
        self._on_frame = on_frame
        self._on_done = on_done
        self._buf = bytearray()
        self.header = {}  # the worker's reply header: {"ok": ..., "count": N}
        self._header = None
        self._err = bytearray()
        self._done = False
        # Set by the worker's end-of-stream marker. Without it, a worker
        # that dies halfway looks exactly like one that finished.
        self._complete = False
        self._worker = pool.take()
        if self._worker is None:
            QTimer.singleShot(0, lambda: self._finish(False, "sandbox refused"))
            return

        try:
            fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
        except OSError as exc:
            self._worker.kill()
            self._worker = None
            QTimer.singleShot(0, lambda msg=str(exc): self._finish(False, msg))
            return

        sock = self._worker.sock
        self._notifier = QSocketNotifier(
            sock.fileno(), QSocketNotifier.Type.Read, self
        )
        self._notifier.activated.connect(self._readable)
        # stderr is drained by the Worker itself, from spawn time.
        # Inactivity watchdog, not a total budget: a 50-page PDF arrives over
        # several seconds, but each frame should come quickly.
        self._watchdog = QTimer(self)
        self._watchdog.setSingleShot(True)
        self._watchdog.timeout.connect(
            lambda: self._finish(False, "timed out")
        )
        self._timeout_ms = timeout_ms
        self._watchdog.start(timeout_ms)

        payload = json.dumps(job).encode()
        try:
            sock.sendmsg(
                [struct.pack(">I", len(payload))],
                [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [fd]))],
            )
            sock.sendall(payload)
        except OSError as exc:
            QTimer.singleShot(0, lambda msg=str(exc): self._finish(False, msg))
        finally:
            os.close(fd)  # the worker holds its own copy now

    # ------------------------------------------------------------ reading
    def _readable(self):
        if self._done:
            return
        try:
            chunk = self._worker.sock.recv(1 << 16)
        except OSError as exc:
            self._finish(False, str(exc))
            return
        if not chunk:  # worker exited
            if self._complete:
                self._finish(True)
            elif self._header is None:
                self._finish(False, "worker closed the socket")
            else:
                # Frames arrived but the end marker never did: the worker
                # died partway (a page it could not render, a kill). Saying
                # "ok" here is what let a PDF that stopped at page 7 of 50
                # be reported as a complete render.
                self._finish(False, "worker stopped before finishing")
            return
        self._watchdog.start(self._timeout_ms)
        self._buf += chunk
        while len(self._buf) >= 4:
            (n,) = struct.unpack(">I", self._buf[:4])
            if n > MAX_FRAME_BYTES:
                self._finish(False, f"absurd frame length {n}")
                return
            if len(self._buf) < 4 + n:
                return
            payload = bytes(self._buf[4:4 + n])
            del self._buf[:4 + n]
            if self._header is not None and n == 0:
                self._complete = True  # end-of-stream marker
                continue
            if self._header is None:
                try:
                    self._header = json.loads(payload)
                except ValueError:
                    self._finish(False, "malformed worker header")
                    return
                self.header = self._header
                if not self._header.get("ok"):
                    self._finish(False, self._header.get("error", "failed"))
                    return
                continue
            self._on_frame(payload)

    def _finish(self, ok: bool, error: str = ""):
        if self._done:
            return
        self._done = True
        self.cancel()
        if not ok and self._err:
            error = f"{error}: " + self._err.decode(
                "utf-8", errors="replace"
            ).strip()[:500]
        self._on_done(ok, error)
        # One job object per preview *and* per prefetch would otherwise pile
        # up as children of the window for the life of a daemon that runs
        # for weeks. Queued, so it outlives the callback above.
        self.deleteLater()

    def cancel(self):
        """Stop listening and kill the worker. Safe to call twice."""
        if self._done and self._worker is None:
            return  # already torn down; the C++ side may be gone with it
        self._done = True
        for attr in ("_notifier", "_watchdog"):
            obj = getattr(self, attr, None)
            if obj is not None:
                obj.setEnabled(False) if isinstance(
                    obj, QSocketNotifier
                ) else obj.stop()
        if self._worker is not None:
            self._err = self._worker.err  # collected since it was spawned
            self._worker.kill()
            self._worker = None
        # Also covers a job cancelled from outside, which never reaches
        # _finish. deleteLater() twice is harmless.
        self.deleteLater()
