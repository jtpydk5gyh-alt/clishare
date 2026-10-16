import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.append(str(Path(__file__).resolve().parents[1] / "scripts"))
import bump_version


class SandboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        patcher = mock.patch.object(bump_version, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_a_three_part_version_is_accepted(self):
        self.assertEqual(bump_version.parse("1.2.3"), (1, 2, 3))

    def test_other_shapes_are_refused(self):
        for value in ("1.2", "1.2.3.4", "v1.2.3", "1.2.x", "", "1.2.3-rc1"):
            with self.subTest(value=value):
                with self.assertRaises(bump_version.BumpRefused):
                    bump_version.parse(value)

    def test_one_match_is_replaced(self):
        path = self.write("a.md", "version 0.5.0.\n")
        pattern = re.compile(r"(version )(0\.\d+\.\d+)(\.)")
        bump_version.rewrite("a.md", pattern, "0.5.0", "0.6.0")
        self.assertEqual(path.read_text(encoding="utf-8"), "version 0.6.0.\n")

    def test_changed_wording_is_refused_instead_of_guessed(self):
        self.write("a.md", "release 0.5.0 today\n")
        pattern = re.compile(r"(version )(0\.\d+\.\d+)(\.)")
        with self.assertRaises(bump_version.BumpRefused):
            bump_version.rewrite("a.md", pattern, "0.5.0", "0.6.0")

    def test_two_matches_are_refused(self):
        self.write("a.md", "version 0.5.0. and version 0.5.0.\n")
        pattern = re.compile(r"(version )(0\.\d+\.\d+)(\.)")
        with self.assertRaises(bump_version.BumpRefused):
            bump_version.rewrite("a.md", pattern, "0.5.0", "0.6.0")

    def test_a_missing_file_is_refused(self):
        with self.assertRaises(FileNotFoundError):
            bump_version.rewrite("absent.md", re.compile(r"(x)"), "1", "2")

    def test_the_current_version_is_read_from_the_package(self):
        self.write("src/cshcli/__init__.py", '__version__ = "0.5.0"\n')
        self.assertEqual(bump_version.read_current(), "0.5.0")

    def test_a_package_without_a_version_is_refused(self):
        self.write("src/cshcli/__init__.py", "nothing here\n")
        with self.assertRaises(bump_version.BumpRefused):
            bump_version.read_current()

    def test_the_changelog_entry_is_detected(self):
        self.write("CHANGELOG.md", "# Changelog\n\n## [0.5.0] - 2026-10-16\n")
        self.assertTrue(bump_version.changelog_entry("0.5.0"))
        self.assertFalse(bump_version.changelog_entry("0.6.0"))

    def test_a_missing_changelog_is_not_a_failure(self):
        self.assertFalse(bump_version.changelog_entry("0.5.0"))

    def test_main_needs_exactly_one_argument(self):
        with mock.patch.object(sys, "argv", ["bump_version.py"]):
            self.assertEqual(bump_version.main(), 2)
        with mock.patch.object(sys, "argv", ["bump_version.py", "0.5.0", "0.6.0"]):
            self.assertEqual(bump_version.main(), 2)

    def test_main_refuses_a_version_that_does_not_move_forward(self):
        self.write("src/cshcli/__init__.py", '__version__ = "0.5.0"\n')
        with mock.patch.object(sys, "argv", ["bump_version.py", "0.5.0"]):
            self.assertEqual(bump_version.main(), 1)
        with mock.patch.object(sys, "argv", ["bump_version.py", "0.4.9"]):
            self.assertEqual(bump_version.main(), 1)
        self.assertIn("0.5.0", (self.root / "src" / "cshcli" / "__init__.py")
                      .read_text(encoding="utf-8"))

    def test_main_refuses_a_malformed_version_before_touching_anything(self):
        self.write("src/cshcli/__init__.py", '__version__ = "0.5.0"\n')
        self.write("pyproject.toml", 'version = "0.5.0"\n')
        with mock.patch.object(sys, "argv", ["bump_version.py", "nope"]):
            self.assertEqual(bump_version.main(), 1)
        self.assertEqual((self.root / "pyproject.toml").read_text(encoding="utf-8"),
                         'version = "0.5.0"\n')


class RepositoryWordingTests(unittest.TestCase):
    def test_every_target_still_matches_exactly_once(self):
        for name, pattern in bump_version.TARGETS:
            with self.subTest(file=name):
                text = (bump_version.ROOT / name).read_text(encoding="utf-8")
                self.assertEqual(
                    len(pattern.findall(text)), 1,
                    f"{name} no longer matches {pattern.pattern} exactly once; "
                    "bump_version.py would refuse, so update both.")

    def test_the_script_and_the_package_agree_today(self):
        self.assertEqual(
            bump_version.read_current(),
            re.search(r'version = "(0\.\d+\.\d+)"',
                      (bump_version.ROOT / "pyproject.toml").read_text(encoding="utf-8")
                      ).group(1))


if __name__ == "__main__":
    unittest.main()