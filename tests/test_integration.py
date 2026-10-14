import tempfile
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import unittest
from pathlib import Path

from cshcli.errors import DomainError
from cshcli.integration import IntegrationGate
from cshcli.store import Store


BASE = "a" * 40
HEAD = "b" * 40
OTHER = "c" * 40


class IntegrationGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "gate.sqlite3"
        self.now = 30_000.0
        self.store = Store(self.path, clock=lambda: self.now)
        self.gate = IntegrationGate(self.store, clock=lambda: self.now)
        self.owner = self.store.register_user("ana")
        self.member = self.store.register_user("luis")
        self.project = self.store.create_project(self.owner["id"], "acme")
        invitation = self.store.create_invite(self.owner["id"], self.project["id"], "member")
        self.store.accept_invite(self.member["id"], invitation["token"])

    def assert_domain(self, status, callback, code=None):
        with self.assertRaises(DomainError) as caught:
            callback()
        self.assertEqual(caught.exception.status, status)
        if code is not None:
            self.assertEqual(caught.exception.code, code)

    def lease(self, user, resources, ttl=120, agent="agent-1"):
        return {item["resource"]: item["fence"] for item in
                self.store.acquire_leases(user["id"], self.project["id"], agent, resources, ttl=ttl)}

    def accept(self, user=None, run_id="run-1", fences=None, base=BASE, head=HEAD, generation=1, resources=None):
        user = user or self.owner
        return self.gate.accept_patch(
            user["id"], self.project["id"], run_id, generation,
            fences if fences is not None else self.lease(user, ["file:src/api.py"]),
            base, head, resources,
        )

    def test_accepts_a_patch_that_holds_a_live_lease(self):
        result = self.accept()
        self.assertEqual(result["state"], "accepted")
        self.assertFalse(result["idempotent_replay"])
        self.assertEqual(result["resources"], ["file:src/api.py"])
        self.assertEqual(result["accepted_at"], self.now)
        events = [event["kind"] for event in self.store.list_events(self.owner["id"], self.project["id"])]
        self.assertEqual(events.count("patch.accepted"), 1)

    def test_a_stale_fence_is_rejected(self):
        fences = self.lease(self.owner, ["file:src/api.py"])
        self.now += 121
        self.store.acquire_leases(self.owner["id"], self.project["id"], "agent-2", ["file:src/api.py"], ttl=120)
        self.assert_domain(409, lambda: self.accept(fences=fences), "fence_mismatch")

    def test_an_expired_lease_is_rejected(self):
        fences = self.lease(self.owner, ["file:src/api.py"])
        self.now += 121
        self.assert_domain(409, lambda: self.accept(fences=fences), "lease_expired")

    def test_the_run_that_was_paused_after_validating_cannot_publish_after_expiry(self):
        fences = self.lease(self.owner, ["file:src/api.py"])
        self.now += 121
        self.assert_domain(409, lambda: self.accept(fences=fences, run_id="run-old"), "lease_expired")
        successor = self.lease(self.owner, ["file:src/api.py"], agent="agent-2")
        self.assertNotEqual(successor["file:src/api.py"], fences["file:src/api.py"])
        published = self.accept(fences=successor, run_id="run-new", head=HEAD)
        self.assertEqual(published["state"], "accepted")
        self.assert_domain(409, lambda: self.accept(fences=fences, run_id="run-old2", head=OTHER),
                           "fence_mismatch")

    def test_a_lease_held_by_another_member_cannot_be_published(self):
        fences = self.lease(self.member, ["file:src/api.py"], agent="luis-1")
        self.assert_domain(403, lambda: self.accept(fences=fences), "lease_foreign")

    def test_publishing_without_a_lease_is_rejected(self):
        self.assert_domain(
            409,
            lambda: self.accept(fences={"file:src/api.py": 1}),
            "lease_missing",
        )

    def test_a_stale_generation_is_rejected_before_any_lease_check(self):
        fences = self.lease(self.owner, ["file:src/api.py"])
        self.assert_domain(409, lambda: self.accept(fences=fences, generation=0), "generation_stale")
        self.assert_domain(400, lambda: self.accept(fences=fences, generation="1"), "invalid_generation")

    def test_replaying_the_same_commit_is_idempotent(self):
        fences = self.lease(self.owner, ["file:src/api.py"])
        first = self.accept(run_id="run-a", fences=fences)
        second = self.accept(run_id="run-b", fences=fences)
        self.assertTrue(first["idempotent_replay"] is False)
        self.assertTrue(second["idempotent_replay"] is True)
        self.assertEqual(second["accepted_at"], first["accepted_at"])
        listed = self.gate.list_accepted(self.owner["id"], self.project["id"])
        self.assertEqual(listed["count"], 1)

    def test_one_run_cannot_publish_two_different_patches(self):
        self.accept(run_id="run-a", head=HEAD)
        fences = self.lease(self.owner, ["file:src/other.py"])
        self.assert_domain(
            409,
            lambda: self.accept(run_id="run-a", fences=fences, head=OTHER),
            "run_already_published",
        )

    def test_a_viewer_cannot_publish(self):
        invitation = self.store.create_invite(self.owner["id"], self.project["id"], "viewer")
        viewer = self.store.register_user("marta")
        self.store.accept_invite(viewer["id"], invitation["token"])
        fences = self.lease(self.owner, ["file:src/api.py"])
        self.assert_domain(
            403,
            lambda: self.gate.accept_patch(
                viewer["id"], self.project["id"], "run-v", 1, fences, BASE, HEAD),
            "forbidden",
        )

    def test_malformed_inputs_are_rejected(self):
        fences = self.lease(self.owner, ["file:src/api.py"])
        self.assert_domain(400, lambda: self.accept(fences={}), "invalid_patch")
        self.assert_domain(400, lambda: self.accept(fences=fences, base="abc"), "invalid_patch")
        self.assert_domain(400, lambda: self.accept(fences=fences, base=BASE.upper()), "invalid_patch")
        self.assert_domain(400, lambda: self.accept(fences=fences, head=BASE), "invalid_patch")
        self.assert_domain(400, lambda: self.accept(fences={"file:src/api.py": 0}), "invalid_patch")
        self.assert_domain(400, lambda: self.accept(fences={"file:src/api.py": True}), "invalid_patch")
        self.assert_domain(400, lambda: self.accept(fences={"deploy:staging": 1}), "invalid_patch")
        self.assert_domain(
            400,
            lambda: self.accept(fences=fences, resources=["file:src/other.py"]),
            "invalid_patch",
        )

    def test_list_accepted_is_readable_and_validates_the_limit(self):
        self.accept()
        listed = self.gate.list_accepted(self.owner["id"], self.project["id"], limit=5)
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["items"][0]["commit_sha"], HEAD)
        self.assertEqual(listed["items"][0]["base_sha"], BASE)
        self.assert_domain(400, lambda: self.gate.list_accepted(self.owner["id"], self.project["id"], limit=0),
                           "invalid_limit")
        self.assert_domain(400, lambda: self.gate.list_accepted(self.owner["id"], self.project["id"], limit=101),
                           "invalid_limit")
        self.assert_domain(404, lambda: self.gate.list_accepted(self.owner["id"], "missing"), "project_not_found")

    def test_resources_outside_the_lease_set_are_refused(self):
        fences = self.lease(self.owner, ["file:src/api.py"])
        second = self.lease(self.owner, ["file:tests/api_test.py"])
        combined = dict(fences)
        combined.update(second)
        self.assert_domain(
            400,
            lambda: self.accept(fences=combined, resources=["file:docs/readme.md"]),
            "invalid_patch",
        )
        accepted = self.accept(fences=combined, resources=["file:tests/api_test.py"])
        self.assertEqual(
            accepted["resources"], ["file:src/api.py", "file:tests/api_test.py"])


    def test_expiry_is_checked_after_acquiring_the_database_write_lock(self):
        fences = self.lease(self.owner, ["file:src/api.py"], ttl=1)
        original_connection = self.store._connection
        started = threading.Event()
        def connection(*args, **kwargs):
            started.set()
            return original_connection(*args, **kwargs)
        self.store._connection = connection
        with ThreadPoolExecutor(max_workers=1) as pool:
            with closing(sqlite3.connect(self.path, isolation_level=None)) as blocker:
                blocker.execute("BEGIN IMMEDIATE")
                pending = pool.submit(self.accept, fences=fences)
                self.assertTrue(started.wait(5))
                self.now += 2
                blocker.commit()
            with self.assertRaises(DomainError) as caught:
                pending.result(timeout=5)
        self.assertEqual(caught.exception.code, "lease_expired")
        self.assertEqual(self.gate.list_accepted(self.owner["id"], self.project["id"])["count"], 0)

    def test_replay_returns_the_original_acceptance_and_requires_its_owner(self):
        fences = self.lease(self.owner, ["file:src/api.py"])
        first = self.accept(fences=fences, run_id="original")
        self.now += 121
        replay = self.accept(fences=fences, run_id="retry")
        self.assertEqual({key: value for key, value in replay.items() if key != "idempotent_replay"},
                         {key: value for key, value in first.items() if key != "idempotent_replay"})
        self.assert_domain(403, lambda: self.accept(user=self.member, fences=fences, run_id="foreign"),
                           "patch_foreign")
        self.assert_domain(409, lambda: self.accept(fences=fences, base=OTHER, run_id="changed"),
                           "patch_mismatch")
        self.assert_domain(409, lambda: self.accept(fences={"file:never-leased": 999}, run_id="forged"),
                           "patch_mismatch")

    def test_patch_resources_use_the_same_canonical_form_as_leases(self):
        fences = self.lease(self.owner, ["file:Src/Main.py"])
        result = self.accept(fences={"file:Src/Main.py": fences["file:src/main.py"]},
                             resources=["file:SRC/MAIN.PY"])
        self.assertEqual(result["resources"], ["file:src/main.py"])

    def test_future_generation_cannot_publish(self):
        fences = self.lease(self.owner, ["file:src/api.py"])
        self.assert_domain(409, lambda: self.accept(fences=fences, generation=2), "generation_stale")
        self.assertEqual(self.gate.list_accepted(self.owner["id"], self.project["id"])["count"], 0)


if __name__ == "__main__":
    unittest.main()