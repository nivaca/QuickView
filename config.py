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
supported 3.10 when it was written. Precedence is environment variable,
then file, then default: the env var stays useful for trying a setting
without editing anything.

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
    "code_font": ("fonts", str, "monospace", "QUICKVIEW_CODE_FONT", None, None),
    "code_font_size": ("fonts", int, 12, "QUICKVIEW_CODE_FONT_SIZE", 6, 48),
    "reading_font": ("fonts", str, "", "QUICKVIEW_READING_FONT", None, None),
    "reading_font_size": ("fonts", int, 11, "QUICKVIEW_READING_FONT_SIZE",
                          6, 36),
    "ui_font_size": ("fonts", int, 12, "QUICKVIEW_UI_FONT_SIZE", 9, 18),
    "daemon_mode": ("daemon", str, "on-demand", "QUICKVIEW_DAEMON_MODE",
                    None, None),
    "idle_minutes": ("daemon", int, 10, "QUICKVIEW_IDLE_MINUTES", 1, 1440),
    "dolphin_space": ("dolphin", bool, True, "QUICKVIEW_DOLPHIN_SPACE",
                      None, None),
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

[fonts]
# Source files and plain text: a font family and its size in pixels.
# "monospace" is the desktop's own fixed-width font.
code_font = monospace
code_font_size = 12

# EPUB books and rendered Markdown: a family and its size in points. Empty
# keeps the built-in look — serif for books, the default sans for Markdown.
reading_font =
reading_font_size = 11

# The panel's own text — title, buttons, sidebar, tabs — in pixels.
ui_font_size = 12

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

[dolphin]
# Whether Space opens Quick Look in Dolphin. When true, QuickView checks
# Dolphin's shortcuts at each login and gives Space back to Quick Look if
# it was lost (Dolphin 26.08 drops service-menu shortcuts whenever its
# settings are applied). Space is never taken from another Dolphin action
# you gave it to. When false, QuickView leaves Dolphin's shortcuts alone.
dolphin_space = true
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


# How a yes/no setting may be written; anything else keeps the default.
_BOOLS = {"true": True, "yes": True, "on": True, "1": True,
          "false": False, "no": False, "off": False, "0": False}


def _clamp(value, low, high):
    if low is not None:
        value = max(low, value)
    if high is not None:
        value = min(high, value)
    return value


# Font families are written into style sheets — the panel's, and the page
# CSS a book is laid out with in the jail — so a name is kept to what font
# names are made of. Anything else ("}", ";", quotes) could end the rule it
# sits in and start one of its own.
_FONT_KEYS = ("code_font", "reading_font")
FONT_NAME_MAX = 64


def clean_font_family(name: str) -> str:
    """A font family name reduced to letters, digits, spaces and -_."""
    kept = "".join(c for c in (name or "") if c.isalnum() or c in " -_.")
    return " ".join(kept.split())[:FONT_NAME_MAX]


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
        if kind is bool:
            out[name] = _BOOLS.get(raw.lower(), default)
        elif kind is int:
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
            if name in _FONT_KEYS:
                # An empty reading_font is a value (the built-in look), not
                # a missing one; a name that cleans to nothing is a typo.
                out[name] = clean_font_family(raw) if raw else default
                if raw and not out[name]:
                    out[name] = default
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


def format_value(name: str, value) -> str:
    """How a setting is written in the file."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip()


def save(values: dict, path: str = CONFIG_FILE):
    """Write settings into the file, keeping everything else in it.

    The file is the commented template people read and edit by hand, so
    it is updated in place rather than regenerated: each `name = value`
    line is rewritten where it stands, a commented-out one ("# name = …")
    is taken back into use, and a setting the file does not mention yet —
    one added since it was written — goes at the end of its section, or of
    the file under a new section heading. Comments and unknown lines are
    left exactly as they were. Written to a temporary file and renamed into
    place, so the daemon's watcher never reads half a file.
    """
    import re

    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except FileNotFoundError:
        lines = DEFAULT_FILE.splitlines()

    pending = {name: format_value(name, v) for name, v in values.items()
               if name in _SETTINGS}
    section = None
    section_end = {}  # section -> index after its last non-blank line
    for i, line in enumerate(lines):
        head = re.match(r"\s*\[([^\]]+)\]\s*$", line)
        if head:
            section = head.group(1).strip()
            section_end.setdefault(section, i + 1)
            continue
        if section is not None and line.strip():
            section_end[section] = i + 1
        entry = re.match(r"\s*#?\s*([A-Za-z_]+)\s*=", line)
        if not entry:
            continue
        name = entry.group(1)
        if name in pending and _SETTINGS[name][0] == section:
            lines[i] = f"{name} = {pending.pop(name)}"

    # Whatever was not found: append, latest sections first so the earlier
    # insertion points stay valid.
    by_section = {}
    for name, value in pending.items():
        by_section.setdefault(_SETTINGS[name][0], []).append(f"{name} = {value}")
    for sec in sorted((s for s in by_section if s in section_end),
                      key=lambda s: section_end[s], reverse=True):
        at = section_end[sec]
        lines[at:at] = by_section.pop(sec)
    for sec, entries in by_section.items():
        if lines and lines[-1].strip():
            lines.append("")
        lines += [f"[{sec}]"] + entries

    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    os.replace(tmp, path)


def defaults() -> dict:
    """Every setting's built-in value."""
    return {name: spec[2] for name, spec in _SETTINGS.items()}
