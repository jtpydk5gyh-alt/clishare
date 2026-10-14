from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from clishare.cli import main
from clishare.client import Client
from clishare.errors import DomainError
from clishare.server import make_server


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
            env = {"CLISHARE_URL": f"http://127.0.0.1:{server.server_port}"}
            try:
                code, out, _ = self.invoke(["auth", "register", "ana"], env)
                self.assertEqual(code, 0)
                env["CLISHARE_TOKEN"] = json.loads(out)["token"]
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
                server.server_close()
                thread.join()

    def test_missing_collaboration_token_is_safe(self):
        code, _, err = self.invoke(["project", "list"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(err)["error"]["code"], "authentication_required")

    def test_provider_commands_delegate_without_coordinator(self):
        with patch("clishare.cli.providers.chat", return_value="answer") as chat:
            code, out, _ = self.invoke(["chat", "--provider", "openai", "--model", "example-model", "hello"])
            self.assertEqual((code, out.strip()), (0, "answer"))
            chat.assert_called_once_with("openai", "example-model", "hello")

    def test_client_rejects_insecure_remote_and_embedded_secrets(self):
        for url in ["http://remote.example", "https://user:secret@remote.example", "file:///tmp/foo", "https://x.example/path"]:
            with self.subTest(url=url), self.assertRaises(DomainError):
                Client(url)
