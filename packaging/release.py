#!/usr/bin/env python3
# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Nicolas Vaughan <nicolasvaughan@proton.me>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Publica una versión de QuickView, del registro de cambios a Copr, de una vez.

    packaging/release.py VERSION [--no-zenodo | --zenodo-draft] [--dry-run]

Lo que se publica es lo que CHANGELOG.md tiene bajo "## Unreleased". En orden,
y deteniéndose en lo primero que falle:

1. Comprueba, sin cambiar nada: que está en main, limpio y al día con origin;
   que VERSION es nueva y mayor que la del spec; que hay algo bajo Unreleased;
   que gh, tea y copr-cli tienen la sesión abierta; que rpmsign está; que la
   clave de firma se puede usar; que las pruebas (tools/test.py, todas a la
   vez) y el lint pasan.
2. Sube la versión de packaging/quickview.spec (Version, Release 1, una
   entrada de %changelog hecha con los titulares de Unreleased) y cambia
   "Unreleased" por "VERSION — fecha"; hace el commit "Release VERSION" y pone
   la etiqueta vVERSION, en local, firmada con la clave (git tag --sign), que
   luego comprueba (git tag --verify).
3. Construye los RPM con build-rpm.sh --sign. La clave es aquella cuya mitad
   pública es packaging/RPM-GPG-KEY-quickview, por su huella, nunca otra clave
   con el mismo nombre. gpg pide su frase de contraseña. Luego firma cada
   archivo que se va a publicar (packaging/sign_release.py: FILE.asc, y
   build/release/SHA256SUMS con su .asc) y comprueba cada firma solo con esa
   clave pública. Por último reúne el depósito para Zenodo en build/zenodo/
   (tools/zenodo.py collect: el árbol de la etiqueta, firmado, con SHA256SUMS
   y la clave pública, cada firma comprobada).
   Hasta aquí nada ha salido de esta máquina; si algo falla, el script dice
   cómo deshacer el commit y la etiqueta locales.
4. Sube main y la etiqueta (origin sube a GitHub y a Codeberg); publica la
   versión en GitHub y en Codeberg, cada una con los dos RPM, el zip
   (build/release/quickview-VERSION.zip), la firma de cada uno, SHA256SUMS y
   su firma, y la clave, y con notas hechas del registro de cambios, con las
   sumas de comprobación.
5. Vuelve a descargar la versión y comprueba sus sumas, las firmas de los RPM
   contra su propio archivo de clave, como lo haría el dnf de un usuario, y la
   firma separada de cada archivo contra la misma clave, como lo haría gpg.
6. Construye el RPM fuente en Copr, espera y comprueba que el repositorio de
   cada chroot sirve la versión nueva.
7. Salvo con --no-zenodo, sube build/zenodo/ a Zenodo y lo publica, con un DOI
   nuevo (el token de $ZENODO_TOKEN o del llavero); con --zenodo-draft queda
   como borrador, para publicarlo a mano.
8. Borra build/release/ y build/zenodo/: aquí solo se quedan los RPM (en
   build/rpm/, y la copia del binario en dist/, que no guarda nada más); las
   forjas, Copr y Zenodo tienen el resto.

--dry-run hace el paso 1 y escribe lo que escribiría el paso 2, las órdenes
de la etiqueta firmada, de la construcción y de la firma, los archivos que
adjuntaría, las notas y los pasos de Zenodo.
"""

import argparse
import datetime
import glob
import hashlib
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packaging"))
import sign_release  # noqa: E402

SPEC = os.path.join(ROOT, "packaging", "quickview.spec")
CHANGELOG = os.path.join(ROOT, "CHANGELOG.md")
VERSION_FILE = os.path.join(ROOT, "version.py")
KEY_FILE = os.path.join(ROOT, "packaging", "RPM-GPG-KEY-quickview")
# Lo que se publica, salvo los RPM, se hace y se firma en build/release/, no en
# dist/: aquí solo se guarda el RPM (en build/rpm/, y su copia en dist/)
OUT = os.path.join(ROOT, "build", "release")
# Las sumas de comprobación de lo publicado (firmadas, como cada archivo)
SUMS = os.path.join(OUT, "SHA256SUMS")
# Lo que se borra al final, cuando ya está publicado
CLEANED = [OUT, os.path.join(ROOT, "build", "zenodo")]
GITHUB_REPO = "nivaca/QuickView"
CODEBERG_REPO = "nivaca/QuickView"
TEA_LOGIN = "codeberg"      # (the login of tea for codeberg.org)
COPR_PROJECT = "nivaca/quickview"
AUTHOR = "Nicolas Vaughan <nicolasvaughan@proton.me>"
UNRELEASED = "## Unreleased"


def zenodo_token() -> bool:
    """Whether tools/zenodo.py finds a Zenodo token, in $ZENODO_TOKEN or
    in the desktop keyring (secret-tool)."""
    tool = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "tools", "zenodo.py")
    done = subprocess.run([sys.executable, tool, "check-token"],
                          capture_output=True, check=False)
    return done.returncode == 0


class ReleaseError(Exception):
    pass


# ----------------------------------------------------------- the text work
# Pure functions, so the tests can check what a release would write.

def version_tuple(version: str) -> tuple:
    if not re.fullmatch(r"\d+(\.\d+){1,3}", version):
        raise ReleaseError(f"not a version: {version!r} (want e.g. 0.1.3)")
    return tuple(int(p) for p in version.split("."))


def unreleased_section(changelog: str) -> str:
    """The text under "## Unreleased", up to the next "## " heading."""
    match = re.search(r"^## Unreleased[ \t]*\n(.*?)(?=^## |\Z)",
                      changelog, re.M | re.S)
    if not match or not match.group(1).strip():
        raise ReleaseError("CHANGELOG.md has nothing under \"## Unreleased\"")
    return match.group(1).strip()


def headlines(section: str) -> list:
    """One line per change: each bullet's bold headline, else its first
    sentence, without the closing full stop."""
    found = []
    for bullet in re.findall(r"^- (.*?)(?=^- |^#|\Z)", section, re.M | re.S):
        text = " ".join(bullet.split())
        bold = re.match(r"\*\*(.+?)\*\*", text)
        line = bold.group(1) if bold else re.split(r"(?<=\.)\s", text)[0]
        found.append(line.strip().rstrip(".").replace("`", ""))
    return found


def bump_changelog(changelog: str, version: str, date: str) -> str:
    if changelog.count(UNRELEASED + "\n") != 1:
        raise ReleaseError("CHANGELOG.md needs exactly one \"## Unreleased\"")
    return changelog.replace(UNRELEASED + "\n", f"## {version} — {date}\n", 1)


def bump_version_file(text: str, version: str) -> str:
    text, n = re.subn(r'^VERSION = "[^"]*"$', f'VERSION = "{version}"',
                      text, count=1, flags=re.M)
    if not n:
        raise ReleaseError("version.py has no VERSION = \"...\" line")
    return text


def spec_entry(version: str, when: datetime.date, lines: list) -> str:
    """A %changelog entry, wrapped as rpm changelogs are."""
    head = f"* {when.strftime('%a %b %d %Y')} {AUTHOR} - {version}-1"
    body = [textwrap.fill(line, width=72, initial_indent="- ",
                          subsequent_indent="  ") for line in lines]
    return "\n".join([head, *body]) + "\n\n"


def bump_spec(spec: str, version: str, when: datetime.date,
              lines: list) -> str:
    spec, n_version = re.subn(r"^(Version:\s*)\S+$", rf"\g<1>{version}",
                              spec, count=1, flags=re.M)
    spec, n_release = re.subn(r"^(Release:\s*)\d+(%\{\?dist\})$",
                              r"\g<1>1\g<2>", spec, count=1, flags=re.M)
    if not (n_version and n_release and "%changelog\n" in spec):
        raise ReleaseError("quickview.spec has no Version/Release/%changelog "
                           "where expected")
    return spec.replace("%changelog\n",
                        "%changelog\n" + spec_entry(version, when, lines), 1)


def spaced_fingerprint(fpr: str) -> str:
    groups = [fpr[i:i + 4] for i in range(0, 40, 4)]
    return " ".join(groups[:5]) + "  " + " ".join(groups[5:])


def release_notes(version: str, previous: str, section: str,
                  files: dict, fpr: str) -> str:
    """The GitHub release's text. files maps each RPM's name to its
    SHA-256; the first one ending in .x86_64.rpm is the one to install,
    and the .zip, if there is one, the bundle for other distributions."""
    rpm = next(name for name in files if name.endswith(".x86_64.rpm"))
    srpm = next(name for name in files if name.endswith(".src.rpm"))
    bundle = next((name for name in files if name.endswith(".zip")), None)
    anywhere = (f"download `{bundle}`, unzip it, and run `./install.sh` in "
                f"the `{bundle[:-4]}` folder (or clone the repository and run "
                "it there)" if bundle else
                "clone the repository and run `./install.sh`")
    since = (f"Changes since [{previous}](https://github.com/{GITHUB_REPO}"
             f"/releases/tag/v{previous}).\n\n") if previous else ""
    rows = "\n".join(f"| `{name}` | `{digest}` |"
                     for name, digest in files.items())
    example = bundle or rpm
    return f"""{since}## What's new

{section}

The full list is in [CHANGELOG.md](https://github.com/{GITHUB_REPO}/blob/v{version}/CHANGELOG.md).

## Install

**Fedora, from Copr (recommended):** signed packages that `dnf upgrade` keeps current.

```bash
sudo dnf copr enable {COPR_PROJECT}
sudo dnf install quickview
```

**Fedora, from this page:** download `{rpm}` and `RPM-GPG-KEY-quickview` below. Both RPMs are signed with Nicolas Vaughan's key, fingerprint `{spaced_fingerprint(fpr)}` (also in the repository as [`packaging/RPM-GPG-KEY-quickview`](https://github.com/{GITHUB_REPO}/blob/main/packaging/RPM-GPG-KEY-quickview)). Import it once, and `dnf` checks the signature:

```bash
sudo rpm --import RPM-GPG-KEY-quickview
sudo dnf install ./{rpm}
```

On another Fedora release, rebuild it with `rpmbuild --rebuild {srpm}`.

Space then opens the preview in Dolphin (restart Dolphin if it was open); QuickView sets that up without overriding a shortcut you chose. There's no need to log out.

**Any distribution:** {anywhere}. If you used `install.sh` before, run `./uninstall.sh` before installing the package.

## Checking a download

Every file here has its detached signature (`FILE.asc`), by the same key; `SHA256SUMS` lists their checksums and is signed too, and so is the tag `v{version}`. Import the key once, then check a file's signature and its checksum:

```bash
gpg --import RPM-GPG-KEY-quickview
gpg --verify {example}.asc {example}
gpg --verify SHA256SUMS.asc SHA256SUMS && sha256sum -c --ignore-missing SHA256SUMS
```

## Files

| File | SHA-256 |
|---|---|
{rows}

QuickView is by Nicolas Vaughan (forked from the QuickView app by Mustapha Alioglou). Licensed GPL-3.0-or-later.
"""


# ------------------------------------------------------------- the commands

def say(text: str):
    print(text, flush=True)


def run(cmd, capture=False, check=True, env=None):
    result = subprocess.run(cmd, cwd=ROOT, text=True, env=env,
                            capture_output=capture)
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip() if capture else ""
        raise ReleaseError(f"failed: {' '.join(cmd)}"
                           + (f"\n{detail[-1500:]}" if detail else ""))
    return result.stdout.strip() if capture else result.returncode


def key_fingerprint() -> str:
    """The fingerprint of the published public key — the one to sign with."""
    out = run(["gpg", "--batch", "--with-colons", "--show-keys", KEY_FILE],
              capture=True)
    fprs = [line.split(":")[9] for line in out.splitlines()
            if line.startswith("fpr:")]
    if not fprs:
        raise ReleaseError(f"no key in {KEY_FILE}")
    return fprs[0]


def check_signing_key(fpr: str):
    out = run(["gpg", "--batch", "--with-colons", "--list-secret-keys", fpr],
              capture=True, check=False)
    sec = [line.split(":") for line in out.splitlines()
           if line.startswith("sec:")]
    if not sec:
        raise ReleaseError(f"the secret half of {fpr} is not in gpg here")
    validity = sec[0][1]
    if validity in ("r", "e", "d", "i"):
        raise ReleaseError(f"signing key {fpr} is not usable (validity "
                           f"{validity!r}: revoked, expired or invalid)")


def python_for_tests() -> str:
    venv = os.path.join(ROOT, ".venv", "bin", "python")
    return venv if os.access(venv, os.X_OK) else sys.executable


def preflight(version: str, dry_run: bool) -> dict:
    say("== Checks")
    for tool, hint in (("git", "git"), ("gh", "gh"), ("tea", "tea"),
                       ("rpmbuild", "rpm-build"),
                       ("rpmspec", "rpm-build"), ("rpmsign", "rpm-sign"),
                       ("rpmkeys", "rpm"), ("gpg", "gnupg2"),
                       ("copr-cli", "copr-cli"), ("dnf", "dnf")):
        if not shutil.which(tool):
            raise ReleaseError(f"{tool} not found (sudo dnf install {hint})")
    if run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture=True) != "main":
        raise ReleaseError("not on main")
    # A dry run is a rehearsal, so it only warns about these; a release
    # must be made from exactly what is on GitHub.
    def refuse(reason: str):
        if not dry_run:
            raise ReleaseError(reason)
        say(f"   warning: {reason} (a real release would stop here)")

    if run(["git", "status", "--porcelain"], capture=True):
        refuse("the tree has uncommitted changes")
    run(["git", "fetch", "-q", "origin"])
    if run(["git", "rev-parse", "HEAD"], capture=True) != \
            run(["git", "rev-parse", "origin/main"], capture=True):
        refuse("main is not the same as origin/main (pull or push first)")
    tag = f"v{version}"
    if run(["git", "tag", "-l", tag], capture=True) or \
            run(["git", "ls-remote", "--tags", "origin", tag], capture=True):
        raise ReleaseError(f"{tag} already exists")
    current = run(["rpmspec", "-q", "--srpm", "--qf", "%{version}", SPEC],
                  capture=True)
    if version_tuple(version) <= version_tuple(current):
        raise ReleaseError(f"{version} is not higher than the spec's {current}")
    with open(CHANGELOG, encoding="utf-8") as fh:
        section = unreleased_section(fh.read())
    lines = headlines(section)
    if not lines:
        raise ReleaseError("no bullets under \"## Unreleased\"")
    run(["gh", "auth", "status"], capture=True)
    logins = run(["tea", "login", "list", "--output", "simple"], capture=True)
    if not any(line.split()[:1] == [TEA_LOGIN] for line in logins.splitlines()):
        raise ReleaseError(f"tea has no login \"{TEA_LOGIN}\" (tea login add)")
    owner = COPR_PROJECT.split("/")[0]
    if run(["copr-cli", "whoami"], capture=True) != owner:
        raise ReleaseError(f"copr-cli is not logged in as {owner}")
    fpr = key_fingerprint()
    check_signing_key(fpr)
    say(f"   {version} after {current}; {len(lines)} change(s); key {fpr}")

    say("== Tests and lint")
    # A la vez, cada archivo en un proceso propio (tools/test.py, que ya
    # pone QT_QPA_PLATFORM=offscreen)
    tests = subprocess.run([python_for_tests(), os.path.join(ROOT, "tools", "test.py")],
                           cwd=ROOT, capture_output=True, text=True)
    summary = [line for line in tests.stdout.splitlines() if line.strip()][-1:]
    say("   " + " | ".join(summary))
    if tests.returncode != 0:
        raise ReleaseError("the tests fail:\n" + tests.stdout[-3000:])
    if shutil.which("uvx"):
        run(["uvx", "ruff", "check", "--select", "F", "-q", "."])
        say("   lint ok")
    else:
        say("   (uvx not found: lint skipped)")
    return {"current": current, "section": section, "lines": lines,
            "fpr": fpr}


def published(paths: list) -> list:
    """What a release attaches: each built file, its signature, SHA256SUMS
    and its signature, and the public key."""
    return ([*paths, *(f"{p}.asc" for p in paths), SUMS, f"{SUMS}.asc",
             KEY_FILE])


def sign_command(fpr: str, paths: list) -> list:
    return [sys.executable, os.path.join(ROOT, "packaging", "sign_release.py"),
            "--key", fpr, "--public", KEY_FILE, "--sums", SUMS, *paths]


def tag_commands(fpr: str, version: str) -> list:
    """The signed tag, and its check."""
    tag = f"v{version}"
    return [["git", "tag", "--sign", "--local-user", fpr, "-m",
             f"QuickView {version}", tag],
            ["git", "tag", "--verify", tag]]


def expected_paths(version: str) -> list:
    """The files build() will find (for the dry run), from rpm's %{dist}."""
    dist = run(["rpm", "--eval", "%{?dist}"], capture=True)
    nvr = f"quickview-{version}-1{dist}"
    return [os.path.join(ROOT, "build", "rpm", "RPMS", "x86_64",
                         f"{nvr}.x86_64.rpm"),
            os.path.join(ROOT, "build", "rpm", "SRPMS", f"{nvr}.src.rpm"),
            os.path.join(OUT, f"quickview-{version}.zip")]


def sign(fpr: str, paths: list):
    """Every file signed, with SHA256SUMS, and each signature checked with
    only the published key (sign_release.py stops on the first doubt)."""
    say("== Signing every file and checking it with the published key")
    run(sign_command(fpr, paths))


def build(fpr: str, version: str) -> dict:
    """The signed RPMs (in build/rpm/) and the Zip bundle (in
    build/release/) that build-rpm.sh makes, with their SHA-256s."""
    say("== Building and signing (gpg asks for the key's passphrase)")
    run([os.path.join(ROOT, "packaging", "build-rpm.sh"), f"--sign={fpr}"])
    found = sorted(glob.glob(os.path.join(ROOT, "build", "rpm", "RPMS", "*", "*.rpm"))
                   + glob.glob(os.path.join(ROOT, "build", "rpm", "SRPMS", "*.rpm")))
    bundle = os.path.join(OUT, f"quickview-{version}.zip")
    if not os.path.isfile(bundle):
        raise ReleaseError(f"build-rpm.sh made no {os.path.relpath(bundle, ROOT)}")
    found.append(bundle)
    files = {}
    for path in found:
        with open(path, "rb") as fh:
            files[os.path.basename(path)] = hashlib.sha256(fh.read()).hexdigest()
    return {"paths": found, "files": files}


def verify_download(version: str, files: dict):
    say("== Checking the published release as a user would")
    with tempfile.TemporaryDirectory() as tmp:
        dl = os.path.join(tmp, "files")
        run(["gh", "release", "download", f"v{version}", "-R", GITHUB_REPO,
             "-D", dl])
        keyring = os.path.join(tmp, "keyring")
        check = ["--dbpath", keyring, "--define", "_keyring fs",
                 "--define", f"_keyringpath {keyring}/pubkeys/"]
        run(["rpmkeys", *check, "--import",
             os.path.join(dl, "RPM-GPG-KEY-quickview")], capture=True)
        for name, digest in files.items():
            path = os.path.join(dl, name)
            with open(path, "rb") as fh:
                if hashlib.sha256(fh.read()).hexdigest() != digest:
                    raise ReleaseError(f"{name} on GitHub is not the file built")
            if not name.endswith(".rpm"):
                say(f"   {name}: checksum matches")
                continue
            run(["rpmkeys", *check, "-K", path], capture=True)
            say(f"   {name}: signature OK, checksum matches")
        # Y las firmas aparte, con la clave descargada y nada más.
        signed = [os.path.join(dl, name) for name in files] + \
            [os.path.join(dl, "SHA256SUMS")]
        failed = sign_release.verify(
            signed, os.path.join(dl, "RPM-GPG-KEY-quickview"))
        if failed:
            raise ReleaseError("on GitHub, these don't verify with the "
                               "published key:\n  " + "\n  ".join(failed))
        say("   every .asc verifies with RPM-GPG-KEY-quickview")


def codeberg(version: str, notes: str, paths: list):
    """The release on Codeberg, as on GitHub: the same title, notes and
    files.  (tea runs outside the repository, which it would otherwise
    read its remote from.)"""
    args = ["tea", "releases", "create", "--login", TEA_LOGIN,
            "--repo", CODEBERG_REPO, "--tag", f"v{version}",
            "--title", f"QuickView {version}", "--note-file", notes]
    for path in paths:
        args += ["--asset", os.path.abspath(path)]
    with tempfile.TemporaryDirectory() as away:
        result = subprocess.run(args, cwd=away, capture_output=True,
                                text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise ReleaseError("the Codeberg release failed (the GitHub one is "
                           "out; make it by hand with tea releases create)"
                           + (f":\n{detail[-1500:]}" if detail else ""))
    say(f"   https://codeberg.org/{CODEBERG_REPO}/releases/tag/v{version}")


def copr(version: str, srpm: str):
    say(f"== Building on Copr ({COPR_PROJECT})")
    run(["copr-cli", "build", COPR_PROJECT, srpm])
    out = run(["copr-cli", "get", COPR_PROJECT], capture=True)
    repos = re.findall(r"^\s+(\S+): (https://\S+)$", out, re.M)
    if not repos:
        raise ReleaseError("could not read the Copr project's repositories")
    with tempfile.TemporaryDirectory() as cache:
        for chroot, url in repos:
            offered = run(["dnf", "repoquery", "-q",
                           f"--setopt=cachedir={cache}",
                           f"--setopt=system_cachedir={cache}",
                           f"--repofrompath=qvcopr,{url}", "--repo=qvcopr",
                           "--qf", "%{version}-%{release}\n", "quickview"],
                          capture=True)
            if not any(v.startswith(f"{version}-1.") for v in offered.split()):
                raise ReleaseError(f"Copr's {chroot} does not offer {version} "
                                   f"(it offers: {offered.split() or 'nothing'})")
            say(f"   {chroot}: serves {version}")


def clean_up():
    """Once all is published, only the RPMs stay here (build/rpm/, and the
    binary one's copy in dist/): the forges, Copr and Zenodo have the rest."""
    say("== Deleting what was published from build/ (only the RPMs stay)")
    for path in CLEANED:
        shutil.rmtree(path, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Release QuickView: changelog, signed tag, signed RPMs "
                    "and files, GitHub and Codeberg releases and Copr build.")
    parser.add_argument("version", help="the new version, e.g. 0.1.3")
    parser.add_argument("--no-zenodo", action="store_true",
                        help="don't upload the deposit to Zenodo (by default it is uploaded and "
                             "published, with the token in $ZENODO_TOKEN or the keyring)")
    parser.add_argument("--zenodo-draft", action="store_true",
                        help="upload it to Zenodo as a draft, not published")
    parser.add_argument("--dry-run", action="store_true",
                        help="check everything and show what would be "
                             "written, changing nothing")
    args = parser.parse_args()
    version = args.version
    today = datetime.date.today()
    zenodo = [sys.executable, os.path.join(ROOT, "tools", "zenodo.py")]
    # Sin token se para aquí, antes de hacer nada, y no al final
    if not args.no_zenodo and not args.dry_run and not zenodo_token():
        say("release: the upload to Zenodo needs a token in $ZENODO_TOKEN or the keyring; "
            "--no-zenodo leaves it out")
        return 1
    try:
        info = preflight(version, args.dry_run)
        with open(SPEC, encoding="utf-8") as fh:
            new_spec = bump_spec(fh.read(), version, today, info["lines"])
        with open(CHANGELOG, encoding="utf-8") as fh:
            new_changelog = bump_changelog(fh.read(), version,
                                           today.isoformat())
        with open(VERSION_FILE, encoding="utf-8") as fh:
            new_version_file = bump_version_file(fh.read(), version)
        if args.dry_run:
            say(f"\n== Would set version.py's VERSION to \"{version}\"")
            say("\n== Would add to quickview.spec:\n")
            say(spec_entry(version, today, info["lines"]).rstrip())
            say(f"\n== Would rename \"## Unreleased\" to \"## {version} — "
                f"{today.isoformat()}\"")
            paths = expected_paths(version)
            say("\n== Would tag, signed, and check the tag:")
            for cmd in tag_commands(info["fpr"], version):
                say("   " + shlex.join(cmd))
            say("\n== Would build and sign the RPMs:")
            say(f"   packaging/build-rpm.sh --sign={info['fpr']}")
            say("\n== Would sign every file, and check it with the "
                "published key:")
            say("   " + shlex.join(
                os.path.relpath(a, ROOT) if a.startswith(ROOT + os.sep) else a
                for a in sign_command(info["fpr"], paths)))
            say("\n== Would collect the deposit for Zenodo:")
            say("   " + shlex.join(["tools/zenodo.py", "collect", "--tag",
                                    f"v{version}"]))
            if not args.no_zenodo:
                how = "as a draft" if args.zenodo_draft else "and publish it"
                say(f"\n== Would upload it to Zenodo, {how}:")
                say("   tools/zenodo.py upload" + ("" if args.zenodo_draft else " --publish"))
            say("\n== Would delete what was published from build/ (only the RPMs stay):")
            say("   " + shlex.join(["rm", "-rf", *(os.path.relpath(d, ROOT) for d in CLEANED)]))
            say("\n== Would attach, on GitHub and on Codeberg:")
            for path in published(paths):
                say("   " + os.path.relpath(path, ROOT))
            say("\n== Would publish these notes (checksums made up):\n")
            fake = {os.path.basename(p): "0" * 64 for p in paths}
            say(release_notes(version, info["current"], info["section"],
                              fake, info["fpr"]))
            say("Dry run: nothing was changed.")
            return 0

        say("== Version bump, commit and tag (local)")
        with open(SPEC, "w", encoding="utf-8") as fh:
            fh.write(new_spec)
        with open(CHANGELOG, "w", encoding="utf-8") as fh:
            fh.write(new_changelog)
        with open(VERSION_FILE, "w", encoding="utf-8") as fh:
            fh.write(new_version_file)
        message = f"Release {version}\n\n" + "\n".join(
            f"- {line}" for line in info["lines"])
        run(["git", "commit", "-q", "-m", message, "--", SPEC, CHANGELOG,
             VERSION_FILE])
        try:
            for cmd in tag_commands(info["fpr"], version):
                run(cmd)
            built = build(info["fpr"], version)
            sign(info["fpr"], built["paths"])
            run([*zenodo, "collect", "--tag", f"v{version}"])
        except ReleaseError:
            say("\nNothing was published. To undo the local release commit "
                "and tag (if it was made):\n"
                f"  git tag -d v{version}; git reset --hard HEAD~1")
            raise

        say("== Publishing")
        run(["git", "push", "-q", "origin", "main"])
        run(["git", "push", "-q", "origin", f"v{version}"])
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(release_notes(version, info["current"], info["section"],
                                   built["files"], info["fpr"]))
            notes = fh.name
        try:
            url = run(["gh", "release", "create", f"v{version}",
                       "-R", GITHUB_REPO, "--title", f"QuickView {version}",
                       "--notes-file", notes, *published(built["paths"])],
                      capture=True)
            say(f"   {url}")
            codeberg(version, notes, published(built["paths"]))
        finally:
            os.unlink(notes)
        verify_download(version, built["files"])
        srpm = next(p for p in built["paths"] if p.endswith(".src.rpm"))
        copr(version, srpm)
        if not args.no_zenodo:
            say("== Zenodo" + (" (a draft, not published)" if args.zenodo_draft else " (published)"))
            run([*zenodo, "upload", *([] if args.zenodo_draft else ["--publish"])])
        clean_up()
        say(f"\nReleased {version}: GitHub ({url}), Codeberg "
            f"(https://codeberg.org/{CODEBERG_REPO}/releases/tag/v{version}) "
            f"and Copr ({COPR_PROJECT}).")
        return 0
    except ReleaseError as exc:
        say(f"\nrelease: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
