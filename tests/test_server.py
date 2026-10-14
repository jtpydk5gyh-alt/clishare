import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from cshcli.server import make_server


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.server = make_server(Path(self.temp.name) / "test.db", port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()
        self.temp.cleanup()

    def request(self, method, path, data=None, token=None, headers=None):
        headers = dict(headers or {})
        if token:
            headers["Authorization"] = "Bearer " + token
        if data is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(data).encode()
        request = Request(self.url + path, data=data, headers=headers, method=method)
        try:
            response = urlopen(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def register(self, name):
        status, body = self.request("POST", "/v1/users", {"name": name})
        self.assertEqual(status, 201)
        return body["data"]["token"]

    def test_two_people_share_memory_but_cannot_lease_same_scope(self):
        owner = self.register("owner")
        member = self.register("member")
        outsider = self.register("outsider")
        status, body = self.request("POST", "/v1/projects", {"name": "demo"}, owner)
        self.assertEqual(status, 201)
        project = body["data"]["id"]
        prefix = f"/v1/projects/{project}"
        _, invite = self.request("POST", prefix + "/invites", {}, owner)
        self.assertEqual(self.request("POST", "/v1/invites/accept", {"token": invite["data"]["token"]}, member)[0], 200)
        self.assertEqual(self.request("GET", prefix + "/memory", token=outsider)[0], 403)
        memory = {"key": "architecture", "content": "one worktree per task", "expected_version": 0}
        self.assertEqual(self.request("PUT", prefix + "/memory", memory, owner)[0], 200)
        _, shared = self.request("GET", prefix + "/memory", token=member)
        self.assertEqual(shared["data"]["items"][0]["version"], 1)
        self.assertEqual(self.request("PUT", prefix + "/memory", memory, member)[0], 409)
        status, lease = self.request("POST", prefix + "/leases", {"agent_id": "owner-1", "resources": ["file:src"]}, owner)
        self.assertEqual(status, 201)
        self.assertEqual(self.request("POST", prefix + "/leases", {"agent_id": "member-1", "resources": ["file:src/app.py"]}, member)[0], 409)
        record = lease["data"][0]
        path = prefix + "/leases/" + str(record["id"])
        self.assertEqual(self.request("POST", path + "/renew", {"fence": record["fence"]}, member)[0], 403)
        self.assertEqual(self.request("DELETE", path, {"fence": record["fence"]}, owner)[0], 200)
        self.assertEqual(self.request("POST", prefix + "/leases", {"agent_id": "member-1", "resources": ["file:src/app.py"]}, member)[0], 201)

    def test_authentication_and_browser_requests_are_rejected(self):
        self.assertEqual(self.request("GET", "/v1/projects")[0], 401)
        self.assertEqual(self.request("GET", "/v1/projects", token="invalid")[0], 401)
        self.assertEqual(self.request("POST", "/v1/users", {"name": "x"}, headers={"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.request("GET", "/health", headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.request("GET", "/health", headers={"Host": "localhost:invalid"})[0], 403)
        self.assertEqual(self.request("GET", "/health")[1]["data"]["status"], "ok")

    def test_bad_json_and_missing_fields_have_safe_errors(self):
        req = Request(self.url + "/v1/users", data=b"{", headers={"Content-Type": "application/json"}, method="POST")
        with self.assertRaises(HTTPError) as result:
            urlopen(req, timeout=5)
        self.assertEqual(result.exception.code, 400)
        result.exception.close()
        self.assertEqual(self.request("POST", "/v1/users", ["not an object"])[0], 400)
        self.assertEqual(self.request("POST", "/v1/users", {})[0], 400)
        self.assertEqual(self.request("POST", "/v1/users", {"name": None})[0], 400)

    def test_server_refuses_public_bind(self):
        with self.assertRaises(ValueError):
            make_server(Path(self.temp.name) / "public.db", host="0.0.0.0", port=0)

    def test_large_memory_pages_can_be_read_by_the_cli_client(self):
        from cshcli.client import Client

        token = self.register("large-memory")
        client = Client(self.url, token)
        project = client.request("POST", "/v1/projects", {"name": "large"})["id"]
        path = f"/v1/projects/{project}/memory"
        for key in ["a", "b", "c", "d"]:
            client.request("PUT", path, {"key": key, "content": "x" * 262144, "expected_version": 0})
        page = client.request("GET", path)
        self.assertEqual(len(page["items"]), 4)
        self.assertIsNone(page["next_cursor"])
        page = client.request("GET", path + "?limit=2")
        self.assertEqual([item["key"] for item in page["items"]], ["a", "b"])
        self.assertEqual(page["next_cursor"], "b")
        page = client.request("GET", path + "?limit=2&after=b")
        self.assertEqual([item["key"] for item in page["items"]], ["c", "d"])
        self.assertIsNone(page["next_cursor"])
        for query in ["limit=0", "limit=abc", "limit=11", "limit=1&limit=2", "unknown=1"]:
            self.assertEqual(self.request("GET", path + "?" + query, token=token)[0], 400)
