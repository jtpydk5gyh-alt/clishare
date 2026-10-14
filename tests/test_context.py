import tempfile
import unittest
from pathlib import Path

from cshcli.context import ContextAssembler
from cshcli.errors import DomainError
from cshcli.store import Store


class FakeStore:
    def __init__(self, store, statuses=None, scopes=None):
        self._store = store
        self._statuses = statuses or {}
        self._scopes = scopes or {}

    def list_memory_page(self, user_id, project_id, limit=10, after=None):
        page = self._store.list_memory_page(user_id, project_id, limit=limit, after=after)
        items = []
        for row in page["items"]:
            patched = dict(row)
            if row["key"] in self._statuses:
                patched["status"] = self._statuses[row["key"]]
            if row["key"] in self._scopes:
                patched["scope"] = self._scopes[row["key"]]
            items.append(patched)
        return {"items": items, "next_cursor": page["next_cursor"]}


class ContextAssemblerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "coordination.sqlite3"
        self.now = 10_000.0
        self.store = Store(self.path, clock=lambda: self.now)
        self.owner = self.store.register_user("owner")
        self.viewer = self.store.register_user("viewer")
        self.outsider = self.store.register_user("outsider")
        self.project = self.store.create_project(self.owner["id"], "shared")
        invitation = self.store.create_invite(self.owner["id"], self.project["id"], "viewer")
        self.store.accept_invite(self.viewer["id"], invitation["token"])
        self.contents = {
            "architecture": "architecture: " + "a" * 40,
            "contracts/api": "contracts/api: " + "c" * 40,
            "decisions/provider": "decisions/provider: " + "d" * 40,
            "handoff/task-1": "handoff/task-1: " + "h" * 40,
            "notes/standup": "notes/standup: " + "n" * 40,
            "refactors/module-a": "refactors/module-a: " + "r" * 40,
            "refactors/module-b": "refactors/module-b: " + "r" * 40,
            "refactors/module-c": "refactors/module-c: " + "r" * 40,
            "refactors/module-d": "refactors/module-d: " + "r" * 40,
            "refactors/module-e": "refactors/module-e: " + "r" * 40,
            "refactors/module-f": "refactors/module-f: " + "r" * 40,
            "rules/style": "rules/style: " + "s" * 40,
        }
        for key, content in self.contents.items():
            self.store.put_memory(self.owner["id"], self.project["id"], key, content, 0)

    def seeded_project(self, name, entries):
        project = self.store.create_project(self.owner["id"], name)
        for key, content in entries.items():
            self.store.put_memory(self.owner["id"], project["id"], key, content, 0)
        return project

    def manifest(self, assembler=None, project=None, budget=100_000, after_revision=None):
        assembler = assembler if assembler is not None else ContextAssembler(self.store, clock=lambda: self.now)
        return assembler.build(
            self.owner["id"],
            (project if project is not None else self.project)["id"],
            "task-1",
            "0f1e2d3",
            budget,
            after_revision,
        )

    def keys(self, items):
        return [item["key"] for item in items]

    def test_manifest_includes_entries_with_author_and_version(self):
        manifest = self.manifest()
        self.assertEqual(
            sorted(manifest),
            [
                "after_revision", "base_sha", "budget_bytes", "entries", "generated_at",
                "omitted", "project_id", "task_id", "used_bytes", "user_id",
            ],
        )
        self.assertEqual(manifest["task_id"], "task-1")
        self.assertEqual(manifest["base_sha"], "0f1e2d3")
        self.assertEqual(manifest["user_id"], self.owner["id"])
        self.assertEqual(manifest["project_id"], self.project["id"])
        self.assertEqual(manifest["budget_bytes"], 100_000)
        self.assertEqual(manifest["after_revision"], None)
        self.assertEqual(manifest["generated_at"], self.now)
        self.assertEqual(manifest["omitted"], [])
        self.assertEqual(self.keys(manifest["entries"]), sorted(self.contents))
        self.assertEqual(len(manifest["entries"]), 12)
        for item in manifest["entries"]:
            self.assertEqual(
                sorted(item),
                ["author_id", "content", "key", "omitted", "scope", "status", "updated_at", "version"],
            )
            self.assertEqual(item["content"], self.contents[item["key"]])
            self.assertEqual(item["author_id"], self.owner["id"])
            self.assertEqual(item["version"], 1)
            self.assertEqual(item["updated_at"], self.now)
            self.assertEqual(item["scope"], "project")
            self.assertEqual(item["status"], "proposed")
            self.assertEqual(item["omitted"], False)
        self.assertEqual(manifest["used_bytes"], sum(len(c.encode("utf-8")) for c in self.contents.values()))

    def test_acl_blocks_non_member(self):
        assembler = ContextAssembler(self.store, clock=lambda: self.now)
        with self.assertRaises(DomainError) as caught:
            assembler.build(self.outsider["id"], self.project["id"], "task-1", "0f1e2d3", 100_000)
        self.assertEqual(caught.exception.status, 403)
        self.assertEqual(caught.exception.code, "not_a_member")
        self.assertEqual(caught.exception.message, "El usuario no pertenece al proyecto.")
        viewer_view = ContextAssembler(self.store, clock=lambda: self.now).build(
            self.viewer["id"], self.project["id"], "task-1", "0f1e2d3", 100_000
        )
        self.assertEqual(viewer_view["user_id"], self.viewer["id"])
        self.assertEqual(self.keys(viewer_view["entries"]), sorted(self.contents))
        self.assertEqual(len(viewer_view["entries"]), 12)

    def test_superseded_entries_are_excluded(self):
        assembler = ContextAssembler(
            FakeStore(self.store, statuses={"decisions/provider": "superseded"}), clock=lambda: self.now
        )
        manifest = self.manifest(assembler=assembler)
        self.assertNotIn("decisions/provider", self.keys(manifest["entries"]))
        self.assertEqual(manifest["omitted"], [])
        self.assertEqual(
            self.keys(manifest["entries"]),
            sorted(["architecture", "contracts/api", "handoff/task-1", "notes/standup", "rules/style"]
                   + [f"refactors/module-{letter}" for letter in "abcdef"]),
        )
        plain = self.manifest()
        self.assertIn("decisions/provider", self.keys(plain["entries"]))

    def test_budget_keeps_rules_and_contracts_first(self):
        entries = {
            "architecture": "a" * 100,
            "contracts/api": "c" * 120,
            "handoff/task-1": "h" * 400,
            "rules/style": "s" * 90,
        }
        project = self.seeded_project("budget", entries)
        manifest = self.manifest(project=project, budget=300)
        self.assertEqual(self.keys(manifest["entries"]), ["contracts/api", "rules/style"])
        self.assertEqual(self.keys(manifest["omitted"]), ["architecture", "handoff/task-1"])
        self.assertEqual(manifest["used_bytes"], 210)
        self.assertEqual(manifest["budget_bytes"], 300)
        self.assertEqual(manifest["entries"][0]["omitted"], False)
        generous = self.manifest(project=project, budget=100_000)
        self.assertEqual(self.keys(generous["entries"]), sorted(entries))
        self.assertEqual(generous["omitted"], [])

    def test_omitted_entries_are_marked_and_truncated(self):
        content = "á" * 99 + "€" + "x" * 50
        project = self.seeded_project("truncation", {"architecture": content})
        manifest = self.manifest(project=project, budget=10)
        self.assertEqual(manifest["entries"], [])
        self.assertEqual(len(manifest["omitted"]), 1)
        item = manifest["omitted"][0]
        self.assertEqual(item["key"], "architecture")
        self.assertEqual(item["omitted"], True)
        self.assertEqual(item["author_id"], self.owner["id"])
        self.assertEqual(item["version"], 1)
        self.assertEqual(item["content"], "á" * 99 + "…")
        self.assertEqual(content.encode("utf-8")[:200].decode("utf-8", errors="ignore"), "á" * 99)
        self.assertEqual(len(item["content"].encode("utf-8")), 201)
        self.assertEqual(manifest["used_bytes"], 0)

    def test_zero_budget_returns_empty_manifest(self):
        for budget in (0, -1):
            with self.subTest(budget=budget):
                manifest = self.manifest(budget=budget)
                self.assertEqual(manifest["entries"], [])
                self.assertEqual(manifest["omitted"], [])
                self.assertEqual(manifest["used_bytes"], 0)
                self.assertEqual(manifest["budget_bytes"], budget)
                self.assertEqual(manifest["task_id"], "task-1")
                self.assertEqual(manifest["base_sha"], "0f1e2d3")
                self.assertEqual(manifest["user_id"], self.owner["id"])
                self.assertEqual(manifest["project_id"], self.project["id"])
                self.assertEqual(manifest["generated_at"], self.now)
                self.assertEqual(manifest["after_revision"], None)

    def test_manifest_is_stable_across_calls(self):
        ticks = iter([1_000.0, 2_000.0])
        assembler = ContextAssembler(self.store, clock=lambda: next(ticks))
        first = assembler.build(self.owner["id"], self.project["id"], "task-1", "0f1e2d3", 400, 7)
        second = assembler.build(self.owner["id"], self.project["id"], "task-1", "0f1e2d3", 400, 7)
        self.assertEqual(first["generated_at"], 1_000.0)
        self.assertEqual(second["generated_at"], 2_000.0)
        self.assertEqual(first["after_revision"], 7)
        first.pop("generated_at")
        second.pop("generated_at")
        self.assertEqual(first, second)
        self.assertTrue(first["omitted"])

    def test_scope_and_status_defaults_are_applied(self):
        store = FakeStore(self.store, statuses={"architecture": None, "rules/style": "accepted"}, scopes={
            "handoff/task-1": "user"
        })
        manifest = self.manifest(assembler=ContextAssembler(store, clock=lambda: self.now))
        entries = {item["key"]: item for item in manifest["entries"]}
        self.assertEqual(entries["architecture"]["status"], "proposed")
        self.assertEqual(entries["architecture"]["scope"], "project")
        self.assertEqual(entries["rules/style"]["status"], "accepted")
        self.assertEqual(entries["handoff/task-1"]["scope"], "user")
        self.assertEqual(entries["notes/standup"]["scope"], "project")
        self.assertEqual(entries["notes/standup"]["status"], "proposed")