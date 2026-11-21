# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Nicolas Vaughan <nicolasvaughan@proton.me>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""The Dolphin watch: when it runs, when it offers a restart, and the
restart itself, with stand-ins for the bus, the notification and Dolphin.
Nothing is sent on the real session bus, where a running watch would hear
it.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

# A full QApplication, though the watch needs only QtCore: the suite's
# other tests share this process, and they need widgets.
_app = QApplication.instance() or QApplication([sys.argv[0]])

import config  # noqa: E402
import dolphin_watch as dw  # noqa: E402


class Versions(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(dw.parse_version("dolphin 26.08.3"), (26, 8))
        self.assertEqual(dw.parse_version("dolphin 26.12.0\n"), (26, 12))
        self.assertIsNone(dw.parse_version("dolphin: cannot connect"))

    def test_only_an_affected_dolphin_is_watched(self):
        self.assertTrue(dw.needs_watching((26, 8))[0])
        self.assertFalse(dw.needs_watching((26, 12))[0])
        self.assertFalse(dw.needs_watching((27, 4))[0])
        self.assertFalse(dw.needs_watching("missing")[0])
        self.assertTrue(dw.needs_watching(None)[0], "unknown: better safe")


class Interface:
    """Stands in for QDBusInterface, recording the windows told to quit."""
    calls = []

    def __init__(self, service, path, interface, bus):
        self.target = (service, path, interface)

    def call(self, method):
        Interface.calls.append(self.target + (method,))


class Fake(dw.Watcher):
    def __init__(self, running=("org.kde.dolphin-42",)):
        self.running = list(running)
        self.asked = []
        self.launched = 0
        super().__init__(bus=None, notify=self.asked.append,
                         launch=self.count_launch)

    def count_launch(self):
        self.launched += 1

    def dolphins(self):
        return list(self.running)


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        saved = config.CONFIG_FILE
        config.CONFIG_FILE = os.path.join(tmp.name, "quickview.conf")
        self.addCleanup(setattr, config, "CONFIG_FILE", saved)
        os.environ.pop("QUICKVIEW_DOLPHIN_SPACE", None)
        Interface.calls = []
        for name, value in (("QDBusInterface", Interface),
                            ("window_paths", lambda bus, s: [f"/dolphin/Dolphin_1@{s}"])):
            saved_attr = getattr(dw, name)
            setattr(dw, name, value)
            self.addCleanup(setattr, dw, name, saved_attr)


class Offer(Base):
    def test_several_signals_make_one_notification(self):
        w = Fake()
        for _ in range(3):
            w.on_event(None)
        self.assertTrue(w.settle.isActive())
        w.settle.stop()
        w.fire()
        self.assertEqual(len(w.asked), 1)

    def test_a_loss_while_one_waits_renews_it(self):
        # Before 1.0.2 the watch went deaf while a notification waited,
        # as one does in Plasma's history after its popup fades.
        w = Fake()
        w.fire()
        w.fire()
        self.assertEqual(len(w.asked), 2)
        w.asked[0](True)  # the replaced one: its answer is ignored
        self.assertEqual((Interface.calls, w.notifying), ([], True))
        w.asked[1](True)
        self.assertEqual(len(Interface.calls), 1)
        self.assertFalse(w.notifying)
        w.poll.stop()

    def test_the_notification_is_critical_and_can_be_replaced(self):
        w = Fake()
        args = w.notify_args()
        self.assertIn("--urgency=critical", args)
        self.assertIn("--print-id", args)
        self.assertFalse(any(a.startswith("--replace-id") for a in args))
        self.assertIn("--replace-id=17", w.notify_args(17))
        self.assertEqual(args[-2:], [dw.SUMMARY, dw.BODY])

    def test_notify_send_output(self):
        self.assertEqual(dw.parse_notify_output("17\n"), (17, ""))
        self.assertEqual(dw.parse_notify_output("17\nrestart\n"), (17, "restart"))
        self.assertEqual(dw.parse_notify_output(""), (None, ""))
        self.assertEqual(dw.parse_notify_output("restart\n"), (None, "restart"))

    def test_no_notification_without_an_open_dolphin(self):
        w = Fake(running=())
        w.fire()
        self.assertEqual(w.asked, [])

    def test_no_notification_with_the_setting_off(self):
        with open(config.CONFIG_FILE, "w") as fh:
            fh.write("[dolphin]\ndolphin_space = false\n")
        w = Fake()
        w.fire()
        self.assertEqual(w.asked, [])

    def test_dismissed_nothing_happens_and_the_next_one_can_come(self):
        w = Fake()
        w.fire()
        w.asked[0](False)
        self.assertEqual((Interface.calls, w.launched), ([], 0))
        w.fire()
        self.assertEqual(len(w.asked), 2)


class Restart(Base):
    def test_every_window_closes_then_dolphin_starts(self):
        w = Fake(running=["org.kde.dolphin-1", "org.kde.dolphin-2"])
        w.fire()
        w.asked[0](True)
        self.assertEqual(Interface.calls, [
            ("org.kde.dolphin-1", "/dolphin/Dolphin_1@org.kde.dolphin-1",
             dw.WINDOW_INTERFACE, "quit"),
            ("org.kde.dolphin-2", "/dolphin/Dolphin_1@org.kde.dolphin-2",
             dw.WINDOW_INTERFACE, "quit"),
        ])
        w._check_closed()
        self.assertEqual(w.launched, 0, "not while one is still open")
        w.running = []
        w._check_closed()
        self.assertEqual(w.launched, 1)
        self.assertIsNone(w.closing)
        self.assertFalse(w.poll.isActive())

    def test_a_dolphin_that_stays_open_is_not_started_twice(self):
        w = Fake()
        w.fire()
        w.asked[0](True)
        w.waited = dw.CLOSE_WAIT_MS
        w._check_closed()
        self.assertEqual(w.launched, 0)
        self.assertIsNone(w.closing)

    def test_no_second_offer_while_restarting(self):
        w = Fake()
        w.fire()
        w.asked[0](True)
        w.fire()
        self.assertEqual(len(w.asked), 1)
        w.poll.stop()


if __name__ == "__main__":
    unittest.main()
