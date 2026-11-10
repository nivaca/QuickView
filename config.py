#!/usr/bin/env python3
# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Mustapha Alioglou
# Copyright (C) 2026 Nicolas Vaughan <nivaca@fastmail.com>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""User settings, read from ~/.config/quickview/quickview.conf.

Deliberately small. Everything here is a *preference* — something a person
might reasonably want different. The many other constants in common.py
are safety bounds on untrusted input (frame sizes, frame counts, timeouts);
exposing those would turn a config file into a way to defeat the sandbox's
limits, so they stay in the code.

INI rather than TOML because tomllib is Python 3.11 and this project
supports 3.10. Precedence is environment variable, then file, then default:
the env var stays useful for trying a setting without editing anything.

Read at startup, and again whenever the file changes: the daemon watches
it (QuickView.watch_settings), so a saved edit applies from the next
preview on, with no restart. Environment variables are read at startup
only — they belong to the daemon's process, not to the file.
"""

import configparser
import os

CONFIG_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
    "quickview",
)
CONFIG_FILE = os.path.join(CONFIG_DIR, "quickview.conf")

# name -> (section, kind, default, env var, minimum, maximum)
# The bounds are there so a typo degrades to something usable instead of a
# daemon that will not start or a cache that eats the disk.
_SETTINGS = {
    "code_style": ("preview", str, "one-dark", "QUICKVIEW_CODE_STYLE",
                   None, None),
    "book_theme": ("preview", str, "paper", "QUICKVIEW_BOOK_THEME",
                   None, None),
    "panel_theme": ("appearance", str, "quicklook", "QUICKVIEW_PANEL_THEME",
                    None, None),
    "text_limit_kb": ("preview", int, 1024, "QUICKVIEW_TEXT_LIMIT_KB",
                      1, 1024 * 64),
    "pdf_max_pages": ("preview", int, 50, "QUICKVIEW_PDF_MAX_PAGES", 1, 2000),
    "office_engine": ("preview", str, "libreoffice", "QUICKVIEW_OFFICE_ENGINE",
                      None, None),
    "log_level": ("logging", str, "info", "QUICKVIEW_LOG_LEVEL", None, None),
    "disk_cache_mb": ("cache", int, 256, "QUICKVIEW_DISK_CACHE_MB", 0, 65536),
    "memory_cache_mb": ("cache", int, 96, "QUICKVIEW_MEMORY_CACHE_MB",
                        8, 8192),
    "daemon_mode": ("daemon", str, "on-demand", "QUICKVIEW_DAEMON_MODE",
                    None, None),
    "idle_minutes": ("daemon", int, 10, "QUICKVIEW_IDLE_MINUTES", 1, 1440),
}

DEFAULT_FILE = """\
# QuickView settings. Changes apply as soon as the file is saved, from the
# next preview on — no restart needed.
#
# Every value below is the built-in default, shown for reference. Delete a
# line to go back to it. Each one can also be overridden for a single run
# with the matching QUICKVIEW_* environment variable.

[preview]
# Pygments style for source files: dracula, gruvbox-dark, nord, monokai,
# native, solarized-dark … anything Pygments ships.
code_style = one-dark

# Page colours for EPUB books: paper, sepia, dark, gruvbox-dark,
# gruvbox-light. Only the page is themed; the panel around it does not
# change.
book_theme = paper

# How much of a text file to read, in KiB. Bigger files are shown
# truncated — the highlighter's cost climbs with length.
text_limit_kb = 1024

# How many pages of a PDF or office document to render at most.
pdf_max_pages = 50

# How office documents are laid out: Word (docx, odt), slide decks (pptx,
# ppsx, odp), and the legacy doc, xls, ppt and rtf.
#
#   libreoffice  exact: the document as LibreOffice shows it — fonts, photos
#                in place, text wrap, headers, a page per slide. ~1-2 s on
#                first open, cached after that. Used only when LibreOffice
#                is installed; otherwise this behaves like builtin.
#   builtin      fast: QuickView's own layout, ~50 ms. Text, headings,
#                tables and images, but no text wrap, headers or EMF logos.
#                A deck shows the thumbnail it embeds; doc, xls, ppt and rtf
#                show the file's details only.
office_engine = libreoffice

[appearance]
# How the panel itself is painted.
#
#   quicklook  the default: a fixed dark panel with the close button top
#              left, the same on every desktop and independent of your
#              Plasma colour scheme.
#   breeze     takes its colours from your Plasma colour scheme instead —
#              light or dark, with your accent colour — and puts the close
#              button on the right, where Plasma's own windows put it.
#
# On a light Plasma scheme, pair breeze with a light code_style above: the
# two settings are independent, and the default one-dark is written for a
# dark background, so its greys are close to unreadable on a pale one.
panel_theme = quicklook

[logging]
# How much the daemon writes to ~/.local/share/quickview/quickview.log and
# to the journal (journalctl --user -u quickview).
#
#   error    only failures
#   warning  failures and recoverable problems
#   info     the above, plus one line per preview
#   debug    everything, including cache hits and worker lifecycle
#
# Crash reports are not affected: a native segfault always lands in
# crash.log, whatever this is set to.
log_level = info

[cache]
# Rendered previews kept on disk, in MiB. 0 disables the disk cache.
disk_cache_mb = 256

# Decoded pixmaps kept in memory, in MiB. This is on top of the ~130 MB the
# Qt process itself costs while it runs.
memory_cache_mb = 96

[daemon]
# Whether QuickView stays in memory between previews. Keeping Qt loaded
# makes a preview appear in ~50 ms; starting it fresh costs ~250 ms more,
# against ~130 MB held while it waits. systemd starts it on the first
# Space press in every mode, so none of them ever misses one.
#
#   on-demand  starts when needed and exits after idle_minutes without a
#              preview open, as macOS's Quick Look services do.
#   resident   once started, stays until logout: every preview is fast.
#   off        no background process: exits as soon as the preview closes.
daemon_mode = on-demand

# on-demand only: how long to wait, with no preview open, before exiting.
idle_minutes = 10
"""


# Settings whose value has to be one of a known set. A style name is
# free-form (Pygments owns that list and ships dozens), but a page palette
# is not: an unrecognised one would silently render every book white.
# The palettes themselves live in renderers.BOOK_THEMES, which runs in the
# jail — this is the list a person may type, and a test keeps the two equal.
_CHOICES = {
    "book_theme": ("paper", "sepia", "dark", "gruvbox-dark", "gruvbox-light"),
    # The panel's own colours. Same reasoning as book_theme: a typo here
    # would otherwise leave the window with no palette at all.
    "panel_theme": ("quicklook", "breeze"),
    # A typo keeps the default, rather than a daemon that never exits or
    # one that exits after every preview.
    "daemon_mode": ("on-demand", "resident", "off"),
    # Named levels only, so a typo cannot silence the log entirely — and so
    # setup_logging() can map straight onto the logging module's constants.
    "log_level": ("error", "warning", "info", "debug"),
    # A typo falls back to the default rather than to either engine by
    # accident.
    "office_engine": ("libreoffice", "builtin"),
}


def _clamp(value, low, high):
    if low is not None:
        value = max(low, value)
    if high is not None:
        value = min(high, value)
    return value


def load(path: str = CONFIG_FILE) -> dict:
    """Every setting, resolved. Never raises: bad input falls back."""
    parsed = configparser.ConfigParser()
    try:
        parsed.read(path, encoding="utf-8")
    except (OSError, configparser.Error):
        parsed = configparser.ConfigParser()  # unreadable or malformed

    out = {}
    for name, (section, kind, default, env, low, high) in _SETTINGS.items():
        raw = os.environ.get(env)
        if raw is None:
            raw = parsed.get(section, name, fallback=None)
        if raw is None:
            out[name] = default
            continue
        raw = raw.strip()
        if kind is int:
            try:
                out[name] = _clamp(int(raw), low, high)
            except ValueError:
                out[name] = default
        else:
            choices = _CHOICES.get(name)
            if choices and raw.lower() not in choices:
                out[name] = default  # a typo reads as "the default", not as
                continue             # a book with no colours at all
            out[name] = raw.lower() if choices else (raw or default)
    return out


def write_default_if_missing(path: str = CONFIG_FILE) -> bool:
    """Drop a commented template next to the user's other settings.

    Only ever creates; an existing file is never rewritten, so nothing a
    person edited can be lost to an upgrade.
    """
    if os.path.exists(path):
        return False
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "x", encoding="utf-8") as fh:
            fh.write(DEFAULT_FILE)
        return True
    except OSError:
        return False  # read-only home, or a race with another daemon
