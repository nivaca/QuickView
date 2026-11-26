#!/usr/bin/env python3
# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Nicolas Vaughan <nicolasvaughan@proton.me>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Prepara el depósito de una versión en Zenodo, lo sube y, si se pide, lo publica.

    python tools/zenodo.py collect [--tag vX.Y] [--packages]
    python tools/zenodo.py upload [--sandbox] [--new-version-of ID] [--publish] [--dry-run]
    python tools/zenodo.py publish [--sandbox] [ID]

collect reúne en dist/zenodo/ lo que se deposita de la versión (la última etiqueta, o --tag):

- NOMBRE-VERSIÓN-source.tar.gz, el árbol completo de la etiqueta (git archive), con pruebas, documentos y
  empaquetado, que es lo que se preserva;
- con --packages, además los archivos publicados con la versión, los de dist/SHA256SUMS (rueda, AppImage,
  RPM...), cada uno con la firma que ya tenía;
- la firma separada de cada archivo (ARCHIVO.asc), SHA256SUMS de solo esos archivos y su firma, y la clave
  pública (packaging/RPM-GPG-KEY-NOMBRE o, en las aplicaciones de Android, GPG-KEY-NOMBRE.asc).

Antes comprueba la firma de la etiqueta, y después cada firma, como lo haría quien descargue el depósito: en un
GNUPGHOME temporal que solo tiene la clave pública. Si algo no se comprueba, no deja dist/zenodo/.

upload sube dist/zenodo/ a Zenodo (o a sandbox.zenodo.org, con --sandbox) con los metadatos de .zenodo.json, más
la versión, la fecha de la etiqueta, los enlaces a ella en los repositorios y, como descripción, el README.md entero de
la etiqueta, pasado a HTML. Después completa el borrador por la API de registros de Zenodo con lo que la de depósitos
no recibe: los idiomas (las claves "languages" de .zenodo.json), el copyright (el año de la etiqueta y el primer
autor), la dirección del repositorio en GitHub, el lenguaje de programación y el estado del desarrollo (las claves
"programming_language" y "development_status"). Si ya hay en Zenodo un depósito
publicado con el mismo título, hace una versión nueva de él (el DOI de concepto se mantiene); si no, uno nuevo.
Sin --publish deja un borrador y da su dirección, para revisarlo y publicarlo a mano; con --publish lo publica al
final y da su DOI (publicar no se deshace: el DOI queda).

publish publica un borrador que ya está en Zenodo: el de ID, o el que espera con el título de .zenodo.json (por
ejemplo uno que upload dejó sin publicar, que impide hacer la versión siguiente).

El token, con los permisos deposit:write y deposit:actions, se toma de $ZENODO_TOKEN ($ZENODO_SANDBOX_TOKEN con
--sandbox) o, si no está, del llavero del escritorio, donde lo guarda una vez

    secret-tool store --label="Zenodo token" service zenodo

(service zenodo-sandbox, el de sandbox.zenodo.org). check-token dice si hay uno, sin mostrarlo.
"""

from __future__ import annotations

import argparse
import hashlib
import html
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

DESCRIPTION = ("Collect a release's files for Zenodo in dist/zenodo/, signed and checked, upload them, and "
               "publish them if asked.")
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "dist" / "zenodo"
METADATA = ROOT / ".zenodo.json"
SERVERS = {False: ("https://zenodo.org", "ZENODO_TOKEN"), True: ("https://sandbox.zenodo.org", "ZENODO_SANDBOX_TOKEN")}
# El servicio con que se guarda el token en el llavero (secret-tool), si no está en la variable
KEYRING = {False: "zenodo", True: "zenodo-sandbox"}


class Failed(Exception):
    """Something that stops the tool, with what to tell the user."""


# ------------------------------------------------------------------ the project


def public_key() -> Path:
    """The public key published with every release: packaging/RPM-GPG-KEY-NAME or, in the Android apps,
    GPG-KEY-NAME.asc at the top of the repository."""
    found = sorted((ROOT / "packaging").glob("RPM-GPG-KEY-*")) + sorted(ROOT.glob("GPG-KEY-*.asc"))
    if len(found) != 1:
        raise Failed("there must be one public key of the releases, packaging/RPM-GPG-KEY-NAME or GPG-KEY-NAME.asc")
    return found[0]


def project_name() -> str:
    return public_key().name.removeprefix("RPM-GPG-KEY-").removeprefix("GPG-KEY-").removesuffix(".asc")


def signing_key() -> str:
    """The key that signs: $SIGNING_KEY if it is set, or else the one of the published public key, by its
    fingerprint (the signatures are checked with that key, so no other would do)."""
    if os.environ.get("SIGNING_KEY"):
        return os.environ["SIGNING_KEY"]
    done = subprocess.run(["gpg", "--batch", "--with-colons", "--show-keys", str(public_key())],
                          capture_output=True, text=True, check=False)
    fingerprints = [line.split(":")[9] for line in done.stdout.splitlines() if line.startswith("fpr:")]
    if done.returncode != 0 or not fingerprints:
        raise Failed(f"gpg cannot read the public key {public_key().name}")
    # La primera es la de la clave principal; las demás, de sus subclaves
    return fingerprints[0]


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
        return "key" if p.name == public_key().name else "other"

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


# ------------------------------------------------------------------ the README, as the description


def escape(text: str) -> str:
    # Las entidades que ya están (el &lt; de una dirección) se dejan como están
    text = re.sub(r"&(?!#?\w+;)", "&amp;", text)
    return text.replace("<", "&lt;").replace(">", "&gt;")


def inline(text: str, base: str | None) -> str:
    """One block's text in HTML: code, links (relative ones made absolute with BASE; <URL> and <EMAIL> too), bold
    and italics. Images are left out: Zenodo doesn't take <img>."""
    kept = []

    def keep(fragment: str) -> str:
        # Lo ya hecho HTML se aparta, para que ni el escape ni los ** lo toquen
        kept.append(fragment)
        return f"\x00{len(kept) - 1}\x01"

    text = re.sub(r"(`+)(.+?)\1", lambda m: keep(f"<code>{html.escape(m.group(2).strip(), quote=False)}</code>"),
                  text)
    text = re.sub(r"<((?:https?|mailto):[^<>\s]+)>",
                  lambda m: keep(f'<a href="{escape(m.group(1))}">{escape(m.group(1).removeprefix("mailto:"))}</a>'),
                  text)
    text = re.sub(r"<([^<>\s@]+@[^<>\s@]+\.[a-z]+)>",
                  lambda m: keep(f'<a href="mailto:{escape(m.group(1))}">{escape(m.group(1))}</a>'), text)
    text = escape(text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)

    def link(m: re.Match) -> str:
        label, url = m.groups()
        if url.startswith("#"):
            return label
        if not re.match(r"[a-z]+:", url) and base:
            url = base + re.sub(r"^(\./)+", "", url)
        return f'<a href="{url}">{label}</a>'

    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", text)
    while "\x00" in text:
        text = re.sub(r"\x00(\d+)\x01", lambda m: kept[int(m.group(1))], text)
    return text.strip()


# La línea que lleva a los README en otras lenguas ("*Leer en español: [README_es.md](README_es.md).*",
# "*(Español: [README_es.md](...); Latine: [README_la.md](...))*"): en Zenodo no lleva a ninguna parte
OTHER_READMES = re.compile(r"^\s*[*_].*\]\([^)\s]*README[._][A-Za-z]{2}(?:[-_][A-Za-z]{2,4})?\.md\).*[*_]\s*$")
# Secciones que no van en la descripción: las capturas, cuyas imágenes Zenodo no muestra
LEFT_OUT = re.compile(r"screenshots?", re.IGNORECASE)


def description_markdown(text: str) -> str:
    """The README without what makes no sense in Zenodo's description: the line that points to the README in
    other languages and the Screenshots section (down to the next heading of its level or higher)."""
    lines = text.splitlines()
    kept, skipping, in_fence, i = [], None, False, 0
    fence = re.compile(r"^\s*(```+|~~~+)")
    while i < len(lines):
        line, heading, width = lines[i], None, 1
        if fence.match(line):
            in_fence = not in_fence
        elif not in_fence:
            if m := re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", line):
                heading = len(m.group(1)), m.group(2)
            elif (line.strip() and i + 1 < len(lines) and re.match(r"^(=+|-+)\s*$", lines[i + 1])
                  and not re.match(r"^\s{0,3}([-*+]|\d+[.)])\s+", line)):
                heading, width = (1 if lines[i + 1].startswith("=") else 2, line.strip()), 2
        if heading:
            level, title = heading
            if skipping is not None and level <= skipping:
                skipping = None
            if skipping is None and LEFT_OUT.fullmatch(title.strip()):
                skipping = level
        if skipping is None and not (not in_fence and OTHER_READMES.match(line)):
            kept.extend(lines[i:i + width])
        i += width
    return "\n".join(kept) + "\n"


def markdown_html(text: str, base: str | None = None) -> str:
    """A README in Markdown as the HTML Zenodo accepts in a description (p, ul, ol, li, table, pre, code, a,
    strong, em, blockquote: no headings nor images, so a heading is a paragraph in bold, and a block of HTML is
    left with its text only)."""
    lines = text.expandtabs(4).splitlines()
    blocks, i = [], 0
    item = re.compile(r"^\s{0,3}([-*+]|\d+[.)])\s+")
    rule = re.compile(r"^(=+|-+)\s*$")
    fence = re.compile(r"^\s*(```+|~~~+)")

    def code_block(code: list[str]) -> str:
        while code and not code[-1].strip():
            code.pop()
        return f"<pre><code>{html.escape(chr(10).join(code), quote=False)}</code></pre>"

    def fenced(start: int) -> tuple[list[str], int]:
        # Las líneas de un bloque ``` que empieza en START (sin la sangría de la marca), y la línea que sigue
        mark = fence.match(lines[start])
        indent, ticks = len(lines[start]) - len(lines[start].lstrip()), mark.group(1)
        end = start + 1
        while end < len(lines) and not lines[end].strip().startswith(ticks):
            end += 1
        return [l[indent:] if l[:indent].isspace() else l.lstrip() for l in lines[start + 1:end]], end + 1

    def starts_block(n: int) -> bool:
        line = lines[n]
        return (not line.strip() or bool(item.match(line)) or bool(fence.match(line))
                or line.startswith(("#", "|", ">", "<"))
                or (n + 1 < len(lines) and bool(rule.match(lines[n + 1])) and bool(line.strip())))

    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
        elif fence.match(line):
            code, i = fenced(i)
            blocks.append(code_block(code))
        elif line.startswith("    "):
            end = i
            while end < len(lines) and (lines[end].startswith("    ") or not lines[end].strip()):
                end += 1
            blocks.append(code_block([l[4:] for l in lines[i:end]]))
            i = end
        elif re.match(r"^</?[a-zA-Z][^>]*>", line) and not re.match(r"^<(?:https?|mailto):|^<[^<>\s@]+@", line):
            # Un bloque de HTML (las imágenes centradas de un README): solo su texto, sin las etiquetas
            end = i
            while end < len(lines) and lines[end].strip():
                end += 1
            text_only = " ".join(re.sub(r"<[^>]*>", " ", " ".join(lines[i:end])).split())
            if text_only:
                blocks.append(f"<p>{inline(text_only, base)}</p>")
            i = end
        elif m := re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", line):
            blocks.append(f"<p><strong>{inline(m.group(2), base)}</strong></p>")
            i += 1
        elif i + 1 < len(lines) and rule.match(lines[i + 1]) and not item.match(line):
            blocks.append(f"<p><strong>{inline(line.strip(), base)}</strong></p>")
            i += 2
        elif line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in re.split(r"(?<!\\)\|", lines[i].strip().strip("|"))]
                if not all(re.fullmatch(r":?-+:?", c) for c in cells):
                    rows.append([c.replace("\\|", "|") for c in cells])
                i += 1
            head, *body = rows or [[]]
            blocks.append("<table><thead><tr>" + "".join(f"<th>{inline(c, base)}</th>" for c in head)
                          + "</tr></thead><tbody>"
                          + "".join("<tr>" + "".join(f"<td>{inline(c, base)}</td>" for c in r) + "</tr>"
                                    for r in body) + "</tbody></table>")
        elif line.startswith(">"):
            quoted = []
            while i < len(lines) and lines[i].startswith(">"):
                quoted.append(lines[i][1:].strip())
                i += 1
            blocks.append(f"<blockquote><p>{inline(' '.join(quoted), base)}</p></blockquote>")
        elif m := item.match(line):
            tag = "ul" if m.group(1) in "-*+" else "ol"
            # Cada elemento, en partes: texto (una lista de líneas) o un bloque de código ya en HTML
            items: list[list] = []
            while i < len(lines):
                if m := item.match(lines[i]):
                    items.append([[lines[i][m.end():].strip()]])
                    i += 1
                elif lines[i].strip() and lines[i].startswith(" ") and fence.match(lines[i]):
                    code, i = fenced(i)
                    items[-1] += [code_block(code), []]
                elif lines[i].strip() and lines[i].startswith(" "):
                    items[-1][-1].append(lines[i].strip())
                    i += 1
                elif (not lines[i].strip() and i + 1 < len(lines)
                      and (item.match(lines[i + 1]) or lines[i + 1].startswith("  "))):
                    i += 1
                else:
                    break
            blocks.append(f"<{tag}>" + "".join(
                "<li>" + " ".join(part if isinstance(part, str) else inline(" ".join(part), base)
                                  for part in parts if part) + "</li>" for parts in items) + f"</{tag}>")
        else:
            paragraph = [line.strip()]
            i += 1
            while i < len(lines) and not starts_block(i):
                paragraph.append(lines[i].strip())
                i += 1
            text_html = inline(" ".join(paragraph), base)
            # (un párrafo de solo una imagen queda vacío)
            if text_html:
                blocks.append(f"<p>{text_html}</p>")
    return "\n".join(blocks)


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


def repository() -> tuple[str, str] | None:
    """The repository's address, GitHub's if it is on GitHub, or else Codeberg's, and the path of a tag in it
    ("tree/{tag}" or "src/tag/{tag}"); None if it is on neither."""
    found = {}
    for line in git("remote", "-v").splitlines():
        m = re.search(r"(codeberg\.org|github\.com)[:/]+([^/\s]+/[^/\s]+?)(?:\.git)?/?\s+\(push\)$", line)
        if m:
            found.setdefault(m.group(1), f"https://{m.group(1)}/{m.group(2)}")
    if "github.com" in found:
        return found["github.com"], "blob/{tag}/"
    if "codeberg.org" in found:
        return found["codeberg.org"], "src/tag/{tag}/"
    return None


# Lo que la API de depósitos no recibe: va después, por la de registros (InvenioRDM)
RECORD_ONLY = ("languages", "programming_language", "development_status")


def metadata(version: str) -> tuple[dict, dict]:
    """The deposit's metadata: .zenodo.json, with the version, the tag's date, the links to the tag and the
    README of the tag as the description; and what only the records API takes, for record_fields()."""
    if not METADATA.is_file():
        raise Failed("there is no .zenodo.json with the deposit's metadata")
    data = json.loads(METADATA.read_text(encoding="utf-8"))
    tag = next((t for t in (f"v{version}", version) if git("tag", "--list", t)), None)
    if not tag:
        raise Failed(f"there is no tag of version {version}")
    extra = {key: data.pop(key) for key in RECORD_ONLY if key in data}
    data["version"] = version
    data["publication_date"] = git("log", "-1", "--format=%cs", f"{tag}^{{commit}}")
    links = repository_links(tag)
    known = {r.get("identifier") for r in data.get("related_identifiers", [])}
    data["related_identifiers"] = data.get("related_identifiers", []) + [l for l in links if l["identifier"] not in known]
    repo = repository()
    if git("ls-tree", "--name-only", tag, "README.md"):
        base = f"{repo[0]}/{repo[1].format(tag=tag)}" if repo else None
        data["description"] = markdown_html(description_markdown(git("show", f"{tag}:README.md")), base)
    if extra.get("languages"):
        # (la API de depósitos recibe uno solo: el primero; los demás, record_fields())
        data["language"] = extra["languages"][0]
    if data.get("creators"):
        name = data["creators"][0]["name"]
        family, _, given = name.partition(", ")
        extra["copyright"] = f"Copyright © {data['publication_date'][:4]} {f'{given} {family}' if given else name}"
    if repo:
        extra["repository"] = repo[0]
    return data, extra


# Con "application/json", Zenodo da los registros en el formato de la API de depósitos, sin languages ni copyright
# ni custom_fields: el de InvenioRDM hay que pedirlo
RDM_JSON = "application/vnd.inveniordm.v1+json"


def languages(value) -> list[str]:
    # "programming_language" puede ser uno ("python") o varios (["kotlin", "c++"])
    return [value] if isinstance(value, str) else list(value or [])


def missing_fields(record: dict, extra: dict) -> list[str]:
    """Those of EXTRA's fields that RECORD (as the records API gives it, in RDM_JSON) doesn't have."""
    meta, custom = record.get("metadata") or {}, record.get("custom_fields") or {}
    have = {
        "languages": [l.get("id") for l in meta.get("languages") or []] == list(extra.get("languages") or []),
        "copyright": meta.get("copyright") == extra.get("copyright"),
        "repository": custom.get("code:codeRepository") == extra.get("repository"),
        "programming_language": [l.get("id") for l in custom.get("code:programmingLanguage") or []]
                                == languages(extra.get("programming_language")),
        "development_status": (custom.get("code:developmentStatus") or {}).get("id") == extra.get("development_status"),
    }
    return [key for key in extra if not have.get(key, True)]


def record_fields(record: dict, extra: dict) -> dict:
    """RECORD (a draft as the records API gives it) with the fields of EXTRA that the deposit API doesn't take:
    the languages, the copyright and the software's fields (repository, programming language, status)."""
    meta = record.setdefault("metadata", {})
    custom = record.get("custom_fields") or {}
    record["custom_fields"] = custom
    if extra.get("languages"):
        meta["languages"] = [{"id": code} for code in extra["languages"]]
    if extra.get("copyright"):
        meta["copyright"] = extra["copyright"]
    if extra.get("repository"):
        custom["code:codeRepository"] = extra["repository"]
    if extra.get("programming_language"):
        custom["code:programmingLanguage"] = [{"id": code} for code in languages(extra["programming_language"])]
    if extra.get("development_status"):
        custom["code:developmentStatus"] = {"id": extra["development_status"]}
    # Solo lo que se puede escribir; links, revision_id, etc. son de lectura
    return {k: record[k] for k in ("access", "files", "metadata", "custom_fields", "pids") if k in record}


class Zenodo:
    """The few calls of Zenodo's deposit API that a draft needs (https://developers.zenodo.org/)."""

    def __init__(self, base: str, token: str):
        self.base, self.token = base.rstrip("/"), token

    def call(self, method: str, url: str, body: dict | None = None, data=None, size: int | None = None,
             accept: str = "application/json"):
        if not url.startswith("http"):
            url = f"{self.base}/api/{url}"
        headers = {"Authorization": f"Bearer {self.token}", "Accept": accept}
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


def publish_draft(api: Zenodo, draft_id) -> dict:
    """Publishes the draft DRAFT_ID; the published deposition (with its DOI)."""
    return api.call("POST", f"deposit/depositions/{draft_id}/actions/publish")


def waiting_draft(api: Zenodo, title: str) -> dict:
    """The one draft of TITLE that waits to be published."""
    mine = [d for d in api.depositions() if d.get("metadata", {}).get("title") == title or d.get("title") == title]
    waiting = [d for d in mine if not d.get("submitted")]
    if not waiting:
        raise Failed(f"there is no draft of {title} on Zenodo to publish")
    if len(waiting) > 1:
        raise Failed(f"several drafts of {title} wait on Zenodo; say which with its ID")
    return waiting[0]


def published(done: dict, base: str) -> str:
    """What to say of a published deposition: its DOI and address."""
    doi = done.get("doi") or done.get("metadata", {}).get("doi") or "?"
    url = done.get("links", {}).get("record_html") or done.get("links", {}).get("html") or \
        f"{base}/records/{done.get('id')}"
    return f"{doi}  {url}"


def publish(sandbox: bool, draft_id: str | None) -> str:
    """Publishes a draft already on Zenodo (DRAFT_ID, or the one waiting with the title of .zenodo.json)."""
    base, _variable = SERVERS[sandbox]
    api = Zenodo(base, token(sandbox))
    if not draft_id:
        title = json.loads(METADATA.read_text(encoding="utf-8"))["title"]
        draft_id = waiting_draft(api, title)["id"]
    return published(publish_draft(api, draft_id), base)


def keyring(service: str) -> str | None:
    """The token kept in the desktop keyring for SERVICE (secret-tool lookup service SERVICE), or None if there is
    no secret-tool, no keyring or no such entry."""
    if not shutil.which("secret-tool"):
        return None
    try:
        done = subprocess.run(["secret-tool", "lookup", "service", service], capture_output=True, text=True,
                              timeout=120, check=False)
    except subprocess.TimeoutExpired:
        # (el llavero cerrado pide la contraseña; si nadie la da, se sigue sin token)
        return None
    return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else None


def token(sandbox: bool) -> str:
    """The Zenodo token: $ZENODO_TOKEN ($ZENODO_SANDBOX_TOKEN), or else the one in the keyring."""
    base, variable = SERVERS[sandbox]
    found, where = os.environ.get(variable), f"${variable}"
    if not found:
        found, where = keyring(KEYRING[sandbox]), f"the keyring (service {KEYRING[sandbox]})"
    if not found:
        raise Failed(f"there is no Zenodo token in ${variable} nor in the keyring; make one at "
                     f"{base}/account/settings/applications/ (with deposit:write and deposit:actions) and keep it "
                     f'with: secret-tool store --label="Zenodo token" service {KEYRING[sandbox]}')
    # Un token de Zenodo es ASCII, sin espacios; otra cosa (el "…" de un ejemplo copiado) no llegaría a la cabecera
    if not found.isascii() or not found.isprintable() or any(c.isspace() for c in found):
        raise Failed(f"the token in {where} is not a Zenodo token (it has spaces or characters that are not "
                     f"ASCII); put there the token made at {base}/account/settings/applications/")
    return found


def upload(sandbox: bool, new_version_of: str | None, dry_run: bool, publish: bool = False) -> str:
    """dist/zenodo/ to a draft on Zenodo, published with PUBLISH; the draft's address, or the DOI and address of
    what was published (with DRY_RUN, nothing sent and "")."""
    version, files = check_deposit()
    data, extra = metadata(version)
    base, _variable = SERVERS[sandbox]
    print(f"Deposit of {data['title']} {version} on {base}, {'to be published' if publish else 'as a draft'}:")
    for path in files:
        print(f"  {path.name}  ({path.stat().st_size:,} bytes)")
    print(json.dumps(data, indent=2, ensure_ascii=False))
    print("Then, through the records API:")
    print(json.dumps(extra, indent=2, ensure_ascii=False))
    if dry_run:
        return ""
    api = Zenodo(base, token(sandbox))
    draft = prepare_draft(api, data["title"], new_version_of)
    for path in files:
        print(f"  uploading {path.name}", flush=True)
        api.upload(draft, path)
    api.call("PUT", f"deposit/depositions/{draft['id']}", body={"metadata": data})
    url = draft["links"].get("html") or f"{base}/uploads/{draft['id']}"
    if extra:
        try:
            record = api.call("GET", f"records/{draft['id']}/draft", accept=RDM_JSON)
            saved = api.call("PUT", f"records/{draft['id']}/draft", body=record_fields(record, extra), accept=RDM_JSON)
            # Se vuelve a leer: lo que Zenodo no guardó se dice, en vez de darlo por hecho
            missing = missing_fields(api.call("GET", f"records/{draft['id']}/draft", accept=RDM_JSON), extra)
        except Failed as e:
            raise Failed(f"{e}\nThe draft is there with its files, but without {', '.join(extra)}: add them by hand "
                         f"at {url}") from None
        if missing:
            errors = f" ({json.dumps(saved['errors'], ensure_ascii=False)})" if saved and saved.get("errors") else ""
            raise Failed(f"Zenodo did not keep {', '.join(missing)} in the draft{errors}; add them by hand at {url}")
    if publish:
        # (solo con todo en el borrador: lo que falte se dice antes, y entonces no se publica)
        return published(publish_draft(api, draft["id"]), base)
    return url


# ------------------------------------------------------------------ main


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="tools/zenodo.py", description=DESCRIPTION)
    commands = parser.add_subparsers(dest="command", required=True)
    c = commands.add_parser("collect", help="put the deposit of a release in dist/zenodo/, signed and checked")
    c.add_argument("--tag", help="the release's tag (default: the last one)")
    c.add_argument("--packages", action="store_true",
                   help="also the files published with the release (those of dist/SHA256SUMS)")
    u = commands.add_parser("upload", help="upload dist/zenodo/ to Zenodo as a draft, published with --publish")
    u.add_argument("--sandbox", action="store_true", help="to sandbox.zenodo.org, to try it")
    u.add_argument("--new-version-of", metavar="ID", help="the deposit this is a new version of (default: the one "
                                                          "with the same title)")
    u.add_argument("--publish", action="store_true", help="publish it at the end (a DOI, which cannot be undone)")
    u.add_argument("-n", "--dry-run", action="store_true", help="only check dist/zenodo/ and show what would go")
    p = commands.add_parser("publish", help="publish a draft already on Zenodo (ID, or the one waiting with the "
                                            "title of .zenodo.json)")
    p.add_argument("id", nargs="?", help="the draft's ID")
    p.add_argument("--sandbox", action="store_true", help="on sandbox.zenodo.org")
    t = commands.add_parser("check-token", help="say whether there is a Zenodo token ($ZENODO_TOKEN or the "
                                                "keyring), without showing it")
    t.add_argument("--sandbox", action="store_true", help="the token of sandbox.zenodo.org")
    args = parser.parse_args(argv)
    try:
        if args.command == "collect":
            files = collect(args.tag, args.packages)
            print(f"In {OUT.relative_to(ROOT)}/, signed and checked with the published key:")
            for path in files:
                print(f"  {path.name}")
        elif args.command == "check-token":
            token(args.sandbox)
            print("There is a Zenodo token.")
        elif args.command == "publish":
            print(f"Published: {publish(args.sandbox, args.id)}")
        else:
            url = upload(args.sandbox, args.new_version_of, args.dry_run, args.publish)
            if url and args.publish:
                print(f"\nPublished: {url}")
            elif url:
                print(f"\nDraft ready, NOT published. Review it, then publish it there:\n  {url}")
    except Failed as e:
        print(f"zenodo.py: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
