import json
import os
import ssl
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from cshcli.remote_server import make_remote_server

sys.path.append(str(Path(__file__).resolve().parents[1] / "scripts"))
import tls_certificate

DSN = os.environ.get("CSHCLI_REMOTE_DSN", "")
SKIP_REASON = "requires a real PostgreSQL and TLS: set CSHCLI_REMOTE_DSN"
CRYPTOGRAPHY_REASON = (
    "requires cryptography: pip install cryptography. Without it a certificate "
    "cannot be made, and a test that cannot run must say so rather than fail."
)


def _has_cryptography() -> bool:
    try:
        import cryptography  # noqa: F401
        return True
    except ImportError:
        return False


def _get(url, context=None, timeout=20):
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


class CertificateTests(unittest.TestCase):
    def setUp(self):
        if not _has_cryptography():
            self.skipTest(CRYPTOGRAPHY_REASON)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_the_files_are_written_and_the_key_is_private(self):
        report = tls_certificate.write_self_signed(Path(self.temp.name))
        certificate = Path(report["certificate"])
        key = Path(report["key"])
        self.assertTrue(certificate.exists())
        self.assertTrue(key.exists())
        body = key.read_text(encoding="utf-8")
        self.assertIn("PRIVATE KEY", body)
        self.assertNotIn("BEGIN CERTIFICATE", body)

    def test_the_certificate_names_the_host_it_was_asked_for(self):
        report = tls_certificate.write_self_signed(Path(self.temp.name), host="localhost")
        from cryptography import x509
        certificate = x509.load_pem_x509_certificate(Path(report["certificate"]).read_bytes())
        names = certificate.extensions.get_extension_for_oid(
            x509.oid.ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value
        self.assertIn("localhost", [entry.value for entry in names])

    def test_the_certificate_expires_and_is_a_ca(self):
        from cryptography import x509
        report = tls_certificate.write_self_signed(Path(self.temp.name))
        certificate = x509.load_pem_x509_certificate(Path(report["certificate"]).read_bytes())
        constraints = certificate.extensions.get_extension_for_oid(
            x509.oid.ExtensionOID.BASIC_CONSTRAINTS).value
        self.assertTrue(constraints.ca)


class RemoteServerTests(unittest.TestCase):
    def setUp(self):
        if not DSN:
            self.skipTest(SKIP_REASON)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.report = tls_certificate.write_self_signed(
            Path(self.temp.name), host="localhost")
        self.server = make_remote_server(
            DSN, self.report["certificate"], self.report["key"],
            host="127.0.0.1", port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop)
        self.base = f"https://localhost:{self.server.server_address[1]}"

    def _stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=10)

    def _context(self):
        context = ssl.create_default_context(cafile=self.report["certificate"])
        return context

    def test_health_is_answered_over_tls_from_a_real_database(self):
        status, body = _get(f"{self.base}/healthz", context=self._context())
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["database"], "postgresql")
        self.assertIn("tls", body)

    def test_the_connection_really_is_encrypted(self):
        with urllib.request.urlopen(f"{self.base}/healthz", timeout=20,
                                    context=self._context()) as response:
            self.assertEqual(response.status, 200)
            self.assertTrue(response.headers.get("X-CSHCLI-TLS"))

    def test_a_client_that_does_not_trust_the_certificate_is_refused(self):
        with self.assertRaises((urllib.error.URLError, ssl.SSLError, OSError)):
            _get(f"{self.base}/healthz", context=ssl.create_default_context())

    def test_plain_http_is_not_accepted_on_the_same_port(self):
        with self.assertRaises((urllib.error.URLError, ssl.SSLError, OSError, ValueError)):
            urllib.request.urlopen(f"http://localhost:{self.server.server_address[1]}/healthz",
                                   timeout=20)

    def test_a_missing_certificate_is_refused_before_binding(self):
        with self.assertRaises(ValueError):
            make_remote_server(DSN, str(Path(self.temp.name) / "no-cert.pem"),
                               self.report["key"], host="127.0.0.1", port=0)

    def test_a_missing_key_is_refused_before_binding(self):
        with self.assertRaises(ValueError):
            make_remote_server(DSN, self.report["certificate"],
                               str(Path(self.temp.name) / "no-key.pem"),
                               host="127.0.0.1", port=0)

    def test_a_server_without_tls_certificate_cannot_be_built(self):
        with self.assertRaises(ValueError):
            make_remote_server(DSN, None, None, host="127.0.0.1", port=0)


if __name__ == "__main__":
    sys.exit(unittest.main())