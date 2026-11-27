# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Nicolas Vaughan <nicolasvaughan@proton.me>
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
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
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
            "* Thu Nov 12 2026 Nicolas Vaughan <nicolasvaughan@proton.me> - 9.8.7-1\n"
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
    def test_the_zip_bundle_is_offered_to_other_distributions(self):
        files = {"quickview-0.1.3-1.fc45.x86_64.rpm": "a" * 64,
                 "quickview-0.1.3-1.fc45.src.rpm": "b" * 64,
                 "quickview-0.1.3.zip": "c" * 64}
        notes = release.release_notes("0.1.3", "0.1.2", "- x\n", files, FPR)
        self.assertIn("download `quickview-0.1.3.zip`, unzip it, and run "
                      "`./install.sh` in the `quickview-0.1.3` folder", notes)
        self.assertIn("| `quickview-0.1.3.zip` | `" + "c" * 64 + "` |", notes)

    def test_without_a_bundle_the_notes_say_to_clone(self):
        self.assertIn("clone the repository and run `./install.sh`.", self.notes())

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
                "QuickView is by Nicolas Vaughan (forked from the QuickView "
                "app by Mustapha Alioglou)."):
            self.assertIn(expected, notes)

    def test_the_fingerprint_is_written_as_gpg_writes_it(self):
        self.assertEqual(release.spaced_fingerprint(FPR),
                         "8187 0643 CA22 1AF9 0C30  554E BE68 32CD 3599 4948")
        self.assertIn(release.spaced_fingerprint(FPR), self.notes())

    def test_how_to_check_a_download_is_said(self):
        files = {"quickview-0.1.3-1.fc45.x86_64.rpm": "a" * 64,
                 "quickview-0.1.3-1.fc45.src.rpm": "b" * 64,
                 "quickview-0.1.3.zip": "c" * 64}
        notes = release.release_notes("0.1.3", "0.1.2", "- x\n", files, FPR)
        for expected in (
                "gpg --import RPM-GPG-KEY-quickview",
                "gpg --verify quickview-0.1.3.zip.asc quickview-0.1.3.zip",
                "gpg --verify SHA256SUMS.asc SHA256SUMS && "
                "sha256sum -c --ignore-missing SHA256SUMS",
                "the tag `v0.1.3`"):
            self.assertIn(expected, notes)

    def test_no_ai_credit(self):
        notes = self.notes().lower()
        for word in ("claude", "anthropic"):
            self.assertNotIn(word, notes)


class Signing(unittest.TestCase):
    PATHS = ["/x/build/rpm/RPMS/x86_64/quickview-0.1.3-1.fc45.x86_64.rpm",
             "/x/build/rpm/SRPMS/quickview-0.1.3-1.fc45.src.rpm",
             "/x/build/release/quickview-0.1.3.zip"]

    def test_only_the_rpms_are_kept_here(self):
        # Las sumas y lo que se publica, salvo los RPM, van en build/release/;
        # al final se borra eso y build/zenodo/, nunca build/rpm/ ni dist/.
        out = os.path.join(release.ROOT, "build", "release")
        self.assertEqual(os.path.dirname(release.SUMS), out)
        self.assertIn(out, release.CLEANED)
        self.assertIn(os.path.join(release.ROOT, "build", "zenodo"), release.CLEANED)
        for kept in ("dist", os.path.join("build", "rpm")):
            self.assertNotIn(os.path.join(release.ROOT, kept), release.CLEANED)

    def test_every_file_goes_with_its_signature_the_sums_and_the_key(self):
        files = release.published(self.PATHS)
        for path in self.PATHS:
            self.assertIn(path, files)
            self.assertIn(path + ".asc", files)
        self.assertIn(release.SUMS, files)
        self.assertIn(release.SUMS + ".asc", files)
        self.assertEqual(files[-1], release.KEY_FILE)
        # GitHub y Codeberg guardan los archivos por su nombre: ninguno
        # puede repetirse.
        names = [os.path.basename(f) for f in files]
        self.assertEqual(len(names), len(set(names)))

    def test_the_files_are_signed_with_the_published_key(self):
        cmd = release.sign_command(FPR, self.PATHS)
        self.assertTrue(cmd[1].endswith("sign_release.py"))
        self.assertEqual(cmd[cmd.index("--key") + 1], FPR)
        self.assertEqual(cmd[cmd.index("--public") + 1], release.KEY_FILE)
        self.assertEqual(cmd[-3:], self.PATHS)

    def test_the_tag_is_signed_and_checked(self):
        make, check = release.tag_commands(FPR, "0.1.3")
        self.assertEqual(make[:5], ["git", "tag", "--sign", "--local-user", FPR])
        self.assertEqual(make[-1], "v0.1.3")
        self.assertEqual(check, ["git", "tag", "--verify", "v0.1.3"])


class Versions(unittest.TestCase):
    def test_version_py_matches_the_spec(self):
        import version
        with open(release.SPEC, encoding="utf-8") as fh:
            spec = fh.read()
        self.assertRegex(spec, rf"(?m)^Version:\s+{re.escape(version.VERSION)}$")

    def test_a_release_bumps_version_py(self):
        with open(release.VERSION_FILE, encoding="utf-8") as fh:
            original = fh.read()
        bumped = release.bump_version_file(original, "9.8.7")
        self.assertIn('VERSION = "9.8.7"\n', bumped)
        self.assertEqual(len(bumped.splitlines()), len(original.splitlines()))
        with self.assertRaises(release.ReleaseError):
            release.bump_version_file("nothing here", "9.8.7")

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
