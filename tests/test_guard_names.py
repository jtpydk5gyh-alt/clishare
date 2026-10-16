import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))
import guard_secrets as guard
from cshcli.knowledge import is_secret


class CredentialNameTests(unittest.TestCase):
    NAMES = (".env", ".env.local", ".netrc", ".npmrc", ".pypirc", ".htpasswd",
             "credentials.json", "service-account.json", "id_rsa", "id_ed25519",
             "known_hosts", "notes_PRIVATE.md")
    SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".crt", ".keystore", ".asc",
                ".ppk", ".jks")

    def test_a_credential_file_is_flagged_by_its_name(self):
        for name in self.NAMES:
            with self.subTest(name=name):
                self.assertTrue(guard.is_credential_file(name),
                                f"{name} debe rechazarse por su nombre")

    def test_a_credential_file_is_flagged_by_its_suffix(self):
        for suffix in self.SUFFIXES:
            with self.subTest(suffix=suffix):
                self.assertTrue(guard.is_credential_file("servidor" + suffix))

    def test_ordinary_source_is_not_a_credential(self):
        for name in (".env.example", "keys.py", "keyboard.py", "credential_manager.py",
                     "README.md", "src/cshcli/cli.py", "docs/STATUS.md"):
            with self.subTest(name=name):
                self.assertFalse(guard.is_credential_file(name))


class TheTwoListsMustAgreeTests(unittest.TestCase):
    def test_everything_the_chat_refuses_the_guard_also_refuses(self):
        for name in (".env", ".env.local", ".netrc", ".npmrc", ".pypirc",
                     "credentials.json", "service-account.json", "id_rsa",
                     "id_ecdsa", "id_ed25519", ".htpasswd", "known_hosts",
                     "notes_PRIVATE.md", "vault.jks", "key.ppk",
                     "release.asc", "server.pem", "server.key", "server.crt"):
            with self.subTest(name=name):
                self.assertTrue(is_secret(name), f"{name}: el chat lo trata como secreto")
                self.assertTrue(guard.is_credential_file(name),
                                f"{name}: el guard no lo rechaza y el chat si")


class RealRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True,
                       capture_output=True)
        subprocess.run(["git", "config", "user.email", guard.ALLOWED_EMAIL],
                       cwd=self.root, check=True, capture_output=True)

    def stage(self, name, payload):
        (self.root / name).write_bytes(payload)
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True,
                       capture_output=True)

    def scan(self):
        return subprocess.run([sys.executable, str(Path(guard.__file__).resolve())],
                              cwd=self.root, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")

    def test_a_netrc_with_a_password_is_refused(self):
        self.stage(".netrc", b"machine example.com login ana password hunter2\n")
        result = self.scan()
        self.assertEqual(result.returncode, 1,
                         "un .netrc con contrasena se puede commitear")

    def test_a_npmrc_with_a_token_is_refused(self):
        self.stage(".npmrc", b"//registry.npmjs.org/:_authToken=npm_000000000000\n")
        self.assertEqual(self.scan().returncode, 1)

    def test_a_binary_keystore_is_refused_even_without_a_readable_marker(self):
        self.stage("wallet.jks", b"\x00\x01\x02binary keystore\xff")
        result = self.scan()
        self.assertEqual(result.returncode, 1)
        self.assertIn("wallet.jks", result.stdout)

    def test_ordinary_files_still_pass(self):
        self.stage("app.py", b"print('hola')\n")
        self.assertEqual(self.scan().returncode, 0)

    def test_an_env_example_is_not_a_secret(self):
        self.stage(".env.example", b"OPENAI_API_KEY=sk-ejemplo\n")
        self.assertEqual(self.scan().returncode, 0)


if __name__ == "__main__":
    unittest.main()