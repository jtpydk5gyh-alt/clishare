import tempfile
import unittest
from pathlib import Path

from cshcli.errors import DomainError
from cshcli.knowledge import index_text, is_secret, note_text


class SecretNameTests(unittest.TestCase):
    def test_the_usual_credential_files_are_recognised(self):
        for name in (".env", ".env.local", ".netrc", ".npmrc", ".pypirc",
                     "credentials.json", "service-account.json", "id_rsa",
                     "server.key", "server.pem", "server.crt", "server.p12",
                     "server.pfx", "vault.keystore", "notes_PRIVATE.md",
                     "secret.asc", ".htpasswd"):
            with self.subTest(name=name):
                self.assertTrue(is_secret(name), f"{name} debe tratarse como secreto")

    def test_an_environment_example_is_not_a_secret(self):
        for name in (".env.example", "env.py", "keys.py", "keyboard.py",
                     "README.md", "src/cshcli/cli.py"):
            with self.subTest(name=name):
                self.assertFalse(is_secret(name), f"{name} es codigo normal")


class IndexHidesSecretsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / ".env").write_text("OPENAI_API_KEY=sk-real\n", encoding="utf-8")
        (self.root / "credentials.json").write_text('{"k":"s"}\n', encoding="utf-8")
        (self.root / "server.key").write_text("PRIVATE KEY\n", encoding="utf-8")
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
        (self.root / "README.md").write_text("# Aqui\n", encoding="utf-8")

    def test_the_index_never_announces_a_credential_file(self):
        text = index_text(self.root)
        for secret in (".env", "credentials.json", "server.key"):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, text)
        self.assertIn("src/app.py", text)

    def test_a_credential_file_cannot_be_read_through_the_chat(self):
        for secret in (".env", "credentials.json", "server.key", ".netrc"):
            with self.subTest(secret=secret):
                with self.assertRaises(DomainError) as caught:
                    note_text(self.root, secret)
                self.assertEqual(caught.exception.code, "secret_refused")

    def test_a_hidden_secret_cannot_be_reached_by_escaping_into_its_folder(self):
        (self.root / "src" / ".env").write_text("TOKEN=sk\n", encoding="utf-8")
        self.assertNotIn(".env", index_text(self.root))
        with self.assertRaises(DomainError) as caught:
            note_text(self.root, "src/.env")
        self.assertEqual(caught.exception.code, "secret_refused")

    def test_ordinary_source_is_still_readable(self):
        self.assertIn("print('ok')", note_text(self.root, "src/app.py"))


if __name__ == "__main__":
    unittest.main()