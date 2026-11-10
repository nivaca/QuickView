# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Mustapha Alioglou
# Copyright (C) 2026 Nicolas Vaughan <nivaca@fastmail.com>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""The worker's side of the wire protocol, without a jail.

serve() is driven over a socketpair with the file passed as a descriptor,
exactly as the daemon passes it, so these check what the daemon relies on:
a header, the frames, and the end-of-stream marker only when everything
got through.
"""

import array
import glob
import json
import os
import re
import socket
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([sys.argv[0]])

import worker  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def frames(sock):
    """Every length-prefixed frame until the peer closes."""
    buf = b""
    while True:
        chunk = sock.recv(1 << 16)
        if not chunk:
            break
        buf += chunk
    out = []
    while len(buf) >= 4:
        (size,) = struct.unpack(">I", buf[:4])
        out.append(buf[4:4 + size])
        buf = buf[4 + size:]
    return out


class Serve(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def request(self, job, data=b"", name="f"):
        """Run one job through serve(); (exit code, frames received)."""
        path = os.path.join(self.tmp.name, name)
        with open(path, "wb") as fh:
            fh.write(data)
        daemon, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        fd = os.open(path, os.O_RDONLY)
        try:
            payload = json.dumps(job).encode()
            daemon.sendmsg([struct.pack(">I", len(payload))],
                           [(socket.SOL_SOCKET, socket.SCM_RIGHTS,
                             array.array("i", [fd]))])
            daemon.sendall(payload)
            code = worker.serve(child)  # closes child
            return code, frames(daemon)
        finally:
            os.close(fd)
            daemon.close()

    def test_a_text_job_is_a_header_a_document_and_the_marker(self):
        code, out = self.request(
            {"op": "text", "name": "a.py", "limit": 1 << 20},
            b"print('hi')\n", "a.py")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out[0]), {"ok": True, "count": 1})
        self.assertIn("print", json.loads(out[1])["text"])
        self.assertEqual(out[-1], b"", "end-of-stream marker")
        self.assertEqual(len(out), 3)

    def test_a_prefetch_image_gets_only_the_cache_copy(self):
        img = QImage(8, 6, QImage.Format_RGB32)
        img.fill(QColor("red"))
        path = os.path.join(self.tmp.name, "src.png")
        img.save(path)
        with open(path, "rb") as fh:
            png = fh.read()
        code, out = self.request(
            {"op": "image", "max_w": 100, "max_h": 100, "raw": False}, png)
        self.assertEqual(code, 0)
        head = json.loads(out[0])
        self.assertEqual((head["ok"], head["count"], head["orig"]),
                         (True, 1, "8×6"))
        self.assertFalse(QImage.fromData(out[1]).isNull())
        self.assertEqual(out[2:], [b""])

    def test_an_unknown_op_is_refused_before_any_header(self):
        code, out = self.request({"op": "format-c"})
        self.assertEqual(code, 1)
        self.assertEqual(len(out), 1, "no marker after a refusal")
        reply = json.loads(out[0])
        self.assertFalse(reply["ok"])
        self.assertIn("unknown op", reply["error"])

    def test_a_failure_after_the_header_leaves_out_the_marker(self):
        # Once the header is out, {"ok": false} would be read as a frame;
        # the missing marker is the only way to say "truncated".
        def half(job, src, fd, out):
            out.header(2)
            out.frame(b"page one")
            raise RuntimeError("page two is hostile")

        saved = worker.OPS.copy()
        self.addCleanup(lambda: (worker.OPS.clear(), worker.OPS.update(saved)))
        worker.OPS["half"] = half
        code, out = self.request({"op": "half"})
        self.assertEqual(code, 1)
        self.assertEqual(out, [json.dumps({"ok": True, "count": 2}).encode(),
                               b"page one"])

    def test_every_op_the_daemon_sends_has_a_handler(self):
        sent = set()
        for path in glob.glob(os.path.join(ROOT, "*.py")):
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            sent |= set(re.findall(r'"op":\s*"(\w+)"', text))
            sent |= set(re.findall(r'\bop="(\w+)"', text))
            sent |= set(re.findall(r'\bop: str = "(\w+)"', text))
            for table in re.findall(r"_find_op = (\{[^}]*\})", text):
                sent |= set(re.findall(r'"(\w+)"', table))
        sent.discard("media")  # the media worker's, not this one's
        self.assertTrue(sent, "found no ops — the pattern needs updating")
        self.assertEqual(sent - set(worker.OPS), set())


if __name__ == "__main__":
    unittest.main()
