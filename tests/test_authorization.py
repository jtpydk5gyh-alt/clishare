import tempfile
import unittest
from pathlib import Path

from cshcli.errors import DomainError
from cshcli.policy import Policy
from cshcli.store import Store


class AuthorizationGenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "grants.sqlite3"
        self.now = 50_000.0
        self.store = Store(self.path, clock=lambda: self.now)
        self.policy = Policy(self.store, clock=lambda: self.now)
        self.owner = self.store.register_user("ana")
        self.member = self.store.register_user("luis")
        self.project = self.store.create_project(self.owner["id"], "acme")
        invitation = self.store.create_invite(self.owner["id"], self.project["id"], "member")
        self.store.accept_invite(self.member["id"], invitation["token"])

    def test_the_generation_starts_at_one_and_is_stored(self):
        self.assertEqual(
            self.store.authorization_generation(self.owner["id"], self.project["id"]), 1)
        self.assertEqual(
            self.store.authorization_generation(self.owner["id"], self.project["id"]), 1)

    def test_revoking_bumps_the_generation(self):
        self.store.authorization_generation(self.owner["id"], self.project["id"])
        result = self.store.revoke_authorization(
            self.owner["id"], self.project["id"], self.owner["id"])
        self.assertEqual(result["generation"], 2)
        self.assertEqual(
            self.store.authorization_generation(self.owner["id"], self.project["id"]), 2)

    def test_revoking_twice_bumps_again(self):
        self.store.authorization_generation(self.owner["id"], self.project["id"])
        self.store.revoke_authorization(self.owner["id"], self.project["id"], self.owner["id"])
        self.store.revoke_authorization(self.owner["id"], self.project["id"], self.owner["id"])
        self.assertEqual(
            self.store.authorization_generation(self.owner["id"], self.project["id"]), 3)

    def test_generations_are_independent_per_member(self):
        self.store.authorization_generation(self.owner["id"], self.project["id"])
        self.store.authorization_generation(self.member["id"], self.project["id"])
        self.store.revoke_authorization(self.owner["id"], self.project["id"], self.member["id"])
        self.assertEqual(
            self.store.authorization_generation(self.member["id"], self.project["id"]), 2)
        self.assertEqual(
            self.store.authorization_generation(self.owner["id"], self.project["id"]), 1)

    def test_revoking_only_the_owner_is_required(self):
        with self.assertRaises(DomainError) as caught:
            self.store.revoke_authorization(
                self.member["id"], self.project["id"], self.member["id"])
        self.assertEqual(caught.exception.code, "forbidden")

    def test_revoking_an_unknown_user_is_refused(self):
        with self.assertRaises(DomainError) as caught:
            self.store.revoke_authorization(
                self.owner["id"], self.project["id"], "no-existe")
        self.assertEqual(caught.exception.code, "user_not_found")

    def test_an_agent_scope_advances_without_moving_the_member(self):
        self.store.authorization_generation(self.owner["id"], self.project["id"], "agente-1")
        self.store.revoke_authorization(
            self.owner["id"], self.project["id"], self.owner["id"], agent_id="agente-1")
        self.assertEqual(
            self.store.authorization_generation(self.owner["id"], self.project["id"], "agente-1"), 2)
        self.assertEqual(
            self.store.authorization_generation(self.owner["id"], self.project["id"]), 1)

    def test_a_revoked_member_cannot_reserve_a_run(self):
        self.store.authorization_generation(self.member["id"], self.project["id"])
        reservation = self.policy.reserve_run(
            self.member["id"], self.project["id"], "run-1", 1, {"max_agents": 2})
        self.assertEqual(reservation["authorization_generation"], 1)
        self.store.revoke_authorization(
            self.owner["id"], self.project["id"], self.member["id"])
        with self.assertRaises(DomainError) as caught:
            self.policy.reserve_run(
                self.member["id"], self.project["id"], "run-2", 1, {"max_agents": 2})
        self.assertEqual(caught.exception.code, "generation_stale")

    def test_a_run_reserved_before_revocation_cannot_be_settled_afterwards(self):
        self.store.authorization_generation(self.member["id"], self.project["id"])
        reservation = self.policy.reserve_run(
            self.member["id"], self.project["id"], "run-1", 1, {"max_agents": 2})
        self.store.revoke_authorization(
            self.owner["id"], self.project["id"], self.member["id"])
        with self.assertRaises(DomainError) as caught:
            self.policy.finish_run(
                self.member["id"], self.project["id"],
                reservation["run_id"], reservation["attempt_id"], {"cost": 1.0})
        self.assertEqual(caught.exception.code, "generation_stale")

    def test_revocation_is_audited(self):
        self.store.authorization_generation(self.member["id"], self.project["id"])
        self.store.revoke_authorization(
            self.owner["id"], self.project["id"], self.member["id"])
        kinds = [event["kind"] for event in
                 self.store.list_events(self.owner["id"], self.project["id"])]
        self.assertIn("authorization.revoked", kinds)
        event = next(event for event in
                     self.store.list_events(self.owner["id"], self.project["id"])
                     if event["kind"] == "authorization.revoked")
        self.assertEqual(event["data"]["user_id"], self.member["id"])
        self.assertEqual(event["data"]["generation"], 2)


if __name__ == "__main__":
    unittest.main()