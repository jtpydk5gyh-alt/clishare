import json
import tempfile
import threading
import unittest
from pathlib import Path

from cshcli.client import Client
from cshcli.errors import DomainError
from cshcli.server import make_server


BASE = "a" * 40
HEAD = "b" * 40
OTHER = "c" * 40


class MilestoneRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "coordinator.sqlite3"
        self.server = make_server(self.path, port=0)
        self.host, self.port = self.server.server_address[0], self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.thread_shutdown, thread)

    def thread_shutdown(self, thread):
        self.server.shutdown()
        self.server.server_close()
        thread.join(timeout=5)

    def identity(self, name):
        client = Client(self.url)
        record = client.request("POST", "/v1/users", {"name": name})
        return Client(self.url, record["token"])

    def project_for(self, client, name="acme"):
        return client.request("POST", "/v1/projects", {"name": name})["id"]

    def test_context_manifest_is_served_over_http(self):
        owner = self.identity("ana")
        project = self.project_for(owner)
        owner.request("PUT", f"/v1/projects/{project}/memory",
                      {"key": "rules/scope", "content": "one worktree per task", "expected_version": 0})
        manifest = owner.request("POST", f"/v1/projects/{project}/context",
                                 {"task_id": "task-1", "base_sha": BASE, "context_budget_bytes": 4096})
        self.assertEqual(manifest["task_id"], "task-1")
        self.assertEqual(manifest["base_sha"], BASE)
        self.assertEqual(manifest["entries"][0]["key"], "rules/scope")
        self.assertEqual(manifest["entries"][0]["version"], 1)
        self.assertEqual(manifest["budget_bytes"], 4096)
        self.assertIn("generated_at", manifest)

    def test_context_manifest_respects_a_zero_budget(self):
        owner = self.identity("ana")
        project = self.project_for(owner)
        owner.request("PUT", f"/v1/projects/{project}/memory",
                      {"key": "rules/scope", "content": "x" * 50, "expected_version": 0})
        manifest = owner.request("POST", f"/v1/projects/{project}/context",
                                 {"task_id": "t", "base_sha": BASE, "context_budget_bytes": 0})
        self.assertEqual(manifest["entries"], [])
        self.assertEqual(manifest["used_bytes"], 0)

    def test_run_reservation_lifecycle_over_http(self):
        owner = self.identity("ana")
        project = self.project_for(owner)
        reservation = owner.request("POST", f"/v1/projects/{project}/runs",
                                    {"run_id": "run-1", "authorization_generation": 1,
                                     "limits": {"max_agents": 2}})
        self.assertEqual(reservation["state"], "reserved")
        active = owner.request("GET", f"/v1/projects/{project}/runs")
        self.assertEqual(active["count"], 1)
        self.assertEqual(active["active"][0]["run_id"], "run-1")
        settled = owner.request("POST", f"/v1/projects/{project}/runs/settle",
                                {"run_id": "run-1", "attempt_id": reservation["attempt_id"],
                                 "measured_usage": {"inference_calls": 2, "cost": 0.5}})
        self.assertEqual(settled["measured_usage"]["inference_calls"], 2)
        self.assertEqual(owner.request("GET", f"/v1/projects/{project}/runs")["count"], 0)

    def test_the_concurrency_ceiling_is_enforced_over_http(self):
        owner = self.identity("ana")
        project = self.project_for(owner)
        for index in range(2):
            owner.request("POST", f"/v1/projects/{project}/runs",
                          {"run_id": f"run-{index}", "authorization_generation": 1,
                           "limits": {"max_agents": 2}})
        with self.assertRaises(DomainError) as caught:
            owner.request("POST", f"/v1/projects/{project}/runs",
                          {"run_id": "run-overflow", "authorization_generation": 1,
                           "limits": {"max_agents": 2}})
        self.assertEqual(caught.exception.code, "agent_limit_reached")

    def test_accept_patch_over_http_requires_a_live_lease(self):
        owner = self.identity("ana")
        project = self.project_for(owner)
        lease = owner.request("POST", f"/v1/projects/{project}/leases",
                              {"agent_id": "a1", "resources": ["file:src/api.py"], "ttl": 120})
        accepted = owner.request("POST", f"/v1/projects/{project}/patches/accept",
                                 {"run_id": "run-1", "authorization_generation": 1,
                                  "lease_fences": {"file:src/api.py": lease[0]["fence"]},
                                  "base_sha": BASE, "commit_sha": HEAD})
        self.assertEqual(accepted["state"], "accepted")
        listed = owner.request("GET", f"/v1/projects/{project}/patches")
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["items"][0]["commit_sha"], HEAD)

    def test_accept_patch_over_http_rejects_a_stale_fence(self):
        owner = self.identity("ana")
        project = self.project_for(owner)
        first = owner.request("POST", f"/v1/projects/{project}/leases",
                              {"agent_id": "a1", "resources": ["file:src/api.py"], "ttl": 1})
        stale = first[0]["fence"]
        import time
        time.sleep(1.2)
        second = owner.request("POST", f"/v1/projects/{project}/leases",
                               {"agent_id": "a2", "resources": ["file:src/api.py"], "ttl": 120})
        self.assertNotEqual(stale, second[0]["fence"])
        with self.assertRaises(DomainError) as caught:
            owner.request("POST", f"/v1/projects/{project}/patches/accept",
                          {"run_id": "run-1", "authorization_generation": 1,
                           "lease_fences": {"file:src/api.py": stale},
                           "base_sha": BASE, "commit_sha": HEAD})
        self.assertEqual(caught.exception.code, "fence_mismatch")

    def test_a_non_member_cannot_read_the_manifest_or_the_runs(self):
        owner = self.identity("ana")
        stranger = self.identity("mallory")
        project = self.project_for(owner)
        owner.request("PUT", f"/v1/projects/{project}/memory",
                      {"key": "rules/scope", "content": "privado", "expected_version": 0})
        with self.assertRaises(DomainError) as caught:
            stranger.request("POST", f"/v1/projects/{project}/context",
                             {"task_id": "t", "base_sha": BASE, "context_budget_bytes": 1024})
        self.assertEqual(caught.exception.status, 403)
        with self.assertRaises(DomainError):
            stranger.request("GET", f"/v1/projects/{project}/runs")

    def test_malformed_route_bodies_are_refused(self):
        owner = self.identity("ana")
        project = self.project_for(owner)
        for payload in ({}, {"base_sha": BASE}, {"task_id": "t"},
                        {"task_id": "t", "base_sha": BASE, "context_budget_bytes": -1},
                        {"task_id": "t", "base_sha": BASE, "context_budget_bytes": "4096"}):
            with self.subTest(payload=payload):
                with self.assertRaises(DomainError) as caught:
                    owner.request("POST", f"/v1/projects/{project}/context", payload)
                self.assertEqual(caught.exception.status, 400)
        for payload in ({}, {"run_id": "r", "limits": {}},
                        {"run_id": "r", "authorization_generation": "1", "limits": {}},
                        {"run_id": "r", "authorization_generation": 1, "limits": {"max_agents": 0}}):
            with self.subTest(payload=payload):
                with self.assertRaises(DomainError) as caught:
                    owner.request("POST", f"/v1/projects/{project}/runs", payload)
                self.assertEqual(caught.exception.status, 400)

    def test_the_new_routes_require_a_bearer(self):
        anonymous = Client(self.url)
        owner = self.identity("ana")
        project = self.project_for(owner)
        for method, path, payload in (
            ("POST", f"/v1/projects/{project}/context", {"task_id": "t", "base_sha": BASE}),
            ("POST", f"/v1/projects/{project}/runs", {"run_id": "r", "authorization_generation": 1}),
            ("GET", f"/v1/projects/{project}/runs", None),
            ("GET", f"/v1/projects/{project}/patches", None),
        ):
            with self.subTest(path=path):
                with self.assertRaises(DomainError) as caught:
                    anonymous.request(method, path, payload)
                self.assertEqual(caught.exception.status, 401)

    def test_events_record_the_new_transitions(self):
        owner = self.identity("ana")
        project = self.project_for(owner)
        lease = owner.request("POST", f"/v1/projects/{project}/leases",
                              {"agent_id": "a1", "resources": ["file:src/api.py"], "ttl": 120})
        owner.request("POST", f"/v1/projects/{project}/runs",
                      {"run_id": "run-1", "authorization_generation": 1, "limits": {"max_agents": 2}})
        owner.request("POST", f"/v1/projects/{project}/patches/accept",
                      {"run_id": "run-1", "authorization_generation": 1,
                       "lease_fences": {"file:src/api.py": lease[0]["fence"]},
                       "base_sha": BASE, "commit_sha": HEAD})
        events = owner.request("GET", f"/v1/projects/{project}/events")
        kinds = [event["kind"] for event in events]
        self.assertIn("policy.reserved", kinds)
        self.assertIn("patch.accepted", kinds)
        serialized = json.dumps(events)
        self.assertNotIn("Bearer", serialized)


if __name__ == "__main__":
    unittest.main()