# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Nicolas Vaughan <nivaca@fastmail.com>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""What packaging/release.py writes: spec entry, changelog, release notes.

Only the text work — nothing here commits, builds, pushes or publishes.
"""

import datetime
import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "release", os.path.join(ROOT, "packaging", "release.py"))
release = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release)

FPR = "81870643CA221AF90C30554EBE6832CD35994948"
WHEN = datetime.date(2026, 11, 12)

CHANGELOG = """# Changelog

Intro.

## Unreleased

### Added

- **A new thing.** Described at some
  length, over two lines.
- A change without a bold headline. And a second sentence.

### Fixed

- **`build-rpm.sh` no longer fails.** Because.

## 0.1.2 — 2026-11-11

### Added

- **Old.** Old.
"""


class Changelog(unittest.TestCase):
    def test_the_unreleased_section_is_what_is_released(self):
        section = release.unreleased_section(CHANGELOG)
        self.assertTrue(section.startswith("### Added"))
        self.assertNotIn("Old.", section)

    def test_each_change_becomes_one_line(self):
        lines = release.headlines(release.unreleased_section(CHANGELOG))
        self.assertEqual(lines, ["A new thing",
                                 "A change without a bold headline",
                                 "build-rpm.sh no longer fails"])

    def test_nothing_unreleased_is_refused(self):
        for text in ("# Changelog\n\n## 0.1.2 — x\n- **Old.**\n",
                     "# Changelog\n\n## Unreleased\n\n## 0.1.2 — x\n"):
            with self.subTest(text=text[:30]):
                with self.assertRaises(release.ReleaseError):
                    release.unreleased_section(text)

    def test_unreleased_becomes_the_version(self):
        out = release.bump_changelog(CHANGELOG, "0.1.3", "2026-11-12")
        self.assertIn("## 0.1.3 — 2026-11-12\n\n### Added", out)
        self.assertNotIn("## Unreleased", out)

    def test_the_real_changelog_has_something_to_release(self):
        with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as fh:
            text = fh.read()
        if "## Unreleased" not in text:
            self.skipTest("nothing unreleased right now")
        self.assertTrue(release.headlines(release.unreleased_section(text)))


class Spec(unittest.TestCase):
    def bumped(self):
        with open(release.SPEC, encoding="utf-8") as fh:
            original = fh.read()
        lines = ["A new thing", "x" * 100]
        return original, release.bump_spec(original, "9.8.7", WHEN, lines)

    def test_version_release_and_entry(self):
        original, spec = self.bumped()
        self.assertRegex(spec, r"(?m)^Version:\s+9\.8\.7$")
        self.assertRegex(spec, r"(?m)^Release:\s+1%\{\?dist\}$")
        entry = spec.split("%changelog\n", 1)[1]
        self.assertTrue(entry.startswith(
            "* Thu Nov 12 2026 Nicolas Vaughan <nivaca@fastmail.com> - 9.8.7-1\n"
            "- A new thing\n"))
        # The older entries are all still there, after the new one.
        self.assertIn(original.split("%changelog\n", 1)[1], entry)

    def test_long_lines_are_wrapped(self):
        _, spec = self.bumped()
        entry = spec.split("%changelog\n", 1)[1].split("\n\n", 1)[0]
        self.assertTrue(all(len(line) <= 72 for line in entry.splitlines()[1:]))

    @unittest.skipUnless(shutil.which("rpmspec"), "rpm-build not installed")
    def test_rpm_reads_the_bumped_spec(self):
        _, spec = self.bumped()
        with tempfile.NamedTemporaryFile("w", suffix=".spec") as fh:
            fh.write(spec)
            fh.flush()
            out = subprocess.run(
                ["rpmspec", "-q", "--srpm", "--qf",
                 "%{version}-%{release}\\n", fh.name],
                capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(out.stdout.startswith("9.8.7-1"))


class Notes(unittest.TestCase):
    def notes(self):
        files = {"quickview-0.1.3-1.fc45.x86_64.rpm": "a" * 64,
                 "quickview-0.1.3-1.fc45.src.rpm": "b" * 64}
        section = release.unreleased_section(CHANGELOG)
        return release.release_notes("0.1.3", "0.1.2", section, files, FPR)

    def test_what_a_user_needs_is_there(self):
        notes = self.notes()
        for expected in (
                "sudo dnf copr enable nivaca/quickview",
                "sudo rpm --import RPM-GPG-KEY-quickview",
                "sudo dnf install ./quickview-0.1.3-1.fc45.x86_64.rpm",
                "rpmbuild --rebuild quickview-0.1.3-1.fc45.src.rpm",
                "| `quickview-0.1.3-1.fc45.x86_64.rpm` | `" + "a" * 64 + "` |",
                "/releases/tag/v0.1.2",
                "/blob/v0.1.3/CHANGELOG.md",
                "**A new thing.**",
                "QuickView is by Mustapha Alioglou; this fork is maintained "
                "by Nicolas Vaughan."):
            self.assertIn(expected, notes)

    def test_the_fingerprint_is_written_as_gpg_writes_it(self):
        self.assertEqual(release.spaced_fingerprint(FPR),
                         "8187 0643 CA22 1AF9 0C30  554E BE68 32CD 3599 4948")
        self.assertIn(release.spaced_fingerprint(FPR), self.notes())

    def test_no_ai_credit(self):
        notes = self.notes().lower()
        for word in ("claude", "anthropic"):
            self.assertNotIn(word, notes)


class Versions(unittest.TestCase):
    def test_versions_compare_as_numbers(self):
        self.assertGreater(release.version_tuple("0.1.10"),
                           release.version_tuple("0.1.9"))

    def test_a_malformed_version_is_refused(self):
        for bad in ("v0.1.3", "0.1.x", "1", ""):
            with self.subTest(bad=bad):
                with self.assertRaises(release.ReleaseError):
                    release.version_tuple(bad)


if __name__ == "__main__":
    unittest.main()
