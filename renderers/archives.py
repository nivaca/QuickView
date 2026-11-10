# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Mustapha Alioglou
# Copyright (C) 2026 Nicolas Vaughan <nivaca@fastmail.com>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Archive listings — read, never extracted."""

from .base import (
    ARCHIVE_MAX_ENTRIES,
    ARCHIVE_TOOLS,
    _rewound,
)


def list_archive(fd: int, name: str, max_entries: int = ARCHIVE_MAX_ENTRIES) -> dict:
    """List an archive's entries without extracting anything.

    Reads headers only — no member is ever decompressed — so an archive that
    expands to terabytes costs nothing here. zip and tar are handled by the
    standard library; everything else (rar, 7z, iso) goes to whichever of
    bsdtar/7z/unrar exists, reading the archive through /dev/fd rather than a
    path, because the jail has the descriptor and no filesystem.
    """
    import os
    import subprocess
    import tarfile
    import zipfile

    # count_exact says whether "count" and "total" describe the whole
    # archive. The tar branch stops reading early on a huge member list, and
    # a floor reported as a total is worse than an honest "500+".
    out = {"entries": [], "count": 0, "total": 0, "truncated": False,
           "count_exact": True, "tool": None}

    with _rewound(fd) as fh:
        if zipfile.is_zipfile(fh):
            fh.seek(0)
            with zipfile.ZipFile(fh) as zf:
                infos = zf.infolist()
                out["tool"] = "zipfile"
                out["count"] = len(infos)
                out["total"] = sum(i.file_size for i in infos)
                out["entries"] = [
                    [i.filename, i.file_size] for i in infos[:max_entries]
                ]
                out["truncated"] = len(infos) > max_entries
                return out
        fh.seek(0)
        try:
            with tarfile.open(fileobj=fh, mode="r:*") as tf:
                members = []
                capped = False
                for member in tf:  # streamed: no full scan up front
                    if len(members) >= max_entries * 4:
                        capped = True  # stop before a tar with millions of
                        break          # members costs a full scan
                    members.append(member)
                out["tool"] = "tarfile"
                out["count"] = len(members)
                out["total"] = sum(m.size for m in members)
                out["count_exact"] = not capped
                out["entries"] = [[m.name, m.size] for m in members[:max_entries]]
                out["truncated"] = capped or len(members) > max_entries
                return out
        except tarfile.TarError:
            pass

    # Not a zip or a tar: hand the descriptor to an external lister.
    os.lseek(fd, 0, os.SEEK_SET)
    for tool, args in ARCHIVE_TOOLS:
        if not os.path.exists(tool):
            continue
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            proc = subprocess.run(
                [tool] + args + ["/dev/fd/%d" % fd],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                pass_fds=(fd,), timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if proc.returncode != 0 or not proc.stdout:
            continue  # encrypted, corrupt, or a format this tool refuses
        names = _parse_listing(tool, proc.stdout)
        if not names:
            continue
        out["tool"] = os.path.basename(tool)
        out["count"] = len(names)
        out["entries"] = [[n, None] for n in names[:max_entries]]
        out["truncated"] = len(names) > max_entries
        return out

    raise RuntimeError("no archive lister available for this format")


def _parse_listing(tool: str, data: bytes) -> list:
    """Entry names out of a lister's stdout. Names only: the long formats
    differ per tool and per locale, and a preview does not need sizes."""
    text = data.decode("utf-8", errors="replace")
    if tool.endswith("7z"):
        # -slt prints "Path = name" records.
        return [
            line[7:].strip() for line in text.splitlines()
            if line.startswith("Path = ")
        ]
    return [line for line in text.splitlines() if line.strip()]
