import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from cshcli.errors import DomainError
from cshcli.policy import Policy
from cshcli.store import Store


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "policy.sqlite3"
        self.now = 20_000.0
        self.store = Store(self.path, clock=lambda: self.now)
        self.policy = Policy(self.store, clock=lambda: self.now)
        self.owner = self.store.register_user("policy-owner")
        self.viewer = self.store.register_user("policy-viewer")
        self.project = self.store.create_project(self.owner["id"], "metered")
        invitation = self.store.create_invite(self.owner["id"], self.project["id"], "viewer")
        self.store.accept_invite(self.viewer["id"], invitation["token"])

    def assert_domain(self, status, callback, code=None):
        with self.assertRaises(DomainError) as caught:
            callback()
        self.assertEqual(caught.exception.status, status)
        if code is not None:
            self.assertEqual(caught.exception.code, code)

    def reserve(self, limits=None, run_id="run-1", generation=1):
        return self.policy.reserve_run(
            self.owner["id"], self.project["id"], run_id, generation, limits or {},
        )

    def settle(self, reservation, usage):
        return self.policy.finish_run(reservation["run_id"], reservation["attempt_id"], usage)

    def event_kinds(self):
        return [
            event["kind"] for event in self.store.list_events(self.owner["id"], self.project["id"])
            if event["kind"].startswith("policy.")
        ]

    def reservation_rows(self, run_id):
        with closing(sqlite3.connect(self.path)) as connection:
            connection.row_factory = sqlite3.Row
            return connection.execute(
                "SELECT * FROM run_reservations WHERE run_id = ? ORDER BY attempt_id", (run_id,),
            ).fetchall()

    def settlement_row(self, run_id, attempt_id):
        with closing(sqlite3.connect(self.path)) as connection:
            connection.row_factory = sqlite3.Row
            return connection.execute(
                "SELECT * FROM run_settlements WHERE run_id = ? AND attempt_id = ?", (run_id, attempt_id),
            ).fetchone()

    def test_reserve_run_is_idempotent_for_same_run_and_attempt(self):
        first = self.reserve({"max_agents": 5, "max_inference_calls": 20})
        again = self.reserve({"max_inference_calls": 20, "max_agents": 5})
        self.assertEqual(first, again)
        self.assertEqual(first["state"], "reserved")
        self.assertEqual(first["limits"], {"max_agents": 5, "max_inference_calls": 20})
        self.assertEqual(len(self.reservation_rows("run-1")), 1)
        self.assertEqual(self.event_kinds(), ["policy.reserved"])
        reserved = next(
            event for event in self.store.list_events(self.owner["id"], self.project["id"])
            if event["kind"] == "policy.reserved" and event["data"]["run_id"] == "run-1"
        )
        self.assertEqual(reserved["data"]["limits"], {"max_agents": 5, "max_inference_calls": 20})
        self.assertEqual(reserved["data"]["attempt_id"], first["attempt_id"])
        self.assertEqual(reserved["data"]["authorization_generation"], 1)
        other = self.reserve(run_id="run-2")
        self.assertNotEqual(other["attempt_id"], first["attempt_id"])
        self.assert_domain(409, lambda: self.reserve({"max_agents": 6}, run_id="run-1"), "reservation_mismatch")
        self.assert_domain(409, lambda: self.reserve(generation=2, run_id="run-1"), "reservation_mismatch")

    def test_reserve_run_rejects_generation_mismatch(self):
        self.assertEqual(self.store.authorization_generation(self.owner["id"], self.project["id"], "agent"), 1)
        self.assertEqual(self.store.authorization_generation(self.owner["id"], self.project["id"]), 1)
        self.assert_domain(409, lambda: self.reserve(generation=0), "generation_stale")
        self.assert_domain(409, lambda: self.reserve(generation=-3), "generation_stale")
        self.assert_domain(400, lambda: self.reserve(generation="1"), "invalid_input")
        self.assert_domain(400, lambda: self.reserve(generation=True), "invalid_input")
        self.assertEqual(self.event_kinds(), [])
        self.assertEqual(self.reservation_rows("run-1"), [])
        self.assert_domain(403, lambda: self.policy.reserve_run(
            self.viewer["id"], self.project["id"], "run-viewer", 1, {}), "forbidden")
        self.assert_domain(404, lambda: self.policy.reserve_run(
            self.owner["id"], "missing-project", "run-ghost", 1, {}), "project_not_found")

    def test_reserve_run_rejects_invalid_limits(self):
        for limits in (
            None, [], "limits", 11, {"max_agents": 0}, {"max_agents": -1}, {"max_agents": True},
            {"max_agents": 1.0}, {"max_agents": "11"}, {"max_agents": None},
            {"max_inference_calls": 0}, {"max_inference_calls": "20"}, {"max_capture_bytes": -1},
            {"max_capture_bytes": 1.5}, {"max_runtime_seconds": 0}, {"max_runtime_seconds": True},
            {"allow_unknown_cost": "yes"}, {"allow_unknown_cost": 1}, {"allow_unknown_cost": None},
        ):
            with self.subTest(limits=limits):
                self.assert_domain(
                    400, lambda: self.policy.reserve_run(
                        self.owner["id"], self.project["id"], "run-invalid", 1, limits), "invalid_limits",
                )
        self.assertEqual(self.event_kinds(), [])
        self.assertEqual(self.reservation_rows("run-invalid"), [])
        self.assert_domain(400, lambda: self.reserve(run_id=""), "invalid_input")
        self.assert_domain(400, lambda: self.reserve(run_id="bad\ud800"), "invalid_input")

    def test_reserve_run_defaults_max_agents_to_eleven(self):
        defaulted = self.reserve(run_id="run-default")
        self.assertEqual(defaulted["limits"], {"max_agents": 11})
        capped = self.reserve({"max_inference_calls": 20}, run_id="run-capped")
        self.assertEqual(capped["limits"], {"max_agents": 11, "max_inference_calls": 20})
        explicit = self.reserve({"max_agents": 10}, run_id="run-explicit")
        self.assertEqual(explicit["limits"], {"max_agents": 10})
        stored = json.loads(self.reservation_rows("run-default")[0]["limits_json"])
        self.assertEqual(stored, {"max_agents": 11})

    def test_finish_run_records_measured_usage_and_unknown_fields(self):
        reservation = self.reserve({"max_agents": 5})
        self.now += 30
        settlement = self.settle(reservation, {
            "inference_calls": 4, "capture_bytes": 2048, "runtime_seconds": 28.5,
            "cost": 0.42, "output_tokens": None,
        })
        self.assertEqual(settlement["settled_at"], self.now)
        self.assertEqual(settlement["authorization_generation"], 1)
        self.assertEqual(settlement["measured_usage"]["inference_calls"], 4)
        self.assertEqual(settlement["unknown_usage"], ["output_tokens"])
        self.assertEqual(self.event_kinds(), ["policy.settled", "policy.reserved"])
        event = self.store.list_events(self.owner["id"], self.project["id"])[0]
        self.assertEqual(event["kind"], "policy.settled")
        self.assertEqual(event["data"]["unknown_usage"], ["output_tokens"])
        self.assertEqual(event["data"]["run_id"], reservation["run_id"])
        self.assertEqual(event["data"]["attempt_id"], reservation["attempt_id"])
        row = self.settlement_row(reservation["run_id"], reservation["attempt_id"])
        self.assertEqual(json.loads(row["measured_usage_json"])["cost"], 0.42)
        self.assertEqual(json.loads(row["unknown_usage_json"]), ["output_tokens"])
        self.assertEqual(self.reservation_rows("run-1")[0]["state"], "settled")

    def test_finish_run_rejects_unknown_cost_when_policy_forbids(self):
        reservation = self.reserve({"allow_unknown_cost": False})
        for cost in (None, "unknown"):
            with self.subTest(cost=cost):
                self.assert_domain(
                    409, lambda: self.settle(reservation, {"inference_calls": 2, "cost": cost}), "cost_unknown",
                )
        defaulted = self.reserve(run_id="run-default-policy")
        self.assert_domain(
            409, lambda: self.settle(defaulted, {"inference_calls": 2, "cost": None}), "cost_unknown",
        )
        self.assertEqual(self.event_kinds(), ["policy.reserved", "policy.reserved"])
        self.assertIsNone(self.settlement_row(reservation["run_id"], reservation["attempt_id"]))
        self.assertEqual(self.settle(reservation, {"inference_calls": 2, "cost": 1.5})["measured_usage"]["cost"], 1.5)

    def test_finish_run_accepts_unknown_cost_when_policy_allows(self):
        reservation = self.reserve({"allow_unknown_cost": True})
        settlement = self.settle(reservation, {"inference_calls": 3, "cost": "unknown"})
        self.assertEqual(settlement["unknown_usage"], ["cost"])
        self.assertEqual(settlement["measured_usage"]["cost"], "unknown")
        self.assertEqual(self.reservation_rows("run-1")[0]["state"], "settled")

    def test_finish_run_rejects_missing_or_double_settlement(self):
        self.assert_domain(
            404, lambda: self.policy.finish_run("missing-run", "attempt-1", {"cost": 1.0}), "reservation_not_found",
        )
        self.assert_domain(404, lambda: self.policy.finish_run("run-1", "attempt-1", {}), "reservation_not_found")
        reservation = self.reserve()
        self.assert_domain(
            404, lambda: self.policy.finish_run(reservation["run_id"], "other-attempt", {}), "reservation_not_found",
        )
        self.assertEqual(self.event_kinds(), ["policy.reserved"])
        first = self.settle(reservation, {"cost": 1.0})
        self.assert_domain(409, lambda: self.settle(reservation, {"cost": 2.0}), "already_settled")
        replay = self.reserve()
        self.assertEqual(replay["attempt_id"], first["attempt_id"])
        self.assertEqual(replay["state"], "settled")
        self.assertEqual(len(self.reservation_rows("run-1")), 1)
        self.assert_domain(400, lambda: self.policy.finish_run(reservation["run_id"], reservation["attempt_id"], []), "invalid_input")
        self.assertEqual(self.event_kinds().count("policy.settled"), 1)
        self.assertEqual(json.loads(self.settlement_row(
            reservation["run_id"], reservation["attempt_id"])["measured_usage_json"]), {"cost": 1.0})

    def test_finish_run_never_zeroes_unknown_usage(self):
        reservation = self.reserve({"allow_unknown_cost": True, "max_inference_calls": 20})
        settlement = self.settle(reservation, {
            "inference_calls": 2, "capture_bytes": None, "runtime_seconds": "unknown", "cost": None,
        })
        self.assertEqual(settlement["unknown_usage"], ["capture_bytes", "cost", "runtime_seconds"])
        self.assertEqual(settlement["measured_usage"]["inference_calls"], 2)
        stored = json.loads(self.settlement_row(
            reservation["run_id"], reservation["attempt_id"])["measured_usage_json"])
        self.assertIsNone(stored["capture_bytes"])
        self.assertEqual(stored["runtime_seconds"], "unknown")
        self.assertNotEqual(stored["capture_bytes"], 0)
        self.assertNotEqual(stored["runtime_seconds"], 0)
        self.assertEqual(self.store.list_events(
            self.owner["id"], self.project["id"])[0]["data"]["measured_usage"]["capture_bytes"], None)
