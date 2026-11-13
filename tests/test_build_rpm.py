# QuickView — a Quick Look style file previewer for KDE Plasma.
# Copyright (C) 2026 Nicolas Vaughan <nivaca@fastmail.com>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed WITHOUT ANY
# WARRANTY; see the LICENSE file, or <https://www.gnu.org/licenses/>.

"""packaging/build-rpm.sh's options, short of building anything.

Every case here stops in the checks before the build — so they run in a
second, need no rpm-sign, and never touch build/ or the user's keys: gpg
looks in an empty, temporary GNUPGHOME.
"""

import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "packaging", "build-rpm.sh")


@unittest.skipUnless(shutil.which("rpmbuild") and shutil.which("rpmspec"),
                     "rpm-build not installed")
class Options(unittest.TestCase):
    def run_script(self, *args, **env):
        gnupg = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, gnupg, True)
        os.chmod(gnupg, 0o700)
        full_env = dict(os.environ, GNUPGHOME=gnupg, **env)
        result = subprocess.run([SCRIPT, *args], env=full_env, timeout=60,
                                capture_output=True, text=True)
        return result.returncode, result.stdout + result.stderr

    def test_help_is_the_comment_block(self):
        code, out = self.run_script("--help")
        self.assertEqual(code, 0)
        self.assertIn("--sign[=KEY]", out)
        self.assertNotIn("set -euo", out)
        self.assertNotIn("GNU General Public License", out)

    def test_an_unknown_option_is_refused(self):
        code, out = self.run_script("--signn")
        self.assertEqual(code, 1)
        self.assertIn("unknown option --signn", out)

    def test_an_empty_key_name_is_refused(self):
        code, out = self.run_script("--sign=")
        self.assertEqual(code, 1)
        self.assertIn("--sign= needs a key", out)

    def test_a_missing_rpmsign_is_named_before_building(self):
        code, out = self.run_script("--sign", RPMSIGN="no-such-rpmsign-qv")
        self.assertEqual(code, 1)
        self.assertIn("dnf install rpm-sign", out)

    def test_no_key_says_how_to_make_one(self):
        # An rpmsign that exists, so the key check is what fails; it would
        # never run, as nothing gets that far. A plain --sign asks for the
        # project's key, which the empty test keyring does not hold.
        code, out = self.run_script("--sign", RPMSIGN="/bin/true")
        self.assertEqual(code, 1)
        self.assertIn("no secret key matching "
                      "81870643CA221AF90C30554EBE6832CD35994948", out)
        self.assertIn("gpg --quick-generate-key", out)

    def test_signing_key_names_another_key(self):
        code, out = self.run_script("--sign", RPMSIGN="/bin/true",
                                    SIGNING_KEY="nobody@example.invalid")
        self.assertEqual(code, 1)
        self.assertIn("no secret key matching nobody@example.invalid", out)

    def test_an_unknown_key_is_named(self):
        code, out = self.run_script("--sign=nobody@example.invalid",
                                    RPMSIGN="/bin/true")
        self.assertEqual(code, 1)
        self.assertIn("no secret key matching nobody@example.invalid", out)


if __name__ == "__main__":
    unittest.main()
