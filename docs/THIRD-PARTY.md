Open-source software used by QuickView
======================================

QuickView itself is free software, under the GNU General Public License,
version 3 or later (GPL-3.0-or-later); see [LICENSE](../LICENSE). It is a
fork of the QuickView app by Mustapha Alioglou, under the same license.

QuickView contains no third-party code: nothing is copied into this
repository, and nothing is bundled in its packages. Everything below is
used from the system, as the RPM's dependencies or as programs found at run
time. The one exception is `install.sh`, which installs PySide6 and Pygments
from PyPI into a private virtualenv when the system has no usable copy;
those are the same projects, under the same licenses.

The licenses are given as SPDX identifiers, as the projects or Fedora's
packages state them. Large projects (Qt WebEngine, LibreOffice, the KDE
programs) contain parts under further licenses; only the main ones are
listed here. The versions are those QuickView 1.0 was developed and tested
with, on Fedora 45.

Needed to run
-------------

| Software | Used for | License |
|---|---|---|
| [Python](https://www.python.org/) 3.15 | the language QuickView is written in, with its standard library | PSF-2.0 |
| [Qt](https://www.qt.io/) 6 and [PySide6](https://doc.qt.io/qtforpython-6/) 6.11 | the panel, the daemon's event loop, the rendering of images, text and office layouts | LGPL-3.0-only OR GPL-3.0-only |
| Qt PDF, with [PDFium](https://pdfium.googlesource.com/pdfium/) | rendering PDFs, and the PDFs LibreOffice makes of office documents | LGPL-3.0-only OR GPL-3.0-only; PDFium: BSD-3-Clause |
| Qt WebEngine, with [Chromium](https://www.chromium.org/) | HTML previews | LGPL-3.0-only OR GPL-3.0-only; Chromium: BSD-3-Clause and others |
| Qt Multimedia, with [FFmpeg](https://ffmpeg.org/) | audio and video previews | LGPL-3.0-only OR GPL-3.0-only; FFmpeg: LGPL-2.1-or-later (GPL-3.0-or-later in some builds) |
| [Pygments](https://pygments.org/) 2.20 | syntax highlighting of source code (optional: without it, code is shown as plain text) | BSD-2-Clause |
| [bubblewrap](https://github.com/containers/bubblewrap) 0.13 | the jail in which every file is read | LGPL-2.0-or-later |
| [systemd](https://systemd.io/) | the user units that start the daemon on demand, and the Dolphin watch | LGPL-2.1-or-later |
| [libnotify](https://gitlab.gnome.org/GNOME/libnotify) (`notify-send`) | the Dolphin watch's notification, with its "Restart Dolphin" button | LGPL-2.1-or-later |
| [Dolphin](https://apps.kde.org/dolphin/) 26.08 | the file manager QuickView previews for; the service menu and the Space shortcut | GPL-2.0-or-later |
| `kstart`, from [KDE CLI Tools](https://invent.kde.org/plasma/kde-cli-tools) | restarting Dolphin from the Dolphin watch | GPL-2.0-or-later |

Optional, used when installed
-----------------------------

| Software | Used for | License |
|---|---|---|
| `pdftotext`, from [Poppler](https://poppler.freedesktop.org/) 26.08 | the position of each word of a PDF, for selecting its text (otherwise Qt PDF does it, more slowly) | GPL-2.0-only OR GPL-3.0-only |
| [LibreOffice](https://www.libreoffice.org/) | the exact layout of office documents, converted to PDF in the jail | MPL-2.0 |
| [Flatpak](https://flatpak.org/) | running the Flathub LibreOffice, when that is the one installed | LGPL-2.1-or-later |
| `bsdtar`, from [libarchive](https://www.libarchive.org/) | listing archives that Python's standard library cannot read | BSD-2-Clause |
| [7-Zip](https://www.7-zip.org/) (`7z`) | the same, for 7z and other archives | LGPL-2.1-or-later, with parts under BSD-3-Clause |
| [Rust](https://www.rust-lang.org/) (`rustc` and the standard library) | building the fast-path client; no crates are used | MIT OR Apache-2.0 |
| [PipeWire](https://pipewire.org/) or [PulseAudio](https://www.freedesktop.org/wiki/Software/PulseAudio/) | sound in audio and video previews | MIT; PulseAudio: LGPL-2.1-or-later |

QuickView can also list RAR archives with `unrar`, if it is installed.
`unrar` is not open-source software: its license is a freeware license
with further limitations (it forbids using the code to make a RAR
compressor). QuickView never requires it, and the RPM only suggests it.

Used to build, test and release
-------------------------------

| Software | Used for | License |
|---|---|---|
| [RPM](https://rpm.org/) (`rpmbuild`, `rpmsign`) | building and signing the RPM packages | GPL-2.0-or-later |
| [desktop-file-utils](https://www.freedesktop.org/wiki/Software/desktop-file-utils/) | checking the `.desktop` files when the RPM is built | GPL-2.0-or-later |
| [GnuPG](https://gnupg.org/) | signing the RPMs | GPL-3.0-or-later |
| [Ruff](https://docs.astral.sh/ruff/) | the lint check in continuous integration | MIT |
| [GitHub CLI](https://cli.github.com/) (`gh`) | publishing releases on GitHub | MIT |
| [tea](https://gitea.com/gitea/tea) | publishing releases on Codeberg | MIT |
| [copr-cli](https://github.com/fedora-copr/copr) | building the packages on Fedora Copr | GPL-2.0-or-later |

The tests use only Python's `unittest`, and the screenshots in
`docs/screenshots/` are taken by `tools/screenshots.py` with QuickView
itself. They show KDE's *Next* wallpaper (*Hanabi*, by Krystian Zajdel,
under CC-BY-SA-4.0) and the manual of hwloc (BSD-3-Clause), both from the
system's own packages.
