# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Nicolas Vaughan <nicolasvaughan@proton.me>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""La firma de los archivos de una versión (packaging/sign_release.py):
cada archivo y SHA256SUMS firmados, y cada firma comprobada con solo la
clave pública publicada; un archivo cambiado, o otra clave, no se
comprueban. Con una clave hecha aquí, en un GNUPGHOME de la prueba: nunca
la del usuario.
"""

import contextlib
import hashlib
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "sign_release", os.path.join(ROOT, "packaging", "sign_release.py"))
sign_release = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sign_release)

GPG_ENV = {"PATH": "/usr/bin:/bin"}


def make_key(home: Path, name: str) -> tuple:
    """A key without a passphrase in HOME: its fingerprint, and its public
    key exported."""
    home.mkdir(mode=0o700)
    env = dict(GPG_ENV, GNUPGHOME=str(home))
    subprocess.run(["gpg", "--batch", "--passphrase", "", "--quick-gen-key",
                    f"{name} <{name}@example.org>", "ed25519", "sign",
                    "never"], env=env, check=True, capture_output=True)
    out = subprocess.run(["gpg", "--batch", "--with-colons",
                          "--list-secret-keys"], env=env, check=True,
                         capture_output=True, text=True).stdout
    fpr = next(line.split(":")[9] for line in out.splitlines()
               if line.startswith("fpr"))
    public = home.parent / f"{name}.asc"
    public.write_bytes(subprocess.run(
        ["gpg", "--batch", "--armor", "--export", fpr], env=env, check=True,
        capture_output=True).stdout)
    return fpr, public


def kill_agents(home: Path):
    subprocess.run(["gpgconf", "--kill", "all"],
                   env=dict(GPG_ENV, GNUPGHOME=str(home)),
                   capture_output=True)


@unittest.skipUnless(shutil.which("gpg") and sys.platform != "win32",
                     "needs gpg")
class SignRelease(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        home = self.tmp / "gnupg"
        self.fpr, self.public = make_key(home, "release")
        self.addCleanup(kill_agents, home)
        # gpg firma con el GNUPGHOME de la prueba, nunca con el del usuario
        patcher = mock.patch.dict(os.environ, GNUPGHOME=str(home))
        patcher.start()
        self.addCleanup(patcher.stop)

    def main(self, *args):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), \
                contextlib.redirect_stdout(io.StringIO()):
            code = sign_release.main(list(args))
        return code, err.getvalue()

    def test_every_file_signed_and_checked(self):
        files = []
        for name, data in (("quickview.zip", b"zip"),
                           ("quickview.x86_64.rpm", b"rpm"),
                           ("quickview.src.rpm", b"srpm")):
            (self.tmp / name).write_bytes(data)
            files.append(self.tmp / name)
        sums = self.tmp / "SHA256SUMS"
        code, err = self.main("--key", self.fpr, "--public", str(self.public),
                              "--sums", str(sums), *map(str, files))
        self.assertEqual(code, 0, err)
        self.assertEqual(sums.read_text(), "".join(
            f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}\n"
            for f in files))
        for f in files + [sums]:
            self.assertTrue(f.with_name(f.name + ".asc").read_text()
                            .startswith("-----BEGIN PGP SIGNATURE-----"))
        self.assertEqual(sign_release.verify(files + [sums], self.public), [])
        # A file changed after it was signed: its signature is bad.
        files[0].write_bytes(b"zip, changed")
        (bad,) = sign_release.verify(files, self.public)
        self.assertTrue(bad.startswith("quickview.zip:"))

    def test_another_key_does_not_check(self):
        """The key published must be the one that signed: with another,
        nothing verifies, and the release stops."""
        other_home = self.tmp / "other-home"
        _, other = make_key(other_home, "other")
        self.addCleanup(kill_agents, other_home)
        (self.tmp / "quickview.zip").write_bytes(b"zip")
        code, err = self.main("--key", self.fpr, "--public", str(other),
                              "--sums", str(self.tmp / "SHA256SUMS"),
                              str(self.tmp / "quickview.zip"))
        self.assertEqual(code, 1)
        self.assertIn("don't verify", err)

    def test_missing_files_are_said(self):
        code, err = self.main("--key", self.fpr, "--public", str(self.public),
                              "--sums", str(self.tmp / "S"),
                              str(self.tmp / "nothing.zip"))
        self.assertEqual(code, 1)
        self.assertIn("missing", err)


if __name__ == "__main__":
    unittest.main()
