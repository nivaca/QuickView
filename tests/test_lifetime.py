# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Mustapha Alioglou
# Copyright (C) 2026 Nicolas Vaughan <nivaca@fastmail.com>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""The daemon starts on demand and exits when daemon_mode says.

The socket half plays systemd's part with a real listening socket in a
temporary directory; the lifetime half records exits instead of quitting.
"""

import os
import socket
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([sys.argv[0]])

import common  # noqa: E402
import quickview  # noqa: E402


def spin(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class SystemdSocket(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "sock")
        # What systemd does before starting the service: bind and listen.
        self.bound = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.bound.bind(self.path)
        self.bound.listen(8)
        self.addCleanup(self.bound.close)

    def env(self, pid=None, fds="1"):
        return {"LISTEN_PID": str(pid or os.getpid()), "LISTEN_FDS": fds,
                "LISTEN_FDNAMES": "quickview.socket", "HOME": "/home/x"}

    def adopt(self, environ):
        # A duplicate stands in for descriptor 3, and for the copy systemd
        # keeps open itself.
        return quickview.systemd_listener(environ, fd=os.dup(self.bound.fileno()))

    def test_a_socket_meant_for_this_process_is_adopted(self):
        environ = self.env()
        sock = self.adopt(environ)
        self.assertIsNotNone(sock)
        self.addCleanup(sock.close)
        self.assertEqual(environ, {"HOME": "/home/x"},
                         "nothing started from here inherits the variables")
        self.assertFalse(os.get_inheritable(sock.fileno()))

    def test_one_meant_for_another_process_is_not(self):
        self.assertIsNone(quickview.systemd_listener(self.env(pid=1)))

    def test_no_descriptors_means_none(self):
        self.assertIsNone(quickview.systemd_listener(self.env(fds="0")))

    def test_a_descriptor_that_is_not_a_unix_stream_is_left_alone(self):
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addCleanup(udp.close)
        self.assertIsNone(quickview.systemd_listener(self.env(), fd=udp.fileno()))
        udp.getsockname()  # still open: not ours to close

    def test_requests_arrive_and_the_socket_outlives_the_daemon(self):
        # A Space press made before the daemon was up is queued, not lost.
        early = socket.socket(socket.AF_UNIX)
        early.connect(self.path)
        early.sendall(b"/a/file\0")
        early.close()

        listener = self.adopt(self.env())
        got = []

        def handle(conn):
            conn.disconnected.connect(lambda: got.append(bytes(conn.readAll())))

        notifier = quickview.accept_from(listener, handle, _app)
        end = time.monotonic() + 2
        while not got and time.monotonic() < end:
            spin(20)
        self.assertEqual(got, [b"/a/file\0"])

        # The daemon exits: its copy closes, the path must stay reachable.
        notifier.setEnabled(False)
        listener.close()
        self.assertTrue(os.path.exists(self.path))
        later = socket.socket(socket.AF_UNIX)
        later.connect(self.path)  # queued for the next start
        later.close()


class Lifetime(unittest.TestCase):
    def setUp(self):
        saved = dict(common.SETTINGS)
        self.addCleanup(lambda: (common.SETTINGS.clear(),
                                 common.SETTINGS.update(saved)))
        self.exits = []
        self.window = quickview.QuickView()
        self.addCleanup(self.window.deleteLater)

    def manage(self, mode, minutes=10):
        common.SETTINGS["daemon_mode"] = mode
        common.SETTINGS["idle_minutes"] = minutes
        self.window.manage_lifetime(lambda: self.exits.append(mode))

    def preview_then_close(self):
        self.window.show_file("/nonexistent/quickview-test.txt")
        self.window.dismiss("test")

    def test_off_exits_as_soon_as_the_preview_closes(self):
        self.manage("off")
        self.exits.clear()  # starting with no preview counts as idle too
        self.preview_then_close()
        spin(50)
        self.assertEqual(self.exits, ["off"])

    def test_resident_never_exits(self):
        self.manage("resident")
        self.preview_then_close()
        spin(50)
        self.assertEqual(self.exits, [])
        self.assertFalse(self.window._idle_exit.isActive())

    def test_on_demand_counts_down_idle_minutes(self):
        self.manage("on-demand", minutes=7)
        self.preview_then_close()
        timer = self.window._idle_exit
        self.assertTrue(timer.isActive())
        self.assertEqual(timer.interval(), 7 * 60_000)

    def test_a_preview_stops_the_countdown(self):
        self.manage("on-demand")
        self.assertTrue(self.window._idle_exit.isActive(), "idle from the start")
        self.window.show_file("/nonexistent/quickview-test.txt")
        self.assertFalse(self.window._idle_exit.isActive())

    def test_an_open_preview_is_never_cut_short(self):
        self.manage("on-demand", minutes=1)
        self.window.show_file("/nonexistent/quickview-test.txt")
        self.window._exit_if_idle()  # as if the timer had fired late
        self.assertEqual(self.exits, [])

    def test_changing_the_mode_applies_while_idle(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        conf = os.path.join(tmp.name, "quickview.conf")
        with open(conf, "w") as fh:
            fh.write("[daemon]\ndaemon_mode = resident\n")
        self.window.watch_settings(conf)
        self.window.manage_lifetime(lambda: self.exits.append("exit"))
        self.assertFalse(self.window._idle_exit.isActive())
        with open(conf, "w") as fh:
            fh.write("[daemon]\ndaemon_mode = on-demand\nidle_minutes = 3\n")
        self.window.reload_settings()
        self.assertTrue(self.window._idle_exit.isActive())
        self.assertEqual(self.window._idle_exit.interval(), 3 * 60_000)

    def test_a_window_not_managed_never_exits(self):
        # Every other test's window dismisses freely: it must not quit the
        # application they all share.
        common.SETTINGS["daemon_mode"] = "off"
        other = quickview.QuickView()
        self.addCleanup(other.deleteLater)
        other.dismiss("test")
        self.assertIsNone(getattr(other, "_idle_exit", None))


if __name__ == "__main__":
    unittest.main()
