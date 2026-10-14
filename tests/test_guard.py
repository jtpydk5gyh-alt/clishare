import importlib.util
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "guard_secrets.py"


def load_guard():
    spec = importlib.util.spec_from_file_location("guard_secrets", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = load_guard()


class GuardTests(unittest.TestCase):
    def write(self, name, text):
        path = Path(self.temp.name) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return str(path)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_the_noreply_address_is_the_only_allowed_email(self):
        self.assertEqual(guard.ALLOWED_EMAIL, "jtpydk5gyh-alt@users.noreply.github.com")

    def test_a_personal_email_is_flagged(self):
        name = self.write("doc.md", "contact: ana.lopez@correo-real.net\n")
        findings = guard.scan([name], "")
        self.assertTrue(any("correo" in label for _, _, label, _ in findings))

    def test_the_private_relay_address_is_flagged_explicitly(self):
        name = self.write("doc.md", "contact: jtpydk5gyh@privaterelay.appleid.com\n")
        findings = guard.scan([name], "")
        self.assertTrue(any("privada" in label for _, _, label, _ in findings))

    def test_the_noreply_address_is_not_flagged(self):
        name = self.write("doc.md", f"owner: {guard.ALLOWED_EMAIL}\n")
        self.assertEqual(guard.scan([name], ""), [])

    def test_reserved_example_domains_are_allowed(self):
        name = self.write("doc.md", "a@example.com b@example.invalid c@example.org d@remote.example\n")
        self.assertEqual(guard.scan([name], ""), [])

    def test_system_user_paths_are_flagged(self):
        for content in ("path: C:/Users/67gang/Documents\n",
                        "path: /home/67gang/project\n",
                        "path: /Users/67gang/project\n"):
            with self.subTest(content=content):
                name = self.write("doc.md", content)
                findings = guard.scan([name], "")
                self.assertTrue(any("ruta" in label for _, _, label, _ in findings))

    def test_tokens_and_private_keys_are_flagged(self):
        name = self.write("doc.md",
                          "key sk-abcdefghijklmnopqrstuvwxyz012345\ngh ghp_abcdefghijklmnopqrstuvwxyz012345\n"
                          "-----BEGIN RSA PRIVATE KEY-----\n")
        labels = [label for _, _, label, _ in guard.scan([name], "")]
        self.assertTrue(any("token" in label for label in labels))
        self.assertTrue(any("clave privada" in label for label in labels))

    def test_a_clean_file_produces_no_findings(self):
        name = self.write("doc.md", "# Title\n\nNormal prose with no personal data.\n")
        self.assertEqual(guard.scan([name], ""), [])

    def test_the_guard_exempts_only_its_own_test_file(self):
        self.assertEqual(guard.SELF_EXEMPT, {"tests/test_guard.py"})
        exempt = self.write(os.path.join("tests", "test_guard.py"),
                            "contact: jtpydk5gyh@privaterelay.appleid.com\n")
        self.assertEqual(guard.scan([exempt], ""), [])
        other = self.write(os.path.join("tests", "test_other.py"),
                           "contact: jtpydk5gyh@privaterelay.appleid.com\n")
        self.assertTrue(guard.scan([other], ""))

    def test_identity_findings_rejects_a_wrong_email(self):
        with mock.patch.object(guard.subprocess, "run") as run:
            run.side_effect = [
                type("R", (), {"stdout": "ana@gmail.com\n", "returncode": 0})(),
                type("R", (), {"stdout": "ana@gmail.com\n", "returncode": 0})(),
            ]
            problems = guard.identity_findings()
        self.assertEqual(len(problems), 2)
        self.assertIn(guard.ALLOWED_EMAIL, problems[0])

    def test_identity_findings_accepts_the_noreply_email(self):
        with mock.patch.object(guard.subprocess, "run") as run:
            run.side_effect = [
                type("R", (), {"stdout": guard.ALLOWED_EMAIL + "\n", "returncode": 0})(),
                type("R", (), {"stdout": guard.ALLOWED_EMAIL + "\n", "returncode": 0})(),
            ]
            self.assertEqual(guard.identity_findings(), [])


if __name__ == "__main__":
    unittest.main()