#!/usr/bin/env python3
# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Nicolas Vaughan <nivaca@fastmail.com>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Makes Space open the Quick Look preview in Dolphin, unless the user chose
otherwise.

A Dolphin service menu cannot carry a shortcut: Dolphin takes service-menu
shortcuts only from the user's own copy of its UI file,
~/.local/share/kxmlgui5/dolphin/dolphinui.rc, under <ActionProperties>.
So this writes one there:

    <Action name="servicemenu_quickview-servicemenu.desktop::QuickView" shortcut="Space"/>

Dolphin's own Selection Mode has Space by default, and two actions on one
key leave the key doing nothing, so Selection Mode is moved off Space
(shortcut="") when — and only when — it still has its default. It stays
in Dolphin's menu.

Nothing the user chose is overridden:

* a Quick Look entry already there, with any shortcut or none, is left
  as it is (a cleared shortcut is a choice too);
* if the user put Space on Selection Mode or on any other action, Space is
  theirs, and nothing is changed.

Only the <ActionProperties> section is edited, as text, so the rest of the
file stays byte for byte; the result must parse before it is written,
atomically, and the original is kept once as dolphinui.rc.before-quickview.
With no file at all, a minimal one is written: Dolphin treats it as older
than its own and keeps just its shortcuts, rewriting it in full.

Run by quickview.socket each time it starts (at login, and when installing),
so it is cheap and changes nothing on a second run. Dolphin reads the file
when it starts: a window already open sees the change after a restart.

Standard library only: this runs before, and without, Qt.
"""

import os
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET

ACTION = "servicemenu_quickview-servicemenu.desktop::QuickView"
SELECTION_MODE = "toggle_selection_mode"
# Dolphin's own actions bound to Space when the user has not changed them:
# checked against Dolphin 26.08, where Selection Mode is the only one.
SPACE_BY_DEFAULT = (SELECTION_MODE,)

MINIMAL = """<!DOCTYPE gui>
<gui name="dolphin" version="0">
 <ActionProperties scheme="Default">
  <Action name="{selection}" shortcut=""/>
  <Action name="{action}" shortcut="Space"/>
 </ActionProperties>
</gui>
""".format(selection=SELECTION_MODE, action=ACTION)


def ui_file() -> str:
    data = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(data, "kxmlgui5", "dolphin", "dolphinui.rc")


def uses_space(shortcut: str) -> bool:
    """Whether any of a shortcut's alternatives ("A; B") starts with Space."""
    for alternative in shortcut.split(";"):
        first_key = alternative.split(",")[0].strip()
        if first_key.lower() == "space":
            return True
    return False


def plan(text):
    """(new text or None, what happened) for a dolphinui.rc's text, or None
    when the file does not exist."""
    if text is None:
        return MINIMAL, "added: a new Dolphin settings file with Space for Quick Look"
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        return None, f"left alone: {ui_file()} is not valid XML ({exc})"
    sections = root.findall("ActionProperties")
    section = next((s for s in sections if s.get("scheme", "Default") == "Default"),
                   sections[0] if sections else None)
    entries = {a.get("name"): a.get("shortcut")
               for a in (section.findall("Action") if section is not None else [])}

    if ACTION in entries:
        current = entries[ACTION]
        return None, ("unchanged: Quick Look already has "
                      + (f"the shortcut {current!r}" if current else "no shortcut, by choice"))
    for name, shortcut in entries.items():
        if shortcut is not None and uses_space(shortcut):
            return None, f"left alone: Space belongs to Dolphin's {name!r}, as you set it"

    lines = []
    if SELECTION_MODE not in entries:
        lines.append(f'  <Action name="{SELECTION_MODE}" shortcut=""/>')
    lines.append(f'  <Action name="{ACTION}" shortcut="Space"/>')
    block = "\n".join(lines) + "\n"

    if section is not None:
        new, n = re.subn(r"(?m)^([ \t]*)</ActionProperties>",
                         lambda m: block + m.group(0), text, count=1)
    else:
        new, n = re.subn(r"(?m)^</gui>",
                         ' <ActionProperties scheme="Default">\n' + block
                         + " </ActionProperties>\n</gui>", text, count=1)
    if not n:
        return None, f"left alone: could not find where to add the shortcut in {ui_file()}"
    ET.fromstring(new)  # must still parse — ParseError reaches the caller
    moved = " (Selection Mode moved off Space)" if SELECTION_MODE not in entries else ""
    return new, "added: Space opens Quick Look" + moved


def ensure(path: str = None) -> str:
    """Apply plan() to the file at path; a one-line report."""
    path = path or ui_file()
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except FileNotFoundError:
        text = None
    try:
        new, report = plan(text)
    except ET.ParseError as exc:
        return f"left alone: the edited file would not parse ({exc})"
    if new is None:
        return report
    os.makedirs(os.path.dirname(path), exist_ok=True)
    backup = path + ".before-quickview"
    if text is not None and not os.path.exists(backup):
        shutil.copy2(path, backup)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".dolphinui.")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(new)
    if text is not None:
        shutil.copymode(path, tmp)
    os.replace(tmp, path)
    return report + " — restart Dolphin to use it"


def main() -> int:
    print(f"quickview: Dolphin shortcut {ensure()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
