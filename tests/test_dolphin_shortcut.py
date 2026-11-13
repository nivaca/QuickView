# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Nicolas Vaughan <nivaca@fastmail.com>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Space opens Quick Look in Dolphin, and gets it back when Dolphin loses it,
unless the user chose otherwise.

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
    def test_quick_look_with_space_is_kept(self):
        for shortcut in ("Space", "F3; Space"):
            with self.subTest(shortcut=shortcut):
                new, report = ds.plan(ui(f'<Action name="{ds.SELECTION_MODE}" shortcut=""/>',
                                         f'<Action name="{ds.ACTION}" shortcut="{shortcut}"/>'))
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


class Restore(unittest.TestCase):
    """Dolphin 26.08 drops service-menu shortcuts and may save the loss."""

    def plan(self, entry):
        return ds.plan(ui(f'<Action name="{ds.SELECTION_MODE}" shortcut="; "/>',
                          '<Action name="edit_copy" priority="0"/>', entry))

    def test_an_emptied_shortcut_gets_space_back(self):
        new, report = self.plan(f'<Action name="{ds.ACTION}" shortcut=""/>')
        self.assertIn("restored", report)
        self.assertEqual(shortcuts(new)[ds.ACTION], "Space")

    def test_an_entry_with_no_shortcut_at_all(self):
        new, _ = self.plan(f'<Action name="{ds.ACTION}"/>')
        self.assertEqual(shortcuts(new)[ds.ACTION], "Space")

    def test_another_key_is_kept_beside_space(self):
        new, report = self.plan(f'<Action name="{ds.ACTION}" shortcut="F3"/>')
        self.assertEqual(shortcuts(new)[ds.ACTION], "Space; F3")
        self.assertIn("'F3'", report)

    def test_only_that_line_changes(self):
        old = ui(f'<Action name="{ds.SELECTION_MODE}" shortcut="; "/>',
                 f'<Action name="{ds.ACTION}" shortcut=""/>')
        new, _ = ds.plan(old)
        changed = [(a, b) for a, b in zip(old.splitlines(), new.splitlines()) if a != b]
        self.assertEqual(changed, [(f'  <Action name="{ds.ACTION}" shortcut=""/>',
                                    f'  <Action name="{ds.ACTION}" shortcut="Space"/>')])

    def test_selection_mode_back_on_its_default_is_moved_off_again(self):
        new, report = ds.plan(ui(f'<Action name="{ds.ACTION}" shortcut=""/>'))
        self.assertEqual(shortcuts(new), {ds.ACTION: "Space", ds.SELECTION_MODE: ""})
        self.assertIn("Selection Mode moved off Space", report)

    def test_space_on_another_action_still_wins(self):
        new, report = ds.plan(ui(f'<Action name="{ds.ACTION}" shortcut=""/>',
                                 '<Action name="reload" shortcut="Space"/>'))
        self.assertIsNone(new)
        self.assertIn("'reload'", report)

    def test_a_second_run_changes_nothing(self):
        new, _ = self.plan(f'<Action name="{ds.ACTION}" shortcut=""/>')
        self.assertEqual(ds.plan(new), (None, "unchanged: Quick Look already has the shortcut 'Space'"))


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

    def test_turned_off_nothing_is_touched(self):
        self.write(ui(f'<Action name="{ds.ACTION}" shortcut=""/>'))
        before = self.read()
        self.assertIn("turned off", ds.ensure(self.path, on=False))
        self.assertEqual(self.read(), before)
        self.assertFalse(os.path.exists(self.path + ".before-quickview"))

    def test_the_setting_is_read_from_the_config_file(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        conf = os.path.join(tmp.name, "quickview.conf")
        with open(conf, "w") as fh:
            fh.write("[dolphin]\ndolphin_space = false\n")
        import config
        saved = config.CONFIG_FILE
        config.CONFIG_FILE = conf
        self.addCleanup(setattr, config, "CONFIG_FILE", saved)
        os.environ.pop("QUICKVIEW_DOLPHIN_SPACE", None)
        self.assertIn("turned off", ds.ensure(self.path))
        self.assertFalse(os.path.exists(self.path))

    def test_a_missing_file_and_folder_are_created(self):
        self.assertIn("added", ds.ensure(self.path, on=True))
        self.assertEqual(shortcuts(self.read())[ds.ACTION], "Space")
        self.assertFalse(os.path.exists(self.path + ".before-quickview"))

    def test_the_original_is_kept_once_and_its_mode_too(self):
        original = ui('<Action name="edit_copy" priority="0"/>')
        self.write(original)
        ds.ensure(self.path, on=True)
        with open(self.path + ".before-quickview") as fh:
            self.assertEqual(fh.read(), original)
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o640)

    def test_a_second_run_changes_nothing(self):
        self.write(ui())
        ds.ensure(self.path, on=True)
        once = self.read()
        self.assertIn("unchanged", ds.ensure(self.path, on=True))
        self.assertEqual(self.read(), once)

    def test_no_temporary_file_is_left_behind(self):
        self.write(ui())
        ds.ensure(self.path, on=True)
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.path))),
                         ["dolphinui.rc", "dolphinui.rc.before-quickview"])


if __name__ == "__main__":
    unittest.main()
