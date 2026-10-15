import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from cshcli import cli


class ServeRemoteTests(unittest.TestCase):
    def run_cli(self, *arguments):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(list(arguments))
        return code, out.getvalue(), err.getvalue()

    def setUp(self):
        for variable in ("CSHCLI_REMOTE_DSN", "CSHCLI_TLS_CERT", "CSHCLI_TOKEN"):
            os.environ.pop(variable, None)

    def test_without_configuration_it_refuses_and_names_what_is_missing(self):
        code, out, err = self.run_cli("serve", "--remote")
        report = json.loads(out)
        self.assertEqual(code, 1)
        self.assertFalse(report["started"])
        self.assertIn("CSHCLI_REMOTE_DSN", report["missing"])
        self.assertIn("CSHCLI_TLS_CERT", report["missing"])
        self.assertIn("OPERATIONS.md", err)

    def test_a_dsn_that_is_not_postgresql_is_refused(self):
        os.environ["CSHCLI_REMOTE_DSN"] = "sqlite:///tmp/x.sqlite3"
        os.environ["CSHCLI_TLS_CERT"] = "cert.pem"
        code, out, _ = self.run_cli("serve", "--remote")
        report = json.loads(out)
        self.assertEqual(code, 1)
        self.assertIn("a PostgreSQL DSN", report["missing"])

    def test_no_certificate_is_refused_even_with_a_database(self):
        os.environ["CSHCLI_REMOTE_DSN"] = "postgresql://user@host/db"
        code, out, _ = self.run_cli("serve", "--remote")
        report = json.loads(out)
        self.assertEqual(code, 1)
        self.assertIn("CSHCLI_TLS_CERT", report["missing"])
        self.assertFalse(report["started"],
                         "a remote coordinator without TLS must never start")

    def test_it_never_reports_itself_started_without_a_database(self):
        os.environ["CSHCLI_REMOTE_DSN"] = "postgresql://user@host/db"
        os.environ["CSHCLI_TLS_CERT"] = "cert.pem"
        code, out, _ = self.run_cli("serve", "--remote")
        report = json.loads(out)
        self.assertFalse(report["started"],
                         "this machine has no PostgreSQL; it must not claim to start one")
        self.assertEqual(report["database"], "postgresql")

    def test_plain_serve_still_works_as_before(self):
        with mock.patch("cshcli.cli.make_server") as make:
            make.return_value.server_port = 8765
            with mock.patch("cshcli.cli.Coordinator", create=True):
                out, err = io.StringIO(), io.StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    code = cli.main(["serve", "--db", "x.sqlite3"])
        self.assertEqual(code, 0)
        make.assert_called_once()


if __name__ == "__main__":
    unittest.main()