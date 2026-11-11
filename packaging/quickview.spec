# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Nicolas Vaughan <nivaca@fastmail.com>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.
#
# Build with packaging/build-rpm.sh, which makes the source tarball.

# The one compiled file is the fast-path client, built with plain rustc and
# stripped; there is no debug information to split out of it.
%global debug_package %{nil}

Name:           quickview
Version:        0.1.3
Release:        1%{?dist}
Summary:        Quick Look style file previewer for KDE Plasma

License:        GPL-3.0-or-later
URL:            https://github.com/nivaca/QuickView
Source0:        %{name}-%{version}.tar.gz

BuildRequires:  python3-devel
BuildRequires:  rust
BuildRequires:  systemd-rpm-macros
BuildRequires:  desktop-file-utils

Requires:       python3
Requires:       python3-pyside6
Requires:       python3-pygments
# Every parser runs in a bubblewrap jail; without it nothing is previewed.
Requires:       bubblewrap
%{?systemd_requires}

# Optional: archive listings beyond zip and tar, and exact office layout
# (QuickView also finds the Flathub LibreOffice on its own).
Suggests:       bsdtar
Suggests:       7zip
Suggests:       unrar
Suggests:       libreoffice-writer
Suggests:       libreoffice-impress
Suggests:       libreoffice-calc

%description
Select a file in Dolphin, press Space, and a floating preview panel
appears, as in macOS's Quick Look: images, PDFs, EPUB books, Markdown,
office documents, spreadsheets, archives, audio, video, HTML and source
code with syntax highlighting. Every parser runs in a bubblewrap jail
with no network and no filesystem. A small daemon keeps Qt loaded so a
preview appears in ~50 ms; systemd starts it on the first preview, and
by default it exits when idle.

%prep
%autosetup -n %{name}-%{version}

%build
rustc -O -C strip=symbols -C panic=abort --edition 2021 \
    -o quickview-client client.rs

%install
# The application: the top-level modules and the renderers package. Not
# the tests, tools or docs.
install -d %{buildroot}%{_datadir}/%{name}/renderers
install -pm 0644 *.py %{buildroot}%{_datadir}/%{name}/
install -pm 0644 renderers/*.py %{buildroot}%{_datadir}/%{name}/renderers/
# Compiled now: the jail binds /usr read-only, so a worker could never
# write its own bytecode, and would compile every module on every start.
%py_byte_compile %{python3} %{buildroot}%{_datadir}/%{name}

install -Dpm 0755 quickview-client \
    %{buildroot}%{_libexecdir}/%{name}/quickview-client
install -d %{buildroot}%{_bindir}
sed -e 's|@LIBEXECDIR@|%{_libexecdir}/%{name}|' \
    -e 's|@DATADIR@|%{_datadir}/%{name}|' \
    packaging/quickview-launcher.in > %{buildroot}%{_bindir}/quickview
chmod 0755 %{buildroot}%{_bindir}/quickview

install -d %{buildroot}%{_userunitdir}
sed -e 's|@PYTHON@|%{python3}|' -e 's|@APPDIR@|%{_datadir}/%{name}|' \
    packaging/quickview.socket.in > %{buildroot}%{_userunitdir}/quickview.socket
sed 's|@QUICKVIEW@|%{_bindir}/quickview|' packaging/quickview.service.in \
    > %{buildroot}%{_userunitdir}/quickview.service
install -Dpm 0644 packaging/80-quickview.preset \
    %{buildroot}%{_userpresetdir}/80-quickview.preset

install -d %{buildroot}%{_datadir}/applications
sed 's|"@DIR@/bin/quickview"|%{_bindir}/quickview|' quickview-settings.desktop \
    > %{buildroot}%{_datadir}/applications/quickview-settings.desktop
# KDE runs a service menu only if the file is executable.
install -d %{buildroot}%{_datadir}/kio/servicemenus
sed 's|"@DIR@/bin/quickview"|%{_bindir}/quickview|' quickview-servicemenu.desktop \
    > %{buildroot}%{_datadir}/kio/servicemenus/quickview-servicemenu.desktop
chmod 0755 %{buildroot}%{_datadir}/kio/servicemenus/quickview-servicemenu.desktop

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/quickview-settings.desktop
# Every module imports nothing at load time that the build lacks; compile
# them all, and make sure no template placeholder was left behind.
%{python3} -m compileall -q %{buildroot}%{_datadir}/%{name}
! grep -rl '@[A-Z]*@' %{buildroot}%{_bindir} %{buildroot}%{_userunitdir} \
    %{buildroot}%{_datadir}/applications %{buildroot}%{_datadir}/kio

%post
%systemd_user_post quickview.socket

%preun
%systemd_user_preun quickview.socket

%files
%license LICENSE
%doc README.md CHANGELOG.md
%{_bindir}/quickview
%{_libexecdir}/%{name}/
%{_datadir}/%{name}/
%{_userunitdir}/quickview.socket
%{_userunitdir}/quickview.service
%{_userpresetdir}/80-quickview.preset
%{_datadir}/applications/quickview-settings.desktop
%dir %{_datadir}/kio
%dir %{_datadir}/kio/servicemenus
%{_datadir}/kio/servicemenus/quickview-servicemenu.desktop

%changelog
* Wed Nov 11 2026 Nicolas Vaughan <nivaca@fastmail.com> - 0.1.3-1
- Space opens Quick Look in Dolphin without setting it up
- packaging/release.py VERSION makes a whole release
- The release RPMs are signed

* Wed Nov 11 2026 Nicolas Vaughan <nivaca@fastmail.com> - 0.1.2-1
- Optional OpenPGP signing in build-rpm.sh (--sign)
- A worker job's queued error no longer outlives the job
- Install instructions lead with the Copr repository

* Tue Nov 10 2026 Nicolas Vaughan <nivaca@fastmail.com> - 0.1.1-1
- The launcher starts quickview.socket on the first preview after
  installing, so no logout is needed
- GPL-3 notices in the launcher, the systemd units and the preset

* Tue Nov 10 2026 Nicolas Vaughan <nivaca@fastmail.com> - 0.1.0-1
- First package: runs on the system's Python, PySide6 and Pygments, with
  no virtualenv; socket-activated user units enabled by preset
