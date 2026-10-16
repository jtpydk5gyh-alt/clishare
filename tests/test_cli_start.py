import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from cshcli import cli


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

    def test_start_is_the_default_when_no_command_is_given(self):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("builtins.input", side_effect=EOFError), \
             redirect_stdout(out), redirect_stderr(err):
            code = cli.main([])
        self.assertEqual(code, 1)
        self.assertIn("input_required", err.getvalue())


if __name__ == "__main__":
    unittest.main()