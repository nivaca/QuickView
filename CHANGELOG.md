# Changelog

Notable changes to QuickView. Format follows [Keep a Changelog][kac]; the
project has no version tags yet, so entries are dated.

[kac]: https://keepachangelog.com/en/1.1.0/

## 0.1.8 — 2026-11-12

### Changed

- **The release notes and the README credit the fork the same way as the
  About box:** "By Nicolas Vaughan (forked from the QuickView app by
  Mustapha Alioglou)".

## 0.1.7 — 2026-11-12

### Changed

- **The About box credits the fork first:** "By Nicolas Vaughan (forked
  from the QuickView app by Mustapha Alioglou)".

## 0.1.6 — 2026-11-12

### Added

- **An About button in the settings window.** It shows QuickView's
  version, its authors (Mustapha Alioglou, and Nicolas Vaughan for this
  fork), links to this fork and to the original project, the licence, and
  the Qt and PySide6 versions in use. The version comes from a new
  `version.py`, which `packaging/release.py` now sets along with the
  spec's, and a test keeps the two in step.

## 0.1.5 — 2026-11-12

### Fixed

- **Upgrading the RPM restarts a running daemon.** It used to keep running
  the old version until the next login, so a new feature (selecting a
  PDF's text, in 0.1.4) seemed missing after `dnf upgrade`. The package
  now marks `quickview.service` for a restart, which systemd carries out
  at the end of the transaction for every logged-in user.

## 0.1.4 — 2026-11-12

### Added

- **A PDF's text can be selected and copied, as in Quick Look.** Dragging
  across a page selects from word to word, across pages too, scrolling the
  view when the pointer goes past its edge; a double-click selects a word;
  Ctrl+A selects everything and Ctrl+C copies. A click elsewhere clears
  the selection, which also goes to the primary selection for
  middle-click pasting. The pages show a text cursor.

  The words' positions come from the jail, like everything else read from
  the file: a new `pdftext` op runs Poppler's `pdftotext -bbox-layout` on
  the passed descriptor (about 25 ms a page), with QtPdf as the fallback
  when Poppler is not installed. A page's text is asked for only when a
  press lands on it. Line and paragraph breaks in the copied text come from
  the lines' positions, so list items stay on consecutive lines and a
  heading's number stays with its title. The daemon validates every offset
  and box it is sent, and caps the text it accepts. The RPM recommends
  `poppler-utils`.

### Changed

- **A new signing key.** The release RPMs are now signed with Nicolas
  Vaughan's key `8187 0643 CA22 1AF9 0C30  554E BE68 32CD 3599 4948`,
  which replaces `236E F043 AB7A 4434 A05C  A4EC B554 9099 FC0D 6464`.
  `packaging/RPM-GPG-KEY-quickview` and the key attached to the release
  are the new one; anyone who installs the downloaded RPMs imports it
  once more (`sudo rpm --import RPM-GPG-KEY-quickview`). The Copr
  packages are signed by Copr's own key and are not affected.

## 0.1.3 — 2026-11-11

### Added

- **Space opens Quick Look in Dolphin without setting it up.** A service
  menu cannot carry a shortcut, so `dolphin_shortcut.py` writes one into
  the user's Dolphin settings (`kxmlgui5/dolphin/dolphinui.rc`), run by
  `quickview.socket` each time it starts — at login and on installing —
  and by `install.sh`. Dolphin's Selection Mode, which has Space by
  default, moves off it when it still has that default. A shortcut the
  user chose is never overridden: an existing Quick Look shortcut (or a
  cleared one), or Space given to any other action, leaves the file as it
  is. Only the shortcuts section is edited, the original is kept once as
  `dolphinui.rc.before-quickview`, and with no settings file a minimal one
  is written, which Dolphin expands into its own. Checked against a real
  Dolphin 26.08 in an isolated session.

- **`packaging/release.py VERSION` makes a whole release.** It checks
  that the tree is clean and in step with GitHub, that the tools are
  logged in, that the signing key is usable and that the tests pass; turns
  this changelog's "Unreleased" section into the version's (and into the
  spec's `%changelog` entry); commits and tags; builds and signs the RPMs
  with the key published as `packaging/RPM-GPG-KEY-quickview`; publishes
  the GitHub release, with notes made from the changelog and checksums;
  checks the downloaded RPMs' signatures as a user's `dnf` would; and
  builds on Copr, waiting until every chroot serves the new version.
  `--dry-run` shows what it would do and changes nothing.

### Changed

- **The release RPMs are signed.** The RPMs attached to the GitHub
  release of 0.1.2 were re-signed with Nicolas Vaughan's key
  (`236E F043 AB7A 4434 A05C  A4EC B554 9099 FC0D 6464`), whose public half
  is now in the repository as `packaging/RPM-GPG-KEY-quickview` and
  attached to the release. Copr's packages were already signed by Copr.

## 0.1.2 — 2026-11-11

### Added

- **QuickView is on Copr.** On Fedora 45 and Rawhide,
  `sudo dnf copr enable nivaca/quickview && sudo dnf install quickview`
  installs it as a package Copr builds and signs, and `dnf upgrade` keeps
  it current. The README's Install section now leads with it, ahead of
  `install.sh` for other distributions and of building the RPM yourself.

- **`packaging/build-rpm.sh --sign`** signs both RPMs with OpenPGP, so
  `dnf` can check where they came from rather than warn that it skipped
  the check. `--sign` uses the default GPG key, `--sign=KEY` names one;
  the public key is exported as `build/rpm/RPM-GPG-KEY-quickview` for
  people to import. Each signed package is then verified the way a user's
  `dnf` would, in a keyring of its own holding only that exported key, so
  a wrong key or a failed signature stops the build. A missing `rpm-sign`
  or key is reported before building.

### Fixed

- **A worker job's queued error no longer outlives the job.** When a file
  could not be opened or a worker not started, the error was reported
  from a zero-delay timer; if the window owning the job was deleted first,
  that timer ran anyway and failed on the deleted job ("Internal C++
  object already deleted"). The timers are now tied to the job, so Qt
  drops them along with it. The daemon's one window lives as long as the
  daemon, so this showed up in the test suite rather than in use.
- **The tests no longer litter `/tmp`.** `tests/test_config.py` made a
  temporary folder for every test and never removed it — fifteen per run
  of the suite. Tests driving a window with a stand-in worker also stop
  its work before the stand-in is swapped back for the real worker.

## 0.1.1 — 2026-11-10

The entry below — the package needs no logout after installing — and:

- **GPL-3 notices in the packaging files.** The package was already
  GPL-3.0-or-later (its License tag and the GPLv3 text it installs), but
  the spec, the launcher, the systemd units and the preset now carry the
  project's licence header too, as every source file does.

## 2026-11-10 — no logout after installing the package

### Changed

- **The package's launcher starts the socket on first use.** Installing
  the RPM enables `quickview.socket` for every user, but it only started
  listening at the next login — the installer runs as root, outside the
  session — so until then each preview fell back to a daemon systemd did
  not manage, which started cold again after every idle exit. When nobody
  answers a request for a file, the launcher now checks whether the socket
  is enabled but not listening, starts it (reloading the user's systemd
  once if it has not seen the new unit files yet) and sends the request
  again. A disabled socket is left alone, flags such as `--settings` never
  touch systemd, and without systemd nothing changes.

## 2026-11-10 — an RPM package

### Added

- **QuickView builds as an RPM** (`packaging/quickview.spec`, version
  0.1.0), with `packaging/build-rpm.sh` building it into `build/rpm/`. The
  package runs on the system's Python, PySide6 and Pygments — no
  virtualenv, which is the part of `install.sh` that broke when a checkout
  was copied without its `pyvenv.cfg`. It installs the code in
  `/usr/share/quickview/`, byte-compiled ahead of time since the jail sees
  it read-only, the compiled client in `/usr/libexec/quickview/`, a
  `/usr/bin/quickview` launcher, the socket and service as systemd user
  units enabled for every user by a preset, and the settings window's and
  Dolphin's menu entries. bubblewrap is required; archive tools and
  LibreOffice are suggested.

### Changed

- **The systemd units are files** (`packaging/quickview.socket`,
  `quickview.service.in`) rather than text inside `install.sh`, so the
  package and `install.sh` install the same ones.

## 2026-11-10 — screenshots by script

### Added

- **`tools/screenshots.py` takes the README's screenshots.** The panel
  previewing a PDF, an image and a source file, the breeze theme with a
  PDF's contents open, and — new — the settings window, written to
  `docs/screenshots/` at twice the screen's size by default (`--scale`).
  QuickView runs in the script's own process on Qt's offscreen platform,
  with a virtual 1920×1200 screen, so nothing appears on screen and no
  display is needed; settings, cache and logs are temporary, so the
  user's are untouched; and files go through the real jailed workers, so
  the shots show what QuickView renders. The samples come from system
  packages — Ghostscript's manual if installed, else hwloc's (opened on
  its first chapter), and KDE's Next wallpaper — and `--pdf`, `--page` and
  `--image` name others. The breeze shot and the settings window take
  their colours from Plasma's Breeze Dark scheme file (`--scheme light`
  for Breeze Light), not from the desktop's current scheme.

### Changed

- **The screenshots are retaken** with it: current code, the ⚙ button,
  sharp at 2×, plus one of the settings window in the README's Settings
  section.

## 2026-11-10 — a settings window, and fonts

### Added

- **A settings window.** Every setting in `quickview.conf`, in five tabs —
  Appearance, Fonts, Previews, Background (the daemon mode and its idle
  time), Cache & logs — with OK, Apply, Cancel and Restore Defaults, a
  "Clear cache now" button and a shortcut to the log folder. It opens from
  **QuickView Settings** in the application menu, from Dolphin's context
  menu, from a new **⚙** button in the panel, and with
  `quickview --settings`. It is a process of its own, so it works with no
  daemon running, and it only writes the file: the daemon applies what
  changed, as it does any edit. Bounds and choices come from `config.py`,
  so it cannot offer a value the loader would refuse; a setting overridden
  by a `QUICKVIEW_*` environment variable is pointed out; and one window
  at a time.
- **Font settings.** `[fonts] code_font` and `code_font_size` for source
  files, `reading_font` and `reading_font_size` for EPUB books and
  rendered Markdown, and `ui_font_size` for the panel's own text (the title
  a step above it, small print a step below). The defaults are exactly the
  fonts used before. The reading font changes where pages break, so book
  and Markdown pages — and their contents, whose page numbers come from
  the layout — are cached per font, and a book's search lays out with the
  same font so matches land where the text is. Font names are reduced to
  letters, digits, spaces and `-_.` before they go into a style sheet,
  in the daemon and again in the jail.
- **`config.save()`** updates the settings file in place: values are
  rewritten where they stand, commented-out ones taken back into use, new
  ones added to their section, and comments kept — written to a
  temporary file and renamed, so the daemon never reads half of it.

## 2026-11-10 — the daemon on demand

### Changed

- **The daemon starts on demand and exits when idle, like macOS's Quick
  Look services.** It used to start at login and stay until logout,
  holding ~130 MB to save ~200 ms per preview (a cold start measures
  ~250–300 ms, not the ~1 s the README claimed). `install.sh` now installs
  `quickview.socket`: systemd listens on QuickView's socket from login and
  starts the daemon on the first connection, queueing that request until
  the daemon reads it, so no Space press is ever lost. The old
  start-at-login service is disabled on upgrade.
- **The daemon is optional.** `[daemon] daemon_mode` chooses: `on-demand`
  (the default) exits after `idle_minutes` (10) without a preview open;
  `resident` stays once started, as before; `off` exits as soon as the
  preview closes, so nothing lingers between previews. Applies when the
  file is saved. Without systemd, XDG autostart and the launcher start the
  daemon, and the modes behave the same.

### Fixed

- **A socket systemd owns is never deleted.** `QLocalServer`, given a
  descriptor, removes the socket file when it closes, as if it had created
  it — which after the first idle exit would leave systemd listening on a
  path no client can reach. Connections on systemd's socket are accepted
  directly and handed to the same code as `QLocalSocket`s, and the file
  stays.
- **A socket-activated daemon does not mistake itself for another.** The
  single-instance check connects to the socket; started by systemd, it
  would reach its own and exit. It is skipped when systemd passed the
  socket.

## 2026-11-10 — speed and structure

### Added

- **Office documents show at once, then sharpen.** With LibreOffice in
  use, a docx or odt waited ~0.6 s on "Loading…" for LibreOffice to start
  and lay it out. The built-in layout now appears in ~35–50 ms, while
  LibreOffice works alongside in a second worker; its pages replace the
  quick ones as soon as they are cached, and the reader stays at the same
  fraction of the document even though the two paginate differently.
  Moving on cancels the conversion, so paging through a folder never
  leaves LibreOffice running for files already gone by. Decks and the
  legacy formats, which have no quick layout, wait for LibreOffice as
  before. If LibreOffice fails, the quick layout stays.
- **Neighbouring documents are prefetched, not just images.** The files
  ← → would show next were warmed only when they were images. PDFs and
  office documents are now warmed too — their first two pages
  (`PREFETCH_PAGES`), which is enough for them to open in ~5 ms against
  ~85 ms cold; the rest renders when the reader gets there. An office
  neighbour is warmed in the layout it will open with, so with LibreOffice
  it opens straight into LibreOffice's pages. Prefetch still runs one job
  at a time, after the current preview has finished rendering, and waits
  for an office document's LibreOffice layout before starting.
- **Settings apply without a restart.** The daemon watches
  `quickview.conf` (and its folder, for editors that save by renaming) and
  re-reads it a quarter second after the last change. Every setting
  applies from the next preview; the panel theme (including where the
  close button sits) and the log level change at once, and a smaller disk
  cache is pruned immediately. An edit saved while the daemon is still
  starting is picked up too. A malformed file falls back to defaults for
  whatever it gets wrong, as at startup.

### Changed

- **`renderers.py` is a package.** The decoders were one 3,948-line file;
  they are now `renderers/` with a module per family — `images`, `pdf`,
  `highlight`, `archives`, `office`, `suite` (running LibreOffice), `sheets`,
  `epub`, `markdown` — plus `base` for shared limits and encoders. Moved by
  a script and checked line by line: no code changed, and
  `import renderers` still reaches every name, so the workers and helper
  scripts are untouched. No import cycles.
- **The worker dispatches through a table.** `worker.py`'s `main()` was
  221 lines with twelve job types in one if/elif chain. Each type is now a
  function in an `OPS` table, writing through a small `Reply` object that
  tracks whether the header has gone out — which is what decides how a
  failure is reported. `serve()` answers one request and can be driven
  over a socket pair, so the protocol is now tested without a jail,
  including the rule that a stream failing after its header ends without
  the end-of-stream marker, and that every job type the daemon sends has a
  handler.
- **Settings are read when used.** Seven settings were copied into
  constants when the daemon started (`PDF_MAX_PAGES`, `OFFICE_ENGINE` and
  the like), which is what made a restart necessary and made tests patch
  module variables. They are read from the one `SETTINGS` dict at the
  point of use, and a reload updates that dict in place.
- **One check decides whether a worker's answer is still wanted.** Eleven
  callbacks across four views each re-implemented "is this the job
  rendering the panel now, for the file on screen?"; a slip in any of them
  would paint one file's preview under another's name. They now share
  `_is_current()`, and a test checks that late answers are dropped.
- **File routing is one method.** Which view previews a file was decided
  inline in `show_file()`; it is now `route()`, asked by `show_file()` and
  by the prefetch, so the two cannot disagree about a file.
- **Long UI methods split.** The media controls row is a `PlaybackBar`
  widget of its own (`show_media()` went from 162 lines to 34) and
  `show_image()` from 97 to 10, as a cache lookup and a render. The
  controls lay out to the pixel as before.
- **The disk cache's location is private to `common.py`.** The image
  prefetch built cache paths itself; it asks `cache_has()` now.

## 2026-11-10 — fork by Nicolas Vaughan

The first changes made in [nivaca/QuickView][fork], a fork of
[MustaphaAlioglou/QuickView][upstream] maintained by Nicolas Vaughan
(<nivaca@fastmail.com>): reviewing the code, reproducing each
bug before fixing it, and checking every change against the test suite
and a running daemon. Everything up to the 2026-10-07 entry below is
Mustapha Alioglou's original work.

[fork]: https://github.com/nivaca/QuickView
[upstream]: https://github.com/MustaphaAlioglou/QuickView

### Added

- **The Flathub LibreOffice is used.** Only a distro LibreOffice under
  `/usr` was looked for, and the README said a Flatpak copy could not run
  in the jail. On a machine with only the Flatpak, every docx, odt and
  deck therefore fell back to the approximate built-in layout, and the
  legacy `.doc`, `.xls`, `.ppt` and `.rtf` files to the metadata card. Now:
  - **Detection** (`renderers.flatpak_suite`). `org.libreoffice.LibreOffice`
    is found by reading the installation directories directly — the
    per-user one first, then `/var/lib/flatpak`, as `flatpak` itself
    searches — and the runtime is the one the app's `metadata` names,
    from whichever installation holds it (a per-user app on a system-wide
    runtime is the common case). No `flatpak` command is run, and both
    trees are resolved to real paths, so an update that swaps the
    `active` link cannot pull one out from under a conversion. It is one
    more entry in `OFFICE_SUITES`, `flatpak:org.libreoffice.LibreOffice`,
    after the distro paths: a distro LibreOffice still wins, and
    `office_engine = builtin` still turns both off.
  - **Into the worker's jail** (`sandbox._office_suite_binds`). The daemon
    binds the app and runtime trees read-only under
    `/run/quickview/libreoffice/` in the render workers' jail — and only
    theirs; the media player's jail is unchanged. Nothing writable is
    added, and still no user document: the file arrives as a descriptor,
    as before.
  - **A nested jail** (`renderers.suite_command`). Flatpak's LibreOffice
    is built against its runtime, not the distro's `/usr`, so the worker
    runs it in a second bubblewrap jail laid out the way Flatpak lays one
    out: the runtime as `/usr`, the app as `/app`, `/lib`, `/bin` and the
    rest rebuilt as links into it, `--unshare-all` (no network),
    `--cap-drop ALL`, a cleared environment, and the conversion's own
    temporary directory as the only writable path. Inside the worker's
    jail it nests; run from a test on the host it is the same jail.
    Killing it on the 12 s timeout still takes the whole tree down.
  - **Fonts.** System fonts are bound where the runtime's fontconfig
    looks (`/run/host/fonts`), and so are the user's own, from
    `~/.local/share/fonts`. Entries there are often symlinks into a font
    collection elsewhere in the home directory, which a bind of the
    directory would carry in as links to nowhere, so each entry is bound
    at its real target. Checked by converting a document set in Junicode,
    a user-installed font: without this it came out in DejaVu Serif.
  - **One Flatpak setting is deliberately left out.** The app's metadata
    sets `LIBO_FLATPAK=1`, which turns on the desktop integration a real
    Flatpak sandbox has (portals, `/.flatpak-info`); in this jail
    LibreOffice then exits with status 1 and no message.
  - **Speed.** ~0.4 s to convert a short document, ~0.6 s for a legacy
    `.doc` through the daemon's real worker pool, including the nested
    jail.
  - **Tests.** Seven new ones (`FlatpakSuite` in `tests/test_office.py`)
    run against a fake installation tree, so CI covers detection, the
    precedence of a distro install, broken installs, the binds, the
    in-jail branch and the shape of the nested jail without a Flatpak.
    On a machine with the Flatpak, the nine real-LibreOffice tests that
    used to skip there (docx, pptx, odp, doc, ppt, xls as pages and as a
    grid, rtf) now run and pass.
- **Lint in CI.** The workflow runs ruff's pyflakes checks
  (`ruff check --select F`) before the tests. They flag undefined names
  and unused imports — and would have caught the bug fixed below on the
  day it was written. Six unused imports were removed so it starts clean.

### Changed

- **The daemon is split into modules** (commit `56d4f84`). `quickview.py`
  had grown to ~4,000 lines, ~2,500 of them one window class. It now
  holds the window, the IPC socket and the dispatch from file type to
  view (~770 lines). Each family of views is a mixin class that
  `QuickView` inherits, in its own module:
  - `view_image.py` — still images, neighbour prefetch, animations
  - `view_document.py` — PDF, Markdown, EPUB, the contents sidebar, find
  - `view_media.py` — audio and video
  - `view_text.py` — source and plain text, HTML, folders, archives
  - `view_office.py` — office documents, slide decks, spreadsheets

  and the shared pieces moved out to `common.py` (settings, file-type
  tables, stylesheet, logging, the disk cache), `sandbox.py` (the jail,
  the worker pool, `SandboxJob`, `MediaSession`) and `widgets.py` (the
  titlebar, seek bar and match overlay). The split was done by a script
  that moved lines, not by hand, and every moved line was then checked to
  be byte-identical to the original: only imports and the class header
  differ, and behaviour does not change. Nothing imports `quickview` back
  — the daemon runs it as `__main__`, and a second import would load a
  second copy with its own settings. Tests that swapped a module
  attribute (`MediaSession`, `office_suite`, `OFFICE_ENGINE`,
  `CACHE_VERSION`) now swap it in the module that reads it, where the
  swap actually takes effect.

### Fixed

- **A file that cannot be opened shows its error instead of hanging the
  panel** (commit `c0e767c`). A file deleted, moved or made unreadable
  between being selected and being previewed left the panel waiting
  forever. The error was delivered from a zero-delay timer whose callback
  read `exc` from an `except OSError as exc:` block — but Python unbinds
  that name when the block ends, so the callback raised `NameError` and
  the job's `on_done` never fired. Five places had it: two in
  `SandboxJob` (every document and image preview) and three in
  `MediaSession` (audio and video). Each now binds the message while it
  still exists. Reproduced before the fix; `tests/test_sandbox_job.py`
  fails on the old code and passes on the new.
- **The media frame buffer is freed when the player cannot start**
  (commit `c0e767c`). If the jailed media worker failed to spawn, its
  shared-memory frame buffer stayed mapped: `MediaSession.stop()` returns
  early for a session that never started, so nothing else unmapped it.
- **`install.sh` repairs a virtualenv that lost its `pyvenv.cfg`.** A
  `.venv` copied or synced without that file still has a `python` that
  runs — as the bare system interpreter, with the packages in `.venv`
  invisible to it. The daemon then lost syntax highlighting, and the
  installer's pip step aimed at `/usr/local` and failed with
  `Permission denied`. The installer now re-runs `venv` over such a
  directory, which writes the file back and keeps every installed
  package, and refuses to continue with a `python` that is not a
  virtualenv at all rather than let pip write to the system.

### Documentation

- The README describes the Flatpak support, the new module layout and
  this fork's contributions, and the install instructions clone the fork.

## 2026-10-07

### Added

- **Old `.xls` workbooks open as a grid with tabs.** With LibreOffice
  installed, a legacy workbook is converted to xlsx in the jail and read
  by the same grid reader as a current one, so it gets a table per sheet
  with the tabs along the bottom instead of flat pages. ~0.6 s on first
  open; the grid is cached on disk after that, and the daemon checks a
  cached grid's shape and bounds before building a table from it, since
  the cache directory is writable by anything running as the user. If the
  grid cannot be read, the page view is the fallback.
- **Spreadsheet figures keep their number formats.** xlsx cells were shown
  as bare numbers apart from dates and percentages: €1,234.50 read
  1234.5. The format codes are now applied — decimals, thousands
  separators, currency written quoted, escaped or as a `[$€-408]` locale
  tag, scientific notation, and the positive;negative;zero sections that
  put negatives in brackets or show zero as a dash — rounding half away
  from zero as Excel does. Conditional sections, fractions and digit
  layouts such as phone numbers still show the plain number.
- **Slide decks and the legacy office formats preview with LibreOffice.**
  `.pptx`, `.ppsx` and `.odp` decks get a page per slide, and the old
  binary `.doc`, `.xls` and `.ppt`, and `.rtf`, are laid out as pages —
  all through the same in-jail conversion Word documents already use,
  cached the same way. Each used to show only the metadata card. Without
  LibreOffice (or with `office_engine = builtin`) a deck shows the
  thumbnail it embeds, with its text a button away, and the legacy formats
  and RTF keep the card. The format is decided from the content: the zip
  members or ODF `mimetype`, the main stream's directory entry in the OLE2
  container the binary formats share — checked as a directory entry, so a
  stream name typed into a document cannot decide it — and RTF's opening
  `{\rtf`. An `.odp` with no LibreOffice is no longer read by the
  built-in layout as a column of loose text boxes. CI installs Impress and
  Calc alongside Writer so the real conversions are tested.
- **Continuous integration.** A GitHub Actions workflow runs the test
  suite on every push and pull request, on Python 3.10 (the oldest
  `install.sh` accepts) and 3.14, against the PySide6 wheels on Ubuntu,
  with LibreOffice Writer installed so the real `.docx` conversion is
  tested too — nothing in the suite skips there.
- **The PDF outline and search tests run everywhere.** They used to skip
  unless pointed at a real document, and the search ones asserted match
  counts in one particular file only its author had. They now run against
  a nine-page PDF that `tests/samplepdf.py` writes from raw PDF syntax, with
  a nested outline and known text, so the expected counts come from what
  was written. Two checks are new: the outline comes back exactly as
  written, each entry landing on its own line, and every search highlight
  covers the words it reports, read back from the page. The second catches
  a match offset not mapped back through the text flattening, which shifts
  each highlight sideways and that nothing else noticed.
  `QUICKVIEW_SEARCH_PDF` is gone; `QUICKVIEW_TEST_PDF` still overrides the
  outline sample.

### Fixed

- **Percentages show the decimals their format asks for.** Every
  percentage was printed with all its digits, so `0.0%` showed 52.65%
  where Excel shows 52.7%, and `0.00%` showed 22.3% for 22.30%.
- **The test suite no longer aborts depending on how it is started.**
  `python -m unittest discover tests` died with SIGABRT partway through:
  without `-t .` the files load as top-level modules, so the shared
  `QApplication` in `tests/__init__.py` was never made, `test_epub` made a
  `QGuiApplication` instead, and the first widget test in `test_media`
  aborted Qt. Every test module now creates a `QApplication` itself — it
  serves the non-widget tests just as well — so discovery from anywhere,
  and running a single file directly, all work.
- **The unreadable-config test skips itself as root.** Root reads a
  mode-000 file anyway, so in a container the case could not be set up
  and failed instead.

## 2026-09-25

### Added

- **Word documents preview exactly when LibreOffice is installed.** A
  `.docx` or `.odt` is converted to PDF by LibreOffice inside the bwrap
  jail and shown by the PDF page view, so photos keep their size and
  position, text wraps around them, and fonts, justification, headers and
  EMF logos all appear as they do in the document. ~1.3 s on first open,
  cached after that. Machines without LibreOffice — or a conversion that
  fails or takes over 12 s — fall back to the built-in layout. The office
  cache key now names the engine, so installing or removing LibreOffice
  never leaves the other engine's pages on screen.

  Speed over fidelity is a setting: `office_engine = builtin` in
  `[preview]` skips LibreOffice even when it is installed.

### Fixed

- **Pages are sharp on scaled screens.** PDF, office, EPUB and Markdown
  pages were rendered at their logical width and then stretched by the
  compositor, so at 125 % or 150 % scaling they were visibly blurry next
  to Okular. They are now rendered with the window's device pixel ratio —
  asked of the window, since under Wayland fractional scaling only it
  knows the exact 1.25 — and shown at the same size with all the pixels.
  Layout is unchanged: books and Markdown are painted at the higher
  resolution, not re-flowed, and search highlights, outline and chapter
  positions keep their logical geometry. The ratio is part of the page
  cache key, and each page records the ratio it was actually rendered at.
- **The built-in .docx layout is much closer to the document.** Images
  are drawn at the size the document gives them instead of a fixed 420 px;
  text in a table or text box is no longer printed twice; `<w:b w:val="0"/>`
  ("not bold") is no longer bold; headings are found by style *name*, so a
  Greek or German Word's headings are recognised; alignment, indents,
  paragraph spacing, page and line breaks, tabs, run sizes, colours, fonts,
  strike-through and super/subscript are carried over; and EMF/WMF images,
  which Qt cannot decode, are left out instead of leaving a gap.
- **`install.sh` no longer exits silently on distros without a packaged
  PySide6** (Ubuntu 22.04/24.04, Mint). The location probe added on
  2026-09-23 failed under `set -e` when PySide6 was absent, ending the
  script before it could install the private copy. Verified by clean
  installs in Ubuntu 22.04 and 24.04 containers, alongside Fedora, Debian 13
  and Arch.
- **The Arch/CachyOS hint for missing Qt modules was wrong.** QtPdf lives in
  `qt6-webengine` and QtMultimedia in `qt6-multimedia`, both optional for
  `pyside6`; the hint now names them instead of `pyside6`, which the user
  already has.

## 2026-09-23

### Added

- **Shebangs decide the language when there is no extension.** A script
  kept as `~/bin/deploy` rather than `deploy.sh` used to preview as grey
  text; its `#!` line is now read instead. The content is already decoded
  by the time the lexer is chosen, so this costs one string split and no
  extra I/O.

  Pygments' own `guess_lexer()` is deliberately not used. It runs every
  lexer's `analyse_text()` over untrusted content — the slow, regex-heavy
  surface the filename path exists to avoid — and it is wrong often enough
  to matter: `#!/usr/bin/env node` and `#!/usr/bin/awk -f` both guess "Text
  only", and `#!/usr/bin/php` guesses JavaScript. Reading the interpreter's
  name off the line is exact. `env` is unwrapped, including `-S` and
  leading `VAR=value` assignments, and a version suffix is trimmed
  (`python3.12` → `python`). A small table covers the names Pygments has no
  alias for (`node`, `deno`, `dash`, `Rscript`, …) or resolves wrongly
  (`v` is the V language, not Verilog).

  An extension Pygments recognises still wins; the shebang only fills the
  gap where there is none.

- **`[logging] log_level`**, one of `error`, `warning`, `info`, `debug`,
  defaulting to `info`. The daemon used to be pinned to `DEBUG`, so every
  install wrote cache hits and worker lifecycle to `quickview.log` and the
  journal forever. Override for one run with `QUICKVIEW_LOG_LEVEL`. Crash
  capture is unaffected: a native crash still lands in `crash.log` whatever
  this is set to.

### Changed

- **A distribution's own PySide6 and Pygments are used when they are good
  enough.** `install.sh` now builds `.venv` with `--system-site-packages`
  and only pip-installs PySide6 when the system has none usable (6.4+, the
  release that added the QtPdf bindings). An existing virtualenv is
  upgraded in place by flipping the flag in `pyvenv.cfg`, which the
  interpreter re-reads at every start.

  Mostly a disk saving: measured on one machine, `.venv` drops from 672 MB
  to 13 MB. Memory improves too, but modestly. Sharing the distribution's
  Qt with Plasma's processes takes the daemon's private-clean pages from
  14.7 MB to under 0.1 MB; against that, the distribution splits Qt into
  more libraries than the bundled build loads (17 against 6), and the extra
  relocations add ~8.6 MB of private-dirty. Net, over three runs of a
  freshly started daemon: PSS 51.2 MB to 46.7 MB, exclusive (private) pages
  44.9 MB to 38.9 MB. Plain RSS *rises*, 77 MB to 112 MB, because it counts
  those extra shared libraries in full — which is why it is the wrong
  number to quote here.

  The saving depends on something else on the desktop already having the
  libraries resident, which under Plasma it does; on a bare session it
  would be smaller.

  The jail reaches system site-packages without change: `/usr` is already
  bound read-only. It does not reach `~/.local/lib`, which
  `--system-site-packages` also exposes and which sits *ahead* of `/usr` on
  `sys.path`, so the installer checks where a module resolves rather than
  only that it imports — an earlier `pip install --user PySide6` would
  otherwise satisfy every check and then be missing inside bubblewrap.

  PySide6 is probed by module rather than by a bare `import PySide6`, since
  distributions split it up differently. `QtCore`, `QtGui`, `QtWidgets` and
  `QtNetwork` are required; `QtPdf`, `QtWebEngine` and `QtMultimedia` are
  imported lazily and cost exactly one preview type each, so a missing one
  is named on the way past rather than triggering a whole private Qt.
  `./install.sh --pip-qt` forces the old behaviour.

## 2026-08-30

### Added

- **A Breeze panel theme**, behind `panel_theme = breeze` in the new
  `[appearance]` section. The panel has always been a Quick Look impression
  — a fixed dark window, close button top left, indifferent to the Plasma
  colour scheme — and that is still the default and still the point. The
  alternative reads every colour from the running `QPalette`, so it follows
  the user's own scheme, light or dark, accent included, rather than being a
  second hardcoded theme that happens to resemble today's Breeze. It also
  squares the corners and moves the close button to the right.

  The colours used to be written into eleven stylesheets as some thirty
  literals. They now go through one set of tokens in `theme.py`, which is
  what makes a second theme possible at all — and the default palette is
  those same literals, so the default look is unchanged: a test compares the
  built stylesheet against the previous one declaration by declaration.

- **Playback speed and mute** on video and audio, at 0.25x through 2x. Both
  are new ops on the jailed player, and the rate is clamped worker-side.

- **Photoshop previews (`.psd`, `.psb`).** Qt ships no PSD handler, so these
  used to fail with "unsupported or corrupt" — a .psd matches `image/*` and
  went to the image path, which could not read it. QuickView now parses the
  format itself, in the jail with every other parser and using nothing but
  the standard library.

  It reads the flattened composite Photoshop already stores next to the
  layers and never looks at a layer, so the expensive half of the format is
  the half a preview skips. The compressed image data is preceded by a table
  of every scanline's length, which means rows can be *seeked past* rather
  than decoded — so the cost tracks the size of the preview rather than the
  size of the document, the same bargain the image path already strikes with
  libjpeg's DCT scaling. On a 6000x4000 file, 95 ms against 281 ms for the
  same decode undecimated, and the gap widens with the document. How busy the
  artwork is matters more than how big it is: dithered or high-frequency
  two-colour scanlines code as thousands of short PackBits opcodes rather
  than dozens of long ones and cost around 25x as much to walk, so the same
  12 megapixels range from 95 ms to 733 ms.

  RGB, greyscale, indexed, CMYK and duotone all decode, at 8 or 16 bits, in
  PSD and PSB, RLE-compressed or raw. CMYK is converted by drawing the black
  plate over the other three with a multiply blend, which is exactly the
  formula and leaves the per-pixel work to Qt. A file saved without "Maximize
  Compatibility" has no composite at all and falls back to the JPEG thumbnail
  in its image resources; Lab and 1-bit bitmaps do the same.

  Because the fallback lives inside `decode_image` rather than in a branch of
  its own, PSD inherits the two-tier cache, the raw-ARGB32 wire frame, the
  neighbour prefetch and the document's real dimensions in the titlebar
  without any of them knowing the format exists.

- **Krita and OpenRaster previews (`.kra`, `.ora`).** Both are a zip holding
  the flattened image as an ordinary PNG, which Krita writes precisely so a
  thumbnailer never has to understand a layer stack. Reading that one member
  is the whole decoder, and it is handed back to the image path so it gets
  the scaled read and the dimensions like any other PNG. `preview.png` is the
  fallback for a file saved without the merged image.

- **Illustrator previews (`.ai`).** An `.ai` has been a PDF since Illustrator
  9, so it is handed to the PDF page view and streams, scrolls, searches and
  caches identically. The daemon reads four bytes to check for `%PDF` first —
  a sniff, not a parse, so no decoder moves back into the daemon — and a
  PostScript-only `.ai` from before that still gets the metadata card.

### Fixed

- **Clicking the seek bar seeks there.** A QSlider's groove is a page-step
  control by default, so a click moved the handle a fixed nudge towards the
  cursor and dragging it was the only way to get anywhere. The whole
  timeline is now the target, as it is in every media player. Position
  reports from the player are also ignored while the handle is held, which
  stops it snapping back mid-drag.

### Security

- The PSD reader is the first format QuickView parses by hand, so every
  length field in it is checked against the real file size before anything is
  allocated or skipped, and the canvas, channel count, resource walk,
  thumbnail resource and decimated result are each capped. The zip member a
  `.kra` preview comes from is bounded both by its declared size and by what
  it actually yields, so a lying header buys nothing. A malformed file still
  only takes down its own throwaway worker.

## 2026-08-27

### Added

- **EPUB previews.** Books used to get the metadata card. They are now laid
  out as pages by the same pipeline PDFs and office documents use: the spine
  is converted to the HTML subset `QTextDocument` understands and inserted
  chapter by chapter through a cursor, with each spine document starting a
  new page the way a chapter does in print. No reader engine is involved and
  nothing new runs outside the jail.
- **Markdown renders**, on the same titlebar button HTML uses: rendered
  pages by default, the highlighted source behind **Code**, and the choice
  is remembered for the session. Qt parses Markdown itself (md4c, behind
  `QTextDocument.setMarkdown`), so this needs no library and no HTML
  engine — the parse runs in the jail like every other one, a `markdown`
  op streams page images, and they scroll and cache exactly like a PDF's.
  Tables, task lists and fenced code all render, and the page palette
  (`book_theme`) applies here too, so Markdown is themed with the books.

  **Its headings are the sidebar**, nested by their hashes and carrying the
  page each lands on, on the same ☰ button as a PDF's bookmarks and a
  book's chapters. A Markdown file has no table of contents of its own, so
  its headings are it.

  Three things happen to a document before it is painted, all of them
  fixes for things that looked broken:

  - **Raw HTML tags are stripped outside code.** Qt hands an HTML block to
    its rich-text importer mid-parse, and an unbalanced one — a
    `<p align="center">` wrapping two `<img>` tags, the way half of
    GitHub's READMEs open — swallows the rest of the document. This
    project's own README imported as 2,420 characters of the 22,222 it
    has, with every paragraph after the block silently gone. Fenced blocks
    and inline code keep their tags, so a README documenting HTML still
    shows it.
  - **Images are replaced by a note naming them.** A Markdown file's images
    sit next to it on disk and the jail has no disk — the file arrives as a
    descriptor. Qt resolves those relative paths against the worker's
    working directory, so an image loaded only when the document happened
    to live inside this application's own folder: right for the project's
    README, wrong for every file a person actually previews.
  - **Fenced code is allowed to wrap.** Qt imports it as unbreakable lines,
    and a page cannot scroll sideways: a long line was simply cut off at
    the margin. Wrapping reads slightly wrong; losing half the line reads
    as a bug.

### Fixed

- **Clicking a contents entry scrolled to the page, not to the heading.** A
  rendered page here is routinely taller than the window — 2326 px against
  a 1451 px viewport on a 3072×1728 screen — so an entry that carried only
  a page number scrolled to the top of that page: every section of one
  chapter went to the same place, and clicking one whose heading was
  already on screen did nothing at all. Entries now carry where on the page
  they sit, taken from the bookmark's own destination for a PDF and from
  the layout that produced the pages for a book or a Markdown file, and the
  view scrolls there. Contents cached by the previous version are
  superseded rather than reused, since they have no offsets in them.
- **A cached document with no cached contents re-rendered on every open.**
  The contents entry is now written even when a document has no headings at
  all, so "none" is stored as an answer rather than read back as "unknown".
  Affected books and Markdown files alike.

- **Ctrl+F works in EPUB previews**, with the same highlighting, the same
  Enter / Shift+Enter stepping and the same match counter as a PDF. The
  route there is different: a book has no text layer to extract, so a new
  `epubsearch` op lays the book out again in the jail — same page width,
  same style sheet, so the same layout the pages were painted from — and
  measures each match against it line by line. What comes back is what the
  PDF search returns, `{"matches": [{"page", "rects"}], "capped"}`, so the
  daemon paints both with the code it already had. A match that wraps gets
  one rectangle per line rather than one slab across the gap, and a match
  on a page past the render cap is dropped rather than highlighted where
  nobody can scroll.

  Laying the book out twice (once to render, once to search) is deliberate:
  a rectangle only means something in a layout, and the alternative — the
  daemon holding a parsed book — is exactly what the jail exists to
  prevent. Office documents still have no find, for the same reason they
  never did: nothing re-lays them out to search.
- **`book_theme`, a page palette for EPUB previews**: `paper` (the default),
  `sepia`, `dark`, `gruvbox-dark` and `gruvbox-light`. The worker paints the
  page background, body text, headings and quotations from the chosen
  palette — only the page, never the panel around it, which is application
  chrome. Books are also laid out in a serif at 11pt now, matching the
  office path. The theme name goes into the page cache key, so switching
  themes re-renders instead of serving back the old theme's pages, and an
  unknown name in the config file reads as the default rather than as a
  book with no colours at all.
- **A contents sidebar, on a ☰ button top left.** It lists a PDF's bookmarks
  or a book's chapters — nested, with page numbers — and clicking an entry
  scrolls to that page. The button appears only for documents that have a
  table of contents, and the sidebar stays open across files once opened.

  The two sources are different but the sidebar is not. A PDF's outline
  comes from a new `pdfoutline` op that walks Qt's bookmark model in the
  jail; a book's chapters come out of the layout pass that produced its
  pages (the cursor position where each chapter was inserted is what makes
  a page number possible), so they ride on the render's header instead of
  costing a second parse. Both are cached next to the page images, so
  reopening a document brings its sidebar back without a worker. Entries
  pointing past the last rendered page are dropped rather than shown as
  rows that scroll nowhere.

  Both kinds of EPUB table of contents are read — the EPUB 3 navigation
  document and the EPUB 2 NCX — and a book with neither still gets a
  chapter list, built from each spine file's first heading. A contents
  entry pointing at a fragment *inside* a file splits that file at the
  fragment, so books that keep several chapters in one document still land
  on the right page.

- **Spreadsheets are previewed as a grid, with a tab per sheet.** `.xlsx`,
  `.xlsm` and `.ods` used to be poured into the office page view, which
  turned a workbook into an undifferentiated wall of bordered rows labelled
  "Sheet 1", "Sheet 2" — the sheets' real names were never read. They now go
  to a new `sheets` worker op that reads the cells in the jail, and the
  daemon shows them in a table: the sheet names on tabs along the bottom,
  the workbook's own column letters and row numbers in the gutters, numeric
  columns aligned right, and the header row picked out when the first row
  looks like one. Hidden sheets are skipped, as they are in Excel.

  Cells are now placed by their own reference rather than by the order they
  appear in, so a sparse row — one that omits its empty cells, which is what
  the format writes — keeps its columns instead of sliding every value to
  the left. Dates and percentages in xlsx are ordinary numbers wearing a
  number format, so `styles.xml` is read as well, including custom format
  codes; without it every date in a workbook showed as a five-digit serial.
  Floats print rounded (`15.7`, not `15.700000000000001`).

  Each sheet is bounded — 2000 rows, 64 columns, 512 characters a cell, 24
  sheets — so a million-row workbook costs what a small one does. A file
  that will not parse as a grid still falls back to the office page view,
  and from there to the metadata card.

## 2026-08-26

### Added

- **A test suite**: `python -m unittest discover -s tests`. 51 checks in
  about a second, no display required — the wire format (including the
  non-UTF-8 filenames that used to fail silently), the settings parser, the
  raw-frame bounds guard, cache encoding and keys, and the PDF search's text
  flattening and geometry.
- **`uninstall.sh`**, which reverses what `install.sh` did: the daemon and
  its unit, the Dolphin service menu, the launcher on `PATH`, the cache and
  the logs. Settings are kept unless `--purge` is passed, and the checkout is
  never touched.
- **A settings file at `~/.config/quickview/quickview.conf`**, written with
  its defaults commented in the first time the daemon starts and never
  rewritten afterwards. It carries the syntax-highlighting style, the text
  preview limit, the PDF page cap and both cache sizes; each still has a
  `QUICKVIEW_*` environment variable that wins over the file. Previously the
  one setting that existed had to go in the systemd unit's `Environment=`,
  which `install.sh` regenerates on every run — so it was silently lost on
  the next upgrade. Out-of-range values are clamped and an unparseable file
  falls back to the defaults. The many other constants are safety bounds on
  untrusted input and stay in the code deliberately.
- **Ctrl+F finds text in a PDF preview.** Matches are highlighted in place
  and Enter / Shift+Enter step through them, scrolling each into view. The
  daemon owns no PDF parser, so the query goes to a jailed worker (a new
  `pdfsearch` op) that extracts the text and answers with match rectangles
  already in page pixels — the daemon only paints them. Multi-word phrases
  work, including across a line break: a PDF's text layer breaks lines with
  `\r\n`, so the page text is matched with whitespace collapsed and each
  match is highlighted with one rectangle per line it spans rather than one
  box swallowing the gap between them. Some PDFs position their glyphs
  instead of emitting spaces, and Qt extracts those as
  "accordingtoyoursoftskills"; when an exact multi-word search finds
  nothing, it retries ignoring whitespace altogether and marks the result
  `≈` so an approximate hit is never mistaken for a literal one. Search
  covers the pages the viewer actually shows (the first 50), because a hit
  reported on page 73 of a document that stops rendering at 50 is worse
  than silence. Office documents share the PDF view but are laid out through
  `QTextDocument`, so they do not get the find row.

### Performance

- **Photo previews open about 2.4x faster: ~338 ms to ~127 ms** (median of
  15 cold renders across five photos, measured from the daemon's own
  `preview:` -> `rendered:` log). The worker used to PNG-compress every
  decoded image to hand it down a Unix socket to a process that immediately
  decompressed it — ~107 ms to write and ~31 ms to read back, more than the
  JPEG decode in front of it. It now sends raw ARGB32 pixels (~0.4 ms each
  way) and the daemon paints as soon as they land. The copy the disk cache
  wants still gets made, but in the jailed worker *after* the image is on
  screen, so it is off the user-visible path. BMP would have been the
  obvious middle ground and is wrong: Qt's BMP writer drops the alpha
  channel, so transparent PNGs and SVGs would have come back opaque.
- **Reopening a photo is ~3.4x faster: ~54 ms to ~16 ms**, and the disk
  cache holds ten times as much. Preview images with no alpha are cached as
  JPEG rather than PNG — ~24 ms to write and ~11 ms to read back against
  ~111 and ~37, at a tenth of the size, so the 256 MB cap now fits over a
  thousand previews instead of ~110. Images that carry alpha stay PNG,
  because JPEG has none and a transparent logo would come back on a black
  square. The `QuickView:OrigSize` tEXt chunk survives as a JPEG comment
  marker, so the cache-hit path is unchanged, and existing PNG entries stay
  readable.
- Prefetching a neighbouring image no longer ships pixels it throws away —
  it warms the disk cache and displays nothing, so it asks for the encoded
  frame alone.
- **The fast path is now a compiled client (`client.rs`).** Handing a path
  to the warm daemon cost ~29 ms, essentially all of it Python interpreter
  startup — `urllib.parse` alone was ~6 ms of it. The Rust client does the
  same work in ~0.8 ms, so `bin/quickview somefile` now returns in ~4 ms
  end to end instead of ~40 ms. No crates, so `rustc` builds it without
  Cargo; `install.sh` skips it with a note when there is no toolchain, and
  `client.py` stays as the fallback (itself now ~15 ms, having shed its
  `urllib` import).

### Security

- **The fast-path client no longer parses anything.** Percent-decoding and
  path normalization moved from the client to `ipc.py` on the daemon side,
  so the one QuickView process that runs *outside* the bubblewrap jail now
  forwards its arguments byte for byte and never inspects them. Filenames
  are untrusted input — a crafted name inside a downloaded archive is a
  plausible vector — and this keeps every parser on the memory-safe side of
  the wire. It also leaves `normalize_arg` with a single implementation,
  which is what its docstring always asked for.

### Fixed

- **Opaque images are cached as JPEG again.** The format check used
  `hasAlphaChannel()`, which answers about the image *format* and not its
  pixels — so screenshots and most PNGs, which decode to ARGB32 while being
  fully opaque, were cached as multi-megabyte PNGs. The pixels are now
  actually checked (~2 ms, in the worker, after the image is on screen): one
  sample PNG's cache entry went from 190 KB to 76 KB.
- **Preview cache entries now carry a format version.** Keys were built from
  the source file's path, mtime, size and fit box — nothing about *how* it
  was rendered — so changing a renderer left the old output being served for
  ever. The PDF path had been working around this with hand-bumped `v2`
  strings in its variant names; a single `CACHE_VERSION` now covers every
  entry.
- **Filenames that are not valid UTF-8 now preview instead of silently
  failing.** The wire format decoded with `errors="replace"`, which turned
  an undecodable byte into U+FFFD — a path that does not exist. Both
  directions now use `surrogateescape`, the codec `sys.argv` and `open()`
  already speak, so those bytes round-trip intact.

### Changed

- The client→daemon message gained a leading field: the sender's working
  directory, which the daemon resolves relative arguments against (its own
  cwd, under systemd, is not the client's). An old daemon left running
  across an upgrade would misread the new format; `install.sh` already
  restarts the service rather than leaving a running one alone.

## 2026-08-25 — first public release

The release that took QuickView from a personal tool to a published one:
sandboxed rendering for every format, a window that behaves itself on
Wayland, and an installer that works on a machine other than the author's.

### Security

- **Every format QuickView decodes itself is now parsed outside the
  daemon.** Images, PDFs, animations, audio, video and the syntax
  highlighter all run in a bubblewrap jail (HTML is the exception, and
  stays in Chromium's own renderer sandbox); the daemon
  keeps the window, the socket and the cache, and holds no decoder. The
  previously documented exceptions — animated GIFs (`QMovie`) and
  audio/video (`QMediaPlayer`) — are gone.
- **The jail no longer has access to user files at all.** The target file
  arrives as a file descriptor over `SCM_RIGHTS`, so there is nothing to
  bind-mount. Verified from inside a worker: `/etc/passwd` and
  `$XDG_RUNTIME_DIR` unreachable, the home directory shows only the bind
  skeleton (1 visible entry where the real directory has 32), and
  `connect()` fails with `ENETUNREACH`.
- Added `--cap-drop ALL` to the jail.
- Bounded the frame-length field in the worker stream. It came from the
  helper and was buffered unchecked, so a compromised helper could ask the
  daemon to allocate 4 GiB; frames over 64 MiB now kill the worker.
- `QUICKVIEW_STRICT_SANDBOX=1` now only governs HTML (source view instead
  of QtWebEngine). GIF and media no longer need it — they are always
  jailed.

### Added

- **Archives and office documents preview instead of falling through to the
  metadata card.** Archives (zip, rar, 7z, tar and friends) show a contents
  listing with sizes; nothing is ever extracted, only headers are read, so a
  zip bomb is inert. zip and tar go through Python's standard library, and
  everything else through `bsdtar`/`7z`/`unrar` — which read the archive from
  `/dev/fd`, so the jail still gets a descriptor and no path, and no copy is
  made. Missing listers, encrypted headers and corrupt files fall back to the
  metadata card without an error.

  Office documents are **laid out as pages** and shown by the same view PDFs
  use, so they scroll, stream and cache page by page. docx, odt, xlsx and ods
  are converted in the jail to the HTML subset `QTextDocument` understands —
  headings, bold/italic, tables, embedded images — and rendered with Qt
  alone: no office suite, no QtWebEngine. Measured: a 7-page .docx converts
  in 8 ms and renders a page in 7 ms.

  Slide decks are deliberately not previewed: their content is absolutely
  positioned graphics with no path through QTextDocument, and the only
  thing that lays them out is a full office suite. Legacy binary
  .doc/.xls/.ppt are out for the same reason; both show the metadata card.
- **Syntax highlighting in the text preview**, via Pygments — and it runs in
  the jail, not here. Lexers are regexes; a file written to make one
  backtrack should cost a throwaway worker, not the process holding the
  window and the IPC socket. The worker returns the text plus
  `[start, length, colour]` spans, and the daemon paints ranges: no lexer
  and no HTML parser on this side. Text previews therefore go through a
  worker now, with the old in-process read (`show_text_direct`) kept as the
  fallback for when the sandbox is unavailable.

  Files over 256 KiB stay plain — 83 KiB of Python lexes in ~245 ms, but
  1 MiB takes ~1.5 s, slower than the preview it decorates. Pick any
  Pygments style with `QUICKVIEW_CODE_STYLE` (default `one-dark`); with
  Pygments absent the preview is simply uncoloured.
- `worker.py` — warm jailed worker for images, PDF pages and animation
  frames, decoding from a passed descriptor.
- `media_worker.py` — jailed audio/video player. It owns the audio clock
  (PipeWire socket bound into the jail), so Qt does A/V sync in there;
  video frames cross to the daemon through a shared `memfd` and the daemon
  only blits them. Play/pause/seek are socket messages.
- `renderers.py` — the decoders themselves, shared by the workers and the
  standalone scripts.
- Worker pool with pre-booted hot spares, so the ~150 ms Qt import is paid
  before a preview needs it rather than during one. Each worker still
  handles exactly one file and then exits.
- Animation playback without an animation parser in the daemon: frames are
  decoded in the jail and cycled as pixmaps on a timer, bounded at 512
  frames / 256 MiB.
- Debug log line recording who sized the preview window and against which
  screen, for diagnosing a window that opens at the wrong size.

### Changed

- **Previews are faster than before they were sandboxed.** Measured on this
  machine: PDF page 1 on a cache miss 583 ms → 122 ms, image on a cache
  miss ~150 ms → 56 ms, cache hit ~20 ms → 2 ms, prefetched neighbour 2 ms.
  Entering the jail costs ~3 ms; the old cost was importing Qt per file.
- The window is fully opaque. The panel was `rgba(34, 34, 38, 245)` and the
  hairline border was translucent white; both are now solid colours, as are
  the button, slider and text backgrounds. `WA_TranslucentBackground` stays
  on — it is what makes the rounded corners and drop shadow composite —
  but nothing shows through the panel.
- Text previews are read on a pool thread — now the fallback path, since
  text normally goes through the jail — so a file on a stalled NFS or
  FUSE mount can no longer freeze the window and the daemon socket. The
  window is sized for text up front instead of being resized after the read
  lands.
- `render.py` and `render_pdf.py` are now thin CLI wrappers over
  `renderers.py`, kept for reproducing a render by hand. The daemon talks
  to `worker.py` instead.
- README rewritten around the new boundary, including an honest list of
  what still runs in the daemon: HTML (in Chromium's own renderer sandbox),
  text bytes, MIME sniffing, and the daemon decoding the workers' PNG
  output.

### Fixed

- **A text preview could crash the daemon.** `FileReader` was a
  `QRunnable` the daemon held exactly one reference to, so previewing a
  second file while the first read was still blocked (the stalled-mount
  case the reader thread exists for) dropped the last reference to a
  running object — and the pool touches a runnable again after `run()`
  returns. It is a plain `QObject` now, handed to the pool as a bound
  method, and every in-flight reader is held until its signal lands.
- **Dismissing a media preview could hang the whole daemon.** `stop()`
  waited on the killed worker with no timeout on the GUI thread, so a
  worker wedged in an uninterruptible read took the window, the shortcuts
  and the IPC socket down with it. Bounded to 2 s, like `Worker.kill()`.
- **A truncated render was reported as a successful one.** Once the
  worker had sent its `{"ok": true}` header it could not take it back, so
  a PDF that died on page 7 of 50 looked complete: the daemon inferred
  success from "a header arrived". The worker now ends a stream with a
  zero-length frame, a failure after the header closes the socket without
  one and explains itself on stderr, and the daemon treats a stream with
  no end marker as truncated.
- **Video frames could arrive out of order.** The media worker recycled
  its two shared-memory slots per decoded frame with no acknowledgement,
  so a daemon busy with layout was handed a slot whose pixels had already
  been replaced. A slot is now reused only after the daemon acks copying
  it out, and the worker drops a frame rather than race for it.
- Hardened `MediaSession.read_frame()` against its own worker: `slot`,
  `w`, `h` and `stride` were only checked as `stride * h`, so a frame
  claiming `w=100000, h=1, stride=4` passed and then read ~400 KB past a
  4-byte buffer. Every field is now range-checked, `stride` against
  `w * 4`, and a negative slot is rejected.
- Bounded the pixel height of a rendered PDF page. A page declared as
  1 pt × 10000 pt asked for a ten-million-pixel column — tens of GB of
  QImage, in a jail that has no memory limit of its own.
- Bounded animation frames in the daemon as well as in the worker: 512
  screen-sized pixmaps is gigabytes of memory in the process that owns
  the window, and the job watchdog restarts on every frame, so a worker
  streaming for ever was never cut off.
- Fixed the font cache bind. The jail runs with `--clearenv` and
  `HOME=/tmp`, so fontconfig looks in `/tmp/.cache/fontconfig` and never
  saw `~/.cache/fontconfig` bound at its real path — which on a system
  with no `/var/cache/fontconfig` meant binding `/etc/fonts` with no
  usable cache, the 749 ms worst case the code set out to avoid.
- Spare workers now have their stderr drained from the moment they are
  spawned rather than from the moment they get a job: a worker that
  chattered during Qt's boot could fill the 64 KiB pipe buffer and block
  before ever reading its request, failing the job on the watchdog.
- `SandboxJob` objects are deleted when they finish. One per preview
  *and* one per prefetch accumulated as children of the window for the
  life of a daemon that is meant to run for weeks.
- Animation frames are no longer unpacked from a payload shorter than the
  4-byte delay header, and the prefetcher skips APNG as well as GIF (it
  was warming an image-op cache entry that the animation path never
  reads).
- Throttled position updates from the media worker to the 200 ms the
  constant always described: Qt 6 dropped `setNotifyInterval`, so the
  worker was sending a message per decoded frame to drive one slider.
- **The panel opened wherever the compositor felt like putting it.** The
  daemon is a native Wayland client and Wayland ignores `QWidget.move()`,
  so `center_on_screen()` had been doing nothing for the whole session:
  KWin placed the window, and every resize (a PDF swapping its "Loading…"
  card for the page column) grew it from that spot. The window is now a
  transparent overlay the size of the work area with the panel centred
  inside it — in *screen* coordinates, so the panel lands dead centre even
  if the compositor puts the overlay somewhere else. A preview now opens
  centred and stays centred as it resizes. Dragging the titlebar slides
  the panel within the overlay.

  Two things the overlay must *not* do, both learned the hard way. It is
  not fullscreen: KWin lowers an inactive fullscreen window below the
  focused one, which made a preview raised by the daemon — no activation
  token, since no click started it — disappear behind other windows about
  half the time. And its input region is set through `QWindow.setMask()`,
  never `QWidget.setMask()`: the widget one clips painting as well as
  input, so a panel that shrank (a PDF, then a text file) left the older,
  larger panel's pixels on screen with the new one drawn inside them — a
  window within a window. Either way the point of the mask is that clicks
  outside the panel go to whatever is underneath, exactly as they did when
  the window was panel-sized.
- **A PDF scrolled itself back to the top for the first second or two.**
  Pages were appended to the column as they decoded, so the scrollable
  range grew for as long as that took — on a 30-page document at 1689 px
  a little over two seconds. Scrolling in that window was clamped to the
  two pages that existed, and once the rest arrived the reader was left
  near the top of a 69499 px column, which looks exactly like the view
  scrolling up on its own. Every page now gets a placeholder of its real
  size before any pixels arrive (sizes come from the cached PNGs' IHDR
  headers, 24 bytes each, no decode), so the range is final on the first
  paint and an early scroll lands where it was aimed.
- **A partially cached PDF restarted from page 1 on every open**, throwing
  away the pages already on screen and jumping the reader back to the top —
  it looked like the preview closing and reopening. A missing page (the
  pruner dropped it, or an earlier render was cut short when the panel
  closed) now resumes the render at that page and appends into the view
  that is already up, so the scroll position survives and each open makes
  forward progress instead of re-rendering the same prefix. The worker's
  `pdf` op takes a `start` page for this.
- **PDF pages rendered as black text on a transparent background.**
  `QPdfDocument.render()` returns an ARGB image and a PDF paints glyphs but
  not its page, so nothing was behind the text. Pages are now composited
  onto white. Cached pages from before the fix are bypassed by a bumped
  cache variant (`pdf{i}v2`).
- Retired workers were left unreaped, leaking one zombie process per
  preview in a daemon that runs for weeks.
- Fontconfig had no config or cache inside the jail, so Qt rebuilt its font
  index on every single render — 583 ms instead of 148 ms for a one-page
  PDF. `/etc/fonts` and the fontconfig caches are now bound read-only.
  (Binding `/etc/fonts` alone is worse than neither, at 749 ms: it enables
  the scan without supplying the cache.)
- `shutil.which("bwrap")` ran on every render and every prefetch; it is
  resolved once.

### Known limitations

- **Slide decks (`.pptx`, `.odp`) are not previewed at all**, and the
  reason is worth recording so nobody re-treads it. Their content is
  absolutely positioned DrawingML, which `QTextDocument` cannot lay out,
  so the only faithful renderer is LibreOffice. That was implemented and
  then removed: `soffice --headless --convert-to pdf` **hangs inside the
  jail** — 90 s with zero bytes on stdout *and* stderr and no output file,
  where the identical command on the host converts a 149-slide deck in
  9 s. Binding `/etc/passwd` did not help; neither did giving it the
  network namespace back. Left enabled it was worse than useless, since
  every deck would wait out the watchdog before falling back. The
  remaining option is a DrawingML renderer of our own (shape geometry in
  EMU, placeholder positions from the slide layouts, pictures from the
  media parts) — no dependency, but charts and SmartArt would be missing.
- Spreadsheet sheets are labelled "Sheet 1", "Sheet 2" rather than by
  their real names; the names are in `xl/workbook.xml` and simply are not
  read yet.
- Office layout is `QTextDocument`'s approximation, not Word's: fonts,
  margins and page breaks differ from what the authoring application
  shows. It is a readable page, not a faithful reproduction.
- Archive entries listed through `bsdtar`/`7z`/`unrar` (rar, 7z, iso) show
  names only — no sizes, and no uncompressed total. The long-listing
  formats differ per tool and per locale, and a preview does not need
  them; zip and tar, which go through the standard library, do show sizes.
- Audio from the jailed player is wired and the socket is reachable
  (`pactl info` succeeds through it), but audible output has not been
  confirmed — this machine currently exposes no real sink (`auto_null`).
- The daemon still decodes the workers' PNG output, so a compromised worker
  could aim a malformed PNG at the daemon's own decoder. One hardened
  format instead of every format Qt supports, but not zero.

## 2026-06-13

- Sandboxed PDF rendering: pages are rendered by a bubblewrap helper and
  streamed one at a time, so page 1 appears while the rest (capped at 50)
  render, each page cached individually.

## 2026-06-12

- Async image rendering via `QProcess` with a 20 s watchdog, replacing a
  blocking `subprocess.run` on the GUI thread; in-flight renders are
  cancelled on navigation and stale results dropped.
- Out-of-process image decoding under bubblewrap (`render.py`), refusing
  untrusted decodes without `bwrap` unless `QUICKVIEW_ALLOW_UNSANDBOXED=1`.
- Two-tier preview cache: in-daemon pixmap LRU plus PNGs under
  `~/.cache/quickview/previews`, keyed by path + mtime + size, 256 MiB cap,
  oldest-first pruning, `--clear-cache`.
- Multi-file selection: the service menu passes `%U`, the daemon protocol
  takes newline-separated paths, and arrow keys page the selection with a
  folder-sibling fallback for single files.
- Rotating log at `~/.local/share/quickview/quickview.log` plus
  faulthandler crash tracebacks in `crash.log`.
- systemd user service (restart on failure) with XDG autostart as fallback;
  the service menu's `Exec` is templated by `install.sh` so the repo works
  from any path.
