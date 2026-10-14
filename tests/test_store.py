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
from cshcli.store import Store


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


if __name__ == "__main__":
    unittest.main()
