# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Mustapha Alioglou
# Copyright (C) 2026 Nicolas Vaughan <nivaca@fastmail.com>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""LibreOffice, from the distro or Flathub, run headless in a jail."""

from .base import (
    _rewound,
)
from .pdf import (
    render_pdf,
)


# The distro's own LibreOffice first, then the Flathub one. A "flatpak:"
# entry names an app ID: its files and the runtime it was built against
# are found on disk (no `flatpak` command is run), bound into the jail
# read-only by the daemon (sandbox._office_suite_binds), and run there in
# a nested jail laid out the way Flatpak lays one out. An AppImage is still
# not found: it is one opaque file that mounts itself, which a jail with no
# FUSE cannot do.
OFFICE_SUITES = (
    "/usr/bin/soffice",
    "/usr/lib/libreoffice/program/soffice",
    "/usr/lib64/libreoffice/program/soffice",
    "flatpak:org.libreoffice.LibreOffice",
)


# Inside the daemon's 20 s inactivity watchdog, with room left over for the
# built-in layout to run when this gives up.
OFFICE_SUITE_TIMEOUT = 12


OFFICE_SUITE_MAX_BYTES = 64 * 1024 * 1024


# Where the daemon binds a Flatpak suite inside the worker's jail: app/ and
# runtime/ are the two trees' files/ directories, user-fonts/ holds the
# user's own fonts (system fonts are already there, under /usr).
FLATPAK_SUITE_ROOT = "/run/quickview/libreoffice"


_SOFFICE = ("libreoffice", "program", "soffice")


def _flatpak_installations() -> tuple:
    """The per-user installation first, as `flatpak` itself searches."""
    import os

    data = os.environ.get("XDG_DATA_HOME") or os.path.expanduser(
        "~/.local/share")
    return (os.path.join(data, "flatpak"), "/var/lib/flatpak")


def flatpak_suite(app_id: str):
    """Host side: (app files, runtime files) of an installed Flatpak, or None.

    Read straight from the installation directories, resolved to real
    paths so an update that swaps the "active" link mid-preview cannot
    pull a tree out from under a running conversion. The runtime is the
    one the app's metadata names, from whichever installation has it — a
    per-user app on a system-wide runtime is the common case.
    """
    import configparser
    import os

    installs = _flatpak_installations()
    for inst in installs:
        app = os.path.join(inst, "app", app_id, "current", "active")
        meta = configparser.ConfigParser(interpolation=None, strict=False)
        try:
            with open(os.path.join(app, "metadata"), encoding="utf-8") as fh:
                meta.read_file(fh)
            ref = meta["Application"]["runtime"]
        except (OSError, KeyError, configparser.Error, UnicodeDecodeError):
            continue
        files = os.path.join(app, "files")
        if not os.access(os.path.join(files, *_SOFFICE), os.X_OK):
            continue
        for rt_inst in installs:
            runtime = os.path.join(rt_inst, "runtime", ref, "active", "files")
            if os.path.isdir(os.path.join(runtime, "lib")):
                return os.path.realpath(files), os.path.realpath(runtime)
    return None


def _user_fonts() -> list:
    """(real path, name) for each entry of the user's font directory.

    Entries are commonly symlinks to a fonts collection elsewhere in the
    home directory, which a bind of the directory itself would carry into
    the jail as links to nowhere — so each is bound at its real path.
    """
    import os

    data = os.environ.get("XDG_DATA_HOME") or os.path.expanduser(
        "~/.local/share")
    base = os.path.join(data, "fonts")
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return []
    found = []
    for name in names:
        real = os.path.realpath(os.path.join(base, name))
        if os.path.exists(real):
            found.append((real, name))
    return found


def _suite():
    """(soffice, flatpak) for the first usable entry in OFFICE_SUITES.

    flatpak is None for a distro install, and otherwise (app files,
    runtime files, user fonts) as the caller can see them: the jail's
    bind mounts inside a worker, the installation itself on the host.
    """
    import os

    for entry in OFFICE_SUITES:
        if not entry.startswith("flatpak:"):
            if os.access(entry, os.X_OK):
                return entry, None
            continue
        app = os.path.join(FLATPAK_SUITE_ROOT, "app")
        if os.access(os.path.join(app, *_SOFFICE), os.X_OK):  # in the jail
            fonts = os.path.join(FLATPAK_SUITE_ROOT, "user-fonts")
            return os.path.join(app, *_SOFFICE), (
                app, os.path.join(FLATPAK_SUITE_ROOT, "runtime"),
                [(fonts, "")] if os.path.isdir(fonts) else [])
        trees = flatpak_suite(entry[len("flatpak:"):])
        if trees:  # on the host
            return os.path.join(trees[0], *_SOFFICE), (*trees, _user_fonts())
    return "", None


def office_suite() -> str:
    """Path of a LibreOffice the jail can run, or "" when there is none.

    Also asked by the daemon, whose office cache key changes with the answer:
    installing or removing LibreOffice must not leave pages from the other
    engine on screen.
    """
    return _suite()[0]


def flatpak_suite_binds(root: str = FLATPAK_SUITE_ROOT) -> list:
    """bwrap flags that make a Flatpak suite runnable from inside a jail.

    Empty unless the suite office_suite() picks is a Flatpak: a distro
    LibreOffice is under /usr, which every jail has already.
    """
    import os

    soffice, flatpak = _suite()
    if not flatpak:
        return []
    app, runtime, fonts = flatpak
    flags = ["--ro-bind", app, os.path.join(root, "app"),
             "--ro-bind", runtime, os.path.join(root, "runtime")]
    for src, name in fonts:
        flags += ["--ro-bind", src, os.path.join(root, "user-fonts", name)]
    return flags


def suite_command(workdir: str, args: list) -> list:
    """The command that runs LibreOffice headless on args, or [] for none.

    workdir is a private directory every path in args lies under: it holds
    the throwaway user profile, and for a Flatpak suite it is the only
    thing the nested jail can write. That jail is Flatpak's own layout —
    the runtime as /usr, the app as /app — with no network, no host
    filesystem beyond fonts. It nests inside the worker's jail, and runs on
    the host the same way when a test calls this outside one.
    """
    import os
    import shutil

    soffice, flatpak = _suite()
    if not soffice:
        return []
    flags = ["--headless", "--norestore", "--nologo", "--nolockcheck",
             "--nodefault", "-env:UserInstallation=file://%s/profile" % workdir]
    if not flatpak:
        return [soffice, *flags, *args]
    bwrap = shutil.which("bwrap", path="/usr/bin:/bin")
    if not bwrap:
        return []
    app, runtime, fonts = flatpak
    # The runtime's fontconfig reads this; Flatpak writes one per sandbox.
    # Empty is enough — the font directories themselves are configured in
    # the runtime — and saves an error on stderr for every conversion.
    font_dirs = os.path.join(workdir, "font-dirs.xml")
    with open(font_dirs, "w") as fh:
        fh.write("<?xml version=\"1.0\"?>\n<fontconfig></fontconfig>\n")
    jail = [
        bwrap,
        "--unshare-all", "--cap-drop", "ALL", "--die-with-parent",
        "--clearenv",
        "--ro-bind", runtime, "/usr",
        "--ro-bind", app, "/app",
        "--symlink", "usr/lib", "/lib",
        "--symlink", "usr/lib64", "/lib64",
        "--symlink", "usr/bin", "/bin",
        "--symlink", "usr/sbin", "/sbin",
        "--ro-bind", os.path.join(runtime, "etc"), "/etc",
        "--proc", "/proc",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
        "--bind", workdir, workdir,
        "--ro-bind-try", "/usr/share/fonts", "/run/host/fonts",
        "--ro-bind", font_dirs, "/run/host/font-dirs.xml",
    ]
    for src, name in fonts:
        jail += ["--ro-bind", src,
                 os.path.join("/run/host/user-fonts", name).rstrip("/")]
    jail += [
        "--setenv", "HOME", workdir,
        "--setenv", "TMPDIR", workdir,
        "--setenv", "PATH", "/app/bin:/usr/bin",
        "--setenv", "SAL_USE_VCLPLUGIN", "svp",
        # Not the app metadata's LIBO_FLATPAK=1: it switches on the desktop
        # integration (portals, /.flatpak-info) a real Flatpak sandbox has
        # and this one does not, and soffice then exits 1 without a word.
        "/app/" + "/".join(_SOFFICE),
    ]
    return [*jail, *flags, *args]


# ODF packages name their type in a "mimetype" member.
_ODF_SUITE_KINDS = {
    b"application/vnd.oasis.opendocument.text": ".odt",
    b"application/vnd.oasis.opendocument.presentation": ".odp",
}


# The legacy binary formats share one container, the OLE2 compound file,
# and differ in the name of the main stream inside it. "Book" is Excel 5/95.
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


_OLE_SUITE_KINDS = (
    ("WordDocument", ".doc"),
    ("PowerPoint Document", ".ppt"),
    ("Workbook", ".xls"),
    ("Book", ".xls"),
)


def _office_suite_kind(fh) -> str:
    """The extension LibreOffice should see, or "" to leave it to Qt.

    Word-processor documents and slide decks, in their current and legacy
    formats, legacy Excel workbooks and RTF. Current spreadsheets are not
    sent: they have the sheets view, and come here only when that view has
    already failed. Decided from the content, not the name, which the
    file's owner chose.
    """
    import zipfile

    fh.seek(0)  # is_zipfile leaves the position at the end before 3.13
    head = fh.read(8)
    fh.seek(0)
    if head[:5] == b"{\\rtf":
        return ".rtf"
    if head == _OLE_MAGIC:
        return _ole_kind(fh.read(OFFICE_SUITE_MAX_BYTES))
    if not zipfile.is_zipfile(fh):
        return ""
    fh.seek(0)
    with zipfile.ZipFile(fh) as zf:
        names = set(zf.namelist())
        if "word/document.xml" in names:
            return ".docx"
        if "ppt/presentation.xml" in names:
            return ".pptx"
        if "mimetype" in names:
            with zf.open("mimetype") as m:
                return _ODF_SUITE_KINDS.get(m.read(64).strip(), "")
    return ""


def _ole_kind(data: bytes) -> str:
    """Which legacy format an OLE2 compound file holds, from its directory.

    A directory entry is 128 bytes, aligned to 128 in the file: the name in
    UTF-16, zero-padded, with its byte length (terminator included) at
    offset 64. Requiring all three keeps a stream name that merely occurs in
    the document's text — "PowerPoint Document" typed into a Word file —
    from deciding the format.
    """
    import struct

    for name, kind in _OLE_SUITE_KINDS:
        needle = name.encode("utf-16-le") + b"\0\0"
        size = struct.pack("<H", len(needle))
        at = data.find(needle)
        while at != -1:
            if at % 128 == 0 and data[at + 64:at + 66] == size:
                return kind
            at = data.find(needle, at + 1)
    return ""


def _pages_via_office_suite(fd: int, page_w: int, max_pages: int, start: int = 0,
                            scale: float = 1.0):
    """Convert with LibreOffice to PDF, then render that like any PDF."""
    import tempfile

    with _rewound(fd) as fh:
        kind = _office_suite_kind(fh)
        if not kind:
            raise RuntimeError("not a document LibreOffice is used for")
        with tempfile.TemporaryDirectory(prefix="qv-office-") as tmp:
            pdf = _suite_convert(fh, kind, "pdf", tmp)
            yield from render_pdf(pdf, page_w, max_pages, start, scale)


def _suite_convert(fh, kind: str, target: str, tmp: str) -> str:
    """Convert fh with LibreOffice to target, in tmp; the output's path.

    tmp is a private temporary directory in the jail's tmpfs, which the
    caller removes: it holds a copy of the document (LibreOffice wants a
    path; the jail has only a descriptor), a throwaway user profile, and
    the output. Nothing outlives the worker, and the jail has no network
    for a linked image to be fetched over.
    """
    import os
    import signal
    import subprocess

    src = os.path.join(tmp, "doc" + kind)
    cmd = suite_command(tmp, ["--convert-to", target, "--outdir", tmp, src])
    if not cmd:
        raise RuntimeError("no office suite")
    fh.seek(0)
    with open(src, "wb") as out:
        data = fh.read(OFFICE_SUITE_MAX_BYTES + 1)
        if len(data) > OFFICE_SUITE_MAX_BYTES:
            raise RuntimeError("too large for the office suite")
        out.write(data)
    del data
    # Its own session, so a timeout can take down the whole tree:
    # soffice is a launcher that forks soffice.bin, and killing only
    # the launcher leaves the converter running.
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        env={"HOME": tmp, "PATH": "/usr/bin:/bin",
             "SAL_USE_VCLPLUGIN": "svp"},
        start_new_session=True,
    )
    try:
        _out, err = proc.communicate(timeout=OFFICE_SUITE_TIMEOUT)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()  # reaps it and closes the stderr pipe
        raise RuntimeError("timed out after %d s" % OFFICE_SUITE_TIMEOUT)
    result = os.path.join(tmp, "doc." + target)
    if not os.path.isfile(result):
        tail = err.decode("utf-8", "replace").strip()[-200:]
        raise RuntimeError("no %s produced (exit %s) %s"
                           % (target.upper(), proc.returncode, tail))
    return result
