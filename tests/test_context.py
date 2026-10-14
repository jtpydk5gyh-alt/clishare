import tempfile
import unittest
from pathlib import Path

from clishare.context import ContextAssembler
from clishare.errors import DomainError
from clishare.store import Store


class _FakeStore:
    def __init__(self, items, members):
        self._items = sorted(
            ({**item} for item in items),
            key=lambda entry: entry["key"],
        )
        self._members = set(members)

    def list_memory_page(self, user_id, project_id, limit=10, after=None):
        del project_id
        if user_id not in self._members:
            raise DomainError(403, "forbidden", "Your project role does not permit this operation.")
        cursor = after or ""
        filtered = [entry for entry in self._items if entry["key"] > cursor]
        sliced = [dict(entry) for entry in filtered[:limit]]
        next_cursor = sliced[-1]["key"] if len(filtered) > limit else None
        return {"items": sliced, "next_cursor": next_cursor}


class ContextAssemblerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "coordination.sqlite3"
        self.now = 10000.0
        self.store = Store(self.path, clock=lambda: self.now)
        self.owner = self.store.register_user("owner")
        self.member = self.store.register_user("member")
        self.viewer = self.store.register_user("viewer")
        self.outsider = self.store.register_user("outsider")
        self.project = self.store.create_project(self.owner["id"], "shared")
        invitation = self.store.create_invite(self.owner["id"], self.project["id"], "member")
        self.store.accept_invite(self.member["id"], invitation["token"])
        viewer_invite = self.store.create_invite(self.owner["id"], self.project["id"], "viewer")
        self.store.accept_invite(self.viewer["id"], viewer_invite["token"])
        self.clock_value = 12345.0
        self.assembler = ContextAssembler(self.store, clock=lambda: self.clock_value)

    def assert_domain(self, status, callback, code=None):
        with self.assertRaises(DomainError) as caught:
            callback()
        self.assertEqual(caught.exception.status, status)
        if code is not None:
            self.assertEqual(caught.exception.code, code)

    def build(self, user=None, budget=4096, after_revision=42):
        return self.assembler.build(
            user_id=(user or self.member)["id"],
            project_id=self.project["id"],
            task_id="task-42",
            base_sha="deadbeef",
            context_budget_bytes=budget,
            after_revision=after_revision,
        )

    def test_manifest_includes_entries_with_author_and_version(self):
        pid = self.project["id"]
        first = self.store.put_memory(self.owner["id"], pid, "alpha", "content-a", 0)
        second = self.store.put_memory(self.member["id"], pid, "beta", "content-b", 0)
        manifest = self.build(budget=4096)
        self.assertEqual(manifest["task_id"], "task-42")
        self.assertEqual(manifest["base_sha"], "deadbeef")
        self.assertEqual(manifest["after_revision"], 42)
        self.assertEqual(manifest["budget_bytes"], 4096)
        self.assertEqual(manifest["generated_at"], self.clock_value)
        self.assertEqual(manifest["omitted"], [])
        keys = [entry["key"] for entry in manifest["entries"]]
        self.assertEqual(keys, ["alpha", "beta"])
        by_key = {entry["key"]: entry for entry in manifest["entries"]}
        self.assertEqual(by_key["alpha"]["author_id"], self.owner["id"])
        self.assertEqual(by_key["alpha"]["version"], first["version"])
        self.assertEqual(by_key["alpha"]["updated_at"], first["updated_at"])
        self.assertEqual(by_key["alpha"]["scope"], "project")
        self.assertEqual(by_key["alpha"]["status"], "proposed")
        self.assertEqual(by_key["alpha"]["content"], "content-a")
        self.assertFalse(by_key["alpha"]["omitted"])
        self.assertEqual(by_key["beta"]["author_id"], self.member["id"])
        self.assertEqual(by_key["beta"]["version"], second["version"])
        self.assertEqual(by_key["beta"]["status"], "proposed")
        expected_used = len("content-a".encode("utf-8")) + len("content-b".encode("utf-8"))
        self.assertEqual(manifest["used_bytes"], expected_used)

    def test_acl_blocks_non_member(self):
        self.assert_domain(403, lambda: self.build(user=self.outsider), "not_a_member")
        viewer_manifest = self.build(user=self.viewer)
        self.assertEqual(viewer_manifest["entries"], [])

    def test_superseded_entries_are_excluded(self):
        items = [
            {"key": "alpha", "content": "a", "version": 1, "author_id": self.owner["id"], "updated_at": 1.0,
             "status": "superseded"},
            {"key": "beta", "content": "b", "version": 1, "author_id": self.owner["id"], "updated_at": 1.0,
             "status": "verified"},
            {"key": "gamma", "content": "c", "version": 1, "author_id": self.owner["id"], "updated_at": 1.0},
        ]
        fake = _FakeStore(items, [self.member["id"]])
        assembler = ContextAssembler(fake, clock=lambda: self.clock_value)
        manifest = assembler.build(
            user_id=self.member["id"],
            project_id=self.project["id"],
            task_id="task-42",
            base_sha="deadbeef",
            context_budget_bytes=4096,
        )
        keys = [entry["key"] for entry in manifest["entries"]]
        self.assertNotIn("alpha", keys)
        self.assertIn("beta", keys)
        self.assertIn("gamma", keys)
        self.assertEqual(manifest["omitted"], [])
        self.assertFalse(all(entry["omitted"] for entry in manifest["entries"]))

    def test_budget_keeps_rules_and_contracts_first(self):
        pid = self.project["id"]
        self.store.put_memory(self.owner["id"], pid, "rules/core", "R" * 500, 0)
        self.store.put_memory(self.owner["id"], pid, "contracts/api", "C" * 500, 0)
        self.store.put_memory(self.owner["id"], pid, "notes/scratch", "N" * 500, 0)
        self.store.put_memory(self.owner["id"], pid, "evidence/run", "E" * 500, 0)
        manifest = self.build(budget=300)
        self.assertNotIn("rules/core", manifest["omitted"])
        self.assertNotIn("contracts/api", manifest["omitted"])
        self.assertIn("notes/scratch", manifest["omitted"])
        self.assertIn("evidence/run", manifest["omitted"])
        by_key = {entry["key"]: entry for entry in manifest["entries"]}
        self.assertEqual(by_key["rules/core"]["content"], "R" * 500)
        self.assertEqual(by_key["contracts/api"]["content"], "C" * 500)
        self.assertFalse(by_key["rules/core"]["omitted"])
        self.assertFalse(by_key["contracts/api"]["omitted"])

    def test_omitted_entries_are_marked_and_truncated(self):
        pid = self.project["id"]
        self.store.put_memory(self.owner["id"], pid, "rules/core", "R" * 100, 0)
        self.store.put_memory(self.owner["id"], pid, "notes/big", "N" * 1000, 0)
        manifest = self.build(budget=150)
        by_key = {entry["key"]: entry for entry in manifest["entries"]}
        omitted_entry = by_key["notes/big"]
        self.assertTrue(omitted_entry["omitted"])
        self.assertTrue(omitted_entry["content"].endswith("\u2026"))
        self.assertLess(len(omitted_entry["content"].encode("utf-8")), 250)
        self.assertNotEqual(omitted_entry["content"], "N" * 1000)
        self.assertFalse(by_key["rules/core"]["omitted"])
        self.assertEqual(by_key["rules/core"]["content"], "R" * 100)
        self.assertIn("notes/big", manifest["omitted"])

    def test_zero_budget_returns_empty_manifest(self):
        pid = self.project["id"]
        self.store.put_memory(self.owner["id"], pid, "alpha", "x", 0)
        self.store.put_memory(self.owner["id"], pid, "rules/core", "y", 0)
        zero = self.build(budget=0)
        self.assertEqual(zero["entries"], [])
        self.assertEqual(zero["used_bytes"], 0)
        self.assertEqual(zero["omitted"], [])
        self.assertEqual(zero["budget_bytes"], 0)
        negative = self.build(budget=-10)
        self.assertEqual(negative["entries"], [])
        self.assertEqual(negative["used_bytes"], 0)
        self.assertEqual(negative["budget_bytes"], -10)

    def test_manifest_is_stable_across_calls(self):
        pid = self.project["id"]
        self.store.put_memory(self.owner["id"], pid, "rules/core", "R" * 500, 0)
        self.store.put_memory(self.owner["id"], pid, "notes/a", "A" * 500, 0)
        self.store.put_memory(self.owner["id"], pid, "notes/b", "B" * 500, 0)
        first = self.build(budget=300)
        second = self.build(budget=300)
        self.assertEqual(first, second)
        self.assertEqual([entry["key"] for entry in first["entries"]], ["notes/a", "notes/b", "rules/core"])
        self.assertEqual(first["omitted"], ["notes/a", "notes/b"])


if __name__ == "__main__":
    unittest.main()