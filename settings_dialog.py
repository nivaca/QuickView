# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Mustapha Alioglou
# Copyright (C) 2026 Nicolas Vaughan <nivaca@fastmail.com>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""The settings window: `quickview --settings`, the app menu, Dolphin's
context menu and the panel's ⚙ button all open this.

It edits ~/.config/quickview/quickview.conf through config.save(), which
keeps the file's comments, and does nothing else: the daemon watches that
file and applies what changed (QuickView.watch_settings). So this runs as a
process of its own, whether or not a daemon is up — on demand, it may well
not be.

Every bound and choice comes from config.py, so the window cannot offer a
value the loader would refuse.
"""

import os

from PySide6 import __version__ as PYSIDE_VERSION
from PySide6.QtCore import Qt, QLockFile, QUrl, qVersion
from PySide6.QtGui import QDesktopServices, QFont, QFontDatabase, QIcon
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QFontComboBox, QFormLayout, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QRadioButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

import config
import version

SAMPLE = "The quick brown fox — 0123456789 {}[]()"

# What each choice is called on screen, where its config value is terse.
PANEL_THEMES = [("quicklook", "Quick Look (fixed dark panel)"),
                ("breeze", "Breeze (follows the Plasma colour scheme)")]
OFFICE_ENGINES = [("libreoffice", "LibreOffice — exact, ~0.6 s on first open"),
                  ("builtin", "Built-in — instant, approximate")]
LOG_LEVELS = [("error", "Errors only"), ("warning", "Warnings"),
              ("info", "Normal (one line per preview)"),
              ("debug", "Everything (for bug reports)")]
DAEMON_MODES = [
    ("on-demand",
     "On demand — starts with the first preview, exits when idle",
     "Like macOS's Quick Look. The ~130 MB it uses are returned after the "
     "idle time below; the first preview after that takes ~250 ms instead "
     "of ~50 ms."),
    ("resident",
     "Resident — stays running once started",
     "Every preview is fast, at the cost of ~130 MB held until you log out."),
    ("off",
     "Off — exits as soon as the preview closes",
     "Nothing stays in memory between previews; every preview takes "
     "~250–300 ms to appear."),
]


def _bounds(name):
    _section, _kind, _default, _env, low, high = config._SETTINGS[name]
    return low, high


def libreoffice_found() -> str:
    """Which LibreOffice previews would use, in words."""
    try:
        from renderers import suite
        soffice, flatpak = suite._suite()
    except Exception:
        soffice, flatpak = "", None
    if flatpak:
        return "the Flathub version (org.libreoffice.LibreOffice)"
    if soffice:
        return f"installed ({soffice})"
    return "not found — the built-in layout is used either way"


def code_styles() -> list:
    """Pygments' style names, or just the current default without it."""
    try:
        from pygments.styles import get_all_styles
        return sorted(get_all_styles())
    except ImportError:
        return [config._SETTINGS["code_style"][2]]


class FontField(QWidget):
    """A family picker with a "use the default" box; the default is a value
    of its own ("monospace", or "" for the built-in reading look) rather
    than any one installed family."""

    def __init__(self, default_value: str, default_label: str,
                 monospace: bool):
        super().__init__()
        self.default_value = default_value
        self.use_default = QCheckBox(default_label)
        self.family = QFontComboBox()
        if monospace:
            self.family.setFontFilters(QFontComboBox.FontFilter.MonospacedFonts)
        # A configured family that is not installed (any more, or on this
        # machine) is displayed as whatever Qt substitutes, though the field
        # still holds — and saves — the configured name. Say so, rather
        # than show a font that is not the one in use.
        self.missing = QLabel("")
        self.missing.setWordWrap(True)
        self.missing.hide()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.use_default)
        lay.addWidget(self.family)
        lay.addWidget(self.missing)
        self.use_default.toggled.connect(
            lambda on: self.family.setEnabled(not on))
        self.family.currentFontChanged.connect(lambda _f: self.missing.hide())

    def value(self) -> str:
        if self.use_default.isChecked():
            return self.default_value
        return config.clean_font_family(self.family.currentFont().family())

    def set_value(self, value: str):
        is_default = value == self.default_value
        self.use_default.setChecked(is_default)
        self.family.setEnabled(not is_default)
        if not is_default:
            self.family.setCurrentFont(QFont(value))
        absent = not is_default and value not in QFontDatabase.families()
        self.missing.setText(f"“{value}” is not installed here; it is kept "
                             "unless you pick another font." if absent else "")
        self.missing.setVisible(absent)


class SettingsDialog(QDialog):
    def __init__(self, path: str = config.CONFIG_FILE, parent=None,
                 environ=os.environ):
        super().__init__(parent)
        self.path = path
        self.setWindowTitle("QuickView Settings")
        self.setWindowIcon(QIcon.fromTheme("document-preview"))
        self._fields = {}  # name -> (get, set)

        tabs = QTabWidget()
        tabs.addTab(self._appearance_tab(), "Appearance")
        tabs.addTab(self._fonts_tab(), "Fonts")
        tabs.addTab(self._previews_tab(), "Previews")
        tabs.addTab(self._daemon_tab(), "Background")
        tabs.addTab(self._cache_tab(), "Cache && logs")

        self.status = QLabel("")
        self.status.setWordWrap(True)
        overridden = [f"{name} ({spec[3]})"
                      for name, spec in config._SETTINGS.items()
                      if spec[3] in environ]
        self.env_note = QLabel(
            "Set by an environment variable, which wins over this window: "
            + ", ".join(overridden) if overridden else "")
        self.env_note.setWordWrap(True)
        self.env_note.setVisible(bool(overridden))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(
            self.apply)
        buttons.button(
            QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(
            lambda: self.set_values(config.defaults()))
        # Help role: KDE's button order puts it on the left, apart from the
        # buttons that close the window.
        self.about_button = buttons.addButton(
            "About", QDialogButtonBox.ButtonRole.HelpRole)
        self.about_button.setIcon(QIcon.fromTheme("help-about"))
        self.about_button.clicked.connect(self.show_about)
        self.buttons = buttons

        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        lay.addWidget(self.env_note)
        lay.addWidget(self.status)
        lay.addWidget(buttons)

        self.set_values(config.load(path))

    # ------------------------------------------------------------ fields
    def _bind(self, name, get, put):
        self._fields[name] = (get, put)

    def _combo(self, name, choices) -> QComboBox:
        box = QComboBox()
        for value, label in choices:
            box.addItem(label, value)

        def put(value):
            i = box.findData(value)
            if i < 0:  # a value the list does not name — keep it selectable
                box.addItem(str(value), value)
                i = box.count() - 1
            box.setCurrentIndex(i)

        self._bind(name, box.currentData, put)
        return box

    def _spin(self, name, suffix="", zero_text=None) -> QSpinBox:
        spin = QSpinBox()
        low, high = _bounds(name)
        spin.setRange(low if low is not None else 0,
                      high if high is not None else 1_000_000)
        spin.setSuffix(suffix)
        if zero_text:
            spin.setSpecialValueText(zero_text)
        self._bind(name, spin.value, spin.setValue)
        return spin

    def values(self) -> dict:
        return {name: get() for name, (get, _put) in self._fields.items()}

    def set_values(self, values: dict):
        for name, (_get, put) in self._fields.items():
            if name in values:
                put(values[name])
        self._sync_idle()

    # -------------------------------------------------------------- tabs
    def _appearance_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.addRow("Panel style:", self._combo("panel_theme", PANEL_THEMES))
        form.addRow("Panel text size:", self._spin("ui_font_size", " px"))
        form.addRow("Code colours:", self._combo(
            "code_style", [(s, s) for s in code_styles()]))
        form.addRow("Book and Markdown pages:", self._combo(
            "book_theme", [(t, t) for t in config._CHOICES["book_theme"]]))
        hint = QLabel("On a light Plasma colour scheme, pair Breeze with "
                      "light code colours (e.g. solarized-light).")
        hint.setWordWrap(True)
        form.addRow(hint)
        return page

    def _fonts_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)

        self.code_font = FontField("monospace", "Desktop fixed-width font",
                                   monospace=True)
        self._bind("code_font", self.code_font.value, self.code_font.set_value)
        code_size = self._spin("code_font_size", " px")
        self.code_sample = QLabel(SAMPLE)
        form.addRow("Code font:", self.code_font)
        form.addRow("Code size:", code_size)
        form.addRow("", self.code_sample)

        self.reading_font = FontField(
            "", "Built-in (serif for books, sans for Markdown)",
            monospace=False)
        self._bind("reading_font", self.reading_font.value,
                   self.reading_font.set_value)
        reading_size = self._spin("reading_font_size", " pt")
        self.reading_sample = QLabel(SAMPLE)
        form.addRow("Reading font:", self.reading_font)
        form.addRow("Reading size:", reading_size)
        form.addRow("", self.reading_sample)

        def refresh():
            code = QFont(self.code_font.value())
            code.setPixelSize(code_size.value())
            self.code_sample.setFont(code)
            reading = QFont(self.reading_font.value() or "serif")
            reading.setPointSize(reading_size.value())
            self.reading_sample.setFont(reading)

        for field in (self.code_font, self.reading_font):
            field.use_default.toggled.connect(refresh)
            field.family.currentFontChanged.connect(refresh)
        code_size.valueChanged.connect(refresh)
        reading_size.valueChanged.connect(refresh)
        self._refresh_samples = refresh
        return page

    def _previews_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.addRow("Read text files up to:", self._spin("text_limit_kb", " KiB"))
        form.addRow("Render at most:", self._spin("pdf_max_pages", " pages"))
        form.addRow("Office documents:",
                    self._combo("office_engine", OFFICE_ENGINES))
        note = QLabel("LibreOffice: " + libreoffice_found())
        note.setWordWrap(True)
        form.addRow("", note)
        return page

    def _daemon_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        intro = QLabel(
            "QuickView keeps Qt loaded in a background process so previews "
            "appear in ~50 ms. systemd starts it on the first Space press in "
            "every mode, so no press is ever missed.")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        group = QButtonGroup(self)
        radios = {}
        for value, label, detail in DAEMON_MODES:
            radio = QRadioButton(label)
            text = QLabel(detail)
            text.setWordWrap(True)
            text.setContentsMargins(24, 0, 0, 6)
            group.addButton(radio)
            radios[value] = radio
            lay.addWidget(radio)
            lay.addWidget(text)

        def get():
            return next(v for v, r in radios.items() if r.isChecked())

        def put(value):
            radios.get(value, radios["on-demand"]).setChecked(True)

        self._bind("daemon_mode", get, put)
        self.daemon_radios = radios

        row = QHBoxLayout()
        row.addWidget(QLabel("Exit after"))
        self.idle = self._spin("idle_minutes", " minutes without a preview")
        row.addWidget(self.idle)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)
        group.buttonToggled.connect(lambda *_: self._sync_idle())
        return page

    def _sync_idle(self):
        radios = getattr(self, "daemon_radios", None)
        if radios is not None:
            self.idle.setEnabled(radios["on-demand"].isChecked())
        refresh = getattr(self, "_refresh_samples", None)
        if refresh is not None:
            refresh()

    def _cache_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.addRow("Disk cache:", self._spin("disk_cache_mb", " MiB", "Off"))
        form.addRow("Memory cache:", self._spin("memory_cache_mb", " MiB"))
        form.addRow("", self._button("Clear cache now", self._clear_cache))
        form.addRow("Log detail:", self._combo("log_level", LOG_LEVELS))
        form.addRow("", self._button("Open log folder", self._open_logs))
        return page

    @staticmethod
    def _button(text, action) -> QWidget:
        """A button at its natural width, not stretched across the form."""
        button = QPushButton(text)
        button.clicked.connect(action)
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(button)
        lay.addStretch(1)
        return row

    def _clear_cache(self):
        import common
        common.clear_cache()
        self.status.setText("Disk cache cleared.")

    def _open_logs(self):
        import common
        QDesktopServices.openUrl(QUrl.fromLocalFile(common.DATA_DIR))

    # ------------------------------------------------------------ about
    @staticmethod
    def about_text() -> str:
        return (
            f"<h3>QuickView {version.VERSION}</h3>"
            "<p>A Quick Look style file previewer for KDE Plasma: select a "
            "file in Dolphin and press Space.</p>"
            "<p>By Mustapha Alioglou. This fork is maintained by Nicolas "
            "Vaughan.</p>"
            f'<p><a href="{version.HOMEPAGE}">{version.HOMEPAGE}</a><br>'
            f'Original project: <a href="{version.UPSTREAM}">'
            f"{version.UPSTREAM}</a></p>"
            "<p>Licensed under the GNU General Public License, version 3 or "
            "later. QuickView comes with absolutely no warranty.</p>"
            f"<p><small>Qt {qVersion()}, PySide6 {PYSIDE_VERSION}"
            "</small></p>")

    def show_about(self):
        QMessageBox.about(self, "About QuickView", self.about_text())

    # ----------------------------------------------------------- saving
    def apply(self):
        try:
            config.save(self.values(), self.path)
        except OSError as exc:
            self.status.setText(f"Could not save {self.path}: {exc}")
            return False
        self.status.setText(
            "Saved. QuickView applies it from the next preview.")
        return True

    def accept(self):
        if self.apply():
            super().accept()


def run(path: str = config.CONFIG_FILE) -> int:
    """Show the window until it is closed; one at a time."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lock = QLockFile(os.path.join(os.path.dirname(path), ".settings.lock"))
    if not lock.tryLock(100):
        print("quickview: the settings window is already open")
        return 0
    app = QApplication.instance()
    app.setApplicationName("QuickView")
    app.setDesktopFileName("quickview-settings")
    dialog = SettingsDialog(path)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    dialog.exec()
    lock.unlock()
    return 0
