# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Nicolas Vaughan <nivaca@fastmail.com>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Space opens Quick Look in Dolphin, unless the user chose otherwise.

Against Dolphin UI files in a temporary folder, never the user's own.
"""

import os
import stat
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dolphin_shortcut as ds  # noqa: E402

HEAD = '<!DOCTYPE gui>\n<gui name="dolphin" translationDomain="kxmlgui6" version="49">\n <MenuBar>\n  <Menu name="file"><Action name="file_new"/></Menu>\n </MenuBar>\n'


def ui(*actions, section=True):
    body = "".join(f"  {a}\n" for a in actions)
    props = (f' <ActionProperties scheme="Default">\n{body} </ActionProperties>\n'
             if section else "")
    return HEAD + props + "</gui>\n"


def shortcuts(text):
    root = ET.fromstring(text)
    return {a.get("name"): a.get("shortcut")
            for a in root.find("ActionProperties").findall("Action")}


class Plan(unittest.TestCase):
    def test_no_file_gets_a_minimal_one(self):
        new, report = ds.plan(None)
        self.assertIn("added", report)
        self.assertEqual(shortcuts(new), {ds.SELECTION_MODE: "",
                                          ds.ACTION: "Space"})
        # Older than Dolphin's own, so Dolphin keeps only the shortcuts.
        self.assertEqual(ET.fromstring(new).get("version"), "0")

    def test_selection_mode_is_moved_off_its_default_space(self):
        new, report = ds.plan(ui('<Action name="edit_copy" priority="0"/>'))
        self.assertIn("Selection Mode moved off Space", report)
        self.assertEqual(shortcuts(new), {"edit_copy": None,
                                          ds.SELECTION_MODE: "",
                                          ds.ACTION: "Space"})

    def test_a_selection_mode_already_moved_is_left_as_it_is(self):
        new, _ = ds.plan(ui(f'<Action name="{ds.SELECTION_MODE}" shortcut="Ctrl+M"/>'))
        self.assertEqual(shortcuts(new), {ds.SELECTION_MODE: "Ctrl+M",
                                          ds.ACTION: "Space"})

    def test_a_file_without_shortcuts_gets_the_section(self):
        new, _ = ds.plan(ui(section=False))
        self.assertEqual(shortcuts(new)[ds.ACTION], "Space")

    def test_everything_outside_the_section_stays_byte_for_byte(self):
        old = ui('<Action name="edit_copy" priority="0"/>')
        new, _ = ds.plan(old)
        added = [line for line in new.splitlines() if line not in old.splitlines()]
        self.assertEqual(len(added), 2)
        self.assertEqual([line for line in new.splitlines() if line in old.splitlines()],
                         old.splitlines())


class UsersChoice(unittest.TestCase):
    def test_an_existing_quick_look_shortcut_is_kept(self):
        for shortcut in ("Space", "F3", ""):
            with self.subTest(shortcut=shortcut):
                new, report = ds.plan(ui(f'<Action name="{ds.ACTION}" shortcut="{shortcut}"/>'))
                self.assertIsNone(new)
                self.assertIn("unchanged", report)

    def test_space_the_user_gave_selection_mode_stays_theirs(self):
        new, report = ds.plan(ui(f'<Action name="{ds.SELECTION_MODE}" shortcut="Space"/>'))
        self.assertIsNone(new)
        self.assertIn(ds.SELECTION_MODE, report)

    def test_space_on_any_other_action_stays_theirs(self):
        for shortcut in ("Space", "F5; Space", "Space, X"):
            with self.subTest(shortcut=shortcut):
                new, report = ds.plan(ui(f'<Action name="reload" shortcut="{shortcut}"/>'))
                self.assertIsNone(new)
                self.assertIn("'reload'", report)

    def test_ctrl_space_is_not_space(self):
        new, _ = ds.plan(ui('<Action name="reload" shortcut="Ctrl+Space"/>'))
        self.assertEqual(shortcuts(new)[ds.ACTION], "Space")

    def test_a_broken_file_is_left_alone(self):
        new, report = ds.plan("<gui><ActionProperties>")
        self.assertIsNone(new)
        self.assertIn("not valid XML", report)


class Ensure(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = os.path.join(tmp.name, "kxmlgui5", "dolphin", "dolphinui.rc")

    def write(self, text, mode=0o640):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as fh:
            fh.write(text)
        os.chmod(self.path, mode)

    def read(self):
        with open(self.path) as fh:
            return fh.read()

    def test_a_missing_file_and_folder_are_created(self):
        self.assertIn("added", ds.ensure(self.path))
        self.assertEqual(shortcuts(self.read())[ds.ACTION], "Space")
        self.assertFalse(os.path.exists(self.path + ".before-quickview"))

    def test_the_original_is_kept_once_and_its_mode_too(self):
        original = ui('<Action name="edit_copy" priority="0"/>')
        self.write(original)
        ds.ensure(self.path)
        with open(self.path + ".before-quickview") as fh:
            self.assertEqual(fh.read(), original)
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o640)

    def test_a_second_run_changes_nothing(self):
        self.write(ui())
        ds.ensure(self.path)
        once = self.read()
        self.assertIn("unchanged", ds.ensure(self.path))
        self.assertEqual(self.read(), once)

    def test_no_temporary_file_is_left_behind(self):
        self.write(ui())
        ds.ensure(self.path)
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.path))),
                         ["dolphinui.rc", "dolphinui.rc.before-quickview"])


if __name__ == "__main__":
    unittest.main()
