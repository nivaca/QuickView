#!/usr/bin/env python3
# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Nicolas Vaughan <nicolasvaughan@proton.me>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Prepara el depósito de una versión en Zenodo y lo sube como borrador, sin publicarlo.

    python tools/zenodo.py collect [--tag vX.Y] [--packages]
    python tools/zenodo.py upload [--sandbox] [--new-version-of ID] [--dry-run]

collect reúne en dist/zenodo/ lo que se deposita de la versión (la última etiqueta, o --tag):

- NOMBRE-VERSIÓN-source.tar.gz, el árbol completo de la etiqueta (git archive), con pruebas, documentos y
  empaquetado, que es lo que se preserva;
- con --packages, además los archivos publicados con la versión, los de dist/SHA256SUMS (rueda, AppImage,
  RPM...), cada uno con la firma que ya tenía;
- la firma separada de cada archivo (ARCHIVO.asc), SHA256SUMS de solo esos archivos y su firma, y la clave
  pública packaging/RPM-GPG-KEY-NOMBRE.

Antes comprueba la firma de la etiqueta, y después cada firma, como lo haría quien descargue el depósito: en un
GNUPGHOME temporal que solo tiene la clave pública. Si algo no se comprueba, no deja dist/zenodo/.

upload sube dist/zenodo/ a Zenodo (o a sandbox.zenodo.org, con --sandbox) con los metadatos de .zenodo.json, más
la versión, la fecha de la etiqueta y los enlaces a ella en los repositorios. Si ya hay en Zenodo un depósito
publicado con el mismo título, hace una versión nueva de él (el DOI de concepto se mantiene); si no, uno nuevo.
Nunca lo publica: deja un borrador y da su dirección, para revisarlo y publicarlo a mano. El token va en
$ZENODO_TOKEN ($ZENODO_SANDBOX_TOKEN con --sandbox), con los permisos deposit:write y deposit:actions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DESCRIPTION = "Collect a release's files for Zenodo in dist/zenodo/, signed and checked, and upload them as a draft."
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "dist" / "zenodo"
METADATA = ROOT / ".zenodo.json"
SERVERS = {False: ("https://zenodo.org", "ZENODO_TOKEN"), True: ("https://sandbox.zenodo.org", "ZENODO_SANDBOX_TOKEN")}


class Failed(Exception):
    """Something that stops the tool, with what to tell the user."""


# ------------------------------------------------------------------ the project


def public_key() -> Path:
    """packaging/RPM-GPG-KEY-NAME, the public key published with every release."""
    found = sorted((ROOT / "packaging").glob("RPM-GPG-KEY-*"))
    if len(found) != 1:
        raise Failed("there must be one packaging/RPM-GPG-KEY-NAME, the public key of the releases")
    return found[0]


def project_name() -> str:
    return public_key().name.removeprefix("RPM-GPG-KEY-")


def signing_key() -> str:
    """The project's signing key, as packaging/build-rpm.sh pins it (or $SIGNING_KEY, as there)."""
    if os.environ.get("SIGNING_KEY"):
        return os.environ["SIGNING_KEY"]
    script = ROOT / "packaging" / "build-rpm.sh"
    m = re.search(r'SIGNING_KEY="\$\{SIGNING_KEY:-([0-9A-F]{40})\}"', script.read_text() if script.is_file() else "")
    if not m:
        raise Failed("no signing key pinned in packaging/build-rpm.sh")
    return m.group(1)


def git(*args: str, env: dict[str, str] | None = None) -> str:
    done = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, env=env, check=False)
    if done.returncode != 0:
        raise Failed(f"git {' '.join(args)}: {(done.stderr or done.stdout).strip()}")
    return done.stdout.strip()


def version_of(tag: str) -> str:
    # v1.2.0 → 1.2.0; la de py-words, v3.31 → 3.31
    return tag[1:] if tag[:1] == "v" and tag[1:2].isdigit() else tag


# ------------------------------------------------------------------ signatures


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def md5(path: Path) -> str:
    # (Zenodo da el MD5 de cada archivo subido: así se ve que llegó entero)
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def bare_env(home: str) -> dict[str, str]:
    """The environment with GNUPGHOME=HOME, where only the published public key is: none of the user's keys."""
    env = dict(os.environ, GNUPGHOME=home)
    env.pop("GPG_AGENT_INFO", None)
    return env


class OnlyPublicKey:
    """A temporary GNUPGHOME with only the published public key, to check signatures as a user would."""

    def __init__(self, public: Path):
        self.public = public

    def __enter__(self) -> dict[str, str]:
        # /tmp, y no una carpeta larga: el socket de gpg-agent no admite rutas de más de ~100 caracteres
        self.home = tempfile.mkdtemp(prefix="zenodo-gpg-", dir="/tmp" if os.path.isdir("/tmp") else None)
        Path(self.home).chmod(0o700)
        self.env = bare_env(self.home)
        subprocess.run(["gpg", "--batch", "--quiet", "--import", str(self.public)], env=self.env, check=True,
                       capture_output=True)
        return self.env

    def __exit__(self, *exc):
        # (un GNUPGHOME nuevo arranca gpg-agent o keyboxd: se detienen antes de borrar la carpeta)
        subprocess.run(["gpgconf", "--kill", "all"], env=self.env, capture_output=True, check=False)
        shutil.rmtree(self.home, ignore_errors=True)


def sign(path: Path, key: str) -> None:
    """PATH.asc, PATH's detached signature with KEY (gpg asks for the passphrase if it isn't cached)."""
    done = subprocess.run(["gpg", "--batch", "--yes", "--local-user", key, "--armor", "--detach-sign", "--output",
                           f"{path}.asc", str(path)], capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise Failed(f"gpg could not sign {path.name} (is the key's passphrase cached?): {done.stderr.strip()}")


def unverified(files: list[Path], public: Path) -> list[str]:
    """Those of FILES whose FILE.asc doesn't verify with only PUBLIC known, with gpg's reason."""
    failed = []
    with OnlyPublicKey(public) as env:
        for path in files:
            done = subprocess.run(["gpg", "--batch", "--verify", f"{path}.asc", str(path)], env=env,
                                  capture_output=True, text=True, check=False)
            if done.returncode != 0:
                reason = done.stderr.strip().splitlines()[-1] if done.stderr.strip() else "not good"
                failed.append(f"{path.name}: {reason}")
    return failed


def check_tag(tag: str, public: Path) -> None:
    """The tag must be signed with the published key (git verify-tag, with only that key in gpg)."""
    with OnlyPublicKey(public) as env:
        done = subprocess.run(["git", "verify-tag", tag], cwd=ROOT, env=env, capture_output=True, text=True,
                              check=False)
    if done.returncode != 0:
        raise Failed(f"the tag {tag} is not signed with {public.name}: {done.stderr.strip()}")


def read_sums(path: Path) -> dict[str, str]:
    """{name: SHA-256} of a SHA256SUMS file (as sha256sum writes it)."""
    sums = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, name = line.split(maxsplit=1)
            sums[name.lstrip("*")] = digest
    return sums


# ------------------------------------------------------------------ collect


def released_files(version: str) -> list[tuple[Path, Path | None]]:
    """The files of dist/SHA256SUMS, each with its signature if it has one: [(file, file.asc or None)]. Each one
    is looked for in dist/ and, if not there, in build/ (the RPM's signature is beside the RPM in build/rpm/),
    and must have the SHA-256 written in SHA256SUMS."""
    sums_file = ROOT / "dist" / "SHA256SUMS"
    if not sums_file.is_file():
        raise Failed("there is no dist/SHA256SUMS (--packages takes the files of a release made here)")
    sums = read_sums(sums_file)
    found = []
    for name, digest in sums.items():
        candidates = [ROOT / "dist" / name] + sorted((ROOT / "build").rglob(name))
        matching = [c for c in candidates if c.is_file() and sha256(c) == digest]
        if not matching:
            raise Failed(f"{name}, of dist/SHA256SUMS, is not in dist/ nor build/, or has changed")
        # La firma puede estar junto a otra copia del mismo archivo (la del RPM, en build/rpm/)
        signed = next((c for c in matching if Path(f"{c}.asc").is_file()), None)
        found.append((matching[0], Path(f"{signed}.asc") if signed else None))
    if not any(version in path.name for path, _asc in found):
        raise Failed(f"dist/SHA256SUMS is not of version {version} (make that release here first, or leave out "
                     "--packages)")
    return found


def link_or_copy(source: Path, target: Path) -> None:
    # Un enlace duro no ocupa espacio (las AppImage pesan); si no se puede, una copia
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def collect(tag: str | None, packages: bool, out: Path = OUT) -> list[Path]:
    """Fill OUT with the deposit of TAG (the last tag if None); the files in it, in the order they upload."""
    tag = tag or git("describe", "--tags", "--abbrev=0")
    git("rev-parse", "--verify", "--quiet", f"refs/tags/{tag}")
    version, name, public = version_of(tag), project_name(), public_key()
    check_tag(tag, public)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    try:
        source = out / f"{name}-{version}-source.tar.gz"
        git("archive", "--format=tar.gz", f"--prefix={name}-{version}/", "--output", str(source), tag)
        files, to_sign = [source], [source]
        if packages:
            for path, asc in released_files(version):
                target = out / path.name
                if target.exists():
                    raise Failed(f"two files are named {path.name}")
                link_or_copy(path, target)
                files.append(target)
                if asc:
                    shutil.copy2(asc, f"{target}.asc")
                else:
                    to_sign.append(target)
        sums = out / "SHA256SUMS"
        sums.write_text("".join(f"{sha256(f)}  {f.name}\n" for f in files), encoding="utf-8")
        key = signing_key()
        for path in to_sign + [sums]:
            sign(path, key)
        shutil.copy2(public, out / public.name)
        failed = unverified(files + [sums], public)
        if failed:
            raise Failed("these don't verify with the published key:\n  " + "\n  ".join(failed))
    except BaseException:
        # Nada a medias: sin todas las firmas comprobadas, no hay depósito
        shutil.rmtree(out, ignore_errors=True)
        raise
    return deposit_files(out)


def deposit_files(out: Path = OUT) -> list[Path]:
    """The files of OUT in upload order: the source first, then the rest, SHA256SUMS and the key last."""
    files = sorted(p for p in out.iterdir() if p.is_file())
    order = {"source": 0, "other": 1, "sums": 2, "key": 3}

    def kind(p: Path) -> str:
        base = p.name.removesuffix(".asc")
        if base.endswith("-source.tar.gz"):
            return "source"
        if base == "SHA256SUMS":
            return "sums"
        return "key" if p.name.startswith("RPM-GPG-KEY-") else "other"

    return sorted(files, key=lambda p: (order[kind(p)], p.name.removesuffix(".asc"), p.name))


def check_deposit(out: Path = OUT) -> tuple[str, list[Path]]:
    """Before uploading, dist/zenodo/ again as a user would check it: every file in SHA256SUMS with its sum, and
    every signature good with the key that is in the deposit. Its version and its files."""
    sums_file, key = out / "SHA256SUMS", out / public_key().name
    if not sums_file.is_file() or not key.is_file():
        raise Failed("dist/zenodo/ is not complete (run: tools/zenodo.py collect)")
    sums = read_sums(sums_file)
    listed = {out / n for n in sums} | {out / f"{n}.asc" for n in sums} | {sums_file, Path(f"{sums_file}.asc"), key}
    present = set(deposit_files(out))
    if present != listed:
        extra = sorted(p.name for p in present - listed)
        missing = sorted(p.name for p in listed - present)
        raise Failed(f"dist/zenodo/ doesn't match its SHA256SUMS (extra: {extra}, missing: {missing})")
    changed = [n for n, digest in sums.items() if sha256(out / n) != digest]
    if changed:
        raise Failed(f"changed after collect: {', '.join(changed)}")
    failed = unverified([out / n for n in sums] + [sums_file], key)
    if failed:
        raise Failed("these don't verify with the published key:\n  " + "\n  ".join(failed))
    sources = [n for n in sums if n.endswith("-source.tar.gz")]
    if len(sources) != 1:
        raise Failed("dist/zenodo/ has no source archive")
    version = sources[0].removeprefix(f"{project_name()}-").removesuffix("-source.tar.gz")
    return version, deposit_files(out)


# ------------------------------------------------------------------ upload


def repository_links(tag: str) -> list[dict[str, str]]:
    """The tag on each forge of the push remotes (Codeberg, GitHub), as related identifiers of the deposit."""
    links = []
    for line in git("remote", "-v").splitlines():
        m = re.search(r"(codeberg\.org|github\.com)[:/]+([^/\s]+/[^/\s]+?)(?:\.git)?/?\s+\(push\)$", line)
        if m:
            host, repo = m.groups()
            path = f"src/tag/{tag}" if host == "codeberg.org" else f"tree/{tag}"
            url = f"https://{host}/{repo}/{path}"
            if all(link["identifier"] != url for link in links):
                links.append({"identifier": url, "relation": "isSupplementTo", "resource_type": "software",
                              "scheme": "url"})
    # Codeberg primero: es el repositorio principal
    return sorted(links, key=lambda link: "codeberg.org" not in link["identifier"])


def metadata(version: str) -> dict:
    """The deposit's metadata: .zenodo.json, with the version, the tag's date and the links to the tag."""
    if not METADATA.is_file():
        raise Failed("there is no .zenodo.json with the deposit's metadata")
    data = json.loads(METADATA.read_text(encoding="utf-8"))
    tag = next((t for t in (f"v{version}", version) if git("tag", "--list", t)), None)
    if not tag:
        raise Failed(f"there is no tag of version {version}")
    data["version"] = version
    data["publication_date"] = git("log", "-1", "--format=%cs", f"{tag}^{{commit}}")
    links = repository_links(tag)
    known = {r.get("identifier") for r in data.get("related_identifiers", [])}
    data["related_identifiers"] = data.get("related_identifiers", []) + [l for l in links if l["identifier"] not in known]
    return data


class Zenodo:
    """The few calls of Zenodo's deposit API that a draft needs (https://developers.zenodo.org/)."""

    def __init__(self, base: str, token: str):
        self.base, self.token = base.rstrip("/"), token

    def call(self, method: str, url: str, body: dict | None = None, data=None, size: int | None = None):
        if not url.startswith("http"):
            url = f"{self.base}/api/{url}"
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        elif data is not None:
            headers["Content-Type"] = "application/octet-stream"
            headers["Content-Length"] = str(size)
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                text = response.read().decode()
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:1000]
            raise Failed(f"Zenodo: {method} {url.split('?')[0]}: {e.code} {e.reason}: {detail}") from None
        except urllib.error.URLError as e:
            raise Failed(f"Zenodo: cannot reach {self.base}: {e.reason}") from None
        return json.loads(text) if text.strip() else None

    def depositions(self) -> list[dict]:
        """The token owner's depositions, all versions, published or not."""
        found, page = [], 1
        while True:
            rows = self.call("GET", f"deposit/depositions?size=100&page={page}&all_versions=true")
            found += rows
            if len(rows) < 100:
                return found
            page += 1

    def upload(self, draft: dict, path: Path) -> None:
        bucket = draft["links"]["bucket"]
        with path.open("rb") as f:
            done = self.call("PUT", f"{bucket}/{urllib.parse.quote(path.name)}", data=f, size=path.stat().st_size)
        if done and done.get("checksum") and done["checksum"] != f"md5:{md5(path)}":
            raise Failed(f"{path.name} did not arrive whole at Zenodo ({done['checksum']})")


def prepare_draft(api: Zenodo, title: str, new_version_of: str | None) -> dict:
    """The draft to fill: a new version of the published deposit of TITLE (or of NEW_VERSION_OF), or a new
    deposit if there is none; without the files a new version brings from the one before."""
    if new_version_of:
        base = api.call("GET", f"deposit/depositions/{new_version_of}")
    else:
        mine = [d for d in api.depositions() if d.get("metadata", {}).get("title") == title or d.get("title") == title]
        waiting = [d for d in mine if not d.get("submitted")]
        if waiting:
            raise Failed(f"there is already a draft of {title} on Zenodo; publish or delete it first: "
                         f"{waiting[0]['links'].get('html')}")
        concepts = {d.get("conceptrecid") for d in mine}
        if len(concepts) > 1:
            raise Failed(f"several deposits are titled {title} on Zenodo; say which with --new-version-of ID")
        base = mine[0] if mine else None
    if base is None:
        return api.call("POST", "deposit/depositions", body={})
    made = api.call("POST", f"deposit/depositions/{base['id']}/actions/newversion")
    draft = api.call("GET", made["links"]["latest_draft"])
    for f in draft.get("files", []):
        # (una versión nueva puede traer los archivos de la anterior: se quitan)
        api.call("DELETE", f"deposit/depositions/{draft['id']}/files/{f['id']}")
    return api.call("GET", f"deposit/depositions/{draft['id']}")


def upload(sandbox: bool, new_version_of: str | None, dry_run: bool) -> str:
    """dist/zenodo/ to a draft on Zenodo; the draft's address (or, with DRY_RUN, nothing sent and "")."""
    version, files = check_deposit()
    data = metadata(version)
    base, variable = SERVERS[sandbox]
    print(f"Deposit of {data['title']} {version} on {base}, as a draft:")
    for path in files:
        print(f"  {path.name}  ({path.stat().st_size:,} bytes)")
    print(json.dumps(data, indent=2, ensure_ascii=False))
    if dry_run:
        return ""
    token = os.environ.get(variable)
    if not token:
        raise Failed(f"put a Zenodo token in ${variable} (made at {base}/account/settings/applications/, "
                     "with deposit:write and deposit:actions)")
    api = Zenodo(base, token)
    draft = prepare_draft(api, data["title"], new_version_of)
    for path in files:
        print(f"  uploading {path.name}", flush=True)
        api.upload(draft, path)
    api.call("PUT", f"deposit/depositions/{draft['id']}", body={"metadata": data})
    return draft["links"].get("html") or f"{base}/uploads/{draft['id']}"


# ------------------------------------------------------------------ main


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="tools/zenodo.py", description=DESCRIPTION)
    commands = parser.add_subparsers(dest="command", required=True)
    c = commands.add_parser("collect", help="put the deposit of a release in dist/zenodo/, signed and checked")
    c.add_argument("--tag", help="the release's tag (default: the last one)")
    c.add_argument("--packages", action="store_true",
                   help="also the files published with the release (those of dist/SHA256SUMS)")
    u = commands.add_parser("upload", help="upload dist/zenodo/ to Zenodo as a draft (never published)")
    u.add_argument("--sandbox", action="store_true", help="to sandbox.zenodo.org, to try it ($ZENODO_SANDBOX_TOKEN)")
    u.add_argument("--new-version-of", metavar="ID", help="the deposit this is a new version of (default: the one "
                                                          "with the same title)")
    u.add_argument("-n", "--dry-run", action="store_true", help="only check dist/zenodo/ and show what would go")
    args = parser.parse_args(argv)
    try:
        if args.command == "collect":
            files = collect(args.tag, args.packages)
            print(f"In {OUT.relative_to(ROOT)}/, signed and checked with the published key:")
            for path in files:
                print(f"  {path.name}")
        else:
            url = upload(args.sandbox, args.new_version_of, args.dry_run)
            if url:
                print(f"\nDraft ready, NOT published. Review it, then publish it there:\n  {url}")
    except Failed as e:
        print(f"zenodo.py: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
