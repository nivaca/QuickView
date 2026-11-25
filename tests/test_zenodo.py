# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Nicolas Vaughan <nicolasvaughan@proton.me>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Pruebas de tools/zenodo.py: el depósito de una versión en dist/zenodo/ (el árbol de la etiqueta, los paquetes
con sus firmas, SHA256SUMS firmado, la clave pública) y su subida como borrador, contra un Zenodo de mentira que
corre aquí. Firman con una clave hecha para la prueba, en un GNUPGHOME temporal: nunca la del usuario."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TOOL = Path(__file__).resolve().parent.parent / "tools" / "zenodo.py"
HAVE_TOOLS = all(shutil.which(t) for t in ("gpg", "gpgconf", "git")) and sys.platform != "win32"


def gpg_home(name: str) -> Path:
    # Bajo /tmp: el socket de gpg-agent no cabe en una ruta larga
    home = Path(tempfile.mkdtemp(prefix=f"zenodo-test-{name}-", dir="/tmp" if os.path.isdir("/tmp") else None))
    home.chmod(0o700)
    return home


def make_key(home: Path, name: str) -> tuple[str, bytes]:
    """A key without a passphrase in HOME: its fingerprint and its public key, exported."""
    env = dict(os.environ, GNUPGHOME=str(home))
    subprocess.run(["gpg", "--batch", "--passphrase", "", "--quick-gen-key", f"{name} <{name}@example.org>",
                    "ed25519", "sign", "never"], env=env, check=True, capture_output=True)
    out = subprocess.run(["gpg", "--batch", "--with-colons", "--list-secret-keys"], env=env, check=True,
                         capture_output=True, text=True).stdout
    fpr = next(line.split(":")[9] for line in out.splitlines() if line.startswith("fpr"))
    public = subprocess.run(["gpg", "--batch", "--armor", "--export", fpr], env=env, check=True,
                            capture_output=True).stdout
    return fpr, public


def kill_agents(home: Path) -> None:
    subprocess.run(["gpgconf", "--kill", "all"], env=dict(os.environ, GNUPGHOME=str(home)), capture_output=True,
                   check=False)
    shutil.rmtree(home, ignore_errors=True)


class FakeZenodo(BaseHTTPRequestHandler):
    """The deposit API, as much as tools/zenodo.py uses it, in memory. server.state has the depositions, the files
    of each bucket and the calls made."""

    def log_message(self, *args):
        pass

    def reply(self, code: int, body=None):
        data = json.dumps(body).encode() if body is not None else b""
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def deposition(self, d: dict) -> dict:
        base = f"http://127.0.0.1:{self.server.server_port}"
        return dict(d, links={"html": f"{base}/uploads/{d['id']}", "bucket": f"{base}/files/b{d['id']}",
                              "latest_draft": f"{base}/api/deposit/depositions/{d.get('draft', d['id'])}"})

    def handle_call(self, method: str):
        state = self.server.state
        state["calls"].append((method, self.path))
        if self.headers.get("Authorization") != "Bearer secret":
            return self.reply(403, {"message": "no token"})
        size = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(size) if size else b""
        path = self.path.split("?")[0]
        deps = state["depositions"]
        if method == "GET" and path == "/api/deposit/depositions":
            return self.reply(200, [self.deposition(d) for d in deps.values()])
        if method == "POST" and path == "/api/deposit/depositions":
            new = {"id": max(deps, default=100) + 1, "submitted": False, "metadata": {}, "files": [],
                   "conceptrecid": "c-new"}
            deps[new["id"]] = new
            return self.reply(201, self.deposition(new))
        parts = path.strip("/").split("/")
        if parts[:3] == ["api", "deposit", "depositions"] and len(parts) >= 4:
            d = deps[int(parts[3])]
            if method == "GET" and len(parts) == 4:
                return self.reply(200, self.deposition(d))
            if method == "PUT" and len(parts) == 4:
                d["metadata"] = json.loads(body)["metadata"]
                return self.reply(200, self.deposition(d))
            if method == "POST" and parts[4:] == ["actions", "newversion"]:
                new = {"id": max(deps) + 1, "submitted": False, "metadata": dict(d["metadata"]),
                       "files": [{"id": "old-file", "filename": "old.tar.gz"}], "conceptrecid": d["conceptrecid"]}
                deps[new["id"]] = new
                return self.reply(201, dict(self.deposition(d), links=self.deposition(dict(d, draft=new["id"]))["links"]))
            if method == "DELETE" and parts[4] == "files":
                d["files"] = [f for f in d["files"] if f["id"] != parts[5]]
                return self.reply(204)
            if method == "POST" and parts[4:5] == ["actions"]:
                state["published"] = True
                return self.reply(202, self.deposition(d))
        if method == "PUT" and parts[0] == "files":
            d = deps[int(parts[1][1:])]
            d["files"].append({"id": parts[2], "filename": parts[2]})
            state["uploaded"].setdefault(d["id"], {})[parts[2]] = body
            return self.reply(201, {"checksum": f"md5:{hashlib.md5(body).hexdigest()}"})
        return self.reply(404, {"message": f"unknown {method} {path}"})

    def do_GET(self):
        self.handle_call("GET")

    def do_POST(self):
        self.handle_call("POST")

    def do_PUT(self):
        self.handle_call("PUT")

    def do_DELETE(self):
        self.handle_call("DELETE")


@unittest.skipUnless(HAVE_TOOLS, "needs gpg and git")
class ZenodoTest(unittest.TestCase):
    """A project of mentira, with the tool copied into it, a signed tag and the files of a release in dist/."""

    @classmethod
    def setUpClass(cls):
        cls.home = gpg_home("release")
        cls.fpr, cls.public = make_key(cls.home, "release")

    @classmethod
    def tearDownClass(cls):
        kill_agents(cls.home)

    def setUp(self):
        self.env_before = dict(os.environ)
        os.environ.update(GNUPGHOME=str(self.home), SIGNING_KEY=self.fpr, GIT_CONFIG_GLOBAL=os.devnull,
                          GIT_CONFIG_NOSYSTEM="1")
        self.root = Path(tempfile.mkdtemp(prefix="zenodo-project-"))
        (self.root / "tools").mkdir()
        shutil.copy2(TOOL, self.root / "tools" / "zenodo.py")
        (self.root / "packaging").mkdir()
        (self.root / "packaging" / "RPM-GPG-KEY-demo").write_bytes(self.public)
        (self.root / "README.md").write_text("demo\n")
        (self.root / ".zenodo.json").write_text(json.dumps({"title": "demo", "upload_type": "software",
                                                             "creators": [{"name": "Vaughan, Nicolas"}]}))
        self.git("init", "--quiet", "--initial-branch=main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.org")
        self.git("remote", "add", "origin", "git@codeberg.org:someone/demo.git")
        self.git("remote", "set-url", "--add", "--push", "origin", "git@codeberg.org:someone/demo.git")
        self.git("remote", "set-url", "--add", "--push", "origin", "git@github.com:someone/demo.git")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "first")
        self.git("tag", "--sign", "--local-user", self.fpr, "-m", "demo 1.0", "v1.0")
        # Un cambio después de la etiqueta, que no debe entrar en el depósito
        (self.root / "README.md").write_text("demo, later\n")
        self.git("commit", "--quiet", "-am", "later")
        self.tool = self.load()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env_before)
        shutil.rmtree(self.root, ignore_errors=True)

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True)

    def load(self):
        spec = importlib.util.spec_from_file_location(f"zenodo_{id(self)}", self.root / "tools" / "zenodo.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def release_files(self):
        """dist/ as the release leaves it: two files signed, one (the .deb) whose signature is not there, and the
        RPM in dist/ with its signature beside the copy in build/rpm/."""
        dist, rpms = self.root / "dist", self.root / "build" / "rpm" / "RPMS"
        dist.mkdir()
        rpms.mkdir(parents=True)
        files = {"demo-1.0.zip": b"zip", "demo-1.0-x86_64.AppImage": b"appimage", "demo_1.0_all.deb": b"deb",
                 "demo-1.0-1.noarch.rpm": b"rpm"}
        for name, data in files.items():
            (dist / name).write_bytes(data)
        shutil.copy2(dist / "demo-1.0-1.noarch.rpm", rpms / "demo-1.0-1.noarch.rpm")
        for path in (dist / "demo-1.0.zip", dist / "demo-1.0-x86_64.AppImage", rpms / "demo-1.0-1.noarch.rpm"):
            self.tool.sign(path, self.fpr)
        (dist / "SHA256SUMS").write_text("".join(f"{hashlib.sha256(d).hexdigest()}  {n}\n" for n, d in files.items()))
        return files

    # -------------------------------------------------------------- collect

    def test_collect_the_tagged_tree_signed(self):
        names = [p.name for p in self.tool.collect(None, packages=False)]
        self.assertEqual(names, ["demo-1.0-source.tar.gz", "demo-1.0-source.tar.gz.asc", "SHA256SUMS",
                                 "SHA256SUMS.asc", "RPM-GPG-KEY-demo"])
        with tarfile.open(self.tool.OUT / "demo-1.0-source.tar.gz") as tar:
            self.assertEqual(tar.extractfile("demo-1.0/README.md").read(), b"demo\n")
        version, _files = self.tool.check_deposit()
        self.assertEqual(version, "1.0")

    def test_collect_with_packages(self):
        files = self.release_files()
        names = {p.name for p in self.tool.collect("v1.0", packages=True)}
        for name in files:
            self.assertIn(name, names)
            self.assertIn(f"{name}.asc", names)  # (the .deb's, made now; the RPM's, from build/rpm/)
        sums = self.tool.read_sums(self.tool.OUT / "SHA256SUMS")
        self.assertEqual(set(sums), set(files) | {"demo-1.0-source.tar.gz"})
        self.tool.check_deposit()

    def test_a_changed_package_stops_collect(self):
        self.release_files()
        (self.root / "dist" / "demo-1.0.zip").write_bytes(b"zip, changed")
        with self.assertRaisesRegex(self.tool.Failed, "demo-1.0.zip"):
            self.tool.collect("v1.0", packages=True)
        self.assertFalse(self.tool.OUT.exists())

    def test_tag_signed_by_another_key_stops_collect(self):
        other = gpg_home("other")
        try:
            other_fpr, _public = make_key(other, "other")
            os.environ["GNUPGHOME"] = str(other)
            self.git("tag", "--sign", "--local-user", other_fpr, "-m", "demo 2.0", "v2.0")
            os.environ["GNUPGHOME"] = str(self.home)
            with self.assertRaisesRegex(self.tool.Failed, "not signed with"):
                self.tool.collect("v2.0", packages=False)
            self.assertFalse(self.tool.OUT.exists())
        finally:
            kill_agents(other)

    def test_a_change_after_collect_is_found(self):
        self.tool.collect(None, packages=False)
        with (self.tool.OUT / "demo-1.0-source.tar.gz").open("ab") as f:
            f.write(b"x")
        with self.assertRaisesRegex(self.tool.Failed, "changed after collect"):
            self.tool.check_deposit()
        (self.tool.OUT / "stray.txt").write_text("x")
        with self.assertRaisesRegex(self.tool.Failed, "extra"):
            self.tool.check_deposit()

    # -------------------------------------------------------------- upload

    def serve(self, depositions: dict):
        server = ThreadingHTTPServer(("127.0.0.1", 0), FakeZenodo)
        server.state = {"depositions": depositions, "calls": [], "uploaded": {}, "published": False}
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        self.tool.SERVERS[True] = (f"http://127.0.0.1:{server.server_port}", "ZENODO_SANDBOX_TOKEN")
        os.environ["ZENODO_SANDBOX_TOKEN"] = "secret"
        return server.state

    def test_metadata(self):
        data = self.tool.metadata("1.0")
        self.assertEqual(data["version"], "1.0")
        self.assertRegex(data["publication_date"], r"^\d{4}-\d\d-\d\d$")
        self.assertEqual([r["identifier"] for r in data["related_identifiers"]],
                         ["https://codeberg.org/someone/demo/src/tag/v1.0", "https://github.com/someone/demo/tree/v1.0"])

    def test_first_upload_makes_a_new_draft(self):
        self.tool.collect(None, packages=False)
        state = self.serve({})
        url = self.tool.upload(sandbox=True, new_version_of=None, dry_run=False)
        (draft,) = state["depositions"].values()
        self.assertTrue(url.endswith(f"/uploads/{draft['id']}"))
        self.assertFalse(draft["submitted"])
        self.assertFalse(state["published"])
        uploaded = state["uploaded"][draft["id"]]
        self.assertEqual(set(uploaded), {p.name for p in self.tool.deposit_files()})
        self.assertEqual(uploaded["demo-1.0-source.tar.gz"], (self.tool.OUT / "demo-1.0-source.tar.gz").read_bytes())
        self.assertEqual(draft["metadata"]["version"], "1.0")

    def test_next_upload_is_a_new_version_without_the_old_files(self):
        self.tool.collect(None, packages=False)
        state = self.serve({7: {"id": 7, "submitted": True, "metadata": {"title": "demo"}, "files": [],
                                "conceptrecid": "c7"}})
        self.tool.upload(sandbox=True, new_version_of=None, dry_run=False)
        draft = state["depositions"][8]
        self.assertEqual(draft["conceptrecid"], "c7")
        self.assertNotIn("old-file", [f["id"] for f in draft["files"]])
        self.assertIn(("POST", "/api/deposit/depositions/7/actions/newversion"), state["calls"])
        self.assertFalse(state["published"])

    def test_a_waiting_draft_stops_upload(self):
        self.tool.collect(None, packages=False)
        state = self.serve({7: {"id": 7, "submitted": False, "metadata": {"title": "demo"}, "files": [],
                                "conceptrecid": "c7"}})
        with self.assertRaisesRegex(self.tool.Failed, "already a draft"):
            self.tool.upload(sandbox=True, new_version_of=None, dry_run=False)
        self.assertEqual([c for c in state["calls"] if c[0] != "GET"], [])

    def test_dry_run_sends_nothing(self):
        self.tool.collect(None, packages=False)
        state = self.serve({})
        self.assertEqual(self.tool.upload(sandbox=True, new_version_of=None, dry_run=True), "")
        self.assertEqual(state["calls"], [])


if __name__ == "__main__":
    unittest.main()
