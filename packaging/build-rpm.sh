#!/usr/bin/env bash
# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Nicolas Vaughan <nicolasvaughan@proton.me>
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
# from, with the project's signing key, SIGNING_KEY below (the same on all
# the author's machines; a copy of its public key is in
# packaging/RPM-GPG-KEY-quickview). --sign=KEY, or $SIGNING_KEY, names
# another key for an exceptional build. The public key is exported next to them as
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
#
# The binary RPM is also copied into dist/, replacing the older ones there:
# it is the only package kept in dist/. The Zip bundle of the same files as
# the source tarball goes to build/release/quickview-VERSION.zip, where
# packaging/release.py signs and publishes it (and deletes it afterwards).
set -euo pipefail

DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
# The project's signing key (Nicolas Vaughan, RPM signing, ed25519, 2026)
SIGNING_KEY="${SIGNING_KEY:-81870643CA221AF90C30554EBE6832CD35994948}"
SPEC="$DIR/packaging/quickview.spec"
TOP="$DIR/build/rpm"
RPMSIGN="${RPMSIGN:-rpmsign}"

die() { echo "build-rpm: $*" >&2; exit 1; }

SIGN=0
KEY=""
for arg in "$@"; do
    case "$arg" in
        --sign) SIGN=1; KEY="$SIGNING_KEY" ;;
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
    # The key published with the RPMs must be the project's, the one in
    # packaging/ (unless another was asked for).
    if [ "$KEY" = "$SIGNING_KEY" ] && [ -f "$DIR/packaging/RPM-GPG-KEY-quickview" ]; then
        shipped="$(gpg --batch --with-colons --show-keys "$DIR/packaging/RPM-GPG-KEY-quickview" |
            awk -F: '$1 == "fpr" { print $10; exit }')"
        [ "$shipped" = "$FPR" ] ||
            die "packaging/RPM-GPG-KEY-quickview is not the key that signed ($FPR)"
    fi
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

# The newest RPM goes to dist/ too, in place of the older ones: it is all that
# dist/ holds (it stays in build/rpm/ as well, where the release tools look
# for it).
mkdir -p "$DIR/dist"
find "$DIR/dist" -maxdepth 1 -name 'quickview-*.rpm' ! -name '*.src.rpm' -delete
for rpm in "${RPMS[@]}"; do
    case "$rpm" in
        *.src.rpm) ;;
        *) cp -p "$rpm" "$DIR/dist/" ;;
    esac
done

# And a Zip bundle of the same files as the source tarball, under
# quickview-VERSION/: unzipped, it is a checkout without git, for
# ./install.sh on any distribution. File modes are kept, so the scripts
# stay executable. It goes to build/release/, not dist/, replacing the
# older bundles there.
RELEASE="$DIR/build/release"
mkdir -p "$RELEASE"
find "$RELEASE" -maxdepth 1 -name 'quickview-*.zip' -delete
(cd "$DIR" && git ls-files -z --cached --others --exclude-standard |
    python3 -c '
import os, sys, zipfile
prefix, out = sys.argv[1], sys.argv[2]
names = sorted(n for n in sys.stdin.buffer.read().decode().split("\0")
               if n and os.path.isfile(n))
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
    for name in names:
        zf.write(name, prefix + "/" + name)
' "$NAME" "$RELEASE/$NAME.zip")

echo
echo "Built:"
for rpm in "${RPMS[@]}"; do
    echo "  $rpm"
done
echo "Copied to dist/: $(cd "$DIR/dist" && ls quickview-*.rpm 2>/dev/null | grep -v '\.src\.rpm$' | tr '\n' ' ')"
echo "Zip bundle: build/release/$NAME.zip"
if [ "$SIGN" = 1 ]; then
    echo "Signed by $FPR; public key: $TOP/RPM-GPG-KEY-quickview"
fi
