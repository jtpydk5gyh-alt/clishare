import hashlib
import json
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

from cshcli.errors import DomainError
from cshcli.store import Store, _SCHEMA


_LEGACY_SCHEMA = """
CREATE TABLE users (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL UNIQUE,
    token_hash TEXT NOT NULL UNIQUE
);
CREATE TABLE projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    owner_id TEXT NOT NULL REFERENCES users(id)
);
CREATE TABLE memberships (
    project_id TEXT NOT NULL REFERENCES projects(id),
    user_id TEXT NOT NULL REFERENCES users(id),
    role TEXT NOT NULL CHECK (role IN ('owner', 'member', 'viewer')),
    PRIMARY KEY (project_id, user_id)
);
CREATE TABLE memory (
    project_id TEXT NOT NULL REFERENCES projects(id),
    key TEXT NOT NULL,
    content TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    author_id TEXT NOT NULL REFERENCES users(id),
    updated_at REAL NOT NULL,
    PRIMARY KEY (project_id, key)
);
"""


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "coordination.sqlite3"
        self.now = 10_000.0
        self.store = Store(self.path, clock=lambda: self.now)
        self.owner = self.store.register_user("owner")
        self.member = self.store.register_user("member")
        self.viewer = self.store.register_user("viewer")
        self.outsider = self.store.register_user("outsider")
        self.project = self.store.create_project(self.owner["id"], "shared")
        for user, role in ((self.member, "member"), (self.viewer, "viewer")):
            invitation = self.store.create_invite(self.owner["id"], self.project["id"], role)
            self.store.accept_invite(user["id"], invitation["token"])

    def assert_domain(self, status, callback, code=None):
        with self.assertRaises(DomainError) as caught:
            callback()
        self.assertEqual(caught.exception.status, status)
        if code is not None:
            self.assertEqual(caught.exception.code, code)

    def acquire(self, user=None, resources=None, agent="agent", ttl=120):
        return self.store.acquire_leases(
            (user or self.owner)["id"], self.project["id"], agent,
            resources or ["file:src/main.py"], ttl,
        )

    def race(self, callback):
        barrier = threading.Barrier(11)

        def run(index):
            barrier.wait(timeout=10)
            try:
                return ("ok", callback(index))
            except DomainError as error:
                return (error.status, error.code)

        with ThreadPoolExecutor(max_workers=11) as pool:
            return list(pool.map(run, range(11)))

    def test_identity_is_persistent_unique_and_authenticates_hashed_tokens(self):
        restarted = Store(self.path)
        self.assertEqual(restarted.authenticate(self.owner["token"]), self.owner["id"])
        self.assert_domain(401, lambda: restarted.authenticate("unknown"), "invalid_token")
        self.assert_domain(409, lambda: self.store.register_user("OWNER"), "name_taken")
        with closing(sqlite3.connect(self.path)) as connection:
            dump = "\n".join(connection.iterdump())
        self.assertNotIn(self.owner["token"], dump)
        self.assertIn(hashlib.sha256(self.owner["token"].encode()).hexdigest(), dump)

    def test_user_and_project_names_reject_empty_control_and_excess_length(self):
        for value in ("", " ", "x" * 81, "bad\nname", None, 17):
            with self.subTest(value=value):
                self.assert_domain(400, lambda: self.store.register_user(value))
        for value in ("", " ", "x" * 121, "bad\tname", None):
            with self.subTest(project=value):
                self.assert_domain(400, lambda: self.store.create_project(self.owner["id"], value))
        self.assert_domain(401, lambda: self.store.create_project("unknown", "project"))
        self.assert_domain(401, lambda: self.store.list_projects("unknown"))

    def test_project_listing_contains_only_memberships_and_roles(self):
        hidden = self.store.create_project(self.outsider["id"], "private")
        listed = self.store.list_projects(self.member["id"])
        self.assertEqual([item["id"] for item in listed], [self.project["id"]])
        self.assertEqual(listed[0]["role"], "member")
        self.assertNotIn(hidden["id"], json.dumps(listed))

    def test_every_project_operation_checks_membership(self):
        uid, pid = self.outsider["id"], self.project["id"]
        lease = self.acquire()[0]
        operations = [
            lambda: self.store.create_invite(uid, pid),
            lambda: self.store.list_memory(uid, pid),
            lambda: self.store.put_memory(uid, pid, "context", "secret", 0),
            lambda: self.store.acquire_leases(uid, pid, "agent", ["file:other.py"]),
            lambda: self.store.list_leases(uid, pid),
            lambda: self.store.renew_lease(uid, pid, lease["id"], lease["fence"]),
            lambda: self.store.release_lease(uid, pid, lease["id"], lease["fence"]),
            lambda: self.store.list_events(uid, pid),
        ]
        for operation in operations:
            self.assert_domain(403, operation, "forbidden")
        self.assert_domain(404, lambda: self.store.list_memory(self.owner["id"], "missing"))
        self.assert_domain(401, lambda: self.store.list_memory("unknown", pid))

    def test_viewer_can_read_but_cannot_mutate_or_invite(self):
        uid, pid = self.viewer["id"], self.project["id"]
        lease = self.acquire()[0]
        for operation in (
            lambda: self.store.put_memory(uid, pid, "context", "value", 0),
            lambda: self.store.acquire_leases(uid, pid, "agent", ["file:viewer.py"]),
            lambda: self.store.renew_lease(uid, pid, lease["id"], lease["fence"]),
            lambda: self.store.release_lease(uid, pid, lease["id"], lease["fence"]),
            lambda: self.store.create_invite(uid, pid),
            lambda: self.store.create_invite(self.member["id"], pid),
        ):
            self.assert_domain(403, operation)
        self.assertEqual(self.store.list_memory(uid, pid), [])
        self.assertEqual(len(self.store.list_leases(uid, pid)), 1)
        self.assertTrue(self.store.list_events(uid, pid))

    def test_invitation_expires_and_is_single_use_and_hash_only(self):
        pid = self.project["id"]
        invite = self.store.create_invite(self.owner["id"], pid, "member", ttl=1)
        with closing(sqlite3.connect(self.path)) as connection:
            dump = "\n".join(connection.iterdump())
        self.assertNotIn(invite["token"], dump)
        self.now += 1
        self.assert_domain(409, lambda: self.store.accept_invite(self.outsider["id"], invite["token"]), "invite_expired")
        invite = self.store.create_invite(self.owner["id"], pid, "viewer")
        accepted = self.store.accept_invite(self.outsider["id"], invite["token"])
        self.assertEqual(accepted, {"project_id": pid, "role": "viewer"})
        self.assert_domain(409, lambda: self.store.accept_invite(self.member["id"], invite["token"]), "invite_used")
        self.assert_domain(404, lambda: self.store.accept_invite(self.member["id"], "not-a-token"), "invite_not_found")

    def test_owner_is_not_downgraded_when_accepting_invitation(self):
        invitation = self.store.create_invite(self.owner["id"], self.project["id"], "viewer")
        result = self.store.accept_invite(self.owner["id"], invitation["token"])
        self.assertEqual(result["role"], "owner")
        self.assertEqual(self.store.list_projects(self.owner["id"])[0]["role"], "owner")

    def test_invitation_role_and_ttl_are_validated_strictly(self):
        for role in ("owner", "admin", "", None):
            self.assert_domain(400, lambda: self.store.create_invite(self.owner["id"], self.project["id"], role))
        for ttl in (0, -1, 604801, True, 1.0, "1", None):
            self.assert_domain(400, lambda: self.store.create_invite(self.owner["id"], self.project["id"], ttl=ttl))
        self.store.create_invite(self.owner["id"], self.project["id"], ttl=604800)

    def test_concurrent_invitation_acceptance_has_exactly_one_winner(self):
        invite = self.store.create_invite(self.owner["id"], self.project["id"])
        users = [self.store.register_user(f"invite-user-{index}") for index in range(11)]
        results = self.race(lambda index: self.store.accept_invite(users[index]["id"], invite["token"]))
        self.assertEqual(sum(status == "ok" for status, _ in results), 1)
        self.assertEqual(sum(status == 409 for status, _ in results), 10)
        self.assertEqual(sum(bool(self.store.list_projects(user["id"])) for user in users), 1)

    def test_memory_uses_versions_and_persists_authorship(self):
        pid, uid = self.project["id"], self.member["id"]
        first = self.store.put_memory(uid, pid, "architecture", "initial", 0)
        self.assertEqual((first["version"], first["author_id"]), (1, uid))
        self.assert_domain(409, lambda: self.store.put_memory(uid, pid, "architecture", "stale", 0), "version_conflict")
        second = self.store.put_memory(self.owner["id"], pid, "architecture", "updated", 1)
        self.assertEqual(second["version"], 2)
        self.assertEqual(Store(self.path).list_memory(uid, pid), [second])
        for version in (-1, True, 1.0, "1", None):
            self.assert_domain(400, lambda: self.store.put_memory(uid, pid, "architecture", "bad", version))

    def test_concurrent_memory_cas_prevents_lost_updates(self):
        results = self.race(lambda index: self.store.put_memory(
            self.member["id"], self.project["id"], "decision", str(index), 0,
        ))
        self.assertEqual(sum(status == "ok" for status, _ in results), 1)
        self.assertEqual(sum(status == 409 for status, _ in results), 10)
        self.assertEqual(self.store.list_memory(self.owner["id"], self.project["id"])[0]["version"], 1)

    def test_eleven_agents_across_two_users_have_one_lease_winner(self):
        results = self.race(lambda index: self.acquire(
            self.owner if index < 5 else self.member, agent=f"agent-{index}",
        ))
        self.assertEqual(sum(status == "ok" for status, _ in results), 1)
        self.assertEqual(sum(status == 409 for status, _ in results), 10)
        self.assertEqual(len(self.store.list_leases(self.owner["id"], self.project["id"])), 1)

    def test_resource_conflicts_follow_directory_boundaries_and_windows_case(self):
        parent = self.acquire(resources=["file:Src"])[0]
        self.assertEqual(parent["resource"], "file:src")
        self.assert_domain(409, lambda: self.acquire(resources=["file:src/Main.py"]))
        self.acquire(resources=["file:src2/main.py"])
        self.store.release_lease(self.owner["id"], self.project["id"], parent["id"], parent["fence"])
        self.acquire(resources=["file:SRC/main.py"])
        self.assert_domain(409, lambda: self.acquire(resources=["file:src"]))

    def test_batch_acquisition_is_atomic_when_any_resource_conflicts(self):
        self.acquire(resources=["file:z.py"])
        self.assert_domain(409, lambda: self.acquire(resources=["file:a.py", "file:z.py"]))
        acquired = self.acquire(resources=["file:a.py"])
        self.assertEqual(len(acquired), 1)

    def test_resource_validation_rejects_unsafe_or_ambiguous_paths(self):
        for resource in (
            "", "src/a.py", "file:", "file:/src", "file:C:/src", "file:../src",
            "file:src/../a.py", "file:src\\a.py", "file:a//b", "file:a/", "file:./a",
            "file:a. ", "file:con.txt", "file:a:b", "file:a\n", "deploy:",
            "deploy:../prod", "deploy:prod/main", "other:value", None,
        ):
            with self.subTest(resource=resource):
                self.assert_domain(400, lambda: self.acquire(resources=[resource]))
        self.assert_domain(400, lambda: self.store.acquire_leases(self.owner["id"], self.project["id"], "agent", []))
        self.assert_domain(400, lambda: self.acquire(resources=["file:a", "file:A"]))
        self.assert_domain(400, lambda: self.acquire(resources=["file:a", "file:a/b"]))

    def test_deploy_is_owner_only_and_environment_is_exact(self):
        self.assert_domain(403, lambda: self.acquire(self.member, ["deploy:prod"]))
        self.acquire(resources=["deploy:prod"])
        self.assert_domain(409, lambda: self.acquire(resources=["deploy:PROD"]))
        self.acquire(resources=["deploy:prod-eu"])
        self.acquire(resources=["file:prod"])

    def test_expiry_invalidates_stale_holder_and_fences_survive_restart(self):
        pid, uid = self.project["id"], self.owner["id"]
        old = self.acquire(ttl=1)[0]
        self.now += 1
        self.assertEqual(self.store.list_leases(uid, pid), [])
        self.assert_domain(409, lambda: self.store.renew_lease(uid, pid, old["id"], old["fence"]), "lease_expired")
        new = Store(self.path, clock=lambda: self.now).acquire_leases(uid, pid, "new", ["file:src/main.py"])[0]
        self.assertGreater(new["fence"], old["fence"])
        self.assert_domain(409, lambda: self.store.release_lease(uid, pid, old["id"], old["fence"]), "lease_expired")
        self.assertEqual(self.store.list_leases(uid, pid), [new])
        self.store.release_lease(uid, pid, new["id"], new["fence"])
        latest = Store(self.path, clock=lambda: self.now).acquire_leases(uid, pid, "latest", ["file:src/main.py"])[0]
        self.assertGreater(latest["fence"], new["fence"])

    def test_renew_and_release_require_holder_and_current_fence(self):
        pid, uid = self.project["id"], self.owner["id"]
        lease = self.acquire(ttl=2)[0]
        self.assert_domain(403, lambda: self.store.renew_lease(self.member["id"], pid, lease["id"], lease["fence"]))
        self.assert_domain(403, lambda: self.store.release_lease(self.member["id"], pid, lease["id"], lease["fence"]))
        self.assert_domain(409, lambda: self.store.renew_lease(uid, pid, lease["id"], lease["fence"] + 1), "fence_mismatch")
        self.assert_domain(409, lambda: self.store.release_lease(uid, pid, lease["id"], lease["fence"] + 1), "fence_mismatch")
        self.now += 1
        renewed = self.store.renew_lease(uid, pid, lease["id"], lease["fence"], ttl=10)
        self.assertEqual(renewed["expires_at"], self.now + 10)
        self.assertEqual(renewed["fence"], lease["fence"])
        self.assertEqual(self.store.release_lease(uid, pid, lease["id"], lease["fence"]), {"released": True})
        self.assertEqual(self.store.list_leases(uid, pid), [])

    def test_lease_ttl_fence_and_agent_are_strictly_validated(self):
        for ttl in (0, -1, 3601, True, 1.0, "1", None):
            self.assert_domain(400, lambda: self.acquire(ttl=ttl))
        lease = self.acquire(ttl=3600)[0]
        for fence in (0, -1, True, 1.0, "1", None):
            self.assert_domain(400, lambda: self.store.renew_lease(self.owner["id"], self.project["id"], lease["id"], fence))
            self.assert_domain(400, lambda: self.store.release_lease(self.owner["id"], self.project["id"], lease["id"], fence))
        self.assert_domain(400, lambda: self.acquire(agent=""))

    def test_lease_id_cannot_be_used_in_another_project(self):
        lease = self.acquire()[0]
        another = self.store.create_project(self.owner["id"], "another")
        self.assert_domain(404, lambda: self.store.renew_lease(self.owner["id"], another["id"], lease["id"], lease["fence"]))
        self.assert_domain(404, lambda: self.store.release_lease(self.owner["id"], another["id"], lease["id"], lease["fence"]))

    def test_events_are_persistent_project_scoped_and_do_not_contain_secrets(self):
        self.store.put_memory(self.member["id"], self.project["id"], "secret", "PRIVATE-CONTENT", 0)
        lease = self.acquire()[0]
        self.store.renew_lease(self.owner["id"], self.project["id"], lease["id"], lease["fence"])
        self.store.release_lease(self.owner["id"], self.project["id"], lease["id"], lease["fence"])
        events = Store(self.path).list_events(self.viewer["id"], self.project["id"])
        serialized = json.dumps(events)
        self.assertNotIn("PRIVATE-CONTENT", serialized)
        self.assertNotIn(self.owner["token"], serialized)
        self.assertTrue(all(event["project_id"] == self.project["id"] for event in events))
        self.assertIn("memory.updated", [event["kind"] for event in events])
        self.assertEqual(len(self.store.list_events(self.owner["id"], self.project["id"], limit=2)), 2)
        for limit in (0, 1001, True, 1.0, "1"):
            self.assert_domain(400, lambda: self.store.list_events(self.owner["id"], self.project["id"], limit))

    def test_malformed_unicode_is_a_domain_error_instead_of_a_server_crash(self):
        malformed = "bad\ud800"
        self.assert_domain(400, lambda: self.store.register_user(malformed))
        self.assert_domain(400, lambda: self.acquire(resources=["file:" + malformed]))
        self.assert_domain(400, lambda: self.store.put_memory(self.owner["id"], self.project["id"], "context", malformed, 0))
        self.assert_domain(401, lambda: self.store.authenticate(malformed))
        self.assert_domain(404, lambda: self.store.accept_invite(self.owner["id"], malformed))

    def test_memory_rejects_invalid_keys_and_oversized_content(self):
        for key in ("", " ", "bad\nkey", "x" * 201, None):
            self.assert_domain(400, lambda: self.store.put_memory(self.owner["id"], self.project["id"], key, "content", 0))
        for content in (None, 17, "x" * 262145, "é" * 131073):
            self.assert_domain(400, lambda: self.store.put_memory(self.owner["id"], self.project["id"], "context", content, 0))
        self.assertEqual(self.store.list_memory(self.owner["id"], self.project["id"]), [])
        self.store.put_memory(self.owner["id"], self.project["id"], "context", "", 0)

    def test_resource_ownership_is_scoped_to_project(self):
        self.acquire(resources=["file:src/main.py"])
        another = self.store.create_project(self.owner["id"], "another")
        acquired = self.store.acquire_leases(self.owner["id"], another["id"], "agent", ["file:src/main.py"])
        self.assertEqual(len(acquired), 1)

    def test_memory_pages_return_all_entries_once_in_key_order(self):
        uid, pid = self.owner["id"], self.project["id"]
        for index in reversed(range(12)):
            self.store.put_memory(uid, pid, f"entry-{index:02d}", str(index), 0)
        first = self.store.list_memory_page(uid, pid)
        self.assertEqual([item["key"] for item in first["items"]], [f"entry-{index:02d}" for index in range(10)])
        self.assertEqual(first["next_cursor"], "entry-09")
        second = self.store.list_memory_page(uid, pid, after=first["next_cursor"])
        self.assertEqual([item["key"] for item in second["items"]], ["entry-10", "entry-11"])
        self.assertIsNone(second["next_cursor"])
        collected, cursor = [], None
        while True:
            page = self.store.list_memory_page(uid, pid, limit=5, after=cursor)
            collected.extend(item["key"] for item in page["items"])
            cursor = page["next_cursor"]
            if cursor is None:
                break
        self.assertEqual(collected, [f"entry-{index:02d}" for index in range(12)])
        self.assertEqual(self.store.list_memory_page(uid, pid, after="zzz"), {"items": [], "next_cursor": None})

    def test_memory_pages_enforce_membership_and_validate_arguments(self):
        uid, pid = self.owner["id"], self.project["id"]
        self.assert_domain(403, lambda: self.store.list_memory_page(self.outsider["id"], pid))
        self.assertEqual(self.store.list_memory_page(self.viewer["id"], pid), {"items": [], "next_cursor": None})
        for limit in (0, -1, 11, True, 1.0, "1", None):
            self.assert_domain(400, lambda: self.store.list_memory_page(uid, pid, limit=limit))
        for after in ("", " ", "x" * 201, "bad\nkey", "bad\ud800", True, 1, []):
            self.assert_domain(400, lambda: self.store.list_memory_page(uid, pid, after=after))

    def test_memory_pages_preserve_large_text_without_truncation(self):
        uid, pid = self.owner["id"], self.project["id"]
        content = "é" * 131072
        for index in range(4):
            self.store.put_memory(uid, pid, f"large-{index}", content, 0)
        page = self.store.list_memory_page(uid, pid, limit=3)
        self.assertEqual(len(page["items"]), 3)
        self.assertTrue(all(item["content"] == content for item in page["items"]))
        self.assertEqual(page["next_cursor"], "large-2")
        final = self.store.list_memory_page(uid, pid, limit=3, after=page["next_cursor"])
        self.assertEqual(len(final["items"]), 1)
        self.assertEqual(final["items"][0]["content"], content)
        self.assertIsNone(final["next_cursor"])

    def test_memory_accepts_kind_scope_status_and_evidence(self):
        uid, pid = self.member["id"], self.project["id"]
        metadata = {
            "kind": "decision", "scope": "task", "status": "verified",
            "source_commit": "0f1e2d3c", "evidence": ["docs/spec.md#7"],
        }
        written = self.store.put_memory(uid, pid, "decisions/provider-auth", "sqlite", 0, metadata)
        self.assertEqual(
            (written["kind"], written["scope"], written["status"], written["source_commit"]),
            ("decision", "task", "verified", "0f1e2d3c"),
        )
        self.assertEqual(written["evidence"], ["docs/spec.md#7"])
        listed = Store(self.path).list_memory(uid, pid)
        self.assertEqual(listed, [written])
        page = self.store.list_memory_page(uid, pid)
        self.assertEqual(page["items"], [written])
        for kind in ("contract", "evidence", "handoff"):
            updated = self.store.put_memory(
                uid, pid, f"entries/{kind}", "body", 0, {"kind": kind, "scope": "resource"},
            )
            self.assertEqual((updated["kind"], updated["scope"], updated["status"]), (kind, "resource", "proposed"))

    def test_memory_rejects_invalid_kind_or_scope_or_status(self):
        uid, pid = self.owner["id"], self.project["id"]
        for field, values in (
            ("kind", ("note", "", 17, True, ["decision"])),
            ("scope", ("team", "", 17, True, ["project"])),
            ("status", ("draft", "", 17, True, None, ["proposed"])),
            ("source_commit", (17, True, "x" * 201)),
            ("evidence", ("note", [1], [["note"]], {"note": True}, 7)),
            ("expires_at", ("1", True, [1], {"at": 1})),
        ):
            for value in values:
                with self.subTest(field=field, value=value):
                    self.assert_domain(
                        400,
                        lambda field=field, value=value: self.store.put_memory(
                            uid, pid, "rejected", "body", 0, {field: value},
                        ),
                        "invalid_memory_metadata",
                    )
        self.assert_domain(400, lambda: self.store.put_memory(uid, pid, "rejected", "body", 0, []), "invalid_memory_metadata")
        self.assertEqual(self.store.list_memory(uid, pid), [])
        allowed = self.store.put_memory(uid, pid, "allowed", "body", 0, {"kind": None, "scope": None, "evidence": []})
        self.assertEqual((allowed["kind"], allowed["scope"], allowed["evidence"]), (None, None, []))

    def test_memory_evidence_round_trips_as_json(self):
        uid, pid = self.owner["id"], self.project["id"]
        evidence = ['tests/test_store.py:42 "quoted"', "línea con acentos ✓", "", "path/to/file.py"]
        written = self.store.put_memory(uid, pid, "evidence/audit", "body", 0, {"kind": "evidence", "evidence": evidence})
        self.assertEqual(written["evidence"], evidence)
        with closing(sqlite3.connect(self.path)) as connection:
            raw = connection.execute("SELECT evidence FROM memory WHERE project_id = ? AND key = ?", (pid, "evidence/audit")).fetchone()[0]
        self.assertIsInstance(raw, str)
        self.assertEqual(json.loads(raw), evidence)
        self.assertEqual(Store(self.path).list_memory(uid, pid)[0]["evidence"], evidence)

    def test_memory_corrupt_evidence_reads_as_none(self):
        uid, pid = self.owner["id"], self.project["id"]
        self.store.put_memory(uid, pid, "evidence/broken", "body", 0, {"evidence": ["ok"]})
        self.store.put_memory(uid, pid, "evidence/wrong-shape", "body", 0, {"evidence": ["ok"]})
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("UPDATE memory SET evidence = ? WHERE project_id = ? AND key = ?", ("{not json", pid, "evidence/broken"))
            connection.execute("UPDATE memory SET evidence = ? WHERE project_id = ? AND key = ?", ('{"note": true}', pid, "evidence/wrong-shape"))
            connection.commit()
        entries = Store(self.path).list_memory(uid, pid)
        self.assertEqual([item["key"] for item in entries], ["evidence/broken", "evidence/wrong-shape"])
        self.assertTrue(all(item["evidence"] is None for item in entries))
        self.assertEqual(Store(self.path).list_memory_page(uid, pid)["items"], entries)

    def test_memory_status_defaults_to_proposed(self):
        uid, pid = self.owner["id"], self.project["id"]
        default = self.store.put_memory(uid, pid, "handoff/task-42", "body", 0)
        self.assertEqual(default["status"], "proposed")
        self.assertEqual(default["kind"], None)
        self.assertEqual(default["scope"], None)
        self.assertEqual(default["evidence"], None)
        self.assertEqual(default["expires_at"], None)
        self.assertEqual(default["source_commit"], None)
        self.assertEqual(Store(self.path).list_memory(uid, pid), [default])
        self.assertEqual(self.store.put_memory(uid, pid, "handoff/task-42", "body", 1, {})["status"], "proposed")
        superseded = self.store.put_memory(uid, pid, "handoff/task-42", "body", 2, {"status": "superseded"})
        self.assertEqual(superseded["status"], "superseded")
        self.assertEqual(Store(self.path).list_memory(uid, pid)[0]["status"], "superseded")

    def test_memory_legacy_entries_without_metadata_still_read(self):
        path = Path(self.temp.name) / "pilot.sqlite3"
        with closing(sqlite3.connect(path)) as connection:
            connection.executescript(_LEGACY_SCHEMA)
            token_hash = hashlib.sha256(b"pilot-token").hexdigest()
            connection.execute(
                "INSERT INTO users(id, name, name_key, token_hash) VALUES (?, ?, ?, ?)",
                ("pilot-owner", "pilot owner", "pilot owner", token_hash),
            )
            connection.execute(
                "INSERT INTO projects(id, name, owner_id) VALUES (?, ?, ?)", ("pilot-project", "pilot", "pilot-owner")
            )
            connection.execute(
                "INSERT INTO memberships(project_id, user_id, role) VALUES (?, ?, 'owner')", ("pilot-project", "pilot-owner")
            )
            connection.execute(
                "INSERT INTO memory(project_id, key, content, version, author_id, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("pilot-project", "architecture", "one worktree per task", 3, "pilot-owner", 4242.0),
            )
            connection.commit()
        store = Store(path, clock=lambda: self.now)
        with closing(sqlite3.connect(path)) as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(memory)")}
        self.assertTrue({"kind", "scope", "status", "source_commit", "evidence", "expires_at"} <= columns)
        legacy = store.list_memory("pilot-owner", "pilot-project")
        self.assertEqual(len(legacy), 1)
        self.assertEqual(
            (legacy[0]["key"], legacy[0]["content"], legacy[0]["version"], legacy[0]["updated_at"]),
            ("architecture", "one worktree per task", 3, 4242.0),
        )
        self.assertEqual(legacy[0]["status"], "proposed")
        for field in ("kind", "scope", "source_commit", "evidence", "expires_at"):
            self.assertIsNone(legacy[0][field])
        self.assertEqual(store.list_memory_page("pilot-owner", "pilot-project")["items"], legacy)
        updated = store.put_memory(
            "pilot-owner", "pilot-project", "architecture", "two worktrees", 3,
            {"kind": "decision", "scope": "project", "status": "verified", "source_commit": "9c8b7a6"},
        )
        self.assertEqual((updated["version"], updated["status"], updated["kind"]), (4, "verified", "decision"))
        self.assertEqual(Store(path).list_memory("pilot-owner", "pilot-project")[0]["content"], "two worktrees")

    def test_memory_expires_at_is_stored_as_float(self):
        uid, pid = self.owner["id"], self.project["id"]
        written = self.store.put_memory(uid, pid, "evidence/transient", "body", 0, {"expires_at": 10_500})
        self.assertIsInstance(written["expires_at"], float)
        self.assertEqual(written["expires_at"], 10_500.0)
        fractional = self.store.put_memory(uid, pid, "evidence/fractional", "body", 0, {"expires_at": 0.5})
        self.assertEqual(fractional["expires_at"], 0.5)
        with closing(sqlite3.connect(self.path)) as connection:
            row = connection.execute(
                "SELECT expires_at FROM memory WHERE project_id = ? AND key = ?", (pid, "evidence/transient"),
            ).fetchone()
        self.assertIsInstance(row[0], float)
        self.assertEqual(row[0], 10_500.0)
        self.assertEqual(Store(self.path).list_memory(uid, pid)[0]["expires_at"], 0.5)
        negative = self.store.put_memory(uid, pid, "evidence/past", "body", 0, {"expires_at": -1})
        self.assertEqual(negative["expires_at"], -1.0)


    def test_health_does_not_recreate_a_missing_database_or_accept_an_empty_one(self):
        self.assertTrue(self.store.ping())
        self.path.unlink()
        self.assertFalse(self.store.ping())
        self.assertFalse(self.path.exists())
        with closing(sqlite3.connect(self.path)):
            pass
        self.assertFalse(self.store.ping())

    def test_reservation_migration_preserves_settlements_and_fencing_sequence(self):
        for settled in (False, True):
            with self.subTest(settled=settled):
                path = Path(self.temp.name) / f"legacy-reservations-{settled}.sqlite3"
                with closing(sqlite3.connect(path)) as connection:
                    connection.executescript(_SCHEMA.replace(
                        "'reserved', 'settled', 'abandoned'", "'reserved', 'settled'"))
                    connection.execute("INSERT INTO users VALUES ('u', 'u', 'u', 'token')")
                    connection.execute("INSERT INTO projects VALUES ('p', 'p', 'u')")
                    connection.execute("INSERT INTO memberships VALUES ('p', 'u', 'owner')")
                    connection.execute("INSERT INTO leases VALUES (42, 'old', 'p', 'agent', 'u', 'file:a', 1)")
                    connection.execute("INSERT INTO run_reservations VALUES ('r', 'a', 'u', 'p', 1, '{}', ?, 1)",
                                       ("settled" if settled else "reserved",))
                    if settled:
                        connection.execute("INSERT INTO run_settlements VALUES ('r', 'a', ?, '[]', 2)", (json.dumps({"cost": 1}, separators=(",", ":")),))
                    connection.commit()
                migrated = Store(path, clock=lambda: self.now)
                from cshcli.policy import Policy
                if not settled:
                    Policy(migrated).finish_run("u", "p", "r", "a", {"cost": 1})
                with closing(sqlite3.connect(path)) as connection:
                    self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
                    self.assertEqual(connection.execute("SELECT measured_usage_json FROM run_settlements").fetchone()[0],
                                     '{"cost":1}')
                    self.assertEqual({row[2] for row in connection.execute("PRAGMA foreign_key_list(run_settlements)")},
                                     {"run_reservations"})
                lease = migrated.acquire_leases("u", "p", "agent", ["file:a"])[0]
                self.assertGreater(lease["fence"], 42)
                self.assertTrue(Store(path).ping())

    def test_health_rejects_an_incomplete_schema(self):
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("ALTER TABLE memory DROP COLUMN kind")
            connection.commit()
        self.assertFalse(self.store.ping())


if __name__ == "__main__":
    unittest.main()
