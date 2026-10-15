import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from cshcli import cli
from cshcli.errors import DomainError


class CliKeyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = str(Path(self.temp.name))
        patcher = mock.patch.dict(os.environ, {"CSHCLI_HOME": self.home})
        patcher.start()
        self.addCleanup(patcher.stop)
        for variable in ("CSHCLI_TOKEN", "CSHCLI_URL", "OPENAI_API_KEY",
                         "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "MINIMAX_API_KEY"):
            os.environ.pop(variable, None)

    def run_cli(self, *arguments, **keywords):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(list(arguments))
        return code, out.getvalue(), err.getvalue()

    def test_a_key_is_stored_without_echoing_it(self):
        with mock.patch("cshcli.cli.getpass.getpass", return_value="sk-example-value") as prompt:
            code, out, err = self.run_cli("key", "set", "openai")
        self.assertEqual(code, 0)
        self.assertIn("configured", out)
        self.assertNotIn("sk-example-value", out)
        self.assertNotIn("sk-example-value", err)
        self.assertIn("no se muestra", prompt.call_args[0][0])

    def test_an_empty_key_stores_nothing(self):
        with mock.patch("cshcli.cli.getpass.getpass", return_value="   "):
            code, out, err = self.run_cli("key", "set", "openai")
        self.assertEqual(code, 1)
        code, out, err = self.run_cli("key", "show", "openai")
        self.assertEqual(code, 1)
        self.assertIn("configured", out)

    def test_show_reports_whether_a_key_exists_and_never_its_value(self):
        with mock.patch("cshcli.cli.getpass.getpass", return_value="sk-secret-here"):
            self.run_cli("key", "set", "anthropic")
        code, out, _ = self.run_cli("key", "show", "anthropic")
        self.assertEqual(code, 0)
        self.assertNotIn("sk-secret-here", out)
        self.assertIn('"source": "keyring"', out)

    def test_list_covers_every_provider_and_leaks_nothing(self):
        with mock.patch("cshcli.cli.getpass.getpass", return_value="sk-secret-here"):
            self.run_cli("key", "set", "openai")
        code, out, _ = self.run_cli("key", "list")
        self.assertEqual(code, 0)
        self.assertNotIn("sk-secret-here", out)
        reported = {item["provider"] for item in json.loads(out)}
        self.assertIn("openai", reported)
        self.assertIn("anthropic", reported)
        self.assertIn("minimax", reported)

    def test_dropping_removes_the_key(self):
        with mock.patch("cshcli.cli.getpass.getpass", return_value="sk-secret-here"):
            self.run_cli("key", "set", "openai")
        code, _, _ = self.run_cli("key", "drop", "openai")
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli("key", "drop", "openai")
        self.assertEqual(code, 1)

    def test_start_without_a_coordinator_points_at_serve(self):
        with mock.patch.object(cli, "Client") as client:
            client.return_value.request.side_effect = DomainError(
                503, "coordinator_unavailable", "No se pudo conectar.")
            code, out, _ = self.run_cli("start")
        self.assertEqual(code, 0)
        self.assertIn("cshcli serve", out)
        self.assertIn("not running", out)

    def test_start_without_an_identity_asks_for_a_name(self):
        with mock.patch.object(cli, "Client") as client:
            client.return_value.request.side_effect = DomainError(
                401, "invalid_token", "No.")
            code, out, err = self.run_cli("start")
        self.assertEqual(code, 1)
        self.assertIn("invalid_token", err)

    def test_start_with_a_coordinator_but_no_project_asks_for_a_project(self):
        with mock.patch.object(cli, "Client") as client:
            client.return_value.request.return_value = {"projects": []}
            code, out, _ = self.run_cli("start")
        self.assertEqual(code, 0)
        self.assertIn("project create", out)

    def test_start_with_a_project_but_no_key_asks_for_the_key(self):
        with mock.patch.object(cli, "Client") as client:
            client.return_value.request.return_value = {"projects": [{"id": "p1"}]}
            code, out, _ = self.run_cli("start", "--provider", "minimax")
        self.assertEqual(code, 0)
        self.assertIn("key set minimax", out)
        self.assertIn("minimax", out)

    def test_start_with_everything_present_says_it_is_ready(self):
        with mock.patch.object(cli, "Client") as client:
            client.return_value.request.return_value = {"projects": [{"id": "p1"}]}
            with mock.patch("cshcli.cli.getpass.getpass", return_value="sk-example"):
                self.run_cli("key", "set", "openai")
            code, out, _ = self.run_cli("start")
        self.assertEqual(code, 0)
        self.assertIn("Todo listo", out)

    def test_start_does_not_need_a_collaboration_token(self):
        with mock.patch.object(cli, "Client") as client:
            client.return_value.request.return_value = {"projects": []}
            code, _, _ = self.run_cli("start")
        self.assertEqual(code, 0)
        client.assert_called_once()
        self.assertIsNone(client.call_args[0][1])

    def test_start_reports_a_permission_error_instead_of_guessing(self):
        with mock.patch.object(cli, "Client") as client:
            client.return_value.request.side_effect = DomainError(
                401, "invalid_token", "No.")
            code, out, err = self.run_cli("start")
        self.assertEqual(code, 1)
        self.assertIn("invalid_token", err)
        self.assertEqual(out.strip(), "", "an error must not also print a next step")


if __name__ == "__main__":
    unittest.main()