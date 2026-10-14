import subprocess
import tempfile
import unittest
from pathlib import Path

from cshcli.errors import DomainError
from cshcli.integration import IntegrationGate
from cshcli.store import Store


class GitVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.coord = self.root / "coord.sqlite3"
        self.now = 90_000.0
        self.store = Store(self.coord, clock=lambda: self.now)
        self.gate = IntegrationGate(self.store, clock=lambda: self.now)
        self.owner = self.store.register_user("ana")
        self.project = self.store.create_project(self.owner["id"], "acme")
        self.repo = self.build_repo()
        self.base = self.head(self.repo)

    def build_repo(self) -> Path:
        repo = self.root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.invalid"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
        subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=repo, check=True)
        (repo / "src").mkdir()
        (repo / "src" / "api.py").write_text("v = 1\n", encoding="utf-8", newline="\n")
        (repo / "docs").mkdir()
        (repo / "docs" / "readme.md").write_text("d\n", encoding="utf-8", newline="\n")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)
        return repo

    def head(self, repo: Path) -> str:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit_file(self, path: str, text: str, message: str) -> str:
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", message], cwd=self.repo, check=True)
        return self.head(self.repo)

    def lease(self, resources):
        return {item["resource"]: item["fence"] for item in
                self.store.acquire_leases(self.owner["id"], self.project["id"], "a1", resources)}

    def accept(self, fences, base, head, resources=None, repo=None):
        return self.gate.accept_patch(
            self.owner["id"], self.project["id"], "run-1", 1, fences, base, head,
            resources, str(self.repo) if repo is None else repo)

    def test_verify_reports_the_paths_the_commit_actually_touches(self):
        head = self.commit_file("src/api.py", "v = 2\n", "change api")
        report = self.gate.verify_with_git(self.repo, self.base, head)
        self.assertTrue(report["verified"])
        self.assertEqual(report["changed_paths"], ["src/api.py"])

    def test_a_missing_commit_is_refused(self):
        fences = self.lease(["file:src/api.py"])
        with self.assertRaises(DomainError) as caught:
            self.accept(fences, self.base, "f" * 40)
        self.assertEqual(caught.exception.code, "commit_unknown")

    def test_a_base_that_is_not_an_ancestor_is_refused(self):
        head = self.commit_file("src/api.py", "v = 2\n", "change api")
        fences = self.lease(["file:src/api.py"])
        with self.assertRaises(DomainError) as caught:
            self.accept(fences, head, self.base)
        self.assertEqual(caught.exception.code, "base_not_ancestor")

    def test_a_path_outside_every_lease_is_refused(self):
        head = self.commit_file("src/api.py", "v = 2\n", "change api")
        self.commit_file("docs/readme.md", "otro\n", "sneaky change")
        head = self.head(self.repo)
        fences = self.lease(["file:src/api.py"])
        with self.assertRaises(DomainError) as caught:
            self.accept(fences, self.base, head)
        self.assertEqual(caught.exception.code, "changes_outside_lease")

    def test_a_change_inside_a_leased_directory_is_accepted(self):
        self.commit_file("src/api.py", "v = 2\n", "one")
        head = self.commit_file("src/other.py", "x = 1\n", "two")
        fences = self.lease(["file:src"])
        accepted = self.accept(fences, self.base, head)
        self.assertEqual(accepted["state"], "accepted")

    def test_without_a_repository_the_gate_still_works_as_before(self):
        head = self.commit_file("src/api.py", "v = 2\n", "change api")
        fences = self.lease(["file:src/api.py"])
        accepted = self.gate.accept_patch(
            self.owner["id"], self.project["id"], "run-x", 1, fences, self.base, head)
        self.assertEqual(accepted["state"], "accepted")

    def test_a_path_without_a_git_directory_is_refused(self):
        plain = self.root / "plain"
        plain.mkdir()
        head = self.commit_file("src/api.py", "v = 2\n", "change api")
        fences = self.lease(["file:src/api.py"])
        with self.assertRaises(DomainError) as caught:
            self.accept(fences, self.base, head, repo=plain)
        self.assertEqual(caught.exception.code, "repo_missing")


if __name__ == "__main__":
    unittest.main()