#!/usr/bin/env python3
# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Nicolas Vaughan <nicolasvaughan@proton.me>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Says so when Dolphin has dropped the Space shortcut, and offers to
restart it.

Dolphin 26.08 forgets service-menu shortcuts in its open windows whenever
it rebuilds its service-menu actions: when Configure Dolphin is applied
(on any page, changed or not) and when the context-menu settings
(kservicemenurc) change. dolphin_shortcut.py keeps the shortcut in
Dolphin's file, but nothing outside Dolphin can give it back to a window
already open: only a restart does. Dolphin 26.12 keeps the shortcuts
(commit d90c6f46), so with it this exits at once and watches nothing.

Both triggers are on the session bus: each Dolphin window broadcasts
org.kde.dolphin.MainWindow.settingsChanged when its settings are applied,
and KConfig broadcasts org.kde.kconfig.notify.ConfigChanged on
/kservicemenurc. On either, while QuickView's dolphin_space setting is
on, a notification offers "Restart Dolphin". That closes each window the
way its own close button would (Dolphin still asks before closing several
tabs) and, once Dolphin has gone, starts it again as Plasma would.

The notification is critical, so Plasma keeps it on screen until it is
answered. Another loss while it is still waiting (say Dolphin was
restarted by hand, then its settings applied again) replaces it with a
fresh one, rather than being ignored until the first is answered.

Run by quickview-dolphin-watch.service for the graphical session. QtCore
and QtDBus only, no widgets.
"""

import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

from PySide6.QtCore import QCoreApplication, QObject, QProcess, QTimer, Slot, SLOT
from PySide6.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage

# The first Dolphin that keeps the shortcuts across a refresh.
FIXED_IN = (26, 12)
SERVICE_PREFIX = "org.kde.dolphin-"
WINDOW_INTERFACE = "org.kde.dolphin.MainWindow"
# One event can arrive several times (every window, every write): one
# notification for them all.
SETTLE_MS = 1500
# How long a restart waits for Dolphin to close: a window may be asking
# whether to close its tabs.
CLOSE_WAIT_MS = 60_000
CLOSE_POLL_MS = 500

SUMMARY = "Space no longer opens Quick Look in Dolphin"
BODY = ("Dolphin 26.08 forgets service-menu shortcuts when its settings are "
        "applied, until it is restarted. Restarting Dolphin brings Space "
        "back; the Dolphin windows open now will close.")


def parse_notify_output(text: str):
    """(notification id or None, chosen action or "") from what
    `notify-send --print-id --action=...` prints: the id on the first line,
    then the action's name, if one is chosen."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not lines or not lines[0].isdigit():
        return None, lines[-1] if lines else ""
    return int(lines[0]), lines[1] if len(lines) > 1 else ""


def log(text: str):
    print(f"quickview: Dolphin watch: {text}", flush=True)


def parse_version(text: str):
    """(major, minor) from `dolphin --version`, or None."""
    match = re.search(r"(\d+)\.(\d+)(?:\.\d+)?", text or "")
    return (int(match.group(1)), int(match.group(2))) if match else None


def dolphin_version():
    """(major, minor); None when it cannot be told; "missing" without
    Dolphin."""
    if shutil.which("dolphin") is None:
        return "missing"
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    try:
        out = subprocess.run(["dolphin", "--version"], capture_output=True,
                             text=True, timeout=20, env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_version(out.stdout + out.stderr)


def needs_watching(version) -> tuple:
    """(whether to watch, why) for a dolphin_version() answer."""
    if version == "missing":
        return False, "Dolphin is not installed"
    if version is None:
        return True, "Dolphin's version is unknown; watching to be safe"
    if version >= FIXED_IN:
        return False, (f"Dolphin {version[0]}.{version[1]:02d} keeps its "
                       "shortcuts; nothing to watch")
    return True, f"Dolphin {version[0]}.{version[1]:02d} drops its shortcuts"


def setting_on() -> bool:
    """QuickView's dolphin_space setting, read afresh; on when unreadable."""
    try:
        import config
        return bool(config.load(config.CONFIG_FILE).get("dolphin_space", True))
    except Exception:  # noqa: BLE001 — a broken config must not stop this
        return True


def window_paths(bus, service: str) -> list:
    """The object paths of a Dolphin process's main windows."""
    reply = bus.call(QDBusMessage.createMethodCall(
        service, "/dolphin", "org.freedesktop.DBus.Introspectable", "Introspect"))
    if reply.type() != QDBusMessage.MessageType.ReplyMessage or not reply.arguments():
        return []
    try:
        root = ET.fromstring(reply.arguments()[0])
    except ET.ParseError:
        return []
    return [f"/dolphin/{node.get('name')}" for node in root.findall("node")
            if (node.get("name") or "").startswith("Dolphin_")]


class Watcher(QObject):
    """Listens on the bus, notifies, and restarts Dolphin when asked.

    notify(callback) shows the notification and calls callback(True) when
    "Restart Dolphin" is chosen; launch() starts Dolphin. Both can be
    replaced, for the tests.
    """

    def __init__(self, bus, notify=None, launch=None, parent=None):
        super().__init__(parent)
        self.bus = bus
        self.notify = notify or self._notify
        self.launch = launch or self._launch
        self.notifying = False
        self.generation = 0   # which notification an answer belongs to
        self._proc = None     # the notify-send waiting for an answer
        self._note_id = None  # its notification's id, to replace it
        self.settle = QTimer(self)
        self.settle.setSingleShot(True)
        self.settle.setInterval(SETTLE_MS)
        self.settle.timeout.connect(self.fire)
        self.closing = None   # services being waited for, during a restart
        self.waited = 0
        self.poll = QTimer(self)
        self.poll.setInterval(CLOSE_POLL_MS)
        self.poll.timeout.connect(self._check_closed)

    def listen(self) -> bool:
        ok = self.bus.connect("", "", WINDOW_INTERFACE, "settingsChanged",
                              self, SLOT("on_event(QDBusMessage)"))
        ok &= self.bus.connect("", "/kservicemenurc", "org.kde.kconfig.notify",
                               "ConfigChanged", self, SLOT("on_event(QDBusMessage)"))
        return ok

    # ----------------------------------------------------------- events
    @Slot(QDBusMessage)
    def on_event(self, message):
        self.settle.start()

    def dolphins(self) -> list:
        names = self.bus.interface().registeredServiceNames().value() or []
        return sorted(n for n in names if n.startswith(SERVICE_PREFIX))

    def fire(self):
        if not setting_on():
            log("Dolphin dropped its shortcuts, but dolphin_space is off")
            return
        if not self.dolphins():
            return  # nothing open has lost anything
        if self.closing is not None:
            return  # the restart under way brings the shortcut back
        if self.notifying:
            log("Dolphin dropped its shortcuts again; renewing the notification")
        else:
            log("Dolphin dropped its shortcuts; offering a restart")
        self.notifying = True
        self.generation += 1
        generation = self.generation

        def chosen(restart: bool):
            if generation != self.generation:
                return  # a later notification replaced this one
            self.notifying = False
            if restart:
                self.restart()

        self.notify(chosen)

    # ---------------------------------------------------------- restart
    def restart(self):
        services = self.dolphins()
        if not services:
            self.launch()
            return
        for service in services:
            for path in window_paths(self.bus, service):
                QDBusInterface(service, path, WINDOW_INTERFACE, self.bus).call("quit")
        self.closing, self.waited = services, 0
        self.poll.start()

    def _check_closed(self):
        self.waited += CLOSE_POLL_MS
        left = set(self.closing) & set(self.dolphins())
        if not left:
            self.poll.stop()
            self.closing = None
            log("Dolphin closed; starting it again")
            self.launch()
        elif self.waited >= CLOSE_WAIT_MS:
            self.poll.stop()
            self.closing = None
            log("Dolphin did not close (a window may have kept its tabs); "
                "not restarted")

    # ------------------------------------------------------ the desktop
    def notify_args(self, replace_id=None) -> list:
        args = ["--app-name=QuickView", "--icon=document-preview",
                "--urgency=critical", "--print-id",
                "--action=restart=Restart Dolphin"]
        if replace_id is not None:
            args.append(f"--replace-id={replace_id}")
        return args + [SUMMARY, BODY]

    def _notify(self, chosen):
        old = self._proc
        proc = QProcess(self)
        proc.setProgram("notify-send")
        proc.setArguments(self.notify_args(self._note_id if old else None))
        self._proc = proc
        output = []

        def read():
            output.append(bytes(proc.readAllStandardOutput()).decode(errors="replace"))
            note_id, _ = parse_notify_output("".join(output))
            if proc is self._proc and note_id is not None:
                self._note_id = note_id

        def finished(*_args):
            read()
            proc.deleteLater()
            if proc is not self._proc:
                return  # replaced, and killed on purpose
            self._proc = self._note_id = None
            chosen(parse_notify_output("".join(output))[1] == "restart")

        def failed(*_args):
            if proc is self._proc:
                log("notify-send failed")
                self._proc = self._note_id = None
                chosen(False)

        proc.readyReadStandardOutput.connect(read)
        proc.finished.connect(finished)
        proc.errorOccurred.connect(failed)
        proc.start()
        if old is not None:
            # SIGKILL, so that the old notify-send cannot close, on its
            # way out, the notification the new one has just taken over.
            old.kill()

    @staticmethod
    def _launch():
        # In an app unit of its own, as Plasma starts it: started straight
        # from here, it would belong to this service, and go when it does.
        if shutil.which("kstart"):
            QProcess.startDetached("kstart", ["--application", "org.kde.dolphin"])
        else:
            QProcess.startDetached("systemd-run", ["--user", "--scope", "--quiet",
                                                   "--collect", "dolphin"])


def main() -> int:
    watch, why = needs_watching(dolphin_version())
    log(why)
    if not watch:
        return 0
    app = QCoreApplication(sys.argv[:1])
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        log("no session bus")
        return 1
    watcher = Watcher(bus)
    if not watcher.listen():
        log("could not subscribe to Dolphin's signals")
        return 1
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
