# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Nicolas Vaughan <nivaca@fastmail.com>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""The packaged launcher starts systemd's socket on first use.

The real template, rendered as the spec renders it, run against stand-ins:
a client that answers only once "the socket is up", a systemctl that logs
what it is asked and answers as told, and a quickview.py that records that
Python was reached. Nothing here touches the user's systemd.
"""

import os
import stat
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CLIENT = """#!/bin/sh
for a in "$@"; do case "$a" in -*) exit 1;; esac; done
[ -e "$STATE/up" ] && echo "client $*" >> "$STATE/log" && exit 0
exit 1
"""
SYSTEMCTL = """#!/bin/sh
echo "systemctl $*" >> "$STATE/log"
case "$*" in
    *is-enabled*) [ "$ENABLED" = 1 ];;
    *is-active*) [ -e "$STATE/up" ];;
    *daemon-reload*) : > "$STATE/reloaded";;
    *start*)
        if [ "$START" = ok ] || { [ "$START" = after-reload ] && [ -e "$STATE/reloaded" ]; }; then
            : > "$STATE/up"
        else
            exit 1
        fi;;
esac
"""
PYTHON_STUB = 'import sys, os\nopen(os.environ["STATE"] + "/log", "a").write("python " + " ".join(sys.argv[1:]) + "\\n")\n'


def executable(path, text):
    with open(path, "w") as fh:
        fh.write(text)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)


class FirstUse(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        self.state = os.path.join(self.dir, "state")
        self.bin = os.path.join(self.dir, "bin")
        os.makedirs(self.state)
        os.makedirs(self.bin)
        executable(os.path.join(self.dir, "quickview-client"), CLIENT)
        executable(os.path.join(self.bin, "systemctl"), SYSTEMCTL)
        with open(os.path.join(self.dir, "quickview.py"), "w") as fh:
            fh.write(PYTHON_STUB)
        with open(os.path.join(ROOT, "packaging", "quickview-launcher.in")) as fh:
            text = (fh.read().replace("@LIBEXECDIR@", self.dir)
                    .replace("@DATADIR@", self.dir))
        self.launcher = os.path.join(self.dir, "quickview")
        executable(self.launcher, text)

    def run_launcher(self, *args, enabled=True, start="ok", up=False,
                     systemd=True):
        if up:
            open(os.path.join(self.state, "up"), "w").close()
        env = {"STATE": self.state, "ENABLED": "1" if enabled else "0",
               "START": start,
               # No systemctl at all: a PATH holding only the stand-ins'
               # folder without it.
               "PATH": self.bin if systemd else self.state}
        code = subprocess.run([self.launcher, *args], env=env).returncode
        with open(os.path.join(self.state, "log")) as fh:
            return code, fh.read().splitlines()

    def test_a_running_daemon_is_simply_handed_the_file(self):
        code, log = self.run_launcher("/a.pdf", up=True)
        self.assertEqual((code, log), (0, ["client /a.pdf"]))

    def test_first_use_after_install_starts_the_socket(self):
        code, log = self.run_launcher("/a.pdf")
        self.assertEqual(code, 0)
        self.assertEqual(log, [
            "systemctl --user -q is-enabled quickview.socket",
            "systemctl --user -q is-active quickview.socket",
            "systemctl --user start quickview.socket",
            "client /a.pdf",  # delivered to the daemon the socket starts
        ])

    def test_unit_files_the_manager_has_not_read_get_one_reload(self):
        code, log = self.run_launcher("/a.pdf", start="after-reload")
        self.assertEqual(code, 0)
        self.assertIn("systemctl --user daemon-reload", log)
        self.assertEqual(log[-1], "client /a.pdf")

    def test_a_disabled_socket_is_left_alone(self):
        code, log = self.run_launcher("/a.pdf", enabled=False)
        self.assertNotIn("systemctl --user start quickview.socket", log)
        self.assertEqual(log[-1], "python /a.pdf")

    def test_a_listening_socket_is_not_restarted(self):
        # Listening, but the client failed anyway: not ours to fix here.
        os.remove(os.path.join(self.dir, "quickview-client"))
        executable(os.path.join(self.dir, "quickview-client"), "#!/bin/sh\nexit 1\n")
        code, log = self.run_launcher("/a.pdf", up=True)
        self.assertNotIn("systemctl --user start quickview.socket", log)
        self.assertEqual(log[-1], "python /a.pdf")

    def test_a_flag_never_touches_systemd(self):
        code, log = self.run_launcher("--settings")
        self.assertEqual(log, ["python --settings"])

    def test_a_failed_start_falls_back_to_python(self):
        code, log = self.run_launcher("/a.pdf", start="never")
        self.assertEqual(log[-1], "python /a.pdf")

    def test_without_systemd_python_takes_over(self):
        code, log = self.run_launcher("/a.pdf", systemd=False)
        self.assertEqual(log, ["python /a.pdf"])


if __name__ == "__main__":
    unittest.main()
