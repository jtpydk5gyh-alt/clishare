import subprocess
import tempfile
import unittest
from pathlib import Path

from cshcli.errors import DomainError
from cshcli.integration import IntegrationGate
from cshcli.queue import FAILED, MERGED, QUEUED, REVIEW, IntegrationQueue, _Checkout
from cshcli.store import Store


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repository = self.root / "repo"
        self.repository.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "queue@example.invalid")
        self.git("config", "user.name", "Queue")
        self.git("config", "commit.gpgsign", "false")
        (self.repository / "app.py").write_text(
            "def total(items):\n    return sum(items)\n", encoding="utf-8")
        (self.repository / "test_app.py").write_text(
            "def check():\n    return True\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.base = self.head()
        self.git("branch", "integration", self.base)

        self.store = Store(self.root / "coordinator.sqlite3")
        self.ana = self.store.register_user("ana")
        self.project = self.store.create_project(self.ana["id"], "demo")
        self.gate = IntegrationGate(self.store)
        self.queue = IntegrationQueue(self.store, self.repository, checks=self.checks_pass)
        self.runs = 0

    def accept(self, commit_sha, base_sha=None, resources=None):
        self.runs += 1
        touched = resources or ["file:app.py", "file:test_app.py"]
        held = self.store.acquire_leases(self.ana["id"], self.project["id"],
                                         f"agent-{self.runs}", touched, ttl=3600)
        self.gate.accept_patch(self.ana["id"], self.project["id"],
                               f"run-{self.runs}",
                               self.store.authorization_generation(
                                   self.ana["id"], self.project["id"]),
                               {item["resource"]: item["fence"] for item in held},
                               base_sha or self.base, commit_sha, touched)
        for lease in held:
            self.store.release_lease(self.ana["id"], self.project["id"],
                                     lease["id"], lease["fence"])

    def git(self, *arguments):
        return subprocess.run(["git", *arguments], cwd=self.repository, check=True,
                              capture_output=True, text=True).stdout

    def head(self):
        return self.git("rev-parse", "HEAD").strip()

    def checks_pass(self, path):
        return True

    def branch_sha(self):
        return self.git("rev-parse", "integration").strip()

    def commit(self, name, content, message):
        (self.repository / name).write_text(content, encoding="utf-8")
        self.git("add", name)
        self.git("commit", "-qm", message)
        return self.head()

    def worktree(self, name, content, message):
        original = self.head()
        self.commit(name, content, message)
        sha = self.head()
        self.git("reset", "--hard", original)
        return sha

    def parent_of(self, sha):
        return self.git("rev-parse", f"{sha}^").strip()

    def branch_content(self, name):
        return self.git("show", f"integration:{name}")

    def submit(self, commit_sha, base=None, resources=None):
        base = base or self.base
        self.accept(commit_sha, base, resources)
        return self.queue.submit(self.project["id"], commit_sha, base)

    def test_an_empty_queue_says_so(self):
        result = self.queue.process_next(self.project["id"])
        self.assertEqual(result["state"], "idle")

    def test_a_commit_that_no_gate_accepted_is_refused(self):
        sha = self.worktree("app.py", "def total(items):\n    return 5\n", "fix")
        with self.assertRaises(DomainError) as caught:
            self.queue.submit(self.project["id"], sha, self.base)
        self.assertEqual(caught.exception.code, "patch_not_accepted")
        self.assertEqual(self.queue.list(self.project["id"]), [])

    def test_a_patch_accepted_with_another_base_is_refused(self):
        sha = self.worktree("app.py", "def total(items):\n    return 6\n", "fix")
        other = self.commit("app.py", "def total(items):\n    return 4\n", "other")
        self.accept(sha, self.base)
        with self.assertRaises(DomainError) as caught:
            self.queue.submit(self.project["id"], sha, other)
        self.assertEqual(caught.exception.code, "patch_base_mismatch")

    def test_an_acceptance_that_disappears_before_merging_is_refused(self):
        sha = self.worktree("app.py", "def total(items):\n    return 8\n", "fix")
        self.submit(sha)
        with self.store._connection(write=True) as connection:
            connection.execute(
                "DELETE FROM accepted_patches WHERE project_id = ? AND commit_sha = ?",
                (self.project["id"], sha))
        with self.assertRaises(DomainError) as caught:
            self.queue.process_next(self.project["id"])
        self.assertEqual(caught.exception.code, "patch_not_accepted")
        self.assertEqual(self.branch_sha(), self.base, "the branch must not move")

    def test_a_submission_requires_a_real_commit(self):
        with self.assertRaises(DomainError) as caught:
            self.submit("f" * 40)
        self.assertEqual(caught.exception.code, "commit_not_found")

    def test_the_same_commit_is_queued_once(self):
        sha = self.worktree("app.py", "def total(items):\n    return 0\n", "wip")
        first = self.submit(sha)
        second = self.submit(sha)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(self.queue.list(self.project["id"])), 1)

    def test_a_patch_merges_and_records_both_shas(self):
        sha = self.worktree("app.py", "def total(items):\n    return 42\n", "fix")
        self.submit(sha)
        result = self.queue.process_next(self.project["id"])
        self.assertEqual(result["state"], MERGED)
        self.assertEqual(result["tested_sha"], result["merge_sha"])
        self.assertTrue(result["checks_passed"])
        self.assertEqual(self.branch_sha(), result["merge_sha"])

    def test_two_patches_on_the_same_base_compose(self):
        first = self.worktree("app.py", "def total(items):\n    return 7\n", "fix body")
        second = self.worktree("test_app.py", "def check():\n    return 7\n", "fix test")
        self.assertNotEqual(first, second, "the two patches differ")
        self.assertEqual(self.parent_of(first), self.base)
        self.assertEqual(self.parent_of(second), self.base,
                         "both patches are based on the same SHA")

        self.submit(first, self.base)
        first_result = self.queue.process_next(self.project["id"])
        self.assertEqual(first_result["state"], MERGED)

        self.submit(second, self.base)
        second_result = self.queue.process_next(self.project["id"])
        self.assertEqual(second_result["state"], MERGED)
        self.assertEqual(second_result["tested_sha"], second_result["merge_sha"])
        self.assertNotEqual(second_result["merge_sha"], first_result["merge_sha"])
        self.assertEqual(second_result["observed_base"], first_result["merge_sha"])
        self.assertIn("return 7", self.branch_content("app.py"))
        self.assertIn("return 7", self.branch_content("test_app.py"))

    def test_a_failing_check_leaves_the_branch_untouched(self):
        sha = self.worktree("app.py", "def total(items):\n    return 9\n", "fix")
        self.submit(sha)
        self.queue.checks = lambda path: False
        result = self.queue.process_next(self.project["id"])
        self.assertEqual(result["state"], FAILED)
        self.assertEqual(self.branch_sha(), self.base)
        self.assertNotEqual(result["tested_sha"], result["merge_sha"])

    def test_a_conflicting_patch_is_reviewed_not_merged(self):
        first = self.worktree("app.py", "def total(items):\n    return 1\n", "one")
        conflict = self.worktree("app.py", "def total(items):\n    return 2\n", "two")
        self.submit(first, self.base)
        self.queue.process_next(self.project["id"])
        merged_before = self.branch_sha()
        self.submit(conflict, self.base)
        result = self.queue.process_next(self.project["id"])
        self.assertEqual(result["state"], REVIEW)
        self.assertEqual(result["merge_sha"], None)
        self.assertEqual(self.branch_sha(), merged_before)
        self.assertIn("return 1", self.branch_content("app.py"))

    def test_a_branch_that_moved_while_the_checks_ran_forces_a_recompute(self):
        sha = self.worktree("app.py", "def total(items):\n    return 8\n", "fix")
        self.submit(sha)
        elsewhere = self.commit("test_app.py", "def check():\n    return 0\n", "someone else")

        def moves_then_reports(path):
            subprocess.run(["git", "update-ref", "refs/heads/integration", elsewhere],
                           cwd=self.repository, check=True)
            return True

        self.queue.checks = moves_then_reports
        result = self.queue.process_next(self.project["id"])
        self.assertEqual(result["state"], REVIEW)
        self.assertIn("moved", result["detail"])
        self.assertEqual(result["merge_sha"], None)
        self.assertEqual(self.branch_sha(), elsewhere,
                         "the branch keeps someone else's work, untouched")

    def test_a_branch_that_moves_before_the_update_is_not_overwritten(self):
        sha = self.worktree("app.py", "def total(items):\n    return 12\n", "fix")
        self.submit(sha)
        elsewhere = self.commit("test_app.py", "def check():\n    return 0\n", "someone else")
        original = _Checkout.push_fast_forward

        def moves_after_the_check(self, expected, tested):
            subprocess.run(["git", "update-ref", "refs/heads/integration", elsewhere],
                           cwd=self.repository, check=True)
            return original(self, expected, tested)

        _Checkout.push_fast_forward = moves_after_the_check
        self.addCleanup(setattr, _Checkout, "push_fast_forward", original)
        result = self.queue.process_next(self.project["id"])
        self.assertEqual(result["state"], REVIEW)
        self.assertIsNone(result["merge_sha"])
        self.assertIn("moved", result["detail"])
        self.assertEqual(self.branch_sha(), elsewhere,
                         "the compare-and-swap refuses instead of overwriting")

    def test_a_revoked_author_suspends_the_queue(self):
        sha = self.worktree("app.py", "def total(items):\n    return 3\n", "fix")
        self.submit(sha)
        self.queue.suspend(self.project["id"], "The author was revoked.")
        with self.assertRaises(DomainError) as caught:
            self.queue.process_next(self.project["id"])
        self.assertEqual(caught.exception.code, "integration_suspended")
        states = {item["state"] for item in self.queue.list(self.project["id"])}
        self.assertEqual(states, {"suspended"})

    def test_processing_is_serialised_per_project(self):
        first = self.worktree("app.py", "def total(items):\n    return 11\n", "one")
        second = self.worktree("test_app.py", "def check():\n    return 11\n", "two")
        self.submit(first, self.base)
        self.submit(second, self.base)
        first_result = self.queue.process_next(self.project["id"])
        second_result = self.queue.process_next(self.project["id"])
        self.assertEqual(first_result["state"], MERGED)
        self.assertEqual(second_result["state"], MERGED)
        self.assertEqual(second_result["observed_base"], first_result["merge_sha"],
                         "the second patch was recomputed on top of the first")
        states = sorted(item["state"] for item in self.queue.list(self.project["id"]))
        self.assertEqual(states, [MERGED, MERGED])
        self.assertIn("return 11", self.branch_content("app.py"))
        self.assertIn("return 11", self.branch_content("test_app.py"))

    def test_a_missing_branch_is_reviewed(self):
        subprocess.run(["git", "branch", "-D", "integration"], cwd=self.repository,
                       check=True, capture_output=True)
        sha = self.worktree("app.py", "def total(items):\n    return 4\n", "fix")
        self.submit(sha)
        result = self.queue.process_next(self.project["id"])
        self.assertEqual(result["state"], REVIEW)

    def test_an_unknown_project_is_refused(self):
        with self.assertRaises(DomainError) as caught:
            self.queue.process_next("no-such-project")
        self.assertEqual(caught.exception.code, "project_not_found")

    def test_a_malformed_sha_is_refused(self):
        for value in ("short", "Z" * 40, 42, ""):
            with self.subTest(value=value):
                with self.assertRaises(DomainError):
                    self.queue.submit(self.project["id"], value, self.base)

    def test_the_checkout_never_touches_the_working_tree(self):
        sha = self.worktree("app.py", "def total(items):\n    return 6\n", "fix")
        before_files = sorted(item.name for item in self.repository.iterdir())
        before_content = (self.repository / "app.py").read_text(encoding="utf-8")
        self.submit(sha)
        self.queue.process_next(self.project["id"])

        after_files = sorted(item.name for item in self.repository.iterdir())
        self.assertEqual(before_files, after_files,
                         "the integrator must not add or remove files in the working tree")
        self.assertEqual((self.repository / "app.py").read_text(encoding="utf-8"),
                         before_content,
                         "the user's working tree is never the checkout the integrator uses")
        self.assertIn("return 6", self.branch_content("app.py"))


if __name__ == "__main__":
    unittest.main()