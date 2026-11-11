#!/usr/bin/env bash
# Builds QuickView's RPM (and source RPM) from this checkout, into
# build/rpm/ — not ~/rpmbuild, so nothing outside the repo is touched.
#
#   packaging/build-rpm.sh
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

for tool in rpmbuild rpmspec git; do
    command -v "$tool" >/dev/null 2>&1 || {
        echo "build-rpm: $tool not found (dnf install rpm-build git)" >&2
        exit 1
    }
done

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

echo
echo "Built:"
find "$TOP/RPMS" "$TOP/SRPMS" -name '*.rpm' -printf '  %p\n'
