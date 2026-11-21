How QuickView was made
======================

QuickView is a file previewer for KDE Plasma in the manner of Quick Look
on macOS: you select a file in Dolphin, press Space, and a panel shows the
file at once, whatever it is (a photo, a PDF, a Word document, a book, a
video, source code, an archive), and Space again closes it.  Mustapha
Alioglou wrote the first versions between June and October 2026.  Nicolas
Vaughan made a fork of it in November 2026, and the fork is the program
described here, which reached version 1.0 on 19 November 2026.  Here I
explain how it was made, in seven stages.

QuickView is free software, under the GNU General Public License, version 3
or later.  It is written with PySide6, the Python binding of Qt 6 (LGPL
3.0), whose QtPdf module renders the PDFs with PDFium (BSD); Pygments
(BSD-2-Clause) colours the source code; bubblewrap (LGPL 2.0 or later)
makes the jail in which every file is read.  Two external programs are
used when they are installed, and never linked: `pdftotext`, from Poppler
(GPL 2.0 or later), for the text of PDFs, and LibreOffice (MPL 2.0) for
the exact layout of office documents.  The full list of the open-source
software QuickView uses, and their licenses, is in
[THIRD-PARTY.md](THIRD-PARTY.md).

Nicolas Vaughan is Associate Professor of Literature at the School of Arts
and Humanities of the Universidad de los Andes, Bogotá, Colombia.

1. The original program
-----------------------

Mustapha Alioglou's program already had the shape it still has.  A daemon
keeps Qt loaded, so the panel appears in about 50 milliseconds, and a
small client, later rewritten in Rust, passes it the file Dolphin gives it
through a Unix socket.  The idea that matters most was there from the
first commit: the daemon never parses a file itself.  Every file is opened
once, and its descriptor is passed to a worker that runs inside a
bubblewrap jail, with no network, no home folder and a read-only system;
the worker decodes the file and sends back pixels or text.  A PDF made to
crash its parser crashes the worker, not the panel.

Over the summer the program learned to show images (also PSD, Krita and
Illustrator files), PDFs page by page, source code with colours, the
contents of archives, Word documents (first with its own layout, then
exactly through LibreOffice), slide decks, spreadsheets, EPUB books with
themes and a table of contents, Markdown, and video and sound with a
player.  It had a disk cache of rendered pages, a settings file, a second
theme that takes its colours from Plasma, and tests that ran on GitHub
Actions.

2. The fork, and a cleanup
--------------------------

I started the fork on 10 November 2026.  The first work was to make the
code easier to change.  The panel was one large module; I split it into a
module per kind of preview (`view_image.py`, `view_document.py`,
`view_office.py` and so on), mixed into one window.  The worker's jobs went
into a table of operations, and the decoders into a package of their own,
`renderers/`.  The check that a worker's answer is still wanted (the user
may have moved to another file while the worker was working) was written
once, instead of in every view.

Some things were missing for my own use.  I have LibreOffice only from
Flathub, so the jail learned to run the Flatpak version inside itself,
with its own nested sandbox.  An office document now appears at once with
the quick layout, and LibreOffice's pages replace it when they are ready,
about a second later.  The neighbours of the file shown, in the folder or
in the selection, are rendered in advance, so the arrows move to the next
file without waiting.  The settings now apply when the file is saved,
without a restart.

3. Running on demand, and a package
-----------------------------------

A daemon that is always loaded costs about 130 MB.  So QuickView is now
started by systemd the first time Space is pressed, through a socket that
is always open, and it can exit when it has been idle for a while; a
setting chooses between this, staying loaded, or exiting after each
preview.  A settings window, with tabs, replaced the editing of the file
by hand, and an About box says who made what.

Then came the package.  `packaging/build-rpm.sh` builds an RPM for
Fedora, signed with my key, and `packaging/release.py` makes a whole
release in one command: it checks that everything is ready, changes the
version, builds and signs the packages, publishes them on GitHub and on
Codeberg, downloads them again to check the signatures as `dnf` would, and
builds them on Copr, from where `dnf upgrade` keeps QuickView current.  An
upgrade restarts a running daemon, so the new code runs at once.  Each
build also leaves the RPM and a Zip bundle of the program in `dist/`.  The
program requires Python 3.15 or later.

4. Space in Dolphin
-------------------

A Dolphin service menu cannot bring its own shortcut: Dolphin keeps those
in the user's copy of its settings, `dolphinui.rc`.  So
`dolphin_shortcut.py` writes "Space opens Quick Look" there when QuickView
starts, and moves Dolphin's own Selection Mode off Space, but only while it
still has its default; a shortcut the user chose is never changed.

This was not enough, and the shortcut kept getting lost.  Reading
Dolphin's source showed why: Dolphin 26.08 forgets the shortcuts of
service menus in its open windows whenever its settings are applied, even
without changes, and saving its shortcuts window afterwards writes the
loss to the file.  The developers of Dolphin fixed it for 26.12.  Until
then, QuickView does two things.  At each login it gives Space back to
Quick Look if the file lost it, unless Space was given to something else.
And a small background service listens for the two moments in which
Dolphin loses the shortcut (signals that Dolphin itself sends on the
session bus) and shows a notification with a button to restart Dolphin,
which closes each window as its own close button would.  With Dolphin
26.12 the service exits at once.  Uninstalling takes the shortcut out
again and gives Space back to Selection Mode.

5. Selecting text
-----------------

The pages of a PDF are pictures, so to select their text QuickView has to
know where each word is.  The jail runs Poppler's `pdftotext
-bbox-layout`, which gives each word of a page with its box, in reading
order, in about 25 milliseconds; QtPdf is used when Poppler is missing.
The text of a page is asked for only when the mouse presses on it.  The
daemon checks every offset and every box before using them
(`text_select.py`), and works out the line and paragraph breaks from the
position of the lines, so a list is not copied with empty lines between
its items.

Markdown files and EPUB books are also shown as pages, laid out by Qt.
For them the jail lays the text out again, with the same width, font and
colours, and reads each word's box from that layout, so the daemon uses
the same selection code.  Office documents use whichever layout drew
their pages: the text of the PDF that LibreOffice makes of them, or Qt's
layout.  Since a LibreOffice conversion takes about a second, all the
pages come back at once, and only the first press waits.  Plain text and
code were always selectable.

6. Zoom
-------

Ctrl and the plus and minus keys, or Ctrl and the mouse wheel, zoom from
25% to 400%.  A zoomed photo is decoded again in the jail at its new size,
never past the original, so it stays sharp; the pages on screen are
rendered again at the new resolution, and those scrolled away go back to
their normal size, so a long reading at 400% does not fill the memory.
The text selection and the search highlights follow the zoom, and the
point under the pointer stays still.

7. Towards 1.0
--------------

With several files selected, the arrows already moved through the
selection.  Version 1.0 adds Quick Look's index sheet: Ctrl+Enter, or a
button, shows all the selected files as thumbnails.  The thumbnails are
the ones Dolphin has already made, read from the freedesktop cache only
while they match the file, or for images, decoded in the jail.

Before 1.0 the whole program was reviewed, and some real problems were
found and corrected.  The worst was that the daemon decoded some images
(the embedded thumbnail of a slide deck, the pages from the cache) with
Qt's automatic detection of the format, so a "thumbnail" that was really
a PDF or an SVG was parsed outside the jail; now the daemon decodes only
PNG and JPEG, by name.  A named pipe called `a.txt` froze the daemon, file
names that are not UTF-8 showed nothing, and a slow search could paint its
results on the next document.  More of what the workers send is now
checked before it is used.

Testing
-------

There are 495 automatic tests, in 33 files, which run in about twelve
seconds without a display (the Qt ones run offscreen); GitHub Actions runs
them with each push.  They cover the routing of each kind of file, the
decoders, the jail and the checks of what comes out of it, the cache, the
settings, the text selection, the zoom, the index sheet, the Dolphin
shortcut and its watch (with stand-ins, so that no test sends anything on
the real session bus), the package and the release script.  The tests of
LibreOffice run only where it is installed.

The new worker operations were also tried inside the real jail, and the
views were checked by eye, by saving pictures of the panel drawn
offscreen.  The diagnosis of the lost Dolphin shortcut was made by reading
Dolphin's source, and the watch was tried against a running Dolphin
without closing it.  The repository has 100 files and around 23,000 lines,
of which about 7,200 are tests.
