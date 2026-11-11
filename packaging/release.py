#!/usr/bin/env python3
# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Nicolas Vaughan <nivaca@fastmail.com>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Makes a QuickView release, from the changelog to Copr, in one go.

    packaging/release.py VERSION [--dry-run]

What is released is what CHANGELOG.md lists under "## Unreleased". In
order, stopping at the first thing that fails:

1. Checks, changing nothing: on main, clean, in step with origin; VERSION
   new and higher than the spec's; something under Unreleased; gh and
   copr-cli logged in; rpmsign present; the signing key usable; the tests
   and the lint passing.
2. Bumps packaging/quickview.spec (Version, Release 1, a %changelog entry
   made from the Unreleased headlines) and renames "Unreleased" to
   "VERSION — date"; commits "Release VERSION" and tags vVERSION, locally.
3. Builds the RPMs with build-rpm.sh --sign. The key is the one whose
   public half is packaging/RPM-GPG-KEY-quickview, by fingerprint — never
   another key with the same name. gpg asks for its passphrase.
   Up to here nothing has left this machine; if this fails, the script
   says how to undo the local commit and tag.
4. Pushes main and the tag; publishes the GitHub release with both RPMs
   and the key, and notes made from the changelog, with checksums.
5. Downloads the release back and checks its signatures against its own
   key file, the way a user's dnf would.
6. Builds the source RPM on Copr, waits, and checks that every chroot's
   repository serves the new version.

--dry-run does step 1 and prints what step 2 would write and the notes.
"""

import argparse
import datetime
import glob
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join(ROOT, "packaging", "quickview.spec")
CHANGELOG = os.path.join(ROOT, "CHANGELOG.md")
KEY_FILE = os.path.join(ROOT, "packaging", "RPM-GPG-KEY-quickview")
GITHUB_REPO = "nivaca/QuickView"
COPR_PROJECT = "nivaca/quickview"
AUTHOR = "Nicolas Vaughan <nivaca@fastmail.com>"
UNRELEASED = "## Unreleased"


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
    SHA-256; the first one ending in .x86_64.rpm is the one to install."""
    rpm = next(name for name in files if name.endswith(".x86_64.rpm"))
    srpm = next(name for name in files if name.endswith(".src.rpm"))
    since = (f"Changes since [{previous}](https://github.com/{GITHUB_REPO}"
             f"/releases/tag/v{previous}).\n\n") if previous else ""
    rows = "\n".join(f"| `{name}` | `{digest}` |"
                     for name, digest in files.items())
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

**Any distribution:** clone the repository and run `./install.sh`. If you used `install.sh` before, run `./uninstall.sh` before installing the package.

## Files

| File | SHA-256 |
|---|---|
{rows}

QuickView is by Mustapha Alioglou; this fork is maintained by Nicolas Vaughan. Licensed GPL-3.0-or-later.
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
    for tool, hint in (("git", "git"), ("gh", "gh"), ("rpmbuild", "rpm-build"),
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
    owner = COPR_PROJECT.split("/")[0]
    if run(["copr-cli", "whoami"], capture=True) != owner:
        raise ReleaseError(f"copr-cli is not logged in as {owner}")
    fpr = key_fingerprint()
    check_signing_key(fpr)
    say(f"   {version} after {current}; {len(lines)} change(s); key {fpr}")

    say("== Tests and lint")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    tests = subprocess.run([python_for_tests(), "-m", "unittest", "discover",
                            "-s", "tests", "-t", "."], cwd=ROOT, env=env,
                           capture_output=True, text=True)
    summary = [line for line in tests.stderr.splitlines()
               if line.startswith(("Ran ", "OK", "FAILED"))]
    say("   " + " | ".join(summary))
    if tests.returncode != 0:
        raise ReleaseError("the tests fail:\n" + tests.stderr[-3000:])
    if shutil.which("uvx"):
        run(["uvx", "ruff", "check", "--select", "F", "-q", "."])
        say("   lint ok")
    else:
        say("   (uvx not found: lint skipped)")
    return {"current": current, "section": section, "lines": lines,
            "fpr": fpr}


def build(fpr: str) -> dict:
    say("== Building and signing (gpg asks for the key's passphrase)")
    run([os.path.join(ROOT, "packaging", "build-rpm.sh"), f"--sign={fpr}"])
    found = sorted(glob.glob(os.path.join(ROOT, "build", "rpm", "RPMS", "*", "*.rpm"))
                   + glob.glob(os.path.join(ROOT, "build", "rpm", "SRPMS", "*.rpm")))
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
            run(["rpmkeys", *check, "-K", path], capture=True)
            say(f"   {name}: signature OK, checksum matches")


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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Release QuickView: changelog, tag, signed RPMs, "
                    "GitHub release and Copr build.")
    parser.add_argument("version", help="the new version, e.g. 0.1.3")
    parser.add_argument("--dry-run", action="store_true",
                        help="check everything and show what would be "
                             "written, changing nothing")
    args = parser.parse_args()
    version = args.version
    today = datetime.date.today()
    try:
        info = preflight(version, args.dry_run)
        with open(SPEC, encoding="utf-8") as fh:
            new_spec = bump_spec(fh.read(), version, today, info["lines"])
        with open(CHANGELOG, encoding="utf-8") as fh:
            new_changelog = bump_changelog(fh.read(), version,
                                           today.isoformat())
        if args.dry_run:
            say("\n== Would add to quickview.spec:\n")
            say(spec_entry(version, today, info["lines"]).rstrip())
            say(f"\n== Would rename \"## Unreleased\" to \"## {version} — "
                f"{today.isoformat()}\"")
            say("\n== Would publish these notes (checksums made up):\n")
            fake = {f"quickview-{version}-1.fc45.x86_64.rpm": "0" * 64,
                    f"quickview-{version}-1.fc45.src.rpm": "0" * 64}
            say(release_notes(version, info["current"], info["section"],
                              fake, info["fpr"]))
            say("Dry run: nothing was changed.")
            return 0

        say("== Version bump, commit and tag (local)")
        with open(SPEC, "w", encoding="utf-8") as fh:
            fh.write(new_spec)
        with open(CHANGELOG, "w", encoding="utf-8") as fh:
            fh.write(new_changelog)
        message = f"Release {version}\n\n" + "\n".join(
            f"- {line}" for line in info["lines"])
        run(["git", "commit", "-q", "-m", message, "--", SPEC, CHANGELOG])
        run(["git", "tag", "-a", f"v{version}", "-m", f"QuickView {version}"])
        try:
            built = build(info["fpr"])
        except ReleaseError:
            say("\nNothing was published. To undo the local release commit "
                "and tag:\n"
                f"  git tag -d v{version} && git reset --hard HEAD~1")
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
                       "--notes-file", notes, *built["paths"], KEY_FILE],
                      capture=True)
        finally:
            os.unlink(notes)
        say(f"   {url}")
        verify_download(version, built["files"])
        srpm = next(p for p in built["paths"] if p.endswith(".src.rpm"))
        copr(version, srpm)
        say(f"\nReleased {version}: GitHub ({url}) and Copr ({COPR_PROJECT}).")
        return 0
    except ReleaseError as exc:
        say(f"\nrelease: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
