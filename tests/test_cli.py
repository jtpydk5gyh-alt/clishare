from contextlib import redirect_stdout, redirect_stderr
from http.client import IncompleteRead
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from cshcli.cli import main
from cshcli.client import Client
from cshcli.errors import DomainError
from cshcli.server import make_server


class CliTests(unittest.TestCase):
    def invoke(self, args, env=None):
        out, err = io.StringIO(), io.StringIO()
        with patch.dict("os.environ", env or {}, clear=True), redirect_stdout(out), redirect_stderr(err):
            result = main(args)
        return result, out.getvalue(), err.getvalue()

    def test_cli_full_local_flow_and_deploy_reservation(self):
        with tempfile.TemporaryDirectory() as temp:
            server = make_server(Path(temp) / "db.sqlite", port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            env = {"CSHCLI_URL": f"http://127.0.0.1:{server.server_port}"}
            try:
                code, out, _ = self.invoke(["auth", "register", "ana"], env)
                self.assertEqual(code, 0)
                env["CSHCLI_TOKEN"] = json.loads(out)["token"]
                code, out, _ = self.invoke(["project", "create", "collab"], env)
                self.assertEqual(code, 0)
                project = json.loads(out)["id"]
                code, out, _ = self.invoke(["memory", "put", project, "decision", "--content", "SQLite", "--expected-version", "0"], env)
                self.assertEqual(code, 0)
                code, _, err = self.invoke(["memory", "put", project, "decision", "--content", "conflict", "--expected-version", "0"], env)
                self.assertEqual(code, 1)
                self.assertIn("error", json.loads(err))
                code, out, _ = self.invoke(["deploy", "reserve", project, "staging", "--agent", "ana-1"], env)
                self.assertEqual(code, 0)
                lease = json.loads(out)[0]
                self.assertEqual(lease["resource"], "deploy:staging")
                code, _, _ = self.invoke(["lease", "release", project, str(lease["id"]), str(lease["fence"])], env)
                self.assertEqual(code, 0)
            finally:
                server.shutdown()
                thread.join()
                server.server_close()

    def test_missing_collaboration_token_is_safe(self):
        code, _, err = self.invoke(["project", "list"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(err)["error"]["code"], "authentication_required")

    def test_provider_commands_delegate_without_coordinator(self):
        with patch("cshcli.cli.providers.chat", return_value="answer") as chat:
            code, out, _ = self.invoke(["chat", "--provider", "openai", "--model", "example-model", "hello"])
            self.assertEqual((code, out.strip()), (0, "answer"))
            chat.assert_called_once_with("openai", "example-model", "hello")

    def test_client_rejects_insecure_remote_and_embedded_secrets(self):
        for url in ["http://remote.example", "https://user:secret@remote.example", "file:///tmp/foo", "https://x.example/path"]:
            with self.subTest(url=url), self.assertRaises(DomainError):
                Client(url)

    def test_client_handles_invalid_response_bodies_over_http(self):
        class BrokenResponse(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(500 if self.path.startswith("/error-") else 200)
                if self.path.endswith("chunked"):
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    self.wfile.write(b'10\r\n{"data":1}\r\n')
                else:
                    body = b'{"data":1}' if self.path == "/length" else b'{"data":' + b"[" * 50000 + b"0" + b"]" * 50000 + b"}"
                    self.send_header("Content-Length", str(len(body) + (10 if self.path == "/length" else 0)))
                    self.end_headers()
                    self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), BrokenResponse)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        client = Client(f"http://127.0.0.1:{server.server_port}")
        try:
            for path in ("/chunked", "/length", "/deep", "/error-chunked", "/error-deep"):
                with self.subTest(path=path):
                    with self.assertRaises(DomainError) as caught:
                        client.request("GET", path)
                    expected = (500, "http_error") if path == "/error-deep" else (502, "invalid_response")
                    self.assertEqual((caught.exception.status, caught.exception.code), expected)
        finally:
            server.shutdown()
            thread.join(5)
            server.server_close()

    def test_cli_handles_failed_success_and_error_body_reads(self):
        for response_status, failure, expected in (
            (200, TimeoutError(), "coordinator_unavailable"),
            (200, IncompleteRead(b"partial"), "invalid_response"),
            (503, TimeoutError(), "coordinator_unavailable"),
            (503, IncompleteRead(b"partial"), "invalid_response"),
        ):
            with self.subTest(status=response_status, failure=type(failure).__name__):
                if response_status == 200:
                    response = io.BytesIO()
                    effect = {"return_value": response}
                else:
                    response = HTTPError("http://127.0.0.1/", response_status, "unavailable", {}, io.BytesIO())
                    effect = {"side_effect": response}
                with patch.object(response, "read", side_effect=failure), patch("urllib.request.OpenerDirector.open", **effect):
                    code, _, errors = self.invoke(
                        ["project", "list"],
                        {"CSHCLI_TOKEN": "fixture", "CSHCLI_URL": "http://127.0.0.1:8765"})
                self.assertEqual(code, 1)
                self.assertEqual(json.loads(errors)["error"]["code"], expected)

class MilestoneCommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.server = make_server(Path(self.temp.name) / "db.sqlite", port=0)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(thread.join, 5)
        self.addCleanup(self.server.shutdown)
        self.env = {"CSHCLI_URL": f"http://127.0.0.1:{self.server.server_port}"}
        code, out, errors = self.invoke(["auth", "register", "ana"], self.env)
        self.assertEqual(code, 0, errors)
        self.env = dict(self.env, CSHCLI_TOKEN=json.loads(out)["token"])
        code, out, errors = self.invoke(["project", "create", "acme"], self.env)
        self.assertEqual(code, 0, errors)
        self.project = json.loads(out)["id"]

    def invoke(self, arguments, env=None):
        out, err = io.StringIO(), io.StringIO()
        with patch.dict("os.environ", env if env is not None else self.env, clear=True):
            with redirect_stdout(out), redirect_stderr(err):
                result = main(arguments)
        return result, out.getvalue(), err.getvalue()

    def test_context_command_prints_a_bounded_manifest(self):
        code, output, errors = self.invoke(
            ["context", self.project, "--task", "task-1", "--base-sha", "a" * 40, "--budget", "4096"])
        self.assertEqual(code, 0, errors)
        manifest = json.loads(output)
        self.assertEqual(manifest["task_id"], "task-1")
        self.assertEqual(manifest["budget_bytes"], 4096)
        self.assertEqual(manifest["base_sha"], "a" * 40)

    def test_run_reserve_list_and_settle(self):
        code, output, errors = self.invoke(
            ["run", "reserve", self.project, "run-1", "--max-agents", "2"])
        self.assertEqual(code, 0, errors)
        reservation = json.loads(output)
        self.assertEqual(reservation["state"], "reserved")
        code, output, errors = self.invoke(["run", "list", self.project])
        self.assertEqual(code, 0, errors)
        self.assertEqual(json.loads(output)["count"], 1)
        code, output, errors = self.invoke(
            ["run", "settle", self.project, "run-1", reservation["attempt_id"],
             "--inference-calls", "3", "--cost", "0.25"])
        self.assertEqual(code, 0, errors)
        settlement = json.loads(output)
        self.assertEqual(settlement["measured_usage"]["inference_calls"], 3)
        self.assertEqual(settlement["unknown_usage"], ["capture_bytes", "runtime_seconds"])

    def test_settling_without_a_cost_records_it_as_unknown(self):
        _, output, _ = self.invoke(["run", "reserve", self.project, "run-u", "--allow-unknown-cost"])
        reservation = json.loads(output)
        code, output, errors = self.invoke(
            ["run", "settle", self.project, "run-u", reservation["attempt_id"]])
        self.assertEqual(code, 0, errors)
        self.assertEqual(json.loads(output)["unknown_usage"], ["capture_bytes", "cost", "runtime_seconds"])

    def test_run_refuses_to_exceed_the_ceiling(self):
        self.invoke(["run", "reserve", self.project, "a", "--max-agents", "1"])
        code, _, errors = self.invoke(["run", "reserve", self.project, "b", "--max-agents", "1"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(errors)["error"]["code"], "agent_limit_reached")

    def test_patch_accept_and_list(self):
        lease = json.loads(self.invoke(
            ["lease", "acquire", self.project, "a1", "file:src/api.py", "--ttl", "120"])[1])
        code, output, errors = self.invoke([
            "patch", "accept", self.project, "run-1",
            "--base-sha", "a" * 40, "--commit-sha", "b" * 40,
            "--lease", "file:src/api.py=" + str(lease[0]["fence"])])
        self.assertEqual(code, 0, errors)
        self.assertEqual(json.loads(output)["state"], "accepted")
        code, output, errors = self.invoke(["patch", "list", self.project])
        self.assertEqual(code, 0, errors)
        self.assertEqual(json.loads(output)["count"], 1)

    def test_patch_rejects_a_malformed_lease_argument(self):
        code, _, errors = self.invoke([
            "patch", "accept", self.project, "run-1",
            "--base-sha", "a" * 40, "--commit-sha", "b" * 40, "--lease", "no-fence"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(errors)["error"]["code"], "invalid_lease_fence")

    def test_patch_accept_rejects_a_stale_fence_over_the_cli(self):
        lease = json.loads(self.invoke(
            ["lease", "acquire", self.project, "a1", "file:src/api.py", "--ttl", "1"])[1])
        time.sleep(1.2)
        self.invoke(["lease", "acquire", self.project, "a2", "file:src/api.py", "--ttl", "120"])
        code, _, errors = self.invoke([
            "patch", "accept", self.project, "run-1",
            "--base-sha", "a" * 40, "--commit-sha", "b" * 40,
            "--lease", "file:src/api.py=" + str(lease[0]["fence"])])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(errors)["error"]["code"], "fence_mismatch")


if __name__ == "__main__":
    unittest.main()
