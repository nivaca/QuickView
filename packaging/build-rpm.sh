#!/usr/bin/env bash
# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Nicolas Vaughan <nivaca@fastmail.com>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.
#
# Builds QuickView's RPM (and source RPM) from this checkout, into
# build/rpm/ — not ~/rpmbuild, so nothing outside the repo is touched.
#
#   packaging/build-rpm.sh [--sign[=KEY]]
#
# --sign signs both RPMs with OpenPGP, so dnf can check where they came
# from: with KEY (an ID, email or fingerprint) or else the first secret
# key gpg holds. The public key is exported next to them as
# build/rpm/RPM-GPG-KEY-quickview, for people to import before installing
# (sudo rpm --import RPM-GPG-KEY-quickview). gpg asks for the key's
# passphrase as usual. Needs rpm-sign; RPMSIGN names another rpmsign.
#
# The source tarball is made from the files git knows about, committed or
# not (ignored files, such as .venv/, are left out), so a change can be
# packaged before it is committed. For a release, build from a clean tree.
#
# Needs rpm-build, plus what the spec builds with: python3-devel, rust,
# systemd-rpm-macros and desktop-file-utils.
set -euo pipefail

DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
SPEC="$DIR/packaging/quickview.spec"
TOP="$DIR/build/rpm"
RPMSIGN="${RPMSIGN:-rpmsign}"

die() { echo "build-rpm: $*" >&2; exit 1; }

SIGN=0
KEY=""
for arg in "$@"; do
    case "$arg" in
        --sign) SIGN=1 ;;
        --sign=*) SIGN=1; KEY="${arg#--sign=}"
                  [ -n "$KEY" ] || die "--sign= needs a key" ;;
        -h|--help)  # the comment block after the licence, as help
            awk 'NR > 10 && !/^#/ { exit } NR > 10 { sub(/^# ?/, ""); print }' "$0"
            exit 0 ;;
        *) die "unknown option $arg (try --help)" ;;
    esac
done

for tool in rpmbuild rpmspec git; do
    command -v "$tool" >/dev/null 2>&1 ||
        die "$tool not found (dnf install rpm-build git)"
done

# Signing is checked before building, so a missing tool or key costs
# seconds rather than a whole build.
if [ "$SIGN" = 1 ]; then
    command -v "$RPMSIGN" >/dev/null 2>&1 ||
        die "$RPMSIGN not found (sudo dnf install rpm-sign)"
    command -v gpg >/dev/null 2>&1 || die "gpg not found (sudo dnf install gnupg2)"
    # The fingerprint, whichever way the key was named: unambiguous for
    # rpmsign, and what the exported key file is made from.
    # (gpg exits non-zero when nothing matches; "|| true" lets the check
    # below say so, where set -e and pipefail would end the script mute.)
    FPR="$(gpg --batch --with-colons --list-secret-keys ${KEY:+"$KEY"} 2>/dev/null |
        awk -F: '$1 == "sec" { want = 1 } want && $1 == "fpr" { print $10; exit }' ||
        true)"
    [ -n "$FPR" ] || die "no secret key${KEY:+ matching $KEY} in gpg (make one with: gpg --quick-generate-key \"Your Name <you@example.org>\")"
    echo "Signing with $(gpg --batch --with-colons --list-keys "$FPR" |
        awk -F: '$1 == "uid" { print $10; exit }') ($FPR)"
fi

VERSION="$(rpmspec -q --srpm --qf '%{version}\n' "$SPEC")"
NAME="quickview-$VERSION"

if [ -n "$(git -C "$DIR" status --porcelain)" ]; then
    echo "note: the tree has uncommitted changes; they go into this build."
fi

rm -rf "$TOP"
mkdir -p "$TOP"/{SOURCES,SPECS,BUILD,RPMS,SRPMS}
# Tracked and new files, as they are on disk, under quickview-VERSION/.
(cd "$DIR" && git ls-files -z --cached --others --exclude-standard |
    while IFS= read -r -d '' f; do [ -e "$f" ] && printf '%s\0' "$f"; done |
    tar --null -T - --transform "s|^|$NAME/|" -czf "$TOP/SOURCES/$NAME.tar.gz")

rpmbuild --define "_topdir $TOP" -ba "$SPEC"

mapfile -t RPMS < <(find "$TOP/RPMS" "$TOP/SRPMS" -name '*.rpm' | sort)

if [ "$SIGN" = 1 ]; then
    # rpm looks for gpg's keys in ~/.gnupg unless told otherwise.
    "$RPMSIGN" --define "_gpg_name $FPR" \
        ${GNUPGHOME:+--define "_gpg_path $GNUPGHOME"} --addsign "${RPMS[@]}"
    gpg --batch --armor --export "$FPR" > "$TOP/RPM-GPG-KEY-quickview"
    # Prove it the way a user's dnf will: in a keyring of its own, holding
    # only the exported key, every package must verify. That checks the
    # signatures and that the key file published with them is the right
    # one, without touching the system's keys.
    keyring="$(mktemp -d)"
    trap 'rm -rf "$keyring"' EXIT
    check=(--dbpath "$keyring" --define "_keyring fs"
           --define "_keyringpath $keyring/pubkeys/")
    rpmkeys "${check[@]}" --import "$TOP/RPM-GPG-KEY-quickview" ||
        die "the exported key could not be read back"
    for rpm in "${RPMS[@]}"; do
        rpmkeys "${check[@]}" -K "$rpm" >/dev/null ||
            die "$(basename "$rpm") does not verify with the exported key"
    done
fi

echo
echo "Built:"
for rpm in "${RPMS[@]}"; do
    echo "  $rpm"
done
if [ "$SIGN" = 1 ]; then
    echo "Signed by $FPR; public key: $TOP/RPM-GPG-KEY-quickview"
fi
