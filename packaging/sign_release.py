#!/usr/bin/env python3
# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Nicolas Vaughan <nicolasvaughan@proton.me>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Firma los archivos de una versión, como los recibirá quien los
descargue, y lo comprueba.

    packaging/sign_release.py --key FINGERPRINT --public KEYFILE \
                              --sums dist/SHA256SUMS FILE...

Escribe SUMS (el SHA-256 de cada FILE, por su nombre, como lo lee
`sha256sum -c`), una firma separada en ASCII (FILE.asc) de cada FILE y de
SUMS, hecha por gpg con la clave FINGERPRINT, y luego comprueba cada firma
como lo haría el usuario: en un GNUPGHOME temporal que solo tiene KEYFILE,
la clave pública que se publica con la versión. Así se comprueban a la vez
las firmas y que la clave publicada es la que firmó. Termina con un error
si algo no se comprueba (y no deja firmas a medias).
"""

import argparse
import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sign(path: Path, key: str) -> Path:
    """PATH.asc, the detached signature of PATH with KEY (gpg asks for the
    passphrase, if it isn't cached)."""
    out = path.with_name(path.name + ".asc")
    subprocess.run(["gpg", "--batch", "--yes", "--local-user", key, "--armor",
                    "--detach-sign", "--output", str(out), str(path)],
                   check=True)
    return out


def verify(files: list, public: Path) -> list:
    """What doesn't verify with only PUBLIC known (an empty list: everything
    does)."""
    failed = []
    with tempfile.TemporaryDirectory(prefix="sign-release-") as home:
        env = {"GNUPGHOME": home, "PATH": "/usr/bin:/bin"}
        # (gpg quiere su carpeta solo para el usuario)
        Path(home).chmod(0o700)
        subprocess.run(["gpg", "--batch", "--quiet", "--import", str(public)],
                       env=env, check=True, capture_output=True)
        for path in map(Path, files):
            asc = path.with_name(path.name + ".asc")
            done = subprocess.run(["gpg", "--batch", "--verify", str(asc),
                                   str(path)], env=env, capture_output=True,
                                  text=True)
            if done.returncode != 0:
                why = (done.stderr.strip().splitlines()[-1] if done.stderr
                       else "not good")
                failed.append(f"{path.name}: {why}")
        # Un GNUPGHOME nuevo puede arrancar keyboxd o gpg-agent: se
        # detienen antes de borrar la carpeta.
        subprocess.run(["gpgconf", "--kill", "all"], env=env,
                       capture_output=True)
    return failed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="packaging/sign_release.py",
        description="Sign the files of a release.")
    parser.add_argument("--key", required=True,
                        help="the fingerprint of the signing key")
    parser.add_argument("--public", required=True,
                        help="the public key published with the release")
    parser.add_argument("--sums", required=True,
                        help="where to write the SHA-256 sums")
    parser.add_argument("files", nargs="+")
    args = parser.parse_args(argv)
    files = [Path(f) for f in args.files]
    missing = [str(f) for f in files if not f.is_file()]
    if missing:
        print(f"sign_release.py: missing: {', '.join(missing)}",
              file=sys.stderr)
        return 1
    sums = Path(args.sums)
    names = [f.name for f in files]
    # SHA256SUMS va por nombre: dos archivos con el mismo nombre no caben.
    if len(set(names)) != len(names):
        print("sign_release.py: two files have the same name", file=sys.stderr)
        return 1
    sums.write_text("".join(f"{sha256(f)}  {f.name}\n" for f in files),
                    encoding="utf-8")
    signed = files + [sums]
    try:
        for path in signed:
            sign(path, args.key)
    except subprocess.CalledProcessError:
        # (most often, a passphrase gpg could not ask for)
        print("sign_release.py: gpg could not sign (is the key's passphrase "
              "cached? see packaging/COPR.org)", file=sys.stderr)
        return 1
    failed = verify(signed, Path(args.public))
    if failed:
        print("sign_release.py: these don't verify with the published key:\n  "
              + "\n  ".join(failed), file=sys.stderr)
        return 1
    print(f"Signed and verified: {', '.join(p.name for p in signed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
