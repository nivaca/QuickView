#!/usr/bin/env python3
# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Nicolas Vaughan <nicolasvaughan@proton.me>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Makes Space open the Quick Look preview in Dolphin, while QuickView's
dolphin_space setting is on (the default).

A Dolphin service menu cannot carry a shortcut: Dolphin takes service-menu
shortcuts only from the user's own copy of its UI file,
~/.local/share/kxmlgui5/dolphin/dolphinui.rc, under <ActionProperties>.
So this writes one there:

    <Action name="servicemenu_quickview-servicemenu.desktop::QuickView" shortcut="Space"/>

Dolphin's own Selection Mode has Space by default, and two actions on one
key leave the key doing nothing, so Selection Mode is moved off Space
(shortcut="") when — and only when — it still has its default. It stays
in Dolphin's menu.

Dolphin 26.08 loses service-menu shortcuts: applying its settings, or any
change to kservicemenurc, re-adds the service-menu actions without them,
and saving the Keyboard Shortcuts window afterwards writes the loss to
this file (fixed in Dolphin's master, commit d90c6f46). So a Quick Look
entry with no shortcut, or one without Space, is given Space again: Space
is added in front of any other key it has. To keep Quick Look off Space,
turn the setting off; then this changes nothing at all.

Space someone gave to Selection Mode or to any other action stays theirs:
the file is left as it is.

Only the <ActionProperties> section is edited, as text, so the rest of the
file stays byte for byte; the result must parse before it is written,
atomically, and the original is kept once as dolphinui.rc.before-quickview.
With no file at all, a minimal one is written: Dolphin treats it as older
than its own and keeps just its shortcuts, rewriting it in full.

Run by quickview.socket each time it starts (at login, and when installing),
and by the settings window when it is saved, so it is cheap and changes
nothing on a second run. Dolphin reads the file when it starts: a window
already open sees the change after a restart.

Standard library only: this runs before, and without, Qt.
"""

import os
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET

ACTION = "servicemenu_quickview-servicemenu.desktop::QuickView"
# The settings entry of the same service menu, which Dolphin lists (with no
# shortcut) once its Keyboard Shortcuts window has been saved.
SETTINGS_ACTION = "servicemenu_quickview-servicemenu.desktop::QuickViewSettings"
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


def section_span(text: str):
    """(start, end) of the text inside the <ActionProperties> section the
    shortcuts belong to (scheme "Default", else the first), or None: the
    same section plan() reads, so an edit lands where it was decided."""
    spans = []
    for opening in re.finditer(r"<ActionProperties\b([^>]*)>", text):
        close = text.find("</ActionProperties>", opening.end())
        if close < 0:
            break
        scheme = re.search(r'\bscheme="([^"]*)"', opening.group(1))
        spans.append(((scheme.group(1) if scheme else "Default"), opening.end(), close))
    chosen = next((s for s in spans if s[0] == "Default"), spans[0] if spans else None)
    return (chosen[1], chosen[2]) if chosen else None


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

    current = entries.get(ACTION)
    if current is not None and uses_space(current):
        return None, f"unchanged: Quick Look already has the shortcut {current!r}"
    for name, shortcut in entries.items():
        if name != ACTION and shortcut is not None and uses_space(shortcut):
            return None, f"left alone: Space belongs to Dolphin's {name!r}, as you set it"

    report = "added: Space opens Quick Look"
    if ACTION in entries:
        text, report = restore(text, current)
        if text is None:
            return None, report
        if SELECTION_MODE in entries:
            return text, report

    lines = []
    if SELECTION_MODE not in entries:
        lines.append(f'  <Action name="{SELECTION_MODE}" shortcut=""/>')
    if ACTION not in entries:
        lines.append(f'  <Action name="{ACTION}" shortcut="Space"/>')
    block = "\n".join(lines) + "\n"

    span = section_span(text) if section is not None else None
    if span is not None:
        # Before the chosen section's closing tag, on a line of its own.
        at = text.rfind("\n", span[0], span[1]) + 1 or span[1]
        new, n = text[:at] + block + text[at:], 1
    elif section is not None:
        new, n = text, 0
    else:
        new, n = re.subn(r"(?m)^</gui>",
                         ' <ActionProperties scheme="Default">\n' + block
                         + " </ActionProperties>\n</gui>", text, count=1)
    if not n:
        return None, f"left alone: could not find where to add the shortcut in {ui_file()}"
    ET.fromstring(new)  # must still parse — ParseError reaches the caller
    moved = " (Selection Mode moved off Space)" if SELECTION_MODE not in entries else ""
    return new, report + moved


def restore(text, current):
    """(new text, report) giving Space back to an existing Quick Look entry
    whose shortcut is empty or lacks Space."""
    current = (current or "").strip().strip(";").strip()
    wanted = "Space; " + current if current else "Space"
    element = re.compile(r'<Action\b[^>]*\bname="' + re.escape(ACTION) + r'"[^>]*>')
    span = section_span(text) or (0, len(text))
    match = element.search(text, span[0], span[1])
    if not match:
        return None, f"left alone: could not find Quick Look's entry in {ui_file()}"
    tag = match.group(0)
    if re.search(r'\sshortcut="[^"]*"', tag):
        new_tag = re.sub(r'(\sshortcut=)"[^"]*"', lambda m: f'{m.group(1)}"{wanted}"',
                         tag, count=1)
    else:
        new_tag = re.sub(r'(\s*/?>)$', lambda m: f' shortcut="{wanted}"' + m.group(1),
                         tag, count=1)
    new = text[:match.start()] + new_tag + text[match.end():]
    ET.fromstring(new)  # must still parse — ParseError reaches the caller
    lost = f"it had {current!r}" if current else "Dolphin had dropped it"
    return new, f"restored: Space opens Quick Look again ({lost})"


def enabled() -> bool:
    """QuickView's dolphin_space setting; on when it cannot be read."""
    try:
        import config
        return bool(config.load(config.CONFIG_FILE).get("dolphin_space", True))
    except Exception:  # noqa: BLE001 — a broken config must not stop this
        return True


def ensure(path: str = None, on: bool = None) -> str:
    """Apply plan() to the file at path; a one-line report."""
    if not (enabled() if on is None else on):
        return "left alone: turned off in QuickView's settings (dolphin_space)"
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


def unplan(text):
    """(new text or None, what happened): plan() undone, for uninstalling.

    Quick Look's entries go. So does Selection Mode's, if it is the
    shortcut-less one plan() wrote while Quick Look had Space, so that
    Space goes back to Dolphin's own Selection Mode; with Quick Look gone,
    an entry left on it would leave Space doing nothing at all.
    """
    if text is None:
        return None, "nothing to undo: no Dolphin settings file"
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        return None, f"left alone: {ui_file()} is not valid XML ({exc})"
    sections = root.findall("ActionProperties")
    section = next((s for s in sections if s.get("scheme", "Default") == "Default"),
                   sections[0] if sections else None)
    entries = {a.get("name"): a.get("shortcut")
               for a in (section.findall("Action") if section is not None else [])}
    span = section_span(text)
    if span is None or not ({ACTION, SETTINGS_ACTION} & set(entries)):
        return None, "nothing to undo"
    names = [ACTION, SETTINGS_ACTION]
    quick = entries.get(ACTION)
    selection = entries.get(SELECTION_MODE)
    if quick is not None and uses_space(quick) and selection is not None \
            and not selection.replace(";", "").strip():
        names.append(SELECTION_MODE)
    inside = text[span[0]:span[1]]
    for name in names:
        inside = re.sub(r'(?m)^[ \t]*<Action\b[^>]*\bname="' + re.escape(name)
                        + r'"[^>]*/>[ \t]*\n?', "", inside)
    new = text[:span[0]] + inside + text[span[1]:]
    ET.fromstring(new)  # must still parse — ParseError reaches the caller
    back = (" and Space given back to Selection Mode"
            if SELECTION_MODE in names else "")
    return new, "removed: Quick Look's shortcut" + back


def remove(path: str = None) -> str:
    """Apply unplan() to the file at path; a one-line report."""
    path = path or ui_file()
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except FileNotFoundError:
        text = None
    try:
        new, report = unplan(text)
    except ET.ParseError as exc:
        return f"left alone: the edited file would not parse ({exc})"
    if new is None:
        return report
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".dolphinui.")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(new)
    shutil.copymode(path, tmp)
    os.replace(tmp, path)
    return report + " — restart Dolphin to use it"


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["--remove"]:
        print(f"quickview: Dolphin shortcut {remove()}")
        return 0
    if argv:
        print("usage: dolphin_shortcut.py [--remove]", file=sys.stderr)
        return 2
    print(f"quickview: Dolphin shortcut {ensure()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
