# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Mustapha Alioglou
# Copyright (C) 2026 Nicolas Vaughan <nivaca@fastmail.com>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""The settings window, the file it writes, and the font settings it sets.

Against temporary config files: the user's own is never read or written.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Saving with "Space opens Quick Look" on edits Dolphin's UI file: a
# temporary one, never the user's own. Only while these tests run, as
# other tests start programs that read it.
_DATA = tempfile.TemporaryDirectory()
_SAVED_DATA_HOME = os.environ.get("XDG_DATA_HOME")


def setUpModule():
    os.environ["XDG_DATA_HOME"] = _DATA.name


def tearDownModule():
    if _SAVED_DATA_HOME is None:
        os.environ.pop("XDG_DATA_HOME", None)
    else:
        os.environ["XDG_DATA_HOME"] = _SAVED_DATA_HOME

from PySide6.QtWidgets import QApplication, QDialogButtonBox  # noqa: E402

_app = QApplication.instance() or QApplication([sys.argv[0]])

import common  # noqa: E402
import config  # noqa: E402
import quickview  # noqa: E402
import renderers  # noqa: E402
import settings_dialog  # noqa: E402
import version  # noqa: E402
import worker  # noqa: E402


class TempConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "quickview.conf")

    def write(self, text):
        with open(self.path, "w") as fh:
            fh.write(text)

    def read(self):
        with open(self.path) as fh:
            return fh.read()


class Save(TempConfig):
    def test_values_change_in_place_and_comments_stay(self):
        self.write("# mine\n[preview]\n# about styles\ncode_style = nord\n")
        config.save({"code_style": "dracula"}, self.path)
        self.assertEqual(self.read(),
                         "# mine\n[preview]\n# about styles\ncode_style = dracula\n")

    def test_a_commented_out_setting_is_taken_back_into_use(self):
        self.write("[preview]\n# pdf_max_pages = 50\n")
        config.save({"pdf_max_pages": 9}, self.path)
        self.assertIn("pdf_max_pages = 9", self.read())
        self.assertEqual(config.load(self.path)["pdf_max_pages"], 9)

    def test_new_settings_join_their_section_or_get_one(self):
        self.write("[preview]\ncode_style = nord\n\n[logging]\nlog_level = info\n")
        config.save({"text_limit_kb": 64, "daemon_mode": "off"}, self.path)
        text = self.read()
        self.assertLess(text.index("text_limit_kb"), text.index("[logging]"))
        self.assertIn("[daemon]\ndaemon_mode = off", text)

    def test_a_setting_in_the_wrong_section_is_not_mistaken_for_it(self):
        # code_style belongs to [preview]; a stray one elsewhere is not it.
        self.write("[logging]\ncode_style = nord\n")
        config.save({"code_style": "dracula"}, self.path)
        self.assertIn("[logging]\ncode_style = nord", self.read())
        self.assertEqual(config.load(self.path)["code_style"], "dracula")

    def test_everything_saved_reads_back(self):
        values = dict(config.defaults(), code_font="Fira Code",
                      reading_font="Junicode", ui_font_size=14,
                      daemon_mode="resident", idle_minutes=3)
        config.save(values, self.path)
        self.assertEqual(config.load(self.path), values)
        self.assertEqual([n for n in os.listdir(self.tmp.name)
                          if n.endswith(".tmp")], [])

    def test_a_missing_file_starts_from_the_commented_template(self):
        config.save({"code_style": "nord"}, self.path)
        self.assertIn("# QuickView settings.", self.read())
        self.assertEqual(config.load(self.path)["code_style"], "nord")


class FontNames(TempConfig):
    def test_a_name_cannot_carry_style_sheet_syntax(self):
        cleaned = config.clean_font_family('Mono}; QWidget { color: red }"')
        for bad in "{};:\"'":
            self.assertNotIn(bad, cleaned)

    def test_a_name_that_cleans_to_nothing_is_the_default(self):
        self.write("[fonts]\ncode_font = {};\n")
        self.assertEqual(config.load(self.path)["code_font"], "monospace")

    def test_an_empty_reading_font_means_the_built_in_look(self):
        self.write("[fonts]\nreading_font =\n")
        self.assertEqual(config.load(self.path)["reading_font"], "")


class Window(TempConfig):
    def dialog(self, environ=None):
        dlg = settings_dialog.SettingsDialog(self.path, environ=environ or {})
        self.addCleanup(dlg.deleteLater)
        return dlg

    def press(self, dlg, which):
        dlg.buttons.button(getattr(QDialogButtonBox.StandardButton, which)).click()

    def test_the_about_button_shows_version_authors_and_licence(self):
        dlg = self.dialog()
        shown = []
        saved = settings_dialog.QMessageBox.about
        settings_dialog.QMessageBox.about = staticmethod(
            lambda parent, title, text: shown.append((title, text)))
        self.addCleanup(setattr, settings_dialog.QMessageBox, "about", saved)
        self.assertEqual(dlg.buttons.buttonRole(dlg.about_button),
                         QDialogButtonBox.ButtonRole.HelpRole)
        dlg.about_button.click()
        self.assertEqual(len(shown), 1)
        text = shown[0][1]
        for expected in (version.VERSION,
                         "By Nicolas Vaughan (forked from the QuickView app "
                         "by Mustapha Alioglou)", "General Public License",
                         version.HOMEPAGE):
            self.assertIn(expected, text)
        for word in ("claude", "anthropic"):
            self.assertNotIn(word, text.lower())

    def test_every_setting_has_a_field(self):
        self.assertEqual(set(self.dialog().values()), set(config._SETTINGS))

    def test_it_opens_on_what_the_file_says(self):
        self.write("[daemon]\ndaemon_mode = resident\n[fonts]\nreading_font = Junicode\n")
        dlg = self.dialog()
        self.assertEqual(dlg.values()["daemon_mode"], "resident")
        self.assertFalse(dlg.reading_font.use_default.isChecked())
        self.assertEqual(dlg.values()["reading_font"], "Junicode")

    def test_a_font_that_is_not_installed_is_not_overwritten(self):
        # Shown as a substitute, but saved as configured unless changed.
        self.write("[fonts]\nreading_font = No Such Font QV\n")
        dlg = self.dialog()
        self.assertEqual(dlg.values()["reading_font"], "No Such Font QV")
        self.assertFalse(dlg.reading_font.missing.isHidden(), "and says so")
        self.press(dlg, "Apply")
        self.assertEqual(config.load(self.path)["reading_font"], "No Such Font QV")

    def test_apply_and_ok_save_cancel_does_not(self):
        dlg = self.dialog()
        dlg.daemon_radios["off"].setChecked(True)
        self.press(dlg, "Apply")
        self.assertEqual(config.load(self.path)["daemon_mode"], "off")
        dlg.daemon_radios["resident"].setChecked(True)
        self.press(dlg, "Cancel")
        self.assertEqual(config.load(self.path)["daemon_mode"], "off")
        dlg = self.dialog()
        dlg.daemon_radios["resident"].setChecked(True)
        self.press(dlg, "Ok")
        self.assertEqual(config.load(self.path)["daemon_mode"], "resident")

    def test_restore_defaults_only_fills_the_fields(self):
        self.write("[daemon]\ndaemon_mode = off\n")
        dlg = self.dialog()
        self.press(dlg, "RestoreDefaults")
        self.assertEqual(dlg.values(), config.defaults())
        self.assertEqual(config.load(self.path)["daemon_mode"], "off",
                         "not saved until Apply or OK")

    def test_idle_minutes_only_matter_on_demand(self):
        dlg = self.dialog()
        self.assertTrue(dlg.idle.isEnabled())
        dlg.daemon_radios["off"].setChecked(True)
        self.assertFalse(dlg.idle.isEnabled())

    def test_the_default_fonts_are_values_of_their_own(self):
        dlg = self.dialog()
        self.assertEqual(dlg.values()["code_font"], "monospace")
        self.assertEqual(dlg.values()["reading_font"], "")
        dlg.reading_font.use_default.setChecked(False)
        self.assertNotEqual(dlg.values()["reading_font"], "")

    def test_an_environment_override_is_pointed_out(self):
        quiet = self.dialog()
        self.assertTrue(quiet.env_note.isHidden())
        loud = self.dialog({"QUICKVIEW_DAEMON_MODE": "resident"})
        self.assertFalse(loud.env_note.isHidden())
        self.assertIn("daemon_mode", loud.env_note.text())


class PanelFonts(unittest.TestCase):
    def setUp(self):
        saved = dict(common.SETTINGS)
        self.addCleanup(lambda: (common.SETTINGS.clear(),
                                 common.SETTINGS.update(saved)))

    def window(self):
        w = quickview.QuickView()
        self.addCleanup(w.deleteLater)
        return w

    def test_the_fonts_reach_the_panel_style_sheet(self):
        common.SETTINGS.update(code_font="DejaVu Sans Mono", code_font_size=15,
                               ui_font_size=14)
        css = self.window().styleSheet()
        self.assertIn('font-family: "DejaVu Sans Mono"; font-size: 15px;', css)
        self.assertIn("font-size: 15px; font-weight: 600", css)  # title, +1
        self.assertIn("font-size: 13px; font-weight: bold", css)  # close, -1

    def test_a_font_change_restyles_the_open_panel(self):
        w = self.window()
        common.SETTINGS["code_font_size"] = 19
        w.apply_panel_theme(w.theme_name)
        self.assertIn("font-size: 19px", w.styleSheet())

    def test_the_gear_opens_the_settings_process(self):
        w = self.window()
        started = []
        saved = quickview.QProcess.startDetached
        quickview.QProcess.startDetached = lambda *a: started.append(a)
        try:
            w.titlebar.settings_btn.click()
        finally:
            quickview.QProcess.startDetached = saved
        self.assertEqual(len(started), 1)
        self.assertEqual(started[0][-1][-1], "--settings")
        self.assertFalse(w.isVisible())


class ReadingFont(unittest.TestCase):
    MARKDOWN = "\n\n".join("Paragraph %d. " % n + "word " * 80 for n in range(30))

    def pages(self, **font):
        with tempfile.TemporaryFile() as fh:
            fh.write(self.MARKDOWN.encode())
            fh.flush()
            return list(renderers.markdown_pages(
                fh.fileno(), "doc.md", 400, 50, 0, **font))

    def test_a_bigger_reading_size_lays_markdown_out_on_more_pages(self):
        small = self.pages(font="DejaVu Serif", font_size=9)
        large = self.pages(font="DejaVu Serif", font_size=20)
        self.assertGreater(large[0][0]["count"], small[0][0]["count"])

    def test_the_book_style_sheet_takes_the_family_and_size(self):
        css = renderers.epub._book_css(renderers.book_theme("paper"),
                                       "Junicode", 14)
        self.assertIn("font-family: 'Junicode', serif;", css)
        self.assertIn("font-size: 14pt", css)
        builtin = renderers.epub._book_css(renderers.book_theme("paper"))
        self.assertIn("font-family: serif; font-size: 11pt", builtin)

    def test_the_worker_filters_what_it_is_sent(self):
        self.assertEqual(renderers.reading_font("A}B;C", 99), ("ABC", 36))
        self.assertEqual(renderers.reading_font(None, "x"), ("", 11))

    def test_the_worker_passes_the_font_through(self):
        seen = {}
        saved = renderers.markdown_pages

        def fake(*args, **kwargs):
            seen.update(kwargs)
            return iter(())

        renderers.markdown_pages = fake
        try:
            with self.assertRaises(RuntimeError):  # nothing rendered
                worker.op_markdown({"page_w": 400, "max_pages": 5,
                                    "font": "Junicode", "font_size": 13},
                                   None, -1, None)
        finally:
            renderers.markdown_pages = saved
        self.assertEqual((seen["font"], seen["font_size"]), ("Junicode", 13))

    def test_the_cache_keys_change_with_the_font(self):
        saved = dict(common.SETTINGS)
        self.addCleanup(lambda: (common.SETTINGS.clear(),
                                 common.SETTINGS.update(saved)))
        before = quickview.QuickView.reading_tag()
        common.SETTINGS["reading_font_size"] = 17
        self.assertNotEqual(quickview.QuickView.reading_tag(), before)


class DolphinSpace(TempConfig):
    def setUp(self):
        super().setUp()
        os.environ.pop("QUICKVIEW_DOLPHIN_SPACE", None)
        self.ui = os.path.join(_DATA.name, "kxmlgui5", "dolphin", "dolphinui.rc")
        if os.path.exists(self.ui):
            os.remove(self.ui)

    def test_on_by_default_and_saving_sets_space(self):
        dialog = settings_dialog.SettingsDialog(self.path)
        self.assertTrue(dialog.dolphin_space.isChecked())
        self.assertTrue(dialog.apply())
        with open(self.ui) as fh:
            self.assertIn('shortcut="Space"', fh.read())
        self.assertIn("Dolphin shortcut added", dialog.status.text())
        self.assertIn("dolphin_space = true", self.read())

    def test_off_is_saved_and_dolphin_is_left_alone(self):
        dialog = settings_dialog.SettingsDialog(self.path)
        dialog.dolphin_space.setChecked(False)
        dialog.apply()
        self.assertFalse(os.path.exists(self.ui))
        self.assertIn("dolphin_space = false", self.read())
        self.assertFalse(settings_dialog.SettingsDialog(self.path).dolphin_space.isChecked())


if __name__ == "__main__":
    unittest.main()
