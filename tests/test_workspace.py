import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from cshcli.errors import DomainError
from cshcli.workspace import Workspace


def build_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=repo, check=True)
    (repo / "src").mkdir()
    (repo / "src" / "api.py").write_text("value = 1\n", encoding="utf-8", newline="\n")
    (repo / "README.md").write_text("demo\n", encoding="utf-8", newline="\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)
    return repo


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = build_repo(self.root)
        self.sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo, check=True,
                                  capture_output=True, text=True).stdout.strip()
        self.outside = self.root / "outside.txt"
        self.outside.write_text("secreto\n", encoding="utf-8")

    def workspace(self, run_id="run-1") -> Workspace:
        space = Workspace.create(self.repo, self.sha, run_id, parent=self.root)
        self.addCleanup(space.close)
        return space

    def assert_rejected(self, callback):
        with self.assertRaises(DomainError) as caught:
            callback()
        self.assertEqual(caught.exception.code, "path_rejected")
        return caught.exception

    def test_creates_an_isolated_worktree_at_the_base_sha(self):
        space = self.workspace()
        self.assertTrue(space.root.is_dir())
        self.assertEqual(space.read("README.md"), b"demo\n")
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=space.root, check=True,
                              capture_output=True, text=True).stdout.strip()
        self.assertEqual(head, self.sha)
        self.assertNotEqual(space.root.resolve(), self.repo.resolve())

    def test_editing_the_workspace_does_not_touch_the_main_checkout(self):
        space = self.workspace()
        space.write("src/api.py", b"value = 2\n")
        self.assertEqual(space.read("src/api.py"), b"value = 2\n")
        self.assertEqual((self.repo / "src" / "api.py").read_text(encoding="utf-8"), "value = 1\n")
        self.assertIn("src/api.py", space.tracked_changes())

    def test_two_workspaces_do_not_see_each_other(self):
        first = self.workspace("run-a")
        second = self.workspace("run-b")
        first.write("src/api.py", b"value = 3\n")
        self.assertEqual(second.read("src/api.py"), b"value = 1\n")
        self.assertEqual(second.tracked_changes(), [])

    def test_rejects_traversal_and_absolute_paths(self):
        space = self.workspace()
        self.assert_rejected(lambda: space.resolve("../outside.txt"))
        self.assert_rejected(lambda: space.resolve("src/../../outside.txt"))
        self.assert_rejected(lambda: space.resolve(".."))
        self.assert_rejected(lambda: space.resolve("."))
        self.assert_rejected(lambda: space.resolve(str(self.outside)))
        self.assert_rejected(lambda: space.resolve("C:/Windows/System32"))
        self.assert_rejected(lambda: space.resolve(""))
        self.assert_rejected(lambda: space.resolve("src\api.py"))

    def test_rejects_windows_ambiguous_names(self):
        space = self.workspace()
        for candidate in ("src/api .py", "src/api.py.", "src/CON.py", "src/nul", "src/com1",
                          "src/lpt9.txt", "src/a:b", "src/a*b", 'src/a"b', "src/a|b",
                          "src/a?b", "src/a<b", "src/a>b"):
            with self.subTest(candidate=candidate):
                self.assert_rejected(lambda candidate=candidate: space.resolve(candidate))

    def test_rejects_a_symbolic_link_pointing_outside(self):
        space = self.workspace()
        try:
            os.symlink(self.outside, space.root / "escape.txt")
        except OSError:
            self.skipTest("symbolic links are not available here")
        with self.assertRaises(DomainError) as caught:
            space.resolve("escape.txt")
        self.assertEqual(caught.exception.code, "path_rejected")

    def test_rejects_traversal_through_a_directory_link(self):
        space = self.workspace()
        try:
            os.symlink(self.root, space.root / "linked")
        except OSError:
            self.skipTest("symbolic links are not available here")
        self.assert_rejected(lambda: space.resolve("linked/outside.txt"))

    def test_write_read_rename_and_remove_stay_inside(self):
        space = self.workspace()
        space.write("src/new.py", b"created\n")
        self.assertEqual(space.read("src/new.py"), b"created\n")
        space.write("docs/deep/nested/file.txt", b"deep\n")
        self.assertEqual(space.read("docs/deep/nested/file.txt"), b"deep\n")
        space.rename("src/new.py", "src/moved.py")
        self.assertEqual(space.read("src/moved.py"), b"created\n")
        with self.assertRaises(DomainError):
            space.read("src/new.py")
        space.remove("src/moved.py")
        self.assertFalse((space.root / "src" / "moved.py").exists())
        self.assertTrue(self.outside.exists())
        self.assertEqual(self.outside.read_text(encoding="utf-8"), "secreto\n")

    def test_rejects_a_junction_pointing_outside(self):
        space = self.workspace()
        outside_dir = self.root / "outside-dir"
        outside_dir.mkdir()
        (outside_dir / "secret.txt").write_text("secreto\n", encoding="utf-8", newline="\n")
        if os.name != "nt":
            self.skipTest("junctions are a Windows concept")
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(space.root / "junction"), str(outside_dir)],
                                capture_output=True, text=True)
        if result.returncode != 0:
            self.skipTest("this environment does not allow creating junctions")
        with self.assertRaises(DomainError) as caught:
            space.resolve("junction/secret.txt")
        self.assertEqual(caught.exception.code, "path_rejected")
        self.assertTrue((outside_dir / "secret.txt").exists())

    def test_remove_cannot_escape_the_workspace(self):
        space = self.workspace()
        self.assert_rejected(lambda: space.remove("../outside.txt"))
        self.assertTrue(self.outside.exists())

    def test_unknown_base_sha_is_refused_before_any_directory_is_left_behind(self):
        before = set(self.root.iterdir())
        with self.assertRaises(DomainError) as caught:
            Workspace.create(self.repo, "0" * 40, "run-x", parent=self.root)
        self.assertEqual(caught.exception.code, "git_failed")
        self.assertEqual(set(self.root.iterdir()), before)

    def test_non_repository_is_refused(self):
        plain = self.root / "plain"
        plain.mkdir()
        with self.assertRaises(DomainError) as caught:
            Workspace.create(plain, self.sha, "run-y", parent=self.root)
        self.assertEqual(caught.exception.code, "repo_invalid")

    def test_close_removes_the_worktree_and_its_registration(self):
        space = Workspace.create(self.repo, self.sha, "run-z", parent=self.root)
        root = space.root
        space.close()
        self.assertFalse(root.exists())
        listing = subprocess.run(["git", "worktree", "list"], cwd=self.repo, check=True,
                                 capture_output=True, text=True).stdout
        self.assertNotIn(str(root), listing)


if __name__ == "__main__":
    unittest.main()