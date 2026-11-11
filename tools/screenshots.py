#!/usr/bin/env python3
# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Nicolas Vaughan <nivaca@fastmail.com>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Takes the screenshots of the README: the panel previewing a PDF, an
image and a source file, the breeze theme with a PDF's contents open, and
the settings window.

    .venv/bin/python tools/screenshots.py [-o FOLDER] [--scale 2]
        [--only pdf,image,code,breeze,settings] [--pdf FILE] [--page N]
        [--image FILE] [--scheme dark|light]

It writes FOLDER/KIND.png (by default in docs/screenshots/, where the README
takes them from), at SCALE times the size of the screen (2 by default,
sharp on screens of high resolution).

QuickView runs in this very process, on Qt's offscreen platform with a
screen of its own (1920×1200 at SCALE): nothing is shown on the real
screen and no display is needed. Only the panel is captured, rounded
corners and all, never a desktop around it. Settings, cache and logs live
in a temporary folder, so the user's are not touched. The files are
previewed by the same jailed workers as always, so the shots show what
QuickView really renders — which needs bubblewrap, as QuickView does.

The samples come from the system's own packages, so the shots can be
taken again anywhere:

* the PDF is Ghostscript's colour management manual if ghostscript-doc is
  installed, else hwloc's manual (it has bookmarks, for the contents
  sidebar of the breeze shot), opened on its first chapter rather than
  on a cover that is nearly blank; --pdf names another, --page the page
  to show;
* the image is KDE's Next wallpaper (--image names another);
* the source file is quickview.py itself.

The breeze shot and the settings window take their colours from a Plasma
colour scheme file — Breeze Dark by default, --scheme light for Breeze
Light — rather than from whatever scheme this desktop happens to use.
"""

import argparse
import configparser
import glob
import json
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KINDS = ("pdf", "image", "code", "breeze", "settings")
SCREEN = (1920, 1200)  # logical pixels, before the scale
SCALE = 2
SETTINGS_TAB = "Fonts"
SETTINGS_SIZE = (640, 560)
TIMEOUT = 60  # seconds a preview may take to render

# (pattern, page to show — counted from 1): the page that makes a shot.
PDF_CANDIDATES = (
    ("/usr/share/doc/ghostscript*/GS9_Color_Management.pdf", 1),
    ("/usr/share/doc/ghostscript*/*/GS9_Color_Management.pdf", 1),
    ("/usr/share/doc/hwloc/hwloc-a4.pdf", 27),
    ("/usr/share/doc/hwloc/hwloc-letter.pdf", 27),
)
IMAGE_CANDIDATES = (
    "/usr/share/wallpapers/Next/contents/images/5120x2880.png",
    "/usr/share/wallpapers/Next/contents/images/*.png",
)
SCHEMES = {"dark": "/usr/share/color-schemes/BreezeDark.colors",
           "light": "/usr/share/color-schemes/BreezeLight.colors"}


def say(text: str):
    print(text, flush=True)


def first_existing(patterns) -> str:
    for pattern in patterns:
        for path in sorted(glob.glob(pattern)):
            if os.path.isfile(path):
                return path
    return ""


def sample_pdf() -> tuple:
    """(path, page) of the first sample PDF installed, or ("", 1)."""
    for pattern, page in PDF_CANDIDATES:
        path = first_existing([pattern])
        if path:
            return path, page
    return "", 1


# ---------------------------------------------------------------------------
#  A world of its own: run before Qt or QuickView is imported

def isolate(scale: int) -> str:
    """Point QuickView's settings, cache, logs and runtime folder at a
    temporary one, and Qt at an offscreen screen; the temporary folder."""
    tmp = tempfile.mkdtemp(prefix="qv-shots-")
    for var, sub in (("XDG_CONFIG_HOME", "config"), ("XDG_CACHE_HOME", "cache"),
                     ("XDG_DATA_HOME", "data"), ("XDG_RUNTIME_DIR", "run")):
        os.makedirs(os.path.join(tmp, sub), mode=0o700)
        os.environ[var] = os.path.join(tmp, sub)
    for var in [v for v in os.environ if v.startswith("QUICKVIEW_")]:
        del os.environ[var]  # the user's overrides would change the shots
    # The screen in device pixels, scaled by Qt as a whole: the offscreen
    # screen's own "dpr" setting is reported by the screen but never
    # reaches its windows, which would then render and grab at 1x.
    screen = os.path.join(tmp, "screen.json")
    with open(screen, "w") as fh:
        json.dump({"screens": [{
            "name": "shots", "x": 0, "y": 0,
            "width": SCREEN[0] * scale, "height": SCREEN[1] * scale,
            "logicalDpi": 96,
        }]}, fh)
    os.environ["QT_QPA_PLATFORM"] = f"offscreen:configfile={screen}"
    os.environ["QT_SCALE_FACTOR"] = str(scale)
    for var in ("QT_SCREEN_SCALE_FACTORS", "QT_AUTO_SCREEN_SCALE_FACTOR"):
        os.environ.pop(var, None)
    return tmp


def scheme_palette(path: str):
    """A QPalette from a Plasma colour scheme file, the way Plasma maps its
    colour sets onto Qt's roles."""
    from PySide6.QtGui import QColor, QPalette

    scheme = configparser.ConfigParser(interpolation=None, strict=False)
    scheme.read(path, encoding="utf-8")

    def colour(group: str, key: str) -> QColor:
        r, g, b = (int(v) for v in scheme[f"Colors:{group}"][key].split(",")[:3])
        return QColor(r, g, b)

    window = colour("Window", "BackgroundNormal")
    button = colour("Button", "BackgroundNormal")
    palette = QPalette(button, window)  # Qt derives light, mid and dark
    role = QPalette.ColorRole
    for r, (group, key) in {
        role.Window: ("Window", "BackgroundNormal"),
        role.WindowText: ("Window", "ForegroundNormal"),
        role.Base: ("View", "BackgroundNormal"),
        role.AlternateBase: ("View", "BackgroundAlternate"),
        role.Text: ("View", "ForegroundNormal"),
        role.Button: ("Button", "BackgroundNormal"),
        role.ButtonText: ("Button", "ForegroundNormal"),
        role.Highlight: ("Selection", "BackgroundNormal"),
        role.HighlightedText: ("Selection", "ForegroundNormal"),
        role.ToolTipBase: ("Tooltip", "BackgroundNormal"),
        role.ToolTipText: ("Tooltip", "ForegroundNormal"),
        role.Link: ("View", "ForegroundLink"),
    }.items():
        palette.setColor(r, colour(group, key))
    faint = colour("Window", "ForegroundInactive")
    for r in (role.WindowText, role.Text, role.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, r, faint)
    palette.setColor(role.PlaceholderText, faint)
    return palette


# ---------------------------------------------------------------------------
#  Taking them

def settle(ms: int):
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_for(condition, what: str):
    end = time.monotonic() + TIMEOUT
    while not condition():
        if time.monotonic() > end:
            raise SystemExit(f"screenshots: gave up waiting for {what}")
        settle(50)


def panel_window():
    import quickview

    window = quickview.QuickView()
    # Not the neighbours: the samples sit in system folders whose other
    # files have nothing to do with the shots.
    window._prefetch_neighbors = lambda: None
    return window


def preview(window, path: str):
    """Show path and wait until it has finished rendering."""
    window.show_file(path)
    wait_for(lambda: window._render_job is None, os.path.basename(path))
    settle(400)  # the cached-page stepper and the last repaints


def shoot_panel(kind: str, path: str, out: str, toc: bool = False,
                page: int = 1):
    from common import SETTINGS

    SETTINGS["panel_theme"] = "breeze" if kind == "breeze" else "quicklook"
    window = panel_window()
    preview(window, path)
    if page > 1:
        window.scroll_to_page(page - 1)
        settle(300)
    if toc:
        wait_for(lambda: window._toc_job is None and window._toc_entries,
                 "the contents")
        window.toggle_toc()
        settle(300)
    window.panel.grab().save(out)
    window.dismiss("screenshot")
    window.deleteLater()


def shoot_settings(out: str, config_path: str):
    from PySide6.QtWidgets import QStyleFactory, QTabWidget

    import settings_dialog

    dialog = settings_dialog.SettingsDialog(config_path, environ={})
    style = QStyleFactory.create("Breeze") or QStyleFactory.create("Fusion")
    dialog.setStyle(style)
    for child in dialog.findChildren(object):
        if hasattr(child, "setStyle"):
            child.setStyle(style)
    dialog.resize(*SETTINGS_SIZE)
    tabs = dialog.findChild(QTabWidget)
    for i in range(tabs.count()):
        if tabs.tabText(i).replace("&&", "&") == SETTINGS_TAB:
            tabs.setCurrentIndex(i)
    dialog.show()
    settle(300)
    dialog.grab().save(out)
    dialog.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Take the README's screenshots of QuickView.")
    parser.add_argument("-o", "--output",
                        default=os.path.join(ROOT, "docs", "screenshots"),
                        help="folder to write KIND.png into")
    parser.add_argument("--only", default=",".join(KINDS),
                        help="which shots, comma-separated: " + ",".join(KINDS))
    parser.add_argument("--scale", type=int, default=SCALE,
                        help="device pixels per logical pixel (default 2)")
    parser.add_argument("--pdf", help="the PDF to preview")
    parser.add_argument("--page", type=int,
                        help="the PDF page to show, from 1 (default: the "
                             "sample's best page, or 1)")
    parser.add_argument("--image", help="the image to preview")
    parser.add_argument("--scheme", choices=sorted(SCHEMES), default="dark",
                        help="Plasma colour scheme for breeze and settings")
    args = parser.parse_args()

    kinds = [k.strip() for k in args.only.split(",") if k.strip()]
    unknown = set(kinds) - set(KINDS)
    if unknown:
        parser.error("unknown shots: " + ", ".join(sorted(unknown)))
    pdf, page = (args.pdf, 1) if args.pdf else sample_pdf()
    page = args.page or page
    image = args.image or first_existing(IMAGE_CANDIDATES)
    if {"pdf", "breeze"} & set(kinds) and not pdf:
        parser.error("no sample PDF found; name one with --pdf")
    if "image" in kinds and not image:
        parser.error("no sample image found; name one with --image")
    if not shutil.which("bwrap"):
        parser.error("bubblewrap (bwrap) is needed: QuickView previews "
                     "files only in its jail")

    tmp = isolate(args.scale)
    sys.path.insert(0, ROOT)
    from PySide6.QtWidgets import QApplication

    app = QApplication([sys.argv[0]])
    app.setApplicationName("QuickView")
    os.makedirs(args.output, exist_ok=True)
    config_path = os.path.join(tmp, "config", "quickview", "quickview.conf")
    try:
        import config

        config.write_default_if_missing(config_path)
        for kind in kinds:
            out = os.path.join(args.output, f"{kind}.png")
            if kind in ("breeze", "settings"):
                app.setPalette(scheme_palette(SCHEMES[args.scheme]))
            else:
                app.setStyle("Fusion")  # as the daemon pins it
                app.setPalette(app.style().standardPalette())
            if kind == "pdf":
                shoot_panel(kind, pdf, out, page=page)
            elif kind == "breeze":
                app.setStyle("Fusion")
                shoot_panel(kind, pdf, out, toc=True, page=page)
            elif kind == "image":
                shoot_panel(kind, image, out)
            elif kind == "code":
                shoot_panel(kind, os.path.join(ROOT, "quickview.py"), out)
            elif kind == "settings":
                shoot_settings(out, config_path)
            from PySide6.QtGui import QImage
            size = QImage(out).size()
            say(f"{out}  {size.width()}×{size.height()}")
        if {"pdf", "breeze"} & set(kinds):
            say(f"PDF: {pdf}, page {page}")
        if "image" in kinds:
            say(f"image: {image}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
