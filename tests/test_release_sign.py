import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "scripts"))
import release

MINISIGN = Path(os.path.expanduser("~")) / "cshcli-tools" / "bin" / "minisign-win64" / "x86_64" / "minisign.exe"
SKIP_REASON = ("requires minisign: the release is unsigned without it, and that is "
               "reported rather than hidden")


def _minisign():
    return MINISIGN if MINISIGN.exists() else (shutil.which("minisign"))


class SignatureAvailabilityTests(unittest.TestCase):
    def test_without_a_signer_the_release_says_it_is_unsigned(self):
        signer = None
        report = release.signature_report(signer, None)
        self.assertFalse(report["signed"])
        self.assertEqual(report["reason"], "no_signer")

    def test_without_a_key_the_release_says_it_is_unsigned(self):
        signer = "minisign"
        report = release.signature_report(signer, None)
        self.assertFalse(report["signed"])
        self.assertEqual(report["reason"], "no_key")

    def test_a_signer_and_a_key_are_both_needed(self):
        self.assertFalse(release.signature_report("minisign", "key")["signed"]
                         if not Path("key").exists() else False)

    def test_the_environment_variable_is_the_only_source_of_the_key(self):
        os.environ.pop("CSHCLI_SIGNING_KEY", None)
        self.assertEqual(release.signing_key_from_environment(), None)
        os.environ["CSHCLI_SIGNING_KEY"] = "/tmp/x.key"
        self.addCleanup(os.environ.pop, "CSHCLI_SIGNING_KEY", None)
        self.assertEqual(release.signing_key_from_environment(), Path("/tmp/x.key"))


class RealSigningTests(unittest.TestCase):
    def setUp(self):
        self.signer = _minisign()
        if not self.signer:
            self.skipTest(SKIP_REASON)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.key = self.root / "prueba.key"
        self.public = self.root / "prueba.pub"
        self.sums = self.root / "SHA256SUMS"
        self.sums.write_text("a" * 64 + "  cshcli-0.9.0.whl\n", encoding="utf-8")
        generated = subprocess.run([str(self.signer), "-G", "-W", "-p", str(self.public),
                                    "-s", str(self.key)],
                                   cwd=self.root, capture_output=True, text=True)
        self.assertEqual(generated.returncode, 0, generated.stderr)

    def test_the_checksum_file_gets_signed_and_verified(self):
        report = release.sign(str(self.sums), str(self.signer), str(self.key))
        self.assertTrue(report["signed"], report)
        self.assertTrue((self.root / "SHA256SUMS.minisig").exists())

    def test_a_tampered_checksum_file_fails_verification(self):
        release.sign(str(self.sums), str(self.signer), str(self.key))
        self.sums.write_text("b" * 64 + "  cshcli-0.9.0.whl\n", encoding="utf-8")
        report = release.verify_signature(str(self.sums), str(self.signer),
                                          str(self.public))
        self.assertFalse(report["valid"])

    def test_a_signature_by_another_key_is_refused(self):
        release.sign(str(self.sums), str(self.signer), str(self.key))
        other_public = self.root / "otro.pub"
        other_key = self.root / "otro.key"
        subprocess.run([str(self.signer), "-G", "-W", "-p", str(other_public),
                        "-s", str(other_key)], cwd=self.root, capture_output=True)
        report = release.verify_signature(str(self.sums), str(self.signer),
                                          str(other_public))
        self.assertFalse(report["valid"])

    def test_signing_without_a_key_is_refused_rather_than_silently_skipped(self):
        with self.assertRaises(release.ReleaseRefused):
            release.sign(str(self.sums), str(self.signer), str(self.root / "no-existe.key"))


if __name__ == "__main__":
    sys.exit(unittest.main())