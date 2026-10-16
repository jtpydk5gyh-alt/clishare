import http.client
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from threading import Thread
from unittest import mock

from cshcli.server import make_server


class QueueRouteTests(unittest.TestCase):
    def setUp(self):
        environment = mock.patch.dict(os.environ, {}, clear=False)
        environment.start()
        self.addCleanup(environment.stop)
        os.environ.pop("CSHCLI_REPOSITORY", None)
        os.environ.pop("CSHCLI_INTEGRATION_CHECK", None)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repository = self.root / "repo"
        self.repository.mkdir()
        self._git("init", "-q")
        self._git("config", "user.email", "queue@example.invalid")
        self._git("config", "user.name", "Queue")
        (self.repository / "app.py").write_text("value = 1\n", encoding="utf-8")
        self._git("add", ".")
        self._git("commit", "-qm", "base")
        self.base = self._git("rev-parse", "HEAD").strip()
        self._git("branch", "integration", self.base)

        self.coordinator = make_server(self.root / "c.sqlite3", "127.0.0.1", 0)
        self.port = self.coordinator.server_address[1]
        thread = Thread(target=self.coordinator.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.coordinator.server_close)
        self.addCleanup(thread.join, 5)
        self.addCleanup(self.coordinator.shutdown)

        _, created = self._call("POST", "/v1/users", {"name": "ana"})
        self.token = created["data"]["token"]
        _, project = self._call("POST", "/v1/projects", {"name": "demo"}, self.token)
        self.project = project["data"]["id"]

    def _git(self, *arguments):
        return subprocess.run(["git", *arguments], cwd=self.repository, check=True,
                              capture_output=True, text=True).stdout

    def _call(self, method, path, body=None, token=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        try:
            headers = {"Accept": "application/json"}
            data = None
            if body is not None:
                headers["Content-Type"] = "application/json"
                data = json.dumps(body).encode()
            if token:
                headers["Authorization"] = "Bearer " + token
            connection.request(method, path, data, headers)
            answer = connection.getresponse()
            raw = answer.read()
            return answer.status, (json.loads(raw) if raw else {})
        finally:
            connection.close()

    def new_commit(self, content, message):
        (self.repository / "app.py").write_text(content, encoding="utf-8")
        self._git("add", "app.py")
        self._git("commit", "-qm", message)
        return self._git("rev-parse", "HEAD").strip()

    def test_queueing_without_a_repository_is_refused(self):
        os.environ.pop("CSHCLI_REPOSITORY", None)
        status, payload = self._call("POST", f"/v1/projects/{self.project}/queue",
                                     {"commit_sha": self.base, "base_sha": self.base},
                                     self.token)
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "repository_not_configured")

    def test_a_commit_is_queued_and_listed(self):
        sha = self.new_commit("value = 2\n", "change")
        status, payload = self._call("POST", f"/v1/projects/{self.project}/queue",
                                     {"commit_sha": sha, "base_sha": self.base,
                                      "repository": str(self.repository)}, self.token)
        self.assertEqual(status, 201)
        entry = payload["data"]
        self.assertEqual(entry["state"], "queued")
        status, payload = self._call("GET", f"/v1/projects/{self.project}/queue", None,
                                     self.token)
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["data"]["entries"]), 1)

    def test_the_same_commit_is_queued_once(self):
        sha = self.new_commit("value = 3\n", "change")
        body = {"commit_sha": sha, "base_sha": self.base,
                "repository": str(self.repository)}
        first = self._call("POST", f"/v1/projects/{self.project}/queue", body, self.token)
        second = self._call("POST", f"/v1/projects/{self.project}/queue", body, self.token)
        self.assertEqual(first[0], 201)
        self.assertEqual(first[1]["data"]["id"], second[1]["data"]["id"])

    def test_a_commit_that_does_not_exist_is_refused(self):
        status, payload = self._call("POST", f"/v1/projects/{self.project}/queue",
                                     {"commit_sha": "f" * 40, "base_sha": self.base,
                                      "repository": str(self.repository)}, self.token)
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "commit_not_found")

    def test_processing_advances_the_integration_branch(self):
        sha = self.new_commit("value = 4\n", "change")
        self._call("POST", f"/v1/projects/{self.project}/queue",
                   {"commit_sha": sha, "base_sha": self.base,
                    "repository": str(self.repository)}, self.token)
        command = json.dumps([sys.executable, "-c", "raise SystemExit(0)"])
        with mock.patch.dict(os.environ, {"CSHCLI_INTEGRATION_CHECK": command}):
            status, payload = self._call(
                "POST", f"/v1/projects/{self.project}/queue/next",
                {"repository": str(self.repository), "branch": "integration"}, self.token)
        self.assertEqual(status, 200)
        self.assertEqual(payload["data"]["state"], "merged")
        head = self._git("rev-parse", "integration").strip()
        self.assertNotEqual(head, self.base)

    def test_processing_without_checks_is_refused(self):
        sha = self.new_commit("value = 4\n", "change")
        self._call("POST", f"/v1/projects/{self.project}/queue",
                   {"commit_sha": sha, "base_sha": self.base,
                    "repository": str(self.repository)}, self.token)
        status, payload = self._call(
            "POST", f"/v1/projects/{self.project}/queue/next",
            {"repository": str(self.repository)}, self.token)
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "checks_not_configured")
        self.assertEqual(self._git("rev-parse", "integration").strip(), self.base)

    def test_an_empty_queue_reports_idle(self):
        status, payload = self._call("POST", f"/v1/projects/{self.project}/queue/next",
                                     {"repository": str(self.repository)}, self.token)
        self.assertEqual(status, 200)
        self.assertEqual(payload["data"]["state"], "idle")

    def test_a_queue_entry_can_be_read_by_id(self):
        sha = self.new_commit("value = 5\n", "change")
        created = self._call("POST", f"/v1/projects/{self.project}/queue",
                             {"commit_sha": sha, "base_sha": self.base,
                              "repository": str(self.repository)}, self.token)[1]["data"]
        status, payload = self._call(
            "GET", f"/v1/projects/{self.project}/queue/{created['id']}", None, self.token)
        self.assertEqual(status, 200)
        self.assertEqual(payload["data"]["id"], created["id"])

    def test_a_queue_entry_cannot_be_read_through_another_project(self):
        sha = self.new_commit("value = 6\n", "change")
        created = self._call("POST", f"/v1/projects/{self.project}/queue",
                             {"commit_sha": sha, "base_sha": self.base,
                              "repository": str(self.repository)}, self.token)[1]["data"]
        _, second = self._call("POST", "/v1/projects", {"name": "other"}, self.token)
        status, payload = self._call(
            "GET", f"/v1/projects/{second['data']['id']}/queue/{created['id']}",
            None, self.token)
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "queue_not_found")

    def test_only_the_owner_can_override_the_repository(self):
        _, invited = self._call("POST", f"/v1/projects/{self.project}/invites", {},
                                self.token)
        _, member_created = self._call("POST", "/v1/users", {"name": "luis"})
        member = member_created["data"]["token"]
        self._call("POST", "/v1/invites/accept",
                   {"token": invited["data"]["token"]}, member)
        sha = self.new_commit("value = 7\n", "change")
        status, payload = self._call(
            "POST", f"/v1/projects/{self.project}/queue",
            {"commit_sha": sha, "base_sha": self.base,
             "repository": str(self.repository)}, member)
        self.assertEqual(status, 403)
        self.assertEqual(payload["error"]["code"], "repository_override_forbidden")

    def test_a_non_member_cannot_queue(self):
        _, other_created = self._call("POST", "/v1/users", {"name": "luis"})
        other = other_created["data"]["token"]
        status, _ = self._call("POST", f"/v1/projects/{self.project}/queue",
                               {"commit_sha": self.base, "base_sha": self.base,
                                "repository": str(self.repository)}, other)
        self.assertEqual(status, 403)

    def test_the_repository_can_come_from_the_environment(self):
        os.environ["CSHCLI_REPOSITORY"] = str(self.repository)
        self.addCleanup(os.environ.pop, "CSHCLI_REPOSITORY", None)
        sha = self.new_commit("value = 6\n", "change")
        status, payload = self._call("POST", f"/v1/projects/{self.project}/queue",
                                     {"commit_sha": sha, "base_sha": self.base}, self.token)
        self.assertEqual(status, 201)
        self.assertEqual(payload["data"]["state"], "queued")

    def test_an_invalid_check_command_only_blocks_processing(self):
        os.environ["CSHCLI_INTEGRATION_CHECK"] = "not-json"
        status, payload = self._call(
            "GET", f"/v1/projects/{self.project}/queue", None, self.token)
        self.assertEqual(status, 200)
        self.assertEqual(payload["data"]["entries"], [])
        status, payload = self._call(
            "POST", f"/v1/projects/{self.project}/queue/next",
            {"repository": str(self.repository)}, self.token)
        self.assertEqual(status, 500)
        self.assertEqual(payload["error"]["code"], "integration_check_invalid")

    def test_a_malformed_sha_is_refused(self):
        for value in ("short", "Z" * 40, 42, ""):
            with self.subTest(value=value):
                status, _ = self._call("POST", f"/v1/projects/{self.project}/queue",
                                       {"commit_sha": value, "base_sha": self.base,
                                        "repository": str(self.repository)}, self.token)
                self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()