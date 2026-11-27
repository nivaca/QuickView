# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Nicolas Vaughan <nicolasvaughan@proton.me>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Pruebas de tools/zenodo.py: el depósito de una versión en build/zenodo/ (el árbol de la etiqueta, los paquetes
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
                d["submitted"] = True
                d["doi"] = f"10.5072/zenodo.{d['id']}"
                return self.reply(202, self.deposition(d))
        if parts[:2] == ["api", "records"] and parts[3:] == ["draft"]:
            # La API de registros (InvenioRDM): el mismo borrador, con sus campos de solo lectura
            # Como Zenodo: con "application/json", el formato de la API de depósitos; el de InvenioRDM hay que pedirlo
            d = deps[int(parts[2])]
            if method == "GET" and self.headers.get("Accept") != "application/vnd.inveniordm.v1+json":
                return self.reply(200, self.deposition(d))
            if method == "GET":
                return self.reply(200, d.get("record") or {
                    "id": str(d["id"]), "metadata": {"title": d["metadata"].get("title")}, "custom_fields": {},
                    "access": {"record": "public"}, "files": {"enabled": True}, "links": {}, "revision_id": 3})
            if method == "PUT":
                d["record"] = json.loads(body)
                return self.reply(200, d["record"])
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
    """A project of mentira, with the tool copied into it, a signed tag and the files of a release in build/release/."""

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
        (self.root / ".zenodo.json").write_text(json.dumps({
            "title": "demo", "upload_type": "software", "creators": [{"name": "Vaughan, Nicolas"}],
            "languages": ["eng", "spa"], "programming_language": "python", "development_status": "active"}))
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
        # Nunca el llavero de quien corre las pruebas
        self.keyring = {}
        self.tool.keyring = self.keyring.get

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
        """build/release/ as the release leaves it: two files signed, one (the .deb) whose signature is not there;
        and the RPM, with its signature, in build/rpm/ only (dist/ has a copy of it, without its signature)."""
        out, rpms = self.root / "build" / "release", self.root / "build" / "rpm" / "RPMS"
        out.mkdir(parents=True)
        rpms.mkdir(parents=True)
        files = {"demo-1.0.zip": b"zip", "demo-1.0-x86_64.AppImage": b"appimage", "demo_1.0_all.deb": b"deb",
                 "demo-1.0-1.noarch.rpm": b"rpm"}
        for name, data in files.items():
            (rpms if name.endswith(".rpm") else out).joinpath(name).write_bytes(data)
        (self.root / "dist").mkdir()
        shutil.copy2(rpms / "demo-1.0-1.noarch.rpm", self.root / "dist" / "demo-1.0-1.noarch.rpm")
        for path in (out / "demo-1.0.zip", out / "demo-1.0-x86_64.AppImage", rpms / "demo-1.0-1.noarch.rpm"):
            self.tool.sign(path, self.fpr)
        (out / "SHA256SUMS").write_text("".join(f"{hashlib.sha256(d).hexdigest()}  {n}\n" for n, d in files.items()))
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

    def test_the_signing_key_is_that_of_the_public_key(self):
        """Without $SIGNING_KEY, the key that signs is the one of the published public key, by its fingerprint."""
        del os.environ["SIGNING_KEY"]
        self.assertEqual(self.tool.signing_key(), self.fpr)
        self.tool.collect(None, packages=False)
        self.tool.check_deposit()

    def test_the_public_key_of_the_android_apps(self):
        """The public key as GPG-KEY-NAME.asc at the top of the repository, as in the Android apps."""
        (self.root / "packaging" / "RPM-GPG-KEY-demo").rename(self.root / "GPG-KEY-demo-app.asc")
        names = [p.name for p in self.tool.collect(None, packages=False)]
        self.assertEqual(names, ["demo-app-1.0-source.tar.gz", "demo-app-1.0-source.tar.gz.asc", "SHA256SUMS",
                                 "SHA256SUMS.asc", "GPG-KEY-demo-app.asc"])
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
        (self.root / "build" / "release" / "demo-1.0.zip").write_bytes(b"zip, changed")
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
        data, extra = self.tool.metadata("1.0")
        self.assertEqual(data["version"], "1.0")
        # El README de la etiqueta, no el de después
        self.assertEqual(data["description"], "<p>demo</p>")
        self.assertEqual(data["language"], "eng")
        for key in ("languages", "programming_language", "development_status"):
            self.assertNotIn(key, data)
        year = data["publication_date"][:4]
        self.assertEqual(extra, {"languages": ["eng", "spa"], "programming_language": "python",
                                 "development_status": "active", "copyright": f"Copyright © {year} Nicolas Vaughan",
                                 "repository": "https://github.com/someone/demo"})
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
        record = draft["record"]
        self.assertEqual(record["metadata"]["languages"], [{"id": "eng"}, {"id": "spa"}])
        self.assertRegex(record["metadata"]["copyright"], r"^Copyright © \d{4} Nicolas Vaughan$")
        self.assertEqual(record["custom_fields"], {
            "code:codeRepository": "https://github.com/someone/demo",
            "code:programmingLanguage": [{"id": "python"}], "code:developmentStatus": {"id": "active"}})
        self.assertNotIn("links", record)
        # Lo que se manda es el borrador en el formato de InvenioRDM, no en el de la API de depósitos
        self.assertEqual(record["access"], {"record": "public"})
        self.assertEqual(record["files"], {"enabled": True})
        self.assertNotIn("revision_id", record)

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

    def test_upload_with_publish_publishes_it(self):
        self.tool.collect(None, packages=False)
        state = self.serve({7: {"id": 7, "submitted": True, "metadata": {"title": "demo"}, "files": [],
                                "conceptrecid": "c7"}})
        said = self.tool.upload(sandbox=True, new_version_of=None, dry_run=False, publish=True)
        self.assertIn(("POST", "/api/deposit/depositions/8/actions/publish"), state["calls"])
        self.assertTrue(state["depositions"][8]["submitted"])
        self.assertTrue(said.startswith("10.5072/zenodo.8 "))
        # Lo de la API de registros va antes de publicar
        calls = state["calls"]
        self.assertLess(calls.index(("PUT", "/api/records/8/draft")),
                        calls.index(("POST", "/api/deposit/depositions/8/actions/publish")))

    def test_publish_the_waiting_draft(self):
        state = self.serve({7: {"id": 7, "submitted": True, "metadata": {"title": "demo"}, "files": [],
                                "conceptrecid": "c7"},
                            8: {"id": 8, "submitted": False, "metadata": {"title": "demo"}, "files": [],
                                "conceptrecid": "c7"}})
        said = self.tool.publish(sandbox=True, draft_id=None)
        self.assertEqual([c for c in state["calls"] if c[0] == "POST"],
                         [("POST", "/api/deposit/depositions/8/actions/publish")])
        self.assertTrue(said.startswith("10.5072/zenodo.8 "))
        state["calls"].clear()
        with self.assertRaisesRegex(self.tool.Failed, "no draft"):
            self.tool.publish(sandbox=True, draft_id=None)

    def test_a_waiting_draft_stops_upload(self):
        self.tool.collect(None, packages=False)
        state = self.serve({7: {"id": 7, "submitted": False, "metadata": {"title": "demo"}, "files": [],
                                "conceptrecid": "c7"}})
        with self.assertRaisesRegex(self.tool.Failed, "already a draft"):
            self.tool.upload(sandbox=True, new_version_of=None, dry_run=False)
        self.assertEqual([c for c in state["calls"] if c[0] != "GET"], [])

    def test_a_token_that_is_not_one_stops_upload(self):
        """A placeholder copied from an example ("…") is refused before anything is sent."""
        self.tool.collect(None, packages=False)
        state = self.serve({})
        for token in ("\u2026", "two words", "secret\n"):
            os.environ["ZENODO_SANDBOX_TOKEN"] = token
            with self.assertRaisesRegex(self.tool.Failed, "is not a Zenodo token"):
                self.tool.upload(sandbox=True, new_version_of=None, dry_run=False)
        self.assertEqual(state["calls"], [])

    def test_readme_as_html(self):
        """What Zenodo takes in a description: headings as bold paragraphs, no images, relative links made
        absolute, lists with their continuation lines, tables and code."""
        readme = ("Demo\n====\n\nIt *plays* **music**.\n\n![shot](docs/a.png)\n\nUsage\n-----\n\n"
                  "- one, with `a<b>`\n  and more\n- see [the manual](docs/M.pdf) or [web](https://x.org)\n\n"
                  "| Key | Does |\n|-----|------|\n| B | mark |\n\n    uv run demo\n\nA &lt;b&gt; & c\n")
        self.assertEqual(self.tool.markdown_html(readme, "https://github.com/someone/demo/blob/v1.0/"), "\n".join([
            "<p><strong>Demo</strong></p>",
            "<p>It <em>plays</em> <strong>music</strong>.</p>",
            "<p><strong>Usage</strong></p>",
            '<ul><li>one, with <code>a&lt;b&gt;</code> and more</li><li>see <a href="https://github.com/someone/demo/'
            'blob/v1.0/docs/M.pdf">the manual</a> or <a href="https://x.org">web</a></li></ul>',
            "<table><thead><tr><th>Key</th><th>Does</th></tr></thead><tbody><tr><td>B</td><td>mark</td></tr>"
            "</tbody></table>",
            "<pre><code>uv run demo</code></pre>",
            "<p>A &lt;b&gt; &amp; c</p>"]))

    def test_fields_zenodo_did_not_keep_stop_upload(self):
        """If the draft, read again, lacks a field that was sent (Spanish, say), upload says so."""
        self.tool.collect(None, packages=False)
        self.serve({})
        keep = self.tool.record_fields
        self.tool.record_fields = lambda record, extra: keep(record, dict(extra, languages=["eng"]))
        with self.assertRaisesRegex(self.tool.Failed, "did not keep languages"):
            self.tool.upload(sandbox=True, new_version_of=None, dry_run=False)

    def test_the_token_from_the_keyring(self):
        """Without $ZENODO_SANDBOX_TOKEN, the token kept in the keyring (service zenodo-sandbox) is used; with
        neither, upload stops before sending anything, saying how to keep one."""
        self.tool.collect(None, packages=False)
        state = self.serve({})
        del os.environ["ZENODO_SANDBOX_TOKEN"]
        with self.assertRaisesRegex(self.tool.Failed, "secret-tool store .* service zenodo-sandbox"):
            self.tool.upload(sandbox=True, new_version_of=None, dry_run=False)
        self.assertEqual(state["calls"], [])
        self.keyring["zenodo"] = "secret"  # (el de zenodo.org no sirve para sandbox)
        with self.assertRaises(self.tool.Failed):
            self.tool.token(sandbox=True)
        self.keyring["zenodo-sandbox"] = "secret"
        self.assertTrue(self.tool.upload(sandbox=True, new_version_of=None, dry_run=False))
        self.assertEqual(self.tool.main(["check-token", "--sandbox"]), 0)

    def test_readme_as_html_other_readmes(self):
        """What other READMEs have: <URL> and <EMAIL>, code in a link or in bold, a block of HTML with images, a
        fenced block inside a list item, and several programming languages."""
        readme = ('<p align="center">\n  <img src="a.png" alt="shot">\n</p>\n\n'
                  "See [`docs/D.md`](docs/D.md), **`run.py`** and <https://x.org>; Me <me@example.org>.\n\n"
                  "1. Install:\n\n   ```sh\n   pip install demo\n   ```\n\n   then run it.\n")
        self.assertEqual(self.tool.markdown_html(readme, "https://github.com/someone/demo/blob/v1.0/"), "\n".join([
            '<p>See <a href="https://github.com/someone/demo/blob/v1.0/docs/D.md"><code>docs/D.md</code></a>, '
            '<strong><code>run.py</code></strong> and <a href="https://x.org">https://x.org</a>; Me '
            '<a href="mailto:me@example.org">me@example.org</a>.</p>',
            "<ol><li>Install: <pre><code>pip install demo</code></pre> then run it.</li></ol>"]))
        self.assertEqual(self.tool.languages("python"), ["python"])
        self.assertEqual(self.tool.languages(["kotlin", "c++"]), ["kotlin", "c++"])

    def test_the_description_leaves_out_other_readmes_and_screenshots(self):
        """The line that points to the README in other languages and the Screenshots section (to the next
        heading of its level or higher, whether # or underlined) are not in the description."""
        readme = ("Demo\n====\n\n*Leer en español: [README_es.md](README_es.md).*\n\nIt plays.\n\n"
                  "*(Español: [README_es.md](README_es.md); Latine: [README_la.md](README_la.md))*\n\n"
                  "*[Leer en español](https://github.com/someone/demo/blob/main/README.es.md)*\n\n"
                  "Screenshots\n-----------\n\n![a](a.png)\n\n### Main window\n\nText.\n\n"
                  "Usage\n-----\n\n```\n# Screenshots\n```\n\n## Screenshots\n\n![b](b.png)\n\n"
                  "# Licence\n\n*Italics, see [README.md](README.md).*\n")
        self.assertEqual(self.tool.description_markdown(readme), "Demo\n====\n\n\nIt plays.\n\n\n\n"
                         "Usage\n-----\n\n```\n# Screenshots\n```\n\n# Licence\n\n"
                         "*Italics, see [README.md](README.md).*\n")

    def test_dry_run_sends_nothing(self):
        self.tool.collect(None, packages=False)
        state = self.serve({})
        self.assertEqual(self.tool.upload(sandbox=True, new_version_of=None, dry_run=True), "")
        self.assertEqual(state["calls"], [])


if __name__ == "__main__":
    unittest.main()
