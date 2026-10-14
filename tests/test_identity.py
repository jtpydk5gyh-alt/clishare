import tempfile
import unittest
from pathlib import Path

from cshcli.errors import DomainError
from cshcli.identity import Identity


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = Clock()
        self.identity = Identity(str(Path(self.temp.name) / "identity.sqlite3"),
                                 secret=b"k" * 32, clock=self.clock)
        self.addCleanup(self.identity.close)

    def test_a_session_authenticates_and_carries_no_token(self):
        session = self.identity.issue_session("u1", ttl=3600)
        self.assertEqual(self.identity.authenticate(session["token"]), "u1")
        rows = self.identity.connection.execute("SELECT * FROM sessions").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertNotIn(session["token"], str(dict(rows[0])))
        self.assertNotEqual(rows[0]["token_hash"], session["token"])

    def test_an_unknown_token_is_refused(self):
        for token in ("", "nope", "x" * 5000, None, 42):
            with self.subTest(token=token):
                with self.assertRaises(DomainError) as caught:
                    self.identity.authenticate(token)
                self.assertEqual(caught.exception.code, "invalid_token")

    def test_an_expired_session_stops_working(self):
        session = self.identity.issue_session("u1", ttl=60)
        self.clock.advance(61)
        with self.assertRaises(DomainError) as caught:
            self.identity.authenticate(session["token"])
        self.assertEqual(caught.exception.code, "session_expired")

    def test_revoking_one_session_leaves_the_others(self):
        first = self.identity.issue_session("u1", ttl=3600)
        second = self.identity.issue_session("u1", ttl=3600)
        self.identity.revoke_session("u1", first["session_id"])
        with self.assertRaises(DomainError):
            self.identity.authenticate(first["token"])
        self.assertEqual(self.identity.authenticate(second["token"]), "u1")

    def test_another_member_cannot_revoke_someone_elses_session(self):
        session = self.identity.issue_session("u1", ttl=3600)
        with self.assertRaises(DomainError) as caught:
            self.identity.revoke_session("u2", session["session_id"])
        self.assertEqual(caught.exception.code, "session_not_found")

    def test_revoking_a_member_ends_every_session_they_hold(self):
        first = self.identity.issue_session("u1", ttl=3600)
        second = self.identity.issue_session("u1", ttl=3600)
        self.identity.revoke_agent("owner", "p1", "u1")
        for session in (first, second):
            with self.assertRaises(DomainError):
                self.identity.authenticate(session["token"])

    def test_generation_starts_at_zero_and_advances(self):
        self.assertEqual(self.identity.authorization_generation("u1", "p1"), 0)
        first = self.identity.revoke_agent("owner", "p1", "u1", agent_id="a1")
        self.assertEqual(first["authorization_generation"], 1)
        second = self.identity.revoke_agent("owner", "p1", "u1", agent_id="a1")
        self.assertEqual(second["authorization_generation"], 2)

    def test_revoking_one_agent_does_not_end_the_members_sessions(self):
        session = self.identity.issue_session("u1", ttl=3600)
        self.identity.revoke_agent("owner", "p1", "u1", agent_id="a1")
        self.assertEqual(self.identity.authenticate(session["token"]), "u1")

    def test_work_queued_before_a_revocation_cannot_act_afterwards(self):
        generation = self.identity.authorization_generation("u1", "p1", agent_id="a1")
        queued = {"run_id": "run-1", "artifact": "keep-me.txt"}
        self.identity.revoke_agent("owner", "p1", "u1", agent_id="a1")
        with self.assertRaises(DomainError) as caught:
            self.identity.assert_authorized("u1", "p1", generation, agent_id="a1")
        self.assertEqual(caught.exception.code, "authorization_revoked")
        self.assertEqual(queued["artifact"], "keep-me.txt")

    def test_work_authorised_after_the_revocation_may_act(self):
        self.identity.revoke_agent("owner", "p1", "u1", agent_id="a1")
        generation = self.identity.authorization_generation("u1", "p1", agent_id="a1")
        self.identity.assert_authorized("u1", "p1", generation, agent_id="a1")

    def test_an_agent_scope_does_not_disturb_the_member_scope(self):
        member = self.identity.authorization_generation("u1", "p1")
        self.identity.revoke_agent("owner", "p1", "u1", agent_id="a1")
        self.assertEqual(self.identity.authorization_generation("u1", "p1"), member)

    def test_two_identities_with_the_same_secret_agree(self):
        other = Identity(str(Path(self.temp.name) / "identity.sqlite3"),
                         secret=b"k" * 32, clock=self.clock)
        self.addCleanup(other.close)
        session = self.identity.issue_session("u1", ttl=3600)
        self.assertEqual(other.authenticate(session["token"]), "u1")

    def test_a_different_secret_does_not_accept_the_token(self):
        other = Identity(":memory:", secret=b"z" * 32, clock=self.clock)
        self.addCleanup(other.close)
        session = self.identity.issue_session("u1", ttl=3600)
        with self.assertRaises(DomainError):
            other.authenticate(session["token"])

    def test_a_revoked_token_cannot_be_replayed_from_another_process(self):
        session = self.identity.issue_session("u1", ttl=3600)
        other = Identity(str(Path(self.temp.name) / "identity.sqlite3"),
                         secret=b"k" * 32, clock=self.clock)
        self.addCleanup(other.close)
        self.identity.revoke_session("u1", session["session_id"])
        with self.assertRaises(DomainError):
            other.authenticate(session["token"])

    def test_ttl_must_be_sane(self):
        for ttl in (0, -1, 31 * 24 * 3600, True, "60"):
            with self.subTest(ttl=ttl):
                with self.assertRaises(DomainError):
                    self.identity.issue_session("u1", ttl=ttl)


if __name__ == "__main__":
    unittest.main()