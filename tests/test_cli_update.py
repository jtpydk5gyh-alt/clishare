import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from cshcli import cli, updater


class CliUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = str(Path(self.temp.name))
        patcher = mock.patch.dict(os.environ, {"CSHCLI_HOME": self.home})
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_cli(self, *arguments, **keywords):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), mock.patch("builtins.input",
                                                                   **keywords):
            code = cli.main(list(arguments))
        return code, out.getvalue(), err.getvalue()

    def test_update_reports_and_changes_nothing(self):
        with mock.patch.object(updater, "newest_remote_version", return_value="v0.3.0"):
            code, out, err = self.run_cli("update")
        report = json.loads(out)
        self.assertEqual(report["action"], "update")
        self.assertIn("No se ha cambiado nada", err)
        self.assertEqual(code, 0)

    def test_update_never_asks_to_type_anything_without_apply(self):
        with mock.patch.object(updater, "newest_remote_version", return_value="v0.3.0"):
            with mock.patch("builtins.input") as prompt:
                code, _, _ = self.run_cli("update")
        prompt.assert_not_called()

    def test_a_wrong_typed_version_installs_nothing(self):
        with mock.patch.object(updater, "newest_remote_version", return_value="v0.3.0"):
            code, _, err = self.run_cli("update", "--apply", return_value="0.9.9")
        self.assertEqual(code, 1)
        self.assertIn("No coincide", err)
        self.assertFalse((Path(self.home) / "update").exists(),
                         "a refused confirmation must not download anything")

    def test_a_network_failure_touches_nothing(self):
        def broken():
            raise updater.UpdateUnavailable("GitHub could not be reached")
        with mock.patch.object(updater, "newest_remote_version", broken):
            code, out, err = self.run_cli("update")
        self.assertEqual(code, 1)
        self.assertEqual(out.strip(), "")
        self.assertIn("No se ha tocado nada", err)

    def test_apply_with_nothing_to_install_says_so_and_does_not_ask(self):
        with mock.patch.object(updater, "newest_remote_version", return_value=None):
            with mock.patch("builtins.input") as prompt:
                code, _, err = self.run_cli("update", "--apply")
        prompt.assert_not_called()
        self.assertEqual(code, 0)
        self.assertIn("No hay nada que instalar", err)

    def test_apply_when_current_says_so_and_does_not_ask(self):
        with mock.patch.object(updater, "newest_remote_version",
                               return_value=updater.current_version()):
            with mock.patch("builtins.input") as prompt:
                code, _, _ = self.run_cli("update", "--apply")
        prompt.assert_not_called()
        self.assertEqual(code, 0)

    def test_apply_downloads_and_verifies_before_installing(self):
        import hashlib
        payload = b"wheel-bytes"
        digest = hashlib.sha256(payload).hexdigest()
        expected = Path(self.home) / "update" / "cshcli-0.3.0.whl"
        with mock.patch.object(updater, "newest_remote_version", return_value="v0.3.0"):
            with mock.patch.object(updater, "fetch_checksums",
                                   return_value={"cshcli-0.3.0.whl": digest}):
                with mock.patch.object(updater, "download") as download:
                    def fake_download(url, target):
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(payload)
                        return target
                    download.side_effect = fake_download
                    with mock.patch.object(updater, "install") as installer:
                        installer.return_value = {"installed": "ok"}
                        code, out, _ = self.run_cli("update", "--apply", return_value="v0.3.0")
        self.assertEqual(code, 0)
        download.assert_called_once()
        installer.assert_called_once()
        self.assertEqual(installer.call_args[0][0], expected)
        self.assertEqual(installer.call_args[0][1], digest)

    def test_apply_without_published_checksums_installs_nothing(self):
        with mock.patch.object(updater, "newest_remote_version", return_value="v0.3.0"):
            with mock.patch.object(updater, "fetch_checksums", return_value={}):
                with mock.patch.object(updater, "install") as installer:
                    code, _, err = self.run_cli("update", "--apply", return_value="v0.3.0")
        installer.assert_not_called()
        self.assertEqual(code, 1)
        self.assertIn("No se instaló", err)

    def test_apply_stops_when_the_download_fails(self):
        with mock.patch.object(updater, "newest_remote_version", return_value="v0.3.0"):
            with mock.patch.object(updater, "fetch_checksums",
                                   return_value={"cshcli-0.3.0.whl": "0" * 64}):
                with mock.patch.object(updater, "download",
                                       side_effect=updater.UpdateUnavailable("no")):
                    with mock.patch.object(updater, "install") as installer:
                        code, _, err = self.run_cli("update", "--apply", return_value="v0.3.0")
        installer.assert_not_called()
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()